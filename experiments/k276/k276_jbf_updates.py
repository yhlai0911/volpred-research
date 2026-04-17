"""
K276: JBF Paper Section Updates — Integrating Session Findings into Paper 1

Experiment type: SYNTHESIS (no new data computation)
Paper: paper/leverage-direction/main.tex (JBF: Leverage Direction Matters)
Current state: ~60 pages, 7 figures, 12+ tables, 3 contributions
Estimated novel content: ~70% (per K274 assessment)

This file maps recent research findings to specific paper sections,
identifies gaps, and prioritizes updates.
"""

import json

# =============================================================================
# 1. PAPER STRUCTURE AUDIT
# =============================================================================

PAPER_STRUCTURE = {
    "section_1": {
        "title": "Introduction",
        "location": "body.tex lines 3-19",
        "current_contributions": [
            "C1: Leverage direction taxonomy (gamma sign -> model selection)",
            "C2: Gamma-mechanism mapping (gamma -> VT alpha channel)",
            "C3: Time-zone arbitrage (US -> Asia momentum)"
        ],
        "status": "COMPLETE — well-written, 3 clear contributions",
        "page_count_est": 3,
    },
    "section_2": {
        "title": "Literature Review",
        "location": "body.tex lines 23-60",
        "subsections": [
            "2.1 GARCH Models and the Leverage Effect",
            "2.2 Commodity Volatility and Inverted Asymmetry",
            "2.3 Value-at-Risk and Basel III",
            "2.4 Volatility Targeting",
            "2.5 Deep Learning for Volatility Forecasting"
        ],
        "status": "COMPLETE — comprehensive references",
        "page_count_est": 5,
    },
    "section_3": {
        "title": "Data and Methodology",
        "location": "body.tex lines 63-143",
        "subsections": [
            "3.1 Data (7 primary assets, 2017-2025)",
            "3.2 Volatility Models (GARCH, GJR-GARCH)",
            "3.3 Rolling Estimation (w=504 primary)",
            "3.4 Evaluation Criteria (QLIKE, DM, VaR, VT)",
            "3.5 Volatility Targeting"
        ],
        "status": "COMPLETE",
        "page_count_est": 5,
    },
    "section_4": {
        "title": "Empirical Results",
        "location": "body.tex lines 146-410",
        "subsections": [
            "4.1 Data Characteristics",
            "4.2 Leverage Direction Across Asset Classes",
            "4.3 GARCH vs. GJR-GARCH: Forecasting Comparison",
            "4.4 VaR Compliance: Distribution Choice Dominates",
            "4.5 Volatility Targeting Across Leverage Regimes",
            "4.6 The QLIKE Ceiling (from additions_jk.tex)",
            "4.7 Formal Market Timing Tests (from additions_jk.tex)",
            "4.8 Real-Time Crisis Validation: 2026 Iran Episode"
        ],
        "status": "MOSTLY COMPLETE — see update opportunities below",
        "page_count_est": 20,
    },
    "section_5": {
        "title": "Discussion",
        "location": "body.tex lines 413-578",
        "subsections": [
            "5.1 The Economics of Inverted Leverage",
            "5.2 Diversification Amplifies Leverage",
            "5.3 Conditional Leverage: Regime Dependence",
            "5.4 Implications for Risk Management Practice",
            "5.5 Proposition: Gamma-Mechanism Mapping",
            "5.6 VT as Volatility Insurance",
            "5.7 Cross-Asset VT Applicability",
            "5.8 Practical Implementation: Implied-VT",
            "5.9 The Complexity Ceiling",
            "5.10 Limitations and Future Directions"
        ],
        "status": "COMPLETE but could benefit from new robustness evidence",
        "page_count_est": 18,
    },
    "section_6": {
        "title": "Conclusion",
        "location": "body.tex lines 582-593",
        "status": "COMPLETE — summarizes 3 contributions",
        "page_count_est": 2,
    },
    "appendix_a": {
        "title": "Commodity Extension",
        "location": "body.tex lines 596-617",
        "status": "COMPLETE",
        "page_count_est": 2,
    },
    "appendix_b": {
        "title": "Time-Zone Information Transmission",
        "location": "body.tex lines 619-651",
        "status": "COMPLETE — includes c2c vs o2o caveat",
        "page_count_est": 2,
    },
    "appendix_c": {
        "title": "Practical Implementation Summary",
        "location": "body.tex lines 653-end",
        "status": "COMPLETE",
        "page_count_est": 1,
    },
}


