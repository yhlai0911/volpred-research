"""
K456: Taiwan 0050.TW Semivariance VaR Application
==================================================
Background:
  K454 found RS⁻-based VaR passes Trinity test (3/3) for SPY/QQQ/EEM,
  beating GJR-GARCH Skewed-t (1/3). This experiment tests whether
  semivariance VaR also works for Taiwan's 0050.TW ETF.

Asset: 0050.TW (Yuanta/P-shares Taiwan Top 50 ETF)
Data: 2005-2026 (yfinance, Close prices — yfinance v2 removed Adj Close)
OOS: 2023-01-01 to 2024-12-31
Rolling window: 504 trading days

VaR Methods:
  1. GJR-GARCH Normal VaR
  2. GJR-GARCH Skewed-t VaR
  3. RS⁻ (Realized Semivariance negative) Normal VaR
  4. Hybrid (50/50 GARCH + RS⁻)
  5. Historical Simulation (250-day rolling)

Trinity Test at 1% and 5%:
  - Kupiec unconditional coverage
  - Christoffersen independence
  - Engle-Manganelli Dynamic Quantile (DQ)

Notes:
  - 0050.TW has ex-dividend gap issues (K453: skewness=-17.8 on raw data)
  - yfinance v2 removed "Adj Close" column; Close is now auto-adjusted
  - However, historical data may still contain artifacts (e.g., -138.89% return on 2014-01-02)
  - We apply Winsorization at ±15% to remove obvious data artifacts
  - Taiwan market GJR gamma=0.146 (K453), lower than SPY but significant

Data source: yfinance (Close, auto-adjusted in yfinance v2)
"""

import json
import warnings
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model

warnings.filterwarnings("ignore")

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 70)
print("K456: Taiwan 0050.TW Semivariance VaR Application")
print("=" * 70)

ticker = "0050.TW"
print(f"\nDownloading {ticker} data from yfinance...")
df = yf.download(ticker, start="2003-01-01", end="2026-12-31", progress=False)

if df.empty:
    print("ERROR: No data downloaded for 0050.TW")
    sys.exit(1)

# Handle MultiIndex columns from yfinance
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

# yfinance v2 removed Adj Close — Close is now auto-adjusted
prices = df["Close"].dropna()
price_col_used = "Close (yfinance v2 auto-adjusted)"

print(f"  Price column used: {price_col_used}")
print(f"  Date range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total trading days: {len(prices)}")

# Compute log returns (percentage)
returns = np.log(prices / prices.shift(1)).dropna() * 100

# ============================================================
# 1.5 DATA CLEANING: Detect and handle ex-dividend artifacts
# ============================================================
print("\n--- Data Cleaning ---")

# Check for extreme returns (likely ex-dividend artifacts or data errors)
extreme_threshold = 15.0  # ±15% is far beyond normal daily moves for 0050.TW
extreme_mask = returns.abs() > extreme_threshold
n_extreme = extreme_mask.sum()
print(f"  Returns > |{extreme_threshold}%|: {n_extreme}")

if n_extreme > 0:
    print("  Extreme returns detected (likely data artifacts):")
    for date, val in returns[extreme_mask].items():
        print(f"    {date.strftime('%Y-%m-%d')}: {val:.2f}%")

    # Winsorize: clip to ±15%
    print(f"  Applying Winsorization: clipping to ±{extreme_threshold}%")
    returns_clean = returns.clip(lower=-extreme_threshold, upper=extreme_threshold)
else:
    returns_clean = returns.copy()

print(f"  Clean return series length: {len(returns_clean)}")

# Use clean returns for all subsequent analysis
returns = returns_clean

# ============================================================
# 2. DATA DIAGNOSTICS (MANDATORY)
# ============================================================
print("\n" + "=" * 70)
print("DIAGNOSTICS")
print("=" * 70)

# --- 2.1 Descriptive Statistics ---
print("\n--- Descriptive Statistics (after cleaning) ---")
desc = {
    "mean": float(returns.mean()),
    "std": float(returns.std()),
    "skewness": float(returns.skew()),
    "kurtosis": float(returns.kurtosis()),  # excess kurtosis
    "min": float(returns.min()),
    "max": float(returns.max()),
    "count": int(len(returns)),
}
for k, v in desc.items():
    print(f"  {k:>12s}: {v:.4f}" if isinstance(v, float) else f"  {k:>12s}: {v}")

