"""
K1061: TWSE 50 Portfolio-Level EAV Binomial Test
=================================================

Research Question:
  Does the T+1 Earnings Announcement Volatility (EAV) effect observed in K1060
  (individual stocks, 10 stocks, T+1 ratio=1.466, one-sample t=2.07, p=0.034)
  hold at the TWSE 50 portfolio level with a formal binomial test?

Key upgrade over K1060:
  - K1060: 10 stocks, binom p_t1=0.377 (6/10 > 1) -- underpowered
  - K1061: 50 TWSE constituent stocks, portfolio-level binomial test
  - Taiwan earnings are announced AFTER close -> T+1 is the correct window
  - Binomial test H0: p(ratio_t1 > 1) = 0.5 (no directional EAV)
  - If proportion > 0.6 AND binom p < 0.05 -> SUPPORTED

Hypotheses:
  H_K1061: In TWSE 50 constituents, T+1 |return| > non-event |return| (ratio > 1)
           measured by: proportion of stocks with ratio_t1 > 1, tested via binomial

Lookahead compliance:
  - event_date = announcement date (T+0); NOT used for trading
  - T+1 = next trading day after announcement (uses NEXT DAY close, no lookahead)
  - baseline excludes [T-5, T+5] window -> clean non-event sample

Random seed: 42

References:
  - Patell & Wolfson (1984) J Accounting Research -- vol increase on earnings days
  - Beaver (1968) J Accounting Research -- earnings raise vol + volume
  - Ball & Kothari (1991) Accounting Review -- event studies
  - Savor & Wilson (2016) JFQA -- earnings as systematic risk events
  - K1059 (TSMC->0050.TW NULL, T+0 ratio=1.007)
  - K1060 (10 stocks, T+1 ratio=1.466, one-sample p=0.034, binom underpowered 6/10)
"""

import numpy as np
import pandas as pd
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

import yfinance as yf

np.random.seed(42)
warnings.filterwarnings('ignore')

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
START_TIME = time.time()

# ── Configuration ─────────────────────────────────────────────────────────────
START_DATE = '2010-01-01'
END_DATE   = '2025-12-31'
EVENT_WINDOW = 5       # ±5 trading days excluded from non-event baseline
MIN_EVENTS   = 10      # minimum announcements per stock to be included
MIN_VALID_STOCKS = 30  # experiment requires at least 30 valid stocks

# TWSE 50 representative large-caps (50 tickers)
TWSE50_TICKERS = [
    '2330.TW',  # TSMC
    '2454.TW',  # MediaTek
    '2317.TW',  # Foxconn
    '2308.TW',  # Delta Electronics
    '2303.TW',  # UMC
    '2412.TW',  # Chunghwa Telecom
    '2002.TW',  # China Steel
    '2382.TW',  # Quanta Computer
    '2357.TW',  # ASUS
    '2327.TW',  # Yageo
    '1303.TW',  # Nan Ya Plastics
    '1301.TW',  # Formosa Plastics
    '1326.TW',  # Formosa Chemicals
    '2886.TW',  # Mega Financial
    '2891.TW',  # CTBC Financial
    '2882.TW',  # Cathay Financial
    '2884.TW',  # E.SUN Financial
    '2881.TW',  # Fubon Financial
    '2892.TW',  # First Financial
    '5880.TW',  # Cooperative Financial
    '2885.TW',  # Yuanta Financial
    '6505.TW',  # Formosa Petrochemical
    '1402.TW',  # Far Eastern New Century
    '2408.TW',  # Nanya Technology
    '3711.TW',  # ASMedia
    '4938.TW',  # Pegatron
    '2379.TW',  # Realtek
    '3034.TW',  # Novatek
    '2395.TW',  # Advantech
    '6669.TW',  # Wiwynn
    '2301.TW',  # Lite-On
    '2356.TW',  # Inventec
    '2324.TW',  # Compal
    '2353.TW',  # Acer
    '2880.TW',  # Hua Nan Financial
    '2883.TW',  # KGI Financial
    '2887.TW',  # Taishin Financial
    '2890.TW',  # SinoPac Financial
    '5871.TW',  # Chailease Financial
    '6415.TW',  # Silergy
    '3008.TW',  # LARGAN
    '2377.TW',  # Micro-Star International
    '2376.TW',  # Gigabyte
    '3481.TW',  # Innolux
    '2474.TW',  # Can-Fite / Catcher Technology
    '2609.TW',  # Yang Ming Marine
    '2615.TW',  # Wan Hai Lines
    '2603.TW',  # Evergreen Marine
    '9910.TW',  # Feng Tay Enterprise
    '1216.TW',  # Uni-President
]

