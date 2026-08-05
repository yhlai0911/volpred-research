# D25 交付：可行性宣稱 × 漏斗實證對照 ＋ G3/G1/G2 規格

- 部門：member_success
- 指派：manager `item_20260805T101945726190Z_d25-6-g3-g1-g3-g1-g2-entitlement`（P1, decision）
- 產出時間：2026-08-05 18:30–19:0x（台灣時間）
- 對照標的：`docs/feasibility_yp_finance_model.md`（v4）
- 實證來源：`reports/funnel_baseline_20260805.md`、`reports/member_qa_review_20260805.md`

---

# 第一部分：可行性宣稱 × 漏斗實證對照表

判定四級：**✅支持**（實證與宣稱一致）／**⚠️修正**（方向對但前提要改）／
**❌推翻**（實證與宣稱矛盾）／**🔺前置**（宣稱本身沒錯，但有更上游的東西擋著，順序要改）

| # | 可行性評估的宣稱 | 出處 | 漏斗實證 | 判定 |
|---|---|---|---|---|
| 1 | 「YP 付費牆切在**市場涵蓋**而非**功能存在**」，我們應比照 | §1(a), §4「切範圍不切功能」 | `getPricingPlans()` 三個方案全部 `paymentEnabled:false`，Radar Plus 的 CTA 文案是「尚未開放付款」（線上實測 /pricing 三段字串全部命中）。**我們現在沒有牆**——不是切錯位置，是還沒有牆 | ⚠️修正 |
| 2 | 定價與 YP 完全相同（299／599），「定價不是問題」 | §1 定價表, §2 | 線上 /pricing 實測：NT$299、NT$599 字串命中。`src/volpred/payments/plans.py` 亦為 299/599。**宣稱正確** | ✅支持 |
| 3 | 「金流已建好（ECPay adapter、19 測試、簽章釘官方向量），關著是老闆 2026-07-04 的指示」 | §7.3 | **只有一半是真的**。簽章 adapter 確實存在且有測試向量，但：(a) `src/volpred/payments/` **production caller 為零**，全 repo 只有 `tests/test_payments_ecpay.py` 引用；(b) Supabase **沒有** orders／subscriptions／payments／billing_events／entitlements 任何一張表（逐一查，全部 PGRST205）；(c) entitlement 唯一載體是 `profiles.role` 這個 TEXT 欄位，無到期日、無方案 id、無金流單號。**「關著」≠「開了就能收錢」**，中間缺整個落地與對帳層 | ⚠️修正 |
| 4 | 「會員系統已有」，故 B1 投組輸入層只需做 ticker 驗證與取價快取 | §6 B1 | 註冊會員 6 人（含 admin 1、老闆自己 1），**最後一筆註冊 2026-04-16，停流 111 天**；6 人中 3 人註冊後從未在站上讀過任何文章。會員系統在 schema 意義上存在，在**運作意義上等於沒有** | ⚠️修正 |
| 5 | YP 的登入牆是設計過的轉換裝置（半透明遮罩、「免費使用 30 種工具」、6 個好處、「先逛逛」逃生口），我們該學 | §4.5 登入牆 | **我們沒有登入牆可以設計——因為沒有登入入口。** 實測真實 Chrome：/questions 的「提出你的問題」卡片永久停在 skeleton，整頁沒有 textarea 也沒有任何按鈕；全前端唯一的 `signInWithOAuth` 就在該卡片內（questions/page.tsx:277），首頁／nav／footer 皆無登入連結。已登入 owner 狀態下同樣壞 | ❌推翻／🔺前置 |
| 6 | A0（風險預報改人話，2–3 天）是「最便宜的驗證」，「做完就能看出有沒有差別」 | §4.5, §6 | **目前無法驗證**。`profiles.last_seen_at` 6/6 全 NULL（從未寫入），pricing 頁與註冊 CTA 零埋點，註冊無來源歸因。A0 改完之後，我們**沒有任何指標可以判斷它有沒有用** | 🔺前置（需 G3/G1） |
| 7 | 「如果連這個都做了還是沒人回訪，那六個新工具也救不了」 | §4.5 末 | 同上：**「回訪」目前不可觀測**。唯一的代理指標是 `article_impressions.user_id`，而登入 impression 已從 4 月 375 崩到 8 月 1，且歷來只有 3 個 user_id 有過登入閱讀 | 🔺前置 |
| 8 | 「沒有任何工具接受讀者的持倉」，這是產品類別差異 | §2 | 本部門無反證，且與會員行為一致：12 題真實提問沒有任何一題問「我的持倉如何」，全是總經／產業／選股與長期報酬框架 | ✅支持 |
| 9 | 六個工具中 T1–T5 是「把已有研究換一層皮」，T6 需先做實驗 | §4 | 非本部門轄區（研究底子屬研究部），不判定 | — |
| 10 | 「文章 → 個人化工具 → 訂閱」這條線 B0–B5 約 5–7 週會第一次真的存在 | §6 | 這條線的**入口**（註冊）目前是斷的，**出口**（結帳）沒有落地層。B0–B5 做完會得到一條兩端都不通的中段 | 🔺前置 |

