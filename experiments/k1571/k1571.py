"""K1571 — Baseline audit for deep quantile VaR estimators.

Stage 1 of the deep quantile VaR fairness investigation. We benchmark four
*classical* quantile / VaR estimators on TLT and HYG daily returns to
establish what a fair high-dimensional covariate baseline buys, before any
DNN gets introduced. The DNN comparison is deferred to a compute_queue run
that uses the SAME covariate set produced here.

Assets: TLT (iShares 20+ Year Treasury), HYG (iShares iBoxx High Yield).
Topic-cluster compliance: SPY/QQQ/VIX cannot be the dependent. VIX is allowed
as a lagged covariate; SPY/QQQ are NOT used at all.

Covariates (all t-1 lagged via signal.shift(1)):
  - own asset 5-day realized vol  (rolling std of log returns * sqrt(252))
  - IEF 5-day momentum
  - LQD 5-day momentum
  - credit-spread proxy: 5-day change in HYG/IEF close ratio
  - VIX level (lagged)

Models:
  1. Historical Simulation HS-250        (rolling 250-day empirical quantile)
  2. Linear Quantile Regression          (statsmodels QuantReg, all covariates)
  3. CAViaR Symmetric Absolute Value     (Engle-Manganelli 2004)
  4. HAR-Quantile                        (QuantReg on RV_d / RV_w / RV_m)

OOS window: 2015-01-01 .. 2026-06-26 (≥ 11 years, ~2900 daily obs / asset).
Refit cadence: monthly expanding window for parametric models. HS rolls daily.
Targets:       VaR(5%) and VaR(1%).

Evaluation: pinball loss, Kupiec POF, Christoffersen independence, DM tests
(HAC SE, Newey-West lag = floor(1.5 * n^{1/3})).

All seeds fixed to 1571.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from scipy.optimize import minimize
from statsmodels.regression.quantile_regression import QuantReg

warnings.simplefilter("ignore", category=RuntimeWarning)

SEED = 1571
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_CACHE = HERE / "data_cache.parquet"


# -----------------------------------------------------------------------------
# Data
# -----------------------------------------------------------------------------
TICKERS = ["TLT", "HYG", "IEF", "LQD", "^VIX"]
START = "2010-01-01"
END = "2026-06-27"


def fetch_data(force: bool = False) -> pd.DataFrame:
    if DATA_CACHE.exists() and not force:
        return pd.read_parquet(DATA_CACHE)
    import yfinance as yf

    df = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
    )["Close"]
    df = df.dropna(how="any").sort_index()
    df.to_parquet(DATA_CACHE)
    return df


# -----------------------------------------------------------------------------
# Feature engineering
# -----------------------------------------------------------------------------
def build_panel(close: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Build a single-asset feature panel with strict t-1 lagging.

    All forecast features come from data observed AT OR BEFORE day t-1 and
    are then `.shift(1)` so they line up with the day-t return. The target
    (r_t) is left unlagged.
    """
    logret = np.log(close).diff()
    own_ret = logret[asset]

    # Realized vol features (causal: use returns up to and including t-1).
    rv5 = own_ret.rolling(5).std() * np.sqrt(252)
    rv_d = own_ret.abs()  # |r_t| as daily |return| proxy for HAR-Q
    rv_w = own_ret.rolling(5).std()
    rv_m = own_ret.rolling(22).std()

    # Macro covariates.
    ief_mom = logret["IEF"].rolling(5).sum()
    lqd_mom = logret["LQD"].rolling(5).sum()
    credit_ratio = (close["HYG"] / close["IEF"])
    credit_chg = credit_ratio.pct_change(5)
    vix = close["^VIX"]

    feats = pd.DataFrame(
        {
            "rv5": rv5,
            "ief_mom": ief_mom,
            "lqd_mom": lqd_mom,
            "credit_chg": credit_chg,
            "vix": vix,
            "rv_d": rv_d,
            "rv_w": rv_w,
            "rv_m": rv_m,
        },
        index=close.index,
    ).shift(1)  # <-- the canonical t-1 lag

    df = pd.concat([own_ret.rename("y"), feats], axis=1).dropna()
    return df


# -----------------------------------------------------------------------------
# CAViaR symmetric absolute value (Engle & Manganelli 2004)
# -----------------------------------------------------------------------------
def _quantile_loss(q: np.ndarray, y: np.ndarray, alpha: float) -> float:
    """Pinball / tick loss; q is the VaR forecast (negative for losses)."""
    e = y - q
    return float(np.mean(np.where(e >= 0, alpha * e, (alpha - 1.0) * e)))


