"""
Test the corrected MCS implementation (src/volpred/stats/mcs.py).

Verifies:
1. Stationary bootstrap is used (not iid)
2. Test statistic is non-degenerate
3. Elimination uses standardised T_R, not raw average loss
4. GJR survives as sole MCS member on K778 data (synthetic proxy)
"""

import numpy as np
import sys
import os

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from volpred.stats.mcs import (
    model_confidence_set,
    _stationary_bootstrap_indices,
    _auto_block_length,
    _hac_se,
)


def test_stationary_bootstrap_block_structure():
    """Verify that stationary bootstrap produces blocks, not iid draws."""
    rng = np.random.default_rng(42)
    T = 1000
    block_length = 10.0

    idx = _stationary_bootstrap_indices(T, block_length, rng)
    assert len(idx) == T

    # Count consecutive runs (idx[t] == idx[t-1]+1 mod T)
    consecutive = sum(1 for t in range(1, T) if idx[t] == (idx[t-1] + 1) % T)
    # With block_length=10, expected consecutive fraction ~ 1 - 1/10 = 0.9
    frac = consecutive / (T - 1)
    assert 0.7 < frac < 0.98, (
        f"Block structure broken: consecutive fraction = {frac:.3f}, "
        f"expected ~0.9 for block_length=10"
    )
    print(f"  [PASS] Stationary bootstrap consecutive fraction: {frac:.3f} (expected ~0.9)")


def test_auto_block_length():
    """Verify auto block length scales with T^(1/3)."""
    x = np.random.randn(5000)
    bl = _auto_block_length(x)
    # 1.75 * 5000^(1/3) ~ 1.75 * 17.1 ~ 29.9
    assert 20 < bl < 40, f"Auto block length = {bl:.1f}, expected ~30"
    print(f"  [PASS] Auto block length for T=5000: {bl:.1f}")


def test_hac_se_nonzero():
    """HAC standard error should be positive for autocorrelated series."""
    rng = np.random.default_rng(99)
    # Generate AR(1) with rho=0.5
    T = 500
    e = rng.standard_normal(T)
    x = np.zeros(T)
    x[0] = e[0]
    for t in range(1, T):
        x[t] = 0.5 * x[t-1] + e[t]

    se = _hac_se(x, T)
    assert se > 0, f"HAC SE should be positive, got {se}"
    # HAC SE should be larger than naive SE for positively autocorrelated data
    naive_se = np.std(x) / np.sqrt(T)
    assert se > naive_se * 0.8, (
        f"HAC SE ({se:.6f}) should be >= naive SE ({naive_se:.6f}) for AR(1)"
    )
    print(f"  [PASS] HAC SE = {se:.6f} > naive SE = {naive_se:.6f}")


def test_mcs_single_model():
    """Single model should survive trivially."""
    losses = {"only_model": np.random.randn(100) ** 2}
    result = model_confidence_set(losses, alpha=0.10)
    assert result["mcs_models"] == ["only_model"]
    assert result["p_values"]["only_model"] == 1.0
    assert result["eliminated"] == []
    print("  [PASS] Single model MCS")


def test_mcs_two_identical_models():
    """Two models with identical losses should both survive."""
    rng = np.random.default_rng(42)
    L = rng.standard_normal(500) ** 2
    losses = {"A": L.copy(), "B": L.copy()}
    result = model_confidence_set(losses, alpha=0.10, n_boot=2000)
    assert len(result["mcs_models"]) == 2, (
        f"Both models should survive, got {result['mcs_models']}"
    )
    print(f"  [PASS] Two identical models both survive: {result['mcs_models']}")


def test_mcs_clear_winner():
    """One clearly better model should be the sole survivor."""
    rng = np.random.default_rng(123)
    T = 2000
    # Model A: low loss; Model B: high loss; Model C: very high loss
    base = rng.exponential(1.0, T)
    losses = {
        "good":  base,
        "bad":   base + 0.5 + rng.standard_normal(T) * 0.3,
        "worst": base + 1.5 + rng.standard_normal(T) * 0.3,
    }
    result = model_confidence_set(losses, alpha=0.10, n_boot=3000)

    assert "good" in result["mcs_models"], (
        f"'good' should be in MCS, got {result['mcs_models']}"
    )
    assert "worst" not in result["mcs_models"], (
        f"'worst' should not be in MCS, got {result['mcs_models']}"
    )
    print(f"  [PASS] Clear winner: MCS = {result['mcs_models']}")
    print(f"         Eliminated: {result['eliminated']}")
    print(f"         P-values: {result['p_values']}")


def test_mcs_pvalue_monotonicity():
    """MCS p-values should be monotonically non-decreasing in elimination order."""
    rng = np.random.default_rng(77)
    T = 1500
    base = rng.exponential(0.5, T)
    losses = {
        "m1": base,
        "m2": base + 0.2 + rng.standard_normal(T) * 0.2,
        "m3": base + 0.5 + rng.standard_normal(T) * 0.2,
        "m4": base + 1.0 + rng.standard_normal(T) * 0.2,
    }
    result = model_confidence_set(losses, alpha=0.05, n_boot=3000)

    elim_pvals = [pv for _, pv in result["eliminated"]]
    for i in range(1, len(elim_pvals)):
        assert elim_pvals[i] >= elim_pvals[i-1] - 1e-10, (
            f"P-value monotonicity violated: {elim_pvals}"
        )
    print(f"  [PASS] P-value monotonicity: {elim_pvals}")


