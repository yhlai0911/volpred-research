# Paper Taiwan-VT R4 Academic Review

**Reviewer:** Claude Sonnet 4.6 (feature-dev:code-reviewer subagent)
**Date:** 2026-05-12
**Document reviewed:** body_v3.tex / main_v3.tex
**Experiment sources cross-checked:** K892, K896, K900, K1175
**Review standard:** JBF-level strict

---

## R4 Summary Table

| Category | R1 | R2 | R3 | R4 |
|---|---|---|---|---|
| Severe | 6 | 2 | 0 | **0** |
| High (blocking) | — | — | 3 pending | **0 (after eb9ef353 fixes)** |
| Medium | 8 | 8 | 8 | **7** |
| Minor | 7 | 6 | 6 | **6** |

---

## R3 HIGH Items: Resolution Status

### M7 (K892 Gamma Integration) — RESOLVED ✅
- 0050.TW γ=0.097 (t=3.60), TSMC γ=0.052 (t=3.98) verified against K892 JSON
- Table 2, Section 3.1, Section 4.5, Abstract, Conclusion all updated
- Source attribution: "Source: K892" present

### M8 (K896/K900 ES Integration) — RESOLVED ✅  
- ES subsection in Section 7.4 present
- Acerbi-Szekely (2014) + Fissler-Ziegel (2016) citations present in body + bibliography
- Abstract mentions ES backtesting
- Sub-issue sub-M8a (MEDIUM-95): CF description incorrectly says "excess violation rates" — CF fails due to undercoverage (0.51%), not excess. Carried as MEDIUM.

### K900 Tables 4-5 Integration — RESOLVED ✅ (commit eb9ef353)
- Table 5 replaced with K900 canonical common-period values (n=1,512)
- Table 4 uses K1175 values (already correctly attributed)
- Narrative updated to reflect 2020-2026 bull market context honestly

---

## Issues Found During R4 (all addressed in eb9ef353)

### ~~N1 (HIGH-100): Conclusion stale legacy numbers~~ → FIXED
- Was: "EWMA VT improves Sharpe from 0.729 to 0.796 while halving MDD from -41.3% to -18.4%"
- Fixed: Updated to K1175 values (B&H 0.799 → EWMA 0.701, MDD -33.8% → -21.2%) with honest narrative

### ~~N2 (HIGH-98): Table 5 day count 1,549 conflicts with K900 (1,512)~~ → FIXED
- Fixed: Changed to n=1,512 per K900

### ~~N3 (HIGH-98): Table 5 values not from K900~~ → FIXED
- Fixed: Full replacement with K900/K1175 canonical values

---

## Remaining Medium Issues (non-blocking)

1. **sub-M8a (MEDIUM-95)**: CF in Section 7.4 described as "excess violation rates" — should say "undercoverage" (0.51% < 1%)
2. **N4 (MEDIUM-90)**: Section 7.2 "8 violations (0.5%)" claim untraceable; K896 shows 18/1,756 (1.025%)
3. **M3-persist (MEDIUM-90)**: Christoffersen (1998) bibitem missing for VaR trinity independence test
4. **SSVS PIP (MEDIUM-85)**: Table 3 shows 0050.TW "Lagged own return" PIP=0.312 vs K461 0.9994 — may be different variables
5. **M5 (MEDIUM-80)**: GJR+Normal violation count small discrepancy (paper: 2.0% vs K896: 1.71%)

---

## Overall Verdict

**Minor Revision.** All SEVERE and HIGH issues are resolved. Paper is approaching submission readiness.

**Remaining blocking item for submission**: Reproduce gate must pass (run `python reproduce.py` and confirm match_rate ≥ 95%).

**Recommended target journal**: IRFA (near-term); JBF (after addressing remaining mediums + scope clarification in M1).

---

## Issue Count After R4

| Severity | Count |
|---|---|
| SEVERE | 0 |
| HIGH | 0 |
| MEDIUM | 5 |
| MINOR | 6 |
