# K1575 - Critical-minerals export-restriction shocks and ETF RV transmission

**Status: COMPLETE - MIXED / jump-only, market-confounded signal**

## 核心發現

8 個 critical-minerals export-restriction announcements（2023-07-03 到 2025-10-09）對 13 檔 listed ETF / benchmark proxies 的事件研究顯示：

- Confirmatory RV family (`t1_r2`, `rv5`, `rv22`) 共 312 個 event-ticker-metric tests，**0 個通過 Bonferroni**。
- Aggregate RV family mean ratio = **2.452**，但 median ratio = **0.869**，`ratio > 1` 比例只有 **0.462**，pooled one-sided sign test p = **0.922**，所以不是系統性 post-event RV 上升。
- `jump5_abs` bootstrap 有 **2 / 104** 個 tests 通過 Bonferroni，都是 **2025-04-04 China medium/heavy rare-earth controls** 後的 `LIT` 與 `REMX`。
- 這兩個 jump signal **不能 cleanly 歸因於 rare-earth control 本身**：同一事件窗內 `SPY`、`QQQ`、`XLI` 也出現高 rv5 / jump ratios，且 direct-minerals mean `rv5` / `jump5_abs` 沒有超過 benchmark mean。2025-04-04 事件窗明顯受同週 broad tariff-driven market volatility 混淆。

結論應表述為：

> Critical-minerals export-restriction announcements 在 ETF 日資料上沒有穩健的 sector-specific RV transmission；有單一 rare-earth event 的 jump 訊號，但被廣泛市場震盪混淆，不能宣稱為乾淨的礦產限制 causal effect。

## 動機與差異化

Critical minerals、rare earths、graphite、cobalt、gallium/germanium export controls 是 2024-2026 的 clean-tech / defense / semiconductor supply-chain 風險主題。直覺上，出口限制可能提高 clean-tech、battery、semiconductor、defense ETF 的 short-horizon volatility。

本實驗和先前 K 的差異：

- vs K1573：K1573 是 CHIPS Act semiconductor industrial-policy awards；K1575 是 critical-minerals export restrictions。
- vs 既有 oil / commodity spillover K：K1575 用公告事件窗，而不是連續 commodity factor / VIX-style state variable。
- vs article-level narrative：本實驗先驗證 listed ETF 日資料是否真的有可發佈的波動率訊號，避免只依新聞直覺寫結論。

## 資料

### Event set

`events.csv` 包含 8 個公開 announcement dates：

| Date | Event | Material group | Shock type |
|---|---|---|---|
| 2023-07-03 | China gallium/germanium controls | gallium_germanium | license requirement |
| 2023-10-20 | China graphite controls | graphite | license requirement |
| 2024-08-15 | China antimony / superhard controls | antimony_superhard | license requirement |
| 2024-12-03 | China US-specific dual-use mineral tightening | gallium/germanium/antimony/graphite | US-specific tightening |
| 2025-02-04 | China tungsten / tellurium / bismuth / molybdenum / indium controls | minor metals | license requirement |
| 2025-02-22 | DRC cobalt export suspension | cobalt | temporary export suspension |
| 2025-04-04 | China medium/heavy rare-earth controls | medium_heavy_rare_earths | license requirement |
| 2025-10-09 | China rare-earth related-item expansion | rare_earths_related_items | expanded controls |

Event sources are stored in `events.csv` as URLs, using MOFCOM / IEA policy pages where available. Context sources in `k1575_results.json` include OECD CRM export-restriction inventory, IEA Global Critical Minerals Outlook, and IEA policy tracker.

### Market data

- Price source: yfinance adjusted close (`auto_adjust=True`)
- Sample: **2023-01-04 to 2026-04-07**
- Tickers used: `COPX`, `ICLN`, `ITA`, `LIT`, `PICK`, `QQQ`, `REMX`, `SMH`, `SOXX`, `SPY`, `TAN`, `URA`, `XLI`
- Missing / sparse tickers: none

## 方法

Window design is lookahead-safe:

| Window | Relative trading days | Use |
|---|---:|---|
| Pre baseline | T-30 to T-6 | baseline volatility |
| Gap | T-5 to T0 | discarded |
| Post | T+1 onward | event response |

T=0 is the first trading day on or after the announcement date. Same-day returns are excluded from post metrics.

Metrics:

