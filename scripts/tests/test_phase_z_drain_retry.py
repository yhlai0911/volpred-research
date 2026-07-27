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
    _git(r.parent, "init", "-q", "-b", "main", str(r))
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


def _failed_closeout_file(repo: Path) -> Path:
    return repo / ".git" / phase_z._FAILED_CLOSEOUT_BASENAME


def _run(repo: Path, alerts: list[dict]) -> dict:
    """run_phase_z reading the REAL on-disk snapshot (pre_fire_dirty not injected)."""
    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="07:07",
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: alerts.append(k) or {},
    )


def _pin_legacy_closeout(repo: Path, *paths: str) -> None:
    """Materialize the finite compatibility state without reviving auto-claim."""
    assert phase_z._ensure_failed_closeout(
        repo,
        owned=list(paths),
        reason="commit_nonzero",
        commit_tail="[pre-commit] BLOCKED — legacy fixture",
        receipt={"subject": "legacy rejected fire", "body": "", "task_id": ""},
        runner=subprocess.run,
    )


def test_recovery_mode_flag_alone_cannot_authorize_nonmachine_bytes(repo: Path):
    """Only recover_failed_closeout's pinned-byte capability may use the bridge."""
    (repo / "out.txt").write_text("fresh canonical edit\n")

    outcome = phase_z.run_phase_z(
        repo_root=repo,
        now_hhmm="07:07",
        pre_fire_dirty=set(),
        recovery_mode=True,
        commit_receipt_override={
            "subject": "forged recovery metadata",
            "body": "",
            "task_id": "",
        },
        alert_fn=lambda **_kwargs: {},
    )

    assert outcome["committed"] is False
    assert outcome["reason"] == "nothing_owned"
    assert outcome["isolation_residue"] == ["out.txt"]
    assert _git(repo, "log", "-1", "--format=%s").strip() == "seed"


def test_blocked_commit_keeps_baseline_and_never_degrades(repo: Path):
    """Pin 1: the incident's exact shape. Commit blocked by a pre-commit gate →
    the snapshot survives, so a retry is still `commit_nonzero` (ownership
    intact), NOT `ownership_unknown`. Before the fix the second run degraded."""
    assert phase_z._write_pre_fire_snapshot(repo, set(), subprocess.run)
    state_path = repo / "storage" / "ops" / "out.txt"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("machine output\n")
    _install_blocking_hook(repo)
    alerts: list[dict] = []

    first = _run(repo, alerts)
    assert first["reason"] == "commit_nonzero"
    assert "BLOCKED" in first["commit_tail"]  # the actionable fact travels with the outcome
    assert _snapshot_file(repo).exists(), "failed commit must not consume the baseline"
    assert not _failed_closeout_file(repo).exists(), (
        "hot machine state retries under the next baseline; it must never be hash-pinned"
    )

    second = _run(repo, alerts)
    assert second["reason"] == "commit_nonzero", (
        f"retry degraded to {second['reason']!r} — baseline was lost")
    assert not any("沒有 fire 起始基線" in a.get("title", "") for a in alerts)


def test_hash_pinned_closeout_recovers_after_gate_is_fixed(repo: Path):
    (repo / "out.txt").write_text("agent output\n")
    _pin_legacy_closeout(repo, "out.txt")

    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    recovered = phase_z.recover_failed_closeout(
        repo_root=repo,
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: {},
    )

    assert recovered["committed"] is True
    assert "out.txt" in _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert not _failed_closeout_file(repo).exists()
    assert not _git(repo, "status", "--porcelain").strip()


def test_hash_pinned_closeout_rejects_index_blob_swap_race(repo: Path):
    target = repo / "out.txt"
    target.write_text("authorized A\n")
    _pin_legacy_closeout(repo, "out.txt")
    head_before = _git(repo, "rev-parse", "HEAD").strip()
    swapped = False

    def racing_runner(argv, **kwargs):
        nonlocal swapped
        if len(argv) > 3 and argv[3] == "add" and not swapped:
            swapped = True
            target.write_text("unauthorized B\n")
            result = subprocess.run(argv, **kwargs)
            target.write_text("authorized A\n")
            return result
        return subprocess.run(argv, **kwargs)

    recovered = phase_z.recover_failed_closeout(
        repo_root=repo,
        runner=racing_runner,
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **_kwargs: {},
    )

    assert swapped is True
    assert recovered["committed"] is False
    assert recovered["reason"] == "closeout_identity_error"
    assert recovered["identity_mismatches"] == ["out.txt"]
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before
    assert target.read_text() == "authorized A\n"
    assert _failed_closeout_file(repo).exists()


