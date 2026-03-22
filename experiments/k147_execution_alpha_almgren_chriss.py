"""
K147: Execution Alpha — GJR-GARCH for Optimal Liquidation (Almgren-Chriss)
===========================================================================
[提出: Gemini R4#4, 執行: Claude]

Research Question:
    What is the bps advantage of using GJR-GARCH vol forecast for an
    Almgren-Chriss optimal liquidation strategy vs a simple 20-day realized
    vol estimate or EWMA(0.97)?

Background:
    Even though GJR-GARCH doesn't provide Sharpe alpha in VT strategies,
    it may save basis points in trade execution. This shifts from
    "predicting vol for VT" to "using vol for execution" — a completely
    new application domain.

Almgren-Chriss Framework (2000):
    For a position of X shares to be liquidated over T periods:
    - Optimal trajectory: n_k = X * sinh(kappa*(T-t_k)) / sinh(kappa*T)
    - kappa = sqrt(lambda * sigma^2 / eta)
    - sigma^2 = volatility estimate (THIS IS WHERE GARCH MATTERS)
    - eta = temporary market impact coefficient
    - lambda = risk aversion parameter

    Better vol forecast -> better kappa -> more efficient liquidation trajectory.

Implementation:
    Part A: Daily proxy analysis (full OOS 2020-2024, ~1200 days)
    Part B: 5-min intraday execution simulation (47 days, PRELIMINARY)
"""

import sys
import os
import warnings
import glob
import json
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

# ==================================================================
# CONFIGURATION
# ==================================================================
POSITION_VALUE = 100_000_000  # $100M position to liquidate
N_INTRADAY_PERIODS = 78       # 390 min / 5 min = 78 five-minute bars
RISK_AVERSION = 1e-6          # lambda: risk aversion
TEMP_IMPACT_SCALE = 0.1       # eta scaling factor
PERM_IMPACT = 0.0             # no permanent impact in baseline
GARCH_WINDOW = 2000           # rolling window for GARCH estimation
RV_WINDOW = 20                # 20-day realized vol baseline
EWMA_LAMBDA = 0.97            # EWMA decay factor

DATA_START = "2010-01-01"     # pre-OOS for GARCH warm-up
OOS_START = "2020-01-01"
OOS_END = "2026-03-21"

print("=" * 80)
print("K147: EXECUTION ALPHA — GJR-GARCH FOR OPTIMAL LIQUIDATION")
print("[提出: Gemini R4#4, 執行: Claude]")
print("=" * 80)
print(f"\nPosition: ${POSITION_VALUE/1e6:.0f}M sell order")
print(f"Liquidation horizon: 1 trading day ({N_INTRADAY_PERIODS} x 5-min bars)")
print(f"GARCH window: {GARCH_WINDOW}, RV window: {RV_WINDOW}")
print(f"OOS period: {OOS_START} to {OOS_END}")

# ==================================================================
# 1. DOWNLOAD DAILY DATA
# ==================================================================
print("\n" + "=" * 80)
print("[1/7] Downloading SPY daily data...")
print("=" * 80)

spy_raw = yf.download("SPY", start=DATA_START, end=OOS_END, progress=False, auto_adjust=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)

spy = pd.DataFrame({
    'Close': spy_raw['Close'].values,
    'Volume': spy_raw['Volume'].values,
    'High': spy_raw['High'].values,
    'Low': spy_raw['Low'].values,
    'Open': spy_raw['Open'].values,
}, index=spy_raw.index)
spy.index = pd.to_datetime(spy.index)
spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index

