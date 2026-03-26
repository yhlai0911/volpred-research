"""
K453: Daily Semivariance Cross-Asset Validation

Background:
  K449: RS⁻ (bad vol) significantly beats RV for SPY (DM p=0.007) and QQQ (p=0.003),
        but FAILED for GLD. Need cross-asset validation to determine if this is
        equity-specific or a more general phenomenon.
  K450: VRP + Semivariance combined — no synergy (curse of dimensionality at daily freq)

Hypothesis:
  Negative semivariance (RS⁻) captures leverage/asymmetry effects that improve
  volatility prediction. This should be stronger in assets with pronounced asymmetry
  (negative gamma / leverage effect), measured by GJR gamma.

Literature:
  - Patton & Sheppard (2015) "Good Volatility, Bad Volatility" JFQA
  - Black (1976) leverage effect
  - Engle & Ng (1993) news impact curve

Assets (8):
  SPY (US large cap) — K449 positive
  QQQ (US tech) — K449 positive
  EEM (Emerging markets)
  TLT (Long-term bonds)
  IWM (US small cap)
  XLE (Energy sector)
  BTC-USD (Crypto)
  0050.TW (Taiwan)

Design:
  M1: lagged RV21 → next-day |return| (baseline)
  M2: lagged RS⁻_21 → next-day |return|
  M3: RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21 (HAR-semi, 4 features)
  OOS: 2023-01-01 to 2025-12-31
  DM test + block bootstrap (10000 reps, block size 10)
  GJR gamma estimation for cross-sectional analysis

Data: yfinance, 2005-01-01 to present (2015 for BTC, 0050.TW)
Author: [Proposed: User(K449 follow-up), Executed: Claude]
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
from arch import arch_model

warnings.filterwarnings('ignore')

print("=" * 70)
print("K453: Daily Semivariance Cross-Asset Validation")
print("  8 assets × 3 models × DM test + GJR gamma cross-sectional")
print("=" * 70)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
ASSETS = {
    'SPY': {'name': 'US Large Cap', 'start': '2005-01-01'},
    'QQQ': {'name': 'US Tech', 'start': '2005-01-01'},
    'EEM': {'name': 'Emerging Markets', 'start': '2005-01-01'},
    'TLT': {'name': 'Long-Term Bonds', 'start': '2005-01-01'},
    'IWM': {'name': 'US Small Cap', 'start': '2005-01-01'},
    'XLE': {'name': 'Energy Sector', 'start': '2005-01-01'},
    'BTC-USD': {'name': 'Crypto (Bitcoin)', 'start': '2015-01-01'},
    '0050.TW': {'name': 'Taiwan (0050)', 'start': '2005-01-01'},
}

OOS_START = '2023-01-01'
OOS_END = '2025-12-31'
BOOTSTRAP_REPS = 10000
BLOCK_SIZE = 10
HARVEY_THRESHOLD = 3.0

print("\n[1] Downloading data...")
data = {}
for ticker, info in ASSETS.items():
    try:
        raw = yf.download(ticker, start=info['start'], progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        if len(raw) < 500:
            print(f"  {ticker}: SKIP — only {len(raw)} observations")
            continue
        data[ticker] = raw
        print(f"  {ticker} ({info['name']}): {raw.index[0].date()} to {raw.index[-1].date()} ({len(raw)} obs)")
    except Exception as e:
        print(f"  {ticker}: DOWNLOAD ERROR — {e}")

print(f"\n  Successfully downloaded {len(data)}/{len(ASSETS)} assets")


# ============================================================
# 2. DESCRIPTIVE STATISTICS & DIAGNOSTICS
# ============================================================
print("\n" + "=" * 70)
print("[2] DESCRIPTIVE STATISTICS & DIAGNOSTICS")
print("=" * 70)

diagnostics = {}
for ticker in data:
    ret = data[ticker]['Close'].pct_change().dropna()

    # Basic stats
    mean_ret = ret.mean() * 252 * 100
    std_ret = ret.std() * np.sqrt(252) * 100
    skew = ret.skew()
    kurt = ret.kurtosis()

    # ADF test
    adf_stat, adf_p = adfuller(ret.dropna().values[:5000])[:2]

    # ARCH LM test
    try:
        arch_lm = het_arch(ret.dropna().values[:5000], nlags=5)
        arch_p = arch_lm[1]
    except:
        arch_p = np.nan

    # Negative return fraction
    neg_frac = (ret < 0).mean()

    diagnostics[ticker] = {
        'n_obs': len(ret),
        'ann_mean_pct': round(mean_ret, 2),
        'ann_std_pct': round(std_ret, 2),
        'skewness': round(skew, 4),
        'kurtosis': round(kurt, 4),
        'adf_stat': round(adf_stat, 4),
        'adf_p': round(adf_p, 6),
        'arch_lm_p': round(arch_p, 6) if not np.isnan(arch_p) else None,
        'neg_return_frac': round(neg_frac, 4),
    }

    print(f"\n  {ticker} ({ASSETS[ticker]['name']}):")
    print(f"    N={len(ret)}, Ann.Mean={mean_ret:.1f}%, Ann.Std={std_ret:.1f}%")
    print(f"    Skew={skew:.3f}, Kurt={kurt:.3f}")
    print(f"    ADF stat={adf_stat:.3f} (p={adf_p:.6f}) — {'Stationary' if adf_p < 0.05 else 'NON-STATIONARY'}")
    print(f"    ARCH LM p={arch_p:.6f} — {'ARCH effects present' if arch_p < 0.05 else 'No ARCH effects'}")
    print(f"    Neg return fraction: {neg_frac:.3f}")


# ============================================================
# 3. GJR-GARCH GAMMA ESTIMATION (for cross-sectional analysis)
# ============================================================
print("\n" + "=" * 70)
print("[3] GJR-GARCH GAMMA ESTIMATION")
print("=" * 70)

gjr_gammas = {}
for ticker in data:
    ret = data[ticker]['Close'].pct_change().dropna() * 100  # percent returns
    ret = ret.dropna()

    # Use full sample for gamma estimation
    try:
        gjr = arch_model(ret, vol='GARCH', p=1, o=1, q=1, dist='t', mean='AR', lags=1)
        res = gjr.fit(disp='off', options={'maxiter': 500})

        if res.convergence_flag == 0:
            alpha = res.params.get('alpha[1]', np.nan)
            gamma = res.params.get('gamma[1]', np.nan)
            beta = res.params.get('beta[1]', np.nan)
            persistence = alpha + gamma / 2 + beta

            gjr_gammas[ticker] = {
                'alpha': round(float(alpha), 6),
                'gamma': round(float(gamma), 6),
                'beta': round(float(beta), 6),
                'persistence': round(float(persistence), 6),
                'converged': True,
                'gamma_pval': None,
            }

            # Get p-value for gamma
            try:
                gamma_tstat = res.tvalues.get('gamma[1]', np.nan)
                gamma_pval = res.pvalues.get('gamma[1]', np.nan)
                gjr_gammas[ticker]['gamma_tstat'] = round(float(gamma_tstat), 4)
                gjr_gammas[ticker]['gamma_pval'] = round(float(gamma_pval), 6)
            except:
                pass

            print(f"  {ticker}: alpha={alpha:.4f}, gamma={gamma:.4f}, beta={beta:.4f}, "
                  f"persist={persistence:.4f}")
            if gjr_gammas[ticker].get('gamma_pval') is not None:
                sig = "***" if gjr_gammas[ticker]['gamma_pval'] < 0.001 else \
                      "**" if gjr_gammas[ticker]['gamma_pval'] < 0.01 else \
                      "*" if gjr_gammas[ticker]['gamma_pval'] < 0.05 else "NS"
                print(f"    gamma t={gjr_gammas[ticker].get('gamma_tstat', '?')}, "
                      f"p={gjr_gammas[ticker]['gamma_pval']:.4f} {sig}")
        else:
            gjr_gammas[ticker] = {'converged': False, 'gamma': np.nan}
            print(f"  {ticker}: GJR FAILED TO CONVERGE")
    except Exception as e:
        gjr_gammas[ticker] = {'converged': False, 'gamma': np.nan, 'error': str(e)}
        print(f"  {ticker}: GJR ERROR — {e}")


# ============================================================
# 4. SEMIVARIANCE PREDICTION MODELS (per asset)
# ============================================================
print("\n" + "=" * 70)
print("[4] SEMIVARIANCE PREDICTION — 3 MODELS × 8 ASSETS")
print("=" * 70)


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (squared errors). Negative stat = model 2 better."""
    d = e1 ** 2 - e2 ** 2
    d = d[np.isfinite(d)]
    n = len(d)
    d_mean = np.mean(d)
    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return float(dm_stat), float(p_val)


