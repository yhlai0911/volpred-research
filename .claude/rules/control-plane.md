
---
paths:
  - "src/volpred/ops/**/*"
  - "storage/ops/**/*"
  - "config/runtime_schedules.json"
  - "scripts/session_startup.md"
  - "docs/project_improvement_status.md"
---

# Control Plane Rules

- 本機控制面優先順序固定：`user-assigned > scheduled > agent-discovered`。
- 目前正式 runtime 是：`單一主線程 Claude Code` + `按需啟動的 Codex rescue / subagent`；不要再把 `claude-worker` / `codex-worker` 視為 standing worker runtime。
- 排程唯一來源是 `config/runtime_schedules.json`；不要讓舊 guide 或歷史報告變成另類 source of truth。
- `storage/ops/` 內的 task / approval / execution / rollback 檔案是控制面資料，不要手動亂改收尾。
- `storage/next_tasks.json` 只屬 legacy planning / working list，不是 canonical queue，也不可覆蓋 `storage/ops/` 狀態。
- `uv run volpred ops scheduler-tick` 的 executor lane 目前只做 advisory snapshot / would-dispatch 報告；正式 task claim/finish 必須來自主線程 direct dispatch 或明確 bootstrapped session。
- Session cron 與 system crontab 需與 canonical runtime schedule 一致。
- Admin UI 目前是 observer；如果 UI 與 canonical spec 不一致，以 canonical spec / local state 為準。

## Universal piggy-back scheduler（2026-04-20 canonical）

**macOS host cron daemon 只可靠執行 `0 * * * *` pattern**（驗證於此 machine，所有其他 pattern 包括 `* * * * *`、`3 */2`、`0 8 * * 1`、`3 7 * * 2-6` 皆 silently skip）。根本解 = 把 **check_alerts** (`0 * * * *`) 當作唯一可靠 trigger，在其啟動 hook 呼叫 **`scripts/run_due_jobs.py`** 作 universal dispatcher。

- Canonical schedule source: `config/runtime_schedules.json`（不變）
- Per-job last-run state: `storage/ops/cron_last_run.json`（UTC ISO timestamps）
- Timezone: host crontab 使用 local time (`Asia/Taipei`)；scheduler 評估 due 必須用 LOCAL_TZ
- Subprocess timeout: 600s per job
- Sequential invocation: 避免同時跑多個 yfinance / heavy job
- Skip list: `check_alerts`（recurse）、`shared_scheduler_tick`（advisory）、`host_crontab_managed: false`

**工作流**：
1. Host cron `0 * * * *` fires `cron_check_alerts.sh`（唯一可靠）
2. `check_alerts.py` main() 啟動先呼叫 `run_due_jobs()` 
3. Iterate canonical schedule, croniter 評估每 job 的 prev scheduled fire vs last_run
4. Due → subprocess-invoke wrapper，log 寫同檔案、exit code 同 semantics
5. Success 更新 last_run；failure 不更新（下小時再評估、避免 silent skip whole day）
6. **`run_due_jobs` 尾端再呼叫 `expand_due_event_jobs`**（2026-04-20 新增）— 把 `event_jobs.items` 中 `not_before ≤ now ≤ deadline` 的條目 materialize 成 control-plane task。原設計這由 `shared_scheduler_tick` 呼叫但該項目被降級 advisory 後 host 端並未真 fire（`storage/logs/cron/scheduler_tick.log` 自 2026-04-19 起 size=0），缺 trigger → event_jobs populate 後永遠停 pending。Piggy-back 接管後 ~60min latency materialize，下一輪 v12 主線程 claim-next 即派。

**Crontab entries 保留**：不刪除，harmless（永不 fire），兼 fallback。不需 install_host_crontab.sh 重跑。

