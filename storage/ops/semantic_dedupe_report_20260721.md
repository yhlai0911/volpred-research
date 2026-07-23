# 任務池語意重複掃描報告

- 產生時間：2026-07-21T14:29:41.173943Z
- 佇列總筆數：3244；掃描範圍（open = pending/in_progress/claimed）：137
- 判定為語意重複的組數：0；涉及單數：0；建議合併掉：0

> **本報告不動任何檔案。** 合併裁決需人工確認後再執行。
> signature = 檔案 + 符號 + failure_class + 稀有識別碼，並以「兩張單的**標題**
> 必須共享錨點」作為誤報煞車（寧可漏報不可誤報）。

## A. 現有 open 任務的建議合併清單（可行動）

（無）

## B. 校準掃描：2026-07-19 之後建立的所有任務（含已結案，僅供驗證，不可行動）

- 掃描 355 張，判定 20 組語意重複。
- 目的：證明偵測器在真實資料上抓得到東西 —— A 區為空時，區別
  「沒有重複」與「偵測器壞掉」的唯一方法。

### B 第 1 組（3 張）

- **保留**：`assign_6c43a4d4` — snapaudit worktree triage：dy_diag_param.py 觸發 fevd-ordering ratchet（agent job exit 4）
  - created_at: 2026-07-19T06:20:10.463763+00:00 / status: succeeded
- **合併掉**：`assign_aa048c27` — compute queue：failed job 自動重試與 hourly triage followup 併發撞同一 worktree（created_at: 2026-07-19T06:28:31.488714+00:00 / status: succeeded）
- **合併掉**：`snapaudit_fevd_gate_remediation_20260719` — [triage] snapaudit agent job exit 4 —— fevd-ordering gate 擋下 dy_diag_param.py，修正後合併 worktree（created_at: 2026-07-19T14:20:53.389233+08:00 / status: succeeded）

- signature: `audit_results.json|dy_diag_param.py|merge_worktree.sh::audit_dup_snapshot_20260719|partition_cfc_va::-::commit|dispatch|experiment`
- 判定理由：
  - `assign_6c43a4d4` ≡ `snapaudit_fevd_gate_remediation_20260719` (score=16, anchor=['dy_diag_param.py', 'worktree']): shared symbols: ['audit_dup_snapshot_20260719', 'partition_cfc_va']; shared files: ['audit_results.json', 'dy_diag_param.py', 'merge_worktree.sh']; shared rare ids: ['858545f9', 'agent-brief_snapaudit-3cae76', 'audit_dup_snapshot_20260719', 'dispatch-slot-1-858545f9-snapaudit']; title token jaccard=0.44
  - `assign_6c43a4d4` ≡ `assign_aa048c27` (score=6, anchor=['worktree']): shared rare ids: ['858545f9', 'agent-brief_snapaudit-3cae76', 'dispatch-slot-1-858545f9-snapaudit']
  - `snapaudit_fevd_gate_remediation_20260719` ≡ `assign_aa048c27` (score=6, anchor=['worktree']): shared rare ids: ['858545f9', 'agent-brief_snapaudit-3cae76', 'dispatch-slot-1-858545f9-snapaudit']

### B 第 2 組（3 張）

- **保留**：`worktree_harvest_wave2_dirty_stale_20260719` — [worktree harvest wave 2] 9 個 dirty stale worktree 待人工裁決（reclaim gate 攔下、agent lane 卡滿）
  - created_at: 2026-07-19T13:30:35.097860+08:00 / status: succeeded
