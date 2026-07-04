# K1626 — TSM ADR (NYSE) vs 2330.TW：ADR 溢價、價格發現與波動率傳導（雙時區、lookahead-safe）

## 動機（Mission #2 研究護城河 + Mission #1/#5 高時效台灣讀者議題）

TSM ADR（NYSE: TSM, USD）與 2330.TW（台積電台股, TWD）是**同一家公司在兩個市場、兩個時區**交易：

| 市場 | 交易時段（台灣時間）| yfinance date label `t` 的收盤發生在 |
|------|------|------|
| 2330.TW | 09:00–13:30 | 台灣 `t` 13:30（**先**）|
| TSM ADR | 21:30–04:00（美東 09:30–16:00）| 台灣 `t+1` ~04:00–05:00（**晚 ~14.5 小時**）|

三個子問題：
1. **ADR 溢價序列（Q1）**：TSM ADR 隱含的每股台幣價 vs 2330.TW 收盤價的溢價隨時間如何變化？AI 熱潮期間是否創紀錄？
2. **價格發現（Q2）**：哪個市場 leads？用日資料 lead-lag。
3. **波動率傳導（Q3）**：隔夜 ADR 波動是否預示 2330.TW 次日波動？方向性（US→TW 是否強於 TW→US）？

## 與 K1108b 的差異化（**關鍵前車之鑑**）

K1108b 曾發現「extended foundry pool 加入 TSM ADR 得到 **t=-2.28 反向**結果，是 ADR local-listing trading-day / timezone mismatch 造成的 **confounded artifact**」，因而把 ADR 排除在 primary pool 之外。

**本實驗的核心貢獻正是「正確處理」這個 timing mismatch，而非迴避它**。做法：
- 把「date label 對齊」與「資訊時序對齊」**分開處理**（date 對齊 ≠ 資訊對齊）。
- 每條 predictive regression 都用明確 `.shift()`，並在 code 註解寫清 information-time 假設。
- 把 K1108b 掉進去的那個「同 date 混用 ADR(t) 與 2330(t)」的方向，**只當 labelled diagnostic (eqC)** 跑出來展示 confound，**絕不當 predictive 結論**。

## Timing 模型（lookahead 最高風險，本實驗成敗關鍵）

同一 calendar date label `t` 的**資訊順序**：

```
2330.TW close(t)  [TW t 13:30]        <-- 最先發生
  -> TSM ADR close(t)  [TW t+1 ~04:00,  US 時段 t 反映 TW t 收盤 + 全球隔夜資訊]
  -> 2330.TW(t+1)      [TW t+1 09:00-13:30,  可吸收 ADR close(t)]
```

- `r_2330(t)` 涵蓋 `[TW t-1 13:30, TW t 13:30]`
- `r_ADR(t)` 涵蓋 `[TW t 04:00, TW t+1 04:00]`；其主體（US 時段 `TW t 21:30 → t+1 04:00`）**完全發生在 2330(t) 收盤之後**。

**合法方向（無 lookahead）**：
- **(A) US→TW 隔夜**：`r_2330(t) ~ r_ADR(t-1)` — ADR(t-1) 收在 TW t 04:00 < 2330(t) 收盤 TW t 13:30 ✅
- **(B) TW→US 同日**：`r_ADR(t) ~ r_2330(t)` — 2330(t) 在 TW t 13:30 < ADR(t) TW t+1 04:00 ✅

**禁止（lookahead）— 僅作 labelled diagnostic**：
- **(C)** `r_2330(t) ~ r_ADR(t)` 同 date — ADR(t) 是 2330(t) 的**未來**。這正是 K1108b 陷阱；報告它只為**揭露** confound，不是 finding。

## 資料

- 來源：yfinance 1.2.0。Tickers：`TSM`（ADR, USD）、`2330.TW`（TWD）、`TWD=X`（TWD per USD）。
- 期間：2004-03-24 ~ 2026-07-02（`START=2003-01-01`，受 TWD=X 起始限制）。
- 重疊交易日（inner join 兩檔股票）：**5616 天**（丟棄 ADR-only 296 天、2330-only 191 天）。
- Return 用 **Adj Close**（log return，去除各自股利/拆股跳點）；溢價 price-level 用 **raw Close**（`auto_adjust=False`）。
- **ADR ratio = 5**（1 TSM ADR = 5 股 2330 普通股；來源：TSMC ADR program，存託銀行 Citibank N.A.，NYSE:TSM）。實證交叉驗證：median implied ratio = **5.246**（= adr_usd × TWD/USD ÷ loc_twd），確認 ratio≈5 加約 5% 平均溢價。
- **資料品質過濾**：yfinance `TWD=X` 有偶發壞值（如 2011-10-25 Close=1.801，應為 ~30 → 造成假的 -93.9% 溢價）。同公司兩地價格不可能使 implied ratio 偏離 5 太遠，故丟棄 implied ratio 落在 [3, 9] 之外的 **2 個** data-error 日。Return/vol 不使用 FX，不受影響（>50% 日 return clip = 0 筆）。
- Seed = 42（block bootstrap）。

