import json
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


def test_append_to_index_writes_provenance_entry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    memory = MemorySystem(storage_dir=str(tmp_path))

    # Disable mirror to keep test hermetic
    monkeypatch.setattr(MemorySystem, "MIRROR_URL", "")
    monkeypatch.setattr(MemorySystem, "MIRROR_TOKEN", "")

    memory._append_to_index("experiments.json", {"experiment_id": "test_prov_1", "value": 1})
    memory._append_to_index("knowledge.json", {"item_id": "K_test_1", "note": "x"})

    log_path = tmp_path / "ops" / "writer_log.jsonl"
    assert log_path.exists(), "writer_log.jsonl should be created"
    lines = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2

    subsystems = {entry["subsystem"] for entry in lines}
    assert subsystems == {"memory"}
    targets = {entry["target"] for entry in lines}
    assert targets == {"memory/experiments.json", "memory/knowledge.json"}
    record_ids = {entry["record_id"] for entry in lines}
    assert record_ids == {"test_prov_1", "K_test_1"}
    for entry in lines:
        assert entry["actor"] == "claude"
        assert entry["result"] == "ok"
        assert entry["ts"].endswith("+00:00") or entry["ts"].endswith("Z")


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
