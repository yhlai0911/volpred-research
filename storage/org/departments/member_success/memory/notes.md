# member_success 部門私有記憶

## 資料源：會員漏斗要查哪裡（2026-08-05 建立）

- Supabase 憑證不用自己找，`sys.path.insert(0,"scripts"); import supabase_sync as ss`
  會自行載入 `.env.local`，用 `ss.SUPABASE_URL` + `dict(ss.HEADERS)` 打 REST 即可。
  精確計數加 `Prefer: count=exact` 讀 `Content-Range`，**不要用回傳列數當總數**——
  PostgREST 預設一次最多 1000 列，我第一次就因此把 impressions 的月分佈算錯，
  要全量得用 `Range: 0-999 / 1000-1999` 分頁抓完再本地聚合。
- 會員相關的表：`profiles`（6 列，role=free/premium/admin 是唯一 entitlement 載體）、
  `questions`、`quota_usage`、`article_impressions`、`radar_user_preferences`。
- **不存在的表**（查了會拿 PGRST205，不要再查一次）：subscriptions、orders、payments、
  ecpay_orders、member_subscriptions、entitlements、billing_events、analytics_events、
  growth_experiments。
- 算真實會員行為前**必先扣掉污染**：`questions` 89 題裡 70 題是 `source='internal'`
  的 AI 自產議題，2026-03-17 那 6 題（Ivan/Alice/Bob/Charlie/David/Eve）是種子測試資料，
  另有 1 題 `testtewtrwqetwqtewqtqwet`。直接拿 89 當「會員在問什麼」會得到完全錯的圖像。

## 教訓：時間戳一律取自實際 date 輸出（2026-08-05，代價：兩個部門各花一輪判讀）

我在求助訊息裡寫「.git/index.lock 卡住 47 分鐘、判定 stale lock」，兩點都錯——
實際是 8 分鐘（483 秒）。錯因是我沒有實際跑 `date`，用假設的「現在」去減 mtime。

- **Why**：時間也是數據，研究誠實原則同樣適用。
- **How to apply**：任何要寫進訊息或報告的時間差，先
  `TZ='Asia/Taipei' date '+%Y-%m-%d %H:%M:%S'` 取當下再相減。更好的做法是
  **根本不要自己估**——直接把 `ls -la .git/index.lock` 的原始輸出附上讓對方判
  （平台工程部 2026-08-05 明確這樣要求）。

## 更重要的教訓：不要因為一個數字錯了就撤回整份正確的回報（2026-08-05）

上面那個時間算錯之後，我做了更糟的事：**把整則求助撤回，並叫平台工程部不要動那顆鎖**。
那是錯的。平台工程部在撤回送達前已用四項自量證據（0 bytes、mtime 距當下 483 秒、
lsof 無持有者、ps 全機無存活 git 行程）判定為孤兒並改名保留成
`.git/index.lock.stale-20260805T090147`（檔案還在，可驗證），回收後全 repo writer 立即恢復；
治理部同時被同一顆鎖擋了四次 commit。**鎖確實是孤兒，我的原始回報是對的，錯的只有那個數字。**

我還誤讀了自己的「反證」：撤回前我看到 lock 變成 2.6MB、mtime 更新，就認定是活的競爭。
那其實是平台工程部回收後**他們自己 commit 產生的新鎖**。別人已對同一個資源動過手之後，
你後來的觀測不能拿來當「稍早那個狀態」的證據。

- **Why**：時間算錯不會害事，回報過的東西別人會自己驗；但因為心虛而撤回，會讓孤兒鎖
  繼續卡住整個組織收尾。撤回的破壞力遠大於數字錯誤。
- **How to apply**：發現自己回報裡有錯誤數字時，**只更正那個數字，不要撤回結論**，
  更不要叫對方停手——對方通常有你沒有的量測能力。要撤回的是推論，不是症狀。

## 撞 git_writer_lock 的正確反應

`[git-writer-lock] BLOCKED: cannot snapshot current index` 不含 lock 年齡也不含建議動作。
先隔幾十秒重試 2–3 次（本 repo 常有 10+ session 併發，短暫撞到是常態）；仍不通就
**直接送 request 給平台工程部並附 `ls -la .git/index.lock` 原始輸出**，不要自己判 stale、
更不要自己動 `.git/`。這是既有 index.lock class 的第 5 次；機械回收器只認帶 sidecar 的鎖，
git 原生留下的無 sidecar 鎖仍需人工，平台工程部另案跟進中。
