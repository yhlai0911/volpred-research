# Paper 4: Supporting Experiments Index

**Paper**: Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation of Eleven Signal Families for Equity Volatility Forecasting and Volatility Timing
**Journal**: Journal of Forecasting
**Status**: Near submission-ready (R2 SEVERE=0)
**Last Updated**: 2026-04-17

---

## Part A: Original 11 Signal Families (pre-2026-04-17 core experiments)

These experiments underpin the original VIX sufficiency claim across SPY 1993–2026.

| K | Experiment File | Contribution | Path |
|---|----------------|-------------|------|
| K730 | `k730_cross_asset_vol_momentum.py` | Family 1: cross-asset vol momentum (bonds/oil/USD/gold/credit); NULL | `paper/vix-sufficiency/experiments/` |
| K731 | `k731_vix_term_structure.py` | Family 2: VIX term structure (VIX3M/VIX9D slope); NULL | `paper/vix-sufficiency/experiments/` |
| K732 | `k732_pcr_behavioral_sentiment.py` | Family 3: behavioral sentiment (PCR, put-call ratio); NULL | `paper/vix-sufficiency/experiments/` |
| K734 | `k734_vrp_trading_results.json` | Family 4: variance risk premium as predictor; NULL | `paper/vix-sufficiency/experiments/` |
| K736 | `k736_calendar_anomaly_vt_results.json` | Family 8: calendar anomalies; NULL | `paper/vix-sufficiency/experiments/` |
| K738 | `k738_vt_insurance_cost_benefit_results.json` | VT insurance cost-benefit: 12/VIX drag = 3.49%/yr; CRRA γ≥4.5 welfare-improving | `paper/vix-sufficiency/experiments/` |
| K742 | `k742_crowding_simulation_results.json` | Family crowding simulation; NULL for crowding premium | `paper/vix-sufficiency/experiments/` |
| K745 | `k745_pilot_har_rv_results.json` | HAR-RV pilot for realized-vol family; partial context | `paper/vix-sufficiency/experiments/` |
| K746 | `k746_bitcoin_vix_results.json` | Family 7: Bitcoin-VIX Granger causality; no BTC→VIX spillover | `paper/vix-sufficiency/experiments/` |
| K746b | `k746b_bitcoin_vix_fixed_results.json` | K746 bug-fix; confirmed NULL | `paper/vix-sufficiency/experiments/` |
| K747 | `k747_equal_risk_contribution_results.json` | Family 6: equal risk contribution portfolio; NULL for VT improvement | `paper/vix-sufficiency/experiments/` |
| K748 | `k748_simplicity_premium_results.json` | Simplicity premium analysis; supports parsimony conclusion | `paper/vix-sufficiency/experiments/` |
| K749 | `k749_yield_curve_vol_results.json` | Family 10: yield curve slope; NULL | `paper/vix-sufficiency/experiments/` |
| K750 | `k750_google_trends_fear_results.json` | Family 9: Google Trends fear proxies; NULL (OOS DM t=0.669, Harvey FAIL) | `paper/vix-sufficiency/experiments/` |
| K751 | `k751_overnight_vix_news_results.json` | Family 11: overnight VIX changes; NULL | `paper/vix-sufficiency/experiments/` |
| K752 | `k752_vix_sufficiency_eras.py` | Era stability: VIX–RV R² across 5 eras (CV=0.33); supports time-invariance claim | `paper/vix-sufficiency/experiments/` |
| K778 | `k778_mem_r2_native.py` | MEM baseline R² comparison | `paper/vix-sufficiency/experiments/` |
| K780 | `k780_tail_first_es.py` | Tail risk / ES analysis | `paper/vix-sufficiency/experiments/` |
| K799 | `k799_grand_evaluation.py` | Grand QLIKE evaluation: GJR dominates under proxy-robust QLIKE (MCS sole member) | `paper/vix-sufficiency/experiments/` |
| K821 | `k821_ssvs_variance_equation.py` | SSVS variable selection for variance equation | `paper/vix-sufficiency/experiments/` |
| K824v2 | `k824v2_quantile_fixed.py` | VaR/ES quantile evaluation (fixed); AMEM dominates for risk management (score 1.94 vs 1.63) | `paper/vix-sufficiency/experiments/` |
| K828 | `k828_vix_only_insurance.py` | VIX-only insurance cost-benefit baseline | `paper/vix-sufficiency/experiments/` |
| K504 | `k504_stlfsi_strategy.py` | STLFSI4 macro-stress regime VT: adjusting 12/VIX target vol; NULL (STLFSI4 narrow null) | `experiments/k504/` |

