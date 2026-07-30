"""Canonical taxonomy for substantive dispatch outcomes.

The active Operations Core and retained historical audit tools must measure
the same population.  Keeping this vocabulary outside a retired executable
prevents an audit dependency from making that executable look authoritative.
"""
SUBSTANTIVE_TASK_TYPES = frozenset(
    {
        "daily_article",
        "daily_digest",
        "event_article",
        "experiment",
        "member_qa",
        "paper_body",
        "paper_decision",
        "paper_review",
        "strategy_lifecycle",
        "trending_repost",
    }
)
