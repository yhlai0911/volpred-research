# K1746 fresh-worktree Codex retry — bottom-up versus top-down VaR/ES

## Recovery identity (authoritative override)

- Task id / experiment id: `K1746` (already reserved)
- Executor: detached Codex compute job (`gpt-5.6-sol` via the bounded repository wrapper)
- Fresh registered worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-2b0f34d8-k1746`
- Branch: `wt/dispatch-slot-1-2b0f34d8-k1746`
- Only write scope: `experiments/K1746/`
- Required result artifact: `experiments/K1746/K1746_results.json`
- Commit actor/task identity: `codex-failover-slot-1-2b0f34d80c874ec68b67cc98b8a9d2b6` / `K1746`

The earlier Claude job `agent-k1746-var-es-4316fc94` never began research. Its
first quota receipt was recorded at `2026-08-01T17:32:05Z`; terminal runner
evidence at `2026-08-02T04:45:45Z` reported the provider weekly limit, with a
stated reset at 16:00 Asia/Taipei. That receipt has `exit_code=1`,
`failure_class=quota`, `timed_out=false`, no output paths, and no declared
result artifact. Its registered worktree is clean. It remains **ZERO_SALVAGE**:
neither a successful experiment nor a scientific null. Do not read research
code or data from that worktree, remove it, relabel the incident as a false
positive, or reinterpret its receipt. This retry uses the separately healthy
Codex failover path in a distinct worktree; it does not assert that the original
Claude provider has recovered.

The frozen original research brief is:

`/Users/yhlai0911/volpred-research/storage/ops/agent_briefs/agent-k1746-var-es-4316fc94.md`

Read it completely and preserve its research question, universe, point-in-time
policy, aggregation comparison, formal backtests, success criteria, and honest
null/blocked policy. This recovery brief overrides only executor, worktree,
branch, commit identity, and review timing. Do not edit the frozen original.

## Mandatory preflight

Read, in order:

1. `AGENTS.md` if present and repository research-honesty instructions.
2. `.claude/skills/autonomous-research/SKILL.md`.
3. `.claude/skills/autonomous-research/references/operations-core-contract.md`.
4. `.claude/skills/autonomous-research/references/experiment-preamble.md`.
5. `.claude/rules/experiments.md` and `.claude/rules/worktree.md`.
6. Relevant VaR/ES, target-alignment, dependence, multiple-testing, bootstrap,
   artifact, and worktree entries in `docs/error_log.md`.
7. The frozen K1746 brief and the backlog item around
   `research_program.md:1587`.
8. Narrowly query `storage/memory/knowledge.json` for prior VaR/ES, tail-risk,
   aggregation, dependence, and MCS evidence. Do not load the full file.
9. Review at least three primary academic sources. Verify the motivating 2025
   Journal of Forecasting aggregation paper if identifiable, and record direct
   DOI/URL, metadata, access time, and the precise claim each source supports.
   Do not invent a citation if the described paper cannot be verified.

Do not mutate the task pool, shared memory, work log, feed, reports, paper,
frontend, `research_program.md`, Supabase, Mirror, or any path outside
`experiments/K1746/`. Do not publish. Commissioning prompts and raw review
transcripts stay outside the worktree. Independent review, knowledge
integration, and merge belong to the later PHASE A collector.

## Falsifiable research contract

For the equal-weight `SPY/TLT/GLD/HYG/QQQ` basket, compare genuinely
out-of-sample one-day 1% and 5% VaR/ES forecasts from:

1. bottom-up component forecasts aggregated to the portfolio; and
2. top-down forecasts estimated directly from the identical portfolio-return
   target.

The study asks whether aggregation direction changes tail calibration or a
jointly elicitable VaR/ES proper score. It must not turn failure to reject a
coverage test into evidence that a method is superior.

### Data, target, and information set

- Freeze source, retrieval/as-of timestamp, raw/cache hashes, period, timezone,
  common trading calendar, adjusted-price policy, missingness, duplicates,
  corporate actions, weights, and rebalancing convention before fitting.
- Use the same five-asset basket, common-date return panel, forecast origins,
  horizon, alpha, realized portfolio return, and information set for both
  directions. State whether equal weights are daily rebalanced and include a
  defensible alternative rebalancing sensitivity.
- Every target at `t` must use only information available by `t-1`.
  `K1746.py` must contain explicit `signal.shift(1)` (or an equally explicit
  named seam where raw returns themselves are the signal), plus assertions that
  rolling/expanding training labels end before every forecast origin.
- Fix seed `42` for every stochastic path, bootstrap, MCS elimination, and
  optimizer initialization. No full-OOS hyperparameter tuning.

### Aggregation and dependence

- Define bottom-up VaR and ES mathematically, including weight/sign
  conventions. A marginal quantile or ES sum is only a clearly labelled
  **naive dependence-ignoring diagnostic**; it cannot be the sole bottom-up
  scientific method.
- Include a defensible dependence-aware bottom-up construction that converts
  component conditional distributions and their point-in-time joint
  dependence into the portfolio predictive distribution. Estimate dependence
  only from the available training window. Report positive-definiteness,
  tail-dependence limitations, simulation error, and sensitivity to at least
  one alternative dependence/block/window choice.
- Match estimator families as fairly as possible between directions and
  separate aggregation-direction effects from distribution or sample-window
  effects. Predeclare rolling window, distribution, weights/rebalancing, and
  crisis-period sensitivities; sensitivities cannot rescue a failed primary
  family.

### Backtests, losses, and MCS

- Report per method/alpha the exact OOS count, violations, expected violations,
  Kupiec UC, Christoffersen independence and conditional coverage, a correctly
  specified dynamic-quantile test, and an established ES backtest with stated
  null, statistic orientation, and finite-sample caveats.
- Use a recognized jointly elicitable VaR/ES proper score with explicit sign
  and loss orientation. Do not compare ES point forecasts with an improper
  standalone loss. Use repository helpers where available.
- Predeclare the primary family and apply multiplicity control across the
  methods/alphas/tests used for public claims. Preserve raw and adjusted
  p-values. Directional superiority requires better calibration **and** proper
  score evidence, not isolated test acceptance.
- MCS must record candidate set, loss series, block/bootstrap design, block
  length, seed, resample count, elimination statistic/rule, confidence level,
  and sensitivity. Use identical OOS origins and a date-level bootstrap; do not
  treat stacked method/asset observations as iid.
- Report rolling-window, distribution, dependence, rebalancing, and
  crisis-period sensitivities. If computation or data make the contract
  underpowered, emit an honest `INCONCLUSIVE`/`INSUFFICIENT_DATA` artifact
  rather than synthetic evidence or a scientific null.

A substantive positive requires materially better multiplicity-aware tail
calibration and proper-score performance for one aggregation direction, stable
under the preregistered sensitivities. Otherwise return an honest `NULL`,
`CONDITIONAL`, `FAIL`, or `INCONCLUSIVE` grade no stronger than the evidence.

## Required runtime artifacts and checks

Create at minimum:

- `README.md`, `K1746.py`, `K1746_results.json`, and runtime-generated
  `reproduce_spec.json`;
- frozen source/cache manifest and data diagnostics;
- forecast/loss/backtest sidecars needed to reproduce every inference cell;
- scoped tests for information timing, identical origins, aggregation math,
  dependence treatment, VaR/ES signs, backtests, multiplicity, MCS bootstrap,
  and README/result consistency.

The same execution that writes canonical results must call
`volpred.research.reproduce_spec.finalize_experiment(...)`; do not hand-create
post-hoc code tracing. The README must point every numeric claim to JSON and
must distinguish the old `ZERO_SALVAGE` receipt from the current scientific
verdict.

Before committing, run at minimum:

```bash
uv run python experiments/K1746/K1746.py
uv run pytest -q experiments/K1746
uv run ruff check experiments/K1746
uv run python scripts/experiment_gates.py run --path experiments/K1746
uv run python scripts/check_experiment_artifacts.py check --path experiments/K1746
```

The artifact checker may report only the intentional pre-collection gaps for
shared `knowledge.json` and the later independent review. Accept no reproduce
spec/code-trace drift. Do not create `review_verdict.json`; PHASE A commissions
the independent fresh-context review and freezes the final claim surface.

## Commit and terminal receipt

Commit only literal files under `experiments/K1746/` through the canonical
writer lock; no directory pathspec, glob, `git add -A`, unrelated file, merge,
push, or worktree removal. Use actor
`codex-failover-slot-1-2b0f34d80c874ec68b67cc98b8a9d2b6`, task `K1746`,
and ASCII message `[codex] K1746 bottom up top down VaR ES`.

End stdout with at most 15 lines containing scientific grade, artifact path and
hash, exact run command, gate/test outcomes, commit SHA, primary adjusted
inference, MCS outcome, sensitivity direction, and material limitations.