## 方法

- **溢價**：`premium(t) = adr_usd(t) × TWD/USD(t) / 5 / loc_twd(t) - 1`（same-date-label；ADR ~14.5h 較新）。描述統計 + rolling-252 percentile + expanding percentile。
- **價格發現**：eqA/eqB HAC (Newey-West) OLS + block bootstrap（1000 reps, block=20, seed=42）95% CI；雙向 Granger causality（maxlag=5）；cross-correlation function（k=-5..5）。
- **波動傳導**：Parkinson range `(ln(H/L))² / (4 ln2)` 作日內波動 proxy（**無 5-min RV**，見限制）。eqVA/eqVB HAC OLS；雙向 log-Parkinson Granger。
- 所有 HAC maxlags = `floor(4(n/100)^(2/9))`。

## 主要發現

### Q1 — ADR 溢價：AI 時代確實創紀錄（描述性，POSITIVE）
- 全樣本平均溢價 **+7.1%**（median +4.9%, std 6.7%）。
- **AI 時代（2023+）平均 +15.6% vs 前 AI 時期 +5.6%，約 2.8 倍**。
- **全 22 年樣本最高溢價 +33.8% 就發生在 AI 時代（2025-04-09）**——「AI 時代創紀錄」為真。
- 最新（2026-07-02）溢價 +12.35%，位於全樣本 expanding percentile 的 **79.5%**。
- 誠實限界：這是描述統計，不宣稱因果；溢價受 ADR 流動性、稅務、資金管制、FX daily-close timing 噪音等多因素影響。

### Q2 — 價格發現：US（ADR）**方向性領先** TW（乾淨的不對稱結果）
| 檢定 | 規格 | β | HAC t | R² | 判讀 |
|------|------|---|-------|----|------|
| eqA US→TW 隔夜 | `r_2330(t) ~ r_ADR(t-1)` | +0.360 | **+27.8** | 0.19 | 隔夜 ADR **強力**預示次日 TW ✅ |
| eqA + AR(1) | `+ r_2330(t-1)` | +0.437 | +30.1 | 0.24 | 穩健 |
| eqB TW→US 同日 | `r_ADR(t) ~ r_2330(t)` | +0.492 | +25.1 | 0.16 | 同日 TW 資訊流入 ADR（同日、合法）|
| eqC **diagnostic** | `r_2330(t) ~ r_ADR(t)` 同 date | +0.327 | +23.2 | 0.16 | **lookahead 陷阱，非結論**（K1108b confound）|

- Bootstrap：eqA slope 95% CI [0.337, 0.384]、eqB [0.455, 0.529]，**皆不跨 0**。
- **Granger（決定性不對稱）**：US→TW（r_ADR 因果 r_2330）**p≈0 於所有 lag 1–5**；TW→US（r_2330 因果 r_ADR）**p = 0.85 / 0.57 / 0.15 / 0.09 / 0.10，任何 lag 皆不顯著**。
- CCF 主峰在 **k=-1（0.44，ADR 領先）**；k=0（0.40，同日）；k>0（TW 領先未來 ADR）全部 near-zero。
- **結論**：隔夜 US ADR **領先**次日 TW；TW 資訊只在**同日**流入 ADR，**不具**對未來 ADR 的預測性領先。價格發現**偏向 US 市場**。

### Q3 — 波動率傳導：**雙向**溢出，US→TW 略強（與 return 的單向形成對比）
| 檢定 | 規格 | 跨市項 β | HAC t | R² | 判讀 |
|------|------|---------|-------|----|------|
| eqVA US→TW | `rv_2330(t) ~ rv_ADR(t-1) + rv_2330(t-1)` | +0.134 | **+3.25** | 0.44 | 隔夜 ADR 波動**確實**預示次日 TW 波動（modest）✅ |
| eqVB TW→US | `rv_ADR(t) ~ rv_2330(t) + rv_ADR(t-1)` | +0.291 | +7.94 | 0.29 | 同日 TW 波動流入 US 時段 |
- **Granger 雙向皆極顯著**：US→TW vol p ≈ 3.5e-57 … 1.7e-23；TW→US vol p ≈ 1.5e-49 … 9.6e-14。US→TW 在**每個 lag 都比 TW→US 更強**（p 更小）。
- **結論（honest nuance）**：與 return 的**單向** US→TW 價格發現不同，**波動率是雙向傳導**，US→TW 邊際占優。這符合直覺：資訊 shock 的方向性領先（return）偏 US，但波動叢聚（volatility clustering）會在兩地相互回饋。

