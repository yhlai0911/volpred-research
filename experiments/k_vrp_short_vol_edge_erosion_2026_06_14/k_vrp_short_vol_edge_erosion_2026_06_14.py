#!/usr/bin/env python3
"""K1476: VRP decline (post-2018) and short-vol strategy edge erosion.

Hypotheses (all explicitly tested):
- H1: Variance Risk Premium (VRP) — defined as ex-ante VIX^2 minus realized
  variance over the same month — has a statistically lower mean in the
  post-2018 regime relative to the 2006-2017 regime.
- H2: A naive long-SVXY (and short-VXX) monthly rebalance strategy delivers
  weaker Sharpe / worse max drawdown in the post-2018 regime.
- H3: The contemporaneous and 1-month forward correlation between VRP and
  short-vol strategy return is structurally weaker post-2018.

Data sources: ^VIX, ^GSPC, VXX, SVXY (yfinance close-to-close).

Lookahead controls:
- VRP_t uses VIX_close at the LAST trading day of month (t-1) as ex-ante and
  realized variance over month t. This is a *measure* (not a trading signal);
  it is the canonical Bollerslev-Tauchen-Zhou (2009) construction.
- For predictability tests, VRP_t (known at month-end) is paired with strategy
  return r_{t+1} (next month). No lookahead.
- Strategy returns are computed as in-month price returns from first to last
  trading day of the month (long SVXY); no forward-looking allocation.

Random seed (bootstrap, n=1000): 42.

Output:
- results JSON (sample sizes, p-values, Sharpe / MDD per regime, correlations,
  bootstrap CIs).
- 2 PNG figures: VRP regime time series, rolling 36-mo Sharpe of short-vol.

Run: uv run python experiments/k_vrp_short_vol_edge_erosion_2026_06_14/k_vrp_short_vol_edge_erosion_2026_06_14.py
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

EXP_ID = "k_vrp_short_vol_edge_erosion_2026_06_14"
K_ID = "K1476"
OUT_DIR = Path(__file__).resolve().parent

SEED = 42
N_BOOT = 1000
# Primary regime boundary chosen ex-ante: post-Feb-2018 XIV blowup era starts
# 2018-02-05 when XIV imploded; we use 2018-03-01 (next full month) as the
# canonical break. We additionally report robustness at 2018-01-01 and
# 2019-01-01. The "VRP decline" framing (Chicago Fed 2025) also points to
# post-COVID regime; we therefore add 2020-04-01 as a secondary check.
REGIME_BOUNDARY = pd.Timestamp("2018-03-01")
ALT_BOUNDARIES = [
    pd.Timestamp("2018-01-01"),
    pd.Timestamp("2019-01-01"),
    pd.Timestamp("2020-04-01"),
]
START = "2006-01-01"
END = "2026-06-13"


# ------------------------- Data ------------------------- #


def fetch_daily(ticker: str, start: str = START, end: str = END) -> pd.Series:
    """Fetch close prices; return Series indexed by date."""
    df = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned empty for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Adj Close"] if "Adj Close" in df.columns else df["Close"]
    close = close.dropna()
    close.name = ticker
    return close


# ------------------------- VRP construction ------------------------- #


def compute_monthly_vrp(vix: pd.Series, spx: pd.Series) -> pd.DataFrame:
    """Construct VRP at monthly frequency.

    VRP_t = VIX^2 (at month-end of t-1, ex-ante) - RV^2 (realized over month t).

    Returns DataFrame with columns:
      - vix_ex_ante: VIX at last trading day of t-1 (start of month t)
      - rv_ann: realized vol annualized (sqrt(sum r^2 * 252/n))
      - vrp: vix_ex_ante^2 - rv_ann^2 (both in "vol points squared" units,
             i.e. percent^2 like VIX^2)
      - month_obs: number of trading days observed in the month (used to
        drop the final partial month).
    """
    spx_ret = np.log(spx / spx.shift(1)).dropna()
    # daily squared returns -> sum over month -> annualize
    spx_ret2 = spx_ret.pow(2)
    by_m = spx_ret2.groupby(pd.Grouper(freq="ME"))
    n_obs = by_m.count()
    rv_var_ann = by_m.sum() * 252.0 / n_obs  # variance annualized
    rv_ann = np.sqrt(rv_var_ann) * 100.0  # vol in "VIX units" (percent)

    # VIX at last trading day prior to month start
    vix_eom = vix.resample("ME").last()
    vix_ex_ante = vix_eom.shift(1)  # known before month begins -> no lookahead

    df = pd.DataFrame(
        {
            "vix_ex_ante": vix_ex_ante,
            "rv_ann": rv_ann,
            "month_obs": n_obs,
        }
    ).dropna()
    df["vrp"] = df["vix_ex_ante"] ** 2 - df["rv_ann"] ** 2  # vol-points^2
    # Drop final partial month (fewer than 15 trading days observed)
    df = df[df["month_obs"] >= 15]
    return df


def newey_west_auto_lag(n: int) -> int:
    """Newey-West (1994) automatic lag selection: floor(4 * (T/100)^(2/9))."""
    return max(1, int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))))


# ------------------------- Short-vol strategy ------------------------- #


def monthly_close_to_close_return(price: pd.Series) -> pd.Series:
    eom = price.resample("ME").last()
    ret = eom.pct_change().dropna()
    return ret


def collateralized_short_return(vxx_ret: pd.Series) -> pd.Series:
    """Convert raw -VXX simple-return into a fully cash-collateralized
    short-position return, bounded so that monthly equity cannot go below 0.

    Mechanically: 1 + r_short = max(0, 1 - r_vxx). The position is wiped out
    if VXX rallies more than 100% in a month (e.g. Feb 2018 XIV scenario).
    """
    raw = -vxx_ret
    floored_equity = np.maximum(0.0, 1.0 + raw)
    return floored_equity - 1.0


def annualized_sharpe(monthly_ret: pd.Series, rf: float = 0.0) -> float:
    if len(monthly_ret) < 6:
        return float("nan")
    mu = monthly_ret.mean() * 12 - rf
    sd = monthly_ret.std(ddof=1) * np.sqrt(12)
    if sd == 0 or math.isnan(sd):
        return float("nan")
    return float(mu / sd)


def max_drawdown(monthly_ret: pd.Series) -> float:
    if monthly_ret.empty:
        return float("nan")
    eq = (1.0 + monthly_ret).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min())


# ------------------------- Tests ------------------------- #


def welch_t_test(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    from scipy import stats

    t, p = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
    return float(t), float(p)


def newey_west_mean_test(x: np.ndarray, lag: int = 3) -> tuple[float, float, float]:
    """Return (mean, NW SE, t-stat) for H0: mean=0 with HAC SE."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 5:
        return (float("nan"), float("nan"), float("nan"))
    mu = x.mean()
    d = x - mu
    g0 = (d @ d) / n
    s = g0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)
        gk = (d[k:] @ d[:-k]) / n
        s += 2.0 * w * gk
    se = math.sqrt(s / n) if s > 0 else float("nan")
    t = mu / se if se and not math.isnan(se) else float("nan")
    return float(mu), float(se), float(t)


