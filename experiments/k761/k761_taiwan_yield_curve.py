"""
K761: Taiwan Yield Curve and 0050.TW Volatility Prediction
Does the US Bond Market Predict Taiwan Stock Fear?

[提出: Claude (from research_program), 執行: Claude]

Background:
K749 tested US yield curve slope → SPY volatility: NULL for short-term (slope
subsumed by VIX), interesting at 126d+ horizon (partial r=0.048-0.081, t>3).
K739b showed US VIX works for Taiwan vol prediction (R²=0.039).

Now test: does US yield curve slope add information for TAIWAN equity volatility
beyond what VIX already captures?

Taiwan specifics:
- Taiwan central bank policy is relatively stable (rates low, narrow band)
- US yield curve may matter via capital flow channel and USD/TWD dynamics
- Taiwan is a small open economy → external conditions dominate

Data sources:
- ^TNX (10Y Treasury yield) from yfinance
- ^IRX (13-week T-bill rate) from yfinance
- 0050.TW (Taiwan equity ETF) from yfinance
- ^VIX from yfinance
- Period: 2006-01-01 to 2026-03-30

Methodology:
- TW calendar primary (K739b methodology) — no union calendar
- VIX asof-lookup for TW dates (prior US close)
- Yield slope asof-lookup for TW dates (same approach as VIX)
- signal.shift(1) for all trading signals
- TX cost: 10 bps per one-way trade

References:
- K749: US yield curve → SPY vol (NULL short-term, interesting 126d+)
- K739b: Taiwan VT cross-validation (holiday-bug fixed)
- K636: Taiwan amplification 4.6x
- K82/K88: Taiwan VT guide (8.63/VIX target)
- Estrella & Hardouvelis (1991) "The Term Structure as a Predictor"
- Adrian et al. (2019) "Vulnerable Growth" AER
- Harvey (1988) "The Real Term Structure and Consumption Growth"
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
from pathlib import Path

warnings.filterwarnings('ignore')

RESULTS = {}
OUTPUT_DIR = Path(__file__).parent

# ============================================================
# DATA COLLECTION — SEPARATE CALENDARS (K739b methodology)
# ============================================================
print("=" * 70)
print("K761: Taiwan Yield Curve and 0050.TW Volatility Prediction")
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

# ============================================================
# BUILD TW-CALENDAR-BASED SERIES
# ============================================================
print("\n[2] Building Taiwan-calendar aligned series...")

# 0050 returns on TW calendar only (no ffill!)
ret_0050 = raw['0050'].pct_change().dropna()
tw_dates = sorted(ret_0050.index)
print(f"  TW trading days: {len(tw_dates)}")

# For each TW trading day, find most recent US VIX close STRICTLY BEFORE that day
# (US closes at ~04:00-05:00 TW time next day)
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

# Yield curve slope on TW calendar
slope_tw = tnx_tw - irx_tw  # In percentage points
slope_tw.name = 'slope'

print(f"  VIX-for-TW: {len(vix_tw)} days")
print(f"  Slope-for-TW: {len(slope_tw)} days")

# Realized volatility on TW calendar (21 TW trading days)
rv_0050_21d = ret_0050.rolling(21, min_periods=15).std() * np.sqrt(252) * 100
rv_0050_63d = ret_0050.rolling(63, min_periods=45).std() * np.sqrt(252) * 100

# Forward RV (next 21/63/126 TW trading days from t+1)
fwd_rv_21 = ret_0050.iloc[::-1].rolling(21, min_periods=15).std().iloc[::-1] * np.sqrt(252) * 100
fwd_rv_21 = fwd_rv_21.shift(-1)  # Start from t+1

fwd_rv_63 = ret_0050.iloc[::-1].rolling(63, min_periods=45).std().iloc[::-1] * np.sqrt(252) * 100
fwd_rv_63 = fwd_rv_63.shift(-1)

fwd_rv_126 = ret_0050.iloc[::-1].rolling(126, min_periods=90).std().iloc[::-1] * np.sqrt(252) * 100
fwd_rv_126 = fwd_rv_126.shift(-1)

# ============================================================
# PART A: YIELD CURVE SLOPE ON TW CALENDAR — DESCRIPTIVE STATS
# ============================================================
print("\n" + "=" * 70)
print("PART A: Yield Curve Slope (as seen from Taiwan)")
print("=" * 70)

slope_clean = slope_tw.dropna()
desc = {
    'mean': float(slope_clean.mean()),
    'std': float(slope_clean.std()),
    'median': float(slope_clean.median()),
    'min': float(slope_clean.min()),
    'max': float(slope_clean.max()),
    'skewness': float(slope_clean.skew()),
    'kurtosis': float(slope_clean.kurtosis()),
    'pct_negative': float((slope_clean < 0).mean() * 100),
    'n_obs': int(len(slope_clean))
}
print(f"\nSlope (10Y-3M, as-of TW dates) descriptive stats:")
for k, v in desc.items():
    if isinstance(v, float):
        print(f"  {k}: {v:.4f}")
    else:
        print(f"  {k}: {v}")

# Autocorrelation of slope (extremely persistent?)
ac1 = slope_clean.autocorr(1)
ac5 = slope_clean.autocorr(5)
ac21 = slope_clean.autocorr(21)
print(f"\n  Autocorrelation: lag1={ac1:.4f}, lag5={ac5:.4f}, lag21={ac21:.4f}")

# Inversion episodes on TW calendar
inv_dates_tw = slope_clean[slope_clean < 0].index
if len(inv_dates_tw) > 0:
    episodes = []
    ep_start = inv_dates_tw[0]
    ep_prev = inv_dates_tw[0]
    for d in inv_dates_tw[1:]:
        if (d - ep_prev).days > 5:
            episodes.append({
                'start': str(ep_start.date()),
                'end': str(ep_prev.date()),
                'trading_days': int(len(slope_clean[(slope_clean.index >= ep_start) &
                                                     (slope_clean.index <= ep_prev) &
                                                     (slope_clean < 0)]))
            })
            ep_start = d
        ep_prev = d
    episodes.append({
        'start': str(ep_start.date()),
        'end': str(ep_prev.date()),
        'trading_days': int(len(slope_clean[(slope_clean.index >= ep_start) &
                                             (slope_clean.index <= ep_prev) &
                                             (slope_clean < 0)]))
    })
    print(f"\nInversion episodes (slope < 0, TW calendar): {len(episodes)}")
    for ep in episodes:
        print(f"  {ep['start']} to {ep['end']} ({ep['trading_days']} TW trading days)")
else:
    episodes = []
    print("\nNo inversion episodes found.")

# VIX vs slope correlation (both on TW calendar)
common_idx = vix_tw.dropna().index.intersection(slope_clean.index)
corr_vix_slope = np.corrcoef(vix_tw.loc[common_idx], slope_clean.loc[common_idx])[0, 1]
print(f"\nCorrelation VIX vs Slope (TW calendar): {corr_vix_slope:.4f}")
print(f"  (K749 US calendar: counter-intuitive — steep curve → higher VIX)")

# Slope by VIX regime
vix_common = vix_tw.loc[common_idx]
slope_common = slope_clean.loc[common_idx]
print(f"\n  Slope by VIX regime:")
for lo, hi, label in [(0, 15, 'Low'), (15, 20, 'Normal'), (20, 25, 'Elevated'),
                       (25, 35, 'High'), (35, 100, 'Crisis')]:
    mask = (vix_common >= lo) & (vix_common < hi)
    if mask.sum() > 0:
        print(f"    VIX {lo}-{hi} ({label}): slope mean={slope_common[mask].mean():.3f}, "
              f"n={mask.sum()}")

RESULTS['part_a'] = {
    'slope_descriptive': desc,
    'autocorrelation': {'lag1': float(ac1), 'lag5': float(ac5), 'lag21': float(ac21)},
    'inversion_episodes': episodes,
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

    # Align all series by date
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

    # (1) Slope alone → fwd RV
    X1 = add_constant(reg_df['slope'])
    m1 = OLS(reg_df['fwd_rv'], X1).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
    print(f"\n  Slope → fwd RV {h_name}:")
    print(f"    β_slope = {m1.params.iloc[1]:.4f} (t={m1.tvalues.iloc[1]:.2f}, p={m1.pvalues.iloc[1]:.4f})")
    print(f"    R² = {m1.rsquared:.4f}")

    # (2) VIX alone → fwd RV
    X2 = add_constant(reg_df['vix'])
    m2 = OLS(reg_df['fwd_rv'], X2).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
    print(f"\n  VIX → fwd RV {h_name}:")
    print(f"    β_VIX = {m2.params.iloc[1]:.4f} (t={m2.tvalues.iloc[1]:.2f}, p={m2.pvalues.iloc[1]:.4f})")
    print(f"    R² = {m2.rsquared:.4f}")

    # (3) Slope + VIX → fwd RV
    X3 = add_constant(reg_df[['slope', 'vix']])
    m3 = OLS(reg_df['fwd_rv'], X3).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
    print(f"\n  Slope + VIX → fwd RV {h_name}:")
    print(f"    β_slope = {m3.params.iloc[1]:.4f} (t={m3.tvalues.iloc[1]:.2f}, p={m3.pvalues.iloc[1]:.4f})")
    print(f"    β_VIX = {m3.params.iloc[2]:.4f} (t={m3.tvalues.iloc[2]:.2f}, p={m3.pvalues.iloc[2]:.4f})")
    print(f"    R² = {m3.rsquared:.4f}, ΔR² from VIX-only = {m3.rsquared - m2.rsquared:.4f}")

    # (4) Partial correlation of slope with fwd RV, controlling VIX
    # Residualize both slope and fwd_rv on VIX, then correlate residuals
    Xv = add_constant(reg_df['vix'])
    resid_slope = OLS(reg_df['slope'], Xv).fit().resid
    resid_rv = OLS(reg_df['fwd_rv'], Xv).fit().resid
    partial_r = np.corrcoef(resid_slope, resid_rv)[0, 1]
    partial_t = partial_r * np.sqrt((n - 3) / (1 - partial_r**2))
    print(f"\n  Partial correlation (slope|VIX → fwd_rv|VIX):")
    print(f"    partial_r = {partial_r:.4f}, t = {partial_t:.2f}")
    print(f"    Harvey (2016) threshold: t > 3.0")

    # (5) Kitchen-sink: Slope + VIX + own RV → fwd RV
    X4 = add_constant(reg_df[['slope', 'vix', 'own_rv']])
    m4 = OLS(reg_df['fwd_rv'], X4).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
    print(f"\n  Kitchen-sink (Slope + VIX + own_RV) → fwd RV {h_name}:")
    print(f"    β_slope = {m4.params.iloc[1]:.4f} (t={m4.tvalues.iloc[1]:.2f})")
    print(f"    β_VIX = {m4.params.iloc[2]:.4f} (t={m4.tvalues.iloc[2]:.2f})")
    print(f"    β_own_RV = {m4.params.iloc[3]:.4f} (t={m4.tvalues.iloc[3]:.2f})")
    print(f"    R² = {m4.rsquared:.4f}")

    pred_results[h_name] = {
        'n': int(n),
        'slope_only': {
            'beta': float(m1.params.iloc[1]),
            't_stat': float(m1.tvalues.iloc[1]),
            'p_value': float(m1.pvalues.iloc[1]),
            'r_squared': float(m1.rsquared)
        },
        'vix_only': {
            'beta': float(m2.params.iloc[1]),
            't_stat': float(m2.tvalues.iloc[1]),
            'p_value': float(m2.pvalues.iloc[1]),
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
            'beta_vix': float(m4.params.iloc[2]),
            't_vix': float(m4.tvalues.iloc[2]),
            'beta_own_rv': float(m4.params.iloc[3]),
            't_own_rv': float(m4.tvalues.iloc[3]),
            'r_squared': float(m4.rsquared)
        }
    }

RESULTS['part_b'] = pred_results

# ============================================================
# PART B2: DIEBOLD-MARIANO TEST — slope+VIX vs VIX alone
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

    # Model 1: VIX-only forecast
    X_vix = add_constant(reg_df['vix'])
    m_vix = OLS(reg_df['fwd_rv'], X_vix).fit()
    e1 = m_vix.resid

    # Model 2: VIX + slope forecast
    X_both = add_constant(reg_df[['vix', 'slope']])
    m_both = OLS(reg_df['fwd_rv'], X_both).fit()
    e2 = m_both.resid

    # DM test (squared loss)
    d = e1**2 - e2**2
    d_bar = d.mean()
    n_dm = len(d)

    # HAC standard error (Newey-West)
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
    print(f"    d_bar = {d_bar:.4f} (>0 means slope+VIX better)")
    print(f"    Conclusion: {'Slope ADDS value' if dm_pval < 0.05 and d_bar > 0 else 'Slope does NOT add value'}")

    dm_results[h_name] = {
        'dm_stat': float(dm_stat),
        'p_value': float(dm_pval),
        'd_bar': float(d_bar),
        'slope_adds_value': bool(dm_pval < 0.05 and d_bar > 0)
    }

RESULTS['part_b2_dm_test'] = dm_results

# ============================================================
# PART C: INVERSION EVENT STUDY — Taiwan vol around inversions
# ============================================================
print("\n" + "=" * 70)
print("PART C: Inversion Event Study — Taiwan Vol Around US Curve Inversions")
print("=" * 70)

# Identify inversion START dates (slope crosses below 0)
slope_sign = (slope_tw > 0).astype(int)
sign_change = slope_sign.diff()
inversion_starts = sign_change[sign_change == -1].index

print(f"\nInversion start dates: {len(inversion_starts)}")

if len(inversion_starts) > 0:
    # For each inversion start, measure 0050 vol before and after
    event_study = []
    for inv_date in inversion_starts:
        # Get position in TW calendar
        tw_idx = ret_0050.index.get_indexer([inv_date], method='nearest')[0]
        if tw_idx < 63 or tw_idx > len(ret_0050) - 63:
            continue

        # Pre-inversion vol (63d before)
        pre_rets = ret_0050.iloc[tw_idx-63:tw_idx]
        pre_vol = pre_rets.std() * np.sqrt(252) * 100

        # Post-inversion vol (63d after)
        post_rets = ret_0050.iloc[tw_idx:tw_idx+63]
        post_vol = post_rets.std() * np.sqrt(252) * 100

        # VIX at inversion
        vix_at = vix_tw.loc[inv_date] if inv_date in vix_tw.index else np.nan

        event_study.append({
            'date': str(inv_date.date()),
            'pre_vol_63d': float(pre_vol),
            'post_vol_63d': float(post_vol),
            'vol_change_pct': float((post_vol / pre_vol - 1) * 100) if pre_vol > 0 else np.nan,
            'vix_at_inversion': float(vix_at) if not np.isnan(vix_at) else None
        })

    print(f"  Events with sufficient data: {len(event_study)}")

    if len(event_study) > 0:
        pre_vols = [e['pre_vol_63d'] for e in event_study]
        post_vols = [e['post_vol_63d'] for e in event_study]
        changes = [e['vol_change_pct'] for e in event_study if not np.isnan(e['vol_change_pct'])]

        print(f"\n  Pre-inversion 0050 vol (63d):  mean={np.mean(pre_vols):.1f}%")
        print(f"  Post-inversion 0050 vol (63d): mean={np.mean(post_vols):.1f}%")
        print(f"  Vol change: mean={np.mean(changes):.1f}%")

        # Paired t-test: does vol change after inversion?
        if len(pre_vols) >= 3:
            t_paired, p_paired = stats.ttest_rel(post_vols, pre_vols)
            print(f"  Paired t-test (post vs pre): t={t_paired:.2f}, p={p_paired:.4f}")
        else:
            t_paired, p_paired = np.nan, np.nan

        for e in event_study:
            print(f"    {e['date']}: pre={e['pre_vol_63d']:.1f}%, "
                  f"post={e['post_vol_63d']:.1f}%, "
                  f"change={e['vol_change_pct']:.1f}%, "
                  f"VIX={e['vix_at_inversion']}")
else:
    event_study = []
    t_paired, p_paired = np.nan, np.nan

RESULTS['part_c'] = {
    'n_inversion_events': len(event_study),
    'events': event_study,
    'paired_t': float(t_paired) if not np.isnan(t_paired) else None,
    'paired_p': float(p_paired) if not np.isnan(p_paired) else None
}

# ============================================================
# PART C2: SLOPE REGIME — Taiwan vol by slope quintile
# ============================================================
print("\n" + "=" * 70)
print("PART C2: Taiwan 0050 Vol by Slope Regime")
print("=" * 70)

# Align slope and forward RV
idx_c2 = slope_tw.dropna().index.intersection(fwd_rv_21.dropna().index)
slope_c2 = slope_tw.loc[idx_c2]
rv_c2 = fwd_rv_21.loc[idx_c2]

# Quintiles
quintiles = pd.qcut(slope_c2, 5, labels=['Q1(inverted)', 'Q2', 'Q3', 'Q4', 'Q5(steep)'])
regime_results = {}

print(f"\nForward 21d 0050 vol by slope quintile (n={len(idx_c2)}):")
for q in ['Q1(inverted)', 'Q2', 'Q3', 'Q4', 'Q5(steep)']:
    mask = quintiles == q
    rv_q = rv_c2[mask]
    print(f"  {q}: mean={rv_q.mean():.2f}%, median={rv_q.median():.2f}%, "
          f"std={rv_q.std():.2f}%, n={mask.sum()}")
    regime_results[q] = {
        'mean': float(rv_q.mean()),
        'median': float(rv_q.median()),
        'std': float(rv_q.std()),
        'n': int(mask.sum())
    }

# Q1 vs Q5 test
q1_mask = quintiles == 'Q1(inverted)'
q5_mask = quintiles == 'Q5(steep)'
t_q1q5, p_q1q5 = stats.ttest_ind(rv_c2[q1_mask], rv_c2[q5_mask])
print(f"\n  Q1 vs Q5 t-test: t={t_q1q5:.2f}, p={p_q1q5:.4f}")

# Monotonicity test (Spearman rank of quintile vs mean vol)
q_means = [regime_results[q]['mean'] for q in ['Q1(inverted)', 'Q2', 'Q3', 'Q4', 'Q5(steep)']]
spearman_rho, spearman_p = stats.spearmanr(range(5), q_means)
print(f"  Monotonicity (Spearman): rho={spearman_rho:.3f}, p={spearman_p:.4f}")

RESULTS['part_c2'] = {
    'regime_results': regime_results,
    'q1_vs_q5_t': float(t_q1q5),
    'q1_vs_q5_p': float(p_q1q5),
    'monotonicity_rho': float(spearman_rho),
    'monotonicity_p': float(spearman_p)
}

# ============================================================
# PART D: TRADING STRATEGY — Slope-enhanced VT for Taiwan
# ============================================================
print("\n" + "=" * 70)
print("PART D: Trading Strategy — Can Slope Improve Taiwan VT?")
print("=" * 70)

# Build strategy data on TW calendar
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

TX_COST = 0.001  # 10 bps one-way

# Strategy 1: Baseline — Buy & Hold 0050
strat_df['bh_ret'] = strat_df['ret_0050']

# Strategy 2: Standard Taiwan VT (8.63/VIX target — K82/K88)
target_vol = 8.63
strat_df['vt_weight_raw'] = target_vol / strat_df['vix']
strat_df['vt_weight'] = strat_df['vt_weight_raw'].clip(0, 1)
# CRITICAL: signal.shift(1) — use yesterday's VIX for today's weight
strat_df['vt_weight_lag'] = strat_df['vt_weight'].shift(1)
strat_df['vt_weight_change'] = strat_df['vt_weight_lag'].diff().abs()
strat_df['vt_tx'] = strat_df['vt_weight_change'] * TX_COST
strat_df['vt_ret'] = strat_df['vt_weight_lag'] * strat_df['ret_0050'] - strat_df['vt_tx']

# Strategy 3: Slope Guard — reduce exposure when curve inverts
# When slope < 0: reduce weight by 50% (defensive)
strat_df['slope_guard'] = np.where(strat_df['slope'] < 0, 0.5, 1.0)
# CRITICAL: signal.shift(1) — use yesterday's slope for today's weight
strat_df['slope_guard_lag'] = strat_df['slope_guard'].shift(1)
strat_df['sg_weight'] = strat_df['vt_weight_lag'] * strat_df['slope_guard_lag']
strat_df['sg_weight_change'] = strat_df['sg_weight'].diff().abs()
strat_df['sg_tx'] = strat_df['sg_weight_change'] * TX_COST
strat_df['sg_ret'] = strat_df['sg_weight'] * strat_df['ret_0050'] - strat_df['sg_tx']

# Strategy 4: Continuous slope adjustment (proportional to slope z-score)
# When slope very negative: reduce more; when very positive: full exposure
slope_expanding_mean = strat_df['slope'].expanding(min_periods=252).mean()
slope_expanding_std = strat_df['slope'].expanding(min_periods=252).std()
strat_df['slope_z'] = (strat_df['slope'] - slope_expanding_mean) / slope_expanding_std
# Map z-score to multiplier: z=-2 → 0.5, z=0 → 1.0, z=+2 → 1.0 (cap at 1.0)
strat_df['slope_mult_raw'] = 0.5 + 0.25 * strat_df['slope_z']
strat_df['slope_mult'] = strat_df['slope_mult_raw'].clip(0.3, 1.0)
# CRITICAL: signal.shift(1)
strat_df['slope_mult_lag'] = strat_df['slope_mult'].shift(1)
strat_df['cont_weight'] = strat_df['vt_weight_lag'] * strat_df['slope_mult_lag']
strat_df['cont_weight_change'] = strat_df['cont_weight'].diff().abs()
strat_df['cont_tx'] = strat_df['cont_weight_change'] * TX_COST
strat_df['cont_ret'] = strat_df['cont_weight'] * strat_df['ret_0050'] - strat_df['cont_tx']

# Drop warmup rows
strat_clean = strat_df.dropna(subset=['vt_ret', 'sg_ret', 'cont_ret']).copy()
print(f"  Strategy analysis: {len(strat_clean)} days after warmup")

# Compute performance metrics
def compute_metrics(returns, name):
    r = returns.dropna()
    n_years = len(r) / 252
    cum = (1 + r).cumprod()
    total_ret = cum.iloc[-1] - 1
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    # Max drawdown
    rolling_max = cum.cummax()
    drawdown = (cum / rolling_max - 1)
    mdd = drawdown.min()
    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    print(f"\n  {name}:")
    print(f"    Ann. Return: {ann_ret*100:.2f}%")
    print(f"    Ann. Vol:    {ann_vol*100:.2f}%")
    print(f"    Sharpe:      {sharpe:.3f}")
    print(f"    Sortino:     {sortino:.3f}")
    print(f"    Max DD:      {mdd*100:.1f}%")
    print(f"    Total Ret:   {total_ret*100:.1f}%")

    return {
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'sortino': float(sortino),
        'max_drawdown': float(mdd),
        'total_return': float(total_ret)
    }

print(f"\n--- Full Period Performance ---")
metrics = {}
metrics['buy_hold_0050'] = compute_metrics(strat_clean['bh_ret'], 'Buy & Hold 0050')
metrics['taiwan_vt_863'] = compute_metrics(strat_clean['vt_ret'], 'Taiwan VT (8.63/VIX)')
metrics['slope_guard'] = compute_metrics(strat_clean['sg_ret'], 'Slope Guard (50% cut on inversion)')
metrics['continuous_slope'] = compute_metrics(strat_clean['cont_ret'], 'Continuous Slope Adj')

RESULTS['part_d'] = {'full_period': metrics}

# ============================================================
# PART D2: SUB-PERIOD ANALYSIS (vs K749 US 3 regimes)
# ============================================================
print("\n--- Sub-Period Analysis ---")

# Define regimes
sub_periods = [
    ('Pre-GFC', '2007-01-01', '2008-09-01'),
    ('GFC', '2008-09-01', '2009-06-01'),
    ('Post-GFC', '2009-06-01', '2015-01-01'),
    ('Rate-Hike', '2015-01-01', '2019-06-01'),
    ('COVID', '2020-01-01', '2020-12-01'),
    ('Post-COVID', '2021-01-01', '2022-12-01'),
    ('Rate-Inversion', '2022-07-01', '2024-12-01'),
    ('Recent', '2025-01-01', '2026-12-01')
]

sub_results = {}
for name, s, e in sub_periods:
    mask = (strat_clean.index >= s) & (strat_clean.index < e)
    sub = strat_clean[mask]
    if len(sub) < 63:
        print(f"\n  {name}: too few obs ({len(sub)}), skip")
        continue

    print(f"\n  === {name} ({s} to {e}, n={len(sub)}) ===")

    # Average slope in this period
    avg_slope = sub['slope'].mean()
    pct_inverted = (sub['slope'] < 0).mean() * 100
    print(f"    Avg slope: {avg_slope:.2f}%, Inverted: {pct_inverted:.0f}%")

    sub_metrics = {}
    for strat_name, col in [('B&H', 'bh_ret'), ('VT', 'vt_ret'),
                             ('SlopeGuard', 'sg_ret'), ('ContSlope', 'cont_ret')]:
        r = sub[col].dropna()
        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + r).cumprod()
        mdd = (cum / cum.cummax() - 1).min()
        print(f"    {strat_name}: ret={ann_ret*100:.1f}%, vol={ann_vol*100:.1f}%, "
              f"Sharpe={sharpe:.3f}, MDD={mdd*100:.1f}%")
        sub_metrics[strat_name] = {
            'ann_return': float(ann_ret),
            'ann_vol': float(ann_vol),
            'sharpe': float(sharpe),
            'mdd': float(mdd)
        }

    sub_results[name] = {
        'avg_slope': float(avg_slope),
        'pct_inverted': float(pct_inverted),
        'metrics': sub_metrics
    }

RESULTS['part_d2'] = sub_results

# ============================================================
# PART D3: DM TEST — Slope strategies vs plain VT
# ============================================================
print("\n" + "=" * 70)
print("PART D3: DM Test — Do slope strategies beat plain Taiwan VT?")
print("=" * 70)

# DM test: slope_guard vs plain VT
for strat_name, strat_col in [('SlopeGuard', 'sg_ret'), ('ContSlope', 'cont_ret')]:
    vt_r = strat_clean['vt_ret'].dropna()
    sg_r = strat_clean[strat_col].dropna()
    common = vt_r.index.intersection(sg_r.index)
    vt_r = vt_r.loc[common]
    sg_r = sg_r.loc[common]

    # DM test on returns (not squared errors)
    d = sg_r - vt_r  # Positive if slope strategy is better
    d_bar = d.mean()
    n_d = len(d)

    lag_d = int(np.ceil(n_d**(1/3)))
    gamma_0_d = np.var(d, ddof=1)
    gamma_sum_d = 0
    for k in range(1, lag_d + 1):
        gk = np.cov(d.iloc[k:].values, d.iloc[:-k].values)[0, 1]
        gamma_sum_d += 2 * (1 - k / (lag_d + 1)) * gk
    var_d_d = gamma_0_d + gamma_sum_d
    se_d_d = np.sqrt(var_d_d / n_d) if var_d_d > 0 else 1e-10

    dm_stat_d = d_bar / se_d_d
    dm_pval_d = 2 * (1 - stats.norm.cdf(abs(dm_stat_d)))

    print(f"\n  {strat_name} vs VT: DM stat = {dm_stat_d:.3f}, p = {dm_pval_d:.4f}")
    print(f"    Mean daily excess return: {d_bar*10000:.2f} bps")
    print(f"    Ann. excess return: {d_bar*252*100:.2f}%")

    RESULTS[f'dm_{strat_name.lower()}_vs_vt'] = {
        'dm_stat': float(dm_stat_d),
        'p_value': float(dm_pval_d),
        'mean_daily_excess_bps': float(d_bar * 10000),
        'ann_excess_pct': float(d_bar * 252 * 100)
    }

# ============================================================
# PART E: COMPARISON WITH K749 US FINDINGS
# ============================================================
print("\n" + "=" * 70)
print("PART E: Comparison with K749 (US Yield Curve → SPY Vol)")
print("=" * 70)

comparison = {
    'US_K749': {
        'partial_r_21d': -0.006,
        'partial_r_63d': 0.048,
        'partial_r_126d': 0.081,
        'slope_subsumption': 'Full at 21d, partial at 63d+',
        'trading_value': 'NULL (no strategy beats BH or VT)',
        'note': 'Counter-intuitive: steep curve = higher VIX (crisis recovery)'
    },
    'TW_K761': {}
}

for h_name in ['21d', '63d', '126d']:
    if h_name in pred_results:
        comparison['TW_K761'][f'partial_r_{h_name}'] = pred_results[h_name]['partial_correlation']['partial_r']
        comparison['TW_K761'][f'partial_t_{h_name}'] = pred_results[h_name]['partial_correlation']['t_stat']

print("\n  Partial correlation (slope|VIX → fwd_RV|VIX):")
print(f"    {'Horizon':<10} {'US (K749)':<15} {'TW (K761)':<15}")
for h in ['21d', '63d', '126d']:
    us_val = comparison['US_K749'].get(f'partial_r_{h}', 'N/A')
    tw_val = comparison['TW_K761'].get(f'partial_r_{h}', 'N/A')
    tw_t = comparison['TW_K761'].get(f'partial_t_{h}', 'N/A')
    if isinstance(us_val, float) and isinstance(tw_val, float):
        print(f"    {h:<10} {us_val:<15.4f} {tw_val:.4f} (t={tw_t:.2f})")
    elif isinstance(tw_val, float):
        print(f"    {h:<10} {'N/A':<15} {tw_val:.4f} (t={tw_t:.2f})")

RESULTS['part_e_comparison'] = comparison

# ============================================================
# OVERALL CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("OVERALL CONCLUSION")
print("=" * 70)

# Summarize key findings
any_slope_sig = any(
    pred_results.get(h, {}).get('partial_correlation', {}).get('passes_harvey_3', False)
    for h in ['21d', '63d', '126d']
)
any_dm_sig = any(
    dm_results.get(h, {}).get('slope_adds_value', False)
    for h in ['21d', '63d', '126d']
)

slope_guard_sharpe = metrics.get('slope_guard', {}).get('sharpe', 0)
vt_sharpe = metrics.get('taiwan_vt_863', {}).get('sharpe', 0)
bh_sharpe = metrics.get('buy_hold_0050', {}).get('sharpe', 0)

conclusion_lines = []

if not any_slope_sig:
    conclusion_lines.append("NULL: Yield curve slope does NOT pass Harvey (2016) t>3.0 threshold for ANY horizon in Taiwan.")
    conclusion_lines.append("This confirms K749 finding extends to Taiwan — VIX subsumes slope information.")
else:
    sig_horizons = [h for h in ['21d', '63d', '126d']
                    if pred_results.get(h, {}).get('partial_correlation', {}).get('passes_harvey_3', False)]
    conclusion_lines.append(f"PARTIAL: Slope shows significance at {', '.join(sig_horizons)} horizon(s) for Taiwan.")

if slope_guard_sharpe <= vt_sharpe:
    conclusion_lines.append(f"Trading: Slope guard Sharpe ({slope_guard_sharpe:.3f}) ≤ plain VT ({vt_sharpe:.3f}) — no improvement.")
else:
    conclusion_lines.append(f"Trading: Slope guard Sharpe ({slope_guard_sharpe:.3f}) > plain VT ({vt_sharpe:.3f}) — but check DM test.")

conclusion_lines.append(f"Baseline: B&H 0050 Sharpe={bh_sharpe:.3f}")

conclusion = ' | '.join(conclusion_lines)
print(f"\n{conclusion}")

RESULTS['conclusion'] = {
    'any_partial_r_passes_harvey': any_slope_sig,
    'any_dm_test_significant': any_dm_sig,
    'slope_guard_sharpe': float(slope_guard_sharpe),
    'vt_sharpe': float(vt_sharpe),
    'bh_sharpe': float(bh_sharpe),
    'verdict': conclusion
}

# ============================================================
# SAVE RESULTS
# ============================================================
RESULTS['metadata'] = {
    'experiment': 'K761',
    'title': 'Taiwan Yield Curve and 0050.TW Volatility Prediction',
    'date': datetime.now().isoformat(),
    'data_source': 'yfinance (0050.TW, ^VIX, ^TNX, ^IRX)',
    'period': f"{strat_df.index[0].date()} to {strat_df.index[-1].date()}",
    'n_obs': int(len(strat_df)),
    'methodology': 'TW calendar primary, VIX/slope asof-lookup, signal.shift(1), TX 10bps',
    'references': [
        'K749: US yield curve → SPY vol (NULL short-term)',
        'K739b: Taiwan VT cross-validation (holiday-fixed)',
        'K636: Taiwan amplification 4.6x',
        'Estrella & Hardouvelis (1991)',
        'Adrian et al. (2019) Vulnerable Growth AER',
        'Harvey (1988)'
    ],
    'attribution': '[提出: Claude (from research_program), 執行: Claude]'
}

output_path = OUTPUT_DIR / 'k761_taiwan_yield_curve_results.json'
with open(output_path, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

print("\n" + "=" * 70)
print("K761 COMPLETE")
print("=" * 70)
