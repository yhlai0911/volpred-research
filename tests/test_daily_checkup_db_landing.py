"""db_landing sub-check（data_freshness 維度）：DB 入庫驗證 + P1 修復單 actuator.

2026-07-20 boss 指令「抓完數據要確認資料庫已正確存入」的 regression gate：
- canonical（storage/paper_trading.json）vs Supabase 端 trade_date/row 收據比對
- DB 落後 → finding（>=3 個資料日 critical）+ 自動開 P1 修復單（附正式 recovery CLI）
- 對齊 → 安靜（零 finding、零 task）
- 重跑同一缺口 → 不重複開單（id 以 table+canonical 最新日 dedup）
- 遠端讀被封鎖（CI/test）→ 安靜 skip + stderr trace（no-silent-fallback）
"""

from __future__ import annotations

import datetime
import json
import types
from pathlib import Path

from scripts import daily_checkup


def _seed_canonical(tmp_path: Path) -> Path:
    storage = tmp_path / "storage"
    storage.mkdir(parents=True)
    (storage / "paper_trading.json").write_text(json.dumps({
        "_market_daily": {
            "2026-07-16": {}, "2026-07-17": {}, "2026-07-18": {}, "2026-07-20": {},
        },
        "stratA": {"entries": [{"trade_date": "2026-07-18"}, {"trade_date": "2026-07-20"}]},
        "stratB": {"entries": [{"trade_date": "2026-07-20"}]},
        # 已停更策略：latest 停在舊日期，不得計入最新日 row 數
        "stratOld": {"entries": [{"trade_date": "2026-06-01"}]},
    }))
    return storage


def _fake_ss():
    return types.SimpleNamespace(
        _remote_reads_blocked=lambda: False,
        SUPABASE_URL="http://fake.supabase.test",
        SUPABASE_KEY="test-key",
        HEADERS={},
    )


def _wire(monkeypatch, tmp_path: Path, probe_results: dict) -> None:
    storage = _seed_canonical(tmp_path)
    monkeypatch.setattr(daily_checkup, "STORAGE", storage)
    monkeypatch.setattr(daily_checkup, "_now", datetime.datetime(2026, 7, 20, 12, 0))
    monkeypatch.setattr(daily_checkup, "_supabase_mod", _fake_ss)
    monkeypatch.setattr(
        daily_checkup, "_db_landing_probe",
        lambda ss, table, date_col: probe_results[table])


def _tasks(tmp_path: Path) -> list[dict]:
    p = tmp_path / "storage" / "next_tasks.json"
    return json.loads(p.read_text()) if p.exists() else []


def test_db_lag_flags_critical_and_opens_p1_repair_task(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, {
        "market_daily": ("2026-07-16", 1),   # 落後 3 個資料日（07-17/18/20）→ critical
        "paper_trades": ("2026-07-20", 2),   # 對齊
    })

    findings = daily_checkup._db_landing_findings()

    assert len(findings) == 1
    f = findings[0]
    assert f["severity"] == "critical"
    assert "db_landing/market_daily" in f["message"]
    assert "落後 3 個資料日" in f["message"]
    assert "supabase_sync.py market-daily" in f["recovery"]
    assert "已開修復單 db_landing_repair_market_daily_2026-07-20" in f["message"]

    tasks = _tasks(tmp_path)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["id"] == "db_landing_repair_market_daily_2026-07-20"
    assert task["priority"] == 1
    assert task["status"] == "pending"
    assert task["source"] == "daily_checkup_db_landing"
    assert "supabase_sync.py market-daily" in task["description"]


def test_rerun_same_gap_does_not_duplicate_repair_task(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, {
        "market_daily": ("2026-07-18", 1),   # 落後 1 個資料日 → warn
        "paper_trades": ("2026-07-20", 2),
    })

    first = daily_checkup._db_landing_findings()
    second = daily_checkup._db_landing_findings()

    assert first[0]["severity"] == "warn"
    assert "已開修復單" in first[0]["message"]
    assert "修復單已存在" in second[0]["message"]
    assert len(_tasks(tmp_path)) == 1  # 同缺口不重複開單


def test_aligned_db_stays_quiet(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, {
        "market_daily": ("2026-07-20", 1),
        "paper_trades": ("2026-07-20", 2),
    })

    assert daily_checkup._db_landing_findings() == []
    assert _tasks(tmp_path) == []


def test_paper_trades_partial_landing_warns(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, {
        "market_daily": ("2026-07-20", 1),
        "paper_trades": ("2026-07-20", 1),   # DB 只落了 1/2 個策略 row
    })

    findings = daily_checkup._db_landing_findings()

    assert len(findings) == 1
    f = findings[0]
    assert f["severity"] == "warn"
    assert "db_landing/paper_trades" in f["message"]
    assert "入庫不完整" in f["message"]
    assert "DB 1 row < canonical 2 row" in f["message"]
    assert [t["id"] for t in _tasks(tmp_path)] == ["db_landing_repair_paper_trades_2026-07-20"]


def test_remote_reads_blocked_skips_with_stderr_trace(monkeypatch, tmp_path, capsys):
    # conftest 已設 VOLPRED_NO_REMOTE_READ=1 → 真 module 回報 blocked；
    # 不 monkeypatch _supabase_mod，走真實 import 路徑驗證 CI 行為。
    storage = _seed_canonical(tmp_path)
    monkeypatch.setattr(daily_checkup, "STORAGE", storage)

    assert daily_checkup._db_landing_findings() == []
    assert "remote reads blocked" in capsys.readouterr().err
    assert _tasks(tmp_path) == []


def test_missing_creds_is_a_visible_warn_not_a_silent_skip(monkeypatch, tmp_path):
    storage = _seed_canonical(tmp_path)
    monkeypatch.setattr(daily_checkup, "STORAGE", storage)
    ss = _fake_ss()
    ss.SUPABASE_KEY = None
    monkeypatch.setattr(daily_checkup, "_supabase_mod", lambda: ss)

    findings = daily_checkup._db_landing_findings()

    assert len(findings) == 1
    assert findings[0]["severity"] == "warn"
    assert "缺 Supabase 憑證" in findings[0]["message"]
