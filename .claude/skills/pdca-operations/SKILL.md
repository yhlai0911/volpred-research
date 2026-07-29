---
name: pdca-operations
description: >
  把已觀察到的營運問題或改進機會收斂成可重播修正、回歸證據與制度化防線。
  用於 incident follow-up、使用者糾正與流程改善；不擁有 task、memory 或 schedule。
---

# PDCA Improvement Leaf

這是改善與制度化的 leaf，不是平台 loop、health scanner、dispatcher 或 business clock。
上游必須先提供具體 finding／incident／execution receipt；沒有證據時先回到 domain
診斷。

## 一圈

1. **Plan**：寫出 observable gap、canonical owner、根因層級、成功判準與最小回歸案例。
2. **Do**：在既有 owner 修 code／contract／state machine／checker；重跑或補值只算
   `contained`。
3. **Check**：重跑案例與相關測試，再從 provider、API、hash 或 downstream
   acknowledgement 獨立回讀。一次乾淨 observation 不足以結案。
4. **Act**：把防復發放進同一 owner 的 contract、test、automation、skill 或操作紀錄；
   不新增平行 runner。

Incident 的 strike、sustained-clean 與 resolution state 由
`src/volpred/ops/incident.py` 機械裁決；PDCA 只提交上述 evidence，不另算一次乾淨結果。

若 Act 需要：

- 新工作登記：交給當下 task-pool mode 允許的 canonical ingress。
- 研究記憶：交給 memory workflow／writer 與 provenance gate。
- cadence 變更：交給 Operations Core schedule proposal／owner transaction。
- 外部通知：交給該 domain 已存在的 notifier，並保存 delivery receipt。

本 skill 不直接寫上述 state，也不假設它們目前的模式。

## Completion

只有「症狀 evidence → 根因 → 底層修正 → 回歸 + live readback → 同 owner 防線」全鏈可
追溯，且 canonical incident lifecycle 接受 resolution，才回報
`root_cause_fixed_and_verified`。缺任何一步回報 `contained`；根因不明則 `blocked`。

`references/operations-cadence.md` 只說明 ownership handoff，不列週期或 job 現值。
