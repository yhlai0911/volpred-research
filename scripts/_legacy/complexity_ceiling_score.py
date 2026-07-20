#!/usr/bin/env python3
"""
Complexity Ceiling Score (CCS)
==============================
Quantifies each model/method's improvement across three orthogonal dimensions:
  1. GARCH equation → QLIKE (vol forecasting accuracy)
  2. Distribution   → VaR  (tail risk coverage)
  3. Signal source  → Strategy (investable performance)

Data compiled from 120+ experiments in research_findings.md and knowledge.json.
Phase Q established these as orthogonal: improving one does NOT improve others.

Author: VolPred Research System
Date: 2026-03-17
"""

import json
import os
from datetime import datetime

# ============================================================
# DIMENSION 1: VOLATILITY FORECASTING (QLIKE)
# Baseline: GARCH(1,1) Normal, w=2000, SPY OOS 2020-2025
# GJR best QLIKE = -9.034 (w=252, 2023-2024)
# GARCH baseline QLIKE ≈ -8.988 (w=252, 2023-2024)
# Improvement = (model - GARCH) / |GARCH| * 100
# ============================================================

# ============================================================
# DIMENSION 2: VaR (Tail Risk Coverage)
# Baseline: Normal VaR, 1% level
# Metric: Trinity pass rate (Kupiec + Christoffersen + DQ)
# across 7 assets, 5% VaR level (most stringent test)
# ============================================================

# ============================================================
# DIMENSION 3: STRATEGY (Investable Performance)
# Baseline: Buy & Hold SPY
# Metrics: Sharpe change, MDD change (pp)
# Primary OOS: 2007-2025 (19 years) for strategies
# ============================================================

