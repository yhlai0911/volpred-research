# Paper 8: Supporting Experiments Index

**Paper**: The Volatility Absorption Hypothesis
**Journal**: JBF (primary; P0-1 gate closed 2026-07-14 — absorption survives ambient-fear-shock gate)
**Status**: MAJOR REVISION — active manuscript narrowed to reproducible evidence set; K897 retired, identification rests on K1686 ambient×sign decomposition
**Last Updated**: 2026-07-14

---

## Core Experiments

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K716 | Absorption regression (SPY, pilot) | Original shock amplification ratio estimation; VIX regime binning | `experiments/k716/` |
| K718 | Cross-asset absorption | Cross-asset absorption coefficients (Table 4) | `experiments/k718/` |
| K719 | NFP event study | Nonfarm Payroll day volatility by VIX regime (Table 5) | `experiments/k719/` |
| K720 | Absorption by shock type | Legacy shock-type artifact; not active manuscript evidence | `experiments/k720/` |
| K721 | Variance Risk Premium by regime | Legacy VRP artifact; not active manuscript evidence | `experiments/k721/` |
| K722 | Hedging cost-benefit ratio | Legacy hedging artifact; not active manuscript evidence | `experiments/k722/` |
| K741 | NFP event study (revision) | Revised NFP analysis addressing reviewer S4 | `experiments/` (paper folder) |
| K897 | SAR null simulation | **RETIRED (2026-07-14, by K1686)**: lagged-proxy timing flaw — its `NULL REJECTED` flips under the contemporaneous proxy on pointwise-identical paths; no longer cited as evidence | `experiments/k897/` |
| K903 | Paper 8 robustness | Alternative shock thresholds robustness (Table 9) | `experiments/k903/` |
| K904 | Shock + NFP fix | Combined shock definition and NFP correction; addresses S2/S4 | `experiments/k904/` |
| **K1686** | Contemporaneous null + ambient×sign | **Core identification (§null_reexam)**: retires K897; null panel inconclusive (calibration failure); 58% threshold artifact; H ambient-up decline +1.0465 CI [0.33,1.76] — absorption survives fear-shock gate (Codex R2 PASS) | `experiments/k1686/` |
| — | Table 3 inference rebuild (P0-3) | Paired circular moving-block bootstrap CIs/p for ΔSAR on pinned snapshot; replaces unverifiable K716 p-values | `scripts/rebuild_table3_sar_inference.py` → `results/table3_sar_inference.json` |

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
| Table 2 | VIX Regime Distribution and Shock Frequency | `results/table3_sar_inference.json` (pinned; was K716) |
| Table 3 | Shock Amplification Ratio by VIX Regime (SPY, Five-Bin) | `results/table3_sar_inference.json` (pinned rebuild; was K716) |
| Table 4 | Cross-Asset Absorption Coefficients | K718 |
| Table 5 | Nonfarm Payroll Day Volatility by VIX Regime | K719/K741 |
| Table 6 | Shock-type extension | Deferred from active evidence |
| Table 7 | Variance Risk Premium by VIX Regime | Deferred from active evidence |
| Table 8 | Hedging Cost-Benefit Ratio by VIX Regime | Deferred from active evidence |
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

- **S1**: Null simulation → ~~K897 proves absorption is real~~ **superseded 2026-07-14**: K897 retired by K1686 (timing-dependent rejection); identification now = K1686 ambient×sign paired-block gate ✅
- **S2**: Table 5 sample-size inconsistency → K741 fix adopted in active body ✅
- **S3**: Old v2 gate / snapshot mixing → active body now tied to K903 + K1418 + K1686 + K741 + `results/table3_sar_inference.json`
- **Deferred**: shock-type / VRP / hedging sections await pinned-snapshot rebuild before they can re-enter the manuscript
- **Missing .py scripts for K716–K722**: original estimation scripts not in repo [K-ref found in experiments/ JSON but source scripts missing — see `experiments/k716/k716_results.json` etc.]
