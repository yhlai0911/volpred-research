"""Shared dataclasses for the volpred system."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4


@dataclass
class DataRequirement:
    """Specifies what data a model needs."""

    fields: list[str]
    frequency: str = "daily"
    min_periods: int = 252
    external_sources: Optional[list[str]] = None


@dataclass
class ForecastResult:
    """Single-step forecast output from a volatility model."""

    date: datetime
    point_forecast: float
    variance_forecast: float
    distribution_params: dict = field(default_factory=dict)
    model_name: str = ""
    fit_info: dict = field(default_factory=dict)


@dataclass
class ModelState:
    """Serialisable snapshot of a fitted model (for checkpointing / resume)."""

    model_name: str
    params: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class WindowSpec:
    """Rolling-window specification using integer indices."""

    start: int
    end: int
    target_date: datetime


@dataclass
class ExperimentConfig:
    """Full specification for a single back-test experiment."""

    model_name: str
    model_params: dict = field(default_factory=dict)
    asset: str = ""
    window_size: int = 252
    oos_start: str = ""
    oos_end: str = ""
    experiment_id: str = field(default_factory=lambda: uuid4().hex[:8])


@dataclass
class ExperimentResult:
    """Collected results of a completed experiment."""

    experiment_id: str
    config: ExperimentConfig
    forecasts: list[ForecastResult] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    fit_time: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
