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


# ---------------------------------------------------------------------------
# Exposure correction (2026-07-15)
# ---------------------------------------------------------------------------
def _toy_market(n_days: int = 800, seed: int = 7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_days)
    equity = pd.Series(rng.normal(0.0004, 0.011, n_days), index=dates)
    cash = pd.Series(np.full(n_days, 0.00008), index=dates)
    targets = pd.Series(
        np.repeat(rng.uniform(0.3, 1.0, n_days), 1)[:n_days], index=dates
    )
    # weights are constant within a calendar month, exactly like the 12/VIX signal
    month = dates.to_period("M")
    monthly = pd.Series(rng.uniform(0.3, 1.0, len(month.unique())), index=month.unique())
    targets = pd.Series([monthly[p] for p in month], index=dates)
    return equity, cash, targets


def test_scenario_simulator_reproduces_the_canonical_scalar_simulator() -> None:
    # The null re-simulates the strategy tens of thousands of times.  If the fast path
    # disagreed with the audited scalar path, the correction would just be a new bug.
    equity, cash, targets = _toy_market()
    canonical = k1695.simulate_monthly_hold(equity, cash, targets)
    fast = k1695.simulate_monthly_hold_scenarios(
        equity.to_numpy(dtype=float),
        cash.to_numpy(dtype=float),
        targets.to_numpy(dtype=float).reshape(-1, 1),
        k1695.month_start_mask(equity.index),
    )
    np.testing.assert_allclose(fast[:, 0], canonical.returns.to_numpy(), atol=1e-14, rtol=0.0)


def test_pure_delevering_earns_a_zero_exposure_matched_gap() -> None:
    # This is the entire point of the correction.  A strategy that just holds less equity
    # has a shallower RAW drawdown and zero skill; the exposure-matched statistic must see
    # through it, otherwise it cannot detect the artifact it exists to detect.
    rng = np.random.default_rng(11)
    benchmark = rng.normal(0.0003, 0.012, 3000)
    delevered = 0.65 * benchmark  # no timing whatsoever: a constant scale-down

    raw = (k1695.vp_max_drawdown(delevered) - k1695.vp_max_drawdown(benchmark)) * 100.0
    assert raw > 5.0, "a pure de-levering must show a large RAW MDD 'improvement'"

    lam, matched = k1695.exposure_matched_mdd_by_column(
        delevered.reshape(-1, 1), benchmark.reshape(-1, 1)
    )
    gap_pp = (k1695.max_drawdown_by_column(delevered.reshape(-1, 1))[0] - matched[0]) * 100.0
    assert lam[0] == pytest.approx(0.65, abs=1e-12)
    assert gap_pp == pytest.approx(0.0, abs=1e-9)


def test_vectorized_exposure_statistic_equals_the_canonical_helper() -> None:
    rng = np.random.default_rng(3)
    benchmark = rng.normal(0.0003, 0.013, (1500, 2))
    strategy = 0.7 * benchmark + rng.normal(0.0, 0.001, (1500, 2))
    k1695.assert_vectorized_matches_canonical(strategy, benchmark, tickers=["A", "B"])


def test_circular_shift_preserves_the_weight_multiset_and_only_moves_phase() -> None:
    signal = pd.Series(
        [0.4, 0.9, 1.0, 0.55, 0.7],
        index=pd.period_range("2020-01", periods=5, freq="M"),
    )
    dates = pd.to_datetime(["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01", "2020-05-01"])
    matrix = k1695._shifted_target_matrix(signal, dates, n_shifts=5)
    assert matrix.shape == (5, 5)
    np.testing.assert_allclose(matrix[:, 0], signal.to_numpy())  # shift 0 IS the observed path
    for shift in range(5):
        assert sorted(matrix[:, shift]) == sorted(signal.to_numpy())  # a permutation of time
    np.testing.assert_allclose(matrix[:, 1], np.roll(signal.to_numpy(), 1))

    # A market with a SHORT history must roll only its own months.  Rolling a longer
    # union-span vector would hand it weights from months it never traded (the 2026-07-15
    # review caught exactly this for INDA/MCHI, whose samples start in 2012/2011).
    short = signal.iloc[2:]  # a market that only exists for the last 3 months
    short_dates = dates[2:]
    short_matrix = k1695._shifted_target_matrix(short, short_dates, n_shifts=5)
    assert short_matrix.shape == (3, 5)
    held = set(short.to_numpy())
    for shift in range(5):
        assert set(short_matrix[:, shift]) <= held, "shift introduced a weight never held"
    # s and s + len(own months) are the same phase for this market
    np.testing.assert_allclose(short_matrix[:, 0], short_matrix[:, 3])


