"""K1649 — Expectile-VaR / CARE backtest against quantile-VaR baselines.

This experiment asks whether expectile-based tail risk forecasts add practical
OOS value beyond standard quantile-VaR forecasts on daily TLT/HYG returns.

Models:
  1. HS250               rolling historical simulation quantile
  2. LinearQR            expanding-window quantile regression
  3. ALSExpectile-VaR    expectile regression with alpha-mapped tau
  4. CARE-SAV            conditional autoregressive expectile

Lookahead policy:
  - All covariates are aligned by `signal = features.shift(1)`.
  - HS250 uses `y.shift(1).rolling(...).quantile(alpha)`.
  - Every refit uses only `df[df.index < ts]`.

Seed is fixed to 42.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize
from statsmodels.regression.quantile_regression import QuantReg

warnings.simplefilter("ignore", category=RuntimeWarning)
warnings.simplefilter("ignore", category=UserWarning)

EXPERIMENT_ID = "K1649"
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_CACHE = HERE / "K1649_ohlc_cache.parquet"
FORECASTS_PARQUET = HERE / "K1649_forecasts.parquet"
RESULTS_JSON = HERE / "K1649_results.json"

TICKERS = ["TLT", "HYG", "IEF", "LQD", "^VIX"]
DEPENDENT_ASSETS = ["TLT", "HYG"]
START = "2010-01-01"
END = "2026-07-07"
OOS_START = pd.Timestamp("2015-01-01")
ALPHAS = (0.05, 0.01)
HARVEY_ABS_T_THRESHOLD = 3.0

LINEAR_FEATS = ["rv5", "abs_ret1", "neg_ret1", "ief_mom5", "lqd_mom5", "credit_chg5", "vix"]

TAU_GRIDS = {
    0.05: np.array([0.0025, 0.005, 0.01, 0.015, 0.025, 0.04, 0.06, 0.09, 0.13, 0.18]),
    0.01: np.array([0.0005, 0.001, 0.002, 0.0035, 0.005, 0.0075, 0.01, 0.015, 0.025, 0.04]),
}


@dataclass
class ForecastSeries:
    name: str
    var: pd.Series
    loss: pd.Series
    violations: pd.Series
    tau: pd.Series | None = None


@dataclass
class LinearExpectileModel:
    params: np.ndarray
    mean: pd.Series
    std: pd.Series
    feats: List[str]


def fetch_data(force: bool = False) -> pd.DataFrame:
    if DATA_CACHE.exists() and not force:
        return pd.read_parquet(DATA_CACHE)

    import yfinance as yf

    close = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
    )["Close"]
    close = close.dropna(how="any").sort_index()
    close.to_parquet(DATA_CACHE)
    return close


def build_panel(close: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Build a causal daily return panel for one dependent asset.

    The target is day-t log return. All predictors are shifted by one trading
    day, so a forecast for t can only see information through t-1.
    """
    logret = np.log(close).diff()
    y = logret[asset].rename("y")

    own = logret[asset]
    credit_ratio = close["HYG"] / close["IEF"]
    features = pd.DataFrame(
        {
            "rv5": own.rolling(5).std() * np.sqrt(252),
            "abs_ret1": own.abs(),
            "neg_ret1": np.minimum(own, 0.0),
            "ief_mom5": logret["IEF"].rolling(5).sum(),
            "lqd_mom5": logret["LQD"].rolling(5).sum(),
            "credit_chg5": credit_ratio.pct_change(5),
            "vix": close["^VIX"],
        },
        index=close.index,
    )
    signal = features.shift(1)  # canonical t-1 alignment; no same-day signal.
    return pd.concat([y, signal], axis=1).dropna()


