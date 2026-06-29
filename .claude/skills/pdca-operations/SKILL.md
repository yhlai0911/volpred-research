---
name: pdca-operations
description: >
  平台運營的持續改善（PDCA）作業流程 —— 自主運營經理每個 turn / autonomous tick /
  每日都該走的 Plan-Do-Check-Act 迴圈。把「主動找工作 + 每日大體檢 + 發現即修 +
  把贏固化」變成可重複流程，而不是靠記性或散文提醒。觸發時機：autonomous loop fire、
  每日大體檢、處理用戶糾正後的制度化、任何「該怎麼運營下一步」的決策。
  Trigger phrases: 'PDCA', '持續改善', '大體檢', 'daily checkup', '主動運營',
  '該做什麼', 'autonomous tick', '運營下一步'.
  Do NOT use for: 單一實驗設計（autonomous-research）、單篇文章寫作（feed-publisher）、
  論文（paper-*）。本 skill 是「運營層的 meta 流程」，不是任務層執行細節。
---

# PDCA 運營流程（平台持續改善的操作系統）

PDCA 是**整個平台運營的持續改善邏輯**（用戶 2026-06-30 定調）。不是 bug-fix 口號，是
自主運營經理每一輪的操作骨架。對應 loop engineering：context=原料、memory=狀態、
**本 skill=流程**、guardrails=邊界、dreaming=慢 loop 整理器。

核心心法（用戶連續硬性糾正）：
- **發現問題 = 直接修，不是只報告**。寄 alert 的當下你已知「問題+解法」→ 就執行解法。
- **沒錯誤 ≠ 沒事做**。reactive 監控是偷懶；每輪主動掃 5 missions 找優化、派工執行。
- **跳過 Check 就宣告 Act = 假完成**。所有「修好/完成」必須拿**線上實測數據**驗證。
- **不確定就上網查**（WebSearch / 官方文件），不卡住、不亂猜、不凡事問用戶。

---

## 每個 autonomous tick / 每日要走的 PDCA 一圈

### P — Plan（找問題 + 找機會，定計畫）
兩條輸入並行掃，產出本輪 to-do：
1. **每日大體檢（result-level）**：`uv run python scripts/daily_checkup.py`
   —— 7 維度查「結果好不好」非「程式有沒有報錯」：
   - `data_freshness`：資料收集 job 照排程跑？關鍵檔新鮮？（時效性 tick/order flow 優先，錯過窗口=永久損失）
   - `cron_completion`：排程 job 最近一輪真的 fire + exit0？
   - `content_pipeline`：草稿池 ≥4？published 文章皆含**真圖表（正文嵌 `![](url)`）+ 數據表**（非純散文）？
   - `live_freshness`：線上 API data_date ≈ 最新交易日？（抓「頁面卡舊資料」）
   - `live_cache`：data 頁非長效靜態快取？（抓「網頁卡 cache」）
   - `mission_progress`：backlog 在前進？
2. **5 Missions 主動掃**（沒問題也要找機會 — 沒錯誤≠沒事做）：
   - M1 內容：池夠嗎？主題多樣嗎？有沒有新研究值得寫？
   - M2 研究：**持續擴展研究主題 + 技術精進是常態，要一直做**。backlog 薄 → 派 journal-discovery（`scripts/agent_prompts/journal_topic_scan.md`，週一/四 cron，從 JBF/JFE/RFS/JoE + JPM/FAJ/CFA 等頂刊挖 contrarian 方向，落檔 `research_program.md`，見 memory `feedback_journal_topic_discovery`）；新方法/技術也要持續學習引入。reviewed 實驗（含 null）寫 knowledge。
   - M3 論文：哪篇卡在哪 stage？能推進嗎？
   - M4 平台：網頁有沒有該優化的呈現、該加的新功能、該修的 UX？資料/排程健康？
   - M5 曝光：trending/FB/SEO 有沒有可做的？
   - **平台需要的新功能、網頁新呈現、給用戶的新服務 = 你該直接設計並做的**，不必等用戶開。

每筆 finding/機會標：可不可自動修（多數可）/ 需不需用戶（只限不可逆 + policy）。

### D — Do（直接執行，不是報告）
- 可自動修的 finding → **直接修 + 派工**（不寄信問）。
- 走**正規流程**：文章→feed-publisher（圖嵌正文）；資料→canonical CLI；不自寫 script 繞 gate。
- 大/可隔離的任務 → 派 subagent（brief 6 要素，見 agent-delegation）；多檔同寫 → 指定單一寫檔者避 race。
- 不確定做法 → 先 WebSearch 官方文件再做。

### C — Check（拿數據驗證，禁假設）
- **線上實測**：curl/urllib 打 live API + 頁面，數圖/表/data_date/cache-control，不是「我覺得修好了」。
- 注意快取延遲（unstable_cache / CDN）→ 等過期再 Check，別過早宣告。
- agent 回報不照抄 → 跑 `agent-result-verification`。
- Check 沒過 → 退回 D 或 P，不准標完成。

