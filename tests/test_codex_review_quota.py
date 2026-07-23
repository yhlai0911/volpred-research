from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codex_review_quota.py"
SPEC = importlib.util.spec_from_file_location("codex_review_quota", MODULE_PATH)
quota = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(quota)

from scripts import compute_queue


USAGE = (
    "ERROR: You've hit your usage limit. Visit settings or try again at "
    "Jul 25th, 2026 1:30 PM."
)


def test_parse_reset_at_uses_taipei_host_timezone() -> None:
    parsed = quota.parse_reset_at(USAGE)
    assert parsed == datetime(2026, 7, 25, 13, 30, tzinfo=quota.TAIPEI)
    assert parsed.isoformat() == "2026-07-25T13:30:00+08:00"


def test_find_dependants_is_kid_scoped_and_pending_only() -> None:
    tasks = [
        {"id": "target", "status": "pending", "title": "K1698 Codex review closeout"},
        {"id": "other-k", "status": "pending", "title": "K1701 Codex review"},
        {"id": "same-k-no-review", "status": "pending", "title": "K1698 chart polish"},
        {"id": "running", "status": "in_progress", "title": "K1698 Codex review"},
        {"id": "exact", "status": "pending", "description": "/tmp/k1698_verdict.md"},
    ]
    assert quota.find_dependent_task_ids(
        tasks, hints=["/tmp/k1698_verdict.md"]
    ) == ["exact", "target"]


def _write_fake_bounded(path: Path, *, stdout: str, stderr: str, rc: int) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%b' {shlex.quote(stdout)}\n"
        f"printf '%b' {shlex.quote(stderr)} >&2\n"
        f"exit {rc}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_runner_quota_failure_publishes_no_zero_byte_artifact(tmp_path: Path) -> None:
    prompt = tmp_path / "k1698_prompt.md"
    out = tmp_path / "k1698_verdict.md"
    fake_bounded = tmp_path / "bounded.sh"
    fake_handler = tmp_path / "handler.py"
    called = tmp_path / "handler-called"
    prompt.write_text("review K1698", encoding="utf-8")
    out.write_bytes(b"")  # legacy artifact must be removed
    _write_fake_bounded(fake_bounded, stdout="", stderr=USAGE, rc=1)
    fake_handler.write_text(
        "from pathlib import Path\n"
        f"Path({str(called)!r}).write_text('called')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CODEX_BOUNDED"] = str(fake_bounded)
    env["CODEX_QUOTA_HANDLER"] = str(fake_handler)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "codex_review_job.sh"), str(prompt), str(out), "10"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert not out.exists()
    assert called.read_text() == "called"
    assert "QUOTA_EXHAUSTED" in result.stderr


def test_runner_success_publishes_complete_output(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    out = tmp_path / "verdict.md"
    fake_bounded = tmp_path / "bounded.sh"
    prompt.write_text("review", encoding="utf-8")
    _write_fake_bounded(fake_bounded, stdout="VERDICT: PASS\n", stderr="", rc=0)
    env = os.environ.copy()
    env["CODEX_BOUNDED"] = str(fake_bounded)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "codex_review_job.sh"), str(prompt), str(out), "10"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert out.read_text() == "VERDICT: PASS\n"
    assert not list(tmp_path.glob("verdict.md.tmp.*"))


def test_compute_receipt_gets_dedicated_quota_state_and_exact_reset(tmp_path: Path) -> None:
    stderr = tmp_path / "worker.stderr"
    stderr.write_text(
        "[CODEX_QUOTA_RESET_AT] 2099-07-25T13:30:00+08:00\n"
        "[FAILURE_CLASS] quota\n",
        encoding="utf-8",
    )
    job = {
        "id": "codex-review",
        "kind": "compute",
        "status": "failed",
        "exit_code": 1,
        "stderr_file": str(stderr),
        "followup_dispatched": False,
    }
    assert compute_queue._requeue_quota_blocked(job) is True
    assert job["status"] == "queued"
    assert job["attempt_status"] == "codex_quota_exhausted"
    assert job["quota_reset_at"] == "2099-07-25T13:30:00+08:00"
    assert job["not_before"] == job["quota_reset_at"]
