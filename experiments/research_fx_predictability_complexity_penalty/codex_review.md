# Codex Review

Verdict: **CONDITIONAL_PASS_WITH_SCOPE_LIMITS**

## Checks

- Triplet: PASS. The experiment folder contains `README.md`, the executable
  script, and `research_fx_predictability_complexity_penalty_results.json`.
- Data transparency: PASS. Results state Yahoo Finance tickers, local FRED macro
  files, period, generated panels, and OOS sample sizes.
- Lookahead: PASS. ETF features, macro features, and the left-tail threshold are
  all lagged with explicit `shift(1)` logic before month `t` prediction.
- Randomness: PASS. `SEED=42` is used for RFF features and bootstrap. The RFF
  per-cell seed uses deterministic `zlib.crc32`, not Python's process-randomized
  `hash()`.
- Benchmarks: PASS. Return uses the random-walk zero forecast; RV and left-tail
  use historical training-window baselines.
- Formal tests: PASS. The script reports Newey-West loss-differential t-stats,
  Clark-West adjusted return tests, and bootstrap Sharpe differences.
- Claim strength: PASS after conservative framing. The result does not claim FX
  return predictability; it only flags localized RV forecast improvement.

## Caveats

- This is an ETF/monthly/free-data proxy screen, not a spot-FX or macro-vintage
  replication of Kiliç (2025).
- The 2 benchmark-clearing RV cells are selected from 108 tested cells. They are
  follow-up candidates, not stand-alone publication evidence.
- RFF-vs-linear wins should not be overread. Linear Ridge is often worse than
  the simple benchmark, so beating linear Ridge is weaker than beating the
  random-walk / historical-mean baseline.

## Required Framing

Use this result as a **complexity ceiling / partial RV-only** finding. Do not
publish a return-forecasting or trading-alpha claim from this experiment.
