from __future__ import annotations

from pathlib import Path
import json

from volpred.ops.execution.spawn_audit import (
    SpawnKind,
    audit_provider_spawns,
)


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_BUSINESS_LAUNCHERS = {
    "scripts/dispatch_supervisor/codex_failover.py",
    "scripts/dispatch_supervisor/worker.py",
    "scripts/gen_lazypack_agy.py",
    "scripts/gen_lazypack_codex.py",
    "scripts/run_agent_job.py",
    "scripts/scan_trending_agy.py",
    "src/volpred/ops/execution_brief.py",
    "src/volpred/ops/questions.py",
    "src/volpred/publisher/prepublish_audit.py",
}
EXPECTED_DIAGNOSTIC_LAUNCHERS = {
    "scripts/gen_codex_cli_reference.py",
    "src/volpred/ops/alerts.py",
}


def test_every_production_ai_cli_spawn_is_discovered_and_classified() -> None:
    report = audit_provider_spawns(ROOT)

    assert report.files(SpawnKind.BUSINESS) == EXPECTED_BUSINESS_LAUNCHERS
    assert report.files(SpawnKind.DIAGNOSTIC) == EXPECTED_DIAGNOSTIC_LAUNCHERS
    assert not report.unclassified


def test_every_business_spawn_is_guarded_by_provider_policy() -> None:
    report = audit_provider_spawns(ROOT)

    assert not report.unguarded, report.format_violations()


def test_new_business_launcher_cannot_hide_behind_a_diagnostic_exemption(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "new_provider.py").write_text(
        "import subprocess\n"
        "subprocess.run(['codex', '--version'])\n"
        "subprocess.run(['codex', 'exec', 'do work'])\n"
    )

    report = audit_provider_spawns(tmp_path)

    assert report.files(SpawnKind.BUSINESS) == {"scripts/new_provider.py"}
    assert len(report.unguarded) == 1
    assert report.unguarded[0].line == 3


def test_live_shell_launchers_route_through_the_same_provider_policy() -> None:
    bounded = (ROOT / "scripts/codex_exec_bounded.sh").read_text()
    responder = (ROOT / "scripts/telegram_responder.sh").read_text()
    schedules = json.loads((ROOT / "config/runtime_schedules.json").read_text())

    assert "authorize_provider_spawn(" in bounded
    assert "verify_spawn_receipt(" in bounded
    assert '"bounded-codex.agentic"' in bounded
    assert "authorized_provider_exec.py" in responder
    assert "--contract telegram-responder.claude" in responder
    assert "VOLPRED_CODEX_EXEC_CONTRACT=telegram-responder.codex" in responder

    retired_hourly = next(
        item
        for item in schedules["cron_jobs"]
        if item.get("canonical_script") == "scripts/cron_hourly_dispatch.sh"
    )
    assert retired_hourly["status"] == "retired"
    assert retired_hourly["host_crontab_managed"] is False
