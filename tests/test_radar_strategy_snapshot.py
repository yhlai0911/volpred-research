"""
Tests for VolPred Radar P1 — daily strategy snapshot job + diff computation.

Covers:
  1. Snapshot job idempotency: rows already present for snapshot_date are skipped,
     only-new strategies are inserted, invalid weights are skipped.
  2. Diff computation correctness (mirror of strategy-diff/route.ts logic):
     added / removed / changed classification + CHANGE_THRESHOLD gate + no-prev case.

The snapshot job's Supabase access goes through a requests.Session; we inject a
fake session so no network / real DB is touched (seed fixed, deterministic).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JOB_PATH = REPO_ROOT / "scripts" / "radar_strategy_snapshot_daily.py"

CHANGE_THRESHOLD = 0.5  # must mirror strategy-diff/route.ts


def _load_job_module():
    spec = importlib.util.spec_from_file_location("radar_strategy_snapshot_daily", JOB_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


job = _load_job_module()


# ─────────────────────────────────────────────────────────────────────────────
# Fake Supabase REST session
# ─────────────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Simulates the strategy_signals / metrics / snapshot endpoints."""

    def __init__(self, active_strategies, metrics, existing_snapshot_ids):
        self._active = active_strategies
        self._metrics = metrics  # {strategy: metrics_blob}
        self._existing = set(existing_snapshot_ids)
        self.inserted: list[dict] = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        params = params or {}
        if job.SIGNALS_TABLE in url:
            return _Resp(self._active)
        if job.METRICS_TABLE in url:
            return _Resp([{"strategy": k, "metrics": v} for k, v in self._metrics.items()])
        if job.SNAPSHOT_TABLE in url:
            return _Resp([{"strategy_id": sid} for sid in self._existing])
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, params=None, headers=None, data=None, timeout=None):
        assert job.SNAPSHOT_TABLE in url
        rows = json.loads(data)
        # Simulate unique(snapshot_date, strategy_id): ignore-duplicates.
        accepted = [r for r in rows if r["strategy_id"] not in self._existing]
        self.inserted.extend(accepted)
        for r in accepted:
            self._existing.add(r["strategy_id"])
        return _Resp(accepted, status=201)


