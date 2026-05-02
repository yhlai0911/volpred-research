# NFP 2026-05-01 T-2 dispatch memo

**Event**: US Bureau of Labor Statistics — Employment Situation Report (Non-Farm Payrolls + Unemployment + Average Hourly Earnings)
**Release time**: 2026-05-01 (Friday) 08:30 ET = 20:30 CST
**Materialize window**: not_before 2026-04-29 00:00 CST → deadline 2026-04-30 23:59 CST
**Slot**: T-2 of NFP_2026_05_01 cluster (T-7 missed)
**Audience**: general
**Status target**: published (event-driven, immediate)
**Word count**: ≥ 1500 CJK
**Charts**: 2 real matplotlib PNGs (Supabase upload), no ASCII placeholder

## Differentiation axis（避免與一般「NFP 預期」文章雷同）

主軸：**Consensus expectations × Historical surprise-conditional reaction**

不寫「NFP 是什麼／為什麼重要」這種 explainer。直接給：
1. **Consensus 數字 grid**（headline NFP / unemployment rate / AHE YoY 三個變數的 Bloomberg/MarketWatch 共識）— WebSearch 取最新
2. **Historical surprise buckets**（過去 24-36 個月 NFP releases，按 |actual − consensus| 分 small/medium/large 三檔）
3. **每檔的 SPY 1-day return + VIX 1-day move 分佈**（mean / std / 5-95 percentile）
4. **Trader takeaway**：T-2 到 T+0 的 position sizing 規則（依 surprise size 預設 hedge ratio 或 vol scaling）

## 數據來源（必引用）

- BLS Employment Situation：https://www.bls.gov/news.release/empsit.htm
- FRED PAYEMS / UNRATE / CES0500000003 (production AHE YoY)
- Bloomberg / MarketWatch consensus（WebSearch 04-29 ~ 04-30 取得最新預期）
- SPY / VIX 從本地 yfinance pull（30 個月）

## 3-layer dedup（dispatch 前主線程必做）

```bash
# Layer 2: feed grep
grep -i "NFP\|非農\|non.farm" storage/reports/feed.json | grep -i title | head -5
# Layer 1: candidates check
jq '.top_10_uncovered + .missing_general_top5 | map(select(.title | test("NFP|非農|payroll"; "i")))' storage/publication_candidates.json
# Layer 3: theme matrix
# 最近 7 天有沒有 macro/event 文章已蓋過 NFP angle?
jq -r 'map(select(.published_at >= "2026-04-19") | "\(.published_at[:10]) \(.title[:80])")[]' storage/reports/feed.json | head -20
```

若 dedup 出現 hard duplicate → 切換到 audience=research 重寫，或 skip 此 slot 留 T+0 名額。

## Tags 建議

`["NFP", "非農就業", "macro-event", "labor-market", "T-2", "general"]` + 「event」「研究」根據 publisher 規則自動加。

## Hard rules

- 不改 paper/*.tex（paper-workflow rule）
- 不動實驗 results.json
- 圖表必真實 matplotlib PNG，Supabase upload
- 數據引用必標期間（X 月 - Y 月）+ 樣本數（N=Z 個 NFP releases）
- 走 `feed-publisher` skill 正式管道，不手動 PATCH Supabase
- WebSearch 必須在 dispatch 前完成，不靠 agent 訓練資料記憶 consensus 數字

## Cap

NFP_2026_05_01 cluster 共 2 entries（T-2 + T+0），T-7 因 calendar populate gap missed。本 slot 為 1/2。
