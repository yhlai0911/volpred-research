# K1745 detached experiment brief

**Model**: opus / xhigh (per `scripts/model_router.py --task-type experiment`)

Implement and run K1745 in the registered worktree `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-dce2e9e5-k1745`. This is a full experiment, not a proposal.

## Research question

Test whether a time-varying-parameter HAR model, implemented as a state-space/Kalman random-walk coefficient model, improves genuinely out-of-sample daily realized-volatility forecasts over a fixed rolling/expanding OLS-HAR baseline for SPY, 0050.TW, and TX where defensible free data are available. Evaluate QLIKE and MSE with canonical DM-HLN inference and a Giacomini-Rossi fluctuation/stability analysis. Inspect whether coefficient paths move around leverage or volatility-regime transitions without making causal claims.

This is orthogonal to factor-loading TVP (research_program.md line 1452) and discrete level shifts (line 1478): K1745 concerns continuous evolution of HAR's own daily/weekly/monthly coefficients.

## Mandatory preamble

Before implementation, read `AGENTS.md`, `.claude/rules/experiments.md`, `docs/error_log.md`, `.claude/skills/autonomous-research/references/experiment-preamble.md`, and the K1745 item around `research_program.md:1577`. Search `storage/memory/knowledge.json` narrowly with `rg`/`jq` for prior HAR/TVP/Kalman findings. Review at least three primary academic sources and record exact citations/URLs/DOIs in the README. Do not fabricate inaccessible data or literature.

## Deliverables and ownership

Write only `experiments/K1745/**` in this worktree. Required deliverables:

- `experiments/K1745/README.md` with motivation, differentiation, data sources/periods/sample sizes, method, diagnostics, lookahead policy, preregistered success criteria, results, limitations, and honest verdict.
- `experiments/K1745/K1745.py`, deterministic with seed 42 and an explicit `signal.shift(1)` or mathematically equivalent lag at the feature/forecast seam.
- `experiments/K1745/K1745_results.json` containing byte-traceable computed outputs, per-market sample counts/date spans, losses, DM-HLN statistics, fluctuation-test outputs, coefficient-path summaries, diagnostics, and verdict.
- `experiments/K1745/reproduce_spec.json`, emitted at runtime together with results via `volpred.research.reproduce_spec.finalize_experiment`; its code hash/byte count must match the producing script.
- Useful plots/tables and tests under the same directory.

Do not modify shared state (`storage/memory/knowledge.json`, work log, task pool, feed, reports, paper, or research_program.md). The collection fire owns those updates after review.

## Methodological gates

- Use point-in-time-safe rolling/expanding forecasts. Construct HAR daily/weekly/monthly predictors only from observations available before each forecast target. Explicitly assert date alignment and lag behavior.
- Compare TVP-HAR and static HAR on identical forecast origins and losses. QLIKE must be actual/predicted; prefer canonical `volpred.stats.model_evaluation.qlike_pointwise` and canonical DM machinery rather than local substitutes.
- DM HAC bandwidth must be at least the repo canonical bandwidth, not merely `h-1`; report loss-differential autocorrelation and lag sensitivity. Apply HLN correction and disclose multiplicity handling across markets/losses.
- Define the Giacomini-Rossi fluctuation statistic/window/critical-value or resampling method precisely. Do not label an informal rolling DM plot as the formal test.
- Kalman covariance/initialization and hyperparameter selection must use training data only. Report stability, positive forecast enforcement, missing-data handling, convergence/degeneracy checks, and sensitivity to state-noise settings.
- If free TX realized-volatility data cannot be obtained reproducibly, do not substitute or invent it. Report the limitation and complete SPY/0050.TW; distinguish true RV from squared-return or range proxies everywhere.
- Fix all random seeds at 42. Preserve null/negative results and keep claim strength within evidence.

## Success criteria and completion

The experiment is a substantive positive only if TVP-HAR improves OOS QLIKE with correctly signed loss differentials and multiplicity-aware evidence on at least two defensible markets, remains directionally stable under reasonable state-noise/HAC/window sensitivity, and the coefficient paths pass the preregistered stability analysis. Otherwise issue an honest NULL/FAIL/CONDITIONAL verdict.

Run the experiment and relevant tests/gates, including `python3 scripts/check_experiment_artifacts.py check --path experiments/K1745` where applicable. Perform a primary-path Codex review following the experiment rules; generate `review_verdict.json` through `scripts/experiment_gates.py verdict-template`, never by inventing its schema, and ensure it pins the final unchanged claim surface. If review cannot be completed because of quota, leave explicit durable review-needed evidence and do not claim PASS.

Commit the worktree changes on branch `codex/k1745-tvp-har` with an ASCII `[agent]` message. Return the commit hash, exact commands/tests, result artifact path, verdict, and blockers. Do not merge or remove the worktree; the later collection task must use `scripts/merge_worktree.sh`.
