# K1629 - 美股開盤第一小時真的最危險嗎？

## 研究問題

讀者常聽到一句市場經驗法則：「美股開盤第一個小時波動最大，最危險。」

K1629 用本地 SPY 5-minute 快照把交易日切成三段，檢查這句話的兩個版本：

1. 平均而言，開盤 60 分鐘的 realized volatility 強度是否最高？
2. 尾部風險，也就是最大的 5-minute 波動或負向跳動，是否也集中在開盤？

## 差異化

這不是預測模型，也不是交易策略。既有 VolPred 研究較多討論隔夜/日內報酬分解、HAR-RV 預測與日內 shape 是否改善次日 RV；K1629 改成讀者可理解的「同一天內哪個時段比較危險」。

相關背景：

- `research_intraday_garch_vs_har_rv_rv`：SPY 2026 5-minute pilot，intraday-shape 對次日 RV 預測沒有增量，且樣本不足 252 OOS。
- `K1613`：noise-robust realized measures，SPY 5-minute 只作短樣本 diagnostic。
- `K545`：用 daily OHLC 拆 overnight / intraday，討論 time-of-day 與 VT rebalancing，但不是 5-minute 分時段風險。

## 文獻基礎

- Andersen and Bollerslev (1997), Journal of Empirical Finance：日內 volatility periodicity 會強烈影響高頻報酬動態。
- Madhavan, Richardson, and Roomans (1997), Review of Financial Studies：開盤附近包含資訊不對稱、price discovery 與交易摩擦。
- Engle and Sokalska (2012), Journal of Financial Econometrics：將日內 volatility 拆成 daily、diurnal、stochastic intraday components。
- Harris (1986), Journal of Financial Economics：早期 transaction data 顯示 intraday return patterns，尤其開盤附近。

## 數據

- 來源：本地 `data/intraday/SPY_5min_YYYY-MM-DD.csv`
- 標的：SPY
- 原始檔案：117 個交易日
- 完整 regular-session filter 後：114 個交易日
- 期間：2026-01-14 至 2026-07-02
- 5-minute bars：8,889
- 排除日：3 天，原因為當日本地快照不完整或開始/結束時間不完整

## 方法

1. 讀取本地 yfinance 5-minute OHLCV CSV，不下載 live data。
2. 將 UTC timestamp 轉成 `America/New_York`。
3. 只保留完整 regular session：至少 75 根 bar，第一根不晚於 09:35，最後一根不早於 15:55。
4. 每根 5-minute bar 報酬使用 `log(Close/Open)`。
5. 分段：
   - `open_60`: 09:30 <= bar start < 10:30
   - `midday`: 10:30 <= bar start < 15:00
   - `close_60`: 15:00 <= bar start < 16:00
6. 主指標：segment RV per bar / full-day RV per bar。這避免 midday 因為時間長而機械性擁有較高 raw RV。
7. 檢定：
   - 日層級 paired difference，用 Newey-West HAC lag=5 檢定 mean difference。
   - seed=42、5,000 次 day-level bootstrap CI。
   - tail event 使用全樣本 5-minute absolute return 95th percentile 與 negative return 5th percentile；比例 CI 用 Wilson 與 day-cluster bootstrap。

## 結果

Verdict: `SUPPORTS_FIRST_HOUR_HIGHEST_ON_AVERAGE_LIMITED_SAMPLE`

一句話：

> 在 114 個完整 SPY 5-min 交易日中，開盤第一小時的每根 5-min RV 強度約為全天平均的 2.13 倍，且 92/114 天為三段最高；因此「開盤平均最震」成立，但「每天都最危險」不成立。

核心數字：

| 時段 | 平均 RV share | 每根 5-min RV 強度 / 全日平均 | 最高強度天數 | top 5% absolute move rate | worst 5% negative move rate |
|---|---:|---:|---:|---:|---:|
| 開盤 09:30-10:30 | 32.8% | 2.13x | 92/114 | 12.5% | 11.5% |
| 盤中 10:30-15:00 | 55.4% | 0.80x | 11/114 | 3.8% | 4.0% |
| 收盤 15:00-16:00 | 11.8% | 0.77x | 11/114 | 3.1% | 3.2% |

Paired tests：

- open minus midday relative intensity：mean diff `+1.328`，HAC t `13.45`，bootstrap 95% CI `[1.126, 1.535]`。
- open minus close relative intensity：mean diff `+1.361`，HAC t `13.23`，bootstrap 95% CI `[1.142, 1.577]`。
- close minus midday relative intensity：mean diff `-0.034`，HAC t `-0.73`，bootstrap 95% CI `[-0.144, 0.084]`。

Tail risk：

- 5-minute absolute tail threshold：約 `17.0 bp`。
- 5-minute negative tail threshold：約 `-13.0 bp`。
- 開盤 absolute-tail rate 比收盤高 `+9.43 pp`，day-cluster bootstrap 95% CI `[+7.09 pp, +11.99 pp]`。
- 開盤 negative-tail rate 比收盤高 `+8.26 pp`，day-cluster bootstrap 95% CI `[+6.07 pp, +10.60 pp]`。

## 解讀

這個實驗支持「平均而言，開盤第一小時最震」這個版本。開盤附近集中隔夜資訊消化、訂單不平衡、price discovery 與流動性重新排列，符合文獻對日內週期與開盤微結構的描述。

但它不支持「每天都最危險」的絕對說法。開盤是三段中最高 RV intensity 的比例為 80.7%，最大單根 5-minute move 出現在開盤的比例為 55.3%；也就是說，仍有不少交易日的最大單根波動發生在盤中或收盤。

## 局限

- 本地 SPY 5-minute cache 只涵蓋 2026-01-14 至 2026-07-02，短樣本，不是長歷史 paper-grade inference。
- 這是描述性風險切片，不是交易策略；沒有估計可交易性、滑價、bid-ask spread 或 transaction cost。
- Pooled 5-minute tail event 不是完全獨立樣本，因此結果同時提供 day-cluster bootstrap CI。
- 結論只適用於 SPY local 2026 snapshot；若要正式化，需擴充更長 SPY 5-minute archive 或跨 ETF 重驗。

## 重跑

```bash
uv run python experiments/k1629/k1629.py
```

主要輸出：

- `experiments/k1629/k1629_results.json`
- `experiments/k1629/fig_segment_rv_intensity.png`
- `experiments/k1629/fig_daily_intensity_distribution.png`
- `experiments/k1629/fig_tail_risk_by_segment.png`
