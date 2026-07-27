# K1725 — 現貨 BTC ETF 上市對加密 vol「時段結構」的改變

## 動機（Motivation）

現貨 BTC ETF（IBIT 等）於 **2024-01-11** 在美股（NYSE Arca / Nasdaq / CBOE）掛牌。
文獻（J. Futures Markets 2025 lineage）提出的假說：**ETF-ization 把加密資產的波動「時段
分配結構」拉向傳統市場時鐘**。具體而言，美股常規交易時段（RTH, 9:30–16:00 ET）所承載的
realized variance（RV）**佔比**在 IBIT 後**上升**，而週末 / 非時段佔比**下降**。

這是一個關於**「波動何時發生」（when）的時間重分配**主張，與既有的 vol-of-vol / 外溢
（spillover, 「how much」）研究**本質不同** —— 不是量的外溢，而是時間分配結構的改變。

## 差異化（與相關研究的區隔）

- 既有 crypto vol 研究多聚焦：GARCH/HAR 水平預測、跨市場外溢幅度、vol-of-vol 結構轉變
  （BTC vol 200%→50%）。本 K **不預測水平**，而是檢定 **RV 在一日/一週內三個時段桶的
  分配佔比是否因 IBIT 而重分配**。
- 因此 identifying variation 是「時段佔比」的斷點，而非幅度或外溢。

## 資料（Data）

- **來源**：Binance 公開 klines API（`api.binance.com` / mirror `data-api.binance.vision`），
  `BTCUSDT`，`interval=1h`，無需 API key。回溯抓取起點 `2022-01-01`，終點為腳本執行時刻。
- **為何 Binance 而非 yfinance**：yfinance `interval='1h'` 硬上限 ~730 天回溯，2026-07 往回
  只到 ~2024-07，**吃不到 2024-01-11 斷點**，會讓 pre/post 設計失效。Binance klines 可回溯
  到 2017，分頁 `startTime/endTime` 每次 1000 根。
- **時區**：一律以 **UTC** 為 canonical 索引；時段桶映射時才轉 ET wall-clock。
- **資料衛生**：(1) 依 `open_time` 去重（本專案有 snapshot-dup 污染前科，
  `storage/ops/snapaudit_reconciliation_20260722.md`）；(2) 對齊 `pd.date_range(freq='1h')`
  檢查缺根數與缺根比例；(3) 記錄實際起訖與根數。全部寫入 `k1725_results.json.data_hygiene`。
- **本地快取**：`data/btcusdt_1h.csv`（重跑不重打 API；刪除即重抓）。

## 方法（Method）

### RV 時段拆解

- 小時 close-to-close log return：`r_t = ln(C_t / C_{t-1})`。日/週 RV = 桶內 `Σ r_t²`。
- **三桶**（以每根 bar 的 **open time** 轉 ET wall-clock，用 `zoneinfo` America/New_York
  **自動處理夏令時 DST**）：
  1. **US-session (RTH)**：ET 平日（Mon–Fri）且 ET open-hour ∈ {9,10,11,12,13,14,15}
     —— 涵蓋 ~09:00–16:00 ET，是 9:30–16:00 RTH 的 **±30 分鐘近似**（小時 bar 無法對齊
     9:30 半點；此近似含 09:00–09:30 開盤前半小時，於 README 明示為 limitation）。
  2. **weekend**：ET 週六或週日全日。
  3. **non-session**：ET 平日且 ET open-hour 不在 RTH 集合。

### 主要聚合單位 = 週（ISO week, ET 曆, Monday-anchored）

- **為何用「週」而非「日」**：日層級的**週末佔比會退化** —— 平日的 `weekend_share ≡ 0`、
  週末日的 `us_session_share ≡ 0`。若對「每日三桶佔比」做 pre/post 檢定，週末桶的日序列
  恆為 {0 或 1}，其均值 ≈ 週末日比例（≈2/7），**與 ETF 效應無關**，無法檢定週末佔比變化。
  改以**週**為單位，一週同時含平日 RTH 小時與週末小時，**三桶佔比聯合非退化且合計=1**，
  才能對三桶都做正確的重分配檢定。日層級 RTH 集中度另作為穩健性（R4）保留。
- 每週：`bucket_share = RV(bucket, week) / total_RV(week)`，三桶 share 合計 = 1
  （success criterion 一致性檢查）。

### 斷點檢定

- **完整週閘（complete-week gate）**：僅保留 bar 數 ≥ 160 的週（完整 ET 週 ~168，DST 167/169），
  剔除起訖不完整的部分週 —— 部分週退化（如終端 9-bar 週為 (0,1,0)）會污染所有檢定、
  尤其 logit（0/1 share clip 後產生極端 log-odds）。本次僅剔 1 個終端部分週。
