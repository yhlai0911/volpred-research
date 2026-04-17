"""K705: Website Messaging Audit — What VolPred Says vs What Research Supports

After K687 paradigm shift (VT=insurance not alpha), K693 (paper_trading lookahead fix),
and K700 (final truth synthesis), this experiment audits the website's messaging for
accuracy against current research conclusions.

Data sources:
- frontend-v2-fix/ source code (StrategyPanel, StrategySelector, HeroSection, About, Disclaimer)
- storage/strategy_metrics.json (displayed performance numbers)
- storage/memory/knowledge.json (K687, K688, K690, K693, K694, K700)
- scripts/daily_update.py (daily article generator text)

References:
- K687: No VT beats BH 50/50 on Sharpe after proper lag (Moreira & Muir 2017 replication)
- K688: VT wins under CRRA utility (gamma >= 5) — insurance value is real
- K690: EWMA VT most lag-robust; Piecewise most fragile
- K693: 9,935 paper_trading entries corrected (same-day → next-day return)
- K694: Post-correction audit — 7/10 still beat SPY, but rankings reshuffled
- K700: 80 experiments, 3 certainties, 3 mistakes caught, VT=insurance

Author: Yi-Hao Lai (Da-Yeh University) + VolPred Research System
"""
import json
from datetime import datetime
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
MAIN_REPO = Path("/Users/yhlai0911/Desktop/volpred-research")

# ─── 1. Current Website Claims ───────────────────────────────────────────────

# 1A. Strategy Panel Header
strategy_panel_claims = {
    "header_label": "投資建議",
    "location": "frontend-v2-fix/src/components/StrategyPanel.tsx:64",
    "issue": "Label says '投資建議' (Investment Advice) — implies we are recommending specific trades for profit. "
             "Post-K687, VT is insurance not alpha. Should be '風險管理工具' or '策略配置參考'.",
    "severity": "HIGH",
}

# 1B. Strategy Panel Metrics — Sharpe/Cumulative displayed
strategy_metrics_path = WORKTREE / "storage" / "strategy_metrics.json"
with open(strategy_metrics_path) as f:
    metrics = json.load(f)

strategy_metrics_claims = []
for key, m in metrics.items():
    entry = {
        "strategy_key": key,
        "displayed_sharpe": m.get("sharpe"),
        "displayed_cumulative_return": m.get("cumulative_return"),
        "displayed_annualized_return": m.get("annualized_return"),
        "displayed_max_drawdown": m.get("max_drawdown"),
        "trading_days": m.get("trading_days"),
    }
    # Check for potentially misleading numbers
    issues = []
    if m.get("sharpe", 0) > 2.0:
        issues.append(f"Sharpe {m['sharpe']:.2f} may still contain residual lookahead inflation (K693 fixed same-day but check if recalc is current)")
    if m.get("annualized_return", 0) > 25:
        issues.append(f"Ann. return {m['annualized_return']:.1f}% implies alpha generation — misleading post-K687")
    if m.get("cumulative_return", 0) > 100:
        issues.append(f"Cumulative {m['cumulative_return']:.1f}% over {m.get('trading_days',0)} days — contextualize vs BH benchmark")
    entry["issues"] = issues
    strategy_metrics_claims.append(entry)

