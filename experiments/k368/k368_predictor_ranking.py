#!/usr/bin/env python3
"""
K368: Vol Prediction Hall of Fame — Ranking ALL Tested Predictors by Partial r|VIX

Meta-analysis of 185+ experiments across the VolPred research program.
Extracts every predictor tested for incremental vol prediction power
beyond VIX, ranks them by |partial r|, and classifies into tiers.

[提出: 用戶, 執行: Claude]
Data source: storage/memory/knowledge.json (978 entries)
Method: Manual extraction from knowledge entries, cross-referenced
"""

import json
from datetime import datetime

# ============================================================
# DEFINITIVE PREDICTOR RANKING TABLE
# ============================================================
# Each entry extracted from knowledge.json with traceable source
#
# Fields:
#   predictor: Name of the predictor variable
#   partial_r: Partial correlation with vol, controlling for VIX
#   t_stat: t-statistic (if reported)
#   p_value: p-value (if reported)
#   asset: Which asset(s) tested on
#   source_experiment: Which experiment (phase/number)
#   harvey_pass: Whether t > 3.0 (Harvey 2016 threshold)
#   oos_survives: Whether OOS validation passed
#   rolling_stable: Whether rolling/sub-period checks passed
#   verdict: Final classification
#   notes: Additional context
# ============================================================

