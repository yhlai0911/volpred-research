"""The provider registry pins files that legitimately change. Catch the drift.

2026-08-05: `.claude/settings.json` was changed by commit e69a0c55c at 15:29 --
a correct, reviewed change (the write-claim guard). The registry's pinned
sha256 for that same file was last written at 12:45. From 15:58 every single
`spawn` was refused with `provider_policy_denied`, because
`registry.py::_validate_settings_surface` compares the pinned digest against the
file on disk. The platform's entire execution layer was down for 2h45m: CI
repair and PHASE-Z work were silently dropped, the Telegram responder could not
start, and the owner's messages went unanswered while the dashboard reported
zero alerts.

This is the third instance of the same class in two days (08-04 pin .221,
08-05 12:45 pin .222, 08-05 15:29 settings surface), so per CLAUDE.md the
deliverable is a mechanical gate, not a fourth hand-written digest.

The gate deliberately does NOT auto-repin at runtime. The digest exists to
detect an unreviewed change to the auth surface; a process that silently
re-pins whatever it finds would keep every spawn alive and delete the security
property in the same motion. Failing loudly here -- where a human or agent is
already looking at the diff -- is the whole point: the pinned file and its pin
must land in the same change.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "config" / "provider_registry.json"


def _pinned_surfaces() -> list[tuple[str, str, str]]:
    """(provider_id, path, sha256) for every pinned settings surface."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    out = []
    for provider in registry.get("providers", []):
        surface = (provider.get("auth") or {}).get("settings_surface") or {}
        if surface.get("path") and surface.get("sha256"):
            out.append((provider["provider_id"], surface["path"], surface["sha256"]))
    return out


def test_registry_declares_at_least_one_pinned_surface() -> None:
    """If the pins ever vanish, the test below would pass vacuously."""
    assert _pinned_surfaces(), "no settings_surface pins found — the gate below would be a no-op"


@pytest.mark.parametrize("provider_id,rel_path,pinned", _pinned_surfaces())
def test_pinned_settings_surface_matches_the_file(provider_id: str, rel_path: str, pinned: str) -> None:
    target = REPO / rel_path
    assert target.is_file(), f"{provider_id} pins {rel_path}, which does not exist"

    actual = hashlib.sha256(target.read_bytes()).hexdigest()

    assert actual == pinned, (
        f"{provider_id} 的 auth surface pin 已漂移 —— 每一次 spawn 都會被拒絕。\n"
        f"  pinned: {pinned}\n"
        f"  actual: {actual}  ({rel_path})\n"
        f"若 {rel_path} 的改動是正當且已審過的，把 pin 更新到 actual 並與該改動放在同一個 commit：\n"
        f"  config/provider_registry.json → providers[{provider_id}].auth.settings_surface.sha256\n"
        f"若你不知道這個檔為什麼變了，先查清楚再動 pin —— 這個比對存在的理由就是偵測未經審查的改動。"
    )
