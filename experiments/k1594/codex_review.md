# Codex Review - K1594

Review date: 2026-07-01

Verdict: `CONDITIONAL_PASS`

## Scope

Reviewed:

- `experiments/k1594/k1594.py`
- `experiments/k1594/k1594_results.json`
- `experiments/k1594/README.md`

The review treats K1594 as a KOWCPI-style mechanism test, not a faithful
replication of Lee-Xu-Xie (2024).

## Findings

### PASS - Data provenance

The script reads only the frozen local cache:

`experiments/k1571/data_cache.parquet`

No live download occurs.

### PASS - Lookahead discipline

Feature construction uses `.shift(1)` for every covariate. For a forecast at
date `t`, the calibration window is `[t-1000, t-1]`; the realized return at `t`
is not included in the quantile calculation. This satisfies the VaR convention
`signal from t-1, return at t`.

### PASS - Weighted quantile mechanics

`KOWCPI-lite` computes Gaussian-kernel weights on standardized lagged features,
then estimates a lower-tail weighted quantile of past returns. When weights
become too concentrated, they are shrunk toward uniform weights until Kish ESS
is at least 125. This is a reasonable guard against overfitting in a daily VaR
setting.

### PASS - Pre-OOS tuning

Bandwidth is selected on 2013-2014 validation and then frozen for 2015-2026
OOS. The OOS period is not used to choose bandwidths.

### PASS - VaR evaluation

The review confirms the script reports:

- mean pinball loss,
- VaR width,
- violation rate,
- Kupiec coverage p-value,
- Christoffersen independence p-value,
- Basel-style traffic light,
- Trinity pass,
- DM tests with Holm-adjusted p-values across cells/pairs.

### PASS - Conservative conclusion

The result `MIXED_WEAK` is supported:

- KOWCPI-lite has lowest mean pinball in 3/4 cells.
- KOWCPI-lite has 0/4 Trinity passes.
- No KOWCPI-lite comparison survives the strict `|t| > 3` plus Holm gate.
- Hit clustering remains severe, especially for HYG.

## Caveats

1. This is not a full KOWCPI replication; it is a finance-specific kernel
   weighted VaR quantile.
2. Christoffersen independence failures are economically important and should
   dominate the narrative over lower pinball loss.
3. The 1% alpha validation window has few tail observations, so bandwidth
   selection is noisy.
4. Only TLT and HYG are tested. A production claim would need cross-asset
   robustness.
5. ES/Fissler-Ziegel joint scoring is absent.

## Required Wording

Acceptable:

> KOWCPI-style weighting lowers pinball loss in several cells but does not pass
> the full VaR backtesting gate because exceedances remain clustered.

Not acceptable:

> KOWCPI improves VaR.

Not acceptable:

> KOWCPI is production-ready for ETF risk management.

## Recommendation

Record as `MIXED_WEAK`. Do not publish a standalone positive article. A useful
follow-up would combine kernel weighting with an explicit online coverage
control layer, because the current kernel weighting mostly narrows intervals
without solving violation clustering.
