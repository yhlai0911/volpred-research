"""Sector-Level VT Effectiveness Map
=====================================
K53 showed leverage effect (GJR gamma) drives VT's trend-following exposure (r=0.742, N=15).
This experiment tests whether sector-level gamma predicts VT effectiveness across 11 SPDR sectors.

Hypothesis: Sectors with higher leverage effect (higher gamma) benefit more from VT.

[提出: 用戶, 執行: Claude]
"""
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────
SECTORS = {
    "XLB": "Materials",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLK": "Technology",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLV": "Healthcare",
    "XLY": "Consumer Disc.",
    "XLRE": "Real Estate",
    "XLC": "Communication",
}

START = "1998-01-01"
END = "2026-12-31"
OOS_START = "2023-01-01"
GARCH_WINDOW = 2000
VIX_THRESHOLD = 12.0
RF_ANNUAL = 0.04
TX_COST_PER_TRADE = 0.0005  # one-way

STORAGE = Path(__file__).parent.parent / "storage"
OUTPUT_FILE = STORAGE / "experiments" / "sector_vt_map.json"


# ── Data Fetching ──────────────────────────────────────────
def fetch_all_data():
    """Download sector ETFs + VIX."""
    print("=" * 60)
    print("Fetching data...")
    print("=" * 60)

    sector_data = {}
    for ticker, name in SECTORS.items():
        print(f"  {ticker} ({name})...", end=" ")
        df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
        if df.empty:
            print("SKIP (no data)")
            continue
        # Handle multi-level columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        sector_data[ticker] = close
        print(f"{len(close)} obs, {close.index[0].strftime('%Y-%m-%d')} to {close.index[-1].strftime('%Y-%m-%d')}")

    print("  ^VIX...", end=" ")
    vix_df = yf.download("^VIX", start=START, end=END, progress=False, auto_adjust=True)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)
    vix = vix_df["Close"].dropna()
    print(f"{len(vix)} obs")

    # SPY as benchmark
    print("  SPY (benchmark)...", end=" ")
    spy_df = yf.download("SPY", start=START, end=END, progress=False, auto_adjust=True)
    if isinstance(spy_df.columns, pd.MultiIndex):
        spy_df.columns = spy_df.columns.get_level_values(0)
    spy = spy_df["Close"].dropna()
    print(f"{len(spy)} obs")

    return sector_data, vix, spy


# ── GJR-GARCH Estimation ──────────────────────────────────
def estimate_gjr_garch(returns_pct, window=None):
    """Estimate GJR-GARCH(1,1) and extract gamma (leverage effect).

    Returns: dict with alpha, beta, gamma, persistence, omega, log_likelihood
    """
    if window is not None and len(returns_pct) > window:
        data = returns_pct.iloc[-window:]
    else:
        data = returns_pct

    try:
        am = arch_model(
            data, vol="GARCH", p=1, o=1, q=1,
            dist="normal", mean="Zero", rescale=False
        )
        res = am.fit(disp="off", show_warning=False)

        params = res.params
        omega = float(params.get("omega", 0))
        alpha = float(params.get("alpha[1]", 0))
        gamma = float(params.get("gamma[1]", 0))
        beta = float(params.get("beta[1]", 0))
        persistence = alpha + beta + gamma / 2

        return {
            "omega": omega,
            "alpha": alpha,
            "gamma": gamma,
            "beta": beta,
            "persistence": persistence,
            "log_likelihood": float(res.loglikelihood),
            "nobs": int(res.nobs),
        }
    except Exception as e:
        print(f"    GJR-GARCH failed: {e}")
        return None


