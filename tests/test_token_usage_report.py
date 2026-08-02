import importlib.util
import json
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
                    "input": {"command": "cd /Users/yhlai0911/volpred-research"},
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


def test_scan_jsonl_warns_on_bad_usage_lines_without_blocking(tmp_path, capsys):
    token_usage_report = _load_token_usage_report_module()
    jsonl = tmp_path / "usage.jsonl"
    target_day = date(2026, 6, 22)
    valid = {
        "type": "assistant",
        "timestamp": "2026-06-22T01:02:03Z",
        "message": {
            "model": "claude-opus-4-7",
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "content": [{"type": "text", "text": "ok"}],
        },
    }
    bad_ts = {
        "type": "assistant",
        "timestamp": "not-a-timestamp",
        "message": {
            "model": "claude-opus-4-7",
            "usage": {"input_tokens": 1},
            "content": [],
        },
    }
    missing_ts = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-7",
            "usage": {"input_tokens": 1},
            "content": [],
        },
    }
    jsonl.write_text(
        "\n".join([
            json.dumps(valid),
            "{bad-json",
            json.dumps(bad_ts),
            json.dumps(missing_ts),
        ]),
        encoding="utf-8",
    )

    rows = list(
        token_usage_report._scan_jsonl(
            jsonl,
            "session",
            False,
            target_day,
            date(2026, 6, 23),
        )
    )

    assert len(rows) == 1
    assert rows[0]["usage"] == {"input_tokens": 10, "output_tokens": 2}
    err = capsys.readouterr().err
    assert "[token_usage_report] WARN JSONL line parse failed; skipping" in err
    assert "[token_usage_report] WARN assistant timestamp parse failed; skipping" in err
    assert "[token_usage_report] WARN assistant usage missing timestamp; skipping" in err
    assert "usage.jsonl:2" in err
    assert "JSONDecodeError" in err


def test_scan_jsonl_warns_on_unreadable_usage_path(tmp_path, capsys):
    token_usage_report = _load_token_usage_report_module()
    missing = tmp_path / "missing.jsonl"

    rows = list(token_usage_report._scan_jsonl(missing, "session", False, None, None))

    assert rows == []
    err = capsys.readouterr().err
    assert "[token_usage_report] WARN JSONL file read failed; returning no records" in err
    assert "missing.jsonl" in err
    assert "FileNotFoundError" in err


def test_discover_project_dirs_includes_repo_isolation_but_not_other_projects(
    tmp_path,
    monkeypatch,
):
    token_usage_report = _load_token_usage_report_module()
    projects = tmp_path / ".claude" / "projects"
    repo = tmp_path / "volpred-research"
    dispatch = tmp_path / ".volpred" / "run" / "dispatch_workdirs"
    assert token_usage_report._claude_project_slug(dispatch).endswith(
        "-dispatch-workdirs"
    )
    main = projects / token_usage_report._claude_project_slug(repo)
    worktree = projects / (
        token_usage_report._claude_project_slug(repo / ".claude" / "worktrees")
        + "-dispatch-slot-1-deadbeef-k1"
    )
    scratch = projects / (
        token_usage_report._claude_project_slug(dispatch)
        + "-dispatch-slot-1-deadbeef"
    )
    unrelated = projects / "-Users-someone-another-volpred-project"
    lookalike = projects / (
        token_usage_report._claude_project_slug(tmp_path / "volpred-research-old")
    )
    for path in (main, worktree, scratch, unrelated, lookalike):
        path.mkdir(parents=True)

    monkeypatch.setattr(token_usage_report, "CLAUDE_PROJECTS_DIR", main)
    monkeypatch.setattr(token_usage_report, "REPO_ROOT", repo)
    monkeypatch.setattr(token_usage_report, "DISPATCH_WORKDIR_ROOT", dispatch)

    assert token_usage_report.discover_claude_project_dirs() == [
        scratch,
        main,
        worktree,
    ]