# =============================================================================
# 2. FINDINGS-TO-SECTION MAPPING
# =============================================================================

FINDING_MAPPINGS = [
    # ------------------------------------------------------------------
    # PRIORITY 1: Strengthens C1 (Leverage Direction Taxonomy)
    # ------------------------------------------------------------------
    {
        "finding_id": "K207_VIX_BOUNDARY_PANEL",
        "knowledge_ids": ["a7aaae29"],
        "title": "VIX Boundary Conditions for Gamma-Mechanism (12 Assets)",
        "target_section": "5.5 (Proposition: Gamma-Mechanism Mapping)",
        "target_subsection": "Robustness and Boundary Conditions",
        "priority": 1,
        "already_in_paper": True,
        "current_coverage": (
            "Section 5.5 already reports: within equity (N=6) rho=0.886 (p=0.019), "
            "cross-all (N=12) rho=-0.448 (p=0.14 NS). Also reports extension to "
            "N=17 (rho=0.874) and N=26 (rho=0.753). The boundary condition is well-documented."
        ),
        "proposed_addition": (
            "No major addition needed. The paper already handles this finding comprehensively "
            "in Section 5.5 body.tex lines 484-488. The key result — gamma predicts within "
            "homogeneous equities but MDD improvement is universal — is correctly stated."
        ),
        "table_figure_needed": None,
        "additional_analysis": None,
        "impact_assessment": "LOW — already well-covered in current manuscript",
    },
    {
        "finding_id": "K228_GAMMA_TRENDING",
        "knowledge_ids": ["7dc85de2"],
        "title": "Gamma Declining Over Time (-53%) but VT Effectiveness Stable",
        "target_section": "5.3 (Conditional Leverage: Regime Dependence)",
        "target_subsection": "After 'conditional on volatility regime' discussion",
        "priority": 2,
        "already_in_paper": "PARTIAL",
        "current_coverage": (
            "Section 5.3 (body.tex line 427) discusses gamma's relationship with vol regime "
            "(slope=-0.36, p=0.02) but does NOT discuss the secular decline in SPY gamma "
            "(0.33 -> 0.20) or its implication for VT robustness. The related knowledge entry "
            "(id=a7aaae29) mentions 'SPY declining 0.33->0.20' but the paper doesn't elaborate."
        ),
        "proposed_addition": (
            "Add 2-3 sentences to Section 5.3 after the conditional leverage paragraph: "
            "'A notable secular trend is the decline of SPY gamma from approximately 0.33 "
            "(2010-2015) to 0.20 (2020-2025), a -39% reduction. Despite this substantial "
            "decline, VT effectiveness shows no corresponding deterioration: the Sharpe "
            "differential between VT and buy-and-hold is statistically constant across six "
            "sub-periods (range: -0.44 to +0.06, no trend), and MaxDD improvement is positive "
            "in 5 of 6 periods (+5.9pp to +19.6pp). This confirms that VT's primary benefit "
            "is vol-of-vol driven, not gamma-level driven, consistent with Proposition 1's "
            "distinction between the directional (gamma-dependent) and non-directional "
            "(gamma-independent) channels.'"
        ),
        "table_figure_needed": "Optional: Add gamma time-trend panel to Fig 1 (rolling gamma)",
        "additional_analysis": (
            "The rolling gamma figure (fig_rolling_gamma.pdf) already shows the decline "
            "visually. Could add a formal trend test (OLS regression of gamma on time) "
            "to quantify the -53% decline with p-value."
        ),
        "impact_assessment": "MEDIUM — strengthens the 'VT is robust' narrative and directly "
                             "addresses a potential reviewer concern about parameter instability",
    },
    # ------------------------------------------------------------------
    # PRIORITY 2: Strengthens C2 (VT Economic Channel)
    # ------------------------------------------------------------------
    {
        "finding_id": "K269_CORRELATION_REGIME",
        "knowledge_ids": ["830fb764"],
        "title": "VIX Regime -> Tail Correlation Shift: 50/50 SPY/GLD Robust",
        "target_section": "5.3 (Conditional Leverage: Regime Dependence)",
        "target_subsection": "After SPY-TLT correlation break discussion",
        "priority": 2,
        "already_in_paper": "PARTIAL",
        "current_coverage": (
            "Section 5.3 already notes SPY-TLT correlation changed from -0.42 to +0.09 "
            "post-2022 (Fisher z=-13.58, p<0.0001). BUT it does NOT report the critical "
            "finding that SPY-GLD correlation remains approximately zero across ALL VIX "
            "regimes, nor the tail correlation data (crisis SPY-QQQ=0.96, SPY-GLD~0, "
            "SPY-TLT=-0.48). The sentence 'SPY-GLD tail correlation remains approximately "
            "zero across all VIX regimes' IS in the paper at line 429, but without the "
            "detailed regime-stratified numbers."
        ),
        "proposed_addition": (
            "Expand the SPY-GLD mention at body.tex line 429 into a short paragraph: "
            "'We verify this stability by stratifying correlations across VIX regimes. "
            "SPY-QQQ correlation rises from 0.85 (VIX<15) to 0.96 during crises—near-"
            "perfect comovemement that eliminates diversification precisely when needed. "
            "SPY-TLT correlation inverts from -0.10 to -0.48, enhancing its hedge quality "
            "in crises but undermined by the post-2022 regime break. In contrast, SPY-GLD "
            "correlation remains anchored near zero across all regimes (range: -0.05 to "
            "+0.04), confirming that gold's diversification benefit is regime-invariant. "
            "This finding provides the economic rationale for the 50/50 SPY/GLD portfolio "
            "recommendation in Section 5.8.'"
        ),
        "table_figure_needed": (
            "Table: 'Tail and Conditional Correlation by VIX Regime' — 4 pairs x 3 regimes "
            "(Low VIX <15, Normal 15-25, Crisis >25) showing correlation, tail correlation "
            "(bottom 5th percentile), and portfolio vol reduction."
        ),
        "additional_analysis": None,
        "impact_assessment": "HIGH — directly supports 50/50 recommendation with regime evidence, "
                             "addresses reviewer concern about static allocation robustness",
    },
    {
        "finding_id": "K271_GLD_SELF_HEALING",
        "knowledge_ids": ["c20da2ed"],
        "title": "GLD GARCH Recovery After Flash Crash: Half-life=17d, 90% Decay=55d",
        "target_section": "4.2.4 (Robustness) or 5.1 (Economics of Inverted Leverage)",
        "target_subsection": "After regime-dependent leverage discussion",
        "priority": 3,
        "already_in_paper": False,
        "current_coverage": (
            "The paper mentions the Jan 30 2026 gold flash crash (-10.27%) in Section 4.5.3 "
            "(body.tex line 297) but only as a single data point illustrating why VT's risk "
            "reduction matters for gold. The GARCH recovery dynamics (peak sigma=72.8%, "
            "half-life=17d, 90% decay=55d, persistence adaptation 0.94->0.97->gradual return) "
            "are NOT discussed."
        ),
        "proposed_addition": (
            "Add to Section 5.1 (Economics of Inverted Leverage), after the existing discussion "
            "of regime-dependent leverage: "
            "'The January 2026 gold flash crash (-10.27% in one day) provides a natural "
            "experiment for the GARCH model's adaptation to extreme events. The GJR-GARCH "
            "conditional volatility peaked at 72.8% annualized (Feb 4), with an empirical "
            "half-life of 17 trading days and 90% decay of 55 days. The persistence parameter "
            "adapted endogenously: pre-crash alpha+beta=0.94 rose to 0.97 during the shock "
            "absorption period, before gradually reverting. This self-correcting behavior "
            "demonstrates that GARCH models handle extreme events without manual intervention, "
            "a practical advantage for automated VT implementations.'"
        ),
        "table_figure_needed": (
            "Optional figure: GLD conditional volatility time series around Jan 2026 flash crash, "
            "showing peak, half-life, and 90% decay markers."
        ),
        "additional_analysis": (
            "Formal shock-decay regression: log(sigma_t - sigma_pre) on t to estimate "
            "exponential decay rate. Compare with theoretical half-life implied by "
            "alpha+beta parameter."
        ),
        "impact_assessment": "MEDIUM — adds practical credibility to the model, shows GARCH "
                             "handles tail events gracefully, useful for practitioner audience",
    },
    {
        "finding_id": "K273_CRASH_TAXONOMY",
        "knowledge_ids": ["e8e069f7", "1fd0be4b"],
        "title": "VT Crisis Protection is Type-Agnostic: 10/10 Crises, Avg +8.7pp",
        "target_section": "4.8 (Real-Time Crisis Validation) and 5.9 (Complexity Ceiling)",
        "target_subsection": "Extend Table: crisis-by-crisis protection",
        "priority": 1,
        "already_in_paper": "PARTIAL",
        "current_coverage": (
            "Section 4.8 (body.tex line 409) mentions '10 identifiable crisis episodes from "
            "2008 to 2026' with protection scaling by severity. Figure 5 (fig_mdd_comparison.pdf) "
            "shows 7 crises visually. BUT the paper does not present the complete taxonomy: "
            "COVID +23.5pp, GFC +16.3pp, 2022 Rate +10.9pp, EU Debt +9.4pp, 2018 Q4 +8.4pp, "
            "Lib Day +5.7pp, Flash Crash +4.7pp, 2018 Vol +3.1pp, China +2.7pp, Iran +2.0pp. "
            "Nor does it classify crises by TYPE (financial, pandemic, geopolitical, monetary)."
        ),
        "proposed_addition": (
            "Add a formal crisis taxonomy table to Section 5.4.3 (VT: Universal Risk Management): "
            "'Table X reports VT drawdown protection across ten identifiable crises spanning four "
            "distinct types: financial (GFC, EU Debt), pandemic (COVID-19), monetary (2018 Q4, "
            "2022 Rate Hike), and geopolitical (China 2015, Lib Day 2016, 2018 Vol Spike, Flash "
            "Crash 2010, Iran 2026). The protection is type-agnostic: average drawdown improvement "
            "is +8.7pp with protection in 10 of 10 events. Protection magnitude scales with crisis "
            "severity (VIX peak), not crisis type. This universality confirms that VT operates as "
            "a variance-management mechanism rather than a crisis-type-specific hedge, consistent "
            "with the market timing null results of Section 4.7.'"
        ),
        "table_figure_needed": (
            "NEW TABLE: 'VT Crisis Protection Taxonomy' — columns: Crisis, Date, Type, "
            "VIX Peak, B&H MDD, VT MDD, Protection (pp). 10 rows. This is one of the "
            "most impactful additions for a JBF audience."
        ),
        "additional_analysis": (
            "Formal test: Kruskal-Wallis or ANOVA comparing protection across 4 crisis types. "
            "Expected result: p > 0.05 (no significant type effect), confirming type-agnostic nature."
        ),
        "impact_assessment": "HIGH — systematic crisis analysis with taxonomy is exactly what "
                             "JBF reviewers want. Connects VT literature to crisis literature. "
                             "Strengthens the 'universal risk management' claim.",
    },
    # ------------------------------------------------------------------
    # PRIORITY 3: Robustness Section Additions
    # ------------------------------------------------------------------
    {
        "finding_id": "K149_REGIME_ICL_NULL",
        "knowledge_ids": ["429388c6"],
        "title": "Regime-Aware In-Context Learning: GARCH Ceiling Confirmed",
        "target_section": "4.5 (GARCH Forecasting Ceiling) and Table 8 (Null Results)",
        "target_subsection": "Add to comprehensive null results table",
        "priority": 3,
        "already_in_paper": False,
        "current_coverage": (
            "Table 8 (table_nulls.tex) already lists 25 null results across 3 categories. "
            "The ICL approach (non-parametric regime matching with cosine similarity on "
            "standardized features) is NOT listed. It's a notable null because it represents "
            "a fundamentally different approach (non-parametric, data-driven) that still "
            "fails to beat GJR-GARCH."
        ),
        "proposed_addition": (
            "Add one row to Table 8 (Prediction accuracy section): "
            "'Regime-aware ICL | QLIKE | +0.36-0.41% worse | Non-parametric regime matching "
            "(K=10-100, cosine sim) cannot improve on GARCH's parametric structure.' "
            "Also add a sentence to Section 4.5: 'Even non-parametric approaches—such as "
            "regime-aware in-context learning, which matches current market conditions to "
            "historical analogs using cosine similarity on standardized features (RV at "
            "multiple horizons, return momentum, vol-of-vol, VIX level)—fail to improve "
            "upon GJR-GARCH (best ICL QLIKE is 0.36-0.41% worse across 16 configurations, "
            "3 assets), confirming that the GARCH structure is not merely a convenient "
            "parameterization but captures the relevant dynamics.'"
        ),
        "table_figure_needed": "Add 1 row to existing Table 8",
        "additional_analysis": None,
        "impact_assessment": "MEDIUM — adds a genuinely novel null result (ICL/LLM-era method) "
                             "to the already impressive null results table",
    },
    {
        "finding_id": "VT_INSURANCE_PRICING_CORRECTION",
        "knowledge_ids": ["60e390ca"],  # K31 and related K41-K91 series
        "title": "VT Insurance Premium ~1%/yr (76-Year Average), Not 4%/yr",
        "target_section": "5.6 (VT as Volatility Insurance)",
        "target_subsection": "Revise the ~4%/year figure",
        "priority": 2,
        "already_in_paper": "NEEDS REVISION",
        "current_coverage": (
            "Section 5.6 (body.tex line 495-500) states 'The wealth cost is approximately "
            "constant at ~4% per annum' and 'the VT/B&H wealth ratio at horizon T is 0.96^T'. "
            "BUT K41-K91 research series found the 76-year average is ~1%/yr, with VIX-era "
            "(1990+) being 2-4%/yr. The ~4% figure is VIX-era specific and overstates the "
            "long-run cost. The premium is also highly unstable (std=2.54%)."
        ),
        "proposed_addition": (
            "Revise Section 5.6 to: 'The long-run insurance premium averages approximately "
            "1% per annum over the full 76-year sample (1950-2025), rising to 2-4% during "
            "the VIX era (1990-2025). The premium is highly variable (standard deviation "
            "2.54%), reflecting the inherent unpredictability of crisis frequency. Crucially, "
            "MDD protection is positive in 8 of 8 decades tested, including decades where "
            "the wealth cost exceeded 5%. The investor's decision thus depends on drawdown "
            "aversion (lambda in Equation 6), not on the point estimate of the premium.'"
        ),
        "table_figure_needed": (
            "Optional: Decade-by-decade VT insurance premium table (8 decades, showing "
            "premium, MDD improvement, and whether VT dominated by utility)."
        ),
        "additional_analysis": (
            "Need to verify the exact premium figures from K41-K91 experiments. "
            "The current 4%/yr may need to be recalculated with the corrected methodology."
        ),
        "impact_assessment": "HIGH — correcting an overstatement is critical for research "
                             "integrity. A reviewer familiar with long-run VT costs would "
                             "flag the 4%/yr as too high.",
    },
    {
        "finding_id": "EWMA_CRISIS_DIVERGENCE",
        "knowledge_ids": ["7dc85de2"],
        "title": "EWMA vs GJR Crisis Advantage (J5-J9 Arc)",
        "target_section": "4.5.4 (EWMA as Parsimonious Alternative)",
        "target_subsection": "Already in paper",
        "priority": 4,
        "already_in_paper": True,
        "current_coverage": (
            "Section 4.5.4 (body.tex lines 299-308) already covers: EWMA(0.97) matches GJR "
            "in Sharpe (DM p=0.73) but GJR wins MDD in 4-5/5 OOS periods. The crisis-period "
            "divergence (COVID Sharpe 1.130 vs 0.745), the mechanism (gamma triggers faster "
            "deleveraging), and the smoothness hypothesis refutation (rho=-0.007) are all "
            "well-documented."
        ),
        "proposed_addition": None,
        "table_figure_needed": None,
        "additional_analysis": None,
        "impact_assessment": "LOW — already well-covered",
    },
    {
        "finding_id": "K14_253_START_DATES",
        "knowledge_ids": [],
        "title": "253 Starting Dates -> 100% MDD Win Rate for VT",
        "target_section": "5.5 (Proposition) or 5.6 (VT Insurance)",
        "target_subsection": "Bootstrap robustness",
        "priority": 3,
        "already_in_paper": "IMPLICIT",
        "current_coverage": (
            "Section 5.8 reports MDD bootstrap p=0.0004 with 10,000 replications. "
            "The specific 253-starting-date result (testing EVERY possible start date "
            "over 1 year, finding 100% positive MDD improvement) is NOT explicitly stated, "
            "but the bootstrap result is stronger evidence."
        ),
        "proposed_addition": (
            "Add one sentence to Section 5.8 after the bootstrap result: "
            "'As a further robustness check, we initialize the VT strategy at each of the "
            "253 possible start dates within a calendar year: maximum drawdown improvement "
            "is positive for all 253 start dates, confirming that VT's protective benefit "
            "is not an artifact of a favorable starting point.'"
        ),
        "table_figure_needed": None,
        "additional_analysis": None,
        "impact_assessment": "LOW-MEDIUM — simple but compelling robustness check",
    },
    {
        "finding_id": "COMPLEXITY_CEILING_EXTENSION",
        "knowledge_ids": ["a5e93cf1"],
        "title": "CCS Score: 52% of Models Provide Zero/Negative Value",
        "target_section": "5.9 (The Complexity Ceiling)",
        "target_subsection": "Already in paper as Table 7",
        "priority": 4,
        "already_in_paper": True,
        "current_coverage": (
            "Section 5.9 and Table 7 (complexity_ceiling) already present the complexity "
            "ceiling with 9 specific tests. The CCS (Complexity Ceiling Score) metric with "
            "31 models is referenced in CLAUDE.md but not in the paper. Adding all 31 would "
            "be excessive; the current 9-test summary is more focused."
        ),
        "proposed_addition": (
            "Optional: add one sentence noting that 'of 31 alternative approaches tested "
            "across three evaluation dimensions, 52% provide zero or negative value relative "
            "to the baseline GJR + Student-t(5) + 12/VIX system.'"
        ),
        "table_figure_needed": None,
        "additional_analysis": None,
        "impact_assessment": "LOW — current coverage is already effective",
    },
]


