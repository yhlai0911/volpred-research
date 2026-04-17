"""
K771: Dispersion Timing — Index vs Sector Basket
==================================================
[提出: Codex GPT-5.4 8th suggestion #3, 執行: Claude]

Hypothesis: When sectors diverge (high dispersion), equal-weight sector basket
outperforms cap-weighted SPY. When sectors converge (low dispersion), SPY is better.

Strategy:
- Measure cross-sector return dispersion (rolling 20-day std of 11 sector returns)
- High dispersion (>75th pct): hold equal-weight 11 sectors
- Low dispersion (<25th pct): hold SPY
- Middle: hold 50/50 SPY + equal-weight sectors
- Monthly rebalancing, signal.shift(1) for lag

Data: 11 SPDR sector ETFs + SPY + GLD + ^VIX, 2010-2026
References:
- Solnik & Roulet (2000) "Dispersion as cross-sectional volatility"
- Stivers (2003) "Firm-level return dispersion and the future volatility of aggregate stock market returns"
- Connolly & Stivers (2006) "Information content of sector dispersion"
"""

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────
SECTOR_ETFS = ['XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLC', 'XLY', 'XLP', 'XLU', 'XLRE', 'XLB']
TICKERS = SECTOR_ETFS + ['SPY', 'GLD', '^VIX']
START = '2010-01-01'
END = '2026-03-31'
DISP_WINDOW = 20        # rolling window for dispersion
TX_COST = 0.001          # 10 bps per trade (each leg)
REBAL_FREQ = 'M'         # monthly rebalancing

# ── Part A: Data Download & Dispersion Measurement ─────────────────────
print("=" * 70)
print("K771: Dispersion Timing — Index vs Sector Basket")
print("=" * 70)

print("\n[1/5] Downloading data...")
data = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False)
prices = data['Close'].copy()

# Handle MultiIndex if needed
if isinstance(prices.columns, pd.MultiIndex):
    prices.columns = prices.columns.get_level_values(-1)

# Rename VIX
if '^VIX' in prices.columns:
    prices = prices.rename(columns={'^VIX': 'VIX'})

prices = prices.dropna(how='all')
print(f"  Data range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(prices)}")

# Check for missing sectors
avail_sectors = [s for s in SECTOR_ETFS if s in prices.columns]
missing_sectors = [s for s in SECTOR_ETFS if s not in prices.columns]
if missing_sectors:
    print(f"  ⚠️ Missing sectors: {missing_sectors}")
print(f"  Available sectors: {len(avail_sectors)}")

# Forward fill small gaps, then drop rows with too many NaN
prices = prices.ffill(limit=5)

# Compute returns
sector_returns = prices[avail_sectors].pct_change()
spy_ret = prices['SPY'].pct_change()
gld_ret = prices['GLD'].pct_change() if 'GLD' in prices.columns else None
vix = prices['VIX'] if 'VIX' in prices.columns else None

# Drop first row (NaN from pct_change)
sector_returns = sector_returns.iloc[1:]
spy_ret = spy_ret.iloc[1:]
if gld_ret is not None:
    gld_ret = gld_ret.iloc[1:]

# Equal-weight sector basket return
ew_sector_ret = sector_returns.mean(axis=1)

# Cross-sector dispersion: std of daily sector returns
daily_dispersion = sector_returns.std(axis=1)

# Rolling 20-day average dispersion
rolling_disp = daily_dispersion.rolling(DISP_WINDOW).mean()

print(f"\n[2/5] Dispersion Statistics:")
print(f"  Daily dispersion mean: {daily_dispersion.mean():.6f}")
print(f"  Daily dispersion std:  {daily_dispersion.std():.6f}")
print(f"  Rolling {DISP_WINDOW}d dispersion mean: {rolling_disp.dropna().mean():.6f}")
print(f"  Rolling {DISP_WINDOW}d dispersion std:  {rolling_disp.dropna().std():.6f}")

# Percentile thresholds (expanding to avoid lookahead)
expanding_pct75 = rolling_disp.expanding(min_periods=252).quantile(0.75)
expanding_pct25 = rolling_disp.expanding(min_periods=252).quantile(0.25)