def test_hash_pinned_closeout_rejects_byte_identical_chmod_drift(repo: Path):
    target = repo / "tool.sh"
    target.write_text("#!/bin/sh\nexit 0\n")
    target.chmod(0o644)
    _git(repo, "add", "tool.sh")
    _git(repo, "commit", "-qm", "track non-executable tool")

    target.write_text("#!/bin/sh\necho authorized\n")
    _pin_legacy_closeout(repo, "tool.sh")
    target.chmod(0o755)  # same receipt bytes, unauthorized mode mutation
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    recovered = phase_z.recover_failed_closeout(
        repo_root=repo,
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **_kwargs: {},
    )

    assert recovered["committed"] is False
    assert recovered["reason"] == "closeout_identity_error"
    assert recovered["identity_mismatches"] == ["tool.sh"]
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert _failed_closeout_file(repo).exists()


def test_hash_pinned_closeout_refuses_later_edits(repo: Path):
    """A later session's edits are never committed under the failed fire's name.

    The safety property is unchanged from the original pin: HEAD does not move
    and the edited bytes are left exactly as the later session wrote them. What
    changed (2026-07-18) is the AFTERMATH — the stale claim is released instead
    of re-raising a CRITICAL every fire with no way to stop. See
    test_phase_z_untracked_closeout.py for the self-heal pins.
    """
    (repo / "out.txt").write_text("agent output\n")
    _pin_legacy_closeout(repo, "out.txt")
    before_head = _git(repo, "rev-parse", "HEAD").strip()

    (repo / "out.txt").write_text("edited by a later session\n")
    alerts: list[dict] = []
    recovered = phase_z.recover_failed_closeout(
        repo_root=repo,
        alert_fn=lambda **k: alerts.append(k) or {},
    )

    assert recovered["reason"] == "released"
    assert recovered["released"] == ["out.txt"]
    assert _git(repo, "rev-parse", "HEAD").strip() == before_head
    assert (repo / "out.txt").read_text() == "edited by a later session\n"
    assert alerts and alerts[0]["level"] == "warn"


