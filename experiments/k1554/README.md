# K1554: Public Social-Transmission Proxy Feasibility Test

- Experiment ID: `K1554`
- Status: `COMPLETE`
- Created: 2026-06-28
- Script: `experiments/k1554/k1554.py`
- Results: `experiments/k1554/k1554_results.json`

## Motivation

Sui and Wang (2025), "Social transmission bias: evidence from an online investor
platform" in Review of Finance, reports that investors are more likely to post
about their better-performing stocks, and that followers are more likely to buy
posted stocks. The effect is stronger for high-volatility stocks and stocks with
strong recent performance.

K1554 asks whether a free public proxy can detect the same mechanism in US
retail-heavy tickers: when a high-return and high-volatility stock receives a
Stocktwits message-volume shock, do the next trading days show higher abnormal
volume, range volatility, gap risk, or reversal?

This is deliberately a public-data feasibility test. It does not observe the
private investor-platform network, follower graph, trades, or purchases used in
the RoF paper.

## Literature Preamble

- Sui and Wang (2025), "Social transmission bias: evidence from an online
  investor platform", Review of Finance 29(6), 1663-1697.
  Source: https://academic.oup.com/rof/article/29/6/1663/8259631
- Han, Hirshleifer, and Walden (2022), "Social Transmission Bias and Investor
  Behavior", Journal of Financial and Quantitative Analysis.
  Source: https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/social-transmission-bias-and-investor-behavior/72313DD8E8227F179EE1ED760B10FD65
- Antweiler and Frank (2004), "Is All That Talk Just Noise?", Journal of Finance:
  message-board posting helps predict volatility.
  Source: https://experts.umn.edu/en/publications/is-all-that-talk-just-noise-the-information-content-of-internet-s/
- Barber and Odean (2008), "All That Glitters", Review of Financial Studies:
  individual investors buy attention-grabbing stocks.
  Source: https://academic.oup.com/rfs/article-abstract/21/2/785/1607197
- Da, Engelberg, and Gao (2011), "In Search of Attention", Journal of Finance:
  search volume is a timely retail-attention proxy.
  Source: https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2011.01679.x

## Data

- Social proxy: unauthenticated Stocktwits public symbol streams.
- Price proxy: yfinance adjusted OHLCV.
- Universe: fixed current retail/social-attention basket in `k1554.py`.
- Requested price period: 2024-01-01 through 2026-06-28.
- Stocktwits coverage is whatever the public stream can page back to at runtime;
  the result JSON records per-ticker oldest timestamps and effective event counts.

The Stocktwits Firestream historical sentiment/chart endpoint requires
authorization, and GDELT returned rate-limit responses in this environment. Those
blocked probes are logged in the result JSON rather than silently treated as data.

## Method

For each ticker:

1. Fetch recent Stocktwits messages through cursor pagination and aggregate daily
   message counts.
2. Fetch yfinance daily OHLCV and compute close-to-close returns, high-low range,
   overnight gap, and volume baselines.
3. Define a raw social-transmission shock on formation day `t` when:
   - Stocktwits message count is above the ticker's rolling high-count threshold;
   - trailing 5-day return is in the ticker's upper rolling quartile;
   - trailing 5-day realized volatility is in the ticker's upper rolling quartile.
4. Apply the signal to the next trading day with explicit lag:
   `signal = raw_signal.shift(1)`.
5. Test whether the next 1 to 5 trading days show higher:
   - abnormal volume;
   - range volatility;
   - absolute opening gap;
   - negative forward return / reversal.

Formal tests:

- Ticker-level event-minus-control effects.
- Pooled Welch t-tests as a diagnostic.
- Bootstrap confidence intervals over ticker-level effects with seed 42.
- Sign tests for cross-ticker direction.

## Lookahead Policy

- The raw event only uses Stocktwits messages and trailing prices through
  formation day `t`.
- The applied event indicator is explicitly lagged with
  `signal = raw_signal.shift(1)`.
- All forward outcomes start on the applied day, which is the first trading day
  after the formation signal.
- Rolling thresholds use `.shift(1)` before comparing current observations.
- Bootstrap seed is fixed at 42.

## Success Criteria

- `PASS`: at least 30 events, primary abnormal-volume or range-vol effect is
  positive, the bootstrap CI excludes 0, and the sign test supports broad
  cross-ticker direction.
- `CONDITIONAL_PASS`: at least 10 events with directionally positive evidence,
  but statistical support is weaker or concentrated in a few tickers.
- `NULL`: enough events exist but the tested effects are weak, mixed, or negative.
- `UNDERPOWERED`: public social history is too shallow for a serious market
  inference.

## Result

Verdict: `UNDERPOWERED`.

Headline findings:

- Public Stocktwits stream fetch produced 2,959 messages and 221 ticker-day count
  rows across the 18-name basket, but usable event days came from only 2 tickers:
  `KOSS` and `KSS`.
- Applied social-transmission events: 22 rows, 2 event tickers.
- 5-day abnormal log-volume effect is directionally positive:
  event-minus-control `+1.3046`, Welch t `1.86`, p `0.077`.
- 5-day range-vol effect is not positive:
  event-minus-control `-0.0051`, Welch t `-0.30`, p `0.767`.
- 1-day absolute gap is lower on event rows, not higher:
  event-minus-control `-0.0077`, Welch t `-3.17`, p `0.0045`.
- 5-day reversal is positive but weak:
  event-minus-control `+0.0136`, Welch t `0.97`, p `0.344`.

Interpretation: free Stocktwits public streams are useful for a live monitoring
feature or a seed list, but the unauthenticated recent-message API is too shallow
and rate-limited for a standalone historical social-transmission volatility
study. The directional abnormal-volume finding is not promoted because it is
concentrated in only two tickers.

The empirical conclusion should be read narrowly. K1554 tests whether free
public Stocktwits streams are sufficient for a reproducible social-transmission
volatility proxy. It is not a replication of investor-level network transmission.

## Files

- `k1554.py`: reproducible experiment script.
- `k1554_results.json`: numeric output and API coverage diagnostics.
- `k1554_event_effects.png`: target-effect summary chart.
- `data/stocktwits_messages.csv`: fetched public messages.
- `data/stocktwits_daily_counts.csv`: daily message count proxy.
- `data/prices.csv`: adjusted OHLCV snapshot.
- `data/panel.csv`: joined signal/target panel.
- `codex_review.md`: source/result review.
