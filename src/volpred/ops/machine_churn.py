"""Is this dirty path someone's live work, or just uncommitted machine output?

Every unattended writer in this repo eventually needs the same answer, because
``git status`` cannot give it: a path is "dirty" whether a daemon wrote it an
hour ago and nobody has committed it yet, or a session is typing into it right
now.  Treating the first case as the second is what produces a *latch* — the
writer excludes the path to stay safe, but that writer was the only thing that
would ever have committed it, so the exclusion never lifts and the path stays
dirty forever.  See ``docs/fix_56ddf72b_dirty_guard.md``.

The two gates below are the discriminator, lifted verbatim from PHASE-Z where
they were first built and hardened:

1. the writers' own lock (``fcntl`` ``LOCK_EX`` across every read-modify-write of
   next_tasks.json — see scripts/task_pool_claim.py:87). If a shared lock cannot
   be taken without blocking, a writer holds it right now → defer. *This* is
   "someone is still typing", and it is the only thing a dirty flag was ever a
   proxy for.
2. the content parses. A canonical control file that does not parse is a real
   problem worth escalating, but committing it is how a truncated queue became
   "valid history" once already.

Callers must only offer paths they have *declared as their own outputs*; the
gates answer "is it safe to adopt this now", not "is this mine".
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path

LOG = logging.getLogger(__name__)


def _expand_candidate(
    repo_root: Path,
    rel: str,
    *,
    label: str,
) -> tuple[list[str], list[str]]:
    """Return exact files for one candidate and any fail-closed paths.

    Git reports an untracked directory as one status entry.  Returning that
    directory to a later ``git add`` would create a race: files appearing after
    classification would be staged without passing the lock/parse gates.  Walk
    directories here instead, never follow symlinks, and return only the exact
    regular-file paths that were inspected.
    """
    relative = Path(rel)
    if (
        not rel
        or relative.is_absolute()
        or relative == Path(".")
        or ".." in relative.parts
    ):
        LOG.warning("%s: machine-churn path escapes repository: %s", label, rel)
        return [], [rel]

    root = repo_root.resolve()
    candidate = repo_root / relative

    # Refuse a symlink in any existing component, including a broken final
    # symlink.  ``resolve()`` containment alone would still permit a symlink
    # whose target happens to be inside the repository.
    cursor = repo_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            bad = cursor.relative_to(repo_root).as_posix()
            LOG.warning("%s: refusing symlink machine-churn path: %s", label, bad)
            return [], [bad]

    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        LOG.warning("%s: machine-churn path escapes repository: %s", label, rel)
        return [], [rel]

    if not candidate.exists():
        return [relative.as_posix()], []
    if not candidate.is_dir():
        if not candidate.is_file():
            LOG.warning("%s: refusing non-regular machine-churn path: %s", label, rel)
            return [], [relative.as_posix()]
        return [relative.as_posix()], []

    files: list[str] = []
    rejected: list[str] = []

    def walk(directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            rejected_path = directory.relative_to(repo_root).as_posix()
            LOG.warning(
                "%s: cannot enumerate machine-churn directory %s (%s) — refusing it",
                label,
                rejected_path,
                exc,
            )
            rejected.append(rejected_path)
            return
        for entry in entries:
            path = Path(entry.path)
            child = path.relative_to(repo_root).as_posix()
            try:
                if entry.is_symlink():
                    LOG.warning(
                        "%s: refusing symlink machine-churn path: %s", label, child
                    )
                    rejected.append(child)
                elif entry.is_dir(follow_symlinks=False):
                    walk(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append(child)
                else:
                    LOG.warning(
                        "%s: refusing non-regular machine-churn path: %s",
                        label,
                        child,
                    )
                    rejected.append(child)
            except OSError:
                LOG.warning(
                    "%s: cannot inspect machine-churn path %s — refusing it",
                    label,
                    child,
                )
                rejected.append(child)

    walk(candidate)
    return files, rejected


def classify_machine_churn(
    repo_root: Path,
    candidates: list[str],
    *,
    label: str = "machine_churn",
) -> tuple[list[str], list[str], list[str]]:
    """Split declared machine-churn paths into (committable, deferred, corrupt).

    Adopting a daemon-written file is only safe when nobody is mid-write. The two
    gates are described in the module docstring.

    ``.json`` and ``.jsonl`` candidates are parse-checked; any other churn path still
    gets the lock gate.

    A candidate that no longer exists is a deletion, and deletions are how the
    machine state garbage-collects itself (``gc_event_ledger`` expiring a ledger
    entry). Staging one is the whole point; there is nothing to lock or parse. Until
    2026-07-12 the open() below raised ENOENT on exactly these paths and filed them
    as ``deferred`` — "leave it for the next fire" — which for a file that will never
    come back means every fire, forever. One had been cycling that way for eight.
    """
    committable: list[str] = []
    deferred: list[str] = []
    corrupt: list[str] = []
    expanded: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        exact_paths, rejected = _expand_candidate(
            repo_root, candidate, label=label
        )
        corrupt.extend(path for path in rejected if path not in corrupt)
        for exact in exact_paths:
            if exact not in seen:
                seen.add(exact)
                expanded.append(exact)

    for rel in expanded:
        if not (repo_root / rel).exists():
            committable.append(rel)
            continue
        try:
            with open(repo_root / rel, "r", encoding="utf-8") as fh:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except OSError:
                    LOG.info("%s: %s is locked by a writer right now — leaving it "
                             "for the next fire", label, rel)
                    deferred.append(rel)
                    continue
                try:
                    if rel.endswith(".json"):
                        json.load(fh)
                    elif rel.endswith(".jsonl"):
                        # The queue archive is appended to, not replaced by rename, so
                        # a writer killed mid-append leaves a truncated final line —
                        # the .json gate's exact failure mode in a file the gate did
                        # not cover. Parse every record; a bad one escalates instead
                        # of entering history.
                        for line in fh:
                            if line.strip():
                                json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    LOG.warning("%s: %s does not parse (%s) — refusing to commit it",
                                label, rel, exc)
                    corrupt.append(rel)
                    continue
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            LOG.warning("%s: cannot read machine-churn path %s (%s) — leaving it dirty",
                        label, rel, exc)
            deferred.append(rel)
            continue
        committable.append(rel)
    return committable, deferred, corrupt