## 對照表讀出來的三句話

1. **可行性評估對「該做什麼」的判斷，我沒有一條要推翻。** 人話化、切範圍不切功能、
   六個工具走 YP 算不出來的風險面——這些方向漏斗數據都不反對。

2. **要修正的全部集中在「我們現在站在哪裡」。** 評估文件反覆使用「已有」「已建好」「只要」，
   而實證是：會員系統有 schema 沒有人、金流有簽章沒有帳、登入牆有設計討論沒有入口。
   這不是評估寫錯，是它成文時沒有人量過漏斗——那正是本部門今天補上的東西。

3. **最尖銳的一條是經理特別點的第 1 條，但結論比預期更硬**：
   YP 的洞見是「牆該切在市場涵蓋而非功能存在」。我們的問題不在牆切在哪裡——
   **我們連牆都沒有，而且牆前面那道門也打不開。** 排序因此必須改：
   `修門（incident） → 量測（G3/G1） → 訂閱骨架（G2） → 立牆（CTA，需老闆核准）`。
   A0 可以與「修門」並行，因為它不動引擎、也不依賴任何權限。

---

# 第二部分：G3 + G1 可交付規格

> 定位：**本部門出規格，不出實作。** 落點在 `frontend-v2-fix/` 與 `supabase/`，
> 屬 platform_eng 與 Codex Zone A。以下每一項都寫了驗收查詢，讓實作方自證、
> 也讓本部門能獨立回讀，不必相信摘要。

## G1：`profiles.last_seen_at` 寫入

**現況**：欄位存在，6/6 為 NULL，從未被任何程式寫過。導致 MAU、沉睡、流失全部不可計算。

**規格**

- 寫入點：任何**已認證** request 命中站上頁面時，以該 user 的 id 更新 `last_seen_at = now()`。
  建議實作在既有的 server-side session 解析處，一次寫入涵蓋全站，不要逐頁埋。
- 節流：同一 user 60 分鐘內最多寫一次（避免每次 pageview 都打 DB）。
- 不得阻塞渲染：寫入失敗只記 log，不可讓頁面因此報錯。
- 匿名者不寫。

**驗收查詢**（本部門會實際跑，不看回報）

```
GET /rest/v1/profiles?select=id,last_seen_at&order=last_seen_at.desc
```
通過條件：至少一列 `last_seen_at` 非 NULL，且該時間在驗收當下 24 小時內。

## G3：pricing／註冊漏斗埋點

**現況**：pricing 頁零埋點；註冊無來源歸因；`article_impressions` 有 session_id 但無
landing／exit 標記。因此「看到價目表 → 註冊 → 付費」每一段都算不出來。

**事件清單**（最小集合，五個事件，不多不少）

| 事件名 | 觸發時機 | 必要欄位 |
|---|---|---|
| `pricing_viewed` | /pricing 頁載入 | session_id, user_id(nullable), referrer, ts |
| `plan_cta_clicked` | 任一方案 CTA 被點 | session_id, user_id(nullable), plan_id, cta_label, ts |
| `signup_prompt_shown` | 登入／註冊入口實際 render 出來 | session_id, surface（哪一頁／哪個元件）, ts |
| `signup_started` | 使用者點下登入按鈕、跳轉 OAuth 前 | session_id, surface, ts |
| `signup_completed` | OAuth 回來且 profile 建立成功 | session_id, user_id, surface, ts |

**設計要點（三條，都是為了避免重蹈現有覆轍）**

1. `signup_prompt_shown` **不是多餘的**。今天這個 incident 的症狀正是「入口從未 render」，
   而我們是靠人工開瀏覽器才發現。有了這個事件，同樣的故障會在數據上自己現形：
   `signup_prompt_shown` 連續數日為 0 = 入口壞了。**這一條的價值高於其他四條。**
2. 匿名 `session_id` 必須與 `article_impressions.session_id` 同源，否則
   「讀文章 → 看價目表 → 註冊」串不起來。
3. 來源歸因（G4）順帶解決：`pricing_viewed.referrer` 與 `signup_completed` 的
   session 串接即可回答「這個註冊者從哪篇文章來的」，不需要另建 utm 欄位。

**驗收查詢**

```sql
-- 漏斗一次看完（實作方自行決定落在哪張表，但必須可用單一查詢得出）
select event, count(*), count(distinct session_id)
from <events_table>
where ts >= now() - interval '7 days'
  and event in ('pricing_viewed','plan_cta_clicked',
                'signup_prompt_shown','signup_started','signup_completed')
group by event;
```
通過條件：本部門實際開一次瀏覽器走完「首頁 → 文章 → /pricing → 點 CTA → 看到登入入口」，
上述查詢應出現對應事件且 session_id 一致。

**依賴**：`signup_prompt_shown` / `signup_started` / `signup_completed` 三個事件
在註冊入口修好之前**埋了也不會有資料**。所以 G3 與 incident 修復要同一批驗收，
不可分開宣告完成。

---

# 第三部分：G2 訂閱骨架規格

