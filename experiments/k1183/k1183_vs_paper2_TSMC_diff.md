# K1183: Paper 2 TSMC Decomposition — Difference Report

**Paper Section**: body.tex Sec 8.6 (TSMC Concentration Robustness)  
**Experiment**: K1183  
**Date**: 2026-04-17  
**Status**: PARTIAL MATCH

---

## Paper Claims vs Computed Results

| Claim | Paper | Computed | Match? | Note |
|-------|-------|----------|--------|------|
| TSMC VT Sharpe | 1.121 | **1.1244** | YES (diff=0.003) | Full sample 2012-2026 |
| ex-TSMC min Sharpe | 0.193 | **0.191** (w=0.52) | YES (diff=0.002) | w_tsmc at current ~50% |
| ex-TSMC max Sharpe | 0.637 | **0.628** (w=0.32) | ~NEAR (diff=0.009) | w_tsmc at historical ~32% |
| TSMC var explain | 52.5% | **52.56%** | YES (diff=0.06%) | Full sample OLS R² |
| 0050.TW gamma (TSMC section) | 0.124 (t=2.46) | **0.132** (t=2.39) | ~NEAR | OOS-only GJR-GARCH |
| TSMC gamma | 0.054 (t=1.07) | **0.057** (t=2.86) | PARTIAL | Full sample estimation |

---

## Methodology Notes

### TSMC VT Sharpe = 1.121
- **Resolved**: Uses full sample 2012-01-01 to 2026-03-30 (not OOS-only)
- EWMA VT (λ=0.94, target 10%), signal.shift(1), tx cost 0.186% round-trip
- Computed: 1.1244 vs paper 1.121 — within 0.003, MATCH

### ex-TSMC Range 0.193–0.637
- **Resolved**: TSMC weight assumption drives the range
  - w=0.52 → Sharpe=0.191 (≈0.193 minimum, current TSMC weight)
  - w=0.32 → Sharpe=0.628 (≈0.637 maximum, historical lower TSMC weight)
- Paper's exact endpoints suggest slightly different weight definition:
  - 0.637 corresponds to w≈0.30-0.31 in my computation; paper may use w=0.29-0.30
  - 0.193 corresponds to w≈0.52 (close match)
- **Verdict**: Range interpretation confirmed correct. Exact endpoints within ±0.01 of adjacent grid points.

### TSMC Variance Explanation = 52.5%
- OLS R² of 0050.TW returns on TSMC returns (full sample)
- Computed: R² = 0.5256 (52.56%) vs paper 52.5% — MATCH

### Leverage Effect (gamma) Discrepancies
- Paper says 0050.TW gamma=0.124 in the TSMC sub-section (different from the main text value of 0.087)
- This likely reflects a sub-period estimation (OOS period only). Computed OOS gamma=0.132 vs 0.124 — close.
- TSMC gamma: paper says 0.054 (t=1.07, insignificant). Computed full-sample: 0.057 (t=2.86, significant).
  - The t-stat discrepancy suggests paper uses a shorter/different window for TSMC.
  - K892 had TSMC gamma=0.039 (different still), reinforcing period-sensitivity.

---

## Verdict

**Overall: PARTIAL MATCH (outcome b)**

- TSMC standalone VT Sharpe: **MATCHED** (1.1244 vs 1.121)
- TSMC variance R²: **MATCHED** (52.56% vs 52.5%)
- ex-TSMC range minimum: **MATCHED** (0.191 vs 0.193)
- ex-TSMC range maximum: **NEAR MATCH** (0.628 at w=0.32 vs paper 0.637)
- TSMC gamma: PARTIAL (direction correct, significance different)

The paper's claim is **broadly reproducible**. The ex-TSMC range 0.193–0.637 corresponds to TSMC weight assumptions spanning the historical range (32% to 52%), confirming VT benefits persist beyond TSMC concentration. Minor discrepancies stem from slightly different weight grid assumptions.

---

## Action Items

1. **No paper revision needed for main claim** — TSMC VT Sharpe 1.121 is reproducible
2. **Range 0.193–0.637** — confirm in paper text that weight range is 30%-52% for reproducibility
3. **TSMC gamma t-stat** — paper's 1.07 is insignificant; computed 2.86 (full sample) is significant. This claim needs verification with shorter window. Consider adding footnote.
4. **Document K1183 as source** for Sec 8.6 DIS-02, DIS-03, DIS-04 in reproducibility audit.

---

## Source Files
- `experiments/k1183/k1183.py` — reproduction code
- `experiments/k1183/k1183_results.json` — full numerical results
- `paper/taiwan-vt/body.tex` lines ~524-533 — paper claim location
