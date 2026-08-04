# 自主波動率預測研究系統
原則上使用繁體中文互動

<!-- shared:Bootstrap 原則:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## Bootstrap 原則


這份 `CLAUDE.md` 只保留每次 session 都必須先知道的核心規則。它刻意維持精簡；較長的細節拆到：

- `docs/architecture.md`：網站架構、資料流、Supabase / Mirror / Admin surfaces
- `docs/quick-commands.md`：常用命令
- `docs/paper-guide.md`：論文版本、PDF slug、更新流程
- `docs/strategy-registry.md`：active strategies 與上架 gate
- `research_program.md`：研究北極星、重大發現、方法論約束、待辦方向
- `docs/error_log.md`：已知錯誤、教訓、根因修正
- `docs/project_improvement_status.md`：專案優化計劃狀態
- `config/project_targets.json`：active frontend / active service / runtime targets 唯一來源
- `config/runtime_schedules.json`：排程唯一來源
- `.claude/skills/`：工作流與 task-specific reference
- `.claude/rules/`：Claude 觸發對應 paths 時自動載入的規則

### Rule path-trigger 時序原則（2026-04-20 補）

**Path-scoped rule 只在內建 Read/open 命中 `paths:` 時 auto-load**；Bash 的 `rg`/`grep`/`jq`/`cat` 與 command 文字出現檔名**都不觸發**（2026-07-14 fresh-session A/B 驗證）。需要在 selection 前出現的規則，必須由 CLAUDE.md 一行 pointer、dispatch prompt 或顯式讀取 rule/skill 保證載入 — 禁止假設 Bash 查詢會觸發。改 rules paths 前先填 stage×paths 矩陣（memory `feedback_path_narrowing_audit`；歷史 incident：publish-checklist 6 次 dispatch 漏 5 次 dedup）。
<!-- shared:Bootstrap 原則:end -->

<!-- shared:研究誠實原則:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## 研究誠實原則（最高優先，不可違反）


**一切結果必須真實、嚴謹、可驗證。違反任何一條即視為研究失敗。**

1. **不可造假/虛構**：所有數據、統計量、圖表來自實際計算；每個實驗須標來源、期間、樣本數。
2. **實驗三件套**：`experiments/<id>/{README.md, <id>.py, <id>_results.json}` + 圖表/refs/專屬資料（如有）。知識庫與經驗庫同步寫 `storage/memory/{knowledge,experiment_experiences}.json`（`storage/memory/thinking_journal.json` 同屬共享狀態，worktree agent 一律禁改）。
3. **觀察 + 文獻先於計算**：非探索任務先查知識庫 + 至少 3 篇文獻；先做資料診斷 + 描述統計再估計。
4. **方法論正式檢定**：不看圖下結論；Harvey / DM / bootstrap / Patton 標準。實證/理論/模擬不混口徑。
5. **Lookahead 最高風險 + 隨機程序固定 seed**：代碼要有明確 `signal.shift(1)` 或等效 lag；bootstrap/MC/抽樣/train-test split 都 seed。
6. **Null result 如實報告、不過度宣稱、推翻舊結論必回溯更正**：失敗也是結果；結論強度不超過證據；更新文章、feed/report JSON、同步平台、寫 `docs/error_log.md`。

詳細版（13 條原版）在 git history commit 4d7d787c 之前；實驗規則另見 `.claude/rules/experiments.md`。
<!-- shared:研究誠實原則:end -->

<!-- shared:專案地圖:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## 專案地圖


- 本機多 agent 研究系統：Claude 偏主研究與整合，Codex 與 Antigravity (agy) 偏審查、第二意見、針對性修正與分擔工作。
- **AI CLI 可用性**：**Codex** `codex exec`（ChatGPT auth；中文 prompt 必 heredoc + stdin）✅；**agy** `agy -p "<prompt>"`（Google OAuth；agentic 加 `--dangerously-skip-permissions`）✅；**gemini_ask.py**（PAID API，僅作 agy fallback，每次呼叫自動 email + 記 usage log）⚠️。分工：agentic 多步 → Codex 或 agy；一次性問答 → agy 優先。已放棄 gemini-cli。細節/陷阱/診斷 SOP：codex-cli SKILL + memory `reference_dual_cli_availability`、`reference_antigravity_cli`。
- active frontend / Zeabur target 由 `config/project_targets.json` 決定；**先改 config，再改程式或文件。**
- 目前線上站點：`https://volpred.zeabur.app`
- 研究記憶雙寫：Supabase + Mirror API
- active 前端實作：`frontend-v2-fix/`
- 研究引擎與 ops CLI：`src/volpred/`
- 唯一本地資料源：`storage/`
- 論文：`paper/`
- 實驗：`experiments/`