print("=" * 70)
print("K1061: TWSE 50 Portfolio-Level EAV Binomial Test")
print("       T+1 window (Taiwan post-close announcements)")
print("=" * 70)

###############################################################################
# Part 0: Load earnings announcement data
###############################################################################
print("\n[Part 0] Loading earnings announcement data (Big5)...")

with open(DATA_FILE, 'rb') as f:
    raw_text = f.read().decode('big5', errors='replace')

lines = raw_text.strip().split('\n')
records = []
for line in lines[1:]:
    parts = line.strip().split('\t')
    if len(parts) >= 4:
        code     = parts[0].strip()
        name     = parts[1].strip()
        ym       = parts[2].strip()
        date_str = parts[3].strip()
        if date_str:
            try:
                dt = pd.Timestamp(date_str.replace('/', '-'))
                records.append({'code': code, 'name': name, 'ym': ym, 'date': dt})
            except Exception:
                pass

ea_df = pd.DataFrame(records)
print(f"Total announcement records parsed: {len(ea_df):,}")
print(f"Unique companies: {ea_df['code'].nunique():,}")

# Pre-filter to TWSE50 codes and date range
stock_codes_bare = [t.replace('.TW', '') for t in TWSE50_TICKERS]
ea_sample = ea_df[ea_df['code'].isin(stock_codes_bare)].copy()
ea_sample = ea_sample[
    (ea_sample['date'] >= START_DATE) &
    (ea_sample['date'] <= END_DATE)
]
print(f"Announcements for TWSE50 codes in {START_DATE}~{END_DATE}: {len(ea_sample)}")
print(f"Unique TWSE50 codes with announcement data: {ea_sample['code'].nunique()}")

###############################################################################
# Part 1: Download price data for all 50 stocks
###############################################################################
print("\n[Part 1] Downloading price data for TWSE 50 stocks...")
print("         (skipping tickers with no data / delisted -- not an error)")

stock_data   = {}
failed_tickers = []

for ticker in TWSE50_TICKERS:
    print(f"  {ticker}...", end=' ', flush=True)
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if df is None or len(df) == 0:
            print("EMPTY -- skip")
            failed_tickers.append((ticker, "empty"))
            continue
        # Flatten possible multi-level columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df['Close'].astype(float)
        if len(close) < 100:
            print(f"TOO FEW ROWS ({len(close)}) -- skip")
            failed_tickers.append((ticker, f"only {len(close)} rows"))
            continue
        # Log returns (no lookahead: return_t uses close_t / close_{t-1})
        ret = np.log(close / close.shift(1)).dropna()
        abs_ret = ret.abs()
        stock_data[ticker] = {
            'close':   close,
            'ret':     ret,
            'abs_ret': abs_ret,
        }
        print(f"OK N={len(ret):,}")
    except Exception as exc:
        print(f"FAIL ({exc}) -- skip")
        failed_tickers.append((ticker, str(exc)))

print(f"\nStocks loaded: {len(stock_data)}/{len(TWSE50_TICKERS)}")
if failed_tickers:
    print(f"Skipped tickers: {[t for t, _ in failed_tickers]}")

###############################################################################
# Part 2: Per-stock EAV event study (T+1 window)
###############################################################################
print("\n[Part 2] Per-stock EAV event study (T+1 window)...")

per_stock_results = {}
valid_tickers     = []
skipped_few_events = []

