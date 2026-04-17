"""
Comprehensive Taiwan Stock Analysis: Financial & Sentiment Indicators
=====================================================================
Analyzes 0050.TW, 2330.TW, 2317.TW with global indicators.
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests
import datetime

print("=" * 80)
print("COMPREHENSIVE TAIWAN STOCK ANALYSIS")
print("Financial & Sentiment Indicators")
print("=" * 80)

# =============================================================================
# 1. DATA LOADING
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 1: DATA LOADING")
print("=" * 80)

tickers = {
    '0050.TW': 'Taiwan 50 ETF',
    '2330.TW': 'TSMC',
    '2317.TW': 'Hon Hai (Foxconn)',
    '^VIX': 'VIX',
    '^VIX3M': 'VIX 3-Month',
    '^TNX': 'US 10Y Yield',
    'TWD=X': 'USD/TWD',
    'GLD': 'Gold ETF',
}

start_date = '2015-01-01'
end_date = '2025-12-31'

print(f"\nDownloading data from {start_date} to present...")
data = {}
for ticker, name in tickers.items():
    try:
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if len(df) > 100:
            data[ticker] = df
            print(f"  {name} ({ticker}): {len(df)} observations, "
                  f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {name} ({ticker}): INSUFFICIENT DATA ({len(df)} obs)")
    except Exception as e:
        print(f"  {name} ({ticker}): FAILED - {e}")

# =============================================================================
# Compute returns and realized vol
# =============================================================================
print("\n--- Computing Returns & Realized Volatility ---")

# Handle potential MultiIndex columns from yfinance
def get_close(df, ticker=None):
    """Extract Close price handling both single and multi-index columns."""
    if isinstance(df.columns, pd.MultiIndex):
        if 'Close' in df.columns.get_level_values(0):
            return df['Close'].iloc[:, 0] if df['Close'].ndim > 1 else df['Close']
        return df.iloc[:, 0]
    if 'Close' in df.columns:
        return df['Close']
    return df.iloc[:, 0]

returns = {}
for ticker in ['0050.TW', '2330.TW', '2317.TW', 'GLD']:
    if ticker in data:
        close = get_close(data[ticker], ticker)
        ret = close.pct_change().dropna() * 100  # percentage returns
        returns[ticker] = ret
        print(f"  {ticker}: mean={ret.mean():.4f}%, std={ret.std():.4f}%, "
              f"skew={ret.skew():.3f}, kurt={ret.kurtosis():.3f}")

# VIX levels (not returns)
vix_level = get_close(data['^VIX']) if '^VIX' in data else None
vix3m_level = get_close(data['^VIX3M']) if '^VIX3M' in data else None

# VIX term structure: VIX/VIX3M ratio (contango < 1 = complacent, backwardation > 1 = fear)
if vix_level is not None and vix3m_level is not None:
    # Align dates
    common_idx = vix_level.dropna().index.intersection(vix3m_level.dropna().index)
    vix_term = (vix_level.reindex(common_idx) / vix3m_level.reindex(common_idx))
    print(f"\n  VIX Term Structure (VIX/VIX3M): mean={vix_term.mean():.4f}, "
          f"std={vix_term.std():.4f}")
    print(f"  Backwardation (>1, fear): {(vix_term > 1).sum()} days "
          f"({(vix_term > 1).mean()*100:.1f}%)")
else:
    vix_term = None

# USD/TWD
if 'TWD=X' in data:
    usdtwd = get_close(data['TWD=X'])
    usdtwd_ret = usdtwd.pct_change().dropna() * 100
    print(f"\n  USD/TWD: last={usdtwd.iloc[-1]:.2f}, mean return={usdtwd_ret.mean():.4f}%")
else:
    usdtwd = None
    usdtwd_ret = None

# US 10Y yield changes
if '^TNX' in data:
    tnx = get_close(data['^TNX'])
    tnx_change = tnx.diff().dropna()
    print(f"  US 10Y Yield: last={tnx.iloc[-1]:.2f}%, mean change={tnx_change.mean():.4f}")
else:
    tnx = None
    tnx_change = None

# Realized volatility (20-day rolling)
print("\n--- 20-day Realized Volatility ---")
rv = {}
for ticker in ['0050.TW', '2330.TW', '2317.TW']:
    if ticker in returns:
        rv[ticker] = returns[ticker].rolling(20).std() * np.sqrt(252)
        recent_rv = rv[ticker].dropna().iloc[-1]
        mean_rv = rv[ticker].dropna().mean()
        print(f"  {ticker}: current RV={recent_rv:.2f}%, mean RV={mean_rv:.2f}%")

# =============================================================================
# 2. CORRELATION ANALYSIS
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 2: CORRELATION ANALYSIS")
print("0050.TW Returns vs All Indicators (Contemporaneous + Lagged)")
print("=" * 80)

# Build indicator DataFrame
indicators = {}
if '0050.TW' in returns:
    indicators['0050_ret'] = returns['0050.TW']
if vix_level is not None:
    indicators['VIX'] = vix_level
    indicators['VIX_chg'] = vix_level.pct_change().dropna() * 100
if vix_term is not None:
    indicators['VIX_term'] = vix_term
if usdtwd is not None:
    indicators['USDTWD'] = usdtwd
    indicators['USDTWD_ret'] = usdtwd_ret
if tnx is not None:
    indicators['TNX'] = tnx
    indicators['TNX_chg'] = tnx_change
if 'GLD' in returns:
    indicators['GLD_ret'] = returns['GLD']
if '0050.TW' in rv:
    indicators['0050_RV20'] = rv['0050.TW']

ind_df = pd.DataFrame(indicators)
ind_df = ind_df.dropna()
print(f"\nCommon date range: {ind_df.index[0].strftime('%Y-%m-%d')} to "
      f"{ind_df.index[-1].strftime('%Y-%m-%d')} ({len(ind_df)} obs)")

# Contemporaneous correlations
print("\n--- Contemporaneous Correlations with 0050.TW Returns ---")
for col in ind_df.columns:
    if col != '0050_ret':
        corr, pval = stats.pearsonr(ind_df['0050_ret'], ind_df[col])
        sig = '***' if pval < 0.001 else '**' if pval < 0.01 else '*' if pval < 0.05 else ''
        print(f"  {col:15s}: r={corr:+.4f} (p={pval:.4f}) {sig}")

# Lagged correlations (indicator at t-k vs 0050 return at t)
print("\n--- Lagged Correlations: Indicator(t-k) → 0050.TW Return(t) ---")
print(f"{'Indicator':15s} {'Lag-1':>10s} {'Lag-2':>10s} {'Lag-3':>10s} {'Lag-4':>10s} {'Lag-5':>10s}")
print("-" * 70)

indicator_cols = [c for c in ind_df.columns if c not in ['0050_ret', '0050_RV20']]
for col in indicator_cols:
    row = f"{col:15s}"
    for lag in range(1, 6):
        lagged = ind_df[col].shift(lag)
        valid = pd.DataFrame({'ret': ind_df['0050_ret'], 'ind': lagged}).dropna()
        corr, pval = stats.pearsonr(valid['ret'], valid['ind'])
        sig = '*' if pval < 0.05 else ' '
        row += f" {corr:+.4f}{sig}  "
    print(row)

# Cross-correlation with realized vol
print("\n--- Lagged Correlations: Indicator(t-k) → 0050.TW Realized Vol(t) ---")
print(f"{'Indicator':15s} {'Lag-0':>10s} {'Lag-1':>10s} {'Lag-3':>10s} {'Lag-5':>10s} {'Lag-10':>10s}")
print("-" * 70)

if '0050_RV20' in ind_df.columns:
    for col in indicator_cols:
        row = f"{col:15s}"
        for lag in [0, 1, 3, 5, 10]:
            lagged = ind_df[col].shift(lag)
            valid = pd.DataFrame({'rv': ind_df['0050_RV20'], 'ind': lagged}).dropna()
            corr, pval = stats.pearsonr(valid['rv'], valid['ind'])
            sig = '*' if pval < 0.05 else ' '
            row += f" {corr:+.4f}{sig}  "
        print(row)

# =============================================================================
# 3. GARCH VOLATILITY COMPARISON
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 3: GARCH VOLATILITY COMPARISON")
print("0050.TW vs TSMC vs Hon Hai — GJR-GARCH(1,1)")
print("=" * 80)

garch_results = {}
for ticker in ['0050.TW', '2330.TW', '2317.TW']:
    if ticker not in returns:
        continue
    ret = returns[ticker].dropna()
    # Use full sample for parameter estimation
    try:
        am = arch_model(ret, vol='GARCH', p=1, o=1, q=1, dist='StudentsT')
        res = am.fit(disp='off', options={'maxiter': 1000})

        params = res.params
        omega = params.get('omega', 0)
        alpha = params.get('alpha[1]', 0)
        gamma = params.get('gamma[1]', 0)
        beta = params.get('beta[1]', 0)
        nu = params.get('nu', 0)

        persistence = alpha + gamma/2 + beta

        garch_results[ticker] = {
            'omega': omega, 'alpha': alpha, 'gamma': gamma,
            'beta': beta, 'nu': nu, 'persistence': persistence,
            'loglik': res.loglikelihood, 'bic': res.bic
        }

        # Get p-values
        pvals = res.pvalues
        gamma_pval = pvals.get('gamma[1]', 1.0)

        print(f"\n  {tickers[ticker]} ({ticker}):")
        print(f"    ω = {omega:.6f}")
        print(f"    α = {alpha:.4f} (ARCH)")
        print(f"    γ = {gamma:.4f} (Leverage) [p={gamma_pval:.4f}] {'***' if gamma_pval<0.001 else '**' if gamma_pval<0.01 else '*' if gamma_pval<0.05 else 'ns'}")
        print(f"    β = {beta:.4f} (GARCH)")
        print(f"    ν = {nu:.2f} (Student-t df)")
        print(f"    Persistence = {persistence:.4f}")
        print(f"    BIC = {res.bic:.2f}")

        if gamma > 0:
            asym_ratio = (alpha + gamma) / alpha if alpha > 0 else float('inf')
            print(f"    Asymmetry ratio (bad/good news): {asym_ratio:.2f}x")
        else:
            print(f"    NOTE: γ < 0 → INVERTED leverage effect!")

    except Exception as e:
        print(f"  {ticker}: GARCH FAILED - {e}")

# Compare gammas
print("\n--- Gamma Comparison ---")
if len(garch_results) >= 2:
    sorted_gamma = sorted(garch_results.items(), key=lambda x: x[1]['gamma'], reverse=True)
    for ticker, res in sorted_gamma:
        print(f"  {tickers[ticker]:20s}: γ={res['gamma']:.4f}, persistence={res['persistence']:.4f}")

    # Is TSMC gamma different from 0050?
    if '2330.TW' in garch_results and '0050.TW' in garch_results:
        g_tsmc = garch_results['2330.TW']['gamma']
        g_0050 = garch_results['0050.TW']['gamma']
        print(f"\n  TSMC γ ({g_tsmc:.4f}) vs 0050 γ ({g_0050:.4f}): "
              f"difference = {g_tsmc - g_0050:+.4f}")
        if g_tsmc > g_0050:
            print(f"  → TSMC has STRONGER leverage effect than 0050.TW")
        else:
            print(f"  → 0050.TW has STRONGER leverage effect than TSMC")

# =============================================================================
# 4. VIX → 0050.TW SPILLOVER (Granger Causality)
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 4: VIX → 0050.TW VOLATILITY SPILLOVER")
print("Granger Causality Tests")
print("=" * 80)

if vix_level is not None and '0050.TW' in rv:
    # Build aligned dataset
    vix_rv = pd.DataFrame({
        'VIX': vix_level,
        '0050_RV': rv['0050.TW'],
    }).dropna()

    print(f"\nSample: {vix_rv.index[0].strftime('%Y-%m-%d')} to "
          f"{vix_rv.index[-1].strftime('%Y-%m-%d')} ({len(vix_rv)} obs)")

    # Granger causality: VIX → 0050.TW RV
    print("\n--- Granger Causality: VIX → 0050.TW Realized Vol ---")
    print(f"{'Lags':>6s} {'F-stat':>10s} {'p-value':>10s} {'Sig':>5s}")
    print("-" * 35)

    try:
        gc_results = grangercausalitytests(
            vix_rv[['0050_RV', 'VIX']].values, maxlag=10, verbose=False
        )
        for lag in range(1, 11):
            fstat = gc_results[lag][0]['ssr_ftest'][0]
            pval = gc_results[lag][0]['ssr_ftest'][1]
            sig = '***' if pval < 0.001 else '**' if pval < 0.01 else '*' if pval < 0.05 else ''
            print(f"  {lag:4d}   {fstat:10.3f} {pval:10.4f}  {sig}")
    except Exception as e:
        print(f"  Granger test failed: {e}")

    # Reverse: 0050.TW RV → VIX (should be weaker)
    print("\n--- Granger Causality: 0050.TW Realized Vol → VIX (reverse) ---")
    print(f"{'Lags':>6s} {'F-stat':>10s} {'p-value':>10s} {'Sig':>5s}")
    print("-" * 35)

    try:
        gc_rev = grangercausalitytests(
            vix_rv[['VIX', '0050_RV']].values, maxlag=10, verbose=False
        )
        for lag in range(1, 11):
            fstat = gc_rev[lag][0]['ssr_ftest'][0]
            pval = gc_rev[lag][0]['ssr_ftest'][1]
            sig = '***' if pval < 0.001 else '**' if pval < 0.01 else '*' if pval < 0.05 else ''
            print(f"  {lag:4d}   {fstat:10.3f} {pval:10.4f}  {sig}")
    except Exception as e:
        print(f"  Reverse Granger test failed: {e}")

# Also test VIX term structure
if vix_term is not None and '0050.TW' in rv:
    vterm_rv = pd.DataFrame({
        'VIX_term': vix_term,
        '0050_RV': rv['0050.TW'],
    }).dropna()

    print("\n--- Granger Causality: VIX Term Structure → 0050.TW RV ---")
    print(f"{'Lags':>6s} {'F-stat':>10s} {'p-value':>10s} {'Sig':>5s}")
    print("-" * 35)

    try:
        gc_term = grangercausalitytests(
            vterm_rv[['0050_RV', 'VIX_term']].values, maxlag=5, verbose=False
        )
        for lag in range(1, 6):
            fstat = gc_term[lag][0]['ssr_ftest'][0]
            pval = gc_term[lag][0]['ssr_ftest'][1]
            sig = '***' if pval < 0.001 else '**' if pval < 0.01 else '*' if pval < 0.05 else ''
            print(f"  {lag:4d}   {fstat:10.3f} {pval:10.4f}  {sig}")
    except Exception as e:
        print(f"  VIX term Granger test failed: {e}")

# =============================================================================
# 5. USD/TWD INCREMENTAL INFORMATION
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 5: USD/TWD INCREMENTAL INFORMATION")
print("Does USD/TWD add info beyond VIX for Taiwan vol?")
print("=" * 80)

if usdtwd_ret is not None and vix_level is not None and '0050.TW' in rv:
    from statsmodels.regression.linear_model import OLS
    from statsmodels.tools import add_constant

    combo = pd.DataFrame({
        '0050_RV': rv['0050.TW'],
        'VIX': vix_level,
        'USDTWD_ret': usdtwd_ret,
    }).dropna()

    # Lagged predictors (t-1)
    combo['VIX_lag1'] = combo['VIX'].shift(1)
    combo['USDTWD_lag1'] = combo['USDTWD_ret'].shift(1)
    combo['RV_lag1'] = combo['0050_RV'].shift(1)
    combo = combo.dropna()

    # Model 1: RV ~ RV_lag + VIX_lag
    X1 = add_constant(combo[['RV_lag1', 'VIX_lag1']])
    model1 = OLS(combo['0050_RV'], X1).fit()

    # Model 2: RV ~ RV_lag + VIX_lag + USDTWD_lag
    X2 = add_constant(combo[['RV_lag1', 'VIX_lag1', 'USDTWD_lag1']])
    model2 = OLS(combo['0050_RV'], X2).fit()

    print(f"\nModel 1 (RV_lag + VIX_lag):         R² = {model1.rsquared:.4f}, AIC = {model1.aic:.1f}")
    print(f"Model 2 (+ USD/TWD_lag):            R² = {model2.rsquared:.4f}, AIC = {model2.aic:.1f}")
    print(f"  ΔR² = {model2.rsquared - model1.rsquared:+.6f}")
    print(f"  USDTWD_lag coef = {model2.params['USDTWD_lag1']:.4f}, "
          f"t = {model2.tvalues['USDTWD_lag1']:.3f}, p = {model2.pvalues['USDTWD_lag1']:.4f}")

    if model2.pvalues['USDTWD_lag1'] < 0.05:
        print("  → USD/TWD ADDS significant information beyond VIX")
    else:
        print("  → USD/TWD does NOT add significant information beyond VIX")

    # Also check contemporaneous
    X3 = add_constant(combo[['RV_lag1', 'VIX', 'USDTWD_ret']])
    model3 = OLS(combo['0050_RV'], X3).fit()
    print(f"\nContemporaneous model (RV_lag + VIX + USDTWD):")
    print(f"  R² = {model3.rsquared:.4f}")
    print(f"  USDTWD coef = {model3.params['USDTWD_ret']:.4f}, "
          f"t = {model3.tvalues['USDTWD_ret']:.3f}, p = {model3.pvalues['USDTWD_ret']:.4f}")

# =============================================================================
# 6. REGIME ANALYSIS
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 6: REGIME ANALYSIS")
print("Do financial indicators predict 0050.TW vol regimes?")
print("=" * 80)

if '0050.TW' in rv:
    rv_0050 = rv['0050.TW'].dropna()

    # Define regimes: Low (<P25), Normal (P25-P75), High (>P75)
    p25 = rv_0050.quantile(0.25)
    p75 = rv_0050.quantile(0.75)

    regime = pd.Series(index=rv_0050.index, dtype=str)
    regime[rv_0050 <= p25] = 'Low'
    regime[(rv_0050 > p25) & (rv_0050 <= p75)] = 'Normal'
    regime[rv_0050 > p75] = 'High'

    print(f"\nVol Regime Thresholds: Low ≤ {p25:.2f}%, Normal, High > {p75:.2f}%")
    print(f"  Low: {(regime=='Low').sum()} days, Normal: {(regime=='Normal').sum()} days, "
          f"High: {(regime=='High').sum()} days")

    # What do indicators look like in each regime?
    regime_df = pd.DataFrame({
        'regime': regime,
        'VIX': vix_level.reindex(regime.index) if vix_level is not None else np.nan,
        'USDTWD': usdtwd.reindex(regime.index) if usdtwd is not None else np.nan,
        'TNX': tnx.reindex(regime.index) if tnx is not None else np.nan,
    }).dropna()

    if len(regime_df) > 100:
        print("\n--- Mean Indicator Values by Vol Regime ---")
        print(f"{'Indicator':>12s} {'Low Vol':>12s} {'Normal':>12s} {'High Vol':>12s} {'High/Low':>12s}")
        print("-" * 55)

        for col in ['VIX', 'USDTWD', 'TNX']:
            if col in regime_df.columns:
                means = regime_df.groupby('regime')[col].mean()
                if 'Low' in means.index and 'High' in means.index:
                    ratio = means['High'] / means['Low'] if means['Low'] != 0 else np.nan
                    print(f"  {col:10s} {means.get('Low', np.nan):12.2f} "
                          f"{means.get('Normal', np.nan):12.2f} "
                          f"{means.get('High', np.nan):12.2f} "
                          f"{ratio:12.3f}")

        # VIX term structure by regime
        if vix_term is not None:
            regime_df['VIX_term'] = vix_term.reindex(regime_df.index)
            regime_df_vt = regime_df.dropna(subset=['VIX_term'])
            if len(regime_df_vt) > 50:
                means = regime_df_vt.groupby('regime')['VIX_term'].mean()
                backwd_rate = regime_df_vt.groupby('regime').apply(
                    lambda x: (x['VIX_term'] > 1).mean(), include_groups=False
                )
                print(f"\n  VIX Term Structure by Regime:")
                for r in ['Low', 'Normal', 'High']:
                    if r in means.index:
                        print(f"    {r}: mean ratio={means[r]:.4f}, "
                              f"backwardation rate={backwd_rate.get(r, 0)*100:.1f}%")

# =============================================================================
# 7. PREDICTIVE ANALYSIS (OOS)
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 7: OUT-OF-SAMPLE PREDICTIVE ANALYSIS")
print("Can indicators predict 0050.TW next-day vol? (OOS: 2023-2024)")
print("=" * 80)

if '0050.TW' in returns and vix_level is not None:
    from statsmodels.regression.linear_model import OLS
    from statsmodels.tools import add_constant

    # Build prediction dataset
    ret_0050 = returns['0050.TW']

    # Next-day absolute return as vol proxy
    pred_df = pd.DataFrame({
        'abs_ret_next': ret_0050.abs().shift(-1),  # target: next day |return|
        'abs_ret': ret_0050.abs(),  # current day
        'VIX': vix_level,
        'VIX_chg': vix_level.pct_change() * 100,
    })

    if vix_term is not None:
        pred_df['VIX_term'] = vix_term
    if usdtwd_ret is not None:
        pred_df['USDTWD_ret'] = usdtwd_ret
    if tnx_change is not None:
        pred_df['TNX_chg'] = tnx_change
    if 'GLD' in returns:
        pred_df['GLD_ret'] = returns['GLD']

    pred_df = pred_df.dropna()

    # Split
    oos_start = '2023-01-01'
    is_df = pred_df[pred_df.index < oos_start]
    oos_df = pred_df[pred_df.index >= oos_start]

    print(f"\nIn-sample: {is_df.index[0].strftime('%Y-%m-%d')} to "
          f"{is_df.index[-1].strftime('%Y-%m-%d')} ({len(is_df)} obs)")
    print(f"OOS:       {oos_df.index[0].strftime('%Y-%m-%d')} to "
          f"{oos_df.index[-1].strftime('%Y-%m-%d')} ({len(oos_df)} obs)")

    target = 'abs_ret_next'
    predictors_list = {
        'AR(1)': ['abs_ret'],
        'VIX only': ['abs_ret', 'VIX'],
        'VIX + term': ['abs_ret', 'VIX', 'VIX_term'] if 'VIX_term' in pred_df.columns else ['abs_ret', 'VIX'],
        'VIX + USDTWD': ['abs_ret', 'VIX', 'USDTWD_ret'] if 'USDTWD_ret' in pred_df.columns else ['abs_ret', 'VIX'],
        'All indicators': [c for c in pred_df.columns if c != target],
    }

    print(f"\n{'Model':25s} {'IS R²':>8s} {'OOS R²':>8s} {'OOS MAE':>8s} {'OOS Corr':>9s}")
    print("-" * 62)

    for name, preds in predictors_list.items():
        available = [p for p in preds if p in is_df.columns]
        if len(available) == 0:
            continue

        X_is = add_constant(is_df[available])
        y_is = is_df[target]
        model = OLS(y_is, X_is).fit()

        X_oos = add_constant(oos_df[available])
        y_oos = oos_df[target]
        y_pred = model.predict(X_oos)

        # OOS metrics
        ss_res = ((y_oos - y_pred) ** 2).sum()
        ss_tot = ((y_oos - y_oos.mean()) ** 2).sum()
        oos_r2 = 1 - ss_res / ss_tot
        oos_mae = (y_oos - y_pred).abs().mean()
        oos_corr = np.corrcoef(y_oos, y_pred)[0, 1]

        print(f"  {name:23s} {model.rsquared:8.4f} {oos_r2:8.4f} {oos_mae:8.4f} {oos_corr:9.4f}")

    # VIX/VIX3M term structure specific test
    if 'VIX_term' in pred_df.columns:
        print("\n--- VIX Term Structure Predictive Power ---")
        # When VIX term > 1 (backwardation/fear), is next-day vol higher?
        oos_with_term = oos_df.dropna(subset=['VIX_term'])
        fear = oos_with_term[oos_with_term['VIX_term'] > 1]
        calm = oos_with_term[oos_with_term['VIX_term'] <= 1]

        print(f"  Backwardation days (fear):  n={len(fear)}, "
              f"mean |ret|={fear[target].mean():.4f}%")
        print(f"  Contango days (calm):       n={len(calm)}, "
              f"mean |ret|={calm[target].mean():.4f}%")

        if len(fear) > 10 and len(calm) > 10:
            tstat, pval = stats.ttest_ind(fear[target], calm[target])
            print(f"  t-test: t={tstat:.3f}, p={pval:.4f} "
                  f"{'***' if pval < 0.001 else '**' if pval < 0.01 else '*' if pval < 0.05 else 'ns'}")

# =============================================================================
# 8. GARCH WITH EXOGENOUS VARIABLES
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 8: GARCH-X — EXOGENOUS VARIABLES IN VARIANCE EQUATION")
print("Does VIX improve GARCH vol forecasts for 0050.TW?")
print("=" * 80)

if '0050.TW' in returns and vix_level is not None:
    ret_0050 = returns['0050.TW']

    # Align data
    gx_df = pd.DataFrame({
        'ret': ret_0050,
        'VIX': vix_level,
    }).dropna()

    if usdtwd_ret is not None:
        gx_df['USDTWD_ret'] = usdtwd_ret

    gx_df = gx_df.dropna()

    # Split for OOS
    oos_start = '2023-01-01'
    estimation = gx_df[gx_df.index < oos_start]
    oos = gx_df[gx_df.index >= oos_start]

    # Model 1: Plain GJR-GARCH
    try:
        am1 = arch_model(estimation['ret'], vol='GARCH', p=1, o=1, q=1, dist='StudentsT')
        res1 = am1.fit(disp='off')
        print(f"\nModel 1 (GJR-GARCH): BIC={res1.bic:.1f}")
        print(f"  γ = {res1.params.get('gamma[1]', 0):.4f}")
    except Exception as e:
        print(f"  Model 1 failed: {e}")
        res1 = None

    # Model 2: GJR-GARCH with VIX as exogenous (in mean equation, since arch doesn't support variance-X directly)
    # Instead, do rolling forecast comparison
    print("\n--- Rolling 1-step OOS Forecast Comparison ---")
    print("(Using expanding window from estimation period)")

    window = min(2000, len(estimation))

    # Simple approach: forecast with GARCH, then check if VIX improves
    forecasts_garch = []
    forecasts_actual = []
    dates_oos = []
    vix_values = []

    oos_indices = oos.index[:min(500, len(oos))]  # Limit for speed

    # Use fixed parameters from estimation
    if res1 is not None:
        for i, dt in enumerate(oos_indices):
            if i >= len(oos) - 1:
                break
            # Get actual next-day squared return
            actual_var = oos['ret'].iloc[i] ** 2
            forecasts_actual.append(actual_var)
            vix_values.append(oos['VIX'].iloc[i])
            dates_oos.append(dt)

        # GARCH forecast using fixed params
        full_ret = pd.concat([estimation['ret'], oos['ret'].iloc[:len(oos_indices)]])
        try:
            am_full = arch_model(full_ret, vol='GARCH', p=1, o=1, q=1, dist='StudentsT')
            res_full = am_full.fit(disp='off', last_obs=estimation.index[-1])
            fcast = res_full.forecast(horizon=1, start=oos_indices[0],
                                       reindex=False)

            # Get conditional variance series
            cv = am_full.fit(disp='off').conditional_volatility ** 2

        except:
            pass

    # Alternative: correlation between VIX and GARCH residuals
    if res1 is not None:
        resid2 = res1.resid ** 2
        cond_var = res1.conditional_volatility ** 2
        garch_surprise = resid2 - cond_var  # vol surprise

        vix_aligned = estimation['VIX'].reindex(garch_surprise.index)
        valid = pd.DataFrame({
            'surprise': garch_surprise,
            'VIX': vix_aligned
        }).dropna()

        corr, pval = stats.pearsonr(valid['surprise'], valid['VIX'])
        print(f"\n  Correlation(GARCH vol surprise, VIX): r={corr:.4f}, p={pval:.4f}")
        if pval < 0.05:
            print("  → VIX contains information NOT captured by GARCH")
        else:
            print("  → VIX does NOT add information beyond GARCH")

        # Regression: surprise ~ VIX
        from statsmodels.regression.linear_model import OLS
        from statsmodels.tools import add_constant

        X = add_constant(valid['VIX'])
        reg = OLS(valid['surprise'], X).fit()
        print(f"  Regression surprise ~ VIX: coef={reg.params['VIX']:.6f}, "
              f"t={reg.tvalues['VIX']:.3f}, R²={reg.rsquared:.4f}")

# =============================================================================
# 9. KEY FINDINGS SUMMARY
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 9: KEY FINDINGS SUMMARY")
print("=" * 80)

print("\n=== Q1: Can VIX/VIX3M term structure predict 0050.TW next-day vol? ===")
print("  See Section 7 OOS results above.")

print("\n=== Q2: Does USD/TWD add information beyond VIX for Taiwan vol? ===")
print("  See Section 5 incremental test above.")

print("\n=== Q3: Is TSMC gamma different from 0050.TW? ===")
if '2330.TW' in garch_results and '0050.TW' in garch_results:
    g_tsmc = garch_results['2330.TW']['gamma']
    g_0050 = garch_results['0050.TW']['gamma']
    print(f"  TSMC γ = {g_tsmc:.4f}")
    print(f"  0050 γ = {g_0050:.4f}")
    print(f"  Difference = {g_tsmc - g_0050:+.4f}")
    if abs(g_tsmc - g_0050) > 0.02:
        print(f"  → Substantial difference; TSMC ≈ 50% of 0050 but gamma differs")
    else:
        print(f"  → Similar gamma, consistent with TSMC dominating 0050")

print("\n=== Q4: Which indicator has highest cross-correlation with 0050.TW RV? ===")
if '0050_RV20' in ind_df.columns:
    best_corr = 0
    best_name = ''
    for col in indicator_cols:
        valid = pd.DataFrame({'rv': ind_df['0050_RV20'], 'ind': ind_df[col]}).dropna()
        corr, _ = stats.pearsonr(valid['rv'], valid['ind'])
        if abs(corr) > abs(best_corr):
            best_corr = corr
            best_name = col
    print(f"  Highest contemporaneous |correlation|: {best_name} (r={best_corr:.4f})")

    # Also check lagged
    best_lag_corr = 0
    best_lag_name = ''
    best_lag_k = 0
    for col in indicator_cols:
        for k in range(1, 11):
            lagged = ind_df[col].shift(k)
            valid = pd.DataFrame({'rv': ind_df['0050_RV20'], 'ind': lagged}).dropna()
            corr, _ = stats.pearsonr(valid['rv'], valid['ind'])
            if abs(corr) > abs(best_lag_corr):
                best_lag_corr = corr
                best_lag_name = col
                best_lag_k = k
    print(f"  Highest lagged |correlation|: {best_lag_name} at lag-{best_lag_k} (r={best_lag_corr:.4f})")

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