def _caviar_recursion(
    params: np.ndarray, y: np.ndarray, alpha: float, q0: float
) -> np.ndarray:
    """VaR_t = b0 + b1 * |y_{t-1}| + b2 * VaR_{t-1}."""
    b0, b1, b2 = params
    n = len(y)
    q = np.empty(n)
    q[0] = q0
    for t in range(1, n):
        q[t] = b0 + b1 * abs(y[t - 1]) + b2 * q[t - 1]
    return q


def fit_caviar(y_train: np.ndarray, alpha: float, n_starts: int = 6) -> np.ndarray:
    """Fit CAViaR-SAV by minimizing the pinball loss with multi-start."""
    q0 = float(np.quantile(y_train[:250], alpha))  # warm start
    rng = np.random.default_rng(SEED)
    best = (np.inf, None)

    starts = [
        np.array([q0 * 0.2, -0.05 if alpha < 0.5 else 0.05, 0.9]),
        np.array([q0 * 0.1, -0.1 if alpha < 0.5 else 0.1, 0.85]),
        np.array([0.0, 0.0, 0.95]),
    ]
    for _ in range(max(0, n_starts - len(starts))):
        starts.append(
            np.array(
                [
                    q0 * rng.uniform(0.0, 0.4),
                    rng.uniform(-0.2, 0.2),
                    rng.uniform(0.6, 0.98),
                ]
            )
        )

    def obj(params: np.ndarray) -> float:
        q = _caviar_recursion(params, y_train, alpha, q0)
        return _quantile_loss(q, y_train, alpha)

    for x0 in starts:
        try:
            res = minimize(
                obj,
                x0,
                method="Nelder-Mead",
                options={"xatol": 1e-5, "fatol": 1e-7, "maxiter": 2000},
            )
            if res.fun < best[0]:
                best = (res.fun, res.x)
        except Exception:
            continue
    return best[1] if best[1] is not None else starts[0]


def caviar_forecast_step(
    params: np.ndarray, y_prev: float, q_prev: float
) -> float:
    b0, b1, b2 = params
    return float(b0 + b1 * abs(y_prev) + b2 * q_prev)


# -----------------------------------------------------------------------------
# Backtest engines
# -----------------------------------------------------------------------------
@dataclass
class ForecastSeries:
    name: str
    var: pd.Series       # VaR forecast (negative numbers in loss space)
    loss: pd.Series      # pointwise pinball loss
    violations: pd.Series  # 1[r_t < VaR_t]


OOS_START = pd.Timestamp("2015-01-01")


def _refit_dates(index: pd.DatetimeIndex) -> List[pd.Timestamp]:
    """Pick the first OOS date of each calendar month."""
    dates: List[pd.Timestamp] = []
    last_ym = None
    for ts in index:
        if ts < OOS_START:
            continue
        ym = (ts.year, ts.month)
        if ym != last_ym:
            dates.append(ts)
            last_ym = ym
    return dates


def run_hs(panel: pd.DataFrame, alpha: float, win: int = 250) -> ForecastSeries:
    """Historical simulation: rolling empirical quantile of *past* returns.

    The rolling window ends at t-1, so VaR_t uses only returns y_{t-win..t-1}.
    """
    y = panel["y"]
    # shift(1) so the rolling window is closed BEFORE day t.
    var = y.shift(1).rolling(win).quantile(alpha)
    df = pd.concat([y, var.rename("var")], axis=1).dropna()
    df = df[df.index >= OOS_START]
    loss = df.apply(
        lambda r: alpha * (r["y"] - r["var"]) if (r["y"] - r["var"]) >= 0 else (alpha - 1.0) * (r["y"] - r["var"]),
        axis=1,
    )
    violations = (df["y"] < df["var"]).astype(int)
    return ForecastSeries(
        name=f"HS{win}", var=df["var"], loss=loss, violations=violations
    )


def run_quantreg(
    panel: pd.DataFrame, alpha: float, feats: List[str], name: str
) -> ForecastSeries:
    """Monthly-refit expanding-window linear quantile regression."""
    df = panel.dropna()
    refit_dates = _refit_dates(df.index)
    var = pd.Series(index=df.index, dtype=float)

    # initial fit using everything strictly before OOS_START
    train = df[df.index < OOS_START]
    if len(train) < 200:
        raise ValueError(f"Insufficient pre-OOS data: {len(train)}")

    model = _fit_quantreg(train, feats, alpha)
    for i in range(len(df)):
        ts = df.index[i]
        if ts < OOS_START:
            continue
        if ts in refit_dates and ts != refit_dates[0]:
            train = df[df.index < ts]
            model = _fit_quantreg(train, feats, alpha)
        x = df.loc[ts, feats].values
        var.loc[ts] = float(model[0] + np.dot(x, model[1:]))

    var = var.dropna()
    y = df.loc[var.index, "y"]
    loss = (y - var).apply(lambda e: alpha * e if e >= 0 else (alpha - 1.0) * e)
    violations = (y < var).astype(int)
    return ForecastSeries(name=name, var=var, loss=loss, violations=violations)


