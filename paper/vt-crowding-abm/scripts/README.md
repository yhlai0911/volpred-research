# Paper 5: Scripts / Reproduction Guide

---

## Primary Scripts (paper root)

| Script | Location | Purpose |
|--------|----------|---------|
| `reproduce.py` | `paper/vt-crowding-abm/` | Main reproduction pipeline: re-runs all ABM simulations |

## Experiment Scripts (paper/vt-crowding-abm/experiments/)

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `k827_abm_vt_crowding.py` | K827 | Base ABM simulation: VT adoption 0–100%, market outcomes |
| `k827v2_abm_sensitivity.py` | K827v2 | OAT parameter sensitivity sweep (9 variations) |
| `k827v3_abm_fixed_liquidity.py` | K827v3 | Fixed liquidity ABM — main Table 1 results; generates tipping point analysis |
| `k864_heterogeneous_abm.py` | K864 | Heterogeneous agent extension — Table 2 microstructure effects |

## Full Reproduction Sequence

```bash
# Step 1: Base simulation
uv run python paper/vt-crowding-abm/experiments/k827_abm_vt_crowding.py

# Step 2: Fixed liquidity (main result)
uv run python paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py

# Step 3: Sensitivity analysis
uv run python paper/vt-crowding-abm/experiments/k827v2_abm_sensitivity.py

# Step 4: Heterogeneous agents (Table 2)
uv run python paper/vt-crowding-abm/experiments/k864_heterogeneous_abm.py
```

## Notes

- All simulation is purely agent-based; no external market data required.
- Results are deterministic with fixed seed (see individual scripts for seed values).
- K827v3 is the canonical version for Table 1 (corrected liquidity mechanism).

## Dependencies

```
numpy >= 1.26
pandas >= 2.1
matplotlib >= 3.8
scipy >= 1.12
```

Install: `uv pip install numpy pandas matplotlib scipy`
