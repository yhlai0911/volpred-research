# Dispatch Writer Isolation Design

- **Task**: `dispatch_writer_isolation_design`
- **狀態**: 設計完成，等待 owner 核准；**尚未啟用、不得視為現行 runtime 行為**
- **範圍**: 先處理 automated `platform_ops` / `governance` 的 repo patch；不在本文件直接修改 supervisor
- **rollback anchor**: `683f87e55` (`snapshot: [codex] before dispatch writer isolation design`)

## 1. 決策摘要

建議採用「**每 task 一個 registered worktree，repo patch 與 canonical／external side effect 分段**」；
但不可把現有 experiment `merge_worktree.sh` 原封不動擴到所有 task。該工具在 2026-07-16 前會 stash
整個 main checkout；目前已改成 staged／同路徑 WIP fail-closed、不相交 WIP 原地保留且零 stash，
但仍混有 experiment-only certification 與歷史救援分支，不是通用 landing surface。

第一階段只做 `platform_ops` repo-patch shadow/pilot；`governance` 在 pilot 穩定後才加入。worker 不再靠
prompt 自己建 worktree：allocator 在 agent 啟動前建立並記錄 workspace，worker 的 `cwd` 直接指向它。
agent 只提供修改理由；機器 finalizer 依 declared paths commit、跑 gate、產出綁定 commit SHA 的 receipt。

主線整合是單一序列化邊界，規則是：**不 stash、不 `git add -A`、不覆蓋 main 上任何 dirty target path、
不在 gate receipt 過期後 merge、不 force-remove worktree**。main 有碰撞就 defer，worktree/branch 保留。

PHASE-Z 在 rollout 期間保留，定位降為 canonical machine-state 與 legacy direct-writer fallback。只有當
所有 automated repo-byte writers 都受 workspace contract 約束後，才能宣稱 fire baseline authorship
問題「結構上消失」；pilot 階段不可提前做這個宣稱。

## 2. 現況證據與缺口

| 現況 | 證據 | 結論 |
|---|---|---|
| supervisor 只把 `worktree_prefix` 寫進 prompt | `scripts/dispatch_supervisor/scheduler.py::_slot_prompt` | 目前是 prose 約定，不是 execution boundary |
| worker spawn 未指定 `cwd` | `scripts/dispatch_supervisor/worker.py::_spawn` | child 繼承 supervisor cwd，無法機械證明在 slot worktree 寫入 |
| `platform_ops` / `governance` 預設 topology 是 `subagent` | `scripts/model_router.py::TASK_TYPE_TO_TOPOLOGY` | topology 與 workspace isolation 是兩個維度，不應混成同一欄 |
| experiment 已有 worktree + merge/certification | `AGENTS.md`、`.claude/rules/task-routing.md`、`scripts/merge_worktree.sh` | 可重用原則與 gates，不可直接重用整支 883-line merge shell |
| PHASE-Z 已有 alternate index、pinned gate、`update-ref` CAS | `scripts/dispatch_supervisor/phase_z.py::run_phase_z` | candidate transaction 可抽象化；不能再建第二套較弱 gate |
| scheduled writer 已有獨立 ownership registry | `config/scheduled_writer_ownership.json` | 本設計不接管 cron self-commit／machine-state ownership |
| long-running agent 已可在指定 `--cwd` 執行 | `scripts/run_agent_job.py`、`scripts/compute_queue.py enqueue-agent` | pilot 可重用現有 detached agent substrate，不另建 daemon |

事故證據集中在 `docs/error_log.md` §B/§C 與 `docs/error_log_archive/2026-Q3.md`：

- shared checkout 的 `git add -A` 已四次誤收其他 writer，證明 dirty bytes 不是可靠 owner identity。
- PHASE-Z 曾因 live daemon churn、基線遺失及 candidate partial transaction 誤歸因。
- worktree merge 曾發生 main/root 誤判、獨立 repo 冒充 registered worktree、detached unique commits 遺失、
  shared JSON two-dot 誤報與 stash-pop 回灌舊 runtime state。
- 現有測試只驗 prompt 含 prefix，尚無 `slot/job ↔ registered worktree ↔ branch ↔ cleanup receipt` E2E gate。

### 2026-07-14 實測成本快照

這些是當下 filesystem 實測，不外推成長期常數：

