# HARQ realized-quarticity backlog closure

## Status

Verdict: `DUPLICATE_CLOSED_BY_K1582`

This directory closes the pending backlog task:

> HARQ 已實現四次矩測量誤差修正：本機 5-min 算 realized quarticity，HARQ（RV×√RQ 交互修正衰減偏誤）vs 標準 RV-HAR，OOS QLIKE/DM。

The task is already covered by `experiments/k1582/`. This directory provides a reproducible audit that verifies K1582 contains the requested realized-quarticity HARQ implementation and records the duplicate-closure decision.

## Why Not Rerun?

K1582 already implements:

- local 5-minute realized measures;
- `RQ_t = n / 3 * sum_j r_{t,j}^4`;
- HAR baseline;
- HARQ measurement-error interaction using `sqrt(RQ) / RV`;
- OOS QLIKE and DM tests;
- MCS screen;
- explicit `.shift(1)` feature timing;
- Codex review and knowledge entry.

Re-running the same model under a new slug would create duplicate publication-candidate noise without adding evidence.

## Canonical Result

Gateable market: `TX_active`

- OOS forecasts: 1,697
- HAR QLIKE: 0.1687
- HARQ QLIKE improvement: +1.94%, DM t = -2.60
- SHARK-like QLIKE improvement: +2.05%, DM t = -1.77
- MCS members: HARQ, HARQ_full, SHARK_like
- K1582 verdict: `DIRECTIONAL_ONLY`

Interpretation: measurement-error correction has the right sign on the only gateable panel, but it does not pass the project's Harvey `|DM| > 3` gate.

## Files

- `research_harq_5_min_realized_quarticity_harq_rv_rq_vs_rv.py`: duplicate-closure audit script
- `research_harq_5_min_realized_quarticity_harq_rv_rq_vs_rv_results.json`: closure result
- `research_harq_5_min_realized_quarticity_harq_rv_rq_vs_rv_summary.csv`: K1582 TX_active compact metric table

## Canonical References

- `experiments/k1582/K1582.py`
- `experiments/k1582/K1582_results.json`
- `experiments/k1582/README.md`
- `experiments/k1582/CODEX_REVIEW.md`