# Sanity check: skewness should be reasonable after cleaning
if abs(desc["skewness"]) > 3:
    print(f"  ⚠️ WARNING: Skewness still extreme ({desc['skewness']:.2f}) after cleaning!")

# --- 2.2 ADF Test ---
from statsmodels.tsa.stattools import adfuller
adf_result = adfuller(returns.values, maxlag=20, autolag="AIC")
adf_stat, adf_pval = adf_result[0], adf_result[1]
print(f"\n--- ADF Test ---")
print(f"  ADF statistic: {adf_stat:.4f}")
print(f"  p-value: {adf_pval:.6f}")
print(f"  Stationary: {'YES' if adf_pval < 0.01 else 'NO'}")

# --- 2.3 ARCH-LM Test ---
from statsmodels.stats.diagnostic import het_arch
arch_lm_stat, arch_lm_pval, _, _ = het_arch(returns.values, nlags=10)
print(f"\n--- ARCH-LM Test (10 lags) ---")
print(f"  LM statistic: {arch_lm_stat:.4f}")
print(f"  p-value: {arch_lm_pval:.6f}")
print(f"  ARCH effects: {'YES' if arch_lm_pval < 0.01 else 'NO'}")

# --- 2.4 Ljung-Box Test on squared returns ---
from statsmodels.stats.diagnostic import acorr_ljungbox
lb_sq = acorr_ljungbox(returns.values**2, lags=[10, 20], return_df=True)
print(f"\n--- Ljung-Box Test (on r²) ---")
for lag in [10, 20]:
    lb_row = lb_sq.loc[lag]
    print(f"  Lag {lag}: Q={lb_row['lb_stat']:.2f}, p={lb_row['lb_pvalue']:.6f}")

# Also on levels
lb = acorr_ljungbox(returns.values, lags=[10, 20], return_df=True)
print(f"\n--- Ljung-Box Test (on returns) ---")
for lag in [10, 20]:
    lb_row = lb.loc[lag]
    print(f"  Lag {lag}: Q={lb_row['lb_stat']:.2f}, p={lb_row['lb_pvalue']:.4f}")

# ============================================================
# 3. GJR-GARCH ESTIMATION (full IS for diagnostics)
# ============================================================
print("\n" + "=" * 70)
print("GJR-GARCH ESTIMATION (diagnostics on full sample)")
print("=" * 70)

gjr_full = arch_model(returns.values, vol="GARCH", p=1, o=1, q=1, dist="normal")
res_full = gjr_full.fit(disp="off")
print(f"\n  omega  = {res_full.params['omega']:.6f}")
print(f"  alpha  = {res_full.params['alpha[1]']:.6f}")
print(f"  gamma  = {res_full.params['gamma[1]']:.6f}")
print(f"  beta   = {res_full.params['beta[1]']:.6f}")
persistence = res_full.params['alpha[1]'] + res_full.params['gamma[1]'] / 2 + res_full.params['beta[1]']
print(f"  persistence = {persistence:.4f}")
print(f"  Convergence: {'YES' if res_full.convergence_flag == 0 else 'NO (flag=' + str(res_full.convergence_flag) + ')'}")

if persistence >= 1.0:
    print("  ⚠️ WARNING: persistence >= 1.0, IGARCH territory!")

# Standardized residuals ARCH-LM
std_resid = res_full.std_resid
arch_lm2_stat, arch_lm2_pval, _, _ = het_arch(std_resid, nlags=10)
print(f"\n--- Residual ARCH-LM (10 lags) ---")
print(f"  LM statistic: {arch_lm2_stat:.4f}")
print(f"  p-value: {arch_lm2_pval:.6f}")
print(f"  Remaining ARCH: {'YES — model may be misspecified' if arch_lm2_pval < 0.05 else 'NO — good fit'}")

# ============================================================
# 4. VaR BACKTESTING
# ============================================================
print("\n" + "=" * 70)
print("VaR BACKTESTING (OOS: 2023-2024)")
print("=" * 70)

