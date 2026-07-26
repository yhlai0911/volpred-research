from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from scripts.cron_owner_gate import owner_for_wrapper

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path, *, mode: str, active_jobs: dict | None = None) -> Path:
    path = tmp_path / "runtime_schedules.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schedule_materialization": {
                    "mode": mode,
                    "active_jobs": active_jobs or {},
                },
                "system_crontab": {
                    "items": [
                        {
                            "id": "demo",
                            "wrapper_script": "/x/cron_demo.sh",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_owner_gate_uses_canonical_canary_owner(tmp_path: Path) -> None:
    legacy = _config(tmp_path, mode="canary")
    core = _config(
        tmp_path / "core",
        mode="canary",
        active_jobs={"demo": {"activated_at": "2026-07-26T10:20:00Z"}},
    )

    assert owner_for_wrapper("cron_demo.sh", config_path=legacy) == (
        "legacy",
        "demo",
    )
    assert owner_for_wrapper("cron_demo.sh", config_path=core) == (
        "operations_core",
        "demo",
    )


def test_cron_lib_suppresses_stale_legacy_trigger_before_business_action(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "cron_handoff_regen.sh"
    effect = tmp_path / "business-effect"
    wrapper.write_text(
        "#!/bin/bash\n"
        f"source {ROOT / 'scripts' / 'cron_lib.sh'}\n"
        "cron_emit_start handoff_regen\n"
        f"touch {effect}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    completed = subprocess.run(
        [str(wrapper)],
        cwd=ROOT,
        env={**os.environ, "VOLPRED_REPO_ROOT": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert not effect.exists()
    assert "legacy trigger suppressed" in completed.stdout


def test_operations_core_execution_bypasses_legacy_gate(tmp_path: Path) -> None:
    wrapper = tmp_path / "cron_handoff_regen.sh"
    effect = tmp_path / "business-effect"
    wrapper.write_text(
        "#!/bin/bash\n"
        f"source {ROOT / 'scripts' / 'cron_lib.sh'}\n"
        "cron_emit_start handoff_regen\n"
        f"touch {effect}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    completed = subprocess.run(
        [str(wrapper)],
        cwd=ROOT,
        env={
            **os.environ,
            "VOLPRED_REPO_ROOT": str(ROOT),
            "VOLPRED_SCHEDULE_OWNER": "operations_core",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert effect.exists()
