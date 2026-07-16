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
from pathlib import Path

LOG = logging.getLogger(__name__)


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
    for rel in candidates:
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
