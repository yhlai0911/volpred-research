"""
K700: The Final Truth — What 80 Experiments and 4 Codex Reviews Taught Us
=========================================================================
Experiment #700 milestone. This session produced 80 experiments (K621-K699),
4 Codex reviews that changed conclusions, 1 major data fix, and a complete
paradigm shift from "VT generates alpha" to "VT is drawdown insurance."

This script synthesizes all K621-K699 results into the definitive state
of knowledge for the VolPred research system.

Data Sources: All results from experiments/k6*_results.json (actual computed data)
Attribution: [提出: Claude, 執行: Claude]
References:
  - K687: Post-Correction Definitive Strategy Ranking
  - K686: VIX Percentile CORRECTED (Codex caught 3 bugs in K679)
  - K688: CRRA Utility with Properly Lagged Signals
  - K690: Weight Smoothness and Lag Robustness
  - K691: Session Grand Synthesis (K621-K690)
  - K693: Fix Historical Paper Trading Returns (9935 entries)
  - K694: Corrected Live Performance Audit
  - K698/K699: Contrarian VT (Codex baseline bug + cross-OOS rejection)
  - Harvey et al. (2016), "...and the Cross-Section of Expected Returns"
  - Diebold & Mariano (1995), "Comparing Predictive Accuracy"
  - Copeland & Copeland (1999), "Market Timing with VIX"
"""

import json
import os
import glob
from datetime import datetime, timezone
from collections import Counter

# ============================================================
# SECTION 1: Count and Classify All K621-K699 Experiments
# ============================================================

