# K1373: 台股除權息日波動率事件研究

| Item | Value |
|------|-------|
| Experiment ID | K1373 |
| Title | 台股除權息日波動率事件研究 |
| Status | CONDITIONAL_PASS |
| Date | 2026-05-18 |
| Script | k1373.py |
| Results | k1373_results.json |

---

## Research Question

台股個股與 ETF 的除權息日前後，市場波動率是否出現系統性改變？具體：
1. 除權息日（t=0）的波動率是否顯著高於控制日？
2. 除權息前（t=-10 到 t=-1）是否出現「填息期待」型波動率堆積？
3. 除權息後（t=+1 到 +10）是否出現回歸？

---

## Motivation

- `research_program.md` 明確列出「除權息研究方向（用戶指定）」作為優先研究方向
- 類比 K498（財報公告事件研究），但除權息是台灣高股息文化特有的年度事件
- 台股除權息旺季（六月起）即將到來，研究具時效性
- 本實驗為此方向首個正式 K 實驗

---

## Method

### Assets
| Ticker | Name |
|--------|------|
| 0050.TW | 台灣 50 ETF（大盤代表）|
| 0056.TW | 高股息 ETF（高股息文化代表）|
| 2330.TW | 台積電（科技龍頭）|
| 2317.TW | 鴻海（製造業代表）|
| 2882.TW | 國泰金（金融股代表）|

### Data
- Source: yfinance（adjusted close prices + `.dividends` 屬性）
- Period: 2015-01-01 to 2025-12-31（~11 年）
- Ex-dates 來源: `yfinance.Ticker(ticker).dividends` 的 index（外部行事曆，非由報酬推導）

### Volatility Measure
- `|r_t| = |log(P_t / P_{t-1})|`（absolute log return）

### Event Study Design
- **t=0**: 除權息日（若落在非交易日，取次個交易日）
- **Pre-window**: t ∈ [-10, -1]
- **Post-window**: t ∈ [+1, +10]
- **Control days**: min distance > 10 交易日與任何除權息日的所有非事件日

### Statistical Tests
1. **Welch's t-test**: ex-date |r| vs control days（雙尾）
2. **Mann-Whitney U**: 非參數版，same comparison
3. **Pre vs Control**: pre-window |r| 是否顯著高於控制日
4. **Post vs Control**: post-window |r| 是否顯著高於控制日
5. **Cohen's d**: 效果量（(mean_ex − mean_ctrl) / pooled std）

---

## Lookahead Check

- **CLEAN**: Ex-dates 來自 yfinance .dividends 外部行事曆，非從報酬序列推導
- 不做預測：本實驗是描述性事件研究，測量已知事件日的同期報酬
- `signal.shift(1)` 不適用於事件研究設計（不是預測模型）
- `np.random.seed(42)` 設定於腳本頂層（可重現性）

---

## Key Results

### Event Coverage

| Ticker | N ex-dates | Ex obs | Pre obs | Post obs | Control obs |
|--------|-----------|--------|---------|----------|-------------|
| 0050.TW | 21 | 21 | 205 | 205 | 2,244 |
| 0056.TW | 18 | 18 | 180 | 180 | 2,302 |
| 2330.TW | 31 | 31 | 310 | 310 | 2,023 |
| 2317.TW | 11 | 11 | 110 | 110 | 2,443 |
| 2882.TW | 11 | 11 | 110 | 110 | 2,443 |
| **Pooled** | **92** | **92** | **915** | **915** | **11,455** |

### Mean |r| by Window

| Ticker | Pre | Ex-date | Post | Control | Ex/Ctrl ratio |
|--------|-----|---------|------|---------|--------------|
| 0050.TW | 0.00798 | 0.00970 | 0.00834 | 0.00811 | 1.196 |
| 0056.TW | 0.00708 | 0.00665 | 0.00648 | 0.00565 | 1.177 |
| 2330.TW | 0.01284 | 0.01346 | 0.01189 | 0.01226 | 1.098 |
| 2317.TW | 0.01363 | 0.01318 | 0.01102 | 0.01170 | 1.127 |
| 2882.TW | 0.01067 | 0.01508 | 0.01046 | 0.00969 | 1.556 |
| **Pooled** | **0.01045** | **0.01143** | **0.00976** | **0.00945** | **1.209** |

### Statistical Tests — Pooled

| Test | Statistic | p-value | Interpretation |
|------|-----------|---------|----------------|
| Welch t-test (ex vs ctrl) | t=1.967 | p=0.0521 | 邊緣顯著（p≈0.052）|
| Mann-Whitney U (ex vs ctrl) | U=614,825 | p=0.0058 | 顯著（p<0.01）|
| Cohen's d | 0.188 | — | 小效果量 |
| t-test (pre vs ctrl) | t=2.867 | p=0.0042 | 顯著（p<0.01）—前置波動堆積 |
| t-test (post vs ctrl) | t=0.909 | p=0.3637 | 不顯著 |

### Per-Asset Highlights

| Ticker | Ex vs Ctrl t-stat | p-value | Cohen's d | MW p |
|--------|-------------------|---------|-----------|------|
| 0050.TW | 0.690 | 0.498 | 0.184 | 0.635 |
| 0056.TW | 0.703 | 0.491 | 0.159 | 0.458 |
| 2330.TW | 0.625 | 0.537 | 0.101 | 0.298 |
| 2317.TW | 0.644 | 0.533 | 0.117 | 0.150 |
| 2882.TW | 1.951 | 0.079 | 0.517 | **0.019** |

國泰金（2882.TW）是唯一 Mann-Whitney 顯著的個股（p=0.019），Cohen's d=0.517 屬中等效果量。

---

## Verdict: CONDITIONAL_PASS

**Pooled 主要結論**：

- **Ex-date 波動率**：高於控制日約 20.9%（0.01143 vs 0.00945）
- **t-test**: p=0.052（邊緣顯著，剛好過 5% 邊界）
- **Mann-Whitney**: p=0.0058（非參數檢定顯著，更穩健）
- **Pre-window 效果最強**：pooled t-test pre vs control p=0.0042（前置波動堆積顯著）
- **Post-window 不顯著**：p=0.364（無明顯回歸效應）

**解讀**：台股除權息前的「期待不確定性」（填息能否達成）確實產生統計上可辨識的波動率堆積（pre-window 顯著），但 ex-date 當天的波動放大程度比前期更弱（僅邊緣顯著）。事後無顯著回歸效應。結果在非參數檢定下較強（MW p=0.006），parametric t-test 邊緣（p=0.052）— 可能因分配右偏。整體屬小效果（Cohen's d=0.188），個股間異質性大（2882.TW 有中等效果，其他 4 個效果不顯著）。

**誠實備注**：
- N=92 events 略小，個股樣本尤其小（最少 11 events）
- 單一個股（2882.TW）Mann-Whitney 顯著但 t-test 邊緣，整體仍受樣本量限制
- 結論強度：「有可識別的 pre-window 波動堆積，ex-date 效果邊緣顯著」— 需更多資產或更長樣本驗證

---

## Next Steps

- 擴展至更多高股息個股（2412.TW 中華電、6505.TW 台塑化等），提高事件數
- 分層分析：高股息 vs 低股息個股、金融股 vs 科技股
- 考慮 GARCH 控制背景波動率後的條件事件效應（conditional event study）
- 細化 pre-window：最後 5 天（t=-5 到 -1）vs 早期（t=-10 到 -6）

---

## Files

```
experiments/k1373/
├── README.md              ← this file
├── k1373.py               ← experiment script
└── k1373_results.json     ← full results
```
