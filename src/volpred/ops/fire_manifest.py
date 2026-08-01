"""Legacy fire-output declarations retained for shadow and foreign attribution.

Supersession (2026-07-27)
-------------------------
Issue #43 made producer-scoped workspaces, declared output paths, and durable
machine settlement receipts the canonical ownership contract. Issue #44 retires
PHASE-Z's recognizer physically after its acceptance window. Consequently this
module has **no commit-cutover authority**: manifests remain useful temporary
observability/foreign-attribution evidence, but even green Stage-2 metrics may
not activate the manifest-driven Stage 3 described by the older design below.
``assess_shadow_records`` enforces that boundary mechanically.

Why this module exists
----------------------
PHASE-Z decides authorship with ``owned = dirty_now - baseline``: "whatever
turned dirty between the pre-fire snapshot and now is this fire's". That is not
ownership, it is *first observation inside a window*, and on a checkout shared by
~24 machine writers plus human/codex sessions plus (since max_slots 2→4) up to
four concurrent dispatch slots, the inference is wrong by construction:

  - slot A's baseline is taken before slot B starts writing, so B's bytes land
    inside A's window and read as A's output;
  - a path already dirty at fire start but edited again by this fire is filed as
    "someone else's", and the fire's contribution is dropped;
  - two writers touching one path cannot be split by a set difference at all.

The external adjudication (docs/governance/2026-07/phase_z_ownership_external_review.md)
put it in one line: *ownership must be produced by execution isolation, not
inferred by a cleanup layer afterwards*. This module is the cheaper half of that
verdict — the part that works even when isolation is unavailable (canonical
checkout writers, scheduled jobs, non-isolated fires): **ownership is DECLARED at
write time, by the writer, into a manifest scoped to that fire.**

A manifest answers "who wrote this path" by record, not by arithmetic. PHASE-Z's
question then stops being "which dirty paths look like mine" (unanswerable) and
becomes "which paths did I declare" (a lookup).

Where manifests live
--------------------
``<git-common-dir>/volpred_fire_manifests/<fire_id>.json``.

The git *common* dir, not the per-worktree git dir, on purpose: a fire running in
a producer-scoped worktree must be readable by the canonical checkout's PHASE-Z,
so the ledger has to be shared across linked worktrees. It is inside the git dir
rather than under ``storage/`` for the same reason the pre-fire snapshot is:
``git status`` never walks it, so the ledger can never become the orphan file it
exists to prevent, and needs no ``.gitignore`` rule to stay invisible.

Concurrency
-----------
Every mutation is a read-modify-write under an ``fcntl`` exclusive lock on the
manifest's own file, then an atomic ``os.replace``. Four slots appending to four
different manifests never contend; two tools appending to the *same* manifest
serialise. A reader never sees a half-written manifest.

States
------
``open``       — the fire is running; entries may still be appended.
``sealed``     — the fire finished and declared its final path set (digest pinned
                 to the bytes it declared). This is what PHASE-Z would commit.
``committed``  — landed; carries the commit oid.
``abandoned``  — the fire died / its output was rejected; the paths become
                 orphans with a named last owner instead of anonymous residue.

An ``open`` manifest older than ``MAX_AGE_S`` is ``stale``: its producer died
without sealing. Stale manifests are excluded from live ownership (so they cannot
keep claiming paths forever) but are still reported, because "this path's last
declared owner was job X, which died" is exactly the attribution the current
orphan alerts cannot produce.

Scope note (legacy stage 1)
---------------------------
Nothing here mutates git and nothing here is wired into PHASE-Z's commit
decision. ``shadow_compare`` exists to run both answers side by side — declared
vs inferred — and log the delta, so the size of the disagreement is measured
without authorizing any behaviour change from it.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import statistics
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from volpred.ops.git_writer_lock import GitWriterLockError, git_common_dir

LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MANIFEST_DIRNAME = "volpred_fire_manifests"
SHADOW_LOG_BASENAME = "volpred_phase_z_shadow.jsonl"

# Same ceiling as PHASE-Z's pre-fire snapshot (_SNAPSHOT_MAX_AGE_S): a fire is
# bounded by the worker timeout (~50min); six hours is "the producer is dead".
MAX_AGE_S = 6 * 3600

STATE_OPEN = "open"
STATE_SEALED = "sealed"
STATE_COMMITTED = "committed"
STATE_ABANDONED = "abandoned"
_LIVE_STATES = (STATE_OPEN, STATE_SEALED)
_TERMINAL_STATES = (STATE_COMMITTED, STATE_ABANDONED)

OP_WRITE = "write"
OP_DELETE = "delete"
_OPS = (OP_WRITE, OP_DELETE)

# A fire_id becomes a filename, so it may not escape the manifest directory.
_FIRE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class FireManifestError(RuntimeError):
    """Refused a manifest operation. Never raised for a *missing* manifest."""


# ── paths ────────────────────────────────────────────────────────────────────

def manifest_dir(repo_root: Path) -> Path:
    """``<git-common-dir>/volpred_fire_manifests`` (created on demand)."""
    try:
        common = git_common_dir(Path(repo_root))
    except GitWriterLockError as exc:
        raise FireManifestError(f"cannot resolve git common dir: {exc}") from exc
    target = common / MANIFEST_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def manifest_path(repo_root: Path, fire_id: str) -> Path:
    return manifest_dir(repo_root) / f"{_validated_fire_id(fire_id)}.json"


def shadow_log_path(repo_root: Path) -> Path:
    return manifest_dir(repo_root).parent / SHADOW_LOG_BASENAME


def _validated_fire_id(fire_id: str) -> str:
    if not isinstance(fire_id, str) or not _FIRE_ID_RE.match(fire_id):
        raise FireManifestError(
            f"invalid fire_id {fire_id!r}: must match {_FIRE_ID_RE.pattern} "
            "(it becomes a filename)"
        )
    return fire_id


def new_fire_id(*, slot_id: str = "", job_id: str = "", now: float | None = None) -> str:
    """A collision-free id for one fire: ``<utc-stamp>-<slot>-<job8>``."""
    stamp = datetime.fromtimestamp(now if now is not None else time.time(), tz=timezone.utc)
    parts = [stamp.strftime("%Y%m%dT%H%M%S%fZ")]
    if slot_id:
        parts.append(re.sub(r"[^A-Za-z0-9]+", "-", slot_id).strip("-") or "slot")
    if job_id:
        parts.append(re.sub(r"[^A-Za-z0-9]+", "", job_id)[:8] or "job")
    return "-".join(p for p in parts if p)


# ── low-level io ─────────────────────────────────────────────────────────────

def _now_iso(now: float | None = None) -> str:
    return datetime.fromtimestamp(
        now if now is not None else time.time(), tz=timezone.utc
    ).isoformat().replace("+00:00", "Z")


def _read_raw(path: Path) -> dict[str, Any] | None:
    """Parsed manifest, or None when missing/unreadable.

    Unreadable is deliberately *not* an exception: a corrupt manifest must not be
    able to wedge every reader (the 2026-07-18 unreadable-receipt lesson — a
    fail-closed read left the module permanently unable to record ownership and
    silent about it). It is logged and treated as "no declaration", which routes
    the affected paths to the orphan lane where a human sees them.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:  # silent-ok: an absent manifest is the normal "nothing declared yet" state, not a fault (unreadable is warned below)
        return None
    except (OSError, ValueError) as exc:
        LOG.warning("fire_manifest: %s unreadable (%s) — treating as no declaration",
                    path.name, exc)
        return None
    if not isinstance(payload, dict) or "fire_id" not in payload:
        LOG.warning("fire_manifest: %s is not a manifest — treating as no declaration",
                    path.name)
        return None
    return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _mutate(repo_root: Path, fire_id: str, fn) -> dict[str, Any]:
    """Read-modify-write one manifest under an exclusive lock on its own file."""
    path = manifest_path(repo_root, fire_id)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            payload = _read_raw(path)
            updated = fn(payload)
            _atomic_write(path, updated)
            return updated
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