oos_start = "2023-01-01"
oos_end = "2024-12-31"
window = 504  # rolling estimation window

# Identify OOS period
oos_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
oos_indices = returns.index[oos_mask]
print(f"  OOS period: {oos_indices[0].strftime('%Y-%m-%d')} to {oos_indices[-1].strftime('%Y-%m-%d')}")
print(f"  OOS trading days: {len(oos_indices)}")

# Pre-allocate VaR forecasts
alpha_levels = [0.01, 0.05]
methods = [
    "GJR-Normal",
    "GJR-SkewT",
    "RS_neg-Normal",
    "Hybrid",
    "HistSim-250",
]

# Store results: method -> alpha -> list of (date, var_forecast, actual_return)
var_results = {m: {a: [] for a in alpha_levels} for m in methods}

# Get return values as array for efficiency
returns_array = returns.values
returns_index = returns.index
n_total = len(returns_array)

# Find OOS start/end indices in the array
oos_start_idx = None
for i, dt in enumerate(returns_index):
    if dt >= pd.Timestamp(oos_start):
        oos_start_idx = i
        break

oos_end_idx = None
for i, dt in enumerate(returns_index):
    if dt > pd.Timestamp(oos_end):
        oos_end_idx = i
        break
if oos_end_idx is None:
    oos_end_idx = n_total

print(f"  OOS array indices: [{oos_start_idx}, {oos_end_idx})")
print(f"  First IS window: [{oos_start_idx - window}, {oos_start_idx})")

# Verify enough data
if oos_start_idx < window:
    print(f"  ERROR: Not enough IS data. Need {window}, have {oos_start_idx}")
    sys.exit(1)

n_oos = oos_end_idx - oos_start_idx
print(f"\n  Running rolling VaR estimation ({n_oos} days)...")

# Import SkewStudent outside loop for efficiency
from arch.univariate.distribution import SkewStudent
skewt_dist = SkewStudent()

# Progress tracking
progress_marks = set([int(n_oos * p) for p in [0.1, 0.25, 0.5, 0.75, 1.0]])

