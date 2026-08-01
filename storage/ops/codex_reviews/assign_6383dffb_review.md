# assign_6383dffb — Matt implement / TDD / code-review receipt

Review fixed point: `57ae90f2a17488d7b963c60d90d3c86dba97cc54`

## Ticket scope

- Salvage generic Holm step-down and exact fixed-count label permutation logic
  from rejected branch `codex/k1707-pseudo-stress` without merging its science.
- Replace K1380's local Holm implementation and reproduce its committed result
  byte-for-byte.
- Preserve the branch's independent sample-inventory agreement, then retire the
  rejected branch only after review and durable evidence retention.
- Prevent new local copies rather than creating a third implementation.

## TDD evidence

- Branch self-checks: Holm `[0.01, 0.04, 0.03] → [0.03, 0.06, 0.06]` and the
  four-value exact permutation (`difference=2`, `6` allocations).
- K1380's 15-test adjusted p-values match the committed correction artifact at
  `atol=1e-15`; a full rerun leaves result SHA-256
  `0eeeab129ff7634b00b33a15726527207d0f059e3c83220fb84ff6077f94bc81`
  unchanged.
- Exact permutation regressions cover invalid groups, computation cap,
  tiny-scale effects, and translation invariance under a `+1e16` common level.
- Ratchet regressions cover new helpers, duplicate same-name helpers, parse
  failure, untracked other-session WIP, stale active entries, retired
  resurrection, and active/retired overlap.
- Final focused suite: 41 tests passed; Ruff passed; live ratchet returned no
  new, stale-active, or resurrected sites.

## Two-axis review

### Spec review — PASS

Initial findings and resolutions:

1. P1: live-filesystem scan read ignored/untracked experiment data. Fixed by
   enumerating Git tracked/index experiment paths in a checkout; temp fixture
   repos retain filesystem mode.
2. P2: absolute `1e-12` tail tolerance swallowed tiny effects. Removed; the
   observed allocation and permutations now use the same strict statistic.
3. P2: uncentered `total - high_sum` lost translation invariance. Fixed by
   centering every value on one common anchor before all test-statistic sums.

Final verdict: **PASS**, no remaining P1/P2.

### Standards review — PASS

Initial findings and resolutions:

1. P2: stale active baseline entries allowed later resurrection. The ratchet
   now fails on stale active entries, retired resurrection, and active/retired
   overlap.
2. P2: deleting the branch would eventually garbage-collect the evidence behind
   the cross-implementation claim. A 74 KiB thin Git bundle is now committed;
   `git bundle verify` and a fresh bare-repository restore both read back tip
   `de0dbef8…` and result SHA `f381380a…` exactly.

Final verdict: **PASS**, no remaining P1/P2.

## Release decision

Implementation is approved for exact-path commit. Branch retirement remains a
separate post-commit action: first prove the bundle is tracked in the commit,
then delete only the exact local branch and write a terminal retirement receipt.
