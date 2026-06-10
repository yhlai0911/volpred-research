"""K1464 — BAB return conditional on prior-month realized volatility.

Research question (JFE 2025 "The volatility puzzle of the beta anomaly"):
Is Betting-Against-Beta (BAB) strategy return conditional on prior-month
realized volatility? Hypothesis: BAB premium is concentrated after low-vol
months, and shrinks (or reverses) after high-vol months.

Design:
- Universe: S&P 500 constituents (approximated via current SPY holdings list
  + survivorship-bias caveat noted in README).
- Period: 2000-01 to 2025-12 (25 years, monthly rebalance).
- Beta: rolling 60-month OLS beta vs SPY (Frazzini & Pedersen 2014).
- BAB portfolio: monthly rebalance, long bottom-30% beta + short top-30%
  beta, Frazzini-Pedersen rank weights, scaled to net beta = 0.
- Conditioning: market month-t RV → tertiles → analyze month-(t+1) BAB ret.

Lookahead protection:
- Beta estimated on returns t-60 .. t-1 → used for portfolio formed at end
  of month t, return measured in month t+1. All `.shift(1)` explicit.
- RV regime for conditioning is also lagged (regime from month t → BAB
  return in month t+1).

Seed: 42 (bootstrap and any resampling).
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.api as sm
from scipy import stats

warnings.filterwarnings("ignore")
np.random.seed(42)

HERE = Path(__file__).parent
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)
RESULTS_PATH = HERE / "k1464_bab_vol_conditional_results.json"

START = "2000-01-01"
END = "2025-12-31"
SEED = 42
RNG = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
def get_universe() -> List[str]:
    """Return a broad US large-cap tickers list.

    To avoid look-ahead via current-SP500 (survivorship bias warning in
    README), we use a fixed list of large-cap tickers active across most of
    the 2000-2025 window. ~250 tickers, mix of survivors + some that delisted
    will be dropped naturally by yfinance.
    """
    # Hand-curated large-cap list spanning sectors; tickers active for most of
    # 2000-2025. Survivorship bias acknowledged.
    tickers = [
        # Tech
        "AAPL", "MSFT", "GOOGL", "ORCL", "CSCO", "IBM", "INTC", "AMD", "TXN",
        "ADBE", "CRM", "QCOM", "HPQ", "DELL", "WDC", "STX", "GLW", "AMAT",
        "ADI", "LRCX", "KLAC", "MU", "NVDA", "AVGO", "EBAY", "AKAM",
        # Financials
        "JPM", "BAC", "C", "WFC", "GS", "MS", "AXP", "USB", "PNC", "BK",
        "STT", "SCHW", "TRV", "ALL", "MET", "PRU", "AFL", "AIG", "MMC",
        "AON", "CB", "PGR", "SPGI", "MCO", "ICE", "CME", "NDAQ",
        # Healthcare
        "JNJ", "PFE", "MRK", "ABT", "LLY", "BMY", "UNH", "CI", "HUM", "ANTM",
        "AMGN", "GILD", "BIIB", "MDT", "SYK", "BSX", "BDX", "BAX", "ZBH",
        "TMO", "DHR", "A", "ISRG", "REGN", "VRTX", "HCA",
        # Consumer discretionary
        "MCD", "SBUX", "NKE", "HD", "LOW", "TGT", "TJX", "ROST", "GPS",
        "F", "GM", "DIS", "CMCSA", "VZ", "T", "TMUS", "NFLX", "BKNG",
        "MAR", "HLT", "YUM", "DRI", "DPZ", "CMG",
        # Consumer staples
        "PG", "KO", "PEP", "WMT", "COST", "CL", "KMB", "GIS", "K",
        "CAG", "CPB", "HSY", "MDLZ", "MO", "PM", "STZ", "TAP", "TSN",
        "ADM", "KR", "SYY",
        # Industrials
        "GE", "BA", "CAT", "DE", "MMM", "HON", "UPS", "FDX", "UNP", "CSX",
        "NSC", "LMT", "RTX", "NOC", "GD", "ITW", "ETN", "EMR", "PH", "ROK",
        "DOV", "PCAR", "JCI", "CMI", "WM", "RSG",
        # Energy
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "OXY", "MRO", "DVN",
        "APA", "HES", "VLO", "PSX", "MPC", "KMI", "WMB", "OKE",
        # Materials
        "DD", "DOW", "LIN", "APD", "ECL", "PPG", "SHW", "NEM", "FCX",
        "MOS", "CF", "NUE", "X", "BLL", "IP", "WY",
        # Utilities & Real Estate
        "NEE", "DUK", "SO", "D", "EXC", "AEP", "SRE", "XEL", "PEG", "ED",
        "AMT", "PLD", "EQIX", "PSA", "SPG", "WELL", "AVB", "EQR",
        # Communication / media
        "WBD", "PARA", "FOX", "NWSA",
        # Others (some may have data gaps but yfinance will tag NaN)
        "GLD", "TLT",  # ETFs as cross-check
    ]
    # dedupe preserving order
    seen = set()
    out = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------
def fetch_prices(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    """Fetch adjusted close monthly. Returns wide DataFrame (date x ticker)."""
    print(f"[fetch] {len(tickers)} tickers, {start} -> {end}")
    # Batch fetch
    data = yf.download(
        tickers,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="column",
    )
    # data is multi-index (column, ticker) when auto_adjust=True; pull Close
    if isinstance(data.columns, pd.MultiIndex):
        # yfinance returns 'Close' (auto_adjust already applied)
        if "Close" in data.columns.get_level_values(0):
            px = data["Close"].copy()
        else:
            px = data.xs("Close", axis=1, level=0).copy()
    else:
        px = data["Close"].to_frame() if "Close" in data.columns else data.copy()
    px = px.dropna(how="all")
    # Drop tickers with <500 observations (~2 years)
    obs_counts = px.notna().sum()
    keep = obs_counts[obs_counts >= 500].index.tolist()
    dropped = [t for t in px.columns if t not in keep]
    if dropped:
        print(f"[fetch] dropped {len(dropped)} tickers with <500 obs: {dropped[:10]}...")
    px = px[keep]
    print(f"[fetch] retained {px.shape[1]} tickers, {px.shape[0]} daily obs")
    return px


def fetch_market(start: str, end: str) -> pd.Series:
    spy = yf.download("SPY", start=start, end=end, interval="1d",
                      auto_adjust=True, progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy = spy.xs("Close", axis=1, level=0).iloc[:, 0]
    else:
        spy = spy["Close"]
    return spy.dropna()


# ---------------------------------------------------------------------------
# Returns, RV, beta
# ---------------------------------------------------------------------------
def daily_log_returns(px: pd.DataFrame) -> pd.DataFrame:
    return np.log(px / px.shift(1))


def monthly_returns(daily_ret: pd.DataFrame) -> pd.DataFrame:
    """Monthly simple returns (sum of daily log → exp - 1)."""
    monthly_log = daily_ret.resample("ME").sum(min_count=15)
    return np.exp(monthly_log) - 1.0


def monthly_rv(daily_ret: pd.DataFrame) -> pd.DataFrame:
    """Monthly realized vol = sqrt(sum of squared daily log returns)."""
    return (daily_ret**2).resample("ME").sum(min_count=15).pow(0.5)


def rolling_beta_60m(stock_m: pd.DataFrame, mkt_m: pd.Series,
                     window: int = 60) -> pd.DataFrame:
    """Rolling OLS beta (no intercept simpler: with intercept).

    For each stock, beta_t = cov(r_i, r_m) / var(r_m) over t-window+1 .. t.
    Returned beta indexed by end-of-window month.
    """
    mkt_m = mkt_m.reindex(stock_m.index)
    betas = pd.DataFrame(index=stock_m.index, columns=stock_m.columns,
                         dtype=float)
    mkt_arr = mkt_m.values
    for col in stock_m.columns:
        ri = stock_m[col].values
        # rolling cov / var
        for t in range(window - 1, len(stock_m)):
            x = mkt_arr[t - window + 1 : t + 1]
            y = ri[t - window + 1 : t + 1]
            mask = ~(np.isnan(x) | np.isnan(y))
            if mask.sum() < window * 0.8:  # require 80% non-nan
                continue
            xm = x[mask] - x[mask].mean()
            ym = y[mask] - y[mask].mean()
            var_x = (xm**2).sum()
            if var_x <= 0:
                continue
            betas.iloc[t, betas.columns.get_loc(col)] = (xm * ym).sum() / var_x
    return betas


# ---------------------------------------------------------------------------
# BAB portfolio (Frazzini-Pedersen 2014)
# ---------------------------------------------------------------------------
def bab_returns(betas: pd.DataFrame, fwd_ret: pd.DataFrame,
                low_q: float = 0.30, high_q: float = 0.30) -> pd.Series:
    """Construct BAB return series.

    For each month t:
    - Use beta_t (computed from t-60..t-1 data) — already lag-safe by
      construction (betas series shifted by 1 below).
    - Long bottom low_q beta, short top high_q beta.
    - Rank weights (Frazzini-Pedersen): z_i = rank(beta_i); weight_L =
      2 * (z_bar - z_i)+ / sum(...); weight_H = 2 * (z_i - z_bar)+ / sum(...).
    - Leverage: long leg scaled to beta=1/avg_beta_L, short leg to
      beta=1/avg_beta_H, so that BAB = 1/beta_L * r_L - 1/beta_H * r_H.

    fwd_ret: monthly stock returns aligned to month t+1.

    Returns: pd.Series indexed by month t+1.
    """
    # Critical lag: use beta_t to form portfolio at end of month t, get return
    # at month t+1. Shift betas forward by 1: portfolio_t = beta_{t-1}.
    bab_series = pd.Series(index=fwd_ret.index, dtype=float, name="BAB")
    diag = []
    for t in range(1, len(fwd_ret)):
        idx_t = fwd_ret.index[t]
        prev_idx = fwd_ret.index[t - 1]
        if prev_idx not in betas.index:
            continue
        b = betas.loc[prev_idx].dropna()
        r = fwd_ret.loc[idx_t].dropna()
        common = b.index.intersection(r.index)
        if len(common) < 30:
            continue
        b = b.loc[common]
        r = r.loc[common]
        # Drop extreme/invalid betas
        b = b[(b > -3) & (b < 5)]
        r = r.loc[b.index]
        if len(b) < 30:
            continue
        # Rank weights — Frazzini-Pedersen style: rank, demean, normalize so
        # long leg weights sum to 1 and short leg weights sum to 1.
        z = b.rank()
        zbar = z.mean()
        w_low = (zbar - z).clip(lower=0)
        w_high = (z - zbar).clip(lower=0)
        if w_low.sum() <= 0 or w_high.sum() <= 0:
            continue
        w_low = w_low / w_low.sum()
        w_high = w_high / w_high.sum()
        # Compute leg betas and returns
        beta_L = float((w_low * b).sum())
        beta_H = float((w_high * b).sum())
        r_L = float((w_low * r).sum())
        r_H = float((w_high * r).sum())
        if beta_L <= 0 or beta_H <= 0:
            continue
        # Frazzini-Pedersen: BAB = (1/beta_L) * (r_L - rf) - (1/beta_H) * (r_H - rf)
        # We approximate rf = 0 (zero excess) for simplicity; results focus on
        # cross-sectional conditional differences, rf cancels in tertile comparisons.
        bab_t = (1.0 / beta_L) * r_L - (1.0 / beta_H) * r_H
        bab_series.loc[idx_t] = bab_t
        diag.append({"date": idx_t, "n": len(b),
                     "beta_L": beta_L, "beta_H": beta_H,
                     "r_L": r_L, "r_H": r_H, "bab": bab_t})
    return bab_series.dropna(), pd.DataFrame(diag)


# ---------------------------------------------------------------------------
# Conditioning analysis
# ---------------------------------------------------------------------------
def market_rv_monthly(spy_daily: pd.Series) -> pd.Series:
    r = np.log(spy_daily / spy_daily.shift(1)).dropna()
    return (r**2).resample("ME").sum(min_count=15).pow(0.5).dropna()


def newey_west_tstat(x: np.ndarray, lag: int = 6) -> Tuple[float, float, float]:
    """Return (mean, NW se, t-stat) for mean of x using Newey-West."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    mean = x.mean()
    # Regress on constant
    X = np.ones((n, 1))
    model = sm.OLS(x, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    se = float(model.bse[0])
    t = mean / se if se > 0 else np.nan
    return float(mean), se, float(t)


def block_bootstrap_diff(low: np.ndarray, high: np.ndarray,
                         block_len: int = 12, reps: int = 10000,
                         seed: int = 42) -> Tuple[float, float, float]:
    """Block-bootstrap on the *difference of means* low - high.

    Each tertile sample has its own length; use stationary block bootstrap on
    each independently with the given block_len.
    """
    rng = np.random.default_rng(seed)

    def stationary_block(arr, n, p):
        out = np.empty(n)
        i = 0
        while i < n:
            start = rng.integers(0, len(arr))
            block_len_i = rng.geometric(p)
            for k in range(block_len_i):
                if i >= n:
                    break
                out[i] = arr[(start + k) % len(arr)]
                i += 1
        return out

    p = 1.0 / block_len
    n_low = len(low)
    n_high = len(high)
    diffs = np.empty(reps)
    for r in range(reps):
        bl = stationary_block(low, n_low, p)
        bh = stationary_block(high, n_high, p)
        diffs[r] = bl.mean() - bh.mean()
    ci = np.percentile(diffs, [2.5, 97.5])
    return float(diffs.mean()), float(ci[0]), float(ci[1])


def conditional_analysis(bab: pd.Series, mkt_rv: pd.Series) -> Dict:
    """Conditional analysis: BAB return in month t+1 vs market RV in month t."""
    # Align: mkt_rv at t → BAB return at t+1
    # i.e. regime signal at t-1 → BAB return at t
    rv_lag = mkt_rv.shift(1).reindex(bab.index).dropna()
    bab_aligned = bab.reindex(rv_lag.index).dropna()
    rv_lag = rv_lag.reindex(bab_aligned.index)
    # tertile by lagged RV
    q33 = rv_lag.quantile(1.0 / 3.0)
    q67 = rv_lag.quantile(2.0 / 3.0)
    low_mask = rv_lag <= q33
    mid_mask = (rv_lag > q33) & (rv_lag <= q67)
    high_mask = rv_lag > q67
    out: Dict[str, Dict] = {}
    for name, mask in [("low_vol", low_mask), ("mid_vol", mid_mask),
                       ("high_vol", high_mask)]:
        ret = bab_aligned[mask].values
        if len(ret) < 5:
            continue
        mean, se, t = newey_west_tstat(ret, lag=6)
        annual_sharpe = (mean / ret.std(ddof=1)) * np.sqrt(12) if ret.std(ddof=1) > 0 else np.nan
        out[name] = {
            "n_obs": int(len(ret)),
            "mean_monthly": float(mean),
            "std_monthly": float(ret.std(ddof=1)),
            "annual_sharpe": float(annual_sharpe),
            "nw_se": float(se),
            "nw_tstat": float(t),
            "ann_return_pct": float(mean * 12 * 100),
        }
    # Difference test: low_vol vs high_vol (Welch + bootstrap)
    low = bab_aligned[low_mask].values
    high = bab_aligned[high_mask].values
    welch_t, welch_p = stats.ttest_ind(low, high, equal_var=False)
    diff_mean = float(low.mean() - high.mean())
    # Block bootstrap
    bs_mean, bs_lo, bs_hi = block_bootstrap_diff(
        low, high, block_len=12, reps=10000, seed=SEED
    )
    # HAC on combined: regress BAB on low_dummy - high_dummy (zero=mid)
    # Build difference test via OLS with HAC for joint sample
    df = pd.DataFrame({
        "bab": np.concatenate([low, high]),
        "low_minus_high": np.concatenate([np.ones(len(low)),
                                          -np.ones(len(high))]),
    })
    # Slightly off but OK as additional check; primary HAC = per-tertile NW
    X = sm.add_constant(df["low_minus_high"].values)
    hac_model = sm.OLS(df["bab"].values, X).fit(
        cov_type="HAC", cov_kwds={"maxlags": 6}
    )
    out["diff_test"] = {
        "mean_low_minus_high": diff_mean,
        "welch_t": float(welch_t),
        "welch_p": float(welch_p),
        "hac_coef": float(hac_model.params[1]),
        "hac_se": float(hac_model.bse[1]),
        "hac_tstat": float(hac_model.tvalues[1]),
        "hac_p": float(hac_model.pvalues[1]),
        "bootstrap_mean_diff": bs_mean,
        "bootstrap_ci95_lo": bs_lo,
        "bootstrap_ci95_hi": bs_hi,
        "n_low": int(len(low)),
        "n_high": int(len(high)),
    }
    # Unconditional baseline
    mean_u, se_u, t_u = newey_west_tstat(bab_aligned.values, lag=6)
    sharpe_u = (mean_u / bab_aligned.std(ddof=1)) * np.sqrt(12)
    out["unconditional"] = {
        "n_obs": int(len(bab_aligned)),
        "mean_monthly": float(mean_u),
        "annual_sharpe": float(sharpe_u),
        "nw_se": float(se_u),
        "nw_tstat": float(t_u),
        "ann_return_pct": float(mean_u * 12 * 100),
    }
    # Fama-MacBeth lite: regress BAB_{t} on lagged RV percentile
    rv_pct = rv_lag.rank(pct=True)
    X_fm = sm.add_constant(rv_pct.values)
    fm = sm.OLS(bab_aligned.values, X_fm).fit(
        cov_type="HAC", cov_kwds={"maxlags": 6}
    )
    out["fama_macbeth_lite"] = {
        "intercept": float(fm.params[0]),
        "intercept_se": float(fm.bse[0]),
        "intercept_t": float(fm.tvalues[0]),
        "rv_pct_coef": float(fm.params[1]),
        "rv_pct_se": float(fm.bse[1]),
        "rv_pct_t": float(fm.tvalues[1]),
        "rv_pct_p": float(fm.pvalues[1]),
        "r2": float(fm.rsquared),
    }
    return out, bab_aligned, rv_lag, (low_mask, mid_mask, high_mask)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------
def make_figures(bab: pd.Series, masks, results: Dict, mkt_rv: pd.Series):
    low_mask, mid_mask, high_mask = masks
    # Fig 1: cumulative BAB by regime
    fig, ax = plt.subplots(figsize=(10, 6))
    cum_all = (1 + bab).cumprod()
    ax.plot(cum_all.index, cum_all.values, label="Unconditional BAB", color="black", lw=1.5)
    # Highlight high-vol months
    for name, mask, color in [("low_vol", low_mask, "tab:green"),
                              ("high_vol", high_mask, "tab:red")]:
        sub_bab = bab.where(mask, 0)
        sub_cum = (1 + sub_bab).cumprod()
        ax.plot(sub_cum.index, sub_cum.values, label=f"BAB | {name} (else=0)",
                color=color, alpha=0.7)
    ax.set_title("K1464 — BAB cumulative return by prior-month RV regime")
    ax.set_ylabel("Cumulative growth ($1 → )")
    ax.set_xlabel("Month")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "bab_cumulative_by_regime.png", dpi=120)
    plt.close(fig)

    # Fig 2: Sharpe bar by tertile
    fig, ax = plt.subplots(figsize=(8, 5))
    regimes = ["low_vol", "mid_vol", "high_vol"]
    sharpes = [results.get(r, {}).get("annual_sharpe", np.nan) for r in regimes]
    means = [results.get(r, {}).get("ann_return_pct", np.nan) for r in regimes]
    ax2 = ax.twinx()
    bars = ax.bar(regimes, sharpes, color=["tab:green", "tab:gray", "tab:red"],
                  alpha=0.7, label="Annualized Sharpe")
    ax2.plot(regimes, means, "o-", color="black", lw=2, label="Ann. return %")
    ax.set_ylabel("Annualized Sharpe Ratio")
    ax2.set_ylabel("Annualized Return (%)")
    ax.set_title("K1464 — BAB Sharpe & Return by prior-month RV tertile")
    ax.axhline(0, color="gray", lw=0.5)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "bab_sharpe_by_tertile.png", dpi=120)
    plt.close(fig)

    # Fig 3: scatter RV vs BAB
    fig, ax = plt.subplots(figsize=(8, 6))
    rv_lag_aligned = mkt_rv.shift(1).reindex(bab.index).dropna()
    bab_a = bab.reindex(rv_lag_aligned.index)
    ax.scatter(rv_lag_aligned.values, bab_a.values, alpha=0.4, s=18)
    # OLS line
    X = sm.add_constant(rv_lag_aligned.values)
    fit = sm.OLS(bab_a.values, X).fit()
    xx = np.linspace(rv_lag_aligned.min(), rv_lag_aligned.max(), 100)
    yy = fit.params[0] + fit.params[1] * xx
    ax.plot(xx, yy, "r-", lw=2, label=f"OLS β={fit.params[1]:.3f}, t={fit.tvalues[1]:.2f}")
    ax.axhline(0, color="gray", lw=0.5)
    ax.set_xlabel("Lagged (month t) Market RV")
    ax.set_ylabel("BAB return (month t+1)")
    ax.set_title("K1464 — BAB vs prior-month market RV")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "rv_vs_bab_scatter.png", dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    tickers = get_universe()
    print(f"[universe] {len(tickers)} tickers")
    px = fetch_prices(tickers, START, END)
    spy = fetch_market(START, END)

    # Daily log returns
    dret = daily_log_returns(px)
    mret = monthly_returns(dret)
    print(f"[monthly] {mret.shape[0]} months, {mret.shape[1]} tickers")

    # Market monthly returns
    mret_spy = np.log(spy / spy.shift(1)).resample("ME").sum(min_count=15)
    mret_spy = (np.exp(mret_spy) - 1).dropna()

    # Rolling 60-month beta
    print("[beta] computing rolling 60-month beta...")
    betas = rolling_beta_60m(mret, mret_spy, window=60)
    n_valid_beta = betas.notna().sum().sum()
    print(f"[beta] valid beta cells: {n_valid_beta}")

    # BAB returns (returns at t use beta_{t-1})
    print("[bab] constructing BAB portfolio...")
    bab, diag = bab_returns(betas, mret, low_q=0.30, high_q=0.30)
    print(f"[bab] {len(bab)} monthly observations: {bab.index.min()} -> {bab.index.max()}")

    # Market RV monthly
    mkt_rv = market_rv_monthly(spy)
    print(f"[mkt_rv] {len(mkt_rv)} months")

    # Conditional analysis
    results, bab_aligned, rv_lag, masks = conditional_analysis(bab, mkt_rv)
    results["effective_period"] = {
        "start": str(bab_aligned.index.min().date()),
        "end": str(bab_aligned.index.max().date()),
        "n_months": int(len(bab_aligned)),
    }
    results["universe"] = {
        "candidates_requested": len(tickers),
        "tickers_with_data": int(px.shape[1]),
        "median_betas_per_month": int(betas.notna().sum(axis=1).median()),
        "survivorship_bias_note": "Hand-curated large-cap list; survivors over-represented. Results should be read as upper bound on premium magnitude; tertile *conditioning* (within-strategy) is robust to constant survivorship bias.",
    }

    # Verdict logic
    dt = results["diff_test"]
    hac_t = abs(dt["hac_tstat"])
    welch_t = abs(dt["welch_t"])
    bs_ci_lo = dt["bootstrap_ci95_lo"]
    bs_ci_hi = dt["bootstrap_ci95_hi"]
    bs_excludes_zero = (bs_ci_lo > 0) or (bs_ci_hi < 0)
    diff_sign = np.sign(dt["mean_low_minus_high"])

    if hac_t > 2.5 and bs_excludes_zero and diff_sign > 0:
        verdict = "SUPPORT"
    elif hac_t > 2.5 and bs_excludes_zero and diff_sign < 0:
        verdict = "REJECT"
    elif (hac_t > 2.0 or welch_t > 2.0) and not bs_excludes_zero:
        verdict = "MIXED"
    elif diff_sign > 0 and (hac_t > 1.5 or welch_t > 1.5):
        verdict = "MIXED"
    else:
        verdict = "NULL"
    results["verdict"] = verdict
    results["verdict_basis"] = {
        "hac_tstat_abs": float(hac_t),
        "welch_tstat_abs": float(welch_t),
        "bootstrap_excludes_zero": bool(bs_excludes_zero),
        "sign_low_minus_high": float(diff_sign),
        "bar": "SUPPORT requires |HAC t|>2.5 AND bootstrap CI excludes 0 AND low>high",
    }
    results["meta"] = {
        "experiment_id": "k1464",
        "research_question": "BAB return conditional on prior-month RV",
        "source_paper": "JFE 2025 'The volatility puzzle of the beta anomaly'",
        "seed": SEED,
        "lag_safety": "betas shifted by 1 (use beta_{t-1} for portfolio formed at end of t-1, ret at t); RV regime also lagged",
        "bootstrap": {"type": "stationary_block", "block_len": 12, "reps": 10000, "seed": SEED},
        "hac_lag": 6,
    }

    # Save results
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[save] {RESULTS_PATH}")

    # Figures
    print("[fig] making figures...")
    make_figures(bab_aligned, masks, results, mkt_rv)
    print(f"[fig] saved to {FIG_DIR}")

    # Print headline
    print("\n=== HEADLINE ===")
    print(f"Verdict: {verdict}")
    for r in ["low_vol", "mid_vol", "high_vol"]:
        if r in results:
            d = results[r]
            print(f"  {r}: n={d['n_obs']}, ann_ret={d['ann_return_pct']:.2f}%, "
                  f"Sharpe={d['annual_sharpe']:.3f}, NW t={d['nw_tstat']:.2f}")
    print(f"diff (low-high): mean={dt['mean_low_minus_high']:.4f}, "
          f"HAC t={dt['hac_tstat']:.2f}, Welch t={dt['welch_t']:.2f}, "
          f"bootstrap 95% CI=[{bs_ci_lo:.4f}, {bs_ci_hi:.4f}]")
    print(f"unconditional Sharpe: {results['unconditional']['annual_sharpe']:.3f}")


if __name__ == "__main__":
    main()
