# Task: K1681 一般讀者文章（draft，不發佈）

**Model**: opus / medium (per model_router) | **Task type**: daily_article（P1，餓死 72.3h）
**Task id**: K1681_article_general

## 開工前必讀（3 canonical，讀完才動筆）
- `.claude/skills/anti-ai-style/SKILL.md` + `references/prompt-templates.md`
- `.claude/rules/publishing.md`
- `.claude/skills/trending-repost/SKILL.md`（style 規範通用）

## 查重狀態（主線程已跑，不用重跑）
`check_arc_dedup.py --k-id k1681 --audience general` → **verdict=clean**；feed 層 grep k1681 → **0 命中**。

## 素材（唯一來源：experiments/k1681/ — README.md + results JSON + figures/）
- 主題：**SMAD =（收盤價 − 10 日均線）/ 10 日均線**，對「次日已實現波動、未來 5 日下行半變異數、左尾命中率」的**增量**預測力
- 樣本：20 檔美股 ETF 與大型股，2010-01 至 2026-07，**79,140 asset-days**，seed 1681
- verdict：**PASS / Harvey-significant**（這是庫內少見的正結果 —— 但正因為少見，更要守住「增量」二字）
- 關鍵設計：**span baseline** —— SMAD 的一階近似就是過去 10 日報酬，所以基準必須先吃掉那個成分，否則測到的只是動量的影子。文章一定要講清楚這個「公平比較」的設計，否則讀者會以為我們在賣一個神奇指標。

## 硬要求
- **Evidence package 先於 prose**：≥3 個可驗證數字（全出自 k1681 的 results JSON，禁臆造）+ ≥1 表 + ≥1 真圖（可用 `experiments/k1681/figures/` 現成圖，或自產存 `storage/drafts/assets/`；**禁 ASCII 冒充**）+ ≥1 層量化分析。
- **結論強度不可超過證據**：這是「在控制掉動量之後仍有增量訊號」，不是「找到聖杯」。不可推導成交易建議。

## 產出（並行安全，嚴格限定）
- `storage/drafts/k1681_general_draft.md`（front-matter: title / audience=general / k_id=k1681 / 數據來源與對應實驗）
- 圖存 `storage/drafts/assets/`
- **禁碰** `storage/reports/feed.json`、`storage/memory/*.json`、Supabase / Mirror sync。**只寫草稿，發佈由主線程串行做。**

## 收工 gate（未過不算完成）
1. `uv run python scripts/anti_ai_gate.py --file storage/drafts/k1681_general_draft.md` → exit 0；**禁 --force**。
2. anti-ai-style `references/editor-sop.md` 三階段 9-checklist（3 輪 fail 就回報 abandon）。
3. 文末附懶人包圖組。
