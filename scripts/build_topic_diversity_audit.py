"""Regenerate docs/topic_diversity_audit.md.

Pulls topic signals from three sources (all via jq streaming — never full load):
    1. storage/reports/feed.json       — article tags
    2. experiments/                    — directory names (fast ls, local only)
    3. storage/memory/knowledge.json   — K categories + content keyword scan

Produces a gap-analysis report: dominant clusters, under-explored topics,
5-10 novelty candidates for selection by the main thread.

Manual-trigger only — NOT in daily_update.py (user 2026-04-19 rule).
Usage:
    uv run python scripts/build_topic_diversity_audit.py

Idempotent: overwrites docs/topic_diversity_audit.md.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
KNOWLEDGE_PATH = ROOT / "storage" / "memory" / "knowledge.json"
EXPERIMENTS_DIR = ROOT / "experiments"
OUT_DOC = ROOT / "docs" / "topic_diversity_audit.md"

# Stop-words / generic labels we want to exclude from topic frequency.
STOP_TAGS = {
    "研究", "一般讀者", "daily", "研究者", "研究心得", "NULL", "Null Result",
    "null", "daily-update", "methodology", "Q&A", "會員提問", "strategy",
    "投資策略", "投資組合", "投資觀念", "投資入門", "分散投資", "分散化",
    "策略", "策略評估", "策略配置", "資產配置", "回測", "預測",
    "模型比較", "自我修正", "研究誠實", "audience=general",
    "volatility", "forecasting", "correlation", "portfolio", "hedge",
    "regime", "crypto", "cross-asset", "cross-market", "event-study",
    "microstructure", "lead-lag", "meta-analysis", "drawdown",
    "K", "Phase G", "Phase K", "Phase S", "Phase_K", "Paper2", "Paper4",
    "Paper 2", "Paper 4", "Paper 9", "Paper 10", "Paper_2", "Paper9",
    "cross-OOS",
}
# Also exclude pure K-numbers like "K513"
K_RE = re.compile(r"^[kK]\d{2,}$|^[iI]\d+[a-z]?$")


def _jq(prog: str, path: Path) -> str:
    return subprocess.run(
        ["jq", "-c", prog, str(path)],
        check=True, capture_output=True, text=True,
    ).stdout


def _feed_tags() -> Counter:
    """Top tags from feed.json (excluding stop list + K labels)."""
    raw = _jq(".[] | .tags // []", FEED_PATH)
    ctr: Counter = Counter()
    latest_date: dict[str, str] = {}
    # We also want per-tag latest date — need another jq pass with date join.
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            tags = json.loads(line)
        except json.JSONDecodeError:
            continue
        for t in tags:
            if not isinstance(t, str):
                continue
            t_s = t.strip()
            if not t_s or t_s in STOP_TAGS or K_RE.match(t_s):
                continue
            ctr[t_s] += 1
    return ctr


def _feed_tag_latest_date() -> dict[str, str]:
    """For each tag, the latest article date."""
    raw = _jq(".[] | {d: (.published_at // .created_at), t: (.tags // [])}", FEED_PATH)
    latest: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        d = rec.get("d") or ""
        for t in rec.get("t") or []:
            if not isinstance(t, str):
                continue
            t_s = t.strip()
            if not t_s:
                continue
            if t_s not in latest or d > latest[t_s]:
                latest[t_s] = d
    return latest


def _experiment_tokens() -> Counter:
    """Tokens from experiment directory names (non-K experiments).

    K### dirs are just serial IDs without topic info; the named ones (e.g.
    `gjr_vs_ewma_crisis`) carry the topic signal.
    """
    ctr: Counter = Counter()
    if not EXPERIMENTS_DIR.exists():
        return ctr
    for p in EXPERIMENTS_DIR.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if K_RE.match(name) or name.startswith("_") or name in {"charts", "__pycache__"}:
            continue
        # Split on underscore + hyphen; drop short tokens.
        for tok in re.split(r"[_\-]", name.lower()):
            if len(tok) < 3 or tok.isdigit():
                continue
            ctr[tok] += 1
    return ctr


def _experiment_count_by_tag(tag: str) -> int:
    """Rough count of experiments related to a tag (substring match on name)."""
    if not EXPERIMENTS_DIR.exists():
        return 0
    needle = tag.lower().replace("-", "").replace(" ", "")
    count = 0
    for p in EXPERIMENTS_DIR.iterdir():
        if not p.is_dir():
            continue
        name = p.name.lower().replace("-", "").replace("_", "")
        if needle and needle in name:
            count += 1
    return count


def _knowledge_categories() -> Counter:
    raw = _jq(".[] | .category // \"unknown\"", KNOWLEDGE_PATH)
    ctr: Counter = Counter()
    for line in raw.splitlines():
        t = line.strip().strip('"')
        if t:
            ctr[t] += 1
    return ctr


def _knowledge_keyword_hits(keywords: list[str]) -> dict[str, int]:
    """For each keyword, how many K records' content contain it (case-insensitive)."""
    # Single jq pass: output lowercased content strings.
    raw = _jq(".[] | (.content // \"\")", KNOWLEDGE_PATH)
    hits = {kw: 0 for kw in keywords}
    lowered_kw = [kw.lower() for kw in keywords]
    # Each line is a JSON string on its own.
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            content = json.loads(line).lower()
        except json.JSONDecodeError:
            continue
        for i, kw in enumerate(lowered_kw):
            if kw in content:
                hits[keywords[i]] += 1
    return hits


