from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "continue_task_dispatch.py"
SPEC = importlib.util.spec_from_file_location("continue_task_dispatch", MODULE_PATH)
ctd = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ctd)


def test_pool_dry_diag_list_queue_appends_via_canonical_helper(tmp_path, monkeypatch) -> None:
    # WS-A1 hotfix（refactor_plan_ops_master_2026_07）：list 型 canonical queue
    # 走 write_tasks_to_handle（serialize-first），不再 truncate-before-serialize。
    q = tmp_path / "next_tasks.json"
    q.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(ctd, "NEXT_TASKS", q)

    res = ctd._materialize_pool_dry_diagnostic_task()

    assert res["ok"] is True
    assert res["added"] == 1
    saved = json.loads(q.read_text(encoding="utf-8"))
    assert saved[0]["id"].startswith(ctd.POOL_DRY_DIAGNOSTIC_PREFIX)


def test_pool_dry_diag_legacy_dict_scrubs_surrogate_and_file_stays_valid(tmp_path, monkeypatch) -> None:
    # Codex CONDITIONAL_PASS 條件（2026-07-20）：legacy dict 分支需與 helper 同等
    # 的 encode 防護 —— \ud800 escape 經 json.load 會變 lone surrogate，dump 後
    # encode 必炸；scrub 要在 truncate 前完成，序列化/編碼失敗不得留下壞檔。
    q = tmp_path / "next_tasks.json"
    q.write_text(
        '{"tasks": [{"id": "x", "title": "bad \\ud800 char", '
        '"status": "pending", "priority": 3, "task_type": "platform_ops"}]}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ctd, "NEXT_TASKS", q)

    res = ctd._materialize_pool_dry_diagnostic_task()

    assert res["ok"] is True
    assert res["added"] == 1
    saved = json.loads(q.read_text(encoding="utf-8"))  # 仍是合法 JSON = 無截斷、無壞編碼
    assert isinstance(saved, dict)
    assert len(saved["tasks"]) == 2
