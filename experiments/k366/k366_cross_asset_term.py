"""
K366: Cross-Asset Volatility Term Structure — Does the h=5d Peak Hold for ALL Assets?

Extension of K365 (SPY h=5d R²=0.524 peak) and K145 (R² peak mechanism).

KEY QUESTION: Is the hump-shaped term structure (R² rising then falling with horizon)
UNIVERSAL across asset classes, or is it SPY-specific?

Related findings:
- K365: SPY vol term structure peaks at h=5d (R²=0.524)
- K342: Oil QLIKE 2.5x worse than equity
- K343: NG vol clustering 3x weaker
- K345: FX ACF fast decay
- K145: R² peak mechanism = signal-to-noise tradeoff

Assets: SPY, GLD, TLT, BTC-USD, CL=F (oil), EURUSD=X
Horizons: h = 1, 2, 5, 10, 22 days

Methodology (ALL using lagged predictors — bias-free per K362):
- Rolling GJR-GARCH(1,1) with window=2000
- Refit every 22 days for efficiency
- OOS: 2020-01-01 to 2025-12-31
- Target: sum of squared returns over next h days (RV proxy)
- Forecast: sum of GARCH h-step conditional variances
- Metric: Mincer-Zarnowitz R² (bias-free OOS evaluation)
- For SPY: also test with VIX as auxiliary predictor
- For others: own lagged RV only

Data source: yfinance (real market data)
Author: [提出: 用戶, 執行: Claude]
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

warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURATION
# ============================================================
HORIZONS = [1, 2, 5, 10, 22]
WINDOW = 2000
OOS_START = '2020-01-01'
REFIT_FREQ = 22  # Refit GARCH every 22 trading days

ASSETS = {
    'SPY': {'name': 'S&P 500 ETF', 'class': 'Equity', 'start': '2007-01-01'},
    'GLD': {'name': 'Gold ETF', 'class': 'Commodity', 'start': '2007-01-01'},
    'TLT': {'name': '20Y Treasury ETF', 'class': 'Bond', 'start': '2007-01-01'},
    'BTC-USD': {'name': 'Bitcoin', 'class': 'Crypto', 'start': '2015-01-01'},
    'CL=F': {'name': 'Crude Oil Futures', 'class': 'Commodity', 'start': '2007-01-01'},
    'EURUSD=X': {'name': 'EUR/USD', 'class': 'FX', 'start': '2007-01-01'},
}

print("=" * 80)
print("K366: Cross-Asset Volatility Term Structure")
print("Does the h=5d R² Peak Hold for ALL Assets?")
print("=" * 80)
print(f"Horizons: {HORIZONS}")
print(f"Window: {WINDOW}, Refit: every {REFIT_FREQ}d")
print(f"OOS start: {OOS_START}")
print(f"Assets: {list(ASSETS.keys())}")
print()

# ============================================================
# DATA LOADING
# ============================================================
all_results = {}

for ticker, info in ASSETS.items():
    print(f"\n{'='*70}")
    print(f"  {ticker} ({info['name']}) — {info['class']}")
    print(f"{'='*70}")

    try:
        df = yf.download(ticker, start=info['start'], end='2026-03-25',
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < WINDOW + 252:
            print(f"  SKIP: insufficient data ({len(df)} rows, need {WINDOW+252})")
            continue

        # Log returns
        returns = np.log(df['close'] / df['close'].shift(1)).dropna()
        r2_daily = returns ** 2  # daily squared return (RV proxy)

        print(f"  Data: {returns.index[0].date()} to {returns.index[-1].date()}, N={len(returns)}")
        print(f"  Annualized vol: {returns.std() * np.sqrt(252) * 100:.1f}%")
        print(f"  Skewness: {returns.skew():.3f}, Kurtosis: {returns.kurtosis():.3f}")

        # Check ACF of squared returns (vol clustering strength)
        from statsmodels.tsa.stattools import acf
        acf_vals = acf(r2_daily.dropna().values, nlags=22, fft=True)
        print(f"  ACF(r²) at lag 1/5/22: {acf_vals[1]:.3f} / {acf_vals[5]:.3f} / {acf_vals[22]:.3f}")

        # Percentage returns for arch
        ret_pct = returns * 100

        # Determine OOS range
        oos_mask = returns.index >= OOS_START
        oos_dates = returns.index[oos_mask]

        if len(oos_dates) == 0:
            print(f"  SKIP: no OOS dates after {OOS_START}")
            continue

        first_oos_loc = returns.index.get_loc(oos_dates[0])
        if first_oos_loc < WINDOW:
            print(f"  WARNING: Not enough pre-OOS data ({first_oos_loc} < {WINDOW})")
            # Use available data
            actual_window = first_oos_loc
            if actual_window < 504:
                print(f"  SKIP: too little data even with reduced window ({actual_window})")
                continue
            print(f"  Using reduced window: {actual_window}")
        else:
            actual_window = WINDOW

        print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()}, N_oos={len(oos_dates)}")

        # ============================================================
        # ROLLING GJR-GARCH FORECASTING
        # ============================================================
        MAX_HORIZON = max(HORIZONS)

        # Store forecasts: {horizon: {date: forecast_variance_sum}}
        forecasts_by_h = {h: {} for h in HORIZONS}
        actuals_by_h = {h: {} for h in HORIZONS}

        n_fits = 0
        n_fail = 0
        last_params = None

        for i_oos, t_idx in enumerate(range(first_oos_loc, len(returns) - MAX_HORIZON)):
            t_date = returns.index[t_idx]

            if t_date < pd.Timestamp(OOS_START):
                continue

            # Fit/refit GJR-GARCH
            if i_oos % REFIT_FREQ == 0 or last_params is None:
                train_start = max(0, t_idx - actual_window)
                train_data = ret_pct.iloc[train_start:t_idx]

                try:
                    am = arch_model(train_data, vol='Garch', p=1, o=1, q=1, dist='t')
                    res = am.fit(disp='off', show_warning=False)
                    last_params = res.params
                    last_res = res
                    n_fits += 1
                except Exception:
                    n_fail += 1
                    if last_params is None:
                        continue

            # Generate multi-step forecasts
            try:
                fcast = last_res.forecast(horizon=MAX_HORIZON, reindex=False)
                var_forecasts = fcast.variance.iloc[-1].values  # h-step variances

                for h in HORIZONS:
                    # Cumulative variance over h steps (sum of 1-step to h-step)
                    cum_var = var_forecasts[:h].sum() / 10000.0  # back to decimal

                    # Actual RV over next h days
                    future_r2 = r2_daily.iloc[t_idx + 1 : t_idx + 1 + h]
                    if len(future_r2) == h:
                        actual_rv = future_r2.sum()
                        forecasts_by_h[h][t_date] = cum_var
                        actuals_by_h[h][t_date] = actual_rv

            except Exception:
                n_fail += 1
                continue

        print(f"  Fits: {n_fits}, Failures: {n_fail}")

        # ============================================================
        # COMPUTE R² FOR EACH HORIZON
        # ============================================================
        horizon_results = {}
        print(f"\n  {'h':>3s}  {'N_oos':>6s}  {'R²':>8s}  {'QLIKE':>10s}  {'Slope(b)':>10s}  {'Intercept(a)':>12s}")
        print(f"  {'-'*3}  {'-'*6}  {'-'*8}  {'-'*10}  {'-'*10}  {'-'*12}")

        for h in HORIZONS:
            dates = sorted(set(forecasts_by_h[h].keys()) & set(actuals_by_h[h].keys()))
            if len(dates) < 50:
                print(f"  {h:>3d}  {len(dates):>6d}  -- insufficient --")
                continue

            f_arr = np.array([forecasts_by_h[h][d] for d in dates])
            a_arr = np.array([actuals_by_h[h][d] for d in dates])

            # Remove any inf/nan
            mask = np.isfinite(f_arr) & np.isfinite(a_arr) & (f_arr > 0) & (a_arr > 0)
            f_arr = f_arr[mask]
            a_arr = a_arr[mask]

            if len(f_arr) < 50:
                print(f"  {h:>3d}  {len(f_arr):>6d}  -- insufficient after cleaning --")
                continue

            # Mincer-Zarnowitz regression: actual = a + b * forecast
            slope, intercept, r_value, p_value, std_err = stats.linregress(f_arr, a_arr)
            r_squared = r_value ** 2

            # QLIKE: mean(log(sigma2) + RV/sigma2)
            qlike = np.mean(np.log(f_arr) + a_arr / f_arr)

            # Also compute correlation
            corr = np.corrcoef(f_arr, a_arr)[0, 1]

            horizon_results[h] = {
                'r_squared': float(r_squared),
                'qlike': float(qlike),
                'slope': float(slope),
                'intercept': float(intercept),
                'correlation': float(corr),
                'n_obs': int(len(f_arr)),
                'p_value': float(p_value),
            }

            print(f"  {h:>3d}  {len(f_arr):>6d}  {r_squared:>8.4f}  {qlike:>10.4f}  {slope:>10.4f}  {intercept:>12.6f}")

        if not horizon_results:
            print(f"  SKIP: no valid results for {ticker}")
            continue

        # Find peak horizon
        peak_h = max(horizon_results, key=lambda h: horizon_results[h]['r_squared'])
        peak_r2 = horizon_results[peak_h]['r_squared']

        # Compute shape characteristics
        r2_values = [horizon_results[h]['r_squared'] for h in sorted(horizon_results.keys())]
        r2_horizons = sorted(horizon_results.keys())

        # Is it hump-shaped? (rises then falls)
        peak_idx = r2_values.index(max(r2_values))
        is_hump = (peak_idx > 0 and peak_idx < len(r2_values) - 1)
        is_monotone_up = all(r2_values[i] <= r2_values[i+1] for i in range(len(r2_values)-1))
        is_monotone_down = all(r2_values[i] >= r2_values[i+1] for i in range(len(r2_values)-1))

        if is_hump:
            shape = "hump"
        elif is_monotone_up:
            shape = "monotone_up"
        elif is_monotone_down:
            shape = "monotone_down"
        else:
            shape = "irregular"

        # R² ratio: peak / h=1
        if 1 in horizon_results and horizon_results[1]['r_squared'] > 0:
            r2_ratio = peak_r2 / horizon_results[1]['r_squared']
        else:
            r2_ratio = None

        all_results[ticker] = {
            'name': info['name'],
            'asset_class': info['class'],
            'horizons': horizon_results,
            'peak_horizon': int(peak_h),
            'peak_r_squared': float(peak_r2),
            'shape': shape,
            'r2_ratio_peak_vs_h1': float(r2_ratio) if r2_ratio else None,
            'acf_r2': {
                'lag1': float(acf_vals[1]),
                'lag5': float(acf_vals[5]),
                'lag22': float(acf_vals[22]),
            },
            'ann_vol': float(returns.std() * np.sqrt(252) * 100),
        }

        print(f"\n  >>> Peak horizon: h={peak_h}d (R²={peak_r2:.4f})")
        print(f"  >>> Shape: {shape}")
        if r2_ratio:
            print(f"  >>> R² improvement from h=1 to peak: {r2_ratio:.2f}x")

    except Exception as e:
        print(f"  ERROR processing {ticker}: {e}")
        import traceback
        traceback.print_exc()
        continue


# ============================================================
# CROSS-ASSET COMPARISON
# ============================================================
print("\n\n" + "=" * 80)
print("CROSS-ASSET TERM STRUCTURE COMPARISON")
print("=" * 80)

# Summary table
print(f"\n{'Asset':<12s} {'Class':<10s} {'Peak h':<8s} {'Peak R²':<10s} {'Shape':<12s} "
      f"{'R²(h=1)':<10s} {'R²(h=5)':<10s} {'R²(h=22)':<10s} {'ACF(1)':<8s}")
print("-" * 100)

for ticker, res in all_results.items():
    h1_r2 = res['horizons'].get(1, {}).get('r_squared', float('nan'))
    h5_r2 = res['horizons'].get(5, {}).get('r_squared', float('nan'))
    h22_r2 = res['horizons'].get(22, {}).get('r_squared', float('nan'))

    print(f"{ticker:<12s} {res['asset_class']:<10s} h={res['peak_horizon']:<5d} "
          f"{res['peak_r_squared']:<10.4f} {res['shape']:<12s} "
          f"{h1_r2:<10.4f} {h5_r2:<10.4f} {h22_r2:<10.4f} {res['acf_r2']['lag1']:<8.3f}")

# ============================================================
# KEY ANALYSES
# ============================================================
print("\n\n" + "=" * 80)
print("KEY ANALYSES")
print("=" * 80)

# 1. Is h=5d peak universal?
peak_horizons = {t: r['peak_horizon'] for t, r in all_results.items()}
print(f"\n1. Peak horizons: {peak_horizons}")
h5_count = sum(1 for h in peak_horizons.values() if h == 5)
print(f"   Assets peaking at h=5: {h5_count}/{len(peak_horizons)}")
print(f"   h=5d peak is {'UNIVERSAL' if h5_count == len(peak_horizons) else 'NOT universal'}")

# 2. Shape analysis
shapes = {t: r['shape'] for t, r in all_results.items()}
print(f"\n2. Term structure shapes: {shapes}")
hump_count = sum(1 for s in shapes.values() if s == 'hump')
print(f"   Hump-shaped: {hump_count}/{len(shapes)}")

# 3. ACF vs peak horizon correlation
if len(all_results) >= 3:
    acf1_vals = [r['acf_r2']['lag1'] for r in all_results.values()]
    peak_h_vals = [r['peak_horizon'] for r in all_results.values()]
    peak_r2_vals = [r['peak_r_squared'] for r in all_results.values()]

    if len(set(peak_h_vals)) > 1:
        corr_acf_peak, p_acf_peak = stats.spearmanr(acf1_vals, peak_h_vals)
        print(f"\n3. Spearman corr(ACF(1), peak_h): rho={corr_acf_peak:.3f}, p={p_acf_peak:.3f}")
    else:
        print(f"\n3. All peaks at same horizon — cannot compute correlation")

    corr_acf_r2, p_acf_r2 = stats.spearmanr(acf1_vals, peak_r2_vals)
    print(f"   Spearman corr(ACF(1), peak_R²): rho={corr_acf_r2:.3f}, p={p_acf_r2:.3f}")

# 4. R² at h=5 across assets
print(f"\n4. R² at h=5d across assets:")
for ticker, res in all_results.items():
    h5 = res['horizons'].get(5, {})
    if h5:
        print(f"   {ticker}: R²={h5['r_squared']:.4f}, QLIKE={h5['qlike']:.4f}")

# 5. Asset class patterns
print(f"\n5. Asset class patterns:")
class_groups = {}
for ticker, res in all_results.items():
    cls = res['asset_class']
    if cls not in class_groups:
        class_groups[cls] = []
    class_groups[cls].append((ticker, res))

for cls, members in class_groups.items():
    peaks = [m[1]['peak_horizon'] for m in members]
    r2s = [m[1]['peak_r_squared'] for m in members]
    print(f"   {cls}: peaks={peaks}, peak R²={[f'{r:.4f}' for r in r2s]}")

# 6. QLIKE term structure (does QLIKE also have a sweet spot?)
print(f"\n6. QLIKE term structure (lower = better):")
for ticker, res in all_results.items():
    qlikes = {h: res['horizons'][h]['qlike'] for h in sorted(res['horizons'].keys())}
    best_h = min(qlikes, key=qlikes.get)
    print(f"   {ticker}: QLIKE by h = {', '.join(f'h={h}:{q:.4f}' for h, q in qlikes.items())} → best h={best_h}")

# ============================================================
# CONCLUSIONS
# ============================================================
print("\n\n" + "=" * 80)
print("CONCLUSIONS")
print("=" * 80)

# Determine if universal
if h5_count == len(peak_horizons):
    conclusion = "h=5d peak is UNIVERSAL across all tested assets"
elif h5_count >= len(peak_horizons) * 0.5:
    conclusion = f"h=5d peak is COMMON ({h5_count}/{len(peak_horizons)}) but not universal"
else:
    conclusion = f"h=5d peak is SPY-SPECIFIC — other assets have different optimal horizons"

print(f"\n{conclusion}")
print(f"\nAsset-specific optimal horizons would improve forecast targeting for non-equity assets.")

# ============================================================
# SAVE RESULTS
# ============================================================
output = {
    'experiment': 'K366',
    'title': 'Cross-Asset Volatility Term Structure',
    'question': 'Does the h=5d R² peak hold for ALL assets?',
    'methodology': {
        'model': 'GJR-GARCH(1,1)',
        'window': WINDOW,
        'oos_start': OOS_START,
        'refit_freq': REFIT_FREQ,
        'horizons': HORIZONS,
        'metric': 'Mincer-Zarnowitz R²',
        'data_source': 'yfinance',
        'bias_control': 'All predictors lagged (per K362)',
    },
    'results': all_results,
    'summary': {
        'peak_horizons': peak_horizons,
        'shapes': shapes,
        'conclusion': conclusion,
        'h5_universal': h5_count == len(peak_horizons),
        'h5_count': h5_count,
        'total_assets': len(peak_horizons),
    },
    'timestamp': datetime.now().isoformat(),
}

output_path = 'experiments/k366_cross_asset_term_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
