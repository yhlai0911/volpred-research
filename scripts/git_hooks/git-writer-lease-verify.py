#!/usr/bin/env python3
"""Fail-fast verifier used by the installed reference-transaction hook.

This file is copied into the common hooks directory.  It intentionally has no
working-tree imports: an uncommitted edit to a repo helper must not weaken the
gate that decides whether main may move.
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
from pathlib import Path

LOCK_BASENAME = "volpred-git-writer.lock"
TOKEN_ENV = "VOLPRED_GIT_WRITER_LOCK_TOKEN"
PATH_ENV = "VOLPRED_GIT_WRITER_LOCK_PATH"
FD_ENV = "VOLPRED_GIT_WRITER_LOCK_FD"
CAP_FD_ENV = "VOLPRED_GIT_WRITER_CAP_FD"


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    common_dir = Path(sys.argv[1]).resolve()
    expected_path = (common_dir / LOCK_BASENAME).resolve()
    token = os.environ.get(TOKEN_ENV, "")
    declared_path = os.environ.get(PATH_ENV, "")
    declared_fd = os.environ.get(FD_ENV, "")
    declared_cap_fd = os.environ.get(CAP_FD_ENV, "")
    if not token or not declared_path or not declared_fd or not declared_cap_fd:
        return 1
    try:
        if Path(declared_path).resolve() != expected_path:
            return 1
        fd = int(declared_fd)
        capability_fd = int(declared_cap_fd)
        opened = os.fstat(fd)
        capability = os.fstat(capability_fd)
        current = expected_path.stat()
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            return 1
        metadata = json.loads(expected_path.read_text(encoding="utf-8"))
        if (
            metadata.get("state") != "held"
            or metadata.get("token") != token
            or metadata.get("capability_dev") != capability.st_dev
            or metadata.get("capability_ino") != capability.st_ino
        ):
            return 1

        # A declared fd must not be allowed to *newly acquire* a lock after a
        # crashed holder left stale metadata.  An independent probe must first
        # observe the lock as occupied.
        probe_fd = os.open(expected_path, os.O_RDWR)
        try:
            try:
                fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:  # silent-ok: EWOULDBLOCK proves another open description already holds the lease.
                pass
            else:
                fcntl.flock(probe_fd, fcntl.LOCK_UN)
                return 1
        finally:
            os.close(probe_fd)

        # Idempotent only for the inherited open-file-description that already
        # owns the flock.  A separately opened FD receives EWOULDBLOCK.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        metadata = json.loads(expected_path.read_text(encoding="utf-8"))
        if (
            metadata.get("state") != "held"
            or metadata.get("token") != token
            or metadata.get("capability_dev") != capability.st_dev
            or metadata.get("capability_ino") != capability.st_ino
        ):
            return 1
    except (BlockingIOError, OSError, ValueError, json.JSONDecodeError) as exc:
        # Keep the hook standalone and avoid leaking path/token evidence, while
        # still making fail-closed verifier errors observable to operators.
        print(
            "[git-writer-lease-verify] WARN "
            f"kind=lease_evidence_invalid reason={type(exc).__name__} "
            "exit_semantics=deny dedupe_key=git_writer_lease_verify",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
