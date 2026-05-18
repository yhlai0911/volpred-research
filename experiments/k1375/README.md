# K1375: 高股息 ETF 除息日波動率事件研究

| Item | Value |
|------|-------|
| Experiment ID | K1375 |
| Title | 高股息 ETF（0056 / 00878 / 00919）除息日波動率事件研究 |
| Status | **NULL** |
| Date | 2026-05-18 |
| Script | k1375.py |
| Results | k1375_results.json |
| Related | K1373 (CONDITIONAL_PASS, 5 tickers), K1374 (PASS, 17 TWSE stocks, peak-season d=0.305) |

---

## Motivation

K1374 以 17 檔台股個股發現除息日波動率在旺季（Apr-Sep）有顯著效應（Cohen's d=0.305）。本實驗轉向三檔**高股息 ETF**（0056、00878、00919），問題：ETF 結構（多成份股分散）是否會弱化個股層級觀察到的效應？

研究動機：
1. 投資人持有高股息 ETF 主要為配息收益，關心除息日前後的操作時機
2. ETF 除息日前後是否有 vol spike 值得量化
3. 與 K1374 個股結果的對比本身即是研究貢獻

---

## Method

| 項目 | 設定 |
|------|------|
| 樣本 | 0056.TW (2008+, 21 events)、00878.TW (2020+, 22 events)、00919.TW (2022+, 12 events) |
| 波動率代理 | 日絕對報酬 \|r_t\| |
| 事件定義 | yfinance `.dividends` ex-date（外部日曆，非 return series 推算）|
| 控制組 | 距任意除息日 ≥10 交易日的 non-event 交易日 |
| 主要檢定 | Welch t-test（T=0 vs control）+ Cohen's d (pooled SD) |
| 穩健性 | Bootstrap 2000 rep 95% CI |
| Profile | 事件窗格 \[-10, +10\] 平均 \|return\| |
| Seed | `np.random.seed(42)` + `np.random.default_rng(42)` |

**Lookahead 說明**：純事件研究設計，ex-dates 來自外部日曆，不從報酬序列推算，無前視偏誤。`signal.shift(1)` 僅適用於預測模型，本實驗不適用。

---

## Results

| ETF | 頻率 | n events | Cohen's d | p-value | 顯著 |
|-----|------|----------|-----------|---------|------|
| 0056.TW | 年配 | 21 | -0.015 | 0.927 | ✗ |
| 00878.TW | 季配 | 22 | +0.343 | 0.179 | ✗ |
| 00919.TW | 月配 | 12 | -0.147 | 0.285 | ✗ |
| **POOLED** | — | **55** | **+0.055** | **0.617** | **✗** |

K1374 基準（個股峰季 d）: 0.305

---

## Interpretation

**全面 NULL**，高股息 ETF 除息日無顯著波動率提升：

1. **ETF 分散效應**：ETF 持有多檔個股，個股除息日的特有風險在組合層級被分散。K1374 個股的 d=0.305 在 ETF 層級縮至 d=0.055。

2. **00878 邊際**（d=0.343, p=0.179）：方向性一致，但 22 事件樣本對 d≈0.34 的 80% power 需約 68 事件。資料不足以確認，待後續（00878 每季配，約 2028 年可累積 ≈32 事件）。

3. **研究含意**：高股息 ETF 投資人除息日前後**無需擔心特別的 vol spike**，執行成本無顯著上升。個股與 ETF 在此現象上存在結構性差異。

---

## Contrast with K1374

| 指標 | K1374（個股）| K1375（ETF）|
|------|-------------|------------|
| 樣本數（events）| 226 | 55 |
| 峰季 Cohen's d | 0.305 | N/A (pooled d=0.055) |
| 顯著 p<0.05 | ✓ | ✗ |
| 機制 | 個股特有風險 | 被組合分散 |

---

## Limitations

1. **小樣本**：55 total events（尤其 00919 僅 12 events）統計力有限
2. **時間段短**：00878（2020+）/ 00919（2022+）未覆蓋完整市場周期
3. **未控制市場 regime**：未做 season-matched 分析（樣本太小）

---

## Code Review

Manual review (2026-05-18):
- Lookahead: ✓ 無前視（外部日曆）
- 控制組: ✓ 10 trading day exclusion，與 K1374 一致
- Cohen's d: ✓ pooled SD 公式正確
- Bootstrap: ✓ `np.random.default_rng(42)` fixed seed
- Codex working-tree review: 未直接針對 K1375 — 未發現問題

**Code verdict: CONDITIONAL_PASS**
