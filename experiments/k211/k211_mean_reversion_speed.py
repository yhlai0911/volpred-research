"""
K211: Volatility Mean Reversion Speed as Predictive Feature

Background: GARCH models assume constant mean-reversion speed (alpha+beta).
K197 showed persistence changes over time. Does the SPEED of mean reversion
(how fast vol returns to its long-run mean after a shock) predict future vol
or strategy performance?

Methodology:
1. Estimate rolling half-life of vol shocks:
   - From GARCH: HL = -log(2)/log(alpha+beta+gamma/2)
   - From EWMA: HL of autocorrelation decay of r²
   - Direct: time for r² to return to mean after exceeding 2 std
2. Half-life as predictor of future vol
3. Strategy implications: does optimal rebalance frequency depend on HL regime?
4. Cross-asset HL structure

Statistical: Partial r|VIX, DM test, Harvey threshold (t>3.0).
Data: SPY, QQQ, GLD, TLT, BTC-USD from yfinance. OOS: 2023-2024.

[提出: 用戶, 執行: Claude]
"""

import sys
import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from arch import arch_model
from scipy import stats
from collections import OrderedDict

warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURATION
# ============================================================
ASSETS = ['SPY', 'QQQ', 'GLD', 'TLT', 'BTC-USD']
DATA_START = '2007-01-01'
DATA_END = '2024-12-31'
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
GARCH_WINDOW = 2000
ROLLING_HL_WINDOW = 252  # 1 year rolling for half-life estimation
REFIT_FREQ = 22  # Refit GARCH every 22 days
HL_THRESHOLD_FAST = 10  # days: fast mean-reversion
HL_THRESHOLD_SLOW = 30  # days: slow mean-reversion

print("=" * 70)
print("K211: Volatility Mean Reversion Speed as Predictive Feature")
print("=" * 70)
print(f"Assets: {ASSETS}")
print(f"OOS: {OOS_START} to {OOS_END}")
print(f"GARCH window: {GARCH_WINDOW}, Rolling HL window: {ROLLING_HL_WINDOW}")
print()

# ============================================================
# 1. DATA LOADING
# ============================================================
print("=" * 70)
print("SECTION 1: Data Loading")
print("=" * 70)

price_data = {}
return_data = {}

for ticker in ASSETS:
    start = '2005-01-01' if ticker != 'BTC-USD' else '2015-01-01'
    df = yf.download(ticker, start=start, end=DATA_END, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]

    price_data[ticker] = df['close']
    returns = np.log(df['close'] / df['close'].shift(1)).dropna()
    return_data[ticker] = returns
    print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}, N={len(returns)}")

