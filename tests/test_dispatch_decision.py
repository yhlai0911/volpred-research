"""WS-H4 step 2 — single dispatch decision pipeline (`dispatch_supervisor.decision`).

Three layers, per docs/dispatch-decision-pipeline-design.md §4:

  1. decide() unit branches — the tick-level admission ladder (auth → capacity
     → bootstrap → due/request → pregate) in one pure module.
  2. Purity locks — repeated calls are identical; the module's source contains
     no I/O / clock / randomness (the §4.2 audit grep as a test).
  3. Dry-run vs fire consistency — the H4 acceptance criterion: with the same
     injected state, `_tick_once(dry_run=True)` and `_tick_once(dry_run=False)`
     consume the SAME `Decision` (dataclass-equal, digest included); dry-run
     never calls `state.reserve_fire`.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.dispatch_supervisor import custody_receipt, decision, scheduler, state as st

CRON = "7 * * * *"


def _inp(**overrides) -> decision.DecisionInput:
    base = dict(
        auth_blocked=False,
        active_slots=0,
        capacity=2,
        quota_derated=False,
        last_fire_known=True,
        due=True,
        prev_fire="2026-07-20T10:07:00",
        fire_request=None,
        pregate_mode="off",
        demand=None,
        candidates=(),
    )
    base.update(overrides)
    return decision.DecisionInput(**base)


# ─────────────────────────────────────────────── decide() admission ladder ──

def test_auth_blocked_skips_first() -> None:
    dec = decision.decide(_inp(auth_blocked=True, active_slots=9, last_fire_known=False))
    assert (dec.action, dec.reason) == ("skip", "auth_blocked")
    assert dec.fire_reason is None


def test_slots_full_skips() -> None:
    dec = decision.decide(_inp(active_slots=2, capacity=2))
    assert (dec.action, dec.reason) == ("skip", "slots_full")


def test_unknown_last_fire_is_bootstrap_not_fire() -> None:
    # 2026-07-10 invariant: unknown state must never mean "fire now".
    dec = decision.decide(_inp(last_fire_known=False, due=False))
    assert (dec.action, dec.reason) == ("skip", "bootstrap_last_fire_at")


def test_not_due_without_request_skips() -> None:
    dec = decision.decide(_inp(due=False))
    assert (dec.action, dec.reason) == ("skip", "not_due")


def test_due_cron_mode_off_fires_without_demand() -> None:
    dec = decision.decide(_inp(pregate_mode="off"))
    assert (dec.action, dec.fire_reason) == ("fire", "cron")


def test_requested_off_cadence_fires_and_bypasses_pregate() -> None:
    dec = decision.decide(_inp(due=False, fire_request="boss-email", pregate_mode="enforce"))
    assert (dec.action, dec.fire_reason) == ("fire", "requested:boss-email")


def test_request_on_due_cron_merges_and_bypasses_pregate() -> None:
    dec = decision.decide(_inp(due=True, fire_request="boss-email", pregate_mode="enforce"))
    assert (dec.action, dec.fire_reason) == ("fire", "cron+requested:boss-email")


def test_plain_cron_with_gated_mode_demands_collection() -> None:
    for mode in decision.PREGATE_GATED_MODES:
        dec = decision.decide(_inp(pregate_mode=mode, demand=None))
        assert (dec.action, dec.fire_reason) == ("collect_demand", "cron"), mode


def test_demand_proceed_fires() -> None:
    dec = decision.decide(_inp(pregate_mode="shadow", demand={"pregate_skip": False}))
    assert (dec.action, dec.fire_reason) == ("fire", "cron")


def test_demand_skip_skips_and_consumes_slot() -> None:
    dec = decision.decide(_inp(pregate_mode="enforce", demand={"pregate_skip": True}))
    assert (dec.action, dec.reason) == ("skip", "pregate_skip")
    assert dec.fire_reason is None


# ──────────────────────────────────────────────────────────── purity locks ──

def test_decide_is_deterministic_over_repeated_calls() -> None:
    inp = _inp(pregate_mode="shadow", demand={"pregate_skip": False},
               fire_request=None, candidates=({"id": "t1", "priority": 1},))
    first = decision.decide(inp)
    for _ in range(100):
        assert decision.decide(inp) == first
    assert first.inputs_digest == inp.digest()


def test_digest_changes_with_inputs() -> None:
    assert _inp().digest() != _inp(due=False).digest()
    assert _inp().digest() != _inp(fire_request="x").digest()


def test_decision_module_source_has_no_io_clock_or_randomness() -> None:
    """§4.2 regression lock: decide() must stay pure by construction."""
    src = (Path(scheduler.__file__).parent / "decision.py").read_text(encoding="utf-8")
    for banned in ("open(", "write_text", "datetime.now", "import random", "time.time"):
        assert banned not in src, f"decision.py must not contain {banned!r}"


# ───────────────────────────────── dry-run vs fire decision consistency ──────

@pytest.fixture
def consistency_env(tmp_path: Path, monkeypatch):
    """Frozen fixture: pinned due-ness, stubbed pregate, mocked worker/phase_z,
    a decide() spy, and a resettable injected state file."""
    custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    state_path = tmp_path / "dispatch_state.json"
    with st._locked_state(state_path) as (_fh, data):
        data["last_fire_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    state_snapshot = state_path.read_bytes()

    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("test prompt", encoding="utf-8")

    # Pin the clock-dependent seam so both runs see identical (due, prev_fire)
    # even across a real minute boundary — decide() itself never reads a clock.
    pinned_prev = datetime(2026, 7, 20, 10, 7)
    monkeypatch.setattr(scheduler, "_due_to_fire", lambda **kw: (True, pinned_prev))

    monkeypatch.setattr(
        scheduler.worker, "run_worker",
        lambda **kw: SimpleNamespace(outcome="succeeded", attempts=1, duration_s=0.1, exit_code=0),
    )
    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", lambda **kw: {"skipped": True})
    monkeypatch.setattr(scheduler.phase_z, "recover_failed_closeout", lambda **kw: {"skipped": True})
    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **kw: {
            "skipped": True,
            "fire_lifecycle": {
                "generation_id": "decision-test-generation",
                "captured_at": "2026-07-20T10:07:00+00:00",
                "pre_fire_dirty": [],
            },
        },
    )

    decisions: list[decision.Decision] = []
    real_decide = decision.decide

    def spy(inp: decision.DecisionInput) -> decision.Decision:
        dec = real_decide(inp)
        decisions.append(dec)
        return dec

    monkeypatch.setattr(scheduler.decision, "decide", spy)

    reserve_calls: list = []
    real_reserve = st.reserve_fire

    def reserve_spy(**kw):
        reserve_calls.append(kw)
        return real_reserve(**kw)

    monkeypatch.setattr(scheduler.state, "reserve_fire", reserve_spy)

    def schedules(pregate: dict | None) -> Path:
        entry: dict = {"id": "volpred-hourly-dispatch", "schedule": CRON}
        if pregate is not None:
            entry["pregate"] = pregate
        p = tmp_path / "runtime_schedules.json"
        p.write_text(json.dumps({"cron_jobs": [entry]}), encoding="utf-8")
        return p

    def tick(*, dry_run: bool, schedules_path: Path):
        return asyncio.run(scheduler._tick_once(
            state_path=state_path, cron_expr=CRON,
            prompt_path=prompt_file, log_path=tmp_path / "worker.log",
            dry_run=dry_run, repo_root=tmp_path, schedules_path=schedules_path,
        ))

    def reset_state() -> None:
        state_path.write_bytes(state_snapshot)

    return SimpleNamespace(
        tick=tick, reset_state=reset_state, schedules=schedules,
        decisions=decisions, reserve_calls=reserve_calls, state_path=state_path,
    )


def test_dry_run_and_fire_consume_the_same_decision(consistency_env, monkeypatch) -> None:
    env = consistency_env
    schedules_path = env.schedules({"mode": "shadow", "window_hours": 3.0})
    monkeypatch.setattr(scheduler, "_run_pregate", lambda **kw: False)

    dry = env.tick(dry_run=True, schedules_path=schedules_path)
    assert dry["action"] == "dry_run_fire"
    d_dry = env.decisions[-1]
    assert env.reserve_calls == []  # §4.2: dry-run must never reserve

    env.reset_state()
    env.decisions.clear()
    fire = env.tick(dry_run=False, schedules_path=schedules_path)
    assert fire["action"] == "fired"
    d_fire = env.decisions[-1]
    assert len(env.reserve_calls) == 1

    # The H4 acceptance criterion: identical injected state → identical
    # Decision, digest included (dataclass equality covers every field).
    assert d_dry == d_fire
    assert d_dry.action == "fire"
    assert d_dry.fire_reason == "cron"
    assert d_dry.inputs_digest == d_fire.inputs_digest


def test_dry_run_and_fire_agree_on_pregate_skip(consistency_env, monkeypatch) -> None:
    env = consistency_env
    schedules_path = env.schedules({"mode": "enforce", "window_hours": 3.0})
    monkeypatch.setattr(scheduler, "_run_pregate", lambda **kw: True)

    dry = env.tick(dry_run=True, schedules_path=schedules_path)
    assert dry["action"] == "pregate_skip"
    d_dry = env.decisions[-1]
    assert env.reserve_calls == []

    env.reset_state()
    env.decisions.clear()
    fire = env.tick(dry_run=False, schedules_path=schedules_path)
    assert fire["action"] == "pregate_skip"
    d_fire = env.decisions[-1]
    assert env.reserve_calls == []  # a pregate skip never reserves either

    assert d_dry == d_fire
    assert (d_dry.action, d_dry.reason) == ("skip", "pregate_skip")


def test_requested_fire_consistency_and_request_consumption(consistency_env, monkeypatch) -> None:
    """Off-cadence requested fire: dry-run and fire agree, and both consume the
    request exactly once (dry-run parity with the pre-H4 behavior)."""
    env = consistency_env
    schedules_path = env.schedules({"mode": "enforce", "window_hours": 3.0})
    monkeypatch.setattr(
        scheduler, "_run_pregate",
        lambda **kw: (_ for _ in ()).throw(AssertionError("requested fire must bypass pregate")),
    )
    monkeypatch.setattr(scheduler, "_due_to_fire",
                        lambda **kw: (False, datetime(2026, 7, 20, 10, 7)))
    state_path = env.state_path

    st.request_fire("boss-email", path=state_path)
    dry = env.tick(dry_run=True, schedules_path=schedules_path)
    assert dry["action"] == "dry_run_fire"
    d_dry = env.decisions[-1]
    assert d_dry.fire_reason == "requested:boss-email"
    assert st.read_state(state_path)["fire_requested_at"] is None  # consumed

    env.reset_state()
    env.decisions.clear()
    st.request_fire("boss-email", path=state_path)
    fire = env.tick(dry_run=False, schedules_path=schedules_path)
    assert fire["action"] == "fired"
    d_fire = env.decisions[-1]
    assert st.read_state(state_path)["fire_requested_at"] is None  # consumed

    assert d_dry == d_fire
    assert d_fire.fire_reason == "requested:boss-email"


def test_request_survives_full_pool_skip(consistency_env, monkeypatch) -> None:
    """Caller contract: skips at the admission gates must NOT consume the request."""
    env = consistency_env
    schedules_path = env.schedules(None)
    state_path = env.state_path
    st.request_fire("boss-email", path=state_path)
    with st._locked_state(state_path) as (_fh, data):
        data["current_jobs"] = [
            {"job_id": "j1", "cohort_id": "c1", "slot_id": 1, "phase": "running"},
            {"job_id": "j2", "cohort_id": "c1", "slot_id": 2, "phase": "running"},
        ]

    result = env.tick(dry_run=False, schedules_path=schedules_path)

    assert result["reason"] == "producer_slot_in_flight"
    assert st.read_state(state_path)["fire_request_reason"] == "boss-email"  # survived
