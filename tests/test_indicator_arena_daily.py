"""
Tests for scripts/indicator_arena_daily.py (task indicator_arena_phase1d_cron_job_2026_06_11).

Gate requirements:
  1. Idempotency — same indicator + target_date already signalled -> skip, no
     duplicate append (run twice, row counts unchanged).
  2. Ex-ante guard — a draft with as_of_ts > now is rejected (Lookahead) and
     recorded as a failure, never written.
  3. Failure isolation — one indicator's data source failing does not block
     the others; run summary reflects partial success (ok=False).

All network access is mocked via fetch_fn injection; Supabase sync disabled.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "indicator_arena_daily", PROJECT_ROOT / "scripts" / "indicator_arena_daily.py"
)
iad = importlib.util.module_from_spec(spec)
sys.modules["indicator_arena_daily"] = iad
spec.loader.exec_module(iad)


# ---------------------------------------------------------------------------
# Synthetic market data (seeded — no network)
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 11, 9, 40, tzinfo=timezone.utc)  # 17:40 Taipei 2026-06-11

US_DATES = pd.bdate_range("2024-01-02", "2026-06-10")
TW_DATES = pd.bdate_range("2024-01-02", "2026-06-11")


def _gbm(dates, seed, s0=100.0, vol=0.01):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, vol, len(dates))
    return pd.Series(s0 * np.exp(np.cumsum(rets)), index=dates)


def _vix_like(dates, seed, base=16.0):
    rng = np.random.default_rng(seed)
    return pd.Series(base + np.abs(rng.normal(0, 3, len(dates))), index=dates)


def make_prices() -> dict[str, pd.Series]:
    return {
        "SPY": _gbm(US_DATES, 1),
        "QQQ": _gbm(US_DATES, 2),
        "GLD": _gbm(US_DATES, 3, vol=0.008),
        "TLT": _gbm(US_DATES, 4, vol=0.007),
        "^VIX": _vix_like(US_DATES, 5),
        "^VIX9D": _vix_like(US_DATES, 6, base=15.0),
        "0050.TW": _gbm(TW_DATES, 7),
    }


def make_fetch(prices: dict[str, pd.Series], fail: set[str] | None = None):
    fail = fail or set()

    def fetch(ticker: str, start: str):
        if ticker in fail:
            raise RuntimeError(f"simulated fetch failure for {ticker}")
        if ticker not in prices:
            raise RuntimeError(f"no mock data for {ticker}")
        s = prices[ticker]
        if start:
            s = s[s.index >= pd.Timestamp(start)]
        return s.copy()

    return fetch


@pytest.fixture()
def fast_a4f(monkeypatch):
    """Replace the heavy GARCH-X MLE with a cheap deterministic fit (the
    pipeline mechanics under test do not depend on MLE accuracy)."""

    def fake_fit(returns, vix2):
        n = len(returns)
        return {
            "params": np.array([1e-5, 0.5, 0.05, 0.04, 0.06, 0.90, 8.0]),
            "h": np.full(n, float(np.var(returns))),
            "g": np.ones(n),
            "converged": True,
            "nll": 0.0,
            "df": 8.0,
        }

    monkeypatch.setattr(iad, "fit_a4f_t_joint", fake_fit)
    return fake_fit


def _run(tmp_path, prices=None, fail=None, now=NOW):
    sig_dir = tmp_path / "signals"
    rev_dir = tmp_path / "reviews"
    return iad.run_pipeline(
        now_utc=now,
        fetch_fn=make_fetch(prices or make_prices(), fail=fail),
        signals_dir=sig_dir,
        reviews_dir=rev_dir,
        do_sync=False,
    ), sig_dir, rev_dir


def _count_rows(dir_path: Path) -> int:
    n = 0
    for f in dir_path.glob("*.jsonl"):
        n += sum(1 for line in f.read_text().splitlines() if line.strip())
    return n


ALL_IDS = {
    "us_tw_overnight_lead",
    "vix_term_structure_vol_direction",
    "garch_vix9d_spy_var25",
    "har_qr_spy_var5",
    "vix_crisis_alert_tw",
    "har_qr_rv_q95_qqq_gld_tlt",
}


# ---------------------------------------------------------------------------
# 1. Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_run_appends_nothing(self, tmp_path, fast_a4f):
        result1, sig_dir, rev_dir = _run(tmp_path)
        assert {e["indicator_id"] for e in result1["emitted"]} == ALL_IDS
        assert result1["failed"] == []
        n_sig_1 = _count_rows(sig_dir)
        n_rev_1 = _count_rows(rev_dir)
        assert n_sig_1 == 6

        result2 = iad.run_pipeline(
            now_utc=NOW,
            fetch_fn=make_fetch(make_prices()),
            signals_dir=sig_dir,
            reviews_dir=rev_dir,
            do_sync=False,
        )
        assert result2["emitted"] == []
        dup = [s for s in result2["skipped"] if s["kind"] == "duplicate"]
        assert {d["indicator_id"] for d in dup} == ALL_IDS
        assert _count_rows(sig_dir) == n_sig_1, "second run must not append signals"
        assert _count_rows(rev_dir) == n_rev_1, "second run must not duplicate reviews"
        # duplicate skips are normal operation, not failure
        assert result2["ok"] is True

    def test_signal_id_is_indicator_and_target_date(self, tmp_path, fast_a4f):
        result, sig_dir, _ = _run(tmp_path)
        for e in result["emitted"]:
            assert e["signal_id"] == f"{e['indicator_id']}:{e['target_date']}"


# ---------------------------------------------------------------------------
# 2. Ex-ante guard (as_of_ts > now -> rejected, never written)
# ---------------------------------------------------------------------------

class TestExAnteGuard:
    def test_future_as_of_rejected(self, tmp_path, fast_a4f, monkeypatch):
        def evil_builder(mkt, now, spec):
            future = (now + pd.Timedelta(days=1)).isoformat()
            return {
                "signal_id": f"{spec.indicator_id}:2026-06-12",
                "as_of_ts": future,  # data cutoff in the future = lookahead
                "target_date": "2026-06-12",
                "prediction": {"direction": "up"},
                "horizon_days": 1,
                "expires_at": future,
                "resolve_after": future,
                "indicator_value": 0.0,
                "late": False,
                "league": "direction",
                "inputs_snapshot": {},
                "_raw_inputs": {},
            }

        monkeypatch.setitem(iad.BUILDERS, "us_tw_overnight_lead", evil_builder)
        result, sig_dir, _ = _run(tmp_path)

        fail = [f for f in result["failed"] if f["indicator_id"] == "us_tw_overnight_lead"]
        assert len(fail) == 1
        assert "Lookahead" in fail[0]["error"]
        assert result["ok"] is False
        # the lookahead signal must never reach disk
        for f in sig_dir.glob("*.jsonl"):
            for line in f.read_text().splitlines():
                row = json.loads(line)
                assert row["indicator_id"] != "us_tw_overnight_lead"

    def test_in_progress_session_dropped(self):
        """Data-layer lookahead guard: a bar whose session close is after `now`
        must be excluded from completed closes."""
        prices = make_prices()
        # now = before the 2026-06-11 TW close -> the 06-11 TW bar is in-progress
        now_mid_session = datetime(2026, 6, 11, 2, 0, tzinfo=timezone.utc)  # 10:00 TST
        mkt = iad.MarketData(make_fetch(prices), now_mid_session)
        tw = mkt.closes("0050.TW")
        assert tw.index[-1].date().isoformat() == "2026-06-10"


# ---------------------------------------------------------------------------
# 3. Failure isolation (one data source down does not block the others)
# ---------------------------------------------------------------------------

class TestFailureIsolation:
    def test_vix9d_failure_does_not_block_others(self, tmp_path, fast_a4f):
        result, sig_dir, _ = _run(tmp_path, fail={"^VIX9D", "__CBOE_VIX9D__"})

        emitted_ids = {e["indicator_id"] for e in result["emitted"]}
        assert emitted_ids == {
            "us_tw_overnight_lead",
            "har_qr_spy_var5",
            "vix_crisis_alert_tw",
            "har_qr_rv_q95_qqq_gld_tlt",
        }
        blocked = {
            f["indicator_id"]
            for f in result["failed"]
        } | {
            s["indicator_id"]
            for s in result["skipped"]
            if s["kind"] == "data_unavailable"
        }
        assert blocked == {"vix_term_structure_vol_direction", "garch_vix9d_spy_var25"}
        assert result["ok"] is False  # not fully successful
        assert _count_rows(sig_dir) == 4

    def test_all_sources_down_yields_no_rows_and_not_ok(self, tmp_path, fast_a4f):
        all_tickers = set(make_prices().keys()) | {"__CBOE_VIX9D__"}
        result, sig_dir, _ = _run(tmp_path, fail=all_tickers)
        assert result["emitted"] == []
        assert result["ok"] is False
        assert _count_rows(sig_dir) == 0


# ---------------------------------------------------------------------------
# Review resolution sanity (late TW signal resolvable same run)
# ---------------------------------------------------------------------------

class TestReviewResolution:
    def test_tw_signals_resolved_when_outcome_available(self, tmp_path, fast_a4f):
        result, _, rev_dir = _run(tmp_path)
        reviewed = {r["indicator_id"] for r in result["reviews_done"]}
        # 0050.TW closed 2026-06-11 13:30 TST (< now 17:40) -> both TW
        # indicators are due and resolvable within the same run.
        assert reviewed == {"us_tw_overnight_lead", "vix_crisis_alert_tw"}
        assert _count_rows(rev_dir) == 2
        for r in result["reviews_done"]:
            assert r["hit"] in (True, False)

    def test_us_signals_stay_pending(self, tmp_path, fast_a4f):
        result, _, _ = _run(tmp_path)
        pending_ids = ALL_IDS - {r["indicator_id"] for r in result["reviews_done"]}
        assert "garch_vix9d_spy_var25" in pending_ids
        assert "har_qr_spy_var5" in pending_ids