for ticker in stock_data:
    code = ticker.replace('.TW', '')
    info = stock_data[ticker]

    # Announcement dates for this stock
    dates_ea = ea_sample.loc[ea_sample['code'] == code, 'date'].sort_values().unique()
    dates_ea = pd.DatetimeIndex(dates_ea)

    abs_ret     = info['abs_ret']
    trading_days = abs_ret.index

    # Map each announcement date -> next trading day >= date (T+0 for this stock)
    mapped_t0 = []
    for d in dates_ea:
        pos = trading_days.searchsorted(pd.Timestamp(d))
        if pos < len(trading_days):
            mapped_t0.append(trading_days[pos])
    mapped_t0 = pd.DatetimeIndex(sorted(set(mapped_t0)))

    # T+1 = next trading day AFTER mapped_t0
    # announcement day returns are NOT used; only T+1 is the event observation
    event_positions_t0 = []
    for d in mapped_t0:
        if d in trading_days:
            event_positions_t0.append(trading_days.get_loc(d))
    event_positions_t1 = [p + 1 for p in event_positions_t0 if p + 1 < len(trading_days)]
    mapped_t1 = pd.DatetimeIndex([trading_days[p] for p in event_positions_t1])

    n_events = len(mapped_t1)  # number of usable T+1 events
    if n_events < MIN_EVENTS:
        skipped_few_events.append((ticker, n_events))
        continue

    # Non-event days: exclude [-EVENT_WINDOW, +EVENT_WINDOW] around each T+0 event
    exclusion = set()
    for pos in event_positions_t0:
        for k in range(-EVENT_WINDOW, EVENT_WINDOW + 1):
            if 0 <= pos + k < len(trading_days):
                exclusion.add(trading_days[pos + k])
    non_event_mask  = ~abs_ret.index.isin(exclusion)
    non_event_abs_r = abs_ret[non_event_mask].dropna()
    event_abs_r_t1  = abs_ret.reindex(mapped_t1).dropna()

    if len(non_event_abs_r) < 30 or len(event_abs_r_t1) < MIN_EVENTS:
        skipped_few_events.append((ticker, n_events))
        continue

    # Core ratio: mean(|r|_T+1) / mean(|r|_non-event)
    mean_event_t1  = float(event_abs_r_t1.mean())
    mean_nonevent  = float(non_event_abs_r.mean())
    ratio_t1       = mean_event_t1 / mean_nonevent if mean_nonevent > 0 else np.nan

    # Welch t-test on |r| (event T+1 vs non-event)
    if not np.isnan(ratio_t1):
        t_stat_t1, p_val_t1 = stats.ttest_ind(
            event_abs_r_t1.values,
            non_event_abs_r.values,
            equal_var=False
        )
        p_val_t1_one = float(p_val_t1 / 2) if t_stat_t1 > 0 else float(1 - p_val_t1 / 2)
    else:
        t_stat_t1, p_val_t1_one = np.nan, np.nan

    per_stock_results[ticker] = {
        'n_events_t1':        int(n_events),
        'n_nonevent_days':    int(len(non_event_abs_r)),
        'mean_abs_ret_t1':    mean_event_t1,
        'mean_abs_ret_nonevent': mean_nonevent,
        'ratio_t1':           float(ratio_t1) if not np.isnan(ratio_t1) else None,
        't_stat_t1':          float(t_stat_t1) if not np.isnan(t_stat_t1) else None,
        'p_value_t1_onesided': float(p_val_t1_one) if not np.isnan(p_val_t1_one) else None,
        'ratio_gt_1':         bool(ratio_t1 > 1.0) if not np.isnan(ratio_t1) else None,
    }
    valid_tickers.append(ticker)

print(f"\nValid stocks (>= {MIN_EVENTS} events): {len(valid_tickers)}")
if skipped_few_events:
    print(f"Skipped (too few events): {[(t, n) for t, n in skipped_few_events]}")

###############################################################################
# Part 3: Portfolio-level binomial test + pooled t-test
###############################################################################
print("\n[Part 3] Portfolio-level analysis...")

ratios_t1 = np.array([
    per_stock_results[t]['ratio_t1']
    for t in valid_tickers
    if per_stock_results[t]['ratio_t1'] is not None
])
n_valid = len(ratios_t1)
n_ratio_gt1 = int(np.sum(ratios_t1 > 1.0))
proportion_gt1 = float(n_ratio_gt1 / n_valid) if n_valid > 0 else np.nan

print(f"  N valid stocks: {n_valid}")
print(f"  Ratio > 1: {n_ratio_gt1}/{n_valid} = {proportion_gt1:.3f}")

# Binomial test: H0 p=0.5 (directional null)
try:
    from scipy.stats import binomtest
    bt = binomtest(n_ratio_gt1, n_valid, p=0.5, alternative='greater')
    binom_p = float(bt.pvalue)
except Exception:
    binom_p = float(stats.binom.sf(n_ratio_gt1 - 1, n_valid, 0.5))

print(f"  Binomial test p (one-sided, H0:p=0.5): {binom_p:.4f}")

# Portfolio-level one-sample t-test: mean(ratio_t1) > 1?
port_t_stat, port_p_raw = stats.ttest_1samp(ratios_t1, popmean=1.0)
port_p_onesided = float(port_p_raw / 2) if port_t_stat > 0 else float(1 - port_p_raw / 2)
portfolio_ratio_t1 = float(np.mean(ratios_t1))

print(f"  Portfolio mean ratio_t1: {portfolio_ratio_t1:.4f}")
print(f"  One-sample t: {port_t_stat:+.4f}, p (one-sided): {port_p_onesided:.4f}")