def _fit_quantreg(train: pd.DataFrame, feats: List[str], alpha: float) -> np.ndarray:
    X = train[feats].values
    y = train["y"].values
    X1 = np.column_stack([np.ones(len(y)), X])
    try:
        mod = QuantReg(y, X1).fit(q=alpha, max_iter=2000)
        return np.asarray(mod.params)
    except Exception:
        # Fallback: empirical quantile + zeros
        return np.array([np.quantile(y, alpha)] + [0.0] * len(feats))


def run_caviar(panel: pd.DataFrame, alpha: float) -> ForecastSeries:
    """Monthly-refit CAViaR-SAV; rolling forecast inside the month."""
    df = panel.dropna()
    refit_dates = _refit_dates(df.index)

    train = df[df.index < OOS_START]
    if len(train) < 500:
        raise ValueError(f"Insufficient pre-OOS data for CAViaR: {len(train)}")

    params = fit_caviar(train["y"].values, alpha)
    # Seed q_prev with the in-sample fit so the recursive state is consistent.
    q_in = _caviar_recursion(params, train["y"].values, alpha, np.quantile(train["y"].values[:250], alpha))
    q_prev = q_in[-1]
    y_prev = train["y"].iloc[-1]

    var = pd.Series(index=df.index, dtype=float)
    oos = df[df.index >= OOS_START]
    for ts in oos.index:
        if ts in refit_dates and ts != refit_dates[0]:
            train = df[df.index < ts]
            params = fit_caviar(train["y"].values, alpha)
            # Re-seed state by replaying recursion over training history.
            q_in = _caviar_recursion(
                params,
                train["y"].values,
                alpha,
                np.quantile(train["y"].values[:250], alpha),
            )
            q_prev = q_in[-1]
            y_prev = train["y"].iloc[-1]
        var.loc[ts] = caviar_forecast_step(params, y_prev, q_prev)
        q_prev = var.loc[ts]
        y_prev = df.loc[ts, "y"]

    var = var.dropna()
    y = df.loc[var.index, "y"]
    loss = (y - var).apply(lambda e: alpha * e if e >= 0 else (alpha - 1.0) * e)
    violations = (y < var).astype(int)
    return ForecastSeries(name="CAViaR-SAV", var=var, loss=loss, violations=violations)


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------
def kupiec_pof(violations: pd.Series, alpha: float) -> Dict[str, float]:
    n = int(len(violations))
    x = int(violations.sum())
    if n == 0:
        return {"n": 0, "violations": 0, "rate": float("nan"), "stat": float("nan"), "p": float("nan")}
    pi_hat = x / n if n > 0 else 0.0
    p = alpha
    if x == 0 or x == n:
        # boundary: log(0) -> handle via direct chi-sq comparison.
        # Likelihood under null only.
        ll0 = x * math.log(p) + (n - x) * math.log(1 - p)
        ll1 = -np.inf  # degenerate
        stat = -2 * (ll0 - 0.0)  # rough boundary
    else:
        ll0 = x * math.log(p) + (n - x) * math.log(1 - p)
        ll1 = x * math.log(pi_hat) + (n - x) * math.log(1 - pi_hat)
        stat = -2.0 * (ll0 - ll1)
    pval = float(1.0 - stats.chi2.cdf(stat, df=1))
    return {
        "n": n,
        "violations": x,
        "rate": float(pi_hat),
        "expected_rate": float(p),
        "stat": float(stat),
        "p": pval,
    }