PREDICTORS = [
    # ===================================================================
    # TIER 1: HALL OF FAME — Passed Harvey AND survived validation
    # ===================================================================
    {
        "predictor": "STLFSI2 (St. Louis Financial Stress Index)",
        "partial_r": 0.406,  # sqrt of partial R²=16.5%
        "t_stat": 6.49,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "G9 (FRED 42-var sweep)",
        "harvey_pass": True,
        "oos_survives": True,
        "rolling_stable": True,  # 4/4 sub-samples stable
        "verdict": "HALL_OF_FAME",
        "notes": "Strongest predictor found. BUT STLFSI2 contains VIX+credit+yields — "
                 "not truly independent of VIX. Incremental R²=16.5%, OOS R²=0.145. "
                 "Academically valid, practically circular (stress index includes VIX components).",
        "caveat": "Circular — STLFSI2 partially contains VIX information"
    },
    {
        "predictor": "Google Trends 'recession' (weekly)",
        "partial_r": 0.634,
        "t_stat": None,  # p<0.001
        "p_value": 0.001,
        "asset": "SPY",
        "source_experiment": "J3",
        "harvey_pass": True,  # implied from p<0.001
        "oos_survives": False,  # VT overlay all NS
        "rolling_stable": True,  # 2020 r=0.87, 2023 r=0.43, 2025 r=0.68
        "verdict": "PASSED_HARVEY_FAILED_VALIDATION",
        "notes": "Highest raw partial r found (0.634), but weekly frequency vs daily VIX. "
                 "Captures regime-level variation not incremental daily signal. "
                 "VT overlay all NS (DM p=0.47-0.80). Academic interest only.",
        "caveat": "Weekly frequency — cannot improve daily VT"
    },
    {
        "predictor": "Google Trends 'stock market crash' (weekly)",
        "partial_r": 0.600,
        "t_stat": None,
        "p_value": 0.001,
        "asset": "SPY",
        "source_experiment": "J3",
        "harvey_pass": True,
        "oos_survives": False,
        "rolling_stable": True,
        "verdict": "PASSED_HARVEY_FAILED_VALIDATION",
        "notes": "Same as 'recession' — high partial r but weekly, no VT improvement. "
                 "Retail fear → vol channel academically interesting.",
        "caveat": "Weekly frequency — cannot improve daily VT"
    },
    {
        "predictor": "VIX Backwardation (term structure inversion)",
        "partial_r": None,  # reported as lift ratio, not partial r
        "t_stat": 8.58,  # for next-day |ret| comparison
        "p_value": None,
        "asset": "SPY, 0050.TW",
        "source_experiment": "P36, T-series",
        "harvey_pass": True,
        "oos_survives": True,
        "rolling_stable": True,
        "verdict": "HALL_OF_FAME",
        "notes": "Backwardation days: next-day |ret|=2.38% vs contango 0.88% (t=8.58). "
                 "Incremental beyond VIX level: logistic coeff 0.70 vs VIX 0.36. "
                 "Most useful in low-VIX regime (lift=5.10x when VIX<20). "
                 "BUT: this IS VIX information (term structure), not external.",
        "caveat": "VIX-derived signal, not independent"
    },
    {
        "predictor": "Excess Fear Signal (VIX/GARCH Z>1.5)",
        "partial_r": None,
        "t_stat": 4.48,  # in-sample
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "N182 (Gemini proposed)",
        "harvey_pass": True,  # IS only
        "oos_survives": False,  # OOS t=2.61 (fails Harvey)
        "rolling_stable": False,
        "verdict": "PASSED_HARVEY_FAILED_VALIDATION",
        "notes": "In-sample t=4.48 passes Harvey, but OOS t=2.61 fails. "
                 "Return prediction, not vol prediction per se. Promising but decayed OOS.",
        "caveat": "OOS decay from t=4.48 to t=2.61"
    },
    {
        "predictor": "Taiwan Import YoY (GARCH-MIDAS)",
        "partial_r": 0.214,
        "t_stat": None,
        "p_value": 0.0007,
        "asset": "0050.TW",
        "source_experiment": "G12 (Taiwan 27-indicator sweep)",
        "harvey_pass": True,  # implied from p=0.0007
        "oos_survives": True,  # OOS MSE +5.6%, DM p=0.043
        "rolling_stable": True,
        "verdict": "HALL_OF_FAME",
        "notes": "Only macro indicator to pass IS+OOS dual test for Taiwan. "
                 "Taiwan VIX coverage incomplete for export-oriented economy. "
                 "Improvement small (5.6%) — doesn't change strategy. "
                 "Export YoY equivalent (r=0.92 collinear).",
        "caveat": "Taiwan-specific, small improvement, collinear with exports"
    },
    {
        "predictor": "Taiwan Export YoY (GARCH-MIDAS)",
        "partial_r": 0.196,
        "t_stat": None,
        "p_value": None,
        "asset": "0050.TW",
        "source_experiment": "G19",
        "harvey_pass": True,
        "oos_survives": True,  # OOS +4.1%
        "rolling_stable": True,
        "verdict": "HALL_OF_FAME",
        "notes": "Equivalent to Import YoY (r=0.92 between them). "
                 "Stick with imports as primary. OOS +4.1%.",
        "caveat": "Collinear with imports, Taiwan-specific"
    },

    # ===================================================================
    # TIER 2: PASSED HARVEY BUT FAILED VALIDATION
    # ===================================================================
    {
        "predictor": "TDA Persistence (Topological Data Analysis)",
        "partial_r": -0.224,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "K131 (Gemini proposed)",
        "harvey_pass": False,  # not clearly reported
        "oos_survives": False,
        "rolling_stable": False,  # early warning: GFC only (1/4)
        "verdict": "STATISTICALLY_SIGNIFICANT_FAILED_HARVEY",
        "notes": "VIX captures 96% of TDA info. dR²=0.023. "
                 "Mean-reversion signal. Early warning only worked for GFC (1/4 crises).",
        "caveat": "VIX captures 96% of the information"
    },
    {
        "predictor": "VIX-MOVE ECT (Error Correction Term)",
        "partial_r": -0.0419,
        "t_stat": None,
        "p_value": 0.0024,
        "asset": "SPY",
        "source_experiment": "K153 (Gemini proposed)",
        "harvey_pass": False,
        "oos_survives": False,  # strategy overlay Sharpe diff=-0.0732
        "rolling_stable": False,
        "verdict": "STATISTICALLY_SIGNIFICANT_FAILED_HARVEY",
        "notes": "Cointegration exists (EG p=0.0000), ECT has some info, "
                 "but no OOS forecast improvement. GARCH-X with ECT: DM_t=2.470.",
        "caveat": "Statistically real but economically zero"
    },

    # ===================================================================
    # TIER 3: STATISTICALLY SIGNIFICANT BUT FAILED HARVEY (t < 3.0)
    # ===================================================================
    {
        "predictor": "STLFSI4 (St. Louis Financial Stress v4)",
        "partial_r": 0.16,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "G10",
        "harvey_pass": False,
        "oos_survives": False,  # QLIKE improvement <1%
        "rolling_stable": True,
        "verdict": "STATISTICALLY_SIGNIFICANT_FAILED_HARVEY",
        "notes": "OOS1 QLIKE +0.52% (sig but tiny), OOS2 COVID +0.06% (NS). "
                 "12/VIX Sharpe 0.95 vs STLFSI4 Step 0.82. Cannot break QLIKE ceiling.",
        "caveat": "Tiny improvement, VT strategy worse"
    },
    {
        "predictor": "BAMLH0A0HYM2 change (HY spread change)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "G9",
        "harvey_pass": False,
        "oos_survives": True,  # 5/5 stable, OOS R²=0.045
        "rolling_stable": True,
        "verdict": "STATISTICALLY_SIGNIFICANT_FAILED_HARVEY",
        "notes": "Notable stability (5/5 sub-samples). OOS R²=0.045. "
                 "But improvement too small to be practically relevant.",
        "caveat": "Small effect size"
    },
    {
        "predictor": "Google Trends 'stock market crash' (return predictor)",
        "partial_r": -0.145,
        "t_stat": -3.15,
        "p_value": 0.035,
        "asset": "SPY",
        "source_experiment": "G14",
        "harvey_pass": True,  # raw t=3.15 > 3.0
        "oos_survives": False,  # 2-week reversal
        "rolling_stable": False,
        "verdict": "PASSED_HARVEY_FAILED_VALIDATION",
        "notes": "Controls for VIX+momentum still significant. "
                 "But crash momentum reverses in 2 weeks (+0.84%). "
                 "R²=4.8%. Regime indicator, not trading signal.",
        "caveat": "Reversal within 2 weeks, not tradeable"
    },
    {
        "predictor": "Network Density (Granger causality)",
        "partial_r": -0.172,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "K120",
        "harvey_pass": False,
        "oos_survives": False,  # 4/4 robustness FAIL
        "rolling_stable": False,  # sign consistency 3+/3-
        "verdict": "ARTIFACT",
        "notes": "Looks significant but effective N=15 (raw 709, fwd RV autocorr=0.96). "
                 "Adjusted p=0.43. Sign inconsistency across sub-periods. "
                 "Rolling partial_r oscillates wildly. Classic autocorrelation artifact.",
        "caveat": "Autocorrelation inflated — effective N=15, artifact"
    },
    {
        "predictor": "SPY Centrality (network)",
        "partial_r": -0.232,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "K120",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "ARTIFACT",
        "notes": "Same autocorrelation artifact as network density. Effective N=15.",
        "caveat": "Autocorrelation inflated — artifact"
    },
    {
        "predictor": "Permutation Entropy (information theory)",
        "partial_r": 0.070,
        "t_stat": None,
        "p_value": None,  # sig but tiny
        "asset": "SPY",
        "source_experiment": "K114",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "STATISTICALLY_SIGNIFICANT_FAILED_HARVEY",
        "notes": "Sig due to large N but economically tiny. "
                 "VIX r=0.70 is 10x stronger. All entropy VT strategies worse than 12/VIX.",
        "caveat": "Large-N significance only"
    },

    # ===================================================================
    # TIER 4: HALL OF SHAME — Not significant / Absorbed by VIX
    # ===================================================================
    {
        "predictor": "CNN Fear & Greed Index",
        "partial_r": -0.06,
        "t_stat": -2.4,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "G1 (Phase G)",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "corr(FG,VIX)=-0.57. VIX explains 32% of FG. "
                 "Zero incremental R² over VIX (F-test p>0.15). "
                 "Extreme Fear predicts positive 5d returns (t=3.8) but VIX-driven.",
        "caveat": "Completely absorbed by VIX"
    },
    {
        "predictor": "AAII Bull-Bear Spread",
        "partial_r": 0.028,
        "t_stat": None,
        "p_value": 0.70,
        "asset": "SPY",
        "source_experiment": "J8, G5",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "corr(spread,VIX)=-0.499. Incremental R²=0.0001 (F=0.15). "
                 "VT overlay Sharpe -0.037. Contrarian only at 2-3 year horizon. "
                 "AAII-VIX double fear signal (26w partial r=-0.058, t=-2.36) is marginal.",
        "caveat": "Absorbed by VIX at daily/monthly frequency"
    },
    {
        "predictor": "CBOE SKEW Index",
        "partial_r": 0.03,  # <0.03 per G5
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "G5",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Controlling VIX: partial r <0.03. Combined overlay DM p=0.005 significantly WORSE.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "Credit Spread (BAAFFM, HY)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "T14, G5, P23",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "VIX alone R²=0.318, +credit only +1.6% incremental R² "
                 "(F=10.35 stat sig but econ trivial). Credit overlay REDUCES Sharpe "
                 "(0.79 vs 0.88, t=-1.87). GARCH-MIDAS(BAAFFM) theta≈0.",
        "caveat": "Absorbed by VIX, hurts strategy"
    },
    {
        "predictor": "Yield Curve (T10Y2Y)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "T14, G5, P23",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "GARCH-MIDAS theta≈0. No incremental power beyond VIX. "
                 "Combined with credit: trivial R² gain.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "VVIX (Vol-of-Vol)",
        "partial_r": 0.006,
        "t_stat": None,
        "p_value": 0.70,
        "asset": "SPY",
        "source_experiment": "J17, G5",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Partial corr(VVIX, RV_next|VIX)=0.006 (p=0.70). "
                 "High VVIX predicts VIX mean-reversion, NOT spike. "
                 "Best overlay +0.016 Sharpe (DM p=0.99). "
                 "OOS AUC=0.44 for VaR violations (worse than random).",
        "caveat": "Completely absorbed by VIX, reversal signal"
    },
    {
        "predictor": "MOVE Index (Bond Vol)",
        "partial_r": None,  # r<0.05
        "t_stat": None,
        "p_value": None,
        "asset": "SPY, TLT, HYG",
        "source_experiment": "T11",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "MOVE→SPY/TLT/HYG all r<0.05. VIX sufficient statistic confirmed.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "VIX Term Structure Slope (VIX3M/VIX)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "T13, G5",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "VIX slope incremental R²=0.72% (trivial). "
                 "7 models tested, all regression-based augmented models significantly WORSE. "
                 "VIX-only naive ties GARCH.",
        "caveat": "Trivial incremental R²"
    },
    {
        "predictor": "Shiller CAPE Ratio",
        "partial_r": 0.0001,
        "t_stat": None,
        "p_value": 0.999,
        "asset": "SPY",
        "source_experiment": "G16",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Raw r=-0.22 (p<0.001) but controlling VIX → partial r=0.0001 (p=0.999). "
                 "CAPE incremental R²=0.0000. Prediction power COMPLETELY explained by VIX. "
                 "CAPE change = price return (leverage effect).",
        "caveat": "100% absorbed by VIX — poster child of VIX sufficiency"
    },
    {
        "predictor": "Dividend Yield (DY)",
        "partial_r": 0.06,  # <0.06 per J14
        "t_stat": None,
        "p_value": 0.22,
        "asset": "SPY, 0050.TW",
        "source_experiment": "J14",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "All partial r (controlling VIX) < 0.06, p>0.22. "
                 "30 VT overlay configurations all NS. Taiwan DY→12M has overlapping bias.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "SPY-GLD Correlation Breakdown",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY, GLD",
        "source_experiment": "J18",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Interesting finding (mean 22d corr=+0.30) but null for VT strategy.",
        "caveat": "Descriptive only, no predictive power"
    },
    {
        "predictor": "Crypto Fear & Greed Index",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "BTC",
        "source_experiment": "G18",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Lagging indicator: ret(t-1)→FNG(t) r=+0.40. FNG follows price, doesn't predict.",
        "caveat": "Lagging indicator, not a predictor"
    },
    {
        "predictor": "Cross-Asset Vol PCA (PC1)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY, QQQ, GLD, TLT, EEM, BTC",
        "source_experiment": "T24",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "PC1 explains 76.6% vol variance, r(PC1,VIX)=-0.81. "
                 "PC1 incremental R²=0.00%. VIX IS the market vol first principal component. "
                 "Own vol R²>0.97 → cross-asset info completely redundant.",
        "caveat": "VIX IS PC1 — tautological"
    },
    {
        "predictor": "USD/TWD Exchange Rate",
        "partial_r": None,
        "t_stat": 0.80,
        "p_value": 0.43,
        "asset": "0050.TW",
        "source_experiment": "T-series (Taiwan comprehensive)",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "USD/TWD adds zero info beyond VIX (t=0.80, p=0.43).",
        "caveat": "Absorbed by VIX for Taiwan"
    },
    {
        "predictor": "Sample Entropy (SampEn)",
        "partial_r": 0.001,
        "t_stat": None,
        "p_value": None,  # NS
        "asset": "SPY",
        "source_experiment": "K114",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Raw |r|~0.09 (significant) but VIX r=0.70 is 70x stronger. "
                 "Partial r=0.001 after VIX control. Market complexity already encoded in VIX.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "Approximate Entropy (ApEn)",
        "partial_r": 0.017,
        "t_stat": None,
        "p_value": None,  # NS
        "asset": "SPY",
        "source_experiment": "K114",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Same as SampEn — entropy captured by VIX.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "Climate Disaster Dummy",
        "partial_r": 0.03,  # range 0.03 to -0.03
        "t_stat": None,  # all fail Harvey except USO
        "p_value": None,
        "asset": "SPY, XLE, DBA, KIE",
        "source_experiment": "K148",
        "harvey_pass": False,  # 0/5 except USO t=3.73
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "32 named climate disasters (2010-2024, $1028B). "
                 "Event study 69/130 significant but GARCH-X 0/5 pass Harvey. "
                 "USO only exception (t=3.73, dR²=0.0018). VIX absorbs climate info.",
        "caveat": "Small sample (32 events), VIX absorbs"
    },
    {
        "predictor": "USO Climate Disaster Dummy",
        "partial_r": None,
        "t_stat": 3.73,
        "p_value": None,
        "asset": "USO",
        "source_experiment": "K148",
        "harvey_pass": True,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "PASSED_HARVEY_FAILED_VALIDATION",
        "notes": "Only asset where climate dummy passes Harvey. "
                 "dR²=0.0018 — statistically significant but economically negligible. "
                 "32-event small sample caveat.",
        "caveat": "Tiny effect size, single asset, small sample"
    },
    {
        "predictor": "Net Liquidity (WALCL-WTREGEN-RRPONTSYD)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,  # NS
        "asset": "SPY, GLD, TLT",
        "source_experiment": "K152 (Gemini proposed)",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "5 models tested: GJR remains best. "
                 "VIX already captures liquidity info at daily frequency. "
                 "MS-GARCH with liquidity does not improve.",
        "caveat": "Absorbed by VIX at daily frequency"
    },
    {
        "predictor": "Amihud Illiquidity (log)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY, QQQ, GLD, TLT",
        "source_experiment": "K150 (Gemini proposed)",
        "harvey_pass": False,
        "oos_survives": False,  # QLIKE improvements <0.32%
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "GARCH-X(logAmihud) best QLIKE improvement: -0.32% for QQQ. "
                 "GJR baseline remains dominant across all assets.",
        "caveat": "Marginal QLIKE improvement"
    },
    {
        "predictor": "Order Flow Imbalance (daily OFI proxies)",
        "partial_r": None,  # 8/12 partial corr sig
        "t_stat": None,
        "p_value": None,
        "asset": "SPY, QQQ, GLD",
        "source_experiment": "K154",
        "harvey_pass": False,
        "oos_survives": False,  # GJR+OFI DM wins: 0/6
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "8/12 partial correlations statistically significant "
                 "but daily OHLCV proxies too noisy. "
                 "GJR+OFI adjustment: 0/6 DM-significant wins. "
                 "Needs tick data for real test.",
        "caveat": "Daily proxy too noisy, need tick data"
    },
    {
        "predictor": "CSVD (Cross-Sector Vol Dispersion)",
        "partial_r": None,  # |r|<0.05 after VIX control
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "K151 (Gemini proposed)",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Spec ETF (ARKK/BITO) vs defensive (XLP/XLU/GLD) vol dispersion. "
                 "Large-N significance only (|r|<0.05). VIX captures the information.",
        "caveat": "Large-N artifact"
    },
    {
        "predictor": "GARCH Persistence (alpha+beta)",
        "partial_r": None,
        "t_stat": None,  # range 0.04 to 1.53 (all NS)
        "p_value": None,
        "asset": "SPY → INDPRO",
        "source_experiment": "Bloom 2009 test",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Persistence as macro predictor: controlling for VIX t(NW)=0.04-1.53. "
                 "No incremental value for Industrial Production. "
                 "R²≈0.01-0.03 vs VIX R²=0.12-0.27.",
        "caveat": "VIX dominates for macro prediction too"
    },
    {
        "predictor": "VIX Level (as return predictor)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "K102",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "VIX predicts returns with R²<2%. "
                 "VT is risk management, not return enhancement. "
                 "This is about VIX→return, not VIX→vol (where VIX is dominant).",
        "caveat": "VIX predicts vol well but not returns"
    },
    {
        "predictor": "VRP (Variance Risk Premium) Timing",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "N90, T9, Q10",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "3 independent confirmations of failure. "
                 "VRP positive 84% of time. "
                 "GARCH adds noise not signal to VRP decomposition (K13).",
        "caveat": "Triple-confirmed failure"
    },
    {
        "predictor": "GARCH-X (VIX as exogenous)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "Multiple",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "VIX in variance equation: identical to GARCH (possible arch package bug). "
                 "QLIKE not improved.",
        "caveat": "No improvement from adding VIX to GARCH"
    },
    {
        "predictor": "Europe STOXX → Asia vol (chain effect)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "N225, TWII",
        "source_experiment": "T41",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "STOXX→N225 r=+0.358 but weaker than SPY→N225 r=+0.419. "
                 "Europe incremental R² only +1.8%. Two-day chain r=-0.01 (nonexistent). "
                 "US→Asia is dominant channel.",
        "caveat": "US channel dominates, Europe adds nothing"
    },
    {
        "predictor": "VIX Intraday Change",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "0050.TW, N225",
        "source_experiment": "T42",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "VIX intraday 2nd strongest Asia predictor (r=-0.36). "
                 "But incremental R² only +1.8-2.0% beyond SPY. "
                 "VIX intraday ≈ SPY return (correlated).",
        "caveat": "Redundant with SPY return"
    },
    {
        "predictor": "SPY Overnight Gap (for Asia prediction)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "0050.TW, N225",
        "source_experiment": "T44",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "SPY intraday (r=0.38) >> overnight gap (r=0.20). "
                 "Incremental R² only +0.5-1.2%. SPY total return is best.",
        "caveat": "Decomposition adds no value"
    },
    {
        "predictor": "BTC Weekend → Monday Stock Market",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "T45",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "BTC weekend → SPY Monday: null result. No predictive power.",
        "caveat": "No signal"
    },
    {
        "predictor": "Taiwan Business Cycle Light (景氣燈號)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "0050.TW",
        "source_experiment": "G12",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "All null in Taiwan GARCH-MIDAS 27-indicator sweep.",
        "caveat": "No signal"
    },
    {
        "predictor": "Taiwan M1B-M2 Spread",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "0050.TW",
        "source_experiment": "G12",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "All null in Taiwan GARCH-MIDAS 27-indicator sweep.",
        "caveat": "No signal"
    },
    {
        "predictor": "INDPRO (Industrial Production)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "G9, GARCH-MIDAS",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "GARCH-MIDAS(INDPRO) initially appeared to beat GJR "
                 "but subsequent cross-validation showed NS. "
                 "Real economy indicators controlled by VIX are all null.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "UNRATE (Unemployment Rate)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "G9",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Controlled by VIX: NS. Real economy → vol path is dead.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "CPI (Consumer Price Index)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "G9",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Controlled by VIX: NS.",
        "caveat": "Absorbed by VIX"
    },
    {
        "predictor": "FOMC VIX Pattern",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "R13",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "123 FOMC meetings 2010-2025. Pattern exists but not tradeable.",
        "caveat": "Calendar effect, not a predictor"
    },
    {
        "predictor": "Rate-Hike Regime VT Filter",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "S4",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Null result.",
        "caveat": "No signal"
    },
    {
        "predictor": "SPY Overnight for Taiwan Vol (GARCH-X)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "0050.TW",
        "source_experiment": "T5c",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "GARCH-X(SPY overnight) for Taiwan vol = WORSE (+4%).",
        "caveat": "Makes prediction worse"
    },
    {
        "predictor": "Panel GARCH-X (cross-asset RV)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY, QQQ, GLD, TLT, EEM, BTC",
        "source_experiment": "U1",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "All panel methods worse than GJR baseline. "
                 "A(+QQQ RV) -3%. Cross-asset vol info does not help own-asset prediction.",
        "caveat": "Cross-asset vol info is noise for own-asset"
    },
    {
        "predictor": "MF2-GARCH (Multi-Frequency 2-Component)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY, QQQ, GLD, TLT, EEM, BTC",
        "source_experiment": "K141, K144",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Conrad & Engle 2025 JAE. K141 TLT +0.30% is estimation artifact. "
                 "K144 proper joint QML: GJR wins 5/6 assets. QLIKE ceiling confirmed.",
        "caveat": "Estimation artifact, GJR remains superior"
    },
    {
        "predictor": "XGBoost + HAR",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY, QQQ, GLD",
        "source_experiment": "K142",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "GJR wins 3/3 assets. 4th ML failure. "
                 "Daily return r² signal-to-noise too low for ML.",
        "caveat": "ML fails at daily frequency vol prediction"
    },
    {
        "predictor": "LSTM/GRU (Deep Learning)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "Phase F",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Daily residuals are iid → DL has no incremental pattern to learn. "
                 "GARCH-LSTM hybrid: LSTM factor unstable (std=1.16).",
        "caveat": "IID residuals → no DL advantage"
    },
    {
        "predictor": "FIGARCH (Fractional Integration)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "Multiple",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "d parameter estimated but no QLIKE improvement over GJR.",
        "caveat": "No improvement"
    },
    {
        "predictor": "APARCH(delta=1)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "OOS test",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "QLIKE diff -0.xx% vs GJR(delta=2). No significant improvement.",
        "caveat": "No improvement over GJR"
    },
    {
        "predictor": "MS-GARCH (Markov Switching)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "P31, P33",
        "harvey_pass": False,
        "oos_survives": False,  # QLIKE -0.xx%
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "2-regime Hamilton filter. Regime detection works descriptively "
                 "but no QLIKE improvement. Split-sample OOS marginal.",
        "caveat": "No forecast improvement"
    },
    {
        "predictor": "Factor VT (Moreira-Muir 2017)",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "R3 (Gemini proposed)",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "OOS null result.",
        "caveat": "No improvement"
    },
    {
        "predictor": "Gamma-Momentum Switch",
        "partial_r": None,
        "t_stat": None,
        "p_value": None,
        "asset": "SPY",
        "source_experiment": "R4 (Gemini proposed)",
        "harvey_pass": False,
        "oos_survives": False,
        "rolling_stable": False,
        "verdict": "NOT_SIGNIFICANT",
        "notes": "Null result.",
        "caveat": "No signal"
    },
]


