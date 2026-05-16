from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .common import get_storage_dir, require_research_mirror_token

router = APIRouter()


def _get_publisher():
    from volpred.publisher.publisher import Publisher

    return Publisher(storage_dir=get_storage_dir())


@router.get("/feed")
def get_feed(limit: int = 50, category: str | None = None):
    """Get published feed items."""
    publisher = _get_publisher()
    return publisher.get_feed(limit=limit, category=category)


@router.get("/feed/{pub_id}")
def get_publication(pub_id: str):
    """Get a single publication by ID."""
    from fastapi import HTTPException

    publisher = _get_publisher()
    # 2026-05-16: prefer get_report() which streams the feed and exits on first
    # match. Previous code did `get_feed(limit=1000)` which loaded the entire
    # feed into memory on every single-article request (violates CLAUDE.md
    # token discipline for storage/reports/feed.json).
    report = publisher.get_report(pub_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    if report.get("status") != "published":
        raise HTTPException(status_code=404, detail="Publication not found")
    return report


@router.get("/notifications")
def get_notifications(limit: int = 20, level: str | None = None):
    """Get notification history."""
    from volpred.publisher.email_notifier import EmailNotifier

    notifier = EmailNotifier()
    return notifier.get_notifications(limit=limit, level=level)


class PublishRequest(BaseModel):
    title: str
    description: str = ""
    category: str = "milestone"
    phase: str = ""
    details: dict = {}
    tags: list[str] = []
    metrics: dict = {}


@router.post("/publish", dependencies=[Depends(require_research_mirror_token)])
def publish_item(req: PublishRequest):
    """Publish a new item to the feed (can be called from local to Zeabur).

    2026-05-16: gated behind RESEARCH_MIRROR_TOKEN. Previously unauthenticated
    — any caller could publish arbitrary content to the canonical feed and
    trigger Supabase push. See docs/code_review_2026-05-16.md C5.
    """
    publisher = _get_publisher()
    pub_id = publisher.publish_milestone(
        title=req.title,
        description=req.description,
        phase=req.phase,
        details=req.details,
    )
    return {"status": "published", "id": pub_id}
