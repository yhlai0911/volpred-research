from __future__ import annotations

from pydantic import BaseModel


class ExperimentSummary(BaseModel):
    experiment_id: str
    model_name: str
    asset: str
    qlike: float | None = None
    mse: float | None = None
    n_forecasts: int = 0
    timestamp: str = ""


class FeedItem(BaseModel):
    id: str
    title: str
    category: str
    published_at: str
    status: str = "published"
