# 自主波動率預測研究系統
原則上使用繁體中文互動

## 研究誠實原則（最高優先，不可違反）

**一切結果必須真實、嚴謹、可驗證。違反任何一條即視為研究失敗。**

1. **不可造假、不可虛構**：所有數據、統計量、圖表必須來自實際計算，不可編造數字或偽造結果
2. **數據來源透明**：每個實驗必須標明數據來源（yfinance、FRED、CBOE 等）、資料期間、樣本數量。不可用模擬數據冒充實證數據
3. **實驗必須有對應檔案 + 知識庫記錄 + 經驗記錄**：每個實驗完成後，**必須同時產出三項**：
   - **檔案**：每個實驗必須有專屬資料夾 `experiments/<experiment_id>/`，所有相關檔案放在裡面：
     - `experiments/<experiment_id>/README.md`（**必備：計劃、問題描述、動機、方法、預期、結論**）
     - `experiments/<experiment_id>/<experiment_id>.py`（腳本）
     - `experiments/<experiment_id>/<experiment_id>_results.json`（結果）
     - `experiments/<experiment_id>/*.png`（圖表）
     - `experiments/<experiment_id>/references/`（參考文獻，如有）
     - `experiments/<experiment_id>/data/`（實驗專屬數據，如有）
     - **Agent worktree 完成後必須用 `bash scripts/merge_worktree.sh` 合併到主分支**（⚠️ 絕對禁止 `git worktree remove --force`）
     - **README.md 是必備的**——打開資料夾就能知道在做什麼、為什麼、怎麼做、結論是什麼
   - **知識庫**（`storage/memory/knowledge.json`）：含 experiment_id、title、content 摘要（200-300字）、tags、data_source。記錄**發現了什麼**（結論、數據、統計量）
   - **經驗庫**（`storage/memory/experiment_experiences.json`，Exxx 編號）：記錄**學到了什麼**（為什麼成功/失敗、踩了什麼坑、下次該怎麼做）。**觸發條件 = per-incident**（遇到棘手狀況/重要狀況/非預期方式解決後立刻寫），不是「每 N 實驗批次彙整」。判斷要不要寫：問「這件事下次我該怎麼做才不重犯？」——有答案就寫。每 5-10 實驗再補一條 session-arc summary 是輔助，不是主觸發
   - 不可只存 results JSON 而不進知識庫——2026-03 曾發現 85/124 實驗只有 results 但不在知識庫中
   - **Knowledge = 發現（what），Experience = 教訓（why + how to avoid）**
4. **文獻先於實驗，理解先於動手**：每個特定主題的研究開始前，**必須先搜尋並分析相關學術文獻**，不可直接憑直覺設計實驗。具體要求：
   - **搜尋**：用 WebSearch 搜尋 arXiv/SSRN/Google Scholar 該主題的關鍵論文（至少 3-5 篇）
   - **分析**：閱讀方法論、數據來源、核心發現、局限性。用 sci-hub skill 取得全文
   - **文獻探討**：整理已知結論（什麼已經被證實/否定？）、方法論選擇（前人用什麼方法？為什麼？）、我們的差異化（我們能做什麼不同的？）
   - **決定實驗設計**：基於文獻分析決定模型選擇、參數設定、評估指標，而非自行猜測
   - **記錄來源**：實驗腳本和結果 JSON 必須標注參考文獻（作者、年份、期刊、核心方法）
   - **例外**：純探索性實驗（沒有明確主題的跳躍式探索）可以先做再查文獻，但事後仍須補充文獻連結
5. **觀察先於計算，異常觸發覆查**：所有統計分析必須遵循「資料診斷 → 基本統計 → 估計 → 收斂檢查 → 延伸分析」的順序。具體要求：
   - **開始前**：描述性統計（均值/標準差/偏態/峰態）、ADF 定態檢定、ARCH LM 檢定、自相關（Ljung-Box）
   - **估計後**：收斂狀態（convergence flag）、參數有效性（persistence < 1）、殘差診斷（標準化殘差無剩餘 ARCH）
   - **結果異常時**：HE < 0、相關係數不穩定、parameter 在邊界上 → 必須啟動覆查，不能直接報告
   - **期貨避險特別注意**：spot-futures 相關性穩定性（rolling correlation）、共整合檢定、ETF 結構問題（如 USO contango roll）