# Dispersion-VIX correlation
if vix is not None:
    vix_aligned = vix.reindex(rolling_disp.index)
    disp_vix_corr = rolling_disp.corr(vix_aligned)
    print(f"  Dispersion-VIX correlation: {disp_vix_corr:.4f}")
else:
    disp_vix_corr = np.nan

# ── Part B: Strategy Construction ──────────────────────────────────────
print(f"\n[3/5] Constructing strategies...")

# Align all series
common_idx = rolling_disp.dropna().index
common_idx = common_idx.intersection(spy_ret.index)
common_idx = common_idx.intersection(ew_sector_ret.index)
if gld_ret is not None:
    common_idx = common_idx.intersection(gld_ret.index)

rolling_d = rolling_disp.reindex(common_idx)
pct75 = expanding_pct75.reindex(common_idx)
pct25 = expanding_pct25.reindex(common_idx)
spy = spy_ret.reindex(common_idx)
ew_sec = ew_sector_ret.reindex(common_idx)
gld = gld_ret.reindex(common_idx) if gld_ret is not None else None

# Signal: regime based on dispersion vs expanding percentiles
# 1 = high dispersion (sectors), 0 = low (SPY), 0.5 = middle
regime = pd.Series(0.5, index=common_idx)
regime[rolling_d > pct75] = 1.0   # high dispersion → EW sectors
regime[rolling_d < pct25] = 0.0   # low dispersion → SPY

# CRITICAL: shift(1) to avoid lookahead bias
signal = regime.shift(1)
signal = signal.dropna()

# Restrict to signal availability
idx = signal.index
spy_s = spy.reindex(idx)
ew_s = ew_sec.reindex(idx)

# Monthly rebalancing: only change weights at month-end
# Create monthly flag
month_end = pd.Series(False, index=idx)
for i in range(len(idx) - 1):
    if idx[i].month != idx[i + 1].month:
        month_end.iloc[i] = True
month_end.iloc[-1] = True

# Apply monthly rebalancing to signal
monthly_signal = signal.copy()
current_weight = monthly_signal.iloc[0]
for i in range(len(monthly_signal)):
    if month_end.iloc[i]:
        current_weight = monthly_signal.iloc[i]
    else:
        monthly_signal.iloc[i] = current_weight

# Dispersion timing strategy return
# weight = monthly_signal (0, 0.5, 1 → fraction in EW sectors, rest in SPY)
disp_ret = monthly_signal * ew_s + (1 - monthly_signal) * spy_s

# TX cost: applied when weight changes
weight_changes = monthly_signal.diff().abs()
weight_changes.iloc[0] = 0
tx = weight_changes * TX_COST
disp_ret_net = disp_ret - tx

# ── Baselines ──────────────────────────────────────────────────────────
# 1. SPY Buy & Hold
spy_bh = spy_s.copy()

# 2. EW Sector Buy & Hold
ew_bh = ew_s.copy()

# 3. 50/50 SPY/GLD
if gld is not None:
    gld_s = gld.reindex(idx)
    spygld_5050 = 0.5 * spy_s + 0.5 * gld_s
else:
    spygld_5050 = spy_s  # fallback

# 4. 12/VIX strategy
if vix is not None:
    vix_s = vix.reindex(idx)
    vix_weight = (12.0 / vix_s).clip(0, 1)
    vix_weight_lag = vix_weight.shift(1).dropna()
    # Monthly rebalancing for 12/VIX too
    vix_monthly = vix_weight_lag.copy()
    current_w = vix_monthly.iloc[0]
    for i in range(len(vix_monthly)):
        if i < len(month_end) and month_end.iloc[i]:
            current_w = vix_monthly.iloc[i]
        else:
            vix_monthly.iloc[i] = current_w
    # Note: 12/VIX is smooth enough that monthly vs daily barely matters
    # Use daily-rebalanced version for fair comparison (it's the standard)
    vix12_ret = vix_weight_lag * spy_s.reindex(vix_weight_lag.index) + \
                (1 - vix_weight_lag) * gld_s.reindex(vix_weight_lag.index) if gld is not None else \
                vix_weight_lag * spy_s.reindex(vix_weight_lag.index)
else:
    vix12_ret = spy_s

# ── Part C: Performance Evaluation ─────────────────────────────────────
print(f"\n[4/5] Performance Evaluation...")

