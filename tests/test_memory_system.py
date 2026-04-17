import urllib.request
from pathlib import Path

from volpred.memory.system import MemorySystem


def test_sync_to_remote_skips_unsupported_file_without_warning(tmp_path: Path, monkeypatch, capsys):
    memory = MemorySystem(storage_dir=str(tmp_path))
    (memory.memory_dir / "open_questions.json").write_text("[]")

    monkeypatch.setattr(MemorySystem, "MIRROR_URL", "https://mirror.example")
    monkeypatch.setattr(MemorySystem, "MIRROR_TOKEN", "secret")

    called = {"value": False}

    def _unexpected(*args, **kwargs):
        called["value"] = True
        raise AssertionError("urlopen should not be called for unsupported files")

    monkeypatch.setattr(urllib.request, "urlopen", _unexpected)

    assert memory._sync_to_remote("open_questions.json") is False
    assert called["value"] is False
    captured = capsys.readouterr()
    assert "Mirror sync failed" not in captured.err


def test_reconcile_remote_reports_failures(tmp_path: Path, monkeypatch, capsys):
    memory = MemorySystem(storage_dir=str(tmp_path))
    for filename in MemorySystem.SUPPORTED_MIRROR_FILES:
        (memory.memory_dir / filename).write_text("[]")

    monkeypatch.setattr(MemorySystem, "MIRROR_URL", "https://mirror.example")
    monkeypatch.setattr(MemorySystem, "MIRROR_TOKEN", "secret")

    def _boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    result = memory.reconcile_remote()

    assert set(result) == MemorySystem.SUPPORTED_MIRROR_FILES
    assert all("network down" in value for value in result.values())
    captured = capsys.readouterr()
    assert "Warning: Mirror sync failed for knowledge.json: network down" in captured.err
