# ADR-0001：以交易式運營核心統一平台控制面

- **Status**：Accepted
- **Date**：2026-07-23

## Context

目前任務、排程、派工、Git 寫入、外部發佈、事故與主機狀態分散在本機 JSON、腳本、LaunchAgent、Supervisor 與多個 API 路徑。既有 `src/volpred/ops/`、dispatch supervisor、incident lifecycle 與 Git writer lock 已提供可保留的機械基礎，但仍缺少跨程序／跨主機的單一交易邊界，造成殭屍任務、雙寫、提交阻塞、外部效果無法證明與遷移後狀態不一致。

## Decision

VolPred 採用建於既有 Supabase PostgreSQL 上的 **Python 模組化單體運營核心**，實作集中在 `src/volpred/ops/`。它是 WorkItem、能力需求、已驗證檢查點、ChangeSet、EffectRequest、事件、outbox、incident、schedule materialization 與主控租約的 canonical 協調面；研究資料、文章、論文、實驗與其他可版本化產物仍以 repo／`storage/` 為研究真相。

所有可能改變 repo、運營狀態或外部世界的工作，必須先取得 durable WorkItem；純讀取健康探針只產生 Observation。Agent 只能提交不可變 ChangeSet 或具 idempotency key 的 EffectRequest，不能自行 commit、push、發佈或直接修改 canonical coordination state；正式落地分別由受主控租約保護的單一 commit worker 與 effect worker 執行，並以測試、雜湊與下游回讀產生 receipt。

`storage/next_tasks.json` 在正式接管前仍是現行 pending queue。切換時採一次性匯入、對帳、原子 ownership 切換，之後只保留為唯讀相容投影；禁止長期雙寫、靜默回退或讓新舊 owner 同時 materialize 任務。

## Considered Options

- **維持本機 JSON 加更多鎖**：無法提供跨主機交易、lease、outbox 與一致的恢復語意。
- **全面事件溯源**：現階段會增加不必要的 replay、projection 與維運成本；採 current-state tables 加 append-only event／receipt 即可。
- **拆成微服務**：團隊與部署規模不需要網路邊界，會放大部署與除錯負擔。
- **Big-bang 重寫**：會同時破壞仍在運作的研究與發佈流程，不符合逐能力驗證與回滾要求。

## Consequences

- 每項能力只有一個正式 owner，接管完成時必須在同一 gate 退役舊寫入路徑。
- Supabase 暫時不可用時，正式協調寫入與外部效果 fail closed；已隔離的純計算可繼續，稍後再提交成果。
- 既有 ops master 仍負責接管前的可靠性修復；本 ADR 不把其已完成成果作廢。
- 需要新增 schema migration、相容 adapter、outbox worker、lease fencing 與 failure-injection 測試。

