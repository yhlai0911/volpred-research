# K1684 E2 — 認證審查（review-certification gate）

- **Reviewer**: gemini-3.1-pro-preview（direct API via `scripts/gemini_ask.py`）
- **Reviewed commit（凍結）**: `dd211a5e5`
- **Reviewed at**: 2026-07-17T20:12:56Z
- **Scope**: README §8 三爭點的方法論裁定 —— 判定 H2_UNSUPPORTED 誠實 null 是否站得住、可否併入知識庫（**非** paper-ready 判定）
- **背景**: 本班兩次 Codex 認證審查（session 019f710f 01:12、019f7128 01:40）皆卡在 reasoning 無最終裁決；依 task 授權（README/task「若再 stall 改用 gemini_ask.py」）改用 Gemini。
- **凍結檔 sha256**: 逐檔比對 review_verdict.json 的 `reviewed_sha256`，8 檔全 `ALL_MATCH`。

## FINAL_VERDICT: PASS

## 三爭點裁定

**(a) 對稱乘法 bias 校正（僅修 level）是否足夠 → 足夠（non-blocking）**
QLIKE 對 predicted/target scale 錯配極敏感；乘法校正已消除離散價格向下偏誤的一階 level bias。裁決並非「單靠」校正，而是以校正為診斷工具（證明 HAR 在 raw GK 上的大勝是 proxy-calibration artifact），正式檢定依據是 Patton (2011) 無偏 co² proxy。expanding Mincer–Zarnowitz（截距+斜率）/ Hansen–Lunde 全套屬 non-blocking robustness，不影響凍結與核心結論。

**(b) 以無偏 co² 為主裁是否恰當（N225 caveat）→ 足夠且恰當**
Patton (2011)：有偏 proxy 上的 QLIKE 會系統性偏袒「與該有偏 proxy 動態最相符」的模型。HAR 訓練在 GK 上 → 其對 recal-GK 的殘餘優勢（N225 t≈−3.1）是可預期的內生現象，反映對 proxy 噪音結構的擬合，非對真實潛在波動的預測勝出。以條件無偏 co²（t=−0.39）為唯一公平主裁符合頂尖計量期刊理論要求；誠實揭露 N225 caveat 是嚴謹表現。

**(c) co² near-zero QLIKE 病態是否 blocking → 否（non-blocking）**
co² 極嘈雜、open≈close 日產生病態分配，降低 DM power，是 Patton (2011) 框架公認代價。已用平滑 proxy 族（GK/PK/RS）對稱校正 + 無偏 proxy 形成三角佐證。未 winsorize 的 co² 是理論上最乾淨、無人為干預的 baseline；winsorize/trim 是未來論文 nice-to-have，不構成 blocking defect。

## Blocking defects
（無）

## 非阻斷建議（若走 paper route 再補）
- 補 expanding Mincer–Zarnowitz（截距+斜率）作為 leg-1 公平性 robustness。
- co² winsorize / 排除極端低 co² 日的 robustness 表。
