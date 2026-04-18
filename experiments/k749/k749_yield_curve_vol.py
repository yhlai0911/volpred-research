"""
K749: Yield Curve Slope and Equity Volatility
Does the Bond Market Predict Stock Fear?

[提出: Claude, 執行: Claude]

Hypothesis: Yield curve slope (10Y-3M) contains information about future equity
volatility beyond what VIX already captures.

Data sources:
- ^TNX (10Y Treasury yield) from yfinance
- ^IRX (13-week T-bill rate) from yfinance
- SPY (S&P 500 ETF) from yfinance
- ^VIX from yfinance
- Period: 2006-01-01 to 2026-03-28

References:
- Estrella & Hardouvelis (1991) "The Term Structure as a Predictor of Real Economic Activity"
- Harvey (1988) "The Real Term Structure and Consumption Growth"
- Adrian et al. (2019) "Vulnerable Growth" AER - yield curve predicts downside risk
- Bauer & Mertens (2018) "Economic Forecasting with the Yield Curve" FRBSF

Methodology:
- Part A: Yield curve characteristics (slope distribution, inversion episodes)
- Part B: Predictive regressions (slope → future RV, partial corr vs VIX)
- Part C: Inversion as vol warning signal (event study)
- Part D: Trading strategy (monthly rebalancing, lag=1, TX=10bps round-trip)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.stats.diagnostic import acorr_ljungbox
from pathlib import Path

warnings.filterwarnings('ignore')

RESULTS = {}
OUTPUT_DIR = Path(__file__).parent

# ============================================================
# DATA COLLECTION
# ============================================================
print("=" * 70)
print("K749: Yield Curve Slope and Equity Volatility")
print("=" * 70)

print("\n[1] Downloading data...")
tickers = {
    'TNX': '^TNX',    # 10-Year Treasury Yield
    'IRX': '^IRX',    # 13-Week T-Bill Rate
    'SPY': 'SPY',
    'VIX': '^VIX'
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2005-01-01', end='2026-03-29', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].dropna()
    print(f"  {name}: {len(data[name])} obs, {data[name].index[0].date()} to {data[name].index[-1].date()}")

# Align all series
df = pd.DataFrame(data).dropna()
print(f"\n  Aligned dataset: {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")

# ============================================================
# PART A: YIELD CURVE CHARACTERISTICS
# ============================================================
print("\n" + "=" * 70)
print("PART A: Yield Curve Characteristics")
print("=" * 70)

# Compute yield curve slope: 10Y - 3M
df['slope'] = df['TNX'] - df['IRX']
df['slope_pct'] = df['slope']  # Already in percentage points

# SPY returns
df['spy_ret'] = np.log(df['SPY'] / df['SPY'].shift(1))

# Realized volatility (21-day annualized)
df['rv_21d'] = df['spy_ret'].rolling(21).std() * np.sqrt(252) * 100

# Realized volatility (63-day = ~3 months)
df['rv_63d'] = df['spy_ret'].rolling(63).std() * np.sqrt(252) * 100

# Forward realized volatility (next 21 trading days)
df['fwd_rv_21d'] = df['spy_ret'].shift(-21).rolling(21).std() * np.sqrt(252) * 100
# Shift back to align: for date t, fwd_rv = vol of [t+1, t+21]
# Actually: compute rolling std of returns, then shift entire series
fwd_returns = df['spy_ret'].copy()
fwd_rv = fwd_returns.iloc[::-1].rolling(21).std().iloc[::-1] * np.sqrt(252) * 100
df['fwd_rv_21d'] = fwd_rv.shift(-1)  # vol from t+1 to t+21

# Forward RV 63d
fwd_rv_63 = fwd_returns.iloc[::-1].rolling(63).std().iloc[::-1] * np.sqrt(252) * 100
df['fwd_rv_63d'] = fwd_rv_63.shift(-1)

# Forward RV 126d (6 months)
fwd_rv_126 = fwd_returns.iloc[::-1].rolling(126).std().iloc[::-1] * np.sqrt(252) * 100
df['fwd_rv_126d'] = fwd_rv_126.shift(-1)

# Forward RV 252d (12 months)
fwd_rv_252 = fwd_returns.iloc[::-1].rolling(252).std().iloc[::-1] * np.sqrt(252) * 100
df['fwd_rv_252d'] = fwd_rv_252.shift(-1)

# Slope descriptive statistics
slope = df['slope'].dropna()
desc = {
    'mean': float(slope.mean()),
    'std': float(slope.std()),
    'median': float(slope.median()),
    'min': float(slope.min()),
    'max': float(slope.max()),
    'skewness': float(slope.skew()),
    'kurtosis': float(slope.kurtosis()),
    'pct_negative': float((slope < 0).mean() * 100),
    'n_obs': int(len(slope))
}
print(f"\nSlope (10Y - 3M) descriptive stats:")
for k, v in desc.items():
    print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

RESULTS['part_a'] = {'slope_descriptive': desc}

# Inversion episodes
inversions = df[df['slope'] < 0].copy()
if len(inversions) > 0:
    # Group consecutive inversion days
    inv_dates = inversions.index
    episodes = []
    ep_start = inv_dates[0]
    ep_prev = inv_dates[0]
    for d in inv_dates[1:]:
        if (d - ep_prev).days > 5:  # Gap > 5 calendar days = new episode
            episodes.append({
                'start': str(ep_start.date()),
                'end': str(ep_prev.date()),
                'days': int((ep_prev - ep_start).days)
            })
            ep_start = d
        ep_prev = d
    episodes.append({
        'start': str(ep_start.date()),
        'end': str(ep_prev.date()),
        'days': int((ep_prev - ep_start).days)
    })

    print(f"\nInversion episodes (slope < 0): {len(episodes)}")
    for ep in episodes:
        print(f"  {ep['start']} to {ep['end']} ({ep['days']} calendar days)")

    RESULTS['part_a']['inversion_episodes'] = episodes
    RESULTS['part_a']['total_inversion_days'] = int(len(inversions))
    RESULTS['part_a']['pct_inverted'] = float(len(inversions) / len(df) * 100)
else:
    print("\nNo inversion episodes found.")
    RESULTS['part_a']['inversion_episodes'] = []

# Autocorrelation of slope
from statsmodels.tsa.stattools import acf
slope_acf = acf(slope.dropna(), nlags=20, fft=True)
print(f"\nSlope autocorrelation:")
print(f"  Lag 1: {slope_acf[1]:.4f}")
print(f"  Lag 5: {slope_acf[5]:.4f}")
print(f"  Lag 21: {slope_acf[20]:.4f}")
RESULTS['part_a']['autocorrelation'] = {
    'lag_1': float(slope_acf[1]),
    'lag_5': float(slope_acf[5]),
    'lag_21': float(slope_acf[20])
}

# Slope regime classification
df['slope_regime'] = pd.cut(df['slope'], bins=[-np.inf, -0.5, 0, 1.0, 2.0, np.inf],
                            labels=['deep_inversion', 'mild_inversion', 'flat', 'normal', 'steep'])

regime_stats = {}
for regime in ['deep_inversion', 'mild_inversion', 'flat', 'normal', 'steep']:
    mask = df['slope_regime'] == regime
    if mask.sum() > 0:
        regime_stats[regime] = {
            'n_days': int(mask.sum()),
            'pct': float(mask.mean() * 100),
            'avg_vix': float(df.loc[mask, 'VIX'].mean()),
            'avg_rv_21d': float(df.loc[mask, 'rv_21d'].dropna().mean()),
        }
        print(f"\n  Regime '{regime}': {regime_stats[regime]['n_days']} days ({regime_stats[regime]['pct']:.1f}%), "
              f"avg VIX={regime_stats[regime]['avg_vix']:.1f}, avg RV={regime_stats[regime]['avg_rv_21d']:.1f}%")

RESULTS['part_a']['regime_stats'] = regime_stats

# ============================================================
# PART B: PREDICTIVE POWER
# ============================================================
print("\n" + "=" * 70)
print("PART B: Predictive Power")
print("=" * 70)

# B1: Slope → Future RV regressions
horizons = {
    '21d': 'fwd_rv_21d',
    '63d': 'fwd_rv_63d',
    '126d': 'fwd_rv_126d',
    '252d': 'fwd_rv_252d'
}

regression_results = {}
for h_name, h_col in horizons.items():
    tmp = df[['slope', 'VIX', h_col]].dropna()
    if len(tmp) < 100:
        continue

    # Univariate: slope → fwd RV
    X = add_constant(tmp['slope'])
    y = tmp[h_col]
    model = OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 21})

    # Univariate: VIX → fwd RV
    X_vix = add_constant(tmp['VIX'])
    model_vix = OLS(y, X_vix).fit(cov_type='HAC', cov_kwds={'maxlags': 21})

    # Multivariate: slope + VIX → fwd RV
    X_both = add_constant(tmp[['slope', 'VIX']])
    model_both = OLS(y, X_both).fit(cov_type='HAC', cov_kwds={'maxlags': 21})

    res = {
        'slope_only': {
            'beta': float(model.params.iloc[1]),
            't_stat': float(model.tvalues.iloc[1]),
            'p_value': float(model.pvalues.iloc[1]),
            'r_squared': float(model.rsquared),
        },
        'vix_only': {
            'beta': float(model_vix.params.iloc[1]),
            't_stat': float(model_vix.tvalues.iloc[1]),
            'p_value': float(model_vix.pvalues.iloc[1]),
            'r_squared': float(model_vix.rsquared),
        },
        'slope_plus_vix': {
            'slope_beta': float(model_both.params['slope']),
            'slope_t': float(model_both.tvalues['slope']),
            'slope_p': float(model_both.pvalues['slope']),
            'vix_beta': float(model_both.params['VIX']),
            'vix_t': float(model_both.tvalues['VIX']),
            'vix_p': float(model_both.pvalues['VIX']),
            'r_squared': float(model_both.rsquared),
            'r_sq_improvement': float(model_both.rsquared - model_vix.rsquared),
        },
        'n_obs': int(len(tmp))
    }

    regression_results[h_name] = res
    print(f"\n  Horizon {h_name} (n={len(tmp)}):")
    print(f"    Slope only:  β={res['slope_only']['beta']:.3f}, t={res['slope_only']['t_stat']:.2f}, R²={res['slope_only']['r_squared']:.4f}")
    print(f"    VIX only:    β={res['vix_only']['beta']:.3f}, t={res['vix_only']['t_stat']:.2f}, R²={res['vix_only']['r_squared']:.4f}")
    print(f"    Slope|VIX:   β={res['slope_plus_vix']['slope_beta']:.3f}, t={res['slope_plus_vix']['slope_t']:.2f}")
    print(f"    R² improvement (VIX+Slope vs VIX): {res['slope_plus_vix']['r_sq_improvement']:.4f}")

RESULTS['part_b'] = {'regressions': regression_results}

# B2: Slope CHANGE predicts VIX CHANGE?
df['slope_chg_21d'] = df['slope'] - df['slope'].shift(21)
df['vix_chg_21d'] = df['VIX'] - df['VIX'].shift(21)
df['slope_chg_63d'] = df['slope'] - df['slope'].shift(63)
df['vix_chg_63d'] = df['VIX'] - df['VIX'].shift(63)

# Forward VIX change
df['fwd_vix_chg_21d'] = df['VIX'].shift(-21) - df['VIX']
df['fwd_vix_chg_63d'] = df['VIX'].shift(-63) - df['VIX']

momentum_results = {}
for period in ['21d', '63d']:
    slope_chg = f'slope_chg_{period}'
    fwd_vix = f'fwd_vix_chg_{period}'

    tmp = df[[slope_chg, fwd_vix, 'VIX']].dropna()
    if len(tmp) < 100:
        continue

    X = add_constant(tmp[slope_chg])
    y = tmp[fwd_vix]
    model = OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 21})

    # Controlling for VIX level
    X_ctrl = add_constant(tmp[[slope_chg, 'VIX']])
    model_ctrl = OLS(y, X_ctrl).fit(cov_type='HAC', cov_kwds={'maxlags': 21})

    momentum_results[period] = {
        'univariate': {
            'beta': float(model.params.iloc[1]),
            't_stat': float(model.tvalues.iloc[1]),
            'p_value': float(model.pvalues.iloc[1]),
            'r_squared': float(model.rsquared),
        },
        'controlling_vix': {
            'slope_chg_beta': float(model_ctrl.params[slope_chg]),
            'slope_chg_t': float(model_ctrl.tvalues[slope_chg]),
            'slope_chg_p': float(model_ctrl.pvalues[slope_chg]),
            'r_squared': float(model_ctrl.rsquared),
        },
        'n_obs': int(len(tmp))
    }

    print(f"\n  Slope change {period} → Fwd VIX change {period}:")
    print(f"    Univariate: β={momentum_results[period]['univariate']['beta']:.3f}, "
          f"t={momentum_results[period]['univariate']['t_stat']:.2f}, "
          f"R²={momentum_results[period]['univariate']['r_squared']:.4f}")
    print(f"    Ctrl VIX:   β={momentum_results[period]['controlling_vix']['slope_chg_beta']:.3f}, "
          f"t={momentum_results[period]['controlling_vix']['slope_chg_t']:.2f}")

RESULTS['part_b']['momentum'] = momentum_results

# B3: Partial correlation (slope vs fwd_rv, controlling VIX)
partial_corr_results = {}
for h_name, h_col in horizons.items():
    tmp = df[['slope', 'VIX', h_col]].dropna()
    if len(tmp) < 100:
        continue

    # Partial correlation: residualize both slope and fwd_rv on VIX
    X_vix = add_constant(tmp['VIX'])

    resid_slope = OLS(tmp['slope'], X_vix).fit().resid
    resid_rv = OLS(tmp[h_col], X_vix).fit().resid

    partial_r = float(np.corrcoef(resid_slope, resid_rv)[0, 1])
    # t-test for partial correlation
    n = len(tmp)
    t_stat = partial_r * np.sqrt((n - 3) / (1 - partial_r**2))
    p_value = float(2 * stats.t.sf(abs(t_stat), n - 3))

    partial_corr_results[h_name] = {
        'partial_r': partial_r,
        't_stat': float(t_stat),
        'p_value': p_value,
        'simple_corr_slope_rv': float(tmp['slope'].corr(tmp[h_col])),
        'simple_corr_vix_rv': float(tmp['VIX'].corr(tmp[h_col]))
    }

    print(f"\n  Partial corr (slope, fwd_rv_{h_name} | VIX):")
    print(f"    Simple corr(slope, rv): {partial_corr_results[h_name]['simple_corr_slope_rv']:.4f}")
    print(f"    Simple corr(VIX, rv):   {partial_corr_results[h_name]['simple_corr_vix_rv']:.4f}")
    print(f"    Partial corr:           {partial_corr_results[h_name]['partial_r']:.4f} (t={t_stat:.2f}, p={p_value:.4f})")

RESULTS['part_b']['partial_correlations'] = partial_corr_results

# B4: Granger causality test (slope → VIX)
from statsmodels.tsa.stattools import grangercausalitytests
print("\n  Granger causality: slope → VIX (monthly data)")

# Use monthly frequency for Granger test (slope is slow-moving)
monthly = df[['slope', 'VIX']].resample('ME').last().dropna()
monthly['d_slope'] = monthly['slope'].diff()
monthly['d_vix'] = monthly['VIX'].diff()
monthly_clean = monthly[['d_vix', 'd_slope']].dropna()

if len(monthly_clean) > 50:
    gc_results = {}
    for lag in [1, 2, 3, 6]:
        try:
            gc = grangercausalitytests(monthly_clean[['d_vix', 'd_slope']], maxlag=lag, verbose=False)
            f_stat = gc[lag][0]['ssr_ftest'][0]
            p_val = gc[lag][0]['ssr_ftest'][1]
            gc_results[f'lag_{lag}'] = {'F_stat': float(f_stat), 'p_value': float(p_val)}
            print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f}")
        except Exception as e:
            print(f"    Lag {lag}: Error - {e}")

    RESULTS['part_b']['granger_causality'] = gc_results

# ============================================================
# PART C: INVERSION AS WARNING SIGNAL
# ============================================================
print("\n" + "=" * 70)
print("PART C: Inversion as Vol Warning Signal")
print("=" * 70)

# C1: Event study around inversion starts
# Identify inversion start dates (first day slope goes negative after being positive)
df['inverted'] = (df['slope'] < 0).astype(int)
df['inv_start'] = (df['inverted'] == 1) & (df['inverted'].shift(1) == 0)

inv_start_dates = df[df['inv_start']].index
print(f"\n  Inversion start events: {len(inv_start_dates)}")

event_study = {}
windows = [21, 63, 126, 252]  # 1m, 3m, 6m, 12m forward

for w in windows:
    fwd_vols = []
    normal_vols = []

    for date in inv_start_dates:
        loc = df.index.get_loc(date)
        if loc + w < len(df):
            fwd_ret = df['spy_ret'].iloc[loc+1:loc+1+w]
            if len(fwd_ret) >= w * 0.8:
                fwd_vol = float(fwd_ret.std() * np.sqrt(252) * 100)
                fwd_vols.append(fwd_vol)

    # Baseline: average forward vol from all dates
    all_fwd_vols = []
    for i in range(0, len(df) - w, 21):  # sample every 21 days to reduce overlap
        fwd_ret = df['spy_ret'].iloc[i+1:i+1+w]
        if len(fwd_ret) >= w * 0.8:
            all_fwd_vols.append(float(fwd_ret.std() * np.sqrt(252) * 100))

    if fwd_vols and all_fwd_vols:
        inv_mean = np.mean(fwd_vols)
        all_mean = np.mean(all_fwd_vols)
        t, p = stats.ttest_ind(fwd_vols, all_fwd_vols)

        event_study[f'{w}d'] = {
            'n_events': len(fwd_vols),
            'inversion_fwd_vol': float(inv_mean),
            'unconditional_fwd_vol': float(all_mean),
            'ratio': float(inv_mean / all_mean),
            't_stat': float(t),
            'p_value': float(p)
        }

        print(f"\n  Window {w}d after inversion start:")
        print(f"    Inversion avg vol: {inv_mean:.1f}%  (n={len(fwd_vols)})")
        print(f"    Unconditional:     {all_mean:.1f}%  (n={len(all_fwd_vols)})")
        print(f"    Ratio: {inv_mean/all_mean:.2f}x, t={t:.2f}, p={p:.4f}")

RESULTS['part_c'] = {'event_study': event_study}

# C2: Does inversion predict VIX spikes (VIX > 30)?
df['vix_spike'] = (df['VIX'] > 30).astype(int)

# Within N months after inversion: probability of VIX spike
spike_analysis = {}
for w in [63, 126, 252]:
    hits = 0
    total = 0
    for date in inv_start_dates:
        loc = df.index.get_loc(date)
        if loc + w < len(df):
            total += 1
            if df['vix_spike'].iloc[loc+1:loc+1+w].sum() > 0:
                hits += 1

    # Unconditional rate
    unc_rate = 0
    unc_total = 0
    for i in range(0, len(df) - w, 63):
        unc_total += 1
        if df['vix_spike'].iloc[i+1:i+1+w].sum() > 0:
            unc_rate += 1

    if total > 0 and unc_total > 0:
        inv_prob = hits / total
        unc_prob = unc_rate / unc_total
        spike_analysis[f'{w}d'] = {
            'n_inversions': total,
            'spike_after_inv': hits,
            'prob_spike_after_inv': float(inv_prob),
            'unconditional_spike_prob': float(unc_prob),
            'ratio': float(inv_prob / unc_prob) if unc_prob > 0 else None
        }

        print(f"\n  VIX>30 within {w}d of inversion:")
        print(f"    After inversion: {hits}/{total} = {inv_prob:.1%}")
        print(f"    Unconditional:   {unc_rate}/{unc_total} = {unc_prob:.1%}")
        print(f"    Ratio: {inv_prob/unc_prob:.2f}x" if unc_prob > 0 else "    Ratio: N/A")

RESULTS['part_c']['vix_spike_prediction'] = spike_analysis

# C3: False positive rate
print("\n  False positive analysis:")
print(f"  Inversions that did NOT lead to VIX>30 within 252d:")
if '252d' in spike_analysis:
    fp = spike_analysis['252d']['n_inversions'] - spike_analysis['252d']['spike_after_inv']
    fpr = fp / spike_analysis['252d']['n_inversions'] if spike_analysis['252d']['n_inversions'] > 0 else 0
    print(f"    {fp}/{spike_analysis['252d']['n_inversions']} = {fpr:.1%} false positive rate")
    RESULTS['part_c']['false_positive_rate_252d'] = float(fpr)

# ============================================================
# PART D: TRADING STRATEGY
# ============================================================
print("\n" + "=" * 70)
print("PART D: Trading Strategy Based on Yield Curve")
print("=" * 70)

# Monthly rebalancing strategy
# Signal: yield curve slope → equity weight
# Steeper = more equity (economy good), Inverted = less equity (recession risk)

# Create monthly signal using LAGGED slope (end of previous month)
monthly_df = pd.DataFrame()
monthly_df['spy_ret'] = df['spy_ret'].resample('ME').sum()  # monthly log returns
monthly_df['slope'] = df['slope'].resample('ME').last()
monthly_df['vix'] = df['VIX'].resample('ME').last()

# CRITICAL: signal.shift(1) — use PREVIOUS month's slope for THIS month's weight
monthly_df['slope_signal'] = monthly_df['slope'].shift(1)
monthly_df['vix_signal'] = monthly_df['vix'].shift(1)

monthly_df = monthly_df.dropna()

# Strategy 1: Slope-based weight
# Weight = clip(slope / 3.0, 0.3, 1.0) — slope of 3% → full equity, 0 → 30% equity
monthly_df['w_slope'] = monthly_df['slope_signal'].apply(
    lambda x: np.clip(x / 3.0, 0.3, 1.0)
)

# Strategy 2: Slope + VIX combo
# Start with 12/VIX, reduce if curve is inverted
monthly_df['w_12vix'] = 12.0 / monthly_df['vix_signal']
monthly_df['w_12vix'] = monthly_df['w_12vix'].clip(0.3, 1.0)

# Combo: if inverted, reduce 12/VIX weight by 30%
monthly_df['w_combo'] = monthly_df['w_12vix'].copy()
inv_mask = monthly_df['slope_signal'] < 0
monthly_df.loc[inv_mask, 'w_combo'] = monthly_df.loc[inv_mask, 'w_12vix'] * 0.7

# Strategy 3: Binary — full equity unless inverted
monthly_df['w_binary'] = 1.0
monthly_df.loc[monthly_df['slope_signal'] < 0, 'w_binary'] = 0.5

# Baselines
monthly_df['w_bh'] = 1.0
monthly_df['w_5050'] = 0.5

# Transaction costs: 10bps round-trip (5bps each leg)
TX_COST = 0.0010  # 10bps

strategies = {
    'slope_vt': 'w_slope',
    'slope_vix_combo': 'w_combo',
    'binary_inversion': 'w_binary',
    'bh_spy': 'w_bh',
    'bh_5050': 'w_5050',
    '12_vix': 'w_12vix'
}

strat_results = {}
for name, col in strategies.items():
    w = monthly_df[col]
    ret = monthly_df['spy_ret']

    # Portfolio return = w * SPY return + (1-w) * 0 (cash)
    port_ret = w * ret

    # TX cost
    w_chg = w.diff().abs().fillna(0)
    tx = w_chg * TX_COST
    port_ret_net = port_ret - tx

    # Metrics (simple returns for Sharpe)
    port_simple = np.exp(port_ret_net) - 1

    ann_ret = float(port_simple.mean() * 12)
    ann_vol = float(port_simple.std() * np.sqrt(12))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Cumulative for MDD
    cum = (1 + port_simple).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = float(dd.min())

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    strat_results[name] = {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'calmar': float(calmar),
        'avg_weight': float(w.mean()),
        'avg_tx_per_month': float(tx.mean()),
        'n_months': int(len(monthly_df))
    }

    print(f"\n  {name}:")
    print(f"    Sharpe: {sharpe:.3f}, Return: {ann_ret:.1%}, Vol: {ann_vol:.1%}")
    print(f"    MDD: {mdd:.1%}, Calmar: {calmar:.3f}")
    print(f"    Avg weight: {w.mean():.2f}, Avg TX/month: {tx.mean()*10000:.1f}bps")

RESULTS['part_d'] = {'strategies': strat_results}

# Diebold-Mariano test: slope strategies vs 12/VIX
print("\n  Diebold-Mariano tests vs 12/VIX baseline:")
dm_results = {}
baseline_ret = monthly_df['w_12vix'] * monthly_df['spy_ret']
baseline_ret -= monthly_df['w_12vix'].diff().abs().fillna(0) * TX_COST

for name in ['slope_vt', 'slope_vix_combo', 'binary_inversion']:
    col = strategies[name]
    w = monthly_df[col]
    port_ret = w * monthly_df['spy_ret']
    tx = w.diff().abs().fillna(0) * TX_COST
    port_ret_net = port_ret - tx

    # DM test: compare squared errors (using returns as proxy)
    d = (port_ret_net - baseline_ret)

    # Use Sharpe difference approach
    # Loss differential: strategy return - baseline return
    d_mean = d.mean()
    d_std = d.std() / np.sqrt(len(d))
    dm_stat = d_mean / d_std if d_std > 0 else 0
    dm_p = float(2 * stats.t.sf(abs(dm_stat), len(d) - 1))

    dm_results[name] = {
        'dm_stat': float(dm_stat),
        'p_value': dm_p,
        'mean_diff_monthly': float(d_mean),
        'significant': dm_p < 0.05
    }

    print(f"    {name} vs 12/VIX: DM={dm_stat:.3f}, p={dm_p:.4f}, {'SIG' if dm_p < 0.05 else 'NS'}")

RESULTS['part_d']['dm_tests'] = dm_results

# ============================================================
# PART E: SUBSAMPLE ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("PART E: Subsample Robustness")
print("=" * 70)

subsamples = {
    '2006-2010 (GFC)': ('2006-01-01', '2010-12-31'),
    '2011-2015 (Recovery)': ('2011-01-01', '2015-12-31'),
    '2016-2020 (Late cycle + COVID)': ('2016-01-01', '2020-12-31'),
    '2021-2026 (Post-COVID)': ('2021-01-01', '2026-12-31'),
}

subsample_results = {}
for label, (start, end) in subsamples.items():
    sub = df.loc[start:end]
    if len(sub) < 100:
        continue

    tmp = sub[['slope', 'VIX', 'fwd_rv_63d']].dropna()
    if len(tmp) < 50:
        continue

    corr_slope = float(tmp['slope'].corr(tmp['fwd_rv_63d']))
    corr_vix = float(tmp['VIX'].corr(tmp['fwd_rv_63d']))

    # Partial correlation
    X_vix = add_constant(tmp['VIX'])
    resid_s = OLS(tmp['slope'], X_vix).fit().resid
    resid_r = OLS(tmp['fwd_rv_63d'], X_vix).fit().resid
    partial = float(np.corrcoef(resid_s, resid_r)[0, 1])

    subsample_results[label] = {
        'n_obs': int(len(tmp)),
        'corr_slope_rv': corr_slope,
        'corr_vix_rv': corr_vix,
        'partial_corr_slope_rv_ctrl_vix': partial,
        'avg_slope': float(sub['slope'].mean()),
        'pct_inverted': float((sub['slope'] < 0).mean() * 100)
    }

    print(f"\n  {label} (n={len(tmp)}):")
    print(f"    Avg slope: {sub['slope'].mean():.2f}, Inverted: {(sub['slope'] < 0).mean():.1%}")
    print(f"    Corr(slope, fwd_rv_63d): {corr_slope:.3f}")
    print(f"    Corr(VIX, fwd_rv_63d):   {corr_vix:.3f}")
    print(f"    Partial corr (ctrl VIX):  {partial:.3f}")

RESULTS['part_e'] = {'subsamples': subsample_results}

# ============================================================
# SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Determine significance of key findings
key_findings = []

# Check if slope has incremental predictive power
for h in ['21d', '63d', '126d', '252d']:
    if h in regression_results:
        r = regression_results[h]['slope_plus_vix']
        if abs(r['slope_t']) > 3.0:
            key_findings.append(f"Slope significant at {h} horizon (t={r['slope_t']:.2f}) controlling for VIX")
        elif abs(r['slope_t']) > 1.96:
            key_findings.append(f"Slope marginally significant at {h} (t={r['slope_t']:.2f}) — fails Harvey threshold")

# Check trading strategy
best_slope_strat = max(['slope_vt', 'slope_vix_combo', 'binary_inversion'],
                       key=lambda x: strat_results[x]['sharpe'])
slope_sharpe = strat_results[best_slope_strat]['sharpe']
vix_sharpe = strat_results['12_vix']['sharpe']

if slope_sharpe > vix_sharpe:
    key_findings.append(f"Best slope strategy ({best_slope_strat}, Sharpe={slope_sharpe:.3f}) beats 12/VIX ({vix_sharpe:.3f})")
else:
    key_findings.append(f"No slope strategy beats 12/VIX. Best: {best_slope_strat} ({slope_sharpe:.3f}) vs 12/VIX ({vix_sharpe:.3f})")

# Overall verdict
overall_null = True
for h in ['63d', '126d', '252d']:
    if h in regression_results:
        if abs(regression_results[h]['slope_plus_vix']['slope_t']) > 3.0:
            overall_null = False

if overall_null:
    verdict = "NULL — Yield curve slope does NOT add incremental information beyond VIX for equity vol prediction"
else:
    verdict = "POSITIVE — Yield curve slope adds information beyond VIX at longer horizons"

key_findings.append(f"VERDICT: {verdict}")

RESULTS['summary'] = {
    'key_findings': key_findings,
    'verdict': verdict,
    'overall_null': overall_null
}

for f in key_findings:
    print(f"  • {f}")

# ============================================================
# SAVE RESULTS
# ============================================================
RESULTS['metadata'] = {
    'experiment_id': 'K749',
    'title': 'Yield Curve Slope and Equity Volatility',
    'data_source': 'yfinance (^TNX, ^IRX, SPY, ^VIX)',
    'period': f"{df.index[0].date()} to {df.index[-1].date()}",
    'n_obs_daily': int(len(df)),
    'method': 'Predictive regression, partial correlation, event study, trading strategy',
    'proposer': 'Claude',
    'executor': 'Claude',
    'references': [
        'Estrella & Hardouvelis (1991) JPE',
        'Harvey (1988) JFE',
        'Adrian et al. (2019) AER',
        'Bauer & Mertens (2018) FRBSF'
    ],
    'timestamp': datetime.now().isoformat()
}

output_path = OUTPUT_DIR / 'k749_yield_curve_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print("\nDone.")
