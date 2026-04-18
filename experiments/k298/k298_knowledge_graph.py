#!/usr/bin/env python3
"""
K298: Knowledge Graph — How Do Our 978 Findings Connect?

Analyzes the STRUCTURE of the knowledge base:
- Tag frequency and co-occurrence
- Topic clusters and centrality
- Temporal evolution of research focus
- Gap analysis (under-researched combinations)
- Most connected findings
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path


def load_knowledge():
    """Load and normalize all knowledge entries."""
    with open("storage/memory/knowledge.json") as f:
        data = json.load(f)

    entries = []
    for e in data:
        entry = {}
        # Normalize ID
        entry["id"] = e.get("id") or e.get("item_id", "unknown")

        # Normalize date
        if "created_at" in e:
            entry["date"] = e["created_at"][:10]
        elif "date" in e:
            entry["date"] = e["date"]
        elif "timestamp" in e:
            entry["date"] = e["timestamp"][:10]
        else:
            entry["date"] = "unknown"

        # Category
        entry["category"] = e.get("category", "uncategorized")

        # Content
        entry["content"] = e.get("content", "")

        # Title (new format has it)
        entry["title"] = e.get("title", "")

        # Tags: use explicit tags if available, otherwise derive from category + content
        if "tags" in e and e["tags"]:
            entry["tags"] = e["tags"]
        else:
            entry["tags"] = [entry["category"]]

        # Confidence
        entry["confidence"] = e.get("confidence", 0.5)

        # Evidence links
        entry["evidence"] = e.get("evidence", e.get("experiment_ids", []))

        entries.append(entry)

    return entries


def extract_content_tags(content):
    """Extract implicit tags from content text using keyword patterns."""
    content_lower = content.lower()
    implicit_tags = set()

    # Asset mentions
    asset_patterns = {
        "SPY": r"\bspy\b",
        "GLD": r"\bgld\b",
        "QQQ": r"\bqqq\b",
        "TLT": r"\btlt\b",
        "EEM": r"\beem\b",
        "BTC": r"\bbtc\b|bitcoin",
        "0050.TW": r"0050|taiwan.*etf|tw50",
        "VIX": r"\bvix\b",
        "VVIX": r"\bvvix\b",
    }
    for tag, pat in asset_patterns.items():
        if re.search(pat, content_lower):
            implicit_tags.add(f"asset:{tag}")

    # Model mentions
    model_patterns = {
        "GARCH": r"\bgarch\b",
        "GJR": r"\bgjr\b",
        "EGARCH": r"\begarch\b",
        "HAR": r"\bhar\b",
        "EWMA": r"\bewma\b",
        "DCC": r"\bdcc\b",
        "LSTM": r"\blstm\b",
        "XGBoost": r"\bxgboost\b",
        "FHS": r"\bfhs\b",
    }
    for tag, pat in model_patterns.items():
        if re.search(pat, content_lower):
            implicit_tags.add(f"model:{tag}")

    # Method mentions
    method_patterns = {
        "VaR": r"\bvar\b.*(?:risk|value|violation|backtest|kupiec)",
        "VT": r"\bvt\b|volatility.?target",
        "MDD": r"\bmdd\b|max.*drawdown",
        "Sharpe": r"\bsharpe\b",
        "DM_test": r"diebold.?mariano|dm.?test|\bdm\b.{0,5}stat",
        "bootstrap": r"\bbootstrap\b",
        "QLIKE": r"\bqlike\b",
        "MCS": r"model confidence set|\bmcs\b",
    }
    for tag, pat in method_patterns.items():
        if re.search(pat, content_lower):
            implicit_tags.add(f"method:{tag}")

    # Topic mentions
    topic_patterns = {
        "leverage_effect": r"leverage.?effect|asymmetr",
        "crisis": r"\bcrisis\b|crash|drawdown|covid|gfc",
        "cross_asset": r"cross.?asset|multi.?asset",
        "cross_market": r"cross.?market|taiwan|japan|international",
        "insurance_pricing": r"insurance|cost.*protection|premium",
        "rebalancing": r"rebalanc",
        "transaction_cost": r"transaction.?cost|turnover|net.?sharpe",
        "tail_risk": r"tail.?risk|kurtosis|skewness|fat.?tail",
        "sentiment": r"sentiment|fear|greed|put.?call",
        "regime": r"\bregime\b|regime.?switch|markov",
        "null_result": r"null.?result|not.?significant|fails|no.*improvement",
    }
    for tag, pat in topic_patterns.items():
        if re.search(pat, content_lower):
            implicit_tags.add(f"topic:{tag}")

    return implicit_tags


def normalize_category(cat):
    """Group similar categories into broader themes."""
    theme_map = {
        # Model-related
        "model_behavior": "Models",
        "model_comparison": "Models",
        "model_evaluation": "Models",
        "model_implementation": "Models",
        "model_selection": "Models",
        "model": "Models",
        "vol_models": "Models",
        "volatility_prediction": "Models",

        # Strategy-related
        "strategies": "Strategies",
        "strategy": "Strategies",
        "strategy_behavior": "Strategies",
        "strategy_caveat": "Strategies",
        "strategy_comparison": "Strategies",
        "strategy_cross_market": "Strategies",
        "strategy_dca": "Strategies",
        "strategy_enhancement": "Strategies",
        "strategy_failed": "Strategies",
        "strategy_improvement": "Strategies",
        "strategy_insight": "Strategies",
        "strategy_killed": "Strategies",
        "strategy_mechanism": "Strategies",
        "strategy_multi_asset": "Strategies",
        "strategy_optimization": "Strategies",
        "strategy_performance": "Strategies",
        "strategy_practical": "Strategies",
        "strategy_rebalancing": "Strategies",
        "strategy_recovery": "Strategies",
        "strategy_risk": "Strategies",
        "strategy_robustness": "Strategies",
        "strategy_stability": "Strategies",
        "strategy_stress_test": "Strategies",
        "strategy_timing": "Strategies",
        "strategy_vrp": "Strategies",

        # VaR and risk
        "var_methods": "Risk_Management",
        "var_methodology": "Risk_Management",
        "var_regime_experiment": "Risk_Management",
        "var_reliability": "Risk_Management",
        "var_violations": "Risk_Management",
        "risk_management": "Risk_Management",
        "portfolio_var": "Risk_Management",
        "tail_risk": "Risk_Management",

        # Cross-asset
        "cross_asset": "Cross_Asset",
        "cross_asset_mechanism": "Cross_Asset",
        "cross_asset_validation": "Cross_Asset",
        "cross_asset_vt": "Cross_Asset",
        "cross_market": "Cross_Market",
        "cross_market_application": "Cross_Market",
        "cross_market_validation": "Cross_Market",
        "cross_period_validation": "Cross_Asset",
        "international_comparison": "Cross_Market",

        # Data and methodology
        "data_property": "Data",
        "data_sources": "Data",
        "data": "Data",
        "market_data": "Data",
        "research_methodology": "Methodology",
        "methodology": "Methodology",
        "methodology_correction": "Methodology",
        "methodology_insight": "Methodology",
        "methodology_warning": "Methodology",
        "evaluation_methodology": "Methodology",
        "statistical_caveat": "Methodology",
        "statistical_significance": "Methodology",

        # Leverage and mechanism
        "leverage_effect": "Leverage_Mechanism",
        "mechanism_discovery": "Leverage_Mechanism",
        "gamma_mechanism": "Leverage_Mechanism",
        "gamma_dynamics": "Leverage_Mechanism",
        "amplification_mechanism": "Leverage_Mechanism",
        "kurtosis_mechanism": "Leverage_Mechanism",
        "VT_mechanism": "Leverage_Mechanism",
        "diversification_amplification": "Leverage_Mechanism",

        # Market context
        "market_context": "Market_Context",
        "market_dynamics": "Market_Context",
        "market_event": "Market_Context",
        "market_structure": "Market_Context",
        "market_microstructure": "Market_Microstructure",
        "market_update": "Market_Context",
        "market": "Market_Context",
        "real_time_market": "Market_Context",
        "real_time_validation": "Market_Context",

        # Literature
        "literature": "Literature",
        "literature_review": "Literature",
        "literature_2024_2026": "Literature",
        "reference": "Literature",

        # Distribution
        "distribution_effect": "Distribution",

        # Portfolio
        "portfolio": "Portfolio",
        "portfolio_construction": "Portfolio",
        "portfolio_optimization": "Portfolio",
        "portfolio_strategy": "Portfolio",
        "diversification_analysis": "Portfolio",

        # Experiments
        "experiment": "Experiments",
        "experiment_result": "Experiments",
        "null_result": "Experiments",

        # Taiwan
        "taiwan_market": "Taiwan",

        # Crypto
        "crypto": "Crypto",
        "crypto_lead_lag": "Crypto",
        "crypto_strategy": "Crypto",
        "crypto_vt": "Crypto",

        # Parameters
        "parameter_sensitivity": "Parameters",
        "parameter_optimization": "Parameters",
        "optimal_parameters": "Parameters",

        # VIX and sentiment
        "vix_correlation": "VIX_Sentiment",
        "vix_proxy_transport": "VIX_Sentiment",
        "sentiment_indicator": "VIX_Sentiment",
        "sentiment_indicators": "VIX_Sentiment",
        "financial_indicators": "VIX_Sentiment",

        # AI
        "ai_collaboration": "AI_Review",
        "ai_review": "AI_Review",
        "peer_review": "AI_Review",
        "peer_review_synthesis": "AI_Review",
        "review": "AI_Review",

        # Theoretical
        "theoretical": "Theory",
        "theoretical_contribution": "Theory",
        "theoretical_derivation": "Theory",
        "theoretical_foundation": "Theory",
        "theoretical_insight": "Theory",
        "theory": "Theory",

        # Crisis
        "crisis_analysis": "Crisis",
        "crisis_protection": "Crisis",
        "crisis_taxonomy": "Crisis",
        "crisis_validation": "Crisis",

        # VRP
        "vrp_analysis": "VRP",
        "vrp_dynamics": "VRP",
        "vrp_robustness": "VRP",
        "vrp_structure": "VRP",

        # Other
        "return_prediction": "Return_Prediction",
        "return-prediction": "Return_Prediction",
        "return_decomposition": "Return_Prediction",
        "macro_prediction": "Return_Prediction",

        "general_content": "Communication",
        "research_communication": "Communication",
        "research_direction": "Communication",
        "research_report": "Communication",
        "research_summary": "Communication",
        "publication": "Communication",

        "platform": "Platform",
        "deployment": "Platform",
        "features": "Platform",
        "system_ops": "Platform",

        "behavioral_finance": "Behavioral",
        "investor_experience": "Behavioral",

        "seasonality": "Seasonality",
        "network_topology": "Network",
        "high_frequency": "High_Frequency",
        "multivariate_model": "Multivariate",
        "transaction_costs": "Transaction_Costs",
        "drawdown_analysis": "Drawdown",
        "scenario_analysis": "Scenario",
        "utility_analysis": "Utility",
        "live_performance": "Live_Performance",
        "monetization": "Business",
        "business": "Business",
        "paper_planning": "Paper",
        "milestone": "Milestone",
        "validation": "Validation",
        "oos_validation": "Validation",
        "leveraged_etf": "Leveraged_ETF",
        "anti_tautology": "Anti_Tautology",
        "proposition_boundary": "Proposition_Test",
        "proposition_robustness": "Proposition_Test",
        "complexity_ceiling": "Complexity_Ceiling",
        "formal_test": "Formal_Test",
    }
    return theme_map.get(cat, cat)


def build_cooccurrence(entries):
    """Build tag co-occurrence matrix from content-derived tags."""
    # For each entry, collect all tags (category + content-derived)
    entry_tagsets = []
    for e in entries:
        tags = set()
        tags.add(f"cat:{normalize_category(e['category'])}")
        content_tags = extract_content_tags(e["content"])
        tags.update(content_tags)
        entry_tagsets.append((e["id"], tags))

    # Count tag frequency
    tag_freq = Counter()
    for _, tags in entry_tagsets:
        for t in tags:
            tag_freq[t] += 1

    # Build co-occurrence matrix (only for tags appearing 5+ times)
    min_freq = 5
    frequent_tags = {t for t, c in tag_freq.items() if c >= min_freq}

    cooccurrence = defaultdict(lambda: defaultdict(int))
    for _, tags in entry_tagsets:
        ftags = tags & frequent_tags
        for t1, t2 in combinations(sorted(ftags), 2):
            cooccurrence[t1][t2] += 1
            cooccurrence[t2][t1] += 1

    return entry_tagsets, tag_freq, cooccurrence, frequent_tags


def compute_centrality(cooccurrence, frequent_tags):
    """Compute degree centrality for each tag."""
    centrality = {}
    for tag in frequent_tags:
        neighbors = cooccurrence.get(tag, {})
        # Degree centrality = sum of co-occurrence weights
        degree = sum(neighbors.values())
        n_neighbors = len([v for v in neighbors.values() if v > 0])
        centrality[tag] = {
            "weighted_degree": degree,
            "n_neighbors": n_neighbors,
            "avg_weight": degree / n_neighbors if n_neighbors > 0 else 0,
        }
    return centrality


def find_clusters(cooccurrence, frequent_tags, tag_freq):
    """Simple greedy clustering based on co-occurrence strength."""
    # Jaccard similarity between tags
    similarities = {}
    for t1 in frequent_tags:
        for t2 in frequent_tags:
            if t1 >= t2:
                continue
            co = cooccurrence.get(t1, {}).get(t2, 0)
            union = tag_freq[t1] + tag_freq[t2] - co
            if union > 0:
                sim = co / union
                if sim > 0.05:  # threshold
                    similarities[(t1, t2)] = sim

    # Greedy agglomerative: assign each tag to its strongest neighbor's cluster
    assigned = {}
    cluster_id = 0

    # Sort tags by frequency (most frequent first)
    sorted_tags = sorted(frequent_tags, key=lambda t: -tag_freq[t])

    for tag in sorted_tags:
        if tag in assigned:
            continue
        # Start new cluster
        assigned[tag] = cluster_id
        # Add tags strongly connected to this one
        neighbors = cooccurrence.get(tag, {})
        for neighbor, weight in sorted(neighbors.items(), key=lambda x: -x[1]):
            if neighbor not in assigned and weight >= 3:
                co = weight
                union = tag_freq[tag] + tag_freq[neighbor] - co
                if union > 0 and co / union > 0.03:
                    assigned[neighbor] = cluster_id
        cluster_id += 1

    # Group by cluster
    clusters = defaultdict(list)
    for tag, cid in assigned.items():
        clusters[cid].append(tag)

    return clusters


def temporal_analysis(entries):
    """Analyze how research focus shifted over time."""
    # Group by date
    daily_themes = defaultdict(lambda: Counter())
    for e in entries:
        if e["date"] == "unknown":
            continue
        date = e["date"]
        theme = normalize_category(e["category"])
        daily_themes[date][theme] += 1

    # Group into sessions (multi-day periods)
    dates = sorted(daily_themes.keys())
    if not dates:
        return {}

    # Split into early/middle/late thirds
    n = len(dates)
    third = n // 3
    periods = {
        "early": dates[:third],
        "middle": dates[third:2*third],
        "late": dates[2*third:],
    }

    period_themes = {}
    for period_name, period_dates in periods.items():
        theme_counts = Counter()
        for d in period_dates:
            theme_counts.update(daily_themes[d])
        total = sum(theme_counts.values())
        period_themes[period_name] = {
            "dates": f"{period_dates[0]} to {period_dates[-1]}",
            "n_entries": total,
            "n_days": len(period_dates),
            "top_themes": [
                {"theme": t, "count": c, "pct": round(100 * c / total, 1)}
                for t, c in theme_counts.most_common(10)
            ],
        }

    # Daily trend
    daily_counts = {}
    for d in dates:
        daily_counts[d] = sum(daily_themes[d].values())

    return {
        "periods": period_themes,
        "daily_counts": daily_counts,
        "total_days": len(dates),
        "date_range": f"{dates[0]} to {dates[-1]}",
    }


def gap_analysis(entry_tagsets, frequent_tags, tag_freq):
    """Find tag combinations that are under-explored."""
    # Count co-occurrences
    pair_counts = Counter()
    for _, tags in entry_tagsets:
        ftags = sorted(tags & frequent_tags)
        for t1, t2 in combinations(ftags, 2):
            pair_counts[(t1, t2)] += 1

    # Find high-frequency tags with low co-occurrence (gaps)
    # Only consider tags with freq >= 10
    high_freq_tags = sorted(
        [t for t, c in tag_freq.items() if c >= 10 and t in frequent_tags],
        key=lambda t: -tag_freq[t]
    )

    gaps = []
    for t1, t2 in combinations(high_freq_tags, 2):
        co = pair_counts.get((t1, t2), 0) + pair_counts.get((t2, t1), 0)
        expected = tag_freq[t1] * tag_freq[t2] / len(entry_tagsets)
        if expected > 2 and co < expected * 0.3:  # much less than expected
            gaps.append({
                "tag1": t1,
                "tag2": t2,
                "tag1_freq": tag_freq[t1],
                "tag2_freq": tag_freq[t2],
                "cooccurrence": co,
                "expected": round(expected, 1),
                "ratio": round(co / expected, 2) if expected > 0 else 0,
            })

    gaps.sort(key=lambda g: g["ratio"])
    return gaps[:30]


def most_connected_findings(entries, entry_tagsets):
    """Find the 20 entries with highest tag overlap with other entries."""
    # For each entry, count how many other entries share at least one tag
    n = len(entry_tagsets)
    connectivity = []

    for i, (eid, tags) in enumerate(entry_tagsets):
        overlap_count = 0
        overlap_weight = 0
        for j, (_, other_tags) in enumerate(entry_tagsets):
            if i == j:
                continue
            shared = tags & other_tags
            if shared:
                overlap_count += 1
                overlap_weight += len(shared)

        connectivity.append({
            "id": eid,
            "category": entries[i]["category"],
            "title": entries[i].get("title", ""),
            "content_preview": entries[i]["content"][:150],
            "n_tags": len(tags),
            "n_connected_entries": overlap_count,
            "total_overlap_weight": overlap_weight,
            "connectivity_score": round(overlap_weight / (n - 1), 3),
        })

    connectivity.sort(key=lambda x: -x["total_overlap_weight"])
    return connectivity[:20]


def category_theme_analysis(entries):
    """Analyze the 166 raw categories grouped into themes."""
    theme_counts = Counter()
    theme_categories = defaultdict(list)

    for e in entries:
        theme = normalize_category(e["category"])
        theme_counts[theme] += 1
        if e["category"] not in theme_categories[theme]:
            theme_categories[theme].append(e["category"])

    result = []
    for theme, count in theme_counts.most_common():
        result.append({
            "theme": theme,
            "count": count,
            "pct": round(100 * count / len(entries), 1),
            "sub_categories": theme_categories[theme],
        })
    return result


def source_attribution(entries):
    """Analyze who proposed what (source attribution)."""
    sources = Counter()
    source_themes = defaultdict(lambda: Counter())

    for e in entries:
        content = e["content"]
        theme = normalize_category(e["category"])

        if "[提出: Gemini" in content:
            sources["Gemini"] += 1
            source_themes["Gemini"][theme] += 1
        elif "[提出: Codex" in content:
            sources["Codex"] += 1
            source_themes["Codex"][theme] += 1
        elif "[提出: User" in content or "[提出: 用戶" in content:
            sources["User"] += 1
            source_themes["User"][theme] += 1
        elif "[提出: Claude" in content:
            sources["Claude"] += 1
            source_themes["Claude"][theme] += 1
        else:
            sources["unattributed"] += 1

    result = {"total_attributed": sum(v for k, v in sources.items() if k != "unattributed")}
    for src in ["Gemini", "Codex", "User", "Claude", "unattributed"]:
        result[src] = {
            "count": sources[src],
            "top_themes": dict(source_themes[src].most_common(5)) if src != "unattributed" else {},
        }
    return result


def confidence_analysis(entries):
    """Analyze confidence distribution across themes."""
    theme_conf = defaultdict(list)
    for e in entries:
        theme = normalize_category(e["category"])
        conf = e.get("confidence", 0.5)
        if isinstance(conf, (int, float)):
            theme_conf[theme].append(conf)

    result = {}
    for theme, confs in theme_conf.items():
        if len(confs) >= 3:
            result[theme] = {
                "n": len(confs),
                "mean": round(sum(confs) / len(confs), 3),
                "min": round(min(confs), 2),
                "max": round(max(confs), 2),
            }

    # Sort by mean confidence
    return dict(sorted(result.items(), key=lambda x: -x[1]["mean"]))


def main():
    print("=" * 70)
    print("K298: Knowledge Graph — How Do Our Findings Connect?")
    print("=" * 70)

    entries = load_knowledge()
    print(f"\nLoaded {len(entries)} knowledge entries")
    print(f"Date range: {min(e['date'] for e in entries if e['date'] != 'unknown')} to {max(e['date'] for e in entries if e['date'] != 'unknown')}")

    # ========================================
    # 1. Category / Theme Analysis
    # ========================================
    print("\n" + "=" * 50)
    print("1. THEME ANALYSIS (166 categories → grouped themes)")
    print("=" * 50)

    themes = category_theme_analysis(entries)
    print(f"\n{len(themes)} distinct themes after grouping:")
    print(f"\n{'Theme':<25} {'Count':>6} {'Pct':>6}  Sub-categories")
    print("-" * 90)
    for t in themes[:25]:
        subcats = ", ".join(t["sub_categories"][:3])
        if len(t["sub_categories"]) > 3:
            subcats += f" (+{len(t['sub_categories'])-3} more)"
        print(f"{t['theme']:<25} {t['count']:>6} {t['pct']:>5.1f}%  {subcats}")

    # ========================================
    # 2. Tag Co-occurrence Network
    # ========================================
    print("\n" + "=" * 50)
    print("2. TAG CO-OCCURRENCE NETWORK")
    print("=" * 50)

    entry_tagsets, tag_freq, cooccurrence, frequent_tags = build_cooccurrence(entries)

    print(f"\nTotal unique tags (freq >= 5): {len(frequent_tags)}")
    print(f"\nTop 30 most frequent tags:")
    print(f"{'Tag':<35} {'Freq':>5}")
    print("-" * 42)
    for tag, freq in sorted(tag_freq.items(), key=lambda x: -x[1])[:30]:
        marker = "*" if tag in frequent_tags else " "
        print(f"{marker}{tag:<34} {freq:>5}")

    # ========================================
    # 3. Centrality Analysis
    # ========================================
    print("\n" + "=" * 50)
    print("3. TAG CENTRALITY (most connected tags)")
    print("=" * 50)

    centrality = compute_centrality(cooccurrence, frequent_tags)
    sorted_centrality = sorted(centrality.items(), key=lambda x: -x[1]["weighted_degree"])

    print(f"\n{'Tag':<35} {'Degree':>8} {'Neighbors':>10} {'Avg Wt':>8}")
    print("-" * 65)
    for tag, stats in sorted_centrality[:25]:
        print(f"{tag:<35} {stats['weighted_degree']:>8} {stats['n_neighbors']:>10} {stats['avg_weight']:>8.1f}")

    # ========================================
    # 4. Strongest Edges (Co-occurrence pairs)
    # ========================================
    print("\n" + "=" * 50)
    print("4. STRONGEST EDGES (most co-occurring tag pairs)")
    print("=" * 50)

    edges = []
    seen = set()
    for t1 in frequent_tags:
        for t2, weight in cooccurrence.get(t1, {}).items():
            if (t2, t1) not in seen:
                edges.append((t1, t2, weight))
                seen.add((t1, t2))

    edges.sort(key=lambda x: -x[2])
    print(f"\n{'Tag 1':<30} {'Tag 2':<30} {'Co-occ':>7}")
    print("-" * 70)
    for t1, t2, w in edges[:30]:
        print(f"{t1:<30} {t2:<30} {w:>7}")

    # ========================================
    # 5. Cluster Analysis
    # ========================================
    print("\n" + "=" * 50)
    print("5. TAG CLUSTERS")
    print("=" * 50)

    clusters = find_clusters(cooccurrence, frequent_tags, tag_freq)

    # Only show clusters with 2+ members
    multi_clusters = {k: v for k, v in clusters.items() if len(v) >= 2}
    print(f"\n{len(multi_clusters)} clusters with 2+ members (out of {len(clusters)} total):")

    for cid, members in sorted(multi_clusters.items(), key=lambda x: -len(x[1])):
        sorted_members = sorted(members, key=lambda t: -tag_freq[t])
        total_freq = sum(tag_freq[t] for t in members)
        print(f"\n  Cluster {cid} ({len(members)} tags, {total_freq} total entries):")
        for m in sorted_members[:10]:
            print(f"    {m:<35} freq={tag_freq[m]}")
        if len(sorted_members) > 10:
            print(f"    ... and {len(sorted_members)-10} more")

    # ========================================
    # 6. Temporal Analysis
    # ========================================
    print("\n" + "=" * 50)
    print("6. TEMPORAL ANALYSIS")
    print("=" * 50)

    temporal = temporal_analysis(entries)

    for period_name, info in temporal.get("periods", {}).items():
        print(f"\n  {period_name.upper()} ({info['dates']}, {info['n_entries']} entries over {info['n_days']} days):")
        for t in info["top_themes"][:7]:
            bar = "#" * int(t["pct"] / 2)
            print(f"    {t['theme']:<25} {t['count']:>4} ({t['pct']:>5.1f}%) {bar}")

    # Daily output rate
    daily = temporal.get("daily_counts", {})
    if daily:
        counts = list(daily.values())
        print(f"\n  Daily output rate:")
        print(f"    Mean: {sum(counts)/len(counts):.1f} entries/day")
        print(f"    Max:  {max(counts)} entries/day ({max(daily, key=daily.get)})")
        print(f"    Min:  {min(counts)} entries/day")
        print(f"    Total days active: {len(counts)}")

    # ========================================
    # 7. Gap Analysis
    # ========================================
    print("\n" + "=" * 50)
    print("7. GAP ANALYSIS (under-explored combinations)")
    print("=" * 50)

    gaps = gap_analysis(entry_tagsets, frequent_tags, tag_freq)

    print(f"\nTag pairs with much fewer co-occurrences than expected:")
    print(f"{'Tag 1':<30} {'Tag 2':<30} {'Actual':>7} {'Expected':>9} {'Ratio':>6}")
    print("-" * 85)
    for g in gaps[:20]:
        print(f"{g['tag1']:<30} {g['tag2']:<30} {g['cooccurrence']:>7} {g['expected']:>9.1f} {g['ratio']:>6.2f}")

    # ========================================
    # 8. Most Connected Findings
    # ========================================
    print("\n" + "=" * 50)
    print("8. TOP 20 MOST CONNECTED FINDINGS")
    print("=" * 50)

    connected = most_connected_findings(entries, entry_tagsets)

    for i, c in enumerate(connected, 1):
        print(f"\n  #{i} [{c['id']}] (score={c['connectivity_score']:.3f}, "
              f"connected to {c['n_connected_entries']} entries, "
              f"{c['n_tags']} tags)")
        print(f"     Cat: {c['category']}")
        if c["title"]:
            print(f"     Title: {c['title']}")
        print(f"     {c['content_preview']}...")

    # ========================================
    # 9. Source Attribution
    # ========================================
    print("\n" + "=" * 50)
    print("9. SOURCE ATTRIBUTION")
    print("=" * 50)

    sources = source_attribution(entries)
    print(f"\n  Total attributed: {sources['total_attributed']}/{len(entries)}")
    for src in ["Claude", "User", "Gemini", "Codex", "unattributed"]:
        info = sources[src]
        print(f"\n  {src}: {info['count']} entries")
        if info.get("top_themes"):
            for theme, count in list(info["top_themes"].items())[:3]:
                print(f"    - {theme}: {count}")

    # ========================================
    # 10. Confidence by Theme
    # ========================================
    print("\n" + "=" * 50)
    print("10. CONFIDENCE BY THEME")
    print("=" * 50)

    conf = confidence_analysis(entries)
    print(f"\n{'Theme':<25} {'N':>5} {'Mean':>6} {'Min':>5} {'Max':>5}")
    print("-" * 50)
    for theme, stats in list(conf.items())[:20]:
        print(f"{theme:<25} {stats['n']:>5} {stats['mean']:>6.3f} {stats['min']:>5.2f} {stats['max']:>5.2f}")

    # ========================================
    # Save structured results
    # ========================================
    results = {
        "experiment": "K298",
        "title": "Knowledge Graph — How Do Our Findings Connect?",
        "n_entries": len(entries),
        "n_categories": len(set(e["category"] for e in entries)),
        "n_themes": len(themes),
        "date_range": temporal.get("date_range", ""),
        "themes": themes,
        "tag_frequency": dict(sorted(tag_freq.items(), key=lambda x: -x[1])[:50]),
        "centrality_top20": [
            {"tag": t, **s} for t, s in sorted_centrality[:20]
        ],
        "strongest_edges_top30": [
            {"tag1": t1, "tag2": t2, "weight": w} for t1, t2, w in edges[:30]
        ],
        "clusters": {
            str(k): {
                "members": sorted(v, key=lambda t: -tag_freq[t]),
                "total_freq": sum(tag_freq[t] for t in v),
            }
            for k, v in multi_clusters.items()
        },
        "temporal": temporal,
        "gaps": gaps[:20],
        "most_connected": connected,
        "source_attribution": sources,
        "confidence_by_theme": conf,
        "key_insights": [],  # filled below
    }

    # ========================================
    # Key Insights Summary
    # ========================================
    print("\n" + "=" * 70)
    print("KEY INSIGHTS SUMMARY")
    print("=" * 70)

    insights = []

    # Insight 1: Research concentration
    top3_themes = themes[:3]
    top3_pct = sum(t["count"] for t in top3_themes)
    top3_pct_ratio = round(100 * top3_pct / len(entries), 1)
    i1 = (f"Research is concentrated: top 3 themes ({', '.join(t['theme'] for t in top3_themes)}) "
          f"account for {top3_pct_ratio}% of all findings ({top3_pct}/{len(entries)})")
    insights.append(i1)
    print(f"\n1. {i1}")

    # Insight 2: Central hub
    top_central = sorted_centrality[0]
    i2 = (f"Most central tag: {top_central[0]} (degree={top_central[1]['weighted_degree']}, "
          f"connected to {top_central[1]['n_neighbors']} other tags)")
    insights.append(i2)
    print(f"\n2. {i2}")

    # Insight 3: Strongest connection
    strongest = edges[0]
    i3 = f"Strongest link: {strongest[0]} <-> {strongest[1]} ({strongest[2]} co-occurrences)"
    insights.append(i3)
    print(f"\n3. {i3}")

    # Insight 4: Research pace
    if daily:
        counts = list(daily.values())
        avg_rate = sum(counts) / len(counts)
        i4 = f"Research pace: {avg_rate:.1f} findings/day over {len(counts)} days ({len(entries)} total)"
        insights.append(i4)
        print(f"\n4. {i4}")

    # Insight 5: Temporal shift
    early_top = temporal.get("periods", {}).get("early", {}).get("top_themes", [{}])[0].get("theme", "")
    late_top = temporal.get("periods", {}).get("late", {}).get("top_themes", [{}])[0].get("theme", "")
    if early_top and late_top:
        i5 = f"Research drift: early focus on '{early_top}' → late focus on '{late_top}'"
        insights.append(i5)
        print(f"\n5. {i5}")

    # Insight 6: Gaps
    if gaps:
        top_gap = gaps[0]
        i6 = (f"Biggest gap: {top_gap['tag1']} x {top_gap['tag2']} "
              f"(only {top_gap['cooccurrence']} co-occurrences vs {top_gap['expected']} expected)")
        insights.append(i6)
        print(f"\n6. {i6}")

    # Insight 7: Under-explored areas
    bottom_themes = [t for t in themes if t["count"] <= 3]
    i7 = f"Under-explored: {len(bottom_themes)} themes have 3 or fewer entries (potential research opportunities)"
    insights.append(i7)
    print(f"\n7. {i7}")
    for bt in bottom_themes[:10]:
        print(f"   - {bt['theme']}: {bt['count']} entries")

    # Insight 8: Source diversity
    attributed = sources["total_attributed"]
    i8 = (f"Source diversity: {attributed} entries have attribution "
          f"(Claude: {sources['Claude']['count']}, "
          f"User: {sources['User']['count']}, "
          f"Gemini: {sources['Gemini']['count']}, "
          f"Codex: {sources['Codex']['count']})")
    insights.append(i8)
    print(f"\n8. {i8}")

    results["key_insights"] = insights

    # Save
    output_path = Path("experiments/k298_knowledge_graph_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == "__main__":
    main()
