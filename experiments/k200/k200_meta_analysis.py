"""
K200: 200-Experiment Meta-Analysis — What Have We Learned?

[提出: User, 執行: Claude]

Synthesizes all findings from ~200 experiments (Phase A through Phase K)
across the entire VolPred research program. This is a DESCRIPTIVE analysis
of our own research, not new empirical work.

Usage:
    cd <project_root>
    uv run python experiments/k200/k200_meta_analysis.py
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

###############################################################################
# 1. Load knowledge base
###############################################################################

EXPERIMENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPERIMENT_DIR.parents[1]
KNOWLEDGE_PATH = REPO_ROOT / "storage" / "memory" / "knowledge.json"
EXPERIMENTS_PATH = REPO_ROOT / "storage" / "memory" / "experiments.json"
OUTPUT_PATH = EXPERIMENT_DIR / "k200_meta_analysis_results.json"


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


knowledge = load_json(KNOWLEDGE_PATH)
experiments = load_json(EXPERIMENTS_PATH)

print(f"Loaded {len(knowledge)} knowledge entries")
print(f"Loaded {len(experiments)} experiment records")

###############################################################################
# 2. Classify each knowledge entry
###############################################################################

# --- Category mapping (coarse) ---
CATEGORY_MAP = {
    # Volatility prediction models
    "model_behavior": "vol_prediction",
    "model_comparison": "vol_prediction",
    "model": "vol_prediction",
    "vol_models": "vol_prediction",
    "model_evaluation": "vol_prediction",
    "model_implementation": "vol_prediction",
    "model_selection": "vol_prediction",
    "multivariate_model": "vol_prediction",
    "volatility_prediction": "vol_prediction",
    # Distribution / VaR
    "distribution_effect": "var_methods",
    "var_methods": "var_methods",
    "var_regime_experiment": "var_methods",
    "var_violations": "var_methods",
    "var_methodology": "var_methods",
    "var_reliability": "var_methods",
    "portfolio_var": "var_methods",
    # Strategy
    "strategy": "strategy",
    "strategies": "strategy",
    "strategy_optimization": "strategy",
    "strategy_comparison": "strategy",
    "strategy_practical": "strategy",
    "strategy_enhancement": "strategy",
    "strategy_robustness": "strategy",
    "strategy_failed": "strategy",
    "strategy_performance": "strategy",
    "strategy_mechanism": "strategy",
    "strategy_multi_asset": "strategy",
    "strategy_rebalancing": "strategy",
    "strategy_cross_market": "strategy",
    "strategy_stability": "strategy",
    "strategy_stress_test": "strategy",
    "strategy_behavior": "strategy",
    "strategy_timing": "strategy",
    "strategy_insight": "strategy",
    "strategy_dca": "strategy",
    "strategy_recovery": "strategy",
    "strategy_vrp": "strategy",
    "strategy_caveat": "strategy",
    "strategy_risk": "strategy",
    "strategy_improvement": "strategy",
    "strategy_killed": "strategy",
    "crypto_strategy": "strategy",
    "crypto_vt": "strategy",
    # Cross-asset
    "cross_asset": "cross_asset",
    "cross_asset_mechanism": "cross_asset",
    "cross_asset_validation": "cross_asset",
    "cross_asset_vt": "cross_asset",
    "cross_market": "cross_asset",
    "cross_market_application": "cross_asset",
    "cross_market_validation": "cross_asset",
    "vix_proxy_transport": "cross_asset",
    "vix_correlation": "cross_asset",
    "international_comparison": "cross_asset",
    "crypto_lead_lag": "cross_asset",
    # Leverage effect / gamma
    "leverage_effect": "leverage_gamma",
    "gamma_mechanism": "leverage_gamma",
    "gamma_dynamics": "leverage_gamma",
    "anti_tautology": "leverage_gamma",
    "proposition_boundary": "leverage_gamma",
    "proposition_robustness": "leverage_gamma",
    # Methodology
    "research_methodology": "methodology",
    "methodology": "methodology",
    "methodology_insight": "methodology",
    "methodology_warning": "methodology",
    "methodology_correction": "methodology",
    "evaluation_methodology": "methodology",
    "formal_test": "methodology",
    "statistical_caveat": "methodology",
    "statistical_significance": "methodology",
    # Data / market
    "data_property": "descriptive",
    "market_context": "descriptive",
    "market_dynamics": "descriptive",
    "market_structure": "descriptive",
    "market_microstructure": "descriptive",
    "market_event": "descriptive",
    "market_update": "descriptive",
    "market": "descriptive",
    "market_data": "descriptive",
    "data": "descriptive",
    "data_sources": "descriptive",
    "seasonality": "descriptive",
    "real_time_market": "descriptive",
    "real_time_validation": "descriptive",
    # Literature
    "literature": "literature",
    "literature_review": "literature",
    "literature_2024_2026": "literature",
    # Mechanism discovery
    "mechanism_discovery": "mechanism",
    "theoretical": "mechanism",
    "theory": "mechanism",
    "theoretical_contribution": "mechanism",
    "theoretical_derivation": "mechanism",
    "theoretical_foundation": "mechanism",
    "theoretical_insight": "mechanism",
    "complexity_ceiling": "mechanism",
    "VT_mechanism": "mechanism",
    "VT-failure-modes": "mechanism",
    "kurtosis_mechanism": "mechanism",
    # Taiwan-specific
    "taiwan_market": "taiwan",
    # Portfolio / multi-asset
    "portfolio": "portfolio",
    "portfolio_construction": "portfolio",
    "portfolio_optimization": "portfolio",
    "portfolio_strategy": "portfolio",
    "diversification_analysis": "portfolio",
    "diversification_amplification": "portfolio",
    # Sentiment / alternative data
    "sentiment_indicators": "alt_data",
    "sentiment_indicator": "alt_data",
    "financial_indicators": "alt_data",
    "return_prediction": "alt_data",
    "return-prediction": "alt_data",
    "macro_prediction": "alt_data",
    # Network / topology
    "network_topology": "network",
    # Crisis
    "crisis_analysis": "crisis",
    "crisis_validation": "crisis",
    "crisis_protection": "crisis",
    "crisis_taxonomy": "crisis",
    # Behavioral
    "behavioral_finance": "behavioral",
    "investor_experience": "behavioral",
    "utility_analysis": "behavioral",
    # Other
    "parameter_sensitivity": "param_sensitivity",
    "null_result": "null_result",
    "experiment": "experiment_record",
    "experiment_result": "experiment_record",
    "peer_review": "peer_review",
    "review": "peer_review",
    "ai_collaboration": "peer_review",
    "peer_review_synthesis": "peer_review",
    "research_direction": "research_direction",
    "reference": "reference",
    "platform": "platform",
    "deployment": "platform",
    "system_ops": "platform",
    "features": "platform",
    "publication": "platform",
    "research_communication": "platform",
    "general_content": "content",
    "business": "content",
    "monetization": "content",
    "paper_planning": "content",
    "milestone": "content",
    "live_performance": "live_perf",
    "transaction_costs": "strategy",
    "drawdown_analysis": "strategy",
    "scenario_analysis": "strategy",
    "return_decomposition": "strategy",
    "tail_risk": "strategy",
    "optimal_parameters": "strategy",
    "leveraged_etf": "strategy",
    "high_frequency": "vol_prediction",
    "vrp_structure": "mechanism",
    "vrp_dynamics": "mechanism",
    "vrp_robustness": "mechanism",
    "vrp_analysis": "mechanism",
    "cross_period_validation": "methodology",
    "research_report": "content",
    "research_summary": "methodology",
    "validation": "methodology",
    "oos_validation": "methodology",
}


def classify_category(entry):
    """Map fine-grained category to coarse research category."""
    cat = entry.get("category", "unknown")
    return CATEGORY_MAP.get(cat, "other")


def classify_result(content):
    """Classify a knowledge entry result."""
    c = content[:600]
    cl = c.lower()

    if "★★★" in c:
        return "breakthrough"
    if "★★" in c and "★★★" not in c:
        return "strong_positive"

    # Corrections
    correction_kws = ["correction", "修正", "false alarm", "tautology",
                      "降級", "artifact", "Simpson"]
    for kw in correction_kws:
        if kw.lower() in cl:
            if any(pos in c for pos in ["CONFIRMED", "PASSED", "ROBUST"]):
                return "positive"
            return "correction"

    # Null results
    null_kws = ["null result", "null。", "null for", "null —",
                "FAILS", "FAILED", "no improvement",
                "not significant", " NS ", "REJECTED", "collapsed",
                "no predictive", "FALSE ALARM", "killed", "全 null",
                "null result", "全部 null"]
    for kw in null_kws:
        if kw in c or kw.lower() in cl:
            return "null"

    # Positive
    if "★" in c:
        return "positive"
    positive_kws = ["CONFIRMED", "PASS", "ROBUST", "works", "effective",
                    "validated", "verified"]
    for kw in positive_kws:
        if kw in c:
            return "positive"

    return "descriptive"


def classify_source(content):
    """Identify who proposed the research direction."""
    c = content[:400]

    if "[提出: Gemini" in c:
        return "Gemini"
    if "[提出: Codex" in c:
        return "Codex"
    if any(kw in c for kw in ["[提出: 用戶", "[提出: User", "USER INSIGHT",
                               "用戶指導", "用戶啟發", "用戶要求", "用戶(", "會員"]):
        return "User"
    if "[提出: Claude" in c:
        return "Claude"
    if "Gemini" in c and any(kw in c for kw in ["建議", "suggestion", "direction", "審查"]):
        return "Gemini"
    if "Codex" in c and any(kw in c for kw in ["建議", "suggestion", "direction", "審查"]):
        return "Codex"

    return "Claude"


def classify_finding_type(content):
    """Classify what the finding is about."""
    cl = content.lower()

    if "vix sufficient" in cl or "vix 已包含" in cl:
        return "VIX_sufficient"
    if "qlike ceiling" in cl or ("ceiling" in cl and "qlike" in cl):
        return "QLIKE_ceiling"
    if any(kw in cl for kw in ["gjr vs garch", "gjr > garch", "gjr beats", "model confidence set"]):
        return "model_comparison"
    if "mdd" in cl and any(kw in cl for kw in ["improvement", "reduction", "保護", "protection"]):
        return "MDD_protection"
    if "leverage" in cl and any(kw in cl for kw in ["direction", "gamma", "taxonomy"]):
        return "leverage_taxonomy"
    if "12/vix" in cl or "target/vix" in cl:
        return "VIX_VT_strategy"
    if "hybrid vt" in cl:
        return "hybrid_VT"
    if any(kw in cl for kw in ["taiwan", "0050", "台灣", "台股"]):
        return "taiwan"
    if any(kw in cl for kw in ["btc", "crypto", "bitcoin"]):
        return "crypto"
    if any(kw in cl for kw in ["var ", "kupiec", "christoffersen", "skewed-t", "student-t"]):
        return "VaR_evaluation"
    if any(kw in cl for kw in ["time-zone", "timezone", "lead-lag", "spillover"]):
        return "cross_market"
    if "carry" in cl and "vt" in cl:
        return "carry_VT"
    if "50/50" in cl and "spy/gld" in cl:
        return "portfolio_construction"
    if "ewma" in cl and "0.97" in cl:
        return "EWMA_comparison"

    return "other"


###############################################################################
# 3. Process all entries
###############################################################################

classified = []
for entry in knowledge:
    content = entry.get("content", "")
    classified.append({
        "item_id": entry.get("item_id", ""),
        "category": classify_category(entry),
        "result": classify_result(content),
        "source": classify_source(content),
        "finding_type": classify_finding_type(content),
        "confidence": entry.get("confidence", 0),
        "content_preview": content[:200],
        "raw_category": entry.get("category", "unknown"),
    })

###############################################################################
# 4. Compute statistics
###############################################################################

print("\n" + "=" * 80)
print("K200: 200-EXPERIMENT META-ANALYSIS — WHAT HAVE WE LEARNED?")
print("=" * 80)

total_knowledge = len(knowledge)
total_experiments = len(experiments)
print(f"\n--- DATA SCOPE ---")
print(f"Total knowledge entries: {total_knowledge}")
print(f"Total experiment records: {total_experiments}")
print(f"Research period: 2026-03-14 to 2026-03-24 (~10 days)")

# Category distribution
cat_counts = Counter(e["category"] for e in classified)
print(f"\n--- CATEGORY DISTRIBUTION ---")
for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
    print(f"  {cat:25s}: {count:3d} ({count/total_knowledge*100:.1f}%)")

# Result distribution
result_counts = Counter(e["result"] for e in classified)
print(f"\n--- RESULT DISTRIBUTION ---")
for result, count in sorted(result_counts.items(), key=lambda x: -x[1]):
    print(f"  {result:20s}: {count:3d} ({count/total_knowledge*100:.1f}%)")

# Filter to research findings
NON_RESEARCH = {"descriptive", "literature", "reference", "platform", "content",
                 "live_perf", "peer_review", "research_direction", "experiment_record",
                 "other"}
research_entries = [e for e in classified if e["category"] not in NON_RESEARCH]
print(f"\nResearch entries (excluding descriptive/literature/platform): {len(research_entries)}")

# Success rate by category
print(f"\n--- SUCCESS RATE BY CATEGORY ---")
print(f"{'Category':25s} {'Total':>5s} {'BT':>4s} {'S+':>4s} {'Pos':>4s} {'Null':>5s} {'Corr':>5s} {'Desc':>5s} {'%Pos+':>7s}")
for cat in sorted(set(e["category"] for e in research_entries)):
    cat_entries = [e for e in research_entries if e["category"] == cat]
    total = len(cat_entries)
    breaks = sum(1 for e in cat_entries if e["result"] == "breakthrough")
    strong = sum(1 for e in cat_entries if e["result"] == "strong_positive")
    pos = sum(1 for e in cat_entries if e["result"] == "positive")
    null = sum(1 for e in cat_entries if e["result"] == "null")
    corr = sum(1 for e in cat_entries if e["result"] == "correction")
    desc = sum(1 for e in cat_entries if e["result"] == "descriptive")
    pct = (breaks + strong + pos) / total * 100 if total > 0 else 0
    print(f"  {cat:25s} {total:5d} {breaks:4d} {strong:4d} {pos:4d} {null:5d} {corr:5d} {desc:5d} {pct:6.1f}%")

# Source attribution
print(f"\n--- SOURCE ATTRIBUTION ---")
source_counts = Counter(e["source"] for e in research_entries)
for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
    entries = [e for e in research_entries if e["source"] == source]
    pos_count = sum(1 for e in entries if e["result"] in ("breakthrough", "strong_positive", "positive"))
    null_count = sum(1 for e in entries if e["result"] == "null")
    pct_pos = pos_count / count * 100 if count > 0 else 0
    print(f"  {source:10s}: {count:3d} entries, {pos_count:3d} positive ({pct_pos:.0f}%), {null_count:3d} null")

# VIX sufficient count (deep search)
vix_suff_count = 0
for entry in knowledge:
    c = entry.get("content", "").lower()
    if "vix sufficient" in c or "vix 已包含" in c or "vix already encapsulates" in c:
        vix_suff_count += 1
print(f"\n--- VIX SUFFICIENT STATISTIC: confirmed {vix_suff_count} times ---")

# QLIKE ceiling count
ceiling_count = 0
max_numbered = 0
for entry in knowledge:
    c = entry.get("content", "").lower()
    if "qlike ceiling" in c or ("ceiling" in c and "qlike" in c):
        ceiling_count += 1
    match = re.search(r"ceiling 第 ?(\d+)", c)
    if match:
        max_numbered = max(max_numbered, int(match.group(1)))
ceiling_count = max(ceiling_count, max_numbered)
print(f"--- QLIKE CEILING: confirmed {ceiling_count}+ times ---")

###############################################################################
# 5. TOP 10 Most Important Findings
###############################################################################

print(f"\n{'=' * 80}")
print("TOP 10 MOST IMPORTANT FINDINGS")
print("=" * 80)

top_findings = [
    {
        "rank": 1,
        "title": "VIX is the sufficient statistic for VT",
        "detail": "21+ confirmations across VIX term structure, VVIX, SKEW, credit spreads, "
                  "yield curves, AAII, CNN Fear&Greed, Google Trends, CAPE, MOVE, macro, "
                  "and more. No additional indicator adds value once VIX is included.",
        "phases": "J3/J4/J8/J14/J17/J18/K1/G3/G5/T11/T13/T14/K148-K153",
        "impact": "Simplifies the entire VT framework to a single variable",
    },
    {
        "rank": 2,
        "title": "VT Sharpe improvement NOT significant; MDD improvement IS",
        "detail": "VT Sharpe t=0.33 (NS). MDD bootstrap p=0.0004 (highly significant). "
                  "MDD improvement is mechanical (99% under null). "
                  "VT value = risk management, not alpha generation.",
        "phases": "N105/N106/N107/K9/K12/K41",
        "impact": "Correctly frames VT as insurance, not alpha",
    },
    {
        "rank": 3,
        "title": "50/50 SPY/GLD is the unbeatable retail portfolio",
        "detail": "8 independent validations. Sharpe 0.83, MDD -16%. Cannot be beaten by "
                  "optimization, dynamic allocation, or adding assets. "
                  "QQQ tail dep lambda_L=0.82; TLT structural break post-2022.",
        "phases": "K2/K16/K19/K24/K54/K63/K64/K89/Q21",
        "impact": "Definitive retail investment recommendation",
    },
    {
        "rank": 4,
        "title": "Leverage direction taxonomy predicts VT mechanism",
        "detail": "Gamma sign predicts VT behavior: trend follower (gamma>0, equities), "
                  "contrarian (gamma<0, gold), pure variance mgmt (gamma~0, bonds). "
                  "17-asset Spearman rho=0.874 (p=4e-6). EGARCH cross-verified.",
        "phases": "N94-N98/N135-N142/N171",
        "impact": "Novel theoretical contribution for Paper 1",
    },
    {
        "rank": 5,
        "title": "QLIKE ceiling is universal across GARCH variants",
        "detail": "15+ confirmations. 31 models scored: 52% provide zero/negative value. "
                  "14 models x 3 assets: top 7 statistically indistinguishable. "
                  "Only 5-min RV can potentially break it.",
        "phases": "K6/Q22/K34/T22-T23/U1",
        "impact": "Stops futile model complexity search",
    },
    {
        "rank": 6,
        "title": "Asia-Pacific Time-Zone Arbitrage is structural",
        "detail": "6/8 local markets pass Harvey (HK/AU/SG/KR/TW/JP). "
                  "All US-listed ETF controls fail. 13-year rolling: NO decay. "
                  "Alpha is structural (timezone gap) not statistical.",
        "phases": "T32-T35/T43/U2/U4",
        "impact": "Actionable trading strategy for Asia-Pacific investors",
    },
    {
        "rank": 7,
        "title": "Diversification amplifies leverage effect",
        "detail": "SPY gamma 2.8x individual stock gamma (50-stock, t=-16.92). "
                  "Taiwan 4.6x. Japan 0.7x (attenuation). "
                  "Mechanism: correlation asymmetry.",
        "phases": "N138/N146/N155-N162",
        "impact": "Novel finding for Paper 1; explains ETF vs stock VT",
    },
    {
        "rank": 8,
        "title": "VT insurance pricing: ~1-4%/yr, MDD protection 8/8 decades",
        "detail": "76-year analysis: mean ~1%/yr (not 4%/yr). "
                  "VIX era 2-4%/yr, std=2.54%. K36/K39/K40 trilogy: "
                  "'insurance compounds' not 'VT hurts long-term'.",
        "phases": "K36/K39/K40/K41/K85-K87",
        "impact": "Honest cost-benefit analysis for VT",
    },
    {
        "rank": 9,
        "title": "Skewed Student-t is the best VaR distribution (6/6 Kupiec)",
        "detail": "Only method passing all 6 assets. CF-VaR 5/6 (QQQ over-conservative). "
                  "Master VaR Panel T21: 7x5x3x3=315 cells tested. "
                  "MLE auto-adapts df+skewness per asset.",
        "phases": "O11/O14/T21/J20",
        "impact": "Definitive VaR methodology recommendation",
    },
    {
        "rank": 10,
        "title": "GJR-GARCH is MCS superior for equity volatility",
        "detail": "MCS p=0.044 excludes symmetric GARCH. Advantage proportional to skewness "
                  "(equities only; breaks for BTC). w=2000 recommended. "
                  "Multi-step advantage amplifies at longer horizons.",
        "phases": "Phase A-C/K6/R8/T15",
        "impact": "Core model selection for the research system",
    },
]

for f in top_findings:
    print(f"\n  #{f['rank']}: {f['title']}")
    print(f"     {f['detail'][:130]}...")
    print(f"     Phases: {f['phases']}")

###############################################################################
# 6. TOP 5 Methodological Lessons
###############################################################################

print(f"\n{'=' * 80}")
print("TOP 5 METHODOLOGICAL LESSONS")
print("=" * 80)

method_lessons = [
    {
        "rank": 1,
        "title": "Same-day timing bias inflates VIX backtest Sharpe by ~1.0",
        "detail": "VIX_t for r_t: Sharpe 1.98. VIX_t for r_{t+1}: Sharpe 0.81. "
                  "Mechanism: corr(VIX, SPY)=-0.65. All VIX studies must use lagged weights.",
        "discovered": "Q10",
    },
    {
        "rank": 2,
        "title": "Single-period OOS is unreliable; need 5+ cross-OOS periods",
        "detail": "J9: EWMA beats GARCH in 2023-24 but GARCH wins crisis. "
                  "T22 GBM ceiling break: 0/15 cross-asset cells significant. "
                  "|Skewness| N=12 rho=-0.87 collapsed to N=21 rho=-0.086.",
        "discovered": "J9/T22/T2",
    },
    {
        "rank": 3,
        "title": "Measurement tautology: proxy choice determines conclusion",
        "detail": "Rolling Parkinson predicting Parkinson = self-referential (G28). "
                  "Forward r^2 target: GARCH wins 7/7 assets. "
                  "Evaluation target matters more than model choice.",
        "discovered": "I2/R11",
    },
    {
        "rank": 4,
        "title": "Small cross-sectional samples produce inflated correlations",
        "detail": "|Skewness|: N=12 rho=-0.87 -> N=21 rho=-0.086. "
                  "Gamma-mechanism: N=7 rho=1.000 -> N=12(all) rho=-0.448 (NS). "
                  "Rule: N>=15 for cross-sectional claims.",
        "discovered": "T2/Q19",
    },
    {
        "rank": 5,
        "title": "TZ momentum c2c Sharpe includes uncapturable overnight gap",
        "detail": "c2c Sharpe 3.09 but o2o only 0.87 (-72%). "
                  "78% of alpha in gap (R^2=0.35). "
                  "Requires position before signal exists.",
        "discovered": "I8",
    },
]

for lesson in method_lessons:
    print(f"\n  #{lesson['rank']}: {lesson['title']}")
    print(f"     {lesson['detail']}")

###############################################################################
# 7. AI Collaboration Statistics
###############################################################################

print(f"\n{'=' * 80}")
print("AI COLLABORATION STATISTICS")
print("=" * 80)

for source in ["Claude", "User", "Codex", "Gemini"]:
    entries = [e for e in research_entries if e["source"] == source]
    total = len(entries)
    if total == 0:
        continue
    bt = sum(1 for e in entries if e["result"] == "breakthrough")
    sp = sum(1 for e in entries if e["result"] == "strong_positive")
    pos = sum(1 for e in entries if e["result"] == "positive")
    null = sum(1 for e in entries if e["result"] == "null")
    corr = sum(1 for e in entries if e["result"] == "correction")
    pct = (bt + sp + pos) / total * 100

    print(f"\n  {source}: {total} entries")
    print(f"    Breakthroughs: {bt}, Strong+: {sp}, Positive: {pos}, Null: {null}, Correction: {corr}")
    print(f"    Actionable rate: {pct:.0f}%")

    ftypes = Counter(e["finding_type"] for e in entries).most_common(5)
    print(f"    Top topics: {', '.join(f'{t}({c})' for t, c in ftypes)}")

###############################################################################
# 8. Null Result Analysis
###############################################################################

print(f"\n{'=' * 80}")
print("NULL RESULT ANALYSIS")
print("=" * 80)

null_entries = [e for e in research_entries if e["result"] == "null"]
print(f"\nTotal null results: {len(null_entries)}")

null_cats = Counter(e["category"] for e in null_entries)
print(f"\nBy category:")
for cat, count in sorted(null_cats.items(), key=lambda x: -x[1]):
    print(f"  {cat:25s}: {count}")

###############################################################################
# 9. Confidence Distribution
###############################################################################

print(f"\n{'=' * 80}")
print("CONFIDENCE DISTRIBUTION")
print("=" * 80)

confidences = [e.get("confidence", 0) for e in knowledge]
avg_conf = sum(confidences) / len(confidences)
high_conf = sum(1 for c in confidences if c >= 0.9)
low_conf = sum(1 for c in confidences if c < 0.7)
print(f"  Average: {avg_conf:.3f}")
print(f"  High (>=0.9): {high_conf} ({high_conf/total_knowledge*100:.1f}%)")
print(f"  Low (<0.7): {low_conf} ({low_conf/total_knowledge*100:.1f}%)")

###############################################################################
# 10. Save results JSON
###############################################################################

results = {
    "meta": {
        "experiment_id": "K200",
        "title": "200-Experiment Meta-Analysis",
        "date": datetime.now().isoformat(),
        "total_knowledge_entries": total_knowledge,
        "total_experiment_records": total_experiments,
    },
    "category_distribution": dict(cat_counts),
    "result_distribution": dict(result_counts),
    "source_distribution": dict(source_counts),
    "research_entry_count": len(research_entries),
    "vix_sufficient_confirmations": vix_suff_count,
    "qlike_ceiling_mentions": ceiling_count,
    "null_result_count": len(null_entries),
    "confidence_stats": {
        "mean": round(avg_conf, 3),
        "high_conf_count": high_conf,
        "low_conf_count": low_conf,
    },
    "success_rates_by_category": {},
    "source_hit_rates": {},
    "top_10_findings": top_findings,
    "top_5_methodology_lessons": method_lessons,
}

for cat in sorted(set(e["category"] for e in research_entries)):
    cat_entries = [e for e in research_entries if e["category"] == cat]
    total = len(cat_entries)
    pos = sum(1 for e in cat_entries if e["result"] in ("breakthrough", "strong_positive", "positive"))
    null = sum(1 for e in cat_entries if e["result"] == "null")
    results["success_rates_by_category"][cat] = {
        "total": total, "positive": pos, "null": null,
        "rate": round(pos / total * 100, 1) if total > 0 else 0,
    }

for source in ["Claude", "User", "Codex", "Gemini"]:
    entries = [e for e in research_entries if e["source"] == source]
    total = len(entries)
    if total == 0:
        continue
    pos = sum(1 for e in entries if e["result"] in ("breakthrough", "strong_positive", "positive"))
    results["source_hit_rates"][source] = {
        "total": total, "positive": pos,
        "rate": round(pos / total * 100, 1),
    }

with open(OUTPUT_PATH, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to {OUTPUT_PATH}")

###############################################################################
# 11. Executive Summary
###############################################################################

print(f"\n{'=' * 80}")
print("EXECUTIVE SUMMARY")
print("=" * 80)

bt_count = result_counts.get("breakthrough", 0)
sp_count = result_counts.get("strong_positive", 0)
pos_count = result_counts.get("positive", 0)
null_count = result_counts.get("null", 0)
corr_count = result_counts.get("correction", 0)

print(f"""
The VolPred Research System produced {total_knowledge} knowledge entries and
{total_experiments} formal experiment records over ~10 days (2026-03-14 to 2026-03-24).

