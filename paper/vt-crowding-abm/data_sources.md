# Paper 5: Data Sources

**Paper**: When Volatility Targeting Crowds — Quantifying the Tipping Point via ABM

---

## Data Type

This paper uses **purely synthetic agent-based simulation data**. No external market data is required.

All results are generated entirely from the ABM simulation engine in:
- `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py`
- `experiments/k864/k864_heterogeneous_abm.py`

---

## Simulation Parameters

| Parameter | Base Value | Range Tested (OAT) |
|-----------|-----------|-------------------|
| VT adoption level | 0–100% | 10%, 30%, 50%, 70%, 90% |
| Number of agents | 1,000 | 500, 2,000 |
| Liquidity (fixed) | 0.5 | 0.2, 0.5, 0.8 |
| Rebalancing threshold | σ-based | σ×0.5, σ×1.0, σ×1.5 |
| Trading horizon | Daily | — |

See K827v3 script for full parameter specification.

---

## Random Seed

All simulations use a fixed seed for reproducibility:
- K827, K827v2, K827v3: `seed=42`
- K864: `seed=42`

---

## No External Data Dependencies

This paper has no external data dependencies. A reviewer can fully reproduce all results from a clean Python environment with no data downloads.
