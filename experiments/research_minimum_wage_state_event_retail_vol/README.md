# Minimum-Wage Effective Dates and Restaurant/Retail Realized Volatility

## Motivation

The backlog question asked whether state minimum-wage effective dates can be
used as clean regulatory cost shocks for labor-intensive restaurant and retail
stocks. The original idea was inspired by state-border discontinuity designs in
labor economics, but this experiment is narrower and more conservative: it is a
public equity event-window pilot, not a county-border or store-location
replication.

The test asks whether restaurant and retail baskets show higher realized
volatility or downside variance after public minimum-wage effective-date
clusters, relative to market and sector controls.

## Literature / External Context

- Dube, Lester, and Reich (2010), "Minimum Wage Effects Across State Borders:
  Estimates Using Contiguous Counties," Review of Economics and Statistics.
  https://irle.berkeley.edu/publications/scholarly-publications/minimum-wage-effects-across-state-borders-estimates-using-contiguous-counties/
- Card and Krueger, "The Effect of the Minimum Wage on Shareholder Wealth."
  https://davidcard.berkeley.edu/papers/minwage-shareholder.pdf
- Rao and Risch (2026), "Who's Afraid of the Minimum Wage? Measuring the
  Impacts on Independent Businesses Using Matched U.S. Tax Returns," Quarterly
  Journal of Economics. https://academic.oup.com/qje/article/141/1/373/8376639
- Luca and Luca, "Survival of the Fittest: The Impact of the Minimum Wage on
  Firm Exit." https://www.hbs.edu/ris/Publication%20Files/17-088_9f5c63e3-fcb7-4144-b9cf-74bf594cc308.pdf

## Data

- Event-date sources:
  - U.S. Department of Labor state minimum wage laws:
    https://www.dol.gov/agencies/whd/minimum-wage/state
  - DOL consolidated minimum wage table:
    https://www.dol.gov/agencies/whd/mw-consolidated
  - Economic Policy Institute minimum wage tracker:
    https://www.epi.org/minimum-wage-tracker/
  - National Conference of State Legislatures state minimum wages:
    https://www.ncsl.org/labor-and-employment/state-minimum-wages
  - California DIR fast-food minimum wage page:
    https://www.dir.ca.gov/dlse/minimum_wage.htm
- Market data: yfinance adjusted close, `auto_adjust=True`.
- Sample: 2020-01-02 to 2026-07-02 market data.
- Embedded events: 21 public effective-date clusters from 2021-01-01 through
  2026-07-01. The 2026-07-01 event is excluded by the script for 22-day tests
  because the post-event window is incomplete, leaving 20 usable events.

## Method

Target baskets:

- `restaurants`: MCD, SBUX, CMG, YUM, DRI, WEN, DPZ, TXRH, EAT, SHAK.
- `retail`: WMT, TGT, COST, DG, DLTR, TJX, ROST, M, KSS, BBY.
- `wage_sensitive`: equal-weight combination of restaurant and retail names.

Controls:

- `SPY`
- `XLY`
- `XLP`
- `low_labor_tech`: AAPL, MSFT, GOOGL, META, NVDA, ADBE, CRM, AVGO, INTU, ORCL.

For each event, the event date is mapped to the next trading day. For 10- and
22-trading-day windows, the script computes:

- pre-event annualized realized variance,
- post-event annualized realized variance,
- pre/post downside variance,
- log post/pre changes for each target and control,
- DID = target log-change minus control log-change.

The primary family is 12 tests: restaurant, retail, and combined baskets versus
XLY, SPY, and low-labor-tech controls for 22-day RV and downside variance.
Inference uses one-sample event-level t-tests, Wilcoxon p-values, 2,000-rep
bootstrap confidence intervals, and Holm/Bonferroni correction. The support
gate is:

`mean DID > 0`, `|t| >= 3.0`, `Holm p < 0.05`, and bootstrap CI lower bound > 0.

Placebo check: for the primary `wage_sensitive - XLY` 22-day RV cell, the
script samples 2,000 non-event calendar sets with the same event count and
compares their mean DID to the actual event mean.

## Results

Verdict: **NULL_PUBLIC_EVENT_STUDY**.

- Primary tests: 12.
- Positive support gate count: 0.
- Raw positive `t > 2` count: 0.
- Strongest positive cell: restaurants minus low-labor-tech 22-day RV
  (`mean DID = 0.1314`, `t = 0.9655`, Holm p = 1.0, bootstrap CI
  `[-0.1208, 0.4007]`).
- Strongest absolute t-stat cell: retail minus XLY 22-day downside
  (`mean DID = -0.2376`, `t = -1.0543`, Holm p = 1.0).
- Primary placebo: `wage_sensitive - XLY` 22-day RV event mean is `-0.1024`.
  It sits at the 1.1th percentile of the random non-event calendar distribution,
  with one-sided `p(placebo >= event) = 0.9890`.

Interpretation: the public effective-date calendar does not support the claim
that minimum-wage implementation dates robustly increase restaurant/retail
realized volatility relative to controls. If anything, the main placebo check
leans against an event-date RV spike in this public-equity proxy.

## Limitations

- This is not a true state-border discontinuity design.
- Public companies have geographically diversified store footprints; the script
  does not measure state-level employment or revenue exposure.
- Jan-1 minimum-wage changes are seasonal and partly anticipated. Benchmark DID
  and placebo tests reduce but do not eliminate that confounding.
- Effective-date clusters may be priced earlier at legislative passage,
  ballot, guidance, or earnings-call dates.
- The result is a null for this public calendar proxy, not evidence that
  minimum wages have no real effects on private firms, workers, or local
  business dynamics.

## Files

- `research_minimum_wage_state_event_retail_vol.py`: reproducible script.
- `research_minimum_wage_state_event_retail_vol_results.json`: full machine
  readable result.
- `data/event_panel.csv`: event-window DID panel.
- `data/summary_table.csv`: primary test summary.
- `data/placebo_primary_means.csv`: placebo calendar distribution.
- `figures/event_did_tstats.png`: primary t-stat diagnostics.
- `figures/primary_placebo_distribution.png`: placebo distribution.

Run:

```bash
uv run python experiments/research_minimum_wage_state_event_retail_vol/research_minimum_wage_state_event_retail_vol.py
```