def block_bootstrap_dm(e1, e2, n_boot=10000, block_size=10):
    """Block bootstrap for DM test p-value."""
    d = (e1 ** 2 - e2 ** 2)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    observed_mean = np.mean(d)

    count_same_sign = 0
    for _ in range(n_boot):
        # Generate block bootstrap indices
        n_blocks = int(np.ceil(n / block_size))
        starts = np.random.randint(0, n - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]
        boot_d = d[indices]
        if np.mean(boot_d) * np.sign(observed_mean) > 0:
            count_same_sign += 1

    # Two-sided p-value
    p_boot = 2 * min(count_same_sign / n_boot, 1 - count_same_sign / n_boot)
    return float(p_boot)


results = {}
for ticker in data:
    print(f"\n--- {ticker} ({ASSETS[ticker]['name']}) ---")

    price = data[ticker]['Close']
    ret = price.pct_change()
    abs_ret = ret.abs()  # Target: next-day |return|

    # === Build features ===
    ret_vals = ret.values.flatten()

    # Semivariance components
    rs_neg = np.where(ret_vals < 0, ret_vals ** 2, 0.0)
    rs_pos = np.where(ret_vals >= 0, ret_vals ** 2, 0.0)

    rs_neg_s = pd.Series(rs_neg, index=price.index)
    rs_pos_s = pd.Series(rs_pos, index=price.index)
    rv_s = pd.Series(ret_vals ** 2, index=price.index)

    # Rolling windows
    rs_neg_5 = rs_neg_s.rolling(5).mean()
    rs_neg_21 = rs_neg_s.rolling(21).mean()
    rs_pos_5 = rs_pos_s.rolling(5).mean()
    rs_pos_21 = rs_pos_s.rolling(21).mean()
    rv_21 = rv_s.rolling(21).mean()

    # Build feature DataFrame (all lagged by 1 day — no look-ahead)
    features = pd.DataFrame({
        'rv_21': rv_21.shift(1),
        'rs_neg_5': rs_neg_5.shift(1),
        'rs_neg_21': rs_neg_21.shift(1),
        'rs_pos_5': rs_pos_5.shift(1),
        'rs_pos_21': rs_pos_21.shift(1),
        'target': abs_ret,
    }, index=price.index).dropna()

    # Split IS/OOS
    is_mask = features.index < OOS_START
    oos_mask = (features.index >= OOS_START) & (features.index <= OOS_END)
    is_data = features[is_mask]
    oos_data = features[oos_mask]

    if len(oos_data) < 100:
        print(f"  SKIP: only {len(oos_data)} OOS observations")
        continue

    print(f"  IS: {len(is_data)} obs, OOS: {len(oos_data)} obs")

    # === Model 1: RV21 baseline ===
    X_is_m1 = sm.add_constant(is_data[['rv_21']])
    y_is = is_data['target']
    m1_fit = sm.OLS(y_is, X_is_m1).fit()

    X_oos_m1 = sm.add_constant(oos_data[['rv_21']])
    y_oos = oos_data['target'].values
    pred_m1 = m1_fit.predict(X_oos_m1).values

    # === Model 2: RS⁻_21 ===
    X_is_m2 = sm.add_constant(is_data[['rs_neg_21']])
    m2_fit = sm.OLS(y_is, X_is_m2).fit()

    X_oos_m2 = sm.add_constant(oos_data[['rs_neg_21']])
    pred_m2 = m2_fit.predict(X_oos_m2).values

    # === Model 3: HAR-semi (RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21) ===
    har_cols = ['rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21']
    X_is_m3 = sm.add_constant(is_data[har_cols])
    m3_fit = sm.OLS(y_is, X_is_m3).fit()

    X_oos_m3 = sm.add_constant(oos_data[har_cols])
    pred_m3 = m3_fit.predict(X_oos_m3).values

    # === Errors ===
    e_m1 = y_oos - pred_m1
    e_m2 = y_oos - pred_m2
    e_m3 = y_oos - pred_m3

    # === R² OOS ===
    ss_total = np.sum((y_oos - np.mean(y_oos)) ** 2)
    r2_m1 = 1 - np.sum(e_m1 ** 2) / ss_total
    r2_m2 = 1 - np.sum(e_m2 ** 2) / ss_total
    r2_m3 = 1 - np.sum(e_m3 ** 2) / ss_total

    # === MAE ===
    mae_m1 = np.mean(np.abs(e_m1))
    mae_m2 = np.mean(np.abs(e_m2))
    mae_m3 = np.mean(np.abs(e_m3))

    # === RMSE ===
    rmse_m1 = np.sqrt(np.mean(e_m1 ** 2))
    rmse_m2 = np.sqrt(np.mean(e_m2 ** 2))
    rmse_m3 = np.sqrt(np.mean(e_m3 ** 2))

    # === DM tests ===
    dm_m2_m1_stat, dm_m2_m1_p = dm_test(e_m1, e_m2)
    dm_m3_m1_stat, dm_m3_m1_p = dm_test(e_m1, e_m3)
    dm_m3_m2_stat, dm_m3_m2_p = dm_test(e_m2, e_m3)

    # === Block bootstrap ===
    boot_m2_m1_p = block_bootstrap_dm(e_m1, e_m2, BOOTSTRAP_REPS, BLOCK_SIZE)
    boot_m3_m1_p = block_bootstrap_dm(e_m1, e_m3, BOOTSTRAP_REPS, BLOCK_SIZE)

    # === IS coefficients (for interpretation) ===
    m2_coef_rs_neg = float(m2_fit.params.iloc[1]) if len(m2_fit.params) > 1 else np.nan
    m3_coefs = {col: round(float(m3_fit.params[col]), 6) for col in har_cols}
    m3_tvals = {col: round(float(m3_fit.tvalues[col]), 4) for col in har_cols}

    # === Significance flags ===
    m2_sig = dm_m2_m1_p < 0.05 if not np.isnan(dm_m2_m1_p) else False
    m3_sig = dm_m3_m1_p < 0.05 if not np.isnan(dm_m3_m1_p) else False
    m2_harvey = abs(dm_m2_m1_stat) > HARVEY_THRESHOLD if not np.isnan(dm_m2_m1_stat) else False
    m3_harvey = abs(dm_m3_m1_stat) > HARVEY_THRESHOLD if not np.isnan(dm_m3_m1_stat) else False

    # === Determine direction of DM stat ===
    # DM = mean(e1² - e2²) / se. Positive stat means e1 (M1) has LARGER errors → M2 is BETTER
    m2_better = dm_m2_m1_stat > 0 if not np.isnan(dm_m2_m1_stat) else False
    m3_better = dm_m3_m1_stat > 0 if not np.isnan(dm_m3_m1_stat) else False

    # Print results
    print(f"\n  Model   R²_OOS    RMSE       MAE")
    print(f"  M1(RV)  {r2_m1:+.4f}   {rmse_m1:.6f}   {mae_m1:.6f}")
    print(f"  M2(RS⁻) {r2_m2:+.4f}   {rmse_m2:.6f}   {mae_m2:.6f}")
    print(f"  M3(HAR) {r2_m3:+.4f}   {rmse_m3:.6f}   {mae_m3:.6f}")

    print(f"\n  DM Tests (negative stat = alt model better):")
    dm2_dir = "RS⁻ BETTER" if m2_better else "RV BETTER"
    dm3_dir = "HAR BETTER" if m3_better else "RV BETTER"
    sig2 = "***" if m2_harvey else ("*" if m2_sig else "NS")
    sig3 = "***" if m3_harvey else ("*" if m3_sig else "NS")
    print(f"  M2 vs M1: DM={dm_m2_m1_stat:+.3f} (p={dm_m2_m1_p:.4f}) boot_p={boot_m2_m1_p:.4f} [{dm2_dir}] {sig2}")
    print(f"  M3 vs M1: DM={dm_m3_m1_stat:+.3f} (p={dm_m3_m1_p:.4f}) boot_p={boot_m3_m1_p:.4f} [{dm3_dir}] {sig3}")

    print(f"\n  HAR-semi IS coefficients:")
    for col in har_cols:
        print(f"    {col}: coef={m3_coefs[col]:.6f}, t={m3_tvals[col]:.3f}")

    results[ticker] = {
        'name': ASSETS[ticker]['name'],
        'n_is': len(is_data),
        'n_oos': len(oos_data),
        'models': {
            'M1_RV21': {
                'R2_oos': round(r2_m1, 6),
                'RMSE': round(rmse_m1, 8),
                'MAE': round(mae_m1, 8),
            },
            'M2_RS_neg21': {
                'R2_oos': round(r2_m2, 6),
                'RMSE': round(rmse_m2, 8),
                'MAE': round(mae_m2, 8),
            },
            'M3_HAR_semi': {
                'R2_oos': round(r2_m3, 6),
                'RMSE': round(rmse_m3, 8),
                'MAE': round(mae_m3, 8),
                'IS_coefs': m3_coefs,
                'IS_tvals': m3_tvals,
            },
        },
        'dm_tests': {
            'M2_vs_M1': {
                'DM_stat': round(dm_m2_m1_stat, 4) if not np.isnan(dm_m2_m1_stat) else None,
                'DM_pval': round(dm_m2_m1_p, 6) if not np.isnan(dm_m2_m1_p) else None,
                'boot_pval': round(boot_m2_m1_p, 6),
                'RS_neg_better': bool(m2_better),
                'significant_5pct': bool(m2_sig),
                'passes_harvey': bool(m2_harvey),
            },
            'M3_vs_M1': {
                'DM_stat': round(dm_m3_m1_stat, 4) if not np.isnan(dm_m3_m1_stat) else None,
                'DM_pval': round(dm_m3_m1_p, 6) if not np.isnan(dm_m3_m1_p) else None,
                'boot_pval': round(boot_m3_m1_p, 6),
                'HAR_semi_better': bool(m3_better),
                'significant_5pct': bool(m3_sig),
                'passes_harvey': bool(m3_harvey),
            },
            'M3_vs_M2': {
                'DM_stat': round(dm_m3_m2_stat, 4) if not np.isnan(dm_m3_m2_stat) else None,
                'DM_pval': round(dm_m3_m2_p, 6) if not np.isnan(dm_m3_m2_p) else None,
            },
        },
        'gjr_gamma': gjr_gammas.get(ticker, {}),
    }


