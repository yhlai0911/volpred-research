import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path


def _load_token_usage_report_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "token_usage_report.py"
    spec = importlib.util.spec_from_file_location("token_usage_report_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_generate_drilldown_splits_text_bash_and_cache(monkeypatch):
    token_usage_report = _load_token_usage_report_module()
    target_day = date(2026, 4, 23)

    records = [
        {
            "timestamp": datetime(2026, 4, 23, 1, 0, tzinfo=timezone.utc),
            "date": target_day,
            "session_id": "sess_text",
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 400,
            },
            "category": "text_only",
            "is_subagent": False,
            "content": [{"type": "text", "text": "Context 已滿。請執行 /compact 繼續。"}],
            "text_content": "Context 已滿。請執行 /compact 繼續。",
        },
        {
            "timestamp": datetime(2026, 4, 23, 1, 10, tzinfo=timezone.utc),
            "date": target_day,
            "session_id": "sess_bash",
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 5,
                "cache_read_input_tokens": 15,
                "cache_creation_input_tokens": 120,
            },
            "category": "bash_other",
            "is_subagent": False,
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "crontab -l 2>/dev/null"},
                }
            ],
            "text_content": "",
        },
        {
            "timestamp": datetime(2026, 4, 23, 1, 11, tzinfo=timezone.utc),
            "date": target_day,
            "session_id": "sess_bash",
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 3,
                "output_tokens": 2,
                "cache_read_input_tokens": 9,
                "cache_creation_input_tokens": 80,
            },
            "category": "bash_other",
            "is_subagent": False,
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "cd /Users/yhlai0911/Desktop/volpred-research"},
                }
            ],
            "text_content": "",
        },
    ]

    monkeypatch.setattr(token_usage_report, "iter_session_records", lambda *_args, **_kwargs: iter(records))

    drilldown = token_usage_report.generate_drilldown(target_day, target_day)

    assert drilldown["text_only"]["messages"] == 1
    assert drilldown["text_only"]["reason_groups"][0]["name"] == "context/compact"
    assert drilldown["bash_other"]["messages"] == 2
    family_names = {item["name"] for item in drilldown["bash_other"]["family_breakdown"]}
    assert "scheduler/cron inspection" in family_names
    assert "repo navigation" in family_names
    assert drilldown["cache_diagnostics"]["top_sessions_by_cache_create"][0]["session_id"] == "sess_text"