# Load VIX for partial correlation control
vix_df = yf.download('^VIX', start='2005-01-01', end=DATA_END, auto_adjust=True, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_df.columns = [c.lower() for c in vix_df.columns]
vix_series = vix_df['close']
print(f"  VIX: {vix_df.index[0].date()} to {vix_df.index[-1].date()}, N={len(vix_series)}")

print()

# ============================================================
# 2. HALF-LIFE ESTIMATION METHODS
# ============================================================
print("=" * 70)
print("SECTION 2: Half-Life Estimation Methods")
print("=" * 70)


def garch_half_life(alpha, beta, gamma):
    """
    Compute half-life from GARCH persistence.
    For GJR-GARCH: persistence = alpha + beta + gamma/2
    HL = -log(2) / log(persistence)
    """
    persistence = alpha + beta + gamma / 2.0
    if persistence >= 1.0 or persistence <= 0.0:
        return np.nan
    hl = -np.log(2) / np.log(persistence)
    return hl


def ewma_half_life_from_acf(r_squared, window=252):
    """
    Estimate half-life from autocorrelation decay of r².
    Fit exponential decay to ACF of r² and extract half-life.
    """
    from statsmodels.tsa.stattools import acf

    # Compute ACF up to lag 60
    max_lag = min(60, len(r_squared) // 4)
    if max_lag < 10:
        return np.nan

    acf_vals = acf(r_squared, nlags=max_lag, fft=True)

    # Find first lag where ACF drops below 0.5 * ACF(1)
    target = acf_vals[1] * 0.5
    for lag in range(2, max_lag + 1):
        if acf_vals[lag] < target:
            # Linear interpolation between lag-1 and lag
            if acf_vals[lag - 1] == acf_vals[lag]:
                return float(lag)
            frac = (acf_vals[lag - 1] - target) / (acf_vals[lag - 1] - acf_vals[lag])
            return float(lag - 1) + frac
    return float(max_lag)  # Very persistent


def direct_half_life(r_squared, threshold_std=2.0, window=252):
    """
    Direct measurement: average time for r² to return to mean
    after exceeding threshold_std standard deviations above mean.
    """
    mean_r2 = r_squared.mean()
    std_r2 = r_squared.std()
    threshold = mean_r2 + threshold_std * std_r2

    # Find shock events (r² > threshold)
    shock_dates = r_squared.index[r_squared > threshold]

    if len(shock_dates) < 3:
        return np.nan

    # For each shock, measure how many days until r² returns below mean + 0.5*std
    return_level = mean_r2 + 0.5 * std_r2
    half_lives = []

    i = 0
    while i < len(shock_dates):
        shock_date = shock_dates[i]
        shock_loc = r_squared.index.get_loc(shock_date)

        # Look forward for return to normal
        for j in range(1, min(120, len(r_squared) - shock_loc)):
            if r_squared.iloc[shock_loc + j] < return_level:
                half_lives.append(j)
                break
        else:
            half_lives.append(120)  # Cap at 120 days

        # Skip consecutive shock days
        while i < len(shock_dates) - 1:
            next_loc = r_squared.index.get_loc(shock_dates[i + 1])
            if next_loc - r_squared.index.get_loc(shock_dates[i]) <= 5:
                i += 1
            else:
                break
        i += 1

    if len(half_lives) < 2:
        return np.nan
    return np.median(half_lives)


# ============================================================
# 3. ROLLING GARCH HALF-LIFE ESTIMATION
# ============================================================
print()
print("=" * 70)
print("SECTION 3: Rolling GARCH Half-Life Estimation (OOS)")
print("=" * 70)

all_results = {}

for ticker in ASSETS:
    print(f"\n{'='*60}")
    print(f"Processing {ticker}")
    print(f"{'='*60}")

    returns = return_data[ticker]
    ret_pct = returns * 100
    r_squared = returns ** 2

    # Align with OOS period
    oos_mask = returns.index >= OOS_START
    oos_dates = returns.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  No OOS data for {ticker}, skipping.")
        continue

    first_oos_loc = returns.index.get_loc(oos_dates[0])
    if first_oos_loc < GARCH_WINDOW:
        print(f"  Insufficient history for {ticker} (need {GARCH_WINDOW}, have {first_oos_loc})")
        continue

    print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()}, N_oos={len(oos_dates)}")

    # ---- Method A: Rolling GARCH Half-Life ----
    garch_hl_series = {}
    garch_persistence_series = {}
    garch_var_forecast = {}

    last_params = None
    n_fits = 0

    for idx_num, t in enumerate(range(first_oos_loc, len(returns))):
        date = returns.index[t]

        # Refit GARCH periodically
        if idx_num % REFIT_FREQ == 0 or last_params is None:
            train_data = ret_pct.iloc[t - GARCH_WINDOW:t]
            try:
                model = arch_model(train_data, vol='Garch', p=1, o=1, q=1, dist='t')
                res = model.fit(disp='off', show_warning=False)
                omega = res.params.get('omega', np.nan)
                alpha = res.params.get('alpha[1]', np.nan)
                gamma_param = res.params.get('gamma[1]', np.nan)
                beta = res.params.get('beta[1]', np.nan)
                last_params = (omega, alpha, gamma_param, beta)
                n_fits += 1
            except Exception:
                pass

        if last_params is not None:
            omega, alpha, gamma_param, beta = last_params
            hl = garch_half_life(alpha, beta, gamma_param)
            persistence = alpha + beta + gamma_param / 2.0

            garch_hl_series[date] = hl
            garch_persistence_series[date] = persistence

            # 1-step variance forecast
            if t > 0:
                prev_ret = ret_pct.iloc[t - 1]
                prev_var = prev_ret ** 2  # Simplified
                indicator = 1.0 if prev_ret < 0 else 0.0
                var_forecast = omega + (alpha + gamma_param * indicator) * prev_ret ** 2 + beta * prev_var
                garch_var_forecast[date] = var_forecast / 10000  # Convert back from pct²

    garch_hl = pd.Series(garch_hl_series)
    garch_persist = pd.Series(garch_persistence_series)
    garch_vf = pd.Series(garch_var_forecast)

    print(f"  GARCH fits: {n_fits}")
    print(f"  GARCH HL: mean={garch_hl.mean():.1f}d, median={garch_hl.median():.1f}d, "
          f"std={garch_hl.std():.1f}d, range=[{garch_hl.min():.1f}, {garch_hl.max():.1f}]")
    print(f"  Persistence: mean={garch_persist.mean():.4f}, "
          f"range=[{garch_persist.min():.4f}, {garch_persist.max():.4f}]")

    # ---- Method B: Rolling EWMA ACF Half-Life ----
    ewma_hl_series = {}

    for t in range(first_oos_loc, len(returns)):
        date = returns.index[t]
        if t >= ROLLING_HL_WINDOW:
            window_r2 = r_squared.iloc[t - ROLLING_HL_WINDOW:t]
            hl_ewma = ewma_half_life_from_acf(window_r2.values)
            ewma_hl_series[date] = hl_ewma

    ewma_hl = pd.Series(ewma_hl_series)
    if len(ewma_hl) > 0:
        print(f"  EWMA ACF HL: mean={ewma_hl.mean():.1f}d, median={ewma_hl.median():.1f}d, "
              f"std={ewma_hl.std():.1f}d")

    # ---- Method C: Rolling Direct Half-Life ----
    direct_hl_series = {}

    for t in range(first_oos_loc, len(returns)):
        date = returns.index[t]
        if t >= ROLLING_HL_WINDOW:
            window_r2 = r_squared.iloc[t - ROLLING_HL_WINDOW:t]
            hl_direct = direct_half_life(window_r2)
            direct_hl_series[date] = hl_direct

    direct_hl = pd.Series(direct_hl_series)
    if len(direct_hl) > 0 and not direct_hl.isna().all():
        print(f"  Direct HL: mean={direct_hl.mean():.1f}d, median={direct_hl.median():.1f}d, "
              f"std={direct_hl.std():.1f}d")

    # Store for later analysis
    all_results[ticker] = {
        'garch_hl': garch_hl,
        'garch_persist': garch_persist,
        'garch_var_forecast': garch_vf,
        'ewma_hl': ewma_hl,
        'direct_hl': direct_hl,
        'returns': returns,
        'r_squared': r_squared,
    }

# ============================================================
# 4. HALF-LIFE AS PREDICTOR OF FUTURE VOLATILITY
# ============================================================
print()
print("=" * 70)
print("SECTION 4: Half-Life as Predictor of Future Volatility")
print("=" * 70)
print("Question: Does HL predict future realized vol (5d, 22d forward)?")
print()

predictor_results = {}

for ticker in ASSETS:
    if ticker not in all_results:
        continue

    res = all_results[ticker]
    garch_hl = res['garch_hl']
    returns = res['returns']
    r_squared = res['r_squared']

    # Compute forward realized vol (5d and 22d)
    rv_5d = r_squared.rolling(5).sum().shift(-5)   # Forward 5-day RV
    rv_22d = r_squared.rolling(22).sum().shift(-22)  # Forward 22-day RV

    # Align data
    common_idx = garch_hl.index.intersection(rv_5d.dropna().index).intersection(rv_22d.dropna().index)

    # Also align VIX
    vix_aligned = vix_series.reindex(common_idx).dropna()
    common_idx = common_idx.intersection(vix_aligned.index)

    if len(common_idx) < 50:
        print(f"  {ticker}: Insufficient aligned data ({len(common_idx)} obs), skipping.")
        continue

    hl = garch_hl.reindex(common_idx).dropna()
    rv5 = rv_5d.reindex(hl.index)
    rv22 = rv_22d.reindex(hl.index)
    vix = vix_aligned.reindex(hl.index)

    # Drop any remaining NaNs
    valid = hl.notna() & rv5.notna() & rv22.notna() & vix.notna()
    hl = hl[valid]
    rv5 = rv5[valid]
    rv22 = rv22[valid]
    vix = vix[valid]

    print(f"\n  {ticker} (N={len(hl)}):")

    # --- Raw correlation: HL vs future RV ---
    r_5d, p_5d = stats.pearsonr(hl, rv5)
    r_22d, p_22d = stats.pearsonr(hl, rv22)
    print(f"    Raw corr(HL, RV_5d_fwd):  r={r_5d:.4f}, p={p_5d:.4f}")
    print(f"    Raw corr(HL, RV_22d_fwd): r={r_22d:.4f}, p={p_22d:.4f}")

    # --- Partial correlation controlling for VIX ---
    # partial_r(HL, RV | VIX) = (r_xy - r_xz * r_yz) / sqrt((1-r_xz²)(1-r_yz²))
    def partial_corr(x, y, z):
        r_xy = np.corrcoef(x, y)[0, 1]
        r_xz = np.corrcoef(x, z)[0, 1]
        r_yz = np.corrcoef(y, z)[0, 1]

        numerator = r_xy - r_xz * r_yz
        denominator = np.sqrt((1 - r_xz**2) * (1 - r_yz**2))
        if denominator < 1e-10:
            return np.nan, 1.0

        pr = numerator / denominator
        n = len(x)
        t_stat = pr * np.sqrt((n - 3) / (1 - pr**2)) if abs(pr) < 1 else 0
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n - 3))
        return pr, p_val

    pr_5d, pp_5d = partial_corr(hl.values, rv5.values, vix.values)
    pr_22d, pp_22d = partial_corr(hl.values, rv22.values, vix.values)
    print(f"    Partial r(HL, RV_5d | VIX):  pr={pr_5d:.4f}, p={pp_5d:.4f}")
    print(f"    Partial r(HL, RV_22d | VIX): pr={pr_22d:.4f}, p={pp_22d:.4f}")

    # --- Regime analysis: Short HL vs Long HL ---
    median_hl = hl.median()
    fast_mask = hl < median_hl
    slow_mask = hl >= median_hl

    rv5_fast = rv5[fast_mask].mean()
    rv5_slow = rv5[slow_mask].mean()
    rv22_fast = rv22[fast_mask].mean()
    rv22_slow = rv22[slow_mask].mean()

    # T-test for difference
    t_5d, tp_5d = stats.ttest_ind(rv5[fast_mask], rv5[slow_mask])
    t_22d, tp_22d = stats.ttest_ind(rv22[fast_mask], rv22[slow_mask])

    print(f"    Median HL = {median_hl:.1f}d")
    print(f"    Fast HL regime (<{median_hl:.0f}d): RV_5d={rv5_fast*1e4:.2f}bps², RV_22d={rv22_fast*1e4:.2f}bps²")
    print(f"    Slow HL regime (>={median_hl:.0f}d): RV_5d={rv5_slow*1e4:.2f}bps², RV_22d={rv22_slow*1e4:.2f}bps²")
    print(f"    Diff t-test 5d:  t={t_5d:.3f}, p={tp_5d:.4f}")
    print(f"    Diff t-test 22d: t={t_22d:.3f}, p={tp_22d:.4f}")

    predictor_results[ticker] = {
        'n_obs': len(hl),
        'raw_r_5d': r_5d, 'raw_p_5d': p_5d,
        'raw_r_22d': r_22d, 'raw_p_22d': p_22d,
        'partial_r_5d': pr_5d, 'partial_p_5d': pp_5d,
        'partial_r_22d': pr_22d, 'partial_p_22d': pp_22d,
        'median_hl': median_hl,
        'rv5_fast': rv5_fast, 'rv5_slow': rv5_slow,
        'rv22_fast': rv22_fast, 'rv22_slow': rv22_slow,
        'regime_t_5d': t_5d, 'regime_p_5d': tp_5d,
        'regime_t_22d': t_22d, 'regime_p_22d': tp_22d,
    }