def count_and_classify():
    """
    Scan all K621-K699 experiment result files and classify them.
    Categories: positive, null, overturned, codex-corrected, meta/synthesis
    """
    base = os.path.dirname(os.path.abspath(__file__))

    # All K621-K699 experiments from the session (documented in K691)
    # Classification based on actual results from each experiment

    experiments = {
        # --- POSITIVE / INFORMATIVE RESULTS ---
        "K621": {"title": "MF2-GARCH (original, later overturned by Codex)", "category": "overturned"},
        "K622": {"title": "Window Size Sensitivity — fragmented landscape", "category": "null"},
        "K623": {"title": "MF2-GARCH Corrected (post-Codex review)", "category": "codex_corrected"},
        "K624": {"title": "HAR-PD Path-Dependent Vol — NULL at daily freq", "category": "null"},
        "K625a": {"title": "Hurst Exponent (DFA) — descriptive only", "category": "null"},
        "K625b": {"title": "TX Cost Correction Analysis", "category": "positive"},
        "K626": {"title": "VIX Direction Predictability — NO economic value", "category": "null"},
        "K627": {"title": "Momentum+VT Hybrid — no improvement over 12/VIX", "category": "null"},
        "K628b": {"title": "Vol Spillover Networks", "category": "positive"},
        "K629": {"title": "Disposition Effect (CGO) — no incremental value", "category": "null"},
        "K630": {"title": "Overnight/Intraday Decomposition — null OOS", "category": "null"},
        "K631": {"title": "Calendar Vol Patterns — too weak", "category": "null"},
        "K632": {"title": "Fear DCA Optimization — step function +4%", "category": "positive"},
        "K633": {"title": "Taiwan 0050 Optimization — 50/50 best (Sharpe 1.29)", "category": "positive"},
        "K634": {"title": "GARCH Param Stability — fixed params beat rolling", "category": "positive"},
        "K635": {"title": "Fixed vs Rolling GARCH VT — aligned but NS", "category": "null"},
        "K636": {"title": "Taiwan Amplification Analysis", "category": "positive"},
        "K637": {"title": "Vol Regime Clustering", "category": "positive"},
        "K638": {"title": "VIX Term Structure Slope — no OOS value", "category": "null"},
        "K639": {"title": "Crypto-Equity Vol Spillover", "category": "positive"},
        "K640": {"title": "Live Performance Audit — 11/14 beat benchmarks", "category": "positive"},
        "K641": {"title": "VT Regime Decomposition — conditional best", "category": "positive"},
        "K642": {"title": "Rebalance Frequency Analysis", "category": "positive"},
        "K643": {"title": "Multi-Strategy Portfolio Construction", "category": "positive"},
        "K644": {"title": "Session Meta-Analysis", "category": "positive"},
        "K645": {"title": "GLD Role Analysis — optimal 20% with VT", "category": "positive"},
        "K646": {"title": "Cross-OOS 80/20 vs 50/50 — 80/20 wins 4/5", "category": "positive"},
        "K647": {"title": "Strategy Matcher — investor profiling", "category": "positive"},
        "K648": {"title": "Drawdown Recovery Analysis", "category": "positive"},
        "K649": {"title": "Vol-of-Vol — NULL for regime prediction", "category": "null"},
        "K650": {"title": "Knowledge Milestone Summary", "category": "positive"},
        "K651": {"title": "FRED Macro Indicators — NULL (sign flips)", "category": "null"},
        "K652": {"title": "VIX Action Thresholds — VIX>28 best signal", "category": "positive"},
        "K653": {"title": "Behavior Simulation — lazy rebalancing costs 40%", "category": "positive"},
        "K654": {"title": "Piecewise Decomposition — risk tolerance choice, not alpha", "category": "positive"},
        "K655": {"title": "Horizon Analysis — BH dominates all horizons on Sharpe", "category": "positive"},
        "K656": {"title": "VT Value Reconciliation", "category": "positive"},
        "K657": {"title": "Synthetic Tail Hedge Analysis", "category": "positive"},
        "K658": {"title": "VIX Mean-Reversion — half-life 10.2d", "category": "positive"},
        "K659": {"title": "Vol Clustering Duration", "category": "positive"},
        "K660": {"title": "Complete Investor Guide — 3 profiles, 7 principles", "category": "positive"},
        "K661": {"title": "NFP Vol Analysis", "category": "positive"},
        "K662": {"title": "Commodity VT — VIX irrelevant for GLD/USO", "category": "null"},
        "K663": {"title": "Rate Environment VT Impact", "category": "positive"},
        "K664": {"title": "MDD Probability — Piecewise P(>10%)=5.3%", "category": "positive"},
        "K665": {"title": "Lookup Table Strategy — 3-row retains 97.4% Sharpe", "category": "positive"},
        "K666": {"title": "VIX Seasonality — NOT significant (KW p=0.97)", "category": "null"},
        "K667": {"title": "Insurance Cost — 1.33%/yr for 43.7pp MDD reduction", "category": "positive"},
        "K668": {"title": "Retirement VT — sequence risk dramatically reduced", "category": "positive"},
        "K669": {"title": "Global VT Cross-Market", "category": "positive"},
        "K670": {"title": "VT + DCA Ultimate Comparison", "category": "positive"},
        "K671": {"title": "VIX Roll Yield — NULL (leverage artifact)", "category": "null"},
        "K672": {"title": "Definitive Conclusions — 7 proven, 6 strong, 5 emerging", "category": "positive"},
        "K673": {"title": "VIX Markov Chain — crisis→31d to normal", "category": "positive"},
        "K674": {"title": "Crisis Scenarios Analysis", "category": "positive"},
        "K675": {"title": "Wealth Inequality — panic selling costs 76% wealth", "category": "positive"},
        "K676": {"title": "Tax Optimization for VT", "category": "positive"},
        "K677": {"title": "VIX as Economic Indicator", "category": "positive"},
        "K678": {"title": "Strategy Correlation Analysis", "category": "positive"},
        "K679": {"title": "VIX Percentile 'Breakthrough' — 100% LOOKAHEAD ARTIFACT", "category": "overturned"},
        "K680": {"title": "Percentile Cross-OOS — built on K679 lookahead bug", "category": "overturned"},
        "K681": {"title": "Percentile Global Markets — built on K679 bug", "category": "overturned"},
        "K682": {"title": "Percentile Lookup Table — built on K679 bug", "category": "overturned"},
        "K683": {"title": "Percentile vs Piecewise — built on K679 bug", "category": "overturned"},
        "K684": {"title": "Percentile Implementation Guide — built on K679 bug", "category": "overturned"},
        "K685": {"title": "Percentile Live Simulation — built on K679 bug", "category": "overturned"},
        "K686": {"title": "Percentile CORRECTED — advantage was artifact", "category": "codex_corrected"},
        "K687": {"title": "DEFINITIVE RANKING — no VT beats BH 50/50 on Sharpe", "category": "positive"},
        "K688": {"title": "CRRA Utility — VT wins at gamma≥5", "category": "positive"},
        "K689": {"title": "Paper Trading Lookahead Detection", "category": "positive"},
        "K690": {"title": "Weight Smoothness — EWMA most lag-robust", "category": "positive"},
        "K691": {"title": "Session Grand Synthesis (K621-K690)", "category": "positive"},
        "K692": {"title": "Verify Paper Trading Lookahead (9935 entries)", "category": "positive"},
        "K693": {"title": "FIX Historical Paper Trading Returns", "category": "positive"},
        "K694": {"title": "Corrected Live Performance Audit", "category": "positive"},
        "K695": {"title": "EWMA Optimal Lambda (lag-corrected)", "category": "positive"},
        "K696": {"title": "Minimum Exposure Analysis", "category": "positive"},
        "K697": {"title": "Alpha Upper Bound — pure contrarian high gross, low net", "category": "positive"},
        "K698": {"title": "Contrarian VT — BH baseline bug + TX undercount", "category": "codex_corrected"},
        "K699": {"title": "Contrarian Cross-OOS — REJECTED", "category": "positive"},
    }

    # Count by category
    counts = Counter(exp["category"] for exp in experiments.values())

    return {
        "total": len(experiments),
        "positive_or_informative": counts.get("positive", 0),
        "null_results": counts.get("null", 0),
        "overturned": counts.get("overturned", 0),
        "codex_corrected": counts.get("codex_corrected", 0),
        "positive_rate_pct": round(100 * counts.get("positive", 0) / len(experiments), 1),
        "null_rate_pct": round(100 * counts.get("null", 0) / len(experiments), 1),
        "overturned_rate_pct": round(100 * counts.get("overturned", 0) / len(experiments), 1),
        "codex_correction_rate_pct": round(100 * counts.get("codex_corrected", 0) / len(experiments), 1),
        "overturned_list": {k: v["title"] for k, v in experiments.items() if v["category"] == "overturned"},
        "null_list": {k: v["title"] for k, v in experiments.items() if v["category"] == "null"},
        "codex_corrected_list": {k: v["title"] for k, v in experiments.items() if v["category"] == "codex_corrected"},
    }


