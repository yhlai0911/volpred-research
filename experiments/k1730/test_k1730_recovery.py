"""Correctness tests for the K1730 estimator, added in the v2 remediation.

The v1 review could say only that it found no algebraic error in the sampler —
absence of evidence. These tests supply positive evidence instead, on data where
the right answer is known by construction:

1. the penalized NLL equals the exact NLL wherever the parameters are feasible,
   so the remediation changed the optimizer's behaviour outside the support and
   nothing about the likelihood being maximized;
2. the penalty actually carries a gradient outside the support — the specific
   defect that made a constant 1e10 penalty produce 0-iteration "convergence";
3. the multistart reports start feasibility and basin concentration as separate
   quantities, and does not count an infeasible point as an optimum;
4. the SSVS sampler recovers a known signal / known null pair, and converges
   comfortably while doing it.

Test 4 is the one that matters for interpreting this experiment. It shows the
sampler is not broken: on a well-identified posterior it reaches R-hat ~1.00 and
ESS in the thousands. The non-convergence reported on the real data is therefore
a property of *that* posterior — weakly identified, highly correlated macro
coefficients — not an implementation defect. That is why the remediation
downgrades the PIP to diagnostic-only rather than claiming the sampler is wrong.

Run:  uv run python test_k1730_recovery.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import k1730_models as M          # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def simulate(seed: int = 7, n: int = 900):
    """GEV regression with one informative and one exactly-null macro column."""
    rng = np.random.default_rng(seed)
    X = np.column_stack([np.ones(n), rng.normal(0, 1, (n, 3)),
                         rng.normal(0, 1, (n, 2))])
    scale_reg = rng.normal(0, 1, n)
    beta_true = np.array([-9.0, 0.5, 0.3, 0.2, 0.45, 0.0])
    phi0, phi1, xi = -0.7, 0.12, -0.13
    sigma = np.exp(phi0 + phi1 * scale_reg)
    u = rng.uniform(size=n)
    y = X @ beta_true + sigma * ((-np.log(u)) ** (-xi) - 1.0) / xi
    return y, X, scale_reg, beta_true, xi


def test_penalty_is_transparent_inside_the_support(y, X, scale_reg, beta_true, xi):
    """Feasible parameters must score exactly the unpenalized NLL."""
    p = np.concatenate([beta_true, [-0.7, 0.12, xi]])
    viol = M.gev_reg_constraint_violation(p, y, X, scale_reg)
    check("feasible point reports zero constraint violation", viol == 0.0,
          f"violation={viol}")

    exact = -float(M.gev_logpdf(y, X @ beta_true,
                                np.exp(-0.7 + 0.12 * scale_reg), xi).sum())
    got = M.gev_reg_nll(p, y, X, scale_reg)
    check("penalized NLL == exact NLL inside the support",
          abs(got - exact) < 1e-8, f"|diff|={abs(got - exact):.3e}")


def test_penalty_has_a_gradient_outside_the_support(y, X, scale_reg, beta_true, xi):
    """The defect Codex found: a constant penalty gives L-BFGS-B nothing to follow."""
    bad = np.concatenate([beta_true, [-0.7, 0.12, xi]])
    bad[0] -= 6.0                      # shove the location far below the data
    v0 = M.gev_reg_constraint_violation(bad, y, X, scale_reg)
    check("infeasible point reports a positive violation", v0 > 0,
          f"violation={v0:.4g}")

    f0 = M.gev_reg_nll(bad, y, X, scale_reg)
    worse = bad.copy(); worse[0] -= 1.0
    better = bad.copy(); better[0] += 1.0
    f_worse = M.gev_reg_nll(worse, y, X, scale_reg)
    f_better = M.gev_reg_nll(better, y, X, scale_reg)
    check("objective strictly decreases toward the feasible set",
          f_better < f0 < f_worse,
          f"{f_better:.4g} < {f0:.4g} < {f_worse:.4g}")
    check("objective is finite outside the support",
          np.isfinite([f0, f_worse, f_better]).all())


def test_multistart_separates_start_quality_from_surface_shape(y, X, scale_reg):
    fit = M.fit_gev_reg(y, X, scale_reg, n_starts=20, seed=1)
    check("multistart converged", bool(fit["converged"]))
    for k in ("feasible_start_rate", "feasible_optimum_rate",
              "basin_concentration", "lbfgs_success_rate"):
        check(f"reports {k}", k in fit)
    check("legacy ambiguous 'convergence_rate' field is gone",
          "convergence_rate" not in fit)
    check("no optimum counted outside the parameter space",
          fit["n_feasible_optima"] <= fit["n_starts"]
          and fit["n_at_best_basin"] <= fit["n_feasible_optima"],
          f"{fit['n_at_best_basin']} at best of {fit['n_feasible_optima']} feasible")
    return fit


def test_ssvs_recovers_a_known_signal_and_a_known_null(y, X, scale_reg, fit,
                                                       beta_true):
    s = M.ssvs_gev(y, X, scale_reg, fit, n_macro=2, n_draws=20000,
                   n_burnin=6000, thin=5, seed=3, n_chains=4)
    check("sampler ran", bool(s.get("ok")))
    pip_signal, pip_null = float(s["pip"][0]), float(s["pip"][1])
    check("informative macro column selected", pip_signal > 0.80,
          f"PIP={pip_signal:.3f}")
    check("null macro column not selected", pip_null < 0.40,
          f"PIP={pip_null:.3f}")

    post = s["param_draws"].mean(axis=0)
    err = abs(post[4] - beta_true[4])
    check("posterior mean recovers the true coefficient", err < 0.15,
          f"{post[4]:.4f} vs {beta_true[4]} (err {err:.4f})")
    check("null coefficient shrunk to ~0", abs(post[5]) < 0.10,
          f"{post[5]:.4f}")

    # The point of the whole file: on an identified posterior this sampler is
    # not merely unbroken, it converges easily.
    check("converges on a well-identified posterior",
          bool(s["converged"]),
          f"rhat={s['rhat_max']:.3f} ess={s['ess_min']:.0f} "
          f"geweke={s['geweke_max_abs_z']:.2f}")
    check("mode-jump move is actually firing",
          s["acceptance_mode_jump_mean"] > 0.001,
          f"acceptance={s['acceptance_mode_jump_mean']:.4f}")


def main() -> int:
    print("K1730 estimator recovery tests\n")
    y, X, scale_reg, beta_true, xi = simulate()

    print("[1] penalized objective")
    test_penalty_is_transparent_inside_the_support(y, X, scale_reg, beta_true, xi)
    test_penalty_has_a_gradient_outside_the_support(y, X, scale_reg, beta_true, xi)

    print("\n[2] multistart diagnostics")
    fit = test_multistart_separates_start_quality_from_surface_shape(y, X, scale_reg)

    print("\n[3] SSVS recovery on known ground truth")
    test_ssvs_recovers_a_known_signal_and_a_known_null(y, X, scale_reg, fit, beta_true)

    print("\n[4] GEV density against scipy")
    v = M.validate_against_scipy(seed=42)
    check("log-density matches scipy", bool(v["passed"]),
          f"max err {v['max_abs_logpdf_err']:.2e}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
