#!/usr/bin/env python3
"""
K497: Loss Function Sensitivity — Model Ranking Stability Across Loss Functions
================================================================================
72 experiments almost exclusively use QLIKE. But different loss functions have
different properties:
  - QLIKE: penalizes underestimation more; robust to imperfect proxies (Patton 2011)
  - MSE: penalizes large errors (squared); sensitive to outliers
  - MAE: more robust; linear penalty
  - HMSE: heteroscedastic MSE = MSE on standardized errors; scale-free
  - HMAE: heteroscedastic MAE = MAE on standardized errors; scale-free

Research Question: Does model ranking change when we use different loss functions?
If rankings are stable across loss functions, QLIKE-based conclusions are robust.
If rankings shift, we need to be cautious about loss-function dependency.

Design:
  - 8 models (K481 MCS candidate set + excluded models)
  - 5 loss functions (QLIKE, MSE, MAE, HMSE, HMAE)
  - SPY, OOS 2023-2025
  - Spearman rank correlation across loss functions
  - MCS with each loss → do superior sets differ?
  - Identify "universally good" vs "loss-sensitive" models

References:
  - Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies"
    J Econometrics 160:99-109 — Shows QLIKE/MSE robust to noisy proxies
  - Hansen, Lunde, Nason (2011) "The Model Confidence Set" Econometrica 79(2):453-497
  - Bollerslev, Patton, Quaedvlieg (2016) Exploiting the errors: A simple approach
    for improved volatility forecasting — loss function comparison
  - Laurent, Rombouts, Violante (2012) On the forecasting accuracy of multivariate
    GARCH models — MCS with multiple loss functions

Data: yfinance (SPY), 2004-2026
Models: GJR-GARCH, GARCH, EGARCH, HAR log-range, Semivariance, EWMA,
        Equal-weight ensemble, Rolling 21d
Author: [Proposed: User, Executed: Claude]
Date: 2026-03-26
"""

import json
import warnings
import time
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
MCS_BLOCK_SIZE = 10
EWMA_LAMBDA = 0.94
ROLLING_WINDOW = 21
REFIT_INTERVAL = 63  # quarterly

print("=" * 70)
print("K497: Loss Function Sensitivity — Model Ranking Across 5 Loss Functions")
print("  Patton (2011) + Hansen et al. (2011) MCS")
print("  8 models × 5 losses = 40 rankings")
print("=" * 70)

# ============================================================
# Loss Functions (Patton 2011)
# ============================================================
def loss_qlike(sigma2, rv):
    """QLIKE: rv/sigma2 - log(rv/sigma2) - 1. Homogeneous of degree 0."""
    ratio = np.clip(rv / sigma2, 1e-10, None)
    return ratio - np.log(ratio) - 1

def loss_mse(sigma2, rv):
    """MSE: (sigma2 - rv)^2. Penalizes large errors."""
    return (sigma2 - rv) ** 2

def loss_mae(sigma2, rv):
    """MAE: |sigma2 - rv|. More robust than MSE."""
    return np.abs(sigma2 - rv)

def loss_hmse(sigma2, rv):
    """HMSE: (rv/sigma2 - 1)^2. Heteroscedastic MSE, scale-free."""
    return (rv / sigma2 - 1) ** 2

def loss_hmae(sigma2, rv):
    """HMAE: |rv/sigma2 - 1|. Heteroscedastic MAE, scale-free."""
    return np.abs(rv / sigma2 - 1)

LOSS_FUNCTIONS = {
    'QLIKE': loss_qlike,
    'MSE': loss_mse,
    'MAE': loss_mae,
    'HMSE': loss_hmse,
    'HMAE': loss_hmae,
}


