"""PHASE-Z drain must converge — never livelock, never alert-spam (2026-07-13).

Regression pins for the 21:29 incident (error_log 2026-07-13 21:55): a pre-commit
gate blocked PHASE-Z's commit, the pre-fire snapshot had already been consumed,
and the scheduler's retry-until-terminal loop degraded every subsequent tick into
`ownership_unknown` — whose alert path fired an identical warn to the boss every
~64s, 14+ times, while the actually-actionable fact (the gate block) never
reached any alert.

Three conditions, three pins:
  1. a failed commit must NOT consume the fire-start baseline (retries keep
     knowing what the fire owns);
  2. `ownership_unknown` is terminal — no baseline can ever appear via retry;
  3. non-terminal drains give up loudly after a bounded number of attempts.
"""
from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z, scheduler, state


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A hermetic repo — never the real one (per feedback_hermetic_git_in_tests)."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r.parent, "init", "-q", str(r))
    _git(r, "config", "user.email", "t@t.t")
    _git(r, "config", "user.name", "t")
    hook = r / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    (r / "seed.txt").write_text("seed\n")
    _git(r, "add", "seed.txt")
    _git(r, "commit", "-qm", "seed")
    return r


def _install_blocking_hook(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho '[pre-commit] BLOCKED — fake gate' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)


def _snapshot_file(repo: Path) -> Path:
    return repo / ".git" / phase_z._SNAPSHOT_BASENAME


def _run(repo: Path, alerts: list[dict]) -> dict:
    """run_phase_z reading the REAL on-disk snapshot (pre_fire_dirty not injected)."""
    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="07:07",
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: alerts.append(k) or {},
    )


def test_blocked_commit_keeps_baseline_and_never_degrades(repo: Path):
    """Pin 1: the incident's exact shape. Commit blocked by a pre-commit gate →
    the snapshot survives, so a retry is still `commit_nonzero` (ownership
    intact), NOT `ownership_unknown`. Before the fix the second run degraded."""
    assert phase_z._write_pre_fire_snapshot(repo, set(), subprocess.run)
    (repo / "out.txt").write_text("agent output\n")
    _install_blocking_hook(repo)
    alerts: list[dict] = []

    first = _run(repo, alerts)
    assert first["reason"] == "commit_nonzero"
    assert "BLOCKED" in first["commit_tail"]  # the actionable fact travels with the outcome
    assert _snapshot_file(repo).exists(), "failed commit must not consume the baseline"

    second = _run(repo, alerts)
    assert second["reason"] == "commit_nonzero", (
        f"retry degraded to {second['reason']!r} — baseline was lost")
    assert not any("沒有 fire 起始基線" in a.get("title", "") for a in alerts)


def test_blocked_candidate_preserves_head_index_and_working_bytes(repo: Path):
    """Alternate-index transaction: a hook veto cannot leave half the fire staged."""
    (repo / "foreign.txt").write_text("another writer\n")
    _git(repo, "add", "foreign.txt")
    before_tree = _git(repo, "write-tree").strip()
    before_head = _git(repo, "rev-parse", "HEAD").strip()
    assert phase_z._write_pre_fire_snapshot(repo, {"foreign.txt"}, subprocess.run)
    (repo / "out.txt").write_text("agent output\n")
    _install_blocking_hook(repo)

    out = _run(repo, [])

    assert out["reason"] == "commit_nonzero"
    assert out["rolled_back"] is True
    assert _git(repo, "rev-parse", "HEAD").strip() == before_head
    assert _git(repo, "write-tree").strip() == before_tree
    assert (repo / "out.txt").read_text() == "agent output\n"
    assert (repo / "foreign.txt").read_text() == "another writer\n"


def test_blocking_hook_side_effect_stays_in_disposable_candidate(repo: Path):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\necho touched > hook-side-effect.txt\necho BLOCKED >&2\nexit 1\n"
    )
    hook.chmod(0o755)
    assert phase_z._write_pre_fire_snapshot(repo, set(), subprocess.run)
    (repo / "out.txt").write_text("agent output\n")

    out = _run(repo, [])

    assert out["reason"] == "commit_nonzero"
    assert not (repo / "hook-side-effect.txt").exists()
    assert (repo / "out.txt").read_text() == "agent output\n"