# ============================================================
# 5. CROSS-SECTIONAL ANALYSIS: gamma vs RS⁻ predictive gain
# ============================================================
print("\n" + "=" * 70)
print("[5] CROSS-SECTIONAL ANALYSIS: GJR gamma vs RS⁻ predictive gain")
print("=" * 70)

# Collect valid pairs
cross_data = []
for ticker in results:
    gamma_info = gjr_gammas.get(ticker, {})
    if not gamma_info.get('converged', False):
        continue
    gamma_val = gamma_info.get('gamma', np.nan)
    if np.isnan(gamma_val):
        continue

    # Predictive gain = R²(M2) - R²(M1)  (positive = RS⁻ better)
    r2_m1 = results[ticker]['models']['M1_RV21']['R2_oos']
    r2_m2 = results[ticker]['models']['M2_RS_neg21']['R2_oos']
    r2_m3 = results[ticker]['models']['M3_HAR_semi']['R2_oos']
    r2_gain_m2 = r2_m2 - r2_m1
    r2_gain_m3 = r2_m3 - r2_m1

    # RMSE gain (negative = better)
    rmse_m1 = results[ticker]['models']['M1_RV21']['RMSE']
    rmse_m2 = results[ticker]['models']['M2_RS_neg21']['RMSE']
    rmse_m3 = results[ticker]['models']['M3_HAR_semi']['RMSE']
    rmse_gain_m2 = (rmse_m1 - rmse_m2) / rmse_m1  # positive = RS⁻ has lower RMSE
    rmse_gain_m3 = (rmse_m1 - rmse_m3) / rmse_m1

    cross_data.append({
        'ticker': ticker,
        'gamma': gamma_val,
        'r2_gain_m2': r2_gain_m2,
        'r2_gain_m3': r2_gain_m3,
        'rmse_gain_m2': rmse_gain_m2,
        'rmse_gain_m3': rmse_gain_m3,
        'skewness': diagnostics[ticker]['skewness'],
    })

