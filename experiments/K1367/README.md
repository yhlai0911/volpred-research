# K1367 - Climate-News Duration And Green/Brown Tail-Risk Proxy

## 問題

`research_program.md` 的待辦問題是：

> Climate-news duration 而非 climate-news level：green/brown 反應時間差是否預測 tail risk - 用 RSS/GDELT climate-news clusters 建 event duration / decay proxy，搭配 ICLN/TAN/XLE/XOP/XLU 與可得 green/brown baskets，檢定同一 climate-news shock 下「反應時間較長」是否預測後續 RV、VaR/ES 與 green-brown correlation spike。

本實驗是免費資料 proxy diagnostic。它不能複製 Fahmy (2025) 的公司級 daily / intraday response-time model；只檢查公開 GDELT climate-news attention duration 加 ETF 日頻價格時，是否已經看得到可用的 lagged tail-risk signal。

## 動機與差異化

- 既有 climate vol 題多看 named physical events、oil/energy proxy 或 green-minus-brown level spread；本題改看新聞注意力的 duration / decay。
- JBF 2025 response-time model 強調 climate-news event duration 可改善 VaR / ES 風險統計；本實驗用免費日頻資料做可重現降階測試。
- 同一 climate-news shock 下同時量測 green basket 與 brown basket 的 price-response days，避免只把新聞量本身當成 level signal。

## 文獻脈絡

1. Fahmy (2025), *A stochastic model for predicting the response time of green vs brown stocks to climate change news risk*, Journal of Banking & Finance. The paper models climate-news duration and reports risk-management relevance for VaR and expected shortfall. <https://ideas.repec.org/a/eee/jbfina/v178y2025ics037842662500127x.html>
2. Engle, Giglio, Kelly, Lee, Stroebel (2020), *Hedging Climate Change News*, RFS. Climate-news innovations can affect green/brown hedge portfolios and investor climate-risk exposure. <https://pages.stern.nyu.edu/~jstroebe/PDF/EGKLS_ClimateRisk_RFS.pdf>
3. Li et al., *Return volatility, correlation, and hedging of green and brown stocks: Is there a role for climate risk factors?* Climate-news risk factors are linked to brown/green volatility and dynamic correlation. <https://repository.up.ac.za/bitstreams/39649bec-a2c6-468e-976d-7796d5c9b0d3/download>
4. Olasehinde-Williams and Akadiri (2025), *Dynamics of Brown and Green Energy Stocks Under Climate-Related Risk*. Transition-risk growth is tested against green/brown energy returns and volatility. <https://doi.org/10.46557/001c.126024>

## 資料

- News source: GDELT DOC API `TimelineVolRaw`, query:
  `"climate change" OR "climate policy" OR "carbon emissions" OR "global warming" OR "clean energy transition" OR "net zero" OR "carbon tax"`.
- News sample: 2017-01-01 to 2026-06-23, 3,440 daily rows.
- ETF prices: yfinance adjusted daily close, `ICLN`, `TAN`, `XLE`, `XOP`, `XLU`, `SPY`.
- Green basket: equal-weight `ICLN` + `TAN`.
- Brown basket: equal-weight `XLE` + `XOP`.
- Effective aligned sample: 69 climate-news duration events, 2017-03-15 to 2026-06-22 market data.
- Seed: `42`.

## 方法

1. Build GDELT daily article-share z-score using rolling statistics estimated with prior data only.
2. Define an active climate-news cluster as consecutive days with `news_z >= 0.5`, retained only if the cluster contains a core day with `news_z >= 1.5`.
3. Duration/decay proxy:
   - `duration_days`: active cluster length.
   - `decay_days`: days from peak z-score to active-cluster end.
   - `duration_score = log1p(duration_days) + 0.5 * log1p(decay_days)`.
4. Price-response proxy:
   - Green/brown excess returns are measured versus `SPY`.
   - Response time is the first trading day where cumulative absolute excess return crosses lagged 60-day sigma.
   - `reaction_gap_abs` is the absolute green/brown response-time difference.
5. Lookahead guard:

```python
signal_lagged = signal.shift(1)
```

Raw event features are assigned on the event feature date, then shifted by one trading day before joining to forward risk targets.