def test_iter_session_records_dedupes_copied_jsonl_records_across_isolation_dirs(
    tmp_path,
    monkeypatch,
):
    token_usage_report = _load_token_usage_report_module()
    projects = tmp_path / ".claude" / "projects"
    repo = tmp_path / "volpred-research"
    dispatch = tmp_path / ".volpred" / "run" / "dispatch_workdirs"
    main = projects / token_usage_report._claude_project_slug(repo)
    scratch = projects / (
        token_usage_report._claude_project_slug(dispatch)
        + "-dispatch-slot-1-deadbeef"
    )
    main.mkdir(parents=True)
    scratch.mkdir(parents=True)
    copied = {
        "type": "assistant",
        "uuid": "raw-record-1",
        "timestamp": "2026-08-02T01:02:03Z",
        "message": {
            "id": "message-1",
            "model": "claude-opus-5",
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "content": [{"type": "text", "text": "same turn"}],
        },
    }
    unique = {
        **copied,
        "uuid": "raw-record-2",
        "timestamp": "2026-08-02T01:03:03Z",
        "message": {
            **copied["message"],
            "id": "message-2",
            "usage": {"input_tokens": 20, "output_tokens": 3},
        },
    }
    (main / "session.jsonl").write_text(
        json.dumps(copied) + "\n",
        encoding="utf-8",
    )
    (scratch / "session.jsonl").write_text(
        json.dumps(copied) + "\n" + json.dumps(unique) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(token_usage_report, "CLAUDE_PROJECTS_DIR", main)
    monkeypatch.setattr(token_usage_report, "REPO_ROOT", repo)
    monkeypatch.setattr(token_usage_report, "DISPATCH_WORKDIR_ROOT", dispatch)
    monkeypatch.setattr(
        token_usage_report,
        "CODEX_SESSIONS_DIR",
        tmp_path / ".codex" / "sessions",
    )

    records = list(token_usage_report.iter_session_records())

    assert [record["msg_id"] for record in records] == [
        "message-1",
        "message-2",
    ]
    assert sum(record["usage"]["input_tokens"] for record in records) == 30


def test_iter_session_records_adds_repo_bound_codex_cumulative_deltas(
    tmp_path,
    monkeypatch,
):
    token_usage_report = _load_token_usage_report_module()
    projects = tmp_path / ".claude" / "projects"
    repo = tmp_path / "volpred-research"
    main = projects / token_usage_report._claude_project_slug(repo)
    main.mkdir(parents=True)
    codex_sessions = tmp_path / ".codex" / "sessions"
    day_dir = codex_sessions / "2026" / "08" / "02"
    day_dir.mkdir(parents=True)
    next_local_day_dir = codex_sessions / "2026" / "08" / "03"
    next_local_day_dir.mkdir(parents=True)

    def _token_count(timestamp, input_tokens, cached, output):
        return {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": input_tokens,
                        "cached_input_tokens": cached,
                        "cache_write_input_tokens": 0,
                        "output_tokens": output,
                        "reasoning_output_tokens": 0,
                        "total_tokens": input_tokens + output,
                    }
                },
            },
        }

    repo_rows = [
        {
            "timestamp": "2026-08-02T01:00:00Z",
            "type": "session_meta",
            "payload": {"id": "codex-session", "cwd": str(repo)},
        },
        {
            "timestamp": "2026-08-02T01:00:01Z",
            "type": "turn_context",
            "payload": {"cwd": str(repo), "model": "gpt-5.6-sol"},
        },
        _token_count("2026-08-02T01:01:00Z", 100, 40, 10),
        _token_count("2026-08-02T01:01:01Z", 100, 40, 10),
        _token_count("2026-08-02T01:02:00Z", 160, 80, 20),
    ]
    unrelated_rows = [
        {
            "timestamp": "2026-08-02T02:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "other-session",
                "cwd": str(tmp_path / "another-repo"),
            },
        },
        _token_count("2026-08-02T02:01:00Z", 999, 0, 999),
    ]
    (day_dir / "repo.jsonl").write_text(
        "\n".join(json.dumps(row) for row in repo_rows) + "\n",
        encoding="utf-8",
    )
    fork_rows = [
        {
            "timestamp": "2026-08-02T01:02:30Z",
            "type": "session_meta",
            "payload": {
                "id": "codex-fork",
                "cwd": str(repo),
                "forked_from_id": "codex-session",
                "parent_thread_id": "codex-session",
            },
        },
        {
            "timestamp": "2026-08-02T01:02:30Z",
            "type": "session_meta",
            "payload": {"id": "codex-session", "cwd": str(repo)},
        },
        # Forked files copy the parent cumulative baseline. It is not new use.
        _token_count("2026-08-02T01:02:00Z", 160, 80, 20),
        {
            "timestamp": "2026-08-02T01:02:40Z",
            "type": "event_msg",
            "payload": {"type": "thread_settings_applied"},
        },
        {
            "timestamp": "2026-08-02T01:02:41Z",
            "type": "turn_context",
            "payload": {"cwd": str(repo), "model": "gpt-5.4-mini"},
        },
        _token_count("2026-08-02T01:03:00Z", 200, 100, 30),
    ]
    (day_dir / "fork.jsonl").write_text(
        "\n".join(json.dumps(row) for row in fork_rows) + "\n",
        encoding="utf-8",
    )
    lineage_only_rows = [
        {
            "timestamp": "2026-08-02T03:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "lineage-worker",
                "cwd": str(repo),
                "forked_from_id": "codex-session",
                "parent_thread_id": "codex-session",
            },
        },
        {
            "timestamp": "2026-08-02T03:00:00Z",
            "type": "session_meta",
            "payload": {"id": "codex-session", "cwd": str(repo)},
        },
        _token_count("2026-08-02T03:00:01Z", 10_000, 0, 1_000),
        {
            "timestamp": "2026-08-02T03:00:01.010Z",
            "type": "event_msg",
            "payload": {"type": "task_started"},
        },
        {
            "timestamp": "2026-08-02T03:00:02Z",
            "type": "turn_context",
            "payload": {"cwd": str(repo), "model": "gpt-5.6-sol"},
        },
        _token_count("2026-08-02T03:00:03Z", 10_100, 50, 1_020),
    ]
    (day_dir / "lineage-only.jsonl").write_text(
        "\n".join(json.dumps(row) for row in lineage_only_rows) + "\n",
        encoding="utf-8",
    )
    (day_dir / "unrelated.jsonl").write_text(
        "\n".join(json.dumps(row) for row in unrelated_rows) + "\n",
        encoding="utf-8",
    )
    cross_midnight_rows = [
        {
            "timestamp": "2026-08-02T23:59:00Z",
            "type": "session_meta",
            "payload": {"id": "cross-midnight", "cwd": str(repo)},
        },
        {
            "timestamp": "2026-08-02T23:59:01Z",
            "type": "turn_context",
            "payload": {"cwd": str(repo), "model": "gpt-5.4-mini"},
        },
        _token_count("2026-08-02T23:59:02Z", 30, 10, 5),
    ]
    (next_local_day_dir / "cross-midnight.jsonl").write_text(
        "\n".join(json.dumps(row) for row in cross_midnight_rows) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(token_usage_report, "CLAUDE_PROJECTS_DIR", main)
    monkeypatch.setattr(token_usage_report, "REPO_ROOT", repo)
    monkeypatch.setattr(
        token_usage_report,
        "DISPATCH_WORKDIR_ROOT",
        tmp_path / ".volpred" / "run" / "dispatch_workdirs",
    )
    monkeypatch.setattr(
        token_usage_report,
        "CODEX_SESSIONS_DIR",
        codex_sessions,
    )

    records = list(
        token_usage_report.iter_session_records(
            date(2026, 8, 2),
            date(2026, 8, 3),
        )
    )

    observed = sorted(
        (
            record["model"],
            record["usage"]["input_tokens"],
            record["usage"]["cache_read_input_tokens"],
            record["usage"]["cache_creation_input_tokens"],
            record["usage"]["output_tokens"],
        )
        for record in records
    )
    assert observed == [
        ("gpt-5.4-mini", 20, 10, 0, 5),
        ("gpt-5.4-mini", 20, 20, 0, 10),
        ("gpt-5.6-sol", 20, 40, 0, 10),
        ("gpt-5.6-sol", 50, 50, 0, 20),
        ("gpt-5.6-sol", 60, 40, 0, 10),
    ]


def test_bash_command_bucket_classification():
    m = _load_token_usage_report_module()
    cases = [
        ("git status", ("git", None)),
        ("gh pr view 12 --json state", ("git", None)),
        # && 串接：首段 cd 是導航 glue，取下一段主指令
        ("cd /Users/x/repo && git log --oneline -5", ("git", None)),
        # env 前綴要跳過
        ("TZ='Asia/Taipei' date '+%Y-%m-%d'", ("echo/shell glue", None)),
        ("bash scripts/deploy-zeabur-safe.sh", ("bash/.sh 腳本", None)),
        ("cd /repo && uv run pytest tests/test_x.py -q", ("pytest/測試", None)),
        # pipe：取第一段主指令（cat|jq 歸檔案系統，jq 開頭才歸查詢）
        ("cat storage/next_tasks.json | jq '.tasks'", ("ls/檔案系統", None)),
        ("jq '.tasks | length' storage/next_tasks.json", ("jq/grep/查詢", None)),
        ("grep -rn 'foo' src/ | head -5", ("jq/grep/查詢", None)),
        ("curl -s https://volpred.zeabur.app/api/health", ("curl/網路", None)),
        ("ls -la | head -20", ("ls/檔案系統", None)),
        ("timeout 600 git fetch origin", ("git", None)),
        ("", ("其他", None)),
        # 長命令：只看第一行第一段的指令詞
        ("git commit -m '" + "x" * 5000 + "'", ("git", None)),
    ]
    for cmd, expected in cases:
        assert m._bash_command_bucket(cmd) == expected, f"cmd={cmd[:60]!r}"


def test_bash_command_bucket_python_script_detail():
    m = _load_token_usage_report_module()
    assert m._bash_command_bucket("uv run python scripts/ops_snapshot.py") == (
        "uv run python", "scripts/ops_snapshot.py")
    # uv 帶 value flag（--extra dev）不可誤判子指令
    assert m._bash_command_bucket(
        "uv run --extra dev python scripts/daily_checkup.py --json") == (
        "uv run python", "scripts/daily_checkup.py")
    assert m._bash_command_bucket("python3 -c 'print(1)'") == ("uv run python", "(inline -c)")
    # heredoc：body 內的 && / | 不參與分類
    heredoc = "python3 - <<'EOF'\nimport os && bad | tokens\nEOF"
    assert m._bash_command_bucket(heredoc) == ("uv run python", "(heredoc/stdin)")
    assert m._bash_command_bucket("uv run volpred ops release-pool") == (
        "uv run python", "volpred")
    assert m._bash_command_bucket("python3 -m json.tool x.json") == (
        "uv run python", "(-m json.tool)")


def _bash_record(msg_id, session_id, ts, usage, commands, category="bash_other"):
    return {
        "timestamp": ts,
        "date": ts.date(),
        "session_id": session_id,
        "model": "claude-opus-5",
        "usage": usage,
        "category": category,
        "is_subagent": False,
        "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": c}}
            for c in commands
        ],
        "text_content": "",
        "msg_id": msg_id,
    }