# ============================================================
# 5. STRATEGY IMPLICATIONS: REBALANCE FREQUENCY vs HL REGIME
# ============================================================
print()
print("=" * 70)
print("SECTION 5: Rebalance Frequency vs Half-Life Regime")
print("=" * 70)
print("Test: Does optimal rebalancing frequency depend on HL regime?")
print("  Short HL → daily rebalancing should have more value")
print("  Long HL → monthly rebalancing sufficient")
print()

# Use SPY as primary test case (most liquid, longest history)
strategy_results = {}

for ticker in ['SPY', 'QQQ', 'GLD']:
    if ticker not in all_results:
        continue

    res = all_results[ticker]
    garch_hl = res['garch_hl']
    returns = res['returns']

    # Simple 12/VIX strategy with different rebalance frequencies
    vix_aligned = vix_series.reindex(returns.index).ffill()

    # Filter to OOS period
    oos_mask = returns.index >= OOS_START
    oos_returns = returns[oos_mask]
    oos_vix = vix_aligned[oos_mask]
    oos_hl = garch_hl.reindex(oos_returns.index)

    # Drop NaNs
    valid = oos_returns.notna() & oos_vix.notna() & oos_hl.notna()
    oos_returns = oos_returns[valid]
    oos_vix = oos_vix[valid]
    oos_hl = oos_hl[valid]

    if len(oos_returns) < 100:
        print(f"  {ticker}: Insufficient OOS data, skipping strategy test.")
        continue

    print(f"\n  {ticker} (N_oos={len(oos_returns)}):")

    # Split into fast and slow HL regimes
    median_hl = oos_hl.median()
    fast_regime = oos_hl < median_hl
    slow_regime = oos_hl >= median_hl

    # VT weight: 12/VIX, capped at [0, 1.5]
    # Use lagged VIX (t-1) to avoid look-ahead
    vt_weight_daily = np.clip(12.0 / oos_vix.shift(1), 0, 1.5)

    # Monthly rebalancing: hold weight for 22 days
    vt_weight_monthly = vt_weight_daily.copy()
    last_rebal = 0
    last_weight = vt_weight_daily.iloc[0]
    for i in range(len(vt_weight_monthly)):
        if i - last_rebal >= 22:
            last_weight = vt_weight_daily.iloc[i]
            last_rebal = i
        vt_weight_monthly.iloc[i] = last_weight

    # HL-adaptive rebalancing: daily if fast HL, monthly if slow HL
    vt_weight_adaptive = vt_weight_daily.copy()
    last_rebal_adaptive = 0
    last_weight_adaptive = vt_weight_daily.iloc[0]
    for i in range(len(vt_weight_adaptive)):
        current_hl = oos_hl.iloc[i]
        if np.isnan(current_hl):
            rebal_freq = 22
        elif current_hl < median_hl:
            rebal_freq = 1  # Daily
        else:
            rebal_freq = 22  # Monthly

        if i - last_rebal_adaptive >= rebal_freq:
            last_weight_adaptive = vt_weight_daily.iloc[i]
            last_rebal_adaptive = i
        vt_weight_adaptive.iloc[i] = last_weight_adaptive

    # Compute strategy returns
    strat_daily = oos_returns * vt_weight_daily
    strat_monthly = oos_returns * vt_weight_monthly
    strat_adaptive = oos_returns * vt_weight_adaptive
    strat_bh = oos_returns  # Buy & hold

    # Sharpe ratios (annualized)
    def ann_sharpe(r):
        if r.std() == 0:
            return 0
        return r.mean() / r.std() * np.sqrt(252)

    def max_dd(r):
        cum = (1 + r).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        return dd.min()

    sharpe_daily = ann_sharpe(strat_daily)
    sharpe_monthly = ann_sharpe(strat_monthly)
    sharpe_adaptive = ann_sharpe(strat_adaptive)
    sharpe_bh = ann_sharpe(strat_bh)

    mdd_daily = max_dd(strat_daily)
    mdd_monthly = max_dd(strat_monthly)
    mdd_adaptive = max_dd(strat_adaptive)
    mdd_bh = max_dd(strat_bh)

    # Turnover
    turnover_daily = np.abs(vt_weight_daily.diff()).sum() / (len(vt_weight_daily) / 252)
    turnover_monthly = np.abs(vt_weight_monthly.diff()).sum() / (len(vt_weight_monthly) / 252)
    turnover_adaptive = np.abs(vt_weight_adaptive.diff()).sum() / (len(vt_weight_adaptive) / 252)

    print(f"    {'Strategy':<20} {'Sharpe':>8} {'MDD':>8} {'Turnover/yr':>12}")
    print(f"    {'-'*48}")
    print(f"    {'Buy & Hold':<20} {sharpe_bh:>8.3f} {mdd_bh:>8.1%} {'N/A':>12}")
    print(f"    {'VT Daily Rebal':<20} {sharpe_daily:>8.3f} {mdd_daily:>8.1%} {turnover_daily:>12.1f}")
    print(f"    {'VT Monthly Rebal':<20} {sharpe_monthly:>8.3f} {mdd_monthly:>8.1%} {turnover_monthly:>12.1f}")
    print(f"    {'VT HL-Adaptive':<20} {sharpe_adaptive:>8.3f} {mdd_adaptive:>8.1%} {turnover_adaptive:>12.1f}")

    # Conditional performance: daily vs monthly in each regime
    for regime_name, regime_mask in [('Fast HL', fast_regime), ('Slow HL', slow_regime)]:
        n_regime = regime_mask.sum()
        if n_regime < 30:
            print(f"    {regime_name}: too few obs ({n_regime})")
            continue

        s_daily_r = ann_sharpe(strat_daily[regime_mask])
        s_monthly_r = ann_sharpe(strat_monthly[regime_mask])

        # DM-like test: is daily better than monthly in this regime?
        d_i = strat_daily[regime_mask] - strat_monthly[regime_mask]
        if d_i.std() > 0:
            dm_t = d_i.mean() / (d_i.std() / np.sqrt(len(d_i)))
            dm_p = 2 * (1 - stats.t.cdf(abs(dm_t), len(d_i) - 1))
        else:
            dm_t, dm_p = 0, 1

        print(f"    {regime_name} (N={n_regime}): Daily Sharpe={s_daily_r:.3f}, Monthly Sharpe={s_monthly_r:.3f}, "
              f"DM t={dm_t:.3f}, p={dm_p:.4f}")

    strategy_results[ticker] = {
        'sharpe_daily': sharpe_daily,
        'sharpe_monthly': sharpe_monthly,
        'sharpe_adaptive': sharpe_adaptive,
        'sharpe_bh': sharpe_bh,
        'mdd_daily': mdd_daily,
        'mdd_monthly': mdd_monthly,
        'mdd_adaptive': mdd_adaptive,
        'mdd_bh': mdd_bh,
        'turnover_daily': turnover_daily,
        'turnover_monthly': turnover_monthly,
        'turnover_adaptive': turnover_adaptive,
        'median_hl': median_hl,
    }

