from __future__ import annotations
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from volpred.config.runtime import get_default_remote_url


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
        high_overlap = [s for s in similar if s['similarity'] > 0.30]
        if high_overlap:
            print(f"  🚫 HIGH similarity articles found ({len(high_overlap)}) — likely duplicate topic:")
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

        pub_id = f"mile_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        normalized_status = status if status in {'published', 'draft', 'scheduled', 'unpublished', 'archived'} else 'published'
        # Determine audience and category — explicit params take priority
        tag_list = tags or []
        if audience is None:
            if '一般讀者' in tag_list:
                audience = 'general'
            elif '每日建議' in tag_list or 'daily-update' in tag_list:
                audience = 'daily'
            else:
                audience = 'research'
                # 2026-04-14: warn when auto-classify falls through to research default
                # Common bug: general-intent article missed explicit audience='general'
                print(f"  ⚠️ audience auto-defaulted to 'research' for title='{title[:50]}...'. If this is a general-reader article, explicitly pass audience='general'.")
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
        if proposer:
            item['proposer'] = proposer

        # Contentlayer pattern: feed.json is canonical; no per-item mile_*.json.
        self._append_to_feed(item)
        self._sync_to_remote(title, description, phase, details)

        # Sync to Supabase DB (so website shows article immediately)
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
            from supabase_sync import sync_article
            sync_article(item, storage_dir=self.reports_dir.parent)
        except Exception as e:
            # Record failed sync with error for later diagnosis
            failed_path = self.reports_dir.parent / ".failed_supabase_syncs.json"
            failed = json.loads(failed_path.read_text()) if failed_path.exists() else []
            failed.append(pub_id)
            failed_path.write_text(json.dumps(failed))
            print(f"  Supabase sync failed for {pub_id}: {e}")

        if normalized_status == 'published':
            try:
                from volpred.publisher.email_notifier import EmailNotifier

                EmailNotifier(storage_dir=str(self.reports_dir.parent)).notify_article_published(
                    item,
                    reason='publish_milestone',
                )
            except Exception:
                pass

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
            data = self._feed_file.read_bytes()
            req = urllib.request.Request(
                f"{self.REMOTE_URL}/api/sync/feed.json",
                data=data,
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    def _load_feed(self) -> list[dict]:
        if self._feed_file.exists():
            with open(self._feed_file) as f:
                return json.load(f)
        return []
