# trending_ai_capex_defensive_20260707

Evidence package for trending_repost article「AI 基建變現疑慮升溫，科技股與防禦板塊的波動率黃金交叉」.

## What it computes
- QQQ / XLK (tech) vs XLV/XLP/XLU equal-weight defensive basket
- 20-day rolling annualized realized volatility (RV) divergence
- Cumulative returns over 1M / 3M trailing windows
- QQQ-minus-defensive RV spread (level + window stats)
- 60-day rolling correlation QQQ vs defensive basket
- VIX level + CBOE ^SKEW tail-risk index

## Data / repro
- Source: yfinance daily adjusted close
- Period: 2025-10-01 to 2026-07-06 (183 trading days)
- seed=42
- Run: `uv run python evidence.py` → writes `results.json` + 2 PNGs to `storage/drafts/assets/`

## Key finding (honest)
Divergence is SIGNIFICANT: QQQ RV 35.28% vs defensive 16.02% (spread 19.27pp,
near 90-day max of 20.54). Rotation is recent (last 1M: QQQ −2.77% vs XLV +10.25%;
3M window still shows tech leading). Key nuance: VIX is LOW (15.57) while sector RV
spiked → this is a sector-level shock under a calm index surface, not market-wide
panic. SKEW elevated (145) = options market pricing tail risk despite calm VIX.
Rolling corr turned positive (0.308 vs −0.03 3M ago) → defensive win is partly
"relative resilience," not absolute rally.
