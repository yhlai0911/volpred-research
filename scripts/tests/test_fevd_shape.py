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


# A site may reproduce the bug ON PURPOSE -- k1025 v3 recomputes v2's mis-sliced index
# so the before/after correction is a measured number rather than an assertion. Such a
# site must say so on the offending line, mirroring the `# silent-ok:` convention in
# .claude/rules/no-silent-fallback.md. The marker is deliberately ugly and greppable:
# it must never appear on a line whose value feeds a published statistic.
BUG_REPRO_MARKER = "# fevd-bug-reproduction:"


def _scan_for_bad_decomp_subscript() -> list[str]:
    """Find `<something>.decomp[-1]` -- a bare negative index on the VARIABLE axis.

    Correct call sites index the variable axis first (`decomp[i][-1]`,
    `decomp[1][h-1, 0]`) or slice it explicitly (`decomp[:, -1, :]`). Only a
    single bare `-1` subscript directly on `.decomp` is the bug pattern.
    """
    hits: list[str] = []
    for directory in SCAN_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            source = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue  # silent-ok: non-parseable file is not a FEVD call site
            lines = source.splitlines()
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
                    line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    if BUG_REPRO_MARKER in line:
                        continue  # deliberate, marked, before/after demonstration
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
        "experiments/k865/k865_vol_spillover_network.py:fit_var_fevd.\n"
        f"If a site reproduces the bug ON PURPOSE, mark that line `{BUG_REPRO_MARKER} "
        "<reason>` -- and never let its value reach a published number."
    )


def test_bug_reproduction_marker_is_not_being_used_to_smuggle_the_bug_back() -> None:
    """The escape hatch must stay a hatch. Only k1025 v3's before/after may use it."""
    allowed = {"experiments/k1025/k1025_v3.py"}
    this_file = Path(__file__).resolve()  # defines the marker; would otherwise flag itself
    marked = {
        str(path.relative_to(REPO_ROOT))
        for directory in SCAN_DIRS
        for path in (REPO_ROOT / directory).rglob("*.py")
        if path.resolve() != this_file
        and BUG_REPRO_MARKER in path.read_text(encoding="utf-8", errors="replace")
    }

    assert marked <= allowed, (
        f"`{BUG_REPRO_MARKER}` appeared in files that are not sanctioned bug "
        f"demonstrations: {sorted(marked - allowed)}. The marker suppresses the "
        "clean-tree scan above; it exists solely so k1025 v3 can MEASURE the size of "
        "the v2 error. Do not use it to keep a mis-sliced number in production."
    )


# ---------------------------------------------------------------------------
# k1025 v3 (2026-07-12): the SHIPPED pipeline, not a re-implementation.
#
# Everything above validates the raw statsmodels slice against a TSI helper defined
# locally in this file. That leaves a gap: an experiment can slice correctly and
# still ship a broken connectedness table, and it says nothing about the KPPS
# GENERALIZED FEVD, which k1025 v3 introduces and which is the estimator the
# crypto-fear paper's net-direction claim now rests on.
#
# These tests import k1025_v3's ACTUAL functions and run the placebo through them.
# Extending this file rather than adding test_fevd_iid_placebo.py is deliberate:
# same concern, one enforcement owner (CLAUDE.md anti-stacking; the k865 remediation
# in docs/error_log.md names this file as the sole owner).
# ---------------------------------------------------------------------------

# The brief's threshold for the iid placebo. The measured value is ~0.4%, so this is
# a very loose ceiling -- it is set where it is because ANY value near it already
# means the pipeline is mis-slicing, and the buggy slice lands at ~67%.
SHIPPED_IID_TSI_CEILING = 15.0