# ============================================================
# 6. CROSS-ASSET HALF-LIFE STRUCTURE
# ============================================================
print()
print("=" * 70)
print("SECTION 6: Cross-Asset Half-Life Structure")
print("=" * 70)
print("How does mean-reversion speed vary across asset classes?")
print()

cross_asset_hl = {}

for ticker in ASSETS:
    if ticker not in all_results:
        continue

    res = all_results[ticker]
    garch_hl = res['garch_hl']
    ewma_hl = res['ewma_hl']
    direct_hl = res['direct_hl']

    # Full sample statistics
    row = {
        'garch_hl_mean': garch_hl.mean(),
        'garch_hl_median': garch_hl.median(),
        'garch_hl_std': garch_hl.std(),
        'garch_hl_min': garch_hl.min(),
        'garch_hl_max': garch_hl.max(),
    }

    if len(ewma_hl) > 0:
        row['ewma_hl_mean'] = ewma_hl.mean()
        row['ewma_hl_median'] = ewma_hl.median()

    if len(direct_hl) > 0 and not direct_hl.isna().all():
        row['direct_hl_mean'] = direct_hl.mean()
        row['direct_hl_median'] = direct_hl.median()

    cross_asset_hl[ticker] = row

# Print cross-asset comparison table
print(f"  {'Asset':<10} {'GARCH HL':>10} {'EWMA HL':>10} {'Direct HL':>10} {'GARCH HL Std':>12}")
print(f"  {'-'*52}")
for ticker in ASSETS:
    if ticker not in cross_asset_hl:
        continue
    r = cross_asset_hl[ticker]
    ewma_str = f"{r.get('ewma_hl_median', np.nan):.1f}" if 'ewma_hl_median' in r else "N/A"
    direct_str = f"{r.get('direct_hl_median', np.nan):.1f}" if 'direct_hl_median' in r else "N/A"
    print(f"  {ticker:<10} {r['garch_hl_median']:>10.1f} {ewma_str:>10} {direct_str:>10} {r['garch_hl_std']:>12.1f}")