**Event_jobs 補充**（2026-04-20 新增）：
- Populate schema 見 `src/volpred/ops/event_jobs.py::_materialize_task`（必填：`id`、`dedupe_key`、`not_before`、`deadline`、`task_template.{title,description,task_family,priority,preferred_agent,approval_mode,risk_level,public_effect,payload_patch}`）。
- 單一事件 entries ≤ 3-4 篇（防 2026-04-13 TSMC 5-fold overdispatch 教訓）；透過 `payload_patch.event_series_slot` 或 priority ordering 控制 slot 衝突。
- `_materialize_task` 自動抓 `deadline + 7d` 寫 `gc_after` 到 `storage/ops/event_ledger/<sha256(dedupe_key)>.json`；`gc_event_ledger` 在下次 piggy-back 清過期 ledger，不用手動。
- `preview_event_jobs()` 可隨時讀 pending/due/materialized 狀態，不會改 state（dry-run 安全）。
- 已 populate 範例：`fomc-2026-04-29-t2`、`fomc-2026-04-29-t0`（round 13）。

### Standard event pattern（2026-04-20 canonical — CPI/NFP/FOMC/Earnings 共用）

**原則**：每類 recurring macroeconomic event / 企業事件用相同 4-field id scheme + T-series slots 管理文章配額。複製對應 template 修 date/asset 即可 populate。

**命名規則**：
- `id`: `<event-type>-<YYYY-MM-DD>-<slot>` e.g. `cpi-us-2026-05-13-t2`, `nfp-2026-05-02-t0`, `tsmc-earnings-2026-07-17-t7`
- `event_key`: `<TYPE>_<YYYY_MM_DD>` e.g. `CPI_US_2026_05_13`（允許同一事件多個 entries 聚類）
- `dedupe_key`: `<id>:one_shot`
- `trigger_mode`: `"one_shot"`（目前僅此型；未來 `recurring` 保留擴充）

**T-series slots**（per `.claude/rules/publish-checklist.md` 事件驅動配額）：

| slot | `not_before` 建議 | `deadline` | priority | audience | 差異化主軸 |
|------|----------------|------------|----------|----------|-----------|
| T-7  | event_date - 7d 08:00 CST | T-7 + 24h | 30 | research/general | 歷史 baseline + regime 比較 |
| T-2  | event_date - 2d 00:00 CST | T-2 + 24h | 20 | general | scenario 具體數字 grid + position sizing |
| T+0  | event_date 當日 announce 後 | T+0 + 24h | 15 | general | 實際 vs 預期 + dot-plot / 數字 reconcile |
| T+1  | event_date + 1d 08:00 CST | T+1 + 24h | 25 | research | 市場消化 + 隔日 drift 統計（可選） |

**配額 cap**：同一 `event_key` 總 entries ≤ 4。T-7/T-2/T+0 為 core 三篇，T+1 選配。`payload_patch.event_series_slot` 必填以便 dedup audit。

**事件類型檢查清單**（populate 前每類必做）：

1. **FOMC**（8 次/年，US 下午公佈 UTC+21:00 → CST 隔日 02:00 早上）
   - 核心 data source: CME FedWatch implied prob / dot plot median
   - 典型 prior_articles: VIX term structure、94.x% hold baseline
   - Precondition: `US market hour awareness`（T+0 寫作需等 announce）

2. **US CPI**（每月 10-15 日，08:30 ET = CST 當日晚 8:30）
   - 核心 data source: BLS CPI headline + core YoY/MoM，FRED CPILFESL
   - Angle: inflation surprise → breakeven inflation / TIPS reaction
   - T+0 `not_before` 用 announce 後 1h（收集實際數字）

3. **US NFP**（每月第一週五，08:30 ET）
   - 核心: BLS Employment Situation headline NFP + unemployment + wage growth
   - Angle: labor market tight/soft → Fed path / SPY/VIX reaction
   - T+0 同 CPI 時差

4. **Earnings（TSMC / NVDA / AAPL / 0050 成份股）**
   - Schedule source: Nasdaq earnings calendar / 台股財報公告日.txt
   - Angle: pre-earnings IV crush / post-earnings drift / K1107 foundry fabless type effect
   - Precondition: earnings_date confirmed from primary source（公告變動常見）
   - **特別小心**：單家公司 ≤ 3 篇（TSMC 2026-04-13 5-fold 過載教訓），連同 sector 同日報 ≤ 5 篇

