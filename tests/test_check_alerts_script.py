from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


def _load_check_alerts_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "check_alerts.py"
    spec = importlib.util.spec_from_file_location("check_alerts_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_auto_trigger_release_pool_if_due_records_fallback_observability(tmp_path: Path, monkeypatch):
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)

    settings_path = tmp_path / "storage" / ".release_settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "mode": "auto",
                "interval_minutes": 60,
                "last_released_at": "2026-04-23T10:00:00+00:00",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def _fake_run(cmd, cwd, capture_output, text, timeout):
        assert cwd == str(tmp_path)
        assert capture_output is True
        assert text is True
        assert timeout == 180
        return subprocess.CompletedProcess(cmd, 0, stdout="released\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = check_alerts._auto_trigger_release_pool_if_due()

    assert result["triggered"] is True
    assert result["ok"] is True

    release_log = (tmp_path / "storage" / "logs" / "cron" / "release_pool.log").read_text(encoding="utf-8")
    assert "check_alerts fallback fire" in release_log

    cron_last_run = json.loads((tmp_path / "storage" / "ops" / "cron_last_run.json").read_text(encoding="utf-8"))
    from datetime import datetime

    expected = datetime.fromisoformat(result["end_at"]).isoformat(timespec="seconds")
    assert cron_last_run["release_pool"] == expected


def test_release_pool_fallback_warns_on_corrupt_cron_state(tmp_path: Path, monkeypatch, capsys):
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)
    state_path = tmp_path / "storage" / "ops" / "cron_last_run.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{bad json", encoding="utf-8")

    check_alerts._record_release_pool_fallback_fire(
        start_iso="2026-06-23T00:00:00+00:00",
        end_iso="2026-06-23T00:00:05+00:00",
        returncode=0,
    )

    captured = capsys.readouterr()
    assert "[check_alerts] WARN cron_last_run JSON read failed; using empty object" in captured.err
    assert "cron_last_run.json" in captured.err
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {"release_pool": "2026-06-23T00:00:05+00:00"}


def test_piggy_back_drift_warns_on_bad_state_source(tmp_path: Path, monkeypatch, capsys):
    check_alerts = _load_check_alerts_module()
    monkeypatch.setattr(check_alerts, "PROJECT_ROOT", tmp_path)
    state_path = tmp_path / "storage" / "ops" / "cron_last_run.json"
    config_path = tmp_path / "config" / "runtime_schedules.json"
    state_path.parent.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    state_path.write_text("{bad json", encoding="utf-8")
    config_path.write_text(json.dumps({"system_crontab": {"items": []}}), encoding="utf-8")

    result = check_alerts._check_piggy_back_drift({"ok": True, "jobs": []})

    captured = capsys.readouterr()
    assert result == {"drift_count": 0, "drifts": []}
    assert "[check_alerts] WARN cron_last_run JSON read failed; using empty object" in captured.err
    assert "piggy-back-drift: none" in captured.out
