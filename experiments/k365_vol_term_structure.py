#!/usr/bin/env python3
"""
K365: Realized Volatility Term Structure — How Does Predictability Decay with Horizon?

PURPOSE:
  K360 found weekly R²=0.50 (peak), monthly 0.24. But K362 revealed same-day bias
  inflated the daily R². This experiment properly tests the vol TERM STRUCTURE using
  LAGGED predictors ONLY (VIX_{t-1}, RV_{t-1}).

DATA: SPY + VIX daily from yfinance, 2005-2024.

METHODOLOGY (all using LAGGED predictors):
  1. For h = 1, 2, 5, 10, 22, 44, 66 days:
     - Target: RV(t, t+h) = realized vol over next h days
     - Predictors: VIX_{t-1}, RV_{t-h-1, t-1} (past h-day RV)
     - Models: VIX-only, RV-only, Combined (VIX + RV)
     - OOS R² via expanding window (train≥1000, predict next 250)
  2. Build the "predictability term structure": R² vs horizon h
  3. Scaling law test: does R²(h) follow a power law? R² ∝ h^α
  4. Practical cutoff: at what horizon does VIX lose predictive power?

KEY: ALL predictors are lagged by at least 1 day. No same-day information leakage.

[提出: User, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import json
import warnings
from scipy import stats
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

warnings.filterwarnings('ignore')

print("=" * 80)
print("K365: Realized Volatility Term Structure (Lagged Predictors Only)")
print("=" * 80)

# ─── 1. Data Download ───────────────────────────────────────────────────────
print("\n[1] Downloading SPY + VIX data from yfinance (2004-2025)...")

spy = yf.download("SPY", start="2004-01-01", end="2025-01-01", auto_adjust=True, progress=False)
vix = yf.download("^VIX", start="2004-01-01", end="2025-01-01", auto_adjust=True, progress=False)

# Handle MultiIndex columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  SPY: {len(spy)} rows ({spy.index[0].date()} to {spy.index[-1].date()})")
print(f"  VIX: {len(vix)} rows ({vix.index[0].date()} to {vix.index[-1].date()})")

# ─── 2. Compute Daily Returns & Realized Volatility ─────────────────────────
print("\n[2] Computing daily returns and realized volatility...")

# Daily log returns
spy['log_ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['ret_sq'] = spy['log_ret'] ** 2  # squared return for RV computation

# Merge VIX
df = spy[['Close', 'log_ret', 'ret_sq']].copy()
df['VIX'] = vix['Close']
df = df.dropna()

# Trim to 2005-2024
df = df.loc['2005-01-01':'2024-12-31']
print(f"  Working sample: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# ─── 3. Build h-step RV targets & lagged predictors ─────────────────────────
print("\n[3] Building targets and predictors for each horizon...")

horizons = [1, 2, 5, 10, 22, 44, 66]

def compute_rv(ret_sq_series, window):
    """Compute annualized realized volatility over 'window' days (forward-looking)."""
    rv = ret_sq_series.rolling(window=window).mean().shift(-window + 1)
    # shift(-window+1) aligns so that rv[t] = mean(ret_sq[t], ..., ret_sq[t+window-1])
    # But we want FORWARD rv: rv[t] = mean(ret_sq[t+1], ..., ret_sq[t+window])
    rv_forward = ret_sq_series.rolling(window=window).mean().shift(-window)
    return np.sqrt(rv_forward * 252)  # annualized

def compute_past_rv(ret_sq_series, window):
    """Compute annualized realized volatility over past 'window' days (backward-looking)."""
    rv_past = ret_sq_series.rolling(window=window).mean()
    return np.sqrt(rv_past * 252)  # annualized


# ─── 4. OOS Evaluation Framework ────────────────────────────────────────────
print("\n[4] Running OOS evaluation for each horizon...")
print("    Method: Expanding window, min train=1000 days, test blocks=250 days")
print("    Models: VIX-only, RV-only, Combined (VIX+RV)")
print("    ALL predictors lagged by 1 day (t-1) — NO same-day info\n")

MIN_TRAIN = 1000
TEST_BLOCK = 250

results = {}

for h in horizons:
    print(f"  Horizon h={h:3d} days ... ", end="", flush=True)

    # Target: forward h-day RV starting from t+1
    target = compute_rv(df['ret_sq'], h)

    # Predictors (ALL lagged by 1 day):
    # VIX_{t-1}: yesterday's VIX (converted to decimal)
    vix_lag = df['VIX'].shift(1) / 100.0

    # Past h-day RV_{t-h, t-1}: RV over past h days, lagged by 1
    past_rv = compute_past_rv(df['ret_sq'], h).shift(1)

    # Combine into a clean dataframe
    data = pd.DataFrame({
        'target': target,
        'vix_lag': vix_lag,
        'past_rv': past_rv
    }, index=df.index).dropna()

    if len(data) < MIN_TRAIN + TEST_BLOCK:
        print(f"SKIP (only {len(data)} rows)")
        continue

    # OOS predictions using expanding window
    models_preds = {
        'vix_only': [],
        'rv_only': [],
        'combined': [],
        'benchmark': []  # historical mean
    }
    actuals = []

    n = len(data)
    test_start = MIN_TRAIN

    while test_start + TEST_BLOCK <= n:
        test_end = min(test_start + TEST_BLOCK, n)

        train = data.iloc[:test_start]
        test = data.iloc[test_start:test_end]

        y_train = train['target'].values
        y_test = test['target'].values

        # Historical mean benchmark
        hist_mean = y_train.mean()
        models_preds['benchmark'].extend([hist_mean] * len(y_test))

        # VIX-only model
        X_train_vix = train[['vix_lag']].values
        X_test_vix = test[['vix_lag']].values
        reg_vix = LinearRegression().fit(X_train_vix, y_train)
        models_preds['vix_only'].extend(reg_vix.predict(X_test_vix).tolist())

        # RV-only model
        X_train_rv = train[['past_rv']].values
        X_test_rv = test[['past_rv']].values
        reg_rv = LinearRegression().fit(X_train_rv, y_train)
        models_preds['rv_only'].extend(reg_rv.predict(X_test_rv).tolist())

        # Combined model (VIX + RV)
        X_train_c = train[['vix_lag', 'past_rv']].values
        X_test_c = test[['vix_lag', 'past_rv']].values
        reg_c = LinearRegression().fit(X_train_c, y_train)
        models_preds['combined'].extend(reg_c.predict(X_test_c).tolist())

        actuals.extend(y_test.tolist())

        test_start += TEST_BLOCK

    actuals = np.array(actuals)

    # Compute OOS R² for each model
    ss_tot = np.sum((actuals - np.mean(actuals)) ** 2)

    horizon_results = {}
    for model_name in ['vix_only', 'rv_only', 'combined']:
        preds = np.array(models_preds[model_name])
        ss_res = np.sum((actuals - preds) ** 2)
        oos_r2 = 1 - ss_res / ss_tot

        # Also compute MSFE ratio vs benchmark
        benchmark_preds = np.array(models_preds['benchmark'])
        msfe_model = np.mean((actuals - preds) ** 2)
        msfe_bench = np.mean((actuals - benchmark_preds) ** 2)
        msfe_ratio = msfe_model / msfe_bench

        # Correlation between predicted and actual
        corr = np.corrcoef(actuals, preds)[0, 1]

        horizon_results[model_name] = {
            'oos_r2': round(oos_r2, 4),
            'msfe_ratio': round(msfe_ratio, 4),
            'correlation': round(corr, 4),
            'n_test': len(actuals)
        }

    # In-sample R² for reference (full sample, combined model)
    X_full = data[['vix_lag', 'past_rv']].values
    y_full = data['target'].values
    reg_full = LinearRegression().fit(X_full, y_full)
    is_r2 = r2_score(y_full, reg_full.predict(X_full))

    # In-sample coefficients
    beta_vix = reg_full.coef_[0]
    beta_rv = reg_full.coef_[1]
    intercept = reg_full.intercept_

    horizon_results['in_sample'] = {
        'r2': round(is_r2, 4),
        'beta_vix': round(beta_vix, 4),
        'beta_rv': round(beta_rv, 4),
        'intercept': round(intercept, 4),
        'n_total': len(data)
    }

    results[h] = horizon_results

    best_model = max(['vix_only', 'rv_only', 'combined'],
                     key=lambda m: horizon_results[m]['oos_r2'])
    best_r2 = horizon_results[best_model]['oos_r2']

    print(f"OOS R²: VIX={horizon_results['vix_only']['oos_r2']:.3f}  "
          f"RV={horizon_results['rv_only']['oos_r2']:.3f}  "
          f"Combined={horizon_results['combined']['oos_r2']:.3f}  "
          f"(IS={is_r2:.3f}, n_test={len(actuals)})")


# ─── 5. Results Summary ─────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("RESULTS: Predictability Term Structure (OOS R²)")
print("=" * 80)

print(f"\n{'Horizon':>8} | {'VIX-only':>10} | {'RV-only':>10} | {'Combined':>10} | {'IS R²':>8} | {'Best':>10}")
print("-" * 75)

oos_vix = []
oos_rv = []
oos_comb = []
h_list = []

for h in horizons:
    if h not in results:
        continue
    r = results[h]
    best = max(['vix_only', 'rv_only', 'combined'], key=lambda m: r[m]['oos_r2'])
    best_label = {'vix_only': 'VIX', 'rv_only': 'RV', 'combined': 'VIX+RV'}[best]

    print(f"  h={h:3d}d | {r['vix_only']['oos_r2']:>10.4f} | {r['rv_only']['oos_r2']:>10.4f} | "
          f"{r['combined']['oos_r2']:>10.4f} | {r['in_sample']['r2']:>8.4f} | {best_label:>10}")

    h_list.append(h)
    oos_vix.append(r['vix_only']['oos_r2'])
    oos_rv.append(r['rv_only']['oos_r2'])
    oos_comb.append(r['combined']['oos_r2'])


# ─── 6. Scaling Law Analysis ────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SCALING LAW: Does R²(h) follow a power law?")
print("=" * 80)

# Test: log(R²) = α * log(h) + c  for the combined model
# Only use horizons where R² > 0 for log transform
valid = [(h, r2) for h, r2 in zip(h_list, oos_comb) if r2 > 0]

if len(valid) >= 3:
    h_valid = np.array([v[0] for v in valid])
    r2_valid = np.array([v[1] for v in valid])

    log_h = np.log(h_valid)
    log_r2 = np.log(r2_valid)

    slope, intercept, r_val, p_val, se = stats.linregress(log_h, log_r2)

    print(f"\n  Power law fit: log(R²) = {slope:.4f} * log(h) + {intercept:.4f}")
    print(f"  α (exponent) = {slope:.4f}")
    print(f"  R² of fit    = {r_val**2:.4f}")
    print(f"  p-value      = {p_val:.6f}")

    if slope > 0:
        print(f"\n  → Predictability INCREASES with horizon (α > 0)")
        print(f"    This is consistent with VIX being a better predictor of")
        print(f"    longer-term vol (noise averages out)")
    elif slope < 0:
        print(f"\n  → Predictability DECREASES with horizon (α < 0)")
        print(f"    Signal decays at longer horizons")

    # Find where R² crosses key thresholds
    for threshold in [0.10, 0.05, 0.01]:
        if slope != 0:
            h_threshold = np.exp((np.log(threshold) - intercept) / slope)
            if 1 <= h_threshold <= 252:
                print(f"  → R² crosses {threshold:.2f} at h ≈ {h_threshold:.0f} days")
else:
    print("  Not enough valid data points for power law fit")


# ─── 7. VIX vs RV Comparison ────────────────────────────────────────────────
print("\n" + "=" * 80)
print("VIX vs RV: Which predictor dominates at each horizon?")
print("=" * 80)

print(f"\n{'Horizon':>8} | {'VIX R²':>8} | {'RV R²':>8} | {'Δ(VIX-RV)':>10} | {'VIX β':>8} | {'RV β':>8} | Winner")
print("-" * 78)

for h in horizons:
    if h not in results:
        continue
    r = results[h]
    delta = r['vix_only']['oos_r2'] - r['rv_only']['oos_r2']
    winner = "VIX" if delta > 0.01 else ("RV" if delta < -0.01 else "≈ TIE")

    print(f"  h={h:3d}d | {r['vix_only']['oos_r2']:>8.4f} | {r['rv_only']['oos_r2']:>8.4f} | "
          f"{delta:>10.4f} | {r['in_sample']['beta_vix']:>8.4f} | {r['in_sample']['beta_rv']:>8.4f} | {winner}")


# ─── 8. Monotonicity Test ───────────────────────────────────────────────────
print("\n" + "=" * 80)
print("MONOTONICITY: Does R² monotonically increase or decrease with horizon?")
print("=" * 80)

# Check if combined OOS R² is monotonically increasing
diffs = [oos_comb[i+1] - oos_comb[i] for i in range(len(oos_comb)-1)]
n_increasing = sum(1 for d in diffs if d > 0)
n_decreasing = sum(1 for d in diffs if d < 0)

print(f"\n  Combined OOS R² sequence: {[round(r, 4) for r in oos_comb]}")
print(f"  Horizons:                 {h_list}")
print(f"  Diffs (h[i+1] - h[i]):   {[round(d, 4) for d in diffs]}")
print(f"  Increasing steps: {n_increasing}/{len(diffs)}")
print(f"  Decreasing steps: {n_decreasing}/{len(diffs)}")

if n_increasing == len(diffs):
    print("  → MONOTONICALLY INCREASING: longer horizon = more predictable")
elif n_decreasing == len(diffs):
    print("  → MONOTONICALLY DECREASING: shorter horizon = more predictable")
else:
    peak_idx = oos_comb.index(max(oos_comb))
    print(f"  → NON-MONOTONIC: Peak at h={h_list[peak_idx]} days (R²={oos_comb[peak_idx]:.4f})")


# ─── 9. Practical Significance Test (DM-like) ───────────────────────────────
print("\n" + "=" * 80)
print("STATISTICAL SIGNIFICANCE: Combined vs Benchmark at each horizon")
print("=" * 80)

for h in horizons:
    if h not in results:
        continue
    r = results[h]

    # Re-run to get actual forecast errors for DM test
    target = compute_rv(df['ret_sq'], h)
    vix_lag = df['VIX'].shift(1) / 100.0
    past_rv = compute_past_rv(df['ret_sq'], h).shift(1)

    data = pd.DataFrame({
        'target': target,
        'vix_lag': vix_lag,
        'past_rv': past_rv
    }, index=df.index).dropna()

    n = len(data)
    test_start = MIN_TRAIN

    e_bench_all = []
    e_model_all = []

    while test_start + TEST_BLOCK <= n:
        test_end = min(test_start + TEST_BLOCK, n)

        train = data.iloc[:test_start]
        test = data.iloc[test_start:test_end]

        y_train = train['target'].values
        y_test = test['target'].values

        hist_mean = y_train.mean()

        X_train = train[['vix_lag', 'past_rv']].values
        X_test = test[['vix_lag', 'past_rv']].values
        reg = LinearRegression().fit(X_train, y_train)
        preds = reg.predict(X_test)

        e_bench = (y_test - hist_mean) ** 2
        e_model = (y_test - preds) ** 2

        e_bench_all.extend(e_bench.tolist())
        e_model_all.extend(e_model.tolist())

        test_start += TEST_BLOCK

    e_bench_all = np.array(e_bench_all)
    e_model_all = np.array(e_model_all)

    # DM-like test: d = e_bench - e_model
    d = e_bench_all - e_model_all
    d_mean = d.mean()
    d_se = d.std() / np.sqrt(len(d))

    # Use Newey-West HAC SE (simple version with h lags)
    T = len(d)
    d_demeaned = d - d_mean
    gamma_0 = np.mean(d_demeaned ** 2)
    hac_var = gamma_0
    for lag in range(1, min(h, T-1)):
        gamma_lag = np.mean(d_demeaned[lag:] * d_demeaned[:-lag])
        weight = 1 - lag / (h + 1)  # Bartlett kernel
        hac_var += 2 * weight * gamma_lag
    hac_se = np.sqrt(hac_var / T)

    dm_stat = d_mean / hac_se if hac_se > 0 else 0
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    sig = "***" if dm_pval < 0.001 else "**" if dm_pval < 0.01 else "*" if dm_pval < 0.05 else ""
    harvey_flag = " [>3.0!]" if abs(dm_stat) > 3.0 else ""

    print(f"  h={h:3d}d: DM-stat={dm_stat:7.3f}, p={dm_pval:.4f} {sig:3s} "
          f"| MSFE ratio={r['combined']['msfe_ratio']:.4f}{harvey_flag}")


# ─── 10. Summary & Interpretation ───────────────────────────────────────────
print("\n" + "=" * 80)
print("SUMMARY & INTERPRETATION")
print("=" * 80)

peak_h = h_list[oos_comb.index(max(oos_comb))]
peak_r2 = max(oos_comb)
min_h = h_list[oos_comb.index(min(oos_comb))]
min_r2 = min(oos_comb)

print(f"""
  Data: SPY daily, 2005-2024 ({len(df)} trading days)
  Method: OOS expanding window, lagged predictors only

  KEY FINDINGS:
  1. Peak predictability at h={peak_h} days (OOS R²={peak_r2:.4f})
  2. Lowest predictability at h={min_h} days (OOS R²={min_r2:.4f})
  3. Predictability range: {min_r2:.4f} to {peak_r2:.4f}
