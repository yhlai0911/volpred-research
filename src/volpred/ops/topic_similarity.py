"""Semantic topic similarity — measure how alike two topics are by MEANING, not
keywords.

Background (boss directive 2026-06-29, email-12132/12139): the platform's
concentration / dedup / staleness signals were all keyword-based, which produces
false positives — 「波動率對風險值的影響」 and 「波動率對選擇權定價的影響」 both
keyword-classify as a "vix"/"波動率" cluster, yet they are two DIFFERENT topics
and must NOT count as over-concentration. The boss's principle: *similarity must
be SEMANTIC over the whole topic, not keyword count.*

This module is the foundation for moving concentration/dedup/staleness to
semantic similarity. It reuses the existing embedding pipeline
(`scripts/build_knowledge_index.py`, OpenAI text-embedding-3-small / Gemini,
768-dim) and adds:

- `cosine` — pure cosine similarity (no deps).
- `embed_with_cache` — sha256-keyed disk cache so repeated texts never re-hit the
  PAID embedding API (cost control).
- `topic_concentration` — fraction of recent titles that are a SEMANTIC rehash of
  another recent title (the boss's real concern), with a cluster breakdown.
- `near_duplicates` — semantic near-dups of a query among candidates (for a
  future dedup gate).

Design constraints:
- Every higher-level function takes an injectable `embedder` (default = the real
  one) so tests run offline and deterministically.
- FAIL-OPEN: if embedding is unavailable (no API key / network down), functions
  return a `{"status": "semantic_unavailable"}` shape and never raise — the
  content pipeline must never break because a PAID API is down.
- Cost-aware: only NEW texts are embedded; everything else is served from cache.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from datetime import datetime, timezone

from .common import load_json, project_path
from .diagnostics import warn

# Near-duplicate cosine threshold for text-embedding-3-small (768-dim) on
# WHOLE-TOPIC text (title + description + conclusion — NOT title alone).
#
# Empirical calibration (2026-06-29, boss's exact example):
#   TITLE-ONLY embeddings FAIL the boss's distinction — short structured titles
#   (「波動率對X的影響」) embed by sentence STRUCTURE, so cos(風險值, 選擇權定價)
#   =0.760 came out HIGHER than the actual paraphrase cos(風險值, VaR改寫)=0.706.
#   WHOLE-TOPIC text fixes it: paraphrase=0.752 > different-subtopic=0.569. This
#   confirms the boss's wording 「整個主題」 — callers MUST pass the full topic
#   (use `article_topic_text`), not just the keyword-laden title.
# Threshold sits between the different-subtopic and paraphrase bands. Refined
# 2026-06-29 on real feed pairs: clear rehashes (RECH-X ML article ×2 = 0.766,
# copper-ETF vol ×2 = 0.757) and the boss's deliberate paraphrase (0.752) all land
# ≥0.75, while a related-but-DISTINCT pair (K1333 vol-of-vol vs VIX→VRP = 0.724)
# sits just below. 0.74 catches the former, spares the latter. Preliminary —
# refine as labelled pairs accumulate.
DEFAULT_NEAR_DUP_THRESHOLD = 0.74

_CACHE_REL = "cache/topic_embeddings.json"

Embedder = Callable[[Sequence[str]], list[list[float]]]


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------
def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length vectors. 0.0 on a zero vector."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _text_key(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def article_topic_text(item: dict[str, Any]) -> str:
    """Assemble the WHOLE-TOPIC text for a feed/article item.

    Empirically required (see DEFAULT_NEAR_DUP_THRESHOLD note): title alone embeds
    by sentence structure and cannot separate distinct subtopics from rehashes.
    Combine title + description + the conclusion/arc so the embedding reflects the
    actual topic, matching the boss's 「整個主題」 principle. Capped to keep the
    embedding input bounded.
    """
    parts: list[str] = []
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        parts.append(title.strip())
    desc = item.get("description")
    if isinstance(desc, str) and desc.strip():
        parts.append(desc.strip())
    details = item.get("details")
    if isinstance(details, dict):
        for key in ("conclusion", "arc_signature", "headline"):
            val = details.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
    return "。".join(parts)[:1200]


# ---------------------------------------------------------------------------
# Embedding (cached, fail-open)
# ---------------------------------------------------------------------------
def _real_embedder(texts: Sequence[str]) -> list[list[float]]:
    """Default embedder — reuses the knowledge-index embedding pipeline."""
    repo = project_path("")  # PROJECT_ROOT
    scripts_dir = str(repo / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import build_knowledge_index as bki  # lazy: avoids importing openai unless used

    client = bki.get_client()
    return bki.embed_texts(client, list(texts))


def _cache_path(storage_dir: str) -> Path:
    return project_path(storage_dir) / _CACHE_REL


def _load_cache(storage_dir: str) -> dict[str, list[float]]:
    path = _cache_path(storage_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        warn("topic_similarity", "embedding cache read failed; starting empty", err=str(exc))
        return {}


def _save_cache(storage_dir: str, cache: dict[str, list[float]]) -> None:
    path = _cache_path(storage_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        warn("topic_similarity", "embedding cache write failed; continuing", err=str(exc))


def embed_with_cache(
    texts: Sequence[str],
    *,
    embedder: Embedder | None = None,
    storage_dir: str = "storage",
    use_cache: bool = True,
) -> list[list[float]] | None:
    """Embed `texts`, serving cached vectors and embedding only the misses.

    Returns a list of vectors aligned to `texts`, or None if embedding the misses
    fails (fail-open — caller treats None as `semantic_unavailable`).
    """
    embed = embedder or _real_embedder
    cache = _load_cache(storage_dir) if use_cache else {}
    keys = [_text_key(t) for t in texts]
    missing_idx = [i for i, k in enumerate(keys) if k not in cache]

    if missing_idx:
        try:
            new_vecs = embed([texts[i] for i in missing_idx])
        except Exception as exc:  # no API key / network / quota — fail-open
            warn("topic_similarity", "embedding failed; semantic signal unavailable", err=str(exc))
            return None
        if len(new_vecs) != len(missing_idx):
            warn(
                "topic_similarity",
                "embedder returned wrong count; semantic signal unavailable",
                want=len(missing_idx),
                got=len(new_vecs),
            )
            return None
        for idx, vec in zip(missing_idx, new_vecs):
            cache[keys[idx]] = list(vec)
        if use_cache:
            _save_cache(storage_dir, cache)

    return [cache[k] for k in keys]


# ---------------------------------------------------------------------------
# Concentration + dedup
# ---------------------------------------------------------------------------
def _nearest_other(vectors: list[list[float]]) -> list[tuple[int, float]]:
    """For each vector, the (index, cosine) of its most-similar OTHER vector."""
    out: list[tuple[int, float]] = []
    for i, vi in enumerate(vectors):
        best_j, best_s = -1, -1.0
        for j, vj in enumerate(vectors):
            if i == j:
                continue
            s = cosine(vi, vj)
            if s > best_s:
                best_j, best_s = j, s
        out.append((best_j, best_s))
    return out


def topic_concentration(
    titles: Sequence[str],
    *,
    embedder: Embedder | None = None,
    threshold: float = DEFAULT_NEAR_DUP_THRESHOLD,
    storage_dir: str = "storage",
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fraction of titles that are a SEMANTIC rehash of another recent title.

    The boss's concern: not 'how many mention VIX' (keyword) but 'how many are the
    same topic said again' (semantic). A title with a near-twin (cosine >=
    threshold) counts as concentrated; distinct subtopics do not. Fail-open:
    returns `{"status": "semantic_unavailable"}` if embedding is down.
    """
    clean = [t for t in titles if isinstance(t, str) and t.strip()]
    if len(clean) < 2:
        return {"status": "ok", "sample": len(clean), "note": "too few titles"}

    vectors = embed_with_cache(
        clean, embedder=embedder, storage_dir=storage_dir, use_cache=use_cache
    )
    if vectors is None:
        return {"status": "semantic_unavailable", "sample": len(clean)}

    nearest = _nearest_other(vectors)
    rehash = [i for i, (_, s) in enumerate(nearest) if s >= threshold]
    pairs = [
        {"title": clean[i], "twin": clean[j], "similarity": round(s, 3)}
        for i, (j, s) in enumerate(nearest)
        if s >= threshold and i < j  # report each pair once
    ]
    rate = round(len(rehash) / len(clean), 3)
    return {
        "status": "concentrated" if rate > 0.5 else "ok",
        "sample": len(clean),
        "rehash_count": len(rehash),
        "rehash_rate": rate,
        "threshold": threshold,
        "near_twin_pairs": sorted(pairs, key=lambda p: -p["similarity"])[:10],
    }


