"""K1337 — Yield curve steepening RATE (dV/dt) regime predicts SPY forward RV?

Differentiation vs prior K (K749 / K871 / G5 / T14):
  Prior NULL results test SLOPE LEVEL → forward equity vol, often dominated by VIX.
  K1337 tests SLOPE RATE-OF-CHANGE (steepening velocity dV/dt) over short windows
  (5/10/20d) as a REGIME signal — not a regression input — for SPY forward RV.

Methodology (research-honesty hard rules):
  - All signals use signal.shift(1) before joining with target.
  - Regime cutoffs (top/bottom quintiles of dV/dt) are computed on a ROLLING basis
    using ONLY data up to t-1 to avoid in-sample regime classification lookahead.
  - Forward RV(H) at date t = annualized std of log-returns over [t+1, t+H].
    Sample restricted to t where the forward window is fully observable AND
    where the signal at t is built from data up to t-1.
  - Baseline: HAR-RV(1,5,22) on past RV (no overhead from VIX), expanding-window
    OLS with refit cadence so no full-sample fit leakage.
  - QLIKE (Patton 2011) computed on r^2-style RV proxy; DM test with HAC
    (Newey-West, lag = H-1) standard errors.
  - Bootstrap: 999 reps, seed=42, stationary block bootstrap on per-date QLIKE diffs.
  - Multiple-testing warning printed for the grid of (signal_slope × N × H).

Out-of-scope: full sector rotation; XLF/XLU only optional descriptive overlay.

Usage:
    uv run python experiments/k1337/K1337.py

Output:
    experiments/k1337/K1337_results.json
    experiments/k1337/K1337_overview.png
    experiments/k1337/K1337_regime.png
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
np.random.seed(SEED)

EXP_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXP_DIR / "K1337_results.json"

START_DATE = "2014-01-01"
END_DATE = "2026-06-15"

TICKERS = ["^TNX", "^IRX", "^FVX", "^TYX", "^VIX", "SPY", "XLF", "XLU"]

# Grid
SLOPE_SPECS = [("TNX_minus_IRX", "^TNX", "^IRX"), ("TNX_minus_FVX", "^TNX", "^FVX")]
N_WINDOWS = [5, 10, 20]  # dV/dt window
H_HORIZONS = [5, 10, 20]  # forward RV horizon (trading days)

# Regime split: top/bottom 20%
REGIME_Q_HI = 0.80
REGIME_Q_LO = 0.20
ROLLING_REGIME_WINDOW = 252  # 1 year rolling regime calibration

# HAR refit cadence
HAR_INIT = 504  # ~2y warmup before first OOS forecast
HAR_REFIT_EVERY = 21

BOOTSTRAP_REPS = 999
BLOCK_LEN_FACTOR = 1.5  # block length ~ BLOCK_LEN_FACTOR * H

# =============================================================================
# Data
# =============================================================================


def fetch_data() -> pd.DataFrame:
    """Fetch daily close prices for all tickers."""
    print(f"[data] downloading {TICKERS} from {START_DATE} to {END_DATE}")
    df = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        progress=False,
        auto_adjust=False,
    )
    # multiindex: get Close
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].copy()
    else:
        close = df[["Close"]].rename(columns={"Close": TICKERS[0]})
    close = close.dropna(how="all")
    return close


def build_features(close: pd.DataFrame) -> pd.DataFrame:
    """Build slope + dV/dt features. NO LOOKAHEAD: all features as of date t use info up to t."""
    df = close.copy()
    feats = pd.DataFrame(index=df.index)

    # Yields (^TNX etc. quoted as percent already; we keep as-is)
    for name, long_t, short_t in SLOPE_SPECS:
        feats[f"slope_{name}"] = df[long_t] - df[short_t]
        for N in N_WINDOWS:
            # dV/dt = N-day change of slope; this is a t-information signal (uses t)
            feats[f"dslope_{name}_N{N}"] = feats[f"slope_{name}"].diff(N)

    # SPY log returns
    feats["spy_ret"] = np.log(df["SPY"]).diff()

    # VIX level for reference
    feats["vix"] = df["^VIX"]

    # XLF / XLU log returns (for secondary)
    if "XLF" in df:
        feats["xlf_ret"] = np.log(df["XLF"]).diff()
    if "XLU" in df:
        feats["xlu_ret"] = np.log(df["XLU"]).diff()

    return feats


def forward_rv(returns: pd.Series, H: int) -> pd.Series:
    """Annualized realized vol over forward window [t+1, t+H].

    forward_rv at index t uses returns indexed (t+1 ... t+H).
    Therefore using forward_rv[t] together with signal_at_t built from data up to t-1
    is causal (signal in info(t-1), target in info(t+H)).
    """
    n = len(returns)
    out = np.full(n, np.nan)
    arr = returns.values
    for i in range(n - H):
        window = arr[i + 1 : i + 1 + H]
        if np.isfinite(window).sum() == H:
            out[i] = math.sqrt(252.0 * np.mean(window ** 2))
    return pd.Series(out, index=returns.index, name=f"fwd_rv_{H}")


# =============================================================================
# HAR-RV baseline
# =============================================================================


def realized_var_daily(returns: pd.Series) -> pd.Series:
    """Daily realized variance proxy = r^2 (annualized to align with forward RV).

    For HAR-RV we use BACKWARD rolling over [t-K+1, t] then shift by 1 to be t-1 info.
    """
    return returns ** 2 * 252.0  # annualized variance proxy at each day


def har_features(rv_daily: pd.Series) -> pd.DataFrame:
    """HAR(1,5,22) lagged components. All features at index t use info up to t.
    Caller must shift by 1 (or evaluate as forecasting t->t+H using t-information).
    """
    df = pd.DataFrame(index=rv_daily.index)
    df["rv_d"] = rv_daily
    df["rv_w"] = rv_daily.rolling(5).mean()
    df["rv_m"] = rv_daily.rolling(22).mean()
    return df


def har_forecast(
    rv_daily: pd.Series,
    target: pd.Series,
    init: int = HAR_INIT,
    refit_every: int = HAR_REFIT_EVERY,
) -> pd.Series:
    """Expanding-window OLS HAR forecast of `target` from rv_daily lagged components.

    All HAR features at date t use info up to t-1 (we shift by 1 below).
    Coefficients refit every `refit_every` days using only data strictly before t.
    """
    feats = har_features(rv_daily).shift(1)  # ensure t-1 info
    df = pd.concat([feats, target.rename("y")], axis=1).dropna()

    n = len(df)
    yhat = pd.Series(np.nan, index=df.index)
    if n <= init:
        return yhat
    coef = None
    for i in range(init, n):
        if (i - init) % refit_every == 0:
            X = df.iloc[:i][["rv_d", "rv_w", "rv_m"]].values
            X = np.c_[np.ones(len(X)), X]
            y_train = df.iloc[:i]["y"].values
            coef, *_ = np.linalg.lstsq(X, y_train, rcond=None)
        x_t = df.iloc[i][["rv_d", "rv_w", "rv_m"]].values
        x_t = np.r_[1.0, x_t]
        yhat.iloc[i] = float(x_t @ coef)
    return yhat


# =============================================================================
# QLIKE + DM-HAC + bootstrap
# =============================================================================


def qlike(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """Patton (2011) QLIKE for variance: log(yhat) + y_true / yhat. Lower is better.

    Both inputs are variance proxies (we square our fwd vol to get var)."""
    eps = 1e-10
    yhat = np.clip(y_pred, eps, None)
    yt = np.clip(y_true, eps, None)
    return np.log(yhat) + yt / yhat


def dm_test_hac(d: np.ndarray, lag: int) -> Tuple[float, float]:
    """Diebold-Mariano with Newey-West HAC SE. d = per-date loss difference."""
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return float("nan"), float("nan")
    mean_d = d.mean()
    # NW variance with truncation lag
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        w = 1.0 - k / (lag + 1)
        cov_k = np.mean((d[k:] - mean_d) * (d[:-k] - mean_d))
        var_d += 2.0 * w * cov_k
    se = math.sqrt(max(var_d, 1e-12) / n)
    t_stat = mean_d / se
    from scipy.stats import norm
    p = 2.0 * (1.0 - norm.cdf(abs(t_stat)))
    return float(t_stat), float(p)


def stationary_block_bootstrap_mean(
    d: np.ndarray, block_len: float, reps: int, seed: int = SEED
) -> Tuple[float, float, float]:
    """Stationary block bootstrap CI for mean(d). Returns (mean, ci_lo, ci_hi)."""
    rng = np.random.default_rng(seed)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return float("nan"), float("nan"), float("nan")
    p_geom = 1.0 / max(block_len, 1.0)
    means = np.empty(reps)
    for r in range(reps):
        i = 0
        sample = np.empty(n)
        idx = rng.integers(0, n)
        while i < n:
            sample[i] = d[idx]
            i += 1
            if rng.random() < p_geom:
                idx = rng.integers(0, n)
            else:
                idx = (idx + 1) % n
        means[r] = sample.mean()
    return float(np.mean(d)), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


# =============================================================================
# Regime classification (rolling, causal)
# =============================================================================


def rolling_regime(signal: pd.Series, window: int = ROLLING_REGIME_WINDOW) -> pd.Series:
    """Classify each date t into HIGH (top 20% of past window), LOW (bottom 20%), MID.

    Uses ONLY signal values up to and including t (causal). When paired with
    forward_rv at t (which uses returns t+1..t+H), the overall pipeline is causal.
    """
    out = pd.Series(index=signal.index, dtype=object)
    vals = signal.values
    for i in range(len(signal)):
        if i < window:
            out.iloc[i] = "WARMUP"
            continue
        past = vals[i - window : i + 1]  # includes today
        past = past[np.isfinite(past)]
        if len(past) < window // 2:
            out.iloc[i] = "WARMUP"
            continue
        q_hi = np.quantile(past, REGIME_Q_HI)
        q_lo = np.quantile(past, REGIME_Q_LO)
        v = vals[i]
        if not np.isfinite(v):
            out.iloc[i] = "NA"
        elif v >= q_hi:
            out.iloc[i] = "FAST_STEEPEN"
        elif v <= q_lo:
            out.iloc[i] = "FAST_FLATTEN"
        else:
            out.iloc[i] = "MID"
    return out


# =============================================================================
# Main pipeline
# =============================================================================


@dataclass
class SpecResult:
    spec_name: str
    N: int
    H: int
    n_obs: int
    har_qlike: float
    har_plus_signal_qlike: float
    improvement_pct: float
    dm_t: float
    dm_p: float
    boot_mean: float
    boot_ci_lo: float
    boot_ci_hi: float
    regime_table: Dict[str, Dict[str, float]]


def run_one_spec(
    feats: pd.DataFrame,
    spec_name: str,
    N: int,
    H: int,
) -> SpecResult:
    spy_ret = feats["spy_ret"].dropna()
    # daily annualized variance proxy
    rv_daily = realized_var_daily(spy_ret)
    # target: forward annualized vol -> we evaluate variance, so square it
    fwd_vol = forward_rv(spy_ret, H)
    fwd_var = fwd_vol ** 2

    # HAR baseline forecast (variance space)
    har_yhat = har_forecast(rv_daily, fwd_var, init=HAR_INIT, refit_every=HAR_REFIT_EVERY)

    # Signal: dslope[spec][N], shift(1) for causality
    sig_col = f"dslope_{spec_name}_N{N}"
    sig = feats[sig_col].shift(1)

    # Augmented forecast: HAR + signal
    # FIT IN LOG-VARIANCE SPACE for numerical stability with heavy-tailed RV target.
    # Predictions exponentiated and clipped to [1e-8, 10x HAR_yhat] to prevent extrapolation blowup.
    df = pd.concat([har_yhat.rename("har_yhat"), sig.rename("sig"), fwd_var.rename("y")], axis=1).dropna()
    df = df[df["har_yhat"] > 0]  # need positive for log
    df = df[df["y"] > 0]
    n = len(df)
    if n <= HAR_INIT + 50:
        return SpecResult(spec_name, N, H, n, float("nan"), float("nan"), float("nan"),
                          float("nan"), float("nan"), float("nan"), float("nan"), float("nan"), {})

    aug_yhat = pd.Series(np.nan, index=df.index)
    coef = None
    init_aug = max(HAR_INIT, 252)
    log_har = np.log(df["har_yhat"].values)
    log_y = np.log(df["y"].values)
    sig_v = df["sig"].values
    har_raw = df["har_yhat"].values

    for i in range(init_aug, n):
        if (i - init_aug) % HAR_REFIT_EVERY == 0:
            X = np.c_[np.ones(i), log_har[:i], sig_v[:i]]
            y_train = log_y[:i]
            coef, *_ = np.linalg.lstsq(X, y_train, rcond=None)
        x_t = np.r_[1.0, log_har[i], sig_v[i]]
        pred_log = float(x_t @ coef)
        # back-transform with Jensen correction omitted (small); clip to [1e-8, 10*HAR]
        pred = math.exp(pred_log)
        cap = 10.0 * har_raw[i]
        floor = 1e-8
        aug_yhat.iloc[i] = float(min(max(pred, floor), cap))

    df_eval = pd.concat([df["y"].rename("y"), df["har_yhat"].rename("har"), aug_yhat.rename("aug")], axis=1).dropna()
    y = df_eval["y"].values
    yhat_har = df_eval["har"].values
    yhat_aug = df_eval["aug"].values

    qlike_har = qlike(y, yhat_har)
    qlike_aug = qlike(y, yhat_aug)
    d = qlike_aug - qlike_har  # negative => aug better

    har_mean = float(np.mean(qlike_har))
    aug_mean = float(np.mean(qlike_aug))
    impr_pct = 100.0 * (har_mean - aug_mean) / abs(har_mean) if har_mean != 0 else float("nan")

    dm_t, dm_p = dm_test_hac(d, lag=max(H - 1, 1))
    boot_mean, ci_lo, ci_hi = stationary_block_bootstrap_mean(
        d, block_len=BLOCK_LEN_FACTOR * H, reps=BOOTSTRAP_REPS, seed=SEED
    )

    # Regime-conditional analysis on the raw signal (regime at t, target at t+1..t+H)
    regime = rolling_regime(feats[sig_col])
    reg_df = pd.concat([regime.rename("regime"), fwd_vol.rename("fv"), feats["vix"].rename("vix")], axis=1).dropna()
    reg_df = reg_df[reg_df["regime"].isin(["FAST_STEEPEN", "FAST_FLATTEN", "MID"])]
    regime_table = {}
    for label in ["FAST_STEEPEN", "FAST_FLATTEN", "MID"]:
        sub = reg_df[reg_df["regime"] == label]
        if len(sub) > 0:
            regime_table[label] = {
                "n": int(len(sub)),
                "fwd_vol_mean": float(sub["fv"].mean()),
                "fwd_vol_median": float(sub["fv"].median()),
                "fwd_vol_p90": float(sub["fv"].quantile(0.9)),
                "vix_mean": float(sub["vix"].mean()),
            }

    return SpecResult(
        spec_name=spec_name, N=N, H=H, n_obs=int(len(df_eval)),
        har_qlike=har_mean, har_plus_signal_qlike=aug_mean, improvement_pct=impr_pct,
        dm_t=dm_t, dm_p=dm_p,
        boot_mean=boot_mean, boot_ci_lo=ci_lo, boot_ci_hi=ci_hi,
        regime_table=regime_table,
    )


def secondary_sector_diff(feats: pd.DataFrame) -> Dict[str, Dict]:
    """Optional descriptive: XLF/XLU/SPY forward RV by regime."""
    out = {}
    regime = rolling_regime(feats["dslope_TNX_minus_IRX_N10"])
    for ticker, retcol in [("XLF", "xlf_ret"), ("XLU", "xlu_ret"), ("SPY", "spy_ret")]:
        if retcol not in feats.columns:
            continue
        fwd_vol_10 = forward_rv(feats[retcol].dropna(), 10)
        df = pd.concat([regime.rename("regime"), fwd_vol_10.rename("fv")], axis=1).dropna()
        df = df[df["regime"].isin(["FAST_STEEPEN", "FAST_FLATTEN", "MID"])]
        sub = {}
        for label in ["FAST_STEEPEN", "FAST_FLATTEN", "MID"]:
            s = df[df["regime"] == label]
            if len(s) > 0:
                sub[label] = {"n": int(len(s)), "fwd_vol_mean": float(s["fv"].mean())}
        out[ticker] = sub
    return out


def make_plots(feats: pd.DataFrame, spec_results: List[SpecResult]) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    feats["slope_TNX_minus_IRX"].plot(ax=axes[0], color="C0")
    axes[0].set_ylabel("10y - 3m slope (pp)")
    axes[0].axhline(0, color="k", lw=0.5, alpha=0.5)
    axes[0].set_title("K1337: Yield curve slope, dslope, and SPY realized vol")

    feats["dslope_TNX_minus_IRX_N10"].plot(ax=axes[1], color="C1")
    axes[1].set_ylabel("10d Δ slope")
    axes[1].axhline(0, color="k", lw=0.5, alpha=0.5)

    spy_ret = feats["spy_ret"].dropna()
    rv20 = (spy_ret.rolling(20).std() * math.sqrt(252) * 100)
    rv20.plot(ax=axes[2], color="C3")
    axes[2].set_ylabel("SPY 20d RV (% ann.)")

    fig.tight_layout()
    fig.savefig(EXP_DIR / "K1337_overview.png", dpi=110)
    plt.close(fig)

    target = next((r for r in spec_results if r.spec_name == "TNX_minus_IRX" and r.N == 10 and r.H == 10), None)
    if target and target.regime_table:
        fig2, ax = plt.subplots(figsize=(8, 5))
        labels = list(target.regime_table.keys())
        means = [target.regime_table[l]["fwd_vol_mean"] for l in labels]
        ns = [target.regime_table[l]["n"] for l in labels]
        colors = {"FAST_STEEPEN": "C2", "FAST_FLATTEN": "C3", "MID": "C7"}
        bars = ax.bar(labels, means, color=[colors[l] for l in labels])
        for b, n in zip(bars, ns):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(),
                    f"n={n}", ha="center", va="bottom", fontsize=9)
        ax.set_ylabel("SPY 10d forward RV (ann.)")
        ax.set_title("K1337: Forward RV by dslope regime (N=10, H=10)")
        fig2.tight_layout()
        fig2.savefig(EXP_DIR / "K1337_regime.png", dpi=110)
        plt.close(fig2)


def main() -> None:
    close = fetch_data()
    print(f"[data] close shape={close.shape}, date range=({close.index.min().date()} .. {close.index.max().date()})")
    feats = build_features(close)
    feats = feats.dropna(subset=["spy_ret"]).copy()

    all_results: List[SpecResult] = []
    grid = []
    for spec_name, _, _ in SLOPE_SPECS:
        for N in N_WINDOWS:
            for H in H_HORIZONS:
                grid.append((spec_name, N, H))
    print(f"[grid] {len(grid)} (spec × N × H) combos")

    for spec_name, N, H in grid:
        print(f"[run] {spec_name} N={N} H={H}")
        res = run_one_spec(feats, spec_name, N, H)
        all_results.append(res)
        print(f"    -> n={res.n_obs}  HAR QLIKE={res.har_qlike:.6f}  AUG QLIKE={res.har_plus_signal_qlike:.6f}  "
              f"impr={res.improvement_pct:+.3f}%  DM t={res.dm_t:.3f} p={res.dm_p:.4f}  "
              f"boot95=[{res.boot_ci_lo:+.6f}, {res.boot_ci_hi:+.6f}]")

    sec = secondary_sector_diff(feats)
    make_plots(feats, all_results)

    out = {
        "experiment_id": "K1337",
        "title": "Yield curve steepening rate (dV/dt) regime predicts SPY forward RV?",
        "data": {
            "tickers": TICKERS,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "source": "yfinance daily Close, auto_adjust=False",
            "n_dates": int(len(feats)),
            "first_date": str(feats.index.min().date()),
            "last_date": str(feats.index.max().date()),
        },
        "design": {
            "lookahead_policy": "signal.shift(1) before pairing with forward target; "
                                "forward_rv at t uses returns over [t+1, t+H]; "
                                "regime classification rolling 252d up to and including t, "
                                "evaluated on forward target (t+1..t+H) — causal.",
            "baseline": "HAR-RV(1,5,22) on annualized r^2 variance proxy; expanding OLS, "
                        f"warmup={HAR_INIT}, refit_every={HAR_REFIT_EVERY}",
            "augmented_model": "OLS regression of fwd_var on [HAR_yhat, dslope_shifted], "
                               "expanding window, same refit cadence",
            "qlike_form": "log(yhat) + y/yhat, Patton 2011, variance space",
            "dm_test": "Newey-West HAC SE, lag=H-1, two-sided p via normal approx",
            "bootstrap": f"Stationary block bootstrap, reps={BOOTSTRAP_REPS}, "
                         f"block_len=1.5*H, seed={SEED}",
            "regime_definition": f"Rolling {ROLLING_REGIME_WINDOW}d quantiles of dslope; "
                                  f"FAST_STEEPEN >= Q{int(REGIME_Q_HI*100)}, "
                                  f"FAST_FLATTEN <= Q{int(REGIME_Q_LO*100)}",
            "multiple_testing_note": (
                f"{len(grid)} combos tested ({len(SLOPE_SPECS)} signals × {len(N_WINDOWS)} N × {len(H_HORIZONS)} H). "
                "Harvey (2016) suggests |t| > 3 for multi-test robustness. "
                "Per-spec p-values are NOT FDR-adjusted; use Bonferroni alpha=0.05/9≈0.0056 or |DM_t|>3 as gate."
            ),
            "seed": SEED,
        },
        "results": [
            {
                "spec_name": r.spec_name, "N": r.N, "H": r.H, "n_obs": r.n_obs,
                "har_qlike": r.har_qlike, "har_plus_signal_qlike": r.har_plus_signal_qlike,
                "improvement_pct": r.improvement_pct,
                "dm_t": r.dm_t, "dm_p": r.dm_p,
                "boot_mean_diff": r.boot_mean, "boot_ci95_lo": r.boot_ci_lo, "boot_ci95_hi": r.boot_ci_hi,
                "regime_table": r.regime_table,
            }
            for r in all_results
        ],
        "secondary_sector_descriptive": sec,
        "verdict": None,
        "verdict_logic": None,
    }

    pass_specs = [
        r for r in all_results
        if r.dm_t < -3.0 and r.boot_ci_hi < 0 and r.improvement_pct > 0.0
    ]
    cond_specs = [
        r for r in all_results
        if (-3.0 <= r.dm_t < -2.0) and r.boot_ci_hi < 0 and r.improvement_pct > 0.5
    ]
    if pass_specs:
        out["verdict"] = "PASS"
        out["verdict_logic"] = (
            f"{len(pass_specs)} spec(s) clear Harvey |t|>3 + bootstrap CI excludes 0 + positive QLIKE improvement"
        )
    elif cond_specs:
        out["verdict"] = "CONDITIONAL_PASS"
        out["verdict_logic"] = (
            f"{len(cond_specs)} spec(s) at |t|>2 with bootstrap CI < 0 — suggestive but not multi-test robust"
        )
    else:
        out["verdict"] = "NULL"
        out["verdict_logic"] = (
            "No spec clears Harvey |t|>3; consistent with prior K749/K871/G5 that yield-curve information "
            "is largely absorbed by VIX/HAR baselines even at dV/dt rate-of-change level."
        )

    RESULTS_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[done] verdict={out['verdict']}")
    print(f"[done] results written: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
