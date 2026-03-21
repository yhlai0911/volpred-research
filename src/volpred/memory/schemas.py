from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ExperimentRecord:
    """Record of a completed experiment."""
    experiment_id: str
    model_name: str
    asset: str
    config: dict
    metrics: dict
    timestamp: datetime = field(default_factory=datetime.now)
    notes: str = ""
    rank: int | None = None  # relative ranking among experiments


@dataclass
class ResearchLogEntry:
    """A single entry in the research journal."""
    entry_id: str
    timestamp: datetime
    phase: str  # 'baseline', 'tuning', 'advanced', etc.
    action: str  # what was done
    observation: str  # what was observed
    decision: str  # what was decided next
    experiment_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class KnowledgeItem:
    """A piece of knowledge/insight discovered during research."""
    item_id: str
    category: str  # 'data_property', 'model_behavior', 'parameter_sensitivity', etc.
    content: str
    evidence: list[str] = field(default_factory=list)  # experiment IDs that support this
    confidence: float = 0.5  # 0-1
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