for t_idx in range(oos_start_idx, oos_end_idx):
    progress = t_idx - oos_start_idx
    if progress in progress_marks:
        pct = progress / n_oos * 100
        print(f"    Progress: {pct:.0f}% ({progress}/{n_oos})")

    # IS window
    is_start = t_idx - window
    is_returns = returns_array[is_start:t_idx]
    actual_return = returns_array[t_idx]
    date = returns_index[t_idx]

    # --- Method 1: GJR-GARCH Normal ---
    gjr_cond_vol = np.nan
    gjr_cond_mean = np.nan
    try:
        model = arch_model(is_returns, vol="GARCH", p=1, o=1, q=1, dist="normal")
        res = model.fit(disp="off", show_warning=False)
        forecast = res.forecast(horizon=1)
        cond_var = forecast.variance.values[-1, 0]
        gjr_cond_vol = np.sqrt(cond_var)
        gjr_cond_mean = forecast.mean.values[-1, 0]
        for alpha in alpha_levels:
            z = stats.norm.ppf(alpha)
            var_forecast = gjr_cond_mean + z * gjr_cond_vol
            var_results["GJR-Normal"][alpha].append((date, var_forecast, actual_return))
    except Exception:
        for alpha in alpha_levels:
            var_results["GJR-Normal"][alpha].append((date, np.nan, actual_return))

    # --- Method 2: GJR-GARCH Skewed-t ---
    try:
        model_st = arch_model(is_returns, vol="GARCH", p=1, o=1, q=1, dist="skewt")
        res_st = model_st.fit(disp="off", show_warning=False)
        forecast_st = res_st.forecast(horizon=1)
        cond_var_st = forecast_st.variance.values[-1, 0]
        cond_vol_st = np.sqrt(cond_var_st)
        cond_mean_st = forecast_st.mean.values[-1, 0]

        # Get skewed-t parameters
        eta = res_st.params.get("eta", res_st.params.get("nu", 8.0))  # df
        lam = res_st.params.get("lambda", 0.0)  # skewness parameter

        for alpha in alpha_levels:
            z_skewt = skewt_dist.ppf(alpha, parameters=np.array([eta, lam]))
            var_forecast_st = cond_mean_st + z_skewt * cond_vol_st
            var_results["GJR-SkewT"][alpha].append((date, var_forecast_st, actual_return))
    except Exception:
        for alpha in alpha_levels:
            var_results["GJR-SkewT"][alpha].append((date, np.nan, actual_return))

    # --- Method 3: RS⁻ Normal VaR (Realized Semivariance, negative) ---
    # EWMA on squared negative returns (lambda=0.94, RiskMetrics standard)
    decay = 0.94
    sq_neg = np.where(is_returns < 0, is_returns ** 2, 0.0)
    # Compute EWMA: iterate forward so most recent has highest weight
    ewma_rs_neg = 0.0
    for k in range(len(sq_neg)):
        ewma_rs_neg = decay * ewma_rs_neg + (1 - decay) * sq_neg[k]

    # Scale semivariance to full variance: multiply by 2
    # (downside semivariance ≈ 0.5 * total variance for symmetric distributions)
    semivar_vol = np.sqrt(ewma_rs_neg * 2)

    for alpha in alpha_levels:
        z = stats.norm.ppf(alpha)
        var_forecast_rs = z * semivar_vol  # mean ≈ 0 for daily
        var_results["RS_neg-Normal"][alpha].append((date, var_forecast_rs, actual_return))

    # --- Method 4: Hybrid (50/50 GARCH + RS⁻) ---
    for alpha in alpha_levels:
        garch_var = var_results["GJR-Normal"][alpha][-1][1]
        rs_var = var_results["RS_neg-Normal"][alpha][-1][1]
        if not np.isnan(garch_var) and not np.isnan(rs_var):
            hybrid_var = 0.5 * garch_var + 0.5 * rs_var
        elif not np.isnan(garch_var):
            hybrid_var = garch_var
        else:
            hybrid_var = rs_var
        var_results["Hybrid"][alpha].append((date, hybrid_var, actual_return))

    # --- Method 5: Historical Simulation (250-day rolling) ---
    hs_window = min(250, len(is_returns))
    hs_returns = is_returns[-hs_window:]
    for alpha in alpha_levels:
        hs_var = np.percentile(hs_returns, alpha * 100)
        var_results["HistSim-250"][alpha].append((date, hs_var, actual_return))

print("  VaR estimation complete.")

# ============================================================
# 5. TRINITY TEST (Kupiec + Christoffersen + DQ)
# ============================================================
print("\n" + "=" * 70)
print("TRINITY TEST RESULTS")
print("=" * 70)


def kupiec_test(violations, n_total, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n_viol = np.sum(violations)
    p_hat = n_viol / n_total if n_total > 0 else 0
    if p_hat == 0 or p_hat == 1:
        return 0.0, 1.0  # degenerate
    lr = -2 * (n_viol * np.log(alpha / p_hat) +
               (n_total - n_viol) * np.log((1 - alpha) / (1 - p_hat)))
    pval = 1 - stats.chi2.cdf(lr, df=1)
    return lr, pval


def christoffersen_test(violations):
    """Christoffersen (1998) independence test."""
    n = len(violations)
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i - 1] == 0 and violations[i] == 0:
            n00 += 1
        elif violations[i - 1] == 0 and violations[i] == 1:
            n01 += 1
        elif violations[i - 1] == 1 and violations[i] == 0:
            n10 += 1
        else:
            n11 += 1

    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return 0.0, 1.0
    p01 = n01 / (n00 + n01)
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n

    if p == 0 or p == 1 or p01 == 0 or p01 == 1:
        return 0.0, 1.0
    if p11 == 0 or p11 == 1:
        return 0.0, 1.0

    lr_ind = -2 * (
        (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p)
        - n00 * np.log(1 - p01) - n01 * np.log(p01)
        - n10 * np.log(1 - p11) - n11 * np.log(p11)
    )
    pval = 1 - stats.chi2.cdf(lr_ind, df=1)
    return lr_ind, pval