| 項目 | 實測 |
|---|---:|
| repo 內 registered dispatch worktrees | 3 |
| worktree `du -sh` disk usage | 2.9 GB / 2.9 GB / 4.7 GB |
| 三棵合計 | 約 10.5 GB |
| 每棵 `.venv` | 約 1.3 GB |
| 每棵 tracked `experiments/` | 約 1.3–1.4 GB |
| filesystem | 926 GiB total、64 GiB available、93% used |
| worktree setup latency | **目前未記錄；不可虛構數字** |

因此 pilot 不得一次把所有 4 slots 全改 full checkout。先加計時與 disk receipt，且同時最多一個新的
`platform_ops` pilot workspace；allocator 在空間低於 configurable floor 時 fail closed，不先建立再祈禱。

## 3. 寫入面盤點

`task_type` 只能給預設值，不能單獨代表 write ownership。同一個 `platform_ops` 可能是 read-only audit、
repo code patch、canonical CLI operation 或 deploy。目標 contract 必須另有 `write_intent`。

| task 類型 | 常見寫入面 | worktree 決策 |
|---|---|---|
| `experiment` | `experiments/<K>/`；不得碰共享 memory/feed/state | 維持現有 worktree + experiment certification，不納入首波 |
| `platform_ops` | `scripts/`、`src/`、`tests/`、`frontend-v2-fix/`、`config/`、少量 docs；也可能 deploy／安裝 hook | **首波目標**：同一 Git repo 的 patch 必須 worktree；deploy/install 拆成 post-merge action。`frontend-v2-fix/` 是獨立 repo，須由該 repo 自己配置 worktree，排除首波 parent-repo pilot |
| `governance` | `.claude/`、`docs/`、`config/`、routing/audit scripts 與 tests | 第二波；serialize；既有 snapshot 規則保留，未經 owner 同意不改寫 |
| `code_review` | 通常 read-only；若包含 fix 會寫 code/tests | read-only 不建；有 fix 時轉成 `repo_patch` contract |
| `paper_review` | evidence inspection 是 read-only；若保存 review report，會寫 `paper/<id>/review_history/**`；小修另可能碰 paper metadata | 純終驗不建；保存 report 是未來的 per-paper `repo_patch` profile；`.tex` 結構寫入仍轉 `paper_body` |
| `paper_body` / `paper_decision` | `paper/`、pipeline metadata，且需主線方法論判斷 | main-thread only，明確排除 background writer pilot |
| `daily_article` / `daily_digest` | draft、charts、`storage/reports/feed.json`、Supabase projection | generation 可作未來子階段；publish 是 canonical/external transaction，不在首波 |
| `event_article` / `trending_repost` / `member_qa` | canonical feed/question state + 外部發布 | main-thread / canonical CLI，排除首波 |
| `strategy_lifecycle` | registry/code、paper-trading state、Supabase | 保留既有 main-thread gated pipeline，排除首波 |
| `email_reply` / `telegram_reply` | task lifecycle、mail/Telegram external state | responder owner，不是 repo-patch worktree |
| `lookup` / `verify` / `classification` | 原則 read-only | 不建 worktree；若實際要改檔，必升級 write intent |
| scheduled/compute writers（非 task type） | registry-declared exact outputs、machine state、experiment artifacts | 繼續由 scheduled-writer registry／compute output receipt 管理 |

### Proposed `write_intent`

| 值 | 語意 | 執行位置 |
|---|---|---|
| `read_only` | 不改 repo、canonical state 或外部系統 | current root 可讀 |
| `repo_patch` | 產出 Git-tracked code/config/docs/test patch | task worktree |
| `canonical_operation` | 只走既有帶鎖 CLI 改 canonical state | canonical root，序列化 |
| `external_operation` | deploy、寄信、安裝 hook、改 OS service | merge 後由明確 owner 執行 |
| `mixed` | 同時需要 patch + canonical/external action | 強制拆成 worktree patch → merge → post-merge actions |

未宣告 write intent 的 automated `platform_ops` / `governance` 預設視為 `repo_patch`，而不是退回 shared
main。真正 read-only 任務必顯式標記，避免 typo 變成 direct-write escape hatch。

## 4. Workspace contract

