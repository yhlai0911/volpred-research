# K841 methodology-repair independent review — PASS

- Reviewed at: 2026-07-15T23:40:00+08:00
- Reviewer: Codex fresh-context independent reviewer / GPT-5
- Frozen base commit: `cb3247d7e056e50f8f6cca1a95042767b88e8493`
- Verdict: **PASS**
- Blocking defects: none after the legacy-stream wording was narrowed

## Verification performed

The reviewer inspected the task brief, prior K841 implementation, repaired
source, README, frozen inputs, pointwise evidence, results, and focused
regression tests. The review independently confirmed:

- the old `range(h)` one-step helper included only lag zero, while the repaired
  final strategy comparison uses
  `strategy_dm_test(loss_fn="variance_risk")` and the already-squared legacy
  loss evidence uses the canonical `dm_test` directly;
- all seven old iid cells reproduce to their published four-decimal values and
  every canonical lag-13 HAC-only cell recomputes from the pinned evidence;
- every final DM cell recomputes exactly, positive squared daily returns are
  the stated variance-risk proxy, and the stored pointwise losses equal the
  stored returns squared;
- all six performance rows recompute from the dated strategy-return evidence;
- the analysis distinguishes same-base overlay ablations from cross-exposure
  diagnostics and does not use raw MDD to claim timing skill;
- a Taiwan-open-known weight is not applied to the already-realised overnight
  gap, each active night overlay pays its round-trip cost, and S5 includes the
  S1 stock-rebalance cost;
- Friday-PM/Saturday-AM continuation rows in a Monday TAIFEX file remain in the
  same night session;
- the Yahoo snapshot, final analysis slice, legacy evidence, and final return
  evidence are hash-pinned and fail closed; and
- the frozen-input run reconstructs 2,157 paired days from 2017-05-16 through
  2026-04-02, while all experiment-integrity gates pass.

The refreshed Yahoo snapshot changes the pointwise legacy arrays slightly from
earlier repair artifacts. The README now accurately says that the legacy
strategy construction and rounded published cells are reproduced on the
refreshed pinned snapshot; it no longer claims byte-identical legacy streams.

## Independently verified headline results

Canonical lag-13 HAC changes all seven legacy t statistics without changing
any `|t|>3` classification:

| Comparison | Old iid t | Corrected HAC t | Classification changed |
|---|---:|---:|:---:|
| S2 vs S1 | 10.8213 | 6.7855 | no |
| S2 vs S0 | -7.1306 | -8.1976 | no |
| S3 vs S0 | -1.9712 | -2.3880 | no |
| S3 vs S1 | 14.0087 | 8.2635 | no |
| S4 vs S0 | -4.4320 | -5.5126 | no |
| S4 vs S1 | 12.1384 | 7.6436 | no |
| S5 vs S1 | -0.7583 | -0.4931 | no |

On the fully repaired strategy construction, the claim-bearing same-base HAC
statistics are S2-vs-S0 `t=-7.6263`, S3-vs-S0 `t=-2.1031`, S4-vs-S0
`t=-5.1323`, and S5-vs-S1 `t=-0.7483`. Thus the always-on and high-VIX
overlays have lower squared-return risk than S0 under this proxy, while the
spike overlay and S5 comparison do not clear the conservative screen. These
statistics do not establish higher total return, Sharpe, utility, or causal
hedge effectiveness.

## Scope limitations retained

- The VIX input is the last close strictly before the actual night start. It is
  at least one US session stale and is not an intraday tradable hedge signal.
- The highest-full-file-volume TX expiry is an ex-post continuous-contract
  convention, not an executable roll rule.
- Returns and costs are an allocation approximation because the held stock/cash
  weight does not model natural self-financing drift between threshold events.
- Raw full-period and COVID drawdowns remain descriptive because exposures are
  not matched and no phase-randomisation null is supplied.
- The repair does not show that TAIFEX night hedging is generally unworkable;
  intraday VIX/VIX-futures signals and an ex-ante roll rule remain untested.

## Frozen hashes and checks

- Yahoo snapshot: `e099454ea239f8b5bbc999c5536dafc16b99af57a3afde9a028f371aa869a899`
- Final analysis slice: `79970c5d4fdc2b998511e27923671e0e56d5d102358fc856ea5cc6ee42ad617b`
- Legacy evidence NPZ: `a2121b39e9a06dc96630650325d76dcf26bda05de197856f48a5bc3c2e654ab9`
- Strategy-return NPZ: `28b36ed0108628404fccedba509df61f3652f1c46a4ad2ad0a2081734b86ebad`

Observed verification commands:

```bash
uv run python experiments/k841/k841_futures_realtime_vt.py
VOLPRED_CI_PARITY=0 uv run --extra dev python -m pytest experiments/k841/test_k841_methodology_repair.py tests/test_strategy_dm_variance_risk.py scripts/tests/test_dm_hac_lag_ratchet.py -q
uv run python scripts/experiment_gates.py run --path experiments/k841
```

The combined focused suite passed 31 tests, and the experiment gate reported
PASS for all scoped integrity checks.
