# Paper 5: Supporting Experiments Index

**Paper**: When Volatility Targeting Crowds — Quantifying the Tipping Point via ABM
**Journal**: Finance Research Letters (FRL)
**Status**: Submission-ready (R3 SEVERE=0)
**Last Updated**: 2026-04-17

---

## Core Experiments

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K827 | ABM VT Crowding (base) | Original agent-based simulation; VT adoption vs market stability trade-off | `experiments/k827/` |
| K827v2 | ABM Sensitivity Analysis | Parameter sensitivity sweep for OAT analysis | `experiments/k827v2/` |
| K827v3 | ABM Fixed Liquidity | Fixed liquidity ABM with 9 OAT parameter variations; main Table 3 | `experiments/k827v3/` |
| K864 | Heterogeneous ABM | Heterogeneous agent extension; Table 2 microstructure effects | `experiments/k864/` |

---

## Experiment Scripts (paper/vt-crowding-abm/experiments/)

Scripts co-located in paper folder:

| Script | Description |
|--------|-------------|
| `k827_abm_vt_crowding.py` | K827 base simulation |
| `k827v2_abm_sensitivity.py` | K827v2 sensitivity sweep |
| `k827v3_abm_fixed_liquidity.py` | K827v3 fixed liquidity; main results |
| `k864_heterogeneous_abm.py` | K864 heterogeneous agents |

---

## Table → Experiment Mapping

| Table | Caption | Source Experiment |
|-------|---------|------------------|
| Table 1 | VT Strategy and Market Outcomes by Adoption Level | K827v3 (`k827v3_abm_fixed_liquidity_results.json`) |
| Table 2 | Market Microstructure Effects of VT Crowding | K864 (`k864_results.json`) |
| Table 3 | Sensitivity of VT Tipping Point to Key Parameters (Fixed Liquidity) | K827v3 OAT parameter sweep |

---

## Figure → Experiment Mapping

No `\includegraphics` commands found in main.tex — all results are tabular.
[TODO: figures/directory created as placeholder; confirm with author]

---

## Key Results Summary

- **Tipping point**: 50–70% VT adoption
- **Safe zone**: 10–20% adoption (Sharpe ~0.50)
- **Collapse zone**: 50%+ adoption (Sharpe negative, flash crashes)
- **Mechanism**: When adoption > tipping point, synchronized rebalancing overwhelms market liquidity
