#!/usr/bin/env python3
"""Verify that the pytest workflow's paths-ignore never hides a test dependency.

`paths-ignore` is a claim: "changing these files cannot change a test outcome."
The claim is true when written and turns false silently — a test grows a new
dependency, the entry stays, and CI starts reporting green for commits it never
ran. That is not hypothetical: a blanket `**/*.md` sat there on the claim that
the suite read no markdown while 20+ test files asserted on AGENTS.md,
CLAUDE.md and .claude/rules/*.md, and a governance commit that broke the suite
went unreported for two commits (docs/error_log.md 2026-08-04).

So the claim gets checked mechanically against a recorded dependency set:

    config/ci_test_repo_dependencies.json

which is produced by actually running the suite under an audit hook, not by
grepping — a test can reach a repo path through a default constant, a config
pointer, or a glob it never spells out. Regenerate it with:

    VOLPRED_PROBE_REPO="$PWD" VOLPRED_PROBE_OUT=/tmp/hits.txt PYTHONPATH=scripts \\
      uv run --extra dev pytest -q -p no:randomly -p ci_storage_read_probe
    uv run python scripts/audit_ci_paths_ignore.py freeze --hits /tmp/hits.txt

Commands:
    check       fail if any recorded dependency is covered by paths-ignore
    freeze      rewrite the dependency file from a probe run
    simulate    report how many recent commits the current rules would skip
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pytest.yml"
QUEUE_WORKFLOW = ROOT / ".github" / "workflows" / "queue-invariants.yml"
DEPENDENCIES = ROOT / "config" / "ci_test_repo_dependencies.json"
TEST_DIRS = ("tests", "scripts/tests")


def load_paths_ignore() -> list[str]:
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = spec.get(True) or spec.get("on") or {}
    push = triggers.get("push") or {}
    return list(push.get("paths-ignore") or [])


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a GitHub Actions path filter into a regex.

    Only the three constructs GitHub documents are honoured: `**` spans
    separators, `*` does not, `?` is a single non-separator character. A
    pattern ending in `/**` also matches the directory itself, which is how
    GitHub treats it and how a naive fnmatch translation gets it wrong.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    body = "".join(out)
    if body.endswith("/.*"):
        body = body[: -len("/.*")] + "(/.*)?"
    return re.compile("^" + body + "$")


def covered_by(path: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if glob_to_regex(pattern).match(path):
            return pattern
    return None


def load_queue_workflow_paths() -> list[str]:
    spec = yaml.safe_load(QUEUE_WORKFLOW.read_text(encoding="utf-8"))
    triggers = spec.get(True) or spec.get("on") or {}
    push = triggers.get("push") or {}
    return list(push.get("paths") or [])


def find_real_queue_test_files() -> list[str]:
    """Test files carrying @pytest.mark.real_queue.

    Textual, deliberately: importing the suite to ask pytest would run
    collection-time side effects, and this has to stay cheap enough to sit in
    the audit. A marker applied dynamically (parametrize, a fixture) would be
    missed — none exist today, and the pytest.ini marker docs say to apply it
    directly.
    """
    found = []
    for rel_dir in TEST_DIRS:
        for path in sorted((ROOT / rel_dir).glob("test_*.py")):
            # errors="replace": a byte-corrupted source file is real, and it
            # already has an owner (scripts/audit_source_encoding.py + the
            # Source Encoding Gate workflow). Raising here would make this
            # audit a second, worse reporter of someone else's failure and
            # would take the marker check offline while that one is red.
            text = path.read_text(encoding="utf-8", errors="replace")
            if "@pytest.mark.real_queue" in text:
                found.append(path.relative_to(ROOT).as_posix())
    return found


def load_dependencies() -> list[str]:
    if not DEPENDENCIES.exists():
        raise SystemExit(
            f"missing {DEPENDENCIES.relative_to(ROOT)} — regenerate it with the "
            "probe command in this file's docstring"
        )
    payload = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))
    return list(payload.get("paths") or [])


def cmd_check(_args: argparse.Namespace) -> int:
    patterns = load_paths_ignore()
    violations = []
    for path in load_dependencies():
        pattern = covered_by(path, patterns)
        if pattern:
            violations.append((path, pattern))

    if violations:
        print("paths-ignore hides files the suite actually reads:")
        for path, pattern in violations:
            print(f"  {path}\n    hidden by: {pattern}")
        print(
            "\nEither drop/narrow the pattern, or change the test to use a "
            "fixture instead of the repo copy. Do not edit the dependency "
            "file by hand — it is a recording, not a policy."
        )
        return 1

    # Test Suite deselects real_queue, so those tests run ONLY in
    # queue-invariants.yml. A marked test in a file that workflow's `paths`
    # never names would be selected by neither: deselected in one, untriggered
    # in the other. Silently unrun, which is worse than either workflow failing.
    queue_paths = load_queue_workflow_paths()
    orphaned = [
        f for f in find_real_queue_test_files() if not covered_by(f, queue_paths)
    ]
    if orphaned:
        print("real_queue tests that no workflow would run:")
        for path in orphaned:
            print(f"  {path}")
        print(
            "\nTest Suite deselects them and queue-invariants.yml does not "
            "trigger on this file. Add it to that workflow's `paths`."
        )
        return 1

    print(
        f"paths-ignore OK: {len(patterns)} pattern(s), "
        f"{len(load_dependencies())} recorded dependenc(ies), no overlap; "
        f"{len(find_real_queue_test_files())} real_queue file(s) all triggered"
    )
    return 0


def cmd_freeze(args: argparse.Namespace) -> int:
    raw = Path(args.hits).read_text(encoding="utf-8").splitlines()
    paths: dict[str, str] = {}
    for line in raw:
        if not line.strip():
            continue
        path, _, nodeid = line.partition("\t")
        paths.setdefault(path, nodeid or "<unknown>")

    tracked = set(
        subprocess.run(
            ["git", "ls-files", "storage"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    )
    # Untracked hits cannot appear in a commit, so paths-ignore can never hide
    # them; recording them would only produce noise that never fails.
    kept = {p: n for p, n in paths.items() if p in tracked}

    DEPENDENCIES.write_text(
        json.dumps(
            {
                "_comment": (
                    "Repo paths the pytest suite actually opens, recorded by "
                    "scripts/ci_storage_read_probe.py under a full run. "
                    "scripts/audit_ci_paths_ignore.py check fails if the "
                    "workflow's paths-ignore covers any of them. Regenerate, "
                    "do not hand-edit."
                ),
                "recorded_from": args.recorded_from,
                "paths": sorted(kept),
                "read_by": {p: kept[p] for p in sorted(kept)},
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"froze {len(kept)} tracked dependenc(ies) to {DEPENDENCIES.relative_to(ROOT)}")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    patterns = load_paths_ignore()
    revs = subprocess.run(
        ["git", "log", "--format=%H", f"-{args.commits}", args.ref],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    skipped = 0
    triggered = 0
    for rev in revs:
        files = subprocess.run(
            ["git", "show", "--name-only", "--format=", rev],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        if not files:
            continue
        # GitHub skips a run only when EVERY changed file matches.
        if all(covered_by(f, patterns) for f in files):
            skipped += 1
        else:
            triggered += 1

    total = skipped + triggered
    if not total:
        print("no commits to simulate")
        return 0
    print(
        f"{args.commits} commits on {args.ref}: {skipped} skipped, "
        f"{triggered} would run the suite ({100 * skipped / total:.0f}% skipped)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check").set_defaults(func=cmd_check)

    freeze = sub.add_parser("freeze")
    freeze.add_argument("--hits", required=True, help="probe output file")
    freeze.add_argument("--recorded-from", default="full pytest run")
    freeze.set_defaults(func=cmd_freeze)

    simulate = sub.add_parser("simulate")
    simulate.add_argument("--commits", type=int, default=200)
    simulate.add_argument("--ref", default="origin/main")
    simulate.set_defaults(func=cmd_simulate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
