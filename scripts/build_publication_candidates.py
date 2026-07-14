#!/usr/bin/env python3
"""
Build publication candidate list: K experiments that have PASS/important results
but no feed article covering them yet.

Output: storage/publication_candidates.json

Logic:
1. Scan knowledge.json for all experiments (experiment_id = K_NN)
2. For each K, find feed articles covering it via:
   - tags array containing K_NN
   - title containing K_NN
   - content (description) mentioning K_NN
3. Score priority based on verdict keywords:
   - PASS / Harvey / significant / robust → +3
   - universal / cross-market / three-market → +3
   - mechanism / methodology warning → +2
   - NULL decisive / paradigm → +2
   - sample too small / inconclusive → -1
4. Output sorted candidates with coverage status.
"""
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
KNOWLEDGE_PATH = ROOT / "storage/memory/knowledge.json"
FEED_PATH = ROOT / "storage/reports/feed.json"
OUTPUT_PATH = ROOT / "storage/publication_candidates.json"
READER_METRICS_LATEST_PATH = ROOT / "storage/analytics/latest.json"
NEXT_TASKS_PATH = ROOT / "storage/next_tasks.json"

sys.path.insert(0, str(ROOT / "src"))

from volpred.canonical_write import guard_canonical_write
from volpred.publication_gate import publication_block_reason
from volpred.topic_clusters import classify_topic_cluster, cluster_gate_status


