#!/usr/bin/env python3
"""Keep `scripts/cron_*.sh` (canonical) and `~/.volpred/bin/` (what launchd execs) in lockstep.

The trap this closes
--------------------
launchd execs `~/.volpred/bin/cron_<x>.sh`; it never reads `scripts/cron_<x>.sh`.
Every wrapper's own header tells you to `cp` it across after editing, and for
months nobody did: on 2026-07-10 eleven of forty wrappers had drifted, including
`cron_hourly_dispatch.sh` (the dispatch backbone) and `cron_market_cal.sh`, whose
live copy was three months behind and did not even source `cron_lib.sh`. Editing
the canonical copy looked like it worked and changed nothing. Same bug class as
the cron freshness marker: the artifact you edit is decoupled from the thing that
executes.

`config/cron_wrapper_manifest.json` is the fix. It is a committed hash of every
canonical wrapper, which makes the coupling checkable from two places that see
different halves of the world:

- CI (`scripts/tests/test_cron_wrapper_manifest.py`) sees the repo but not
  `~/.volpred/bin`. It compares canonical against the manifest, so editing a
  wrapper without running `--apply` fails the build.
- The host (`scripts/check_alerts.py::_check_piggy_back_drift`) sees both. It
  compares the live copy against canonical and reports `wrapper_drift: <id>`.

Population = every `scripts/cron_*.sh` except `cron_lib.sh`. That is deliberately
a superset of what `config/runtime_schedules.json` declares: the config splits
host wrappers across `system_crontab.items[].wrapper_script` AND
`cron_jobs[].tcc_bypass_copy` / `.script` / `.command`, and a subset audit that
reads only the first section misses the backbone (that is exactly how
`cron_hourly_dispatch.sh` stayed invisible). The glob cannot miss a section.

Install is an atomic rename, never `cp`
---------------------------------------
bash reads a script incrementally by byte offset while executing it. `cp` truncates
and rewrites the *same inode*, so overwriting a wrapper that a launchd job is
running mid-flight makes bash resume at a stale offset in new bytes. `os.replace`
swaps the directory entry instead: a running process keeps the old inode until it
exits. Every `cp scripts/... ~/.volpred/bin/` line in the wrapper headers is
subtly wrong; use this script.

Usage:
    uv run python scripts/sync_cron_wrappers.py            # --check (default)
    uv run python scripts/sync_cron_wrappers.py --apply    # install + regen manifest
    uv run python scripts/sync_cron_wrappers.py --check --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_RELPATH = Path("config") / "cron_wrapper_manifest.json"

# The directory launchd actually execs from. Machine-local: absent in CI, which is
# why the manifest exists at all.
DEFAULT_INSTALL_DIR = Path.home() / ".volpred" / "bin"

# Sourced in place from the repo checkout (`source scripts/cron_lib.sh` after the
# wrapper cd's here), so it is never installed. Changes to it take effect live on
# the next fire — that is the design, not an oversight.
NOT_INSTALLED = frozenset({"cron_lib.sh"})

_HOST_WRAPPER_RE = re.compile(r"[^\s'\"]*\.volpred/bin/(cron_[^\s'\"]+\.sh)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_canonical_wrappers(root: Path = PROJECT_ROOT) -> list[Path]:
    """Every wrapper that belongs in the install dir, sorted by name."""
    return sorted(
        p for p in (root / "scripts").glob("cron_*.sh") if p.name not in NOT_INSTALLED
    )


def build_manifest_entries(root: Path = PROJECT_ROOT) -> dict[str, str]:
    return {p.name: sha256_file(p) for p in iter_canonical_wrappers(root)}


def manifest_path(root: Path = PROJECT_ROOT) -> Path:
    return root / MANIFEST_RELPATH


def load_manifest(root: Path = PROJECT_ROOT) -> dict[str, str]:
    path = manifest_path(root)
    if not path.exists():
        raise FileNotFoundError(f"manifest missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("wrappers") or {})


def write_manifest(entries: dict[str, str], root: Path = PROJECT_ROOT) -> Path:
    path = manifest_path(root)
    payload = {
        "_comment": (
            "sha256 of every canonical scripts/cron_*.sh. launchd execs the copy in "
            "~/.volpred/bin, not this repo — this manifest is the only thing CI can "
            "see that proves the two are in lockstep. Regenerate with "
            "`uv run python scripts/sync_cron_wrappers.py --apply`, which also "
            "installs the wrappers. Never hand-edit."
        ),
        "install_dir": "~/.volpred/bin",
        "not_installed": sorted(NOT_INSTALLED),
        "wrappers": dict(sorted(entries.items())),
    }
    # No generated_at: a timestamp would churn the diff on every regen and prove
    # nothing the hashes don't already prove.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def declared_host_wrappers(root: Path = PROJECT_ROOT) -> dict[str, str]:
    """basename -> job id, for every host wrapper named anywhere in runtime_schedules.json.

    Walks the whole config rather than one section: host wrapper paths appear under
    `system_crontab.items[].wrapper_script`, `cron_jobs[].tcc_bypass_copy`,
    `cron_jobs[].script` and `cron_jobs[].command`, and new sections will keep
    appearing. Matching on the path shape is section-agnostic.
    """
    config = json.loads((root / "config" / "runtime_schedules.json").read_text(encoding="utf-8"))
    found: dict[str, str] = {}

    def walk(node, job_id: str) -> None:
        if isinstance(node, dict):
            job_id = node.get("id") or node.get("name") or job_id
            for value in node.values():
                walk(value, job_id)
        elif isinstance(node, list):
            for value in node:
                walk(value, job_id)
        elif isinstance(node, str):
            for basename in _HOST_WRAPPER_RE.findall(node):
                found.setdefault(basename, job_id)

    walk(config, "<unknown>")
    return found


def check_manifest(root: Path = PROJECT_ROOT) -> list[str]:
    """Repo-only invariants. Safe in CI: never touches the install dir."""
    problems: list[str] = []
    try:
        recorded = load_manifest(root)
    except FileNotFoundError as exc:
        return [f"manifest_missing: {exc}"]
    except json.JSONDecodeError as exc:
        return [f"manifest_unparsable: {exc}"]

    actual = build_manifest_entries(root)

    for name in sorted(set(actual) - set(recorded)):
        problems.append(f"manifest_missing_entry: {name} (new wrapper never synced)")
    for name in sorted(set(recorded) - set(actual)):
        problems.append(f"manifest_stale_entry: {name} (canonical deleted or renamed)")
    for name in sorted(set(actual) & set(recorded)):
        if actual[name] != recorded[name]:
            problems.append(
                f"manifest_stale: {name} canonical={actual[name][:12]} "
                f"manifest={recorded[name][:12]} (edited without --apply)"
            )

    # A wrapper the scheduler will exec but the repo cannot version is unfixable by
    # definition — you cannot edit-and-sync what has no canonical.
    for basename, job_id in sorted(declared_host_wrappers(root).items()):
        if not (root / "scripts" / basename).exists():
            problems.append(f"canonical_missing: {basename} (job={job_id}) has no scripts/ copy")

    return problems


def detect_live_drift(
    root: Path = PROJECT_ROOT, install_dir: Path | None = None
) -> list[dict[str, str]]:
    """Host-only: does the copy launchd execs still match canonical?

    Returns [] when the install dir is absent (CI, another machine) — this check is
    about a specific host's state, and having no install dir is not drift.
    """
    # An empty population means `root` is not a checkout (callers monkeypatch
    # PROJECT_ROOT to a bare tmp dir). Comparing nothing against nothing is not a
    # silent fallback — it is an empty domain, and a real checkout always has 40+.
    # A checkout that genuinely lost its wrappers is caught by check_manifest's
    # `manifest_stale_entry`, which reads the committed manifest rather than the glob.
    canonical_wrappers = iter_canonical_wrappers(root)
    if not canonical_wrappers:
        return []

    install_dir = install_dir or DEFAULT_INSTALL_DIR
    if not install_dir.is_dir():
        return []

    job_ids = declared_host_wrappers(root)
    findings: list[dict[str, str]] = []
    for canonical in canonical_wrappers:
        live = install_dir / canonical.name
        job_id = job_ids.get(canonical.name, canonical.name)
        if not live.exists():
            findings.append(
                {"kind": "wrapper_not_installed", "job_id": job_id, "detail": str(live)}
            )
            continue
        canonical_sha = sha256_file(canonical)
        live_sha = sha256_file(live)
        if canonical_sha != live_sha:
            findings.append(
                {
                    "kind": "wrapper_drift",
                    "job_id": job_id,
                    "detail": f"live={live_sha[:12]} canonical={canonical_sha[:12]}",
                }
            )
    return findings


def install_atomic(src: Path, dst: Path) -> None:
    """Replace `dst` without ever truncating the inode a running bash may be reading."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.tmp.{os.getpid()}")
    try:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dst)  # atomic within the same filesystem
    finally:
        tmp.unlink(missing_ok=True)


