"""
K302: What We Still Don't Know — The Open Questions After 300 Experiments

SYNTHESIS ONLY — no new computation. Based on 1142 knowledge entries.

After 300+ experiments, 179 null results, and 44 self-corrections, this catalog
identifies genuinely UNRESOLVED questions that our research program could not answer.

[提出: 用戶, 執行: Claude]
"""

import json
from datetime import datetime

# =============================================================================
# CATEGORY A: ANSWERABLE WITH CURRENT DATA (Need Better Methods)
# These questions have available data but our methods couldn't crack them.
# =============================================================================

category_a = [
    {
        "id": "OQ-A1",
        "question": "Can any model break the daily QLIKE ceiling?",
        "importance": "CRITICAL",
        "why_it_matters": (
            "36 independent validations confirmed GJR-GARCH(1,1) defines the daily "
            "QLIKE floor. 14 model families × 3 assets all fail to significantly beat it. "
            "But GJR only captures ~63% of SPY variance, ~19% for GLD, ~15% for BTC "
            "(K132 Capture Rate). There is 37-85% unexplained variance."
        ),
        "what_we_tried": [
            "FIGARCH (d=0.68, long memory exists but +8.7% worse OOS)",
            "MS-GARCH (8 params, IS +2.25% vanishes OOS, P33)",
            "Component GARCH (trend too slow for regime changes)",
            "GARCH-MIDAS (macro: INDPRO/BAAFFM/T10Y2Y all +0.02% NS)",
            "GARCH-X (VIX: unstable delta 0.006-0.821, +0.17% worse)",
            "CARR (Parkinson: -33.9% overnight bias kills it)",
            "Wavelet-GARCH (MODWT: apparent -22% was look-ahead bias, K159)",
            "GBM (VIX-only: false alarm, cross-asset 0/15 significant, T22)",
            "XGBoost/Ridge-HAR (4th ML attempt: all worse, K142)",
            "Panel GARCH-X (cross-asset: adds noise, U1 null)",
            "EMD-GARCH (0/9 significant, K112)",
            "Hurst-augmented GARCH (+1.28% worse, no improvement)",
            "APARCH (delta=1 vs delta=2: DM p=0.34 NS)",
            "Regime-aware ICL (LLM in-context: interesting but fragile)",
        ],
        "what_might_resolve_it": (
            "5-min Realized Volatility as GARCH measurement equation input. "
            "RV is 10.5x less noisy than daily r^2 (R9). GARCH forecast-to-RV "
            "correlation is near zero at daily frequency (-0.11 over 41 days) because "
            "GARCH is a smoother, but RV ACF(1)=0.41 shows the underlying signal exists. "
            "HAR-RV in literature gets R^2=0.3-0.6 vs our 0.05 with 41 days. "
            "Also: Rough Volatility with proper 5-min Hurst estimation (H=0.10 confirmed "
            "but daily proxy unreliable, T3)."
        ),
        "estimated_timeline": "252+ trading days of 5-min data (~12 months from 2026-01)",
        "confidence_resolvable": 0.65,
        "evidence_refs": ["K6", "K132", "P33", "K159", "T22", "K142", "R9", "T3"],
    },
    {
        "id": "OQ-A2",
        "question": "What drives the 37% of SPY variance that GARCH cannot capture?",
        "importance": "HIGH",
        "why_it_matters": (
            "K132 decomposition: SPY Capture Rate = 62.7% [56.9, 67.9]. "
            "The remaining ~37% is 'irreducible' at daily frequency with close-to-close "
            "returns. Understanding its composition (overnight gaps? jumps? macro events? "
            "microstructure?) would reveal whether ANY daily model can improve, or if "
            "the ceiling is fundamental."
        ),
        "what_we_tried": [
            "Overnight gap decomposition: gap = 36.5% of daily var (K158), confirming major source",
            "Jump detection via BPV: jumps = 23.1% of RV (5-min pilot)",
            "Macro event calendar: FOMC/NFP/CPI add 13% vol but VIX already prices it (K259)",
            "Order flow proxies: partial r < 0.08 controlling VIX (K154)",
            "GARCH-in-Mean: lambda = 0.037, p=0.38 NS (vol does not predict returns)",
        ],
        "what_might_resolve_it": (
            "Proper overnight-intraday-jump variance decomposition using 5-min data over "
            "252+ days. Zhang (2025, J Forecasting) shows overnight vol decomposition "
            "significantly improves prediction — the most promising direction from literature. "
            "Also: tick-level VPIN/OFI for microstructure component."
        ),
        "estimated_timeline": "252+ days 5-min data + tick data access",
        "confidence_resolvable": 0.55,
        "evidence_refs": ["K132", "K158", "K259", "K154", "K196"],
    },
    {
        "id": "OQ-A3",
        "question": "Is GLD's inverted leverage effect structural or just a gold-standard artifact?",
        "importance": "HIGH",
        "why_it_matters": (
            "GLD gamma is negative 93% of quarters (mean gamma = -0.088). This is our "
            "most novel finding (Chevallier & Ielpo 2017 documented it in commodities but "
            "we provided the systematic cross-asset taxonomy). The mechanism hypothesis: "
            "gold rises during fear (positive returns coincide with high vol via safe-haven "
            "flows). But is this a fundamental property of gold, or an artifact of the "
            "2005-2026 sample where gold was primarily a fear hedge?"
        ),
        "what_we_tried": [
            "12-quarter rolling gamma: consistently negative (all 12 quarters)",
            "Bear market test (2012-2015): gamma flipped positive (GLD gamma = +0.06 during gold bear, K48/K95)",
            "Cross-commodity: SLV mixed (-0.02, 72% negative), USO standard (like equities)",
            "Defensive equities: JNJ/MRK/PFE gamma near zero, NOT inverted",
        ],
        "what_might_resolve_it": (
            "Longer history (pre-2005, physical gold price data since 1970s). Test whether "
            "gamma was inverted during: (1) gold standard era, (2) 1980-2000 bear market, "
            "(3) 2011-2015 bear. The 2012-2015 bear result (gamma flipped +) suggests "
            "the inversion IS linked to gold's safe-haven role, which could weaken if gold's "
            "monetary role diminishes. Need COMEX futures data."
        ),
        "estimated_timeline": "Achievable now with COMEX/LBMA historical data",
        "confidence_resolvable": 0.70,
        "evidence_refs": ["K48", "K95", "K228", "R6"],
    },
    {
        "id": "OQ-A4",
        "question": "Why does QLIKE-VT disconnect exist? (Best volatility model ≠ best strategy)",
        "importance": "HIGH",
        "why_it_matters": (
            "K124/N124: Cross-asset Spearman rho(QLIKE improvement, VT Sharpe improvement) "
            "= 0.700 but p = 0.188 (NS, N=5). Taiwan GJR VT Sharpe 1.108 vs GARCH VT 0.994 "
            "(+0.114 Sharpe) despite insignificant QLIKE difference. QLIKE measures average "
            "accuracy; VT rewards timing during regime changes. K130 showed the optimal model "
            "is objective-dependent (90-cell loss tensor, no Pareto-dominant model)."
        ),
        "what_we_tried": [
            "Decision-conditioned model selection (K130: 6 models × 3 assets × 5 objectives)",
            "Loss function analysis: QLIKE vs MSE vs VaR vs utility-based metrics",
            "Regime-conditional evaluation: GJR wins crisis, EWMA wins calm",
        ],
        "what_might_resolve_it": (
            "A formal theoretical framework connecting QLIKE loss to economic utility. "
            "The Estimation Risk/Overfitting Duality suggested by Gemini: complexity increases "
            "QLIKE fit but also estimation variance, creating a bias-variance tradeoff that "
            "differs between statistical and economic evaluation. Need formal proof that "
            "VT utility is a concave function of QLIKE with diminishing returns."
        ),
        "estimated_timeline": "Theoretical work, 1-2 months",
        "confidence_resolvable": 0.75,
        "evidence_refs": ["K130", "K137", "N124", "K123"],
    },
    {
        "id": "OQ-A5",
        "question": "Can Copula-GARCH or CAViaR provide a fundamentally different approach to tail risk?",
        "importance": "MEDIUM",
        "why_it_matters": (
            "BTC distribution paradox: no single parametric distribution passes both VaR-1% "
            "and VaR-5% simultaneously. FHS solves this but is a workaround, not a model. "
            "Gemini suggested CAViaR (direct quantile modeling) and Copula-GARCH (tail "
            "dependence). Neither has been tested. These represent genuinely different "
            "paradigms beyond the GARCH family."
        ),
        "what_we_tried": [
            "FHS (works for BTC but doesn't improve SPY where GJR is sufficient)",
            "GED distribution (fixes SPY VaR-1% but not structural for BTC)",
            "Student-t (BTC: passes VaR-1% but fails VaR-5%)",
        ],
        "what_might_resolve_it": (
            "Implement CAViaR (Engle-Manganelli 2004) for direct VaR estimation without "
            "distribution assumption. Test Copula-GARCH for multivariate tail dependence. "
            "Also: EVT (Extreme Value Theory) for BTC tail modeling."
        ),
        "estimated_timeline": "2-3 weeks implementation + testing",
        "confidence_resolvable": 0.60,
        "evidence_refs": ["BTC_distribution_paradox", "Gemini_Phase_O_review"],
    },
]

