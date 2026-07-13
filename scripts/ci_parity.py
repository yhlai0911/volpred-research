"""Fail a local test run the same way a clean CI checkout would.

The bug class this closes, stated once: a test reads a file that exists on the
author's machine but is not in the repository. Locally it passes; on a fresh
`actions/checkout` the file is simply not there, so the test fails. pre-push
runs the suite in the working checkout, where those files DO exist, so pre-push
is green and CI is red — the two instruments disagree by construction, and the
author only finds out from a GitHub failure mail.

`frontend-v2-fix/` is the canonical example: a nested git repo, .gitignore'd by
the parent, present on every dev mac and absent from every CI runner
(29244725421 and 13 sibling runs, 2026-07-12/13).

The instrument is the audit hook rather than a source scan because the question
is about paths the suite ACTUALLY touches, not paths it spells. A source scan
sees `Path("frontend-v2-fix")` and misses `ROOT / cfg["active_frontend"]`, a
subprocess `cwd=`, or anything assembled at runtime. `sys.addaudithook` sees all
of them, because it fires inside CPython's open/stat/listdir/Popen.

Parity rule: an existing path under the repo root that git does not track would
not survive `git archive HEAD`, therefore it does not exist in CI, therefore any
test that reads it is machine-dependent. Untracked-but-not-ignored counts too —
a file the author forgot to `git add` breaks CI identically.

Not in scope (each already has its own owner, per anti-stacking):
  - tests WRITING repo state      → guard_canonical_write + the pytest.yml step
  - reads outside the repo root   → not a checkout-parity question
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = ROOT / "storage" / "ops" / "ci_parity_baseline.json"

# Runtime noise that is untracked by design and has nothing to do with checkout
# parity: the interpreter, its caches, and git's own plumbing. Anything here is
# either recreated by `uv sync` on the runner or never read by product code.
_NOISE_DIRS = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".uv",
    "node_modules",
    ".next",
    "storage/logs",  # append-only run logs; absence in CI changes no assertion
)


def _is_noise(rel: Path) -> bool:
    """Noise dirs nest — `experiments/K1655/__pycache__` is as much a cache as a
    top-level one. Matching only on the prefix reported every buried __pycache__
    as a parity break on the first real run."""
    parts = rel.parts
    for noise in _NOISE_DIRS:
        noise_parts = Path(noise).parts
        for i in range(len(parts) - len(noise_parts) + 1):
            if parts[i : i + len(noise_parts)] == noise_parts:
                return True
    return False


def _tracked_paths() -> set[str]:
    """Every path a clean `actions/checkout` would materialise.

    Files come straight from the index; their parent directories are added too,
    because a directory exists in the checkout exactly when it holds a tracked
    file (git stores no empty directories).
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    tracked: set[str] = set()
    for rel in out.split("\0"):
        if not rel:
            continue
        tracked.add(rel)
        parent = Path(rel).parent
        while str(parent) not in (".", "/"):
            tracked.add(str(parent))
            parent = parent.parent
    return tracked


def _load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return set(data.get("allowed_paths", []))


