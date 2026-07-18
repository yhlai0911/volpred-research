"""A dirty-at-fire-start path that is the missing half of a landed commit must
have an exit (CI red 3 cycles, run 29653262702).

The incident: commit `4684b5e02` landed a test plus two modules, but the asset
that test asserts on — `scripts/cron_hourly_dispatch_prompt.md` — stayed in the
working tree. Locally green, CI red, forever. PHASE-Z's ownership model saw the
asset as dirty-before-the-fire, i.e. "another session is still typing it", and
skipped it EVERY fire. Same class as the 2026-07-18 untracked-closeout pin: a
path in a bucket with no state transition out of it.

"Dirty before the fire" ⇒ "someone else's work in progress" is an INFERENCE with
exactly one mechanically falsifiable exception, and the direction of the evidence
is the entire safety argument:

    A test ALREADY COMMITTED at HEAD is RED, and this path's working-tree bytes
    turn that same test GREEN in an isolated clone.

Real work in progress does not repair a test that HEAD already ships. Only the
missing half does. These pins hold the exception NARROW: no red test at HEAD, no
proof, a broken probe, or a test file as the candidate ⇒ adopt nothing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout


# Committed test files in the fixture repo. The fake pytest runner below decides
# each one's colour from the CLONE's bytes, which is what makes the probe's
# evidence direction observable in a unit test.
_ASSET_TEST = "scripts/tests/test_asset_lane.py"
_WIP_TEST = "scripts/tests/test_wip_thing.py"
_QUIET_TEST = "scripts/tests/test_quiet_thing.py"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    _git(r, "config", "user.email", "t@t.t")
    _git(r, "config", "user.name", "t")
    hook = r / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)

    (r / "scripts" / "tests").mkdir(parents=True)
    # The asset half of a split commit: the test landed, the asset did not.
    (r / "scripts" / "asset_lane.md").write_text("prompt without the token\n")
    (r / _ASSET_TEST).write_text("def test_asset_lane_mentions_token():\n    assert True\n")
    # An unrelated module with a genuinely pre-existing red test.
    (r / "scripts" / "wip_thing.py").write_text("VALUE = 1\n")
    (r / _WIP_TEST).write_text("def test_wip_thing():\n    assert True\n")
    # An unrelated module whose test is green — nothing for a probe to repair.
    (r / "scripts" / "quiet_thing.py").write_text("VALUE = 1\n")
    (r / _QUIET_TEST).write_text("def test_quiet_thing():\n    assert True\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "seed")
    return r


def _fake_pytest(*, wip_always_red: bool = True):
    """A pytest stand-in whose verdict is read off the clone it is run in.

    `scripts/tests/test_asset_lane.py` is green exactly when the clone's
    `scripts/asset_lane.md` contains TOKEN — i.e. only when the missing half has
    been materialised. Everything else is fixed, so any adoption the probe makes
    must come from that one flip.
    """

    def runner(argv, **kwargs):
        clone_root = Path(kwargs["cwd"])
        targets = [a for a in argv if isinstance(a, str) and a.endswith(".py")
                   and "tests/" in a]
        failed: list[str] = []
        for target in targets:
            if target.endswith("test_asset_lane.py"):
                asset = clone_root / "scripts" / "asset_lane.md"
                text = asset.read_text(encoding="utf-8") if asset.is_file() else ""
                if "TOKEN" not in text:
                    failed.append(f"{target}::test_asset_lane_mentions_token")
            elif target.endswith("test_wip_thing.py") and wip_always_red:
                failed.append(f"{target}::test_wip_thing")
        if not targets:
            return subprocess.CompletedProcess(argv, phase_z._PYTEST_NO_TESTS_COLLECTED, "", "")
        if not failed:
            return subprocess.CompletedProcess(argv, 0, f"{len(targets)} passed\n", "")
        out = "\n".join(f"FAILED {node}" for node in failed)
        return subprocess.CompletedProcess(argv, 1, out + "\n1 failed\n", "")

    return runner


def _dirty(repo: Path) -> set[str]:
    return phase_z._dirty_paths(repo, subprocess.run) or set()


def _fire(repo: Path, alerts: list[dict], *, test_runner=None, baseline=None) -> dict:
    """Fire with the whole tree declared dirty-at-fire-start unless told otherwise.

    Passing the full dirty set as the baseline is the scenario under test: every
    candidate is FOREIGN, so anything that gets committed was adopted purely on
    the probe's evidence, never by ordinary ownership.
    """
    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="07:07",
        pre_fire_dirty=_dirty(repo) if baseline is None else baseline,
        test_runner=test_runner or _fake_pytest(),
        alert_fn=lambda **k: alerts.append(k) or {},
    )


# --------------------------------------------------------------------------
# The exception: a proved missing half is adopted.
# --------------------------------------------------------------------------

def test_missing_half_of_a_landed_commit_is_adopted(repo: Path) -> None:
    (repo / "scripts" / "asset_lane.md").write_text("prompt with TOKEN\n")
    alerts: list[dict] = []

    result = _fire(repo, alerts)

    assert result["committed"] is True, result
    assert result["orphan_halves"]["adopted"] == ["scripts/asset_lane.md"]
    committed = _git(repo, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert committed == ["scripts/asset_lane.md"], committed
    assert "TOKEN" in _git(repo, "show", "HEAD:scripts/asset_lane.md")


def test_adoption_names_the_path_and_the_test_that_turned_green(repo: Path) -> None:
    """Silent adoption would repeat every incident this file has been fixing."""
    (repo / "scripts" / "asset_lane.md").write_text("prompt with TOKEN\n")
    alerts: list[dict] = []

    result = _fire(repo, alerts)

    evidence = result["orphan_halves"]["evidence"]["scripts/asset_lane.md"]
    assert evidence["turned_green"] == [f"{_ASSET_TEST}::test_asset_lane_mentions_token"]
    message = _git(repo, "log", "-1", "--pretty=%B")
    assert "scripts/asset_lane.md" in message
    assert "test_asset_lane_mentions_token" in message


# --------------------------------------------------------------------------
# The default answer, which must stay NO.
# --------------------------------------------------------------------------

def test_third_party_work_in_progress_is_not_adopted(repo: Path) -> None:
    """Its test is red at HEAD and stays red with its bytes applied."""
    (repo / "scripts" / "wip_thing.py").write_text("VALUE = 2  # half-typed\n")
    alerts: list[dict] = []

    result = _fire(repo, alerts)

    assert result["committed"] is False
    assert result["reason"] == "nothing_owned"
    assert result["orphan_halves"]["adopted"] == []
    assert "scripts/wip_thing.py" in result["foreign"]


def test_dirty_path_with_no_red_test_is_not_adopted(repo: Path) -> None:
    """Nothing at HEAD is broken in a way these bytes could repair."""
    (repo / "scripts" / "quiet_thing.py").write_text("VALUE = 2\n")
    alerts: list[dict] = []

    result = _fire(repo, alerts, test_runner=_fake_pytest(wip_always_red=False))

    assert result["committed"] is False
    assert result["orphan_halves"]["adopted"] == []
    assert result["orphan_halves"]["reason"] == "head_not_red"


def test_only_the_proved_path_is_adopted_from_a_mixed_dirty_tree(repo: Path) -> None:
    """The adopted set is the PROVED MINIMUM, never "everything in the baseline"."""
    (repo / "scripts" / "asset_lane.md").write_text("prompt with TOKEN\n")
    (repo / "scripts" / "wip_thing.py").write_text("VALUE = 2  # half-typed\n")
    (repo / "scripts" / "quiet_thing.py").write_text("VALUE = 3\n")
    (repo / "notes.txt").write_text("outside the gated trees\n")
    (repo / "src").mkdir()
    (repo / "src" / "stray.py").write_text("x = 1\n")
    alerts: list[dict] = []

    result = _fire(repo, alerts)

    assert result["orphan_halves"]["adopted"] == ["scripts/asset_lane.md"]
    committed = _git(repo, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert committed == ["scripts/asset_lane.md"], committed
    still_dirty = _dirty(repo)
    for survivor in ("scripts/wip_thing.py", "scripts/quiet_thing.py",
                     "notes.txt", "src/stray.py"):
        assert survivor in still_dirty, survivor


def test_a_dirty_test_file_is_never_a_candidate(repo: Path) -> None:
    """Adopting a working-tree test would let a relaxed assertion adopt itself.

    The probe would then be reading the candidate's own thermometer instead of
    HEAD's, which is the one way this rule could be turned into its opposite.
    """
    (repo / _ASSET_TEST).write_text("def test_asset_lane_mentions_token():\n    pass\n")
    assert phase_z._orphan_half_candidates(repo, [_ASSET_TEST, "scripts/asset_lane.md"]) == [
        "scripts/asset_lane.md"
    ]
    assert phase_z._is_test_path("tests/test_x.py")
    assert phase_z._is_test_path("scripts/tests/helpers.py")
    assert not phase_z._is_test_path("scripts/cron_hourly_dispatch_prompt.md")


def test_deletions_and_ungated_paths_are_never_candidates(repo: Path) -> None:
    (repo / "scripts" / "quiet_thing.py").unlink()
    candidates = phase_z._orphan_half_candidates(
        repo,
        ["scripts/quiet_thing.py", "storage/next_tasks.json",
         "experiments/k1380/k1380.py", "scripts/asset_lane.md"],
    )
    assert candidates == ["scripts/asset_lane.md"]


# --------------------------------------------------------------------------
# Fail-closed: no evidence, no adoption.
# --------------------------------------------------------------------------

def test_pytest_timeout_adopts_nothing_and_says_so(repo: Path) -> None:
    (repo / "scripts" / "asset_lane.md").write_text("prompt with TOKEN\n")

    def timing_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    outcome = phase_z._adopt_orphan_halves(
        repo, ["scripts/asset_lane.md"], runner=subprocess.run, test_runner=timing_out,
    )

    assert outcome["adopted"] == []
    assert outcome["reason"] == "head_timeout"


def test_clone_failure_adopts_nothing_and_says_so(repo: Path) -> None:
    (repo / "scripts" / "asset_lane.md").write_text("prompt with TOKEN\n")

    def broken_clone(argv, **kwargs):
        if list(argv[:2]) == ["git", "clone"]:
            return subprocess.CompletedProcess(argv, 128, "", "fatal: cannot clone")
        return subprocess.run(argv, **kwargs)

    outcome = phase_z._adopt_orphan_halves(
        repo, ["scripts/asset_lane.md"], runner=broken_clone,
        test_runner=_fake_pytest(),
    )

    assert outcome["adopted"] == []
    assert outcome["reason"] == "clone_error"


def test_too_many_candidates_declines_instead_of_probing_a_subset(repo: Path) -> None:
    """A truncated scan would answer "not a missing half" for paths it never ran."""
    many = []
    for i in range(phase_z._ORPHAN_HALF_MAX_CANDIDATES + 1):
        rel = f"scripts/bulk_{i}.py"
        (repo / rel).write_text("x = 1\n")
        many.append(rel)

    outcome = phase_z._adopt_orphan_halves(
        repo, many, runner=subprocess.run, test_runner=_fake_pytest(),
    )

    assert outcome["adopted"] == []
    assert outcome["reason"] == "too_many_candidates"


def test_budget_exhaustion_stops_the_probe(repo: Path) -> None:
    (repo / "scripts" / "asset_lane.md").write_text("prompt with TOKEN\n")
    clock = iter([0.0, 10.0 ** 9, 10.0 ** 9])

    outcome = phase_z._adopt_orphan_halves(
        repo, ["scripts/asset_lane.md"], runner=subprocess.run,
        test_runner=_fake_pytest(), monotonic=lambda: next(clock),
    )

    assert outcome["adopted"] == []
    assert outcome["reason"] == "budget_exhausted"


# --------------------------------------------------------------------------
# The existing ownership model must be untouched.
# --------------------------------------------------------------------------

def test_this_fires_own_output_still_commits_normally(repo: Path) -> None:
    """The probe is an added exception, not a rewrite of the ownership model."""
    (repo / "scripts" / "new_output.md").write_text("produced by this fire\n")
    alerts: list[dict] = []

    result = _fire(repo, alerts, baseline=set())

    assert result["committed"] is True, result
    assert result["owned"] == ["scripts/new_output.md"]
    assert result["orphan_halves"]["adopted"] == []
    committed = _git(repo, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert committed == ["scripts/new_output.md"], committed


def test_recovery_pass_does_not_pay_for_the_probe_twice(repo: Path) -> None:
    """The real fire follows immediately; probing in both halves buys one answer."""
    (repo / "scripts" / "asset_lane.md").write_text("prompt with TOKEN\n")
    calls: list[list] = []

    def counting(argv, **kwargs):
        calls.append(list(argv))
        return _fake_pytest()(argv, **kwargs)

    result = phase_z.run_phase_z(
        repo_root=repo, now_hhmm="07:07", pre_fire_dirty=_dirty(repo),
        test_runner=counting, alert_fn=lambda **k: {}, recovery_mode=True,
    )

    assert result["orphan_halves"]["reason"] == "recovery_mode"
    assert result["orphan_halves"]["adopted"] == []
    assert calls == []
