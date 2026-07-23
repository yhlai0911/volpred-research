#!/usr/bin/env python3
"""Stress the orphan-reaper symlink/ignore regression across host variables.

This is a diagnosis harness, not a workaround.  It repeatedly runs the exact
test that failed with ``StopIteration`` on 2026-07-19 while varying the four
environment dimensions named in the follow-up task:

* macOS temporary-directory aliases (``/var/tmp`` and ``/private/var/tmp``);
* every locally available Git binary;
* an empty versus matching global ``core.excludesFile``;
* serial versus concurrent pytest subprocesses.

The test itself creates a fresh repository and asserts that ``compute-invalid``
is present in ``result["held"]``.  A missing entry therefore reproduces the
original symptom instead of relying on a proxy signal.

Run:
    uv run --extra dev python scripts/run_orphan_reaper_flake_harness.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
TEST_TARGET = (
    ROOT
    / "scripts/tests/test_orphan_reaper.py"
)
TEST_NODE = (
    f"{TEST_TARGET}"
    "::test_job_reaper_rejects_agent_external_directory_symlink_and_ignored_paths"
)


@dataclass(frozen=True)
class Variant:
    tmpdir: str
    git_binary: str
    global_excludes: str
    workers: int

    @property
    def label(self) -> str:
        git_name = self.git_binary.removeprefix("/").replace("/", "_")
        tmp_name = self.tmpdir.removeprefix("/").replace("/", "_")
        return (
            f"tmp={tmp_name},git={git_name},"
            f"global={self.global_excludes},workers={self.workers}"
        )


@dataclass(frozen=True)
class Attempt:
    variant: str
    iteration: int
    returncode: int
    output: str


def _available_git_binaries() -> list[Path]:
    candidates = (Path("/usr/bin/git"), Path("/opt/homebrew/bin/git"))
    return [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]


def _available_tmpdirs() -> list[Path]:
    candidates = (Path("/var/tmp"), Path("/private/var/tmp"))
    return [path for path in candidates if path.is_dir()]


def _variants(parallel_workers: int) -> list[Variant]:
    worker_counts = [1]
    if parallel_workers > 1:
        worker_counts.append(parallel_workers)
    return [
        Variant(
            tmpdir=str(tmpdir),
            git_binary=str(git_binary),
            global_excludes=global_excludes,
            workers=workers,
        )
        for tmpdir in _available_tmpdirs()
        for git_binary in _available_git_binaries()
        for global_excludes in ("empty", "matches_fixture")
        for workers in worker_counts
    ]


def _git_version(git_binary: str) -> str:
    result = subprocess.run(
        [git_binary, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_attempt(
    variant: Variant,
    iteration: int,
    *,
    global_config: Path,
) -> Attempt:
    env = os.environ.copy()
    env["TMPDIR"] = variant.tmpdir
    env["PATH"] = os.pathsep.join(
        [str(Path(variant.git_binary).parent), env.get("PATH", "")]
    )
    env["GIT_CONFIG_GLOBAL"] = (
        os.devnull if variant.global_excludes == "empty" else str(global_config)
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_NODE, "-q"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    return Attempt(
        variant=variant.label,
        iteration=iteration,
        returncode=result.returncode,
        output=output,
    )


def _run_variant(
    variant: Variant,
    iterations: int,
    *,
    global_config: Path,
) -> list[Attempt]:
    def run(iteration: int) -> Attempt:
        return _run_attempt(variant, iteration, global_config=global_config)

    if variant.workers == 1:
        return [run(iteration) for iteration in range(1, iterations + 1)]
    with ThreadPoolExecutor(max_workers=variant.workers) as executor:
        return list(executor.map(run, range(1, iterations + 1)))


def _summarize(
    variants: Iterable[Variant],
    attempts: list[Attempt],
    *,
    iterations: int,
) -> dict:
    rows = []
    for variant in variants:
        selected = [attempt for attempt in attempts if attempt.variant == variant.label]
        failures = [attempt for attempt in selected if attempt.returncode != 0]
        rows.append(
            {
                **asdict(variant),
                "label": variant.label,
                "git_version": _git_version(variant.git_binary),
                "passed": len(selected) - len(failures),
                "failed": len(failures),
                "failure_samples": [asdict(failure) for failure in failures[:3]],
            }
        )
    return {
        "test_node": TEST_NODE,
        "iterations_per_variant": iterations,
        "attempts": len(attempts),
        "failures": sum(attempt.returncode != 0 for attempt in attempts),
        "variants": rows,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="pytest subprocesses per environment variant (default: 10)",
    )
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=4,
        help="concurrent subprocesses in the stress variants (default: 4)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be >= 1")
    if args.parallel_workers < 1:
        raise SystemExit("--parallel-workers must be >= 1")

    variants = _variants(args.parallel_workers)
    if not variants:
        raise SystemExit("no supported TMPDIR/Git variants found")
    labels = [variant.label for variant in variants]
    if len(labels) != len(set(labels)):
        raise SystemExit("environment variant labels are not unique")

    attempts: list[Attempt] = []
    with tempfile.TemporaryDirectory(prefix="orphan-reaper-flake-") as temp_dir:
        fixture_dir = Path(temp_dir)
        global_ignore = fixture_dir / "global-ignore"
        global_ignore.write_text("*.tmp\noutside.txt\n", encoding="utf-8")
        global_config = fixture_dir / "global-gitconfig"
        subprocess.run(
            [
                variants[0].git_binary,
                "config",
                "--file",
                str(global_config),
                "core.excludesFile",
                str(global_ignore),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        for variant in variants:
            attempts.extend(
                _run_variant(
                    variant,
                    args.iterations,
                    global_config=global_config,
                )
            )

    summary = _summarize(variants, attempts, iterations=args.iterations)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
