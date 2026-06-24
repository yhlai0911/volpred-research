from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_topic_audit():
    module_path = ROOT / "scripts" / "build_topic_diversity_audit.py"
    spec = importlib.util.spec_from_file_location("build_topic_diversity_audit", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_feed_tags_warns_on_bad_jq_json_line(monkeypatch, capsys) -> None:
    module = _load_topic_audit()
    monkeypatch.setattr(module, "_jq", lambda _prog, _path: '["VIX","K123"]\n{bad-json\n')

    tags = module._feed_tags()

    assert tags["VIX"] == 1
    assert "K123" not in tags
    err = capsys.readouterr().err
    assert "[topic-audit] WARN jq output JSON line parse failed; skipping" in err
    assert "source=feed_tags" in err
    assert "line=2" in err
    assert "JSONDecodeError" in err


def test_feed_latest_date_warns_on_bad_jq_json_line(monkeypatch, capsys) -> None:
    module = _load_topic_audit()
    monkeypatch.setattr(
        module,
        "_jq",
        lambda _prog, _path: '{"d":"2026-06-22T00:00:00Z","t":["VIX"]}\n{bad-json\n',
    )

    latest = module._feed_tag_latest_date()

    assert latest["VIX"] == "2026-06-22T00:00:00Z"
    err = capsys.readouterr().err
    assert "source=feed_tag_latest_date" in err
    assert "JSONDecodeError" in err


def test_knowledge_keyword_hits_warns_on_bad_jq_json_line(monkeypatch, capsys) -> None:
    module = _load_topic_audit()
    monkeypatch.setattr(module, "_jq", lambda _prog, _path: '"contains climate risk"\n{bad-json\n')

    hits = module._knowledge_keyword_hits(["climate", "credit"])

    assert hits == {"climate": 1, "credit": 0}
    err = capsys.readouterr().err
    assert "source=knowledge_keyword_hits" in err
    assert "JSONDecodeError" in err
