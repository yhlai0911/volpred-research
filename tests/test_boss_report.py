from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import audit_silent_fallbacks
from volpred.ops.boss_report_payload import (
    materialize_boss_report_payload,
)
from volpred.ops.boss_report_read_model import read_boss_report_program


def _load_module(name: str, rel_path: str):
    module_path = Path(__file__).resolve().parents[1] / rel_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


boss_report = _load_module("boss_report", "scripts/boss_report.py")


def _canonical_boss_fire(
    scheduled_for: str = "2026-07-26T12:10:00Z",
) -> str:
    generation = "operations-core-v1"
    digest = hashlib.sha256(
        (
            f"{generation}\0boss_report_4h\0{scheduled_for}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"{generation}:boss_report_4h:{digest}"


def _set_scheduled_boss_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    scheduled_for: str = "2026-07-26T12:10:00Z",
) -> str:
    fire_key = _canonical_boss_fire(scheduled_for)
    monkeypatch.setenv("VOLPRED_SCHEDULE_FIRE_KEY", fire_key)
    monkeypatch.setenv(
        "VOLPRED_SCHEDULE_GENERATION",
        "operations-core-v1",
    )
    monkeypatch.setenv("VOLPRED_SCHEDULE_JOB_ID", "boss_report_4h")
    monkeypatch.setenv("VOLPRED_SCHEDULE_OWNER", "operations_core")
    monkeypatch.setenv("VOLPRED_SCHEDULED_FOR", scheduled_for)
    monkeypatch.setattr(
        boss_report,
        "read_existing_owned_email_request",
        lambda idempotency_key: None,
    )
    return fire_key


def test_boss_report_surfaces_next_tasks_parse_warning(tmp_path, monkeypatch) -> None:
    (tmp_path / "storage").mkdir(parents=True)
    (tmp_path / "storage" / "next_tasks.json").write_text("{bad json\n", encoding="utf-8")

    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(boss_report, "_dashboard", lambda: {"overall_status": "ok", "sections": []})
    monkeypatch.setattr(boss_report, "_commits_in_window", lambda: [])
    monkeypatch.setattr(boss_report, "_paper_portfolio", lambda: [])
    monkeypatch.setattr(boss_report, "_autonomous_decisions", lambda: [])
    monkeypatch.setattr(boss_report, "_program_context", lambda: None)
    monkeypatch.setattr(boss_report, "_blockers", lambda: [])
    monkeypatch.setattr(boss_report, "_cron_review", lambda: "ok")

    _, html_body, plain = boss_report.build_html()

    assert "Report generation warnings" in html_body
    assert "next_tasks read failed" in html_body
    assert "next_tasks read failed" in plain


def test_boss_report_has_no_bare_except_pass() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "boss_report.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))

    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                offenders.append(node.lineno)

    assert offenders == []


def test_boss_report_has_no_silent_fallback_audit_findings() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "boss_report.py"

    findings = audit_silent_fallbacks.audit_file(script)

    assert findings == []


# ── daily-close collectors (ported 2026-07-20 WS-H2 from retired work_summary_6h;
#    coverage carried over from deleted tests/test_work_summary_6h_warnings.py) ──


def test_work_log_entries_warns_on_bad_json(tmp_path, monkeypatch) -> None:
    (tmp_path / "storage").mkdir(parents=True)
    (tmp_path / "storage" / "work_log.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)

    boss_report._REPORT_WARNINGS.clear()
    entries = boss_report._work_log_entries()

    assert entries == []
    assert any("work_log read failed" in w for w in boss_report._REPORT_WARNINGS)
    assert any("JSONDecodeError" in w for w in boss_report._REPORT_WARNINGS)


def test_work_log_entries_accepts_lowercase_utc_z_without_warning(
    tmp_path,
    monkeypatch,
) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    recent = (boss_report.NOW - boss_report.timedelta(hours=1)).isoformat()
    (storage / "work_log.json").write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-06-09T03:30:z",
                    "task_id": "historical-row",
                },
                {
                    "timestamp": recent,
                    "task_id": "recent-row",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)

    boss_report._REPORT_WARNINGS.clear()
    entries = boss_report._work_log_entries()

    assert [entry["task_id"] for entry in entries] == ["recent-row"]
    assert not any(
        "timestamp unparseable" in warning
        for warning in boss_report._REPORT_WARNINGS
    )


def test_program_read_model_uses_canonical_master_spec_not_stale_cycle_docs(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    ops = tmp_path / "storage" / "ops"
    docs.mkdir()
    ops.mkdir(parents=True)
    (tmp_path / "storage" / "next_tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "assign-control",
                    "status": "pending",
                    "title": "全面重構 Operations Core",
                    "task_type": "platform_ops",
                }
            ]
        ),
        encoding="utf-8",
    )
    (ops / "task_pool_mode.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "mode": "direct_execution",
                "preserve_task_ids": ["assign-control"],
            }
        ),
        encoding="utf-8",
    )
    (ops / "current_cycle_intent.json").write_text(
        json.dumps({"intent": "STALE MAY CYCLE"}),
        encoding="utf-8",
    )
    (docs / "ops_team_structure.md").write_text(
        "## Next actions\n1. STALE MAY ACTION\n",
        encoding="utf-8",
    )
    (docs / "refactor_plan_ops_master_2026_07.md").write_text(
        "\n".join(
            (
                "# Master",
                "",
                "## 7. 狀態表（canonical — 唯一進度真相）",
                "",
                "| 項 | 狀態 | 證據 |",
                "|---|---|---|",
                "| **T05 Notification Tracer** | ✅ 2026-07-26 | done |",
                "| **T09 Scheduler Ownership Cutover** | 🟡 contained | 長窗未滿 |",
                "| Program commit 15：**production ownership** | ⏳ pending | 雙機未完成 |",
                "",
                "## 8. 後續",
            )
        ),
        encoding="utf-8",
    )

    context = read_boss_report_program(tmp_path)

    assert context.intent == "全面重構 Operations Core"
    assert [item.title for item in context.open_items] == [
        "T09 Scheduler Ownership Cutover",
        "Program commit 15：production ownership",
    ]
    assert [item.status for item in context.open_items] == [
        "🟡 contained",
        "⏳ pending",
    ]
    assert context.source_ref == (
        "docs/refactor_plan_ops_master_2026_07.md#7"
    )
    assert (
        "storage/ops/task_pool_mode.json + "
        "storage/next_tasks.json#assign-control"
        in context.as_report_fields()["source_identity"]
    )
    rendered = json.dumps(
        context.as_report_fields(),
        ensure_ascii=False,
    )
    assert "STALE MAY" not in rendered
    assert "T05 Notification Tracer" not in rendered


