# Codex Review

Reviewer: Codex
Date: 2026-07-03
Experiment: `research_etf_dose_response`

## Verdict

**CONDITIONAL_PASS_SOURCE_REVIEW / research verdict PARTIAL_PUBLIC_PROXY_DOSE_RESPONSE**

The experiment is reproducible and the code-level lookahead controls are
acceptable. The empirical claim must remain narrow: only the 4-week increase in
California drought severity passes the pre-specified positive-dose `t>=3` gate
for 5d agriculture ETF RV. Wildfire acreage dose is directionally positive but
does not pass the continuous-dose t-stat gate.

## Checks

- Experiment triplet present:
  - `README.md`
  - `research_etf_dose_response.py`
  - `research_etf_dose_response_results.json`
- Data sources are explicit:
  - yfinance adjusted closes for `PCG/EIX/SRE/XLU/DBA/CORN/WEAT/SPY`
  - CAL FIRE California Fire Perimeters CSV
  - U.S. Drought Monitor California state statistics API
- Lookahead controls:
  - Wildfire targets begin on the first trading day strictly after `Alarm Date`.
  - CAL FIRE final acres are disclosed as ex-post physical-dose labels, not
    tradable same-day signals.
  - USDM `validStart` is shifted by `+2` calendar days for release timing, then
    drought signals enter regressions with one trading-day lag.
  - RV/downside baselines use lagged rolling windows.
- DSCI correction:
  - Initial code incorrectly weighted cumulative `D0..D4` by `1..5`.
  - Fixed to `D0 + D1 + D2 + D3 + D4`, bounded by `0..500`, because USDM
    traditional category percentages are cumulative.
- Gate logic:
  - Wildfire pass requires positive log-acre t-stat, monotone terciles, and
    high-minus-low bootstrap CI above zero.
  - Drought pass accepts either level DSCI or 4-week DSCI increase because the
    task explicitly asks about drought level increases.
- Randomness:
  - Bootstrap seed fixed as `SEED = 42`.

## Result Snapshot

- Overall verdict: `PARTIAL_PUBLIC_PROXY_DOSE_RESPONSE`.
- Wildfire gate pass count: `0`.
- Drought gate pass count: `1`.
- Passing cell: agriculture 5d RV on 4-week DSCI increase, coefficient `0.00325`,
  HAC `t=3.5355`, `p=0.000407`.
- Wildfire near miss: utility 5d RV log-acre coefficient `t=1.47`; acreage
  terciles are monotone and high-minus-low CI is positive, but this is not enough
  for a formal pass.
- Utility drought level effects are negative, so no broad utility-volatility
  drought claim is supported.

## Limitations

- State-level USDM is coarse and not matched to crop exposure or utility service
  territory.
- Final fire perimeter acres introduce ex-post severity information; the code
  avoids trading claims, but article language must preserve this caveat.
- Agriculture ETFs include non-California and roll-yield/basis effects.
- Daily close-to-close returns are too coarse for intraday emergency
  announcement or public-safety power-shutoff timing.

No blocking defects remain if the knowledge entry and any later article preserve
the narrow partial result and all proxy limitations.