# ============================================================
# Data Download
# ============================================================
def download_data():
    """Download SPY OHLC data."""
    print("\n[1] Downloading SPY data...")
    df = yf.download(ASSET, start='2004-01-01', end='2026-03-26', auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()

    df['log_return'] = np.log(df['Close'] / df['Close'].shift(1))
    df['r_squared'] = df['log_return'] ** 2
    df['log_range'] = np.log(df['High'] / df['Low'])
    df['parkinson_var'] = df['log_range'] ** 2 / (4 * np.log(2))
    df = df.dropna().copy()

    print(f"  Total observations: {len(df)}")
    print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    return df


# ============================================================
# Rolling Forecast Generation (reuse K481 approach)
# ============================================================
def rolling_forecast_all_models(df):
    """Generate rolling 1-step-ahead forecasts for 8 models over OOS period."""
    print("\n[2] Generating rolling forecasts...")
    t0 = time.time()

    oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
    oos_dates = df.index[oos_mask]

    if len(oos_dates) < 50:
        raise ValueError(f"Only {len(oos_dates)} OOS observations — too few")

    returns_pct = df['log_return'] * 100
    r_squared = df['r_squared'].values
    log_range = df['log_range'].values

    n = len(df)
    all_indices = np.arange(n)
    oos_positions = all_indices[oos_mask]
    first_oos_pos = oos_positions[0]
    is_start = max(0, first_oos_pos - IS_WINDOW)
    is_end = first_oos_pos

    # Initialize forecast storage
    model_names = ['GJR-GARCH', 'GARCH', 'EGARCH', 'HAR_logrange',
                   'Semivar_RS-', 'EWMA', 'EW_Ensemble', 'Rolling_21d']
    forecasts = {m: np.full(len(oos_dates), np.nan) for m in model_names}

    # ---- Fit initial GARCH models on IS ----
    print("  Fitting GJR-GARCH...")
    am_gjr = arch_model(returns_pct.iloc[:is_end], vol='GARCH', p=1, o=1, q=1,
                         dist='t', mean='Constant')
    res_gjr = am_gjr.fit(disp='off', show_warning=False)

    print("  Fitting GARCH(1,1)...")
    am_g = arch_model(returns_pct.iloc[:is_end], vol='GARCH', p=1, q=1,
                       dist='normal', mean='Constant')
    res_g = am_g.fit(disp='off', show_warning=False)

    print("  Fitting EGARCH...")
    am_e = arch_model(returns_pct.iloc[:is_end], vol='EGARCH', p=1, o=1, q=1,
                       dist='normal', mean='Constant')
    res_e = am_e.fit(disp='off', show_warning=False)

    # ---- HAR calibration on IS ----
    is_lr_sq = log_range[is_start:is_end] ** 2
    n_is = len(is_lr_sq)
    y_har = is_lr_sq[21:]
    x1 = is_lr_sq[20:-1]
    x5 = np.array([np.mean(is_lr_sq[j-4:j+1]) for j in range(20, n_is-1)])
    x21 = np.array([np.mean(is_lr_sq[j-20:j+1]) for j in range(20, n_is-1)])
    X_har = np.column_stack([np.ones(len(y_har)), x1, x5, x21])
    try:
        har_coefs = np.linalg.lstsq(X_har, y_har, rcond=None)[0]
    except Exception:
        har_coefs = np.array([np.mean(y_har), 0.3, 0.3, 0.3])

    # Scale ratio: r²/Parkinson for proxy alignment
    is_r2_mean = np.mean(r_squared[is_start:is_end])
    is_park_mean = np.mean(df['parkinson_var'].values[is_start:is_end])
    har_scale_ratio = is_r2_mean / is_park_mean if is_park_mean > 0 else 1.5

    # ---- Semivariance HAR calibration on IS ----
    is_rets = df['log_return'].values[is_start:is_end]
    n_is_sv = len(is_rets)
    sv_y = is_rets[21:] ** 2
    sv_neg5 = np.array([np.sum(is_rets[j-4:j+1][is_rets[j-4:j+1] < 0]**2) for j in range(20, n_is_sv-1)])
    sv_neg21 = np.array([np.sum(is_rets[j-20:j+1][is_rets[j-20:j+1] < 0]**2) for j in range(20, n_is_sv-1)])
    sv_pos5 = np.array([np.sum(is_rets[j-4:j+1][is_rets[j-4:j+1] >= 0]**2) for j in range(20, n_is_sv-1)])
    sv_pos21 = np.array([np.sum(is_rets[j-20:j+1][is_rets[j-20:j+1] >= 0]**2) for j in range(20, n_is_sv-1)])
    X_sv = np.column_stack([np.ones(len(sv_y)), sv_neg5, sv_neg21, sv_pos5, sv_pos21])
    try:
        sv_coefs = np.linalg.lstsq(X_sv, sv_y, rcond=None)[0]
    except Exception:
        sv_coefs = np.array([1e-5, 0.25, 0.25, 0.25, 0.25])

    # ---- EWMA initialization ----
    prev_var_ewma = np.var(df['log_return'].values[is_start:is_end])

    # ---- GARCH state initialization ----
    prev_var_gjr = res_gjr.conditional_volatility.iloc[-1] ** 2
    prev_var_g = res_g.conditional_volatility.iloc[-1] ** 2
    prev_log_var_e = np.log(res_e.conditional_volatility.iloc[-1] ** 2)

    # ---- Rolling forecasts ----
    print(f"  Generating {len(oos_positions)} OOS forecasts...")
    for i, pos in enumerate(oos_positions):
        # Refit GARCH models quarterly
        if i > 0 and i % REFIT_INTERVAL == 0:
            try:
                am2 = arch_model(returns_pct.iloc[max(0, pos-IS_WINDOW):pos],
                                  vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
                res_gjr = am2.fit(disp='off', show_warning=False)
                prev_var_gjr = res_gjr.conditional_volatility.iloc[-1] ** 2
            except Exception:
                pass
            try:
                am2 = arch_model(returns_pct.iloc[max(0, pos-IS_WINDOW):pos],
                                  vol='GARCH', p=1, q=1, dist='normal', mean='Constant')
                res_g = am2.fit(disp='off', show_warning=False)
                prev_var_g = res_g.conditional_volatility.iloc[-1] ** 2
            except Exception:
                pass
            try:
                am2 = arch_model(returns_pct.iloc[max(0, pos-IS_WINDOW):pos],
                                  vol='EGARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
                res_e = am2.fit(disp='off', show_warning=False)
                prev_log_var_e = np.log(res_e.conditional_volatility.iloc[-1] ** 2)
            except Exception:
                pass

        ret_t = returns_pct.iloc[pos - 1]  # most recent return (pct)

        # --- GJR-GARCH ---
        try:
            params = res_gjr.params
            omega = params.get('omega', params.iloc[1])
            alpha = params.get('alpha[1]', params.iloc[2])
            gamma = params.get('gamma[1]', params.iloc[3])
            beta = params.get('beta[1]', params.iloc[4])
            indicator = 1.0 if ret_t < 0 else 0.0
            new_var = omega + (alpha + gamma * indicator) * ret_t**2 + beta * prev_var_gjr
            forecasts['GJR-GARCH'][i] = new_var / 10000
            prev_var_gjr = new_var
        except Exception:
            pass

        # --- GARCH ---
        try:
            params = res_g.params
            omega = params.get('omega', params.iloc[1])
            alpha = params.get('alpha[1]', params.iloc[2])
            beta = params.get('beta[1]', params.iloc[3])
            new_var = omega + alpha * ret_t**2 + beta * prev_var_g
            forecasts['GARCH'][i] = new_var / 10000
            prev_var_g = new_var
        except Exception:
            pass

        # --- EGARCH ---
        try:
            params = res_e.params
            omega_e = params.get('omega', params.iloc[1])
            alpha_e = params.get('alpha[1]', params.iloc[2])
            gamma_e = params.get('gamma[1]', params.iloc[3])
            beta_e = params.get('beta[1]', params.iloc[4])
            std_resid = ret_t / np.exp(prev_log_var_e / 2)
            new_log_var = (omega_e + alpha_e * (np.abs(std_resid) - np.sqrt(2/np.pi))
                           + gamma_e * std_resid + beta_e * prev_log_var_e)
            new_var = np.exp(new_log_var)
            forecasts['EGARCH'][i] = new_var / 10000
            prev_log_var_e = new_log_var
        except Exception:
            pass

        # --- HAR log-range ---
        try:
            lr = log_range[max(0, pos-21):pos]
            lr_sq = lr ** 2
            lr_1d = lr_sq[-1]
            lr_5d = np.mean(lr_sq[-5:]) if len(lr_sq) >= 5 else lr_1d
            lr_21d = np.mean(lr_sq[-21:]) if len(lr_sq) >= 21 else lr_5d
            har_pred = har_coefs[0] + har_coefs[1]*lr_1d + har_coefs[2]*lr_5d + har_coefs[3]*lr_21d
            har_pred = max(har_pred, 1e-10)
            # Convert log-range² to Parkinson variance, then scale to r² level
            har_parkinson = har_pred / (4 * np.log(2))
            forecasts['HAR_logrange'][i] = har_parkinson * har_scale_ratio
        except Exception:
            pass

        # --- Semivariance ---
        try:
            rets = df['log_return'].values[max(0, pos-21):pos]
            neg_rets = rets[rets < 0]
            pos_rets = rets[rets >= 0]
            rs_neg_5 = np.sum(rets[-5:][rets[-5:] < 0] ** 2) if len(rets) >= 5 else 0
            rs_neg_21 = np.sum(neg_rets ** 2) / max(len(rets), 1) * 21
            rs_pos_5 = np.sum(rets[-5:][rets[-5:] >= 0] ** 2) if len(rets) >= 5 else 0
            rs_pos_21 = np.sum(pos_rets ** 2) / max(len(rets), 1) * 21
            sv_pred = (sv_coefs[0] + sv_coefs[1]*rs_neg_5 + sv_coefs[2]*rs_neg_21
                       + sv_coefs[3]*rs_pos_5 + sv_coefs[4]*rs_pos_21)
            forecasts['Semivar_RS-'][i] = max(sv_pred, 1e-10)
        except Exception:
            pass

        # --- EWMA ---
        try:
            ret_dec = df['log_return'].values[pos - 1]
            new_var = EWMA_LAMBDA * prev_var_ewma + (1 - EWMA_LAMBDA) * ret_dec**2
            forecasts['EWMA'][i] = new_var
            prev_var_ewma = new_var
        except Exception:
            pass

        # --- Rolling 21d ---
        try:
            rets_21 = df['log_return'].values[pos-ROLLING_WINDOW:pos]
            forecasts['Rolling_21d'][i] = np.var(rets_21, ddof=1)
        except Exception:
            pass

    # --- Equal-weight ensemble (all 7 models) ---
    arr = np.column_stack([forecasts[m] for m in model_names if m != 'EW_Ensemble'])
    # Equal-weight average where at least 4 models have valid forecasts
    for i in range(len(oos_dates)):
        valid_vals = arr[i][~np.isnan(arr[i]) & (arr[i] > 0)]
        if len(valid_vals) >= 4:
            forecasts['EW_Ensemble'][i] = np.mean(valid_vals)

    forecasts_df = pd.DataFrame(forecasts, index=oos_dates)
    proxy = pd.Series(r_squared[oos_mask], index=oos_dates, name='r_squared')

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s")

    # Report NaN counts
    for m in model_names:
        nan_ct = np.isnan(forecasts[m]).sum()
        if nan_ct > 0:
            print(f"  WARNING: {m} has {nan_ct} NaN forecasts")

    return forecasts_df, proxy


# ============================================================
# Diagnostics
# ============================================================
def run_diagnostics(df):
    """Descriptive statistics for data quality check."""
    print("\n[1b] Data diagnostics...")
    returns = df['log_return']
    diag = {
        'n_obs': len(df),
        'date_range': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'return_mean_bps': round(float(returns.mean() * 10000), 2),
        'return_std_pct': round(float(returns.std() * 100), 4),
        'return_skew': round(float(returns.skew()), 4),
        'return_kurt': round(float(returns.kurtosis()), 2),
        'r2_mean': float(df['r_squared'].mean()),
        'parkinson_mean': float(df['parkinson_var'].mean()),
        'r2_over_parkinson': round(float(df['r_squared'].mean() / df['parkinson_var'].mean()), 3),
    }
    for k, v in diag.items():
        print(f"  {k}: {v}")
    return diag


# ============================================================
# Loss Computation
# ============================================================
def compute_losses_all(forecasts_df, proxy, loss_fn_name, loss_fn):
    """Compute loss for all models under a given loss function."""
    losses = {}
    proxy_vals = proxy.values

    for model in forecasts_df.columns:
        fc = forecasts_df[model].values.copy()
        valid = ~np.isnan(fc) & ~np.isnan(proxy_vals) & (fc > 0) & (proxy_vals > 0)
        if valid.sum() < 50:
            continue
        loss_vals = loss_fn(fc[valid], proxy_vals[valid])
        # Store as full-length with NaN padding
        full = np.full(len(proxy_vals), np.nan)
        full[valid] = loss_vals
        losses[model] = full

    return pd.DataFrame(losses, index=proxy.index)


# ============================================================
# Diebold-Mariano Test
# ============================================================
def dm_test(loss1, loss2):
    """DM test with Newey-West HAC variance."""
    d = loss1 - loss2
    d = d[~np.isnan(d)]
    if len(d) < 30:
        return np.nan, np.nan
    n = len(d)
    d_bar = np.mean(d)
    max_lag = int(np.floor(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    hac_var = gamma_0
    for k in range(1, max_lag + 1):
        weight = 1 - k / (max_lag + 1)
        gamma_k = np.sum((d[k:] - d_bar) * (d[:-k] - d_bar)) / n
        hac_var += 2 * weight * gamma_k
    hac_se = np.sqrt(max(hac_var, 1e-20) / n)
    if hac_se < 1e-15:
        return 0, 1.0
    dm_stat = d_bar / hac_se
    p_value = 2 * (1 - stats.t.cdf(np.abs(dm_stat), df=n-1))
    return float(dm_stat), float(p_value)


# ============================================================
# MCS Wrapper
# ============================================================
def run_mcs(losses_df, alpha=MCS_ALPHA, reps=MCS_BOOTSTRAP_REPS, block_size=MCS_BLOCK_SIZE):
    """Run Hansen-Lunde-Nason MCS. Returns dict or None."""
    valid_cols = losses_df.columns[losses_df.isna().sum() < len(losses_df) * 0.1]
    losses_clean = losses_df[valid_cols].dropna()
    if len(losses_clean) < 50 or len(valid_cols) < 2:
        return None
    mcs = MCS(losses_clean, size=alpha, reps=reps, block_size=block_size,
              method='R', bootstrap='stationary', seed=42)
    mcs.compute()

    pvalues = mcs.pvalues
    included = list(mcs.included)
    excluded = list(mcs.excluded)

    return {
        'included': included,
        'excluded': excluded,
        'pvalues': {k: float(v) for k, v in pvalues['Pvalue'].items()},
        'n_obs': len(losses_clean),
        'n_included': len(included),
        'n_excluded': len(excluded),
    }


# ============================================================
# Main Analysis
# ============================================================
def main():
    start_time = time.time()

    # Step 1: Data
    df = download_data()
    diagnostics = run_diagnostics(df)

    # Step 2: Generate forecasts
    forecasts_df, proxy = rolling_forecast_all_models(df)
    n_oos = len(forecasts_df)
    print(f"\n  OOS observations: {n_oos}")
    print(f"  OOS period: {forecasts_df.index[0].strftime('%Y-%m-%d')} to {forecasts_df.index[-1].strftime('%Y-%m-%d')}")

    models = list(forecasts_df.columns)
    print(f"  Models ({len(models)}): {models}")

    # Step 3: Compute losses under all 5 functions
    print("\n[3] Computing losses under 5 loss functions...")
    all_losses = {}  # loss_name -> DataFrame
    all_mean_losses = {}  # loss_name -> {model: mean_loss}
    all_rankings = {}  # loss_name -> {model: rank}

    for loss_name, loss_fn in LOSS_FUNCTIONS.items():
        losses_df = compute_losses_all(forecasts_df, proxy, loss_name, loss_fn)
        all_losses[loss_name] = losses_df

        # Mean loss per model (lower = better)
        means = losses_df.mean().sort_values()
        all_mean_losses[loss_name] = {m: float(v) for m, v in means.items()}

        # Rank (1 = best)
        ranking = means.rank().astype(int)
        all_rankings[loss_name] = {m: int(ranking[m]) for m in ranking.index}

        print(f"\n  {loss_name} ranking:")
        for rank_pos, (model, val) in enumerate(means.items(), 1):
            print(f"    {rank_pos}. {model}: {val:.8f}")

    # Step 4: Cross-loss rank correlation (Spearman)
    print("\n[4] Cross-loss Spearman rank correlations...")
    loss_names = list(LOSS_FUNCTIONS.keys())
    rank_matrix = pd.DataFrame(all_rankings).reindex(models)  # models × losses
    # Fill NaN with worst rank for missing models
    rank_matrix = rank_matrix.fillna(len(models))

    corr_matrix = {}
    for l1 in loss_names:
        corr_matrix[l1] = {}
        for l2 in loss_names:
            r1 = rank_matrix[l1].values
            r2 = rank_matrix[l2].values
            valid = ~np.isnan(r1) & ~np.isnan(r2)
            if valid.sum() >= 3:
                rho, pval = stats.spearmanr(r1[valid], r2[valid])
                corr_matrix[l1][l2] = round(float(rho), 4)
            else:
                corr_matrix[l1][l2] = None

    print("\n  Spearman rank correlation matrix:")
    print(f"  {'':>8s}", end='')
    for l in loss_names:
        print(f"  {l:>7s}", end='')
    print()
    for l1 in loss_names:
        print(f"  {l1:>8s}", end='')
        for l2 in loss_names:
            val = corr_matrix[l1][l2]
            if val is not None:
                print(f"  {val:>7.3f}", end='')
            else:
                print(f"  {'N/A':>7s}", end='')
        print()

    # Step 5: MCS under each loss function
    print("\n[5] Running MCS under each loss function (alpha=0.10)...")
    mcs_results = {}
    for loss_name in loss_names:
        print(f"\n  MCS with {loss_name} loss...")
        losses_df = all_losses[loss_name]
        result = run_mcs(losses_df)
        if result:
            mcs_results[loss_name] = result
            print(f"    Superior set ({result['n_included']}): {sorted(result['included'])}")
            print(f"    Excluded ({result['n_excluded']}): {sorted(result['excluded'])}")
        else:
            print("    MCS failed (insufficient data)")
            mcs_results[loss_name] = None

    # Step 6: Identify universally good/bad models
    print("\n[6] Universal model assessment...")
    model_rank_summary = {}
    for m in models:
        ranks = []
        in_mcs_count = 0
        for ln in loss_names:
            if m in all_rankings[ln]:
                ranks.append(all_rankings[ln][m])
            if mcs_results.get(ln) and m in mcs_results[ln].get('included', []):
                in_mcs_count += 1

        model_rank_summary[m] = {
            'mean_rank': round(float(np.mean(ranks)), 2) if ranks else None,
            'rank_std': round(float(np.std(ranks)), 2) if ranks else None,
            'min_rank': int(np.min(ranks)) if ranks else None,
            'max_rank': int(np.max(ranks)) if ranks else None,
            'rank_range': int(np.max(ranks) - np.min(ranks)) if ranks else None,
            'ranks_by_loss': {ln: all_rankings[ln].get(m) for ln in loss_names},
            'in_mcs_count': in_mcs_count,
            'in_mcs_fraction': round(in_mcs_count / len(loss_names), 2),
        }

    print(f"\n  {'Model':<16s} {'MeanRank':>9s} {'RankStd':>8s} {'Range':>6s} {'MCS_frac':>9s}")
    print("  " + "-" * 52)
    sorted_models = sorted(model_rank_summary.items(), key=lambda x: x[1]['mean_rank'] or 99)
    for m, info in sorted_models:
        mr = info['mean_rank'] if info['mean_rank'] else 'N/A'
        rs = info['rank_std'] if info['rank_std'] else 'N/A'
        rr = info['rank_range'] if info['rank_range'] else 'N/A'
        mf = info['in_mcs_fraction']
        print(f"  {m:<16s} {mr:>9} {rs:>8} {rr:>6} {mf:>9.2f}")

    # Step 7: DM tests — best model vs second-best under each loss
    print("\n[7] DM tests: Best vs 2nd-best under each loss...")
    dm_results = {}
    for loss_name in loss_names:
        losses_df = all_losses[loss_name]
        means = losses_df.mean().sort_values()
        if len(means) < 2:
            continue
        best = means.index[0]
        second = means.index[1]
        dm_stat, dm_pval = dm_test(losses_df[best].values, losses_df[second].values)
        dm_results[loss_name] = {
            'best': best,
            'second': second,
            'dm_stat': round(dm_stat, 4) if not np.isnan(dm_stat) else None,
            'dm_pval': round(dm_pval, 4) if not np.isnan(dm_pval) else None,
            'significant_5pct': dm_pval < 0.05 if not np.isnan(dm_pval) else None,
        }
        sig = '***' if dm_pval < 0.01 else ('**' if dm_pval < 0.05 else ('*' if dm_pval < 0.10 else ''))
        print(f"  {loss_name}: {best} vs {second} — DM={dm_stat:.3f}, p={dm_pval:.4f} {sig}")

    # Step 8: Pairwise model comparison across losses
    print("\n[8] Pairwise win-count matrix (how many loss functions model A beats model B)...")
    win_matrix = {}
    for m1 in models:
        win_matrix[m1] = {}
        for m2 in models:
            if m1 == m2:
                win_matrix[m1][m2] = '-'
                continue
            wins = 0
            for ln in loss_names:
                r1 = all_rankings[ln].get(m1, 99)
                r2 = all_rankings[ln].get(m2, 99)
                if r1 < r2:
                    wins += 1
            win_matrix[m1][m2] = wins

    # Summary: total wins across all losses
    total_wins = {}
    for m in models:
        tw = sum(v for k, v in win_matrix[m].items() if isinstance(v, int))
        total_wins[m] = tw

    # Step 9: Categorize loss functions
    print("\n[9] Loss function categorization...")
    # Patton (2011) classes: homogeneous (QLIKE, HMSE, HMAE) vs non-homogeneous (MSE, MAE)
    homo_losses = ['QLIKE', 'HMSE', 'HMAE']
    nonhomo_losses = ['MSE', 'MAE']

    # Average rank correlation within and between classes
    homo_corrs = []
    for l1 in homo_losses:
        for l2 in homo_losses:
            if l1 != l2 and corr_matrix[l1][l2] is not None:
                homo_corrs.append(corr_matrix[l1][l2])

    nonhomo_corrs = []
    for l1 in nonhomo_losses:
        for l2 in nonhomo_losses:
            if l1 != l2 and corr_matrix[l1][l2] is not None:
                nonhomo_corrs.append(corr_matrix[l1][l2])

    cross_corrs = []
    for l1 in homo_losses:
        for l2 in nonhomo_losses:
            if corr_matrix[l1][l2] is not None:
                cross_corrs.append(corr_matrix[l1][l2])

    patton_analysis = {
        'homogeneous_losses': homo_losses,
        'non_homogeneous_losses': nonhomo_losses,
        'within_homo_avg_rho': round(float(np.mean(homo_corrs)), 4) if homo_corrs else None,
        'within_nonhomo_avg_rho': round(float(np.mean(nonhomo_corrs)), 4) if nonhomo_corrs else None,
        'cross_class_avg_rho': round(float(np.mean(cross_corrs)), 4) if cross_corrs else None,
    }

    print(f"  Homogeneous (QLIKE, HMSE, HMAE) within-class avg rho: {patton_analysis['within_homo_avg_rho']}")
    print(f"  Non-homogeneous (MSE, MAE) within-class avg rho: {patton_analysis['within_nonhomo_avg_rho']}")
    print(f"  Cross-class avg rho: {patton_analysis['cross_class_avg_rho']}")

    # Step 10: MCS intersection — models in ALL superior sets
    print("\n[10] MCS intersection analysis...")
    all_superior_sets = []
    for ln in loss_names:
        if mcs_results.get(ln):
            all_superior_sets.append(set(mcs_results[ln]['included']))

    if all_superior_sets:
        universal_superior = set.intersection(*all_superior_sets)
        any_superior = set.union(*all_superior_sets)
        never_superior = set(models) - any_superior
    else:
        universal_superior = set()
        any_superior = set()
        never_superior = set(models)

    print(f"  In ALL superior sets: {sorted(universal_superior) if universal_superior else 'None'}")
    print(f"  In ANY superior set: {sorted(any_superior) if any_superior else 'None'}")
    print(f"  NEVER in superior set: {sorted(never_superior) if never_superior else 'None'}")

    elapsed = time.time() - start_time

    # ============================================================
    # Conclusions
    # ============================================================
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)

    # Overall avg Spearman
    all_rhos = []
    for l1 in loss_names:
        for l2 in loss_names:
            if l1 < l2 and corr_matrix[l1][l2] is not None:
                all_rhos.append(corr_matrix[l1][l2])
    avg_rho = np.mean(all_rhos) if all_rhos else None

    if avg_rho and avg_rho > 0.85:
        stability = "HIGHLY STABLE"
        stability_detail = "Rankings very consistent across loss functions — QLIKE conclusions robust"
    elif avg_rho and avg_rho > 0.7:
        stability = "MODERATELY STABLE"
        stability_detail = "Rankings mostly consistent but some sensitivity exists"
    elif avg_rho and avg_rho > 0.5:
        stability = "SOMEWHAT SENSITIVE"
        stability_detail = "Rankings change meaningfully with loss function — interpret QLIKE results with caution"
    else:
        stability = "HIGHLY SENSITIVE"
        stability_detail = "Rankings strongly depend on loss function — QLIKE-only conclusions unreliable"

    print(f"\n  Average pairwise Spearman rho: {avg_rho:.4f}")
    print(f"  Stability verdict: {stability}")
    print(f"  {stability_detail}")

    if universal_superior:
        print(f"\n  Universally superior models: {sorted(universal_superior)}")
    if never_superior:
        print(f"  Universally inferior models: {sorted(never_superior)}")

    print(f"\n  Total elapsed: {elapsed:.1f}s")

    # ============================================================
    # Save results
    # ============================================================
    results = {
        'experiment_id': 'K497',
        'title': 'Loss Function Sensitivity — Model Ranking Stability Across 5 Loss Functions',
        'date': datetime.now(timezone.utc).isoformat(),
        'references': [
            'Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies" J Econometrics 160:99-109',
            'Hansen, Lunde, Nason (2011) "The Model Confidence Set" Econometrica 79(2):453-497',
            'Bollerslev, Patton, Quaedvlieg (2016) Exploiting the errors — loss function comparison',
            'Laurent, Rombouts, Violante (2012) MCS with multiple loss functions',
            'K481 — Model Confidence Set baseline (QLIKE only)',
            'K495 — Unified vol guide (QLIKE-based conclusions)',
        ],
        'method': {
            'loss_functions': list(LOSS_FUNCTIONS.keys()),
            'loss_descriptions': {
                'QLIKE': 'rv/σ² - log(rv/σ²) - 1 (degree-0 homogeneous, Patton 2011)',
                'MSE': '(σ² - rv)² (penalizes large errors)',
                'MAE': '|σ² - rv| (robust)',
                'HMSE': '(rv/σ² - 1)² (standardized MSE, scale-free)',
                'HMAE': '|rv/σ² - 1| (standardized MAE, scale-free)',
            },
            'mcs': f'Hansen-Lunde-Nason MCS, alpha={MCS_ALPHA}, reps={MCS_BOOTSTRAP_REPS}, block={MCS_BLOCK_SIZE}',
            'proxy': 'r² (close-to-close squared return)',
            'oos_period': f'{OOS_START} to {OOS_END}',
            'refit_interval': f'{REFIT_INTERVAL} days (quarterly)',
            'is_window': IS_WINDOW,
        },
        'asset': ASSET,
        'data_source': 'yfinance',
        'diagnostics': diagnostics,
        'n_oos': n_oos,
        'models': models,
        'mean_losses': all_mean_losses,
        'rankings': all_rankings,
        'spearman_correlation_matrix': corr_matrix,
        'average_pairwise_spearman': round(float(avg_rho), 4) if avg_rho else None,
        'stability_verdict': stability,
        'stability_detail': stability_detail,
        'mcs_results': {
            ln: (r if r else None)
            for ln, r in mcs_results.items()
        },
        'mcs_intersection': {
            'universal_superior': sorted(list(universal_superior)),
            'in_any_superior': sorted(list(any_superior)),
            'never_superior': sorted(list(never_superior)),
        },
        'model_rank_summary': model_rank_summary,
        'dm_best_vs_second': dm_results,
        'pairwise_total_wins': total_wins,
        'patton_loss_class_analysis': patton_analysis,
        'conclusions': {
            'ranking_stability': stability,
            'avg_spearman_rho': round(float(avg_rho), 4) if avg_rho else None,
            'universal_superior_models': sorted(list(universal_superior)),
            'universal_inferior_models': sorted(list(never_superior)),
            'qlike_robustness': stability in ['HIGHLY STABLE', 'MODERATELY STABLE'],
            'implication_for_K495': (
                'QLIKE-based unified guide conclusions are robust'
                if stability in ['HIGHLY STABLE', 'MODERATELY STABLE']
                else 'QLIKE-based conclusions may need revision under alternative loss functions'
            ),
        },
        'elapsed_seconds': round(elapsed, 1),
    }

    out_path = 'experiments/k497_loss_sensitivity_results.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == '__main__':
    main()