ACTIVE = [
    {"strategy_key": "slow_vt", "weights": {"SPY": 62}, "is_active": True},
    {"strategy_key": "recommended_5050", "weights": {"SPY": 34, "GLD": 34}, "is_active": True},
    {"strategy_key": "taiwan_8.63vix", "weights": {"0050.TW": 49}, "is_active": True},
    {"strategy_key": "broken", "weights": None, "is_active": True},  # invalid -> skip
]
METRICS = {
    "slow_vt": {"sharpe": 1.1, "max_drawdown": -12.0},
    "recommended_5050": {"sharpe": 0.9},
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Snapshot job idempotency
# ─────────────────────────────────────────────────────────────────────────────
def test_first_run_inserts_valid_strategies_only():
    sess = FakeSession(ACTIVE, METRICS, existing_snapshot_ids=[])
    existing = job.fetch_existing_for_date(sess, "http://x", "2026-06-14")
    assert existing == set()

    strategies = job.fetch_active_strategies(sess, "http://x")
    metrics = job.fetch_metrics(sess, "http://x")

    rows = []
    for s in strategies:
        sid = s.get("strategy_key")
        w = s.get("weights")
        if not sid or not isinstance(w, dict) or not w:
            continue
        if sid in existing:
            continue
        rows.append(
            {
                "snapshot_date": "2026-06-14",
                "strategy_id": sid,
                "weights": w,
                "metrics": metrics.get(sid),
            }
        )

    inserted = job.insert_snapshots(sess, "http://x", rows)
    # 3 valid (slow_vt, recommended_5050, taiwan_8.63vix); 'broken' skipped.
    assert inserted == 3
    inserted_ids = {r["strategy_id"] for r in sess.inserted}
    assert inserted_ids == {"slow_vt", "recommended_5050", "taiwan_8.63vix"}
    # metrics carried through when present, None otherwise.
    by_id = {r["strategy_id"]: r for r in sess.inserted}
    assert by_id["slow_vt"]["metrics"] == {"sharpe": 1.1, "max_drawdown": -12.0}
    assert by_id["taiwan_8.63vix"]["metrics"] is None


def test_rerun_same_day_is_idempotent():
    # All three already snapshotted for the date.
    sess = FakeSession(
        ACTIVE,
        METRICS,
        existing_snapshot_ids=["slow_vt", "recommended_5050", "taiwan_8.63vix"],
    )
    existing = job.fetch_existing_for_date(sess, "http://x", "2026-06-14")
    strategies = job.fetch_active_strategies(sess, "http://x")

    rows = []
    for s in strategies:
        sid = s.get("strategy_key")
        w = s.get("weights")
        if not sid or not isinstance(w, dict) or not w:
            continue
        if sid in existing:
            continue
        rows.append({"snapshot_date": "2026-06-14", "strategy_id": sid, "weights": w, "metrics": None})

    assert rows == []  # nothing new to insert
    inserted = job.insert_snapshots(sess, "http://x", rows)
    assert inserted == 0
    assert sess.inserted == []


def test_post_layer_dedup_guards_against_race():
    # Even if caller passes a dup (race between fetch_existing and post),
    # the unique constraint (simulated ignore-duplicates) drops it.
    sess = FakeSession(ACTIVE, METRICS, existing_snapshot_ids=["slow_vt"])
    rows = [
        {"snapshot_date": "2026-06-14", "strategy_id": "slow_vt", "weights": {"SPY": 62}, "metrics": None},
        {"snapshot_date": "2026-06-14", "strategy_id": "recommended_5050", "weights": {"SPY": 34, "GLD": 34}, "metrics": None},
    ]
    inserted = job.insert_snapshots(sess, "http://x", rows)
    assert inserted == 1  # slow_vt dropped as duplicate
    assert {r["strategy_id"] for r in sess.inserted} == {"recommended_5050"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Diff computation (Python mirror of strategy-diff/route.ts)
# ─────────────────────────────────────────────────────────────────────────────
def _compute_diffs(prev: dict, curr: dict) -> list[dict]:
    assets = set(prev) | set(curr)
    diffs = []
    for asset in assets:
        p = prev.get(asset, 0)
        c = curr.get(asset, 0)
        delta = c - p
        if abs(delta) <= CHANGE_THRESHOLD:
            continue
        kind = "added" if p == 0 else "removed" if c == 0 else "changed"
        diffs.append({"asset": asset, "prev": p, "curr": c, "delta": delta, "kind": kind})
    diffs.sort(key=lambda d: abs(d["delta"]), reverse=True)
    return diffs


def test_diff_changed_weight():
    diffs = _compute_diffs({"SPY": 62}, {"SPY": 68})
    assert len(diffs) == 1
    assert diffs[0] == {"asset": "SPY", "prev": 62, "curr": 68, "delta": 6, "kind": "changed"}


def test_diff_added_and_removed():
    # Previously SPY+GLD, now SPY-only (GLD removed) and added a new asset.
    diffs = _compute_diffs({"SPY": 34, "GLD": 34}, {"SPY": 34, "TLT": 20})
    by_asset = {d["asset"]: d for d in diffs}
    assert "SPY" not in by_asset  # unchanged -> excluded
    assert by_asset["GLD"]["kind"] == "removed"
    assert by_asset["GLD"]["curr"] == 0
    assert by_asset["TLT"]["kind"] == "added"
    assert by_asset["TLT"]["prev"] == 0


def test_diff_threshold_filters_noise():
    # 0.3pp move is below CHANGE_THRESHOLD (0.5) -> not reported.
    diffs = _compute_diffs({"SPY": 62.0}, {"SPY": 62.3})
    assert diffs == []


def test_diff_no_change():
    diffs = _compute_diffs({"SPY": 34, "GLD": 34}, {"SPY": 34, "GLD": 34})
    assert diffs == []


def test_diff_sorted_by_magnitude():
    diffs = _compute_diffs({"SPY": 50, "GLD": 50}, {"SPY": 70, "GLD": 45})
    # SPY delta +20, GLD delta -5 -> SPY first.
    assert [d["asset"] for d in diffs] == ["SPY", "GLD"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
