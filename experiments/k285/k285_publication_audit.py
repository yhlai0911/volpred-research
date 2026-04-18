"""
K285: Publication Readiness Audit — Are Our 3 Papers Ready to Submit?
=====================================================================
[提出: User, 執行: Claude]

Background: K274 mapped paper contributions. K276 identified JBF updates.
This is a final pre-submission checklist for all 3 papers.

Methodology: SYNTHESIS only — reading existing paper TeX files, compilation
logs, and knowledge entries. No new experiments.
"""

import json
from datetime import datetime
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent

audit = {
    "experiment_id": "K285",
    "title": "Publication Readiness Audit — Are Our 3 Papers Ready to Submit?",
    "date": "2026-03-24",
    "type": "synthesis",
    "methodology": "Read all 3 paper TeX files, check cross-references, "
                   "citations, tables, figures, compilation warnings, and "
                   "map recent findings not yet incorporated.",

    # ========================================================================
    # PAPER 1: Leverage Direction Matters (JBF target)
    # ========================================================================
    "paper_1_leverage_direction": {
        "target_journal": "Journal of Banking & Finance",
        "file": "paper/leverage-direction/main.tex",
        "body_file": "paper/leverage-direction/body.tex",
        "pages": "~60 (double-spaced)",
        "word_count_estimate": "~18,000",
        "sections": 8,  # Intro, Lit Review, Data, Results, Discussion, Conclusion, Appendix A (Commodity), Appendix B (TZ), Practical Summary
        "tables": 14,  # desc, gamma, qlike, var, var_panel, vt, window, hybrid, amplify, tail, gamma-mechanism, complexity_ceiling, nulls, tz_arbitrage
        "figures": 6,   # rolling_gamma, vix_garch_ratio, cumulative_returns, gamma_mechanism, vix_weight_timeline, mdd_comparison
        "references": 46,
        "cover_letter": True,
        "highlights": True,
        "review_report": True,  # review_report.tex exists

        "abstract": {
            "status": "COMPLETE",
            "matches_findings": True,
            "issues": [
                "Abstract mentions 'Spearman rho=0.886, p=0.019 for six equity-type assets' — matches body (line 13).",
                "Abstract mentions 'rho=0.944' for MDD vs base vol — matches body.",
                "Abstract covers all 3 contributions accurately.",
            ],
        },

        "tables_audit": {
            "status": "PARTIAL ISSUE",
            "present_tables": [
                "tab:desc (Table 1 — descriptive stats)",
                "tab:gamma (Table 2 — gamma rolling estimates)",
                "tab:qlike (Table 3 — GARCH vs GJR QLIKE)",
                "tab:var (Table 4 — VaR attribution)",
                "tab:var_panel (Table 5 — VaR backtest panel)",
                "tab:vt (Table 6 — cross-asset VT performance)",
                "tab:window (Table 7 — window size robustness)",
                "tab:hybrid (Table 8 — hybrid VT comparison)",
                "tab:amplify (Table 9 — diversification amplification)",
                "tab:tail (Table 10 — tail risk metrics)",
                "tab:gamma-mechanism (Table 11 — gamma-mechanism mapping)",
                "tab:complexity_ceiling (referenced, LABEL EXISTS in body line 547)",
                "tab:nulls (Table — comprehensive null results, in table_nulls.tex)",
                "tab:tz_arbitrage (Table — TZ momentum, in body line 631)",
            ],
            "missing_tables": [
                "tab:qlike_ceiling — UNDEFINED REFERENCE. Referenced at body line 372 "
                "but NO \\label{tab:qlike_ceiling} in body.tex, tables.tex, or table_nulls.tex. "
                "The table WAS in additions_jk.tex but was NOT integrated into body.tex — "
                "only the text paragraphs were copied, not the table itself.",
            ],
            "action_needed": "HIGH PRIORITY: Copy the tab:qlike_ceiling table from additions_jk.tex "
                           "into body.tex at the appropriate location (after line 376).",
        },

        "figures_audit": {
            "status": "COMPLETE",
            "figures_present": [
                "fig_rolling_gamma.pdf — exists in directory",
                "fig_vix_garch_ratio.pdf — exists in directory",
                "fig_cumulative_returns.pdf — exists in directory",
                "fig_gamma_mechanism.pdf — exists in directory",
                "fig_vix_weight_timeline.pdf — exists in directory",
                "fig_mdd_comparison.pdf — exists in directory",
                "fig_kurtosis_reduction.pdf — exists but NOT referenced in body (unused)",
            ],
            "missing_figures": [],
        },

        "references_audit": {
            "status": "STYLE ISSUE",
            "total_bibitems": 46,
            "citation_style_issue": (
                "CRITICAL: body.tex uses MIXED citation style. Most references are "
                "inline text (e.g., 'Bollerslev (1986)') without \\cite{}, while "
                "11 uses of \\citet{} exist (lines 15, 374, 376, 383, 389, 429, "
                "512, 523, 590, 624, 650). This means most bibitems appear 'unused' "
                "by LaTeX — they show in the bibliography but are NOT hyperlinked. "
                "For JBF submission, ALL citations should use \\citet{} or \\citep{} "
                "for proper formatting and hyperlinks."
            ),
            "unused_bibitems": [
                "Most bibitems appear formally unused because citations are inline text, "
                "not \\cite commands. After converting to proper \\cite style, check for "
                "any truly unused references."
            ],
        },

        "undefined_references": {
            "status": "2 UNDEFINED",
            "items": [
                {
                    "ref": "tab:qlike_ceiling",
                    "location": "body.tex line 372",
                    "cause": "Table not integrated from additions_jk.tex",
                    "fix": "Copy table from additions_jk.tex lines 16-45 into body.tex",
                    "effort": "5 minutes",
                },
                {
                    "ref": "sec:timing_bias",
                    "location": "body.tex line 626 (TZ appendix)",
                    "cause": "Section label sec:timing_bias does not exist anywhere in body.tex. "
                             "The text references 'the same-day timing bias in VIX strategies "
                             "(Section sec:timing_bias)' but there is no such labeled section.",
                    "fix": "Either add \\label{sec:timing_bias} to the appropriate VT timing "
                           "discussion section, or change the reference to point to sec:timing_tests "
                           "(the formal market timing tests section).",
                    "effort": "5 minutes",
                },
            ],
        },

        "contribution_claims_supported": {
            "status": "YES — all 3 contributions well-supported",
            "contribution_1": "Leverage direction taxonomy — supported by Table 2 (gamma), "
                            "Table 3 (QLIKE DM tests), 26-asset validation, crisis validation.",
            "contribution_2": "Gamma predicts VT alpha mechanism — supported by Table 11 "
                            "(gamma-mechanism), rho=0.886 for 6 equity assets, OOS rho=0.821.",
            "contribution_3": "Time-zone arbitrage — supported by Table tz_arbitrage, "
                            "6 markets with t>3.0, c2c vs o2o caveat clearly stated.",
        },

        "limitations_stated": {
            "status": "YES — Section 5.6 (Limitations and Future Directions)",
            "issues": [
                "Sample period (2017-2025) relatively short for some assets",
                "Yahoo Finance data (not Bloomberg) — noted in methodology",
                "7 primary assets may not cover all asset classes",
                "Daily frequency only — intraday not tested",
            ],
        },

        "recent_findings_not_in_paper": {
            "status": "5 HIGH-PRIORITY ADDITIONS IDENTIFIED (from K276)",
            "items": [
                {
                    "id": "K273",
                    "title": "Crash Taxonomy Table",
                    "description": "VT wins 6/6 crash types (100%). Strongest when GLD fails (+41.1pp). "
                                   "This is the single most compelling VT evidence.",
                    "effort_hours": 0.5,
                    "priority": "HIGH",
                    "section": "Add to Section 5.5 (VT as Volatility Insurance) or new subsection",
                },
                {
                    "id": "K272_correction",
                    "title": "VT Insurance Premium Correction",
                    "description": "Insurance cost is ~1%/yr Sharpe drag, not 4%/yr as some sections state. "
                                   "Need to reconcile across paper.",
                    "effort_hours": 0.5,
                    "priority": "HIGH",
                    "section": "Multiple sections reference insurance cost",
                },
                {
                    "id": "K269",
                    "title": "SPY-GLD Correlation Regime",
                    "description": "Correlation NOT stable — 2022 rate hike corr=0.44. "
                                   "Relevant to 50/50 blend discussion.",
                    "effort_hours": 0.5,
                    "priority": "MEDIUM",
                    "section": "Discussion or Appendix",
                },
                {
                    "id": "K228",
                    "title": "Gamma Secular Decline",
                    "description": "SPY gamma declining over decades. Implications for leverage taxonomy stability.",
                    "effort_hours": 0.5,
                    "priority": "MEDIUM",
                    "section": "Discussion — forward-looking implications",
                },
                {
                    "id": "K149",
                    "title": "ICL Null Result",
                    "description": "Regime-dependent ICL test — important null result for Table nulls.",
                    "effort_hours": 0.3,
                    "priority": "LOW",
                    "section": "Already covered by tab:nulls comprehensiveness",
                },
            ],
        },

        "overall_readiness": "85% — NEARLY READY",
        "must_fix_before_submission": [
            "1. Fix tab:qlike_ceiling undefined reference (5 min)",
            "2. Fix sec:timing_bias undefined reference (5 min)",
            "3. Convert inline text citations to \\citet{}/\\citep{} throughout body.tex (2-3 hours)",
            "4. Add K273 crash taxonomy table (0.5 hours)",
            "5. Reconcile VT insurance premium cost (1% vs 4%/yr) across paper (0.5 hours)",
        ],
        "nice_to_have": [
            "6. Add K269 correlation regime discussion",
            "7. Add K228 gamma secular decline discussion",
            "8. Remove unused fig_kurtosis_reduction.pdf from directory",
            "9. Verify all 46 bibitems are actually needed after citation style fix",
        ],
        "estimated_effort_hours": {
            "must_fix": 3.5,
            "nice_to_have": 2.0,
            "total": 5.5,
        },
    },

    # ========================================================================
    # PAPER 2: Taiwan VT + TZ Information Transmission (PBFJ target)
    # ========================================================================
    "paper_2_taiwan_vt": {
        "target_journal": "Pacific-Basin Finance Journal",
        "file": "paper/taiwan-vt/main.tex",
        "body_file": "paper/taiwan-vt/body.tex",
        "pages": "~34 (double-spaced)",
        "word_count_estimate": "~12,000",
        "sections": 9,  # Intro, Data, Leverage, VT, TZ, Macro, VaR, Discussion, Conclusion
        "tables": 5,    # summary_stats, gamma, vt_results, tz_results, sharpe_reconciliation
        "figures": 0,
        "references": 16,
        "cover_letter": False,
        "highlights": False,

        "abstract": {
            "status": "COMPLETE but OVERLOADED",
            "matches_findings": True,
            "issues": [
                "Abstract is ~350 words — VERY long for PBFJ (typical: 150-200 words).",
                "Tries to cover 4+ distinct contributions: leverage amplification, VT, "
                "TZ momentum, macro indicators, VaR, TSMC concentration.",
                "ACTION: Trim to ~200 words, focus on top 3 contributions.",
            ],
        },

        "tables_audit": {
            "status": "COMPLETE",
            "present_tables": [
                "tab:summary_stats — Summary statistics",
                "tab:gamma — GJR-GARCH gamma for Taiwan assets",
                "tab:vt_results — VT strategy results",
                "tab:tz_results — Time-zone momentum results",
                "tab:sharpe_reconciliation — Sharpe ratio reconciliation",
            ],
            "missing_tables": [
                "NONE — but only 5 tables for a 34-page paper is SPARSE. "
                "Consider adding: VaR backtest results table, macro indicator "
                "regression table, TSMC decomposition table.",
            ],
        },

        "figures_audit": {
            "status": "NONE — NO FIGURES",
            "figures_present": [],
            "missing_figures": [
                "CRITICAL: A 34-page paper with ZERO figures is unusual for PBFJ. "
                "Recommended additions: (1) Rolling gamma plot for 0050.TW, "
                "(2) VT weight timeline, (3) Cumulative return comparison "
                "(B&H vs VT), (4) c2c vs o2o return decomposition chart.",
            ],
        },

        "references_audit": {
            "status": "COMPLETE — all cited refs have bibitems",
            "total_bibitems": 16,
            "citation_style_issue": (
                "References use proper \\citet{}/\\citep{} throughout — good. "
                "However, only 16 references is THIN for a PBFJ paper. "
                "Typical PBFJ papers cite 30-50 references. Need to add: "
                "Taiwan-specific finance literature, Asian market microstructure, "
                "opening auction efficiency literature, more VT/GARCH references."
            ),
            "missing_references": [
                "Nelson (1991) — EGARCH, cited in text but no bibitem",
                "Ang and Chen (2002) — only PBFJ-relevant asymmetric correlation ref",
                "Need Taiwan stock market studies (Chen et al., various years)",
                "Need Asia-Pacific market studies",
                "Need opening auction/call market literature",
            ],
        },

        "undefined_references": {
            "status": "0 UNDEFINED — compilation clean",
            "items": [],
        },

        "contribution_claims_supported": {
            "status": "YES — all claims supported",
            "contribution_1": "Diversification amplification 4.6x — supported by tab:gamma, "
                            "but carefully caveated with 1.45x for investable 0050.TW.",
            "contribution_2": "VT for Taiwan — supported by tab:vt_results, VaR section.",
            "contribution_3": "TZ information transmission — supported by tab:tz_results, "
                            "c2c vs o2o caveat clearly stated.",
            "contribution_4": "Leading indicator — supported by t=3.74 in body, "
                            "DM p=0.0005 for combined strategy.",
        },

        "limitations_stated": {
            "status": "YES — Section 9 (Conclusion) lists 5 limitations",
            "adequacy": "Good — covers VIXTWN history, c2c bias, rolling window, "
                       "single-market generalizability, TSMC concentration.",
        },

        "recent_findings_not_in_paper": {
            "status": "1 potentially relevant",
            "items": [
                {
                    "id": "K284",
                    "title": "Current Market Status (2026-03-23)",
                    "description": "VIX 26.7, HIGH regime. Could add as real-time validation "
                                   "paragraph but not essential for submission.",
                    "effort_hours": 0.5,
                    "priority": "LOW",
                },
            ],
        },

        "overall_readiness": "70% — NEEDS WORK",
        "must_fix_before_submission": [
            "1. Trim abstract to ~200 words (0.5 hours)",
            "2. Add 3-4 figures (rolling gamma, VT weights, cumulative returns, c2c/o2o) (3-4 hours)",
            "3. Expand reference list to 30+ entries with Taiwan/Asia-Pacific literature (2 hours)",
            "4. Write cover letter (0.5 hours)",
            "5. Add at least 2 more tables (VaR results, macro regressions) (1-2 hours)",
        ],
        "nice_to_have": [
            "6. Add highlights.txt for PBFJ submission",
            "7. Add currency risk analysis table",
            "8. Expand discussion of retail investor behavior implications",
        ],
        "estimated_effort_hours": {
            "must_fix": 8.0,
            "nice_to_have": 3.0,
            "total": 11.0,
        },
    },

    # ========================================================================
    # PAPER 3: Is VT Just Trend Following? (target TBD)
    # ========================================================================
    "paper_3_vt_trend_following": {
        "target_journal": "TBD — candidates: Journal of Portfolio Management, "
                         "Journal of Financial Economics (reach), Financial Analysts Journal",
        "file": "paper/vt-trend-following/main.tex",
        "body_file": "SELF-CONTAINED (no separate body.tex)",
        "pages": "~24 (double-spaced)",
        "word_count_estimate": "~10,000",
        "sections": 5,  # Intro, Data/Methodology, Results, Discussion, Conclusion
        "tables": 5,    # alpha_decomp, cross_section, dual_mechanism, ff5, international
        "figures": 0,
        "references": 18,
        "cover_letter": False,
        "highlights": False,

        "abstract": {
            "status": "COMPLETE",
            "matches_findings": True,
            "issues": [
                "Abstract at ~250 words — appropriate length.",
                "Covers all 3 contributions clearly.",
                "Statistics match body (r=0.564 p=0.006, 90-97% MDD retention, "
                "13/13 markets, t=15.70).",
            ],
        },

        "tables_audit": {
            "status": "COMPLETE",
            "present_tables": [
                "tab:alpha_decomp — Alpha decomposition (22 assets, elaborate table)",
                "tab:cross_section — Cross-sectional predictors (N=22)",
                "tab:dual_mechanism — Dual mechanism decomposition (SPY + 50/50 blend)",
                "tab:ff5 — Fama-French 5-factor regression",
                "tab:international — International VT (13 markets)",
            ],
            "missing_tables": [
                "NONE critical. Tables are comprehensive and well-formatted with "
                "threeparttable notes. Consider adding a sub-period stability table "
                "instead of relegating to Online Appendix.",
            ],
        },

        "figures_audit": {
            "status": "NONE — NO FIGURES",
            "figures_present": [],
            "missing_figures": [
                "RECOMMENDED: (1) Scatter plot of gamma vs TSMOM loading (the key "
                "cross-sectional relationship), (2) Cumulative returns: VT vs "
                "TSMOM-hedged VT vs B&H, (3) International MDD protection bar chart.",
            ],
        },

        "references_audit": {
            "status": "MINOR ISSUES",
            "total_bibitems": 18,
            "citation_style_issue": "Uses proper \\citet{}/\\citep{} — good.",
            "unused_bibitems": [
                "barroso2015 — not cited in text",
                "daniel2016 — not cited in text",
                "fleming2001 — not cited in text",
                "harvey2016 — not cited in text (but should be, given Harvey threshold)",
            ],
            "missing_references": [
                "Only 18 references is on the thin side. Need more momentum literature, "
                "drawdown literature, insurance/option pricing connections.",
            ],
        },

        "undefined_references": {
            "status": "0 UNDEFINED — compilation clean",
            "items": [],
        },

        "contribution_claims_supported": {
            "status": "YES — all 3 contributions well-supported",
            "contribution_1": "Gamma predicts TSMOM loading — supported by tab:cross_section, "
                            "r=0.564 p=0.006, bootstrap CI [0.263, 0.772].",
            "contribution_2": "Dual mechanism decomposition — supported by tab:dual_mechanism, "
                            "90-97% MDD retention across 5 assets.",
            "contribution_3": "International VIX as MDD protection — supported by "
                            "tab:international, 13/13 markets, t=15.70.",
        },

        "limitations_stated": {
            "status": "YES — Section 4.4 (Limitations)",
            "adequacy": "Good — covers sample size (22 vs 50 in Hood), OOS period limitations, "
                       "VIX availability, gamma estimation data requirements.",
        },

        "recent_findings_not_in_paper": {
            "status": "3 potentially relevant",
            "items": [
                {
                    "id": "K272",
                    "title": "VT as Synthetic Put",
                    "description": "VT implied strike 85.5%, cost 3.31%/yr — directly supports "
                                   "the 'insurance pricing' interpretation. Could strengthen "
                                   "Section 4.3.",
                    "effort_hours": 1.0,
                    "priority": "MEDIUM",
                },
                {
                    "id": "K273",
                    "title": "Crash Taxonomy (VT wins 6/6)",
                    "description": "VT protective across all crash types. Supports the universal "
                                   "MDD protection claim.",
                    "effort_hours": 0.5,
                    "priority": "MEDIUM",
                },
                {
                    "id": "K279",
                    "title": "Weekly VT NOT Sweet Spot",
                    "description": "Daily dominates all TX costs — relevant to methodology "
                                   "choice justification.",
                    "effort_hours": 0.3,
                    "priority": "LOW",
                },
            ],
        },

        "overall_readiness": "80% — GOOD but needs polish",
        "must_fix_before_submission": [
            "1. Remove 4 unused bibitems (barroso2015, daniel2016, fleming2001, harvey2016) "
            "OR add citations in text where appropriate (0.5 hours)",
            "2. Add 2-3 figures (gamma vs TSMOM scatter, cumulative returns, "
            "international MDD bar chart) (2-3 hours)",
            "3. Choose target journal and adjust formatting (1 hour)",
            "4. Write cover letter (0.5 hours)",
            "5. Expand references to 25+ (1 hour)",
        ],
        "nice_to_have": [
            "6. Add K272 synthetic put analysis to insurance pricing discussion",
            "7. Add sub-period stability table (currently referenced as Online Appendix)",
            "8. Add K273 crash taxonomy evidence",
        ],
        "estimated_effort_hours": {
            "must_fix": 5.0,
            "nice_to_have": 2.5,
            "total": 7.5,
        },
    },

    # ========================================================================
    # CROSS-PAPER ISSUES
    # ========================================================================
    "cross_paper_issues": {
        "self_citation_consistency": {
            "status": "CHECK NEEDED",
            "details": (
                "Paper 3 cites \\citet{lai2026a} (Paper 1) as 'Working Paper'. "
                "Paper 2 body refers to Paper 1 findings. Need to ensure: "
                "(1) Paper numbering is consistent, (2) self-citations use "
                "correct title, (3) if Paper 1 is accepted first, update "
                "citation in Papers 2 & 3."
            ),
        },
        "overlapping_content": {
            "status": "MODERATE OVERLAP — needs attention",
            "details": [
                "Paper 1 (Appendix B) covers TZ momentum for 6 Asian markets — "
                "Paper 2 covers TZ momentum for Taiwan/Japan in detail. "
                "RISK: Reviewer may see self-plagiarism if submitted simultaneously.",
                "Paper 1 covers VT cross-asset — Paper 3 covers VT vs TSMOM. "
                "Some VT performance tables overlap.",
                "RECOMMENDATION: Submit Paper 1 first, then Paper 2 & 3 after "
                "Paper 1 is accepted (or at least under review). Paper 1's "
                "appendices establish findings that Papers 2 & 3 extend.",
            ],
        },
        "hood2025_citation": {
            "status": "INCONSISTENT",
            "details": (
                "Paper 1 cites 'Hood and Raughtigan (2025)' while Paper 3 cites "
                "'Hood, M., & Raughtigan, J. (2025)' with different first names. "
                "Paper 1: 'Hood, B., & Raughtigan, C.' vs Paper 3: 'Hood, M., & "
                "Raughtigan, J.' — verify correct author names."
            ),
        },
    },

    # ========================================================================
    # SUBMISSION PRIORITY & TIMELINE
    # ========================================================================
    "submission_priority": {
        "recommended_order": [
            {
                "rank": 1,
                "paper": "Paper 1: Leverage Direction Matters",
                "journal": "JBF",
                "readiness": "85%",
                "effort_to_ready": "3.5 hours (must-fix only)",
                "reason": "Most complete, broadest contribution, 70% NOVEL content (K274). "
                         "Fix 2 undefined refs + citation style = submittable.",
            },
            {
                "rank": 2,
                "paper": "Paper 3: VT vs Trend Following",
                "journal": "JPM or FAJ",
                "readiness": "80%",
                "effort_to_ready": "5 hours",
                "reason": "Clean compilation, strong tables, focused contribution. "
                         "Needs figures and expanded references.",
            },
            {
                "rank": 3,
                "paper": "Paper 2: Taiwan VT + TZ",
                "journal": "PBFJ",
                "readiness": "70%",
                "effort_to_ready": "8 hours",
                "reason": "Needs most work: no figures, thin references, long abstract. "
                         "Wait for Paper 1 to establish priority.",
            },
        ],
        "total_estimated_effort": "16.5 hours for must-fix across all 3 papers",
        "recommended_next_steps": [
            "STEP 1: Fix Paper 1's 2 undefined references (10 minutes)",
            "STEP 2: Convert Paper 1's inline citations to \\citet{} (2-3 hours)",
            "STEP 3: Add K273 crash taxonomy table to Paper 1 (30 minutes)",
            "STEP 4: Fix Hood/Raughtigan author name inconsistency across papers",
            "STEP 5: Generate figures for Papers 2 & 3",
            "STEP 6: Expand reference lists for Papers 2 & 3",
            "STEP 7: Write cover letters for Papers 2 & 3",
        ],
    },

    # ========================================================================
    # SUMMARY SCORECARD
    # ========================================================================
    "scorecard": {
        "paper_1_jbf": {
            "abstract": "PASS",
            "tables": "FAIL (1 undefined ref: tab:qlike_ceiling)",
            "figures": "PASS (6 figures, all present)",
            "references": "FAIL (mixed citation style, needs conversion)",
            "contributions": "PASS",
            "limitations": "PASS",
            "cover_letter": "PASS",
            "compilation": "FAIL (2 undefined references)",
            "overall": "85% — 3.5 hours to fix",
        },
        "paper_2_pbfj": {
            "abstract": "FAIL (too long, ~350 words)",
            "tables": "MARGINAL (5 tables for 34 pages — sparse)",
            "figures": "FAIL (0 figures)",
            "references": "FAIL (only 16, need 30+)",
            "contributions": "PASS",
            "limitations": "PASS",
            "cover_letter": "MISSING",
            "compilation": "PASS (clean)",
            "overall": "70% — 8 hours to fix",
        },
        "paper_3_vt_tf": {
            "abstract": "PASS",
            "tables": "PASS (5 well-formatted tables)",
            "figures": "FAIL (0 figures)",
            "references": "MARGINAL (18, 4 unused bibitems)",
            "contributions": "PASS",
            "limitations": "PASS",
            "cover_letter": "MISSING",
            "compilation": "PASS (clean)",
            "overall": "80% — 5 hours to fix",
        },
    },
}

