"""D3: a stuck foreign path must change what the scheduler DOES, not just what it logs.

Background — `docs/governance/2026-07/phase_z_ownership_external_review.md`, verbatim
conclusion: **「若 CRITICAL 不會改變 scheduler 行為，它只是紅色日誌。」** PHASE-Z sent
the CRITICAL correctly for 78 consecutive fires, with a textbook 3/6/12/24 backoff,
and produced zero actions — because a notification has no owner, no deadline, no
effect on dispatch, and no consequence for staying unresolved.

So the alert is now *subsumed* by a persistent incident in the canonical queue, and
that incident de-rates the slot cap until it closes. Each test below pins one way
this could be implemented so it looks right in a log and still changes nothing:

1. N fires on one stuck set must produce ONE incident — a per-fire incident is the
   per-fire CRITICAL wearing a task id, and the queue would grow 78 rows deep;
2. the CRITICAL must fire exactly once — keeping BOTH channels alive is stacking, and
   two ignorable reminders for one condition are worse than one;
3. an open incident must actually lower `dispatch_slot_budget.budget()["cap"]`, with
   a reason a human can act on — a de-rate nobody can attribute is a new mystery;
4. the close condition must be mechanical and universally quantified — "most of the
   files are handled" is how the 78 fires were rationalised each hour.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z
from volpred.ops import foreign_incident as fi

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import dispatch_slot_budget as sb  # noqa: E402

THEIRS = "scripts/somebody_elses_edit.py"
QUEUE = "storage/next_tasks.json"


# ── harness (mirrors test_phase_z_quarantine_checkpoint.py: real git, real fires) ──

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
    )


def _no_tests(*_a, **_k):
    return subprocess.CompletedProcess(args=[], returncode=5, stdout="", stderr="")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@volpred.local")
    _git(tmp_path, "config", "user.name", "phase-z-incident-test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    # The canonical queue exists in every real checkout; the incident is written
    # through it, so a repo without one is not the situation under test.
    (tmp_path / "storage").mkdir()
    (tmp_path / QUEUE).write_text("[]\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "seed")
    return tmp_path


@pytest.fixture(autouse=True)
def isolate_slot_occupancy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let slot-budget assertions inspect the developer's live checkout."""
    worktrees = tmp_path / "slot-budget-worktrees"
    agents = tmp_path / "slot-budget-agents"
    worktrees.mkdir(exist_ok=True)
    agents.mkdir(exist_ok=True)
    monkeypatch.setattr(sb, "WORKTREES_DIR", worktrees)
    monkeypatch.setattr(sb, "AGENTS_DIR", agents)


def _fire(repo: Path, alerts: list | None = None) -> dict:
    def _alert(*, level, title, body):
        if alerts is not None:
            alerts.append((level, title, body))
        return {"sent": True}

    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="03:00", test_runner=_no_tests, alert_fn=_alert,
    )


def _fires(repo: Path, n: int, alerts: list | None = None) -> dict:
    outcome: dict = {}
    for _ in range(n):
        phase_z.run_pre_fire_guard(repo_root=repo)
        outcome = _fire(repo, alerts=alerts)
    return outcome


def _write(root: Path, rel: str, text: str) -> None:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def _stale(root: Path, rel: str, age_s: float | None = None) -> None:
    """Age a path past the live-authoring grace window.

    Touches mtime only — content and git status are untouched, because the thing
    being simulated is *nobody coming back to it*, not a different edit.
    """
    age_s = fi.LIVE_AUTHORING_GRACE_S * 2 if age_s is None else age_s
    target = (root / rel).stat().st_mtime - age_s
    os.utime(root / rel, (target, target))


def _incidents(repo: Path) -> list[dict]:
    tasks = json.loads((repo / QUEUE).read_text(encoding="utf-8"))
    return [t for t in tasks if isinstance(t, dict) and fi._is_incident(t)]


# ── 1. one stuck set, one incident ───────────────────────────────────────────