6. **方法論嚴謹**：每個結論必須經過正規統計檢定（DM test、t-test、bootstrap），不可僅憑觀察就下結論。遵守 Harvey (2016) t>3.0 門檻
6b. **模型比較必須公平（Patton 2011 標準）**：不同類型的波動率模型必須在公平框架下比較，不可只用單一 target，不可只報告對自己有利的結果。VaR/ES 評估必須做正確的分配轉換，不可直接把預測值當 VaR。**技術細節（評估層次、VaR 轉換公式、backtesting 規格）見 `research_program.md` 的「模型比較公平性標準」和「經濟顯著性評估」段。**
7. **區分實證與理論**：明確標示每項分析屬於「實證分析（真實數據）」、「理論推導」或「模擬實驗」。不可混淆
8. **Null result 如實報告**：負面結果同樣重要，必須完整記錄。不可只報告成功、隱藏失敗
9. **發佈內容真實不虛**：Feed 文章、研究摘要、知識記錄的每一項數據和結論都必須可追溯到具體實驗腳本和數據
10. **承認局限**：每個發現都必須說明其局限性（樣本大小、OOS 期間、資產範圍、proxy 變數的假設）
11. **不可過度宣稱**：結論的強度不可超過證據支持的範圍。partial r=0.08 不可宣稱為「突破性發現」
12. **Lookahead Bias 檢查（最常見錯誤）**：所有策略回測必須確認信號 lag：
   - **Signal from t-1, return at t**：weight 基於昨天的 VIX，今天的 return
   - **禁止 same-day**：weight 基於今天 VIX × 今天 return = 未來資訊（lookahead）
   - 歷史教訓：K679 VIX Percentile Sharpe 1.68→修正 lag 後 0.355（100% artifact）
   - **不修改歷史數據**：K693 嘗試修改 9935 筆歷史 portfolio_return 導致更多問題（metrics 不同步、Supabase 不一致）→ 已 revert。正確做法是讓 forward tracking 自然修正
   - **Codex 審查已 4 次抓到 lookahead**（K618, K621, K679, K698）——同 session 犯 4 次相同錯誤
   - **實驗代碼寫完後、執行前，必須先讓 Codex 審查代碼**。不是跑完出結果才審。流程：寫代碼 → Codex 審 → 修正 → 才跑 → 記錄 → 才發文
   - **代碼中必須有明確的 `signal.shift(1)`**——lag 驗證靠代碼結構，不靠事後記憶
   - **Sharpe > 2x baseline = 幾乎一定有 bug**——先停下來檢查，不要先歡呼
   - **所有模擬或隨機值生成必須設定固定 seed**：`np.random.seed(42)` 或 `rng = np.random.default_rng(42)`。適用：Bootstrap、Monte Carlo、ABM、permutation test、random sampling、MCMC、train/test split、任何用到 `np.random`/`random` 的操作。沒有固定 seed 的結果無法重現，違反可追溯原則
13. **自我修正後回溯更新**：每次推翻或修正先前結論時，必須立即：
   - 搜尋已發佈文章中引用該結論的內容（用 grep 搜尋關鍵詞）
   - 在受影響文章頂部加入 `⚠️ 更正聲明（日期）`，說明修正內容
   - 更新 feed.json 和個別 report JSON 的 content/description
   - 同步到 Supabase（`supabase_sync.py full`）
   - 記錄到 `docs/error_log.md`（自我修正類）

## 專案簡介
Claude Code 驅動的自主研究系統，用於尋找給定資產的最佳波動率預測模型，並建立一般投資人可用的交易策略。

## 網站架構（v4 Supabase + Admin CMS + Mirror API）
完整細節與最新頁面 / schema / 資料流以 `docs/architecture.md` 與 `.claude/skills/admin-ops/references/architecture.md` 為準。

CLAUDE.md 只保留高層 source-of-truth：