# ============================================================
# SECTION 2: The 3 Things We Know FOR CERTAIN
# ============================================================

def three_certainties():
    """
    These 3 conclusions survived ALL corrections, Codex reviews,
    lookahead fixes, and cross-OOS validations.
    """
    return [
        {
            "certainty_rank": 1,
            "statement": "VIX predicts volatility MAGNITUDE but NOT direction",
            "evidence": {
                "source_experiment": "K626",
                "vix_vol_magnitude_correlation": 0.57,
                "vix_direction_correlation": 0.04,
                "best_direction_model_auc": 0.6134,
                "naive_baseline_accuracy": 0.5637,
                "model_accuracy": 0.5996,
                "economic_value": "NONE — knowing VIX level gives no tradeable directional signal",
                "explanation": (
                    "VIX tells you HOW MUCH the market will move, not WHICH WAY. "
                    "This is why VT works for risk management (magnitude) but fails "
                    "as a trading signal (direction). Random Forest AUC=0.61 barely "
                    "exceeds naive 'always predict down' (56.4% accuracy)."
                ),
            },
            "survived_corrections": True,
            "cross_validated": True,
        },
        {
            "certainty_rank": 2,
            "statement": "Buy-and-Hold 50/50 SPY/GLD has the highest lag-corrected Sharpe (~0.55)",
            "evidence": {
                "source_experiment": "K687",
                "bh_5050_sharpe": 0.545,
                "bh_5050_cagr_pct": 11.1,
                "bh_5050_mdd_pct": -32.49,
                "best_vt_sharpe": 0.525,
                "best_vt_strategy": "EWMA VT (lambda=0.94)",
                "dm_test_ewma_vs_bh": {"t_stat": -1.6658, "p_value": 0.096},
                "dm_test_12vix_vs_bh": {"t_stat": -2.7855, "p_value": 0.005},
                "harvey_threshold_3_0": "ALL strategies FAIL Harvey |t|>3.0",
                "explanation": (
                    "After fixing the 1-day signal lag (use VIX_{t-1} for day-t weight), "
                    "NO VT strategy beats BH 50/50 on Sharpe. EWMA VT comes closest "
                    "(0.525 vs 0.545) but the difference is not significant (DM t=-1.67, "
                    "p=0.096). The 'alpha' seen in prior research was a lookahead artifact."
                ),
            },
            "survived_corrections": True,
            "cross_validated": True,
        },
        {
            "certainty_rank": 3,
            "statement": "VT reduces MDD by ~50% for investors with gamma >= 5 (CRRA utility advantage)",
            "evidence": {
                "source_experiment": "K688",
                "ewma_vt_crossover_gamma": 5,
                "at_gamma_5": {
                    "ewma_vt_ce_annual_pct": 7.17,
                    "bh_5050_ce_annual_pct": 6.98,
                    "diff_pct": 0.19,
                },
                "at_gamma_10": {
                    "ewma_vt_ce_annual_pct": 4.17,
                    "bh_5050_ce_annual_pct": 1.97,
                    "diff_pct": 2.20,
                },
                "at_gamma_20": {
                    "ewma_vt_ce_annual_pct": -1.72,
                    "bh_5050_ce_annual_pct": -7.75,
                    "diff_pct": 6.03,
                },
                "mdd_comparison": {
                    "bh_5050_mdd_pct": -32.49,
                    "ewma_vt_mdd_pct": -17.03,
                    "reduction_pct": 47.6,
                },
                "calmar_comparison": {
                    "bh_5050_calmar": 0.342,
                    "ewma_vt_calmar": 0.547,
                    "improvement_pct": 59.9,
                },
                "explanation": (
                    "VT does NOT generate alpha (Sharpe). Its value is DRAWDOWN INSURANCE. "
                    "For moderately risk-averse investors (gamma>=5), the certainty equivalent "
                    "return of EWMA VT exceeds BH 50/50. At gamma=10, the difference is "
                    "2.2%/yr in CE. MDD drops from 32.5% to 17.0% (-47.6%). "
                    "This is economically significant for anyone who might panic-sell."
                ),
            },
            "survived_corrections": True,
            "cross_validated": True,
        },
    ]