# 1C. Strategy Selector Claims
strategy_selector_claims = {
    "location": "frontend-v2-fix/src/components/StrategySelector.tsx",
    "issues": [
        {
            "strategy": "vix_cond_leverage",
            "claim": "stats: { sharpe: '0.9-1.2', mdd: '-18% ~ -25%', cagr: '14-18%' }",
            "problem": "CAGR 14-18% implies alpha. Post-K687: VT doesn't beat BH 50/50 on Sharpe. These numbers need context: they include the BH component return, not VT alpha.",
            "severity": "HIGH",
        },
        {
            "strategy": "adaptive_tier",
            "claim": "stats: { sharpe: '0.9-1.1', mdd: '-15% ~ -20%', cagr: '12-15%' }",
            "problem": "K693 corrected Adaptive from Sharpe 3.02→1.51. Current metric shows 1.51. The range '0.9-1.1' is actually closer to reality post-correction, but needs verification.",
            "severity": "MEDIUM",
        },
        {
            "strategy": "recommended_5050",
            "claim": "stats: { sharpe: '0.8-1.0', mdd: '-12% ~ -16%', cagr: '9-12%' }",
            "problem": "Current metric shows Sharpe 1.79, which is higher than the displayed range. But 50/50 BH is the benchmark — its Sharpe IS the target to match, not beat.",
            "severity": "LOW",
        },
        {
            "strategy": "fear_dca",
            "claim": "'長期下來可顯著提升報酬' in description",
            "problem": "K687: VT doesn't improve Sharpe. Fear DCA may improve dollar-cost-averaged returns via timing, but 'significantly improve returns' is overclaiming.",
            "severity": "MEDIUM",
        },
        {
            "strategy": "general",
            "claim": "Page titled '策略選擇器' with '找到最適合你的投資策略'",
            "problem": "Implies we help you pick a winning strategy. Should frame as risk management tool selection.",
            "severity": "MEDIUM",
        },
    ]
}

# 1D. Hero Section Claims
hero_section_claims = {
    "location": "frontend-v2-fix/src/components/HeroSection.tsx",
    "current_headline": "用科學方法管理投資風險",
    "current_subtitle": "基於 200+ 嚴謹實驗的波動率預測研究，為一般投資人提供可執行的策略建議",
    "stats_displayed": [
        {"value": "200+", "label": "實驗", "issue": None},
        {"value": "50/50+VT", "label": "策略", "issue": "Correctly names the strategy approach"},
        {"value": "-12%", "label": "最大回撤", "issue": "MDD claim — need to specify which strategy and period"},
    ],
    "assessment": "MOSTLY GOOD — headline correctly says '管理投資風險' not '產生超額報酬'. "
                  "But '策略建議' in subtitle could be read as investment advice. "
                  "The -12% MDD is unattributed — which strategy? Over what period?",
    "severity": "LOW",
}

# 1E. About Page Claims
about_page_claims = {
    "location": "frontend-v2-fix/src/app/about/page.tsx",
    "claims": [
        {
            "section": "研究背景",
            "text": "建立一般投資人可用的交易策略",
            "issue": "'交易策略' implies trading for profit. Post-K687: reframe as '風險管理工具'.",
            "severity": "MEDIUM",
        },
        {
            "section": "核心發現 - 50/50 + VT",
            "text": "50/50 + VT：風險管理而非超額報酬",
            "issue": None,
            "assessment": "CORRECT — this section already uses the insurance framing from K687.",
        },
        {
            "section": "核心發現 - 50/50 + VT",
            "text": "VT 的價值在於風險管理（MDD 改善統計顯著 p=0.0004），而非追求更高 Sharpe",
            "issue": None,
            "assessment": "CORRECT — perfectly aligned with K687/K700 conclusions.",
        },
    ],
    "overall_assessment": "About page is PARTIALLY aligned. The '核心發現' section is correct, "
                          "but the intro still says '交易策略'. Need to unify messaging.",
}

# 1F. Daily Article Claims
daily_article_claims = {
    "location": "scripts/daily_update.py:176-260",
    "issues": [
        {
            "text": "預測下一交易日最佳持倉配置",
            "problem": "'最佳持倉配置' implies optimality for returns. Should say '風險管理配置參考'.",
            "severity": "MEDIUM",
        },
        {
            "text": "今日策略配置 (table header)",
            "problem": "Presenting allocation as definitive. Add context: 'based on current VIX, for risk management'.",
            "severity": "LOW",
        },
        {
            "text": "操作建議",
            "problem": "'操作建議' (Operating Advice) too directive for risk management tools. "
                       "Suggest: '風險管理參考' or '配置說明'.",
            "severity": "MEDIUM",
        },
        {
            "text": "條件槓桿策略可啟動 1.5x",
            "problem": "Recommending leverage activation is aggressive. K687: leverage VT has worst lag sensitivity. "
                       "Add warning about leverage risk.",
            "severity": "HIGH",
        },
        {
            "text": "本文僅供研究參考，不構成投資建議",
            "problem": None,
            "assessment": "CORRECT — disclaimer exists but is tiny text at bottom. Should be more prominent.",
        },
    ]
}

