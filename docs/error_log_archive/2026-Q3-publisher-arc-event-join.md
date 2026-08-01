# 2026-08-02 — publisher arc-dedup warn 被事件文章 outcome join 誤報為 harm

**Class**：E（Dedup / narrative-arc）。**狀態**：`root_cause_fixed_and_verified`。

## 症狀

`publisher_arc_dedup` 的 PDCA review 把 `nfp_us_2026_08_07:T-7` 判為
`unjoined=1`，因此觸發 `harm_outcomes=1>=1`。然而 live feed `mile_84e3be0a`
已於 warning 後約 6 分鐘，以相同 `event_key=NFP_US_2026_08_07`、
`event_series_slot=T-7` 成功 published；dedup gate 全程是 `mode=warn`，沒有持有
publication lock。

## 根因

`control_gate_lifecycle._feed_identities()` 只投影文章 id、title、K/audience 與
question id；事件 identity 雖已有 canonical `_event_identity()`，卻只給
`candidate_or_event_stage` 使用。`publisher_arc_dedup` 採 `candidate_or_feed`，所以
同一篇事件文章在 feed 明明存在，outcome join 仍找不到。

## 底層修正

把 canonical event key/slot identity 收進統一 feed identity set；不新增 dedup gate、
不改 warning 為 block，也不降低 harm threshold。新增回歸測試以大小寫不同的 event key
驗證 `candidate_or_feed` 回讀 `published=1, unjoined=0`。registry Act 裁決
`retain`，即保留目前 warn-only 契約。

## 驗證與機械 owner

production feed 與 decision row 回放；focused lifecycle tests；完整 lifecycle audit
live read-back。機械 owner：
`src/volpred/ops/control_gate_lifecycle.py::_feed_identities` +
`tests/test_control_gate_lifecycle.py::test_candidate_or_feed_joins_published_event_stage_identity`。

## 同輪 PDCA 第二層：warn-only 不得把 unjoined 當 harm

第一個 review 完成後，全量 audit 又立刻把 4 個 `unjoined` 判為 harm：兩個是作者在
prewrite warning 後換掉的暫定標題，一個是 `pass_prewrite`，另一個是 alert remediation
本身做的 prewrite probe。warn-only dedup 不阻擋後續，因此「這個候選 identity 沒直接出現在
feed」不等於 gate 傷害；用舊 selection-constraint 的 `unjoined` harm 定義只會讓 advisory
觀測永久自我開單。

第二張 canonical review task 裁決 `recalibrate`：移除 `unjoined`；保留
`failed`、`missed_deadline`、`sequence_coverage_gap`、`worker_failed`，並把舊
`block_arc_dup`／`block_same_ref_recycle` resurrection 會直接產生的 `blocked` 納入 harm。
任何一筆硬鎖復活都會立即開 PDCA review，不必等 300 次 raw trigger。
raw trigger / distinct candidate 門檻仍保留，identity/source health 也未放寬；因此大量 warning
與 identity 壞資料仍會進 PDCA，但「作者改題或只做預檢」不再冒充發文事故。