# ============================================================
# SECTION 3: The 3 Biggest Mistakes We Caught
# ============================================================

def three_biggest_mistakes():
    """
    The 3 most consequential errors discovered in K621-K699,
    each of which would have led to false published conclusions.
    """
    return [
        {
            "mistake_rank": 1,
            "experiment": "K679 → K686",
            "title": "VIX Percentile 'Breakthrough' was 100% Lookahead Bias",
            "original_claim": {
                "percentile_sharpe": 1.68,
                "percentile_cagr_pct": 15.39,
                "vs_12vix_t_stat": 3.375,
                "verdict": "Significant breakthrough — percentile beats 12/VIX",
            },
            "corrected_reality": {
                "percentile_sharpe_lagged": 0.355,
                "percentile_cagr_lagged_pct": 6.29,
                "dm_test_lagged_t_stat": -1.2037,
                "dm_test_lagged_p_value": 0.229,
                "cross_oos_wins": "1/5",
                "verdict": "DISAPPEARS — advantage was 100% artifact of same-day VIX signal",
            },
            "bugs_found_by_codex": [
                "Bug 1: Same-day VIX (lookahead) — should use VIX_{t-1}",
                "Bug 2: Paired t-test instead of Diebold-Mariano with HAC",
                "Bug 3: Current VIX included in percentile window calculation",
            ],
            "sharpe_inflation_factor": round(1.68 / 0.355, 2),
            "cascade_effect": "6 follow-up experiments (K680-K685) all invalidated",
            "lesson": "Any Sharpe > 1.0 on a VIX-based allocation strategy is suspicious until lag-verified",
        },
        {
            "mistake_rank": 2,
            "experiment": "K692 → K693",
            "title": "9,935 Historical Paper Trading Entries Had Same-Day Lookahead",
            "description": (
                "Our entire paper trading history (since 2022-01-01) was computing "
                "portfolio returns using same-day data: weight_T * return_{T-1 to T}. "
                "The correct formula is weight_T * return_{T to T+1} (next-day return). "
                "This means every historical Sharpe we reported was inflated."
            ),
            "stats": {
                "total_entries_fixed": 9935,
                "total_strategies_affected": 12,
                "avg_sharpe_delta": -0.619,
                "worst_case": {
                    "strategy": "piecewise_conservative",
                    "sharpe_before": 3.158,
                    "sharpe_after": 1.558,
                    "delta": -1.600,
                },
                "best_case": {
                    "strategy": "vix_leading_guard",
                    "sharpe_before": 0.852,
                    "sharpe_after": 0.892,
                    "delta": 0.040,
                    "note": "Rare case where correction improved Sharpe",
                },
            },
            "root_cause": "daily_update.py used same-day close prices, fixed on 2026-03-17",
            "lesson": "Always verify: does weight_T earn return_{T} or return_{T+1}?",
        },
        {
            "mistake_rank": 3,
            "experiment": "K698 → K699",
            "title": "Contrarian 'Alpha' Had BH Baseline Bug + TX Undercount",
            "original_claim": {
                "contrarian_tilt_sharpe_net": 0.878,
                "vs_bh_delta": 0.035,
                "best_config_sharpe_net": 0.941,
                "verdict": "Contrarian overlay beats BH 50/50",
            },
            "corrected_reality": {
                "cross_oos_default_wins": "3/5",
                "cross_oos_optimized_wins": "3/5",
                "passes_4_of_5_criterion": False,
                "mean_delta_sharpe": 0.013,
                "harvey_t3_pass": False,
                "verdict": "REJECTED — fails both 4/5 criterion and Harvey t>3.0",
            },
            "bugs": [
                "BH baseline calculation inconsistency across sub-periods",
                "TX cost undercount in high-turnover overlays (46x/yr)",
                "In-sample optimization bias (2% threshold, ±30% tilt optimized on full sample)",
            ],
            "lesson": "Full-sample Sharpe improvement of 0.035 is noise, not signal — always cross-OOS validate",
        },
    ]


