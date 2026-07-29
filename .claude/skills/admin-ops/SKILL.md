---
name: admin-ops
description: >
  路由平台管理工作到既有 Admin UI、Admin API 或 `uv run volpred ops`。
  用於內容、策略、會員問題、論文交付、使用者、同步、站務觀測與安全部署 handoff；
  不負責研究內容、文章寫作或排程執行。
user-invocable: true
---

# Admin Ops

這是薄的 **surface index**。Admin 是 observer／operator surface，不是 canonical
control plane；資料、target、排程與 task admission 仍由各自母本決定。

## 執行

1. 分類 domain，依下方指標只讀一份必要 reference。
2. 任何動作前回讀該 domain 的 canonical config／summary；不要從本 skill 複製現值。
3. 選最窄的共享入口：
   - 人工操作或視覺檢查：active frontend 的 `/admin/*`
   - 本機可重播操作：`uv run volpred ops <command>`
   - 程式整合：active frontend 的 `/api/admin/*`
4. 寫入只走既有 CLI／API／transactional writer。若入口缺失，先補 shared logic，再接
   CLI／API，最後才加 UI。
5. 外部效果必保存 command/API receipt，並從 provider 或 reader-facing surface
   獨立回讀。沒有回讀只能回報 `contained`。

完成條件：選用的 owner 可指出、所有 mutation 都有 receipt、每個外部效果都有 live
readback，且沒有另建資料或排程 owner。

## 按需 references

- 平台入口與能力探索：`references/surfaces.md`
- CLI／API 操作契約：`references/platform-api-manual.md`
- target、runtime 與部署 handoff：`references/deploy-and-runtime.md`
- 正式時鐘的唯讀診斷：`references/scheduling.md`
- source-of-truth 與同步：`references/data-flow.md`
- Supabase projection：`references/supabase-sync-checklist.md`
- 策略 metadata 上下架：`references/strategy-lifecycle.md`
- incident 結案 gate：`references/governance.md`
- 拓樸摘要：`references/architecture.md`
- 單次背景觀測：`references/monitor-usage.md`
