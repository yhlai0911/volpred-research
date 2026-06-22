from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_warn_index_prints_exception(capsys) -> None:
    from build_knowledge_index import _warn_index  # type: ignore

    _warn_index("strategy data skipped (risk_forecast.json)", RuntimeError("bad json"))
    output = capsys.readouterr().out

    assert "[knowledge_index] WARN strategy data skipped" in output
    assert "RuntimeError: bad json" in output


def test_load_strategy_data_warns_on_bad_json(tmp_path, monkeypatch, capsys) -> None:
    import build_knowledge_index as bki  # type: ignore

    monkeypatch.setattr(bki, "STORAGE", tmp_path)
    (tmp_path / "risk_forecast.json").write_text("{bad json")

    docs = bki.load_strategy_data()
    output = capsys.readouterr().out

    assert docs == []
    assert "strategy data skipped (risk_forecast.json)" in output
    assert "JSONDecodeError" in output


def test_load_notifications_warns_on_bad_json(tmp_path, monkeypatch, capsys) -> None:
    import build_knowledge_index as bki  # type: ignore

    monkeypatch.setattr(bki, "STORAGE", tmp_path)
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    (notif_dir / "bad.json").write_text("{bad json")

    docs = bki.load_notifications()
    output = capsys.readouterr().out

    assert docs == []
    assert "notification history skipped (bad.json)" in output
    assert "JSONDecodeError" in output


def test_load_storage_experiments_warns_on_bad_json(tmp_path, monkeypatch, capsys) -> None:
    import build_knowledge_index as bki  # type: ignore

    monkeypatch.setattr(bki, "STORAGE", tmp_path)
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    (exp_dir / "broken.json").write_text("{bad json")

    docs = bki.load_storage_experiments()
    output = capsys.readouterr().out

    assert docs == []
    assert "storage experiment skipped (broken.json)" in output
    assert "JSONDecodeError" in output
