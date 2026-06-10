# Paper 4 (Paper 7): Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation

**Target Journal**: Journal of Forecasting
**Status**: `MAJOR_REVISION` after audit 2026-06-10. HIGH findings are applied in `main_v4.tex`, but the package is not submission-ready because the current reproduce gate still reflects a v3-era report and does not cover the full v4 body.
**Pages**: 39 | **Citations**: 40

## Summary

Systematic horse race among **13** signal families evaluating whether any observable signal can improve upon VIX for equity volatility forecasting and volatility-timing. Main finding remains strongly negative: no family delivers a beneficial out-of-sample improvement once signed DM direction, Holm-Bonferroni control, and the Harvey discipline are applied. VIX–RV R² is time-invariant across 5 eras (CV=0.33). VT functions as drawdown insurance (CRRA γ≥4.5 welfare-improving).

## Audit 2026-06-10: HIGH fixes now applied

- Table 3 errata landed: BH 50/50 Sharpe corrected from `0.947` to `0.827`, reversing the stale claim that static 50/50 beats every dynamic strategy.
- Title/body family count is now consistent at **thirteen**.
- §7.1 stale v3 prose about “all eight testable DM tests” and “minimum raw p = 0.147” was replaced with the correct 10-test harmful-direction discussion for families 12–13.
- Intro/Table 3 Sharpe-improvement inconsistency fixed: behavioral sentiment is the largest improvement at `+0.030`, still not significant.
- `luo2019` bibliography entry corrected to Huang, Tong, and Wang (2019).
- “pre-registered” overclaim removed; the paper now discloses that families 12–13 were added in revision under the same evaluation pipeline.

## Still open

- `reproduce_report.json` is still tagged `paper_version = v3`; it does not validate the v4-only tables and sections added in this revision.
- MEDIUM findings in `review_history/audit_2026-06-10/audit_findings.json` remain for the next pass.

## Data Sources

See `data_sources.md` for full details.

- SPY, VIX, VIX3M, VIX9D, VVIX: Yahoo Finance
- Cross-asset signals: GLD, TLT, USO, UUP, HYG, LQD, QQQ, IWM, BTC-USD
- Alt-data: EPU, NFCI, STLFSI4 (FRED); Google Trends fear
- OOS: 2008-01-01 to 2026-04-17; era analysis: 1993–2026

## Supporting Experiments

Full index: `experiments.md`.

- Core horse-race families: K730, K731, K732, K734, K736, K738, K742, K745, K746b, K747, K748, K749, K750, K751, K752, K778, K780, K799, K821, K824v2, K828
- Alt-data compendium: K504, K1116, K1116b, K1117, K1118, K1121, K1123
- Robust-model compendium: K1129, K1130, K1131, K1134, K1135, K1136, K1137, K1138, K1139, K1143

## Reproduction

```bash
uv run python paper/vix-sufficiency/reproduce.py
```

Current note: the bundled reproduce gate is historical and still reflects the v3 package. It should not be treated as a current-version green light for `main_v4.tex`.

## Key Results

- 13 signal families: 0 beneficial passes at the Harvey threshold in the full-sample horse race
- Era stability: VIX–RV R² CV=0.33 across 5 eras
- VT drag: 3.49%/yr average for 12/VIX; welfare-improving for CRRA γ≥4.5
- Model rankings criterion-dependent: GJR dominates QLIKE; AMEM dominates VaR/ES
- Alt-data families do not beat VIX; when they are significant, they are significant in the harmful direction
- HAR-RV-X passes equity but not commodity, documenting asset-class heterogeneity

## Files

```text
paper/vix-sufficiency/
  main_v4.tex            current audited paper body
  main.tex               legacy older wrapper/version
  reproduce.py           historical reproduction pipeline, needs v4 extension
  reproduce_report.json  historical v3-era reproduction output
  data_sources.md        provenance index
  experiments.md         full K-number experiment index
  review_history/        audit and fix logs
```
