"""The pinned auth surface must match the bytes in the tree.

2026-08-05: commit e69a0c55c edited `.claude/settings.json` to wire the
write-claim guard into PreToolUse. The sha256 of that file is pinned in
`config/provider_registry.json` as the provider's auth surface, and the pin was
not re-rendered. Every worker spawn was refused from 15:5x onward -- the whole
execution layer, for 2.5 hours -- while `ops_snapshot` stayed green, because the
gate lives in the daemon at runtime and nothing checked the pin before push.

That was the third time this class landed (08-04 pin .221, 08-05 12:45 pin .222,
then the settings surface): the pin is maintained by hand while the thing it
pins changes on its own, and a stale pin looks green everywhere except inside
the daemon.

The cron wrapper manifest already has exactly this test
(`scripts/tests/test_cron_wrapper_manifest.py`), which is why an out-of-date
wrapper manifest turns CI red instead of silently halting a schedule. The auth
surface had no equivalent. This is that equivalent -- it moves the failure from
runtime (execution layer stops, nobody is told) to push time (CI is red, with
the recompute command in the message).

Scope note: only repo-relative pins can be checked here. Executable pins point
at `~/.local/share/claude/versions/...`, which does not exist on a CI runner --
asserting on them would fail for a reason that has nothing to do with the commit
under test. They are excluded by path, and
`test_registry_declares_at_least_one_repo_relative_pin` keeps that exclusion
from quietly emptying the suite.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "config").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("repo root not found (no ancestor holds config/ and scripts/)")


ROOT = _repo_root()
REGISTRY_PATH = ROOT / "config" / "provider_registry.json"

FIX_HINT = (
    "Recompute it yourself and update config/provider_registry.json:\n"
    "    shasum -a 256 <path>\n"
    "Never copy the value out of an alert, a log line or a report -- the pin "
    "exists so the thing being verified cannot supply its own answer."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative_pins() -> list[tuple[str, str, str]]:
    """(pin_id, repo-relative path, pinned sha256) for every in-repo pin."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    pins: list[tuple[str, str, str]] = []
    for provider in registry["providers"]:
        provider_id = provider["provider_id"]
        surface = (provider.get("auth") or {}).get("settings_surface")
        if surface:
            pins.append(
                (f"{provider_id}.auth.settings_surface", surface["path"],
                 surface["sha256"])
            )
        for identity in provider.get("executables", []):
            realpath = Path(identity["realpath"])
            try:
                relative = realpath.relative_to(ROOT)
            except ValueError:
                # An executable outside the repo cannot be hashed on a CI runner.
                # The exclusion is not silent at the suite level:
                # test_registry_declares_at_least_one_repo_relative_pin fails
                # loudly if it ever empties the parametrisation.
                continue  # silent-ok: unhashable off-repo path, covered by the guard test
            pins.append(
                (f"{provider_id}.executable", str(relative), identity["sha256"])
            )
    return pins


def test_registry_declares_at_least_one_repo_relative_pin() -> None:
    """A test that silently checks nothing is worse than no test at all."""
    assert _repo_relative_pins(), (
        "no repo-relative pin found in config/provider_registry.json -- either "
        "the schema moved or this test stopped covering anything"
    )


@pytest.mark.parametrize(
    "pin_id,relative_path,pinned",
    _repo_relative_pins(),
    ids=lambda value: value if isinstance(value, str) and "." in value else "",
)
def test_pinned_bytes_match_the_tree(pin_id: str, relative_path: str, pinned: str) -> None:
    target = ROOT / relative_path
    assert target.is_file(), (
        f"{pin_id} pins {relative_path}, which does not exist. A pin whose "
        f"target is gone refuses every spawn at runtime.\n{FIX_HINT}"
    )
    actual = _sha256(target)
    assert actual == pinned, (
        f"{pin_id} is out of date: {relative_path} no longer hashes to the "
        f"pinned value.\n"
        f"  pinned: {pinned}\n"
        f"  actual: {actual}\n"
        "Until the pin is updated the provider registry refuses EVERY worker "
        "spawn -- the execution layer stops while heartbeat and ops_snapshot "
        "stay green (2026-08-05, 2.5h).\n"
        "If the change to the file was not intended, revert the file instead; "
        "the pin is what makes a silent auth-surface edit impossible.\n"
        f"{FIX_HINT}"
    )
