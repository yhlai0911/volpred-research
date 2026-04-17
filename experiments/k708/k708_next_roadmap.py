"""K708: Next Session Roadmap — What's Left to Discover?

After 87 experiments (K621-K707), this session established three certainties:
1. VT = insurance, not alpha (K687/K688)
2. 50/50 SPY/GLD = optimal static allocation (K702/K704/K706)
3. VIX predicts vol magnitude, not direction (K626/K697/K701)

This experiment synthesizes what's settled, what's actionable next session,
what's genuinely unexplored, and what the website needs.

NOT a computation experiment — this is a strategic roadmap synthesis.

Data source: All prior experiment results (K621-K707), 5-min data collection
status (51 SPY files, 40 0050.TW files), website source code audit (K705),
investor FAQ (K707).

Attribution: [提出: Claude, 執行: Claude]
"""

import json
from datetime import datetime, timezone

results = {
    "experiment_id": "K708",
    "title": "Next Session Roadmap — What's Left to Discover?",
    "date": datetime.now(timezone.utc).isoformat(),
    "type": "strategic_roadmap",
    "attribution": "[提出: Claude, 執行: Claude]",
    "data_source": "K621-K707 results + 5-min data collection status + frontend audit",
    "session_summary": {
        "total_experiments": 87,
        "range": "K621-K707",
        "positive_or_informative": 54,
        "null_results": 15,
        "overturned_by_codex": 8,
        "codex_corrected": 3,
        "key_paradigm_shift": "VT = insurance (MDD reduction), NOT alpha (Sharpe improvement)"
    },

    # ========================================================================
    # SECTION 1: SETTLED — Do NOT Revisit
    # ========================================================================
    "section_1_settled": {
        "description": "These conclusions survived multiple corrections, Codex reviews, "
                       "and cross-OOS validation. Revisiting them wastes resources.",
        "settled_conclusions": [
            {
                "id": "S1",
                "conclusion": "Daily/weekly/monthly VIX alpha is impossible",
                "evidence": "K697: direction corr=0.04, oracle Sharpe gain only 0.28 (wiped by TX). "
                            "K701: weekly/monthly no better — corr still <0.1 at all horizons. "
                            "Even with perfect foresight, VIX-based directional trading fails.",
                "experiments": ["K626", "K697", "K701"],
                "times_confirmed": 5,
                "status": "CLOSED"
            },
            {
                "id": "S2",
                "conclusion": "50/50 SPY/GLD is the optimal static allocation",
                "evidence": "K702: 21-way grid search, 50/50 max Sharpe (0.548). "
                            "K704: Risk Parity converges to ~50/50 because vol ratio ~1.05. "
                            "K706: Robust to correlation shifts (-0.3 to +0.3). "
                            "DM test: no allocation significantly beats 50/50.",
                "experiments": ["K702", "K704", "K706"],
                "times_confirmed": 8,
                "status": "CLOSED"
            },
            {
                "id": "S3",
                "conclusion": "VT is drawdown insurance, not alpha generator",
                "evidence": "K687: After proper lag, NO VT beats BH 50/50 on Sharpe. "
                            "K688: VT wins only under CRRA utility gamma>=5 "
                            "(MDD -32.5% to -17.0%, p=0.0004). "
                            "K690: EWMA VT most lag-robust (autocorr 0.99). "
                            "K694: Post-correction, 7/10 beat SPY but none beat BH 50/50 Sharpe.",
                "experiments": ["K687", "K688", "K690", "K694"],
                "paradigm_shift": True,
                "status": "CLOSED"
            },
            {
                "id": "S4",
                "conclusion": "Lookahead bias is the #1 research risk",
                "evidence": "K679: Percentile Sharpe 1.68 was 100% artifact (corrected to 0.355). "
                            "K693: 9,935 paper_trading entries had same-day bug. "
                            "K698: Contrarian 'alpha' had BH baseline bug. "
                            "Codex caught bugs 3 times (K618, K621, K679).",
                "experiments": ["K679", "K686", "K693", "K698", "K700"],
                "codex_saves": 3,
                "status": "CLOSED — but vigilance required for every new strategy"
            },
            {
                "id": "S5",
                "conclusion": "GJR-GARCH > GARCH for vol forecasting",
                "evidence": "Confirmed 40+ times across sessions. Gamma consistently significant. "
                            "VIX is sufficient statistic for equity vol (31 confirmations).",
                "times_confirmed": 40,
                "status": "CLOSED"
            },
            {
                "id": "S6",
                "conclusion": "VIX overlays (term structure, roll yield, seasonality) add no OOS value",
                "evidence": "K638: VIX term structure slope NULL OOS. "
                            "K666: VIX seasonality NOT significant (KW p=0.97). "
                            "K671: VIX roll yield NULL (leverage artifact). "
                            "K649: Vol-of-vol NULL for regime prediction. "
                            "K651: FRED macro indicators NULL (sign flips).",
                "experiments": ["K638", "K649", "K651", "K666", "K671"],
                "status": "CLOSED"
            },
            {
                "id": "S7",
                "conclusion": "Smooth-weight strategies are most lag-robust",
                "evidence": "K690: 12/VIX and Risk Parity almost unaffected by 1-day lag "
                            "(weight autocorr 0.99). Piecewise most fragile. "
                            "Design principle: smooth weights = robust to execution delay.",
                "experiments": ["K690"],
                "status": "CLOSED — design principle established"
            }
        ]
    },

    # ========================================================================
    # SECTION 2: ACTIONABLE Next Session
    # ========================================================================
    "section_2_actionable": {
        "description": "Concrete tasks with clear deadlines and deliverables.",
        "tasks": [
            {
                "id": "A1",
                "task": "HAR-RV with 5-min data",
                "priority": "HIGH",
                "eta": "2026-04-11 (60 days of SPY data accumulated)",
                "current_status": {
                    "spy_5min_files": 51,
                    "tw0050_5min_files": 40,
                    "min_needed_for_har_rv": 60,
                    "days_until_ready": 9,
                    "collection_script": "scripts/collect_5min_data.py (running via cron)"
                },
                "why_important": "First genuinely new data source in this research program. "
                                 "Daily squared returns are a noisy RV proxy — 5-min data gives "
                                 "true realized variance. HAR-RV (Corsi 2009) decomposes into "
                                 "daily/weekly/monthly components. Could reveal patterns invisible "
                                 "at daily frequency.",
                "experiment_design": {
                    "model": "HAR-RV: RV_t = c + b_d*RV_{t-1} + b_w*RV_{t-5:t-1} + b_m*RV_{t-22:t-1}",
                    "benchmark": "GJR-GARCH with daily squared returns",
                    "evaluation": "QLIKE, MSE, DM test",
                    "lag_check": "Signal from t-1 RV, forecast for t RV — verify no lookahead",
                    "oos_periods": "Leave last 20% for OOS (rolling re-estimation)"
                },
                "references": [
                    "Corsi (2009) JFE: HAR-RV model",
                    "Andersen et al. (2003): Realized variance theory",
                    "Patton & Sheppard (2015): Good and bad RV decomposition"
                ]
            },
            {
                "id": "A2",
                "task": "NFP 04/03 post-event article",
                "priority": "HIGH",
                "eta": "2026-04-04 (day after release)",
                "why_important": "Non-farm payrolls is the single most market-moving data release. "
                                 "Pre-event article 04/01-02, post-event analysis 04/04.",
                "deliverables": [
                    "Pre-NFP article: what VIX regime says about expected reaction",
                    "Post-NFP article: actual reaction vs VIX-implied expectation",
                    "Research note: does NFP surprise predict next-week vol?"
                ]
            },
            {
                "id": "A3",
                "task": "TSMC earnings coverage",
                "priority": "MEDIUM",
                "eta": "2026-04-10 (revenue) and 2026-04-16 (full earnings)",
                "why_important": "TSMC is the most important Taiwan-connected stock. "
                                 "0050.TW is ~50% TSMC. Revenue report 04/10, full earnings 04/16.",
                "deliverables": [
                    "Pre-earnings article: TSMC + 0050.TW vol regime",
                    "Post-earnings article: actual impact on 0050.TW and our Taiwan strategies"
                ]
            },
            {
                "id": "A4",
                "task": "Paper corrections (VT=insurance paradigm)",
                "priority": "HIGH",
                "papers_affected": [
                    {
                        "paper": "paper/leverage-direction/main.tex",
                        "pages": 60,
                        "changes_needed": [
                            "Reframe VT contribution from 'alpha generation' to 'insurance/MDD reduction'",
                            "Add K687 lag correction results",
                            "Update CRRA utility analysis with K688 gamma>=5 crossover",
                            "Add K693 paper_trading correction disclosure"
                        ]
                    },
                    {
                        "paper": "paper/vt-trend-following/main.tex",
                        "pages": 24,
                        "changes_needed": [
                            "Align with VT=insurance conclusion",
                            "Address Codex review issues from prior session"
                        ]
                    }
                ]
            },
            {
                "id": "A5",
                "task": "Website messaging fixes (K705 HIGH gaps)",
                "priority": "HIGH",
                "gaps_to_fix": [
                    {
                        "gap_id": "GAP-01",
                        "description": "StrategyPanel header: '投資建議' → '風險管理配置'",
                        "effort": "trivial",
                        "file": "frontend-v2-fix/src/components/StrategyPanel.tsx:64"
                    },
                    {
                        "gap_id": "GAP-03",
                        "description": "StrategySelector: CAGR prominent → lead with MDD",
                        "effort": "moderate",
                        "file": "frontend-v2-fix/src/components/StrategySelector.tsx"
                    },
                    {
                        "gap_id": "GAP-07",
                        "description": "MDD as primary metric, framed positively (green, not red)",
                        "effort": "moderate",
                        "file": "frontend-v2-fix/src/components/StrategyPanel.tsx"
                    },
                    {
                        "gap_id": "GAP-08",
                        "description": "Insurance framing: add explicit VT=insurance context",
                        "effort": "moderate",
                        "files": [
                            "frontend-v2-fix/src/components/HeroSection.tsx",
                            "frontend-v2-fix/src/components/StrategyPanel.tsx"
                        ]
                    }
                ]
            },
            {
                "id": "A6",
                "task": "K707 FAQ as /guide page content",
                "priority": "MEDIUM",
                "description": "K707 produced 20 investor FAQs backed by 25 experiments. "
                               "This should become the /guide page (W3.3 in backlog).",
                "deliverables": [
                    "Create /guide page with expandable FAQ sections",
                    "Each answer links to supporting experiment",
                    "Insurance framing throughout"
                ]
            },
            {
                "id": "A7",
                "task": "Strategy descriptions update (post-K693 correct numbers)",
                "priority": "MEDIUM",
                "description": "After K693 corrected 9,935 entries, some strategy descriptions "
                               "and StrategySelector stats may reference pre-correction numbers. "
                               "Audit and update all hardcoded performance claims.",
                "files_to_audit": [
                    "frontend-v2-fix/src/components/StrategySelector.tsx (stats objects)",
                    "frontend-v2-fix/src/app/vix-calculator/page.tsx (HISTORICAL_STATS)",
                    "scripts/daily_update.py (strategy descriptions)"
                ]
            }
        ]
    },

    # ========================================================================
    # SECTION 3: GENUINELY UNEXPLORED
    # ========================================================================
    "section_3_unexplored": {
        "description": "These directions involve genuinely different data, methods, or markets. "
                       "They cannot be answered by re-running VT variants on daily SPY/GLD.",
        "directions": [
            {
                "id": "U1",
                "direction": "Intraday alpha from 5-min data",
                "novelty": "HIGH — entirely different information set",
                "description": "5-min data may reveal patterns invisible at daily frequency. "
                               "Intraday seasonality (U-shape), overnight vs intraday decomposition, "
                               "market microstructure effects (bid-ask bounce, order flow). "
                               "K630 tested overnight/intraday with daily proxies and got NULL — "
                               "but actual 5-min data could show different results.",
                "specific_hypotheses": [
                    "H1: HAR-RV with realized variance beats GJR-GARCH with daily squared returns (QLIKE)",
                    "H2: Good/bad RV decomposition (Patton-Sheppard) captures asymmetry better than GJR gamma",
                    "H3: Intraday vol pattern has predictive power for next-day opening direction",
                    "H4: Jump detection (Barndorff-Nielsen-Shephard) improves tail risk forecasting"
                ],
                "data_readiness": "51/60 SPY days collected, ETA 2026-04-11",
                "prior_related": ["K196 (5min pilot)", "K545 (intraday seasonality)", "K630 (overnight/intraday NULL)"],
                "literature": [
                    "Corsi (2009) JFE: HAR-RV",
                    "Patton & Sheppard (2015): Good/Bad RV",
                    "Barndorff-Nielsen & Shephard (2006): Bipower variation for jump detection",
                    "Bollerslev et al. (2018): Realized GARCH"
                ]
            },
            {
                "id": "U2",
                "direction": "NLP sentiment as alternative information",
                "novelty": "HIGH — completely different data modality",
                "description": "VIX captures option-implied information. NLP sentiment from "
                               "news/social media captures a different information set. "
                               "If VIX already prices in news sentiment, NLP adds nothing. "
                               "If not, NLP may capture narrative momentum invisible to VIX.",
                "specific_hypotheses": [
                    "H1: News sentiment (GDELT/FinBERT) predicts next-day vol beyond VIX",
                    "H2: Social media fear index (Twitter/Reddit) leads VIX by 1-2 hours",
                    "H3: Earnings call transcript sentiment predicts post-announcement vol"
                ],
                "data_sources": [
                    "GDELT (free news tone data — available via API)",
                    "FinBERT (pre-trained finance-specific NLP model)",
                    "Google Trends (free, proxies for retail attention)",
                    "Reddit/Twitter API (may require authentication)"
                ],
                "prior_related": [],
                "barrier": "Data acquisition and processing pipeline needed",
                "literature": [
                    "Tetlock (2007) JF: Giving content to investor sentiment",
                    "Loughran & McDonald (2011) JF: Finance-specific word lists",
                    "Araci (2019): FinBERT for financial sentiment",
                    "Da et al. (2015) RFS: Google Trends as fear gauge"
                ]
            },
            {
                "id": "U3",
                "direction": "Multi-asset beyond SPY/GLD",
                "novelty": "MEDIUM — same methods, different correlation structure",
                "description": "K662 tested commodity VT and found VIX irrelevant for GLD/USO. "
                               "But haven't tested: REITs (VNQ), EM equities (EEM), "
                               "international developed (EFA), Treasury bonds (TLT), "
                               "or multi-asset portfolios with 3+ assets.",
                "specific_hypotheses": [
                    "H1: 3-asset portfolio (SPY/GLD/TLT) has better Sharpe than 2-asset 50/50",
                    "H2: VT applied to TLT reduces bond drawdowns during rate hikes",
                    "H3: EM equities (EEM) respond differently to VIX signals than SPY",
                    "H4: Correlation clustering identifies optimal multi-asset groups"
                ],
                "prior_related": ["K662 (commodity VT NULL)", "K706 (SPY-GLD correlation)"],
                "data_readiness": "Immediate — all available via yfinance"
            },
            {
                "id": "U4",
                "direction": "Conditional correlation strategies",
                "novelty": "MEDIUM — builds on K706 finding",
                "description": "K706 found SPY-GLD correlation ranges from -0.35 to +0.44 "
                               "(252d rolling). When correlation is high (>0.2), diversification "
                               "benefit drops. Could adjust weights conditional on rolling correlation. "
                               "K706 also found vol ratio trends upward (SPY getting relatively more "
                               "volatile vs GLD) — this suggests dynamic adjustment may help.",
                "specific_hypotheses": [
                    "H1: Adjust SPY/GLD weights when rolling corr > 0.2 or < -0.2",
                    "H2: When vol ratio > 1.5x, shift toward lower-vol asset (GLD)",
                    "H3: DCC-GARCH conditional weights beat fixed 50/50 (K312 started this)",
                    "H4: Regime-switching allocation (K706 bear/normal/bull corr regimes)"
                ],
                "prior_related": ["K706 (correlation stability)", "K312 (DCC-GARCH)", "K360 (dynamic vs fixed)"],
                "caution": "K360 already showed fixed beats dynamic on Sharpe. "
                           "Conditional correlation must pass cross-OOS to avoid overfitting."
            },
            {
                "id": "U5",
                "direction": "VT for bonds / fixed income (TLT)",
                "novelty": "MEDIUM — same method, fundamentally different asset",
                "description": "All VT research so far is equity-centric. Bond vol has different "
                               "dynamics: interest rate driven, less fat-tailed, different "
                               "vol-return relationship (no leverage effect for bonds). "
                               "MOVE index is the bond VIX. Does VT work for bond portfolios?",
                "specific_hypotheses": [
                    "H1: GJR-GARCH gamma is near zero for TLT (no leverage effect)",
                    "H2: MOVE index predicts TLT vol better than VIX",
                    "H3: Bond VT reduces MDD during 2022 rate hike (-30% TLT drawdown)",
                    "H4: SPY VT + TLT VT cross-asset strategy"
                ],
                "data_sources": ["TLT (yfinance)", "MOVE index (FRED: BAMLMOVE)"],
                "prior_related": ["K662 (commodity VT)"]
            },
            {
                "id": "U6",
                "direction": "Google Trends as fear proxy",
                "novelty": "HIGH — alternative data, zero overlap with VIX",
                "description": "Da, Engelberg & Gao (2015) RFS showed Google search volume for "
                               "'recession', 'stock market crash', etc. predicts market returns. "
                               "If this captures retail investor fear independent of VIX, "
                               "it could be a complementary signal.",
                "specific_hypotheses": [
                    "H1: Google Trends 'recession' search volume predicts next-week vol beyond VIX",
                    "H2: Google Trends fear index leads VIX by 1-3 days (retail fear precedes institutional)",
                    "H3: Combining VIX + Google Trends improves vol forecast vs VIX alone"
                ],
                "data_sources": ["pytrends (Google Trends API — free)", "yfinance (VIX)"],
                "prior_related": [],
                "barrier": "Google Trends data has low frequency (weekly) and rate limits"
            },
            {
                "id": "U7",
                "direction": "Behavioral finance — disposition effect in VT context",
                "novelty": "HIGH — different paradigm entirely",
                "description": "K629 tested CGO (Capital Gains Overhang) as VT overlay and got NULL. "
                               "But the behavioral angle is broader: do investors systematically "
                               "mis-time VT entries? Is there a 'VT disposition effect' where investors "
                               "exit VT positions too early after seeing Sharpe lag? "
                               "This connects to the K688 utility framework.",
                "specific_hypotheses": [
                    "H1: Investors who exit VT after 6 months of underperformance lose the insurance benefit",
                    "H2: Dollar-weighted returns of VT are lower than time-weighted (gap = behavioral cost)",
                    "H3: The gamma>=5 threshold from K688 maps to measurable loss aversion parameters"
                ],
                "prior_related": ["K629 (CGO NULL)", "K688 (CRRA utility)"],
                "data_readiness": "Simulation-based — can compute with existing data"
            },
            {
                "id": "U8",
                "direction": "Crypto/DeFi volatility dynamics",
                "novelty": "HIGH — different market microstructure entirely",
                "description": "24/7 trading, no circuit breakers, extreme vol, different return "
                               "distribution (positive skew for BTC vs negative for SPY). "
                               "K664 briefly explored BTC but focused on VIX sufficiency test. "
                               "A full crypto VT study is unexplored.",
                "specific_hypotheses": [
                    "H1: GJR-GARCH gamma is different sign for BTC (no leverage effect, momentum effect?)",
                    "H2: BTC-ETH correlation is too high for diversification benefit",
                    "H3: DeFi yields correlate with crypto vol — high vol = high yields (risk premium)",
                    "H4: BTC VT strategy feasibility (extreme turnover vs insurance benefit)"
                ],
                "prior_related": ["K664 (BTC VIX test)"],
                "data_readiness": "BTC-USD via yfinance. DeFi yields need alternative sources."
            }
        ]
    },

    # ========================================================================
    # SECTION 4: WEBSITE FOCUS
    # ========================================================================
    "section_4_website": {
        "description": "Website changes needed to align with post-K687 paradigm shift.",
        "immediate_priority": [
            {
                "id": "W1",
                "task": "K705 HIGH severity messaging fixes",
                "gaps": ["GAP-01", "GAP-03", "GAP-07", "GAP-08"],
                "summary": "Change '投資建議' to '風險管理配置', lead with MDD not Sharpe, "
                           "reframe performance metrics positively, add insurance framing.",
                "effort": "1-2 hours frontend changes + deploy",
                "impact": "Prevents misleading visitors about VT capabilities"
            },
            {
                "id": "W2",
                "task": "K707 FAQ as /guide page",
                "summary": "20 research-backed FAQs ready to deploy as /guide content. "
                           "Expandable accordion format. Each answer cites experiments.",
                "effort": "2-3 hours frontend page creation",
                "impact": "Major user experience improvement — answers the questions visitors actually ask"
            }
        ],
        "high_priority": [
            {
                "id": "W3",
                "task": "Strategy descriptions post-K693 audit",
                "summary": "Verify all hardcoded performance numbers against corrected metrics. "
                           "Update StrategySelector stats objects and VIX calculator ranges.",
                "effort": "1 hour data verification + code changes"
            },
            {
                "id": "W4",
                "task": "Insurance framing throughout site",
                "summary": "Unified messaging: VT = insurance premium. Every strategy page should "
                           "clearly state 'MDD reduction is the goal, not Sharpe improvement'. "
                           "Add 'insurance cost' metric (Sharpe gap vs BH 50/50).",
                "effort": "2 hours content + code changes"
            }
        ],
        "medium_priority": [
            {
                "id": "W5",
                "task": "Google Search Console registration",
                "summary": "W1.1-W1.3 done (robots.txt, sitemap, OG tags, JSON-LD). "
                           "W1.4 (GSC registration) still pending — needs manual action.",
                "effort": "30 minutes manual setup"
            },
            {
                "id": "W6",
                "task": "Hero Section value proposition update",
                "summary": "Current: '用科學方法管理投資風險'. Good direction. "
                           "Add: specific MDD reduction number (34% to 7%), "
                           "insurance framing, experiment count update (200+ → 700+).",
                "effort": "1 hour"
            }
        ]
    },

    # ========================================================================
    # SECTION 5: PRIORITY RANKING
    # ========================================================================
    "section_5_priority_matrix": {
        "description": "Combined priority ranking across all categories.",
        "tier_1_this_week": [
            "A5: K705 messaging fixes (4 HIGH gaps) — credibility risk if left unfixed",
            "A4: Paper corrections (VT=insurance) — academic integrity",
            "A2: NFP 04/03 coverage (pre-event 04/01-02, post-event 04/04)",
            "A7: Strategy descriptions audit (post-K693 numbers)"
        ],
        "tier_2_next_two_weeks": [
            "A1: HAR-RV with 5-min data (ready 04/11) — MOST EXCITING research direction",
            "A3: TSMC coverage (04/10 revenue, 04/16 earnings)",
            "A6: K707 FAQ as /guide page",
            "U3-H1: 3-asset portfolio test (SPY/GLD/TLT) — immediate data available"
        ],
        "tier_3_this_month": [
            "U1: Full intraday alpha study (after HAR-RV baseline)",
            "U4: Conditional correlation strategies (build on K706)",
            "U5: Bond VT (TLT + MOVE index)",
            "U6: Google Trends as fear proxy"
        ],
        "tier_4_exploratory": [
            "U2: NLP sentiment pipeline (data acquisition needed)",
            "U7: Behavioral finance simulation",
            "U8: Crypto/DeFi VT study"
        ]
    },

    # ========================================================================
    # SECTION 6: RESEARCH EFFICIENCY LESSONS
    # ========================================================================
    "section_6_efficiency_lessons": {
        "from_87_experiments": [
            {
                "lesson": "Codex review is non-negotiable for any strategy claiming alpha",
                "evidence": "3/3 times Codex was called on suspicious results, it found bugs. "
                            "K679 Percentile: Sharpe 1.68 → 0.355 (100% artifact).",
                "rule": "Sharpe > 1.0 on VIX-based strategy → mandatory Codex review before publishing"
            },
            {
                "lesson": "Cross-OOS catches 53% of false positives",
                "evidence": "K459/K474/K476: cross-OOS rejected strategies that passed single-period OOS. "
                            "K699: Contrarian passed 3/5 periods but not robust enough.",
                "rule": "Minimum 5-period cross-OOS before any strategy claims"
            },
            {
                "lesson": "Smooth weights are the most important design principle",
                "evidence": "K690: 12/VIX and Risk Parity survive lag perfectly (autocorr 0.99). "
                            "Piecewise and regime-switching are fragile. "
                            "Any new strategy must have weight autocorrelation > 0.95.",
                "rule": "New strategy design: maximize weight smoothness, not in-sample Sharpe"
            },
            {
                "lesson": "Stop testing VIX overlays — VIX is sufficient",
                "evidence": "31 confirmations that VIX is sufficient statistic for equity vol. "
                            "Term structure, roll yield, seasonality, macro indicators — all NULL OOS. "
                            "The information is already in VIX level.",
                "rule": "No more 'VIX + X' experiments unless X is a genuinely different data source "
                        "(not another VIX derivative)"
            },
            {
                "lesson": "Agent efficiency: timeout ≠ method failure",
                "evidence": "K419→K426: same method, 1.5s vs timeout after vectorization. "
                            "Always check code efficiency before concluding method doesn't work.",
                "rule": "Pre-estimate runtime. If > 3 min, optimize before running."
            }
        ]
    },

    # ========================================================================
    # SECTION 7: WHAT THIS SESSION WOULD HAVE DONE DIFFERENTLY
    # ========================================================================
    "section_7_retrospective": {
        "what_went_well": [
            "Codex review caught K679 lookahead — saved from publishing false results",
            "K693 paper_trading correction was thorough (9,935 entries)",
            "K700 meta-analysis provided honest accounting of all 80 experiments",
            "Insurance paradigm (K687/K688) is a genuinely important reframing",
            "K707 FAQ is immediately useful for the website"
        ],
        "what_could_improve": [
            "K679-K685: 6 follow-up experiments built on a bug — should have Codex-reviewed K679 first",
            "Too many VIX overlay tests (K638, K649, K651, K666, K671) — VIX sufficiency "
            "was already established, these were foreseeable null results",
            "K698 Contrarian could have been caught earlier with proper BH baseline verification",
            "Should have started 5-min data collection 30 days earlier — would be HAR-RV ready now"
        ],
        "paradigm_evolution": {
            "start_of_session": "VT generates alpha, optimize VIX signal",
            "end_of_session": "VT is insurance, 50/50 is optimal, alpha from VIX is impossible",
            "sessions_to_reach_clarity": 1,
            "experiments_to_reach_clarity": 87,
            "key_turning_point": "K686 (Codex review of K679 Percentile) + K687 (proper lag on all strategies)"
        }
    }
}

# Save results
output_path = "experiments/k708_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"K708 results saved to {output_path}")
print(f"\nROADMAP SUMMARY:")
print(f"  SETTLED: {len(results['section_1_settled']['settled_conclusions'])} conclusions (do not revisit)")
print(f"  ACTIONABLE: {len(results['section_2_actionable']['tasks'])} tasks for next session")
print(f"  UNEXPLORED: {len(results['section_3_unexplored']['directions'])} genuinely new directions")
print(f"  WEBSITE: {len(results['section_4_website']['immediate_priority']) + len(results['section_4_website']['high_priority'])} priority changes")
print(f"  LESSONS: {len(results['section_6_efficiency_lessons']['from_87_experiments'])} key efficiency lessons")
print(f"\nTOP 3 NEXT SESSION PRIORITIES:")
print(f"  1. Fix website messaging (K705 HIGH gaps) — credibility risk")
print(f"  2. Paper corrections (VT=insurance paradigm) — academic integrity")
print(f"  3. HAR-RV with 5-min data (ETA 04/11) — most exciting new research")
