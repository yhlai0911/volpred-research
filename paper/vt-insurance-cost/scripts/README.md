# Paper 4: Scripts / Reproduction Guide

---

## Primary Scripts (paper root)

| Script | Location | Purpose |
|--------|----------|---------|
| `reproduce.py` | `paper/vt-insurance-cost/` | Main reproduction pipeline |

## Experiment Scripts (paper/vt-insurance-cost/experiments/)

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `k811v2_main.py` | K811v2 | **Primary entry point** — full insurance cost decomposition |
| `k811v2_insurance_premium_vov_fixed.py` | K811v2 | Core VoV-based decomposition (generates Table 2) |
| `k811v2_threshold_0.5.py` | K811v2 | Sensitivity at σ×0.5 threshold |
| `k811v2_threshold_1.5.py` | K811v2 | Sensitivity at σ×1.5 threshold |
| `sensitivity_sweep.py` | K811v2 | Full sensitivity parameter sweep (all thresholds) |
| `k846_rebalancing_premium.py` | K846 | Isolated rebalancing premium (cross-asset SPY/GLD) |
| `k860_prospect_theory_vt.py` | K860 | Prospect theory extension (supplementary) |
| `k811_insurance_premium_vov.py` | K811 | Original pilot (superseded by K811v2; kept for reference) |

## Full Reproduction Sequence

```bash
# Step 1: Main results (Tables 1 and 2)
uv run python paper/vt-insurance-cost/experiments/k811v2_main.py

# Step 2: Sensitivity analysis
uv run python paper/vt-insurance-cost/experiments/sensitivity_sweep.py

# Step 3: Rebalancing premium decomposition
uv run python paper/vt-insurance-cost/experiments/k846_rebalancing_premium.py
```

## Data

Pre-downloaded CSV files are in `paper/vt-insurance-cost/data/`:
- `spy_2012_2024.csv`
- `gld_2012_2024.csv`
- `vix_2012_2024.csv`
- `vvix_2012_2024.csv`

No internet connection required for reproduction (data already included).

## Dependencies

```
numpy >= 1.26
pandas >= 2.1
matplotlib >= 3.8
scipy >= 1.12
```

Install: `uv pip install numpy pandas matplotlib scipy`