# =============================================================================
# 3. PRIORITY RANKING
# =============================================================================

PRIORITY_RANKING = [
    {
        "rank": 1,
        "finding": "K273_CRASH_TAXONOMY",
        "section": "5.4 + new table",
        "rationale": (
            "Systematic crisis taxonomy (10 crises x 4 types) is the single most "
            "impactful addition. JBF reviewers will expect cross-crisis validation, and "
            "the type-agnostic finding directly strengthens the 'VT as universal risk "
            "management' claim. Requires new table (easy to produce from existing data)."
        ),
        "effort": "LOW — data exists, just needs formatting",
        "impact": "HIGH",
    },
    {
        "rank": 2,
        "finding": "VT_INSURANCE_PRICING_CORRECTION",
        "section": "5.6",
        "rationale": (
            "Correcting the ~4%/yr insurance premium to ~1%/yr (76-year average) is "
            "essential for research integrity. An informed reviewer would flag this. "
            "The correction actually STRENGTHENS the paper: VT is cheaper than claimed."
        ),
        "effort": "MEDIUM — need to verify exact numbers from K41-K91",
        "impact": "HIGH (integrity)",
    },
    {
        "rank": 3,
        "finding": "K269_CORRELATION_REGIME",
        "section": "5.3",
        "rationale": (
            "The regime-stratified correlation table provides the economic foundation "
            "for the 50/50 SPY/GLD recommendation. Shows GLD's uniqueness: zero "
            "correlation across ALL VIX regimes, unlike TLT which broke post-2022."
        ),
        "effort": "LOW — add a few sentences expanding existing text",
        "impact": "HIGH (supports portfolio recommendation)",
    },
    {
        "rank": 4,
        "finding": "K228_GAMMA_TRENDING",
        "section": "5.3",
        "rationale": (
            "Addresses parameter instability concern. The fact that VT works despite "
            "-53% gamma decline is a strong robustness argument. Pairs well with the "
            "existing rolling gamma figure."
        ),
        "effort": "LOW — 2-3 sentences",
        "impact": "MEDIUM",
    },
    {
        "rank": 5,
        "finding": "K149_REGIME_ICL_NULL",
        "section": "4.5 + Table 8",
        "rationale": (
            "Adding a non-parametric (ICL/LLM-era) null result to the comprehensive "
            "null table strengthens the GARCH ceiling argument. Shows we tested "
            "cutting-edge methods, not just legacy models."
        ),
        "effort": "LOW — 1 table row + 1-2 sentences",
        "impact": "MEDIUM",
    },
    {
        "rank": 6,
        "finding": "K271_GLD_SELF_HEALING",
        "section": "5.1",
        "rationale": (
            "Practical credibility for automated VT: GARCH handles extreme events "
            "without manual intervention. Half-life and decay analysis add quantitative "
            "rigor. Less critical for JBF but valuable for practitioner appeal."
        ),
        "effort": "LOW — 3-4 sentences",
        "impact": "MEDIUM-LOW",
    },
    {
        "rank": 7,
        "finding": "K14_253_START_DATES",
        "section": "5.8",
        "rationale": "Simple robustness check, one sentence. Low impact but easy.",
        "effort": "TRIVIAL",
        "impact": "LOW",
    },
]