# =============================================================================
# CATEGORY B: ANSWERABLE WITH MORE DATA (Need Time)
# These require data that will only become available with time.
# =============================================================================

category_b = [
    {
        "id": "OQ-B1",
        "question": "Can HAR-RV break the QLIKE ceiling with 252+ days of 5-min data?",
        "importance": "CRITICAL",
        "why_it_matters": (
            "HAR-RV is the single most promising path to break the QLIKE ceiling. "
            "Literature R^2 = 0.3-0.6 vs our 0.05 (N=41 underpowered). RV ACF(1) = 0.41 "
            "shows strong predictability exists. Codex R6 meta-diagnosis: 'If you stay on "
            "daily close-to-close variance with public daily covariates, you are probably done.' "
            "5-min RV is the escape route from daily frequency."
        ),
        "current_status": (
            "47 trading days of 5-min SPY data collected (as of 2026-03-24). "
            "yfinance 5-min limit = 59 days rolling. Auto-collection cron active. "
            "HAR-RV pilot R^2 = 0.047 (meaningless at this sample size). "
            "Need 252 days minimum, 500+ for stable estimation."
        ),
        "what_might_resolve_it": "Wait for data accumulation. Target: 2026-10 for 252 days.",
        "estimated_timeline": "October 2026 (252 days), March 2027 (500 days)",
        "confidence_resolvable": 0.70,
        "evidence_refs": ["K196", "R9", "T17", "T25", "N131"],
    },
    {
        "id": "OQ-B2",
        "question": "Will the leverage effect secular decline (K228) continue or reverse?",
        "importance": "HIGH",
        "why_it_matters": (
            "K228: SPY gamma declining from ~0.286 (pre-2020) to ~0.186 (2023-2026), "
            "-35%. All 10 individual stocks show declining gamma (avg -74%). "
            "K228 trend is statistically significant (Mann-Kendall tau=0.530, p<1e-40). "
            "But K228 also showed 3 structural breaks (2005/2011/2014), and the formal "
            "test (non-overlapping 3yr trends) gives p=0.147 — NOT conclusive that it's "
            "structural vs cyclical."
        ),
        "current_status": (
            "Gamma is CURRENTLY cyclical (p=0.147 for structural). Bull markets → higher "
            "gamma, low volume → higher gamma. The 2020-2026 decline may be post-COVID "
            "normalization. If a sustained bear market returns, gamma may rise again."
        ),
        "what_might_resolve_it": (
            "3-5 more years of data including at least one major bear market. "
            "If gamma continues declining through a crisis, the structural hypothesis "
            "gains credibility. If it rebounds, it's cyclical."
        ),
        "estimated_timeline": "2028-2030 (need next bear market cycle)",
        "confidence_resolvable": 0.50,
        "evidence_refs": ["K228", "K197"],
    },
    {
        "id": "OQ-B3",
        "question": "Does VT work in crypto-native portfolios?",
        "importance": "MEDIUM",
        "why_it_matters": (
            "BTC has 8 structural differences from SPY (K119): ACF 3x weaker, NO leverage "
            "effect (p=0.90), VIX R^2 = 0.0005 (useless), kurtosis 9.25. VIX-based VT "
            "is inappropriate for BTC. BTC EWMA VT shows promise (Sharpe 2.10, K58) "
            "but with only ~6 years of mature crypto data, cross-validation is thin."
        ),
        "current_status": (
            "BTC EWMA VT works in-sample. BTC halving vol pattern drops ~44% post-halving "
            "but N=3 halvings (too few). ETH gamma = +0.17 (standard, like equities). "
            "SOL/BNB/XRP gamma is unstable. Only BTC and ETH have meaningful leverage effects."
        ),
        "what_might_resolve_it": (
            "5+ more years of BTC data spanning multiple cycles. Also: DeFi-native vol "
            "instruments (DVol, on-chain implied vol) to build crypto-specific VT. "
            "Next halving (2028) will be critical test."
        ),
        "estimated_timeline": "2028-2030 (next halving cycle + DeFi vol maturation)",
        "confidence_resolvable": 0.45,
        "evidence_refs": ["K119", "K136", "K139", "BTC_halving"],
    },
    {
        "id": "OQ-B4",
        "question": "Is the SPY-TLT correlation break (2022+) permanent?",
        "importance": "HIGH",
        "why_it_matters": (
            "T19: Pre-2022 SPY-TLT corr = -0.42, post-2022 = +0.09 (Fisher z = -13.58, "
            "p<0.0001). This structural break destroyed 60/40 portfolios. Our 50/50 SPY/GLD "
            "strategy avoids this because GLD-SPY R^2 = 0.003 (truly independent). But if "
            "bonds normalize, 60/40 becomes competitive again."
        ),
        "current_status": (
            "2022 rate-hike regime broke the stock-bond negative correlation that held "
            "since ~2000. Historical context: pre-1998, stock-bond corr was often POSITIVE. "
            "The 2000-2021 negative correlation may have been the anomaly, not 2022+."
        ),
        "what_might_resolve_it": (
            "A full rate-cutting cycle + next recession. If corr reverts to negative during "
            "a demand-driven crisis, the break was regime-specific. If it stays positive, "
            "it's a structural shift (inflation-driven macro regime)."
        ),
        "estimated_timeline": "Next recession (unknown, likely 2026-2029)",
        "confidence_resolvable": 0.40,
        "evidence_refs": ["T19", "K111_corr_regime", "K75"],
    },
    {
        "id": "OQ-B5",
        "question": "Will Realized GARCH with proper 5-min RV significantly beat standard GARCH?",
        "importance": "HIGH",
        "why_it_matters": (
            "K198: Realized GARCH with daily OHLC proxy = null (0/15 DM significant). "
            "But the measurement equation noise (sigma_u) is too high with daily proxies. "
            "Pilot with 41 days 5-min: QLIKE -18% vs GJR, Corr(h,RV) 0.267 vs 0.090 (3x "
            "better). But 41 days is meaningless for inference."
        ),
        "current_status": "Waiting for 252+ days of 5-min data. Same timeline as OQ-B1.",
        "what_might_resolve_it": "252+ days 5-min data → proper rolling OOS Realized GARCH test.",
        "estimated_timeline": "October 2026",
        "confidence_resolvable": 0.65,
        "evidence_refs": ["K198", "Realized_GARCH_pilot", "R9"],
    },
]

