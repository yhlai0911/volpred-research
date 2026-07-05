# Codex Review - HARQ duplicate closure

Verdict: `CONDITIONAL_PASS_DUPLICATE_CLOSURE`

## Scope Reviewed

- Pending task `research_harq_5_min_realized_quarticity_harq_rv_rq_vs_rv`
- Canonical experiment `experiments/k1582/`
- Closure audit script in this directory

## Findings

No new model run is warranted. The task is a duplicate of K1582.

The closure audit verifies that K1582 includes:

- realized quarticity formula `RQ_t = n/3 * sum r^4`;
- measurement-error proxy `sqrt(RQ) / RV`;
- explicit `.shift(1)` feature timing;
- expanding OOS forecast code that trains before the forecast row;
- QLIKE, DM test, and MCS outputs;
- a Codex review and a knowledge entry.

K1582's substantive result remains `DIRECTIONAL_ONLY`: TX_active has OOS n=1,697 and directionally better HARQ / SHARK-like QLIKE, but no candidate passes the Harvey `|DM| > 3` gate.

## Recommendation

Close the pending task as succeeded duplicate closure and update `research_program.md` so this stale open line does not get dispatched a third time. Future work should require either a longer SPY/0050 5-minute archive, a materially different HARQ-X estimator, or night-session-specific TAIFEX measurement-error design.
