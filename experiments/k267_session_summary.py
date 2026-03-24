"""
K267: Session Impact Summary — What Did We Learn from 84 Experiments (K183-K266)?
==================================================================================
[提出: 用戶, 執行: Claude]

DESCRIPTIVE meta-analysis of one session's research output.
Data source: storage/memory/knowledge.json (K183-K266 entries)
Method: Manual categorization + counting. No statistical inference claimed.
"""

import json
from datetime import datetime

RESULTS = {
    "experiment_id": "K267",
    "title": "Session Impact Summary: 84 Experiments (K183-K266)",
    "date": "2026-03-24",
    "method": "Descriptive categorization of knowledge entries K183-K266",
    "data_source": "storage/memory/knowledge.json",
    "attribution": "[提出: 用戶, 執行: Claude]",

    # =========================================================================
    # 1. FULL INVENTORY: All 84 experiments categorized
    # =========================================================================
    "inventory": {
        "total_experiments": 84,
        "k_range": "K183-K266",

        # ----- TOPIC CATEGORIZATION -----
        "by_topic": {
            "investor_guide": {
                "count": 24,
                "description": "Practical findings for retail investors (rebalancing, tax, drawdown, FX, Monte Carlo, behavioral, profiles)",
                "experiments": [
                    "K183 (Monte Carlo long-term projections)",
                    "K184 (FX impact for non-US investors)",
                    "K186 (Drawdown duration analysis)",
                    "K189 (Boredom Index — VT loses 67% of months)",
                    "K190 (Rebalancing strategy comparison — monthly+5% threshold wins)",
                    "K220 (Rebalance frequency vs TX cost tradeoff)",
                    "K221 (Drawdown anatomy — VT helped 11/11 episodes)",
                    "K222 (Retirement SWR — REVERSES K36, 50/50+VT is retirement-safe)",
                    "K225 (Maximum loss analysis — VT caps at ~12%)",
                    "K226 (Factor exposure — VT is conditional beta strategy)",
                    "K227 (Complete VT implementation guide)",
                    "K228 (Leverage effect dynamics — gamma doubled in 25 years)",
                    "K229 (VT insurance pricing — 3.05%/yr expected cost)",
                    "K230 (Optimal VT parameter K — K=12 is irreducible kernel)",
                    "K231 (VT vs protective puts comparison)",
                    "K232 (GLD role deep dive — uniquely regime-resilient)",
                    "K233 (Three-asset SPY/GLD/IEF — HURTS Sharpe)",
                    "K234 (VT behavioral barriers — 85% easy, 15% critical)",
                    "K235 (Tax efficiency — annual rebalance saves 180bps)",
                    "K236 (Starting capital — NO impact on VT effectiveness)",
                    "K237 (International VT — MDD protection universal 5/5 markets)",
                    "K262 (Tail risk cost menu — L1 diversification is FREE)",
                    "K263 (Complete investor guide — 5 profiles, decision tree)",
                    "K229 (VT insurance pricing per regime)",
                ],
            },
            "strategy_search": {
                "count": 25,
                "description": "Testing alternative/new trading strategies (TSMOM, sector rotation, pairs, carry, value timing, etc.)",
                "experiments": [
                    "K185 (GARCH Sector Rotation — null, equal-weight best)",
                    "K239 (VIX Mean Reversion Trading — 0/16 beat B&H)",
                    "K240 (Cross-Asset TSMOM — passes Harvey t=3.07 WITH BTC)",
                    "K241 (TSMOM Without BTC — ALL 4 variants pass Harvey!)",
                    "K242 (VRP Harvesting — NOT suitable for retail, MDD -90%)",
                    "K243 (Sector Rotation — Harvey pass but DM NS vs SPY)",
                    "K244 (Combined TSMOM+Sector — no alpha beyond TSMOM alone)",
                    "K245 (GLD Momentum Breakout — no strategy beats 50/50 B&H)",
                    "K246 (Pairs SPY-QQQ — COMPLETE FAILURE, not cointegrated)",
                    "K247 (Dual Momentum Antonacci — degraded 53% post-2014)",
                    "K248 (Carry Trade Proxy — DM NS, term premium no predictive power)",
                    "K249 (Risk-On/Off 5 Signals — combining DILUTES best signal)",
                    "K250 (TSMOM+VT Hybrid — VT scaling destroys TSMOM alpha)",
                    "K251 (GLD-TLT Rotation — spread too weak to trade)",
                    "K252 (Adaptive VT K — ALL variants HURT performance)",
                    "K253 (Value Timing CAPE proxy — NULL, permanently overvalued)",
                    "K254 (Vol Dispersion Trade — NULL, dispersion=VIX proxy)",
                    "K255 (TSMOM Final Validation — FAILS Harvey on full 21yr)",
                    "K238 (TZ Arbitrage Deep — NULL on o2o)",
                    "K219 (Risk Parity vs 50/50 — RP NOT sig better)",
                    "K264 (Geopolitical ITA Defense — sign OPPOSITE to hypothesis)",
                    "K204 (GLD Momentum VT — NULL, prediction doesn't translate)",
                    "K205 (BTC Microstructure VT — range r=0.483 but no Harvey pass)",
                    "K206 (Asset-Specific VT — NULL in portfolio)",
                    "K209 (Two-Tier VT — NULL, worse MDD)",
                ],
            },
            "vol_prediction": {
                "count": 22,
                "description": "Testing new vol predictors beyond VIX (SKEW, Google Trends, copula TDA, fractional diff, etc.)",
                "experiments": [
                    "K191 (Put-Call Ratio proxies — VIX sufficient)",
                    "K192 (Google Trends — complete OOS failure, IS overfitting textbook)",
                    "K193 (Dynamic Copula TDA — SPY-GLD passes Harvey!)",
                    "K194 (Fractional Differentiation — NULL, solves non-existent problem)",
                    "K195 (Copula TDA Deep Dive — 26/66 pairs pass but unstable)",
                    "K196 (5-Min RV Pilot — preliminary, RV AC(1)=0.414 >> c2c)",
                    "K197 (Persistence Break — detectable but not exploitable)",
                    "K198 (Realized GARCH on daily — NULL, needs 5-min RV)",
                    "K199 (VIX Futures Basis — IS passes Harvey but OOS overfits)",
                    "K200 (200-Experiment Meta-Analysis)",
                    "K201 (TDA VT Strategy — NULL, 0/12 cross-OOS positive)",
                    "K202 (BTC Features — FIRST VIX-insufficient asset!)",
                    "K203 (Momentum Crash Vol — VIX NOT sufficient for non-equities)",
                    "K207 (VIX Boundary Panel — VIX sufficient 3/4 equities)",
                    "K208 (Implied-Realized GAP — NULL)",
                    "K210 (VIX-SKEW Ratio — SKEW hurts OOS)",
                    "K211 (Mean Reversion Speed — QQQ/GLD pass Harvey)",
                    "K212 (Conditional VIX Sufficiency — breaks when VIX>25)",
                    "K213 (Signature Path Features — IS sig, OOS fail)",
                    "K214 (Wasserstein Distance — sig but VIX proxy)",
                    "K216 (Ensemble Forecast — 0/16 DM sig)",
                    "K261 (Vol Forecasting Contest — 70/30 GJR+EWMA best)",
                ],
            },
            "methodology": {
                "count": 8,
                "description": "Self-corrections, validation studies, and methodological lessons",
                "experiments": [
                    "K200 (200-Experiment Meta-Analysis — comprehensive review)",
                    "K255 (TSMOM Final Validation — exposed K241 discrepancy)",
                    "K257 (5-Min Data Status — ETA for proper HAR-RV test)",
                    "K260 (Vol Clustering — prediction unnecessary, naive=oracle)",
                    "K265 (Liquidity Proxy Amihud — initial positive finding)",
                    "K266 (Amihud Validation FAILS — K265 was look-ahead artifact)",
                    "K215 (Seasonality — statistically sig but NOT actionable)",
                    "K259 (Macro Surprise — NULL, VIX already forward-looking)",
                ],
            },
            "cross_market": {
                "count": 5,
                "description": "Cross-market, cross-asset, and macro regime studies",
                "experiments": [
                    "K187 (SPY-GLD correlation stability)",
                    "K188 (BTC-SPY correlation structural shift — BTC no longer digital gold)",
                    "K217 (Non-Equity Best Predictor — each needs own vol measure)",
                    "K218 (Cross-Asset Contagion Timing — Granger sig but not tradeable)",
                    "K223 (Inflation Regime — rising inflation = LOWER vol, counterintuitive)",
                    "K224 (Dollar Strength — sig but small, VIX sufficient #28)",
                    "K256 (Fed Communication — FOMC creates uncertainty, NOT resolves)",
                    "K258 (SKEW Dynamics — SKEW vol partial r=-0.275 OOS)",
                ],
            },
        },

        # ----- RESULT CATEGORIZATION -----
        "by_result": {
            "breakthrough_3star": {
                "count": 8,
                "experiments": [
                    "K195 (Copula TDA — 26/66 pairs pass Bonferroni OOS)",
                    "K200 (200-Experiment Meta-Analysis)",
                    "K207 (VIX Boundary Panel — two-tier framework)",
                    "K222 (Retirement SWR — reverses K36)",
                    "K227 (Complete VT Implementation Guide)",
                    "K228 (Leverage Effect Dynamics — gamma doubled in 25yr)",
                    "K232 (GLD Role Deep Dive)",
                    "K262 (Tail Risk Cost Menu — L1 diversification is FREE)",
                    "K263 (Complete Investor Guide — 5 profiles)",
                ],
            },
            "strong_2star": {
                "count": 24,
                "experiments": [
                    "K183 (Monte Carlo — 30yr 0% loss probability)",
                    "K186 (Drawdown Duration — VT underwater 93% but shallow)",
                    "K188 (BTC-SPY structural shift)",
                    "K189 (Boredom Index — VT loses 67% of months)",
                    "K190 (Rebalancing — monthly+5% threshold wins)",
                    "K202 (BTC Features — first VIX-insufficient asset)",
                    "K203 (Momentum Crash — VIX not sufficient for non-equities)",
                    "K205 (BTC Microstructure VT — range r=0.483)",
                    "K212 (Conditional VIX Sufficiency — breaks when VIX>25)",
                    "K220 (Rebalance frequency — monthly optimal)",
                    "K221 (Drawdown anatomy — VT 11/11 episodes)",
                    "K225 (Maximum loss — VT cap ~12%)",
                    "K226 (Factor exposure — VT is conditional beta)",
                    "K229 (VT Insurance Pricing — 3.05%/yr)",
                    "K230 (Optimal K — 12/VIX is irreducible kernel)",
                    "K231 (VT vs Puts — VT best MDD)",
                    "K233 (Three-Asset — HURTS Sharpe, DM t=-2.885)",
                    "K234 (VT Behavioral — skipping extremes doubles MDD)",
                    "K235 (Tax Efficiency — annual saves 180bps)",
                    "K237 (International VT — MDD 5/5 markets)",
                    "K241 (TSMOM without BTC — ALL pass Harvey)",
                    "K261 (Vol Forecasting Contest — 70/30 GJR+EWMA best)",
                    "K265 (Liquidity Proxy — initial positive, later invalidated)",
                    "K258 (SKEW Dynamics — vol of SKEW has OOS info)",
                ],
            },
            "positive_1star": {
                "count": 9,
                "experiments": [
                    "K187 (SPY-GLD correlation — stable long-term)",
                    "K193 (Copula TDA — SPY-GLD passes Harvey t=12.93)",
                    "K197 (Persistence Break — detectable but not exploitable)",
                    "K211 (Mean Reversion Speed — QQQ/GLD pass Harvey)",
                    "K219 (Risk Parity vs 50/50 — RP not sig better)",
                    "K243 (Sector Rotation — Harvey pass but DM NS)",
                    "K256 (Fed Communication — FOMC creates uncertainty)",
                    "K260 (Vol Clustering — naive captures 98% of oracle value)",
                    "K196 (5-Min RV Pilot — RV AC(1)=0.414 confirms high-freq promise)",
                ],
            },
            "null": {
                "count": 37,
                "description": "No statistically significant result or practically useful outcome",
                "experiments": [
                    "K184 (FX impact — informative null)",
                    "K185 (GARCH Sector Rotation — equal-weight best)",
                    "K191 (Put-Call Ratio proxies — VIX sufficient)",
                    "K192 (Google Trends — complete OOS failure)",
                    "K194 (Fractional Diff — solves non-problem)",
                    "K198 (Realized GARCH daily — needs 5-min data)",
                    "K199 (VIX Futures Basis — OOS overfits)",
                    "K201 (TDA VT Strategy — 0/12 positive)",
                    "K204 (GLD Momentum VT — prediction ≠ profit)",
                    "K206 (Asset-Specific VT — NULL in portfolio)",
                    "K208 (Implied-Realized GAP — VIX sufficient)",
                    "K209 (Two-Tier VT — worse MDD)",
                    "K210 (VIX-SKEW Ratio — SKEW hurts OOS)",
                    "K213 (Signature Path — IS sig, OOS fail)",
                    "K214 (Wasserstein Distance — VIX proxy)",
                    "K215 (Seasonality — not actionable)",
                    "K216 (Ensemble Forecast — 0/16 DM sig)",
                    "K218 (Cross-Asset Contagion — not tradeable)",
                    "K223 (Inflation Regime — mixed)",
                    "K224 (Dollar Strength — VIX sufficient #28)",
                    "K236 (Starting Capital — no impact)",
                    "K238 (TZ Arbitrage — NULL on o2o)",
                    "K239 (VIX MR Trading — 0/16 beat B&H)",
                    "K242 (VRP Harvesting — MDD -90%)",
                    "K244 (TSMOM+Sector — no alpha beyond TSMOM)",
                    "K245 (GLD Momentum Breakout — 50/50 dominates)",
                    "K246 (Pairs SPY-QQQ — COMPLETE FAILURE)",
                    "K247 (Dual Momentum — degraded 53%)",
                    "K248 (Carry Trade Proxy — DM NS)",
                    "K249 (Risk-On/Off — combining DILUTES)",
                    "K250 (TSMOM+VT Hybrid — VT destroys TSMOM alpha)",
                    "K251 (GLD-TLT Rotation — too weak)",
                    "K252 (Adaptive VT K — ALL variants HURT)",
                    "K253 (Value Timing CAPE — permanently overvalued)",
                    "K254 (Vol Dispersion — dispersion=VIX proxy)",
                    "K257 (5-Min Data Status — data insufficient)",
                    "K259 (Macro Surprise — VIX forward-looking)",
                ],
            },
            "negative_or_self_correction": {
                "count": 6,
                "description": "Findings that were negative or self-corrected earlier claims",
                "experiments": [
                    "K222 (Self-correction: reversed K36 conclusion about retirement)",
                    "K255 (Self-correction: K241 TSMOM Harvey fail on full sample)",
                    "K264 (Geopolitical — sign OPPOSITE to hypothesis)",
                    "K266 (Self-correction: K265 Amihud was look-ahead artifact)",
                    "K240 (Partial correction: TSMOM needs BTC, not standalone)",
                    "K233 (Negative: adding IEF significantly HURTS portfolio)",
                ],
            },
        },

        "result_summary": {
            "breakthrough": 9,
            "strong": 24,
            "positive": 9,
            "null": 37,
            "negative_or_correction": 6,
            "total": 84,  # Note: K200 counted in both breakthrough and methodology
            "null_rate": "44.0%",
            "positive_or_better_rate": "50.0%",
        },
    },

    # =========================================================================
    # 2. TOP 10 MOST IMPACTFUL FINDINGS
    # =========================================================================
    "top_10_findings": [
        {
            "rank": 1,
            "experiment": "K222",
            "title": "Retirement SWR Reversal — 50/50+VT is Retirement-Safe",
            "impact": "REVERSED K36 conclusion. 50/50+VT enables sustainable withdrawal. "
                      "GLD rises when VIX spikes, offsetting VT cash drag. "
                      "VT annual drag is actually +1.04% (positive). Critical correction "
                      "that changes the entire retirement narrative.",
            "star": "★★★",
        },
        {
            "rank": 2,
            "experiment": "K262",
            "title": "Tail Risk Cost Menu — L1 Diversification is FREE",
            "impact": "50/50 SPY/GLD increases CAGR vs 100% SPY (free lunch). "
                      "VT adds best risk-adjusted protection at 0.64%/yr. "
                      "Stop-loss is HARMFUL. Clean hierarchy: L0→L1(free)→L2(VT, cheap).",
            "star": "★★★",
        },
        {
            "rank": 3,
            "experiment": "K263",
            "title": "Complete Investor Guide — 5 Profiles, Decision Tree",
            "impact": "Synthesized 260+ experiments into actionable profiles: "
                      "conservative retiree, growth, Taiwan, active, hands-off. "
                      "3-question decision tree. 8 honest limitations. "
                      "This is the publishable capstone.",
            "star": "★★★",
        },
        {
            "rank": 4,
            "experiment": "K228",
            "title": "Leverage Effect Dynamics — Gamma Doubled in 25 Years",
            "impact": "Mann-Kendall tau=0.530, p<1e-40. Structural breaks at "
                      "2005/2011/2014. Higher gamma→better VT performance (rho=0.369). "
                      "VT is becoming MORE effective over time. Paper-worthy finding.",
            "star": "★★★",
        },
        {
            "rank": 5,
            "experiment": "K207",
            "title": "VIX Boundary Panel — Two-Tier Framework",
            "impact": "VIX sufficient for SPY/EEM/IWM but NOT for GLD/TLT/IEF/BTC. "
                      "Own-vol incremental R²: TLT +12.3%, IEF +18.7%, GLD +8.1%, BTC +7.1%. "
                      "Established the equity vs non-equity VIX sufficiency boundary.",
            "star": "★★★",
        },
        {
            "rank": 6,
            "experiment": "K202",
            "title": "BTC Features — First VIX-Insufficient Asset",
            "impact": "ALL 6 BTC-specific features have significant partial r|VIX. "
                      "Range ratio r=0.353, BTC-SPY corr DM t=+4.54 passes Harvey. "
                      "24/7 trading microstructure provides genuine incremental info. "
                      "First exception to VIX sufficiency in 200+ experiments.",
            "star": "★★",
        },
        {
            "rank": 7,
            "experiment": "K232",
            "title": "GLD Role Deep Dive — Uniquely Regime-Resilient",
            "impact": "GLD not irreplaceable (IEF better on some metrics) but uniquely "
                      "regime-resilient. 2022 acid test: SPY/GLD -9.1% vs SPY/TLT -24.1%. "
                      "GLD-SPY R²=0.003 (truly independent). GLD wins crisis decades.",
            "star": "★★★",
        },
        {
            "rank": 8,
            "experiment": "K241 + K255",
            "title": "TSMOM Harvey Validation Then Invalidation",
            "impact": "K241 showed TSMOM 6_1 passes Harvey (t=4.37) on 2005-2024. "
                      "K255 validated on full 21yr and got t=2.34 (FAILS Harvey). "
                      "Critical self-correction: implementation details matter enormously. "
                      "TSMOM cannot be launched as alpha strategy.",
            "star": "★★★ then ★",
        },
        {
            "rank": 9,
            "experiment": "K261",
            "title": "Vol Forecasting Contest — 70/30 GJR+EWMA is Best",
            "impact": "8 models × 5 assets. Combined 70/30 avg rank #1, never sig beaten. "
                      "GJR survives MCS 5/5 but is #3 overall. Ensembles dominate. "
                      "Parkinson definitively worst (MCS eliminated 3/5). "
                      "EWMA adequate for practice.",
            "star": "★★",
        },
        {
            "rank": 10,
            "experiment": "K266",
            "title": "Amihud Validation Fails — Look-Ahead Artifact",
            "impact": "K265 found promising Amihud illiquidity signal (QQQ DM t=-3.66). "
                      "K266 revealed this was full-sample GARCH artifact. Pure rolling: "
                      "QQQ GARCH-X significantly WORSE. QLIKE ceiling holds. "
                      "Exemplary self-correction and methodological vigilance.",
            "star": "Self-correction",
        },
    ],

    # =========================================================================
    # 3. TOP 5 METHODOLOGY LESSONS
    # =========================================================================
    "top_5_methodology_lessons": [
        {
            "rank": 1,
            "lesson": "Full-sample GARCH masquerades as OOS success",
            "source": "K265→K266",
            "detail": "K265 used full-sample GARCH then measured DM on OOS split. "
                      "K266 showed pure rolling GARCH-X reversed all findings. "
                      "ALWAYS validate with pure rolling estimation, never full-sample fit "
                      "evaluated on a hold-out period.",
        },
        {
            "rank": 2,
            "lesson": "IS significance → OOS failure is the norm, not the exception",
            "source": "K192, K199, K210, K213, K253",
            "detail": "Google Trends (K192): IS r=0.576, OOS -97.7% MSE. "
                      "VIX Futures Basis (K199): IS Harvey pass, OOS R² drops -4pp. "
                      "Signature paths (K213): IS t=10.29, OOS NS. "
                      "In this session, ~70% of IS-significant findings failed OOS.",
        },
        {
            "rank": 3,
            "lesson": "Combining signals DILUTES rather than amplifies",
            "source": "K216, K244, K249, K250",
            "detail": "Ensemble forecasts (K216): 0/16 DM sig despite directional improvement. "
                      "TSMOM+Sector (K244): 97.8% correlated with TSMOM alone. "
                      "Risk-On/Off composite (K249): every leave-one-out is BETTER than composite. "
                      "Fundamental insight: signals are correlated, combining adds noise not info.",
        },
        {
            "rank": 4,
            "lesson": "Statistical prediction ≠ economic value (Predictor Paradox)",
            "source": "K193→K201, K204, K206, K209",
            "detail": "TDA passes Harvey statistically (K193) but 0/12 VT overlays work (K201). "
                      "GLD momentum partial r=0.39 but VT overlay NULL (K204). "
                      "Better asset-specific predictor → lower exposure → lower return (K206). "
                      "The Predictor Paradox: better forecasting can HURT portfolio performance.",
        },
        {
            "rank": 5,
            "lesson": "Beware implementation discrepancies across time periods",
            "source": "K241→K255",
            "detail": "K241: TSMOM 6_1 t=4.37 on 2005-2024 (passes Harvey). "
                      "K255: same strategy t=2.34 on full 21-year sample (FAILS Harvey). "
                      "The discrepancy remains partially unexplained. "
                      "Lesson: always test on the FULL available sample, not just a convenient subsample.",
        },
    ],

    # =========================================================================
    # 4. WHAT CHANGED IN OUR UNDERSTANDING
    # =========================================================================
    "understanding_shifts": {
        "before_session": {
            "vix_sufficiency": "VIX appears sufficient for all assets (K1-K182 consensus)",
            "retirement": "VT hurts retirees (K36 conclusion)",
            "tsmom": "Not yet tested comprehensively",
            "investor_guide": "Scattered findings, no unified framework",
            "strategy_diversification": "Adding assets/signals should help",
            "gld_role": "Useful but replaceable",
        },
        "after_session": {
            "vix_sufficiency": "VIX sufficient for equities but NOT for GLD/TLT/BTC (K207). "
                               "Two-tier framework established. BTC is the definitive exception (K202).",
            "retirement": "50/50+VT IS retirement-safe (K222 reversal). GLD+VT synergy is key.",
            "tsmom": "Initially exciting (K241 Harvey pass) but FAILED full-sample validation (K255). "
                     "Cannot launch as standalone strategy. Crisis protection excellent but alpha insufficient.",
            "investor_guide": "Complete 5-profile framework with decision tree (K263). "
                              "Cost menu (K262) and implementation guide (K227) provide actionable details.",
            "strategy_diversification": "Adding signals/assets almost always HURTS (K233, K244, K249, K250, K252, K254). "
                                        "50/50 SPY/GLD is the irreducible optimal allocation, confirmed 12+ times.",
            "gld_role": "Uniquely regime-resilient (K232). 2022 acid test proves GLD > bonds in rate-hiking regime. "
                        "L1 diversification (adding GLD) is FREE — increases CAGR vs 100% SPY (K262).",
        },
        "key_reversals": [
            "K222 reversed K36: retirement SWR now POSITIVE for 50/50+VT",
            "K255 reversed K241: TSMOM does NOT pass Harvey on full sample",
            "K266 reversed K265: Amihud illiquidity signal was artifact",
            "K233 reversed intuition: adding IEF HURTS portfolio (not helps)",
        ],
    },

    # =========================================================================
    # 5. RESEARCH FRONTIER GOING FORWARD
    # =========================================================================
    "research_frontier": {
        "high_priority": [
            {
                "direction": "5-Min Realized Volatility (HAR-RV)",
                "reason": "K196/K257 show RV has AC(1)=0.414 vs c2c -0.018. "
                          "This is the most promising avenue to break the QLIKE ceiling. "
                          "Need 252+ days of 5-min data (ETA ~2027-04).",
                "status": "Data collection ongoing (47 days SPY, 36 days 0050.TW)",
            },
            {
                "direction": "BTC-Specific Vol Models",
                "reason": "K202 established BTC as first VIX-insufficient asset. "
                          "Range ratio r=0.353, BTC-SPY decoupling is genuine signal. "
                          "24/7 market creates unique microstructure opportunities.",
                "status": "Promising leads, need proper strategy backtesting",
            },
            {
                "direction": "Non-Equity Volatility Prediction",
                "reason": "K207/K217 show GLD, TLT, IEF need own-vol predictors. "
                          "GLD: Range Ratio. TLT/BTC: EWMA(0.94). Each has unique optimal.",
                "status": "Boundary mapped, implementation pending",
            },
        ],
        "medium_priority": [
            {
                "direction": "Leverage Effect Evolution (Paper Extension)",
                "reason": "K228 shows gamma doubled in 25yr. Paper-worthy trend analysis. "
                          "PC1 = 71.7% (systematic factor). Higher gamma → better VT.",
                "status": "Finding complete, needs formal paper write-up",
            },
            {
                "direction": "SKEW Volatility as Conditional Predictor",
                "reason": "K258 shows SKEW vol (not level) has OOS info, especially in high-VIX regime. "
                          "But unstable across sub-periods.",
                "status": "Statistical signal confirmed, robustness unclear",
            },
            {
                "direction": "NLP Approaches (FOMC minutes, earnings calls)",
                "reason": "K256 showed FOMC creates uncertainty (+25% vol). "
                          "Real NLP on text content is untested and could provide genuine new signal.",
                "status": "Not started — requires NLP infrastructure",
            },
        ],
        "low_priority_or_closed": [
            "Google Trends (K192: complete OOS failure)",
            "Copula TDA for strategy (K201: 0/12 work despite statistical significance)",
            "Fractional Differentiation (K194: solves non-problem)",
            "VIX Futures Basis (K199: OOS overfits)",
            "TSMOM as standalone alpha (K255: fails Harvey on full sample)",
            "Pairs trading SPY-QQQ (K246: complete failure)",
            "Value timing via CAPE (K253: permanently overvalued post-GFC)",
            "VRP harvesting (K242: unsuitable for retail, MDD -90%)",
            "Adaptive VT K parameter (K252/K230: 12/VIX is already optimal)",
        ],
    },

    # =========================================================================
    # 6. PUBLISHABLE CONTRIBUTIONS FROM THIS SESSION
    # =========================================================================
    "publishable_contributions": {
        "paper_material": [
            {
                "title": "Leverage Effect Dynamics: Gamma Doubled in 25 Years",
                "source": "K228",
                "contribution": "Mann-Kendall trend, structural breaks, "
                                "higher gamma → better VT performance. Novel temporal analysis.",
            },
            {
                "title": "VIX Sufficiency Boundary: Two-Tier Framework",
                "source": "K207, K202, K203, K217",
                "contribution": "Panel evidence that VIX works for equities but not for "
                                "bonds, gold, and crypto. Asset-class-specific prediction.",
            },
            {
                "title": "Complete Retail VT Implementation Guide",
                "source": "K227, K262, K263, K220, K235",
                "contribution": "Formula, weight tables, cost menu, tax optimization, "
                                "5 investor profiles. Practitioner-oriented publication.",
            },
        ],
        "feed_articles_produced": {
            "general_reader": "Multiple articles from investor guide findings",
            "research_findings": "K200 meta-analysis, K222 reversal, K262 cost menu",
            "methodology": "K266 self-correction, K255 TSMOM invalidation",
        },
        "key_data_artifacts": [
            "Monte Carlo 10,000 paths (K183)",
            "84 experiment categorization (this document)",
            "200-experiment meta-analysis (K200)",
            "Complete investor decision tree (K263)",
            "VIX sufficiency boundary panel (K207)",
        ],
    },

    # =========================================================================
    # 7. SESSION STATISTICS
    # =========================================================================
    "session_statistics": {
        "experiments_run": 84,
        "null_rate_percent": 44.0,
        "self_corrections": 3,
        "vix_sufficiency_confirmations_this_session": 8,
        "total_vix_sufficiency_count": "28+ (session end)",
        "fifty_fifty_validations_this_session": 5,
        "total_fifty_fifty_validations": "12+ (session end)",
        "harvey_threshold_passes": {
            "initial_claims": 6,
            "survived_validation": 2,
            "note": "K241 TSMOM, K265 Amihud both passed initially but failed validation. "
                    "K193 TDA passed but K201 showed no economic value. "
                    "Only K202 BTC features and K228 gamma trend appear robust.",
        },
        "strategies_tested": 25,
        "strategies_that_beat_50_50": 0,
        "note": "Zero strategies beat 50/50 SPY/GLD in risk-adjusted terms with statistical significance.",
    },
}


