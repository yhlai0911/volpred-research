from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("k1705.py")
SPEC = importlib.util.spec_from_file_location("k1705_module", SCRIPT)
assert SPEC and SPEC.loader
K1705 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(K1705)


def test_joe_independence_density_is_one() -> None:
    u = np.array([0.05, 0.2, 0.5, 0.9])
    v = np.array([0.8, 0.4, 0.5, 0.1])
    np.testing.assert_allclose(K1705.joe_log_density(u, v, 1.0), 0.0, atol=1e-12)


def test_ewma_forecast_does_not_use_current_or_future_return() -> None:
    returns = np.linspace(-0.03, 0.03, 100)
    baseline = K1705.ewma_variance(returns)
    changed = returns.copy()
    changed[80:] = 99.0
    alternate = K1705.ewma_variance(changed)
    np.testing.assert_allclose(baseline[:81], alternate[:81], equal_nan=True)


def test_parent_sign_audit_finds_both_reversals() -> None:
    parent = K1705.json.loads(K1705.PARENT_RESULTS.read_text(encoding="utf-8"))
    audit = K1705.parent_claim_audit(parent)
    assert all(row["sign_reversal_confirmed"] for row in audit["pairs"].values())
    assert audit["code_evidence"]["archived_joe_density_fails_independence_limit"]