if len(cross_data) >= 4:
    cross_df = pd.DataFrame(cross_data)

    # Correlation: gamma vs RS⁻ R² gain
    corr_gamma_r2, corr_gamma_r2_p = stats.pearsonr(cross_df['gamma'], cross_df['r2_gain_m2'])
    corr_gamma_rmse, corr_gamma_rmse_p = stats.pearsonr(cross_df['gamma'], cross_df['rmse_gain_m2'])

    # Rank correlation
    spear_gamma_r2, spear_gamma_r2_p = stats.spearmanr(cross_df['gamma'], cross_df['r2_gain_m2'])
    spear_gamma_rmse, spear_gamma_rmse_p = stats.spearmanr(cross_df['gamma'], cross_df['rmse_gain_m2'])

    # Also: skewness vs gain
    corr_skew_r2, corr_skew_r2_p = stats.pearsonr(cross_df['skewness'], cross_df['r2_gain_m2'])
    spear_skew_r2, spear_skew_r2_p = stats.spearmanr(cross_df['skewness'], cross_df['r2_gain_m2'])

    print(f"\n  N = {len(cross_df)} assets with valid GJR gamma")
    print(f"\n  Pearson correlations:")
    print(f"    gamma vs R²_gain(M2): r={corr_gamma_r2:.4f} (p={corr_gamma_r2_p:.4f})")
    print(f"    gamma vs RMSE_gain(M2): r={corr_gamma_rmse:.4f} (p={corr_gamma_rmse_p:.4f})")
    print(f"    skewness vs R²_gain(M2): r={corr_skew_r2:.4f} (p={corr_skew_r2_p:.4f})")
    print(f"\n  Spearman rank correlations:")
    print(f"    gamma vs R²_gain(M2): rho={spear_gamma_r2:.4f} (p={spear_gamma_r2_p:.4f})")
    print(f"    gamma vs RMSE_gain(M2): rho={spear_gamma_rmse:.4f} (p={spear_gamma_rmse_p:.4f})")
    print(f"    skewness vs R²_gain(M2): rho={spear_skew_r2:.4f} (p={spear_skew_r2_p:.4f})")

    print(f"\n  Per-asset gamma and gain:")
    for _, row in cross_df.iterrows():
        print(f"    {row['ticker']:>10}: gamma={row['gamma']:.4f}, skew={row['skewness']:.4f}, "
              f"R²_gain(M2)={row['r2_gain_m2']:+.4f}, RMSE_gain(M2)={row['rmse_gain_m2']:+.4f}")

    cross_section_results = {
        'n_assets': len(cross_df),
        'pearson': {
            'gamma_vs_r2_gain_M2': {'r': round(corr_gamma_r2, 4), 'p': round(corr_gamma_r2_p, 4)},
            'gamma_vs_rmse_gain_M2': {'r': round(corr_gamma_rmse, 4), 'p': round(corr_gamma_rmse_p, 4)},
            'skew_vs_r2_gain_M2': {'r': round(corr_skew_r2, 4), 'p': round(corr_skew_r2_p, 4)},
        },
        'spearman': {
            'gamma_vs_r2_gain_M2': {'rho': round(spear_gamma_r2, 4), 'p': round(spear_gamma_r2_p, 4)},
            'gamma_vs_rmse_gain_M2': {'rho': round(spear_gamma_rmse, 4), 'p': round(spear_gamma_rmse_p, 4)},
            'skew_vs_r2_gain_M2': {'rho': round(spear_skew_r2, 4), 'p': round(spear_skew_r2_p, 4)},
        },
        'per_asset': cross_data,
    }
