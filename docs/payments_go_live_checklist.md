# 金流整合 — 已建置、尚未開放（2026-07-04）

**狀態：BUILT BUT NOT OPEN。** 平台變現目標（信賴度 / 流量 / 漏斗）尚未達到，
老闆明確指示「應該還無法收費」，所以 checkout **未開放**。此文件記錄：研究了哪些
金流、為何選綠界、已建了什麼、以及未來目標達成後「開通」需要哪些步驟。

## 1. 金流服務比較（有無 CLI / Skill / MCP）

| 服務 | AI 工具鏈 | 台灣支援 | 付款方式 | 訂閱扣款 | 定位 |
|---|---|---|---|---|---|
| **綠界 ECPay（選用）** | 官方 **Python SDK**（`ECPay/ECPayAIO_Python`）+ 官方 **agent Skill**（`ECPay/ECPay-API-Skill`）；無 MCP/CLI | ✅ 原生台灣 | 信用卡 / ATM / 超商 / LINE Pay / Apple Pay | ✅ 定期定額（信用卡週期授權） | 台灣本位、TWD 會員的實務首選 |
| Stripe | 最完整：官方 **MCP server**（`mcp.stripe.com` / `npx @stripe/mcp`）+ **CLI** + agent toolkit，Claude Code 原生支援 | ⚠️ 台灣商戶受限（僅信用卡、撥款限制） | 信用卡 | ✅ Billing/Subscriptions | AI 工具最強，但適合國際 / USD；台灣商戶不完整 |
| 藍新 NewebPay / TapPay | REST API + SDK，無 MCP/Skill | ✅ 台灣 | 信用卡 / ATM / 超商 | 部分 | 綠界的替代，工具鏈較弱 |

**決策：主用綠界 ECPay。** 理由：平台是台灣本位（TWD 計價的 Free/Radar Plus 299/
Research Pro 599），會員多為台灣使用者，需要信用卡以外的 ATM/超商付款與定期定額；
綠界原生支援且有官方 Python SDK + 官方 agent Skill。Stripe 的 AI 工具鏈雖最強，但
台灣商戶支援不完整，保留為「未來走國際 / USD」時的替代 adapter（介面已抽象，加一個
`StripeProvider` 即可，不需改架構）。

## 2. 已建置（`src/volpred/payments/`）

- `base.py` — provider 無關介面 `PaymentProvider` + **總開關** `PAYMENTS_ENABLED`
  （env，預設 **off**）。任何會產生扣款 checkout 的方法都先呼叫
  `require_payments_enabled()`，關閉時 raise `PaymentsDisabledError` —— 即使有人誤接
  UI 也不會意外扣款。
- `plans.py` — 方案 catalog 單一真實來源（Free / Radar Plus 299 / Research Pro 599），
  與前端 `radar-data.ts::getPricingPlans()` 對齊，tier→Supabase `profiles.role` 對應。
- `ecpay.py` — 綠界 adapter：`make_check_mac_value()`（AIO SHA256 簽章）、定期定額
  checkout 欄位組裝、callback 簽章驗證（constant-time）。**無網路呼叫、無真實憑證**：
  buyer 瀏覽器直接 POST 到綠界，憑證由 env 於呼叫時注入。預設用綠界**公開的 stage
  測試憑證**（MerchantID 2000132），零 secret 即可測試。
- `tests/test_payments_ecpay.py` — **19 tests**，最關鍵的
  `test_check_mac_value_matches_ecpay_official_vector` 把簽章演算法**釘死在綠界官方
  發布的測試向量**（`6C51C9E6...B840`）；簽章一旦漂移綠界會拒絕所有交易，此測試永不可壞。

**雙層 OFF gate**：(1) 後端 `PAYMENTS_ENABLED` env 預設 off；(2) 前端每個方案
`paymentEnabled: false`（`radar-data.ts`）。兩層都要主動打開才會真的收費。

## 3. 開通步驟（未來目標達成後）

1. **確認變現目標已達**（信賴度 / 流量 / 漏斗到位）—— 這是 policy gate，由老闆判斷。
2. **申請綠界正式商戶**：註冊 https://www.ecpay.com.tw/ 取得正式 MerchantID / HashKey /
   HashIV（需公司/個人商戶資料、對應金流費率）。
3. **憑證進 env（不進 git）**：`.env.local` / Zeabur service env 設
   `ECPAY_MERCHANT_ID` / `ECPAY_HASH_KEY` / `ECPAY_HASH_IV` / `ECPAY_ENV=prod`。
   （adapter 已擋「prod 但用 stage 測試 id」，避免誤用測試憑證上正式。）
4. **建 callback 端點**：前端 `/api/pay/ecpay/callback`（接綠界 async ReturnURL POST）
   → `verify_callback()` 驗簽 → 更新 Supabase `profiles.role=premium` + 記交易。
   （目前只有後端簽章邏輯，callback API route + 訂閱狀態機是開通時要補的。）
5. **打開兩層 gate**：後端 `PAYMENTS_ENABLED=1` + 前端對應方案 `paymentEnabled: true`。
6. **stage 端到端測試**：用綠界測試卡（4311-9522-2222-2222 等）跑完整流程，驗證
   定期定額授權 + callback 入帳 + role 升級。
7. **退款 / 取消訂閱 / 發票**流程（綠界定期定額可由使用者取消）—— 上線前補齊。

## 4. 尚未做（開通時才做，避免過度建置）

- callback API route + 訂閱狀態機（授權成功 / 每期扣款 / 失敗 / 取消）
- 前端 checkout 表單送出（`paymentEnabled` 打開後把 plan 導到後端組好的 ECPay form）
- 退款 / 發票（載具）/ 對帳報表
- Research Pro vs Radar Plus 的細緻 entitlement 分流（目前都對應 `premium`）

*Created 2026-07-04 台灣時間；owner = interactive main thread。此為 backend 骨架，
開通是 config + 少量 route 補完，不是重新開發。*

Sources:
- [ECPay Python SDK — ECPay/ECPayAIO_Python](https://github.com/ECPay/ECPayAIO_Python)
- [ECPay 官方 agent Skill — ECPay/ECPay-API-Skill](https://github.com/ECPay/ECPay-API-Skill)
- [ECPay CheckMacValue 檢查碼機制（官方測試向量來源）](https://developers.ecpay.com.tw/?p=2902)
- [Stripe MCP Server（官方）](https://docs.stripe.com/mcp)
