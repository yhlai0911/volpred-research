"""Content Correction Scanner (K321)

Scans published articles for claims that contradict current knowledge.
Reads self-correction entries from knowledge.json, extracts the CORRECTED
claim's distinctive fingerprint (compound keyword sets), then scans all
articles in storage/reports/ and feed.json for potentially outdated content.

Design principle: avoid flagging every article that mentions "VIX" or "GARCH".
Instead, require co-occurrence of SPECIFIC claim identifiers — the particular
combination of asset+model+concept+metric that was corrected.

Usage:
    uv run python scripts/content_correction_scanner.py
    uv run python scripts/content_correction_scanner.py --verbose
    uv run python scripts/content_correction_scanner.py --output results.json
    uv run python scripts/content_correction_scanner.py --min-severity medium
    uv run python scripts/content_correction_scanner.py --published-only
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

PROJECT = Path(__file__).resolve().parent.parent
KNOWLEDGE_PATH = PROJECT / "storage" / "memory" / "knowledge.json"
REPORTS_DIR = PROJECT / "storage" / "reports"
FEED_PATH = REPORTS_DIR / "feed.json"
DEFAULT_OUTPUT = PROJECT / "storage" / "content_correction_report.json"


def _warn_content_correction(message: str, path: Path, exc: Exception) -> None:
    print(
        f"[content_correction_scanner] WARN {message}: "
        f"path={path} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# 1. Self-correction detection patterns
# ---------------------------------------------------------------------------

CORRECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bREVERSES?\b"),
    re.compile(r"推翻"),
    re.compile(r"\bself[- ]correction\b", re.IGNORECASE),
    re.compile(r"\boverturned\b", re.IGNORECASE),
    re.compile(r"\binvalidat\w*\b", re.IGNORECASE),
    re.compile(r"\bFAIL Harvey\b"),
    re.compile(r"\bartifact\b", re.IGNORECASE),
    re.compile(r"\bspurious\b", re.IGNORECASE),
    re.compile(r"\bmisleading\b", re.IGNORECASE),
    re.compile(r"\bcorrected\b", re.IGNORECASE),
    re.compile(r"\breversal\b", re.IGNORECASE),
    re.compile(r"\breversed\b", re.IGNORECASE),
    re.compile(r"\bnot real\b", re.IGNORECASE),
    re.compile(r"無效"),
    re.compile(r"錯誤"),
    re.compile(r"否定"),
    re.compile(r"\bdebunk\w*\b", re.IGNORECASE),
    re.compile(r"\bwas wrong\b", re.IGNORECASE),
    re.compile(r"\bincorrect\b", re.IGNORECASE),
    re.compile(r"\bNULL RESULT\b", re.IGNORECASE),
]

HIGH_SEVERITY_PATTERNS = {
    "REVERSES", "REVERSE", "推翻", "self-correction", "self correction",
    "overturned",
}
MEDIUM_SEVERITY_PATTERNS = {
    "artifact", "spurious", "misleading", "FAIL Harvey", "invalidat",
    "corrected", "reversed", "reversal",
}

# ---------------------------------------------------------------------------
# 2. Claim fingerprint extraction
# ---------------------------------------------------------------------------
# The key insight: a correction is about a SPECIFIC claim, identified by the
# combination of (subject + predicate). Generic terms like "VIX" or "GARCH"
# appear in nearly every article. What makes a claim specific is the
# COMBINATION — e.g., "FOMC" + "VIX" + "tradeable" identifies the
# FOMC-VIX pattern claim specifically.
#
# We split keywords into tiers:
#   - ANCHOR keywords: specific to the corrected claim (rare across articles)
#   - CONTEXT keywords: domain terms that narrow the topic
#
# Matching requires: >= 1 anchor + >= N context keywords from the SAME
# correction entry.

# Terms that are too common to be useful alone (appear in >30% of articles)
UBIQUITOUS_TERMS = {
    "VIX", "GARCH", "GJR", "SPY", "Sharpe", "MDD", "VT", "QLIKE",
    "OOS", "波動率", "策略", "投資", "風險", "報酬", "預測",
    "市場", "模型", "信號", "研究", "實驗",
}

# Stop words for keyword extraction
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "need", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "between", "out", "off", "over", "under", "again",
    "then", "once", "here", "there", "when", "where", "why", "how", "all",
    "both", "each", "few", "more", "most", "other", "some", "such", "no",
    "not", "only", "same", "so", "than", "too", "very", "and", "but", "or",
    "if", "while", "because", "until", "that", "which", "who", "this",
    "these", "those", "it", "its", "they", "them", "their", "we", "our",
    "you", "your", "about", "just", "also", "vs", "etc",
    "result", "results", "data", "test", "tests", "analysis", "method",
    "model", "models", "using", "based", "shows", "found", "however",
    "conclusion", "significant", "evidence", "sample", "period",
    "claude", "gemini", "codex", "提出", "執行",
}

# Chinese generic stop phrases
CHINESE_STOPS = {
    "結論", "方法", "結果", "分析", "測試", "數據", "建議", "發現", "確認",
    "提出", "執行", "修正", "注意", "波動率", "策略", "投資", "風險", "報酬",
    "預測", "市場", "模型", "信號", "研究", "實驗", "估計", "計算", "顯著",
    "證據", "假設", "統計",
}


@dataclass
class CorrectionEntry:
    """A knowledge entry that represents a self-correction or reversal."""
    knowledge_id: str
    content: str
    category: str
    matched_patterns: list[str]
    severity: str
    anchor_keywords: list[str] = field(default_factory=list)
    context_keywords: list[str] = field(default_factory=list)
    knowledge_refs: list[str] = field(default_factory=list)
    claim_summary: str = ""  # short description of what was corrected


@dataclass
class ArticleMatch:
    """An article that potentially contains outdated claims."""
    article_id: str
    title: str
    status: str
    source_file: str
    matched_keywords: list[str]
    correction_sources: list[dict]
    max_severity: str
    relevance_score: float = 0.0  # higher = more likely outdated
    text_snippets: list[str] = field(default_factory=list)


def extract_knowledge_refs(text: str) -> list[str]:
    """Extract knowledge reference IDs like K36, K85, K222 from text."""
    return re.findall(r"\bK\d{1,4}\b", text)


def extract_experiment_refs(text: str) -> list[str]:
    """Extract experiment references like R2, R13, T3, T15, J7, G8, etc."""
    return re.findall(r"\b[RTJGP]\d{1,3}\b", text)


def extract_claim_fingerprint(text: str) -> tuple[list[str], list[str]]:
    """Extract anchor and context keywords from a correction entry.

    Anchor keywords: specific identifiers that narrow the claim
      - Knowledge refs (K36, K85, K222)
      - Experiment refs (R2, J7, T15)
      - Multi-word specific phrases (e.g., "FOMC-VIX", "pairs trading")
      - Specific numeric claims (e.g., "Sharpe 3.09")
      - Non-ubiquitous domain terms (e.g., "CARR", "TSMOM", "FOMC")

    Context keywords: broader domain terms that provide topic context
      - Ubiquitous terms (VIX, GARCH, SPY) — only useful WITH anchors
      - Asset names, model names
    """
    anchors = set()
    context = set()

    # 1. Knowledge references (always anchors — very specific)
    for ref in extract_knowledge_refs(text):
        anchors.add(ref)

    # 2. Experiment references (always anchors)
    for ref in extract_experiment_refs(text):
        anchors.add(ref)

    # 3. Compound terms with hyphens/slashes (usually specific)
    for match in re.finditer(r"\b\w+[-/]\w+(?:[-/]\w+)*\b", text):
        term = match.group(0)
        if len(term) >= 4 and term not in {"t-test", "p-value", "out-of"}:
            if any(c.isupper() for c in term) or any(
                "\u4e00" <= c <= "\u9fff" for c in term
            ):
                if term in UBIQUITOUS_TERMS:
                    context.add(term)
                else:
                    anchors.add(term)

    # 4. Specific numeric claims (very specific to a claim)
    for match in re.finditer(
        r"(Sharpe|QLIKE|MDD|Calmar|t)\s*[=:]?\s*[-+]?\d+\.\d+", text
    ):
        anchors.add(match.group(0).strip())

    # 5. Quoted phrases (author intentionally highlighted these)
    for match in re.finditer(r'[「\'"]([^「」\'"]{3,40})[」\'"]', text):
        phrase = match.group(1).strip()
        if len(phrase) >= 3 and phrase.lower() not in STOP_WORDS:
            anchors.add(phrase)

    # 6. Domain terms — classify as anchor or context
    domain_anchors = {
        # Less common models/concepts (anchor-worthy)
        "CARR", "MF2", "RFSV", "TSMOM", "HAR-RV",
        "FOMC", "Hurst",
        "cointegration", "dispersion", "straddle",
        # Assets that narrow the claim (less common ones only)
        "IEF", "AGG", "LQD", "HYG", "UUP", "USO", "XLE", "DBA", "KIE",
        "AUD/JPY",
        # Specific multi-word strategy/concept terms
        "pairs trading", "carry trade", "time-zone arbitrage",
        "trend following", "rough volatility", "phase transition",
        "correlation breakdown", "weight smoothness",
        "PUT/CALL ratio",
        "Monte Carlo",
        "GARCH-MIDAS", "GARCH-X", "MF2-GARCH",
    }
    domain_context = {
        # Common terms (context only — too ubiquitous to be anchors)
        "VIX", "GARCH", "GJR", "EGARCH", "SPY", "GLD", "TLT", "QQQ",
        "EEM", "BTC", "0050", "VT", "VaR",
        "Sharpe", "QLIKE", "MDD", "50/50", "12/VIX", "15/VIX",
        "bootstrap", "Harvey",
        # Generic English words that appear broadly
        "EWMA", "Parkinson", "leverage", "leveraged",
        "overnight", "gap", "retirement", "withdrawal",
        "momentum", "PCR", "climate", "weather",
    }

    for term in domain_anchors:
        if term.lower() in text.lower() or term in text:
            anchors.add(term)
    for term in domain_context:
        if term in text:
            context.add(term)

    # 7. Chinese phrases — DISABLED for automated extraction.
    # Chinese character n-grams produce too many false positives because
    # short phrases appear across many unrelated articles. Instead, Chinese
    # claim identifiers should come from the domain_anchors list above
    # (manually curated) or from quoted phrases (rule 5).
    pass

    # 8. Capitalized multi-word phrases (specific concepts)
    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        phrase = match.group(0)
        if len(phrase) > 8 and phrase.lower() not in STOP_WORDS:
            anchors.add(phrase)

    # Remove any stop words that leaked through
    anchors = {
        kw for kw in anchors
        if kw.lower() not in STOP_WORDS and len(kw) >= 2
    }
    context = {
        kw for kw in context
        if kw.lower() not in STOP_WORDS and len(kw) >= 2
    }

    # Ensure no overlap: if something is in anchors, remove from context
    context -= anchors

    return sorted(anchors), sorted(context)


def extract_claim_summary(text: str) -> str:
    """Extract a short summary of what was corrected.

    Looks for the key conclusion/correction statement.
    """
    # Look for patterns that indicate the correction conclusion
    conclusion_patterns = [
        r"結論[：:]\s*(.{10,100})",
        r"修正[：:]\s*(.{10,100})",
        r"CRITICAL[：:]\s*(.{10,100})",
        r"★+\s*(.{10,80})",
        r"NOT\s+\w+able",
        r"FAILS?\b.{5,60}",
        r"無增量.{0,30}",
    ]
    for pat in conclusion_patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0)[:120].replace("\n", " ")
    # Fallback: first sentence
    return text[:120].replace("\n", " ")


def determine_severity(matched_patterns: list[str]) -> str:
    """Determine severity based on which correction patterns matched."""
    pattern_texts = {p.lower() for p in matched_patterns}
    for high in HIGH_SEVERITY_PATTERNS:
        if high.lower() in pattern_texts:
            return "HIGH"
    for med in MEDIUM_SEVERITY_PATTERNS:
        if any(med.lower() in p for p in pattern_texts):
            return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# 3. Load and process data
# ---------------------------------------------------------------------------

def load_corrections(verbose: bool = False) -> list[CorrectionEntry]:
    """Load knowledge.json and extract self-correction entries."""
    if not KNOWLEDGE_PATH.exists():
        print(f"ERROR: {KNOWLEDGE_PATH} not found", file=sys.stderr)
        sys.exit(1)

    with open(KNOWLEDGE_PATH) as f:
        knowledge = json.load(f)

    corrections = []
    for entry in knowledge:
        content = entry.get("content", "")
        matched = []
        for pattern in CORRECTION_PATTERNS:
            if pattern.search(content):
                # Extract a clean pattern name for display
                raw = pattern.pattern
                # Strip regex artifacts for display
                clean = raw.replace(r"\b", "").replace(r"\w*", "")
                clean = re.sub(r"\[.*?\]", "", clean)
                matched.append(clean.strip())

        if not matched:
            continue

        kid = entry.get("item_id", "unknown")
        category = entry.get("category", "")
        severity = determine_severity(matched)
        anchor_kws, context_kws = extract_claim_fingerprint(content)
        krefs = extract_knowledge_refs(content)
        claim_summary = extract_claim_summary(content)

        ce = CorrectionEntry(
            knowledge_id=kid or "unknown",
            content=content,
            category=category,
            matched_patterns=matched,
            severity=severity,
            anchor_keywords=anchor_kws,
            context_keywords=context_kws,
            knowledge_refs=krefs,
            claim_summary=claim_summary,
        )
        corrections.append(ce)

        if verbose:
            print(f"  [CORRECTION] {kid} ({severity}) patterns={matched}")
            print(f"    anchors: {anchor_kws[:8]}")
            print(f"    context: {context_kws[:8]}")
            print(f"    summary: {claim_summary[:80]}")

    return corrections


def load_articles() -> list[dict]:
    """Load all articles from storage/reports/*.json and feed.json.

    Returns a list of dicts with keys: id, title, status, text, source_file.
    Deduplicates by article ID (individual report files take priority).
    """
    articles = {}

    # 1. Individual report files (higher priority)
    if REPORTS_DIR.exists():
        for fpath in sorted(REPORTS_DIR.glob("*.json")):
            if fpath.name == "feed.json":
                continue
            try:
                with open(fpath) as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                _warn_content_correction("report JSON read failed; skipping", fpath, exc)
                continue
            if not isinstance(data, dict):
                _warn_content_correction(
                    "report JSON schema invalid; skipping",
                    fpath,
                    TypeError(f"expected dict, got {type(data).__name__}"),
                )
                continue

            aid = data.get("id", fpath.stem)
            content = data.get("content", "") or ""
            description = data.get("description", "") or ""
            title = data.get("title", "") or ""
            text = f"{title} {content} {description}".strip()

            if len(text) < 30:
                continue

            articles[aid] = {
                "id": aid,
                "title": title,
                "status": data.get("status", "unknown"),
                "text": text,
                "source_file": str(fpath.relative_to(PROJECT)),
            }

    # 2. Feed entries (fill in any missing)
    if FEED_PATH.exists():
        try:
            with open(FEED_PATH) as f:
                feed = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            _warn_content_correction(
                "feed JSON read failed; skipping feed fallback",
                FEED_PATH,
                exc,
            )
            feed = []
        if not isinstance(feed, list):
            _warn_content_correction(
                "feed JSON schema invalid; skipping feed fallback",
                FEED_PATH,
                TypeError(f"expected list, got {type(feed).__name__}"),
            )
            feed = []
        for index, item in enumerate(feed):
            if not isinstance(item, dict):
                _warn_content_correction(
                    f"feed entry schema invalid at index={index}; skipping",
                    FEED_PATH,
                    TypeError(f"expected dict, got {type(item).__name__}"),
                )
                continue
            aid = item.get("id", "")
            if aid in articles:
                continue
            content = item.get("content", "") or ""
            description = item.get("description", "") or ""
            title = item.get("title", "") or ""
            text = f"{title} {content} {description}".strip()
            if len(text) < 30:
                continue
            articles[aid] = {
                "id": aid,
                "title": title,
                "status": item.get("status", "unknown"),
                "text": text,
                "source_file": "storage/reports/feed.json",
            }

    return list(articles.values())


def keyword_in_text(keyword: str, text: str, text_lower: str) -> bool:
    """Check if a keyword appears in text, with appropriate matching."""
    kw_len = len(keyword)

    # For very short terms (< 3 chars), require word boundary
    if kw_len < 3:
        return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text))

    # For knowledge/experiment refs (K36, R2, etc.), require word boundary
    if re.match(r"^[KRTJGP]\d{1,4}$", keyword):
        return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text))

    # For terms with uppercase, try case-sensitive first
    if any(c.isupper() for c in keyword):
        if keyword in text:
            return True

    # Case-insensitive fallback for longer terms
    if kw_len >= 4:
        return keyword.lower() in text_lower

    return False


def find_snippet(text: str, keyword: str, context_chars: int = 80) -> Optional[str]:
    """Find keyword in text and return surrounding context."""
    idx = text.find(keyword)
    if idx == -1:
        idx = text.lower().find(keyword.lower())
    if idx == -1:
        return None

    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(keyword) + context_chars)
    snippet = text[start:end].replace("\n", " ").strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _compute_keyword_doc_freq(
    corrections: list[CorrectionEntry],
    articles: list[dict],
) -> dict[str, float]:
    """Compute document frequency (fraction of articles containing each keyword).

    Keywords appearing in >5% of articles are too common to be anchors and
    will be demoted to context during matching.
    """
    all_keywords = set()
    for c in corrections:
        all_keywords.update(c.anchor_keywords)
        all_keywords.update(c.context_keywords)

    n_articles = len(articles)
    if n_articles == 0:
        return {}

    doc_freq: dict[str, float] = {}
    for kw in all_keywords:
        count = 0
        for a in articles:
            if keyword_in_text(kw, a["text"], a["text"].lower()):
                count += 1
        doc_freq[kw] = count / n_articles

    return doc_freq


def scan_articles(
    corrections: list[CorrectionEntry],
    articles: list[dict],
    verbose: bool = False,
) -> list[ArticleMatch]:
    """Scan articles for claims matching correction fingerprints.

    Two-phase approach:
    1. Compute document frequency for all keywords across all articles.
       Keywords appearing in >5% of articles are demoted from anchor to context.
    2. Match using corrected anchor/context classification:
       - 2+ rare anchors match, OR
       - 1 rare anchor + 2+ context match
       - Context-only matches are DISABLED (too many false positives)

    This ensures that only genuinely distinctive keywords drive matches.
    """
    # Phase 1: compute document frequency and identify common keywords
    if verbose:
        print("  Computing keyword document frequencies...")
    doc_freq = _compute_keyword_doc_freq(corrections, articles)

    ANCHOR_MAX_DF = 0.05  # keywords in >5% of articles become context

    common_anchors = {
        kw for kw, df in doc_freq.items() if df > ANCHOR_MAX_DF
    }
    if verbose and common_anchors:
        print(f"  Demoted {len(common_anchors)} common keywords to context: "
              f"{sorted(common_anchors)[:10]}")

    # Phase 2: scan each article
    matches = []
    articles_seen: dict[str, ArticleMatch] = {}

    for article in articles:
        text = article["text"]
        text_lower = text.lower()
        aid = article["id"]

        article_corrections = []
        all_matched_keywords = set()

        for correction in corrections:
            # Classify keywords with doc-freq adjustment
            effective_anchors = [
                kw for kw in correction.anchor_keywords
                if kw not in common_anchors
            ]
            effective_context = list(correction.context_keywords) + [
                kw for kw in correction.anchor_keywords
                if kw in common_anchors
            ]

            # Count matches
            matched_anchors = [
                kw for kw in effective_anchors
                if keyword_in_text(kw, text, text_lower)
            ]
            matched_context = [
                kw for kw in effective_context
                if keyword_in_text(kw, text, text_lower)
            ]

            # Decide if this correction matches this article.
            # REQUIRE at least 1 rare anchor keyword — context-only matches
            # produce too many false positives since domain terms (VIX, GARCH,
            # SPY, Sharpe) appear in nearly every research article.
            is_match = False
            if matched_anchors:
                if len(matched_anchors) >= 2:
                    is_match = True
                elif len(matched_anchors) >= 1 and len(matched_context) >= 2:
                    is_match = True

            if is_match:
                all_kws = matched_anchors + matched_context
                all_matched_keywords.update(all_kws)
                summary = correction.claim_summary or correction.content[:150]
                article_corrections.append({
                    "knowledge_id": correction.knowledge_id,
                    "severity": correction.severity,
                    "summary": summary.replace("\n", " "),
                    "matched_anchors": matched_anchors,
                    "matched_context": matched_context,
                    "anchor_count": len(matched_anchors),
                    "context_count": len(matched_context),
                    "knowledge_refs": correction.knowledge_refs,
                })

        if article_corrections and aid not in articles_seen:
            severities = [c["severity"] for c in article_corrections]
            if "HIGH" in severities:
                max_sev = "HIGH"
            elif "MEDIUM" in severities:
                max_sev = "MEDIUM"
            else:
                max_sev = "LOW"

            # Text snippets for the most specific (longest) matched keywords
            snippets = []
            for kw in sorted(all_matched_keywords, key=lambda k: -len(k))[:5]:
                s = find_snippet(text, kw)
                if s:
                    snippets.append(f"[{kw}] {s}")

            # Sort corrections by anchor count (most specific first)
            article_corrections.sort(
                key=lambda c: -(c["anchor_count"] * 10 + c["context_count"])
            )

            # Compute relevance score:
            #   - Each anchor match weighted by rarity (1/doc_freq, capped)
            #   - Severity multiplier: HIGH=3, MEDIUM=2, LOW=1
            #   - Multiple correction sources add up
            sev_mult = {"HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0}
            score = 0.0
            for cs in article_corrections:
                anchor_score = sum(
                    min(1.0 / max(doc_freq.get(kw, 0.001), 0.001), 100.0)
                    for kw in cs.get("matched_anchors", [])
                )
                ctx_score = len(cs.get("matched_context", [])) * 0.5
                score += (anchor_score + ctx_score) * sev_mult.get(
                    cs["severity"], 1.0
                )

            match = ArticleMatch(
                article_id=aid,
                title=article["title"],
                status=article["status"],
                source_file=article["source_file"],
                matched_keywords=sorted(all_matched_keywords),
                correction_sources=article_corrections[:5],
                max_severity=max_sev,
                relevance_score=round(score, 1),
                text_snippets=snippets,
            )
            matches.append(match)
            articles_seen[aid] = match

            if verbose:
                print(f"  [MATCH] {aid} ({max_sev}, score={score:.1f})"
                      f" — {article['title'][:55]}")
                total_anchors = sum(
                    c["anchor_count"] for c in article_corrections
                )
                print(f"    {total_anchors} anchor + "
                      f"{len(all_matched_keywords) - total_anchors} context")

    # Sort by relevance score (highest first), then severity as tiebreaker
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    matches.sort(key=lambda m: (
        -m.relevance_score,
        severity_order.get(m.max_severity, 3),
    ))

    return matches


# ---------------------------------------------------------------------------
# 4. Report generation
# ---------------------------------------------------------------------------

def generate_report(
    corrections: list[CorrectionEntry],
    matches: list[ArticleMatch],
    n_knowledge: int,
    n_articles: int,
) -> dict:
    """Generate a structured JSON report."""
    return {
        "scan_metadata": {
            "knowledge_entries_scanned": n_knowledge,
            "corrections_found": len(corrections),
            "articles_scanned": n_articles,
            "articles_flagged": len(matches),
            "severity_breakdown": {
                "HIGH": sum(1 for m in matches if m.max_severity == "HIGH"),
                "MEDIUM": sum(1 for m in matches if m.max_severity == "MEDIUM"),
                "LOW": sum(1 for m in matches if m.max_severity == "LOW"),
            },
        },
        "corrections_summary": [
            {
                "knowledge_id": c.knowledge_id,
                "severity": c.severity,
                "patterns": c.matched_patterns,
                "anchor_keywords": c.anchor_keywords,
                "context_keywords": c.context_keywords,
                "knowledge_refs": c.knowledge_refs,
                "claim_summary": c.claim_summary,
            }
            for c in corrections
        ],
        "flagged_articles": [asdict(m) for m in matches],
    }


def print_summary(
    corrections: list[CorrectionEntry],
    matches: list[ArticleMatch],
    n_knowledge: int,
    n_articles: int,
) -> None:
    """Print a human-readable summary to stdout."""
    print("\n" + "=" * 70)
    print("Content Correction Scanner Report")
    print("=" * 70)

    print(f"\nKnowledge entries scanned: {n_knowledge}")
    print(f"Self-corrections found:   {len(corrections)}")
    high = sum(1 for c in corrections if c.severity == "HIGH")
    med = sum(1 for c in corrections if c.severity == "MEDIUM")
    low = sum(1 for c in corrections if c.severity == "LOW")
    print(f"  HIGH: {high}  MEDIUM: {med}  LOW: {low}")

    print(f"\nArticles scanned:  {n_articles}")
    print(f"Articles flagged:  {len(matches)}")
    fh = sum(1 for m in matches if m.max_severity == "HIGH")
    fm = sum(1 for m in matches if m.max_severity == "MEDIUM")
    fl = sum(1 for m in matches if m.max_severity == "LOW")
    print(f"  HIGH: {fh}  MEDIUM: {fm}  LOW: {fl}")

    if not matches:
        print("\nNo articles flagged. All content appears consistent.")
        return

    print("\n" + "-" * 70)
    print("FLAGGED ARTICLES (sorted by relevance score)")
    print("-" * 70)

    for i, m in enumerate(matches, 1):
        print(f"\n[{i}] [{m.max_severity}] (score={m.relevance_score}) "
              f"{m.article_id}")
        print(f"    Title:  {m.title[:70]}")
        print(f"    Status: {m.status}")
        print(f"    File:   {m.source_file}")
        print(f"    Matched keywords ({len(m.matched_keywords)}): "
              f"{', '.join(m.matched_keywords[:10])}")
        if len(m.matched_keywords) > 10:
            print(f"      ... and {len(m.matched_keywords) - 10} more")
        print(f"    Correction sources:")
        for cs in m.correction_sources[:3]:
            refs = ", ".join(cs.get("knowledge_refs", []))
            ref_str = f" (refs: {refs})" if refs else ""
            anchors = cs.get("matched_anchors", [])
            print(f"      - [{cs['severity']}] {cs['knowledge_id']}{ref_str}")
            print(f"        Anchors: {anchors[:5]}")
            print(f"        {cs['summary'][:100]}")
        if m.text_snippets:
            print(f"    Snippets:")
            for s in m.text_snippets[:3]:
                print(f"      {s[:140]}")

    print("\n" + "=" * 70)
    print(f"Total: {len(matches)} articles need review")
    if fh > 0:
        print(f"  {fh} HIGH severity — likely contain reversed/disproved claims")
    if fm > 0:
        print(f"  {fm} MEDIUM severity — may contain outdated methodology/results")
    if fl > 0:
        print(f"  {fl} LOW severity — minor or tangential matches")
    print("=" * 70)


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan published articles for claims contradicting "
                    "current knowledge (K321)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print detailed progress during scan",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT.relative_to(PROJECT)})",
    )
    parser.add_argument(
        "--min-severity", type=str, default=None,
        choices=["high", "medium", "low"],
        help="Only report articles at or above this severity",
    )
    parser.add_argument(
        "--published-only", action="store_true",
        help="Only scan articles with status=published",
    )
    parser.add_argument(
        "--top", type=int, default=None,
        help="Only show top N articles by relevance score",
    )
    parser.add_argument(
        "--json-only", action="store_true",
        help="Output only JSON (suppress human-readable summary)",
    )
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT

    # Step 1: Load corrections from knowledge.json
    if args.verbose:
        print("Loading knowledge entries...")
    with open(KNOWLEDGE_PATH) as f:
        n_knowledge = len(json.load(f))

    corrections = load_corrections(verbose=args.verbose)
    if not corrections:
        print("No self-correction entries found in knowledge.json")
        sys.exit(0)

    if args.verbose:
        print(f"\nFound {len(corrections)} correction entries")

    # Step 2: Load articles
    if args.verbose:
        print("\nLoading articles...")
    articles = load_articles()
    n_articles = len(articles)
    if args.published_only:
        articles = [a for a in articles if a["status"] == "published"]
        if args.verbose:
            print(f"  Filtered to {len(articles)} published articles")

    if args.verbose:
        print(f"Loaded {len(articles)} articles to scan")

    # Step 3: Scan for outdated claims
    if args.verbose:
        print("\nScanning articles for outdated claims...")
    matches = scan_articles(corrections, articles, verbose=args.verbose)

    # Step 4: Filter by severity and top-N
    if args.min_severity:
        severity_order = {"high": 0, "medium": 1, "low": 2}
        threshold = severity_order[args.min_severity]
        matches = [
            m for m in matches
            if severity_order.get(m.max_severity.lower(), 3) <= threshold
        ]
    if args.top:
        matches = matches[:args.top]

    # Step 5: Output
    report = generate_report(corrections, matches, n_knowledge, n_articles)

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    if not args.json_only:
        print_summary(corrections, matches, n_knowledge, n_articles)
        print(f"\nFull report saved to: {output_path.relative_to(PROJECT)}")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
