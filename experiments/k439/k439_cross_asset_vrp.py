"""
K439: Cross-Asset VRP Predictability Test

Research Question:
  K436 confirmed VRP (VIX - RV21) predicts SPY vol (DM p=0.018 daily, bootstrap p=0.000).
  Is this SPY-specific or a universal phenomenon across asset classes?

Design:
  For each asset (SPY, QQQ, EEM, GLD, TLT):
    1. Download price data + VIX (all assets use VIX as implied vol proxy)
    2. Compute RV21 = 21-day rolling realized vol (annualized %)
    3. VRP = VIX - RV21 (using SPY's VIX for all, since VIX is the only freely available IV index)
    4. Baseline model: lagged RV21 -> next-day |return|
    5. VRP model: lagged RV21 + lagged VRP -> next-day |return|
    6. OOS: 2023-01-01 to present
    7. Evaluation: DM test (HAC) + block bootstrap (10000 reps, block=21)

Hypothesis:
  - VRP significant for >=3/5 assets -> universal phenomenon
  - VRP only significant for SPY -> SPY-specific (VIX is SPY implied vol)
  - VRP for equity but not commodity/bond -> asset-class dependent

Literature:
  - Bollerslev, Tauchen, Zhou (2009) RFS — VRP predicts equity premium
  - Bekaert & Hoerova (2014) JoE — VRP decomposition
  - K436: VRP confirmed for SPY (daily DM p=0.018, bootstrap p=0.000)

Data: yfinance (SPY, QQQ, EEM, GLD, TLT, ^VIX)
OOS: 2023-01-01 to present
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch

warnings.filterwarnings('ignore')

print("=" * 70)
print("K439: Cross-Asset VRP Predictability Test")
print("  Testing VRP (VIX - RV21) across SPY, QQQ, EEM, GLD, TLT")
print("=" * 70)

# ============================================================
# CONFIG
# ============================================================
ASSETS = ['SPY', 'QQQ', 'EEM', 'GLD', 'TLT']
OOS_START = '2023-01-01'
START_DATE = '2005-01-01'
N_BOOT = 10000
BLOCK_SIZE = 21
RIDGE_ALPHA = 0.01  # Small ridge penalty for numerical stability

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
all_data = {}
for ticker in ASSETS + ['^VIX']:
    data = yf.download(ticker, start=START_DATE, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    all_data[ticker] = data
    print(f"  {ticker}: {data.index[0].date()} to {data.index[-1].date()} ({len(data)} obs)")

vix_close = all_data['^VIX']['Close']

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def compute_features(asset_data, vix_series):
    """Compute RV21, VRP, and target for a given asset."""
    ret = asset_data['Close'].pct_change()
    rv_21 = ret.rolling(21).std() * np.sqrt(252) * 100  # annualized %

    df = pd.DataFrame({
        'ret': ret,
        'abs_ret': ret.abs() * 100,
        'vix': vix_series.reindex(asset_data.index),
        'rv_21': rv_21,
    }, index=asset_data.index)

    df['vrp'] = df['vix'] - df['rv_21']
    df['abs_ret_next'] = df['abs_ret'].shift(-1)  # next-day |return| (no overlap)

    # Lag predictors by 1 day to avoid look-ahead
    df['rv_21_lag'] = df['rv_21'].shift(1)
    df['vrp_lag'] = df['vrp'].shift(1)

    return df.dropna()


def dm_test_hac(loss1, loss2, max_lag=None):
    """Diebold-Mariano test with HAC (Newey-West) standard errors."""
    d = loss1 - loss2  # positive = model 2 better
    n = len(d)
    if max_lag is None:
        max_lag = int(np.floor(n ** (1/3)))

    d_mean = d.mean()

    # Newey-West variance estimator
    gamma_0 = np.mean((d - d_mean) ** 2)
    nw_var = gamma_0
    for j in range(1, max_lag + 1):
        w = 1 - j / (max_lag + 1)  # Bartlett kernel
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        nw_var += 2 * w * gamma_j

    se = np.sqrt(nw_var / n)
    if se < 1e-15:
        return {'stat': np.nan, 'p_value': np.nan}

    dm_stat = d_mean / se
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return {
        'stat': float(dm_stat),
        'p_value': float(p_value),
        'mean_loss_diff': float(d_mean),
        'hac_lag': max_lag
    }


def block_bootstrap_dm(loss1, loss2, n_boot=10000, block_size=21):
    """Block bootstrap p-value for DM test."""
    d = (loss1 - loss2).values if hasattr(loss1, 'values') else loss1 - loss2
    n = len(d)
    obs_stat = d.mean()

    # Center the differences for the null
    d_centered = d - d.mean()

    n_blocks = int(np.ceil(n / block_size))
    boot_stats = np.zeros(n_boot)

    rng = np.random.default_rng(42)

    for b in range(n_boot):
        # Sample blocks with replacement
        block_starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        boot_sample = np.concatenate([d_centered[s:s+block_size] for s in block_starts])[:n]
        boot_stats[b] = boot_sample.mean()

    # Two-sided p-value
    p_value = float(np.mean(np.abs(boot_stats) >= abs(obs_stat)))

    return {
        'obs_stat': float(obs_stat),
        'bootstrap_p_value': float(p_value),
        'ci_95_lower': float(np.percentile(boot_stats, 2.5) + obs_stat),
        'ci_95_upper': float(np.percentile(boot_stats, 97.5) + obs_stat),
        'n_boot': n_boot,
        'block_size': block_size
    }


def ridge_predict_oos(X_is, y_is, X_oos, alpha=0.01):
    """Ridge regression OOS predictions."""
    # Add intercept
    X_is_c = sm.add_constant(X_is)
    X_oos_c = sm.add_constant(X_oos)

    # Ridge: (X'X + alpha*I)^-1 X'y
    n_feat = X_is_c.shape[1]
    penalty = np.eye(n_feat) * alpha
    penalty[0, 0] = 0  # Don't penalize intercept

    XtX = X_is_c.T @ X_is_c + penalty
    Xty = X_is_c.T @ y_is
    beta = np.linalg.solve(XtX, Xty)

    return X_oos_c @ beta, beta


def run_is_regression(X, y, var_names):
    """Run IS regression and return coefficient info."""
    X_c = sm.add_constant(X)
    model = sm.OLS(y, X_c).fit(cov_type='HC1')

    result = {
        'r_squared': float(model.rsquared),
        'adj_r_squared': float(model.rsquared_adj),
        'n_obs': int(model.nobs),
    }

    for i, name in enumerate(var_names):
        idx = i + 1  # skip constant
        result[f'{name}_coef'] = float(model.params[idx])
        result[f'{name}_t_stat'] = float(model.tvalues[idx])
        result[f'{name}_p_value'] = float(model.pvalues[idx])

    return result


# ============================================================
# 2. RUN PER-ASSET ANALYSIS
# ============================================================
print("\n[2] Running per-asset VRP analysis...")

results = {
    'experiment_id': 'k439',
    'title': 'Cross-Asset VRP Predictability Test',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, QQQ, EEM, GLD, TLT, ^VIX)',
    'oos_start': OOS_START,
    'n_bootstrap': N_BOOT,
    'block_size': BLOCK_SIZE,
    'literature': [
        'Bollerslev, Tauchen, Zhou (2009) RFS — VRP predicts equity returns',
        'Bekaert & Hoerova (2014) JoE — VRP decomposition',
        'K436: VRP confirmed for SPY (daily DM p=0.018, bootstrap p=0.000)',
    ],
    'design_note': 'All assets use VIX (SPY implied vol) as proxy. For non-SPY assets, '
                   'VRP = VIX - asset_RV21 is a cross-asset fear premium measure, '
                   'not a true asset-specific VRP.',
    'assets': {},
}

asset_summary = []

for asset in ASSETS:
    print(f"\n{'='*60}")
    print(f"  Processing {asset}")
    print(f"{'='*60}")

    # --- Feature construction ---
    df = compute_features(all_data[asset], vix_close)

    # --- Split IS/OOS ---
    is_mask = df.index < OOS_START
    oos_mask = df.index >= OOS_START
    df_is = df[is_mask].copy()
    df_oos = df[oos_mask].copy()

    print(f"  IS: {df_is.index[0].date()} to {df_is.index[-1].date()} ({len(df_is)} obs)")
    print(f"  OOS: {df_oos.index[0].date()} to {df_oos.index[-1].date()} ({len(df_oos)} obs)")

    # --- Descriptive statistics ---
    desc = {}
    for v in ['vix', 'rv_21', 'vrp', 'abs_ret_next']:
        s = df[v]
        desc[v] = {
            'mean': float(s.mean()),
            'std': float(s.std()),
            'skew': float(s.skew()),
            'kurtosis': float(s.kurtosis()),
            'N': int(len(s)),
        }

    # --- ADF test on VRP ---
    adf_result = adfuller(df['vrp'].values, maxlag=21)
    adf_dict = {
        'statistic': float(adf_result[0]),
        'p_value': float(adf_result[1]),
        'stationary': bool(adf_result[1] < 0.05)
    }

    # --- ARCH LM test on returns ---
    try:
        ret_vals = df['ret'].dropna().values
        arch_test = het_arch(ret_vals, nlags=10)
        arch_dict = {
            'lm_stat': float(arch_test[0]),
            'lm_p_value': float(arch_test[1]),
            'arch_present': bool(arch_test[1] < 0.05)
        }
    except Exception:
        arch_dict = {'error': 'could not compute'}

    # --- Correlation: VIX vs asset RV21 ---
    corr_vix_rv = float(df['vix'].corr(df['rv_21']))
    spearman_vix_rv = float(df['vix'].corr(df['rv_21'], method='spearman'))

    print(f"  Corr(VIX, {asset} RV21) = {corr_vix_rv:.3f} (Pearson), {spearman_vix_rv:.3f} (Spearman)")

    # --- IS Regression ---
    y_is = df_is['abs_ret_next'].values
    X_base_is = df_is[['rv_21_lag']].values
    X_vrp_is = df_is[['rv_21_lag', 'vrp_lag']].values

    is_base = run_is_regression(X_base_is, y_is, ['rv21'])
    is_vrp = run_is_regression(X_vrp_is, y_is, ['rv21', 'vrp'])

    print(f"  IS baseline R²: {is_base['r_squared']:.4f}")
    print(f"  IS VRP-augmented R²: {is_vrp['r_squared']:.4f}")
    print(f"  IS VRP t-stat: {is_vrp['vrp_t_stat']:.3f} (p={is_vrp['vrp_p_value']:.4f})")

    # --- OOS Prediction ---
    y_oos = df_oos['abs_ret_next'].values
    X_base_oos = df_oos[['rv_21_lag']].values
    X_vrp_oos = df_oos[['rv_21_lag', 'vrp_lag']].values

    pred_base, _ = ridge_predict_oos(X_base_is, y_is, X_base_oos, alpha=RIDGE_ALPHA)
    pred_vrp, _ = ridge_predict_oos(X_vrp_is, y_is, X_vrp_oos, alpha=RIDGE_ALPHA)

    # --- Loss functions ---
    mse_base = (y_oos - pred_base) ** 2
    mse_vrp = (y_oos - pred_vrp) ** 2

    mse_base_mean = float(np.mean(mse_base))
    mse_vrp_mean = float(np.mean(mse_vrp))
    mse_improvement = float((mse_base_mean - mse_vrp_mean) / mse_base_mean * 100)

    corr_base = float(np.corrcoef(y_oos, pred_base)[0, 1])
    corr_vrp = float(np.corrcoef(y_oos, pred_vrp)[0, 1])

    print(f"  OOS MSE baseline: {mse_base_mean:.4f}")
    print(f"  OOS MSE VRP-aug:  {mse_vrp_mean:.4f} ({mse_improvement:+.1f}%)")
    print(f"  OOS Corr baseline: {corr_base:.4f}")
    print(f"  OOS Corr VRP-aug:  {corr_vrp:.4f}")

    # --- DM Test (HAC) ---
    dm_result = dm_test_hac(mse_base, mse_vrp)
    print(f"  DM test (HAC): stat={dm_result['stat']:.3f}, p={dm_result['p_value']:.4f}")

    # --- Block Bootstrap ---
    boot_result = block_bootstrap_dm(mse_base, mse_vrp, n_boot=N_BOOT, block_size=BLOCK_SIZE)
    print(f"  Bootstrap p-value: {boot_result['bootstrap_p_value']:.4f}")

    # --- Encompassing Test ---
    # Test: y = lambda*f_base + (1-lambda)*f_vrp + noise
    # Equivalent to regressing y - f_base on f_vrp - f_base
    diff_pred = pred_vrp - pred_base
    diff_actual = y_oos - pred_base
    if np.std(diff_pred) > 1e-10:
        X_enc = sm.add_constant(diff_pred)
        enc_model = sm.OLS(diff_actual, X_enc).fit(cov_type='HC1')
        enc_test = {
            'lambda_vrp': float(enc_model.params[1]),
            't_stat': float(enc_model.tvalues[1]),
            'p_value': float(enc_model.pvalues[1]),
            'significant_5pct': bool(enc_model.pvalues[1] < 0.05),
        }
    else:
        enc_test = {'lambda_vrp': 0.0, 't_stat': 0.0, 'p_value': 1.0, 'significant_5pct': False}

    print(f"  Encompassing test: t={enc_test['t_stat']:.3f}, p={enc_test['p_value']:.4f}")

    # --- Verdict for this asset ---
    sig_dm = dm_result['p_value'] < 0.10 if not np.isnan(dm_result['p_value']) else False
    sig_boot = boot_result['bootstrap_p_value'] < 0.10
    sig_enc = enc_test['p_value'] < 0.10

    n_sig = sum([sig_dm, sig_boot, sig_enc])
    if n_sig >= 2:
        verdict = 'SIGNIFICANT (>=2/3 tests pass)'
    elif n_sig == 1:
        verdict = 'BORDERLINE (1/3 tests pass)'
    else:
        verdict = 'NOT SIGNIFICANT (0/3 tests pass)'

    print(f"  VERDICT: {verdict}")

    asset_result = {
        'n_is': len(df_is),
        'n_oos': len(df_oos),
        'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'descriptive_statistics': desc,
        'adf_test_vrp': adf_dict,
        'arch_lm_test': arch_dict,
        'corr_vix_rv21': corr_vix_rv,
        'spearman_vix_rv21': spearman_vix_rv,
        'is_regression_baseline': is_base,
        'is_regression_vrp_augmented': is_vrp,
        'oos_performance': {
            'mse_baseline': mse_base_mean,
            'mse_vrp_augmented': mse_vrp_mean,
            'mse_improvement_pct': mse_improvement,
            'corr_baseline': corr_base,
            'corr_vrp_augmented': corr_vrp,
        },
        'dm_test_hac': dm_result,
        'block_bootstrap': boot_result,
        'encompassing_test': enc_test,
        'verdict': verdict,
        'sig_dm_10pct': sig_dm,
        'sig_bootstrap_10pct': sig_boot,
        'sig_encompassing_10pct': sig_enc,
    }

    results['assets'][asset] = asset_result

    asset_summary.append({
        'asset': asset,
        'corr_vix_rv': corr_vix_rv,
        'is_vrp_t': is_vrp['vrp_t_stat'],
        'oos_mse_impr': mse_improvement,
        'dm_p': dm_result['p_value'],
        'boot_p': boot_result['bootstrap_p_value'],
        'enc_p': enc_test['p_value'],
        'verdict': verdict,
    })


# ============================================================
# 3. CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("  CROSS-ASSET SUMMARY")
print("=" * 70)

print(f"\n{'Asset':<8} {'Corr(VIX,RV)':<14} {'IS VRP t':<10} {'OOS MSE%':<10} {'DM p':<8} {'Boot p':<8} {'Enc p':<8} {'Verdict'}")
print("-" * 90)

n_significant = 0
n_equity_sig = 0
n_equity_total = 0

for s in asset_summary:
    asset_class = 'equity' if s['asset'] in ['SPY', 'QQQ', 'EEM'] else 'other'
    if asset_class == 'equity':
        n_equity_total += 1

    is_sig = s['verdict'].startswith('SIGNIFICANT')
    if is_sig:
        n_significant += 1
        if asset_class == 'equity':
            n_equity_sig += 1

    print(f"{s['asset']:<8} {s['corr_vix_rv']:<14.3f} {s['is_vrp_t']:<10.3f} {s['oos_mse_impr']:<+10.1f} "
          f"{s['dm_p']:<8.4f} {s['boot_p']:<8.4f} {s['enc_p']:<8.4f} "
          f"{'***' if is_sig else '   '}")

# --- Overall conclusion ---
print(f"\n  Assets with significant VRP: {n_significant}/{len(ASSETS)}")
print(f"  Equity assets with significant VRP: {n_equity_sig}/{n_equity_total}")

if n_significant >= 3:
    overall = "UNIVERSAL: VRP has broad cross-asset predictive power (>=3/5 assets significant)"
elif n_significant == 1 and any(s['asset'] == 'SPY' and 'SIGNIFICANT' in s['verdict'] for s in asset_summary):
    overall = "SPY-SPECIFIC: VRP only predicts SPY vol (VIX is SPY implied vol, tautological)"
elif n_equity_sig >= 2 and n_significant == n_equity_sig:
    overall = "EQUITY-SPECIFIC: VRP predicts equity vol but not commodity/bond"
else:
    overall = f"MIXED: {n_significant}/{len(ASSETS)} significant, pattern unclear"

print(f"\n  OVERALL CONCLUSION: {overall}")

# --- Harvey (2016) check ---
print("\n  Harvey (2016) t>3.0 threshold check:")
for s in asset_summary:
    passes = abs(s['is_vrp_t']) > 3.0
    print(f"    {s['asset']}: IS VRP t={s['is_vrp_t']:.3f} → {'PASSES' if passes else 'FAILS'}")

results['cross_asset_summary'] = {
    'n_significant': n_significant,
    'n_total': len(ASSETS),
    'n_equity_significant': n_equity_sig,
    'n_equity_total': n_equity_total,
    'overall_conclusion': overall,
    'asset_table': asset_summary,
    'harvey_threshold_check': {
        asset: {
            'is_vrp_t': s['is_vrp_t'],
            'passes_t3': abs(s['is_vrp_t']) > 3.0
        }
        for s, asset in zip(asset_summary, ASSETS)
    },
}

# --- Conclusions ---
conclusions = [
    f"Cross-asset VRP test: {n_significant}/{len(ASSETS)} assets show significant VRP predictability",
    f"Equity assets: {n_equity_sig}/{n_equity_total} significant",
    overall,
]

for s in asset_summary:
    conclusions.append(
        f"  {s['asset']}: DM p={s['dm_p']:.4f}, Bootstrap p={s['boot_p']:.4f}, "
        f"MSE improvement {s['oos_mse_impr']:+.1f}%, "
        f"Corr(VIX,RV)={s['corr_vix_rv']:.3f}"
    )

conclusions.append("\nKey insight: VIX is SPY-specific implied vol. For non-SPY assets, "
                   "VRP = VIX - asset_RV21 measures CROSS-ASSET fear premium, not asset-specific VRP.")
conclusions.append("High Corr(VIX,RV) indicates the asset moves with SPY → VRP proxy is more valid.")
conclusions.append("Low Corr(VIX,RV) indicates the asset has its own dynamics → VIX-based VRP is a poor proxy.")

results['conclusions'] = conclusions

# --- Limitations ---
results['limitations'] = [
    "All assets use VIX (SPY implied vol) as proxy — not true asset-specific VRP",
    "Ideal: use GVZ for GLD, MOVE for TLT, but not freely available via yfinance",
    "OOS period (2023-2025) is relatively calm, limiting crisis-period inference",
    "Daily |return| is noisy — VRP is a slow-moving predictor, better at monthly/quarterly horizon",
    "Ridge regularization (alpha=0.01) — negligible impact but noted for reproducibility",
    "VRP for non-equity assets is really a 'cross-asset fear spillover' measure, not VRP per se",
]

results['prior_knowledge'] = [
    "K436: VRP confirmed for SPY (daily DM p=0.018, bootstrap p=0.000)",
    "K430: VRP IS t=4.38 passes Harvey threshold",
    "VRP = VIX - RV21 is positive ~86% of the time (mean +3.5%)",
    "VRP is NOT a directional return predictor, but IS a vol predictor",
]

# ============================================================
# 4. SAVE RESULTS
# ============================================================
import os
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'k439_cross_asset_vrp_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n[4] Results saved to {output_path}")

print("\n" + "=" * 70)
print("K439 COMPLETE")
print("=" * 70)
