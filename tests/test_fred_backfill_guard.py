from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    script_path = ROOT / "scripts" / "fred_backfill_guard.py"
    spec = importlib.util.spec_from_file_location("fred_backfill_guard", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_latest_date_warns_on_bad_csv_date(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    macro_dir = tmp_path / "macro"
    macro_dir.mkdir()
    (macro_dir / "fred_DGS10.csv").write_text(
        "date,value\n"
        "2026-13-01,2.0\n"
        "2026-06-20,4.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "MACRO_DIR", macro_dir)

    latest = module._latest_date("DGS10")

    assert latest == datetime(2026, 6, 20)
    captured = capsys.readouterr()
    assert "[fred_guard] WARN CSV date parse failed; skipping row" in captured.err
    assert "2026-13-01" in captured.err
    assert "fred_DGS10.csv" in captured.err
