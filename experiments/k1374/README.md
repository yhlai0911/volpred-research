# K1374: 台股除息日波動率 — 擴展樣本分析

| Item | Value |
|------|-------|
| Experiment ID | K1374 |
| Title | 台股除息日波動率 — 擴展樣本分析 |
| Status | **PASS** |
| Date | 2026-05-18 |
| Script | k1374.py |
| Results | k1374_results.json |
| Related | K1373 (CONDITIONAL_PASS, 5 tickers) |

---

## Motivation

K1373（CONDITIONAL_PASS）以 5 檔股票（0050、0056、2330、2317、2882）發現除息日波動率邊際顯著（pooled p=0.052, Cohen's d=0.188）。本實驗以 17 檔 TWSE 主要成份股擴展至約 226 個事件（約 K1373 的 2.5 倍），測試以下問題：

1. K1373 的 CONDITIONAL_PASS 能否在更大樣本下升格為 PASS？
2. 哪些板塊的除息日效應最強？
3. 除息旺季（4-9 月）vs 非旺季（10-3 月）有無差異？

台股除息旺季（六月起）即將到來，研究具高時效性。

---

## Method

### Assets（17 檔）

| Ticker | 名稱 | 板塊 | N ex-dates |
|--------|------|------|-----------|
| 0050.TW | 台灣 50 ETF | ETF | 21 |
| 0056.TW | 高股息 ETF | ETF | 18 |
| 2330.TW | 台積電 | Tech | 31 |
| 2317.TW | 鴻海 | Tech | 11 |
| 2454.TW | 聯發科 | Tech | 13 |
| 2412.TW | 中華電 | Industrial | 11 |
| 2882.TW | 國泰金 | Financial | 11 |
| 2881.TW | 富邦金 | Financial | 11 |
| 2886.TW | 兆豐金 | Financial | 11 |
| 2880.TW | 華南金 | Financial | 11 |
| 2891.TW | 中信金 | Financial | 11 |
| 2303.TW | 聯電 | Tech | 11 |
| 2308.TW | 台達電 | Tech | 11 |
| 1301.TW | 台塑 | Industrial | 11 |
| 1303.TW | 南亞 | Industrial | 11 |
| 1216.TW | 統一 | Industrial | 11 |
| 2002.TW | 中鋼 | Industrial | 11 |
| **Total** | | | **226** |

### Data
- Source: yfinance adjusted close + `.dividends` 屬性
- Period: 2015-01-01 to 2025-12-31（~11 年）
- Ex-dates: 外部行事曆（非從報酬推導）

### Volatility Measure
- `|r_t| = |log(P_t / P_{t-1})|`（absolute log return）

### Event Study Design
- **t=0**: 除息日（若落在非交易日，取次個交易日）
- **Pre-window**: t ∈ [-10, -1]
- **Post-window**: t ∈ [+1, +10]
- **Control days**: 與任何除息日最小距離 > 10 個交易日的所有其他交易日

### Statistical Tests
1. **Pooled Welch t-test** (primary): ex-date |r| vs control days（雙尾）
2. **Mann-Whitney U**: 非參數版
3. **Cohen's d**: (mean_ex − mean_ctrl) / pooled std
4. **FDR correction** (per-ticker): Benjamini-Hochberg
5. **Robustness**: 排除最高 d 的兩檔（2412.TW + 2886.TW），驗證非 outlier 驅動

---

## Lookahead Check

- **CLEAN**: Ex-dates 來自 yfinance `.dividends` 外部行事曆，非從報酬序列推導
- 本實驗是描述性事件研究（不是預測模型），`signal.shift(1)` 不適用
- `np.random.seed(42)` 設定於腳本頂層

---

## Key Results

### Pooled Statistics (PRIMARY)

| Test | Statistic | p-value | Interpretation |
|------|-----------|---------|----------------|
| Welch t-test (ex vs ctrl) | t=4.019 | **p=0.0001** | 顯著（p<0.001）|
| Mann-Whitney U | U=5,505,349 | **p<0.001** | 顯著 |
| Cohen's d | **0.305** | — | 小-中等效果量 |

- N ex events: **226**（17 tickers，2015-2025）
- N control obs: **40,729**
- Mean ex \|r\|: **0.01324** vs ctrl: **0.00986**（ratio = **1.342**）

升幅顯著：K1373 pooled p=0.052 → K1374 pooled p=0.0001；Cohen's d=0.188 → 0.305。

