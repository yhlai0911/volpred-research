"""Mirror API auth header for /api/sync and /api/publications callers.

2026-06-11: the frontend gated these endpoints behind OPS_ADMIN_TOKEN
(security fix C1/C2, live since ~2026-05-16) but no caller sent the token —
every mirror sync silently 401'd for nearly a month (publisher.py swallowed
the error with a bare ``except``). All mirror-write callers must attach
``ops_admin_headers()`` and must NOT silently swallow auth failures.
"""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def ops_admin_token() -> str | None:
    """OPS_ADMIN_TOKEN from env, falling back to project .env.local."""
    token = os.environ.get("OPS_ADMIN_TOKEN")
    if token:
        return token
    env_file = _PROJECT_ROOT / ".env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPS_ADMIN_TOKEN="):
                value = line.split("=", 1)[1].strip()
                return value or None
    return None


def ops_admin_headers() -> dict[str, str]:
    """Headers dict carrying the ops admin token (empty if unset)."""
    token = ops_admin_token()
    return {"x-ops-key": token} if token else {}
