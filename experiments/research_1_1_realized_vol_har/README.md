# research_1_1_realized_vol_har

## Question

Can free financial-news text improve 1/5/22-trading-day SPY realized-volatility
forecasts beyond a HAR baseline?

## Motivation

The task was generated from the research backlog after 2025 textual-regression
papers suggested that LLM/BERT-style text features may help longer-horizon
realized-volatility forecasts. This experiment tests the first practical gate:
whether a no-cost Yahoo Finance RSS workflow has enough historical text coverage
to support a lookahead-safe HAR-versus-text horserace.

## Literature Checked

- Corsi (2009), "A Simple Approximate Long-Memory Model of Realized Volatility":
  canonical HAR realized-volatility baseline.
- Tetlock (2007), "Giving Content to Investor Sentiment": media pessimism and
  market activity.
- Manela and Moreira (2017), "News Implied Volatility and Disaster Concerns":
  text-derived uncertainty/news-implied volatility.
- Parvini and Assa (2025), "Textual Regression for Realized Volatility": recent
  motivation for LLM/BERT textual regression at 1-day to 1-month horizons.

Project priors:

- K1487: GDELT daily novel-risk keyword intensity did not improve RV forecasts
  beyond HAR/VIX on SPY/QQQ/HYG/TLT.
- K1338: Chinese financial-news sentiment pipeline was blocked by only 11 public
  machine-readable API days.
- K531: FRED sentiment/uncertainty proxies did not improve volatility prediction
  beyond VIX.

## Data

- Market: `yfinance` SPY adjusted close, 2006-01-01 to 2026-06-16.
- News: current public Yahoo Finance RSS snapshots:
  - `feeds.finance.yahoo.com/rss/2.0/headline?s=SPY`
  - `feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC`
  - `finance.yahoo.com/news/rssindex`

The RSS feeds are snapshots, not a historical archive. The run stores fetched
headlines under `data/yahoo_rss_headlines.csv`.

## Method

Market-side sanity check:

1. Compute SPY close-to-close squared log return as daily realized variance.
2. Build HAR features from `rv_d`, `rv_w`, and `rv_m`, all shifted by one trading
   day.
3. Evaluate expanding HAR log-variance forecasts for horizons 1, 5, and 22.
4. For horizon `h`, training rows are kept only when `target_end_pos < forecast_pos`.
   This prevents the K1337 forward-label leakage mode.

Text-side gate:

- A text model is allowed only if the RSS source has at least 252 training days,
  60 OOS days, and max-horizon coverage.
- FinBERT/BERT embeddings are allowed only if `transformers` is installed and
  model weights can be loaded.
- In the current runtime, `transformers` is absent and Yahoo RSS has only a
  short current snapshot, so no text regression is fit and no "text beats HAR"
  claim is made.

## Result

Verdict: `NULL_DATA_LIMITATION`.

The HAR baseline pipeline is reproducible and lookahead-safe, but the requested
Yahoo-RSS plus FinBERT/BERT horserace cannot be honestly evaluated from the
available public RSS snapshot. A valid follow-up needs either:

- a persistent daily collector that starts storing headlines now, or
- a historical/licensed headline archive.

## Reproduce

```bash
uv run python experiments/research_1_1_realized_vol_har/research_1_1_realized_vol_har.py
```

Artifacts:

- `research_1_1_realized_vol_har.py`
- `research_1_1_realized_vol_har_results.json`
- `data/yahoo_rss_headlines.csv`
- `figures/news_coverage_and_har_baseline.png`

