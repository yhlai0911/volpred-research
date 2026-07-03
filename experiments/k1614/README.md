# K1614 — 天然資源實質資產的波動率結構、通膨壓力與乾旱壓力診斷

**類型**：public-proxy diagnostic（**NON-tradable，不做策略回測、不宣稱可交易訊號**）
**Verdict**：`DIRECTIONAL_ONLY_PUBLIC_PROXY_DIAGNOSTIC`
**生成**：`experiments/k1614/k1614.py` → `k1614_results.json` + `figures/`
**資料來源**：yfinance（`auto_adjust=True`，adjusted close）+ FRED（CPIAUCSL/PPIACO/T10YIE）+ U.S. Drought Monitor California weekly statistics
**期間**：2015-01-01 ~ 2026-07-03（script `END=2026-07-04` 為 yfinance exclusive end），日資料，每檔 **2,891 個交易日**（跨資產一致）
**Seed**：42（本描述性實驗無隨機程序，仍依規範固定）

## 動機

農地 REIT、林地 REIT、水資源 ETF 這一籃「天然資源實質資產」常被行銷為「通膨避險 + 抗景氣循環 + 低相關避風港」標的。本實驗做**誠實的波動率結構與 public-proxy 壓力診斷**，回答四個問題：

1. 這一籃實質資產的已實現波動率(RV)是否形成一致的 vol cluster？
2. 市場高波動 regime 下，它們的 vol 是放大還是相對穩定（避風港 / 脫鉤特性）？
3. 各檔對大盤(SPY)的 vol beta 為何（<1 = vol 較大盤鈍）？
4. 在 lagged public inflation pressure / breakeven / California drought intensification proxy 下，下一個 21 交易日的 RV、downside volatility、與 SPY return correlation 是否真的較低？

**不做**策略回測、不宣稱可交易訊號；FRED CPI/PPI 是 current-vintage release-lag proxy，不是 consensus surprise / real-time vintage，結論強度不超過 public-proxy diagnostic。

## 資產

| 群組 | 代碼 | 說明 |
|---|---|---|
| 實質資產籃 (7) | LAND, FPI | 農地 REIT |
| | WY, RYN | 林地 REIT |
| | PHO, CGW, FIW | 水資源 ETF |
| 對照 proxy (3) | SPY | 大盤 |
| | TIP | 通膨連結債 |
| | DBC | 商品 |

## 方法

1. 日 log return `ln(P_t / P_{t-1})`（adjusted close）；RV = 21日 & 63日 rolling std × √252（年化）。主分析用 21d RV。
2. 五塊分析：
   - **(a) 描述統計表**：每檔 21d RV 的 mean/median/std/min/max + 當前值歷史百分位。
   - **(b) Vol cluster 一致性**：7 檔實質資產 21d RV 的 Pearson 相關矩陣、整體平均 pairwise corr、三子群(farmland/timber/water)內與跨群平均 corr。robustness 補 **ΔRV 差分相關**（去共同趨勢）。
   - **(c) 市場 regime 對照**：SPY 21d RV 全樣本三分位(low/mid/high)，比較每檔在各 regime 的平均 RV + 相對自身全期均值比率；high vs low 做 Welch t-test + Cohen's d + **非重疊子樣本 robustness**。
   - **(d) Vol beta**：每檔 21d RV 對 SPY 21d RV 的同期 OLS slope + R²（**Newey-West HAC SE** 校正重疊窗口 residual 自相關）。
   - **(e) Public-proxy stress diagnostics**：CPI/PPI 經保守發布延遲後 `shift(1)`，T10YIE 21d change `shift(1)`，USDM California DSCI 4w change 經 release_date+2 calendar days 後 `shift(1)`；target 是 signal date 之後 **21 個交易日**的 forward RV、downside volatility、與 SPY return correlation。正式 gate 用 HAC regression + Holm 校正；高/低分組只作描述性輔助。

### 防錯 / 誠實原則

- **Lookahead 控制**：
  - cluster / market-regime / vol beta 是同期描述性關係，非預測。
  - public-proxy stress diagnostics 明確使用 lagged stress columns：CPI/PPI 經發布延遲後再 `shift(1)`；T10YIE 與 USDM DSCI 也 `shift(1)`。
  - stress target 是 next-21-trading-day forward RV / downside / correlation，因此 signal 不含未來 realized volatility。
- **通膨資料 caveat**：FRED CPI/PPI 使用 current-vintage series；雖做保守 release lag，但仍不是 consensus surprise 或 ALFRED real-time vintage，不可宣稱交易級 inflation surprise。
- **多重檢定 gate**：63 個 stress × asset × target HAC regression cells 的 signal gate 需要 `|t|>=3` 且 Holm-adjusted p<=0.05；raw p 或 high/low split 不可單獨當結論。
- **重疊窗口自相關（重要 caveat）**：21d rolling RV 每日值高度自相關，有效樣本量遠小於名目 n → 標準 Welch t-test 的 p-value 被**系統性高估**。因此以 (i) **Cohen's d 效果量**（對 n 不敏感）與 (ii) **非重疊(每 21 日)子樣本 t-test** 為推論依據，overlapping-window p 僅供對照。vol beta 的 OLS 亦用 HAC SE。
- **RV level 相關天然偏高**：兩條平滑 rolling RV 序列因共同市場趨勢而相關偏高 → 額外報 **ΔRV 差分相關**作為更嚴格的「同步 vol shock」共動指標。
- **Regime tertile 防呆**：`assert` 各分位非空（K1128 教訓：degenerate tertile）；本處為全樣本描述性分類（非 IS/OOS 外推），不受 K1128 OOS-cutoff 失效問題影響。
- Seed 固定；不手改 JSON。

