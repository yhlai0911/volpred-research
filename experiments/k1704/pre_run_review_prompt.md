# K1704 primary pre-run code review

Work read-only in this repository. Review the frozen K1704 implementation at the current
HEAD, specifically:

- `experiments/K1704/README.md`
- `experiments/K1704/K1704.py`

Do not edit files and do not trust or review the existing untracked results/cache as
scientific evidence; they were produced before primary-path review and will be rerun only
after this review passes and any fixes are applied.

Research question: using the same TAIFEX day-session ledger, is the forecast-model ranking
robust across 1/5/10-minute RV, Parkinson range, squared day return, and a past-only
reliability-weighted consensus proxy?

Mandatory review checks:

1. Lookahead: every forecast, scale calibration, proxy-bias estimate, and consensus weight
   at origin t must use only data strictly before t. Confirm GJR recursion/refits likewise.
2. Target fairness: distinguish model native-target advantage from empirical proxy
   robustness. No causal, trading, or latent-variance claim is allowed.
3. TAIFEX construction: all-contract TX data, completed-day highest-volume contract,
   homogeneous 08:45-13:45 session, no TX1 roll-gap contamination, consistent session-open
   grid for 1/5/10-minute RV.
4. QLIKE and DM: canonical repo helpers only, correct pointwise-loss sign convention,
   common date/model ledger, and no local h=1 lag-0 shortcut.
5. MCS: repo implementation, seed=42, at least 1,000 bootstrap reps, and no post-result
   redefinition of the decision rule.
6. Reliability consensus: rolling [t-500,t) inputs only; actual target at t cannot affect
   t's weights or scale calibration. Identify any circularity or common-error limitation.
7. Traceability: source/file/code hashes, cache invalidation, atomic JSON, and failure-loud
   behavior must be adequate for a rerun.
8. Tests/edge cases: identify missing tests that could allow a material bug, especially
   sampling-grid endpoints, forecast-origin alignment, calibration leakage, and MCS inputs.

Relevant project rules:

- `.claude/skills/autonomous-research/references/experiment-preamble.md`
- `.claude/rules/experiments.md`
- `docs/error_log.md` classes C, F, G, O, and P
- fixed seed 42; formal Harvey |t| > 3 reporting; null/inconclusive reported honestly
- review is pre-run: PASS only means the code is safe to execute, not that results are valid

Return a concise formal verdict with exactly one of `PASS`, `CONDITIONAL_PASS`, or `FAIL`,
then list findings by severity with file/line references. Any lookahead, mismatched ledger,
incorrect target comparison, non-canonical DM, or traceability failure is blocking.
