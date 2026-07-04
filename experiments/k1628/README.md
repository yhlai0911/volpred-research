# K1628 — 「黃金真的是股災避風港嗎？」危機期間條件相關性

**投資迷思驗證系列** · task `newroute_gold_safe_haven_myth`

生成時間見 `k1628_results.json` 的 `generated_at_utc`。所有數字均由 `k1628.py` 從本地 SQLite 價格快取重算產生。

## 1. 問題

讀者常把「黃金是避險資產」理解成：股市大跌時，黃金應該明顯上漲或至少不跌。本實驗把這個說法拆成兩個可驗證命題：

1. **文獻定義的 safe haven**：SPY 極端下跌時，GLD 與 SPY 是否不相關或負相關？
2. **讀者直覺的保護力**：SPY 大跌當天，GLD 是否常常收紅、平均是否能抵銷部分跌幅？

本實驗是 empirical descriptive safe-haven test，不是交易策略回測。所有 GLD / SPY 關係都是同日危機共動描述，不宣稱事前可交易訊號。

## 2. 文獻依據

- Baur and Lucey (2010), *Financial Review*, “Is Gold a Hedge or a Safe Haven?”：hedge = 平均不相關/負相關；safe haven = 市場崩跌時不相關/負相關。
- Baur and McDermott (2010), *Journal of Banking & Finance*, “Is gold a safe haven? International evidence”：gold 對美歐股市常有 safe-haven 屬性，但不是所有市場與所有危機都成立。
- Hood and Malik (2013), *Review of Financial Economics*, “Is gold the best hedge and a safe haven under changing stock market volatility?”：gold 可作 weak safe haven，但 VIX 在高波動期通常更強。

## 3. 資料與方法

| 項目 | 設定 |
|---|---|
| 股票 proxy | `SPY` |
| 黃金 proxy | `GLD` |
| 壓力 regime proxy | `^VIX`（只做描述性 regime 分類） |
| 來源 | `data/cache/price_cache.db`, table `price_data` |
| 報酬 | SPY / GLD 各自使用 `adj_close` close-to-close `pct_change()` |
| 樣本 | 2016-01-05 至 2026-07-02，共 2,638 個共同交易日 |
| 隨機程序 | block bootstrap seed=42, block=5, B=2000 |
| 檢定 | Wilson CI、Fisher-z correlation CI、HAC lag=5 mean test、Baur-style quantile interaction regression |

防錯重點：

- `SPY` 與 `GLD` 分別計算日報酬，沒有跨序列 pct_change。
- first-row NaN 由共同 panel drop 掉。
- Same-day alignment 是 safe-haven 文獻定義下的危機共動檢定；程式在 results JSON 明確標註不是預測或交易訊號。

## 4. 核心結果

### 4.1 平均低相關，不代表股災必抗跌

全樣本 SPY-GLD 同日相關只有 **0.075**，GLD 日均報酬 **+0.055%**，收紅率 **53.8%**。這支持「GLD 平常和股票不是高度同向」。

但在股市壓力日，黃金沒有變得更可靠：

| 條件 | n | GLD 收紅率 | GLD 平均日報酬 | SPY-GLD 同日相關 |
|---|---:|---:|---:|---:|
| 全樣本 | 2,638 | 53.8% | +0.055% | +0.075 |
| SPY < 0 | 1,170 | 53.0% | +0.005% | +0.032 |
| SPY < -1% | 290 | 47.9% | +0.025% | +0.103 |
| SPY < -2% | 92 | 45.7% | +0.067% | +0.248 |
| SPY < -3% | 33 | 48.5% | -0.180% | +0.360 |
| VIX 前 10% 且 SPY 下跌 | 154 | 48.1% | -0.059% | +0.137 |

主結論：**黃金可以是低相關分散資產，但不是「股災當天一定上漲」的保險。**

### 4.2 強 safe-haven gate 沒過

本實驗把 strong safe haven 定義為：

> crisis-bin SPY-GLD correlation <= 0 且 GLD conditional mean >= 0

結果：

| Gate | 結果 |
|---|---|
| SPY < -2% | FAIL：GLD 平均報酬略正，但相關 +0.248 |
| SPY < -3% | FAIL：GLD 平均報酬 -0.180%，相關 +0.360 |
| VIX 前 10% 且 SPY 下跌 | FAIL：GLD 平均報酬 -0.059%，相關 +0.137 |

Bootstrap 也顯示不確定性很大：

- `SPY < -2%`：GLD 收紅率 bootstrap 95% CI = **[35.1%, 56.2%]**，相關 CI = **[-0.015, +0.425]**。
- `VIX 前 10% 且 SPY 下跌`：GLD 收紅率 CI = **[39.9%, 56.7%]**，相關 CI = **[-0.060, +0.321]**。

### 4.3 危機 episode 非常不穩定

| Episode | SPY 累積 | GLD 累積 | SPY-GLD corr | SPY 下跌日中 GLD 收紅率 |
|---|---:|---:|---:|---:|
| 2018Q4 sell-off | -13.5% | +7.5% | -0.244 | 69.4% |
| COVID crash | -13.6% | +4.6% | +0.217 | 57.1% |
| 2022 rate-shock bear | -17.7% | -11.1% | +0.102 | 47.4% |
| 2025 April shock | -0.9% | +5.4% | +0.218 | 62.5% |

這是本實驗最重要的機制訊息：**黃金保護力取決於危機類型**。2018Q4 像避風港；2022 升息熊市則和股票一起受傷。

## 5. Verdict

**WEAK_REGIME_DEPENDENT_SAFE_HAVEN_NOT_AUTOMATIC**

一句話：GLD 對 SPY 的平均相關很低，但在 2016-2026 的 SPY 大跌日並沒有穩定負相關；SPY 跌逾 2% 時 GLD 收紅率只有約 **45.7%**、同日相關 **+0.248**，所以「有時能保護」成立，「股災一定抗跌」不成立。

## 6. 限制

1. `GLD` 是黃金 ETF proxy，不是現貨黃金；ETF 交易時段與現貨市場不同。
2. 樣本從 2016 開始，未覆蓋 2008 金融海嘯；這是本地 cache 可用窗口限制。
3. Same-day safe-haven 檢定是描述危機共動，不是可交易預測。
4. `SPY < -3%` 只有 33 天，點估計需保守解讀。
5. VIX regime 使用同日 VIX close，因此只作描述性分類；不作事前訊號。

## 7. 檔案

| 檔案 | 內容 |
|---|---|
| `k1628.py` | 可復現腳本：讀 SQLite → 條件統計 → HAC / bootstrap → 圖表 |
| `k1628_results.json` | 所有結果、metadata、文獻與方法註記 |
| `fig_safe_haven_conditions.png` | 條件壓力日下 GLD 收紅率、平均報酬、SPY-GLD 相關 |
| `fig_rolling_corr_episodes.png` | 60 日 rolling correlation 與危機 episode |

復現：

```bash
uv run python experiments/k1628/k1628.py
```