# 1G. VIX Calculator Claims
vix_calculator_claims = {
    "location": "frontend-v2-fix/src/app/vix-calculator/page.tsx",
    "issues": [
        {
            "section": "HISTORICAL_STATS",
            "data": {
                8:  {"cagr": "6-8%",   "sharpe": "0.8-1.0"},
                10: {"cagr": "8-10%",  "sharpe": "0.9-1.2"},
                12: {"cagr": "10-13%", "sharpe": "1.0-1.4"},
                15: {"cagr": "12-16%", "sharpe": "1.0-1.3"},
            },
            "problem": "These ranges may be pre-K693 correction. Need to verify against corrected metrics. "
                       "Also, presenting CAGR prominently implies return generation rather than risk management.",
            "severity": "MEDIUM",
        },
    ]
}

# 1H. Disclaimer Page
disclaimer_claims = {
    "location": "frontend-v2-fix/src/app/disclaimer/page.tsx",
    "assessment": "GOOD — properly states '不構成投資建議', explains backtest vs reality differences, "
                  "has investment risk warning. But it's a separate page that users must navigate to.",
    "missing": [
        "No mention of K693 lookahead correction history",
        "No mention that VT strategies are insurance (MDD reduction) not alpha",
        "No inline disclaimer on strategy panel itself",
        "No mention of the specific paradigm: Sharpe improvement is NOT expected",
    ],
    "severity": "MEDIUM",
}

# ─── 2. What Research Now Supports ───────────────────────────────────────────

research_truth = {
    "K687_paradigm": {
        "conclusion": "No VT strategy beats BH 50/50 on Sharpe after proper lag correction.",
        "implication": "All website claims implying VT improves Sharpe/CAGR are misleading.",
        "what_VT_does": "Reduces MDD (statistically significant, p=0.0004). This IS the value.",
    },
    "K688_utility": {
        "conclusion": "VT wins under CRRA utility for gamma >= 5 (risk-averse investors).",
        "implication": "VT is valuable for investors who care about downside more than upside. "
                       "Frame as: 'for investors who lose more sleep over -20% than they celebrate +20%'.",
    },
    "K690_lag_robustness": {
        "conclusion": "Smooth-weight strategies (12/VIX, Risk Parity) are most lag-robust. "
                      "Piecewise is most fragile.",
        "implication": "Don't recommend Piecewise as 'safe' — it's the most affected by execution lag.",
    },
    "K693_correction": {
        "conclusion": "9,935 paper_trading entries fixed: same-day → next-day return. "
                      "Piecewise Sharpe 3.16→1.56, Adaptive 3.02→1.51.",
        "implication": "Historical performance numbers on website are from corrected data. "
                       "But any cached/screenshot values from before 2026-03-29 are wrong.",
    },
    "K694_post_correction": {
        "conclusion": "7/10 strategies still beat SPY, but Sharpe avg dropped 0.74. "
                      "BH 50/50 is the Sharpe champion.",
        "implication": "50/50 is not just a suggestion — it IS the best risk-adjusted strategy.",
    },
    "K700_three_certainties": {
        "conclusion": "1) GJR-GARCH > GARCH (confirmed 40+ times). "
                      "2) VT = insurance not alpha (confirmed K687). "
                      "3) VIX is sufficient statistic for equity vol (31x confirmed).",
        "implication": "These are settled science. Website should reflect certainty, not exploration.",
    },
}

# ─── 3. Messaging Gaps Analysis ──────────────────────────────────────────────