def test_the_same_stuck_paths_produce_exactly_one_incident_across_many_fires(repo: Path):
    """The 2..N-th fire must UPDATE, never append. A row per fire is the hourly
    CRITICAL with extra steps, and it buries the one row that matters."""
    _write(repo, THEIRS, "half-finished edit\n")

    fires = phase_z._FOREIGN_STREAK_CRITICAL + 6
    outcome = _fires(repo, fires)

    incidents = _incidents(repo)
    assert len(incidents) == 1, [t["id"] for t in incidents]
    payload = incidents[0]["payload"]
    assert payload["paths"] == [THEIRS]
    assert payload["fingerprint"] == fi.fingerprint([THEIRS])
    # Observed once per fire from the threshold onward, and every one of those
    # observations landed on the SAME row.
    assert payload["fires"] == fires - phase_z._FOREIGN_STREAK_CRITICAL + 1
    assert outcome["incident"]["created"] is False
    assert outcome["incident"]["updated"] is True
    assert outcome["incident"]["task_id"] == incidents[0]["id"]


def test_the_incident_tracks_the_streak_and_the_quarantine_ref_as_it_updates(repo: Path):
    """Updating must carry the new facts, or the single row goes stale and the
    reader has to go back to reading logs — which is the state we started in."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL + 3)

    payload = _incidents(repo)[0]["payload"]
    assert payload["streaks"][THEIRS] == phase_z._FOREIGN_STREAK_CRITICAL + 3
    assert payload["quarantine_refs"], "the retrievable bytes must be named on the row"
    assert all(r.startswith(fi.QUARANTINE_REF_PREFIX) for r in payload["quarantine_refs"])
    assert payload["last_seen_at"] >= payload["first_seen_at"]


def test_a_widened_stuck_set_supersedes_the_row_it_subsumes(repo: Path):
    """One more stuck file is a different fingerprint, so it is a new row — but
    leaving the old one open too would accumulate permanently-uncloseable rows
    until a de-rate is just the background state again."""
    _write(repo, THEIRS, "first\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    first = _incidents(repo)[0]

    _write(repo, "scripts/another_edit.py", "second\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)

    rows = {t["id"]: t for t in _incidents(repo)}
    assert len(rows) == 2
    assert rows[first["id"]]["status"] == "superseded"
    newer = next(t for t in rows.values() if t["id"] != first["id"])
    assert rows[first["id"]]["superseded_by"] == newer["id"]
    assert set(newer["payload"]["paths"]) == {THEIRS, "scripts/another_edit.py"}
    # Exactly one signal reaches the scheduler.
    assert [t["id"] for t in fi.open_incidents(repo / QUEUE)] == [newer["id"]]


# ── 2. the alert is subsumed, not stacked ────────────────────────────────────

def test_the_critical_is_sent_once_and_not_re_sent_while_the_incident_is_open(repo: Path):
    """The old curve re-paged at 3/6/12/24. With an owner, a deadline and a cost
    on the row, re-paging is a second reminder channel for one condition."""
    _write(repo, THEIRS, "stuck\n")
    alerts: list = []

    _fires(repo, 30, alerts=alerts)  # well past 3, 6, 12 and 24

    stuck_pages = [a for a in alerts
                   if a[0] == "critical" and "達處置門檻" in a[1]]
    assert len(stuck_pages) == 1, [a[1] for a in stuck_pages]
    body = stuck_pages[0][2]
    incident = _incidents(repo)[0]
    # And that single page hands over to the incident rather than ending at
    # "somebody should look at this".
    assert incident["id"] in body
    assert "降載" in body


def test_a_page_still_goes_out_when_the_incident_cannot_be_opened(repo: Path):
    """No incident means no owner and no de-rate, so silence would be strictly
    worse than the old noise. This is the one path allowed to keep the backoff."""
    (repo / QUEUE).unlink()
    _write(repo, THEIRS, "stuck\n")
    alerts: list = []

    outcome = _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL, alerts=alerts)

    assert outcome["incident"]["reason"] == "no_queue"
    assert [a for a in alerts if a[0] == "critical" and "達處置門檻" in a[1]]


# ── 3. admission control: the incident changes the cap ───────────────────────

def test_an_open_incident_de_rates_the_slot_cap_with_an_attributable_reason(tmp_path: Path):
    """`dispatch_slot_budget` is the single enforcement owner. The de-rate has to
    name the incident: a cap that silently drops is a new unexplained outage."""
    tasks = tmp_path / "next_tasks.json"
    state = tmp_path / "dispatch_state.json"
    state.write_text(json.dumps({"auth_blocked": False}), encoding="utf-8")
    tasks.write_text("[]\n", encoding="utf-8")

    baseline = sb.budget(tasks_path=tasks, state_path=state)
    assert baseline["cap"] == sb.BASE_CAP
    assert baseline["open_incident"] is None

    fi.upsert_incident(paths=[THEIRS, "b.py"], streaks={THEIRS: 9, "b.py": 4},
                       tasks_path=tasks)
    derated = sb.budget(tasks_path=tasks, state_path=state)

    assert derated["cap"] == sb.DERATE_CAP < baseline["cap"]
    row = json.loads(tasks.read_text())[0]
    assert row["id"] in derated["reason"]
    assert row["payload"]["fingerprint"] in derated["reason"]
    assert "de-rated" in derated["reason"]
    assert derated["open_incident"]["task_id"] == row["id"]
    assert derated["open_incident"]["paths"] == 2


def test_the_de_rate_outranks_the_p1_surge(tmp_path: Path):
    """A P1 backlog is not a reason to run MORE concurrent agents into a working
    tree whose ownership signal is already unreliable — that is how it got that
    way. Pinned because the ordering is the whole admission-control decision."""
    tasks = tmp_path / "next_tasks.json"
    state = tmp_path / "dispatch_state.json"
    state.write_text(json.dumps({"auth_blocked": False}), encoding="utf-8")
    tasks.write_text(json.dumps(
        [{"id": f"t{i}", "status": "pending", "priority": 1}
         for i in range(sb.P1_SURGE_AT + 2)]), encoding="utf-8")

    assert sb.budget(tasks_path=tasks, state_path=state)["cap"] == sb.SURGE_CAP

    fi.upsert_incident(paths=[THEIRS], streaks={THEIRS: 5}, tasks_path=tasks)

    assert sb.budget(tasks_path=tasks, state_path=state)["cap"] == sb.DERATE_CAP


def test_a_closed_incident_stops_de_rating(tmp_path: Path):
    """The de-rate must have an off switch that is the incident's own status —
    otherwise closing it changes nothing and it becomes another red log."""
    tasks = tmp_path / "next_tasks.json"
    state = tmp_path / "dispatch_state.json"
    state.write_text(json.dumps({"auth_blocked": False}), encoding="utf-8")
    tasks.write_text("[]\n", encoding="utf-8")
    fi.upsert_incident(paths=[THEIRS], streaks={THEIRS: 5}, tasks_path=tasks)
    assert sb.budget(tasks_path=tasks, state_path=state)["cap"] == sb.DERATE_CAP

    rows = json.loads(tasks.read_text())
    rows[0]["status"] = "succeeded"
    tasks.write_text(json.dumps(rows), encoding="utf-8")

    assert sb.budget(tasks_path=tasks, state_path=state)["cap"] == sb.BASE_CAP


@pytest.mark.parametrize("status", ["blocked", "blocked_on_user"])
def test_blocking_an_incident_does_not_lift_the_de_rate(tmp_path: Path, status: str):
    """`blocked` is a state, not a resolution: the files are still stuck. If it
    lifted the cap it would be a mute button on the only consequence."""
    tasks = tmp_path / "next_tasks.json"
    state = tmp_path / "dispatch_state.json"
    state.write_text(json.dumps({"auth_blocked": False}), encoding="utf-8")
    tasks.write_text("[]\n", encoding="utf-8")
    fi.upsert_incident(paths=[THEIRS], streaks={THEIRS: 5}, tasks_path=tasks)

    rows = json.loads(tasks.read_text())
    rows[0]["status"] = status
    tasks.write_text(json.dumps(rows), encoding="utf-8")

    assert sb.budget(tasks_path=tasks, state_path=state)["cap"] == sb.DERATE_CAP


# ── 4. the close condition is mechanical ─────────────────────────────────────

def test_a_still_dirty_path_cannot_close_the_incident_even_though_it_is_quarantined(repo: Path):
    """This is exactly the 78-fire state: the bytes were preserved and NOTHING was
    cleaned up. Preserved-but-not-tidied must not read as resolved.

    The file is aged past the grace window on purpose — 78 fires is 78 hours of
    nobody touching it, which is the thing that makes it an unowned leftover. The
    fixture used to write it a millisecond earlier and still assert this, which
    quietly conflated 'dirty' with 'abandoned'; those are different conditions and
    `_stale` is where the difference now lives."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    _stale(repo, THEIRS)

    verdict = fi.incident_closeable(repo, [THEIRS])

    assert verdict["paths"][THEIRS]["quarantined"] is True
    assert verdict["paths"][THEIRS]["still_dirty_in_main"] is True
    assert verdict["paths"][THEIRS]["live_authoring"] is False
    assert verdict["closeable"] is False
    assert any("仍髒在 main checkout" in b for b in verdict["blockers"])


