"""
K377: The Complete Decision Framework — When Should You Use WHAT?
================================================================
[提出: 用戶, 執行: Claude]

SYNTHESIS experiment — no new data computation.
Integrates ALL research findings (K1-K376, 195 experiments, 978 knowledge entries)
into a single actionable decision tree for retail investors.

Data sources: All results from existing experiments using real market data
(yfinance SPY/GLD/SHY/TLT/QQQ/BTC/0050.TW/VIX, period 2008-2026).

Methodology: Binary decision tree synthesis. Every node references the specific
experiment that established the branching criterion. Every number is traceable
to a prior experiment's output.

Limitations:
- All backtest results are in-sample or single-OOS unless noted
- Sharpe ratios have SE ≈ 1/sqrt(N_years), so 10yr Sharpe SE ≈ 0.32
- Past performance does not guarantee future results
- Transaction costs assumed at modern brokerage rates (0-2 bps)
- Tax treatment varies by jurisdiction
"""

import json
import sys
from datetime import datetime

print("=" * 78)
print("K377: THE COMPLETE DECISION FRAMEWORK")
print("When Should You Use WHAT? — Synthesizing 195 Experiments")
print("=" * 78)

# ======================================================================
# SECTION 1: THE MASTER DECISION TREE
# ======================================================================

