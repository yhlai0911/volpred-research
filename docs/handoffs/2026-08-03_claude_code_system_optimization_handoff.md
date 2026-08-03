# Claude Code 接續：VolPred 自我修復、派工與 Graphify 優化

更新時間：2026-08-03 19:33（Asia/Taipei）  
交接基準 commit：`f8da0b7a228b55e9596a2585b61f00ca613daddc`  
本輪狀態：article-continuity 控制面為 `root_cause_fixed_and_verified`；文章產出本身仍須等待目前安全 slot 釋放後回讀。

## 1. Owner 要的最終行為

1. 不要只寄「發生問題」通知；自我修復要先自動執行，owner 最後只收到**修復成功**通知，內容只需問題、根因、最終步驟與驗證。
2. user-assigned > scheduled > discovery 只決定挑選順序，不可讓 scheduled/daily article 永久沒人做。
3. 只有程式運算、資料處理等低 token 工作時，要充分使用 compute slots；不可因 Claude 安全 slot=1 就讓 CPU 閒置。
4. 不可為了表面吞吐直接提高 shared-launchd Claude slot。先完成 per-fire isolation / custody 證明，或把 model-free 工作送 canonical compute queue。
5. Graphify 要 query-first、保持 freshness，並留下 token A/B usage；Graphify 是 map，結論仍須 source/test/live read-back。

## 2. 本輪已完成並已套用 live

### Article continuity 閉環

- 新增 `src/volpred/ops/article_continuity.py` 與 `scripts/article_continuity.py`。
- `scripts/cron_agent_dispatch_tick.sh` 每分鐘先讀 canonical release preview：
  - `eligible=0`：批次升級既有 daily_article backlog，但只 nominate 最老一張為 continuity preempt。
  - 有 article claimed/in_progress：不平行 nominate 第二張。
  - pool 恢復：只清 `dispatch_preempt_source=article_continuity`，不碰 CI/PHASE-Z flags。
- supervisor scheduled-preempt admission 現讀 `dispatch_preempt_rank`；continuity rank=-100。human urgent 與 time-critical lane 仍在更外層，沒有被降級。
- durable `request_fire` 在 slot 已滿時保留，不提高 slot、不丟任務。

### Operations Core receipt 壓力

- `FileReceiptStore` 現保留所有 live/retryable fire，terminal 上限 6,000、shadow 上限 2,000。
- live daemon 已 reload；receipt 從 27,639,056 bytes / 25,171 fires 收斂到 6,876,425 bytes / 6,286 fires（6,000 terminal + 286 actionable），後續不再無限長大。

### Live 安裝與驗證

- `sync_cron_wrappers.py --apply` 已安裝 `cron_agent_dispatch_tick.sh`；同時把先前 canonical 但未安裝的 `cron_compute_worker.sh` 同步到 live。
- Operations Core LaunchAgent 已 restart；新 daemon 正常每 30 秒 tick。
- root Graphify 已更新到 `f8da0b7a` 且 `fresh=true`。
- 217 個相關 regression tests 通過；schedule config validate 為 57/57 Operations Core owners。
- 完整事件紀錄：`docs/error_log_archive/2026-Q3-article-continuity.md`。

## 3. 交接時 live snapshot（必須重新回讀，不能當永久事實）

- release preview：draft=0、scheduled=0、eligible=0。
- `K1706_article_general`：pending、P1、`dispatch_preempt_source=article_continuity`。
- dispatch state：`fire_request_reason=article_continuity:K1706_article_general`。
- 當下唯一安全 slot 正跑 `ci-red-30736983439`，job `db30a837...`；因此 K1706 request 正在等待，這是預期狀態，不是失敗。
- root graph fresh；active frontend graph 仍 stale。只有分析 active frontend 時才更新 `--graph active_frontend`，不要把它混進 root graph。

## 4. Claude Code 接手後的執行順序

### A. 先完成本輪 sustained live closure

1. 讀 `storage/ops/handoff_latest.md` 第一條 `---` 前與 current dispatch state。
2. 等目前 CI job 正式 settlement；不要殺 worker、不要 release 別人的 claim。
3. 驗證下一個 fire 是否 exact preselect/claim `K1706_article_general`。
4. 驗證該任務完成後真的產生 canonical draft，再用 release preview 回讀 `eligible>0`。
5. 走正式 release/publish workflow，回讀 feed / API / live URL acknowledgement；「worker exit 0」不算完成。
6. 需要 sustained-clean 的 incident 要遵守 `src/volpred/ops/incident.py`，一次乾淨不可直接 resolved。