# ── declaration api ──────────────────────────────────────────────────────────

def open_manifest(
    repo_root: Path,
    *,
    fire_id: str,
    actor: str,
    job_id: str = "",
    slot_id: str = "",
    workspace_kind: str = "canonical",
    workspace_path: str = "",
    branch: str = "",
    task_ids: list[str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Declare that ``fire_id`` is about to start producing output.

    Idempotent: re-opening an existing live manifest returns it untouched, so a
    retried attempt of the same fire keeps one ledger instead of splitting its
    output across two (the 2026-07-21 partial-commit shape: correctness is a
    property of the change *set*, not of individual paths).
    """
    _validated_fire_id(fire_id)
    if not actor:
        raise FireManifestError("actor is required: an unnamed owner is not ownership")

    def _fn(existing: dict[str, Any] | None) -> dict[str, Any]:
        if existing is not None and existing.get("state") in _LIVE_STATES:
            return existing
        return {
            "schema": SCHEMA_VERSION,
            "fire_id": fire_id,
            "actor": actor,
            "job_id": job_id,
            "slot_id": slot_id,
            "workspace": {
                "kind": workspace_kind,
                "path": workspace_path,
                "branch": branch,
            },
            "task_ids": list(task_ids or []),
            "opened_at": _now_iso(now),
            "opened_at_ts": now if now is not None else time.time(),
            "state": STATE_OPEN,
            "entries": [],
            "seal": None,
            "closed_at": None,
            "commit": None,
        }

    return _mutate(repo_root, fire_id, _fn)


def _fingerprint(repo_root: Path, rel: str) -> tuple[str | None, int | None]:
    target = Path(repo_root) / rel
    try:
        data = target.read_bytes()
    except (OSError, IsADirectoryError):
        return None, None
    return hashlib.sha256(data).hexdigest(), len(data)


def record(
    repo_root: Path,
    fire_id: str,
    path: str,
    *,
    op: str = OP_WRITE,
    tool: str = "",
    note: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Declare one repo-relative path as this fire's output.

    Called at the moment of the write, by whoever wrote it. The bytes are
    fingerprinted here so a later reader can tell "the file I declared" from "the
    file someone else has since overwritten" — the same hash-pinning the
    failed-closeout receipt already relies on.

    A ``delete`` records ``sha256: null``: there are no bytes, but the *deletion*
    is still this fire's output and still has to be staged.
    """
    if op not in _OPS:
        raise FireManifestError(f"unknown op {op!r}: expected one of {_OPS}")
    rel = _normalise_rel(repo_root, path)
    sha, size = (None, None) if op == OP_DELETE else _fingerprint(repo_root, rel)

    def _fn(existing: dict[str, Any] | None) -> dict[str, Any]:
        if existing is None:
            raise FireManifestError(
                f"no manifest for fire {fire_id!r}: open_manifest() before recording"
            )
        if existing.get("state") != STATE_OPEN:
            raise FireManifestError(
                f"manifest {fire_id!r} is {existing.get('state')!r}, not open — "
                "a sealed fire cannot grow new output"
            )
        entries = list(existing.get("entries") or [])
        entries.append({
            "path": rel,
            "op": op,
            "at": _now_iso(now),
            "sha256": sha,
            "bytes": size,
            "tool": tool,
            "note": note,
        })
        return {**existing, "entries": entries}

    return _mutate(repo_root, fire_id, _fn)


def _normalise_rel(repo_root: Path, path: str) -> str:
    """Repo-relative POSIX path. Absolute paths inside the repo are accepted."""
    raw = Path(path)
    if raw.is_absolute():
        try:
            raw = raw.resolve().relative_to(Path(repo_root).resolve())
        except ValueError as exc:
            raise FireManifestError(f"{path!r} is outside {repo_root}") from exc
    rel = raw.as_posix().lstrip("./")
    if not rel or rel.startswith("../"):
        raise FireManifestError(f"{path!r} does not name a repo-relative path")
    return rel


def declared_paths(manifest: dict[str, Any]) -> dict[str, str]:
    """``{path: op}`` for the manifest's net declaration (last op per path wins)."""
    out: dict[str, str] = {}
    for entry in manifest.get("entries") or []:
        rel = entry.get("path")
        if isinstance(rel, str) and rel:
            out[rel] = entry.get("op", OP_WRITE)
    return out


def seal(repo_root: Path, fire_id: str, *, now: float | None = None) -> dict[str, Any]:
    """Freeze the declared path set and pin it to the bytes on disk right now.

    Sealing is what makes the change set atomic: the digest covers *all* declared
    paths together, so "commit half of them" is not expressible. A path whose
    bytes moved after the seal is detectable by re-fingerprinting.
    """
    def _fn(existing: dict[str, Any] | None) -> dict[str, Any]:
        if existing is None:
            raise FireManifestError(f"no manifest for fire {fire_id!r}")
        if existing.get("state") in _TERMINAL_STATES:
            raise FireManifestError(
                f"manifest {fire_id!r} is already {existing['state']!r}")
        if existing.get("state") == STATE_SEALED:
            return existing
        paths = declared_paths(existing)
        pinned = []
        for rel in sorted(paths):
            sha, size = (None, None) if paths[rel] == OP_DELETE else _fingerprint(repo_root, rel)
            pinned.append({"path": rel, "op": paths[rel], "sha256": sha, "bytes": size})
        digest = hashlib.sha256(
            json.dumps([(p["path"], p["op"], p["sha256"]) for p in pinned],
                       sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            **existing,
            "state": STATE_SEALED,
            "seal": {"at": _now_iso(now), "paths": pinned, "digest": digest},
        }

    return _mutate(repo_root, fire_id, _fn)


def close(
    repo_root: Path,
    fire_id: str,
    *,
    state: str,
    commit: str = "",
    reason: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Move a manifest to a terminal state (``committed`` / ``abandoned``).

    ``abandoned`` is not a failure to hide — it is the named exit an orphan file
    has never had. The paths stop being claimed, but the record of *who* last
    claimed them survives, which is the whole difference between "40 files nobody
    owns" and "40 files job X abandoned at 03:12".
    """
    if state not in _TERMINAL_STATES:
        raise FireManifestError(f"{state!r} is not terminal: expected {_TERMINAL_STATES}")

    def _fn(existing: dict[str, Any] | None) -> dict[str, Any]:
        if existing is None:
            raise FireManifestError(f"no manifest for fire {fire_id!r}")
        return {
            **existing,
            "state": state,
            "closed_at": _now_iso(now),
            "commit": commit or None,
            "close_reason": reason,
        }

    return _mutate(repo_root, fire_id, _fn)


# ── reading ──────────────────────────────────────────────────────────────────

def read(repo_root: Path, fire_id: str) -> dict[str, Any] | None:
    return _read_raw(manifest_path(repo_root, fire_id))


def iter_manifests(repo_root: Path) -> Iterator[dict[str, Any]]:
    for path in sorted(manifest_dir(repo_root).glob("*.json")):
        payload = _read_raw(path)
        if payload is not None:
            yield payload


def is_stale(manifest: dict[str, Any], *, now: float | None = None) -> bool:
    """An ``open`` manifest whose producer has been gone longer than MAX_AGE_S."""
    if manifest.get("state") != STATE_OPEN:
        return False
    opened = manifest.get("opened_at_ts")
    if not isinstance(opened, (int, float)):
        return True  # no usable clock on it → cannot vouch for it
    age = (now if now is not None else time.time()) - opened
    return age > MAX_AGE_S or age < 0


def resolve_ownership(
    repo_root: Path,
    dirty: set[str] | list[str],
    *,
    fire_id: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Split a dirty set by *declared* ownership.

    Returns:
      ``owned``     — declared by ``fire_id`` and by nobody else alive.
      ``contested`` — declared by more than one live manifest (``{path: [ids]}``).
                      Never auto-committed: two declared owners is a real
                      conflict, and it is the one case a set difference silently
                      resolved the wrong way.
      ``foreign``   — declared by exactly one *other* live manifest
                      (``{path: fire_id}``). Attributed, not anonymous.
      ``stale``     — last declared by a manifest whose producer died
                      (``{path: fire_id}``). Has a named last owner.
      ``orphan``    — dirty and declared by nobody. This is the only residual
                      lane, and it now has a size that can be watched instead of
                      being the default answer for everything.
    """
    dirty_set = set(dirty)
    live: dict[str, list[str]] = {}
    stale_claims: dict[str, str] = {}
    for manifest in iter_manifests(repo_root):
        state = manifest.get("state")
        mid = manifest.get("fire_id", "")
        if state in _TERMINAL_STATES:
            continue
        paths = set(declared_paths(manifest))
        if is_stale(manifest, now=now):
            for rel in paths & dirty_set:
                stale_claims[rel] = mid
            continue
        for rel in paths & dirty_set:
            live.setdefault(rel, []).append(mid)

    owned: list[str] = []
    contested: dict[str, list[str]] = {}
    foreign: dict[str, str] = {}
    for rel, claimants in live.items():
        unique = sorted(set(claimants))
        if len(unique) > 1:
            contested[rel] = unique
        elif fire_id is not None and unique[0] == fire_id:
            owned.append(rel)
        else:
            foreign[rel] = unique[0]

    claimed = set(live) | set(stale_claims)
    return {
        "fire_id": fire_id,
        "owned": sorted(owned),
        "contested": contested,
        "foreign": foreign,
        "stale": {k: stale_claims[k] for k in sorted(stale_claims)},
        "orphan": sorted(dirty_set - claimed),
    }


def prune(repo_root: Path, *, max_age_s: float = 7 * 24 * 3600,
          now: float | None = None) -> list[str]:
    """Delete terminal manifests older than ``max_age_s``. Returns removed ids.

    Only terminal ones: a stale ``open`` manifest is evidence about an unfinished
    fire and must outlive the fire that abandoned it.
    """
    removed: list[str] = []
    cutoff = (now if now is not None else time.time()) - max_age_s
    for manifest in iter_manifests(repo_root):
        if manifest.get("state") not in _TERMINAL_STATES:
            continue
        opened = manifest.get("opened_at_ts")
        if isinstance(opened, (int, float)) and opened > cutoff:
            continue
        fid = manifest.get("fire_id", "")
        try:
            manifest_path(repo_root, fid).unlink(missing_ok=True)
            manifest_path(repo_root, fid).with_name(f"{fid}.json.lock").unlink(missing_ok=True)
        except (OSError, FireManifestError) as exc:
            LOG.warning("fire_manifest: cannot prune %s (%s)", fid, exc)
            continue
        removed.append(fid)
    return removed


# ── shadow mode ──────────────────────────────────────────────────────────────

def shadow_compare(
    repo_root: Path,
    *,
    dirty_now: set[str] | list[str],
    baseline: set[str] | list[str] | None,
    fire_id: str | None = None,
    fire_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Both answers, side by side: what PHASE-Z *infers* vs what was *declared*.

    ``inferred`` reproduces PHASE-Z's arithmetic exactly (``dirty_now - baseline``)
    without calling into it, so running this cannot perturb the live commit path.
    The interesting numbers are the two disagreement sets:

      ``inferred_not_declared`` — PHASE-Z would commit these under this fire's
          name although nobody declared them. Every historical mis-attribution
          incident lives in this set.
      ``declared_not_inferred`` — this fire declared them but the arithmetic
          misses them (typically: already dirty at fire start, so filed foreign
          and dropped). Every "my contribution vanished" incident lives here.

    Read-only. Never mutates a manifest, never touches git, never raises.
    """
    dirty_set = set(dirty_now)
    base = None if baseline is None else set(baseline)
    inferred = sorted(dirty_set - base) if base is not None else []
    ownership = resolve_ownership(repo_root, dirty_set, fire_id=fire_id, now=now)
    wanted = {str(item) for item in (fire_ids or []) if str(item)}
    if fire_id:
        wanted.add(fire_id)
    if wanted:
        declared = {
            rel
            for manifest in iter_manifests(repo_root)
            if manifest.get("fire_id") in wanted
            and manifest.get("state") in _LIVE_STATES
            and not is_stale(manifest, now=now)
            for rel in declared_paths(manifest)
            if rel in dirty_set
        }
    else:
        declared = set(ownership["owned"])
    inferred_set = set(inferred)
    return {
        "at": _now_iso(now),
        "fire_id": fire_id,
        "fire_ids": sorted(wanted),
        "dirty_total": len(dirty_set),
        "baseline_available": base is not None,
        "inferred": inferred,
        "declared": sorted(declared),
        "inferred_not_declared": sorted(inferred_set - declared),
        "declared_not_inferred": sorted(declared - inferred_set),
        "agree": sorted(inferred_set & declared),
        "contested": ownership["contested"],
        "foreign_attributed": ownership["foreign"],
        "stale_attributed": ownership["stale"],
        "orphan": ownership["orphan"],
    }


def append_shadow_record(repo_root: Path, record_payload: dict[str, Any]) -> bool:
    """Append one shadow observation as JSONL. Never raises.

    Written into the git dir alongside the manifests: an observability log that
    lives in the working tree would itself become an uncommitted dirty path —
    i.e. the exact failure this whole module exists to remove.
    """
    try:
        target = shadow_log_path(repo_root)
        with open(target, "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(json.dumps(record_payload, ensure_ascii=False, sort_keys=True) + "\n")
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return True
    except (OSError, ValueError, FireManifestError) as exc:
        LOG.warning("fire_manifest: cannot append shadow record (%s)", exc)
        return False


def observe_shadow(
    repo_root: Path,
    *,
    dirty_now: set[str] | list[str],
    baseline: set[str] | list[str] | None,
    fire_id: str | None = None,
    fire_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """``shadow_compare`` + log it, swallowing every error.

    This is the only function a live caller (PHASE-Z, stage 1) should use: it is
    total. A bug in the shadow path must not be able to affect a commit decision.
    """
    try:
        payload = shadow_compare(repo_root, dirty_now=dirty_now, baseline=baseline,
                                 fire_id=fire_id, fire_ids=fire_ids, now=now)
    except Exception as exc:  # noqa: BLE001 — shadow must never propagate
        LOG.warning("fire_manifest: shadow compare failed (%s)", exc)
        return None
    if payload["inferred_not_declared"] or payload["declared_not_inferred"]:
        LOG.info(
            "fire_manifest shadow: declared=%d inferred=%d "
            "inferred_not_declared=%d declared_not_inferred=%d orphan=%d",
            len(payload["declared"]), len(payload["inferred"]),
            len(payload["inferred_not_declared"]), len(payload["declared_not_inferred"]),
            len(payload["orphan"]),
        )
    append_shadow_record(repo_root, payload)
    return payload


# ── stage-2 acceptance audit ────────────────────────────────────────────────

def _shadow_timestamp(record: Mapping[str, Any], index: int) -> datetime:
    raw = record.get("at")
    if not isinstance(raw, str) or not raw.strip():
        raise FireManifestError(f"shadow record {index} has invalid at")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise FireManifestError(
            f"shadow record {index} has invalid at"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FireManifestError(f"shadow record {index} has invalid at")
    return parsed.astimezone(UTC)


def assess_shadow_records(
    records: Sequence[Mapping[str, Any]],
    *,
    assessed_at: datetime,
    expected_fires: Sequence[Mapping[str, Any]],
    expected_schedule: Sequence[datetime],
    window_days: int = 7,
    identity_threshold: float = 0.95,
    median_missing_threshold: float = 2.0,
    max_observation_gap_multiplier: float = 2.0,
    classify_path: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Assess the historical Stage-2 shadow without granting cutover authority.

    The 2026-07-22 experiment expected a seven-day manifest shadow to authorize
    a later manifest-driven PHASE-Z.  Issue #43 subsequently made isolated
    workspaces plus machine settlement receipts the canonical producer contract,
    and Issue #44 requires physical removal of the recognizer instead.  This
    assessor therefore preserves the useful measurements while making the old
    inference impossible: even a completely green historical window returns
    ``manifest_cutover_eligible=False``.

    ``classify_path`` is deliberately injected by the caller.  The shadow ledger
    owns observations, not the temporary PHASE-Z machine-state namespace; the
    audit CLI can use that live classifier without duplicating it here.
    """
    if window_days <= 0:
        raise FireManifestError("window_days must be positive")
    if not 0 < identity_threshold <= 1:
        raise FireManifestError("identity_threshold must be in (0, 1]")
    if median_missing_threshold < 0:
        raise FireManifestError("median_missing_threshold must be non-negative")
    if max_observation_gap_multiplier < 1:
        raise FireManifestError(
            "max_observation_gap_multiplier must be at least 1"
        )
    if not records:
        raise FireManifestError("shadow evidence is empty")
    if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise FireManifestError("assessed_at must be timezone-aware")
    assessed_at = assessed_at.astimezone(UTC)

    schedule_input = list(expected_schedule)
    if len(schedule_input) < 2:
        raise FireManifestError("expected_schedule must contain at least two slots")
    for index, slot in enumerate(schedule_input):
        if not isinstance(slot, datetime) or slot.tzinfo is None or slot.utcoffset() is None:
            raise FireManifestError(
                f"expected_schedule slot {index} must be timezone-aware"
            )
    schedule = sorted({slot.astimezone(UTC) for slot in schedule_input})

    normalized: list[
        tuple[
            datetime,
            Mapping[str, Any],
            set[str],
            list[str],
            list[str],
            list[str],
        ]
    ] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise FireManifestError(f"shadow record {index} is not an object")
        timestamp = _shadow_timestamp(record, index)
        if timestamp > assessed_at:
            raise FireManifestError(f"shadow record {index} is newer than assessed_at")

        fire_id = record.get("fire_id")
        if fire_id is not None and (
            not isinstance(fire_id, str) or not fire_id.strip()
        ):
            raise FireManifestError(
                f"shadow record {index} fire_id must be null or a non-empty string"
            )
        # Rows written before cohort-aware attribution added ``fire_ids`` have
        # only the nullable scalar ``fire_id``. Preserve them as explicit
        # identity-missing evidence; a present container is still strict, so
        # values such as ``[null]`` can never masquerade as an identity.
        fire_ids = record.get("fire_ids", [])
        if not isinstance(fire_ids, list) or not all(
            isinstance(value, str) and value.strip() for value in fire_ids
        ):
            raise FireManifestError(
                f"shadow record {index} fire_ids must be a string list"
            )
        if not isinstance(record.get("baseline_available"), bool):
            raise FireManifestError(
                f"shadow record {index} baseline_available must be boolean"
            )

        path_lists: dict[str, list[str]] = {}
        for field in ("inferred", "declared", "inferred_not_declared"):
            values = record.get(field)
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                raise FireManifestError(
                    f"shadow record {index} {field} must be a string list"
                )
            path_lists[field] = values

        identities = {value.strip() for value in fire_ids}
        if isinstance(fire_id, str):
            identities.add(fire_id.strip())
        normalized.append((
            timestamp,
            record,
            identities,
            path_lists["inferred_not_declared"],
            path_lists["declared"],
            path_lists["inferred"],
        ))
    normalized.sort(key=lambda item: item[0])

    evidence_start = normalized[0][0]
    window_end = assessed_at
    window_start = assessed_at - timedelta(days=window_days)
    window = [item for item in normalized if window_start <= item[0] <= window_end]

    schedule_window = [
        slot for slot in schedule if window_start <= slot <= window_end
    ]
    if len(schedule_window) < 2:
        raise FireManifestError(
            "expected_schedule does not cover the assessment window"
        )
    schedule_gaps = [
        (right - left).total_seconds()
        for left, right in zip(schedule_window, schedule_window[1:], strict=False)
    ]
    canonical_gap_s = max(schedule_gaps)
    max_allowed_gap_s = canonical_gap_s * max_observation_gap_multiplier

    observation_points = [window_start, *(item[0] for item in window), window_end]
    observation_points = sorted(set(observation_points))
    observation_gaps = [
        (right - left).total_seconds()
        for left, right in zip(observation_points, observation_points[1:], strict=False)
    ]
    max_observation_gap_s = max(observation_gaps, default=window_days * 86400)
    latest_observation = window[-1][0] if window else None
    evidence_age_s = (
        (assessed_at - latest_observation).total_seconds()
        if latest_observation is not None
        else None
    )
    fresh = evidence_age_s is not None and evidence_age_s <= max_allowed_gap_s
    full_window = bool(window) and max_observation_gap_s <= max_allowed_gap_s

    identity_records = [item for item in window if item[2]]
    total = len(window)
    identity_total = len(identity_records)
    identity_coverage = identity_total / total if total else 0.0
    # The canonical acceptance criterion is paths/fire ("檔/班"), not
    # paths/identified-fire.  Missing identity is itself a failed observation
    # and may not remove a high-gap shift from the median denominator.
    missing_lengths = [len(item[3]) for item in window]
    median_missing = (
        statistics.median(missing_lengths) if missing_lengths else None
    )
    baseline_available = sum(
        item[1].get("baseline_available") is True for item in window
    )
    baseline_throughout = baseline_available == total
    baseline_contract_violations = sum(
        item[1].get("baseline_available") is False and bool(item[5])
        for item in window
    )
    declared_signal_total = sum(bool(item[4]) for item in identity_records)

    expected_by_id: dict[str, datetime] = {}
    for index, fire in enumerate(expected_fires):
        if not isinstance(fire, Mapping):
            raise FireManifestError(f"expected fire {index} is not an object")
        fire_id = fire.get("fire_id")
        if not isinstance(fire_id, str) or not fire_id.strip():
            raise FireManifestError(
                f"expected fire {index} has invalid fire_id"
            )
        opened_at = fire.get("opened_at")
        if not isinstance(opened_at, str):
            raise FireManifestError(
                f"expected fire {index} has invalid opened_at"
            )
        try:
            opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FireManifestError(
                f"expected fire {index} has invalid opened_at"
            ) from exc
        if opened.tzinfo is None or opened.utcoffset() is None:
            raise FireManifestError(
                f"expected fire {index} has invalid opened_at"
            )
        fire_id = fire_id.strip()
        if fire_id in expected_by_id:
            raise FireManifestError(f"duplicate expected fire_id {fire_id!r}")
        expected_by_id[fire_id] = opened.astimezone(UTC)

    expected_ids = {
        fire_id
        for fire_id, opened in expected_by_id.items()
        if window_start <= opened <= window_end
    }
    observed_ids = set().union(*(item[2] for item in window)) if window else set()
    observed_expected_ids = observed_ids & expected_ids
    missing_expected_ids = sorted(expected_ids - observed_ids)
    unexpected_observed_ids = sorted(observed_ids - expected_ids)
    expected_fire_coverage = (
        len(observed_expected_ids) / len(expected_ids) if expected_ids else 0.0
    )

    path_occurrences: Counter[str] = Counter()
    top_paths: Counter[str] = Counter()
    for item in window:
        paths = item[3]
        for path in paths:
            top_paths[path] += 1
            lane = classify_path(path) if classify_path is not None else "unclassified"
            if not isinstance(lane, str) or not lane.strip():
                raise FireManifestError("shadow path classifier returned an invalid lane")
            path_occurrences[lane] += 1

    legacy_metric_blockers: list[str] = []
    if not full_window:
        legacy_metric_blockers.append("observation_cadence_incomplete")
    if not fresh:
        legacy_metric_blockers.append("shadow_evidence_stale")
    if identity_coverage < identity_threshold:
        legacy_metric_blockers.append("identity_coverage_below_95pct")
    if not expected_ids:
        legacy_metric_blockers.append("expected_fire_population_empty")
    elif expected_fire_coverage < identity_threshold:
        legacy_metric_blockers.append("expected_fire_coverage_below_95pct")
    if unexpected_observed_ids:
        legacy_metric_blockers.append("observed_fire_missing_manifest_receipt")
    if median_missing is None or median_missing > median_missing_threshold:
        legacy_metric_blockers.append("median_inferred_not_declared_above_2")
    if not baseline_throughout:
        legacy_metric_blockers.append("baseline_unavailable_in_window")
    if baseline_contract_violations:
        legacy_metric_blockers.append("baseline_or_decline_contract_violated")

    return {
        "schema_version": "commit-ownership-shadow-assessment.v1",
        "status": "superseded_contract_blocked",
        "window": {
            "days": window_days,
            "start_at": window_start.isoformat(),
            "end_at": window_end.isoformat(),
            "evidence_start_at": evidence_start.isoformat(),
            "full_window": full_window,
            "fresh": fresh,
            "evidence_age_seconds": evidence_age_s,
            "canonical_schedule_slots": len(schedule_window),
            "canonical_max_gap_seconds": canonical_gap_s,
            "max_allowed_observation_gap_seconds": max_allowed_gap_s,
            "max_observation_gap_seconds": max_observation_gap_s,
        },
        "thresholds": {
            "identity_coverage": identity_threshold,
            "median_inferred_not_declared": median_missing_threshold,
            "max_observation_gap_multiplier": max_observation_gap_multiplier,
        },
        "metrics": {
            "observations": total,
            "identity_observations": identity_total,
            "identity_coverage": identity_coverage,
            "expected_fires": len(expected_ids),
            "observed_expected_fires": len(observed_expected_ids),
            "expected_fire_coverage": expected_fire_coverage,
            "missing_expected_fire_count": len(missing_expected_ids),
            "missing_expected_fire_ids_sample": missing_expected_ids[:20],
            "unexpected_observed_fire_count": len(unexpected_observed_ids),
            "unexpected_observed_fire_ids_sample": unexpected_observed_ids[:20],
            "declared_signal_observations": declared_signal_total,
            "declared_signal_coverage": (
                declared_signal_total / identity_total if identity_total else 0.0
            ),
            "median_inferred_not_declared": median_missing,
            "max_inferred_not_declared": max(missing_lengths, default=None),
            "baseline_available_observations": baseline_available,
            "baseline_available_throughout": baseline_throughout,
            "baseline_or_decline_contract_violations": baseline_contract_violations,
        },
        "missing_path_occurrences": dict(sorted(path_occurrences.items())),
        "top_inferred_not_declared_paths": [
            {"path": path, "occurrences": count}
            for path, count in top_paths.most_common(20)
        ],
        "legacy_metric_blockers": legacy_metric_blockers,
        "legacy_stage2_metrics_pass": not legacy_metric_blockers,
        "manifest_cutover_eligible": False,
        "cutover_blockers": ["legacy_manifest_stage3_superseded"],
        "successor_contract": {
            "issue_refs": ["#41", "#43", "#44"],
            "producer_ownership": (
                "isolated workspace + declared output paths + durable settlement receipt"
            ),
            "machine_state_exit": "Work Coordinator single-writer cutover",
            "legacy_action": "observe_only_until_physical_retirement",
        },
    }


# ── cli ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="volpred.ops.fire_manifest", description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_open = sub.add_parser("open", help="declare a fire")
    p_open.add_argument("--fire-id", required=True)
    p_open.add_argument("--actor", required=True)
    p_open.add_argument("--job-id", default="")
    p_open.add_argument("--slot-id", default="")
    p_open.add_argument("--workspace-kind", default="canonical")

    p_rec = sub.add_parser("record", help="declare one output path")
    p_rec.add_argument("--fire-id", required=True)
    p_rec.add_argument("--path", required=True, action="append", dest="paths")
    p_rec.add_argument("--op", default=OP_WRITE, choices=list(_OPS))
    p_rec.add_argument("--tool", default="")

    p_seal = sub.add_parser("seal", help="freeze the declared set")
    p_seal.add_argument("--fire-id", required=True)

    p_close = sub.add_parser("close", help="terminal state")
    p_close.add_argument("--fire-id", required=True)
    p_close.add_argument("--state", required=True, choices=list(_TERMINAL_STATES))
    p_close.add_argument("--commit", default="")
    p_close.add_argument("--reason", default="")

    p_res = sub.add_parser("resolve", help="split the current dirty set by declared owner")
    p_res.add_argument("--fire-id", default=None)

    sub.add_parser("list", help="every known manifest")

    args = ap.parse_args(argv)
    root = Path(args.repo_root).resolve()

    if args.cmd == "open":
        payload = open_manifest(root, fire_id=args.fire_id, actor=args.actor,
                                job_id=args.job_id, slot_id=args.slot_id,
                                workspace_kind=args.workspace_kind)
    elif args.cmd == "record":
        payload = {}
        for rel in args.paths:
            payload = record(root, args.fire_id, rel, op=args.op, tool=args.tool)
    elif args.cmd == "seal":
        payload = seal(root, args.fire_id)
    elif args.cmd == "close":
        payload = close(root, args.fire_id, state=args.state,
                        commit=args.commit, reason=args.reason)
    elif args.cmd == "resolve":
        import subprocess
        proc = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"],
                              cwd=root, capture_output=True, text=True, timeout=30, check=False)
        dirty = {e[3:] for e in proc.stdout.split("\0") if len(e) >= 4}
        payload = resolve_ownership(root, dirty, fire_id=args.fire_id)
    else:  # list
        payload = {"manifests": [
            {"fire_id": m.get("fire_id"), "state": m.get("state"), "actor": m.get("actor"),
             "paths": len(declared_paths(m)), "opened_at": m.get("opened_at")}
            for m in iter_manifests(root)
        ]}

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