def test_generate_drilldown_bash_commands_buckets_and_dedupe(monkeypatch):
    token_usage_report = _load_token_usage_report_module()
    target_day = date(2026, 7, 19)
    usage_m1 = {"input_tokens": 60, "output_tokens": 40,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 100}
    usage_m2 = {"input_tokens": 30, "output_tokens": 10,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 60}
    ts1 = datetime(2026, 7, 19, 1, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 7, 19, 2, 0, tzinfo=timezone.utc)
    records = [
        # 同一 turn 的兩個 block-record（同 msg_id、同 turn-total usage）→ 只計一次
        _bash_record("m1", "sess_a", ts1, usage_m1, ["git status"], category="git_sync"),
        _bash_record("m1", "sess_a", ts1, usage_m1, [], category="text_only"),
        # 一 turn 兩條指令 → token 均分
        _bash_record("m2", "sess_a", ts2, usage_m2,
                     ["uv run python scripts/ops_snapshot.py", "git push"],
                     category="git_sync"),
    ]
    monkeypatch.setattr(
        token_usage_report, "iter_session_records", lambda *a, **k: iter(records))

    drilldown = token_usage_report.generate_drilldown(target_day, target_day)
    bc = drilldown["bash_commands"]

    assert bc["turns"] == 2
    assert bc["commands"] == 3
    # io: m1=100（一次，不因兩個 block-record 重複計）+ m2=40 → 140
    assert bc["input_output_tokens"] == 140
    by_name = {row["name"]: row for row in bc["buckets"]}
    assert by_name["git"]["commands"] == 2
    assert by_name["git"]["turns"] == 2
    assert by_name["git"]["input_output_tokens"] == 120  # 100 + 40/2
    assert by_name["uv run python"]["input_output_tokens"] == 20  # 40/2
    assert abs(by_name["git"]["share_pct"] - 85.7) < 0.1
    assert bc["python_scripts_top"][0]["name"] == "scripts/ops_snapshot.py"
    assert bc["python_scripts_top"][0]["commands"] == 1


