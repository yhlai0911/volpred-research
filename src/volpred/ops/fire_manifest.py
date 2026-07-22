"""Declared ownership of a fire's output — the write-side ledger PHASE-Z lacks.

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

Scope note (stage 1)
--------------------
Nothing here mutates git and nothing here is wired into PHASE-Z's commit
decision. ``shadow_compare`` exists to run both answers side by side — declared
vs inferred — and log the delta, so the size of the disagreement is measured
before any behaviour changes on it.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

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
    declared = set(ownership["owned"])
    inferred_set = set(inferred)
    return {
        "at": _now_iso(now),
        "fire_id": fire_id,
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
    now: float | None = None,
) -> dict[str, Any] | None:
    """``shadow_compare`` + log it, swallowing every error.

    This is the only function a live caller (PHASE-Z, stage 1) should use: it is
    total. A bug in the shadow path must not be able to affect a commit decision.
    """
    try:
        payload = shadow_compare(repo_root, dirty_now=dirty_now, baseline=baseline,
                                 fire_id=fire_id, now=now)
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