- **主檢定（known breakpoint 2024-01-11）**：對「週 US-session RV 佔比」做
  **pre vs post Welch t-test**（不假設等變異）+ **Cohen's d** + **佔比百分點差 (pp)** +
  **circular block bootstrap 95% CI**（block ≈ n^{1/3}，保留自相關，`seed=42`，B=5000）。
  - 主窗口：pre = [2023-01-11, 2024-01-11)（1 年），post = [2024-01-11, 資料末端]。窗口切分以
    週 label（週一）為界，跨 IBIT 那一週歸入 pre（R1 事件緩衝提供乾淨對照）。
- **補強（endogenous break location）**：**sup-Wald / Andrews QLR** mean-shift 掃描
  （trim 15%，合法斷點分數 k∈[⌈n·0.15⌉, ⌊n·0.85⌋] **兩尾皆滿足 trim**），回報 argmax 斷點日期、
  classical sup-F、5% 漸近臨界值（Andrews 1993 ≈ 8.85；2003 corrigendum ≈ 8.68，本檔以 8.68 判定）
  與距 IBIT 天數 —— **只讀斷點位置**是否落在 IBIT 附近，勝過只信先驗日期。
  sup-F / Chow 用 classical SSE（無 HAC）；週 share 有輕度序列相依（acf1、Ljung-Box lag-4 已診斷），
  故斷點顯著性屬 **assumption-heavy**，只讀位置不當作精確 p 值。
- **Chow test**：在已知 2024-01-11 的 mean-shift 檢定（與 Welch 互為 cross-check；同屬 iid-assumption-heavy）。

### 穩健性（Robustness）

- **R1 事件緩衝**：剔除 IBIT 前後各 4 週重跑三桶 Welch（排除掛牌前後的過渡噪音）。
- **R2 logit-share 常態化**：對 share 做 logit 變換後重檢（share 有界於 [0,1]，logit 較近常態；
  注意 logit 尺度的差是 **log-odds**，非百分點）。
- **R3 延伸 pre 窗口**：pre 拉長至 2 年（2022-01-11 起）重檢（更高 power，但混入 2022 LUNA/FTX
  極端 regime，故列為穩健性而非主窗口）。
- **R4 日層級平日 RTH 集中度**：`RTH_RV / (RTH_RV + nonsession_RV)`（排除週末、剔 bar 數 <20 的部分日），
  直接檢定「交易日內 variance 是否更集中於美股時段」，含 Welch + block bootstrap。
- 三桶皆檢定並判定重分配方向（是否 US↑ 且 weekend/non-session↓），為主分析一部分。

## Lookahead policy（前視風險政策）

**本 K 為 realized（同期）variance 佔比的描述性 / 結構斷點研究，非預測任務。**
- 沒有任何「以 t-1 資訊預測 t 結果」的預測性訊號，因此**無 `signal.shift(1)` 適用對象**
  —— RV 佔比是同期觀測量，不是被預測目標。
- 主斷點日期 2024-01-11 為**外生、事前固定**的日曆事件（IBIT 掛牌），**非 in-sample
  最佳化**選出的斷點。
- sup-Wald 的 endogenous 斷點搜尋僅用同期資料，且**只作為斷點位置的佐證**，
  絕不包裝成預測性 / 可交易主張。
- 所有隨機程序（block bootstrap）固定 `SEED=42`。

## Success criteria（CONDITIONAL_PASS 最低門檻）

- [x] 明確回答：週 US-session RV 佔比在 IBIT 後是否**統計顯著**改變？方向與量級為何？
- [x] 三桶合計佔比 = 1 的一致性檢查（`consistency_shares_sum_to_one.passed`）。
- [x] 至少一個正式斷點/差異檢定（Welch + Chow + sup-Wald）+ 效果量（Cohen's d）+ CI
  （block bootstrap）。
- [x] 穩健性 ≥2 項（實際 4 項：R1–R4 + 三桶方向判定）。
- [x] 結論誠實標註資料限制。

## 結果與結論（Results & Conclusion）— VERDICT: **NULL**

> 數字全部可回溯至 `k1725_results.json`（`uv run python experiments/k1725/k1725.py` 重現）。
> 資料：Binance BTCUSDT 1h，40,044 根（去重 0、缺 1 根 = 0.0025%，該缺口後的 2h return 已設 NaN），
> UTC 2022-01-01 → 2026-07-27；完整週閘後 **236 週**（剔 1 個終端部分週）；三桶 share 合計 = 1
> （max 偏差 2.2e-16）。

