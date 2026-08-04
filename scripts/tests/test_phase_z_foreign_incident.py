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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z
from scripts.task_pool_claim import _dispatch_execution_contract
from volpred.ops import alerts as ops_alerts
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

def test_a_changed_stuck_set_does_not_repage_while_the_incident_family_is_open(
    repo: Path,
):
    """Path-set churn is an incident update, not a new reason to page.

    Production evidence (2026-07-23..29) showed one stable alert title sent six
    times at occurrences 1/6/9/13/26/44.  The central dedupe was working; PHASE-Z
    kept presenting each wider path set as a newly created incident.  One open
    incident family already supplies the owner, close condition, and scheduler
    consequence, so another page only stacks notification channels.
    """
    alerts: list = []
    _write(repo, THEIRS, "first\n")
    _fires(repo, phase_z._FOREIGN_STREAK_CRITICAL, alerts=alerts)

    _write(repo, "scripts/another_edit.py", "second\n")
    created_outcome = _fires(
        repo, phase_z._FOREIGN_STREAK_CRITICAL, alerts=alerts,
    )
    updated_outcome = _fires(repo, 1, alerts=alerts)

    stuck_pages = [
        alert
        for alert in alerts
        if alert[0] == "critical" and "達處置門檻" in alert[1]
    ]
    assert len(stuck_pages) == 1, [alert[1] for alert in stuck_pages]
    assert created_outcome["incident"]["created"] is True
    assert created_outcome["incident"]["page_required"] is False
    assert updated_outcome["incident"]["updated"] is True
    assert updated_outcome["incident"]["page_required"] is False


def test_transport_dedup_key_is_bound_to_the_incident_episode():
    """Disjoint families and terminal recurrences must not consume each other."""
    a_e1 = {
        "task_id": "phase-z-foreign-aaa-e1",
        "page_transport_id": "phase-z-family-a-e1",
    }
    a_successor = {
        "task_id": "phase-z-foreign-aaabbb-e1",
        "page_transport_id": "phase-z-family-a-e1",
    }
    a_e2 = {
        "task_id": "phase-z-foreign-aaa-e2",
        "page_transport_id": "phase-z-family-a-e2",
    }
    b_e1 = {
        "task_id": "phase-z-foreign-bbb-e1",
        "page_transport_id": "phase-z-family-b-e1",
    }

    titles = [
        phase_z._stuck_incident_alert_title(incident)
        for incident in (a_e1, a_successor, a_e2, b_e1)
    ]
    keys = [ops_alerts._alert_key("critical", title) for title in titles]

    assert keys[0] == keys[1], "overlapping successor must reuse root transport id"
    assert len({keys[0], keys[2], keys[3]}) == 3
    assert a_e1["page_transport_id"] in titles[0]
    assert a_successor["task_id"] not in titles[1]


def test_a_disjoint_stuck_set_is_a_new_notification_episode(tmp_path: Path):
    """An unrelated new root cause must not be silenced by an old open row."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")

    first = fi.upsert_incident(paths=["a.py"], tasks_path=tasks)
    second = fi.upsert_incident(paths=["b.py"], tasks_path=tasks)

    assert first["page_required"] is True
    assert second["page_required"] is True


def test_concurrent_overlapping_creators_claim_exactly_one_family_page(
    tmp_path: Path,
):
    """The persisted LOCK_EX claim, not a pre-append snapshot, elects the pager."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")

    def create(paths: list[str]) -> dict:
        return fi.upsert_incident(paths=paths, tasks_path=tasks)

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(create, [["a.py"], ["a.py", "b.py"]]))

    assert sum(bool(receipt["page_required"]) for receipt in receipts) == 1
    open_rows = fi.open_incidents(tasks)
    assert sum(
        bool((row.get("payload") or {}).get("family_page_leases"))
        for row in open_rows
    ) == 1


