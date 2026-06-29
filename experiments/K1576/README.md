# K1576 - Defence-spending boom announcements and ETF volatility / beta

**Status: COMPLETE - NULL result**

## 核心發現

9 個 NATO / UK / EU / Germany defence-spending announcements（2014-09-05 到 2025-06-25）對 10 檔 listed ETF proxies 的事件研究顯示：

- Confirmatory RV family (`t1_r2`, `rv5`, `rv22`) 共 **270** 個 event-ticker-metric tests，**0 個通過 Bonferroni**。
- Beta family (`beta63_delta`) 共 **45** 個 tests，**0 個通過 Bonferroni**。
- RV family aggregate mean ratio = **1.426**，但 median ratio = **0.901**，`ratio > 1` 比例只有 **0.456**，pooled one-sided sign test p = **0.936**。
- Defense ETF beta-to-SPY change mean = **-0.041**，median = **-0.030**，`delta > 0` 比例 **0.422**，sign test p = **0.884**。
- `rv22` 有弱描述性升高（mean 1.825，median 1.168，sign p = 0.036），但 **0 個單一 event-ticker 通過 Bonferroni**，且 defense-minus-benchmark contrast 為負。

結論：

> 在日頻 ETF data 裡，defence-spending / rearmament announcements 沒有形成穩健的 defense-specific RV spike，也沒有讓 defense ETF 的 63 日 market beta 系統性上升。若要寫文章，應定位為「rearmament headline 很大，但 ETF 波動反應不是乾淨 defense beta trade」的 null finding。

## 動機與差異化

Defense spending 自 2022 後成為重要宏觀主題：Germany Zeitenwende、NATO 2% floor、EU ReArm Europe、NATO Hague 5% pledge 都讓市場有「defense boom beta」直覺。這個實驗問的是：這些 spending-path announcements 是否真的領先 defense ETF、industrial ETF 或 rates ETF 的短期 realized volatility / beta change？

和既有研究的差異：

- vs K446 GPR：K446 是 generic geopolitical-risk predictor；K1576 只看可定位日期的 budget / spending-path announcements。
- vs K1575 critical minerals：K1575 是 supply-chain export restrictions；K1576 是 fiscal procurement / rearmament path。
- vs 單純 defense stock return story：本實驗測 volatility / beta response，不測長期 alpha。

## 資料

### Event set

`events.csv` 包含 9 個 source-linked announcements：

| Date | Event | Type |
|---|---|---|
| 2014-09-05 | NATO Wales Defence Investment Pledge | alliance spending target |
| 2022-02-27 | Germany Zeitenwende EUR 100bn special fund | national special fund |
| 2023-07-11 | NATO Vilnius 2% as floor | alliance spending target |
| 2024-02-14 | NATO 18 Allies expected at 2% in 2024 | spending path update |
| 2024-04-23 | UK 2.5% by 2030 | national spending target |
| 2024-07-10 | NATO Washington more-than-2% language | alliance spending target |
| 2025-02-25 | UK 2.5% by 2027 | national spending target |
| 2025-03-19 | EU ReArm Europe / Readiness 2030 | EU financing plan |
| 2025-06-25 | NATO Hague 5% commitment | alliance spending target |

### Market data

- Price source: yfinance adjusted close (`auto_adjust=True`)
- Sample: **2014-01-28 to 2026-01-31**
- Tickers used: `IEF`, `ITA`, `IYT`, `PPA`, `QQQ`, `SPY`, `TLT`, `UUP`, `XAR`, `XLI`
- Channels:
  - defense: `ITA`, `PPA`, `XAR`
  - industrials / transport: `XLI`, `IYT`
  - rates: `TLT`, `IEF`
  - dollar: `UUP`
  - benchmarks: `SPY`, `QQQ`

## 方法

Window design:

| Window | Relative trading days | Use |
|---|---:|---|
| RV pre baseline | T-30 to T-6 | baseline daily r² |
| Gap | T-5 to T0 | discarded |
| RV post | T+1 onward | event response |
| Beta pre | T-90 to T-6 | pre-event beta to SPY |
| Beta post | T+1 to T+63 | post-event beta to SPY |

T=0 is the first trading day on or after the announcement date. Post windows start strictly at T+1.

Metrics:

- `t1_r2`: T+1 squared log return / pre mean squared log return
- `rv5`: T+1..T+5 mean squared log return / pre mean squared log return
- `rv22`: T+1..T+22 mean squared log return / pre mean squared log return
- `beta63_delta`: OLS beta to SPY over T+1..T+63 minus beta over T-90..T-6

