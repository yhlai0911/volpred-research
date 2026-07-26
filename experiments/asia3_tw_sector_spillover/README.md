# ASIA-3：台股產業層級波動溢出網絡（Diebold-Yilmaz connectedness）

**Experiment id**：`asia3_tw_sector_spillover`
**產出**：`asia3_tw_sector_spillover.py`、`asia3_tw_sector_spillover_results.json`、`assets/`（3 張圖 + rolling CSV）
**日期**：2026-07-27　**Seed**：42

---

## 1. 動機與差異化

VolPred 既有的波動溢出研究多在**跨資產**（K628b：SPY/TLT/GLD/0050，SPY 為 dominant transmitter）或**跨市場**（T5b：SPY→台股 Granger）層級。本實驗把 Diebold-Yilmaz (2012, 2014) connectedness 框架下沉到**單一市場內的產業層級**：台股 9 檔產業代表股，回答兩個問題：

1. 哪些產業是波動的**淨發送者**（net transmitter），哪些是**淨接收者**（net receiver）？
2. 連結度網絡在**空頭期**如何收斂/放大？

**與 T5a 的對話**：T5a 已知 VT gamma 結構為 `TAIEX 0.153 > 0050 0.087 > TSMC 0.039`（聚合層級愈高、gamma 愈大，ETF 分散化放大 gamma）。T5a 量的是**波動持續性（gamma）**、非溢出；但兩者可以對接——若產業層級存在明確的系統性傳送者（半導體/金融），則指數是把這些高度連結、共同因子持續的成分聚合起來，這正是「指數 gamma > 單股 gamma」的微觀基礎。本實驗檢驗這個 bridge 是否成立。

---

## 2. 資料

| 項目 | 內容 |
|---|---|
| 來源 | yfinance 日 OHLC（`auto_adjust=True`） |
| 標的 | 9 檔 TWSE 上市產業代表股（見下表） |
| 各檔可得起點 | 2317 1993、2330/2603/2609/1301 2000、2454 2001、2881 2001、3008 2002-03、2891 2002-05 |
| **共同樣本** | **2002-05-17 → 2026-07-24，N = 5,985 交易日** |
| 空頭覆蓋 | 2008 GFC、2011 歐債、2015 中國股災、2018Q4、2020 COVID、**2022 全球熊市**（OOS 含多次空頭，滿足硬規則） |
| Alignment | 9 檔皆 TWSE 同一交易日曆 → 內部 inner join，**不做跨市場假日填補、不前向填補** |

**波動度量：Garman-Klass (1980) 範圍估計量**（DY 2012 canonical 用法）：

```
σ²_GK = 0.5·[ln(H/L)]² − (2·ln2 − 1)·[ln(C/O)]²
```

只用**日內** log 比值，因此對任何**每日等比例價格調整（分割 / 除權息）不變**——`ln(kH/kL)=ln(H/L)`。這天然避開了 close-to-close proxy 會遇到的除權息跳空污染問題（本專案 `error_log` 記過「日內 RV 不可把隔夜跳空混入」）。取 `log(σ_GK)` 進 VAR。

**產業代表股與描述統計（年化波動）**：

| Ticker | 產業 | 年化波動 |
|---|---|---|
| 2330 TSMC | 半導體 | 17.3% |
| 2317 鴻海 | 電子代工 | 19.3% |
| 2454 聯發科 | IC 設計 | 26.5% |
| 2881 富邦金 | 金融 | 18.8% |
| 2891 中信金 | 金融 | 18.0% |
| 2603 長榮 | 航運 | 27.7% |
| 2609 陽明 | 航運 | 27.4% |
| 1301 台塑 | 塑化 | 18.5% |
| 3008 大立光 | 光學 | 28.7% |

（航運、光學、IC 設計波動最高；權值型半導體、金融、塑化較低。）

---

## 3. 方法

1. **VAR(p)**：對 9 檔 log-GK-vol 估 VAR，lag 用資訊準則選（AIC=6、BIC=2、HQ=5、FPE=6），主結果採 **AIC lag=6**，並做 lag robustness（見 §4.4）。系統穩定（所有特徵根 < 1）。殘差 Ljung-Box(10)：9 檔中 8 檔 p>0.05（僅中信金 p=0.007 有輕微殘留自相關）。
2. **廣義 FEVD（Pesaran-Shin 1998）**：以 VAR 的 MA(∞) 表示 `Ψ_h = Σ A_m Ψ_{h−m}` 計算 GFEVD，horizon H=10。**刻意不用 Cholesky-FEVD**——後者對變數排序敏感、會產生排序假象（本任務點名陷阱，`error_log` 亦記過 FEVD 軸向 K865 教訓）。GFEVD 排序不變。
   - 軸向紀律：row *i* = 被解釋變異的變數、col *j* = 衝擊來源；`from_others(i)` = 第 *i* 列去對角和、`to_others(j)` = 第 *j* 行去對角和；每列正規化後和為 1（程式內 assert）。
   - 方向性度量採 **DY(2012) /N 慣例**（to/from/net 除以 N，與 total 同尺度）。
