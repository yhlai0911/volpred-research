# Paper 4: Supporting Experiments Index

**Paper**: The True Cost of Volatility Targeting — Insurance Premium Decomposition
**Journal**: Finance Research Letters (FRL)
**Status**: Audit 2026-06-10 downgraded to `MAJOR_REVISION` pending two omitted cross-OOS re-runs and reproduce-gate cleanup for claim #9.
**Last Updated**: 2026-04-17

---

## Core Experiments

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K811 | Insurance Premium VoV (original) | Original VT cost decomposition using VoV; pilot estimation | `paper/vt-insurance-cost/experiments/` |
| K811v2 | Insurance Premium VoV (fixed) | Corrected estimation with threshold sensitivity; main Table 2 | `experiments/k811v2/` + `paper/vt-insurance-cost/experiments/` |
| K846 | Rebalancing Premium | Isolated rebalancing premium component; cross-asset (SPY/GLD) | `experiments/k846/` |
| K860 | Prospect Theory VT | Prospect theory framing of insurance cost; supplementary analysis | `paper/vt-insurance-cost/experiments/` |

---

## Experiment Scripts (paper/vt-insurance-cost/experiments/)

Scripts co-located in paper folder:

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `k811_insurance_premium_vov.py` | K811 | Original VoV decomposition (superseded by K811v2) |
| `k811v2_insurance_premium_vov_fixed.py` | K811v2 | Fixed estimation — Table 2 main results |
| `k811v2_main.py` | K811v2 | Main entry point for full reproduction |
| `k811v2_sensitivity_th0_5.py` | K811v2 | Threshold sensitivity at z=0.5 (generates `k811v2_th0_5_results.json`) |
| `k811v2_sensitivity_th1_0.py` | K811v2 | Threshold sensitivity at z=1.0 (generates `k811v2_th1_0_results.json`) |
| `k811v2_sensitivity_th1_5.py` | K811v2 | Threshold sensitivity at z=1.5 (generates `k811v2_th1_5_results.json`) |
| `k811v2_share_bootstrap_ci.py` | K811v2 | Stationary-bootstrap 95% CI for the opportunity-cost share (seed 42, 10,000 reps; generates `k811v2_share_bootstrap_ci_results.json`) — abstract, §3.1, §4.2, Conclusion |
| `k811v2_fig1_wealth_regimes.py` | K811v2 | Figure 1 — cumulative wealth S0/S1/S2/S4 + VoV-regime shading (generates `figures/fig1_wealth_regimes.{pdf,png}`; asserts each curve's CAGR against Table 1 before writing) |
| `k846_rebalancing_premium.py` | K846 | Rebalancing premium isolation |
| `k860_prospect_theory_vt.py` | K860 | Prospect theory extension — unused in final draft |

---

## Table → Experiment Mapping

| Table | Caption | Source Experiment |
|-------|---------|------------------|
| Table 1 | Strategy Performance: Full Sample (2012–2024) | K811v2 (`k811v2_th0_5_results.json` + `k811v2_th1_0_results.json`) |
| Table 2 | Insurance Premium Decomposition (%/year) | K811v2 (`k811v2_insurance_premium_vov_fixed_results.json`) |

---

## Figure → Experiment Mapping

No `\includegraphics` commands found in main.tex — all results are tabular.
[TODO: confirm with author whether figures are planned]

---

## Number Traceability

Per `reviews/audit_step1_2.md`: all numbers verified — 0 mismatches.
Detailed traceability table available in audit file.

---

## Threshold Sensitivity Results

| Threshold | File |
|-----------|------|
| z=0.5 | `k811v2_th0_5_results.json` |
| z=1.0 | `k811v2_th1_0_results.json` |
| z=1.5 | `k811v2_th1_5_results.json` |

(2026-07-11 package hygiene: stale `k811v2_sensitivity_sweep.json` and mislabelled `k811v2_threshold_0.5_results.json` removed; superseded `k811v2_threshold_*.py` / `sensitivity_sweep.py` removed — the three `k811v2_sensitivity_th*.py` scripts above are the canonical generators.)