else:
    print(f"  Only {len(cross_data)} assets with valid gamma — skipping cross-sectional analysis")
    cross_section_results = {'error': f'Too few valid assets ({len(cross_data)})'}


# ============================================================
# 6. SUMMARY VERDICT
# ============================================================
print("\n" + "=" * 70)
print("[6] SUMMARY")
print("=" * 70)

n_m2_sig = sum(1 for t in results if results[t]['dm_tests']['M2_vs_M1']['significant_5pct']
               and results[t]['dm_tests']['M2_vs_M1']['RS_neg_better'])
n_m3_sig = sum(1 for t in results if results[t]['dm_tests']['M3_vs_M1']['significant_5pct']
               and results[t]['dm_tests']['M3_vs_M1']['HAR_semi_better'])
n_m2_harvey = sum(1 for t in results if results[t]['dm_tests']['M2_vs_M1']['passes_harvey']
                  and results[t]['dm_tests']['M2_vs_M1']['RS_neg_better'])
n_m3_harvey = sum(1 for t in results if results[t]['dm_tests']['M3_vs_M1']['passes_harvey']
                  and results[t]['dm_tests']['M3_vs_M1']['HAR_semi_better'])

n_total = len(results)
print(f"\n  Total assets tested: {n_total}")
print(f"\n  M2 (RS⁻) significantly better than M1 (RV): {n_m2_sig}/{n_total} at p<0.05")
print(f"  M3 (HAR-semi) significantly better than M1 (RV): {n_m3_sig}/{n_total} at p<0.05")
print(f"  M2 passes Harvey (|t|>3): {n_m2_harvey}/{n_total}")
print(f"  M3 passes Harvey (|t|>3): {n_m3_harvey}/{n_total}")

