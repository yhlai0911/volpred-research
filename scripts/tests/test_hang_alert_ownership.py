"""Regression: hang detection has ONE owner — the caller that atomically closed
the job slot. Everyone else stays silent.

Incident (2026-07-12 00:57). A hung worker trips two independent detectors within
~1s of each other:

    00:57:03,848 [worker] attempt=1 timeout=3000s — SIGTERM→SIGKILL pgid=80516
    00:57:04,906 [health] worker pgid=80516 age=3001s > 3000s cap — force-killing
    00:57:04,969 [worker] attempt=1 exit=-1000 category=hang duration=3001.3s

Both then raced to describe the incident. `record_completion` is atomic, so one
of them cleared `current_job` first; the other re-read `current_job` to build its
mail, got None, and sent this to the owner:

    pid: -1 / pgid: -1 / started_at: None / log: (unknown) / Worker log tail: (empty)

A content-free CRITICAL. Which of the two mails actually went out was decided by
the 10-minute alert-dedup lottery, so the owner intermittently received a blind
alert for a hang the system could describe perfectly well. That is what these
tests pin down: the winner mails with real numbers, the loser does not mail at
all, and exactly one mail leaves per hang.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.dispatch_supervisor import alerts, claim_release, health, procutil, worker  # noqa: E402
from scripts.dispatch_supervisor import state as st  # noqa: E402


@pytest.fixture(autouse=True)
def _throwaway_task_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both hang paths now re-pend the dead fire's task claims (WS-A2b/A2c), so
    every test in this file reaches the canonical next_tasks writer. Point it at
    tmp_path: the repo's canonical-write gate raises `CanonicalWriteBlocked`
    (a BaseException, deliberately unswallowable by the best-effort re-pend
    handler) the moment a test touches the real pool."""
    pool = tmp_path / "next_tasks.json"
    pool.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(claim_release._task_pool_claim(), "NEXT_TASKS", pool)


@pytest.fixture()
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "dispatch_state.json"


def _begin_fire(path: Path, *, pid: int, pgid: int) -> None:
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/worker.log", path=path,
    )
    st.attach_process(pid=pid, pgid=pgid, started_wall="Wed Jan  1 00:00:00 2026", path=path)


# --- the atomic transition itself -------------------------------------------

def test_winner_gets_the_job_snapshot_back(tmp_state: Path) -> None:
    """The closer never has to re-read current_job — the snapshot rides along."""
    _begin_fire(tmp_state, pid=80516, pgid=80516)

    entry = st.record_completion(
        exit_code=137, outcome="killed_timeout", final_model="opus", path=tmp_state,
    )

    assert entry is not None, "the caller that closed the slot must get the entry"
    job = entry["job"]
    assert job["pid"] == 80516
    assert job["pgid"] == 80516
    assert job["log_path"] == "/tmp/worker.log"
    assert job["started_at"], "started_at must survive the transition"


def test_race_loser_gets_none(tmp_state: Path) -> None:
    """Second closer sees an empty slot — that None is its cue to stay silent."""
    _begin_fire(tmp_state, pid=80516, pgid=80516)

    first = st.record_completion(
        exit_code=137, outcome="killed_timeout", final_model="opus", path=tmp_state,
    )
    second = st.record_completion(
        exit_code=137, outcome="killed_timeout", final_model="opus", path=tmp_state,
    )

    assert first is not None
    assert second is None


def test_job_snapshot_is_not_persisted_into_the_ring_buffer(tmp_state: Path) -> None:
    """`job` is a return-value-only convenience; the on-disk shape is unchanged."""
    _begin_fire(tmp_state, pid=80516, pgid=80516)
    st.record_completion(
        exit_code=137, outcome="killed_timeout", final_model="opus", path=tmp_state,
    )

    completions = st.read_state(tmp_state)["completions"]
    assert len(completions) == 1
    assert "job" not in completions[0]


# --- health.py honours the ownership rule ------------------------------------

def _force_hang(monkeypatch: pytest.MonkeyPatch, *, kill_ok: bool = True) -> list[dict]:
    """Make health.check_once() see an aged, identity-matched, killable worker.
    Returns the list that captures any hang alert it decides to send."""
    monkeypatch.setattr(procutil, "check_identity", lambda *_a, **_k: procutil.IDENTITY_MATCH)
    monkeypatch.setattr(health.procutil, "check_identity", lambda *_a, **_k: procutil.IDENTITY_MATCH)
    monkeypatch.setattr(health, "_force_kill_pgid", lambda _pgid, **_kw: kill_ok)
    monkeypatch.setattr(health.procutil, "pgid_members", lambda _pgid: [])

    sent: list[dict] = []

    def _capture(*, job: dict, log_tail: str = "", state_path: Path | None = None) -> bool:
        sent.append(job)
        return True

    monkeypatch.setattr(health.alerts, "send_hang_alert", _capture)
    monkeypatch.setattr(health.alerts, "read_log_tail", lambda _p, **_k: "tail")
    return sent


