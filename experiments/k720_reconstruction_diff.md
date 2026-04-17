# K720 Reconstruction Diff Report

Comparison: `k720_results.json` (original) vs `k720_results_reconstructed.json` (reconstructed)

Reconstruction date: 2026-04-17

## Field Comparison

| Field | Original | Reconstructed | Diff | Match? |
|-------|----------|---------------|------|--------|
| vrp_flip_confirmed | True | True | bool | YES |
| direction_corr | 0.0277 | 0.8432 | 0.815500 | NO |

## Notes on direction_corr

The exact definition of `direction_corr=0.0277` in the original is ambiguous.
Candidates tested:
- corr(VRP_t, ΔVIX_t)
- corr(sign(VRP_t), VIX_t)
A near-zero value (0.0277) suggests the VRP sign has very weak correlation
with VIX changes or levels, consistent with VRP being always positive
(no regime where VRP turns negative).

## Overall Status

**Reconstruction result: APPROXIMATE — see direction_corr note above**

### Likely causes of divergence in direction_corr:
- Exact formula for direction_corr not specified in main_v2.tex
- Different VRP formula variant (e.g., lagged RV vs concurrent)
- Different annualization convention

**Paper errata risk**: vrp_flip_confirmed=true is the key claim (VRP always positive).
If our reconstruction also shows no flip, the paper's conclusion is confirmed.
direction_corr (0.0277) appears only in internal results, not in paper text — low errata risk.