# Classify assets
equity_tickers = ['SPY', 'QQQ', 'IWM', 'EEM', 'XLE']
non_equity = ['TLT', 'BTC-USD', '0050.TW']

n_equity_m2_sig = sum(1 for t in equity_tickers if t in results
                      and results[t]['dm_tests']['M2_vs_M1']['significant_5pct']
                      and results[t]['dm_tests']['M2_vs_M1']['RS_neg_better'])
n_equity_total = sum(1 for t in equity_tickers if t in results)

n_noneq_m2_sig = sum(1 for t in non_equity if t in results
                     and results[t]['dm_tests']['M2_vs_M1']['significant_5pct']
                     and results[t]['dm_tests']['M2_vs_M1']['RS_neg_better'])
n_noneq_total = sum(1 for t in non_equity if t in results)

print(f"\n  Equity assets: {n_equity_m2_sig}/{n_equity_total} M2 significant")
print(f"  Non-equity:    {n_noneq_m2_sig}/{n_noneq_total} M2 significant")

# Determine verdict
if n_m2_sig >= 5:
    verdict = "UNIVERSAL"
    verdict_desc = f"RS⁻ semivariance is a UNIVERSAL predictor ({n_m2_sig}/{n_total} significant)"
elif n_equity_m2_sig >= 3 and n_noneq_m2_sig == 0:
    verdict = "EQUITY_SPECIFIC"
    verdict_desc = f"RS⁻ semivariance is EQUITY-SPECIFIC ({n_equity_m2_sig}/{n_equity_total} equity sig, {n_noneq_m2_sig}/{n_noneq_total} non-equity sig)"