messaging_gaps = [
    {
        "gap_id": "GAP-01",
        "category": "Framing",
        "current": "Strategy Panel header says '投資建議' (Investment Advice)",
        "correct": "Should say '風險管理配置' (Risk Management Allocation) or '策略配置參考' (Strategy Allocation Reference)",
        "files_to_change": ["frontend-v2-fix/src/components/StrategyPanel.tsx:64"],
        "severity": "HIGH",
        "effort": "trivial (1 line change)",
    },
    {
        "gap_id": "GAP-02",
        "category": "Performance Numbers",
        "current": "Strategy panel shows Sharpe and cumulative return without context",
        "correct": "Should show MDD improvement as primary metric, Sharpe as secondary. "
                   "Or add tooltip: 'VT value is MDD reduction, not Sharpe improvement'.",
        "files_to_change": [
            "frontend-v2-fix/src/components/StrategyPanel.tsx:181-189",
        ],
        "severity": "MEDIUM",
        "effort": "moderate (change metric display order + add tooltip)",
    },
    {
        "gap_id": "GAP-03",
        "category": "Strategy Selector",
        "current": "Strategy Selector shows CAGR prominently and implies strategies generate alpha",
        "correct": "Should lead with MDD, note that CAGR includes market return (not VT alpha). "
                   "Add text: '這些策略的價值在於風險管理（降低最大回撤），而非追求更高的報酬率。'",
        "files_to_change": [
            "frontend-v2-fix/src/components/StrategySelector.tsx:15 (stats type)",
            "frontend-v2-fix/src/components/StrategySelector.tsx:514-533 (stats grid)",
        ],
        "severity": "HIGH",
        "effort": "moderate (restructure stats display)",
    },
    {
        "gap_id": "GAP-04",
        "category": "Daily Article",
        "current": "Daily article says '最佳持倉配置' and '操作建議'",
        "correct": "Should say '風險管理配置參考' and '配置說明'. "
                   "Leverage recommendation should include warning.",
        "files_to_change": [
            "scripts/daily_update.py:178",
            "scripts/daily_update.py:193",
            "scripts/daily_update.py:205",
            "scripts/daily_update.py:214",
        ],
        "severity": "MEDIUM",
        "effort": "trivial (text changes)",
    },
    {
        "gap_id": "GAP-05",
        "category": "About Page",
        "current": "Intro says '建立一般投資人可用的交易策略'",
        "correct": "Should say '建立一般投資人可用的風險管理工具'",
        "files_to_change": ["frontend-v2-fix/src/app/about/page.tsx:25"],
        "severity": "MEDIUM",
        "effort": "trivial (1 line change)",
    },
    {
        "gap_id": "GAP-06",
        "category": "Inline Disclaimer",
        "current": "Disclaimer only exists on /disclaimer page. Strategy panel has no inline disclaimer.",
        "correct": "Add small inline text under strategy panel: "
                   "'策略配置基於波動率預測，目的為風險管理而非追求超額報酬。過去績效不代表未來表現。'",
        "files_to_change": [
            "frontend-v2-fix/src/components/StrategyPanel.tsx (after strategies grid)",
        ],
        "severity": "MEDIUM",
        "effort": "trivial (add 1-2 lines)",
    },
    {
        "gap_id": "GAP-07",
        "category": "MDD as Primary Metric",
        "current": "Sharpe shown first in metrics, cumulative return highlighted. MDD is last and in red (feels bad).",
        "correct": "MDD improvement should be the HERO metric. Frame positively: "
                   "'最大回撤控制在 -X%（vs SPY -36%）'. Show as green/good, not red/bad.",
        "files_to_change": [
            "frontend-v2-fix/src/components/StrategyPanel.tsx:182-189",
            "frontend-v2-fix/src/components/StrategySelector.tsx:514-533",
        ],
        "severity": "HIGH",
        "effort": "moderate (redesign metric display)",
    },
    {
        "gap_id": "GAP-08",
        "category": "Insurance Framing",
        "current": "No explicit mention of 'insurance' framing anywhere on the public website (only in About page's core findings).",
        "correct": "Hero section or strategy panel should include: "
                   "'VT = 波動率保險：每年付約 1-4% 保費，換取最大回撤從 -34% 降至 -7%。' (K41/K687 data)",
        "files_to_change": [
            "frontend-v2-fix/src/components/HeroSection.tsx",
            "frontend-v2-fix/src/components/StrategyPanel.tsx",
        ],
        "severity": "HIGH",
        "effort": "moderate (add insurance context)",
    },
    {
        "gap_id": "GAP-09",
        "category": "VIX Calculator Stats",
        "current": "HISTORICAL_STATS shows CAGR ranges that may be pre-K693 correction",
        "correct": "Verify ranges against corrected strategy_metrics.json. "
                   "Add note: '報酬率包含市場報酬和分散化收益，非 VT 策略 alpha。'",
        "files_to_change": [
            "frontend-v2-fix/src/app/vix-calculator/page.tsx:16-21",
        ],
        "severity": "MEDIUM",
        "effort": "moderate (verify + add context)",
    },
    {
        "gap_id": "GAP-10",
        "category": "Benchmark Context",
        "current": "Strategy metrics show absolute numbers without benchmark comparison",
        "correct": "Add 'vs BH SPY' or 'vs BH 50/50' column/comparison. "
                   "K694: BH 50/50 Sharpe ~1.79 is the bar to clear (and most VT doesn't).",
        "files_to_change": [
            "frontend-v2-fix/src/components/StrategyPanel.tsx",
            "scripts/recalc_metrics.py (add benchmark metrics)",
        ],
        "severity": "MEDIUM",
        "effort": "moderate (add benchmark data to pipeline + display)",
    },
]

