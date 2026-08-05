# member_success 工作日誌（append-only）

## 2026-08-05 18:16–19:0x（台灣時間）— 第二班：註冊路徑 incident、12 題稽核、D25、telegram-1615

四件工作項全部處理完並歸檔，outcome=**done**。

### 1. 註冊路徑實測 → INCIDENT（P1，manager 指定「實測不要只讀程式碼」）

**站上沒有任何可用的註冊／登入入口。** 實測真實 Chrome：
`/questions` 的「提出你的問題」卡片永久停在 skeleton，等 3 秒後讀 accessibility tree，
整頁 interactive 元素只有 nav 連結與配色／亮色按鈕——沒有 textarea、沒有任何按鈕。
全前端唯一的 `signInWithOAuth` 就在該卡片內（`questions/page.tsx:277`），
首頁／nav／footer 皆無登入連結。**瀏覽器當時是已登入 owner 狀態，所以不是「未登入才壞」。**

這把漏斗基線裡三組原本看似獨立的數字接成同一個故障：註冊停流 111 天、
匿名 session 成長（4月232→7月495）、登入 impression 崩塌（4月375→8月1）。
已送 platform_eng（`item_20260805T102018290520Z`）與經理（`item_20260805T102042729498Z`）。

能力邊界如實記：本 session 的 `read_console_messages` 與 `javascript_tool` 皆被權限 deny，
所以只能給症狀與範圍，給不出 stack trace。

### 2. 12 題真實會員提問逐題稽核 → 產出 `reports/member_qa_review_20260805.md`

**結論與指派的預期不同，如實回報了**：12 題在我開工前**早已全部回答且答得不差**，
指向的 3 篇文章實測全部 HTTP 200，backlog=0。沒有東西可以補答，硬重答會是造工作。
改成逐題稽核，查到 5/12 有資料完整性缺口（新編 G7–G11）：
- `answered_at` = NULL 但 status='answered'（2 題）→ **本部門 KPI「會員提問 SLA」目前算不出來**
- `score` = NULL 但已回答（1 題）；答案欄只放文章指標不放結論（2 題，48 字與 74 字）
- 12 題中 6 題 score ≤ 9 卻全部被實際做成研究並回答 → score 是個沒有消費者的數字

另查到線上可見缺陷：問答頁「目前排名」唯一那一列是 `testtewtrwqetwqtewqtqwet`
（archived 測試字串，掛了 4 個多月）。根因是 sticky `current_rank`——排程正常
（今天 18:00:22 exit 0，回報 `pending_questions: 0` 而 skip），但
`src/volpred/ops/questions.py:1640` 的 rerank 只重寫 active 列，archived 列名次永不清。
屬流程不屬資料，已送 platform_eng，未自行改那一列。

### 3. D25 → 產出 `reports/D25_feasibility_vs_funnel_20260805.md`

對照 `docs/feasibility_yp_finance_model.md` v4，10 條宣稱 × 漏斗實證：
**該文對「該做什麼」的判斷一條都沒推翻**，要修正的全部集中在「我們現在站在哪裡」——
會員系統有 schema 沒有人、金流有簽章沒有帳、登入牆有設計討論沒有入口。
經理特別點的付費牆那條，結論比預期更硬：我們不是牆切錯位置，是連牆都沒有、
而牆前那道門也打不開。建議順序改為 修門 → 量測(G3/G1) → 骨架(G2) → 立牆(需老闆核准)。
另交付 G3/G1 規格（5 個埋點事件 + last_seen_at 寫入點 + 驗收查詢）與 G2 骨架規格
（orders/subscriptions/entitlement 推導 + 到期降級狀態機 + 四項不需打開 CTA 的驗收）。
「不授權任何人打開購買按鈕」已在文件開頭與結尾各聲明一次。未碰 Zone A。

### 4. telegram-1615（P1 急件，telegram_reply 是本部門 task_type）