def nw_diff_mean_test(
    a: np.ndarray, b: np.ndarray, lag: int = 3
) -> tuple[float, float, float, float]:
    """HAC-robust test of mean(a)-mean(b). Returns (diff, se, t, p_two_sided).

    Treats a and b as two independent (HAC) samples; SE adds variances.
    """
    from scipy import stats

    _, sea, _ = newey_west_mean_test(a, lag=lag)
    _, seb, _ = newey_west_mean_test(b, lag=lag)
    a = np.asarray(a, dtype=float)
    a = a[~np.isnan(a)]
    b = np.asarray(b, dtype=float)
    b = b[~np.isnan(b)]
    diff = a.mean() - b.mean()
    if math.isnan(sea) or math.isnan(seb):
        return (diff, float("nan"), float("nan"), float("nan"))
    se = math.sqrt(sea**2 + seb**2)
    t = diff / se if se > 0 else float("nan")
    # two-sided p from normal approx (lots of dof in monthly samples)
    p = 2.0 * (1.0 - stats.norm.cdf(abs(t)))
    return float(diff), float(se), float(t), float(p)


def bootstrap_sharpe_ci(
    monthly_ret: pd.Series,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    arr = monthly_ret.dropna().to_numpy()
    n = len(arr)
    if n < 12:
        return (float("nan"), float("nan"), float("nan"))
    samples = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        sample = arr[idx]
        mu = sample.mean() * 12
        sd = sample.std(ddof=1) * np.sqrt(12)
        samples[i] = mu / sd if sd > 0 else np.nan
    samples = samples[~np.isnan(samples)]
    point = annualized_sharpe(monthly_ret)
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def bootstrap_corr_ci(
    x: pd.Series, y: pd.Series, n_boot: int = N_BOOT, seed: int = SEED
) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    df = pd.concat([x, y], axis=1).dropna()
    if len(df) < 12:
        return (float("nan"), float("nan"), float("nan"))
    arr = df.to_numpy()
    n = len(arr)
    samples = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        a = arr[idx, 0]
        b = arr[idx, 1]
        if a.std() == 0 or b.std() == 0:
            samples[i] = np.nan
        else:
            samples[i] = np.corrcoef(a, b)[0, 1]
    samples = samples[~np.isnan(samples)]
    point = float(df.iloc[:, 0].corr(df.iloc[:, 1]))
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return point, float(lo), float(hi)


# ------------------------- Main ------------------------- #


@dataclass
class RegimeStats:
    label: str
    period: str
    n: int
    vrp_mean: float
    vrp_median: float
    vrp_std: float
    vrp_share_positive: float
    sharpe_svxy: float
    sharpe_svxy_ci: tuple[float, float]
    mdd_svxy: float
    sharpe_short_vxx: float
    mdd_short_vxx: float


def regime_label(ts: pd.Timestamp) -> str:
    return "A_pre_2018" if ts < REGIME_BOUNDARY else "B_post_2018"


def main() -> None:
    print(f"[{EXP_ID}] start")
    vix = fetch_daily("^VIX")
    spx = fetch_daily("^GSPC")
    vxx = fetch_daily("VXX")
    svxy = fetch_daily("SVXY")

    # VRP monthly
    vrp_df = compute_monthly_vrp(vix, spx)
    vrp_df["regime"] = vrp_df.index.map(regime_label)

    # Strategy monthly returns
    svxy_ret = monthly_close_to_close_return(svxy)
    vxx_ret = monthly_close_to_close_return(vxx)

    short_vxx_ret = collateralized_short_return(vxx_ret)
    # NOTE: yfinance "VXX" history only covers the iPath Series B (post-Jan
    # 2018 reissue). The original Barclays VXX (2009-2017) is not available
    # via yfinance. Therefore short-VXX comparisons are only available in the
    # post-2018 regime; we keep SVXY (data from 2011-10-04) as the primary
    # short-vol strategy for regime comparison.

    # Align everything to common monthly index (month-end)
    panel = pd.concat(
        [
            vrp_df["vrp"].rename("vrp"),
            vrp_df["vix_ex_ante"].rename("vix_ex_ante"),
            vrp_df["rv_ann"].rename("rv_ann"),
            svxy_ret.rename("svxy_ret"),
            short_vxx_ret.rename("short_vxx_ret"),
        ],
        axis=1,
    )
    panel.index.name = "month_end"
    panel = panel[panel.index >= pd.Timestamp(START)]
    # Drop final partial month: keep only months that VRP-side accepted
    # (>=15 trading days observed). This guarantees no June-2026 partial.
    valid_months = vrp_df.index
    panel = panel.loc[panel.index.intersection(valid_months).union(
        panel.index[panel.index < valid_months.min()]
    ).sort_values()]
    # Above keeps history before VRP starts (none expected). Simpler:
    panel = panel.loc[panel.index.isin(valid_months)]

    # Subsamples
    A = panel[panel.index < REGIME_BOUNDARY]
    B = panel[panel.index >= REGIME_BOUNDARY]

    # H1: VRP mean difference (auto NW lag)
    vrp_A = A["vrp"].dropna().to_numpy()
    vrp_B = B["vrp"].dropna().to_numpy()
    nw_lag_h1 = newey_west_auto_lag(min(len(vrp_A), len(vrp_B)))
    t_h1, p_h1 = welch_t_test(vrp_A, vrp_B)
    diff_h1, se_h1, tnw_h1, pnw_h1 = nw_diff_mean_test(vrp_A, vrp_B, lag=nw_lag_h1)

    # H2: Sharpe / MDD per regime for SVXY (long) and -VXX (short)
    sA = A.dropna(subset=["svxy_ret"])["svxy_ret"]
    sB = B.dropna(subset=["svxy_ret"])["svxy_ret"]
    vA = A.dropna(subset=["short_vxx_ret"])["short_vxx_ret"]
    vB = B.dropna(subset=["short_vxx_ret"])["short_vxx_ret"]

    sharpe_sA, lo_sA, hi_sA = bootstrap_sharpe_ci(sA)
    sharpe_sB, lo_sB, hi_sB = bootstrap_sharpe_ci(sB)
    # Short-VXX: report NaN if regime has <12 months (insufficient sample)
    sharpe_vA = annualized_sharpe(vA) if len(vA) >= 12 else float("nan")
    sharpe_vB = annualized_sharpe(vB) if len(vB) >= 12 else float("nan")
    mdd_sA = max_drawdown(sA)
    mdd_sB = max_drawdown(sB)
    mdd_vA = max_drawdown(vA) if len(vA) >= 12 else float("nan")
    mdd_vB = max_drawdown(vB) if len(vB) >= 12 else float("nan")

    # Difference in monthly mean return (HAC, auto lag)
    nw_lag_h2 = newey_west_auto_lag(min(len(sA), len(sB)))
    diff_sret, se_sret, tnw_sret, pnw_sret = nw_diff_mean_test(
        sA.to_numpy(), sB.to_numpy(), lag=nw_lag_h2
    )

    # H3: corr(VRP_t, strategy_ret_{t+1}) per regime — predictive correlation
    # IMPORTANT: classify each (VRP_t, ret_{t+1}) pair by the RETURN month
    # (when the trade actually realizes), not by the VRP month. This prevents
    # Dec-2017 VRP -> Jan-2018 return being booked into the pre-2018 regime.
    panel_pred = panel.copy()
    panel_pred["svxy_next"] = panel_pred["svxy_ret"].shift(-1)
    panel_pred["short_vxx_next"] = panel_pred["short_vxx_ret"].shift(-1)
    # return_month_index of pair (t, t+1) is t+1 month-end
    return_month = panel_pred.index.shift(1, freq="ME")
    panel_pred["return_month"] = return_month
    Ap = panel_pred[panel_pred["return_month"] < REGIME_BOUNDARY]
    Bp = panel_pred[panel_pred["return_month"] >= REGIME_BOUNDARY]

    r_h3_svxy_A, lo_h3_svxy_A, hi_h3_svxy_A = bootstrap_corr_ci(
        Ap["vrp"], Ap["svxy_next"]
    )
    r_h3_svxy_B, lo_h3_svxy_B, hi_h3_svxy_B = bootstrap_corr_ci(
        Bp["vrp"], Bp["svxy_next"]
    )
    r_h3_vxx_A, lo_h3_vxx_A, hi_h3_vxx_A = bootstrap_corr_ci(
        Ap["vrp"], Ap["short_vxx_next"]
    )
    r_h3_vxx_B, lo_h3_vxx_B, hi_h3_vxx_B = bootstrap_corr_ci(
        Bp["vrp"], Bp["short_vxx_next"]
    )

    # ----- Figure 1: VRP time series with regime means ----- #
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(panel.index, panel["vrp"], lw=0.9, color="#2b6cb0", alpha=0.8, label="VRP")
    ax.axhline(0, color="black", lw=0.5, linestyle="--")
    ax.axvline(
        REGIME_BOUNDARY, color="firebrick", lw=1.0, linestyle="--", label="2018-01"
    )
    if len(vrp_A):
        ax.hlines(
            vrp_A.mean(),
            panel.index.min(),
            REGIME_BOUNDARY,
            color="navy",
            lw=2,
            label=f"A mean {vrp_A.mean():.1f}",
        )
    if len(vrp_B):
        ax.hlines(
            vrp_B.mean(),
            REGIME_BOUNDARY,
            panel.index.max(),
            color="darkorange",
            lw=2,
            label=f"B mean {vrp_B.mean():.1f}",
        )
    ax.set_title("Variance Risk Premium (VIX^2 - RV^2) — Monthly, 2006-2026")
    ax.set_ylabel("VRP (vol points^2)")
    ax.set_xlabel("Month-end")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.25)
    plt.tight_layout()
    fig.savefig(OUT_DIR / "fig_vrp_regime.png", dpi=130)
    plt.close(fig)

    # ----- Figure 2: rolling 36m Sharpe — SVXY ----- #
    def rolling_sharpe(monthly_ret: pd.Series, window: int = 36) -> pd.Series:
        mu = monthly_ret.rolling(window).mean() * 12
        sd = monthly_ret.rolling(window).std(ddof=1) * np.sqrt(12)
        return mu / sd

    svxy_full = panel["svxy_ret"].dropna()
    short_vxx_full = panel["short_vxx_ret"].dropna()
    rs_svxy = rolling_sharpe(svxy_full)
    rs_vxx = rolling_sharpe(short_vxx_full)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(rs_svxy.index, rs_svxy, color="#2b6cb0", lw=1.4, label="Long SVXY")
    ax.plot(rs_vxx.index, rs_vxx, color="#d97706", lw=1.4, label="Short VXX")
    ax.axhline(0, color="black", lw=0.5, linestyle="--")
    ax.axvline(
        REGIME_BOUNDARY, color="firebrick", lw=1.0, linestyle="--", label="2018-01"
    )
    ax.set_title("Rolling 36-month Annualized Sharpe — Short-Vol Strategies")
    ax.set_ylabel("Sharpe")
    ax.set_xlabel("Month-end")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(alpha=0.25)
    plt.tight_layout()
    fig.savefig(OUT_DIR / "fig_short_vol_sharpe.png", dpi=130)
    plt.close(fig)

    # ----- Build results JSON ----- #

    def safe_period(idx) -> str:
        if len(idx) == 0:
            return "n/a"
        return f"{idx.min().date().isoformat()} to {idx.max().date().isoformat()}"

    results = {
        "experiment_id": EXP_ID,
        "k_id": K_ID,
        "title": "VRP decline (post-2018) and short-vol strategy edge erosion",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": [
            "yfinance: ^VIX",
            "yfinance: ^GSPC",
            "yfinance: VXX (history starts 2009-01-30)",
            "yfinance: SVXY (history starts 2011-10-04)",
        ],
        "regime_boundary": REGIME_BOUNDARY.date().isoformat(),
        "seed": SEED,
        "bootstrap_n": N_BOOT,
        "regimes": {
            "A_pre_2018": {
                "period": safe_period(A.index),
                "n_months_vrp": int(A["vrp"].notna().sum()),
                "n_months_svxy": int(A["svxy_ret"].notna().sum()),
                "n_months_short_vxx": int(A["short_vxx_ret"].notna().sum()),
                "vrp_mean": float(np.nanmean(vrp_A)) if len(vrp_A) else None,
                "vrp_median": float(np.nanmedian(vrp_A)) if len(vrp_A) else None,
                "vrp_std": float(np.nanstd(vrp_A, ddof=1)) if len(vrp_A) > 1 else None,
                "vrp_share_positive": (
                    float((vrp_A > 0).mean()) if len(vrp_A) else None
                ),
                "sharpe_svxy": sharpe_sA,
                "sharpe_svxy_ci95": [lo_sA, hi_sA],
                "mdd_svxy": mdd_sA,
                "sharpe_short_vxx": sharpe_vA,
                "mdd_short_vxx": mdd_vA,
            },
            "B_post_2018": {
                "period": safe_period(B.index),
                "n_months_vrp": int(B["vrp"].notna().sum()),
                "n_months_svxy": int(B["svxy_ret"].notna().sum()),
                "n_months_short_vxx": int(B["short_vxx_ret"].notna().sum()),
                "vrp_mean": float(np.nanmean(vrp_B)) if len(vrp_B) else None,
                "vrp_median": float(np.nanmedian(vrp_B)) if len(vrp_B) else None,
                "vrp_std": float(np.nanstd(vrp_B, ddof=1)) if len(vrp_B) > 1 else None,
                "vrp_share_positive": (
                    float((vrp_B > 0).mean()) if len(vrp_B) else None
                ),
                "sharpe_svxy": sharpe_sB,
                "sharpe_svxy_ci95": [lo_sB, hi_sB],
                "mdd_svxy": mdd_sB,
                "sharpe_short_vxx": sharpe_vB,
                "mdd_short_vxx": mdd_vB,
            },
        },
        "tests": {
            "H1_vrp_mean_decline": {
                "description": (
                    "Welch t-test and HAC (Newey-West 1994 auto lag) difference "
                    "of mean VRP, A vs B"
                ),
                "nw_lag": nw_lag_h1,
                "welch_t": t_h1,
                "welch_p_two_sided": p_h1,
                "nw_diff_mean": diff_h1,
                "nw_se": se_h1,
                "nw_t": tnw_h1,
                "nw_p_two_sided": pnw_h1,
                "direction": "A_minus_B (positive = VRP declined post-2018)",
            },
            "H2_svxy_monthly_return_diff": {
                "description": (
                    "HAC (Newey-West 1994 auto lag) test of mean SVXY monthly "
                    "return, A vs B"
                ),
                "nw_lag": nw_lag_h2,
                "nw_diff_mean": diff_sret,
                "nw_se": se_sret,
                "nw_t": tnw_sret,
                "nw_p_two_sided": pnw_sret,
                "interpretation": (
                    "Negative diff = SVXY return weaker pre-2018 vs post-2018; "
                    "positive diff = SVXY edge eroded."
                ),
            },
            "H3_predictive_correlation_vrp_strategy_next_month": {
                "description": "corr(VRP_t, strategy_ret_{t+1}) with 1000-bootstrap 95% CI",
                "svxy": {
                    "A_corr": r_h3_svxy_A,
                    "A_ci95": [lo_h3_svxy_A, hi_h3_svxy_A],
                    "B_corr": r_h3_svxy_B,
                    "B_ci95": [lo_h3_svxy_B, hi_h3_svxy_B],
                },
                "short_vxx": {
                    "A_corr": r_h3_vxx_A,
                    "A_ci95": [lo_h3_vxx_A, hi_h3_vxx_A],
                    "B_corr": r_h3_vxx_B,
                    "B_ci95": [lo_h3_vxx_B, hi_h3_vxx_B],
                },
            },
        },
        "figures": [
            "fig_vrp_regime.png",
            "fig_short_vol_sharpe.png",
        ],
        "codex_review": {"status": "pending"},
    }

    # ----- Boundary robustness ----- #
    boundary_robust: dict = {}
    for alt in ALT_BOUNDARIES:
        Aa = panel[panel.index < alt]
        Bb = panel[panel.index >= alt]
        vrpAa = Aa["vrp"].dropna().to_numpy()
        vrpBb = Bb["vrp"].dropna().to_numpy()
        if len(vrpAa) < 12 or len(vrpBb) < 12:
            continue
        lag = newey_west_auto_lag(min(len(vrpAa), len(vrpBb)))
        diff, se, tn, pn = nw_diff_mean_test(vrpAa, vrpBb, lag=lag)
        sAa = Aa.dropna(subset=["svxy_ret"])["svxy_ret"]
        sBb = Bb.dropna(subset=["svxy_ret"])["svxy_ret"]
        sh_a = annualized_sharpe(sAa) if len(sAa) >= 12 else float("nan")
        sh_b = annualized_sharpe(sBb) if len(sBb) >= 12 else float("nan")
        boundary_robust[alt.date().isoformat()] = {
            "n_A": int(len(vrpAa)),
            "n_B": int(len(vrpBb)),
            "vrp_diff_A_minus_B": diff,
            "vrp_nw_t": tn,
            "vrp_nw_p_two_sided": pn,
            "svxy_sharpe_A": sh_a,
            "svxy_sharpe_B": sh_b,
            "svxy_n_A": int(len(sAa)),
            "svxy_n_B": int(len(sBb)),
        }
    results["boundary_robustness"] = boundary_robust

    # ----- Determine verdict (mechanical) ----- #
    h1_pass = (
        (results["tests"]["H1_vrp_mean_decline"]["nw_p_two_sided"] is not None)
        and (results["tests"]["H1_vrp_mean_decline"]["nw_p_two_sided"] < 0.05)
        and (results["tests"]["H1_vrp_mean_decline"]["nw_diff_mean"] > 0)
    )
    sharpe_A = results["regimes"]["A_pre_2018"]["sharpe_svxy"]
    sharpe_B = results["regimes"]["B_post_2018"]["sharpe_svxy"]
    h2_directional = (
        (sharpe_A is not None)
        and (sharpe_B is not None)
        and (not math.isnan(sharpe_A))
        and (not math.isnan(sharpe_B))
        and (sharpe_A > sharpe_B)
    )
    # H3 weakening: |B corr| < |A corr| with non-overlapping CIs would be PASS;
    # we report descriptively.
    rA = results["tests"]["H3_predictive_correlation_vrp_strategy_next_month"]["svxy"][
        "A_corr"
    ]
    rB = results["tests"]["H3_predictive_correlation_vrp_strategy_next_month"]["svxy"][
        "B_corr"
    ]
    if rA is not None and rB is not None and not math.isnan(rA) and not math.isnan(rB):
        h3_weak = abs(rB) < abs(rA)
    else:
        h3_weak = False

    n_pass = sum([h1_pass, h2_directional, h3_weak])
    if n_pass == 3:
        verdict = "PASS"
    elif n_pass == 2:
        verdict = "CONDITIONAL_PASS"
    elif n_pass == 1:
        verdict = "MIXED"
    else:
        verdict = "NULL"

    results["verdict"] = verdict
    results["verdict_breakdown"] = {
        "H1_vrp_declined_p_lt_0p05_and_positive_diff": h1_pass,
        "H2_svxy_sharpe_A_gt_B_directionally": h2_directional,
        "H3_predictive_corr_weaker_in_B_for_svxy": h3_weak,
    }
    results["summary"] = (
        f"VRP A({results['regimes']['A_pre_2018']['vrp_mean']:.1f}) "
        f"vs B({results['regimes']['B_post_2018']['vrp_mean']:.1f}) | "
        f"SVXY Sharpe A={sharpe_A:.2f} vs B={sharpe_B:.2f} | verdict={verdict}"
    )

    out_path = OUT_DIR / f"{EXP_ID}_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"[{EXP_ID}] wrote {out_path}")
    print(f"[{EXP_ID}] verdict={verdict}")
    print(results["summary"])


if __name__ == "__main__":
    main()