**主檢定（1 年 pre 窗口，週 RV 佔比，Welch）**

| 桶 | pre | post | 差 (pp) | Welch t | p | Cohen d | block-boot 95% CI | CI 排除 0 |
|---|---|---|---|---|---|---|---|---|
| US-session | 0.399 | 0.418 | **+1.86** | 0.77 | 0.441 | 0.15 | [−0.021, +0.059] | 否 |
| non-session | 0.463 | 0.417 | **−4.61** | −1.89 | 0.063 | −0.38 | [−0.083, −0.011] | **是** |
| weekend | 0.137 | 0.165 | **+2.75** | 1.61 | 0.110 | 0.26 | [−0.005, +0.060] | 否 |

**核心結論（誠實、不誇大）**：

1. **假說不成立於常規顯著水準。** 週 US-session RV 佔比僅上升 +1.86pp（39.9%→41.8%），
   **統計上不顯著**（Welch p=0.441, d=0.15, block-bootstrap 95% CI 含 0）。
2. **唯一 bootstrap CI 排除 0 的效應是 non-session（平日隔夜）佔比下降** −4.61pp
   （Welch p=0.063；bootstrap CI [−0.083, −0.011] 排除 0）。但——
3. **週末佔比反而上升** +2.75pp，**與假說相反**（「拉向傳統市場時鐘」預測週末應**縮小**）。
   因此並非乾淨的「US↑、週末↓」重分配；真實圖像是 non-session 佔比縮小、同時分散到
   US **與**週末兩側，而非集中到美股時段。（`redistribution_check.is_redistribution_toward_rth=True`
   僅因 non-session 下降就觸發，**不可據此宣稱假說成立**；`weekend_contradicts_clean_hypothesis=True`。）
4. **最強 endogenous 斷點候選遠離 IBIT。** sup-Wald（Andrews QLR，合法 trim 修正後）argmax 落在
   **2023-06-19**（classical sup-F=9.50，名義上 > 5% 臨界 8.68，距 IBIT **−206 天**）。
   但週 share 有輕度序列相依（IBIT-demeaned acf1=0.097、Ljung-Box lag-4 p=0.031），classical
   sup-F 標準誤**非精確**，故此顯著性屬 assumption-heavy —— 我們**只讀斷點位置**：它離 IBIT 甚遠，
   最多只能說「樣本內最強單一 mean-shift 候選不靠近 ETF 掛牌」，**不能**證明唯一斷點或排除次級斷點。
5. **名義顯著性只出現在被 2022 regime 混淆的規格、且在關鍵穩健性下消失：**
   - R3 延伸 2 年 pre → US +3.88pp p=0.025、non-session −5.29pp p=0.002。但此窗口含 2022 極端
     regime，可能受其混淆（endogenous 最強斷點亦落在 2023 中、遠離 IBIT），**不能歸因於 IBIT**。
   - Chow@IBIT F=5.43 p=0.021 —— 但其 pre 亦用全 2 年資料、且同屬 iid-assumption-heavy，受同樣混淆。
   - R1 事件緩衝（剔 ±4 週）→ US +1.44pp p=0.572，效應消失。
   - R2 logit 常態化 → US log-odds 差 +0.094 p=0.397，**不顯著**（唯一 logit-顯著的桶是 weekend
     p=0.039，但週末是**上升**、方向與假說相反）。raw +1.86pp 對 logit 不穩健。
   - R4 日層級平日 RTH 集中度 +2.96pp p=0.068（bootstrap CI 含 0），marginal 不顯著。

**判定（machine-derived, `conclusion.verdict`）= `NULL`**：主假說「IBIT 後美股時段 RV 佔比顯著上升、
且週末/非時段下降」在主窗口**不成立、方向不完整（週末反向上升）、且不穩健**。verdict gate 要求
US 方向為正 + 三個主窗口規格皆顯著 + 至少一個抵銷桶如預期下降 + 週末不反向 —— 四項未同時滿足。
唯一站得住的**探索性次級證據**是平日隔夜（non-session）佔比縮小（bootstrap CI 排除 0），但它擴散到
US 與週末兩側、非集中美股時段，且未做三桶 joint / multiple-testing 推論，故僅列為 exploratory。
**寧報 NULL 不誇大。**

## 資料限制（Limitations，誠實揭露）

1. **RTH half-hour grid 近似**（非「DST 近似」—— DST 由 zoneinfo 精確處理）：小時 bar 無法對齊
   9:30 半點；RTH 桶用 {9..15} ET 小時，含開盤前 09:00–09:30 半小時，為 ±30min 網格近似。