def dq_test(violations, var_forecasts, actual_returns, n_lags=4):
    """Engle & Manganelli (2004) Dynamic Quantile test."""
    T = len(violations)
    if T <= n_lags + 2:
        return 0.0, 1.0

    hits = violations.astype(float) - np.mean(violations)

    # Build regressor matrix: constant + lagged hits + VaR
    X = np.ones((T - n_lags, 1))
    for lag in range(1, n_lags + 1):
        X = np.column_stack([X, hits[n_lags - lag:T - lag]])
    X = np.column_stack([X, var_forecasts[n_lags:]])

    y = hits[n_lags:]

    try:
        XtX = X.T @ X
        # Add small ridge regularization for numerical stability
        XtX_inv = np.linalg.inv(XtX + 1e-10 * np.eye(XtX.shape[0]))
        beta = XtX_inv @ X.T @ y
        dq_stat = float(beta.T @ X.T @ X @ beta)
        pval = 1 - stats.chi2.cdf(dq_stat, df=X.shape[1])
        return dq_stat, pval
    except np.linalg.LinAlgError:
        return 0.0, 1.0


def basel_zone(violation_rate, alpha):
    """Basel traffic light: Green/Yellow/Red."""
    if alpha == 0.01:
        if violation_rate <= 0.016:
            return "Green"
        elif violation_rate <= 0.0265:
            return "Yellow"
        else:
            return "Red"
    elif alpha == 0.05:
        if violation_rate <= 0.065:
            return "Green"
        elif violation_rate <= 0.085:
            return "Yellow"
        else:
            return "Red"
    return "Unknown"


# Collect all results
all_results = {}

for method in methods:
    all_results[method] = {}
    for alpha in alpha_levels:
        records = var_results[method][alpha]
        dates = [r[0] for r in records]
        var_fcasts = np.array([r[1] for r in records])
        actuals = np.array([r[2] for r in records])

        # Remove NaN
        valid = ~np.isnan(var_fcasts)
        var_fcasts_v = var_fcasts[valid]
        actuals_v = actuals[valid]
        n_valid = len(actuals_v)

        violations = (actuals_v < var_fcasts_v).astype(int)
        n_violations = int(violations.sum())
        violation_rate = n_violations / n_valid if n_valid > 0 else 0

        # Tests
        kup_stat, kup_pval = kupiec_test(violations, n_valid, alpha)
        chr_stat, chr_pval = christoffersen_test(violations)
        dq_stat, dq_pval = dq_test(violations, var_fcasts_v, actuals_v)

        zone = basel_zone(violation_rate, alpha)

        # Trinity pass: all three p-values > 0.05
        trinity_pass = bool((kup_pval > 0.05) and (chr_pval > 0.05) and (dq_pval > 0.05))

        result = {
            "n_obs": n_valid,
            "n_violations": n_violations,
            "violation_rate": round(violation_rate, 4),
            "expected_rate": alpha,
            "basel_zone": zone,
            "kupiec": {"stat": round(float(kup_stat), 4), "p_value": round(float(kup_pval), 4)},
            "christoffersen": {"stat": round(float(chr_stat), 4), "p_value": round(float(chr_pval), 4)},
            "dq": {"stat": round(float(dq_stat), 4), "p_value": round(float(dq_pval), 4)},
            "trinity_pass": trinity_pass,
        }
        all_results[method][f"{int(alpha*100)}%"] = result

        # Print summary
        pass_str = "PASS" if trinity_pass else "FAIL"
        tests_pass = sum([kup_pval > 0.05, chr_pval > 0.05, dq_pval > 0.05])
        print(f"\n  {method} @ {int(alpha*100)}% VaR:")
        print(f"    Violations: {n_violations}/{n_valid} = {violation_rate:.3f} (expected {alpha:.2f})")
        print(f"    Basel Zone: {zone}")
        print(f"    Kupiec:          stat={kup_stat:.3f}, p={kup_pval:.4f} {'PASS' if kup_pval>0.05 else 'FAIL'}")
        print(f"    Christoffersen:  stat={chr_stat:.3f}, p={chr_pval:.4f} {'PASS' if chr_pval>0.05 else 'FAIL'}")
        print(f"    DQ:              stat={dq_stat:.3f}, p={dq_pval:.4f} {'PASS' if dq_pval>0.05 else 'FAIL'}")
        print(f"    Trinity: {pass_str} ({tests_pass}/3)")

