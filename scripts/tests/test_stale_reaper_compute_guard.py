"""stale reaper 不得回收「工作還在 compute queue 上飛」的 task。

事故（2026-07-21，error_log Class A）：`task_pool_claim.py cleanup` 只用 claimed_at
年齡判 stale，看不見 compute queue。長研究 job timeout 5400s 遠超 --stale-hours 2
→ dispatch 出去的 task 每 2h 被 flip 回 pending、重進 starvation lockout 被二度派工
（assign_5aa9d5f5 連兩次 auto_release_stale_2h，agent job 全程正常執行）。

這裡鎖住 guard 的四個行為，含兩個 fail-open 方向 —— guard 擋太多會把 task 永久釘死，
比不擋更糟。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "task_pool_claim.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tpc_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def tpc(tmp_path, monkeypatch):
    mod = _load_module()
    monkeypatch.setattr(mod, "_COMPUTE_QUEUE_DIR", tmp_path)
    return mod


def _write_job(dirpath: Path, job_id: str, status: str) -> None:
    (dirpath / f"{job_id}.json").write_text(
        json.dumps({"id": job_id, "status": status}), encoding="utf-8"
    )


@pytest.mark.parametrize("status", ["pending", "queued", "running", "claimed"])
def test_live_job_blocks_release(tpc, tmp_path, status):
    """job 還在飛 → guard 必須擋下回收。這是事故本體。"""
    _write_job(tmp_path, "job-live", status)
    assert tpc._compute_job_alive("job-live") is True


@pytest.mark.parametrize("status", ["completed", "failed", "timeout", "cancelled"])
def test_terminal_job_allows_release(tpc, tmp_path, status):
    """job 已進終態 → task 本來就該回池等收件，不可被 guard 永久釘住。"""
    _write_job(tmp_path, "job-done", status)
    assert tpc._compute_job_alive("job-done") is False


def test_missing_job_file_allows_release(tpc):
    """job 檔讀不到 = 無法證明它活著 → fail-open 照常回收，不因 IO 錯誤釘死 task。"""
    assert tpc._compute_job_alive("no-such-job") is False


def test_no_compute_job_id_allows_release(tpc):
    """絕大多數 task 沒有 compute_job_id → guard 必須完全不影響它們。"""
    assert tpc._compute_job_alive(None) is False
    assert tpc._compute_job_alive("") is False