def test_program_read_model_accepts_restored_queued_execution_control(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    ops = tmp_path / "storage" / "ops"
    docs.mkdir()
    ops.mkdir(parents=True)
    (docs / "refactor_plan_ops_master_2026_07.md").write_text(
        "\n".join(
            (
                "# Master",
                "",
                "## 7. 狀態表（canonical — 唯一進度真相）",
                "",
                "| 項 | 狀態 | 證據 |",
                "|---|---|---|",
                "| T09 Scheduler | 🟡 contained | 長窗未滿 |",
                "",
                "## 8. 後續",
            )
        ),
        encoding="utf-8",
    )
    (ops / "task_pool_mode.json").write_text(
        json.dumps(
            {
                "enabled": False,
                "mode": "queued_execution",
                "reason": (
                    "Operations Core production authorized; "
                    "resume canonical content queue"
                ),
            }
        ),
        encoding="utf-8",
    )

    context = read_boss_report_program(tmp_path)

    assert context.intent == (
        "Operations Core production authorized; "
        "resume canonical content queue"
    )
    assert context.warnings == ()
    assert "storage/ops/task_pool_mode.json" in (
        context.as_report_fields()["source_identity"]
    )


@pytest.mark.parametrize(
    ("preserve_ids", "queue", "message"),
    [
        ([], [], "must be non-empty"),
        (
            ["missing"],
            [],
            "must have exactly one queue row: missing",
        ),
        (
            ["duplicate", "duplicate"],
            [{"id": "duplicate", "title": "task"}],
            "must be unique",
        ),
        (
            ["duplicate"],
            [
                {"id": "duplicate", "title": "task A"},
                {"id": "duplicate", "title": "task B"},
            ],
            "must have exactly one queue row: duplicate",
        ),
    ],
)
def test_program_read_model_fails_closed_on_inexact_direct_control(
    tmp_path: Path,
    preserve_ids: list[str],
    queue: list[dict[str, str]],
    message: str,
) -> None:
    docs = tmp_path / "docs"
    ops = tmp_path / "storage" / "ops"
    docs.mkdir()
    ops.mkdir(parents=True)
    (docs / "refactor_plan_ops_master_2026_07.md").write_text(
        "\n".join(
            (
                "# Master",
                "",
                "## 7. 狀態表（canonical — 唯一進度真相）",
                "",
                "| 項 | 狀態 | 證據 |",
                "|---|---|---|",
                "| T09 Scheduler | 🟡 contained | 長窗未滿 |",
                "",
                "## 8. 後續",
            )
        ),
        encoding="utf-8",
    )
    (ops / "task_pool_mode.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "mode": "direct_execution",
                "preserve_task_ids": preserve_ids,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "storage" / "next_tasks.json").write_text(
        json.dumps(queue),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        read_boss_report_program(tmp_path)


def test_program_read_model_allows_all_status_rows_to_be_complete(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    ops = tmp_path / "storage" / "ops"
    docs.mkdir()
    ops.mkdir(parents=True)
    (docs / "refactor_plan_ops_master_2026_07.md").write_text(
        "\n".join(
            (
                "# Master",
                "",
                "## 7. 狀態表（canonical — 唯一進度真相）",
                "",
                "| 項 | 狀態 | 證據 |",
                "|---|---|---|",
                "| T05 | ✅ 2026-07-26 | done |",
                (
                    "| T09 | root_cause_fixed_and_verified | "
                    "terminal receipt |"
                ),
                "",
                "## 8. 後續",
            )
        ),
        encoding="utf-8",
    )
    (ops / "task_pool_mode.json").write_text(
        json.dumps(
            {
                "enabled": False,
                "mode": "queued_execution",
                "reason": "All Operations Core work is complete",
            }
        ),
        encoding="utf-8",
    )

    context = read_boss_report_program(tmp_path)

    assert context.open_items == ()
    assert context.next_actions() == []
    assert context.as_report_fields()["weekly_goal"] == []


def test_articles_in_window_warns_on_bad_feed_schema(tmp_path, monkeypatch) -> None:
    reports = tmp_path / "storage" / "reports"
    reports.mkdir(parents=True)
    (reports / "feed.json").write_text('{"not": "a list"}', encoding="utf-8")
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)

    boss_report._REPORT_WARNINGS.clear()
    articles = boss_report._articles_in_window()

    assert articles == {"published": [], "drafts": []}
    assert any("feed schema invalid" in w for w in boss_report._REPORT_WARNINGS)
    assert any("dict" in w for w in boss_report._REPORT_WARNINGS)


def test_daily_close_renders_day_close_sections(monkeypatch) -> None:
    monkeypatch.setattr(boss_report, "_dashboard", lambda: {"overall_status": "ok", "sections": []})
    monkeypatch.setattr(boss_report, "_commits_in_window", lambda: [])
    monkeypatch.setattr(boss_report, "_paper_portfolio", lambda: [])
    monkeypatch.setattr(boss_report, "_pending_tasks", lambda: {"total": 0, "by_type": {}, "by_priority": {}})
    monkeypatch.setattr(boss_report, "_autonomous_decisions", lambda: [])
    monkeypatch.setattr(boss_report, "_program_context", lambda: None)
    monkeypatch.setattr(boss_report, "_blockers", lambda: [])
    monkeypatch.setattr(boss_report, "_cron_review", lambda: "ok")
    monkeypatch.setattr(boss_report, "_files_changed_in_window", lambda: {"scripts/a.py": 3})
    monkeypatch.setattr(boss_report, "_work_log_entries", lambda: [{"task_type": "experiment", "summary": "K9999 done"}])
    monkeypatch.setattr(boss_report, "_new_notifications", lambda: [{"time": "12:00", "title": "t", "level": "info"}])
    monkeypatch.setattr(
        boss_report, "_articles_in_window",
        lambda: {"published": [{"id": "x", "title": "T", "ts": "10:00", "audience": "general"}], "drafts": []},
    )
    monkeypatch.setattr(boss_report, "_active_worktrees", lambda: ["agent-abc"])

    title, html_body, plain = boss_report.build_html(daily_close=True)

    assert "每日日結" in title
    assert "Mission 5" in html_body
    assert "agent-abc" in html_body
    assert "scripts/a.py" in html_body
    assert "Daily close (24h)" in plain
    assert "published=1" in plain


def test_plain_edition_skips_day_close_sections(monkeypatch) -> None:
    monkeypatch.setattr(boss_report, "_dashboard", lambda: {"overall_status": "ok", "sections": []})
    monkeypatch.setattr(boss_report, "_commits_in_window", lambda: [])
    monkeypatch.setattr(boss_report, "_paper_portfolio", lambda: [])
    monkeypatch.setattr(boss_report, "_pending_tasks", lambda: {"total": 0, "by_type": {}, "by_priority": {}})
    monkeypatch.setattr(boss_report, "_autonomous_decisions", lambda: [])
    monkeypatch.setattr(boss_report, "_program_context", lambda: None)
    monkeypatch.setattr(boss_report, "_blockers", lambda: [])
    monkeypatch.setattr(boss_report, "_cron_review", lambda: "ok")

    called = []
    monkeypatch.setattr(boss_report, "_articles_in_window", lambda: called.append("articles"))

    title, html_body, plain = boss_report.build_html(daily_close=False)

    assert called == []  # day-close collectors must not run on the 4h editions
    assert title.startswith("[新架構派發][VolPred Boss Report]")
    assert title.count("[新架構派發]") == 1
    assert "日結" not in html_body
    assert "Daily close" not in plain


def test_build_html_uses_one_program_snapshot(monkeypatch) -> None:
    reads = 0
    program = SimpleNamespace(
        next_actions=lambda *, limit: ["same-snapshot action"],
        as_report_fields=lambda: {
            "intent": "same-snapshot intent",
            "source_identity": "same-snapshot source",
        },
    )

    def read_once():
        nonlocal reads
        reads += 1
        return program

    monkeypatch.setattr(boss_report, "_program_context", read_once)
    monkeypatch.setattr(
        boss_report,
        "_dashboard",
        lambda: {"overall_status": "ok", "sections": []},
    )
    monkeypatch.setattr(boss_report, "_commits_in_window", lambda: [])
    monkeypatch.setattr(boss_report, "_paper_portfolio", lambda: [])
    monkeypatch.setattr(
        boss_report,
        "_pending_tasks",
        lambda: {"total": 0, "by_type": {}, "by_priority": {}},
    )
    monkeypatch.setattr(boss_report, "_autonomous_decisions", lambda: [])
    monkeypatch.setattr(boss_report, "_blockers", lambda: [])
    monkeypatch.setattr(boss_report, "_cron_review", lambda: "ok")

    _, html_body, plain = boss_report.build_html()

    assert reads == 1
    assert "same-snapshot intent" in html_body
    assert "same-snapshot source" in html_body
    assert "same-snapshot action" in plain


def test_configure_window_moves_since() -> None:
    boss_report._configure_window(24.0)
    try:
        assert boss_report.WINDOW.total_seconds() == 24 * 3600
        assert boss_report.SINCE == boss_report.NOW - boss_report.WINDOW
    finally:
        boss_report._configure_window(4.0)


def test_main_routes_scheduled_report_through_owned_email(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class ForbiddenLegacyNotifier:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("scheduled report used direct EmailNotifier")

    def fake_dispatch(command, *, storage_dir):
        captured["command"] = command
        captured["storage_dir"] = storage_dir
        return {
            "notification_id": "effect-boss-report",
            "sent": True,
            "delivery_owner": "operations_core",
            "effect_status": "delivered",
            "evidence_ref": "imap-sent:boss-report",
        }

    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenLegacyNotifier,
    )
    monkeypatch.setattr(
        boss_report,
        "dispatch_email_by_current_owner",
        fake_dispatch,
        raising=False,
    )
    monkeypatch.setattr(
        boss_report,
        "build_html",
        lambda daily_close=False: (
            "[新架構派發][VolPred Boss Report] Test",
            "<p>report</p>",
            "report",
        ),
    )
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)
    fire_key = _set_scheduled_boss_environment(monkeypatch)

    exit_code = boss_report.main(["--daily-close"])

    command = captured["command"]
    assert command.idempotency_key == fire_key
    assert command.actor_ref == (
        f"schedule:boss_report_4h:{fire_key}"
    )
    assert command.title == "[新架構派發][VolPred Boss Report] Test"
    assert command.title.count("[新架構派發]") == 1
    assert captured["storage_dir"] == str(
        boss_report.PROJECT_ROOT / "storage"
    )
    assert exit_code == 0


def test_main_replays_same_fire_without_rebuilding_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    build_calls = 0
    commands = []

    def changing_builder(*, daily_close=False):
        nonlocal build_calls
        build_calls += 1
        return (
            f"[新架構派發][VolPred Boss Report] build-{build_calls}",
            f"<p>build-{build_calls}</p>",
            f"build-{build_calls}",
        )

    def fake_dispatch(command, *, storage_dir):
        commands.append(command)
        return {
            "notification_id": "effect-boss-report",
            "sent": True,
            "delivery_owner": "operations_core",
            "effect_status": "delivered",
            "evidence_ref": "imap-sent:boss-report",
        }

    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(boss_report, "build_html", changing_builder)
    monkeypatch.setattr(
        boss_report,
        "dispatch_email_by_current_owner",
        fake_dispatch,
    )
    _set_scheduled_boss_environment(monkeypatch)

    first = boss_report.main(["--daily-close"])
    second = boss_report.main(["--daily-close"])

    assert first == second == 0
    assert build_calls == 1
    assert len(commands) == 2
    assert commands[0] == commands[1]
    assert commands[0].title == (
        "[新架構派發][VolPred Boss Report] build-1"
    )
    assert commands[0].title.count("[新架構派發]") == 1
    payloads = list(
        (tmp_path / "storage" / "ops" / "boss_report_payloads").glob(
            "*.json"
        )
    )
    assert len(payloads) == 1


def test_main_reuses_cross_host_durable_command_without_local_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire_key = _set_scheduled_boss_environment(monkeypatch)
    command = SimpleNamespace(
        idempotency_key=fire_key,
        level="info",
        title="[VolPred Boss Report] durable",
        recipient="yihao.lai@gmail.com",
        text_body="durable body",
        html_body="<p>durable body</p>",
        actor_ref=f"schedule:boss_report_4h:{fire_key}",
    )
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        boss_report,
        "read_existing_owned_email_request",
        lambda idempotency_key: SimpleNamespace(command=command),
    )
    monkeypatch.setattr(
        boss_report,
        "build_html",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("cross-host replay rebuilt report")
        ),
    )
    captured: list[object] = []
    monkeypatch.setattr(
        boss_report,
        "dispatch_email_by_current_owner",
        lambda delivered, **kwargs: (
            captured.append(delivered)
            or {
                "notification_id": "effect-cross-host",
                "sent": True,
                "delivery_owner": "operations_core",
                "effect_status": "delivered",
                "evidence_ref": "imap-sent:cross-host",
            }
        ),
    )

    assert boss_report.main(["--daily-close"]) == 0
    assert len(captured) == 1
    delivered = captured[0]
    assert delivered.idempotency_key == command.idempotency_key
    assert delivered.title == command.title
    assert delivered.html_body == command.html_body
    assert delivered.actor_ref == command.actor_ref
    assert not (
        tmp_path / "storage" / "ops" / "boss_report_payloads"
    ).exists()


