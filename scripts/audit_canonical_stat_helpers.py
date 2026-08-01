"""Ratchet local copies of statistical helpers that now have canonical homes.

Historical experiments are immutable evidence, so existing local definitions
are frozen as debt instead of mechanically rewritten.  The frozen set may only
shrink.  Any new definition must import the canonical implementation from
``volpred.stats.inference`` instead.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "storage/ops/canonical_stat_helper_baseline.json"
LOCAL_HELPER_NAME_RE = re.compile(
    r"holm|exact_label_permutation",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class LocalHelperSite:
    path: str
    function: str
    line: int

    @property
    def identity(self) -> str:
        return f"{self.path}::{self.function}"


def _candidate_paths(root: Path) -> list[Path]:
    """Use the index in a checkout; standalone fixtures use their filesystem."""

    if not (root / ".git").exists():
        return sorted((root / "experiments").glob("**/*.py"))
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--", "experiments"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"cannot enumerate tracked experiment sources: {root}") from exc
    return sorted(
        root / relative.decode("utf-8")
        for relative in result.stdout.split(b"\0")
        if relative and relative.endswith(b".py")
    )


def collect_local_helper_sites(root: Path = ROOT) -> list[LocalHelperSite]:
    """Return local canonical-helper copies under experiment source trees."""

    sites: list[LocalHelperSite] = []
    for path in _candidate_paths(root):
        if (
            "gate_history" in path.parts
            or "__pycache__" in path.parts
            or path.name.startswith("test_")
            or path.name.startswith("test-")
        ):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot read candidate experiment source: {path}") from exc
        if "holm" not in source.lower() and "exact_label_permutation" not in source:
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            raise ValueError(f"cannot parse candidate experiment source: {path}") from exc
        relative = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                LOCAL_HELPER_NAME_RE.search(node.name)
            ):
                sites.append(LocalHelperSite(relative, node.name, node.lineno))
    return sorted(sites)


def load_baseline(path: Path = DEFAULT_BASELINE) -> tuple[set[str], set[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read canonical-stat baseline: {path}") from exc
    sites = payload.get("local_helper_sites")
    if not isinstance(sites, list) or any(not isinstance(site, str) for site in sites):
        raise ValueError("canonical-stat baseline local_helper_sites must be strings")
    if len(sites) != len(set(sites)):
        raise ValueError("canonical-stat baseline contains duplicate sites")
    retired_payload = payload.get("retired_sites", [])
    if not isinstance(retired_payload, list):
        raise TypeError("canonical-stat baseline retired_sites must be a list")
    retired: list[str] = []
    for item in retired_payload:
        if isinstance(item, str):
            retired.append(item)
        elif isinstance(item, dict) and isinstance(item.get("site"), str):
            retired.append(item["site"])
        else:
            raise TypeError(
                "canonical-stat retired site entries require a string site"
            )
    if len(retired) != len(set(retired)):
        raise ValueError("canonical-stat baseline contains duplicate retired sites")
    active_set = set(sites)
    retired_set = set(retired)
    if active_set & retired_set:
        raise ValueError("canonical-stat active and retired sites must be disjoint")
    return active_set, retired_set


def compare_to_baseline(
    root: Path = ROOT,
    baseline_path: Path = DEFAULT_BASELINE,
) -> tuple[list[LocalHelperSite], list[str], list[LocalHelperSite]]:
    current = collect_local_helper_sites(root)
    active, retired = load_baseline(baseline_path)
    remaining = Counter(active)
    added: list[LocalHelperSite] = []
    resurrected: list[LocalHelperSite] = []
    for site in current:
        if remaining[site.identity] > 0:
            remaining[site.identity] -= 1
        elif site.identity in retired:
            resurrected.append(site)
        else:
            added.append(site)
    stale_active = sorted(
        identity for identity, count in remaining.items() if count > 0
    )
    return added, stale_active, resurrected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--print-sites", action="store_true")
    args = parser.parse_args()

    if args.print_sites:
        payload = [site.identity for site in collect_local_helper_sites(args.root)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    try:
        added, stale_active, resurrected = compare_to_baseline(
            args.root,
            args.baseline,
        )
    except (TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    payload = {
        "ok": not added and not stale_active and not resurrected,
        "new_local_helpers": [site.identity for site in added],
        "stale_active_baseline": stale_active,
        "resurrected_retired_helpers": [
            site.identity for site in resurrected
        ],
        "canonical": "volpred.stats.inference",
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif added or stale_active or resurrected:
        print("Canonical-stat helper ratchet failed:")
        for site in added:
            print(f"  new: {site.identity} (line {site.line})")
        for identity in stale_active:
            print(f"  stale active baseline: {identity} (move it to retired_sites)")
        for site in resurrected:
            print(f"  retired site resurrected: {site.identity} (line {site.line})")
    else:
        print("canonical-stat helper ratchet PASS")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
