from __future__ import annotations
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

def _sanitize_tags(tags: list) -> list[str]:
    """Clean tags: fix double-encoded JSON, strip quotes/brackets, dedupe."""
    cleaned: list[str] = []
    for t in tags:
        if not isinstance(t, str):
            t = str(t)
        # Strip JSON artifacts from double-encoding: '["研究"' → '研究'
        t = t.strip().strip('[').strip(']').strip('"').strip("'").strip()
        if t and t not in cleaned:
            cleaned.append(t)
    return cleaned


class Publisher:
    """Publishes research results to storage/reports/ for Web platform consumption.

    If remote_url is set, also POSTs to a remote API (e.g., Zeabur) for dual publishing.
    """

    # Set this to Zeabur URL to enable dual publishing
    REMOTE_URL = os.environ.get("VOLPRED_REMOTE_URL", "https://volpred.zeabur.app")

    def __init__(self, storage_dir: str = 'storage'):
        self.reports_dir = Path(storage_dir) / 'reports'
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._feed_file = self.reports_dir / 'feed.json'

    def _sync_to_remote(self, title: str, description: str = "", phase: str = "", details: dict | None = None):
        """Sync is handled by _sync_feed_to_remote (PUT entire feed.json).
        POST is no longer used to avoid duplicate/ordering conflicts."""
        pass

    @staticmethod
    def _tokenize_title(title: str) -> set:
        """Extract meaningful Chinese/English keywords from title."""
        import re
        # Remove punctuation and split
        clean = re.sub(r'[^\w\u4e00-\u9fff]', ' ', title.lower())
        # Split Chinese into 2-char ngrams + keep English words
        tokens = set()
        for word in clean.split():
            if len(word) >= 2:
                tokens.add(word)
        # Chinese 2-gram
        chinese = re.findall(r'[\u4e00-\u9fff]+', title)
        for phrase in chinese:
            for i in range(len(phrase) - 1):
                tokens.add(phrase[i:i+2])
        # Remove very common words
        stopwords = {'的', '了', '是', '在', '和', '你', '我', '這', '那', '都', '也', '就', '但'}
        tokens -= stopwords
        return tokens

    def _find_similar_articles(self, title: str, feed: list, audience: str | None = None) -> list:
        """Find articles with similar topics (>50% keyword overlap).
        Only checks same audience type to avoid false positives across general/research.
        """
        new_tokens = self._tokenize_title(title)
        if not new_tokens:
            return []

        similar = []
        for existing in feed:
            if existing.get('status') == 'unpublished':
                continue
            # Only compare within same audience
            if audience and existing.get('audience') != audience:
                continue
            ex_tokens = self._tokenize_title(existing.get('title', ''))
            if not ex_tokens:
                continue
            overlap = len(new_tokens & ex_tokens)
            union = len(new_tokens | ex_tokens)
            jaccard = overlap / union if union > 0 else 0
            if jaccard > 0.35:  # 35% Jaccard similarity threshold
                similar.append({
                    'id': existing.get('id', '?'),
                    'title': existing.get('title', '?'),
                    'similarity': jaccard,
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

        # Save individual report
        report_file = self.reports_dir / f"{item['id']}.json"
        with open(report_file, 'w') as f:
            json.dump(item, f, indent=2, default=str)

        # Append to feed
        self._append_to_feed(item)
        try:
            from volpred.publisher.email_notifier import EmailNotifier

            EmailNotifier(storage_dir=str(self.reports_dir.parent)).notify_article_published(
                item,
                reason='publish_experiment',
            )
        except Exception as e:
            print(f"  WARNING publisher: {e}")

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

        report_file = self.reports_dir / f"{pub_id}.json"
        with open(report_file, 'w') as f:
            json.dump(item, f, indent=2, default=str)

        self._append_to_feed(item)
        self._sync_to_remote(title, analysis, 'comparison')
        try:
            from volpred.publisher.email_notifier import EmailNotifier

            EmailNotifier(storage_dir=str(self.reports_dir.parent)).notify_article_published(
                item,
                reason='publish_comparison',
            )
        except Exception as e:
            print(f"  WARNING publisher: {e}")
        return pub_id

    def publish_milestone(self, title: str, description: str,
                         phase: str, details: dict | None = None,
                         tags: list[str] | None = None,
                         status: str = 'published',
                         publish_at: str | None = None,
                         audience: str | None = None,
                         category: str | None = None,
                         proposer: str | None = None) -> str:
        """Publish a research milestone.

        audience: 'general' (一般讀者), 'research' (研究), 'daily' (每日建議), 'member_qa'
        category: 'general', 'milestone', 'experiment', 'comparison', 'qa'
        If not provided, auto-detected from tags.
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
                except Exception as e:
                    print(f"  WARNING publisher: {e}")

        # --- Similar topic check: warn if >60% keyword overlap with existing ---
        similar = self._find_similar_articles(title, feed, audience)
        if similar:
            print(f"  ⚠️ Similar articles found ({len(similar)}):")
            for s in similar[:3]:
                print(f"    [{s['similarity']:.0%}] {s['id']}: {s['title'][:60]}")
            print(f"  → Proceeding with publish, but consider if this adds new value.")
        # Sanitize description
        if isinstance(description, str):
            # Fix double-escaped newlines from CLI input, but preserve LaTeX commands.
            # \\n → newline ONLY when NOT followed by a letter (avoid destroying \nu, \nabla, \newcommand, etc.)
            # \\t → NEVER replace (destroys \tau, \times, \theta, \text{}, etc.)
            import re
            description = re.sub(r'\\n(?![a-zA-Z])', '\n', description)
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
                if s.get('status') in ('published', 'draft') and s['similarity'] > 0.2
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
        tag_list = _sanitize_tags(tags or [])
        if audience is None:
            if '一般讀者' in tag_list:
                audience = 'general'
            elif '每日建議' in tag_list or 'daily-update' in tag_list:
                audience = 'daily'
            else:
                audience = 'research'
        if category is None:
            if audience == 'general':
                category = 'general'
            else:
                category = 'milestone'

        # Build related_articles list for metadata
        related_articles = []
        if similar:
            related_articles = [
                {'id': s['id'], 'title': s['title'], 'similarity': round(s['similarity'], 2)}
                for s in similar if s.get('status') in ('published', 'draft') and s['similarity'] > 0.2
            ][:5]

        item = {
            'id': pub_id,
            'title': title,
            'description': description,
            'content': description,
            'category': category,
            'audience': audience,
            'phase': phase,
            'details': details or {},
            'tags': tag_list,
            'related_articles': related_articles,
            'created_at': now,
            'published_at': publish_at or now,
            'status': normalized_status,
        }
        if proposer:
            item['proposer'] = proposer

        report_file = self.reports_dir / f"{pub_id}.json"
        with open(report_file, 'w') as f:
            json.dump(item, f, indent=2, default=str)

        self._append_to_feed(item)
        self._sync_to_remote(title, description, phase, details)
        self._sync_report_to_remote(pub_id, item)

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
            except Exception as e:
                print(f"  WARNING publisher: {e}")

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
        report_file = self.reports_dir / f"{pub_id}.json"
        if report_file.exists():
            report = json.loads(report_file.read_text())
            report['status'] = 'unpublished'
            report_file.write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False))
            target_item = report
        self._sync_feed_to_remote()
        if target_item:
            self._sync_report_to_remote(pub_id, target_item)
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
            from supabase_sync import sync_article
            sync_article(target_item, storage_dir=self.reports_dir.parent)
        except Exception as e:
            print(f"  WARNING publisher: {e}")
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
            item['category'] = 'general' if item.get('audience') == 'general' else 'milestone'
        # Ensure content is not empty (use description as fallback)
        if not item.get('content') and item.get('description'):
            item['content'] = item['description']
        feed = self._load_feed()
        feed.append(item)
        # Sort newest first — use published_at (consistent with frontend display)
        feed.sort(key=lambda x: x.get('published_at') or x.get('created_at') or '', reverse=True)
        with open(self._feed_file, 'w') as f:
            json.dump(feed, f, indent=2, default=str, ensure_ascii=False)
        self._sync_feed_to_remote()
        # Also sync the individual report JSON
        if item.get('id'):
            self._sync_report_to_remote(item['id'], item)

    def get_report(self, pub_id: str) -> dict | None:
        report_file = self.reports_dir / f"{pub_id}.json"
        if report_file.exists():
            try:
                return json.loads(report_file.read_text())
            except Exception:
                return None
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
        """PUT individual report JSON to remote."""
        if not self.REMOTE_URL:
            return
        try:
            import urllib.request
            data = json.dumps(item, indent=2, default=str).encode('utf-8')
            req = urllib.request.Request(
                f"{self.REMOTE_URL}/api/sync/reports/{pub_id}.json",
                data=data,
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"  WARNING publisher: {e}")

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