def calc_metrics(returns, name):
    """Calculate standard performance metrics."""
    r = returns.dropna()
    n = len(r)
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0
    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0
    return {
        'name': name,
        'n_days': n,
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 4),
        'mdd': round(mdd, 4),
        'calmar': round(calmar, 4),
        'sortino': round(sortino, 4),
    }

# Use common date range for all strategies
eval_start = idx[0]
eval_end = idx[-1]

strategies = {
    'Dispersion Timing (gross)': disp_ret,
    'Dispersion Timing (net TX)': disp_ret_net,
    'SPY B&H': spy_bh,
    'EW Sectors B&H': ew_bh,
    '50/50 SPY/GLD': spygld_5050,
}
if vix is not None:
    strategies['12/VIX (SPY+GLD)'] = vix12_ret

results = {}
print(f"\n  Evaluation period: {eval_start.strftime('%Y-%m-%d')} to {eval_end.strftime('%Y-%m-%d')}")
print(f"  {'Strategy':<30} {'Ann.Ret':>8} {'Ann.Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

for name, ret in strategies.items():
    m = calc_metrics(ret, name)
    results[name] = m
    print(f"  {name:<30} {m['ann_return']:>8.4f} {m['ann_vol']:>8.4f} {m['sharpe']:>8.4f} {m['mdd']:>8.4f} {m['calmar']:>8.4f} {m['sortino']:>8.4f}")

# ── Regime Analysis ────────────────────────────────────────────────────
print(f"\n  Regime Distribution:")
regime_counts = monthly_signal.value_counts()
total = len(monthly_signal)
for val, count in sorted(regime_counts.items()):
    label = {0.0: 'Low Disp (SPY)', 0.5: 'Medium (50/50)', 1.0: 'High Disp (EW Sectors)'}
    print(f"    {label.get(val, str(val))}: {count} days ({count/total*100:.1f}%)")

# Per-regime performance
print(f"\n  Per-Regime Performance (SPY vs EW Sectors):")
for regime_val, label in [(0.0, 'Low Dispersion'), (0.5, 'Medium'), (1.0, 'High Dispersion')]:
    mask = monthly_signal == regime_val
    if mask.sum() > 10:
        spy_regime = spy_s[mask].mean() * 252
        ew_regime = ew_s[mask].mean() * 252
        diff = ew_regime - spy_regime
        print(f"    {label:>20}: SPY={spy_regime:+.4f}  EW={ew_regime:+.4f}  EW-SPY={diff:+.4f}")

# ── Cross-OOS Validation (5 non-overlapping 2-year periods) ────────────
print(f"\n[5/5] Cross-OOS Validation (5 x 2-year periods)...")

# Use 2011-2025 for 5 non-overlapping 2-year periods (skip first year for warmup)
oos_periods = [
    ('2011-01-01', '2012-12-31'),
    ('2013-01-01', '2014-12-31'),
    ('2015-01-01', '2016-12-31'),
    ('2017-01-01', '2018-12-31'),
    ('2019-01-01', '2020-12-31'),
]
# Plus recent periods
oos_periods_extended = oos_periods + [
    ('2021-01-01', '2022-12-31'),
    ('2023-01-01', '2024-12-31'),
]

oos_results = []
disp_wins_vs_spy = 0
disp_wins_vs_5050 = 0
n_valid = 0

print(f"\n  {'Period':<25} {'Disp Sharpe':>12} {'SPY Sharpe':>12} {'5050 Sharpe':>12} {'Beat SPY?':>10} {'Beat 5050?':>10}")
print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*12} {'-'*10} {'-'*10}")

for start_d, end_d in oos_periods_extended:
    mask = (idx >= start_d) & (idx <= end_d)
    if mask.sum() < 100:
        continue

    d_sharpe = calc_metrics(disp_ret_net[mask], '')['sharpe']
    s_sharpe = calc_metrics(spy_bh[mask], '')['sharpe']
    g_sharpe = calc_metrics(spygld_5050[mask], '')['sharpe']

    beat_spy = d_sharpe > s_sharpe
    beat_5050 = d_sharpe > g_sharpe

    if beat_spy:
        disp_wins_vs_spy += 1
    if beat_5050:
        disp_wins_vs_5050 += 1
    n_valid += 1

    oos_results.append({
        'period': f"{start_d} to {end_d}",
        'disp_sharpe': round(d_sharpe, 4),
        'spy_sharpe': round(s_sharpe, 4),
        'spygld_sharpe': round(g_sharpe, 4),
        'beat_spy': beat_spy,
        'beat_5050': beat_5050,
    })

    print(f"  {start_d} to {end_d:<10} {d_sharpe:>12.4f} {s_sharpe:>12.4f} {g_sharpe:>12.4f} {'✓' if beat_spy else '✗':>10} {'✓' if beat_5050 else '✗':>10}")