class CIParityPlugin:
    """Records untracked in-repo reads and attributes them to the test that did it."""

    # CPython audit events that mean "the suite looked at this path". `open`
    # covers read and write; writes are someone else's gate, but a write to an
    # untracked path is harmless here anyway because we only report paths that
    # existed BEFORE the suite touched them (see _record).
    _PATH_EVENTS = {
        "open": 0,
        "os.listdir": 0,
        "os.scandir": 0,
        "os.stat": 0,
        "pathlib.Path.glob": 0,
    }

    def __init__(self) -> None:
        self.tracked = _tracked_paths()
        self.baseline = _load_baseline()
        self.violations: dict[str, set[str]] = {}
        self.current_test = "<collection>"
        self._enabled = True
        # Snapshot taken before the suite runs: a path the suite CREATES is not a
        # parity break (it is a canonical-write leak, which pytest.yml owns).
        # Only paths that already existed can make a local run diverge from CI.
        self._preexisting: dict[str, bool] = {}

    # ---- audit hook -------------------------------------------------------
    def audit(self, event: str, args: tuple) -> None:
        if not self._enabled or event not in self._PATH_EVENTS:
            return
        raw = args[self._PATH_EVENTS[event]]
        if not isinstance(raw, (str, bytes, os.PathLike)):
            return  # open() on an fd, not a path
        try:
            path = Path(os.fsdecode(raw))
        except (ValueError, TypeError):  # silent-ok: an un-decodable arg is not a path; nothing to judge
            return
        self._record(path)

    def _record(self, path: Path) -> None:
        # Re-entrancy: everything below (resolve, exists) itself triggers os.stat
        # audit events. Without this the hook recurses until the stack blows.
        self._enabled = False
        try:
            abs_path = path if path.is_absolute() else (Path.cwd() / path)
            try:
                rel = abs_path.resolve().relative_to(ROOT)
            except (ValueError, OSError):  # silent-ok: relative_to raises for every path outside ROOT — that is the filter, not a failure
                return  # outside the repo — not a checkout-parity question
            rel_str = str(rel)
            if rel_str == ".":
                return
            if _is_noise(rel):
                return
            if rel_str in self.tracked:
                return
            if rel_str in self.baseline:
                return
            existed = self._preexisting.get(rel_str)
            if existed is None:
                existed = abs_path.exists()
                self._preexisting[rel_str] = existed
            if not existed:
                return  # absent here too — the test already handles its absence
            self.violations.setdefault(rel_str, set()).add(self.current_test)
        finally:
            self._enabled = True

    # ---- pytest hooks -----------------------------------------------------
    def pytest_collection_modifyitems(self, session, config, items) -> None:
        # The audit hook cannot see conftest.py: pytest imports it before any
        # plugin exists to watch. That blind spot is not academic — the root
        # conftest.py holding all four production guards was .gitignore'd from
        # 2026-07-10 to 2026-07-14 and therefore never existed on a runner, so
        # every test under scripts/tests/ ran in CI with VOLPRED_NO_REMOTE_READ
        # unset. Nothing noticed, because the file was right there locally.
        self._enabled = False
        try:
            seen: set[Path] = set()
            for item in items:
                path = Path(str(item.path))
                for candidate in (path, *path.parents):
                    if candidate == ROOT:
                        break
                    seen.add(candidate)
                seen.add(path)
            for path in seen:
                if path.name != "conftest.py" and not path.name.startswith("test"):
                    continue
                if not path.exists():
                    continue
                try:
                    rel_str = str(path.resolve().relative_to(ROOT))
                except ValueError:  # silent-ok: same out-of-repo filter as above
                    continue
                if rel_str in self.tracked or rel_str in self.baseline:
                    continue
                self.violations.setdefault(rel_str, set()).add(
                    "<pytest loaded this file, but git does not track it>"
                )
            # conftest.py sits beside the test dirs, so the loop above only sees
            # it via item.path parents; name it explicitly for the root one.
            for conftest in (ROOT / "conftest.py",):
                if not conftest.exists():
                    continue
                rel_str = str(conftest.relative_to(ROOT))
                if rel_str in self.tracked or rel_str in self.baseline:
                    continue
                self.violations.setdefault(rel_str, set()).add(
                    "<pytest loaded this file, but git does not track it>"
                )
        finally:
            self._enabled = True

    def pytest_runtest_protocol(self, item) -> None:
        self.current_test = item.nodeid

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        self._enabled = False
        if not self.violations:
            return
        lines = [
            "",
            "=" * 72,
            "CI-PARITY FAILURE — these tests read files that are NOT in the repo.",
            "They pass here and fail on a clean `actions/checkout`, which is what",
            "CI runs. That divergence is the bug, not the red CI run.",
            "=" * 72,
        ]
        for rel_str in sorted(self.violations):
            lines.append(f"\n  {rel_str}")
            for nodeid in sorted(self.violations[rel_str]):
                lines.append(f"      read by  {nodeid}")
        lines += [
            "",
            "Fix at the test, one of:",
            "  - skip when the path is absent (pytest.skip / a guard clause), or",
            "  - build the fixture under tmp_path instead of reading the live tree, or",
            "  - `git add` the file if it genuinely belongs in the repo.",
            f"\nDeliberate, permanent exception → add the path to {BASELINE_PATH.relative_to(ROOT)}",
            "(that file is a ratchet: entries may be removed, never added casually).",
            "",
        ]
        print("\n".join(lines), file=sys.stderr)
        session.exitstatus = 1


def install(config) -> None:
    """Register the plugin unless we are already running on a clean checkout.

    Pointless in CI: the untracked files simply are not there, so there is
    nothing to detect. The instrument only has information to give on the
    machine that has them — the dev checkout, at pre-push time.
    """
    if os.environ.get("CI") or os.environ.get("VOLPRED_CI_PARITY") == "0":
        return
    plugin = CIParityPlugin()
    sys.addaudithook(plugin.audit)
    config.pluginmanager.register(plugin, "volpred_ci_parity")
