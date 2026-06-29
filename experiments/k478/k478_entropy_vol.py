#!/usr/bin/env python3
"""
K478: Entropy-Based Volatility Prediction (Jump Exploration)

Literature:
  - Pincus (1991) "Approximate entropy as a measure of system complexity" PNAS
  - Richman & Moorman (2000) "Sample entropy" Am J Physiol Heart Circ
  - Bandt & Pompe (2002) "Permutation entropy" Physical Review Letters
  - Stosic et al. (2019) "Multifractal analysis of managed and independent float
    exchange rates" Physica A

Prior results:
  - T22: MI(sign(SPY)×VIX) = 0.148 > VIX alone 0.146 → leverage effect
  - T22: Transfer Entropy VIX→SPY vol = 0.12 nats
  - K192/J3: Attention features failed OOS despite strong IS
  - Complexity Ceiling: most features add noise, not signal

Research Questions:
  1. Does market "complexity" (entropy) predict future vol?
  2. Low entropy (high predictability) → trending → low vol?
  3. High entropy (high randomness) → chaos → high vol?
  4. Does entropy provide incremental info beyond VIX?

Entropy Methods:
  1. Sample Entropy (SampEn) — template matching complexity
  2. Permutation Entropy (PE) — ordinal pattern complexity (Bandt & Pompe 2002)
  3. Shannon Entropy of returns distribution — distributional complexity

Asset: SPY
Features: rolling 21-day entropy measures (lagged 1 day)
OOS: 2023-01-01 to 2025-12-31
Models:
  1. Baseline: lagged RV21
  2. + SampEn
  3. + PE
  4. + Shannon Entropy
  5. + All three entropy features
  6. VIX only (control)
  7. VIX + All three entropy features

Evaluation: QLIKE, MSE, DM test
Refs: Pincus (1991), Bandt & Pompe (2002), Richman & Moorman (2000)
"""

import json
import warnings
import time
import math
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
OOS_START = '2023-01-01'
DATA_START = '2005-01-01'
DATA_END = '2026-01-01'
ASSET = 'SPY'
WINDOW = 21  # rolling window for entropy
HORIZON = 21  # forward realized-variance target horizon
N_BINS_SHANNON = 20  # bins for Shannon entropy
SAMPEN_R_MULT = 0.2
MIN_TRAINING_WINDOW = 504
DM_HAC_LAG = HORIZON
OUT_DIR = Path(__file__).resolve().parent

# ============================================================
# Entropy Functions
# ============================================================

def sample_entropy(x, m=2, r_mult=0.3):
    """
    Sample Entropy (SampEn) — Richman & Moorman (2000)

    Measures the negative natural log of the conditional probability that
    two sequences similar for m points remain similar at m+1 points.

    Parameters:
        x: 1D array of values
        m: embedding dimension (template length)
        r_mult: tolerance as fraction of std(x). Use 0.3 for short windows (N~21)
                to ensure sufficient template matches (Richman recommends 0.1-0.25
                for long series; wider tolerance needed for short windows)

    Returns:
        SampEn value (higher = more complex/random)
    """
    N = len(x)
    if N < m + 2:
        return np.nan

    r = r_mult * np.std(x, ddof=1)
    if r == 0:
        return np.nan

    # Count template matches for m and m+1
    def count_matches(template_len):
        count = 0
        templates = np.array([x[i:i+template_len] for i in range(N - template_len)])
        n_templates = len(templates)
        for i in range(n_templates):
            # Chebyshev distance (max absolute difference)
            dists = np.max(np.abs(templates[i+1:] - templates[i]), axis=1)
            count += np.sum(dists <= r)
        return count

    A = count_matches(m + 1)
    B = count_matches(m)

    if B == 0:
        return np.nan

    return -np.log(A / B) if A > 0 else np.nan


