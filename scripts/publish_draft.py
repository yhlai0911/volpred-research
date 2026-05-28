"""Publish a markdown draft from storage/drafts/ via volpred ops publish-milestone.

Background: agent-written drafts go to storage/drafts/<kid>_<audience>_draft.md
with YAML frontmatter; main thread runs this helper to sanitize banned terms,
extract metadata, and invoke the publisher CLI. Replaces the per-publish
Python heredoc that we wrote 3+ times manually.

Sanitizer covers the publisher.py L46-52 strict-audit ban list for
audience=general so that agents that "almost" complied still publish cleanly:

  - p=N        → 達顯著水準（p≈N）
  - p<N        → 達顯著水準（p<N）
  - t=N        → 統計強度 N
  - t-stat     → 統計強度
  - \\|t\\|    → 統計強度
  - Harvey     → 嚴格統計
  - Diebold-Mariano (test) → 兩模型比較顯著
  - DM test    → 比較檢定

Sanitizer is NOT applied to audience=research (those terms are required for
academic readers per .claude/skills/feed-publisher/SKILL.md).

## Two modes

### Mode A: NEW publish (default)
  uv run python scripts/publish_draft.py storage/drafts/k1033_general_draft.md \\
      --phase robustness --tags 'garch,refit,robustness,paper-9' --kid K1033

Optional flags:
  --status (default draft) | published | scheduled
  --audience (default from frontmatter) | general | research | daily
  --dry-run  print what would be published, do not call CLI

### Mode B: UPDATE existing article (in-place rewrite)
  uv run python scripts/publish_draft.py storage/drafts/rewrite_xyz.md \\
      --update mile_d716099a \\
      --update-action codex_review_fix \\
      --update-summary "各 number 已加 provenance；Meta capex 修正"

Update path replaces .content (markdown body), preserves
id/created_at/audience/category/phase/tags (unless overridden via flags),
appends an audit-trail entry to .errata (update_action / update_at /
update_summary), and writes to BOTH storage/reports/feed.json (in-place)
and storage/reports/<mile_id>.json. Strict ban-list sanitizer + IMAGE
GATE (≥2 PNG for general/research) still apply. DUPLICATE GATE is
SKIPPED (it's the same article by design).

Update-mode flags:
  --update <mile_id>             required to enter update mode
  --update-action <action>       required (e.g. codex_review_fix, k222b_mc_added)
  --update-summary "<text>"      required (1-3 sentences explaining what changed)
  --update-title "<new title>"   optional (default preserves original)
  --update-description "<text>"  optional SEO snippet override (default auto-
                                 extracts first paragraph from new content)
  --no-update-description        optional preserve existing description verbatim
                                 (rare — for curated SEO meta differing from body)
  --sync-supabase                optional (auto-run feed-sync after patch)

Description sync (2026-05-08, K703 fix):
  Update mode now keeps `description` in sync with `content`. Resolution:
    1. --no-update-description       → preserve old description
    2. --update-description "<text>" → CLI override
    3. frontmatter `description: ""` → frontmatter override
    4. Default                        → first paragraph of new content (≤200 ch)

Update mode does NOT auto-sync to Supabase by default — run
`uv run volpred ops feed-sync --apply` manually, or pass --sync-supabase.
This decouples publish_draft (file-system only) from network ops, matching
new-publish behaviour.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 2026-05-08: HTTPS image-URL enforcement (P2 platform_ops structural fix).
#
# Background: agents wrote drafts with image refs in two patterns:
#   (a) `![chart](https://qxhfg...supabase.co/.../k717_*.png)` — pre-uploaded
#   (b) `![chart](experiments/k547/k547_tom_anomaly_dead.png)` — local relative
#
# Pattern (b) shipped to feed.json broke the frontend (Supabase Storage 404 on
# resolved relative paths). Audit found 101 articles affected; bulk fix repaired
# 60 + 2 residuals (K438 / K681 PNGs already disk-deleted, unrecoverable).
#
# Root cause = agent-level inconsistency (no enforcement at publish time).
# Fix per CLAUDE.md "永遠修流程，不修資料":
#   - Detect every `![alt](path)` ref + `image_url` field in body / frontmatter
#   - https://... and http://... → pass-through (already canonical)
#   - Relative path → resolve (ROOT / path); upload via volpred.charts.upload_chart;
#     replace path with returned HTTPS URL
#   - Local file missing → FAIL the publish with actionable error message
#
# Cache by source path so the same chart appearing N times = upload once.
# Tests: tests/test_publish_draft_image_validation.py
_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
# Inline-style markdown images only: ![alt](path "optional title").
# KNOWN GAP (per 2026-05-08 review MAJ-1): reference-style images
# `![alt][ref]` with `[ref]: url` definitions are NOT matched. Practice
# shows agents universally use inline syntax, so this gap has not surfaced
# in production, but if future drafts use reference syntax with local
# paths the relative path will silently pass through. Document if changing.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _is_http_url(path: str) -> bool:
    """Return True for http(s):// URLs that should pass-through unchanged."""
    return bool(_HTTP_URL_RE.match(path or ""))