def test_an_ordinary_semantic_duplicate_cannot_swallow_the_incident(
    tmp_path: Path,
):
    """Incident identity outranks the generic task semantic matcher."""
    tasks = tmp_path / "next_tasks.json"
    paths = ["a.py"]
    fp = fi.fingerprint(paths)
    tasks.write_text(
        json.dumps(
            [
                {
                    "id": "ordinary-task",
                    "title": (
                        f"PHASE-Z 卡住檔案 incident（{fp}）"
                        "— 未關則 scheduler 降載"
                    ),
                    "description": "ordinary task with deliberately colliding text",
                    "task_type": "platform_ops",
                    "priority": 2,
                    "status": "pending",
                    "source": "agent",
                    "created_at": "2026-07-30T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )

    receipt = fi.upsert_incident(paths=paths, tasks_path=tasks)

    assert receipt["created"] is True
    assert receipt["page_required"] is True
    assert receipt["task_id"] == f"phase-z-foreign-{fp}-e1"
    assert len(fi.open_incidents(tasks)) == 1


def test_new_incident_is_dispatchable_with_an_observe_only_contract(
    tmp_path: Path,
):
    """A PHASE-Z incident must reach the supervisor instead of failing closed.

    The incident task does not own repository mutations: the formal
    ``foreign_disposition`` actuator remains the only write path.  It therefore
    needs an explicit, empty observe-only output declaration so the dispatcher
    can admit and settle the observation.
    """
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")

    receipt = fi.upsert_incident(paths=["a.py"], tasks_path=tasks)
    row = next(
        task for task in json.loads(tasks.read_text(encoding="utf-8"))
        if task.get("id") == receipt["task_id"]
    )

    assert row["dispatch_lane"] == "agent"
    assert row["write_intent"] == "observe_only"
    assert row["declared_output_paths"] == []
    assert row["post_merge_actions"] == []
    contract, error = _dispatch_execution_contract(row)
    assert error is None
    assert contract is not None
    assert contract["write_intent"] == "observe_only"


def test_existing_legacy_incident_is_repaired_through_the_queue_writer(
    tmp_path: Path,
):
    """Rows materialized before the contract change must self-heal on update."""
    tasks = tmp_path / "next_tasks.json"
    paths = ["a.py"]
    fp = fi.fingerprint(paths)
    tasks.write_text(
        json.dumps(
            [
                {
                    "id": f"phase-z-foreign-{fp}-e1",
                    "title": "legacy PHASE-Z incident",
                    "description": "legacy row",
                    "task_type": "platform_ops",
                    "priority": 2,
                    "status": "pending",
                    "source": "phase_z",
                    "payload": {
                        "incident_kind": fi.INCIDENT_KIND,
                        "fingerprint": fp,
                        "paths": paths,
                        "fires": 1,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    receipt = fi.upsert_incident(paths=paths, tasks_path=tasks)
    row = json.loads(tasks.read_text(encoding="utf-8"))[0]

    assert receipt["updated"] is True
    assert receipt["contract_repaired"] is True
    assert row["dispatch_lane"] == "agent"
    assert row["dispatch_preempt"] is True
    contract, error = _dispatch_execution_contract(row)
    assert error is None
    assert contract is not None


def test_terminal_fingerprint_recurrence_opens_a_new_episode(tmp_path: Path):
    """A terminal audit row must not permanently occupy the deterministic id."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    first = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)
    assert fi.settle_family_page(
        tasks,
        token=first["page_claim_token"],
        delivered=True,
        now=now,
    )
    rows = json.loads(tasks.read_text(encoding="utf-8"))
    rows[0]["status"] = "succeeded"
    tasks.write_text(json.dumps(rows), encoding="utf-8")

    recurrence = fi.upsert_incident(
        paths=["a.py"], tasks_path=tasks, now=now + timedelta(days=1),
    )

    assert recurrence["created"] is True
    assert recurrence["page_required"] is True
    assert recurrence["task_id"].endswith("-e2")
    assert len(fi.open_incidents(tasks)) == 1


def test_concurrent_terminal_recurrence_creates_and_leases_one_episode(
    tmp_path: Path,
):
    """Concurrent reopen callers share the next generation's deterministic id."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    first = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)
    assert fi.settle_family_page(
        tasks,
        token=first["page_claim_token"],
        delivered=True,
        now=now,
    )
    rows = json.loads(tasks.read_text(encoding="utf-8"))
    rows[0]["status"] = "succeeded"
    tasks.write_text(json.dumps(rows), encoding="utf-8")

    def reopen(_index: int) -> dict:
        return fi.upsert_incident(
            paths=["a.py"],
            tasks_path=tasks,
            now=now + timedelta(days=1),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(reopen, range(2)))

    assert sum(bool(receipt["created"]) for receipt in receipts) == 1
    assert sum(bool(receipt["page_required"]) for receipt in receipts) == 1
    open_rows = fi.open_incidents(tasks)
    assert len(open_rows) == 1
    assert open_rows[0]["id"].endswith("-e2")


def test_an_unacknowledged_page_lease_expires_and_retries(tmp_path: Path):
    """Crash after queue claim cannot permanently suppress first delivery."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)

    first = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)
    held = fi.upsert_incident(
        paths=["a.py"], tasks_path=tasks, now=now + timedelta(minutes=5),
    )
    retried = fi.upsert_incident(
        paths=["a.py"], tasks_path=tasks, now=now + timedelta(minutes=11),
    )

    assert first["page_required"] is True
    assert first["page_claim_token"]
    assert held["page_required"] is False
    assert retried["page_required"] is True
    assert retried["page_claim_token"] != first["page_claim_token"]


def test_schema_one_active_scalar_lease_is_normalized_without_false_delivery(
    tmp_path: Path,
):
    """Deploying schema 2 must not swallow an in-flight schema 1 page."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    first = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)
    rows = json.loads(tasks.read_text(encoding="utf-8"))
    payload = rows[0]["payload"]
    lease = payload.pop("family_page_leases")[0]
    payload["family_page_claim_schema"] = 1
    payload["family_page_lease_token"] = lease["token"]
    payload["family_page_lease_at"] = lease["leased_at"]
    payload["family_page_lease_by"] = lease["by"]
    tasks.write_text(json.dumps(rows), encoding="utf-8")

    held = fi.upsert_incident(
        paths=["a.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=5),
    )
    migrated = json.loads(tasks.read_text(encoding="utf-8"))[0]["payload"]
    assert held["page_required"] is False
    assert migrated["family_page_claim_schema"] == 2
    assert migrated["family_page_leases"][0]["token"] == first["page_claim_token"]
    assert "family_page_delivered_at" not in migrated
    assert "family_page_lease_token" not in migrated


def test_schema_one_expired_scalar_lease_retries_instead_of_false_delivery(
    tmp_path: Path,
):
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    first = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)
    rows = json.loads(tasks.read_text(encoding="utf-8"))
    payload = rows[0]["payload"]
    lease = payload.pop("family_page_leases")[0]
    payload["family_page_claim_schema"] = 1
    payload["family_page_lease_token"] = lease["token"]
    payload["family_page_lease_at"] = lease["leased_at"]
    payload["family_page_lease_by"] = lease["by"]
    tasks.write_text(json.dumps(rows), encoding="utf-8")

    retried = fi.upsert_incident(
        paths=["a.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=11),
    )
    migrated = json.loads(tasks.read_text(encoding="utf-8"))[0]["payload"]
    assert retried["page_required"] is True
    assert retried["page_claim_token"] != first["page_claim_token"]
    assert "family_page_delivered_at" not in migrated


def test_schema_one_released_scalar_state_claims_a_fresh_page(tmp_path: Path):
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    first = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)
    rows = json.loads(tasks.read_text(encoding="utf-8"))
    payload = rows[0]["payload"]
    payload.pop("family_page_leases")
    payload["family_page_claim_schema"] = 1
    tasks.write_text(json.dumps(rows), encoding="utf-8")

    retried = fi.upsert_incident(
        paths=["a.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=1),
    )
    assert retried["page_required"] is True
    assert retried["page_claim_token"] != first["page_claim_token"]


def test_successor_crash_retry_reuses_the_root_transport_identity(tmp_path: Path):
    """A→AB after an un-settled send must hit the same 24h dedupe episode."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    root = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)

    successor = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=11),
    )

    assert successor["page_required"] is True
    assert successor["page_transport_id"] == root["page_transport_id"]
    assert (
        phase_z._stuck_incident_alert_title(root)
        == phase_z._stuck_incident_alert_title(successor)
    )
    assert fi.settle_family_page(
        tasks,
        token=successor["page_claim_token"],
        delivered=True,
        now=now + timedelta(minutes=11, seconds=1),
    )
    repeat = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=12),
    )
    assert repeat["page_required"] is False


def test_successor_moves_the_retry_lease_before_delivery_settlement(tmp_path: Path):
    """Settlement must acknowledge the live successor, not its superseded row."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)

    successor = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=11),
    )
    assert successor["page_required"] is True
    assert fi.settle_family_page(
        tasks,
        token=successor["page_claim_token"],
        delivered=True,
        now=now + timedelta(minutes=11, seconds=1),
    )

    open_row = fi.open_incidents(tasks)[0]
    payload = open_row["payload"]
    assert payload["family_page_delivered_at"]
    assert "family_page_leases" not in payload


def test_any_predecessor_delivery_acknowledges_a_wider_live_successor(
    tmp_path: Path,
):
    """Merging two leased roots must not strand one receipt on a terminal row."""
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    root_a = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)
    root_b = fi.upsert_incident(
        paths=["b.py"],
        tasks_path=tasks,
        now=now + timedelta(seconds=1),
    )

    merged = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=1),
    )
    assert merged["page_required"] is False

    # Whichever token was moved to the successor fails; the other predecessor
    # succeeds. The successful receipt must follow superseded_by to the live row.
    open_payload = fi.open_incidents(tasks)[0]["payload"]
    moved_token = open_payload["family_page_leases"][0]["token"]
    remaining_token = next(
        token
        for token in (
            root_a["page_claim_token"],
            root_b["page_claim_token"],
        )
        if token != moved_token
    )
    assert fi.settle_family_page(
        tasks,
        token=moved_token,
        delivered=False,
        now=now + timedelta(minutes=2),
    )
    while_remaining_in_flight = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=2, seconds=1),
    )
    assert while_remaining_in_flight["page_required"] is False
    assert fi.settle_family_page(
        tasks,
        token=remaining_token,
        delivered=True,
        now=now + timedelta(minutes=2),
    )

    repeat = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=3),
    )
    assert repeat["page_required"] is False
    assert fi.open_incidents(tasks)[0]["payload"]["family_page_delivered_at"]


def test_delivery_survives_when_the_original_overlap_member_closes(
    tmp_path: Path,
):
    """A family acknowledgement belongs to every open overlap member.

    AB and BC overlap without either being a subset.  If AB owns the page,
    settles after BC joins, and then closes, BC must retain the acknowledgement;
    otherwise the next exact-BC observation silently starts a second page cycle.
    """
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    ab = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now,
    )
    bc = fi.upsert_incident(
        paths=["b.py", "c.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=1),
    )
    assert ab["page_required"] is True
    assert bc["page_required"] is False
    assert fi.settle_family_page(
        tasks,
        token=ab["page_claim_token"],
        delivered=True,
        now=now + timedelta(minutes=2),
    )

    rows = json.loads(tasks.read_text(encoding="utf-8"))
    row_ab = next(row for row in rows if row["id"] == ab["task_id"])
    row_bc = next(row for row in rows if row["id"] == bc["task_id"])
    assert row_ab["payload"]["family_page_delivered_at"]
    assert row_bc["payload"]["family_page_delivered_at"]
    row_ab["status"] = "succeeded"
    tasks.write_text(json.dumps(rows), encoding="utf-8")

    repeat = fi.upsert_incident(
        paths=["b.py", "c.py"],
        tasks_path=tasks,
        now=now + timedelta(days=2),
    )
    assert repeat["page_required"] is False


def test_merged_retry_checks_every_predecessor_transport_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A sent-before-crash predecessor cannot be lost when two roots merge.

    B's transport delivers but its process crashes before settling.  A and B
    then merge.  Once both leases expire, the retry must offer both historical
    titles to the central 24h ledger; B's receipt suppresses a third email and
    durably acknowledges the live merged row.
    """
    tasks = tmp_path / "next_tasks.json"
    storage = tmp_path / "storage"
    tasks.write_text("[]\n", encoding="utf-8")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    root_a = fi.upsert_incident(paths=["a.py"], tasks_path=tasks, now=now)
    root_b = fi.upsert_incident(
        paths=["b.py"],
        tasks_path=tasks,
        now=now + timedelta(seconds=1),
    )
    title_b = phase_z._stuck_incident_alert_title(root_b)
    dispatches: list[str] = []

    def fake_dispatch(**kwargs):
        dispatches.append(str(kwargs["title"]))
        return {
            "notification_id": f"notif-{len(dispatches)}",
            "subject": str(kwargs["title"]),
            "sent": True,
            "configured": True,
            "send_error": None,
        }

    monkeypatch.setattr(ops_alerts, "_dispatch_alert_email", fake_dispatch)
    delivered_b = ops_alerts.send_alert(
        "critical",
        title_b,
        "delivered before settlement crash",
        storage_dir=str(storage),
    )
    assert delivered_b["sent"] is True

    merged = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=1),
    )
    assert merged["page_required"] is False
    retried = fi.upsert_incident(
        paths=["a.py", "b.py"],
        tasks_path=tasks,
        now=now + timedelta(minutes=11),
    )
    assert retried["page_required"] is True
    assert root_b["page_transport_id"] in retried["page_transport_alias_ids"]

    title = phase_z._stuck_incident_alert_title(retried)
    alias_titles = phase_z._stuck_incident_alert_alias_titles(retried)
    result = ops_alerts.send_alert(
        "critical",
        title,
        "retry after merged predecessor crash",
        storage_dir=str(storage),
        dedup_alias_titles=alias_titles,
    )
    assert result["skip_reason"] == "dedup_24h"
    assert result["dedup_matched_title"] == title_b
    assert dispatches == [title_b]
    assert fi.settle_family_page(
        tasks,
        token=retried["page_claim_token"],
        delivered=True,
        now=now + timedelta(minutes=11, seconds=1),
    )
    assert fi.open_incidents(tasks)[0]["payload"]["family_page_delivered_at"]


def test_failed_delivery_releases_the_page_lease_for_the_next_fire(repo: Path):
    """A ``sent=false`` receipt is not a durable notification acknowledgement."""
    _write(repo, THEIRS, "stuck\n")

    def failed_alert(**_kwargs):
        return {"sent": False}

    outcome: dict = {}
    for _ in range(phase_z._FOREIGN_STREAK_CRITICAL):
        phase_z.run_pre_fire_guard(repo_root=repo)
        outcome = phase_z.run_phase_z(
            repo_root=repo,
            now_hhmm="03:00",
            test_runner=_no_tests,
            alert_fn=failed_alert,
        )

    assert outcome["incident"]["page_required"] is True
    row = fi.open_incidents(repo / QUEUE)[0]
    payload = row["payload"]
    assert "family_page_leases" not in payload
    assert "family_page_delivered_at" not in payload

    phase_z.run_pre_fire_guard(repo_root=repo)
    retried = _fire(repo)
    assert retried["incident"]["page_required"] is True
    payload = fi.open_incidents(repo / QUEUE)[0]["payload"]
    assert payload["family_page_delivered_at"]


def test_dedup_skip_acknowledges_the_existing_external_page(repo: Path):
    """24h transport dedupe means a prior delivery exists, so settle the lease."""
    _write(repo, THEIRS, "stuck\n")

    def deduped_alert(**_kwargs):
        return {
            "sent": False,
            "skipped": True,
            "skip_reason": "dedup_24h",
        }

    outcome: dict = {}
    for _ in range(phase_z._FOREIGN_STREAK_CRITICAL):
        phase_z.run_pre_fire_guard(repo_root=repo)
        outcome = phase_z.run_phase_z(
            repo_root=repo,
            now_hhmm="03:00",
            test_runner=_no_tests,
            alert_fn=deduped_alert,
        )

    assert outcome["incident"]["page_required"] is True
    payload = fi.open_incidents(repo / QUEUE)[0]["payload"]
    assert payload["family_page_delivered_at"]
    assert "family_page_leases" not in payload


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
    assert incident["id"] in stuck_pages[0][1]
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


def test_a_page_still_goes_out_when_incident_upsert_raises(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A queue writer failure keeps the explicit fail-loud backoff path."""
    _write(repo, THEIRS, "stuck\n")
    alerts: list = []

    def fail_upsert(**_kwargs):
        raise OSError("simulated queue writer failure")

    monkeypatch.setattr(phase_z, "upsert_incident", fail_upsert)
    outcome = _fires(
        repo, phase_z._FOREIGN_STREAK_CRITICAL, alerts=alerts,
    )

    assert outcome["incident"]["reason"] == "error"
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
        # Match by content, not index — _git_lines injects `-c core.quotePath=false`
        # ahead of the subcommand (CJK-path fix, 2026-08-04).
        if "for-each-ref" in cmd and "--format=%(refname)" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "refs/quarantine/x\n", "")
        if "ls-tree" in cmd:
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