# =============================================================================
# CATEGORY C: FUNDAMENTALLY DIFFICULT TO ANSWER (Structural Uncertainty)
# These involve future regimes, rare events, or counterfactuals.
# =============================================================================

category_c = [
    {
        "id": "OQ-C1",
        "question": "Will 50/50 SPY/GLD work in a gold-standard collapse or de-dollarization?",
        "importance": "CRITICAL",
        "why_it_matters": (
            "50/50 SPY/GLD is our flagship strategy recommendation. It survived every "
            "historical crisis including 2022 (both fell, VT MDD -8.7%). Monte Carlo: "
            "50/50 wins Sharpe at ALL correlations -0.5 to +1.0. Breaking requires "
            "sustained corr>0.8 + GLD falls + VIX low + months duration (estimated "
            "<0.1%/decade). But we've never seen a true gold-standard crisis in ETF era."
        ),
        "what_we_know": [
            "Gold 5 drawdowns >10%, ALL recovered (K113)",
            "Dollar-GLD r = -0.42 (strong negative, p<1e-191)",
            "2022 acid test: GLD -18.9%, but GLD bottomed 303 days BEFORE last hike",
            "Simulated gold crash: VT MDD = -13.5% (painful but survivable)",
            "Gold bear market 2012-2015: gamma flipped to positive (hedge function weakened)",
        ],
        "why_unresolvable": (
            "Counterfactual: we cannot observe a world where gold loses its monetary "
            "premium entirely. De-dollarization / BRICS reserve currency / digital gold "
            "standard — these are tail scenarios that cannot be backtested. Gold's 5000-year "
            "track record as store-of-value is the best evidence, but past is not prologue "
            "for structural breaks."
        ),
        "estimated_timeline": "UNKNOWABLE",
        "confidence_resolvable": 0.10,
        "evidence_refs": ["K113", "K271_stress_test", "K95"],
    },
    {
        "id": "OQ-C2",
        "question": "What happens when VT becomes crowded?",
        "importance": "HIGH",
        "why_it_matters": (
            "K110 agent-based simulation: current adoption ~5% (300-500B / 50T), "
            "Sharpe decay only 2.3%. Tipping point exists but not yet reached. "
            "However, VT is becoming mainstream (Moreira-Muir 2017 has 2400+ citations). "
            "If adoption reaches 20-30%, the VIX signal degrades because everyone "
            "is selling when VIX is high."
        ),
        "what_we_know": [
            "K110: At 5% adoption, Sharpe decay = 2.3% (negligible)",
            "Tipping point in simulation around 15-25% adoption",
            "VT is fundamentally a liquidity provision strategy (selling in panic)",
            "Market impact: at current scale, VT rebalancing < 0.1% of SPY daily volume",
        ],
        "why_unresolvable": (
            "Cannot observe future adoption rates or emergent market dynamics. "
            "Agent-based simulation is our best tool but relies on assumed agent behaviors. "
            "Also: if VT becomes crowded, smart money will front-run the VIX signal, "
            "creating a second-order effect we can't model."
        ),
        "estimated_timeline": "DEPENDS on adoption trajectory (5-20 years?)",
        "confidence_resolvable": 0.15,
        "evidence_refs": ["K110"],
    },
    {
        "id": "OQ-C3",
        "question": "Is VIX 'sufficient' for VT a permanent or era-specific result?",
        "importance": "CRITICAL",
        "why_it_matters": (
            "VIX sufficient statistic is our strongest validated claim (31 confirmations, "
            "166 alternatives ALL failed, 4/4 cross-period stability for VT strategy). "
            "But K301 noted: VIX sufficient FAILS for statistical prediction in all 4 "
            "cross-periods (lagged |r| always helps QLIKE). The sufficiency is specific to "
            "the VT economic application. What if market structure changes make VIX less "
            "informative about tail risk?"
        ),
        "what_we_know": [
            "F1: VIX sufficient for VT strategy decisions (4/4 cross-periods)",
            "F1 FAILS for statistical vol prediction (lagged |r| always helps QLIKE)",
            "0DTE options now 59% of SPX volume — may change VIX dynamics",
            "VIX term structure increasingly compressed (structural shift?)",
        ],
        "why_unresolvable": (
            "0DTE proliferation is changing options market microstructure. If 0DTE gamma "
            "hedging compresses intraday vol (some CBOE research suggests this), VIX may "
            "become a less accurate measure of realized vol risk. This is an ongoing "
            "structural change whose endpoint is unknown."
        ),
        "estimated_timeline": "3-5 years to assess 0DTE impact",
        "confidence_resolvable": 0.30,
        "evidence_refs": ["K301", "0DTE_research", "VIX_sufficient_31x"],
    },
    {
        "id": "OQ-C4",
        "question": "Can NLP on Fed text / earnings calls improve bond vol prediction?",
        "importance": "MEDIUM",
        "why_it_matters": (
            "TLT has the weakest VIX-based predictability of any equity-adjacent asset "
            "(VIX R^2 for TLT vol < SPY). Bond vol is driven by rate expectations, which "
            "are shaped by Fed communication. NLP extraction of Fed hawkishness / tone "
            "change could provide a leading indicator. FOMC days have +25% TLT vol (K259)."
        ),
        "what_we_tried": [
            "FOMC calendar binary: VIX prices it already (partial r ≈ 0 controlling VIX)",
            "Google Trends 'recession': partial r = 0.634 but incremental R^2 < 1%",
            "K93 VIX surprise z-score: R^2 +2.56% but VT strategy Sharpe zero difference",
        ],
        "why_unresolvable": (
            "Requires access to real-time Fed text processing pipeline (FOMC minutes, "
            "speeches, press conferences). The tools exist (FinBERT, Fed-specific LLMs) "
            "but building a proper NLP pipeline is a major engineering effort outside "
            "our core competency. Also: if NLP sentiment is priced by institutional "
            "algo traders within milliseconds, there's no daily-frequency edge."
        ),
        "estimated_timeline": "6-12 months for NLP pipeline + 1 year of real-time data",
        "confidence_resolvable": 0.35,
        "evidence_refs": ["K259", "K93", "J3"],
    },
    {
        "id": "OQ-C5",
        "question": "Will 50/50 SPY/GLD outperform SPY buy-and-hold over the next 20 years?",
        "importance": "CRITICAL",
        "why_it_matters": (
            "Historical: 50/50 Sharpe 0.51 vs SPY 0.39 (2005-2026). But this period "
            "includes two major GLD bull runs (GFC flight-to-safety, 2019-2026 inflation). "
            "SPY B&H has higher CAGR in pure bull markets. The question isn't whether "
            "50/50 has better risk-adjusted returns (it does, statistically), but whether "
            "the Sharpe advantage (0.12) is economically meaningful over a lifetime — "
            "Sharpe SE ≈ 1/sqrt(n_years), so 20yr Sharpe has CI width ±0.45."
        ),
        "what_we_know": [
            "Sharpe improvement is NOT statistically significant (CI includes 0)",
            "MDD improvement IS significant (p=0.0004, bootstrap)",
            "50/50 free lunch: SPY-GLD corr ≈ 0 means diversification increases Sharpe for free",
            "Gold bear market (2012-2015): 50/50 underperformed SPY by ~5%/yr",
        ],
        "why_unresolvable": (
            "The next 20 years may be structurally different (AI-driven growth, inflation "
            "regime, de-dollarization, climate transition). Any prediction is speculation."
        ),
        "estimated_timeline": "UNKNOWABLE (20 years)",
        "confidence_resolvable": 0.05,
        "evidence_refs": ["K61", "K271_stress_test", "K87_self_correction"],
    },
]