- **合併掉**：`merge_worktree_k1262v4_overtrigger_20260719` — merge_worktree.sh 的 K1262-v4 防護誤判 → 會把 47 個跨分支 commit 合進 main（created_at: 2026-07-19T13:54:38.850847+08:00 / status: succeeded）
- **合併掉**：`worktree_harvest_wave3_dirty_stale_20260719` — [worktree harvest wave 3] 剩餘 6 個 dirty stale worktree 待裁決（agent lane 仍卡滿）（created_at: 2026-07-19T13:56:03.464889+08:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py::k1708_fix_verdict_gate_20260717::data_stale::commit|dispatch|merge`
- 判定理由：
  - `worktree_harvest_wave2_dirty_stale_20260719` ≡ `merge_worktree_k1262v4_overtrigger_20260719` (score=6, anchor=['worktree']): shared files: ['merge_worktree.sh']; shared rare ids: ['dispatch-slot-1-f53bca44-k1692', 'f53bca44']
  - `worktree_harvest_wave2_dirty_stale_20260719` ≡ `worktree_harvest_wave3_dirty_stale_20260719` (score=15, anchor=['worktree']): shared symbols: ['k1708_fix_verdict_gate_20260717']; shared files: ['merge_worktree.sh', 'reclaim_stale_worktrees.py']; shared rare ids: ['1533dcbc', '30aeb902', '79726798', '8dda242d']; same failure_class: data_stale; title token jaccard=0.44
  - `merge_worktree_k1262v4_overtrigger_20260719` ≡ `worktree_harvest_wave3_dirty_stale_20260719` (score=6, anchor=['worktree']): shared files: ['merge_worktree.sh']; shared rare ids: ['dispatch-slot-1-f53bca44-k1692', 'f53bca44']

### B 第 3 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-1-1533dcbc-cqamend` — worktree 產物裁決：dispatch-slot-1-1533dcbc-cqamend（idle=138.7h unmerged=2 dirty=True branch=ops/compute-queue-amend）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-1-1533dcbc-cqamend` — WS-B workspace remediation: dispatch-slot-1-1533dcbc-cqamend (worker_orphaned)（created_at: 2026-07-20T10:19:31.721906+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-1-1533dcbc-cqamend` ≡ `wsb_remed_dispatch-slot-1-1533dcbc-cqamend` (score=8, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['1533dcbc', 'compute-queue-amend', 'dispatch-slot-1-1533dcbc-cqamend']

### B 第 4 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-1-b55db3be-2` — worktree 產物裁決：dispatch-slot-1-b55db3be-2（idle=137.3h unmerged=0 dirty=True branch=fix/dispatch-slot-1-b55db3be-brief-leak）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-1-b55db3be-2` — WS-B workspace remediation: dispatch-slot-1-b55db3be-2 (worker_orphaned)（created_at: 2026-07-20T10:19:37.635590+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-1-b55db3be-2` ≡ `wsb_remed_dispatch-slot-1-b55db3be-2` (score=8, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['b55db3be', 'dispatch-slot-1-b55db3be-2', 'dispatch-slot-1-b55db3be-brief-leak']

### B 第 5 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-2-c5cafe39-k1623` — worktree 產物裁決：dispatch-slot-2-c5cafe39-k1623（idle=12.8h unmerged=3 dirty=False branch=worktree-dispatch-slot-2-c5cafe39-k1623）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-2-c5cafe39-k1623` — WS-B workspace remediation: dispatch-slot-2-c5cafe39-k1623 (worker_orphaned)（created_at: 2026-07-20T10:19:42.768468+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-2-c5cafe39-k1623` ≡ `wsb_remed_dispatch-slot-2-c5cafe39-k1623` (score=8, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['c5cafe39', 'dispatch-slot-2-c5cafe39-k1623', 'worktree-dispatch-slot-2-c5cafe39-k1623']

### B 第 6 組（2 張）

- **保留**：`wsb_remed_dispatch-slot-2-c5cafe39-k1698` — WS-B workspace remediation: dispatch-slot-2-c5cafe39-k1698 (worker_orphaned)
  - created_at: 2026-07-20T10:19:44.453610+00:00 / status: succeeded
- **合併掉**：`worktree_salvage_dispatch-slot-2-c5cafe39-k1698` — worktree 產物裁決：dispatch-slot-2-c5cafe39-k1698（idle=4.2h unmerged=4 dirty=True branch=worktree-dispatch-slot-2-c5cafe39-k1698）（created_at: 2026-07-20T11:00:50.217663+00:00 / status: succeeded）

- signature: `merge_worktree.sh::-::-::commit|dispatch|merge`
- 判定理由：
  - `wsb_remed_dispatch-slot-2-c5cafe39-k1698` ≡ `worktree_salvage_dispatch-slot-2-c5cafe39-k1698` (score=8, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['c5cafe39', 'dispatch-slot-2-c5cafe39-k1698', 'worktree-dispatch-slot-2-c5cafe39-k1698']

### B 第 7 組（2 張）

- **保留**：`wsb_remed_dispatch-slot-3-30adeed7-k528nfp` — WS-B workspace remediation: dispatch-slot-3-30adeed7-k528nfp (worker_orphaned)
  - created_at: 2026-07-20T10:19:45.954365+00:00 / status: succeeded
- **合併掉**：`worktree_salvage_dispatch-slot-3-30adeed7-k528nfp` — worktree 產物裁決：dispatch-slot-3-30adeed7-k528nfp（idle=4.7h unmerged=8 dirty=True branch=k528-nfp-official-dates）（created_at: 2026-07-20T11:00:50.217663+00:00 / status: succeeded）

- signature: `merge_worktree.sh::-::-::commit|dispatch|merge`
- 判定理由：
  - `wsb_remed_dispatch-slot-3-30adeed7-k528nfp` ≡ `worktree_salvage_dispatch-slot-3-30adeed7-k528nfp` (score=8, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['30adeed7', 'dispatch-slot-3-30adeed7-k528nfp', 'k528-nfp-official-dates']

### B 第 8 組（2 張）

- **保留**：`assign_feed_superseded_by_null_audit_20260719` — feed.json 撤稿 entry 的 superseded_by 是 null 但 work_log 宣稱有寫 → 疑 writer 漏寫欄位
  - created_at: 2026-07-19T12:14:35+08:00 / status: succeeded
- **合併掉**：`assign_82551c2e` — 撤稿沒有 writer：13 篇 retracted 只有 1 篇有 supersede 指標，全靠手改 feed.json（created_at: 2026-07-21T09:35:40.903195+00:00 / status: pending）

- signature: `feed.json::assign_fb_retract_note_ebb5d6f5_20260717|assign_frontend_deploy_revalidate_endpoint_20260719::regression::deploy|feed|frontend`
- 判定理由：
  - `assign_feed_superseded_by_null_audit_20260719` ≡ `assign_82551c2e` (score=7, anchor=['feed', 'feed.json']): shared symbols: ['assign_frontend_deploy_revalidate_endpoint_20260719']; shared files: ['feed.json']; same failure_class: regression

### B 第 9 組（2 張）

- **保留**：`assign_614e70ee` — 修 check_alerts NameError：_ci_incident_store_sync 未定義，警報系統整條停擺
  - created_at: 2026-07-21T13:38:16.665265+00:00 / status: succeeded
- **合併掉**：`assign_1d936f52` — [P1 回歸] check_alerts.py 呼叫 _ci_incident_store_sync 但該函式不存在 — CI-red alert 路徑必崩（created_at: 2026-07-21T13:53:11.931971+00:00 / status: pending）

- signature: `check_alerts.py::_ci_incident_store_sync|feedback_declare_complete_requires_class_sync|git_push_backup::nameerror::alert|ci|commit`
- 判定理由：
  - `assign_614e70ee` ≡ `assign_1d936f52` (score=7, anchor=['_ci_incident_store_sync', 'alert', 'ci', 'incident']): shared symbols: ['_ci_incident_store_sync']; shared files: ['check_alerts.py']; same failure_class: nameerror

### B 第 10 組（2 張）

- **保留**：`assign_667a501a` — k528 Codex 二審重跑：review_verdict.json 全是未填 FILL 佔位（禁合併/禁套18條更正）
  - created_at: 2026-07-19T03:41:07.556892+00:00 / status: succeeded
- **合併掉**：`assign_06d6352d` — [K528 split 2/2] Codex round 5 review + merge 裁決（等 stage 1 交付物才可開工）（created_at: 2026-07-19T09:47:44.300788+00:00 / status: pending）

- signature: `build_article_correction.py|knowledge.json|merge_worktree.sh::-::-::commit|dispatch|experiment`
- 判定理由：
  - `assign_667a501a` ≡ `assign_06d6352d` (score=6, anchor=['merge']): shared files: ['knowledge.json', 'merge_worktree.sh']; shared rare ids: ['30adeed7', 'dispatch-slot-3-30adeed7-k528nfp']

### B 第 11 組（2 張）

- **保留**：`assign_79faa0b0` — K1708 verdict-gate 修正 — Codex re-review（PASS 才 merge worktree + 寫 knowledge）
  - created_at: 2026-07-19T06:31:28.438762+00:00 / status: succeeded
- **合併掉**：`worktree_salvage_dispatch-slot-2-8dda242d-k1708` — worktree 產物裁決：dispatch-slot-2-8dda242d-k1708（idle=27.7h unmerged=1 dirty=True branch=wt/dispatch-slot-2-8dda242d-k1708）（created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded）

- signature: `knowledge.json|merge_worktree.sh|test_k1708.py::a_verdict_label_after_fix|full_sample_rerun|gate_family_alpha::regression::commit|cron|dispatch`
- 判定理由：
  - `assign_79faa0b0` ≡ `worktree_salvage_dispatch-slot-2-8dda242d-k1708` (score=6, anchor=['merge', 'worktree']): shared files: ['merge_worktree.sh']; shared rare ids: ['8dda242d', 'dispatch-slot-2-8dda242d-k1708']

### B 第 12 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-1-30aeb902-taifexrv` — worktree 產物裁決：dispatch-slot-1-30aeb902-taifexrv（idle=69.3h unmerged=3 dirty=True branch=wt/dispatch-slot-1-30aeb902-taifexrv）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-1-30aeb902-taifexrv` — WS-B workspace remediation: dispatch-slot-1-30aeb902-taifexrv (worker_orphaned)（created_at: 2026-07-20T10:19:32.207694+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-1-30aeb902-taifexrv` ≡ `wsb_remed_dispatch-slot-1-30aeb902-taifexrv` (score=6, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['30aeb902', 'dispatch-slot-1-30aeb902-taifexrv']

### B 第 13 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-1-558d7893-k1730` — worktree 產物裁決：dispatch-slot-1-558d7893-k1730（idle=17.9h unmerged=1 dirty=True branch=wt/dispatch-slot-1-558d7893-k1730）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-1-558d7893-k1730` — WS-B workspace remediation: dispatch-slot-1-558d7893-k1730 (worker_orphaned)（created_at: 2026-07-20T10:19:32.933377+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-1-558d7893-k1730` ≡ `wsb_remed_dispatch-slot-1-558d7893-k1730` (score=6, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['558d7893', 'dispatch-slot-1-558d7893-k1730']

### B 第 14 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-1-79726798-credit-firm` — worktree 產物裁決：dispatch-slot-1-79726798-credit-firm（idle=64.5h unmerged=0 dirty=True branch=wt/dispatch-slot-1-79726798-credit-firm）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-1-79726798-credit-firm` — WS-B workspace remediation: dispatch-slot-1-79726798-credit-firm (worker_orphaned)（created_at: 2026-07-20T10:19:34.251121+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-1-79726798-credit-firm` ≡ `wsb_remed_dispatch-slot-1-79726798-credit-firm` (score=6, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['79726798', 'dispatch-slot-1-79726798-credit-firm']

### B 第 15 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-1-858545f9-snapaudit` — worktree 產物裁決：dispatch-slot-1-858545f9-snapaudit（idle=27.6h unmerged=7 dirty=True branch=wt/dispatch-slot-1-858545f9-snapaudit）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-1-858545f9-snapaudit` — WS-B workspace remediation: dispatch-slot-1-858545f9-snapaudit (worker_orphaned)（created_at: 2026-07-20T10:19:36.438477+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-1-858545f9-snapaudit` ≡ `wsb_remed_dispatch-slot-1-858545f9-snapaudit` (score=6, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['858545f9', 'dispatch-slot-1-858545f9-snapaudit']

### B 第 16 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-1-bd00f90a-k1731` — worktree 產物裁決：dispatch-slot-1-bd00f90a-k1731（idle=31.4h unmerged=8 dirty=False branch=wt/dispatch-slot-1-bd00f90a-k1731）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-1-bd00f90a-k1731` — WS-B workspace remediation: dispatch-slot-1-bd00f90a-k1731 (worker_orphaned)（created_at: 2026-07-20T10:19:39.792278+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-1-bd00f90a-k1731` ≡ `wsb_remed_dispatch-slot-1-bd00f90a-k1731` (score=6, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['bd00f90a', 'dispatch-slot-1-bd00f90a-k1731']

### B 第 17 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-1-f53bca44-k1692` — worktree 產物裁決：dispatch-slot-1-f53bca44-k1692（idle=128.8h unmerged=0 dirty=True branch=wt/dispatch-slot-1-f53bca44-k1692）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-1-f53bca44-k1692` — WS-B workspace remediation: dispatch-slot-1-f53bca44-k1692 (worker_orphaned)（created_at: 2026-07-20T10:19:40.521008+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-1-f53bca44-k1692` ≡ `wsb_remed_dispatch-slot-1-f53bca44-k1692` (score=6, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['dispatch-slot-1-f53bca44-k1692', 'f53bca44']

### B 第 18 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-2-dcc222db-snapaudit` — worktree 產物裁決：dispatch-slot-2-dcc222db-snapaudit（idle=7.9h unmerged=2 dirty=True branch=snapaudit-dcc222db）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-2-dcc222db-snapaudit` — WS-B workspace remediation: dispatch-slot-2-dcc222db-snapaudit (worker_orphaned)（created_at: 2026-07-20T10:19:45.164986+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-2-dcc222db-snapaudit` ≡ `wsb_remed_dispatch-slot-2-dcc222db-snapaudit` (score=6, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['dcc222db', 'dispatch-slot-2-dcc222db-snapaudit']

### B 第 19 組（2 張）

- **保留**：`worktree_salvage_dispatch-slot-3-b5fbc1f4-nfpcal` — worktree 產物裁決：dispatch-slot-3-b5fbc1f4-nfpcal（idle=6.1h unmerged=2 dirty=False branch=wt/dispatch-slot-3-b5fbc1f4-nfpcal）
  - created_at: 2026-07-20T10:00:56.269360+00:00 / status: succeeded
- **合併掉**：`wsb_remed_dispatch-slot-3-b5fbc1f4-nfpcal` — WS-B workspace remediation: dispatch-slot-3-b5fbc1f4-nfpcal (worker_orphaned)（created_at: 2026-07-20T10:19:47.085471+00:00 / status: succeeded）

- signature: `merge_worktree.sh|reclaim_stale_worktrees.py|review_verdict.json::feedback_worktree_stale_base_extract_by_path::data_stale::commit|dispatch|experiment`
- 判定理由：
  - `worktree_salvage_dispatch-slot-3-b5fbc1f4-nfpcal` ≡ `wsb_remed_dispatch-slot-3-b5fbc1f4-nfpcal` (score=6, anchor=['dispatch']): shared files: ['merge_worktree.sh']; shared rare ids: ['b5fbc1f4', 'dispatch-slot-3-b5fbc1f4-nfpcal']

### B 第 20 組（2 張）

- **保留**：`k1380_stage_refactor_collect` — K1380 收件：驗 --stage 三段重構 + 合併 worktree（compute 尚未跑，禁寫 Paper 9）
  - created_at: 2026-07-21T07:23:18.572000+00:00 / status: pending
- **合併掉**：`assign_a5ddf2b4` — 收割並清理 3 個未合併 worktree（1+4+18 commits）（created_at: 2026-07-21T13:52:03.874658+00:00 / status: succeeded）

- signature: `experiments.md|k1380_stage_refactor_report.json|knowledge.json::brief_k1380_stage|defects_found_beyond_the_known_reversed_qlike|refactor_complete_compute_held_pending_merge::timeout::commit|dispatch|experiment`
- 判定理由：
  - `k1380_stage_refactor_collect` ≡ `assign_a5ddf2b4` (score=6, anchor=['merge', 'worktree']): shared files: ['merge_worktree.sh']; shared rare ids: ['375ba0e3', 'dispatch-slot-1-375ba0e3-k1380']
