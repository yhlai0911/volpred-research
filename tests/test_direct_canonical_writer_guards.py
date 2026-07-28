"""Representative regressions for direct canonical writer bypasses.

Each probe exercises a different writer family at its actual mutation helper.
The same helper must fail closed under checkout ``storage/`` and remain usable
when a test redirects its state to ``tmp_path``.
"""

from __future__ import annotations

import importlib
import os
import stat
from pathlib import Path

import pytest

from volpred.canonical_write import ENV_FLAG, CanonicalWriteBlocked

ROOT = Path(__file__).resolve().parents[1]


def _invoke(writer: str, storage_root: Path) -> Path:
    if writer == "alert_atomic_json":
        module = importlib.import_module("scripts.check_alerts")
        target = storage_root / "ops" / "guard_alert.json"
        module._write_json_atomic(target, {"ok": True})
        return target
    if writer == "fb_json":
        module = importlib.import_module("scripts.mark_fb_post_status")
        target = storage_root / "reports" / "guard_fb.json"
        module._write_json(target, [{"ok": True}])
        return target
    if writer == "telegram_state":
        module = importlib.import_module("volpred.ops.telegram")
        target = storage_root / "ops" / "telegram_state.json"
        module.save_state({"ok": True}, storage_dir=storage_root)
        return target
    if writer == "topic_cache":
        module = importlib.import_module("volpred.ops.topic_similarity")
        target = storage_root / "cache" / "topic_embeddings.json"
        module._save_cache(str(storage_root), {"probe": [1.0]})
        return target
    if writer == "writer_log":
        module = importlib.import_module("volpred.ops.writer_log")
        target = storage_root / "ops" / "writer_log.jsonl"
        module.append_writer_log("test", "guard_probe", storage_dir=str(storage_root))
        return target
    raise AssertionError(f"unknown writer probe: {writer}")


WRITERS = (
    "alert_atomic_json",
    "fb_json",
    "telegram_state",
    "topic_cache",
    "writer_log",
)


@pytest.mark.parametrize("writer", WRITERS)
def test_direct_writer_refuses_checkout_storage(writer, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "1")
    storage_root = ROOT / "storage" / "ops" / "__direct_guard_probe__" / writer

    with pytest.raises(CanonicalWriteBlocked):
        _invoke(writer, storage_root)

    assert not storage_root.exists()


@pytest.mark.parametrize("writer", WRITERS)
def test_direct_writer_allows_redirected_storage(writer, monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_FLAG, "1")
    storage_root = tmp_path / "storage"
    (storage_root / "reports").mkdir(parents=True)

    target = _invoke(writer, storage_root)

    assert target.is_file()
    if writer == "telegram_state":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_telegram_state_fsyncs_file_before_replace_and_parent_after(
    monkeypatch,
    tmp_path,
):
    module = importlib.import_module("volpred.ops.telegram")
    events: list[str] = []
    original_fsync = module.os.fsync
    original_replace = module.os.replace

    def tracked_fsync(descriptor: int) -> None:
        kind = "directory_fsync" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file_fsync"
        events.append(kind)
        original_fsync(descriptor)

    def tracked_replace(source, target) -> None:
        events.append("replace")
        original_replace(source, target)

    monkeypatch.setattr(module.os, "fsync", tracked_fsync)
    monkeypatch.setattr(module.os, "replace", tracked_replace)

    module.save_state({"chat_id": 123}, storage_dir=tmp_path / "storage")

    assert events == ["file_fsync", "replace", "directory_fsync"]


@pytest.mark.parametrize("failure", ["serialize", "replace"])
def test_telegram_state_write_failure_cleans_temporary_file(
    failure,
    monkeypatch,
    tmp_path,
):
    module = importlib.import_module("volpred.ops.telegram")
    storage_root = tmp_path / "storage"
    target = storage_root / "ops" / "telegram_state.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"chat_id":1}', encoding="utf-8")
    target.chmod(0o600)

    if failure == "serialize":
        state = {"invalid": object()}
        expected = TypeError
    else:
        state = {"chat_id": 2}
        expected = OSError
        monkeypatch.setattr(
            module.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
        )

    with pytest.raises(expected):
        module.save_state(state, storage_dir=storage_root)

    assert target.read_text(encoding="utf-8") == '{"chat_id":1}'
    assert not list(target.parent.glob(".telegram_state.json.*.tmp"))