高頻來源檔案：

- `research_program.md`：研究方向、重大發現、方法論與 backlog
- `docs/architecture.md`：架構與資料流
- `docs/error_log.md`：先前踩坑與防錯規則
- `docs/project_improvement_status.md`：優化計劃目前到哪
<!-- shared:專案地圖:end -->

<!-- shared:關鍵操作規則:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## 關鍵操作規則


### Source of Truth

- `storage/` 是本地唯一源頭 — 不手改歷史 JSON 修結果；paper_trading 不手補，讓 forward tracking / recalc 自然修正
- Frontend target / Zeabur service / paper public dir / Mirror 預設 URL → `config/project_targets.json`；排程 → `config/runtime_schedules.json`（不反推 cron）
- task/schedule sources：`storage/next_tasks.json` = pending queue（dispatcher 讀；終態 >3 天自動壓 tombstone + 歸檔 `storage/next_tasks_archive/`）；`storage/ops/` = execution receipts / audit trail；`config/runtime_schedules.json` + event_jobs + event_ledger = canonical schedule spec。完成同步 `scripts/sync_next_tasks_status.py`。完整分工與歷史：`.claude/rules/control-plane.md`。
- `storage/ops/handoff_latest.md` = 每小時 :50 自動產生的**統一任務池快照**，Codex / Claude / 互動 session 共用入口。開工只讀 §1–§9（第一條 `---` 以前）；候補區按任務關鍵字搜尋，歷史見 `storage/ops/handoff_archive/`。

### 永遠修流程，不修資料

- 不要直接改 JSON / DB 欄位來收尾。
- 不要用 session workaround 掩蓋 schema 或流程缺陷。
- 不要繞過正式 CLI / sync / publish 流程。
- 任何資料錯誤都要追到產生它的程式與流程。

### 問題結案五步 Gate（2026-07-22 owner 指令，不可妥協）

固定結案順序：**證據化症狀 → 判定根因層級 → 重構底層邏輯/流程/架構 → 重跑與回讀驗證 → 制度化寫回**。

1. 症狀與證據：讀 live source / log / receipt / 時間戳 / 上下游交接，不憑印象
2. 根因判定：定位到邏輯、流程契約、排程、狀態機、API、權限、checker 或架構；**根因不明只能標 blocked**
3. 底層修正：重構可重複執行的程式/流程/防呆；重跑、補檔、改文字、手動清 blocker 都只算止血
4. 回歸驗證：重跑案例 + 測試 + 用 API/DB/雜湊/下游 acknowledgement **回讀**
5. 制度化寫回：落入 script / contract / automation / skill / dashboard / 操作紀錄，同類錯誤不得再靜默發生

回報二態必分：**`contained`**（止血，不可宣稱完成）vs **`root_cause_fixed_and_verified`**（五步全過才是結案）。機械 owner = incident sustained-clean resolution（`src/volpred/ops/incident.py`）+ 3-Strike Rule；本段為上位口徑，progress_report 與 error_log 一律採此二態。

### Three-Strike Rule — 同類錯誤 / 同處 hang 三次就整體重構

**Trigger**：同一類錯誤（同根因、同症狀、同類 bug 模式）連續發生 **3 次** OR 同一處（同一 script / function / pipeline 節點）連續 hang 住 **3 次**。

**但 strike 3 是 LATEST 觸發點不是 ONLY 觸發點**（2026-05-16 用戶補強）：**一旦看見結構性 root cause（dual source、race condition、無 single-source-of-truth、無 lock、無 hang detect、wrong domain model 等），就立刻三層重構，不等次數累積到 3。** 「先 patch 再 observe 看會不會 strike 3」是被禁止的偷懶 reaction。