# =============================================================================
# CATEGORY D: QUESTIONS WE HAVEN'T ASKED YET (Blind Spots)
# Directions not explored or barely touched in 300 experiments.
# =============================================================================

category_d = [
    {
        "id": "OQ-D1",
        "question": "Can transformer / foundation models for volatility work at daily frequency?",
        "importance": "HIGH",
        "why_it_matters": (
            "Literature review (U3, K149): GARCH-GRU (arXiv:2504.09380) claims 77% MSE "
            "improvement but has 5 fatal flaws (22d training window, biased baseline, etc.). "
            "Regime-aware ICL (arXiv:2603.10299) is promising conceptually. PatchTST for "
            "vol is emerging. We tested GBM (T22, false alarm) and XGBoost (K142, worse) "
            "but never tested modern transformers or foundation models properly."
        ),
        "exploration_status": "BARELY TOUCHED (2 ML attempts, both flawed)",
        "what_would_be_needed": (
            "Proper implementation of (1) PatchTST with multi-asset vol features, "
            "(2) In-context learning with GPT-4/Claude for vol regime detection, "
            "(3) TimeGPT or Chronos fine-tuned on vol data. Key challenge: daily frequency "
            "has ~250 data points per year — may be fundamentally too little for neural nets."
        ),
        "estimated_timeline": "1-2 months implementation",
        "confidence_resolvable": 0.40,
    },
    {
        "id": "OQ-D2",
        "question": "What is the optimal multi-asset VT strategy (beyond 2 assets)?",
        "importance": "HIGH",
        "why_it_matters": (
            "We thoroughly tested 50/50 SPY/GLD and showed 33/33/33 SPY/GLD/TLT fails "
            "(K75). 60/20/20 fails cross-OOS (K24). But we never systematically explored: "
            "(1) 50/50+VT with dynamic gold allocation based on rate regime, "
            "(2) asset-class rotation WITH VT overlay, (3) BTC as a diversifier "
            "(K136: 50/40/10 SPY/GLD/BTC Sharpe 1.03 vs 60/40 0.96 but NS). "
            "The strategy space beyond 2 assets is vastly under-explored."
        ),
        "exploration_status": "PARTIALLY EXPLORED (5-6 multi-asset experiments, all negative)",
        "what_would_be_needed": (
            "Systematic grid search over: (1) asset weights (10% increments), "
            "(2) VT parameter (K) per asset, (3) rebalancing frequency per asset. "
            "With cross-OOS validation. Risk: combinatorial explosion + overfitting."
        ),
        "estimated_timeline": "2-4 weeks",
        "confidence_resolvable": 0.50,
    },
    {
        "id": "OQ-D3",
        "question": "Does intraday volatility pattern (J-shape) contain exploitable information?",
        "importance": "MEDIUM",
        "why_it_matters": (
            "K196/K295: 5-min data shows vol J-shape (open 1.65x midday, close 0.91x). "
            "First 30 min = 17.8% of daily RV in 7.7% of time. ACF(r^2, lag1) = 0.127 "
            "(t=5.65). 22 jumps in 47 days (59% negative, cluster afternoon). "
            "This microstructure pattern is well-known but we haven't tested whether "
            "intraday patterns predict next-day vol better than close-to-close."
        ),
        "exploration_status": "PRELIMINARY (47 days, descriptive only)",
        "what_would_be_needed": (
            "252+ days of 5-min data. Test: (1) First-30-min RV as next-day predictor, "
            "(2) Afternoon jump count as tail risk indicator, (3) Volume-weighted RV "
            "decomposition. Also: optimal intraday sampling frequency for RV."
        ),
        "estimated_timeline": "October 2026 (data dependent)",
        "confidence_resolvable": 0.55,
    },
    {
        "id": "OQ-D4",
        "question": "Can causal inference methods identify TRUE volatility drivers (not just correlates)?",
        "importance": "MEDIUM",
        "why_it_matters": (
            "Most of our 300 experiments find correlations. VIX predicts SPY vol "
            "(r^2 = 0.5+) but is VIX a CAUSE or merely a reflection? "
            "P35: VIX backwardation 'predicts' regime change (lift=3.39x) but may be "
            "simultaneity. We haven't applied: Granger causality networks, directed "
            "information, instrumental variables, or do-calculus."
        ),
        "exploration_status": "BARELY TOUCHED (basic Granger tests only)",
        "what_would_be_needed": (
            "Apply: (1) Convergent Cross Mapping (nonlinear causality), "
            "(2) Transfer Entropy with significance testing (touched in K134 but not "
            "for causal inference), (3) Natural experiments (Fed surprise component "
            "as instrument for vol). This could strengthen the theoretical contribution "
            "of our papers."
        ),
        "estimated_timeline": "1-2 months",
        "confidence_resolvable": 0.45,
    },
    {
        "id": "OQ-D5",
        "question": "Is there a behavioral finance explanation for VT's effectiveness?",
        "importance": "MEDIUM",
        "why_it_matters": (
            "VT works because VIX spikes coincide with drawdowns and mean-revert. "
            "The behavioral explanation: VIX overshoots due to panic selling → VT "
            "de-leverages at the peak of fear → rides the recovery. K271: VIX/RV > 1 "
            "= 'excess fear' → contrarian positive. But we only have 2 behavioral "
            "experiments in 300+ (K138 knowledge topology shows behavioral = 3 entries, "
            "under-explored)."
        ),
        "exploration_status": "BARELY TOUCHED (3 entries in 1142)",
        "what_would_be_needed": (
            "Test: (1) VIX vs actual realized — does VIX systematically over-predict vol? "
            "(2) Disposition effect in options markets (retail buy puts at peaks), "
            "(3) Prospect theory model of VT: loss aversion → excess put demand → "
            "VIX inflation → VT alpha. (4) Behavioral investor simulation comparing "
            "VT vs emotional decision-making."
        ),
        "estimated_timeline": "2-4 weeks",
        "confidence_resolvable": 0.55,
    },
    {
        "id": "OQ-D6",
        "question": "How does VT interact with tax-loss harvesting, DCA, and real portfolio constraints?",
        "importance": "MEDIUM",
        "why_it_matters": (
            "K282: DCA VT = 50/50 BH wins for accumulators (VT costs terminal wealth). "
            "K74: Monthly VT tax drag 48bps (37% ST rate). But we haven't explored: "
            "(1) Tax-lot-aware VT (sell specific lots to minimize tax), "
            "(2) VT + tax-loss harvesting (sell losers in December), "
            "(3) Estate planning implications, (4) Roth conversion timing with VT. "
            "These are critical for real implementation."
        ),
        "exploration_status": "PARTIALLY EXPLORED (tax impact estimated but not optimized)",
        "what_would_be_needed": (
            "Tax-lot simulation with actual IRS rules. Test VT + TLH combined strategy. "
            "Compare: (1) VT in taxable account, (2) VT in IRA, (3) VT in Roth, "
            "(4) Cross-account optimization."
        ),
        "estimated_timeline": "2-3 weeks",
        "confidence_resolvable": 0.70,
    },
]

