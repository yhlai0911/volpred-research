"""Mechanical gate for the FEVD axis-order bug class (k865 / crypto-fear, 2026-07-11).

statsmodels' ``VARResults.fevd(h).decomp`` has shape ``(n, horizon, n)``:

    axis 0 = variable i whose forecast error variance is being decomposed
    axis 1 = forecast horizon step (0 .. horizon-1)
    axis 2 = shock source j

The Diebold-Yilmaz connectedness table is the n x n matrix at the FINAL horizon,
i.e. ``decomp[:, -1, :]``. Writing ``decomp[-1]`` instead selects the LAST
VARIABLE and returns its ``(horizon, n)`` table -- horizon steps get silently
treated as assets. Downstream code then reads a (horizon, n) array as if it were
(n, n), slices an n x n sub-block out of it, and every number derived from it
(total spillover index, from/to/net spillover, transmitters/receivers) is an
artifact. The failure is quiet because the array is still 2-D, the arithmetic
still runs, and the output still looks like percentages.

The empirical signature is a near-constant ~90% connectedness index that barely
moves between calm and crisis windows: the "diagonal" of the mis-sliced matrix is
no longer own-variance, so almost everything lands off-diagonal. k865 shipped a
90.9% TSI in every regime and a nonsensical +536 net spillover for BTC (a net
share cannot exceed ~100 x n). See docs/error_log.md 2026-07-11.

The gate has two halves:

1. BEHAVIOURAL -- on iid data (true connectedness = 0) the correct slice returns
   a near-identity matrix and a TSI of ~1-2%, while the buggy slice manufactures
   ~80%. A connected chain DGP is also checked, so the test cannot be satisfied
   by an implementation that just always returns a small number.
2. STATIC -- an AST scan of the whole experiments/ + src/ + scripts/ population
   for the ``.decomp[-1]`` subscript. The population is currently CLEAN (k865 was
   the only site; k628b and k304 index the variable axis first and are correct),
   so this is a clean-tree assertion, not a ratchet.

Per anti-stacking this is the single enforcement owner for the FEVD axis-order
concern. Do not add a second watchdog -- extend this file.

Run:
    uv run --extra dev python -m pytest scripts/tests/test_fevd_shape.py -q
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.api import VAR

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# iid truth is 0% connectedness. Estimating a VAR(5) on 5 series x 1500 obs leaves
# a little sampling noise in the off-diagonals: measured 1.13-1.69% across 8 seeds
# (2026-07-11 calibration). 5.0 sits far above that noise band and far below both
# the buggy slice's ~80% and a genuinely connected system's ~33%.
IID_TSI_CEILING = 5.0
# The buggy slice on the same iid data. Measured ~80.1% across the same 8 seeds.
BUGGY_TSI_FLOOR = 50.0
# A deliberately connected chain X -> Y -> Z. Measured 33.2%.
CONNECTED_TSI_FLOOR = 20.0

SCAN_DIRS = ("experiments", "src", "scripts")


def _total_spillover_index(matrix: np.ndarray) -> float:
    """Diebold-Yilmaz TSI: off-diagonal share of the row-normalised FEVD table."""
    m = matrix / matrix.sum(axis=1, keepdims=True) * 100.0
    return float((m.sum() - np.trace(m)) / m.sum() * 100.0)


def _iid_decomp(seed: int, n: int = 5, obs: int = 1500, lags: int = 5, horizon: int = 10):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        rng.standard_normal((obs, n)),
        columns=[f"X{i}" for i in range(n)],
    )
    return VAR(df).fit(maxlags=lags, ic=None).fevd(horizon).decomp, n, horizon


def test_statsmodels_fevd_axis_order_is_n_horizon_n() -> None:
    """Pin the axis order. If statsmodels ever changes it, fail loudly here."""
    decomp, n, horizon = _iid_decomp(seed=865)

    assert decomp.shape == (n, horizon, n), (
        f"statsmodels FEVD decomp shape is {decomp.shape}, expected "
        f"({n}, {horizon}, {n}) = (variable, horizon, shock). Every call site that "
        "slices `decomp[:, -1, :]` to get the final-horizon connectedness table "
        "assumes this order -- re-verify them all before touching this assertion."
    )
    # Each (variable, horizon) row of shock shares must sum to 1. This is what
    # identifies axis 2 as the shock axis rather than the horizon axis.
    np.testing.assert_allclose(decomp.sum(axis=2), 1.0, atol=1e-8)


@pytest.mark.parametrize("seed", [0, 1, 2, 42, 865])
def test_correct_slice_gives_near_zero_connectedness_on_iid(seed: int) -> None:
    """decomp[:, -1, :] on independent series -> near-identity, TSI ~ 0."""
    decomp, _, _ = _iid_decomp(seed=seed)

    tsi = _total_spillover_index(decomp[:, -1, :])

    assert tsi < IID_TSI_CEILING, (
        f"Independent series produced a {tsi:.2f}% total spillover index "
        f"(ceiling {IID_TSI_CEILING}%). The final-horizon FEVD table of an iid "
        "system must be near-identity; a high index means the horizon axis is "
        "being read as the asset axis. Use decomp[:, -1, :], never decomp[-1]."
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 42, 865])
def test_buggy_slice_manufactures_connectedness_on_iid(seed: int) -> None:
    """The k865 bug, reproduced: decomp[-1] fabricates ~80% TSI out of noise.

    This is the discriminating half of the gate -- it proves the iid check above
    would actually have caught the shipped bug, rather than passing vacuously.
    """
    decomp, n, _ = _iid_decomp(seed=seed)

    # Exactly what k865 did: take decomp[-1] -- the LAST VARIABLE's (horizon, n)
    # table -- and let downstream code read the leading n x n block as if the
    # horizon steps were assets.
    buggy = decomp[-1][:n]
    tsi = _total_spillover_index(buggy)

    assert tsi > BUGGY_TSI_FLOOR, (
        f"decomp[-1] on iid data gave only {tsi:.2f}% TSI; this regression test "
        "expects it to fabricate a large index (>%.0f%%). If this fails, the "
        "shape semantics changed and the whole gate needs re-derivation."
        % BUGGY_TSI_FLOOR
    )


def test_correct_slice_still_detects_real_connectedness() -> None:
    """Guard against a 'always returns small' implementation passing the iid test."""
    rng = np.random.default_rng(9)
    obs = 1500
    e = rng.standard_normal((obs, 3))
    x = np.zeros((obs, 3))
    for t in range(1, obs):
        x[t, 0] = 0.5 * x[t - 1, 0] + e[t, 0]
        x[t, 1] = 0.8 * x[t - 1, 0] + e[t, 1]  # X -> Y
        x[t, 2] = 0.8 * x[t - 1, 1] + e[t, 2]  # Y -> Z

    decomp = VAR(pd.DataFrame(x, columns=["X", "Y", "Z"])).fit(maxlags=2, ic=None).fevd(10).decomp
    tsi = _total_spillover_index(decomp[:, -1, :])

    assert tsi > CONNECTED_TSI_FLOOR, (
        f"A deliberately connected X->Y->Z chain gave only {tsi:.2f}% TSI "
        f"(floor {CONNECTED_TSI_FLOOR}%). The correct slice must still pick up "
        "genuine spillover, otherwise the iid test above is passing vacuously."
    )


def _scan_for_bad_decomp_subscript() -> list[str]:
    """Find `<something>.decomp[-1]` -- a bare negative index on the VARIABLE axis.

    Correct call sites index the variable axis first (`decomp[i][-1]`,
    `decomp[1][h-1, 0]`) or slice it explicitly (`decomp[:, -1, :]`). Only a
    single bare `-1` subscript directly on `.decomp` is the bug pattern.
    """
    hits: list[str] = []
    for directory in SCAN_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue  # silent-ok: non-parseable file is not a FEVD call site
            for node in ast.walk(tree):
                if not isinstance(node, ast.Subscript):
                    continue
                value = node.value
                if not (isinstance(value, ast.Attribute) and value.attr == "decomp"):
                    continue
                index = node.slice
                if (
                    isinstance(index, ast.UnaryOp)
                    and isinstance(index.op, ast.USub)
                    and isinstance(index.operand, ast.Constant)
                ):
                    rel = path.relative_to(REPO_ROOT)
                    hits.append(f"{rel}:{node.lineno}")
    return hits


def test_no_bare_negative_index_on_fevd_decomp() -> None:
    """Clean-tree: nobody may write `fevd.decomp[-1]` to get a spillover matrix."""
    hits = _scan_for_bad_decomp_subscript()

    assert not hits, (
        "`.decomp[-1]` indexes the VARIABLE axis, not the horizon axis -- it "
        "returns the last variable's (horizon, n) table, not the n x n "
        "connectedness matrix:\n\n"
        + "\n".join(f"  - {h}" for h in hits)
        + "\n\nUse `fevd.decomp[:, -1, :]` for the final-horizon Diebold-Yilmaz "
        "table. See docs/error_log.md 2026-07-11 (k865) and "
        "experiments/k865/k865_vol_spillover_network.py:fit_var_fevd."
    )
