# K1259 B2-mini Backfill — HALTED (STOP condition triggered)

**Date**: 2026-05-17
**Task**: Backfill `experiment_id` provenance for the 20 oldest V1 violations (validate workflow before scaling B2-B5).
**Operator**: subagent (per K1259 cleanup roadmap)
**Outcome**: **HALTED — methodology blocker. No knowledge.json mutation written.**

## STOP condition

Per task spec:
> If you cannot determine provenance for >50% of the batch (>10 unknown), STOP and report — methodology may need rethinking before scaling to B2-B5.

Re-derived V1 population: **203 entries** (audit doc baseline = 200; +3 drift from new entries since audit). Sorted by `created_at` ascending; took first 20.

**Pre-write analysis verdict for the 20 oldest**:
- Entries with K-id mention in `content`: **0/20**
- Entries with verifiable experiments/ thematic match (stats hash to a results.json): **0/20** (spot-checked `459942fa` → `experiments/emd_garch_vol/`, QLIKE -8.738 not found; `884a1263` → `experiments/gjr_vs_ewma_crisis/`, DM=-6.27 not found)
- Entries that would receive `provenance_unknown: true`: **20/20 (100%)**

20/20 unknown >> 50% threshold → STOP.

## Root cause (methodology issue)

The 20 oldest V1 entries span **2026-03-14 19:40 → 2026-03-15 22:23 CST** — a single ~28-hour batch of legacy import / pre-K-id-discipline narrative entries. Earliest entry containing any `K\d{2,4}` reference (control sample query): around K43+ era. **The 200 V1 entries are not a uniform population — the oldest 50-150 are pre-discipline and structurally unrecoverable; the youngest 50 might trace to actual K-experiments.**

Attempting `experiment_path` attachment by thematic match (e.g. EMD-GJR content → `experiments/emd_garch_vol/`) violates the honesty rule: thematic overlap ≠ source verification, and the spot-check confirmed the exact stats in these entries (QLIKE -8.738, DM=-6.27) do not appear in the candidate experiments/ directories. Attaching the label would be fabricated provenance.

## Recommendation for B2-B5 redesign

Three options for main thread to choose:

**Option A (conservative)**: Restrict B2-B5 scope to entries with `created_at >= 2026-04-01` (post-K-id discipline). The remaining ~100 pre-2026-04 entries get a single bulk patch `provenance_unknown: true, provenance_note: "K1259 audit: legacy pre-K-id-discipline import"` and are excluded from violation count going forward (whitelist).

**Option B (medium)**: Restrict B2 to entries whose `content` matches a tight regex against active experiments/ directory names (e.g. `emd|garch|leverage|vix.term`); manually verify each before attaching. Likely yields 10-30 traceable across all 200 — not 50/batch.

**Option C (aggressive, NOT recommended)**: Force backfill by thematic match without stat verification. Violates K1259 v2 honesty rule (attaching K-id without verifying the stat number actually came from that experiment's results.json). Will create new false-provenance gap.

Main thread should pick A or B and revise the B2-B5 brief before re-dispatching.

## 20 oldest V1 entries (audit subset, not patched)

| item_id / id | created_at | content snippet |
|---|---|---|
| `K671_legacy_pilot` | null (legacy) | publication entry — VIX overshoot +36% p=0.025, references mile_9738acad |
| `884a1263` | 2026-03-14T19:40 | GJR vs GARCH SPY DM=-6.27 p<0.001 in QLIKE |
| `a5488d2c` | 2026-03-14T20:25 | DM test QLIKE hierarchy GJR-arch > GJR-HAR > GARCH (p=0.003) |
| `459942fa` | 2026-03-15T04:48 | EMD-GJR SPY OOS=2025 QLIKE=-8.738, VaR Kupiec FAIL p=0.019 |
| `be083f35` | 2026-03-15T04:52 | GJR residual Ljung-Box SPY 2020-2024 lag5/10/22 p=0.76/0.94/0.97 |
| `54eb47e0` | 2026-03-15T05:21 | SPY vol→return r=-0.002 p=0.86, 22d r=0.004 p=0.75 |
| `376d6365` | 2026-03-15T05:36 | Cross-asset spillover SPY/QQQ Granger p=0.74; SPY/GLD p=0.70 |
| `60dc7eb8` | 2026-03-15T09:51 | VIX→VT advantage corr -0.43 p<0.001 |
| `a308a9d5` | 2026-03-15T13:32 | VIX/VIX3M term structure → 22d realized vol corr 0.51 p<0.001 |
| `db498d0f` | 2026-03-15T14:42 | Persistence vs VT advantage corr 0.21 p=0.22 (ns) |
| `0d548d0a` | 2026-03-15T18:49 | GJR(1,1) w=504 Student-t(5) VaR Basel Green 6yr, Kupiec p=0.78 |
| `f7d3422d` | 2026-03-15T18:49 | (duplicate of above, condensed) |
| `fa8fa49b` | 2026-03-15T19:54 | Cross-asset leverage γ panel SPY/QQQ/GLD/TLT/BTC; DM GLD p=0.87 etc |
| `9c6da276` | 2026-03-15T20:22 | DM test panel (9 tests) SPY p=0.001, QQQ 2025 p=0.023, GLD p>0.35 |
| `bed06a33` | 2026-03-15T21:22 | Peer review responses (Parkinson DM p<0.001, HAC t=-5.79 p<0.001) |
| `415e6f6b` | 2026-03-15T21:31 | Conditional leverage SPY slope -0.36 p=0.02; GLD slope +0.49 p=0.04 |
| `c9ec2acc` | 2026-03-15T21:34 | GLD leverage regime-dependent t=-4.705 p<0.0001 |
| `2d08e949` | 2026-03-15T21:38 | Full DM test panel (12 tests, 6 assets) |
| `a0dab4ce` | 2026-03-15T22:01 | VIX/GARCH ratio VaR reliability point-biserial r=0.276 p<0.0001 |
| `039d0d41` | 2026-03-15T22:23 | GJR PIT calibration SPY 2020-2025 KS p<0.001, skew -0.71 |

## Validation (post-halt state)

- `storage/memory/knowledge.json` length: **2130** (unchanged from pre-task)
- No file modification performed; no atomic write attempted
- Violation count: unchanged (V1 baseline ≈ 203 in current snapshot)
- No git diff to leave for main thread

## Files

- This report: `docs/knowledge_k1259_b2mini_patch_2026_05_17.md`
- Audit doc reference: `docs/knowledge_k1259_audit_2026_05_17.md`
- V1 oldest-20 snapshot: `/tmp/v1_oldest20.json` (ephemeral)