def normalize_image_paths(
    text: str,
    root: Path,
    *,
    uploader=None,
    cache: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Rewrite local image refs to HTTPS Supabase URLs in markdown body.

    Walks every `![alt](path)` ref in `text`:
      - If `path` is http(s)://… → keep verbatim
      - If `path` is relative or absolute local file:
          - Resolve (root / path) for relative; use as-is for absolute
          - If the file exists → call uploader(path) → swap path for URL
          - If the file does NOT exist → raise FileNotFoundError with the
            full failed path + alt text in the message so callers can
            actionably fix the draft (re-render the chart or fix the path).

    Args:
        text:     markdown body or any string with `![](…)` refs.
        root:     project root used to resolve relative paths.
        uploader: callable(local_path: str) -> public_url. Defaults to
                  volpred.charts.upload_chart. Tests inject a fake.
        cache:    optional dict[local_path -> uploaded_url] reused across
                  multiple calls (e.g. body + frontmatter image_url) so
                  the same chart referenced N times uploads once. If None,
                  a fresh dict is used per call.

    Returns:
        (rewritten_text, list_of_local_paths_uploaded). The list is the
        ordered set of local refs that were uploaded (deduped, used by
        the CLI summary print so the user sees what changed).

    Raises:
        FileNotFoundError: if any local image path fails to resolve to an
            existing file. The error message includes the failed path
            and surrounding alt-text for actionable triage.
    """
    if uploader is None:
        # Lazy import: keeps test fixtures from needing supabase env vars.
        sys.path.insert(0, str(root / "src"))
        from volpred.charts import upload_chart as _upload_chart
        uploader = _upload_chart
    if cache is None:
        cache = {}

    uploaded: list[str] = []

    def _replace(m: re.Match) -> str:
        alt = m.group(1)
        path = m.group(2).strip()
        if _is_http_url(path):
            return m.group(0)
        # Resolve local path (relative → ROOT / path; absolute → as-is)
        p = Path(path)
        if not p.is_absolute():
            p = root / path
        if not p.exists():
            raise FileNotFoundError(
                f"local image not found: {path} (resolved to {p}). "
                f"Image alt='{alt[:60]}'. Upload the chart to Supabase "
                f"first or fix the relative path. Aborting publish to "
                f"prevent broken images on the frontend."
            )
        if path in cache:
            return f"![{alt}]({cache[path]})"
        url = uploader(str(p))
        cache[path] = url
        if path not in uploaded:
            uploaded.append(path)
        return f"![{alt}]({url})"

    new_text = _MARKDOWN_IMAGE_RE.sub(_replace, text)
    return new_text, uploaded


def normalize_image_url_field(
    image_url: str,
    root: Path,
    *,
    uploader=None,
    cache: dict[str, str] | None = None,
) -> str:
    """Same treatment for an `image_url` scalar (frontmatter / feed field).

    Pass-through if empty or already http(s)://. Local path → upload + return
    URL. Missing file → FileNotFoundError. Uses same cache as body so a
    feature-image referenced from both frontmatter `image_url` and body
    `![](…)` only uploads once.
    """
    if not image_url:
        return image_url
    if _is_http_url(image_url):
        return image_url
    if uploader is None:
        sys.path.insert(0, str(root / "src"))
        from volpred.charts import upload_chart as _upload_chart
        uploader = _upload_chart
    if cache is None:
        cache = {}
    p = Path(image_url)
    if not p.is_absolute():
        p = root / image_url
    if not p.exists():
        raise FileNotFoundError(
            f"local image_url not found: {image_url} (resolved to {p}). "
            f"Upload to Supabase first or fix the path. Aborting publish."
        )
    if image_url in cache:
        return cache[image_url]
    url = uploader(str(p))
    cache[image_url] = url
    return url


GENERAL_BAN_REPLACEMENTS = [
    # IMPORTANT: replacements must NOT regenerate any banned pattern.
    # Earlier bug: `p<\1` and `p≈\1` both contained `p` adjacent to digits
    # which the publisher's `\bp\s*=\s*\d` / `\bp\s*<\s*\d` regex re-flagged.
    # Solution: drop the `p` operator entirely from replacement text.
    (re.compile(r'\bp\s*=\s*(\d[\d.]*)'), r'達顯著水準（顯著性 \1）'),
    (re.compile(r'\bp\s*<\s*(\d[\d.]*)'), r'達顯著水準（顯著性低於 \1）'),
    (re.compile(r'\bt\s*=\s*(-?\d[\d.]*)'), r'統計強度 \1'),
    (re.compile(r'\bHarvey\s+threshold\b'), r'嚴格統計檢驗門檻'),
    (re.compile(r'\bHarvey\b'), r'嚴格統計'),
    (re.compile(r'\bDiebold-Mariano(?:\s+test)?\b'), r'兩模型比較顯著'),
    (re.compile(r'\bDM\s*test\b', re.IGNORECASE), r'比較檢定'),
    (re.compile(r'\\\|t\\\|', re.IGNORECASE), r'統計強度'),
    (re.compile(r'\|t\|'), r'統計強度'),
    (re.compile(r'\bt-stat\b', re.IGNORECASE), r'統計強度'),
    (re.compile(r'bootstrap\s+p[\s_=-]'), r'重抽樣比較'),
]


# 2026-05-08: Citation-context exemption.
#
# Background: the general-audience sanitizer replaces "Harvey" → "嚴格統計"
# and "Diebold-Mariano" → "兩模型比較顯著" to keep articles jargon-free for
# retail readers. But these author surnames also appear in legitimate
# academic citations (e.g. "Erb & Harvey (2013)", "Patton (2011)",
# "Diebold & Mariano (1995)") which the general-audience reader should still
# see — replacing them inside a citation produces nonsensical strings like
# "Erb & 嚴格統計 (2013)" or duplicated "嚴格統計, 嚴格統計, Liu and Zhu".
#
# Fix strategy: detect citation patterns BEFORE running ban-list replacements,
# stash them as opaque placeholders that contain none of the banned tokens,
# run the sanitizer, then restore the original citation strings.
#
# Citation patterns we protect (handles both ASCII parens "(2016)" and
# fullwidth Chinese parens "（2016）" because article bodies mix both):
#   - "Author1, Author2 and Author3 (2016)"  →  Harvey, Liu and Zhu (2016)
#   - "Author1 et al. (2016)"                →  Harvey et al. (2017)
#   - "Author1 & Author2 (1995)"             →  Erb & Harvey (2013)
#   - "Author1 and Author2 (1995)"           →  Diebold and Mariano (1995)
#   - "Author1 (2011)"                       →  Patton (2011)
#   - "Author1, YEAR" (loose, comma-year)    →  Bouman & Jacobsen, 2002
#
# What is NOT protected (intentional):
#   - "Harvey threshold" (no year, no paren) → sanitize as before
#   - "Harvey 的門檻" (no year, descriptive)  → sanitize as before
# Only explicit citation forms (with a 4-digit year + paren or comma) escape.
_CITATION_PATTERNS = [
    # 3+ authors with "and"/"&" connector before final author + 4-digit year
    # e.g. "Harvey, Liu and Zhu (2016)" / "Harvey, Liu, and Zhu（2016）" /
    # "Harvey, Liu & Zhu (2016)" / "Harvey, Liu &amp; Zhu (2016)".
    # K928 footgun (mile_0e16d067 2026-05-08) showed `&` form was unprotected.
    re.compile(
        r'\b[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+'
        r'(?:,\s+[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+)+'
        r',?\s+(?:and|&amp;|&)\s+[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+'
        r'\s*[（(]\s*[12]\d{3}'
        r'(?:[a-z]?)\s*[）)]'
    ),
    # "Author et al. (2016)" / "Author et al.（2016）"
    re.compile(
        r'\b[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+'
        r'\s+et\s+al\.?\s*[（(]\s*[12]\d{3}(?:[a-z]?)\s*[）)]'
    ),
    # "Author1 & Author2 (1995)" / "Author1 and Author2 (1995)"
    re.compile(
        r'\b[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+'
        r'\s+(?:&|and)\s+'
        r'[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+'
        r'\s*[（(]\s*[12]\d{3}(?:[a-z]?)\s*[）)]'
    ),
    # "Author (2011)" — single author, paren year (handles fullwidth parens too)
    re.compile(
        r'\b[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+'
        r'\s*[（(]\s*[12]\d{3}(?:[a-z]?)\s*[）)]'
    ),
    # Comma-year form: "Bouman & Jacobsen, 2002" / "Harvey, 2016"
    # (no parens, looser; require explicit comma + year to avoid false positives)
    re.compile(
        r'\b[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+'
        r'(?:\s+(?:&|and)\s+[A-Z][a-zA-ZÀ-ɏ‘’\'\-]+)?'
        r',\s+[12]\d{3}\b'
    ),
]


def _stash_citations(text: str) -> tuple[str, list[str]]:
    """Replace citation strings with opaque placeholders.

    Returns (stashed_text, citations) where placeholder N maps to citations[N].
    Placeholder format avoids the banned tokens (no "Harvey", no "DM", no "|t|",
    no digits adjacent to "p"/"t"/"=" patterns).
    """
    citations: list[str] = []

    def _replace(m: re.Match) -> str:
        idx = len(citations)
        citations.append(m.group(0))
        # Placeholder: ASCII letters + index. Use unicode private-use chars
        # to make round-trip robust against any sanitizer accidentally touching it.
        return f"CITE{idx:04d}"

    for pat in _CITATION_PATTERNS:
        text = pat.sub(_replace, text)
    return text, citations


def _restore_citations(text: str, citations: list[str]) -> str:
    for idx, original in enumerate(citations):
        text = text.replace(f"CITE{idx:04d}", original)
    return text


def sanitize_general(text: str) -> tuple[str, list[str]]:
    """Apply general-audience ban-list replacements. Return (text, applied_rules).

    Citation-context exemption (2026-05-08): legitimate academic citations
    like "Patton (2011)" or "Erb & Harvey (2013)" are stashed before
    sanitization and restored after, so author surnames (Harvey, Mariano,
    Patton, etc.) survive intact inside citation strings while still being
    sanitized in jargon contexts ("Harvey threshold", "DM test 顯示").
    """
    text, citations = _stash_citations(text)
    applied = []
    for pat, rep in GENERAL_BAN_REPLACEMENTS:
        new = pat.sub(rep, text)
        if new != text:
            applied.append(pat.pattern)
            text = new
    text = _restore_citations(text, citations)
    return text, applied


def extract_description(body: str, max_chars: int = 200) -> str:
    """Extract a plain-text SEO snippet from markdown body.

    Strategy (2026-05-08, K703 mile_6c2bd99e edge case):
      Update mode previously only wrote `art["content"]`, leaving the
      separate `art["description"]` field stale. Some surfaces (frontend
      list views, Supabase row search, social share previews) render
      `description` as the article snippet — so an updated article would
      keep showing the OLD description body. Per CLAUDE.md "永遠修流程，
      不修資料" the publisher script must keep description in sync, not a
      manual per-article patch.

    Extraction rules (skip in this order, take first non-empty paragraph):
      1. Skip H1/H2/H3 markdown headings (`# ...`, `## ...`, `### ...`)
      2. Skip standalone image refs `![alt](url)` lines
      3. Skip blockquote markers (`> ...`) — the `>` prefix is stripped but
         the quoted text is taken as the paragraph (often a TL;DR summary,
         which is exactly what we want for SEO snippet)
      4. Skip metadata like `[提出: X, 執行: Y]` lines
      5. Strip inline image refs `![alt](url)` → empty
      6. Replace inline links `[text](url)` → `text` (preserve readable text)
      7. Strip remaining markdown emphasis markers `**bold**` / `*italic*`
      8. Truncate to max_chars at a sensible boundary (sentence / comma /
         space) and append `…` if truncated

    Returns plain text suitable for SEO meta description / list preview.
    Defaults to empty string if no paragraph found (caller should fall
    back to title or preserve old description).
    """
    if not body:
        return ""

    # Strip inline image refs entirely (they're not readable text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body)
    # Replace inline links with their visible text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Walk lines, find first non-empty paragraph that isn't a heading /
    # metadata / image-only line
    lines = text.splitlines()
    paragraph_lines: list[str] = []
    in_paragraph = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_paragraph:
                break  # End of first paragraph
            continue
        # Skip headings
        if re.match(r"^#{1,6}\s+", stripped):
            if in_paragraph:
                break
            continue
        # Skip metadata-style lines `[提出: ...]` / `[作者: ...]`
        if re.match(r"^\[(提出|作者|執行|Author|Posted)[:：]", stripped):
            if in_paragraph:
                break
            continue
        # Skip horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            if in_paragraph:
                break
            continue
        # Strip blockquote prefix `> ` but keep content
        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
            if not stripped:
                continue
        # Skip empty after blockquote strip
        paragraph_lines.append(stripped)
        in_paragraph = True

    if not paragraph_lines:
        return ""
    snippet = " ".join(paragraph_lines)

    # Strip emphasis markers `**bold**` / `*italic*` / `__bold__` / `_italic_`
    snippet = re.sub(r"\*\*([^*]+)\*\*", r"\1", snippet)
    snippet = re.sub(r"__([^_]+)__", r"\1", snippet)
    snippet = re.sub(r"(?<!\*)\*([^*\s][^*]*[^*\s]|[^*\s])\*(?!\*)", r"\1", snippet)
    snippet = re.sub(r"(?<!_)_([^_\s][^_]*[^_\s]|[^_\s])_(?!_)", r"\1", snippet)
    # Strip backticks `code`
    snippet = re.sub(r"`([^`]+)`", r"\1", snippet)
    # Collapse whitespace
    snippet = re.sub(r"\s+", " ", snippet).strip()

    if len(snippet) <= max_chars:
        return snippet

    # Truncate at a sensible boundary
    # Prefer sentence end (。 / . / ！ / ! / ？ / ?) within last 30% of window
    window_start = int(max_chars * 0.7)
    cut = -1
    for end_char in ("。", "！", "？", ". ", "! ", "? "):
        idx = snippet.rfind(end_char, window_start, max_chars)
        if idx > cut:
            cut = idx + len(end_char)
    if cut > 0:
        return snippet[:cut].rstrip()
    # Fall back to comma / space
    for sep in ("，", ",", " "):
        idx = snippet.rfind(sep, window_start, max_chars)
        if idx > 0:
            return snippet[:idx].rstrip() + "…"
    # Hard truncate
    return snippet[:max_chars].rstrip() + "…"


# 2026-05-08: tag count cap with priority eviction (P3 platform_ops fix).
#
# Background: cross-K general articles routinely listed 6-8 user tags in
# frontmatter + experiment_refs=[K1, K2, K3]. Publisher prepends the
# audience badge tag (`一般讀者` / `研究` / `每日建議`) → final tag count
# could overshoot publisher's `_GENERAL_MAX_TAG_COUNT = 8` audit cap and
# fail the publish. Agents had to manually shrink frontmatter tags to ≤6
# as buffer space — agent-level inconsistency, not a flow-level guarantee.
#
# Per CLAUDE.md "永遠修流程，不修資料": cap is applied here in
# publish_draft.py (single source) before invoking publisher CLI / writing
# feed.json, so the same logic governs both new-publish and --update paths.
#
# Priority order (kept first → evicted last):
#   1. user frontmatter tags  (highest — user-supplied editorial intent)
#   2. audience badge tag     (medium  — categorisation, navigationally important)
#   3. K-id experiment refs   (lowest  — research-internal; publisher strips
#                              these from tags anyway, but eviction here keeps
#                              the pre-publisher cap budget honest)
#
# Eviction is FROM THE END of K-id list (newest K-id evicted first; oldest
# K-id likely the canonical/primary K, preserved). Within user tags / refs
# subgroups, original ordering is preserved.
TAG_CAP = 8
_AUDIENCE_TAG_BY_AUDIENCE = {
    "general": "一般讀者",
    "research": "研究",
    "daily": "每日建議",
    "member_qa": "會員問答",
}


def _cap_tags_with_priority(
    user_tags: list[str],
    audience: str,
    experiment_refs: list[str],
    *,
    max_tags: int = TAG_CAP,
) -> tuple[list[str], dict]:
    """Dedupe + cap tags with priority eviction.

    Builds the final tag list as: user_tags + [audience_tag] + K-id-tags,
    deduping case-insensitively (preserving first occurrence's casing),
    then evicts FROM THE END to fit `max_tags`. K-id refs are appended as
    tags so callers don't need to think about whether the publisher will
    re-extract them — this function gives a single, predictable cap.

    Returns (final_tags, audit) where audit has:
      - input_user: original user_tags
      - input_audience_tag: the audience badge tag inserted (or '')
      - input_kid_tags: K-id ref tags considered
      - evicted: list of evicted tags in eviction order
      - final: final tag list (echoes return value 0)
    """
    audit: dict = {
        "input_user": list(user_tags),
        "input_audience_tag": "",
        "input_kid_tags": [],
        "evicted": [],
        "final": [],
    }

    # Build assembly preserving priority order
    audience_tag = _AUDIENCE_TAG_BY_AUDIENCE.get((audience or "").strip().lower(), "")
    audit["input_audience_tag"] = audience_tag

    # K-id ref tags: only true K-pattern strings are eligible (other refs like
    # 'paper-9' / 'fred-vix' are not user-facing tags so we skip them — the
    # cap applies to what the publisher would receive as `--tags`).
    kid_tags = [r for r in experiment_refs if re.match(r"^K\d", str(r))]
    audit["input_kid_tags"] = list(kid_tags)

    assembled: list[tuple[str, str]] = []  # (priority_class, tag) for trace
    for t in user_tags:
        assembled.append(("user", t))
    if audience_tag:
        assembled.append(("audience", audience_tag))
    for k in kid_tags:
        assembled.append(("kid", k))

    # Dedupe (case-insensitive) preserving first occurrence's casing
    seen: dict[str, int] = {}  # lowered → index in deduped
    deduped: list[tuple[str, str]] = []
    for cls, t in assembled:
        if not t:
            continue
        key = t.strip().lower()
        if not key or key in seen:
            continue
        seen[key] = len(deduped)
        deduped.append((cls, t.strip()))

    # Evict to fit max_tags. Priority order: evict K-id (lowest) first,
    # newest K-id (last) first within K-id group; then audience; then user
    # tags from the END (so earlier user tags survive). This matches the
    # priority spec: user > audience > kid.
    while len(deduped) > max_tags:
        # Find last K-id; if none, fall back to audience; else last user
        kid_indices = [i for i, (cls, _t) in enumerate(deduped) if cls == "kid"]
        if kid_indices:
            evict_idx = kid_indices[-1]
        else:
            audience_indices = [i for i, (cls, _t) in enumerate(deduped) if cls == "audience"]
            if audience_indices:
                evict_idx = audience_indices[-1]
            else:
                # Only user tags left — evict from end
                evict_idx = len(deduped) - 1
        _cls, t = deduped.pop(evict_idx)
        audit["evicted"].append(t)

    final = [t for _cls, t in deduped]
    audit["final"] = list(final)
    return final, audit


def _normalize_refs(refs: list[str]) -> list[str]:
    """Uppercase K-id refs (`k123` → `K123`) and dedupe preserving first occurrence.

    Non-K strings are passed through with original casing (after stripping)
    but still deduped. Empty strings are filtered out. Used by both the
    new-publish merge (`[--kid] + frontmatter_refs`) and the --update merge
    (`existing details.experiment_refs + frontmatter_refs`) paths so that
    cross-K aggregation articles end up with a clean, canonical refs list.
    """
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if r is None:
            continue
        s = str(r).strip()
        if not s:
            continue
        # Normalize K-id pattern: `k123`/`K123`/`k123b` → `K123`/`K123b`
        if re.match(r"^[Kk]\d", s):
            s = "K" + s[1:]
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def parse_draft(path: Path, require_frontmatter: bool = True) -> dict:
    """Extract frontmatter + body from a markdown draft.

    With require_frontmatter=False (used by --update mode where audience /
    title / phase / tags are inherited from existing feed entry), accepts
    body-only drafts and returns empty frontmatter dict.
    """
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        if require_frontmatter:
            raise SystemExit(f"error: no YAML frontmatter in {path}")
        # Body-only draft: return empty fm + full text as body
        return {
            "title": "",
            "audience": "",
            "status_default": "draft",
            "tags": [],
            "experiment_refs": [],
            "description": "",
            "image_url": "",
            "phase": "",
            "body": text.lstrip(),
        }
    fm_block, body = m.group(1), m.group(2).lstrip()

    # Manual two-pass YAML parse: scalar `key: value` pairs + multi-line
    # list form `key:\n  - item1\n  - item2`. PyYAML would be cleaner but
    # we keep the script dependency-light.
    fm: dict[str, object] = {}
    lines = fm_block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if val:
                fm[key] = val
                i += 1
                continue
            # Empty value → look ahead for `  - item` lines
            collected: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                stripped = nxt.lstrip()
                if stripped.startswith("- "):
                    collected.append(stripped[2:].strip().strip('"').strip("'"))
                    j += 1
                elif not nxt.strip():
                    j += 1
                else:
                    break
            if collected:
                fm[key] = collected
            i = j
        else:
            i += 1

    def _list_from(field: str) -> list[str]:
        v = fm.get(field, [])
        if isinstance(v, list):
            return v
        # Inline form: "[a, b, c]"
        s = str(v).strip().strip("[]")
        return [t.strip().strip('"').strip("'") for t in s.split(",") if t.strip()]

    tags = _list_from("tags")
    # Drop any K-id tags — publisher auto-extracts to details.experiment_refs
    tags = [t for t in tags if not re.match(r"^K\d", t)]
    refs = _normalize_refs(_list_from("experiment_refs"))

    description_fm = fm.get("description", "")
    if isinstance(description_fm, list):
        description_fm = " ".join(str(x) for x in description_fm)
    description_fm = str(description_fm).strip().strip('"').strip("'")

    image_url_fm = fm.get("image_url", "")
    if isinstance(image_url_fm, list):
        image_url_fm = image_url_fm[0] if image_url_fm else ""
    image_url_fm = str(image_url_fm).strip().strip('"').strip("'")

    phase_fm = fm.get("phase", "")
    if isinstance(phase_fm, list):
        phase_fm = phase_fm[0] if phase_fm else ""
    phase_fm = str(phase_fm).strip().strip('"').strip("'")

    return {
        "title": fm.get("title", "").strip('"').strip("'"),
        "audience": fm.get("audience", "general"),
        "status_default": fm.get("status", "draft"),
        "tags": tags[:8],  # publisher cap
        "experiment_refs": refs,
        "description": description_fm,
        "image_url": image_url_fm,
        "phase": phase_fm,
        "body": body,
    }


def check_kid_audience_duplicate(kid: str, audience: str) -> list[dict]:
    """Return existing feed articles matching (K-id, audience) where status != unpublished.

    The publisher has no built-in (K-id, audience) dedup — only mile_id
    uniqueness. Without this check, auto-discovered article tasks can
    re-cover the same K twice. (2026-05-04 K518 incident: refilled article
    task re-published a K that already had a general article from a prior
    session.)
    """
    feed_path = ROOT / "storage" / "reports" / "feed.json"
    if not feed_path.exists():
        return []
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    matches = []
    for art in feed:
        if not isinstance(art, dict):
            continue
        if art.get("audience") != audience:
            continue
        if art.get("status") not in ("draft", "published", "scheduled"):
            continue
        details = art.get("details") or {}
        refs = details.get("experiment_refs") if isinstance(details, dict) else []
        if not isinstance(refs, list):
            refs = []
        # Also check title for K-id mention (covers older articles without
        # experiment_refs metadata)
        title = art.get("title", "") or ""
        if kid in refs or re.search(rf"\b{re.escape(kid)}\b", title):
            matches.append({
                "id": art.get("id"),
                "status": art.get("status"),
                "title": title[:80],
            })
    return matches


def check_todo_gate(body: str) -> int:
    """Return 0 if clean, 4 if TODO markers found (and prints to stderr)."""
    todo_inline = re.findall(r"\[TODO 主線程：[^\]]*\]", body)
    todo_heading = re.findall(r"^#+\s*TODO 主線程[：:]", body, re.MULTILINE)
    if todo_inline or todo_heading:
        print(f"\n[publish_draft] TODO GATE: draft contains "
              f"{len(todo_inline)} inline + {len(todo_heading)} heading TODO marker(s):",
              file=sys.stderr)
        for t in todo_inline[:3]:
            print(f"  - {t[:100]}", file=sys.stderr)
        for t in todo_heading[:3]:
            print(f"  - {t}", file=sys.stderr)
        print("\n  Refusing to publish. Replace TODOs with real content "
              "(generate the requested PNG via main thread, or remove the placeholder).",
              file=sys.stderr)
        return 4
    return 0


def check_image_gate(body: str, audience: str, bypass: bool) -> int:
    """Return 0 if pass, 5 if image gate fails. Mirrors publish path enforcement."""
    if bypass or audience not in ('general', 'research'):
        return 0
    image_refs = re.findall(r"!\[[^\]]*\]\([^)]+\)", body)
    if len(image_refs) < 2:
        print(f"\n[publish_draft] IMAGE GATE: audience={audience} requires ≥2 "
              f"markdown images (![…](…)); found {len(image_refs)}.",
              file=sys.stderr)
        for ref in image_refs:
            print(f"  - {ref[:120]}", file=sys.stderr)
        print(f"\n  Per .claude/rules/publishing.md, every published article "
              f"needs 2+ real PNG charts. Generate the charts and embed them "
              f"in a `## 圖表` section, then retry. Use `--no-image-gate` only "
              f"for genuinely text-only commentary (rare).",
              file=sys.stderr)
        return 5
    return 0


def infer_publish_audience(title: str, body: str, publish_tags: list[str]) -> str:
    """Mirror publisher-side audience inference for preflight validation.

    `publish_draft.py` is the last deterministic checkpoint before invoking the
    publisher CLI. If a draft is declared `audience=general` here but the
    publisher would upcast it to `research`, letting the publish proceed creates
    a queue/accounting bug: the `daily_article` task looks succeeded while the
    platform still lacks general-audience coverage for that K. Import the same
    `_infer_audience()` implementation used by Publisher so this script can fail
    early and force the draft to be rewritten in genuinely general language.
    """
    import sys

    src_dir = ROOT / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from volpred.publisher.publisher import _infer_audience  # noqa: WPS433

    return _infer_audience(title, body, publish_tags)


def find_article_in_feed(feed: list, mile_id: str) -> int | None:
    """Return index of article with matching id, else None."""
    for i, art in enumerate(feed):
        if isinstance(art, dict) and art.get("id") == mile_id:
            return i
    return None


def apply_update(args) -> int:
    """In-place rewrite path (--update <mile_id>).

    Steps (per CLAUDE.md '永遠修流程，不修資料' refactor of one-off patch scripts):
      1. Load feed.json + locate mile_id (404 if missing)
      2. Parse draft markdown (frontmatter + body), apply sanitizer if general
      3. Run TODO gate + IMAGE gate (NO dedup gate — same article by design)
      4. Replace .content; optionally .title (--update-title)
      5. Append errata audit-trail fields (update_action / update_at / update_summary)
      6. Write feed.json + storage/reports/<mile_id>.json (parallel single-file)
      7. Optionally invoke feed-sync (--sync-supabase) — default is decoupled
    """
    draft_path = Path(args.draft_path)
    if not draft_path.is_absolute():
        draft_path = ROOT / draft_path
    if not draft_path.exists():
        print(f"error: draft not found: {draft_path}", file=sys.stderr)
        return 1

    mile_id = args.update
    feed_path = ROOT / "storage" / "reports" / "feed.json"
    if not feed_path.exists():
        print(f"error: feed.json not found at {feed_path}", file=sys.stderr)
        return 1

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    idx = find_article_in_feed(feed, mile_id)
    if idx is None:
        print(f"error: mile_id={mile_id} not found in feed.json "
              f"({len(feed)} articles scanned)", file=sys.stderr)
        return 2

    art = feed[idx]
    old_audience = art.get("audience", "general")
    old_title = art.get("title", "")
    old_phase = art.get("phase", "")
    old_tags = art.get("tags", []) or []
    old_content_len = len(art.get("content", "") or "")
    old_description = art.get("description", "") or ""
    old_details = art.get("details") or {}
    if not isinstance(old_details, dict):
        old_details = {}
    old_refs = old_details.get("experiment_refs", []) or []
    if not isinstance(old_refs, list):
        old_refs = []

    # Parse draft (frontmatter optional in update mode — fields inherited)
    info = parse_draft(draft_path, require_frontmatter=False)
    audience = args.audience or info["audience"] or old_audience
    body = info["body"]
    # Merge existing details.experiment_refs + frontmatter experiment_refs
    # (2026-05-08: cross-K aggregation update path needs symmetric merge so
    # rewrites can extend the K-id provenance list, e.g. K703-style article
    # adding a new source K when a follow-up experiment is added). Dedupe
    # preserves first occurrence (existing refs win ordering).
    merged_refs = _normalize_refs(list(old_refs) + info["experiment_refs"])

    # 2026-05-08 P3 platform_ops: re-apply tag cap on update path so growing
    # K-id refs in cross-K rewrites don't push tag count past publisher
    # audit cap. old_tags already contains audience badge from original
    # publish — pass audience='' so we don't double-count it.
    capped_tags_update, tag_audit_update = _cap_tags_with_priority(
        list(old_tags), "", merged_refs, max_tags=TAG_CAP,
    )
    if tag_audit_update["evicted"]:
        print(
            f"[publish_draft] update tag cap: {len(old_tags)} existing "
            f"+ {len(tag_audit_update['input_kid_tags'])} K-id → "
            f"{len(capped_tags_update)} (cap={TAG_CAP}); evicted: "
            f"{tag_audit_update['evicted']}"
        )
    # Note: in update mode we do NOT mutate art['tags'] here — cap is
    # advisory. Tag evictions in update mode are rare (existing article
    # already passed publish-time cap; merged_refs only adds K-ids which
    # publisher strips from tags anyway). Audit print provides visibility.

    # Sanitizer (general only, unless --no-sanitize)
    applied = []
    if audience == "general" and not args.no_sanitize:
        body, applied = sanitize_general(body)

    # 2026-05-08 P2 platform_ops: enforce HTTPS image URLs by auto-uploading
    # any local relative paths in the body BEFORE the image gate runs. This
    # eliminates the agent-level inconsistency that produced 101 broken-image
    # articles (60 fixed, 2 unrecoverable). Skipped under --no-image-gate
    # (text-only commentary) to keep the bypass coherent.
    image_cache: dict[str, str] = {}
    image_uploads: list[str] = []
    new_image_url = info.get("image_url", "") or art.get("image_url", "") or ""
    if not args.no_image_gate:
        try:
            uploader = getattr(args, "_image_uploader", None)
            body, image_uploads = normalize_image_paths(
                body, ROOT, uploader=uploader, cache=image_cache,
            )
            if new_image_url and not _is_http_url(new_image_url):
                new_image_url = normalize_image_url_field(
                    new_image_url, ROOT, uploader=uploader, cache=image_cache,
                )
        except FileNotFoundError as e:
            print(f"\n[publish_draft] IMAGE PATH ERROR: {e}", file=sys.stderr)
            return 6

    # Optional markdown table sanitizer (matches publisher.py behaviour)
    table_fix_count = 0
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from volpred.publisher.markdown_table_sanitizer import sanitize_markdown_tables
        body, report = sanitize_markdown_tables(body)
        # SanitizeReport exposes fixed_lines / unfixed_lines / summary;
        # treat any change as a fix count signal.
        table_fix_count = len(getattr(report, "fixed_lines", []) or [])
    except Exception as e:
        print(f"[publish_draft] table-sanitizer skipped: {e}")

    # Gates
    rc = check_todo_gate(body)
    if rc != 0:
        return rc
    rc = check_image_gate(body, audience, args.no_image_gate)
    if rc != 0:
        return rc

    # Title override (optional)
    new_title = args.update_title if args.update_title else old_title

    # Description sync (2026-05-08, K703 mile_6c2bd99e edge case).
    # Resolution priority (first non-empty wins):
    #   1. --no-update-description flag → preserve old description
    #   2. --update-description "<text>" CLI override
    #   3. frontmatter `description: "..."` field
    #   4. Default: extract first paragraph (≤200 char SEO snippet) from body
    # If the extraction yields empty (rare — pure-image body), preserve old.
    if getattr(args, "no_update_description", False):
        new_description = old_description
        description_source = "preserved (--no-update-description)"
    elif getattr(args, "update_description", None):
        new_description = args.update_description.strip()
        description_source = "cli override (--update-description)"
    elif info.get("description"):
        new_description = info["description"]
        description_source = "frontmatter override"
    else:
        extracted = extract_description(body)
        if extracted:
            new_description = extracted
            description_source = "auto (first paragraph)"
        else:
            new_description = old_description
            description_source = "preserved (no extractable paragraph)"

    # Build errata update
    now_iso = datetime.now(timezone.utc).isoformat()
    errata = art.get("errata") or {}
    if not isinstance(errata, dict):
        errata = {}
    # Preserve audit trail; append new fields
    errata["update_at"] = now_iso
    errata["update_action"] = args.update_action
    errata["update_summary"] = args.update_summary
    # If errata.history list exists, append; else create one for chronological audit
    history = errata.get("update_history")
    if not isinstance(history, list):
        history = []
    history.append({
        "at": now_iso,
        "action": args.update_action,
        "summary": args.update_summary,
        "old_content_chars": old_content_len,
        "new_content_chars": len(body),
        "title_changed": new_title != old_title,
        "description_changed": new_description != old_description,
        "description_source": description_source,
        "image_paths_normalized": len(image_uploads),
        "image_url_changed": new_image_url != art.get("image_url", ""),
    })
    errata["update_history"] = history

    # Pretty-print summary
    print(f"[publish_draft] mode=UPDATE mile_id={mile_id}")
    print(f"[publish_draft] file={draft_path.relative_to(ROOT) if draft_path.is_relative_to(ROOT) else draft_path}")
    print(f"[publish_draft] title={(new_title or '')[:80]}"
          f"{'  (changed)' if new_title != old_title else '  (preserved)'}")
    print(f"[publish_draft] audience={audience} phase={old_phase} (preserved)")
    print(f"[publish_draft] tags={','.join(old_tags)} (preserved)")
    print(f"[publish_draft] content_chars: {old_content_len} -> {len(body)}  "
          f"sanitize_applied={len(applied)}  table_fixes={table_fix_count}")
    desc_changed = "changed" if new_description != old_description else "preserved"
    print(f"[publish_draft] description: {len(old_description)}ch -> {len(new_description)}ch "
          f"({desc_changed}, source={description_source})")
    if new_description != old_description:
        preview = new_description[:120].replace("\n", " ")
        print(f"[publish_draft]   new desc preview: {preview}{'…' if len(new_description) > 120 else ''}")
    if merged_refs != list(old_refs):
        print(f"[publish_draft] details.experiment_refs: {old_refs} -> {merged_refs}")
    else:
        print(f"[publish_draft] details.experiment_refs={merged_refs} (preserved)")
    if image_uploads:
        print(f"[publish_draft] image auto-uploads: {len(image_uploads)} local refs → HTTPS")
        for p in image_uploads:
            print(f"  - {p} → {image_cache[p]}")
    print(f"[publish_draft] errata.update_action={args.update_action}")
    print(f"[publish_draft] errata.update_summary={args.update_summary[:120]}")

    if args.dry_run:
        print("[publish_draft] dry-run: no files written, no CLI invoked")
        return 0

    # Apply patch
    art["content"] = body
    art["description"] = new_description
    art["errata"] = errata
    if new_title != old_title:
        art["title"] = new_title
    # Sync image_url field if frontmatter / body upload produced a canonical URL
    if new_image_url:
        art["image_url"] = new_image_url
    art["last_updated_at"] = now_iso
    # Persist merged experiment_refs (only if frontmatter actually contributed
    # new entries — preserves backwards-compat for update-only-content rewrites
    # that don't touch K provenance).
    if merged_refs != list(old_refs):
        details = art.get("details")
        if not isinstance(details, dict):
            details = {}
        details["experiment_refs"] = merged_refs
        art["details"] = details

    # Write feed.json — serialize with same lock + atomic-swap used by publisher.py
    # to avoid silent data loss on concurrent publisher appends (Codex review P2).
    from volpred.ops.shared_lock import shared_state_lock
    storage_dir = str(feed_path.parent.parent)
    with shared_state_lock("publisher_feed", storage_dir=storage_dir):
        tmp_path = feed_path.with_name(f".{feed_path.name}.tmp")
        tmp_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(feed_path)
    print(f"[publish_draft] wrote {feed_path.relative_to(ROOT)}")

    # Write parallel single-article file
    single_path = ROOT / "storage" / "reports" / f"{mile_id}.json"
    single_path.write_text(
        json.dumps(copy.deepcopy(art), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[publish_draft] wrote {single_path.relative_to(ROOT)}")

    # Optional Supabase sync (decoupled by default)
    if getattr(args, "sync_supabase", False):
        cmd = ["uv", "run", "volpred", "ops", "feed-sync", "--apply"]
        print(f"[publish_draft] running feed-sync: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(f"[publish_draft] feed-sync rc={result.returncode}")
        if result.stdout:
            print(f"[publish_draft] feed-sync stdout: {result.stdout[-400:]}")
        if result.returncode != 0 and result.stderr:
            print(f"[publish_draft] feed-sync stderr: {result.stderr[-400:]}",
                  file=sys.stderr)
            return result.returncode
    else:
        print("[publish_draft] note: Supabase NOT auto-synced. Run "
              "`uv run volpred ops feed-sync --apply` to push.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # 2026-05-08 P3 platform_ops: accept draft path via positional OR --draft.
    # Agent feedback (K852) noted recurring `--draft <path>` typing pattern
    # producing argparse errors. Make positional optional + add --draft alias
    # so both work; prefer --draft if both given.
    parser.add_argument("draft_path", nargs="?", default=None,
                        help="path to markdown draft (relative or absolute); "
                             "alternative: --draft <path>")
    parser.add_argument("--draft", default=None, dest="draft_flag",
                        metavar="PATH",
                        help="path to markdown draft (alias for positional arg; "
                             "wins if both provided)")
    parser.add_argument("--phase", default=None,
                        help="research phase tag (e.g. robustness, tail-risk); "
                             "defaults to 'research' for new publish if "
                             "frontmatter does not specify; ignored for "
                             "--update (inherited from existing article)")
    parser.add_argument("--audience", default=None, help="override frontmatter audience")
    parser.add_argument("--status", default=None,
                        choices=["draft", "published", "scheduled"],
                        help="override frontmatter status")
    parser.add_argument("--tags", default=None,
                        help="comma-separated; overrides frontmatter tags entirely")
    parser.add_argument("--kid", default=None,
                        help="K-id for experiment_refs; overrides frontmatter")
    parser.add_argument("--cluster-waiver", default=None,
                        help="details.cluster_waiver reason used to justify topic cooldown exception")
    parser.add_argument("--no-sanitize", action="store_true",
                        help="skip ban-list sanitizer (default applies for audience=general)")
    parser.add_argument("--force-duplicate", action="store_true",
                        help="bypass (K-id, audience) duplicate gate (use only when "
                             "intentionally publishing a follow-up / errata)")
    parser.add_argument("--no-image-gate", action="store_true",
                        help="bypass ≥2 PNG check (use only for genuinely text-only "
                             "commentary; default enforces .claude/rules/publishing.md)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print metadata + sanitize report; do not invoke CLI")

    # Update-mode flags (mutually exclusive with new-publish path)
    update_group = parser.add_argument_group(
        "update mode",
        "in-place rewrite of an existing article (replaces 3+ one-off patch scripts)",
    )
    update_group.add_argument("--update", default=None, metavar="MILE_ID",
                              help="rewrite article with this mile_id "
                                   "(switches script to update mode)")
    update_group.add_argument("--update-action", default=None, metavar="ACTION",
                              help="audit-trail action label "
                                   "(e.g. codex_review_fix, k222b_mc_added). "
                                   "Required with --update.")
    update_group.add_argument("--update-summary", default=None, metavar="TEXT",
                              help="1-3 sentences describing what changed and why. "
                                   "Required with --update.")
    update_group.add_argument("--update-title", default=None, metavar="TITLE",
                              help="optional title override; default preserves original")
    update_group.add_argument("--update-description", default=None, metavar="TEXT",
                              help="optional SEO description / list-preview snippet "
                                   "override (default auto-extracts first paragraph "
                                   "of new content; use this for hand-curated meta "
                                   "description)")
    update_group.add_argument("--no-update-description", action="store_true",
                              help="preserve existing description verbatim (rare — "
                                   "use only when description is curated SEO meta "
                                   "that intentionally differs from body content)")
    update_group.add_argument("--sync-supabase", action="store_true",
                              help="auto-run `volpred ops feed-sync --apply` after "
                                   "patch (default is decoupled — run manually)")

    args = parser.parse_args()

    # 2026-05-08 P3 platform_ops: resolve draft_path from --draft alias OR
    # positional. --draft wins if both are provided (explicit-flag preference).
    resolved_draft_path = args.draft_flag or args.draft_path
    if not resolved_draft_path:
        print("error: draft path required (positional or --draft <path>)",
              file=sys.stderr)
        return 1
    args.draft_path = resolved_draft_path

    # Mode dispatch
    if args.update:
        # Update mode validation
        missing = []
        if not args.update_action:
            missing.append("--update-action")
        if not args.update_summary:
            missing.append("--update-summary")
        if missing:
            print(f"error: --update requires {' and '.join(missing)}", file=sys.stderr)
            return 1
        if args.update_description and args.no_update_description:
            print("error: --update-description and --no-update-description are "
                  "mutually exclusive", file=sys.stderr)
            return 1
        return apply_update(args)

    # 2026-05-08 P3 platform_ops: --phase no longer mandatory; resolve from
    # frontmatter `phase:` field, then fall back to 'research' default.
    # Frontmatter phase wins over CLI default but CLI explicit --phase wins
    # over frontmatter (CLI is the explicit override surface).
    draft_path = Path(args.draft_path)
    if not draft_path.is_absolute():
        draft_path = ROOT / draft_path
    if not draft_path.exists():
        print(f"error: draft not found: {draft_path}", file=sys.stderr)
        return 1

    info = parse_draft(draft_path)
    # Resolve phase: explicit CLI --phase > frontmatter `phase:` > default
    if args.phase:
        resolved_phase = args.phase
    elif info.get("phase"):
        resolved_phase = info["phase"]
    else:
        resolved_phase = "research"
    args.phase = resolved_phase
    audience = args.audience or info["audience"]
    status = args.status or info["status_default"]
    # Resolve user tag list: --tags overrides frontmatter entirely.
    if args.tags:
        user_tag_list = [t.strip() for t in args.tags.split(",") if t.strip()]
    else:
        user_tag_list = list(info["tags"])
    # Merge --kid (legacy CLI flag) + frontmatter experiment_refs.
    # Prior to 2026-05-08, --kid REPLACED frontmatter refs entirely, which
    # broke cross-K aggregation articles (e.g. K703 listed 7 source K in
    # frontmatter but only K703 survived to details.experiment_refs because
    # the publisher CLI got `--kid K703` from main thread). Per CLAUDE.md
    # "永遠修流程，不修資料" — merge instead of overwrite, dedupe with K-id
    # uppercase normalization (preserve first occurrence so --kid wins
    # ordering when caller put it first).
    refs = _normalize_refs(([args.kid] if args.kid else []) + info["experiment_refs"])

    # 2026-05-08 P3 platform_ops: dedupe + cap final tag count to 8 with
    # priority eviction (user > audience > K-id) so cross-K articles with
    # frontmatter tags + audience prepend + experiment_refs K-ids don't
    # overshoot publisher's _GENERAL_MAX_TAG_COUNT audit cap. The audience
    # badge is added by the publisher itself so we strip it from the
    # `--tags` we pass through (publisher will re-insert exactly one
    # canonical Chinese tag); we assemble it here only for the cap budget.
    # K-id refs stay in details.experiment_refs and must NOT leak into
    # user-facing tags, otherwise publisher._infer_audience will correctly
    # force audience='research' on a draft that was otherwise written for
    # general readers.
    capped_tags, tag_audit = _cap_tags_with_priority(
        user_tag_list, audience, refs, max_tags=TAG_CAP,
    )
    # Drop the audience tag we added — publisher inserts canonical version.
    audience_tag_inserted = tag_audit.get("input_audience_tag", "")
    publish_tag_list = [
        t for t in capped_tags
        if t != audience_tag_inserted and not re.match(r"^K\d", t)
    ]
    tags = ",".join(publish_tag_list)
    if tag_audit["evicted"]:
        print(
            f"[publish_draft] tag cap: {len(tag_audit['input_user'])} user "
            f"+ 1 audience + {len(tag_audit['input_kid_tags'])} K-id → "
            f"{len(capped_tags)} (cap={TAG_CAP}); evicted: {tag_audit['evicted']}"
        )

    body = info["body"]
    applied = []
    if audience == "general" and not args.no_sanitize:
        body, applied = sanitize_general(body)

    # 2026-05-08 P2 platform_ops: enforce HTTPS image URLs in NEW publish path.
    # Same logic as apply_update: parse every ![](path) ref, pass-through
    # https://, auto-upload local files, FAIL if local file missing. Runs
    # BEFORE TODO + IMAGE gates so the gate counts are accurate after rewrite.
    # Skipped under --no-image-gate to keep that bypass coherent.
    image_cache: dict[str, str] = {}
    image_uploads: list[str] = []
    image_url_field = info.get("image_url", "") or ""
    if not getattr(args, "no_image_gate", False):
        try:
            uploader = getattr(args, "_image_uploader", None)
            body, image_uploads = normalize_image_paths(
                body, ROOT, uploader=uploader, cache=image_cache,
            )
            if image_url_field and not _is_http_url(image_url_field):
                image_url_field = normalize_image_url_field(
                    image_url_field, ROOT, uploader=uploader, cache=image_cache,
                )
        except FileNotFoundError as e:
            print(f"\n[publish_draft] IMAGE PATH ERROR: {e}", file=sys.stderr)
            return 6

    # Pre-flight gates — call extracted functions to keep new-publish (main)
    # and update (apply_update) paths in lockstep. Past inline duplication caused
    # divergent gate logic; per 2026-05-08 review (MAJ-2) consolidate to single source.
    rc = check_todo_gate(body)
    if rc != 0:
        return rc
    rc = check_image_gate(body, audience, getattr(args, 'no_image_gate', False))
    if rc != 0:
        return rc

    # 2026-05-29 platform_ops: fail fast when a supposed general-audience draft
    # would be auto-upcast to research by Publisher. Silent upcast polluted the
    # daily_article queue: task marked succeeded, but publication_candidates
    # still saw missing general coverage and kept refilling v2/v3 retries.
    if audience == "general":
        inferred_audience = infer_publish_audience(
            info["title"], body, publish_tag_list,
        )
        if inferred_audience != "general":
            print(
                "\n[publish_draft] AUDIENCE GATE: draft declares audience=general "
                f"but publisher would infer '{inferred_audience}'.",
                file=sys.stderr,
            )
            print(
                "  Refusing to publish. Rewrite the draft in general-reader "
                "language (remove K-id / statistical jargon from title and body) "
                "or intentionally publish it as research.",
                file=sys.stderr,
            )
            return 7

    # 2026-05-08 P3 platform_ops: tolerate /tmp/ and other out-of-repo
    # paths (agents sometimes write drafts to a temp dir before publish).
    file_display = (
        draft_path.relative_to(ROOT)
        if draft_path.is_relative_to(ROOT) else draft_path
    )
    print(f"[publish_draft] file={file_display}")
    print(f"[publish_draft] title={info['title'][:80]}")
    print(f"[publish_draft] audience={audience} status={status} phase={args.phase}")
    print(f"[publish_draft] tags={tags}")
    print(f"[publish_draft] experiment_refs={refs}")
    print(f"[publish_draft] body_chars={len(body)}  sanitize_applied={len(applied)}")
    if applied:
        for p in applied:
            print(f"  - replaced pattern: {p}")
    if image_uploads:
        print(f"[publish_draft] image auto-uploads: {len(image_uploads)} local refs → HTTPS")
        for p in image_uploads:
            print(f"  - {p} → {image_cache[p]}")
    if image_url_field:
        print(f"[publish_draft] image_url={image_url_field[:120]}")

    # Pre-publish dedup gate per (K-id, audience). Skip if --force-duplicate.
    if not args.force_duplicate and refs:
        for kid in refs:
            existing = check_kid_audience_duplicate(kid, audience)
            if existing:
                print(f"\n[publish_draft] DUPLICATE GATE: ({kid}, {audience}) "
                      f"already has {len(existing)} article(s):", file=sys.stderr)
                for m in existing:
                    print(f"  - {m['id']} [{m['status']}] {m['title']}", file=sys.stderr)
                print(f"\n  Refusing to publish. Use --force-duplicate if this is "
                      f"an intentional follow-up / errata.", file=sys.stderr)
                return 3

    if args.dry_run:
        print("[publish_draft] dry-run: not invoking CLI")
        return 0

    details_payload: dict[str, object] = {"experiment_refs": refs}
    if image_url_field:
        # Persist HTTPS image_url so frontend list/share previews use the
        # canonical URL (frontend reads this top-level field). Surfaces that
        # consume `details.image_url` also work via this nested copy.
        details_payload["image_url"] = image_url_field
    if args.cluster_waiver:
        details_payload["cluster_waiver"] = args.cluster_waiver
    cmd = [
        "uv", "run", "volpred", "ops", "publish-milestone",
        "--title", info["title"],
        "--description", body,
        "--phase", args.phase,
        "--audience", audience,
        "--status", status,
        "--tags", tags,
        "--details-json", json.dumps(details_payload),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\n[publish_draft] rc={result.returncode}")
    if result.stdout:
        print(f"[publish_draft] stdout: {result.stdout[-400:]}")
    if result.returncode != 0 and result.stderr:
        print(f"[publish_draft] stderr: {result.stderr[-700:]}", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
