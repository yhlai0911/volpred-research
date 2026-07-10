"""Post-commit test gate for PHASE-Z safety-net auto-commits.

Guards the wound in docs/error_log.md dab3baa12: a safety-net commit rewrote
gmail_inbox_poll production straight into main, bypassing the test gate, and the
red test sat red on main for 5 days. run_phase_z now re-runs the tests a commit
put at risk. These tests inject a FAKE test-runner (never a real pytest — that
would recurse) and a fake alert_fn, exactly the `runner=` injection style the
rest of phase_z already uses.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.dispatch_supervisor import phase_z


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
    )


def _init_repo(root: Path, seed: dict[str, str]) -> None:
    """Hermetic repo seeded with `seed` (relpath → contents), all committed."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@volpred.local")
    _git(root, "config", "user.name", "phase-z-gate-test")
    _git(root, "config", "commit.gpgsign", "false")
    for rel, contents in seed.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(contents, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")


def _head_count(root: Path) -> int:
    return int(_git(root, "rev-list", "--count", "HEAD").stdout.strip())


def _head_subject(root: Path) -> str:
    return _git(root, "log", "-1", "--pretty=%s").stdout.strip()


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _recording_runner():
    """A fake test-runner that records its argv and returns green by default."""
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return _FakeCompleted(0, stdout="1 passed in 0.01s\n")

    return runner, calls


def _recording_alert():
    calls: list[dict] = []

    def alert_fn(**kwargs):
        calls.append(kwargs)
        return {"sent": True}

    return alert_fn, calls


def test_gate_skips_when_commit_touches_only_docs_and_json(tmp_path: Path) -> None:
    # A drafted article / config edit is not gated code — the gate must not spend
    # a pytest run on it, and must record WHY it skipped (observable, not silent).
    _init_repo(tmp_path, {"seed.txt": "seed\n"})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("# note\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"k": 1}\n', encoding="utf-8")
    test_runner, calls = _recording_runner()

    # baseline = clean tree at fire start, so every dirty path is this fire's.
    # Without it PHASE-Z declines to commit and there is nothing for the gate
    # to check (docs/error_log.md 2026-07-10 — `git add -A` had no owner).
    out = phase_z.run_phase_z(
        pre_fire_dirty=set(),
        repo_root=tmp_path, now_hhmm="16:07", test_runner=test_runner,
    )

    assert out["committed"] is True
    assert calls == []  # no pytest spawned for a docs/json-only commit
    assert out["tests"]["passed"] is None
    assert out["tests"]["reason"] == "skipped_non_code"


def test_gate_runs_precise_test_and_reports_green(tmp_path: Path) -> None:
    # Pre-seed the test file so it is already tracked (not part of the PHASE-Z
    # commit); only scripts/foo.py is the changed gated file → precise mapping.
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("VALUE = 1\n", encoding="utf-8")
    test_runner, calls = _recording_runner()

    # baseline = clean tree at fire start, so every dirty path is this fire's.
    # Without it PHASE-Z declines to commit and there is nothing for the gate
    # to check (docs/error_log.md 2026-07-10 — `git add -A` had no owner).
    out = phase_z.run_phase_z(
        pre_fire_dirty=set(),
        repo_root=tmp_path, now_hhmm="16:07", test_runner=test_runner,
    )

    assert out["committed"] is True
    assert len(calls) == 1
    argv = calls[0]
    assert "tests/test_foo.py" in argv  # precise file targeted by path
    assert "-k" not in argv  # precise mapping → no keyword filter
    assert out["tests"]["passed"] is True
    assert out["tests"]["reason"] == "green"
    assert out["tests"]["ran"] == ["tests/test_foo.py"]


def test_gate_red_alerts_and_does_not_revert(tmp_path: Path) -> None:
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("VALUE = 2\n", encoding="utf-8")
    before = _head_count(tmp_path)

    def red_runner(argv, **kwargs):
        return _FakeCompleted(1, stdout="E   assert 1 == 2\n1 failed in 0.02s\n")

    alert_fn, alerts = _recording_alert()

    # baseline = clean tree at fire start, so every dirty path is this fire's.
    # Without it PHASE-Z declines to commit and there is nothing for the gate
    # to check (docs/error_log.md 2026-07-10 — `git add -A` had no owner).
    out = phase_z.run_phase_z(
        pre_fire_dirty=set(),
        repo_root=tmp_path, now_hhmm="16:07",
        test_runner=red_runner, alert_fn=alert_fn,
    )

    assert out["committed"] is True
    assert out["tests"]["passed"] is False
    assert out["tests"]["reason"] == "red"
    assert out["tests"]["returncode"] == 1
    # a critical alert was raised through the injected alert path
    assert len(alerts) == 1
    assert alerts[0]["level"] == "critical"
    assert "紅燈" in alerts[0]["title"]
    # NO auto-revert — the commit stays; only one new commit exists (no revert commit)
    assert _head_count(tmp_path) == before + 1
    assert _head_subject(tmp_path).startswith("ops(dispatch-supervisor 16:07): PHASE-Z")


def test_gate_runner_timeout_is_observable_and_does_not_crash(tmp_path: Path) -> None:
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("VALUE = 3\n", encoding="utf-8")
    alert_fn, alerts = _recording_alert()

    def timeout_runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout"))

    # must not raise — the commit already landed; a wedged runner cannot undo it
    # baseline = clean tree at fire start, so every dirty path is this fire's.
    # Without it PHASE-Z declines to commit and there is nothing for the gate
    # to check (docs/error_log.md 2026-07-10 — `git add -A` had no owner).
    out = phase_z.run_phase_z(
        pre_fire_dirty=set(),
        repo_root=tmp_path, now_hhmm="16:07",
        test_runner=timeout_runner, alert_fn=alert_fn,
    )

    assert out["committed"] is True
    assert out["tests"]["passed"] is None
    assert out["tests"]["reason"] == "timeout"
    assert alerts == []  # a timeout is "could not verify", not a confirmed red


def test_gate_records_code_change_with_no_matching_test(tmp_path: Path) -> None:
    # scripts/orphan.py has no tests/test_orphan*.py and the stem appears nowhere
    # in the tests tree → must be recorded as unmapped, NEVER passed=True.
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "orphan.py").write_text("VALUE = 4\n", encoding="utf-8")
    test_runner, calls = _recording_runner()

    # baseline = clean tree at fire start, so every dirty path is this fire's.
    # Without it PHASE-Z declines to commit and there is nothing for the gate
    # to check (docs/error_log.md 2026-07-10 — `git add -A` had no owner).
    out = phase_z.run_phase_z(
        pre_fire_dirty=set(),
        repo_root=tmp_path, now_hhmm="16:07", test_runner=test_runner,
    )

    assert out["committed"] is True
    assert calls == []  # nothing to run → no pytest spawned
    assert out["tests"]["passed"] is None
    assert out["tests"]["reason"] == "no_mapped_tests"
    assert "scripts/orphan.py" in out["tests"]["unmapped"]


def test_gate_keyword_fallback_when_no_precise_file(tmp_path: Path) -> None:
    # No tests/test_widget*.py, but a test file mentions the stem `widget` in its
    # body → keyword fallback runs the tests/ dir filtered by `-k widget`.
    _init_repo(tmp_path, {
        "seed.txt": "seed\n",
        "tests/test_misc.py": "from scripts.widget import go\n\ndef test_widget_go():\n    assert go()\n",
    })
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "widget.py").write_text("def go():\n    return True\n", encoding="utf-8")
    test_runner, calls = _recording_runner()

    # baseline = clean tree at fire start, so every dirty path is this fire's.
    # Without it PHASE-Z declines to commit and there is nothing for the gate
    # to check (docs/error_log.md 2026-07-10 — `git add -A` had no owner).
    out = phase_z.run_phase_z(
        pre_fire_dirty=set(),
        repo_root=tmp_path, now_hhmm="16:07", test_runner=test_runner,
    )

    assert out["committed"] is True
    assert len(calls) == 1
    argv = calls[0]
    assert "tests" in argv  # keyword fallback targets the tests dir
    assert "-k" in argv
    assert "widget" in argv[argv.index("-k") + 1]
    assert out["tests"]["passed"] is True
    assert out["tests"]["k_expr"] == "widget"


def test_gate_no_tests_collected_is_not_a_pass(tmp_path: Path) -> None:
    # pytest exit 5 (nothing collected) must be classified no_tests, not green.
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("VALUE = 5\n", encoding="utf-8")

    def empty_runner(argv, **kwargs):
        return _FakeCompleted(5, stdout="no tests ran\n")

    # baseline = clean tree at fire start, so every dirty path is this fire's.
    # Without it PHASE-Z declines to commit and there is nothing for the gate
    # to check (docs/error_log.md 2026-07-10 — `git add -A` had no owner).
    out = phase_z.run_phase_z(
        pre_fire_dirty=set(),
        repo_root=tmp_path, now_hhmm="16:07", test_runner=empty_runner,
    )

    assert out["tests"]["passed"] is None
    assert out["tests"]["reason"] == "no_tests_collected"
