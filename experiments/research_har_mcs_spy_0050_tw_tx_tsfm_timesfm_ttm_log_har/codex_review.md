# Codex Review

## Verdict

`CONDITIONAL_PASS_HARNESS / BLOCKED_PRIMARY_TSFMS`

## Scope

Reviewed the newly added diagnostic experiment for lookahead, data provenance,
and whether the task's TimesFM/TTM claim is represented honestly.

## Findings

- No lookahead issue found in the executed HAR/EWMA/combination harness. Training
  examples map prior forecast origin `j` to target `j+1`; the current origin is
  excluded from the supervised fit, and all forecast rows satisfy
  `target_date > origin_date`.
- The first implementation of the baseline harness had a target-alignment bug
  (`X_t` paired with `y_t`) and a level-space bias-correction instability. Both
  were fixed before final results: HAR now trains on `X_j -> y_{j+1}`, and
  bias-correction is in log space.
- The primary TSFM task is not empirically answered. TimesFM package import is
  available, but weights were not cached after a >150s smoke-test download
  attempt. TTM was not installed because the dry-run would downgrade the shared
  project `scikit-learn` below the repo requirement.
- Results correctly mark `status =
  BLOCKED_FOR_PRIMARY_TSFMS_BUT_BASELINE_HARNESS_EXECUTED`; no TimesFM/TTM
  forecast rows are mixed into the empirical tables.

## Verification

- `uv run python experiments/research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har/research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har.py`
- `uv run python -m py_compile experiments/research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har/research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har.py`
- CSV invariant check: 4,919 rows; all `target_date > origin_date`; all actual
  and forecast variance values positive.