# =============================================================================
# 4. GAP ANALYSIS — What the Paper Still Needs
# =============================================================================

GAPS = [
    {
        "gap_id": "G1",
        "description": "Crisis Taxonomy Table missing",
        "severity": "HIGH",
        "resolution": "Create Table from K273 data (10 crises, 4 types, VIX peak, MDD improvement)",
    },
    {
        "gap_id": "G2",
        "description": "VT insurance premium overstated (~4%/yr should be ~1%/yr long-run)",
        "severity": "HIGH",
        "resolution": "Revise Section 5.6 with K41-K91 corrected figures",
    },
    {
        "gap_id": "G3",
        "description": "Regime-stratified correlation numbers mentioned but not tabulated",
        "severity": "MEDIUM",
        "resolution": "Add regime correlation table or expand text in Section 5.3",
    },
    {
        "gap_id": "G4",
        "description": "Gamma secular decline not discussed",
        "severity": "MEDIUM",
        "resolution": "Add 2-3 sentences to Section 5.3 about -53% decline + VT stability",
    },
    {
        "gap_id": "G5",
        "description": "ICL null result not in Table 8",
        "severity": "LOW",
        "resolution": "Add 1 row to table_nulls.tex",
    },
    {
        "gap_id": "G6",
        "description": "GLD flash crash GARCH recovery dynamics undocumented",
        "severity": "LOW",
        "resolution": "Add paragraph to Section 5.1 about half-life and persistence adaptation",
    },
    {
        "gap_id": "G7",
        "description": "TZ momentum c2c vs o2o — missing o2o data for HK/AU/SG/KR",
        "severity": "MEDIUM",
        "resolution": (
            "Table B1 shows '---' for o2o Sharpe of HK, AU, SG, KR. "
            "Either compute o2o or add note explaining data limitation."
        ),
    },
]


