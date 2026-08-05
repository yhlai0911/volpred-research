# 會員漏斗基線 — 2026-08-05

- 部門：member_success
- 資料讀取時間：2026-08-05 17:00–17:20（台灣時間）
- 資料來源：Supabase REST（service role，`scripts/supabase_sync.py` 載入 `.env.local` 憑證），
  逐表 `Prefer: count=exact` 精確計數；`article_impressions` 以 Range 分頁抓滿 1968 列後在本地聚合
- 一句話結論：**漏斗末端不是轉換率低，是根本沒有末端。付費路徑在前端被硬編碼關閉，
  後端沒有任何訂單／訂閱資料表，所以 0 付費會員是結構結果而非行銷結果。**

---

## 1. 會員與付費比例

| 指標 | 數字 | 來源 |
|---|---|---|
| 註冊會員總數 | **6** | `public.profiles` count=exact |
| 其中 admin（老闆本人） | 1 | `role='admin'`, yihao.lai@gmail.com |
| 實際外部註冊者 | **5** | 扣除 admin |
| 付費會員（`role='premium'`） | **0** | profiles 全表 role 僅 admin×1 / free×5 |
| 付費比例 | **0.0%** | 0 / 6 |

profiles 全表（僅 6 列，逐列列出，無抽樣）：

| created_at | role | status | 帳號 |
|---|---|---|---|
| 2026-03-17 | admin | active | yihao.lai@gmail.com |
| 2026-03-17 | free | active | yhlai@mail.dyu.edu.tw |
| 2026-03-17 | free | active | ideahub.everything@gmail.com |
| 2026-03-31 | free | active | yaoxk1431@gmail.com |
| 2026-04-02 | free | active | huanpea@gmail.com |
| 2026-04-16 | free | active | sieyiting23@gmail.com |

**最後一筆註冊是 2026-04-16，距今 111 天。註冊已經停流近四個月。**

## 2. 新增與流失 —— 新增看得到，流失看不到

**新增**：可觀測（`profiles.created_at`）。3 月 3 人（含 admin 與老闆校內信箱，實際只有 1 個
陌生人）、3 月底 1 人、4 月 2 人、5 月起 0 人。

**流失**：**觀測不到，而且原因很具體**——`profiles.last_seen_at` 這個欄位存在，但
**6 列全部是 NULL**，代表從來沒有任何一段程式寫過它。沒有 last_seen 就沒有 MAU、沒有
沉睡判定、沒有流失定義。這是本次盤點最該優先修的資料缺口之一。

替代觀測（用 `article_impressions.user_id` 當登入活躍代理，1968 列全量聚合）：

| 月份 | 總 impression | 登入狀態 impression | distinct session |
|---|---|---|---|
| 2026-03 | 258 | 123 | 108 |
| 2026-04 | 517 | 375 | 232 |
| 2026-05 | 217 | 65 | 176 |
| 2026-06 | 328 | 54 | 248 |
| 2026-07 | 556 | 44 | 495 |
| 2026-08（至 8/5） | 92 | **1** | 85 |

兩件事同時發生，方向相反：

- **匿名流量在成長**：session 數 108 → 232 → 176 → 248 → **495**（7 月），8 月前 5 天已 85。
- **登入活躍在崩塌**：登入 impression 375（4 月）→ 65 → 54 → 44 → **1**（8 月）。

歷來曾有登入閱讀行為的 user_id 只有 **3 個**（全部對得上 profiles，無孤兒 id）。
也就是說 6 個註冊者裡有 3 個註冊後從未在站上讀過任何一篇文章。

## 3. 會員實際在問什麼

`public.questions` 共 89 題，但要先把來源拆開才有意義：

- `source='internal'` **70 題**（AI 自產的研究議題，proposer 為 Claude/Codex/「用戶」）
- `source='user'` **19 題**，其中 2026-03-17 同一天的 6 題（Ivan/Alice/Bob/Charlie/David/Eve）
  是明顯的種子測試資料，1 題是 `testtewtrwqetwqtewqtqwet`（已 archived）

**扣掉種子與測試，真實會員提問只有 12 題**，且高度集中：

| 提問者 | 題數 | 期間 |
|---|---|---|
| yaoxk1431 | **8** | 2026-03-31 ~ 2026-07-18（每月不間斷） |
| yihao.lai / yhlai（老闆本人） | 3 | 3–4 月 |
| ideahub.everything | 1 | 2026-04-04 |

主題分群（12 題，人工歸類）：

1. **總經／產業敘事型選股（6 題，全部來自 yaoxk1431）** — 「未來五年台灣營造業會大漲的 10 個理由」、
   「進口車比例上升代表什麼、推薦可買股票」、「酒店娛樂業與股市相關性」、「台股到 60,000 點該預先佈局什麼」。
   共同特徵：要 2000–3000 字、要圖表、要個股推薦。
2. **投資框架型（2 題，同一人，7 月連兩週）** — 「我要 30 年每年穩定成長 15%／7%，我必須掌握哪 15 個問題」。
3. **另類資料策略（2 題）** — 美國國會議員持股追蹤能否獲利、反向操作是否可行。
4. **本業波動率方法（2 題，皆老闆自問）** — BTC 與 VIX/VRP 關聯、copula 在股匯市的應用。

