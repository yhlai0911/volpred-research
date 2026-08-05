# member_success 工作日誌（append-only）

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
