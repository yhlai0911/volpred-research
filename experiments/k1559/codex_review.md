# K1559 Codex Source Audit

Audit verdict: PASS_WITH_CAVEATS.

## Scope

Reviewed `experiments/k1559/k1559.py` after the final run that produced
`k1559_results.json` with `verdict=CONDITIONAL_PASS`.

## Checklist

1. Lookahead absence: PASS.
   `forward_window_stats()` builds future targets with
   `vals[i + 1 : i + 1 + h]`, so same-date return at signal date `t` is not
   included in `fwd_rv5`, `fwd_rv22`, gap, or drawdown targets
   (`k1559.py:150-181`). Event signals are constructed separately from the
   same-day data-quality flags (`k1559.py:221-249`).

2. Target and source transparency: PASS.
   The script fixes `START_DATE`, `END_DATE`, yfinance source, SPY reference
   calendar, 28-ETF universe, and adjusted-close return construction
   (`k1559.py:66-105`, `k1559.py:128-145`, `k1559.py:216-219`).

3. Controls and formal tests: PASS.
   Panel tests include asset fixed effects, lagged 22d RV, dollar volume, price,
   and SPY absolute return controls (`k1559.py:294-328`). HAC standard errors
   are used with horizon-based maxlags (`k1559.py:329-331`).

4. Multiple testing: PASS.
   Holm-Bonferroni adjustment is implemented once over all event-target p-values
   (`k1559.py:185-202`, `k1559.py:541-551`).

5. Seed / reproducibility: PASS.
   NumPy and Python random seeds are fixed at 42 (`k1559.py:55-57`). The main
   reproducibility caveat is vendor data drift from yfinance; the result file
   stores the requested date range and each asset fetch status.

6. Conclusion strength: PASS_WITH_CAVEATS.
   The final code deliberately prevents broad PASS unless events are cross-asset
   diversified and missing rows are sufficiently observed (`k1559.py:571-599`).
   This correctly downgrades the empirical result to `CONDITIONAL_PASS` because
   missing-row evidence is only one observation and most zero-volume/stale-price
   evidence is concentrated in QAT/KSA/UAE.

## Residual Risk

The binary risk outcomes use linear probability models with HAC standard errors.
That is acceptable for this screening experiment, but a publication-grade follow
up should add clustered or block-bootstrap inference by date and asset, because
stacked ETF panels can share cross-sectional shocks.
