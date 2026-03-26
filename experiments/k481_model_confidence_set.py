"""
K481: Model Confidence Set (MCS) — Formal Multi-Model Comparison
================================================================
Hansen, Lunde, Nason (2011) "The Model Confidence Set" Econometrica 79(2):453-497

MCS is the gold standard for multi-model comparison:
- Controls for multiple testing (unlike pairwise DM tests)
- Finds the "superior set" of models that cannot be rejected as inferior
- More rigorous than cherry-picking best model from pairwise comparisons

This experiment applies MCS to our 8 candidate volatility models for SPY
using both r² and Parkinson proxies, with sub-period stability analysis.

References:
- Hansen, Lunde, Nason (2011) Econometrica 79(2):453-497 — MCS procedure
- Corsi (2009) J Financial Econometrics — HAR-RV model
- Patton (2011) J Econometrics — Volatility forecast evaluation with QLIKE
- Glosten, Jagannathan, Runkle (1993) JF — GJR-GARCH
- Patton & Sheppard (2015) — Semivariance decomposition
- K468 — Yang-Zhang tautology check (Parkinson favors range models)
- K469 — HAR with r² proxy (genuine advantage confirmed)

Author: VolPred Research System
Date: 2026-03-26
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from arch import arch_model
from arch.bootstrap import MCS
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
ASSET = 'SPY'
IS_WINDOW = 2000
OOS_START = '2023-01-01'
OOS_END = '2025-12-31'
MCS_ALPHA = 0.10
MCS_BOOTSTRAP_REPS = 5000
MCS_BLOCK_SIZE = 10  # block bootstrap for dependent losses
EWMA_LAMBDA = 0.94
ROLLING_WINDOW = 21

# Sub-periods for stability analysis
SUB_PERIODS = [
    ('2015-01-01', '2016-12-31', '2015-2016 (low vol)'),
    ('2017-01-01', '2018-12-31', '2017-2018 (Volmageddon)'),
    ('2019-01-01', '2020-12-31', '2019-2020 (COVID)'),
    ('2021-01-01', '2022-12-31', '2021-2022 (rate hikes)'),
    ('2023-01-01', '2025-12-31', '2023-2025 (post-COVID)'),
]


def download_data():
    """Download SPY OHLC data from yfinance."""
    df = yf.download(ASSET, start='2004-01-01', end='2026-03-26', auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()

    # Compute returns and volatility proxies
    df['log_return'] = np.log(df['Close'] / df['Close'].shift(1))
    df['r_squared'] = df['log_return'] ** 2
    df['log_range'] = np.log(df['High'] / df['Low'])
    df['parkinson_var'] = df['log_range'] ** 2 / (4 * np.log(2))
    df = df.dropna().copy()

    return df


def compute_qlike(forecast, proxy):
    """QLIKE loss: proxy/forecast - log(proxy/forecast) - 1"""
    ratio = proxy / forecast
    # Avoid log(0) or log(negative)
    ratio = np.clip(ratio, 1e-10, None)
    return ratio - np.log(ratio) - 1


def fit_gjr_garch(returns_pct, dist='t'):
    """Fit GJR-GARCH(1,1) and return 1-step forecast variance."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist=dist, mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        if not res.convergence_flag == 0:
            return None, None
        forecast = res.forecast(horizon=1)
        cond_var = res.conditional_volatility ** 2 / 10000  # Convert from pct^2 to decimal^2
        one_step = forecast.variance.values[-1, 0] / 10000
        return cond_var, res
    except:
        return None, None