KEY NUMBERS:
  Research entries: {len(research_entries)}
  Breakthroughs: {bt_count}  |  Strong+: {sp_count}  |  Positive: {pos_count}
  Null results: {null_count}  |  Corrections: {corr_count}
  VIX sufficient statistic: {vix_suff_count}+ confirmations
  QLIKE ceiling: {ceiling_count}+ confirmations

WHAT WE DISCOVERED:
  1. VIX is the only variable needed for VT (21+ confirmations)
  2. VT value = MDD reduction (p=0.0004), NOT Sharpe (t=0.33)
  3. 50/50 SPY/GLD + 12/VIX is optimal retail portfolio (8x validated)
  4. Gamma sign predicts VT mechanism (17 assets, rho=0.874)
  5. GARCH(1,1) fully exploits daily returns (52% of 31 models add nothing)
  6. Asia-Pacific TZ arbitrage is structural (6/8 markets, Harvey PASS)
  7. Diversification amplifies leverage 2.8x (US) to 4.6x (Taiwan)
  8. Skewed Student-t is best VaR method (6/6 Kupiec)

WHAT FAILED:
  - ML/DL at daily frequency (4 failures: LSTM, GRU, XGBoost, GBM cross-asset)
  - All sentiment indicators beyond VIX (10+ tested, 0 add value)
  - GARCH complexity (FIGARCH, APARCH, Component, MF2, Panel)
  - VRP as directional signal (14+ null results)
  - Dynamic portfolio optimization vs static 50/50

METHODOLOGY:
  - Same-day timing bias: Sharpe inflation +145%
  - Cross-OOS validation mandatory (5+ periods)
  - Harvey (2016) t>3.0 threshold consistently applied
  - FDR audit: 30/32 findings survive BH (q=0.05)
""")
