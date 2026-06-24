from __future__ import annotations

import json
import os
import time
from collections import namedtuple
from pathlib import Path

import pytest

from volpred.ops import health
from volpred.ops.alerts import build_alert_condition_report
from volpred.ops.health import (
    check_disk_usage,
    check_paper_trading_gaps,
    check_strategy_metrics_freshness,
    health_snapshot,
)

_DiskUsage = namedtuple("_DiskUsage", ["total", "used", "free"])


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# strategy_metrics_freshness
# --------------------------------------------------------------------------- #
def test_strategy_metrics_fresh_is_ok(tmp_path: Path):
    storage = tmp_path / "storage"
    _write_json(storage / "strategy_metrics.json", {"x": 1})
    result = check_strategy_metrics_freshness(str(storage))
    assert result["status"] == "ok"
    assert result["exists"] is True
    assert result["age_hours"] is not None and result["age_hours"] < 26


def test_strategy_metrics_stale_when_old(tmp_path: Path):
    storage = tmp_path / "storage"
    path = storage / "strategy_metrics.json"
    _write_json(path, {"x": 1})
    old = time.time() - 30 * 3600  # 30h ago > 26h threshold
    os.utime(path, (old, old))
    result = check_strategy_metrics_freshness(str(storage))
    assert result["status"] == "stale"
    assert result["age_hours"] > 26


def test_strategy_metrics_stale_when_missing(tmp_path: Path):
    storage = tmp_path / "storage"
    storage.mkdir(parents=True)
    result = check_strategy_metrics_freshness(str(storage))
    assert result["status"] == "stale"
    assert result["exists"] is False


# --------------------------------------------------------------------------- #
# paper_trading_gaps
# --------------------------------------------------------------------------- #
def test_paper_trading_one_null_is_ok(tmp_path: Path):
    storage = tmp_path / "storage"
    _write_json(
        storage / "paper_trading.json",
        {
            "slow_vt": {
                "entries": [
                    {"portfolio_return": 0.01},
                    {"portfolio_return": -0.02},
                    {"portfolio_return": None},  # weekend lag, normal
                ]
            }
        },
    )
    result = check_paper_trading_gaps(str(storage))
    assert result["status"] == "ok"
    assert result["gap_strategies"] == []


def test_paper_trading_three_nulls_is_gap(tmp_path: Path):
    storage = tmp_path / "storage"
    _write_json(
        storage / "paper_trading.json",
        {
            "slow_vt": {
                "entries": [
                    {"portfolio_return": None},
                    {"portfolio_return": None},
                    {"portfolio_return": None},
                ]
            },
            "risk_parity": {
                "entries": [
                    {"portfolio_return": 0.01},
                    {"portfolio_return": 0.02},
                    {"portfolio_return": None},
                ]
            },
        },
    )
    result = check_paper_trading_gaps(str(storage))
    assert result["status"] == "gap"
    names = {g["strategy"]: g["null_count"] for g in result["gap_strategies"]}
    assert names == {"slow_vt": 3}  # only slow_vt breaches >2


# --------------------------------------------------------------------------- #
# disk_usage
# --------------------------------------------------------------------------- #
def test_disk_usage_alert_when_high(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = tmp_path / "storage"
    storage.mkdir(parents=True)
    monkeypatch.setattr(
        health.shutil, "disk_usage", lambda _p: _DiskUsage(total=100, used=90, free=10)
    )
    result = check_disk_usage(str(storage))
    assert result["status"] == "alert"
    assert result["pct"] == 90.0


def test_disk_usage_ok_when_low(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = tmp_path / "storage"
    storage.mkdir(parents=True)
    monkeypatch.setattr(
        health.shutil, "disk_usage", lambda _p: _DiskUsage(total=100, used=50, free=50)
    )
    result = check_disk_usage(str(storage))
    assert result["status"] == "ok"
    assert result["pct"] == 50.0


# --------------------------------------------------------------------------- #
# health_snapshot integration
# --------------------------------------------------------------------------- #
def test_health_snapshot_includes_three_new_checks(tmp_path: Path):
    storage = tmp_path / "storage"
    _write_json(storage / "reports" / "feed.json", [])
    _write_json(storage / "memory" / "open_questions.json", [])
    _write_json(storage / "paper_trading.json", {})
    _write_json(storage / "strategy_metrics.json", {"x": 1})
    snapshot = health_snapshot(storage_dir=str(storage))
    assert "strategy_metrics_freshness" in snapshot
    assert "paper_trading_gaps" in snapshot
    assert "disk_usage" in snapshot
    assert snapshot["strategy_metrics_freshness"]["status"] == "ok"
    assert snapshot["paper_trading_gaps"]["status"] == "ok"
    assert snapshot["disk_usage"]["status"] in {"ok", "alert", "unknown"}


# --------------------------------------------------------------------------- #
# alert chain integration
# --------------------------------------------------------------------------- #
def test_alert_chain_surfaces_new_breaches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = tmp_path / "storage"
    # strategy_metrics: stale (old mtime)
    sm = storage / "strategy_metrics.json"
    _write_json(sm, {"x": 1})
    old = time.time() - 30 * 3600
    os.utime(sm, (old, old))
    # paper_trading: gap (3 nulls)
    _write_json(
        storage / "paper_trading.json",
        {"slow_vt": {"entries": [{"portfolio_return": None}] * 3}},
    )
    # disk: force alert
    monkeypatch.setattr(
        health.shutil, "disk_usage", lambda _p: _DiskUsage(total=100, used=95, free=5)
    )

    report = build_alert_condition_report(storage_dir=str(storage))
    by_id = {c["id"]: c for c in report["conditions"]}

    assert by_id["strategy_metrics_freshness"]["breached"] is True
    assert by_id["strategy_metrics_freshness"]["level"] == "warn"
    assert by_id["paper_trading_gaps"]["breached"] is True
    assert by_id["disk_usage"]["breached"] is True
    # breached conditions carry a non-empty 3-section body for the email
    for cid in ("strategy_metrics_freshness", "paper_trading_gaps", "disk_usage"):
        assert "## 觸發條件" in by_id[cid]["body"]
        assert "## 影響" in by_id[cid]["body"]
        assert "## 建議行動" in by_id[cid]["body"]


def test_alert_chain_healthy_no_breach(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = tmp_path / "storage"
    _write_json(storage / "strategy_metrics.json", {"x": 1})  # fresh
    _write_json(
        storage / "paper_trading.json",
        {"slow_vt": {"entries": [{"portfolio_return": 0.01}] * 3}},
    )
    monkeypatch.setattr(
        health.shutil, "disk_usage", lambda _p: _DiskUsage(total=100, used=40, free=60)
    )
    report = build_alert_condition_report(storage_dir=str(storage))
    by_id = {c["id"]: c for c in report["conditions"]}
    assert by_id["strategy_metrics_freshness"]["breached"] is False
    assert by_id["paper_trading_gaps"]["breached"] is False
    assert by_id["disk_usage"]["breached"] is False