3. **Rolling connectedness**：200 天窗、步進 5，觀察時間演化；另做 100/150/250 天窗與 H=12 敏感度。
4. **Granger 網絡**：pairwise Granger causality（Bonferroni 校正 α=0.01/72）作正交 robustness。
5. **補充 OOS 預測比較**：expanding window 一步預測，VAR（含跨產業資訊）vs 單變量 AR(lag)，用 canonical `volpred.stats.model_evaluation.dm_test`（Newey-West HAC、Harvey |t|>3 門檻）。按 K1355 紀律先**按日期聚合**跨產業 loss 再做 DM，不把 asset-day 當 iid。

**Lookahead 紀律**：VAR 本質是 `y_t ~ y_{t−1..t−p}`（嚴格因果）；rolling 每個日期只用窗內資料；OOS 迴圈明確 `train = arr[:t]`（結束於 t−1，嚴格早於預測目標 row t）。所有隨機程序 seed=42。

---

## 4. 結果

### 4.1 全樣本連結度：高度連結、相當對稱

- **Total spillover index = 80.5%**。9 檔台股個別的預測誤差變異中，平均約 **80% 來自其他標的**、僅 ~20% 來自自身（`from_own_share` 各檔 78.7–82.6%）。這是「單一整合市場內產業近乎飽和連結」的典型量級。
- **方向性淨值很小**（所有 |net| < 1.1%）——網絡高度連結但**相當對稱**，沒有單一支配傳送者。淨值差異幾乎全來自 **TO others 端的異質性**（FROM others 各檔 8.7–9.2% 幾乎均勻）。

**方向性表（%，DY /N 慣例）**：

| 產業 | TO others | FROM others | **NET** |
|---|---|---|---|
| TSMC（半導體） | 10.05 | 9.18 | **+0.87** |
| 富邦金（金融） | 9.61 | 9.03 | **+0.58** |
| 台塑（塑化） | 9.59 | 9.04 | **+0.55** |
| 中信金（金融） | 9.50 | 9.03 | **+0.46** |
| 長榮（航運） | 9.40 | 9.01 | **+0.40** |
| 陽明（航運） | 8.96 | 8.87 | **+0.08** |
| 聯發科（IC 設計） | 8.07 | 8.82 | **−0.76** |
| 大立光（光學） | 7.70 | 8.80 | **−1.09** |
| 鴻海（電子代工） | 7.64 | 8.74 | **−1.10** |

**淨發送者**：半導體（TSMC）> 金融 > 塑化 > 航運。**淨接收者**：電子代工（鴻海）、光學（大立光）、IC 設計（聯發科）。

**產業群平均 net**：Semiconductor +0.87、Petrochemical +0.55、Financials +0.52、Shipping +0.24（發送）；Electronics_EMS −1.10、Optical −1.09、IC_Design −0.76（接收）。

> **誠實限縮**：net 絕對值很小（< 1.1%），主導故事是「高且對稱的連結」，不是強烈的傳送者階層。傳送者/接收者排序是穩健的（§4.4），但不應被詮釋為大幅度的方向性支配。

### 4.2 與 T5a 的對照（bridge 成立、但為 suggestive）

TSMC 是 9 檔中**最大的淨發送者**，且是台股加權指數約 30% 權重的核心。產業層級「半導體/金融為系統性傳送者」的結構，與 T5a「指數 gamma > ETF > 單股 gamma」一致——指數把這些高度連結、共同因子持續的傳送成分聚合起來，聚合層級愈高就愈集中系統性波動、gamma 愈大。本實驗**支持但未證明**這條微觀基礎（GFEVD 是網絡中心性診斷，非結構性因果）。

### 4.3 空頭期網絡：異質，取決於危機**時長**（重要修正）

單純把「空頭 vs 平時」聚合平均是**誤導的**（200 天窗 bear 61.7% vs calm 62.9%，差 −1.2%，看似無效應）。逐危機拆解後真相是：

| 危機 | 型態 | 200 天窗 mean | vs 全期均值 62.8% |
|---|---|---|---|
| 2008 GFC | 持續性熊市 | **76.6%** | ↑ 明顯升高 |
| 2015 中國股災 | 持續性 | **69.1%**（max 85.9%） | ↑ 升高 |
| 2022 全球熊市 | 波段 | 58.2%（max 83.3%） | 尖峰升高 |
| 2011 歐債 | 短 | 58.3% | ≈ |
| 2018 Q4 急跌 | 快速 | **35.5%** | ↓ 反而低 |
| 2020 COVID | 快速崩跌 | **44.3%** | ↓ 反而低 |

**機制**：200 天 trailing 窗能充分捕捉**持續數月的熊市**（2008、2015），但對**數週內的急跌**（2018Q4、COVID）會被窗內大量平時資料稀釋 → 讀數偏低。聚合 bear≈calm 只是把「相反時長」的事件平均掉的假象，**不是無傳染的證據**。100 天短窗結論一致（bear 68.7% vs calm 69.2%），確認這是窗長 vs 危機時長的方法論細節。

