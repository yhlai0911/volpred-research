"""One-click pin maintenance for config/provider_registry.json.

CLI auto-upgrades and settings.json edits both drift the pins that
`src/volpred/ops/execution/registry.py` checks before every provider spawn —
a drifted pin means every fire gets `provider_policy_denied` until someone
manually recomputes and writes the sha256. That manual step happened three
times in two days (2026-08-04 CLI upgrade, 2026-08-05 pin, 2026-08-05
settings surface) with zero alert coverage on the denial itself, which is
exactly the "3-STRIKE" pattern per CLAUDE.md.

This tool always recomputes the sha256 from the actual file bytes — never
trusts a value copied from a log line or a prior report, matching the "禁止
照抄 log" requirement in the originating task
(next_tasks.json#assign_4e4e8030). It only touches config/provider_registry.json
(this department's owned_paths); it does not edit the validation logic in
src/volpred/ops/execution/registry.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "config" / "provider_registry.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _save_registry(registry: dict) -> None:
    REGISTRY_PATH.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _find_provider(registry: dict, provider_id: str) -> dict:
    for provider in registry.get("providers", []):
        if provider.get("provider_id") == provider_id:
            return provider
    raise SystemExit(f"no such provider_id in registry: {provider_id!r}")


def cmd_check(_args: argparse.Namespace) -> int:
    registry = _load_registry()
    drifted = 0
    for provider in registry.get("providers", []):
        provider_id = provider["provider_id"]
        surface = (provider.get("auth") or {}).get("settings_surface")
        if surface:
            target = REPO_ROOT / surface["path"]
            if not target.is_file():
                print(f"[{provider_id}] settings_surface {surface['path']} MISSING on disk")
                drifted += 1
            else:
                actual = _sha256_file(target)
                if actual != surface["sha256"]:
                    print(
                        f"[{provider_id}] settings_surface DRIFT {surface['path']}\n"
                        f"    pinned: {surface['sha256']}\n"
                        f"    actual: {actual}"
                    )
                    drifted += 1
        pinned_execs = {e["realpath"] for e in provider.get("executables", [])}
        resolved = shutil.which(provider_id.removesuffix("-cli"))
        if resolved:
            resolved = str(Path(resolved).resolve())
            if resolved not in pinned_execs:
                print(
                    f"[{provider_id}] currently-resolved executable not in registry: "
                    f"{resolved} (which() -> {provider_id.removesuffix('-cli')})"
                )
                drifted += 1
    if drifted == 0:
        print("no drift detected")
    return 1 if drifted else 0


def cmd_pin_settings_surface(args: argparse.Namespace) -> int:
    registry = _load_registry()
    provider = _find_provider(registry, args.provider)
    surface = (provider.get("auth") or {}).get("settings_surface")
    if not surface:
        raise SystemExit(f"{args.provider} has no settings_surface to pin")
    target = REPO_ROOT / surface["path"]
    if not target.is_file():
        raise SystemExit(f"{surface['path']} does not exist on disk")
    actual = _sha256_file(target)
    if actual == surface["sha256"]:
        print(f"[{args.provider}] already pinned correctly: {actual}")
        return 0
    print(f"[{args.provider}] {surface['path']}: {surface['sha256']} -> {actual}")
    if not args.apply:
        print("(dry-run; pass --apply to write)")
        return 1
    surface["sha256"] = actual
    _save_registry(registry)
    print("written")
    return 0


def cmd_add_executable(args: argparse.Namespace) -> int:
    registry = _load_registry()
    provider = _find_provider(registry, args.provider)
    path = Path(args.path).resolve()
    if not path.is_file():
        raise SystemExit(f"not a file: {path}")
    actual = _sha256_file(path)
    executables = provider.setdefault("executables", [])
    for entry in executables:
        if entry["realpath"] == str(path):
            if entry["sha256"] == actual:
                print(f"[{args.provider}] {path} already pinned: {actual}")
                return 0
            print(
                f"[{args.provider}] {path} is registered with a DIFFERENT sha256 "
                f"({entry['sha256']}) than the file on disk now ({actual}) — "
                "the file changed under a pinned path, refusing to silently "
                "overwrite; investigate before re-pinning."
            )
            return 1
    print(f"[{args.provider}] new executable {path}: {actual}")
    if not args.apply:
        print("(dry-run; pass --apply to write)")
        return 1
    executables.append({"realpath": str(path), "sha256": actual})
    _save_registry(registry)
    print("written (existing pins untouched — old versions stay valid)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser(
        "check", help="report pin drift across all providers (read-only)"
    )
    p_check.set_defaults(func=cmd_check)

    p_settings = sub.add_parser(
        "pin-settings-surface", help="recompute and (optionally) write a settings_surface pin"
    )
    p_settings.add_argument("--provider", required=True)
    p_settings.add_argument("--apply", action="store_true")
    p_settings.set_defaults(func=cmd_pin_settings_surface)

    p_exec = sub.add_parser(
        "add-executable",
        help="compute sha256 for a new CLI version and append it (never replaces existing pins)",
    )
    p_exec.add_argument("--provider", required=True)
    p_exec.add_argument("--path", required=True, help="absolute path to the executable")
    p_exec.add_argument("--apply", action="store_true")
    p_exec.set_defaults(func=cmd_add_executable)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