# Cross-method correlation (for assets with all 3 methods)
print(f"\n  Cross-method agreement (median HL, days):")
garch_medians = []
ewma_medians = []
direct_medians = []
asset_labels = []
for ticker in ASSETS:
    if ticker not in cross_asset_hl:
        continue
    r = cross_asset_hl[ticker]
    if 'ewma_hl_median' in r and 'direct_hl_median' in r:
        garch_medians.append(r['garch_hl_median'])
        ewma_medians.append(r['ewma_hl_median'])
        direct_medians.append(r['direct_hl_median'])
        asset_labels.append(ticker)

if len(garch_medians) >= 3:
    r_ge, p_ge = stats.pearsonr(garch_medians, ewma_medians)
    r_gd, p_gd = stats.pearsonr(garch_medians, direct_medians)
    r_ed, p_ed = stats.pearsonr(ewma_medians, direct_medians)
    print(f"    GARCH vs EWMA:   r={r_ge:.3f} (p={p_ge:.4f})")
    print(f"    GARCH vs Direct: r={r_gd:.3f} (p={p_gd:.4f})")
    print(f"    EWMA vs Direct:  r={r_ed:.3f} (p={p_ed:.4f})")
else:
    print(f"    Only {len(garch_medians)} assets with all 3 methods — insufficient for correlation.")

