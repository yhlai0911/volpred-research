from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import k1695


def test_explicit_total_return_adds_distributions_but_not_split_twice() -> None:
    # Yahoo historical Close is already split-normalized.  The split action is
    # audit metadata; a second multiplication would create a false 100% return.
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    frame = pd.DataFrame(
        {
            "date": dates,
            "ticker": "TEST",
            "close": [100.0, 98.0, 99.0],
            "adj_close": [98.0, 98.0, 99.0],
            "dividends": [0.0, 2.0, 0.0],
            "capital_gains": [0.0, 0.0, 0.0],
            "stock_splits": [0.0, 2.0, 0.0],
            "volume": [1, 1, 1],
        }
    )
    returns, diagnostics = k1695.explicit_total_returns(frame)
    assert returns.iloc[0] == pytest.approx(0.0)
    assert returns.iloc[1] == pytest.approx(99.0 / 98.0 - 1.0)
    assert diagnostics["split_events_audit_only"] == 1


def test_monthly_signal_maps_previous_month_to_entire_next_month() -> None:
    vix = pd.Series(
        [10.0, 20.0, 40.0],
        index=pd.to_datetime(["2024-12-31", "2025-01-31", "2025-02-28"]),
    )
    dates = pd.to_datetime(
        ["2025-01-02", "2025-01-31", "2025-02-03", "2025-02-28", "2025-03-03"]
    )
    weight = k1695.build_monthly_lagged_weights(vix, dates)
    assert weight.tolist() == pytest.approx([1.0, 1.0, 0.6, 0.6, 0.3])


def test_irx_is_prior_day_and_forward_filled_without_backfill() -> None:
    irx = pd.Series(
        [5.04, 2.52],
        index=pd.to_datetime(["2025-01-02", "2025-01-06"]),
    )
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
    daily = k1695.prior_day_irx_daily(irx, dates)
    assert np.isnan(daily.iloc[0])
    assert daily.iloc[1] == pytest.approx(0.0504 / 252.0)
    # The 1/6 quote cannot benchmark the same day's return; it first appears 1/7.
    assert daily.iloc[2] == pytest.approx(0.0504 / 252.0)
    assert daily.iloc[3] == pytest.approx(0.0252 / 252.0)


def test_monthly_hold_cost_is_turnover_based_not_fixed_monthly_fee() -> None:
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-02-03", "2025-02-04"])
    equity = pd.Series([0.10, 0.00, 0.00, 0.00], index=dates)
    cash = pd.Series([0.00, 0.00, 0.00, 0.00], index=dates)
    target = pd.Series([0.50, 0.50, 0.25, 0.25], index=dates)
    path = k1695.simulate_monthly_hold(equity, cash, target, cost_rate=0.001)
    assert path.returns.name == "vt_return"
    assert path.target_weight.name == "target_weight"
    assert path.turnover.name == "turnover"
    assert path.transaction_cost.name == "transaction_cost"
    assert path.transaction_cost.iloc[:2].sum() == 0.0
    # Jan drift raises equity weight above 0.50; Feb cost uses actual pretrade
    # weight change, not a flat 10 bp charge.
    assert path.turnover.iloc[2] == pytest.approx(abs(0.25 - 0.55 / 1.05))
    assert path.transaction_cost.iloc[2] == pytest.approx(path.turnover.iloc[2] * 0.001)
    assert path.transaction_cost.iloc[3] == 0.0


def test_stationary_bootstrap_indices_have_exact_length_and_shared_pairing() -> None:
    rng = np.random.default_rng(42)
    indices = k1695.stationary_bootstrap_indices(17, 5, rng)
    assert len(indices) == 17
    assert indices.min() >= 0 and indices.max() < 17
    paired = np.column_stack([np.arange(17), np.arange(17) + 100])
    sampled = paired[indices]
    assert np.all(sampled[:, 1] - sampled[:, 0] == 100)


def test_mdd_includes_initial_nav_as_running_peak() -> None:
    returns = np.array([[-0.20, -0.10], [0.00, 0.05], [0.25, 0.10]])
    observed = k1695.max_drawdown_by_column(returns)
    assert observed[0] == pytest.approx(-0.20)
    assert observed[1] == pytest.approx(-0.10)

    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    scalar_returns = pd.Series(np.r_[-0.20, np.zeros(299)], index=dates)
    rf = pd.Series(0.0, index=dates)
    assert k1695.compute_metrics(scalar_returns, rf)["max_drawdown"] == pytest.approx(-0.20)


def test_joint_bootstrap_uses_paired_columns_and_native_booleans() -> None:
    rng = np.random.default_rng(9)
    n = 300
    bh_a = rng.normal(0.0002, 0.01, n)
    bh_b = rng.normal(0.0001, 0.012, n)
    # Lower-volatility paired VT returns for both toy markets.
    panel = pd.DataFrame(
        {
            "A_bh": bh_a,
            "B_bh": bh_b,
            "A_vt": 0.6 * bh_a,
            "B_vt": 0.6 * bh_b,
        }
    )
    result = k1695.joint_mdd_bootstrap(
        panel,
        ["A", "B"],
        reps=1_000,
        mean_block=21,
        seed=42,
    )
    assert result["n_obs"] == n
    assert isinstance(result["probability_all_13_positive"], float)
    assert set(result["per_market_delta_mdd_ci"]) == {"A", "B"}


def test_atomic_json_failure_preserves_existing_final(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "result.json"
    target.write_text('{"old": true}\n', encoding="utf-8")
    real_loads = json.loads
    calls = {"n": 0}

    def fail_second_parse(value: str):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("injected parse failure before replace")
        return real_loads(value)

    monkeypatch.setattr(k1695.json, "loads", fail_second_parse)
    with pytest.raises(ValueError, match="injected"):
        k1695.atomic_write_json(target, {"new": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}


def test_builtin_conversion_does_not_stringify_numpy_booleans() -> None:
    converted = k1695._to_builtin({"pass": np.bool_(True), "x": np.float64(1.25)})
    assert converted == {"pass": True, "x": 1.25}
    assert isinstance(converted["pass"], bool)


def test_snapshot_coverage_fails_closed_on_truncated_ticker(monkeypatch) -> None:
    monkeypatch.setattr(k1695, "REQUIRED_TICKERS", ("A", "B"))
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-03-30", "2026-03-31", "2026-03-30", "2026-03-31"]
            ),
            "ticker": ["A", "A", "B", "B"],
            "close": [1.0, 1.0, 1.0, 1.0],
        }
    )
    assert set(k1695.validate_snapshot_coverage(frame)) == {"A", "B"}
    truncated = frame[~((frame["ticker"] == "B") & (frame["date"] == pd.Timestamp("2026-03-31")))]
    with pytest.raises(ValueError, match="truncated snapshot end"):
        k1695.validate_snapshot_coverage(truncated)


def test_total_return_crosscheck_has_stricter_ordinary_day_gate() -> None:
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    frame = pd.DataFrame(
        {
            "date": dates,
            "ticker": "TEST",
            "close": [100.0, 100.0, 100.0],
            "adj_close": [100.0, 100.02, 100.02],  # 2 bp ordinary-day drift
            "dividends": [0.0, 0.0, 0.0],
            "capital_gains": [0.0, 0.0, 0.0],
            "stock_splits": [0.0, 0.0, 0.0],
            "volume": [1, 1, 1],
        }
    )
    with pytest.raises(ValueError, match="ordinary-day"):
        k1695.explicit_total_returns(frame)
