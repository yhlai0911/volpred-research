# 自主波動率預測研究系統
原則上使用繁體中文互動

## Bootstrap 原則

這份 `AGENTS.md` 只保留每次 session 都必須先知道的核心規則。它刻意維持精簡；較長的細節拆到：

- `docs/architecture.md`：網站架構、資料流、Supabase / Mirror / Admin surfaces
- `docs/quick-commands.md`：常用命令
- `docs/paper-guide.md`：論文版本、PDF slug、更新流程
- `docs/strategy-registry.md`：active strategies 與上架 gate
- `research_program.md`：研究北極星、重大發現、方法論約束、待辦方向
- `docs/error_log.md`：已知錯誤、教訓、根因修正
- `docs/project_improvement_status.md`：專案優化計劃狀態
- `config/project_targets.json`：active frontend / active service / runtime targets 唯一來源
- `config/runtime_schedules.json`：排程唯一來源
- `.claude/skills/`：工作流與 task-specific reference（Codex subagent 經 codex-rescue 派工時可讀專案內任何檔）

## 研究誠實原則（最高優先，不可違反）

**一切結果必須真實、嚴謹、可驗證。違反任何一條即視為研究失敗。**

1. **不可造假、不可虛構**：所有數據、統計量、圖表必須來自實際計算。
2. **數據來源透明**：每個實驗必須標明資料來源、期間、樣本數。
3. **實驗三件套不可缺**：
   - `experiments/<experiment_id>/README.md`
   - `experiments/<experiment_id>/<experiment_id>.py`
   - `experiments/<experiment_id>/<experiment_id>_results.json`
   - 另加圖表、參考文獻、專屬資料（如有）
4. **知識庫與經驗庫要同步**：
   - `storage/memory/knowledge.json` 記錄發現了什麼
   - `storage/memory/experiment_experiences.json` 記錄學到了什麼
5. **文獻先於特定主題實驗**：非純探索任務，先做知識庫檢索與學術文獻搜尋，再設計實驗。
6. **觀察先於計算**：先做資料診斷與描述統計，再做估計、收斂與殘差檢查。
7. **方法論必須有正式檢定**：不要只看圖下結論；遵守 Harvey / DM / bootstrap / Patton 標準。
8. **區分實證、理論、模擬**：不可混用口徑。
9. **Null result 如實報告**：失敗也是結果。
10. **承認局限，不可過度宣稱**：結論強度不能超過證據。
11. **Lookahead bias 是最高風險**：
   - `signal from t-1, return at t`
   - 禁止 same-day 訊號乘 same-day 報酬
   - 代碼裡要有明確 `signal.shift(1)` 或等效 lag
12. **隨機程序必須固定 seed**：bootstrap、Monte Carlo、抽樣、MCMC、train/test split 都一樣。
13. **推翻舊結論時必須回溯更正**：更新文章、feed / report JSON、同步平台、寫入 `docs/error_log.md`。

## 專案地圖

- 本機雙 agent 研究系統：Claude 偏主研究與整合，Codex 偏審查、第二意見、針對性修正。
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

## 關鍵操作規則

### Source of Truth

- `storage/` 是本地唯一源頭；不要手改歷史 JSON 來「修結果」。
- Paper trading 歷史資料不可手補；讓 forward tracking / recalc 流程自然修正。
- 前端 target、Zeabur service、paper public dir、Mirror 預設 URL 全看 `config/project_targets.json`。
- 排程唯一來源是 `config/runtime_schedules.json`；不要從舊文件反推 cron。
- **正式 task / schedule source of truth**（2026-05-04 audit 確認的實際分工）：
  - **`storage/next_tasks.json`** = **canonical pending queue**（priority sorted；dispatcher 從這挑下個任務派工）
  - **`storage/ops/`** TaskRecord / AgentSession / ExecutionReceipt = **execution receipts / audit trail**（已完成 history，不是 pending queue）
  - `config/runtime_schedules.json` + `event_jobs` + `storage/ops/event_ledger/` = canonical schedule spec