def refit_dates(index: pd.DatetimeIndex, cadence: str = "month") -> List[pd.Timestamp]:
    dates: List[pd.Timestamp] = []
    last_key = None
    for ts in index:
        if ts < OOS_START:
            continue
        key = (ts.year, ts.month) if cadence == "month" else (ts.year, (ts.month - 1) // 3)
        if key != last_key:
            dates.append(ts)
            last_key = key
    return dates


def pinball_loss(y: pd.Series, q: pd.Series, alpha: float) -> pd.Series:
    e = y - q
    return e.apply(lambda x: alpha * x if x >= 0.0 else (alpha - 1.0) * x)


def expectile_loss_array(y: np.ndarray, ehat: np.ndarray, tau: float) -> np.ndarray:
    residual = y - ehat
    weights = np.where(residual >= 0.0, tau, 1.0 - tau)
    return weights * residual * residual


def constant_expectile(y: np.ndarray, tau: float, max_iter: int = 200) -> float:
    ehat = float(np.mean(y))
    for _ in range(max_iter):
        residual = y - ehat
        weights = np.where(residual >= 0.0, tau, 1.0 - tau)
        new = float(np.sum(weights * y) / np.sum(weights))
        if abs(new - ehat) < 1e-12:
            break
        ehat = new
    return ehat


def calibrate_tau_unconditional(y_train: np.ndarray, alpha: float) -> Tuple[float, float]:
    """Map expectile tau to a VaR-like alpha using in-sample violation rate.

    This follows the practical expectile-to-quantile mapping: choose the
    expectile whose in-sample exceedance probability is closest to alpha.
    """
    best: Tuple[float, float, float] | None = None
    for tau in TAU_GRIDS[alpha]:
        ehat = constant_expectile(y_train, float(tau))
        rate = float(np.mean(y_train < ehat))
        score = abs(rate - alpha)
        if best is None or (score, abs(float(tau) - alpha)) < (best[0], abs(best[1] - alpha)):
            best = (score, float(tau), rate)
    assert best is not None
    return best[1], best[2]


def standardize(train: pd.DataFrame, feats: List[str]) -> Tuple[pd.Series, pd.Series]:
    mean = train[feats].mean()
    std = train[feats].std().replace(0.0, 1.0).fillna(1.0)
    return mean, std


def design_matrix(df: pd.DataFrame, feats: List[str], mean: pd.Series, std: pd.Series) -> np.ndarray:
    x = ((df[feats] - mean) / std).to_numpy(dtype=float)
    return np.column_stack([np.ones(len(df)), x])


def fit_expectile_irls(
    x: np.ndarray,
    y: np.ndarray,
    tau: float,
    ridge: float = 1e-8,
    max_iter: int = 200,
) -> np.ndarray:
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    ident = np.eye(x.shape[1])
    ident[0, 0] = 0.0
    for _ in range(max_iter):
        residual = y - x @ beta
        weights = np.where(residual >= 0.0, tau, 1.0 - tau)
        xw = x * weights[:, None]
        lhs = x.T @ xw + ridge * ident
        rhs = x.T @ (weights * y)
        try:
            new_beta = np.linalg.solve(lhs, rhs)
        except np.linalg.LinAlgError:
            new_beta = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
        if np.max(np.abs(new_beta - beta)) < 1e-10:
            beta = new_beta
            break
        beta = new_beta
    return beta


def fit_linear_expectile(train: pd.DataFrame, feats: List[str], tau: float) -> LinearExpectileModel:
    mean, std = standardize(train, feats)
    x = design_matrix(train, feats, mean, std)
    beta = fit_expectile_irls(x, train["y"].to_numpy(dtype=float), tau)
    return LinearExpectileModel(params=beta, mean=mean, std=std, feats=feats)


def predict_linear_expectile(model: LinearExpectileModel, row: pd.DataFrame) -> np.ndarray:
    x = design_matrix(row, model.feats, model.mean, model.std)
    return x @ model.params


def fit_quantreg(train: pd.DataFrame, feats: List[str], alpha: float) -> LinearExpectileModel:
    mean, std = standardize(train, feats)
    x = design_matrix(train, feats, mean, std)
    y = train["y"].to_numpy(dtype=float)
    try:
        params = np.asarray(QuantReg(y, x).fit(q=alpha, max_iter=2000).params, dtype=float)
    except Exception:
        params = np.array([np.quantile(y, alpha)] + [0.0] * len(feats), dtype=float)
    return LinearExpectileModel(params=params, mean=mean, std=std, feats=feats)


def run_hs(panel: pd.DataFrame, alpha: float, win: int = 250) -> ForecastSeries:
    y = panel["y"]
    var = y.shift(1).rolling(win).quantile(alpha)
    df = pd.concat([y, var.rename("var")], axis=1).dropna()
    df = df[df.index >= OOS_START]
    loss = pinball_loss(df["y"], df["var"], alpha)
    violations = (df["y"] < df["var"]).astype(int)
    return ForecastSeries(name=f"HS{win}", var=df["var"], loss=loss, violations=violations)


def run_linear_quantreg(panel: pd.DataFrame, alpha: float, cadence: str) -> ForecastSeries:
    df = panel.dropna()
    dates = set(refit_dates(df.index, cadence=cadence))
    model = fit_quantreg(df[df.index < OOS_START], LINEAR_FEATS, alpha)
    var = pd.Series(index=df.index, dtype=float)

    for ts in df.index[df.index >= OOS_START]:
        if ts in dates:
            model = fit_quantreg(df[df.index < ts], LINEAR_FEATS, alpha)
        row = df.loc[[ts]]
        var.loc[ts] = float(predict_linear_expectile(model, row)[0])

    var = var.dropna()
    y = df.loc[var.index, "y"]
    return ForecastSeries(
        name="LinearQR",
        var=var,
        loss=pinball_loss(y, var, alpha),
        violations=(y < var).astype(int),
    )


def run_linear_expectile(panel: pd.DataFrame, alpha: float, cadence: str) -> ForecastSeries:
    df = panel.dropna()
    dates = set(refit_dates(df.index, cadence=cadence))
    train = df[df.index < OOS_START]
    tau, _ = calibrate_tau_unconditional(train["y"].to_numpy(dtype=float), alpha)
    model = fit_linear_expectile(train, LINEAR_FEATS, tau)
    var = pd.Series(index=df.index, dtype=float)
    taus = pd.Series(index=df.index, dtype=float)

    for ts in df.index[df.index >= OOS_START]:
        if ts in dates:
            train = df[df.index < ts]
            tau, _ = calibrate_tau_unconditional(train["y"].to_numpy(dtype=float), alpha)
            model = fit_linear_expectile(train, LINEAR_FEATS, tau)
        row = df.loc[[ts]]
        var.loc[ts] = float(predict_linear_expectile(model, row)[0])
        taus.loc[ts] = tau

    var = var.dropna()
    taus = taus.loc[var.index]
    y = df.loc[var.index, "y"]
    return ForecastSeries(
        name="ALSExpectile-VaR",
        var=var,
        loss=pinball_loss(y, var, alpha),
        violations=(y < var).astype(int),
        tau=taus,
    )


def care_recursion(params: np.ndarray, y: np.ndarray, q0: float) -> np.ndarray:
    b0, b1, b2 = params
    q = np.empty(len(y), dtype=float)
    q[0] = q0
    for i in range(1, len(y)):
        q[i] = b0 + b1 * abs(y[i - 1]) + b2 * q[i - 1]
    return q


def fit_care(train_y: np.ndarray, tau: float) -> Tuple[np.ndarray, float]:
    q0 = constant_expectile(train_y[: min(500, len(train_y))], tau)
    rng = np.random.default_rng(SEED)
    starts = [
        np.array([q0 * 0.05, -0.35, 0.90]),
        np.array([q0 * 0.10, -0.70, 0.85]),
        np.array([q0 * 0.15, -1.00, 0.75]),
        np.array([0.0, -0.50, 0.95]),
    ]
    for _ in range(1):
        starts.append(
            np.array(
                [
                    rng.uniform(-0.005, 0.002),
                    rng.uniform(-1.5, 0.2),
                    rng.uniform(0.35, 0.98),
                ]
            )
        )

    bounds = [(-0.08, 0.02), (-4.0, 2.0), (0.0, 0.995)]
    best_fun = np.inf
    best_params = starts[0]

    def objective(params: np.ndarray) -> float:
        q = care_recursion(params, train_y, q0)
        if not np.all(np.isfinite(q)):
            return 1e9
        return float(np.mean(expectile_loss_array(train_y, q, tau)))

    for x0 in starts:
        try:
            res = minimize(
                objective,
                x0,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 250, "ftol": 1e-10},
            )
        except Exception:
            continue
        if res.fun < best_fun and np.all(np.isfinite(res.x)):
            best_fun = float(res.fun)
            best_params = np.asarray(res.x, dtype=float)
    return best_params, q0


