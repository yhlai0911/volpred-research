from __future__ import annotations

from volpred.ops import autotune


def test_autotune_warns_on_invalid_floor_and_cap(monkeypatch, capsys) -> None:
    rules = {
        "family_minimums": {
            "floors": {"research": "bad-floor", "ops": 4},
            "weekly_caps": {"content": "bad-cap", "ops": 10},
        }
    }
    monkeypatch.setattr(
        autotune,
        "build_supervisor_snapshot",
        lambda days, storage_dir, rules_path: {
            "task_activity": {"by_family": {"ops": 0, "content": 20}},
            "family_coverage_deficit": {"families_below_floor": []},
        },
    )
    monkeypatch.setattr(autotune, "load_supervisor_rules", lambda rules_path: rules)

    result = autotune.autotune_supervisor_rules(dry_run=True, aggressiveness=0.3)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["floor_changes"] == [
        {
            "family": "ops",
            "old_floor": 4,
            "new_floor": 3,
            "actual": 0,
            "rationale": "actual(0) < 50% of floor(4); lowered by 1",
        }
    ]
    assert result["cap_changes"] == []
    captured = capsys.readouterr()
    assert "[autotune] WARN family floor parse failed; skipping" in captured.err
    assert "research" in captured.err
    assert "bad-floor" in captured.err
    assert "[autotune] WARN family weekly cap parse failed; skipping" in captured.err
    assert "content" in captured.err
    assert "bad-cap" in captured.err