- **前端（線上版）**：`frontend-v2-fix/`，部署於 `volpred-v3`
- **平台資料唯一源頭**：`storage/`
- **平台同步入口**：`scripts/supabase_sync.py` / `uv run volpred ops ...`
- **策略 metadata 唯一來源**：`daily_update.py` 的 `STRATEGY_REGISTRY`
- **每日策略更新**：`scripts/daily_update.py` 於台灣時間 08:03 執行
- **Mirror 記憶同步**：`MemorySystem._sync_to_remote()`

頁面、資料表、ops surfaces、job queue、deploy 拓樸等操作細節不再放在 `CLAUDE.md`。

### Skill 導覽
- **完整技能地圖**：見 `docs/skill-registry.md`
- **研究主流程**：`.claude/skills/autonomous-research/SKILL.md`
- **研究派工 / 策略上架 gate**：`autonomous-research/references/agent-orchestration.md`、`autonomous-research/references/strategy-launch-gate.md`
- **文章內容與圖表規格**：`.claude/skills/feed-publisher/SKILL.md`
- **平台 ops / 文章池 / cron / monitor**：`.claude/skills/admin-ops/SKILL.md`
- **deploy / runtime / session automation**：`.claude/skills/admin-ops/references/deploy-and-runtime.md`
- **會員問題審查與流轉**：`.claude/skills/member-questions/SKILL.md`
- **論文系列 workflow**：`.claude/skills/paper-stage-classifier/SKILL.md`、`.claude/skills/paper-review-cycle/SKILL.md`、`.claude/skills/paper-update/SKILL.md`
- **support gates**：`agent-result-verification` / `worktree-merge-verification` / `memory-health`

### 研究結論（非此處）
→ 所有研究結論、設計原則、K 編號詳情見 `research_program.md`「重大研究結論」段（5 條核心結論：VT 本質、50/50 SPY/GLD、Smooth-weight、Proxy-robust、VaR+ES）。CLAUDE.md 只放跨研究通用的操作規則（如 Token 節約、部署、排程），不放會隨實驗更新的研究結論。

### Token 節約規則（必須遵守）
- **⚠️ 禁止整檔讀取 `feed.json`（5.4MB = 135 萬 tokens）**。任何情況都不可 `Read("storage/reports/feed.json")`：
  - **批量文字修復**（LaTeX/Unicode/escape）：用 `jq` / `python -c` / `sed` 處理，不用 Claude 讀取
  - **主題查重**：用 `grep -i '關鍵詞' storage/reports/feed.json | head`
  - **需要理解語義才能修的情況**：先用 `jq` 篩出需要修的那幾篇 ID，再只讀個別 `storage/reports/{id}.json`
  - **發佈/同步**：已由 Python 腳本處理，不需要 Claude 讀取
- 同理，`knowledge.json`（1.3MB）也禁止整檔讀取，用 `grep` 或 `jq` 查詢

### 注意事項
- Feed 發文一律走 `feed-publisher`（thinking ≠ content）
- 時間對齊與跨市場規則以 `.claude/skills/autonomous-research/references/data-timing.md` 為準；涉及 `published_at` 比較一律用 UTC
- 外部數據來源與高風險資料陷阱以 `.claude/skills/external-data-sources/SKILL.md` 與 `taiwan-macro-data` 為準
- **不可遺漏的高風險規則仍保留**：
  - `paper_trading` 一律看 `portfolio_return`
  - `0050.TW` 實驗必須用 `clean_tw50_data`
  - TAIFEX 不可直接把 `TX1` 當永久連續合約；轉倉處理以 `external-data-sources` 規範為準
- deploy / runtime / reverse proxy 類問題優先看 `admin-ops` 與 `docs/zeabur-oauth-gotcha.md`

### 每日文章產出要求（摘要）

文章內容規格與圖表要求由 `feed-publisher` 負責；文章池、排程釋出、通知與節奏由 `admin-ops` 負責。

`CLAUDE.md` 只保留全域要求：

- 網站每日仍有 `general` / `research` / `daily` 三類產出目標
- 非時效性文章預設進文章池；事件驅動文章不可延遲
- 每篇文章都必須可追溯到真實圖表、資料來源與實驗腳本/結果