def _load_reader_signal_map() -> dict[str, dict]:
    """slug -> reader engagement row, from scripts/pull_reader_metrics.py output.

    Reader-metrics feedback loop (platform_ops_reader_metrics_feedback_loop_c9,
    2026-07-05): a SOFT signal only. It attaches real, already-published reader
    engagement data (impressions / read-completion proxy / reactions) onto
    candidates whose K is already covered by one or more feed articles, so
    future topic selection can see "which covered topics people actually
    finished reading" — it does NOT change `score`/`adjusted_score` or the
    sort key below, and it never affects `uncovered` candidates (no article
    exists yet, so there is nothing to look up).

    Fail-open: file missing/corrupt/stale -> empty map, candidates simply lack
    the `reader_signal` field. Never fabricates a number.
    """
    if not READER_METRICS_LATEST_PATH.exists():
        return {}
    try:
        data = json.loads(READER_METRICS_LATEST_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: reader metrics latest.json unreadable, skipping reader_signal: {exc}", file=sys.stderr)
        return {}
    rows = data.get("top_articles") or []
    return {row.get("slug"): row for row in rows if isinstance(row, dict) and row.get("slug")}


# Reader-preference bonus is intentionally small: a tie-breaker nudge, never a
# gate and never large enough to dominate the content-keyword score (max 10).
PREFERENCE_BONUS_CAP = 2


def _load_preference_signals() -> tuple[set[str], bool]:
    """(high_engagement_tags, research_type_is_higher) from reader_preferences.json.

    Source: scripts/analyze_reader_preferences.py output. Only *qualified*
    conclusions (buckets that passed the >=10 articles AND >=30 impressions
    sample gate) are ever present in that file, so an insufficient-sample bucket
    contributes NOTHING here by construction — "樣本不足 → 零影響" is enforced
    upstream, not re-checked. File missing/corrupt/empty -> ({}, False) -> zero
    bonus, i.e. identical candidate output to before this feedback loop existed.

    Path is derived from the module-level ROOT at call time (not a frozen
    constant) so tests that monkeypatch ROOT get a clean, file-free environment
    without also having to know this path.
    """
    prefs_path = ROOT / "storage/analytics/reader_preferences.json"
    if not prefs_path.exists():
        return set(), False
    try:
        data = json.loads(prefs_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: reader_preferences.json unreadable, skipping preference bonus: {exc}", file=sys.stderr)
        return set(), False
    high_tags: set[str] = set()
    research_higher = False
    for c in data.get("qualified_conclusions") or []:
        if not isinstance(c, dict):
            continue
        if c.get("dimension") == "tag" and c.get("higher_bucket"):
            high_tags.add(str(c["higher_bucket"]))
        if c.get("dimension") == "research_vs_narrative" and c.get("higher_bucket") == "research":
            research_higher = True
    return high_tags, research_higher


def _preference_bonus(
    tags: list, is_research_candidate: bool, high_tags: set[str], research_higher: bool
) -> tuple[int, list[str]]:
    """Additive, capped tie-breaker bonus. Only matches dimensions knowable at
    SELECTION time (the candidate's tags + that it is a research K); style/format
    dimensions like chart/table count are writing-time decisions, not properties
    of the K, so they never enter the candidate score."""
    bonus = 0
    reasons: list[str] = []
    for t in tags or []:
        if str(t) in high_tags:
            bonus += 1
            reasons.append(f"reader-pref: tag『{t}』higher reader engagement")
    if research_higher and is_research_candidate:
        bonus += 1
        reasons.append("reader-pref: research-type higher reader engagement")
    return min(bonus, PREFERENCE_BONUS_CAP), reasons


def extract_k_id(experiment_id: str) -> str | None:
    """Normalize K1145, k1145, K1145b → K1145."""
    if not experiment_id:
        return None
    m = re.match(r"[Kk](\d+)", experiment_id)
    if not m:
        return None
    return f"K{m.group(1)}"


def derive_title(entry: dict) -> str:
    """Title fallback: knowledge entries 沒 title 時，從 content 第一句取。

    2026-05-29: K1318/K1322/K1378/K1382 等 entries title=null 但 content 開頭就有
    完整 K-id 描述（e.g. 'K1318: HAR-RV 5-min Pilot — SPY & 0050.TW ...'）。
    沒有 fallback 時 refill `_has_publishable_title` belt 會擋掉全部 → pool 永空。
    截斷規則：第一個句號（. / 。）前的 first line，cap 160 chars。
    """
    explicit = str(entry.get("title") or "").strip()
    if explicit:
        return explicit
    content = str(entry.get("content") or "").strip()
    if not content:
        return ""
    first_line = content.split("\n", 1)[0].strip()
    for sep in ("。", ". "):
        cut = first_line.find(sep)
        if cut > 10:  # avoid cutting at 'K1318.' prefix
            first_line = first_line[:cut]
            break
    return first_line[:160].strip()


def score_priority(entry: dict) -> tuple[int, list[str]]:
    """Score 0-10 based on content keywords. Return (score, reasons)."""
    content = (entry.get("content", "") + " " + entry.get("title", "")).lower()
    score = 0
    reasons = []
    # Positive signals
    if any(k in content for k in ["pass", "harvey"]) and "fail" not in content[:200]:
        score += 3
        reasons.append("PASS/Harvey-significant")
    if any(k in content for k in ["universal", "cross-market", "three-market", "三市場"]):
        score += 3
        reasons.append("cross-market/universal")
    if any(k in content for k in ["mechanism", "methodology", "教訓", "warning"]):
        score += 2
        reasons.append("methodology/mechanism lesson")
    if any(k in content for k in ["decisive", "決定性", "paradigm", "推翻"]):
        score += 2
        reasons.append("paradigm/decisive null")
    if any(k in content for k in ["bootstrap", "placebo", "robust"]):
        score += 1
        reasons.append("robust inference")
    if any(k in content for k in ["5 layer", "五層", "5 robustness"]):
        score += 2
        reasons.append("5-layer robustness")
    # Negative signals
    if any(k in content for k in ["inconclusive", "data 不足", "sample too small"]):
        score -= 2
        reasons.append("inconclusive (data limit)")
    if any(k in content for k in ["mixed", "scenario stable"]):
        score -= 1
        reasons.append("mixed/non-novel")
    return max(0, min(10, score)), reasons


def _k_id_family(kid: str) -> str:
    """Strip trailing letter suffix to get K-family base (K1106b → K1106, K852b → K852).

    K-experiment sub-variants (K1106 vs K1106b vs K1106c) cover the same
    underlying study. For dedup purposes, treat them as the same family.
    """
    # Strip trailing letters case-insensitively, then uppercase for comparison.
    return re.sub(r"[a-zA-Z]+$", "", kid, count=1).upper() if re.match(r"^[Kk]\d", kid) else kid.upper()


def k_covered_by_article(k_id: str, article: dict) -> bool:
    """Check whether article covers this K via tags/title/content/experiment_refs.

    Matches K-family (K1106 ↔ K1106b ↔ K1106c) via _k_id_family().
    """
    k_lower = k_id.lower()
    k_family = _k_id_family(k_id)
    # 1. tags — exact + family match
    tags = [str(t).lower() for t in article.get("tags", [])]
    if k_lower in tags:
        return True
    for t in tags:
        if t.upper().startswith(k_family) and _k_id_family(t) == k_family:
            return True
    # 2. details.experiment_refs (canonical structured field per feed-publisher
    # SKILL.md K-id stripping; titles get K-id stripped to experiment_refs).
    # 2026-05-11 K869 incident: mile_4ec7b75e covered K869 but build script
    # only checked tags/title/content, missed structured refs → K869 stayed
    # falsely uncovered for 6 days.
    # 2026-05-11 K1106 follow-up: family-match needed since refs may use
    # K1106b sub-variant while candidate is K1106 base.
    details = article.get("details") or {}
    if isinstance(details, dict):
        refs = details.get("experiment_refs") or []
        if isinstance(refs, list):
            for r in refs:
                if _k_id_family(str(r)) == k_family:
                    return True
    # 3. title
    title = str(article.get("title", "")).lower()
    if k_lower in title:
        return True
    # 4. description + content body
    content = str(article.get("description", "") + article.get("content", "")).lower()
    # Match K1145 or k1145 but not K114 inside K1145
    pattern = rf"\b{re.escape(k_lower)}\b"
    if re.search(pattern, content):
        return True
    return False


_ARTICLE_TASK_ID_RE = re.compile(
    r"^(?P<kid>K\d{2,5}[A-Za-z0-9_]*)_article_(?P<audience>general|research)(?:_|$)",
    re.IGNORECASE,
)


def _load_next_tasks() -> list[dict]:
    if not NEXT_TASKS_PATH.exists():
        return []
    try:
        data = json.loads(NEXT_TASKS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: next_tasks.json unreadable, skipping task coverage: {exc}", file=sys.stderr)
        return []
    return data if isinstance(data, list) else []


def _succeeded_article_task_coverage(tasks: list[dict]) -> dict[str, list[dict]]:
    """K-family -> synthetic coverage rows from completed article tasks.

    2026-07-06 C8 follow-up: publication_candidates could keep treating a K as
    uncovered/missing-general even after the article task had succeeded, when
    feed metadata lagged or the article was later reclassified. The task receipt
    is not a content source, but it is a release-layer coverage signal that must
    stop refill treadmill loops.
    """
    coverage: dict[str, list[dict]] = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("task_type") or "") != "daily_article":
            continue
        if str(task.get("status") or "").lower() != "succeeded":
            continue
        task_id = str(task.get("id") or task.get("task_id") or "")
        match = _ARTICLE_TASK_ID_RE.match(task_id)
        if not match:
            continue
        kid = match.group("kid").upper()
        audience = match.group("audience").lower()
        coverage.setdefault(_k_id_family(kid), []).append({
            "id": task_id,
            "title": str(task.get("title") or ""),
            "status": "succeeded_task",
            "audience": audience,
            "source": "next_tasks_succeeded_daily_article",
        })
    return coverage


def _feed_experiment_ref_families(feed: list[dict]) -> set[str]:
    """K-families that have structured feed coverage via details.experiment_refs."""
    families: set[str] = set()
    for article in feed:
        if not isinstance(article, dict):
            continue
        details = article.get("details") or {}
        if not isinstance(details, dict):
            continue
        refs = details.get("experiment_refs") or []
        if not isinstance(refs, list):
            continue
        status = str(article.get("status") or "").lower()
        if status in {"unpublished", "retracted"}:
            continue
        for ref in refs:
            ref_s = str(ref or "").strip()
            if ref_s:
                families.add(_k_id_family(ref_s))
    return families


def _extract_overturned_map(knowledge: list) -> dict[str, list[str]]:
    """Map of overturned K-id → sorted list of overturning K-ids.

    Scans entries whose title contains "OVERTURNED" (the canonical overturn
    marker) and extracts referenced K-ids from their content (regex K\\d+).
    Self-reference is excluded.

    2026-06-06 K683 incident root cause: build script previously emitted
    overturned K's into missing_general/missing_research top5, where
    publishing agents would reject them ("invalid stale K, already
    overturned"), wasting hourly fire slots. Pre-filter at build time.

    Note: only catches *explicit* K-ref linkages. Topic-level relationships
    (e.g. K683's "percentile" claim overturned by K686 which only names
    K679 explicitly) are not caught — those still slip through and require
    main-thread judgment + per-task blocked-deprecated marking.
    """
    overturned_map: dict[str, set[str]] = {}
    k_ref_re = re.compile(r"K\d{3,4}")
    for entry in knowledge:
        title = str(entry.get("title") or "")
        if "OVERTURNED" not in title.upper():
            continue
        own_kid = extract_k_id(entry.get("experiment_id", "") or entry.get("id", ""))
        if not own_kid:
            continue
        content = str(entry.get("content") or "")
        for ref in k_ref_re.findall(content):
            if ref != own_kid:
                overturned_map.setdefault(ref, set()).add(own_kid)
    return {kid: sorted(refs) for kid, refs in overturned_map.items()}


def _is_invalidated_artifact(entry: dict) -> bool:
    """True if the latest knowledge entry says the artifact is not promotable."""
    haystacks = [
        str(entry.get("title") or ""),
        str(entry.get("summary") or ""),
        str(entry.get("content") or ""),
        str(entry.get("codex_review") or ""),
        " ".join(str(t) for t in (entry.get("tags") or [])),
    ]
    merged = "\n".join(haystacks).lower()
    fail_markers = (
        "codex review fail",
        "formal conclusion 不可採信",
        "formal conclusion not trustworthy",
        "artifact 作廢",
        "invalidated artifact",
        "設計錯誤作廢",
    )
    return any(marker in merged for marker in fail_markers)


def _write_output_atomically(output: dict) -> None:
    """Write via tmp + os.replace so a killed run can never leave truncated JSON.

    refill_task_pool spawns this script under a hard timeout, and the timeout
    kills `uv`, orphaning the python child mid-write (see docs/error_log.md
    2026-07-10). A SIGKILL landing between `write_text`'s open-truncate and its
    final flush would otherwise corrupt the tracked storage/publication_candidates.json.
    os.replace is atomic on the same filesystem, so readers see either the old
    complete file or the new complete file, never a half-written one.
    """
    guard_canonical_write(OUTPUT_PATH)
    payload = json.dumps(output, ensure_ascii=False, indent=2)
    tmp_path = OUTPUT_PATH.with_name(OUTPUT_PATH.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, OUTPUT_PATH)


def main():
    # Fail before the ~30s scan rather than at the write site below.
    guard_canonical_write(OUTPUT_PATH)
    if not KNOWLEDGE_PATH.exists():
        print(f"ERROR: {KNOWLEDGE_PATH} not found", file=sys.stderr)
        sys.exit(1)
    if not FEED_PATH.exists():
        print(f"ERROR: {FEED_PATH} not found", file=sys.stderr)
        sys.exit(1)

    knowledge = json.loads(KNOWLEDGE_PATH.read_text())
    feed = json.loads(FEED_PATH.read_text())
    next_tasks = _load_next_tasks()
    task_coverage_by_family = _succeeded_article_task_coverage(next_tasks)
    release_layer_covered_families = _feed_experiment_ref_families(feed) | set(task_coverage_by_family)
    overturned_map = _extract_overturned_map(knowledge)
    reader_signal_map = _load_reader_signal_map()
    pref_high_tags, pref_research_higher = _load_preference_signals()

    # Deduplicate knowledge by experiment_id (keep latest)
    by_k: dict[str, dict] = {}
    for entry in knowledge:
        k_id = extract_k_id(entry.get("experiment_id", ""))
        if not k_id:
            continue
        existing = by_k.get(k_id)
        if existing is None or entry.get("updated_at", "") > existing.get("updated_at", ""):
            by_k[k_id] = entry

    # For each K, check feed coverage
    incomplete_research_count = 0
    publication_blocked: list[dict] = []
    candidates = []
    for k_id, entry in by_k.items():
        # 2026-05-09 K728/K924 incidents: K experiments without *_results.json are
        # incomplete research and must not enter article candidate pool.
        k_lower = k_id.lower()
        exp_dir = ROOT / "experiments" / k_lower
        has_results = bool(
            (exp_dir / f"{k_lower}_results.json").exists()
            or (exp_dir.exists() and any(exp_dir.glob("*_results.json")))
        )
        if not has_results:
            incomplete_research_count += 1
            continue
        if _is_invalidated_artifact(entry):
            continue
        # A reviewer can clear an experiment as research while withholding it
        # from publication (K1684: CONDITIONAL_PASS, "E2 required before
        # publication/paper routing"). Such a K must never surface as an
        # article candidate — see volpred.publication_gate.
        block_reason = publication_block_reason(entry)
        if block_reason:
            publication_blocked.append({
                "k_id": k_id,
                "verdict": entry.get("verdict"),
                "reason": block_reason,
            })
            continue
        covering_articles = []
        for article in feed:
            if k_covered_by_article(k_id, article):
                covering_articles.append({
                    "id": article.get("id"),
                    "title": article.get("title", ""),
                    "status": article.get("status"),
                    "audience": article.get("audience"),
                })
        covering_articles.extend(task_coverage_by_family.get(_k_id_family(k_id), []))
        score, reasons = score_priority(entry)
        cluster = classify_topic_cluster(
            entry.get("title", ""),
            entry.get("tags") or [],
            entry.get("content", ""),
        )
        cluster_gate = cluster_gate_status(cluster)
        adjusted_score = score
        if cluster and cluster_gate["count"] > cluster_gate["cap"]:
            adjusted_score = max(0, int(score * 0.5))
            reasons = reasons + [f"cluster cooldown penalty ({cluster} 30d={cluster_gate['count']}>{cluster_gate['cap']})"]
        # Reader-preference bonus (additive tie-breaker, NOT a gate). Sourced from
        # qualified conclusions in reader_preferences.json; insufficient-sample
        # buckets never reach here, so small/absent reader data => zero bonus =>
        # unchanged ranking. Capped at PREFERENCE_BONUS_CAP.
        is_research_candidate = bool(
            (entry.get("experiment_id"))
            or any(re.match(r"[Kk]\d", str(t)) for t in (entry.get("tags") or []))
        )
        preference_bonus, preference_bonus_reasons = _preference_bonus(
            entry.get("tags") or [], is_research_candidate, pref_high_tags, pref_research_higher
        )
        if preference_bonus:
            adjusted_score += preference_bonus
            reasons = reasons + preference_bonus_reasons
        # Soft reader-engagement signal (metadata only — see
        # _load_reader_signal_map docstring; never affects score/adjusted_score
        # or the sort key). Matched via covering-article slug against
        # storage/analytics/latest.json (scripts/pull_reader_metrics.py output).
        reader_signal = None
        matched_rows = [
            reader_signal_map[a["id"]] for a in covering_articles
            if a.get("id") in reader_signal_map
        ]
        if matched_rows:
            completions = [
                r.get("read_completion_rate_proxy") for r in matched_rows
                if r.get("read_completion_rate_proxy") is not None
            ]
            reader_signal = {
                "matched_slugs": [r.get("slug") for r in matched_rows],
                "impressions_total": sum(r.get("impressions") or 0 for r in matched_rows),
                "avg_read_completion_rate_proxy": (
                    round(sum(completions) / len(completions), 4) if completions else None
                ),
                "read_time_is_proxy": True,
                "source": "storage/analytics/latest.json",
            }
        candidates.append({
            "k_id": k_id,
            "title": derive_title(entry),
            "score": adjusted_score,
            "base_score": score,
            "reasons": reasons,
            "verdict_preview": entry.get("content", "")[:300],
            "covered_by": covering_articles,
            "uncovered": len(covering_articles) == 0,
            "topic_cluster": cluster,
            "topic_cluster_30d": {
                "count": cluster_gate["count"],
                "cap": cluster_gate["cap"],
                "ratio": round(cluster_gate["ratio"], 4),
            },
            # Treat audience=None/empty as 'general' (pre-2026-04-14 articles
            # had no audience metadata; platform default-tone was general).
            # 2026-05-11 K665/K630/K622 incidents: dropping audience=null from
            # this set caused refill_task_pool to mistakenly queue articles
            # for K-experiments that already had audience=null legacy coverage.
            "audiences_covered": sorted({
                (a.get("audience") or "general")
                for a in covering_articles
            }),
            "updated_at": entry.get("updated_at", ""),
            "tags": entry.get("tags", []),
            "overturned_by": overturned_map.get(k_id, []),
            "reader_signal": reader_signal,
            "preference_bonus": preference_bonus,
            "preference_bonus_reasons": preference_bonus_reasons,
            "release_layer_covered": _k_id_family(k_id) in release_layer_covered_families,
        })

    # Sort: uncovered first, then by score desc, then by recency desc
    candidates.sort(
        key=lambda c: (
            not c["uncovered"],
            -c["score"],
            c.get("updated_at", ""),
        ),
        reverse=False,
    )

    # Summary
    total = len(candidates)
    uncovered = sum(1 for c in candidates if c["uncovered"])
    high_uncovered = [c for c in candidates if c["uncovered"] and c["score"] >= 5]

    # 2026-05-09 K979 incident: missing_audience 須 cluster by topic family，非僅 K-id
    # K979 was tagged missing_general because no article mentioned "K979", but K447's
    # mile_1b2ad1f8 (general SKEW article from 2026-05-05) covered the same topic family.
    # Fix: compute tag-overlap between candidate K and existing articles in target audience;
    # if ≥2 domain tags overlap, mark as topic_family_collision and exclude from missing list.
    GENERIC_TAGS = {
        "一般讀者", "研究", "general", "research", "深度研究",
        "波動率預測", "vol-prediction", "volatility", "金融研究",
    }

    # 2026-05-09 K979 incident fix: cross-language synonyms were missed by pure
    # lowercase+hyphen normalisation (tail-risk ↔ 尾端風險, vix-sufficiency ↔ VIX充分性).
    CROSS_LANG_SYNONYMS: dict[str, str] = {
        "尾端風險": "tail-risk", "尾部風險": "tail-risk",
        "tail-risk": "tail-risk", "tailrisk": "tail-risk",
        "vix充分性": "vix-sufficiency", "vix-充分性": "vix-sufficiency",
        "vix-sufficiency": "vix-sufficiency",
        "波動率模型": "garch", "garch模型": "garch", "波動率預測模型": "garch",
        "動能": "momentum", "動量": "momentum",
        "類股輪動": "sector-rotation", "板塊輪動": "sector-rotation",
        "sector-rotation": "sector-rotation",
        "風險平價": "risk-parity", "risk-parity": "risk-parity",
        "機制轉換": "regime-switching", "體制轉換": "regime-switching",
        "regime-switching": "regime-switching",
        "跨資產": "cross-asset", "cross-asset": "cross-asset",
        "避險": "hedging", "對沖": "hedging",
        "槓桿": "leverage",
        "最大回撤": "max-drawdown", "最大跌幅": "max-drawdown", "mdd": "max-drawdown",
        "期權": "options", "選擇權": "options",
        "隱含波動率": "implied-volatility", "implied-volatility": "implied-volatility",
        "加密貨幣": "crypto", "比特幣": "bitcoin",
        "台股": "taiwan", "台灣市場": "taiwan",
        "國際市場": "international", "跨國": "international",
    }

    def _norm_tag(t: str) -> str:
        normed = t.strip().lower().replace("_", "-").replace(" ", "-")
        return CROSS_LANG_SYNONYMS.get(normed, normed)

    def _domain_tags(tags: list) -> set[str]:
        return {_norm_tag(t) for t in (tags or []) if t and t not in GENERIC_TAGS}

    def _topic_family_collision(cand_tags: set[str], audience: str) -> list[dict]:
        """Find feed articles in target audience sharing ≥2 domain tags with candidate K."""
        if not cand_tags:
            return []
        hits = []
        for art in feed:
            if not isinstance(art, dict):
                continue
            if (art.get("audience") or (art.get("details") or {}).get("audience")) != audience:
                continue
            art_tags = _domain_tags(art.get("tags") or [])
            overlap = cand_tags & art_tags
            if len(overlap) >= 2:
                hits.append({
                    "id": art.get("id"),
                    "title": art.get("title", "")[:80],
                    "shared_tags": sorted(overlap),
                })
        return hits

    # Annotate each candidate with topic_family_collision per audience
    for c in candidates:
        cand_tags = _domain_tags(c.get("tags") or [])
        c["topic_family_collisions"] = {
            "general": _topic_family_collision(cand_tags, "general"),
            "research": _topic_family_collision(cand_tags, "research"),
        }

    # 2026-06-06: also skip candidates whose own title contains OVERTURNED/
    # 撤稿/推翻 — they are research-history artifacts, not promotable signal.
    # Mirrors refill_task_pool.py::_is_retracted_or_overturned_candidate.
    _self_overturned_needles = ("OVERTURNED", "RETRACTED", "撤稿", "推翻")
    def _self_overturned(c: dict) -> bool:
        t = str(c.get("title") or "").upper()
        return any(n in t for n in _self_overturned_needles)

    missing_general = [
        c for c in candidates
        if c["covered_by"]
        and "general" not in c["audiences_covered"]
        and c["score"] >= 4
        and not c["release_layer_covered"]
        and not c["topic_family_collisions"]["general"]  # exclude topic-family clashes
        and not c["overturned_by"]  # 2026-06-06: skip explicitly-overturned K's
        and not _self_overturned(c)
    ]
    missing_research = [
        c for c in candidates
        if c["covered_by"]
        and "research" not in c["audiences_covered"]
        and c["score"] >= 4
        and not c["topic_family_collisions"]["research"]
        and not c["overturned_by"]
        and not _self_overturned(c)
    ]

    def _audience_gap_row(candidate: dict, target_audience: str) -> dict:
        return {
            "k_id": candidate["k_id"],
            "score": candidate["score"],
            "title": candidate["title"][:120],
            "missing_target_audience": target_audience,
            "coverage_status": "covered_for_other_audiences",
            "already_covered_for": candidate["audiences_covered"],
        }

    candidates_with_reader_signal = sum(1 for c in candidates if c.get("reader_signal"))
    candidates_with_preference_bonus = sum(1 for c in candidates if c.get("preference_bonus"))
    release_layer_covered_count = sum(1 for c in candidates if c.get("release_layer_covered"))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": {
            "missing_general_top5": (
                "Covered by at least one published article, but still missing "
                "a general-audience article; excludes K's already covered at "
                "the release layer by structured feed experiment_refs or a "
                "succeeded daily_article task."
            ),
            "missing_research_top5": (
                "Covered by at least one published article, but still missing "
                "a research-audience article."
            ),
            "reader_signal": (
                "Soft metadata only (per-candidate `reader_signal`), sourced from "
                "storage/analytics/latest.json (scripts/pull_reader_metrics.py). "
                "Does NOT affect score/adjusted_score or candidate sort order — "
                "only present when the K is already covered by an article with "
                "measured reader activity. Absent (null) reader_signal_map or no "
                "matching activity -> reader_signal stays null, never fabricated."
            ),
            "preference_bonus": (
                "Additive tie-breaker (0..2) folded into score, sourced from "
                "qualified conclusions in storage/analytics/reader_preferences.json "
                "(scripts/analyze_reader_preferences.py). Matches only "
                "selection-time signals (candidate tags in a high-engagement tag "
                "bucket; research-type when research reads higher). Insufficient-"
                "sample buckets are excluded upstream, so small/absent reader data "
                "=> 0 bonus => identical ranking. Never a gate; never a penalty."
            ),
            "release_layer_covered": (
                "True when storage/reports/feed.json carries structured "
                "details.experiment_refs for the K-family, or storage/next_tasks.json "
                "has a succeeded *_article_general/research daily_article task. "
                "These K's are excluded from top_10_uncovered and missing_general_top5 "
                "to avoid refill treadmill loops."
            ),
        },
        "publication_blocked": publication_blocked,
        "summary": {
            "total_k": total,
            "incomplete_research_filtered": incomplete_research_count,
            "publication_blocked": len(publication_blocked),
            "uncovered": uncovered,
            "high_priority_uncovered": len(high_uncovered),
            "missing_general_audience": len(missing_general),
            "missing_research_audience": len(missing_research),
            "candidates_with_reader_signal": candidates_with_reader_signal,
            "candidates_with_preference_bonus": candidates_with_preference_bonus,
            "release_layer_covered": release_layer_covered_count,
        },
        "overturned_kids": sorted(overturned_map.keys()),
        "top_10_uncovered": [
            {"k_id": c["k_id"], "score": c["score"], "title": c["title"][:120]}
            for c in candidates[:10]
            if c["uncovered"] and not c["overturned_by"] and not c["release_layer_covered"]
        ],
        "missing_general_top5": [
            _audience_gap_row(c, "general")
            for c in missing_general[:5]
        ],
        "missing_research_top5": [
            _audience_gap_row(c, "research")
            for c in missing_research[:5]
        ],
        # Clearer aliases for future readers; keep legacy keys above for compatibility.
        "general_audience_gap_top5": [
            _audience_gap_row(c, "general")
            for c in missing_general[:5]
        ],
        "research_audience_gap_top5": [
            _audience_gap_row(c, "research")
            for c in missing_research[:5]
        ],
        "candidates": candidates,
    }

    guard_canonical_write(OUTPUT_PATH)
    _write_output_atomically(output)

    # Print concise summary
    print(f"Scanned {total} K experiments ({incomplete_research_count} filtered: no results JSON).")
    if publication_blocked:
        print(f"  Publication-blocked by reviewer (excluded from all pools): {len(publication_blocked)}")
        for row in publication_blocked:
            print(f"    - {row['k_id']} [{row['verdict']}] {row['reason'][:110]}")
    print(f"  Uncovered: {uncovered}")
    print(f"  High-priority uncovered (score≥5): {len(high_uncovered)}")
    print(f"  Covered but missing general audience: {len(missing_general)}")
    print(f"  Covered but missing research audience: {len(missing_research)}")
    print(f"  Candidates with reader_signal (soft engagement metadata): {candidates_with_reader_signal}")
    print(f"  Explicitly-overturned K's excluded from missing lists: {len(overturned_map)} ({sorted(overturned_map.keys())})")
    print()
    print("Top 5 uncovered candidates:")
    for c in [c for c in candidates if c["uncovered"]][:5]:
        print(f"  [{c['score']}] {c['k_id']}: {c['title'][:100]}")
    print()
    print(f"Full output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