def test_daily_report_text_includes_bash_bucket_table(monkeypatch):
    token_usage_report = _load_token_usage_report_module()
    target_day = date(2026, 7, 19)
    ts = datetime(2026, 7, 19, 3, 0, tzinfo=timezone.utc)
    usage = {"input_tokens": 50, "output_tokens": 20,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 10}
    records = [
        _bash_record("m1", "sess_a", ts, usage, ["jq '.x' storage/next_tasks.json"]),
    ]
    monkeypatch.setattr(
        token_usage_report, "iter_session_records", lambda *a, **k: iter(records))

    report = token_usage_report.generate_daily_report(target_day)
    text = token_usage_report.format_report_text(report)

    assert "## Bash 指令大類（全部 Bash 呼叫）" in text
    assert "| jq/grep/查詢 | 1 | 70 | 100.0% |" in text
    assert "API 定價等值" in text
    assert "使用訂閱額度，非實際帳單" in text


def test_unknown_model_has_no_invented_api_price_equivalent():
    token_usage_report = _load_token_usage_report_module()
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_read_tokens": 1_000_000,
        "cache_create_tokens": 1_000_000,
    }

    assert token_usage_report.compute_cost_usd(usage, "gpt-unpriced") is None


def test_weekly_daily_breakdown_does_not_allocate_unknown_provider_cost(
    monkeypatch,
):
    token_usage_report = _load_token_usage_report_module()
    week_start = date(2026, 8, 2)

    def _record(day, provider, model, msg_id):
        return {
            "timestamp": datetime.combine(
                day,
                datetime.min.time(),
                tzinfo=timezone.utc,
            ),
            "date": day,
            "session_id": f"{provider}/{msg_id}",
            "provider": provider,
            "model": model,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            "category": "unclassified",
            "is_subagent": False,
            "content": [],
            "text_content": "",
            "msg_id": msg_id,
        }

    records = [
        _record(week_start, "claude", "claude-opus-5", "claude-turn"),
        _record(
            week_start.replace(day=3),
            "codex",
            "gpt-unpriced",
            "codex-turn",
        ),
    ]
    monkeypatch.setattr(
        token_usage_report,
        "iter_session_records",
        lambda *_args, **_kwargs: iter(records),
    )

    report = token_usage_report.generate_weekly_report(week_start)
    text = token_usage_report.format_report_text(report)

    assert report["by_model"]["gpt-unpriced"]["estimated_cost_usd"] is None
    assert all(
        "estimated_cost_usd" not in day
        for day in report["daily_breakdown"].values()
    )
    assert "Claude Code / Codex 真實記錄" in text
    assert "| 日期 | Messages | Billable Tokens |" in text