# =============================================================================
# 5. OVERALL ASSESSMENT
# =============================================================================

ASSESSMENT = {
    "paper_current_quality": (
        "The paper is already strong: 60 pages, comprehensive empirical results across "
        "7 primary + 26 validation assets, formal statistical tests, crisis validation, "
        "and a well-articulated complexity ceiling. The three contributions are clear "
        "and well-supported."
    ),
    "novelty_percentage": 70,  # per K274
    "novelty_breakdown": {
        "C1_leverage_taxonomy": "HIGHLY NOVEL — first systematic cross-asset gamma taxonomy",
        "C2_gamma_mechanism": "NOVEL — extends Hood & Raughtigan (2025) to non-equity",
        "C3_timezone_arbitrage": "MODERATE — information transmission is known, but "
                                 "Harvey t>3.0 across 6 markets is new",
        "complexity_ceiling": "NOVEL — 25+ null results as unified argument is unique",
        "VT_insurance": "MODERATE — extends Moreira & Muir with cross-asset evidence",
    },
    "biggest_risks": [
        "C3 (TZ arbitrage) may be flagged as not implementable (o2o fails Harvey) — "
        "but the paper already has the caveat at body.tex lines 625-626",
        "VT insurance premium 4%/yr needs correction to avoid overstating cost",
        "Specification search (110+ experiments) creates data mining concern — "
        "but FDR audit (30/32 survive) addresses this",
    ],
    "recommended_action_before_submission": [
        "1. Add crisis taxonomy table (Rank 1, ~1 hour work)",
        "2. Correct VT insurance premium (Rank 2, ~30 min verification + edit)",
        "3. Expand correlation regime text (Rank 3, ~20 min)",
        "4. Add gamma secular decline discussion (Rank 4, ~15 min)",
        "5. Add ICL null to Table 8 (Rank 5, ~10 min)",
        "6. Final pass: verify all statistics match knowledge.json entries",
    ],
}


