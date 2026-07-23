from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cron_review.py"
SPEC = importlib.util.spec_from_file_location("cron_review_module", MODULE_PATH)
assert SPEC and SPEC.loader
cron_review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cron_review)

TPE = cron_review.TPE
expected_prev_fire = cron_review.expected_prev_fire
is_stale = cron_review.is_stale
last_log_run = cron_review.last_log_run


def test_last_log_run_returns_mtime_when_completion_marker_not_banner(tmp_path):
    """collect_tw 假 stale regression（2026-05-29）：完成標記 `✓ 台股數據收集完成`
    不是 ===exit/end banner，banner parser 抓不到 end；log-mtime 必須回傳，
    供 main() override 過舊的 banner/piggy-back end，消除假 30h stale。"""
    log = tmp_path / "collect_tw.log"
    log.write_text(
        "=== 台股數據收集: 2026-05-29 15:00 ===\n"
        "  0050.TW: 2026-05-29 close=105.40 (1552 rows)\n"
        "✓ 台股數據收集完成\n",
        encoding="utf-8",
    )
    res = last_log_run(log)
    # 完成標記非 banner → banner end 抓不到，但 mtime 必在且為近期
    assert res.get("mtime") is not None
    assert res["mtime"].tzinfo is not None  # tz-aware TPE
    # mtime 應約等於剛寫入的當下（寬鬆 24h 容差，跨時區安全）
    now = datetime.now(TPE)
    assert abs((now - res["mtime"]).total_seconds()) < 86400


def test_last_log_run_warns_when_mtime_stat_fails(capsys):
    class UnstatableLog:
        def __init__(self) -> None:
            self.path = Path("/tmp/unstatable-cron.log")

        def exists(self) -> bool:
            return True

        def read_text(self, errors: str = "ignore") -> str:
            return "=== job start 2026-06-23 00:00:00 ===\n"

        def stat(self):
            raise OSError("stat denied")

        def __str__(self) -> str:
            return str(self.path)

    res = last_log_run(UnstatableLog())  # type: ignore[arg-type]

    err = capsys.readouterr().err
    assert "[cron_review] WARN log mtime stat failed; continuing without mtime fallback" in err
    assert "stat denied" in err
    assert res["mtime"] is None
    assert res["start"] == datetime(2026, 6, 23, 0, 0, tzinfo=TPE)


