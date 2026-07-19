"""Regression coverage for the coordinated K1257/K1258 BMA remediation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "name,path",
    [
        ("k1257_bma_guard", "experiments/k1257/k1257_bma_volatility.py"),
        ("k1258_bma_guard", "experiments/k1258/k1258_forgetting_factor_bma.py"),
    ],
)
def test_nonconverged_and_exception_fits_are_dropped_and_counted(name, path):
    module = _load(name, path)
    state = {
        "good": {"converged": True},
        "bad": {"converged": False},
        "raised": None,
    }
    mapping = {"good": "GOOD", "bad": "BAD", "raised": "RAISED"}
    diagnostics = {
        model: {
            "fit_attempts": 0,
            "fit_exceptions": 0,
            "nonconverged_fits": 0,
        }
        for model in mapping.values()
    }

    module._drop_unusable_fits(state, diagnostics, mapping)

    assert state["good"] == {"converged": True}
    assert state["bad"] is None
    assert state["raised"] is None
    assert diagnostics["GOOD"]["fit_attempts"] == 1
    assert diagnostics["BAD"]["nonconverged_fits"] == 1
    assert diagnostics["RAISED"]["fit_exceptions"] == 1


def test_ffbma_invalid_models_receive_zero_weight_on_that_day():
    module = _load(
        "k1258_bma_posterior_guard",
        "experiments/k1258/k1258_forgetting_factor_bma.py",
    )
    log_likelihoods = np.array(
        [
            [0.0, np.nan, -1.0],
            [np.nan, 0.0, -1.0],
            [0.0, 0.0, 0.0],
        ]
    )

    weights = module.ffbma_posterior(log_likelihoods, lambda_=0.99)

    np.testing.assert_allclose(weights.sum(axis=1), 1.0)
    assert weights[0, 1] == 0.0
    assert weights[1, 0] == 0.0
    assert np.isfinite(weights).all()