Significance:

- Random-anchor one-sided bootstrap on the same ticker's full sample
- `B=1000`, seed = `42`
- Bonferroni over all **315** p-values: alpha = **0.000159**

## Results

### Metric summary

| Metric | N | Mean | Median | Frac above null | Sign-test p | Bonferroni sig |
|---|---:|---:|---:|---:|---:|---:|
| `t1_r2` | 90 | 1.155 | 0.527 | 0.289 | 0.99999 | 0 |
| `rv5` | 90 | 1.299 | 0.892 | 0.478 | 0.701 | 0 |
| `rv22` | 90 | 1.825 | 1.168 | 0.600 | 0.036 | 0 |
| `beta63_delta` | 45 | -0.041 | -0.030 | 0.422 | 0.884 | 0 |

`rv22` is the only descriptive positive metric, but it is not robust after multiple testing and does not isolate defense ETFs.

### Defense-specific contrasts

| Metric | Contrast | N events | Mean diff | Median diff | Frac positive | Sign-test p |
|---|---|---:|---:|---:|---:|---:|
| `rv5` | defense minus benchmark | 9 | -0.387 | -0.450 | 0.222 | 0.980 |
| `rv5` | defense minus industrial | 9 | -0.336 | -0.442 | 0.333 | 0.910 |
| `rv22` | defense minus benchmark | 9 | -0.434 | -0.380 | 0.333 | 0.910 |
| `rv22` | defense minus industrial | 9 | -0.030 | 0.036 | 0.556 | 0.500 |
| `beta63_delta` | defense minus industrial | 9 | -0.042 | -0.071 | 0.444 | 0.746 |

Defense ETF volatility is not stronger than benchmark volatility after these spending announcements. Beta-to-SPY does not rise relative to industrials.

### Top raw observations

Largest `rv5` rows are not clean defense-specific evidence:

- 2024-07-10 NATO Washington: `IYT` rv5 ratio 6.03, `QQQ` 4.60, `XLI` 3.36, `ITA` 3.33, `SPY` 3.09
- 2022-02-27 Germany Zeitenwende: `IEF` rv5 3.73, `TLT` 3.57, `UUP` 2.80

Largest `rv22` rows are broad-market-heavy:

- 2025-03-19 EU ReArm Europe: `SPY` rv22 8.15, `XLI` 7.91, `ITA` 7.14, `PPA` 6.93
- 2024-07-10 NATO Washington: `SPY` rv22 7.15, `QQQ` 5.59, `ITA` 4.68

This is why the aggregate RV mean exceeds 1 while the defense-specific contrast remains negative.

## Interpretation

The market may price defence spending as a long-horizon revenue / procurement theme rather than as a short-horizon volatility shock. Large announcements are also often clustered with broader macro events, rate moves, NATO summits, or broad equity risk. Daily ETF proxies are therefore too coarse to support a clean "defense boom beta" claim.

The more defensible inference is:

- defense-spending announcements are visible macro headlines;
- broad RV can be elevated around some windows;
- listed ETF data does not show a robust defense-specific post-announcement RV or beta effect.

## 防錯與限制

- **No lookahead**: post metrics start at T+1; T=0 is excluded.
- **Fixed seed**: bootstrap uses `np.random.default_rng(42)`.
- **Multiple testing**: 315 p-values, Bonferroni alpha 0.000159.
- **Small N**: only 9 event dates.
- **ETF proxy limitation**: ITA/PPA/XAR are US-listed aerospace/defense proxies, not pure European rearmament beneficiaries.
- **Daily data only**: intraday announcement response may be missed.
- **Causal confounding**: NATO / EU announcements overlap broader macro and geopolitical environments.
- **Realized spending lag**: announcements do not equal procurement cash flow; fiscal impulse can take years.

## Files

- `events.csv` - event list and source URLs
- `k1576.py` - reproducible script
- `k1576_results.json` - full machine-readable results
- `event_ticker_metric_results.csv` - 315 event/ticker/metric tests
- `close_yfinance.csv` - adjusted-close cache
- `fig_a.png` - rv5 ratio distribution by channel
- `fig_b.png` - beta-to-SPY change by ticker
- `fig_c.png` - channel mean RV heatmap
- `codex_review.md` - code and methodology review

## Reproduce

```bash
uv run python experiments/K1576/k1576.py
```
