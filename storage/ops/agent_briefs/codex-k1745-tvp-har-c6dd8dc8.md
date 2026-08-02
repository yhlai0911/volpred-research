# K1745 fresh-worktree Codex retry — TVP-HAR Kalman OOS experiment

## Recovery identity (authoritative override)

- Task id: `K1745`
- Experiment id: `K1745` (already reserved)
- Executor: detached Codex compute job (`gpt-5.6-sol` through the repository's bounded Codex wrapper)
- Fresh registered worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-c6dd8dc8-k1745`
- Branch: `wt/dispatch-slot-1-c6dd8dc8-k1745`
- Only write scope: `experiments/K1745/`
- Required result artifact: `experiments/K1745/K1745_results.json`
- Commit actor/task identity: `codex-failover-slot-1-c6dd8dc80ec549d4a685610f92910545` / `K1745`

The earlier Claude job `agent-k1745-tvp-har-dce2e9e5` never began research.
Its first quota receipt was recorded at `2026-08-01T17:31:59Z`; its terminal
runner evidence at `2026-08-02T04:45:45Z` reported a weekly limit resetting at
16:00 Asia/Taipei. The terminal receipt has `exit_code=1`,
`failure_class=quota`, `timed_out=false`, no output paths, and no declared
result artifact. The old registered worktree is clean. It is **ZERO_SALVAGE**:
neither a successful experiment nor a scientific null. Do not read research
code or data from that worktree, do not remove it, and do not reinterpret the
receipt. This is a distinct retry from current `main` using the healthy Codex
failover provider and a new runtime receipt.

The original frozen research brief is:

`/Users/yhlai0911/volpred-research/storage/ops/agent_briefs/agent-brief-k1745-dce2e9e5.md`

Read it completely and preserve its research question, continuous-TVP
differentiation, market universe, point-in-time policy, baselines, formal tests,
success criteria, and honest null/blocked policy. This recovery brief overrides
only its old executor, worktree, branch, commit identity, and review timing. Do
not edit the frozen original.

## Mandatory preflight

Read, in order:

1. `AGENTS.md`, especially research honesty and experiment workflow.
2. `.claude/skills/autonomous-research/SKILL.md`.
3. `.claude/skills/autonomous-research/references/operations-core-contract.md`.
4. `.claude/skills/autonomous-research/references/experiment-preamble.md`.
5. `.claude/rules/experiments.md` and `.claude/rules/worktree.md`.
6. Relevant data-timing, target-alignment, QLIKE, DM/HAC, multiple-testing,
   artifact, and worktree entries in `docs/error_log.md`.
7. The original frozen K1745 brief above and the K1745 backlog item around
   `research_program.md:1577`.
8. Narrowly query `storage/memory/knowledge.json` for prior HAR, TVP, Kalman,
   K1617, and K1648 evidence. Do not load the full file.
9. At least three primary academic sources, including the referenced 2025
   TVP-HAR trend where it can be identified. Record direct URL/DOI, publication
   metadata, access time, and the precise methodological claim supported. Do not
   invent a citation if the described paper cannot be verified.

Do not mutate the task pool, shared memory, work log, feed, reports, paper,
frontend, `research_program.md`, Supabase, Mirror, or any path outside
`experiments/K1745/`. Do not publish. Commissioning prompts and raw review
transcripts stay outside the worktree. Independent full-surface review,
knowledge integration, and merge belong to the later PHASE A collector.

## Falsifiable research contract

Test whether a time-varying-parameter HAR model, expressed as a state-space
model with random-walk daily/weekly/monthly HAR coefficients and estimated by a
Kalman filter, improves genuinely out-of-sample one-day volatility forecasts
over a fixed-coefficient HAR baseline for `SPY`, `0050.TW`, and Taiwan futures
`TX` wherever defensible free data exist.

This is continuous evolution of HAR's own coefficients. It is not the
time-varying factor-loading question studied by K1617 and not a discrete
level-shift or breakpoint model.

### Data and feasibility lock

- Before fitting, freeze source, retrieval/as-of timestamp, period, timezone,
  trading calendar, estimator, raw/cache identity, missingness, duplicates, and
  extreme-value diagnostics for each market.
- A true realized-variance claim requires reproducible intraday observations and
  an explicit sampling rule. Daily squared return, Parkinson, or Garman-Klass
  range measures may be used only as clearly labelled proxies; they must never
  be renamed as intraday RV.
- Do not silently splice adjusted and unadjusted prices or forward-fill returns.
  Report corporate-action handling and cross-market calendar loss.
- If reproducible free TX data are unavailable, record the source attempts and
  limitation, then complete the defensible SPY/0050.TW scope as the original
  brief permits. If fewer than two defensible markets or too few OOS observations
  remain, produce an honest `INCONCLUSIVE`/`INSUFFICIENT_DATA` canonical artifact
  rather than synthetic data or an underpowered scientific null.

### Information set, models, and tuning

- Build HAR daily/weekly/monthly predictors only from values known strictly
  before the forecast target. `K1745.py` must contain an explicit
  `signal.shift(1)` at the feature/forecast seam plus assertions that every
  training label is complete before its forecast origin.
- Use identical forecast origins, target, loss sample, transformation, and lag
  convention for TVP-HAR and static HAR. The baseline must be a defensible
  expanding or rolling OLS-HAR, with window choice fixed before OOS outcomes.
- Estimate Kalman initial state, covariance, state noise, observation noise, and
  any positivity transform using training data only. Hyperparameter selection
  must be nested within the available information set, never chosen on the full
  OOS period. Record initialization, covariance conditioning, boundary hits,
  update failures, forecast clipping/floor frequency, and sensitivity to at
  least three defensible state-noise settings.
- Fix seed `42` for every stochastic path, resampling procedure, optimizer
  initialization, and split.

### Losses and formal inference

- Primary economic loss is canonical QLIKE with `actual / predicted`; use the
  repository pointwise helper. MSE is a preregistered secondary loss. Preserve
  correctly signed loss differentials and state which sign favors TVP-HAR.
- Use repository canonical DM inference with HLN correction. HAC bandwidth may
  not degenerate to `h-1`; report canonical bandwidth, loss-differential ACF,
  and lag sensitivity for every market/loss cell.
- Predeclare the primary comparison family and apply Holm correction at minimum
  across the market/loss cells. Per-market, proxy, window, and state-noise
  sensitivities cannot rescue a failed primary family.
- Implement a genuine Giacomini-Rossi fluctuation/stability test: define the
  rolling window, standardized local loss-differential statistic, dependence
  correction, critical-value or seeded resampling rule, and multiplicity policy.
  An informal rolling DM chart is diagnostic only and must not be labelled as
  the formal test.
- Predeclare leverage/regime dates or mechanical rules before examining
  coefficient paths. Coefficient movement is descriptive/associational, not a
  causal effect. Report path uncertainty and avoid interpreting filter noise as
  structural change.

The experiment is substantively positive only if TVP-HAR improves OOS QLIKE on
at least two defensible markets with multiplicity-aware evidence, remains
directionally stable under state-noise/HAC/window sensitivities, and the formal
fluctuation analysis supports time variation. Otherwise return an honest
`NULL`, `FAIL`, `CONDITIONAL`, or `INCONCLUSIVE` grade whose strength does not
exceed the evidence.

## Required runtime artifacts

Create at minimum:

- `experiments/K1745/README.md`
- `experiments/K1745/K1745.py`
- `experiments/K1745/K1745_results.json`
- `experiments/K1745/reproduce_spec.json`
- source/cache manifest and data diagnostics needed to prove provenance
- loss-differential or forecast sidecars needed to reproduce inference
- scoped tests for lag/alignment, QLIKE direction, Kalman filtering, formal
  fluctuation inference, multiplicity, and README/result consistency
- data-backed figures for coefficient paths and fluctuation statistics only
  when the corresponding empirical scope is valid

The README must state motivation, differentiation, primary sources, source and
period per market, sample sizes, data-vintage policy, method, lookahead policy,
preregistered success/null/blocked criteria, results, limitations, and JSON
pointers for numeric claims. The result JSON must contain provenance, date spans,
sample counts, loss tables, raw and adjusted inference, sensitivity results,
coefficient diagnostics, anomalies, limitations, and a machine-readable verdict.

The same execution that writes canonical results must call
`volpred.research.reproduce_spec.finalize_experiment(...)`; do not hand-create a
post-hoc code trace or reproduce spec. If the feasibility gate stops the study,
the canonical artifact must still byte-trace the executed diagnostic and record
the exact missing source or power condition.

Before committing, run at minimum:

```bash
uv run python experiments/K1745/K1745.py
uv run python scripts/experiment_gates.py run --path experiments/K1745
uv run python scripts/check_experiment_artifacts.py check --path experiments/K1745
```

Run relevant scoped tests and Ruff on new Python files. The artifact checker may
report the one intentional pre-collection gap: K1745 is not yet in shared
`knowledge.json`, which this worker is forbidden to edit. Accept no other
violation, especially no reproduce-spec/code-trace drift. Do not create
`review_verdict.json` yourself; the later collector commissions an independent
fresh-context Codex review, generates the gate template, and freezes the final
unchanged claim surface before formal merge.

## Commit and final receipt

Preserve the worktree result in one writer-locked transaction. Use canonical
`git_writer_lock.py run` to wrap the linked-worktree `git add` and `git commit`
transaction. List every created file literally: no directory pathspec, glob,
`git add -A`, or unrelated file. Use:

- actor: `codex-failover-slot-1-c6dd8dc80ec549d4a685610f92910545`
- task id in the ASCII commit message: `K1745`
- commit message: `[codex] K1745 TVP HAR experiment`

Do not merge, push, remove either K1745 worktree, write knowledge, or mark the
pool task succeeded. End stdout with at most 15 lines containing the verdict
grade, artifact path/hash, exact run command, gate/test outcomes, commit SHA,
three key result JSON paths, primary adjusted inference, sensitivity direction,
and material limitations.
