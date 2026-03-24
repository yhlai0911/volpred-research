"""
K197: GARCH Persistence Break Detection and Volatility Regime Change

Background:
- GARCH models assume constant alpha+beta (persistence). But persistence can change
  structurally (e.g., post-GFC, post-COVID).
- If we detect persistence breaks, we can adjust forecasts accordingly.

Data: SPY, QQQ, GLD, TLT, BTC-USD daily returns from yfinance (2005-2024).
OOS: 2023-2024.

Methodology:
1. Rolling GJR-GARCH estimation (w=500, step=22):
   - Track alpha+beta+gamma/2 (persistence) over time
   - Track individual parameter trajectories (omega, alpha, beta, gamma)
2. Structural break detection:
   - CUSUM test on persistence series
   - Simple change-point detection: find dates where persistence shifts significantly
3. Adaptive GARCH:
   - If persistence break detected in recent 252 days, re-estimate with shorter window (w=252)
   - Otherwise use standard w=2000
   - Compare vs fixed-window GJR
4. Persistence as predictor:
   - Does rolling persistence predict future vol or strategy performance?
   - Partial correlation of persistence with future RV controlling for VIX

Statistical tests: DM test, Harvey threshold (t>3.0).
Data source: yfinance (Yahoo Finance), all real market data.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K197: GARCH Persistence Break Detection & Volatility Regime Change")
print("=" * 70)

assets = ['SPY', 'QQQ', 'GLD', 'TLT', 'BTC-USD']
asset_names = {'SPY': 'S&P 500', 'QQQ': 'NASDAQ-100', 'GLD': 'Gold',
               'TLT': 'Long Treasury', 'BTC-USD': 'Bitcoin'}

print("\n[1] Downloading data from yfinance...")
price_data = {}
for asset in assets:
    start = '2003-01-01' if asset != 'BTC-USD' else '2014-01-01'
    df = yf.download(asset, start=start, end='2025-01-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    price_data[asset] = df['Close'].dropna()
    print(f"  {asset}: {len(price_data[asset])} obs "
          f"({price_data[asset].index[0].strftime('%Y-%m-%d')} to "
          f"{price_data[asset].index[-1].strftime('%Y-%m-%d')})")

# Also download VIX for partial correlation analysis
vix = yf.download('^VIX', start='2003-01-01', end='2025-01-01', progress=False)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix_close = vix['Close'].dropna()
print(f"  VIX: {len(vix_close)} obs")

# ============================================================
# 2. Rolling GJR-GARCH Parameter Estimation
# ============================================================
print("\n[2] Rolling GJR-GARCH estimation (w=500, step=22)...")

ROLL_WINDOW = 500
ROLL_STEP = 22  # monthly steps

def rolling_gjr_params(returns, window=500, step=22):
    """Estimate GJR-GARCH parameters on rolling windows.
    Returns DataFrame with omega, alpha, beta, gamma, persistence, and date index."""
    results = []
    n = len(returns)
    for i in range(window, n, step):
        chunk = returns.iloc[i-window:i]
        date = returns.index[i]
        try:
            model = arch_model(chunk * 100, vol='GARCH', p=1, o=1, q=1,
                               dist='normal', mean='Zero')
            res = model.fit(disp='off', show_warning=False)
            omega = res.params.get('omega', np.nan)
            alpha = res.params.get('alpha[1]', np.nan)
            gamma = res.params.get('gamma[1]', np.nan)
            beta = res.params.get('beta[1]', np.nan)
            # GJR persistence = alpha + beta + gamma/2
            persistence = alpha + beta + gamma / 2
            results.append({
                'date': date,
                'omega': omega,
                'alpha': alpha,
                'beta': beta,
                'gamma': gamma,
                'persistence': persistence
            })
        except Exception:
            pass
    return pd.DataFrame(results).set_index('date')

rolling_params = {}
for asset in assets:
    ret = np.log(price_data[asset] / price_data[asset].shift(1)).dropna()
    params = rolling_gjr_params(ret, window=ROLL_WINDOW, step=ROLL_STEP)
    rolling_params[asset] = params
    p = params['persistence']
    print(f"  {asset}: {len(params)} windows, "
          f"persistence mean={p.mean():.4f}, std={p.std():.4f}, "
          f"min={p.min():.4f}, max={p.max():.4f}")

# ============================================================
# 3. CUSUM Test on Persistence Series
# ============================================================
print("\n[3] CUSUM test on persistence series...")

def cusum_test(series):
    """Simple CUSUM test for structural break.
    Returns max CUSUM statistic and approximate p-value.
    H0: no structural break (constant mean)."""
    n = len(series)
    s = series.values
    mean_s = np.mean(s)
    std_s = np.std(s, ddof=1)
    if std_s < 1e-10:
        return 0.0, 1.0, 0
    cumsum = np.cumsum(s - mean_s) / (std_s * np.sqrt(n))
    max_cusum = np.max(np.abs(cumsum))
    # Approximate p-value using Brownian bridge critical values
    # Critical values: 1.358 (5%), 1.224 (10%), 1.628 (1%)
    # Using the exp(-2*x^2) approximation for Kolmogorov-Smirnov
    p_approx = 2 * np.exp(-2 * max_cusum**2)
    p_approx = min(p_approx, 1.0)
    break_idx = np.argmax(np.abs(cumsum))
    return max_cusum, p_approx, break_idx

cusum_results = {}
for asset in assets:
    params = rolling_params[asset]
    p_series = params['persistence'].dropna()
    max_cusum, p_val, break_idx = cusum_test(p_series)
    break_date = p_series.index[break_idx] if break_idx < len(p_series) else None
    cusum_results[asset] = {
        'max_cusum': max_cusum,
        'p_value': p_val,
        'break_date': break_date.strftime('%Y-%m-%d') if break_date else None,
        'significant': p_val < 0.05
    }
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else "NS"
    print(f"  {asset}: CUSUM={max_cusum:.3f}, p={p_val:.4f} [{sig}], "
          f"break={break_date.strftime('%Y-%m-%d') if break_date else 'N/A'}")

# ============================================================
# 4. Change-Point Detection (Multiple Breaks)
# ============================================================
print("\n[4] Change-point detection (binary segmentation)...")

def binary_segmentation_changepoints(series, min_size=10, threshold=2.0, max_breaks=5):
    """Simple binary segmentation for change-point detection.
    Uses difference of means test (t-test) to find breaks.
    Returns list of (break_index, t_stat, p_value) tuples."""
    breaks = []

    def find_best_split(s, start, end):
        if end - start < 2 * min_size:
            return None
        best_t = 0
        best_idx = None
        for k in range(start + min_size, end - min_size):
            left = s[start:k]
            right = s[k:end]
            t_stat, p_val = stats.ttest_ind(left, right, equal_var=False)
            if abs(t_stat) > abs(best_t):
                best_t = t_stat
                best_idx = k
                best_p = p_val
        if best_idx is not None and abs(best_t) > threshold:
            return (best_idx, best_t, best_p)
        return None

    s = series.values
    segments = [(0, len(s))]

    for _ in range(max_breaks):
        best_result = None
        best_seg_idx = None
        for seg_idx, (start, end) in enumerate(segments):
            result = find_best_split(s, start, end)
            if result is not None:
                if best_result is None or abs(result[1]) > abs(best_result[1]):
                    best_result = result
                    best_seg_idx = seg_idx
        if best_result is None:
            break
        bp, t_stat, p_val = best_result
        breaks.append((bp, t_stat, p_val))
        start, end = segments[best_seg_idx]
        segments[best_seg_idx] = (start, bp)
        segments.insert(best_seg_idx + 1, (bp, end))

    breaks.sort(key=lambda x: x[0])
    return breaks

changepoint_results = {}
for asset in assets:
    params = rolling_params[asset]
    p_series = params['persistence'].dropna()
    breaks = binary_segmentation_changepoints(p_series, min_size=8, threshold=2.0, max_breaks=5)

    break_info = []
    for bp_idx, t_stat, p_val in breaks:
        bp_date = p_series.index[bp_idx]
        # Mean before and after
        mean_before = p_series.iloc[:bp_idx].mean()
        mean_after = p_series.iloc[bp_idx:].mean()
        break_info.append({
            'date': bp_date.strftime('%Y-%m-%d'),
            'index': int(bp_idx),
            't_stat': round(t_stat, 3),
            'p_value': round(p_val, 4),
            'mean_before': round(mean_before, 4),
            'mean_after': round(mean_after, 4),
            'delta': round(mean_after - mean_before, 4)
        })

    changepoint_results[asset] = break_info
    print(f"\n  {asset}: {len(breaks)} change-points detected")
    for bi in break_info:
        direction = "UP" if bi['delta'] > 0 else "DOWN"
        print(f"    {bi['date']}: {bi['mean_before']:.4f} -> {bi['mean_after']:.4f} "
              f"({direction} {abs(bi['delta']):.4f}), t={bi['t_stat']:.2f}, p={bi['p_value']:.4f}")

# ============================================================
# 5. Persistence Regime Summary
# ============================================================
print("\n[5] Persistence regime summary...")

regime_summary = {}
for asset in assets:
    params = rolling_params[asset]
    p = params['persistence']

    # Define regimes by percentile
    low_thresh = p.quantile(0.25)
    high_thresh = p.quantile(0.75)

    low_regime = p[p <= low_thresh]
    mid_regime = p[(p > low_thresh) & (p < high_thresh)]
    high_regime = p[p >= high_thresh]

    regime_summary[asset] = {
        'overall_mean': round(p.mean(), 4),
        'overall_std': round(p.std(), 4),
        'low_persistence': {
            'threshold': round(low_thresh, 4),
            'mean': round(low_regime.mean(), 4),
            'count': len(low_regime)
        },
        'high_persistence': {
            'threshold': round(high_thresh, 4),
            'mean': round(high_regime.mean(), 4),
            'count': len(high_regime)
        },
        'range': round(p.max() - p.min(), 4),
        'cv': round(p.std() / p.mean() * 100, 2) if p.mean() != 0 else 0
    }

    print(f"  {asset}: mean={p.mean():.4f}, std={p.std():.4f}, "
          f"CV={p.std()/p.mean()*100:.1f}%, range=[{p.min():.4f}, {p.max():.4f}]")

# ============================================================
# 6. Adaptive GARCH vs Fixed-Window GARCH
# ============================================================
print("\n[6] Adaptive GARCH (break-aware) vs Fixed-Window GJR-GARCH...")
print("    Adaptive: w=252 if persistence break in last 252 days, else w=2000")
print("    Fixed: w=2000 always")
print("    OOS: 2023-01-01 to 2024-12-31")

OOS_START = '2023-01-01'

def compute_qlike(actual_var, forecast_var):
    """QLIKE loss function (Patton 2011). Lower is better."""
    mask = (forecast_var > 0) & (actual_var > 0) & np.isfinite(actual_var) & np.isfinite(forecast_var)
    a = actual_var[mask]
    f = forecast_var[mask]
    return np.mean(np.log(f) + a / f)

def dm_test(loss1, loss2):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Returns t-stat and p-value. Negative t means loss1 < loss2 (model1 better)."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    mean_d = np.mean(d)
    # Newey-West HAC variance with bandwidth = int(n^(1/3))
    bw = max(1, int(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, bw + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / (bw + 1)) * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = mean_d / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value

adaptive_results = {}

for asset in assets:
    ret = np.log(price_data[asset] / price_data[asset].shift(1)).dropna()

    # Get persistence breaks for this asset
    breaks_for_asset = changepoint_results[asset]
    break_dates = [pd.Timestamp(b['date']) for b in breaks_for_asset]

    # OOS period
    oos_mask = ret.index >= OOS_START
    oos_dates = ret.index[oos_mask]

    if len(oos_dates) < 50:
        print(f"  {asset}: Not enough OOS data, skipping")
        continue

    # Generate daily forecasts for OOS period
    fixed_forecasts = []
    adaptive_forecasts = []
    actual_vars = []
    forecast_dates = []

    # Step through OOS daily (but re-estimate every 22 days for speed)
    est_interval = 22
    last_fixed_vol = None
    last_adaptive_vol = None

    for i, date in enumerate(oos_dates):
        idx_in_full = ret.index.get_loc(date)

        if i % est_interval == 0 or last_fixed_vol is None:
            # Fixed window (w=2000)
            w_fixed = 2000
            start_fixed = max(0, idx_in_full - w_fixed)
            chunk_fixed = ret.iloc[start_fixed:idx_in_full]

            try:
                model_f = arch_model(chunk_fixed * 100, vol='GARCH', p=1, o=1, q=1,
                                     dist='normal', mean='Zero')
                res_f = model_f.fit(disp='off', show_warning=False)
                fcast_f = res_f.forecast(horizon=1)
                last_fixed_vol = fcast_f.variance.iloc[-1, 0] / 10000  # back to decimal
            except Exception:
                pass

            # Adaptive window: check if any break within last 252 trading days
            lookback_date = ret.index[max(0, idx_in_full - 252)]
            recent_break = any(d >= lookback_date and d <= date for d in break_dates)

            if recent_break:
                w_adaptive = 252
            else:
                w_adaptive = 2000

            start_adaptive = max(0, idx_in_full - w_adaptive)
            chunk_adaptive = ret.iloc[start_adaptive:idx_in_full]

            try:
                model_a = arch_model(chunk_adaptive * 100, vol='GARCH', p=1, o=1, q=1,
                                     dist='normal', mean='Zero')
                res_a = model_a.fit(disp='off', show_warning=False)
                fcast_a = res_a.forecast(horizon=1)
                last_adaptive_vol = fcast_a.variance.iloc[-1, 0] / 10000
            except Exception:
                pass

        if last_fixed_vol is not None and last_adaptive_vol is not None:
            fixed_forecasts.append(last_fixed_vol)
            adaptive_forecasts.append(last_adaptive_vol)
            actual_vars.append(ret.iloc[idx_in_full] ** 2)
            forecast_dates.append(date)

    fixed_arr = np.array(fixed_forecasts)
    adaptive_arr = np.array(adaptive_forecasts)
    actual_arr = np.array(actual_vars)

    # QLIKE
    qlike_fixed = compute_qlike(actual_arr, fixed_arr)
    qlike_adaptive = compute_qlike(actual_arr, adaptive_arr)

    # DM test
    loss_fixed = np.log(fixed_arr) + actual_arr / fixed_arr
    loss_adaptive = np.log(adaptive_arr) + actual_arr / adaptive_arr
    dm_t, dm_p = dm_test(loss_adaptive, loss_fixed)

    # MSE
    mse_fixed = np.mean((actual_arr - fixed_arr) ** 2)
    mse_adaptive = np.mean((actual_arr - adaptive_arr) ** 2)

    adaptive_results[asset] = {
        'n_forecasts': len(fixed_arr),
        'qlike_fixed': round(qlike_fixed, 6),
        'qlike_adaptive': round(qlike_adaptive, 6),
        'qlike_diff_pct': round((qlike_adaptive - qlike_fixed) / abs(qlike_fixed) * 100, 3),
        'mse_fixed': float(f"{mse_fixed:.8f}"),
        'mse_adaptive': float(f"{mse_adaptive:.8f}"),
        'dm_t': round(dm_t, 3) if not np.isnan(dm_t) else None,
        'dm_p': round(dm_p, 4) if not np.isnan(dm_p) else None,
        'adaptive_better': qlike_adaptive < qlike_fixed,
        'n_breaks_in_oos_vicinity': sum(1 for d in break_dates
                                        if d >= pd.Timestamp('2022-01-01') and d <= pd.Timestamp('2024-12-31'))
    }

    better = "Adaptive" if qlike_adaptive < qlike_fixed else "Fixed"
    sig = f"DM t={dm_t:.2f}, p={dm_p:.4f}" if not np.isnan(dm_t) else "DM: N/A"
    print(f"  {asset}: QLIKE fixed={qlike_fixed:.6f}, adaptive={qlike_adaptive:.6f} "
          f"[{better}] ({sig})")

# ============================================================
# 7. Persistence as Predictor of Future Realized Volatility
# ============================================================
print("\n[7] Persistence as predictor of future realized vol...")
print("    Regression: RV_22d_fwd = a + b1*persistence + b2*VIX + e")

predictor_results = {}
for asset in assets:
    params = rolling_params[asset]
    ret = np.log(price_data[asset] / price_data[asset].shift(1)).dropna()

    # Build aligned dataset
    pred_data = pd.DataFrame(index=params.index)
    pred_data['persistence'] = params['persistence']

    # Forward 22-day realized vol (annualized)
    rv_22d = ret.rolling(22).std() * np.sqrt(252)
    pred_data['fwd_rv'] = rv_22d.shift(-22).reindex(pred_data.index)

    # Current VIX (aligned)
    pred_data['vix'] = vix_close.reindex(pred_data.index, method='ffill') / 100  # to decimal

    pred_data = pred_data.dropna()

    if len(pred_data) < 30:
        print(f"  {asset}: Not enough aligned data, skipping")
        continue

    # Simple correlation
    corr_pers_rv = pred_data['persistence'].corr(pred_data['fwd_rv'])

    # Partial correlation: persistence -> fwd_rv | VIX
    # Method: regress persistence on VIX, get residuals; regress fwd_rv on VIX, get residuals; correlate
    from numpy.linalg import lstsq

    X_vix = np.column_stack([np.ones(len(pred_data)), pred_data['vix'].values])

    # Residualize persistence
    coef_p, _, _, _ = lstsq(X_vix, pred_data['persistence'].values, rcond=None)
    resid_pers = pred_data['persistence'].values - X_vix @ coef_p

    # Residualize fwd_rv
    coef_r, _, _, _ = lstsq(X_vix, pred_data['fwd_rv'].values, rcond=None)
    resid_rv = pred_data['fwd_rv'].values - X_vix @ coef_r

    partial_corr = np.corrcoef(resid_pers, resid_rv)[0, 1]

    # t-test for partial correlation
    n = len(pred_data)
    t_partial = partial_corr * np.sqrt(n - 3) / np.sqrt(1 - partial_corr**2)
    p_partial = 2 * (1 - stats.t.cdf(abs(t_partial), df=n-3))

    # Multiple regression
    X_multi = np.column_stack([np.ones(n), pred_data['persistence'].values, pred_data['vix'].values])
    coef_multi, _, _, _ = lstsq(X_multi, pred_data['fwd_rv'].values, rcond=None)
    y_pred = X_multi @ coef_multi
    ss_res = np.sum((pred_data['fwd_rv'].values - y_pred) ** 2)
    ss_tot = np.sum((pred_data['fwd_rv'].values - np.mean(pred_data['fwd_rv'].values)) ** 2)
    r2_multi = 1 - ss_res / ss_tot

    # VIX-only regression for comparison
    coef_vix_only, _, _, _ = lstsq(X_vix, pred_data['fwd_rv'].values, rcond=None)
    y_pred_vix = X_vix @ coef_vix_only
    ss_res_vix = np.sum((pred_data['fwd_rv'].values - y_pred_vix) ** 2)
    r2_vix_only = 1 - ss_res_vix / ss_tot

    predictor_results[asset] = {
        'n_obs': n,
        'corr_persistence_fwd_rv': round(corr_pers_rv, 4),
        'partial_corr_persistence_rv_given_vix': round(partial_corr, 4),
        'partial_t': round(t_partial, 3),
        'partial_p': round(p_partial, 4),
        'r2_vix_only': round(r2_vix_only, 4),
        'r2_vix_plus_persistence': round(r2_multi, 4),
        'r2_increment': round(r2_multi - r2_vix_only, 4),
        'beta_persistence': round(coef_multi[1], 4),
        'beta_vix': round(coef_multi[2], 4)
    }

    sig = "***" if p_partial < 0.01 else "**" if p_partial < 0.05 else "*" if p_partial < 0.10 else "NS"
    print(f"  {asset}: corr(pers,fwd_rv)={corr_pers_rv:.3f}, "
          f"partial_corr|VIX={partial_corr:.3f} (t={t_partial:.2f}, p={p_partial:.4f}) [{sig}]")
    print(f"         R2(VIX only)={r2_vix_only:.4f}, R2(VIX+pers)={r2_multi:.4f}, "
          f"increment={r2_multi - r2_vix_only:.4f}")

# ============================================================
# 8. Persistence Regime and VT Strategy Performance
# ============================================================
print("\n[8] Persistence regime vs VT strategy performance (SPY only)...")

# SPY 12/VIX strategy in different persistence regimes
spy_ret = np.log(price_data['SPY'] / price_data['SPY'].shift(1)).dropna()
spy_params = rolling_params['SPY']

# Build daily persistence (forward-fill from monthly estimates)
daily_persistence = spy_params['persistence'].reindex(spy_ret.index, method='ffill')

# 12/VIX weight (lagged)
vix_aligned = vix_close.reindex(spy_ret.index, method='ffill')
vt_weight = np.clip(12 / vix_aligned, 0, 1).shift(1)

# VT returns
vt_ret = vt_weight * spy_ret

# Combine
strat_data = pd.DataFrame({
    'spy_ret': spy_ret,
    'vt_ret': vt_ret,
    'persistence': daily_persistence,
    'vix': vix_aligned,
    'vt_weight': vt_weight
}).dropna()

# Split into persistence terciles
p33 = strat_data['persistence'].quantile(0.33)
p67 = strat_data['persistence'].quantile(0.67)

regimes = {
    'Low Persistence (<P33)': strat_data['persistence'] <= p33,
    'Mid Persistence (P33-P67)': (strat_data['persistence'] > p33) & (strat_data['persistence'] <= p67),
    'High Persistence (>P67)': strat_data['persistence'] > p67
}

print(f"\n  Persistence terciles: P33={p33:.4f}, P67={p67:.4f}")
print(f"  {'Regime':<30} {'N':>6} {'VT Ann Ret':>12} {'VT Sharpe':>10} {'BH Sharpe':>10} {'VT-BH':>8}")
print(f"  {'-'*76}")

regime_perf = {}
for regime_name, mask in regimes.items():
    subset = strat_data[mask]
    n = len(subset)

    vt_ann_ret = subset['vt_ret'].mean() * 252
    vt_ann_vol = subset['vt_ret'].std() * np.sqrt(252)
    vt_sharpe = vt_ann_ret / vt_ann_vol if vt_ann_vol > 0 else 0

    bh_ann_ret = subset['spy_ret'].mean() * 252
    bh_ann_vol = subset['spy_ret'].std() * np.sqrt(252)
    bh_sharpe = bh_ann_ret / bh_ann_vol if bh_ann_vol > 0 else 0

    print(f"  {regime_name:<30} {n:>6} {vt_ann_ret:>11.2%} {vt_sharpe:>10.3f} {bh_sharpe:>10.3f} {vt_sharpe-bh_sharpe:>+8.3f}")

    regime_perf[regime_name] = {
        'n': n,
        'vt_ann_ret': round(vt_ann_ret, 4),
        'vt_sharpe': round(vt_sharpe, 3),
        'bh_sharpe': round(bh_sharpe, 3),
        'vt_minus_bh': round(vt_sharpe - bh_sharpe, 3),
        'mean_vix': round(subset['vix'].mean(), 2),
        'mean_weight': round(subset['vt_weight'].mean(), 3)
    }

# ============================================================
# 9. Parameter Trajectory Analysis
# ============================================================
print("\n[9] Individual parameter trajectory analysis...")

param_trajectories = {}
for asset in assets:
    params = rolling_params[asset]
    traj = {}
    for param_name in ['omega', 'alpha', 'beta', 'gamma']:
        series = params[param_name].dropna()
        # Trend test (Mann-Kendall via correlation with time)
        time_idx = np.arange(len(series))
        tau, mk_p = stats.kendalltau(time_idx, series.values)

        traj[param_name] = {
            'mean': round(series.mean(), 6),
            'std': round(series.std(), 6),
            'cv_pct': round(series.std() / series.mean() * 100, 1) if series.mean() != 0 else 0,
            'kendall_tau': round(tau, 4),
            'trend_p': round(mk_p, 4),
            'has_trend': mk_p < 0.05
        }

    param_trajectories[asset] = traj

    trending = [p for p in ['omega', 'alpha', 'beta', 'gamma'] if traj[p]['has_trend']]
    print(f"  {asset}: trending params = {trending if trending else 'none'}")
    for pn in ['alpha', 'beta', 'gamma']:
        t = traj[pn]
        sig = "TREND" if t['has_trend'] else "stable"
        direction = "UP" if t['kendall_tau'] > 0 else "DOWN"
        print(f"    {pn}: mean={t['mean']:.4f}, CV={t['cv_pct']:.1f}%, "
              f"tau={t['kendall_tau']:.3f} ({direction}, p={t['trend_p']:.4f}) [{sig}]")

# ============================================================
# 10. Cross-Asset Persistence Correlation
# ============================================================
print("\n[10] Cross-asset persistence correlation...")

# Align persistence series across assets (monthly)
persist_df = pd.DataFrame()
for asset in assets:
    persist_df[asset] = rolling_params[asset]['persistence']

# Forward-fill to common monthly index
persist_aligned = persist_df.dropna(how='all')
persist_aligned = persist_aligned.resample('ME').last().dropna()

print(f"  Aligned months: {len(persist_aligned)}")
if len(persist_aligned) >= 10:
    corr_matrix = persist_aligned.corr()
    print("\n  Persistence correlation matrix:")
    print(f"  {'':>10}", end='')
    for a in persist_aligned.columns:
        print(f" {a:>8}", end='')
    print()
    for a1 in persist_aligned.columns:
        print(f"  {a1:>10}", end='')
        for a2 in persist_aligned.columns:
            if a1 == a2:
                print(f" {'1.000':>8}", end='')
            else:
                val = corr_matrix.loc[a1, a2]
                print(f" {val:>8.3f}", end='')
        print()

# ============================================================
# 11. Summary Statistics Table
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K197 Results")
print("=" * 70)

print("\n[A] CUSUM Structural Break Test on Persistence")
print(f"  {'Asset':<10} {'CUSUM':>8} {'p-value':>10} {'Break Date':>12} {'Significant':>12}")
print(f"  {'-'*52}")
for asset in assets:
    r = cusum_results[asset]
    print(f"  {asset:<10} {r['max_cusum']:>8.3f} {r['p_value']:>10.4f} "
          f"{r['break_date'] or 'N/A':>12} {'YES' if r['significant'] else 'no':>12}")

print("\n[B] Adaptive vs Fixed-Window GARCH (OOS 2023-2024)")
print(f"  {'Asset':<10} {'QLIKE Fixed':>12} {'QLIKE Adapt':>12} {'Diff%':>8} {'DM-t':>8} {'DM-p':>8} {'Better':>8}")
print(f"  {'-'*66}")
for asset in assets:
    if asset in adaptive_results:
        r = adaptive_results[asset]
        better = "Adapt" if r['adaptive_better'] else "Fixed"
        dm_t_str = f"{r['dm_t']:.2f}" if r['dm_t'] is not None else "N/A"
        dm_p_str = f"{r['dm_p']:.4f}" if r['dm_p'] is not None else "N/A"
        print(f"  {asset:<10} {r['qlike_fixed']:>12.6f} {r['qlike_adaptive']:>12.6f} "
              f"{r['qlike_diff_pct']:>7.2f}% {dm_t_str:>8} {dm_p_str:>8} {better:>8}")

print("\n[C] Persistence as Predictor (partial corr with fwd RV | VIX)")
print(f"  {'Asset':<10} {'Partial r':>10} {'t-stat':>8} {'p-value':>10} {'R2(VIX)':>8} {'R2(+pers)':>10} {'Incr':>6}")
print(f"  {'-'*62}")
for asset in assets:
    if asset in predictor_results:
        r = predictor_results[asset]
        sig = "***" if r['partial_p'] < 0.01 else "**" if r['partial_p'] < 0.05 else "*" if r['partial_p'] < 0.10 else ""
        print(f"  {asset:<10} {r['partial_corr_persistence_rv_given_vix']:>10.4f} "
              f"{r['partial_t']:>8.2f} {r['partial_p']:>9.4f}{sig} "
              f"{r['r2_vix_only']:>8.4f} {r['r2_vix_plus_persistence']:>10.4f} "
              f"{r['r2_increment']:>+6.4f}")

# ============================================================
# 12. Key Conclusions
# ============================================================
print("\n" + "=" * 70)
print("KEY CONCLUSIONS")
print("=" * 70)

# Count significant CUSUM breaks
n_cusum_sig = sum(1 for r in cusum_results.values() if r['significant'])
print(f"\n1. CUSUM breaks: {n_cusum_sig}/{len(assets)} assets show significant persistence breaks")

# Adaptive vs fixed
n_adaptive_better = sum(1 for r in adaptive_results.values() if r['adaptive_better'])
n_adaptive_sig = sum(1 for r in adaptive_results.values()
                     if r['dm_p'] is not None and r['dm_p'] < 0.05 and r['adaptive_better'])
print(f"2. Adaptive GARCH better in {n_adaptive_better}/{len(adaptive_results)} assets "
      f"(but {n_adaptive_sig} significant by DM test)")

# Persistence predictor
n_sig_predictor = sum(1 for r in predictor_results.values() if r['partial_p'] < 0.05)
avg_increment = np.mean([r['r2_increment'] for r in predictor_results.values()])
print(f"3. Persistence predicts fwd vol (partial|VIX): {n_sig_predictor}/{len(predictor_results)} significant")
print(f"   Average R2 increment over VIX: {avg_increment:+.4f}")

# VT performance by persistence regime
if regime_perf:
    low_vt_bh = regime_perf.get('Low Persistence (<P33)', {}).get('vt_minus_bh', 0)
    high_vt_bh = regime_perf.get('High Persistence (>P67)', {}).get('vt_minus_bh', 0)
    print(f"4. SPY VT performance by persistence regime:")
    print(f"   Low persistence: VT-BH Sharpe = {low_vt_bh:+.3f}")
    print(f"   High persistence: VT-BH Sharpe = {high_vt_bh:+.3f}")

# Parameter trends
n_trending = sum(1 for a in param_trajectories.values()
                 for p in a.values() if p['has_trend'])
total_params = sum(len(a) for a in param_trajectories.values())
print(f"5. Parameter trends: {n_trending}/{total_params} (asset x param) show significant time trends")

# Overall verdict
print(f"\nVERDICT: ", end="")
if n_adaptive_sig > 0:
    print("Adaptive GARCH shows SIGNIFICANT improvement for some assets.")
    print("         Persistence break detection has practical value.")
else:
    print("Persistence breaks are DETECTABLE but adaptive GARCH shows NO SIGNIFICANT")
    print("         improvement over fixed-window. Consistent with VIX sufficiency (J3/J4/K1).")
    print("         Persistence variation is real but not exploitable for forecasting.")

# ============================================================
# 13. Save Results
# ============================================================
results = {
    'experiment': 'K197',
    'title': 'GARCH Persistence Break Detection and Volatility Regime Change',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (Yahoo Finance)',
    'assets': assets,
    'oos_period': '2023-01-01 to 2024-12-31',
    'methodology': {
        'rolling_window': ROLL_WINDOW,
        'rolling_step': ROLL_STEP,
        'fixed_window': 2000,
        'adaptive_short_window': 252,
        'adaptive_trigger': 'persistence break within last 252 trading days',
        'break_detection': ['CUSUM test', 'Binary segmentation (t-test, threshold=2.0)'],
    },
    'cusum_results': cusum_results,
    'changepoint_results': changepoint_results,
    'regime_summary': regime_summary,
    'adaptive_vs_fixed': adaptive_results,
    'persistence_predictor': predictor_results,
    'vt_by_persistence_regime': regime_perf,
    'parameter_trajectories': param_trajectories,
    'conclusions': {
        'cusum_breaks_significant': n_cusum_sig,
        'adaptive_better_count': n_adaptive_better,
        'adaptive_significant_count': n_adaptive_sig,
        'persistence_predicts_vol_count': n_sig_predictor,
        'avg_r2_increment': round(avg_increment, 4),
        'verdict': 'Persistence breaks detectable but not exploitable' if n_adaptive_sig == 0
                   else 'Adaptive GARCH shows significant improvement'
    }
}

with open('experiments/k197_persistence_break_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to experiments/k197_persistence_break_results.json")
print(f"\nK197 complete.")
