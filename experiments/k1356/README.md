# K1356: Oil-News Attention and Energy-Market Volatility

## Motivation

This experiment tests whether a free public news-attention proxy adds
out-of-sample information for one-day-ahead crude-oil and energy-equity
volatility forecasts.

The backlog item was motivated by Calomiris, Cakir Melek, and Mamaysky's
energy-market NLP work, later published in the *Financial Analysts Journal* as
"Big Data Meets the Turbulent Oil Market". Their result uses a large Reuters
energy-news corpus and topic models. This experiment is intentionally weaker:
it uses only GDELT DOC API daily article counts matching oil-market terms.

## Prior Internal Checks

Related internal findings searched before implementation:

- K1481: EIA inventory-surprise crude RV pilot. Inventory controls were useful
  as a fundamental benchmark, but that experiment did not test news flow.
- K1129/K1135/K1136: commodity volatility model-family tests were mostly NULL.
  K1356 does not change the volatility model class; it adds a public exogenous
  text-attention feature.
- K154 and K1355: low-frequency flow/liquidity proxies can be endogenous to
  volatility, so K1356 caps claims at "GDELT attention proxy" rather than true
  topic-model information.
- K1487: coarse GDELT novel-risk keyword proxies were NULL/negative for broad
  cross-asset RV. K1356 narrows the domain to oil and energy assets.

## External Anchors

- Calomiris, Cakir Melek, and Mamaysky, "Big Data Meets the Turbulent Oil
  Market", *Financial Analysts Journal* 2026 / Kansas City Fed RWP 20-20.
- GDELT DOC API TimelineVolRaw documentation, which reports raw article counts
  per time interval for a query.
- Li, Jiang, Li, and Wang (2021), *Energy Economics*, on oil-news sentiment and
  oil futures return/volatility forecasting.
- Corsi (2009) HAR volatility model and Patton (2011) QLIKE forecast loss.

## Data

- yfinance daily OHLCV, `auto_adjust=False`.
- Assets: `CL=F`, `USO`, `XLE`, `XOP`.
- GDELT DOC 2.0 `TimelineVolRaw` query:
  `("crude oil" OR "oil market" OR OPEC OR petroleum OR "oil prices" OR "energy market")`.
- EIA `WCESTUS1`, weekly U.S. ending stocks excluding SPR of crude oil,
  downloaded from `https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls`.
- Sample starts 2017-01-01 because this is the public GDELT DOC historical
  search window.
- OOS starts 2020-01-01.

Raw snapshots are saved under `data/`.

## Method

The target is next-day Garman-Klass range variance, a daily OHLC proxy for
realized volatility.

Baseline model:

- `HAR_INV`: HAR range-variance features plus lagged EIA crude-stock-change
  control.

Primary challenger:

- `HAR_INV_NEWS`: `HAR_INV` plus lagged GDELT oil-news attention z-score.

Diagnostic challenger:

- `HAR_INV_NEWS_ABS`: `HAR_INV` plus lagged absolute news-attention shock.

Models are expanding-window OLS with annual refits. Evaluation uses QLIKE and
Diebold-Mariano tests. The pooled test averages QLIKE loss differences by date
across assets before running DM, so same-day cross-asset dependence is not
treated as four independent observations.

## Lookahead Policy

The code explicitly enforces:

```python
frame["news_signal"] = frame["news_z"].shift(1)
frame["news_abs_signal"] = frame["news_z"].abs().shift(1)
frame["inventory_signal"] = frame["inventory_z"].shift(1)
```

Weekly EIA inventory values are first shifted five business days from the
reported Friday period date before daily forward-fill, then shifted one more
day in the model panel.

At row `t`, the target is `RV[t+1]`; the model never uses news or inventory
information from `t+1`.

## Success Criteria

The experiment requires all of the following for `CONDITIONAL_PASS_PROXY`:

- pooled `HAR_INV_NEWS` QLIKE beats `HAR_INV`;
- date-clustered pooled DM statistic is below `-3.0`;
- at least 3 of 4 assets improve on QLIKE.

If pooled improvement is positive but below Harvey strength, the verdict is
`MIXED_WEAK`. Otherwise the verdict is `NULL`.

## Results

Verdict: `NULL`.

- Pooled `HAR_INV_NEWS` vs `HAR_INV`: mean QLIKE loss differential
  `-0.0005708`, DM `t=-0.744`, `p=0.457`.
- Pooled absolute-attention shock variant: mean QLIKE loss differential
  `+0.0029068`, DM `t=+1.070`, `p=0.285`.
- Per-asset QLIKE improvement for the primary news proxy:
  `CL=F +0.10%`, `USO +0.95%`, `XLE -0.53%`, `XOP -0.26%`.
- Only 2 of 4 assets improve, so the predeclared breadth gate fails.

The result does not support a robust claim that free GDELT oil-news attention
adds OOS daily volatility information beyond HAR range-variance features and
the conservative EIA inventory-control proxy.

## Claim Ceiling

Even a positive result would not validate the FAJ Reuters topic-model result.
GDELT article-count attention is not full-text topic modeling, and EIA
inventory changes are not survey inventory surprises. This is a cheap public
proxy test of whether oil-news attention contains incremental daily RV
information beyond price history and a simple inventory control.

## Files

- `K1356.py`
- `K1356_results.json`
- `K1356_news_oil_vol.png`
- `data/`