# =============================================================================
# CATEGORY E: CONTRADICTORY EVIDENCE (Need Resolution)
# Questions where our own experiments give conflicting results.
# =============================================================================

category_e = [
    {
        "id": "OQ-E1",
        "question": "Daily vs Monthly rebalancing: which is actually optimal?",
        "importance": "HIGH",
        "contradiction": (
            "K220 originally said monthly optimal. K279 revised to daily (Sharpe 0.787 "
            "vs monthly 0.187, gross). K281 re-revised back to monthly NET (0.239 vs "
            "daily 0.192 after TX). Three experiments, three answers. The resolution "
            "depends ENTIRELY on transaction cost assumption (0 bps → daily wins, "
            "5+ bps → monthly wins)."
        ),
        "what_we_know": [
            "Gross: daily Sharpe 0.787 >> monthly 0.187 (4x better)",
            "Net at 5bps: monthly 0.239 > daily 0.192",
            "Crossover at ~2-3 bps per trade",
            "For ETFs: actual cost is ~1-3 bps (spread + impact)",
        ],
        "resolution_needed": (
            "Empirical measurement of actual round-trip transaction costs for SPY/GLD "
            "at various trade sizes ($10K, $100K, $1M). Also: limit order fill rates "
            "and slippage. The answer is cost-dependent, not model-dependent."
        ),
        "evidence_refs": ["K220", "K279", "K281"],
    },
    {
        "id": "OQ-E2",
        "question": "Does TSMOM (time-series momentum) add value over 50/50+VT?",
        "importance": "MEDIUM",
        "contradiction": (
            "K241 reported TSMOM 6_1 Sharpe 0.792, t=4.370, Harvey PASS on 20yr data. "
            "K255 found t=2.34 on full sample (discrepancy with K241). Cross-OOS 5/5 "
            "positive BUT DM vs 50/50 all NS. TSMOM+VT hybrid: Sharpe drops 0.466→0.287 "
            "(K252, significantly worse). TSMOM alpha = momentum, VT alpha = vol timing. "
            "They fundamentally conflict."
        ),
        "what_we_know": [
            "TSMOM works standalone (Harvey pass in some periods)",
            "TSMOM does NOT improve over 50/50+VT (no DM significance)",
            "TSMOM+VT actively hurts (momentum and vol timing conflict)",
            "K241 vs K255 discrepancy may be implementation difference (needs investigation)",
        ],
        "resolution_needed": (
            "Reconcile K241 vs K255 t-statistic discrepancy. Then test TSMOM as a "
            "REPLACEMENT (not complement) for VT, with proper cost accounting."
        ),
        "evidence_refs": ["K241", "K255", "K252", "K244"],
    },
    {
        "id": "OQ-E3",
        "question": "Amihud illiquidity: real signal or full-sample artifact?",
        "importance": "LOW",
        "contradiction": (
            "K265: Amihud illiquidity QQQ DM t=-3.66 (significant, Harvey pass). "
            "K266 CRITICAL CORRECTION: this was artifact of full-sample GARCH estimation. "
            "Pure rolling: QQQ significantly WORSE (0-1/3 wins). TLT also reversed. "
            "GLD best case but single-period."
        ),
        "what_we_know": [
            "Full-sample GARCH inflates significance of any additional feature",
            "Pure rolling eliminates the Amihud signal",
            "This pattern may apply to OTHER positive results that used full-sample estimation",
        ],
        "resolution_needed": (
            "Audit ALL experiments that found positive results: were they using "
            "full-sample or rolling estimation? This is a methodological concern "
            "that could invalidate other findings."
        ),
        "evidence_refs": ["K265", "K266"],
    },
]