def test_piggy_back_end_warns_when_state_read_fails(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "cron_last_run.json"
    state_path.write_text("{bad-json", encoding="utf-8")
    monkeypatch.setattr(cron_review, "LAST_RUN_PATH", state_path)

    end = cron_review._piggy_back_end("release_pool")

    err = capsys.readouterr().err
    assert end is None
    # WS-D1: marker loading delegates to the canonical reader in
    # volpred.ops.schedules — the warn is emitted by that single owner now.
    assert "[schedules] WARN cron_last_run read failed" in err
    assert str(state_path) in err


def test_piggy_back_end_warns_when_timestamp_parse_fails(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "cron_last_run.json"
    state_path.write_text(json.dumps({"release_pool": "not-a-timestamp"}), encoding="utf-8")
    monkeypatch.setattr(cron_review, "LAST_RUN_PATH", state_path)

    end = cron_review._piggy_back_end("release_pool")

    err = capsys.readouterr().err
    assert end is None
    assert "[cron_review] WARN piggy-back timestamp parse failed for job_id=release_pool" in err
    assert "not-a-timestamp" in err


def test_expected_prev_fire_respects_weekday_restricted_collect_us_cron():
    now = datetime(2026, 5, 25, 22, 0, tzinfo=TPE)  # Sunday night Taipei
    prev_fire = expected_prev_fire(now, "3 7 * * 2-6")

    assert prev_fire is not None
    assert prev_fire == datetime(2026, 5, 23, 7, 3, tzinfo=TPE)  # Saturday


def test_expected_prev_fire_warns_when_cron_expr_invalid(capsys):
    now = datetime(2026, 5, 25, 22, 0, tzinfo=TPE)

    prev_fire = expected_prev_fire(now, "not a cron")

    assert prev_fire is None
    err = capsys.readouterr().err
    assert "[cron_review] WARN cron schedule evaluation failed; using max-gap fallback" in err
    assert "cron_expr='not a cron'" in err


def test_git_commits_since_warns_when_git_scan_fails(monkeypatch, capsys):
    def fail_run(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(cron_review.subprocess, "run", fail_run)

    commits = cron_review.git_commits_since(75)

    err = capsys.readouterr().err
    assert commits == []
    assert "[cron_review] WARN git commit scan failed; treating recent commit list as empty" in err
    assert "OSError: git unavailable" in err


def test_is_stale_does_not_false_alarm_on_weekend_gap_for_collect_us():
    now = datetime(2026, 5, 25, 22, 0, tzinfo=TPE)  # Sunday night Taipei
    last_end = datetime(2026, 5, 23, 8, 0, tzinfo=TPE)  # Saturday after run

    stale, flag = is_stale(
        now=now,
        last_end=last_end,
        cron_expr="3 7 * * 2-6",
        fallback_max_gap_h=30,
    )

    assert stale is False
    assert flag is None


def test_is_stale_flags_when_missing_expected_weekday_fire():
    now = datetime(2026, 5, 26, 12, 0, tzinfo=TPE)  # Tuesday noon
    last_end = datetime(2026, 5, 23, 8, 0, tzinfo=TPE)  # still last Saturday

    stale, flag = is_stale(
        now=now,
        last_end=last_end,
        cron_expr="3 7 * * 2-6",
        fallback_max_gap_h=30,
    )

    assert stale is True
    assert flag is not None


# --- dispatch-supervisor state regression (email-11870, 2026-07-08) -----------
# 7/4 cutover 把 hourly dispatch 從 LaunchAgent `com.volpred.hourly-dispatch` 換成
# 常駐 daemon。cron_review v-pre 仍讀死掉的 label + 停更的 hourly_dispatch.log
# (cutover 後 mtime 凍結) → 對健康的 daemon 永遠報 80h+ 假 stale 紅色告警，老闆收到
# boss report 誤以為 dispatch 掛了。修正：hourly_dispatch 改讀 dispatch_state.json。

dispatch_supervisor_state = cron_review.dispatch_supervisor_state


def _write_state(tmp_path, monkeypatch, payload, *, daemon_running=True):
    state_file = tmp_path / "dispatch_state.json"
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cron_review, "DISPATCH_STATE_PATH", state_file)
    monkeypatch.setattr(
        cron_review, "launchctl_state",
        lambda label: {"runs": 1, "last_exit": "(never exited)",
                       "running": daemon_running},
    )
    return state_file


def _iso_minutes_ago(minutes: int) -> str:
    """main() 用真實 `datetime.now(TPE)`，所以「新鮮完成班」得相對真實 now 產生。"""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def test_dispatch_supervisor_healthy_no_false_stale(tmp_path, monkeypatch):
    """核心 regression：daemon 活著 + 近期成功完成班 → 不得報 stale。"""
    now = datetime(2026, 7, 8, 1, 35, tzinfo=TPE)
    _write_state(tmp_path, monkeypatch, {
        "current_job": {"pid": 123},  # 本班正在跑
        "completions": [
            {"completed_at": "2026-07-07T17:11:50.714155+00:00", "exit_code": 0},
        ],
    })
    ds = dispatch_supervisor_state(now)
    assert ds["daemon_alive"] is True
    assert ds["running"] is True
    assert ds["last_exit"] == "0"
    assert ds["end"] is not None  # 從 completions[] 末筆抓到，非 None
    # 01:11 完成 → 相對 01:35 gap 極小，is_stale 不觸發
    stale, _ = is_stale(now=now, last_end=ds["end"], cron_expr="7 * * * *",
                        fallback_max_gap_h=2)
    assert stale is False


def test_dispatch_supervisor_reads_last_entry_of_completions(tmp_path, monkeypatch):
    """契約：`completions[]` 是 append-only ring buffer，末筆就是最後完成班 —
    `end` 與 `last_exit` 都只從末筆取，不看前面任何一筆（唯一 writer 是
    `state.record_completion()`）。"""
    now = datetime(2026, 7, 8, 1, 35, tzinfo=TPE)
    _write_state(tmp_path, monkeypatch, {
        "current_job": None,
        "completions": [
            {"completed_at": "2026-07-07T15:11:00+00:00", "exit_code": 0},
            {"completed_at": "2026-07-07T16:11:00+00:00", "exit_code": 0},
            {"completed_at": "2026-07-07T17:11:50+00:00", "exit_code": 1},  # 末筆
        ],
    })
    ds = dispatch_supervisor_state(now)
    # 末筆 17:11 UTC = 01:11 TPE (7/8)，不是首筆也不是中間筆
    assert (ds["end"].day, ds["end"].hour, ds["end"].minute) == (8, 1, 11)
    # exit_code 同樣取末筆 → main() 會標 🔴 last exit 1（不被前面的 0 蓋掉）
    assert ds["last_exit"] == "1"


def test_dispatch_supervisor_no_completions_yet(tmp_path, monkeypatch):
    """空 buffer（daemon 剛起、尚無完成班）→ end/last_exit 皆 None，不得 crash。"""
    now = datetime(2026, 7, 8, 1, 35, tzinfo=TPE)
    _write_state(tmp_path, monkeypatch, {"current_job": None, "completions": []})
    ds = dispatch_supervisor_state(now)
    assert ds["end"] is None and ds["last_exit"] is None
    assert ds["daemon_alive"] is True and ds["error"] is None


def test_dispatch_supervisor_daemon_down_flags(tmp_path, monkeypatch):
    now = datetime(2026, 7, 8, 1, 35, tzinfo=TPE)
    _write_state(tmp_path, monkeypatch, {
        "current_job": None,
        "completions": [
            {"completed_at": "2026-07-07T17:11:50+00:00", "exit_code": 0},
        ],
    }, daemon_running=False)
    ds = dispatch_supervisor_state(now)
    assert ds["daemon_alive"] is False  # main() 會據此標 🔴 daemon DOWN


def test_dispatch_supervisor_truly_stale_still_flagged(tmp_path, monkeypatch):
    """反向保護：daemon 活著但最後完成班在 5h 前且無 current_job → 真 stale 必報，
    確認修正沒把監控關成永遠綠燈。"""
    now = datetime(2026, 7, 8, 6, 0, tzinfo=TPE)
    _write_state(tmp_path, monkeypatch, {
        "current_job": None,
        "completions": [
            {"completed_at": "2026-07-07T17:11:50+00:00", "exit_code": 0},  # 01:11 TPE, ~5h 前
        ],
    })
    ds = dispatch_supervisor_state(now)
    assert ds["running"] is False
    stale, flag = is_stale(now=now, last_end=ds["end"], cron_expr="7 * * * *",
                           fallback_max_gap_h=2)
    assert stale is True and flag is not None


def _run_main_for_hourly_dispatch(monkeypatch, capsys) -> tuple[str, str]:
    """只跑 hourly_dispatch 這一列的 main()，回傳 (該列, 完整 stdout)。

    stale 在該列印 ⚠️ 旗標，同時把該 job 推進尾段的「🔴 需要掌握/處理」清單 —
    兩個 surface 都要驗，才是老闆真正會看到的東西。
    """
    monkeypatch.setattr(cron_review, "JOBS", {
        "hourly_dispatch": cron_review.JOBS["hourly_dispatch"],
    })
    monkeypatch.setattr(cron_review, "git_commits_since", lambda minutes=75: [])
    assert cron_review.main() == 0
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if ln.startswith("  hourly_dispatch"))
    return line, out


def test_main_running_job_never_judged_stale(tmp_path, monkeypatch, capsys):
    """email-11870 事故的端到端 gate：`current_job` 非 null 代表本班正在跑，此時
    `completions[-1]` 必然是「上一班」— 即使它舊到 is_stale 會觸發，main() 也不得
    報 stale。stale 判定唯一的守門條件就是 `running`，這條測試釘死它。"""
    _write_state(tmp_path, monkeypatch, {
        "current_job": {"pid": 123, "schedule_id": "hourly_dispatch"},
        "completions": [
            # 相對「現在」極舊：單看 completions[-1] 一定 stale
            {"completed_at": "2020-01-01T00:00:00+00:00", "exit_code": 0},
        ],
    })
    line, out = _run_main_for_hourly_dispatch(monkeypatch, capsys)
    assert "daemon=alive" in line and "running" in line
    assert "⚠️" not in line and "🔴" not in line  # 正在跑 → 該列不得有任何旗標
    assert "🔴 需要掌握/處理" not in out       # 也不得進告警清單
    assert "✅" in out


def test_main_idle_and_stale_still_flags(tmp_path, monkeypatch, capsys):
    """反向保護：同樣極舊的 completions[-1]，但 `current_job` 為 null（沒在跑）→
    必須報 stale 並進「🔴 需要掌握/處理」。證明上一條的綠燈來自 running gate，
    不是監控被關成永遠綠燈。"""
    _write_state(tmp_path, monkeypatch, {
        "current_job": None,
        "completions": [
            {"completed_at": "2020-01-01T00:00:00+00:00", "exit_code": 0},
        ],
    })
    line, out = _run_main_for_hourly_dispatch(monkeypatch, capsys)
    assert "idle" in line and "⚠️" in line
    assert "🔴 需要掌握/處理" in out
    assert "hourly_dispatch" in out.split("🔴 需要掌握/處理")[1]


def test_main_daemon_down_flags_red(tmp_path, monkeypatch, capsys):
    """daemon 不在 launchctl → 該列 🔴 + 進告警清單，即使完成班很新。"""
    _write_state(tmp_path, monkeypatch, {
        "current_job": None,
        "completions": [
            {"completed_at": _iso_minutes_ago(5), "exit_code": 0},
        ],
    }, daemon_running=False)
    line, out = _run_main_for_hourly_dispatch(monkeypatch, capsys)
    assert "daemon=DOWN" in line and "🔴" in line
    assert "🔴 需要掌握/處理" in out
