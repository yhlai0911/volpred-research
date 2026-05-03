"""K1265 — VIX-Managed Portfolio (Moreira-Muir 2017 replication + VIX extension)

4 specs (long-only, monthly rebalance):
  1. buy_hold        : 100% SPY (baseline)
  2. vol_target_static: w = min(1.0, target_vol / RV_{t-1}), target_vol=15%
  3. mm_rv_managed   : w = c / RV^2_{t-1}, c calibrated in-sample (1993-2003) so unconditional weight = 1.0 in-sample
  4. mm_vix_managed  : w = c / VIX^2_{t-1}, c calibrated same way using VIX

Lookahead controls:
- All weights based on signal at t-1 (.shift(1)); returns realised at t
- Calibration uses ONLY in-sample window (1993-2003); OOS is 2004-2026
- monthly rebalance: weight set on rebalance date using info known at close of t-1, applied through next rebalance

Outputs:
- experiments/k1265/k1265_results.json   (metrics, DM tests, bootstrap CI, sub-period)
- experiments/k1265/k1265_cumulative_returns.png
- experiments/k1265/k1265_rolling_sharpe.png
- experiments/k1265/k1265_weight_history.png

References:
  Moreira & Muir (2017). Volatility-Managed Portfolios. Journal of Finance 72(4), 1611-1644.
  Liu et al. (2024). Volatility-managed portfolio across asset classes. International Review of Financial Analysis.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
SEED = 42
np.random.seed(SEED)

EXPERIMENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPERIMENT_DIR.parent.parent
DATA_DIR = REPO_ROOT / "data"

IN_SAMPLE_END = "2003-12-31"
OOS_START = "2004-01-01"
OOS_END = "2026-04-30"
TARGET_VOL = 0.15           # 15% annualised target for vol_target_static
RV_WINDOW = 22              # 22-day rolling window for realised vol (~1 month)
TRADING_DAYS = 252
WEIGHT_CAP = 5.0            # avoid runaway leverage when RV very small (consistent with M&M sec V)
SUBPERIODS = [
    ("2004-2009", "2004-01-01", "2009-12-31"),
    ("2010-2019", "2010-01-01", "2019-12-31"),
    ("2020-2026", "2020-01-01", "2026-04-30"),
]
BOOTSTRAP_N = 10000
BOOTSTRAP_BLOCK_MEAN = 22   # ~1 month avg block length for stationary bootstrap


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _load_yf_csv(path: Path, value_col: str) -> pd.Series:
    """Load yfinance multi-row-header csv -> a single Close series."""
    raw = pd.read_csv(path, header=[0, 1], index_col=0)
    # find the column whose top level matches value_col
    cols = [c for c in raw.columns if c[0] == value_col]
    if not cols:
        raise ValueError(f"No column {value_col!r} in {path}")
    series = raw[cols[0]]
    series.index = pd.to_datetime(series.index, errors="coerce")
    series = series[series.index.notna()].astype(float).sort_index()
    series.name = value_col
    return series


def load_data() -> pd.DataFrame:
    spy_close = _load_yf_csv(DATA_DIR / "spy_daily.csv", "Close")
    vix_close = _load_yf_csv(DATA_DIR / "vix_daily.csv", "Close")

    df = pd.DataFrame({"spy_close": spy_close, "vix_close": vix_close})
    df = df.dropna()
    df["ret"] = df["spy_close"].pct_change()
    # 22-day rolling realised vol (annualised)
    df["rv_daily"] = df["ret"].rolling(RV_WINDOW).std()
    df["rv_ann"] = df["rv_daily"] * np.sqrt(TRADING_DAYS)
    # VIX expressed as decimal
    df["vix_dec"] = df["vix_close"] / 100.0
    df = df.dropna()
    return df


# ---------------------------------------------------------------------------
# Strategy weight construction
# ---------------------------------------------------------------------------
def _calibrate_c(signal_in_sample: pd.Series) -> float:
    """Find c so unconditional in-sample mean of clip(c / sig^2, 0, WEIGHT_CAP) == 1.0.

    We use a closed-form first guess then numerically tighten so the average
    weight across in-sample period equals 1.0 (matches Moreira & Muir's
    normalisation; ensures fair Sharpe comparison vs buy-hold).
    """
    sig2 = signal_in_sample.dropna() ** 2
    # initial c so E[c / sig2] approx 1
    c0 = 1.0 / (1.0 / sig2).mean()
    # numeric refine respecting WEIGHT_CAP
    c = c0
    for _ in range(200):
        weights = np.clip(c / sig2, 0.0, WEIGHT_CAP)
        mean_w = weights.mean()
        if abs(mean_w - 1.0) < 1e-6:
            break
        c *= 1.0 / mean_w
    return float(c)


def build_weights(df: pd.DataFrame) -> pd.DataFrame:
    """Build raw daily weights for each strategy. Lookahead-safe via .shift(1)."""

    # Signals (RV / VIX) lagged by one trading day so they're known at close of t-1
    rv_lag = df["rv_ann"].shift(1)
    vix_lag = df["vix_dec"].shift(1)

    # Calibrate c using IN-SAMPLE (1993-end_2003) signals only
    rv_in = rv_lag.loc[:IN_SAMPLE_END]
    vix_in = vix_lag.loc[:IN_SAMPLE_END]
    c_rv = _calibrate_c(rv_in)
    c_vix = _calibrate_c(vix_in)

    weights = pd.DataFrame(index=df.index)
    weights["buy_hold"] = 1.0
    weights["vol_target_static"] = np.minimum(1.0, TARGET_VOL / rv_lag).clip(lower=0.0)
    weights["mm_rv_managed"] = np.clip(c_rv / (rv_lag ** 2), 0.0, WEIGHT_CAP)
    weights["mm_vix_managed"] = np.clip(c_vix / (vix_lag ** 2), 0.0, WEIGHT_CAP)

    weights = weights.dropna()
    weights.attrs["c_rv"] = c_rv
    weights.attrs["c_vix"] = c_vix
    return weights


def monthly_rebalance(weights: pd.DataFrame) -> pd.DataFrame:
    """Hold weight constant within month; reset on first trading day of new month
    using the weight available at close of previous month-end day.
    All inputs are already lagged via .shift(1) inside build_weights.
    """
    rebalanced = pd.DataFrame(index=weights.index, columns=weights.columns, dtype=float)
    month_id = weights.index.to_period("M")
    is_first_of_month = month_id != pd.Series(month_id, index=weights.index).shift(1)
    is_first_of_month.iloc[0] = True
    current = None
    for ts, row in weights.iterrows():
        if is_first_of_month.loc[ts]:
            current = row.copy()
        rebalanced.loc[ts] = current
    return rebalanced


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------
def annualised_metrics(returns: pd.Series) -> dict:
    r = returns.dropna()
    if len(r) < 2:
        return {"n": int(len(r))}
    mu = r.mean() * TRADING_DAYS
    sd = r.std(ddof=1) * np.sqrt(TRADING_DAYS)
    sharpe = mu / sd if sd > 0 else float("nan")
    cum = (1.0 + r).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    mdd = dd.min()
    calmar = (mu / abs(mdd)) if mdd < 0 else float("nan")
    return {
        "n": int(len(r)),
        "annual_return": float(mu),
        "annual_vol": float(sd),
        "sharpe": float(sharpe),
        "max_drawdown": float(mdd),
        "calmar": float(calmar),
        "total_return": float(cum.iloc[-1] - 1.0),
    }


def turnover_annual(weights_daily: pd.Series) -> float:
    diffs = weights_daily.diff().abs().dropna()
    months_per_year = 12
    # since weights only change at month start, sum of |dW| over year ~ monthly turnover * 12
    n_years = max(len(weights_daily) / TRADING_DAYS, 1.0)
    return float(diffs.sum() / n_years)


# ---------------------------------------------------------------------------
# DM-HLN with Newey-West auto bandwidth
# ---------------------------------------------------------------------------
def _newey_west_lrv(x: np.ndarray, max_lag: int) -> float:
    n = len(x)
    x = x - x.mean()
    gamma0 = float(np.dot(x, x) / n)
    s = gamma0
    for k in range(1, max_lag + 1):
        gamma_k = float(np.dot(x[k:], x[:-k]) / n)
        w = 1.0 - k / (max_lag + 1)
        s += 2.0 * w * gamma_k
    return s


def dm_hln(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> dict:
    """Diebold-Mariano with Harvey-Leybourne-Newbold small-sample correction.

    For Sharpe-style portfolio comparison we use d_t = r_a_t - r_b_t (returns)
    so positive mean = strategy A outperforms B in mean. p-value is from t with n-1 df.
    """
    d = loss_a - loss_b
    n = len(d)
    if n < 5:
        return {"t": float("nan"), "p_value": float("nan"), "n": int(n)}
    # auto bandwidth: floor(4*(n/100)^(2/9)) (Newey-West rule of thumb)
    max_lag = max(int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))), h - 1)
    lrv = _newey_west_lrv(d, max_lag)
    if lrv <= 0:
        return {"t": float("nan"), "p_value": float("nan"), "n": int(n), "max_lag": max_lag}
    dm_stat = d.mean() / np.sqrt(lrv / n)
    # HLN small-sample correction
    correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = dm_stat * correction
    # two-sided p value using t distribution with n-1 df
    from scipy.stats import t as student_t
    p = 2.0 * (1.0 - student_t.cdf(abs(t_stat), df=n - 1))
    return {"t": float(t_stat), "p_value": float(p), "n": int(n), "max_lag": int(max_lag)}


# ---------------------------------------------------------------------------
# Stationary bootstrap CI for Sharpe
# ---------------------------------------------------------------------------
def stationary_bootstrap_indices(n: int, mean_block: int, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / mean_block
    idx = np.empty(n, dtype=int)
    idx[0] = rng.integers(0, n)
    for i in range(1, n):
        if rng.random() < p:
            idx[i] = rng.integers(0, n)
        else:
            idx[i] = (idx[i - 1] + 1) % n
    return idx


def bootstrap_sharpe_ci(returns: np.ndarray, n_boot: int, mean_block: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = len(returns)
    if n < 30:
        return {"sharpe_lo": float("nan"), "sharpe_hi": float("nan"), "n_boot": 0}
    sharpes = np.empty(n_boot)
    for b in range(n_boot):
        idx = stationary_bootstrap_indices(n, mean_block, rng)
        sample = returns[idx]
        sd = sample.std(ddof=1)
        if sd > 0:
            sharpes[b] = (sample.mean() / sd) * np.sqrt(TRADING_DAYS)
        else:
            sharpes[b] = np.nan
    sharpes = sharpes[~np.isnan(sharpes)]
    lo, hi = np.percentile(sharpes, [2.5, 97.5])
    return {"sharpe_lo": float(lo), "sharpe_hi": float(hi), "n_boot": int(len(sharpes))}


def bootstrap_sharpe_diff_ci(ret_a: np.ndarray, ret_b: np.ndarray, n_boot: int, mean_block: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = len(ret_a)
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        idx = stationary_bootstrap_indices(n, mean_block, rng)
        sa = ret_a[idx]; sb = ret_b[idx]
        if sa.std(ddof=1) > 0 and sb.std(ddof=1) > 0:
            diffs[b] = (sa.mean() / sa.std(ddof=1) - sb.mean() / sb.std(ddof=1)) * np.sqrt(TRADING_DAYS)
        else:
            diffs[b] = np.nan
    diffs = diffs[~np.isnan(diffs)]
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"diff_lo": float(lo), "diff_hi": float(hi), "n_boot": int(len(diffs))}


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
COLORS = {
    "buy_hold": "#1f77b4",
    "vol_target_static": "#2ca02c",
    "mm_rv_managed": "#ff7f0e",
    "mm_vix_managed": "#d62728",
}


def plot_cumulative(ret_df: pd.DataFrame, out: Path) -> None:
    cum = (1.0 + ret_df).cumprod()
    fig, ax = plt.subplots(figsize=(10, 6))
    for col in ret_df.columns:
        ax.plot(cum.index, cum[col], label=col, color=COLORS.get(col), linewidth=1.5)
    ax.set_yscale("log")
    ax.set_title("K1265 Cumulative Returns (log scale, OOS 2004-2026)")
    ax.set_ylabel("$1 invested → ($)")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def plot_rolling_sharpe(ret_df: pd.DataFrame, out: Path) -> None:
    window = TRADING_DAYS * 3  # 3-year rolling
    rs = ret_df.rolling(window).apply(lambda r: (r.mean() / r.std(ddof=1)) * np.sqrt(TRADING_DAYS) if r.std(ddof=1) > 0 else np.nan)
    fig, ax = plt.subplots(figsize=(10, 6))
    for col in ret_df.columns:
        ax.plot(rs.index, rs[col], label=col, color=COLORS.get(col), linewidth=1.3)
    ax.set_title("K1265 3-Year Rolling Sharpe Ratio (OOS 2004-2026)")
    ax.set_ylabel("Annualised Sharpe (3y window)")
    ax.set_xlabel("Date")
    ax.axhline(0.0, color="black", linewidth=0.5)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def plot_weights(weights_df: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    for col in weights_df.columns:
        ax.plot(weights_df.index, weights_df[col], label=col, color=COLORS.get(col), linewidth=1.0, alpha=0.85)
    ax.set_title("K1265 Strategy Weights Over Time (OOS 2004-2026)")
    ax.set_ylabel("Portfolio weight (× SPY)")
    ax.set_xlabel("Date")
    ax.axhline(1.0, color="black", linewidth=0.5, linestyle="--")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()

    weights_raw = build_weights(df)
    weights = monthly_rebalance(weights_raw)

    # Align: returns happen at t, weight in effect at t was set using info from t-1
    rets = df.loc[weights.index, "ret"]

    strat_returns = pd.DataFrame(index=weights.index)
    for col in weights.columns:
        strat_returns[col] = weights[col] * rets

    # ------------------------------------------------------------------
    # OOS slice
    # ------------------------------------------------------------------
    oos_returns = strat_returns.loc[OOS_START:OOS_END].dropna()
    oos_weights = weights.loc[OOS_START:OOS_END]

    # full-OOS metrics
    full_metrics = {col: annualised_metrics(oos_returns[col]) for col in oos_returns.columns}
    for col in oos_returns.columns:
        full_metrics[col]["turnover_annual"] = turnover_annual(oos_weights[col])

    # DM-HLN vs buy_hold (positive t = strategy beats buy_hold in mean return)
    dm_results = {}
    for col in oos_returns.columns:
        if col == "buy_hold":
            continue
        dm_results[col] = dm_hln(oos_returns[col].values, oos_returns["buy_hold"].values, h=1)

    # Sharpe CI bootstrap
    boot_results = {}
    for col in oos_returns.columns:
        boot_results[col] = bootstrap_sharpe_ci(oos_returns[col].values, BOOTSTRAP_N, BOOTSTRAP_BLOCK_MEAN, SEED)

    # Sharpe-diff CI vs buy_hold
    boot_diff = {}
    for col in oos_returns.columns:
        if col == "buy_hold":
            continue
        boot_diff[col] = bootstrap_sharpe_diff_ci(
            oos_returns[col].values,
            oos_returns["buy_hold"].values,
            BOOTSTRAP_N,
            BOOTSTRAP_BLOCK_MEAN,
            SEED,
        )

    # Sub-period analysis
    subperiod_results = {}
    for label, start, end in SUBPERIODS:
        sub_ret = oos_returns.loc[start:end]
        if sub_ret.empty:
            continue
        sub = {col: annualised_metrics(sub_ret[col]) for col in sub_ret.columns}
        sub_dm = {}
        for col in sub_ret.columns:
            if col == "buy_hold":
                continue
            sub_dm[col] = dm_hln(sub_ret[col].values, sub_ret["buy_hold"].values, h=1)
        subperiod_results[label] = {"start": start, "end": end, "metrics": sub, "dm_vs_buy_hold": sub_dm}

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------
    gates = {}
    bh_sharpe = full_metrics["buy_hold"]["sharpe"]
    bh_mdd = abs(full_metrics["buy_hold"]["max_drawdown"])
    for col in oos_returns.columns:
        if col == "buy_hold":
            continue
        delta_sharpe = full_metrics[col]["sharpe"] - bh_sharpe
        dm_p = dm_results[col]["p_value"]
        # sign agreement across sub-periods (positive sharpe diff)
        signs = []
        for label in subperiod_results:
            try:
                sub_diff = subperiod_results[label]["metrics"][col]["sharpe"] - subperiod_results[label]["metrics"]["buy_hold"]["sharpe"]
                signs.append(sub_diff > 0)
            except KeyError:
                pass
        sign_agreement = sum(signs)
        mdd_ratio = abs(full_metrics[col]["max_drawdown"]) / bh_mdd if bh_mdd > 0 else float("nan")
        gates[col] = {
            "delta_sharpe": float(delta_sharpe),
            "delta_sharpe_gt_0_15": bool(delta_sharpe > 0.15),
            "dm_p_value": dm_p,
            "dm_p_lt_0_10": bool(dm_p < 0.10) if not np.isnan(dm_p) else False,
            "subperiod_positive": int(sign_agreement),
            "subperiod_positive_ge_2": bool(sign_agreement >= 2),
            "mdd_ratio": float(mdd_ratio),
            "mdd_ratio_lt_1_2": bool(mdd_ratio < 1.2),
        }
        gates[col]["all_pass"] = bool(
            gates[col]["delta_sharpe_gt_0_15"]
            and gates[col]["dm_p_lt_0_10"]
            and gates[col]["subperiod_positive_ge_2"]
            and gates[col]["mdd_ratio_lt_1_2"]
        )

    any_pass = any(g["all_pass"] for g in gates.values())
    if any_pass:
        verdict = "PASS"
    else:
        verdict = "NULL"

    # ------------------------------------------------------------------
    # Plots
    # ------------------------------------------------------------------
    plot_cumulative(oos_returns, EXPERIMENT_DIR / "k1265_cumulative_returns.png")
    plot_rolling_sharpe(oos_returns, EXPERIMENT_DIR / "k1265_rolling_sharpe.png")
    plot_weights(oos_weights, EXPERIMENT_DIR / "k1265_weight_history.png")

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    results = {
        "experiment_id": "k1265",
        "title": "VIX-Managed Portfolio (Moreira-Muir 2017 replication + VIX extension)",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "spy_source": "yfinance SPY auto_adjust=True",
            "vix_source": "yfinance ^VIX Close",
            "in_sample": ["1993-01-29", IN_SAMPLE_END],
            "oos": [OOS_START, OOS_END],
            "n_obs_oos": int(len(oos_returns)),
        },
        "calibration": {
            "c_rv": float(weights_raw.attrs["c_rv"]),
            "c_vix": float(weights_raw.attrs["c_vix"]),
            "in_sample_avg_weight_target": 1.0,
            "weight_cap": WEIGHT_CAP,
            "target_vol_static": TARGET_VOL,
            "rv_window": RV_WINDOW,
        },
        "metrics_oos": full_metrics,
        "dm_hln_vs_buy_hold": dm_results,
        "bootstrap_sharpe_ci": boot_results,
        "bootstrap_sharpe_diff_vs_buy_hold": boot_diff,
        "subperiod": subperiod_results,
        "gates": gates,
        "verdict": verdict,
        "notes": [
            "Lookahead-controlled: weight at t uses signal at t-1 (.shift(1)).",
            "c_rv and c_vix calibrated using IN-SAMPLE 1993-2003 only; reported metrics are OOS 2004-2026.",
            "Monthly rebalance applied to lagged signal (no end-of-month look-ahead).",
            "Weight cap 5x to prevent runaway leverage in low-vol windows; consistent with Moreira-Muir Sec V.",
            "Long-only (negative weights clipped to 0).",
            f"Stationary bootstrap n={BOOTSTRAP_N}, mean block={BOOTSTRAP_BLOCK_MEAN}, seed={SEED}.",
        ],
    }

    with open(EXPERIMENT_DIR / "k1265_results.json", "w") as f:
        json.dump(results, f, indent=2, default=float)

    # console summary
    print("=" * 70)
    print(f"K1265 verdict: {verdict}")
    print(f"OOS window: {OOS_START} -> {OOS_END} ({len(oos_returns)} obs)")
    print(f"c_rv={results['calibration']['c_rv']:.6f}  c_vix={results['calibration']['c_vix']:.6f}")
    print()
    print(f"{'Strategy':<22} {'Sharpe':>8} {'AnnRet':>8} {'AnnVol':>8} {'MDD':>8} {'TurnAnn':>8}")
    for col in oos_returns.columns:
        m = full_metrics[col]
        print(f"{col:<22} {m['sharpe']:>8.3f} {m['annual_return']:>8.3f} {m['annual_vol']:>8.3f} {m['max_drawdown']:>8.3f} {m['turnover_annual']:>8.2f}")
    print()
    for col, dm in dm_results.items():
        print(f"DM vs buy_hold {col:<20}: t={dm['t']:.3f}  p={dm['p_value']:.4f}  lag={dm['max_lag']}")
    print()
    for col, g in gates.items():
        print(f"Gate {col:<20}: ΔSharpe={g['delta_sharpe']:+.3f} (>0.15? {g['delta_sharpe_gt_0_15']}) | "
              f"DM p={g['dm_p_value']:.3f} (<0.10? {g['dm_p_lt_0_10']}) | "
              f"sub-positive {g['subperiod_positive']}/3 (≥2? {g['subperiod_positive_ge_2']}) | "
              f"MDD ratio {g['mdd_ratio']:.2f} (<1.2? {g['mdd_ratio_lt_1_2']}) | "
              f"ALL PASS? {g['all_pass']}")


if __name__ == "__main__":
    main()
