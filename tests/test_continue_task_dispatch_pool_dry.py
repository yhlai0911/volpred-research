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


def test_pool_dry_diag_legacy_dict_root_is_rejected_before_any_write(tmp_path, monkeypatch) -> None:
    # WS-A1b（取代 2026-07-20 Codex CONDITIONAL_PASS 釘住的舊契約）：dict 包裝殼
    # 只剩讀取容忍，canonical root 自 2026-07-16 single-gateway 起固定為 list。
    # 原本這裡維護一份 write_tasks_to_handle 的手抄 serialize-first 複本（helper
    # 演進時必漂移）；現在 dict-root 在「任何寫入之前」就 loud reject —— 原測試
    # 關心的「不得留下截斷/壞編碼檔案」由此獲得更強保證：檔案 byte 不動。
    q = tmp_path / "next_tasks.json"
    original = (
        '{"tasks": [{"id": "x", "title": "bad \\ud800 char", '
        '"status": "pending", "priority": 3, "task_type": "platform_ops"}]}\n'
    )
    q.write_text(original, encoding="utf-8")
    monkeypatch.setattr(ctd, "NEXT_TASKS", q)

    res = ctd._materialize_pool_dry_diagnostic_task()

    assert res["ok"] is False
    assert res["added"] == 0
    assert "must be a list" in res["error"]
    assert q.read_text(encoding="utf-8") == original  # untouched, still valid JSON
