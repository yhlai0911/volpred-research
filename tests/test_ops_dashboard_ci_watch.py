from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_ops_dashboard():
    path = Path(__file__).resolve().parents[1] / "scripts" / "ops_dashboard.py"
    spec = importlib.util.spec_from_file_location("ops_dashboard_ci_watch", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("remediating", "warn"),
        ("verifying", "warn"),
        ("recovery_pending", "warn"),
        ("recovery_cleanup_pending", "warn"),
        ("escalation_pending", "critical"),
        ("escalated", "critical"),
    ],
)
def test_ci_watch_active_incident_is_visible_on_dashboard(phase, expected):
    dashboard = _load_ops_dashboard()
    state = {
        "active_incident": {
            "incident_id": "ci-red-123",
            "phase": phase,
            "failure_run_keys": ["123:1", "124:1"],
            "repair_task_statuses": {"ci-red-123": "in_progress"},
        }
    }

    result = dashboard.ci_watch_section(state)

    assert result["section"] == "health_ci_watch"
    assert result["status"] == expected
    assert result["phase"] == phase
    assert result["failure_cycles"] == 2


def test_ci_watch_closed_incident_is_ok_on_dashboard():
    dashboard = _load_ops_dashboard()
    state = {
        "last_closed_incident": {
            "phase": "recovered",
            "verified_green_run": {"run_id": 456},
        }
    }

    result = dashboard.ci_watch_section(state)

    assert result["status"] == "ok"
    assert result["phase"] == "idle"
    assert "456" in result["tldr"]