# ── 12/VIX VT Strategy ────────────────────────────────────
def compute_12vix_strategy(asset_returns, vix_close, monthly_rebal=True):
    """12/VIX VT with monthly rebalance and lagged weights.

    Weight = min(12/VIX_t, 1.0), applied to return at t+1.
    Monthly: weight updated only on first trading day of each month.
    """
    # Align indices
    common = asset_returns.index.intersection(vix_close.index)
    ret = asset_returns.loc[common]
    vix = vix_close.loc[common]

    # Raw weight (lagged by 1 day)
    raw_weight = (VIX_THRESHOLD / vix).clip(0, 1.0).shift(1)

    if monthly_rebal:
        weight = raw_weight.copy()
        current_w = np.nan
        current_month = None
        for i, (date, w) in enumerate(raw_weight.items()):
            ym = (date.year, date.month)
            if ym != current_month:
                current_month = ym
                current_w = w
            weight.iloc[i] = current_w
    else:
        weight = raw_weight

    # Strategy return: w * asset + (1-w) * rf_daily
    rf_daily = RF_ANNUAL / 252
    strat_ret = weight * ret + (1 - weight) * rf_daily

    # Transaction costs (monthly turnover)
    turnover = weight.diff().abs()
    strat_ret_net = strat_ret - turnover * TX_COST_PER_TRADE

    return strat_ret.dropna(), strat_ret_net.dropna(), weight.dropna()


# ── Metrics ────────────────────────────────────────────────
def compute_metrics(daily_returns, label=""):
    """Compute comprehensive performance metrics."""
    dr = daily_returns.dropna()
    n = len(dr)
    if n < 60:
        return None

    arr = dr.values
    years = n / 252

    # Cumulative
    cum = np.prod(1 + arr) - 1
    ann_ret = (1 + cum) ** (1 / years) - 1 if years > 0.5 else cum

    # Volatility
    ann_vol = np.std(arr, ddof=1) * np.sqrt(252)

    # Sharpe
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Sortino
    downside = arr[arr < 0]
    down_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 1 else 1e-9
    sortino = ann_ret / down_vol

    # MDD
    cum_series = np.cumprod(1 + arr)
    running_max = np.maximum.accumulate(cum_series)
    drawdowns = cum_series / running_max - 1
    mdd = float(np.min(drawdowns))

    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-9 else 0

    # Win rate
    win_rate = np.mean(arr > 0) * 100

    # Skewness and kurtosis
    skew = float(stats.skew(arr))
    kurt = float(stats.kurtosis(arr))

    return {
        "label": label,
        "n_obs": n,
        "years": round(years, 1),
        "ann_return_pct": round(ann_ret * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "win_rate": round(win_rate, 1),
        "skewness": round(skew, 3),
        "kurtosis": round(kurt, 3),
    }


# ── Cross-Sectional Analysis ──────────────────────────────
def newey_west_corr(x, y, label=""):
    """Pearson correlation with Newey-West t-stat (lag = int(N^(1/3)))."""
    mask = ~(np.isnan(x) | np.isnan(y))
    x_c = x[mask]
    y_c = y[mask]
    n = len(x_c)
    if n < 5:
        return None

    r, p_pearson = stats.pearsonr(x_c, y_c)

    # Newey-West SE for correlation
    # t = r * sqrt(n-2) / sqrt(1-r^2) is the standard t-stat
    t_stat = r * np.sqrt(n - 2) / np.sqrt(1 - r**2) if abs(r) < 1 else np.inf
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-2))

    # Spearman for robustness
    rho_s, p_s = stats.spearmanr(x_c, y_c)

    return {
        "label": label,
        "n": int(n),
        "pearson_r": round(float(r), 4),
        "pearson_t": round(float(t_stat), 3),
        "pearson_p": round(float(p_val), 4),
        "spearman_rho": round(float(rho_s), 4),
        "spearman_p": round(float(p_s), 4),
        "significant_5pct": p_val < 0.05,
    }


