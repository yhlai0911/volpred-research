"""R3 dispatch-lanes（2026-07-21）：存量 P1 通膨遷移的冪等性與判定一致性。

遷移必須和 R2 admission 夾制 import **同一個判定函數** —— 兩邊各自維護條件的話，
存量與增量會漂移（一邊夾一邊放），等於重建 dual-source 病根。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import migrate_p1_inflation as mig  # noqa: E402


def _pool(tmp_path: Path) -> Path:
    tasks = [
        # 該夾：機器來源 pending P1
        {"id": "machine_p1", "title": "auto found thing", "task_type": "platform_ops",
         "priority": 1, "status": "pending", "source": "auto_discovered",
         "created_at": "2026-07-17T00:00:00+00:00"},
        {"id": "router_p1", "title": "alert remediation", "task_type": "platform_ops",
         "priority": 1, "status": "pending", "source": "internal_alert_remediation_router",
         "created_at": "2026-07-18T00:00:00+00:00"},
        # 不動：boss 來源 P1
        {"id": "boss_p1", "title": "boss asked", "task_type": "platform_ops",
         "priority": 1, "status": "pending", "source": "telegram-999",
         "created_at": "2026-07-20T00:00:00+00:00"},
        # 不動：時效 task_type P1（機器源）
        {"id": "event_p1", "title": "CPI event", "task_type": "event_article",
         "priority": 1, "status": "pending", "source": "reader_facing_refill",
         "created_at": "2026-07-20T01:00:00+00:00"},
        # 不動：dedicated-owner ingress
        {"id": "email_p1", "title": "reply boss mail", "task_type": "email_reply",
         "priority": 1, "status": "pending", "source": "gmail_inbox_poll",
         "created_at": "2026-07-20T02:00:00+00:00"},
        # 不動：機器 P1 但非 pending（存量遷移只碰 pending）
        {"id": "done_p1", "title": "already done", "task_type": "platform_ops",
         "priority": 1, "status": "succeeded", "source": "auto_discovered",
         "created_at": "2026-07-10T00:00:00+00:00",
         "result": "done"},
        # 不動：機器 P2
        {"id": "machine_p2", "title": "normal work", "task_type": "daily_article",
         "priority": 2, "status": "pending", "source": "auto_discovered",
         "created_at": "2026-07-19T00:00:00+00:00"},
    ]
    p = tmp_path / "next_tasks.json"
    p.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _load(p: Path) -> dict[str, dict]:
    return {t["id"]: t for t in json.loads(p.read_text(encoding="utf-8"))}


def test_migration_clamps_only_machine_pending_p1(tmp_path: Path) -> None:
    pool = _pool(tmp_path)
    summary = mig.migrate(pool)

    assert summary["migrated_count"] == 2
    assert sorted(r["id"] for r in summary["migrated"]) == ["machine_p1", "router_p1"]
    # 真 P1（boss / 時效 / dedicated-owner）一張不少
    assert summary["kept_p1_count"] == 3

    after = _load(pool)
    for tid in ("machine_p1", "router_p1"):
        assert after[tid]["priority"] == 2
        assert after[tid]["priority_capped_from"] == 1
        assert after[tid]["migrated_at"] == summary["migrated_at"]
        # 只改 priority + audit stamp，狀態機欄位不碰
        assert after[tid]["status"] == "pending"
    for tid in ("boss_p1", "event_p1", "email_p1"):
        assert after[tid]["priority"] == 1
        assert "priority_capped_from" not in after[tid]
    assert after["done_p1"]["priority"] == 1, "非 pending 不碰"
    assert after["machine_p2"]["priority"] == 2
    assert "priority_capped_from" not in after["machine_p2"]


def test_migration_is_idempotent_second_run_changes_nothing(tmp_path: Path) -> None:
    pool = _pool(tmp_path)
    mig.migrate(pool)
    snapshot = pool.read_bytes()

    second = mig.migrate(pool)

    assert second["migrated_count"] == 0
    assert second["migrated"] == []
    assert pool.read_bytes() == snapshot, "第二次執行必須零變更（byte-identical）"


def test_dry_run_lists_but_does_not_write(tmp_path: Path) -> None:
    pool = _pool(tmp_path)
    before = pool.read_bytes()

    summary = mig.migrate(pool, dry_run=True)

    assert summary["dry_run"] is True
    assert summary["migrated_count"] == 2
    assert pool.read_bytes() == before


def test_cli_writes_receipt_with_migration_list(tmp_path: Path, capsys) -> None:
    pool = _pool(tmp_path)
    out = tmp_path / "receipt.json"

    rc = mig.main(["--tasks", str(pool), "--out", str(out)])

    assert rc == 0
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["migrated_count"] == 2
    assert {r["id"] for r in receipt["migrated"]} == {"machine_p1", "router_p1"}
    stdout = capsys.readouterr().out
    assert "machine_p1" in stdout and "router_p1" in stdout, "遷移清單必須進 stdout"


def test_migration_reuses_the_r2_clamp_function() -> None:
    """判定唯一 owner：migration 直接 import gateway 的 clamp 函數，不得複製條件。"""
    src = (ROOT / "scripts" / "migrate_p1_inflation.py").read_text(encoding="utf-8")
    assert "clamp_machine_priority_inflation" in src
    assert "URGENT_SOURCE_TOKENS" not in src, "不得繞過 clamp 自建 source 判定"