# ── 5. the grace exit: live authoring is not an unowned leftover ─────────────

def test_a_covered_path_someone_is_still_editing_stops_the_derate(repo: Path):
    """2026-07-21: `scripts/detect_price_split_breaks.py` was quarantined, edited two
    hours earlier, and was the ONLY blocker in the pool — so it pinned every fire at
    DERATE_CAP. There was no way out: `commit` and `delete` both belong to the author,
    `leave` records the decision but still blocks, and every save reset the clock.

    A gate whose exit condition an active author keeps resetting is a deadlock, not a
    forcing function. So the grace lifts the *de-rate* — the thing that was punishing
    the wrong person — while the incident stays open, because the file genuinely is
    still sitting in the checkout."""
    _write(repo, THEIRS, "still working on it\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)

    verdict = fi.incident_closeable(repo, [THEIRS])

    assert verdict["paths"][THEIRS]["live_authoring"] is True
    assert verdict["derates"] is False
    assert verdict["blockers"] == []
    assert any("活躍碼" in d for d in verdict["deferred"])
    # Not resolved — nothing was collected, so the incident must not close.
    assert verdict["closeable"] is False


def test_first_fire_stamps_live_authoring_verdict_before_slot_admission(repo: Path):
    """The incident creator and the cap reader must agree on the *first* fire.

    The former ordering reconciled existing incidents and only then upserted the
    newly observed one.  Its payload therefore had no ``derates`` verdict until
    a later PHASE-Z pass.  ``dispatch_slot_budget`` correctly treats a missing
    verdict as unsafe, but that turned covered active work into a one-fire false
    de-rate.  Pin the real boundary: after the first incident-creating fire, the
    durable verdict must already match the live assessor before admission reads
    it.
    """
    _write(repo, THEIRS, "still working on it\n")

    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)

    incident = _incidents(repo)[0]
    assert incident["payload"]["derates"] is False
    assert sb.budget(
        tasks_path=repo / QUEUE,
        state_path=repo / "state.json",
    )["cap"] != sb.DERATE_CAP


