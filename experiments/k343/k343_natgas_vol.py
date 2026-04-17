#!/usr/bin/env python3
"""
K343: Natural Gas Volatility — The Most Volatile Major Commodity
================================================================
新研究路線：天然氣波動率動態

Background: K342 showed oil vol is 4x SPY and GJR is useless for oil.
Natural gas (NG=F) is even MORE volatile than oil — driven by weather,
storage reports, and extreme supply/demand seasonality. Does it have
different vol dynamics?

Data: yfinance
  - NG=F (Natural Gas futures, 25 years)
  - CL=F (Crude Oil for comparison)
  - SPY, ^VIX

Methodology:
  1. NG vol characteristics vs Oil vs SPY (ann vol, kurtosis, skew, ACF r²)
  2. GJR gamma (leverage effect?) — does NG have asymmetry?
  3. Seasonality: does NG vol spike in winter? (heating demand)
  4. EIA storage report day (Thursday) vol premium
  5. NG-Oil vol correlation
  6. GARCH QLIKE comparison across assets
  7. Can NG vol predict equity vol? (supply shock → economic risk)

[提出: 用戶, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model
import json
import warnings
warnings.filterwarnings('ignore')

RESULTS = {}

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K343: Natural Gas Volatility — The Most Volatile Major Commodity")
print("=" * 70)

tickers = {
    'NG=F': 'Natural Gas Futures',
    'CL=F': 'WTI Crude Oil Futures',
    'SPY': 'S&P 500 ETF',
    '^VIX': 'VIX (Equity Fear Gauge)',
}

print("\n[1] Downloading data 2001-2026...")
data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2001-01-01', end='2026-12-31',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            close = df['Close']
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            data[ticker] = close
            print(f"  {ticker}: {len(df)} days ({desc}), "
                  f"{close.index[0].date()} to {close.index[-1].date()}")
        else:
            print(f"  {ticker}: NO DATA")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

# Compute returns
returns = {}
for ticker in data:
    if ticker == '^VIX':
        continue
    r = np.log(data[ticker] / data[ticker].shift(1)).dropna()
    returns[ticker] = r

print(f"\n  Returns computed:")
for t, r in returns.items():
    print(f"    {t}: {len(r)} obs, {r.index[0].date()} to {r.index[-1].date()}")

# ============================================================
# 2. Volatility Characteristics: NG vs Oil vs SPY
# ============================================================
print("\n" + "=" * 70)
print("[2] Volatility Characteristics Comparison")
print("=" * 70)

asset_names = {'NG=F': 'Natural Gas', 'CL=F': 'Oil (WTI)', 'SPY': 'SPY'}
vol_chars = {}

for ticker in ['NG=F', 'CL=F', 'SPY']:
    if ticker not in returns:
        continue
    r = returns[ticker]
    r_clean = r.replace([np.inf, -np.inf], np.nan).dropna()

    ann_vol = r_clean.std() * np.sqrt(252) * 100
    daily_mean = r_clean.mean() * 252 * 100  # annualized
    skew = stats.skew(r_clean)
    kurt = stats.kurtosis(r_clean)  # excess kurtosis

    # Max daily moves
    max_up = r_clean.max() * 100
    max_down = r_clean.min() * 100

    # Days with |r| > 5%
    extreme_days = (np.abs(r_clean) > 0.05).sum()
    extreme_pct = extreme_days / len(r_clean) * 100

    # Days with |r| > 10%
    very_extreme = (np.abs(r_clean) > 0.10).sum()

    vol_chars[ticker] = {
        'name': asset_names[ticker],
        'obs': len(r_clean),
        'ann_vol_pct': round(float(ann_vol), 1),
        'ann_return_pct': round(float(daily_mean), 2),
        'skewness': round(float(skew), 3),
        'kurtosis': round(float(kurt), 1),
        'max_up_pct': round(float(max_up), 2),
        'max_down_pct': round(float(max_down), 2),
        'extreme_5pct_days': int(extreme_days),
        'extreme_5pct_ratio': round(float(extreme_pct), 3),
        'extreme_10pct_days': int(very_extreme),
    }

    print(f"\n  {asset_names[ticker]} ({ticker}):")
    print(f"    Annualized Vol:     {ann_vol:.1f}%")
    print(f"    Annualized Return:  {daily_mean:.2f}%")
    print(f"    Skewness:           {skew:.3f}")
    print(f"    Excess Kurtosis:    {kurt:.1f}")
    print(f"    Max Daily Up:       +{max_up:.2f}%")
    print(f"    Max Daily Down:     {max_down:.2f}%")
    print(f"    Days |r|>5%:        {extreme_days} ({extreme_pct:.2f}%)")
    print(f"    Days |r|>10%:       {very_extreme}")

RESULTS['vol_characteristics'] = vol_chars

# Vol ratio comparison
if 'NG=F' in vol_chars and 'SPY' in vol_chars:
    ng_spy_ratio = vol_chars['NG=F']['ann_vol_pct'] / vol_chars['SPY']['ann_vol_pct']
    print(f"\n  NG/SPY vol ratio:  {ng_spy_ratio:.1f}x")
    RESULTS['ng_spy_vol_ratio'] = round(ng_spy_ratio, 2)

if 'NG=F' in vol_chars and 'CL=F' in vol_chars:
    ng_oil_ratio = vol_chars['NG=F']['ann_vol_pct'] / vol_chars['CL=F']['ann_vol_pct']
    print(f"  NG/Oil vol ratio:  {ng_oil_ratio:.1f}x")
    RESULTS['ng_oil_vol_ratio'] = round(ng_oil_ratio, 2)

# ============================================================
# 3. ACF of Squared Returns (Volatility Clustering)
# ============================================================
print("\n" + "=" * 70)
print("[3] ACF of Squared Returns (Volatility Clustering)")
print("=" * 70)

acf_results = {}
for ticker in ['NG=F', 'CL=F', 'SPY']:
    if ticker not in returns:
        continue
    r = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()
    r2 = r ** 2

    # Manual ACF computation for lags 1, 5, 10, 20
    acf_vals = {}
    for lag in [1, 5, 10, 20]:
        acf_val = r2.autocorr(lag=lag)
        acf_vals[f'lag_{lag}'] = round(float(acf_val), 4)

    acf_results[ticker] = acf_vals
    print(f"\n  {asset_names[ticker]}:")
    for lag_name, val in acf_vals.items():
        print(f"    ACF({lag_name.split('_')[1]}):  {val:.4f}")

RESULTS['acf_squared_returns'] = acf_results

# Compare clustering strength
if 'NG=F' in acf_results and 'SPY' in acf_results:
    ng_acf1 = acf_results['NG=F']['lag_1']
    spy_acf1 = acf_results['SPY']['lag_1']
    oil_acf1 = acf_results.get('CL=F', {}).get('lag_1', 0)
    print(f"\n  Clustering strength (ACF(1) of r²):")
    print(f"    SPY:  {spy_acf1:.4f}")
    print(f"    Oil:  {oil_acf1:.4f}")
    print(f"    NG:   {ng_acf1:.4f}")
    if ng_acf1 < spy_acf1:
        print(f"    → NG has WEAKER clustering than SPY (harder to predict)")
    else:
        print(f"    → NG has STRONGER clustering than SPY")

# ============================================================
# 4. GJR-GARCH: Leverage Effect
# ============================================================
print("\n" + "=" * 70)
print("[4] GJR-GARCH: Testing Leverage Effect")
print("=" * 70)

gjr_results = {}
for ticker in ['NG=F', 'CL=F', 'SPY']:
    if ticker not in returns:
        continue
    r = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()
    r_scaled = r * 100  # percent

    # Fit GJR-GARCH(1,1)
    try:
        model = arch_model(r_scaled, vol='GARCH', p=1, o=1, q=1,
                          mean='Constant', dist='t')
        res = model.fit(disp='off', show_warning=False)

        omega = res.params.get('omega', 0)
        alpha = res.params.get('alpha[1]', 0)
        gamma = res.params.get('gamma[1]', 0)
        beta = res.params.get('beta[1]', 0)

        # gamma > 0 means leverage effect (bad news → more vol)
        # gamma < 0 means "inverse leverage" (good news → more vol or no asymmetry)

        gjr_results[ticker] = {
            'name': asset_names[ticker],
            'omega': round(float(omega), 6),
            'alpha': round(float(alpha), 4),
            'gamma': round(float(gamma), 4),
            'beta': round(float(beta), 4),
            'persistence': round(float(alpha + beta + gamma/2), 4),
            'gamma_tstat': round(float(res.tvalues.get('gamma[1]', 0)), 2),
        }

        print(f"\n  {asset_names[ticker]}:")
        print(f"    omega:       {omega:.6f}")
        print(f"    alpha:       {alpha:.4f}")
        print(f"    gamma:       {gamma:.4f} (t={res.tvalues.get('gamma[1]', 0):.2f})")
        print(f"    beta:        {beta:.4f}")
        print(f"    persistence: {alpha + beta + gamma/2:.4f}")

        if gamma > 0.01 and res.tvalues.get('gamma[1]', 0) > 2:
            print(f"    → Significant LEVERAGE effect")
        elif gamma < -0.01 and res.tvalues.get('gamma[1]', 0) < -2:
            print(f"    → Significant INVERSE leverage (unusual)")
        else:
            print(f"    → No significant asymmetry")

    except Exception as e:
        print(f"  {asset_names[ticker]}: GJR fit failed - {e}")
        gjr_results[ticker] = {'name': asset_names[ticker], 'error': str(e)}

RESULTS['gjr_garch'] = gjr_results

# ============================================================
# 5. Seasonality Analysis — Winter vs Summer Vol
# ============================================================
print("\n" + "=" * 70)
print("[5] Seasonality: Winter vs Summer Volatility")
print("=" * 70)

if 'NG=F' in returns:
    r_ng = returns['NG=F'].replace([np.inf, -np.inf], np.nan).dropna()

    # Define seasons
    # Winter: Nov-Mar (heating season)
    # Summer: May-Sep (cooling season, but less extreme)
    # Transition: Apr, Oct

    months = r_ng.index.month
    winter_mask = months.isin([11, 12, 1, 2, 3])
    summer_mask = months.isin([5, 6, 7, 8, 9])

    r_winter = r_ng[winter_mask]
    r_summer = r_ng[summer_mask]

    vol_winter = r_winter.std() * np.sqrt(252) * 100
    vol_summer = r_summer.std() * np.sqrt(252) * 100

    # Monthly breakdown
    print("\n  Monthly Annualized Volatility (NG=F):")
    monthly_vol = {}
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    for m in range(1, 13):
        r_month = r_ng[months == m]
        mvol = r_month.std() * np.sqrt(252) * 100
        monthly_vol[month_names[m-1]] = round(float(mvol), 1)
        marker = " ← WINTER" if m in [11, 12, 1, 2, 3] else ""
        print(f"    {month_names[m-1]:>3}: {mvol:6.1f}%{marker}")

    winter_premium = (vol_winter / vol_summer - 1) * 100

    # Statistical test: is winter vol significantly higher?
    # Compare squared returns
    r2_winter = r_winter ** 2
    r2_summer = r_summer ** 2
    t_stat, p_val = stats.ttest_ind(r2_winter, r2_summer, equal_var=False)

    seasonality_result = {
        'vol_winter_pct': round(float(vol_winter), 1),
        'vol_summer_pct': round(float(vol_summer), 1),
        'winter_premium_pct': round(float(winter_premium), 1),
        'ttest_tstat': round(float(t_stat), 2),
        'ttest_pval': round(float(p_val), 6),
        'monthly_vol': monthly_vol,
        'n_winter': len(r_winter),
        'n_summer': len(r_summer),
    }

    print(f"\n  Winter (Nov-Mar) vol: {vol_winter:.1f}%  (n={len(r_winter)})")
    print(f"  Summer (May-Sep) vol: {vol_summer:.1f}%  (n={len(r_summer)})")
    print(f"  Winter premium:       {winter_premium:.1f}%")
    print(f"  t-test (r² diff):     t={t_stat:.2f}, p={p_val:.6f}")

    if p_val < 0.05:
        print(f"  → Winter vol is SIGNIFICANTLY higher (p<0.05)")
    else:
        print(f"  → No significant seasonal difference")

    RESULTS['seasonality'] = seasonality_result

    # Also do same for Oil
    if 'CL=F' in returns:
        r_oil = returns['CL=F'].replace([np.inf, -np.inf], np.nan).dropna()
        m_oil = r_oil.index.month
        vol_w_oil = r_oil[m_oil.isin([11,12,1,2,3])].std() * np.sqrt(252) * 100
        vol_s_oil = r_oil[m_oil.isin([5,6,7,8,9])].std() * np.sqrt(252) * 100
        oil_premium = (vol_w_oil / vol_s_oil - 1) * 100
        print(f"\n  Oil winter vol: {vol_w_oil:.1f}%  summer: {vol_s_oil:.1f}%  premium: {oil_premium:.1f}%")
        RESULTS['seasonality']['oil_winter_premium_pct'] = round(float(oil_premium), 1)

# ============================================================
# 6. EIA Storage Report Day (Thursday) Vol Premium
# ============================================================
print("\n" + "=" * 70)
print("[6] EIA Storage Report Day (Thursday) Vol Premium")
print("=" * 70)

if 'NG=F' in returns:
    r_ng = returns['NG=F'].replace([np.inf, -np.inf], np.nan).dropna()

    # Day of week: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    dow = r_ng.index.dayofweek

    print("\n  Daily Volatility by Day of Week (NG=F):")
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    dow_vol = {}
    dow_abs_r = {}
    for d in range(5):
        r_day = r_ng[dow == d]
        dvol = r_day.std() * np.sqrt(252) * 100
        mean_abs = np.abs(r_day).mean() * 100
        dow_vol[day_names[d]] = round(float(dvol), 1)
        dow_abs_r[day_names[d]] = round(float(mean_abs), 3)
        marker = " ← EIA REPORT" if d == 3 else ""
        print(f"    {day_names[d]}: vol={dvol:6.1f}%  mean|r|={mean_abs:.3f}%{marker}")

    # Thursday vs other days
    r_thu = r_ng[dow == 3]
    r_not_thu = r_ng[dow != 3]
    vol_thu = r_thu.std() * np.sqrt(252) * 100
    vol_nothu = r_not_thu.std() * np.sqrt(252) * 100
    thu_premium = (vol_thu / vol_nothu - 1) * 100

    # t-test on squared returns
    t_thu, p_thu = stats.ttest_ind(r_thu**2, r_not_thu**2, equal_var=False)

    eia_result = {
        'vol_thursday_pct': round(float(vol_thu), 1),
        'vol_other_days_pct': round(float(vol_nothu), 1),
        'thu_premium_pct': round(float(thu_premium), 1),
        'ttest_tstat': round(float(t_thu), 2),
        'ttest_pval': round(float(p_thu), 6),
        'dow_vol': dow_vol,
        'dow_mean_abs_r': dow_abs_r,
    }

    print(f"\n  Thursday vol:     {vol_thu:.1f}%  (n={len(r_thu)})")
    print(f"  Other days vol:   {vol_nothu:.1f}%  (n={len(r_not_thu)})")
    print(f"  Thursday premium: {thu_premium:.1f}%")
    print(f"  t-test:           t={t_thu:.2f}, p={p_thu:.6f}")

    if p_thu < 0.05:
        print(f"  → EIA report day has SIGNIFICANTLY higher vol")
    else:
        print(f"  → No significant Thursday premium")

    RESULTS['eia_thursday_effect'] = eia_result

# ============================================================
# 7. NG-Oil Volatility Correlation
# ============================================================
print("\n" + "=" * 70)
print("[7] NG-Oil Volatility Correlation")
print("=" * 70)

if 'NG=F' in returns and 'CL=F' in returns:
    r_ng = returns['NG=F'].replace([np.inf, -np.inf], np.nan)
    r_oil = returns['CL=F'].replace([np.inf, -np.inf], np.nan)

    # Align dates
    common = r_ng.index.intersection(r_oil.index)
    r_ng_c = r_ng.loc[common].dropna()
    r_oil_c = r_oil.loc[common].dropna()
    common2 = r_ng_c.index.intersection(r_oil_c.index)
    r_ng_c = r_ng_c.loc[common2]
    r_oil_c = r_oil_c.loc[common2]

    # Return correlation
    ret_corr = r_ng_c.corr(r_oil_c)

    # Realized vol correlation (21-day rolling)
    rv_ng = r_ng_c.rolling(21).std() * np.sqrt(252) * 100
    rv_oil = r_oil_c.rolling(21).std() * np.sqrt(252) * 100
    rv_both = pd.DataFrame({'ng': rv_ng, 'oil': rv_oil}).dropna()
    vol_corr = rv_both['ng'].corr(rv_both['oil'])

    # Squared return correlation (daily vol proxy)
    r2_corr = (r_ng_c**2).corr(r_oil_c**2)

    # Rolling correlation of realized vol (252-day window)
    rolling_vol_corr = rv_both['ng'].rolling(252).corr(rv_both['oil'])
    rolling_vol_corr = rolling_vol_corr.dropna()

    vol_corr_result = {
        'return_corr': round(float(ret_corr), 4),
        'rv21_corr': round(float(vol_corr), 4),
        'r2_corr': round(float(r2_corr), 4),
        'n_common_days': len(common2),
        'rolling_vol_corr_mean': round(float(rolling_vol_corr.mean()), 4),
        'rolling_vol_corr_std': round(float(rolling_vol_corr.std()), 4),
        'rolling_vol_corr_min': round(float(rolling_vol_corr.min()), 4),
        'rolling_vol_corr_max': round(float(rolling_vol_corr.max()), 4),
    }

    print(f"\n  NG vs Oil (n={len(common2)} common days):")
    print(f"    Return correlation:          {ret_corr:.4f}")
    print(f"    Realized vol (21d) corr:     {vol_corr:.4f}")
    print(f"    Squared return corr:         {r2_corr:.4f}")
    print(f"    Rolling vol corr (mean):     {rolling_vol_corr.mean():.4f}")
    print(f"    Rolling vol corr (range):    [{rolling_vol_corr.min():.4f}, {rolling_vol_corr.max():.4f}]")

    if abs(vol_corr) < 0.3:
        print(f"    → NG and Oil vol are WEAKLY correlated — different dynamics")
    elif abs(vol_corr) < 0.6:
        print(f"    → NG and Oil vol are MODERATELY correlated")
    else:
        print(f"    → NG and Oil vol are STRONGLY correlated")

    RESULTS['ng_oil_vol_correlation'] = vol_corr_result

# ============================================================
# 8. GARCH QLIKE Comparison Across Assets
# ============================================================
print("\n" + "=" * 70)
print("[8] GARCH QLIKE Comparison Across Assets")
print("=" * 70)

garch_comparison = {}
for ticker in ['NG=F', 'CL=F', 'SPY']:
    if ticker not in returns:
        continue
    r = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()
    r_scaled = r * 100

    n_total = len(r_scaled)
    n_is = int(n_total * 0.7)
    n_oos = n_total - n_is

    r_is = r_scaled.iloc[:n_is]
    r_oos = r_scaled.iloc[n_is:]

    # Realized variance (OOS) = r² (daily, in pct²)
    rv_oos = r_oos ** 2

    models_to_fit = {
        'GARCH(1,1)': {'vol': 'GARCH', 'p': 1, 'o': 0, 'q': 1},
        'GJR-GARCH': {'vol': 'GARCH', 'p': 1, 'o': 1, 'q': 1},
        'EGARCH': {'vol': 'EGARCH', 'p': 1, 'o': 1, 'q': 1},
    }

    print(f"\n  {asset_names[ticker]} (IS={n_is}, OOS={n_oos}):")

    asset_results = {}
    for model_name, params in models_to_fit.items():
        try:
            model = arch_model(r_is, vol=params['vol'], p=params['p'],
                             o=params['o'], q=params['q'],
                             mean='Constant', dist='t')
            res = model.fit(disp='off', show_warning=False,
                          options={'maxiter': 500})

            # Forecast OOS
            forecasts = res.forecast(horizon=1, start=r_is.index[-1],
                                    method='simulation' if params['vol'] == 'EGARCH' else 'analytic')
            h_oos = forecasts.variance

            # Align with OOS
            # Get the variance forecasts that correspond to OOS dates
            h_aligned = h_oos.reindex(r_oos.index)
            h_aligned = h_aligned.iloc[:, 0] if isinstance(h_aligned, pd.DataFrame) else h_aligned

            # Drop NaN
            valid = pd.DataFrame({'rv': rv_oos, 'h': h_aligned}).dropna()

            if len(valid) < 100:
                # Try alternative: fit on full sample, get in-sample conditional variance
                model_full = arch_model(r_scaled, vol=params['vol'], p=params['p'],
                                       o=params['o'], q=params['q'],
                                       mean='Constant', dist='t')
                res_full = model_full.fit(disp='off', show_warning=False,
                                         options={'maxiter': 500})
                h_full = res_full.conditional_volatility ** 2
                h_oos_alt = h_full.iloc[n_is:]

                valid = pd.DataFrame({'rv': rv_oos, 'h': h_oos_alt}).dropna()

            if len(valid) > 100:
                rv_v = valid['rv'].values
                h_v = valid['h'].values

                # Clamp h to avoid log(0)
                h_v = np.maximum(h_v, 1e-10)

                # QLIKE = mean(rv/h + log(h))
                qlike = np.mean(rv_v / h_v + np.log(h_v))

                # MSE
                mse = np.mean((rv_v - h_v) ** 2)

                asset_results[model_name] = {
                    'qlike': round(float(qlike), 4),
                    'mse': round(float(mse), 4),
                    'n_oos': len(valid),
                }

                print(f"    {model_name:15s}: QLIKE={qlike:.4f}  MSE={mse:.4f}  (n={len(valid)})")
            else:
                print(f"    {model_name:15s}: Insufficient OOS data ({len(valid)} points)")

        except Exception as e:
            print(f"    {model_name:15s}: FAILED - {e}")

    if asset_results:
        # Find best model by QLIKE
        best = min(asset_results, key=lambda x: asset_results[x]['qlike'])
        print(f"    Best model: {best}")
        asset_results['best_model'] = best

    garch_comparison[ticker] = asset_results

RESULTS['garch_qlike_comparison'] = garch_comparison

# ============================================================
# 9. Can NG Vol Predict Equity Vol? (Granger-style)
# ============================================================
print("\n" + "=" * 70)
print("[9] Can NG Vol Predict Equity Vol?")
print("=" * 70)

if 'NG=F' in returns and 'SPY' in returns and '^VIX' in data:
    r_ng = returns['NG=F'].replace([np.inf, -np.inf], np.nan)
    r_spy = returns['SPY'].replace([np.inf, -np.inf], np.nan)
    vix = data['^VIX']

    # Compute realized vol (21-day rolling)
    rv_ng = (r_ng ** 2).rolling(21).sum()
    rv_spy = (r_spy ** 2).rolling(21).sum()

    # Also use VIX level
    # Align all on common dates
    combined = pd.DataFrame({
        'rv_ng': rv_ng,
        'rv_spy': rv_spy,
        'vix': vix,
    }).dropna()

    print(f"\n  Common observations: {len(combined)}")

    # Predictive regression: rv_spy(t+21) = a + b1*rv_spy(t) + b2*rv_ng(t) + e
    # Forward-looking rv_spy
    combined['rv_spy_fwd'] = combined['rv_spy'].shift(-21)
    combined = combined.dropna()

    from numpy.linalg import lstsq

    # Model 1: rv_spy(t) alone
    X1 = np.column_stack([np.ones(len(combined)), combined['rv_spy'].values])
    y = combined['rv_spy_fwd'].values
    b1, _, _, _ = lstsq(X1, y, rcond=None)
    y_hat1 = X1 @ b1
    r2_1 = 1 - np.sum((y - y_hat1)**2) / np.sum((y - y.mean())**2)

    # Model 2: rv_spy(t) + rv_ng(t)
    X2 = np.column_stack([np.ones(len(combined)), combined['rv_spy'].values, combined['rv_ng'].values])
    b2, _, _, _ = lstsq(X2, y, rcond=None)
    y_hat2 = X2 @ b2
    r2_2 = 1 - np.sum((y - y_hat2)**2) / np.sum((y - y.mean())**2)

    # Model 3: rv_spy(t) + rv_ng(t) + VIX(t)
    X3 = np.column_stack([np.ones(len(combined)), combined['rv_spy'].values,
                          combined['rv_ng'].values, combined['vix'].values])
    b3, _, _, _ = lstsq(X3, y, rcond=None)
    y_hat3 = X3 @ b3
    r2_3 = 1 - np.sum((y - y_hat3)**2) / np.sum((y - y.mean())**2)

    # Incremental R² from adding NG vol
    delta_r2 = r2_2 - r2_1

    # Significance test for NG coefficient in Model 2
    n = len(y)
    k = 3  # intercept + 2 regressors
    e2 = y - y_hat2
    s2 = np.sum(e2**2) / (n - k)
    XtX_inv = np.linalg.inv(X2.T @ X2)
    se_b = np.sqrt(s2 * np.diag(XtX_inv))
    t_ng = b2[2] / se_b[2]

    pred_result = {
        'r2_spy_only': round(float(r2_1), 4),
        'r2_spy_plus_ng': round(float(r2_2), 4),
        'r2_spy_ng_vix': round(float(r2_3), 4),
        'delta_r2_from_ng': round(float(delta_r2), 4),
        'ng_coeff': round(float(b2[2]), 6),
        'ng_tstat': round(float(t_ng), 2),
        'n_obs': n,
    }

    print(f"\n  Predicting SPY RV(t+21) from:")
    print(f"    Model 1 (SPY RV only):          R² = {r2_1:.4f}")
    print(f"    Model 2 (+NG RV):                R² = {r2_2:.4f}  (ΔR² = {delta_r2:.4f})")
    print(f"    Model 3 (+NG RV + VIX):          R² = {r2_3:.4f}")
    print(f"\n    NG vol coefficient:  {b2[2]:.6f}  (t={t_ng:.2f})")

    if abs(t_ng) > 2:
        print(f"    → NG vol has SIGNIFICANT predictive power for equity vol")
    elif abs(t_ng) > 1.5:
        print(f"    → NG vol has MARGINAL predictive power (t={t_ng:.2f})")
    else:
        print(f"    → NG vol has NO predictive power for equity vol")

    RESULTS['ng_predicts_spy_vol'] = pred_result

# ============================================================
# 10. Extreme Events Analysis: NG "Blow-ups"
# ============================================================
print("\n" + "=" * 70)
print("[10] Extreme Events: NG Blow-ups")
print("=" * 70)

if 'NG=F' in returns:
    r_ng = returns['NG=F'].replace([np.inf, -np.inf], np.nan).dropna()

    # Find top 20 absolute returns
    abs_r = np.abs(r_ng).sort_values(ascending=False)

    print("\n  Top 20 Most Extreme NG Daily Moves:")
    top_events = []
    for i, (date, val) in enumerate(abs_r.head(20).items()):
        direction = "UP" if r_ng.loc[date] > 0 else "DOWN"
        pct = r_ng.loc[date] * 100

        # Check month — is it winter?
        month = date.month
        is_winter = month in [11, 12, 1, 2, 3]
        season = "WINTER" if is_winter else "SUMMER" if month in [5,6,7,8,9] else "TRANS"

        print(f"    {i+1:2d}. {date.date()} ({season:6s}): {pct:+7.2f}% ({direction})")
        top_events.append({
            'date': str(date.date()),
            'return_pct': round(float(pct), 2),
            'season': season,
        })

    # Count winter vs non-winter in top 50 extremes
    top50_months = abs_r.head(50).index.month
    n_winter_extreme = sum(m in [11, 12, 1, 2, 3] for m in top50_months)
    expected_winter = 50 * (5/12)  # 5 months / 12

    print(f"\n  Top 50 extreme days: {n_winter_extreme}/50 in winter months")
    print(f"  Expected (random):   {expected_winter:.0f}/50")
    if n_winter_extreme > expected_winter:
        print(f"  → Extreme events CLUSTER in winter")
    else:
        print(f"  → No winter clustering of extreme events")

    RESULTS['extreme_events'] = {
        'top_20': top_events,
        'top50_winter_count': int(n_winter_extreme),
        'top50_expected_winter': round(float(expected_winter), 0),
    }

# ============================================================
# 11. Rolling Volatility Comparison (NG vs Oil vs SPY)
# ============================================================
print("\n" + "=" * 70)
print("[11] Rolling Volatility Statistics (63-day)")
print("=" * 70)

rv_stats = {}
for ticker in ['NG=F', 'CL=F', 'SPY']:
    if ticker not in returns:
        continue
    r = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()
    rv63 = r.rolling(63).std() * np.sqrt(252) * 100
    rv63 = rv63.dropna()

    rv_stats[ticker] = {
        'name': asset_names[ticker],
        'mean_vol': round(float(rv63.mean()), 1),
        'median_vol': round(float(rv63.median()), 1),
        'max_vol': round(float(rv63.max()), 1),
        'min_vol': round(float(rv63.min()), 1),
        'vol_of_vol': round(float(rv63.std()), 1),
        'p95_vol': round(float(rv63.quantile(0.95)), 1),
        'p5_vol': round(float(rv63.quantile(0.05)), 1),
    }

    print(f"\n  {asset_names[ticker]}:")
    print(f"    Mean RV(63d):   {rv63.mean():.1f}%")
    print(f"    Median:         {rv63.median():.1f}%")
    print(f"    Range:          [{rv63.min():.1f}%, {rv63.max():.1f}%]")
    print(f"    P5-P95:         [{rv63.quantile(0.05):.1f}%, {rv63.quantile(0.95):.1f}%]")
    print(f"    Vol-of-Vol:     {rv63.std():.1f}%")

RESULTS['rolling_vol_stats'] = rv_stats

# ============================================================
# 12. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("[12] SUMMARY & CONCLUSIONS")
print("=" * 70)

# Compile key findings
summary_points = []

# 1. Vol level
if 'NG=F' in vol_chars:
    ng_vol = vol_chars['NG=F']['ann_vol_pct']
    spy_vol = vol_chars.get('SPY', {}).get('ann_vol_pct', 0)
    oil_vol = vol_chars.get('CL=F', {}).get('ann_vol_pct', 0)
    ratio_spy = ng_vol / spy_vol if spy_vol > 0 else 0
    ratio_oil = ng_vol / oil_vol if oil_vol > 0 else 0
    summary_points.append(f"NG annualized vol = {ng_vol:.1f}% ({ratio_spy:.1f}x SPY, {ratio_oil:.1f}x Oil)")

# 2. Kurtosis
if 'NG=F' in vol_chars:
    ng_kurt = vol_chars['NG=F']['kurtosis']
    summary_points.append(f"NG excess kurtosis = {ng_kurt:.1f} (extreme tail risk)")

# 3. Clustering
if 'NG=F' in acf_results:
    ng_acf1 = acf_results['NG=F']['lag_1']
    spy_acf1 = acf_results.get('SPY', {}).get('lag_1', 0)
    clustering = "weaker" if ng_acf1 < spy_acf1 else "stronger"
    summary_points.append(f"NG vol clustering ACF(1)={ng_acf1:.4f} ({clustering} than SPY={spy_acf1:.4f})")

# 4. Leverage
if 'NG=F' in gjr_results and 'gamma' in gjr_results['NG=F']:
    ng_gamma = gjr_results['NG=F']['gamma']
    ng_gamma_t = gjr_results['NG=F'].get('gamma_tstat', 0)
    has_lev = "YES" if abs(ng_gamma_t) > 2 else "NO"
    summary_points.append(f"NG leverage effect: {has_lev} (gamma={ng_gamma:.4f}, t={ng_gamma_t:.2f})")

# 5. Seasonality
if 'seasonality' in RESULTS:
    s = RESULTS['seasonality']
    summary_points.append(f"Winter vol premium: {s['winter_premium_pct']:.1f}% (p={s['ttest_pval']:.6f})")

# 6. EIA day
if 'eia_thursday_effect' in RESULTS:
    e = RESULTS['eia_thursday_effect']
    summary_points.append(f"Thursday (EIA) premium: {e['thu_premium_pct']:.1f}% (p={e['ttest_pval']:.6f})")

# 7. NG-Oil correlation
if 'ng_oil_vol_correlation' in RESULTS:
    c = RESULTS['ng_oil_vol_correlation']
    summary_points.append(f"NG-Oil vol corr: {c['rv21_corr']:.4f} (return corr: {c['return_corr']:.4f})")

# 8. Predictive power
if 'ng_predicts_spy_vol' in RESULTS:
    p = RESULTS['ng_predicts_spy_vol']
    summary_points.append(f"NG vol predicts SPY vol: ΔR²={p['delta_r2_from_ng']:.4f}, t={p['ng_tstat']:.2f}")

print("\n  Key Findings:")
for i, point in enumerate(summary_points, 1):
    print(f"    {i}. {point}")

RESULTS['summary'] = summary_points

# ============================================================
# Save Results
# ============================================================
output_file = 'experiments/k343_natgas_vol_results.json'
with open(output_file, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n  Results saved to: {output_file}")

print("\n" + "=" * 70)
print("K343 COMPLETE")
print("=" * 70)