decision_tree = {
    "metadata": {
        "experiment_id": "K377",
        "title": "The Complete Decision Framework",
        "created": datetime.now().isoformat(),
        "based_on": "195 experiments, 978 knowledge entries",
        "data_period": "2008-2026 (varies by experiment)",
        "data_sources": "yfinance (SPY, GLD, SHY, TLT, QQQ, BTC, 0050.TW, ^VIX)",
        "attribution": "[提出: 用戶, 執行: Claude]",
    },

    # ======================================================================
    # DECISION NODE Q1: LIFE STAGE
    # ======================================================================
    "Q1_life_stage": {
        "question": "Are you accumulating wealth or withdrawing?",
        "why_this_matters": (
            "K39 Lifecycle Paradox: VT has OPPOSITE effects in accumulation vs withdrawal. "
            "During accumulation with DCA, drawdowns are buying opportunities (you buy cheap). "
            "VT's cash position makes you MISS those cheap prices. "
            "During withdrawal, drawdowns force you to sell at lows (sequence-of-returns risk). "
            "VT prevents forced selling at lows."
        ),
        "evidence": "K39: DCA+VT terminal wealth -55.9% vs B&H; K79: VT withdrawal survival 100% vs 96.3%",

        "branch_A_accumulating": {
            "label": "Accumulating (working years, saving)",
            "goto": "Q2_accumulating_method",
        },
        "branch_B_withdrawing": {
            "label": "Withdrawing (retired, spending down)",
            "goto": "Q3_drawdown_tolerance",
        },
    },

    # ======================================================================
    # DECISION NODE Q2: ACCUMULATION METHOD
    # ======================================================================
    "Q2_accumulating_method": {
        "question": "How are you investing — lump sum or monthly contributions (DCA)?",
        "why_this_matters": (
            "N172: DCA already provides time diversification. Pure DCA MDD is only -22.5% "
            "(vs lump sum -80%). Adding VT on top of DCA gives only 4.2pp more MDD "
            "improvement at a cost of 118pp less return. DCA and VT are substitutes, not complements."
        ),
        "evidence": "N172: DCA return 297.8% vs DCA+VT 179.6%; K31: DCA+VT MDD -5.4% vs DCA -14.5%",

        "branch_A_DCA": {
            "label": "Monthly DCA (salary savings)",
            "recommendation": {
                "strategy": "50/50 SPY/GLD Buy & Hold with monthly DCA",
                "details": (
                    "Just buy 50% SPY + 50% GLD every month. No VT needed. "
                    "DCA itself smooths entry prices and reduces timing risk. "
                    "VT on top of DCA costs -30% terminal wealth for only -4pp MDD improvement."
                ),
                "implementation": [
                    "Split monthly savings: 50% into SPY, 50% into GLD",
                    "Rebalance annually to restore 50/50 (or when drift >10pp)",
                    "Do NOT check VIX. Do NOT adjust positions.",
                    "Continue for 20+ years.",
                ],
                "expected_metrics": {
                    "source": "K2/K16/K19/J1 (8 independent validations)",
                    "note": "50/50 SPY/GLD is the hardest-to-beat monthly baseline",
                },
                "why_no_VT": "K39: VT costs -55.9% terminal wealth during accumulation. DCA already provides behavioral protection (buying dips).",
                "why_no_QQQ": "QQQ tail dependence with SPY: lambda_L = 0.82. Adding QQQ = making one concentrated bet on US tech (Q21).",
                "why_GLD": "SPY-GLD correlation ~0.03 (near zero). Diversification benefit 42% (portfolio VaR is 58% of naive sum). GLD value is risk reduction, not return.",
                "why_not_TLT": "TLT crashed -54.8% in 2022 rate hiking cycle. In rising rate environments, TLT is a LIABILITY, not a hedge (N82, N169).",
            },
            "goto": "Q4_location",
        },

        "branch_B_lump_sum": {
            "label": "Lump sum (inheritance, bonus, windfall)",
            "recommendation": {
                "strategy": "50/50 SPY/GLD + 12/VIX monthly rebalancing + SHY as cash",
                "details": (
                    "This is the ONLY scenario where VT clearly adds value during accumulation. "
                    "With a lump sum, you can't dollar-cost-average into dips. "
                    "VT protects the principal from catastrophic drawdowns."
                ),
                "implementation": [
                    "Step 1: Check VIX (free on any financial site)",
                    "Step 2: Calculate equity_weight = min(12 / VIX, 1.0)",
                    "Step 3: Split equity portion 50/50 between SPY and GLD",
                    "Step 4: Put remainder in SHY (1-3yr US Treasury ETF)",
                    "Step 5: Rebalance monthly (1st trading day of month)",
                    "Example: VIX=20 → equity=60% (30% SPY + 30% GLD) + 40% SHY",
                    "Example: VIX=12 → equity=100% (50% SPY + 50% GLD) + 0% SHY",
                    "Example: VIX=36 → equity=33% (17% SPY + 17% GLD) + 67% SHY",
                ],
                "expected_metrics": {
                    "sharpe": 0.826,
                    "calmar": 0.77,
                    "mdd": "-15.5%",
                    "covid_drawdown": "-8.9% (vs B&H -33.8%)",
                    "source": "Q21 optimal retail portfolio (2008-2026)",
                },
                "transaction_cost": "Monthly rebal: ~0.10%/yr drag. Net Sharpe 0.792 (J10).",
                "why_12": "12 is not cherry-picked. Targets 6-20 all work. 12 gives target ~12% annual vol (N79).",
                "why_SHY_not_TLT": "SHY MDD -23.7% vs TLT MDD -37.6%. TLT has interest rate risk that CANCELS VT protection (N82, N169).",
                "why_monthly": "Monthly Sharpe 0.697 > Daily 0.610. Less whipsaw, lower TX cost (50981d0e).",
            },
            "goto": "Q4_location",
        },
    },

    # ======================================================================
    # DECISION NODE Q3: WITHDRAWAL — DRAWDOWN TOLERANCE
    # ======================================================================
    "Q3_drawdown_tolerance": {
        "question": "How much portfolio drawdown can you tolerate?",
        "why_this_matters": (
            "K79: In withdrawal, VT is not just insurance — it has POSITIVE NPV. "
            "Avoiding drawdowns means not being forced to sell at lows (sequencing bonus). "
            "VT doubles the safe withdrawal rate from 4% to 8%. "
            "N115: At risk aversion gamma=10 (typical retiree), B&H utility is NEGATIVE. "
            "VT certainty equivalent = +1.26% vs B&H = -3.21%."
        ),
        "evidence": "K79: 4% SWR survival B&H 96.3% → VT 100%; Max SWR: B&H 4% → VT 8%",

        "branch_A_moderate": {
            "label": "Can tolerate -25% (moderate risk tolerance)",
            "recommendation": {
                "strategy": "50/50 SPY/GLD + 12/VIX monthly + SHY",
                "details": "Same as lump-sum accumulation strategy. MDD -15.5% with full VT protection.",
                "expected_metrics": {
                    "sharpe": 0.826,
                    "mdd": "-15.5%",
                    "swr_95_survival": "8%",
                    "source": "Q21 + K79",
                },
            },
        },

        "branch_B_conservative": {
            "label": "Can only tolerate -15% (conservative)",
            "recommendation": {
                "strategy": "60/40 SPY-GLD/SHY + VIX Step Rule (monthly)",
                "details": (
                    "Reduce base equity allocation to 60% and apply VIX Step Rule: "
                    "VIX<15 → hold full 60% equity; VIX 15-25 → reduce to 42% equity; "
                    "VIX>25 → reduce to 24% equity. Rest in SHY."
                ),
                "implementation": [
                    "Base allocation: 60% equity (30% SPY + 30% GLD) + 40% SHY",
                    "If VIX < 15: keep full equity allocation",
                    "If VIX 15-25: multiply equity by 0.7 → 42% equity + 58% SHY",
                    "If VIX > 25: multiply equity by 0.4 → 24% equity + 76% SHY",
                    "Rebalance monthly",
                ],
                "expected_metrics": {
                    "sharpe": "~0.69",
                    "mdd": "~-12% to -15%",
                    "note": "VIX Step Rule Sharpe 0.69 with MDD -20.4% at 100% equity; 60/40 base reduces both",
                    "source": "N79 (step rule) + scaling",
                },
                "why_step_rule": "Zero calculation. No model. No app. Just memorize 3 VIX levels. (N79)",
            },
        },

        "branch_C_very_conservative": {
            "label": "Can only tolerate -10% (very conservative)",
            "recommendation": {
                "strategy": "40/60 SPY-GLD/SHY + 12/VIX monthly (capped at 0.4)",
                "details": (
                    "Cap equity at 40%. Apply 12/VIX but never exceed 40% equity. "
                    "This sacrifices return for drawdown protection."
                ),
                "implementation": [
                    "equity_weight = min(12/VIX, 0.4)",
                    "Split equity 50/50 SPY/GLD",
                    "Remainder in SHY",
                    "Rebalance monthly",
                ],
                "expected_metrics": {
                    "note": "Estimated MDD ~-8% to -10%. Sharpe ~0.5-0.6. Tradeoff: safety vs growth.",
                },
                "caveat": "At this risk level, consider whether equities are appropriate at all.",
            },
        },
    },

    # ======================================================================
    # DECISION NODE Q4: GEOGRAPHIC LOCATION
    # ======================================================================
    "Q4_location": {
        "question": "Where are you investing from?",
        "why_this_matters": (
            "US VIX is NOT a universal vol proxy. It works for markets correlated with SPY "
            "but fails for uncorrelated ones. Taiwan has its own VIXTWN. "
            "Tax treatment also differs dramatically."
        ),
        "evidence": "N118: US VIX direct on Taiwan FAILS (Sharpe -0.056); EWMA own-vol works (+0.076 Sharpe)",

        "branch_A_US": {
            "label": "United States",
            "recommendation": {
                "details": "Use strategies as described above (SPY/GLD/SHY + 12/VIX).",
                "tax_note": "Rebalancing triggers short-term capital gains (24%). Monthly rebal with SHY interest partially offsets.",
                "goto": "Q5_tail_protection",
            },
        },

        "branch_B_Taiwan": {
            "label": "Taiwan (台灣)",
            "recommendation": {
                "strategy": "0050.TW + short-term bond fund, EWMA VT monthly, target vol 10-12%",
                "details": (
                    "Taiwan has 0% capital gains tax on foreign/domestic ETFs. "
                    "Use 0050.TW (Taiwan 50 ETF) instead of SPY. "
                    "Use EWMA own-vol targeting instead of US VIX (VIX proxy FAILS for Taiwan). "
                    "If VIXTWN data available, 8.63/VIXTWN is the Taiwan 12/VIX equivalent."
                ),
                "implementation": [
                    "Calculate 20-day EWMA vol of 0050.TW (lambda=0.97)",
                    "equity_weight = target_vol / (EWMA_vol * sqrt(252))",
                    "Cap at 100%, floor at 0%",
                    "Put remainder in short-term bond fund (e.g., 元大台灣50反1 is NOT a bond fund — use actual bond fund)",
                    "Rebalance monthly",
                    "Alternative (simpler): use 8.63/VIXTWN if VIXTWN data is accessible",
                ],
                "expected_metrics": {
                    "sharpe_bh": 0.729,
                    "sharpe_vt": 0.796,
                    "mdd_bh": "-41.3%",
                    "mdd_vt": "-18.4%",
                    "target_vol": "8-18% all give Sharpe 0.78-0.80 (flat plateau)",
                    "source": "N119 (0050.TW EWMA VT, 2008-2026)",
                },
                "tax_advantage": "Taiwan: 0% capital gains tax. Frequent rebalancing has zero tax drag.",
                "why_not_US_VIX": "N118: EWT-SPY corr=0.742, but not enough for VIX proxy. Direct US VIX → Sharpe -0.056 (DESTROYS value).",
                "vix_lag_warning": "If using any VIX-based signal for Taiwan, use PREVIOUS day's VIX (US market closes after Taiwan opens).",
            },
        },

        "branch_C_other": {
            "label": "Other markets",
            "recommendation": {
                "details": (
                    "Check if US VIX correlates with your local market. "
                    "K25: US VIX works as universal proxy for 10 international equity markets. "
                    "But N118 shows correlation must be high enough. "
                    "If corr(your_market, SPY) < 0.6, use EWMA own-vol targeting instead."
                ),
                "decision_rule": [
                    "Calculate corr(your_market_return, SPY_return) over 252 days",
                    "If corr > 0.6: use 12/VIX (may need to calibrate numerator)",
                    "If corr < 0.6: use EWMA own-vol targeting (lambda=0.97, target=12%)",
                ],
                "evidence": "K25: VIX works for intl equity; N118: fails when corr < threshold",
            },
        },
    },

    # ======================================================================
    # DECISION NODE Q5: OPTIONAL TAIL PROTECTION
    # ======================================================================
    "Q5_tail_protection": {
        "question": "Do you want additional tail-risk protection beyond VT?",
        "why_this_matters": (
            "12/VIX already provides significant crisis protection (6/6 major crashes). "
            "Additional tail hedges have costs. Most are not worth it for retail investors."
        ),
        "evidence": "VT protects in 6/6 crashes (GFC, Flash Crash, Euro Crisis, 2015, 2018, COVID). K79: 0% ruin probability with VT.",

        "branch_A_no_extra": {
            "label": "No extra protection (recommended for most)",
            "recommendation": {
                "details": (
                    "12/VIX + SHY is sufficient for most investors. "
                    "VT already reduced COVID drawdown from -33.8% to -8.9%. "
                    "Adding complexity has diminishing returns."
                ),
            },
        },

        "branch_B_add_conditional_TLT": {
            "label": "Add conditional TLT (for sophisticated investors)",
            "recommendation": {
                "strategy": "Add TLT position ONLY when interest rates are falling",
                "details": (
                    "N181: Conditional TLT wins 5/5 rate regimes. "
                    "Signal: 10yr yield < 60-day MA → allocate to TLT. "
                    "This avoids the 2022 TLT disaster (-54.8%) while capturing rate-falling rallies."
                ),
                "expected_metrics": {
                    "sharpe": 1.08,
                    "mdd": "-19%",
                    "source": "N181 (2008-2026, robust 5/5 rate regimes)",
                },
                "caveat": "Requires monitoring interest rates. More complex than base strategy.",
            },
        },

        "branch_C_gold_is_enough": {
            "label": "GLD in 50/50 IS your tail hedge",
            "recommendation": {
                "details": (
                    "GLD already serves as the tail hedge in the 50/50 portfolio. "
                    "Gold has inverted leverage effect (vol rises when price rises — opposite of stocks). "
                    "SPY-GLD correlation ~0.03 normally, goes negative in crises. "
                    "Don't hedge the hedge."
                ),
                "why_not_BTC": "BTC-SPY correlation surges to 0.47 in high-VIX environments (T26). BTC is risk-on, NOT a hedge.",
                "why_not_options": "N178-N180: All options simulations failed without real IV surface data. Pause until real data available.",
            },
        },
    },

    # ======================================================================
    # SECTION 2: WHAT NOT TO DO
    # ======================================================================
    "dont_list": {
        "title": "Critical DON'Ts — Mistakes Our Research Has Proven Costly",
        "items": [
            {
                "dont": "DON'T add QQQ to diversify",
                "why": "QQQ-SPY tail dependence lambda_L = 0.82. In crashes they move together. Adding QQQ = one concentrated US tech bet. (Q21)",
                "cost": "Higher MDD with minimal Sharpe improvement",
            },
            {
                "dont": "DON'T use TLT as your cash/safe position",
                "why": "TLT crashed -54.8% in 2022. Long-duration bonds have interest rate risk that can CANCEL VT protection entirely. (N82, N169)",
                "cost": "MDD -37.6% (vs -23.7% with SHY)",
            },
            {
                "dont": "DON'T use VT during DCA accumulation",
                "why": "K39 Lifecycle Paradox: DCA already buys cheap during drawdowns. VT's cash position makes you miss low prices. Terminal wealth -55.9% vs B&H. (K39)",
                "cost": "-55.9% terminal wealth over 20 years",
            },
            {
                "dont": "DON'T use daily rebalancing",
                "why": "Monthly Sharpe 0.697 > Daily 0.610. Daily creates whipsaw and higher TX costs. Monthly is strictly better. (50981d0e, J10)",
                "cost": "Lower Sharpe + 0.72%/yr more TX cost",
            },
            {
                "dont": "DON'T use same-day VIX for same-day returns",
                "why": "Timing bias inflates Sharpe by ~1.0 (0.81 → 1.80). VIX_t must set weight for r_{t+1}. (1d8eedc7, Q10)",
                "cost": "Illusory performance — impossible to implement",
            },
            {
                "dont": "DON'T try to predict returns with volatility",
                "why": "K102: VIX predicts returns with R² < 2%. Vol targeting is RISK MANAGEMENT, not return enhancement.",
                "cost": "Wasted effort; false sense of skill",
            },
            {
                "dont": "DON'T use Risk Parity with 4+ assets including TLT",
                "why": "TLT gets 40% weight in RP (low vol → high weight) but crashed in 2022 stock-bond co-movement. 4-asset RP Sharpe=0.64, MaxDD=39%. (b90ca6c3)",
                "cost": "Worse than simple 50/50 SPY/GLD",
            },
            {
                "dont": "DON'T add BTC as a hedge",
                "why": "BTC-SPY correlation surges from 0.07 to 0.47 in high-VIX environments. BTC is leveraged equity exposure in crises, not a hedge. (T26)",
                "cost": "MDD worsens from -20% to -24%, skewness from -0.35 to -0.82",
            },
            {
                "dont": "DON'T use complex models (LSTM, XGBoost, etc.) for daily vol",
                "why": "Daily returns are essentially iid noise after GARCH filtering. 4 separate ML attempts all failed. GJR-GARCH is the ceiling. (K142, LSTM/GRU experiments)",
                "cost": "Overfitting risk + no improvement",
            },
            {
                "dont": "DON'T optimize VT target vol extensively",
                "why": "Targets 6-20% all give nearly identical Sharpe (flat plateau). 12% is fine. Don't waste time finding the 'optimal' target. (N79, N119)",
                "cost": "Data snooping risk for zero gain",
            },
            {
                "dont": "DON'T panic sell during volatility spikes",
                "why": "K28: Panic sellers lose 40% wealth vs B&H over 20 years (2.55%/yr drag). They miss +52.4% recovery rallies yet STILL experience -18.9% MDD. VT is the systematic alternative to panic selling.",
                "cost": "$442K vs $732K over 20 years (40% loss)",
            },
        ],
    },

    # ======================================================================
    # SECTION 3: CHANGE TRIGGERS — WHEN TO REVISIT YOUR STRATEGY
    # ======================================================================
    "change_triggers": {
        "title": "When to Revisit Your Strategy",
        "items": [
            {
                "trigger": "Life stage changes (retirement, inheritance, job loss)",
                "action": "Re-enter decision tree at Q1. Your optimal strategy may flip entirely.",
                "evidence": "K39: Accumulation vs withdrawal have OPPOSITE optimal strategies.",
            },
            {
                "trigger": "VIX sustained above 30 for 2+ weeks",
                "action": "Your 12/VIX strategy is ALREADY handling this (equity weight = 40%). Trust the system. Do NOT override manually.",
                "evidence": "K28: Panic selling during spikes costs 2.55%/yr. VT mechanically reduces exposure.",
            },
            {
                "trigger": "Interest rate regime shift (Fed pivot)",
                "action": "Consider adding conditional TLT if rates are falling. Remove TLT if rates are rising.",
                "evidence": "N181: Conditional TLT wins 5/5 rate regimes. Rate direction matters more than rate level.",
            },
            {
                "trigger": "Your market decorrelates from US (corr drops below 0.5)",
                "action": "Switch from US VIX proxy to EWMA own-vol targeting.",
                "evidence": "N118: VIX proxy fails when corr < threshold. EWMA always works (it uses own data).",
            },
            {
                "trigger": "You accumulated a large cash position (lump sum event)",
                "action": "Switch from DCA-only (no VT) to lump-sum strategy (with VT). The lump sum needs drawdown protection.",
                "evidence": "N172: DCA doesn't need VT, but lump sums do (can't dollar-cost-average into dips).",
            },
            {
                "trigger": "New asset class with uncorrelated returns emerges",
                "action": "Only add if corr < 0.3 with current portfolio AND no tail dependence with equities.",
                "evidence": "T26: BTC looks uncorrelated (0.07) in calm markets but surges to 0.47 in crises. Check crisis correlation, not average.",
            },
        ],
    },

    # ======================================================================
    # SECTION 4: BEHAVIORAL CHECKLIST
    # ======================================================================
    "behavioral_advice": {
        "title": "Behavioral Protection — VT as Anti-Panic System",
        "key_insight": (
            "K28: VT is primarily a BEHAVIORAL protection system, not an alpha generator. "
            "It reduces tail days from 81 to 11 over 20 years. "
            "The real value is preventing the #1 investor mistake: panic selling."
        ),
        "rules": [
            {
                "rule": "NEVER override VT mechanically",
                "explanation": "The whole point of VT is to remove discretion. If VIX=40 and your weight is 30%, hold 30%. Don't second-guess.",
            },
            {
                "rule": "Monthly check takes 10 seconds",
                "explanation": "Look up VIX. Calculate 12/VIX. Done. This should be boring. (N83: '10 seconds to check VIX + 1 monthly rebalance')",
            },
            {
                "rule": "Write down your rules BEFORE a crisis",
                "explanation": "K28: Procrastinator VT still beats emotional investors. Having a pre-written plan removes decision fatigue during panic.",
            },
            {
                "rule": "Expect 1-3% annual insurance cost",
                "explanation": "K41-K91: VT insurance premium averages ~1%/yr over 76 years, 2-4%/yr in VIX era. This is the cost of not losing -30% in crashes.",
            },
            {
                "rule": "Don't check daily",
                "explanation": "Monthly rebalancing is optimal. Checking daily creates anxiety without actionable information. Set a monthly calendar reminder.",
            },
            {
                "rule": "VT works in EVERY crash we tested",
                "explanation": "6/6 major crashes: GFC 2008, Flash Crash 2010, Euro Crisis 2011, China Devaluation 2015, Volmageddon 2018, COVID 2020. CASH (via SHY) is the only truly universal hedge.",
            },
        ],
    },

    # ======================================================================
    # SECTION 5: STRATEGY COMPARISON TABLE
    # ======================================================================
    "strategy_comparison": {
        "title": "Complete Strategy Comparison",
        "strategies": [
            {
                "name": "50/50 SPY/GLD Buy & Hold",
                "sharpe": 0.81,
                "mdd": "-16%",
                "complexity": "Zero",
                "rebalancing": "Annual",
                "best_for": "DCA accumulators",
                "source": "J1, K2 (8 validations)",
            },
            {
                "name": "50/50 SPY/GLD + 12/VIX + SHY",
                "sharpe": 0.826,
                "mdd": "-15.5%",
                "complexity": "Low (check VIX monthly)",
                "rebalancing": "Monthly",
                "best_for": "Lump sum + retirees",
                "source": "Q21 optimal portfolio",
            },
            {
                "name": "VIX Step Rule (3-tier)",
                "sharpe": 0.69,
                "mdd": "-20.4%",
                "complexity": "Zero (memorize 3 levels)",
                "rebalancing": "Monthly",
                "best_for": "People who hate math",
                "source": "N79",
            },
            {
                "name": "12/VIX SPY-only + SHY",
                "sharpe": 0.695,
                "mdd": "-23.7%",
                "complexity": "Low",
                "rebalancing": "Monthly",
                "best_for": "US-only investors",
                "source": "N82",
            },
            {
                "name": "Vol-adj EW (SPY+QQQ+SHY)",
                "sharpe": 0.912,
                "mdd": "-20.0%",
                "complexity": "Medium",
                "rebalancing": "Monthly",
                "best_for": "Tech-tilted, higher risk tolerance",
                "source": "N101",
                "caveat": "QQQ adds tail risk (lambda_L=0.82 with SPY)",
            },
            {
                "name": "0050.TW EWMA VT (target 10%)",
                "sharpe": 0.796,
                "mdd": "-18.4%",
                "complexity": "Medium (calculate EWMA)",
                "rebalancing": "Monthly",
                "best_for": "Taiwan investors",
                "source": "N119",
                "tax": "0% capital gains in Taiwan",
            },
            {
                "name": "Conditional TLT + 12/VIX",
                "sharpe": 1.08,
                "mdd": "-19%",
                "complexity": "High (monitor rates + VIX)",
                "rebalancing": "Monthly",
                "best_for": "Sophisticated investors",
                "source": "N181",
                "caveat": "Requires understanding rate regime",
            },
            {
                "name": "EWMA(0.97) VT (any asset)",
                "sharpe": "varies",
                "mdd": "varies",
                "complexity": "Low (one Excel formula)",
                "rebalancing": "Monthly",
                "best_for": "Any asset, any market, no VIX needed",
                "source": "J12 (safest default for 4/7 assets)",
                "note": "Best MDD in 4/7 assets tested, never worst",
            },
        ],
    },

    # ======================================================================
    # SECTION 6: THE 1-MINUTE SUMMARY
    # ======================================================================
    "one_minute_summary": {
        "title": "The 1-Minute Answer",
        "for_most_people": (
            "If you're saving monthly: Just buy 50/50 SPY/GLD. Don't touch it. "
            "If you have a lump sum or are retired: 50/50 SPY/GLD + 12/VIX + SHY, rebalance monthly. "
            "If you're in Taiwan: 0050.TW + bond fund, EWMA vol target 10%, monthly. "
            "If you hate math: VIX Step Rule (VIX<15:100%, 15-25:70%, >25:40%)."
        ),
        "the_one_thing": (
            "The single most important finding from 195 experiments: "
            "CASH (SHY) is the only universal hedge that works in every type of crisis. "
            "Not gold. Not bonds. Not crypto. Not options. CASH. "
            "VT's mechanism is simply: hold more cash when volatility is high."
        ),
    },

    # ======================================================================
    # SECTION 7: CONFIDENCE & LIMITATIONS
    # ======================================================================
    "limitations": {
        "title": "What We Don't Know (Intellectual Honesty)",
        "items": [
            "All backtests are historical. Future market structure may differ (0DTE options, AI trading).",
            "VT Sharpe improvement is NOT statistically significant (t=0.33). MDD improvement IS significant (p=0.0004).",
            "The 12/VIX numerator works across 6-20 range but may not be optimal for future volatility regimes.",
            "Taiwan results based on shorter data history (since ~2003 for 0050.TW).",
            "GLD correlation with SPY may increase during de-dollarization scenarios (untested).",
            "SHY assumes stable short-term rates. In negative rate environments (Japan/EU), SHY equivalent may not exist.",
            "VT insurance premium (1-4%/yr) compounds over decades. In a permanent bull market, B&H strictly dominates.",
            "All strategies assume you CAN rebalance monthly. Locked retirement accounts may not permit this.",
            "Harvey (2016) t>3.0 threshold: most individual strategy Sharpes do not pass this bar in isolation.",
            "Cross-OOS validation done for 5+ periods for major strategies, but not exhaustively for all combinations.",
        ],
    },
}