- **`storage/ops/handoff_latest.md`** = 每小時 :50 自動產生的**統一任務池快照**（Codex / Claude / 互動 session 共用入口）— 開工前必讀

### 永遠修流程，不修資料

- 不要直接改 JSON / DB 欄位來收尾。
- 不要用 session workaround 掩蓋 schema 或流程缺陷。
- 不要繞過正式 CLI / sync / publish 流程。
- 任何資料錯誤都要追到產生它的程式與流程。

### CLI / Workflow 優先順序

- **CLI 首選入口**：`uv run volpred ops ...`
- 發文用 `feed-publisher`
- 論文更新用 `paper-review-cycle` / `paper-update`
- 研究與實驗協調用 `autonomous-research`
- 記憶與 drift 檢查用 `memory-health`

若你要改的是流程、規格、長期工作法，優先改 canonical：

- `.claude/skills/`（Codex plugin 讀的）
- `docs/`
- `config/`
- 對應 Python / frontend 實作

## Token / Context 紀律

- **禁止整檔讀取** `storage/reports/feed.json`；用 `grep`、`jq`、單篇 `storage/reports/<id>.json`。
- `storage/memory/knowledge.json` 同理，禁止整檔讀取。
- 重複性流程靠 skill，不要每次把長 SOP 貼進主對話。
- **若新任務與當前上下文、已載入 skills、或目前正在處理的專案文件無直接關聯，必須另開一個乾淨的 sub-agent 處理。**
- 用 sub-agent 的目的是隔離大搜尋、大量 logs、文件探索與無關 side task，減少 context 汙染與 token 損耗。

## 實驗與研究流程

### 實驗前必做

1. 先讀 `docs/error_log.md`
2. 搜尋 `storage/memory/knowledge.json`，確認是否已有相似 K
3. 搜尋相關文獻（至少 3 篇）
4. 讀 `.claude/skills/autonomous-research/references/experiment-preamble.md`
5. 在 agent brief 中寫清楚：
   - 動機
   - 差異化
   - 相關 K 編號
   - 防錯規則
   - 成功標準

### 實驗中必守

- 每個實驗一律用 `experiments/<experiment_id>/` 收納。
- `README.md` 是必備，不可省略。
- 策略回測要明確 lag；baseline 與新策略要用同一個 lag 慣例。
- 公平比較遵守 `research_program.md` 的 Patton / VaR+ES 標準。
- Sharpe 遠高於 baseline 時先懷疑 bug，不要先慶祝。

### 實驗後必做

1. **先做 Codex 審查代碼，再信結果**
2. 通過後才寫入 `knowledge.json`
3. 每 5-10 個實驗彙整一條 `experiment_experiences.json`
4. 有可發佈價值的結果，立刻排入文章或論文工作流
5. 新方向回寫 `research_program.md`

### Worktree / Agent 規則

- Worktree agent 只應產出 `experiments/kXXX/` 內檔案。
- Worktree agent **禁止修改共享狀態**：
  - `storage/reports/feed.json`
  - `storage/memory/knowledge.json`
  - `storage/memory/thinking_journal.json`
  - `storage/memory/experiment_experiences.json`
  - Supabase / Mirror sync 流程
- Worktree agent 完成後要 commit。
- 主線程再用 `bash scripts/merge_worktree.sh` 合併。
- **絕對禁止** `git worktree remove --force`。

## 發佈、論文、策略

### 發佈

- Feed 文章一律走 `feed-publisher`，不要把 thinking 直接當成 content。
- 非時效性文章預設 `draft` 進池；事件驅動文章必須立即 `published`。
- 每篇文章都要有真正圖表，不可用 ASCII / 文字框冒充。
- 每篇文章都要標明數據來源與對應實驗。
- 主題重複檢查要在啟動寫作 agent 前完成。

文章細節與檢查清單：

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

## 自動化與控制面