def near_duplicates(
    query: str,
    candidates: Sequence[str],
    *,
    embedder: Embedder | None = None,
    threshold: float = DEFAULT_NEAR_DUP_THRESHOLD,
    storage_dir: str = "storage",
    use_cache: bool = True,
) -> dict[str, Any]:
    """Semantic near-duplicates of `query` among `candidates` (future dedup gate).

    Fail-open: `{"status": "semantic_unavailable"}` if embedding is down.
    """
    cands = [c for c in candidates if isinstance(c, str) and c.strip()]
    if not query.strip() or not cands:
        return {"status": "ok", "matches": []}
    vectors = embed_with_cache(
        [query, *cands], embedder=embedder, storage_dir=storage_dir, use_cache=use_cache
    )
    if vectors is None:
        return {"status": "semantic_unavailable", "matches": []}
    qv = vectors[0]
    matches = [
        {"candidate": cands[i], "similarity": round(s, 3)}
        for i, cv in enumerate(vectors[1:])
        if (s := cosine(qv, cv)) >= threshold
    ]
    return {
        "status": "duplicate" if matches else "ok",
        "threshold": threshold,
        "matches": sorted(matches, key=lambda m: -m["similarity"]),
    }


# ---------------------------------------------------------------------------
# Feed-level report (the boss's directive on real content)
# ---------------------------------------------------------------------------
# Daily-templated article types are by-design repetitive (a daily bulletin/digest
# is supposed to look like yesterday's) — same rationale the cluster cooldown
# exempts timely types. They must NOT count as semantic over-concentration.
_DAILY_TEMPLATED_TITLE_PREFIXES = ("每日", "本日", "daily", "Daily")
_DAILY_TEMPLATED_TYPES = {"daily_digest", "daily_update", "daily-update"}