# =============================================================================
# PRIORITY RANKING FOR NEXT RESEARCH PHASE
# =============================================================================

priority_ranking = [
    {
        "rank": 1,
        "question_id": "OQ-B1",
        "title": "HAR-RV with 252+ days 5-min data",
        "rationale": (
            "Highest expected value: most likely path to break QLIKE ceiling. "
            "Data accumulating automatically. Codex R6 confirms this is the #1 direction. "
            "Literature strongly supports HAR-RV superiority with proper data."
        ),
        "action": "Continue 5-min data collection. Run HAR-RV at 100, 150, 200, 252 day milestones.",
        "blocking": "DATA (need time)",
    },
    {
        "rank": 2,
        "question_id": "OQ-A1",
        "title": "Overnight-Intraday variance decomposition for daily models",
        "rationale": (
            "Zhang (2025) shows this is the most promising daily-frequency improvement. "
            "Overnight gap = 36.5% of variance (K158). Decomposing and modeling "
            "gap^2 separately could improve GARCH without leaving daily frequency."
        ),
        "action": "Implement GARCH with separate overnight/intraday components using OHLC data.",
        "blocking": "METHODS (can start now)",
    },
    {
        "rank": 3,
        "question_id": "OQ-A5",
        "title": "CAViaR for direct quantile modeling",
        "rationale": (
            "Genuinely different paradigm. Avoids distribution assumption entirely. "
            "Solves BTC paradox cleanly. Gemini suggested twice. Never tested."
        ),
        "action": "Implement Engle-Manganelli (2004) CAViaR for SPY/BTC/GLD.",
        "blocking": "METHODS (can start now)",
    },
    {
        "rank": 4,
        "question_id": "OQ-D5",
        "title": "Behavioral finance explanation for VT",
        "rationale": (
            "Under-explored direction with high paper value. Only 3/1142 entries are "
            "behavioral. Prospect theory model of VT could be a standalone paper. "
            "VIX overreaction hypothesis is testable with current data."
        ),
        "action": "VIX vs realized vol bias test. Prospect theory VT model.",
        "blocking": "METHODS (can start now)",
    },
    {
        "rank": 5,
        "question_id": "OQ-A3",
        "title": "Gold inverted leverage: historical verification with pre-2005 data",
        "rationale": (
            "Our most novel finding. If confirmed with 50-year data, strengthens Paper 1 "
            "significantly. If refuted, need to revise conclusions."
        ),
        "action": "Obtain COMEX/LBMA gold data 1970-2005. Run gamma analysis.",
        "blocking": "DATA (need historical gold prices, likely available)",
    },
    {
        "rank": 6,
        "question_id": "OQ-D1",
        "title": "Foundation models / transformers for volatility",
        "rationale": (
            "High-reward but uncertain. If PatchTST or in-context learning works, "
            "it's a paradigm shift. Previous ML attempts failed but were unsophisticated."
        ),
        "action": "Implement PatchTST vol forecasting. Test TimeGPT/Chronos on vol data.",
        "blocking": "METHODS + COMPUTE (can start now)",
    },
    {
        "rank": 7,
        "question_id": "OQ-E1",
        "title": "Daily vs monthly rebalancing: empirical TX cost measurement",
        "rationale": (
            "Practical importance for investors. Three conflicting experiments. "
            "Resolution is purely empirical (measure actual costs)."
        ),
        "action": "Paper trading with actual limit orders for 1 month. Measure fill quality.",
        "blocking": "DATA (need live trading data, ~1 month)",
    },
    {
        "rank": 8,
        "question_id": "OQ-A4",
        "title": "QLIKE-VT utility disconnect: theoretical framework",
        "rationale": (
            "Academic contribution. Explains why better vol models don't always "
            "mean better strategies. Could be a standalone theoretical paper."
        ),
        "action": "Derive formal utility-based evaluation framework. Connect to K130/K137.",
        "blocking": "THEORY (can start now)",
    },
]