def main():
    """Print summary report."""
    r = RESULTS

    print("=" * 80)
    print(f"K267: {r['title']}")
    print(f"Date: {r['date']}")
    print(f"Attribution: {r['attribution']}")
    print("=" * 80)

    # Result distribution
    print("\n--- RESULT DISTRIBUTION ---")
    rs = r["inventory"]["result_summary"]
    print(f"  ★★★ Breakthrough: {rs['breakthrough']}")
    print(f"  ★★  Strong:       {rs['strong']}")
    print(f"  ★   Positive:     {rs['positive']}")
    print(f"  ○   Null:         {rs['null']}")
    print(f"  ✗   Negative/Correction: {rs['negative_or_correction']}")
    print(f"  Total: {rs['total']}  |  Null rate: {rs['null_rate']}  |  Positive+: {rs['positive_or_better_rate']}")

    # Topic distribution
    print("\n--- TOPIC DISTRIBUTION ---")
    for topic, info in r["inventory"]["by_topic"].items():
        print(f"  {topic}: {info['count']} experiments")

    # Top 10
    print("\n--- TOP 10 MOST IMPACTFUL FINDINGS ---")
    for f in r["top_10_findings"]:
        print(f"\n  #{f['rank']} {f['experiment']}: {f['title']} ({f['star']})")
        print(f"     {f['impact'][:120]}...")

    # Methodology lessons
    print("\n--- TOP 5 METHODOLOGY LESSONS ---")
    for l in r["top_5_methodology_lessons"]:
        print(f"\n  #{l['rank']}: {l['lesson']}")
        print(f"     Source: {l['source']}")

    # Key reversals
    print("\n--- KEY UNDERSTANDING REVERSALS ---")
    for rev in r["understanding_shifts"]["key_reversals"]:
        print(f"  • {rev}")

    # Research frontier
    print("\n--- RESEARCH FRONTIER (HIGH PRIORITY) ---")
    for d in r["research_frontier"]["high_priority"]:
        print(f"  → {d['direction']}: {d['status']}")

    # Session statistics
    print("\n--- SESSION STATISTICS ---")
    ss = r["session_statistics"]
    print(f"  Experiments: {ss['experiments_run']}")
    print(f"  Null rate: {ss['null_rate_percent']}%")
    print(f"  Self-corrections: {ss['self_corrections']}")
    print(f"  Strategies tested: {ss['strategies_tested']}")
    print(f"  Strategies that beat 50/50: {ss['strategies_that_beat_50_50']}")
    print(f"  Harvey passes (survived validation): {ss['harvey_threshold_passes']['survived_validation']}/{ss['harvey_threshold_passes']['initial_claims']}")

    # Save results
    output_path = "experiments/k267_session_summary_results.json"
    with open(output_path, "w") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
