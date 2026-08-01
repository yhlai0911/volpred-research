# K1746 detached experiment brief

**Model**: opus / xhigh (per `scripts/model_router.py --task-type experiment`)

Implement and run K1746 in the registered worktree `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-4316fc94-k1746`. This is a full experiment, not a proposal.

## Research question

For an equal-weight SPY/TLT/GLD/HYG/QQQ basket, compare genuinely out-of-sample one-day 1% and 5% VaR/ES forecasts from (a) bottom-up component forecasts aggregated to the portfolio and (b) top-down forecasts estimated directly from portfolio returns. Test whether cross-sectional aggregation direction improves tail calibration using Kupiec, Christoffersen, DQ, ES backtests, proper VaR/ES scoring, and a defensible model-confidence-set comparison.

## Mandatory preamble

Before implementation, read `AGENTS.md`, `.claude/rules/experiments.md`, `docs/error_log.md`, `.claude/skills/autonomous-research/references/experiment-preamble.md`, and the K1746 item around `research_program.md:1587`. Search `storage/memory/knowledge.json` narrowly for prior VaR/ES, tail-risk, aggregation, and MCS findings. Review at least three primary academic sources, including the motivating 2025 Journal of Forecasting aggregation paper if verifiable, and record exact citations/URLs/DOIs. Do not fabricate literature or data.

## Deliverables and ownership

Write only `experiments/K1746/**` in this worktree. Required deliverables:

- `README.md` with motivation, method, data provenance/date spans/sample sizes, preregistered success criteria, lookahead policy, results, limitations, and honest verdict.
- `K1746.py`, deterministic with seed 42 and explicit `signal.shift(1)` or mathematically equivalent lag at every forecasting seam.
- `K1746_results.json` with byte-traceable outputs, per-method/alpha forecast counts, violations, all test statistics/p-values, loss/MCS results, diagnostics, sensitivities, and verdict.
- `reproduce_spec.json`, emitted with results through `volpred.research.reproduce_spec.finalize_experiment`, whose producer hash and bytes match the final script.
- Useful plots/tables and tests under the same directory.

Do not modify shared state such as the task pool, work log, knowledge, feed, paper, or research program. A later collection fire owns review, merge, and shared-state updates.

## Methodological gates

- Use point-in-time-safe rolling or expanding forecasts; all parameters and portfolio/component inputs at target t must use data available no later than t-1. Assert alignment and lag behavior.
- Define bottom-up aggregation mathematically. Naively adding marginal VaR/ES ignores dependence; include a defensible dependence-aware construction or label the naive sum explicitly and test it as such. Ensure both directions target the identical portfolio, forecast origins, alpha, horizon, and information set.
- Report Kupiec unconditional coverage, Christoffersen independence/conditional coverage, a correctly specified DQ test, and an established ES backtest. State small-sample limitations and apply multiplicity control across methods/alphas/tests.
- Use consistent loss orientation and canonical repository helpers where available. MCS must state bootstrap design/block choice, seed, elimination rule, and sensitivity; never infer superiority merely from failure to reject coverage.
- yfinance adjustment/missing-day handling and weights/rebalancing must be reproducible. Avoid survivorship claims. Include rolling-window, distribution, weighting/rebalancing, and crisis-period sensitivities where feasible.
- Preserve null/negative findings. A positive verdict requires materially better calibration/proper score for one aggregation direction with multiplicity-aware evidence and reasonable sensitivity stability; otherwise issue NULL/CONDITIONAL/FAIL honestly.

## Completion

Run the experiment and relevant artifact gates. Perform the required primary-path Codex review; create `review_verdict.json` only via `scripts/experiment_gates.py verdict-template`, and pin the final unchanged claim surface. If review is unavailable, leave durable review-needed evidence and do not claim PASS.

Commit worktree changes with an ASCII `[agent]` message. Return the commit hash, commands/tests, artifact path, verdict, and blockers. Do not merge or remove the worktree; the collection fire must use `scripts/merge_worktree.sh`.