elif n_m2_sig >= 3:
    verdict = "PARTIAL"
    verdict_desc = f"RS⁻ semivariance is PARTIALLY effective ({n_m2_sig}/{n_total} significant)"
else:
    verdict = "WEAK"
    verdict_desc = f"RS⁻ semivariance shows WEAK cross-asset validity ({n_m2_sig}/{n_total} significant)"

print(f"\n  ★ VERDICT: {verdict}")
print(f"    {verdict_desc}")

# Print per-asset summary table
print(f"\n  {'Asset':>10} | {'GJR γ':>8} | {'Skew':>7} | {'R²(M1)':>8} | {'R²(M2)':>8} | {'R²(M3)':>8} | {'DM(M2)':>8} | {'p':>7} | {'Sig':>4}")
print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*7}-+-{'-'*4}")
for ticker in results:
    r = results[ticker]
    gamma = gjr_gammas.get(ticker, {}).get('gamma', np.nan)
    skew = diagnostics.get(ticker, {}).get('skewness', np.nan)
    r2_1 = r['models']['M1_RV21']['R2_oos']
    r2_2 = r['models']['M2_RS_neg21']['R2_oos']
    r2_3 = r['models']['M3_HAR_semi']['R2_oos']
    dm_stat = r['dm_tests']['M2_vs_M1']['DM_stat']
    dm_p = r['dm_tests']['M2_vs_M1']['DM_pval']
    sig = "***" if r['dm_tests']['M2_vs_M1']['passes_harvey'] and r['dm_tests']['M2_vs_M1']['RS_neg_better'] else \
          "*" if r['dm_tests']['M2_vs_M1']['significant_5pct'] and r['dm_tests']['M2_vs_M1']['RS_neg_better'] else "NS"
    gamma_str = f"{gamma:.4f}" if not np.isnan(gamma) else "N/A"
    skew_str = f"{skew:.3f}" if not np.isnan(skew) else "N/A"
    dm_str = f"{dm_stat:+.3f}" if dm_stat is not None else "N/A"
    p_str = f"{dm_p:.4f}" if dm_p is not None else "N/A"
    print(f"  {ticker:>10} | {gamma_str:>8} | {skew_str:>7} | {r2_1:+.4f} | {r2_2:+.4f} | {r2_3:+.4f} | {dm_str:>8} | {p_str:>7} | {sig:>4}")


