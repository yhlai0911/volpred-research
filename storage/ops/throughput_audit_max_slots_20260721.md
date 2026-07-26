# max_slots 2→4 上線後吞吐驗收（assign_f59976b6）

- **驗收時間**：2026-07-21 21:40 CST
- **變更時間**：2026-07-19 10:40 CST（`config/runtime_schedules.json` max_slots 2→4 + `scheduler.load_max_slots` quota de-rate guard）
- **觀測窗**：變更後約 35 小時（07-19 部分日 / 07-20 完整日 / 07-21 至 21:20）

---

## 1. 吞吐：有提升，但**尚不足以宣稱**（樣本太小、基線變異太大）

任務池 `status=succeeded` 逐日計數（`storage/next_tasks.json`，依 `completed_at`）：

| 日期 | completed | 相對變更 |
|---|---|---|
| 07-14 | 57 | 基線 |
| 07-15 | 98 | 基線 |
| 07-16 | 53 | 基線 |
| 07-17 | 45 | 基線 |
| 07-18 | 57 | 基線 |
| **07-19** | **111** | 變更當日（10:40 上線，含變更前 10.7h） |
| **07-20** | **62** | 變更後**唯一完整日** |
| **07-21** | **99** | 變更後，**至 21:20 尚未整日** |

- 基線（07-14~18）平均 **62.0/日**、中位數 57、全距 **45–98**。
- 變更後唯一完整日 07-20 = **62**，與基線平均**完全持平**。
- 07-21 已達 99 且尚有 ~3h，是三日中最強訊號，但**單日 98 在基線期就出現過（07-15）**。

**誠實結論**：目前只有 **1 個乾淨的完整日** 落在變更後，而基線本身的日間變異（45–98）已覆蓋所有觀測值。**現有資料無法區分「加碼生效」與「基線正常波動」**。建議再觀察 3-4 個完整日再下判斷（見第 5 節 followup）。

### 1-recheck（2026-07-27，`throughput_recheck_max_slots_20260725`）

累積到 3-4 個完整日後重跑同一比對（`storage/next_tasks.json`，`status=succeeded`，依 `completed_at // updated_at`）：

| 日期 | completed | 分類 |
|---|---|---|
| 07-20 | 62 | 變更後完整日 |
| 07-21 | 136 | 變更後完整日（首驗時記 99「未整日」，事後補記完成後拉到 136） |
| 07-22 | 71 | 變更後完整日 |
| 07-23 | 22 | 變更後完整日 |
| **07-24** | **0** | ⚠️ 零完成日（見下） |
| **07-25** | **0** | ⚠️ 零完成日（見下） |
| 07-26 | 28 | 變更後完整日 |
| 07-27 | (今日未整) | 排除 |

**乾淨完整日重算**（排除 07-19 混合日、07-21 事後補記造成的異常尖峰、07-24/25 零日、07-27 今日）：07-20=62、07-22=71、07-23=22、07-26=28 → 平均 **45.75/日**、中位數 45。

- 對比基線（07-14~18）平均 **62.0**、中位數 57：變更後乾淨日平均**不升反降**（-26%），且全落在基線全距 45–98 內。
- 若把 07-21=136 也算進去，平均被單日尖峰拉高，但那是「事後補記完成時戳」造成的 retroactive bunching，非當日真實吞吐，**不可作為提升證據**。

**⚠️ 07-24 / 07-25 兩個連續零完成日**：逐欄位交叉核對（`completed_at` / `updated_at` / `succeeded_at` / `claimed_at` / `created_at`）—— **沒有任何一筆 `succeeded` 任務的任一時戳落在這兩日**。且 07-22/23/26 的紀錄都仍在池中（→ 不是 age-based 壓縮把它們清掉），故這是**真實的完成斷檔**，非時戳欄位假象。指向變更後期間存在派工 / 完成中斷（outage 或 dispatch 餓死），需對照 supervisor fire log 進一步確認（超出本次任務池層級稽核範圍）。

**複驗結論（定案）**：max_slots 2→4 **未證實提升吞吐**，乾淨完整日甚至略低於基線，且期間出現兩個連續零完成日。呼應第 2 節：cap 已非 binding constraint（66% cohort 只發 1 slot、全期 `slots_full` 僅 1 次）。**不建議再上調 max_slots**；下一步應查上游 —— (a) supervisor 每 cohort 發幾條主線程、(b) 單張任務 wall-clock、(c) 07-24/25 零完成斷檔的成因（fire 是否有發、發了為何零完成）。

## 2. 真瓶頸不是 slot cap —— 大多數 cohort 只跑 1 個 slot

`storage/ops/dispatch_state.json` rolling-100 completions，依 cohort 統計每次實際併發的 slot 數：

| 一個 cohort 用了幾個 slot | cohort 數 |
|---|---|
| 1 | **45** |
| 2 | 16 |
| 3 | 5 |
| 4 | 2 |

- 68 個 cohort 中 **66% 只發 1 個 slot**，用滿 4 slot 的只有 **2 次**。
- slot_id 分佈同樣傾斜：slot1 = 68、slot2 = 23、slot3 = 7、slot4 = 2。
- 整個 log 期間 `reason=slots_full` 只出現 **1 次**。

**即 max_slots 從 2 提到 4 之後，這個 cap 幾乎不再是 binding constraint。** 真正決定吞吐的是上游「supervisor 每個 cohort 決定發幾條主線程」以及單張任務的 wall-clock，不是 slot 上限。task description 第 4 點的假設（真瓶頸可能在 agent slot budget 4/6 或任務本身 wall-clock）**成立**。

## 3. ⚠️ 新風險面已實際發生：cohort-wide kill sweep

> **2026-07-23 follow-up 勘誤（`cohort_wide_kill_sweep_20260721`）**：下方將
> `exit=143` 推論為「supervisor 層整批 kill」的結論不成立。逐路徑稽核
> `scheduler.py` / `health.py` / `worker.py` 後，supervisor 只有逐 job/PGID 的
> timeout kill，沒有 cohort-wide kill primitive。實際 log 也顯示第一批
> slot-1 仍正常跑到 success（duration=1100.3s）；第二批 slot-2 先正常
> success（640.3s），其餘三個 Claude CLI 才同秒結束。因此觸發類別是
> **supervisor 外部 / Claude execution plane 的共同失敗**，不是 cohort drain
> 連坐殺。當時沒有 signal-sender audit trail，無法事後誠實地指定精確 PID；
> `23b8063de` 已將 raw signal-like exit 從 `killed_timeout` 改為
> `external_signal`（不再發假 hang CRITICAL，並釋放該 slot claim），
> `d93ebbb42` 已在下次發生時留 process-table snapshot 以追 killer。
> 本 follow-up 另補三個 same-cohort slot 的 regression：只有單一 slot 超過
> 3000s 時，只能 signal 該 slot PGID，兩個年輕 sibling 必須保留。

`killed_timeout` 逐日：

| 日期 | killed_timeout |
|---|---|
| 07-11 | 2 |
| 07-12 | 1 |
| 07-15 | 1 |
| 07-17 | 1 |
| **07-20** | **7** |
| **07-21** | **3** |

變更前約 **1-2/日**，變更後 **07-20 衝到 7**。但關鍵不在總量，在**型態**：

```
11:23:29  slot-2  killed_timeout  duration=671.5s
11:23:30  slot-4  killed_timeout  duration=131.2s
11:23:31  slot-3  killed_timeout  duration=611.7s
---
11:44:59  slot-3  killed_timeout  duration=450.4s
11:44:59  slot-1  killed_timeout  duration=930.5s
11:45:00  slot-4  killed_timeout  duration=270.5s
```