def _load_token_report_email_module():
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "token_report_email.py"
    spec = importlib.util.spec_from_file_location("token_report_email_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_email_html_includes_bash_bucket_table(monkeypatch):
    mod = _load_token_report_email_module()
    monkeypatch.setattr(mod, "_thinking_estimate", lambda week_range: {})
    week = {
        "totals": {"billable_total": 1000, "cache_read_tokens": 5},
        "by_provider": {
            "claude": {"billable_total": 600},
            "codex": {"billable_total": 400},
        },
        "week_range": "2026-07-19 → 2026-07-26",
        "daily_breakdown": {"2026-07-19": {"billable_total": 1000}},
        "by_category": {"git_sync": {"billable_total": 1000, "messages": 3}},
        "by_model": {
            "gpt-unpriced": {
                "billable_total": 400,
                "messages": 2,
                "estimated_cost_usd": None,
            }
        },
        "drilldown": {
            "bash_commands": {
                "turns": 2,
                "commands": 3,
                "input_output_tokens": 140,
                "billable_total": 300,
                "buckets": [
                    {"name": "git", "commands": 2, "turns": 2,
                     "input_output_tokens": 120, "billable_total": 250,
                     "share_pct": 85.7},
                    {"name": "uv run python", "commands": 1, "turns": 1,
                     "input_output_tokens": 20, "billable_total": 50,
                     "share_pct": 14.3},
                ],
                "python_scripts_top": [
                    {"name": "scripts/ops_snapshot.py", "commands": 1,
                     "input_output_tokens": 20},
                ],
            }
        },
    }
    today = {"totals": {"billable_total": 500}}
    now_tw = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)

    html_body, text_body = mod.build_html(today, week, now_tw)

    assert "當週 × Bash 指令大類" in html_body
    assert "scripts/ops_snapshot.py" in html_body
    assert "86%" in html_body or "85%" in html_body
    assert "Bash 指令大類前 3" in text_body
    assert "API 定價等值（非實付）" in html_body
    assert "Operations Core dispatch scratch" in html_body
    assert "Claude 本週累計已用" in html_body
    assert "600" in html_body
    assert "全 provider 本週 1,000 billable" in text_body
    assert "N/A" in html_body
    assert "API等值" in text_body
