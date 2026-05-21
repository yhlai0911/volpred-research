# Academic Review Report — leverage-direction v5

**Date**: 2026-05-21
**Reviewer**: latex-academic-reviewer agent (JBF R1 standard)
**Paper version**: v3.3 → v5 fixes applied (body.tex + tables.tex)
**Review trigger**: v4 M-1 citation fix complete; first full academic review of v3.3+ state
**Prior rating**: 3.5/5★ CONDITIONAL (v4)

---

## Overall Assessment

**Academic Score: 4.0/5★**
**Submission Readiness: NEEDS_REVISION (minor)**
**Predicted Journal Response: Minor revision** (after Priority 1 + 2 fixes below)

v3.3 resolved v4's S-1 overclaim, M-2 date field, M-3 campbell2017 bibitem optional-arg, M-4 hardcoded §5.4.1, Mi-2 empty appendix. The systematic M-1 citation conversion substantially raised citation quality. v5 mechanical fixes resolved H-1 residual plain-text citations and M-2 K-codes in table notes. Remaining issues are the ρ=1.000 circularity defense (H-2, needs one sentence), hardcoded table/section numbers (M-1), and MCS citation verification (M-3).

---

## Strengths

1. **Null-results table (table_nulls.tex)** — 25+ failed alternatives across prediction accuracy, strategy improvement, and VIX sufficiency. JBF-quality methodological transparency; directly addresses "why not use a richer model?" objection.
2. **Contribution framing correctly scoped** — "all twelve tested assets" overclaim from v4 resolved; Conclusion correctly acknowledges small cross-section N=6 limits OOS statistical power.
3. **VaR backtesting framework is state-of-the-art** — Trinity criterion (Kupiec + Christoffersen + DQ) at three α levels, Basel III traffic-light, Fissler-Ziegel joint (VaR, ES) scoring.
4. **GLD regime-dependent footnote** (body.tex:167) — scientifically honest treatment of full-sample vs. rolling γ divergence; pre-empts common referee objection.
5. **Errata transparency** — substantive correction disclosures now maintained without internal K-codes (after v5 fix).

---

## HIGH Severity Issues (blocking submission)

### H-2: ρ=1.000 Circularity Defense Incomplete

**Location**: body.tex ~line 462 (Section 4.4 / ρ=1.000 discussion)

**Issue**: The paragraph explaining ρ=1.000 correctly notes Pearson r=0.993 < 1, ruling out algebraic identity. However, it does not invoke the temporally separated OOS evidence as direct proof of non-circularity. The OOS ρ=0.821 (body.tex ~line 471) is mentioned two paragraphs later but not connected to the circularity defense. A JBF referee who notes that VT weight w_t = σ_target/σ_hat_t and σ_hat_t is downstream of GJR asymmetry via γ will challenge mechanical correlation.

**Fix required**: Add one sentence to the ρ=1.000 paragraph:
> "Crucially, γ is estimated over the in-sample period (2010–2017) while β^trend is estimated over the separate OOS period (2018–2026); the ρ=1.000 therefore cannot be a mechanical artifact of shared estimation data (OOS ρ=0.821, Section 4.5)."

This directly closes the temporal-separation question with existing evidence.

---

## MEDIUM Issues (should fix before submission)

### M-1: Hardcoded Table and Section Reference Numbers

**Locations** (body.tex):
- Line ~165: `Table 2 reports cross-sectional statistics` → `Table~\ref{tab:gamma} reports`
- Line ~175: `Table 3` → `Table~\ref{tab:qlike}` (verify label)
- Line ~215: `Table 3` → same
- Line ~287: `Table 5` → `Table~\ref{tab:...}` (verify label)
- Line ~146: `Section 5.1` → `Section~\ref{sec:...}` (verify label)

Hardcoded numbers will silently break if table ordering changes. JBF typesetting may reorder; `\ref{}` is the standard.

---

### M-3: MCS Citation Year Possibly Incorrect

**Issue**: The Model Confidence Set (MCS) procedure is canonically associated with Hansen, Lunde, and Nason (2011, *Review of Economic Studies*), not Hansen (2005). Verify:
1. Find `\citet{hansen2005}` in body.tex
2. Confirm the bibitem at main.tex matches the correct paper
3. If MCS-related: replace `hansen2005` → `hansen2011` (add bibitem if needed)

Canonical reference: Hansen, P.R., Lunde, A., Nason, J.M. (2011). "The model confidence set." *Econometrica*, 79(2), 453–497.

---

## MINOR Issues

### min-1: Internal Review Comment Survives in body.tex

