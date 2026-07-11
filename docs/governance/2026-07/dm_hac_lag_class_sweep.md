# DM HAC bandwidth — bug-class full-population sweep

**Date**: 2026-07-11 (hourly-18)
**Trigger**: K1655 primary-path Codex re-verify FAIL (2026-07-11 hourly-16)
**Task**: `k1655_dm_lag_class_sweep`
**Scope**: `experiments/**/*.py`, full population, static AST analysis

## The defect

A local Diebold-Mariano helper that computes its Newey-West correction as

```python
for k in range(1, h):          # or: lag = h - 1
    var_d += 2 * (1 - k / h) * autocov(d, k)
```

applies **no HAC correction at all when `h == 1`**, because the loop is empty.
The canonical helper `volpred.stats.model_evaluation.dm_test` floors its
bandwidth at 1 and scales it with the sample —
`max_lag = max(1, min(ceil(h**(1/3) * n**(1/3)), n // 4))` — so it never degenerates.

In K1655 the loss differential had `acf(1) = 0.68` (a persistent predictor, NFCI),
the missing correction understated the standard error, and Harvey-significant DM
cells fell from **26 to 18 out of 60** once the bandwidth was floored.

## Materiality caveat — read before quoting any number here

**Exposure is structural, not a proven error.** Zero HAC at `h == 1` *is* the
textbook DM statistic: under a correctly specified one-step forecast the loss
differential is a martingale difference sequence and needs no correction. The
rule only fails when the differential is genuinely autocorrelated — a misspecified
challenger, or a persistent predictor.

Static analysis cannot tell the two apart. **Whether any given site's conclusion
actually changes is an empirical question about that site's loss differential, and
answering it means re-running the experiment and measuring the acf.** Nothing in
this document should be reported as "N wrong results".

## Findings

570 local DM implementations across `experiments/` (after excluding name-matched
helpers that compute no test statistic).

| Verdict | Count | Meaning |
|---|---|---|
| `degenerate_at_h1` | 139 | `range(1, h)` — zero HAC when h=1 |
| `unknown` | 195 | bandwidth binding not statically resolvable |
| `h_lags_inclusive` | 21 | `range(1, h+1)` — keeps lag 1, but never scales with n |
| `hardcoded` | 1 | fixed integer bandwidth |
| `canonical_like` | 204 | n^(1/3)-shaped rule, or floored at ≥1 |
| `delegates_to_canonical` | 10 | wraps the repo's `dm_test` |

**Structurally exposed** (degenerate bandwidth *and* the file exercises an h=1
cell): **130 experiment directories**. Of those, **95 have entries in
`storage/memory/knowledge.json`** — i.e. they carry a live downstream claim, so
they are the triage priority.

Full machine-readable report: `storage/ops/dm_hac_lag_audit.json`.

## Blind-spot analysis (required by the audit-methodology hard rule)

- **`unknown` (195) is the real blind spot.** It is not homogeneous. Inspection
  found both benign and non-benign members:
  - `K1611.py::dm_hln` computes **both** variants (`t_hln` at h-1 *and* `t_hac`
    with a data-driven Bartlett lag) and its docstring states the primary reported
    bar is `t_hac`. That is the *correct* pattern — the one K1655 failed to follow.
  - `classify_dm_status()`, `plot_dm_heatmap()` and similar read `t_stat` keys and
    so survive the "computes a test statistic" filter without being tests. Noise.
  - The remainder bind their bandwidth through a call or a branch the AST walker
    does not resolve to a single expression.
  These need eyes, not a regex. They are **not** counted as exposed.
- **The static verdict is not the failure mode.** K1655's actual defect was not
  "the file contains `h-1`" — the correct HAC helper was *already there*. It was
  that the h-1 variant was the one feeding the published claim. A file can be
  `canonical_like` by this audit and still report the wrong variant as primary.
  **This audit cannot detect that**, and any per-site re-run must check which
  statistic the README / knowledge entry / article actually quotes.
- **`h_lags_inclusive` (21) is a weaker but real issue**: it keeps lag 1 so it does
  not zero out, but the bandwidth never grows with n, so it under-corrects when the
  differential is persistent beyond lag 1. Lower priority, not clean.
- **Scope is `experiments/` only.** `src/`, `scripts/` and `paper/` reproduce
  scripts were not swept.

## Enforcement (anti-stacking: one owner)

| Layer | Artifact |
|---|---|
| Enforcement owner | `scripts/tests/test_dm_hac_lag_ratchet.py` — new degenerate local DM fails CI |
| Auditor | `scripts/audit_dm_hac_lag.py` |
| Frozen backlog | `storage/ops/dm_hac_lag_baseline.json` (139 sites; may only shrink) |
| Rule pointer | `.claude/rules/experiments.md` § DM 的 HAC 落後期不可只用 `h-1` |

The gate is a **ratchet**, not a clean-tree assertion: the 139 existing sites are
frozen, the class cannot grow, and each site leaves the baseline only after it is
re-run and corrected. It was verified to bite — a synthetic new local DM with
`range(1, h)` was planted in a throwaway worktree and the gate failed on it.

## What this sweep did NOT do

Re-running 130 experiments is far outside one dispatch slot. The exposed sites
that carry live knowledge claims are queued as follow-up work, priority-ordered by
whether the DM result is load-bearing for a published article or a paper. Sites
whose DM is diagnostic-only can be corrected lazily; sites whose Harvey-significance
*is* the headline claim must be re-run before their claim is quoted again.

## 2026-07-12 blind-spot expansion

The follow-up audit expanded the population to `paper/*/experiments/**/*.py` and
replaced the original narrow pattern matcher with AST evidence for four missed
classes: plain-variance / `diff.std()` inference, zero floors such as
`max(0, h-1)`, explicit `h<=1` iid branches, and iid exception fallbacks behind
a canonical normal path. It also distinguishes canonical wrappers and
block/stationary bootstrap from local no-HAC implementations.

The corrected machine report contains **615 path-level local findings**:

| Verdict | Count |
|---|---:|
| `no_hac` | 80 |
| `degenerate_at_h1` | 148 |
| `unknown` | 78 |
| `h_lags_inclusive` | 28 |
| `hardcoded` | 9 |
| `canonical_like` | 225 |
| `dependence_robust_resampling` | 8 |
| `delegates_to_canonical` | 39 |

There are 35 paper-path findings. These are kept as separate ratchet keys even
when a paper package currently duplicates a root experiment, because either copy
can diverge later. The active ratchet is **228 sites**: 128 remaining from the
original cohort plus a separately frozen 100-site blind-spot cohort. The audit
set and baseline set are exactly equal (`new=0`, `stale=0`); repaired sites still
move to the retired ledger and cannot reappear. Twelve regression tests cover
the named VIX-sufficiency/EAV/Taiwan sites plus the zero-floor, manual-HAC,
canonical-wrapper, result-reader, and dependence-robust false-positive traps.