# ============================================================
# 6. SUMMARY TABLE
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: Trinity Test Pass/Fail")
print("=" * 70)

print(f"\n{'Method':<20} {'1% VaR':>10} {'5% VaR':>10} {'Total':>8}")
print("-" * 52)

method_scores = {}
for method in methods:
    r1 = all_results[method]["1%"]
    r5 = all_results[method]["5%"]
    p1 = "PASS" if r1["trinity_pass"] else "FAIL"
    p5 = "PASS" if r5["trinity_pass"] else "FAIL"
    total = int(r1["trinity_pass"]) + int(r5["trinity_pass"])
    method_scores[method] = total
    print(f"  {method:<18} {p1:>10} {p5:>10} {total:>6}/2")

best_method = max(method_scores, key=method_scores.get)
best_score = method_scores[best_method]
# Handle ties
tied_methods = [m for m, s in method_scores.items() if s == best_score]
print(f"\n  Best method(s): {', '.join(tied_methods)} ({best_score}/2)")

# ============================================================
# 7. COMPARISON WITH K454 (SPY/QQQ/EEM)
# ============================================================
print("\n" + "=" * 70)
print("COMPARISON WITH K454 (SPY/QQQ/EEM)")
print("=" * 70)

k454_reference = {
    "RS_neg-Normal": "3/3 markets passed Trinity (1%+5%)",
    "GJR-SkewT": "1/3 markets passed Trinity",
}

print("\n  K454 Results (SPY/QQQ/EEM):")
for m, r in k454_reference.items():
    print(f"    {m}: {r}")

tw_rs = all_results.get("RS_neg-Normal", {})
tw_gjr_st = all_results.get("GJR-SkewT", {})
tw_rs_pass = sum(1 for a in ["1%", "5%"] if tw_rs.get(a, {}).get("trinity_pass", False))
tw_gjr_st_pass = sum(1 for a in ["1%", "5%"] if tw_gjr_st.get(a, {}).get("trinity_pass", False))

print(f"\n  K456 Results (0050.TW):")
print(f"    RS_neg-Normal: {tw_rs_pass}/2 levels passed")
print(f"    GJR-SkewT:     {tw_gjr_st_pass}/2 levels passed")

if tw_rs_pass > tw_gjr_st_pass:
    comparison = "CONSISTENT: RS- > GJR-SkewT in Taiwan (same as K454)"
elif tw_rs_pass == tw_gjr_st_pass:
    comparison = "TIED: RS- = GJR-SkewT in Taiwan (partial consistency)"
else:
    comparison = "DIFFERS: GJR-SkewT > RS- in Taiwan (opposite to K454)"
print(f"\n  Comparison: {comparison}")

# ============================================================
# 8. ADDITIONAL ANALYSIS: Violation timing
# ============================================================
print("\n" + "=" * 70)
print("VIOLATION ANALYSIS")
print("=" * 70)

# For each method at 1% level, check when violations occur
for method in methods:
    records = var_results[method][0.01]
    var_fcasts = np.array([r[1] for r in records])
    actuals = np.array([r[2] for r in records])
    dates_list = [r[0] for r in records]

    valid = ~np.isnan(var_fcasts)
    violations_idx = np.where(valid & (actuals < var_fcasts))[0]

    if len(violations_idx) > 0:
        viol_dates = [dates_list[i] for i in violations_idx]
        viol_returns = [actuals[i] for i in violations_idx]
        viol_vars = [var_fcasts[i] for i in violations_idx]

        print(f"\n  {method} @ 1% violations:")
        for d, r, v in zip(viol_dates, viol_returns, viol_vars):
            severity = r / v  # how many times VaR was breached
            print(f"    {d.strftime('%Y-%m-%d')}: return={r:.2f}%, VaR={v:.2f}%, severity={severity:.2f}x")

# ============================================================
# 9. SAVE RESULTS
# ============================================================

# Compute data cleaning summary
cleaning_summary = {
    "original_count": int(len(returns_clean)),
    "extreme_returns_clipped": int(n_extreme),
    "winsorization_threshold": extreme_threshold,
    "dates_affected": [d.strftime('%Y-%m-%d') for d in returns.index[extreme_mask]] if n_extreme > 0 else [],
}