### Robustness Check

排除最高 d 的兩檔（2412.TW d=1.633 + 2886.TW d=1.245），仍有 204 個事件：

| Test | Stat | p-value | Verdict |
|------|------|---------|---------|
| Welch t-test | t=2.985 | p=0.003 | PASS |
| Cohen's d | 0.238 | — | > 0.20 |

**結果非 outlier 股票驅動。**

### Sector Cohen's d

| 板塊 | Cohen's d | N ex events | 解讀 |
|------|-----------|------------|------|
| Industrial | **0.579** | 55 | 最強（石化、電信、鋼鐵）|
| Financial | **0.520** | 55 | 金融股效應顯著 |
| ETF | 0.187 | 39 | 小效果（分散化稀釋）|
| Tech | 0.090 | 77 | 最弱（科技股波動背景噪音大）|

工業股與金融股板塊效應最為明顯；科技股因背景波動率高，除息效果相對淡化。

### Per-Ticker Highlights（FDR corrected）

| Ticker | Cohen's d | p (raw) | p (BH) | FDR pass |
|--------|-----------|---------|---------|----------|
| 2412.TW | 1.633 | 0.011 | 0.096 | No |
| 2886.TW | **1.245** | 0.001 | **0.020** | **Yes** |
| 2880.TW | 0.908 | 0.084 | 0.287 | No |
| 1301.TW | 0.837 | 0.128 | 0.362 | No |
| 1303.TW | 0.708 | 0.311 | 0.662 | No |

FDR 校正後只有 2886.TW（兆豐金）個別顯著，其餘個股因樣本量小（n=11）無法單獨支撐宣稱。主要結論依賴 **pooled** 分析。

### Seasonal Analysis

| 季節 | N events | Cohen's d | 解讀 |
|------|---------|-----------|------|
| 旺季 Apr-Sep | **188** | **0.346** | 主要除息旺季效應更強 |
| 淡季 Oct-Mar | 38 | 0.105 | 效應明顯較弱 |

台灣高股息文化集中在 7-9 月除息 → 旺季 d=0.346 >> 淡季 d=0.105，季節性明確。

---

## Figures

1. `k1374_event_study_profile.png` — t=-10 到 +10 的平均 \|r\| profile vs 控制日水平線
2. `k1374_cohens_d_by_sector.png` — 各板塊的 Cohen's d 條形圖
3. `k1374_pooled_distribution.png` — ex-date vs control \|r\| 分佈比較

---

## Verdict: PASS

**主要結論**：

- **Pooled**: Welch t=4.019, p=0.0001, Cohen's d=0.305 — 兩個判準均達標（p<0.05 且 d>0.20）
- **Robustness**: 排除最高 d 的兩檔仍 PASS（p=0.003, d=0.238）
- **K1373 升格確認**：CONDITIONAL_PASS（p=0.052, d=0.188）→ PASS（p=0.0001, d=0.305）
- **板塊異質性**：工業/金融 > ETF >> 科技
- **季節性**：旺季（Apr-Sep）效應 d=0.346，淡季 d=0.105 — 旺季更明顯

**誠實備注**：
- 個股層級僅 2886.TW 通過 FDR 校正（其他 16 檔個別不顯著），主要結論來自 pooled
- 台積電（2330）d=0.101 幾乎無效應 — 高背景波動率股票除息效應稀釋
- 2412.TW（中華電）d=1.633 乃因該股波動率極低（mean |r|=0.00479），少數大幅擺動日效果顯著但個別樣本僅 11 事件

---

## Next Steps

- 加入 GARCH 條件波動率標準化後的條件事件效應（conditional event study）
- 細化 pre-window：t=-5 到 -1（最後一週效應是否更強於 t=-10 到 -6？）
- 延伸至 2012-2014（TAIFEX 更長樣本），增加金融板塊事件數
- 板塊內同質性驗證：金融股 5 檔是否可合併宣稱「金融股除息效應」

---

## Files

```
experiments/k1374/
├── README.md                          ← this file
├── k1374.py                           ← experiment script
├── k1374_results.json                 ← full results
├── k1374_event_study_profile.png      ← t=-10 to +10 profile
├── k1374_cohens_d_by_sector.png       ← sector Cohen's d bar chart
└── k1374_pooled_distribution.png      ← pooled box + density plot
```