# ============================================================
# 7. SAVE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("[7] SAVING RESULTS")
print("=" * 70)

output = {
    'experiment_id': 'K453',
    'title': 'Daily Semivariance Cross-Asset Validation',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'methodology': {
        'target': 'next-day |return|',
        'models': {
            'M1': 'OLS: lagged RV_21 → |r_t+1|',
            'M2': 'OLS: lagged RS⁻_21 → |r_t+1|',
            'M3': 'OLS: RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21 → |r_t+1| (HAR-semi)',
        },
        'OOS_period': f'{OOS_START} to {OOS_END}',
        'evaluation': 'DM test (MSE), block bootstrap (10000 reps, block=10)',
        'harvey_threshold': HARVEY_THRESHOLD,
    },
    'data_source': 'yfinance',
    'assets': {t: ASSETS[t] for t in data},
    'diagnostics': diagnostics,
    'gjr_gammas': {k: {kk: vv for kk, vv in v.items() if not (isinstance(vv, float) and np.isnan(vv))}
                   for k, v in gjr_gammas.items()},
    'per_asset_results': results,
    'cross_sectional_analysis': cross_section_results,
    'summary': {
        'n_assets': n_total,
        'n_m2_significant_5pct': n_m2_sig,
        'n_m3_significant_5pct': n_m3_sig,
        'n_m2_passes_harvey': n_m2_harvey,
        'n_m3_passes_harvey': n_m3_harvey,
        'n_equity_m2_sig': n_equity_m2_sig,
        'n_equity_total': n_equity_total,
        'n_non_equity_m2_sig': n_noneq_m2_sig,
        'n_non_equity_total': n_noneq_total,
        'verdict': verdict,
        'verdict_description': verdict_desc,
    },
    'references': [
        'Patton & Sheppard (2015) JFQA',
        'K449: SPY RS⁻ DM p=0.007, QQQ p=0.003, GLD FAIL',
        'K450: VRP + Semi combined — no synergy',
        'Black (1976) leverage effect',
        'Engle & Ng (1993) news impact curve',
    ],
    'limitations': [
        'Daily close-to-close data only (no intraday semivariance)',
        'Linear OLS models (nonlinear relationships not captured)',
        'Single OOS window (2023-2025) — could differ in other periods',
        'Small cross-section (N=8) limits statistical power for gamma correlation',
        'BTC and 0050.TW have shorter IS period',
        'yfinance data may have survivorship/adjustment issues',
    ],
}

out_path = 'experiments/k453_semivar_cross_asset_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Saved to {out_path}")

print("\n" + "=" * 70)
print(f"K453 COMPLETE — Verdict: {verdict}")
print(f"  {verdict_desc}")
print("=" * 70)
