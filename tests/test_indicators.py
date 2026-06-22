"""
Tests for src/volpred/indicators/ module.

Gate requirements (task indicator_arena_phase1_backend_2026_06_11):
  1. Registry loads correctly — 6 active indicators
  2. signals.append_signal append-only (two appends → 2 rows, different timestamps)
  3. signals.append_signal rejects missing required field (raises ValueError)
  4. reviews.compute_review correctly scores direction league (hit + abs error)
  5. cli emit rejects unknown indicator_id (exits with code 1)
  6. reviews.compute_review append-only (two reviews → 2 rows in JSONL)
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from volpred.indicators import signals as signals_module
from volpred.indicators.registry import (
    IndicatorSpec,
    load_registry,
    get_active,
    get_by_id,
    REGISTRY_PATH,
)
from volpred.indicators.signals import (
    append_signal,
    read_signals,
    compute_data_hash,
)
from volpred.indicators.reviews import (
    compute_review,
    read_reviews,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(
    indicator_id: str = "test_indicator",
    as_of_ts: str | None = None,
    emitted_at: str | None = None,
    prediction: dict | None = None,
) -> dict:
    now_utc = datetime.now(timezone.utc)
    past = (now_utc - timedelta(hours=1)).isoformat()
    return {
        "signal_id": str(uuid.uuid4()),
        "indicator_id": indicator_id,
        "as_of_ts": as_of_ts or past,
        "emitted_at": emitted_at or now_utc.isoformat(),
        "prediction": prediction or {"direction": "up"},
        "horizon_days": 1,
        "expires_at": (now_utc + timedelta(days=1)).isoformat(),
        "data_hash": compute_data_hash({"price": 100.0}),
        "code_version": "abc1234",
    }


# ---------------------------------------------------------------------------
# Test 1: Registry loads correctly — 6 active indicators
# ---------------------------------------------------------------------------

def test_git_short_sha_warning_when_git_unavailable(monkeypatch, capsys):
    def fail_run(*args, **kwargs):
        raise RuntimeError("git missing")

    monkeypatch.setattr(signals_module.subprocess, "run", fail_run)

    assert signals_module._get_git_short_sha() == "unknown"
    out = capsys.readouterr().out
    assert "[signals] WARN git rev-parse exception" in out
    assert "git missing" in out


class TestRegistryLoad:
    def test_loads_six_active_indicators(self):
        specs = get_active()
        assert len(specs) == 6, (
            f"Expected 6 active indicators, got {len(specs)}: "
            f"{[s.indicator_id for s in specs]}"
        )

    def test_all_required_fields_present(self):
        specs = load_registry()
        for spec in specs:
            assert spec.indicator_id
            assert spec.name_zh
            assert spec.league in {"direction", "calibration"}
            assert spec.signal_rule
            assert spec.target
            assert spec.horizon_days >= 1
            assert isinstance(spec.k_refs, list)
            assert len(spec.k_refs) >= 1
            assert isinstance(spec.oos_evidence, dict)
            assert spec.caveats
            assert spec.status in {"active", "observation", "delisted"}

    def test_known_indicator_ids_present(self):
        ids = {s.indicator_id for s in load_registry()}
        expected = {
            "us_tw_overnight_lead",
            "vix_term_structure_vol_direction",
            "garch_vix9d_spy_var25",
            "har_qr_spy_var5",
            "vix_crisis_alert_tw",
            "har_qr_rv_q95_qqq_gld_tlt",
        }
        assert expected.issubset(ids), f"Missing: {expected - ids}"

    def test_get_by_id_returns_correct_spec(self):
        spec = get_by_id("us_tw_overnight_lead")
        assert spec is not None
        assert spec.league == "direction"
        assert spec.horizon_days == 1

    def test_get_by_id_returns_none_for_unknown(self):
        spec = get_by_id("nonexistent_indicator_xyz")
        assert spec is None


# ---------------------------------------------------------------------------
# Test 2: append_signal — append-only (two appends → 2 rows, diff timestamps)
# ---------------------------------------------------------------------------

class TestSignalsAppendOnly:
    def test_two_appends_produce_two_rows(self, tmp_path):
        sig_dir = tmp_path / "signals"
        sig_dir.mkdir()

        # First append
        sig1 = _make_signal()
        append_signal("test_indicator", sig1, signals_dir=sig_dir)

        # Small pause so emitted_at timestamps differ
        time.sleep(0.05)

        # Second append (different signal_id)
        sig2 = _make_signal()
        sig2["signal_id"] = str(uuid.uuid4())  # ensure different
        append_signal("test_indicator", sig2, signals_dir=sig_dir)

        # Find the written file
        files = list(sig_dir.glob("*.jsonl"))
        assert len(files) == 1, f"Expected 1 JSONL file, found {files}"

        rows = read_signals(files[0].stem, sig_dir)
        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"

        # Verify signal_ids are different
        ids = {r["signal_id"] for r in rows}
        assert len(ids) == 2, "Two rows should have distinct signal_ids"

    def test_file_mode_is_append_not_overwrite(self, tmp_path):
        """Re-running append_signal must not truncate existing data."""
        sig_dir = tmp_path / "signals"
        sig_dir.mkdir()

        for i in range(3):
            sig = _make_signal()
            sig["signal_id"] = str(uuid.uuid4())
            append_signal("test_indicator", sig, signals_dir=sig_dir)

        files = list(sig_dir.glob("*.jsonl"))
        assert len(files) == 1
        rows = read_signals(files[0].stem, sig_dir)
        assert len(rows) == 3, f"Expected 3 rows after 3 appends, got {len(rows)}"


# ---------------------------------------------------------------------------
# Test 3: append_signal rejects missing required field
# ---------------------------------------------------------------------------

class TestSignalsValidation:
    def test_rejects_missing_prediction(self, tmp_path):
        sig_dir = tmp_path / "signals"
        sig_dir.mkdir()

        sig = _make_signal()
        del sig["prediction"]  # remove required field

        with pytest.raises(ValueError, match="missing required fields"):
            append_signal("test_indicator", sig, signals_dir=sig_dir)

    def test_rejects_missing_data_hash(self, tmp_path):
        sig_dir = tmp_path / "signals"
        sig_dir.mkdir()

        sig = _make_signal()
        del sig["data_hash"]

        with pytest.raises(ValueError, match="missing required fields"):
            append_signal("test_indicator", sig, signals_dir=sig_dir)

    def test_rejects_lookahead(self, tmp_path):
        """as_of_ts > emitted_at must raise ValueError."""
        sig_dir = tmp_path / "signals"
        sig_dir.mkdir()

        now = datetime.now(timezone.utc)
        future = (now + timedelta(days=1)).isoformat()
        past = (now - timedelta(hours=1)).isoformat()

        sig = _make_signal()
        sig["as_of_ts"] = future   # data cutoff is in the future
        sig["emitted_at"] = past   # but we claim we emitted it in the past

        with pytest.raises(ValueError, match="Lookahead"):
            append_signal("test_indicator", sig, signals_dir=sig_dir)

    def test_rejects_invalid_horizon_days(self, tmp_path):
        sig_dir = tmp_path / "signals"
        sig_dir.mkdir()

        sig = _make_signal()
        sig["horizon_days"] = 0  # invalid

        with pytest.raises(ValueError):
            append_signal("test_indicator", sig, signals_dir=sig_dir)


# ---------------------------------------------------------------------------
# Test 4: compute_review — direction league correct scoring
# ---------------------------------------------------------------------------

class TestReviewsCompute:
    def _make_direction_signal(self, direction: str = "up") -> dict:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=2)
        return {
            "signal_id": str(uuid.uuid4()),
            "indicator_id": "us_tw_overnight_lead",
            "as_of_ts": (past - timedelta(hours=1)).isoformat(),
            "emitted_at": past.isoformat(),
            "prediction": {"direction": direction},
            "horizon_days": 1,
            "expires_at": (past + timedelta(days=1)).isoformat(),
            "resolve_after": (past + timedelta(days=1)).isoformat(),
            "data_hash": compute_data_hash({"price": 100.0}),
            "code_version": "test",
            "league": "direction",
        }

    def test_direction_hit_positive_return(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        rev_dir.mkdir()

        sig = self._make_direction_signal("up")
        result = compute_review(
            sig,
            realized={"actual_return": 0.012},
            reviews_dir=rev_dir,
        )
        assert result.hit is True
        assert result.econ_value_bps is not None
        assert abs(result.econ_value_bps - 120.0) < 0.01

    def test_direction_miss_negative_return(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        rev_dir.mkdir()

        sig = self._make_direction_signal("up")
        result = compute_review(
            sig,
            realized={"actual_return": -0.008},
            reviews_dir=rev_dir,
        )
        assert result.hit is False

    def test_down_prediction_hit(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        rev_dir.mkdir()

        sig = self._make_direction_signal("down")
        result = compute_review(
            sig,
            realized={"actual_return": -0.015},
            reviews_dir=rev_dir,
        )
        assert result.hit is True
        assert result.econ_value_bps is not None
        assert result.econ_value_bps > 0  # short position profits

    def test_review_append_only_two_reviews(self, tmp_path):
        """Two reviews for different signals → 2 rows in JSONL."""
        rev_dir = tmp_path / "reviews"
        rev_dir.mkdir()

        for _ in range(2):
            sig = self._make_direction_signal("up")
            compute_review(
                sig,
                realized={"actual_return": 0.005},
                reviews_dir=rev_dir,
            )

        files = list(rev_dir.glob("*.jsonl"))
        assert len(files) >= 1
        all_rows = []
        for f in files:
            all_rows.extend(read_reviews(f.stem, rev_dir))
        assert len(all_rows) == 2

    def test_review_id_format(self, tmp_path):
        rev_dir = tmp_path / "reviews"
        rev_dir.mkdir()

        sig = self._make_direction_signal("up")
        result = compute_review(
            sig,
            realized={"actual_return": 0.01},
            reviews_dir=rev_dir,
        )
        assert result.review_id == f"{sig['signal_id']}:review"


# ---------------------------------------------------------------------------
# Test 5: CLI emit rejects unknown indicator_id (exits with code 1)
# ---------------------------------------------------------------------------

class TestCliEmit:
    def test_emit_unknown_indicator_exits_1(self):
        from click.testing import CliRunner
        from volpred.indicators.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["emit", "completely_unknown_indicator_xyz"])

        assert result.exit_code == 1, (
            f"Expected exit code 1 for unknown indicator, "
            f"got {result.exit_code}. Output: {result.output}"
        )
        assert "unknown indicator_id" in result.output or "Error" in result.output

    def test_emit_known_indicator_dry_run_succeeds(self):
        from click.testing import CliRunner
        from volpred.indicators.cli import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["emit", "us_tw_overnight_lead", "--dry-run"]
        )
        assert result.exit_code == 0, (
            f"Expected exit code 0 for known indicator dry run, "
            f"got {result.exit_code}. Output: {result.output}"
        )
        # Output should be valid JSON scaffold
        assert "indicator_id" in result.output
        assert "us_tw_overnight_lead" in result.output

    def test_status_command_lists_six_active(self):
        from click.testing import CliRunner
        from volpred.indicators.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "6 active" in result.output