Targets:

- 5-day forward realized variance for green and brown baskets.
- 5-day left-tail loss for green and brown baskets.
- 5-day VaR breach indicator using lagged 252-day historical 5% VaR.
- 5-day ES shortfall gap using lagged 252-day historical ES.
- 21-day forward green-brown correlation spike relative to lagged 63-day trailing correlation.

Regression:

- OLS with HAC standard errors.
- Focal predictors: `duration_score_lag1`, `reaction_gap_abs_lag1`.
- Controls: `peak_news_z_lag1`, `spy_rv21_lag1`, `abs_spy_ret_lag1`.
- Regressors are standardized within each regression sample for coefficient comparability.

## Success Criteria

The proxy supports the backlog hypothesis only if at least two focal predictor / target cells have:

- expected positive coefficient;
- Harvey-style `|t| >= 3`;
- Bonferroni-adjusted `p < 0.05` across 18 focal tests.

Anything weaker is `WEAK_DIAGNOSTIC` or `NULL_PROXY`, not publishable evidence.

## Outputs

- `K1367.py` - reproducible experiment script.
- `K1367_results.json` - byte-traceable result output.
- `K1367_event_features.csv` - event-level duration and reaction features.
- `K1367_model_panel.csv` - daily predictive panel after lagging signals.
- `K1367_news_duration_events.png` - GDELT event visualization.
- `K1367_coefficients.png` - HAC coefficient chart.
- `K1367_event_diagnostics.png` - top vs bottom duration-reaction diagnostic.
- `data/gdelt_climate_timeline_raw.json` - raw GDELT response cache.
- `data/gdelt_climate_daily.csv` - parsed daily GDELT series.
- `data/yfinance_ohlcv.csv` - ETF OHLCV cache.

## Main Result

Verdict: `NULL_PROXY`.

No focal duration or reaction-gap coefficient passes Harvey `|t| >= 3`, and none passes Bonferroni correction.

| Target | n | Duration coef | Duration t | Reaction-gap coef | Reaction-gap t |
| --- | ---: | ---: | ---: | ---: | ---: |
| `green_rv5` | 69 | +0.0241 | +1.80 | +0.0096 | +1.32 |
| `brown_rv5` | 69 | +0.0336 | +1.69 | -0.0051 | -0.33 |
| `green_left_tail_loss5` | 69 | +0.0038 | +0.95 | +0.0009 | +0.34 |
| `brown_left_tail_loss5` | 69 | -0.0018 | -0.86 | -0.0018 | -1.41 |
| `green_var5_breach` | 64 | +0.0031 | +0.04 | +0.0232 | +0.58 |
| `brown_var5_breach` | 64 | -0.0439 | -0.73 | +0.0173 | +0.39 |
| `green_es_gap5` | 64 | +0.00005 | +0.21 | -0.000004 | -0.03 |
| `brown_es_gap5` | 64 | -0.0001 | -0.53 | -0.00002 | -0.09 |
| `green_brown_corr_spike21` | 69 | -0.0326 | -0.86 | +0.0100 | +0.43 |

The event diagnostic is directionally positive for green RV and green left-tail loss, but bootstrap intervals cross zero. Example: top-tercile duration-reaction composite green RV5 is 0.0930 versus 0.0547 in the bottom tercile, but the bootstrap 95% CI for the difference is `[-0.0131, +0.0956]`.

## Interpretation

This result does not support using free GDELT daily climate-news duration plus public green/brown ETFs as a robust tail-risk prior. It also does not reject the JBF 2025 mechanism, because that paper uses richer firm-level and intraday duration data. The honest conclusion is narrower: with this public daily proxy, reaction-time and duration features are too noisy for a strong VolPred signal.

## Limitations

- ETF baskets are coarse proxies, not green/brown firm portfolios.
- GDELT keyword counts measure attention volume, not validated climate-news content or sentiment.
- Duration is known only after the news cluster decays; this is a lagged risk-prior diagnostic, not an event-day trading signal.
- Daily ETF prices cannot test the intraday IG-ACD-GARCH channel.
- Sample size is only 69 aligned events after all lag and horizon requirements.