> **這份規格不授權任何人打開購買按鈕。**
> `paymentEnabled` 維持 `false`、pricing CTA 維持現狀，任何實作不得變更之。
> 打開 CTA 是獨立決策，需老闆核准（金流＝對外開通新通路）。
> 本規格的目的相反：**確保在那個決策到來之前，收錢這件事已經有地方落帳。**

## 為什麼順序不能倒過來

目前若直接接上 ECPay，會發生：錢進了綠界、平台沒有訂單記錄、開通只能手動改
`profiles.role`、到期沒有任何機制降級、退款與對帳無從查起。
**先有骨架再開牆，不是保守，是避免製造無法對帳的收入。**

## 三個實體

### 1. `orders`（一次性事實，append-only）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | uuid pk | |
| user_id | uuid fk profiles | |
| plan_id | text | 對照 `payments/plans.py` 的 plan_id，非自由文字 |
| amount_twd | int | 下單當下的金額，**不可事後回頭改** |
| provider | text | 'ecpay' |
| provider_trade_no | text unique | 綠界交易編號，冪等鍵 |
| status | text | pending / paid / failed / refunded |
| raw_callback | jsonb | 原始回調全文，供對帳與爭議查證 |
| created_at / updated_at | timestamptz | |

要點：`provider_trade_no` 唯一約束是**冪等的機械保證**——綠界重送回調不得產生第二筆訂單。

### 2. `subscriptions`（週期狀態）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | uuid pk | |
| user_id | uuid fk profiles | |
| plan_id | text | |
| status | text | active / past_due / canceled / expired |
| current_period_start / current_period_end | timestamptz | **到期的唯一真相** |
| cancel_at_period_end | bool | 使用者已取消但尚未到期 |
| provider_subscription_id | text | ECPay 定期定額授權編號 |
| created_at / updated_at | timestamptz | |

### 3. entitlement：**不新增表，改為由 subscriptions 推導**

現況 `profiles.role` 同時扮演「身分」與「權利」，且無到期概念。規格：

- `profiles.role` 保留，但**降級為身分**（free / admin），不再表達付費權利
- 付費權利一律由「該 user 是否存在 `status='active'` 且 `current_period_end > now()`
  的 subscription」推導
- 提供單一讀取點（view 或 function）`current_entitlement(user_id)` 回傳
  `{plan_id, active, current_period_end}`，前後端都只讀它，不得各自拼裝

## 到期降級狀態機

```
（無訂閱）
   │ 付款成功（orders.status=paid）
   ▼
 active ──── current_period_end 到期且續扣成功 ───▶ active（展期）
   │                                                  ▲
   │ 續扣失敗                                          │ 補款成功
   ▼                                                  │
 past_due ── 寬限期 N 天內未補款 ──▶ expired ──────────┘
   │
   │ 使用者取消（cancel_at_period_end=true）
   ▼
 canceled（權利保留至 current_period_end，之後視同 expired）
```

三條硬規則：

1. **降級由到期時間推導，不由排程「執行」。** `current_entitlement()` 每次讀取都比對
   `current_period_end > now()`，所以就算降級排程掛掉，權利也不會多給。
   （這正是本平台既有的教訓：不要讓權利正確性依賴一個會 silent fail 的 cron。）
2. **寬限期 N 天要寫在設定裡，不寫死在程式**，且預設值需老闆確認後才生效。
3. **降級不刪資料。** expired 使用者的收藏、提問、追蹤全部保留，只是讀不到付費內容——
   否則退款或重新訂閱會製造資料遺失事故。

## 驗收（不需要打開 CTA 也能全部驗完）

1. 用測試資料手動插一筆 `orders(status=paid)` + `subscriptions(active, period_end=明天)`
   → `current_entitlement()` 回 active
2. 把 `current_period_end` 改成昨天，**不跑任何排程** → `current_entitlement()` 立刻回 inactive
3. 同一個 `provider_trade_no` 插第二次 → 唯一約束擋下
4. 全程 `paymentEnabled` 維持 false、pricing 頁 CTA 文案不變（線上回讀確認）

## 明確不做

- 不碰 `src/volpred/payments/`（Zone A，D14 定案）
- 不碰 `supabase/migrations/`（Zone A）——本文件是規格，migration 由 Zone A 撰寫
- 不改 `getPricingPlans()` 的 `paymentEnabled`
- 不接任何 ECPay 網路呼叫

---

# 附：本份交付對 D25 三項要求的自查

| D25 要求 | 狀態 |
|---|---|
| 1. 可行性宣稱 × 漏斗實證對照表（含經理指定的付費牆那條） | ✅ 第一部分，10 條，付費牆為第 1 條 |
| 2. G3/G1 規格（埋點事件清單、last_seen_at 寫入點、驗收查詢） | ✅ 第二部分，5 事件 + 寫入點 + 兩組驗收查詢 |
| 3. G2 骨架規格（三者欄位與到期降級狀態機）＋ 明寫不授權打開購買按鈕 | ✅ 第三部分，開頭與「明確不做」各聲明一次 |
| 不碰 `src/volpred/payments/` 與 `supabase/migrations/` | ✅ 本班未讀寫該兩處以外的任何 Zone A 檔案，未提交任何實作 |
