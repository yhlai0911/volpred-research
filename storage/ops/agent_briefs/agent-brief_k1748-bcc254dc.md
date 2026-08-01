# K1748 — primary-dealer settlement fails as a Treasury market-plumbing warning

## Identity

- Task id: `K1748`
- Owner token: `codex-failover-slot-1-bcc254dc0d9d465691a935e894219b88`
- Reserved experiment id: `K1748` (already present in the canonical task pool / K registry; do not reserve or rename it)
- Worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bcc254dc-k1748`
- Branch: `codex/k1748-bcc254dc`
- Unique write scope: `experiments/K1748/`
- This is detached execution. Do not write task-pool state, shared memory, feed, paper, frontend, remote systems, or files outside the unique scope.

## WHAT

Test whether weekly FR 2004 primary-dealer settlement fails contain an honestly timed warning signal for US bond-market plumbing.

Use official Treasury, agency-debt, and agency-MBS fails-to-deliver and fails-to-receive series. Establish the actual public-release timestamp first. A report-week observation may enter an information set only after its Thursday publication; choose the next fully tradable session conservatively if release time relative to market close is not documented.

Forecast the next non-overlapping trading-week outcomes for TLT, IEF, and MBB:

1. close-to-close variance proxy: sum of daily squared close returns;
2. OHLC range-variance proxy, named as a range proxy rather than high-frequency realized variance;
3. noisy within-week SPY/bond daily-return correlation, Fisher transformed for modeling and clearly caveated.

Required models and comparisons:

- threshold local projections for high-fails states over 1–4 weekly horizons;
- expanding-window HAR using 1/4/13-week target histories;
- nested HAR+fails using the same forecast origins and training rows;
- Clark–West as the primary nested-model forecast test;
- repository-canonical QLIKE/DM only as correctly aligned diagnostics, never a hand-written replacement.

The primary incremental claim requires common-origin OOS loss improvement and familywise-corrected formal evidence. Pre-register before seeing results:

- H1 (plumbing pressure): high lagged fails predicts higher future variance/range. Support requires the expected positive sign and Holm-adjusted p < 0.05 for at least two of three bond ETFs in a predeclared target family; otherwise NULL/PARTIAL as appropriate.
- H2 (forecast increment): HAR+fails beats HAR on common OOS origins. Support requires lower mean OOS loss and Holm-adjusted Clark–West p < 0.05 for at least two of three ETFs for the predeclared primary loss. Report every asset/target cell, including adverse signs.
- H3 (stock–bond correlation): treat the five-daily-observation weekly correlation as secondary/noisy. Never let it rescue failed H1/H2. Any support must survive the same predeclared multiplicity rule.
- Threshold and alternative receive/deliver/net definitions not designated primary are robustness/post-hoc and must be labelled as such.

Null, insufficient-data, and contaminated-timing results are valid deliverables.

## WHY

- Research question: can actual collateral-chain settlement stress warn about near-term Treasury/MBS volatility beyond the target's own HAR history?
- Closest repo evidence: `experiments/k_repo_basis_funding_stress_gate_duration_2026_06_14/` found a related weekly duration-RV null, but its legacy local QLIKE/HAC must not be copied. `experiments/k1506/README.md` found auction/dealer-pressure null evidence and explicitly identified NY Fed weekly statistics as a follow-up.
- Increment: strict public-availability alignment, separate Treasury/agency/MBS plumbing signals, threshold response, and expanding OOS HAR comparison.
- Positive result: a reproducible, availability-clean warning increment.
- Null result: settlement fails do not add robust weekly forecast value beyond HAR under this public-data design.
- Failure/data shortage: an honest `INSUFFICIENT_DATA` or `BLOCKED_SOURCE_CONTRACT`, not synthetic values or a weaker substituted question.

## Data contract

- Primary source: official Federal Reserve Bank of New York primary-dealer statistics/data hub and fails primer. Record exact URLs, series labels, units, report-week semantics, download timestamp, response identity/hash, and documented release schedule.
- Market source: reproducible daily adjusted close and OHLC for TLT, IEF, MBB, and SPY. Record provider, retrieval time, adjustment convention, first/last usable dates, and raw-snapshot identity.
- Period: maximum common sample after every series/ETF is genuinely available; do not backfill pre-inception or silently splice proxies.
- Availability: construct an explicit `observation_period -> public_timestamp -> first_tradable_origin` table. Join as-of on availability, never on matching date labels.
- Fails features: units and receive/deliver definitions must be explicit. Winsorization, if used, is expanding/past-only. The z-score at origin uses only observations available strictly before or at that origin; no full-sample mean/std. The forecast design must also contain an explicit `signal.shift(1)` or equivalent lag.
- Targets: forward windows begin after the first tradable origin and end before any row can enter training. Store origin, `target_start`, and `target_end` diagnostics.
- Minimum useful sample: predeclare at least 104 common OOS weekly origins per primary cell. If unavailable, report insufficient data and stop primary inference.
- No fabricated, interpolated, or manually typed observations. Missing official fields stay missing and are reported.

## Method contract

- Empirical design; no simulation may substitute for the requested evidence.
- Run data diagnostics before estimation: missingness, duplicates, outliers, unit changes, calendar/timezone, availability gaps, sample counts, autocorrelation, and target distributions.
- Fix all seeds at `42`, including bootstrap, split, sampling, and optimizer paths.
- Forward-label training gate: for target horizon H, a training row is legal only when `target_end < forecast_origin` (equivalently the complete label window is known). Pin this invariant with tests and result diagnostics.
- Use expanding OOS only. HAR and HAR+fails share identical origins, targets, train rows, transformations, and minimum-history rules.
- Each target horizon gets its own embargo and HAC/inference horizon. Use the repository canonical bandwidth floor; never reduce HAC to only `h-1`.
- Use `src/volpred/stats/model_evaluation.py` canonical pointwise QLIKE/DM/Clark–West surfaces where applicable. QLIKE is actual over predicted. Do not use ordinary DM as the primary test for nested HAR vs HAR+fails.
- Predeclare the primary family and Holm correction before inspecting outcomes. Preserve raw and adjusted p-values and pre/post-correction decisions in JSON.
- Report effect sizes, OOS loss levels/differences, sample counts, dates, and sensitivity—not only p-values.
- Lookahead probes must include a future-noise causal test and explicit zero-violation diagnostics.
- Read `docs/error_log.md` for current methodology incidents before implementation. In particular, do not copy legacy local DM/QLIKE, do not treat stacked asset-days as iid, and do not call a final-vintage or date-label join point-in-time.

## Artifact contract

Create only:

- `experiments/K1748/README.md`
- `experiments/K1748/K1748.py`
- `experiments/K1748/K1748_results.json`
- `experiments/K1748/reproduce_spec.json`
- scoped tests, diagnostics, figures, or cached source snapshots inside `experiments/K1748/` when needed

The entrypoint must call `volpred.research.reproduce_spec.finalize_experiment(...)` once at runtime so the canonical result and sibling reproduce spec are written together and byte-bound to the executed code and inputs. Do not hand-write a post-hoc reproduce spec.

Do not create `review_verdict.json` yourself. Independent primary-path Codex review, knowledge writing, and formal worktree integration belong to the later PHASE A collector. Leave the claim surface frozen after the final run.

## Acceptance

- Success: complete three-piece experiment plus runtime reproduce spec; official availability provenance; `signal.shift(1)`/equivalent; target-window embargo diagnostics; seed 42; common-origin expanding HAR comparison; canonical tests; multiplicity-adjusted decisions; all commands reproducible.
- Null: same artifacts and gates, with NULL/PARTIAL language and no attempt to promote a weak robustness cell.
- Blocked: source/timestamp contract cannot be verified, minimum OOS origins fail, or required official data cannot be reproduced. Preserve diagnostics and return the exact blocker; do not substitute data.
- Stop immediately on: impossible timestamps, duplicate period keys with conflicting values, unit ambiguity, target windows crossing origins, full-sample standardization, forward-label leakage, fabricated rows, or result/spec identity drift.
- Required local gates before handoff:
  - `uv run python scripts/experiment_gates.py run --path experiments/K1748`
  - `uv run python scripts/check_experiment_artifacts.py check --path experiments/K1748`
  - run all K1748 scoped tests
  - programmatically parse results/spec and verify the declared result identity

Commit the exact experiment scope in the worktree using the locked writer, not bare Git mutation:

```bash
uv run python /Users/yhlai0911/volpred-research/scripts/git_writer_lock.py commit \
  --repo /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bcc254dc-k1748 \
  --actor codex-k1748-detached \
  --task-id K1748 \
  --message '[codex] K1748 settlement-fails experiment artifacts' \
  -- experiments/K1748
