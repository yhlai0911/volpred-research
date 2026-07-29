---
name: platform-ops-manager
description: >
  執行一次性的 VolPred ops triage：讀 live handoff/health/receipts、排序當前問題、處理或
  handoff 一個可驗證動作。用於 ops loop、平台巡檢、idle triage；不是 scheduler。
paths:
  - "storage/ops/handoff_latest.md"
  - "storage/ops/dashboard_latest.json"
  - "storage/ops/dispatch_state.json"
  - "storage/ops/task_pool_mode.json"
  - ".claude/skills/platform-ops-manager/**"
---

# Platform Ops Triage

每次 invocation 是一個 **ephemeral pass**。它由使用者或正式 control plane 觸發，完成
本次 triage 後回報；它不建立下一次觸發、不維護 cadence，也不擁有 pending queue。

## Pass

1. **Context**

   ```bash
   sed -n '1,/^---$/p' storage/ops/handoff_latest.md
   uv run volpred ops control-plane-summary
   uv run volpred ops platform-patrol-summary
   ```

   若要宣稱整體健康，再跑 `uv run volpred ops daily-checkup --json`。只讀必要 detail，
   不全文載入大型 state。

   排程相關 finding 才讀 `config/runtime_schedules.json` 與 exact fire receipt；這是
   schedule owner pointer，不授權本 pass materialize 或觸發 job。

2. **Triage**

   優先順序：

   1. 當前 user-assigned work
   2. live critical incident／下游 delivery mismatch
   3. 已被正式 ingress 接受且可執行的 work
   4. agent-discovered 改善

   同一 task／incident identity 已有人執行時只觀察或 handoff，不能搶 owner。

3. **Act**

   選一個 bounded action，交給 domain skill／CLI。只用 canonical writer；不直接編輯
   task、memory、feed 或 remote rows，也不執行 repository mutation。

   新工作需要登記時，先讀：

   ```bash
   jq '{enabled, mode, schema}' storage/ops/task_pool_mode.json
   ```

   再呼叫 live mode 接受的 ingress。由 writer enforcement 決定 admission；若拒絕，
   保存 structured reason 並走它指定的 control-plane handoff，不假設固定模式。

4. **Verify**

   每個 mutation 保存 receipt，再由 provider／API／hash／downstream acknowledgement
   回讀 exact target。Incident resolution 交由 `src/volpred/ops/incident.py` 的
   strike／sustained-clean lifecycle 裁決。只有 task receipt 沒有 effect readback，
   最多是 `contained`。

5. **Close the pass**

   回報做了什麼、receipt/evidence、目前狀態與真正 blocker，然後結束互動 turn。持續
   execution 由正式 owner 保持，不由本 skill 自我喚醒。

## Boundaries

- schedule observation／change → `admin-ops/references/scheduling.md`
- 持續改善／制度化 → `pdca-operations`
- member QA → `member-questions`
- feed／paper／research → 對應 domain skill
- loop trend 解讀 → `references/loop-health-and-dreaming.md`

完成條件：本 pass 的 target、owner、action、receipt 與 readback 都可指出；無新 owner、
無固定 task mode 假設。