> **對讀者角度（產業輪動 TA）的誠實表述**：台股產業波動在**持續性空頭**中確實收斂放大（連結度衝到 76–86%），此時「分散到不同產業」的避險效果最弱；但**快速崩跌**的傳染是數週尺度事件，用季度級 rolling 窗會低估——要抓它得用更短窗或事件研究。

### 4.4 穩健性

- **Lag robustness**：net 符號在 lag 2/4/6 下 **9/9 全一致**，Spearman ρ = 0.983，total 80.3–80.5% 幾乎不變 → 傳送者/接收者排序穩健。
- **窗長敏感度**：mean total 150 天 63.4%、200 天 62.8%、250 天 63.6%（穩定）。
- **Horizon**：H=10 → 80.53%，H=12 → 80.52%（不敏感）。

### 4.5 Granger 網絡（正交視角）

Bonferroni α=0.01/72 下 26 條顯著邊。out-degree（發送）：大立光 6、富邦金 5、TSMC 4、中信金/台塑 3；in-degree（接收）：陽明 8、中信金 5、大立光 4。

> **與 GFEVD 的分歧要誠實講**：Granger 把**大立光**列為最大發送者（out=6），但 GFEVD 把它列為最大**接收者**（net −1.09）。原因是兩者量不同的東西——Granger 測線性 in-sample 領先落後（大立光作為高波動、時常領先反轉的個股，短期線性上「Granger-causes」他人），GFEVD 測 H 步預測誤差變異分解（大立光的變異主要被系統因子解釋 → 接收端）。兩者在「航運/光學偏 idiosyncratic 接收側、金融/半導體偏系統發送側」大方向一致，但個股層級不完全重合。Granger 為 robustness 補充，非機制證明。

### 4.6 補充 OOS 預測：連結度**不助**點預測（誠實 null）

聚合後 VAR vs AR 一步預測 DM **t = +2.51**（正 t = VAR loss 較高，即較差）、p = 0.012，**未達 Harvey |t|>3**。逐產業診斷更揭露：大型科技股 TSMC（t=+3.29）、聯發科（t=+3.44）、大立光（t=+3.09）VAR **顯著更差**（Harvey-sig）——跨產業資訊對這些自身持續性強的權值股反而是雜訊。

> **結論**：DY connectedness 是**描述性網絡診斷**，本實驗未發現它能改善一步波動點預測，對部分權值股甚至有害。這與 DY 框架的定位一致（connectedness ≠ forecasting claim），如實報告為 null，不過度宣稱。

---

## 5. 圖表（`assets/`）

- `spillover_network.png`：淨 pairwise 溢出有向網絡（紅=淨發送、藍=淨接收，節點大小 ~ |net|）。
- `rolling_total_spillover.png`：200 天 rolling total spillover 時間序列（標注空頭區間）。
- `directional_bars.png`：各產業 TO / FROM / NET 長條（依 NET 排序）。
- `rolling_total_spillover.csv`：rolling 序列原始數據。

---

## 6. 限制

1. 日 Garman-Klass 是範圍型 proxy，非日內 realized variance。
2. GFEVD / connectedness 是**網絡中心性診斷**，非結構性因果溢出。
3. 金融、航運各有 2 檔代表股，其餘產業各 1 檔——產業覆蓋為代表性、非完備。
4. Granger causality 為線性 in-sample，僅作 robustness、非機制證明。
5. Rolling 窗長會影響對「快速 vs 持續」危機的偵測（§4.3）；季度級窗會低估數週尺度急跌的傳染。
6. 中信金殘差有輕微殘留自相關（Ljung-Box p=0.007），不影響 GFEVD 描述性結論但為診斷 caveat。
7. OOS 補充比較的 VAR/AR 共用同一 lag（比較公平），但該 lag 由全樣本 AIC 選定；完全 PIT 版本應只用 origin 前資料重選 lag（因共用 lag 的公平性與 n=2810，影響可忽略）。

---

## 7. 參考文獻

1. Diebold, F.X. & Yilmaz, K. (2012). Better to give than to receive: Predictive directional measurement of volatility spillovers. *International Journal of Forecasting*, 28(1), 57–66.
2. Diebold, F.X. & Yilmaz, K. (2014). On the network topology of variance decompositions: Measuring the connectedness of financial firms. *Journal of Econometrics*, 182(1), 119–134.
3. Pesaran, H.H. & Shin, Y. (1998). Generalized impulse response analysis in linear multivariate models. *Economics Letters*, 58(1), 17–29.
4. Garman, M.B. & Klass, M.J. (1980). On the estimation of security price volatilities from historical data. *Journal of Business*, 53(1), 67–78.

---

## 8. 復現

```bash
uv run python experiments/asia3_tw_sector_spillover/asia3_tw_sector_spillover.py
```

首次執行會下載 yfinance OHLC 並快取到 `data/ohlc_max.parquet`（後續離線可重跑）。全部數字寫入 `asia3_tw_sector_spillover_results.json`。