**禁止 reaction**：再 patch 一次、加一個 flag、塞一層 retry / try-except、寫一個 workaround / fallback、再 grep + sed 一次、「先記下來等下次再修」、「strike 1 不修等 strike 3」。**任何 surface-level patch 或拖延都不准。**

**強制 reaction**：從**底層邏輯（domain model / 狀態機 / 責任分配對不對）、流程（hand-off / failure mode / observability / recovery 有沒有系統性遺漏）、程式架構（該不該換實作技術 / 隔離邊界）**三層徹底翻掉重新優化。

**執行流程**：(a) error_log 標 `**3-STRIKE TRIGGER**` + 三次 incident 的 commit/timestamp → (b) 寫 `docs/refactor_plan_<topic>.md`（三層診斷 + 方案 + 廢棄面 + 驗證 gate）→ (c) 落地後廢棄原 patch 路徑（`_legacy/` 或刪），不留兩套 → (d) regression test 覆蓋三次觸發條件 → (e) commit 開頭 `refactor(3-strike): <topic>`。

### Anti-stacking（不疊床架屋，2026-07-02 owner 指令）

一個 concern 只有**一個 enforcement owner**；新增 gate/watchdog/hook 必須收編進既有機制，同 commit 把被取代的提醒層降級成一行 pointer。升級路徑：prose 提醒（strike 1）→ 機械 gate（strike 2+），機械化後 prose 縮 pointer。Layer map：`docs/governance/enforcement_layer_map.md`。

### CLI / Workflow 優先順序

- **CLI 首選入口**：`uv run volpred ops ...`
- 發文用 `feed-publisher`
- 論文更新用 `paper-review-cycle` / `paper-update`
- 研究與實驗協調用 `autonomous-research`
- 記憶與 drift 檢查用 `memory-health`

若你要改的是流程、規格、長期工作法，優先改：

- `.claude/skills/` + `.claude/rules/`（Claude Code 讀的）
- `docs/`
- `config/`
- 對應 Python / frontend 實作
<!-- shared:關鍵操作規則:end -->

<!-- shared:Token / Context 紀律:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## Token / Context 紀律


- **Session 開頭運營定位一律 `uv run python scripts/ops_snapshot.py`**（backbone / queue / pool / alerts / git 一份 JSON，0.4s）— 不用零散 ls / git status / jq 翻抽屜重建狀態（2026-07-14 WS1b：repo-navigation bash 曾佔一週 10.1M tokens）。
- **禁止整檔讀取** `storage/reports/feed.json`；用 `grep`、`jq`、單篇 `storage/reports/<id>.json`。〔Bash 側 L1 機械 deny：`cat/less/more feed.json·knowledge.json` 由 `.claude/hooks/pretooluse-bash-optimizer.sh` 攔截；內建 Read 側由 `scripts/hooks/read_context_budget.py` 自動 bound（非 deny）。細則唯一 owner = `.claude/rules/context-hygiene.md`〕
- `storage/memory/knowledge.json` 同理，禁止整檔讀取。
- 重複性流程靠 skill，不要每次把長 SOP 貼進主對話。
- 先看 [`docs/workflow-index.md`](/Users/yhlai0911/volpred-research/docs/workflow-index.md) 判斷 workflow / 執行模式，再按需讀對應 skill 全文；不要一開始就把多份長 SOP 全載入。
- **若新任務與當前上下文、已載入 skills、或目前正在處理的專案文件無直接關聯，必須另開一個乾淨的 sub-agent 處理。**
- 用 sub-agent 的目的是隔離大搜尋、大量 logs、文件探索與無關 side task，減少 context 汙染與 token 損耗。
- **外部論文 / 文件 / 法規 / 大型網頁 RAG → `/notebooklm`**（不要拉整篇 PDF/HTML 進 context）。觸發時機：cross-paper meta-eval、prior-art audit、reviewer R1 drafting、開新方向深挖文獻、paper intro 寫作、法規/公告查詢。**主線程已被授權自主**判斷需要哪些文獻、自主下載 PDF 上傳建主題式 notebook、自主 query 作 RAG（不必逐次徵詢）— 只有大量 quota 消耗（≥10 notebook 或 ≥50 sources）/ audio·video 生成 / 投稿決策仍需確認。完整 SOP 見 `~/.claude/skills/notebooklm/SKILL.md`；專案觸發時機 + 授權範圍細節見 user memory `reference_notebooklm_rag_workflow`。對比：自家 `knowledge.json` / experiments 用 LanceDB（`scripts/build_knowledge_index.py update`），不混用。
- **2026-07-09 投稿授權 supersession**：上句末尾「投稿決策仍需確認」已被老闆 msg 309 取代；方法、敘事、期刊與投稿時機由主線程以 acceptance probability 為目標自主決定，ready 後直接推進。只有登入/MFA、付款、法律聲明或作者親簽等不可代理外部輸入才回報 blocker。Canonical SOP：`paper-submission-pipeline`；memory：`feedback_paper_autonomy_optimize_acceptance`。
- `context_window.used_percentage` 行為邊界：
  - `<55%`：正常工作
  - `55-62%`：避免開新 noisy side task；優先 fork subagent 或先收斂
  - `62%+`：優先 `/compact`
  - `70%+`：除非正在收尾，停止開新主題；跨 task family 時優先新 session / `/clear`