def build_ranking():
    """Build the definitive ranking table."""

    # Sort by |partial_r| where available, then by significance
    def sort_key(p):
        # Priority: HALL_OF_FAME > PASSED_HARVEY > SIG_FAILED > ARTIFACT > NOT_SIG
        verdict_order = {
            "HALL_OF_FAME": 0,
            "PASSED_HARVEY_FAILED_VALIDATION": 1,
            "STATISTICALLY_SIGNIFICANT_FAILED_HARVEY": 2,
            "ARTIFACT": 3,
            "NOT_SIGNIFICANT": 4,
        }
        vorder = verdict_order.get(p["verdict"], 5)
        pr = abs(p["partial_r"]) if p["partial_r"] is not None else 0
        return (vorder, -pr)

    sorted_predictors = sorted(PREDICTORS, key=sort_key)
    return sorted_predictors


def print_summary():
    """Print formatted summary."""
    ranked = build_ranking()

    verdicts = {}
    for p in ranked:
        v = p["verdict"]
        verdicts[v] = verdicts.get(v, 0) + 1

    print("=" * 80)
    print("K368: VOL PREDICTION HALL OF FAME")
    print("Definitive Ranking of ALL Tested Predictors by Partial r|VIX")
    print("=" * 80)
    print(f"\nTotal predictors tested: {len(ranked)}")
    print(f"\nVerdict distribution:")
    for v, n in sorted(verdicts.items()):
        print(f"  {v}: {n}")

    print("\n" + "=" * 80)
    print("TIER 1: HALL OF FAME (Passed Harvey + Survived Validation)")
    print("=" * 80)
    for p in ranked:
        if p["verdict"] == "HALL_OF_FAME":
            pr = f"partial_r={p['partial_r']:.3f}" if p['partial_r'] is not None else ""
            ts = f"t={p['t_stat']:.2f}" if p['t_stat'] is not None else ""
            print(f"\n  ★ {p['predictor']}")
            print(f"    {pr}  {ts}  Asset: {p['asset']}")
            print(f"    Source: {p['source_experiment']}")
            print(f"    Caveat: {p.get('caveat', 'None')}")

    print("\n" + "=" * 80)
    print("TIER 2: PASSED HARVEY BUT FAILED VALIDATION")
    print("=" * 80)
    for p in ranked:
        if p["verdict"] == "PASSED_HARVEY_FAILED_VALIDATION":
            pr = f"partial_r={p['partial_r']:.3f}" if p['partial_r'] is not None else ""
            ts = f"t={p['t_stat']:.2f}" if p['t_stat'] is not None else ""
            print(f"\n  △ {p['predictor']}")
            print(f"    {pr}  {ts}  Asset: {p['asset']}")
            print(f"    Source: {p['source_experiment']}")
            print(f"    Caveat: {p.get('caveat', 'None')}")

    print("\n" + "=" * 80)
    print("TIER 3: SIGNIFICANT BUT FAILED HARVEY / ARTIFACTS")
    print("=" * 80)
    for p in ranked:
        if p["verdict"] in ("STATISTICALLY_SIGNIFICANT_FAILED_HARVEY", "ARTIFACT"):
            pr = f"partial_r={p['partial_r']:.3f}" if p['partial_r'] is not None else ""
            ts = f"t={p['t_stat']:.2f}" if p['t_stat'] is not None else ""
            print(f"\n  ▽ {p['predictor']}  [{p['verdict']}]")
            print(f"    {pr}  {ts}  Asset: {p['asset']}")
            print(f"    Source: {p['source_experiment']}")

    print("\n" + "=" * 80)
    print("TIER 4: HALL OF SHAME (Not Significant — Absorbed by VIX)")
    print(f"  ({sum(1 for p in ranked if p['verdict'] == 'NOT_SIGNIFICANT')} predictors)")
    print("=" * 80)
    for p in ranked:
        if p["verdict"] == "NOT_SIGNIFICANT":
            pr = f"partial_r={p['partial_r']:.3f}" if p['partial_r'] is not None else "partial_r=N/A"
            print(f"  ✗ {p['predictor']:45s} {pr:25s} [{p['source_experiment']}]")

    # Key insights
    print("\n" + "=" * 80)
    print("KEY META-INSIGHTS")
    print("=" * 80)
    print("""
1. VIX SUFFICIENT STATISTIC (21+ confirmations):
   At daily-to-monthly frequency, VIX absorbs virtually ALL alternative
   predictors. The only exceptions are:
   - STLFSI2 (but it CONTAINS VIX → circular)
   - Google Trends (but weekly → can't improve daily VT)
   - Taiwan trade data (but improvement only 5%)
   - VIX backwardation (but this IS VIX term structure)

2. THE QLIKE CEILING:
   GJR-GARCH(1,1) defines the daily vol prediction floor.
   NO alternative model has broken it: GARCH-MIDAS, CARR, MS-GARCH,
   MF2-GARCH, XGBoost, LSTM, Panel GARCH — all fail.

3. THE FUTILITY OF OVERLAY:
   Even predictors with high partial r (Google Trends r=0.634!)
   cannot improve VT strategy because:
   - VIX updates in real-time (daily/intraday)
   - Alternatives are lower frequency (weekly/monthly)
   - 12/VIX already captures the actionable signal

4. HONEST HALL OF FAME IS NEARLY EMPTY:
   Of {len(ranked)} predictors tested, only Taiwan trade data
   provides genuinely independent incremental information.
   STLFSI2 is circular, Google Trends is too slow,
   VIX backwardation is VIX-derived.

5. THE REAL FINDING IS NEGATIVE:
   The most important research conclusion is that VIX alone
   is sufficient. This IS the finding — not a failure.
   It means VT implementation can be maximally simple:
   12/VIX → done. No need for complex multi-signal systems.
""")

    return ranked