**Location**: body.tex ~line 68
```latex
\paragraph{Sample period justification.} % H6 response: short sample period
```
Comment `% H6 response:` is invisible in PDF but visible in .tex source (distributed in replication package). Remove the comment text.

### min-2: Engle (1982) ARCH Citation Missing

**Location**: body.tex ~line 66
```
ARCH effects (Engle's LM test p < 0.001)
```
Add `\citep{engle1982}` after "Engle's LM test". The foundational ARCH paper citation is unusual to omit in a GARCH paper. If `engle1982` is not in the bibliography, add it.

### min-3: VT Weight Scaling Convention Not Stated

**Location**: body.tex §3.5 (VT weight equation)
The formula w_t = σ_target/σ_hat_t does not clarify whether σ_hat_t is annualized (GJR-GARCH produces daily variance; requires ×√252). State explicitly: "where σ_hat_t denotes annualized conditional volatility (daily GJR-GARCH variance scaled by √252)."

### min-4: hood2025 Full Metadata (same as MIN-3 in citation report)

Update main.tex bibliography: remove "early access", update to Vol 52(1), p.100, and add full title.

---

## v4 Fix Verification

| v4 Issue | Claimed Fix | Verification |
|---|---|---|
| S-1: "all twelve assets" overclaim | Resolved | CONFIRMED — body.tex:13 + Conclusion correctly scoped |
| S-2: ρ=1.000 explanation | Partial | IMPROVED but H-2 remains open |
| M-1: Plain-text citations (27 entries) | Resolved | MOSTLY RESOLVED — 3 missed, now fixed in v5 |
| M-2: Date field | Resolved | CONFIRMED — "May 2026 (v3.3)" |
| M-3: campbell2017 bibitem format | Resolved | CONFIRMED — `\bibitem[Campbell et~al.(2017)]{campbell2017}` |
| M-4: Hardcoded §5.4.1 | Resolved | CONFIRMED — body.tex:502 reference gone |
| Mi-2: Empty appendix | Resolved | CONFIRMED — section removed |

---

## JBF Referee Simulation (Top 3)

**R-1 [High probability]**: "The Spearman ρ=1.000 result is suspicious. Please show this holds when γ and β^trend are estimated on non-overlapping periods." → H-2 fix + OOS ρ=0.821 cross-reference addresses this.

**R-2 [High probability]**: "N=6 OOS cross-section has very low statistical power. What is the minimum N for 80% power at ρ=0.80?" → Currently acknowledged ("limits statistical power") but power calculation not provided.

**R-3 [Medium probability]**: "The Errata in Tables 4 and 7 indicate corrections were made. Please clarify whether corrections were identified pre- or post-initial submission." → Handled by errata transparency, but K-codes removed in v5 make the notes cleaner.

---

## Gate Assessment for ready_for_submission

| Gate condition | Current Status |
|---|---|
| Academic ≥ 4★ | PASS — 4.0/5★ |
| Citation 0 MAJOR | CONDITIONAL — campbell2017 DOI needs manual verification |
| ≤ 1 MED remaining | FAIL — 2 MEDIUM remaining (M-1 hardcoded refs, M-3 MCS year) |

**Verdict**: NOT READY. Fix H-2 (one sentence, ~10 minutes), M-1 (table `\ref{}` replacements, ~20 minutes), M-3 (MCS citation verification, ~5 minutes), and campbell2017 DOI (manual URL check). After these 4 fixes → run v6 citation verification → upgrade to `ready_for_submission`.

---

## Priority Action Plan for v6

| Priority | Fix | Effort |
|---|---|---|
| P1 | body.tex ~462: Add OOS temporal-separation sentence to ρ=1.000 paragraph | 5 min |
| P1 | tables → `\ref{}`: Replace 4 hardcoded Table N + 1 Section N.N with `\ref{}` | 20 min |
| P1 | Verify MCS citation: `hansen2005` vs `hansen2011` in body.tex + bibliography | 5 min |
| P1 | Verify campbell2017 DOI at doi.org: `104.00000043` vs `104.00000044` | 2 min |
| P2 | Update hood2025 bibitem: Vol 52(1), p.100, full title | 5 min |
| P3 | body.tex:68: Remove `% H6 response:` comment | 1 min |
| P3 | body.tex:66: Add `\citep{engle1982}` for ARCH LM test | 5 min |
| P3 | body.tex §3.5: Clarify σ_hat_t annualization convention | 5 min |

*After P1 fixes: recompile + v6 citation check → expected upgrade to ready_for_submission.*