---

## Part B: Alt-Data Compendium (cross-asset & conditional null expansions, 2026-04-13+)

These experiments extend the VIX sufficiency claim from SPY-only to cross-asset and conditional settings.

| K | Title | Verdict | Contribution | Path |
|---|-------|---------|-------------|------|
| K1116 | Alternative Data (EPU+NFCI+STLFSI) for SPY weekly RV | NULL | SPY alt-data compendium: all 3 canonical FRED stress series fail; VIX sufficient | `experiments/k1116/` |
| K1116b | FRED Publication-Delay Re-verification | H2/H3 (most hold; TLT M4 collapses) | Delay-corrected robustness; narrative qualification for TLT cell | `experiments/k1116b/` |
| K1117 | Alt-data on VIX jump days (conditional null) | FULL_NULL | Even conditional on VIX jump regime, alt-data adds nothing (87 specs, 2 freq) | `experiments/k1117/` |
| K1118 | Cross-Asset Alternative-Data Sufficiency Test | NULL (3/3 assets) | Universal sufficiency: GLD+VVIX, TLT+MOVE also fail alt-data; H1 universal sufficiency PASS | `experiments/k1118/` |
| K1121 | Alt-data for Portfolio Construction (allocation, not forecasting) | S5 NULL | NFCI regime signal fails allocation task on 2-asset SPY+GLD; Sharpe +0.003, p=0.966 | `experiments/k1121/` |
| K1123 | Cross-asset Alt-data Allocation (SPY+GLD+TLT 3-asset) | NULL | Extending K1121 to TLT bond leg; still fails | `experiments/k1123/` |

---

## Part C: Robust Volatility Models Compendium (2026-04-13 + 2026-04-17)

Tests whether sophisticated robust vol models can beat VIX+GJR baseline. Results shape Paper 4's "what would it take" section.

| K | Title | Verdict | Contribution | Path |
|---|-------|---------|-------------|------|
| K1129 | GAS-t on Commodity Markets (Creal-Koopman-Lucas) | NULL (32 DM tests, 0 PASS) | Symmetric Student-t GAS fails commodity vol prediction; score-driven downweighting unhelpful | `experiments/k1129/` |
| K1130 | Extended IS 2012–2019 for K1128 OFI-jump regime test | NULL (structural) | Extended IS does not rescue degenerate OOS regime coverage; structural problem confirmed | `experiments/k1130/` |
| K1131 | Continuous VIX-dependent β via Cubic Spline | NULL | Spline rescue of K1128 fails: OOS DM t=-3.94; tertile ≥ spline | `experiments/k1131/` |
| K1134 | [GAS-t equity/stock extension of K1129] | NULL | GAS-t also fails on equity (SPY/QQQ/GLD/0050.TW); 32 tests, 0 triple-gate PASS | `experiments/k1134/` [TODO: verify path] |
| K1136 | Non-score-driven robust vol on commodity compendium (HAR-RV-X, GARCH-MIDAS-X) | Hypothesis B CONFIRMED — universal NULL | Even non-score-driven methods fail; commodity daily vol: no exogenous info improves GJR | `experiments/k1136/` |

---

## Part D: 2026-04-17 Key Experiments (today's integration)

These are the most recent experiments completing Paper 4's "robust models compendium" and asset-class boundary tests.