`storage/next_tasks.json` 仍是 pending/lifecycle SoT；workspace metadata 只是 execution receipt，放在
`storage/ops/task_workspaces/<task_id>.json`（建議名稱，實作前仍需 schema review），不可建立第二個 queue。

每個 receipt 至少綁定：

- `task_id`、`claim_session_id`、actor、`job_id` / `slot_id`（如有）
- target repo root / git common dir、`base_sha`、registered worktree path、branch、creation timestamp
- `write_intent`、declared repo output paths、denied canonical paths、post-merge actions
- worker terminal outcome、task branch `head_sha`
- gate name/version、trusted gate SHA、gated `head_sha`、tests/audits outcome
- integration base/head、merge disposition、main commit SHA、cleanup disposition
- allocation/setup/gate/merge-wait durations 與 disk bytes

Invariant：task branch bytes 在 gate 後一旦再改，`head_sha` 不符即 gate receipt 失效；不得以舊 PASS
merge 新 bytes。這沿用 experiment verdict 必須綁 commit SHA 的既有教訓。

### Workspace allocator

1. claim 成功後由機器在 agent spawn **之前**，於 declared target repo 建立 registered `git worktree`；
   禁止 agent 自建獨立 repo。parent-repo worktree 不視為能隔離 `frontend-v2-fix/` 這類獨立 nested repo。
2. 命名同時含 task id 與 job/slot identity，branch 不可 detached。
3. worker 的 process `cwd` 直接設為 worktree；不能只把路徑寫進 prompt。
4. worker env 預設禁止 canonical/remote write；動態 state 讀取走 canonical root 的 read-only surface，
   不把 worktree 中 stale `storage/` 當 live state，也不以 symlink 讓寫入穿回 main。
5. dependency manifest 變更另列高風險 class；一般 pilot 不得自行 sync／改共享 `.venv`。

## 5. Agent、finalizer 與 gate 的責任切分

沿用「git 歸機器、理由歸 agent」：

- **agent**：只改 declared repo paths，留下 task receipt subject/body；不 claim/complete task、不 publish、
  不 deploy、不自行 remove worktree。
- **workspace finalizer**：盤點 branch diff，拒絕 undeclared path／canonical state；只 stage declared paths，
  產生 commit，並確認 registered branch 含 unique commit。
- **gate runner**：以 main/pinned trusted gate 判 candidate；candidate 不可修改 gate 後再用自己判自己。
- **orchestrator**：接收 gate receipt，排 merge；merge + post-actions 完成前 task 保持 `in_progress`。

Common gate 最少包含 `git diff --check`、candidate pre-commit、silent-fallback audit、test-import closure，
再由 changed-path policy 選 targeted tests。修改 canonical writer 時加 canonical-writer audit；修改 cron wrapper
時加 manifest/live parity（live install 留到 post-merge）。純 docs governance 不硬跑整套 pytest，但必跑 link/path、
routing/schema 或該規則現有的機械 gate。

Trusted gate files 若本身就是 task 目標，不能一般化放行。需標 `gate_change=true`，先由舊 gate + 專屬
compatibility tests 審，再經 owner-approved post-merge activation；普通 task 直接 fail closed。

## 6. Landing protocol（目標態）

landing 必須是單一 owner，且不可回歸 2026-07-16 前 `merge_worktree.sh` 的全樹 stash 前置條件。

1. 取得 integration lock，重讀 `main` HEAD、task branch、workspace receipt。
2. 驗 registered worktree/branch identity、unique commits、declared-path subset、denied-path zero、gate SHA fresh。
3. 用目前 main + task branch 建 disposable three-way candidate；有 conflict 就 `merge_deferred`，不改 main。
4. 對 rebased candidate 重跑受影響 gate；main 前進後不可沿用舊 candidate PASS。
5. main checkout 的每個 target path 必須與 integration base 相符；任何 staged/unstaged/untracked overlap 都
   defer。**其他不相干 dirty path 不 stash、不 reset、不 commit。**
6. candidate commit 用 old-OID CAS 採納；CAS lost 就重建 candidate，不 retry 舊 tree。
7. 更新 shared index/worktree 也要 path-scoped CAS；若無法證明不覆蓋並行 bytes，寧可 defer 並保留 branch。
8. 驗 main commit 含 task branch 的每個 declared blob，才可執行 post-merge actions。
9. post-actions 全部成功才 complete task；失敗時保留 idempotent action receipt，不能把 code merge 回滾成
   未發生，也不能假稱 task succeeded。
