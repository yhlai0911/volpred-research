# K1747 detached experiment brief

**Model**: opus / xhigh (per `scripts/model_router.py --task-type experiment`)

Implement and run K1747 in the registered worktree
`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bf6e9f48-k1747`.
This is a complete empirical-and-Monte-Carlo experiment, not a proposal or a
literature-only note.

## Research question

On one common SPY/QQQ next-day realized-volatility task, compare HAR with a
regularized linear learner and tree learners, then audit whether ordinary
Diebold-Mariano predictive-ability inference has correct size once model
selection, hyperparameter estimation, and learner convergence are included.
Contrast the ordinary fixed-forecast DM analysis with a defensible
learner-aware procedure grounded in the cited JBES paper, and use Monte Carlo
null designs to measure empirical rejection size. An untouched outer holdout
must prevent the selector or learner from overfitting the final claim surface.

Motivating primary source (verify it rather than relying on this title alone):
“Extending Predictive-Ability Inference to Machine Learning,” *Journal of
Business & Economic Statistics*, DOI `10.1080/07350015.2025.2562964`.

The contribution is an inference audit, not another ML-ceiling horse race.
Whether any learner beats HAR is secondary; a null or negative predictive
result remains useful if the inference calibration is sound.

## Mandatory preamble

Before design or code, read all of:

- `AGENTS.md`
- `.claude/rules/experiments.md`
- `.claude/rules/worktree.md`
- `docs/error_log.md` (search especially for DM/HAC, forward-label leakage,
  QLIKE orientation, nested model selection, and review/artifact incidents)
- `.claude/skills/autonomous-research/references/experiment-preamble.md`
- `.claude/skills/autonomous-research/references/operations-core-contract.md`
- `.claude/skills/autonomous-research/references/agent-result-template.md`
- the K1747 item around `research_program.md:1605`

Search `storage/memory/knowledge.json` narrowly for prior HAR, Lasso/tree/ML,
SPY/QQQ range-RV, model-selection, and DM findings. Review at least three
primary academic sources, including the motivating paper and canonical
predictive-ability/DM references. Record verified DOI/URL and the exact method
actually implemented. Do not infer an algorithm from an abstract or invent an
unavailable theorem. If the paper's proposed estimator cannot be reproduced
from accessible primary material, implement only a clearly labelled,
well-supported sample-split or cross-fit diagnostic and state that it is not a
paper replication.

## Deliverables and ownership

Modify only `experiments/K1747/**` in this worktree. Required deliverables:

- `README.md` with motivation, prior-work differentiation, estimand, data
  provenance/date spans/sample counts, model-selection protocol, Monte Carlo
  DGPs, preregistered success criteria, lookahead policy, results, limitations,
  and an honest verdict.
- `K1747.py`, deterministic with master seed 42 and explicit
  `signal.shift(1)` or a mathematically equivalent, asserted information-set
  join at every empirical forecasting seam.
- `K1747_results.json` with byte-traceable empirical forecasts/losses and
  inference results, Monte Carlo rejection counts/rates/uncertainty, split and
  seed identities, convergence diagnostics, multiplicity adjustments,
  sensitivities, and verdict.
- `reproduce_spec.json`, emitted together with the canonical result through
  `volpred.research.reproduce_spec.finalize_experiment`; its script hash and
  byte size must match the code that produced the results.
- Useful machine-readable tables/plots and focused tests under the same
  experiment directory.

Do not modify the task pool, work log, knowledge, feed, paper, research program,
or any other shared state. A later collection fire owns independent review,
knowledge, and integration.

## Empirical design gates

- Use identical assets, dates, forecast origins, next-day target, information
  set, refit schedule, and loss definitions for HAR and every learner. Save the
  intersection audit and assert equal forecast counts.
- If free daily OHLC produces a range-based variance proxy rather than
  high-frequency realized variance, name it precisely (for example,
  Garman-Klass range variance), document adjustment assumptions, and limit the
  claim to a range-RV proxy. Do not call it 5-minute RV.
- Build HAR features and all other predictors using information available by
  the forecast origin. A forward target row may enter training only when its
  full target window ends strictly before the origin. Make the lag behavior
  visible in code and test it.
- Include HAR, Lasso (or another explicitly regularized linear learner), and at
  least two genuinely different tree specifications where feasible. Select
  hyperparameters only with time-ordered inner training/validation data.
  Record convergence/fitting failures rather than silently replacing them.
- Reserve an outer evaluation holdout before examining candidate results. The
  selector, feature choices, hyperparameter grids, loss choice, and inference
  variants must be frozen using pre-holdout data; report any unavoidable reuse.
- Use repository-canonical pointwise QLIKE with `actual / predicted` orientation
  and a secondary squared-error loss. State which loss-score conditions are
  required by each inference method. Do not choose the reporting loss after
  looking at holdout significance.
- Ordinary DM must use the canonical HAC implementation/bandwidth floor and
  report bandwidth sensitivity. Learner-aware inference must account for the
  fact that learners and selectors are estimated, with its sample splitting,
  cross-fitting, rate assumptions, or correction stated explicitly. Merely
  renaming ordinary DM is a blocking defect.
- Apply a declared multiple-testing correction across assets, learners, losses,
  and inference variants. Separate per-comparison diagnostics from the primary
  family-level claim.

## Monte Carlo size audit

- Simulate under a genuine equal-predictive-ability null where the entire
  learner fitting and selection pipeline is rerun in every replication. A null
  that holds forecasts fixed does not audit estimation risk.
- Include at least one persistent/heteroskedastic volatility design resembling
  the empirical task and one simpler sanity-check design. Match the empirical
  time ordering, train/validation/evaluation split, refit cadence, and losses as
  closely as computationally practical.
- Predeclare sample-size and learner-complexity grids that can reveal
  convergence-rate effects. Use enough replications for a useful binomial
  confidence interval around nominal 5% size; report Monte Carlo standard
  errors and mark underpowered cells rather than overinterpreting them.
- Use deterministic child seeds derived from master seed 42, save the mapping,
  and confirm serial versus parallel reproducibility on a small subset.
- Primary size conclusions compare empirical rejection rates and confidence
  intervals with the nominal level for ordinary and learner-aware procedures.
  Power, if reported, must use separate alternatives and cannot rescue a
  size-distorted method.

## Preregistered verdict gate

A positive inference finding requires repeatable evidence that ordinary DM is
materially mis-sized in at least one preregistered estimation-risk design while
the supported learner-aware method is meaningfully closer to nominal size,
without relying on a single seed or one cherry-picked learner. If both methods
are acceptably calibrated, evidence is mixed, accessible theory is
insufficient, or Monte Carlo uncertainty is too wide, issue an honest
`NULL`, `CONDITIONAL`, or `FAIL` verdict. No learner needs to beat HAR for the
experiment to be successful as an inference audit.

## Completion

Run focused tests, the experiment, and
`uv run python scripts/experiment_gates.py run --path experiments/K1747`.
Do not launch a nested Codex process from this agent; the collection fire will
commission the required independent primary-path Codex review outside the
worktree, generate `review_verdict.json` through
`scripts/experiment_gates.py verdict-template`, and re-run the certification
gate. Leave explicit review-needed evidence and do not claim PASS before that
review.

Commit only `experiments/K1747` through the locked exact-path helper with an
ASCII `[agent]` message and task id `K1747`. Return the worktree commit hash,
commands/tests, artifact path and hash, core JSON paths, empirical and Monte
Carlo verdicts, review-needed status, and blockers. Do not merge or remove the
worktree; the collection fire must integrate it only through
`scripts/merge_worktree.sh` after the independent review and artifact gates.
