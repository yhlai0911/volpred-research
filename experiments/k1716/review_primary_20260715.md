# K1716 primary-path Codex review

- Reviewer: Codex CLI 0.144.1, `gpt-5.6-sol`, high reasoning, read-only sandbox
- Session: `019f6819-7731-72f0-941d-e357657b422e`
- Frozen commit: `a6702bd987820d51555cb3c36b722982293413b7`
- Reviewed at: 2026-07-15T23:29:42Z
- Verdict: **PASS**

## Scope and evidence

The reviewer re-walked the full claim surface (`K1716.py`, `test_k1716.py`, `README.md`, `K1716_results.json`, and the rendered figure) plus the frozen CSV. A read-only in-memory reconstruction produced zero differences across data diagnostics, descriptives, all four HAC regressions, 4,000 moving-block bootstrap draws, Holm values, restricted-era placebos, and pre-treatment trends. Recorded data, script, and figure SHA-256 values matched their frozen bytes.

The review confirmed that the earlier defects were fixed: atomic validated results writing, pandas round-trip float parsing, explicit K1477 overlap disclosure, and placebo samples restricted to untreated/pre-treatment and already-treated/post-treatment eras. It also confirmed 2,144 unique monotonic observations, zero invalid OHLC rows, 23 excluded transition observations, 2,115 regression observations, and exact `.shift(1)` control alignment.

## Findings

No blocking defects. One low-severity clarity note remains: `transition_dates_excluded` stores the interval endpoints as a list rather than an explicit start/end object. The code and README unambiguously exclude the full 2022-04-18 through 2022-05-18 interval, so this does not affect computation or interpretation.

The `NULL_PROXY_DIAGNOSTIC` verdict is conservative: both primary statistics are far below Harvey's threshold, Holm p-values are 1.0, primary signs disagree, bootstrap intervals cross zero, and causal limitations are explicit.

## Blind spots

The review sandbox could not create pytest/tempfile caches, so the reviewer used an equivalent in-memory reconstruction. Outside that sandbox, the worktree ran 4 unit tests successfully and the experiment-integrity gate passed. The reviewer did not independently reopen K1477 or re-verify literature claims because the re-review was scoped to the frozen K1716 certification surface.
