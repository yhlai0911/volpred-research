# P2 v2 Blocker Fix Note — 2026-06-05

## Scope

Address `Paper2_v2_fix_H1_H2_blocking` HIGH blockers in active paper body (`body_v3.tex`) plus specified editorial consistency fixes.

## Changes Applied

1. **H2 fixed — ELITE Material disclosed**
   - Added `2383.TW` (ELITE Material) to Section 2.1 data description.
   - Clarified that the primary leverage cross-section is the **9-stock non-TSMC set**, while `0056.TW` is an ETF sensitivity row.

2. **Cross-section labels clarified**
   - Updated summary/table labels from ambiguous `9-stock average (excl. 0056)` to `9-stock average (excl. 2330 & 0056)`.
   - Updated `10-security` label and notes to clarify it adds `0056.TW` back in while still excluding TSMC.

3. **M6 fixed — VaR model counts aligned to K896**
   - Replaced stale text claiming `GJR+Student-t` had `8` violations / `0.5%`.
   - Canonical model-level wording now matches `experiments/k896/k896_taiwan_es_supplement_results.json`:
     - `GJR+Student-t`: 18 violations, 1.03%
     - `GJR+HistSim`: 18 violations, 1.03%
     - `GJR+Cornish-Fisher`: 9 violations, 0.51%
     - `GJR+Normal`: 30 violations, 1.71%

4. **Portable XeLaTeX font fallback**
   - `main_v3.tex` now uses `PingFang TC` when available, otherwise falls back to `Songti TC`.
   - This resolves environment-specific compile failure on machines without `PingFang TC`.

## Verification

- `latexmk -xelatex -interaction=nonstopmode -halt-on-error main_v3.tex`
  - **PASS** (PDF built successfully)
  - Remaining output contains warnings only (`Overfull \hbox`, duplicate object warnings), no fatal compile errors.

## Remaining Notes

- H1 (`0050.TW γ=0.097`) was already consistent in the active `body_v3.tex` at the time of this pass.
- Reviewer-facing follow-up should re-check whether any abstract / non-body mirrored wording still uses stale leverage/VaR phrasing before submission.