# =============================================================================
# 6. OUTPUT
# =============================================================================

def main():
    """Print structured summary of K276 findings."""
    output = {
        "experiment_id": "K276",
        "title": "JBF Paper Section Updates — Integrating Session Findings",
        "type": "SYNTHESIS",
        "paper": "paper/leverage-direction/main.tex",
        "paper_structure": PAPER_STRUCTURE,
        "finding_mappings": FINDING_MAPPINGS,
        "priority_ranking": PRIORITY_RANKING,
        "gaps": GAPS,
        "assessment": ASSESSMENT,
    }

    # Summary statistics
    n_mappings = len(FINDING_MAPPINGS)
    n_already_covered = sum(1 for m in FINDING_MAPPINGS if m["already_in_paper"] is True)
    n_partial = sum(1 for m in FINDING_MAPPINGS if m["already_in_paper"] == "PARTIAL")
    n_needs_revision = sum(1 for m in FINDING_MAPPINGS if m["already_in_paper"] == "NEEDS REVISION")
    n_new = sum(1 for m in FINDING_MAPPINGS if m["already_in_paper"] is False)

    print("=" * 70)
    print("K276: JBF Paper Section Updates — Summary")
    print("=" * 70)
    print(f"\nTotal findings mapped: {n_mappings}")
    print(f"  Already well-covered: {n_already_covered}")
    print(f"  Partially covered:    {n_partial}")
    print(f"  Needs revision:       {n_needs_revision}")
    print(f"  Not in paper:         {n_new}")
    print(f"\nGaps identified: {len(GAPS)}")
    print(f"  HIGH severity: {sum(1 for g in GAPS if g['severity'] == 'HIGH')}")
    print(f"  MEDIUM:        {sum(1 for g in GAPS if g['severity'] == 'MEDIUM')}")
    print(f"  LOW:           {sum(1 for g in GAPS if g['severity'] == 'LOW')}")

    print(f"\nPriority ranking for paper updates:")
    for item in PRIORITY_RANKING:
        print(f"  #{item['rank']}: {item['finding']} -> {item['section']} "
              f"[effort={item['effort']}, impact={item['impact']}]")

    print(f"\nAssessment: {ASSESSMENT['novelty_percentage']}% novel content")
    print(f"Recommended actions before submission:")
    for action in ASSESSMENT["recommended_action_before_submission"]:
        print(f"  {action}")

    # Save full output as JSON
    with open("experiments/k276_jbf_updates_results.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nFull results saved to experiments/k276_jbf_updates_results.json")


if __name__ == "__main__":
    main()