def permutation_entropy(x, order=3, delay=1, normalize=True):
    """
    Permutation Entropy (PE) — Bandt & Pompe (2002)

    Based on the relative ordering of values in embedded vectors.
    Very fast (O(n)), robust to noise, invariant to monotonic transformations.

    Parameters:
        x: 1D array of values
        order: embedding dimension (order of permutation)
        delay: time delay between elements
        normalize: if True, normalize by log2(order!)

    Returns:
        PE value (higher = more complex/random)
    """
    N = len(x)
    n_patterns = N - (order - 1) * delay
    if n_patterns < 1:
        return np.nan

    # Extract ordinal patterns
    patterns = []
    for i in range(n_patterns):
        window = x[i:i + order * delay:delay]
        pattern = tuple(np.argsort(window))
        patterns.append(pattern)

    # Count pattern frequencies
    counts = Counter(patterns)
    probs = np.array(list(counts.values()), dtype=float) / len(patterns)

    # Shannon entropy of the pattern distribution
    pe = -np.sum(probs * np.log2(probs))

    if normalize:
        max_entropy = np.log2(math.factorial(order))
        pe = pe / max_entropy if max_entropy > 0 else np.nan

    return pe


def shannon_entropy_returns(returns, n_bins=20):
    """
    Shannon Entropy of returns distribution

    Measures the information content / uncertainty of the return distribution.
    Higher entropy = more uniform distribution = less predictable.

    Parameters:
        returns: 1D array of returns
        n_bins: number of histogram bins

    Returns:
        Shannon entropy in bits
    """
    if len(returns) < n_bins:
        return np.nan

    # Use density=True to get proper probability density
    hist, bin_edges = np.histogram(returns, bins=n_bins, density=True)
    bin_width = bin_edges[1] - bin_edges[0]

    # Convert density to probabilities
    probs = hist * bin_width
    probs = probs[probs > 0]

    if len(probs) == 0:
        return np.nan

    return -np.sum(probs * np.log2(probs))


# ============================================================
# Rolling Entropy Computation
# ============================================================

def compute_rolling_entropy(returns, window=21, n_bins=20):
    """
    Compute rolling entropy measures for a return series.
    Returns DataFrame with columns: sampen, pe, shannon
    """
    n = len(returns)
    sampen_arr = np.full(n, np.nan)
    pe_arr = np.full(n, np.nan)
    shannon_arr = np.full(n, np.nan)

    start_time = time.time()
    report_every = 1000

    for i in range(window - 1, n):
        w = returns[i - window + 1:i + 1]

        # Skip windows with NaN
        if np.any(np.isnan(w)):
            continue

        # Sample Entropy (m=2, r=0.2*std)
        sampen_arr[i] = sample_entropy(w, m=2, r_mult=SAMPEN_R_MULT)

        # Permutation Entropy (order=3, delay=1)
        pe_arr[i] = permutation_entropy(w, order=3, delay=1, normalize=True)

        # Shannon Entropy
        shannon_arr[i] = shannon_entropy_returns(w, n_bins=n_bins)

        if (i - window + 2) % report_every == 0:
            elapsed = time.time() - start_time
            pct = (i - window + 2) / (n - window + 1) * 100
            print(f"  Rolling entropy: {pct:.0f}% done ({elapsed:.1f}s)")

    elapsed = time.time() - start_time
    print(f"  Rolling entropy complete: {elapsed:.1f}s for {n - window + 1} windows")

    return pd.DataFrame({
        'sampen': sampen_arr,
        'pe': pe_arr,
        'shannon': shannon_arr
    })


# ============================================================
# Evaluation Functions
# ============================================================

def qlike(realized, forecast):
    """QLIKE loss: RV/forecast - log(RV/forecast) - 1"""
    ratio = realized / forecast
    valid = (realized > 0) & (forecast > 0) & np.isfinite(ratio)
    r = ratio[valid]
    return np.mean(r - np.log(r) - 1)


def mse_loss(realized, forecast):
    """Mean Squared Error"""
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return np.mean((realized[valid] - forecast[valid]) ** 2)


