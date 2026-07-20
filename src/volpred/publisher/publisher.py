from __future__ import annotations
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from volpred.canonical_write import guard_canonical_write
from volpred.config.runtime import get_default_remote_url
from volpred.topic_clusters import classify_topic_cluster, cluster_gate_status


# 2026-06-23: feed.json bloat fix. The publisher API carries the FULL article
# markdown body in the ``description`` parameter, and the feed entry historically
# stored that body in BOTH ``description`` AND ``content`` (line ~1153
# ``'content': description``) — every article persisted twice. With 1650 entries
# the duplicate body was ~5.8MB of a 23MB feed.json. The frontend renders
# ``content`` as the body (``content || description || analysis``) and Supabase
# derives its own ``excerpt = content[:200]``; ``description`` is only a fallback
# that never fires because ``content`` is always populated. So ``description`` as
# a full-body clone is pure waste. Store a short plain-text excerpt instead —
# which is also the conventional semantic of a "description" (list preview / SEO
# meta). ``content`` stays the canonical full body; nothing downstream regresses.
_EXCERPT_MAX_CHARS = 300
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _taipei_publish_date(raw: str | None) -> date | None:
    """Return a feed timestamp's Taipei-local date, or ``None`` if invalid."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):  # silent-ok: invalid legacy timestamps cannot establish a same-day match
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_TAIPEI_TZ).date()


def _make_excerpt(body: str | None, max_chars: int = _EXCERPT_MAX_CHARS) -> str:
    """Derive a short plain-text excerpt from a markdown article body.

    Strips the leading H1/heading line, images, markdown emphasis/heading marks,
    and collapses whitespace, then truncates to ``max_chars`` (ellipsis appended
    when truncated). Returns '' for empty input. Pure/deterministic so the same
    body always yields the same excerpt (used by both publisher and backfill).
    """
    if not body:
        return ''
    text = str(body)
    # Drop image embeds entirely (alt text + url are noise for a preview).
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', text)
    # Unwrap links: keep the visible text, drop the URL.
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Strip heading markers, blockquote/list markers, emphasis, inline code.
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', text)
    text = re.sub(r'(?m)^\s{0,3}>\s?', '', text)
    text = re.sub(r'(?m)^\s{0,3}[-*+]\s+', '', text)
    text = text.replace('`', '').replace('**', '').replace('__', '')
    # Collapse all whitespace runs (incl. newlines) to single spaces.
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + '…'


# 2026-06-23 dedup policy inversion (boss directive「沒發文比重複發文嚴重」).
# A missed publish is ranked WORSE than a duplicate, so the dedup gates change
# from "default block, carve per-category exemptions" (the whack-a-mole that
# silently dropped daily/digest/event content all session) to "default publish,
# hard-block ONLY a provable byte-level recycle, WARN+log everything else".
#   - _RECYCLE_SIM: char-bigram body similarity above which a same-experiment-ref
#     republish is judged a true recycle (K1054 ghost was byte-for-byte ≈ 1.0).
#     Below it, a same-K article is a legitimate companion/different-angle piece
#     and now PUBLISHES instead of being silently swallowed.
#   - _log_dedup_decision: every block OR downgraded-warn is appended to
#     storage/logs/dedup_decisions.jsonl so a non-publish is NEVER silent —
#     it can be audited and (cheaply) retracted, which is the lesser evil.
_RECYCLE_SIM = 0.62


def _dup_body_similarity(a_title: str, a_body: str | None,
                         b_title: str, b_body: str | None) -> float:
    """Char-bigram Jaccard over normalized title+body (first 2000 chars of body).

    Distinguishes a true byte-level recycle (≥ _RECYCLE_SIM) from a same-topic /
    same-experiment companion piece with a genuinely different writeup. CJK-aware
    (strips latin/digits/punctuation so bigrams are content characters). Returns
    0.0 when either side is too short to judge (never blocks on thin input).
    """
    def _prof(title: str, body: str | None) -> set[str]:
        s = re.sub(r"[\s0-9A-Za-z，,。.：:；;？?！!（）()「」、\-—~%]+", "",
                   f"{title}\n{(body or '')[:2000]}")
        return {s[i:i + 2] for i in range(len(s) - 1)}
    pa = _prof(a_title, a_body)
    pb = _prof(b_title, b_body)
    if len(pa) < 20 or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def _log_dedup_decision(storage_dir: str, action: str, new_title: str | None,
                        matched_id: str | None, reason: str) -> None:
    """Append a structured dedup decision so a BLOCK is never silent.

    action ∈ {block_same_ref_recycle, allow_same_ref_companion, warn_near_dup,
    warn_arc_dup}. Fail-safe: logging must never break a publish.
    """
    # Imported here, not at module scope: volpred.ops's __init__ pulls in
    # ops.content, which imports this module (test_no_circular_imports).
    path = os.path.join(storage_dir, "logs", "dedup_decisions.jsonl")
    guard_canonical_write(path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "new_title": (new_title or "")[:120],
            "matched_id": matched_id,
            "reason": reason,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # silent-ok: dedup logging must never break a publish


def _semantic_dup_warn(storage_dir: str, item: dict, feed: list[dict]) -> None:
    """WARN-ONLY semantic near-dup check at publish (boss email-12139 directive).

    The keyword gate (`_find_same_ref_feed_duplicate`) only catches dups that
    SHARE experiment refs + are byte-similar. A semantic rehash (same topic, new
    framing, possibly different refs — e.g. RECH-X written twice) slips through.
    This embeds the candidate's WHOLE TOPIC and compares it against recent
    published topics; on a near-dup it logs `warn_semantic_dup` to
    dedup_decisions.jsonl. Per `.claude/rules/dedup-gate-audit.md`, a FUZZY signal
    must be WARN-ONLY (never a hard block — no content gap) and FAIL-OPEN. Wrapped
    so it can never break a publish; daily-templated bulletins are skipped.
    """
    try:
        from datetime import datetime, timezone

        from volpred.ops.topic_similarity import (
            DEFAULT_NEAR_DUP_THRESHOLD,
            _is_daily_templated,
            article_topic_text,
            cosine,
            effective_near_dup_threshold,
            embed_with_cache,
        )

        if _is_daily_templated(item):
            return
        item_id = item.get("id")
        query = article_topic_text(item)
        if not query.strip():
            return
        recent = [
            x for x in feed
            if isinstance(x, dict)
            and x.get("status") == "published"
            and x.get("id") != item_id
            and not _is_daily_templated(x)
        ]
        recent.sort(key=lambda x: x.get("published_at") or x.get("created_at") or "", reverse=True)
        recent = recent[:15]
        if not recent:
            return

        # Dynamic threshold (boss email-12153 2026-06-29): when the platform
        # is in a reader-facing drought, relax the semantic warn gate so the
        # pool can release borderline-similar pieces rather than freeze.
        # gap = hours since newest reader-facing published article.
        gap_hours: float | None = None
        try:
            from volpred.ops.content import _is_reader_facing_published, _parse_datetime
            reader_times = [
                t for t in (
                    _parse_datetime(a.get("published_at"))
                    for a in feed
                    if isinstance(a, dict) and _is_reader_facing_published(a)
                ) if t is not None
            ]
            if reader_times:
                now = datetime.now(timezone.utc)
                gap_hours = (now - max(reader_times)).total_seconds() / 3600.0
        except Exception:  # silent-ok: gap-hours probe is best-effort, fall through to baseline
            gap_hours = None
        threshold = effective_near_dup_threshold(gap_hours)

        topics = [article_topic_text(x) for x in recent]
        vecs = embed_with_cache([query, *topics], storage_dir=storage_dir)
        if vecs is None:
            return  # fail-open: embeddings unavailable
        qv = vecs[0]
        for x, tv in zip(recent, vecs[1:]):
            sim = cosine(qv, tv)
            if sim >= threshold:
                gap_text = (
                    f"gap={gap_hours:.1f}h, threshold={threshold} (dynamic ladder)"
                    if gap_hours is not None
                    else f"threshold={threshold} (baseline)"
                )
                _log_dedup_decision(
                    storage_dir, "warn_semantic_dup", item.get("title"), x.get("id"),
                    f"whole-topic semantic similarity {round(sim, 3)} >= {threshold} "
                    f"vs {x.get('id')} ({gap_text}; warn-only per dedup-gate-audit)",
                )
                break  # one warning per publish is enough
    except Exception as exc:
        # Observable (not silent) but never blocks the publish — fail-open.
        print(f"  ⚠️ semantic dedup warn-check skipped (publish proceeds): {exc}")


_ANTI_AI_GATE_NAME = "anti_ai_style"
_ANTI_AI_GATE_STRICT_AFTER = date(2026, 7, 13)
_ANTI_AI_GATE_READER_AUDIENCES = {"general", "research", "event", "member_qa"}
_ANTI_AI_GATE_READER_CONTENT_TYPES = {
    "general_article",
    "research_article",
    "daily_digest",
    "event_article",
    "trending_repost",
    "member_qa",
}
_ANTI_AI_GATE_DAILY_BULLETIN_TYPES = {"daily_update", "daily-update"}
_ANTI_AI_TEMPLATE_FIXES: tuple[tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"值得注意的是[，,]?\s*"), "", "remove_值得注意的是"),
    (re.compile(r"綜上所述[，,]?\s*"), "", "remove_綜上所述"),
    (re.compile(r"總而言之[，,]?\s*"), "", "remove_總而言之"),
    (re.compile(r"簡而言之[，,]?\s*"), "", "remove_簡而言之"),
    (re.compile(r"更值得思考的是[，,]?\s*"), "要看的是，", "rewrite_更值得思考的是"),
    (re.compile(r"值得關注的是[，,]?\s*"), "要看的是，", "rewrite_值得關注的是"),
)


def _anti_ai_gate_warn_only() -> tuple[bool, str]:
    """Return whether the gate is in migration warn-only mode.

    Task topology-audit-20260710-anti-ai-gate-wire allows a 3-day warn-only
    ramp. The date is deliberately machine-readable so the soft gate cannot
    silently become permanent.
    """
    mode = os.environ.get("VOLPRED_ANTI_AI_GATE_MODE", "").strip().lower()
    if mode in {"strict", "block", "hard"}:
        return False, "strict_env"
    if mode in {"warn", "warn_only", "warn-only"}:
        return True, "warn_only_env"
    if os.environ.get("VOLPRED_ANTI_AI_GATE_STRICT") == "1":
        return False, "strict_env_legacy"
    today = datetime.now(timezone.utc).date()
    if today < _ANTI_AI_GATE_STRICT_AFTER:
        return True, f"warn_only_until_{_ANTI_AI_GATE_STRICT_AFTER.isoformat()}"
    return False, f"strict_after_{_ANTI_AI_GATE_STRICT_AFTER.isoformat()}"


def _anti_ai_content_type(item: dict) -> str:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    return str(
        details.get("content_type")
        or item.get("content_type")
        or item.get("category")
        or ""
    ).strip().lower()


def _anti_ai_gate_applies(item: dict, *, target_status: str | None = None) -> bool:
    if str(target_status or item.get("status") or "").strip().lower() != "published":
        return False
    audience = str(item.get("audience") or "").strip().lower()
    content_type = _anti_ai_content_type(item)
    if audience == "daily" and content_type in _ANTI_AI_GATE_DAILY_BULLETIN_TYPES:
        return False
    if content_type in _ANTI_AI_GATE_READER_CONTENT_TYPES:
        return True
    return audience in _ANTI_AI_GATE_READER_AUDIENCES


def _anti_ai_fb_mode(item: dict) -> bool:
    # 2026-07-16: feed articles are never FB posts. The fb_mode checks
    # (3.2 short-paragraph / 3.4 list-structure) encode FB-caption layout
    # rules; applying them to long-form feed content made every digest
    # (whose spec REQUIRES a curated link list) start 2 WARNs deep and
    # blocked daily_digest_20260716 once the gate turned strict on
    # 2026-07-13. FB captions are written in the fb-publishing flow, not
    # via publish_milestone, so this gate always audits feed text.
    del item
    return False


def _normalize_anti_ai_template_phrases(text: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    out = text
    for pattern, replacement, label in _ANTI_AI_TEMPLATE_FIXES:
        out, count = pattern.subn(replacement, out)
        if count:
            fixes.append(f"{label}:{count}")
    return out, fixes


def _apply_anti_ai_autofixes(item: dict) -> list[str]:
    """Apply deterministic, low-risk style fixes before the blocking check."""
    fixes: list[str] = []
    text_fields = ("content", "description", "summary", "analysis")
    for field in text_fields:
        raw = item.get(field)
        if not isinstance(raw, str) or not raw:
            continue
        text = raw
        try:
            from volpred.publisher.emdash_normalizer import normalize_emdash

            normalized, emrep = normalize_emdash(text)
            if emrep.changed:
                text = normalized
                fixes.append(f"{field}:emdash:{emrep.replaced}")
                print(
                    f"  [feed_publisher] emdash_normalizer auto-fixed "
                    f"{emrep.replaced} em-dash(es) for "
                    f"{item.get('id', 'unknown')}: {emrep.summary()}"
                )
        except Exception as exc:
            # The hard gate itself remains fail-open; keep auto-fix failures
            # observable but do not abort before the checker gets a chance to run.
            print(
                f"  [feed_publisher] WARN emdash_normalizer skipped for "
                f"{item.get('id', 'unknown')}: {exc}"
            )
        text, phrase_fixes = _normalize_anti_ai_template_phrases(text)
        if phrase_fixes:
            fixes.extend(f"{field}:{fix}" for fix in phrase_fixes)
            print(
                f"  [feed_publisher] anti_ai_template auto-fixed "
                f"{len(phrase_fixes)} phrase pattern(s) for "
                f"{item.get('id', 'unknown')}: {phrase_fixes}"
            )
        if text != raw:
            item[field] = text
    return fixes


def _anti_ai_gate_text(item: dict) -> str:
    body = (
        item.get("content")
        or item.get("analysis")
        or item.get("summary")
        or item.get("description")
        or ""
    )
    return f"{item.get('title') or ''}\n\n{body}"


def _run_anti_ai_checks(text: str, *, fb_mode: bool) -> tuple[bool, list[str]]:
    import sys

    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from anti_ai_gate import run_checks  # noqa: WPS433

    return run_checks(text, fb_mode=fb_mode)


def _log_anti_ai_gate_decision_impl(
    storage_dir: str,
    item: dict,
    *,
    decision: str,
    reason: str,
    failures: list[str] | None = None,
    fixes: list[str] | None = None,
    mode: str | None = None,
) -> None:
    """Append the anti-AI gate audit record; logging is fail-open."""
    path = os.path.join(storage_dir, "logs", "dedup_decisions.jsonl")
    guard_canonical_write(path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "gate": _ANTI_AI_GATE_NAME,
            "target_id": item.get("id"),
            "decision": decision,
            "reason": reason,
            "mode": mode,
            "strict_after": _ANTI_AI_GATE_STRICT_AFTER.isoformat(),
            "title": str(item.get("title") or "")[:120],
            "audience": item.get("audience"),
            "content_type": _anti_ai_content_type(item),
            "failures": list(failures or [])[:8],
            "fixes": list(fixes or [])[:12],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        # fail-open per dedup-gate-audit.md（log 失敗不可炸 publish），但 swallow 必須可觀測
        print(f"⚠️ anti_ai_gate_decision_log_failed (fail-open): {e}")


def _send_anti_ai_gate_degraded_alert(storage_dir: str, item: dict, exc: Exception) -> None:
    try:
        from volpred.ops.alerts import send_alert

        send_alert(
            level="warn",
            title="anti_ai_style gate 失效 — publish gate fail-open",
            body=(
                "publish pipeline 的 anti_ai_style gate 拋出例外並 fail-open，"
                f"文章 `{item.get('id')}` / `{str(item.get('title') or '')[:80]}` "
                "會繼續發佈但未完成 anti-AI-style 檢查。\n\n"
                f"例外：`{type(exc).__name__}: {exc}`\n\n"
                "請檢查 `scripts/anti_ai_gate.py` 與 "
                "`src/volpred/publisher/publisher.py::_run_publish_anti_ai_gate`。"
            ),
            storage_dir=storage_dir,
        )
    except Exception as alert_exc:
        print(
            f"  [feed_publisher] WARN anti-AI degraded alert failed for "
            f"{item.get('id', 'unknown')}: {alert_exc}"
        )


def _run_publish_anti_ai_gate(
    storage_dir: str,
    item: dict,
    *,
    target_status: str | None = None,
    raise_on_block: bool = True,
    log_decision: bool = True,
) -> list[str]:
    """Run anti-AI-style publish gate.

    Returns release-audit issues when `raise_on_block=False`; otherwise raises
    ValueError on hard-block. Gate malfunction is explicitly fail-open.

    `log_decision=False` runs the identical verdict without appending to the
    canonical dedup-decision ledger — for read-only callers such as
    `preview_release_pool_by_settings`, which must be able to ask "would this
    release?" without leaving a decision trail that implies a release was
    attempted (2026-07-19).
    """
    if not _anti_ai_gate_applies(item, target_status=target_status):
        return []

    def _log_anti_ai_gate_decision(*args, **kwargs):  # noqa: WPS430
        if log_decision:
            return _log_anti_ai_gate_decision_impl(*args, **kwargs)
        return None

    warn_only, mode_reason = _anti_ai_gate_warn_only()
    try:
        fixes = _apply_anti_ai_autofixes(item)
        text = _anti_ai_gate_text(item)
        if not text.strip():
            _log_anti_ai_gate_decision(
                storage_dir,
                item,
                decision="warn",
                reason="empty_text_fail_open",
                fixes=fixes,
                mode=mode_reason,
            )
            return []
        passed, failures = _run_anti_ai_checks(text, fb_mode=_anti_ai_fb_mode(item))
    except Exception as exc:
        _log_anti_ai_gate_decision(
            storage_dir,
            item,
            decision="pass",
            reason=f"gate_error_fail_open_degraded:{type(exc).__name__}:{exc}",
            mode=mode_reason,
        )
        if log_decision:
            _send_anti_ai_gate_degraded_alert(storage_dir, item, exc)
        print(
            f"  [feed_publisher] WARN anti-AI gate fail-open for "
            f"{item.get('id', 'unknown')}: {exc}"
        )
        return []

    warn_count = sum(1 for failure in failures if "[WARN]" in failure)
    must_count = sum(1 for failure in failures if "[MUST]" in failure)
    summary = "; ".join(f.strip() for f in failures[:5])
    if passed:
        decision = "warn" if failures else "pass"
        reason = (
            f"passed_with_minor_warnings warn={warn_count} must={must_count}: {summary}"
            if failures
            else "passed"
        )
        _log_anti_ai_gate_decision(
            storage_dir,
            item,
            decision=decision,
            reason=reason,
            failures=failures,
            fixes=fixes,
            mode=mode_reason,
        )
        return []

    reason = (
        f"blocked_by_checker warn={warn_count} must={must_count}: {summary}; "
        "fix per .claude/skills/anti-ai-style/references/editor-sop.md"
    )
    if warn_only:
        _log_anti_ai_gate_decision(
            storage_dir,
            item,
            decision="warn",
            reason=(
                f"{reason}; WARN-ONLY migration until "
                f"{_ANTI_AI_GATE_STRICT_AFTER.isoformat()}"
            ),
            failures=failures,
            fixes=fixes,
            mode=mode_reason,
        )
        print(
            f"  [feed_publisher] WARN anti-AI gate would block "
            f"{item.get('id', 'unknown')} after "
            f"{_ANTI_AI_GATE_STRICT_AFTER.isoformat()}: {summary}"
        )
        return []

    _log_anti_ai_gate_decision(
        storage_dir,
        item,
        decision="block",
        reason=reason,
        failures=failures,
        fixes=fixes,
        mode=mode_reason,
    )
    issue = (
        f"anti_ai_style publish gate failed: {summary}. "
        "Rewrite per .claude/skills/anti-ai-style/references/editor-sop.md"
    )
    if raise_on_block:
        raise ValueError(issue)
    return [issue]


# 2026-06-23: base64 data-URI image gate. One-time Codex publish scripts embedded
# charts as ``![alt](data:image/png;base64,...)`` (bypassing Supabase upload via
# monkey-patched _normalize_publish_assets), bloating feed.json — one entry hit
# 862KB, 10 entries ~1.84MB total. This regex + _extract_base64_images() is the
# canonical-write-site safety net: ANY content reaching _append_to_feed gets its
# data URIs decoded → uploaded to the article-images bucket → rewritten to the
# public URL. Fail-safe: on any error keep the original data URI and warn — never
# block a publish over an image. Reused by scripts/extract_base64_images.py.
_DATA_URI_IMG_RE = re.compile(
    r'!\[([^\]]*)\]\(data:image/([\w.+-]+);base64,([A-Za-z0-9+/=\s]+)\)'
)


def _extract_base64_images(content: str, article_id: str) -> str:
    """Replace inline base64 data-URI images with uploaded Supabase URLs."""
    if not content or 'data:image' not in content:
        return content
    import base64 as _b64
    import tempfile

    try:
        from volpred.charts.article_charts import upload_chart
    except Exception as exc:  # pragma: no cover - import guard
        print(f"  [feed_publisher] WARN base64 gate: upload_chart unavailable for {article_id}: {exc}")
        return content

    counter = {'n': 0}

    def _repl(match: re.Match) -> str:
        alt, img_type, data = match.group(1), match.group(2), match.group(3)
        try:
            raw = _b64.b64decode(re.sub(r'\s+', '', data))
            counter['n'] += 1
            ext = 'png' if img_type.lower() in ('png', 'x-png') else img_type.lower().replace('+', '_')
            fname = f"{article_id}_chart{counter['n']}.{ext}"
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / fname
                path.write_bytes(raw)
                url = upload_chart(str(path), bucket='article-images')
            print(
                f"  [feed_publisher] base64 gate: {article_id} extracted "
                f"{len(raw) // 1024}KB inline image → {url}"
            )
            return f"![{alt}]({url})"
        except Exception as exc:
            print(f"  [feed_publisher] WARN base64 gate: extract failed for {article_id}: {exc}")
            return match.group(0)

    return _DATA_URI_IMG_RE.sub(_repl, content)


# 2026-04-26: audience-content consistency gate. Prior bug: agent dispatched
# with audience='general' brief, wrote research-style content (K-id tags,
# t-stats, Harvey thresholds, 14-tag pollution); publisher silently accepted
# because only audience field was checked, not content-vs-audience match.
# These constants define what "general" audience MUST NOT contain.
_K_ID_TAG_PATTERN = re.compile(r'^K\d+[a-zA-Z_]?\d*$')

# 2026-04-26: audience badge canonicalization. Frontend badge renders the
# Chinese canonical name; agents in briefs / past code used English literals
# ("general", "research") or mixed (Chinese + English) interchangeably →
# 21 articles in feed.json had redundant or conflicting audience tags
# (e.g. ["研究", "一般讀者"], ["研究", "general"]). Map every known alias to
# the canonical Chinese tag; strip ALL aliases at publish time and re-insert
# exactly one matching the article's audience field.
_AUDIENCE_TAG_CANONICAL = {
    # English audience values (publisher API convention)
    'general': '一般讀者',
    'research': '研究',
    'daily': '每日建議',
    'member_qa': '會員提問',
    # Chinese canonical (the badge value itself)
    '一般讀者': '一般讀者',
    '研究': '研究',
    '每日建議': '每日建議',
    '會員提問': '會員提問',
    # Common variants seen in historical feed
    'General': '一般讀者',
    'Research': '研究',
    'Daily': '每日建議',
    'daily-update': '每日建議',
    'member-qa': '會員提問',
}
_AUDIENCE_TAG_ALL_ALIASES = frozenset(_AUDIENCE_TAG_CANONICAL.keys())
# 2026-07-02 (error_log 15:15 root cause #1): this gate bans BARE jargon
# notation only — the statistical information itself must stay in the article,
# rephrased in plain words with the number preserved. Hints below give the
# translation template; scripts/publish_draft.py::sanitize_general applies the
# same table automatically on the CLI publish path.
_GENERAL_FORBIDDEN_PATTERNS = [
    (re.compile(r'\bt\s*=\s*-?\d'), 't=值 → 白話包裝保留數值，例「統計檢定顯著（強度中上，統計值 2.24）」'),
    (re.compile(r'\bp\s*=\s*\d'), 'p=值 → 依大小分級，例「達顯著水準（顯著性 0.03）」；p=0.3 要寫「未達顯著水準」'),
    (re.compile(r'p\s*[<>]\s*0\.\d'), 'p<X / p>X → 例「達顯著水準（顯著性低於 0.05）」/「未達顯著水準」'),
    (re.compile(r'\bHarvey\b'), 'Harvey threshold → 「嚴格統計檢驗門檻」（引用格式 Harvey (2016) 可保留）'),
    (re.compile(r'\bDiebold-Mariano\b'), 'Diebold-Mariano → 「兩模型比較顯著」'),
    (re.compile(r'\bDM\s*test\b', re.IGNORECASE), 'DM test → 「比較檢定」'),
    (re.compile(r'\|t\|'), '|t| → 「統計強度」，數值照列'),
    (re.compile(r'\bt-stat\b', re.IGNORECASE), 't-stat → 「統計強度」，數值照列'),
    (re.compile(r'bootstrap\s+p[\s_=-]'), 'bootstrap p → 「重抽樣比較」'),
]
_GENERAL_MAX_TAG_COUNT = 8

# 2026-05-26: Academic keyword list shared between _audit_general_content and
# _infer_audience. Single source of truth — edit here, both functions benefit.
# Patterns that indicate research-grade content unsuitable for general audience.
_ACADEMIC_KEYWORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'K\d+', re.IGNORECASE), 'K-id'),
    (re.compile(r'\bp[\s-]?value\b', re.IGNORECASE), 'p-value'),
    (re.compile(r'\bt[-\s]?stat\b', re.IGNORECASE), 't-stat'),
    (re.compile(r'\bQlike\b', re.IGNORECASE), 'QLIKE'),
    (re.compile(r'\bSharpe\b', re.IGNORECASE), 'Sharpe'),
    (re.compile(r'\bBonferroni\b', re.IGNORECASE), 'Bonferroni'),
    (re.compile(r'\bbootstrap\b', re.IGNORECASE), 'bootstrap'),
    (re.compile(r'\bMLE\b'), 'MLE'),
    (re.compile(r'\bcointegration\b', re.IGNORECASE), 'cointegration'),
    (re.compile(r'\bGARCH[-\s]?X\b', re.IGNORECASE), 'GARCH-X'),
    (re.compile(r'\bHarvey\b'), 'Harvey'),
    (re.compile(r'\bDiebold[-\s]?Mariano\b', re.IGNORECASE), 'Diebold-Mariano'),
    (re.compile(r'\bDM\s+test\b', re.IGNORECASE), 'DM test'),
    (re.compile(r'\bHAR[-\s]?RV\b', re.IGNORECASE), 'HAR-RV'),
    (re.compile(r'\bGJR[-\s]?GARCH\b', re.IGNORECASE), 'GJR-GARCH'),
    (re.compile(r'\bEGARCH\b', re.IGNORECASE), 'EGARCH'),
    (re.compile(r'\bGARCH\b', re.IGNORECASE), 'GARCH'),
    (re.compile(r'\bMCS\b'), 'MCS'),
    (re.compile(r'\bVaR\b'), 'VaR'),
]
_ACADEMIC_KEYWORD_THRESHOLD = 2  # ≥2 matches → infer research


_MARKDOWN_IMAGE_URL_RE = re.compile(r'!\[([^\]]*)\]\([^)]+\)')
_DAILY_AUDIENCE_CONTENT_TYPES = frozenset({'daily', 'daily_update', 'daily-update'})
_DAILY_AUDIENCE_TAGS = frozenset({'每日建議', 'daily-update'})


def _is_daily_audience_signal(
    tags: list[str] | None,
    content_type: str | None = None,
) -> bool:
    """Return whether canonical metadata type-locks an article as daily."""
    normalized_type = str(content_type or '').strip()
    return (
        normalized_type in _DAILY_AUDIENCE_CONTENT_TYPES
        or bool(_DAILY_AUDIENCE_TAGS.intersection(tags or []))
    )


def _academic_keyword_hits(
    title: str,
    content: str,
    tags: list[str] | None,
) -> list[str]:
    """Return the distinct audience-inference signals in publisher order.

    This helper is deliberately shared with the feed invariant checker.  The
    old checker copied ``_ACADEMIC_KEYWORDS`` and then drifted from the actual
    publisher in two important ways: it ignored tags and counted K-ids in image
    URLs.  Keeping the normalization here makes the publish-time decision and
    the historical audit the same decision.
    """
    # Image filenames often carry experiment ids / metric names (for example
    # ``k1685_qlike.png``).  They are provenance, not reader-visible prose.
    content_no_img_urls = _MARKDOWN_IMAGE_URL_RE.sub(r'![\1]()', content or '')
    combined = ' '.join(
        filter(None, [title or '', content_no_img_urls, ' '.join(tags or [])])
    )
    hits: list[str] = []
    seen: set[str] = set()
    for pattern, label in _ACADEMIC_KEYWORDS:
        if label in seen:
            continue
        if pattern.search(combined):
            hits.append(label)
            seen.add(label)
    return hits


def _load_publish_draft_image_helpers():
    """Load canonical image normalization helpers from publish_draft.py."""
    import sys

    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from publish_draft import normalize_image_paths, normalize_image_url_field
    return normalize_image_paths, normalize_image_url_field


def _should_treat_as_local_upload_ref(value: str) -> bool:
    """True for local file refs that should upload, False for web URLs/routes."""
    if not isinstance(value, str) or not value.strip():
        return False
    value = value.strip()
    if re.match(r"^https?://", value, re.IGNORECASE):
        return False
    # Site-rooted web paths like /charts/foo.png should pass through unchanged.
    if value.startswith("/"):
        return False
    return True


def _normalize_publish_assets(
    description: str | None,
    details: dict | None,
    *,
    root: Path,
) -> tuple[str | None, dict]:
    """Upload local chart refs and rewrite them to canonical URLs."""
    details = dict(details or {})
    cache: dict[str, str] = {}
    normalize_image_paths, normalize_image_url_field = _load_publish_draft_image_helpers()
    uploaded_urls: list[str] = []

    def _record_uploaded_url(url: str):
        if isinstance(url, str) and url.startswith("http") and url not in uploaded_urls:
            uploaded_urls.append(url)

    def _normalize_scalar_ref(value: str) -> str:
        if not _should_treat_as_local_upload_ref(value):
            return value
        new_value = normalize_image_url_field(value, root, cache=cache)
        _record_uploaded_url(new_value)
        return new_value

    if isinstance(description, str) and "![" in description:
        new_description, _ = normalize_image_paths(description, root, cache=cache)
        description = new_description
        for url in cache.values():
            _record_uploaded_url(url)

    if _should_treat_as_local_upload_ref(details.get("image_url", "")):
        details["image_url"] = _normalize_scalar_ref(details["image_url"])

    for list_key in ("image_urls", "chart_urls", "supabase_storage_urls"):
        values = details.get(list_key)
        if isinstance(values, list):
            details[list_key] = [
                _normalize_scalar_ref(v) if isinstance(v, str) else v
                for v in values
            ]

    charts = details.get("charts")
    if isinstance(charts, list):
        normalized_charts = []
        for entry in charts:
            if isinstance(entry, str):
                normalized_charts.append(_normalize_scalar_ref(entry))
                continue
            if isinstance(entry, dict):
                chart_entry = dict(entry)
                for key in ("path", "url", "image_url", "src"):
                    value = chart_entry.get(key)
                    if isinstance(value, str) and _should_treat_as_local_upload_ref(value):
                        chart_entry[key] = _normalize_scalar_ref(value)
                normalized_charts.append(chart_entry)
                continue
            normalized_charts.append(entry)
        details["charts"] = normalized_charts

    if uploaded_urls:
        existing_image_urls = details.get("image_urls")
        if isinstance(existing_image_urls, list):
            details["image_urls"] = list(dict.fromkeys(existing_image_urls + uploaded_urls))
        else:
            details["image_urls"] = uploaded_urls.copy()

        existing_supabase_urls = details.get("supabase_storage_urls")
        if isinstance(existing_supabase_urls, list):
            details["supabase_storage_urls"] = list(dict.fromkeys(existing_supabase_urls + uploaded_urls))
        else:
            details["supabase_storage_urls"] = uploaded_urls.copy()

    return description, details


def _publish_asset_root_from_storage_dir(storage_dir: Path) -> Path:
    """Resolve article asset paths from the canonical project root."""
    storage_dir = storage_dir.resolve()
    if storage_dir.name == "storage":
        return storage_dir.parent
    return storage_dir


def _infer_audience(
    title: str,
    content: str,
    tags: list[str],
    content_type: str | None = None,
) -> str:
    """Infer the correct audience from content signals. This is the source of truth.

    Enforce mechanism: caller-supplied audience is only a hint. If _infer_audience
    disagrees, the inferred value wins and a WARN is emitted (see publish_milestone).
    This prevents agents from defaulting to 'general' for research-grade content,
    which caused mile_d0d66405 to be mis-tagged (audience=general despite ≥2 academic
    keywords in title and content).

    Rules (in priority order):
    1. content_type == 'member_qa'  → 'member_qa' (always preserve)
    2. content_type == 'event_article' → 'event' (always preserve)
    3. content_type == 'daily_digest' → 'general' (curated reader-facing column)
    4. daily content type / tag → 'daily' (retail daily bulletin)
    5. Title contains K\\d+ regex match → 'research'
    6. title + content + tags combined contain ≥2 academic keywords → 'research'
    7. Default → 'general'

    Academic keyword list: K\\d+, p-value, t-stat, QLIKE, Sharpe, Bonferroni,
    bootstrap, MLE, cointegration, GARCH-X, Harvey, Diebold-Mariano, DM test,
    HAR-RV, GJR-GARCH, EGARCH, GARCH, MCS, VaR.
    """
    # Rule 1 & 2: content_type overrides
    if content_type == 'member_qa':
        return 'member_qa'
    if content_type == 'event_article':
        return 'event'
    if content_type == 'daily_digest':
        return 'general'
    if _is_daily_audience_signal(tags, content_type):
        return 'daily'

    # Rule 5: K-id in title → research
    if re.search(r'K\d+', title or ''):
        return 'research'

    # Rule 6: count academic keywords across title + content + tags using the
    # same normalizer consumed by the historical feed validator.
    if len(_academic_keyword_hits(title, content, tags)) >= _ACADEMIC_KEYWORD_THRESHOLD:
        return 'research'

    return 'general'


def _extract_experiment_refs(tag_list: list[str]) -> tuple[list[str], list[str]]:
    """Split K-id tags out of user-facing tags into metadata refs.

    K-id tags (K438, K1258, K1100g, etc.) are research-internal identifiers.
    They belong in details.experiment_refs as metadata, not in the user-facing
    tags field that drives badge rendering and reader navigation. Pre-2026-04-26
    code mixed them together → general articles ended up with 14 tags including
    4 K-ids, polluting frontend tag clouds and search.
    """
    refs = []
    cleaned = []
    for t in tag_list:
        if _K_ID_TAG_PATTERN.match(t.strip()):
            refs.append(t.strip().upper())
        else:
            cleaned.append(t)
    return cleaned, refs


def _normalize_experiment_ref(raw: object) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if re.match(r"^[Kk]\d", s):
        return "K" + s[1:]
    return s.upper()


def _iter_ref_values(raw: object):
    if raw is None:
        return
    if isinstance(raw, (list, tuple, set)):
        for val in raw:
            yield val
        return
    yield raw


def _item_experiment_refs(item: dict) -> set[str]:
    """Return canonical experiment refs from current and legacy feed shapes."""
    refs: set[str] = set()
    details = item.get("details") or {}
    if isinstance(details, dict):
        for key in ("experiment_refs", "experiment_ids", "experiment_id"):
            for raw in _iter_ref_values(details.get(key)):
                ref = _normalize_experiment_ref(raw)
                if ref:
                    refs.add(ref)
    for key in ("experiment_refs", "experiment_ids", "experiment_id"):
        for raw in _iter_ref_values(item.get(key)):
            ref = _normalize_experiment_ref(raw)
            if ref:
                refs.add(ref)
    for raw in _iter_ref_values(item.get("tags") or []):
        s = str(raw or "").strip()
        if re.fullmatch(r"[Kk]\d+[a-z]?", s):
            refs.add(_normalize_experiment_ref(s))
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "summary", "description", "content", "analysis")
    )
    for match in re.findall(r"[Kk]\d{2,}[a-z]?", text):
        refs.add(_normalize_experiment_ref(match))
    return refs


def _find_same_ref_feed_duplicate(feed: list[dict], item: dict) -> dict | None:
    """Last-resort same-experiment-ref duplicate gate for every feed writer.

    `publish_milestone` has richer arc and near-duplicate gates before item
    construction. Legacy entrypoints (`publish_experiment`, `publish_comparison`)
    bypass those gates, so `_append_to_feed` needs a minimal choke-point guard:
    same non-retracted experiment ref + same audience + near-identical BODY means
    "already covered" (a true recycle). 2026-06-23 (boss「沒發文比重複發文嚴重」):
    require the body-similarity check here too, so a same-K but different-angle
    companion piece that passed publish_milestone's relaxed gate is not silently
    re-blocked at the append choke point.
    """
    details = item.get("details") or {}
    if isinstance(details, dict) and details.get("dup_waiver"):
        return None
    refs = _item_experiment_refs(item)
    if not refs:
        return None
    audience = item.get("audience")
    item_title = item.get("title", "")
    item_body = item.get("content") or item.get("description") or ""
    for existing in feed:
        if existing.get("status") in ("unpublished", "retracted"):
            continue
        existing_audience = existing.get("audience")
        if audience and existing_audience and existing_audience != audience:
            continue
        shared = refs & _item_experiment_refs(existing)
        if not shared:
            continue
        body_sim = _dup_body_similarity(
            item_title, item_body,
            existing.get("title", ""),
            existing.get("content") or existing.get("description") or "",
        )
        if body_sim >= _RECYCLE_SIM:
            return existing
    return None


_LAZYPACK_HEADING_RE = re.compile(r"^#+\s*.*懶人包.*$", re.MULTILINE)
_LAZYPACK_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")


def has_lazypack_section(content: str) -> bool:
    """True iff `content` carries a real 懶人包圖組 (lazypack) section.

    Single source of truth for the lazypack requirement, shared by the
    publish_draft.py CLI gate (`check_lazypack_gate`) and the Publisher
    chokepoint gate (publish_milestone). A valid lazypack = a markdown heading
    containing 懶人包 (## 懶人包 / ## 懶人包圖組) WITH at least one markdown image
    appearing after it — so a bare prose mention or an empty heading does not pass.

    Fail-open contract (callers rely on this): on any internal error return True
    (treat as present) so a malfunctioning check never over-blocks content, per
    .claude/rules/no-silent-fallback.md + dedup-gate-audit.md.
    """
    try:
        headings = list(_LAZYPACK_HEADING_RE.finditer(content))
        if not headings:
            return False
        return bool(_LAZYPACK_IMAGE_RE.search(content[headings[0].end():]))
    except Exception:
        return True  # silent-ok: fail-open so a gate malfunction never over-blocks


def lazypack_required_at(status: str | None) -> bool:
    """Lazypack enforcement boundary (2026-07-02 async pipeline, error_log 15:15 #4).

    The 懶人包圖組 section is required exactly when an article becomes
    reader-visible (status='published'). Draft/scheduled creation defers the
    render to the compute_queue async lane (scripts/lazypack_async_render.py);
    the release_pool audit gate (volpred.ops.content) enforces the section
    before flipping to published. Single source for this boundary — shared by
    publish_milestone and publish_draft.py's check_lazypack_gate.
    """
    return str(status or "published").strip().lower() == "published"


def _audit_general_content(audience: str, tags: list[str], content: str) -> list[str]:
    """Return list of audience-content consistency issues. Empty list = clean.

    Only enforces rules for audience='general' (散戶讀者). research/daily/
    member_qa have their own conventions and are exempt.
    """
    if audience != 'general':
        return []
    issues = []
    if len(tags) > _GENERAL_MAX_TAG_COUNT:
        issues.append(
            f"general tag count {len(tags)} > {_GENERAL_MAX_TAG_COUNT} "
            f"(SKILL.md L308: ≤2-3 表格 → ≤8 tags)"
        )
    audit_content = content or ''
    try:
        import sys

        scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from publish_draft import _stash_citations  # noqa: WPS433

        audit_content, _ = _stash_citations(audit_content)
    except Exception:
        # Citation masking is a false-positive reduction only. If it is
        # unavailable, keep the stricter audit rather than silently weakening it.
        audit_content = content or ''
    forbidden_hits = []
    for pattern, hint in _GENERAL_FORBIDDEN_PATTERNS:
        if pattern.search(audit_content):
            forbidden_hits.append(hint)
    if forbidden_hits:
        issues.append(
            "general 內容含裸統計術語 — 請依 hint 白話包裝保留統計資訊與數值，"
            "不要整段刪除統計內容（自動翻譯: scripts/publish_draft.py::sanitize_general；"
            "對照表: feed-publisher SKILL.md『統計表達白話包裝對照表』）: "
            f"{forbidden_hits}"
        )
    return issues


# Depth floors from .claude/rules/publishing.md L98 (chars of body content).
# 2026-07-02 boss escalation: general median length collapsed 4459→2293 chars
# (-49%) May→June while every code gate pushed only in the compress/block
# direction — the prose floors had ZERO code enforcement (and feed-publisher
# SKILL.md even taught 800-1500, below the rule floor). This gate is the
# single code arbiter for the floor, at the same chokepoint as the other
# publish gates. Deterministic → hard-block is allowed per dedup-gate-audit.md
# (fuzzy-only signals must stay warn-only; length/table counts are not fuzzy).
_DEPTH_FLOOR_CHARS = {"general": 1500, "research": 2000}
# Curated / timely formats with their own length conventions are exempt.
_DEPTH_EXEMPT_CONTENT_TYPES = frozenset({"daily_digest", "event_article", "member_qa"})


def _count_md_tables(content: str) -> int:
    """Count markdown table blocks (runs of ≥2 consecutive lines starting with |)."""
    blocks = 0
    run = 0
    for line in (content or "").splitlines():
        if line.lstrip().startswith("|"):
            run += 1
        else:
            if run >= 2:
                blocks += 1
            run = 0
    if run >= 2:
        blocks += 1
    return blocks


def _audit_digest_archive_span(
    details: dict | None,
    published_at: str | None,
    feed: list[dict],
) -> tuple[list[str], list[str]]:
    """Enforce that a daily_digest curates ACROSS THE ARCHIVE, not just recaps
    the last week or two (boss requirement, corrected ≥3× on 2026-07-01, again
    2026-07-05 — the requirement lived only in enqueue_daily_digest.py's prompt
    string with NO governance rule and NO enforcement, so it kept recurring).

    A digest's `details.digest_articles` are its source/evidence articles. If
    they cluster in the last ~2 weeks the digest is a recent-recap, not a
    theme-driven curation from the whole library. We measure the span of the
    source articles' publish dates:
      - span < 14 days                     → BLOCK (recent-recap)
      - span < 45 days OR <2 sources >30d  → WARN  (reach deeper into the archive)

    Fail-open (per .claude/rules/dedup-gate-audit.md): if slugs can't be
    resolved to dates, WARN but never block — a broken lookup must not gap the
    content pipeline. Returns (blocking_issues, warnings).
    """
    try:
        slugs = (details or {}).get("digest_articles") or []
        if not isinstance(slugs, list) or len(slugs) < 2:
            return [], [
                "digest_articles 少於 2 篇或缺失 — 精選導讀應從整庫策展 5-8 篇佐證文章"
            ] if slugs is not None else []
        by_id = {a.get("id"): a for a in feed}
        dates: list[datetime] = []
        unresolved = 0
        for s in slugs:
            a = by_id.get(s)
            pub = (a or {}).get("published_at") if a else None
            if pub:
                try:
                    dates.append(datetime.fromisoformat(str(pub).replace("Z", "+00:00")))
                except ValueError:
                    unresolved += 1
            else:
                unresolved += 1
        if len(dates) < 2:
            return [], [
                f"digest 來源文章日期無法解析（unresolved={unresolved}）— 跳過 archive-span 檢查（fail-open）"
            ]
        try:
            dg_date = datetime.fromisoformat(str(published_at).replace("Z", "+00:00")) if published_at else max(dates)
        except (ValueError, TypeError):
            dg_date = max(dates)
        if dg_date.tzinfo is None:
            dg_date = dg_date.replace(tzinfo=timezone.utc)
        dates = [d if d.tzinfo else d.replace(tzinfo=timezone.utc) for d in dates]
        span_days = (max(dates) - min(dates)).days
        older_than_30 = sum(1 for d in dates if (dg_date - d).days > 30)
        issues: list[str] = []
        warnings: list[str] = []
        if span_days < 14:
            issues.append(
                f"精選導讀來源文章跨度僅 {span_days} 天（全部集中在近兩週）— 這是本週 recap，"
                f"不是跨整庫的主題策展。必須先由時事/宣告/現象訂主題，再從整個 archive 撈佐證文章。"
            )
        elif span_days < 45 or older_than_30 < 2:
            warnings.append(
                f"精選導讀來源跨度 {span_days} 天、僅 {older_than_30} 篇超過 30 天 — 建議更深入 archive "
                f"（whole-library curation，非近期 recap）"
            )
        return issues, warnings
    except Exception as exc:  # noqa: BLE001
        return [], [f"digest archive-span 檢查異常（fail-open）: {exc}"]


def _audit_content_depth(
    audience: str,
    content: str,
    *,
    content_type: str | None = None,
) -> tuple[list[str], list[str]]:
    """Return (blocking_issues, warnings) for the minimum-depth floor.

    Scope: audience 'general' (≥1500 chars) and 'research' (≥2000 chars and
    ≥1 markdown result table). content_type daily_digest / event_article /
    member_qa are exempt (own specs; event is time-critical). general without
    any table is a warning only (lazypack posters may carry the visuals).
    Fail-open on internal errors — a broken depth check must never block.
    """
    try:
        if str(content_type or "").strip() in _DEPTH_EXEMPT_CONTENT_TYPES:
            return [], []
        floor = _DEPTH_FLOOR_CHARS.get(audience)
        if floor is None:
            return [], []
        issues: list[str] = []
        warnings: list[str] = []
        body_len = len((content or "").strip())
        if body_len < floor:
            issues.append(
                f"content depth below floor: {body_len} chars < {floor} "
                f"(audience='{audience}', publishing.md L98). 加深證據鏈（結果表 / "
                f"檢定 / 方法交代 / robustness），不是灌水。"
            )
        tables = _count_md_tables(content or "")
        if audience == "research" and tables < 1:
            issues.append(
                "research article has 0 markdown result tables — 至少 1 張真結果表"
                "（publishing.md §4；讀者需可對表驗證）。"
            )
        elif audience == "general" and tables < 1:
            warnings.append(
                "general article has 0 markdown tables — 建議至少 1 張數據表支撐主論點"
                "（懶人包圖不是可驗證表格）。"
            )
        return issues, warnings
    except Exception as exc:
        try:
            from volpred.ops.diagnostics import warn
            warn("content_depth", "depth audit failed; fail-open", err=str(exc))
        except Exception:
            print(f"  [content_depth] audit failed; fail-open: {exc}")
        return [], []


def _sanitize_publish_tags(audience: str, tags: list[str]) -> list[str]:
    """Canonical last-mile tag sanitizer before writing to feed.

    `publish_draft.py` already caps tags on the CLI path, but direct
    Publisher callers and drift between call sites can still leak over-cap
    tag lists into feed.json. Keep the storage invariant here as the final
    enforcement point:
    - all audiences: cap user-facing tags to `_GENERAL_MAX_TAG_COUNT`
    - general only: drop research/statistical jargon tags that should stay in
      body text, not badges
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = str(raw).strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        if audience == 'general':
            tag_lower = tag.lower()
            if any(
                token in tag_lower
                for token in ('cornish-fisher', 'kupiec', 'harvey', 'qlike', 'dm-test', 'christoffersen')
            ):
                continue
        cleaned.append(tag)
    return cleaned[:_GENERAL_MAX_TAG_COUNT]


# Topic-bound / timely article types are exempt from the 30-day topic-cluster
# cooldown — their repetition is by design (a trending take responds to a live
# event; the daily VIX bulletin is templated). Only discretionary general /
# research articles are cluster-gated. Canonical truth is the content_type /
# audience / category fields; tag & phase are belt-and-suspenders fallbacks for
# older callers that didn't set content_type. (2026-06-28: content_type used to
# only match 'daily_digest', so a trending_repost declared by content_type but
# tagged 台股/波動率 — e.g. K1557 — was wrongly blocked.)
_TIMELY_CONTENT_TYPES = frozenset({
    "daily_digest", "trending_repost", "event_article",
    "member_qa", "daily-update", "daily_update",
})
_TIMELY_TAGS = frozenset({
    "每日建議", "daily-update", "daily_digest", "精選導讀", "會員提問",
    "member_qa", "event_article", "trending_repost", "trending",
})
_TIMELY_PHASE_PREFIXES = ("daily_", "event_", "trending_", "member_")


def cluster_cooldown_type_exempt(
    audience: str | None,
    category: str | None,
    content_type: str | None,
    tags: list[str] | None,
    phase: str | None,
) -> bool:
    """True when the article's TYPE exempts it from the topic-cluster cooldown."""
    tag_set = set(tags or [])
    return (
        (audience or "") in ("daily", "member_qa", "event")
        or (category or "") in ("daily-update", "member_qa", "event_article", "daily_digest")
        or str(content_type or "").strip() in _TIMELY_CONTENT_TYPES
        or bool(tag_set & _TIMELY_TAGS)
        or str(phase or "").startswith(_TIMELY_PHASE_PREFIXES)
    )


class Publisher:
    """Publishes research results to storage/reports/ for Web platform consumption.

    If remote_url is set, also POSTs to a remote API (e.g., Zeabur) for dual publishing.
    """

    # Set this to Zeabur URL to enable dual publishing
    REMOTE_URL = os.environ.get("VOLPRED_REMOTE_URL", get_default_remote_url())

    def __init__(self, storage_dir: str = 'storage'):
        self.reports_dir = Path(storage_dir) / 'reports'
        if not self.reports_dir.exists():
            guard_canonical_write(self.reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._feed_file = self.reports_dir / 'feed.json'

    def _sync_to_remote(self, title: str, description: str = "", phase: str = "", details: dict | None = None):
        """Sync is handled by _sync_feed_to_remote (PUT entire feed.json).
        POST is no longer used to avoid duplicate/ordering conflicts."""
        pass

    def _notify_article_published(self, item: dict, *, reason: str, force_send: bool = False):
        try:
            from volpred.publisher.email_notifier import EmailNotifier

            return EmailNotifier(storage_dir=str(self.reports_dir.parent)).notify_article_published(
                item,
                reason=reason,
                force_send=force_send,
            )
        except Exception as exc:
            print(
                f"  [email_notify] article notification failed for "
                f"{item.get('id', '?')} ({reason}): {exc}"
            )
            return None

    def _record_dead_letter(self, queue_name: str, pub_id: str) -> None:
        """Append ``pub_id`` to a projection dead-letter queue (idempotent)."""
        failed_path = self.reports_dir.parent / queue_name
        try:
            failed = json.loads(failed_path.read_text()) if failed_path.exists() else []
        except Exception as exc:
            print(f"  Failed to read {queue_name}; starting fresh: {exc}")
            failed = []
        if pub_id not in failed:
            failed.append(pub_id)
            guard_canonical_write(failed_path)
            failed_path.write_text(json.dumps(failed))

    def _record_failed_supabase_sync(self, pub_id: str) -> None:
        self._record_dead_letter(".failed_supabase_syncs.json", pub_id)

    def _record_failed_mirror_sync(self, pub_id: str) -> None:
        """Mirror-side dead letter (WS-C1).

        Mirror PUT failures used to be a bare ``print`` (the "401 for a month"
        class). They now land in a queue with the same semantics as the
        Supabase one; WS-C4 wires the shared drain over both queues.
        """
        self._record_dead_letter(".failed_mirror_syncs.json", pub_id)

    def _mirror_article(self, pub_id: str, item: dict) -> bool:
        """PUT one article to the Mirror, dead-lettering a real failure (WS-C4).

        Single exit for "push this article to the Mirror" on the publish and
        unpublish paths, which used to drop :meth:`_sync_report_to_remote`'s
        return value on the floor — a rejected PUT was a bare print, which is
        how a 401 stayed unnoticed for a month.

        A disabled Mirror returns True: nothing was attempted, so nothing
        failed. Dead-lettering it would queue every article on every
        no-remote run and drown the real failures.
        """
        if not self._mirror_enabled():
            return True
        if self._sync_report_to_remote(pub_id, item):
            return True
        self._record_failed_mirror_sync(pub_id)
        print(f"  Mirror sync FAILED for {pub_id} -- recorded to .failed_mirror_syncs.json")
        return False

    def _remote_writes_allowed(self) -> bool:
        """False under the conftest/production kill switch (no network writes)."""
        return os.environ.get("VOLPRED_NO_REMOTE_WRITE") != "1"

    def _mirror_enabled(self) -> bool:
        return bool(self.REMOTE_URL) and self._remote_writes_allowed()

    # Domain-specific compound terms for topic extraction (longest match first)
    _DOMAIN_TERMS = [
        # 4+ char compounds
        '波動率預測', '隔夜跳空', '開盤跳空', '跳空風險', '資產配置', '風險預測',
        '期貨避險', '機器學習', '人工智慧', '深度學習', '計量經濟',
        '恐慌指數', '定期定額', '槓桿策略', '動量策略', '條件槓桿',
        '台指期貨', '波動率', '隔夜風險', '跳空', '隔夜',
        # 3-char terms
        '避險', '預測', '台股', '美股', '期貨', '選擇權',
        '波動', '風險', '策略', '配置', '槓桿', '恐慌',
        '加密', '比特幣', '黃金', '股市', '債券',
        '模型', '回測', '績效', '報酬', '夏普',
    ]

    @staticmethod
    def _tokenize_title(title: str) -> set:
        """Extract meaningful domain keywords from title using dictionary matching + English words.

        Strategy: longest-match dictionary extraction for Chinese domain terms,
        plus lowercase English words (>=2 chars). This avoids the bigram noise problem
        that made Jaccard similarity useless for Chinese titles.
        """
        import re
        tokens = set()

        # 1. Extract English words and well-known acronyms (case-insensitive)
        for word in re.findall(r'[A-Za-z][A-Za-z0-9]+', title):
            w = word.lower()
            if len(w) >= 2:
                tokens.add(w)

        # 2. Extract Chinese domain terms via longest-match
        chinese_text = ''.join(re.findall(r'[\u4e00-\u9fff]+', title))
        remaining = chinese_text
        while remaining:
            matched = False
            for term in Publisher._DOMAIN_TERMS:
                if remaining.startswith(term):
                    tokens.add(term)
                    remaining = remaining[len(term):]
                    matched = True
                    break
            if not matched:
                remaining = remaining[1:]  # skip one char

        # 3. Also extract any Chinese 2-char segments that weren't matched but appear meaningful
        #    (fallback: all unique 2-char substrings from title's Chinese text)
        for phrase in re.findall(r'[\u4e00-\u9fff]{2,}', title):
            for i in range(len(phrase) - 1):
                pair = phrase[i:i+2]
                tokens.add(pair)

        # Remove very common stopwords
        stopwords = {'的了', '了是', '是在', '在和', '和你', '你我', '我這', '這那',
                     '的', '了', '是', '在', '和', '你', '我', '這', '那',
                     '都', '也', '就', '但', '不', '有', '到', '能', '會',
                     '什麼', '為什', '什麼', '怎麼', '可以', '一個', '告訴',
                     '其實', '到底', '真的', '如何', '為何', '為什麼'}
        tokens -= stopwords

        return tokens

    def _find_similar_articles(self, title: str, feed: list, audience: str | None = None) -> list:
        """Find articles with similar topics using domain-keyword overlap.

        Uses two-tier matching:
        1. Domain term overlap: shared domain-specific keywords (weighted 2x)
        2. General token Jaccard similarity

        Threshold: 0.20 (lowered from broken 0.35) for extended reading,
        0.40 for duplicate warning.
        """
        new_tokens = self._tokenize_title(title)
        if not new_tokens:
            return []

        # Only check the most recent 200 articles — duplicates happen within days, not months.
        # feed is already sorted newest-first from _load_feed, but sort defensively.
        recent = sorted(feed, key=lambda x: x.get('published_at') or x.get('created_at', ''), reverse=True)[:200]

        domain_set = set(Publisher._DOMAIN_TERMS)
        new_domain = new_tokens & domain_set

        similar = []
        for existing in recent:
            if existing.get('status') == 'unpublished':
                continue
            # Only compare within same audience
            if audience and existing.get('audience') != audience:
                continue
            ex_tokens = self._tokenize_title(existing.get('title', ''))
            if not ex_tokens:
                continue

            # Also include tags in similarity for better matching
            ex_tags = set(existing.get('tags', []))
            ex_combined = ex_tokens | ex_tags

            ex_domain = ex_tokens & domain_set

            # Weighted Jaccard: domain terms count double
            all_new = new_tokens | new_domain  # domain counted twice
            all_ex = ex_combined | ex_domain
            overlap = len((new_tokens & ex_combined) | (new_domain & ex_domain))
            union = len(all_new | all_ex)
            if union == 0:
                continue

            similarity = overlap / union

            if similarity > 0.15:  # Extended reading threshold
                similar.append({
                    'id': existing.get('id', '?'),
                    'title': existing.get('title', '?'),
                    'similarity': round(similarity, 3),
                    'status': existing.get('status', '?'),
                })

        similar.sort(key=lambda x: -x['similarity'])
        return similar

    def publish_experiment(self, experiment_id: str, title: str,
                          summary: str, metrics: dict,
                          category: str = 'experiment',
                          tags: list[str] | None = None) -> str:
        """Publish an experiment result as a feed item."""
        item = {
            'id': f"pub_{experiment_id}",
            'experiment_id': experiment_id,
            'title': title,
            'summary': summary,
            'category': category,  # 'experiment', 'milestone', 'insight', 'report'
            'metrics': metrics,
            'tags': tags or [],
            'published_at': datetime.now(timezone.utc).isoformat(),
            'status': 'published',
        }

        # Contentlayer pattern (2026-04-18): feed.json is canonical.
        # Individual mile_*.json snapshots are archived to
        # storage/reports/_archive_mile_files/ and no longer written.
        actual_id = self._append_to_feed(item)
        if actual_id != item['id']:
            return actual_id
        self._notify_article_published(item, reason='publish_experiment')

        return item['id']

    def publish_comparison(self, experiment_ids: list[str], title: str,
                          ranking: list[dict], analysis: str,
                          tags: list[str] | None = None) -> str:
        """Publish a model comparison report."""
        import uuid
        pub_id = f"cmp_{uuid.uuid4().hex[:8]}"
        item = {
            'id': pub_id,
            'experiment_ids': experiment_ids,
            'title': title,
            'category': 'comparison',
            'ranking': ranking,
            'analysis': analysis,
            'tags': tags or [],
            'published_at': datetime.now(timezone.utc).isoformat(),
            'status': 'published',
        }

        # Contentlayer pattern: feed.json is canonical; no per-item mile_*.json.
        actual_id = self._append_to_feed(item)
        if actual_id != item['id']:
            return actual_id
        self._sync_to_remote(title, analysis, 'comparison')
        self._notify_article_published(item, reason='publish_comparison')
        return pub_id

    def publish_milestone(self, title: str, description: str,
                         phase: str, details: dict | None = None,
                         tags: list[str] | None = None,
                         status: str = 'published',
                         publish_at: str | None = None,
                         audience: str | None = None,
                         category: str | None = None,
                         proposer: str | None = None,
                         audit_strict: bool = True) -> str:
        """Publish a research milestone.

        audience: 'general' (一般讀者), 'research' (研究), 'daily' (每日建議), 'member_qa'
        category: 'general', 'milestone', 'experiment', 'comparison', 'qa'
        If not provided, auto-detected from tags.
        audit_strict: When True (default) and audience='general', the
            audience-content consistency gate (`_audit_general_content`) raises
            ValueError on issues — K-id tags in user-facing list are
            auto-extracted to details.experiment_refs first, but t-stat /
            Harvey / p-value etc. in content require rewrite. Set False only
            for batch migrations; never for live agent dispatch.
        """
        import uuid
        import re
        # --- Dedupe check: reject exact title + warn similar topics ---
        feed = self._load_feed()

        # --- G1: member_qa publish-time duplicate gate (2026-07-19 STRIKE 2) ---
        # The ONLY gate standing on the reader-visible artifact. Every other
        # member_qa dedup check guards an INTENT step (task creation, question
        # claim) and is therefore skippable by any caller that writes an article
        # by hand — which is exactly how the same member's question got answered
        # twice (mile_d84aa7d0 / mile_0205a444). This one holds even when the
        # entire upstream is bypassed, because nothing becomes reader-visible
        # without passing through publish_milestone. Deliberate sequels pass by
        # naming the prior article(s) in details['supersedes'].
        # Implementation: volpred.ops.content.assert_member_qa_publish_allowed
        # (lazy import — ops.content imports this module at load time).
        if str(status or '') not in ('unpublished', 'retracted') and (
            str(audience or '').strip() == 'member_qa'
            or str(category or '').strip() == 'member_qa'
            or str((details or {}).get('content_type') or '').strip() == 'member_qa'
            or str(phase or '').startswith('member_qa')
        ):
            from volpred.ops.content import assert_member_qa_publish_allowed

            assert_member_qa_publish_allowed(
                (details or {}).get('question_id'),
                feed=feed,
                supersedes=(details or {}).get('supersedes'),
                title=title,
                storage_dir=str(self.reports_dir.parent),
            )
        from datetime import timedelta
        cutoff_exact = datetime.now(timezone.utc) - timedelta(hours=24)
        for existing in feed:
            if existing.get('title') == title:
                existing_time = existing.get('published_at') or existing.get('created_at', '')
                try:
                    from dateutil.parser import parse as dtparse
                    if dtparse(existing_time) > cutoff_exact:
                        print(f"  ⚠️ Duplicate title within 24h: '{title[:50]}' (existing: {existing['id']}). Skipping.")
                        return existing['id']
                except Exception as exc:
                    existing_id = existing.get('id', '?')
                    print(
                        f"  ⚠️ Duplicate title timestamp parse failed: "
                        f"'{title[:50]}' (existing: {existing_id}): {exc}. Skipping."
                    )
                    if existing.get('status') not in {'retracted', 'unpublished'}:
                        return existing_id

        # --- Similar topic check: warn if keyword overlap with existing ---
        similar = self._find_similar_articles(title, feed, audience)

        # --- HARD BLOCK near-duplicates (2026-06-03 fix; K1396 dup incident) ---
        # Previously only exact-title-within-24h blocked; different-title near-dups
        # of the SAME experiment merely WARNED and published anyway (mile_7fbc61c8 +
        # mile_31529fdf, both K1396, 0.48 title-sim, identical opening). Now block:
        #   (a) same experiment_ref AND title-sim > 0.40, OR
        #   (b) title-sim > 0.55 (very high regardless of ref)
        # within the last 14 days. Override with details['dup_waiver']=<reason> for a
        # genuinely differentiated same-topic piece.
        # Canonical K-id refs for the NEW article — extracted once and reused
        # by (1) the near-dup gate, (2) the same-experiment-refs gate, and
        # (3) the narrative-arc gate. Sources: tags (K-id form), explicit
        # details.experiment_refs, and K-ids embedded in title/description.
        import re as _re
        new_refs = set()
        for _t in (tags or []):
            _ts = str(_t).strip()
            if _re.fullmatch(r'[Kk]\d+[a-z]?', _ts):
                new_refs.add('K' + _ts[1:])
        for _r in ((details or {}).get('experiment_refs') or []):
            _rs = str(_r).strip()
            if _re.match(r'^[Kk]\d', _rs):
                new_refs.add('K' + _rs[1:])
        for _m in _re.findall(r'[Kk]\d{2,}[a-z]?', f"{title} {description or ''}"):
            new_refs.add('K' + _m[1:])

        # daily_digest 是 meta-curation：它本來就會引用同主題的多篇舊文，必然與被策展
        # 文章共享 experiment_refs / 標題主題 / narrative arc / entities。對它套用 dup
        # gate 是 false positive（2026-06-23：MOVE-VIX digest 被自己 curate 的來源文章
        # mile_671d4c75 判為 narrative-arc dup 而擋下）。比照 _infer_audience 對 daily_digest
        # 的豁免，這裡也整體豁免三個 dup gate。digest 之間的「同專題重出」改由 daily_digest
        # 自身的 theme-rotation / 主線程選題判斷把關，不靠這組為研究文章設計的 gate。
        _is_digest = str((details or {}).get('content_type') or '') == 'daily_digest'

        _dedup_storage_dir = str(self.reports_dir.parent)

        # --- HARD BLOCK same-experiment-ref recycle (2026-06-19 K1054 ghost
        # incident). mile_bb520db8 byte-for-byte re-published mile_c481c8cf —
        # both K1054, both 'descriptive' (so arc gate skipped them), titles only
        # slightly reworded (so the title-sim near-dup gate missed). The robust
        # signal of a TRUE recycle is same experiment_ref + same audience + a
        # near-identical BODY. 2026-06-23 (boss「沒發文比重複發文嚴重」): require the
        # body-similarity check too — same K with a genuinely different writeup is
        # a legitimate companion/different-angle piece and now PUBLISHES instead
        # of being silently swallowed. This is the ONE remaining hard block; the
        # fuzzy gates below are downgraded to warn+log. Override with dup_waiver.
        if new_refs and not (details or {}).get('dup_waiver') and not _is_digest:
            inferred_aud = _infer_audience(title, description or '', tags or [])
            for existing in feed:
                if existing.get('status') in ('unpublished', 'retracted'):
                    continue
                erefs = set()
                for _r in ((existing.get('details') or {}).get('experiment_refs') or []):
                    _rs = str(_r).strip()
                    if _rs:
                        erefs.add(('K' + _rs[1:]) if _re.match(r'^[Kk]\d', _rs) else _rs.upper())
                shared = new_refs & erefs
                if not shared:
                    continue
                if existing.get('audience') != inferred_aud:
                    continue
                # Same audience + same K. Only block if the BODY is near-identical
                # (a true recycle); otherwise let the companion piece publish.
                body_sim = _dup_body_similarity(
                    title, description,
                    existing.get('title', ''),
                    existing.get('content') or existing.get('description') or '',
                )
                if body_sim >= _RECYCLE_SIM:
                    print(f"  🚫 BLOCKED same-experiment-ref recycle of {existing.get('id')} "
                          f"'{existing.get('title','')[:50]}' (shared_refs={sorted(shared)}, "
                          f"audience={inferred_aud}, body_sim={body_sim:.0%}) — skipping publish. "
                          f"Set details['dup_waiver'] to override or use a different audience.")
                    _log_dedup_decision(_dedup_storage_dir, "block_same_ref_recycle",
                                        title, existing.get('id'),
                                        f"shared_refs={sorted(shared)} aud={inferred_aud} body_sim={body_sim:.2f}")
                    return existing.get('id')
                else:
                    # Same K, different writeup → publish, but record the call so
                    # an over-publishing pattern is auditable (never silent).
                    _log_dedup_decision(_dedup_storage_dir, "allow_same_ref_companion",
                                        title, existing.get('id'),
                                        f"shared_refs={sorted(shared)} aud={inferred_aud} body_sim={body_sim:.2f}")

        # --- WARN-only near-duplicate (title similarity). 2026-06-23: downgraded
        # from HARD BLOCK to warn+log+publish. Title-token similarity is a fuzzy
        # signal with false positives; a true reworded recycle is already caught
        # by the same-ref body-similarity block above. Per boss directive a missed
        # publish is worse than a duplicate, so this only flags for audit.
        if not (details or {}).get('dup_waiver') and not _is_digest:
            cutoff_dup = datetime.now(timezone.utc) - timedelta(days=14)
            for s in similar:
                existing = next((a for a in feed if a.get('id') == s['id']), None)
                if not existing or existing.get('status') in ('unpublished', 'retracted'):
                    continue
                erefs = {str(r).upper() for r in ((existing.get('details') or {}).get('experiment_refs') or [])}
                shared = bool(new_refs & erefs)
                try:
                    from dateutil.parser import parse as dtparse
                    recent = dtparse(existing.get('published_at') or existing.get('created_at', '')) > cutoff_dup
                except Exception:
                    recent = True
                if recent and ((shared and s['similarity'] > 0.40) or s['similarity'] > 0.55):
                    print(f"  ⚠️ NEAR-DUP (warn, publishing anyway) sim={s['similarity']:.0%}, "
                          f"shared_ref={shared} of {s['id']} '{existing.get('title','')[:50]}'.")
                    _log_dedup_decision(_dedup_storage_dir, "warn_near_dup",
                                        title, s['id'],
                                        f"title_sim={s['similarity']:.2f} shared_ref={shared}")
                    break

        # --- WARN-only narrative-arc duplicate. 2026-06-23: downgraded from HARD
        # BLOCK to warn+log+publish. Same-entities/same-conclusion is the gate
        # that false-positived a digest against its own curated source; under the
        # boss directive it must not silently kill a publish. Logged for audit.
        if not (details or {}).get('dup_waiver') and not _is_digest:
            try:
                from volpred.publisher.arc_dedup import (
                    arc_signature,
                    find_arc_duplicates,
                    is_arc_anchorless,
                    is_arc_near_miss,
                )
                arc_matches = find_arc_duplicates(
                    title,
                    description or '',
                    feed,
                    new_refs=new_refs,
                    include_fuzzy=True,
                )
                arc_dups = [m for m in arc_matches if not is_arc_near_miss(m)]
                arc_near_misses = [m for m in arc_matches if is_arc_near_miss(m)]
                if arc_dups:
                    d = arc_dups[0]
                    print(f"  ⚠️ ARC-DUP (warn, publishing anyway) of {d['id']} "
                          f"'{d['title'][:50]}' (shared entities={d['shared_entities']}, "
                          f"conclusion_class={d['conclusion_class']}).")
                    _log_dedup_decision(_dedup_storage_dir, "warn_arc_dup",
                                        title, d['id'],
                                        f"entities={d['shared_entities']} class={d['conclusion_class']}")
                elif arc_near_misses:
                    d = arc_near_misses[0]
                    print(f"  ⚠️ ARC NEAR-MISS (publishing) of {d['id']} "
                          f"'{d['title'][:50]}'; manual 3-layer review required.")
                    _log_dedup_decision(
                        _dedup_storage_dir,
                        "warn_arc_near_miss",
                        title,
                        d['id'],
                        f"reason={d.get('match_reason')} entities={d.get('shared_entities')}",
                    )
                elif is_arc_anchorless(arc_signature(title, description or ''), new_refs):
                    print("  ⚠️ ARC UNJUDGED (publishing) — signature has no "
                          "distinctive entity/ref; manual 3-layer review required.")
                    _log_dedup_decision(
                        _dedup_storage_dir,
                        "warn_arc_unjudged",
                        title,
                        None,
                        "anchorless signature; empty match list is not a clean clearance",
                    )
            except ImportError:
                pass  # silent-ok: optional arc-dedup module; absent → skip arc-dup check

        high_overlap = [s for s in similar if s['similarity'] > 0.30]
        if high_overlap:
            print(f"  ⚠️ HIGH similarity articles found ({len(high_overlap)}) — likely duplicate topic:")
            for s in high_overlap[:3]:
                print(f"    [{s['similarity']:.0%}] {s['id']}: {s['title'][:60]}")
            print(f"  → Consider skipping or differentiating this article significantly.")
        elif similar:
            print(f"  ⚠️ Related articles found ({len(similar)}):")
            for s in similar[:3]:
                print(f"    [{s['similarity']:.0%}] {s['id']}: {s['title'][:60]}")
            print(f"  → Proceeding with publish. 延伸閱讀 will link to these.")
        # Sanitize description
        if isinstance(description, str):
            # Fix double-escaped newlines from various input sources
            description = description.replace('\\n', '\n').replace('\\t', '\t')
            # Remove leaked agent metadata (JSONL fragments from agent output files)
            import re
            metadata_pattern = re.search(r'\{"parentUuid":', description)
            if metadata_pattern:
                description = description[:metadata_pattern.start()].rstrip()
            metadata_pattern = re.search(r'\{"parentToolUseID":', description)
            if metadata_pattern:
                description = description[:metadata_pattern.start()].rstrip()
        # --- Auto-append related articles (延伸閱讀) ---
        if similar and isinstance(description, str):
            related_published = [
                s for s in similar
                if s.get('status') in ('published', 'draft') and s['similarity'] > 0.15
            ][:3]
            if related_published:
                related_section = "\n\n---\n\n### 延伸閱讀\n"
                for s in related_published:
                    related_section += f"- [{s['title']}](/reports/{s['id']})\n"
                # Only append if not already has 延伸閱讀
                if '延伸閱讀' not in description:
                    description += related_section

        # 2026-05-27: topic-cluster cooldown gate. Reader-facing output cannot
        # keep recycling a dominant theme indefinitely; block over-cap cluster
        # publishes unless caller explicitly requests a waiver in details.
        # TYPE-LOCKED EXEMPTIONS (per audience design — same as _infer_audience
        # member_qa/event preservation): daily / member_qa / event / trending_repost
        # are topic-bound by definition; cluster cap would break them. Only
        # discretionary article types (general / research) are cluster-gated.
        description, details = _normalize_publish_assets(
            description,
            details,
            root=_publish_asset_root_from_storage_dir(self.reports_dir.parent),
        )
        details = details or {}
        tag_list_for_cluster = tags or []
        cluster = classify_topic_cluster(title, tag_list_for_cluster, description or "")
        # Determine if this publish is exempt from cluster cooldown:
        # 2026-06-28 fix: content_type was only exempting 'daily_digest', so a
        # correctly-declared trending_repost / event_article whose tags/phase
        # didn't carry the magic token (e.g. K1557, content_type=trending_repost
        # tagged 台股/波動率, phase=research) got cluster-blocked despite the
        # stated intent above ("trending_repost are topic-bound by definition").
        # Exempt ALL topic-bound / timely content_types by the canonical field,
        # not just by incidental tag/phase.
        _ct = str((details or {}).get('content_type') or '').strip()
        is_type_locked = cluster_cooldown_type_exempt(
            audience, category, _ct, tag_list_for_cluster, phase
        )
        cluster_gate = cluster_gate_status(cluster)
        # Defensive .get for soft_cap fields — older stubs / mocked gates may
        # predate the 2026-06-29 soft cap schema and not return them.
        _gate_soft_cap = cluster_gate.get("soft_cap")
        _gate_soft_blocked = bool(cluster_gate.get("soft_blocked"))
        _gate_soft_mult = cluster_gate.get("soft_cap_multiplier")
        if cluster:
            details.setdefault("topic_cluster", cluster)
            topic_30d = {
                "count": cluster_gate["count"],
                "cap": cluster_gate["cap"],
                "ratio": round(cluster_gate["ratio"], 4),
                "exempt": is_type_locked,
            }
            if _gate_soft_cap is not None:
                topic_30d["soft_cap"] = _gate_soft_cap
            details.setdefault("topic_cluster_30d", topic_30d)
        if cluster_gate["blocked"] and not is_type_locked and not details.get("cluster_waiver"):
            _log_dedup_decision(
                str(self.reports_dir.parent),
                "block_cluster_hard_cap",
                title,
                None,
                f"cluster={cluster} count_30d={cluster_gate['count']} cap={cluster_gate['cap']}",
            )
            raise ValueError(
                "topic_cluster_cooldown_blocked: "
                f"cluster={cluster} count_30d={cluster_gate['count']} cap={cluster_gate['cap']}. "
                "Pick another topic or set details['cluster_waiver']=<reason>."
            )
        # 2026-06-29 soft cap (hard_cap × SOFT_CAP_MULTIPLIER): even timely /
        # topic-bound types (event_article / trending_repost / member_qa /
        # daily_*) stop here, because "exempt" was a free pass that let vix grow
        # to 6.1x and spy to 8.3x in 30d (alerts.py cluster_cap_drift, boss
        # escalation 2026-06-29). Real critical events still override via
        # explicit details['cluster_waiver']='<reason>' — same waiver mechanism
        # the hard cap uses. Logged unconditionally so a block is never silent
        # (per .claude/rules/dedup-gate-audit.md).
        if (
            _gate_soft_blocked
            and is_type_locked
            and not details.get("cluster_waiver")
        ):
            _log_dedup_decision(
                str(self.reports_dir.parent),
                "block_cluster_soft_cap",
                title,
                None,
                (
                    f"cluster={cluster} count_30d={cluster_gate['count']} "
                    f"soft_cap={_gate_soft_cap} "
                    f"(hard_cap={cluster_gate['cap']} × {_gate_soft_mult}) "
                    f"content_type={_ct or '?'} audience={audience or '?'}"
                ),
            )
            raise ValueError(
                "topic_cluster_soft_cap_blocked: "
                f"cluster={cluster} count_30d={cluster_gate['count']} "
                f"soft_cap={_gate_soft_cap} (hard_cap×{_gate_soft_mult}). "
                "Even timely / topic-bound types stop here; pick another cluster, "
                "wait for the 30d window to roll, or set details['cluster_waiver']="
                "'<reason>' for a genuinely critical real-world event."
            )

        # --- Pre-publish content-vs-source provenance gate (2026-06-03 3-strike) ---
        # Refactor plan: docs/refactor_plan_prepublish_content_gate.md.
        # Verify cited numbers against cited results.json BEFORE this article goes
        # out (incl. trending "立刻發" — fabrication-grade misses must block
        # regardless of status). Tier-1 deterministic = hard gate (raises iff
        # audit_strict, mirroring _audit_general_content); Tier-2 LLM = warn-only
        # + content_audit_flagged stamp, never blocks.
        content_audit_flagged = False
        try:
            from volpred.publisher.prepublish_audit import audit_content_provenance
            import re as _re_prov
            audit_k_ids: set[str] = set()
            for _t in (tags or []):
                _ts = str(_t).strip()
                if _re_prov.fullmatch(r'[Kk]\d+[a-z]?', _ts):
                    audit_k_ids.add(_ts.upper())
            for _r in ((details or {}).get('experiment_refs') or []):
                _rs = str(_r).strip()
                # Accept K-id refs AND explicitly-declared named experiment dirs
                # (e.g. a member_qa synthesis citing a multi-analysis experiment whose
                # results live at experiments/<ref>/<ref>_results.json). This STRENGTHENS
                # coverage — load_source_values resolves the path and skips if the file is
                # absent, so a junk ref is harmless — letting the content-vs-source gate
                # verify non-K-numbered experiments instead of silently flagging every
                # number as un-sourced. (2026-06-19: member_qa synthesis articles cite a
                # named experiment, not a K-number; previously only [Kk]\d+ refs loaded.)
                if _rs:
                    audit_k_ids.add(_rs.upper())
            for _m in _re_prov.findall(r'[Kk]\d{2,}[a-z]?', f"{title} {description or ''}"):
                audit_k_ids.add(_m.upper())
            # daily_digest exemption (mirrors the dup-gate `_is_digest` bypass and
            # the depth-floor exemption): a digest is meta-curation that cites the
            # numbers of MANY already-published (already-gated) source articles via
            # inline links — it does not reproduce a single experiment's results.json.
            # Auto-extracting the K-ids it mentions in prose (e.g. a footer "涵蓋
            # K575、K1407 等") would force EVERY curated number to appear in those
            # one or two results.json and hard-block a legitimate digest. Provenance
            # for a digest is the cited source articles, verified by the main thread
            # at curation time. Skip the single-experiment gate for digests.
            if _is_digest:
                audit_k_ids = set()
            prov_root = _publish_asset_root_from_storage_dir(self.reports_dir.parent)
            prov = audit_content_provenance(description or '', sorted(audit_k_ids), root=prov_root)
        except Exception as _prov_exc:
            # A bug in the gate must never silently block a legit publish; surface
            # loudly but degrade. BUT a silent degrade is itself dangerous: it
            # reverts to pre-refactor behaviour (fabricated numbers ship) without
            # anyone knowing. So we (a) stamp the article so dashboard/audit see
            # the gate did NOT run, and (b) alert the boss inbox
            # (code-review Issue 6, 2026-06-03).
            print(f"  [prepublish_audit] Tier-1 gate exception (degrading): {_prov_exc}")
            prov = {"tier1_findings": [], "skipped": True, "reason": "gate_exception"}
            content_audit_flagged = True
            try:
                from volpred.ops.alerts import send_alert
                send_alert(
                    level="warn",
                    title="prepublish_audit gate 失效 — 文章未經 content-vs-source 驗證即發佈",
                    body=(
                        f"`publish_milestone` 的 pre-publish content gate 拋出例外並 degrade，"
                        f"文章 `{title[:60]}` 在**未驗證 cited 數字 vs source** 的情況下繼續發佈。\n\n"
                        f"例外：`{_prov_exc}`\n\n"
                        "請檢查 `src/volpred/publisher/prepublish_audit.py` 是否壞掉（3-strike refactor "
                        "`docs/refactor_plan_prepublish_content_gate.md`）。該文已標 `content_audit_flagged=True`。"
                    ),
                    storage_dir=str(self.reports_dir.parent),
                )
            except Exception as _alert_exc:
                print(f"  [prepublish_audit] gate-exception alert failed: {_alert_exc}")

        if prov.get("tier1_findings") and not prov.get("skipped"):
            lines = []
            for f in prov["tier1_findings"]:
                lines.append(f"{f.get('raw')!r} (context: …{f.get('context','')}…)")
            issue_text = '\n  - '.join(lines)
            msg = (
                "pre-publish content-vs-source violations: the following numbers "
                f"are not found in cited sources {sorted(audit_k_ids)}:\n  - {issue_text}\n"
                "Each cited statistic must appear verbatim in the cited results.json "
                "(its fraction/percent form is accepted). DERIVED numbers — a "
                "difference (0.83-0.61=0.22), an average across periods, a ratio — "
                "are NOT in source and will trip this gate: cite the component "
                "values instead, or add the derived value as an explicit results.json "
                "field. Fix the numbers / cite the correct experiment, or set "
                "audit_strict=False (batch migrations only)."
            )
            if audit_strict:
                raise ValueError(msg)
            print(f"  ⚠️ prepublish_audit Tier-1 findings (audit_strict=False bypass):\n  - {issue_text}")

        # --- Pre-publish image-URL gate (2026-06-08 缺圖 incident) ---
        # 20 published articles shipped with image URLs on unserved paths
        # (/experiments/, /api/storage/, /figures/, _PLACEHOLDER, github raw,
        # local abs) → HTTP 404 broken images. Deterministic path-based check:
        # every embedded image must be on a canonical served path (Supabase
        # public storage OR frontend /charts/). Hard gate when audit_strict
        # (mirrors content gate); else warn + stamp. Network-free.
        try:
            from volpred.publisher.prepublish_audit import audit_image_urls
            img_audit = audit_image_urls(description or '')
        except Exception as _img_exc:
            print(f"  [prepublish_audit] image gate exception (degrading): {_img_exc}")
            img_audit = {"broken": [], "total": 0}
            content_audit_flagged = True
        if img_audit.get("broken"):
            img_lines = '\n  - '.join(
                f"{b['url']} ({b['reason']})" for b in img_audit["broken"]
            )
            img_msg = (
                "pre-publish image-URL violations: the following embedded images "
                "are NOT on a canonical served path (must be Supabase public "
                f"storage `/storage/v1/object/public/...` or frontend `/charts/...`):\n  - {img_lines}\n"
                "Upload the PNG to the Supabase article-images bucket "
                "(`from volpred.charts import upload_chart; upload_chart(path)`) and "
                "use the returned public URL. /experiments/ and other repo paths are "
                "NOT served by the frontend → 404 broken images."
            )
            if audit_strict:
                raise ValueError(img_msg)
            content_audit_flagged = True
            print(f"  ⚠️ prepublish_audit image-URL findings (audit_strict=False bypass):\n  - {img_lines}")

        # CJK chart-font gate. An image URL under /article-images/<kid>/ traces back
        # to experiments/<kid>/*.py; if that script draws Chinese without setting a
        # CJK font, every label in the PNG is a tofu box. The CI ratchet catches this
        # too, but only on push — i.e. after the article is already live (k1703,
        # 2026-07-14). Deterministic verdict → hard gate under audit_strict, same
        # shape as the image-URL gate above.
        try:
            from volpred.publisher.prepublish_audit import audit_chart_cjk_fonts
            cjk_audit = audit_chart_cjk_fonts(description or '')
        except Exception as _cjk_exc:
            print(f"  [prepublish_audit] CJK font gate exception (degrading): {_cjk_exc}")
            cjk_audit = {"violations": []}
            content_audit_flagged = True
        if cjk_audit.get("violations"):
            cjk_lines = '\n  - '.join(
                f"{v['path']} ({v['reason']})" for v in cjk_audit["violations"]
            )
            cjk_msg = (
                "pre-publish CJK chart-font violations: the figures embedded in this "
                "article come from scripts that draw Chinese without a CJK font, so "
                "they render as tofu boxes for readers:\n  - "
                f"{cjk_lines}\n"
                "修法：在 savefig 前呼叫 scripts/plot_style.py 的 apply_cjk_style()，"
                "重跑腳本產圖，再用 scripts/upsert_article_image.py 覆蓋線上同名圖檔。"
            )
            if audit_strict:
                raise ValueError(cjk_msg)
            content_audit_flagged = True
            print(f"  ⚠️ prepublish_audit CJK font findings (audit_strict=False bypass):\n  - {cjk_lines}")

        # Chart-path provenance check — warn-only, never blocks (fail-open).
        # Stale/machine-absolute chart refs survive publish as provenance and
        # break future re-publish once the repo path changes (2026-07-02
        # Desktop→home migration audit finding G3).
        try:
            from volpred.publisher.prepublish_audit import audit_details_chart_paths
            chart_path_audit = audit_details_chart_paths(details)
            for _cp_item in chart_path_audit.get("flagged", []):
                print(
                    "  ⚠️ prepublish_audit chart-path finding (warn-only): "
                    f"{_cp_item['where']} = {_cp_item['value']} ({_cp_item['reason']})"
                )
        except Exception as _chart_exc:
            print(f"  [prepublish_audit] chart-path check exception (degrading): {_chart_exc}")

        # Tier-2 LLM conclusion consistency — fully wrapped; never blocks.
        if not prov.get("skipped"):
            try:
                from volpred.publisher.prepublish_audit import (
                    run_llm_consistency_check,
                    load_source_values,
                )
                key_claims = (description or '')[:2000]
                src_vals = sorted(load_source_values(sorted(audit_k_ids), root=prov_root))
                source_summary = (
                    f"cited K-ids: {sorted(audit_k_ids)}; "
                    f"flattened source numeric values (sample): {src_vals[:80]}"
                )
                tier2 = run_llm_consistency_check(key_claims, source_summary)
                if tier2.get("verdict") == "FLAG":
                    content_audit_flagged = True
                    print(
                        "  ⚠️ prepublish_audit Tier-2 FLAG (conclusion-consistency): "
                        f"{tier2.get('contradictions')}"
                    )
            except Exception as _t2_exc:
                print(f"  [prepublish_audit] Tier-2 skipped (degrading): {_t2_exc}")

        pub_id = f"mile_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        normalized_status = status if status in {'published', 'draft', 'scheduled', 'unpublished', 'archived'} else 'published'
        # Determine audience and category — _infer_audience is the enforce mechanism.
        # Caller-supplied audience is only a HINT; inferred value always wins,
        # EXCEPT for type-locked audiences (daily / member_qa / event) which are
        # always preserved (like member_qa/event_article in _infer_audience itself).
        tag_list = tags or []
        explicit_content_type = str(
            (details or {}).get('content_type') or category or ''
        ).strip()
        # 2026-05-27 fix (mile_a91f19be incident): daily preservation.
        # Caller-supplied audience='daily' OR tag-detected '每日建議' / 'daily-update'
        # must skip the academic-keyword inference. daily_update.py boilerplate
        # description always contains GARCH / VaR / Sharpe (≥2 academic keywords)
        # but these articles target retail readers, not researchers.
        is_daily_signal = (
            audience == 'daily'
            or _is_daily_audience_signal(tag_list, explicit_content_type)
        )
        # 2026-06-11 fix (mile_9b76989e incident): member 回答文必含學術詞 →
        # _infer_audience 會強制改 research → badge 變「研究」、不進會員提問 tab。
        # 故 member_qa 必須跳過 inference 保留原 audience。
        # 2026-06-14 fix (mile_6159728d incident): 原條件是 `if proposer:` —— 過廣。
        # proposer 是通用署名欄位（一般文也可 proposer='用戶'/'Claude'），用它當
        # member_qa 的 proxy 會把帶署名的一般讀者文錯分成會員提問。改以「顯式
        # member_qa（audience/category）」判斷；僅保留 proposer-only(無 audience)
        # 的 legacy member_qa 呼叫相容性。
        if explicit_content_type == 'daily_digest':
            audience = audience or 'general'
            category = category or 'general'
        elif (audience == 'member_qa' or category == 'member_qa'
                or (proposer and audience is None)):
            audience = 'member_qa'
            category = 'member_qa'
        elif is_daily_signal:
            audience = 'daily'
        else:
            # 2026-05-26: _infer_audience enforce gate — prevents agents from mis-tagging
            # research-grade content as 'general' (mile_d0d66405 incident).
            inferred = _infer_audience(
                title,
                description or '',
                tag_list,
                content_type=explicit_content_type or category,
            )
            if audience is None:
                audience = inferred
            elif audience != inferred and inferred != 'general':
                # Infer override: log WARN and use inferred result (enforce over discretion)
                print(
                    f"  [_infer_audience] WARN: caller passed audience='{audience}' but "
                    f"content signals infer '{inferred}' — overriding to '{inferred}'. "
                    f"(title='{title[:60]}')"
                )
                audience = inferred
        if category is None:
            if audience == 'general':
                category = 'general'
            elif audience == 'member_qa':
                category = 'member_qa'
            else:
                category = 'milestone'

        # 2026-04-26: enforce single canonical audience badge tag.
        # Strip ALL audience aliases (Chinese / English / variants) regardless
        # of whether they match the desired audience — this prevents the
        # historical bug where ["研究", "general"] or ["研究", "一般讀者"]
        # passed through silently. Then insert exactly one canonical Chinese
        # tag for the article's audience.
        tag_list = [t for t in tag_list if t not in _AUDIENCE_TAG_ALL_ALIASES]
        required_tag = _AUDIENCE_TAG_CANONICAL.get(audience)
        if required_tag:
            tag_list.insert(0, required_tag)

        # 2026-04-26: split K-id tags into details.experiment_refs metadata.
        # K-ids are research-internal references; they pollute frontend tag
        # clouds and confuse general-audience readers. Always extract; never
        # leave K-ids in the user-facing tag list.
        tag_list, experiment_refs = _extract_experiment_refs(tag_list)
        tag_list = _sanitize_publish_tags(audience, tag_list)

        # 2026-04-26: audience-content consistency gate. Audit BEFORE building
        # the item so we fail fast and avoid writing a polluted record.
        audit_issues = _audit_general_content(audience, tag_list, description)
        if audit_issues and audit_strict:
            issue_text = '\n  - '.join(audit_issues)
            raise ValueError(
                f"audience='general' content consistency violations:\n  - {issue_text}\n"
                f"Fix the brief or set audit_strict=False (batch migrations only)."
            )
        elif audit_issues:
            print(f"  ⚠️ general audit issues (audit_strict=False bypass):")
            for issue in audit_issues:
                print(f"     - {issue}")

        # 2026-07-02 (boss): minimum-depth floor — general ≥1500 / research
        # ≥2000 chars + research ≥1 result table (publishing.md L98, previously
        # prose-only with zero code enforcement → May→June general median
        # collapsed -49%). Shares the audit_strict escape; every block/warn is
        # logged to dedup_decisions.jsonl so a non-publish is never silent.
        _depth_ct = str((details or {}).get('content_type') or '')
        depth_issues, depth_warnings = _audit_content_depth(
            audience, description, content_type=_depth_ct or None
        )
        for _dw in depth_warnings:
            print(f"  ⚠️ content depth warning: {_dw}")
        if depth_issues:
            _log_dedup_decision(
                str(self.reports_dir.parent),
                "block_depth_floor" if audit_strict else "warn_depth",
                title, None, "; ".join(depth_issues)[:300],
            )
            if audit_strict:
                issue_text = '\n  - '.join(depth_issues)
                raise ValueError(
                    f"content depth below publish floor:\n  - {issue_text}\n"
                    f"Fix the article (加深證據鏈) or set audit_strict=False (batch migrations only)."
                )
            for issue in depth_issues:
                print(f"  ⚠️ depth issue (audit_strict=False bypass): {issue}")

        # 2026-07-16: enqueue_daily_digest.py already prevents a second daily
        # task, but a direct Publisher call bypassed that lifecycle owner and
        # created two same-day digests (mile_9f5151dc + mile_f9c70bd0). Enforce
        # the invariant again at the universal immediate-publish chokepoint.
        # Drafts/scheduled items remain allowed; uniqueness is reader-visible.
        if _depth_ct == 'daily_digest' and normalized_status == 'published':
            candidate_date = _taipei_publish_date(
                publish_at or datetime.now(timezone.utc).isoformat()
            )
            if candidate_date is not None:
                for existing in feed:
                    existing_details = existing.get('details') or {}
                    existing_date = _taipei_publish_date(
                        existing.get('published_at') or existing.get('created_at')
                    )
                    if (
                        existing.get('status') == 'published'
                        and str(existing_details.get('content_type') or '') == 'daily_digest'
                        and existing_date == candidate_date
                    ):
                        existing_id = str(existing.get('id') or '')
                        _log_dedup_decision(
                            str(self.reports_dir.parent),
                            'block_duplicate_daily_digest',
                            title,
                            existing_id or None,
                            f"Taipei date {candidate_date.isoformat()} already has a published daily_digest",
                        )
                        print(
                            "  ⚠️ Daily digest already published for "
                            f"TPE {candidate_date.isoformat()} (existing: {existing_id}). Skipping."
                        )
                        return existing_id

        # 2026-07-05 (boss): daily_digest must curate ACROSS THE ARCHIVE by a
        # current-event-driven theme, not recap the last week or two. This
        # requirement previously lived only in enqueue_daily_digest.py's prompt
        # (no rule, no gate) and kept recurring. Mechanical gate: source
        # articles' publish-date span must not cluster in the last 2 weeks.
        if _depth_ct == 'daily_digest':
            try:
                _digest_feed = self._load_feed()
            except Exception:  # noqa: BLE001
                _digest_feed = []  # silent-ok: gate fails open below on empty feed
            span_issues, span_warnings = _audit_digest_archive_span(
                details, publish_at or datetime.now(timezone.utc).isoformat(), _digest_feed,
            )
            for _sw in span_warnings:
                print(f"  ⚠️ digest archive-span warning: {_sw}")
            if span_issues:
                _log_dedup_decision(
                    str(self.reports_dir.parent),
                    "block_digest_recap" if audit_strict else "warn_digest_recap",
                    title, None, "; ".join(span_issues)[:300],
                )
                if audit_strict:
                    issue_text = '\n  - '.join(span_issues)
                    raise ValueError(
                        f"daily_digest 是本週 recap 不是跨庫策展:\n  - {issue_text}\n"
                        f"先由時事/宣告/現象訂主題，再從整個 archive 撈佐證；或 audit_strict=False 略過。"
                    )
                for issue in span_issues:
                    print(f"  ⚠️ digest recap issue (audit_strict=False bypass): {issue}")

        # 2026-06-30 (boss): every general-audience reader article must carry a
        # 懶人包圖組 (lazypack) at the end. The publish_draft.py CLI gates this at
        # the file-system stage, but direct Publisher callers (skill §6 Python API)
        # bypass that — enforce here too so the chokepoint is universal. Scope =
        # audience='general' only; daily/event/research/member_qa exempt. Shares
        # the audit_strict escape (batch migrations) with the consistency gate.
        #
        # 2026-07-02 (error_log 15:15 #4): enforcement moved to the
        # reader-visible boundary. Immediate publish (status='published') still
        # blocks here; draft/scheduled creation is allowed without the section —
        # the render runs async on compute_queue (scripts/lazypack_async_render.py
        # enqueue) and the release_pool audit gate holds the flip to published.
        if audience == 'general' and not has_lazypack_section(description):
            if lazypack_required_at(status):
                if audit_strict:
                    raise ValueError(
                        "audience='general' is missing a 懶人包圖組 (lazypack) section.\n"
                        "Per .claude/rules/publishing.md §4 + lazypack-infographic skill, "
                        "immediate-publish reader articles must carry a `## 懶人包圖組` "
                        "section with 2-4 poster-style PNGs (generate from a strict "
                        "data-bound plan via scripts/lazypack_render.py), then retry — OR publish as "
                        "status='draft' and enqueue the async render "
                        "(scripts/lazypack_async_render.py enqueue).\n"
                        "Set audit_strict=False only for genuinely non-reader pieces / batch migrations."
                    )
                print("  ⚠️ lazypack missing (audit_strict=False bypass, status=published)")
            else:
                print(
                    "  [lazypack] general article created without 懶人包圖組 "
                    f"(status={status}) — enqueue the async render now: "
                    "uv run python scripts/lazypack_async_render.py enqueue "
                    "--article-id <mile_id> --experiment <K> --plan <plan.json>; "
                    "release_pool will hold the publish flip until the section lands."
                )

        # Build related_articles list for metadata
        related_articles = []
        if similar:
            related_articles = [
                {'id': s['id'], 'title': s['title'], 'similarity': round(s['similarity'], 2)}
                for s in similar if s.get('status') in ('published', 'draft') and s['similarity'] > 0.2
            ][:5]

        details_clean = {k: v for k, v in (details or {}).items() if k not in ('content', 'description', 'title')}
        # Event dedup can be exact only if every newly published event article
        # carries its canonical identity.  Allowing a live event write without
        # these fields silently pushes the next materializer back to title
        # heuristics — the 2026-07-14 CPI T+0 article was suppressed by an
        # unrelated oil/gold digest whose generic tag happened to say `通膨`.
        # Keep audit_strict=False as the established batch-migration escape, but
        # never permit a normal live event publish to omit structured identity.
        _is_event_article = category == 'event_article' or audience == 'event'
        if _is_event_article:
            _event_fields = ('event_key', 'event_type', 'event_date', 'event_series_slot')
            _missing_event_fields = [
                key for key in _event_fields
                if details_clean.get(key) in (None, '')
            ]
            if _missing_event_fields:
                _event_identity_issue = (
                    "event article is missing canonical metadata: "
                    + ", ".join(_missing_event_fields)
                    + ". Pass the event task payload fields through details so "
                    "future T-series dedup can match event_key/type/date/slot exactly."
                )
                if audit_strict:
                    raise ValueError(_event_identity_issue)
                print(f"  ⚠️ {_event_identity_issue} (audit_strict=False bypass)")
        # 2026-06-18: persist release-layer arc schema for future dedup/backfill.
        # Historical feed entries may lack this and are recomputed on demand by
        # arc_dedup; new writes should carry the schema explicitly.
        _stored_arc_sig = details_clean.get('arc_signature')
        try:
            from volpred.publisher.arc_dedup import (
                ARC_SIGNATURE_SCHEMA_VERSION,
                arc_signature_from_feed_item,
            )
            if (
                not isinstance(_stored_arc_sig, dict)
                or _stored_arc_sig.get('schema_version') != ARC_SIGNATURE_SCHEMA_VERSION
            ):
                details_clean['arc_signature'] = arc_signature_from_feed_item(
                    {
                        'title': title,
                        'content': description or '',
                        'tags': tag_list,
                    }
                )
        except Exception as _arc_sig_exc:
            print(f"  [arc_dedup] arc_signature metadata skipped: {_arc_sig_exc}")
        # 2026-06-11: content_type 強制落地（boss badge-精確性 feedback 的底層修正）。
        # 歷史 1210/1320 篇 details.content_type 為空 → 前端 badge 只能靠 audience 猜。
        # 從本次起每篇必有 content_type：caller 顯式傳的優先，否則由 audience/category 推導。
        if not details_clean.get('content_type'):
            if audience == 'member_qa' or category == 'member_qa':
                details_clean['content_type'] = 'member_qa'
            elif category == 'event_article' or audience == 'event':
                details_clean['content_type'] = 'event_article'
            elif audience == 'daily':
                details_clean['content_type'] = 'daily_update'
            elif audience == 'general':
                details_clean['content_type'] = 'general_article'
            else:
                details_clean['content_type'] = 'research_article'
        # Merge auto-extracted experiment_refs (K-ids removed from tags)
        if experiment_refs:
            existing_refs = details_clean.get('experiment_refs') or []
            if isinstance(existing_refs, list):
                merged = list(dict.fromkeys(existing_refs + experiment_refs))
                details_clean['experiment_refs'] = merged
            else:
                details_clean['experiment_refs'] = experiment_refs
        # Event article metadata is needed by refill/coverage gates as top-level
        # fields, not only nested under details, so reaction coverage can use an
        # exact event match instead of title/tag fuzzy fallback.
        event_metadata = {
            key: details_clean[key]
            for key in ("event_key", "event_type", "event_date", "event_series_slot")
            if details_clean.get(key) not in (None, "")
        }
        item = {
            'id': pub_id,
            'title': title,
            # 2026-06-23: description = short excerpt (not a full-body clone).
            # content holds the canonical full markdown body. See _make_excerpt.
            'description': _make_excerpt(description),
            'content': description,
            'category': category,
            'audience': audience,
            'phase': phase,
            'details': details_clean,
            'tags': tag_list,
            'related_articles': related_articles,
            'created_at': now,
            'published_at': publish_at or now,
            'status': normalized_status,
        }
        item.update(event_metadata)
        if content_audit_flagged:
            # Tier-2 (LLM conclusion-consistency) flagged a possible contradiction.
            # Non-blocking, but visible to dashboard / audit / boss inbox.
            item['content_audit_flagged'] = True
        if proposer:
            item['proposer'] = proposer

        # Contentlayer pattern: feed.json is canonical; no per-item mile_*.json.
        actual_id = self._append_to_feed(item)
        if actual_id != pub_id:
            return actual_id
        self._sync_to_remote(title, description, phase, details)

        # Sync to Supabase DB (so website shows article immediately).
        # K1021 incident (2026-04-30): the previous implementation swallowed
        # the sync_article return value AND swallowed exceptions silently,
        # so a row written as draft to Supabase would never get its
        # status='published' updated when release_pool flipped it. We now
        # capture the boolean return AND treat False as a recordable failure
        # (joins the same .failed_supabase_syncs.json + alerts pipeline as
        # raised exceptions did).
        sync_ok = False
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
            from supabase_sync import sync_article
            sync_ok = bool(sync_article(item, storage_dir=self.reports_dir.parent))
        except Exception as e:
            print(f"  Supabase sync exception for {pub_id}: {e}")
        if not sync_ok:
            self._record_failed_supabase_sync(pub_id)
            print(f"  Supabase sync FAILED for {pub_id} -- recorded to .failed_supabase_syncs.json")

        if normalized_status == 'published':
            self._notify_article_published(item, reason='publish_milestone')

            # 2026-05-19 post-publish live verify gate (Three-Strike fix):
            # 5 articles got published+synced this session but no code verified
            # the public URL resolved → FB pipeline used wrong URL template
            # downstream. We now block "publish success" on actual HTTP 200.
            try:
                from volpred.publisher.live_verify import (
                    verify_article_live,
                    stamp_verified,
                    emit_verify_alert,
                )

                live_ok = verify_article_live(pub_id)
                stamp_verified(item, verified=live_ok)
                # Persist the stamp/flag back to feed.json (the entry was
                # already written by _append_to_feed; rewrite to include the
                # new verify keys).
                self._rewrite_feed_entry(pub_id, item)
                if not live_ok:
                    emit_verify_alert(
                        pub_id,
                        item.get("title"),
                        storage_dir=str(self.reports_dir.parent),
                    )
            except Exception as exc:
                print(f"  [live_verify] exception for {pub_id}: {exc}")

        return pub_id

    def get_feed(self, limit: int = 50, category: str | None = None, include_non_published: bool = False) -> list[dict]:
        """Get feed items, defaulting to published-only for public surfaces."""
        feed = self._load_feed()
        if not include_non_published:
            feed = [f for f in feed if f.get('status', 'published') == 'published']
        if category:
            feed = [f for f in feed if f.get('category') == category]
        # Sort by published_at descending
        feed.sort(key=lambda x: x.get('published_at', ''), reverse=True)
        return feed[:limit]

    def unpublish(self, pub_id: str) -> bool:
        """Mark a publication as unpublished (soft delete)."""
        feed = self._load_feed()
        target_item = None
        for item in feed:
            if item.get('id') == pub_id:
                item['status'] = 'unpublished'
                target_item = item
                break
        if target_item is None:
            return False
        guard_canonical_write(self._feed_file)
        with open(self._feed_file, 'w') as f:
            json.dump(feed, f, indent=2, default=str, ensure_ascii=False)
        self._mirror_article(pub_id, target_item)
        sync_ok = False
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
            from supabase_sync import sync_article
            sync_ok = bool(sync_article(target_item, storage_dir=self.reports_dir.parent))
        except Exception as exc:
            print(f"  Supabase unpublish sync exception for {pub_id}: {exc}")
        if not sync_ok:
            self._record_failed_supabase_sync(pub_id)
            print(f"  Supabase unpublish sync FAILED for {pub_id} -- recorded to .failed_supabase_syncs.json")
        return True

    def _append_to_feed(self, item: dict) -> str:
        # Fail before validation/audit side effects (including writer_log in the
        # finally block) when a test accidentally targets the live feed.
        guard_canonical_write(self._feed_file)
        # Ensure both timestamp fields exist (frontend uses published_at, legacy uses created_at)
        now = datetime.now(timezone.utc).isoformat()
        if 'created_at' not in item:
            item['created_at'] = item.get('published_at', now)
        if 'published_at' not in item:
            item['published_at'] = item.get('created_at', now)
        # Ensure audience/category are set (auto-detect from tags if missing)
        if not item.get('audience'):
            tag_list = item.get('tags', [])
            if '一般讀者' in tag_list:
                item['audience'] = 'general'
            elif '每日建議' in tag_list or 'daily-update' in tag_list:
                item['audience'] = 'daily'
            else:
                item['audience'] = 'research'
        if not item.get('category'):
            if item.get('audience') == 'general':
                item['category'] = 'general'
            elif item.get('audience') == 'member_qa':
                item['category'] = 'member_qa'
            else:
                item['category'] = 'milestone'
        # Ensure audience-specific category tag is present and first
        _audience_tag_map = {
            'general': '一般讀者',
            'research': '研究',
            'daily': '每日建議',
            'member_qa': '會員提問',
        }
        required_tag = _audience_tag_map.get(item.get('audience', ''))
        if required_tag:
            tag_list = item.get('tags', [])
            category_tags = set(_audience_tag_map.values())
            tag_list = [t for t in tag_list if t not in category_tags or t == required_tag]
            if required_tag in tag_list:
                tag_list.remove(required_tag)
            tag_list.insert(0, required_tag)
            item['tags'] = tag_list
        # Ensure content is not empty (use description as fallback)
        if not item.get('content') and item.get('description'):
            item['content'] = item['description']
        # 2026-06-23: base64 data-URI image gate. Extract any inline
        # ![](data:image/...;base64,...) → upload to Supabase → rewrite to URL,
        # so feed.json never accumulates multi-hundred-KB embedded images again.
        # Fail-safe (never blocks a publish). See _extract_base64_images.
        if item.get('content') and 'data:image' in item['content']:
            item['content'] = _extract_base64_images(item['content'], item.get('id', 'unknown'))
        # Auto-escape unescaped statistical-notation pipes inside markdown
        # tables. Architectural fix 2026-04-29: K549 mile_5c662be0 broke
        # frontend table rendering because agent didn't escape `|t|>3.0`
        # (Harvey threshold) inside table cells; pipe count > header count
        # → renderer split row into wrong number of cells. K1018 same-day
        # parallel agent escaped some rows but missed line 28. Behavioral
        # inconsistency proves manual escape unenforceable; sanitize at
        # the canonical write site so feed.json is always clean.
        if item.get('content'):
            # Leaked YAML frontmatter defense (2026-06-24): some writing
            # agents glued their own `---\ntitle: ...\n---` block to the start
            # of the body, so the frontend rendered it as a horizontal rule +
            # literal `audience: general` / `content_type: daily_digest` text
            # (boss saw「排版亂了」). The item's real metadata lives in the feed
            # entry's top-level fields, so a leading frontmatter block is pure
            # leakage. Strip it FIRST, before the table/em-dash sanitizers, so
            # they operate on the real prose. Conservative: only a genuine
            # leading YAML block (or a stray leading `---`) is removed; a
            # mid-article `---` section break is untouched. See
            # frontmatter_stripper for the exact scope.
            from volpred.publisher.frontmatter_stripper import strip_frontmatter

            fm_cleaned, fmrep = strip_frontmatter(item['content'])
            if fmrep.changed:
                item['content'] = fm_cleaned
                print(
                    f"  [feed_publisher] frontmatter_stripper removed leaked "
                    f"frontmatter for {item.get('id', 'unknown')}: "
                    f"{fmrep.summary()}"
                )
            from volpred.publisher.markdown_table_sanitizer import (
                sanitize_markdown_tables,
            )
            sanitized, report = sanitize_markdown_tables(item['content'])
            if report.changed:
                item['content'] = sanitized
                print(
                    f"  [feed_publisher] markdown_table_sanitizer auto-fixed "
                    f"{len(report.fixed_lines)} table row(s) for "
                    f"{item.get('id', 'unknown')}: {report.summary()}"
                )
            if report.has_unfixed:
                # Surface but do not block — caller can decide. The unfixed
                # rows still pass through; renderer may degrade but content
                # is preserved.
                print(
                    f"  [feed_publisher] WARN unfixable table rows for "
                    f"{item.get('id', 'unknown')}: lines={report.unfixed_lines}"
                )
        # Serialize concurrent writers (Claude Code, Codex, cron workers)
        # against feed.json. Lock name follows docs/agent-collab-invariants.md.
        from volpred.ops.shared_lock import shared_state_lock
        from volpred.ops.writer_log import append_writer_log

        storage_dir = str(self.reports_dir.parent)
        result_label = "ok"
        log_record_id = item.get('id')
        try:
            # publishing.md §7: reader-facing published articles must pass
            # anti-ai-style. Deterministic auto-fixes (em-dash/template
            # phrases) happen here; checker failures are warn-only until
            # _ANTI_AI_GATE_STRICT_AFTER, then hard-block. Gate exceptions
            # fail-open with alert + audit trail.
            _run_publish_anti_ai_gate(storage_dir, item, raise_on_block=True)
            with shared_state_lock("publisher_feed", storage_dir=storage_dir):
                feed = self._load_feed()
                # 2026-06-30 boss email-12281: pre-publish throttle gate. The
                # content_quality.py publish_rhythm check was patrol-only —
                # detected bursts but did not prevent them. Reject a discretionary
                # reader-facing publish that would land within RHYTHM_BURST_GAP_MIN
                # of the previous one. Fixtures (digest / daily_update) and event-
                # driven (trending_repost / event_article) bypass via
                # is_rhythm_controlled. See src/volpred/publisher/throttle.py.
                from volpred.publisher.throttle import (
                    PublishThrottleError,
                    check_publish_throttle,
                )

                try:
                    check_publish_throttle(item, feed, storage_dir=storage_dir)
                except PublishThrottleError as throttle_exc:
                    result_label = (
                        f"throttled:prev={throttle_exc.previous_id}:"
                        f"gap={throttle_exc.gap_minutes}min"
                    )[:200]
                    log_record_id = item.get("id")
                    raise
                # 2026-06-23: daily_digest is exempt from the same-experiment-ref
                # gate here too (matching publish_milestone's _is_digest
                # exemptions). A digest curates several past articles and
                # legitimately shares their experiment_refs — without this
                # exemption a digest citing the same K as a source article gets
                # BLOCKED at feed append even after publish_milestone let it
                # through (caught by tests/test_daily_digest_dup_exemption.py).
                _item_is_digest = str((item.get('details') or {}).get('content_type') or '') == 'daily_digest'
                duplicate = None if _item_is_digest else _find_same_ref_feed_duplicate(feed, item)
                if duplicate is not None:
                    existing_id = duplicate.get("id") or item.get("id")
                    result_label = f"duplicate_same_ref:{existing_id}"[:200]
                    log_record_id = existing_id
                    print(
                        "  🚫 BLOCKED same-experiment-ref duplicate at feed append "
                        f"(new={item.get('id')}, existing={existing_id}, "
                        f"refs={sorted(_item_experiment_refs(item) & _item_experiment_refs(duplicate))})"
                    )
                    return str(existing_id)
                # Semantic near-dup WARN (boss email-12139): catches same-topic
                # rehashes the keyword gate above misses. Warn-only + fail-open —
                # never blocks (per dedup-gate-audit fuzzy rule).
                if not _item_is_digest:
                    _semantic_dup_warn(str(self.reports_dir.parent), item, feed)
                feed.append(item)
                # Sort newest first — use published_at (consistent with frontend display)
                feed.sort(key=lambda x: x.get('published_at') or x.get('created_at') or '', reverse=True)
                guard_canonical_write(self._feed_file)
                tmp_file = self._feed_file.with_name(f".{self._feed_file.name}.tmp")
                with open(tmp_file, 'w') as f:
                    json.dump(feed, f, indent=2, default=str, ensure_ascii=False)
                # Post-write sanity: reject if result is not parseable
                with open(tmp_file) as f:
                    json.load(f)
                tmp_file.replace(self._feed_file)
                # Read-back verification: confirm record_id 真的在 persisted feed 裡
                # （2026-05-04 finding #8 修整：tmp_file.replace 雖是 atomic rename，
                # 但 disk fault / partial write / TOCTOU 仍可能讓 item 沒寫進去。
                # K1021 同 pattern — write 回 success ≠ row 真寫入）
                _record_id = item.get('id')
                if _record_id:
                    verify_feed = self._load_feed()
                    if not any(rec.get("id") == _record_id for rec in verify_feed):
                        raise RuntimeError(
                            f"_append_to_feed read-back failed: id={_record_id} "
                            f"not present in persisted feed (entries={len(verify_feed)})"
                        )
                if _record_id:
                    # WS-C4: the MAIN publish path used to drop this return
                    # value (a rejected PUT was a bare print — the "401 for a
                    # month" class). _mirror_article dead-letters the failure
                    # into .failed_mirror_syncs.json for the drain cron.
                    self._mirror_article(str(_record_id), item)
                return str(item.get('id'))
        except Exception as exc:
            result_label = f"error: {type(exc).__name__}: {exc}"[:200]
            raise
        finally:
            append_writer_log(
                subsystem="publisher",
                target="reports/feed.json",
                record_id=log_record_id,
                result=result_label,
                storage_dir=storage_dir,
            )

    def _rewrite_feed_entry(self, pub_id: str, updated_item: dict) -> bool:
        """Replace a single feed entry by id, preserving lock + read-back.

        Used by post-publish gates (live_verify) that mutate an already-appended
        item AFTER _append_to_feed has run. Returns True on success.
        """
        from volpred.ops.shared_lock import shared_state_lock

        storage_dir = str(self.reports_dir.parent)
        with shared_state_lock("publisher_feed", storage_dir=storage_dir):
            feed = self._load_feed()
            found = False
            for idx, entry in enumerate(feed):
                if entry.get("id") == pub_id:
                    feed[idx] = updated_item
                    found = True
                    break
            if not found:
                return False
            guard_canonical_write(self._feed_file)
            tmp_file = self._feed_file.with_name(f".{self._feed_file.name}.tmp")
            with open(tmp_file, 'w') as f:
                json.dump(feed, f, indent=2, default=str, ensure_ascii=False)
            with open(tmp_file) as f:
                json.load(f)
            tmp_file.replace(self._feed_file)
            # Keep the mirror outcome observable to callers (rewrite_and_sync_article
            # dead-letters a failed PUT); the boolean return of this method stays
            # "was the entry found and rewritten", unchanged for existing callers.
            self._last_mirror_ok = (
                bool(self._sync_report_to_remote(pub_id, updated_item))
                if self._mirror_enabled()
                else False
            )
            return True

    def rewrite_and_sync_article(self, pub_id: str, updated_item: dict) -> dict:
        """Single exit for in-place rewrites of an already-published article.

        WS-C1 (refactor_plan_ops_master_2026_07 §3): before this existed, the
        ``publish_draft.py --update`` path wrote feed.json directly and pushed
        neither projection, so a corrected article diverged across feed /
        Supabase / Mirror until somebody remembered to run feed-sync by hand.
        Update and publish now share one gateway:

          1. feed.json rewrite under the ``publisher_feed`` lock (canonical)
          2. Mirror PUT (inside :meth:`_rewrite_feed_entry`)
          3. Supabase ``sync_article`` projection
          4. any projection failure → dead-letter queue (drained by cron)

        Returns a report dict; ``ok`` is False when the canonical write missed
        or a projection failed, so callers can propagate a non-zero exit code.
        """
        report: dict = {
            "id": pub_id,
            "feed_written": False,
            "mirror": "skipped",
            "supabase": "skipped",
            "dead_letters": [],
            "ok": False,
        }
        self._last_mirror_ok = False
        report["feed_written"] = bool(self._rewrite_feed_entry(pub_id, updated_item))
        if not report["feed_written"]:
            return report

        if self._mirror_enabled():
            if self._last_mirror_ok:
                report["mirror"] = "ok"
            else:
                report["mirror"] = "failed"
                self._record_failed_mirror_sync(pub_id)
                report["dead_letters"].append(".failed_mirror_syncs.json")

        if self._remote_writes_allowed():
            sync_ok = False
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
                from supabase_sync import sync_article
                sync_ok = bool(sync_article(updated_item, storage_dir=self.reports_dir.parent))
            except Exception as exc:
                print(f"  Supabase update sync exception for {pub_id}: {exc}")
            if sync_ok:
                report["supabase"] = "ok"
            else:
                report["supabase"] = "failed"
                self._record_failed_supabase_sync(pub_id)
                report["dead_letters"].append(".failed_supabase_syncs.json")

        report["ok"] = not report["dead_letters"]
        return report

    def get_report(self, pub_id: str) -> dict | None:
        # Contentlayer pattern: feed.json is canonical. Read from it only.
        # (Legacy mile_*.json singles are archived; the archive is not a
        # live source and must not be read back from.)
        for item in self._load_feed():
            if item.get("id") == pub_id:
                return item
        return None

    def send_article_notification(self, pub_id: str, *, force_send: bool = False) -> dict:
        article = self.get_report(pub_id)
        if not article:
            return {"found": False, "id": pub_id}
        from volpred.publisher.email_notifier import EmailNotifier

        notification_id = EmailNotifier(storage_dir=str(self.reports_dir.parent)).notify_article_published(
            article,
            reason='manual_resend',
            force_send=force_send,
        )
        return {"found": True, "id": pub_id, "notification_id": notification_id}

    def send_daily_digest(self, *, target_date: date | None = None, force_send: bool = False) -> dict:
        from volpred.publisher.email_notifier import EmailNotifier

        target = target_date or datetime.now(timezone.utc).date()
        articles: list[dict] = []
        for item in self._load_feed():
            if item.get("status", "published") != "published":
                continue
            published_at = item.get("published_at") or item.get("created_at")
            if not isinstance(published_at, str):
                continue
            try:
                published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            except Exception as exc:
                from volpred.ops.diagnostics import warn
                warn(
                    "publisher_published_at_parse",
                    "skip feed item with unparseable published_at",
                    err=str(exc),
                    pub_at=str(published_at)[:40],
                    id=str(item.get("id")),
                )
                continue
            if published_dt.date() != target:
                continue
            full_article = self.get_report(str(item.get("id"))) or item
            articles.append(full_article)

        result = EmailNotifier(storage_dir=str(self.reports_dir.parent)).send_daily_digest(
            articles,
            digest_date=target,
            force_send=force_send,
        )
        result["article_ids"] = [str(article.get("id") or "") for article in articles]
        return result

    def _sync_report_to_remote(self, pub_id: str, item: dict) -> bool:
        """PUT a single article to the remote sync route.

        feed.json remains the local canonical source, but whole-file mirror
        PUTs are too large for the Zeabur/Next.js body limit. The frontend sync
        route already accepts ``reports/<slug>.json`` and revalidates article
        cache tags, so publisher mutations should use this small payload path.
        """
        if not self._mirror_enabled():
            return False
        import time
        import urllib.error
        import urllib.parse
        import urllib.request

        from volpred.mirror_auth import ops_admin_headers

        slug = urllib.parse.quote(str(pub_id), safe="")
        url = f"{self.REMOTE_URL}/api/sync/reports/{slug}.json"
        payload = json.dumps(item, ensure_ascii=False, default=str).encode("utf-8")
        headers = {"Content-Type": "application/json", **ops_admin_headers()}
        last_exc = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers=headers,
                    method="PUT",
                )
                urllib.request.urlopen(req, timeout=10)
                if attempt > 0:
                    print(f"[mirror-sync] article {pub_id} remote sync OK on retry {attempt}")
                return True
            except urllib.error.HTTPError as exc:
                print(f"[mirror-sync] article {pub_id} remote sync FAILED (HTTP {exc.code}): {exc}")
                return False
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        print(f"[mirror-sync] article {pub_id} remote sync FAILED after 3 attempts: {last_exc}")
        return False

    def _sync_feed_to_remote(self):
        """PUT full feed.json to remote for legacy/manual consistency checks."""
        if not self.REMOTE_URL:
            return
        import gzip
        import time
        import urllib.error
        import urllib.request

        from volpred.mirror_auth import ops_admin_headers

        data = self._feed_file.read_bytes()
        # 2026-06-18: the /api/sync/feed.json route handler does
        # ``await request.json()`` — it buffers the ENTIRE body into memory
        # before parsing, and Next.js/Zeabur caps request body size well below
        # feed.json's current footprint (~22MB). Oversized PUTs get reset
        # mid-upload and surface as ``SSL: EOF`` (_ssl.c). If gzip brings the
        # payload back under the ceiling, send Content-Encoding:gzip; otherwise
        # skip this redundant mirror and rely on canonical feed→Supabase sync.
        MAX_MIRROR_BYTES = 8 * 1024 * 1024
        payload = data
        headers = {"Content-Type": "application/json", **ops_admin_headers()}
        if len(data) > MAX_MIRROR_BYTES:
            compressed = gzip.compress(data, compresslevel=6)
            if len(compressed) <= MAX_MIRROR_BYTES:
                payload = compressed
                headers["Content-Encoding"] = "gzip"
                print(
                    f"[mirror-sync] feed.json {len(data) // 1024 // 1024}MB "
                    f"compressed to {len(compressed) // 1024 // 1024}MB for mirror PUT"
                )
            else:
                print(
                    f"[mirror-sync] feed.json {len(data) // 1024 // 1024}MB "
                    f"(gzip {len(compressed) // 1024 // 1024}MB) exceeds "
                    f"whole-file PUT ceiling ({MAX_MIRROR_BYTES // 1024 // 1024}MB) — "
                    f"skipping mirror; Supabase row-by-row sync (feed-sync) is canonical"
                )
                return
        url = f"{self.REMOTE_URL}/api/sync/feed.json"
        # 2026-06-18: transient SSL EOF (_ssl.c) / connection-reset blips were
        # surfacing as hard FAILED even though the mirror endpoint is healthy.
        # Retry network-level errors with backoff; HTTP status errors
        # (401/404/5xx) are NOT transient — surface them immediately, no retry.
        last_exc = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers=headers,
                    method="PUT",
                )
                urllib.request.urlopen(req, timeout=10)
                if attempt > 0:
                    print(f"[mirror-sync] feed.json remote sync OK on retry {attempt}")
                return
            except urllib.error.HTTPError as exc:
                # 2026-06-11: was a bare ``except: pass`` that swallowed a month
                # of 401s after the remote gated /api/sync (C1 fix). Mirror is a
                # replica path (Supabase is canonical) so we don't raise, but we
                # must be loud so silent failures surface in logs/dashboards.
                print(f"[mirror-sync] feed.json remote sync FAILED (HTTP {exc.code}): {exc}")
                return
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        print(f"[mirror-sync] feed.json remote sync FAILED after 3 attempts: {last_exc}")

    def _load_feed(self) -> list[dict]:
        if self._feed_file.exists():
            with open(self._feed_file) as f:
                return json.load(f)
        return []
