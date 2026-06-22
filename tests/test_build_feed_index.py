from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _load_build_feed_index():
    module_path = ROOT / "scripts" / "build_feed_index.py"
    spec = importlib.util.spec_from_file_location("build_feed_index", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_jq_stream_warns_on_invalid_json_line(tmp_path: Path, monkeypatch, capsys) -> None:
    module = _load_build_feed_index()
    feed_path = tmp_path / "feed.json"
    feed_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(module, "FEED_PATH", feed_path)

    def _fake_run(*args, **kwargs):
        return SimpleNamespace(stdout='{"id":"ok"}\n{bad-json\n')

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    records = module._jq_stream()

    assert records == [{"id": "ok"}]
    captured = capsys.readouterr()
    assert "[feed-index] WARN jq output JSON line parse failed; skipping" in captured.err
    assert "{bad-json" in captured.err
    assert "JSONDecodeError" in captured.err