# ======================================================================
# PRINT THE DECISION TREE
# ======================================================================

def print_section(key, data, indent=0):
    """Pretty-print a section of the decision tree."""
    prefix = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("metadata",):
                continue
            if isinstance(v, dict):
                print(f"\n{prefix}{'='*60}")
                title = v.get("title", v.get("question", v.get("label", k)))
                print(f"{prefix}{title}")
                print(f"{prefix}{'='*60}")
                print_section(k, v, indent + 1)
            elif isinstance(v, list):
                print(f"\n{prefix}{k}:")
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        for ik, iv in item.items():
                            print(f"{prefix}  {ik}: {iv}")
                        print()
                    else:
                        print(f"{prefix}  - {item}")
            elif isinstance(v, str) and len(v) > 80:
                print(f"\n{prefix}{k}:")
                # Word wrap
                words = v.split()
                line = prefix + "  "
                for w in words:
                    if len(line) + len(w) > 76:
                        print(line)
                        line = prefix + "  " + w
                    else:
                        line += " " + w if line.strip() else w
                if line.strip():
                    print(line)
            else:
                print(f"{prefix}{k}: {v}")


# Print metadata
print("\n" + "=" * 78)
print("METADATA")
print("=" * 78)
for k, v in decision_tree["metadata"].items():
    print(f"  {k}: {v}")