# ─── 4. Recommended Changes (Specific) ──────────────────────────────────────

recommended_changes = [
    {
        "priority": 1,
        "change_id": "CHG-01",
        "description": "Change Strategy Panel header from '投資建議' to '策略配置參考'",
        "file": "frontend-v2-fix/src/components/StrategyPanel.tsx",
        "line": 64,
        "current_text": "投資建議",
        "new_text": "策略配置參考",
        "rationale": "K687: VT is insurance not investment advice. Most impactful single change.",
    },
    {
        "priority": 1,
        "change_id": "CHG-02",
        "description": "Add inline disclaimer below strategy panel grid",
        "file": "frontend-v2-fix/src/components/StrategyPanel.tsx",
        "line": "after line 218 (end of strategies grid)",
        "new_text": "<p className='mt-3 text-center text-[10px] text-gray-600'>"
                    "策略配置基於波動率預測，目的為風險管理（降低最大回撤）而非追求超額報酬。"
                    "過去績效不代表未來表現。</p>",
        "rationale": "Users see disclaimer in context, not on a separate page they'll never visit.",
    },
    {
        "priority": 2,
        "change_id": "CHG-03",
        "description": "Reorder metrics in StrategyPanel: MDD first (as positive), Sharpe second",
        "file": "frontend-v2-fix/src/components/StrategyPanel.tsx",
        "lines": "181-189",
        "current_order": "cumulative_return → Sharpe → MDD",
        "new_order": "MDD_improvement (green, vs SPY benchmark) → Sharpe → cumulative_return",
        "rationale": "K687: MDD is VT's actual value. Show it first and positively.",
    },
    {
        "priority": 2,
        "change_id": "CHG-04",
        "description": "Strategy Selector: add insurance framing and de-emphasize CAGR",
        "file": "frontend-v2-fix/src/components/StrategySelector.tsx",
        "changes": [
            "Change stats grid label from '年化報酬' to '年化報酬（含市場）'",
            "Add subtitle to all strategies: '風險管理工具'",
            "Add disclaimer: '這些策略的價值在於風險管理（降低最大回撤），而非追求更高的報酬率。'",
        ],
        "rationale": "Strategy Selector is high-traffic page; users shouldn't leave thinking VT = alpha.",
    },
    {
        "priority": 2,
        "change_id": "CHG-05",
        "description": "About page: change '交易策略' to '風險管理工具'",
        "file": "frontend-v2-fix/src/app/about/page.tsx",
        "line": 25,
        "current_text": "建立一般投資人可用的交易策略",
        "new_text": "建立一般投資人可用的風險管理工具",
        "rationale": "Align with K687 paradigm shift.",
    },
    {
        "priority": 3,
        "change_id": "CHG-06",
        "description": "Daily article: reframe language",
        "file": "scripts/daily_update.py",
        "changes": [
            {"line": 178, "from": "預測下一交易日最佳持倉配置", "to": "下一交易日風險管理配置參考"},
            {"line": 205, "from": "操作建議", "to": "配置說明"},
            {"line": 214, "add_warning": "條件槓桿策略可啟動 1.5x → 加入 '（注意：槓桿會放大損失，K690 研究顯示槓桿策略對執行延遲最敏感）'"},
        ],
        "rationale": "Daily articles are the most-read content; language shapes expectations.",
    },
    {
        "priority": 3,
        "change_id": "CHG-07",
        "description": "Hero Section: add insurance framing to stats",
        "file": "frontend-v2-fix/src/components/HeroSection.tsx",
        "changes": [
            "Change stat '-12%, 最大回撤' to '-12% MDD, 風險保險' (specify it's about protection)",
            "Add attribution: '(50/50+VT 策略)' after -12%",
        ],
        "rationale": "Hero is first thing users see. Set correct expectations immediately.",
    },
    {
        "priority": 3,
        "change_id": "CHG-08",
        "description": "VIX Calculator: add context to HISTORICAL_STATS",
        "file": "frontend-v2-fix/src/app/vix-calculator/page.tsx",
        "changes": [
            "Add note under stats: '報酬率包含市場報酬，非策略額外 alpha'",
            "Verify ranges against post-K693 corrected data",
        ],
        "rationale": "Calculator users may interpret projected returns as guaranteed alpha.",
    },
    {
        "priority": 4,
        "change_id": "CHG-09",
        "description": "Add benchmark comparison to strategy metrics",
        "file": "scripts/recalc_metrics.py + frontend-v2-fix/src/components/StrategyPanel.tsx",
        "changes": [
            "Calculate BH SPY and BH 50/50 metrics alongside strategy metrics",
            "Display as 'vs BH 50/50: Sharpe -0.03, MDD +24pp improvement'",
        ],
        "rationale": "K694: Without benchmark context, raw numbers are misleading.",
    },
]