# Verdict
if binom_p < 0.05 and proportion_gt1 > 0.6:
    verdict = "SUPPORT"
elif binom_p < 0.10 or port_p_onesided < 0.05:
    verdict = "INCONCLUSIVE"
else:
    verdict = "FAIL"
print(f"  Verdict: {verdict}")

###############################################################################
# Part 4: Charts
###############################################################################
print("\n[Part 4] Generating charts...")

plt.rcParams.update({'figure.dpi': 120, 'savefig.dpi': 120})

# -- Chart 1: Per-stock ratio_t1 bar chart (sorted) ---------------------------
fig, ax = plt.subplots(figsize=(10, max(8, len(valid_tickers) * 0.28)))

sorted_tickers = sorted(valid_tickers,
                        key=lambda t: per_stock_results[t]['ratio_t1'] or 0)
sorted_ratios  = [per_stock_results[t]['ratio_t1'] for t in sorted_tickers]
bar_colors = ['#2E86AB' if r > 1.0 else '#E84855' for r in sorted_ratios]

y_pos = range(len(sorted_tickers))
ax.barh(y_pos, sorted_ratios, color=bar_colors, edgecolor='black', alpha=0.85)

ticker_labels = [t.replace('.TW', '') for t in sorted_tickers]
ax.set_yticks(y_pos)
ax.set_yticklabels(ticker_labels, fontsize=8)
ax.axvline(x=1.0, color='red', linestyle='--', lw=1.5, label='Ratio = 1 (no effect)')

# Annotate each bar with t-stat
for i, t in enumerate(sorted_tickers):
    r  = per_stock_results[t]['ratio_t1'] or 0
    ts = per_stock_results[t]['t_stat_t1']
    if ts is not None:
        ax.text(r + 0.01, i, f't={ts:+.2f}', va='center', fontsize=7)

ax.set_xlabel('|r|_T+1 / |r|_non-event  (ratio)', fontsize=11)
ax.set_title(
    f'K1061: TWSE 50 Stocks — EAV Ratio at T+1\n'
    f'N={n_valid} stocks | {n_ratio_gt1}/{n_valid} ratio>1 '
    f'(proportion={proportion_gt1:.2f}) | binom p={binom_p:.4f}',
    fontsize=11
)
legend_handles = [
    mpatches.Patch(color='#2E86AB', label='ratio > 1 (EAV present)'),
    mpatches.Patch(color='#E84855', label='ratio <= 1 (no EAV)'),
    Line2D([0], [0], color='red', linestyle='--', label='Ratio = 1'),
]
ax.legend(handles=legend_handles, loc='lower right', fontsize=8)
ax.grid(axis='x', alpha=0.3)

plt.tight_layout()
chart1_path = SCRIPT_DIR / 'k1061_per_stock_ratio_t1.png'
plt.savefig(chart1_path, bbox_inches='tight')
plt.close()
print(f"  saved {chart1_path.name}")

# -- Chart 2: Binomial distribution + observed proportion ---------------------
fig, axes = plt.subplots(1, 2, figsize=(13, 5))

# (a) Binomial PMF
ax = axes[0]
k_vals = np.arange(0, n_valid + 1)
pmf_vals = stats.binom.pmf(k_vals, n=n_valid, p=0.5)
ax.bar(k_vals, pmf_vals, color='#AACFCF', edgecolor='black', alpha=0.8, label='H0: p=0.5')
ax.axvline(x=n_ratio_gt1, color='red', linestyle='--', lw=2,
           label=f'Observed k={n_ratio_gt1}')
# shade critical region
crit_k = int(stats.binom.ppf(0.95, n=n_valid, p=0.5))
for k in range(crit_k + 1, n_valid + 1):
    if k <= n_valid:
        ax.bar([k], [pmf_vals[k]], color='#FF7F7F', edgecolor='black', alpha=0.8)
ax.set_xlabel('Number of stocks with ratio_t1 > 1', fontsize=10)
ax.set_ylabel('PMF (binomial, p=0.5)', fontsize=10)
ax.set_title(
    f'(a) Binomial test\n'
    f'k={n_ratio_gt1}/{n_valid}, p-val={binom_p:.4f}',
    fontsize=10
)
ax.legend(fontsize=9)
ax.grid(axis='y', alpha=0.3)

