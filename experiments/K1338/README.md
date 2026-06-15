# K1338: Chinese Financial-News Sentiment vs 0050.TW Volatility

**Verdict:** NULL_DATA_LIMITATION
**Run date:** 2026-06-15

## Motivation

K1338 tests whether Chinese financial-news sentiment adds incremental
predictive content for 0050.TW daily volatility beyond a simple HAR-style
realized-variance baseline. The intended VolPred angle is narrow: a cheap,
Taiwan-local text signal should improve next-day volatility forecasts only if
it survives a lookahead-free OOS QLIKE/DM comparison.

## Literature

- Ku and Chen, NTUSD / NTU Sentiment Dictionary:
  https://github.com/ntunlplab/NTUSD
- Wei and Lu, "Informativeness of the market news sentiment in the Taiwan stock
  market", International Review of Economics and Finance, 2017:
  https://ideas.repec.org/a/eee/ecofin/v39y2017icp158-181.html
- "Chinese Financial News Analysis for Sentiment and Stock Prediction", Big
  Data and Cognitive Computing, 2025:
  https://www.mdpi.com/2504-2289/9/10/263
- "Textual Regression for Realized Volatility", SSRN, 2025:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5136391
- "Forecasting U.S. equity market volatility with attention and sentiment",
  arXiv, 2025:
  https://arxiv.org/html/2503.19767v1

## Data

- News source attempted:
  - CNYES machine-readable API categories `tw_stock` and `headline`.
  - CTEE public RSS/WP endpoints were probed but did not expose a usable RSS/API
    response at run time.
- Lexicon:
  - NTUSD positive/negative dictionaries from the official GitHub repository.
  - A small finance-domain augmentation for common market terms such as
    `大漲`, `利多`, `重挫`, `違約`.
- Price source:
  - yfinance `0050.TW`, cleaned through `volpred.utils.clean_tw50_data`.

At run time the CNYES API exposed only 11 Taipei-calendar days of public
machine-readable history, 2026-06-05 to 2026-06-15. That is enough to verify the
pipeline and source limitation, but not enough for an honest OOS model test.

## Method

1. Fetch all currently available CNYES pages for `tw_stock` and `headline`.
2. Deduplicate by `newsId`.
3. Score titles using dictionary hits:
   `(positive_hits - negative_hits) / sqrt(total_hits + 1)`.
4. Aggregate to daily sentiment and compute an expanding prior-only z-score.
5. Align to 0050.TW daily variance.
6. Only if the sample passes the OOS gate, compare:
   - Baseline: log-HAR variance model.
   - Augmented: same baseline plus lagged daily sentiment.

## Lookahead Policy

The implementation uses the conservative timing rule:

```python
signal = model["sentiment_z_raw"].shift(1)
model["sentiment_z_lag1"] = signal
```

Date-`t` returns are therefore never multiplied or modeled with same-day
sentiment. The intended forecast comparison uses prior-day news and prior-day
realized variance only.

## Success Criteria

The sentiment signal would be considered promising only if all are true:

- At least 252 training rows and 60 OOS forecast rows.
- HAR+sentiment has lower OOS QLIKE than HAR.
- DM t-statistic passes the project Harvey threshold `|t| > 3`.
- The effect is not driven by a single news day or an endpoint artifact.

The current run fails the first gate, so no predictive claim is made.

## Reproduce

```bash
uv run python experiments/K1338/K1338.py
```

Primary artifacts:

- `K1338_results.json`
- `K1338_daily_sentiment.csv`
- `K1338_article_scores.csv`
- `K1338_sentiment_coverage.png`

## Conclusion

This is a data-availability NULL, not evidence that Chinese sentiment lacks
predictive power. Public RSS/API endpoints available during this run do not
provide enough history for the requested OOS QLIKE/DM gate. A proper follow-up
needs a persistent daily news collector or a licensed/archive source before the
HAR+sentiment hypothesis can be tested.
