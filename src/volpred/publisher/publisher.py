from __future__ import annotations
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

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
        except Exception:
            pass
        return pub_id

    def publish_milestone(self, title: str, description: str,
                         phase: str, details: dict | None = None,
                         tags: list[str] | None = None,
                         status: str = 'published',
                         publish_at: str | None = None) -> str:
        """Publish a research milestone."""
        import uuid
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
        pub_id = f"mile_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        normalized_status = status if status in {'published', 'draft', 'scheduled', 'unpublished', 'archived'} else 'published'
        item = {
            'id': pub_id,
            'title': title,
            'description': description,
            'category': 'milestone',
            'phase': phase,
            'details': details or {},
            'tags': tags or [],
            'created_at': now,
            'published_at': publish_at or now,
            'status': normalized_status,
        }

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
        feed = self._load_feed()
        feed.append(item)
        # Sort newest first — use published_at (consistent with frontend display)
        feed.sort(key=lambda x: x.get('published_at', x.get('created_at', '')), reverse=True)
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
        except Exception:
            pass

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
