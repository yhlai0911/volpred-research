# Platform Surfaces

先從 live tree 探索，不維護會漂移的頁面／command 清單。

## 解析 active surface

```bash
FRONTEND_KEY="$(jq -er '.active_frontend' config/project_targets.json)"
FRONTEND_PATH="$(jq -er --arg key "$FRONTEND_KEY" '.frontends[$key].path' config/project_targets.json)"
rg --files "$FRONTEND_PATH/src/app/admin" "$FRONTEND_PATH/src/app/api/admin" | sort
uv run volpred ops --help
```

若某個 branch 不存在，以 filesystem／CLI help 為準；不要從歷史文件推測。

## 選擇入口

| 需求 | 首選 |
|---|---|
| 人工瀏覽、審核、操作 | active frontend 的 `/admin/*` |
| 本機可重播與自動驗證 | `uv run volpred ops <command>` |
| typed web integration | active frontend 的 `/api/admin/*` |
| 正式 business clock | Operations Core canonical spec |
| task admission | task-pool mode + canonical writer enforcement |

Admin surface 不擁有 source data、task queue 或 schedule。它可以顯示 live state，也可呼叫
既有 mutation API，但成功必由 API receipt 與下游 readback 共同判定。

## Capability 缺口

若沒有合適入口：

1. 找到 canonical owner 與既有 write path。
2. 把能力加在 shared domain logic。
3. 曝露 CLI 或 API。
4. 需要人類操作時才接 Admin UI。
5. 加上 receipt schema、冪等 key、失敗狀態與 reader-facing readback。

完成條件不是「頁面上有按鈕」，而是 CLI/API/UI 共享同一 owner 且可重播驗證。
