# 2026-07-27 — First-paint 指標語意分岔、Zeabur env 全量同步與 upload secret boundary

## 證據化症狀

Issue #8 第一輪 production deployment 先後暴露四個不同層級問題：
deployment monitor 把上一個／瞬時狀態判成新部署失敗；strict navigation contract
拒絕合法 `#feed` 而令原版首頁 500；`zeabur variable env` 全量同步刪除兩個
analytics 變數，使有效事件回 503；最後原版 raw HTML 顯示 `115+`，hydration 後卻被
`/api/research/stats` 以 knowledge count 誤標的 `3,198+` 覆寫。初版 Keychain
補救又把注入 secret 的 `.env.production` 放在 source staging tree，雖未進 Git
仍可能進 build context。

## 根因與底層重構

這不是單一前端 bug，而是 deployment identity、navigation allowlist、environment
ownership、metric semantics 與 secret boundary 五個契約缺口。監控器現只接受
不同 deployment ID 的 durable terminal state；fragment 採 strict regex；
analytics HMAC 材料固定從 macOS Keychain 取得，缺失即拒絕部署；原版／v3 與 stats
API 共用 `getResearchSummary().n_experiments`，API 失敗回 503 而非假 0；
variable sync 使用 upload tree 外的 temp env，copy 與 `.zeaburignore` 均排除所有
`.env*`。

## 回歸與 live read-back

Navigation／first-paint／analytics／deploy tests、typecheck 與 Next production
build（88 routes）通過。Deployment `6a6736c7225290ec74322de0` 為 RUNNING；
container 回讀 `.env.production=false`，但兩個 analytics vars 均存在。原版／v3
raw HTML 與 desktop/mobile hydrated DOM 同為實驗數 115，navigation 實際成功。
Supabase 回讀 browser 事件 impression 4、click 6、depth 4、qualified 1，15 列皆
15 個 distinct keys、retention drift 0；live canary 重播回 `duplicate=true`。

## 狀態

GitHub #8／T20 為 `root_cause_fixed_and_verified`。舊文章 view-count 資料面仍保留
供既有 UI 讀取，但不寫入新的 `volpred_analytics` 事件表；其正式 retirement 由
既有 legacy-retirement tickets 處理，不在 #8 內冒充完成。