# Candidate under-explored / novelty topic ideas to probe.
# Each entry: (label, keyword substrings to search in knowledge content).
PROBE_TOPICS = [
    ("climate / physical risk / ESG", ["climate", "esg", "physical risk", "綠能", "碳"]),
    ("reinforcement learning vol", ["reinforcement", "rl agent", "q-learning"]),
    ("high-frequency microstructure (sub-5min)", ["tick-by-tick", "millisecond", "microburst"]),
    ("sentiment / NLP text signals", ["sentiment", "news text", "fomc transcript", "twitter"]),
    ("options IV surface / skew dynamics", ["iv surface", "skew dynamic", "butterfly", "risk reversal"]),
    ("cross-border policy / geopolitical", ["geopolit", "sanction", "cross-border policy"]),
    ("credit / CDS / funding stress", ["cds", "credit spread", "funding stress", "libor-ois"]),
    ("commodities ex-GLD (oil, copper, ag)", ["crude oil", "copper", "agricultural", "wti"]),
    ("FX vol / DXY / carry", ["fx volatility", "dxy", "carry trade", "yen carry"]),
    ("REIT / housing vol", ["reit", "housing vol", "mortgage"]),
    ("intraday seasonality / session-boundary", ["intraday seasonal", "u-shape intraday"]),
    ("ML interpretability / SHAP", ["shap", "interpretability", "feature importance"]),
    ("realized semivariance / signed jumps", ["semivariance", "signed jump"]),
    ("dynamic Nelson-Siegel / term structure ML", ["nelson-siegel", "term structure ml"]),
    ("crypto-stablecoin spillover", ["stablecoin", "tether depeg", "usdt"]),
    ("climate event vol (已有 1 experiment — extend)", ["climate event", "hurricane", "heatwave"]),
    ("retail order flow / gamma squeeze", ["gamma squeeze", "retail flow", "wsb"]),
    ("network / systemic risk (ex-CoVaR)", ["spillover index", "diebold-yilmaz", "network connectedness"]),
    ("model confidence sets / SPA / Reality Check", ["reality check", "spa test", "hansen test"]),
    ("bayesian model averaging vol", ["bma", "bayesian averaging", "model averaging"]),
]


def _top_n_markdown(counter: Counter, n: int) -> list[tuple[str, int]]:
    return counter.most_common(n)


