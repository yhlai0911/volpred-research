# K1410 AI CapEx vs IV Divergence

**Task type**: trending_repost evidence package  
**Date**: 2026-06-06  
**Article**: AI 變現落後預期 — CapEx 暴衝 vs 波動率靜悄悄  

## Purpose

Assemble primary-source data to support a VolPred-angle trending commentary on
the divergence between AI hyperscaler capital expenditure acceleration and
market-implied / realized volatility structure. VolPred angle: does the vol
surface actually price in AI ROI uncertainty, or is the market still running on
hope?

## Data Sources

- yfinance quarterly cashflow (`Capital Expenditure` row) — META, MSFT, GOOGL, AMZN, NVDA
- yfinance daily price history 2022-01-01 to 2026-06-05 — same tickers
- yfinance ^VIX daily 2022-01-01 to 2026-06-05

## Key Numbers (verified from run.py output)

| Ticker | TTM CapEx ($B) | Latest Q YoY | 2023→2026 Cum Return | H1 2025 30d RV |
|--------|---------------|-------------|----------------------|----------------|
| META   | 75.8          | +47%        | +407%                | 38.9%          |
| MSFT   | 97.2          | +84%        | +84%                 | 27.5%          |
| GOOGL  | 109.9         | +107%       | +321%                | 35.5%          |
| AMZN   | 151.0         | +77%        | +196%                | 35.2%          |
| NVDA   | 6.6           | +43%        | +1431%               | 60.2%          |
| **Total** | **~$440B** | —          | —                    | avg ~39.5%     |

VIX annual averages:
- 2023: 16.9
- 2024: 15.6  ← multi-year low, deepest capex ramp period
- 2025: 19.0
- 2026 YTD: 19.5

## VolPred Angle

Five hyperscalers spent $440B TTM on AI infrastructure. Market priced in the
upside (stocks up 84–1431%) but vol surface stayed compressed through 2024
(VIX avg 15.6). The question: does depressed vol mean "priced in" or
"not yet pricing the downside risk of ROI disappointment"?

## Files

- `run.py` — data fetch + chart generation script
- `k1410_ai_capex_iv_divergence_results.json` — full results
- `figures/fig_price_and_rv.png` — cumulative return + realized vol time series
- `figures/fig_capex_vs_rv.png` — TTM CapEx bar chart + 2026 RV overlay

## Research Honesty Notes

- CapEx YoY `ttm_yoy_growth_pct` shows `None` because yfinance quarterly
  cashflow only returns 5 quarters (not 8), so TTM vs prior-TTM comparison
  cannot be computed. Per-quarter YoY (latest Q vs same Q -1y) IS available
  and used. Article will clearly state data limitation.
- No option chain ATM IV pulled (yfinance options unreliable for systematic
  comparison). Realized vol used as proxy. Article will note this.
- NVDA CapEx ($7B TTM) is small vs peers because NVDA is a fabless chip
  designer — capex is R&D-heavy, not datacenter-build heavy. Context noted
  in article.