# ─── 5. Summary ──────────────────────────────────────────────────────────────

# Score current alignment (0-10)
alignment_scores = {
    "hero_section": 7,        # Correctly says '管理投資風險', but MDD unattributed
    "strategy_panel": 3,      # '投資建議' header is wrong; no insurance framing
    "strategy_selector": 4,   # Shows CAGR prominently; implies alpha
    "about_page": 7,          # Core findings section correct; intro wording off
    "disclaimer_page": 8,     # Properly covers legal bases; missing insurance context
    "daily_article": 5,       # '最佳持倉配置' and '操作建議' imply alpha; disclaimer exists
    "vix_calculator": 5,      # CAGR prominent; no insurance framing
    "overall": 5,             # Weighted average — major gap in primary user-facing surfaces
}

high_severity_count = sum(1 for g in messaging_gaps if g["severity"] == "HIGH")
medium_severity_count = sum(1 for g in messaging_gaps if g["severity"] == "MEDIUM")
low_severity_count = sum(1 for g in messaging_gaps if g["severity"] == "LOW")

summary = {
    "experiment_id": "K705",
    "title": "Website Messaging Audit — Post-K687 Paradigm Shift",
    "date": datetime.now().isoformat(),
    "key_finding": (
        "The website's messaging is PARTIALLY misaligned with research conclusions. "
        "The About page correctly states VT=insurance, but primary user-facing surfaces "
        "(Strategy Panel, Strategy Selector, daily articles) still frame VT as investment advice "
        "and emphasize Sharpe/CAGR rather than MDD improvement. "
        f"Found {len(messaging_gaps)} messaging gaps: {high_severity_count} HIGH, "
        f"{medium_severity_count} MEDIUM, {low_severity_count} LOW severity."
    ),
    "alignment_scores": alignment_scores,
    "critical_changes_needed": [
        "CHG-01: Strategy Panel header '投資建議' → '策略配置參考' (most impactful single fix)",
        "CHG-02: Add inline disclaimer under strategy panel",
        "CHG-03: Reorder metrics — MDD first (as positive), Sharpe second",
        "CHG-08: Insurance framing in Hero Section and Strategy Selector",
    ],
    "post_K693_metric_status": {
        "strategy_metrics.json": "CORRECTED — recalculated after 9,935 entry fix",
        "piecewise_sharpe": f"{metrics.get('piecewise_conservative', {}).get('sharpe', 'N/A')} (was 3.16 pre-K693)",
        "adaptive_sharpe": f"{metrics.get('adaptive_tier', {}).get('sharpe', 'N/A')} (was 3.02 pre-K693)",
        "risk_parity_sharpe": f"{metrics.get('risk_parity', {}).get('sharpe', 'N/A')} (barely changed, smooth weights)",
        "bh_5050_sharpe": f"{metrics.get('recommended_5050', {}).get('sharpe', 'N/A')} (benchmark — best risk-adjusted)",
    },
}

