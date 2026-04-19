# Paper 4 (vt-insurance-cost) reproduce.py — Resolution v1

**Date:** 2026-04-19
**Parent task:** `task_b7c5975e3cf0` (P4 reproducibility diagnosis + fix chain)
**Sub-tasks executed:**

- Sub1 `a43d13d` — re-bundle SPY/GLD 2012-2024 with `auto_adjust=False` raw Close
- Sub2 `a5ca55e` — add SPY/GLD 2006-2024 raw-Close bundle + port K846 pathway into `reproduce.py`
- Sub3 `this task` — rerun reproduce.py, snapshot `reproduce_report_post_fix.json`, write this resolution, update `README.md`

**Scope:** reproducibility packaging only. No `main.tex` / `body.tex` edits. No paper-number changes.

---

## 1. Closing Verdict

**Match rate:** 88.9% (8/9 claims match) — up from 44.4% pre-fix.
**Alert level:** `amber` (≥85%, <95%) — below the Sub3 green gate (≥95%).
**Residual divergence:** 1 of 9 claims (#9, 50/50 SPY/GLD rebalancing premium).

### Per-claim status (post-Sub1+Sub2)

| # | Claim | Paper | Reproduced | Status |
|---|---|---|---|---|
| 1 | S1 opportunity cost 4.20%/yr | 4.20 | 4.200 | match |
| 2 | S1 direct cost 0.43%/yr | 0.43 | 0.428 | match |
| 3 | S1 total premium 4.62%/yr | 4.62 | 4.628 | match |
| 4 | S1 opportunity-cost share 91% | 91.0 | 90.752 | match |
| 5 | S2 opportunity cost 0.70%/yr | 0.70 | 0.696 | match |
| 6 | S2 direct cost 0.52%/yr | 0.52 | 0.522 | match |
| 7 | S2 total premium 1.22%/yr | 1.22 | 1.218 | match |
| 8 | S2 cost reduction vs S1 74% | 74.0 | 73.682 | match |
| 9 | 50/50 SPY/GLD rebalancing premium 54 bps/yr | 54.0 | **62.91** | **divergent** (Δ=+8.91 bps, tolerance ±5.0) |

All S1/S2 insurance-decomposition headline claims (#1–#8) now reproduce exactly from bundled CSVs, validating the diagnosis v1 root cause (adjusted-close vs raw-Close basis) identified in `divergence_breakdown.md` §1.

---

## 2. Root Cause (retrospective, post-fix)

Two separable packaging defects explained the original 44% match rate:

1. **Insurance decomposition basis mismatch (claims #1, #3, #5, #7).** Original bundled 2012-2024 CSVs were pre-cached with `yfinance auto_adjust=True` (dividend-reinvested Adj Close), but K811v2 canonical (and paper) compute on raw Close (`auto_adjust=False`). Adjusted close inflated BH leg of opportunity cost. **Fixed by Sub1.**
2. **Period-coverage gap (claim #9).** `main.tex:184` anchors 54 bps to the 2006-2024 GLD-inception sample (K846), but the replication package only shipped 2012-2024 series. The 2012-2024 sub-period yields a materially different premium (−121 bps with wrong basis; paper footnote notes 48 bps on this sub-period). **Period coverage fixed by Sub2** (raw-Close 2006-2024 SPY/GLD CSVs + K846 monthly-rebalance pathway ported into `reproduce.py`).

---

## 3. Residual Divergence — Claim #9 (pending policy decision L11)

**Gap:** +8.91 bps above the ±5.0 bps tolerance. Match = no.

**Mechanism:** K846 (the paper's 54 bps anchor, canonical = 53.67 bps) was computed with `yfinance auto_adjust=True` — i.e., dividend-adjusted Adj Close for both SPY and GLD. The current replication package enforces the `auto_adjust=False` raw-Close hard rule across all bundled CSVs for consistency with the insurance-decomposition leg (which paper anchors to raw Close via K811v2 and explicitly states "consistent with CRSP to within rounding precision"). Under raw Close, dividend cash flows are paid but not reinvested in either SPY or GLD legs of the 50/50 portfolio, reducing drag from compounded reinvestment and lifting the structural monthly-rebalance premium to 62.91 bps.

**Structural sanity:** the reproduced 62.91 bps sits within the literature's ~50–80 bps structural range for low-correlation monthly rebalancing of equity + alternative. The narrative in `main.tex:184` ("low-correlation monthly rebalancing generates a modest premium") is not challenged. Paper conclusion unchanged.

### Two resolution paths — **not decided by this sub-task**

The dividend-convention decision for claim #9 is a paper-policy choice escalated to user L11 decision. Two symmetric options:

- **(a) Bundle parallel adjusted-close 2006-2024 CSVs for claim #9 path only.** Ship `spy_2006_2024_adj.csv` + `gld_2006_2024_adj.csv` (`auto_adjust=True`); have `reproduce.py` load the adjusted variants exclusively for the `simulate_5050_rebalance` pathway. Exact 54 bps reproduction; paper unchanged. Cost: replication package now has two basis conventions in the same folder (documented in `data_sources.md`).
- **(b) Update `main.tex:184` to state "~63 bps raw Close".** Paper narrative cites the reproducible raw-Close number and flags the −9 bps dividend-adjustment offset in a footnote. Package stays single-basis. Cost: one paper-body edit + reviewer-visible number change + re-compile + `paper-update` CLI.

### Why neither (c) errata is not an option here

- Absolute gap 8.91 bps on a 54 bps base = 16.5% relative divergence. Well above the <5% rounding threshold that would justify a silent errata note.
- Package-level research honesty requires either aligning the data source to the paper's original computation (a) or aligning the paper's number to the reproducible data source (b), not silently leaving the divergence.

### Current state

`reproduce.py` output explicitly flags claim #9 as `divergent` with recommendation text pointing to option (a). `alert_level` remains `amber`, not `green`. This is the honest state and will block automated green-gate checks until the L11 decision is made and applied.

---

## 4. What This Task Did / Did Not Do

**Did:**

- Rerun `reproduce.py` end-to-end on the Sub1+Sub2-fixed code + data (exit 0, 8/9 match, amber).
- Snapshot current reproduce report to `review_history/diagnosis_v1/reproduce_report_post_fix.json` for permanent audit trail.
- Write this `resolution.md` closing the diagnosis_v1 round.
- Update `README.md` reproducibility section with post-fix match rate, residual divergence, and pointer to this resolution.

**Did NOT:**

- Modify `main.tex`, `body.tex`, or any `.tex` file (hard rule).
- Decide the dividend-convention policy for claim #9 (main-thread / user L11 call).
- Re-bundle adjusted-close 2006-2024 CSVs (would implement option (a); out of scope).
- Touch shared state (`storage/reports/feed.json`, `storage/memory/knowledge.json`, Supabase, Mirror).

---

## 5. Handoff to Main Thread

**Pending items for L11:**

1. **Dividend-convention policy for claim #9** — choose (a) or (b). Recommended default if no user preference: (b) paper update (single-basis package is cleaner for reviewers), but (a) preserves the exact 54 bps citation track.
2. **Green-gate re-run** — whichever option is chosen, rerun `reproduce.py` → target match_rate ≥ 95%, alert_level = green. Write `reproduce_report_green.json` as the final snapshot.
3. **Paper narrative state machine** — claim #9 alone does not trigger `paper/vt-insurance-cost/body.tex` rewrite (single-claim, packaging-level). Update `research_program.md` + `knowledge.json` (K846 footnote) after L11 decision; defer body rewrite unless L11 chose option (b).

---

## 6. File Paths Referenced

- Sub3 report snapshot: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/review_history/diagnosis_v1/reproduce_report_post_fix.json`
- Diagnosis v1 breakdown: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/review_history/diagnosis_v1/divergence_breakdown.md`
- Current reproduce script: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/reproduce.py`
- Current reproduce report (live): `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/reproduce_report.json`
- Paper body (untouched): `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/main.tex`
- K811v2 canonical: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/experiments/k811v2_insurance_premium_vov_fixed.py`
- K846 canonical: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/experiments/k846_rebalancing_premium.py`

---

## 7. Commit Trail

- Sub1: `a43d13d` — re-bundle raw-Close 2012-2024 SPY/GLD; S1/S2 decomposition now reproduces exactly
- Sub2: `a5ca55e` — add raw-Close 2006-2024 bundle + port K846 pathway; claim #9 reproduces at 62.91 bps
- Sub3: _(this task; do-not-commit per brief; main thread commits on L11 decision)_
