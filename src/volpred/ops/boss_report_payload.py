"""Immutable, fire-bound payload materialization for Boss Report delivery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from volpred.canonical_write import guard_canonical_write


_SCHEMA_VERSION = "boss-report-payload.v1"
_PAYLOAD_DIR = Path("storage/ops/boss_report_payloads")


@dataclass(frozen=True)
class BossReportPayload:
    fire_key: str
    job_id: str
    scheduled_for: str
    daily_close: bool
    window_hours: float
    title: str
    html_body: str
    text_body: str
    payload_sha256: str
    materialized_ref: str


def materialize_boss_report_payload(
    repo_root: Path,
    *,
    fire_key: str,
    job_id: str,
    scheduled_for: str,
    daily_close: bool,
    window_hours: float,
    build: Callable[[], tuple[str, str, str]],
) -> BossReportPayload:
    """Create one immutable report payload or return the fire's exact bytes."""

    normalized_fire_key = _required_text(fire_key, field="fire_key")
    normalized_job_id = _required_text(job_id, field="job_id")
    normalized_scheduled_for = _required_text(
        scheduled_for,
        field="scheduled_for",
    )
    if not isinstance(daily_close, bool):
        raise TypeError("daily_close must be boolean")
    if (
        isinstance(window_hours, bool)
        or not isinstance(window_hours, (int, float))
        or window_hours <= 0
    ):
        raise ValueError("window_hours must be positive")
    normalized_window = float(window_hours)

    root = repo_root.resolve()
    directory = root / _PAYLOAD_DIR
    target = directory / (
        hashlib.sha256(
            normalized_fire_key.encode("utf-8")
        ).hexdigest()
        + ".json"
    )
    if target.exists():
        return _read_payload(
            target,
            fire_key=normalized_fire_key,
            job_id=normalized_job_id,
            scheduled_for=normalized_scheduled_for,
            daily_close=daily_close,
            window_hours=normalized_window,
        )

    title, html_body, text_body = build()
    identity: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "fire_key": normalized_fire_key,
        "job_id": normalized_job_id,
        "scheduled_for": normalized_scheduled_for,
        "daily_close": daily_close,
        "window_hours": normalized_window,
        "title": _required_text(title, field="title"),
        "html_body": _required_text(html_body, field="html_body"),
        "text_body": _required_text(text_body, field="text_body"),
    }
    identity_bytes = _json_bytes(identity)
    stored = {
        **identity,
        "payload_sha256": hashlib.sha256(identity_bytes).hexdigest(),
    }
    encoded = _json_bytes(stored)

    guard_canonical_write(target)
    directory.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=directory,
            prefix=".boss-report-payload-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            os.chmod(temp_path, 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, target)
        except FileExistsError:
            if not target.is_file() or target.is_symlink():
                raise RuntimeError(
                    "Boss Report materialized payload collision is not "
                    "a regular file"
                )
        else:
            directory_fd = os.open(
                directory,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return _read_payload(
        target,
        fire_key=normalized_fire_key,
        job_id=normalized_job_id,
        scheduled_for=normalized_scheduled_for,
        daily_close=daily_close,
        window_hours=normalized_window,
    )


def _read_payload(
    path: Path,
    *,
    fire_key: str,
    job_id: str,
    scheduled_for: str,
    daily_close: bool,
    window_hours: float,
) -> BossReportPayload:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(
            "Boss Report materialized payload must be a regular file"
        )
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Boss Report materialized payload is unreadable: {path}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError(
            "Boss Report materialized payload must be an object"
        )
    expected_keys = {
        "schema_version",
        "fire_key",
        "job_id",
        "scheduled_for",
        "daily_close",
        "window_hours",
        "title",
        "html_body",
        "text_body",
        "payload_sha256",
    }
    if set(payload) != expected_keys:
        raise RuntimeError(
            "Boss Report materialized payload schema drifted"
        )
    identity = {
        key: payload[key]
        for key in expected_keys
        if key != "payload_sha256"
    }
    observed_sha256 = hashlib.sha256(
        _json_bytes(identity)
    ).hexdigest()
    expected_sha256 = _sha256(
        payload.get("payload_sha256"),
        field="payload_sha256",
    )
    if observed_sha256 != expected_sha256:
        raise RuntimeError(
            "Boss Report materialized payload hash mismatch"
        )
    if (
        payload.get("schema_version") != _SCHEMA_VERSION
        or payload.get("fire_key") != fire_key
        or payload.get("job_id") != job_id
        or payload.get("scheduled_for") != scheduled_for
        or payload.get("daily_close") is not daily_close
        or payload.get("window_hours") != window_hours
    ):
        raise RuntimeError(
            "Boss Report materialized payload fire identity conflicts"
        )
    return BossReportPayload(
        fire_key=fire_key,
        job_id=job_id,
        scheduled_for=scheduled_for,
        daily_close=daily_close,
        window_hours=window_hours,
        title=_required_text(payload.get("title"), field="title"),
        html_body=_required_text(
            payload.get("html_body"),
            field="html_body",
        ),
        text_body=_required_text(
            payload.get("text_body"),
            field="text_body",
        ),
        payload_sha256=expected_sha256,
        materialized_ref=str(path),
    )


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _sha256(value: object, *, field: str) -> str:
    normalized = _required_text(value, field=field)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef"
        for character in normalized
    ):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return normalized


__all__ = [
    "BossReportPayload",
    "materialize_boss_report_payload",
]
