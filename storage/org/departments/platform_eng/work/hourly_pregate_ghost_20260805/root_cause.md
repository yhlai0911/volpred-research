# 已退役的 hourly_pregate 為何仍在盤點裡 —— 根因不是索引脫節，是 compaction 吃掉了退役證明

- 日期：2026-08-05（台灣時間 19:2x）
- 部門：platform_eng
- 來源：governance `item_20260805T100508608054Z`（請求把 registry 的 hourly_pregate 標為 retired）
- 結論：**治理部提的修法會是 no-op**——registry **早就已經標了**。真正壞的是讀取端。

## 1. 治理部的症狀陳述成立（我用 fresh audit 複驗，數字更糟）

`uv run python scripts/audit_control_gate_lifecycle.py`（2026-08-05T11:07:40Z）對 hourly_pregate 的判決：

```
mode: shadow
owner: scripts.hourly_dispatch_pregate     ← 該檔已移到 scripts/_legacy/
pdca_phase: act                            ← 不是 retired
review: {"due": true, "reasons": ["harm_outcomes=14>=1"]}
```

所以它不只是「被列進 29 道盤點」，而是**每次 audit 都判定需要複審**；
只要帶 `--materialize-reviews` 跑，就會替一道 2026-07-30 已正式退役的 gate 再開一張複審單。
治理部說「經理今天差點依據它的 shadow 狀態下令轉 real」——這個誤導是機械上必然，不是巧合。

## 2. 但治理部提的修法不會有效（這是本報告的重點）

`config/control_gate_registry.json:226-233` 現況：

```json
"lifecycle": {
  "phase": "retired",
  "last_action": "retire",
  "last_reviewed_at": "2026-07-30T10:59:31.600000+00:00",
  "review_task_id": "control_gate_review_hourly_pregate_20260730T040739_df86bffb6358"
}
```

**已經是 retired 了。** 再標一次不會改變任何輸出。

## 3. 真正的根因（追到行）

`src/volpred/ops/control_gate_lifecycle.py:2792`

```python
retirement_effective = (
    lifecycle.get("last_action") == "retire"
    and reviewed_through is not None
)
```

第一個條件成立，第二個不成立。`reviewed_through = _review_watermark(gate, tasks)`（:2523），
而 `_review_watermark`（:1843-1890）要在**存活的 next_tasks 池**裡找到一列同時滿足：
`id == review_task_id`、`status == "succeeded"`、`gate_review_id == gate_id`、
`gate_decision == last_action`、`gate_live_readback` 非空、
`gate_registry_reviewed_at == lifecycle.last_reviewed_at`。

那一列在池裡（3961 列中確實有它），但它**已經被壓成 tombstone**：

```
id, status, task_type, priority, title, created_at, completed_at, archived_at, tombstone
```

`gate_review_id` / `gate_decision` / `gate_live_readback` / `gate_registry_reviewed_at` /
`gate_review_watermark` **全部不在 `_TOMBSTONE_KEEP_FIELDS` 裡，已被刪除**。
終態任務滿 3 天就壓（`unblock_expired_blocked_tasks.COMPACT_AGE_DAYS`），該任務完成於 07-30，
所以 **08-02 起** 這道 gate 的退役就永久失效，並回到 `act` 迴圈——不會自癒。

**而證據並沒有消失，只是搬家了。** `storage/next_tasks_archive/2026-08.jsonl` 裡的完整記錄
每一個欄位都在，且與 registry 對得起來：

```
gate_review_id:            "hourly_pregate"
gate_decision:             "retire"
gate_registry_reviewed_at: "2026-07-30T10:59:31.600000+00:00"   ← 與 registry 完全相同
gate_live_readback:        "canonical runtime schedule has no pregate config; …"
```

## 4. 這是同一個 class 今天的第二個實例

`next_tasks.py:738` 的 `is_tombstoned()` docstring 已經把這個 class 命名清楚：

> Any detector that judges a row by the *absence* of such a field must call this first,
> or it will keep re-deriving the same answer from data that was deleted on purpose.

- 今天早上：`event_reaction_coverage` 以「沒有 deadline」判 malformed（gate 窗口 14 天 vs tombstone 3 天）。
- 現在：`_review_watermark` 以「找不到證明欄位」判「沒複審過」。

兩個都在同一個模組家族、同一天、同一個根因：**owner 已經存在，漏的是呼叫。**

## 5. 建議修法（落點在 Zone A，本部門不得自行實作）

`src/volpred/ops/control_gate_lifecycle.py::_review_watermark`：

1. 比對前先問 `is_tombstoned(task)`。
2. 命中 tombstone 時，到 `storage/next_tasks_archive/` 取回同 id 的完整記錄再比對。
   **不要改成「tombstone 就直接相信 registry」**——那會把「必須有機械證明」這個要求拿掉，
   等於用放寬 gate 來修 gate。證據還在，讀對地方就好。
3. 補一條 regression test：終態 review task 被壓成 tombstone 後，
   `retirement_effective` 仍須為 True、`pdca_phase` 仍須是 `retired`。

附帶（同一次改）：`mode` 仍是 `shadow`、`owner` 仍指向已移進 `scripts/_legacy/` 的
`scripts.hourly_dispatch_pregate`。retirement 生效後這兩欄不再影響判決，但它們仍會出現在
盤點輸出裡誤導讀者，建議一併更新 owner 指標並在 registry 註記退役裁定
（`config/runtime_schedules.json:6` 的 H4-4 裁定）。

**本部門為什麼不自己改**：D22 定案 `src/volpred/ops/**` 維持 Codex Zone A，不給任何部門。
`config/` 在本部門轄區內，但單獨改 config 不能修好這件事——所以本輪不動 config，
避免留下「看起來修過了」的假象。