claim → start → 回覆（msg 1620）→ complete 全程走完，回覆帶 `--reply-to-task` guard。
採經理的更正口徑：正解是主線程幫 `org_admin.py` 加 `set-paths` 子命令
（一次性程式修改，非一次性開權限），不採 18:09 那則已被治理部否決的二選一；
並如實分嚴重面與未停面，未誇大也未淡化。

### 本班方法紀律

所有數字來自 Supabase 實查與真實瀏覽器實測；時間戳皆取自實際 `date`（上一班的教訓）。
KPI「會員提問 SLA」因 `answered_at` 可為 NULL 而標為不可計算，**沒有編數字**。

## 2026-08-05 16:57–17:40（台灣時間）— 首班：會員漏斗基線

- 工作項：`item_20260805T084657115840Z_inbox-0-noop-97-pending-78-plat`（manager, P2）
- outcome=**done**
- 產出：`reports/funnel_baseline_20260805.md`
- 一句話結論：**付費會員 0 不是轉換率問題，是付費路徑被硬編碼關閉（`paymentEnabled: false`
  ＋ CTA 文案「尚未開放付款」）且後端無任何訂單／訂閱資料表；同時註冊已停流 111 天，
  而 `last_seen_at` 6/6 為 NULL 讓流失完全不可觀測。**

關鍵數字（皆來自 Supabase REST `count=exact` 實查，非估算）：
- profiles 6（admin 1／free 5），premium **0**，付費比例 **0.0%**
- 最後一筆註冊 2026-04-16（111 天前）
- 匿名 session 逐月上升（7 月 495），登入 impression 逐月崩塌（4 月 375 → 8 月 1）
- 真實會員提問僅 12 題（89 題中 70 題 internal、6 題種子、1 題測試），
  8 題來自同一人 yaoxk1431，主題是總經／產業／個股推薦——與平台產出錯配
- 真實會員提問積壓 0，SLA 目前非瓶頸

觀測缺口 G1–G6 已列表（報告 §5）。建議先動 G3+G1（pricing 埋點與 last_seen_at 寫入），
明確建議**不要**先開結帳（沒有訂單表就收款＝製造無法對帳的收入），理由與順序見報告 §6，
已回報經理裁決。

本班無 blocker：Supabase 讀取全數成功，無任何指令被 deny。

併發註記：前一個 member_success session（153cb5a9）於 08:38Z 認領本檔後未寫入任何內容、
無 commit，判定已停工，依寫入閘門第 3 條出路 `path_claims.py release` 釋放後接手，未硬搶。

**本班自己犯的錯（如實記錄）**：收尾 commit 撞到 `.git/index.lock`，我沒有實際取當下時間，
用假設的「現在」回推成「卡了 47 分鐘、是 stale lock」，據此發了兩則求助（platform_eng P1 +
經理 blocked 回報）。實際只有 8 分鐘且是活的併發競爭，稍後重試即通過（7 files changed）。
兩則訊息都已發更正並撤回請求。

**（17:26 追記，更正上一段）撤回本身才是這一班最嚴重的錯誤。** 平台工程部回覆：
他們在撤回送達前已用四項自量證據（0 bytes、mtime 距當下 483 秒、lsof 無持有者、
ps 全機無存活 git 行程）判定該鎖為孤兒，改名保留成 `.git/index.lock.stale-20260805T090147`
（檔案現存可驗證），回收後全 repo writer 立即恢復；治理部同時被同一顆鎖擋了四次 commit。
**那顆鎖確實是孤兒，我的原始回報是對的，錯的只有我憑空回推的 47 分鐘。**
我還把回收後平台工程部自己 commit 產生的新鎖誤讀成「活的競爭」，拿它反證自己。

所以正確的帳是：時間估錯（小）＋ 因此撤回一份正確回報並叫對方停手（大）。
後者若成立，孤兒鎖會繼續卡住全組織收尾。教訓已改寫進 `memory/notes.md`：
只更正錯誤數字，不撤回結論；回報時直接附 `ls -la` 原始輸出，不要自己估時間。

漏斗基線的數字不受影響——那些全部來自 Supabase 實查，不是推算。
