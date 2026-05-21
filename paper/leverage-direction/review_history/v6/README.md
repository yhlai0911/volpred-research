# Review Round v6 — leverage-direction

**Date:** 2026-05-22
**Triggered by:** post-v5-all-fixes-verify (v5 achieved 4.0★ with minor issues; this round verifies all v5 fixes applied and checks for further issues)
**Reviewers:**
- latex-academic-reviewer (agent ac13274460e2f4a07)
- citation-verifier (agent a36e2722ca8e151b0)

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Academic | 8+ residual hardcoded refs (H-1 blocking); M-2 hood2025 "early access"; M-3 missing engle1982 | 4.2★ NEAR_READY |
| Citation | 0 MAJOR, 2 MED (cederburg2020 framing, hood2025 subtitle), 4 MINOR | ⚠️ 2 MED |

**Combined status: NOT READY for submission** — H-1 hardcoded refs are a blocking LaTeX issue; two MED citation issues require fixes.

---

## Issues Summary

### HIGH severity (1 item) — blocking submission

1. **H-1: Residual hardcoded Section/Table numbers** — 13 hardcoded Section refs + 3 hardcoded Table refs throughout body.tex. Need 6 new `\label{}` additions + corresponding `\ref{}` replacements. Specifically:
   - Lines 126, 156, 158(×2), 167, 242, 263, 283(×2), 369, 441, 568, 593 (Section refs)
   - Lines 225, 231(×2), 283 (Table refs)
   - 6 new labels needed: `sec:data`, `sec:vt_methodology`, `sec:leverage_direction`, `sec:garch_comparison`, `sec:var_compliance`, `sec:vt_results`

### MEDIUM severity (3 items)

2. **M-2: `hood2025` missing subtitle + "early access"** — Full title: "Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies". Update main.tex line 181 with full title + final Vol/issue/page if available.
3. **M-3: Missing `\citep{engle1982}`** — body.tex line 66 mentions "Engle's LM test" without citation. Add `\citep{engle1982}` in-text + new bibitem in main.tex (Econometrica 50(4) 987-1007, DOI 10.2307/1912773).
4. **Citation MED-1: `cederburg2020` framing** — Line 45 presents Cederburg et al. as endorsing VIX-scaling but their paper's headline finding is broadly negative on VT. Add framing of their negative headline conclusion.

### Minor

- `nelson2025` / `nelson1991` author disambiguation in bibitem labels
- `campbell2017` bibitem out of alphabetical order
- `black1976` title variant (no change needed)
- `pattonSheppard2015` issue number (no change needed; publisher is authoritative at issue 3)

---

## Action Plan for v7

**Must fix (P1 — blocking):**
1. Add 6 section labels to body.tex: `sec:data`, `sec:vt_methodology`, `sec:leverage_direction`, `sec:garch_comparison`, `sec:var_compliance`, `sec:vt_results`
2. Replace 13 hardcoded Section refs + 3 hardcoded Table refs → `\ref{}`

**Must fix (P2 — required for publication quality):**
3. `body.tex` line 66: Add `\citep{engle1982}` after "Engle's LM test"
4. `main.tex`: Add engle1982 bibitem (Econometrica 1982)
5. `main.tex` line 181: Update hood2025 with full subtitle + check final pagination

**Should fix (P3):**
6. `body.tex` line 45: Reframe cederburg2020 to include their negative headline finding

**Prediction:** After P1+P2 fixes → 4.5★ READY for submission

---

## V5 Fixes Verified

- ✅ H-2 (ρ=1.000 circularity defense): OOS ρ=0.821 quantification present at line 462
- ✅ M-1 (hardcoded refs from v5): Lines 11, 66, 154 fixed (3 refs)
- ✅ M-3 (MCS citation): `\citep{hansen2011}` at line 367 confirmed
- ✅ min-1 (`% H6 response:` comment removed)
- ⚠️ H-1 (residual refs): 13 Section + 3 Table refs remain unfixed

---

## Files in This Round

- `academic_review_report.md` — full LaTeX/logic/argument review (4.2★ NEAR_READY)
- `citation_check_report.md` — full citation verification (0 MAJOR / 2 MED / 4 MINOR)
- `README.md` — this file

## Next Round Trigger

After main thread completes v7 fixes (P1+P2+P3) + PDF recompile → new round → `review_history/v7/`