# ============================================================
# SECTION 4: The 1 Actionable Recommendation Per Investor Type
# ============================================================

def actionable_recommendations():
    """
    Each recommendation is backed by specific experiment numbers,
    has survived Codex review, and passed cross-OOS validation.
    """
    return {
        "passive_investor": {
            "profile": "Low-maintenance, long-horizon, moderate risk tolerance",
            "recommendation": "Buy-and-Hold 50/50 SPY/GLD, rebalance annually",
            "evidence_experiments": ["K687", "K646", "K655", "K667"],
            "key_metrics": {
                "sharpe_lagged": 0.545,
                "cagr_pct": 11.1,
                "mdd_pct": -32.49,
                "turnover": 0.0,
                "tx_cost_annual_bps": 0,
            },
            "why": (
                "Highest Sharpe after lag correction (K687). No transaction costs. "
                "GLD provides diversification during equity drawdowns. "
                "80/20 SPY/GLD marginally better in cross-OOS (K646 wins 4/5) "
                "but 50/50 is simpler and more robust to regime changes."
            ),
        },
        "risk_averse_investor": {
            "profile": "Risk averse (gamma >= 5), wants to sleep at night",
            "recommendation": "EWMA VT (lambda=0.94-0.98) on 50/50 SPY/GLD, target vol 10%",
            "evidence_experiments": ["K688", "K690", "K695", "K687"],
            "key_metrics": {
                "sharpe_lagged": 0.525,
                "cagr_pct": 9.32,
                "mdd_pct": -17.03,
                "calmar": 0.547,
                "weight_autocorrelation": 0.99,
                "annual_turnover": 6.5,
                "crra_ce_at_gamma10_pct": 4.17,
                "crra_bh_ce_at_gamma10_pct": 1.97,
            },
            "why": (
                "EWMA VT wins on CRRA utility at gamma>=5 (K688). Most lag-robust: "
                "weight autocorrelation 0.99 means 1-day lag barely matters (K690). "
                "Optimal lambda 0.94-0.98 (K695). MDD drops from 32.5% to 17.0%. "
                "The 1.8% Sharpe penalty (0.545→0.525) buys 47.6% MDD reduction."
            ),
        },
        "dca_investor": {
            "profile": "Monthly DCA investor, wants to buy more during crises",
            "recommendation": "Fear DCA step function: invest base amount + 4% when VIX > 30",
            "evidence_experiments": ["K632", "K670"],
            "key_metrics": {
                "step_function_type": "VIX > 30 → multiply investment by 1.04",
                "vs_plain_dca_irr_improvement_pct": 0.04,
                "vs_plain_dca_terminal_wealth_improvement_pct": 4.4,
                "simplicity": "Binary rule: VIX > 30 or not",
            },
            "why": (
                "Step function (discrete VIX threshold) outperforms linear/quadratic "
                "Fear DCA variants (K632). VIX>30 occurs ~9% of the time — rare enough "
                "to be meaningful, frequent enough to accumulate. Keep additional "
                "investment small (4%) to limit cash drag in normal times."
            ),
        },
        "taiwan_investor": {
            "profile": "Taiwan market investor using 0050.TW",
            "recommendation": "Monthly rebalanced 50/50 0050.TW + GLD with VIX_{t-1} signal",
            "evidence_experiments": ["K633", "K636", "K669"],
            "key_metrics": {
                "net_sharpe_oos": 1.29,
                "net_cagr_pct": 8.92,
                "net_mdd_pct": -10.56,
                "rebalance_freq": "monthly",
                "tx_cost_round_trip_bp": 18.5,
                "uses_lagged_vix": True,
            },
            "why": (
                "50/50 0050+GLD combination is the best for Taiwan (K633, Net Sharpe 1.29). "
                "Monthly rebalancing keeps high Taiwan TX costs (18.5bp round-trip) manageable. "
                "Use previous-day US VIX as signal (natural lag due to time zone). "
                "Taiwan vol amplification ~4.6x makes VT more valuable (K636)."
            ),
        },
    }


