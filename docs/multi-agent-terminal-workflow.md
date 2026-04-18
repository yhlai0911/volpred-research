# 多 Agent 作業模式：全系統通盤計劃（v4）

## 實作狀態（2026-04-18）

- **Phase C（Session Identity 正式化）**：✅ 已實作
  - `SESSION_KEY_SPEC = {"claude-supervisor", "claude-worker", "codex-worker"}` + `resolve_session_key()` helper
  - `AgentSession` 新增 `role` / `session_key` / `terminal_label`
  - `TaskRecord` 新增 `claimed_by_session_key` / `claimed_by_role`
  - `ExecutionReceipt` 新增 `session_key` / `role` / `signal_payload`
  - `storage/ops/agents/` 檔名改為 `{session_key}.json`；`--agent` 傳統參數繼續可用（自動映射到 worker role）
  - CLI：`heartbeat / session-bootstrap / claim-next / next-task / complete / fail / finish-task / session-shutdown` 全數新增 `--session-key` / `--role` / `--terminal-label` 選項
  - `ops agents` 表格顯示 session_key / agent / role / status / terminal_label
- **Phase B（Signal / Curate）**：✅ 已實作
  - `complete` / `fail` / `finish-task` 新增 `--signals-json` 選項，接受 JSON 字串或檔案路徑
  - `TaskRecord` 新增 `signal_payload` / `curated_by` / `curated_at` / `curated_promoted` / `curated_notes`
  - 新 CLI：`ops pending-curations`（列未 curate 的 succeeded 任務）、`ops curate <task_id> --actor --promoted --notes`
- **測試**：`tests/test_session_identity_and_curate.py` 16 個新 tests 涵蓋 resolve_session_key / 三 session 不互相覆蓋 / signal_payload round-trip / pending + curate 流程
- **階段 A（零工程量 3-terminal 試跑）**：改動已就緒，等用戶實際開 3 個 terminal 驗證

下方為 v4 原始規格（供背景參考）。

---

## Context

用戶原始 user story：VS Code 開 3 個 terminal（1 Codex + 2 Claude Code），1 個 Claude 當監督者（排程/派工/監看），另 1 個 Claude + 1 個 Codex 當工人（認領任務、登記完成）。監督者依結果更新排程與任務。

**v4 版本的根本改動：** 前 3 版都只看「派工/認領/完成」的機制層。用戶指出要**通盤考慮整個系統**，包含研究目標、任務種類、技能、網頁平台。本版是真正的 system-aware plan。

---

## 一、系統全景（Agent 工作流必須服務的全部）

### 1.1 研究面（北極星）

系統同時在跑 **7 條研究主軸**：
- A. 波動率預測（HAR、Rough Vol、Copula-GARCH、GARCH-X-VIX）
- B. VaR/ES 風險管理（Cornish-Fisher、EVT-GPD 已收斂）
- C. 投資策略（50/50、VT alpha、VIX 策略、台灣市場）
- D. 理論貢獻（Gamma、MDD vs Sharpe、Anti-tautology）
- E. 即時市場分析（危機追蹤、paper trading）
- F. 網站系統升級
- G. 跳躍式探索（NLP 情緒、因果推論、ABM）

**證據：**
- 9 篇論文活躍管線（Paper 1-3 R1 revision、Paper 6 near-submission、Paper 9 under review、Copula 決策點待用戶）
- 1129 個 K 編號實驗，最新 K1053
- 73 個 active task（pending + pending_main_thread + in_progress）

### 1.2 發佈面（使用者看到的）

**前端 `frontend-v2-fix/` 公開頁面：**
- `/` Feed（1015 篇文章，daily 更新）
- `/paper` 論文列表與 PDF 下載
- `/portfolio` Paper Trading（**near-real-time**，10 active strategies）
- `/questions` 會員問答
- `/vix-calculator`、`/risk-forecast`

**Admin 頁面（supervisor 介面）：** `/admin/content | strategies | analytics | questions | papers | paper-trading | ops | health | users | thinking`

**資料同步管線：** 本地 JSON → `/api/sync/[...path]` → Supabase → 前端 revalidate。**不可跳過 sync 手改 Supabase。**

### 1.3 任務分類（Task Family）

程式層定義於 `local_control_plane.py:18`，7 類 + agent 偏好：