- 任務優先順序：`user-assigned > scheduled > agent-discovered`（只決定「誰先被挑」，不要求序貫執行）
- 研究續跑採 `slot-aware idle-driven continuation`（2026-04-17 放寬；M1 Max 10 核建議 4 並行 agent，保留 1 核給主線程）
- **不必等 queue 清空才 discovery**；slot 有空（running < 4）就允許挑新任務；優先序仍為 user > scheduled > discovery
- 同一 K 編號 / task id 不得同時被兩個 agent 執行（啟動前 `ls experiments/` + `ls .codex/worktrees/` 檢查）
- 每次 idle / discovery pass 必須真的產生可驗證輸出，不可空轉
- **Cron skip 用 stub** — slot 滿或 agent 仍在跑時，回覆 ≤15 字省 token（例：`跳過：slot 4/4`）
- **next_tasks 主動補滿**（2026-04-17）：每次 cron tick check，若 P4 pending < 2 **或** P3 pending < 5，主動從 `research_program.md` / knowledge.json / 最近實驗 NULL 衍生新任務補齊；不必等 queue 清空才 refill。
  - 這裡的「補滿」指的是 discovery / planning view 的補充；正式可執行任務仍要 materialize 進 `storage/ops/` control plane。若同步 `storage/next_tasks.json`，也只屬 legacy working list，不是 canonical queue。
- **論文 narrative state machine**（防 Paper 2/4 單一實驗觸發反覆 pivot）：
  - 單一實驗不可直接改 paper body.tex — 只能更新 `research_program.md` + knowledge.json
  - 必須 ≥ 3 個互補實驗（OOS-verified + Codex/Gemini reviewed）都完成才進 narrative decision
  - 決策 user confirm 後設 `status='decision_made_awaiting_body_rewrite'`，body rewrite 才開始
- Admin 目前是 observer，不是 canonical control plane；control plane 真正 source of truth 在本機檔案與 ops layer

排程與控制面細節：

- `config/runtime_schedules.json`
- `scripts/session_startup.md`
- `docs/architecture.md`
- `docs/project_improvement_status.md`

## Subagent / Skill 使用準則

- 常見重複流程優先做成 skill，不要讓主 guide 膨脹。
- 任務若只需要探索或驗證，優先用 read-only subagent。
- 任務若與目前對話主線無關，優先用 fresh-context subagent。
- Agent prompt 必須包含必要路徑、K 編號、error log 規則、成功標準與要讀的 skill。
- 標準模板：
  - brief：`.claude/skills/autonomous-research/references/agent-brief-template.md`
  - result：`.claude/skills/autonomous-research/references/agent-result-template.md`

## 活文件原則

以下內容變了，就應該更新對應母本：

- 架構 / runtime target / 資料流：`docs/architecture.md`、`config/project_targets.json`
- 排程：`config/runtime_schedules.json`
- 研究方向與重大發現：`research_program.md`
- 根因修正與教訓：`docs/error_log.md`
- 專案優化進度：`docs/project_improvement_status.md`
- 重複性 SOP：`.claude/skills/`

可以直接新增補充內容；但**刪除或改寫既有治理規範前，先取得使用者同意。**

## Codex 每小時任務池工作流（2026-05-25 新增）

**你（Codex）作為 peer worker 與 Claude Code 並行**，共用同一個任務池 `storage/next_tasks.json`，
透過 **claim 機制 cross-process atomic**（`fcntl.LOCK_EX`）避免撞題。

### Step 0 — 開工必讀 handoff
```bash
cat storage/ops/handoff_latest.md
```
看 section 1 任務池快照 / section 3 email_reply 待處理 / section 4 pending top 8。

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
uv run python scripts/task_pool_claim.py complete --id <task_id> --status succeeded --result "<2-3 行摘要>"
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
- **不要 `git push`** — 由用戶或 Claude 主線程統一推

---

## 一句話版本

- 先查 error log、知識庫、文獻，再做實驗。
- 先修流程，不修資料。
- 先讓 Codex 審代碼，再信結果。
- 先改 canonical，再 render 產物。
- 任務無關當前上下文時，開乾淨 sub-agent，不要污染主線程。