<!-- shared:Token / Context 紀律:end -->

<!-- shared:實驗與研究流程:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## 實驗與研究流程


### 實驗前

讀 `docs/error_log.md` → 搜 `storage/memory/knowledge.json` 查相似 K → 至少 3 篇文獻 → 讀 `.claude/skills/autonomous-research/references/experiment-preamble.md` → agent brief 寫清動機/差異化/相關 K/防錯規則/成功標準。

### 實驗中

- 一律收 `experiments/<id>/`；`README.md` 必備
- 策略回測明確 lag；baseline 與新策略同 lag 慣例
- 公平比較遵守 `research_program.md` Patton / VaR+ES 標準
- Sharpe 遠高於 baseline 時先懷疑 bug

### 實驗後

Codex 審代碼 → 通過才寫 `knowledge.json` → 每 5-10 實驗彙整一條 `experiment_experiences.json` → 可發佈的排入文章/論文 workflow → 新方向回寫 `research_program.md`。

### 實驗 artifact gate（merge 與 CI 兩處都擋）

帶 archived `*_results.json` 的 `experiments/<id>/` 若少了 knowledge 條目或 `reproduce_spec.json`，
`scripts/check_experiment_artifacts.py` 會擋下 merge（`merge_worktree.sh`）與 push
（`.github/workflows/experiment-artifacts.yml`），並印出可直接執行的補救指令。

- 開工前自查：`python3 scripts/check_experiment_artifacts.py check --path experiments/<id>`
- knowledge 條目**只能主線程寫**（K1259）；數字一律從 `*_results.json` 程式化取得，不從 README 或 agent 摘要轉抄
- `code_trace` / `spec.entrypoint` 的 sha 與 byte size 取自同一次 run-time snapshot，**不可事後補**（K1708 教訓）
- 真的產不出 artifact 才寫 `config/experiment_artifact_exclusions.json`，且必須說明**為什麼做不到**——「之後再補」是 bug，不是理由

### Worktree / Agent

- Worktree agent 只產 `experiments/kXXX/` 檔；**禁改共享狀態**（`feed.json`、`storage/memory/*.json`、Supabase/Mirror sync）
- 完成後 agent commit，主線程用 `bash scripts/merge_worktree.sh` 合併
- **絕對禁止** `git worktree remove --force`〔L1 機械 deny：`.claude/hooks/pretooluse-bash-optimizer.sh` 已攔截〕
<!-- shared:實驗與研究流程:end -->

<!-- shared:發佈、論文、策略:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## 發佈、論文、策略


### 發佈

- Feed 文章一律走 `feed-publisher`，不要把 thinking 直接當成 content。
- 非時效性文章預設 `draft` 進池；事件驅動文章必須立即 `published`。
- 每篇文章都要有真正圖表，不可用 ASCII / 文字框冒充。
- 每篇文章都要標明數據來源與對應實驗。
- 主題重複檢查要在啟動寫作 agent 前完成。