| Family | 用途 | AUTO_PREFERRED_AGENT | 代表任務 |
|--------|-----|--------------------|---------|
| `research` | 實驗、估計、分析 | **claude** | K 編號實驗、模型比較 |
| `content` | 發文、文章改寫 | **claude** | feed-publisher、文章重寫 |
| `member` | 會員問答研究 | **claude** | question-claim → research → answer |
| `code` | 實作、refactor、debug | **codex** | 模組重構、bug fix |
| `review` | 代碼審查、論文審查 | **codex** | adversarial review、citation verify |
| `ops` | 平台營運、同步、監控 | **codex** | sync、recalc、health check |
| `strategy` | 策略上下架、參數調整 | **codex** | strategy-upsert、rollback gate |

**Brief 模板：** `config/brief_templates/` 8 個 YAML（research/review/code/ops/content/member/strategy/schedule-governance）。Template-first policy `C`：先套模板，例外才問 Claude。

### 1.4 技能層（17 Skills）

**主線必用（8）：**
- `autonomous-research`、`paper-review-cycle`、`feed-publisher`、`finance-paper-quality`、`latex-academic-reviewer`、`citation-verifier`、`paper-stage-classifier`、`paper-update`、`admin-ops`

**特殊 / 自動觸發（9）：**
- `worktree-merge-verification`（每次 worktree 完成強制執行）
- `agent-result-verification`（每次 agent 回 JSON 結果前強制執行）
- `external-data-sources`、`taiwan-macro-data`、`memory-health`、`member-questions`、`publication-candidates`、`academic-finance-reviewer`

**Worker 必讀的層：** brief（動態）+ preamble（靜態方法論）+ SKILL.md（scope boundary）。

### 1.5 排程面

`config/runtime_schedules.json` 含 14 項：6 system crontab + 2 remote triggers + 6 session crons。關鍵常態任務：
- `shared_scheduler_tick` 每 10 分鐘
- `collect_tw_data` / `collect_us_data` 每日市場時段
- `daily_update`（策略計算 + 績效重算 + Supabase sync）
- `release_pool` 每 2 小時釋出文章
- `platform-ops-patrol` 每 6 小時
- `question_research` 會員問題 6 小時 cron

### 1.6 治理與授權

**活文件（canonical，只有 supervisor 可改）：**
- `storage/memory/knowledge.json`
- `storage/memory/experiment_experiences.json`
- `storage/memory/thinking_journal.json`
- `research_program.md`、`docs/error_log.md`、`docs/project_improvement_status.md`
- `agent-specs/skills/`（新技能）
- `config/runtime_schedules.json`

**Worker 禁止寫共享狀態**（`AGENTS.md:160-164` 與 `CLAUDE.md` 既有規則延伸）。

**Approval gate**（`_requires_approval`）：strategy 變更、schedule governance、risk_level=destructive 自動攔截。

---

## 二、多 Agent 作業模型（Operating Model）

### 2.1 三個 Terminal 的真實職責

| Terminal | 身份 | 主要工作 |
|---------|------|---------|
| **T1: Claude Supervisor** | 主線（無 agent claim） | 1) 策略層：看 `control-plane-summary`、決派工 2) Curate：讀 worker completion signal → promote 到 canonical 活文件 3) Approval：處理 destructive / strategy / schedule 的 approval backlog 4) 論文決策（Paper 3 narrative、Copula 定位等待用戶決策點）5) 產下一批 brief（主要依賴 template，例外才手寫）6) 觀察前端 freshness（paper trading 有沒有 stale、feed 有沒有該補）|
| **T2: Claude Worker** | `agent=claude` | research / content / member family — 研究實驗、發 feed、會員問答、論文 .tex（論文一律 Claude 做）|
| **T3: Codex Worker** | `agent=codex` | code / review / ops / strategy family — 代碼審查、refactor、sync、recalc、策略上架審查 |

**身份衝突現實：** `LOCAL_AGENT_CHOICES = ("claude", "codex")` 只有 2 slot。如果 T1 要正式登記為 agent（跑 `session-bootstrap`），會覆蓋 T2 的 `claude` 心跳。

**解法（零程式碼）：** T1 supervisor **不登記為 agent**。它只做 supervisor 級 CLI（`tasks`、`agents`、`scheduler-*`、`assign`、`approve`、`control-plane-summary`、`hygiene-report`），並手動寫 canonical 活文件。

**未來升級（有預算再做）：** 擴充 `LOCAL_AGENT_CHOICES` 加 `claude-supervisor` / `claude-worker` / `codex-worker` + AgentSession 加 `role` 欄位。**但這不是今天能跑的前提**。

### 2.2 任務路由決策樹（Supervisor 用）

