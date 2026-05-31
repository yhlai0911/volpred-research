"""
AI CapEx vs Realized Volatility — Evidence Package Script
Task: trending_repost_2026_06_01_ai資本
Date: 2026-06-01

Fetches MSFT and META:
- 24 months daily close → rolling 30D realized vol (HV)
- Quarterly CapEx from yfinance (cash_flow statement)
- IV proxy: HV30 (options chain mid-prices not reliably available via yfinance free tier)

Output:
- raw_data.csv: daily OHLCV + HV30
- quarterly_summary.csv: quarterly CapEx + average HV30 per quarter
- capex_hv_chart.png: dual-axis bar+line chart
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ── Config ──────────────────────────────────────────────────────────────
TICKERS = ['MSFT', 'META']
START = '2024-01-01'
END = '2026-05-31'
HV_WINDOW = 30  # days
OUT_DIR = Path(__file__).parent

# ── 1. Download daily close ──────────────────────────────────────────────
print("Downloading daily price data...")
raw_frames = {}
for ticker in TICKERS:
    t = yf.Ticker(ticker)
    df = t.history(start=START, end=END, auto_adjust=True)
    df = df[['Close']].rename(columns={'Close': ticker})
    raw_frames[ticker] = df

prices = pd.concat(raw_frames.values(), axis=1)
prices.index = prices.index.tz_localize(None)
prices.index.name = 'Date'
print(f"Price data shape: {prices.shape}")
print(prices.tail(3))

# ── 2. Rolling 30D HV (annualized) ──────────────────────────────────────
log_ret = np.log(prices / prices.shift(1))
hv30 = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252) * 100  # in %
hv30.columns = [f'{c}_HV30' for c in hv30.columns]

daily = pd.concat([prices, hv30], axis=1).dropna()
daily.to_csv(OUT_DIR / 'raw_data.csv')
print(f"\nDaily data saved ({len(daily)} rows)")

# ── 3. Quarterly CapEx from yfinance ────────────────────────────────────
print("\nFetching quarterly CapEx...")
capex_data = {}
for ticker in TICKERS:
    t = yf.Ticker(ticker)
    try:
        cf = t.quarterly_cashflow
        print(f"\n{ticker} cash flow index sample:", cf.index[:5].tolist())
        # CapEx is typically labeled 'Capital Expenditure' or 'Purchase Of Property Plant And Equipment'
        capex_row = None
        for label in ['Capital Expenditure', 'Purchase Of Property Plant And Equipment',
                      'Capital Expenditures', 'CapEx', 'capital_expenditure']:
            if label in cf.index:
                capex_row = cf.loc[label]
                print(f"  Found CapEx row: '{label}'")
                break
        if capex_row is None:
            # Try case-insensitive search
            matches = [idx for idx in cf.index if 'capital' in idx.lower() or 'property' in idx.lower()]
            print(f"  Possible CapEx rows: {matches}")
            if matches:
                capex_row = cf.loc[matches[0]]
                print(f"  Using: {matches[0]}")

        if capex_row is not None:
            # CapEx is negative in cash flow (outflow), take abs
            capex_series = capex_row.abs() / 1e9  # convert to billions
            capex_series = capex_series.sort_index()
            capex_data[ticker] = capex_series
            print(f"  {ticker} CapEx (recent quarters):\n{capex_series.tail(8)}")
        else:
            print(f"  WARNING: Could not find CapEx for {ticker}")
            print(f"  Available rows: {cf.index.tolist()}")
    except Exception as e:
        print(f"  ERROR fetching {ticker} cash flow: {e}")

# ── 4. Build quarterly summary ──────────────────────────────────────────
print("\nBuilding quarterly summary...")

# Assign quarters to daily data
daily_indexed = daily.copy()
daily_indexed['Quarter'] = daily_indexed.index.to_period('Q')

quarterly_hv = daily_indexed.groupby('Quarter').agg(
    MSFT_HV30_mean=('MSFT_HV30', 'mean'),
    META_HV30_mean=('META_HV30', 'mean'),
    MSFT_HV30_std=('MSFT_HV30', 'std'),
    META_HV30_std=('META_HV30', 'std'),
)

# Build combined quarterly table
rows = []
for ticker in TICKERS:
    if ticker not in capex_data:
        continue
    capex_s = capex_data[ticker]
    hv_col = f'{ticker}_HV30_mean'

    for col_date in capex_s.index:
        try:
            q = pd.Period(col_date, freq='Q')
            qstr = str(q)
            hv_val = quarterly_hv.loc[q, hv_col] if q in quarterly_hv.index else np.nan
            rows.append({
                'Ticker': ticker,
                'Quarter': qstr,
                'CapEx_Bn': round(capex_s[col_date], 2),
                'HV30_pct_mean': round(hv_val, 1) if not np.isnan(hv_val) else np.nan,
            })
        except Exception as e:
            pass

qdf = pd.DataFrame(rows).sort_values(['Ticker', 'Quarter'])
# Filter to available period
qdf = qdf[qdf['Quarter'] >= '2024Q1'].dropna()
qdf.to_csv(OUT_DIR / 'quarterly_summary.csv', index=False)
print(qdf.to_string())

# ── 5. Compute YoY CapEx growth ─────────────────────────────────────────
print("\n--- YoY CapEx growth ---")
for ticker in TICKERS:
    sub = qdf[qdf['Ticker'] == ticker].set_index('Quarter').sort_index()
    if len(sub) >= 5:
        # Find 4-quarter-ago equivalent
        quarters = sub.index.tolist()
        for i, q in enumerate(quarters):
            if i >= 4:
                yoy = (sub.loc[q, 'CapEx_Bn'] - sub.loc[quarters[i-4], 'CapEx_Bn']) / sub.loc[quarters[i-4], 'CapEx_Bn'] * 100
                hv_now = sub.loc[q, 'HV30_pct_mean']
                hv_year_ago = sub.loc[quarters[i-4], 'HV30_pct_mean']
                hv_change = hv_now - hv_year_ago if not (np.isnan(hv_now) or np.isnan(hv_year_ago)) else np.nan
                print(f"  {ticker} {q}: CapEx YoY = +{yoy:.1f}%, HV30 change = {hv_change:+.1f}pp")

# ── 6. Chart: CapEx bar + HV30 line (dual axis) ─────────────────────────
print("\nGenerating chart...")

fig, axes = plt.subplots(2, 1, figsize=(12, 10))
fig.suptitle('AI 巨頭季度資本支出 vs 30日已實現波動率 (2024-2026)',
             fontsize=14, fontweight='bold', y=0.98)

colors_capex = {'MSFT': '#0078D4', 'META': '#1877F2'}
colors_hv = {'MSFT': '#FF6B35', 'META': '#E8175D'}

for ax_idx, ticker in enumerate(TICKERS):
    ax1 = axes[ax_idx]
    sub = qdf[qdf['Ticker'] == ticker].copy()

    if len(sub) == 0:
        ax1.set_title(f'{ticker}: No data available')
        continue

    quarters = sub['Quarter'].tolist()
    x = np.arange(len(quarters))
    width = 0.6

    # Bar: CapEx
    bars = ax1.bar(x, sub['CapEx_Bn'], width, color=colors_capex[ticker],
                   alpha=0.75, label='季度資本支出 (十億美元)')
    ax1.set_ylabel('資本支出（十億美元）', color=colors_capex[ticker], fontsize=10)
    ax1.tick_params(axis='y', labelcolor=colors_capex[ticker])
    ax1.set_xticks(x)
    ax1.set_xticklabels(quarters, rotation=30, ha='right', fontsize=9)

    # Add value labels on bars
    for bar_item in bars:
        h = bar_item.get_height()
        ax1.text(bar_item.get_x() + bar_item.get_width()/2., h + 0.05,
                 f'${h:.1f}B', ha='center', va='bottom', fontsize=8)

    # Line: HV30 on secondary axis
    ax2 = ax1.twinx()
    hv_vals = sub['HV30_pct_mean'].tolist()
    ax2.plot(x, hv_vals, 'o-', color=colors_hv[ticker], linewidth=2,
             markersize=6, label='30D 已實現波動率 (%)')
    ax2.set_ylabel('30D 已實現波動率 (%)', color=colors_hv[ticker], fontsize=10)
    ax2.tick_params(axis='y', labelcolor=colors_hv[ticker])

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)

    ax1.set_title(f'{ticker}', fontsize=12, fontweight='bold')
    ax1.grid(axis='y', alpha=0.3, linestyle='--')
    ax1.set_xlabel('')

plt.tight_layout(rect=[0, 0, 1, 0.96])

# Save to multiple locations
chart_path_exp = OUT_DIR / 'capex_hv_chart.png'
chart_path_assets = Path('/Users/yhlai0911/Desktop/volpred-research/storage/reports/assets/ai_capex_iv_2026_06.png')
plt.savefig(chart_path_exp, dpi=150, bbox_inches='tight')
plt.savefig(chart_path_assets, dpi=150, bbox_inches='tight')
print(f"Chart saved to {chart_path_exp}")
print(f"Chart saved to {chart_path_assets}")

plt.close()

# ── 7. Summary statistics for article ───────────────────────────────────
print("\n=== SUMMARY FOR ARTICLE ===")
for ticker in TICKERS:
    sub = qdf[qdf['Ticker'] == ticker].set_index('Quarter').sort_index()
    if len(sub) == 0:
        print(f"{ticker}: No quarterly data")
        continue
    latest_q = sub.index[-1]
    latest_capex = sub.loc[latest_q, 'CapEx_Bn']
    latest_hv = sub.loc[latest_q, 'HV30_pct_mean']
    max_capex = sub['CapEx_Bn'].max()
    max_capex_q = sub['CapEx_Bn'].idxmax()
    print(f"\n{ticker}:")
    print(f"  Latest quarter ({latest_q}): CapEx=${latest_capex:.1f}B, HV30={latest_hv:.1f}%")
    print(f"  Peak CapEx: ${max_capex:.1f}B in {max_capex_q}")
    print(f"  HV30 range: {sub['HV30_pct_mean'].min():.1f}% - {sub['HV30_pct_mean'].max():.1f}%")

print("\nDone.")