output = {
    "experiment_id": "K456",
    "title": "Taiwan 0050.TW Semivariance VaR Application",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (Close, auto-adjusted in yfinance v2)",
    "price_column": price_col_used,
    "asset": "0050.TW",
    "data_range": f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    "total_trading_days": int(len(returns)),
    "oos_period": f"{oos_start} to {oos_end}",
    "oos_days": int(n_oos),
    "rolling_window": window,
    "data_cleaning": cleaning_summary,
    "diagnostics": {
        "descriptive_stats": desc,
        "adf_test": {
            "statistic": round(float(adf_stat), 4),
            "p_value": round(float(adf_pval), 6),
            "stationary": bool(adf_pval < 0.01),
        },
        "arch_lm_test": {
            "statistic": round(float(arch_lm_stat), 4),
            "p_value": round(float(arch_lm_pval), 6),
            "arch_effects": bool(arch_lm_pval < 0.01),
        },
        "ljung_box_squared_returns": {
            "lag_10_Q": round(float(lb_sq.loc[10]['lb_stat']), 2),
            "lag_10_p": round(float(lb_sq.loc[10]['lb_pvalue']), 6),
            "lag_20_Q": round(float(lb_sq.loc[20]['lb_stat']), 2),
            "lag_20_p": round(float(lb_sq.loc[20]['lb_pvalue']), 6),
        },
        "gjr_garch_full_sample": {
            "omega": round(float(res_full.params['omega']), 6),
            "alpha": round(float(res_full.params['alpha[1]']), 6),
            "gamma": round(float(res_full.params['gamma[1]']), 6),
            "beta": round(float(res_full.params['beta[1]']), 6),
            "persistence": round(float(persistence), 4),
            "convergence": res_full.convergence_flag == 0,
            "residual_arch_lm_pval": round(float(arch_lm2_pval), 6),
        },
    },
    "var_methods": methods,
    "var_levels": [0.01, 0.05],
    "trinity_test_results": all_results,
    "summary": {
        "method_scores": {m: f"{s}/2" for m, s in method_scores.items()},
        "best_method": best_method if len(tied_methods) == 1 else tied_methods,
        "best_score": f"{best_score}/2",
    },
    "comparison_with_k454": {
        "k454_rs_neg_result": "3/3 markets Trinity pass",
        "k454_gjr_skewt_result": "1/3 markets Trinity pass",
        "k456_rs_neg_result": f"{tw_rs_pass}/2 levels pass",
        "k456_gjr_skewt_result": f"{tw_gjr_st_pass}/2 levels pass",
        "comparison": comparison,
        "consistent": tw_rs_pass >= tw_gjr_st_pass,
    },
    "key_findings": [],
    "limitations": [
        "Single asset (0050.TW only) — cross-market Taiwan confirmation needed",
        "OOS limited to 2023-2024 (2 years)",
        "EWMA lambda=0.94 not optimized for Taiwan market",
        "yfinance v2 auto-adjusts Close but historical artifacts remain (Winsorized)",
        "Semivariance scaling factor (x2) assumes approximate symmetry baseline",
        f"{n_extreme} extreme returns Winsorized at ±{extreme_threshold}% — may affect tail coverage",
    ],
}

# Build key findings
findings = []
findings.append(f"Best VaR method for 0050.TW: {best_method if len(tied_methods)==1 else ', '.join(tied_methods)} ({best_score}/2 Trinity pass)")

for method in methods:
    r1 = all_results[method]["1%"]
    r5 = all_results[method]["5%"]
    findings.append(f"{method}: 1%={r1['violation_rate']:.3f}({r1['basel_zone']}), 5%={r5['violation_rate']:.3f}({r5['basel_zone']})")

findings.append(f"GJR gamma (full sample) = {res_full.params['gamma[1]']:.4f}, persistence = {persistence:.4f}")
findings.append(comparison)

output["key_findings"] = findings

output_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a6247663/experiments/k456_taiwan_semivar_var_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n\nResults saved to: experiments/k456_taiwan_semivar_var_results.json")
print(f"Script: experiments/k456_taiwan_semivar_var.py")
print("\n" + "=" * 70)
print("K456 COMPLETE")
print("=" * 70)