def apply_sync(root: Path = PROJECT_ROOT, install_dir: Path | None = None) -> dict:
    install_dir = install_dir or DEFAULT_INSTALL_DIR
    installed, unchanged = [], []
    for canonical in iter_canonical_wrappers(root):
        live = install_dir / canonical.name
        if live.exists() and sha256_file(live) == sha256_file(canonical):
            unchanged.append(canonical.name)
            continue
        install_atomic(canonical, live)
        installed.append(canonical.name)
    write_manifest(build_manifest_entries(root), root)
    return {"installed": installed, "unchanged": unchanged}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="install wrappers + regenerate manifest")
    parser.add_argument("--check", action="store_true", help="report drift, exit 1 if any (default)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--install-dir", type=Path, default=None, help="override ~/.volpred/bin")
    args = parser.parse_args(argv)

    if args.apply:
        result = apply_sync(PROJECT_ROOT, args.install_dir)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"installed: {len(result['installed'])}  unchanged: {len(result['unchanged'])}")
            for name in result["installed"]:
                print(f"  + {name}")
            print(f"manifest: {manifest_path(PROJECT_ROOT).relative_to(PROJECT_ROOT)}")
        return 0

    problems = check_manifest(PROJECT_ROOT)
    live = detect_live_drift(PROJECT_ROOT, args.install_dir)
    problems.extend(f"{f['kind']}: {f['job_id']} {f['detail']}" for f in live)

    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False, indent=2))
    elif problems:
        print("cron wrapper drift:")
        for entry in problems:
            print(f"  - {entry}")
        print("\nfix: uv run python scripts/sync_cron_wrappers.py --apply")
    else:
        print("cron wrappers: in lockstep (canonical == manifest == ~/.volpred/bin)")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
