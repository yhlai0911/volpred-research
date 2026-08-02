# K1749 detached experiment — consolidation duration and volatility transitions

## Execution identity and scope

- Canonical task and experiment id: `K1749`.
- Registered worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-b7f47803-k1749`.
- Branch: `wt/dispatch-slot-1-b7f47803-k1749`.
- Write only under `experiments/K1749/`; do not edit task pool, shared memory, paper, feeds, or operations state.
- Required artifact: `experiments/K1749/K1749_results.json`.
- This is detached heavy compute. Do not merge, publish, write knowledge, or mark K1749 succeeded; the next PHASE A collector owns review and formal merge.

## Mandatory preflight

Read completely: `AGENTS.md`, `.claude/skills/autonomous-research/SKILL.md`, its operations contract and experiment preamble references, `.claude/rules/experiments.md`, `.claude/rules/worktree.md`, and relevant timing/inference/compute entries in `docs/error_log.md`. Search `storage/memory/knowledge.json` for prior low-volatility regime, volatility-transition, breakout, duration-dependence, and HAR-RV work. Use at least three high-trust primary research/data sources and record URLs, dates, access times, and supported claims.

## Falsifiable contract

Test the popular claim that a longer *completed low-volatility consolidation regime*, measured using information available at forecast origin, predicts a larger or more likely subsequent high-volatility transition. This is a predictive association question, not a causal or trading-profit claim.

Before inspecting outcomes, freeze a machine-readable preregistration covering:

1. a small fixed, liquid universe chosen transparently and not by results (for example SPY/QQQ/IWM, with primary family fixed before data inspection);
2. exact daily return and realized-volatility definitions, data source, sample dates, corporate-action policy, missingness policy, timezone, and forecast origin;
3. the low-volatility threshold and consolidation definition, including how a regime starts, continues, and ends;
4. duration bins or a continuous duration transform, minimum spell count, high-volatility transition threshold, forecast horizons, and first-passage/censoring treatment;
5. primary endpoints (for example future realized volatility, transition indicator, and first-passage time), signs, family size, multiplicity control, success/null/inconclusive gates, and robustness labels;
6. baseline and candidate information sets, common-sample rule, seed 42, and dependence-aware inference.

Thresholds, horizons, duration bins, and the asset universe must not be selected after viewing outcome relationships. Prefer economically interpretable or expanding-history thresholds; if a full-sample percentile is used, label it retrospective and add a real-time expanding-history robustness. Keep completed-spell selection and right censoring explicit. Do not let future regime termination define a signal treated as observable earlier.

## Timing, models, and inference

- `K1749.py` must contain an explicit `.shift(1)` on the duration/signal path, and every outcome window must begin strictly after the forecast origin.
- Use `seed=42` for all stochastic paths.
- Compare a duration-augmented model against a same-target, same-row, same-information-set AR/HAR-RV or transition-hazard baseline. If the candidate nests the baseline, ordinary DM normal inference is diagnostic only; use a nested-model-valid block bootstrap/permutation or other justified primary procedure.
- Preserve serial dependence and regime spells with month/day blocks or spell-aware resampling. Report event counts, effective independent spells, loss/residual ACF, bandwidth/block-length sensitivity, and confidence intervals—not p-values alone.
- Apply Holm (at minimum) across the preregistered primary family. Asset/horizon/threshold variants are robustness and cannot rescue a failed primary family.
- Include duration-monotonicity diagnostics and distinguish transition probability from transition magnitude. Avoid mechanically conditioning on a spell that is only knowable after the outcome begins.
- If data, event count, censoring, or power cannot support the contract, stop honestly with `INCONCLUSIVE/INSUFFICIENT_DATA`; a valid NULL is acceptable. Never tune the consolidation definition to manufacture a breakout result.

## Required artifacts and checks

Create at minimum `README.md`, `K1749.py`, `K1749_results.json`, `reproduce_spec.json`, a machine-readable preregistration, frozen/raw input identities or manifests, and scoped tests. README numeric claims must point to JSON paths. The result must include data provenance/as-of rules, sample/event diagnostics, estimates and intervals, raw/adjusted inference, robustness labels, limitations, and a machine-readable `SUPPORTED`/`NULL`/`INCONCLUSIVE` conclusion.

The same execution that writes canonical results must call `volpred.research.reproduce_spec.finalize_experiment(...)`. Run the experiment, scoped tests, Ruff, `scripts/experiment_gates.py run --path experiments/K1749`, and the artifact checker. The only acceptable pre-collection artifact warning is missing main-thread knowledge/review. Do not create `review_verdict.json`; the collector commissions an independent frozen-byte review.

Commit only literal files under `experiments/K1749/` in the registered worktree, using canonical `scripts/git_writer_lock.py run` around the exact `git add`/`git commit` transaction. No glob, `git add -A`, push, merge, or worktree removal. End with conclusion, artifact/hash, exact run command, tests/gates, commit SHA, key JSON paths, primary adjusted result, robustness direction, and limitations.