10. 只有 main 已含 commit、blob verification 通過、沒有 worktree dirty/untracked output 時才 normal remove；
    永不 `--force`。failed/conflicted workspace 進 quarantine + TTL review，不自動刪 unique commits。

若第 7 步在 shared main 無法做出真正原子且不覆寫的實作，cutover 必須停在 manual landing；不可用
「時間窗很短」冒充 correctness。長期選項是讓所有 automated repo-byte writers 都離開 shared main，或把
main integration 移到 dedicated clean checkout，再明確處理 runtime checkout refresh。

## 7. Canonical state 與外部 side effects

worktree 只隔離 repo patch，不解決下列 shared state：

- `storage/next_tasks.json` / `storage/work_log.json` / `storage/ops/**`
- feed、knowledge、paper trading 等 canonical JSON
- Supabase、Mirror、Zeabur、Gmail/Telegram、FB
- `.git/hooks`、`~/.volpred/bin`、LaunchAgents、crontab

因此 `mixed` task 必切兩段。例：wrapper 修正先在 worktree 改 canonical wrapper + manifest + tests；merge
後再由 root 的既有 sync/install CLI 部署。agent 不可在 worktree 先 install，否則 main 還沒接受 patch，
live runtime 已先改，重演 gate source/deployed copy 版本死鎖。

canonical mutation 仍走既有 fcntl writer；task claim/start/complete 由 orchestrator在 root 執行，branch
內的 stale `storage/next_tasks.json` 絕不 merge。scheduled writers 繼續遵循
`config/scheduled_writer_ownership.json`，本設計不建立平行 owner。

## 8. 成本與緩解

| 成本／風險 | 緩解 |
|---|---|
| full checkout 每棵目前約 3–5 GB | pilot cap=1；記 disk delta；成功即 normal cleanup；低空間 fail closed |
| 每棵 `.venv` 約 1.3 GB | Phase 0 benchmark shared immutable env／no-sync 與 isolated env；未驗證前不硬連共用 env |
| tracked experiments/storage 放大 checkout | 初版先 full worktree 保 correctness；sparse checkout 只作後續獨立 pilot，避免 worktree config 汙染全 repo |
| setup latency未知 | receipt 加 create/checkout/env_prepare p50/p95；沒有量測前不承諾 SLO |
| main advance 造成 conflict | disposable three-way candidate + re-gate；conflict defer，不 auto `-X ours` |
| merge queue 增加完成時間 | task 保持 in_progress；量測 merge-wait；P1 可提高 landing priority但不繞 gate |
| gate／auditor self-modification | trusted main gate + explicit gate-change workflow |
| worktree stale canonical data | canonical read-only surface；禁止 merge canonical paths |
| orphan branch/worktree | workspace lease/receipt + restart reconciliation；unique commit 存在時禁止清除 |

### 預期收益與驗證方式

下表是設計目標，不是已實現成效；只有 acceptance gate 的觀測值能把它升格為實證。

| 預期收益 | 相對現況的機制 | 驗證訊號 |
|---|---|---|
| repo bytes 有明確 writer 身分 | task / claim / repo / branch / commit 綁同一 receipt，不再從 shared dirty baseline 猜作者 | 100% pilot commit 可反查 task 與 registered worktree；foreign-path commit = 0 |
| gate 審的是將要 landing 的 immutable bytes | gate receipt 綁 `head_sha`，main 前進或 branch 改變即失效 | stale receipt、HEAD race、same-path conflict 均 fail closed |
| 一個 writer 失敗不搬動其他 slot WIP | integrator 不 stash、不 reset shared checkout，只在 disposable candidate 合併 | stash = 0；main dirty non-target path byte-for-byte 不變 |
| 回復與稽核邊界清楚 | 未 merge 的失敗保留 branch/receipt；已 merge 的 patch 走正常 revert，external action 另有 receipt | lost unique commit = 0；每個 terminal task 有 merge/post-action disposition |
| PHASE-Z 可縮回真正 fallback | automated repo writers 逐波離開 direct-main write，canonical/root writer 仍保留明確 owner | pilot 不觸發 authorship alert；Phase 4 覆蓋率達標後才調降 baseline guessing |