**兩個缺口，訊號很清楚**：

- **內容缺口**：唯一一位真實活躍會員，8 題有 6 題問的是**總經敘事＋產業＋個股推薦**，
  而平台產出的是波動率預測與策略研究。他每個月回來、每個月用掉免費額度，
  但他要的東西跟我們在寫的東西是兩件事。這是留存最強的訊號，也是最大的錯配。
- **產品缺口**：問題品質分數兩極——這 12 題有 5 題 score ≤ 9（3、4、4、6、8、9），
  代表評分機制認定「不可答／不對題」，但系統仍全部標成 `answered`。
  會員得到的是被勉強回答的答案，不是被引導到平台真正強的地方。

未答存量：`status='open'` 20 題、`partially_answered` 6 題，**全部是 internal 來源**，
真實會員提問 0 積壓。所以 SLA 目前不是瓶頸。

## 4. 從註冊到付費，每一步掉多少人

| 階段 | 可觀測 | 數字（2026-08 當月） | 全期 |
|---|---|---|---|
| 1. 匿名訪客 session | ✅ `article_impressions.session_id` | 85 | 1,344 |
| 2. 註冊 | ✅ `profiles.created_at` | **0** | 6（5 外部） |
| 3. 註冊後曾登入閱讀 | ⚠️ 代理指標 | — | 3 / 6 |
| 4. 用掉免費提問額度（價值時刻） | ✅ `quota_usage` | — | 4 / 6 曾用，**1 人持續** |
| 5. 瀏覽 pricing 頁 | ❌ **完全無埋點** | 不可觀測 | 不可觀測 |
| 6. 點擊付費 CTA | ❌ **CTA 已被關閉** | 0（不可能發生） | 0 |
| 7. 完成付款 | ❌ **無資料表** | 0 | 0 |

**第 5–7 步不是「轉換率很低」，是「這幾步不存在」**。三個獨立證據：

1. `frontend-v2-fix/src/lib/radar-data.ts:1193` `getPricingPlans()` 把三個方案全部
   hardcode `paymentEnabled: false`；Radar Plus 的 CTA 文案就是字面上的
   **「尚未開放付款」**，`ctaHref` 指向 `/me` 而非任何結帳流程。
2. `src/volpred/payments/`（ECPay adapter，CheckMacValue 簽章已實作並有官方測試向量）
   **production caller 為零** —— 全 repo 只有 `tests/test_payments_ecpay.py` 引用它。
3. Supabase 沒有 `subscriptions` / `orders` / `payments` / `ecpay_orders` /
   `billing_events` / `entitlements` 任何一張表（逐一查，全部 `PGRST205 table not found`）。
   entitlement 的唯一載體是 `profiles.role` 這個 TEXT 欄位，**沒有到期日、沒有方案 id、
   沒有金流單號**。

也就是說：即使今天把 CTA 打開接上 ECPay，收到的錢**無法對帳、無法自動開通、無法到期降級**。

## 5. 觀測缺口清單（給 platform_eng 開工單用）

| # | 缺什麼 | 影響 | 具體位置 |
|---|---|---|---|
| G1 | `profiles.last_seen_at` 從未被寫入（6/6 NULL） | 無法算 MAU／流失／沉睡 | 欄位已存在，缺寫入端 |
| G2 | 無訂閱／訂單／entitlement 資料表 | 收款無法對帳、無法自動開通與到期降級 | Supabase public schema |
| G3 | pricing 頁與 CTA 無任何埋點事件 | 算不出「看到價目表→註冊→付費」任一段轉換 | `src/app/pricing/page.tsx` |
| G4 | 註冊無來源歸因（referrer / utm / landing） | 5 個註冊者從哪來完全不知道 | `profiles` 無此欄位 |
| G5 | `article_impressions` 無 landing/exit 標記 | session→註冊無法歸因 | 表結構 |
| G6 | `questions` 低分題仍標 `answered` | 會員體感是「敷衍」而非「不對題被導引」 | 問答 lifecycle |

## 6. 建議先動的一件（回報經理裁決）

**建議：G3 + G1 —— 先把 pricing/註冊埋點與 `last_seen_at` 寫入補上，不要先開結帳。**

理由：

- 現在最急的不是「怎麼收錢」，是**7 月 495 個 session 換到 0 個註冊**這件事我們連原因
  都看不到。沒有 G3/G1，任何改善都無法驗證有沒有效——這正好違反平台的 Check 紀律。
- 成本低、可逆、不觸金流，不需要老闆授權。
- 開結帳（G2）代價高得多且**現在開反而危險**：沒有訂單表就收款＝製造對不了帳的收入，
  而池子裡本來就只有 5 個人，開了也沒有人可以轉換。順序應該是
  **量測（G3/G1）→ 訂閱骨架（G2）→ 打開 CTA**。

第二順位是 G2，但建議它以「資料骨架與 entitlement 到期模型」立案，**明確不含打開 CTA**。

另外一件不需要經理排序、屬於本部門自己該處理的：唯一持續活躍的會員每月都回來問
總經／產業選股，而我們每月產出波動率研究。這個錯配我會在下一班帶著具體選題建議
去找內容部談，不佔用經理的排序。