文章細節與檢查清單：

- `.claude/rules/publishing.md`（選題 / 派工前顯式讀；Bash `rg`/`jq` 不會觸發 path rule）
- `.claude/skills/feed-publisher/SKILL.md`
- `docs/architecture.md`
- `research_program.md` 的發佈規範段

### 論文

- **禁止用 background agent 直接寫論文 `.tex`**；寫作與方法論決策要在主線程完成。
- 論文修訂標準流程：
  - 審查
  - 修正
  - 編譯
  - `uv run volpred ops paper-update --paper-id <id>`
- 版本、slug、同步細節看 `docs/paper-guide.md`。

### 策略

- 策略 metadata 與 active 狀態以 `STRATEGY_REGISTRY` + `docs/strategy-registry.md` 為準。
- 新策略上架前必須走同期間比較、cross-OOS、Codex review、sensitivity、MDD gate。
- 正式比較優先用 `scripts/evaluate_new_strategy.py`。
<!-- shared:發佈、論文、策略:end -->

<!-- shared:自動化與控制面:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## 自動化與控制面


**核心 dispatch 規則（inline 保留；2026-07-21 lane 重構後）**：
- **選擇順序機械化**（唯一 owner = `task_urgency` + `continue_task_dispatch` lane 排序）：老闆急件（boss 來源）FIFO 永遠第一 → 時效性任務（看 task_type 不看數字）→ 其餘 P2/P3 + 餓死保護 + 輪替。餓死保護只在剩餘 slots 運作，不可能逐出 lane head。
- **系統來源禁自封 P1**：入池 gateway 機械夾到 P2（`clamp_machine_priority_inflation`）。P1 只屬於老闆急件與時效任務；手動建時效任務仍寫 `priority: 1`（時效性 / 即時性研究與發文一律 P1，老闆 2026-07-12）。
- **一班 batch-drain 多任務**（老闆 2026-07-21 硬性指令）：完成一張後預算 ≥12 分鐘就接下一張，收班條件僅「無任務」或「不足以完整收尾一張」；批次單位是完整任務，做一半丟下一班照樣禁止。
- **生成端水位閘**：池深超標自動停產（`pool_pressure`，老闆四類白名單免閘）；同根因補救單由 incident 生命週期管理，不重複開單（`docs/refactor_plan_incident_lifecycle.md`）。
- 同一 K 編號禁止雙 agent — 派前 `ls experiments/` + **`ls .claude/worktrees/` 與 `ls .codex/worktrees/` 兩邊都查**（兩個目錄都是活的；先前兩份治理檔各只叫自己的 agent 查自己那邊，等於誰都沒查對方）
- Admin UI 是 **observer**，不是 canonical control plane；control plane 的真相在本機檔案與 ops layer
- **Cron skip 用 stub**（slot 滿 / agent 仍跑 → 回覆 ≤15 字）
- 每次 idle / discovery pass 必須產生可驗證輸出，不可空轉

**論文 narrative state machine（防 paper drift）**：
- 單一實驗不直接改 `paper/*/body.tex`，只更新 `research_program.md` + `knowledge.json`
- ≥3 互補實驗（OOS-verified + Codex reviewed）完成才進 narrative decision
- 用戶 confirm 後設 `status='decision_made_awaiting_body_rewrite'`，body rewrite 才開始

細節（排程 / next_tasks refill / control plane source of truth / Admin observer 角色）見：`config/runtime_schedules.json`、`scripts/session_startup.md`、`.claude/skills/admin-ops/references/scheduling.md`、`docs/architecture.md`。
<!-- shared:自動化與控制面:end -->

## Subagent / Skill 使用準則

- 常見重複流程優先做成 skill，不要讓主 guide 膨脹。
- 任務若只需要探索或驗證，優先用 read-only subagent。
- 任務若與目前對話主線無關，優先用 fresh-context subagent。
- Agent prompt 必須包含必要路徑、K 編號、error log 規則、成功標準與要讀的 skill。
- 標準模板：
  - brief：`.claude/skills/autonomous-research/references/agent-brief-template.md`
  - result：`.claude/skills/autonomous-research/references/agent-result-template.md`

