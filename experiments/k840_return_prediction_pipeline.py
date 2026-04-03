#!/usr/bin/env python3
"""
K840: Return Prediction → Trading Strategy Pipeline

[提出: research_program.md 開放方向, 執行: Claude]

Background:
- K818: SSVS return prediction NULL for SPY (OOS R²=-1.47%, EMH barrier)
- K818: 台灣 hit rate 62.1% 但 C2C gap artifact
- K697: VIX predicts vol magnitude (corr 0.57) but NOT direction (corr 0.04)
- EMH: daily direction accuracy > 55% is extremely difficult for SPY

Question:
  If simple signals achieve direction accuracy > 55%, can a long/cash
  strategy beat buy-and-hold?

Signals (all applied at t based on info up to t-1):
  1. VIX Change Signal: VIX dropped > 1% yesterday → risk-on → long SPY
  2. Momentum Signal: SPY cumulative 5-day return > 0 → long SPY
  3. Mean Reversion Signal: SPY return < -1% yesterday → long SPY (bounce)
  4. Combined: majority vote of 3 signals

Strategy:
  signal > 0  → 100% SPY
  signal < 0  → 0% SPY (cash)
  signal == 0 → 50% SPY

  **CRITICAL**: signal = signal.shift(1) — yesterday's signal for today's return.
  TX cost: 5bps per weight change (round-trip).

OOS: 2023-01-01 ~ 2024-12-31
Full sample: 2006-01-01 ~ 2024-12-31 (for in-sample calibration context)

Evaluation:
  - Direction hit rate (% of days signal correctly predicts up/down)
  - Sharpe ratio, CAGR, MDD
  - DM test vs BH SPY (from volpred.stats.model_evaluation)

Error Log Rules Applied:
  - signal.shift(1): mandatory, in code
  - DM test: use strategy_dm_test from volpred.stats.model_evaluation
  - Sharpe > 2x baseline = bug, stop and check
  - Sanity check: compare shift(0) vs shift(1) to detect lookahead

References:
- Welch & Goyal (2008) "A Comprehensive Look at The Empirical Performance of Equity
  Premium Prediction", RFS — EMH benchmark, most predictors fail OOS
- Rapach, Strauss & Zhou (2010) "Out-of-Sample Equity Premium Prediction: Combination
  Forecasts and Links to the Real Economy", RFS — combination forecasts
- Campbell & Thompson (2008) "Predicting Excess Stock Returns Out of Sample: Can
  Anything Beat the Historical Average?", RFS

Data: yfinance — SPY, ^VIX
Author: VolPred Research System
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
from datetime import datetime
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K840: Return Prediction → Trading Strategy Pipeline")
print("=" * 70)

# Download data
start_date = "2005-01-01"  # extra buffer for rolling calculations
end_date = "2025-01-01"

print("\n[1] Downloading SPY and VIX data...")
spy = yf.download("SPY", start=start_date, end=end_date, progress=False)
vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Build combined dataframe
df = pd.DataFrame(index=spy.index)
df['spy_close'] = spy['Close']
df['spy_return'] = spy['Close'].pct_change()
df['vix_close'] = vix['Close'].reindex(spy.index)
df['vix_return'] = df['vix_close'].pct_change()
df = df.dropna()

print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total trading days: {len(df)}")

# ============================================================
# 2. SIGNAL CONSTRUCTION
# ============================================================
print("\n[2] Constructing signals...")

# Signal 1: VIX Change Signal
# VIX dropped > 1% yesterday → risk-on → long SPY today
# Raw signal at time t: based on VIX change from t-1 to t
# Then shifted by 1 to avoid lookahead
vix_change_raw = (df['vix_return'] < -0.01).astype(int) - (df['vix_return'] > 0.01).astype(int)
# vix_change_raw[t] uses info from t (VIX close at t vs t-1)
# We need signal from t-1 for return at t
df['sig_vix_change'] = vix_change_raw.shift(1)  # CRITICAL: shift(1)

# Signal 2: Momentum Signal
# SPY cumulative 5-day return > 0 → long SPY
# Rolling 5-day return ending at t, then shift(1) for use at t+1
spy_5d_ret = df['spy_return'].rolling(5).sum()
momentum_raw = (spy_5d_ret > 0).astype(int) * 2 - 1  # +1 or -1
df['sig_momentum'] = momentum_raw.shift(1)  # CRITICAL: shift(1)

# Signal 3: Mean Reversion Signal
# SPY return < -1% → bounce expected → long SPY next day
# Raw signal: SPY dropped > 1% at time t
mean_rev_raw = (df['spy_return'] < -0.01).astype(int) - (df['spy_return'] > 0.01).astype(int)
df['sig_mean_rev'] = mean_rev_raw.shift(1)  # CRITICAL: shift(1)

# Signal 4: Combined (majority vote)
df['sig_combined'] = df[['sig_vix_change', 'sig_momentum', 'sig_mean_rev']].sum(axis=1)
# Normalize: positive → long, negative → short, zero → neutral
df['sig_combined'] = np.sign(df['sig_combined'])

# Drop NaN from rolling calculations
df = df.dropna()

print(f"  Signals constructed. Valid observations: {len(df)}")

# ============================================================
# 3. STRATEGY IMPLEMENTATION
# ============================================================
print("\n[3] Implementing strategies...")

TX_COST = 0.0005  # 5bps per weight change

def signal_to_weight(signal_series):
    """Convert signal to weight: +1→100%, -1→0%, 0→50%"""
    w = signal_series.copy()
    w = w.map({1.0: 1.0, -1.0: 0.0, 0.0: 0.5})
    # Handle any unexpected values
    w = w.fillna(0.5)
    return w

def compute_strategy_returns(weights, returns, tx_cost=TX_COST):
    """Compute strategy returns with transaction costs."""
    weight_change = weights.diff().abs().fillna(0)
    tx = weight_change * tx_cost
    strat_ret = weights * returns - tx
    return strat_ret

strategies = {}

# Strategy 0: Buy & Hold SPY (baseline)
bh_weights = pd.Series(1.0, index=df.index)
strategies['BH_SPY'] = {
    'weights': bh_weights,
    'returns': df['spy_return'] * bh_weights  # no TX for BH
}

# Strategy 1: VIX Change
w1 = signal_to_weight(df['sig_vix_change'])
strategies['VIX_Change'] = {
    'weights': w1,
    'returns': compute_strategy_returns(w1, df['spy_return'])
}

# Strategy 2: Momentum
w2 = signal_to_weight(df['sig_momentum'])
strategies['Momentum'] = {
    'weights': w2,
    'returns': compute_strategy_returns(w2, df['spy_return'])
}

# Strategy 3: Mean Reversion
w3 = signal_to_weight(df['sig_mean_rev'])
strategies['Mean_Rev'] = {
    'weights': w3,
    'returns': compute_strategy_returns(w3, df['spy_return'])
}

# Strategy 4: Combined
w4 = signal_to_weight(df['sig_combined'])
strategies['Combined'] = {
    'weights': w4,
    'returns': compute_strategy_returns(w4, df['spy_return'])
}

# ============================================================
# 4. SANITY CHECK: shift(0) vs shift(1)
# ============================================================
print("\n[4] Sanity check: lookahead detection...")

# VIX Change with NO lag (shift(0)) — should be suspiciously good
# Recompute on the already-cleaned df
vix_change_lookahead = (df['vix_return'] < -0.01).astype(int) - (df['vix_return'] > 0.01).astype(int)
w_lookahead = signal_to_weight(vix_change_lookahead)
ret_lookahead = compute_strategy_returns(w_lookahead, df['spy_return'])

# Compare OOS Sharpe
oos_mask = (df.index >= '2023-01-01') & (df.index <= '2024-12-31')
oos_df = df[oos_mask]

sharpe_lookahead = ret_lookahead[oos_mask].mean() / ret_lookahead[oos_mask].std() * np.sqrt(252)
sharpe_correct = strategies['VIX_Change']['returns'][oos_mask].mean() / strategies['VIX_Change']['returns'][oos_mask].std() * np.sqrt(252)

print(f"  VIX Change shift(0) Sharpe: {sharpe_lookahead:.4f} (LOOKAHEAD)")
print(f"  VIX Change shift(1) Sharpe: {sharpe_correct:.4f} (CORRECT)")
if sharpe_lookahead > sharpe_correct * 2:
    print("  ⚠️  shift(0) >> shift(1) — confirms lag is necessary!")
else:
    print("  shift(0) ≈ shift(1) — signal has limited same-day power")

# ============================================================
# 5. DIRECTION HIT RATE ANALYSIS
# ============================================================
print("\n[5] Direction hit rate analysis...")

def compute_hit_rate(signal, returns, mask=None):
    """Compute direction hit rate."""
    if mask is not None:
        s = signal[mask]
        r = returns[mask]
    else:
        s = signal
        r = returns

    # Only consider days with non-zero signal and non-zero return
    valid = (s != 0) & (r != 0) & s.notna() & r.notna()
    s_valid = s[valid]
    r_valid = r[valid]

    correct = ((s_valid > 0) & (r_valid > 0)) | ((s_valid < 0) & (r_valid < 0))
    hit_rate = correct.mean()
    n = len(s_valid)

    # Binomial test: H0: hit_rate = 0.5
    if n > 0:
        z_stat = (hit_rate - 0.5) / np.sqrt(0.5 * 0.5 / n)
        p_val = 2 * (1 - stats.norm.cdf(abs(z_stat)))
    else:
        z_stat = 0
        p_val = 1.0

    return {
        'hit_rate': float(hit_rate),
        'n_signals': int(n),
        'z_stat': float(z_stat),
        'p_value': float(p_val),
        'significant': bool(p_val < 0.05)
    }

# Full sample and OOS hit rates
oos_mask = (df.index >= '2023-01-01') & (df.index <= '2024-12-31')
full_mask = pd.Series(True, index=df.index)

signal_names = {
    'sig_vix_change': 'VIX Change',
    'sig_momentum': 'Momentum',
    'sig_mean_rev': 'Mean Reversion',
    'sig_combined': 'Combined'
}

hit_rate_results = {}
print(f"\n  {'Signal':<15} | {'Full HR':>8} {'(z)':>8} | {'OOS HR':>8} {'(z)':>8} | {'Sig?':>5}")
print("  " + "-" * 70)

for sig_col, sig_name in signal_names.items():
    full_hr = compute_hit_rate(df[sig_col], df['spy_return'], full_mask)
    oos_hr = compute_hit_rate(df[sig_col], df['spy_return'], oos_mask)

    hit_rate_results[sig_name] = {
        'full_sample': full_hr,
        'oos': oos_hr
    }

    print(f"  {sig_name:<15} | {full_hr['hit_rate']:>7.1%} {full_hr['z_stat']:>7.2f} | "
          f"{oos_hr['hit_rate']:>7.1%} {oos_hr['z_stat']:>7.2f} | "
          f"{'YES' if oos_hr['significant'] else 'NO':>5}")

# ============================================================
# 6. PERFORMANCE METRICS (OOS)
# ============================================================
print("\n[6] OOS Performance (2023-01-01 ~ 2024-12-31)...")

def compute_metrics(returns, name=""):
    """Compute strategy performance metrics."""
    r = returns.dropna()
    if len(r) == 0:
        return {}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # CAGR
    n_years = len(r) / 252
    total_ret = cum.iloc[-1] - 1
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    return {
        'annual_return': float(ann_ret),
        'annual_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'cagr': float(cagr),
        'mdd': float(mdd),
        'total_return': float(total_ret),
        'n_days': int(len(r))
    }

oos_metrics = {}
bh_sharpe = None

print(f"\n  {'Strategy':<15} | {'Sharpe':>8} | {'CAGR':>8} | {'MDD':>8} | {'Ann Ret':>8} | {'Ann Vol':>8}")
print("  " + "-" * 75)

for name, strat in strategies.items():
    oos_ret = strat['returns'][oos_mask]
    m = compute_metrics(oos_ret, name)
    oos_metrics[name] = m

    if name == 'BH_SPY':
        bh_sharpe = m['sharpe']

    print(f"  {name:<15} | {m['sharpe']:>8.3f} | {m['cagr']:>7.1%} | {m['mdd']:>7.1%} | "
          f"{m['annual_return']:>7.1%} | {m['annual_vol']:>7.1%}")

# Check for Sharpe > 2x baseline
print(f"\n  BH SPY Sharpe: {bh_sharpe:.3f}")
for name, m in oos_metrics.items():
    if name != 'BH_SPY' and m['sharpe'] > bh_sharpe * 2:
        print(f"  ⚠️  {name} Sharpe {m['sharpe']:.3f} > 2x baseline {bh_sharpe*2:.3f} — POSSIBLE BUG!")

# ============================================================
# 7. FULL SAMPLE PERFORMANCE (2006-2024)
# ============================================================
print("\n[7] Full Sample Performance (2006-01-01 ~ 2024-12-31)...")

full_mask_2006 = (df.index >= '2006-01-01')
full_metrics = {}

print(f"\n  {'Strategy':<15} | {'Sharpe':>8} | {'CAGR':>8} | {'MDD':>8}")
print("  " + "-" * 50)

for name, strat in strategies.items():
    full_ret = strat['returns'][full_mask_2006]
    m = compute_metrics(full_ret, name)
    full_metrics[name] = m
    print(f"  {name:<15} | {m['sharpe']:>8.3f} | {m['cagr']:>7.1%} | {m['mdd']:>7.1%}")

# ============================================================
# 8. DM TEST VS BH
# ============================================================
print("\n[8] DM Test: Each strategy vs BH SPY...")

try:
    from volpred.stats.model_evaluation import strategy_dm_test
    use_volpred_dm = True
except ImportError:
    use_volpred_dm = False
    print("  [WARN] volpred.stats.model_evaluation not available, using manual DM test")

def manual_dm_test(loss1, loss2):
    """Manual Diebold-Mariano test (negative loss = returns)."""
    d = loss1 - loss2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return {'t_stat': 0, 'p_value': 1.0}

    d_mean = d.mean()
    # HAC variance (Newey-West with auto lag)
    from statsmodels.stats.diagnostic import acorr_ljungbox
    max_lag = int(np.floor(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)  # Bartlett kernel
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * w * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n

    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))

    return {'t_stat': float(t_stat), 'p_value': float(p_value)}

dm_results = {}
bh_oos = strategies['BH_SPY']['returns'][oos_mask]

print(f"\n  {'Strategy':<15} | {'DM t-stat':>10} | {'p-value':>8} | {'Harvey sig?':>12}")
print("  " + "-" * 55)

for name in ['VIX_Change', 'Momentum', 'Mean_Rev', 'Combined']:
    strat_oos = strategies[name]['returns'][oos_mask]

    if use_volpred_dm:
        try:
            dm = strategy_dm_test(strat_oos, bh_oos)
            t_stat = dm.get('t_stat', dm.get('dm_stat', 0))
            p_val = dm.get('p_value', 1.0)
        except Exception as e:
            print(f"  volpred DM failed for {name}: {e}, using manual")
            dm = manual_dm_test(strat_oos, bh_oos)
            t_stat = dm['t_stat']
            p_val = dm['p_value']
    else:
        dm = manual_dm_test(strat_oos, bh_oos)
        t_stat = dm['t_stat']
        p_val = dm['p_value']

    harvey_sig = abs(t_stat) > 3.0
    dm_results[name] = {
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'harvey_significant': bool(harvey_sig)
    }

    print(f"  {name:<15} | {t_stat:>10.3f} | {p_val:>8.4f} | {'YES ***' if harvey_sig else 'NO':>12}")

# ============================================================
# 9. WEIGHT DISTRIBUTION & ACTIVITY
# ============================================================
print("\n[9] Strategy weight distribution (OOS)...")

print(f"\n  {'Strategy':<15} | {'% Long':>8} | {'% Cash':>8} | {'% Half':>8} | {'Turnover':>10}")
print("  " + "-" * 60)

weight_stats = {}
for name in ['VIX_Change', 'Momentum', 'Mean_Rev', 'Combined']:
    w = strategies[name]['weights'][oos_mask]
    pct_long = (w == 1.0).mean()
    pct_cash = (w == 0.0).mean()
    pct_half = (w == 0.5).mean()
    turnover = w.diff().abs().sum()  # total weight changes

    weight_stats[name] = {
        'pct_long': float(pct_long),
        'pct_cash': float(pct_cash),
        'pct_half': float(pct_half),
        'turnover': float(turnover)
    }

    print(f"  {name:<15} | {pct_long:>7.1%} | {pct_cash:>7.1%} | {pct_half:>7.1%} | {turnover:>10.1f}")

# ============================================================
# 10. CONDITIONAL ANALYSIS: Performance during high-vol vs low-vol
# ============================================================
print("\n[10] Conditional analysis: High-vol vs Low-vol regimes (OOS)...")

vix_median = df['vix_close'][oos_mask].median()
high_vol = oos_mask & (df['vix_close'] > vix_median)
low_vol = oos_mask & (df['vix_close'] <= vix_median)

print(f"\n  VIX median (OOS): {vix_median:.1f}")
print(f"\n  {'Strategy':<15} | {'Hi-Vol Sharpe':>14} | {'Lo-Vol Sharpe':>14}")
print("  " + "-" * 48)

regime_analysis = {}
for name, strat in strategies.items():
    hv_ret = strat['returns'][high_vol]
    lv_ret = strat['returns'][low_vol]

    hv_sharpe = hv_ret.mean() / hv_ret.std() * np.sqrt(252) if hv_ret.std() > 0 else 0
    lv_sharpe = lv_ret.mean() / lv_ret.std() * np.sqrt(252) if lv_ret.std() > 0 else 0

    regime_analysis[name] = {
        'high_vol_sharpe': float(hv_sharpe),
        'low_vol_sharpe': float(lv_sharpe)
    }

    print(f"  {name:<15} | {hv_sharpe:>14.3f} | {lv_sharpe:>14.3f}")

# ============================================================
# 11. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K840 Return Prediction → Trading Strategy Pipeline")
print("=" * 70)

any_beats_bh = False
for name in ['VIX_Change', 'Momentum', 'Mean_Rev', 'Combined']:
    if oos_metrics[name]['sharpe'] > oos_metrics['BH_SPY']['sharpe']:
        any_beats_bh = True
        break

print(f"\n  EMH Hypothesis: Simple signals cannot beat BH SPY on Sharpe")
print(f"  Result: {'CONFIRMED (EMH holds)' if not any_beats_bh else 'REJECTED (some signal beats BH)'}")

# Check hit rates
best_oos_hr = max(hit_rate_results[s]['oos']['hit_rate'] for s in hit_rate_results)
print(f"\n  Best OOS hit rate: {best_oos_hr:.1%}")
print(f"  55% threshold: {'PASSED' if best_oos_hr > 0.55 else 'NOT REACHED'}")

# Key finding
print(f"\n  Key Finding:")
if not any_beats_bh:
    print(f"    Even if direction accuracy approaches 50-55%, transaction costs")
    print(f"    and timing misses prevent simple signals from beating BH SPY.")
    print(f"    This confirms K818 SSVS result: EMH barrier is real for SPY.")
else:
    print(f"    Surprisingly, a simple signal beats BH. Verify no bug (Codex review).")

# ============================================================
# 12. SAVE RESULTS
# ============================================================
print("\n[12] Saving results...")

results = {
    "experiment_id": "K840",
    "title": "Return Prediction → Trading Strategy Pipeline",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "attribution": "[提出: research_program.md, 執行: Claude]",
    "data_source": "yfinance",
    "assets": ["SPY", "^VIX"],
    "data_range": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "oos_period": "2023-01-01 to 2024-12-31",
    "n_observations": int(len(df)),
    "n_oos": int(oos_mask.sum()),
    "methodology": {
        "signals": {
            "VIX_Change": "VIX dropped >1% yesterday → long SPY",
            "Momentum": "SPY 5-day cumulative return > 0 → long SPY",
            "Mean_Reversion": "SPY dropped >1% yesterday → long SPY (bounce)",
            "Combined": "Majority vote of 3 signals"
        },
        "lag": "signal.shift(1) — all signals use t-1 info for t decision",
        "tx_cost": "5bps per weight change",
        "weight_mapping": "+1→100% SPY, -1→0% SPY, 0→50% SPY"
    },
    "hit_rate_results": hit_rate_results,
    "oos_performance": oos_metrics,
    "full_sample_performance": full_metrics,
    "dm_tests_vs_bh": dm_results,
    "weight_distribution": weight_stats,
    "regime_analysis": regime_analysis,
    "sanity_check": {
        "vix_change_shift0_sharpe": float(sharpe_lookahead),
        "vix_change_shift1_sharpe": float(sharpe_correct),
        "lookahead_detected": bool(sharpe_lookahead > sharpe_correct * 1.5)
    },
    "conclusions": {
        "emh_holds": not any_beats_bh,
        "best_oos_hit_rate": float(best_oos_hr),
        "above_55pct": bool(best_oos_hr > 0.55),
        "summary": (
            "Simple direction signals (VIX change, momentum, mean reversion) fail to "
            "beat BH SPY in OOS period 2023-2024. Hit rates cluster around 50%, "
            "confirming EMH barrier for daily SPY return prediction. "
            "This validates K818 SSVS null result: daily return prediction for SPY "
            "is not economically viable with standard signals."
        ) if not any_beats_bh else (
            "Unexpected: a simple signal beats BH. Requires Codex review for bug check."
        )
    },
    "references": [
        "Welch & Goyal (2008) RFS — equity premium prediction (most predictors fail OOS)",
        "Rapach, Strauss & Zhou (2010) RFS — combination forecasts",
        "Campbell & Thompson (2008) RFS — beating historical average",
        "K818: SSVS return prediction NULL for SPY (OOS R²=-1.47%)",
        "K697: VIX predicts vol magnitude but NOT direction"
    ],
    "limitations": [
        "Only tested SPY — other assets (small-cap, EM, crypto) may differ",
        "OOS period (2023-2024) was strong bull market — may not generalize",
        "Only 3 simple signals tested — ML/NLP signals not explored",
        "No short selling — only long/cash strategy",
        "5bps TX cost assumption — actual costs vary"
    ]
}

output_path = "experiments/k840_return_prediction_pipeline_results.json"
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"  Results saved to {output_path}")
print("\nDone!")
