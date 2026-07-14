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
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
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


def _gate_alerts(calls: list[dict]) -> list[dict]:
    """Only the test-gate's own red-light alerts. PHASE-Z also raises an
    orthogonal warn when a commit lands without an agent-supplied reason; that
    one is not this gate's concern and must not be counted here."""
    return [c for c in calls if "紅燈" in c.get("title", "")]


def test_junit_failure_identity_is_machine_readable(tmp_path: Path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        '<testsuite><testcase file="tests/test_x.py" classname="TestX" name="test_bad">'
        '<failure message="boom"/></testcase><testcase name="test_ok"/></testsuite>',
        encoding="utf-8",
    )
    assert phase_z._junit_failure_ids(junit) == {"tests/test_x.py::TestX::test_bad"}


def test_gate_skips_when_commit_touches_only_docs_and_json(tmp_path: Path) -> None:
    # A drafted article / config edit is not gated code — the gate must not spend
    # a pytest run on it, and must record WHY it skipped (observable, not silent).
    _init_repo(tmp_path, {"seed.txt": "seed\n"})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("# note\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"k": 1}\n', encoding="utf-8")
    test_runner, calls = _recording_runner()
    alert_fn, _alerts = _recording_alert()

    # baseline = clean tree at fire start, so every dirty path is this fire's.
    # Without it PHASE-Z declines to commit and there is nothing for the gate
    # to check (docs/error_log.md 2026-07-10 — `git add -A` had no owner).
    out = phase_z.run_phase_z(
        pre_fire_dirty=set(),
        repo_root=tmp_path, now_hhmm="16:07", test_runner=test_runner,
        alert_fn=alert_fn,
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
        alert_fn=lambda **_kwargs: {},
    )

    assert out["committed"] is True
    assert len(calls) == 1
    argv = calls[0]
    assert "tests/test_foo.py" in argv  # precise file targeted by path
    assert "-k" not in argv  # precise mapping → no keyword filter
    assert out["tests"]["passed"] is True
    assert out["tests"]["reason"] == "green"
    assert out["tests"]["ran"] == ["tests/test_foo.py"]


def test_gate_new_failure_alerts_only_after_parent_comparison(tmp_path: Path) -> None:
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("VALUE = 2\n", encoding="utf-8")
    before = _head_count(tmp_path)

    pytest_cwds: list[Path] = []

    def red_runner(argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        assert cwd != tmp_path
        assert (cwd / ".git").exists(), "pytest must be bound to the disposable clone"
        pytest_cwds.append(cwd)
        if len(pytest_cwds) == 1:
            return _FakeCompleted(
                1,
                stdout="FAILED tests/test_foo.py::test_foo - assert 1 == 2\n1 failed in 0.02s\n",
            )
        return _FakeCompleted(0, stdout="1 passed in 0.01s\n")

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
    assert out["tests"]["reason"] == "new_failure"
    assert out["tests"]["returncode"] == 1
    assert out["tests"]["parent_returncode"] == 0
    assert len(pytest_cwds) == 2
    assert pytest_cwds[0] != pytest_cwds[1]
    # a critical alert was raised through the injected alert path
    gate = _gate_alerts(alerts)
    assert len(gate) == 1
    assert gate[0]["level"] == "critical"
    # NO auto-revert — the commit stays; only one new commit exists (no revert commit)
    assert _head_count(tmp_path) == before + 1
    assert _head_subject(tmp_path).startswith("dispatch(16:07):")


def test_gate_pre_existing_failure_is_not_attributed_or_alerted(tmp_path: Path) -> None:
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("VALUE = 2\n", encoding="utf-8")
    alert_fn, alerts = _recording_alert()

    def same_red_runner(argv, **kwargs):
        return _FakeCompleted(
            1,
            stdout="FAILED tests/test_foo.py::test_foo - assert False\n1 failed in 0.02s\n",
        )

    out = phase_z.run_phase_z(
        pre_fire_dirty=set(), repo_root=tmp_path, now_hhmm="16:07",
        test_runner=same_red_runner, alert_fn=alert_fn,
    )

    assert out["committed"] is True
    assert out["tests"]["reason"] == "pre_existing_failure"
    assert out["tests"]["parent_returncode"] == 1
    assert _gate_alerts(alerts) == []


def test_gate_detects_new_node_even_when_parent_was_already_red(tmp_path: Path) -> None:
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("VALUE = 2\n", encoding="utf-8")
    alert_fn, alerts = _recording_alert()
    calls = 0

    def different_red_runner(argv, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _FakeCompleted(
                1,
                stdout=("FAILED tests/test_foo.py::test_old - assert False\n"
                        "FAILED tests/test_foo.py::test_new - assert False\n2 failed\n"),
            )
        return _FakeCompleted(1, stdout="FAILED tests/test_foo.py::test_old - assert False\n1 failed\n")

    out = phase_z.run_phase_z(
        pre_fire_dirty=set(), repo_root=tmp_path, now_hhmm="16:07",
        test_runner=different_red_runner, alert_fn=alert_fn,
    )

    assert out["tests"]["reason"] == "new_failure"
    assert out["tests"]["failure_ids"] == [
        "tests/test_foo.py::test_new",
        "tests/test_foo.py::test_old",
    ]
    assert out["tests"]["parent_failure_ids"] == ["tests/test_foo.py::test_old"]
    assert len(_gate_alerts(alerts)) == 1


def test_gate_collection_error_is_separate_and_never_critical(tmp_path: Path) -> None:
    _init_repo(tmp_path, {"seed.txt": "seed\n", "tests/test_foo.py": "def test_foo():\n    assert True\n"})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "foo.py").write_text("VALUE = 2\n", encoding="utf-8")
    alert_fn, alerts = _recording_alert()
    calls = 0

    def collection_runner(argv, **kwargs):
        nonlocal calls
        calls += 1
        return _FakeCompleted(2, stdout="ERROR collecting tests/test_foo.py\n")

    out = phase_z.run_phase_z(
        pre_fire_dirty=set(), repo_root=tmp_path, now_hhmm="16:07",
        test_runner=collection_runner, alert_fn=alert_fn,
    )

    assert out["committed"] is True
    assert out["tests"]["reason"] == "collection_error"
    assert calls == 1, "collection failure is classified, not compared as a test failure"
    assert _gate_alerts(alerts) == []


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
    # a timeout is "could not verify", not a confirmed red → no red-light alert
    assert _gate_alerts(alerts) == []


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
        alert_fn=lambda **_kwargs: {},
    )

    assert out["committed"] is True
    assert calls == []  # nothing to run → no pytest spawned
    assert out["tests"]["passed"] is None
    assert out["tests"]["reason"] == "no_mapped_tests"
    assert "scripts/orphan.py" in out["tests"]["unmapped"]


def test_gate_source_reference_maps_to_concrete_file_without_k_filter(tmp_path: Path) -> None:
    # No tests/test_widget*.py and the node id is deliberately generic.  The
    # dependency lives only in the source body, which pytest -k does not search.
    _init_repo(tmp_path, {
        "seed.txt": "seed\n",
        "tests/test_misc.py": (
            "import importlib\n\n"
            "def test_dynamic_loader():\n"
            "    assert importlib.import_module('scripts.widget').go()\n"
        ),
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
        alert_fn=lambda **_kwargs: {},
    )

    assert out["committed"] is True
    assert len(calls) == 1
    argv = calls[0]
    assert "tests/test_misc.py" in argv
    assert "-k" not in argv
    assert out["tests"]["passed"] is True
    assert out["tests"]["k_expr"] is None


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
        alert_fn=lambda **_kwargs: {},
    )

    assert out["tests"]["passed"] is None
    assert out["tests"]["reason"] == "no_tests_collected"
