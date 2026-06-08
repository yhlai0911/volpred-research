# K770b — MEM / AMEM / HAR Unified-Target Comparison

## Motivation

`K770` was overturned because it compared models on mismatched forecast objects:
`MEM / HAR-ABS` were scored on `|r|`, while `GARCH / EWMA` were effectively scored
on `sqrt(sigma2)`. That makes QLIKE comparisons invalid.

`K770b` fixes the methodological bug by forcing all models into the **same target
space** before evaluation. This makes it the repo's canonical standardized
comparison baseline for the `MEM / AMEM / HAR` family.

## Models

- `MEM(1,1)`
- `AMEM(1,1)` with leverage
- `HAR-ABS`
- `GJR-GARCH(1,1)`
- `EWMA`

## Data

- Source: `yfinance`
- Assets: `SPY`, `GLD`, `0050.TW`
- OOS protocol: expanding window, 1-day-ahead

## Method

Two proxy-robust comparison layers were run:

1. **Approach A: absolute-return target**
   - all models converted to predict `E[|r_{t+1}|]`
   - `GJR / EWMA` mapped via `sqrt(sigma2) * sqrt(2/pi)`
2. **Approach B: variance target**
   - all models converted to predict `r^2_{t+1}`
   - `MEM / AMEM / HAR-ABS` mapped via `E[|r|]^2 * (pi/2)`

Scoring:

- `QLIKE` primary
- `MSE`, `MAE`
- pairwise `DM` tests
- `Harvey` strict threshold `|t| > 3.0`

## Key Results

Cross-asset summary from [`k770b_mem_unified_target_results.json`](./k770b_mem_unified_target_results.json):

- **Approach A average rank**: `AMEM = 1.67`, `MEM = 1.67`, `HAR-ABS = 3.33`, `GJR = 4.00`, `EWMA = 4.33`
- **Approach B average rank**: `AMEM = 1.67`, `MEM = 1.67`, `GJR = 3.33`, `HAR-ABS = 4.00`, `EWMA = 4.33`
- In both approaches, the reported cross-asset best model is `AMEM`

Per-asset top models:

- `SPY`: `AMEM` best under both target conventions
- `GLD`: `MEM` best, `AMEM` close second
- `0050.TW`: `MEM` best, `AMEM` close second

Selected Harvey-pass comparisons:

- `SPY`, Approach A: `AMEM` beats `HAR-ABS` (`DM = -7.46`)
- `SPY`, Approach A: `AMEM` beats `GJR` (`DM = -5.37`)
- `GLD`, Approach A: `HAR-ABS` beats `GJR` (`DM = -4.88`)
- `0050.TW`, Approach A: `AMEM` beats `GJR` (`DM = -12.54`)
- `0050.TW`, Approach A: `HAR-ABS` beats `GJR` (`DM = -11.05`)

## Interpretation

This experiment already answers the repo-level question:

- can `MEM / AMEM / HAR` be compared fairly on a standardized target?
- does the ranking survive target-space changes?

The answer is yes. Once the mismatch is fixed, `AMEM / MEM` remain strong, and
`HAR-ABS` is a legitimate benchmark rather than a discarded baseline.

## Limitation

`K770b` does **not** implement the exact `HAR-Q` variant referenced by later
standardization papers. So it is a strong **core duplicate** for generic
`HAR / MEM / AMEM standardized comparison` backlog items, but not a full
paper-exact replication of every HAR-family extension.

## Files

- `k770b_mem_unified_target.py` — canonical implementation
- `k770b_mem_unified_target_results.json` — results
- `README.md` — this summary
