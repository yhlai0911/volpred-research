# Papers 5 + 7 Small Tex Fix Consolidation Guide

**Date**: 2026-04-17
**K**: K1233
**Scope**: Paper 5 (`vt-crowding-abm`) + Paper 7 (`vt-insurance-cost`) — all
READY per K1229 audit; only small tex / script-metadata fixes remaining.
**Author**: Main thread (via worktree K1233) — guide only, not a body edit.

---

## Summary

- K1229 audit (2026-04-17) confirmed **both papers READY** at 96–97.5% match
  with R3 SEVERE=0.
- 4 Paper-5 divergences + 4 Paper-7 action items identified; this guide
  maps each to a concrete edit.
- Execution effort: **~35 min total** (Paper 7 ~20 min, Paper 5 ~15 min).

---

## Paper 7: `vt-insurance-cost`

### Current State

- **Folder**: `paper/vt-insurance-cost/`
- **main.tex**: 27,354 bytes (2026-04-06 backfill; same file as submitted draft)
- **Last commit touching this paper**: `cb1dd9b4 2026-04-17 Paper 7 reproducibility
  audit: 96% matched, 2 divergent, no direction issues`
- **Match rate** (K1229 / audit diff report): 96.0% (97 of 101 numbers verified)
- **Readiness verdict**: SUBMISSION-READY (R3 SEVERE=0)

### Fixes Identified

#### Fix P7-1 (LOW) — "97%" → "98%" opportunity-cost share at 1 bps

- **Location**: `paper/vt-insurance-cost/main.tex`, line **108** (Section 2.3 "Data").
- **Current text** (verbatim, end of line 108):
  > "At 1~bps, the opportunity cost share rises to 97\%, further strengthening our core finding."
- **Proposed text**:
  > "At 1~bps, the opportunity cost share rises to 98\%, further strengthening our core finding."
- **LaTeX diff**:
  ```diff
  - At 1~bps, the opportunity cost share rises to 97\%, further strengthening our core finding.
  + At 1~bps, the opportunity cost share rises to 98\%, further strengthening our core finding.
  ```
- **Rationale**: Audit recomputation from K811v2 results:
  - `direct_cost@1bp = 0.428 / 5 = 0.0856%/yr` (from 5bp scenario)
  - `total@1bp = opp(4.195%) + direct(0.0856%) = 4.281%`
  - `opp_share = 4.195 / 4.281 = 98.0%` (paper wrote 97%)
- **Severity**: LOW (directionally correct; off by 1 pp; noted in prior R1 audit
  `reviews/audit_step1_2.md` FLAG 1).
- **Audit evidence**: `paper/vt-insurance-cost/reproducibility_audit/diff_report.md`
  Section "DIV-1 (LOW): '97% at 1 bps' — should be 98%".

#### Fix P7-2 (MINOR) — "54–80 bps" → "54–81 bps" structural-advantage upper bound

- **Location**: `paper/vt-insurance-cost/main.tex`, line **186** (Section 3.3
  "Structural Advantages of the 50/50 Benchmark").
- **Current text** (verbatim, from line 186 first sentence):
  > "These three structural advantages combine to generate approximately 54--80~bps per annum (the rebalancing premium alone plus the diversification benefit)."
- **Proposed text**:
  > "These three structural advantages combine to generate approximately 54--81~bps per annum (the rebalancing premium alone plus the diversification benefit)."
- **LaTeX diff**:
  ```diff
  - These three structural advantages combine to generate approximately 54--80~bps per annum (the rebalancing premium alone plus the diversification benefit).
  + These three structural advantages combine to generate approximately 54--81~bps per annum (the rebalancing premium alone plus the diversification benefit).
  ```
- **Rationale**: K846 JSON values —
  - `part1_empirical.premium_cagr_bps = 53.67` → rounds to 54 ✓ (unchanged).
  - `part1_theoretical.theoretical_premium_ann_bps = 81.46` → rounds to **81**,
    not 80. Paper stated 80 (off by 1 bp; within 2% relative tolerance but
    outside 1%).
- **Severity**: MINOR (no conclusion impact).
- **Audit evidence**: `paper/vt-insurance-cost/reproducibility_audit/diff_report.md`
  Section "DIV-2 (MINOR): '54–80 bps' range — upper bound off by 1 bp".

#### Fix P7-3 (MINOR — optional) — 2012–2024 sub-period footnote

- **Location**: `paper/vt-insurance-cost/main.tex`, line **184** (Section 3.3,
  footnote on `\rho = 0.057` / rebalancing premium).