```
收到新 task →
  看 task.task_family：
    research / content / member → assign to T2 Claude Worker
    code / review / ops / strategy → assign to T3 Codex Worker
    paper .tex 寫作 → T1 自己做（rule: 不得丟 background agent）
    論文決策點 → T1 等用戶拍板，不派
    schedule governance → T1 自己做 + approval gate
  看 task.risk_level：
    destructive → approval gate，需用戶或 supervisor 明確 approve
  看 task.requires_worktree：
    true（experiments/kXXX/） → worker 在 worktree 做，完成跑 merge_worktree.sh
```

### 2.3 Signal → Curate Protocol（活文件治理核心）

**Worker 在 `complete` 時發結構化 signal**（JSON 字串塞進現有 `--summary`，零程式碼改動）：

```json
{
  "summary_text": "<一句話主結論>",
  "null_result": false,
  "knowledge_candidates": [
    {"topic": "...", "one_line_finding": "...", "evidence_paths": [...], "confidence": "strong|medium|weak", "codex_reviewed": true/false}
  ],
  "experience_candidates": [{"lesson": "...", "context": "..."}],
  "followup_task_candidates": [{"title": "...", "priority": "P3|P4", "rationale": "...", "preferred_family": "..."}],
  "skill_candidates": [{"name": "...", "signal": "..."}],
  "doc_update_needed": ["research_program.md"],
  "frontend_impact": {"pipeline": "paper_trading|feed|questions|none", "requires_sync": true/false}
}
```

**Supervisor curate 工作流（T1，每次回 prompt 前或空檔時）：**

1. `uv run volpred ops tasks --status completed` → 找 `curated_at` 為空的 receipt
2. 逐項判斷 promote：
   - knowledge → 寫 `knowledge.json`（去重 + 引用 K）
   - experience → 彙整到 `experiment_experiences.json`（5-10 實驗一條）
   - followup → `ops enqueue` 或新 TaskRecord
   - skill → `agent-specs/skills/` 新建（月度審查）
   - doc update → 改 `research_program.md` / `error_log.md`
   - frontend_impact → 若有 `requires_sync=true`，確認 worker 有跑 `supabase_sync.py`（沒跑就補跑）
3. Curate 完補 receipt：`curated_by=claude-supervisor, curated_at=<ts>, promoted=[...]`

### 2.4 前端 Freshness 管理

**Near-real-time（<5min）任務完成後必須立即 sync：**
- `paper_trading.json` 更新 → `/api/sync` POST → `replacePaperTrades()` + `refreshStrategyMetricsCache()`
- Worker 做完 `recalc-metrics` / `daily_update` → 結果在 result_summary 標 `requires_sync=true`，supervisor 驗證 sync 有跑

**Daily（可容忍到當日晚間）：**
- Feed 新文（`feed-publisher` 產）→ sync
- 會員問答回覆 → sync
- risk_forecast

**可接受 staleness（1-7 天）：**
- Paper metadata、knowledge viewer、memory dump

### 2.5 Approval Gate 處理

**會自動卡的任務：**
- Strategy 上下架（`strategy-upsert` + `strategy-set-active`）
- Schedule governance 變更
- `risk_level=destructive`
- Paper 重大決策點（narrative state machine，Copula 定位等）

**T1 Supervisor 每次上線必做：**
1. `ops tasks --status blocked` 看 approval backlog
2. 判斷能 `approve` 的就 approve、需要用戶拍板的留著、該 `reject` 的 reject
3. Paper 決策點要等用戶明確指示（CLAUDE.md 規定 ≥3 互補實驗 + Codex/Gemini review 才進 narrative decision）

---

## 三、Terminal 啟動 SOP

### 3.1 Terminal 1（Claude Supervisor）啟動模板

第一個 prompt 給 Claude：

```
你是 volpred-research 的 main supervisor。角色是 T1，不登記 agent 身份。

啟動檢查：
1. uv run volpred ops control-plane-summary
2. uv run volpred ops tasks --status blocked  (看 approval backlog)
3. uv run volpred ops scheduler-preview       (看下一輪排程)
4. uv run volpred ops agents                  (看 T2/T3 是否上線)
5. uv run volpred ops tasks --status completed (看未 curate 的 receipts)

主要職責：
- Curate worker receipts → promote 到 canonical 活文件
- 處理 approval backlog（destructive / strategy / schedule）
- 派 Paper 決策層任務（narrative、Copula 定位等）給自己
- 寫 paper .tex、governance 檔、新 skill
- 補 brief 給 T2/T3 的例外任務

活文件寫入職責（只有你能寫）：
- storage/memory/knowledge.json / experiment_experiences.json / thinking_journal.json
- research_program.md / docs/error_log.md / docs/project_improvement_status.md
- agent-specs/skills/ (新技能)
- config/runtime_schedules.json (governance)

禁止：
- 絕不跑 session-bootstrap / heartbeat --agent claude（會覆蓋 T2）
- 絕不直接寫 paper body 的 background agent（paper .tex 只能你親自寫）
```