## 主要發現（含 null / 反直覺）

### 發現 1：實質資產籃並非「一致 cluster」— 子群異質

| 指標 | 值 |
|---|---|
| 7 檔整體平均 pairwise corr（level） | **0.718** |
| 7 檔整體平均 pairwise corr（**ΔRV 差分**） | **0.388** |
| water 子群內部平均 corr | **0.970** |
| timber 子群內部平均 corr | **0.911** |
| farmland 子群內部平均 corr | **0.355** |

- water 與 timber **子群內部高度一致**；但 **farmland(LAND/FPI) 子群內部僅 0.35**，並非緊密 cluster。
- 整體 level 相關 0.72 看似「一致」，但 **ΔRV 差分相關降到 0.39** → 高 level 相關**大半來自共同市場 vol 趨勢，而非同步的短期 vol shock**。把「一致 vol cluster」當賣點是**過度宣稱**。

### 發現 2：高市場波動時 vol **放大**，非脫鉤（反避風港）

SPY 21d RV 三分位 cutoff：q33=0.102，q67=0.155（high/low 各 957 天、mid 956 天）。所有 7 檔在 high 市場波動 regime 下平均 RV 相對 low regime 的比率：

| 資產 | low RV | high RV | high/low 比 | Cohen's d | 非重疊 p |
|---|---|---|---|---|---|
| LAND | 0.216 | 0.344 | 1.59 | 1.11 | 2e-06 |
| FPI | 0.281 | 0.353 | 1.26 | 0.33 | 0.090 (n.s.) |
| WY | 0.190 | 0.370 | 1.95 | 0.97 | 5.8e-05 |
| RYN | 0.185 | 0.320 | 1.73 | 0.86 | 0.0003 |
| PHO | 0.111 | 0.249 | 2.25 | 1.53 | <1e-6 |
| CGW | 0.099 | 0.221 | 2.23 | 1.39 | <1e-6 |
| FIW | 0.117 | 0.249 | 2.13 | 1.47 | <1e-6 |

- **全部 7 檔 high/low 比 > 1**（1.26–2.25）：市場承壓時這些實質資產的 vol **一起放大**，沒有「vol 脫鉤 / 保持穩定」的避風港特性。
- 效果量多數大(d 0.86–1.53)且非重疊 robustness 仍顯著；**唯一例外 FPI**（d=0.33，非重疊 p=0.09 **不顯著**）— 農地 REIT 之一的 vol regime 敏感度弱，屬 idiosyncratic。

### 發現 3：Vol beta 異質 — timber 放大、water 緊貼大盤、farmland idiosyncratic

| 資產 | vol beta | R² | HAC t |
|---|---|---|---|
| LAND | 0.865 | 0.528 | 15.85 |
| FPI | 0.741 | **0.145** | 5.74 |
| WY | **1.452** | 0.669 | 8.80 |
| RYN | **1.169** | 0.625 | 7.09 |
| PHO | 0.921 | **0.900** | 19.89 |
| CGW | 0.842 | **0.851** | 15.53 |
| FIW | 0.895 | **0.876** | 18.49 |

- **timber(WY/RYN) vol beta > 1**：vol 對市場 vol 反應**比大盤更劇烈**（放大器，非緩衝器）。
- **water(PHO/CGW/FIW) beta 略 <1 但 R² 0.85–0.90**：vol 幾乎是**市場 vol 的縮放版**，緊貼大盤、無獨立避險價值。
- **farmland FPI R² 僅 0.14**：vol 與大盤關聯弱，行為 idiosyncratic（呼應發現 2 的弱 regime 敏感度）。所有 HAC t 仍顯著（beta 點估計穩健），但 R² 差異揭示「解釋力」天差地別。
- **具體佐證**：FPI 史上最大單日 log-return 為 **2018-07-11 −39%**（Rota Fortunae 做空報告攻擊，真實公司特定事件），驅動 FPI RV max≈1.87（見 fig1 該年平頂高原）。此極端 vol 事件與市場 vol 完全無關，正是 farmland REIT vol 主要由 idiosyncratic 事件驅動的直接證據。

### 發現 4：通膨 / breakeven / 乾旱 public proxy 只到方向性，沒有正式 safe-haven gate

Public-proxy stress diagnostics 使用 lagged signals 與 next-21-trading-day targets。正式檢定是 63 個 HAC regression cells（3 stress proxy × 7 assets × 3 targets），signal gate 需要 `|t|>=3` 且 Holm-adjusted p<=0.05。