| K | Title | Verdict | Contribution | Path |
|---|-------|---------|-------------|------|
| K1135 | Skew-t GAS on negatively skewed commodities (Scenario B) | TBD — see results | Commodity skew-t GAS: does Hansen (1994) skew-t GAS improve VaR/ES tail risk even if QLIKE null? Defines Channel 3 narrative | `experiments/k1135/` |
| K1137 | HAR+VIX regime-invariant test (rolling ex-ante VIX tertile) | PASS — Verdict C: C_HAR_REGIME_INVARIANT | HAR-RV-X passes across all 3 VIX regimes on SPY/QQQ/IWM; regime-invariant PASS strengthens conclusion | `experiments/k1137/` |
| K1138 | Equity compendium (SPY/QQQ/IWM) robust models | MIXED | HAR-RV-X PASSES equity (SPY t=+4.19, QQQ t=+4.22); GAS-t HARMFUL; MIDAS NULL; asset-class heterogeneity | `experiments/k1138/` |
| K1139 | SPY/QQQ HAR-RV-X deep dive — VIX component decomposition | Scenario B (VRP channel) | Identifies VRP as the dominant driver of the HAR-RV-X equity PASS (not mechanical RV memory) | `experiments/k1139/` |
| K1143 | GAS-t equity HARM mechanism diagnostic | Mechanism locked | GAS-t harmful on equity because: low-ν Student-t over-downweights vol shocks; architecture incompatible with equity persistence | `experiments/k1143/` |

---

## Part E: Taiwan Cross-Asset (Paper 9 / Paper 4 overlap)

| K | Title | Verdict | Contribution | Path |
|---|-------|---------|-------------|------|
| K1098 | 0050.TW with TAIFEX VIXTWN — Taiwan-Matched IV Pilot | TBD | Tests whether asset-matched IV rescues the Taiwan null; complements cross-asset narrative | `experiments/k1098/` |

---

## Part F: VIX Term Structure Robustness (non-K, support main thesis)

These non-K experiments extend K731's VIX term structure analysis and directly support the Paper 4 VIX sufficiency main thesis.

| Folder | Title | Verdict | Contribution | Path |
|--------|-------|---------|-------------|------|
| `vix_term_structure_vol_pred` | VIX Term Structure Volatility Prediction (weekly OOS) | NULL — term structure adds nothing | DM test vix_vs_vix_ts: t=-2.208, p=0.027; VIX level dominates VIX+slope; OOS 2021–2026, n=56 windows | `experiments/vix_term_structure_vol_pred/` |
| `vix_term_structure_vol_pred_v2` | VIX Term Structure Monthly Vol — Robustness (v2) | NULL — in-sample t=4.49 but negative OOS R² | Classic overfitting pattern; VIX/VIX3M ratio IS significant (t=4.49) but collapses OOS; n=44 monthly windows | `experiments/vix_term_structure_vol_pred_v2/` |

These experiments confirm that the VIX term structure slope/ratio has no incremental OOS predictive value beyond VIX level, reinforcing §3 (Family 2 null) and the global sufficiency conclusion.

---

## Missing / Orphan Notes

- **K1129**: present in `experiments/k1129/` (confirmed); the folder was not found in an earlier `ls` but verified via direct path. No issue.
- **K504**: `experiments/k504/README.md` is a stub (Status: planning), but results file `k504_stlfsi_strategy_results.json` exists. STLFSI4 narrow-null confirmed from script content. [K-ref: README stub — possible orphan README but experiment data exists]
- **K1134**: referenced in K1136 README as predecessor; check `experiments/k1134/` for status. [TODO: verify k1134 path]
- **figures for K1118**: no PNG files found in `experiments/k1118/` — result summary only in JSON. [TODO: figure missing from experiments/k1118/]
- **K1116b figures**: `experiments/k1116b/` — no PNG files found. [TODO: figure missing from experiments/k1116b/]
- **K1131 figures**: `experiments/k1131/` has `spline_beta_vs_vix.png` and `tertile_vs_spline_comparison.png` — linked in figures/ if needed.