```

Do not merge or remove the worktree. The PHASE A collector will independently review and then call `scripts/merge_worktree.sh` only if certification passes.

## Required reading

- `.claude/skills/autonomous-research/references/experiment-preamble.md`
- `.claude/skills/autonomous-research/references/operations-core-contract.md`
- `.claude/skills/autonomous-research/references/agent-result-template.md`
- `.claude/rules/experiments.md`
- `.claude/rules/worktree.md`
- `docs/error_log.md` (current methodology and worktree incidents)
- `research_program.md` around the K1748 source item
- `experiments/k_repo_basis_funding_stress_gate_duration_2026_06_14/README.md`
- `experiments/k1506/README.md`
- `experiments/K1679-rev2/K1679-rev2.py` (embargo/HAR pattern only; verify rather than copy blindly)
- `src/volpred/stats/model_evaluation.py`
- `src/volpred/research/reproduce_spec.py`
- Official NY Fed fails primer and data-hub documentation linked by the canonical K1748 task

## Return format

Use `.claude/skills/autonomous-research/references/agent-result-template.md`. Every numeric or verdict claim must include its canonical `K1748_results.json` path. Report artifact identities, exact run commands, data period/counts, release/vintage rules, seed, gate exit statuses, nulls/limitations, and requested main-thread actions.