| 指標 | 結果 |
|---|---|
| regression cells | 63 |
| safe-haven gate pass | **0** |
| risk-amplifier gate pass | **0** |
| RV/downside beta < 0 directional cells | 29 |
| RV/downside beta > 0 directional cells | 13 |

分組描述有方向，但不能當正式顯著性宣稱：

- Inflation pressure / breakeven 高分位下，多數資產 next-21d RV 的 high/low ratio < 1；例如 breakeven 21d change 下 7 檔 RV ratio 約 0.75–0.90。但 HAC regression 控制 lagged own RV / SPY RV 後，最強 raw signal 也只到 t≈−2.4，Holm-adjusted p=1.0。
- California drought intensification 高分位下，7 檔 next-21d RV high/low ratio 約 **1.18–1.33**，方向上較像風險放大；但同樣沒有 Holm-surviving regression gate。
- 因此結論只能是：**通膨 / 乾旱 public proxy 對天然資源實質資產的 forward volatility 有混合方向性，但不足以支撐「抗通膨低波動避風港」或「可交易氣候 vol 因子」宣稱。**

## 綜合結論（誠實版）

**「天然資源實質資產 = 低相關避風波動率」的行銷敘事在此 public-proxy diagnostic 下最多只能被描述為方向性不支持，不能升級成交易或顯著 alpha claim**：

- 這一籃**不是**一致 vol cluster（farmland 子群鬆散；level 相關受共同趨勢膨脹，ΔRV 僅 0.39）。
- 高市場波動時 vol **放大而非脫鉤**（全部 high/low 比 > 1）。
- 對大盤 vol：timber **放大**(beta>1)、water **緊貼**(R²≈0.9)、farmland **idiosyncratic**(FPI R²=0.14) — 三子群 vol 行為根本不同，不能當同質「實質資產」一籃看待。
- **唯一帶 idiosyncratic/緩衝色彩的是農地 REIT（尤其 FPI）**：regime 敏感度弱、對大盤 vol 解釋力低。但 farmland 子群內部相關也低(0.35)，兩檔農地 REIT 本身行為就不一致，樣本薄（僅 2 檔），不足以支撐「農地是 vol 避風港」的強宣稱。
- 通膨 / breakeven / California drought public proxy 的正式 gate 全部不過；只可宣稱 **DIRECTIONAL_ONLY**。

## 限制

- **描述性、非因果、非可交易**：所有相關 / regime / beta 皆同期描述，不構成預測或交易訊號。
- **樣本期 2015–2026**：涵蓋 2018Q4、2020 COVID、2022 升息、但未含 2008 GFC；REIT/ETF vol 結構可能隨利率環境改變。
- **子群樣本薄**：farmland 僅 2 檔、timber 僅 2 檔，子群內平均 corr 統計不確定性高。
- **重疊窗口**：RV rolling 窗口導致自相關，標準 t-test p 高估已用 Cohen's d + 非重疊子樣本 + HAC 緩解，但非重疊子樣本 n 較小、檢力下降（FPI 因此轉不顯著也可能部分是檢力問題）。
- **ETF/REIT ≠ 標的實質資產本身**：交易的是**證券化**載體，其 vol 含股市 beta、流動性、折溢價成分，不等於農地/林地/水權現貨的經濟波動。
- **Inflation proxy 不是 surprise**：CPI/PPI 是 FRED current-vintage release-lag proxy，不是 consensus surprise 或 real-time vintage；breakeven 是市場 proxy，含 real-rate / risk-premium 成分。
- **Drought proxy 地理曝險有限**：USDM 使用 California statewide DSCI；它對水資源 ETF、農地/林地證券有直覺，但不是每檔 REIT/ETF 的完整地理營收曝險。

## 文獻與資料脈絡

- Newell and Eves (2023), *Inflation hedging effectiveness of farmland and timberland assets* — 動機：私募/實體 farmland/timberland 的 hedge 敘事未必可直接轉移到上市 REIT/ETF。
- Liu, Hartzell and Hoesli, *International Evidence on Real Estate Securities as an Inflation Hedge* — 動機：listed real-estate securities 不必然比股票更抗通膨。
- Hong, Li and Xu (2019), *Climate Risks and Market Efficiency* — 動機：drought/climate state variables 可能影響自然資源相關現金流風險。
- U.S. Drought Monitor web services — weekly D0-D4 drought category percentages and DSCI-style severity proxy。

## 檔案

- `k1614.py` — 可復現腳本（seed、lag/HAC 註解齊備）
- `k1614_results.json` — 全部真實數字（描述統計、corr matrix、regime 表、vol beta、檢定 t/p + metadata）
- `figures/fig1_rv_timeseries.png` — 10 檔 21d RV 時序
- `figures/fig2_rv_corr_heatmap.png` — 7 檔實質資產 RV 相關熱圖
- `figures/fig3_regime_bar.png` — 各 regime 下實質資產平均 RV bar chart
- `figures/fig4_public_proxy_stress_forward_rv.png` — lagged stress proxy 高/低分組的 next-21d RV ratio（描述性，不是 gate）
- `data/` — yfinance adjusted close、FRED CPI/PPI/T10YIE、USDM California weekly cache