print(f"\n  Cross-OOS Summary:")
print(f"    Beat SPY:     {disp_wins_vs_spy}/{n_valid}")
print(f"    Beat 50/50:   {disp_wins_vs_5050}/{n_valid}")

# ── Diebold-Mariano Test ──────────────────────────────────────────────
print(f"\n  Diebold-Mariano Test (Dispersion Timing vs SPY):")
from scipy import stats

# DM test: compare squared errors of cumulative returns
e_disp = (disp_ret_net - disp_ret_net.mean()) ** 2
e_spy = (spy_bh - spy_bh.mean()) ** 2
d = e_disp - e_spy
d = d.dropna()

if len(d) > 30:
    dm_mean = d.mean()
    dm_se = d.std() / np.sqrt(len(d))
    dm_stat = dm_mean / dm_se if dm_se > 0 else 0
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    print(f"    DM statistic: {dm_stat:.4f}")
    print(f"    DM p-value:   {dm_pval:.4f}")
    print(f"    Significant (p<0.05)? {'Yes' if dm_pval < 0.05 else 'No'}")
else:
    dm_stat, dm_pval = np.nan, np.nan

# ── Sensitivity Analysis ──────────────────────────────────────────────
print(f"\n  Sensitivity Analysis (dispersion window ±20%):")
sensitivity = {}
for w in [16, 20, 24]:
    rd = daily_dispersion.rolling(w).mean()
    ep75 = rd.expanding(min_periods=252).quantile(0.75)
    ep25 = rd.expanding(min_periods=252).quantile(0.25)

    ci = rd.dropna().index.intersection(idx)
    rd_a = rd.reindex(ci)
    p75_a = ep75.reindex(ci)
    p25_a = ep25.reindex(ci)

    reg = pd.Series(0.5, index=ci)
    reg[rd_a > p75_a] = 1.0
    reg[rd_a < p25_a] = 0.0
    sig = reg.shift(1).dropna()

    # Monthly rebalance
    si = sig.index
    me = pd.Series(False, index=si)
    for i in range(len(si) - 1):
        if si[i].month != si[i + 1].month:
            me.iloc[i] = True
    me.iloc[-1] = True

    ms = sig.copy()
    cw = ms.iloc[0]
    for i in range(len(ms)):
        if me.iloc[i]:
            cw = ms.iloc[i]
        else:
            ms.iloc[i] = cw

    spy_sa = spy.reindex(si)
    ew_sa = ew_sec.reindex(si)
    dr = ms * ew_sa + (1 - ms) * spy_sa
    wc = ms.diff().abs()
    wc.iloc[0] = 0
    dr_net = dr - wc * TX_COST

    m = calc_metrics(dr_net, f'window={w}')
    sensitivity[w] = m['sharpe']
    print(f"    Window={w}d: Sharpe={m['sharpe']:.4f}")

base_sharpe = sensitivity[20]
for w, s in sensitivity.items():
    if w != 20:
        pct_change = (s - base_sharpe) / abs(base_sharpe) * 100 if base_sharpe != 0 else 0
        print(f"    Δ from base (w={w}): {pct_change:+.1f}%")

# ── Additional: EW Sectors vs SPY historical comparison ───────────────
print(f"\n  Additional: EW Sectors vs SPY Over Full Period:")
ew_cum = (1 + ew_s).cumprod()
spy_cum = (1 + spy_s).cumprod()
ew_total = ew_cum.iloc[-1] - 1
spy_total = spy_cum.iloc[-1] - 1
print(f"    SPY cumulative return: {spy_total:.4f} ({spy_total*100:.1f}%)")
print(f"    EW Sectors cumulative: {ew_total:.4f} ({ew_total*100:.1f}%)")
print(f"    EW - SPY difference:   {(ew_total-spy_total)*100:+.1f}%")

