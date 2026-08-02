# K1750 detached experiment — IPO-market heat and SPY volatility

**Model**: opus / xhigh (per `scripts/model_router.py --task-type experiment`)

## Execution identity and ownership

- Canonical source task and reserved experiment id: `K1750`.
- Source-task owner token: `codex-failover-slot-1-b66d62b6bcf54d5fa30d8b0016702dba`.
- Registered worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-b66d62b6-k1750`.
- Branch: `wt/dispatch-slot-1-b66d62b6-k1750`.
- Unique write scope: `experiments/K1750/**` only.
- Required result artifact: `experiments/K1750/K1750_results.json`.
- This is detached heavy research execution, not a proposal. Do not merge, publish,
  write shared memory, edit the task pool, or mark K1750 succeeded. The later PHASE A
  collector owns frozen-byte review, knowledge, formal `merge_worktree.sh` integration,
  and terminal settlement.

## Mandatory preflight

Before implementation, read completely:

1. `AGENTS.md`;
2. `.claude/skills/autonomous-research/SKILL.md`;
3. `.claude/skills/autonomous-research/references/operations-core-contract.md`;
4. `.claude/skills/autonomous-research/references/experiment-preamble.md`;
5. `.claude/rules/experiments.md` and `.claude/rules/worktree.md`;
6. `research_program.md:1632-1637` and the K1750 row in `storage/next_tasks.json`;
7. the nested-model, QLIKE-direction, forward-label embargo, HAC-lag, runtime-spec,
   and review-certification entries in `docs/error_log.md`.

Search `storage/memory/knowledge.json` narrowly with `rg`/bounded `jq` for K531,
K872, VIX redundancy, sentiment/risk-appetite predictors, and HAR-RV-X evidence.
Inspect the closest reusable implementations before writing new machinery:

- `experiments/k1728/k1728.py` for lagged HAR/exogenous features, common-row OOS,
  positive variance forecasts, and robustness structure;
- `experiments/k1601/K1601.py` for expanding OOS and target-end embargo;
- `experiments/K1611/K1611.py` for adjusted OHLC and variance proxies;
- `experiments/k1138/k1138.py` and `experiments/k1357/K1357.py` for same-target
  VIX-controlled HAR comparisons;
- `src/volpred/stats/model_evaluation.py` for canonical QLIKE and HAC-DM.

Review at least three high-trust primary academic/data sources (including the HAR,
QLIKE/predictive-accuracy, and nested-predictive-inference foundations), plus official
Renaissance IPO ETF and VIX data documentation. Record verified URLs/DOIs, access
times, and the precise claim each source supports. Do not invent citations or infer
facts from inaccessible abstracts.

## Falsifiable question and preregistration

Test whether a lagged, point-in-time IPO-market cooling signal derived from the
Renaissance IPO ETF relative to SPY adds economically material one-day-ahead SPY
variance forecast information beyond a same-target HAR model that already controls
for lagged VIX. This is an empirical predictive-association study, not a causal or
trading-profit claim. Raw or partial correlation is descriptive only and can never
trigger the verdict.

Before inspecting OOS outcomes, freeze a machine-readable `preregistration.json`
containing every primary choice below, its hash, the model/loss sign conventions,
the full cell family, success/null/inconclusive rules, and all stopping anomalies.
Do not tune windows, weights, OOS start, proxy, bootstrap, or materiality after seeing
outcomes.

## Frozen data contract

- Retrieve and freeze daily `IPO`, `SPY`, and `^VIX` data through 2026-07-15
  (use an exclusive API end of 2026-07-16 where required). The common history begins
  no earlier than IPO's 2013-10-16 inception and the confirmatory OOS begins
  2018-01-02 after all warmups.
- Use split/dividend-adjusted IPO and SPY prices. If adjusted OHLC is constructed
  from raw OHLC plus Adj Close, validate the proportional adjustment around known
  corporate-action dates. Do not mix raw and adjusted series.
- Freeze exact input CSV bytes under `experiments/K1750/data/` and a provenance JSON
  with provider, query parameters, fetched-at UTC, timezone, column policy, row count,
  first/last date, duplicate/missing diagnostics, SHA-256, and byte size. A live API
  call alone is not reproducible evidence.
- Primary target: one-day SPY range-based variance from adjusted OHLC, chosen and
  named honestly as a proxy rather than intraday realized variance. Freeze either
  Garman-Klass or Parkinson in preregistration before outcomes; use the other and
  close-to-close squared return only as robustness. Never silently clip an invalid
  target into a favorable observation.
- Align to the SPY trading calendar, sort and deduplicate one-to-one, and bound any
  VIX forward-fill (maximum five calendar/market rows, with stale-tail diagnostics).
  VIX available at close t can first forecast target t+1.

If the frozen-source contract cannot be met, stop with `INSUFFICIENT_DATA` and preserve
the diagnostics. Do not substitute a different ETF, target, endpoint, or revised date
range after inspecting results.

## Signal, models, and common OOS ledger

Let `R_t = log(IPO_adjusted_close_t / SPY_adjusted_close_t)`. The unique headline
predictor is an equal-weight IPO-cooling composite:

1. negative 21-trading-day change in `R_t`;
2. negative drawdown of `R_t` from its trailing 252-trading-day maximum;
3. each component standardized with an expanding/causal scaler using only information
   available by its source date;
4. `ipo_cooling_signal = raw_composite.shift(1)` explicitly in `K1750.py`.

Individual components and 63-day relative momentum are secondary robustness only;
they cannot rescue a failed headline signal.

Use the same target, row mask, training dates, positivity/retransformation policy, and
forecast origins for every model:

- `B0` (diagnostic): log-HAR daily/weekly/monthly variance terms;
- `B1` (the only claim baseline): `B0` plus
  `log((VIX/100)^2/252).shift(1)`;
- `A` (candidate): `B1` plus the shifted IPO-cooling composite.

Primary horizon is H=1 with expanding estimation and at least 756 complete training
rows. Fit only on labels whose `target_end < forecast_origin`. Forecast positive
variance levels using the same causal log-to-level retransformation for B0/B1/A.
H=5/H=22, rolling-756, an added lagged-SPY-return leverage control, alternate target
proxy, OOS starts 2017/2019, early/late halves, and COVID exclusion are preregistered
secondary robustness. Apply Holm across any secondary family and never promote a
selected secondary cell to the headline.

Write `oos_forecasts.csv` with, at minimum, target date/value, forecast origin, every
feature source date, train maximum target-end date, B0/B1/A forecasts, pointwise losses,
and inclusion/exclusion reason. Save a ledger SHA-256 and exact row-count parity checks.

## Loss and nested-model inference contract

Use `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)` with the
canonical actual-over-predicted direction. Define
`delta_qlike = mean(loss_A - loss_B1)`, so a negative value favors IPO information;
also report the percentage improvement using a preregistered denominator.

`A` strictly nests `B1`. Therefore ordinary expanding-window DM/HLN is not valid as
the verdict-producing nested-model test. The older backlog wording does not override
the current mechanical gate:

- Report canonical HAC-DM plus the documented HLN finite-sample factor because K1750
  explicitly requested it, but mark it exactly `nested-dm: diagnostic-only` and
  `feeds_gate=false` everywhere. A thin HLN wrapper may adjust the canonical
  `dm_test` statistic, but must unit-test that the unadjusted statistic equals the
  canonical helper; do not reimplement a competing local DM.
- HAC lag must be at least
  `max(H-1, ceil(H^(1/3) * n^(1/3)))` (capped only as canonical code caps it). Report
  loss-difference ACF and lag sensitivity. For H=1, lag zero is forbidden.
- The primary general-loss inference is a restricted-null recursive moving/stationary
  block bootstrap: generate under B1, preserve dependence, and re-estimate the entire
  expanding B1/A OOS path in every replicate. Freeze block rule and at least 999
  replicates before outcomes; seed every stochastic path at 42. Include block-length
  sensitivity and preserve the bootstrap distribution as a byte-traceable sidecar.
- Clark-West on same-row MSE may be a nested-aware confirmation, never a substitute
  for the preregistered QLIKE claim. DM/HLN failure to reject cannot establish a null.

Run `scripts/experiment_gates.py run --path experiments/K1750` early enough to catch
the nested-DM role wiring before committing hours of compute, then run it again on the
final frozen bytes.

## Lookahead and falsification gates

The result must serialize zero-violation checks for all of the following:

- explicit `.shift(1)` on IPO, VIX, and all HAR feature paths;
- `max(feature_source_date) < target_start` for every forecast;
- `train_max_target_end < forecast_origin` for every fit;
- identical B1/A training rows, targets, forecast origins, and loss ledger;
- causal scaler/retransformation estimates derived only from each origin's past;
- unique dates and one-to-one merges;
- future-data perturbation invariance: altering data strictly after a cut date leaves
  every forecast at/before the cut byte-identical within the stated numeric tolerance;
- no candidate-output-dependent mask, tuning, clipping, or early stopping.

Save descriptive data diagnostics before estimation: missingness, duplicate dates,
extremes, trading-day coverage, variance distribution, IPO/VIX correlation, OOS counts,
and early/late/regime counts. Observation precedes estimation; a diagnostic anomaly can
stop the run but cannot be patched after seeing the result.

## Verdict and artifact contract

Primary economic materiality is a 1% reduction in mean QLIKE relative to B1.

- `SUPPORTED`: delta QLIKE is negative, improvement is at least 1%, the preregistered
  one-sided restricted-null bootstrap p-value is below 0.05, and major target/subperiod
  robustness is directionally stable.
- `CONDITIONAL_PASS`: formal nested-aware detection exists but improvement is below 1%
  or a major preregistered robustness is unstable.
- `BOUNDED_NULL`: no detection and the confidence bound excludes a benefit of 1% or
  more under the preregistered direction/materiality test.
- `INCONCLUSIVE`: no detection but a 1% benefit cannot be excluded, or power/data
  diagnostics are inadequate.
- `NULL_NEGATIVE`: nested-aware inference supports material worsening by A.
- `INSUFFICIENT_DATA` / `FAILED`: contract or execution failure, never a scientific null.

Required files include `README.md`, `K1750.py`, `K1750_results.json`,
`reproduce_spec.json`, `reproduce_commit.json`, `preregistration.json`, frozen data and
provenance, `oos_forecasts.csv`, bootstrap sidecar, useful plots/tables, and scoped
tests. README numeric claims must point to canonical JSON paths and agree byte-for-byte
with the frozen result.

The same successful execution that finalizes the artifacts must call
`volpred.research.reproduce_spec.finalize_experiment(...)` with canonical result
`K1750_results.json`, the exact frozen inputs and output sidecars, seed 42, start time,
and network-deny reproduction instructions. `reproduce_spec.json` is a sibling file,
not a field inside the results JSON. Verify result/spec/code/output identities.

Run the full experiment, scoped tests, Ruff on changed Python, future-perturbation and
ledger-parity tests, `scripts/reproduce_check.py inventory`,
`scripts/experiment_gates.py run`, and `scripts/check_experiment_artifacts.py check`.
The only acceptable pre-collection artifact warnings are main-thread knowledge and
independent review needs. Do not create `review_verdict.json`: the PHASE A collector
must commission a separate frozen-byte Codex review outside the reviewed worktree and
generate the verdict only through `experiment_gates.py verdict-template`.

Commit only literal files under `experiments/K1750/` on the worktree branch using a
writer-locked exact-path transaction. List every file literally; no glob, directory,
`git add -A`, push, merge, worktree removal, or shared-state mutation. Use ASCII commit
message `[agent] K1750 IPO heat experiment artifacts`.

Return the worktree commit SHA, exact run/test/gate commands, result/spec/ledger hashes,
canonical JSON paths for every numeric claim, primary delta QLIKE and bootstrap result,
diagnostic-only DM/HLN, verdict, robustness directions, and limitations. A valid null or
inconclusive result is acceptable; missing/stale artifacts are not.