def _load_k1025_v3():
    """Import the experiment module by path (experiments/ is not an importable package)."""
    import importlib.util

    path = REPO_ROOT / "experiments" / "k1025" / "k1025_v3.py"
    if not path.exists():
        pytest.skip(f"{path.relative_to(REPO_ROOT)} not present")
    spec = importlib.util.spec_from_file_location("k1025_v3", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _iid_var(seed: int, obs: int = 2000, lags: int = 3):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(rng.standard_normal((obs, 3)), columns=["BTC_RV", "SPY_RV", "VIX"])
    return VAR(df).fit(lags)


def _chain_var(seed: int = 11, obs: int = 2000):
    """A deliberately connected system: BTC_RV -> SPY_RV -> VIX."""
    rng = np.random.default_rng(seed)
    e = rng.standard_normal((obs, 3))
    x = np.zeros((obs, 3))
    for t in range(1, obs):
        x[t, 0] = 0.5 * x[t - 1, 0] + e[t, 0]
        x[t, 1] = 0.8 * x[t - 1, 0] + e[t, 1]
        x[t, 2] = 0.8 * x[t - 1, 1] + e[t, 2]
    return VAR(pd.DataFrame(x, columns=["BTC_RV", "SPY_RV", "VIX"])).fit(2)


@pytest.mark.parametrize("seed", [0, 1, 42, 1025])
def test_shipped_pipeline_gives_near_zero_connectedness_on_iid(seed: int) -> None:
    """THE PLACEBO. Independent series have zero true connectedness; the shipped
    generalized + Cholesky estimators must both say so. The k1025 v2 mis-slice
    returned ~67% on exactly this input and shipped it as a 90% finding."""
    mod = _load_k1025_v3()
    res = _iid_var(seed)

    gen = mod.connectedness(mod.generalized_fevd(res))["total_connectedness"]
    chol = mod.connectedness(mod.cholesky_fevd(res))["total_connectedness"]

    assert gen < SHIPPED_IID_TSI_CEILING, (
        f"generalized FEVD reported {gen:.2f}% total connectedness on iid Gaussian "
        f"noise (ceiling {SHIPPED_IID_TSI_CEILING}%). True connectedness is 0."
    )
    assert chol < SHIPPED_IID_TSI_CEILING, (
        f"Cholesky FEVD reported {chol:.2f}% total connectedness on iid Gaussian "
        f"noise (ceiling {SHIPPED_IID_TSI_CEILING}%). True connectedness is 0."
    )


def test_shipped_pipeline_still_detects_real_connectedness() -> None:
    """Non-vacuity: an estimator that always returns ~0 would pass the placebo."""
    mod = _load_k1025_v3()
    gen = mod.connectedness(mod.generalized_fevd(_chain_var()))["total_connectedness"]

    assert gen > CONNECTED_TSI_FLOOR, (
        f"A deliberately connected BTC->SPY->VIX chain gave only {gen:.2f}% "
        f"connectedness (floor {CONNECTED_TSI_FLOOR}%); the placebo above would be "
        "passing vacuously."
    )


def test_generalized_fevd_equals_cholesky_when_shocks_are_orthogonal() -> None:
    """Analytic anchor: with a diagonal residual covariance there is nothing to
    orthogonalise, so KPPS and Cholesky must coincide. This pins the generalized
    formula itself, not just its symmetry."""
    mod = _load_k1025_v3()
    rng = np.random.default_rng(5)
    obs = 4000
    e = rng.standard_normal((obs, 3)) * np.array([1.0, 2.0, 0.5])
    x = np.zeros((obs, 3))
    for t in range(1, obs):
        x[t, 0] = 0.5 * x[t - 1, 0] + e[t, 0]
        x[t, 1] = 0.6 * x[t - 1, 0] + 0.3 * x[t - 1, 1] + e[t, 1]
        x[t, 2] = 0.4 * x[t - 1, 1] + 0.2 * x[t - 1, 2] + e[t, 2]
    res = VAR(pd.DataFrame(x, columns=["BTC_RV", "SPY_RV", "VIX"])).fit(2)

    gen = mod.generalized_fevd(res)
    gen = gen / gen.sum(axis=1, keepdims=True)
    chol = mod.cholesky_fevd(res)

    # Sampling leaves a little correlation in the estimated residuals, so this is
    # "agree to within the residual off-diagonal", not exact equality.
    np.testing.assert_allclose(gen, chol, atol=5e-3)


def _correlated_var(seed: int = 11, obs: int = 2000):
    """A chain DGP with CONTEMPORANEOUSLY CORRELATED innovations.

    The correlation is the point. With orthogonal shocks the Cholesky factor is
    already diagonal, so Cholesky and KPPS agree and BOTH look order-invariant --
    an order-invariance test built on such a DGP proves nothing.
    """
    rng = np.random.default_rng(seed)
    chol_factor = np.array([[1.0, 0.0, 0.0], [0.7, 0.8, 0.0], [0.5, 0.6, 0.7]])
    e = rng.standard_normal((obs, 3)) @ chol_factor.T
    x = np.zeros((obs, 3))
    for t in range(1, obs):
        x[t, 0] = 0.5 * x[t - 1, 0] + e[t, 0]
        x[t, 1] = 0.6 * x[t - 1, 0] + 0.3 * x[t - 1, 1] + e[t, 1]
        x[t, 2] = 0.5 * x[t - 1, 1] + 0.2 * x[t - 1, 2] + e[t, 2]
    return pd.DataFrame(x, columns=["BTC_RV", "SPY_RV", "VIX"])


def test_generalized_fevd_is_order_invariant_but_cholesky_is_not() -> None:
    """The property the paper's net-direction claim depends on.

    The crypto-fear headline is a claim about the SIGN of BTC's net connectedness.
    Under Cholesky that sign flips with the variable ordering (measured on the real
    data: +6.79pp under {BTC,SPY,VIX} vs -10.28pp under {VIX,SPY,BTC}), so no
    Cholesky ordering can support it. KPPS does not orthogonalise, so it is
    invariant by construction -- and this test is what keeps it that way.
    """
    mod = _load_k1025_v3()
    data = _correlated_var()
    perm = ["VIX", "BTC_RV", "SPY_RV"]
    res = VAR(data).fit(2)
    res_p = VAR(data[perm]).fit(2)

    base_gen = mod.connectedness(mod.generalized_fevd(res))
    perm_gen = mod.connectedness(mod.generalized_fevd(res_p), names=tuple(perm))
    assert base_gen["total_connectedness"] == pytest.approx(
        perm_gen["total_connectedness"], abs=1e-8
    ), "generalized FEVD must be invariant to variable ordering -- it is not."
    for name in ("BTC_RV", "SPY_RV", "VIX"):
        assert base_gen["net"][name] == pytest.approx(perm_gen["net"][name], abs=1e-8), (
            f"generalized net connectedness for {name} moved when the variables were "
            "reordered; the KPPS implementation is not order-invariant."
        )

    # Discriminating half: Cholesky genuinely IS order-dependent on this DGP (measured
    # BTC net swing ~91pp), so the invariance above is a real property of KPPS rather
    # than an artifact of a DGP under which nothing could have moved.
    base_chol = mod.connectedness(mod.cholesky_fevd(res))
    perm_chol = mod.connectedness(mod.cholesky_fevd(res_p), names=tuple(perm))
    assert abs(base_chol["net"]["BTC_RV"] - perm_chol["net"]["BTC_RV"]) > 10.0, (
        "Cholesky net connectedness did not move under reordering. Either the DGP "
        "stopped being order-sensitive or cholesky_fevd is silently generalized -- "
        "in both cases the invariance test above proves nothing."
    )
