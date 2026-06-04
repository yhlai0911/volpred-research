# Paper 9: Scripts / Reproduction Guide

---

## Primary Scripts (paper root)

| Script | Location | Purpose | Runtime |
|--------|----------|---------|---------|
| `compute_mcs_dm.py` | `paper/garch-x-vix/` | Full 17-model MCS (Hansen-Lunde-Nason 2011) + pairwise DM matrix + Giacomini-White tests | ~28 min |
| `k998.py` | `paper/garch-x-vix/scripts/` | K998 VRP / Granger / g-series OOS (sourced Table 1 VRP autocorr = 0.20, mean/std/skew/kurt). Output → `paper/garch-x-vix/results/k998_results.json` `diagnostics` block | ~90 s |

## Experiment Scripts (experiments/kXXX/)

All core model estimation and evaluation scripts live in the respective experiment directories:

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `experiments/k988/k988.py` | K988 | 11 multiplicative GARCH-X models (A1–A5, free-omega variants) horse race |
| `experiments/k988/k988b_supplement.py` | K988 | 6 GARCH-MIDAS alternatives (B1–B3, C1–C3) |
| `experiments/k989/k989_mf2_vix2.py` | K989 | VIX² convexity synthesis + tau component visualization |
| `experiments/k1003/k1003.py` | K1003 | Table 12 sensitivity analysis (refit/window/sub-period/VIX variants) |
| `experiments/k1027/k1027.py` | K1027 | Seven 2-year non-overlapping sub-period robustness |
| `experiments/k1085/` (see README) | K1085 | GLD+GVZ cross-asset robustness |
| `experiments/k1088/` (see README) | K1088 | USO+OVX cross-asset robustness |
| `experiments/k1098/k1098_*.py` | K1098 | 0050.TW + VIXTWN 15-year Taiwan test |
| `experiments/k998/k998.py` | K998 | VRP / Granger / OOS diagnostics (Table 1 summary stats source; **mirrored to `paper/garch-x-vix/scripts/k998.py` for self-contained replication**) |

## Full Reproduction Sequence

```bash
# Step 1: Core model comparison (K988 + K988b)
uv run python experiments/k988/k988.py
uv run python experiments/k988/k988b_supplement.py

# Step 2: Convexity synthesis (K989)
uv run python experiments/k989/k989_mf2_vix2.py

# Step 3: Sensitivity / robustness sources (K1003, K1027)
uv run python experiments/k1003/k1003.py
uv run python experiments/k1027/k1027.py

# Step 4: MCS + DM tests (uses K988 + K988b results)
uv run python paper/garch-x-vix/compute_mcs_dm.py

# Step 5: Cross-asset (K1085, K1088, K1098)
# See individual experiment README files for entry points
```

## Dependencies

```
yfinance >= 0.2.40
arch >= 6.3.0
scipy >= 1.12
statsmodels >= 0.14
numpy >= 1.26
pandas >= 2.1
matplotlib >= 3.8
```

Install: `uv pip install yfinance arch scipy statsmodels numpy pandas matplotlib`