def dm_test(loss1, loss2, hac_lag=DM_HAC_LAG):
    """
    Diebold-Mariano test with Newey-West HAC standard error.

    H0: equal predictive accuracy
    d_t = loss1_t - loss2_t, so positive t-stat means model 2 has
    lower average loss than model 1.
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan, np.nan

    d_mean = np.mean(d)
    centered = d - d_mean
    gamma0 = np.mean(centered * centered)
    long_run_var = gamma0
    max_lag = min(int(hac_lag), n - 1)

    for k in range(1, max_lag + 1):
        gamma_k = np.mean(centered[k:] * centered[:-k])
        weight = 1 - k / (max_lag + 1)
        long_run_var += 2 * weight * gamma_k

    long_run_var = max(long_run_var, 1e-20)
    dm_stat = d_mean / np.sqrt(long_run_var / n)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return dm_stat, p_value, d_mean


def align_losses(result_a, result_b, loss_key):
    """
    Align model loss arrays by forecast date before pairwise comparison.
    """
    losses_a = dict(zip(result_a['loss_dates'], result_a[loss_key]))
    losses_b = dict(zip(result_b['loss_dates'], result_b[loss_key]))
    common_dates = sorted(set(losses_a).intersection(losses_b))
    a = np.array([losses_a[d] for d in common_dates], dtype=float)
    b = np.array([losses_b[d] for d in common_dates], dtype=float)
    return a, b, common_dates


def expanding_ols_forecast_panel(data, feature_cols, target_col, oos_start,
                                 horizon=HORIZON, min_window=MIN_TRAINING_WINDOW):
    """
    Expanding-window OLS forecast with forward-label embargo.

    For a forecast origin at row i, a training row j is eligible only when
    j + horizon < i, so the training target's last realized return is known
    before the forecast origin.
    """
    X_all = data[feature_cols].to_numpy(dtype=float)
    y_all = data[target_col].to_numpy(dtype=float)
    idx = data.index
    positions = np.arange(len(data))
    oos_positions = np.where(idx >= pd.Timestamp(oos_start))[0]

    finite_X = np.all(np.isfinite(X_all), axis=1)
    finite_y = np.isfinite(y_all)

    forecasts = []
    realized = []
    dates = []
    train_counts = []

    for pos in oos_positions:
        if not finite_y[pos] or not finite_X[pos]:
            continue

        train_mask = finite_X & finite_y & ((positions + horizon) < pos)
        n_train = int(train_mask.sum())
        if n_train < min_window:
            continue

        Xv = X_all[train_mask]
        yv = y_all[train_mask]
        Xv_c = np.column_stack([np.ones(n_train), Xv])

        try:
            beta = np.linalg.lstsq(Xv_c, yv, rcond=None)[0]
            x_new = np.concatenate([[1.0], X_all[pos]])
            pred = x_new @ beta
            forecasts.append(max(float(pred), 1e-8))
            realized.append(float(y_all[pos]))
            dates.append(idx[pos].strftime('%Y-%m-%d'))
            train_counts.append(n_train)
        except Exception:
            continue

    return {
        'forecast': np.array(forecasts, dtype=float),
        'realized': np.array(realized, dtype=float),
        'dates': dates,
        'train_counts': train_counts,
        'n_valid': int(len(forecasts)),
        'n_total': int(len(oos_positions)),
        'first_forecast_date': dates[0] if dates else None,
        'last_forecast_date': dates[-1] if dates else None,
        'min_train_count': int(min(train_counts)) if train_counts else None,
        'max_train_count': int(max(train_counts)) if train_counts else None,
    }


# ============================================================
# Main
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K478: Entropy-Based Volatility Prediction")
    print("=" * 70)

    # ----------------------------------------------------------
    # 1. Data Download
    # ----------------------------------------------------------
    print("\n[1] Downloading data...")
    spy = yf.download(ASSET, start=DATA_START, end=DATA_END, progress=False)
    vix = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)

    # Handle MultiIndex columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    print(f"  SPY: {len(spy)} rows, {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
    print(f"  VIX: {len(vix)} rows")

    # ----------------------------------------------------------
    # 2. Feature Engineering
    # ----------------------------------------------------------
    print("\n[2] Computing features...")

    # Returns
    spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
    spy['ret2'] = spy['ret'] ** 2

    # Realized Variance (21-day)
    spy['rv21'] = spy['ret2'].rolling(window=21).sum()

    # Forward realized variance target: sum of squared returns t+1 ... t+21.
    spy['rv21_fwd'] = sum(spy['ret2'].shift(-i) for i in range(1, HORIZON + 1))

    # Lagged RV (predictor)
    spy['rv21_lag'] = spy['rv21'].shift(1)

    # VIX (as annualized implied vol → daily variance)
    spy['vix'] = vix['Close'].reindex(spy.index, method='ffill')
    spy['vix_var'] = (spy['vix'] / 100) ** 2 / 252  # daily implied variance
    spy['vix_lag'] = spy['vix_var'].shift(1)

    # ----------------------------------------------------------
    # 3. Compute Rolling Entropy Measures
    # ----------------------------------------------------------
    print("\n[3] Computing rolling entropy measures (window=21)...")

    returns = spy['ret'].values
    entropy_df = compute_rolling_entropy(returns, window=WINDOW, n_bins=N_BINS_SHANNON)

    spy['sampen'] = entropy_df['sampen'].values
    spy['pe'] = entropy_df['pe'].values
    spy['shannon'] = entropy_df['shannon'].values

    # Lag all entropy features by 1 day (no look-ahead)
    spy['sampen_lag'] = spy['sampen'].shift(1)
    spy['pe_lag'] = spy['pe'].shift(1)
    spy['shannon_lag'] = spy['shannon'].shift(1)

    # ----------------------------------------------------------
    # 4. Descriptive Statistics
    # ----------------------------------------------------------
    print("\n[4] Descriptive Statistics of Entropy Measures...")

    desc_cols = ['sampen', 'pe', 'shannon']
    desc_stats = {}
    for col in desc_cols:
        s = spy[col].dropna()
        desc_stats[col] = {
            'count': int(len(s)),
            'mean': float(s.mean()),
            'std': float(s.std()),
            'min': float(s.min()),
            'q25': float(s.quantile(0.25)),
            'median': float(s.median()),
            'q75': float(s.quantile(0.75)),
            'max': float(s.max()),
            'skew': float(s.skew()),
            'kurtosis': float(s.kurtosis()),
            'nan_pct': float(spy[col].isna().mean() * 100)
        }
        print(f"\n  {col}:")
        for k, v in desc_stats[col].items():
            print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")

    # Correlation with future RV
    print("\n  Correlation with forward RV21:")
    for col in ['sampen_lag', 'pe_lag', 'shannon_lag', 'rv21_lag', 'vix_lag']:
        valid = spy[[col, 'rv21_fwd']].dropna()
        if len(valid) > 100:
            r, p = stats.pearsonr(valid[col], valid['rv21_fwd'])
            rho, rho_p = stats.spearmanr(valid[col], valid['rv21_fwd'])
            print(f"    {col}: Pearson r={r:.4f} (p={p:.4e}), Spearman rho={rho:.4f} (p={rho_p:.4e})")

    # ----------------------------------------------------------
    # 5. Split IS/OOS
    # ----------------------------------------------------------
    print(f"\n[5] Splitting data at {OOS_START}...")

    oos_mask = spy.index >= OOS_START
    spy_is = spy[~oos_mask].copy()
    spy_oos = spy[oos_mask].copy()

    print(f"  IS: {len(spy_is)} rows ({spy_is.index[0].strftime('%Y-%m-%d')} to {spy_is.index[-1].strftime('%Y-%m-%d')})")
    print(f"  OOS: {len(spy_oos)} rows ({spy_oos.index[0].strftime('%Y-%m-%d')} to {spy_oos.index[-1].strftime('%Y-%m-%d')})")

    # ----------------------------------------------------------
    # 6. Model Estimation & OOS Forecast
    # ----------------------------------------------------------
    print("\n[6] Running expanding window OLS forecasts...")

    # Target: forward RV21
    target = 'rv21_fwd'

    # Define models
    models = {
        'M1_baseline': ['rv21_lag'],
        'M2_sampen': ['rv21_lag', 'sampen_lag'],
        'M3_pe': ['rv21_lag', 'pe_lag'],
        'M4_shannon': ['rv21_lag', 'shannon_lag'],
        'M5_all_entropy': ['rv21_lag', 'sampen_lag', 'pe_lag', 'shannon_lag'],
        'M6_vix': ['vix_lag'],
        'M7_vix_entropy': ['vix_lag', 'sampen_lag', 'pe_lag', 'shannon_lag'],
    }

    forecasts = {}

    for model_name, feature_cols in models.items():
        print(f"\n  {model_name} ({feature_cols})...")

        forecasts[model_name] = expanding_ols_forecast_panel(
            spy,
            feature_cols,
            target,
            OOS_START,
            horizon=HORIZON,
            min_window=MIN_TRAINING_WINDOW,
        )
        print(f"    Valid forecasts: {forecasts[model_name]['n_valid']}/{forecasts[model_name]['n_total']}")

    # ----------------------------------------------------------
    # 7. Evaluation
    # ----------------------------------------------------------
    print("\n[7] Evaluation Results...")
    print("=" * 70)

    results = {}
    baseline_key = 'M1_baseline'

    for model_name, fdata in forecasts.items():
        realized = fdata['realized']
        forecast = fdata['forecast']

        q = qlike(realized, forecast)
        m = mse_loss(realized, forecast)

        # QLIKE individual losses for DM test
        ratio = realized / forecast
        valid = (realized > 0) & (forecast > 0) & np.isfinite(ratio)
        qlike_losses = (ratio[valid] - np.log(ratio[valid]) - 1)
        mse_losses = (realized[valid] - forecast[valid]) ** 2

        results[model_name] = {
            'qlike': float(q),
            'mse': float(m),
            'n_obs': int(fdata['n_valid']),
            'n_total': int(fdata['n_total']),
            'first_forecast_date': fdata['first_forecast_date'],
            'last_forecast_date': fdata['last_forecast_date'],
            'min_train_count': fdata['min_train_count'],
            'max_train_count': fdata['max_train_count'],
            'qlike_losses': qlike_losses,
            'mse_losses': mse_losses,
            'loss_dates': np.array(fdata['dates'])[valid].tolist(),
        }
        print(f"\n  {model_name}: QLIKE={q:.6f}, MSE={m:.4e}, n={fdata['n_valid']}")

    # DM tests vs baseline
    print("\n  DM Tests vs Baseline (M1_baseline):")
    print("  " + "-" * 60)

    dm_results = {}
    for model_name in models:
        if model_name == baseline_key:
            continue

        base_ql, model_ql, common_q_dates = align_losses(
            results[baseline_key],
            results[model_name],
            'qlike_losses',
        )
        base_ml, model_ml, common_m_dates = align_losses(
            results[baseline_key],
            results[model_name],
            'mse_losses',
        )

        dm_q, p_q, mean_d_q = dm_test(base_ql, model_ql, hac_lag=DM_HAC_LAG)
        dm_m, p_m, mean_d_m = dm_test(base_ml, model_ml, hac_lag=DM_HAC_LAG)

        base_common_qlike = float(np.mean(base_ql)) if len(base_ql) else np.nan
        model_common_qlike = float(np.mean(model_ql)) if len(model_ql) else np.nan
        qlike_gain = (
            (model_common_qlike - base_common_qlike) / abs(base_common_qlike) * 100
            if np.isfinite(base_common_qlike) and base_common_qlike != 0
            else np.nan
        )

        dm_results[model_name] = {
            'dm_qlike_t': float(dm_q) if np.isfinite(dm_q) else None,
            'dm_qlike_p': float(p_q) if np.isfinite(p_q) else None,
            'dm_qlike_mean_loss_diff': float(mean_d_q) if np.isfinite(mean_d_q) else None,
            'dm_mse_t': float(dm_m) if np.isfinite(dm_m) else None,
            'dm_mse_p': float(p_m) if np.isfinite(p_m) else None,
            'dm_mse_mean_loss_diff': float(mean_d_m) if np.isfinite(mean_d_m) else None,
            'qlike_gain_pct': float(qlike_gain),
            'baseline_common_qlike': base_common_qlike,
            'challenger_common_qlike': model_common_qlike,
            'common_n_qlike': int(len(common_q_dates)),
            'common_n_mse': int(len(common_m_dates)),
            'common_start': common_q_dates[0] if common_q_dates else None,
            'common_end': common_q_dates[-1] if common_q_dates else None,
            'dm_hac_lag': DM_HAC_LAG,
            'loss_diff_convention': 'baseline_loss_minus_challenger_loss; positive t means challenger lower loss',
        }

        sig_q = "***" if (p_q or 1) < 0.01 else "**" if (p_q or 1) < 0.05 else "*" if (p_q or 1) < 0.10 else ""
        sig_m = "***" if (p_m or 1) < 0.01 else "**" if (p_m or 1) < 0.05 else "*" if (p_m or 1) < 0.10 else ""

        print(f"    {model_name}: QLIKE gain={qlike_gain:+.3f}%, DM_q t={dm_q:.3f}{sig_q} (p={p_q:.4f}), "
              f"DM_m t={dm_m:.3f}{sig_m} (p={p_m:.4f})")

    # ----------------------------------------------------------
    # 8. IS Regression Analysis (full sample for diagnostics)
    # ----------------------------------------------------------
    print("\n[8] Full IS Regression Analysis...")

    is_regression = {}
    for model_name, feature_cols in models.items():
        cols_needed = feature_cols + [target]
        valid_data = spy_is[cols_needed].dropna()

        X = valid_data[feature_cols].values
        y = valid_data[target].values

        # Add intercept
        X_c = np.column_stack([np.ones(len(X)), X])

        try:
            beta, residuals, rank, sv = np.linalg.lstsq(X_c, y, rcond=None)
            y_hat = X_c @ beta
            ss_res = np.sum((y - y_hat) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot
            adj_r_squared = 1 - (1 - r_squared) * (len(y) - 1) / (len(y) - len(beta))

            # Standard errors
            mse_reg = ss_res / (len(y) - len(beta))
            var_beta = mse_reg * np.linalg.inv(X_c.T @ X_c).diagonal()
            se_beta = np.sqrt(np.maximum(var_beta, 0))
            t_stats = beta / se_beta
            p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=len(y) - len(beta)))

            coef_dict = {'intercept': {'beta': float(beta[0]), 't': float(t_stats[0]), 'p': float(p_vals[0])}}
            for j, col in enumerate(feature_cols):
                coef_dict[col] = {
                    'beta': float(beta[j + 1]),
                    't': float(t_stats[j + 1]),
                    'p': float(p_vals[j + 1]),
                }

            is_regression[model_name] = {
                'r_squared': float(r_squared),
                'adj_r_squared': float(adj_r_squared),
                'n_obs': int(len(y)),
                'coefficients': coef_dict,
            }

            print(f"\n  {model_name}: R²={r_squared:.4f}, Adj.R²={adj_r_squared:.4f}, n={len(y)}")
            for name, cinfo in coef_dict.items():
                sig = "***" if cinfo['p'] < 0.01 else "**" if cinfo['p'] < 0.05 else "*" if cinfo['p'] < 0.10 else ""
                print(f"    {name}: β={cinfo['beta']:.6f}, t={cinfo['t']:.3f}{sig} (p={cinfo['p']:.4f})")
        except Exception as e:
            print(f"  {model_name}: regression failed: {e}")
            is_regression[model_name] = {'error': str(e)}

    # ----------------------------------------------------------
    # 9. Regime Analysis: Entropy quintiles vs future vol
    # ----------------------------------------------------------
    print("\n[9] Regime Analysis: Entropy quintiles vs future RV21...")

    regime_analysis = {}
    for ent_col, lag_col in [('sampen', 'sampen_lag'), ('pe', 'pe_lag'), ('shannon', 'shannon_lag')]:
        valid_data = spy[[lag_col, 'rv21_fwd']].dropna()
        if len(valid_data) < 100:
            continue

        # Quintile analysis
        valid_data['quintile'] = pd.qcut(valid_data[lag_col], q=5, labels=False, duplicates='drop')

        quintile_stats = {}
        for q_val in sorted(valid_data['quintile'].unique()):
            q_data = valid_data[valid_data['quintile'] == q_val]['rv21_fwd']
            quintile_stats[f'Q{q_val+1}'] = {
                'mean_rv': float(q_data.mean()),
                'median_rv': float(q_data.median()),
                'std_rv': float(q_data.std()),
                'n': int(len(q_data)),
            }

        # Monotonicity test: Spearman correlation between quintile and mean RV
        q_means = [quintile_stats[f'Q{i+1}']['mean_rv'] for i in range(len(quintile_stats))]
        q_ranks = list(range(len(q_means)))
        if len(q_means) >= 3:
            rho, p = stats.spearmanr(q_ranks, q_means)
        else:
            rho, p = np.nan, np.nan

        regime_analysis[ent_col] = {
            'quintiles': quintile_stats,
            'monotonicity_rho': float(rho) if np.isfinite(rho) else None,
            'monotonicity_p': float(p) if np.isfinite(p) else None,
        }

        print(f"\n  {ent_col} quintiles → future RV21:")
        for q_name, q_stats in quintile_stats.items():
            print(f"    {q_name}: mean_RV={q_stats['mean_rv']:.6f}, median={q_stats['median_rv']:.6f}, n={q_stats['n']}")
        print(f"    Monotonicity: Spearman rho={rho:.4f}, p={p:.4f}")

    # ----------------------------------------------------------
    # 10. Granger Causality (simple F-test)
    # ----------------------------------------------------------
    print("\n[10] Granger-like F-test: Entropy → Future Vol (IS only)...")

    granger_results = {}
    for ent_col in ['sampen_lag', 'pe_lag', 'shannon_lag']:
        cols_restricted = ['rv21_lag', target]
        cols_full = ['rv21_lag', ent_col, target]

        data_r = spy_is[cols_restricted].dropna()
        data_f = spy_is[cols_full].dropna()

        # Use common valid index
        common_idx = data_r.index.intersection(data_f.index)
        data_r = data_r.loc[common_idx]
        data_f = data_f.loc[common_idx]

        n = len(data_r)
        k_r = 2  # intercept + rv21_lag
        k_f = 3  # intercept + rv21_lag + entropy

        X_r = np.column_stack([np.ones(n), data_r['rv21_lag'].values])
        X_f = np.column_stack([np.ones(n), data_f['rv21_lag'].values, data_f[ent_col].values])
        y = data_r[target].values

        beta_r = np.linalg.lstsq(X_r, y, rcond=None)[0]
        beta_f = np.linalg.lstsq(X_f, y, rcond=None)[0]

        ssr_r = np.sum((y - X_r @ beta_r) ** 2)
        ssr_f = np.sum((y - X_f @ beta_f) ** 2)

        f_stat = ((ssr_r - ssr_f) / (k_f - k_r)) / (ssr_f / (n - k_f))
        f_p = 1 - stats.f.cdf(f_stat, k_f - k_r, n - k_f)

        granger_results[ent_col] = {
            'f_stat': float(f_stat),
            'p_value': float(f_p),
            'n_obs': int(n),
        }

        sig = "***" if f_p < 0.01 else "**" if f_p < 0.05 else "*" if f_p < 0.10 else ""
        print(f"  {ent_col}: F={f_stat:.3f}, p={f_p:.4f}{sig}, n={n}")

    # ----------------------------------------------------------
    # 11. Rolling Correlation Analysis
    # ----------------------------------------------------------
    print("\n[11] Rolling correlation (252-day) of entropy vs forward RV...")

    rolling_corr_analysis = {}
    for ent_col in ['sampen_lag', 'pe_lag', 'shannon_lag']:
        valid_data = spy[[ent_col, 'rv21_fwd']].dropna()
        if len(valid_data) < 504:
            continue

        roll_corr = valid_data[ent_col].rolling(252).corr(valid_data['rv21_fwd'])
        roll_corr = roll_corr.dropna()

        rolling_corr_analysis[ent_col] = {
            'mean_corr': float(roll_corr.mean()),
            'std_corr': float(roll_corr.std()),
            'min_corr': float(roll_corr.min()),
            'max_corr': float(roll_corr.max()),
            'pct_positive': float((roll_corr > 0).mean() * 100),
            'pct_negative': float((roll_corr < 0).mean() * 100),
        }

        print(f"  {ent_col}: mean_corr={roll_corr.mean():.4f}, std={roll_corr.std():.4f}, "
              f"range=[{roll_corr.min():.4f}, {roll_corr.max():.4f}], "
              f"positive%={((roll_corr > 0).mean() * 100):.1f}%")

    # ----------------------------------------------------------
    # 12. Summary & Conclusions
    # ----------------------------------------------------------
    elapsed_total = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"TOTAL RUNTIME: {elapsed_total:.1f}s")
    print(f"{'=' * 70}")

    # Determine best model
    qlike_values = {k: v['qlike'] for k, v in results.items()}
    best_model = min(qlike_values, key=qlike_values.get)

    # Assessment
    # Note: QLIKE gain > 0 means WORSE (higher loss), < 0 means BETTER
    baseline_qlike = results['M1_baseline']['qlike']

    # Check entropy models (M2-M5) vs baseline — negative gain + significant DM = improvement
    entropy_models = ['M2_sampen', 'M3_pe', 'M4_shannon', 'M5_all_entropy']
    any_entropy_improvement = any(
        dm_results.get(m, {}).get('qlike_gain_pct', 0) < -0.1
        and dm_results.get(m, {}).get('dm_qlike_p', 1) < 0.10
        for m in entropy_models if m in dm_results
    )

    # Check entropy augmented VIX (M7) vs VIX only (M6)
    vix_qlike = results.get('M6_vix', {}).get('qlike', np.inf)

    conclusion = (
        "POSITIVE: Entropy features significantly improve vol prediction beyond RV baseline"
        if any_entropy_improvement
        else "NULL RESULT: Entropy features do NOT significantly improve OOS vol prediction beyond lagged RV"
    )

    print(f"\n  CONCLUSION: {conclusion}")
    print(f"  Best model: {best_model} (QLIKE={qlike_values[best_model]:.6f})")
    print(f"  Baseline QLIKE: {baseline_qlike:.6f}")

    # ----------------------------------------------------------
    # 13. Save Results
    # ----------------------------------------------------------
    print("\n[13] Saving results...")

    # Clean up non-serializable items
    clean_results = {}
    for model_name, rdata in results.items():
        clean_results[model_name] = {
            'qlike': rdata['qlike'],
            'mse': rdata['mse'],
            'n_obs': rdata['n_obs'],
            'n_total': rdata['n_total'],
            'first_forecast_date': rdata['first_forecast_date'],
            'last_forecast_date': rdata['last_forecast_date'],
            'min_train_count': rdata['min_train_count'],
            'max_train_count': rdata['max_train_count'],
            'target_end_embargo_enforced': True,
        }

    output = {
        'experiment_id': 'K478',
        'title': 'Entropy-Based Volatility Prediction',
        'category': 'jump_exploration',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'asset': ASSET,
        'data': {
            'source': 'yfinance',
            'asset': ASSET,
            'vix_symbol': '^VIX',
            'asset_rows': int(len(spy)),
            'vix_rows': int(len(vix)),
            'actual_start': spy.index[0].strftime('%Y-%m-%d'),
            'actual_end': spy.index[-1].strftime('%Y-%m-%d'),
            'oos_rows': int(len(spy_oos)),
        },
        'data_period': {
            'start': DATA_START,
            'end': spy.index[-1].strftime('%Y-%m-%d'),
            'is_period': f'{DATA_START} to {OOS_START}',
            'oos_period': f"{OOS_START} to {spy_oos.index[-1].strftime('%Y-%m-%d')}",
        },
        'methodology': {
            'entropy_window': WINDOW,
            'forecast_target': f'sum of squared SPY log returns from t+1 through t+{HORIZON}',
            'target_horizon_trading_days': HORIZON,
            'feature_lag': 'all predictors are shifted by one trading day before forecasting',
            'target_end_embargo': 'training row j is eligible for forecast row i only if j + horizon < i',
            'sampen_params': {'m': 2, 'r_mult': SAMPEN_R_MULT},
            'pe_params': {'order': 3, 'delay': 1, 'normalized': True},
            'shannon_params': {'n_bins': N_BINS_SHANNON},
            'forecast_method': 'expanding_window_OLS',
            'min_training_window': MIN_TRAINING_WINDOW,
            'dm_test': {
                'loss_diff': 'baseline_loss_minus_challenger_loss',
                'positive_t_means': 'challenger_has_lower_average_loss',
                'hac_lag': DM_HAC_LAG,
                'pairwise_alignment': 'forecast dates intersected before computing loss differentials',
            },
        },
        'descriptive_stats': desc_stats,
        'oos_results': clean_results,
        'dm_tests_vs_baseline': dm_results,
        'is_regression': is_regression,
        'regime_analysis': regime_analysis,
        'granger_tests': granger_results,
        'rolling_correlation': rolling_corr_analysis,
        'conclusion': conclusion,
        'best_model': best_model,
        'runtime_seconds': round(elapsed_total, 1),
        'references': [
            'Pincus (1991) "Approximate entropy" PNAS',
            'Richman & Moorman (2000) "Sample entropy" Am J Physiol',
            'Bandt & Pompe (2002) "Permutation entropy" PRL',
            'Stosic et al. (2019) "Multifractal analysis" Physica A',
        ],
        'prior_results': {
            'T22': 'MI and Transfer Entropy showed some info-theoretic signal',
            'complexity_ceiling': '52% of 31 models provide zero/negative value',
        },
    }

    out_path = OUT_DIR / 'k478_entropy_vol_results.json'
    with out_path.open('w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"  Saved to {out_path}")
    print("\nDone!")

    return output


if __name__ == '__main__':
    main()
