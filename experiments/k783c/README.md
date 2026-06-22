# K783c — Cross-Period Window Size Sensitivity on SPY

**Status: source-review FAIL pending K783c-v2 rerun.**

K783c tested whether the preferred GJR-GARCH training window changes across
three SPY OOS regimes: high-vol 2020-2021, moderate 2018-2019, and calm
2016-2017. The original published artifact claimed regime-dependent winners
based on QLIKE rankings and DM tests.

## Source-Review Finding

The 2026-06-17 Codex review found that v1 used inverse QLIKE:

```text
predicted / actual - log(predicted / actual) - 1
```

The project canonical Patton orientation is:

```text
actual / predicted - log(actual / predicted) - 1
```

Because v1 rankings and DM tests were built from the inverse pointwise losses,
the published window-regime conclusion is not source-review safe.

## Current Source Guard

The script now imports the canonical helpers:

- `volpred.stats.model_evaluation.qlike(actual, predicted)`
- `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)`

It also writes results to the canonical local experiment path:
`experiments/k783c/k783c_cross_period_window_results.json`.

## Required K783c-v2 Work

- Rerun the experiment with canonical QLIKE orientation.
- Keep forecast chronology target-aligned and lookahead-clean.
- Rebuild charts and article text from the rerun artifact.
- Disclose DM/HAC assumptions explicitly.
- Do not cite v1 regime-window rankings until K783c-v2 passes review.