def care_next(params: np.ndarray, y_prev: float, q_prev: float) -> float:
    b0, b1, b2 = params
    return float(b0 + b1 * abs(y_prev) + b2 * q_prev)


def run_care(panel: pd.DataFrame, alpha: float, cadence: str) -> ForecastSeries:
    df = panel.dropna()
    dates = set(refit_dates(df.index, cadence=cadence))
    train = df[df.index < OOS_START]
    tau, _ = calibrate_tau_unconditional(train["y"].to_numpy(dtype=float), alpha)
    params, q0 = fit_care(train["y"].to_numpy(dtype=float), tau)
    replay = care_recursion(params, train["y"].to_numpy(dtype=float), q0)
    q_prev = float(replay[-1])
    y_prev = float(train["y"].iloc[-1])

    var = pd.Series(index=df.index, dtype=float)
    taus = pd.Series(index=df.index, dtype=float)
    for ts in df.index[df.index >= OOS_START]:
        if ts in dates:
            train = df[df.index < ts]
            train_y = train["y"].to_numpy(dtype=float)
            tau, _ = calibrate_tau_unconditional(train_y, alpha)
            params, q0 = fit_care(train_y, tau)
            replay = care_recursion(params, train_y, q0)
            q_prev = float(replay[-1])
            y_prev = float(train["y"].iloc[-1])
        var.loc[ts] = care_next(params, y_prev, q_prev)
        taus.loc[ts] = tau
        q_prev = float(var.loc[ts])
        y_prev = float(df.loc[ts, "y"])

    var = var.dropna()
    taus = taus.loc[var.index]
    y = df.loc[var.index, "y"]
    return ForecastSeries(
        name="CARE-SAV",
        var=var,
        loss=pinball_loss(y, var, alpha),
        violations=(y < var).astype(int),
        tau=taus,
    )


