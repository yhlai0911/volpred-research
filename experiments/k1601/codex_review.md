# K1601 Codex Source Review

Review date: 2026-07-02

Verdict: `CONDITIONAL_PASS`

Scope: source code, README, results JSON, and generated OOS CSV for K1601.

## Checks

### Lookahead

PASS.

- VIX, JLN, and SPF predictors are daily-aligned and then explicitly shifted by
  one trading day in `K1601.py`.
- SPF disagreement is conservatively known only from the first day of the next
  quarter.
- JLN monthly uncertainty is conservatively known only after a two-month lag.
- Rolling regime thresholds use `series.shift(1).rolling(...)`, so thresholds
  exclude the current row and future rows.
- Forward RV target is `t+1` through `t+21`.
- Expanding OOS training uses `target_end_pos < forecast_pos`; CSV audit found
  zero rows where the latest training target overlaps the forecast origin.

### Statistical Methods

PASS.

- OOS loss uses canonical `volpred.stats.model_evaluation.qlike_pointwise`.
- Pairwise DM uses canonical `dm_test(..., h=21)`.
- MCS uses `volpred.stats.mcs.model_confidence_set(alpha=0.10, n_boot=1000, seed=42)`.
- Harvey gate requires QLIKE improvement and DM `t < -3`.
- Regime diagnostics use Newey-West HAC lag 21 plus moving-block bootstrap with
  block length 21. These are diagnostics only; the forecast gate is OOS QLIKE.

### Seed

PASS.

All random procedures use `SEED = 42`: NumPy global seed, moving-block
bootstrap, and MCS bootstrap.

### Numeric Consistency

PASS.

Key values in README match `K1601_results.json`:

- VIX high-regime agreed vs disagreed forward vol: 0.1850 vs 0.2396, HAC t=-2.97.
- JLN high-regime agreed vs disagreed forward vol: 0.1389 vs 0.2233, HAC t=-4.71.
- OOS n=7,116.
- VIX baseline QLIKE=0.3168.
- VIX_SPF QLIKE=-1.19% improvement, DM t=+0.72.
- VIX_SPF_JLN QLIKE=+0.84% improvement, DM t=-0.38.
- JLN_SPF QLIKE=-68.57% improvement, DM t=+4.76.

### Research Honesty

PASS with caveats.

The README does not overclaim. It states the descriptive regime sign and clearly
separates that from the failed OOS forecast gate. It also discloses the two main
proxy limitations: SPF RGDP dispersion is not the consumer-disagreement measure
from Gambetti et al., and FRED JLN is revision-corrected rather than vintage.

## Conditions for Knowledge Entry

If written to `knowledge.json`, the entry should say:

- Result is `DIRECTIONAL_ONLY`, not a forecasting PASS.
- In this SPY adaptation, high uncertainty plus high SPF disagreement has higher
  forward vol/tail than high uncertainty plus low SPF disagreement.
- SPF disagreement does not pass the Harvey/MCS OOS forecast gate beyond VIX.
- The result is proxy-limited and should not be framed as a replication of the
  macro agreed/disagreed uncertainty paper.