def save_results(ranked):
    """Save structured results to JSON."""
    output = {
        "experiment_id": "K368",
        "title": "Vol Prediction Hall of Fame — Definitive Predictor Ranking",
        "methodology": "Meta-analysis of 185+ experiments from knowledge.json (978 entries)",
        "date": datetime.now().isoformat(),
        "total_predictors_tested": len(ranked),
        "summary_stats": {
            "hall_of_fame": sum(1 for p in ranked if p["verdict"] == "HALL_OF_FAME"),
            "passed_harvey_failed_validation": sum(1 for p in ranked if p["verdict"] == "PASSED_HARVEY_FAILED_VALIDATION"),
            "significant_failed_harvey": sum(1 for p in ranked if p["verdict"] == "STATISTICALLY_SIGNIFICANT_FAILED_HARVEY"),
            "artifact": sum(1 for p in ranked if p["verdict"] == "ARTIFACT"),
            "not_significant": sum(1 for p in ranked if p["verdict"] == "NOT_SIGNIFICANT"),
        },
        "meta_conclusion": (
            "VIX is the sufficient statistic for daily-to-monthly vol prediction. "
            "Of 55 predictors tested across 185+ experiments, only Taiwan trade data "
            "(partial r=0.214, OOS +5.6%) provides genuinely independent incremental "
            "information — and only for Taiwan, not US. The QLIKE ceiling (GJR-GARCH) "
            "and VIX sufficiency are the two most robust findings of this research program."
        ),
        "predictors": [
            {
                "rank": i + 1,
                "predictor": p["predictor"],
                "partial_r": p["partial_r"],
                "t_stat": p["t_stat"],
                "asset": p["asset"],
                "source": p["source_experiment"],
                "harvey_pass": p["harvey_pass"],
                "oos_survives": p["oos_survives"],
                "rolling_stable": p["rolling_stable"],
                "verdict": p["verdict"],
                "notes": p["notes"],
                "caveat": p.get("caveat"),
            }
            for i, p in enumerate(ranked)
        ],
        "categories_tested": [
            {"category": "Sentiment/Fear", "count": 6,
             "examples": "CNN FG, AAII, Google Trends, Crypto FG, VVIX, SKEW"},
            {"category": "Macro/Financial", "count": 12,
             "examples": "STLFSI, credit spread, yield curve, CAPE, DY, INDPRO, UNRATE, CPI, liquidity"},
            {"category": "Market Microstructure", "count": 5,
             "examples": "Amihud, OFI, backwardation, overnight gap, intraday decomposition"},
            {"category": "Cross-Asset", "count": 6,
             "examples": "PCA, Europe chain, MOVE, VIX intraday, panel GARCH, BTC weekend"},
            {"category": "Information Theory", "count": 3,
             "examples": "SampEn, PE, ApEn"},
            {"category": "Network/Topology", "count": 3,
             "examples": "Granger network density, centrality, TDA"},
            {"category": "Alternative Models", "count": 10,
             "examples": "MF2-GARCH, MS-GARCH, FIGARCH, APARCH, GARCH-X, XGBoost, LSTM, GARCH-MIDAS"},
            {"category": "Climate/ESG", "count": 1,
             "examples": "Climate disaster dummy"},
            {"category": "Taiwan-Specific", "count": 5,
             "examples": "Import YoY, Export YoY, M1B-M2, 景氣燈號, USD/TWD"},
            {"category": "VIX-Derived", "count": 4,
             "examples": "VIX term structure, VRP, FOMC pattern, rate-hike filter"},
        ],
        "vix_sufficiency_confirmations": 21,
        "qlike_ceiling_confirmations": 4,
    }

    outpath = "experiments/k368_predictor_ranking_results.json"
    with open(outpath, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {outpath}")
    return output


if __name__ == "__main__":
    ranked = print_summary()
    results = save_results(ranked)

    # Print compact ranking table
    print("\n" + "=" * 80)
    print("COMPACT RANKING TABLE (sorted by |partial r| where available)")
    print("=" * 80)
    print(f"{'Rank':>4} {'Predictor':45s} {'|partial r|':>12} {'Verdict':>15}")
    print("-" * 80)

    for i, p in enumerate(ranked):
        pr_str = f"{abs(p['partial_r']):.4f}" if p['partial_r'] is not None else "N/A"
        short_verdict = {
            "HALL_OF_FAME": "★ FAME",
            "PASSED_HARVEY_FAILED_VALIDATION": "△ HARVEY_OK",
            "STATISTICALLY_SIGNIFICANT_FAILED_HARVEY": "▽ SIG_ONLY",
            "ARTIFACT": "✗ ARTIFACT",
            "NOT_SIGNIFICANT": "✗ NULL",
        }.get(p["verdict"], p["verdict"])
        print(f"{i+1:>4} {p['predictor']:45s} {pr_str:>12} {short_verdict:>15}")
