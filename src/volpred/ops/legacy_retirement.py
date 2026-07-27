"""Fail-closed evidence gate for physical legacy execution retirement.

This module does not delete anything.  It proves that the old hourly-dispatch
business executor is absent only after formal ownership, the sustained-clean
window, repository references, and live host surfaces all agree.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

_RECEIPT_SCHEMA = "legacy-retirement-observation-bundle.v1"
_OWNER_SCHEMA = "formal-owner-census.v1"
_VIOLATION_KEYS = (
    "silent_loss",
    "duplicate_effect",
    "orphan_work",
    "unknown_ownership",
    "legacy_business_fire",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_HOURLY_JOB_ID = "volpred-hourly-dispatch"
_HOURLY_LABEL = "com.volpred.hourly-dispatch"
_HOURLY_WRAPPER = "cron_hourly_dispatch.sh"
_BUNDLE_SCHEMA = "legacy-retirement-observation-bundle.v1"
_SIGNAL_SCHEMA = "legacy-retirement-signal.v1"
_SOURCE_REFS = {
    "silent_loss": "operations-core://legacy-retirement/silent-loss",
    "duplicate_effect": "operations-core://legacy-retirement/duplicate-effect",
    "orphan_work": "operations-core://legacy-retirement/orphan-work",
    "unknown_ownership": "operations-core://formal-owner-census",
    "legacy_business_fire": (
        "operations-core://legacy-retirement/legacy-business-fire"
    ),
}


class LegacyRetirementInputError(ValueError):
    """Retirement evidence is malformed or internally inconsistent."""


@dataclass(frozen=True)
class SustainedCleanReport:
    schema_version: str
    ready: bool
    status: str
    assessed_at: str
    required_window_seconds: int
    max_gap_seconds: int
    max_age_seconds: int
    observation_count: int
    recorded_from: str | None
    recorded_to: str | None
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LegacyRetirementReport:
    schema_version: str
    ready: bool
    status: str
    assessed_at: str
    blocker_codes: tuple[str, ...]
    evidence: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _Observation:
    receipt_id: str
    observed_at: datetime
    breaks_clean_window: bool


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _signal_payload(
    raw: bytes,
    *,
    dimension: str,
    observed_at: datetime,
    max_age: timedelta,
) -> Mapping[str, Any]:
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LegacyRetirementInputError(
            f"{dimension} source is not valid JSON"
        ) from error
    signal = _mapping(payload, field=f"{dimension} source")
    if signal.get("schema_version") != _SIGNAL_SCHEMA:
        raise LegacyRetirementInputError(f"{dimension} source schema is invalid")
    if signal.get("dimension") != dimension:
        raise LegacyRetirementInputError(f"{dimension} source identity drifted")
    if signal.get("producer") != "operations_core":
        raise LegacyRetirementInputError(
            f"{dimension} source producer is not Operations Core"
        )
    source_time = _timestamp(
        signal.get("observed_at"),
        field=f"{dimension} source observed_at",
    )
    window_from = _timestamp(
        signal.get("window_from"),
        field=f"{dimension} source window_from",
    )
    window_to = _timestamp(
        signal.get("window_to"),
        field=f"{dimension} source window_to",
    )
    if window_from > window_to or source_time != window_to:
        raise LegacyRetirementInputError(
            f"{dimension} source coverage interval is invalid"
        )
    if source_time > observed_at or observed_at - source_time > max_age:
        raise LegacyRetirementInputError(
            f"{dimension} source is stale or from the future"
        )
    count = signal.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise LegacyRetirementInputError(
            f"{dimension} source count must be a non-negative integer"
        )
    high_watermark = signal.get("high_watermark")
    if (
        isinstance(high_watermark, bool)
        or not isinstance(high_watermark, int)
        or high_watermark < 0
    ):
        raise LegacyRetirementInputError(
            f"{dimension} source high_watermark must be a non-negative integer"
        )
    evidence_refs = signal.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(
            not isinstance(reference, str)
            or not reference.strip()
            or reference != reference.strip()
            for reference in evidence_refs
        )
        or len(evidence_refs) != len(set(evidence_refs))
    ):
        raise LegacyRetirementInputError(
            f"{dimension} source evidence_refs are invalid"
        )
    return signal


def _assert_signal_continuity(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    dimension: str,
) -> None:
    previous_to = _timestamp(
        previous.get("window_to"),
        field=f"{dimension} previous window_to",
    )
    current_from = _timestamp(
        current.get("window_from"),
        field=f"{dimension} current window_from",
    )
    if current_from != previous_to:
        raise LegacyRetirementInputError(f"{dimension} source coverage is not gap-free")
    previous_watermark = previous.get("high_watermark")
    current_watermark = current.get("high_watermark")
    if (
        not isinstance(previous_watermark, int)
        or not isinstance(current_watermark, int)
        or current_watermark < previous_watermark
    ):
        raise LegacyRetirementInputError(f"{dimension} source high_watermark regressed")


def _owner_snapshot(
    raw: bytes,
    *,
    observed_at: datetime | None = None,
    max_age: timedelta = timedelta(seconds=30),
) -> tuple[Mapping[str, Any], int]:
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LegacyRetirementInputError(
            "formal owner census snapshot is not valid JSON"
        ) from error
    owner = _mapping(payload, field="formal owner census snapshot")
    if owner.get("schema_version") != _OWNER_SCHEMA:
        raise LegacyRetirementInputError(
            "formal owner census snapshot schema is invalid"
        )
    inventory_sha = owner.get("inventory_sha256")
    if not isinstance(inventory_sha, str) or _SHA256.fullmatch(inventory_sha) is None:
        raise LegacyRetirementInputError(
            "formal owner census snapshot inventory hash is invalid"
        )
    blockers = owner.get("blockers")
    if not isinstance(blockers, list):
        raise LegacyRetirementInputError(
            "formal owner census snapshot blockers are invalid"
        )
    capabilities = owner.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise LegacyRetirementInputError(
            "formal owner census snapshot capabilities are invalid"
        )
    audited_at = _timestamp(
        owner.get("audited_at"),
        field="formal owner census snapshot audited_at",
    )
    if observed_at is not None and (
        audited_at > observed_at or observed_at - audited_at > max_age
    ):
        raise LegacyRetirementInputError(
            "formal owner census snapshot is stale or from the future"
        )
    blocker_count = len(blockers)
    expected_ok = blocker_count == 0
    if owner.get("ok") is not expected_ok or owner.get("status") != (
        "unique_owners_verified" if expected_ok else "ownership_blocked"
    ):
        raise LegacyRetirementInputError(
            "formal owner census snapshot disposition is inconsistent"
        )
    return owner, blocker_count


def _bundle_receipt_sha256(receipt: Mapping[str, object]) -> str:
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    return _sha256_bytes(_canonical_bytes(unsigned))


def _reject_symlink_components(root: Path, path: Path) -> None:
    root_path = root.absolute()
    target = path.absolute()
    try:
        relative = target.relative_to(root_path)
    except ValueError as error:
        raise LegacyRetirementInputError(
            f"legacy retirement path escapes root: {path}"
        ) from error
    cursor = root_path
    for part in (".", *relative.parts):
        if part != ".":
            cursor /= part
        if os.path.lexists(cursor) and cursor.is_symlink():
            raise LegacyRetirementInputError(
                f"legacy retirement path must not traverse symlink: {cursor}"
            )


def _read_regular_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise LegacyRetirementInputError(
            f"could not open canonical source without symlink: {path}"
        ) from error
    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise LegacyRetirementInputError(
                f"canonical source is not a regular file: {path}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def append_retirement_observation(
    *,
    root: Path,
    owner_report: Mapping[str, object],
    observed_at: datetime | None = None,
    source_max_age: timedelta = timedelta(minutes=10),
) -> Path:
    """Append one fsync'd observation bundle from typed canonical sources.

    The production caller supplies the just-computed formal owner report and
    the four fixed Operations Core signal files. Counts are read from those
    files; callers cannot pass count values or arbitrary source identities.
    """

    now = _utc(
        observed_at or datetime.now(UTC),
        field="observed_at",
    )
    allowed_age = _positive_duration(
        source_max_age,
        field="source_max_age",
    )
    repo_root = Path(root)
    expected_signals = set(_VIOLATION_KEYS) - {"unknown_ownership"}
    signal_dir = repo_root / "storage" / "ops" / "legacy_retirement_signals"
    directory = repo_root / "storage" / "ops" / "legacy_retirement_observations"
    _reject_symlink_components(repo_root, signal_dir)
    _reject_symlink_components(repo_root, directory)
    normalized_signal_paths = {
        dimension: signal_dir / f"{dimension}.json" for dimension in expected_signals
    }
    owner_bytes = _canonical_bytes(owner_report)
    owner, owner_blocker_count = _owner_snapshot(
        owner_bytes,
        observed_at=now,
    )

    signal_bytes: dict[str, bytes] = {}
    signal_payloads: dict[str, Mapping[str, Any]] = {}
    violations: dict[str, int] = {
        "unknown_ownership": owner_blocker_count,
    }
    for dimension in sorted(expected_signals):
        path = normalized_signal_paths[dimension]
        try:
            raw = _read_regular_nofollow(path)
        except OSError as error:
            raise LegacyRetirementInputError(
                f"could not read {dimension} canonical source: {path}"
            ) from error
        signal = _signal_payload(
            raw,
            dimension=dimension,
            observed_at=now,
            max_age=allowed_age,
        )
        signal_bytes[dimension] = raw
        signal_payloads[dimension] = signal
        violations[dimension] = int(signal["count"])

    directory_existed = directory.exists()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    if not directory_existed:
        _fsync_directory(directory.parent)
    lock_path = directory / ".append.lock"
    lock_flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        lock_flags |= os.O_NOFOLLOW
    try:
        lock_descriptor = os.open(lock_path, lock_flags, 0o600)
    except OSError as error:
        raise LegacyRetirementInputError(
            "legacy retirement append lock is unsafe"
        ) from error
    with os.fdopen(lock_descriptor, "a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing = load_verified_retirement_observations(repo_root)
        if existing:
            latest_bundle = directory / str(existing[-1]["receipt_id"])
            latest_observed_at = _timestamp(
                existing[-1]["observed_at"],
                field="previous observation observed_at",
            )
            for dimension in sorted(expected_signals):
                previous = _signal_payload(
                    _read_regular_nofollow(
                        latest_bundle / "sources" / f"{dimension}.json"
                    ),
                    dimension=dimension,
                    observed_at=latest_observed_at,
                    max_age=allowed_age,
                )
                _assert_signal_continuity(
                    previous,
                    signal_payloads[dimension],
                    dimension=dimension,
                )
        sequence = len(existing) + 1
        previous_sha = existing[-1]["receipt_sha256"] if existing else None
        receipt_id = (
            f"{sequence:08d}-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:12]}"
        )
        temporary = directory / f".{receipt_id}.tmp"
        final = directory / receipt_id
        temporary.mkdir(mode=0o700)
        try:
            sources = temporary / "sources"
            sources.mkdir(mode=0o700)
            snapshots: dict[str, dict[str, str]] = {}
            for dimension in _VIOLATION_KEYS:
                raw = (
                    owner_bytes
                    if dimension == "unknown_ownership"
                    else signal_bytes[dimension]
                )
                snapshot_name = f"{dimension}.json"
                _write_exclusive(sources / snapshot_name, raw)
                snapshots[dimension] = {
                    "source_ref": _SOURCE_REFS[dimension],
                    "snapshot_path": f"sources/{snapshot_name}",
                    "snapshot_sha256": _sha256_bytes(raw),
                }
            _fsync_directory(sources)
            receipt: dict[str, object] = {
                "schema_version": _BUNDLE_SCHEMA,
                "receipt_id": receipt_id,
                "sequence": sequence,
                "previous_receipt_sha256": previous_sha,
                "observed_at": now.isoformat(),
                "formal_owner_census": {
                    "ok": owner["ok"],
                    "inventory_sha256": owner["inventory_sha256"],
                    **snapshots["unknown_ownership"],
                },
                "violations": {key: violations[key] for key in _VIOLATION_KEYS},
                "evidence": snapshots,
            }
            receipt["receipt_sha256"] = _bundle_receipt_sha256(receipt)
            _write_exclusive(
                temporary / "receipt.json",
                _canonical_bytes(receipt),
            )
            _fsync_directory(temporary)
            os.replace(temporary, final)
            _fsync_directory(directory)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return final


def load_verified_retirement_observations(
    root: Path,
) -> list[dict[str, object]]:
    """Read and re-hash every immutable source snapshot and receipt link."""

    repo_root = Path(root)
    directory = repo_root / "storage" / "ops" / "legacy_retirement_observations"
    _reject_symlink_components(repo_root, directory)
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise LegacyRetirementInputError(
            f"legacy retirement observations is not a directory: {directory}"
        )
    unexpected = [
        path.name
        for path in directory.iterdir()
        if not path.is_dir() and path.name != ".append.lock"
    ]
    if unexpected:
        raise LegacyRetirementInputError(
            "legacy retirement observation directory contains loose files"
        )
    verified: list[dict[str, object]] = []
    previous_sha: str | None = None
    previous_signals: dict[str, Mapping[str, Any]] = {}
    for expected_sequence, bundle in enumerate(
        sorted(path for path in directory.iterdir() if path.is_dir()),
        start=1,
    ):
        if bundle.is_symlink():
            raise LegacyRetirementInputError(
                f"observation bundle must not be a symlink: {bundle}"
            )
        sources_directory = bundle / "sources"
        if sources_directory.is_symlink() or not sources_directory.is_dir():
            raise LegacyRetirementInputError(
                f"observation sources must be a real directory: {bundle}"
            )
        receipt_path = bundle / "receipt.json"
        try:
            receipt_bytes = _read_regular_nofollow(receipt_path)
            decoded = json.loads(receipt_bytes)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise LegacyRetirementInputError(
                f"could not read observation receipt: {receipt_path}"
            ) from error
        receipt = dict(_mapping(decoded, field=f"observation receipt {bundle.name}"))
        if receipt.get("schema_version") != _BUNDLE_SCHEMA:
            raise LegacyRetirementInputError(
                f"observation bundle schema is invalid: {bundle.name}"
            )
        if (
            receipt.get("receipt_id") != bundle.name
            or receipt.get("sequence") != expected_sequence
            or receipt.get("previous_receipt_sha256") != previous_sha
        ):
            raise LegacyRetirementInputError(
                f"observation receipt chain is invalid: {bundle.name}"
            )
        actual_receipt_sha = _bundle_receipt_sha256(receipt)
        if receipt.get("receipt_sha256") != actual_receipt_sha:
            raise LegacyRetirementInputError(
                f"observation receipt hash is invalid: {bundle.name}"
            )

        evidence = _mapping(
            receipt.get("evidence"),
            field=f"{bundle.name} evidence",
        )
        if set(evidence) != set(_VIOLATION_KEYS):
            raise LegacyRetirementInputError(
                f"{bundle.name} evidence population is incomplete"
            )
        violations = _mapping(
            receipt.get("violations"),
            field=f"{bundle.name} violations",
        )
        for dimension in _VIOLATION_KEYS:
            binding = _mapping(
                evidence[dimension],
                field=f"{bundle.name} {dimension} binding",
            )
            if binding.get("source_ref") != _SOURCE_REFS[dimension]:
                raise LegacyRetirementInputError(
                    f"{bundle.name} {dimension} source_ref is not canonical"
                )
            expected_path = f"sources/{dimension}.json"
            if binding.get("snapshot_path") != expected_path:
                raise LegacyRetirementInputError(
                    f"{bundle.name} {dimension} snapshot path drifted"
                )
            snapshot_path = bundle / expected_path
            try:
                raw = _read_regular_nofollow(snapshot_path)
            except OSError as error:
                raise LegacyRetirementInputError(
                    f"{bundle.name} {dimension} snapshot is unreadable"
                ) from error
            if binding.get("snapshot_sha256") != _sha256_bytes(raw):
                raise LegacyRetirementInputError(
                    f"{bundle.name} {dimension} snapshot hash is invalid"
                )
            if dimension == "unknown_ownership":
                owner, count = _owner_snapshot(
                    raw,
                    observed_at=_timestamp(
                        receipt.get("observed_at"),
                        field=f"{bundle.name} observed_at",
                    ),
                )
                owner_binding = _mapping(
                    receipt.get("formal_owner_census"),
                    field=f"{bundle.name} formal_owner_census",
                )
                if (
                    owner_binding.get("ok") != owner.get("ok")
                    or owner_binding.get("inventory_sha256")
                    != owner.get("inventory_sha256")
                    or {
                        key: owner_binding.get(key)
                        for key in (
                            "source_ref",
                            "snapshot_path",
                            "snapshot_sha256",
                        )
                    }
                    != dict(binding)
                ):
                    raise LegacyRetirementInputError(
                        f"{bundle.name} formal owner snapshot binding drifted"
                    )
            else:
                signal = _signal_payload(
                    raw,
                    dimension=dimension,
                    observed_at=_timestamp(
                        receipt.get("observed_at"),
                        field=f"{bundle.name} observed_at",
                    ),
                    max_age=timedelta(minutes=10),
                )
                previous_signal = previous_signals.get(dimension)
                if previous_signal is not None:
                    _assert_signal_continuity(
                        previous_signal,
                        signal,
                        dimension=dimension,
                    )
                previous_signals[dimension] = signal
                count = int(signal["count"])
            if violations.get(dimension) != count:
                raise LegacyRetirementInputError(
                    f"{bundle.name} {dimension} count drifted from snapshot"
                )
        verified.append(receipt)
        previous_sha = actual_receipt_sha
    return verified


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise LegacyRetirementInputError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise LegacyRetirementInputError(f"{field} must include a UTC offset")
    return value.astimezone(UTC)


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LegacyRetirementInputError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise LegacyRetirementInputError(f"{field} must be ISO-8601") from error
    return _utc(parsed, field=field)


def _positive_duration(value: timedelta, *, field: str) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise LegacyRetirementInputError(f"{field} must be positive")
    return value


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LegacyRetirementInputError(f"{field} must be an object")
    return value


def _normalize_observation(
    raw: object,
    *,
    assessed_at: datetime,
) -> _Observation:
    receipt = _mapping(raw, field="observation")
    if receipt.get("schema_version") != _RECEIPT_SCHEMA:
        raise LegacyRetirementInputError(
            "unsupported legacy retirement observation schema"
        )
    receipt_id = receipt.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        raise LegacyRetirementInputError("receipt_id is required")
    if receipt_id != receipt_id.strip():
        raise LegacyRetirementInputError("receipt_id must be normalized")
    observed_at = _timestamp(
        receipt.get("observed_at"),
        field=f"{receipt_id} observed_at",
    )
    if observed_at > assessed_at:
        raise LegacyRetirementInputError(f"{receipt_id} observed_at is in the future")

    owner = _mapping(
        receipt.get("formal_owner_census"),
        field=f"{receipt_id} formal_owner_census",
    )
    owner_ok = owner.get("ok")
    if not isinstance(owner_ok, bool):
        raise LegacyRetirementInputError(
            f"{receipt_id} formal owner census ok must be boolean"
        )
    inventory_sha = owner.get("inventory_sha256")
    if not isinstance(inventory_sha, str) or _SHA256.fullmatch(inventory_sha) is None:
        raise LegacyRetirementInputError(
            f"{receipt_id} formal owner census inventory_sha256 is invalid"
        )

    violations = _mapping(
        receipt.get("violations"),
        field=f"{receipt_id} violations",
    )
    if set(violations) != set(_VIOLATION_KEYS):
        raise LegacyRetirementInputError(
            f"{receipt_id} violations must contain the exact required keys"
        )
    normalized_violations: dict[str, int] = {}
    for key in _VIOLATION_KEYS:
        count = violations[key]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise LegacyRetirementInputError(
                f"{receipt_id} {key} must be a non-negative integer"
            )
        normalized_violations[key] = count
    if owner_ok != (normalized_violations["unknown_ownership"] == 0):
        raise LegacyRetirementInputError(
            f"{receipt_id} formal owner census conflicts with unknown_ownership"
        )

    evidence = _mapping(
        receipt.get("evidence"),
        field=f"{receipt_id} evidence",
    )
    if set(evidence) != set(_VIOLATION_KEYS):
        raise LegacyRetirementInputError(
            f"{receipt_id} evidence must contain the exact required keys"
        )
    source_refs: list[str] = []
    for key in _VIOLATION_KEYS:
        source = _mapping(
            evidence[key],
            field=f"{receipt_id} {key} evidence",
        )
        source_ref = source.get("source_ref")
        source_sha256 = source.get("snapshot_sha256")
        if (
            not isinstance(source_ref, str)
            or not source_ref.strip()
            or source_ref != source_ref.strip()
        ):
            raise LegacyRetirementInputError(
                f"{receipt_id} {key} evidence source_ref is invalid"
            )
        if (
            not isinstance(source_sha256, str)
            or _SHA256.fullmatch(source_sha256) is None
        ):
            raise LegacyRetirementInputError(
                f"{receipt_id} {key} evidence snapshot_sha256 is invalid"
            )
        source_refs.append(source_ref)
    if len(source_refs) != len(set(source_refs)):
        raise LegacyRetirementInputError(
            f"{receipt_id} evidence source_refs must be unique"
        )
    return _Observation(
        receipt_id=receipt_id,
        observed_at=observed_at,
        breaks_clean_window=any(normalized_violations.values()),
    )


def assess_sustained_clean_receipts(
    receipts: Iterable[object],
    *,
    assessed_at: datetime,
    required_window: timedelta = timedelta(days=14),
    max_gap: timedelta = timedelta(minutes=75),
    max_age: timedelta = timedelta(minutes=75),
) -> SustainedCleanReport:
    """Evaluate a consecutive, bounded-gap production observation window."""

    now = _utc(assessed_at, field="assessed_at")
    window = _positive_duration(required_window, field="required_window")
    allowed_gap = _positive_duration(max_gap, field="max_gap")
    allowed_age = _positive_duration(max_age, field="max_age")
    observations = sorted(
        (_normalize_observation(receipt, assessed_at=now) for receipt in receipts),
        key=lambda item: (item.observed_at, item.receipt_id),
    )
    ids = [item.receipt_id for item in observations]
    if len(ids) != len(set(ids)):
        raise LegacyRetirementInputError("duplicate receipt_id")
    timestamps = [item.observed_at for item in observations]
    if len(timestamps) != len(set(timestamps)):
        raise LegacyRetirementInputError("duplicate observed_at")

    current_segment: list[_Observation] = []
    segment_gap = False
    for observation in observations:
        if observation.breaks_clean_window:
            current_segment = []
            segment_gap = False
            continue
        if (
            current_segment
            and observation.observed_at - current_segment[-1].observed_at > allowed_gap
        ):
            current_segment = [observation]
            segment_gap = True
        else:
            current_segment.append(observation)

    reasons: list[str] = []
    recorded_from = current_segment[0].observed_at if current_segment else None
    recorded_to = current_segment[-1].observed_at if current_segment else None
    segment_complete = (
        recorded_from is not None
        and recorded_to is not None
        and recorded_to - recorded_from >= window
    )
    if segment_gap and not segment_complete:
        reasons.append("observation_gap")
    if recorded_to is None or now - recorded_to > allowed_age:
        reasons.append("observation_stale")
    if not segment_complete:
        reasons.append("clean_window_incomplete")
    ready = not reasons
    return SustainedCleanReport(
        schema_version="legacy-retirement-sustained-clean.v1",
        ready=ready,
        status=("sustained_clean_verified" if ready else "observation_blocked"),
        assessed_at=now.isoformat(),
        required_window_seconds=int(window.total_seconds()),
        max_gap_seconds=int(allowed_gap.total_seconds()),
        max_age_seconds=int(allowed_age.total_seconds()),
        observation_count=len(current_segment),
        recorded_from=(
            recorded_from.isoformat() if recorded_from is not None else None
        ),
        recorded_to=(recorded_to.isoformat() if recorded_to is not None else None),
        reason_codes=tuple(reasons),
    )


def _load_json_object(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LegacyRetirementInputError(
            f"could not read retirement dependency: {path}"
        ) from error
    return _mapping(payload, field=str(path))


def _hourly_schedule_row(config: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = config.get("cron_jobs")
    if not isinstance(rows, list):
        raise LegacyRetirementInputError("runtime schedules require cron_jobs")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("id") == _HOURLY_JOB_ID
    ]
    if len(matches) != 1:
        raise LegacyRetirementInputError(
            "runtime schedules require exactly one hourly dispatch policy row"
        )
    return matches[0]


def assess_hourly_dispatch_retirement(
    *,
    root: Path,
    owner_report: Mapping[str, object],
    sustained_clean_report: Mapping[str, object],
    host_evidence: Mapping[str, object],
    assessed_at: datetime,
    host_evidence_max_age: timedelta = timedelta(minutes=2),
) -> LegacyRetirementReport:
    """Prove the retired hourly shell executor has no physical live surface."""

    repo_root = Path(root)
    now = _utc(assessed_at, field="assessed_at")
    max_host_age = _positive_duration(
        host_evidence_max_age,
        field="host_evidence_max_age",
    )
    owner = _mapping(owner_report, field="owner_report")
    soak = _mapping(sustained_clean_report, field="sustained_clean_report")
    host = _mapping(host_evidence, field="host_evidence")

    blockers: list[str] = []
    if owner.get("schema_version") != _OWNER_SCHEMA or owner.get("ok") is not True:
        blockers.append("formal_owner_census_blocked")
    if soak.get("ready") is not True:
        blockers.append("sustained_clean_blocked")

    label_loaded = host.get("label_loaded")
    live_wrapper_exists = host.get("live_wrapper_exists")
    if not isinstance(label_loaded, bool) or not isinstance(
        live_wrapper_exists,
        bool,
    ):
        raise LegacyRetirementInputError("host evidence booleans are required")
    host_observed_at = _timestamp(
        host.get("observed_at"),
        field="host_evidence observed_at",
    )
    if now - host_observed_at > max_host_age:
        blockers.append("host_evidence_stale")
    if label_loaded:
        blockers.append("launchd_label_loaded")
    if live_wrapper_exists:
        blockers.append("live_wrapper_present")

    runtime = _load_json_object(repo_root / "config" / "runtime_schedules.json")
    row = _hourly_schedule_row(runtime)
    if row.get("status") != "retired":
        blockers.append("runtime_job_not_retired")
    if row.get("command") is not None:
        blockers.append("runtime_command_reference_present")
    if row.get("canonical_script") is not None:
        blockers.append("runtime_canonical_reference_present")
    if row.get("tcc_bypass_copy") is not None:
        blockers.append("runtime_tcc_reference_present")

    ownership = _load_json_object(
        repo_root / "config" / "scheduled_writer_ownership.json"
    )
    jobs = _mapping(
        ownership.get("jobs"),
        field="scheduled_writer_ownership jobs",
    )
    if _HOURLY_JOB_ID in jobs:
        blockers.append("writer_registry_reference_present")
    launchagents = _mapping(
        ownership.get("launchagents"),
        field="scheduled_writer_ownership launchagents",
    )
    launchagent = launchagents.get(_HOURLY_LABEL)
    if launchagent is not None:
        blockers.append("writer_launchagent_reference_present")

    wrapper_manifest = _load_json_object(
        repo_root / "config" / "cron_wrapper_manifest.json"
    )
    wrappers = _mapping(
        wrapper_manifest.get("wrappers"),
        field="cron_wrapper_manifest wrappers",
    )
    if _HOURLY_WRAPPER in wrappers:
        blockers.append("wrapper_manifest_reference_present")

    canonical_path = repo_root / "scripts" / _HOURLY_WRAPPER
    plist_path = repo_root / "ops" / "launchd" / f"{_HOURLY_LABEL}.plist"
    if os.path.lexists(canonical_path):
        blockers.append("canonical_wrapper_present")
    if os.path.lexists(plist_path):
        blockers.append("launchd_plist_present")

    blocker_codes = tuple(sorted(set(blockers)))
    ready = not blocker_codes
    return LegacyRetirementReport(
        schema_version="legacy-execution-retirement.v1",
        ready=ready,
        status=("physically_retired_verified" if ready else "retirement_blocked"),
        assessed_at=now.isoformat(),
        blocker_codes=blocker_codes,
        evidence={
            "formal_owner_inventory_sha256": owner.get("inventory_sha256"),
            "sustained_clean_status": soak.get("status"),
            "host_observed_at": host_observed_at.isoformat(),
            "runtime_policy_status": row.get("status"),
            "canonical_wrapper": str(canonical_path),
            "launchd_plist": str(plist_path),
        },
    )


__all__ = [
    "LegacyRetirementInputError",
    "LegacyRetirementReport",
    "SustainedCleanReport",
    "assess_hourly_dispatch_retirement",
    "assess_sustained_clean_receipts",
]