# =============================================================================
# META-STATISTICS
# =============================================================================

meta_stats = {
    "total_knowledge_entries": 1142,
    "total_experiments": "300+",
    "total_null_results": 179,
    "total_self_corrections": 12,
    "null_rate": "~44% (in late phase)",
    "categories": {
        "A_answerable_better_methods": len(category_a),
        "B_answerable_more_data": len(category_b),
        "C_fundamentally_difficult": len(category_c),
        "D_blind_spots_unexplored": len(category_d),
        "E_contradictory_evidence": len(category_e),
    },
    "total_open_questions": (
        len(category_a) + len(category_b) + len(category_c) +
        len(category_d) + len(category_e)
    ),
    "top_3_under_explored_areas": [
        "Behavioral finance (3/1142 entries = 0.26%)",
        "Multivariate models (2/1142 entries = 0.18%)",
        "Causal inference (0 dedicated experiments)",
    ],
    "key_insight": (
        "After 300 experiments, the research frontier has two clear edges: "
        "(1) HIGHER FREQUENCY DATA — 5-min RV is the single most promising path "
        "to improve volatility prediction; "
        "(2) DEEPER THEORY — behavioral, causal, and utility-based frameworks "
        "to explain WHY our findings hold, not just WHAT they are."
    ),
}