### Matt Pocock flow — 規劃已經做完了，不要重跑

使用者明確要求依 Matt skills 選流程時，先讀 `ask-matt` router，依其 main flow／on-ramp
選擇 user-invoked skill，不可自行拼湊替代順序。安裝狀態一律以
`scripts/check_matt_skills_installation.py --json` 的實際 manifest 回讀為準（surface 說明見下方
「全域 skill surface」）。

**現有全域優化的 plan／spec／ticket 三份都已存在**：GitHub Issue #3（plan）→
`docs/refactor_plan_ops_master_2026_07.md`（spec）→ GitHub Issues #5~#36 `[Plan T*]`（tickets）。
使用者說「依先前規劃繼續」時，**不要**重跑 grill／to-spec／to-tickets —— 先讀 spec §7 與 ticket
blocking edge，從第一張未阻塞的 ticket 走 `implement` → `tdd` → `code-review`。只有 scope 確實
改變、且 owner 明確要求重新規劃時才回頭做規劃階段。

標示 `disable-model-invocation: true` 的 skill 只在使用者明確呼叫時啟動；其餘 model-invoked
skills 可按任務描述自動採用。建立或修改 skill 時以 `writing-great-skills` 的 predictability、
information hierarchy、completion criterion 與 single source of truth 為準。

<!-- shared:Agent skills:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## Agent skills

### Graphify code map — 定位問題先查圖，再讀原始碼

架構 / caller / 依賴 / legacy path / 影響面 / data-flow 問題，**先走 graphify，再讀命中的原始碼**。
它回傳的 scoped subgraph 通常遠小於 `GRAPH_REPORT.md` 或 raw grep output。

- **Canonical 入口**：`uv run python scripts/graphify_integration.py query "<question>"`
  （走它才會寫 retrieval-proxy usage record）。輔助：`graphify explain "<node_id>"` 列 caller/callee、
  `graphify path "A" "B"` 查關係。
- **兩張註冊圖**：root 與 `active_frontend`（後者在 `frontend-v2-fix/graphify-out/`）。前端行為要
  `--graph active_frontend`，不可從 root 圖推論。使用者打 `/graphify` 時，先用已安裝的 graphify skill。
- **用前看 freshness**：`graphify_integration.py status`；stale 就 `update --graph all`（AST-only、本機、無 API 成本）。
- 開始 graph work 先跑 `graphify reflect --if-stale`，並讀 `graphify-out/reflections/LESSONS.md`。
- 改完程式跑 `graphify update .` 讓圖跟上（AST-only，無 API 成本）。
- **`graphify-out/` 髒檔不是跳過 graphify 的理由**（它幾乎永遠是髒的）。只有當任務本身就是在處理
  過期或錯誤的 graph 輸出、或使用者明說不要用時才跳過。
- **Graphify 是 map，不是 proof**：所有結論必須回到 `source_location` 對應的原始碼、測試、runtime 驗證。
- 語料邊界由 `config/graphify_integration.json` 與 `.graphifyignore` 定義，不手動放寬；生成的
  `storage/`、experiments、論文產物與獨立的 active frontend 都**不算** root graph 的來源。
- `graphify-out/GRAPH_REPORT.md` 只在 query / path / explain 都撈不到足夠脈絡時才讀。

### 全域 skill surface（`$HOME/.agents/skills/`）

專案 skill 在 `.claude/skills/`；**另有一組全域 skill 住在 `$HOME/.agents/skills/`**，兩邊都可用。
全域組包含 `ask-matt`、`writing-great-skills`、`diagnosing-bugs`、`codebase-design`、
`design-an-interface`、`domain-modeling`、`tdd`、`code-review`、`to-spec`、`to-tickets`、
`grill-with-docs` 等。安裝狀態查 `uv run python scripts/check_matt_skills_installation.py --json`。

這個全域 home surface **不等於** repo 內已退役的 `.agents/skills/` 副本（gate:
`tests/test_skill_surface_single_source.py`），禁止因而復活後者。