# ── CJK paths must survive git's C-quoting (2026-08-04 undead-incident fix) ──


def test_cjk_paths_are_covered_and_dirty_with_their_real_names(repo: Path):
    """git C-quotes non-ASCII pathnames by default, so a CJK path read from
    status/ls-tree never matched the incident's raw UTF-8 path set: the file
    was quarantined AND dirty, yet reported as neither — two incidents became
    mathematically uncloseable and pinned the dispatch derate forever."""
    rel = "storage/ops/graphify/query_中文檔名_20260801.jsonl"
    _write(repo, rel, "line-1\n")
    # Put the CJK file into an immutable quarantine ref the way phase_z does:
    # a commit object reachable from refs/volpred/quarantine/*.
    _git(repo, "add", rel)
    _git(repo, "commit", "-qm", "quarantine checkpoint")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "update-ref", "refs/volpred/quarantine/20260804TESTZ", sha)
    # Make the same path dirty in the working tree again.
    _write(repo, rel, "line-1\nline-2-dirty\n")

    covered = fi.quarantine_covered_paths(repo)
    dirty = fi.dirty_paths(repo)

    assert rel in covered, f"C-quoted ls-tree output lost the CJK path: {sorted(covered)}"
    assert rel in dirty, f"C-quoted status output lost the CJK path: {sorted(dirty)}"
    for got in (covered, dirty):
        assert not any(p.startswith('"') for p in got), (
            "raw C-quoted names leaked through instead of UTF-8"
        )


def test_a_path_landed_in_head_counts_as_covered(repo: Path):
    """A path committed to HEAD and clean in the working tree is preserved in
    the strongest form there is; demanding a quarantine ref on top left landed
    paths permanently 'uncovered' and their incidents undead (2026-08-04)."""
    rel = "storage/landed_artifact.json"
    _write(repo, rel, "{}\n")
    _git(repo, "add", rel)
    _git(repo, "commit", "-qm", "land the artifact")

    verdict = fi.incident_closeable(repo, [rel])

    info = verdict["paths"][rel]
    assert info["covered"] is True
    assert info["still_dirty_in_main"] is False
    assert verdict["closeable"] is True