def christoffersen_independence(violations: pd.Series) -> Dict[str, float]:
    v = violations.values.astype(int)
    if len(v) < 2:
        return {"stat": float("nan"), "p": float("nan")}
    n00 = n01 = n10 = n11 = 0
    for i in range(1, len(v)):
        a, b = v[i - 1], v[i]
        if a == 0 and b == 0:
            n00 += 1
        elif a == 0 and b == 1:
            n01 += 1
        elif a == 1 and b == 0:
            n10 += 1
        else:
            n11 += 1
    n0 = n00 + n01
    n1 = n10 + n11
    if n0 == 0 or n1 == 0 or (n01 + n11) == 0 or (n00 + n10) == 0:
        return {
            "n00": n00, "n01": n01, "n10": n10, "n11": n11,
            "stat": float("nan"), "p": float("nan"),
        }
    pi01 = n01 / n0
    pi11 = n11 / n1
    pi = (n01 + n11) / (n0 + n1)

    def safe_log(x):
        return math.log(x) if x > 0 else 0.0

    ll_null = (
        (n00 + n10) * safe_log(1 - pi) + (n01 + n11) * safe_log(pi)
    )
    ll_alt = (
        n00 * safe_log(1 - pi01)
        + n01 * safe_log(pi01)
        + n10 * safe_log(1 - pi11)
        + n11 * safe_log(pi11)
    )
    stat = -2.0 * (ll_null - ll_alt)
    pval = float(1.0 - stats.chi2.cdf(stat, df=1))
    return {
        "n00": n00, "n01": n01, "n10": n10, "n11": n11,
        "stat": float(stat), "p": pval,
    }


def dm_test_hac(loss_a: pd.Series, loss_b: pd.Series, h: int = 1) -> Dict[str, float]:
    """Diebold-Mariano with Newey-West HAC SE.

    H0: E[loss_a - loss_b] = 0. Negative dbar means model A is better.
    """
    d = (loss_a - loss_b).dropna()
    n = len(d)
    if n < 30:
        return {"n": n, "dbar": float("nan"), "stat": float("nan"), "p": float("nan")}
    dv = d.values
    dbar = float(dv.mean())
    # Newey-West lag selection
    L = max(1, int(np.floor(1.5 * n ** (1.0 / 3.0))))
    g0 = float(np.mean((dv - dbar) ** 2))
    var = g0
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1.0)
        cov = float(np.mean((dv[lag:] - dbar) * (dv[:-lag] - dbar)))
        var += 2.0 * w * cov
    if var <= 0:
        return {"n": n, "dbar": dbar, "stat": float("nan"), "p": float("nan")}
    se = math.sqrt(var / n)
    stat = dbar / se
    # Harvey-Leybourne-Newbold small-sample correction (h=1 -> factor=1)
    hln = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n) if h > 1 else 1.0
    stat_adj = stat * hln
    p = float(2.0 * (1.0 - stats.t.cdf(abs(stat_adj), df=n - 1)))
    return {"n": n, "dbar": dbar, "se": se, "stat": float(stat_adj), "p": p, "L": L}


# -----------------------------------------------------------------------------
# Plots
# -----------------------------------------------------------------------------
def plot_cumulative_loss(
    by_asset_alpha: Dict[Tuple[str, float], Dict[str, ForecastSeries]],
    out: Path,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=False)
    assets = sorted({a for a, _ in by_asset_alpha})
    alphas = sorted({al for _, al in by_asset_alpha})
    for i, asset in enumerate(assets):
        for j, alpha in enumerate(alphas):
            ax = axes[i, j]
            d = by_asset_alpha[(asset, alpha)]
            for name, fs in d.items():
                ax.plot(fs.loss.index, fs.loss.cumsum(), label=name, lw=1.1)
            ax.set_title(f"{asset}  VaR({int(alpha*100)}%)  cumulative pinball loss")
            ax.legend(fontsize=8, loc="upper left")
            ax.grid(alpha=0.3)
    fig.suptitle("K1571 baseline quantile VaR — cumulative pinball loss", y=1.01)
    fig.tight_layout()
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_violations(
    by_asset_alpha: Dict[Tuple[str, float], Dict[str, ForecastSeries]],
    out: Path,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=False)
    assets = sorted({a for a, _ in by_asset_alpha})
    alphas = sorted({al for _, al in by_asset_alpha})
    for i, asset in enumerate(assets):
        for j, alpha in enumerate(alphas):
            ax = axes[i, j]
            d = by_asset_alpha[(asset, alpha)]
            # rolling 250-day violation rate per model
            for name, fs in d.items():
                rate = fs.violations.rolling(250).mean()
                ax.plot(rate.index, rate, label=name, lw=1.0)
            ax.axhline(alpha, color="k", ls="--", lw=0.8, label=f"target {alpha:.0%}")
            ax.set_title(f"{asset}  VaR({int(alpha*100)}%)  rolling 250d violation rate")
            ax.legend(fontsize=8, loc="upper right")
            ax.grid(alpha=0.3)
    fig.suptitle("K1571 — rolling 250d violation rate vs target", y=1.01)
    fig.tight_layout()
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------
LINEAR_QR_FEATS = ["rv5", "ief_mom", "lqd_mom", "credit_chg", "vix"]
HARQ_FEATS = ["rv_d", "rv_w", "rv_m"]


