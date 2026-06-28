# Attention-Utility Winner Focus Proxy Diagnostic

## Question

Does the attention-utility idea imply a public-market volatility footprint: recent winners in retail-heavy / meme-risk stocks get more next-session attention than recent losers, showing higher abnormal volume, range-volatility, gap risk, or squared-return volatility? The control is a large-cap basket.

This is a proxy diagnostic, not a replication of brokerage-login, Google Trends, Reddit, or Stocktwits attention data.

## Literature Preamble

- Barber and Odean (2008), "All that Glitters", motivates abnormal volume and extreme returns as attention-grabbing stock proxies: <https://academic.oup.com/rfs/article-abstract/21/2/785/1607197>
- Da, Engelberg, and Gao (2011), "In Search of Attention", motivates search-volume attention measures; those data are not used here: <https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2011.01679.x>
- "Attention Utility: Evidence from Individual Investors" (Review of Economic Studies, 2026) motivates winner-side selective attention but relies on brokerage/login evidence unavailable in this free-data diagnostic: <https://academic.oup.com/restud/article/93/1/664/8149267>

Related project memory: K473 and K789 found that broad attention/fear proxies do not robustly improve volatility or return prediction beyond VIX/HAR baselines. This experiment is narrower: winner-vs-loser asymmetry in individual-stock OHLCV outcomes.

## Data

- Source: yfinance daily OHLCV, `auto_adjust=True`, `actions=False`
- Effective sample: 2020-07-02 to 2026-06-26
- Panel rows after feature construction: 28,432
- Retail / meme-risk basket: GME, AMC, BB, PLTR, RIVN, SOFI, COIN, HOOD, DKNG, CVNA
- Large-cap control: AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, XOM, UNH, WMT
- Missing tickers: none

## Method

For each ticker-day `t`, event labels use only information available at `t-1`:

- Winner: `ret21_lag >= rolling252 q80` OR prior close within 2% of prior 63-day high.
- Loser: `ret21_lag <= rolling252 q20` OR prior close within 2% of prior 63-day low.
- Conflicting winner/loser labels are dropped from both sides.

Outcomes are measured at `t`: abnormal log-volume, range-volatility, absolute open gap, and squared close-to-close return. Each outcome is standardized against a rolling 252-day benchmark computed through `t-1`.

Tests use ticker-level winner-minus-loser means, then a t-test across tickers. The retail-minus-control difference-in-differences uses Welch t-tests across ticker effects. Holm correction is applied across all 24 tests.

## Results

Verdict: `RELATIVE_DID_ONLY_NO_ABSOLUTE_RETAIL_PASS`.

Retail/meme-risk winner-minus-loser effects are positive for all all-session outcomes, but none survive Holm correction. The strongest is abnormal volume: effect `+0.378` z-score, raw `p=0.041`, Holm `p=0.373`.

The large-cap control shows the opposite pattern: recent losers have significantly higher volume, range, gap, and RV than winners. All four all-session control effects are negative and Holm-significant.

The relative DiD therefore passes in three cells:

- All sessions, abnormal volume: retail-minus-control `+0.881`, Holm `p=0.00498`.
- All sessions, range-vol: retail-minus-control `+0.613`, Holm `p=0.04397`.
- Monday post-weekend, abnormal volume: retail-minus-control `+0.813`, Holm `p=0.01331`.

Interpretation: the evidence supports a relative asymmetry: retail/meme-risk winners do not display the large-cap loser-side dominance, and abnormal volume/range are materially more winner-tilted than controls. It does not support a strong absolute claim that retail winners themselves have a Holm-significant attention/volatility premium.

## Lookahead Controls

- `ret21_lag` is built with `close.pct_change(21).shift(1)`.
- Recent high/low labels use `close.shift(1).rolling(...)`.
- Outcome z-scores use `series.shift(1).rolling(...)` for the benchmark mean/std.
- There is no training/test split or model refit because this is an event-study diagnostic, not an OOS forecast.

## Files

- Script: `research_attention_utility_winner_focus_winner_side_rv_vo.py`
- Results: `research_attention_utility_winner_focus_winner_side_rv_vo_results.json`
- Figure: `research_attention_utility_winner_focus_winner_side_rv_vo_summary.png`

Run:

```bash
uv run python experiments/research_attention_utility_winner_focus_winner_side_rv_vo/research_attention_utility_winner_focus_winner_side_rv_vo.py
```

## Limitations

- No brokerage-login, Google Trends, Reddit, or Stocktwits attention data.
- Earnings-window attention is not tested; reliable point-in-time earnings dates were outside the free-data scope.
- Daily OHLCV cannot isolate market-close attention from intraday order flow.
- Ticker-level tests reduce but do not eliminate common-date cross-sectional dependence.
- This should be treated as a follow-up trigger, not causal evidence.
