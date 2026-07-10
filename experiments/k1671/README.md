# K1671 — 量先價行 / 爆量長黑是出貨：成交量能否預測隔日方向

## 定位

這是一個 **stale backlog closure / independent replication**。同題已由 K1659、K1667 做過，knowledge 也已有結論；K1671 的目的不是把重複題包裝成新發現，而是用更嚴格的成交量門檻與更大的標的池，驗證能否關閉 `research_program.md` 仍未勾選的迷思題。

差異化：

- K1659：4 資產、跨市場聚合、經濟價值、grid robustness。
- K1667：5 資產，加入 2317.TW，細拆「量先價行」與「爆量長黑」。
- K1671：9 資產（ETF + 美股 megacap + 台股個股），成交量門檻改為 `volume_t > 2 × previous_20d_avg_volume`，即 rolling mean 明確 `.shift(1)`；事件訊號再 `signal.shift(1)` 預測隔日報酬。

## 文獻

- Campbell, Grossman and Wang (1993), *Trading Volume and Serial Correlation in Stock Returns* — 高成交量下報酬自相關傾向下降，常見於反轉而非無條件延續。
- Gervais, Kaniel and Mingelgrin (2001), *The High-Volume Return Premium* — high-volume return premium 偏中期/可見度機制，不能直接改寫成隔日必漲。
- Llorente, Michaely, Saar and Wang (2002), *Dynamic Volume-Return Relation of Individual Stocks* — 成交量與報酬延續/反轉取決於資訊交易 vs 風險分擔交易，沒有普世單一方向。

## 資料與樣本

來源：`yfinance` daily OHLCV，快取在 `data/`。報酬用 adjusted close；0050.TW 用 `clean_tw50_data` 處理台灣 50 split artifact。

| ticker | 期間 | n_days | 爆量日 | 爆量長黑 |
|---|---:|---:|---:|---:|
| SPY | 2005-01-04 至 2026-07-09 | 5,411 | 126 | 59 |
| QQQ | 2005-01-04 至 2026-07-09 | 5,411 | 120 | 67 |
| IWM | 2005-01-04 至 2026-07-09 | 5,411 | 109 | 52 |
| AAPL | 2005-01-04 至 2026-07-09 | 5,411 | 163 | 59 |
| MSFT | 2005-01-04 至 2026-07-09 | 5,411 | 158 | 51 |
| NVDA | 2005-01-04 至 2026-07-09 | 5,411 | 193 | 70 |
| 0050.TW | 2009-01-06 至 2026-07-08 | 4,269 | 354 | 106 |
| 2330.TW | 2005-01-04 至 2026-07-09 | 5,260 | 228 | 77 |
| 2317.TW | 2005-01-04 至 2026-07-09 | 5,239 | 293 | 91 |

## 方法

- 爆量：`volume_t > 2.0 × rolling_mean(volume, 20).shift(1)_t`。
- 爆量長黑：爆量且 `ret_t <= -1.5%`。
- Lookahead policy：訊號在第 t 日收盤後形成，程式用 `signal.shift(1)` 對齊第 t+1 日報酬。
- Per-asset primary：條件命中率 vs 無條件 baseline 的 two-proportion z / binomial diagnostic，並用 circular block bootstrap（block=5, reps=5000, seed=42）估計 `E[r|signal] - E[r]` 的 CI。
- 多重檢定：18 個 primary cells 做 BH-FDR。
- Pooled diagnostic：先按日期聚合 cross-asset 訊號隔日報酬，再做 HAC(Newey-West, lag=5)，不把 asset-day 當 iid。
- 經濟價值：事件後持有一天，5 bps 單向交易成本；比較全期等權 buy-and-hold。

## 結果

### A. 「量先價行」：部分成立，但不是普世鐵律

18 個 primary cells 中，只有 **1 個** myth-consistent cell 通過 BH 5%：2317.TW 爆量後隔日上漲。

- 2317.TW：n=293，隔日上漲率相對無條件 baseline **+9.53pp**，隔日均報酬差 **+0.522%**，bootstrap 95% CI `[+0.229%, +0.845%]`，BH q=0.0265。
- 2330.TW 有 raw 正向訊號：均報酬差 **+0.295%**，CI `[+0.027%, +0.566%]`，但 two-prop p=0.0486 經 18 格 BH 後 q=0.322，不能當正式顯著格。
- SPY / QQQ / IWM 與美股 megacap 沒有一致顯著的隔日上漲優勢。
- Date-level pooled diagnostic 為正：平均 **+0.293%**，HAC t=4.10, p=4.17e-5。這支持「某些資產/事件日有 attention drift」，但 pooled 是 diagnostic，不取代 per-asset + FDR primary。
- 事件後做多策略 Sharpe=0.718，低於全期等權 buy-and-hold Sharpe=1.150；因此它不是可直接替代長期持有的單一交易規則。

解讀：量先價行不是完全假的，但它比較像 **個股 attention / 資訊到達的資產依賴現象**，不是「看到爆量就隔日必漲」的普世法則。

### B. 「爆量長黑是出貨，隔日續跌」：再次被否定

- 9 資產沒有任何一個通過「隔日續跌」primary support。
- 方向反而偏相反：pooled diagnostic 的 raw next-day return 是 **+0.344%**；以「續跌」方向取 signed return 後為 **-0.344%**，HAC t=-2.17, p=0.030。
- 爆量長黑後隔日放空策略 Sharpe=-0.551，最大回撤 -89.0%。把這條口訣拿來做隔日放空規則，結果很差。

## Verdict

`PARTIAL_FOR_VOLUME_LEADS_PRICE__FALSE_FOR_BLACK_CANDLE_DISTRIBUTION`

K1671 對 K1659/K1667 的結論是修正而非推翻：

- 「量先價行」有資產依賴的部分支持，尤其台股個股；不可說完全無效，也不可說普世成立。
- 「爆量長黑是出貨、隔日續跌」再次不成立；若要交易，放空版本明顯失敗。

## 檔案

- `k1671.py` — 主腳本；含 `rolling(...).shift(1)`、`signal.shift(1)`、seed=42、atomic JSON write。
- `k1671_results.json` — 全部統計結果。
- `figs/k1671_hit_rates.png` — 條件命中率 vs 無條件 baseline。
- `figs/k1671_strategy_equity.png` — 兩個迷思策略淨值。
- `codex_review.md` — Codex primary path 方法論審查。

## 限制

- yfinance 日資料無法分辨成交量來自資訊交易、避險交易或再平衡交易。
- 台股與美股交易時區不同，但本實驗只測各自標的自身的 next local trading day，不做跨市場 lead-lag。
- Pooled diagnostic 不應取代 per-asset primary；它只回答「事件日期平均是否有共同方向」。