def kupiec_pof(violations: pd.Series, alpha: float) -> Dict[str, float]:
    n = int(len(violations))
    x = int(violations.sum())
    if n == 0:
        return {"n": 0, "violations": 0, "rate": float("nan"), "stat": float("nan"), "p": float("nan")}
    pi_hat = x / n
    p0 = alpha
    eps = 1e-12
    pi_safe = min(max(pi_hat, eps), 1.0 - eps)
    p_safe = min(max(p0, eps), 1.0 - eps)
    ll0 = x * math.log(p_safe) + (n - x) * math.log(1.0 - p_safe)
    ll1 = x * math.log(pi_safe) + (n - x) * math.log(1.0 - pi_safe)
    stat = max(0.0, -2.0 * (ll0 - ll1))
    return {
        "n": n,
        "violations": x,
        "rate": float(pi_hat),
        "expected_rate": float(alpha),
        "stat": float(stat),
        "p": float(1.0 - stats.chi2.cdf(stat, df=1)),
    }


def christoffersen_independence(violations: pd.Series) -> Dict[str, float]:
    v = violations.to_numpy(dtype=int)
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
    if n0 == 0 or n1 == 0:
        return {"n00": n00, "n01": n01, "n10": n10, "n11": n11, "stat": float("nan"), "p": float("nan")}
    pi01 = n01 / n0
    pi11 = n11 / n1
    pi = (n01 + n11) / (n0 + n1)

    def term(n: int, p: float) -> float:
        if n == 0:
            return 0.0
        return n * math.log(min(max(p, 1e-12), 1.0 - 1e-12))

    ll_null = term(n00 + n10, 1.0 - pi) + term(n01 + n11, pi)
    ll_alt = term(n00, 1.0 - pi01) + term(n01, pi01) + term(n10, 1.0 - pi11) + term(n11, pi11)
    stat = max(0.0, -2.0 * (ll_null - ll_alt))
    return {
        "n00": n00,
        "n01": n01,
        "n10": n10,
        "n11": n11,
        "stat": float(stat),
        "p": float(1.0 - stats.chi2.cdf(stat, df=1)),
    }


