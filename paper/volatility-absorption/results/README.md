# Paper 8: Results Index

**Paper**: The Volatility Absorption Hypothesis
**Results Last Updated**: 2026-04-17

---

## Tables → Source Mapping

| Table | Description | Source File / Experiment |
|-------|-------------|--------------------------|
| Table 1 | Descriptive Statistics: Daily Returns and VIX (2006–2026) | `experiments/k716/k716_results.json` |
| Table 2 | VIX Regime Distribution and Shock Frequency | `experiments/k716/k716_results.json` |
| Table 3 | Shock Amplification Ratio by VIX Regime (SPY, Five-Bin) | `experiments/k716/k716_results.json` |
| Table 4 | Cross-Asset Absorption Coefficients | `experiments/k718/k718_results.json` |
| Table 5 | Nonfarm Payroll Day Volatility by VIX Regime | `experiments/k719/` + `paper/volatility-absorption/experiments/k741_nfp_event_study_results.json` |
| Table 6 | Absorption by Shock Type | `experiments/k720/k720_results.json` |
| Table 7 | Variance Risk Premium by VIX Regime | `experiments/k721/k721_results.json` |
| Table 8 | Hedging Cost-Benefit Ratio by VIX Regime | `experiments/k722/k722_results.json` |
| Table 9 | Absorption Coefficient Under Alternative Shock Thresholds | `paper/volatility-absorption/experiments/k897_sar_null_simulation_results.json` + K903 |
| Table 10 | Absorption Coefficient by Sub-Period | K903/K904 (see `experiments/k903/`, `experiments/k904/`) |
| Appendix A | Variable Definitions | Methodology section (no JSON) |
| Appendix B | Full Absorption Regression Results by Asset | `experiments/k718/k718_results.json` |

---

## Key JSON Results Files

| File | Location | Contents |
|------|----------|----------|
| `k716_results.json` | `experiments/k716/` + `paper/volatility-absorption/experiments/` | SPY absorption; VIX regime binning |
| `k718_results.json` | `experiments/k718/` + `paper/volatility-absorption/experiments/` | Cross-asset absorption coefficients |
| `k719_results.json` | `experiments/k719/` + `paper/volatility-absorption/experiments/` | NFP event study original |
| `k720_results.json` | `experiments/k720/` + `paper/volatility-absorption/experiments/` | Shock type asymmetry |
| `k721_results.json` | `experiments/k721/` + `paper/volatility-absorption/experiments/` | VRP by regime |
| `k722_results.json` | `experiments/k722/` + `paper/volatility-absorption/experiments/` | Hedging cost-benefit |
| `k741_nfp_event_study_results.json` | `paper/volatility-absorption/experiments/` | NFP revision results |
| `k897_sar_null_simulation_results.json` | `paper/volatility-absorption/experiments/` | SAR null simulation (GARCH artifact test) |

---

## Figures

No `\includegraphics` commands found in main_v2.tex — all results are tabular.
`figures/` directory created as placeholder for any figures added in revision.
[TODO: confirm with author whether figures are planned for revision]

---

## Known Data Traceability Issues

- S2: Table 5 sample-size inconsistency — needs K904 verification
- S3: Tables 9–10 fully untraceable — K903 partially addresses; original source scripts for K716–K722 are missing from repo (only JSON results preserved)
- Original `.py` scripts for K716, K718, K719, K720, K721, K722 are NOT in repo — results JSONs only

---

## Reproduction

```bash
# SAR null simulation (addresses S1)
uv run python paper/volatility-absorption/experiments/k897_sar_null_simulation.py

# NFP revision (addresses S4)
uv run python paper/volatility-absorption/experiments/k741_nfp_event_study.py

# Robustness (addresses S2/S3)
uv run python paper/volatility-absorption/experiments/k903_paper8_robustness.py
uv run python paper/volatility-absorption/experiments/k904_paper8_shock_nfp_fix.py
```

Data period: SPY/VIX 2006–2026 from yfinance; NFP dates manual.