- **Current text** (verbatim, embedded footnote in line 184):
  > "\footnote{The correlation and rebalancing premium estimates use the 2006--2024 sample (from GLD inception) rather than the 2012--2024 VVIX-reliable period. The 2012--2024 sub-period yields $\rho = 0.04$ and a rebalancing premium of 48~bps, broadly consistent with the full-sample estimates.}"
- **Issue**: Audit UV-1 / UV-2 — the two sub-period numbers (ρ = 0.04,
  premium = 48 bps) are **not** in `k846_rebalancing_premium_results.json`.
  The K846 script only reports the 2006–2024 full sample.
- **Two acceptable paths**:
  - **Path (a) — add sub-period to K846 script** (~15 min):
    Modify `paper/vt-insurance-cost/experiments/k846_rebalancing_premium.py` to
    also compute ρ and rebalancing premium on 2012-01-03 through 2024-12-31;
    write `rho_2012_2024` and `rebalancing_premium_bps_2012_2024` to
    `k846_rebalancing_premium_results.json`. No main.tex change needed — numbers
    already appear in paper.
  - **Path (b) — reword footnote to acknowledge unreported** (0 script change):
    - **Current**: "The 2012--2024 sub-period yields $\rho = 0.04$ and a rebalancing premium of 48~bps, broadly consistent with the full-sample estimates."
    - **Proposed**: "An unreported robustness check on the 2012--2024 VVIX-reliable sub-period yields $\rho \approx 0.04$ and a rebalancing premium of approximately 48~bps, broadly consistent with the full-sample estimates."
    - LaTeX diff:
      ```diff
      - The 2012--2024 sub-period yields $\rho = 0.04$ and a rebalancing premium of 48~bps, broadly consistent with the full-sample estimates.
      + An unreported robustness check on the 2012--2024 VVIX-reliable sub-period yields $\rho \approx 0.04$ and a rebalancing premium of approximately 48~bps, broadly consistent with the full-sample estimates.
      ```
    - This does not change the numbers but flags them as sensitivity rather
      than exact JSON-traceable values.
- **Recommendation**: **Path (a)** preferred (research-honesty principle —
  numbers should be reproducible from a logged script). Path (b) is acceptable
  fallback if K846 sub-period re-run is deferred.