spy['returns'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['returns_sq'] = spy['returns'] ** 2
spy = spy.dropna()

print(f"SPY data: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} days)")

# ==================================================================
# 2. COMPUTE VOL ESTIMATES (3 methods)
# ==================================================================
print("\n" + "=" * 80)
print("[2/7] Computing volatility estimates (GJR-GARCH, RV20, EWMA)...")
print("=" * 80)

oos_mask = spy.index >= OOS_START
oos_indices = spy.index[oos_mask]
print(f"OOS days: {len(oos_indices)}")

# --- Storage for vol forecasts ---
vol_garch = {}
vol_rv20 = {}
vol_ewma = {}

# --- 20-day Realized Vol (baseline) ---
spy['rv20'] = spy['returns'].rolling(RV_WINDOW).std() * np.sqrt(252)
for dt in oos_indices:
    loc = spy.index.get_loc(dt)
    if loc >= RV_WINDOW:
        vol_rv20[dt] = spy['rv20'].iloc[loc]

# --- EWMA(0.97) ---
ewma_var = np.zeros(len(spy))
ewma_var[0] = spy['returns'].iloc[:20].var()
for i in range(1, len(spy)):
    ewma_var[i] = EWMA_LAMBDA * ewma_var[i-1] + (1 - EWMA_LAMBDA) * spy['returns'].iloc[i] ** 2

spy['ewma_vol'] = np.sqrt(ewma_var) * np.sqrt(252)
for dt in oos_indices:
    loc = spy.index.get_loc(dt)
    vol_ewma[dt] = spy['ewma_vol'].iloc[loc]

# --- GJR-GARCH (rolling window) ---
print("Running GJR-GARCH rolling estimation (this may take ~2 min)...")
n_fit = 0
n_fail = 0
for dt in oos_indices:
    loc = spy.index.get_loc(dt)
    if loc < GARCH_WINDOW:
        continue

    # Use data up to day BEFORE dt for forecasting
    train_returns = spy['returns'].iloc[loc - GARCH_WINDOW:loc].values * 100  # arch expects pct

    try:
        model = arch_model(train_returns, vol='GARCH', p=1, o=1, q=1,
                          dist='normal', mean='Zero', rescale=False)
        result = model.fit(disp='off', show_warning=False)
        fcast = result.forecast(horizon=1)
        # Convert from pct^2 back to decimal annualized vol
        daily_var = fcast.variance.iloc[-1, 0] / 10000
        annual_vol = np.sqrt(daily_var * 252)
        vol_garch[dt] = annual_vol
        n_fit += 1
    except Exception:
        n_fail += 1
        # Fallback to RV20
        vol_garch[dt] = vol_rv20.get(dt, 0.15)

print(f"GJR-GARCH: {n_fit} successful fits, {n_fail} failures")

# Align to common dates
common_dates = sorted(set(vol_garch.keys()) & set(vol_rv20.keys()) & set(vol_ewma.keys()))
print(f"Common OOS dates: {len(common_dates)}")

# ==================================================================
# 3. ALMGREN-CHRISS OPTIMAL EXECUTION FRAMEWORK
# ==================================================================
print("\n" + "=" * 80)
print("[3/7] Setting up Almgren-Chriss optimal execution framework...")
print("=" * 80)

def almgren_chriss_trajectory(sigma_annual, n_periods, total_shares, avg_volume_daily,
                              risk_aversion=RISK_AVERSION, impact_scale=TEMP_IMPACT_SCALE):
    """
    Compute optimal Almgren-Chriss liquidation trajectory.

    Parameters
    ----------
    sigma_annual : float
        Annualized volatility estimate
    n_periods : int
        Number of trading periods (e.g., 78 five-min bars)
    total_shares : float
        Total shares to liquidate
    avg_volume_daily : float
        Average daily volume (shares)
    risk_aversion : float
        Risk aversion parameter lambda
    impact_scale : float
        Temporary impact scaling factor

    Returns
    -------
    trajectory : np.array
        Shares remaining at each period [X, n_1, n_2, ..., 0]
    trade_list : np.array
        Shares to trade in each period
    expected_cost : float
        Expected execution cost (in $)
    expected_risk : float
        Execution risk (variance of cost)
    """
    # Convert to per-period quantities
    sigma_per_period = sigma_annual / np.sqrt(252 * n_periods)

    # Temporary market impact: eta = impact_scale * sigma * V^(-0.5)
    # V is average volume per period
    v_per_period = avg_volume_daily / n_periods
    eta = impact_scale * sigma_per_period * (v_per_period ** (-0.5))

    # Kappa = sqrt(lambda * sigma^2 / eta)
    # This controls how aggressively to front-load
    kappa = np.sqrt(risk_aversion * sigma_per_period**2 / max(eta, 1e-20))

    # Optimal trajectory: remaining shares at time k
    # n_k = X * sinh(kappa * (T - k)) / sinh(kappa * T)
    T = n_periods
    trajectory = np.zeros(n_periods + 1)
    trajectory[0] = total_shares

    sinh_kT = np.sinh(kappa * T)
    if abs(sinh_kT) < 1e-20:
        # kappa ≈ 0 -> TWAP (uniform liquidation)
        for k in range(1, n_periods + 1):
            trajectory[k] = total_shares * (1 - k / n_periods)
    else:
        for k in range(1, n_periods + 1):
            trajectory[k] = total_shares * np.sinh(kappa * (T - k)) / sinh_kT
    trajectory[-1] = 0  # ensure fully liquidated

    # Trade list: shares to sell in each period
    trade_list = -np.diff(trajectory)  # positive = sell

    # Expected cost components
    # Temporary impact cost
    temp_cost = eta * np.sum(trade_list ** 2)

    # Volatility risk (variance of execution cost)
    vol_risk = sigma_per_period**2 * np.sum(trajectory[:-1]**2)

    # Total expected cost (mean-variance)
    expected_cost = temp_cost
    expected_risk = vol_risk

    return trajectory, trade_list, expected_cost, expected_risk, kappa


def compute_implementation_shortfall(trade_list, price_path, arrival_price):
    """
    Compute implementation shortfall given a trade list and actual prices.

    IS = (arrival_price * X - sum(trade_k * price_k)) / (arrival_price * X)
    Positive IS = cost (we sold cheaper than arrival price)
    """
    total_shares = np.sum(trade_list)
    ideal_revenue = arrival_price * total_shares
    actual_revenue = np.sum(trade_list * price_path[:len(trade_list)])

    is_value = (ideal_revenue - actual_revenue) / ideal_revenue
    return is_value  # positive = cost, negative = profit


def simulate_execution_with_impact(trade_list, base_prices, sigma_per_period,
                                    avg_vol_per_period, impact_scale=TEMP_IMPACT_SCALE):
    """
    Simulate execution incorporating market impact on prices.

    The actual execution price includes temporary impact:
    effective_price = base_price - impact_scale * sigma * (trade_size / sqrt(V))
    """
    n = len(trade_list)
    exec_prices = np.zeros(n)

    for k in range(n):
        # Temporary impact: moves price against us
        impact = impact_scale * sigma_per_period * (trade_list[k] / np.sqrt(max(avg_vol_per_period, 1)))
        exec_prices[k] = base_prices[k] - impact  # selling, so impact pushes price down

    return exec_prices


print("Almgren-Chriss framework defined.")
print(f"  Risk aversion (lambda): {RISK_AVERSION}")
print(f"  Temp impact scale: {TEMP_IMPACT_SCALE}")
print(f"  N periods per day: {N_INTRADAY_PERIODS}")

# ==================================================================
# 4. PART A — DAILY PROXY ANALYSIS (full OOS)
# ==================================================================
print("\n" + "=" * 80)
print("[4/7] PART A: Daily proxy analysis (vol forecast quality -> execution cost)")
print("=" * 80)

# For each OOS day, we compare:
# 1. How different the vol estimates are
# 2. How different the resulting kappa (urgency) is
# 3. Expected cost difference under each strategy
# 4. Ex-post optimal vol (using realized vol THAT day) as oracle

results_daily = []

for dt in common_dates:
    loc = spy.index.get_loc(dt)

    # Get vol estimates
    sg = vol_garch[dt]
    sr = vol_rv20[dt]
    se = vol_ewma[dt]

    # "Oracle" = actual realized vol that day (using high-low Parkinson estimator)
    hl = np.log(spy['High'].iloc[loc] / spy['Low'].iloc[loc])
    parkinson_vol = hl / (2 * np.sqrt(np.log(2))) * np.sqrt(252)

    # Average daily volume
    avg_vol = spy['Volume'].iloc[max(0, loc-20):loc].mean()

    # Price and shares
    price = spy['Close'].iloc[loc]
    total_shares = POSITION_VALUE / price

    # Compute trajectories for each vol estimate
    for label, sigma_est in [('GJR-GARCH', sg), ('RV20', sr), ('EWMA', se), ('Oracle', parkinson_vol)]:
        traj, trades, exp_cost, exp_risk, kappa = almgren_chriss_trajectory(
            sigma_est, N_INTRADAY_PERIODS, total_shares, avg_vol
        )

        # Front-loading measure: fraction of shares traded in first quarter
        first_quarter = int(N_INTRADAY_PERIODS * 0.25)
        front_load_pct = np.sum(trades[:first_quarter]) / total_shares

        results_daily.append({
            'date': dt,
            'method': label,
            'sigma_annual': sigma_est,
            'kappa': kappa,
            'expected_cost_bps': exp_cost / POSITION_VALUE * 10000,
            'expected_risk_bps': np.sqrt(exp_risk) / POSITION_VALUE * 10000,
            'front_load_pct': front_load_pct,
            'price': price,
            'total_shares': total_shares,
            'avg_volume': avg_vol,
        })

df_daily = pd.DataFrame(results_daily)

# Compute cross-sectional statistics
print("\n--- Volatility Estimate Comparison ---")
for method in ['GJR-GARCH', 'RV20', 'EWMA', 'Oracle']:
    sub = df_daily[df_daily['method'] == method]
    print(f"\n{method}:")
    print(f"  Mean vol:   {sub['sigma_annual'].mean():.4f}")
    print(f"  Std vol:    {sub['sigma_annual'].std():.4f}")
    print(f"  Mean kappa: {sub['kappa'].mean():.6f}")
    print(f"  Mean front-load: {sub['front_load_pct'].mean():.3f}")
    print(f"  Mean exp cost (bps): {sub['expected_cost_bps'].mean():.4f}")
    print(f"  Mean exp risk (bps): {sub['expected_risk_bps'].mean():.4f}")

# --- Compute vol forecast accuracy relative to oracle ---
print("\n\n--- Vol Forecast Accuracy (vs Parkinson Oracle) ---")
pivot_vol = df_daily.pivot(index='date', columns='method', values='sigma_annual')

for method in ['GJR-GARCH', 'RV20', 'EWMA']:
    error = pivot_vol[method] - pivot_vol['Oracle']
    abs_error = np.abs(error)
    sq_error = error ** 2

    print(f"\n{method} vs Oracle:")
    print(f"  Mean Error (bias):    {error.mean():.4f}")
    print(f"  Mean Abs Error (MAE): {abs_error.mean():.4f}")
    print(f"  RMSE:                 {np.sqrt(sq_error.mean()):.4f}")
    print(f"  Correlation:          {pivot_vol[method].corr(pivot_vol['Oracle']):.4f}")

# --- Kappa divergence and its economic impact ---
print("\n\n--- Kappa (Execution Urgency) Divergence ---")
pivot_kappa = df_daily.pivot(index='date', columns='method', values='kappa')
pivot_cost = df_daily.pivot(index='date', columns='method', values='expected_cost_bps')

# Cost difference: GARCH vs RV20
cost_diff_vs_rv = pivot_cost['GJR-GARCH'] - pivot_cost['RV20']
cost_diff_vs_ewma = pivot_cost['GJR-GARCH'] - pivot_cost['EWMA']
cost_optimal = pivot_cost['Oracle']

# Distance from oracle cost
cost_dist_garch = np.abs(pivot_cost['GJR-GARCH'] - pivot_cost['Oracle'])
cost_dist_rv = np.abs(pivot_cost['RV20'] - pivot_cost['Oracle'])
cost_dist_ewma = np.abs(pivot_cost['EWMA'] - pivot_cost['Oracle'])

print(f"\nExpected cost distance from Oracle (bps):")
print(f"  GJR-GARCH: {cost_dist_garch.mean():.4f} mean, {cost_dist_garch.median():.4f} median")
print(f"  RV20:      {cost_dist_rv.mean():.4f} mean, {cost_dist_rv.median():.4f} median")
print(f"  EWMA:      {cost_dist_ewma.mean():.4f} mean, {cost_dist_ewma.median():.4f} median")

# Statistical test: is GARCH closer to Oracle than RV20?
diff_dist = cost_dist_rv - cost_dist_garch  # positive = GARCH is closer
t_stat, p_val = stats.ttest_1samp(diff_dist, 0)
print(f"\nPaired t-test (RV20 distance - GARCH distance from Oracle):")
print(f"  Mean diff: {diff_dist.mean():.6f} bps (positive = GARCH closer to Oracle)")
print(f"  t-stat: {t_stat:.3f}, p-value: {p_val:.4f}")

diff_dist2 = cost_dist_ewma - cost_dist_garch
t_stat2, p_val2 = stats.ttest_1samp(diff_dist2, 0)
print(f"\nPaired t-test (EWMA distance - GARCH distance from Oracle):")
print(f"  Mean diff: {diff_dist2.mean():.6f} bps (positive = GARCH closer to Oracle)")
print(f"  t-stat: {t_stat2:.3f}, p-value: {p_val2:.4f}")

# ==================================================================
# 5. REGIME-CONDITIONAL ANALYSIS
# ==================================================================
print("\n" + "=" * 80)
print("[5/7] Regime-conditional analysis (high vol vs low vol days)")
print("=" * 80)

# Split by realized vol regimes
oracle_vol = pivot_vol['Oracle']
vol_median = oracle_vol.median()
high_vol_mask = oracle_vol > oracle_vol.quantile(0.75)
low_vol_mask = oracle_vol < oracle_vol.quantile(0.25)
normal_mask = ~high_vol_mask & ~low_vol_mask

for regime_name, mask in [('High Vol (Q4)', high_vol_mask),
                           ('Low Vol (Q1)', low_vol_mask),
                           ('Normal (Q2-Q3)', normal_mask)]:
    regime_dates = mask[mask].index
    n_days = len(regime_dates)

    cd_garch = cost_dist_garch.loc[regime_dates].mean()
    cd_rv = cost_dist_rv.loc[regime_dates].mean()
    cd_ewma = cost_dist_ewma.loc[regime_dates].mean()

    diff_r = (cost_dist_rv - cost_dist_garch).loc[regime_dates]
    t_r, p_r = stats.ttest_1samp(diff_r, 0) if len(diff_r) > 2 else (0, 1)

    print(f"\n{regime_name} ({n_days} days):")
    print(f"  GARCH distance from Oracle: {cd_garch:.4f} bps")
    print(f"  RV20 distance from Oracle:  {cd_rv:.4f} bps")
    print(f"  EWMA distance from Oracle:  {cd_ewma:.4f} bps")
    print(f"  GARCH advantage vs RV20:    {cd_rv - cd_garch:.4f} bps (t={t_r:.2f}, p={p_r:.3f})")

# ==================================================================
# 6. PART B — 5-MIN INTRADAY EXECUTION SIMULATION (PRELIMINARY)
# ==================================================================
print("\n" + "=" * 80)
print("[6/7] PART B: 5-min intraday execution simulation (PRELIMINARY)")
print("=" * 80)

# Look for 5-min data files
intraday_dir = "/Users/yhlai0911/Desktop/volpred-research/data/intraday"
files_5min = sorted(glob.glob(os.path.join(intraday_dir, "SPY_5min_*.csv")))
print(f"Found {len(files_5min)} days of 5-min data")

results_intraday = []

for fpath in files_5min:
    fname = os.path.basename(fpath)
    date_str = fname.replace("SPY_5min_", "").replace(".csv", "")

    try:
        date_ts = pd.Timestamp(date_str)
    except Exception:
        continue

    # Check if this date is in our OOS and has vol estimates
    if date_ts not in vol_garch or date_ts not in vol_rv20:
        continue

    # Read 5-min data
    try:
        df5 = pd.read_csv(fpath, skiprows=[1, 2])  # Skip ticker/blank rows
        if 'Close' not in df5.columns:
            # Try alternative parsing
            df5 = pd.read_csv(fpath, header=[0, 1])
            df5.columns = df5.columns.get_level_values(0)

        # Parse datetime
        if 'Datetime' in df5.columns:
            df5['Datetime'] = pd.to_datetime(df5['Datetime'])
            df5 = df5.set_index('Datetime')
        elif df5.index.dtype == 'object':
            df5.index = pd.to_datetime(df5.index)

        prices = df5['Close'].dropna().values
        volumes = df5['Volume'].dropna().values if 'Volume' in df5.columns else None

        if len(prices) < 10:
            continue

    except Exception as e:
        continue

    n_bars = len(prices)
    arrival_price = prices[0]

    # Get vol estimates for this day
    sg = vol_garch[date_ts]
    sr = vol_rv20[date_ts]
    se = vol_ewma[date_ts]

    # Average daily volume (from daily data)
    if date_ts in spy.index:
        loc = spy.index.get_loc(date_ts)
        avg_daily_vol = spy['Volume'].iloc[max(0, loc-20):loc].mean()
        daily_price = spy['Close'].iloc[loc]
    else:
        continue

    total_shares = POSITION_VALUE / arrival_price

    # For each vol method, compute optimal trajectory and simulate execution
    for label, sigma_est in [('GJR-GARCH', sg), ('RV20', sr), ('EWMA', se)]:
        # Compute optimal trajectory for this many bars
        traj, trades, exp_cost, exp_risk, kappa = almgren_chriss_trajectory(
            sigma_est, n_bars, total_shares, avg_daily_vol
        )

        # Simulate with actual prices (no additional market impact for clarity)
        # IS = (arrival_price * X - sum(trade_k * actual_price_k)) / (arrival_price * X)
        is_value = compute_implementation_shortfall(trades, prices, arrival_price)

        # Also compute with simulated market impact
        sigma_per_bar = sigma_est / np.sqrt(252 * n_bars)
        avg_vol_per_bar = avg_daily_vol / n_bars
        exec_prices = simulate_execution_with_impact(
            trades, prices, sigma_per_bar, avg_vol_per_bar
        )
        is_with_impact = compute_implementation_shortfall(trades, exec_prices, arrival_price)

        # TWAP benchmark
        twap_trades = np.full(n_bars, total_shares / n_bars)
        is_twap = compute_implementation_shortfall(twap_trades, prices, arrival_price)

        # Front-loading measure
        first_quarter = max(1, int(n_bars * 0.25))
        front_load_pct = np.sum(trades[:first_quarter]) / total_shares

        results_intraday.append({
            'date': date_ts,
            'method': label,
            'sigma_annual': sigma_est,
            'kappa': kappa,
            'n_bars': n_bars,
            'arrival_price': arrival_price,
            'vwap_price': np.mean(prices),
            'is_no_impact_bps': is_value * 10000,
            'is_with_impact_bps': is_with_impact * 10000,
            'is_twap_bps': is_twap * 10000,
            'ac_vs_twap_bps': (is_twap - is_value) * 10000,  # positive = AC better
            'front_load_pct': front_load_pct,
            'daily_return_pct': (prices[-1] / prices[0] - 1) * 100,
        })

df_intraday = pd.DataFrame(results_intraday)

if len(df_intraday) > 0:
    n_days_intra = df_intraday['date'].nunique()
    print(f"\nSuccessfully simulated {n_days_intra} days with 5-min data")

    print("\n--- PRELIMINARY 5-min Execution Results ---")
    for method in ['GJR-GARCH', 'RV20', 'EWMA']:
        sub = df_intraday[df_intraday['method'] == method]
        print(f"\n{method} ({len(sub)} day-simulations):")
        print(f"  Mean IS (no impact):  {sub['is_no_impact_bps'].mean():.2f} bps")
        print(f"  Mean IS (w/ impact):  {sub['is_with_impact_bps'].mean():.2f} bps")
        print(f"  Mean AC vs TWAP:      {sub['ac_vs_twap_bps'].mean():.2f} bps (positive = AC better)")
        print(f"  Std IS:               {sub['is_no_impact_bps'].std():.2f} bps")
        print(f"  Mean front-load:      {sub['front_load_pct'].mean():.3f}")

    # Paired comparison: GARCH vs RV20 on same days
    pivot_is = df_intraday.pivot(index='date', columns='method', values='is_no_impact_bps')
    if 'GJR-GARCH' in pivot_is.columns and 'RV20' in pivot_is.columns:
        is_diff = pivot_is['RV20'] - pivot_is['GJR-GARCH']  # positive = GARCH better
        is_diff = is_diff.dropna()
        if len(is_diff) > 2:
            t_is, p_is = stats.ttest_1samp(is_diff, 0)
            print(f"\n--- Paired IS Comparison (5-min, PRELIMINARY) ---")
            print(f"  IS(RV20) - IS(GARCH): mean = {is_diff.mean():.2f} bps")
            print(f"  t-stat: {t_is:.3f}, p-value: {p_is:.4f}")
            print(f"  GARCH better on {(is_diff > 0).sum()}/{len(is_diff)} days ({(is_diff > 0).mean()*100:.0f}%)")

    # AC vs TWAP comparison
    pivot_ac = df_intraday.pivot(index='date', columns='method', values='ac_vs_twap_bps')
    print(f"\n--- AC vs TWAP (any vol method helps?) ---")
    for method in ['GJR-GARCH', 'RV20', 'EWMA']:
        if method in pivot_ac.columns:
            ac_adv = pivot_ac[method].dropna()
            t_ac, p_ac = stats.ttest_1samp(ac_adv, 0) if len(ac_adv) > 2 else (0, 1)
            print(f"  {method} AC vs TWAP: mean = {ac_adv.mean():.2f} bps, "
                  f"t={t_ac:.2f}, p={p_ac:.3f}, win rate={( ac_adv > 0).sum()}/{len(ac_adv)}")

    # Conditional on down days (where front-loading matters most)
    down_days = df_intraday[df_intraday['daily_return_pct'] < 0]['date'].unique()
    up_days = df_intraday[df_intraday['daily_return_pct'] >= 0]['date'].unique()

    print(f"\n--- Conditional Analysis ---")
    print(f"Down days: {len(down_days)}, Up days: {len(up_days)}")

    if len(down_days) > 5:
        for regime, days in [('Down Days', down_days), ('Up Days', up_days)]:
            sub_garch = df_intraday[(df_intraday['method'] == 'GJR-GARCH') & (df_intraday['date'].isin(days))]
            sub_rv = df_intraday[(df_intraday['method'] == 'RV20') & (df_intraday['date'].isin(days))]
            if len(sub_garch) > 0 and len(sub_rv) > 0:
                garch_is = sub_garch.set_index('date')['is_no_impact_bps']
                rv_is = sub_rv.set_index('date')['is_no_impact_bps']
                common = garch_is.index.intersection(rv_is.index)
                diff = rv_is.loc[common] - garch_is.loc[common]
                if len(diff) > 2:
                    t_d, p_d = stats.ttest_1samp(diff, 0)
                    print(f"\n  {regime} ({len(diff)} days):")
                    print(f"    IS(RV20) - IS(GARCH) = {diff.mean():.2f} bps (t={t_d:.2f}, p={p_d:.3f})")
else:
    print("\nNo 5-min intraday simulations completed (no matching dates).")

# ==================================================================
# 7. SUMMARY & ECONOMIC SIGNIFICANCE
# ==================================================================
print("\n" + "=" * 80)
print("[7/7] SUMMARY & ECONOMIC SIGNIFICANCE")
print("=" * 80)

# Summarize daily proxy results
print("\n--- PART A: Daily Analysis (Expected Cost Proximity to Oracle) ---")
garch_advantage_rv = (cost_dist_rv - cost_dist_garch).mean()
garch_advantage_ewma = (cost_dist_ewma - cost_dist_garch).mean()
print(f"  GARCH advantage over RV20:  {garch_advantage_rv:.4f} bps/trade")
print(f"  GARCH advantage over EWMA:  {garch_advantage_ewma:.4f} bps/trade")

# Annualize the advantage
trades_per_year = 252  # assume daily large block trades
annual_advantage_rv = garch_advantage_rv * trades_per_year
annual_advantage_ewma = garch_advantage_ewma * trades_per_year
print(f"\n  Annualized (assuming {trades_per_year} block trades/year):")
print(f"    vs RV20:  {annual_advantage_rv:.2f} bps/year = ${POSITION_VALUE * annual_advantage_rv / 10000 / 1e6:.3f}M")
print(f"    vs EWMA:  {annual_advantage_ewma:.2f} bps/year = ${POSITION_VALUE * annual_advantage_ewma / 10000 / 1e6:.3f}M")

# Vol forecast error analysis
print(f"\n--- Vol Forecast Quality Summary ---")
for method in ['GJR-GARCH', 'RV20', 'EWMA']:
    mae = np.abs(pivot_vol[method] - pivot_vol['Oracle']).mean()
    corr = pivot_vol[method].corr(pivot_vol['Oracle'])
    print(f"  {method}: MAE={mae:.4f}, Corr={corr:.4f}")

# Key insight
print(f"\n--- KEY INSIGHT ---")
pivot_front = df_daily.pivot(index='date', columns='method', values='front_load_pct')
for method in ['GJR-GARCH', 'RV20', 'EWMA']:
    fl = pivot_front[method]
    print(f"  {method} front-load: {fl.mean():.3f} +/- {fl.std():.3f}")

# Vol responsiveness: how much does kappa change with vol?
pivot_kappa_all = df_daily.pivot(index='date', columns='method', values='kappa')
for method in ['GJR-GARCH', 'RV20', 'EWMA']:
    kappa_std = pivot_kappa_all[method].std()
    kappa_range = pivot_kappa_all[method].max() - pivot_kappa_all[method].min()
    print(f"  {method} kappa: std={kappa_std:.6f}, range={kappa_range:.6f}")

# Directional accuracy: does GARCH correctly predict high/low vol direction?
print(f"\n--- Directional Accuracy (high/low vol prediction) ---")
oracle_high = pivot_vol['Oracle'] > pivot_vol['Oracle'].median()
for method in ['GJR-GARCH', 'RV20', 'EWMA']:
    pred_high = pivot_vol[method] > pivot_vol[method].median()
    accuracy = (pred_high == oracle_high).mean()
    print(f"  {method}: {accuracy:.3f} directional accuracy")

# ==================================================================
# SAVE RESULTS
# ==================================================================
print("\n" + "=" * 80)
print("Saving results...")
print("=" * 80)

results_summary = {
    "experiment": "K147",
    "title": "Execution Alpha: GJR-GARCH for Almgren-Chriss Optimal Liquidation",
    "proposed_by": "Gemini R4#4",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "position_value": POSITION_VALUE,
        "n_intraday_periods": N_INTRADAY_PERIODS,
        "risk_aversion": RISK_AVERSION,
        "temp_impact_scale": TEMP_IMPACT_SCALE,
        "garch_window": GARCH_WINDOW,
        "rv_window": RV_WINDOW,
        "ewma_lambda": EWMA_LAMBDA,
        "oos_start": OOS_START,
        "oos_end": OOS_END,
    },
    "part_a_daily_proxy": {
        "n_days": len(common_dates),
        "garch_advantage_vs_rv20_bps": float(garch_advantage_rv),
        "garch_advantage_vs_ewma_bps": float(garch_advantage_ewma),
        "garch_t_stat_vs_rv20": float(t_stat),
        "garch_p_value_vs_rv20": float(p_val),
        "garch_t_stat_vs_ewma": float(t_stat2),
        "garch_p_value_vs_ewma": float(p_val2),
        "vol_mae": {
            "garch": float(np.abs(pivot_vol['GJR-GARCH'] - pivot_vol['Oracle']).mean()),
            "rv20": float(np.abs(pivot_vol['RV20'] - pivot_vol['Oracle']).mean()),
            "ewma": float(np.abs(pivot_vol['EWMA'] - pivot_vol['Oracle']).mean()),
        },
        "vol_corr_with_oracle": {
            "garch": float(pivot_vol['GJR-GARCH'].corr(pivot_vol['Oracle'])),
            "rv20": float(pivot_vol['RV20'].corr(pivot_vol['Oracle'])),
            "ewma": float(pivot_vol['EWMA'].corr(pivot_vol['Oracle'])),
        },
        "directional_accuracy": {
            "garch": float((( pivot_vol['GJR-GARCH'] > pivot_vol['GJR-GARCH'].median()) == oracle_high).mean()),
            "rv20": float(((pivot_vol['RV20'] > pivot_vol['RV20'].median()) == oracle_high).mean()),
            "ewma": float(((pivot_vol['EWMA'] > pivot_vol['EWMA'].median()) == oracle_high).mean()),
        },
    },
    "part_b_intraday": {},
}

