# K1358: AI Labor Exposure and Sector ETF Volatility

## Motivation

This experiment tests whether sectors with higher AI labor-income exposure
behave differently after AI/labor-market shocks: higher forward RV, higher
downside semivariance, higher co-movement with SPY, or better OOS volatility
forecasting when AI-labor shock features are added.

The intended mechanism is a household human-capital channel: if workers in a
sector face more AI-related labor-income risk, sector risk-bearing and
volatility may change after AI adoption or layoff news.

## Prior Internal Checks

- K415/K982/K809 and related sector-dispersion tests found that sector ETF
  dispersion/correlation signals often lose once VIX is controlled.
- K1529 showed that ETF-sector event studies need strict event-window and
  date-clustered inference; weak ETF proxies should not be promoted as
  firm-level evidence.
- K1355/K1357 recorded the multi-asset pooled-DM rule: average same-date
  cross-asset loss differentials before DM.

## External Anchors

- Felten, Raj, and Seamans (2021), *Strategic Management Journal*, "Occupational,
  Industry, and Geographic Exposure to Artificial Intelligence": source of
  AIOE/AIIE scores.
- AIOE GitHub repository, `AIOE_DataAppendix.xlsx`: Appendix B contains AIIE
  scores by four-digit NAICS industry.
- BLS/FRED labor series: `PAYEMS` and `CES0500000003`.
- GDELT DOC 2.0 TimelineVolRaw for daily AI-labor news-attention counts.

## Data

- Sector ETFs: `XLB`, `XLE`, `XLF`, `XLI`, `XLK`, `XLP`, `XLU`, `XLV`, `XLY`,
  `XLRE`, `XLC`.
- Market controls: `SPY`, `^VIX`.
- yfinance daily OHLCV, `auto_adjust=False`, sample starts 2017-01-01.
- OOS forecast evaluation starts 2020-01-01.
- AIIE industry scores are mapped to sector ETFs by transparent NAICS-prefix
  buckets; this is not holdings-level labor exposure.

## Shock Proxies

AI-labor news shock:

- GDELT query:
  `("artificial intelligence" OR "generative AI" OR ChatGPT OR automation) (jobs OR layoffs OR workforce OR employment OR labor OR workers)`.
- Daily article-count share is converted to a past-rolling z-score.

BLS/FRED labor shock:

- `PAYEMS` monthly employment change residual z-score.
- `CES0500000003` monthly average-hourly-earnings log-change residual z-score.
- Approximate availability is next month plus four business days, then
  forward-filled to daily and lagged in forecasting.

## Tests

Event DID:

- For each date, compute high-AI-exposure sector average minus low-AI-exposure
  sector average for forward 5-day RV, forward 5-day downside semivariance, and
  forward 21-day correlation to SPY.
- Compare that high-minus-low spread on AI/labor shock days versus non-shock
  days using fixed-seed bootstrap.

OOS forecast:

- Target at row `t`: sector close-to-close RV over `t+1..t+5`.
- Baseline: HAR RV features + lagged VIX z-score + lagged SPY 5-day RV.
- Challenger: baseline + lagged AI-news × sector exposure, BLS-labor-shock ×
  sector exposure, and joint-shock × sector exposure.
- Per-sector expanding OLS with annual refits.
- Pooled DM averages same-date cross-sector QLIKE loss differentials before
  `h=5` DM.

## Lookahead Policy

All forecast predictors are explicitly lagged:

```python
frame["log_rv_1_lag1"] = np.log(rv).shift(1)
frame["log_rv_5_lag1"] = np.log(rv.rolling(5).mean()).shift(1)
frame["log_rv_22_lag1"] = np.log(rv.rolling(22).mean()).shift(1)
frame["vix_z_lag1"] = frame["vix_z"].shift(1)
frame["spy_rv_5_lag1"] = np.log(spy_rv_5).shift(1)
frame["ai_news_x_exposure_lag1"] = (...).shift(1)
frame["labor_x_exposure_lag1"] = (...).shift(1)
frame["joint_shock_x_exposure_lag1"] = (...).shift(1)
```

Rolling z-scores use past rolling moments through `x.shift(1)`.

## Success Criteria

`CONDITIONAL_PASS_PROXY` requires:

- event DID lower CI above zero for both forward RV and downside semivariance;
  and
- OOS pooled QLIKE DM `t < -3.0`, with at least 7 of 11 sectors improving.

`EVENT_ONLY_WEAK` is used if only event-window evidence survives. `MIXED_WEAK`
is used for forecast evidence that is directionally favorable but below Harvey
strength. Otherwise the result is `NULL_PROXY`.

## Results

Verdict: `NULL_PROXY`.

Sector exposure mapping:

- Highest AIIE proxy sectors: `XLF` (`+2.05`), `XLK` (`+1.32`), `XLC`
  (`+0.78`), `XLV` (`+0.55`).
- Lowest AIIE proxy sectors: `XLB` (`-0.80`), `XLP` (`-0.74`), `XLI`
  (`-0.37`), `XLE` (`-0.16`).

Event DID:

- Forward 5-day RV high-minus-low AI exposure spread is **lower** on shock days:
  point `-0.0001007`, CI `[-0.0001812, -0.0000196]`.
- Forward 5-day downside semivariance DID is not significant:
  point `-0.0000167`, CI `[-0.0000704, +0.0000389]`.
- Forward 21-day correlation-to-SPY DID is positive:
  point `+0.0147`, CI `[+0.0014, +0.0280]`.
- Event dates: 410; non-event dates: 1,929.

OOS forecast:

- Pooled `HAR_VIX_AI_LABOR` vs `HAR_VIX` QLIKE loss differential:
  `+0.04937`, DM `t=+1.790`, `p=0.0736`.
- Only 2 of 11 sectors improve on QLIKE.
- The challenger helps `XLF` in point estimate (`+13.72%`) but hurts most
  sectors, including `XLK -23.71%`, `XLP -26.84%`, and `XLY -23.52%`.

Interpretation: the free-data proxy finds modest co-movement evidence, not
higher volatility or downside risk in high-AI-exposure sectors after shocks.
The forecasting model is worse than the HAR+VIX baseline. This is not a
promotable AI-labor-risk finding.

## Claim Ceiling

This experiment cannot identify household portfolios, worker-level labor
income, firm-level AI adoption, or true layoff shocks. It is a sector ETF proxy
using public AIIE, GDELT, BLS/FRED, and yfinance data.

## Files

- `K1358.py`
- `K1358_results.json`
- `K1358_ai_labor_sector_vol.png`
- `codex_review.md`
- `data/`