# ─── Save Results ─────────────────────────────────────────────────────────────

results = {
    "experiment_id": "K705",
    "title": "Website Messaging Audit — Post-K687 Paradigm Shift",
    "date": datetime.now().isoformat(),
    "data_source": "frontend-v2-fix source code + storage/strategy_metrics.json + knowledge.json",
    "references": [
        "K687: No VT beats BH 50/50 on Sharpe after proper lag",
        "K688: VT wins under CRRA utility for gamma >= 5",
        "K690: EWMA VT most lag-robust; Piecewise most fragile",
        "K693: 9,935 paper_trading entries corrected",
        "K694: Post-correction audit — 7/10 still beat SPY",
        "K700: 80 experiments, 3 certainties, VT=insurance",
    ],
    "section_1_current_claims": {
        "strategy_panel": strategy_panel_claims,
        "strategy_metrics": strategy_metrics_claims,
        "strategy_selector": strategy_selector_claims,
        "hero_section": hero_section_claims,
        "about_page": about_page_claims,
        "daily_article": daily_article_claims,
        "vix_calculator": vix_calculator_claims,
        "disclaimer": disclaimer_claims,
    },
    "section_2_research_truth": research_truth,
    "section_3_messaging_gaps": messaging_gaps,
    "section_4_recommended_changes": recommended_changes,
    "section_5_summary": summary,
}

results_path = WORKTREE / "experiments" / "k705_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"K705 Results saved to: {results_path}")
print()
print("=" * 70)
print("K705: WEBSITE MESSAGING AUDIT SUMMARY")
print("=" * 70)
print()
print(f"Overall Alignment Score: {alignment_scores['overall']}/10")
print(f"Messaging Gaps Found: {len(messaging_gaps)}")
print(f"  HIGH severity: {high_severity_count}")
print(f"  MEDIUM severity: {medium_severity_count}")
print(f"  LOW severity: {low_severity_count}")
print()
print("TOP 4 CRITICAL CHANGES:")
for i, chg in enumerate(recommended_changes[:4], 1):
    print(f"  {i}. [{chg['change_id']}] {chg['description']}")
    print(f"     File: {chg['file']}")
print()
print("KEY PARADIGM SHIFT (K687/K700):")
print("  VT strategies are INSURANCE (MDD reduction), not ALPHA (Sharpe improvement).")
print("  The website should frame VT as risk management, not investment advice.")
print()
print("POST-K693 METRIC STATUS:")
print(f"  Piecewise Sharpe: {metrics.get('piecewise_conservative', {}).get('sharpe', 'N/A')} (was 3.16)")
print(f"  Adaptive Sharpe:  {metrics.get('adaptive_tier', {}).get('sharpe', 'N/A')} (was 3.02)")
print(f"  BH 50/50 Sharpe:  {metrics.get('recommended_5050', {}).get('sharpe', 'N/A')} (benchmark)")
print(f"  Risk Parity:      {metrics.get('risk_parity', {}).get('sharpe', 'N/A')} (smooth, barely changed)")