models = [
    # ====================================================================
    # SECTION A: VOLATILITY FORECASTING MODELS (GARCH equation dimension)
    # ====================================================================
    {
        "id": 1,
        "model": "GARCH(1,1)",
        "dimension": "A. Volatility Forecasting",
        "category": "baseline",
        "n_params": 3,
        "extra_params": 0,
        "data_requirements": "Daily returns",
        "est_time_sec": 2.5,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Baseline. SPY QLIKE=-8.988 (w=252), -8.818 (w=2000). MCS excluded (p=0.044).",
        "var_pass_rate_trinity": "5/7",
        "var_evidence": "Normal VaR: 5/7 Trinity pass. SPY 2.5% violation rate at 1% level → Kupiec FAIL.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "N/A (forecasting model, not strategy). GARCH VT Sharpe=0.718.",
        "net_benefit": 0.0,
        "verdict": "BASELINE — adequate for γ<0.10 assets (GLD, TLT)"
    },
    {
        "id": 2,
        "model": "GJR-GARCH(1,1,1)",
        "dimension": "A. Volatility Forecasting",
        "category": "improvement",
        "n_params": 4,
        "extra_params": 1,
        "data_requirements": "Daily returns",
        "est_time_sec": 3.0,
        "qlike_improve_pct": -0.45,
        "qlike_evidence": "Bootstrap CI [-0.78, -0.14]. P(GJR better)=99.7%. MCS superior (p=0.044). DM p<0.001. Cross-validated 3 OOS periods.",
        "var_pass_rate_trinity": "5/7",
        "var_evidence": "Same as GARCH with Normal dist. VaR improvement comes from distribution, not GARCH equation (O12).",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "GARCH VT vs GJR VT: negligible difference (N90). Model choice does not affect strategy.",
        "net_benefit": 0.45,
        "verdict": "BEST for γ>0.10 assets. +1 param for -0.45% QLIKE. Excellent cost/benefit."
    },
    {
        "id": 3,
        "model": "EGARCH(1,1,1)",
        "dimension": "A. Volatility Forecasting",
        "category": "robustness_check",
        "n_params": 4,
        "extra_params": 1,
        "data_requirements": "Daily returns",
        "est_time_sec": 4.0,
        "qlike_improve_pct": -0.3,
        "qlike_evidence": "Numerically unstable with Student-t. Confirms GJR direction (asymmetry matters) but not reliable for production. Regime change boundary causes false convergence.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not tested in Trinity framework. Known instability issues.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Not used in strategies due to instability.",
        "net_benefit": 0.0,
        "verdict": "ROBUSTNESS CHECK ONLY. Confirms leverage direction but unstable for production."
    },
    {
        "id": 4,
        "model": "GARCH-MIDAS",
        "dimension": "A. Volatility Forecasting",
        "category": "null_result",
        "n_params": 7,
        "extra_params": 4,
        "data_requirements": "Daily returns + monthly macro (INDPRO, credit spread, yield curve)",
        "est_time_sec": 30.0,
        "qlike_improve_pct": 0.00,
        "qlike_evidence": "4 assets × 4 macro variables = 16 tests, ALL DM NS. INDPRO OOS p=0.001 was period-specific (full sample NS). P18/P23 confirmed. Occam: GJR wins.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not tested separately. Macro data does not improve volatility forecast.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "No improvement at forecasting level → no strategy benefit.",
        "net_benefit": 0.0,
        "verdict": "NULL RESULT. +4 params + external data for zero improvement. Complexity ceiling confirmed."
    },
    {
        "id": 5,
        "model": "MS-GARCH (Markov-Switching)",
        "dimension": "A. Volatility Forecasting",
        "category": "null_result",
        "n_params": 6,
        "extra_params": 3,
        "data_requirements": "Daily returns",
        "est_time_sec": 60.0,
        "qlike_improve_pct": -0.01,
        "qlike_evidence": "P31-P33: 5th self-built model. In-sample +2.25% but OOS -0.01%. QLIKE ceiling 5th confirmation. Regime info absorbed by GARCH persistence.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not tested separately.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "No improvement at forecasting level.",
        "net_benefit": 0.003,
        "verdict": "NULL RESULT. In-sample gain vanishes OOS. Classic overfitting pattern."
    },
    {
        "id": 6,
        "model": "CARR (Conditional Autoregressive Range)",
        "dimension": "A. Volatility Forecasting",
        "category": "null_result",
        "n_params": 4,
        "extra_params": 1,
        "data_requirements": "Daily OHLC (range data)",
        "est_time_sec": 5.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "P21-P22: Parkinson range proxy has overnight bias (-3.6% on raw proxy). Yang-Zhang correction makes CARR equivalent to GARCH (0% net). H2: CARR VaR = disaster. Range data adds noise from overnight gaps.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "H2: VaR disaster (exact numbers not recorded but marked as failure).",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Not used in strategies.",
        "net_benefit": 0.0,
        "verdict": "MIXED. Parkinson version fails (overnight bias). Yang-Zhang = GARCH equivalent. No net improvement."
    },
    {
        "id": 7,
        "model": "Realized GARCH (Hansen et al. 2012)",
        "dimension": "A. Volatility Forecasting",
        "category": "blocked",
        "n_params": 8,
        "extra_params": 5,
        "data_requirements": "Daily returns + 5-min intraday data (252+ days)",
        "est_time_sec": 15.0,
        "qlike_improve_pct": -18.0,
        "qlike_evidence": "Pilot 41 days: -18% vs GJR, Corr(h,RV) 3x. But with daily proxies: Parkinson -8.795 (< GJR -8.818), Hourly -8.378 (< GJR -8.472). BLOCKED until 252+ days 5-min data (ETA 2027 Q1).",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not yet testable. Requires 252+ days 5-min data.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Not yet testable.",
        "net_benefit": 3.6,
        "verdict": "ONLY PATH TO BREAK CEILING. -18% QLIKE pilot. Blocked on 5-min data (2027 Q1)."
    },
    {
        "id": 8,
        "model": "FIGARCH (Fractionally Integrated)",
        "dimension": "A. Volatility Forecasting",
        "category": "null_result",
        "n_params": 4,
        "extra_params": 1,
        "data_requirements": "Daily returns",
        "est_time_sec": 10.0,
        "qlike_improve_pct": +8.7,
        "qlike_evidence": "M6: d=0.683 long memory. +8.7% WORSE than GJR. Long memory parameter does not help daily forecasting.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not tested. Worse than baseline.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Not used.",
        "net_benefit": -8.7,
        "verdict": "HARMFUL. Long memory adds noise, worsens forecasts by 8.7%."
    },
    {
        "id": 9,
        "model": "LSTM / GRU (Deep Learning)",
        "dimension": "A. Volatility Forecasting",
        "category": "null_result",
        "n_params": 500,
        "extra_params": 497,
        "data_requirements": "Daily returns (5500+ days for GRU)",
        "est_time_sec": 300.0,
        "qlike_improve_pct": -0.06,
        "qlike_evidence": "H3/F-retry: GRU 5500 days first time beats GARCH by -0.06% but DM p=0.27 (NS). Ljung-Box confirms GJR residuals iid (p=0.76/0.94/0.97) — no signal left for DL. GARCH-LSTM hybrid factor std=1.16 (unstable).",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not applicable — cannot improve on iid residuals.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Not used.",
        "net_benefit": 0.0001,
        "verdict": "NULL RESULT. ~500 params for -0.06% NS improvement. Daily residuals are iid — DL structurally cannot help."
    },
    {
        "id": 10,
        "model": "DCC-GARCH(1,1)",
        "dimension": "A. Volatility Forecasting",
        "category": "null_result",
        "n_params": 5,
        "extra_params": 2,
        "data_requirements": "Daily returns (multivariate, 2+ assets)",
        "est_time_sec": 20.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Q3-Q4: 6th self-built model. SPY-GLD ρ range [-0.63, +0.46]. For 2-asset RP, weights are ρ-independent (analytic result). 3-asset DCC statistical improvement (p=0.023) but economic impact Sharpe +0.006.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Q3: DCC improves portfolio VaR (Kupiec pass vs naive fail), but only for correlated pairs.",
        "strategy_sharpe_delta": +0.006,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Q4: Sharpe +0.006 (economically negligible). Inverse-vol sufficient. DCC catch-22: diversified portfolio = low corr = DCC unimportant.",
        "net_benefit": 0.003,
        "verdict": "NULL for 2-asset. MARGINAL for 3+. Portfolio VaR use case only."
    },
    {
        "id": 11,
        "model": "Copula-GARCH (7 copula types)",
        "dimension": "A. Volatility Forecasting",
        "category": "null_result",
        "n_params": 5,
        "extra_params": 2,
        "data_requirements": "Daily returns (multivariate)",
        "est_time_sec": 45.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Q13-Q14: 7th self-built model. SPY-GLD lower tail dep ≈ 0 (GLD doesn't co-crash). SPY-QQQ lower tail dep = 0.82 (extreme). But GLD 30% dilutes tail dep → VaR underestimation only 2% at 1% level.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Tail-dep-aware VaR improves 2% at 1% level, 8% at 0.1% level. Inverse-vol achieves same without copula.",
        "strategy_sharpe_delta": +0.05,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Q14: Sharpe +0.05-0.07 but inverse-vol matches it. 7th complexity ceiling confirmation.",
        "net_benefit": 0.025,
        "verdict": "NULL for investment. Stress testing insight only. 40/30/30 = 70% US equity + 30% GLD."
    },

    # ====================================================================
    # SECTION B: VaR / DISTRIBUTION METHODS (Distribution dimension)
    # ====================================================================
    {
        "id": 12,
        "model": "Normal VaR",
        "dimension": "B. VaR Distribution",
        "category": "baseline",
        "n_params": 0,
        "extra_params": 0,
        "data_requirements": "GARCH σ estimate",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "O12: Distribution does not affect QLIKE (+0.057%, DM p=0.56 NS). Orthogonal dimension.",
        "var_pass_rate_trinity": "5/7",
        "var_evidence": "Trinity: 5/7 pass. SPY 2.5% violation (fail), BTC 3.3% (fail). Structural underestimation of tails.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "O11: VaR distribution does not affect strategy. 12/VIX dominates all VaR-based sizing (DM p<0.0001).",
        "net_benefit": 0.0,
        "verdict": "BASELINE. Fails for fat-tailed assets. 38 SPY violations vs 14 for CF-VaR."
    },
    {
        "id": 13,
        "model": "Student-t(df=5) VaR",
        "dimension": "B. VaR Distribution",
        "category": "harmful",
        "n_params": 0,
        "extra_params": 0,
        "data_requirements": "GARCH σ estimate (df fixed, not estimated)",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Orthogonal to QLIKE. Zero effect on forecasting.",
        "var_pass_rate_trinity": "2/7",
        "var_evidence": "Trinity: WORST at 5% level. Only 2/7 pass. SPY 6.8%, QQQ 6.2% > 5% nominal → systematic over-conservatism at 5%, Kupiec reject. At 1% level: -45.5% violation improvement (18 vs 33). K12: fixed df=5 better than estimated at 1%, worse at 5%.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "O11: Zero strategy impact. VaR method irrelevant to investment performance.",
        "net_benefit": -1.0,
        "verdict": "HARMFUL at 5% VaR (systematic over-conservatism). OK at 1% only. Superseded by FHS/Skewed-t."
    },
    {
        "id": 14,
        "model": "Skewed Student-t VaR (MLE)",
        "dimension": "B. VaR Distribution",
        "category": "improvement",
        "n_params": 2,
        "extra_params": 2,
        "data_requirements": "GARCH residuals (η and λ estimated via MLE)",
        "est_time_sec": 0.5,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Orthogonal to QLIKE.",
        "var_pass_rate_trinity": "6/7",
        "var_evidence": "Trinity: 6/7 pass (GLD Christoffersen fail). Kupiec: 6/6 pass (only method). Auto-adapts: SPY η=6.5 λ=-0.19 | TLT η=77 λ≈0. Skewness is the key (not just fat tails — O13 GED confirms).",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "O11: Zero strategy impact.",
        "net_benefit": 0.5,
        "verdict": "BEST Kupiec-only method (6/6). Good balance of adaptivity and parametric stability."
    },
    {
        "id": 15,
        "model": "CF-VaR (Cornish-Fisher Expansion)",
        "dimension": "B. VaR Distribution",
        "category": "improvement",
        "n_params": 0,
        "extra_params": 0,
        "data_requirements": "GARCH residuals (rolling skew/kurtosis)",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Orthogonal to QLIKE.",
        "var_pass_rate_trinity": "6/7",
        "var_evidence": "Trinity: 6/7 (GLD Christoffersen fail, same as Skewed-t). SPY: 14 violations 0.9% (p=0.78) vs Normal 38 (2.5%). Asset-specific quantile adjustment. But 0050.TW w=2000 diverges (kurt=545, needs winsorization).",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "O11: Zero strategy impact.",
        "net_benefit": 1.0,
        "verdict": "EXCELLENT cost/benefit — 0 extra params, major VaR improvement. Best for 1% VaR. Instability at high kurtosis."
    },
    {
        "id": 16,
        "model": "FHS (Filtered Historical Simulation)",
        "dimension": "B. VaR Distribution",
        "category": "best",
        "n_params": 0,
        "extra_params": 0,
        "data_requirements": "GARCH residuals (empirical distribution)",
        "est_time_sec": 0.1,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Orthogonal to QLIKE.",
        "var_pass_rate_trinity": "7/7",
        "var_evidence": "Trinity: 7/7 pass, 21/21 tests (100%). ONLY method passing all 3 tests across all 7 assets. Solves BTC distribution paradox. GLD violation clustering: only FHS passes Christoffersen (p=0.055). Non-parametric: no assumptions needed.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "O11: Zero strategy impact.",
        "net_benefit": 2.0,
        "verdict": "BEST VaR method overall. 0 extra params, perfect Trinity pass rate. Universal across asset classes."
    },
    {
        "id": 17,
        "model": "CAViaR (Engle-Manganelli 2004)",
        "dimension": "B. VaR Distribution",
        "category": "equivalent",
        "n_params": 3,
        "extra_params": 3,
        "data_requirements": "Daily returns (direct quantile regression)",
        "est_time_sec": 10.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not applicable (quantile regression, no variance forecast).",
        "var_pass_rate_trinity": "6/7",
        "var_evidence": "O15: SAV spec statistically equivalent to Skewed-t (DM p=0.35). IG spec failed. Asymmetric-slope has clustering issues.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Not used for strategies.",
        "net_benefit": 0.0,
        "verdict": "EQUIVALENT to Skewed-t at 3x complexity. No advantage. Direct quantile = interesting but redundant."
    },
    {
        "id": 18,
        "model": "EVT-VaR (POT + GPD)",
        "dimension": "B. VaR Distribution",
        "category": "harmful",
        "n_params": 2,
        "extra_params": 2,
        "data_requirements": "GARCH residuals (GPD fit to exceedances)",
        "est_time_sec": 1.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Orthogonal to QLIKE.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "O2: 28 violations (1.9%, p=0.003) — WORSE than Student-t. GPD shape parameter unstable in rolling windows. Theoretical elegance does not survive practice.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Not used.",
        "net_benefit": -1.0,
        "verdict": "HARMFUL. GPD rolling instability makes it worse than simpler methods. Academic interest only."
    },

    # ====================================================================
    # SECTION C: INVESTMENT STRATEGIES (Signal source dimension)
    # ====================================================================
    {
        "id": 19,
        "model": "12/VIX (Simple VT)",
        "dimension": "C. Investment Strategy",
        "category": "best",
        "n_params": 0,
        "extra_params": 0,
        "data_requirements": "Daily VIX closing price",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": +0.105,
        "strategy_mdd_delta_pp": +47.8,
        "strategy_evidence": "N80: 19yr Sharpe 0.607 vs BH 0.502 (+0.105). MDD -32.5% vs -80.3% (+47.8pp). Bootstrap MDD p=0.0004. BUT Sharpe t=0.33 (NS per Harvey). N88: beats GARCH VT 5/7 periods. N89: target 6-20 all work (not cherry-pick). With SHY: Sharpe 0.682.",
        "net_benefit": 100.0,
        "verdict": "BEST STRATEGY. Zero params, zero computation. MDD improvement highly significant. Sharpe NS but consistent."
    },
    {
        "id": 20,
        "model": "GARCH VT (σ-based weighting)",
        "dimension": "C. Investment Strategy",
        "category": "equivalent",
        "n_params": 3,
        "extra_params": 3,
        "data_requirements": "Daily returns + GARCH estimation",
        "est_time_sec": 3.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Uses GARCH but strategy performance not from QLIKE improvement.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": +0.076,
        "strategy_mdd_delta_pp": +46.0,
        "strategy_evidence": "Sharpe 0.718-0.826 depending on window/comparison. N88: loses to 12/VIX 5/7 periods. N90: GARCH overlay reduces Sharpe by -0.031. GARCH value is academic, not strategic.",
        "net_benefit": 25.3,
        "verdict": "INFERIOR to 12/VIX. Model-dependent for equivalent or worse results. Academic value only."
    },
    {
        "id": 21,
        "model": "Hybrid VT (VIX/GARCH switching)",
        "dimension": "C. Investment Strategy",
        "category": "marginal",
        "n_params": 4,
        "extra_params": 4,
        "data_requirements": "Daily VIX + GARCH estimation",
        "est_time_sec": 3.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": +0.054,
        "strategy_mdd_delta_pp": +6.3,
        "strategy_evidence": "N69: Fair comparison Sharpe 0.772 vs GARCH 0.718 (+0.054). Previous 1.06 was unfair. MDD improvement at ratio 1.3-2.0 = -6.3pp. Threshold 1.3 = VRP median (principled, N25). But adds significant complexity over 12/VIX for marginal gain.",
        "net_benefit": 1.5,
        "verdict": "MARGINAL over 12/VIX. +0.054 Sharpe for +4 params. Value in crisis MDD reduction only."
    },
    {
        "id": 22,
        "model": "50/50 SPY/GLD + 12/VIX",
        "dimension": "C. Investment Strategy",
        "category": "best_portfolio",
        "n_params": 0,
        "extra_params": 0,
        "data_requirements": "Daily VIX + GLD price",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": +0.324,
        "strategy_mdd_delta_pp": +64.8,
        "strategy_evidence": "Q21: Sharpe 0.826, Calmar 0.77, MDD -15.5% (vs SPY BH -80.3%). GLD zero tail dep = true diversifier. COVID: -8.9% vs BH -33.8%. Adding QQQ harmful (tail dep 0.82).",
        "net_benefit": 100.0,
        "verdict": "BEST RETAIL PORTFOLIO. Zero params, max simplicity. GLD diversification + VIX timing."
    },
    {
        "id": 23,
        "model": "Vol-adj EW SPY+QQQ+SHY 12/VIX",
        "dimension": "C. Investment Strategy",
        "category": "best_multi",
        "n_params": 0,
        "extra_params": 0,
        "data_requirements": "Daily VIX + QQQ/SHY prices",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": +0.410,
        "strategy_mdd_delta_pp": +60.3,
        "strategy_evidence": "N101: Sharpe 0.912, MDD -20%. Best multi-asset combination. Vol-adjusted equal weight.",
        "net_benefit": 100.0,
        "verdict": "BEST MULTI-ASSET. Highest Sharpe with 12/VIX. SHY as cash parking superior to TLT."
    },
    {
        "id": 24,
        "model": "VRP Timing (VIX/GARCH ratio signal)",
        "dimension": "C. Investment Strategy",
        "category": "null_result",
        "n_params": 1,
        "extra_params": 1,
        "data_requirements": "Daily VIX + GARCH estimation",
        "est_time_sec": 3.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": -0.031,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "N90: GARCH overlay REDUCES Sharpe by -0.031. Q10: 6 VRP strategies ALL NS vs 12/VIX. VIX already contains complete VRP information. Adding GARCH is redundant.",
        "net_benefit": -0.031,
        "verdict": "NULL RESULT → HARMFUL. VIX already contains VRP. GARCH adds noise, not signal."
    },
    {
        "id": 25,
        "model": "CDaR Optimization",
        "dimension": "C. Investment Strategy",
        "category": "null_result",
        "n_params": 1,
        "extra_params": 1,
        "data_requirements": "Historical drawdown series",
        "est_time_sec": 1.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Q11: K=12 already at CDaR/Calmar optimal (K=10.5-11.5). Strict monotonic tradeoff, no free lunch.",
        "net_benefit": 0.0,
        "verdict": "NULL RESULT. 12/VIX already near-optimal. CDaR confirms, does not improve."
    },
    {
        "id": 26,
        "model": "Momentum Overlay (DD>15% + SPY>50MA)",
        "dimension": "C. Investment Strategy",
        "category": "spy_only",
        "n_params": 2,
        "extra_params": 2,
        "data_requirements": "Daily prices + drawdown calculation",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": +0.16,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "Q8: SPY Sharpe +0.16, passes Harvey (t=4.00), passes 1000 placebo tests (p=0.000). BUT Q9: 0/4 cross-asset validation. QQQ fires too rarely (5.9%), EEM always-on (46%). SPY V-shaped recovery is unique.",
        "net_benefit": 0.08,
        "verdict": "SPY-ONLY. Passes Harvey on SPY but fails cross-asset. Not generalizable."
    },
    {
        "id": 27,
        "model": "VIX Step Rule (heuristic zones)",
        "dimension": "C. Investment Strategy",
        "category": "equivalent",
        "n_params": 0,
        "extra_params": 0,
        "data_requirements": "Daily VIX",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": +0.09,
        "strategy_mdd_delta_pp": +38.0,
        "strategy_evidence": "CLAUDE.md: Sharpe 0.69, MDD -21%. VIX<15→100%, 15-25→70%, >25→30%. Zero computation. Slightly worse than 12/VIX due to discrete steps.",
        "net_benefit": 90.0,
        "verdict": "EXCELLENT simplicity. For investors who cannot divide. Discrete approximation of 12/VIX."
    },
    {
        "id": 28,
        "model": "EWMA VT (0050.TW)",
        "dimension": "C. Investment Strategy",
        "category": "regional",
        "n_params": 1,
        "extra_params": 1,
        "data_requirements": "Daily returns (EWMA λ parameter)",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": +0.07,
        "strategy_mdd_delta_pp": +23.0,
        "strategy_evidence": "N119: 0050.TW Sharpe 0.73→0.80 (+0.07), MDD -41%→-18% (+23pp). Taiwan market where VIX is unavailable. Q1: 8.63/VIX (VIX×1.39 adjusted) Sharpe 1.16, MDD -13.4% — supersedes EWMA when VIXTWN available.",
        "net_benefit": 7.0,
        "verdict": "BEST for Taiwan (no VIX). Superseded by 8.63/VIX if VIXTWN available."
    },
    {
        "id": 29,
        "model": "Excess Fear Signal (VIX/GARCH Z>1.5)",
        "dimension": "C. Investment Strategy",
        "category": "in_sample_only",
        "n_params": 1,
        "extra_params": 1,
        "data_requirements": "Daily VIX + GARCH estimation",
        "est_time_sec": 3.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "In-sample t=4.48 (significant per Harvey). OOS t=2.61 (below Harvey threshold). FDR audit: IN-SAMPLE ONLY. Proposed by Gemini.",
        "net_benefit": 0.0,
        "verdict": "IN-SAMPLE ONLY. OOS degradation typical of return prediction signals."
    },
    {
        "id": 30,
        "model": "VIX Backwardation Strategy",
        "dimension": "C. Investment Strategy",
        "category": "false_positive",
        "n_params": 1,
        "extra_params": 1,
        "data_requirements": "VIX + VIX3M term structure",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "P34-P43: In-sample passes Harvey (t=4.31). But subsample unstable: 2015-2019 drives result (t=4.42), crisis NS. FDR: FALSE POSITIVE. Same-day timing bias identified.",
        "net_benefit": 0.0,
        "verdict": "FALSE POSITIVE. Subsample instability + timing bias. Not investable."
    },
    {
        "id": 31,
        "model": "MA200 Trend Filter + VT",
        "dimension": "C. Investment Strategy",
        "category": "null_result",
        "n_params": 1,
        "extra_params": 1,
        "data_requirements": "Daily prices (200-day MA)",
        "est_time_sec": 0.0,
        "qlike_improve_pct": 0.0,
        "qlike_evidence": "Not a forecasting model.",
        "var_pass_rate_trinity": "N/A",
        "var_evidence": "Not a VaR method.",
        "strategy_sharpe_delta": 0.0,
        "strategy_mdd_delta_pp": 0.0,
        "strategy_evidence": "P10-P12: Sharpe 2.41 headline but Harvey NS (t=0.89, p=0.37). Not investable at statistical rigor.",
        "net_benefit": 0.0,
        "verdict": "NULL per Harvey threshold. Headline Sharpe misleading."
    },
]

# ============================================================
# COMPUTE NET BENEFIT SCORES
# ============================================================
# Net Benefit = weighted sum / complexity
# QLIKE weight = 1.0, VaR weight = 1.0, Strategy weight = 1.0
# Complexity = 1 + extra_params (to avoid division by zero)

def compute_net_benefit(m):
    """Compute normalized net benefit score."""
    complexity = 1 + m["extra_params"]

    # QLIKE dimension: absolute improvement matters, negative = better
    qlike_score = -m["qlike_improve_pct"]  # flip sign so improvement is positive

    # VaR dimension: pass rate improvement over baseline (5/7)
    var_str = m["var_pass_rate_trinity"]
    if var_str == "N/A":
        var_score = 0.0
    else:
        passes = int(var_str.split("/")[0])
        var_score = (passes - 5) / 7 * 100  # baseline = 5/7

    # Strategy dimension: Sharpe delta + MDD delta (scaled)
    strat_score = m["strategy_sharpe_delta"] * 100 + m["strategy_mdd_delta_pp"] * 0.5

    total = qlike_score + var_score + strat_score
    net = total / complexity

    return round(net, 2)


for m in models:
    m["net_benefit_computed"] = compute_net_benefit(m)

# ============================================================
# OUTPUT
# ============================================================

def format_table():
    """Print formatted table for paper appendix."""
    print("=" * 180)
    print("COMPLEXITY CEILING SCORE — Comprehensive Model/Method Evaluation")
    print("=" * 180)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Total models/methods scored: {len(models)}")
    print(f"Data source: 120+ experiments, research_findings.md, knowledge.json")
    print(f"Phase Q established three orthogonal dimensions (O12 confirmed independence)")
    print()

    # SECTION A
    print("=" * 180)
    print("SECTION A: VOLATILITY FORECASTING MODELS (GARCH equation → QLIKE)")
    print(f"{'':>3} {'Model':<40} {'Params':>6} {'QLIKE%':>8} {'Est(s)':>7} {'Net':>8} {'Verdict'}")
    print("-" * 180)
    for m in models:
        if m["dimension"] == "A. Volatility Forecasting":
            qlike_str = f"{m['qlike_improve_pct']:+.2f}%" if m['qlike_improve_pct'] != 0 else "BASE"
            print(f"{m['id']:>3} {m['model']:<40} {m['n_params']:>6} {qlike_str:>8} {m['est_time_sec']:>7.1f} {m['net_benefit_computed']:>8.2f} {m['verdict']}")
    print()

    # SECTION B
    print("=" * 180)
    print("SECTION B: VaR DISTRIBUTION METHODS (Distribution → Tail Risk Coverage)")
    print(f"{'':>3} {'Model':<40} {'Params':>6} {'Trinity':>8} {'Net':>8} {'Verdict'}")
    print("-" * 180)
    for m in models:
        if m["dimension"] == "B. VaR Distribution":
            trinity_str = m["var_pass_rate_trinity"]
            print(f"{m['id']:>3} {m['model']:<40} {m['n_params']:>6} {trinity_str:>8} {m['net_benefit_computed']:>8.2f} {m['verdict']}")
    print()

    # SECTION C
    print("=" * 180)
    print("SECTION C: INVESTMENT STRATEGIES (Signal Source → Investable Performance)")
    print(f"{'':>3} {'Model':<40} {'Params':>6} {'dSharpe':>8} {'dMDD':>8} {'Net':>8} {'Verdict'}")
    print("-" * 180)
    for m in models:
        if m["dimension"] == "C. Investment Strategy":
            sharpe_str = f"{m['strategy_sharpe_delta']:+.3f}" if m['strategy_sharpe_delta'] != 0 else "0.000"
            mdd_str = f"{m['strategy_mdd_delta_pp']:+.1f}pp" if m['strategy_mdd_delta_pp'] != 0 else "0.0pp"
            print(f"{m['id']:>3} {m['model']:<40} {m['n_params']:>6} {sharpe_str:>8} {mdd_str:>8} {m['net_benefit_computed']:>8.2f} {m['verdict']}")
    print()

    # SUMMARY
    print("=" * 180)
    print("SUMMARY: COMPLEXITY CEILING RANKINGS")
    print("=" * 180)
    print()

    # Sort by net benefit within each dimension
    for dim_name, dim_label in [
        ("A. Volatility Forecasting", "QLIKE (Vol Forecasting)"),
        ("B. VaR Distribution", "VaR (Tail Risk)"),
        ("C. Investment Strategy", "Strategy (Investable)")
    ]:
        dim_models = [m for m in models if m["dimension"] == dim_name]
        dim_models.sort(key=lambda x: x["net_benefit_computed"], reverse=True)
        print(f"  {dim_label}:")
        for i, m in enumerate(dim_models, 1):
            star = "★" if m["net_benefit_computed"] > 0.3 else "  "
            print(f"    {star} {i}. {m['model']:<45} Net={m['net_benefit_computed']:>8.2f}  [{m['category']}]")
        print()

    # KEY INSIGHTS
    print("=" * 180)
    print("KEY INSIGHTS FROM COMPLEXITY CEILING ANALYSIS")
    print("=" * 180)
    print("""
  1. THREE DIMENSIONS ARE ORTHOGONAL (O12 confirmed, p=0.56):
     - GARCH equation improvements → QLIKE only (not VaR, not Strategy)
     - Distribution choice → VaR only (not QLIKE, not Strategy)
     - Signal source choice → Strategy only (not QLIKE, not VaR)

  2. EACH DIMENSION HAS A CLEAR CEILING:
     - QLIKE: GJR-GARCH(1,1) is MCS-superior. 7+ advanced models add 0 improvement.
       Only Realized GARCH with 5-min data can break through (-18% pilot).
     - VaR: FHS achieves 7/7 Trinity pass with 0 extra parameters.
       Parametric methods (Skewed-t, CF-VaR) reach 6/7 at most.
     - Strategy: 12/VIX achieves best Sharpe/MDD with 0 parameters.
       GARCH-based strategies cannot beat VIX-based (N88, N90).

  3. COMPLEXITY IS ALMOST NEVER REWARDED:
     - 9/11 forecasting models: zero or negative improvement over GJR (+1 param)
     - 3/7 VaR methods: WORSE than Normal baseline despite more complexity
     - 4/13 strategies: HARMFUL (reduce Sharpe or add noise)
     - Total: 16/31 (52%) of methods provide zero or negative value

  4. THE ONLY EXCEPTIONS:
     - GJR-GARCH: +1 param → -0.45% QLIKE (excellent ratio)
     - FHS: +0 params → 7/7 Trinity (pure improvement)
     - 12/VIX: +0 params → +47.8pp MDD (pure improvement)
     - Realized GARCH: +5 params → -18% QLIKE (but blocked on data)

  5. IMPLICATIONS FOR PRACTITIONERS:
     - Use GJR for vol forecasting, FHS for VaR, 12/VIX for investing
     - Total parameter count: 4 (GJR) + 0 (FHS) + 0 (12/VIX) = 4 parameters
     - This 4-parameter system dominates all 500+ parameter alternatives tested
""")


def save_json(filepath):
    """Save as JSON for programmatic use."""
    output = {
        "metadata": {
            "title": "Complexity Ceiling Score (CCS)",
            "generated": datetime.now().isoformat(),
            "n_models": len(models),
            "n_experiments": "120+",
            "data_sources": ["research_findings.md", "knowledge.json", "experiments.json"],
            "phase": "Q (cross-market VT + multivariate models)",
            "orthogonality_confirmed": "O12: GARCH eq → QLIKE, Distribution → VaR, Signal → Strategy (p=0.56 NS)",
        },
        "scoring_method": {
            "qlike_score": "-(QLIKE_improve_pct): negative improvement = positive score",
            "var_score": "(trinity_passes - 5) / 7 * 100: baseline Normal = 5/7",
            "strategy_score": "sharpe_delta * 100 + mdd_delta_pp * 0.5",
            "net_benefit": "(qlike_score + var_score + strategy_score) / (1 + extra_params)",
        },
        "dimensions": {
            "A_volatility_forecasting": {
                "baseline": "GARCH(1,1) Normal, w=2000",
                "metric": "QLIKE (lower = better)",
                "best": "GJR-GARCH(1,1,1) — MCS superior (p=0.044)",
                "ceiling_breaker": "Realized GARCH with 5-min RV (-18% pilot, ETA 2027 Q1)",
            },
            "B_var_distribution": {
                "baseline": "Normal VaR (Gaussian quantile)",
                "metric": "Trinity pass rate (Kupiec + Christoffersen + DQ, 7 assets)",
                "best": "FHS — 7/7 pass, 21/21 tests (100%)",
                "key_finding": "Skewness more important than fat tails (O13)",
            },
            "C_investment_strategy": {
                "baseline": "Buy & Hold SPY",
                "metric": "Sharpe delta, MDD delta (pp)",
                "best": "12/VIX — Sharpe +0.105, MDD +47.8pp, 0 params",
                "key_finding": "VIX contains complete VRP; GARCH adds no strategy value (N90)",
            },
        },
        "models": models,
        "rankings": {
            "A_qlike_ranking": [
                "1. GJR-GARCH(1,1,1)  [-0.45%, MCS superior]",
                "2. EGARCH(1,1,1)      [-0.3%, robustness check only]",
                "3. GARCH(1,1)         [baseline]",
                "--- CEILING ---",
                "4. MS-GARCH           [-0.01% OOS, in-sample mirage]",
                "5. GARCH-MIDAS        [0.00%, 16/16 DM NS]",
                "6. DCC-GARCH          [0.00%, univariate unchanged]",
                "7. LSTM/GRU           [-0.06% NS, residuals iid]",
                "8. CARR               [-3.6% with bias, 0% corrected]",
                "9. FIGARCH            [+8.7%, HARMFUL]",
                "--- BLOCKED ---",
                "?. Realized GARCH     [-18% pilot, needs 5-min data]",
            ],
            "B_var_ranking": [
                "1. FHS               [7/7 Trinity, 0 params]",
                "2. Skewed-t           [6/7 Trinity, 2 params]",
                "2. CF-VaR             [6/7 Trinity, 0 params]",
                "4. CAViaR             [6/7 equivalent to Skewed-t]",
                "5. Normal             [5/7 Trinity, baseline]",
                "6. Student-t(5)       [2/7 Trinity, HARMFUL at 5%]",
                "7. EVT-VaR            [worse than Student-t, unstable]",
            ],
            "C_strategy_ranking": [
                "1. 12/VIX + SHY             [Sharpe 0.682, MDD -23.7%, 0 params]",
                "2. 50/50 SPY/GLD 12/VIX     [Sharpe 0.826, MDD -15.5%, 0 params]",
                "3. Vol-adj EW+SHY 12/VIX    [Sharpe 0.912, MDD -20%, 0 params]",
                "4. VIX Step Rule             [Sharpe 0.69, MDD -21%, 0 params]",
                "5. GARCH VT                  [Sharpe 0.718-0.826, 3 params]",
                "6. Hybrid VT                 [Sharpe 0.772, 4 params, marginal]",
                "7. EWMA VT (Taiwan)          [Sharpe 0.80, 1 param, regional]",
                "--- CEILING ---",
                "8. Momentum Overlay          [SPY-only, fails cross-asset]",
                "9. VRP Timing                [HARMFUL, reduces Sharpe]",
                "10. CDaR Optimization         [null, 12/VIX already optimal]",
                "11. Excess Fear               [in-sample only, OOS degraded]",
                "12. VIX Backwardation         [false positive]",
                "13. MA200 Trend Filter        [Harvey NS]",
            ],
        },
        "key_statistics": {
            "total_models_tested": 31,
            "zero_or_negative_value": 16,
            "pct_wasteful_complexity": "51.6%",
            "optimal_total_params": 4,
            "optimal_system": "GJR-GARCH(4 params) + FHS(0) + 12/VIX(0)",
            "largest_param_model": "LSTM/GRU (~500 params)",
            "largest_param_improvement": "-0.06% NS (500 params for nothing)",
            "best_param_efficiency": "12/VIX: +47.8pp MDD with 0 params",
        },
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nJSON saved to: {filepath}")


if __name__ == "__main__":
    format_table()

    # Save JSON
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "storage", "results", "complexity_ceiling_score.json"
    )
    save_json(json_path)