## 9. 分階段 cutover

### Phase 0 — owner review + instrumentation（不改 execution）

- owner 核准本文件的 scope、landing strategy、disk policy、governance snapshot semantics。
- 增加 shadow inventory：對 automated task 記 write intent、預計 output paths、若隔離會用的 workspace。
- 量測至少 7 天或 20 個可寫 task 的 setup/disk/gate/merge-conflict，不建立 worktree也不改 routing。

### Phase 1 — `platform_ops` repo-patch pilot

- 同時最多 1 個 pilot；排除 deploy、gate-source、dependency、canonical writer migration 等高風險 task。
- allocator 機械建立 cwd；worker canonical/remote writes disabled。
- gate green 後先 manual landing，禁止現行 merge script stash main。
- `platform_ops` 的 read-only/canonical-only task 繼續原路，但 write intent 必顯式可稽核。

### Phase 2 — non-stashing integrator shadow → enforce

- 先 dry-run 比較 integrator candidate 與人工 landing commit/tree；兩者 tree OID 必一致。
- 加 E2E：兩 slots 同時改不同路徑、同路徑 conflict、main dirty target、HEAD CAS lost、gate receipt stale、
  worker crash、restart orphan、cleanup unique commit、candidate new path collision。
- break-then-verify 必重播至少一個 7/10 foreign-file incident與一個 stash 回灌 incident。

### Phase 3 — 加入 `governance`

- serialize 不變；保留 snapshot rollback rule。
- gate/routing/control-plane 檔改動走 `gate_change` 或 governance-specific review，不准 self-certify。
- owner 核准後才修改 supervisor／model router／task schema；本設計 task 本身不做這一步。

### Phase 4 — automated peer coverage

- 將同 contract 擴到 supervisor worker、detached agent jobs與 Codex hourly peer的 repo patch。
- 全部 automated repo-byte writer 連續觀測期零 direct-main write 後，PHASE-Z 才可降為 machine-state／legacy
  fallback；interactive main-thread、canonical CLI 與 scheduled writers仍各自有明確 owner。
- daily article generation、paper或發布流程若要拆 workspace，另立 task，不隨本 cutover偷渡。

## 10. Proposed acceptance gates

從 Phase 1 升級前，建議同時滿足：

- 至少 20 個 pilot tasks，0 foreign-path commit、0 lost unique commit、0 force removal、0 stash。
- 100% workspace receipt 能由 task id 追到 registered worktree、branch、base/head/gate/main SHA。
- 100% merge 的 changed paths 是 declared subset；canonical denied paths = 0。
- gate failure 只留下 branch/receipt，不改 main、live install或 external system。
- main target dirty、HEAD race、same-path conflict三種 case皆 fail closed且可重試。
- setup/gate/merge-wait p50/p95 與 disk high-water 已有真實數字；owner 依數字接受 latency/capacity。
- 連續 7 天 internal PHASE-Z authorship alert 不因 pilot task觸發；legacy/direct writer仍分開計數，不混報。

## 11. Rollback

- rollout 由單一 config policy 控制 `off → shadow → pilot → enforce`；回退只把新 allocation 關掉，
  不 reset main、不刪 branch、不 force-remove worktree。
- 已 merge commit照正常 revert 流程處理；外部 post-action需各自既有 rollback，不能假設 git revert 能復原。
- 未 merge workspace保留 receipt與branch，人工 review後 normal remove。
- PHASE-Z 全程保留，直到 Phase 4 gate 通過；rollback 不需臨時重建 safety net。

## 12. Owner 核准點

動 supervisor 前需 owner 明確決定：

1. 是否同意首波只做 `platform_ops repo_patch`，`governance` 延後一階段。
2. 是否同意 workspace isolation 與 topology 正交，不把所有 `subagent` 直接改成 topology=`worktree`。
3. landing 初期採 manual/non-stashing，等 candidate tree parity 通過後才 auto-integrate。
4. `.venv` 先 benchmark 再決定 shared immutable env 或 per-worktree isolated env。
5. governance snapshot rule在 worktree rollout後是保留 branch `snapshot:` commit，或另案核准以 immutable
   `base_sha` receipt取代；本文件不自行改寫既有規範。