""")

# Compare with K360 (biased)
print("  COMPARISON WITH K360 (same-day bias):")
print("  K360 reported: daily R²=0.37, weekly R²=0.50, monthly R²=0.24")
r2_1d = f"{oos_comb[0]:.4f}" if len(oos_comb) > 0 else "N/A"
r2_5d = f"{oos_comb[2]:.4f}" if len(oos_comb) > 2 else "N/A"
r2_22d = f"{oos_comb[4]:.4f}" if len(oos_comb) > 4 else "N/A"
print(f"  K365 (lagged): h=1d R²={r2_1d}, h=5d R²={r2_5d}, h=22d R²={r2_22d}")

if oos_comb[0] < 0.37:
    print(f"  → Daily R² dropped from 0.37 to {oos_comb[0]:.4f} after removing same-day bias")
    print(f"    Bias magnitude: {0.37 - oos_comb[0]:.4f} (={100*(0.37 - oos_comb[0])/0.37:.0f}% inflation)")

# Practical recommendation
print("\n  PRACTICAL IMPLICATIONS:")
useful_horizons = [(h, r2) for h, r2 in zip(h_list, oos_comb) if r2 > 0.05]
if useful_horizons:
    print(f"  Horizons with OOS R² > 5%: {[f'h={h}d (R²={r2:.3f})' for h, r2 in useful_horizons]}")
else:
    print("  No horizon achieves OOS R² > 5% with lagged predictors only")

strong_horizons = [(h, r2) for h, r2 in zip(h_list, oos_comb) if r2 > 0.15]
if strong_horizons:
    print(f"  Horizons with OOS R² > 15%: {[f'h={h}d (R²={r2:.3f})' for h, r2 in strong_horizons]}")


# ─── 11. Save Results ───────────────────────────────────────────────────────
output = {
    'experiment': 'K365',
    'title': 'Realized Volatility Term Structure (Lagged Predictors Only)',
    'data': {
        'asset': 'SPY',
        'source': 'yfinance',
        'period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'n_days': len(df)
    },
    'methodology': {
        'predictors': 'VIX_{t-1} and RV_{t-h-1:t-1} (all lagged by 1 day)',
        'oos_method': 'expanding window',
        'min_train': MIN_TRAIN,
        'test_block': TEST_BLOCK,
        'bias_free': True
    },
    'horizons': h_list,
    'results': {str(h): results[h] for h in results},
    'term_structure': {
        'horizons': h_list,
        'oos_r2_vix': oos_vix,
        'oos_r2_rv': oos_rv,
        'oos_r2_combined': oos_comb,
        'peak_horizon': peak_h,
        'peak_r2': peak_r2
    }
}

output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a0d35cff/experiments/k365_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to: {output_path}")

print("\n" + "=" * 80)
print("K365 COMPLETE")
print("=" * 80)
