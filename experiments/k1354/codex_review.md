# K1354 Codex Source Review

Review date: 2026-06-21  
Reviewer: Codex (`codex-vscode`)  
Scope: `experiments/k1354/K1354.py`, `K1354_results.json`, `README.md`,
derived CSV panels, and generated figures.

## Verdict

**PASS_SOURCE_REVIEW_FOR_NULL_RESULT**

The implementation supports the reported **NULL** conclusion. I found no
source-level issue that would turn the result into a positive gamma-cliff
finding.

## Checks

- **Experiment triplet**: PASS. `README.md`, `K1354.py`, and
  `K1354_results.json` are present under `experiments/k1354/`.
- **Data provenance**: PASS. Results record yfinance as source, ticker SPY,
  requested period, usable sample (`1993-02-01` to `2026-06-18`), trading-day
  count (`8403`), event count (`399`), and cache path.
- **Calendar construction**: PASS. Monthly OPEX is generated from the third
  Friday rule and adjusted to the previous SPY trading day if the nominal date
  is closed. June 2026 is not included as evaluable because post-event days are
  unavailable in the sample.
- **Lookahead policy**: PASS. The event study uses known calendar dates only.
  The script also creates the explicit forecasting-style lag
  `opex_pre3_calendar_signal_lag1 = signal.shift(1)`.
- **Unit of inference**: PASS. Tests operate on one row per event month, not
  pooled daily rows.
- **Control design**: PASS with limitation. Same-month non-event controls
  excluding offsets `-5..+5` reduce seasonality drift. They do not control for
  all macro/event news within the same month, which is disclosed.
- **Statistical gate**: PASS. The positive finding threshold is stricter than a
  plain p-value: event-level directional `|t| > 3.0`, Bonferroni alpha
  `0.0125`, and bootstrap CI/p in the pre-registered direction.
- **Result interpretation**: PASS. README and JSON both state NULL. The
  expiration-day lower range variance is labeled as unadjusted suggestive and
  explicitly not a gamma-cliff confirmation.
- **Figures**: PASS. Both PNGs render and show the same NULL pattern as the
  result table.

## Key Result Audit

- `pre3_minus_control`: mean `+2.09e-6`, `t=0.31`, bootstrap CI crosses zero.
  This is the wrong direction for pre-OPEX suppression.
- `post3_minus_pre3`: mean `-3.92e-6`, `t=-0.51`, bootstrap CI crosses zero.
  This is the wrong direction for post-OPEX release.
- `expiration_minus_control`: mean `-1.51e-5`, `t=-2.22`, bootstrap one-sided
  p `0.0144`. This misses Bonferroni alpha `0.0125` and Harvey-style `|t|>3`.
- `quad_vs_nonquad_post3_minus_pre3`: bootstrap CI crosses zero; no stronger
  quad-witching release.

## Knowledge Entry Decision

No `knowledge.json` entry is written in this task because the task brief says
knowledge promotion requires `CONDITIONAL_PASS` minimum. The NULL result is
preserved in experiment artifacts and the task completion receipt.

## Residual Risk

This is a free-data daily-OHLC proxy test. It cannot observe dealer gamma
exposure, strike-level open interest, or intraday hedging flows. A future
positive/negative mechanism test would need historical options data and
intraday SPX/SPY data.
