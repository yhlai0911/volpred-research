# Paper 9: Supporting Experiments Index

**Paper**: Multiplicative GARCH-X with VIX: A Parsimonious Alternative to GARCH-MIDAS for Volatility Forecasting and Risk Management
**Journal**: Journal of Empirical Finance / International Journal of Forecasting (under review)
**Last Updated**: 2026-04-17

---

## Core Experiments

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K889 | MF-GJR Multiplicative Vol Factor | Original pilot: daily multiplicative GARCH-X with VIX; identified the estimation/OOS denominator inconsistency (τ_t in IS vs τ_{t-1} in OOS) that became the key methodological lesson (A1 spec) | `experiments/k889/` |
| K889b | MF-GJR Cross-OOS Validation | Cross-period robustness of the multiplicative structure | `experiments/k889b/` |
| K889v2 | MF-GJR Fixed (denominator-consistent) | Confirmed that fixing the denominator consistency improves performance | `experiments/k889v2/` |
| K988 | Multiplicative GARCH-X vs GARCH-MIDAS(VIX) Specification Comparison | **Main horse race**: 11 models (A1–A5, A2f/A4f/A3f/A2n/A4n, B0), reveals A4f-VIX² free-omega as champion; established the 17-spec taxonomy used in Table 3 | `experiments/k988/` |
| K988b | GARCH-MIDAS Supplement (6 additional) | Added B1/B2/B3/C1/C2/C3 MIDAS-RW and MIDAS-FS specs; confirmed all MIDAS lag-length variants fail to beat A4f | `experiments/k988/` (k988b files) |
| K989 | MF2-VIX + VIX² Convexity Synthesis | Tested VIX convexity (VIX⁴ poly) in tau; confirmed quadratic VIX² sufficient; tau vs OOS figure used in Figure 2 | `experiments/k989/` |

## MCS/DM Statistical Tests (paper/garch-x-vix/ root)

| File | Description | Contribution |
|------|-------------|-------------|
| `compute_mcs_dm.py` | Full 17-model MCS + pairwise DM matrix | Generates Table 4 (DM matrix), Table 5 (MCS set), all Harvey |t|>3.0 checkpoints |
| `mcs_dm_results.json` | Results from `compute_mcs_dm.py` | OOS period 2019–2026 (n=1,825); A4f rank 1 QLIKE=-8.360 |

## Cross-Asset Robustness Experiments (referenced in Section 5.1)

| K | Asset | Result | Path |
|---|-------|--------|------|
| K1077 | 0050.TW with US VIX | DM t=-0.49 NS — asset-IV mismatch | `experiments/k1077/` |
| K1083 | USD/TWD as 0050.TW vol driver | 83% variance explained by currency | `experiments/k1083/` |
| K1085 | GLD with GVZ (asset-matched IV) | DM t=+4.46 PASS | `experiments/k1085/` |
| K1088 | USO with OVX (asset-matched IV) | DM t=+4.48 PASS | `experiments/k1088/` |
| K1098 | 0050.TW with VIXTWN (asset-matched) | Full 15-year test of Taiwan-matched IV | `experiments/k1098/` |

## Orphan/Placeholder K References in main.tex

- **K889-original** (referred to as "A1 spec" in Table 2, line 207): this is the pilot run from `experiments/k889/` — labelled K889-original in the paper to distinguish from the corrected specs. The k889 README is currently a planning stub without full documentation. [TODO: verify k889 README completeness]
- **MIDAS-RW-K125** (Table 2, line 220): this is model B3 from K988b, not a separate K number — the "K125" refers to lag length parameter K=125 in the Beta polynomial, not an experiment ID.

---

## Figure Inventory

All figures are soft-linked in `paper/garch-x-vix/figures/`:

| Figure File | Source Experiment | Description |
|-------------|------------------|-------------|
| `k988_specification_comparison.png` | K988 | 11-model IS/OOS QLIKE bar chart |
| `k989_oos_comparison.png` | K989 | OOS forecast comparison: MF2 variants |
| `k989_tau_comparison.png` | K989 | Tau component visualization |