def test_live_authoring_does_not_churn_the_incident_open_and_shut(repo: Path):
    """Letting the grace mark the incident closeable would close it every fire and
    re-open it the next, so one condition would mint a fresh row every hour — the
    exact per-fire-ticket failure this module's fingerprint dedup exists to prevent.
    The de-rate is what needs an exit; the incident row is what needs to persist."""
    _write(repo, THEIRS, "still working on it\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL + 3)

    assert len(_incidents(repo)) == 1
    assert fi.open_incidents(repo / QUEUE) != []
    # …and across all those fires the cap was never de-rated for live authoring.
    assert sb.budget(tasks_path=repo / QUEUE,
                     state_path=repo / "state.json")["cap"] != sb.DERATE_CAP


def test_the_grace_expires_so_abandoned_work_derates_again(repo: Path):
    """The exit must be self-expiring, or it is just a mute button. An author who
    walks away stops resetting the clock, and the path goes back to being what it
    now actually is: an unowned leftover that costs capacity."""
    _write(repo, THEIRS, "started and abandoned\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    _stale(repo, THEIRS, age_s=fi.LIVE_AUTHORING_GRACE_S + 60)

    verdict = fi.incident_closeable(repo, [THEIRS])

    assert verdict["paths"][THEIRS]["live_authoring"] is False
    assert verdict["derates"] is True
    assert verdict["closeable"] is False
    assert any("仍髒在 main checkout" in b for b in verdict["blockers"])


def test_grace_never_applies_to_a_path_whose_bytes_are_not_retrievable(repo: Path):
    """The safety premise of the whole exit is 'we can get these bytes back'. An
    uncovered path fails that premise, so being freshly edited buys it nothing —
    otherwise 'I am still working on it' would become a way to hold unbacked-up
    work hostage while the incident closes underneath it."""
    _write(repo, "scripts/never_quarantined.py", "brand new, nowhere else\n")

    verdict = fi.incident_closeable(repo, ["scripts/never_quarantined.py"])

    assert verdict["paths"]["scripts/never_quarantined.py"]["covered"] is False
    assert verdict["paths"]["scripts/never_quarantined.py"]["live_authoring"] is False
    assert verdict["closeable"] is False


def test_a_quarantined_path_cleared_from_the_checkout_closes(repo: Path):
    """Coverage plus a clean checkout is the whole postcondition — and it is
    checkable by a machine, which the old alert's exit condition never was."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    (repo / THEIRS).unlink()

    verdict = fi.incident_closeable(repo, [THEIRS])

    assert verdict["closeable"] is True, verdict["blockers"]
    assert verdict["paths"][THEIRS]["quarantined"] is True
    assert verdict["paths"][THEIRS]["still_dirty_in_main"] is False
    # The bytes really are retrievable — the claim the close condition rests on,
    # asserted against git rather than against our own bookkeeping.
    ref = json.loads((repo / QUEUE).read_text())[0]["payload"]["quarantine_refs"][0]
    assert _git(repo, "show", f"{ref}:{THEIRS}").stdout == "stuck\n"


def test_one_uncovered_path_is_enough_to_keep_it_open(repo: Path):
    """Universally quantified on purpose. 'All but one is handled' was available
    as a rationalisation every hour for 78 hours."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    (repo / THEIRS).unlink()

    verdict = fi.incident_closeable(repo, [THEIRS, "scripts/never_seen.py"])

    assert verdict["paths"][THEIRS]["covered"] is True
    assert verdict["paths"]["scripts/never_seen.py"]["covered"] is False
    assert verdict["closeable"] is False
    assert any("scripts/never_seen.py" in b for b in verdict["blockers"])


def test_a_live_workspace_covers_a_path_with_no_quarantine_ref(repo: Path):
    """The other accepted destination: the file is somebody's live workspace, so
    it is not an unowned leftover. Uses a real `git worktree`, because 'a
    directory exists' is the check that produced the zombie-slot incident."""
    workspace = repo.parent / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "side", str(workspace))
    _write(workspace, "scripts/moved_here.py", "carried over\n")

    verdict = fi.incident_closeable(repo, ["scripts/moved_here.py"])

    assert verdict["paths"]["scripts/moved_here.py"]["live_workspace"] == str(workspace)
    assert verdict["paths"]["scripts/moved_here.py"]["quarantined"] is False
    assert verdict["closeable"] is True, verdict["blockers"]


def test_check_open_incidents_reports_per_incident(repo: Path):
    """The CLI-shaped entry point the incident body tells the reader to run.

    Aged past grace so the assertion is about *reporting shape*, not about which
    side of the live-authoring line this fixture happens to land on."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    _stale(repo, THEIRS)

    results = fi.check_open_incidents(repo)

    assert len(results) == 1
    assert results[0]["fingerprint"] == fi.fingerprint([THEIRS])
    assert results[0]["closeable"] is False
    assert results[0]["task_id"] == _incidents(repo)[0]["id"]


# ── 6. the de-rate must be able to release itself ────────────────────────────

def test_a_satisfied_close_condition_actually_closes_the_incident(repo: Path):
    """`incident_closeable` had exactly zero callers outside tests and the CLI, so
    a green close condition changed nothing: on 2026-07-21 the only open incident
    was fully satisfied and every fire still ran at DERATE_CAP. A verdict nobody
    acts on is the 78-fire CRITICAL wearing a different data structure."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    (repo / THEIRS).unlink()  # collected — close condition now satisfied

    closed = fi.reconcile_incidents(repo)["closed"]

    assert [c["task_id"] for c in closed] == [_incidents(repo)[0]["id"]]
    assert _incidents(repo)[0]["status"] == "succeeded"
    assert fi.open_incidents(repo / QUEUE) == []
    # and the de-rate is genuinely gone, not just the row
    assert sb.budget(tasks_path=repo / QUEUE,
                     state_path=repo / "state.json")["cap"] != sb.DERATE_CAP


def test_an_unsatisfied_incident_is_left_open(repo: Path):
    """The actuator must not become a way to clear the queue. Still-stuck means
    still de-rated — that cost IS the mechanism."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    _stale(repo, THEIRS)

    assert fi.reconcile_incidents(repo)["closed"] == []
    assert _incidents(repo)[0]["status"] != "succeeded"
    assert _incidents(repo)[0]["payload"]["derates"] is True


def test_closing_records_the_evidence_it_relied_on(repo: Path):
    """'Why did this incident close?' must be answerable after the fact, or the
    next investigation starts from a status field and a shrug."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)
    (repo / THEIRS).unlink()

    fi.reconcile_incidents(repo)

    evidence = _incidents(repo)[0]["close_evidence"]
    assert evidence["closeable"] is True
    assert evidence["paths"][THEIRS]["quarantined"] is True
    assert evidence["blockers"] == []


# ── fingerprint ──────────────────────────────────────────────────────────────

def test_fingerprint_is_order_insensitive_and_content_addressed():
    """Dedup keys off the path SET. Order or duplicate listings must not mint a
    second incident; a genuinely different set must not collide with the first."""
    assert fi.fingerprint(["b", "a"]) == fi.fingerprint(["a", "b", "a"])
    assert fi.fingerprint(["a", "b"]) != fi.fingerprint(["a", "b", "c"])
    assert fi.fingerprint([]) != fi.fingerprint(["a"])


# --- liveness classification: 無主殘留 vs 未提交的活躍碼 (assign_eb78aedc) -----
#
# 2026-07-20: the closure checklist told the operator to preserve-then-delete 53
# "unclaimed stuck files" that were in fact the running incident system itself
# (foreign_incident.py, phase_z.py, the whole test group). quarantined /
# live_workspace / still_dirty_in_main take IDENTICAL values for dead residue and
# for uncommitted live code, so the instruction was wrong - and quietly so.

def _live_repo(repo: Path) -> Path:
    """A checkout shaped like the 2026-07-20 incident: live code + real junk."""
    (repo / "src" / "volpred" / "ops").mkdir(parents=True)
    (repo / "scripts" / "tests").mkdir(parents=True)
    # Untracked module - but a COMMITTED script imports it. That relationship is
    # visible without guessing anyone's intent; it is the strongest live signal.
    (repo / "src/volpred/ops/foreign_incident.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "scripts/dispatch_slot_budget.py").write_text(
        "from volpred.ops.foreign_incident import X\n", encoding="utf-8")
    (repo / "scripts/tests/test_scheduler_max_slots.py").write_text(
        "def test_x():\n    pass\n", encoding="utf-8")
    # Real junk from the same incident list.
    (repo / "storage").mkdir(exist_ok=True)
    (repo / "storage/work_log.json.bak_20260701").write_text("{}", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests/.!71268!test_junk.py").write_text("x\n", encoding="utf-8")
    # Only the importer is committed; the module it imports stays untracked, which
    # is exactly the shape that fooled the old checklist.
    _git(repo, "add", "scripts/dispatch_slot_budget.py")
    _git(repo, "commit", "-qm", "add importer")
    return repo


def test_untracked_module_imported_by_committed_code_is_live(repo: Path):
    got = fi.classify_path_liveness(_live_repo(repo), [
        "src/volpred/ops/foreign_incident.py",
    ])["src/volpred/ops/foreign_incident.py"]
    assert got["liveness"] == fi.LIVENESS_LIVE
    assert got["referenced_by"] == "scripts/dispatch_slot_budget.py"
    assert got["liveness_evidence"], "a live verdict with no evidence is a guess"


def test_test_files_are_live_even_though_nothing_imports_them(repo: Path):
    """The 53-path list swept up the whole test group; nothing imports a test."""
    got = fi.classify_path_liveness(_live_repo(repo), [
        "scripts/tests/test_scheduler_max_slots.py",
    ])["scripts/tests/test_scheduler_max_slots.py"]
    assert got["liveness"] == fi.LIVENESS_LIVE


def test_backup_and_editor_junk_stay_dead(repo: Path):
    got = fi.classify_path_liveness(_live_repo(repo), [
        "storage/work_log.json.bak_20260701",
        "tests/.!71268!test_junk.py",
    ])
    assert {v["liveness"] for v in got.values()} == {fi.LIVENESS_DEAD}, (
        "if junk classifies as live the classifier is not classifying"
    )


def test_mention_in_docs_or_queue_is_not_liveness(repo: Path):
    """A filename written into a doc or an old task description is not usage.

    Without this the classifier would almost never say dead - every stuck file has
    been named in some incident description by the time anyone looks at it.
    """
    root = _live_repo(repo)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/plan.md").write_text("we should fix scripts/ghost.py\n", encoding="utf-8")
    (root / QUEUE).write_text(
        json.dumps([{"id": "t1", "description": "scripts/ghost.py stuck"}]), encoding="utf-8")
    (root / "scripts/ghost.py").write_text("pass\n", encoding="utf-8")
    _git(root, "add", "docs/plan.md", QUEUE)
    _git(root, "commit", "-qm", "mention only")

    got = fi.classify_path_liveness(root, ["scripts/ghost.py"])["scripts/ghost.py"]
    assert got["liveness"] == fi.LIVENESS_DEAD


def test_live_code_changes_the_instruction_but_not_the_verdict(repo: Path):
    """Liveness must not make a dirty incident closeable - adoption is a decision.

    The bytes are still sitting uncommitted in main, so the incident is not
    resolved; what changes is that the operator is told to adopt rather than to
    preserve-then-delete.
    """
    root = _live_repo(repo)
    rel = "src/volpred/ops/foreign_incident.py"
    # Age it well past the authoring grace. This is the whole point: the real
    # foreign_incident.py survived untracked for 78 shifts, so its mtime was
    # ancient while it ran every hour. mtime answers "did someone just touch
    # this", never "is this alive".
    _stale(root, rel)

    def _runner(cmd, **kw):
        # Pretend the path is quarantine-covered so `covered` is True and the only
        # remaining question is what to tell the operator about the dirty path.
        if cmd[3:5] == ["for-each-ref", "--format=%(refname)"]:
            return subprocess.CompletedProcess(cmd, 0, "refs/quarantine/x\n", "")
        if cmd[3] == "ls-tree":
            return subprocess.CompletedProcess(cmd, 0, f"{rel}\n", "")
        kw.pop("capture_output", None)
        kw.pop("text", None)
        kw.pop("check", None)
        return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)

    got = fi.incident_closeable(root, [rel], runner=_runner)

    assert got["closeable"] is False, "dirty is dirty; liveness does not close it"
    assert got["paths"][rel]["liveness"] == fi.LIVENESS_LIVE
    blocker = "".join(got["blockers"])
    assert "不要清除" in blocker and "收養" in blocker, (
        "a live path must not be handed the preserve-then-delete instruction"
    )