### 3.2 Terminal 2（Claude Worker）啟動模板

```
你是 volpred-research 的 Claude Worker（T2）。身份：agent=claude。

專責 task family：research / content / member / 論文寫作

啟動：
1. uv run volpred ops session-bootstrap --agent claude

工作循環：
1. uv run volpred ops next-task --agent claude --emit-brief
2. 讀 brief_payload：
   - task_family 決定用哪個 skill（research → autonomous-research，content → feed-publisher，member → member-questions）
   - 若有 preamble（research 任務），讀 .claude/skills/autonomous-research/references/experiment-preamble.md
3. 徹底執行任務（可用內建 Agent/Edit/Write/Bash 工具平行）
4. 任務完成前判斷：
   - knowledge / experience / followup / skill / doc_update 信號
   - 是否 requires_sync（feed / paper_trading）
5. 整理成 JSON signal payload
6. uv run volpred ops complete <task_id> --summary '<json>'
7. 長任務每 5-10 分鐘 heartbeat
8. 回步驟 1

Worktree：experiments/kXXX/ 類任務優先走 scripts/merge_worktree.sh 流程

禁止寫共享狀態（AGENTS.md:160-164）：
- knowledge.json / experiment_experiences.json / research_program.md
- agent-specs/skills/ / config/runtime_schedules.json
- feed.json 直接改（走 feed-publisher skill）
```

### 3.3 Terminal 3（Codex Worker）啟動模板

```
你是 volpred-research 的 Codex Worker（T3）。身份：agent=codex。

專責 task family：code / review / ops / strategy

讀 AGENTS.md 獲得規範。特別注意：
- worktree 共享狀態禁寫（AGENTS.md:160-164）
- 代碼審查重點：目標一致？訓練評估公平？指標計算正確？scaling？

啟動：
1. uv run volpred ops session-bootstrap --agent codex

工作循環（與 T2 相同，但 agent=codex）：
1. uv run volpred ops next-task --agent codex --emit-brief
2. 讀 brief + 對應 skill（code → fresh_context_worker，review → code reviewer pattern）
3. 執行
4. 發 JSON signal payload
5. uv run volpred ops complete <task_id> --summary '<json>'
6. 長任務每 5-10 分鐘 heartbeat
7. 回步驟 1

若任務是 recalc-metrics / supabase_sync 類，完成後 signal 帶 `frontend_impact.requires_sync=true`

絕對禁止（AGENTS.md 明文）：
- 直接改 knowledge.json / experiment_experiences.json / research_program.md
- 直接改 agent-specs/skills/ / config/runtime_schedules.json
- 直接改 storage/reports/feed.json
```

---

## 四、Critical Files（只讀參考）

**控制面：**
- `src/volpred/cli.py:44` — `LOCAL_AGENT_CHOICES`（2 slot 限制）
- `src/volpred/cli.py:756-2030` — 所有 ops CLI 指令
- `src/volpred/ops/local_control_plane.py:18` — `TASK_FAMILIES` + AUTO_PREFERRED_AGENT
- `src/volpred/ops/execution_brief.py` — Brief builder + template router
- `src/volpred/ops/scheduler.py` — scheduler_tick（純 queue/state，無 subprocess executor）

**排程與模板：**
- `config/runtime_schedules.json` — 14 項 canonical schedule
- `config/brief_templates/*.yaml` — 8 個任務家族模板

**治理與技能：**
- `AGENTS.md:160-164` — 共享狀態禁寫清單（延伸到所有 worker）
- `CLAUDE.md` — 活文件原則、研究誠實原則、Codex 審查規則
- `agent-specs/skills/` — 17 個 skill canonical
- `.claude/skills/autonomous-research/references/experiment-preamble.md` — 研究任務 preamble
- `.claude/skills/autonomous-research/references/agent-brief-template.md` — brief 模板
- `scripts/merge_worktree.sh` — worktree 合併 SOP

