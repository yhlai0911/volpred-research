---
name: web-ui-ux-review
description: >
  審查或驗證 active frontend 的 UI/UX、資訊正確性、route parity 與 production render。
  用於前端改動、視覺抱怨或 deploy 前後 gate；target 必須從 config 動態解析。
---

# Web UI/UX Review

## 1. Resolve target

每次開始都重新解析，不從 skill 或歷史 commit 複製 frontend／service identity：

```bash
FRONTEND_KEY="$(jq -er '.active_frontend' config/project_targets.json)"
FRONTEND_PATH="$(jq -er --arg key "$FRONTEND_KEY" '.frontends[$key].path' config/project_targets.json)"
ACTIVE_SERVICE="$(jq -er '.deploy.active_service' config/project_targets.json)"
LIVE_URL="$(jq -er '.site.default_remote_url' config/project_targets.json)"
test -d "$FRONTEND_PATH"
test -n "$ACTIVE_SERVICE"
```

先讀 `.claude/rules/frontend-and-deploy.md` 與 active tree 的 local instructions。Admin 是
observer；畫面值必須回到 canonical API／data source。

## 2. Inspect before editing

- 用 `rg` 找同類 card、badge、collapse、empty/loading/error states 與 design tokens，
  重用現有 pattern。
- 若 active tree 同時有 base route 與 alternate presentation route，列出兩邊 exact
  files；同一資訊必讀同一 API／canonical source。
- 對每個狀態欄位確認語意（live、day-level、交易日、timezone、staleness）。
- 檢查入口與排序，確保新內容可被讀者找到；自動載入必有界，footer 可達。
- SSR render path 不得依賴不穩定時間／隨機值；map lookup 要有可理解 fallback。
- 法規／風險文字、mobile keyboard navigation、focus、contrast 與 reduced motion 都納入
  acceptance。

## 3. Verify source

從 active frontend 的 `package.json` 讀可用 scripts，執行與變更相稱的 lint、typecheck、
tests、build。不要假設 package manager 或 script 名稱。

用 in-app Browser／Chrome 對目標 route 做至少 mobile、desktop、wide viewport：

- screenshot 與 layout hierarchy
- keyboard/focus 與主要 interaction
- empty/loading/error/unknown-state
- console error／hydration warning
- DOM 或文字 readback 對照 API expected value
- base/alternate route parity（若存在）

source gate 完成後，把 exact changed paths、測試輸出與 screenshots handoff 給該 frontend
的 canonical repository writer／integrator；本 skill 不自建版本控制流程。

## 4. Safe deploy handoff

只有任務已授權 production deploy 且 source gate 通過時，才交給 active frontend wrapper：

```bash
test -x "$FRONTEND_PATH/scripts/deploy-zeabur-safe.sh"
(cd "$FRONTEND_PATH" && ./scripts/deploy-zeabur-safe.sh)
```

wrapper 必須自行解析 provider target、回傳 deployment identity、等待 terminal running
status，並驗 production APIs。缺任何條件就停止，不改走 provider shortcut。

## 5. Production readback

部署後重新讀 `config/project_targets.json`，確認 target 沒在部署期間漂移，再保存：

1. source identity 與 resolved frontend/service names；
2. deployment receipt 與 terminal provider status；
3. wrapper API acknowledgement；
4. `$LIVE_URL` 上本次 route 的 screenshot、DOM/文字值、interaction 與 console；
5. alternate route parity（若 active tree 有該 route）。

只有 build 綠或 upload 成功時回報 `contained`。source tests、deployment receipt 與 live
feature readback 全過，才可回報 `root_cause_fixed_and_verified`。
