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
實際只有 8 分鐘，而且是活的併發競爭，稍後重試就通過了。錯因是我沒有實際跑 `date`，
用假設的「現在」去減 mtime。

- **Why**：時間也是數據，研究誠實原則同樣適用。憑空回推的時間會直接改變故障判定
  （8 分鐘＝正常競爭，47 分鐘＝stale lock 要清），而清 lock 是會污染別人 commit 的動作。
- **How to apply**：任何要寫進訊息、報告或 journal 的時間差，先
  `TZ='Asia/Taipei' date '+%Y-%m-%d %H:%M:%S'` 取當下，再相減。
  尤其是**對外求助前**——錯誤的診斷會讓別的部門去修一個不存在的故障。

## 教訓：撞 git_writer_lock 先重試，不要當場診斷成故障

`[git-writer-lock] BLOCKED: cannot snapshot current index` 這句話**不含 lock 年齡也不含
建議動作**，很容易被誤讀成故障。正確反應是隔幾十秒重試 2–3 次；併發 session 多的時段
（本 repo 常有 10+ session 同時持 path claim）撞到是常態。真的要判 stale，得先看
`ls -la .git/index.lock` 的 size 與 mtime，並用實際 date 算年齡。