### Path ownership — Codex loop 與主線程的分工（2026-07-26 立）

`scripts/codex_loop.sh` 每小時常駐 tick，與主線程從**同一個** `storage/next_tasks.json` claim 任務。
`git_writer_lock` 只擋「同時寫壞」，**不擋「各自 lock、各自 commit、設計往兩個方向走」**。
動 `src/volpred/ops/**`、`supabase/migrations/**`、`scripts/dispatch_supervisor/**`、`tests/**`
之前，先 `git log -5 --oneline -- <path>`：最近有 `[codex]` 就先協調，`git status` 非空代表
Codex 這個 tick 正在寫，等他 commit 完再動。三區分工表（Codex 專屬 / 主線程專屬 / 共用）與
plan-spec-ticket 現況：`docs/agents/ownership.md`。

### Issue tracker

本專案使用 GitHub Issues 追蹤工程工作。See `docs/agents/issue-tracker.md`.
Runtime task 的 `succeeded` 預設只代表 slice 完成並保持 issue
`contained/OPEN`；只有整張 issue 的 acceptance 與五步 Gate 全過，才可在
`task_pool_claim.py complete` 明確傳 `--issue-disposition close`。

GitHub CLI 已安裝於 `/opt/homebrew/bin/gh`。非互動 shell 可能沒有
`/opt/homebrew/bin`，因此 `gh: command not found` **不代表未安裝**：先跑
`zsh -lic 'command -v gh'` 或直接使用 `/opt/homebrew/bin/gh`。只有固定路徑與 login
shell 都確認不存在後才可討論安裝；禁止因 PATH 漏載而重裝或回報 CLI 不存在。
Supabase CLI 同樣已安裝於 `/opt/homebrew/bin/supabase`。任何 Homebrew CLI 出現
`command not found` 時，一律先檢查 `/opt/homebrew/bin/<tool>` 與 login shell，再判定
是否真的缺少；automation／wrapper 使用已驗證的絕對路徑，不依賴互動 shell PATH。

### Triage labels

使用五個預設 triage roles 與同名 GitHub labels。See `docs/agents/triage-labels.md`.

### Domain docs

本專案採 single-context domain documentation layout。See `docs/agents/domain.md`.
<!-- shared:Agent skills:end -->

<!-- shared:活文件原則:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## 活文件原則


內容變了就更新對應母本：架構 → `docs/architecture.md` + `config/project_targets.json`；排程 → `config/runtime_schedules.json`；研究方向 → `research_program.md`；根因/教訓 → `docs/error_log.md`；優化進度 → `docs/project_improvement_status.md`；重複性 SOP → `.claude/skills/`；Claude rules → `.claude/rules/`。

可以直接新增補充內容；但**刪除或改寫既有治理規範前，先取得使用者同意。**
<!-- shared:活文件原則:end -->

## Codex 每小時任務池工作流（2026-05-25 新增）

**你（Codex）作為 peer worker 與 Claude Code 並行**，共用同一個任務池 `storage/next_tasks.json`，
透過 **claim 機制 cross-process atomic**（`fcntl.LOCK_EX`）避免撞題。

### Step 0 — 開工必讀 handoff
```bash
sed -n '1,/^---$/p' storage/ops/handoff_latest.md
```
看 section 1 任務池快照 / section 3 email_reply 待處理 / section 4 pending top 8；候補區不要全文載入，僅按任務 id / K-id / 關鍵字搜尋。

### Step 1 — claim 一個你能勝任的 pending task

```bash
# 列 pending top 10
uv run python scripts/task_pool_claim.py list --status pending --limit 10

# Codex 只看自己可接的 pending
uv run python scripts/task_pool_claim.py list --status pending --codex-eligible --limit 10

# claim（owner 命名建議：codex-vscode / codex-cli / codex-review-<topic>）
uv run python scripts/task_pool_claim.py claim --id <task_id> --owner codex-vscode
```

- `{"ok": false, "reason": "already_claimed"}` → Claude 或他人已 claim → **換下一筆**（禁強推、禁 release 別人的 claim）
- `{"ok": false, "reason": "wrong_status"}` → succeeded/failed/blocked → 換下一筆
- `{"ok": true}` → 進 Step 2

