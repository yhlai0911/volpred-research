"""
Indicator Arena — registry module.

Loads indicator specs from storage/indicator_arena/registry.json.
Provides typed access via IndicatorSpec dataclass.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "storage"
    / "indicator_arena"
    / "registry.json"
)

VALID_STATUSES = {"active", "observation", "delisted"}
VALID_LEAGUES = {"direction", "calibration"}


@dataclass
class IndicatorSpec:
    """Typed representation of one row in indicator_registry (§2.1)."""

    indicator_id: str
    name_zh: str
    league: str                    # "direction" | "calibration"
    signal_rule: str
    target: str
    horizon_days: int
    data_sources: dict[str, Any]
    k_refs: list[str]
    oos_evidence: dict[str, Any]
    caveats: str
    status: str                    # "active" | "observation" | "delisted"
    status_since: str
    listed_at: str
    delisted_at: str | None
    status_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.league not in VALID_LEAGUES:
            raise ValueError(
                f"Invalid league '{self.league}' for {self.indicator_id}. "
                f"Must be one of {VALID_LEAGUES}."
            )
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{self.status}' for {self.indicator_id}. "
                f"Must be one of {VALID_STATUSES}."
            )
        if self.horizon_days < 1:
            raise ValueError(
                f"horizon_days must be ≥ 1, got {self.horizon_days} "
                f"for {self.indicator_id}."
            )


def load_registry(path: Path | None = None) -> list[IndicatorSpec]:
    """Load all indicators from registry.json.

    Args:
        path: Override path to registry.json (used in tests).

    Returns:
        List of IndicatorSpec, one per row.

    Raises:
        FileNotFoundError: if registry.json does not exist.
        ValueError: if any row is missing required fields.
    """
    p = path or REGISTRY_PATH
    if not p.exists():
        raise FileNotFoundError(f"Registry not found at {p}")

    raw: list[dict[str, Any]] = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"registry.json must be a JSON array, got {type(raw)}")

    specs: list[IndicatorSpec] = []
    required = {
        "indicator_id", "name_zh", "league", "signal_rule", "target",
        "horizon_days", "data_sources", "k_refs", "oos_evidence",
        "caveats", "status", "status_since", "listed_at",
    }
    for i, row in enumerate(raw):
        missing = required - set(row.keys())
        if missing:
            raise ValueError(
                f"Registry row {i} missing required fields: {missing}"
            )
        specs.append(
            IndicatorSpec(
                indicator_id=row["indicator_id"],
                name_zh=row["name_zh"],
                league=row["league"],
                signal_rule=row["signal_rule"],
                target=row["target"],
                horizon_days=int(row["horizon_days"]),
                data_sources=row["data_sources"],
                k_refs=row["k_refs"],
                oos_evidence=row["oos_evidence"],
                caveats=row["caveats"],
                status=row["status"],
                status_since=row["status_since"],
                listed_at=row["listed_at"],
                delisted_at=row.get("delisted_at"),
                status_history=row.get("status_history", []),
            )
        )
    return specs


def get_active(path: Path | None = None) -> list[IndicatorSpec]:
    """Return only indicators with status='active'."""
    return [s for s in load_registry(path) if s.status == "active"]


def get_by_id(
    indicator_id: str, path: Path | None = None
) -> IndicatorSpec | None:
    """Return one IndicatorSpec by indicator_id, or None if not found."""
    for spec in load_registry(path):
        if spec.indicator_id == indicator_id:
            return spec
    return None
