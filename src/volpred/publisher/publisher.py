from __future__ import annotations
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from volpred.config.runtime import get_default_remote_url
from volpred.topic_clusters import classify_topic_cluster, cluster_gate_status


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
_GENERAL_FORBIDDEN_PATTERNS = [
    (re.compile(r'\bt\s*=\s*-?\d'), 't=value (use 「統計顯著」白話)'),
    (re.compile(r'\bp\s*=\s*\d'), 'p=value (use 「達顯著水準」)'),
    (re.compile(r'p\s*[<>]\s*0\.\d'), 'p<X.XX (use 「達顯著水準」)'),
    (re.compile(r'\bHarvey\b'), 'Harvey threshold (use 「嚴格統計檢驗」)'),
    (re.compile(r'\bDiebold-Mariano\b'), 'Diebold-Mariano (use 「兩模型比較顯著」)'),
    (re.compile(r'\bDM\s*test\b', re.IGNORECASE), 'DM test (use 「比較檢定」)'),
    (re.compile(r'\|t\|'), '|t| stat (use 白話)'),
    (re.compile(r'\bt-stat\b', re.IGNORECASE), 't-stat (use 白話)'),
    (re.compile(r'bootstrap\s+p[\s_=-]'), 'bootstrap p (use 白話)'),
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
    3. Title contains K\\d+ regex match → 'research'
    4. title + content + tags combined contain ≥2 academic keywords → 'research'
    5. Default → 'general'

    Academic keyword list: K\\d+, p-value, t-stat, QLIKE, Sharpe, Bonferroni,
    bootstrap, MLE, cointegration, GARCH-X, Harvey, Diebold-Mariano, DM test,
    HAR-RV, GJR-GARCH, EGARCH, GARCH, MCS, VaR.
    """
    # Rule 1 & 2: content_type overrides
    if content_type == 'member_qa':
        return 'member_qa'
    if content_type == 'event_article':
        return 'event'

    # Rule 3: K-id in title → research
    if re.search(r'K\d+', title or ''):
        return 'research'

    # Rule 4: count academic keywords across title + content + tags.
    # Strip image markdown URLs before checking: `![alt](url)` → `![alt]()`.
    # Image filenames often contain K-ids (e.g. k1024_qlike.png) but are not
    # editorial content — counting them as academic jargon would incorrectly
    # upcast legitimate general articles that embed experiment charts.
    _img_url_strip = re.compile(r'!\[([^\]]*)\]\([^)]+\)')
    content_no_img_urls = _img_url_strip.sub(r'![\1]()', content or '')
    combined = ' '.join(filter(None, [title or '', content_no_img_urls, ' '.join(tags or [])]))
    hit_count = 0
    hit_labels: list[str] = []
    seen: set[str] = set()
    for pattern, label in _ACADEMIC_KEYWORDS:
        if label in seen:
            continue
        if pattern.search(combined):
            hit_count += 1
            hit_labels.append(label)
            seen.add(label)
        if hit_count >= _ACADEMIC_KEYWORD_THRESHOLD:
            break

    if hit_count >= _ACADEMIC_KEYWORD_THRESHOLD:
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
    forbidden_hits = []
    for pattern, hint in _GENERAL_FORBIDDEN_PATTERNS:
        if pattern.search(content or ''):
            forbidden_hits.append(hint)
    if forbidden_hits:
        issues.append(
            f"general 內容含禁用統計術語 (SKILL.md L306): {forbidden_hits}"
        )
    return issues


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

class Publisher:
    """Publishes research results to storage/reports/ for Web platform consumption.

    If remote_url is set, also POSTs to a remote API (e.g., Zeabur) for dual publishing.
    """

    # Set this to Zeabur URL to enable dual publishing
    REMOTE_URL = os.environ.get("VOLPRED_REMOTE_URL", get_default_remote_url())

    def __init__(self, storage_dir: str = 'storage'):
        self.reports_dir = Path(storage_dir) / 'reports'
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._feed_file = self.reports_dir / 'feed.json'

    def _sync_to_remote(self, title: str, description: str = "", phase: str = "", details: dict | None = None):
        """Sync is handled by _sync_feed_to_remote (PUT entire feed.json).
        POST is no longer used to avoid duplicate/ordering conflicts."""
        pass

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
        self._append_to_feed(item)
        try:
            from volpred.publisher.email_notifier import EmailNotifier

            EmailNotifier(storage_dir=str(self.reports_dir.parent)).notify_article_published(
                item,
                reason='publish_experiment',
            )
        except Exception:
            pass

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
        self._append_to_feed(item)
        self._sync_to_remote(title, analysis, 'comparison')
        try:
            from volpred.publisher.email_notifier import EmailNotifier

            EmailNotifier(storage_dir=str(self.reports_dir.parent)).notify_article_published(
                item,
                reason='publish_comparison',
            )
        except Exception:
            pass
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
                except Exception:
                    pass

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
        if not (details or {}).get('dup_waiver'):
            import re as _re
            new_refs = set()
            for _t in (tags or []):
                _ts = str(_t).strip()
                if _re.fullmatch(r'[Kk]\d+[a-z]?', _ts):
                    new_refs.add(_ts.upper())
            for _m in _re.findall(r'[Kk]\d{2,}[a-z]?', f"{title} {description or ''}"):
                new_refs.add(_m.upper())
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
                    print(f"  🚫 BLOCKED near-duplicate (sim={s['similarity']:.0%}, shared_ref={shared}) "
                          f"of {s['id']} '{existing.get('title','')[:50]}' — skipping publish. "
                          f"Set details['dup_waiver'] to override.")
                    return s['id']

        # --- HARD BLOCK narrative-arc duplicates (2026-06-10 fix; K1449/K1091
        # incident, 3rd strike of the title-similarity blind spot after K1396).
        # Title-token Jaccard misses "same story, different shell": same asset
        # entities + same conclusion class is a duplicate to the reader even
        # with ~0 title overlap and different experiment refs. 90-day window.
        # Override with details['dup_waiver'] for a genuinely new angle.
        if not (details or {}).get('dup_waiver'):
            try:
                from volpred.publisher.arc_dedup import find_arc_duplicates
                arc_dups = find_arc_duplicates(title, description or '', feed)
                if arc_dups:
                    d = arc_dups[0]
                    print(f"  🚫 BLOCKED narrative-arc duplicate of {d['id']} "
                          f"'{d['title'][:50]}' (shared entities={d['shared_entities']}, "
                          f"conclusion_class={d['conclusion_class']}) — skipping publish. "
                          f"Set details['dup_waiver'] to override.")
                    return d['id']
            except ImportError:
                pass

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
        is_type_locked = (
            audience in ('daily', 'member_qa', 'event')
            or category in ('daily-update', 'member_qa', 'event_article')
            or '每日建議' in tag_list_for_cluster
            or 'daily-update' in tag_list_for_cluster
            or '會員提問' in tag_list_for_cluster
            or 'member_qa' in tag_list_for_cluster
            or 'event_article' in tag_list_for_cluster
            or 'trending_repost' in tag_list_for_cluster
            or 'trending' in tag_list_for_cluster
            or (phase or '').startswith('daily_')
            or (phase or '').startswith('event_')
            or (phase or '').startswith('trending_')
            or (phase or '').startswith('member_')
        )
        cluster_gate = cluster_gate_status(cluster)
        if cluster:
            details.setdefault("topic_cluster", cluster)
            details.setdefault(
                "topic_cluster_30d",
                {
                    "count": cluster_gate["count"],
                    "cap": cluster_gate["cap"],
                    "ratio": round(cluster_gate["ratio"], 4),
                    "exempt": is_type_locked,
                },
            )
        if cluster_gate["blocked"] and not is_type_locked and not details.get("cluster_waiver"):
            raise ValueError(
                "topic_cluster_cooldown_blocked: "
                f"cluster={cluster} count_30d={cluster_gate['count']} cap={cluster_gate['cap']}. "
                "Pick another topic or set details['cluster_waiver']=<reason>."
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
                if _re_prov.fullmatch(r'[Kk]\d+[a-z]?', _rs):
                    audit_k_ids.add(_rs.upper())
            for _m in _re_prov.findall(r'[Kk]\d{2,}[a-z]?', f"{title} {description or ''}"):
                audit_k_ids.add(_m.upper())
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
        # 2026-05-27 fix (mile_a91f19be incident): daily preservation.
        # Caller-supplied audience='daily' OR tag-detected '每日建議' / 'daily-update'
        # must skip the academic-keyword inference. daily_update.py boilerplate
        # description always contains GARCH / VaR / Sharpe (≥2 academic keywords)
        # but these articles target retail readers, not researchers.
        is_daily_signal = (
            audience == 'daily'
            or '每日建議' in tag_list
            or 'daily-update' in tag_list
        )
        if is_daily_signal:
            audience = 'daily'
        else:
            # 2026-05-26: _infer_audience enforce gate — prevents agents from mis-tagging
            # research-grade content as 'general' (mile_d0d66405 incident).
            inferred = _infer_audience(title, description or '', tag_list, content_type=category)
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

        # Build related_articles list for metadata
        related_articles = []
        if similar:
            related_articles = [
                {'id': s['id'], 'title': s['title'], 'similarity': round(s['similarity'], 2)}
                for s in similar if s.get('status') in ('published', 'draft') and s['similarity'] > 0.2
            ][:5]

        details_clean = {k: v for k, v in (details or {}).items() if k not in ('content', 'description', 'title')}
        # Merge auto-extracted experiment_refs (K-ids removed from tags)
        if experiment_refs:
            existing_refs = details_clean.get('experiment_refs') or []
            if isinstance(existing_refs, list):
                merged = list(dict.fromkeys(existing_refs + experiment_refs))
                details_clean['experiment_refs'] = merged
            else:
                details_clean['experiment_refs'] = experiment_refs
        item = {
            'id': pub_id,
            'title': title,
            'description': description,
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
        if content_audit_flagged:
            # Tier-2 (LLM conclusion-consistency) flagged a possible contradiction.
            # Non-blocking, but visible to dashboard / audit / boss inbox.
            item['content_audit_flagged'] = True
        if proposer:
            item['proposer'] = proposer

        # Contentlayer pattern: feed.json is canonical; no per-item mile_*.json.
        self._append_to_feed(item)
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
            failed_path = self.reports_dir.parent / ".failed_supabase_syncs.json"
            try:
                failed = json.loads(failed_path.read_text()) if failed_path.exists() else []
            except Exception:
                failed = []
            if pub_id not in failed:
                failed.append(pub_id)
                failed_path.write_text(json.dumps(failed))
            print(f"  Supabase sync FAILED for {pub_id} -- recorded to .failed_supabase_syncs.json")

        if normalized_status == 'published':
            try:
                from volpred.publisher.email_notifier import EmailNotifier

                EmailNotifier(storage_dir=str(self.reports_dir.parent)).notify_article_published(
                    item,
                    reason='publish_milestone',
                )
            except Exception:
                pass

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
        with open(self._feed_file, 'w') as f:
            json.dump(feed, f, indent=2, default=str, ensure_ascii=False)
        # Contentlayer pattern: no per-item mile_*.json to sync.
        self._sync_feed_to_remote()
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
            from supabase_sync import sync_article
            sync_article(target_item, storage_dir=self.reports_dir.parent)
        except Exception:
            pass
        return True

    def _append_to_feed(self, item: dict):
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
        # Auto-escape unescaped statistical-notation pipes inside markdown
        # tables. Architectural fix 2026-04-29: K549 mile_5c662be0 broke
        # frontend table rendering because agent didn't escape `|t|>3.0`
        # (Harvey threshold) inside table cells; pipe count > header count
        # → renderer split row into wrong number of cells. K1018 same-day
        # parallel agent escaped some rows but missed line 28. Behavioral
        # inconsistency proves manual escape unenforceable; sanitize at
        # the canonical write site so feed.json is always clean.
        if item.get('content'):
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
            # Anti-AI-style landmine 9 defense (2026-05-29): auto-correct
            # over-used CJK appositive em-dashes (「——」/「—」) to commas at the
            # canonical write site. publishing.md §7 mandates anti-ai-style
            # co-run but the publisher had no hard gate — relied on agent
            # self-discipline (validate_anti_ai_style.py: only ~10% of recent
            # articles clean). Conservative: only CJK-flanked appositive dashes
            # are rewritten (fix (b)「改逗號併入主句」, semantically lossless);
            # numeric ranges / Latin compounds / attribution / code / tables
            # are skipped. Same two-layer pattern as markdown_table_sanitizer.
            from volpred.publisher.emdash_normalizer import normalize_emdash

            normalized, emrep = normalize_emdash(item['content'])
            if emrep.changed:
                item['content'] = normalized
                print(
                    f"  [feed_publisher] emdash_normalizer auto-fixed "
                    f"{emrep.replaced} em-dash(es) for "
                    f"{item.get('id', 'unknown')}: {emrep.summary()}"
                )
        # Serialize concurrent writers (Claude Code, Codex, cron workers)
        # against feed.json. Lock name follows docs/agent-collab-invariants.md.
        from volpred.ops.shared_lock import shared_state_lock
        from volpred.ops.writer_log import append_writer_log

        storage_dir = str(self.reports_dir.parent)
        result_label = "ok"
        try:
            with shared_state_lock("publisher_feed", storage_dir=storage_dir):
                feed = self._load_feed()
                feed.append(item)
                # Sort newest first — use published_at (consistent with frontend display)
                feed.sort(key=lambda x: x.get('published_at') or x.get('created_at') or '', reverse=True)
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
                self._sync_feed_to_remote()
        except Exception as exc:
            result_label = f"error: {type(exc).__name__}: {exc}"[:200]
            raise
        finally:
            append_writer_log(
                subsystem="publisher",
                target="reports/feed.json",
                record_id=item.get('id'),
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
            tmp_file = self._feed_file.with_name(f".{self._feed_file.name}.tmp")
            with open(tmp_file, 'w') as f:
                json.dump(feed, f, indent=2, default=str, ensure_ascii=False)
            with open(tmp_file) as f:
                json.load(f)
            tmp_file.replace(self._feed_file)
            self._sync_feed_to_remote()
            return True

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
            except Exception:
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

    def _sync_report_to_remote(self, pub_id: str, item: dict):
        """Deprecated (2026-04-18 Contentlayer cutover): no-op.

        Individual mile_*.json files are no longer canonical. feed.json
        alone is PUT to the remote mirror via _sync_feed_to_remote().
        Kept as a stub so existing callers (content.py release_pool) don't
        break during transition — safe to delete once callers are updated.
        """
        return

    def _sync_feed_to_remote(self):
        """PUT full feed.json to remote for consistency."""
        if not self.REMOTE_URL:
            return
        try:
            import urllib.request

            from volpred.mirror_auth import ops_admin_headers

            data = self._feed_file.read_bytes()
            req = urllib.request.Request(
                f"{self.REMOTE_URL}/api/sync/feed.json",
                data=data,
                headers={"Content-Type": "application/json", **ops_admin_headers()},
                method="PUT",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as exc:
            # 2026-06-11: was a bare ``except: pass`` that swallowed a month of
            # 401s after the remote gated /api/sync (C1 fix). Mirror is a
            # replica path (Supabase is canonical) so we don't raise, but we
            # must be loud so silent failures surface in logs/dashboards.
            print(f"[mirror-sync] feed.json remote sync FAILED: {exc}")

    def _load_feed(self) -> list[dict]:
        if self._feed_file.exists():
            with open(self._feed_file) as f:
                return json.load(f)
        return []
