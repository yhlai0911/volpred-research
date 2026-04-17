"""
K761v2: Taiwan Yield Curve and 0050.TW Volatility Prediction — RERUN with clean_tw50_data
============================================================================================

This is a rerun of K761 using the clean_tw50_data utility to fix the
0050.TW stock split artifact (pre-2014 prices ~4x too high in yfinance).

Original K761 conclusion: partial r=0.117 at 126d horizon (passes Harvey t>3).
Key question: Does partial r=0.117 at 126d survive with clean data?

Data: yfinance (0050.TW, ^VIX, ^TNX, ^IRX) 2005-2026
Author: [提出: User (rerun request), 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import sys
import warnings
from datetime import datetime
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from pathlib import Path

warnings.filterwarnings('ignore')

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))
from volpred.utils import clean_tw50_data

RESULTS = {}
OUTPUT_DIR = Path(__file__).parent

# ============================================================
# DATA COLLECTION
# ============================================================
print("=" * 70)
print("K761v2: Taiwan Yield Curve — Rerun with clean_tw50_data")
print("=" * 70)

start_date = '2005-01-01'
end_date = '2026-03-31'

print("\n[1] Downloading data (separate calendars)...")
raw = {}
tickers_list = [('0050', '0050.TW'), ('VIX', '^VIX'),
                ('TNX', '^TNX'), ('IRX', '^IRX')]

for name, ticker in tickers_list:
    for attempt in range(3):
        try:
            df = yf.download(ticker, start=start_date, end=end_date,
                             progress=False, timeout=30)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            series = df['Close'].dropna()
            if len(series) == 0:
                raise ValueError(f"Empty data for {ticker}")
            raw[name] = series.rename(name)
            print(f"  {name}: {len(raw[name])} obs, "
                  f"{raw[name].index[0].date()} to {raw[name].index[-1].date()}")
            break
        except Exception as e:
            if attempt < 2:
                import time
                print(f"  {name}: attempt {attempt+1} failed ({e}), retrying...")
                time.sleep(2)
            else:
                raise RuntimeError(f"Failed to download {ticker} after 3 attempts: {e}")

assert all(k in raw for k in ['0050', 'VIX', 'TNX', 'IRX']), "Missing data!"

# ── CLEAN 0050.TW DATA (K761v2 FIX) ──
print("\n  Applying clean_tw50_data to 0050.TW...")
raw_0050_before = raw['0050'].copy()
clean_prices_0050, clean_returns_0050 = clean_tw50_data(raw['0050'])
raw['0050'] = clean_prices_0050

n_changed = (raw_0050_before != clean_prices_0050).sum()
print(f"  clean_tw50_data: {n_changed} prices changed")
if n_changed > 0:
    bp = pd.Timestamp("2014-01-02")
    if bp in raw_0050_before.index:
        pre_date = raw_0050_before.index[raw_0050_before.index < bp][-1]
        print(f"  Before: {pre_date.date()}={raw_0050_before.loc[pre_date]:.2f}, "
              f"2014-01-02={raw_0050_before.loc[bp]:.2f}")
        print(f"  After:  {pre_date.date()}={clean_prices_0050.loc[pre_date]:.2f}, "
              f"2014-01-02={clean_prices_0050.loc[bp]:.2f}")

# ============================================================
# BUILD TW-CALENDAR-BASED SERIES
# ============================================================
print("\n[2] Building Taiwan-calendar aligned series...")

# Use clean returns (from clean_tw50_data)
ret_0050 = clean_prices_0050.pct_change().dropna()
tw_dates = sorted(ret_0050.index)
print(f"  TW trading days: {len(tw_dates)}")

vix_raw = raw['VIX'].sort_index()
tnx_raw = raw['TNX'].sort_index()
irx_raw = raw['IRX'].sort_index()


def asof_lookup(us_series, tw_dates_list):
    """For each TW date, get the last US value strictly before that date."""
    result = pd.Series(index=pd.DatetimeIndex(tw_dates_list), dtype=float)
    for d in tw_dates_list:
        mask = us_series.index < d
        if mask.any():
            result.loc[d] = us_series.loc[mask].iloc[-1]
        else:
            result.loc[d] = np.nan
    return result.dropna()


vix_tw = asof_lookup(vix_raw, tw_dates)
tnx_tw = asof_lookup(tnx_raw, tw_dates)
irx_tw = asof_lookup(irx_raw, tw_dates)

slope_tw = tnx_tw - irx_tw
slope_tw.name = 'slope'

print(f"  VIX-for-TW: {len(vix_tw)} days")
print(f"  Slope-for-TW: {len(slope_tw)} days")

# Realized volatility
rv_0050_21d = ret_0050.rolling(21, min_periods=15).std() * np.sqrt(252) * 100
rv_0050_63d = ret_0050.rolling(63, min_periods=45).std() * np.sqrt(252) * 100

# Forward RV
fwd_rv_21 = ret_0050.iloc[::-1].rolling(21, min_periods=15).std().iloc[::-1] * np.sqrt(252) * 100
fwd_rv_21 = fwd_rv_21.shift(-1)

fwd_rv_63 = ret_0050.iloc[::-1].rolling(63, min_periods=45).std().iloc[::-1] * np.sqrt(252) * 100
fwd_rv_63 = fwd_rv_63.shift(-1)

fwd_rv_126 = ret_0050.iloc[::-1].rolling(126, min_periods=90).std().iloc[::-1] * np.sqrt(252) * 100
fwd_rv_126 = fwd_rv_126.shift(-1)

# ============================================================
# PART A: DESCRIPTIVE STATS
# ============================================================
print("\n" + "=" * 70)
print("PART A: Yield Curve Slope (as seen from Taiwan)")
print("=" * 70)

slope_clean = slope_tw.dropna()
desc = {
    'mean': float(slope_clean.mean()),
    'std': float(slope_clean.std()),
    'n_obs': int(len(slope_clean))
}
print(f"\nSlope descriptive: mean={desc['mean']:.4f}, std={desc['std']:.4f}, n={desc['n_obs']}")

common_idx = vix_tw.dropna().index.intersection(slope_clean.index)
corr_vix_slope = np.corrcoef(vix_tw.loc[common_idx], slope_clean.loc[common_idx])[0, 1]
print(f"Correlation VIX vs Slope (TW calendar): {corr_vix_slope:.4f}")

RESULTS['part_a'] = {
    'slope_descriptive': desc,
    'corr_vix_slope_tw': float(corr_vix_slope)
}

# ============================================================
# PART B: PREDICTIVE POWER FOR TAIWAN VOL
# ============================================================
print("\n" + "=" * 70)
print("PART B: Does US Yield Curve Predict Taiwan 0050.TW Volatility?")
print("=" * 70)

horizons = [
    ('21d', fwd_rv_21),
    ('63d', fwd_rv_63),
    ('126d', fwd_rv_126)
]

pred_results = {}

for h_name, fwd_rv in horizons:
    print(f"\n--- Horizon: {h_name} ---")

    idx = (fwd_rv.dropna().index
           .intersection(slope_tw.dropna().index)
           .intersection(vix_tw.dropna().index)
           .intersection(rv_0050_21d.dropna().index))

    reg_df = pd.DataFrame({
        'fwd_rv': fwd_rv.loc[idx],
        'slope': slope_tw.loc[idx],
        'vix': vix_tw.loc[idx],
        'own_rv': rv_0050_21d.loc[idx]
    }).dropna()

    n = len(reg_df)
    print(f"  Sample: {n} obs, {reg_df.index[0].date()} to {reg_df.index[-1].date()}")

    # (1) Slope alone
    X1 = add_constant(reg_df['slope'])
    m1 = OLS(reg_df['fwd_rv'], X1).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
    print(f"\n  Slope → fwd RV {h_name}:")
    print(f"    β_slope = {m1.params.iloc[1]:.4f} (t={m1.tvalues.iloc[1]:.2f}), R²={m1.rsquared:.4f}")

    # (2) VIX alone
    X2 = add_constant(reg_df['vix'])
    m2 = OLS(reg_df['fwd_rv'], X2).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
    print(f"  VIX → fwd RV {h_name}:")
    print(f"    β_VIX = {m2.params.iloc[1]:.4f} (t={m2.tvalues.iloc[1]:.2f}), R²={m2.rsquared:.4f}")

    # (3) Slope + VIX
    X3 = add_constant(reg_df[['slope', 'vix']])
    m3 = OLS(reg_df['fwd_rv'], X3).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
    print(f"  Slope + VIX → fwd RV {h_name}:")
    print(f"    β_slope = {m3.params.iloc[1]:.4f} (t={m3.tvalues.iloc[1]:.2f})")
    print(f"    β_VIX = {m3.params.iloc[2]:.4f} (t={m3.tvalues.iloc[2]:.2f})")
    print(f"    R²={m3.rsquared:.4f}, ΔR² from VIX-only = {m3.rsquared - m2.rsquared:.4f}")

    # (4) Partial correlation
    Xv = add_constant(reg_df['vix'])
    resid_slope = OLS(reg_df['slope'], Xv).fit().resid
    resid_rv = OLS(reg_df['fwd_rv'], Xv).fit().resid
    partial_r = np.corrcoef(resid_slope, resid_rv)[0, 1]
    partial_t = partial_r * np.sqrt((n - 3) / (1 - partial_r**2))
    print(f"\n  Partial correlation (slope|VIX → fwd_rv|VIX):")
    print(f"    partial_r = {partial_r:.4f}, t = {partial_t:.2f}")
    print(f"    Harvey (2016): {'PASSES' if abs(partial_t) > 3.0 else 'FAILS'} t>3.0")

    # (5) Kitchen-sink
    X4 = add_constant(reg_df[['slope', 'vix', 'own_rv']])
    m4 = OLS(reg_df['fwd_rv'], X4).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
    print(f"\n  Kitchen-sink: β_slope t={m4.tvalues.iloc[1]:.2f}, "
          f"β_VIX t={m4.tvalues.iloc[2]:.2f}, β_own_RV t={m4.tvalues.iloc[3]:.2f}, "
          f"R²={m4.rsquared:.4f}")

    pred_results[h_name] = {
        'n': int(n),
        'slope_only': {
            'beta': float(m1.params.iloc[1]),
            't_stat': float(m1.tvalues.iloc[1]),
            'r_squared': float(m1.rsquared)
        },
        'vix_only': {
            'beta': float(m2.params.iloc[1]),
            't_stat': float(m2.tvalues.iloc[1]),
            'r_squared': float(m2.rsquared)
        },
        'slope_plus_vix': {
            'beta_slope': float(m3.params.iloc[1]),
            't_slope': float(m3.tvalues.iloc[1]),
            'beta_vix': float(m3.params.iloc[2]),
            't_vix': float(m3.tvalues.iloc[2]),
            'r_squared': float(m3.rsquared),
            'delta_r2_vs_vix': float(m3.rsquared - m2.rsquared)
        },
        'partial_correlation': {
            'partial_r': float(partial_r),
            't_stat': float(partial_t),
            'passes_harvey_3': bool(abs(partial_t) > 3.0)
        },
        'kitchen_sink': {
            'beta_slope': float(m4.params.iloc[1]),
            't_slope': float(m4.tvalues.iloc[1]),
            'r_squared': float(m4.rsquared)
        }
    }

RESULTS['part_b'] = pred_results

# ============================================================
# PART B2: DIEBOLD-MARIANO TEST
# ============================================================
print("\n" + "=" * 70)
print("PART B2: Diebold-Mariano Test (Slope adds value to VIX?)")
print("=" * 70)

dm_results = {}
for h_name, fwd_rv in horizons:
    idx = (fwd_rv.dropna().index
           .intersection(slope_tw.dropna().index)
           .intersection(vix_tw.dropna().index)
           .intersection(rv_0050_21d.dropna().index))

    reg_df = pd.DataFrame({
        'fwd_rv': fwd_rv.loc[idx],
        'slope': slope_tw.loc[idx],
        'vix': vix_tw.loc[idx],
        'own_rv': rv_0050_21d.loc[idx]
    }).dropna()

    X_vix = add_constant(reg_df['vix'])
    m_vix = OLS(reg_df['fwd_rv'], X_vix).fit()
    e1 = m_vix.resid

    X_both = add_constant(reg_df[['vix', 'slope']])
    m_both = OLS(reg_df['fwd_rv'], X_both).fit()
    e2 = m_both.resid

    d = e1**2 - e2**2
    d_bar = d.mean()
    n_dm = len(d)
    lag_dm = int(np.ceil(n_dm**(1/3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag_dm + 1):
        gamma_k = np.cov(d.iloc[k:].values, d.iloc[:-k].values)[0, 1]
        gamma_sum += 2 * (1 - k / (lag_dm + 1)) * gamma_k
    var_d = gamma_0 + gamma_sum
    se_d = np.sqrt(var_d / n_dm)
    dm_stat = d_bar / se_d if se_d > 0 else 0
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    print(f"\n  {h_name}: DM stat = {dm_stat:.3f}, p = {dm_pval:.4f}")
    print(f"    Conclusion: {'Slope ADDS value' if dm_pval < 0.05 and d_bar > 0 else 'Slope does NOT add value'}")

    dm_results[h_name] = {
        'dm_stat': float(dm_stat),
        'p_value': float(dm_pval),
        'd_bar': float(d_bar),
        'slope_adds_value': bool(dm_pval < 0.05 and d_bar > 0)
    }

RESULTS['part_b2_dm_test'] = dm_results

# ============================================================
# PART C: TRADING STRATEGY
# ============================================================
print("\n" + "=" * 70)
print("PART C: Trading Strategy — Can Slope Improve Taiwan VT?")
print("=" * 70)

strat_idx = (ret_0050.index
             .intersection(vix_tw.index)
             .intersection(slope_tw.index))
strat_idx = sorted(strat_idx)

strat_df = pd.DataFrame({
    'ret_0050': ret_0050.loc[strat_idx],
    'vix': vix_tw.loc[strat_idx],
    'slope': slope_tw.loc[strat_idx]
}, index=strat_idx).dropna()

print(f"\nStrategy period: {strat_df.index[0].date()} to {strat_df.index[-1].date()}")
print(f"  Observations: {len(strat_df)}")

TX_COST = 0.001

# Buy & Hold
strat_df['bh_ret'] = strat_df['ret_0050']

# Taiwan VT (8.63/VIX)
target_vol = 8.63
strat_df['vt_weight'] = (target_vol / strat_df['vix']).clip(0, 1)
strat_df['vt_weight_lag'] = strat_df['vt_weight'].shift(1)  # CRITICAL: signal.shift(1)
strat_df['vt_tx'] = strat_df['vt_weight_lag'].diff().abs() * TX_COST
strat_df['vt_ret'] = strat_df['vt_weight_lag'] * strat_df['ret_0050'] - strat_df['vt_tx']

# Slope Guard
strat_df['slope_guard'] = np.where(strat_df['slope'] < 0, 0.5, 1.0)
strat_df['slope_guard_lag'] = strat_df['slope_guard'].shift(1)  # CRITICAL
strat_df['sg_weight'] = strat_df['vt_weight_lag'] * strat_df['slope_guard_lag']
strat_df['sg_tx'] = strat_df['sg_weight'].diff().abs() * TX_COST
strat_df['sg_ret'] = strat_df['sg_weight'] * strat_df['ret_0050'] - strat_df['sg_tx']

# Continuous slope
slope_exp_mean = strat_df['slope'].expanding(min_periods=252).mean()
slope_exp_std = strat_df['slope'].expanding(min_periods=252).std()
strat_df['slope_z'] = (strat_df['slope'] - slope_exp_mean) / slope_exp_std
strat_df['slope_mult'] = (0.5 + 0.25 * strat_df['slope_z']).clip(0.3, 1.0)
strat_df['slope_mult_lag'] = strat_df['slope_mult'].shift(1)  # CRITICAL
strat_df['cont_weight'] = strat_df['vt_weight_lag'] * strat_df['slope_mult_lag']
strat_df['cont_tx'] = strat_df['cont_weight'].diff().abs() * TX_COST
strat_df['cont_ret'] = strat_df['cont_weight'] * strat_df['ret_0050'] - strat_df['cont_tx']

strat_clean = strat_df.dropna(subset=['vt_ret', 'sg_ret', 'cont_ret']).copy()
print(f"  Strategy analysis: {len(strat_clean)} days after warmup")


def compute_metrics(returns, name):
    r = returns.dropna()
    n_years = len(r) / 252
    cum = (1 + r).cumprod()
    total_ret = cum.iloc[-1] - 1
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    rolling_max = cum.cummax()
    mdd = (cum / rolling_max - 1).min()
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0
    print(f"\n  {name}: Ret={ann_ret*100:.2f}%, Vol={ann_vol*100:.2f}%, "
          f"Sharpe={sharpe:.3f}, MDD={mdd*100:.1f}%")
    return {
        'ann_return': float(ann_ret), 'ann_vol': float(ann_vol),
        'sharpe': float(sharpe), 'sortino': float(sortino),
        'max_drawdown': float(mdd), 'total_return': float(total_ret)
    }


print(f"\n--- Full Period Performance ---")
metrics = {}
metrics['buy_hold_0050'] = compute_metrics(strat_clean['bh_ret'], 'Buy & Hold 0050')
metrics['taiwan_vt_863'] = compute_metrics(strat_clean['vt_ret'], 'Taiwan VT (8.63/VIX)')
metrics['slope_guard'] = compute_metrics(strat_clean['sg_ret'], 'Slope Guard')
metrics['continuous_slope'] = compute_metrics(strat_clean['cont_ret'], 'Continuous Slope Adj')

RESULTS['part_c'] = {'full_period': metrics}

# ============================================================
# COMPARISON WITH ORIGINAL K761
# ============================================================
print("\n" + "=" * 70)
print("COMPARISON WITH ORIGINAL K761")
print("=" * 70)

orig_path = project_root / "experiments" / "k761_taiwan_yield_curve_results.json"
try:
    with open(orig_path) as f:
        orig = json.load(f)

    print(f"\nPartial correlation comparison (slope|VIX → fwd_rv|VIX):")
    print(f"  {'Horizon':<10} {'Original':<20} {'V2 (clean)':<20} {'Change':<15}")
    print(f"  {'-'*65}")

    for h in ['21d', '63d', '126d']:
        orig_pr = orig.get('part_b', {}).get(h, {}).get('partial_correlation', {})
        new_pr = pred_results.get(h, {}).get('partial_correlation', {})
        if orig_pr and new_pr:
            o_r = orig_pr['partial_r']
            n_r = new_pr['partial_r']
            o_t = orig_pr['t_stat']
            n_t = new_pr['t_stat']
            print(f"  {h:<10} r={o_r:.4f} (t={o_t:.2f}) r={n_r:.4f} (t={n_t:.2f}) Δr={n_r-o_r:+.4f}")

    # Key check: 126d partial r
    orig_126_r = orig.get('part_b', {}).get('126d', {}).get('partial_correlation', {}).get('partial_r', None)
    new_126_r = pred_results.get('126d', {}).get('partial_correlation', {}).get('partial_r', None)
    new_126_t = pred_results.get('126d', {}).get('partial_correlation', {}).get('t_stat', None)
    new_126_passes = pred_results.get('126d', {}).get('partial_correlation', {}).get('passes_harvey_3', False)

    if orig_126_r is not None and new_126_r is not None:
        print(f"\n  KEY CHECK: 126d partial r")
        print(f"    Original: {orig_126_r:.4f}")
        print(f"    V2 (clean): {new_126_r:.4f}")
        print(f"    Change: {new_126_r - orig_126_r:+.4f}")
        print(f"    Harvey t>3.0: {'PASSES' if new_126_passes else 'FAILS'} (t={new_126_t:.2f})")

except Exception as e:
    print(f"  Could not load original results: {e}")
    orig_126_r = None
    new_126_r = None

# ============================================================
# CONCLUSION
# ============================================================
any_slope_sig = any(
    pred_results.get(h, {}).get('partial_correlation', {}).get('passes_harvey_3', False)
    for h in ['21d', '63d', '126d']
)

slope_guard_sharpe = metrics.get('slope_guard', {}).get('sharpe', 0)
vt_sharpe = metrics.get('taiwan_vt_863', {}).get('sharpe', 0)

conclusion = ""
if any_slope_sig:
    sig_h = [h for h in ['21d', '63d', '126d']
             if pred_results.get(h, {}).get('partial_correlation', {}).get('passes_harvey_3', False)]
    conclusion += f"PARTIAL: Slope significant at {', '.join(sig_h)}. "
else:
    conclusion += "NULL: Slope fails Harvey t>3.0 at all horizons. "

if slope_guard_sharpe <= vt_sharpe:
    conclusion += f"Trading: slope guard ({slope_guard_sharpe:.3f}) <= VT ({vt_sharpe:.3f}). "
else:
    conclusion += f"Trading: slope guard ({slope_guard_sharpe:.3f}) > VT ({vt_sharpe:.3f}). "

if orig_126_r is not None and new_126_r is not None:
    if abs(new_126_r - orig_126_r) < 0.02:
        conclusion += "CONCLUSION UNCHANGED vs original K761."
    else:
        conclusion += f"CONCLUSION CHANGED: 126d partial r shifted {new_126_r - orig_126_r:+.4f}."

print(f"\n{'='*70}")
print("K761v2 CONCLUSION")
print("="*70)
print(f"\n{conclusion}")

RESULTS['conclusion'] = {
    'any_partial_r_passes_harvey': any_slope_sig,
    'slope_guard_sharpe': float(slope_guard_sharpe),
    'vt_sharpe': float(vt_sharpe),
    'verdict': conclusion
}

# ============================================================
# SAVE
# ============================================================
RESULTS['metadata'] = {
    'experiment': 'K761v2',
    'title': 'Taiwan Yield Curve — Rerun with clean_tw50_data',
    'date': datetime.now().isoformat(),
    'data_source': 'yfinance (0050.TW, ^VIX, ^TNX, ^IRX)',
    'period': f"{strat_df.index[0].date()} to {strat_df.index[-1].date()}",
    'n_obs': int(len(strat_df)),
    'fix_applied': 'clean_tw50_data — fixes 2014-01-02 split breakpoint',
    'methodology': 'TW calendar primary, VIX/slope asof-lookup, signal.shift(1), TX 10bps',
    'attribution': '[提出: User (rerun request), 執行: Claude]'
}

output_path = OUTPUT_DIR / 'k761v2_taiwan_yield_curve_results.json'
with open(output_path, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
print("K761v2 COMPLETE")