def dm_test_hac(loss_a: pd.Series, loss_b: pd.Series, h: int = 1) -> Dict[str, float]:
    d = (loss_a - loss_b).dropna().to_numpy(dtype=float)
    n = len(d)
    if n < 30:
        return {"n": n, "dbar": float("nan"), "stat": float("nan"), "p": float("nan")}
    dbar = float(np.mean(d))
    lag = max(1, int(np.floor(1.5 * n ** (1.0 / 3.0))))
    var = float(np.mean((d - dbar) ** 2))
    for k in range(1, lag + 1):
        weight = 1.0 - k / (lag + 1.0)
        cov = float(np.mean((d[k:] - dbar) * (d[:-k] - dbar)))
        var += 2.0 * weight * cov
    if var <= 0.0:
        return {"n": n, "dbar": dbar, "stat": float("nan"), "p": float("nan"), "nw_lag": lag}
    se = math.sqrt(var / n)
    stat = dbar / se
    hln = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n) if h > 1 else 1.0
    stat *= hln
    return {
        "n": n,
        "dbar": dbar,
        "se": se,
        "stat": float(stat),
        "p": float(2.0 * (1.0 - stats.t.cdf(abs(stat), df=n - 1))),
        "nw_lag": lag,
        "harvey_abs_t_gt_3": bool(abs(stat) > HARVEY_ABS_T_THRESHOLD),
    }


def align_forecasts(forecasts: Dict[str, ForecastSeries]) -> Dict[str, ForecastSeries]:
    common: pd.DatetimeIndex | None = None
    for fs in forecasts.values():
        common = fs.loss.index if common is None else common.intersection(fs.loss.index)
    assert common is not None
    aligned: Dict[str, ForecastSeries] = {}
    for name, fs in forecasts.items():
        tau = fs.tau.loc[common] if fs.tau is not None else None
        aligned[name] = ForecastSeries(
            name=fs.name,
            var=fs.var.loc[common],
            loss=fs.loss.loc[common],
            violations=fs.violations.loc[common],
            tau=tau,
        )
    return aligned


def run_one(panel: pd.DataFrame, alpha: float, cadence: str) -> Dict[str, ForecastSeries]:
    forecasts = {
        "HS250": run_hs(panel, alpha),
        "LinearQR": run_linear_quantreg(panel, alpha, cadence=cadence),
        "ALSExpectile-VaR": run_linear_expectile(panel, alpha, cadence=cadence),
        "CARE-SAV": run_care(panel, alpha, cadence=cadence),
    }
    return align_forecasts(forecasts)


def summarize_forecasts(forecasts: Dict[str, ForecastSeries], alpha: float) -> Dict[str, object]:
    per_model: Dict[str, object] = {}
    for name, fs in forecasts.items():
        row: Dict[str, object] = {
            "obs": int(len(fs.loss)),
            "mean_pinball": float(fs.loss.mean()),
            "sum_pinball": float(fs.loss.sum()),
            "violation_rate": float(fs.violations.mean()),
            "kupiec": kupiec_pof(fs.violations, alpha),
            "christoffersen_ind": christoffersen_independence(fs.violations),
        }
        if fs.tau is not None:
            row["tau_summary"] = {
                "min": float(fs.tau.min()),
                "median": float(fs.tau.median()),
                "max": float(fs.tau.max()),
                "unique_values": sorted(float(x) for x in fs.tau.dropna().unique()),
            }
        per_model[name] = row

    pairs = [
        ("ALSExpectile-VaR", "LinearQR"),
        ("CARE-SAV", "LinearQR"),
        ("ALSExpectile-VaR", "HS250"),
        ("CARE-SAV", "HS250"),
        ("LinearQR", "HS250"),
        ("CARE-SAV", "ALSExpectile-VaR"),
    ]
    dm_pairs = {f"{a}_vs_{b}": dm_test_hac(forecasts[a].loss, forecasts[b].loss) for a, b in pairs}
    best_model = min(per_model, key=lambda m: float(per_model[m]["mean_pinball"]))  # type: ignore[index]
    return {"per_model": per_model, "dm_pairs": dm_pairs, "best_mean_pinball_model": best_model}


