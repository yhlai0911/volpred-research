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
                   if a[0] == "critical" and "連續多班沒人收" in a[1]]
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
    assert [a for a in alerts if a[0] == "critical" and "連續多班沒人收" in a[1]]


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
    cleaned up. Preserved-but-not-tidied must not read as resolved."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)

    verdict = fi.incident_closeable(repo, [THEIRS])

    assert verdict["paths"][THEIRS]["quarantined"] is True
    assert verdict["paths"][THEIRS]["still_dirty_in_main"] is True
    assert verdict["closeable"] is False
    assert any("仍髒在 main checkout" in b for b in verdict["blockers"])


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
    """The CLI-shaped entry point the incident body tells the reader to run."""
    _write(repo, THEIRS, "stuck\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL)

    results = fi.check_open_incidents(repo)

    assert len(results) == 1
    assert results[0]["fingerprint"] == fi.fingerprint([THEIRS])
    assert results[0]["closeable"] is False
    assert results[0]["task_id"] == _incidents(repo)[0]["id"]


# ── fingerprint ──────────────────────────────────────────────────────────────

def test_fingerprint_is_order_insensitive_and_content_addressed():
    """Dedup keys off the path SET. Order or duplicate listings must not mint a
    second incident; a genuinely different set must not collide with the first."""
    assert fi.fingerprint(["b", "a"]) == fi.fingerprint(["a", "b", "a"])
    assert fi.fingerprint(["a", "b"]) != fi.fingerprint(["a", "b", "c"])
    assert fi.fingerprint([]) != fi.fingerprint(["a"])