if len(df_intraday) > 0:
    n_days_sim = df_intraday['date'].nunique()

    intraday_summary = {
        "n_days": int(n_days_sim),
        "preliminary": True,
    }

    for method in ['GJR-GARCH', 'RV20', 'EWMA']:
        sub = df_intraday[df_intraday['method'] == method]
        intraday_summary[method.lower().replace('-', '_')] = {
            "mean_is_bps": float(sub['is_no_impact_bps'].mean()),
            "std_is_bps": float(sub['is_no_impact_bps'].std()),
            "mean_ac_vs_twap_bps": float(sub['ac_vs_twap_bps'].mean()),
        }

    if 'GJR-GARCH' in pivot_is.columns and 'RV20' in pivot_is.columns:
        is_diff_clean = (pivot_is['RV20'] - pivot_is['GJR-GARCH']).dropna()
        if len(is_diff_clean) > 2:
            t_final, p_final = stats.ttest_1samp(is_diff_clean, 0)
            intraday_summary["garch_vs_rv20_is_diff_bps"] = float(is_diff_clean.mean())
            intraday_summary["garch_vs_rv20_t_stat"] = float(t_final)
            intraday_summary["garch_vs_rv20_p_value"] = float(p_final)
            intraday_summary["garch_win_rate"] = float((is_diff_clean > 0).mean())

    results_summary["part_b_intraday"] = intraday_summary

