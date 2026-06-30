# Codex Source Review — K1584

**Timestamp**: 2026-06-30 (Asia/Taipei)
**Reviewer**: Codex CLI
**Verdict**: CONDITIONAL_PASS

## Scope

Reviewed:

- `experiments/k1584/k1584.py`
- `experiments/k1584/k1584_results.json`
- `experiments/k1584/README.md`
- `experiments/k1584/figures/k1584_harcj_diagnostics.png`

## Checks

### Lookahead / Target Alignment

PASS. Forecast target is `RV_t`; forecast features are built from source series shifted by one day before daily/weekly/monthly rolling windows:

- `experiments/k1584/k1584.py`: `lag = series.shift(1)`
- `jump_cluster_w` and `jump_cluster_m` also use `d["jump_event"].shift(1)`
- OOS training uses `train = features.iloc[:pos]`, so each forecast row trains only on rows strictly before the forecast date.

`uv run python scripts/lookahead_audit.py --json` produced no finding for `experiments/k1584/`.

### Numerical Reproducibility

PASS. `uv run python experiments/k1584/k1584.py` completes and regenerates:

- `experiments/k1584/k1584_results.json`
- `experiments/k1584/data/tx_harcj_oos_forecasts.csv`
- `experiments/k1584/figures/k1584_harcj_diagnostics.png`

`uv run python -m py_compile experiments/k1584/k1584.py` passes.

### Claim Strength

PASS with limitations. The formal result is correctly reported as NULL:

- TX OOS forecasts: 1,697
- HAR mean QLIKE: `0.16867692156792077`
- HAR_CJ mean QLIKE: `0.16997307816856064`
- HAR_CJ DM t vs HAR: `1.5902192770157353`
- HAR_CJ QLIKE improvement vs HAR: `-0.7684255727408111%`

The README does not claim systemic co-jump evidence. It explicitly says the SPY/0050 diagnostic is same-calendar-date, not clock-synchronized, non-gateable, and not a systemic co-jump network test.

### Jump Metric Definitions

PASS. README distinguishes:

- jump event count
- jump variance
- jump share

This addresses the K851 lesson that jump-event share and jump-variance share must not be conflated.

## Limitations

- The gateable test is single-market TX day-session only; it is a HAR-CJ jump-axis test, not a systemic co-jump network replication.
- The SPY/0050 diagnostic has only 98 overlapping same-calendar-date observations and should not be cited as formal cross-market co-jump evidence.
- The script depends on the K1582 TX daily-measures cache rather than reparsing raw TAIFEX files in this run. This is acceptable for this hourly task because lineage is documented, but a paper-grade rerun should rebuild from raw files or archive the cache provenance.

## Recommendation

Accept K1584 as a NULL experiment. Do not write a positive knowledge entry or publication claim from it. The useful next step is data infrastructure: build a long synchronized multi-asset intraday panel before revisiting systemic co-jump networks or Hawkes-style co-jump models.