def test_health_mails_real_numbers_when_it_wins(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _force_hang(monkeypatch)
    _begin_fire(tmp_state, pid=80516, pgid=80516)

    health.check_once(state_path=tmp_state, max_age_s=0)

    assert len(sent) == 1, "the winner must report the incident"
    job = sent[0]
    # The exact shape of the blind mail the owner received on 2026-07-12 00:57.
    assert job["pid"] == 80516 and job["pgid"] == 80516
    assert job["started_at"] is not None
    assert job["log_path"] == "/tmp/worker.log"


def test_health_stays_silent_when_someone_else_closed_the_slot(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """health read a live job, but lost the close — the None is binding."""
    sent = _force_hang(monkeypatch)
    _begin_fire(tmp_state, pid=80516, pgid=80516)
    # The worker's own timeout closed it between health's read and health's close.
    monkeypatch.setattr(health.state, "record_completion", lambda **_k: None)

    health.check_once(state_path=tmp_state, max_age_s=0)

    assert sent == [], "the race loser must not mail"


def test_exactly_one_hang_mail_per_hang(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ownership — not the 10-minute dedup lottery — is what makes this true."""
    sent = _force_hang(monkeypatch)
    _begin_fire(tmp_state, pid=80516, pgid=80516)

    health.check_once(state_path=tmp_state, max_age_s=0)
    health.check_once(state_path=tmp_state, max_age_s=0)  # slot now empty

    assert len(sent) == 1


# --- worker.py: the path that actually mailed the blind alert ----------------

def _hang_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_state: Path, *, health_wins_the_race: bool
) -> list[dict]:
    """Drive run_worker() through a hang. If `health_wins_the_race`, the max-age
    watchdog closes the slot before the worker's hang branch runs — the exact
    2026-07-12 00:57 interleaving. Returns captured hang alerts."""
    def fake_attempt(*, state_path: Path, job_id: str, attempt: int, **_kw):
        # what the real _run_one_attempt does before spawning
        st.attach_process(
            job_id=job_id, expected_attempt=attempt,
            pid=80516, pgid=80516, started_wall="Wed Jan  1 00:00:00 2026",
            path=state_path,
        )
        st.mark_job_phase(
            job_id=job_id, expected_attempt=attempt, expected_phase="running",
            expected_pid=80516, phase="classifying", path=state_path,
        )
        if health_wins_the_race:
            st.record_completion(
                job_id=job_id, expected_attempt=attempt, expected_pid=80516,
                exit_code=-9, outcome="killed_timeout", final_model="opus",
                path=state_path,
            )
        return worker.TIMEOUT_KILLED_SENTINEL, 3001.3, "worker wedged waiting on a subagent"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_attempt)
    monkeypatch.setattr(worker.procutil, "pgid_members", lambda _pgid: [])

    sent: list[dict] = []
    monkeypatch.setattr(
        worker.alerts, "send_hang_alert",
        lambda *, job, log_tail="", state_path=None: (sent.append(job), True)[1],
    )

    worker.run_worker(
        prompt_text="x", log_path=Path("/tmp/worker.log"), state_path=tmp_state,
        max_attempts=1, sleep_fn=lambda _s: None,
    )
    return sent


def test_worker_does_not_mail_a_blind_alert_when_health_won(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE INCIDENT. The worker re-read current_job after health had cleared it,
    got nothing, and mailed pid=-1 / pgid=-1 / started_at=None / log=(unknown).

    Health already owns and reports this hang. The worker must stay silent.
    """
    sent = _hang_worker(monkeypatch, tmp_state, health_wins_the_race=True)

    assert sent == [], (
        "worker mailed a hang alert for a job it no longer held — "
        f"this is the blind CRITICAL the owner received: {sent}"
    )


def test_worker_mails_real_numbers_when_it_wins(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _hang_worker(monkeypatch, tmp_state, health_wins_the_race=False)

    assert len(sent) == 1
    job = sent[0]
    assert job["pid"] == 80516 and job["pgid"] == 80516
    assert job["started_at"] is not None
    assert job["log_path"] == "/tmp/worker.log"


# --- the alert body itself ---------------------------------------------------

def test_alert_body_carries_the_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hang mail with no pid, no start time and no log tail is not an alert."""
    bodies: list[str] = []
    monkeypatch.setattr(alerts, "_send", lambda level, title, body: bodies.append(body))
    monkeypatch.setattr(alerts.state, "should_dedup_alert", lambda *_a, **_k: False)
    monkeypatch.setattr(alerts.state, "mark_alert_sent", lambda *_a, **_k: None)

    alerts.send_hang_alert(
        job={"pid": 80516, "pgid": 80516, "started_at": "2026-07-12T00:07:03+08:00",
             "attempt": 1, "model": "claude-opus-4-8",
             "log_path": "/tmp/worker.log", "survivors": []},
        log_tail="Traceback: the agent wedged here",
    )

    assert len(bodies) == 1
    body = bodies[0]
    assert "80516" in body
    assert "2026-07-12T00:07:03+08:00" in body
    assert "the agent wedged here" in body
    for blind in ("pid: -1", "started_at: None", "log: (unknown)", "(empty)"):
        assert blind not in body, f"blind-alert marker leaked back in: {blind!r}"


def test_work_cap_timeout_is_not_reported_as_a_hang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, str, str]] = []
    dedup_keys: list[str] = []
    monkeypatch.setattr(
        alerts, "_send", lambda level, title, body: sent.append((level, title, body))
    )
    monkeypatch.setattr(
        alerts.state,
        "should_dedup_alert",
        lambda key, **_kwargs: dedup_keys.append(key) or False,
    )
    monkeypatch.setattr(alerts.state, "mark_alert_sent", lambda *_a, **_k: None)

    alerts.send_hang_alert(
        job={
            "job_id": "deadline-job",
            "pid": 45848,
            "pgid": 45848,
            "started_at": "2026-07-22T01:57:08+00:00",
            "attempt": 1,
            "model": "claude-opus-4-8",
            "log_path": "/tmp/worker.log",
            "survivors": [],
            "timeout_kind": "work_cap",
        },
        log_tail="still making progress when the deadline fired",
    )

    assert dedup_keys == ["work_timeout:deadline-job"]
    assert len(sent) == 1
    level, title, body = sent[0]
    assert (level, title) == ("warn", "supervisor work_timeout")
    assert "不證明 worker hang" in body
    assert "compute queue" in body