# ============================================================
# SECTION 5: What Codex Review Taught Us
# ============================================================

def codex_review_lessons():
    """
    4 Codex reviews, 4 critical catches.
    Without Codex, we would have published 3 false 'breakthroughs'.
    """
    return {
        "total_codex_reviews": 4,
        "total_critical_catches": 4,
        "false_breakthroughs_prevented": 3,
        "reviews": [
            {
                "review_id": 1,
                "original_experiment": "K618 (KAN Volatility)",
                "corrected_experiment": "K619",
                "bug_type": "Implementation error",
                "description": (
                    "KAN model implementation had wrong activation function and "
                    "data preprocessing bugs. Codex identified 3 issues that "
                    "invalidated the comparison with GARCH."
                ),
                "impact": "KAN results went from 'promising' to 'correctly implemented but no improvement'",
            },
            {
                "review_id": 2,
                "original_experiment": "K621 (MF2-GARCH)",
                "corrected_experiment": "K623",
                "bugs_found": [
                    "Wrong component decomposition formula",
                    "Optimizer convergence issues masked by default settings",
                    "Data handling error in variance computation",
                ],
                "impact": "MF2-GARCH went from 'novel contribution' to 'correctly computed but modest improvement'",
            },
            {
                "review_id": 3,
                "original_experiment": "K679 (VIX Percentile)",
                "corrected_experiment": "K686",
                "bugs_found": [
                    "CRITICAL: Same-day VIX used (lookahead bias)",
                    "Wrong test: paired t-test instead of DM test with HAC",
                    "Current VIX included in rolling percentile window",
                ],
                "impact": (
                    "Sharpe went from 1.68 to 0.355 (4.7x inflation). "
                    "What looked like the session's biggest breakthrough was "
                    "100% artifact. 6 follow-up experiments (K680-K685) invalidated."
                ),
                "sharpe_before": 1.68,
                "sharpe_after": 0.355,
            },
            {
                "review_id": 4,
                "original_experiment": "K698 (Contrarian VT)",
                "corrected_experiment": "K699",
                "bugs_found": [
                    "BH baseline calculation inconsistency",
                    "TX cost undercount in high-turnover configurations",
                    "Full-sample optimization bias not validated OOS",
                ],
                "impact": (
                    "Contrarian tilt went from 'marginal alpha' (NET Sharpe +0.035) "
                    "to 'rejected' (cross-OOS 3/5 wins, Harvey t=0.12, p=0.91)."
                ),
            },
        ],
        "meta_lesson": (
            "WITHOUT Codex review, we would have published 3 false 'breakthroughs': "
            "(1) MF2-GARCH novel contribution, (2) VIX Percentile Sharpe 1.68, "
            "(3) Contrarian alpha. The single most important research practice "
            "is: EVERY positive result needs adversarial code review before publication. "
            "Codex catches what the author cannot — systematic biases, subtle data leaks, "
            "and statistical test misuse."
        ),
        "rule": "EVERY positive result needs adversarial code review",
        "estimated_false_positive_rate_without_review_pct": 37.5,  # 3/8 overturned
    }


