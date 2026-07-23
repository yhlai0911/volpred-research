"""Regression gate for WS-F2: the dedup-gate audit promised by rule §4.

Incident defended: 2026-06-23 dedup-gate 8-day content black hole — the gate
hard-blocked everything, nothing read the audit trail, the owner found out by
eyeballing the feed. Each rule-§4 condition gets one injected scenario, plus a
healthy trail that must NOT page:

1. black hole   — gate firing for 24h with zero passes → critical
2. block rate   — weekly hard-block rate > 30% → warn
3. arc repeat   — same narrative arc blocked ≥3 times → warn
4. healthy      — mixed pass/warn/block traffic → no findings, no breach

Also pins the mixed-schema normalization (legacy ``action`` records, structured
``gate``/``decision`` records, ``task_generation`` records with a ``blocked``
bool) and the alerts.py condition mapping (single alert owner per
`.claude/rules/alert.md`).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import _parse_dedup_gate_health_state
from volpred.ops.dedup_gate_audit import audit_dedup_decisions

NOW = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_log(storage_dir: Path, entries: list[dict]) -> None:
    log_dir = storage_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "dedup_decisions.jsonl").open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _gate(hours_ago: float, gate: str, decision: str, target: str,
          matched_id: str | None = None) -> dict:
    return {
        "ts": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "gate": gate,
        "target_id": target,
        "decision": decision,
        "matched_id": matched_id,
        "reason": "test",
    }


def _action(hours_ago: float, action: str, matched_id: str | None = None) -> dict:
    return {
        "ts": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "action": action,
        "new_title": "t",
        "matched_id": matched_id,
        "reason": "test",
    }


def _taskgen(hours_ago: float, blocked: bool, matched_ids: list[str]) -> dict:
    return {
        "ts": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "gate": "task_generation",
        "lane": "daily_article",
        "action": "block_arc_dup" if blocked else "clean",
        "blocked": blocked,
        "target_id": "task_x",
        "reason": "test",
        "saturation": 0,
        "theme_terms": [],
        "matched_ids": matched_ids,
    }


# ---------------------------------------------------------------- §4-2 black hole


def test_blackhole_breaches_critical(tmp_path: Path) -> None:
    entries = [_gate(30.0, "release_pool_arc_dedup", "pass", "mile_old")]
    entries += [
        _gate(20.0 - i, "release_pool_arc_dedup", "block", f"mile_b{i}", f"mile_arc{i}")
        for i in range(6)
    ]
    _write_log(tmp_path, entries)
    verdict = audit_dedup_decisions(storage_dir=str(tmp_path), now=NOW)
    bh = verdict["conditions"]["no_pass_blackhole"]
    assert bh["breached"] is True
    assert bh["recent_allows"] == 0
    assert bh["recent_blocks"] == 6
    assert bh["streak_hours"] >= 24.0
    assert verdict["healthy"] is False
    assert any(f["id"] == "no_pass_blackhole" and f["level"] == "critical"
               for f in verdict["findings"])

    state = _parse_dedup_gate_health_state(str(tmp_path), NOW)
    assert state["breached"] is True
    assert state["level"] == "critical"
    assert state["id"] == "dedup_gate_health"


def test_idle_pipeline_is_not_a_blackhole(tmp_path: Path) -> None:
    # No decisions at all in the 24h window: silence is publishing_freshness's
    # concern (outcome dead-man switch), not a gate black hole.
    _write_log(tmp_path, [
        _gate(48.0, "release_pool_arc_dedup", "block", "mile_x", "mile_arc"),
        _gate(50.0, "release_pool_arc_dedup", "pass", "mile_y"),
    ])
    verdict = audit_dedup_decisions(storage_dir=str(tmp_path), now=NOW)
    assert verdict["conditions"]["no_pass_blackhole"]["breached"] is False


# ---------------------------------------------------------------- §4-1 block rate


def test_high_block_rate_breaches_warn(tmp_path: Path) -> None:
    entries = [
        _gate(2.0 * i + 1.0, "anti_ai_style", "block", f"mile_r{i}") for i in range(8)
    ]
    entries += [
        _gate(1.5 * i + 0.5, "publish_throttle", "pass", f"mile_p{i}") for i in range(12)
    ]
    _write_log(tmp_path, entries)
    verdict = audit_dedup_decisions(storage_dir=str(tmp_path), now=NOW)
    rate = verdict["conditions"]["block_rate"]
    assert rate["breached"] is True
    assert rate["decisions"] == 20
    assert abs(rate["rate"] - 0.40) < 1e-9
    assert verdict["conditions"]["no_pass_blackhole"]["breached"] is False
    assert [f["id"] for f in verdict["findings"]] == ["block_rate"]

    state = _parse_dedup_gate_health_state(str(tmp_path), NOW)
    assert state["breached"] is True
    assert state["level"] == "warn"


def test_block_rate_needs_min_sample(tmp_path: Path) -> None:
    # 2 blocks / 3 decisions = 67% but only 3 real decisions (< 10): one quiet
    # day must not page. Recent allow keeps the black hole condition quiet too.
    _write_log(tmp_path, [
        _gate(1.0, "release_pool_arc_dedup", "block", "mile_a", "arc1"),
        _gate(2.0, "release_pool_arc_dedup", "block", "mile_b", "arc2"),
        _gate(3.0, "publish_throttle", "pass", "mile_c"),
    ])
    verdict = audit_dedup_decisions(storage_dir=str(tmp_path), now=NOW)
    assert verdict["conditions"]["block_rate"]["breached"] is False
    assert verdict["healthy"] is True


# ---------------------------------------------------------------- §4-3 arc repeat


def test_same_arc_blocked_three_times_breaches(tmp_path: Path) -> None:
    entries = [
        _action(10.0, "block_arc_dup", "mile_arc_hot"),
        _gate(20.0, "release_pool_arc_dedup", "block", "mile_n2", "mile_arc_hot"),
        _taskgen(40.0, True, ["mile_arc_hot"]),
    ]
    entries += [
        _gate(0.5 + i, "publish_throttle", "pass", f"mile_ok{i}") for i in range(30)
    ]
    _write_log(tmp_path, entries)
    verdict = audit_dedup_decisions(storage_dir=str(tmp_path), now=NOW)
    arc = verdict["conditions"]["arc_repeat_block"]
    assert arc["breached"] is True
    assert arc["repeat_arcs"][0]["arc_id"] == "mile_arc_hot"
    assert arc["repeat_arcs"][0]["blocks"] == 3
    # cross-schema: the three blocks came from action / gate / task_generation
    assert len(arc["repeat_arcs"][0]["gates"]) == 3
    assert [f["id"] for f in verdict["findings"]] == ["arc_repeat_block"]

    state = _parse_dedup_gate_health_state(str(tmp_path), NOW)
    assert state["breached"] is True
    assert state["level"] == "warn"


# ---------------------------------------------------------------- healthy / edges


def test_healthy_mixed_traffic_does_not_page(tmp_path: Path) -> None:
    entries = [
        _gate(1.0, "publish_throttle", "pass", "mile_1"),
        _gate(2.0, "anti_ai_style", "warn", "mile_2"),          # warn-only = allow
        _gate(3.0, "release_pool_arc_dedup", "hold", "mile_3"), # pacing hold = other
        _gate(4.0, "event_reaction_coverage", "skip", "mile_4", None),  # skip = other
        _action(5.0, "warn_arc_near_miss", "mile_x"),
        _action(6.0, "allow_same_ref_companion", "mile_y"),
        _action(7.0, "pass_prewrite"),
        _taskgen(8.0, False, []),
        _gate(9.0, "release_pool_arc_dedup", "block", "mile_5", "arc_a"),
        _action(30.0, "block_k_coverage", "arc_b"),
    ] + [
        _gate(10.0 + i, "publish_throttle", "pass", f"mile_f{i}") for i in range(6)
    ]
    _write_log(tmp_path, entries)
    verdict = audit_dedup_decisions(storage_dir=str(tmp_path), now=NOW)
    assert verdict["healthy"] is True
    assert verdict["findings"] == []
    totals = verdict["totals"]
    assert totals["allow"] == 12   # 2 gate-allow + 3 action-allow + taskgen clean + 6 passes
    assert totals["block"] == 2
    assert totals["other"] == 2    # hold + skip stay out of the rate
    rate = verdict["conditions"]["block_rate"]
    assert rate["decisions"] == 14
    assert rate["breached"] is False

    state = _parse_dedup_gate_health_state(str(tmp_path), NOW)
    assert state["breached"] is False
    assert state["level"] == "info"
    assert state["title"] == "dedup_gate_health ok"


def test_missing_log_is_healthy_no_data(tmp_path: Path) -> None:
    verdict = audit_dedup_decisions(storage_dir=str(tmp_path), now=NOW)
    assert verdict["log_exists"] is False
    assert verdict["healthy"] is True
    state = _parse_dedup_gate_health_state(str(tmp_path), NOW)
    assert state["breached"] is False


def test_unparseable_lines_are_counted_not_fatal(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    good = _gate(1.0, "publish_throttle", "pass", "mile_1")
    (log_dir / "dedup_decisions.jsonl").write_text(
        "not-json\n" + json.dumps(good) + "\n[1,2]\n", encoding="utf-8"
    )
    verdict = audit_dedup_decisions(storage_dir=str(tmp_path), now=NOW)
    assert verdict["totals"]["unparseable"] == 2
    assert verdict["totals"]["allow"] == 1


# ---------------------------------------------------------------- CLI wrapper


def test_cli_prints_json_and_exit_codes(tmp_path: Path) -> None:
    _write_log(tmp_path, [
        _gate(1.0, "publish_throttle", "pass", "mile_1"),
    ])
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "audit_dedup_gate_decisions.py"),
         "--storage-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict["healthy"] is True

    # breach → exit 1 (black hole injection, relative to real wall clock)
    real_now = datetime.now(timezone.utc)
    entries = [{
        "ts": (real_now - timedelta(hours=h)).isoformat(),
        "gate": "release_pool_arc_dedup",
        "target_id": f"mile_{h}",
        "decision": "block",
        "matched_id": f"arc{h}",
        "reason": "test",
    } for h in range(1, 7)]
    _write_log(tmp_path, entries)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "audit_dedup_gate_decisions.py"),
         "--storage-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 1, proc.stdout
    verdict = json.loads(proc.stdout)
    assert verdict["conditions"]["no_pass_blackhole"]["breached"] is True