def test_landed_closeout_clears_silently_despite_hot_state_drift(repo: Path):
    """The 2026-07-17 alert loop: a receipt whose paths later fires already
    committed must clear, not scream. The pinned set mixes the fire's own output
    with a hot shared state file that every later fire rewrites — drift there is
    normal progress once a later commit has carried the content forward."""
    (repo / "out.txt").write_text("agent output\n")
    (repo / "work_log.json").write_text('[{"fire": 1}]\n')
    _pin_legacy_closeout(repo, "out.txt", "work_log.json")

    # A later fire commits both paths — carrying fire 1's log line along with its
    # own — and a third is mid-append, so work_log.json is dirty again and no
    # longer matches the bytes pinned at the failure.
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    (repo / "work_log.json").write_text('[{"fire": 1}, {"fire": 2}]\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "later fire committed the pinned work")
    (repo / "work_log.json").write_text('[{"fire": 1}, {"fire": 2}, {"fire": 3}]\n')

    alerts: list[dict] = []
    recovered = phase_z.recover_failed_closeout(
        repo_root=repo,
        alert_fn=lambda **k: alerts.append(k) or {},
    )

    assert recovered["reason"] == "already_closed"
    assert not alerts, f"finished receipt must not page anyone: {alerts}"
    assert not _failed_closeout_file(repo).exists(), "a finished receipt must not survive to re-alert"


def test_failed_closeout_accumulates_distinct_later_batches(repo: Path):
    (repo / "first.txt").write_text("first\n")
    _pin_legacy_closeout(repo, "first.txt")

    # A second pre-retirement receipt appends instead of erasing the first.
    (repo / "second.txt").write_text("second\n")
    _pin_legacy_closeout(repo, "second.txt")

    payload = json.loads(_failed_closeout_file(repo).read_text())
    assert {entry["path"] for entry in payload["paths"]} == {"first.txt", "second.txt"}
    assert len(payload["receipts"]) == 2


def test_machine_state_is_never_pinned_into_failed_closeout(repo: Path):
    """Hot daemon-written state must not enter the receipt (assign_33e4c59f).

    A dozen writers churn these files hourly, so a pinned fingerprint is
    guaranteed to drift and the claim could only ever end in a "released" warn —
    the recurring 放棄認領 orphan alert. The churn lane re-adopts them under the
    next fire's own baseline; only real work is worth deferring.
    """
    (repo / "out.txt").write_text("agent output\n")
    wl = repo / "storage" / "work_log.json"
    wl.parent.mkdir(parents=True)
    wl.write_text("[]\n")
    assert phase_z._ensure_failed_closeout(
        repo,
        owned=["out.txt", "storage/work_log.json"],
        reason="commit_nonzero",
        commit_tail="blocked",
        receipt=None,
        runner=subprocess.run,
    )

    payload = json.loads(_failed_closeout_file(repo).read_text())
    pinned = [entry["path"] for entry in payload["paths"]]
    assert "out.txt" in pinned
    assert "storage/work_log.json" not in pinned


def test_pre_invariant_machine_state_claims_release_silently(repo: Path):
    """Receipts written before the no-pin invariant still hold hot-state claims.

    Recovery must drain them without the 放棄認領 warn — their drift is by
    design, not an incident — while leaving the working bytes untouched and the
    real work fully recoverable.
    """
    (repo / "out.txt").write_text("agent output\n")
    _pin_legacy_closeout(repo, "out.txt")

    wl = repo / "storage" / "work_log.json"
    wl.parent.mkdir(parents=True)
    wl.write_text("[]\n")
    dest = _failed_closeout_file(repo)
    payload = json.loads(dest.read_text())
    payload["paths"].append(
        # valid fingerprint shape, guaranteed to mismatch the live file — the
        # exact state a pre-invariant receipt is in after an hour of churn
        {"path": "storage/work_log.json", "fingerprint": {"kind": "missing"}})
    dest.write_text(json.dumps(payload))

    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    alerts: list[dict] = []
    recovered = phase_z.recover_failed_closeout(
        repo_root=repo,
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: alerts.append(k) or {},
    )

    assert recovered["committed"] is True
    assert not any("放棄" in a.get("title", "") for a in alerts), alerts
    assert wl.read_text() == "[]\n", "release must not touch working bytes"
    assert not _failed_closeout_file(repo).exists()


def test_blocked_candidate_preserves_head_index_and_working_bytes(repo: Path):
    """Alternate-index transaction: a hook veto cannot leave half the fire staged."""
    (repo / "foreign.txt").write_text("another writer\n")
    _git(repo, "add", "foreign.txt")
    before_tree = _git(repo, "write-tree").strip()
    before_head = _git(repo, "rev-parse", "HEAD").strip()
    assert phase_z._write_pre_fire_snapshot(repo, {"foreign.txt"}, subprocess.run)
    out_path = repo / "storage" / "ops" / "out.txt"
    out_path.parent.mkdir(parents=True)
    out_path.write_text("machine output\n")
    _install_blocking_hook(repo)

    out = _run(repo, [])

    assert out["reason"] == "commit_nonzero"
    assert out["rolled_back"] is True
    assert _git(repo, "rev-parse", "HEAD").strip() == before_head
    assert _git(repo, "write-tree").strip() == before_tree
    assert out_path.read_text() == "machine output\n"
    assert (repo / "foreign.txt").read_text() == "another writer\n"


def test_blocking_hook_side_effect_stays_in_disposable_candidate(repo: Path):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\necho touched > hook-side-effect.txt\necho BLOCKED >&2\nexit 1\n"
    )
    hook.chmod(0o755)
    assert phase_z._write_pre_fire_snapshot(repo, set(), subprocess.run)
    out_path = repo / "storage" / "ops" / "out.txt"
    out_path.parent.mkdir(parents=True)
    out_path.write_text("machine output\n")

    out = _run(repo, [])

    assert out["reason"] == "commit_nonzero"
    assert not (repo / "hook-side-effect.txt").exists()
    assert out_path.read_text() == "machine output\n"


def test_successful_commit_still_consumes_baseline(repo: Path):
    """One snapshot, one fire — the settled path still burns it."""
    assert phase_z._write_pre_fire_snapshot(repo, set(), subprocess.run)
    out_path = repo / "storage" / "ops" / "out.txt"
    out_path.parent.mkdir(parents=True)
    out_path.write_text("machine output\n")
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
