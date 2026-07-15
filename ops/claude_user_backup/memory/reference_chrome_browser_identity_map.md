---
name: reference-chrome-browser-identity-map
description: 老闆多個 Chrome 的身分對照；禁止用裸 deviceId 問老闆選瀏覽器
metadata: 
  node_type: memory
  type: reference
  originSessionId: 088b57da-f99e-4210-b03d-8f127c98bc2c
---

**Browser 身分對照**（2026-07-14 實測）：
- `398dcdba-2b52-427b-8877-aab67cda72cd`（原顯示 Browser 1）= **老闆主力 Chrome，VolPred 已登入（yihao.lai admin session）** — VolPred 後台驗證/FB 發文預設選這台
- 其餘（18871a8e / bc09353b / c68b92c0）身分未識別，用到時先探測再記回本檔

**Why**：2026-07-14 拿「Browser 1/2/3/4 + deviceId」問老闆選瀏覽器被痛罵 —
沒有人知道自己的視窗 id。裸 id 選單 = 垃圾體驗。

**How to apply**：多瀏覽器連線時**禁止直接把 list_connected_browsers 的裸名稱丟給老闆**。
順序：(1) 先查本檔對照，任務對得上（VolPred admin / FB）就直接 select 已知那台，不問；
(2) 對照不到才逐台快速探測（開分頁讀目標站登入態/Google 帳號），把「登入了什麼」寫成
人話標籤再問（例：「登入 VolPred 的那台」「無痕/乾淨的那台」）；(3) 新識別結果回寫本檔。
關聯 [[reference-fb-chrome-browser-autoselect]]。