def run_one(asset: str, alpha: float, panel: pd.DataFrame) -> Dict[str, ForecastSeries]:
    out: Dict[str, ForecastSeries] = {}
    out["HS250"] = run_hs(panel, alpha, win=250)
    out["LinearQR"] = run_quantreg(panel, alpha, LINEAR_QR_FEATS, "LinearQR")
    out["HARQ"] = run_quantreg(panel, alpha, HARQ_FEATS, "HARQ")
    out["CAViaR-SAV"] = run_caviar(panel, alpha)
    # Align all series to the common OOS index (= LinearQR/HARQ start, the latest one).
    common = None
    for fs in out.values():
        common = fs.loss.index if common is None else common.intersection(fs.loss.index)
    for k in out:
        fs = out[k]
        out[k] = ForecastSeries(
            name=fs.name,
            var=fs.var.loc[common],
            loss=fs.loss.loc[common],
            violations=fs.violations.loc[common],
        )
    return out


def summarize(forecasts: Dict[str, ForecastSeries], alpha: float) -> Dict:
    rows = {}
    pairs = [
        ("LinearQR", "HS250"),
        ("CAViaR-SAV", "HS250"),
        ("HARQ", "HS250"),
        ("HARQ", "LinearQR"),
        ("HARQ", "CAViaR-SAV"),
        ("LinearQR", "CAViaR-SAV"),
    ]
    dm_results = {}
    for a, b in pairs:
        dm_results[f"{a}_vs_{b}"] = dm_test_hac(forecasts[a].loss, forecasts[b].loss)

    for name, fs in forecasts.items():
        rows[name] = {
            "mean_pinball": float(fs.loss.mean()),
            "sum_pinball": float(fs.loss.sum()),
            "kupiec": kupiec_pof(fs.violations, alpha),
            "christoffersen_ind": christoffersen_independence(fs.violations),
            "obs": int(len(fs.loss)),
        }
    return {"per_model": rows, "dm_pairs": dm_results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-fetch", action="store_true")
    parser.add_argument("--quick", action="store_true", help="dev shortcut; reduces CAViaR multi-start")
    args = parser.parse_args()

    close = fetch_data(force=args.force_fetch)
    print(f"[data] rows={len(close)} from {close.index.min().date()} to {close.index.max().date()}")

    results: Dict = {
        "meta": {
            "experiment_id": "k1571",
            "seed": SEED,
            "data_start": str(close.index.min().date()),
            "data_end": str(close.index.max().date()),
            "oos_start": "2015-01-01",
            "assets_dependent": ["TLT", "HYG"],
            "assets_excluded_per_topic_cluster": ["SPY", "QQQ", "VIX"],  # VIX used as covariate only
            "covariates_linear_qr": LINEAR_QR_FEATS,
            "covariates_harq": HARQ_FEATS,
            "refit_cadence": "monthly_expanding",
            "alphas": [0.05, 0.01],
            "models": ["HS250", "LinearQR", "HARQ", "CAViaR-SAV"],
        }
    }
    by_asset_alpha: Dict[Tuple[str, float], Dict[str, ForecastSeries]] = {}

    for asset in ["TLT", "HYG"]:
        panel = build_panel(close, asset)
        print(f"[panel] {asset} rows={len(panel)} first={panel.index.min().date()} last={panel.index.max().date()}")
        results.setdefault("panels", {})[asset] = {
            "rows": int(len(panel)),
            "first": str(panel.index.min().date()),
            "last": str(panel.index.max().date()),
        }
        for alpha in (0.05, 0.01):
            print(f"[run] asset={asset} alpha={alpha}")
            forecasts = run_one(asset, alpha, panel)
            by_asset_alpha[(asset, alpha)] = forecasts
            summary = summarize(forecasts, alpha)
            results.setdefault("by_asset_alpha", {})[f"{asset}_{int(alpha*100):02d}"] = summary
            for name, fs in forecasts.items():
                print(
                    f"   {name:10s} obs={len(fs.loss):4d} mean_pl={fs.loss.mean():.5f} "
                    f"viol_rate={fs.violations.mean():.4f} (target {alpha:.3f})"
                )

    out_json = HERE / "k1571_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[write] {out_json}")

    plot_cumulative_loss(by_asset_alpha, HERE / "fig_quantile_loss_compare.png")
    plot_violations(by_asset_alpha, HERE / "fig_var_violations.png")
    print("[plots] saved")


if __name__ == "__main__":
    main()
