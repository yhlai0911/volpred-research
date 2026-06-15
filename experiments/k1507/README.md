# K1507 — Returns-only volatility-skew proxy 能否預測 ETF 橫斷面報酬？

## 問題

文獻顯示個股 option volatility smirk / implied lending fee 可能預測後續股票報酬，且高 skew / 高借券費常與後續低報酬相連。本實驗測一個更受限、資料更便宜的版本：

> 若沒有 option IV surface 與 borrow-fee 資料，只用 ETF 歷史報酬做「downside-skew proxy」，能不能在小型 ETF universe 中重現高 skew 次月 underperformance？

## 資料與 proxy

- 資料來源：yfinance adjusted close，`auto_adjust=True`。
- Universe：22 檔流動 ETF：SPY, QQQ, IWM, DIA, EFA, EEM, XLF, XLK, XLE, XLV, XLY, XLP, XLI, XLU, XLB, GLD, TLT, IEF, HYG, LQD, VNQ, USO。
- 樣本：2007-03-31 到 2026-04-30，共 230 個月、5,057 個 ETF-month rows；每月 21-22 檔。
- Proxy：每個月末 t 用過去 63 交易日計算三個 lagged returns-only component，並在當月橫斷面 z-score 後平均：
  - `-realized_skew`：越負偏，proxy 越高。
  - `downside_vol - upside_vol`：下行波動相對上行波動越大，proxy 越高。
  - `left-tail loss`：5% 左尾損失越大，proxy 越高。
- Target：month t+1 的 ETF 月報酬。

這不是 observed option-implied skew，也不是 borrow fee。它只測「returns-only proxy 是否足以替代該 channel」。

## 檢定

1. 每月依 `skew_proxy_z` 排序，top 30% 減 bottom 30% 得 `high_minus_low`。文獻式 underperformance 應該呈現負值且 t < -3。
2. Fama-MacBeth 月度橫斷面迴歸：
   - simple：`next_ret ~ skew_proxy_z`
   - controls：`next_ret ~ skew_proxy_z + realized_vol_z + momentum_21_z`
3. 每月 Spearman rank IC。
4. HAC t-stat + 5,000 次 6-month block bootstrap CI。

所有 feature 都在月末 t 以前形成，target 是 t+1；沒有用 t+1 報酬建 feature。

## 結果

### 1. Tercile spread

| 樣本 | high-minus-low 年化均值 | HAC t | 月均值 bootstrap 95% CI |
|---|---:|---:|---:|
| Full 2007-2026 | -0.81% | -0.23 | [-0.67%, +0.45%] |
| Pre-2018 | -0.53% | -0.10 | [-1.01%, +0.67%] |
| Post-2018 | -1.17% | -0.27 | [-0.74%, +0.65%] |

Full sample 高 proxy 籃次月平均 0.589%，低 proxy 籃 0.656%，方向符合 underperformance，但量級極小、統計上完全不顯著。

### 2. Fama-MacBeth

| 規格 | `skew_proxy_z` 年化係數 | HAC t | 解讀 |
|---|---:|---:|---|
| simple | +0.24% | +0.16 | 無預測力 |
| controls | +1.79% | +1.08 | 方向反而偏正，仍不顯著 |

Rank IC 平均 +0.029，HAC t=1.28，同樣不支持「高 proxy ETF 次月 underperform」。

## Verdict

**NULL。** 在 22 檔 ETF、230 個月資料中，returns-only downside-skew composite 不能複製 option-smirk / borrow-fee 文獻的橫斷面報酬訊號。最合理解讀不是「文獻錯」，而是：

1. ETF 的借券限制遠弱於 hard-to-borrow 個股。
2. 期權 IV skew / lending fee 含有價格、借券供需與限制套利資訊；單靠歷史報酬偏度無法替代。
3. 若要測原始假說，下一版必須用真 options IV surface 或 securities lending / short interest data，而不是 yfinance-only proxy。

## 文獻定位

- Xing, Zhang, and Zhao (2010), *What Does Individual Option Volatility Smirk Tell Us About Future Equity Returns?*, JFQA。
- Muravyev, Pearson, and Pollet (2025), *Why Does Options Market Information Predict Stock Returns?*。
- Ofek, Richardson, and Whitelaw (2004), *Limited Arbitrage and Short Sales Restrictions*, NBER WP 9423。
- Harvey, Liu, and Zhu (2016), *... and the Cross-Section of Expected Returns*, RFS。

## 檔案

- `k1507.py` — 可重跑腳本。
- `k1507_results.json` — 完整 results / config / literature / limitations。
- `k1507_panel.csv` — 月度 panel。
- `figures/k1507_tercile_factor.png` — high/low baskets 與 low-minus-high factor。
- `figures/k1507_sample_spreads.png` — full/pre/post spread。
- `data/*.csv` — yfinance adjusted close cache。

## 審查

Codex self-review：PASS。詳見 `codex_review.md`。主要 caveat 是資料限制：無 options / borrow-fee 真資料，因此結論只是否定 yfinance-only proxy，不否定原始 option-skew 文獻。
