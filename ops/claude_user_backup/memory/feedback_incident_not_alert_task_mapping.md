---
name: feedback_incident_not_alert_task_mapping
description: 自動修復重複開單的根因是 alert→task 無狀態映射；反覆修不好的問題要重新設計而非再補丁（2026-07-21 老闆連兩則 Telegram）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: db1ef130-5ee7-4c51-9652-897695d61137
  modified: 2026-07-21T13:32:50.697Z
---

2026-07-21 老闆連兩則：「你就一直啟動自動修復修這一些就飽啦，他一直出現你一直修就在這邊浪費資源」
／「這個問題不是單次的問題已經很多次你還是修不好？叫你重新設計重新架構你又不要。」

實測（storage/next_tasks.json）：自動補救類任務 7/18=3 → 7/19=13 → 7/20=24 張單調爆量。
重複群：PHASE-Z 系列 ~19 張、CI 紅燈修復 14 張（同 run 反覆 attempt）、WS-B worker_orphaned
一次噴 7 張、dreaming persistent_alert 11 張。關鍵觀察：**治本任務早就在池子裡**
（assign_eb78aedc / assign_e7643d81 / assign_commit_atomicity_gate），alert 仍照樣再開新張。

**Why**：alert→task 是**無狀態映射** —— 每偵測一次就開一張新任務，系統裡沒有「同一件 incident」
這個實體，也沒有 resolution 條件。所以不管底下哪個 bug 修沒修好，單子都會一直生。
這不是「某個 bug 修不好」，是這一層設計缺少收斂語意。
[[feedback_alert_is_a_task_not_a_chore]] 讓 alert 一定會變任務，但沒定義何時**停止**變任務 ——
本則是它缺的另一半。

**How to apply**：
- 診斷「一直在修同一件事」時，先量化重複張數與時間曲線，再判斷是 bug 沒修好還是迴圈沒收斂。
  若治本任務已在池中卻仍持續開單 → 一定是抑制層缺失，不要再開一張修 bug 的單。
- incident 要是有狀態的一等公民：fingerprint、首次發生、發生次數、目前處置任務、
  狀態機 open→mitigating→suppressed→resolved。任務是它的子項，不是它本身。
- 自動修復 N 次未收斂 → **升級為根因重構任務**，不是繼續重試（見
  [[feedback_gates_fix_immediately_two_strikes_switch_model]] 的同構精神）。
- 老闆說「重新設計/重新架構」時，交出「加個去重旗標」等表層修補是違規 —— 見
  [[feedback_refactor_over_patch_no_legacy]]。先交設計文件待過目，再分 Phase 實作。
- 這類任務改的是運營機器本身 → 一律 main_thread 重構獨立軌，不得走 hourly 派工
  （[[feedback_refactor_independent_execution]]）。

追蹤任務：assign_10927b4e（2026-07-21 08:20 標 succeeded）。

## 續集：同日 21:26 復發 —— 重架只做了半套（2026-07-21 晚，老闆第三則：「這算是治標不治本吧？」）

assign_10927b4e 結案說明寫的是「incident-lifecycle P5 收斂：per-instance 模型退役
（merge 883903a96），worker_orphaned / worktree_unmerged instances[]」——
**只涵蓋兩支 fingerprint 家族，PHASE-Z 的 foreign-file 那一支沒進去**，所以同日晚上照樣噴警報。
單子已標 succeeded，沒有任何機制會發現漏掉的家族。

當晚 pool 實測：PHASE-Z 相關 pending 仍有 9 張，其中「解決 1 份長期無主的產物（reaper held 超過 TTL）」
**三張標題完全相同**（assign_1fd87db1 7/19、assign_fedadc8d 7/20、assign_dcd117ad 7/20）。
治本單 assign_c90c43c7（producer-scoped workspace）priority 2，與清運單同級 → 永遠輪不到。
另 `volpred.ops.foreign_incident --check` 出現死結：檔案已 quarantine 但 main checkout 仍髒 →
closeable=false 永不可關，而未關 incident 會讓 dispatch_slot_budget.py 壓低每班 slot cap
（清運做完仍扣吞吐，違反 [[feedback_gates_smooth_no_deadlock]]）。

**追加 How to apply**：
- 宣告「迴圈已重架」前，列出**所有** fingerprint 家族並逐一確認涵蓋，否則就是半套完成
  —— 這正是 [[feedback_declare_complete_requires_class_sweep]] 的同一條規則被漏用。
- 收斂類重架的結案說明必須指名涵蓋了哪些家族；沒指名 = 不可標 succeeded。
- 判斷「治本單存不存在」不夠，還要看它的 **priority 是否高於同 class 的清運單**；
  同級 = 等於不存在。
- responder 這類唯讀角色查到根因時，正確動作是開 P1 治本單 + 走 main_thread lane
  （[[feedback_refactor_independent_execution]]），不是自己動手改 repo。

後續任務：assign_99487a53（pending_main_thread，涵蓋 PHASE-Z ownership + 死結出口 + 三張重複單合併）。
相關：[[feedback_dont_deflect_act_on_repeated_complaints]]、[[project_loop_engineering_layer]]、
[[feedback_fix_verify_then_report]]。

## 續集二：msg 1277「為什麼還是沒根除？為什麼會出現無法認領的問題」（2026-07-21 23:20）

「無法認領」= `scripts/dispatch_supervisor/phase_z.py` 的 orphan-half probe，
`_ORPHAN_HALF_MAX_CANDIDATES = 8` 是**全域** cap，候選超過就 fail-closed 整批放棄
（`too_many_candidates`）。多線共用同一 checkout 時 foreign 髒檔 50+，log 出現 38 次跳過，
峰值 23 candidates ⇒ 高併發下自動回收等於沒開。單子 `phase_z_orphan_half_cap_high_concurrency_20260721`
（P3）已在池中。

**新增的機制性發現（比 bug 本身重要）**：治本單 `assign_c90c43c7`（producer-scoped workspace，
7/19 建）到 7/21 23:20 `status_history` **完全是空的 = 0 次被 claim**，priority 2 與同 class
清運單同級。而且——**沒有任何角色能改 priority**：`task_pool_claim.py annotate` 明確拒絕
lifecycle/identity 欄位（`refusing lifecycle/identity fields ['priority']`），
`volpred ops assign` 只能開**新**單。於是「提升既有治本單優先級」在系統裡不存在這個動作，
唯一出路是再開一張新單 —— 正是重複開單病本身。這是 [[feedback_gates_smooth_no_deadlock]] 的死局。

**How to apply**：
- 診斷「治本單為何沒被做」時，先看 `status_history` 是否為空（0 次 claim），這比看 status 準。
- 要求某個 class 收斂前，先確認 escalation 通道存在；沒有通道就先補通道，否則所有「已提為治本主線」
  的宣稱都是空的。
- responder 查到治本單躺著時，能做的只有 `annotate --set escalation_note=...`（非 lifecycle 欄位可寫）。
  要誠實告訴老闆「我改不動」，不要說「已排入任務池」（[[feedback_responder_cannot_be_a_queue_excuse]]）。
