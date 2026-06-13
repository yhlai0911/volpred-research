# Codex 24h Source Review: mile_77795ca2

**Article**: `mile_77795ca2` - Fed 開會那天 VIX 跳了 5 點，然後呢？

**Experiment**: `K514`

**Date**: 2026-06-12

**Verdict**: FAIL, corrected with errata

## Scope

This review checked whether the production article's numerical claims and methodological framing are supported by:

- `storage/reports/feed.json`
- `storage/drafts/k514_general_draft.md`
- `experiments/k514/k514_fomc_surprise.py`
- `experiments/k514/k514_fomc_surprise_results.json`
- `scripts/article_k514_charts.py`
- `storage/sentiment/vix_historical.csv`

## Findings

### HIGH: The 2007-09-18 opening example had the wrong VIX direction

The article originally said the 2007-09-18 FOMC cut made VIX jump from around 25 by more than 6 points. Local VIX history shows the opposite close-to-close move: VIX closed at 26.48 on 2007-09-17 and 20.35 on 2007-09-18, a -6.13 point close-to-close decline. The article now says VIX was near 25 intraday but closed down by about 6.13 points.

Impact: this was a public factual error in the article hook. It did not overturn the K514 result, because K514 uses signed `vix_change` and the article's later model interpretation already treats negative VIX changes as dovish.

### MEDIUM: DM and OLS significance were overstated for overlapping 21-day targets

K514 uses daily 21-day forward realized volatility targets. These targets overlap heavily, but the OOS DM statistic in `k514_fomc_surprise.py` uses a simple standard error, and the in-sample OLS t-stats also use conventional covariance estimates. The raw DM t=+3.89 is still an OOS warning, but the article's original "strict statistical test" framing was stronger than the code supports.

Impact: corrected wording now describes the analysis as sample-in/sample-out checks and adds a caveat that the raw DM result is not HAC/Newey-West corrected.

### LOW: Experiment README was placeholder-only

`experiments/k514/README.md` still contained planning placeholders even though the experiment had produced a production article. The README was replaced with a source-bound summary, result table, caveats, and artifact list.

### PASS: Core article numbers are traceable

The following article claims match `k514_fomc_surprise_results.json` after the wording correction:

- Data range: 2004-01-02 to 2025-12-30.
- FOMC meetings: 165.
- h=21 regression sample: 5,240 observations.
- h=21 VIX-surprise in-sample t-stat: -8.18.
- h=21 delta R2: 0.74 percentage points.
- OOS raw DM t-stat: +3.89, p=0.0001.
- Strategy backtest: 4,778 days, about 19 years.
- Sharpe: buy-and-hold 0.516, 12/VIX baseline 0.628, surprise overlay 0.599.
- Max drawdown: buy-and-hold -59.6%, 12/VIX baseline -30.8%, surprise overlay -32.2%.
- Regime correlations: 2010-2014 h=21 r=-0.41, p=0.008; 2020-2025 h=21 r=+0.37, p=0.016.
- Hawkish versus dovish h=21 t-stat 0.85, p=0.40.

### PASS: Strategy timing is lagged

The strategy code sets `w_base = (12.0 / vix).clip(0, 1).shift(1)` and `w_surprise = (w_base + adjustment.shift(1)).clip(0, 1)` before multiplying by same-row SPY returns. I did not find a same-day signal multiplied by same-day return pattern in the strategy backtest.

## Actions Taken

- Corrected the 2007-09-18 VIX direction in `storage/drafts/k514_general_draft.md` and `storage/reports/feed.json`.
- Softened "strict statistical test" language in the draft and feed entry.
- Added a caveat that the 21-day OOS DM result uses non-HAC standard errors.
- Replaced the placeholder K514 README with a reproducible experiment summary.

## Follow-Up

No new article is required after the correction. A future K514b should recompute the OOS comparison with a Harvey-Leybourne-Newbold or Newey-West/HAC DM variant for overlapping h=21 losses, and ideally replace the VIX-change proxy with a fed funds futures surprise measure.