2. **未剔除美股假日**：RTH 桶包含 NYSE 假日對應的 ET 時段（該時段美股實際休市）。此偏誤的**方向未知** ——
   取決於假日當日 crypto RV 及 pre/post 假日構成，**不保證只會稀釋**；未做假日校正。
3. **單一交易所代表性**：僅 Binance BTCUSDT，未跨交易所加權；Binance 是最大現貨場所，
   但不等同全市場。
4. **窗口長度與混淆**：主 pre 窗口僅 1 年（受 IBIT 時點限制），power 有限；延伸 2 年窗口（R3）與
   Chow 混入 2022 極端 regime，其名義顯著性**可能受 2022 regime 混淆、不能歸因於 IBIT**。
5. **斷點推論 assumption-heavy**：sup-Wald / Chow 用 classical SSE（無 HAC），週 share 有輕度序列相依
   （acf1=0.097、LB lag-4 p=0.031），故斷點 p 值非精確，只讀位置。
6. **窗口切分邊界**：以週 label（週一）切 pre/post，跨 IBIT 那一週歸入 pre；R1 事件緩衝為乾淨對照。
7. **相關性未建模成因果**：known breakpoint 是研究者事前固定，**日期重合本身不是證據**；本 K 主 US 檢定
   不顯著、endogenous 最強斷點又遠離 IBIT。同期可能有其他宏觀/市場結構變化（利率、其他監管事件），
   本 K 為 observational event-window 分析，**非嚴格因果識別，不能對 IBIT 做因果歸因**。

## 檔案

- `k1725.py` — 可重跑腳本（`SEED=42`），資料抓取+快取、RV 拆解、斷點檢定、穩健性。
- `k1725_results.json` — byte-traceable 輸出（每個數字可回溯到腳本區塊）。
- `data/btcusdt_1h.csv` — Binance 原始 klines 本地快取。

## 重跑

```bash
uv run python experiments/k1725/k1725.py
```

## Knowledge draft（給主線程；agent 不自寫 knowledge.json，K1259 gate）

> 數字取自 `k1725_results.json`；agent 不自寫 knowledge.json（K1259 gate），交主線程審核入庫。

- **verdict**：`NULL`（主假說在主窗口不成立、方向不完整且不穩健；含一項 exploratory 次級發現）
- **topic**：現貨 BTC ETF（IBIT, 2024-01-11）對 BTCUSDT realized variance 時段分配結構的斷點檢定。
- **finding**：週 US-session RV 佔比 pre→post 由 **0.399 → 0.418（+1.86pp）**，
  **不顯著**（Welch t=0.77, p=0.441, d=0.15；block bootstrap 95% CI [−0.021, +0.059] 含 0）。
  三桶方向：US-session ↑（+1.86pp, ns）、non-session **↓ −4.61pp（bootstrap CI [−0.083, −0.011] 排除 0）**、
  weekend ↑ +2.75pp（ns，**與「拉向傳統時鐘」假說相反**）。sup-Wald endogenous 最強斷點候選落在
  **2023-06-19**（sup-F=9.50，距 IBIT −206 天；序列輕度相依故 assumption-heavy，只讀位置 → 遠離 IBIT）。
  名義顯著性僅見於 2 年延伸 pre（US p=0.025）與 Chow（p=0.021），二者受 2022 regime 混淆；且在
  事件緩衝（US p=0.572）與 logit 常態化（US p=0.397）下消失。
- **takeaway**：IBIT 未在加密 vol 的時段分配上留下**穩健**印記；唯一站得住的 **exploratory** 訊號是平日隔夜
  （non-session）佔比縮小，但它擴散到 US **與**週末兩側、非集中美股時段 → 不支持 ETF-clock 假說。
  與 vol-of-vol spillover 文獻的「量」外溢是不同構面，本 K 的「時間分配」構面呈 null。
- **method note**：週為主聚合單位（日層級週末佔比退化）+ 完整週閘（剔部分週）；RTH 用 ET {9..15} 網格近似
  （DST 由 zoneinfo 精確）；斷點用 classical sup-F/Chow（無 HAC，assumption-heavy）；穩健性 R1–R4；
  資料 40,044 根 1h（缺 1 根、gap 後 return 設 NaN）、完整週閘後 236 週。
- **limitations**：RTH half-hour grid 近似、未剔美股假日（偏誤方向未知）、單一交易所（Binance）、
  主 pre 窗口僅 1 年、斷點 iid-assumption-heavy、相關非因果（2022 regime 混淆，不能對 IBIT 因果歸因）。
- **reviewer**：`<Codex review v2 — 由主線程填；v1 判 FAIL 已於本輪修正並重審>`
