"""
Indicator Arena — signals module.

Append-only daily signal emission to storage/indicator_arena/signals/YYYY-MM.jsonl.

Integrity rules (§4 誠實機制):
  - File open mode is always 'a' (append); overwrite is forbidden.
  - as_of_ts must be ≤ emitted_at (no lookahead).
  - All required fields must be present before writing.
  - Once written, a row is never modified (correction_of pattern in reviews).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SIGNALS_DIR = (
    Path(__file__).resolve().parents[3]
    / "storage"
    / "indicator_arena"
    / "signals"
)

REQUIRED_FIELDS = {
    "signal_id",
    "indicator_id",
    "as_of_ts",
    "emitted_at",
    "prediction",
    "horizon_days",
    "expires_at",
    "data_hash",
    "code_version",
}


@dataclass
class SignalPayload:
    """All fields for a single emitted signal (§2.2 daily_signals)."""

    indicator_id: str
    as_of_ts: str          # ISO UTC — data cutoff time (must be ≤ emitted_at)
    prediction: dict[str, Any]
    horizon_days: int
    expires_at: str        # ISO UTC — as_of_ts + horizon_days trading days
    data_hash: str         # sha256 of raw inputs
    code_version: str      # git short sha of producing script

    # Optional / auto-filled
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    emitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    indicator_value: float | None = None
    inputs_snapshot: dict[str, Any] = field(default_factory=dict)
    target_date: str | None = None         # YYYY-MM-DD
    published_at: str | None = None        # alias for emitted_at (§2.2)
    resolve_after: str | None = None       # when result may be scored
    late: bool = False                     # set by pipeline if post-open


def _get_git_short_sha() -> str:
    """Return current git short sha, or 'unknown' if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def compute_data_hash(raw_inputs: dict[str, Any]) -> str:
    """Compute sha256 of canonical JSON representation of raw inputs."""
    canonical = json.dumps(raw_inputs, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_payload(payload: dict[str, Any]) -> None:
    """Raise ValueError if any required field is missing or as_of_ts > emitted_at."""
    missing = REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise ValueError(
            f"Signal payload missing required fields: {sorted(missing)}"
        )

    # Lookahead guard: as_of_ts must be ≤ emitted_at
    as_of = payload["as_of_ts"]
    emitted = payload["emitted_at"]
    try:
        as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        emitted_dt = datetime.fromisoformat(emitted.replace("Z", "+00:00"))
        if as_of_dt > emitted_dt:
            raise ValueError(
                f"Lookahead violation: as_of_ts ({as_of}) > emitted_at ({emitted}). "
                "Signal cannot reference data from the future."
            )
    except (ValueError, TypeError) as exc:
        if "Lookahead" in str(exc):
            raise
        raise ValueError(
            f"Cannot parse timestamps for lookahead check: "
            f"as_of_ts={as_of!r}, emitted_at={emitted!r}"
        ) from exc

    if not isinstance(payload.get("prediction"), dict):
        raise ValueError("'prediction' must be a dict")

    if not isinstance(payload.get("horizon_days"), int) or payload["horizon_days"] < 1:
        raise ValueError("'horizon_days' must be a positive int")


def append_signal(
    indicator_id: str,
    signal_payload: dict[str, Any],
    signals_dir: Path | None = None,
) -> Path:
    """Append one signal record to the appropriate YYYY-MM.jsonl file.

    Args:
        indicator_id: Must match an indicator in the registry.
        signal_payload: Dict with all required fields (see REQUIRED_FIELDS).
        signals_dir: Override storage directory (used in tests).

    Returns:
        Path to the file that was written.

    Raises:
        ValueError: if any required field is missing, or lookahead detected.

    Notes:
        - File is always opened with mode='a' (never 'w').
        - Each call appends exactly one JSON line.
        - indicator_id in the call must match signal_payload["indicator_id"].
    """
    base_dir = signals_dir or SIGNALS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    # Inject indicator_id from caller (authoritative)
    payload = dict(signal_payload)
    payload["indicator_id"] = indicator_id

    # Auto-fill emitted_at if not provided
    if "emitted_at" not in payload:
        payload["emitted_at"] = datetime.now(timezone.utc).isoformat()

    # Auto-fill signal_id if not provided
    if "signal_id" not in payload:
        payload["signal_id"] = str(uuid.uuid4())

    _validate_payload(payload)

    # Determine file from emitted_at month
    emitted = payload["emitted_at"]
    try:
        emitted_dt = datetime.fromisoformat(emitted.replace("Z", "+00:00"))
        month_str = emitted_dt.strftime("%Y-%m")
    except (ValueError, TypeError):
        month_str = datetime.now(timezone.utc).strftime("%Y-%m")

    target_file = base_dir / f"{month_str}.jsonl"

    # Append-only: mode='a' is mandatory
    with open(target_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return target_file


def read_signals(
    year_month: str,
    signals_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Read all signal rows from a YYYY-MM.jsonl file.

    Args:
        year_month: e.g. "2026-06"
        signals_dir: Override storage directory.

    Returns:
        List of signal dicts (may be empty if file doesn't exist).
    """
    base_dir = signals_dir or SIGNALS_DIR
    target_file = base_dir / f"{year_month}.jsonl"
    if not target_file.exists():
        return []
    rows = []
    for line in target_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows
