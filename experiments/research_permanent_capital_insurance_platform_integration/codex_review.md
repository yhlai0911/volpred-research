# Codex review — research_permanent_capital_insurance_platform_integration

Verdict: `PASS_WITH_CAVEATS`.

## Scope reviewed

- Script: `research_permanent_capital_insurance_platform_integration.py`
- Results: `research_permanent_capital_insurance_platform_integration_results.json`
- Tables: `data/panel_regressions.csv`,
  `data/manager_pre_post_metrics.csv`, `data/manager_post_pre_diffs.csv`,
  `data/event_windows.csv`
- Figures: `figures/panel_coefficient_shifts.png`,
  `figures/manager_post_pre_diffs.png`

## Checks

### Event dating and information set

PASS for a regime/event study.  The script records both announcement dates and
integration close dates in `data/insurance_events.csv`.  The `post` dummy begins
only at the close / integration date, while announcement windows are analyzed
separately.  This is not a trading strategy and does not multiply same-day
signals by same-day returns.

### Confounding control

PASS_WITH_CAVEAT.  The first run without time controls showed a broad regime
shift, but that could be a 2020-2024 macro-regime artifact.  The final script
uses manager fixed effects plus calendar-year fixed effects and date-clustered
standard errors.  This materially downgrades the interpretation: residual RV
and credit sensitivity no longer pass, while beta-composition interactions do.

Remaining caveat: year fixed effects are coarse.  A publication-grade version
should add more granular event-time controls, matched non-integrated peers, or a
staggered-difference-in-differences design.

### Statistical threshold

PASS.  The README reports Harvey-style `|t| > 3.0` explicitly.  Primary passes:

- `SPY:post`, t=3.08
- `XLF:post`, t=4.42
- downside `KIE:post`, t=4.88

Primary non-passes:

- unconditional `KIE:post`, t=-2.88
- `credit_z:post`, t=0.83
- residual RV `post`, t=-1.94

The final verdict is therefore correctly narrowed to
`BETA_COMPOSITION_SHIFT_NO_RV_CREDIT_PASS`.

### Data and proxy handling

PASS_WITH_CAVEAT.  yfinance adjusted close is cached and reproducible.  The
script attempts FRED `BAMLH0A0HYM2`, but the accessible CSV only covered
2023-06 onward, so it falls back to `LQD_return - HYG_return`.  The results and
README disclose this as a tradable credit-stress proxy, not a true OAS history.

Brookfield uses `BN` as a longer-history proxy because current `BAM` begins
after the 2022 spinoff.  This is disclosed and acceptable for a backlog
experiment, but it is not a clean BAM-only stock history.

### Result strength

PASS.  The script does not claim that insurance integration causes higher
volatility.  It reports the stronger supported result: public AAM equities
appear to load more on broad market / financial-sector beta post-integration,
while residual RV and credit-stress sensitivity do not pass.

## No blockers

The experiment is safe to record in knowledge as a beta-composition shift with
important proxy and causal-inference caveats.  It should not be used as a
production trading signal or as a claim that permanent-capital integration
directly increases residual volatility.