def forecast_frame(asset: str, alpha: float, forecasts: Dict[str, ForecastSeries], panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, fs in forecasts.items():
        y = panel.loc[fs.var.index, "y"]
        part = pd.DataFrame(
            {
                "date": fs.var.index,
                "asset": asset,
                "alpha": alpha,
                "model": name,
                "y": y.to_numpy(dtype=float),
                "var": fs.var.to_numpy(dtype=float),
                "pinball_loss": fs.loss.to_numpy(dtype=float),
                "violation": fs.violations.to_numpy(dtype=int),
                "tau": fs.tau.to_numpy(dtype=float) if fs.tau is not None else np.nan,
            }
        )
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def plot_mean_pinball(results: Dict[str, object], out: Path) -> None:
    records = []
    for key, block in results["by_asset_alpha"].items():  # type: ignore[index]
        asset, alpha_label = key.split("_")
        for model, row in block["per_model"].items():  # type: ignore[index]
            records.append(
                {
                    "asset_alpha": f"{asset} VaR {int(alpha_label)}%",
                    "model": model,
                    "mean_pinball": row["mean_pinball"],
                }
            )
    df = pd.DataFrame(records)
    labels = list(df["asset_alpha"].drop_duplicates())
    models = ["HS250", "LinearQR", "ALSExpectile-VaR", "CARE-SAV"]
    x = np.arange(len(labels))
    width = 0.18

    fig, ax = plt.subplots(figsize=(13, 7))
    colors = ["#4c78a8", "#72b7b2", "#f58518", "#54a24b"]
    for i, model in enumerate(models):
        vals = [
            float(df[(df["asset_alpha"] == label) & (df["model"] == model)]["mean_pinball"].iloc[0])
            for label in labels
        ]
        ax.bar(x + (i - 1.5) * width, vals, width=width, label=model, color=colors[i])
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Mean pinball loss")
    ax.set_title("K1649 expectile-VaR vs quantile-VaR: lower is better")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_coverage(results: Dict[str, object], out: Path) -> None:
    records = []
    for key, block in results["by_asset_alpha"].items():  # type: ignore[index]
        asset, alpha_label = key.split("_")
        alpha = int(alpha_label) / 100.0
        for model, row in block["per_model"].items():  # type: ignore[index]
            records.append(
                {
                    "asset_alpha": f"{asset} VaR {int(alpha_label)}%",
                    "model": model,
                    "target": alpha,
                    "violation_rate": row["violation_rate"],
                }
            )
    df = pd.DataFrame(records)
    labels = list(df["asset_alpha"].drop_duplicates())
    models = ["HS250", "LinearQR", "ALSExpectile-VaR", "CARE-SAV"]
    x = np.arange(len(labels))
    width = 0.18
    fig, ax = plt.subplots(figsize=(13, 7))
    colors = ["#4c78a8", "#72b7b2", "#f58518", "#54a24b"]
    for i, model in enumerate(models):
        vals = [
            float(df[(df["asset_alpha"] == label) & (df["model"] == model)]["violation_rate"].iloc[0])
            for label in labels
        ]
        ax.bar(x + (i - 1.5) * width, vals, width=width, label=model, color=colors[i])
    for i, label in enumerate(labels):
        target = float(df[df["asset_alpha"] == label]["target"].iloc[0])
        ax.hlines(target, i - 0.42, i + 0.42, colors="#222222", linestyles="--", linewidth=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Violation rate")
    ax.set_title("K1649 VaR backtest calibration: bars vs dashed target")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def build_overall(results: Dict[str, object]) -> Dict[str, object]:
    best_counts: Dict[str, int] = {}
    expectile_harvey_wins_vs_linearqr = 0
    expectile_cases_better_than_linearqr = 0
    for block in results["by_asset_alpha"].values():  # type: ignore[index]
        best = block["best_mean_pinball_model"]  # type: ignore[index]
        best_counts[best] = best_counts.get(best, 0) + 1
        for pair in ["ALSExpectile-VaR_vs_LinearQR", "CARE-SAV_vs_LinearQR"]:
            dm = block["dm_pairs"][pair]  # type: ignore[index]
            if float(dm["dbar"]) < 0.0:
                expectile_cases_better_than_linearqr += 1
            if bool(dm.get("harvey_abs_t_gt_3")) and float(dm["dbar"]) < 0.0:
                expectile_harvey_wins_vs_linearqr += 1
    verdict = (
        "PASS_EXPECTILE_BEATS_LINEARQR"
        if expectile_harvey_wins_vs_linearqr > 0
        else "NULL_NO_EXPECTILE_EDGE_VS_LINEARQR"
    )
    return {
        "best_mean_pinball_counts": best_counts,
        "expectile_cases_better_than_linearqr_by_mean_loss": expectile_cases_better_than_linearqr,
        "expectile_harvey_wins_vs_linearqr": expectile_harvey_wins_vs_linearqr,
        "harvey_abs_t_threshold": HARVEY_ABS_T_THRESHOLD,
        "verdict": verdict,
    }


def atomic_write_json(path: Path, payload: Dict[str, object]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-fetch", action="store_true")
    parser.add_argument("--cadence", choices=["month", "quarter"], default="quarter")
    args = parser.parse_args()

    close = fetch_data(force=args.force_fetch)
    print(f"[data] rows={len(close)} first={close.index.min().date()} last={close.index.max().date()}", flush=True)

    results: Dict[str, object] = {
        "meta": {
            "experiment_id": EXPERIMENT_ID,
            "seed": SEED,
            "data_source": "Yahoo Finance adjusted close via yfinance",
            "data_start": str(close.index.min().date()),
            "data_end": str(close.index.max().date()),
            "oos_start": str(OOS_START.date()),
            "dependent_assets": DEPENDENT_ASSETS,
            "covariates": LINEAR_FEATS,
            "alphas": list(ALPHAS),
            "models": ["HS250", "LinearQR", "ALSExpectile-VaR", "CARE-SAV"],
            "refit_cadence": f"{args.cadence}_expanding",
            "lookahead_policy": "features use signal = features.shift(1); HS uses y.shift(1); model refits use df[df.index < ts]",
            "tau_mapping": "unconditional in-sample expectile tau chosen to match alpha violation rate before each refit",
            "literature_used": [
                "Newey and Powell (1987) asymmetric least squares / expectiles",
                "Taylor (2008) / Kuan et al. CARE and expectile-based VaR",
                "Bellini et al. (2014) generalized quantiles as risk measures",
                "Fissler and Ziegel (2016) elicitability context for risk-measure backtesting",
            ],
        },
        "panels": {},
        "by_asset_alpha": {},
    }

    all_forecasts: List[pd.DataFrame] = []
    for asset in DEPENDENT_ASSETS:
        panel = build_panel(close, asset)
        results["panels"][asset] = {  # type: ignore[index]
            "rows": int(len(panel)),
            "first": str(panel.index.min().date()),
            "last": str(panel.index.max().date()),
        }
        print(f"[panel] {asset} rows={len(panel)} first={panel.index.min().date()} last={panel.index.max().date()}", flush=True)
        for alpha in ALPHAS:
            print(f"[run] asset={asset} alpha={alpha:.2%}", flush=True)
            forecasts = run_one(panel, alpha, cadence=args.cadence)
            key = f"{asset}_{int(alpha * 100):02d}"
            results["by_asset_alpha"][key] = summarize_forecasts(forecasts, alpha)  # type: ignore[index]
            all_forecasts.append(forecast_frame(asset, alpha, forecasts, panel))
            for name, fs in forecasts.items():
                print(
                    f"  {name:17s} obs={len(fs.loss):4d} "
                    f"mean_pinball={fs.loss.mean():.8f} viol_rate={fs.violations.mean():.4f}"
                    ,
                    flush=True,
                )

    results["overall"] = build_overall(results)
    forecast_df = pd.concat(all_forecasts, ignore_index=True)
    forecast_df.to_parquet(FORECASTS_PARQUET, index=False)
    plot_mean_pinball(results, HERE / "fig_k1649_mean_pinball.png")
    plot_coverage(results, HERE / "fig_k1649_coverage.png")
    atomic_write_json(RESULTS_JSON, results)
    print(f"[write] {RESULTS_JSON}", flush=True)
    print(f"[write] {FORECASTS_PARQUET}", flush=True)
    print(f"[verdict] {results['overall']['verdict']}", flush=True)  # type: ignore[index]


if __name__ == "__main__":
    main()
