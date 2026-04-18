# Paper 4 Results Index

**Paper**: Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation
**Journal**: Journal of Forecasting
**Results Last Updated**: 2026-04-17

---

## Tables → Source Mapping

| Table | Description | Source File / Experiment |
|-------|-------------|--------------------------|
| Table 1 | Eleven signal families overview | `main_v2.tex` methodology; K730–K751 |
| Table 2 | OOS forecasting results (DM t-stats, Holm-Bonferroni) | `experiments/k799/k799_grand_evaluation_results.json` → `dm_results` |
| Table 3 | Model Confidence Set (QLIKE) | `experiments/k799/k799_grand_evaluation_results.json` → `mcs_results` |
| Table 4 | VaR/ES backtest scorecard | `experiments/k824v2/k824v2_quantile_fixed_results.json` |
| Table 5 | Era-stratified OOS R² (5 eras 1993–2026, CV=0.33) | `experiments/k752/k752_vix_sufficiency_eras_results.json` |
| Table 6 | Cross-asset alt-data DM matrix (SPY/GLD/TLT) | `experiments/k1118/k1118_results.json` |
| Table 7 | VT strategy performance (12/VIX variants, TX cost) | `experiments/k738/k738_vt_insurance_cost_benefit_results.json` |
| Table 8 | Robust model compendium (commodity) | `experiments/k1136/k1136_results.json` |
| Table 9 | Equity compendium (HAR-RV-X/GAS-t/MIDAS) | `experiments/k1138/k1138_results.json` |
| Table 10 | Regime-conditional DM (K1137) | `experiments/k1137/regime_conditional_heatmap.png` + results JSON |

---

## Figures → Source Mapping

| Figure | Description | Source |
|--------|-------------|--------|
| Fig. 1 | DM t-statistics for 11 signal families | `figures/k1116_dm_tstats.png` → K1116 |
| Fig. 2 | BH significance threshold plot | `figures/k1116_bh_significance.png` → K1116 |
| Fig. 3 | GAS-t DM heatmap (commodity) | `figures/k1129_dm_heatmap.png` → K1129 |
| Fig. 4 | QLIKE comparison (commodity GAS-t) | `figures/k1129_qlike_comparison.png` → K1129 |
| Fig. 5 | VaR violation rates (K1129) | `figures/k1129_var_violations.png` → K1129 |
| Fig. 6 | Commodity skew-t vs Gaussian VaR | `figures/k1135_commodity_skew_vs_gauss.png` → K1135 |
| Fig. 7 | VaR/ES backtest (K1135) | `figures/k1135_var_es_backtest.png` → K1135 |
| Fig. 8 | DM by regime (K1137 HAR regime) | `figures/k1137_dm_by_regime.png` → K1137 |
| Fig. 9 | Regime-conditional heatmap | `figures/k1137_regime_conditional_heatmap.png` → K1137 |
| Fig. 10 | Equity DM heatmap (K1138) | `figures/k1138_dm_heatmap_equity.png` → K1138 |
| Fig. 11 | Equity vs commodity fair tests | `figures/k1138_equity_vs_commodity_fair_tests.png` → K1138 |
| Fig. 12 | VIX component correlation matrix | `figures/k1139_component_correlation_matrix.png` → K1139 |
| Fig. 13 | VIX component contribution | `figures/k1139_vix_component_contribution.png` → K1139 |
| Fig. 14 | GAS-t forecast error by regime | `figures/k1143_gas_forecast_error_by_regime.png` → K1143 |
| Fig. 15 | Score update magnitude distribution | `figures/k1143_score_update_magnitude_distribution.png` → K1143 |
| Fig. 16 | VIX jump regime plot | `figures/k1117_vix_jump_regime_plot.png` → K1117 |
| Fig. 17 | Matched-pair forecast comparison | `figures/k1117_matched_pair_forecast_comparison.png` → K1117 |
| Fig. 18 | Alt-data allocation equity curves | `figures/k1121_equity_curves.png` → K1121 |
| Fig. 19 | Alt-data allocation Sharpe comparison | `figures/k1121_sharpe_comparison.png` → K1121 |
| Fig. 20 | 3-asset cumulative returns vs baselines | `figures/k1123_cumulative_returns_vs_baselines.png` → K1123 |
| Fig. 21 | 0050.TW DM comparison (K1098) | `figures/k1098_dm_comparison.png` → K1098 |
| Fig. 22 | Commodity robust model DM heatmap | `figures/k1136_dm_heatmap.png` → K1136 |

---

## Key JSON Results Files

| File | Location | Contents |
|------|----------|----------|
| `k799_grand_evaluation_results.json` | `experiments/k799/` | Grand QLIKE evaluation; MCS; 11 signal families DM matrix |
| `k824v2_quantile_fixed_results.json` | `experiments/k824v2/` | VaR/ES backtest (AMEM score 1.94 vs 1.63) |
| `k752_vix_sufficiency_eras_results.json` | `experiments/k752/` | 5-era stability test (CV=0.33) |
| `k1116_results.json` | `experiments/k1116/` | SPY alt-data (EPU/NFCI/STLFSI) weekly DM results |
| `k1118_results.json` | `experiments/k1118/` | Cross-asset alt-data (SPY/GLD/TLT) |
| `k1129_results.json` | `experiments/k1129/` | GAS-t commodity (32 DM tests) |
| `k1135_results.json` | `experiments/k1135/` | Commodity skew-t GAS VaR/ES |
| `k1136_results.json` | `experiments/k1136/` | HAR-RV-X + MIDAS on commodity compendium |
| `k1137_results.json` | `experiments/k1137/` | Regime-conditional HAR (Verdict C) |
| `k1138_results.json` | `experiments/k1138/` | Equity compendium MIXED results |
| `k1139_results.json` | `experiments/k1139/` | VIX component decomposition (Scenario B) |
| `k1143_results.json` | `experiments/k1143/` | GAS-t equity harm mechanism |

---

## Reproduction

```bash
# Core signal families evaluation
uv run python paper/vix-sufficiency/reproduce.py

# Individual 2026-04-17 experiments
uv run python experiments/k1135/k1135.py    # commodity skew-t
uv run python experiments/k1137/k1137.py    # regime-invariant HAR
uv run python experiments/k1138/k1138.py    # equity compendium
uv run python experiments/k1139/k1139.py    # VIX component decomp
uv run python experiments/k1143/k1143.py    # GAS-t harm mechanism
```

OOS period: 2008-01-01 – 2026-04-17 (8,325 trading days for main results)
Full sample for era analysis: 1993–2026
