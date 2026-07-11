# K1683 post-run result verification

Date: 2026-07-11
Verdict: **PASS**

The verifier read the results JSON, input CSVs, and source directly rather than
using the experiment summary.

## Checks

- Recomputed all four baseline/augmented loss improvements and confirmed the
  `loss_augmented - loss_base` DM direction.
- Recomputed the four-cell BH-FDR mapping and confirmed 0/4 gate passes imply
  `NULL_NO_ROBUST_INCREMENT`.
- Confirmed OOS counts of 637, 637, 636, and 630 weeks and verified that every
  stored timing audit enforces `target_end < origin`.
- Recomputed the CFTC proxy: 0.2406278776 on 2023-01-03 and 0.3010125468 on
  2025-09-30, a 25.0946273% increase; 4,192 input rows have no duplicate
  contract/report keys.
- Verified byte counts and SHA-256 for all three pinned CSV files.
- Cache-only executions reproduced identical canonical JSON after deleting the
  volatile `run_utc` field. Both PNGs decoded successfully.

## Interpretation

TLT and IEF show small full-period loss improvements, but neither is
Harvey-significant and both reverse sign in late OOS. Yield-jump and
stock-bond-correlation losses worsen. The scoped null is supported; it does not
reject a forced-deleveraging mechanism that requires unobserved funding, margin,
or risk-limit shocks.

No blocking or major issue remained.