- 同一 cohort 的 3 個 slot 在 **1.5 秒內**全部返回 `killed_timeout`。
- 但它們的 **duration 差距極大（131s / 611s / 671s）**，且**全部遠低於 3000s hard cap**。
- 同時返回 + 不同存活時間 + 未達各自 cap ⇒ **這不是 per-job timeout，是 supervisor 層的整批 kill sweep**。一個才跑 131 秒（剛起步）的 slot 被連坐殺掉。

10 次 `killed_timeout` 中 **6 次來自這 2 個 sweep**。max_slots=2 時一次 sweep 損失 2 條主線程，=4 時損失 4 條 —— **加碼把單次 sweep 的爆炸半徑放大一倍**，這正是 task description 第 2 點預期的新風險面，且已實際發生。

## 4. PHASE-Z cohort 競態：有壓力跡象，但**未達 regression 門檻**

`phase_z cohort drain` 結果逐日：

| 期間 | committed | commit_nonzero | 失敗率 | 「gave up after retries」 |
|---|---|---|---|---|
| 07-14~18（前，5 日） | 110 | 10 | 8.3% | 13（2.6/日） |
| 07-19~21（後，3 日） | 70 | 11 | 13.6% | 14（4.7/日） |

- 失敗率 8.3% → 13.6%，但基線期 07-15 單日就有 6 次 gave up —— **樣本內變異已覆蓋此差距，不足以歸因於加碼**。
- **`safety-net auto-commit (agent left uncommitted)` 自變更後 = 0 次**（262 次 commit 中）。PHASE-Z 責任單一化的修法**持續有效**，這點是好消息。
- 但共用 checkout 的壓力有客觀證據：`orphan-half probe skipped — N candidates exceeds cap 8` 全期出現 **38 次**（實例：07-20 03:12 為 23 candidates），且單次 drain 的 `foreign` 清單長達 50+ 檔 —— 多條主線程共用一個 checkout 時，「別人的髒檔」規模已大到讓 orphan-half 認領機制直接放棄。這不會造成錯誤 commit（foreign 有被正確排除），但代表**孤兒半成品的自動回收在高併發下失效**。

## 5. 裁決

**不調回 max_slots**。理由：

1. 沒有 quota 連發 —— `quota_blocked` 變更後 4 次（基線 5 次），**未惡化**，de-rate guard 未被觸發。
2. 沒有 PHASE-Z 錯誤 commit —— safety-net auto-commit = 0，foreign 排除正確。
3. worktree 與磁碟**大幅改善**（見下），不是限制因素。
4. 吞吐雖未證實提升，但也**沒有下降**；slots_full 僅 1 次，代表 cap 已不再卡人 —— 調回去只會重新製造 requested-fire 被延的老問題。

### worktree / 磁碟（task 第 3 點）

| 指標 | 變更前基線 | 現在 |
|---|---|---|
| worktree 數 | 18 | **4** |
| 磁碟使用率 | 91% used / 85GB free | **13% used / 90GB free** |

兩項都**明顯優於**基線，`reclaim_stale_worktrees` 無需加頻。（現存 4 個中有 2 個 stale：`dispatch-slot-1-20b291d5-snapdup` 閒置 9.2h、`dispatch-slot-1-375ba0e3-k1380` 閒置 5.9h，已被 slot budget 釋放，待 reclaim。）

### 待辦（本次不做，另立 task）

1. **查清 cohort-wide kill sweep 的觸發者** —— 3 個 slot 在 1.5s 內同死、duration 全未達 cap，需定位是 supervisor watchdog、cohort drain 逾時、還是 launchd 層。這是本次加碼唯一的實質新風險。
2. **補足吞吐樣本** —— 再收 3-4 個完整日後重跑第 1 節比對，才能對「加碼是否提升吞吐」下結論。
3. **orphan-half cap 8 在高併發下失效** —— 38 次 skipped，考慮改為依 ownership 分群而非全域 cap。

---

*驗收人：hourly dispatch slot-1 / job f67fc237。所有數字可由 `storage/ops/dispatch_state.json`、`storage/next_tasks.json`、`~/.volpred/logs/dispatch_supervisor.log`、`git worktree list`、`df -h` 復現。*