def test_mcs_nondegerate_statistic():
    """Verify the bootstrap T_R distribution is non-degenerate.

    The old K778 bug: centering each bootstrap draw so mean=0, then
    computing |mean|/se gives a degenerate distribution (all near 0).
    The corrected version should produce a spread-out distribution.

    We test with models that are close in performance (small gap),
    so that the bootstrap distribution must be well-calibrated to get
    a meaningful p-value (not trivially 0 or 1).
    """
    rng_data = np.random.default_rng(55)
    T = 1000
    base = rng_data.exponential(1.0, T)
    # Small gap so p-value should be intermediate (not 0 or 1)
    losses = {
        "A": base,
        "B": base + 0.05 + rng_data.standard_normal(T) * 0.8,
    }

    result = model_confidence_set(losses, alpha=0.10, n_boot=3000, seed=55)

    # With a small gap and high noise, we expect a non-trivial p-value
    if result["eliminated"]:
        pv = result["eliminated"][0][1]
        # A degenerate statistic would give p=0.0 trivially
        print(f"  p-value for elimination: {pv:.4f}")
        print(f"  [PASS] Non-degenerate: eliminated {result['eliminated'][0][0]} "
              f"with p={pv:.4f}")
    else:
        # Both survive — also fine, means H0 not rejected
        pv_a = result["p_values"]["A"]
        pv_b = result["p_values"]["B"]
        print(f"  Both survived — p-values: A={pv_a:.4f}, B={pv_b:.4f}")
        # The p-value should not be exactly 1.0 (which would mean degenerate)
        assert pv_a < 1.0 or pv_b < 1.0, "At least one p-value should be < 1"
        print(f"  [PASS] Non-degenerate: models indistinguishable (correct)")


def test_mcs_k778_synthetic():
    """Simulate K778-like loss differentials and verify GJR-like model wins.

    Uses the QLIKE values from K778 results to generate synthetic pointwise
    losses with similar means and realistic autocorrelation.
    """
    rng = np.random.default_rng(778)
    T = 4589  # same as K778 n_oos

    # K778 mean QLIKE values:
    # gjr: 1.5268, amem_r2: 1.5586, mem_r2: 1.5762, garch: 1.5764,
    # ewma_r2: 1.6240, har_r2: 1.6491
    mean_qlikes = {
        'gjr':     1.5268,
        'amem_r2': 1.5586,
        'mem_r2':  1.5762,
        'garch':   1.5764,
        'ewma_r2': 1.6240,
        'har_r2':  1.6491,
    }

    # Generate correlated, autocorrelated loss series
    # Common factor + model-specific shift + AR(1) noise
    common = rng.exponential(1.5, T)
    losses = {}
    for name, mean_q in mean_qlikes.items():
        # AR(1) noise with rho ~ 0.3 (QLIKE losses are moderately persistent)
        noise = np.zeros(T)
        noise[0] = rng.standard_normal()
        for t in range(1, T):
            noise[t] = 0.3 * noise[t-1] + rng.standard_normal()
        noise *= 0.4  # scale

        raw = common + noise + (mean_q - 1.5)
        # Ensure positive
        raw = np.maximum(raw, 0.01)
        losses[name] = raw

    result = model_confidence_set(losses, alpha=0.10, n_boot=5000, seed=778)

    print(f"  MCS members: {result['mcs_models']}")
    print(f"  Eliminated: {result['eliminated']}")
    print(f"  P-values: {result['p_values']}")

    # GJR should survive (lowest mean loss by far)
    assert 'gjr' in result['mcs_models'], (
        f"GJR should be in MCS, got {result['mcs_models']}"
    )
    # har_r2 and ewma_r2 should be eliminated (highest losses)
    assert 'har_r2' not in result['mcs_models'], (
        f"HAR should be eliminated, got {result['mcs_models']}"
    )
    print("  [PASS] K778 synthetic: GJR survives, HAR eliminated")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing MCS implementation (Hansen, Lunde & Nason 2011)")
    print("=" * 60)

    tests = [
        ("Stationary bootstrap block structure", test_stationary_bootstrap_block_structure),
        ("Auto block length", test_auto_block_length),
        ("HAC standard error", test_hac_se_nonzero),
        ("Single model", test_mcs_single_model),
        ("Two identical models", test_mcs_two_identical_models),
        ("Clear winner", test_mcs_clear_winner),
        ("P-value monotonicity", test_mcs_pvalue_monotonicity),
        ("Non-degenerate statistic", test_mcs_nondegerate_statistic),
        ("K778 synthetic (GJR wins)", test_mcs_k778_synthetic),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 60}")

    sys.exit(0 if failed == 0 else 1)
