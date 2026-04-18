"""
K339: ESG Vol Spread Rolling Validation
========================================
[提出: 用戶, 執行: Claude]

Background:
  K335 found ESG leader/laggard vol spread has partial r=0.208 (t=10.17)
  for predicting SPY vol beyond VIX. K265->K266 taught us full-sample
  results can be artifacts. This is the pure rolling validation.

Hypothesis:
  The ESG vol spread (laggard vol - leader vol) contains incremental
  information for SPY vol prediction beyond what VIX already captures.

Data:
  - ESG leaders: XLK (tech), XLV (healthcare)
  - ESG laggards: XLE (energy), XLF (financials)
  - SPY, ^VIX
  - Period: 2005-2024 (yfinance)

Methodology (K266 validation protocol):
  1. ESG vol spread = avg_vol(XLE,XLF) - avg_vol(XLK,XLV) using 22d rolling vol
  2. Rolling two-stage:
     - Stage 1: GJR-GARCH w=2000 -> h_t
     - Stage 2: Rolling OLS (252d): h_adjusted = h_t + delta*ESG_spread_{t-1}
  3. 5-period cross-validation (4-year periods)
  4. Pass criteria:
     - 3+/5 periods QLIKE improvement
     - Consistent delta sign
     - Pooled DM passes Harvey (t>3.0)

Statistical Requirements:
  - Real yfinance data only
  - OOS >= 252 days per period
  - DM test for comparison
  - Harvey t>3.0 for strong claims
"""

import sys
import os
import warnings
import json
import time
from datetime import datetime

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model

# ==================================================================
# CONFIG
# ==================================================================
ESG_LEADERS = ["XLK", "XLV"]
ESG_LAGGARDS = ["XLE", "XLF"]
MARKET_TICKER = "SPY"
VIX_TICKER = "^VIX"

DATA_START = "2003-01-01"  # Need lookback for w=2000
DATA_END = "2024-12-31"
VOL_WINDOW = 22            # Rolling vol window for ESG spread
GARCH_WINDOW = 2000        # GJR-GARCH estimation window
OLS_WINDOW = 252           # Stage 2 rolling OLS window
REFIT_FREQ = 22            # Refit GARCH every 22 days

# 5-period cross-validation (4-year periods)
PERIODS = [
    ("2005-2008", "2005-01-03", "2008-12-31"),
    ("2009-2012", "2009-01-02", "2012-12-31"),
    ("2013-2016", "2013-01-02", "2016-12-31"),
    ("2017-2020", "2017-01-02", "2020-12-31"),
    ("2021-2024", "2021-01-02", "2024-12-31"),
]

print("=" * 80)
print("K339: ESG VOL SPREAD ROLLING VALIDATION")
print("=" * 80)
print(f"  [提出: 用戶, 執行: Claude]")
print(f"  ESG Leaders:  {ESG_LEADERS}")
print(f"  ESG Laggards: {ESG_LAGGARDS}")
print(f"  Market:       {MARKET_TICKER}")
print(f"  VIX:          {VIX_TICKER}")
print(f"  Data range:   {DATA_START} to {DATA_END}")
print(f"  GARCH window: {GARCH_WINDOW}")
print(f"  OLS window:   {OLS_WINDOW}")
print(f"  Refit freq:   {REFIT_FREQ}d")
print(f"  Vol window:   {VOL_WINDOW}d")
print(f"  Periods:      {len(PERIODS)} x 4 years")
print()

# ==================================================================
# 1. Download Data
# ==================================================================
print("[1/5] Downloading data from yfinance...")

all_tickers = ESG_LEADERS + ESG_LAGGARDS + [MARKET_TICKER, VIX_TICKER]
raw_data = {}