**前端管線：**
- `frontend-v2-fix/app/api/sync/[...path]/` — 同步進入點
- Supabase tables: `articles` / `paper_trades` / `strategy_metrics_cache` / `questions` / `memory_entries`
- `scripts/supabase_sync.py` — sync 主腳本（CONFLICT_KEYS + whitelist 防護）

---

## 五、Verification（真的跑得起來）

**Phase 0：預演（不動 state，T1 內執行）**
```bash
uv run volpred ops control-plane-summary
uv run volpred ops tasks --status pending
uv run volpred ops tasks --status blocked
uv run volpred ops agents
uv run volpred ops scheduler-preview
ls config/brief_templates/
```

**Phase 1：最小端到端循環（用 1 個真實小任務）**
1. T1 選一個 `task_family=code` 的 pending task（或新建一個小的 ops 類任務）
2. T3 Codex 啟動 → `session-bootstrap --agent codex`
3. T3 `next-task --agent codex --emit-brief` → 確認拿到 brief
4. T3 執行 → 發 signal → `complete`
5. T1 `tasks --status completed` 看 receipt + signal payload
6. T1 curate：若有 knowledge candidate 就 promote，若有 followup 就 enqueue

**Phase 2：並行（T2 + T3 同時跑）**
1. T1 選一個 `research` task（給 T2）+ 一個 `code` task（給 T3）
2. T2 啟動 claude worker；T3 已在跑
3. `ops agents` 應顯示 2 個 active session（claude + codex）
4. 兩邊並行完成 → T1 依序 curate

**成功標準：**
- `storage/ops/agents/` 有 2 個 AgentSession（claude + codex）；T1 supervisor 不在裡面
- `storage/ops/tasks/` 至少 2 個 TaskRecord 完整走完 `pending → claimed → running → completed → curated`
- 至少 1 個 knowledge candidate 被 T1 promote 到 `knowledge.json`
- 若任務是 recalc 類，前端 `/admin/paper-trading` 反映新結果（sync pipeline 打通）
- 無重複 claim，無孤兒 lock

**失敗排查：**
- `hygiene-report`
- `storage/ops/writer_log.jsonl`
- Supabase sync log：`⚠️ {table} sync: ok=N fail=M`

---

## 六、分階段實施建議

### 階段 A：零工程量試跑（今天就能做）
- 用上面的 prompt 模板啟動三個 terminal
- 選 2-3 個小任務跑一輪端到端驗證
- 驗證：身份衝突、signal 傳遞、curate 流程、OAuth 配額實測
- 工程量：0

### 階段 B：輕量 CLI 增強（試跑順了之後）
- `complete` CLI 加 `--signals-json <file>` 選項（存 signal 到 TaskRecord 獨立欄位）
- 新增 `ops pending-curations` 查未 curate 的 receipts
- 新增 `ops curate <task_id> --promoted <list>` 登記 curation
- 工程量：2-4 小時
- 效益：supervisor curate 工作流有 CLI 支持，不用手工 grep

### 階段 C：Session Identity 正式化（有需求才做）
- `LOCAL_AGENT_CHOICES` 擴充為 `claude-supervisor` / `claude-worker` / `codex-worker`
- AgentSession 加 `role` / `session_key` / `terminal_label`
- TaskRecord 加 `claimed_by_role` / `claimed_by_session_key`
- `ops agents` CLI 顯示 role
- 工程量：4-8 小時
- 觸發條件：階段 A/B 跑過 1-2 週後，發現真的需要 3+ 個獨立 session identity（例如要開 4 個 terminal）

### 不要做的（Codex v1 計劃的 Phase 4）
- 「退役 headless executor」— `scheduler.py` 本來就沒有 subprocess `claude -p` / `codex exec`；只有 `execution_brief.py` 用 `claude -p` 產 brief（這是正當用途，不該退役）

---

## 七、與 Codex 版本（`docs/multi-agent-terminal-workflow-codex.md`）對比

**Codex 對的：** session identity 粒度不足（2 slot 不夠表達 supervisor/worker/codex-worker）、需要 role 欄位、建議的資料模型欄位方向

**Codex 錯的：** scheduler 不是 headless executor（grep 確認無 subprocess）、Phase 4 基於誤讀

**Codex 漏掉的（本 v4 補齊）：** 7 條研究主軸、17 skills、Brief template 層、前端 freshness SLA、sync pipeline、curate protocol、approval gate、活文件治理邊界、論文寫作規則、frontend impact signal

**所以：** 本 v4 計劃 ⊃ 我 v2 原版 ⊃ Codex Phase 1 核心 + 修正 Phase 4 誤讀 + 補齊 8 個 Codex 漏掉的維度
