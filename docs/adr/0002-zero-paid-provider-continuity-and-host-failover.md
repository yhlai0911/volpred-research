# ADR-0002：零增量付費的供應商續跑與主機切換

- **Status**：Accepted
- **Date**：2026-07-23

## Context

目前備援主要是 Claude 執行失敗後改呼叫 Codex，尚未把任務需要的能力、審查資格、額度狀態、付費邊界與可恢復檢查點建模；換機流程也仍依賴硬編路徑、手動搬 secrets 與多層排程安裝，不能證明功能等價或防止雙主。

## Decision

AI 執行只允許既有 OAuth／桌面訂閱內含額度，**不得**啟用 API key 按量計費、usage credits、auto-reload、付費 overflow 或自動購買額度。Provider registry 必須記錄認證方式、能力集合、正式 gate 資格、健康／額度狀態與下次探針時間；router 只有在候選供應商同時滿足能力契約與零增量付費政策時才可派工。

供應商不可用時，能由其他合格訂閱管線完成的 WorkItem 可重新路由；只能做純計算或草稿的工作可在隔離環境繼續；需要特定供應商或正式審查資格的 gate 保持 blocked。系統以有界、低頻、可稽核探針確認額度或認證恢復，並從最近的已驗證檢查點自動接續，不重複已完成的外部效果。

第一版主機連續性只承諾 Apple Silicon macOS 對 Apple Silicon macOS。新機先成為 warm standby，完成版本、依賴、權限、skills、排程 spec、canonical state、artifact hash 與 shadow 行為驗證後，才能原子取得遠端主控租約；所有正式 commit／effect 在執行當下都要驗證 lease fencing token。目標為已驗證狀態 RPO=0、warm failover 在五分鐘內恢復，並保留可從空白相容 Mac 進行較慢 cold restore 的能力。

遷移採單一引導流程：可重建依賴由 manifest 重建，服務 secrets 只透過 Keychain／secret store 安全匯入或重新輸入，AI OAuth、MFA 與 macOS TCC 權限必須在新機互動式重新授權；不得複製登入 session、明文 token 或整個 Keychain。

## Consequences

- 「有模型可用」不等於「任務可 failover」；能力與審查契約優先於吞吐量。
- 所有付費型憑證與路由必須在設定驗證、啟動與每次派工三層 fail closed。
- Supabase／lease control plane 不可達時不得產生正式 commit 或外部效果，以避免 split brain。
- 換機不再以「程式能啟動」為完成，必須以 parity manifest、shadow receipts、租約切換與回滾演練證明。