# =============================================================================
# ASSEMBLE FINAL OUTPUT
# =============================================================================

results = {
    "experiment_id": "K302",
    "title": "What We Still Don't Know — The Open Questions After 300 Experiments",
    "date": datetime.now().isoformat(),
    "methodology": "Synthesis of 1142 knowledge entries across 300+ experiments",
    "data_source": "storage/memory/knowledge.json (no new computation)",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "category_A_answerable_better_methods": category_a,
    "category_B_answerable_more_data": category_b,
    "category_C_fundamentally_difficult": category_c,
    "category_D_blind_spots_unexplored": category_d,
    "category_E_contradictory_evidence": category_e,
    "priority_ranking": priority_ranking,
    "meta_statistics": meta_stats,
    "conclusion": (
        "24 genuinely open questions identified across 5 categories. "
        "The single most important direction is 5-min realized volatility data "
        "accumulation (OQ-B1), which could unlock HAR-RV and Realized GARCH — "
        "the only approaches with strong theoretical and empirical reasons to "
        "break the daily QLIKE ceiling. For near-term actionable research, "
        "CAViaR (OQ-A5) and behavioral VT (OQ-D5) offer the best reward-to-effort "
        "ratio with currently available data. The 5 contradictory findings (Category E) "
        "should be resolved before any new paper submission."
    ),
}

# Save
output_path = "experiments/k302_open_questions_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print("=" * 80)
print("K302: WHAT WE STILL DON'T KNOW")
print("=" * 80)

print(f"\nTotal open questions: {meta_stats['total_open_questions']}")
print(f"  Category A (better methods needed): {len(category_a)}")
print(f"  Category B (more data needed):      {len(category_b)}")
print(f"  Category C (fundamentally hard):     {len(category_c)}")
print(f"  Category D (blind spots):            {len(category_d)}")
print(f"  Category E (contradictory evidence): {len(category_e)}")

print("\n" + "=" * 80)
print("PRIORITY RANKING FOR NEXT RESEARCH PHASE")
print("=" * 80)
for p in priority_ranking:
    print(f"\n  #{p['rank']}: {p['title']}")
    print(f"       [{p['blocking']}]")
    print(f"       {p['rationale'][:120]}...")

print("\n" + "=" * 80)
print("KEY INSIGHT")
print("=" * 80)
print(f"\n{meta_stats['key_insight']}")

print("\n" + "=" * 80)
print("TOP UNDER-EXPLORED AREAS")
print("=" * 80)
for area in meta_stats["top_3_under_explored_areas"]:
    print(f"  - {area}")

print("\n" + "=" * 80)
print("CATEGORY A: ANSWERABLE WITH BETTER METHODS (5)")
print("=" * 80)
for q in category_a:
    print(f"\n  [{q['id']}] {q['question']}")
    print(f"    Importance: {q['importance']}")
    print(f"    Resolvability: {q['confidence_resolvable']:.0%}")
    print(f"    Timeline: {q['estimated_timeline']}")

print("\n" + "=" * 80)
print("CATEGORY B: ANSWERABLE WITH MORE DATA (5)")
print("=" * 80)
for q in category_b:
    print(f"\n  [{q['id']}] {q['question']}")
    print(f"    Importance: {q['importance']}")
    print(f"    Resolvability: {q['confidence_resolvable']:.0%}")
    print(f"    Timeline: {q['estimated_timeline']}")

print("\n" + "=" * 80)
print("CATEGORY C: FUNDAMENTALLY DIFFICULT (5)")
print("=" * 80)
for q in category_c:
    print(f"\n  [{q['id']}] {q['question']}")
    print(f"    Importance: {q['importance']}")
    print(f"    Resolvability: {q['confidence_resolvable']:.0%}")
    print(f"    Timeline: {q['estimated_timeline']}")

print("\n" + "=" * 80)
print("CATEGORY D: BLIND SPOTS / UNEXPLORED (6)")
print("=" * 80)
for q in category_d:
    print(f"\n  [{q['id']}] {q['question']}")
    print(f"    Importance: {q['importance']}")
    print(f"    Exploration: {q['exploration_status']}")
    print(f"    Resolvability: {q['confidence_resolvable']:.0%}")

print("\n" + "=" * 80)
print("CATEGORY E: CONTRADICTORY EVIDENCE (3)")
print("=" * 80)
for q in category_e:
    print(f"\n  [{q['id']}] {q['question']}")
    print(f"    Importance: {q['importance']}")
    print(f"    Contradiction: {q['contradiction'][:150]}...")

print(f"\nResults saved to: {output_path}")
