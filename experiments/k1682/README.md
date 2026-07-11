# K1682 — 跨交易所日收盤價離散，能否預測 BTC / ETH 短期風險？

> 狀態：完整執行、cache 重現與獨立數字驗證均已完成。數字以 `k1682_results.json` 為準。

## Data & Methodology

- **方法論類型**：empirical proxy diagnostic；不是因果研究，也不是可交易套利回測。
- **資料來源**：Binance、Coinbase、Kraken 官方 public REST API 的 UTC 日頻 completed OHLCV candles。Kraken 最後一列固定是未完成 candle，程式無條件丟棄；三所以 exact UTC date inner join，不補值。
- **資產**：BTC 與 ETH。Binance 為 USDT 報價，先乘同 UTC 日 Coinbase `USDT-USD` close 轉成 USD，再與 Coinbase / Kraken USD close 比較。
- **主 proxy**：三所 `log(close)` 的每日橫斷面標準差（basis points）。另報未校正 native-quote dispersion 與 Coinbase–Kraken USD-only dispersion。
- **理想資料與偏誤**：理想量是同一瞬間、可成交規模下的跨所 bid/ask arbitrage gap；日 close 只是各日桶最後成交價，沒有 quote、depth、fee、latency。因此本文只能稱「日收盤價離散 / fragmentation proxy」。
- **風險 target**：跨所 USD-normalized composite close 的 close-to-close `r²`（h=1）及未來五日 `r²` 合計（h=5）；這是 noisy variance proxy，不是 intraday realized volatility。左尾用 h 日累積報酬的 5% quantile pinball loss。

## Motivation and differentiation

Makarov and Schoar (2020) 顯示 crypto 跨所價差會持續且受場地特有訂單流影響；Hautsch, Scheuch, and Voigt (2024) 說明 settlement latency 會形成非零套利邊界。這些文獻支持「市場碎片化可能與風險狀態同時變動」，但**沒有機械地保證昨日離散能預測明日波動**，後者必須 OOS 檢驗。

本題與 K1625 正交：K1625 用單一 Binance perpetual funding 壓力，只有 BTC h=5 一格較強、ETH 不複現；K1682 改測 spot 跨所 close dispersion，並要求 BTC / ETH 跨資產複現。K1652 提醒 basis 類 proxy 即使改善部分 QLIKE，也不能自動升格為 price discovery。

## Timing and lookahead policy

程式明寫所有訊號與 baseline controls 的 `.shift(1)`。第 t 日預測只使用 t−1 以前資訊。更重要的是，forward target 會重疊：對 forecast origin `i`、horizon `h`，訓練列 `j` 只有在 `j + h < i` 時才准進入估計。這道 embargo 防止 h=5 的 training tail 偷看到 forecast window。

所有 rolling z-score 先以當時可得歷史計算，再 lag 到 forecast date；baseline 與 augmented 模型使用完全相同的日期、target、refit 與 embargo。

## Models, tests, and pre-registered gate

- **RV baseline**：HAR-type 日／週／月 lagged log-r² controls。
- **RV augmented**：baseline + lagged USD-normalized dispersion。
- **Left-tail baseline / augmented**：相同 features 的 expanding 5% QuantReg；以 pinball loss 評分。
- **OOS**：至少 252 個 forecast observations；RV 用 QLIKE 主評分，tail 用 pinball。兩者皆報 horizon-specific Newey-West + HLN DM，並以專案保守門檻 `|t| > 3` 判讀。
- **Nested-model 補充**：RV 另報 Clark–West one-sided nested-MSPE diagnostic；正式經濟 loss 結論仍以 QLIKE DM 為準。
- **多重檢定**：BTC / ETH × h=1 / h=5 × RV / tail，共八格一次做 Benjamini–Hochberg FDR。不得只修正看起來顯著的格子。
- **通過**：loss improvement > 0、HLN-DM t < −3、BH q < 0.05。跨資產 signal candidate 至少要 BTC 與 ETH 都各有一格通過。

Volume drought 只用各交易所 OHLCV volume 的 rolling z-score 作 secondary diagnostic；沒有 order-book depth，不能寫成 liquidity 可交易訊號。

## Results

三所共同 completed UTC 日為 **720 日**（2024-07-21 至
2026-07-10）；BTC 與 ETH 使用完全相同的日期範圍。USD-normalized
close dispersion 的樣本平均分別為 BTC **1.1442 bp**、ETH **1.1967
bp**。因 rolling features、252 日初始訓練窗與 forward-label embargo，
各主格 OOS 為 h=1 **407 筆**、h=5 **399 筆**。

