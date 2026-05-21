# Review Round v7 — leverage-direction

**Date:** 2026-05-22
**Triggered by:** post-v7-fixes-verify (v6 review found H-1 blocking refs + M-2/M-3/MED-1; v7 applied all fixes; this round verifies and checks for residuals)
**Reviewers:**
- latex-academic-reviewer (agent a5fa0f9744ce79377)
- citation-verifier (agent a00573cec5f9c9c96)

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Academic | 2 residual hardcoded refs (tables.tex line 147, body line 17); H-3 NEW factual contradiction Trinity pass rates | 3.5★ NEAR_READY |
| Citation | campbell2017 DOI corrected; engle1982/hood2025/cederburg2020 v7 changes verified correct | PASS_WITH_NOTES |

**Combined status after v7 round fixes: NEAR_READY → targeting READY**

Two fixes applied in this session (v7 round):
1. ✅ tables.tex line 147: `Section~4.5` → `Section~\ref{sec:var_compliance}`
2. ✅ body.tex line 249: Corrected Trinity pass rate contradiction — Skewed-t 90.5%(19/21) ≠ FHS 76.2%(16/21); also corrected "FHS leads 7/7" → "FHS leads 6/7 by all-α-pass count"

---

## V6 Fixes Verification

- ✅ H-1 (16 hardcoded Section/Table refs): Converted to \ref{} — 6 labels added (sec:data, sec:vt_methodology, sec:leverage_direction, sec:garch_comparison, sec:var_compliance, sec:vt_results)
- ✅ M-2 (hood2025 subtitle): Full title confirmed — "Volatility targeting is trendy: How trend following explains alpha in volatility-managed strategies"
- ✅ M-3 (engle1982 citation): bibitem added (Econometrica 50(4) 987-1007) + \citep{engle1982} at body line 67
- ✅ Citation MED-1 (cederburg2020 framing): Negative headline finding ("VT does not systematically improve Sharpe across 103 strategies") now present

---

## Issues Found in v7 Review

### HIGH severity — now fixed in this session

1. **H-1 residual — tables.tex `Section~4.5`** (tables.tex line 147): `Section~4.5` was not converted to `\ref{}` in v6/v7. **FIXED** → `Section~\ref{sec:var_compliance}`.

2. **H-3 NEW — Trinity pass rate factual contradiction** (body.tex line 249): Text said "skewed-t and FHS share the highest Trinity pass rate at 76.2% (16/21)" but table (tab:var_panel) shows Skewed-t = 90.5% (19/21) and FHS = 76.2% (16/21). Root cause: tables.tex had updated values post-errata but body.tex retained old values. **FIXED** → "skewed-t achieves the highest Trinity pass rate at 90.5% (19/21); FHS, CF-VaR, and Student-t(5) follow at 76.2% (16/21)." Also corrected "FHS leads (7/7)" → "FHS leads by asset count (6/7 all-α-pass)" which is consistent with the table's 6 ✓ marks for FHS.

### MEDIUM severity — deferred (advisory, not blocking)

3. **M-1: Roadmap paragraph line 17** — "Section 2 reviews... Section 6 concludes." Academic reviewers flagged this as hardcoded. However, the organization paragraph is a widely accepted convention in academic papers; plain "Section 2" reads more naturally than `\ref{sec:literature}`. Decision: **LEAVE AS IS** (standard convention; converting would not improve readability).

4. **M-2: γ symbol overload** (body.tex line 495 area): The paper uses γ for both GJR-GARCH leverage parameter AND CRRA risk-aversion coefficient in the VT section. Recommend disambiguating with a footnote or subscript (e.g., γ_RRA vs γ_GJR) at first occurrence of each.

5. **M-3: Abstract date mismatch** — Abstract says "2017–2025" but data section says "January 2017 through March 2026." Update abstract to "2017–2026" for consistency.

### Minor — advisory only

- **Glosten 1993 data frequency** (body.tex line 76): Text says "fewer than 3,000 daily observations"; Glosten et al. (1993) used monthly data (~462 monthly observations). Recommend changing to "approximately 38 years of monthly data (~462 monthly observations)" for accuracy. Not changed here pending author verification.
- **engle1982 DOI**: JSTOR resolver (10.2307/1912773) is acceptable for most journals; flag at submission if target journal requires publisher-native DOI.
- **nelson2025 / xu2024**: SSRN preprint + forthcoming — standard; update pages/volume when published.
- **black1976**: No DOI (conference proceedings) — standard.

### Citation-specific fixes applied by review agent

- **campbell2017 DOI corrected**: `...00000044` → `...00000043` (correct FTAP article DOI verified)
- 57 bibitems / 57 cited keys — perfect bidirectional match, zero missing or orphan entries

---

## Action Plan for v8 (if another round needed)

**Must fix before submission (P2):**
1. body.tex ~line 495: Add footnote disambiguating γ (GJR leverage vs CRRA risk aversion)
2. Abstract: Change "2017–2025" → "2017–2026"

**Should fix (P3):**
3. body.tex line 76: Change Glosten 1993 data description from "daily observations" to "monthly observations" (after author verification)

**Prediction:** After P2 fixes → 4.5★ READY for submission

---

## Post-v7-round Status

Compilation: **CLEAN** (XeLaTeX 2 passes, no errors; only benign xeCJK font warning)
- Body.tex line 249: Trinity pass rates now consistent with tab:var_panel
- tables.tex line 147: sec:var_compliance \ref{} now correct
- campbell2017 DOI: corrected by citation agent

Remaining blockers for submission:
- γ symbol overload disambiguation (M-2)
- Abstract date update to 2026 (M-3)
- Optional: Glosten 1993 data frequency clarification

---

## Files in This Round

- `academic_review_report.md` — full LaTeX/logic/argument review (3.5★ → post-fix targeting 4.5★)
- `citation_check_report.md` — full citation verification (PASS_WITH_NOTES; campbell2017 DOI fixed)
- `README.md` — this file

## Next Round Trigger

After main thread completes v8 P2 fixes (γ disambiguation + abstract date) → new review round → `review_history/v8/`
