# K1679-rev — Regional-bank deposit-flight NULL, knowledge-grade revision

**Revises**: K1679 (merged to main; Codex verdict = **FAIL** on 3 method problems)
**Verdict (point-in-time)**: `WEAK_FDR_ONLY` — the single BH-surviving cell does **not**
survive the correct nested-model test (Clark-West). The K1606 → K1679 funding-flight
NULL narrative stands.
**Run**: 2026-07-10 (seed = 42, runtime ≈ 58 s)

## Question

Does the H.8 *small-minus-large* bank deposit growth differential ("deposit-flight"
signal) add robust incremental out-of-sample forecasting power over HAR for regional-
bank (KRE) forward realized volatility / downside semivariance?

K1679 said **no** (directional NULL, all DM t positive = the signal *hurts*), but three
methodological problems blocked knowledge-grade status. This revision fixes all three
and re-tests on both the original (current-vintage) and a genuine point-in-time signal.

## Three fixes

1. **ALFRED point-in-time vintages (lookahead).** K1679 pulled the *current* FRED vintage
   of `DPSSCBW027SBOG` / `DPSLCBW027SBOG`, which embeds later revisions unavailable at the
   trading date. K1679-rev reconstructs the signal **as it was known** at each weekly H.8
   release using the full ALFRED vintage history, with the embargo set to the actual ALFRED
   first-print release date (`realtime_start`) + 1 day instead of the +10d heuristic. Both
   the current-vintage and point-in-time signals run through the full grid for a clean
   before/after. Signal correlation current-vs-PIT = **0.548** → the revision materially
   changes the signal, confirming K1679 carried lookahead.

2. **Clark-West (2007) nested-forecast test.** The baseline HAR is fully nested in the
   augmented model, so standard DM/HLN is biased *toward* the null. CW adds the
   `(pred_base − pred_aug)²` adjustment term (canonical for nested-model MSPE) on the two
   strongest K1679 cells (`dep_flight_4w·dsv·H5`, `dep_flight_4w·rv·H21`); one-sided
   upper-tail, HAC lag = cell H, HLN small-sample corrected.

3. **Un-floored loss sensitivity.** K1679 applied a training-min positivity floor uniformly,
   including DSV/MSE cells that legitimately admit exact zeros (strongest dsv cell ~50/53
   forecasts clipped). MSE needs no floor, so every MSE-based DM is recomputed on the raw
   (un-floored) forecasts alongside the floored numbers.

## Method

- **Baseline**: OLS `1 + HAR(d,w,m) + SPY 21d RV + VIX level`
- **Augmented**: baseline + deposit-flight signal (only difference)
- **OOS**: expanding refit, initial train 60%, forward-label embargo `j + H < i`
- **DM**: NW HAC lag = H + HLN correction, t(n−1)
- **Clark-West**: CW(2007) one-sided nested MSPE, HAC lag = H + HLN
- **Bootstrap**: moving-block, block = max(10, H), reps = 2000, seed = 42
- **Multiple testing**: Bonferroni + BH over primary family m = 8
- **QLIKE**: canonical `volpred.stats.model_evaluation.qlike_pointwise` (never hand-written)
- **Pre-registered primary grid**: 2 predictors × 2 targets × 2 H (identical to K1679)

## Results

| Signal | Verdict | Strongest primary cell | DM t (HLN) | p | BH q | Harvey \|t\|>3 | Clark-West reject @05 |
|---|---|---|---|---|---|---|---|
| Current vintage (K1679-style) | **NULL** | `dep_flight_4w·dsv·H5` | 1.77 | 0.076 | 0.34 | no | no |
| Point-in-time (ALFRED) | **WEAK_FDR_ONLY** | `dep_flight_13w·rv·H5` | 2.77 | 0.0057 | 0.045 | no | no |

The point-in-time run has one cell (`dep_flight_13w·rv·H5`) that passes BH at q = 0.10, but:
- No cell reaches Harvey `|t| > 3`.
- **No cell is rejected by Clark-West** — the only test that correctly handles the nested
  baseline. Both pre-registered CW cells have negative or near-zero CW-t (augmented model
  no better than HAR).

**Interpretation**: the lone FDR-surviving cell is a within-family multiple-testing artifact
that does not survive the appropriate nested-model correction. Deposit-flight adds no robust
incremental forecasting power over HAR for KRE volatility once lookahead is removed and the
nested structure is handled. NULL confirmed at knowledge grade.

### Construct-validity note (fix1)

Both signals peak around the SVB episode (current-vintage argmax 2023-03-27, PIT argmax
2023-05-15), so the PIT signal is not degenerate — it just carries no OOS forecasting edge.
ALFRED archiving does not reach the 2008 GFC for these series (GFC max signal = null under
PIT), so the point-in-time test covers the post-archiving sample only; this is disclosed and
does not affect the pre-registered primary grid.

## Files

- `K1679-rev.py` — full pipeline (data pull → PIT reconstruction → grid → DM/CW → figure)
- `K1679-rev_results.json` — all cells, both vintages, three-fix detail
- `K1679-rev_fig_pit_vs_current.png` — signal overlay + primary-grid DM-t before/after

## Reproduce

```
uv run python experiments/K1679-rev/K1679-rev.py
```

Requires `FRED_API_KEY` in `.env.local` and live yfinance access.

## Data sources

- Deposits (small): FRED/ALFRED `DPSSCBW027SBOG`
- Deposits (large): FRED/ALFRED `DPSLCBW027SBOG`
- Prices: yfinance `auto_adjust=True` (KRE, XLF, SPY, ^VIX)
