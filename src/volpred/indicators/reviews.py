"""
Indicator Arena — reviews module.

Append-only outcome review computation (§2.3 outcome_reviews, §5 評分公式).

Rules (§4 誠實機制):
  - Reviews are append-only to reviews/YYYY-MM.jsonl.
  - Original signal rows are never modified.
  - Corrections use correction_of (pointing to original review_id).
  - Review may only be computed after resolve_after time has passed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REVIEWS_DIR = (
    Path(__file__).resolve().parents[3]
    / "storage"
    / "indicator_arena"
    / "reviews"
)


@dataclass
class ReviewResult:
    """Output of compute_review (§2.3 outcome_reviews row)."""

    review_id: str             # "<signal_id>:review"
    signal_id: str
    reviewed_at: str           # ISO UTC
    realized: dict[str, Any]   # actual outcome
    hit: bool | None           # True=correct, False=wrong, None=calibration
    econ_value_bps: float | None
    data_source_asof: str | None
    correction_of: str | None = None
    league: str = "direction"  # "direction" | "calibration"


def compute_review(
    signal: dict[str, Any],
    realized: dict[str, Any],
    reviews_dir: Path | None = None,
    data_source_asof: str | None = None,
    correction_of: str | None = None,
) -> ReviewResult:
    """Compute and append a review for an expired signal.

    Args:
        signal: The original signal dict (from daily_signals).
        realized: Actual outcome. For direction league: {"actual_return": float}.
          For calibration league: {"actual_value": float, "threshold": float}.
        reviews_dir: Override storage directory (used in tests).
        data_source_asof: Timestamp when outcome data was fetched.
        correction_of: If this is a correction, the original review_id.

    Returns:
        ReviewResult dataclass (already appended to JSONL).

    Raises:
        ValueError: If signal is missing required fields or already resolved
                    before resolve_after.
    """
    base_dir = reviews_dir or REVIEWS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    signal_id = signal.get("signal_id")
    if not signal_id:
        raise ValueError("Signal missing 'signal_id'")

    indicator_id = signal.get("indicator_id", "")
    league = signal.get("league", "direction")
    prediction = signal.get("prediction", {})

    reviewed_at = datetime.now(timezone.utc).isoformat()
    review_id = f"{signal_id}:review"

    # Enforce resolve_after guard
    resolve_after = signal.get("resolve_after")
    if resolve_after:
        try:
            resolve_dt = datetime.fromisoformat(
                resolve_after.replace("Z", "+00:00")
            )
            now_dt = datetime.now(timezone.utc)
            if now_dt < resolve_dt:
                raise ValueError(
                    f"Signal {signal_id} cannot be reviewed yet. "
                    f"resolve_after={resolve_after}, now={now_dt.isoformat()}"
                )
        except ValueError as exc:
            if "cannot be reviewed" in str(exc):
                raise
            # If parse fails, allow (don't block on bad timestamp format)
            pass

    # --- Compute hit & econ_value_bps ---
    hit: bool | None = None
    econ_value_bps: float | None = None

    if league == "direction":
        # direction group: prediction = {direction: "up" | "down" | "flat"}
        predicted_dir = prediction.get("direction")
        actual_return = realized.get("actual_return")
        if predicted_dir is not None and actual_return is not None:
            if predicted_dir == "up":
                hit = float(actual_return) > 0
                econ_value_bps = float(actual_return) * 10000
            elif predicted_dir == "down":
                hit = float(actual_return) < 0
                econ_value_bps = -float(actual_return) * 10000
            else:  # "flat"
                hit = abs(float(actual_return)) < 0.005  # < 50bps = flat
                econ_value_bps = None

    elif league == "calibration":
        # calibration group: prediction = {var_5pct: float} or {q95_upper: float}
        # hit = True if no violation (outcome within bound)
        actual_value = realized.get("actual_value")
        threshold = realized.get("threshold")
        if actual_value is not None and threshold is not None:
            # For VaR: hit (no violation) = actual_return > VaR threshold
            # threshold is typically negative (e.g. -0.018)
            hit = float(actual_value) > float(threshold)
            econ_value_bps = None  # calibration group uses Kupiec score

    review_row: dict[str, Any] = {
        "review_id": review_id,
        "signal_id": signal_id,
        "indicator_id": indicator_id,
        "reviewed_at": reviewed_at,
        "realized": realized,
        "hit": hit,
        "econ_value_bps": econ_value_bps,
        "data_source_asof": data_source_asof,
        "correction_of": correction_of,
        "league": league,
    }

    # Append to YYYY-MM.jsonl based on reviewed_at
    reviewed_dt = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    month_str = reviewed_dt.strftime("%Y-%m")
    target_file = base_dir / f"{month_str}.jsonl"

    with open(target_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(review_row, ensure_ascii=False) + "\n")

    return ReviewResult(
        review_id=review_id,
        signal_id=signal_id,
        reviewed_at=reviewed_at,
        realized=realized,
        hit=hit,
        econ_value_bps=econ_value_bps,
        data_source_asof=data_source_asof,
        correction_of=correction_of,
        league=league,
    )


def read_reviews(
    year_month: str,
    reviews_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Read all review rows from a YYYY-MM.jsonl file."""
    base_dir = reviews_dir or REVIEWS_DIR
    target_file = base_dir / f"{year_month}.jsonl"
    if not target_file.exists():
        return []
    rows = []
    for line in target_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows
