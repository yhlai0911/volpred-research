# foreign incident `d930b5e23d12e238` — 40 路徑逐檔歸屬裁決（第 1 輪：證據盤點）

**任務**：`assign_65b27c8b`（P1，PHASE-Z 卡住檔案 incident）
**執行**：hourly-slot-2-d5c99af8459244ce9560dd8f9bf42315 / 2026-07-19 19:0x
**上位文件**：`docs/governance/2026-07/phase_z_ownership_external_review.md`（D1–D5 裁決）

---

## 1. 本輪推翻的前提

incident 任務描述的第一句是：

> 「40 個未提交檔案不是任何一班 fire 產出的，最長已連續 83 班還在工作區。**連續多班沒清，代表沒有人會回來收**。」

**這句話對 40 個路徑中的 10 個是錯的。** 以「open 任務的 description/title 明文提到該路徑」為判準
（不是目錄、不是 suffix、不是 mtime —— 這三者正是 §3(4) 點名的 semantics-as-provenance），
逐路徑比對任務池中 `pending / in_progress / blocked` 的任務：

| 路徑 | 指名它的 open 任務 |
|---|---|
| `scripts/detect_price_split_breaks.py` | `paper_0050_snapshot_repoint_20260719`(P1)、`price_cache_stale_fill_0050_20250610`、`k_reruns_0050_snapshot_contaminated_20260719` |
| `paper/garch-x-vix/data/0050_tw_vix_2007-2022.csv` | `paper_0050_snapshot_repoint_20260719`(P1) |
| `paper/taiwan-vt/data/0050_tw_twii_..._2008-2026.csv` | `assign_7f508612` |
| `scripts/merge_worktree.sh` | `assign_c441604e`、`merge_worktree_k1262v4_overtrigger_20260719`、`assign_06d6352d` |
| `scripts/reclaim_stale_worktrees.py` | `worktree_harvest_wave3_dirty_stale_20260719` |
| `experiments/k1380/README.md` | `k1380_rerun_staged_correct_qlike` |
| `config/experiment_artifact_exclusions.json` | `assign_0e6a740b`（D5） |
| `storage/work_log.json.bak_graphify_verdict_20260717` | `assign_0e6a740b`（D5） |
| `config/runtime_schedules.json` | `assign_f59976b6`（blocked） |
| `scripts/gen_codex_cli_reference.py` | `platform_ops_codex_cli_upgrade_0144_5`（blocked） |

最尖銳的一筆：**`paper_0050_snapshot_repoint_20260719`(P1) 的「驗證指令」逐字就是
`uv run python scripts/detect_price_split_breaks.py --csv-scan`**，而它的待辦 (a) 是
「從已修好的 DB 重建兩個 snapshot CSV」—— 那兩個 CSV 也在這 40 個路徑裡。

也就是說：若任何一層 cleanup 依「卡了 83 班 ⇒ 沒人要」把這批檔清掉，會直接摧毀一張
open P1 的工具與輸入。這是 D5「不得由 cleanup layer 猜著收」的第二個實證反例
（第一個是 K1380 的 `*_INVALID_20260716.*`）。

**方法論註記**：「卡在工作區的班數」量的是**沒有人有權限提交它**，不是**沒有人要它**。
在共享 checkout + 「agent 不得跑 git mutation」的規則下，這兩件事本來就會被系統性混淆——
一個檔案可以同時「被 open P1 需要」且「永遠沒有一班 fire 有資格 commit 它」。

## 2. incident 目前無法關閉，且原因是結構性的

`incident_closeable()` 要求每個路徑「不得還髒在 main checkout」。本輪實測：
40 個路徑 **全部** `covered=true`、**全部** `still_dirty_in_main=true` ⇒ `closeable=false`，
blocker 全是同一句「已保存但仍髒在 main checkout」。

而能讓它們變乾淨的三條路，目前**全部封閉**：

| 路徑 | 為何走不通 |
|---|---|
| PHASE-Z 提交 | `phase_z.py` 只 commit `dirty_now - baseline`（本班自己產出的）。foreign 檔依定義不在其中——這正是 incident 存在的原因 |
| 本班 fire 自行 commit / 刪除 | dispatch 規則硬禁 agent 在 shared checkout 跑 git mutation；且本刻有 3 個 slot 併行，動別人的檔正是 `docs/error_log.md` 2026-07-10 那三次事故 |
| cleanup layer 自動收編 | D1 明令停止；且 §1 已證明會誤刪 open P1 的資產 |

⇒ **incident 沒有 actuator。** D3 把「沒有 actuator 的 CRITICAL 信」換成「有 actuator 的
incident」，但 actuator 只接在**懲罰端**（`dispatch_slot_budget.py` 降 cap 4→2），沒有接在
**解除端**。結果是每一班都以半速派工，且沒有任何一班能靠自己走出來。

這一點恰好違反本 class 自己的驗收標準（§7.2 逐字）：
「任何 writer crash / 同 path 並行 / pre-dirty 再修改 / 未知檔案類型，**都在有限班數內必達
terminal state**」。incident 自己不滿足有限班數可達 terminal state。

**不採取的做法**：不放寬降載、不把 incident 標 succeeded 關單。兩者都會解除壓力但不動檔案，
是把 forcing function 變成靜音鍵——`_CLOSED_STATUSES` 的設計已明確拒絕這件事
（`blocked` 刻意不算關閉）。誠實的狀態是：**壓力該留著，缺的是出口**。

## 3. 一併發現的 gate 缺陷（未修，只記錄）

`live_workspace_paths()`（`foreign_incident.py:327`）判定「檔案存在於某個 registered worktree」
即算 covered。但 worktree 是**全 repo checkout** —— 任何 tracked 檔案在每個 worktree 裡都必然
存在，與那個 worktree 是否含有這些**編輯**無關。

實測：26 個路徑的 `live_workspace` 全部指向同一個 worktree
`agent-a0ef53c7c992ec1df`（且該 worktree 已被 dispatch report 判為 stale、無進度 6.0h）。
這 26 筆的 coverage 是空證據；真正撐住 never-lose 的是 quarantine ref（34/40 命中），
其餘 3 個 ` D`（已刪除）路徑可從 HEAD 取回。

**故 never-lose 目前實質成立，但不是靠 `live_workspace` 這一條。** 未在本班修補：
`foreign_incident.py` 本身仍是 untracked、且併行 slot 可能持有它——在飛行中改一個
untracked 的 gate 檔正是本 class 反覆犯的錯。修法應與 D4 同批，並附「worktree 內該路徑
相對其 HEAD 有差異」的真實斷言。

## 4. 本輪產出與下一步

**已做**：40 路徑逐檔比對 open 任務（機械、可重跑）｜推翻「沒人會回來收」前提（10/40 有主）｜
記錄 incident 無 actuator 的結構性成因｜記錄 `live_workspace` 空證據缺陷。

**未做（刻意）**：沒有動任何一個檔（無 git mutation）｜沒有關單｜沒有放寬降載｜
沒有修 `live_workspace`｜沒有猜那 30 個無主路徑的歸屬。

**下一步（`assign_65b27c8b` 續辦）**：
1. 10 個有主路徑 → 由各自的 owner 任務在**自己的 worktree** 裡處置，不走 cleanup layer。
2. 30 個無主路徑 → 需要一條**有寫入權限的 sanctioned 出口**（`git_writer_lock.py run` 是
   現成的序列化寫入器），否則裁決做完也落不了地。這是 D4 之前的最小止血。
3. 出口存在之前，incident 維持 open、降載維持生效——這是誠實狀態，不是待辦漏做。
