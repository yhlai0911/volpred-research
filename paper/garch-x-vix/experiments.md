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
| K1045 | A4f Residual Diagnostics Suite (Table 11) | **Table 11 source**: SPY OOS 2019-01-02 to 2026-04-10 (n=1,828), window=2000, refit/63d. Computes standardized residual kurtosis (GJR: 3.065 → A4f: 1.238, −60%), skewness (−0.856 → −0.594, −30.6%), JB stat (938.8 → 224.2, −76.1%), ν (GJR 5.28, A4f 8.00). Uses vix2=(vix/100)² and joint MLE with standard-t parameterization. **Verified K995b exact match** (rtol≤0.002). | `experiments/K1045/` |
| K1023 | Proposition Verification (Discussion Props 1–2 source) | **Discussion Propositions source**: SPY full sample 2005–2026 (n_analysis=4,849). Prop.1: Corr(τ_t, g_t)=0.493 (paper ~0.49), Cov(τ,g)/E[σ²]=12.7% confirming E[σ²]=E[τ]E[g]+Cov(τ,g). Prop.2: theta1_ratio_A4=0.781 (paper 0.78), confirms MLE endogenously corrects for VRP discount. Prop.3: σ²/VIX² tracks VRP with Spearman ρ=0.819 (A3f, full period). | `experiments/k1023/` |

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

## Sensitivity Analysis (Section 5.1 / Table 12)

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K1003 | A4f Sensitivity — Refit Frequency × Window × Sub-Period × VIX Variants | **Table 12 source**: 16 sensitivity settings, OOS 2019-01-01 (n_valid=1,823). Refit 21/63/126/252d: DM t=4.29/3.92/3.36/3.32. Window 1000–3000: DM t=3.18/3.49/3.92/5.13/4.94. Sub-period COVID/PostCOVID/Stable: DM t=1.59/2.49/4.52. VIX variant VIX/VIX9D/VIX3M/ratio: DM t=3.92/5.15/2.59/3.53. 13/16 (81.2%) Harvey-significant. QLIKE scale ≈1.498/1.408. **Verified rtol≤0.002 across all 8 key cells**. | `experiments/k1003/` |

## Robustness / Alternative Drivers (Section 5.3)

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K1001 | Conrad-Loch Macro GARCH-X vs VIX GARCH-X | **Section 5.3 source**: VIX dominates macroeconomic specifications. SPY OOS 2019-01-01, n=1,779. GJR-N vs A4f-VIX DM t=4.77 (Harvey PASS); all macro models (Macro_TermSpread/Unemployment/Combined, VIX_Macro) fail to beat GJR (best macro t=1.48). FRED sources: GS10, TB3MS, UNRATE. **Scope note**: tests 2 macro variables; paper narrative says "six" — K1001 covers the key conceptual result, broader macro comparison was planned but not fully run. | `experiments/k1001/` |

## R1 Robustness — Proxy Sensitivity (r1_prep/)

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K1066 | A4f_oc vs A4f_close — Full Rolling OOS Test (Dual-Target) | **R1 proxy robustness source**: A4f_oc vs GJR_oc on r²_oc DM t=+4.04 (Harvey PASS); A4f_oc vs GJR_close on r²_oc DM t=+7.05 (Harvey PASS, largest DM in analysis). H1 PASS, H2 FAIL (4.04<4.48 baseline), H3 PASS (5/5 sub-periods, binomial p=0.031). SPY OHLC + VIX, OOS 2019-01-01 (n=1828), window 2000d, refit 63d, seed 42. Shelf-ready LaTeX: `paper/garch-x-vix/r1_prep/robustness_oc_proxy.tex`. Addresses Limitations "future work" on proxy sensitivity at daily frequency. | `experiments/k1066/` |

## Summary Statistics / Diagnostics (Section 2 / Table 1)

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K998 | VRP / Granger / g-series OOS diagnostics | **Table 1 summary-stat source**: OOS VRP autocorr(1) = 0.2034 (paper cites 0.20), mean 79.28 bps (ann.), std 1362.28 bps, skewness −13.58, kurtosis 241.40. OOS daily return mean 14.9 % / std 19.6 % (ann.). Data: SPY + ^VIX via yfinance, OOS start 2019-01-01. Diagnostics block added to `results[diagnostics]` on 2026-04-18 (previously only printed, un-sourced). Script mirrored to `paper/garch-x-vix/scripts/k998.py`; JSON in `paper/garch-x-vix/results/k998_results.json`. | `experiments/k998/` |

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
