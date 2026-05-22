# Paper 9 (garch-x-vix) — Review History v5

**Date**: 2026-05-22
**Round**: v5 — C5 narrative fix (A4f/Proposition 2 coherence)

---

## What Was Fixed

### C5 — Source Decomposition Coherence (RESOLVED)

**Status**: ✅ Applied — three edits to `main.tex`

**Problem**: Propositions 1–3 derive structural interpretation for the constrained model (E[g_t]=1), but the recommended model is A4f (free ω, E[g_t]=0.48). This created:
1. Proposition 2 stated "the MLE of θ_1 endogenously corrects for VRP" without clarifying this applies to the constrained model only.
2. Table 3 (VRP correlations) showed A3f, A2n, A4n but NOT A4f — omitting the recommended model.
3. Discussion point (ii) referenced "E[g_t]=1 constraint" as a feature, contradicting A4f's free-omega design.

**Changes made**:

1. **Proposition 2 scope clarification** (Section 5.5):
   - Added "Under the constrained model (E[g_t]=1, with ω_g = 1−α−γ/2−β)" as the explicit scope
   - Added note: "In the free-omega model (A4f), VRP correction is distributed across two channels—θ_1 scaling and E[g_t] level—so θ_1 alone no longer identifies the full VRP discount; see the empirical discussion below."

2. **Table 3 (tab:vrp_corr) — A4f row added**:
   - New row: A4f (VIX², free ω, *recommended*): ρ = −0.017, p = 0.479
   - Source: `paper/garch-x-vix/results/k998_results.json` → `contemporaneous.spearman_g_vrp`
   - Table note added explaining the near-zero correlation: free ω_g absorbs average VRP level (E[g_t]=0.48), leaving g_t approximately VRP-orthogonal

3. **Discussion summary (point ii) rewrite**:
   - Old: "(ii) the E[g_t]=1 constraint pins the scale, making τ_t the sole determinant of unconditional variance"
   - New: "(ii) the multiplicative structure provides structural scale separation—τ_t captures exogenous option-market fear while g_t captures endogenous GARCH dynamics, with this decomposition interpretable whether E[g_t]=1 (constrained) or E[g_t]=0.48 (A4f)"

**Evidence**: ρ = −0.017 from k998_results.json `contemporaneous.spearman_g_vrp` (A4f OOS 2019–2026, n=1824)

---

## C4 Status — HAR-RV Benchmark (IN PROGRESS)

**Status**: ⏳ Compute queued — K1396 (compute-k1396-har-rv-vs-a4f-paper-9-c4-har-benchmark-1779455820)

**Plan**: K1396 runs HAR, HAR-VIX vs A4f DM test (same OOS protocol).
- If A4f Harvey-sig > HAR: add HAR/HAR-VIX rows to Table 2 → C4 RESOLVED
- If A4f not Harvey-sig > HAR: add honest limitation paragraph → C4 ACKNOWLEDGED

---

## Remaining Open Issues from v4

| Issue | Status |
|-------|--------|
| C4: HAR-RV benchmark missing | ⏳ K1396 compute queued |
| C5: A4f free-ω vs Proposition 2 contradiction | ✅ RESOLVED (v5) |
| C6: Harvey (2016) citation context | OPEN |
| C7: VRP tautology quantification | OPEN |
| C8: Cross-asset multiple testing | OPEN |
| C9: Refit sensitivity COVID interaction | OPEN |
| C10: Contemporaneous terminology | OPEN |
| C11: A4f vs A4 fragility (block bootstrap) | OPEN |
| C12: GLD DM t inconsistency | OPEN |
| C13: Proposition 3 formal status | OPEN |
| C14: Table 3 A4f VRP correlation | ✅ RESOLVED (v5, ρ=−0.017 added) |
| C15: xeCJK compilation | OPEN |
| C16: Acerbi citation upgrade | OPEN |
| C17: Proposition 1 algebraic identity | OPEN |

---
