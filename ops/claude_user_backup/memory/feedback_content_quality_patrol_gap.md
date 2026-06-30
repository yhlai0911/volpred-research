---
name: feedback_content_quality_patrol_gap
description: 自主運營必須有「內容品質巡檢」層（節奏/主題多樣性/digest唯一/排版/前端render/內容完整），不只基礎設施巡檢
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 77a63c95-6fbc-4cb3-bde4-2847b559951d
---

用戶 2026-06-24 質疑點破 meta-root-cause：**系統只有「基礎設施/outcome 巡檢」（ops_dashboard cron-stale、check_alerts 池空/release-gap、脫班 5h dead-man），缺「內容品質/流程正確性/排版/前端健康」這層主動巡檢。**

**Why**：當天 4 個問題——發文脫班、同日兩篇 digest、「每日精選導讀」標題重複、前端 React #418 hydration——**全部靠用戶人工發現**，因為品質巡檢層不存在。系統只知道「機器活著」，不知道「產出的東西對不對」。這是自主運營的根本盲區：AI 不只要維持機器運轉，還要自檢產出品質。

**How to apply**：
- 設計見 `docs/refactor_plan_content_quality_patrol.md`。新固定任務（每 2–6h），出 `storage/ops/content_quality_report.json` + breach 走既有 `send_alert`。
- 巡檢項目：發文節奏健康 / 主題 narrative-arc 多樣性（早抓 release deadlock 源頭，見 [[project_cloud_agent_git_divergence]] 同期 refactor_plan_release_layer_deadlock）/ digest 每日唯一 / 排版正確（標題前綴重複）/ 前端 render 健康（fetch 關鍵頁查 React error marker）/ 內容完整（真圖表+來源）/ release candidates 連續 0 早警。
- **判斷新巡檢是否該建的準則**：若某類問題「只有用戶會發現、系統不會」→ 就是缺巡檢，補一條。不要等用戶當人工巡檢員。
- 不取代基礎設施巡檢，是補內容品質層。

**關聯**：此 session 還有 release-layer deadlock（`docs/refactor_plan_release_layer_deadlock.md`，鎖機制「鎖+等review」對自主系統不合理）+ digest 冪等 + 前端 #418/標題 待實作。品質巡檢是這些的 meta-fix（建立後自動抓同類）。
