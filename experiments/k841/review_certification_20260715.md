# K841 methodology-repair independent review — PASS

- Reviewed at: 2026-07-15T23:28:00+08:00
- Reviewer: Codex fresh-context independent reviewer / GPT-5
- Frozen base commit: `48f350cda0d51ba4c3c0d0baeee530f9dd32c270`
- Verdict: **PASS**
- Blocking defects: none after the byte-bound verdict is added

## Verification performed

The reviewer inspected the task brief, the prior K841 implementation, the
repaired source, README, frozen inputs, pointwise evidence, results, and focused
regression tests. The review confirmed:

- the old `range(h)` one-step helper used only lag zero, while both the
  legacy-stream attribution and the final analysis now delegate to the
  repository's canonical Bartlett Newey-West HAC-DM implementation;
- the frozen legacy loss arrays reproduce all seven old iid statistics and
  recompute every lag-13 HAC-only result cell by cell;
- the final dated return arrays recompute every reported final DM cell, with
  positive squared daily returns used explicitly as a variance-risk proxy;
- the final analysis distinguishes same-base overlay ablations from
  cross-exposure diagnostics and does not use raw MDD to claim timing skill;
- a Taiwan-open-known weight is not applied to the already-realised overnight
  gap, each active night overlay pays its round-trip cost, and S5 includes the
  S1 stock-rebalance cost;
- Friday-PM/Saturday-AM continuation rows in a Monday TAIFEX file remain in the
  same night session;
- the Yahoo snapshot, final analysis slice, legacy evidence, and final return
  evidence are hash-pinned and fail closed;
- the full frozen-input run reconstructs 2,157 paired days from 2017-05-16
  through 2026-04-02, and all four experiment-integrity gates pass.

The focused pytest suite executed seven tests successfully. Before commit,
pytest's repository-parity fixture correctly reported the new test and two
evidence files as untracked; that is a delivery-state warning, not a test
failure, and disappears once those exact files are committed.

## Independently verified headline results

For the unchanged legacy strategy streams, canonical lag-13 HAC changes all
seven t statistics but none of the repository's `|t|>3` classifications:

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
- Raw full-period and COVID drawdowns remain descriptive because exposures are
  not matched and no phase-randomisation null is supplied.
- The repair does not show that TAIFEX night hedging is generally unworkable;
  intraday VIX/VIX-futures signals and an ex-ante roll rule remain untested.

## Commands observed

```bash
uv run python experiments/k841/k841_futures_realtime_vt.py
uv run --extra dev python -m pytest experiments/k841/test_k841_methodology_repair.py -q
uv run python scripts/experiment_gates.py run --path experiments/k841
```

The full run exited 0, the seven focused tests passed, and the experiment gate
reported PASS for all four scoped integrity checks.