# Save results
output_path = EXPERIMENT_DIR / "k285_publication_audit.json"
with output_path.open("w", encoding="utf-8") as f:
    json.dump(audit, f, indent=2, ensure_ascii=False)

print("=" * 70)
print("K285: PUBLICATION READINESS AUDIT — SUMMARY")
print("=" * 70)

print("\n--- PAPER 1: Leverage Direction Matters (JBF) ---")
print(f"  Readiness: {audit['paper_1_leverage_direction']['overall_readiness']}")
print(f"  CRITICAL ISSUES:")
print(f"    - 2 undefined LaTeX references (tab:qlike_ceiling, sec:timing_bias)")
print(f"    - Mixed citation style (inline text + \\citet mixed)")
print(f"    - 5 recent findings not yet integrated (K273 crash taxonomy #1 priority)")
print(f"  Effort to submit: ~3.5 hours (must-fix)")

print("\n--- PAPER 2: Taiwan VT + TZ (PBFJ) ---")
print(f"  Readiness: {audit['paper_2_taiwan_vt']['overall_readiness']}")
print(f"  CRITICAL ISSUES:")
print(f"    - ZERO figures (need 3-4)")
print(f"    - Only 16 references (need 30+)")
print(f"    - Abstract too long (~350 words, trim to ~200)")
print(f"    - No cover letter")
print(f"  Effort to submit: ~8 hours")

print("\n--- PAPER 3: VT vs Trend Following (TBD journal) ---")
print(f"  Readiness: {audit['paper_3_vt_trend_following']['overall_readiness']}")
print(f"  CRITICAL ISSUES:")
print(f"    - ZERO figures (need 2-3)")
print(f"    - 4 unused bibitem entries")
print(f"    - No cover letter")
print(f"    - No target journal decided")
print(f"  Effort to submit: ~5 hours")

print("\n--- CROSS-PAPER ISSUES ---")
print(f"  - Hood/Raughtigan author name inconsistency between Paper 1 & 3")
print(f"  - Content overlap: Paper 1 Appendix B ↔ Paper 2 TZ section")
print(f"  - Self-citation consistency needed")

print("\n--- RECOMMENDED SUBMISSION ORDER ---")
print(f"  1. Paper 1 (JBF) — most ready, broadest contribution")
print(f"  2. Paper 3 (JPM/FAJ) — focused, clean")
print(f"  3. Paper 2 (PBFJ) — needs most work, benefits from Paper 1 priority")
print(f"\n  Total effort for all 3: ~16.5 hours")

print(f"\nResults saved to: {output_path}")
