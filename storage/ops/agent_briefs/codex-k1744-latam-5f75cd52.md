# K1744 fresh-worktree Codex retry — LatAm private-credit funding-gap transmission

## Recovery identity (authoritative override)

- Task id: `K1744`
- Experiment id: `K1744` (already reserved in `storage/ops/k_id_registry.json`)
- Executor: detached Codex compute job (`gpt-5.6-sol` through the repository's bounded Codex wrapper)
- Fresh registered worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-5f75cd52-k1744`
- Branch: `wt/dispatch-slot-1-5f75cd52-k1744`
- Only write scope: `experiments/K1744/`
- Required result artifact: `experiments/K1744/K1744_results.json`
- Commit actor/task identity: `codex-failover-slot-1-5f75cd525404411f8d34f739ebc128b9` / `K1744`

The earlier job `agent-brief-k1744-552fde40` never began research. Its direct
stdout reported a Claude weekly-limit rejection, it exited after about eleven
seconds with `timed_out=false`, and its declared artifact, near-misses, output
paths, and unique worktree commits were all absent. That receipt is **zero
salvage**: it is neither an experiment result nor a scientific null, and must
never be called successful. Do not read data or code from the old worktree and
do not remove it. This is a distinct retry from current `main` with a new
worktree and runtime receipt.

The original frozen research brief is:

`/Users/yhlai0911/volpred-research/storage/ops/agent_briefs/agent-brief-k1744-552fde40.md`

Read it completely and preserve its research question, ETF universe, regional
funding-gap differentiation, point-in-time proxy requirement, outcome family,
lookahead rules, multiplicity policy, success criteria, and null/blocked policy.
Where it names the old executor, old worktree, old branch, or old execution
identity, this recovery brief overrides it. Do not edit the frozen original.

## Mandatory preflight

Read, in order:

1. `AGENTS.md`, especially research honesty and the experiment workflow.
2. `.claude/skills/autonomous-research/SKILL.md`.
3. `.claude/skills/autonomous-research/references/operations-core-contract.md`.
4. `.claude/skills/autonomous-research/references/experiment-preamble.md`.
5. `.claude/rules/experiments.md` and `.claude/rules/worktree.md`.
6. The index and relevant data-timing, compute, worktree, HAC/DM, proxy, and
   multiple-testing entries in `docs/error_log.md`.
7. The original frozen K1744 brief above.
8. Related private-credit, EM transmission, news-intensity, and ETF-proxy entries
   in `storage/memory/knowledge.json`, using bounded `rg`/`jq` queries rather than
   loading the file wholesale.
9. At least three high-trust primary sources. Include the specified 2026 CFA
   Institute Latin America private-credit funding-gap discussion and its 2026
   private-markets growth report. Record direct URLs, publication/release dates,
   access timestamps, and exactly which institutional claim each source supports.

Do not mutate the task pool, shared memory, feed, work log, paper, frontend,
Supabase, Mirror, or any path outside `experiments/K1744/`. Do not publish. Do
not put commissioning prompts or raw review transcripts inside the worktree.
Independent full-surface review, knowledge integration, and merge belong to the
later PHASE A collector.

## Falsifiable research contract

Test whether a pre-specified, historically observable Latin America
private-credit supply/fundraising/news-intensity proxy predicts changes in:

1. next-period realized volatility for the LatAm/EM market proxy set;
2. a pre-specified tail-risk endpoint; and
3. rolling USD sensitivity using UUP.

The asset universe is fixed: `ILF`, `EWW`, `ECH`, `EPU`, `EWZ`, `CEW`, `EMLC`,
`EMB`, and `UUP`. Keep equity, FX/local-bond, and hard-currency-bond channels
separate. ETFs are liquid market proxies, not private-credit assets; every
conclusion must remain predictive/associational, never causal.

### Proxy lock and feasibility gate

Before loading or inspecting any outcome series, freeze one primary exposure
proxy in a machine-readable preregistration artifact. It must include the ideal
latent variable, exact observable series/event construction, source, raw record
identity, historical release/publication timestamp, frequency, transformation,
expected sign, and known measurement error. Use only information genuinely
available by each forecast origin. A 2026 retrospective report may motivate the
question but cannot be backfilled as if its information existed historically.

If no defensible, reproducible historical proxy is accessible, or the effective
sample/event count is too small for the preregistered inference, stop outcome
analysis and produce an honest `INCONCLUSIVE`/`INSUFFICIENT_DATA` canonical
artifact explaining the failed feasibility gate. Do not substitute synthetic
data, an outcome-selected proxy, generic BDC returns, Google Trends without
point-in-time provenance, or a contemporaneous market variable that merely
renames the outcome. A well-evidenced infeasibility/null artifact is valid.

### Timing, baseline, and inference

- Every exposure applied to an outcome at `t+1` must be observable by `t` and
  visibly lagged; `K1744.py` must contain an explicit `.shift(1)` on the signal
  path. Publication dates govern availability, not retrospective period labels.
- Fix `seed=42` for every bootstrap, permutation, sampling, and random path.
- Define the frequency, forecast origin, horizon, realized-volatility estimator,
  tail endpoint, USD-beta window, and common sample before outcome inspection.
- Compare against a simple lagged AR-RV/HAR-RV baseline appropriate to the chosen
  frequency. Baseline and candidate must use the same information set, target,
  sample, and lag convention.
- Report ETF inception dates, delistings, missingness, duplicates, timezone,
  extreme observations, source revisions, and the common-sample loss caused by
  the full basket. Never silently forward-fill returns or publication events.
- Use dependence-robust inference and the repository canonical QLIKE/DM helpers
  when applicable. HAC bandwidth may not degenerate to only `h-1`; inspect loss-
  differential autocorrelation and report sensitivity.
- Pre-specify the primary family and correct it for multiplicity (Holm at
  minimum). Channel splits, alternative windows, leave-one-country-out,
  excluding COVID, and alternative USD controls are secondary robustness only
  and cannot rescue a failed primary family.
- Sparse event/news data require a seeded block/permutation/bootstrap design and
  explicit power/precision limits. Report `NULL` rather than tune thresholds or
  windows after seeing outcomes.

## Required runtime artifacts

Create at minimum:

- `experiments/K1744/README.md`
- `experiments/K1744/K1744.py`
- `experiments/K1744/K1744_results.json`
- `experiments/K1744/reproduce_spec.json`
- the proxy preregistration and raw/cache manifest needed to prove timing and
  input identity
- scoped tests or machine-readable diagnostics for the proxy lock, lag,
  common-sample construction, inference family, and README/result consistency
- data-backed figures only if a valid empirical run occurs

`README.md` must state motivation, differentiation from generic BDC spillovers,
primary sources, data provenance/as-of policy, method, explicit lookahead policy,
preregistered success/null/blocked criteria, results, limitations, and a JSON
pointer for every numeric claim. The canonical results must contain source,
period, sample, release-time, input/hash, diagnostics, estimates, raw and
adjusted p-values, robustness labels, limitations, and a machine-readable
`SUPPORTED` / `NULL` / `INCONCLUSIVE` conclusion grade.

The same execution that writes canonical results must call
`volpred.research.reproduce_spec.finalize_experiment(...)`; do not hand-create a
post-hoc code trace or reproduce spec. If the empirical feasibility gate fails,
the canonical artifact must still byte-trace the executed diagnostic and state
precisely which required observation/source was unavailable.

Before committing, run at minimum:

```bash
uv run python experiments/K1744/K1744.py
uv run python scripts/experiment_gates.py run --path experiments/K1744
uv run python scripts/check_experiment_artifacts.py check --path experiments/K1744
```

Run relevant scoped tests and Ruff on new Python files. The artifact checker may
report the one intentional pre-collection gap: K1744 is not yet in shared
`knowledge.json`, which this worker is forbidden to edit. Accept no other
violation, especially no reproduce-spec/code-trace drift. Do not create
`review_verdict.json` yourself: the later collector commissions an independent
fresh-context Codex review, generates the gate template, and freezes the reviewed
claim surface before formal merge.

## Commit and final receipt

Preserve the worktree result in one writer-locked transaction. Current
`git_writer_lock.py commit` intentionally accepts only canonical main and only
literal files, so do **not** pass it a directory or point it at this linked
worktree. Instead use canonical `git_writer_lock.py run` to wrap the linked-
worktree `git add` + `git commit` transaction. List every created file literally;
no directory pathspec, glob, `git add -A`, or unrelated file is allowed. Use:

- actor: `codex-failover-slot-1-5f75cd525404411f8d34f739ebc128b9`
- task id in the ASCII commit message: `K1744`
- commit message: `[codex] K1744 LatAm funding-gap experiment`

Do not merge, push, remove either K1744 worktree, write knowledge, or mark the
pool task succeeded. End stdout with at most 15 lines containing the conclusion
grade, artifact path/hash, exact run command, gate/test outcomes, commit SHA,
three key JSON paths, primary adjusted-p-value result (or exact infeasibility
reason), robustness direction, and material limitations.
