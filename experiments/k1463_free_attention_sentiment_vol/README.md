# K1463 — 免費 attention / sentiment proxy 在 HAR+VIX 之後還有沒有用？

## 問題

這不是重新跑一次「Google Trends 有沒有用」。

那條線其實已經被測很多次：K473 / K750 / K789 / K531 / K1116 / K1117b 都碰過 attention 或 sentiment 類 proxy，而且大方向早就偏向 `VIX sufficiency`。真正還值得補的一格是：

> 在同一段共享樣本、同一個 volatility target、同一套 timing discipline 下，免費 public proxy 放進 `HAR+VIX` 之後，還有沒有額外 OOS 價值？

## 這次測的 proxy

- `CNN Fear & Greed`：日頻市場情緒
- `AAII bull-bear spread`：週頻散戶調查情緒
- `USEPUINDXD`：日頻政策不確定性 / 新聞不確定性
- `UMCSENT`：月頻 Michigan consumer sentiment（PIT release-date 對齊）

## 資料與 timing

- SPY OHLC：`experiments/k1206/data/SPY.csv`
- VIX：`experiments/k1312/data/VIX.csv`
- CNN Fear & Greed：`storage/sentiment/cnn_fear_greed_historical.csv`
- AAII：`storage/sentiment/aaii_sentiment.csv`
- USEPU：`experiments/k1121/data/fred_USEPUINDXD.csv`
- UMCSENT PIT：`experiments/k1117b/data/UMCSENT_monthly_pit.csv`

樣本交集：

- full sample：`2011-02-03` → `2023-12-29`
- OOS：`2018-01-02` 附近起跑，實際 OOS 首日 `2018-01-02` 之後滿足 window 條件的第一批預測
- total usable rows：`3226`
- OOS rows：見 results JSON `n_oos`
- train window：`1000`
- refit：每 `63` 日

### timing discipline

- `VIX`：lag 1 日
- `CNNFG`：lag 1 日
- `AAII`：先用 `report_date + 1 business day` 才視為可得，再在模型裡 lag 1 日
- `USEPU`：依 K1121 / error_log 規則採 `shift(2)`（公布延遲 + 交易 lag）
- `UMCSENT`：使用 PIT `release_date` 對齊，再 lag 1 日

## 模型

1. `HAR`
2. `HAR+VIX`
3. `HAR+VIX+CNNFG`
4. `HAR+VIX+AAII`
5. `HAR+VIX+USEPU`
6. `HAR+VIX+UMCSENT`
7. `HAR+VIX+ALL`

target 一律是 **SPY 日頻 Parkinson variance**，比較用 QLIKE。

## 文獻

1. Baker, Bloom, Davis (2016) — Economic Policy Uncertainty
2. Da, Engelberg, Gao (2011) — In Search of Attention
3. Shapiro et al. (2022) — Measuring News Sentiment
4. Corsi (2009) — HAR multi-scale volatility persistence

## 主要結果

### 1. HAR → HAR+VIX 明顯變好

- `HAR` OOS QLIKE = `0.5319`
- `HAR+VIX` OOS QLIKE = `0.4504`

先前的大方向再次成立：VIX 不是小修小補，而是主要增量來源。

### 2. 免費 proxy 放在 VIX 後面，大多沒有穩健增量

OOS QLIKE：

- `HAR+VIX+CNNFG` = `0.4481`
- `HAR+VIX+AAII` = `0.4482`
- `HAR+VIX+USEPU` = `0.4515`
- `HAR+VIX+UMCSENT` = `0.5051`
- `HAR+VIX+ALL` = `0.4848`

表面上 CNNFG / AAII 比 `HAR+VIX` 略低一點，但 DM 都不顯著：

- `+CNNFG`：DM t = `0.41`, p = `0.679`
- `+AAII`：DM t = `0.65`, p = `0.515`
- `+USEPU`：DM t = `-0.30`, p = `0.762`

### 3. 有些 proxy 在 in-sample 看起來顯著，但 OOS 不成立

full-sample HAC：

- `CNNFG` p = `6.53e-12`
- `USEPU` p = `7.59e-04`
- `AAII` p = `0.113`
- `UMCSENT` p = `0.191`

但這些 in-sample 顯著沒有轉成穩健 OOS edge。

### 4. UMCSENT 與 ALL 組合反而明顯拖累

- `HAR+VIX+UMCSENT`：DM t = `-3.73`, p = `2.0e-4`
- `HAR+VIX+ALL`：DM t = `-2.43`, p = `0.015`

解讀很直接：不是 proxy 越多越好。慢頻率或彼此重疊的情緒訊號，堆進去可能只是加噪音。

## 結論

`MOSTLY_NULL_AFTER_VIX`

這次的 reader-honest 結論不是「attention 完全沒資訊」，而是：

1. `VIX` 先吃掉了大部分可交易的前瞻風險資訊。
2. `CNNFG`、`AAII`、`USEPU` 在 full sample 可能帶一些相關性，但 **沒有轉成 Harvey-significant 的 OOS 預測增益**。
3. `UMCSENT` 與 `all-in stack` 甚至會讓預測顯著變差。

所以如果問題是「免費 sentiment / attention proxy 能不能在 HAR+VIX 之後再多榨出一層穩健 edge？」  
這份實驗的答案是：**大致不能，而且堆太多還會有害。**

## 與舊實驗的差異

- 不是重跑 Google Trends 單題
- 不是只做 in-sample partial correlation
- 不是不管 publication delay 的簡單 ffill

這次補的是：

- **shared sample**
- **shared target**
- **shared HAR+VIX benchmark**
- **conservative timing discipline**

## 限制

1. `CNN Fear & Greed` 樣本只到 2023-12，限制了共同樣本終點。
2. 沒把 Google Trends 放進共同樣本主表，因為本地 pinned 週頻 VIX search 資料從 2022 才開始，會把交集砍得太短；Google Trends 已有前案 K473/K750/K789。
3. 這裡測的是 **incremental forecasting value**，不是 proxy 本身的敘事或事件解釋能力。

## 檔案

- `k1463.py`
- `k1463_results.json`
- `k1463_qlike_and_pvalues.png`
