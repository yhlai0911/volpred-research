# Task: K1702 milestone 一般讀者文章（draft，不發佈）

**Model**: opus / medium (per model_router)
**Task type**: daily_article（P1，已餓死 54h+；draft 池只剩 2、今日發佈 0 = 內容斷炊）
**Task id**: publish_milestone_k1702_phase_null

## 開工前必讀（3 canonical，讀完才動筆）
- `.claude/skills/trending-repost/SKILL.md`（dual-publish + style 規範通用）
- `.claude/skills/anti-ai-style/SKILL.md` + `references/prompt-templates.md`（5 原則套 prompt header）
- `.claude/rules/publishing.md`

## 查重狀態（主線程已跑，你不用再跑）
`check_arc_dedup.py --k-id k1702 --audience general` → **verdict=clean**（無 K-coverage、無 arc duplicate）。

## 素材（唯一來源：experiments/k1702/）
K1702 已過 primary-path Codex review + 兩份獨立全母體稽核。實證裁決 **NULL_OR_MIXED_INDIVIDUAL_FACTOR_OOS**：
- primary 正 Sharpe delta：**1/6** 個因子
- paired bootstrap BH-FDR：**0/6**
- spanning-alpha t gate BH-FDR：**0/6**
- 回撤教訓：**MDD/vol 是描述性統計，不是 scale-invariant**。曝險匹配 + 316 次相位隨機化 null 之後，只剩 MOM 有正的 production gap，**p=0.1582（不顯著）**
- 對照：raw MDD 看起來 5/6 改善 → vol-normalized 之後只剩 1/6。「回撤變淺」很多時候只是**少冒險**，不是**會擇時**。

## 文章骨架要求
**Evidence package 先於 prose** —— 動筆前先組好，組不出來就回報而不是硬寫：
- ≥3 個可驗證數字（全部來自 `experiments/k1702/k1702_results.json`，不可臆造）
- ≥1 張表（因子 × 樣本外 Sharpe delta / FDR 結果）
- ≥1 張真圖表（matplotlib 產圖存 `storage/drafts/assets/`；**禁止 ASCII / 文字框冒充**）
- ≥1 層量化分析（raw MDD vs 曝險匹配 MDD 的 before-after 對照最有說服力）

**敘事主軸建議**（不要寫成論文摘要）：一個對散戶最有殺傷力的直覺 —— 「用波動率調控包一層，回撤就變小了」—— 在誠實的檢定下大半是幻覺。把 raw 5/6 → vol-normalized 1/6 這個對照當文章的骨。誠實報 NULL，不可包裝成勝利，也不可為了戲劇性而誇大。

## 產出（嚴格限定，並行安全）
- `storage/drafts/k1702_general_draft.md`（含 front-matter：title / audience=general / k_id=k1702 / 數據來源與對應實驗）
- 圖表 assets 存 `storage/drafts/assets/`
- **禁碰** `storage/reports/feed.json`、`storage/memory/*.json`、Supabase / Mirror sync（feed 寫入無 per-writer lock，並行直發會 race）。**你只寫草稿，發佈由主線程串行做。**

## 收工前硬 gate（未過不算完成）
1. `uv run python scripts/anti_ai_gate.py --file storage/drafts/k1702_general_draft.md` → **exit 0 才算過**。MUST level 命中任一條 = 整篇 reject 改寫；WARN ≥3 累計也 reject。**禁止 --force 繞過**。
2. anti-ai-style `references/editor-sop.md` 三階段 9-checklist 自審；還有 AI 味 / 翻譯腔 / 模板腔 / 空泛評論就繼續改（3 輪仍 fail 就回報 abandon，不要硬發）。
3. 文末附懶人包圖組（per memory feedback_lazypack_infographic；一般讀者文章適用）。

## 研究誠實
所有數字必須出自 k1702 的 results JSON。**Null 就如實報 null。** 結論強度不可超過證據 —— 這篇的價值就在於「誠實的檢定推翻了一個很好賣的直覺」，把它寫成勝利反而毀了它。
