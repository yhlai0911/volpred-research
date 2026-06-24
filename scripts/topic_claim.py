#!/usr/bin/env python3
"""Atomically claim research topics before assigning experiment work.

This is the topic-side guard for the 2026-06-23 journal-discovery race:
multiple agents can see the same backlog candidate, but only one should own a
normalized topic at a time.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "storage" / "ops" / "topic_claims.json"

RELEASED_STATUSES = {"released", "failed", "abandoned", "blocked"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_topic(topic: str) -> str:
    return " ".join(topic.lower().split())


def topic_hash(topic: str) -> str:
    normalized = normalize_topic(topic)
    if not normalized:
        raise ValueError("topic is required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _default_lock_path(ledger_path: Path) -> Path:
    return ledger_path.parent / "locks" / f"{ledger_path.stem}.lock"


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass  # silent-ok: directory fsync is a best-effort durability improvement, not part of claim correctness


def _load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "claims": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"topic claim ledger unreadable: path={path} error={type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"topic claim ledger must be an object: path={path}")
    if data.get("schema_version") not in (None, 1):
        raise ValueError(f"unsupported topic claim ledger schema_version={data.get('schema_version')!r}")
    claims = data.get("claims", [])
    if not isinstance(claims, list):
        raise ValueError(f"topic claim ledger claims must be a list: path={path}")
    data.setdefault("schema_version", 1)
    data["claims"] = claims
    return data


def _blocking_claim(claims: list[Any], digest: str) -> dict[str, Any] | None:
    for rec in reversed(claims):
        if not isinstance(rec, dict):
            continue
        if rec.get("topic_hash") != digest:
            continue
        if str(rec.get("status") or "claimed") not in RELEASED_STATUSES:
            return rec
    return None


def claim_topic(
    *,
    topic: str,
    claimed_by: str,
    k_id: str | None = None,
    ledger_path: Path = LEDGER_PATH,
    lock_path: Path | None = None,
) -> dict[str, Any]:
    """Claim a normalized topic under an exclusive lock.

    Returns ``ok=False`` when the topic already has a non-released claim.  The
    existing claim is included so callers can skip or reuse its K-id without
    racing another agent.
    """
    if not claimed_by.strip():
        raise ValueError("claimed_by is required")
    normalized = normalize_topic(topic)
    if not normalized:
        raise ValueError("topic is required")

    ledger_path = Path(ledger_path)
    lock_path = Path(lock_path) if lock_path is not None else _default_lock_path(ledger_path)
    digest = topic_hash(topic)

    with _exclusive_lock(lock_path):
        ledger = _load_ledger(ledger_path)
        claims = ledger.setdefault("claims", [])
        existing = _blocking_claim(claims, digest)
        if existing is not None:
            return {
                "ok": False,
                "reason": "already_claimed",
                "topic_hash": digest,
                "existing_k_id": existing.get("k_id") or None,
                "existing_claimed_by": existing.get("claimed_by") or None,
                "existing_status": existing.get("status") or "claimed",
            }

        now = _now_iso()
        record = {
            "topic_hash": digest,
            "topic": topic,
            "normalized_topic": normalized,
            "claimed_by": claimed_by,
            "claimed_at": now,
            "k_id": k_id or "",
            "status": "claimed",
        }
        claims.append(record)
        ledger["updated_at"] = now
        _atomic_write_json(ledger_path, ledger)
        return {"ok": True, **record}


def set_topic_status(
    *,
    topic: str,
    status: str,
    updated_by: str,
    ledger_path: Path = LEDGER_PATH,
    lock_path: Path | None = None,
) -> dict[str, Any]:
    if not updated_by.strip():
        raise ValueError("updated_by is required")
    if not status.strip():
        raise ValueError("status is required")
    ledger_path = Path(ledger_path)
    lock_path = Path(lock_path) if lock_path is not None else _default_lock_path(ledger_path)
    digest = topic_hash(topic)

    with _exclusive_lock(lock_path):
        ledger = _load_ledger(ledger_path)
        claims = ledger.setdefault("claims", [])
        for rec in reversed(claims):
            if isinstance(rec, dict) and rec.get("topic_hash") == digest:
                now = _now_iso()
                rec["status"] = status
                rec["updated_at"] = now
                rec["updated_by"] = updated_by
                ledger["updated_at"] = now
                _atomic_write_json(ledger_path, ledger)
                return {"ok": True, **rec}
        return {"ok": False, "reason": "not_found", "topic_hash": digest}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    claim = sub.add_parser("claim", help="atomically claim a normalized topic")
    claim.add_argument("--topic", required=True)
    claim.add_argument("--owner", "--claimed-by", dest="claimed_by", required=True)
    claim.add_argument("--k-id", default="")
    claim.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    claim.add_argument("--lock", type=Path, default=None)

    status = sub.add_parser("status", help="update the latest claim status for a topic")
    status.add_argument("--topic", required=True)
    status.add_argument("--status", required=True)
    status.add_argument("--owner", "--updated-by", dest="updated_by", required=True)
    status.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    status.add_argument("--lock", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "claim":
            result = claim_topic(
                topic=args.topic,
                claimed_by=args.claimed_by,
                k_id=args.k_id,
                ledger_path=args.ledger,
                lock_path=args.lock,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.cmd == "status":
            result = set_topic_status(
                topic=args.topic,
                status=args.status,
                updated_by=args.updated_by,
                ledger_path=args.ledger,
                lock_path=args.lock,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
