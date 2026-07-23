# nested-DM coefficient-mask channel audit

Date: 2026-07-19

Task: `k1731_F2_nested_dm_detector_mask_channel`

## Detector change

`scripts/audit_nested_dm_misuse.py` now treats a coefficient mask as nesting
evidence only when both conditions occur in one module:

1. a subscript or slice of an array is assigned a zero-like value; and
2. that same array is passed to a fit-family call in a restriction-shaped
   positional or keyword argument.

The conjunction is intentional. A zeroed sample-weight or burn-in array is not
model nesting, and a restriction-named array that never reaches an estimator is
not sufficient evidence.

## Scan results

The canonical main checkout scan completed over 1,872 Python files with no
scan errors. It reported 228 affected paths and 12 reviewed-safe paths. Relative
to `storage/ops/nested_dm_misuse_baseline.json`, there were no new or stale
paths. K1730 and K1731 are not yet present in canonical main, so adding their
paths to the live baseline before their experiment worktree merges would make
the ratchet fail its stale-entry check.

The same detector was run directly against the two candidate files in
`dispatch-slot-1-bd00f90a-k1731`:

- `experiments/k1730/k1730_gevreg_midas_ssvs.py` is newly detected as
  `review_required`. Lines 142-143 zero `active[n_beta - n_macro:]` and pass it
  as `active=` to `fit_gev_reg`; raw DM evidence exists, but the file-local
  claim-sink channel is not conclusive. This is a real nested comparison and
  must be adjudicated, not an allowlisted false positive.
- `experiments/k1731/k1731_gevreg_midas_ssvs_returns.py` is newly detected as
  `primary_raw_dm`. Lines 176-177 use the same restriction mask, while the raw
  DM outputs reach claim evidence. This is the K1731 false negative that
  motivated the change and is genuine nested-DM debt.

The experiment worktree already carries the corresponding prospective
baseline change from 193 to 195 active sites. That baseline update must land
atomically with the two experiment paths after their separate review/merge;
the canonical ratchet is intentionally unchanged in this detector-only commit.

## Precision checks

Four focused fixtures cover the new channel: the K1731-shaped positive case,
an otherwise identical case without the mask construction, a zeroed
`sample_weight`, and a restriction-named array never passed to an estimator.
All four pass. The complete nested-DM suite executed 107 assertions
successfully; its repository-parity post-check then rejected unrelated
untracked experiment artifacts already present in the shared canonical
checkout. The scanner itself completed with no errors and no baseline delta.
