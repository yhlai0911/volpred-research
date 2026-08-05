# platform_eng 工作日誌（append-only）

## 2026-08-05 17:19–17:27（台灣時間）｜reproduce gate 整檔 hash｜outcome=blocked

**工作項**：`item_20260805T091934819770Z_reproduce-gate-hash-commit-unver`
（論文部 `request`，非 canonical 派工）

**做了什麼**

1. 論文部的證據逐項獨立重驗（不轉抄）：spec hash `29c6f80d` 確為 `9f868e41f^` 版本；
   AST 逐 top-level def 比對後該 commit 唯一變動者是 `strategy_dm_test`；
   `dm_test`／`qlike_pointwise` 兩版完全相同；兩支實驗只 import 這兩個符號。**全部成立。**
2. 根因：`audit_experiment()`（`scripts/reproduce_check.py:1169-1183`）用**整檔** sha256
   比對 `spec["inputs"]`。整檔 hash 的語意是「檔案沒變」，實驗依賴的卻是「我 import 的
   符號沒變」——在共用模組上這兩者**必然發散**。更糟的是判定後直接 `return`，
   連「重跑看數字有沒有變」都做不到，等於把唯一能產生證據的路也關掉。
3. 採論文部建議的 (a)，但把比較單位從「單一函式」修正為**從被 import 符號出發、
   模組層可達名字的傳遞閉包**——只 hash 那個 def 會漏掉它呼叫的 helper 與讀的常數。
   三條 fail-closed 退路：整模組 import／`import *`、模組頂層有副作用敘述、
   spec 版本在 git 歷史查不到，任一成立就退回整檔比對。
4. **不需改 spec schema**：spec 只記整檔 hash，但那個版本可用內容 hash 反查 git 歷史
   （本例反查到 `42ec9aa70`）。舊 spec 全相容、零 migration。
5. 寫成可執行原型跑真實 repo 實測：k1699／K1710 正確放行（閉包
   `[dm_test, qlike_pointwise, np, stats, Tuple]`）；四個負控制/突變測試
   （閉包內插一行、改綁可達的 `stats` import、`import <module>`、只動閉包外）
   全部符合預期。**設計不是紙上的。**

**結論（誠實）**：**一行未落地。** 修復面在 `scripts/reproduce_check.py` 與 `tests/`，
`Edit` 再次被權限閘擋下（今天第二張同因卡住的任務）。定稿修正與可逐字貼上的 helper
在 `work/reproduce_gate_import_surface/`（`diagnosis_and_patch.md` +
`import_surface_helpers.py`）。

**已走管道**：回覆論文部（含對 `main.tex:118` 那句話的建議：拿到 receipt 後應改成
引用比對基準，否則下次共用模組再動一行，同一個 MAJOR finding 會原封不動回來）；
P1 上報經理 `item_20260805T092519977832Z`，並言明在 owned_paths 裁決下來之前，
本部門收到的任何 platform_ops／code_review 任務都只能停在同一個位置。


## 2026-08-05 16:51–17:0x（台灣時間）｜alert_control_gate_source_health｜outcome=blocked

**工作項**：`item_20260805T085055{722967,835067,932635}Z_canonical-alert-evidence-source`
（三張重複派工，同一 canonical `alert_control_gate_source_health_20260802`）
＋ 期間新到的 `item_20260805T090020179678Z`（canonical `..._20260805`，同一 detector 的第二張單）。

**做了什麼**

1. 以原 detector fresh 重驗（`scripts/audit_control_gate_lifecycle.py`）：警報仍 breached，
   `unhealthy_source_count=2`，非自然解除 → 不適用 fresh no-op 收尾。
2. 兩個失明的 evidence source 都追到根因層級（非資料髒）：
   - `dispatch_worker_ownership`：transition reason 詞彙表**雙源漂移**。producer
     （`scripts/dispatch_supervisor/workspace.py:4493`）以 `f"worker_{outcome}"` 生成，
     `config/control_gate_registry.json` 手抄一份，中間無 gate；outcome 詞彙只以散文
     記在 `state.py:152-162`。新 outcome 一出現就變 `unknown` → audit fail-closed。
     實際漏掉的三個：`worker_killed_timeout`、`worker_orphan_gone_or_reused`、`merge_failed`。
     與 2026-05-27 `BLOCKED_REASONS` 漂移同 class。
   - `event_reaction_coverage`：`_join_outcomes()` 以「沒有 deadline」判 malformed，
     但終態任務滿 3 天就被 `compact_terminal_tasks()` 壓成 tombstone、`deadline` 不在
     `_TOMBSTONE_KEEP_FIELDS`；gate review window 卻是 14 天。跨過第 3 天必然失明且
     不會自癒。即 `is_tombstoned()` docstring 已命名的 class J（2026-08-03 dreaming 同因）。
3. 定稿四處修正 ＋ 一個機械 gate 測試，全文寫在
   `work/alert_control_gate_source_health_20260802/diagnosis_and_patch.md`（P1–P6）：
   詞彙表單一 owner 進 `incident.py`、寫入端不再沉默、registry 補齊分類、
   reader 先問 `is_tombstoned`、新測試 `tests/test_incident_reason_vocabulary.py` 擋未來漂移。

**結論（誠實）**：**一行都沒有落地，警報仍在 breached。** 修復面在
`src/volpred/ops/`、`config/`、`tests/`，而 platform_eng 的 `owned_paths` 只有
`frontend-v2-fix/`，`Edit` 被權限閘擋下（與稍早 `scripts/token_usage_report.py` 同型）。
本輪回報層級只能是 `blocked`，不是 `contained`，更不是 `root_cause_fixed_and_verified`。

**已走管道**：`dept_send.py --to-manager --priority P1`（
`item_20260805T090132643067Z_alert-control-gate-source-healt`），請經理二選一：
(A) 把 `src/volpred/ops/`、`config/control_gate_registry.json`、`tests/` 納入本部門
owned_paths（建議；擁有 `platform_ops` task_type 卻不能寫對應程式碼 = 所有 platform_ops
任務都無法結案）；(B) 指派有寫入權的執行體照 P1–P6 套用。

**同輪處理的 incident（不在派工單上，但屬本部門轄區）**

收尾 commit 時發現 `git_writer_lock` 一律回 `cannot snapshot current index`；
治理部與會員部同時送 P1 request 來（全 repo 的 commit 都過不去）。
`.git/index.lock` 判定為孤兒——0 bytes、滯留 483 秒、`lsof` 無持有者、全機無 git 行程，
四項 fail-closed 檢查齊全才動手，依 2026-07-28 前例**改名**保留為
`.git/index.lock.stale-20260805T090147`（不刪除，證據留存）。解除後 `git status` rc=0，
本部門 commit `fdecaaea7` 落地，兩個部門已回覆可重試。

這只是 **contained**：這是 error_log 記載的 index.lock class **第 5 次**。機械 owner
`phase_z.reclaim_leaked_index_lock()` 只回收帶 owner sidecar 的鎖，git 原生操作留下的
無 sidecar 鎖落在盲區（2026-08-04 13:49 已知，followup 仍在池中）。修復面在
`scripts/dispatch_supervisor/`——同樣寫不了，卡在同一張 owned_paths 裁決。

**順帶回報的兩個流程缺陷**
- 同一 canonical 任務被派三張重複工作項。
- `alert_remediation_bridge` 對同一 detector 的同一根因開了第二張單
  （`..._20260802` 與 `..._20260805`，差別只是「1 類」變「2 類」source）——
  memory `feedback_incident_not_alert_task_mapping` 指的同一個 class。