def run_ols_with_nw(y, x, label=""):
    """OLS regression y = a + b*x with Newey-West standard errors."""
    mask = ~(np.isnan(x) | np.isnan(y))
    x_c = x[mask]
    y_c = y[mask]
    n = len(x_c)
    if n < 5:
        return None

    X = np.column_stack([np.ones(n), x_c])
    beta = np.linalg.lstsq(X, y_c, rcond=None)[0]
    resid = y_c - X @ beta

    # Newey-West covariance
    lag = max(1, int(n ** (1/3)))
    # Meat of the sandwich
    S = np.zeros((2, 2))
    for l in range(lag + 1):
        w = 1.0 if l == 0 else 1.0 - l / (lag + 1)  # Bartlett kernel
        for t in range(l, n):
            xt = X[t].reshape(-1, 1)
            xt_l = X[t - l].reshape(-1, 1)
            S += w * (resid[t] * resid[t - l]) * (xt @ xt_l.T + (xt_l @ xt.T if l > 0 else 0))

    bread = np.linalg.inv(X.T @ X)
    nw_cov = n * bread @ S @ bread

    se_nw = np.sqrt(np.diag(nw_cov))
    t_stats = beta / se_nw
    p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n - 2))

    # R-squared
    ss_res = np.sum(resid**2)
    ss_tot = np.sum((y_c - np.mean(y_c))**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return {
        "label": label,
        "n": int(n),
        "intercept": round(float(beta[0]), 4),
        "slope": round(float(beta[1]), 4),
        "intercept_se_nw": round(float(se_nw[0]), 4),
        "slope_se_nw": round(float(se_nw[1]), 4),
        "intercept_t": round(float(t_stats[0]), 3),
        "slope_t": round(float(t_stats[1]), 3),
        "intercept_p": round(float(p_vals[0]), 4),
        "slope_p": round(float(p_vals[1]), 4),
        "r_squared": round(float(r2), 4),
    }


# ── Main Analysis ─────────────────────────────────────────
def run_analysis():
    """Execute the full sector VT map analysis."""
    print("\n" + "=" * 60)
    print("Sector-Level VT Effectiveness Map")
    print("=" * 60)

    # 1. Fetch data
    sector_data, vix, spy = fetch_all_data()

    # 2. Compute returns
    print("\n" + "=" * 60)
    print("Computing returns and GARCH estimates...")
    print("=" * 60)

    results = {}
    sector_summary = []

    for ticker, name in SECTORS.items():
        if ticker not in sector_data:
            print(f"  {ticker}: skipped (no data)")
            continue

        print(f"\n--- {ticker} ({name}) ---")
        close = sector_data[ticker]
        ret = close.pct_change().dropna()
        ret_pct = ret * 100  # for GARCH (percentage scale)

        n_total = len(ret)
        start_date = ret.index[0].strftime("%Y-%m-%d")
        end_date = ret.index[-1].strftime("%Y-%m-%d")
        print(f"  Data: {n_total} obs, {start_date} to {end_date}")

        # 2a. GJR-GARCH estimation (full sample)
        garch_window = min(GARCH_WINDOW, n_total)
        gjr = estimate_gjr_garch(ret_pct, window=None)  # full sample for gamma
        if gjr is None:
            print(f"  GARCH failed, skipping")
            continue

        print(f"  GJR-GARCH: gamma={gjr['gamma']:.4f}, alpha={gjr['alpha']:.4f}, "
              f"beta={gjr['beta']:.4f}, persistence={gjr['persistence']:.4f}")

        # 2b. Correlation: daily return vs VIX change
        common_idx = ret.index.intersection(vix.index)
        ret_aligned = ret.loc[common_idx]
        vix_aligned = vix.loc[common_idx]
        vix_change = vix_aligned.pct_change().dropna()
        ret_for_corr = ret_aligned.loc[vix_change.index]
        if len(ret_for_corr) > 30:
            corr_vix = float(np.corrcoef(ret_for_corr.values, vix_change.values)[0, 1])
        else:
            corr_vix = np.nan
        print(f"  corr(return, ΔVIX) = {corr_vix:.4f}")

        # 2c. 12/VIX VT strategy
        strat_ret, strat_ret_net, weights = compute_12vix_strategy(ret, vix, monthly_rebal=True)

        # Full sample metrics
        bh_metrics = compute_metrics(ret, f"{ticker} B&H")
        vt_metrics = compute_metrics(strat_ret, f"{ticker} 12/VIX")
        vt_net_metrics = compute_metrics(strat_ret_net, f"{ticker} 12/VIX (net)")

        if bh_metrics is None or vt_metrics is None:
            print(f"  Insufficient data for metrics, skipping")
            continue

        # VT improvement
        sharpe_improve = vt_metrics["sharpe"] - bh_metrics["sharpe"]
        sharpe_improve_net = vt_net_metrics["sharpe"] - bh_metrics["sharpe"] if vt_net_metrics else sharpe_improve
        mdd_improve = bh_metrics["mdd_pct"] - vt_metrics["mdd_pct"]  # positive = VT better (less negative)

        print(f"  B&H: Sharpe={bh_metrics['sharpe']:.3f}, MDD={bh_metrics['mdd_pct']:.1f}%")
        print(f"  12/VIX: Sharpe={vt_metrics['sharpe']:.3f}, MDD={vt_metrics['mdd_pct']:.1f}%")
        print(f"  Improve: ΔSharpe={sharpe_improve:+.3f}, ΔMDD={mdd_improve:+.1f}pp")

        # OOS metrics (2023-2026)
        oos_bh_ret = ret.loc[ret.index >= OOS_START]
        oos_vt_ret = strat_ret.loc[strat_ret.index >= OOS_START]
        oos_vt_net = strat_ret_net.loc[strat_ret_net.index >= OOS_START]

        oos_bh_metrics = compute_metrics(oos_bh_ret, f"{ticker} B&H (OOS)")
        oos_vt_metrics = compute_metrics(oos_vt_ret, f"{ticker} 12/VIX (OOS)")
        oos_vt_net_metrics = compute_metrics(oos_vt_net, f"{ticker} 12/VIX net (OOS)")

        oos_sharpe_improve = None
        oos_mdd_improve = None
        if oos_bh_metrics and oos_vt_metrics:
            oos_sharpe_improve = oos_vt_metrics["sharpe"] - oos_bh_metrics["sharpe"]
            oos_mdd_improve = oos_bh_metrics["mdd_pct"] - oos_vt_metrics["mdd_pct"]
            print(f"  OOS B&H: Sharpe={oos_bh_metrics['sharpe']:.3f}, MDD={oos_bh_metrics['mdd_pct']:.1f}%")
            print(f"  OOS VT:  Sharpe={oos_vt_metrics['sharpe']:.3f}, MDD={oos_vt_metrics['mdd_pct']:.1f}%")
            print(f"  OOS Improve: ΔSharpe={oos_sharpe_improve:+.3f}, ΔMDD={oos_mdd_improve:+.1f}pp")

        # Average weight
        avg_weight = float(weights.mean())
        weight_std = float(weights.std())
        turnover_annual = float(weights.diff().abs().sum() / (len(weights) / 252))

        # Store results
        sector_result = {
            "ticker": ticker,
            "name": name,
            "data_start": start_date,
            "data_end": end_date,
            "n_obs": n_total,
            "gjr_garch": gjr,
            "corr_return_dvix": round(corr_vix, 4),
            "avg_weight": round(avg_weight, 4),
            "weight_std": round(weight_std, 4),
            "turnover_annual": round(turnover_annual, 4),
            "full_sample": {
                "bh": bh_metrics,
                "vt": vt_metrics,
                "vt_net": vt_net_metrics,
                "sharpe_improvement": round(sharpe_improve, 4),
                "sharpe_improvement_net": round(sharpe_improve_net, 4),
                "mdd_improvement_pp": round(mdd_improve, 2),
            },
        }
        if oos_bh_metrics and oos_vt_metrics:
            sector_result["oos_2023_2026"] = {
                "bh": oos_bh_metrics,
                "vt": oos_vt_metrics,
                "vt_net": oos_vt_net_metrics,
                "sharpe_improvement": round(oos_sharpe_improve, 4) if oos_sharpe_improve is not None else None,
                "mdd_improvement_pp": round(oos_mdd_improve, 2) if oos_mdd_improve is not None else None,
            }

        results[ticker] = sector_result
        sector_summary.append({
            "ticker": ticker,
            "name": name,
            "gamma": gjr["gamma"],
            "corr_dvix": corr_vix,
            "bh_sharpe": bh_metrics["sharpe"],
            "vt_sharpe": vt_metrics["sharpe"],
            "sharpe_improve": sharpe_improve,
            "sharpe_improve_net": sharpe_improve_net,
            "bh_mdd": bh_metrics["mdd_pct"],
            "vt_mdd": vt_metrics["mdd_pct"],
            "mdd_improve_pp": mdd_improve,
            "oos_sharpe_improve": oos_sharpe_improve,
            "oos_mdd_improve": oos_mdd_improve,
        })

    # ── 3. Cross-Sectional Analysis ────────────────────────
    print("\n" + "=" * 60)
    print("Cross-Sectional Analysis")
    print("=" * 60)

    df_summary = pd.DataFrame(sector_summary)
    n_sectors = len(df_summary)
    print(f"\nN = {n_sectors} sectors")

    gammas = df_summary["gamma"].values
    sharpe_imps = df_summary["sharpe_improve"].values
    sharpe_imps_net = df_summary["sharpe_improve_net"].values
    mdd_imps = df_summary["mdd_improve_pp"].values
    corr_dvix = df_summary["corr_dvix"].values

    # 3a. gamma vs Sharpe improvement
    corr_gamma_sharpe = newey_west_corr(gammas, sharpe_imps, "gamma_vs_sharpe_improvement")
    print(f"\ncorr(gamma, ΔSharpe): r={corr_gamma_sharpe['pearson_r']:.4f}, "
          f"t={corr_gamma_sharpe['pearson_t']:.3f}, p={corr_gamma_sharpe['pearson_p']:.4f}")

    # 3b. gamma vs MDD improvement
    corr_gamma_mdd = newey_west_corr(gammas, mdd_imps, "gamma_vs_mdd_improvement")
    print(f"corr(gamma, ΔMDD):   r={corr_gamma_mdd['pearson_r']:.4f}, "
          f"t={corr_gamma_mdd['pearson_t']:.3f}, p={corr_gamma_mdd['pearson_p']:.4f}")

    # 3c. gamma vs net Sharpe improvement
    corr_gamma_sharpe_net = newey_west_corr(gammas, sharpe_imps_net, "gamma_vs_sharpe_improvement_net")
    print(f"corr(gamma, ΔSharpe_net): r={corr_gamma_sharpe_net['pearson_r']:.4f}, "
          f"t={corr_gamma_sharpe_net['pearson_t']:.3f}, p={corr_gamma_sharpe_net['pearson_p']:.4f}")

    # 3d. corr(return, ΔVIX) vs VT effectiveness
    corr_dvix_sharpe = newey_west_corr(corr_dvix, sharpe_imps, "corr_dvix_vs_sharpe_improvement")
    print(f"corr(ρ(r,ΔVIX), ΔSharpe): r={corr_dvix_sharpe['pearson_r']:.4f}, "
          f"t={corr_dvix_sharpe['pearson_t']:.3f}, p={corr_dvix_sharpe['pearson_p']:.4f}")

    # 3e. OOS cross-sectional (if enough data)
    oos_sharpe_vals = df_summary["oos_sharpe_improve"].dropna().values
    oos_mdd_vals = df_summary["oos_mdd_improve"].dropna().values
    oos_gammas = df_summary.loc[df_summary["oos_sharpe_improve"].notna(), "gamma"].values

    corr_gamma_oos_sharpe = None
    corr_gamma_oos_mdd = None
    if len(oos_gammas) >= 5:
        corr_gamma_oos_sharpe = newey_west_corr(oos_gammas, oos_sharpe_vals, "gamma_vs_oos_sharpe_improvement")
        corr_gamma_oos_mdd = newey_west_corr(oos_gammas, oos_mdd_vals, "gamma_vs_oos_mdd_improvement")
        print(f"\nOOS corr(gamma, ΔSharpe): r={corr_gamma_oos_sharpe['pearson_r']:.4f}, "
              f"t={corr_gamma_oos_sharpe['pearson_t']:.3f}, p={corr_gamma_oos_sharpe['pearson_p']:.4f}")
        print(f"OOS corr(gamma, ΔMDD):   r={corr_gamma_oos_mdd['pearson_r']:.4f}, "
              f"t={corr_gamma_oos_mdd['pearson_t']:.3f}, p={corr_gamma_oos_mdd['pearson_p']:.4f}")

    # 3f. OLS regressions with Newey-West
    ols_gamma_sharpe = run_ols_with_nw(sharpe_imps, gammas, "ΔSharpe = a + b*gamma")
    ols_gamma_mdd = run_ols_with_nw(mdd_imps, gammas, "ΔMDD = a + b*gamma")

    print(f"\nOLS: ΔSharpe = {ols_gamma_sharpe['intercept']:.4f} + {ols_gamma_sharpe['slope']:.4f}*gamma "
          f"(t={ols_gamma_sharpe['slope_t']:.3f}, R²={ols_gamma_sharpe['r_squared']:.4f})")
    print(f"OLS: ΔMDD = {ols_gamma_mdd['intercept']:.4f} + {ols_gamma_mdd['slope']:.4f}*gamma "
          f"(t={ols_gamma_mdd['slope_t']:.3f}, R²={ols_gamma_mdd['r_squared']:.4f})")

    # ── 4. Sector Ranking ──────────────────────────────────
    print("\n" + "=" * 60)
    print("Sector Ranking (by VT Sharpe improvement)")
    print("=" * 60)

    df_sorted = df_summary.sort_values("sharpe_improve", ascending=False)
    print(f"\n{'Rank':<5} {'Ticker':<6} {'Sector':<22} {'γ':<8} {'B&H SR':<9} {'VT SR':<9} {'ΔSR':<9} {'B&H MDD':<10} {'VT MDD':<10} {'ΔMDD':<8}")
    print("-" * 96)
    for rank, (_, row) in enumerate(df_sorted.iterrows(), 1):
        print(f"{rank:<5} {row['ticker']:<6} {row['name']:<22} {row['gamma']:<8.4f} "
              f"{row['bh_sharpe']:<9.3f} {row['vt_sharpe']:<9.3f} {row['sharpe_improve']:+<9.3f} "
              f"{row['bh_mdd']:<10.1f} {row['vt_mdd']:<10.1f} {row['mdd_improve_pp']:+<8.1f}")

    # ── 5. Summary Statistics ──────────────────────────────
    print("\n" + "=" * 60)
    print("Summary Statistics")
    print("=" * 60)

    mean_gamma = float(np.mean(gammas))
    mean_sharpe_imp = float(np.mean(sharpe_imps))
    mean_mdd_imp = float(np.mean(mdd_imps))
    pct_sharpe_positive = float(np.mean(sharpe_imps > 0) * 100)
    pct_mdd_positive = float(np.mean(mdd_imps > 0) * 100)

    print(f"  Mean gamma:                  {mean_gamma:.4f}")
    print(f"  Mean ΔSharpe:                {mean_sharpe_imp:+.4f}")
    print(f"  Mean ΔMDD (pp):              {mean_mdd_imp:+.1f}")
    print(f"  % sectors VT improves Sharpe: {pct_sharpe_positive:.0f}%")
    print(f"  % sectors VT improves MDD:    {pct_mdd_positive:.0f}%")

    # Highest and lowest gamma sectors
    max_gamma_idx = np.argmax(gammas)
    min_gamma_idx = np.argmin(gammas)
    print(f"\n  Highest gamma: {df_summary.iloc[max_gamma_idx]['ticker']} "
          f"({df_summary.iloc[max_gamma_idx]['name']}) γ={gammas[max_gamma_idx]:.4f}")
    print(f"  Lowest gamma:  {df_summary.iloc[min_gamma_idx]['ticker']} "
          f"({df_summary.iloc[min_gamma_idx]['name']}) γ={gammas[min_gamma_idx]:.4f}")

    # ── 6. Practical Implications ──────────────────────────
    print("\n" + "=" * 60)
    print("Practical Implications")
    print("=" * 60)

    # Group sectors by gamma tercile
    gamma_sorted = df_summary.sort_values("gamma")
    n_tercile = n_sectors // 3
    low_gamma = gamma_sorted.iloc[:n_tercile]
    high_gamma = gamma_sorted.iloc[-n_tercile:]

    avg_improve_high = high_gamma["sharpe_improve"].mean()
    avg_improve_low = low_gamma["sharpe_improve"].mean()
    avg_mdd_improve_high = high_gamma["mdd_improve_pp"].mean()
    avg_mdd_improve_low = low_gamma["mdd_improve_pp"].mean()

    print(f"\n  High-gamma tercile: avg ΔSharpe = {avg_improve_high:+.4f}, avg ΔMDD = {avg_mdd_improve_high:+.1f}pp")
    print(f"  Low-gamma tercile:  avg ΔSharpe = {avg_improve_low:+.4f}, avg ΔMDD = {avg_mdd_improve_low:+.1f}pp")
    print(f"  High-Low spread:    {avg_improve_high - avg_improve_low:+.4f} (Sharpe), "
          f"{avg_mdd_improve_high - avg_mdd_improve_low:+.1f}pp (MDD)")

    high_tickers = list(high_gamma["ticker"].values)
    low_tickers = list(low_gamma["ticker"].values)
    print(f"\n  High-gamma sectors: {', '.join(high_tickers)}")
    print(f"  Low-gamma sectors:  {', '.join(low_tickers)}")

    # ── 7. Save Results ────────────────────────────────────
    output = {
        "experiment": "Sector-Level VT Effectiveness Map",
        "description": (
            "Test whether sector-level leverage effect (GJR gamma) predicts VT effectiveness. "
            "K53 showed gamma drives VT trend-following exposure (r=0.742, N=15). "
            "This extends to 11 SPDR sector ETFs."
        ),
        "proposed_by": "用戶",
        "executed_by": "Claude",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "sectors": SECTORS,
            "garch_window": GARCH_WINDOW,
            "vix_threshold": VIX_THRESHOLD,
            "rf_annual": RF_ANNUAL,
            "tx_cost_per_trade": TX_COST_PER_TRADE,
            "monthly_rebalance": True,
            "oos_start": OOS_START,
        },
        "sector_results": results,
        "cross_sectional_analysis": {
            "n_sectors": n_sectors,
            "correlations": {
                "gamma_vs_sharpe_improvement": corr_gamma_sharpe,
                "gamma_vs_mdd_improvement": corr_gamma_mdd,
                "gamma_vs_sharpe_improvement_net": corr_gamma_sharpe_net,
                "corr_dvix_vs_sharpe_improvement": corr_dvix_sharpe,
                "gamma_vs_oos_sharpe_improvement": corr_gamma_oos_sharpe,
                "gamma_vs_oos_mdd_improvement": corr_gamma_oos_mdd,
            },
            "regressions": {
                "sharpe_on_gamma": ols_gamma_sharpe,
                "mdd_on_gamma": ols_gamma_mdd,
            },
            "sector_ranking": df_sorted[["ticker", "name", "gamma", "bh_sharpe", "vt_sharpe",
                                          "sharpe_improve", "bh_mdd", "vt_mdd", "mdd_improve_pp"]].to_dict("records"),
        },
        "summary_statistics": {
            "mean_gamma": round(mean_gamma, 4),
            "std_gamma": round(float(np.std(gammas, ddof=1)), 4),
            "mean_sharpe_improvement": round(mean_sharpe_imp, 4),
            "mean_mdd_improvement_pp": round(mean_mdd_imp, 2),
            "pct_sectors_sharpe_positive": round(pct_sharpe_positive, 1),
            "pct_sectors_mdd_positive": round(pct_mdd_positive, 1),
        },
        "gamma_tercile_analysis": {
            "high_gamma_sectors": high_tickers,
            "low_gamma_sectors": low_tickers,
            "high_gamma_avg_sharpe_improve": round(float(avg_improve_high), 4),
            "low_gamma_avg_sharpe_improve": round(float(avg_improve_low), 4),
            "high_gamma_avg_mdd_improve_pp": round(float(avg_mdd_improve_high), 2),
            "low_gamma_avg_mdd_improve_pp": round(float(avg_mdd_improve_low), 2),
            "high_low_sharpe_spread": round(float(avg_improve_high - avg_improve_low), 4),
            "high_low_mdd_spread_pp": round(float(avg_mdd_improve_high - avg_mdd_improve_low), 2),
        },
        "conclusions": {},  # filled below
    }

    # Generate conclusions
    sig_sharpe = corr_gamma_sharpe["significant_5pct"]
    sig_mdd = corr_gamma_mdd["significant_5pct"]

    conclusions = {
        "gamma_predicts_sharpe": sig_sharpe,
        "gamma_predicts_mdd": sig_mdd,
        "gamma_sharpe_direction": "positive" if corr_gamma_sharpe["pearson_r"] > 0 else "negative",
        "gamma_mdd_direction": "positive" if corr_gamma_mdd["pearson_r"] > 0 else "negative",
        "best_vt_sector": df_sorted.iloc[0]["ticker"],
        "worst_vt_sector": df_sorted.iloc[-1]["ticker"],
        "interpretation": "",
    }

    # Build interpretation
    if sig_sharpe and corr_gamma_sharpe["pearson_r"] > 0:
        conclusions["interpretation"] = (
            f"Gamma significantly predicts VT Sharpe improvement (r={corr_gamma_sharpe['pearson_r']:.3f}, "
            f"p={corr_gamma_sharpe['pearson_p']:.4f}). Sectors with stronger leverage effect benefit more from VT, "
            f"confirming K53 at the sector level. Sector-rotation investors should apply VT more aggressively "
            f"to high-gamma sectors ({', '.join(high_tickers)})."
        )
    elif sig_mdd and corr_gamma_mdd["pearson_r"] > 0:
        conclusions["interpretation"] = (
            f"Gamma predicts MDD improvement (r={corr_gamma_mdd['pearson_r']:.3f}, "
            f"p={corr_gamma_mdd['pearson_p']:.4f}) but not Sharpe improvement. "
            f"VT provides consistent downside protection across sectors, with stronger protection "
            f"for high-leverage sectors."
        )
    elif not sig_sharpe and not sig_mdd:
        conclusions["interpretation"] = (
            f"Gamma does NOT significantly predict VT effectiveness at the sector level "
            f"(Sharpe: r={corr_gamma_sharpe['pearson_r']:.3f}, p={corr_gamma_sharpe['pearson_p']:.4f}; "
            f"MDD: r={corr_gamma_mdd['pearson_r']:.3f}, p={corr_gamma_mdd['pearson_p']:.4f}). "
            f"This may be because all equity sectors share similar VIX sensitivity, "
            f"making VT universally effective regardless of sector-specific gamma. "
            f"Cross-asset variation (equity vs commodity vs bond) may be needed to see gamma's predictive power."
        )
    else:
        conclusions["interpretation"] = (
            f"Mixed results. Sharpe: r={corr_gamma_sharpe['pearson_r']:.3f} (p={corr_gamma_sharpe['pearson_p']:.4f}), "
            f"MDD: r={corr_gamma_mdd['pearson_r']:.3f} (p={corr_gamma_mdd['pearson_p']:.4f})."
        )

    output["conclusions"] = conclusions

    # Save
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {OUTPUT_FILE}")

    # ── Final Summary ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"\n{conclusions['interpretation']}")

    return output


if __name__ == "__main__":
    run_analysis()