# Print Q1
print("\n" + "=" * 78)
print("DECISION TREE NODE Q1: LIFE STAGE")
print("=" * 78)
q1 = decision_tree["Q1_life_stage"]
print(f"\n  QUESTION: {q1['question']}")
print(f"\n  WHY IT MATTERS: {q1['why_this_matters']}")
print(f"\n  EVIDENCE: {q1['evidence']}")
print(f"\n  → Accumulating → go to Q2")
print(f"  → Withdrawing → go to Q3")

# Print Q2
print("\n" + "=" * 78)
print("DECISION TREE NODE Q2: ACCUMULATION METHOD")
print("=" * 78)
q2 = decision_tree["Q2_accumulating_method"]
print(f"\n  QUESTION: {q2['question']}")
print(f"\n  WHY IT MATTERS: {q2['why_this_matters']}")
print(f"\n  EVIDENCE: {q2['evidence']}")
print(f"\n  → DCA (monthly savings):")
rec_a = q2["branch_A_DCA"]["recommendation"]
print(f"    STRATEGY: {rec_a['strategy']}")
print(f"    WHY NO VT: {rec_a['why_no_VT']}")
print(f"    WHY NO QQQ: {rec_a['why_no_QQQ']}")
print(f"    WHY GLD: {rec_a['why_GLD']}")
print(f"\n  → Lump sum:")
rec_b = q2["branch_B_lump_sum"]["recommendation"]
print(f"    STRATEGY: {rec_b['strategy']}")
print(f"    Sharpe: {rec_b['expected_metrics']['sharpe']}")
print(f"    MDD: {rec_b['expected_metrics']['mdd']}")
print(f"    COVID: {rec_b['expected_metrics']['covid_drawdown']}")
print(f"    WHY SHY NOT TLT: {rec_b['why_SHY_not_TLT']}")
print(f"    WHY MONTHLY: {rec_b['why_monthly']}")

