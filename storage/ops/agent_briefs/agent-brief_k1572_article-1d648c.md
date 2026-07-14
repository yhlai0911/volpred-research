# Task: K1572 一般讀者文章（draft，不發佈）

**Model**: opus / medium (per model_router) | **Task type**: daily_article（P1，餓死 75.6h）
**Task id**: K1572_article_general

## 開工前必讀（3 canonical，讀完才動筆）
- `.claude/skills/anti-ai-style/SKILL.md` + `references/prompt-templates.md`（5 原則套 prompt header）
- `.claude/rules/publishing.md`
- `.claude/skills/trending-repost/SKILL.md`（style 規範通用）

## 查重狀態（主線程已跑，不用重跑）
`check_arc_dedup.py --k-id k1572 --audience general` → **verdict=clean**；feed 層 grep k1572 → **0 命中**。

## 素材（唯一來源：experiments/k1572/）
`README.md` / `k1572_results.json` / 兩張現成圖：`fig_k1572_cumulative_pinball.png`、`fig_k1572_dnn_edges.png`。
- 主題：**DNN 分位數 VaR vs K1571 公平基準 → plateau**
- verdict: **NULL**（Codex reviewed, 2026-06-29）
- 敘事骨：又一次「深度學習沒有贏過老實的基準」。庫內這已是重複確認的天花板 —— 文章的價值不在宣布失敗，而在說清楚**為什麼公平的基準這麼難打敗**，以及一個**不公平的比較**會怎麼讓 DNN 看起來像贏了。

## 硬要求
- **Evidence package 先於 prose**：≥3 個可驗證數字（全出自 `k1572_results.json`，禁臆造）+ ≥1 表 + ≥1 真圖（可直接用現成兩張 PNG，或自己 matplotlib 產新圖存 `storage/drafts/assets/`；**禁 ASCII 冒充**）+ ≥1 層量化分析（pinball loss 的累積對照最直觀）。
- 誠實報 NULL，不可包裝成勝利，也不可為戲劇性誇大。

## 產出（並行安全，嚴格限定）
- `storage/drafts/k1572_general_draft.md`（front-matter: title / audience=general / k_id=k1572 / 數據來源與對應實驗）
- 圖存 `storage/drafts/assets/`
- **禁碰** `storage/reports/feed.json`、`storage/memory/*.json`、Supabase / Mirror sync。**只寫草稿，發佈由主線程串行做。**

## 收工 gate（未過不算完成）
1. `uv run python scripts/anti_ai_gate.py --file storage/drafts/k1572_general_draft.md` → exit 0 才算過；**禁 --force**。
2. anti-ai-style `references/editor-sop.md` 三階段 9-checklist；仍有 AI 味 / 翻譯腔 / 模板腔就改（3 輪 fail 就回報 abandon）。
3. 文末附懶人包圖組。