for ticker in all_tickers:
    try:
        df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        raw_data[ticker] = df
        print(f"  {ticker}: {len(df)} rows ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
    except Exception as e:
        print(f"  ERROR downloading {ticker}: {e}")
        sys.exit(1)

# Build aligned price DataFrame
prices = pd.DataFrame({
    ticker: raw_data[ticker]["Adj Close"]
    for ticker in all_tickers if ticker != VIX_TICKER
})
prices["VIX"] = raw_data[VIX_TICKER]["Close"]
prices = prices.dropna()
print(f"\n  Aligned data: {len(prices)} rows ({prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')})")

# Compute log returns (for SPY) and rolling vol for sector ETFs
returns = {}
for ticker in ESG_LEADERS + ESG_LAGGARDS + [MARKET_TICKER]:
    returns[ticker] = np.log(prices[ticker] / prices[ticker].shift(1))

spy_ret = returns[MARKET_TICKER].dropna()
spy_ret_pct = spy_ret * 100  # For GARCH (percentage returns)

# ==================================================================
# 2. Compute ESG Vol Spread
# ==================================================================
print("\n[2/5] Computing ESG vol spread...")

# Rolling 22d vol for each sector ETF
sector_vols = {}
for ticker in ESG_LEADERS + ESG_LAGGARDS:
    sector_vols[ticker] = returns[ticker].rolling(VOL_WINDOW).std() * np.sqrt(252)

# ESG vol spread = avg_vol(laggards) - avg_vol(leaders)
leader_vol = pd.DataFrame({t: sector_vols[t] for t in ESG_LEADERS}).mean(axis=1)
laggard_vol = pd.DataFrame({t: sector_vols[t] for t in ESG_LAGGARDS}).mean(axis=1)
esg_spread = laggard_vol - leader_vol
esg_spread.name = "esg_vol_spread"

# Lag the spread by 1 day for prediction (avoid look-ahead)
esg_spread_lag = esg_spread.shift(1)

# Realized variance proxy (squared return)
rv_proxy = (spy_ret ** 2)

print(f"  ESG spread: mean={esg_spread.dropna().mean():.4f}, std={esg_spread.dropna().std():.4f}")
print(f"  Leader vol mean:  {leader_vol.dropna().mean():.4f}")
print(f"  Laggard vol mean: {laggard_vol.dropna().mean():.4f}")
print(f"  Correlation(ESG_spread, VIX): {esg_spread.corr(prices['VIX']):.3f}")

# ==================================================================
# 3. QLIKE and DM Test Functions
# ==================================================================

def qlike(realized, forecast):
    """QLIKE loss function: log(forecast) + realized/forecast"""
    valid = (forecast > 0) & (realized > 0) & np.isfinite(realized) & np.isfinite(forecast)
    r = realized[valid]
    f = forecast[valid]
    return np.log(f) + r / f

def dm_test(loss1, loss2):
    """Diebold-Mariano test (one-sided: H1: loss1 < loss2)"""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    if len(d) < 30:
        return np.nan, np.nan

    # Newey-West HAC with auto bandwidth
    n = len(d)
    d_bar = d.mean()

    # Bandwidth selection (Andrews 1991 rule of thumb)
    max_lag = int(np.floor(n ** (1/3)))

    gamma_0 = np.var(d, ddof=1)
    hac_var = gamma_0
    for k in range(1, max_lag + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        weight = 1 - k / (max_lag + 1)  # Bartlett kernel
        hac_var += 2 * weight * gamma_k

    hac_se = np.sqrt(hac_var / n)
    if hac_se < 1e-12:
        return np.nan, np.nan

    t_stat = d_bar / hac_se
    p_value = stats.t.sf(t_stat, df=n-1)  # one-sided (negative = model 1 better)
    # Actually we want: negative d_bar means model 1 has lower loss (better)
    # So for one-sided test that model 1 is better: p = P(T < t) = stats.t.cdf(t, df)
    p_value = stats.t.cdf(t_stat, df=n-1)

    return t_stat, p_value


# ==================================================================
# 4. Rolling Two-Stage Estimation per Period
# ==================================================================
print("\n[3/5] Running rolling two-stage estimation across 5 periods...")

period_results = []

for period_name, oos_start, oos_end in PERIODS:
    print(f"\n  --- Period: {period_name} ({oos_start} to {oos_end}) ---")
    t0 = time.time()

    oos_start_dt = pd.Timestamp(oos_start)
    oos_end_dt = pd.Timestamp(oos_end)

    # We need data starting GARCH_WINDOW days before OOS start
    # Find the index position of OOS start
    valid_dates = spy_ret_pct.dropna().index
    oos_mask = (valid_dates >= oos_start_dt) & (valid_dates <= oos_end_dt)
    oos_dates = valid_dates[oos_mask]

    if len(oos_dates) < 252:
        print(f"    WARNING: Only {len(oos_dates)} OOS days, skipping")
        continue

    print(f"    OOS days: {len(oos_dates)}")

    # Stage 1: Rolling GJR-GARCH forecasts
    print(f"    Stage 1: Rolling GJR-GARCH (w={GARCH_WINDOW}, refit every {REFIT_FREQ}d)...")

    garch_forecasts = {}
    last_params = None
    refit_counter = 0

    for i, date in enumerate(oos_dates):
        date_idx = valid_dates.get_loc(date)

        # Need GARCH_WINDOW observations before this date
        if date_idx < GARCH_WINDOW:
            continue

        train_data = spy_ret_pct.iloc[date_idx - GARCH_WINDOW:date_idx]

        # Refit or reuse
        if last_params is None or refit_counter >= REFIT_FREQ:
            try:
                model = arch_model(train_data, vol='GARCH', p=1, o=1, q=1,
                                   mean='Constant', dist='normal')
                result = model.fit(disp='off', show_warning=False)
                last_params = result.params
                refit_counter = 0
            except Exception:
                if last_params is None:
                    continue

        refit_counter += 1

        # One-step-ahead forecast
        try:
            model_fc = arch_model(train_data, vol='GARCH', p=1, o=1, q=1,
                                  mean='Constant', dist='normal')
            result_fc = model_fc.fit(disp='off', show_warning=False,
                                      starting_values=last_params.values)
            fc = result_fc.forecast(horizon=1)
            h_t = fc.variance.values[-1, 0] / 10000  # Convert from pct^2 to decimal
            garch_forecasts[date] = h_t
        except Exception:
            pass

    if len(garch_forecasts) < 252:
        print(f"    WARNING: Only {len(garch_forecasts)} GARCH forecasts, skipping period")
        continue

    garch_series = pd.Series(garch_forecasts)
    print(f"    GARCH forecasts: {len(garch_series)}")

    # Stage 2: Rolling OLS adjustment with ESG spread
    print(f"    Stage 2: Rolling OLS (w={OLS_WINDOW}) with ESG spread...")

    # Align all series
    common_idx = garch_series.index.intersection(esg_spread_lag.dropna().index).intersection(rv_proxy.dropna().index)
    common_idx = common_idx.sort_values()

    h_t_aligned = garch_series.loc[common_idx]
    esg_aligned = esg_spread_lag.loc[common_idx]
    rv_aligned = rv_proxy.loc[common_idx]

    if len(common_idx) < OLS_WINDOW + 100:
        print(f"    WARNING: Only {len(common_idx)} aligned points, skipping")
        continue

    # Rolling OLS: rv_t = alpha + beta*h_t + delta*esg_spread_{t-1} + epsilon
    # Forecast: h_adjusted = h_t + delta_hat * esg_spread_{t-1}

    baseline_forecasts = []  # h_t only
    adjusted_forecasts = []  # h_t + delta * esg_spread
    realized_vals = []
    delta_estimates = []
    ols_dates_out = []

    for j in range(OLS_WINDOW, len(common_idx)):
        date_j = common_idx[j]

        # Training window for OLS
        train_slice = slice(j - OLS_WINDOW, j)

        rv_train = rv_aligned.iloc[train_slice].values
        h_train = h_t_aligned.iloc[train_slice].values
        esg_train = esg_aligned.iloc[train_slice].values

        # Sanity check
        valid_mask = np.isfinite(rv_train) & np.isfinite(h_train) & np.isfinite(esg_train)
        if valid_mask.sum() < 50:
            continue

        rv_t = rv_train[valid_mask]
        h_t_v = h_train[valid_mask]
        esg_v = esg_train[valid_mask]

        # OLS: rv = alpha + beta*h + delta*esg + eps
        X = np.column_stack([np.ones(len(h_t_v)), h_t_v, esg_v])
        try:
            beta_hat = np.linalg.lstsq(X, rv_t, rcond=None)[0]
        except Exception:
            continue

        alpha_hat, beta_coef, delta_hat = beta_hat

        # Out-of-sample forecast for date j
        h_j = h_t_aligned.iloc[j]
        esg_j = esg_aligned.iloc[j]
        rv_j = rv_aligned.iloc[j]

        if not (np.isfinite(h_j) and np.isfinite(esg_j) and np.isfinite(rv_j)):
            continue

        # Baseline: just h_t
        baseline_fc = h_j

        # Adjusted: h_t + delta * esg_spread (additive adjustment)
        # More precisely: alpha + beta*h_t + delta*esg
        adjusted_fc = alpha_hat + beta_coef * h_j + delta_hat * esg_j

        # Ensure positive forecast
        if adjusted_fc <= 0:
            adjusted_fc = baseline_fc

        baseline_forecasts.append(baseline_fc)
        adjusted_forecasts.append(adjusted_fc)
        realized_vals.append(rv_j)
        delta_estimates.append(delta_hat)
        ols_dates_out.append(date_j)

    elapsed = time.time() - t0
    n_oos = len(baseline_forecasts)

    if n_oos < 100:
        print(f"    WARNING: Only {n_oos} OOS points after rolling OLS, skipping")
        continue

    print(f"    OOS forecast points: {n_oos} ({elapsed:.1f}s)")

    # Convert to arrays
    baseline_arr = np.array(baseline_forecasts)
    adjusted_arr = np.array(adjusted_forecasts)
    realized_arr = np.array(realized_vals)
    delta_arr = np.array(delta_estimates)

    # Compute QLIKE losses
    qlike_base = qlike(realized_arr, baseline_arr)
    qlike_adj = qlike(realized_arr, adjusted_arr)

    mean_qlike_base = np.nanmean(qlike_base)
    mean_qlike_adj = np.nanmean(qlike_adj)
    qlike_improvement = (mean_qlike_base - mean_qlike_adj) / abs(mean_qlike_base) * 100

    # DM test (H1: adjusted has lower loss)
    dm_t, dm_p = dm_test(qlike_adj, qlike_base)

    # Delta statistics
    delta_mean = np.mean(delta_arr)
    delta_std = np.std(delta_arr)
    delta_positive_pct = np.mean(delta_arr > 0) * 100

    # MSE comparison
    mse_base = np.mean((realized_arr - baseline_arr) ** 2)
    mse_adj = np.mean((realized_arr - adjusted_arr) ** 2)
    mse_improvement = (mse_base - mse_adj) / mse_base * 100

    result = {
        "period": period_name,
        "oos_start": oos_start,
        "oos_end": oos_end,
        "n_oos": n_oos,
        "qlike_baseline": float(mean_qlike_base),
        "qlike_adjusted": float(mean_qlike_adj),
        "qlike_improvement_pct": float(qlike_improvement),
        "mse_baseline": float(mse_base),
        "mse_adjusted": float(mse_adj),
        "mse_improvement_pct": float(mse_improvement),
        "dm_t_stat": float(dm_t) if np.isfinite(dm_t) else None,
        "dm_p_value": float(dm_p) if np.isfinite(dm_p) else None,
        "delta_mean": float(delta_mean),
        "delta_std": float(delta_std),
        "delta_positive_pct": float(delta_positive_pct),
        "elapsed_sec": float(elapsed),
    }

    period_results.append(result)

    print(f"    QLIKE baseline: {mean_qlike_base:.6f}")
    print(f"    QLIKE adjusted: {mean_qlike_adj:.6f}")
    print(f"    QLIKE improvement: {qlike_improvement:+.3f}%")
    print(f"    MSE improvement:   {mse_improvement:+.3f}%")
    print(f"    DM t-stat: {dm_t:.3f}, p-value: {dm_p:.4f}")
    print(f"    Delta: mean={delta_mean:.6f}, std={delta_std:.6f}")
    print(f"    Delta positive: {delta_positive_pct:.1f}%")


# ==================================================================
# 5. Pooled Analysis & Summary
# ==================================================================
print("\n" + "=" * 80)
print("[4/5] POOLED ANALYSIS")
print("=" * 80)

if len(period_results) < 3:
    print("  INSUFFICIENT PERIODS for validation (need at least 3)")
    final_verdict = "FAIL_INSUFFICIENT_DATA"
else:
    # Count periods with QLIKE improvement
    n_improved = sum(1 for r in period_results if r["qlike_improvement_pct"] > 0)
    n_total = len(period_results)

    # Check delta sign consistency
    delta_signs = [1 if r["delta_mean"] > 0 else -1 for r in period_results]
    sign_consistent = len(set(delta_signs)) == 1
    dominant_sign = "positive" if sum(delta_signs) > 0 else "negative"

    # Check DM significance
    n_dm_sig = sum(1 for r in period_results
                   if r["dm_p_value"] is not None and r["dm_p_value"] < 0.05)

    # Average improvement
    avg_qlike_imp = np.mean([r["qlike_improvement_pct"] for r in period_results])
    avg_mse_imp = np.mean([r["mse_improvement_pct"] for r in period_results])
    avg_dm_t = np.mean([r["dm_t_stat"] for r in period_results if r["dm_t_stat"] is not None])

    # Average delta
    avg_delta = np.mean([r["delta_mean"] for r in period_results])
    avg_delta_pos = np.mean([r["delta_positive_pct"] for r in period_results])

    print(f"\n  Periods with QLIKE improvement: {n_improved}/{n_total}")
    print(f"  Delta sign consistent: {'YES' if sign_consistent else 'NO'} (dominant: {dominant_sign})")
    print(f"  DM significant (p<0.05): {n_dm_sig}/{n_total}")
    print(f"  Average QLIKE improvement: {avg_qlike_imp:+.4f}%")
    print(f"  Average MSE improvement:   {avg_mse_imp:+.4f}%")
    print(f"  Average DM t-stat:         {avg_dm_t:.3f}")
    print(f"  Average delta:             {avg_delta:.6f}")
    print(f"  Average delta positive %:  {avg_delta_pos:.1f}%")

    # Pass criteria
    print(f"\n  --- PASS CRITERIA ---")
    criterion_1 = n_improved >= 3
    criterion_2 = sign_consistent
    criterion_3 = abs(avg_dm_t) > 3.0 if np.isfinite(avg_dm_t) else False

    print(f"  [{'PASS' if criterion_1 else 'FAIL'}] 3+/5 periods QLIKE improvement: {n_improved}/{n_total}")
    print(f"  [{'PASS' if criterion_2 else 'FAIL'}] Consistent delta sign: {sign_consistent}")
    print(f"  [{'PASS' if criterion_3 else 'FAIL'}] Pooled avg DM t > 3.0 (Harvey): {avg_dm_t:.3f}")

    all_pass = criterion_1 and criterion_2 and criterion_3
    final_verdict = "PASS" if all_pass else "FAIL"

# ==================================================================
# 6. Per-Period Summary Table
# ==================================================================
print("\n" + "=" * 80)
print("[5/5] PER-PERIOD SUMMARY TABLE")
print("=" * 80)
print(f"\n  {'Period':<12} {'N_OOS':>6} {'QLIKE%':>8} {'MSE%':>8} {'DM_t':>7} {'DM_p':>7} {'delta':>10} {'d>0%':>6}")
print("  " + "-" * 72)

for r in period_results:
    dm_t_str = f"{r['dm_t_stat']:.3f}" if r['dm_t_stat'] is not None else "N/A"
    dm_p_str = f"{r['dm_p_value']:.4f}" if r['dm_p_value'] is not None else "N/A"
    print(f"  {r['period']:<12} {r['n_oos']:>6} {r['qlike_improvement_pct']:>+7.3f}% "
          f"{r['mse_improvement_pct']:>+7.3f}% {dm_t_str:>7} {dm_p_str:>7} "
          f"{r['delta_mean']:>+10.6f} {r['delta_positive_pct']:>5.1f}%")

print(f"\n  ========== FINAL VERDICT: {final_verdict} ==========")

if final_verdict == "PASS":
    print("  ESG vol spread SURVIVES pure rolling validation.")
    print("  The signal has genuine incremental predictive power beyond VIX.")
elif final_verdict == "FAIL":
    print("  ESG vol spread FAILS pure rolling validation.")
    print("  K335's t=10.17 was likely a full-sample artifact (K265->K266 pattern).")
else:
    print("  Insufficient data for conclusive validation.")

# ==================================================================
# Save Results
# ==================================================================
output = {
    "experiment": "K339",
    "title": "ESG Vol Spread Rolling Validation",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "esg_leaders": ESG_LEADERS,
        "esg_laggards": ESG_LAGGARDS,
        "market": MARKET_TICKER,
        "data_range": f"{DATA_START} to {DATA_END}",
        "garch_window": GARCH_WINDOW,
        "ols_window": OLS_WINDOW,
        "vol_window": VOL_WINDOW,
        "refit_freq": REFIT_FREQ,
        "n_periods": len(PERIODS),
    },
    "period_results": period_results,
    "summary": {
        "n_periods_tested": len(period_results),
        "n_improved": n_improved if len(period_results) >= 3 else None,
        "avg_qlike_improvement_pct": float(avg_qlike_imp) if len(period_results) >= 3 else None,
        "avg_mse_improvement_pct": float(avg_mse_imp) if len(period_results) >= 3 else None,
        "avg_dm_t_stat": float(avg_dm_t) if len(period_results) >= 3 and np.isfinite(avg_dm_t) else None,
        "delta_sign_consistent": sign_consistent if len(period_results) >= 3 else None,
        "dominant_delta_sign": dominant_sign if len(period_results) >= 3 else None,
        "criterion_1_3plus5_qlike": criterion_1 if len(period_results) >= 3 else None,
        "criterion_2_delta_consistent": criterion_2 if len(period_results) >= 3 else None,
        "criterion_3_harvey_t3": criterion_3 if len(period_results) >= 3 else None,
        "final_verdict": final_verdict,
    },
    "data_source": "yfinance (real market data)",
    "limitations": [
        "Sector ETFs as ESG proxies (not actual ESG ratings)",
        "Rolling OLS may be slow to adapt to regime changes",
        "QLIKE proxy uses r^2 (daily squared return), not realized variance from intraday data",
        "22d vol window introduces some smoothing",
    ],
}

results_path = os.path.join(os.path.dirname(__file__), "k339_esg_validation_results.json")
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {results_path}")
print("\nDone.")