def _is_daily_templated(item: dict[str, Any]) -> bool:
    ct = str(item.get("content_type") or "").strip()
    if ct in _DAILY_TEMPLATED_TYPES:
        return True
    details = item.get("details")
    if isinstance(details, dict) and str(details.get("content_type") or "") in _DAILY_TEMPLATED_TYPES:
        return True
    title = item.get("title")
    return isinstance(title, str) and title.strip().startswith(_DAILY_TEMPLATED_TITLE_PREFIXES)


def _recent_published_items(
    storage_dir: str, lookback: int, *, exclude_daily: bool = True
) -> list[dict[str, Any]]:
    feed = load_json(project_path(storage_dir) / "reports" / "feed.json", [])
    if not isinstance(feed, list):
        return []
    pub = [x for x in feed if isinstance(x, dict) and x.get("status") == "published"]
    if exclude_daily:
        pub = [x for x in pub if not _is_daily_templated(x)]

    def _ts(item: dict[str, Any]) -> str:
        return str(item.get("published_at") or item.get("created_at") or "")

    pub.sort(key=_ts, reverse=True)
    return pub[:lookback]


def semantic_concentration_report(
    storage_dir: str = "storage",
    *,
    lookback: int = 20,
    embedder: Embedder | None = None,
    threshold: float = DEFAULT_NEAR_DUP_THRESHOLD,
    use_cache: bool = True,
    exclude_daily: bool = True,
) -> dict[str, Any]:
    """Semantic concentration of the recent published feed (the boss's directive).

    Unlike the keyword cluster cap (which counts every VIX-mentioning article as
    the same), this embeds each article's WHOLE TOPIC (title + description +
    conclusion) and reports the fraction that are a genuine semantic rehash of
    another recent article. Daily-templated bulletins are excluded by default
    (by-design repetitive). Fail-open: `semantic_unavailable` if embeddings are
    down — never blocks. Cached, so steady-state cost is ~the new articles only.
    """
    items = _recent_published_items(storage_dir, lookback, exclude_daily=exclude_daily)
    if len(items) < 2:
        return {"status": "ok", "sample": len(items), "note": "too few published items"}
    topics = [article_topic_text(it) for it in items]
    report = topic_concentration(
        topics,
        embedder=embedder,
        threshold=threshold,
        storage_dir=storage_dir,
        use_cache=use_cache,
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["lookback"] = lookback
    report["basis"] = "whole_topic_semantic"
    return report
