# Academic Review Report — taiwan-vt v1

**Reviewer**: latex-academic-reviewer agent (feature-dev:code-reviewer subagent)
**Date**: 2026-05-23
**Document**: `paper/taiwan-vt/body.tex` (833 lines)
**Target journal**: Pacific-Basin Finance Journal (PBFJ)
**Review standard**: PBFJ-level strict
**Cross-references**: `review_r4.md`, `gate_fix_v1/gamma_unification_proposal.md`, K892/K896/K900/K1175/K1302/K1370

---

## Overall Assessment

**Verdict: Major Revision Required** (two HIGH issues block reproduce gate and submission)

Strong research content. The γ inconsistency (H1) and undisclosed data source (H2) are new findings not resolved in R1-R4. Six MEDIUM issues require attention before submission.

**Academic score: 3.5/5★** (would be 4.5★ after H1/H2 resolved)

---

## Issue Summary Table

| ID | Severity | Conf. | Lines | Description |
|---|---|---|---|---|
| H1 | HIGH | 98 | 52, 137, 148, 683 | Three different γ for 0050.TW; Table 2 (0.087/2.20) contradicts narrative (0.097/3.60) and K892 canonical |
| H2 | HIGH | 92 | 30-39, 156 | ELITE Material (2383.TW) in Table 2 but absent from Section 2.1 data description |
| M1 | MEDIUM | 92 | 659 | MDD figures (−77.3%/−48.6%) contradict K1175 canonical (−33.8%/−21.2%) |
| M2 | MEDIUM | 88 | 300, 380 | Day-count: 1,549 vs 1,524 vs K900 1,512 for same 2020-2026 period |
| M3 | MEDIUM | 88 | 593-594 | Christoffersen (1998) missing from VaR Trinity text (R4 M3-persist unresolved) |
| M4 | MEDIUM | 85 | 501-574 | Section 6 EAV covers US+Japan heavily — PBFJ Pacific-Basin scope risk |
| M5 | MEDIUM | 85 | 683 | Section 8.4 uses K900 rolling-252d γ without attribution |
| M6 | MEDIUM | 83 | 274, 593, 636 | 0.5% violation source comment points to GJR+CF, but text claims Student-t |
| mn1 | MINOR | 72 | 15 | "+0.124 Sharpe" conflates full-period and common-period table results |
| mn2 | MINOR | 70 | 181, 449 | Dual citation keys for Politis-Romano (1994) (also flagged by citation-verifier) |
| mn3 | MINOR | 68 | 166 | "9-stock average excl. 2330 & 0056" label is ambiguous |
| mn4 | MINOR | 65 | 60, 171 | Tables 1 and 2 state different specs for the same γ column |
| mn5 | MINOR | 62 | 655-656 | VIX Step Rule thresholds have no K-number source |

---

## HIGH Issues

### H1 — Three-way γ inconsistency for 0050.TW (Confidence: 98)

**Locations**: `body.tex` lines 52, 148, 683

Three distinct values for the same parameter appear in the same paper:

| Location | γ | t-stat | Spec |
|---|---|---|---|
| Line 52, Table 1 | **0.087** | **2.20** | Rolling w=2000 Newey-West HAC (Table 1 note) |
| Line 148, Table 2 | **0.087** | **2.20** | Claims BW-robust full-sample (Table 2 note line 171), but source file missing |
| Line 137, Section 3.1 | **0.097** | **3.60** | K892 canonical full-sample MLE |
| Line 683, Section 8.4 | **0.124** | **2.46** | K900 rolling-252d median (per gate_fix_v1) |

**Critical evidence**: `experiments/K892/k892_verify_tw_gamma_results.json` confirms γ=0.097 (n=4,219 full-sample). The source comment on line 148 (`paper/taiwan-vt/data/0050_canonical.json`) **does not exist**. Table 2 line 171 footnote claims "canonical full-sample BW-robust specification" was applied, but the actual cell value (0.087/2.20) is the old rolling-window estimate.

The `gate_fix_v1/gamma_unification_proposal.md` explicitly states: "No single K892 spec produces this pair [0.087, 2.20]. γ=0.087 comes from an old N120 run (deprecated); t=2.20 from the 2018–2026 w=2000 fit. Piecemeal table update — violates research-honesty §1."

**Fix**: Update Table 2 (line 148) to K892 canonical: γ=0.097, t-stat to be verified from K892 full spec. Update Table 1 (line 52) note or values to acknowledge rolling vs full-sample distinction. Standardize Section 8.4 (line 683) to K892 canonical or add explicit rolling-252d attribution.

---

### H2 — ELITE Material (2383.TW) undisclosed in data section (Confidence: 92)

**Locations**: `body.tex` line 156 (Table 2 row); lines 30-39 (Section 2.1)

Table 2 (line 156) includes "ELITE Material (2383)" with γ=0.009, t=1.15, sourced from `experiments/k1302/k1302_results.json (per_stock.2383.TW.TWA)`.

Section 2.1 data sources (lines 30-39) lists nine individual Taiwan stocks: 2330, 2317, 2454, 2882, 2886, 2891, 2412, 2885, 2881. Stock 2383.TW (ELITE Material, PCB/circuit materials manufacturer) is **absent** from this list. The paper uses results for an undisclosed data source.

Additional concern: line 166 says "9-stock individual average (excl. 2330 & 0056)" — if 2383 is one of the stocks from K1302 (10 stocks?), and 2330 is excluded, it may be included in the 9-stock average without being disclosed.

**Fix**: Option A (preferred): Add ELITE Material (2383.TW) to Section 2.1 bullet point with sample period and data source, clarify whether included in 9-stock average. Option B: Remove 2383 row from Table 2 and verify all averages use only the 9 listed stocks.