# ============================================================
# 7. FORMAL STATISTICAL TESTS
# ============================================================
print()
print("=" * 70)
print("SECTION 7: Formal Statistical Tests")
print("=" * 70)

# A. DM test: Does HL-adaptive VT outperform fixed-frequency VT?
print("\n  A. Diebold-Mariano Test: HL-Adaptive vs Fixed Monthly VT")
print(f"     H0: Adaptive and Monthly VT have equal Sharpe")
for ticker in ['SPY', 'QQQ', 'GLD']:
    if ticker not in all_results:
        continue

    res = all_results[ticker]
    returns = res['returns']
    garch_hl = res['garch_hl']

    oos_mask = returns.index >= OOS_START
    oos_returns = returns[oos_mask]
    oos_vix = vix_series.reindex(oos_returns.index).ffill()
    oos_hl = garch_hl.reindex(oos_returns.index)

    valid = oos_returns.notna() & oos_vix.notna() & oos_hl.notna()
    oos_returns = oos_returns[valid]
    oos_vix = oos_vix[valid]
    oos_hl = oos_hl[valid]

    if len(oos_returns) < 100:
        continue

    median_hl_val = oos_hl.median()

    # Rebuild strategies
    vt_w_daily = np.clip(12.0 / oos_vix.shift(1), 0, 1.5)

    vt_w_monthly = vt_w_daily.copy()
    last_r = 0
    last_w = vt_w_daily.iloc[0]
    for i in range(len(vt_w_monthly)):
        if i - last_r >= 22:
            last_w = vt_w_daily.iloc[i]
            last_r = i
        vt_w_monthly.iloc[i] = last_w

    vt_w_adaptive = vt_w_daily.copy()
    last_r_a = 0
    last_w_a = vt_w_daily.iloc[0]
    for i in range(len(vt_w_adaptive)):
        current_hl_val = oos_hl.iloc[i]
        freq = 1 if (not np.isnan(current_hl_val) and current_hl_val < median_hl_val) else 22
        if i - last_r_a >= freq:
            last_w_a = vt_w_daily.iloc[i]
            last_r_a = i
        vt_w_adaptive.iloc[i] = last_w_a

    ret_monthly = oos_returns * vt_w_monthly
    ret_adaptive = oos_returns * vt_w_adaptive

    # DM test on return differences
    d = ret_adaptive - ret_monthly
    d = d.dropna()
    if len(d) > 0 and d.std() > 0:
        dm_stat = d.mean() / (d.std() / np.sqrt(len(d)))
        dm_p = 2 * (1 - stats.t.cdf(abs(dm_stat), len(d) - 1))
        print(f"     {ticker}: DM t={dm_stat:.3f}, p={dm_p:.4f} "
              f"({'Adaptive wins' if dm_stat > 0 and dm_p < 0.05 else 'No sig. difference'})")
    else:
        print(f"     {ticker}: Cannot compute DM test")

