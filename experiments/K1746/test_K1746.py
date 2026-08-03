from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("k1746_module", HERE / "K1746.py")
assert SPEC and SPEC.loader
k = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = k
SPEC.loader.exec_module(k)


def test_signal_is_shifted_one_day() -> None:
    x = pd.Series([0.01, 0.02, -0.01, 0.03], index=pd.date_range("2020-01-01", periods=4))
    signal = k.ewma_signal(x, 0.9)
    raw = x.pow(2).ewm(alpha=0.1, adjust=False).mean().pow(0.5)
    pd.testing.assert_series_equal(signal.iloc[1:], raw.shift(1).clip(lower=k.EPS).iloc[1:])
    assert pd.isna(signal.iloc[0])


def test_quantile_es_sign_and_order() -> None:
    q, e = k.quantile_es(np.linspace(-0.10, 0.10, 1001), 0.05)
    assert e <= q < 0


def test_fz0_is_finite_and_lower_for_nearby_forecast() -> None:
    rng = np.random.default_rng(42)
    y = rng.normal(0, 0.01, 200_000)
    q = np.full_like(y, -1.6448536269514722 * 0.01)
    e = np.full_like(y, -2.0627128075074253 * 0.01)
    good = k.fz0_loss(y, q, e, 0.05).mean()
    bad = k.fz0_loss(y, q * 0.5, e * 0.5, 0.05).mean()
    assert np.isfinite(good)
    assert good < bad


def test_daily_equal_weight_target_math() -> None:
    dates = pd.date_range("2020-01-01", periods=3)
    returns = pd.DataFrame(np.arange(15).reshape(3, 5) / 1000, index=dates, columns=k.ASSETS)
    target, weights = k.daily_equal_weight_returns(returns)
    np.testing.assert_allclose(target, returns.mean(axis=1))
    np.testing.assert_allclose(weights, 0.2)


def test_forecast_origins_are_identical_and_training_ends_before_origin() -> None:
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2010-01-01", periods=260)
    returns = pd.DataFrame(rng.normal(0, 0.01, (260, 5)), index=dates, columns=k.ASSETS)
    target, weights = k.daily_equal_weight_returns(returns)
    spec = k.ForecastSpec("test", 80, "same_date_empirical", "FHS", "daily")
    forecasts = k.forecast_spec(returns, target, weights, spec, 42)
    assert (forecasts.training_end_position < forecasts.origin_position).all()
    counts = forecasts.groupby(["method", "alpha"]).date.nunique()
    assert counts.nunique() == 1
    assert set(forecasts.method) == {"bottom_up", "top_down", "naive_marginal_sum"}
    assert (forecasts.es <= forecasts["var"]).all()
    assert (forecasts["var"] < 0).all()


def test_dependence_aware_aggregation_differs_from_naive_sum() -> None:
    rng = np.random.default_rng(42)
    z = rng.normal(size=(2000, 5))
    z[:, 1:] = 0.6 * z[:, [0]] + np.sqrt(1 - 0.6**2) * z[:, 1:]
    bottom_q, _ = k.quantile_es(z.mean(axis=1), 0.01)
    marginal_q = np.mean([k.quantile_es(z[:, j], 0.01)[0] for j in range(5)])
    assert abs(bottom_q - marginal_q) > 0.1


def _adjust(raw: dict[str, float]) -> dict[str, float]:
    """Mirror the experiment's canonical-Holm call shape (name -> adjusted p)."""
    keys = list(raw)
    return dict(zip(keys, k.holm_step_down([raw[key] for key in keys]).adjusted_p_values))


def test_holm_adjustment_is_monotone_and_not_below_raw() -> None:
    raw = {"a": 0.01, "b": 0.02, "c": 0.5}
    adjusted = _adjust(raw)
    assert all(adjusted[name] >= p for name, p in raw.items())
    assert adjusted["a"] <= adjusted["b"] <= adjusted["c"]


def test_canonical_holm_matches_the_retired_local_definition() -> None:
    """Pin the refactor: canonical Holm == the local copy this file used to hold.

    K1746 originally carried its own ``holm_adjust``; the canonical-stat-helper
    ratchet flagged it as a re-implementation of
    ``volpred.stats.inference.holm_step_down``.  This reproduces the retired
    definition here (test files are outside the ratchet's scan) and asserts the
    canonical helper is indistinguishable from it, including ties and the 0/1
    boundaries, so the swap cannot silently move a published p-value.
    """

    def retired_local_holm(named_p: dict[str, float]) -> dict[str, float]:
        ordered = sorted(named_p.items(), key=lambda kv: kv[1])
        m, running = len(ordered), 0.0
        out: dict[str, float] = {}
        for rank, (name, p) in enumerate(ordered):
            running = max(running, min(1.0, (m - rank) * p))
            out[name] = running
        return out

    rng = np.random.default_rng(20260804)
    for trial in range(500):
        size = int(rng.integers(1, 12))
        values = rng.random(size)
        if trial % 3 == 0:  # force exact ties
            values = np.repeat(values[: max(1, size // 2)], 2)[:size]
        if trial % 7 == 0:  # force boundary p-values
            values = rng.choice([0.0, 1.0, 1e-12, 0.5], size=size)
        raw = {f"cell_{i}": float(v) for i, v in enumerate(values)}
        assert _adjust(raw) == retired_local_holm(raw)


def test_runtime_artifacts_are_byte_traceable_and_consistent() -> None:
    result_path = HERE / "K1746_results.json"
    spec_path = HERE / "reproduce_spec.json"
    if not result_path.exists() or not spec_path.exists():
        return
    result = json.loads(result_path.read_text())
    spec = json.loads(spec_path.read_text())
    script_bytes = (HERE / "K1746.py").read_bytes()
    digest = hashlib.sha256(script_bytes).hexdigest()
    assert result["code_trace"]["sha256"] == digest
    assert spec["entrypoint"]["sha256"] == digest
    assert result["code_trace"]["size_bytes"] == len(script_bytes)
    assert result["recovery_identity"]["prior_status"] == "ZERO_SALVAGE"
    assert result["verdict"]["scientific_null_not_zero_salvage"] is True
    readme = (HERE / "README.md").read_text()
    assert result["verdict"]["grade"] in readme
    assert "ZERO_SALVAGE" in readme


def test_frozen_source_hash() -> None:
    path = HERE / "data" / "prices.csv"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == k.UPSTREAM["sha256"]


def test_source_manifest_is_stable_provenance() -> None:
    first = k.source_manifest()
    second = k.source_manifest()
    assert first == second
    assert first["copied_for_k1746_at_utc"] == k.SOURCE_COPIED_AT_UTC
    assert first["local_sha256"] == k.UPSTREAM["sha256"]
    assert k.UPSTREAM["retrieved_at_utc"] == "2026-07-27T19:36:36.183381+00:00"


def test_wang_wang_claim_does_not_overstate_portfolio_aggregation() -> None:
    claim = k.REFERENCES[0]["verified_claim"]
    assert "does not study portfolio-constituent" in claim
    assert "terminological inspiration" in claim
