from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prune_rollback_points.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("prune_rollback_points", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_parse_timestamp_warns_when_timestamp_is_invalid(capsys) -> None:
    module = _load_module()

    assert module.parse_timestamp("snapshot_20261340T250000Z") is None
    err = capsys.readouterr().err
    assert "[prune-rollback] WARN timestamp parse failed" in err
    assert "snapshot_20261340T250000Z" in err
    assert "ValueError:" in err


def test_dir_size_bytes_warns_when_file_stat_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    module = _load_module()
    ok = tmp_path / "ok.txt"
    broken = tmp_path / "broken.txt"
    ok.write_text("ok", encoding="utf-8")
    broken.write_text("broken", encoding="utf-8")

    original_is_file = Path.is_file
    original_stat = Path.stat

    def _is_file(self):
        if self == broken:
            return True
        return original_is_file(self)

    def _stat(self, *args, **kwargs):
        if self == broken:
            raise OSError("stat unavailable")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", _is_file)
    monkeypatch.setattr(Path, "stat", _stat)

    assert module.dir_size_bytes(tmp_path) == len("ok")
    err = capsys.readouterr().err
    assert "[prune-rollback] WARN file size stat failed; excluding from size total" in err
    assert "broken.txt" in err
    assert "OSError: stat unavailable" in err


def test_dir_size_bytes_warns_when_file_type_check_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()
    ok = tmp_path / "ok.txt"
    broken = tmp_path / "broken.txt"
    ok.write_text("ok", encoding="utf-8")
    broken.write_text("broken", encoding="utf-8")

    original_is_file = Path.is_file

    def _is_file(self):
        if self == broken:
            raise OSError("type check unavailable")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", _is_file)

    assert module.dir_size_bytes(tmp_path) == len("ok")
    err = capsys.readouterr().err
    assert "[prune-rollback] WARN file type check failed; excluding from size total" in err
    assert "broken.txt" in err
    assert "OSError: type check unavailable" in err