# B. Harvey threshold check
print(f"\n  B. Harvey (2016) Threshold Check (t > 3.0 for new strategy claims)")
for ticker in ['SPY', 'QQQ', 'GLD']:
    if ticker not in predictor_results:
        continue
    pr = predictor_results[ticker]

    # t-stat for partial correlation
    n = pr['n_obs']
    pr_val = pr['partial_r_22d']
    if abs(pr_val) < 1:
        t_stat = pr_val * np.sqrt((n - 3) / (1 - pr_val**2))
    else:
        t_stat = 0

    harvey_pass = abs(t_stat) > 3.0
    print(f"     {ticker}: partial_r(HL, RV22d|VIX) = {pr_val:.4f}, t = {t_stat:.2f} "
          f"{'PASS' if harvey_pass else 'FAIL'} Harvey")

# C. Granger causality: Does HL Granger-cause future RV?
print(f"\n  C. Granger Causality: HL → RV (5d, 22d)")
try:
    from statsmodels.tsa.stattools import grangercausalitytests

    for ticker in ['SPY', 'QQQ']:
        if ticker not in all_results:
            continue

        res = all_results[ticker]
        garch_hl = res['garch_hl']
        r_squared = res['r_squared']

        rv_5d = r_squared.rolling(5).mean()

        # Align
        common = garch_hl.index.intersection(rv_5d.dropna().index)
        if len(common) < 100:
            continue

        df_gc = pd.DataFrame({
            'rv5': rv_5d.reindex(common),
            'hl': garch_hl.reindex(common)
        }).dropna()

        if len(df_gc) < 50:
            continue

        print(f"     {ticker} (N={len(df_gc)}):")
        # Test with lags 1-5
        try:
            gc_results = grangercausalitytests(df_gc[['rv5', 'hl']].values, maxlag=5, verbose=False)
            for lag in [1, 3, 5]:
                f_stat = gc_results[lag][0]['ssr_ftest'][0]
                f_p = gc_results[lag][0]['ssr_ftest'][1]
                print(f"       Lag {lag}: F={f_stat:.3f}, p={f_p:.4f} "
                      f"({'sig' if f_p < 0.05 else 'n.s.'})")
        except Exception as e:
            print(f"       GC test error: {e}")
except ImportError:
    print("     statsmodels not available for Granger test")

# ============================================================
# 8. HL DYNAMICS: TIME-VARYING PERSISTENCE
# ============================================================
print()
print("=" * 70)
print("SECTION 8: Half-Life Dynamics and Regime Detection")
print("=" * 70)

for ticker in ['SPY', 'BTC-USD']:
    if ticker not in all_results:
        continue

    res = all_results[ticker]
    garch_hl = res['garch_hl']

    if len(garch_hl) == 0:
        continue

    print(f"\n  {ticker}:")

    # Quartile analysis
    q25 = garch_hl.quantile(0.25)
    q50 = garch_hl.quantile(0.50)
    q75 = garch_hl.quantile(0.75)
    print(f"    HL quartiles: Q25={q25:.1f}d, Q50={q50:.1f}d, Q75={q75:.1f}d")

    # Fraction of time in fast/slow regimes
    fast_pct = (garch_hl < HL_THRESHOLD_FAST).mean() * 100
    slow_pct = (garch_hl > HL_THRESHOLD_SLOW).mean() * 100
    print(f"    Time in fast regime (HL<{HL_THRESHOLD_FAST}d): {fast_pct:.1f}%")
    print(f"    Time in slow regime (HL>{HL_THRESHOLD_SLOW}d): {slow_pct:.1f}%")

    # Autocorrelation of HL (is it persistent?)
    if len(garch_hl) > 22:
        ac1 = garch_hl.autocorr(lag=1)
        ac5 = garch_hl.autocorr(lag=5)
        ac22 = garch_hl.autocorr(lag=22)
        print(f"    HL autocorrelation: AC(1)={ac1:.3f}, AC(5)={ac5:.3f}, AC(22)={ac22:.3f}")

    # HL around crises (if applicable)
    crisis_periods = {
        'COVID crash': ('2020-02-20', '2020-04-30'),
        '2022 bear': ('2022-01-03', '2022-10-31'),
        '2023 banking': ('2023-03-01', '2023-04-30'),
    }

    for crisis_name, (start, end) in crisis_periods.items():
        crisis_hl = garch_hl[(garch_hl.index >= start) & (garch_hl.index <= end)]
        if len(crisis_hl) > 0:
            normal_hl = garch_hl[(garch_hl.index < start) | (garch_hl.index > end)]
            print(f"    {crisis_name}: HL={crisis_hl.mean():.1f}d vs normal={normal_hl.mean():.1f}d")

# ============================================================
# 9. COMPREHENSIVE SUMMARY
# ============================================================
print()
print("=" * 70)
print("SECTION 9: Comprehensive Summary")
print("=" * 70)

