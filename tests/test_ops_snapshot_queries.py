"""Fixture tests for scripts/ops_snapshot.py structured sub-queries (ops-master G2).

Each sub-query gets (a) a correctness fixture test and (b) an output-size
assertion (<2KB serialized) so the instrument itself can never become a token
blackhole. Pure-python readers only — no jq subprocess anywhere in the module.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIZE_CAP = 2048  # bytes per sub-query payload (G2 hard gate)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "ops_snapshot", ROOT / "scripts" / "ops_snapshot.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


MOD = _load_module()


def _size_ok(payload: dict) -> int:
    raw = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    assert raw < SIZE_CAP, f"sub-query payload {raw}B exceeds {SIZE_CAP}B cap"
    return raw


# ── --task ───────────────────────────────────────────────────────────────────
@pytest.fixture()
def tasks_file(tmp_path: Path) -> Path:
    tasks = [
        {
            "id": "K999_article",
            "title": "K999: write article",
            "status": "pending",
            "priority": 1,
            "task_type": "daily_article",
            "dispatch_lane": "agent",
            "created_at": "2026-07-19T01:00:00+00:00",
        },
        {
            "id": "platform_ops_fix_cron",
            "title": "fix cron wrapper",
            "status": "in_progress",
            "priority": 2,
            "task_type": "platform_ops",
            "claimed_by": "slot-1-abc",
            "result": "x" * 500,  # must be clipped to 200
            "created_at": "2026-07-19T02:00:00+00:00",
        },
        {
            "id": "old_done",
            "title": "done thing",
            "status": "succeeded",
            "priority": 3,
            "task_type": "governance",
            "tombstone": True,
        },
    ]
    p = tmp_path / "next_tasks.json"
    p.write_text(json.dumps(tasks))
    return p


def test_task_query_exact_id(tasks_file: Path):
    out = MOD.task_query("K999_article", path=tasks_file)
    assert out["matched"] == 1
    row = out["tasks"][0]
    assert row["status"] == "pending"
    assert row["lane"] == "agent"
    assert "result" not in row  # absent field stays absent, not null-padded
    _size_ok(out)


def test_task_query_substring_and_result_clip(tasks_file: Path):
    out = MOD.task_query("cron", path=tasks_file)
    assert out["matched"] == 1
    row = out["tasks"][0]
    assert row["claimed_by"] == "slot-1-abc"
    assert len(row["result"]) <= 200
    _size_ok(out)


def test_task_query_no_content_dump(tasks_file: Path):
    out = MOD.task_query("K999", path=tasks_file)
    assert out["matched"] == 1
    _size_ok(out)


# ── --article ────────────────────────────────────────────────────────────────
@pytest.fixture()
def feed_file(tmp_path: Path) -> Path:
    articles = [
        {
            "id": "mile_aaa111",
            "title": "GJR beats GARCH",
            "status": "published",
            "published_at": "2026-07-01T00:00:00+00:00",
            "audience": "research",
            "content": "SECRET_BULK_CONTENT " * 500,
            "details": {"slug": "gjr-beats-garch"},
        },
        {
            "id": "mile_bbb222",
            "title": "VIX myth lab",
            "status": "draft",
            "published_at": None,
            "audience": "general",
            "content": "MORE_BULK " * 500,
        },
    ]
    p = tmp_path / "feed.json"
    p.write_text(json.dumps(articles))
    return p


def test_article_query_by_id_excludes_content(feed_file: Path):
    out = MOD.article_query("mile_aaa111", path=feed_file)
    assert out["matched"] == 1
    art = out["articles"][0]
    assert art["audience"] == "research"
    assert "content" not in art
    assert "SECRET_BULK_CONTENT" not in json.dumps(out)
    _size_ok(out)


def test_article_query_by_slug(feed_file: Path):
    out = MOD.article_query("gjr-beats", path=feed_file)
    assert out["matched"] == 1
    assert out["articles"][0]["id"] == "mile_aaa111"
    _size_ok(out)


def test_article_query_title_fallback(feed_file: Path):
    out = MOD.article_query("myth lab", path=feed_file)
    assert out["matched"] == 1
    assert out["articles"][0]["status"] == "draft"
    _size_ok(out)


# ── --job ────────────────────────────────────────────────────────────────────
@pytest.fixture()
def schedule_env(tmp_path: Path) -> tuple[dict, Path]:
    log = tmp_path / "storage" / "logs" / "cron" / "demo_job.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        "starting...\n=== [demo_job] exit 0 at 2026-07-20T08:00:00+0800 (duration=12s) ===\n"
    )
    config = {
        "system_crontab": {
            "items": [
                {
                    "id": "demo_job",
                    "cron": "0 8 * * *",
                    "label": "demo",
                    "log_path": "storage/logs/cron/demo_job.log",
                    "host_crontab_managed": False,
                }
            ]
        }
    }
    return config, tmp_path


def test_job_query_spec_and_liveness(schedule_env):
    config, root = schedule_env
    out = MOD.job_query("demo_job", config=config, marker_state={}, repo_root=root)
    assert out["matched"] == 1
    assert out["spec"]["cron"] == "0 8 * * *"
    # D1 single-source: exit-0 banner in the execution log is success evidence
    # even for a managed=False job with no piggyback marker.
    assert out["liveness"]["success_source"] == "log_banner"
    assert out["liveness"]["last_success"].startswith("2026-07-20T00:00:00")
    assert out["liveness"]["marker_eligible"] is False
    _size_ok(out)


def test_job_query_miss_is_explicit(schedule_env):
    config, root = schedule_env
    out = MOD.job_query("no_such_job", config=config, marker_state={}, repo_root=root)
    assert out == {"query": "no_such_job", "matched": 0}
    _size_ok(out)


# ── --worktrees ──────────────────────────────────────────────────────────────
def _git(args: list[str], cwd: Path, env: dict) -> None:
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def test_worktrees_query_hermetic_repo(tmp_path: Path):
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo, env)
    (repo / "a.txt").write_text("a")
    _git(["add", "a.txt"], repo, env)
    _git(["commit", "-m", "init"], repo, env)
    wt = tmp_path / "wt1"
    _git(["worktree", "add", "-b", "worktree-wt1", str(wt)], repo, env)
    (wt / "b.txt").write_text("b")
    _git(["add", "b.txt"], wt, env)
    _git(["commit", "-m", "wt work"], wt, env)
    (wt / "dirty.txt").write_text("uncommitted")

    out = MOD.worktrees_query(repo_root=repo)
    assert out["n"] == 1
    row = out["worktrees"][0]
    assert row["name"] == "wt1"
    assert "branch" not in row  # worktree-<name> convention elided for compactness
    assert row["unmerged"] == 1
    assert row["dirty"] == 1
    assert row["age_h"] is not None
    _size_ok(out)


# ── --receipts ───────────────────────────────────────────────────────────────
@pytest.fixture()
def dispatch_state_file(tmp_path: Path) -> Path:
    comps = [
        {
            "completed_at": f"2026-07-20T0{i}:00:00+00:00",
            "job_id": f"jobid{i:03d}deadbeef",
            "slot_id": 1 + (i % 2),
            "fire_reason": "cron" if i % 2 else "requested:user:assign_x",
            "exit_code": 0,
            "outcome": "success",
            "duration_s": 100.0 + i,
            "final_model": "claude-opus-4-8",
            "noise_field": "Z" * 300,  # must NOT leak into output
        }
        for i in range(8)
    ]
    p = tmp_path / "dispatch_state.json"
    p.write_text(json.dumps({"completions": comps}))
    return p


def test_receipts_query_tail_and_projection(dispatch_state_file: Path):
    out = MOD.receipts_query(3, path=dispatch_state_file)
    assert out["total"] == 8
    assert out["shown"] == 3
    assert [r["job"] for r in out["receipts"]] == ["jobid005", "jobid006", "jobid007"]
    assert "noise_field" not in json.dumps(out)
    _size_ok(out)


def test_receipts_query_n_is_capped(dispatch_state_file: Path):
    out = MOD.receipts_query(999, path=dispatch_state_file)
    assert out["shown"] == 8  # only 8 exist; cap logic must not error
    _size_ok(out)


# ── --queue ──────────────────────────────────────────────────────────────────
@pytest.fixture()
def queue_file(tmp_path: Path) -> Path:
    tasks = [
        {
            "id": f"t{i}",
            "title": f"task {i} " + "pad" * 30,
            "status": "pending" if i < 6 else "in_progress",
            "priority": (i % 3) + 1,
            "task_type": "experiment" if i % 2 else "platform_ops",
            "created_at": f"2026-07-{10 + i}T00:00:00+00:00",
        }
        for i in range(8)
    ]
    p = tmp_path / "next_tasks.json"
    p.write_text(json.dumps(tasks))
    return p


def test_queue_query_filters_and_counts(queue_file: Path):
    out = MOD.queue_query("pending", "experiment", 10, path=queue_file)
    assert out["matched"] == 3
    assert out["counts"]["pending"] == 6
    assert "top_pending" not in out["counts"]  # deduped against tasks list
    assert all("result" not in r and "status" not in r for r in out["tasks"])
    # priority-sorted ascending
    prios = [r["priority"] for r in out["tasks"]]
    assert prios == sorted(prios)
    _size_ok(out)


def test_queue_query_limit(queue_file: Path):
    out = MOD.queue_query(None, None, 2, path=queue_file)
    assert out["filter"]["status"] == "pending"
    assert out["matched"] == 6
    assert len(out["tasks"]) == 2
    _size_ok(out)