每日數量、audience 寫法、主題查重、圖表與來源模板、文章池節奏等細節，全部以下列 owner 為準：

- 文章內容、圖表、標註、主題查重、audience 寫法 → `.claude/skills/feed-publisher/SKILL.md`
- 文章池、釋出節奏、通知與平台 surfaces → `.claude/skills/admin-ops/SKILL.md`

## 論文
- 論文列表、版本命名、PDF slug → `docs/paper-guide.md`
- paper workflow 現在拆成 4 個 skill：
  - stage 判定 → `.claude/skills/paper-stage-classifier/SKILL.md`
  - review orchestration → `.claude/skills/paper-review-cycle/SKILL.md`
  - 修稿與同步 → `.claude/skills/paper-update/SKILL.md`
  - 內容品質 / citation / LaTeX review → `finance-paper-quality` / `citation-verifier` / `latex-academic-reviewer`
- 5 stages 仍維持：`early` / `draft` / `review` / `ready_for_submission` / `submitted`
- ⚠️ 修正完必跑 `uv run volpred ops paper-update --paper-id <id>`；不同步平台等於沒修

### 目前 STRATEGY_REGISTRY（摘要）
策略 metadata 唯一來源仍是 `daily_update.py` 的 `STRATEGY_REGISTRY`。完整清單、active/inactive 狀態、display order 與上下架流程見 `docs/strategy-registry.md`。
是否值得上架先看 `.claude/skills/autonomous-research/references/strategy-launch-gate.md`；真正 `upsert` / activation / 平台同步走 `admin-ops`。

### 上架必須通過的 5 項檢驗（摘要）

策略是否值得上架，現在以 `.claude/skills/autonomous-research/references/strategy-launch-gate.md` 為 runtime 母本。
高層原則只有一條：**同期間比較、Cross-OOS、Codex 審查、Sensitivity、MDD 五項都過，才 handoff 給 `admin-ops` 做平台上架。**

## 快速指令
完整命令表改以 `docs/quick-commands.md` 為準，`CLAUDE.md` 不再維護命令清單。

runtime routing：

- 研究與實驗 → `autonomous-research`
- 發文內容與圖表 → `feed-publisher`
- 平台 ops / strategy / question / paper metadata / deploy → `admin-ops`
- 論文 stage / review / update → `paper-*`

## 思維模式：永遠修流程，不修資料

**任何問題都不能用手動修正解決。** 必須追溯到底層流程，使修正可以自動化、流程化、規格化。

**絕對禁止的手動操作**：
- 直接改 JSON 檔案的 status/content/metadata → 用 ops CLI/API
- 用 session cron workaround 繞過 DB/系統限制 → 改 DB schema + 程式碼
- 手動 PATCH Supabase 修正資料 → 修正 sync 流程讓它自動正確
- 繞過文章池直接 `status=published` → 用 `release-pool-by-settings` 釋出

| 層次 | 錯誤做法 | 正確做法 |
|------|---------|---------|
| 資料錯誤 | 手動改 JSON/DB | 修正產生資料的程式碼，讓下次自動正確 |
| 發佈失敗 | 手動 sync 到 Supabase | 修正 publisher.py 讓它自動 sync + retry |
| 格式問題 | 手動修文章內容 | 修正 serialization 邏輯（如 `\\n` 雙重轉義）|
| 缺欄位 | 手動 PATCH DB | 修正 sync 函式讓它帶正確欄位 |
| 排版壞掉 | 手動清理 metadata | 修正 publisher.py 自動 sanitize |
| DB schema 不支援 | 用 session cron 繞過 DB 限制 | 改 DB schema（migration） + 改程式碼適配 |
| 流程缺失 | 手動逐篇操作 | 寫入 skill/config 讓流程自動化 |
| 節奏控制 | 手動釋出文章 | DB 設定 interval + cron 自動觸發 release-pool-by-settings |

**診斷三步驟**：
1. **問「為什麼會發生？」** — 找根本原因，不是症狀
2. **問「下次會不會再發生？」** — 如果會，修正流程
3. **問「能不能寫進 skill/code/config？」** — 讓修正永久化