### B. 消除「有算力但沒派工」

1. 驗證剛同步的 `cron_compute_worker.sh` 會先跑 `scripts/compute_task_admission.py`，model-free / explicit compute_spec 任務可在 Claude slot=1 時照樣進 compute queue。
2. 量測 CPU/compute queue utilization、admission count、queue wait、token usage；不要用「slots 設成 4」代替證據。
3. 若要提高 Claude/Codex agent slots，先完成 shared-launchd coalition 的 per-fire isolation、process custody、kill/reload/read-back tests；未完成前保留 safety cap=1。
4. 建立 work-conserving contract：slot 空就立刻接下一張，不等固定排程；相同 task id / K-id 仍須 single-flight。

### C. 自我修復通知收斂

1. 盤點 GitHub/VolPred alert → task → repair → verification → notification 全鏈。
2. detector 不得只通知；必須 materialize repair task 或 model-free actuator 並 request fire。
3. owner-facing 成功通知只在五步 Gate 全過後寄：症狀、根因、底層修正、回歸與 live read-back、制度化位置。
4. blocked/contained 不得偽裝成功；若需要人類權限或決策才通知阻塞原因。

### D. Graphify 完整整合與 token 證據

1. 先跑 `graphify reflect --if-stale`、讀 `graphify-out/reflections/LESSONS.md`，再跑 `scripts/graphify_integration.py status`。
2. 架構/依賴/owner/legacy/impact/data-flow 一律先 `scripts/graphify_integration.py query`，再讀命中 source。
3. 只在分析 active frontend 時更新它的獨立 graph。
4. 補齊可重跑的 freshness/update 流程與 token A/B report：同一組代表問題比較 query-first vs raw browsing，記錄輸入 token、查詢時間、source read 數與答案正確性；不可只引用官網宣稱。
5. 查官方最新 Graphify 功能時使用 GitHub/官方 primary source，再逐項對照本專案；不要因 MCP 未載入阻塞 CLI baseline。

## 5. 不可踩的邊界

- 工作樹很髒，包含其他 worker 的 experiments、skills、paper、storage 與 tests；不要 reset、checkout、stash-pop 或包進自己的 commit。
- 修改 `.claude/skills/**` 前先查 ownership；修改既有 skill 必寄 `send-alert` 通知 owner，並跑 `scripts/check_skill_architecture.py`。
- 不手改 `storage/next_tasks.json` 或歷史 feed JSON 收尾；所有變更走 canonical writer/CLI。
- shared main commit 只能用 `scripts/git_writer_lock.py commit -- <exact paths>`；不 push。
- 不重跑已完成的 Matt plan/spec/tickets。依 `docs/refactor_plan_ops_master_2026_07.md` §7 與 Issue blocking edges 接第一張未阻塞 ticket。
- 問題只有兩種回報：`contained` 或 `root_cause_fixed_and_verified`。

## 6. 起手 read-back 命令

```bash
sed -n '1,/^---$/p' storage/ops/handoff_latest.md
uv run python scripts/graphify_integration.py status
uv run python scripts/graphify_integration.py query "Which control paths can leave scheduled work pending despite free compute or agent capacity?"
uv run python -m scripts.article_continuity
uv run python scripts/task_pool_claim.py list --status pending --limit 20
uv run python - <<'PY'
from scripts.dispatch_supervisor import state
s = state.read_state()
print({k: s.get(k) for k in ('fire_requested_at','fire_request_reason','current_job')})
PY
uv run python -m scripts.operations_core_scheduler validate
uv run python scripts/sync_cron_wrappers.py --check --json
```

## 7. 完成標準

- K1706（或 continuity 選中的 successor）完成 → draft 可釋出 → 正式 release → live acknowledgement，全鏈有 receipt。
- scheduled work 不再只靠通知；每個 critical detector 都有 repair actuator / task owner / fire request / verification owner。
- compute-only 工作在 agent slot 忙碌時仍有實際吞吐與利用率證據。
- agent slots 若提高，隔離與 custody regression/live canary 全過；否則誠實保留 1。
- Graphify root/active-frontend freshness 各自正確，token A/B 有可重跑紀錄。
- 最終通知符合 owner 要求：只說問題、根因、最終修法與驗證，不寄「我發現了但沒修」的成功通知。

