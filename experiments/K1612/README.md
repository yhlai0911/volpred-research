# K1612 - FOMC language complexity and post-release volatility

## Question

Do FOMC statement / minutes readability and hedged-risk tone predict post-release SPY volatility persistence and VIX term-structure changes?

Task brief:

- `K1612`: FOMC statement/minutes language complexity, readability, and hedging tone.
- Public sources: official Federal Reserve FOMC calendar HTML links plus yfinance `SPY`, `^VIX`, `^VIX3M`, and `^VIX9D`.

## Motivation and prior evidence

The prior is mixed. FOMC communication is known to move markets, and prior text-analysis literature treats central-bank language as measurable information. VolPred memory also records that 2024-12-18 was a large Fed-related risk event. At the same time, existing VolPred VIX term-structure evidence is cautious: VIX/VIX3M ratios can be useful descriptively but have weak or unstable daily out-of-sample forecasting power.

K1612 therefore asks a narrow question: whether simple, public, deterministic text metrics add predictive content around FOMC document releases. It does not assume the text variables are tradable or causal.

## Literature checked before design

- Hansen, McMahon, and Prat (2018), Quarterly Journal of Economics, "Transparency and Deliberation Within the FOMC": motivates treating FOMC text as measurable communication.
- Rosa (2013), Federal Reserve Bank of New York Economic Policy Review, "Do FOMC minutes matter to markets?": motivates testing minutes at their public release date rather than backdating them to the meeting day.
- Doh, Kim, and Yang (2020), Federal Reserve Bank of Kansas City, "How You Say It Matters: Text Analysis of FOMC Statements Using Natural Language Processing": motivates tone / uncertainty dictionaries.
- St. Louis Fed Economic Synopses (2014), "The Rising Complexity of the FOMC Statement": motivates measuring statement readability and length.

## Data

Fed source:

- Official FOMC calendar: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`
- HTML documents scraped from official Fed statement and minutes links.
- The available calendar sample contains `87` documents from `2021-01-27` to `2026-06-17`.
- Documents split into `44` statements and `43` minutes.

Market source:

- yfinance adjusted close via `yf.download(auto_adjust=True)`.
- `SPY`: `1,392` observations from `2020-12-15` to `2026-07-02`.
- `^VIX`: `1,393` observations from `2020-12-15` to `2026-07-02`.
- `^VIX3M`: `1,389` observations from `2020-12-15` to `2026-07-02`.
- `^VIX9D`: `1,389` observations from `2020-12-15` to `2026-07-02`.

Text metrics:

- Statements: median `365` words, median Flesch-Kincaid grade `11.2875`, median hedge words per 1,000 words `12.2577`, median risk/uncertainty words per 1,000 words `36.8778`.
- Minutes: median `7,509` words, median Flesch-Kincaid grade `15.6381`, median hedge words per 1,000 words `16.8737`, median risk/uncertainty words per 1,000 words `20.3623`.

## Method

Each document is treated as observable only at its public release date.

- Statements use the meeting date from the official statement URL.
- Minutes use the `Released Month DD, YYYY` date shown in the official Fed calendar.
- Forward targets start on the next trading day after the release-aligned market date.
- Same-day SPY returns are not used as targets.
- The lagged volatility control is 22-trading-day SPY realized volatility shifted by one day.

Text predictors:

- `complexity_z`: average within-document-type z-score of word count, average sentence length, Flesch-Kincaid grade, and lexical diversity.
- `hedged_risk_tone_z`: average within-document-type z-score of hedge-word intensity and risk/uncertainty-word intensity.

Targets:

- `fwd5_spy_rv_ann`: annualized SPY realized volatility over the next 5 trading days.
- `fwd22_spy_rv_ann`: annualized SPY realized volatility over the next 22 trading days.
- `delta_vix9d_vix_5d`: 5-trading-day change in `^VIX9D / ^VIX`.
- `delta_vix_vix3m_22d`: 22-trading-day change in `^VIX / ^VIX3M`.

Formal regressions use OLS with HAC maxlags 1. Pooled document regressions control for lagged 22-day RV, VIX level, `^VIX9D / ^VIX`, and a minutes indicator. Statement-only and minutes-only regressions omit the minutes indicator. High-low tercile bootstrap diagnostics use 3,000 reps with seed `42`.

## Results

Verdict: `WEAK_MIXED_SIGNAL_NEEDS_CONFIRMATION`.

Sample:

- Event panel rows: `87`.
- Rows with 5-day forward RV: `87`.
- Rows with 22-day forward RV: `86`.

Main release-aligned pooled regressions:

- Complexity does not significantly predict 5-day SPY realized volatility: coefficient `0.0101`, HAC `t=0.71`, `p=0.477`, `n=86`.
- Complexity does not significantly predict 22-day SPY realized volatility: coefficient `0.0020`, HAC `t=0.16`, `p=0.876`, `n=86`.
- Hedged-risk tone does not significantly predict 5-day SPY realized volatility: coefficient `-0.0018`, HAC `t=-0.26`, `p=0.794`, `n=86`.
- Hedged-risk tone does not significantly predict 22-day SPY realized volatility: coefficient `-0.0094`, HAC `t=-1.14`, `p=0.256`, `n=86`.
- Complexity is positive for the 22-day `^VIX / ^VIX3M` change: coefficient `0.0414`, HAC `t=2.58`, `p=0.0099`, `n=86`.
- Hedged-risk tone is not significant for the 22-day `^VIX / ^VIX3M` change in the pooled regression: coefficient `-0.0195`, HAC `t=-1.56`, `p=0.118`, `n=86`.

Statement-only meeting-day regressions:

- Complexity has a borderline 5-day SPY RV coefficient: `0.0258`, HAC `t=1.80`, `p=0.0717`, `n=43`.
- Complexity is not significant for 22-day SPY RV: coefficient `0.0029`, HAC `t=0.15`, `p=0.881`, `n=43`.
- Hedged-risk tone is negative for 22-day `^VIX / ^VIX3M` change: coefficient `-0.0420`, HAC `t=-2.37`, `p=0.0176`, `n=43`.
- Neither statement complexity nor hedged-risk tone significantly predicts the 5-day `^VIX9D / ^VIX` change.

Bootstrap diagnostics:

- Pooled top-tercile complexity documents have higher 5-day SPY RV than bottom-tercile documents: high-minus-low `0.0547`, 95% CI `[0.0194, 0.0898]`, `p=0.0013`.
- Statement top-tercile complexity documents have higher 5-day SPY RV: high-minus-low `0.0617`, 95% CI `[0.0165, 0.1055]`, `p=0.0053`.
- Statement top-tercile hedged-risk tone documents have lower 22-day SPY RV: high-minus-low `-0.0628`, 95% CI `[-0.1193, -0.0170]`, `p=0.0047`.
- These tercile results are descriptive diagnostics. They are not the main adjusted predictive conclusion because the corresponding adjusted regressions are weaker or non-significant.

## Interpretation

K1612 does not support the strong claim that FOMC language complexity reliably predicts post-release realized volatility persistence. The adjusted realized-volatility regressions are mostly non-significant.

There is weak, mixed evidence that text metrics relate to VIX term-structure adjustment, especially the 22-day `^VIX / ^VIX3M` change. But the signs are not uniform across complexity and hedged-risk tone, the sample is small, and multiple targets were checked. The honest conclusion is that simple FOMC readability/tone metrics are worth tracking as event-context features, not yet as a standalone forecasting signal.

## Files

- `K1612.py`: reproducible script.
- `K1612_results.json`: full results and metadata.
- `data/fed_document_calendar.csv`: release-aligned official Fed document index.
- `data/fed_document_text_metrics.csv`: deterministic readability and tone metrics.
- `data/fed_texts/`: raw extracted official Fed article text.
- `data/yfinance_market_close.csv`: yfinance adjusted close panel.
- `data/market_features_daily.csv`: lagged RV and VIX term-structure features.
- `data/event_panel.csv`: merged document / market target panel.
- `data/regression_results.csv`: OLS-HAC regression outputs.
- `data/bootstrap_high_low_results.csv`: high-low tercile bootstrap diagnostics.
- `figures/fig1_text_metrics_by_release.png`: document metric time series.
- `figures/fig2_regression_tstats.png`: pooled regression t-statistics.
- `figures/fig3_bootstrap_high_low.png`: bootstrap high-low diagnostics.

## Limitations

- The official calendar page available in this runtime provides HTML statement/minutes links for 2021-2026 only, so sample size is modest.
- Minutes are tested at their public release dates, not at the earlier meeting dates; this avoids lookahead but differs from a pure meeting-day event study.
- Readability and dictionary tone metrics are deterministic proxies, not a structural model of Federal Reserve intent.
- Event targets can overlap, especially 22-trading-day horizons; HAC maxlags 1 and bootstrap diagnostics reduce but do not eliminate small-sample dependence risk.
- Multiple metrics and multiple targets were inspected, so isolated p-values need out-of-sample confirmation before publication claims.