def test_successful_commit_still_consumes_baseline(repo: Path):
    """One snapshot, one fire — the settled path still burns it."""
    assert phase_z._write_pre_fire_snapshot(repo, set(), subprocess.run)
    (repo / "out.txt").write_text("agent output\n")
    alerts: list[dict] = []

    out = _run(repo, alerts)

    assert out["committed"] is True
    assert not _snapshot_file(repo).exists()


def test_status_error_keeps_baseline(repo: Path):
    """A transient `git status` failure must not destroy the baseline either."""
    assert phase_z._write_pre_fire_snapshot(repo, set(), subprocess.run)

    def failing_runner(cmd, **kw):
        if "status" in cmd:
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: index locked")
        return subprocess.run(cmd, **kw)

    out = phase_z.run_phase_z(repo_root=repo, now_hhmm="07:07", runner=failing_runner,
                              alert_fn=lambda **k: {})

    assert out["reason"] == "status_error"
    assert _snapshot_file(repo).exists()


def test_ownership_unknown_is_terminal():
    """Pin 2: no retry can mint a baseline — retrying it is a livelock."""
    assert "ownership_unknown" in scheduler._PHASE_Z_TERMINAL_REASONS


def test_drain_gives_up_after_bounded_attempts(tmp_path: Path, monkeypatch):
    """Pin 3: attempts persist on the pending token; the cap releases it with ONE
    give-up alert instead of one alert per tick forever."""
    state_path = tmp_path / "dispatch_state.json"
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [{"cohort_id": "c1"}]
    sent: list[dict] = []
    monkeypatch.setattr(phase_z, "_default_alert", lambda **k: sent.append(k) or {})
    outcome = {"committed": False, "reason": "commit_nonzero", "commit_tail": "[pre-commit] BLOCKED"}

    results = [scheduler._phase_z_drain_exhausted(cohort_id="c1", outcome=outcome,
                                                  state_path=state_path)
               for _ in range(scheduler._PHASE_Z_MAX_DRAIN_ATTEMPTS)]

    assert results[:-1] == [False] * (scheduler._PHASE_Z_MAX_DRAIN_ATTEMPTS - 1)
    assert results[-1] is True
    assert len(sent) == 1, "give-up must alert exactly once"
    assert "BLOCKED" in sent[0]["body"]  # the gate's own words reach the boss
    pending = json.loads(state_path.read_text())["phase_z_pending"]
    assert pending[0]["drain_attempts"] == scheduler._PHASE_Z_MAX_DRAIN_ATTEMPTS


def test_silent_fallback_drain_giveup_reuses_internal_task_without_paging(
    tmp_path: Path,
    monkeypatch,
):
    state_path = tmp_path / "dispatch_state.json"
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [{"cohort_id": "c1"}]
    internal: list[dict] = []
    monkeypatch.setattr(
        phase_z,
        "_default_internal_alert",
        lambda **kwargs: internal.append(kwargs) or {"sent": False},
    )
    monkeypatch.setattr(
        phase_z,
        "_default_alert",
        lambda **kwargs: pytest.fail("internal gate retry must not page owner"),
    )
    outcome = {
        "committed": False,
        "reason": "commit_nonzero",
        "commit_tail": "[silent-fallback-audit] new=1",
        "internal_alert_key": "silent_fallback_new",
    }

    for _ in range(scheduler._PHASE_Z_MAX_DRAIN_ATTEMPTS):
        scheduler._phase_z_drain_exhausted(
            cohort_id="c1",
            outcome=outcome,
            state_path=state_path,
        )

    assert len(internal) == 1
    assert internal[0]["alert_key"] == "silent_fallback_new"


def test_alert_titles_carry_no_time_varying_tokens():
    """Pin 4 (2026-07-13 22:00 incident): alert dedup keys on hash(level+title),
    so a title that interpolates the fire time (or a per-tick counter like the
    foreign-file streak) mints a fresh dedup key every minute — the 24h window
    never matches and the boss gets one alert per tick. Timestamps and counters
    belong in the body."""
    import re

    src = Path(phase_z.__file__).read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in src.splitlines()
        if re.search(r'title\s*=\s*f?"', line)
        and re.search(r"\{hhmm\}|\{now|\{.*strftime|\{worst_streak\}", line)
    ]
    assert not offenders, f"time-varying token in alert title breaks dedup: {offenders}"