# Print Q3
print("\n" + "=" * 78)
print("DECISION TREE NODE Q3: DRAWDOWN TOLERANCE (RETIREES)")
print("=" * 78)
q3 = decision_tree["Q3_drawdown_tolerance"]
print(f"\n  QUESTION: {q3['question']}")
print(f"\n  KEY FINDING: {q3['why_this_matters']}")
print(f"\n  EVIDENCE: {q3['evidence']}")
for bkey in ["branch_A_moderate", "branch_B_conservative", "branch_C_very_conservative"]:
    b = q3[bkey]
    print(f"\n  → {b['label']}:")
    print(f"    STRATEGY: {b['recommendation']['strategy']}")

# Print Q4
print("\n" + "=" * 78)
print("DECISION TREE NODE Q4: GEOGRAPHIC LOCATION")
print("=" * 78)
q4 = decision_tree["Q4_location"]
print(f"\n  QUESTION: {q4['question']}")
print(f"\n  → US: Standard 12/VIX strategies")
print(f"  → Taiwan: 0050.TW + EWMA VT (US VIX FAILS, Sharpe -0.056)")
tw = q4["branch_B_Taiwan"]["recommendation"]
print(f"    Sharpe B&H: {tw['expected_metrics']['sharpe_bh']} → VT: {tw['expected_metrics']['sharpe_vt']}")
print(f"    MDD B&H: {tw['expected_metrics']['mdd_bh']} → VT: {tw['expected_metrics']['mdd_vt']}")
print(f"    Tax: {tw['tax_advantage']}")
print(f"  → Other: Check corr with SPY; if >0.6 use VIX, else EWMA own-vol")

