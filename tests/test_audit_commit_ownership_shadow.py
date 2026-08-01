from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import scripts.audit_commit_ownership_shadow as audit
from volpred.ops import fire_manifest


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _write_hourly_schedule(repo: Path) -> None:
    target = repo / "config" / "runtime_schedules.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({
            "cron_jobs": [{
                "id": "volpred-hourly-dispatch",
                "schedule": "7 * * * *",
            }],
        }),
        encoding="utf-8",
    )


def _record(at: datetime, *, fire_id: str | None, missing: list[str]) -> dict:
    return {
        "at": at.isoformat(),
        "fire_id": fire_id,
        "fire_ids": [],
        "baseline_available": True,
        "inferred": missing,
        "declared": [],
        "agree": [],
        "inferred_not_declared": missing,
        "declared_not_inferred": [],
    }


def test_audit_reads_git_common_dir_and_hashes_exact_shadow_evidence(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    start = datetime(2026, 7, 25, tzinfo=UTC)
    rows = [
        _record(start, fire_id=None, missing=[]),
        _record(
            start + timedelta(days=7),
            fire_id="fire-1",
            missing=["storage/next_tasks.json", "src/wip.py"],
        ),
    ]
    payload = "".join(json.dumps(row) + "\n" for row in rows).encode()
    shadow = fire_manifest.shadow_log_path(repo)
    shadow.write_bytes(payload)
    _write_hourly_schedule(repo)
    fire_manifest.open_manifest(
        repo,
        fire_id="fire-1",
        actor="test",
        now=(start + timedelta(days=7)).timestamp(),
    )

    report = audit.run_audit(
        root=repo,
        assessed_at=start + timedelta(days=7),
        classify_path=lambda path: (
            "machine_state" if path.startswith("storage/") else "non_machine"
        ),
    )

    assert report["evidence"]["path"] == str(shadow)
    assert report["evidence"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert report["evidence"]["bytes"] == len(payload)
    assert report["missing_path_occurrences"] == {
        "machine_state": 1,
        "non_machine": 1,
    }
    assert report["manifest_cutover_eligible"] is False


def test_audit_fails_closed_on_malformed_jsonl(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    fire_manifest.shadow_log_path(repo).write_text("{\n", encoding="utf-8")

    with pytest.raises(
        fire_manifest.FireManifestError,
        match="shadow evidence line 1 is invalid JSON",
    ):
        audit.run_audit(root=repo)


def test_cli_malformed_evidence_uses_public_exit_2_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    fire_manifest.shadow_log_path(repo).write_text("{\n", encoding="utf-8")

    assert audit.main(["--repo-root", str(repo)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "audit_failed"
    assert report["legacy_stage2_metrics_pass"] is False
    assert report["manifest_cutover_eligible"] is False


def test_cli_never_returns_success_for_the_superseded_cutover_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = {
        "schema_version": "commit-ownership-shadow-assessment.v1",
        "legacy_stage2_metrics_pass": False,
        "manifest_cutover_eligible": False,
    }
    monkeypatch.setattr(audit, "run_audit", lambda **_kwargs: report)

    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out) == report

    report["legacy_stage2_metrics_pass"] = True
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["manifest_cutover_eligible"] is False