---

## MEDIUM Issues

### M1 — Insurance cost MDD figures contradict K1175 (Confidence: 92)

**Location**: `body.tex` line 659

Line 659 states MDD reduction from −77.3% to −48.6%. Table 3 (K1175 canonical) shows B&H MDD = −33.8%, EWMA VT MDD = −21.2%. The −77.3% figure comes from a pre-2009 vendor snapshot no longer available. No source comment on line 659.

**Fix**: Update line 659 to K1175 canonical values. Recompute CAGR cost from K1175.

### M2 — Day-count inconsistency (Confidence: 88)

**Location**: `body.tex` lines 300 (n=1,549), 380 (n=1,524); K900 canonical n=1,512

R4 commit eb9ef353 fixed one location; Table 4 note (line 300) still reads 1,549.

**Fix**: Verify canonical day count from K900/K1175. Update line 300 to match.

### M3 — Christoffersen (1998) missing (Confidence: 88) — R4 M3-persist carry-forward

**Location**: `body.tex` lines 593-594, 637 ("VaR Trinity pass")

The `\citet{kupiec1995}` appears at line 593 but Christoffersen (1998) is not cited anywhere in body.tex (confirmed: bibitem exists in main_v3.tex but no `\citet{christoffersen1998}` in body.tex). R4 commit 70438101 added the bibitem but not the inline citation.

**Fix**: Add `\citet{christoffersen1998}` next to Kupiec at Section 7.2 independence test mention.

### M4 — Section 6 EAV scope risk for PBFJ (Confidence: 85)

**Location**: `body.tex` lines 501-574, Section 6 title "Universal Cross-Market Regularity"

Equal weight given to 30 US S&P 500 stocks and 30 Japan TOPIX stocks alongside Taiwan. PBFJ is Pacific-Basin focused; US large-cap analysis may be flagged as outside scope.

**Fix**: Reframe US/Japan as benchmark comparisons for Taiwan's EAV magnitude; consider moving US/Japan detailed tables to appendix.

### M5 — Section 8.4 unattributed γ spec (Confidence: 85)

**Location**: `body.tex` line 683

γ=0.124 (t=2.46) for 0050.TW and γ=0.054 (t=1.07) for TSMC have no experiment attribution. `gate_fix_v1` identifies these as K900 rolling-252d median. After H1 resolution, update to canonical spec.

### M6 — VaR violation source comment mismatch (Confidence: 83)

**Location**: `body.tex` lines 274, 593, 636

Line 593 says "GJR+Student-t(5)" has 8 violations (0.5%), but line 274 source comment attributes 0.5% to `"GJR+Cornish-Fisher"`. Line 636 shows Cornish-Fisher has 9 violations (0.5%). The two different violation counts (8 vs 9) at the same rate suggest Student-t ≠ Cornish-Fisher here.

**Fix**: Verify K896 JSON for exact violation counts per distribution. Correct text and/or source comment.

---

## MINOR Issues

- **mn1**: Line 15, "+0.124 Sharpe" — specify 2020-2026 common period (Table 3 vs Table 4 distinction)
- **mn2**: Lines 181 and 449, dual Politis-Romano keys — same as citation MAJOR-1; fix citation key
- **mn3**: Line 166, "9-stock average excl. 2330 & 0056" — if both excluded, average is 7-stock or 8-stock; label is ambiguous given 2383 disclosure issue (H2)
- **mn4**: Tables 1/2 show same γ column under different stated methodologies (rolling vs full-sample BW-robust) without explicit cross-table explanation; readers comparing the two tables will be confused
- **mn5**: Lines 655-656, VIX Step Rule thresholds (15/25) not derived from paper's experiments; add "heuristic for illustration" caveat

---

## Strengths

1. Strong inline `% source:` attribution culture — most critical numbers traceable to JSON fields
2. Honest null-result treatment (QLIKE non-improvement DM p=0.86, preliminary rebalancing result)
3. Thorough VaR/ES framework (Acerbi-Székely Z2, Fissler-Ziegel scoring)
4. Self-challenge subsection (8.8) with Bonferroni correction — rare intellectual rigor in applied finance
5. Taiwan-specific calibration (K=8.63 derivation, conditional leverage, linearity robustness)

---

## Action Plan for v2

**Priority 1 — blocking (before reproduce gate):**
1. H1: Update Table 2 line 148 to K892 canonical γ=0.097 (verify t-stat from K892 or K1302+K1302b); update Table 1 spec note for consistency; standardize Section 8.4 (line 683)
2. H2: Add ELITE Material (2383.TW) to Section 2.1, OR remove from Table 2 with average recomputation

**Priority 2 — same editorial pass:**
3. M1: Update line 659 MDD figures to K1175 canonical
4. M2: Unify day-count to K900 canonical across lines 300 and 380
5. M3: Add `\citet{christoffersen1998}` in Section 7.2 (also needed per citation report)
6. M6: Verify and fix 8 vs 9 violations / Student-t vs Cornish-Fisher attribution

**Priority 3 — before submission:**
7. M4: Reframe Section 6 EAV scope framing for PBFJ audience
8. M5: Add K900 rolling-252d attribution to Section 8.4 γ values

**Reproduce gate prediction:**
After Priority 1-2 fixes, run `paper/taiwan-vt/reproduce.py`. Expected improvement from ~73% → ~85%. Reaching ≥95% requires additional experiments per gate_fix_v1 §5 (VIXTWN ratio, TSMC VT, 0056 robustness, canonical γ sweep).

**If all HIGH+MEDIUM resolved → predicted score: 4.5★/5, Minor Revision for PBFJ.**
