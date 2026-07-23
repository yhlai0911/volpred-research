# ADR-0003：混合式 vNext 與三階段前端切換

- **Status**：Accepted
- **Date**：2026-07-23

## Context

目前 `frontend-v2-fix/` 同時提供原版路由與 `/v3/*`。實際檢視顯示原版在功能覆蓋、資訊密度、行動版導覽與 Admin 操作較完整；v3 在長文閱讀、字體與研究敘事較佳，但存在重複 wrapper、缺少部分原版路由、無效連結、初始 mock／舊資料閃現及過重 DOM。兩者都包含應保留的價值，直接選一套會造成確定的功能或體驗退步。

## Decision

建立混合式 vNext：所有模式共用一套 canonical 資料存取、功能契約、路由能力、認證、SEO 與 analytics；預設採原版的清楚資訊架構、功能完整性與行動版效率，長文、研究檔案與深度頁採 v3 的 editorial reading 優勢。呈現模式只能改變資訊密度與視覺，不得複製業務邏輯、資料 fetch 或 Admin command path。

公眾首頁聚焦「目前風險、該注意什麼、證據在哪裡」；登入後才增加收藏、追蹤、提醒與個人化內容。Admin 的觀測功能與 operator console 分離：前者可維持高資訊密度，後者只能透過 typed operations API 提交受控命令，不直接改 DB 或 JSON。

原版與 v3 在 vNext 通過 gate 前必須保持可用，而且不得刪除。**部署 vNext、將 vNext 設為預設入口、退役舊版**是三個獨立決策：每一步都要有 owner 明確核可；即使前兩步成功，沒有另一次明確批准也不得刪除原版或 v3。

## Launch Gate

切換預設入口前至少需證明：

1. 原版與 v3 的有效 route／功能 100% 盤點，vNext 無功能、資料與權限回歸。
2. 首屏直接呈現 authoritative data，不得先顯示 mock、過期資料或 hydration 後才修正。
3. 桌面與行動版核心流程、登入、會員、Admin、SEO、效能、可及性與 analytics 全數通過。
4. 小流量觀察至少七天，錯誤率、核心轉化與任務完成率不劣於基準。
5. 已實際演練一鍵回滾，owner 審閱證據後核可成為預設入口。

## Consequences

- `frontend-v3-design/` 與現行原版／v3 都是參考與回滾資產，不能因 vNext 開發而提前移除。
- 新功能先進共用 core，再由需要的 presentation 組合使用，禁止再新增第三套獨立資料流。
- 舊版退役時間取決於證據與 owner 決策，不由開發完成日期自動觸發。

