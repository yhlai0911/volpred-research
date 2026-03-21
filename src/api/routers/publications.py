from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


def _get_publisher():
    from volpred.publisher.publisher import Publisher

    return Publisher()


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
    feed = publisher.get_feed(limit=1000)
    for item in feed:
        if item.get("id") == pub_id:
            return item
    raise HTTPException(status_code=404, detail="Publication not found")


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


@router.post("/publish")
def publish_item(req: PublishRequest):
    """Publish a new item to the feed (can be called from local to Zeabur)."""
    publisher = _get_publisher()
    pub_id = publisher.publish_milestone(
        title=req.title,
        description=req.description,
        phase=req.phase,
        details=req.details,
    )
    return {"status": "published", "id": pub_id}