### Step 2 — start → 執行 → complete

```bash
uv run python scripts/task_pool_claim.py start --id <task_id>
# ... 執行任務（完整完成、不留半成品）...
# 預設 contained：task 成功但 GitHub issue 保持 OPEN
uv run python scripts/task_pool_claim.py complete --id <task_id> --status succeeded --result "<2-3 行摘要>"
# 只有整張 issue 的 acceptance + 五步 Gate 全過才可追加：
#   --issue-disposition close
```

中途要放棄（誤抓 / 不適合做）：
```bash
uv run python scripts/task_pool_claim.py release --id <task_id>
```

### Codex 適合做的 task_type

> Canonical 對照表：`.claude/rules/task-routing.md` — 12 types × claim/concurrency/skill 完整列表。本節是摘要。

| ✅ 適合 | ❌ 留給 Claude |
|---|---|
| `platform_ops` bug fix / refactor | `paper_body` 寫 .tex |
| `experiment` 跑既有 README brief | `paper_decision` narrative |
| `governance` 小型流程修整 | `knowledge.json` 寫入（必走 Python writer + K1259 gate）|
| `code review` | `event_article` 即時事件 |
| `daily_article` 寫作（需先讀 `.claude/skills/anti-ai-style/`）| `member_qa`、`trending_repost`（Claude skill canonical）|
|  | 標 `pending_main_thread` 的 task |

### email_reply 任務（**Codex 跳過**，Claude 主線程專屬）

`task_type=email_reply` 是用戶 Gmail 回信自動入池的任務（filter: from owner + Re: + 含 `[VolPred`）。

**Codex 不接這類 task**，原因：
- 需要寄 plan email 與 close email — `send-alert` 行為要一致由主線程掌握
- 需要跨 tick 追蹤 linked sub-tasks 狀態

**但 Codex 可接 email_reply 衍生的 sub-tasks** — Claude 在 Phase 0.B Step 3 規劃時會建 linked sub-tasks（task description 內含 `parent_email_task_id`，task_type 為一般 platform_ops/experiment/governance 等）。這些 sub-tasks 你**可以正常 claim 處理**，幫忙加速消化。

完成 sub-task 後 claude 主線程下次 tick 會偵測「parent_email_task_id 的所有 linked subs 都 succeeded」→ 自動寄 close email + complete parent。

### Stale claim 自動退回

每小時 :50 `cron_handoff_regen.sh` 跑 `cleanup --stale-hours 2` — **claim 超過 2 小時沒
complete/release 自動退回 pending**。所以 VSCode 關掉或 crash 不會永久卡住任務，但**請優先自己 release**。

### Commit 慣例

- 改動 commit 訊息開頭加 `[codex]` 與 Claude 區分
- 共用 main checkout 禁止裸跑 `git add` / `git commit`〔L1 機械 deny：`.claude/hooks/pretooluse-bash-optimizer.sh:148-150`，涵蓋 stage/merge/checkout/ref 全 mutation；registered linked worktree 不受攔截〕；完整交易一律走：
  `uv run python scripts/git_writer_lock.py commit --actor <owner> --task-id <id> --message '<ASCII message>' -- <exact paths>`
  （已 complete 且帶 `issue_ref` 的 task 必須傳 `--task-id`；多 task 可重複）
  （worktree 整合走 `bash scripts/merge_worktree.sh`，它會持有同一把 common-dir lock）
- **不要 `git push`** — 由用戶或 Claude 主線程統一推

---

<!-- shared:一句話版本:begin -->
<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。請改 canonical 來源，不要直接改這裡。 -->
## 一句話版本


- 系統由 AI 完全運營，執行階段不問用戶 — 遇問題自行修流程、優化邏輯。
- 先查 error log、知識庫、文獻，再做實驗。
- 先修流程，不修資料。
- 先讓 Codex 審代碼，再信結果。
- 任務無關當前上下文時，開乾淨 sub-agent，不要污染主線程。
<!-- shared:一句話版本:end -->