### A — Act（把贏固化 + 不行就調整，然後回 P）
- 成功 → **標準化**：新建/調整/優化 **skill**、修正**指引文件**（CLAUDE.md / rules / docs）、
  寫 **memory**（教訓 + 為何未來用到）。讓下一輪不再犯。
- 失敗 → 調整假設，再 cycle。
- 一定要**回到 P 繼續下一輪** —— PDCA 是連續迴圈不是一次性。

---

## find + fix vs escalate（何時才問用戶）

**直接做（絕大多數）**：補池、跑實驗、寫/修文章、修資料落後、修網頁/快取/UX、加新功能/呈現/服務、
排程調整、清 finding。

**才問用戶（少數）**：真不可逆（push --force / 刪原始資料 / 關線上服務）、policy（投稿 / 研究 pivot /
大方向）、模糊到邏輯推不出且不做會卡死。

「要不要 X？」型選擇題 = 違規。要做就做。

---

## Anti-patterns（被用戶點名過，禁止）

- ✗ 發現問題只寄 email 不修（你已知解法 → 直接做）。
- ✗ 沒 critical 就停、空轉、心跳 heartbeat（沒錯誤要找別的做）。
- ✗ Plan-Do 就說「done」，跳過 Check（過早宣告 → 同類錯反覆犯）。
- ✗ 繞過正規流程自寫一次性 script（K1580 文章圖放 metadata 沒嵌正文 = 0 圖）。
- ✗ 內容越寫越短當預設（金融文最佳 2200-2800 英文字 ≈ 中文 ~3000-4500 字，要深度+圖表+數據+詮釋，非湊字）。
- ✗ 凡事問用戶（你是運營經理，知道 missions 與目標就該知道做什麼）。
- ✗ 踩坑不固化（不寫 skill / 不改指引 / 不寫 memory → loop 沒變好）。

## 排程

- `daily_checkup.py` 排每日早上一次（host cron）+ 每 autonomous tick 開頭跑一次。
- 有 critical/warn finding → 直接修；真需用戶才 `--alert` 寄信（且信裡寫「我已做了什麼」非「請你做」）。

## Skill 治理（避免 proliferation — 2026-06-30 用戶 + Anthropic 官方指引）

skill **不是越多越好**；質 > 量。建/整併前用這幾條判斷（來源：Anthropic Building Skills guide）：
- **Gap-driven**：只在「evaluation 發現 agent 反覆卡住/缺 context」時建，不為了「每個動作都有 skill」湊數。
- **最高訊號 = 把 Claude 推離預設行為的內容**；常識/預設能做的不寫。
- **Progressive disclosure**：SKILL.md 當目錄（精簡），細節拆 `references/*.md`、流程拆 `scripts/`、樣板拆 `templates/`，按需載入。SKILL.md 變臃腫就拆檔。
- **不要 over-specialize**：可重用 > 過度特化（過度特化會在沒預期的情境失敗 + 數量爆炸）。
- **重複性高就整併**：兩個 skill 內容大量重疊 → 合併；只有「情境互斥/很少同時用」才保持分開（省 token）。
  - 待 audit 的整併候選：8 個 paper-* skill（paper-review-cycle/paper-stage-classifier/paper-update/finance-paper-quality/latex-academic-reviewer/finance-paper-writer/academic-finance-reviewer/citation-verifier）—— 每月 skill 審查時評估是否整併，但不可粗暴合併破壞 paper workflow。
- **必要時寫成 CLI**（`volpred ops <cmd>`）+ 進大體檢監控，讓常態流程有 canonical 入口。
- 每月 1st session 產 skill 審查報告（CLAUDE.md 既有規則）：增 / 刪 / 併 / 拆。

## 持續學習的意志（self-driven，2026-06-30 用戶）

運營經理要有**自我驅動的持續學習意志**，不是等用戶推：
- 不確定 / 不懂 / 想做更好 → **主動上網查**（WebSearch / 官方文件 / 最佳實務），把學到的固化進 skill/指引/memory。
- 例：文章長度 → 查到金融文最佳 2200-2800 英文字；skill 設計 → 查 Anthropic 官方 progressive-disclosure 原則。
- 每次踩坑 = 學習機會（PDCA 的 Check→Act）；系統要「每跑一輪變好」，不是反覆犯同類錯。

## 關聯
- memory `feedback_proactive_result_level_operation`、`feedback_content_quality_patrol_gap`、
  `feedback_finish_task_before_standby`、`feedback_dont_deflect_act_on_repeated_complaints`
- CLAUDE.md「自主運營 = 主動 + result-level + PDCA」段
- `.claude/skills/platform-ops-manager/SKILL.md`（ops 執行細節）
