from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refill_task_pool.py"
SPEC = importlib.util.spec_from_file_location("refill_task_pool", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_refill_skips_blank_title_candidates(tmp_path, monkeypatch):
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    candidates = tmp_path / "storage" / "publication_candidates.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    candidates.write_text(
        json.dumps(
            {
                "top_10_uncovered": [
                    {
                        "k_id": "K1378",
                        "title": "",
                        "score": 4,
                        "reasons": ["robust inference"],
                        "verdict_preview": "stale robustness fix",
                        "audiences_covered": [],
                        "covered_by": [],
                    }
                ],
                "missing_research_top5": [],
                "missing_general_top5": [],
                "candidates": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "CANDIDATES", candidates)
    monkeypatch.setattr(MODULE, "_kids_with_general_article", lambda: set())

    result = MODULE.refill(target=3, dry_run=False)

    assert result["ok"] is True
    assert result["added"] == 0
    assert result["reason"] == "no_new_candidates_passing_filter"
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert data == []
