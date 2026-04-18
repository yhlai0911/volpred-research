# Paper 4 (Paper 7): Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation

**Target Journal**: Journal of Forecasting
**Status**: Near submission-ready (R2 SEVERE=0) | active integration of 9 new experiments (2026-04-17)
**Pages**: 39 | **Citations**: 40

---

## Summary

Systematic horse race among 11 pre-specified signal families evaluating whether any observable signal can improve upon VIX for equity volatility forecasting and volatility-timing. Main finding: strongly negative — not a single signal family produces statistically significant OOS improvement (Harvey |t|>3.0, Holm-Bonferroni corrected). VIX–RV R² is time-invariant across 5 eras (CV=0.33). VT functions as drawdown insurance (CRRA γ≥4.5 welfare-improving).

**2026-04-17 expansion**: 9 new experiments complete the robust-models compendium (K1135/K1137/K1138/K1139/K1143) and alt-data boundaries (K1116/K1117/K1118/K1121/K1123). Key new finding: HAR-RV-X PASSES equity (SPY t=4.19, QQQ t=4.22) but not commodity — asset-class heterogeneity now documented.

---

## Data Sources

See `data_sources.md` for full details.

- SPY, VIX, VIX3M, VIX9D, VVIX: Yahoo Finance (yfinance)
- Cross-asset signals: GLD, TLT, USO, UUP, HYG, LQD, QQQ, IWM, BTC-USD (yfinance)
- Alt-data: EPU, NFCI, STLFSI4 (FRED); Google Trends fear (pytrends)
- OOS: 2008-01-01 – 2026-04-17 (8,325 trading days); era analysis: 1993–2026

---

## Supporting Experiments

Full index: `experiments.md`. Key K-numbers:

**Core 11 families**: K730, K731, K732, K734, K736, K738, K742, K745, K746b, K747, K748, K749, K750, K751, K752, K778, K780, K799, K821, K824v2, K828

**Alt-data compendium**: K504, K1116, K1116b, K1117, K1118, K1121, K1123

**Robust models compendium**: K1129, K1130, K1131, K1134, K1135, K1136, K1137, K1138, K1139, K1143

**Cross-asset**: K1098 (Taiwan VIXTWN)

---

## Reproduction

```bash
uv run python paper/vix-sufficiency/reproduce.py
```

See `scripts/README.md` for full sequence including new 2026-04-17 experiments.

---

## Key Results

- 11 signal families: 0/11 pass Harvey |t|>3.0 in full sample
- Era stability: VIX–RV R² CV=0.33 across 5 eras (1993–2026)
- VT drag: 3.49%/yr average for 12/VIX; welfare-improving for CRRA γ≥4.5
- Model rankings criterion-dependent: GJR dominates QLIKE (MCS sole member); AMEM dominates VaR/ES (score 1.94 vs 1.63)
- Alt-data: EPU/NFCI/STLFSI null confirmed cross-asset (SPY/GLD/TLT)
- Robust models: HAR-RV-X PASSES equity (t=4.19/4.22) but not commodity — new heterogeneity finding
- GAS-t: actively harmful on equity (SPY DM t=-3.27, mechanism = low-ν overtightening)

---

## Files

```
paper/vix-sufficiency/
  main_v2.tex         — Current paper body v2 (DO NOT edit via agent)
  main.tex            — Original v1 body (DO NOT edit via agent)
  reproduce.py        — Core reproduction pipeline
  reproduce_report.json — Last reproduction run results
  citation_check.md   — Citation verification
  integration_plan_v2.md — 2026-04-13 integration plan for 6 new experiments
  experiments/        — Core 22 experiment scripts (K730–K828)
  data_sources.md     — Data provenance index (NEW 2026-04-17)
  experiments.md      — Full K-number experiment index (NEW 2026-04-17)
  scripts/README.md   — Reproduction guide (NEW 2026-04-17)
  results/README.md   — Table/figure → source mapping (NEW 2026-04-17)
  figures/            — Soft-linked figures from experiments/kXXX/ (NEW 2026-04-17)
  reviews/            — Review correspondence
```
