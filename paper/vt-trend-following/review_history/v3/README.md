# Review Round v3 — vt-trend-following

**Date**: 2026-05-23
**Triggered by**: First review of body_v3.tex (all prior rounds R1-R4 were on body_v2; body_v3 introduced partial-update inconsistencies)
**Reviewers**:
- citation-verifier (agent a1250b11df4842d73)
- latex-academic-reviewer (agent ae31826a372a0785f)

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | CONDITIONAL_PASS — 4 MAJOR, 3 MEDIUM | ⚠️ |
| Academic | review_needed — 3 HIGH, 11 MEDIUM, 6 LOW | ❌ → fix HIGH then back to ✅ |

**Root cause**: body_v3 applied partial updates (fixing text in sections but not corresponding table cells), creating 3-way contradictions between section text, tables, and abstract.

## High-Priority Issues (fix immediately)

### H1 — Table 3 Stale (= Citation MAJOR-1)
- **Location**: `body_v3.tex` Table 3 (tab:decomposition)  
- **Problem**: Section 3.3 text updated to K1192 canonical (SPY VT=-26.31%, Hedged=-25.25%, retention=103.7%) but Table 3 still shows v2 values (VT=-24.7%, Hedged=-26.9%, 92.8%)
- **Fix**: Update Table 3 values to match K1192 canonical JSON
- **Source JSON**: experiments/ (K1192 MDD bootstrap)

### H2 — Table 2 Panel B CI Impossible (= Citation MAJOR-3)
- **Location**: `body_v3.tex` Table 2 Panel B
- **Problem**: Header shows r=0.793 (correctly updated) but CI row still reads [0.114, 0.737] from old r=0.487 — mathematically impossible (upper bound < point estimate)
- **Fix**: Update CI to K1193 canonical values
- **Source JSON**: experiments/ (K1193 split-sample)

### H3 — International Dual-Source (= Citation MAJOR-2)
- **Location**: Abstract, Section 3.5, Table 5, Conclusion, Section 4.3
- **Problem**: Abstract/Section 3.5 use K1178 canonical (24.9 pp, t=10.25, r=-0.806, ρ=-0.835) but Table 5, Conclusion, Section 4.3 use different numbers (28.7 pp, t=15.70, r=-0.770, ρ=-0.720)
- **Fix**: Pick one canonical source and synchronize all locations
- **Source JSON**: experiments/K1178

### H4 — Broken \ref (= Citation MAJOR-4)
- **Location**: `body_v3.tex` line ~528
- **Problem**: `\ref{tab:intl_vix}` should be `\ref{tab:international}` 
- **Fix**: Simple sed fix

## Deferred MEDIUM Issues (from R4, carry-over)

- Hood & Raughtigan (2025) no SSRN/institution link
- Newey-West lag formula: cite NW (1994) not (1987)
- Baltas & Kosowski: published 2019 version available
- Frazzini & Pedersen (2014) not cited despite BAB factor usage

## After Fixing H1-H4
- Returns to R4's HIGH=0 status
- Academic score back to ~4★
- Stage: ready_for_submission (conditional on MEDIUM resolution)

## Compilation Status (before fixes)
- body_v3.tex: compiles, but Table 3/Table 2 Panel B/Table 5 show contradictory data
- Fix H4 first (broken ref → PDF shows "Table ??")

## Fix Applied (2026-05-23)

All 4 HIGH issues fixed in body_v3.tex (commit: see git log):

| Issue | Fix | Source |
|-------|-----|--------|
| H4 | `\ref{tab:intl_vix}` → `\ref{tab:international}` | direct |
| H2 | `Bootstrap 95% CI [0.114,0.737]` → `90% CI [0.589,0.919]` | K1193 canonical |
| H3 | Table 5 avg 28.7→24.9 pp, t=15.70→10.25, r=-0.770→-0.806, ρ=-0.720→-0.835 + Figure 2 caption + Discussion + Conclusion | K1178 canonical |
| H1 | Table 3 SPY VT MDD -24.7→-26.3, Hedged -26.9→-25.3, Calmar 0.301→0.283 / 0.264→0.281, protection 30.5→28.9 pp, retained 28.3(93%)→29.9(103.7%) | K1192 canonical |

Compiled: XeLaTeX 0 errors (2 passes, 2026-05-23 07:xx Taiwan time).

**Post-fix status: HIGH=0, 13 MEDIUM, 7 LOW. Returns to R4's HIGH=0. Paper ready for R5 review.**
