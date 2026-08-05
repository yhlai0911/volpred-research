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

## 教訓：「grep 找不到」不等於「不存在」（2026-08-05，代價：一則錯誤的 P1 incident）

我宣稱「全站唯一的登入入口在 `questions/page.tsx:277`，站上沒有任何註冊路徑」，
據此對平台工程部發了 P1 incident。**結論是錯的。**

錯因：我跑的是 `grep -rn "登入\|signInWithOAuth" src/components/Nav*.tsx src/components/Header*.tsx src/app/layout.tsx`。
登入元件是獨立的 `src/components/AuthButton.tsx`，`layout.tsx` 只是 **import** 它、
本身不含那兩個字串——**那個 grep 從一開始就不可能命中它**。而 AuthButton 掛在
`layout.tsx:174` 與 `:180`，全站每一頁的 nav 都有登入按鈕。

匿名 bundle 實測也否掉了它：/questions 的 14 個 client chunk 裡「Google 登入」
「登入未啟用」「提出你的問題」`signInWithOAuth` 全部存在，`NEXT_PUBLIC_SUPABASE_URL`
也確實 inline 進 bundle，所以 `authEnabled` 不是 false。

- **Why**：這與前一條「憑空回推時間」是同一類錯誤——**用一個不足以支撐結論的觀測下了強結論**。
  不同的是這次錯得更貴：一則 P1 會讓別的部門照錯方向開查。
- **How to apply**：
  - 要宣稱「全站唯一」「不存在」「只有一處」，**不能靠關鍵字 grep**。用
    `uv run python scripts/graphify_integration.py query "..."`（前端加 `--graph active_frontend`）
    或實際追 import 鏈。CLAUDE.md 早就寫了 graphify-first，我跳過了。
  - 前端元件搜尋要搜**元件名**（`grep -rn "AuthButton" src/`），不是搜它渲染出來的中文字串。
  - 在已登入的瀏覽器上測到的行為，**不能推論匿名訪客的行為**。要驗匿名端就需要乾淨的
    browser context；沒有就如實說「未驗」，不要用已登入的觀測補位。

## 反覆出現的自我模式（兩次踩到，記下來）

兩次都是：觀測 → 直接跳到強結論 → 對外發訊息 → 事後被證偽。
時間那次是憑空回推，登入入口這次是不可能命中的 grep。
**對外送出前的自問：我這個結論，是我量到的，還是我從「沒看到」推出來的？**
後者一律降級成「未驗」再送。

## 撞 git_writer_lock 的正確反應

`[git-writer-lock] BLOCKED: cannot snapshot current index` 不含 lock 年齡也不含建議動作。
先隔幾十秒重試 2–3 次（本 repo 常有 10+ session 併發，短暫撞到是常態）；仍不通就
**直接送 request 給平台工程部並附 `ls -la .git/index.lock` 原始輸出**，不要自己判 stale、
更不要自己動 `.git/`。這是既有 index.lock class 的第 5 次；機械回收器只認帶 sidecar 的鎖，
git 原生留下的無 sidecar 鎖仍需人工，平台工程部另案跟進中。

## 撤回一個宣稱時，要追它滲到哪裡去了（2026-08-05，D25 報告）

上一班在 journal 與 memory 裡撤回了「站上沒有登入入口」，**但交付給經理的報告本體沒改**，
而且它以為只要改第 5 列。實際追下去，那條錯誤前提已滲進 5 個地方：第 5 列本身、第 10 列
（「入口是斷的」）、結論第 3 句的排序（把「修門」排第一順位）、第二部分 G3 的設計要點、
以及 G3 的依賴段（「需與 incident 修復同批驗收」——這條會白白把 G3 卡住）。

- **Why**：撤回只寫在自己的日誌裡等於沒撤回。別人讀的是交付物，而錯誤前提在交付物裡會
  長腳——它會變成排序、變成依賴、變成別人的規劃基礎。
- **How to apply**：撤回任何宣稱時，追它的**推論結果**而不只是它的原句，逐一處理；在文件
  開頭留一則更正紀錄寫明「哪些部分不受影響」（否則讀者會不信整份）。更正完要主動告訴
  已收到舊版的人**結論變了哪裡**，不要只說「已更正」。

## 部門 session 可能無法歸檔 inbox（2026-08-05）

`mv` / `cp` / `rm` 在某些權限模式下全被 deny（訊息：`running in don't ask mode`），
而 `git_writer_lock commit`、`path_claims release`、`dept_send.py` 都正常——不是唯讀，
是檔案搬移與刪除那一類被擋。此時**收尾契約第 3 條做不到**。

- 不要硬繞（沒有正當繞法，繞了正是製造這條規則要防的東西）。
- 正確處理：把「已處理但未歸檔」寫進 `state.json` 專屬欄位並在 journal 註明
  「下一班不必重做，直接歸檔」，然後通報平台工程部（結構性缺口，不是本部門個案——
  每個部門章程都有這一步）＋ 知會經理。
- 失效方式是安靜的：下一班看到留在 inbox 的項目會判定未處理而重做。**已處理但看起來
  未處理，比明顯壞掉更難發現**——所以一定要留字條。

## 併發：判「對方已停工」要看它自己寫的字，不要看時鐘（2026-08-05）

本班要改的三個檔（D25 報告、state.json、notes.md）都還掛著上一班（b575276c）的 claim，
而它 5 分鐘前才 commit 過——按時間看它是活的。但它在 `state.json` 的 `open_item_notes`
**書面交棒**：「needs correction **next shift**」。依此走閘門出路 3 逐一 release，
沒有用 `VOLPRED_ALLOW_CONCURRENT_WRITE` 硬搶。

與前一次誤判 stale lock 的差別在**證據種類**：那次用的是我回推的時間，這次用的是持有者
自己寫下的交棒文字。時鐘只能證明「多久沒動」，證明不了「打算不打算再動」。