| 資產 | h | outcome | baseline loss | augmented loss | 改善率 | HLN-DM t | BH q | 通過 |
|---|---:|---|---:|---:|---:|---:|---:|---|
| BTC | 1 | RV QLIKE | 1.638202 | 1.683168 | -2.7448% | +1.3790 | 0.3875 | 否 |
| BTC | 1 | 5% tail pinball | 0.00267356 | 0.00266358 | +0.3734% | -0.3063 | 0.8328 | 否 |
| BTC | 5 | RV QLIKE | 0.463721 | 0.464206 | -0.1047% | +0.7126 | 0.7624 | 否 |
| BTC | 5 | 5% tail pinball | 0.00631318 | 0.00643625 | -1.9494% | +1.9063 | 0.3875 | 否 |
| ETH | 1 | RV QLIKE | 1.938026 | 1.948832 | -0.5576% | +1.3017 | 0.3875 | 否 |
| ETH | 1 | 5% tail pinball | 0.00419786 | 0.00427274 | -1.7836% | +1.4431 | 0.3875 | 否 |
| ETH | 5 | RV QLIKE | 0.518785 | 0.519221 | -0.0839% | +0.2112 | 0.8328 | 否 |
| ETH | 5 | 5% tail pinball | 0.00954148 | 0.00958251 | -0.4300% | +0.4500 | 0.8328 | 否 |

唯一正向 loss 變化是 BTC h=1 left-tail 的 **+0.3734%**，但
HLN-DM t=-0.3063、BH q=0.8328，遠未通過門檻。其餘七格皆惡化；八格
沒有任何一格通過。因此 verdict 是
`NULL_NO_ROBUST_OOS_INCREMENT`：在這個兩年日頻 proxy 樣本中，昨日跨所
close dispersion 沒有對 HAR-type baseline 提供穩健的短期 RV 或左尾
增量預測力。

四個 quantile forecast path 均有 0 fit failure、0 convergence warning、
0 iteration-limit hit。cache-only 重跑在刪除 `run_utc` 後的 canonical JSON
SHA-256 完全相同。這個 null 不能外推成「跨所 fragmentation 永遠無資訊」：
Kraken public REST 把共同樣本限制在約兩年，日 close 也會抹平日內短暫
價差；更高頻 synchronized quotes、fees、transfer latency 與可成交 depth
仍是另一個尚未檢驗的問題。

## Reproduction

首次抓取並固定 public API snapshot：

```bash
uv run python experiments/k1682/k1682.py --refresh
```

之後 cache-only 重跑：

```bash
uv run python experiments/k1682/k1682.py
```

必要產出：

- `k1682.py`
- `k1682_results.json`（tmp 寫入、`json.load` 驗證、`os.replace`）
- `README.md`
- `data/*.csv` pinned inputs + results 內 SHA-256
- `k1682_fragmentation_timeseries.png`
- `k1682_oos_loss_comparison.png`

## References

- Makarov, I., & Schoar, A. (2020). *Trading and arbitrage in cryptocurrency markets*. Journal of Financial Economics, 135(2), 293–319. DOI: 10.1016/j.jfineco.2019.07.001.
- Brandvold, M., Molnár, P., Vagstad, K., & Valstad, O. C. A. (2015). *Price discovery on Bitcoin exchanges*. Journal of International Financial Markets, Institutions and Money, 36, 18–35. DOI: 10.1016/j.intfin.2015.02.010.
- Hautsch, N., Scheuch, C., & Voigt, S. (2024). *Building Trust Takes Time: Limits to Arbitrage for Blockchain-Based Assets*. Review of Finance, 28(4), 1345–1381. DOI: 10.1093/rof/rfae004.
- Corsi, F. (2009). *A simple approximate long-memory model of realized volatility*. Journal of Financial Econometrics, 7(2), 174–196. DOI: 10.1093/jjfinec/nbp001.
- Patton, A. J. (2011). *Volatility forecast comparison using imperfect volatility proxies*. Journal of Econometrics, 160(1), 246–256. DOI: 10.1016/j.jeconom.2010.03.034.
- Clark, T. E., & West, K. D. (2007). *Approximately normal tests for equal predictive accuracy in nested models*. Journal of Econometrics, 138(1), 291–311. DOI: 10.1016/j.jeconom.2006.05.023.