def fit_garch(returns_pct):
    """Fit GARCH(1,1) and return conditional variance series."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, q=1, dist='normal', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        cond_var = res.conditional_volatility ** 2 / 10000
        return cond_var, res
    except:
        return None, None


def fit_egarch(returns_pct):
    """Fit EGARCH(1,1) and return conditional variance series."""
    try:
        am = arch_model(returns_pct, vol='EGARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        cond_var = res.conditional_volatility ** 2 / 10000
        return cond_var, res
    except:
        return None, None


def rolling_forecast_all_models(df, oos_start_date, oos_end_date):
    """
    Generate rolling 1-step-ahead forecasts for all 8 models.
    Returns DataFrame of forecasts and DataFrame of proxies aligned to OOS dates.
    """
    oos_mask = (df.index >= oos_start_date) & (df.index <= oos_end_date)
    oos_dates = df.index[oos_mask]

    if len(oos_dates) < 50:
        return None, None, None

    # Pre-compute full series
    returns_pct = df['log_return'] * 100
    r_squared = df['r_squared'].values
    parkinson_var = df['parkinson_var'].values
    log_range = df['log_range'].values

    n = len(df)
    all_indices = np.arange(n)
    oos_positions = all_indices[oos_mask]

    # Storage for forecasts
    forecasts = {
        'GJR-GARCH': np.full(len(oos_dates), np.nan),
        'GARCH': np.full(len(oos_dates), np.nan),
        'EGARCH': np.full(len(oos_dates), np.nan),
        'HAR_logrange': np.full(len(oos_dates), np.nan),
        'Semivar_RS-': np.full(len(oos_dates), np.nan),
        'EWMA': np.full(len(oos_dates), np.nan),
        'GJR+HAR_Ens': np.full(len(oos_dates), np.nan),
        'Rolling_21d': np.full(len(oos_dates), np.nan),
    }

    # ---- GARCH-family: expanding window from IS_WINDOW ----
    # Fit once on full IS period + rolling
    first_oos_pos = oos_positions[0]

    # For efficiency: fit GARCH models once on full IS sample,
    # then use rolling 1-step forecasts
    is_end = first_oos_pos  # position of first OOS obs
    is_start = max(0, is_end - IS_WINDOW)

    # Fit GARCH-family on IS data and extract conditional variance for full sample
    print("  Fitting GJR-GARCH...")
    am_gjr = arch_model(returns_pct.iloc[:is_end], vol='GARCH', p=1, o=1, q=1,
                         dist='t', mean='Constant')
    res_gjr = am_gjr.fit(disp='off', show_warning=False, last_obs=is_end)

    print("  Fitting GARCH...")
    am_g = arch_model(returns_pct.iloc[:is_end], vol='GARCH', p=1, q=1,
                       dist='normal', mean='Constant')
    res_g = am_g.fit(disp='off', show_warning=False, last_obs=is_end)

    print("  Fitting EGARCH...")
    am_e = arch_model(returns_pct.iloc[:is_end], vol='EGARCH', p=1, o=1, q=1,
                       dist='normal', mean='Constant')
    res_e = am_e.fit(disp='off', show_warning=False, last_obs=is_end)

    # For truly rolling forecasts, refit periodically (every 63 days ~ quarterly)
    refit_interval = 63

    for i, pos in enumerate(oos_positions):
        # Determine if we need to refit
        if i % refit_interval == 0 and i > 0:
            try:
                am_gjr2 = arch_model(returns_pct.iloc[max(0, pos-IS_WINDOW):pos],
                                      vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
                res_gjr = am_gjr2.fit(disp='off', show_warning=False)
            except:
                pass
            try:
                am_g2 = arch_model(returns_pct.iloc[max(0, pos-IS_WINDOW):pos],
                                    vol='GARCH', p=1, q=1, dist='normal', mean='Constant')
                res_g = am_g2.fit(disp='off', show_warning=False)
            except:
                pass
            try:
                am_e2 = arch_model(returns_pct.iloc[max(0, pos-IS_WINDOW):pos],
                                    vol='EGARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
                res_e = am_e2.fit(disp='off', show_warning=False)
            except:
                pass

        # 1-step forecast from GARCH models using parameter updating
        ret_t = returns_pct.iloc[pos - 1]  # most recent return

        # GJR-GARCH forecast
        try:
            params = res_gjr.params
            omega = params.get('omega', params.iloc[1])
            alpha = params.get('alpha[1]', params.iloc[2])
            gamma = params.get('gamma[1]', params.iloc[3])
            beta = params.get('beta[1]', params.iloc[4])

            if i == 0:
                prev_var_gjr = res_gjr.conditional_volatility.iloc[-1] ** 2

            indicator = 1.0 if ret_t < 0 else 0.0
            new_var = omega + (alpha + gamma * indicator) * ret_t**2 + beta * prev_var_gjr
            forecasts['GJR-GARCH'][i] = new_var / 10000
            prev_var_gjr = new_var
        except:
            pass

        # GARCH forecast
        try:
            params = res_g.params
            omega = params.get('omega', params.iloc[1])
            alpha = params.get('alpha[1]', params.iloc[2])
            beta = params.get('beta[1]', params.iloc[3])

            if i == 0:
                prev_var_g = res_g.conditional_volatility.iloc[-1] ** 2

            new_var = omega + alpha * ret_t**2 + beta * prev_var_g
            forecasts['GARCH'][i] = new_var / 10000
            prev_var_g = new_var
        except:
            pass

        # EGARCH forecast
        try:
            params = res_e.params
            omega_e = params.get('omega', params.iloc[1])
            alpha_e = params.get('alpha[1]', params.iloc[2])
            gamma_e = params.get('gamma[1]', params.iloc[3])
            beta_e = params.get('beta[1]', params.iloc[4])

            if i == 0:
                prev_log_var_e = np.log(res_e.conditional_volatility.iloc[-1] ** 2)

            std_resid = ret_t / np.exp(prev_log_var_e / 2)
            new_log_var = omega_e + alpha_e * (np.abs(std_resid) - np.sqrt(2/np.pi)) + gamma_e * std_resid + beta_e * prev_log_var_e
            new_var = np.exp(new_log_var)
            forecasts['EGARCH'][i] = new_var / 10000
            prev_log_var_e = new_log_var
        except:
            pass

        # HAR log-range forecast
        try:
            lr = log_range[max(0, pos-21):pos]
            lr_sq = lr ** 2

            lr_1d = lr_sq[-1]
            lr_5d = np.mean(lr_sq[-5:]) if len(lr_sq) >= 5 else lr_1d
            lr_21d = np.mean(lr_sq[-21:]) if len(lr_sq) >= 21 else lr_5d

            # Simple HAR: forecast = c + b1*lr_1d + b2*lr_5d + b3*lr_21d
            # Use IS calibration for coefficients
            if i == 0:
                # Fit HAR on IS data
                is_lr_sq = log_range[is_start:is_end] ** 2
                n_is = len(is_lr_sq)
                y_har = is_lr_sq[21:]
                x1 = is_lr_sq[20:-1]
                x5 = np.array([np.mean(is_lr_sq[j-4:j+1]) for j in range(20, n_is-1)])
                x21 = np.array([np.mean(is_lr_sq[j-20:j+1]) for j in range(20, n_is-1)])
                X_har = np.column_stack([np.ones(len(y_har)), x1, x5, x21])
                try:
                    har_coefs = np.linalg.lstsq(X_har, y_har, rcond=None)[0]
                except:
                    har_coefs = np.array([np.mean(y_har), 0.3, 0.3, 0.3])

                # IS scale ratio: r² / Parkinson for proxy alignment
                is_r2_mean = np.mean(r_squared[is_start:is_end])
                is_park_mean = np.mean(parkinson_var[is_start:is_end])
                har_scale_ratio = is_r2_mean / is_park_mean if is_park_mean > 0 else 1.5

            har_pred = har_coefs[0] + har_coefs[1]*lr_1d + har_coefs[2]*lr_5d + har_coefs[3]*lr_21d
            har_pred = max(har_pred, 1e-10)
            # Convert to Parkinson variance scale, then apply ratio for r² proxy
            har_parkinson = har_pred / (4 * np.log(2))
            forecasts['HAR_logrange'][i] = har_parkinson  # Keep in Parkinson scale; will scale for r² eval
        except:
            pass

        # Semivariance RS⁻ forecast
        try:
            rets = df['log_return'].values[max(0, pos-21):pos]
            neg_rets = rets[rets < 0]
            pos_rets = rets[rets >= 0]

            rs_neg_5 = np.sum(rets[-5:][rets[-5:] < 0] ** 2) if len(rets) >= 5 else 0
            rs_neg_21 = np.sum(neg_rets ** 2) / max(len(rets), 1) * 21
            rs_pos_5 = np.sum(rets[-5:][rets[-5:] >= 0] ** 2) if len(rets) >= 5 else 0
            rs_pos_21 = np.sum(pos_rets ** 2) / max(len(rets), 1) * 21

            if i == 0:
                # Fit semivariance HAR on IS
                is_rets = df['log_return'].values[is_start:is_end]
                n_is = len(is_rets)
                sv_y = is_rets[21:] ** 2
                sv_neg5 = np.array([np.sum(is_rets[j-4:j+1][is_rets[j-4:j+1] < 0]**2) for j in range(20, n_is-1)])
                sv_neg21 = np.array([np.sum(is_rets[j-20:j+1][is_rets[j-20:j+1] < 0]**2) for j in range(20, n_is-1)])
                sv_pos5 = np.array([np.sum(is_rets[j-4:j+1][is_rets[j-4:j+1] >= 0]**2) for j in range(20, n_is-1)])
                sv_pos21 = np.array([np.sum(is_rets[j-20:j+1][is_rets[j-20:j+1] >= 0]**2) for j in range(20, n_is-1)])
                X_sv = np.column_stack([np.ones(len(sv_y)), sv_neg5, sv_neg21, sv_pos5, sv_pos21])
                try:
                    sv_coefs = np.linalg.lstsq(X_sv, sv_y, rcond=None)[0]
                except:
                    sv_coefs = np.array([1e-5, 0.25, 0.25, 0.25, 0.25])

            sv_pred = sv_coefs[0] + sv_coefs[1]*rs_neg_5 + sv_coefs[2]*rs_neg_21 + sv_coefs[3]*rs_pos_5 + sv_coefs[4]*rs_pos_21
            forecasts['Semivar_RS-'][i] = max(sv_pred, 1e-10)
        except:
            pass

        # EWMA forecast
        try:
            if i == 0:
                # Initialize with IS variance
                prev_var_ewma = np.var(df['log_return'].values[is_start:is_end])

            ret_dec = df['log_return'].values[pos - 1]
            new_var = EWMA_LAMBDA * prev_var_ewma + (1 - EWMA_LAMBDA) * ret_dec**2
            forecasts['EWMA'][i] = new_var
            prev_var_ewma = new_var
        except:
            pass

        # Rolling 21d variance
        try:
            rets_21 = df['log_return'].values[pos-ROLLING_WINDOW:pos]
            forecasts['Rolling_21d'][i] = np.var(rets_21, ddof=1)
        except:
            pass

    # GJR+HAR Ensemble = simple average of GJR and HAR
    gjr_f = forecasts['GJR-GARCH']
    har_f = forecasts['HAR_logrange']
    valid_both = ~np.isnan(gjr_f) & ~np.isnan(har_f)
    ens = np.full(len(oos_dates), np.nan)
    # For ensemble: need both in same scale. HAR is in Parkinson scale.
    # Scale HAR to r² scale for combination
    har_r2_scale = har_f * har_scale_ratio
    ens[valid_both] = (gjr_f[valid_both] + har_r2_scale[valid_both]) / 2
    forecasts['GJR+HAR_Ens'] = ens

    # Build DataFrames
    forecasts_df = pd.DataFrame(forecasts, index=oos_dates)

    # Proxies
    proxies = pd.DataFrame({
        'r_squared': r_squared[oos_mask],
        'parkinson_var': parkinson_var[oos_mask],
    }, index=oos_dates)

    return forecasts_df, proxies, har_scale_ratio


def run_mcs(losses_df, alpha=MCS_ALPHA, reps=MCS_BOOTSTRAP_REPS, block_size=MCS_BLOCK_SIZE):
    """
    Run Hansen-Lunde-Nason (2011) MCS using arch package.

    Returns dict with included models, excluded models, and p-values.
    """
    # Drop columns with too many NaN
    valid_cols = losses_df.columns[losses_df.isna().sum() < len(losses_df) * 0.1]
    losses_clean = losses_df[valid_cols].dropna()

    if len(losses_clean) < 50 or len(valid_cols) < 2:
        return None

    mcs = MCS(losses_clean, size=alpha, reps=reps, block_size=block_size,
              method='R', bootstrap='stationary', seed=42)
    mcs.compute()

    pvalues = mcs.pvalues
    included = mcs.included
    excluded = mcs.excluded

    return {
        'included_models': included,
        'excluded_models': excluded,
        'pvalues': pvalues.to_dict(),
        'n_obs': len(losses_clean),
        'alpha': alpha,
        'n_included': len(included),
        'n_excluded': len(excluded),
    }


def compute_all_losses(forecasts_df, proxies, proxy_name, har_scale_ratio):
    """Compute QLIKE losses for all models with given proxy."""
    proxy = proxies[proxy_name].values
    losses = {}

    for model in forecasts_df.columns:
        fc = forecasts_df[model].values.copy()

        # Scale HAR forecast depending on proxy
        if model == 'HAR_logrange':
            if proxy_name == 'r_squared':
                fc = fc * har_scale_ratio
            # For Parkinson, HAR is already in Parkinson scale

        if model == 'GJR+HAR_Ens':
            # Ensemble already scaled for r² during construction
            if proxy_name == 'parkinson_var':
                # Need to reconstruct for Parkinson
                gjr_f = forecasts_df['GJR-GARCH'].values
                har_f = forecasts_df['HAR_logrange'].values
                fc = (gjr_f + har_f) / 2  # Both in Parkinson-ish scale? GJR is r² scale
                # Actually GJR is in r² scale, HAR in Parkinson.
                # For Parkinson eval: scale GJR to Parkinson
                fc = forecasts_df['GJR+HAR_Ens'].values / har_scale_ratio  # rough

        valid = ~np.isnan(fc) & ~np.isnan(proxy) & (fc > 0) & (proxy > 0)
        if valid.sum() < 50:
            continue

        ql = compute_qlike(fc[valid], proxy[valid])
        # Use full-length array with NaN padding
        ql_full = np.full(len(proxy), np.nan)
        ql_full[valid] = ql
        losses[model] = ql_full

    return pd.DataFrame(losses)


def dm_test(loss1, loss2):
    """Diebold-Mariano test with HAC variance."""
    d = loss1 - loss2
    d = d[~np.isnan(d)]
    if len(d) < 30:
        return np.nan, np.nan

    # Newey-West HAC
    n = len(d)
    d_bar = np.mean(d)
    max_lag = int(np.floor(n ** (1/3)))

    gamma_0 = np.var(d, ddof=1)
    hac_var = gamma_0
    for k in range(1, max_lag + 1):
        weight = 1 - k / (max_lag + 1)
        gamma_k = np.sum((d[k:] - d_bar) * (d[:-k] - d_bar)) / n
        hac_var += 2 * weight * gamma_k

    hac_se = np.sqrt(hac_var / n)
    if hac_se < 1e-15:
        return 0, 1.0

    dm_stat = d_bar / hac_se
    p_value = 2 * (1 - stats.t.cdf(np.abs(dm_stat), df=n-1))

    return dm_stat, p_value


def main():
    print("=" * 70)
    print("K481: Model Confidence Set (MCS) — Formal Multi-Model Comparison")
    print("Hansen, Lunde, Nason (2011) Econometrica 79(2):453-497")
    print("=" * 70)

    # ---- Step 1: Download data ----
    print("\n[1] Downloading SPY data...")
    df = download_data()
    print(f"  Total observations: {len(df)}")
    print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    # ---- Step 2: Diagnostics ----
    print("\n[2] Data diagnostics...")
    returns = df['log_return']
    diagnostics = {
        'n_obs': len(df),
        'date_range': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'return_mean_pct': float(returns.mean() * 100),
        'return_std_pct': float(returns.std() * 100),
        'return_skew': float(returns.skew()),
        'return_kurt': float(returns.kurtosis()),
        'r2_mean': float(df['r_squared'].mean()),
        'parkinson_mean': float(df['parkinson_var'].mean()),
        'r2_over_parkinson_ratio': float(df['r_squared'].mean() / df['parkinson_var'].mean()),
    }

    for k, v in diagnostics.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.6f}")
        else:
            print(f"  {k}: {v}")

    # ---- Step 3: Generate rolling forecasts for full OOS (2023-2025) ----
    print("\n[3] Generating rolling forecasts (2023-2025)...")
    forecasts_df, proxies, har_scale_ratio = rolling_forecast_all_models(df, OOS_START, OOS_END)

    if forecasts_df is None:
        print("ERROR: No OOS data available")
        return

    print(f"  OOS observations: {len(forecasts_df)}")
    print(f"  HAR scale ratio (r²/Parkinson): {har_scale_ratio:.4f}")
    print(f"  Models: {list(forecasts_df.columns)}")

    # Check NaN counts
    print("\n  NaN counts per model:")
    for col in forecasts_df.columns:
        nan_count = forecasts_df[col].isna().sum()
        print(f"    {col}: {nan_count}/{len(forecasts_df)}")

    # ---- Step 4: MCS with r² proxy ----
    print("\n[4] MCS with r² proxy (the fair comparison)...")
    losses_r2 = compute_all_losses(forecasts_df, proxies, 'r_squared', har_scale_ratio)

    # Mean QLIKE per model
    print("\n  Mean QLIKE losses (r² proxy, lower = better):")
    mean_losses_r2 = losses_r2.mean().sort_values()
    for model, loss in mean_losses_r2.items():
        print(f"    {model}: {loss:.6f}")

    mcs_r2 = run_mcs(losses_r2)

    if mcs_r2:
        print(f"\n  MCS Results (α={MCS_ALPHA}, B={MCS_BOOTSTRAP_REPS}):")
        print(f"  Superior Set ({mcs_r2['n_included']} models):")
        for m in mcs_r2['included_models']:
            pval = mcs_r2['pvalues']['Pvalue'].get(m, 'N/A')
            print(f"    ✓ {m} (MCS p-value: {pval:.4f})" if isinstance(pval, float) else f"    ✓ {m}")
        print(f"  Excluded ({mcs_r2['n_excluded']} models):")
        for m in mcs_r2['excluded_models']:
            pval = mcs_r2['pvalues']['Pvalue'].get(m, 'N/A')
            print(f"    ✗ {m} (MCS p-value: {pval:.4f})" if isinstance(pval, float) else f"    ✗ {m}")

    # ---- Step 5: MCS with Parkinson proxy (tautology check) ----
    print("\n[5] MCS with Parkinson proxy (tautology check per K468)...")
    losses_park = compute_all_losses(forecasts_df, proxies, 'parkinson_var', har_scale_ratio)

    print("\n  Mean QLIKE losses (Parkinson proxy, lower = better):")
    mean_losses_park = losses_park.mean().sort_values()
    for model, loss in mean_losses_park.items():
        print(f"    {model}: {loss:.6f}")

    mcs_park = run_mcs(losses_park)

    if mcs_park:
        print(f"\n  MCS Results (Parkinson proxy):")
        print(f"  Superior Set ({mcs_park['n_included']} models):")
        for m in mcs_park['included_models']:
            pval = mcs_park['pvalues']['Pvalue'].get(m, 'N/A')
            print(f"    ✓ {m} (MCS p-value: {pval:.4f})" if isinstance(pval, float) else f"    ✓ {m}")
        print(f"  Excluded ({mcs_park['n_excluded']} models):")
        for m in mcs_park['excluded_models']:
            pval = mcs_park['pvalues']['Pvalue'].get(m, 'N/A')
            print(f"    ✗ {m} (MCS p-value: {pval:.4f})" if isinstance(pval, float) else f"    ✗ {m}")

    # ---- Step 6: Pairwise DM tests for context ----
    print("\n[6] Pairwise DM tests (r² proxy) for context...")
    models_list = list(losses_r2.columns)
    dm_results = {}
    for i, m1 in enumerate(models_list):
        for j, m2 in enumerate(models_list):
            if i < j:
                stat, pval = dm_test(losses_r2[m1].values, losses_r2[m2].values)
                dm_results[f"{m1}_vs_{m2}"] = {'dm_stat': float(stat), 'p_value': float(pval)}
                if pval < 0.10:
                    winner = m1 if stat < 0 else m2
                    print(f"  {m1} vs {m2}: DM={stat:.3f}, p={pval:.4f} → {winner} wins")

    # ---- Step 7: Sub-period MCS stability ----
    print("\n[7] Sub-period MCS stability analysis...")
    subperiod_results = []

    for sp_start, sp_end, sp_name in SUB_PERIODS:
        print(f"\n  --- {sp_name} ---")
        fc_sub, prox_sub, scale_sub = rolling_forecast_all_models(df, sp_start, sp_end)

        if fc_sub is None or len(fc_sub) < 50:
            print(f"  Skipped (insufficient data)")
            subperiod_results.append({
                'period': sp_name,
                'status': 'skipped',
                'reason': 'insufficient data'
            })
            continue

        losses_sub = compute_all_losses(fc_sub, prox_sub, 'r_squared', scale_sub)

        # Mean losses
        mean_sub = losses_sub.mean().sort_values()
        best_model = mean_sub.index[0]
        print(f"  Best model (QLIKE): {best_model} ({mean_sub.iloc[0]:.6f})")

        mcs_sub = run_mcs(losses_sub, reps=3000)  # Fewer reps for speed

        sp_result = {
            'period': sp_name,
            'n_oos': len(fc_sub),
            'mean_qlike': {m: float(v) for m, v in mean_sub.items()},
            'best_model': best_model,
        }

        if mcs_sub:
            sp_result['mcs_included'] = mcs_sub['included_models']
            sp_result['mcs_n_included'] = mcs_sub['n_included']
            sp_result['mcs_pvalues'] = {str(k): float(v) for k, v in mcs_sub['pvalues']['Pvalue'].items()}
            print(f"  MCS superior set: {mcs_sub['included_models']}")
        else:
            sp_result['mcs_status'] = 'failed'

        subperiod_results.append(sp_result)

    # ---- Step 8: Cross-period consistency ----
    print("\n[8] Cross-period consistency analysis...")
    model_in_mcs_count = {}
    n_valid_periods = 0
    for sp in subperiod_results:
        if 'mcs_included' in sp:
            n_valid_periods += 1
            for m in sp['mcs_included']:
                model_in_mcs_count[m] = model_in_mcs_count.get(m, 0) + 1

    print(f"\n  Times each model appears in MCS (out of {n_valid_periods} periods):")
    for m, count in sorted(model_in_mcs_count.items(), key=lambda x: -x[1]):
        print(f"    {m}: {count}/{n_valid_periods}")

    # ---- Step 9: Build results ----
    print("\n[9] Compiling results...")

    # Serialize pvalues properly
    def serialize_mcs_result(mcs_res):
        if mcs_res is None:
            return None
        result = dict(mcs_res)
        # Convert pvalues dict
        if 'pvalues' in result:
            result['pvalues'] = {
                col: {str(k): float(v) for k, v in vals.items()}
                for col, vals in result['pvalues'].items()
            }
        return result

    results = {
        'experiment_id': 'K481',
        'title': 'Model Confidence Set (MCS) — Formal Multi-Model Comparison',
        'date': datetime.now(timezone.utc).isoformat(),
        'references': [
            'Hansen, Lunde, Nason (2011) "The Model Confidence Set" Econometrica 79(2):453-497',
            'Corsi (2009) J Financial Econometrics — HAR-RV model',
            'Patton (2011) J Econometrics — Volatility forecast evaluation',
            'K468 — Yang-Zhang tautology check',
            'K469 — HAR with r² proxy',
            'K475 — Validated ensemble',
        ],
        'method': {
            'procedure': 'Hansen-Lunde-Nason (2011) MCS with range statistic (T_R)',
            'bootstrap': f'Stationary bootstrap, B={MCS_BOOTSTRAP_REPS}, block_size={MCS_BLOCK_SIZE}',
            'alpha': MCS_ALPHA,
            'loss_function': 'QLIKE = proxy/forecast - log(proxy/forecast) - 1',
            'implementation': 'arch.bootstrap.MCS (Python arch package)',
            'refit_interval': '63 trading days (quarterly) for GARCH models',
        },
        'asset': ASSET,
        'data_source': 'yfinance',
        'diagnostics': diagnostics,
        'models': {
            'GJR-GARCH': 'GJR-GARCH(1,1) Student-t, quarterly refit',
            'GARCH': 'GARCH(1,1) Normal, quarterly refit',
            'EGARCH': 'EGARCH(1,1) Normal, quarterly refit',
            'HAR_logrange': 'HAR log-range (1d+5d+21d), IS OLS calibration',
            'Semivar_RS-': 'HAR-style semivariance (RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21)',
            'EWMA': f'EWMA (λ={EWMA_LAMBDA})',
            'GJR+HAR_Ens': 'Equal-weight ensemble of GJR + HAR (scaled to r² level)',
            'Rolling_21d': 'Rolling 21-day sample variance',
        },
        'main_results': {
            'r2_proxy': {
                'description': 'MCS with r² proxy (close-to-close squared return) — fair comparison',
                'oos_period': f'{OOS_START} to {OOS_END}',
                'mean_qlike': {m: float(v) for m, v in mean_losses_r2.items()},
                'mcs': serialize_mcs_result(mcs_r2),
                'interpretation': None,  # Will fill below
            },
            'parkinson_proxy': {
                'description': 'MCS with Parkinson proxy — tautology check (K468)',
                'oos_period': f'{OOS_START} to {OOS_END}',
                'mean_qlike': {m: float(v) for m, v in mean_losses_park.items()},
                'mcs': serialize_mcs_result(mcs_park),
                'tautology_note': 'Parkinson proxy naturally favors range-based models (HAR, Rolling)',
            },
        },
        'pairwise_dm_tests': dm_results,
        'subperiod_stability': subperiod_results,
        'cross_period_consistency': {
            'n_periods': n_valid_periods,
            'model_mcs_count': model_in_mcs_count,
        },
    }

    # Interpretation
    if mcs_r2:
        incl = mcs_r2['included_models']
        if len(incl) == 1:
            interp = f"Clear winner: {incl[0]} is the only model in the MCS — statistically superior to all others."
        elif len(incl) == len(models_list):
            interp = "All models in MCS — no model is statistically inferior. Differences are not significant."
        else:
            interp = f"Superior set contains {len(incl)} models: {incl}. These are statistically indistinguishable. Excluded models are significantly worse."
        results['main_results']['r2_proxy']['interpretation'] = interp

    # Proxy sensitivity
    if mcs_r2 and mcs_park:
        r2_set = set(mcs_r2['included_models'])
        park_set = set(mcs_park['included_models'])
        overlap = r2_set & park_set
        r2_only = r2_set - park_set
        park_only = park_set - r2_set

        results['proxy_sensitivity'] = {
            'overlap': list(overlap),
            'r2_only': list(r2_only),
            'parkinson_only': list(park_only),
            'interpretation': (
                f"Overlap: {list(overlap)}. "
                f"r²-only: {list(r2_only)}. "
                f"Parkinson-only: {list(park_only)}. "
                "Models in Parkinson-only but not r² set may benefit from tautological advantage."
            )
        }

    # Summary conclusion
    conclusion_parts = []
    if mcs_r2:
        conclusion_parts.append(f"MCS (r² proxy, α={MCS_ALPHA}): {len(mcs_r2['included_models'])} of {len(models_list)} models in superior set.")
        conclusion_parts.append(f"Included: {mcs_r2['included_models']}")
        conclusion_parts.append(f"Excluded: {mcs_r2['excluded_models']}")

    conclusion_parts.append(f"Cross-period: most robust model(s) = {sorted(model_in_mcs_count.items(), key=lambda x: -x[1])[:3]}")

    results['conclusion'] = ' | '.join(conclusion_parts)
    results['limitations'] = [
        'QLIKE loss only — other loss functions (MSE, MAE) may give different rankings',
        'r² is a noisy proxy for true latent variance',
        'Quarterly refit for GARCH models — daily refit would be more accurate but prohibitively slow',
        'HAR coefficients fixed from IS — could be updated rolling',
        'Single asset (SPY) — generalization to other assets needs verification',
        f'Block size={MCS_BLOCK_SIZE} chosen by convention — sensitivity to block size not tested',
    ]

    # Save
    out_path = 'experiments/k481_model_confidence_set_results.json'
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n  Results saved to {out_path}")
    print(f"\n{'=' * 70}")
    print(f"CONCLUSION: {results['conclusion']}")
    print(f"{'=' * 70}")

    return results


if __name__ == '__main__':
    main()