def test_main_rejects_noncanonical_schedule_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)
    _set_scheduled_boss_environment(
        monkeypatch,
        scheduled_for="2026-07-26T12:10:59Z",
    )

    assert boss_report.main(["--daily-close"]) == 1


def test_main_rejects_wrong_schedule_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)
    _set_scheduled_boss_environment(monkeypatch)
    monkeypatch.setenv(
        "VOLPRED_SCHEDULE_GENERATION",
        "operations-core-v0",
    )

    assert boss_report.main(["--daily-close"]) == 1


def test_materialized_payload_rejects_symlink_collision(
    tmp_path: Path,
) -> None:
    fire_key = "operations-core-v1:boss_report_4h:symlink"
    directory = (
        tmp_path / "storage" / "ops" / "boss_report_payloads"
    )
    directory.mkdir(parents=True)
    target = directory / (
        hashlib.sha256(fire_key.encode("utf-8")).hexdigest() + ".json"
    )
    target.symlink_to(tmp_path / "foreign.json")

    with pytest.raises(RuntimeError, match="regular file"):
        materialize_boss_report_payload(
            tmp_path,
            fire_key=fire_key,
            job_id="boss_report_4h",
            scheduled_for="2026-07-26T12:10:00+00:00",
            daily_close=True,
            window_hours=24,
            build=lambda: ("subject", "<p>body</p>", "body"),
        )


def test_materialized_payload_directory_is_git_ignored() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "storage/ops/boss_report_payloads/example.json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == (
        "storage/ops/boss_report_payloads/example.json"
    )


def test_boss_report_wrapper_gates_legacy_clock_before_business_effect() -> None:
    wrapper = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "cron_boss_report.sh"
    ).read_text(encoding="utf-8")

    assert "source scripts/cron_lib.sh" in wrapper
    assert "cron_emit_start" in wrapper
    assert "VOLPRED_SCHEDULED_FOR" in wrapper
    assert wrapper.index("cron_emit_start") < wrapper.index(
        "scripts/boss_report.py"
    )
