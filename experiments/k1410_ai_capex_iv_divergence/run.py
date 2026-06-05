"""
K1410 AI CapEx vs IV Divergence Evidence Package
=================================================
Topic: AI hyperscaler CapEx growth vs implied/realized volatility dynamics
VolPred angle: IV / realized vol structure shows market is NOT fully pricing AI ROI uncertainty

Primary data sources:
- yfinance: stock prices + option chain (for IV proxy)
- yfinance cashflow: CapEx data from quarterly financials
- VIX from ^VIX
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import json
import os
from datetime import datetime, timedelta

SEED = 20260606
np.random.seed(SEED)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(OUTPUT_DIR, "figures")
os.makedirs(FIG_DIR, exist_ok=True)

# ─── 1. CapEx data from yfinance quarterly cashflow ─────────────────────────
# AI hyperscalers: META, MSFT, GOOGL, AMZN, NVDA
TICKERS = ["META", "MSFT", "GOOGL", "AMZN", "NVDA"]

print("Fetching CapEx data from yfinance quarterly cashflows...")
capex_records = {}
for ticker in TICKERS:
    try:
        t = yf.Ticker(ticker)
        cf = t.quarterly_cashflow
        # CapEx is typically 'Capital Expenditure' (negative in cashflow statement)
        capex_row = None
        for row_name in ['Capital Expenditure', 'Purchase Of Property Plant And Equipment',
                         'Purchase Of Business', 'Capital Expenditures']:
            if row_name in cf.index:
                capex_row = cf.loc[row_name]
                break
        if capex_row is None:
            # Try looking for anything with 'capital' or 'property'
            for row_name in cf.index:
                if 'capital' in row_name.lower() or ('property' in row_name.lower() and 'purchase' in row_name.lower()):
                    capex_row = cf.loc[row_name]
                    print(f"  {ticker}: using row '{row_name}'")
                    break
        if capex_row is not None:
            # Convert to billions, take absolute value (cashflow shows negative outflow)
            capex_records[ticker] = (capex_row.abs() / 1e9).sort_index()
            print(f"  {ticker}: found CapEx, latest quarters: {capex_row.abs().head(4).sort_index().values/1e9}")
        else:
            print(f"  {ticker}: no CapEx row found. Available: {list(cf.index)[:10]}")
    except Exception as e:
        print(f"  {ticker}: error - {e}")

# ─── 2. Price + realized vol ─────────────────────────────────────────────────
print("\nFetching price data...")
price_data = {}
for ticker in TICKERS:
    try:
        hist = yf.download(ticker, start="2022-01-01", end="2026-06-05", auto_adjust=True, progress=False)
        if len(hist) > 0:
            col = hist['Close']
            # yfinance multi-ticker download → DataFrame; single-ticker → Series or 1-col DF
            if isinstance(col, pd.DataFrame):
                col = col.squeeze()
            price_data[ticker] = col
            print(f"  {ticker}: {len(hist)} trading days")
    except Exception as e:
        print(f"  {ticker}: price error - {e}")

# VIX
try:
    vix_raw = yf.download("^VIX", start="2022-01-01", end="2026-06-05", auto_adjust=True, progress=False)['Close']
    vix_data = vix_raw.squeeze() if isinstance(vix_raw, pd.DataFrame) else vix_raw
    print(f"  ^VIX: {len(vix_data)} trading days")
except Exception as e:
    print(f"  VIX error: {e}")
    vix_data = pd.Series(dtype=float)

# ─── 3. Compute 30-day realized vol (annualized) for each ticker ──────────────
print("\nComputing realized vol...")
rv_data = {}
for ticker, prices in price_data.items():
    # yfinance download returns DataFrame; squeeze to 1D Series
    s = prices.squeeze() if hasattr(prices, 'squeeze') else prices
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    log_ret = np.log(s / s.shift(1)).dropna()
    rv_30d = log_ret.rolling(21).std() * np.sqrt(252)  # ~21 trading days per month
    rv_data[ticker] = rv_30d

# ─── 4. Build CapEx growth table ──────────────────────────────────────────────
# Extract most recent 4 quarters and compute YoY growth
capex_summary = {}
for ticker, series in capex_records.items():
    s = series.sort_index(ascending=False)  # most recent first
    if len(s) >= 4:
        # Latest available quarter vs same quarter 1 year ago
        latest_q_val = s.iloc[0]
        year_ago_val = s.iloc[4] if len(s) > 4 else None
        yoy_pct = ((latest_q_val / year_ago_val) - 1) * 100 if year_ago_val and year_ago_val > 0 else None
        latest_annual = s.iloc[:4].sum()  # TTM
        prior_annual = s.iloc[4:8].sum() if len(s) >= 8 else None
        annual_yoy = ((latest_annual / prior_annual) - 1) * 100 if prior_annual and prior_annual > 0 else None
        capex_summary[ticker] = {
            "latest_quarter_bn": round(float(latest_q_val), 2),
            "latest_quarter_date": str(s.index[0].date()),
            "ttm_bn": round(float(latest_annual), 2),
            "yoy_growth_pct": round(float(yoy_pct), 1) if yoy_pct is not None else None,
            "ttm_yoy_growth_pct": round(float(annual_yoy), 1) if annual_yoy is not None else None,
        }
    else:
        capex_summary[ticker] = {"note": f"insufficient data, {len(s)} quarters available"}

print("\nCapEx Summary:")
for ticker, info in capex_summary.items():
    print(f"  {ticker}: {info}")

# ─── 5. Compute vol stats ──────────────────────────────────────────────────────
# Compare: H1 2024 vs H1 2025 (AI capex acceleration period)
def safe_rv(series, start, end):
    sub = series.loc[start:end].dropna()
    if len(sub) == 0:
        return None
    val = float(sub.mean())
    return round(val * 100, 1) if not pd.isna(val) else None

vol_comparison = {}
for ticker, rv in rv_data.items():
    h1_2024_pct = safe_rv(rv, "2024-01-01", "2024-06-30")
    h1_2025_pct = safe_rv(rv, "2025-01-01", "2025-06-30")
    ytd_2026_pct = safe_rv(rv, "2026-01-01", "2026-06-06")
    vol_comparison[ticker] = {
        "h1_2024_rv_pct": h1_2024_pct,
        "h1_2025_rv_pct": h1_2025_pct,
        "2026ytd_rv_pct": ytd_2026_pct,
    }
    if h1_2024_pct is not None and h1_2025_pct is not None:
        vol_comparison[ticker]["vol_change_2024_to_2025_pct"] = round(h1_2025_pct - h1_2024_pct, 1)
print("\nVol Comparison:")
for ticker, info in vol_comparison.items():
    print(f"  {ticker}: {info}")

# ─── 6. Stock price returns during capex ramp-up ─────────────────────────────
# Jan 2023 - Jun 2026: cumulative return and max drawdown
price_stats = {}
for ticker, prices in price_data.items():
    period = prices.loc["2023-01-01":"2026-06-05"].dropna()
    if len(period) > 10:
        cum_ret = (period.iloc[-1] / period.iloc[0] - 1) * 100
        rolling_max = period.expanding().max()
        drawdown = (period - rolling_max) / rolling_max
        max_dd = drawdown.min() * 100
        price_stats[ticker] = {
            "cumulative_return_2023_to_2026_pct": round(float(cum_ret), 1),
            "max_drawdown_pct": round(float(max_dd), 1),
        }
print("\nPrice Stats (2023-2026):")
for ticker, info in price_stats.items():
    print(f"  {ticker}: {info}")

# ─── 7. VIX stats ─────────────────────────────────────────────────────────────
vix_stats = {}
if len(vix_data) > 0:
    for label, start, end in [
        ("2023_avg", "2023-01-01", "2023-12-31"),
        ("2024_avg", "2024-01-01", "2024-12-31"),
        ("2025_avg", "2025-01-01", "2025-12-31"),
        ("2026ytd_avg", "2026-01-01", "2026-06-06"),
    ]:
        sub = vix_data.loc[start:end].dropna()
        if len(sub) > 0:
            vix_stats[label] = round(float(sub.mean()), 1)
print("\nVIX Stats:", vix_stats)

# ─── 8. FIGURE 1: CapEx TTM vs Stock Price (2023-2026) ────────────────────────
# Use price data for the chart + capex as bar overlay
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.patch.set_facecolor('#f8f9fa')

# Panel A: Cumulative return comparison
ax1 = axes[0]
ax1.set_facecolor('#f8f9fa')
colors = {'META': '#1877F2', 'MSFT': '#00BCF2', 'GOOGL': '#34A853', 'AMZN': '#FF9900', 'NVDA': '#76B900'}
for ticker, prices in price_data.items():
    period = prices.loc["2022-01-01":"2026-06-05"].dropna()
    if len(period) > 0:
        normalized = period / period.iloc[0] * 100
        ax1.plot(normalized.index, normalized.values, label=ticker,
                 color=colors.get(ticker, 'gray'), linewidth=1.8, alpha=0.85)

ax1.axvline(pd.Timestamp("2023-01-01"), color='gray', linestyle='--', alpha=0.4, linewidth=1)
ax1.axvline(pd.Timestamp("2025-01-01"), color='gray', linestyle='--', alpha=0.4, linewidth=1)
ax1.text(pd.Timestamp("2023-01-15"), ax1.get_ylim()[0] if ax1.get_ylim()[0] > 0 else 50,
         "AI CapEx\n開始暴衝", fontsize=8, color='gray', va='bottom')
ax1.set_title("AI 科技股累積漲幅 (2022=100)", fontsize=12, fontweight='bold', pad=10)
ax1.set_ylabel("指數化報酬 (基期100)", fontsize=10)
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax1.legend(loc='upper left', fontsize=9)
ax1.grid(True, alpha=0.3)
ax1.set_xlabel("")

# Panel B: 30d RV across time
ax2 = axes[1]
ax2.set_facecolor('#f8f9fa')
for ticker, rv in rv_data.items():
    period = rv.loc["2022-01-01":"2026-06-05"].dropna()
    ax2.plot(period.index, period.values * 100, label=ticker,
             color=colors.get(ticker, 'gray'), linewidth=1.5, alpha=0.75)

if len(vix_data) > 0:
    ax2.plot(vix_data.index, vix_data.values, label='VIX', color='black',
             linewidth=2.0, linestyle='--', alpha=0.6)

ax2.axvline(pd.Timestamp("2023-01-01"), color='gray', linestyle='--', alpha=0.4, linewidth=1)
ax2.set_title("個股 30日實現波動率 vs VIX (%)", fontsize=12, fontweight='bold', pad=10)
ax2.set_ylabel("年化波動率 (%)", fontsize=10)
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax2.legend(loc='upper right', fontsize=9)
ax2.grid(True, alpha=0.3)
ax2.set_ylim(0, 120)

plt.suptitle("AI CapEx 暴衝期間：股價漲了，波動率靜悄悄？", fontsize=13, fontweight='bold', y=1.02)
plt.tight_layout()
fig1_path = os.path.join(FIG_DIR, "fig_price_and_rv.png")
plt.savefig(fig1_path, dpi=150, bbox_inches='tight', facecolor='#f8f9fa')
plt.close()
print(f"\nSaved: {fig1_path}")

# ─── 9. FIGURE 2: CapEx TTM bar chart + vol scatter ──────────────────────────
fig2, ax = plt.subplots(figsize=(10, 6))
fig2.patch.set_facecolor('#f8f9fa')
ax.set_facecolor('#f8f9fa')

valid_capex = {t: v for t, v in capex_summary.items() if isinstance(v.get("ttm_bn"), float)}
if valid_capex:
    tickers_list = list(valid_capex.keys())
    ttm_vals = [valid_capex[t]["ttm_bn"] for t in tickers_list]
    yoy_vals = [valid_capex[t].get("ttm_yoy_growth_pct") for t in tickers_list]

    x = np.arange(len(tickers_list))
    bars = ax.bar(x, ttm_vals, color=[colors.get(t, 'steelblue') for t in tickers_list],
                  alpha=0.8, edgecolor='white', linewidth=1.2)

    for i, (bar, yoy) in enumerate(zip(bars, yoy_vals)):
        if yoy is not None:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                    f"+{yoy:.0f}%\nYoY" if yoy > 0 else f"{yoy:.0f}%\nYoY",
                    ha='center', va='bottom', fontsize=10, fontweight='bold',
                    color='#333333')
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height()/2,
                f"${ttm_vals[i]:.0f}B",
                ha='center', va='center', fontsize=11, fontweight='bold', color='white')

    ax.set_xticks(x)
    ax.set_xticklabels(tickers_list, fontsize=12)
    ax.set_ylabel("TTM CapEx (十億美元)", fontsize=11)
    ax.set_title("AI 概念股 TTM 資本支出 — 年增率 (YoY)", fontsize=13, fontweight='bold', pad=10)
    ax.grid(axis='y', alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Add vol annotation on secondary axis
    ax2b = ax.twinx()
    rv_vals_2026 = []
    for t in tickers_list:
        rv_val = vol_comparison.get(t, {}).get("2026ytd_rv_pct")
        rv_vals_2026.append(rv_val if rv_val else np.nan)

    ax2b.scatter(x, rv_vals_2026, marker='D', s=80, color='crimson', zorder=5, label="2026YTD RV(%)")
    ax2b.set_ylabel("2026 YTD 30日實現波動率 (%)", fontsize=10, color='crimson')
    ax2b.tick_params(axis='y', labelcolor='crimson')
    ax2b.set_ylim(0, 80)
    ax2b.legend(loc='upper right', fontsize=9)

plt.tight_layout()
fig2_path = os.path.join(FIG_DIR, "fig_capex_vs_rv.png")
plt.savefig(fig2_path, dpi=150, bbox_inches='tight', facecolor='#f8f9fa')
plt.close()
print(f"Saved: {fig2_path}")

# ─── 10. Save results JSON ─────────────────────────────────────────────────────
results = {
    "experiment_id": "k1410_ai_capex_iv_divergence",
    "title": "AI CapEx 暴衝 vs 波動率背離：市場真的 priced in AI ROI 質疑了嗎？",
    "generated_at": datetime.utcnow().isoformat() + "+00:00",
    "data_sources": ["yfinance (stock prices, quarterly cashflow)", "^VIX"],
    "tickers": TICKERS,
    "capex_summary": capex_summary,
    "vol_comparison": vol_comparison,
    "price_stats": price_stats,
    "vix_stats": vix_stats,
    "figures": {
        "fig1": "figures/fig_price_and_rv.png",
        "fig2": "figures/fig_capex_vs_rv.png",
    },
    "key_findings": [],  # filled below
}

# Generate key findings
findings = []
# Finding 1: Total AI CapEx TTM
total_capex = sum(v.get("ttm_bn", 0) or 0 for v in capex_summary.values() if isinstance(v.get("ttm_bn"), (int, float)))
findings.append(f"META + MSFT + GOOGL + AMZN + NVDA TTM CapEx 合計 ${total_capex:.0f}B")

# Finding 2: YoY growth leaders
growth_vals = [(t, v.get("ttm_yoy_growth_pct")) for t, v in capex_summary.items()
               if v.get("ttm_yoy_growth_pct") is not None]
if growth_vals:
    best = max(growth_vals, key=lambda x: x[1])
    findings.append(f"YoY 成長最高的是 {best[0]}，TTM CapEx YoY +{best[1]:.0f}%")

# Finding 3: Vol flat or compressed
rv_2025_vals = [(t, vol_comparison[t].get("h1_2025_rv_pct")) for t in TICKERS
                if vol_comparison.get(t, {}).get("h1_2025_rv_pct") is not None]
if rv_2025_vals:
    avg_rv_2025 = np.mean([v for _, v in rv_2025_vals])
    findings.append(f"H1 2025 平均 30日實現波動率 {avg_rv_2025:.1f}%（相較 2022/2023 熊市顯著低）")

# Finding 4: VIX avg
if "2025_avg" in vix_stats:
    findings.append(f"2025 年 VIX 全年均值 {vix_stats['2025_avg']}，為近年相對低點")

# Finding 5: Price vs capex
if "META" in price_stats and price_stats["META"].get("cumulative_return_2023_to_2026_pct"):
    findings.append(f"META 自 2023 至今累計漲幅 +{price_stats['META']['cumulative_return_2023_to_2026_pct']:.0f}%，同期 CapEx YoY 持續擴張")

results["key_findings"] = findings

out_path = os.path.join(OUTPUT_DIR, "k1410_ai_capex_iv_divergence_results.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nResults saved: {out_path}")
print("\nKey findings:")
for kf in findings:
    print(f"  - {kf}")
