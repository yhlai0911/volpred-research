# K1360 — Prediction-market probability shock as macro event vol prior

## 動機

本題來自 `research_program.md`：

> 用 Kalshi/Polymarket 公開 market price/API 建 FOMC、CPI、NFP、election/geopolitical event-probability change，檢定是否領先 VIX9D/VIX、SPY RV 與 event-day tail move；所有 signal 用 `shift(1)`，並與 SOFR/FedWatch prior 比較。

K1360 做的是 public-data feasibility + first-pass diagnostic。目標不是上架策略，而是回答：**公開 prediction-market probability shock 能不能成為 macro event vol prior 的候選訊號？**

## 文獻與資料定位

- Wolfers and Zitzewitz (2004), *Prediction Markets*, JEP：prediction-market price 可作資訊聚合的機率 proxy，但不是無噪音真值。
- Manski (2006), *Interpreting the Predictions of Prediction Markets*：市場價格不必在所有假設下等於平均信念。
- Snowberg, Wolfers, and Zitzewitz (2013), *Prediction Markets for Economic Forecasting*：prediction market 可用於經濟預測，但需處理 liquidity / calibration caveat。
- Bernanke and Kuttner (2005) 與 Kuttner (2001)：FOMC surprise 通常用 fed-funds futures 類 prior 衡量。
- API reference：Kalshi public market/event/candlestick docs (`https://docs.kalshi.com/`)；Polymarket Gamma/CLOB public docs (`https://docs.polymarket.com/`)。

## 資料

Kalshi public API:

- Series：`KXCPI`, `KXCPICORE`, `KXFEDDECISION`, `KXPAYROLLS`, `KXUSNFP`。
- 2026 event stubs：CPI 11、Core CPI 11、FOMC 8、Payrolls 11、US NFP 3。
- Usable selected events：32。
- Selected markets：186。
- Daily candle rows：21,759。
- Calendar signal days：263。

Market outcomes:

- `yfinance` adjusted data：`SPY`, `^VIX`, `^VIX9D`, `ZQ=F`。
- Analysis panel：2025-09-03 to 2026-06-18。
- Market trading days：200。
- Nonzero Kalshi signal days：165。

Polymarket:

- `https://gamma-api.polymarket.com/events?limit=1` and CLOB price-history probe both returned HTTP 404 with a Taiwan domain-block HTML body in this environment.
- Therefore Polymarket is excluded from empirical claims.

## 方法

For each selected Kalshi event:

1. Fetch event detail and keep liquid markets using `volume + 0.05 * open_interest + 0.1 * liquidity`, requiring score >= 1.0.
2. Keep top 6 markets per event.
3. Convert daily candles to close probability using `price.close_dollars`; if absent, use yes bid/ask midpoint.
4. Compute market-level daily probability changes.
5. Aggregate to event-level `shock_max_abs`, then calendar-day max across events as the primary Kalshi shock.

Predictive tests:

- Targets: next-day `SPY` absolute return, next-day left-tail proxy, log `VIX9D/VIX` change, log `VIX` change, log `VIX9D` change, and forward 5-trading-day SPY realized volatility.
- Models: Kalshi-only, `ZQ=F` fed-funds-futures proxy only, and combined.
- Inference: Newey-West HAC with daily lag 5.
- Discovery bar: Harvey-style `|t| >= 3`.

## Lookahead 防線

The script explicitly uses:

```python
features["kalshi_signal"] = features["kalshi_primary_raw"].shift(1)
features["kalshi_l1_signal"] = features["kalshi_l1_raw"].shift(1)
features["fedfunds_prior_signal"] = features["fedfunds_prior_raw"].shift(1)
```

Interpretation:

- Prediction-market shock at calendar date `t-1` predicts listed-market outcome at trading date `t`.
- Forward 5-day RV is overlapping, so K1360 uses HAC lag 5 and keeps it diagnostic.
- No same-day prediction-market shock is used as same-day equity-vol outcome.

## 結果

Verdict：`WEAK_KALSHI_DIAGNOSTIC_UNDERPOWERED`。

| Target | N | Kalshi HAC t | Kalshi beta per 1sd signal | Kalshi R2 |
|---|---:|---:|---:|---:|
| `spy_abs_ret_1d` | 200 | +1.71 | +0.00065 | 0.014 |
| `spy_rv5_forward` | 196 | +2.12 | +0.01485 | 0.082 |
| `spy_left_tail_1d` | 200 | +0.32 | +0.00011 | 0.001 |
| `vix9d_vix_ratio_change` | 200 | -2.25 | -0.00815 | 0.016 |
| `vix_log_change_1d` | 200 | -1.86 | -0.00934 | 0.014 |
| `vix9d_log_change_1d` | 200 | -2.22 | -0.01749 | 0.018 |

Top-quintile diagnostic for `spy_rv5_forward`:

- Top quintile mean：0.1423 annualized.
- Rest mean：0.1142 annualized.
- Difference：+0.0281.
- Welch t：2.73, p=0.0084.

This is a weak diagnostic signal, not a robust discovery. No Kalshi target reaches `t >= 3`; event-study evidence is also underpowered (`n=10` events with market target, all Spearman p-values > 0.5).

## 結論

Prediction-market probability shock is **data-feasible on Kalshi** for CPI/Core CPI/FOMC/NFP-style public events, and it has a weak positive association with next-week SPY realized volatility. It does **not** pass the project's discovery threshold and cannot be presented as a robust volatility prior yet.

Valid takeaway:

- Keep this as a candidate data source and v2 research direction.
- Do not publish a strong claim that prediction-market shock forecasts VIX9D/VIX or SPY tail moves.

## 檔案

- `K1360.py`：可重跑腳本。
- `K1360_results.json`：完整結果與 metadata。
- `K1360_daily_panel.csv`：final predictive panel。
- `K1360_event_study.csv`：event-day diagnostic panel。
- `data/kalshi_selected_events.csv`：selected event metadata。
- `data/kalshi_market_panel.csv`：market-candle probability panel。
- `data/kalshi_event_daily.csv`：event-level shock panel。
- `data/raw/*.json` / `*.html`：API raw cache。
- `figures/k1360_signal_vix9d_ratio.png` and `figures/k1360_hac_tstats.png`。
- `codex_review.md`：source-level review。

## 重跑

```bash
uv run python experiments/k1360/K1360.py
```

To force API refresh:

```bash
uv run python experiments/k1360/K1360.py --refresh
```