- `t1_r2`: T+1 squared log return / pre mean squared log return
- `rv5`: mean squared log return over T+1..T+5 / pre mean squared log return
- `rv22`: mean squared log return over T+1..T+22 / pre mean squared log return
- `jump5_abs`: max absolute log return over T+1..T+5 / pre mean absolute log return

Significance:

- Random-anchor one-sided bootstrap on each ticker's full daily series
- `B=1000`, seed = `42`
- Bonferroni alpha over all 416 p-values = **0.000120**
- `jump5_abs` is tested by bootstrap only. A `ratio > 1` sign test is invalid for jump because a 5-day max is mechanically expected to exceed a one-period mean under the null.

## Results

### Confirmatory RV family

| Metric | N | Mean ratio | Median ratio | Frac > 1 | Sign-test p | Bonferroni sig |
|---|---:|---:|---:|---:|---:|---:|
| `t1_r2` | 104 | 2.837 | 0.295 | 0.240 | 1.000 | 0 |
| `rv5` | 104 | 2.864 | 1.076 | 0.529 | 0.312 | 0 |
| `rv22` | 104 | 1.653 | 1.252 | 0.615 | 0.0118 | 0 |

`rv22` has more ratios above 1, but no individual event-ticker survives Bonferroni and benchmark channels are at least as large as many sector channels. This is weak descriptive elevation, not confirmatory evidence.

### Jump signal

Only two Bonferroni-significant tests:

| Event date | Material group | Ticker | Channel | Metric | Ratio | Bootstrap p |
|---|---|---|---|---|---:|---:|
| 2025-04-04 | medium_heavy_rare_earths | LIT | battery_clean | `jump5_abs` | 10.456 | 0.000 |
| 2025-04-04 | medium_heavy_rare_earths | REMX | direct_minerals | `jump5_abs` | 9.248 | 0.000 |

But same event window also has broad market stress:

- `SPY` rv5 ratio = 15.83 and jump5 ratio = 9.44
- `QQQ` rv5 ratio = 10.56 and jump5 ratio = 7.97
- Direct-minerals mean rv5 is **2.21 below** benchmark mean for that event
- Direct-minerals mean jump5 is **1.17 below** benchmark mean for that event

Therefore the jump signal is real as a return-series observation, but not clean evidence of sector-specific minerals transmission.

### Spillover contrasts

Benchmark-adjusted contrasts do not support clean spillover:

| Metric | Contrast | N events | Mean diff | Frac positive | Sign-test p |
|---|---|---:|---:|---:|---:|
| `rv5` | direct minus benchmark | 8 | -0.737 | 0.500 | 0.637 |
| `rv5` | semiconductor minus benchmark | 8 | -0.447 | 0.500 | 0.637 |
| `rv5` | defense minus benchmark | 8 | -1.775 | 0.250 | 0.965 |
| `rv22` | direct minus benchmark | 8 | -0.388 | 0.375 | 0.855 |
| `rv22` | semiconductor minus benchmark | 8 | -0.363 | 0.375 | 0.855 |
| `rv22` | defense minus benchmark | 8 | -0.790 | 0.375 | 0.855 |

## 防錯與限制

- **No lookahead**: post window starts at T+1; T=0 is excluded.
- **Fixed seed**: all bootstrap draws use `np.random.default_rng(42)`.
- **Multiple testing**: Bonferroni over all 416 event-ticker-metric p-values.
- **Daily data only**: intraday announcement reaction may be missed.
- **Small N**: 8 events is low power and event heterogeneity is large.
- **Manual event set**: dates are source-linked but not an exhaustive policy database.
- **Causal confounding**: 2025-04-04 and 2025-10-09 rare-earth windows overlap broader US-China / tariff market shocks; benchmark-adjusted evidence is therefore central.
- **ETF proxy limitation**: REMX/LIT/COPX/URA/SMH/ITA are liquid proxies, not pure material-specific spot exposures.

## Files

- `events.csv` - event list and source URLs
- `k1575.py` - reproducible script
- `k1575_results.json` - full machine-readable results
- `event_ticker_metric_results.csv` - 416 event/ticker/metric tests
- `close_yfinance.csv` - adjusted-close cache
- `fig_a.png` - rv5 ratio distribution by channel
- `fig_b.png` - mean ratio heatmap by channel and metric
- `codex_review.md` - code and methodology review

## Reproduce

```bash
uv run python experiments/K1575/k1575.py
```