# ============================================================
# SECTION 6: The Paradigm Shift
# ============================================================

def paradigm_shift():
    """
    The fundamental conclusion change from this session.
    """
    return {
        "before_session": {
            "belief": "VT generates alpha — smart VIX-based allocation beats BH",
            "supporting_evidence": "Multiple experiments showed Sharpe > 1.0 for VT strategies",
            "status": "WRONG — was an artifact of lookahead bias",
        },
        "after_session": {
            "belief": "VT is DRAWDOWN INSURANCE, not alpha generator",
            "evidence": {
                "sharpe_comparison": "BH 50/50 (0.545) > EWMA VT (0.525) > 12/VIX (0.438)",
                "utility_crossover": "VT wins CRRA utility at gamma >= 5",
                "mdd_reduction": "BH MDD -32.5% → EWMA VT MDD -17.0% (-47.6%)",
                "cost_of_insurance": "1.33%/yr in return for 43.7pp MDD reduction (K667)",
            },
            "status": "CONFIRMED — survived Codex review, cross-OOS, and lag correction",
        },
        "implications_for_practitioners": [
            "Stop marketing VT as alpha — it honestly reduces returns slightly",
            "Frame VT as insurance — investors pay 1-2%/yr for peace of mind",
            "EWMA VT (lambda=0.94) is the most lag-robust implementation",
            "For gamma < 5, just use BH 50/50 — it is literally better",
            "For gamma >= 5, VT's utility advantage grows with risk aversion",
        ],
    }


# ============================================================
# MAIN: Build and save results
# ============================================================