**記錄要求**：每次根本修正後更新 Error Log + 寫入對應 skill/memory。

## 自主研究模式

研究主流程的 runtime 母本是 `.claude/skills/autonomous-research/SKILL.md`、`.claude/skills/autonomous-research/references/agent-orchestration.md`、`.claude/skills/agent-result-verification/SKILL.md`、`.claude/skills/worktree-merge-verification/SKILL.md`。

本段只保留全域原則：

- 研究永不停止；完成一個任務後要接續下一個有價值的研究動作
- 每個實驗前都必須做 error log 防錯、知識庫搜尋、文獻搜尋、K 編號衝突檢查
- 每個實驗完成後都必須經過驗證、記錄、回寫 `research_program.md`，再決定是否 handoff 發文或平台操作

## 活文件原則
以下文件會隨研究推展持續演化，應主動修改以反映最新狀態：
- **`CLAUDE.md`**：架構變更、新模型/策略、新發現 → 立即更新
- **`research_program.md`**：目標調整、新研究面向、約束修正 → 及時更新
- **`.claude/skills/`**：發現反覆出錯的流程 → 建立或修正 skill（不需要事先徵求同意，但必須遵守下方審查規則）
- **`research_findings.md`**：新的具體發現和數據 → 實驗後立即記錄
- **Memory files**：thinking/knowledge/questions → 每個發現後同步

修改原則：
- **新增補充內容**可以先做，但要記錄修改原因。
- **刪除或改寫既有治理內容**（`CLAUDE.md`、`research_program.md`、`.claude/skills/`、`docs/` 的既有規範）前，必須先取得使用者同意。

### Skill 自主管理與定期審查
- **建立/修正 skill 不需要事先徵求同意**——Claude 依據任務執行中累積的經驗自行判斷。但每次建立或修正必須在下次與用戶互動時主動通知。
- **完整 skill 註冊表 + scope boundaries**: `docs/skill-registry.md`（14 top-level skills，每個有 trigger phrases / 使用範圍 / handoff / 對應 CLAUDE.md 段落）
- **新增/刪除/改名/合併 top-level skill 時，必須同步更新 `docs/skill-registry.md`**。若該變更影響 `CLAUDE.md` 的導覽、職責邊界或流程入口，也必須同步更新 `CLAUDE.md`。
- **若 skill 變更會影響固定路徑、hooks、session 啟動 prompt 或 cron 工作流，必須一併檢查**：`.claude/settings.json`、`scripts/session_startup.md`、`.claude/commands/`、以及相關 skill references 是否仍指向正確路徑。
- **若只是 skill 內部 reference 細節或案例補充，通常更新 skill/reference 本身即可；不要為了小改動過度擴散到 `CLAUDE.md`。**
- **每月第一個 session 產出 Skill 審查報告**，內容包含：
  1. 目前所有 skill 清單（名稱、用途、上次觸發時間）
  2. 本月新增/修改的 skill 及原因
  3. 使用頻率低（上月 0 次觸發）的 skill → 建議合併或刪除
  4. 覆蓋不足的流程（反覆出錯但尚無 skill）→ 建議新增
  5. 與其他 skill 功能重疊的 → 建議合併
- **報告給用戶審閱**，用戶可據此增刪調整 skill

## 署名與歸屬
所有研究成果、發現、策略建議必須標注發起者：
- **Feed 文章**：摘要或首段標注 `[提出: Gemini/Codex/Claude/用戶, 執行: Claude]`
- **Knowledge 記錄**：content 開頭標注 `[提出: XXX, 執行: Claude]`
- **Open Questions**：記錄是誰提出的問題
- **論文**：作者為 Yi-Hao Lai + VolPred Research System，致謝 Codex/Gemini
- **研究方向**：記錄建議來源（例：N182 Excess Fear Signal 由 Gemini 提出）

## AI 協作模式（Claude + Codex + Gemini）
完整協作場景與命令表見 `docs/ai-collaboration.md` 與 `.claude/skills/autonomous-research/references/ai-collaboration.md`。

本段只保留高層分工：