def _build_doc() -> str:
    now = datetime.now(timezone.utc)
    feed_tags = _feed_tags()
    latest_by_tag = _feed_tag_latest_date()
    exp_tokens = _experiment_tokens()
    kn_cats = _knowledge_categories()

    # Dominant clusters: collapse synonym variants into canonical cluster names.
    # Each cluster: canonical_name → list of tag variants.
    CLUSTERS: list[tuple[str, list[str]]] = [
        ("VIX & VIX-derivatives", ["VIX", "VIX/GARCH", "VVIX", "VIX9D", "12/VIX", "VIX 條件槓桿"]),
        ("VT strategies / VT-family", ["VT策略", "VT", "Hybrid-VT", "波動率目標", "Risk-Parity", "Risk Parity"]),
        ("GARCH family (GARCH/GJR/EGARCH)", ["GARCH", "GJR-GARCH", "GJR", "EGARCH", "EWMA"]),
        ("HAR-RV / realized vol", ["HAR-RV", "HAR", "Realized-GARCH", "Yang-Zhang", "Parkinson"]),
        ("GARCH-MIDAS / mixed-frequency", ["GARCH-MIDAS", "MF-GJR", "MF-GJR-X"]),
        ("VaR / ES / tail risk", ["VaR", "ES", "Normal-VaR", "CF-VaR", "EVT", "FHS", "CAViaR", "Kupiec", "Christoffersen", "尾部風險"]),
        ("Taiwan market (0050 / TAIFEX)", ["0050.TW", "台股", "台指期", "TAIFEX", "Taiwan", "0056.TW", "2330.TW", "台灣市場"]),
        ("FOMC / Fed / rate events", ["FOMC", "Fed", "NFP", "CPI", "2022升息"]),
        ("Earnings / corporate events", ["earnings", "法說會", "財報日", "台積電"]),
        ("Crypto / BTC / ETH", ["BTC", "BTC-USD", "ETH", "加密貨幣", "比特幣", "DeFi"]),
        ("GLD / gold / commodities", ["GLD", "黃金", "USO", "SLV", "XLE"]),
        ("SPY / US equity core", ["SPY", "QQQ", "XLF"]),
        ("TLT / bonds / duration", ["TLT"]),
        ("Leverage / regime / gamma", ["槓桿", "Gamma效應", "Gamma-Mechanism"]),
        ("Model diagnostics (DM / MCS / QLIKE)", ["DM-test", "DM test", "DM檢定", "MCS", "QLIKE", "QLIKE-ceiling", "Harvey", "Harvey門檻", "R-squared"]),
        ("Overnight / intraday / gap", ["隔夜波動", "夜盤", "市場微結構"]),
        ("VRP / options", ["VRP", "選擇權", "Straddle"]),
        ("Momentum / TSMOM", ["momentum", "TSMOM"]),
        ("Behavioral / DCA / retail", ["行為金融", "定期定額", "DCA", "恐慌", "FOMO"]),
        ("Copula / DCC / dependence", ["Copula", "DCC-GARCH", "CoVaR"]),
        ("Bayesian / SSVS / ML-avg", ["Bayesian", "SSVS", "Monte Carlo"]),
        ("Deep learning (LSTM / NN)", ["LSTM", "GINN", "AI", "機器學習"]),
    ]

    cluster_totals: list[tuple[str, int, int, str]] = []
    for name, variants in CLUSTERS:
        total = sum(feed_tags.get(v, 0) for v in variants)
        exp_ct = sum(_experiment_count_by_tag(v) for v in variants)
        dates = [latest_by_tag.get(v, "") for v in variants if latest_by_tag.get(v)]
        latest = max(dates)[:10] if dates else "?"
        cluster_totals.append((name, total, exp_ct, latest))
    cluster_totals.sort(key=lambda x: -x[1])

    # Under-explored probe
    probe_rows: list[tuple[str, int, int]] = []
    all_keywords = []
    for _, kws in PROBE_TOPICS:
        all_keywords.extend(kws)
    # Also search feed content tags for these keywords (substring in tag str).
    all_feed_tags_lower = {t.lower(): c for t, c in feed_tags.items()}
    kn_hits = _knowledge_keyword_hits(all_keywords)
    for label, kws in PROBE_TOPICS:
        feed_ct = 0
        for t_low, c in all_feed_tags_lower.items():
            if any(kw.lower() in t_low for kw in kws):
                feed_ct += c
        k_ct = sum(kn_hits.get(kw, 0) for kw in kws)
        probe_rows.append((label, feed_ct, k_ct))
    probe_rows.sort(key=lambda x: (x[1] + x[2] * 0.3))

    # Recommended novelty candidates: those with feed_ct == 0 and k_ct < threshold
    novelty = [row for row in probe_rows if row[1] == 0][:10]

    # Build markdown
    L: list[str] = []
    L.append("# Topic Diversity Audit")
    L.append("")
    L.append(
        f"_Generated: {now.strftime('%Y-%m-%d %H:%M UTC')} — "
        f"source: `storage/reports/feed.json` (tags), `experiments/` (dir names), "
        f"`storage/memory/knowledge.json` (K categories + content keyword scan). "
        f"Re-run: `uv run python scripts/build_topic_diversity_audit.py`._"
    )
    L.append("")
    L.append("## Purpose")
    L.append("")
    L.append(
        "1. Show the **dominant topic axes** the platform has accumulated — so the main thread can see where the coverage is.\n"
        "2. Surface **under-explored topics** for novelty quota selection "
        "(per user 2026-04-19 directive: reserve slots to step off the dominant axes)."
    )
    L.append("")

    # Raw stats
    L.append("## Source-level Stats")
    L.append("")
    L.append(f"- Feed tags: {sum(feed_tags.values())} total tokens / {len(feed_tags)} unique (after stop-word filter)")
    L.append(f"- Experiments: {sum(1 for p in EXPERIMENTS_DIR.iterdir() if p.is_dir())} dirs (K-numbered + named)")
    L.append(f"- Knowledge records: sum of category counts = {sum(kn_cats.values())}")
    L.append("")

    # Top feed tags
    L.append("## Top 30 feed tags (topic signal, stop-words removed)")
    L.append("")
    L.append("| rank | tag | count | latest article |")
    L.append("|---|---|---|---|")
    for i, (tag, n) in enumerate(_top_n_markdown(feed_tags, 30), 1):
        dt = latest_by_tag.get(tag, "")[:10] or "?"
        L.append(f"| {i} | {tag} | {n} | {dt} |")
    L.append("")

    # Top experiment tokens
    L.append("## Top 20 experiment-dir tokens (from named experiments)")
    L.append("")
    L.append("| rank | token | count |")
    L.append("|---|---|---|")
    for i, (tok, n) in enumerate(_top_n_markdown(exp_tokens, 20), 1):
        L.append(f"| {i} | {tok} | {n} |")
    L.append("")

    # Knowledge categories
    L.append("## Top 20 knowledge.json categories")
    L.append("")
    L.append("| rank | category | count |")
    L.append("|---|---|---|")
    for i, (c, n) in enumerate(_top_n_markdown(kn_cats, 20), 1):
        L.append(f"| {i} | {c} | {n} |")
    L.append("")

    # Dominant clusters
    L.append("## Dominant topic clusters (synthesized)")
    L.append("")
    L.append(
        "Each cluster aggregates related tags. `feed_ct` = sum of tag counts in feed.json; "
        "`exp_ct` = experiments with dir-name matching any cluster keyword (approx)."
    )
    L.append("")
    L.append("| cluster | feed_ct | exp_ct | latest feed date |")
    L.append("|---|---|---|---|")
    for name, total, exp_ct, latest in cluster_totals:
        L.append(f"| {name} | {total} | {exp_ct} | {latest} |")
    L.append("")

    # Probe / under-explored
    L.append("## Under-explored topic probe")
    L.append("")
    L.append(
        "Each probed topic: how many feed tags & knowledge-records mention its keywords. "
        "Low scores = genuine gaps; `feed_ct=0` with small `kb_ct` = novelty quota candidates."
    )
    L.append("")
    L.append("| topic | feed_ct | kb_ct (content match) |")
    L.append("|---|---|---|")
    for label, feed_ct, k_ct in probe_rows:
        L.append(f"| {label} | {feed_ct} | {k_ct} |")
    L.append("")

    # Recommended novelty candidates (user asked 5-10)
    L.append("## Recommended novelty candidates (5-10)")
    L.append("")
    L.append(
        "These are topics with **no feed coverage** (feed_ct=0) and "
        "low knowledge-base footprint. Pick 1-2 per novelty-quota cycle; confirm no "
        "in-flight experiment before dispatching."
    )
    L.append("")
    if not novelty:
        L.append("_(none — all probe topics have some feed coverage; extend PROBE_TOPICS to find new gaps)_")
    else:
        for i, (label, feed_ct, k_ct) in enumerate(novelty[:10], 1):
            L.append(f"{i}. **{label}** — feed_ct={feed_ct}, kb_ct={k_ct}")
    L.append("")

    # Notes
    L.append("## Notes / methodology")
    L.append("")
    L.append(
        "- Stop-words (`研究`, `一般讀者`, K-numbers, etc.) removed from tag frequency to avoid "
        "swamping the top table.\n"
        "- `exp_ct` uses substring match on directory name; it under-counts K-numbered experiments "
        "(which are labeled by serial ID, not topic). The true experiment coverage for each cluster "
        "is higher — treat `exp_ct` as a lower bound.\n"
        "- `kb_ct` counts distinct K records whose `content` field contains any probe keyword "
        "(case-insensitive).\n"
        "- To refine gap detection, extend `PROBE_TOPICS` in "
        "`scripts/build_topic_diversity_audit.py`."
    )
    L.append("")
    return "\n".join(L) + "\n"


def main() -> None:
    try:
        doc = _build_doc()
        OUT_DOC.write_text(doc)
        print(f"[topic-audit] wrote {OUT_DOC.relative_to(ROOT)} ({len(doc):,} chars)")
    except Exception as e:  # noqa: BLE001
        print(f"[topic-audit] failed: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
