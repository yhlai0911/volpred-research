# K1741 fresh-worktree Codex retry — short-credit tail hedge

## Recovery identity (authoritative override)

- Task id: `K1741`
- Experiment id: `K1741` (registry-reserved; on-disk directory remains lowercase `experiments/k1741`)
- Executor: detached Codex compute job (`gpt-5.6-sol` through the repository's bounded Codex wrapper)
- Fresh registered worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-6fe0dac5-k1741`
- Branch: `wt/dispatch-slot-1-6fe0dac5-k1741`
- Only write scope: `experiments/k1741/`
- Required result artifact: `experiments/k1741/K1741_results.json`

The earlier job `agent-brief_k1741-dfc2dd` never began research. Its live stdout
reported a Claude weekly-limit rejection, it exited after about 11 seconds, the
declared artifact and near-misses were absent, and its old worktree was clean.
That receipt is **zero salvage**, is not an experiment result, and must never be
called successful. Do not read data or code from the old worktree. This is a
distinct retry from current `main` with a new runtime receipt.

The original frozen research brief is:

`/Users/yhlai0911/volpred-research/storage/ops/agent_briefs/agent-brief_k1741-dfc2dd.md`

Read it completely and preserve its research question, data universe, four
drawdown classes, two short-credit definitions, three borrow-fee assumptions,
benchmarks, statistical tests, lookahead rules, success criteria, and null-result
policy. Where it names the old model, old worktree, or old execution identity,
this recovery brief overrides it. Do not edit the frozen original brief.

## Mandatory preflight

Read, in order:

1. `AGENTS.md`, especially the research-honesty rules.
2. `.claude/skills/autonomous-research/SKILL.md`.
3. `.claude/skills/autonomous-research/references/operations-core-contract.md`.
4. `.claude/skills/autonomous-research/references/experiment-preamble.md`.
5. `.claude/rules/experiments.md` and `.claude/rules/worktree.md`.
6. The index and relevant compute/worktree/lookahead/statistical entries in
   `docs/error_log.md`.
7. The original frozen K1741 brief above.
8. The cited K544, K24, K22, I3, and synthetic-put entries in
   `storage/memory/knowledge.json`, using bounded `rg`/`jq` queries.

Do not mutate the task pool, shared memory, feed, paper, Supabase, Mirror, or any
path outside `experiments/k1741/`. Do not create review prompts or raw review
transcripts inside the worktree. Independent full-surface review and knowledge
integration belong to the later PHASE A collector.

## Research contract and falsifiable question

Test whether a short corporate-credit overlay on SPY delivers better
beta-adjusted crisis alpha per unit of calm-period drag than the repository's
synthetic-put proxy or a long-VXX overlay across the empirically identified
2018Q4, 2020, 2022, and 2025 drawdowns.

The primary short-credit implementation is duration-hedged:

`-(HYG_return - beta_duration * IEF_return)`

Estimate `beta_duration` using only observations available through `t-1` in an
expanding window. Also report naive `-HYG_return` and a JNK robustness series.
Every applied hedge weight, duration beta, and pre-crisis equity beta must be
formed from the prior information set and visibly lagged (an explicit
`signal.shift(1)` must appear in `K1741.py`). Drawdown-window identification is
allowed to be ex post because this is an event study; hedge decisions are not.

### Return and cost accounting invariant

Do not double-count HYG distributions. Reconstruct or decompose the short leg so
that price P&L, actual distribution/coupon payment, borrow fee, and rebalancing
cost are separately traceable, while their sum equals the implemented net short
return within numerical tolerance. If adjusted-close total returns are used,
the distribution is already embedded in the short total return and may be shown
as a decomposition only; it must not be subtracted a second time. Prefer a
transparent ex-distribution price-return plus actual-dividend construction when
the yfinance fields permit it. Record and test the accounting identity.

Borrow fees are unavailable from yfinance and must remain assumptions, never
observations. Run the full annual grid `0.005`, `0.010`, `0.020`, expose every
grid result, and state any ranking/sign reversal. Use total-return-aware inputs
for all ETFs. Do not splice the pre-2018 VXX product into the current VXX series.

Hedge comparisons must share a documented budget rule (calm-drag matching or
crisis-beta-reduction matching). When realized-volatility exposure differs by
more than the repository threshold, report exposure-matched MDD and the required
phase/circular-shift null; raw MDD alone cannot support a claim. Use repository
canonical statistical helpers when available. Four crises are a tiny event
sample: daily evidence, stationary/block bootstrap, Harvey-corrected inference,
and multiplicity decisions may support only the strength their assumptions
allow. `NULL` is a fully valid outcome.

## Required runtime artifacts

Create all of the following in the authorized tree:

- `experiments/k1741/README.md`
- `experiments/k1741/K1741.py`
- `experiments/k1741/K1741_results.json`
- `experiments/k1741/reproduce_spec.json`
- at least two data-backed figures
- scoped tests or machine-readable diagnostics needed to verify the accounting,
  lag, window, and result invariants

The script must use `seed=42` for every random path and finish through
`volpred.research.reproduce_spec.finalize_experiment(...)` so the result and
runtime spec describe the same run. Results must include source/period/sample
identities, actual crisis-window dates, both short definitions, all borrow-fee
cells, all benchmarks, beta/cost decompositions, bootstrap intervals,
DM/Harvey outputs, multiplicity decisions, limitations, and a machine-readable
PASS / CONDITIONAL_PASS / NULL assessment. Every README number must map to an
explicit JSON path.

Before committing, run at minimum:

```bash
uv run python experiments/k1741/K1741.py
uv run python scripts/experiment_gates.py run --path experiments/k1741
uv run python scripts/check_experiment_artifacts.py check --path experiments/k1741
```

The artifact checker may report the one intentional pre-collection gap: K1741
is not yet in shared `knowledge.json`, which this worker is forbidden to edit.
Inspect its full output and accept no other violation; in particular the runtime
`reproduce_spec.json` identity must pass. Run relevant scoped tests and `ruff`
on new Python files. If live data retrieval
is unavailable, do not invent or hand-enter results: preserve a truthful
INSUFFICIENT_DATA/blocked diagnostic only if it satisfies the artifact contract,
otherwise exit nonzero without publishing a fake canonical result.

Commit only the authorized experiment tree through the writer lock:

```bash
uv run python /Users/yhlai0911/volpred-research/scripts/git_writer_lock.py commit \
  --repo /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-6fe0dac5-k1741 \
  --actor codex-compute-k1741-6fe0dac5 \
  --task-id K1741 \
  --message '[codex] K1741 tail hedge experiment' \
  -- experiments/k1741
```

Do not merge, push, write knowledge, or mark the pool task succeeded. End stdout
with at most 15 lines containing artifact path/hash, run command, gate outcomes,
verdict, three key JSON paths, borrow-fee sensitivity, and material limitations.