# (b) Distribution of ratio_t1 across stocks
ax = axes[1]
ax.hist(ratios_t1, bins=15, color='#2E86AB', edgecolor='black', alpha=0.75)
ax.axvline(x=1.0, color='red', linestyle='--', lw=2, label='Ratio=1')
ax.axvline(x=portfolio_ratio_t1, color='green', linestyle='-', lw=2,
           label=f'Portfolio mean={portfolio_ratio_t1:.3f}')
ax.set_xlabel('ratio_t1 (per stock)', fontsize=10)
ax.set_ylabel('Count', fontsize=10)
ax.set_title(
    f'(b) Distribution of ratio_t1 across {n_valid} stocks\n'
    f'mean={portfolio_ratio_t1:.3f}, t={port_t_stat:+.3f}, p={port_p_onesided:.4f}',
    fontsize=10
)
ax.legend(fontsize=9)
ax.grid(axis='y', alpha=0.3)

fig.suptitle('K1061: Portfolio-Level EAV — TWSE 50, T+1 Window (2010-2025)',
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.95])
chart2_path = SCRIPT_DIR / 'k1061_binomial_distribution.png'
plt.savefig(chart2_path, bbox_inches='tight')
plt.close()
print(f"  saved {chart2_path.name}")

###############################################################################
# Part 5: Save results JSON
###############################################################################
elapsed = time.time() - START_TIME
now_iso = datetime.now(timezone.utc).isoformat()

results = {
    "experiment_id": "K1061",
    "title": "TWSE 50 Portfolio-Level EAV Binomial Test (T+1 Window)",
    "proposer": "Claude",
    "executor": "Claude",
    "timestamp_utc": now_iso,
    "runtime_seconds": round(elapsed, 1),
    "random_seed": 42,
    "config": {
        "sample_period": f"{START_DATE} to {END_DATE}",
        "event_window_exclusion_days": EVENT_WINDOW,
        "min_events_per_stock": MIN_EVENTS,
        "tickers_attempted": len(TWSE50_TICKERS),
        "failed_download": [t for t, _ in failed_tickers] if failed_tickers else [],
        "skipped_few_events": [t for t, _ in skipped_few_events] if skipped_few_events else [],
    },
    # Primary outputs (matching task-specified JSON schema)
    "n_stocks_valid": n_valid,
    "n_stocks_ratio_gt1": n_ratio_gt1,
    "proportion_ratio_gt1": proportion_gt1,
    "binomial_p": binom_p,
    "portfolio_ratio_t1": portfolio_ratio_t1,
    "portfolio_t_stat": float(port_t_stat),
    "portfolio_p_value": port_p_onesided,
    "verdict": verdict,
    # K1060 comparison anchor
    "k1060_comparison": {
        "k1060_n_stocks": 10,
        "k1060_mean_ratio_t1": 1.465650220696459,
        "k1060_proportion_gt1": 0.6,
        "k1060_binom_p_t1": 0.376953125,
        "k1060_one_sample_p": 0.033906369982211935,
        "k1060_verdict": "WEAK (underpowered binom)",
    },
    "per_stock_results": per_stock_results,
    "metadata": {
        "data_file": str(DATA_FILE),
        "announcement_records_total": len(ea_df),
        "announcement_records_sample": len(ea_sample),
        "lookahead_check": (
            "T+1 = next trading day AFTER announcement close; "
            "baseline excludes [T-5,T+5]; no lookahead."
        ),
        "chart_files": [
            "k1061_per_stock_ratio_t1.png",
            "k1061_binomial_distribution.png",
        ],
        "references": [
            "Patell & Wolfson (1984) J Accounting Research",
            "Beaver (1968) J Accounting Research",
            "Savor & Wilson (2016) JFQA",
            "Ball & Kothari (1991) Accounting Review",
            "K1059 (TSMC -> 0050.TW NULL, T+0 ratio=1.007)",
            "K1060 (10 stocks, T+1 ratio=1.466, binom underpowered 6/10)",
        ],
    },
}

out_path = SCRIPT_DIR / 'k1061_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\nResults saved to {out_path}")

###############################################################################
# Summary
###############################################################################
print("\n" + "=" * 70)
print(f"K1061 done. Elapsed: {elapsed:.1f}s")
print(f"  N valid stocks : {n_valid}")
print(f"  Ratio > 1      : {n_ratio_gt1}/{n_valid} = {proportion_gt1:.3f}")
print(f"  Binomial p     : {binom_p:.4f}")
print(f"  Portfolio mean : {portfolio_ratio_t1:.4f}")
print(f"  Portfolio t    : {port_t_stat:+.4f}  p(one-sided): {port_p_onesided:.4f}")
print(f"  VERDICT        : {verdict}")
print("=" * 70)