## 限制（誠實揭露）
1. **僅日資料**：無 5-min intraday → 用 Parkinson range 當波動 proxy，**不是**真 realized variance，也無法做 Hasbrouck / Gonzalo-Granger information share。
2. **溢價 same-date-label**：ADR ~14.5h 較新；FX 用 `TWD=X` daily close 有輕微 timing 噪音。
3. **ADR ratio 假設 = 5**（已用 median implied ratio 5.246 交叉驗證）。
4. **Granger 於日資料**混淆同日順序；故以**明確 timing 的 HAC 方向性 regression（eqA/eqB/eqVA/eqVB）為 primary**，Granger 為 corroborating。
5. eqB/eqC 的同日 TW→US 通道無法與「US→TW 的極快同日回饋」完全分離；但 **lagged 檢定（eqA vs Granger TW→US null）是乾淨的**，支撐「US 領先」的主結論。

## Timing mismatch 自評（含 Codex CONDITIONAL_PASS 修正）
**方向乾淨、但「完全 lookahead-safe」需 asof 驗證後才可宣稱**。所有 predictive regression 皆用明確 `.shift()` + information-time 推理（見 `k1626.py` 頂部 docstring 與逐條註解）；K1108b 掉進去的「同 date 混用」方向只以 labelled diagnostic (eqC) 呈現、明標為 forbidden；FX data glitch 已過濾。eqC (t=23.2) 與 eqB (t=25.1) 的並列正好示範：naive 同日混用會給出看似顯著的 spurious 結果，而正確的 lagged 檢定 + Granger null 才揭露真實的單向價格發現。

**Codex review（gpt-5.5 xhigh, 2026-07-04）verdict = CONDITIONAL_PASS**（6 項逐查全 CONDITIONAL_PASS 或 PASS，無 FAIL）。核心方向結論穩健（US 隔夜領先次日 TW：HAC t=27.8、bootstrap CI 不跨 0、Granger 不對稱，Codex 判「方向不太可能只靠 HAC lag 選擇造成」）。**必修 issue（→ 具名 follow-up K1626f）**：目前對齊是 **common-date calendar inner-join 後 `.diff()`**，不是 **timestamp/asof event-time 對齊**——遇台美假日不一致日，`.shift(1)` 在交集 index 上可能漏掉 ADR-only 的最新可用收盤、或把多日 return 聚成一格。K1626f 需改用實際 Asia/Taipei close timestamp 做嚴格 asof merge（每個 TW close 對「嚴格早於它」最近 ADR close，反之亦然），重跑 eqA/eqB/Granger/vol，並量化多少列因假日不一致而改變；**通過後才可保留「lookahead-safe / 完全處理乾淨」這類強 wording**。次要修正（已反映在本 README）：Granger `p=0.0` 為數值下溢應讀作 `p≈0`；Q1 溢價是 **same-date-label 描述性指標**（ADR 較 TW 收盤新 ~14.5h），非同步可套利價差；Q3 vol「US→TW 略強」僅來自 p-value 比較、未做正式方向強度檢定，且 vol t=3.25 較弱，稱 robust 前應補 HAC-lag / block-length sensitivity。

## 可復現指令
```bash
uv run python experiments/k1626_tsm_adr_2330_price_discovery/k1626.py
```
產出：`k1626_results.json` + 4 張 PNG（premium / ccf / leadlag / vol_transmission）。所有數字可由此腳本重跑得出（seed=42）。

## 後續方向（具名 follow-up K，不塞進本次 scope）
- **K1626b**：intraday 5-min Hasbrouck / Gonzalo-Granger information share（需 intraday 資料）。
- **K1626c**：ADR 溢價作為**可交易信號**——溢價是否 mean-revert？是否預測次日 2330 return？（premium-based strategy，接 Mission #1 策略線）。
- **K1626d**：BEKK / DCC-GARCH 波動溢出正式 MLE（依 pooled-MLE 規則 ≥100 multistart）。
- **K1626e**：regime split（AI 時代 vs 前 AI）的 lead-lag——US 價格發現優勢在 AI 時代是否**增強**？
- **K1626f（Codex 必修 → robustness gate）**：timestamp/asof event-time 對齊——用實際 Asia/Taipei close timestamp 做嚴格 asof merge（取代 common-calendar inner-join），重跑 eqA/eqB/Granger/vol，量化台美假日不一致改變的列數；通過後回填「lookahead-safe / 完全乾淨」強 wording。

## 檔案
- `k1626.py` — 完整可復現腳本（fetch → align → premium → price discovery → vol transmission → tests → results.json + charts）
- `k1626_results.json` — 全部數字
- `k1626_premium.png` / `k1626_ccf.png` / `k1626_leadlag.png` / `k1626_vol_transmission.png`