- Claude：主線研究、整合、記錄、最終判斷
- Codex：針對性審查、第二意見、卡住時接手
- Gemini：方法論、文獻連結、robustness 建議

原則：

- 針對特定目標請第二意見，不做無目標全專案掃描
- 卡住、多次修錯、或需要結構性 challenge 時，立即請 Codex / Gemini 協助

### 研究主題來源（必須多元）
研究主題不可只靠 Claude 自選。runtime 規則與派工順序以 `.claude/skills/autonomous-research/references/agent-orchestration.md` 為準；`research_program.md` 仍是北極星。

## 自動化：cron + Monitor（session 啟動必建）

session 自動化與平台 cycle 的 runtime 母本是 `.claude/skills/admin-ops/SKILL.md`、`.claude/skills/admin-ops/references/deploy-and-runtime.md`、`.claude/skills/admin-ops/references/session-cron-workflows.md`。高層規則如下：

- Session cron / Monitor 都是 session-only；每次新 session 都要重建
- 啟動清單、cron cadence、platform cycle 細節 → `scripts/session_startup.md`
- 平台巡檢、文章池、question ranking、deploy/runtime 類工作一律優先走 `admin-ops`

## 硬體資源與 Agent Team
完整硬體資訊與 agent 容量見 `docs/hardware.md`。
實務上預設同時跑 `3-4` 個獨立 worktree agent；具體派工與模型選擇仍以 `.claude/skills/autonomous-research/references/agent-orchestration.md` 為準。

### 模型選擇原則（必須遵守）
模型選擇與 agent 派工的 runtime 規則改由 `.claude/skills/autonomous-research/references/agent-orchestration.md` 承接。
高層原則只保留兩條：

- 研究、統計、程式、論文相關工作預設用最強模型
- 簡單唯讀探索才降級；agent team 必須有明確邊界

### Agent Prompt 必備內容（不可省略）

**Agent 是空白的 Claude，只知道 prompt 裡寫的東西。** 詳細規範改由 `.claude/skills/autonomous-research/references/agent-orchestration.md` 承接。
高層規則只保留：

- 所有 agent prompt 都必須是完整 brief；experiment agent 必須讀 `experiment-preamble.md`
- feed / paper / worktree agent 都要明確指定 skill 與邊界；返回後主線程必須做 synthesis、驗證、合併、記錄

## 排程核心原則（操作細節見 `scripts/session_startup.md`）

排程與 cron 細節以 `scripts/session_startup.md`、`.claude/skills/admin-ops/references/deploy-and-runtime.md`、`.claude/skills/admin-ops/references/session-cron-workflows.md` 為準。高層規則：

- 系統 crontab / session cron 使用台灣時間；RemoteTrigger 固定 UTC
- 任何「繼續研究」型 cron 都必須落成真工作，不能只回 status check
- 實驗完成後仍必須走：審代碼 → 合併 / 驗證 → 記 knowledge / experience → 回寫 `research_program.md`

## 研究方法論與模型

**所有模型清單、策略績效數字、參數估計結果、評估指標定義 → 見 `research_program.md`**

CLAUDE.md 不放具體的 Sharpe/MDD 數字或模型參數值——這些會隨數據更新而過時。
研究約束（統計門檻、OOS 規範、Harvey threshold）見 `research_program.md` 約束區。

## 研究成果
**所有研究發現、實驗結果、Phase 進度、AI 協作建議 → 見 `research_program.md`（北極星文件）。**

CLAUDE.md 不重複研究內容。需要查閱研究結論時直接讀 `research_program.md`。
知識細節在 `storage/memory/knowledge.json`（1000+ 筆，含完整實驗條件和數據）。

## 網站優化待辦
→ 詳見 `docs/website-optimization-plan.md` + `docs/execution_backlog_2026-03-20.md`

## Error Log

**詳細記錄見 `docs/error_log.md`。** 每次根本修正後更新該檔案（問題、現象、過程、解決方法）。

**⚠️ 遇到任何 error 無法立即修好時，第一步永遠是先查 `docs/error_log.md`——同樣的問題可能已經解決過。不要重複踩坑。**
