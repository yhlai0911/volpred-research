from __future__ import annotations

import json
from pathlib import Path

from scripts import audit_silent_fallbacks
import scripts.content_correction_scanner as module


def _patch_paths(tmp_path: Path, monkeypatch) -> Path:
    reports_dir = tmp_path / "storage" / "reports"
    monkeypatch.setattr(module, "PROJECT", tmp_path)
    monkeypatch.setattr(module, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(module, "FEED_PATH", reports_dir / "feed.json")
    return reports_dir


def test_load_articles_warns_and_skips_bad_single_report(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    reports_dir = _patch_paths(tmp_path, monkeypatch)
    reports_dir.mkdir(parents=True)
    (reports_dir / "bad.json").write_text("{bad json", encoding="utf-8")
    (reports_dir / "good.json").write_text(
        json.dumps(
            {
                "id": "good",
                "title": "Valid article",
                "content": "This article has enough body text for scanner inclusion.",
                "status": "published",
            }
        ),
        encoding="utf-8",
    )

    articles = module.load_articles()

    captured = capsys.readouterr()
    assert [article["id"] for article in articles] == ["good"]
    assert (
        "[content_correction_scanner] WARN report JSON read failed; skipping"
        in captured.err
    )
    assert "bad.json" in captured.err
    assert "JSONDecodeError" in captured.err


def test_load_articles_warns_on_bad_feed_json(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    reports_dir = _patch_paths(tmp_path, monkeypatch)
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text("{bad json", encoding="utf-8")

    assert module.load_articles() == []

    captured = capsys.readouterr()
    assert (
        "[content_correction_scanner] WARN feed JSON read failed; skipping feed fallback"
        in captured.err
    )
    assert "feed.json" in captured.err
    assert "JSONDecodeError" in captured.err


def test_content_correction_scanner_has_no_silent_fallback_audit_findings() -> None:
    findings = audit_silent_fallbacks.audit_file(Path(module.__file__))

    assert findings == []