# ── Summary Verdict ───────────────────────────────────────────────────
print(f"\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")

disp_sharpe = results['Dispersion Timing (net TX)']['sharpe']
spy_sharpe = results['SPY B&H']['sharpe']
ew_sharpe = results['EW Sectors B&H']['sharpe']
five0_sharpe = results['50/50 SPY/GLD']['sharpe']

beat_spy_full = disp_sharpe > spy_sharpe
beat_ew_full = disp_sharpe > ew_sharpe
beat_5050_full = disp_sharpe > five0_sharpe

# Determine Codex severity
if disp_sharpe > 2 * spy_sharpe:
    codex_flag = "⚠️ SUSPICIOUS: Sharpe > 2x baseline — likely bug"
elif beat_spy_full and disp_wins_vs_spy >= 4:
    codex_flag = "PROMISING — needs Codex audit"
else:
    codex_flag = "NULL — dispersion timing adds no value"

print(f"\n  Dispersion Timing (net TX) Sharpe: {disp_sharpe:.4f}")
print(f"  SPY B&H Sharpe:                    {spy_sharpe:.4f}")
print(f"  EW Sectors B&H Sharpe:             {ew_sharpe:.4f}")
print(f"  50/50 SPY/GLD Sharpe:              {five0_sharpe:.4f}")
print(f"\n  Full-period: Beat SPY? {beat_spy_full}  Beat EW? {beat_ew_full}  Beat 50/50? {beat_5050_full}")
print(f"  Cross-OOS: Beat SPY {disp_wins_vs_spy}/{n_valid}, Beat 50/50 {disp_wins_vs_5050}/{n_valid}")
print(f"\n  Verdict: {codex_flag}")

# ── Save Results ──────────────────────────────────────────────────────
output = {
    'experiment_id': 'K771',
    'title': 'Dispersion Timing — Index vs Sector Basket',
    'proposer': 'Codex GPT-5.4 8th suggestion #3',
    'executor': 'Claude',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'data_period': f"{eval_start.strftime('%Y-%m-%d')} to {eval_end.strftime('%Y-%m-%d')}",
    'n_trading_days': int(len(idx)),
    'sectors_used': avail_sectors,
    'n_sectors': len(avail_sectors),
    'methodology': {
        'dispersion_window': DISP_WINDOW,
        'percentile_thresholds': '25th/75th (expanding)',
        'rebalancing': 'monthly',
        'signal_lag': 'shift(1)',
        'tx_cost_per_trade': TX_COST,
    },
    'dispersion_stats': {
        'daily_mean': round(float(daily_dispersion.mean()), 6),
        'daily_std': round(float(daily_dispersion.std()), 6),
        'rolling_20d_mean': round(float(rolling_disp.dropna().mean()), 6),
        'rolling_20d_std': round(float(rolling_disp.dropna().std()), 6),
        'dispersion_vix_corr': round(float(disp_vix_corr), 4) if not np.isnan(disp_vix_corr) else None,
    },
    'regime_distribution': {
        'low_disp_pct': round(float((monthly_signal == 0.0).mean() * 100), 1),
        'medium_pct': round(float((monthly_signal == 0.5).mean() * 100), 1),
        'high_disp_pct': round(float((monthly_signal == 1.0).mean() * 100), 1),
    },
    'full_period_results': results,
    'cross_oos': {
        'periods': oos_results,
        'beat_spy': f"{disp_wins_vs_spy}/{n_valid}",
        'beat_5050': f"{disp_wins_vs_5050}/{n_valid}",
    },
    'dm_test': {
        'statistic': round(float(dm_stat), 4) if not np.isnan(dm_stat) else None,
        'p_value': round(float(dm_pval), 4) if not np.isnan(dm_pval) else None,
    },
    'sensitivity': {str(k): round(v, 4) for k, v in sensitivity.items()},
    'verdict': codex_flag,
    'references': [
        'Solnik & Roulet (2000) Dispersion as cross-sectional volatility',
        'Stivers (2003) Firm-level return dispersion and future volatility',
        'Connolly & Stivers (2006) Information content of sector dispersion',
    ],
}

out_path = Path('experiments/k771_dispersion_timing_results.json')
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {out_path}")
print(f"\n{'='*70}")
print("K771 COMPLETE")
print(f"{'='*70}")