# Save JSON
output_path = os.path.join(os.path.dirname(__file__), "k147_execution_alpha_results.json")
with open(output_path, 'w') as f:
    json.dump(results_summary, f, indent=2, default=str)
print(f"Results saved to: {output_path}")

# ==================================================================
# RECORD TO MEMORY SYSTEM
# ==================================================================
print("\n" + "=" * 80)
print("Recording to memory system...")
print("=" * 80)

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
    from volpred.memory.system import MemorySystem
    m = MemorySystem()

    # Construct summary
    adv_str = f"{garch_advantage_rv:.4f}" if garch_advantage_rv > 0 else f"{garch_advantage_rv:.4f}"
    sig_str = "significant" if p_val < 0.05 else "not significant"

    intra_str = ""
    if len(df_intraday) > 0 and 'garch_vs_rv20_is_diff_bps' in results_summary.get('part_b_intraday', {}):
        intra_bps = results_summary['part_b_intraday']['garch_vs_rv20_is_diff_bps']
        intra_p = results_summary['part_b_intraday'].get('garch_vs_rv20_p_value', 1)
        intra_str = f" Intraday 5-min sim (PRELIMINARY, {n_days_sim}d): GARCH vs RV20 IS diff = {intra_bps:.2f} bps (p={intra_p:.3f})."

    knowledge_content = (
        f"[提出: Gemini R4#4, 執行: Claude] K147: Execution Alpha - "
        f"GJR-GARCH for Almgren-Chriss optimal liquidation of $100M position. "
        f"Part A (daily proxy, {len(common_dates)}d): GARCH expected cost advantage over RV20 = "
        f"{adv_str} bps/trade ({sig_str}, t={t_stat:.2f}, p={p_val:.3f}). "
        f"Over EWMA = {garch_advantage_ewma:.4f} bps. "
        f"Vol MAE: GARCH={np.abs(pivot_vol['GJR-GARCH'] - pivot_vol['Oracle']).mean():.4f}, "
        f"RV20={np.abs(pivot_vol['RV20'] - pivot_vol['Oracle']).mean():.4f}, "
        f"EWMA={np.abs(pivot_vol['EWMA'] - pivot_vol['Oracle']).mean():.4f}."
        f"{intra_str} "
        f"This is a NEW application domain: vol for execution, not for VT."
    )

    confidence = 0.6 if p_val < 0.05 else 0.4
    m.add_knowledge(
        category="experiment",
        content=knowledge_content,
        confidence=confidence,
    )

    m.add_log_entry(
        phase="Phase_K",
        action="K147_execution_alpha",
        observation=f"GJR-GARCH expected cost advantage vs RV20: {adv_str} bps/trade (p={p_val:.3f}). "
                    f"New domain: vol for execution (Almgren-Chriss).",
        decision="Record results. This opens a new research direction: vol forecasting for trade execution "
                 "rather than VT strategies. Even small bps advantages scale with institutional volumes.",
    )

    print("Memory system updated successfully.")
except Exception as e:
    print(f"Warning: Could not update memory system: {e}")

print("\n" + "=" * 80)
print("K147 EXPERIMENT COMPLETE")
print("=" * 80)