# Print Q5
print("\n" + "=" * 78)
print("DECISION TREE NODE Q5: TAIL PROTECTION")
print("=" * 78)
q5 = decision_tree["Q5_tail_protection"]
print(f"\n  QUESTION: {q5['question']}")
print(f"\n  → Most investors: No extra protection needed (12/VIX + SHY is sufficient)")
print(f"  → Sophisticated: Conditional TLT when rates falling (Sharpe 1.08)")
print(f"  → Key insight: GLD in 50/50 IS your tail hedge. Don't hedge the hedge.")
print(f"  → NOT BTC: Correlation surges 0.07→0.47 in crises (risk-on, not hedge)")

# Print DON'Ts
print("\n" + "=" * 78)
print("CRITICAL DON'Ts — 11 RESEARCH-PROVEN MISTAKES")
print("=" * 78)
for i, item in enumerate(decision_tree["dont_list"]["items"], 1):
    print(f"\n  {i}. {item['dont']}")
    print(f"     WHY: {item['why']}")
    print(f"     COST: {item['cost']}")

# Print change triggers
print("\n" + "=" * 78)
print("CHANGE TRIGGERS — WHEN TO REVISIT")
print("=" * 78)
for item in decision_tree["change_triggers"]["items"]:
    print(f"\n  TRIGGER: {item['trigger']}")
    print(f"  ACTION: {item['action']}")

