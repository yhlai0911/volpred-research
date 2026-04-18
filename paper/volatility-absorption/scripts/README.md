# Paper 8: Scripts / Reproduction Guide

---

## Primary Scripts (paper root)

| Script | Location | Purpose |
|--------|----------|---------|
| `reproduce.py` | `paper/volatility-absorption/` | Main reproduction pipeline |

## Experiment Scripts (paper/volatility-absorption/experiments/)

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `k741_nfp_event_study.py` | K741 | Revised NFP event study; addresses reviewer S4 (Table 5 discrepancies) |
| `k897_sar_null_simulation.py` | K897 | SAR null simulation — proves absorption is not a GARCH artifact; addresses reviewer S1 |
| `k903_paper8_robustness.py` | K903 | Alternative shock thresholds robustness; generates Table 9 candidates |
| `k904_paper8_shock_nfp_fix.py` | K904 | Combined shock definition + NFP fix; addresses S2 sample-size inconsistency |

## Missing Scripts (known gap)

The following experiments have only JSON results in the repo — original estimation scripts were not preserved:

| K | Missing Script | Status |
|---|---------------|--------|
| K716 | `k716_absorption_regression.py` | **MISSING** — only `k716_results.json` available |
| K718 | `k718_cross_asset.py` | **MISSING** — only `k718_results.json` available |
| K719 | `k719_nfp_event_study.py` | **MISSING** — only `k719_results.json` available |
| K720 | `k720_shock_type.py` | **MISSING** — only `k720_results.json` available |
| K721 | `k721_vrp_regime.py` | **MISSING** — only `k721_results.json` available |
| K722 | `k722_hedging_cost.py` | **MISSING** — only `k722_results.json` available |

[TODO: Reconstruct missing scripts before submission — required for replication package]

## Full Reproduction Sequence

```bash
# Step 1: Core results (using saved JSONs for K716–K722)
# These results are pre-computed; scripts are missing

# Step 2: Revision experiments (scripts available)
uv run python paper/volatility-absorption/experiments/k741_nfp_event_study.py
uv run python paper/volatility-absorption/experiments/k897_sar_null_simulation.py
uv run python paper/volatility-absorption/experiments/k903_paper8_robustness.py
uv run python paper/volatility-absorption/experiments/k904_paper8_shock_nfp_fix.py
```

## Dependencies

```
yfinance >= 0.2.40
scipy >= 1.12
statsmodels >= 0.14
numpy >= 1.26
pandas >= 2.1
matplotlib >= 3.8
```

Install: `uv pip install yfinance scipy statsmodels numpy pandas matplotlib`
