# Next Draft Candidate: K1092 Asymmetric DCC-A4f Portfolio VaR

**Prepared 2026-04-19** as preemptive brief for future `draft_pool_low` remediation. Third memo in series (K957 / K1091 / K1092).

## K1092 Overview

**Score**: 5
**Title**: K1092: Asymmetric DCC-A4f (SPY-VIX + GLD-GVZ) — Strictly Pareto-Dominant but Below Harvey vs Symmetric
**Coverage**: uncovered any audience

## Why this topic works

- **Nuanced finding** — 適合 research audience：asset-matched IV (GVZ for GLD) **strictly Pareto-dominates** SYMMETRIC baseline 在每個 VaR metric，但 **below Harvey |t|>3** for the incremental gain
- **Methodology case**: 示範 asset-matched implied volatility 的 value + Harvey threshold 作為 "significant vs not significant" boundary 的 practical meaning
- **具體結果**:
  - DCC-A4f-ASYM (SPY+VIX², GLD+GVZ²)
  - DCC-A4f-SYMM (both VIX, K1041 baseline)
  - vs DCC-GJR baseline
  - ASYM vs GJR: Harvey PASS on every metric ✓
  - ASYM vs SYMM: Pareto-dominant but below Harvey（improvement 存在但 marginal）
  - Period: 2013-2026, n=3,234 (50/50 SPY+GLD portfolio)

## Article Skeleton Proposal (research audience 2000-2500 chars)

1. **Intro**: DCC-A4f framework + asset-matched IV 假設
2. **Setup**: 3-spec comparison (ASYM / SYMM / GJR) + portfolio structure
3. **Result 1 - ASYM vs GJR**: Harvey PASS everywhere（baseline validation）
4. **Result 2 - ASYM vs SYMM**: Pareto-dominant but below Harvey（the subtlety）
5. **Interpretation**: why asset-matched IV helps but incrementally
6. **Harvey threshold 意義**: 「significant 不等於重要」的實戰案例
7. **Cross-link to K1091 (Meta-prediction)** — asset-class consistency thread

## Charts needed (2 real)

1. Pareto frontier plot: ASYM vs SYMM per metric (all points above 45° line, but Harvey |t|<3 band)
2. VaR time-series sample segment showing difference 不 visually strong (reinforcing 'below Harvey' point)

## Data sources

- `experiments/k1092/k1092_results.json`
- `experiments/k1041/k1041_results.json` (SYMM baseline)
- `experiments/k1090/k1090_results.json` (meta-prediction context)

## Dispatch when

- Pool drops below 4 after K957 + K1091 both used
- Or user requests methodology-nuance article

## Differentiation from other memos

- **vs K957** (37-exp synthesis): K1092 是 single-case methodology nuance
- **vs K1091** (asset-class FAIL mechanism): K1092 是 asset-matched IV value + Harvey boundary 細節
- **vs K672** (evidence hierarchy summary): K1092 示範 evidence "below Harvey" tier 的存在意義

## Hard rules (agent briefing template)

- proposer="Claude" / audience="research" / category="milestone" / status="draft"
- 2000+ chars CJK
- 2 real matplotlib charts
- Emphasize the **"Pareto-dominant but below Harvey"** subtlety as the article's narrative hook
- Harvey threshold explanation should be explicit（不假設讀者熟悉 multiple-testing correction）