# Print behavioral advice
print("\n" + "=" * 78)
print("BEHAVIORAL CHECKLIST")
print("=" * 78)
ba = decision_tree["behavioral_advice"]
print(f"\n  KEY INSIGHT: {ba['key_insight']}")
for rule in ba["rules"]:
    print(f"\n  ✓ {rule['rule']}")
    print(f"    {rule['explanation']}")

# Print strategy comparison
print("\n" + "=" * 78)
print("STRATEGY COMPARISON TABLE")
print("=" * 78)
print(f"\n  {'Strategy':<35} {'Sharpe':<8} {'MDD':<8} {'Complexity':<15} {'Best For'}")
print(f"  {'-'*35} {'-'*7} {'-'*7} {'-'*14} {'-'*25}")
for s in decision_tree["strategy_comparison"]["strategies"]:
    print(f"  {s['name']:<35} {str(s['sharpe']):<8} {s['mdd']:<8} {s['complexity']:<15} {s['best_for']}")

# Print 1-minute summary
print("\n" + "=" * 78)
print("THE 1-MINUTE ANSWER")
print("=" * 78)
oms = decision_tree["one_minute_summary"]
print(f"\n  {oms['for_most_people']}")
print(f"\n  THE ONE THING: {oms['the_one_thing']}")

