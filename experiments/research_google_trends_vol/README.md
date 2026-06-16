# research_google_trends_vol: Google Trends Product Attention vs Taiwan Supply-Chain Volatility

## Motivation

The queued hypothesis asked whether free Google Trends product keywords such as `iPhone`, `AI server`, `TSMC`, and `HBM` add next-week volatility forecasting value for Taiwan supply-chain equities (`2330.TW`, `2303.TW`, `2454.TW`, `2382.TW`) beyond a simple HAR-style realized-volatility baseline.

This is a different target from prior internal tests:

- `K750`: US fear-search terms vs volatility, broadly NULL and reactive.
- `K789`: return / tail-risk follow-up, pytrends failed and a VIX proxy was clearly labelled as circular.
- `K1472`: strict rolling HAR framework for low-frequency volatility predictors.

## Literature Checked

- Da, Engelberg & Gao (2011), *Journal of Finance*: Google Search Volume Index as investor attention.
- Vlastakis & Markellos (2012), *Journal of Banking & Finance*: information demand and stock-market volatility.
- Andrei & Hasler (2015), *Review of Financial Studies*: attention and uncertainty increase return variance.
- PLOS ONE (2023): investor attention fluctuation in HAR-style volatility forecasting for China.

## Data

- Taiwan equities: yfinance adjusted close, `2018-01-01` to `2026-06-15` exclusive.
- Google Trends: pytrends, `geo="TW"`, product keywords `iPhone`, `AI server`, `TSMC`, `HBM`.

The script first tries real pytrends data and writes any successful weekly panel to `google_trends_weekly.csv` for reproducibility. If Google returns HTTP 429 or no sufficient trend panel, the experiment stops with `NULL_DATA_LIMITATION`. It does **not** replace Google Trends with VIX, price, or volume proxies.

## Method

If Google Trends is available:

1. Convert daily Taiwan-stock log returns into weekly realized variance.
2. Convert Google Trends terms into rolling 52-week z-scores.
3. Build a composite attention score.
4. Forecast current-week RV with:
   - baseline: weekly log-HAR using `rv_lag1`, `rv_lag4`, `rv_lag13`
   - augmented: baseline plus `attention.shift(1)`
5. Evaluate rolling expanding OOS QLIKE.
6. Use HAC loss-difference t-statistics with Harvey `|t| > 3` as the pass gate.

## Lookahead Guard

The predictive branch uses:

```python
df["attention_lag1"] = attention.shift(1)
```

That means search volume observed during week `t-1` predicts volatility in week `t`. Same-week search volume is never used to forecast same-week realized variance.

## Result

Current run verdict: **NULL**.

`pytrends` is importable after an urllib3 compatibility patch. The live fetch returned a partial real Taiwan Google Trends panel:

- Available terms: `iPhone`, `TSMC`, `HBM`
- Missing / unusable term: `AI server`
- Available period: 2018-01-05 to 2022-12-30, 261 weekly observations
- 2021-2026 follow-up chunks mostly returned HTTP 429, so this is a partial-panel test.

Primary family: 4 Taiwan supply-chain tickers. The HAR+attention model has **0/4 Harvey passes** against HAR. TSMC and Quanta show small positive relative QLIKE improvements, but neither reaches the `|t| > 3` gate; MediaTek worsens and UMC is slightly worse.

Conclusion: in the available real Google Trends panel, lagged product-keyword attention does **not** robustly improve next-week Taiwan supply-chain RV forecasts beyond HAR. This is not evidence that all product-search attention is useless; it is a partial-panel NULL with unofficial pytrends access limits.

## Files

- `research_google_trends_vol.py`
- `research_google_trends_vol_results.json`
- `google_trends_weekly.csv`
