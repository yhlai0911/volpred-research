"""Enroll this Mac's Codex subscription login for Operations Core failover."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.dispatch_supervisor.isolation import bootstrap_codex_auth_authority


def main() -> int:
    print(json.dumps(bootstrap_codex_auth_authority(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
