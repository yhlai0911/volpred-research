# Paper 8: Supporting Experiments Index

**Paper**: The Volatility Absorption Hypothesis
**Journal**: TBD
**Status**: R1 review — 5 SEVERE, needs major revision
**Last Updated**: 2026-04-17

---

## Core Experiments

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K716 | Absorption regression (SPY, pilot) | Original shock amplification ratio estimation; VIX regime binning | `experiments/k716/` |
| K718 | Cross-asset absorption | Cross-asset absorption coefficients (Table 4) | `experiments/k718/` |
| K719 | NFP event study | Nonfarm Payroll day volatility by VIX regime (Table 5) | `experiments/k719/` |
| K720 | Absorption by shock type | Positive vs negative shock asymmetry (Table 6) | `experiments/k720/` |
| K721 | Variance Risk Premium by regime | VRP narrowing at high VIX (Table 7) | `experiments/k721/` |
| K722 | Hedging cost-benefit ratio | Hedging cost analysis by VIX regime (Table 8) | `experiments/k722/` |
| K741 | NFP event study (revision) | Revised NFP analysis addressing reviewer S4 | `experiments/` (paper folder) |
| K897 | SAR null simulation | Proves absorption is real (not GARCH artifact); addresses reviewer S1 | `experiments/k897/` |
| K903 | Paper 8 robustness | Alternative shock thresholds robustness (Table 9) | `experiments/k903/` |
| K904 | Shock + NFP fix | Combined shock definition and NFP correction; addresses S2/S4 | `experiments/k904/` |

---

## Experiment Scripts (paper/volatility-absorption/experiments/)

Scripts co-located in paper folder:

| Script | Description |
|--------|-------------|
| `k741_nfp_event_study.py` | NFP event study (revision) |
| `k897_sar_null_simulation.py` | SAR null simulation (GARCH artifact test) |
| `k903_paper8_robustness.py` | Alternative threshold robustness |
| `k904_paper8_shock_nfp_fix.py` | Shock + NFP combined fix |

---

## Table → Experiment Mapping

| Table | Caption | Source Experiment |
|-------|---------|------------------|
| Table 1 | Descriptive Statistics: Daily Returns and VIX (2006–2026) | K716 |
| Table 2 | VIX Regime Distribution and Shock Frequency | K716 |
| Table 3 | Shock Amplification Ratio by VIX Regime (SPY, Five-Bin) | K716 |
| Table 4 | Cross-Asset Absorption Coefficients | K718 |
| Table 5 | Nonfarm Payroll Day Volatility by VIX Regime | K719/K741 |
| Table 6 | Absorption by Shock Type | K720 |
| Table 7 | Variance Risk Premium by VIX Regime | K721 |
| Table 8 | Hedging Cost-Benefit Ratio by VIX Regime | K722 |
| Table 9 | Absorption Coefficient Under Alternative Shock Thresholds | K903 |
| Table 10 | Absorption Coefficient by Sub-Period | K903/K904 |
| Appendix A | Variable Definitions | Methodology section |
| Appendix B | Full Absorption Regression Results by Asset | K718 |

---

## Figure → Experiment Mapping

No figures with `\includegraphics` found in main_v2.tex. All results are tabular.
[TODO: confirm with author whether figures are planned for revision]

---

## Known Issues (from README and reviews)

- **S1**: Null simulation → K897 proves absorption is real (not GARCH artifact) ✅
- **S2**: Table 5 sample-size inconsistency → K904 addresses this
- **S3**: Tables 9–10 fully untraceable → K903 partially addresses
- **S4**: Table 6 NFP discrepancies → K741/K904 address this
- **Missing .py scripts for K716–K722**: original estimation scripts not in repo [K-ref found in experiments/ JSON but source scripts missing — see `experiments/k716/k716_results.json` etc.]