def test_holm_is_step_down_and_stops_at_the_first_failure() -> None:
    result = k1695.holm_correction({"a": 0.001, "b": 0.30, "c": 0.02}, alpha=0.10)
    assert result["a"]["reject"] is True  # rank 1: 0.001 <= 0.10/3
    assert result["c"]["reject"] is True  # rank 2: 0.020 <= 0.10/2
    assert result["b"]["reject"] is False  # rank 3: 0.300 >  0.10/1 -> stop
    assert result["a"]["holm_threshold"] == pytest.approx(0.10 / 3)
    assert result["b"]["holm_threshold"] == pytest.approx(0.10)

    # Once the step-down stops, everything weaker stays un-rejected even if its own
    # threshold would have passed it on its own.  x=0.09 clears its rank-2 threshold of
    # 0.10, but y fails at rank 1, so the family stops and x is not rejected either.
    cascade = k1695.holm_correction({"x": 0.09, "y": 0.06}, alpha=0.10)
    assert cascade["y"]["reject"] is False  # rank 1: 0.06 > 0.10/2
    assert cascade["x"]["reject"] is False  # rank 2: cascaded, despite 0.09 <= 0.10



def test_results_json_never_reports_raw_mdd_without_its_exposure_companion() -> None:
    # This gate locks the RULE, not the verdict: every raw MDD number must ship with its
    # exposure companion, and the raw-only kill gate may never come back.  It deliberately
    # says nothing about which way the answer came out -- a gate that pinned the conclusion
    # would block an honest future reversal, which is the opposite of what it is for.
    payload = json.loads(
        (Path(__file__).resolve().parent / "k1695_results.json").read_text(encoding="utf-8")
    )
    for sample in ("inception_aware", "common_period"):
        summary = payload["samples"][sample]["summary"]
        assert "average_exposure_matched_delta_mdd_pp" in summary
        assert "average_delta_mdd_pp" in summary  # the raw number is never deleted
        for row in payload["samples"][sample]["rows"]:
            exposure = row["exposure"]
            assert exposure["source"] == "volpred.stats.drawdown.compare_max_drawdown"
            assert "exposure_matched_delta_mdd_pp" in row
            assert "vol_ratio" in exposure and "exposure_mismatch" in exposure
        null = payload["inference"]["circular_shift_null"][sample]
        assert null["deterministic"] is True
        assert "joint_exposure_matched" in null and "holm" in null

    assert payload["inference"]["primary_statistic"] == "exposure_matched_delta_mdd_pp"
    # the mis-specified pre-registration is preserved, never quietly rewritten
    assert payload["decision"]["superseded_pre_registration"]["pre_registered_kill_rule"]
    # and the live gate is not allowed to be the raw one again
    assert "exposure-matched" in payload["decision"]["kill_rule"]


def test_this_runs_verdict_snapshot() -> None:
    # Separate from the rule gate above ON PURPOSE.  This pins what THIS run concluded, so a
    # silent drift is caught; if evidence ever justifies a different verdict, exactly one
    # test needs updating and the reviewer can see it in the diff.
    payload = json.loads(
        (Path(__file__).resolve().parent / "k1695_results.json").read_text(encoding="utf-8")
    )
    assert payload["decision"]["kill_triggered"] is True
    assert payload["decision"]["claim_status"] == "retracted"

    common = payload["inference"]["circular_shift_null"]["common_period"]
    inception = payload["inference"]["circular_shift_null"]["inception_aware"]
    assert common["joint_exposure_matched"]["p_one_sided"] > 0.10  # cannot reject no-timing
    assert inception["joint_exposure_matched"]["p_one_sided"] > 0.10
    assert common["holm"]["n_survivors"] == 0
    assert inception["holm"]["n_survivors"] == 0

    # The raw statistic DOES reject on the long sample.  Pinned deliberately: it is the one
    # number that could be used to argue the correction away, so it must stay visible and it
    # must stay explained (by the exposure diagnostic below), not quietly dropped.
    assert inception["joint_raw_delta_mdd"]["p_one_sided"] < 0.10
    exposure = inception["exposure_of_the_null"]
    assert exposure["observed_rank_among_phases"] <= 2  # observed phase = the least risky one
    assert exposure["observed_vol_ratio"] < exposure["null_mean_vol_ratio"]


def test_no_timing_reference_reproduces_the_raw_gap_with_zero_matched_gap() -> None:
    # A strategy that never sees VIX should collect most of the raw "protection" and none
    # of the exposure-matched gap.  If this ever stopped holding, the artifact story would
    # be wrong and the retraction would need revisiting.
    payload = json.loads(
        (Path(__file__).resolve().parent / "k1695_results.json").read_text(encoding="utf-8")
    )
    for sample in ("inception_aware", "common_period"):
        reference = payload["inference"]["no_timing_reference"][sample]
        actual_raw = payload["samples"][sample]["summary"]["average_delta_mdd_pp"]
        assert reference["n_raw_improved"] == 13
        assert reference["average_raw_delta_mdd_pp"] > 0.5 * actual_raw
        assert abs(reference["average_exposure_matched_delta_mdd_pp"]) < 0.5