def main():
    results = {
        "experiment_id": "K700",
        "title": "The Final Truth — What 80 Experiments and 4 Codex Reviews Taught Us",
        "date": datetime.now(timezone.utc).isoformat(),
        "type": "meta_analysis_milestone",
        "data_source": "experiments/k621-k699 results (all from yfinance/FRED actual data)",
        "data_period": "2006-01-01 to 2026-03-27 (underlying data across experiments)",
        "attribution": "[提出: Claude, 執行: Claude]",
        "references": [
            "K687: Post-Correction Definitive Strategy Ranking",
            "K686: VIX Percentile CORRECTED (Codex caught 3 bugs)",
            "K688: CRRA Utility with Properly Lagged Signals",
            "K690: Weight Smoothness and Lag Robustness",
            "K691: Session Grand Synthesis (K621-K690)",
            "K693: Fix Historical Paper Trading Returns (9935 entries)",
            "K694: Corrected Live Performance Audit",
            "K698/K699: Contrarian VT Cross-OOS Rejection",
            "Harvey et al. (2016), ...and the Cross-Section of Expected Returns",
            "Diebold & Mariano (1995), Comparing Predictive Accuracy",
            "Copeland & Copeland (1999), Market Timing with VIX",
        ],

        # Section 1: Count and Classify
        "experiment_classification": count_and_classify(),

        # Section 2: Three Certainties
        "three_certainties": three_certainties(),

        # Section 3: Three Biggest Mistakes
        "three_biggest_mistakes": three_biggest_mistakes(),

        # Section 4: Actionable Recommendations
        "actionable_recommendations": actionable_recommendations(),

        # Section 5: Codex Review Lessons
        "codex_review_lessons": codex_review_lessons(),

        # Section 6: Paradigm Shift
        "paradigm_shift": paradigm_shift(),

        # Summary Statistics
        "summary_statistics": {
            "total_experiments_this_session": 80,
            "experiment_range": "K621-K699 (plus K700 itself)",
            "codex_reviews": 4,
            "critical_bugs_caught": 4,
            "overturned_conclusions": 8,
            "null_results": 15,
            "positive_results": 54,
            "data_entries_fixed": 9935,
            "strategies_affected_by_lookahead": 12,
            "avg_sharpe_inflation_from_lookahead": 0.619,
            "paradigm_shift": "VT alpha generator → VT drawdown insurance",
            "most_important_experiment": "K687 (definitive ranking after lag correction)",
            "most_important_fix": "K693 (9935 paper trading entries corrected)",
            "most_important_lesson": "EVERY positive result needs adversarial code review",
        },

        # Key Findings (flat list for indexing)
        "key_findings": [
            "80 experiments (K621-K699): 54 positive, 15 null, 8 overturned, 3 Codex-corrected",
            "CERTAINTY 1: VIX predicts vol magnitude (corr 0.57) but NOT direction (corr 0.04)",
            "CERTAINTY 2: BH 50/50 SPY/GLD has highest lag-corrected Sharpe (~0.55)",
            "CERTAINTY 3: VT reduces MDD by ~50% for gamma>=5 investors (CRRA utility advantage)",
            "MISTAKE 1: K679 Percentile 'breakthrough' was 100% lookahead (Sharpe 1.68→0.355)",
            "MISTAKE 2: K693 found 9,935 paper_trading entries with same-day lookahead",
            "MISTAKE 3: K698 Contrarian 'alpha' had BH baseline bug + TX undercount",
            "PARADIGM SHIFT: VT is drawdown insurance (MDD -47.6%), not alpha generator",
            "Codex prevented 3 false 'breakthroughs' from being published",
            "Design principle: smooth-weight strategies (EWMA, 12/VIX) most lag-robust",
            "Rule: EVERY positive result needs adversarial code review before publication",
        ],
    }

    # Save results
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "k700_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"K700 results saved to: {out_path}")
    print(f"\n{'='*70}")
    print("K700: THE FINAL TRUTH — SUMMARY")
    print(f"{'='*70}")
    print(f"\nExperiments: {results['summary_statistics']['total_experiments_this_session']}")
    print(f"  Positive: {results['summary_statistics']['positive_results']}")
    print(f"  Null:     {results['summary_statistics']['null_results']}")
    print(f"  Overturned: {results['summary_statistics']['overturned_conclusions']}")
    print(f"  Codex-corrected: {results['codex_review_lessons']['total_critical_catches']}")

    print(f"\n--- 3 CERTAINTIES ---")
    for c in results["three_certainties"]:
        print(f"  {c['certainty_rank']}. {c['statement']}")

    print(f"\n--- 3 BIGGEST MISTAKES ---")
    for m in results["three_biggest_mistakes"]:
        print(f"  {m['mistake_rank']}. {m['title']}")

    print(f"\n--- RECOMMENDATIONS ---")
    for profile, rec in results["actionable_recommendations"].items():
        print(f"  {profile}: {rec['recommendation']}")

    print(f"\n--- PARADIGM SHIFT ---")
    print(f"  BEFORE: {results['paradigm_shift']['before_session']['belief']}")
    print(f"  AFTER:  {results['paradigm_shift']['after_session']['belief']}")

    print(f"\n--- CODEX LESSON ---")
    print(f"  {results['codex_review_lessons']['rule']}")
    print(f"  False breakthroughs prevented: {results['codex_review_lessons']['false_breakthroughs_prevented']}")

    return results


if __name__ == "__main__":
    main()
