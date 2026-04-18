"""
K483: Commodity Volatility — Oil and Gold Vol Forecasting
=========================================================

Background:
  58 experiments all on equity (SPY/QQQ/EEM), bond (TLT), crypto (BTC), Taiwan.
  NEVER done commodity vol forecasting. Commodities have different dynamics:
  - Supply shocks (hurricanes, OPEC decisions)
  - Contango/backwardation structure
  - Seasonality
  - Different leverage effect (potentially inverted — price up → vol up for oil)

  Prior findings on GLD:
  - K132: GLD QLIKE capture rate only 19.4% (vs SPY 62.7%) — much harder to predict
  - K135: GLD inventory-conditioned vol null OOS — vol is exogenous
  - K453: GLD semivariance gamma≈0, RS⁻ FAILS for GLD
  - Paper 1: Inverted leverage effect in gold (positive gamma)

Research Questions:
  1. Does GJR-GARCH QLIKE ceiling hold for commodities?
  2. Is commodity leverage effect positive or negative? (oil up → vol up?)
  3. Does HAR log-range work for commodities?
  4. Does semivariance work for commodities? (K453: GLD gamma≈0, RS⁻ fails)
  5. What is the MCS superior set for commodities?

Models (7):
  1. GARCH(1,1) — symmetric baseline
  2. GJR-GARCH(1,1) — asymmetric
  3. EGARCH(1,1) — log-scale asymmetric
  4. HAR log-range — Corsi (2009) with range proxy
  5. Semivariance RS⁻ — Patton & Sheppard (2015)
  6. EWMA(0.94) — RiskMetrics
  7. Equal-weight ensemble (GJR + HAR)

Assets (2):
  - GLD (Gold ETF) — safe haven, inverted leverage known
  - USO (Oil ETF) — supply shock driven, contango drag

OOS: 2023-01-01 to 2025-12-31
IS Window: 2000 (rolling)

Evaluation:
  - QLIKE with r² proxy
  - DM test pairwise (Newey-West HAC)
  - MCS (Hansen, Lunde, Nason 2011) if available
  - GJR gamma sign and significance
  - HAR vs GJR comparison

References:
  - Corsi (2009) "A Simple Approximate Long-Memory Model of Realized Volatility" J Fin Econometrics
  - Glosten, Jagannathan, Runkle (1993) "On the Relation between the Expected Value..." JF
  - Nelson (1991) "Conditional Heteroscedasticity in Asset Returns" Econometrica — EGARCH
  - Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies" J Econometrics
  - Patton & Sheppard (2015) "Good Volatility, Bad Volatility" JFQA
  - Hansen, Lunde, Nason (2011) "The Model Confidence Set" Econometrica
  - Black (1976) "Studies of Stock Price Volatility Changes" — leverage effect
  - K132, K135, K453 — prior GLD findings

Data: yfinance, 2005-01-01 to present
Author: [Proposed: User(commodity direction), Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
from arch.bootstrap import MCS
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch

warnings.filterwarnings('ignore')

t_start = time.time()

print("=" * 70)
print("K483: Commodity Volatility — Oil and Gold Vol Forecasting")
print("  2 assets × 7 models × QLIKE + DM test + MCS")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
ASSETS = {
    'GLD': {'name': 'Gold ETF', 'start': '2005-01-01'},
    'USO': {'name': 'Oil ETF (WTI proxy)', 'start': '2006-05-01'},  # USO inception Apr 2006
}
IS_WINDOW = 2000
OOS_START = '2023-01-01'
OOS_END = '2025-12-31'
EWMA_LAMBDA = 0.94
ROLLING_WINDOW = 21
HARVEY_THRESHOLD = 3.0

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
all_data = {}
for ticker, info in ASSETS.items():
    print(f"  {ticker} ({info['name']})...", end=' ')
    df = yf.download(ticker, start=info['start'], end='2026-03-26', auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()

    # Compute returns and proxies
    df['log_return'] = np.log(df['Close'] / df['Close'].shift(1))
    df['r_squared'] = df['log_return'] ** 2
    df['log_range'] = np.log(df['High'] / df['Low'])
    df['parkinson_var'] = df['log_range'] ** 2 / (4 * np.log(2))
    df['abs_return'] = np.abs(df['log_return'])

    # Semivariance components
    df['ret_neg'] = np.where(df['log_return'] < 0, df['log_return'] ** 2, 0)
    df['ret_pos'] = np.where(df['log_return'] > 0, df['log_return'] ** 2, 0)

    # Rolling realized measures
    for w in [5, 21]:
        df[f'RV_{w}'] = df['r_squared'].rolling(w).sum()
        df[f'RS_neg_{w}'] = df['ret_neg'].rolling(w).sum()
        df[f'RS_pos_{w}'] = df['ret_pos'].rolling(w).sum()
        df[f'log_range_{w}'] = df['log_range'].rolling(w).mean()

    df = df.dropna().copy()
    all_data[ticker] = df
    print(f"N={len(df)}, {df.index[0].date()} to {df.index[-1].date()}")

# ============================================================
# 2. DIAGNOSTICS
# ============================================================
print("\n[2] Data Diagnostics")
print("-" * 70)
diagnostics = {}
for ticker, df in all_data.items():
    oos_mask = df.index >= OOS_START
    is_data = df[~oos_mask]
    oos_data = df[oos_mask]

    ret = df['log_return'] * 100  # pct
    diag = {
        'N_total': len(df),
        'N_IS': len(is_data),
        'N_OOS': len(oos_data),
        'mean_pct': float(ret.mean()),
        'std_pct': float(ret.std()),
        'skewness': float(ret.skew()),
        'kurtosis': float(ret.kurtosis()),
    }

    # ADF test
    adf_stat, adf_p, *_ = adfuller(df['log_return'].dropna(), maxlag=10)
    diag['adf_stat'] = float(adf_stat)
    diag['adf_p'] = float(adf_p)
    diag['stationary'] = adf_p < 0.05

    # ARCH LM test
    try:
        arch_lm_stat, arch_lm_p, *_ = het_arch(df['log_return'].dropna(), nlags=5)
        diag['arch_lm_stat'] = float(arch_lm_stat)
        diag['arch_lm_p'] = float(arch_lm_p)
        diag['arch_effects'] = arch_lm_p < 0.05
    except:
        diag['arch_lm_stat'] = None
        diag['arch_lm_p'] = None
        diag['arch_effects'] = None

    diagnostics[ticker] = diag

    print(f"\n  {ticker} ({ASSETS[ticker]['name']}):")
    print(f"    N_total={diag['N_total']}, N_IS={diag['N_IS']}, N_OOS={diag['N_OOS']}")
    print(f"    Mean={diag['mean_pct']:.4f}%, Std={diag['std_pct']:.4f}%")
    print(f"    Skew={diag['skewness']:.3f}, Kurt={diag['kurtosis']:.2f}")
    print(f"    ADF: stat={diag['adf_stat']:.3f}, p={diag['adf_p']:.6f} → {'Stationary' if diag['stationary'] else 'NON-STATIONARY'}")
    if diag['arch_lm_p'] is not None:
        print(f"    ARCH LM(5): stat={diag['arch_lm_stat']:.2f}, p={diag['arch_lm_p']:.6f} → {'ARCH effects' if diag['arch_effects'] else 'No ARCH'}")


# ============================================================
# 3. HELPER FUNCTIONS
# ============================================================
def compute_qlike(forecast, proxy):
    """QLIKE loss: proxy/forecast - log(proxy/forecast) - 1"""
    ratio = proxy / forecast
    ratio = np.clip(ratio, 1e-10, 1e10)
    return ratio - np.log(ratio) - 1


def dm_test_hac(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC standard errors."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    # Newey-West bandwidth
    bandwidth = int(np.ceil(n ** (1/3)))

    # HAC variance
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, bandwidth + 1):
        weight = 1 - k / (bandwidth + 1)
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        hac_var += 2 * weight * gamma_k

    se = np.sqrt(hac_var / n)
    if se < 1e-15:
        return 0.0, 1.0
    dm_stat = d_bar / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)


def fit_garch_rolling(returns_pct, vol_type='GARCH', p=1, o=0, q=1, dist='t'):
    """Rolling GARCH estimation. Returns 1-step ahead variance forecasts."""
    n = len(returns_pct)
    forecasts = np.full(n, np.nan)
    gamma_values = []
    convergence_count = 0

    for i in range(IS_WINDOW, n):
        window = returns_pct.iloc[i - IS_WINDOW:i]
        try:
            if vol_type == 'EGARCH':
                am = arch_model(window, vol='EGARCH', p=1, o=1, q=1, dist=dist, mean='Constant')
            elif o > 0:
                am = arch_model(window, vol='GARCH', p=p, o=o, q=q, dist=dist, mean='Constant')
            else:
                am = arch_model(window, vol='GARCH', p=p, q=q, dist=dist, mean='Constant')

            res = am.fit(disp='off', show_warning=False)
            if res.convergence_flag == 0:
                convergence_count += 1
                fc = res.forecast(horizon=1)
                forecasts[i] = fc.variance.values[-1, 0] / 10000  # pct^2 to decimal^2

                # Extract gamma for GJR
                if o > 0 and 'gamma[1]' in res.params:
                    gamma_values.append({
                        'gamma': float(res.params['gamma[1]']),
                        'gamma_tstat': float(res.tvalues.get('gamma[1]', 0)),
                    })
                # Extract gamma for EGARCH
                if vol_type == 'EGARCH' and 'gamma[1]' in res.params:
                    gamma_values.append({
                        'gamma': float(res.params['gamma[1]']),
                        'gamma_tstat': float(res.tvalues.get('gamma[1]', 0)),
                    })
        except:
            pass

    total_windows = n - IS_WINDOW
    conv_rate = convergence_count / total_windows if total_windows > 0 else 0
    return forecasts, gamma_values, conv_rate


def fit_ewma(returns, lam=0.94):
    """EWMA variance: sigma2_t = lambda*sigma2_{t-1} + (1-lambda)*r_{t-1}^2"""
    n = len(returns)
    var = np.full(n, np.nan)
    var[0] = returns[:21].var()  # seed with first 21 days
    for i in range(1, n):
        var[i] = lam * var[i - 1] + (1 - lam) * returns.iloc[i - 1] ** 2
    return var


def fit_har_log_range(df, is_window=IS_WINDOW):
    """HAR model: log_range_t = a + b1*LR_1 + b5*LR_5 + b21*LR_21 + eps"""
    n = len(df)
    forecasts = np.full(n, np.nan)

    for i in range(is_window, n):
        window = df.iloc[i - is_window:i]
        y = window['log_range'].iloc[1:]
        X = pd.DataFrame({
            'LR_1': window['log_range'].shift(1).iloc[1:],
            'LR_5': window['log_range_5'].shift(1).iloc[1:],
            'LR_21': window['log_range_21'].shift(1).iloc[1:],
        })
        X = sm.add_constant(X)
        valid = ~(X.isna().any(axis=1) | y.isna())
        if valid.sum() < 100:
            continue

        try:
            model = sm.OLS(y[valid], X[valid]).fit()
            # 1-step forecast
            x_new = np.array([1,
                              df['log_range'].iloc[i - 1],
                              df['log_range_5'].iloc[i - 1],
                              df['log_range_21'].iloc[i - 1]])
            pred_log_range = model.predict(x_new.reshape(1, -1))[0]
            # Convert log-range to variance: Var ≈ LR² / (4*ln2)
            forecasts[i] = pred_log_range ** 2 / (4 * np.log(2))
        except:
            pass

    return forecasts


def fit_semivar(df, is_window=IS_WINDOW):
    """Semivariance RS⁻ model: |ret|_t = a + b*RS⁻_21 + eps"""
    n = len(df)
    forecasts = np.full(n, np.nan)

    for i in range(is_window, n):
        window = df.iloc[i - is_window:i]
        y = window['r_squared'].iloc[1:]
        X = pd.DataFrame({
            'RS_neg_5': window['RS_neg_5'].shift(1).iloc[1:],
            'RS_neg_21': window['RS_neg_21'].shift(1).iloc[1:],
            'RS_pos_5': window['RS_pos_5'].shift(1).iloc[1:],
            'RS_pos_21': window['RS_pos_21'].shift(1).iloc[1:],
        })
        X = sm.add_constant(X)
        valid = ~(X.isna().any(axis=1) | y.isna())
        if valid.sum() < 100:
            continue

        try:
            model = sm.OLS(y[valid], X[valid]).fit()
            x_new = np.array([1,
                              df['RS_neg_5'].iloc[i - 1],
                              df['RS_neg_21'].iloc[i - 1],
                              df['RS_pos_5'].iloc[i - 1],
                              df['RS_pos_21'].iloc[i - 1]])
            pred = model.predict(x_new.reshape(1, -1))[0]
            forecasts[i] = max(pred, 1e-10)  # floor
        except:
            pass

    return forecasts


# ============================================================
# 4. MODEL ESTIMATION (Rolling OOS)
# ============================================================
print("\n[3] Rolling OOS Estimation (2 assets × 7 models)")
print("-" * 70)

results = {}

for ticker, df in all_data.items():
    print(f"\n  === {ticker} ({ASSETS[ticker]['name']}) ===")

    returns_pct = df['log_return'] * 100  # for arch package
    returns_dec = df['log_return']  # decimal
    oos_mask = df.index >= OOS_START

    asset_results = {
        'models': {},
        'diagnostics': diagnostics[ticker],
    }

    # --- Model 1: GARCH(1,1) ---
    print(f"    GARCH(1,1)...", end=' ')
    t0 = time.time()
    garch_fc, _, garch_conv = fit_garch_rolling(returns_pct, vol_type='GARCH', p=1, o=0, q=1)
    df['fc_garch'] = garch_fc
    print(f"done ({time.time()-t0:.1f}s, conv={garch_conv:.1%})")

    # --- Model 2: GJR-GARCH(1,1) ---
    print(f"    GJR-GARCH(1,1)...", end=' ')
    t0 = time.time()
    gjr_fc, gjr_gammas, gjr_conv = fit_garch_rolling(returns_pct, vol_type='GARCH', p=1, o=1, q=1)
    df['fc_gjr'] = gjr_fc
    print(f"done ({time.time()-t0:.1f}s, conv={gjr_conv:.1%})")

    # --- Model 3: EGARCH(1,1) ---
    print(f"    EGARCH(1,1)...", end=' ')
    t0 = time.time()
    egarch_fc, egarch_gammas, egarch_conv = fit_garch_rolling(returns_pct, vol_type='EGARCH', p=1, o=1, q=1)
    df['fc_egarch'] = egarch_fc
    print(f"done ({time.time()-t0:.1f}s, conv={egarch_conv:.1%})")

    # --- Model 4: HAR log-range ---
    print(f"    HAR log-range...", end=' ')
    t0 = time.time()
    har_fc = fit_har_log_range(df)
    df['fc_har'] = har_fc
    print(f"done ({time.time()-t0:.1f}s)")

    # --- Model 5: Semivariance RS⁻ ---
    print(f"    Semivariance RS⁻...", end=' ')
    t0 = time.time()
    semi_fc = fit_semivar(df)
    df['fc_semi'] = semi_fc
    print(f"done ({time.time()-t0:.1f}s)")

    # --- Model 6: EWMA(0.94) ---
    print(f"    EWMA(0.94)...", end=' ')
    t0 = time.time()
    ewma_var = fit_ewma(returns_dec, lam=EWMA_LAMBDA)
    df['fc_ewma'] = ewma_var
    print(f"done ({time.time()-t0:.1f}s)")

    # --- Model 7: Ensemble (GJR + HAR equal weight) ---
    df['fc_ensemble'] = (df['fc_gjr'] + df['fc_har']) / 2
    print(f"    Ensemble (GJR+HAR)... done")

    # ============================================================
    # 5. OOS EVALUATION
    # ============================================================
    print(f"\n    --- OOS Evaluation ({OOS_START} to {OOS_END}) ---")

    oos = df[oos_mask].copy()
    proxy = oos['r_squared'].values

    model_names = ['GARCH', 'GJR', 'EGARCH', 'HAR_LR', 'Semivar', 'EWMA', 'Ensemble']
    fc_cols = ['fc_garch', 'fc_gjr', 'fc_egarch', 'fc_har', 'fc_semi', 'fc_ewma', 'fc_ensemble']

    qlike_losses = {}
    mean_qlikes = {}

    for mname, col in zip(model_names, fc_cols):
        fc = oos[col].values
        valid = ~(np.isnan(fc) | np.isnan(proxy) | (fc <= 0) | (proxy <= 0))
        if valid.sum() < 50:
            print(f"      {mname}: insufficient valid forecasts ({valid.sum()})")
            asset_results['models'][mname] = {'status': 'insufficient_data', 'valid_N': int(valid.sum())}
            continue

        ql = compute_qlike(fc[valid], proxy[valid])
        qlike_losses[mname] = ql
        mean_ql = float(np.mean(ql))
        median_ql = float(np.median(ql))
        mean_qlikes[mname] = mean_ql

        print(f"      {mname}: QLIKE={mean_ql:.6f} (median={median_ql:.6f}, N={valid.sum()})")

        asset_results['models'][mname] = {
            'qlike_mean': mean_ql,
            'qlike_median': median_ql,
            'valid_N': int(valid.sum()),
        }

    # Best model
    if mean_qlikes:
        best = min(mean_qlikes, key=mean_qlikes.get)
        print(f"\n      ★ Best model: {best} (QLIKE={mean_qlikes[best]:.6f})")
        asset_results['best_model'] = best
        asset_results['best_qlike'] = mean_qlikes[best]

    # ============================================================
    # 6. PAIRWISE DM TESTS
    # ============================================================
    print(f"\n    --- Pairwise DM Tests ---")
    dm_results = {}

    # Compare all pairs
    model_list = list(qlike_losses.keys())
    for i in range(len(model_list)):
        for j in range(i + 1, len(model_list)):
            m1, m2 = model_list[i], model_list[j]
            # Align lengths
            n_min = min(len(qlike_losses[m1]), len(qlike_losses[m2]))
            l1 = qlike_losses[m1][:n_min]
            l2 = qlike_losses[m2][:n_min]

            dm_stat, dm_p = dm_test_hac(l1, l2)
            key = f"{m1}_vs_{m2}"
            dm_results[key] = {
                'dm_stat': round(dm_stat, 3),
                'p_value': round(dm_p, 4),
                'winner': m1 if dm_stat < 0 else m2,
                'significant': dm_p < 0.05,
                'harvey_significant': abs(dm_stat) > HARVEY_THRESHOLD,
            }

            winner = m1 if dm_stat < 0 else m2
            sig = "***" if abs(dm_stat) > HARVEY_THRESHOLD else ("**" if dm_p < 0.01 else ("*" if dm_p < 0.05 else ""))
            if dm_p < 0.10:
                print(f"      {m1} vs {m2}: DM={dm_stat:+.3f}, p={dm_p:.4f} → {winner} wins {sig}")

    asset_results['dm_tests'] = dm_results

    # ============================================================
    # 7. GJR GAMMA ANALYSIS
    # ============================================================
    print(f"\n    --- GJR Gamma (Leverage Effect) Analysis ---")
    if gjr_gammas:
        gammas = [g['gamma'] for g in gjr_gammas]
        tstats = [g['gamma_tstat'] for g in gjr_gammas]

        mean_gamma = float(np.mean(gammas))
        median_gamma = float(np.median(gammas))
        std_gamma = float(np.std(gammas))
        pct_positive = float(np.mean(np.array(gammas) > 0))
        pct_significant = float(np.mean(np.abs(np.array(tstats)) > 1.96))
        mean_tstat = float(np.mean(tstats))

        gamma_info = {
            'mean_gamma': round(mean_gamma, 6),
            'median_gamma': round(median_gamma, 6),
            'std_gamma': round(std_gamma, 6),
            'pct_positive': round(pct_positive, 4),
            'pct_significant': round(pct_significant, 4),
            'mean_tstat': round(mean_tstat, 3),
            'n_estimates': len(gammas),
        }

        leverage_type = "INVERTED (positive)" if mean_gamma > 0 else "STANDARD (negative)"
        print(f"      Mean gamma: {mean_gamma:.6f} ({leverage_type})")
        print(f"      Median gamma: {median_gamma:.6f}")
        print(f"      % positive: {pct_positive:.1%}")
        print(f"      % significant (|t|>1.96): {pct_significant:.1%}")
        print(f"      Mean t-stat: {mean_tstat:.3f}")

        asset_results['gjr_gamma'] = gamma_info

    # EGARCH gamma analysis
    if egarch_gammas:
        eg = [g['gamma'] for g in egarch_gammas]
        et = [g['gamma_tstat'] for g in egarch_gammas]
        egarch_info = {
            'mean_gamma': round(float(np.mean(eg)), 6),
            'pct_negative': round(float(np.mean(np.array(eg) < 0)), 4),
            'mean_tstat': round(float(np.mean(et)), 3),
        }
        print(f"\n      EGARCH gamma: mean={np.mean(eg):.6f}, pct_negative={np.mean(np.array(eg)<0):.1%}")
        asset_results['egarch_gamma'] = egarch_info

    # ============================================================
    # 8. MCS (Model Confidence Set)
    # ============================================================
    print(f"\n    --- Model Confidence Set (Hansen et al. 2011) ---")
    try:
        # Build loss matrix for MCS
        common_mask = None
        for mname in model_list:
            fc = oos[fc_cols[model_names.index(mname)]].values
            m = ~(np.isnan(fc) | np.isnan(proxy) | (fc <= 0) | (proxy <= 0))
            common_mask = m if common_mask is None else (common_mask & m)

        if common_mask is not None and common_mask.sum() > 100:
            loss_df = pd.DataFrame()
            for mname in model_list:
                fc = oos[fc_cols[model_names.index(mname)]].values
                ql = compute_qlike(fc[common_mask], proxy[common_mask])
                loss_df[mname] = ql

            mcs = MCS(loss_df, size=0.10, reps=5000, block_size=10, method='max')
            mcs.compute()

            # Get p-values
            pvals = mcs.pvalues
            included = pvals[pvals['Pvalue'] >= 0.10].index.tolist()
            excluded = pvals[pvals['Pvalue'] < 0.10].index.tolist()

            print(f"      MCS Superior Set (α=0.10): {included}")
            print(f"      Excluded: {excluded}")

            mcs_detail = {}
            for idx, row in pvals.iterrows():
                mcs_detail[idx] = round(float(row['Pvalue']), 4)
                print(f"        {idx}: p={row['Pvalue']:.4f} {'✓' if row['Pvalue'] >= 0.10 else '✗'}")

            asset_results['mcs'] = {
                'superior_set': included,
                'excluded': excluded,
                'p_values': mcs_detail,
                'alpha': 0.10,
                'n_obs': int(common_mask.sum()),
            }
        else:
            print("      Insufficient common observations for MCS")
            asset_results['mcs'] = {'status': 'insufficient_data'}
    except Exception as e:
        print(f"      MCS failed: {e}")
        asset_results['mcs'] = {'status': f'error: {str(e)}'}

    # ============================================================
    # 9. HAR vs GJR Direct Comparison
    # ============================================================
    if 'HAR_LR' in qlike_losses and 'GJR' in qlike_losses:
        n_min = min(len(qlike_losses['HAR_LR']), len(qlike_losses['GJR']))
        har_l = qlike_losses['HAR_LR'][:n_min]
        gjr_l = qlike_losses['GJR'][:n_min]
        dm_stat, dm_p = dm_test_hac(har_l, gjr_l)
        winner = 'HAR_LR' if dm_stat < 0 else 'GJR'

        # QLIKE improvement
        har_mean = float(np.mean(har_l))
        gjr_mean = float(np.mean(gjr_l))
        improvement = (gjr_mean - har_mean) / gjr_mean * 100 if gjr_mean != 0 else 0

        print(f"\n    --- HAR vs GJR Head-to-Head ---")
        print(f"      HAR QLIKE: {har_mean:.6f}")
        print(f"      GJR QLIKE: {gjr_mean:.6f}")
        print(f"      Improvement (HAR over GJR): {improvement:+.2f}%")
        print(f"      DM stat: {dm_stat:+.3f}, p={dm_p:.4f}")
        print(f"      Winner: {winner}")

        asset_results['har_vs_gjr'] = {
            'har_qlike': round(har_mean, 6),
            'gjr_qlike': round(gjr_mean, 6),
            'improvement_pct': round(improvement, 2),
            'dm_stat': round(dm_stat, 3),
            'dm_p': round(dm_p, 4),
            'winner': winner,
        }

    results[ticker] = asset_results

# ============================================================
# 10. CROSS-ASSET COMPARISON
# ============================================================
print("\n" + "=" * 70)
print("[4] CROSS-ASSET COMPARISON")
print("=" * 70)

cross_comparison = {}
for ticker in ASSETS:
    r = results[ticker]
    if 'best_model' in r:
        gamma_info = r.get('gjr_gamma', {})
        cross_comparison[ticker] = {
            'best_model': r['best_model'],
            'best_qlike': r.get('best_qlike'),
            'gjr_gamma_mean': gamma_info.get('mean_gamma'),
            'gjr_gamma_positive_pct': gamma_info.get('pct_positive'),
            'leverage_type': 'inverted' if gamma_info.get('mean_gamma', 0) > 0 else 'standard',
            'mcs_superior': r.get('mcs', {}).get('superior_set', []),
        }

        print(f"\n  {ticker}:")
        print(f"    Best: {r['best_model']} (QLIKE={r.get('best_qlike', 'N/A')})")
        print(f"    Gamma: {gamma_info.get('mean_gamma', 'N/A')} ({'inverted' if gamma_info.get('mean_gamma', 0) > 0 else 'standard'})")
        print(f"    MCS: {r.get('mcs', {}).get('superior_set', 'N/A')}")

# ============================================================
# 11. KEY FINDINGS SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[5] KEY FINDINGS")
print("=" * 70)

findings = []

# Q1: QLIKE ceiling
for ticker in ASSETS:
    r = results[ticker]
    models = r.get('models', {})
    if 'GJR' in models and 'GARCH' in models:
        gjr_ql = models['GJR'].get('qlike_mean')
        garch_ql = models['GARCH'].get('qlike_mean')
        if gjr_ql and garch_ql:
            improvement = (garch_ql - gjr_ql) / garch_ql * 100
            finding = f"{ticker}: GJR vs GARCH improvement = {improvement:+.2f}%"
            findings.append(finding)
            print(f"  Q1 (QLIKE ceiling): {finding}")

# Q2: Leverage direction
for ticker in ASSETS:
    gamma_info = results[ticker].get('gjr_gamma', {})
    if gamma_info:
        direction = "INVERTED (positive)" if gamma_info.get('mean_gamma', 0) > 0 else "STANDARD (negative)"
        finding = f"{ticker}: gamma={gamma_info.get('mean_gamma')}, {direction}, sig={gamma_info.get('pct_significant', 0):.0%}"
        findings.append(finding)
        print(f"  Q2 (Leverage direction): {finding}")

# Q3: HAR effectiveness
for ticker in ASSETS:
    hvg = results[ticker].get('har_vs_gjr', {})
    if hvg:
        finding = f"{ticker}: HAR vs GJR → {hvg['winner']} wins (DM p={hvg['dm_p']:.4f}, improvement={hvg['improvement_pct']:+.2f}%)"
        findings.append(finding)
        print(f"  Q3 (HAR in commodities): {finding}")

# Q4: Semivariance
for ticker in ASSETS:
    models = results[ticker].get('models', {})
    if 'Semivar' in models and 'GJR' in models:
        semi_ql = models['Semivar'].get('qlike_mean')
        gjr_ql = models['GJR'].get('qlike_mean')
        if semi_ql and gjr_ql:
            finding = f"{ticker}: Semivar QLIKE={semi_ql:.6f} vs GJR={gjr_ql:.6f} → {'Semivar better' if semi_ql < gjr_ql else 'GJR better'}"
            findings.append(finding)
            print(f"  Q4 (Semivariance): {finding}")

# Q5: MCS
for ticker in ASSETS:
    mcs = results[ticker].get('mcs', {})
    if 'superior_set' in mcs:
        finding = f"{ticker}: MCS superior set = {mcs['superior_set']}"
        findings.append(finding)
        print(f"  Q5 (MCS): {finding}")

elapsed = time.time() - t_start
print(f"\n  Total time: {elapsed:.1f}s")

# ============================================================
# 12. SAVE RESULTS
# ============================================================
output = {
    'experiment_id': 'K483',
    'title': 'Commodity Volatility — Oil and Gold Vol Forecasting',
    'date': datetime.now(timezone.utc).isoformat(),
    'author': '[Proposed: User(commodity direction), Executed: Claude]',
    'data_source': 'yfinance (empirical)',
    'assets': list(ASSETS.keys()),
    'oos_period': f'{OOS_START} to {OOS_END}',
    'is_window': IS_WINDOW,
    'models': ['GARCH(1,1)', 'GJR-GARCH(1,1)', 'EGARCH(1,1)', 'HAR_log-range', 'Semivariance_RS-', 'EWMA(0.94)', 'Ensemble(GJR+HAR)'],
    'evaluation': 'QLIKE with r² proxy + DM test (HAC) + MCS (Hansen et al. 2011)',
    'references': [
        'Corsi (2009) J Financial Econometrics — HAR-RV',
        'Glosten, Jagannathan, Runkle (1993) JF — GJR-GARCH',
        'Nelson (1991) Econometrica — EGARCH',
        'Patton (2011) J Econometrics — QLIKE loss',
        'Patton & Sheppard (2015) JFQA — Semivariance',
        'Hansen, Lunde, Nason (2011) Econometrica — MCS',
        'K132: GLD QLIKE capture rate 19.4%',
        'K135: GLD inventory-conditioned vol null',
        'K453: GLD semivar gamma≈0, RS⁻ fails',
    ],
    'results': {},
    'cross_comparison': cross_comparison,
    'findings': findings,
    'elapsed_seconds': round(elapsed, 1),
}

# Convert results for JSON serialization
for ticker in ASSETS:
    r = results[ticker]
    output['results'][ticker] = {
        'diagnostics': r['diagnostics'],
        'models': r['models'],
        'best_model': r.get('best_model'),
        'best_qlike': r.get('best_qlike'),
        'gjr_gamma': r.get('gjr_gamma'),
        'egarch_gamma': r.get('egarch_gamma'),
        'dm_tests': r.get('dm_tests'),
        'mcs': r.get('mcs'),
        'har_vs_gjr': r.get('har_vs_gjr'),
    }

output_path = 'experiments/k483_commodity_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print("=" * 70)
print("K483 COMPLETE")
print("=" * 70)