# Count significant findings
n_sig_raw = sum(1 for t in ASSETS if t in predictor_results and predictor_results[t]['raw_p_22d'] < 0.05)
n_sig_partial = sum(1 for t in ASSETS if t in predictor_results and predictor_results[t]['partial_p_22d'] < 0.05)
n_tested = len(predictor_results)

print(f"\n  A. Half-Life as Vol Predictor:")
print(f"     Raw corr(HL, RV22d) significant: {n_sig_raw}/{n_tested} assets")
print(f"     Partial r(HL, RV22d | VIX) significant: {n_sig_partial}/{n_tested} assets")

print(f"\n  B. Strategy Implications:")
for ticker in ['SPY', 'QQQ', 'GLD']:
    if ticker not in strategy_results:
        continue
    sr = strategy_results[ticker]
    print(f"     {ticker}: Daily Sharpe={sr['sharpe_daily']:.3f}, Monthly={sr['sharpe_monthly']:.3f}, "
          f"Adaptive={sr['sharpe_adaptive']:.3f}")
    improvement = sr['sharpe_adaptive'] - sr['sharpe_monthly']
    print(f"       Adaptive vs Monthly improvement: {improvement:+.3f} Sharpe")

print(f"\n  C. Cross-Asset HL Structure:")
for ticker in ASSETS:
    if ticker not in cross_asset_hl:
        continue
    r = cross_asset_hl[ticker]
    asset_class = {
        'SPY': 'US Equity', 'QQQ': 'US Tech', 'GLD': 'Gold',
        'TLT': 'US Bond', 'BTC-USD': 'Crypto'
    }.get(ticker, ticker)
    print(f"     {ticker:<10} ({asset_class}): median HL = {r['garch_hl_median']:.1f}d, "
          f"std = {r['garch_hl_std']:.1f}d")

# Overall conclusion
print(f"\n  D. Key Conclusions:")
any_significant = n_sig_partial > 0
adaptive_helps = any(
    strategy_results.get(t, {}).get('sharpe_adaptive', 0) > strategy_results.get(t, {}).get('sharpe_monthly', 0) + 0.05
    for t in ['SPY', 'QQQ', 'GLD']
)

if any_significant:
    print(f"     1. HL has predictive power for future vol BEYOND VIX ({n_sig_partial}/{n_tested} assets sig)")
else:
    print(f"     1. HL does NOT add predictive power beyond VIX (0/{n_tested} partial r sig)")
    print(f"        → Consistent with VIX sufficient statistic finding")

if adaptive_helps:
    print(f"     2. HL-adaptive rebalancing improves VT performance")
else:
    print(f"     2. HL-adaptive rebalancing does NOT significantly improve VT")
    print(f"        → Monthly rebalancing remains sufficient regardless of HL regime")

print(f"     3. HL varies substantially across asset classes:")
hl_medians_sorted = sorted(
    [(t, cross_asset_hl[t]['garch_hl_median']) for t in ASSETS if t in cross_asset_hl],
    key=lambda x: x[1]
)
for t, hl_med in hl_medians_sorted:
    print(f"        {t}: {hl_med:.1f}d")

# ============================================================
# 10. SAVE RESULTS
# ============================================================
print()
print("=" * 70)
print("SECTION 10: Save Results")
print("=" * 70)

output = {
    'experiment': 'K211',
    'title': 'Volatility Mean Reversion Speed as Predictive Feature',
    'timestamp': datetime.now().isoformat(),
    'config': {
        'assets': ASSETS,
        'oos_period': f'{OOS_START} to {OOS_END}',
        'garch_window': GARCH_WINDOW,
        'rolling_hl_window': ROLLING_HL_WINDOW,
        'refit_freq': REFIT_FREQ,
    },
    'predictor_results': {},
    'strategy_results': {},
    'cross_asset_hl': {},
}

for ticker, pr in predictor_results.items():
    output['predictor_results'][ticker] = {
        k: (float(v) if isinstance(v, (np.floating, np.integer, float, int)) else v)
        for k, v in pr.items()
    }

for ticker, sr in strategy_results.items():
    output['strategy_results'][ticker] = {
        k: (float(v) if isinstance(v, (np.floating, np.integer, float, int)) else v)
        for k, v in sr.items()
    }

for ticker, ca in cross_asset_hl.items():
    output['cross_asset_hl'][ticker] = {
        k: (float(v) if isinstance(v, (np.floating, np.integer, float, int)) else v)
        for k, v in ca.items()
    }

# Summary
output['summary'] = {
    'hl_predicts_vol_beyond_vix': any_significant,
    'n_sig_partial': n_sig_partial,
    'n_tested': n_tested,
    'adaptive_rebal_helps': adaptive_helps,
    'conclusion': (
        'HL adds predictive power beyond VIX' if any_significant
        else 'HL does NOT add predictive power beyond VIX (consistent with VIX sufficiency)'
    ),
}

output_path = 'experiments/k211_mean_reversion_speed_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Results saved to {output_path}")

print()
print("=" * 70)
print("K211 COMPLETE")
print("=" * 70)
