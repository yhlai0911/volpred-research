# Next Draft Candidate: Cross-Market Binary-Sufficient EAV (General Audience)

> **🔒 CONSUMED 2026-04-19 19:43 UTC** — Article published as `mile_b9d5db50`（audience=general, status=draft, 1644 CJK 符合 general tier 精簡標準, 2 real matplotlib charts 驗證 HTTP 200）. Dispatched via Claude general-purpose agent `abd65396be9d74740` proactively before 20:00 UTC release (pre-empted draft_pool_low breach). Agent 用 K1151+K1157 raw parquet 1356 + 1370 events US/JP data + K1145/K1147/K1150/K1153 cluster-bootstrap SE/t-stat. Pool went 4→5 post-completion. Keep this memo as audit/cross-link history. Do not re-dispatch.

**Prepared 2026-04-19 19:15 UTC** as preemptive brief for next `draft_pool_low` remediation focused on **general-audience refill**.

## Cluster Overview

**Missing general audience** coverage for 5 score 8-10 K experiments (K1100-K1224 段)，research 版已有 (`mile_28f0ae1b` "三市場齊一的 binary-sufficient 普遍定律")。**pool audience balance** 近 3 research / 1 general，下次 release 會更偏 research — 此 memo 是 general audience side 的高分填補。

| K-id | Score | Title snippet | Covered by |
|------|-------|---------------|------------|
| K1150 | 10 | TOPIX N=30 Japan pooled θ_EAV PASS (three-market validation) | mile_28f0ae1b (research) |
| K1157 | 10 | JP TOPIX continuous EAV — binary-sufficient universality | mile_28f0ae1b |
| K1151 | 9 | Binary sufficient: continuous EAV surprise fails | mile_28f0ae1b |
| K1153 | 9 | EU 4th market PASS — direction universal but refutes cluster | mile_45060685 |
| K1152 | 8 | Relative-magnitude cross-market: direction universal | mile_28f0ae1b |

## Why this topic works (general audience angle)

- **Universal regularity** 敘事在大眾 hook 強：「全球 4 個市場（US/JP/EU/TW）的財報事件一致顯示只分有無」—— 投資人立即 actionable insight
- **Binary vs continuous 對比** 是視覺 - friendly：原本以為「大驚奇 → 大反應」(continuous) 但實際是「事件發生 → 一致大小反應」(binary)
- **可操作建議**：投資人不該去猜「這次 surprise 會多大」，只需知道「有沒有事件」
- **已有 research 版**（`mile_28f0ae1b` 15,862 CJK）可**濃縮為 general 版** 1500-2000 CJK，focus on conclusion + actionable implication，removes heavy stats (Harvey t / Wald / θ_rel 等)

## Article Skeleton Proposal (general audience 1500-2000 CJK)

1. **Intro**（投資人痛點）: 為什麼股市在財報日會大跳動？大家想知道 surprise 會不會被放大
2. **研究發現** (不用 3 市場，**4 市場**，K1153 加 EU): 美 / 日 / 歐 / 台，31 支股票 × 200+ 財報事件
3. **Binary-sufficient 現象**: 圖 1 — y 軸 vol reaction, x 軸 |surprise|。**點雲是平的** — 無 continuous slope
4. **只分有無**: 有事件日 reaction magnitude ~3x 無事件日，但不隨 surprise magnitude 變大
5. **例外？一致的 universality**: 4 個市場都一致 — 方向 universal，雖然 magnitude 市場間略差（K1152 Wald p~0）
6. **Actionable implication**: 
   - 投資人不需要猜「這次 surprise 大小」
   - 單單「財報日」vs「非財報日」的 vol 分層就夠資訊量
   - hedge / position size 決策可以 calendar-based 而非 surprise-prediction-based
7. **Cross-link**: 附深度 research 版 `mile_28f0ae1b` (15,862 CJK for stats-inclined readers)

## Charts needed (2 real)

1. **Binary 對比 scatter**: 4 markets × all events, y=vol ratio (event-day / baseline), x=|surprise|%. 4 subplots。關鍵：全部近水平線，confirming binary-sufficient
2. **4-market universal bar**: 4 個 market 的 θ_EAV binary coefficient (所有 PASS Harvey |t|>3) + error bars。敘事 punch line 圖

## Data sources

- `experiments/k1150/k1150_results.json` — JP TOPIX N=30
- `experiments/k1151/k1151_results.json` — continuous EAV surprise FAIL
- `experiments/k1152/k1152_results.json` — relative-magnitude Wald
- `experiments/k1153/k1153_results.json` — EU 4th market
- `experiments/k1157/k1157_results.json` — JP TOPIX continuous
- `storage/reports/feed.json` `mile_28f0ae1b` — canonical research article (reference only, 不複製)

## Dispatch when

- `draft_pool_low` breach (下次 20:00 UTC release 後 pool=3)
- OR 用戶 requests 一般讀者 cross-market 文章
- **Audience balance priority**: pool 目前 3 research / 1 general，此 memo 補 general side

## Differentiation vs other memos

- **vs K957**（consumed）— methodology lessons from experiments process
- **vs K1091**（consumed）— asset-class asymmetry FAIL mechanism (commodities)
- **vs K1092**（ready, research）— DCC-A4f Pareto subtlety
- **vs K1174**（DOWNGRADED）— already covered via footer
- **vs 本 memo**：是 first general-audience standalone covering cross-market 4-market universal binary regularity → 全新補位

## Hard rules (agent briefing template)

- proposer="Claude" / audience="**general**" / category="milestone" / status="draft"
- 1500-2000 CJK（general tier 較精簡）
- 2 real matplotlib charts
- 不 touch shared memory
- **禁止複製 `mile_28f0ae1b` 現有 research 版文字** — 此文必須 rewrite from experiment JSONs
- 結尾必附 cross-link to research article 供有興趣 deeper stats 讀者
- 圖 1 scatter 要顯 continuous NOT significant (點雲近水平) 是 killer visual
