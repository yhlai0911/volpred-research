#!/usr/bin/env python3
"""
K752: VIX Sufficiency Era Stability — Does the Finding Hold Pre-2010?

[提出: Claude, 執行: Claude]

Background:
  K730-K751 confirmed VIX sufficiency from 11 angles, but mostly 2010-2026 data.
  This experiment tests whether VIX sufficiency holds across 5 distinct market eras
  spanning 1993-2026 (33 years).

Design:
  Part A: Era definition (dot-com, post-dot-com, GFC, low-vol, COVID/inflation)
  Part B: VIX prediction power by era (regress RV_t+22 on VIX_t)
  Part C: 12/VIX strategy by era (SPY/GLD post-2004, SPY/cash pre-2004)
  Part D: Competing signals by era (overnight VIX Δ, VRP proxy, rolling vol momentum)

Data: ^VIX (1993-2026), SPY (1993-2026), GLD (2004-2026), ^TNX (2003-2026)
Signal lag: signal.shift(1) — mandatory
TX cost: 5bps both legs per rebalance

References:
  - K730: Cross-asset vol momentum (null, VIX sufficiency confirmed)
  - K734: VRP predictability (IS t=4.38, OOS DM p=0.163, null)
  - K751: Overnight VIX Δ (stat sig but economically marginal)
  - K687: Correct lag → no VT beats BH 50/50 in Sharpe
  - K697: VIX predicts vol magnitude (corr 0.57) not direction (corr 0.04)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# CONFIG
# ============================================================
ERAS = {
    'Era1_DotCom': ('1993-01-01', '2000-03-31'),
    'Era2_PostDotCom': ('2000-04-01', '2007-06-30'),
    'Era3_GFC': ('2007-07-01', '2012-06-30'),
    'Era4_LowVol_QE': ('2012-07-01', '2020-01-31'),
    'Era5_COVID_Inflation': ('2020-02-01', '2026-12-31'),
}

TX_COST_BPS = 5  # both legs
FORECAST_HORIZON = 22  # trading days for RV
RV_WINDOW = 22

# ============================================================
# DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K752: VIX Sufficiency Era Stability")
print("=" * 70)

tickers = {'^VIX': 'VIX', 'SPY': 'SPY', 'GLD': 'GLD', '^TNX': 'TNX'}
data = {}

for tk, name in tickers.items():
    start = '1990-01-01' if tk != 'GLD' else '2004-01-01'
    df = yf.download(tk, start=start, end='2026-12-31', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].dropna()
    print(f"  {name}: {len(data[name])} obs, {data[name].index[0].strftime('%Y-%m-%d')} to {data[name].index[-1].strftime('%Y-%m-%d')}")

# Align dates
vix = data['VIX']
spy = data['SPY']
gld = data['GLD']

# SPY returns
spy_ret = spy.pct_change().dropna()

# Realized Volatility (22-day annualized)
spy_rv22 = (spy_ret ** 2).rolling(RV_WINDOW).sum().apply(np.sqrt) * np.sqrt(252 / RV_WINDOW)
# Forward RV (next 22 days)
spy_rv22_fwd = spy_rv22.shift(-FORECAST_HORIZON)

print(f"\nSPY returns: {len(spy_ret)} obs")
print(f"SPY RV22: {len(spy_rv22.dropna())} obs")

# ============================================================
# PART B: VIX PREDICTION POWER BY ERA
# ============================================================
print("\n" + "=" * 70)
print("PART B: VIX Prediction Power by Era")
print("=" * 70)

# Align VIX and forward RV
common_idx = vix.index.intersection(spy_rv22_fwd.dropna().index)
vix_aligned = vix.loc[common_idx]
rv_fwd_aligned = spy_rv22_fwd.loc[common_idx]

# Scale VIX to same units as RV (VIX is already annualized %)
vix_scaled = vix_aligned / 100  # VIX is in % points

part_b_results = {}

for era_name, (start, end) in ERAS.items():
    mask = (vix_aligned.index >= start) & (vix_aligned.index <= end)
    era_vix = vix_scaled[mask].values
    era_rv = rv_fwd_aligned[mask].values

    # Remove NaN
    valid = ~(np.isnan(era_vix) | np.isnan(era_rv))
    era_vix = era_vix[valid]
    era_rv = era_rv[valid]

    if len(era_vix) < 50:
        print(f"\n  {era_name}: SKIP (only {len(era_vix)} obs)")
        continue

    # OLS: RV_fwd = alpha + beta * VIX + epsilon
    slope, intercept, r_value, p_value, std_err = stats.linregress(era_vix, era_rv)
    r_squared = r_value ** 2

    # Correlation
    corr = np.corrcoef(era_vix, era_rv)[0, 1]

    # Newey-West adjustment for overlapping returns (HAC)
    # Simple t-stat from linregress (not HAC, but indicative)
    t_stat = slope / std_err

    part_b_results[era_name] = {
        'n_obs': int(len(era_vix)),
        'period': f"{start} to {end}",
        'R_squared': round(float(r_squared), 4),
        'beta': round(float(slope), 4),
        'beta_t': round(float(t_stat), 2),
        'beta_p': float(f"{p_value:.2e}"),
        'correlation': round(float(corr), 4),
        'mean_VIX': round(float(np.mean(era_vix) * 100), 2),
        'mean_RV': round(float(np.mean(era_rv) * 100), 2),
        'std_VIX': round(float(np.std(era_vix) * 100), 2),
        'std_RV': round(float(np.std(era_rv) * 100), 2),
    }

    print(f"\n  {era_name} ({start} to {end}): N={len(era_vix)}")
    print(f"    R² = {r_squared:.4f}, β = {slope:.4f}, t = {t_stat:.2f}, p = {p_value:.2e}")
    print(f"    Corr(VIX, fwd RV) = {corr:.4f}")
    print(f"    Mean VIX = {np.mean(era_vix)*100:.1f}%, Mean fwd RV = {np.mean(era_rv)*100:.1f}%")

# Full sample
full_vix = vix_scaled.values
full_rv = rv_fwd_aligned.values
valid = ~(np.isnan(full_vix) | np.isnan(full_rv))
full_vix_clean = full_vix[valid]
full_rv_clean = full_rv[valid]
slope_f, intercept_f, r_f, p_f, se_f = stats.linregress(full_vix_clean, full_rv_clean)
r2_full = r_f ** 2

part_b_results['Full_Sample'] = {
    'n_obs': int(len(full_vix_clean)),
    'period': f"{vix_aligned.index[0].strftime('%Y-%m-%d')} to {vix_aligned.index[-1].strftime('%Y-%m-%d')}",
    'R_squared': round(float(r2_full), 4),
    'beta': round(float(slope_f), 4),
    'beta_t': round(float(slope_f / se_f), 2),
    'correlation': round(float(r_f), 4),
    'mean_VIX': round(float(np.mean(full_vix_clean) * 100), 2),
    'mean_RV': round(float(np.mean(full_rv_clean) * 100), 2),
}

print(f"\n  Full Sample: N={len(full_vix_clean)}, R² = {r2_full:.4f}, Corr = {r_f:.4f}")

# ============================================================
# PART C: 12/VIX STRATEGY BY ERA
# ============================================================
print("\n" + "=" * 70)
print("PART C: 12/VIX Strategy by Era")
print("=" * 70)

# Build daily returns for SPY and GLD
spy_daily = spy_ret.copy()
gld_ret = gld.pct_change().dropna()

# 12/VIX weight for SPY (lagged)
vix_daily = vix.reindex(spy_daily.index).ffill()
w_spy_raw = 12.0 / vix_daily
w_spy_raw = w_spy_raw.clip(0, 1)  # Cap at 100% equity
w_spy_signal = w_spy_raw.shift(1)  # LAG: signal from t-1, trade at t

# 50/50 baseline (constant)
w_50_spy = 0.5

part_c_results = {}

for era_name, (start, end) in ERAS.items():
    # Pre-2004: SPY/cash (no GLD)
    use_gld = pd.Timestamp(start) >= pd.Timestamp('2004-11-01')

    mask_spy = (spy_daily.index >= start) & (spy_daily.index <= end)
    era_spy_ret = spy_daily[mask_spy]
    era_w_spy = w_spy_signal.reindex(era_spy_ret.index).dropna()

    # Align
    common = era_spy_ret.index.intersection(era_w_spy.index)

    if use_gld:
        era_gld_ret = gld_ret.reindex(common).fillna(0)
        common = common.intersection(era_gld_ret.dropna().index)
        era_spy_ret_c = era_spy_ret.loc[common]
        era_gld_ret_c = era_gld_ret.loc[common]
        era_w_c = era_w_spy.loc[common]

        # 12/VIX strategy: w*SPY + (1-w)*GLD
        strat_ret = era_w_c * era_spy_ret_c + (1 - era_w_c) * era_gld_ret_c
        # 50/50 baseline: 0.5*SPY + 0.5*GLD
        baseline_ret = 0.5 * era_spy_ret_c + 0.5 * era_gld_ret_c
        complement = 'GLD'
    else:
        era_spy_ret_c = era_spy_ret.loc[common]
        era_w_c = era_w_spy.loc[common]

        # 12/VIX strategy: w*SPY + (1-w)*cash (0 return)
        strat_ret = era_w_c * era_spy_ret_c
        # 50/50 baseline: 0.5*SPY + 0.5*cash
        baseline_ret = 0.5 * era_spy_ret_c
        complement = 'Cash'

    # TX costs (both legs)
    w_change = era_w_c.diff().abs().fillna(0)
    tx_daily = w_change * 2 * (TX_COST_BPS / 10000)  # both legs
    strat_ret_net = strat_ret - tx_daily

    # Metrics
    def calc_metrics(rets, label):
        if len(rets) < 20:
            return None
        ann_ret = rets.mean() * 252
        ann_vol = rets.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + rets).cumprod()
        mdd = ((cum / cum.cummax()) - 1).min()
        return {
            'label': label,
            'n_days': int(len(rets)),
            'ann_return': round(float(ann_ret), 4),
            'ann_vol': round(float(ann_vol), 4),
            'sharpe': round(float(sharpe), 4),
            'mdd': round(float(mdd), 4),
            'total_return': round(float(cum.iloc[-1] - 1), 4) if len(cum) > 0 else 0,
        }

    m_strat = calc_metrics(strat_ret_net, f'12/VIX (SPY/{complement})')
    m_base = calc_metrics(baseline_ret, f'50/50 (SPY/{complement})')

    if m_strat is None or m_base is None:
        print(f"\n  {era_name}: SKIP (insufficient data)")
        continue

    sharpe_diff = m_strat['sharpe'] - m_base['sharpe']
    strat_wins = m_strat['sharpe'] > m_base['sharpe']

    # Average turnover
    avg_turnover = float(w_change.mean() * 252)  # annualized

    part_c_results[era_name] = {
        'period': f"{start} to {end}",
        'complement_asset': complement,
        'strategy': m_strat,
        'baseline': m_base,
        'sharpe_diff': round(float(sharpe_diff), 4),
        'strategy_wins': bool(strat_wins),
        'avg_annual_turnover': round(avg_turnover, 2),
        'avg_vix': round(float(vix_daily.loc[(vix_daily.index >= start) & (vix_daily.index <= end)].mean()), 2),
    }

    print(f"\n  {era_name} ({start} to {end}, complement={complement}):")
    print(f"    12/VIX: Sharpe={m_strat['sharpe']:.3f}, MDD={m_strat['mdd']:.3f}, Return={m_strat['total_return']:.3f}")
    print(f"    50/50:  Sharpe={m_base['sharpe']:.3f}, MDD={m_base['mdd']:.3f}, Return={m_base['total_return']:.3f}")
    print(f"    Δ Sharpe = {sharpe_diff:+.3f}, Strategy {'WINS' if strat_wins else 'LOSES'}")
    print(f"    Avg VIX = {part_c_results[era_name]['avg_vix']:.1f}, Turnover = {avg_turnover:.1f}x/yr")

# ============================================================
# PART D: COMPETING SIGNALS BY ERA
# ============================================================
print("\n" + "=" * 70)
print("PART D: Competing Signals by Era")
print("=" * 70)

# Signal 1: Overnight VIX change (proxy for news sentiment)
# |VIX_open - VIX_prev_close|
vix_df = yf.download('^VIX', start='1993-01-01', end='2026-12-31', progress=False, auto_adjust=True)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_open = vix_df['Open']
vix_close = vix_df['Close']
overnight_vix_change = (vix_open - vix_close.shift(1)).abs()
# Use absolute change as predictor of next-day |return|
abs_spy_ret = spy_daily.abs()

# Signal 2: VRP proxy = VIX - RV22 (risk premium)
rv22_current = (spy_ret ** 2).rolling(22).sum().apply(np.sqrt) * np.sqrt(252 / 22)
vrp = (vix / 100) - rv22_current
vrp = vrp.reindex(spy_daily.index)

# Signal 3: Rolling vol momentum (20d vs 60d RV ratio)
rv20 = (spy_ret ** 2).rolling(20).sum().apply(np.sqrt) * np.sqrt(252 / 20)
rv60 = (spy_ret ** 2).rolling(60).sum().apply(np.sqrt) * np.sqrt(252 / 60)
vol_momentum = rv20 / rv60 - 1  # positive = vol accelerating

part_d_results = {}

for era_name, (start, end) in ERAS.items():
    era_results = {}

    # Forward RV for prediction
    mask = (spy_rv22_fwd.index >= start) & (spy_rv22_fwd.index <= end)
    era_rv_fwd = spy_rv22_fwd[mask].dropna()
    era_vix_base = (vix / 100).reindex(era_rv_fwd.index).dropna()

    common = era_rv_fwd.index.intersection(era_vix_base.index)
    era_rv_fwd_c = era_rv_fwd.loc[common]
    era_vix_c = era_vix_base.loc[common]

    if len(common) < 100:
        print(f"\n  {era_name}: SKIP (only {len(common)} obs)")
        continue

    # VIX-only baseline R²
    valid = ~(np.isnan(era_vix_c.values) | np.isnan(era_rv_fwd_c.values))
    if valid.sum() < 50:
        continue

    slope_b, _, r_b, _, _ = stats.linregress(era_vix_c.values[valid], era_rv_fwd_c.values[valid])
    r2_base = r_b ** 2

    # Test each competing signal: incremental R² from VIX + signal vs VIX alone
    signals = {
        'Overnight_VIX_Abs': overnight_vix_change,
        'VRP_Proxy': vrp,
        'Vol_Momentum_20_60': vol_momentum,
    }

    for sig_name, sig_series in signals.items():
        sig_era = sig_series.reindex(common).dropna()
        tri_common = common.intersection(sig_era.index)

        if len(tri_common) < 100:
            era_results[sig_name] = {'status': 'insufficient_data', 'n_obs': int(len(tri_common))}
            continue

        y = era_rv_fwd_c.loc[tri_common].values
        x_vix = era_vix_c.loc[tri_common].values
        x_sig = sig_era.loc[tri_common].values

        valid2 = ~(np.isnan(y) | np.isnan(x_vix) | np.isnan(x_sig) | np.isinf(x_sig))
        y, x_vix, x_sig = y[valid2], x_vix[valid2], x_sig[valid2]

        if len(y) < 50:
            era_results[sig_name] = {'status': 'insufficient_data', 'n_obs': int(len(y))}
            continue

        # VIX-only R²
        X_vix = np.column_stack([np.ones(len(y)), x_vix])
        beta_vix = np.linalg.lstsq(X_vix, y, rcond=None)[0]
        resid_vix = y - X_vix @ beta_vix
        ss_res_vix = np.sum(resid_vix ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2_vix_only = 1 - ss_res_vix / ss_tot

        # VIX + signal R²
        X_both = np.column_stack([np.ones(len(y)), x_vix, x_sig])
        beta_both = np.linalg.lstsq(X_both, y, rcond=None)[0]
        resid_both = y - X_both @ beta_both
        ss_res_both = np.sum(resid_both ** 2)
        r2_both = 1 - ss_res_both / ss_tot

        incremental_r2 = r2_both - r2_vix_only

        # F-test for incremental variable
        n = len(y)
        k_full = 3  # intercept + VIX + signal
        k_reduced = 2  # intercept + VIX
        if ss_res_both > 0:
            f_stat = ((ss_res_vix - ss_res_both) / (k_full - k_reduced)) / (ss_res_both / (n - k_full))
            f_pval = 1 - stats.f.cdf(f_stat, k_full - k_reduced, n - k_full)
        else:
            f_stat, f_pval = np.nan, np.nan

        # Signal coefficient t-stat
        # Manual calculation
        XtX_inv = np.linalg.inv(X_both.T @ X_both)
        sigma2 = ss_res_both / (n - k_full)
        se_beta = np.sqrt(np.diag(XtX_inv) * sigma2)
        t_sig = beta_both[2] / se_beta[2] if se_beta[2] > 0 else np.nan

        era_results[sig_name] = {
            'n_obs': int(n),
            'R2_VIX_only': round(float(r2_vix_only), 4),
            'R2_VIX_plus_signal': round(float(r2_both), 4),
            'incremental_R2': round(float(incremental_r2), 4),
            'incremental_R2_pct': round(float(incremental_r2 * 100), 3),
            'F_stat': round(float(f_stat), 2) if not np.isnan(f_stat) else None,
            'F_pval': round(float(f_pval), 4) if not np.isnan(f_pval) else None,
            'signal_coef': round(float(beta_both[2]), 6),
            'signal_t': round(float(t_sig), 2) if not np.isnan(t_sig) else None,
            'significant_5pct': bool(f_pval < 0.05) if not np.isnan(f_pval) else False,
            'harvey_pass': bool(abs(t_sig) > 3.0) if not np.isnan(t_sig) else False,
        }

    part_d_results[era_name] = {
        'period': f"{start} to {end}",
        'vix_only_R2': round(float(r2_base), 4),
        'signals': era_results,
    }

    print(f"\n  {era_name} ({start} to {end}), VIX-only R² = {r2_base:.4f}")
    for sig_name, res in era_results.items():
        if 'incremental_R2' in res:
            sig_str = "✓ Harvey" if res.get('harvey_pass') else ("* p<.05" if res.get('significant_5pct') else "  n.s.")
            print(f"    {sig_name}: ΔR² = {res['incremental_R2_pct']:+.3f}%, F={res.get('F_stat','N/A')}, t={res.get('signal_t','N/A')} {sig_str}")
        else:
            print(f"    {sig_name}: {res.get('status', 'N/A')}")

# ============================================================
# SYNTHESIS
# ============================================================
print("\n" + "=" * 70)
print("SYNTHESIS: Era Stability Summary")
print("=" * 70)

# R² stability across eras
r2_values = [v['R_squared'] for k, v in part_b_results.items() if k != 'Full_Sample']
r2_mean = np.mean(r2_values)
r2_std = np.std(r2_values)
r2_cv = r2_std / r2_mean if r2_mean > 0 else np.inf
r2_min = np.min(r2_values)
r2_max = np.max(r2_values)

print(f"\nPart B: VIX→RV Prediction R² across eras:")
print(f"  Range: {r2_min:.4f} to {r2_max:.4f}")
print(f"  Mean: {r2_mean:.4f}, Std: {r2_std:.4f}, CV: {r2_cv:.2f}")
print(f"  Full sample R²: {part_b_results.get('Full_Sample', {}).get('R_squared', 'N/A')}")

# Strategy stability
sharpe_diffs = [v['sharpe_diff'] for v in part_c_results.values()]
strat_wins = sum(1 for v in part_c_results.values() if v['strategy_wins'])
total_eras = len(part_c_results)

print(f"\nPart C: 12/VIX vs 50/50 Strategy Sharpe:")
print(f"  12/VIX wins: {strat_wins}/{total_eras} eras")
print(f"  Avg Δ Sharpe: {np.mean(sharpe_diffs):+.4f}")
for era_name, res in part_c_results.items():
    print(f"    {era_name}: {res['sharpe_diff']:+.4f} ({'WIN' if res['strategy_wins'] else 'LOSE'})")

# Competing signals: any era where they help?
print(f"\nPart D: Competing Signals — Any era with Harvey-significant incremental R²?")
any_harvey = False
for era_name, era_res in part_d_results.items():
    for sig_name, sig_res in era_res.get('signals', {}).items():
        if sig_res.get('harvey_pass'):
            print(f"    ✓ {era_name} / {sig_name}: ΔR² = {sig_res['incremental_R2_pct']:+.3f}%, t = {sig_res['signal_t']:.2f}")
            any_harvey = True
if not any_harvey:
    print("    NONE — no competing signal passes Harvey t>3.0 in ANY era")

# Time-invariance assessment
print(f"\n{'='*70}")
print("CONCLUSION")
print(f"{'='*70}")

time_invariant = r2_cv < 0.5  # CV < 50% = relatively stable
vix_sufficient_all_eras = not any_harvey
strategy_robust = strat_wins >= 3

if time_invariant:
    print(f"  VIX prediction power is TIME-INVARIANT (CV={r2_cv:.2f} < 0.50)")
else:
    print(f"  VIX prediction power VARIES across eras (CV={r2_cv:.2f} >= 0.50)")

if vix_sufficient_all_eras:
    print(f"  VIX sufficiency holds in ALL eras — no competing signal passes Harvey threshold")
else:
    print(f"  Some competing signals have era-specific value")

if strategy_robust:
    print(f"  12/VIX strategy wins {strat_wins}/{total_eras} eras — reasonably robust")
else:
    print(f"  12/VIX strategy wins only {strat_wins}/{total_eras} eras — NOT robust across regimes")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K752',
    'title': 'VIX Sufficiency Era Stability — Does the Finding Hold Pre-2010?',
    'proposer': 'Claude',
    'executor': 'Claude',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (^VIX, SPY, GLD, ^TNX)',
    'data_period': '1993-2026',
    'methodology': {
        'eras': {k: {'start': v[0], 'end': v[1]} for k, v in ERAS.items()},
        'forecast_horizon': FORECAST_HORIZON,
        'rv_window': RV_WINDOW,
        'tx_cost_bps': TX_COST_BPS,
        'signal_lag': 'shift(1) — t-1 signal, t return',
        'competing_signals': ['overnight_vix_abs_change', 'vrp_proxy', 'vol_momentum_20_60'],
    },
    'part_b_vix_prediction_by_era': part_b_results,
    'part_c_strategy_by_era': part_c_results,
    'part_d_competing_signals_by_era': part_d_results,
    'synthesis': {
        'r2_range': [round(r2_min, 4), round(r2_max, 4)],
        'r2_mean': round(r2_mean, 4),
        'r2_std': round(r2_std, 4),
        'r2_cv': round(r2_cv, 4),
        'time_invariant': time_invariant,
        'strategy_wins_count': f"{strat_wins}/{total_eras}",
        'avg_sharpe_diff': round(float(np.mean(sharpe_diffs)), 4),
        'any_competing_signal_harvey': any_harvey,
        'vix_sufficient_all_eras': vix_sufficient_all_eras,
    },
    'conclusion': (
        f"VIX prediction R² ranges {r2_min:.4f}–{r2_max:.4f} across 5 eras (CV={r2_cv:.2f}). "
        f"{'TIME-INVARIANT' if time_invariant else 'ERA-DEPENDENT'} finding. "
        f"12/VIX strategy wins {strat_wins}/{total_eras} eras vs 50/50 baseline. "
        f"No competing signal passes Harvey t>3.0 in any era — VIX sufficiency confirmed across 33 years."
        if vix_sufficient_all_eras else
        f"VIX prediction R² ranges {r2_min:.4f}–{r2_max:.4f} across 5 eras (CV={r2_cv:.2f}). "
        f"Some competing signals have era-specific value."
    ),
    'references': [
        'K730: Cross-asset vol momentum (null)',
        'K734: VRP predictability (IS sig, OOS null)',
        'K751: Overnight VIX Δ (stat sig, econ marginal)',
        'K687: Correct lag → no VT beats BH 50/50 in Sharpe',
        'K697: VIX predicts vol magnitude not direction',
    ],
}

output_path = 'experiments/k752_vix_sufficiency_eras_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("K752 complete.")
