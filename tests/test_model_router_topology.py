"""Tests for the 2026-07-10 topology routing layer in scripts/model_router.py.

先選協作方式再選模型：task_type → 預設拓撲的機械對照表 + task 自帶 `topology`
欄位的 per-task override。Regression 覆蓋：欄位優先、預設表、未知型別 fallback、
非法欄位值 fail-open（不 raise）、與 continue_task_dispatch report 的整合。

Run::
    uv run pytest tests/test_model_router_topology.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_model_roster as roster  # noqa: E402
import model_router as mr  # noqa: E402


def test_type_defaults_match_hard_rules() -> None:
    # 硬規錨定：這些對照若被改動，代表有人動了治理決策，測試要炸出來
    assert mr.pick_topology("experiment")["topology"] == "worktree"      # worktree only (CLAUDE.md)
    assert mr.pick_topology("paper_body")["topology"] == "inline"        # 禁 agent 寫 .tex
    assert mr.pick_topology("paper_decision")["topology"] == "inline"    # 主線程 state machine
    assert mr.pick_topology("daily_article")["topology"] == "subagent"   # writer subagent
    assert mr.pick_topology("email_reply")["topology"] == "inline"       # PHASE 0 自做
    assert mr.pick_topology("code_review")["topology"] == "codex_exec"   # Codex primary path


def test_all_model_routed_types_have_topology() -> None:
    # TASK_TYPE_TO_MODEL 的每個型別都必須有 topology 對照（避免兩表 drift）
    for task_type in mr.TASK_TYPE_TO_MODEL:
        assert task_type in mr.TASK_TYPE_TO_TOPOLOGY, f"{task_type} missing topology"


def test_codex_eligible_types_have_mechanical_routes() -> None:
    from task_pool_claim import CODEX_ELIGIBLE_TASK_TYPES

    for task_type in CODEX_ELIGIBLE_TASK_TYPES:
        assert task_type in mr.TASK_TYPE_TO_MODEL, f"{task_type} missing model route"
        assert task_type in mr.TASK_TYPE_TO_TOPOLOGY, f"{task_type} missing topology route"


def test_all_topology_values_valid() -> None:
    for task_type, topo in mr.TASK_TYPE_TO_TOPOLOGY.items():
        assert topo in mr.TOPOLOGIES, f"{task_type} has invalid topology {topo!r}"


def test_task_field_overrides_default() -> None:
    out = mr.pick_topology("experiment", {"topology": "compute_queue"})
    assert out == {"topology": "compute_queue", "source": "task_field"}


def test_task_field_normalized() -> None:
    out = mr.pick_topology("experiment", {"topology": "  Worktree "})
    assert out["topology"] == "worktree"
    assert out["source"] == "task_field"


def test_invalid_field_fails_open_to_default() -> None:
    out = mr.pick_topology("experiment", {"topology": "yolo"})
    assert out["topology"] == "worktree"
    assert out["source"] == "type_default"
    assert out["invalid_field"] == "yolo"


def test_unknown_type_falls_back() -> None:
    out = mr.pick_topology("nonexistent_type")
    assert out == {"topology": mr.DEFAULT_TOPOLOGY, "source": "fallback"}


def test_none_type_falls_back() -> None:
    assert mr.pick_topology(None)["source"] == "fallback"


def test_dispatch_report_carries_topology() -> None:
    # continue_task_dispatch 的 candidate dict 組裝用同一個 pick_topology —
    # 這裡驗證 import 路徑與欄位形狀（不跑完整 build_report，避免碰真實 pool）
    import continue_task_dispatch as ctd  # noqa: F401  (import 本身驗證 sys.path wiring)

    task = {"id": "x", "task_type": "experiment", "priority": 2}
    assert mr.pick_topology(task.get("task_type"), task)["topology"] == "worktree"


def test_active_claude_routes_use_generation_5_models() -> None:
    models = json.loads((ROOT / "config" / "models.json").read_text())
    provider = json.loads(
        (ROOT / "config" / "provider_registry.json").read_text()
    )["providers"][0]

    assert mr.MODEL_TO_CLI_FLAG["opus"] == "claude-opus-5"
    assert mr.MODEL_TO_CLI_FLAG["sonnet"] == "claude-sonnet-5"
    assert models["models"]["opus"]["id"] == "claude-opus-5"
    assert models["models"]["sonnet"]["id"] == "claude-sonnet-5"
    assert models["models"]["opus"]["context_window_tokens"] == 1_000_000
    assert models["models"]["sonnet"]["context_window_tokens"] == 1_000_000
    assert provider["model_ids"] == [
        "claude-opus-5",
        "claude-sonnet-5",
    ]


def test_roster_scanner_catches_typed_tuple_and_role_swap_pins(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    config = root / "config" / "models.json"
    script = root / "scripts" / "live.py"
    config.parent.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    config.write_text("{}\n", encoding="utf-8")
    script.write_text(
        """\
ROUTES = (("opus", "claude-opus-4-8"),)
def dispatch(model: str = "claude-opus-4-8"):
    return model
OPUS_MODEL = "claude-sonnet-5"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(roster, "CONFIG", config)

    findings = roster.scan_code_pins(
        {"claude-opus-5", "claude-sonnet-5"},
        {
            "opus": "claude-opus-5",
            "sonnet": "claude-sonnet-5",
        },
    )

    assert any(
        item["line"] == 1
        and item["role"] == "opus"
        and item["stale_id"] == "claude-opus-4-8"
        and item["reason"] == "role_mismatch"
        for item in findings
    )
    assert any(
        item["line"] == 2
        and item["stale_id"] == "claude-opus-4-8"
        and item["reason"] == "stale_id"
        for item in findings
    )
    assert any(
        item["line"] == 4
        and item["role"] == "opus"
        and item["stale_id"] == "claude-sonnet-5"
        and item["expected_id"] == "claude-opus-5"
        and item["reason"] == "role_mismatch"
        for item in findings
    )