5. **央行決議（ECB / BOJ / PBoC）** — 與 FOMC 同 pattern
6. **地緣政治 / 能源**（OPEC+、關鍵制裁） — 無 T-series 結構因不可預期，改用 ad-hoc `payload_patch.urgency=breaking`

**Populate workflow**：
```
1. 主線程確認事件日期（WebSearch 官方 schedule）
2. 複製對應 T-series template 到 config/runtime_schedules.json event_jobs.items
3. 修 id / event_key / dedupe_key / not_before / deadline / payload_patch
4. uv run python -c "from volpred.ops import preview_event_jobs; import json; print(json.dumps(preview_event_jobs(), ensure_ascii=False, indent=2))" 驗 status=pending
5. 對應 memo 寫到 storage/next_draft_candidate_<event>_<slot>.md（選題軸 + 3-layer dedup checklist）
6. Git commit 整組
```

**ROI 優先序**（當 cycle 太多事件 overwhelm 時）：FOMC > US CPI ≥ US NFP > 台股旗艦財報（TSMC/Hon Hai/MediaTek）> 其他 mega-caps earnings > ECB/BOJ > 次要 macro。

## Host crontab 維運規則（2026-04-19 確立，防反覆 TCC prompt）

- Host crontab 的 volpred 區段**只能**透過 `bash scripts/install_host_crontab.sh` 重建；禁止手動 `crontab -e`、`sed` in-place 改、或直接 `crontab <file>` 塞客製內容。
- **命令/參數變動**：改 `config/runtime_schedules.json` 的對應 item（`cron`、`wrapper_script`、`log_path`）→ 跑 `install_host_crontab.sh`（單次 `crontab <file>` 呼叫完成）。
- **邏輯變動（flags、env、pre-exec 設定）**：直接改 `scripts/cron_*.sh` wrapper；crontab entry 本身不動，**無需重跑 install**（避免觸發 macOS TCC App Management prompt）。
- `scripts/cron_*.sh` 必維持最小結構：`#!/bin/bash` + `cd <repo>` + `exec <command>`；需要 env / PATH 擴展時參考 `scripts/run_scheduler_tick.sh`。
- 每個新 wrapper 必 `chmod +x`；install script 檢查到 non-executable 會 fail-fast。
- **FDA / macOS TCC（2026-04-19 確立）**：host-cron wrapper 實體檔案**必放** `~/.volpred/bin/cron_*.sh`，不可放 `Desktop/volpred-research/scripts/`。macOS TCC 擋 `cron` daemon exec Desktop/ 保護路徑內的 `.sh`（回 `Operation not permitted`），即便 cron 能 read Desktop 檔 + write Desktop log + exec `/opt/homebrew/bin/uv`。
  - `scripts/cron_*.sh` 仍是 canonical source，改動後用 `cp scripts/cron_*.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_*.sh` 同步。
  - `config/runtime_schedules.json` 的 `wrapper_script` 欄位**必填絕對路徑**（`/Users/<u>/.volpred/bin/cron_*.sh`）；install script 會偵測 `/` 前綴並 bypass REPO_ROOT prefix。
  - 新增/修改 wrapper 後必跑一次 `env -i HOME=$HOME PATH=/usr/bin:/bin ~/.volpred/bin/cron_<id>.sh` 簡單模擬 cron env 驗證能 exec。
- Install script idempotent：重跑不應產生 crontab diff。若 diff 非預期，先查 config；不要為了 match 手改 crontab。
- 不想被 host crontab 管理的 item 在 config 加 `"host_crontab_managed": false`（e.g. `shared_scheduler_tick` 在 v12 已降級為 advisory，不納入 host crontab）。
- 非 volpred 的既有 crontab entries 由 install script 自動保留（透過 `# volpred-` 標記區隔）。
