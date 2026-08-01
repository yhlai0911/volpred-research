# K1744 — Latin America private-credit funding gap and EM volatility transmission

**Task id:** K1744  
**Worktree:** `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-552fde40-k1744`  
**Branch:** `k1744-slot1-552fde40`  
**Only writable experiment path:** `experiments/K1744/`

## Objective

Use the 2026 CFA Institute discussion of Latin American private-credit funding gaps as institutional motivation, then test whether a pre-specified, reproducible private-credit supply/fundraising news-intensity proxy predicts changes in Latin America/EM realized volatility, tail risk, or USD sensitivity. The market proxy set is ILF, EWW, ECH, EPU, EWZ, CEW, EMLC, EMB, and UUP. Keep this distinct from generic BDC/private-credit spillover work: the estimand is regional funding-gap/LatAm transmission.

## Required reading and differentiation

Before coding, read `AGENTS.md`, `.claude/rules/experiments.md`, `.claude/skills/autonomous-research/references/experiment-preamble.md`, recent relevant entries in `docs/error_log.md`, and targeted related entries in `storage/memory/knowledge.json` (do not load that file wholesale). Search and cite primary sources, including the specified CFA 2026 Latin America private-credit and private-markets growth reports. State what information is actually observable, its release timestamp/frequency, and why the design is not a renamed generic private-credit spillover test.

## Design requirements

1. Pre-register one primary exposure proxy before inspecting outcomes. Prefer a point-in-time, dated fundraising/deal/news-intensity series with raw observations cached or byte-traceably derived. If no defensible historical proxy can be obtained, return an honest INCONCLUSIVE/blocked artifact rather than fabricate or silently substitute synthetic data.
2. Define outcomes in advance: next-period realized volatility for the LatAm/EM ETF basket; a tail-risk measure; and rolling USD beta/sensitivity using UUP. Include a simple lagged HAR-RV or autoregressive RV baseline appropriate to frequency.
3. Every predictor used for an outcome at t+1 must be observable by t and shifted explicitly with `.shift(1)` (or an exactly documented equivalent). Release/publication dates, not retrospective period labels, govern availability.
4. Use common-sample comparisons, report ETF inception/missingness effects, and distinguish local equity, FX/local bond, and hard-currency bond channels. ETF proxies are not the underlying private-credit market; claims must remain predictive/associational.
5. Use HAC or other dependence-robust inference appropriate to frequency; correct the pre-specified family of primary tests for multiplicity. If event/news observations are sparse, use a seeded block/permutation/bootstrap path with `seed=42` and report power/precision limits.
6. Any robustness (alternative intensity window, leave-one-country-out, excluding COVID, alternative USD control) must be labeled secondary and cannot replace a failed primary test.

## Deliverables and gates

Create and commit only `experiments/K1744/` artifacts:

- `README.md`: motivation, cited sources, data provenance/as-of policy, method, explicit lookahead policy, pre-specified success criteria, results, limitations, and related-K differentiation.
- `K1744.py`: deterministic entrypoint with visible signal lag and `seed=42`.
- `K1744_results.json`: machine-readable values for every number claimed in the README.
- `reproduce_spec.json` and any figures/data snapshots required by the canonical experiment rules.
- `review_verdict.json`, created through the repository verdict-template/gate workflow rather than handwritten.

Use `volpred.research.reproduce_spec.finalize_experiment` in the same run that writes canonical results. Run the experiment artifact checker and relevant focused tests. Verify README numbers byte-for-byte against JSON. A NULL result is valid; knowledge eligibility requires at least CONDITIONAL_PASS. Do not modify shared state (`storage/next_tasks.json`, knowledge, feed, work log), publish content, push, or merge the worktree. Commit the worktree branch when complete; a later collection task will run the official `scripts/merge_worktree.sh` path.

## Final receipt

Report the conclusion grade (SUPPORTED / NULL / INCONCLUSIVE), primary estimates and adjusted p-values, robustness direction, data limitations, gate output, commit SHA, and exact artifact paths.