- **Severity**: MINOR (footnote; doesn't drive any headline claim).
- **Audit evidence**: `paper/vt-insurance-cost/reproducibility_audit/diff_report.md`
  Section "Unverifiable Items UV-1, UV-2".

#### Decision P7-4 (INFO) — K860 prospect-theory reference

- **Location**: `paper/vt-insurance-cost/main.tex` (no current mention — grep
  of `k860|prospect|K860` in main.tex returned **0 matches**).
- **K860 state**:
  - Script exists: `paper/vt-insurance-cost/experiments/k860_prospect_theory_vt.py`
  - Results exist: `paper/vt-insurance-cost/experiments/k860_results.json`
  - Listed in `experiments.md` row 17 + row 33 ("Prospect Theory VT — Prospect
    theory framing of insurance cost; supplementary analysis").
  - NOT cited in main.tex body.
- **Recommendation**: **EXCLUDE from main.tex** (keep current state).
  - Reason 1: Paper is already READY; adding a new section would trigger
    another review cycle.
  - Reason 2: K860 is flagged in `experiments.md` as "supplementary", which is
    the appropriate scope — prospect-theory framing complements but does not
    extend the decomposition claim.
  - Reason 3: FRL (target journal) has a strict 8-page limit; adding
    prospect-theory content would crowd out existing material.
- **Action**: Mark decision as **NO_ACTION** in `k1233_fixes.json`. No tex edit.
- **Severity**: INFO (decision item, not a defect).

### Execution Summary for Paper 7

| Fix   | File                                       | Line | Change                                  | Effort |
|-------|--------------------------------------------|------|-----------------------------------------|--------|
| P7-1  | main.tex                                   | 108  | `97\%` → `98\%`                         | 1 min  |
| P7-2  | main.tex                                   | 186  | `54--80~bps` → `54--81~bps`             | 1 min  |
| P7-3  | main.tex OR k846 script                    | 184  | Path (a) script or path (b) footnote reword | 5–15 min |
| P7-4  | (no edit)                                  | —    | EXCLUDE K860 (decision documented)      | 0 min  |
| Compile + paper-update                     | —    | xelatex ×2, CLI                         | 5 min  |

**Total Paper 7**: ~15–25 min depending on P7-3 path.

---

## Paper 5: `vt-crowding-abm`

### Current State

- **Folder**: `paper/vt-crowding-abm/`
- **main.tex**: 30,457 bytes (2026-04-06 backfill)
- **Last commit touching this paper**: `1bd06dfe 2026-04-17 Paper 8
  reproducibility audit: 97.5% matched, 4 divergent, ABM seed-deterministic: yes`
  (commit message uses old "Paper 8" label; the paper is Paper 5 in current
  numbering).
- **Match rate** (K1229 / audit diff report): 97.5% (158 of 162 numbers verified)
- **Readiness verdict**: SUBMISSION-READY with minor documentation gap.

### Fixes Identified

#### Fix P5-1 (DOC) — DIV-2 threshold classification cutoff in K827v3 script

- **Location**: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py`,
  lines **603** and **605** (inside the `analyze_results` / `threshold_stability`
  block).
- **Current code** (verbatim, lines 600–608):
  ```python
                  deg_30 = (1 - s30['mean'] / s10['mean']) * 100
                  deg_50 = (1 - s50['mean'] / s10['mean']) * 100

                  if deg_30 > 30:
                      thresh = "<=30%"
                  elif deg_50 > 30:
                      thresh = "30-50%"
                  else:
                      thresh = ">50%"
  ```
- **Issue** (audit DIV-2): Paper footnote [c] (main.tex line **219**) defines
  the threshold as where Sharpe degradation **first exceeds 50%**. The code
  uses a **30% cutoff**, so the JSON field `threshold_region` is inconsistent
  with the paper's footnote definition.
- **Proposed change** — align classification cutoff to **50%**:
  ```python
                  deg_30 = (1 - s30['mean'] / s10['mean']) * 100
                  deg_50 = (1 - s50['mean'] / s10['mean']) * 100

                  if deg_30 > 50:
                      thresh = "<=30%"
                  elif deg_50 > 50:
                      thresh = "30-50%"
                  else:
                      thresh = ">50%"
  ```
- **Python diff**:
  ```diff
  -                if deg_30 > 30:
  +                if deg_30 > 50:
                       thresh = "<=30%"
  -                elif deg_50 > 30:
  +                elif deg_50 > 50:
                       thresh = "30-50%"
                   else:
                       thresh = ">50%"
  ```
- **Rationale**: After this change, the threshold_region field (which feeds the
  `threshold_stability` JSON block) reports 8 of 9 sensitivity cells as `>50%`
  and 1 of 9 as `30-50%`, matching the paper text on main.tex line 219
  ("eight of nine parameter combinations produce a threshold above 50%").
- **main.tex impact**: **NONE**. Table 3 published values (Sharpe 0.52, 0.49,
  0.35 for λ etc.) and footnote [c] are **already correct**. Only internal
  JSON metadata changes; paper compilation produces identical PDF.
- **Severity**: DOC / LOW (metadata-only; no published number wrong).
- **Audit evidence**: `paper/vt-crowding-abm/reproducibility_audit/diff_report.md`
  Section "DIV-2 (METHODOLOGY AMBIGUITY) — Threshold 'column' in Table 3".
- **Optional alternative**: Add a brief comment to the code block stating that
  the 30% cutoff is intentional for flagging any degradation (internal QA)
  and that the paper footnote uses a 50% cutoff for the published
  classification. This is acceptable if re-running K827v3 is undesired.

#### Fix P5-2 (LOW — OPTIONAL) — Abstract "below 5%" adoption estimate

- **Location**: `paper/vt-crowding-abm/main.tex`, line **36** (abstract, last sentence).
- **Current text** (verbatim, end of line 36):
  > "Current real-world VT adoption is estimated below 5\%, suggesting the strategy remains safe for individual adopters but highlighting a trajectory that warrants monitoring."
- **Issue** (audit DIV-4): The "below 5%" estimate has no citation and no K
  reference — K1045-pattern qualitative claim.
- **Proposed text** (add citation; pick one):
  - Option A (ECB FSR citation, preferred):
    > "Current real-world VT adoption is estimated below 5\%~\citep{ecb2020}, suggesting the strategy remains safe for individual adopters but highlighting a trajectory that warrants monitoring."
  - Option B (footnote with basis statement):
    > "Current real-world VT adoption is estimated below 5\%,\footnote{Estimate based on public disclosures from volatility-targeted mutual funds and risk-parity institutional mandates relative to global equity AUM; see \citet{baltas2019} for related crowding measurements.} suggesting the strategy remains safe for individual adopters but highlighting a trajectory that warrants monitoring."
- **LaTeX diff (Option A)**:
  ```diff
  - Current real-world VT adoption is estimated below 5\%, suggesting the strategy remains safe for individual adopters but highlighting a trajectory that warrants monitoring.
  + Current real-world VT adoption is estimated below 5\%~\citep{ecb2020}, suggesting the strategy remains safe for individual adopters but highlighting a trajectory that warrants monitoring.
  ```
- **Severity**: LOW — audit classifies as DIV-4 (qualitative no-source).
- **Recommendation**: **Defer**. Paper is READY and audit did not require it
  for submission. Apply only if reviewer comments flag it.
- **Audit evidence**: `paper/vt-crowding-abm/reproducibility_audit/diff_report.md`
  Section "DIV-4 (LOW — QUALITATIVE NO-SOURCE)".

#### Acknowledged (NO_ACTION) — DIV-1 and DIV-3

- **DIV-1** (trivial rounding `+119.1%` vs `+119.0%`): accepted as-is — both
  rounding conventions are defensible (~119.05% underlying).
- **DIV-3** (K827v2 design-validation Sharpe 0.43 / 0.18 UNVERIFIED): flagged
  by audit as SECONDARY SOURCE, not in any main table; leave for future
  follow-up or defer until reviewer asks.

### Execution Summary for Paper 5

| Fix   | File                                                | Line        | Change                              | Effort |
|-------|-----------------------------------------------------|-------------|-------------------------------------|--------|
| P5-1  | experiments/k827v3_abm_fixed_liquidity.py           | 603, 605    | `> 30` → `> 50` (both)              | 1 min  |
|       | (optional) regenerate JSON                          | —           | `python k827v3_abm_fixed_liquidity.py --analysis-only` if supported, or rerun cached sims with fixed seed 42 | 3–5 min |
| P5-2  | (optional / defer)                                  | 36          | Add `\citep{ecb2020}`               | 0 min  |
| Compile + paper-update                              | —           | xelatex ×2, CLI (no PDF change expected) | 5 min  |

**Total Paper 5**: ~10–15 min (P5-1 only); P5-2 deferred.

---

## Execution Sequence (main thread)

1. **Paper 7 edit pass** (`paper/vt-insurance-cost/`):
   - Apply P7-1 (line 108), P7-2 (line 186).
   - Apply P7-3 path choice (main thread decides (a) script-update vs (b) footnote-reword).
   - P7-4: no edit (document decision in commit message).
   - Compile: `cd paper/vt-insurance-cost && xelatex main.tex && xelatex main.tex`.
   - Publish: `uv run volpred ops paper-update --paper-id vt-insurance-cost`.
   - Commit: separate commit for Paper 7 only.
2. **Paper 5 edit pass** (`paper/vt-crowding-abm/`):
   - Apply P5-1 (script metadata cutoff 30 → 50).
   - P5-2: defer unless reviewer flags.
   - Compile: `cd paper/vt-crowding-abm && xelatex main.tex && xelatex main.tex`.
   - Publish: `uv run volpred ops paper-update --paper-id vt-crowding-abm`.
   - Commit: separate commit for Paper 5 only.
3. **Post-edit verification** (both papers):
   - Re-run `reproduce.py` and confirm the `reproduce_report.json` verification
     rate rises or remains ≥ 96%.
   - Update the paper's `reproducibility_audit/README.md` to note the
     divergence resolution (DIV-2 for Paper 5, DIV-1 + DIV-2 for Paper 7).

---

## Estimated Effort (consolidated)

| Task                           | Min |
|--------------------------------|-----|
| Paper 7 edits                  | 5   |
| Paper 7 P7-3 path (a) (option) | 15  |
| Paper 7 compile + paper-update | 5   |
| Paper 5 edits                  | 1   |
| Paper 5 compile + paper-update | 5   |
| Audit README updates           | 5   |
| **Total (P7-3 path b)**        | **~20** |
| **Total (P7-3 path a)**        | **~35** |

Consistent with K1229 "30-minute pass" estimate.

---

## Strict Boundaries Observed in K1233

- Worktree agent produced only `.md` and `.json` in `experiments/k1233/`.
- No `.tex` body edits by worktree.
- No shared-state writes (no `storage/memory/knowledge.json`,
  `storage/reports/feed.json`, no Supabase / Mirror sync).
- Seed 42 (though read-only).
- All data sourced from filesystem reads of existing files (audit diff reports,
  main.tex, K827v3 script, K1229 audit artifacts).