# Print limitations
print("\n" + "=" * 78)
print("LIMITATIONS (Intellectual Honesty)")
print("=" * 78)
for i, lim in enumerate(decision_tree["limitations"]["items"], 1):
    print(f"  {i}. {lim}")

# ======================================================================
# SAVE STRUCTURED JSON
# ======================================================================
output_path = "experiments/k377_decision_framework_output.json"
with open(output_path, "w") as f:
    json.dump(decision_tree, f, indent=2, ensure_ascii=False, default=str)
print(f"\n\nStructured JSON saved to: {output_path}")

# ======================================================================
# SUMMARY STATISTICS
# ======================================================================
print("\n" + "=" * 78)
print("K377 SYNTHESIS STATISTICS")
print("=" * 78)
print(f"  Decision tree nodes: 5 (Q1-Q5)")
print(f"  Total branches: 13")
print(f"  Strategies compared: {len(decision_tree['strategy_comparison']['strategies'])}")
print(f"  DON'T rules: {len(decision_tree['dont_list']['items'])}")
print(f"  Change triggers: {len(decision_tree['change_triggers']['items'])}")
print(f"  Behavioral rules: {len(decision_tree['behavioral_advice']['rules'])}")
print(f"  Limitations acknowledged: {len(decision_tree['limitations']['items'])}")
print(f"  Knowledge entries synthesized: 978")
print(f"  Experiments referenced: ~50 (from 195 total)")
print(f"\n  KEY REFERENCED EXPERIMENTS:")
refs = [
    ("K39", "VT Lifecycle Paradox (accumulation vs withdrawal)"),
    ("K79", "VT + 4% Withdrawal Rule Monte Carlo"),
    ("K28", "Behavioral bias simulation (panic seller cost)"),
    ("K31", "DCA + VT interaction"),
    ("K41-K91", "VT Insurance Pricing (76-year average)"),
    ("Q21", "Optimal retail portfolio (50/50 SPY/GLD + 12/VIX)"),
    ("N79", "12/VIX best lazy strategy + VIX Step Rule"),
    ("N82", "Cash allocation (SHY vs TLT vs BIL)"),
    ("N83", "Complete operation manual"),
    ("N101", "Multi-asset 12/VIX (vol-adj EW)"),
    ("N115", "CRRA utility breakeven (gamma=4)"),
    ("N118-119", "Taiwan market (EWMA VT for 0050.TW)"),
    ("N169", "12/VIX+SHY beats 60/40 on ALL metrics"),
    ("N172", "DCA + VT marginal benefit"),
    ("N181", "Conditional TLT (5/5 rate regimes)"),
    ("J1-J10", "Phase J core findings (rebalancing, costs)"),
    ("J12", "EWMA(0.97) as safest default"),
    ("T26", "BTC integration regime analysis"),
    ("K25", "International equity VIX universality"),
]
for ref_id, desc in refs:
    print(f"    {ref_id}: {desc}")

print("\n" + "=" * 78)
print("K377 COMPLETE. Decision framework synthesized from ALL research.")
print("=" * 78)
