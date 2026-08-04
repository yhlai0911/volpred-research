"""
K1730 model layer — GEV regression with MIDAS location, SSVS variable selection,
and the three baselines it is scored against.

Model
-----
For week ``w`` the target ``y_w`` is the log of the maximum daily realized
variance inside the week. We model it as

    y_w ~ GEV(mu_w, sigma_w, xi)
    mu_w      = b0 + g_d*HAR_d + g_w*HAR_w + g_m*HAR_m + sum_j theta_j * Z_j(omega)
    log sig_w = p0 + p1 * HAR_m
    xi        = constant
    Z_j(omega) = sum_k beta_weight_k(omega) * X_{j, m-k}     (K=12 monthly lags)

The Beta weight function is the one-parameter form used in ``k526``. The scale
is allowed to move with the trailing volatility level because vol-of-vol scales
with the level of vol; holding sigma constant would force the shape parameter to
absorb that, which is exactly where GEV fits go wrong.

**Honest framing of the GEV assumption.** The block size here is one week (~5
trading days). Classical extreme-value theory justifies GEV as the *asymptotic*
law of a block maximum as block size → infinity; with n=5 that asymptotic
argument does not hold, and we do not claim it does. GEV is used here as a
flexible three-parameter right-skewed family for a block maximum — the shape
parameter xi is estimated, not assumed — and the README states this limitation
rather than dressing the fit in EVT authority it has not earned.

Numerics
--------
The GEV log-density is implemented directly in numpy for speed (the MCMC needs
millions of evaluations). :func:`validate_against_scipy` checks it against
``scipy.stats.genextreme.logpdf`` to 1e-10 on random inputs, including the
xi -> 0 Gumbel limit, and is called at import time by the driver. Note scipy's
shape parameter is ``c = -xi`` relative to the standard EVT convention used
throughout this file.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy import optimize, special, stats

# --------------------------------------------------------------------------
# MIDAS weights
# --------------------------------------------------------------------------

def beta_weights(n_lags: int, omega: float) -> np.ndarray:
    """One-parameter Beta polynomial MIDAS weights (omega_1 = 1), as in k526.

    omega = 1 gives equal weights; larger omega concentrates mass on recent lags.
    """
    k = np.arange(1, n_lags + 1, dtype=float)
    base = np.maximum(1.0 - k / (n_lags + 1.0), 1e-10)
    w = base ** (omega - 1.0)
    total = w.sum()
    return w / total if total > 0 else np.full(n_lags, 1.0 / n_lags)


def midas_aggregate(tensor: np.ndarray, omega: float) -> np.ndarray:
    """(n_obs, n_vars, n_lags) tensor → (n_obs, n_vars) MIDAS-weighted regressors."""
    w = beta_weights(tensor.shape[2], omega)
    return tensor @ w


# --------------------------------------------------------------------------
# GEV log-density, quantile, expected shortfall
# --------------------------------------------------------------------------

# The exact branch uses log1p(xi*z) rather than log(1 + xi*z). Forming the sum
# 1 + xi*z first is what destroys precision as xi -> 0 (it is the cancellation
# that costs scipy ~4 digits at c = -1e-9); log1p never forms it. With that
# fixed the exact branch stays accurate to machine precision far below the
# threshold, so _XI_EPS only has to avoid the literal 1/xi division.
_XI_EPS = 1e-10         # below this |xi| we use the Gumbel limit
_NEG_INF = -1e12        # finite sentinel: optimizers handle it, -inf breaks them


def gev_logpdf(y: np.ndarray, mu: np.ndarray, sigma: np.ndarray, xi: float,
               t_floor: float | None = None) -> np.ndarray:
    """log f(y; mu, sigma, xi) in the standard EVT convention (scipy c = -xi).

    ``t_floor`` clamps the support argument ``t = 1 + xi*z`` from below instead
    of returning the out-of-support sentinel. That is *not* the density — it is
    a finite continuation used only by :func:`gev_reg_nll`, which pairs it with
    an explicit exterior penalty that carries the gradient in that region. With
    ``t_floor=None`` (the default, and what :func:`validate_against_scipy`
    exercises) the function is the exact log-density.
    """
    sigma = np.asarray(sigma, dtype=float)
    if np.any(sigma <= 0) or not np.isfinite(sigma).all():
        return np.full(np.shape(y), _NEG_INF)
    z = (np.asarray(y, dtype=float) - mu) / sigma

    if abs(xi) < _XI_EPS:
        return -np.log(sigma) - z - np.exp(-z)

    xz = xi * z
    out = np.full(np.shape(z), _NEG_INF)
    if t_floor is None:
        ok = xz > -1.0 + 1e-300          # outside the support the density is 0
    else:
        ok = np.ones(np.shape(z), dtype=bool)
        xz = np.maximum(xz, -1.0 + t_floor)
    if not np.any(ok):
        return out
    log_t = np.log1p(xz[ok])
    sig_ok = sigma[ok] if np.ndim(sigma) else sigma
    # Clip before exponentiating. Far outside the fitted region -log_t/xi can
    # exceed 709 and overflow to +inf; the density there is zero to any
    # precision that matters, so saturating at the sentinel is exact in effect
    # and keeps the optimizer from seeing a NaN instead of a very bad value.
    expo = np.clip(-log_t / xi, -700.0, 700.0)
    out[ok] = (-np.log(sig_ok)
               - (1.0 + 1.0 / xi) * log_t
               - np.exp(expo))
    return np.maximum(out, _NEG_INF)


def gev_quantile(p, mu, sigma, xi: float):
    """Inverse CDF. p may be scalar or array; mu/sigma broadcast against it."""
    p = np.asarray(p, dtype=float)
    a = -np.log(p)
    if abs(xi) < _XI_EPS:
        return mu - sigma * np.log(a)
    return mu + sigma * (a ** (-xi) - 1.0) / xi


def gev_cdf(y, mu, sigma, xi: float):
    z = (np.asarray(y, dtype=float) - mu) / sigma
    if abs(xi) < _XI_EPS:
        return np.exp(-np.exp(-z))
    xz = xi * z
    inside = xz > -1.0
    log_t = np.log1p(np.where(inside, xz, 0.0))
    out = np.where(inside, np.exp(-np.exp(-log_t / xi)), 0.0)
    # Outside the support: for xi > 0 the violated bound is the lower one (CDF 0,
    # already set); for xi < 0 it is the upper one, where the CDF is 1.
    if xi < 0:
        out = np.where(inside, out, 1.0)
    return out


@lru_cache(maxsize=64)
def _gumbel_es_constant(p: float) -> float:
    """(1/(1-p)) * integral of -log(-log u) over [p, 1].

    The Gumbel quantile is mu - sigma*log(-log u), so the tail mean factorizes
    into mu + sigma * (this constant) and the integral depends only on p. That
    makes an accurate quadrature affordable: it is evaluated once per distinct
    coverage level, not once per forecast. (The naive alternative — taking the
    xi -> 0 limit of the general formula — is a 0/0 form in xi.)
    """
    from scipy import integrate
    val, _ = integrate.quad(lambda u: -np.log(-np.log(u)), p, 1.0,
                            limit=500, epsabs=1e-13, epsrel=1e-13)
    return val / (1.0 - p)


def gev_expected_shortfall(p: float, mu, sigma, xi: float):
    """E[Y | Y > Q(p)] — the mean of the upper (1-p) tail.

    Closed form via the lower incomplete gamma:
        ES_p = mu + (sigma/xi) * [ gamma(1-xi, -log p) / (1-p) - 1 ],  xi < 1
    where gamma(s, a) is the *unregularized* lower incomplete gamma. Validated
    against Monte Carlo in :func:`validate_against_scipy`.
    """
    a = -np.log(p)
    if abs(xi) < _XI_EPS:
        return mu + sigma * _gumbel_es_constant(float(p))
    if xi >= 1.0:
        return np.full(np.shape(mu), np.nan)   # mean does not exist
    inc = special.gammainc(1.0 - xi, a) * special.gamma(1.0 - xi)
    return mu + sigma * (inc / (1.0 - p) - 1.0) / xi


def validate_against_scipy(seed: int = 42, tol: float = 1e-10) -> dict:
    """Assert the hand-rolled GEV matches scipy, including the Gumbel limit.

    The xi grid deliberately excludes the interval 0 < |xi| < 1e-3. There, the
    general GEV form evaluates ``(1 + xi*z)**(-1/xi)`` as ``exp(-log1p(xi*z)/xi)``
    — a ratio of two quantities both going to zero — and scipy's implementation
    loses ~4 significant digits (measured: 2.5e-4 absolute log-density error at
    c=-1e-9, against a Gumbel limit that is accurate to machine precision).
    That is scipy's error, not ours, which is precisely why :func:`gev_logpdf`
    switches to the closed-form Gumbel limit below ``_XI_EPS``. The limit itself
    is checked separately below by convergence from the exact branch.
    """
    rng = np.random.default_rng(seed)
    report = {}
    max_err = 0.0
    for xi in (-0.35, -0.1, 0.0, 0.15, 0.4, 0.8):
        mu = rng.normal(-9, 1, 500)
        sigma = np.exp(rng.normal(-0.5, 0.3, 500))
        y = mu + sigma * rng.normal(0, 2, 500)
        ours = gev_logpdf(y, mu, sigma, xi)
        theirs = stats.genextreme.logpdf(y, c=-xi, loc=mu, scale=sigma)
        both = np.isfinite(ours) & np.isfinite(theirs)
        err = float(np.max(np.abs(ours[both] - theirs[both]))) if both.any() else 0.0
        # Support disagreement would be a real bug, so check it separately.
        support_mismatch = int(np.sum(np.isfinite(theirs) & (ours <= _NEG_INF / 2)))
        max_err = max(max_err, err)
        report[f"xi={xi}"] = {"max_abs_logpdf_err": err,
                             "support_mismatch": support_mismatch,
                             "n_finite": int(both.sum())}
        assert err < tol, f"GEV logpdf mismatch at xi={xi}: {err}"
        assert support_mismatch == 0, f"GEV support mismatch at xi={xi}"

        # Quantile round-trip against scipy's ppf.
        q_ours = gev_quantile(np.array([0.05, 0.5, 0.95, 0.99]), mu[0], sigma[0], xi)
        q_scipy = stats.genextreme.ppf([0.05, 0.5, 0.95, 0.99], c=-xi,
                                       loc=mu[0], scale=sigma[0])
        qerr = float(np.max(np.abs(q_ours - q_scipy)))
        assert qerr < 1e-8, f"GEV quantile mismatch at xi={xi}: {qerr}"
        report[f"xi={xi}"]["max_abs_quantile_err"] = qerr

    # Gumbel limit: the exact branch must converge to the Gumbel branch as
    # xi -> 0, at the O(xi) rate the Taylor expansion predicts. This validates
    # the branch scipy could not adjudicate.
    mu = rng.normal(-9, 1, 500)
    sigma = np.exp(rng.normal(-0.5, 0.3, 500))
    y = mu + sigma * rng.normal(0, 2, 500)
    gumbel = gev_logpdf(y, mu, sigma, 0.0)
    # Restrict to the region carrying appreciable probability mass. The leading
    # correction term is O(xi * exp(-z) * z^2), so at z = -8 — where the log
    # density is already about -3000 and the point is numerically impossible —
    # it blows up for any xi. Agreement there is neither achievable nor useful;
    # agreement where the likelihood actually gets evaluated is both.
    mass = gumbel > -50.0
    limit_errs = {"n_compared": int(mass.sum()), "n_total": int(len(gumbel))}
    ratios = []
    for xi in (1e-2, 1e-3, 1e-4):
        exact = gev_logpdf(y, mu, sigma, xi)   # above _XI_EPS → exact branch
        err = float(np.max(np.abs(exact[mass] - gumbel[mass])))
        limit_errs[f"xi={xi}"] = err
        ratios.append(err / xi)
    # The correct test is the *rate*, not an arbitrary magnitude: the leading
    # correction is O(xi), so err/xi must be constant across decades. A wrong
    # limit (or a wrong branch) would break this ratio immediately, whereas any
    # absolute bound merely encodes how much tail we chose to include.
    ratios = np.array(ratios)
    spread = float(ratios.max() / ratios.min())
    limit_errs["implied_constant"] = [float(r) for r in ratios]
    limit_errs["constant_spread"] = spread
    assert spread < 1.5, f"Gumbel limit not O(xi)-convergent: {limit_errs}"
    report["gumbel_limit_convergence"] = limit_errs

    # And where scipy could not adjudicate: with log1p in place, the exact
    # branch must agree with the Gumbel branch to near machine precision.
    tiny = gev_logpdf(y, mu, sigma, 1e-9)
    tiny_err = float(np.max(np.abs(tiny[mass] - gumbel[mass])))
    assert tiny_err < 1e-5, f"exact branch unstable at xi=1e-9: {tiny_err}"
    report["tiny_xi_exact_vs_gumbel"] = tiny_err

    # ES closed form vs numerical quadrature of the quantile function.
    #
    # The referee here is quadrature, not Monte Carlo. Simulation cannot settle
    # this question at xi = 0.4, where the tail index is 1/xi = 2.5 and the tail
    # mean converges slowly: 4M draws leave a standard error of ~0.007, so a
    # perfectly correct closed form still lands ~1% away from the MC estimate
    # a good fraction of the time. Quadrature is deterministic and agrees to
    # 1e-12. MC is retained only as an independent corroboration, and its
    # tolerance is stated in standard errors rather than as a fixed percentage.
    from scipy import integrate

    es_errs = {}
    for xi in (-0.2, 0.0, 0.2, 0.4):
        mu0, sig0, p = -9.0, 0.6, 0.95
        cf = float(gev_expected_shortfall(p, mu0, sig0, xi))
        quad, _ = integrate.quad(lambda u: gev_quantile(u, mu0, sig0, xi),
                                 p, 1.0, limit=500)
        numint = quad / (1.0 - p)

        draws = stats.genextreme.rvs(c=-xi, loc=mu0, scale=sig0, size=2_000_000,
                                     random_state=seed)
        tail = draws[draws > gev_quantile(p, mu0, sig0, xi)]
        mc = float(tail.mean())
        mc_se = float(tail.std() / np.sqrt(len(tail)))

        es_errs[f"xi={xi}"] = {
            "closed_form": cf, "quadrature": numint, "monte_carlo": mc,
            "abs_err_vs_quadrature": abs(cf - numint),
            "mc_z": (mc - cf) / mc_se if mc_se > 0 else 0.0,
        }
        assert abs(cf - numint) < 1e-6, (
            f"GEV ES closed form disagrees with quadrature at xi={xi}: "
            f"{cf} vs {numint}")
        assert abs((mc - cf) / mc_se) < 4.0, (
            f"GEV ES fails MC corroboration at xi={xi}: z={(mc - cf) / mc_se}")

    return {"logpdf_quantile": report, "expected_shortfall": es_errs,
            "max_abs_logpdf_err": max_err, "passed": True}


# --------------------------------------------------------------------------
# Design matrix
# --------------------------------------------------------------------------

HAR_NAMES = ["har_d", "har_w", "har_m"]


def build_design(weeks_df, tensor: np.ndarray, omega: float,
                 macro_names: list[str]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Location design matrix [1, HAR_d, HAR_w, HAR_m, Z_1..Z_J] and scale regressor."""
    har = weeks_df[HAR_NAMES].values.astype(float)
    z = midas_aggregate(tensor, omega)
    X = np.column_stack([np.ones(len(weeks_df)), har, z])
    scale_reg = weeks_df["har_m"].values.astype(float)
    names = ["const"] + HAR_NAMES + list(macro_names)
    return X, scale_reg, names


class Standardizer:
    """Column standardizer fitted on the estimation rows only.

    Fitting this on the full sample would leak the OOS distribution into the
    estimation window — a mild leak, but a real one, and it is free to avoid.
    """

    def __init__(self, X: np.ndarray, skip: int = 1):
        self.skip = skip
        self.mean = X[:, skip:].mean(axis=0)
        self.std = X[:, skip:].std(axis=0)
        self.std[self.std < 1e-12] = 1.0

    def apply(self, X: np.ndarray) -> np.ndarray:
        out = X.copy()
        out[:, self.skip:] = (out[:, self.skip:] - self.mean) / self.std
        return out


# --------------------------------------------------------------------------
# GEV regression MLE
# --------------------------------------------------------------------------

def _unpack(params: np.ndarray, n_beta: int):
    beta = params[:n_beta]
    phi0, phi1, xi = params[n_beta], params[n_beta + 1], params[n_beta + 2]
    return beta, phi0, phi1, xi


# Exterior-penalty constants for the constrained region of the GEV likelihood.
#
# K1730 remediation (2026-07-19), Codex finding 1. The previous version returned
# a *constant* 1e10 for any parameter vector violating the support, the xi range
# or the scale range. A constant objective has zero gradient, so L-BFGS-B started
# from an infeasible point terminated at iteration 0 and was recorded as a failed
# start. The reported "convergence rate" of 0.47-0.51 was therefore the fraction
# of random starts that happened to land inside the support, not evidence about
# the shape of the likelihood surface. Replacing the constant with a smooth
# quadratic exterior penalty gives the optimizer a gradient that points back into
# the feasible set, so a start's feasibility no longer decides its fate and the
# convergence statistics measure what their names claim.
_T_FLOOR = 1e-6          # smallest 1 + xi*z carried into the log-density
_PENALTY_W = 1.0e4       # weight on squared constraint violation
_XI_ABS_MAX = 0.9
_LOG_SIGMA_HI, _LOG_SIGMA_LO = 5.0, -20.0
_BIG = 1e10             # only for genuinely non-finite input


def gev_reg_constraint_violation(params: np.ndarray, y: np.ndarray, X: np.ndarray,
                                 scale_reg: np.ndarray,
                                 active: np.ndarray | None = None) -> float:
    """Total squared violation of the GEV regression's constraints; 0 iff feasible.

    Exposed separately so callers can ask "did this optimum land inside the
    parameter space?" without re-deriving the penalty arithmetic.
    """
    n_beta = X.shape[1]
    beta, phi0, phi1, xi = _unpack(params, n_beta)
    if active is not None:
        beta = beta * active
    if not np.isfinite(params).all():
        return float("inf")

    viol = 0.0
    viol += max(0.0, abs(xi) - _XI_ABS_MAX) ** 2

    log_sigma = phi0 + phi1 * scale_reg
    viol += float(np.sum(np.maximum(0.0, log_sigma - _LOG_SIGMA_HI) ** 2))
    viol += float(np.sum(np.maximum(0.0, _LOG_SIGMA_LO - log_sigma) ** 2))

    xi_c = float(np.clip(xi, -_XI_ABS_MAX, _XI_ABS_MAX))
    sigma = np.exp(np.clip(log_sigma, _LOG_SIGMA_LO, _LOG_SIGMA_HI))
    t = 1.0 + xi_c * (y - X @ beta) / sigma
    viol += float(np.sum(np.maximum(0.0, _T_FLOOR - t) ** 2))
    return viol


def gev_reg_nll(params: np.ndarray, y: np.ndarray, X: np.ndarray,
                scale_reg: np.ndarray, active: np.ndarray | None = None) -> float:
    """Penalized negative log-likelihood of the GEV regression.

    Equal to the exact NLL wherever the parameters are feasible. Outside the
    feasible set the log-density is evaluated on the clamped support argument
    (a constant in that region, hence gradient-free) and a smooth quadratic
    exterior penalty supplies the restoring gradient, so an optimizer started
    from an infeasible point walks back in rather than stalling on a plateau.

    ``active`` optionally zeroes out columns of X (used by SSVS's median model).
    """
    n_beta = X.shape[1]
    beta, phi0, phi1, xi = _unpack(params, n_beta)
    if active is not None:
        beta = beta * active
    if not np.isfinite(params).all():
        return _BIG

    penalty = gev_reg_constraint_violation(params, y, X, scale_reg, active)
    if not np.isfinite(penalty):
        return _BIG

    xi_c = float(np.clip(xi, -_XI_ABS_MAX, _XI_ABS_MAX))
    log_sigma = np.clip(phi0 + phi1 * scale_reg, _LOG_SIGMA_LO, _LOG_SIGMA_HI)
    sigma = np.exp(log_sigma)
    mu = X @ beta
    ll = gev_logpdf(y, mu, sigma, xi_c, t_floor=_T_FLOOR)
    if not np.isfinite(ll).all():
        return _BIG
    total = -float(ll.sum()) + _PENALTY_W * penalty
    return total if np.isfinite(total) else _BIG


def fit_gev_reg(y: np.ndarray, X: np.ndarray, scale_reg: np.ndarray,
                n_starts: int = 30, seed: int = 42,
                active: np.ndarray | None = None) -> dict:
    """Multistart MLE with an L-BFGS-B sweep and a Nelder-Mead cross-check.

    Two optimizers matter here: L-BFGS-B is fast but the GEV likelihood has a
    boundary (the support depends on the parameters) where its finite-difference
    gradients degrade. Nelder-Mead is restarted from the L-BFGS-B optimum; if it
    finds a materially better point, that is reported as a convergence warning
    rather than silently accepted.
    """
    rng = np.random.default_rng(seed)
    n_beta = X.shape[1]
    n_par = n_beta + 3

    # Sensible starting point: OLS location, residual-scale, xi near zero.
    beta_ols, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid_sd = float(np.std(y - X @ beta_ols))
    p0 = np.zeros(n_par)
    p0[:n_beta] = beta_ols
    p0[n_beta] = np.log(max(resid_sd, 1e-3))
    p0[n_beta + 1] = 0.0
    p0[n_beta + 2] = 0.05

    starts = [p0]
    for _ in range(n_starts - 1):
        s = p0.copy()
        s[:n_beta] += rng.normal(0, 0.5, n_beta) * (np.abs(p0[:n_beta]) + 0.2)
        s[n_beta] += rng.normal(0, 0.4)
        s[n_beta + 1] += rng.normal(0, 0.3)
        s[n_beta + 2] = rng.uniform(-0.35, 0.45)
        starts.append(s)

    bounds = [(None, None)] * n_beta + [(-15.0, 3.0), (-3.0, 3.0), (-0.6, 0.85)]

    # Feasibility of each *starting* point, recorded before optimizing. This is
    # the quantity the pre-remediation code was implicitly reporting as its
    # "convergence rate"; keeping it explicit makes the two impossible to
    # confuse again (Codex finding 1).
    n_feasible_starts = int(sum(
        gev_reg_constraint_violation(s, y, X, scale_reg, active) == 0.0
        for s in starts))

    results, n_success, n_feasible_optima = [], 0, 0
    for s in starts:
        try:
            r = optimize.minimize(gev_reg_nll, s, args=(y, X, scale_reg, active),
                                  method="L-BFGS-B", bounds=bounds,
                                  options={"maxiter": 4000, "ftol": 1e-12})
        except Exception:
            continue
        if not np.isfinite(r.fun) or r.fun >= _BIG:
            continue
        # An optimum only counts if it landed *inside* the parameter space:
        # a point held out by the exterior penalty is not a maximum-likelihood
        # estimate, however finite its penalized objective.
        if gev_reg_constraint_violation(r.x, y, X, scale_reg, active) > 0.0:
            continue
        n_feasible_optima += 1
        results.append(r)
        n_success += int(bool(r.success))

    if not results:
        return {"converged": False, "reason": "no start produced a feasible optimum"}

    results.sort(key=lambda r: r.fun)
    best = results[0]

    nm = optimize.minimize(gev_reg_nll, best.x, args=(y, X, scale_reg, active),
                           method="Nelder-Mead",
                           options={"maxiter": 20000, "xatol": 1e-8, "fatol": 1e-10})
    nm_improvement = float(best.fun - nm.fun)
    if np.isfinite(nm.fun) and nm.fun < best.fun and abs(nm.x[-1]) <= 0.9:
        best_x, best_nll = nm.x, float(nm.fun)
    else:
        best_x, best_nll = best.x, float(best.fun)

    # Numerical Hessian → identification diagnostics.
    hess_ok, cond, min_eig = False, np.nan, np.nan
    try:
        h = _numerical_hessian(lambda p: gev_reg_nll(p, y, X, scale_reg, active), best_x)
        eig = np.linalg.eigvalsh((h + h.T) / 2.0)
        min_eig = float(eig.min())
        cond = float(abs(eig.max() / eig.min())) if eig.min() != 0 else np.inf
        hess_ok = bool(min_eig > 0 and np.isfinite(cond))
    except Exception:
        pass

    nlls = np.array([r.fun for r in results])
    n_at_best = int(np.sum(nlls < nlls.min() + 1e-4))
    beta, phi0, phi1, xi = _unpack(best_x, n_beta)
    return {
        "converged": True,
        "params": best_x,
        "beta": beta * (active if active is not None else 1.0),
        "phi0": float(phi0), "phi1": float(phi1), "xi": float(xi),
        "log_likelihood": float(-best_nll),
        "n_starts": n_starts,
        # --- start-quality vs surface-shape, kept strictly apart -------------
        "n_feasible_starts": n_feasible_starts,
        "feasible_start_rate": float(n_feasible_starts / n_starts),
        "n_feasible_optima": n_feasible_optima,
        "feasible_optimum_rate": float(n_feasible_optima / n_starts),
        "n_lbfgs_success": n_success,
        "lbfgs_success_rate": float(n_success / n_starts),
        # Multimodality lives here and nowhere else: of the starts that reached
        # a feasible optimum, what fraction reached the *best* one. 1.0 means
        # every start agreed; a value well below 1 with a wide nll_spread is
        # what a multi-modal surface actually looks like.
        "n_at_best_basin": n_at_best,
        "basin_concentration": float(n_at_best / max(n_feasible_optima, 1)),
        "best_nll": float(nlls.min()),
        "worst_nll": float(nlls.max()),
        "nll_spread": float(nlls.max() - nlls.min()),
        "nelder_mead_improvement": nm_improvement,
        "hessian_pd": hess_ok,
        "hessian_cond": cond,
        "hessian_min_eig": min_eig,
    }


def _numerical_hessian(f, x: np.ndarray, eps: float = 1e-4) -> np.ndarray:
    n = len(x)
    h = np.zeros((n, n))
    step = eps * np.maximum(np.abs(x), 1.0)
    f0 = f(x)
    for i in range(n):
        for j in range(i, n):
            xi_ = x.copy(); xi_[i] += step[i]; xi_[j] += step[j]
            xj_ = x.copy(); xj_[i] += step[i]; xj_[j] -= step[j]
            xk_ = x.copy(); xk_[i] -= step[i]; xk_[j] += step[j]
            xl_ = x.copy(); xl_[i] -= step[i]; xl_[j] -= step[j]
            val = (f(xi_) - f(xj_) - f(xk_) + f(xl_)) / (4 * step[i] * step[j])
            h[i, j] = h[j, i] = val
    del f0
    return h


def gev_predict(fit: dict, X_row: np.ndarray, scale_reg_row: float) -> tuple[float, float, float]:
    mu = float(X_row @ fit["beta"])
    sigma = float(np.exp(fit["phi0"] + fit["phi1"] * scale_reg_row))
    return mu, sigma, fit["xi"]


# --------------------------------------------------------------------------
# SSVS: Metropolis-within-Gibbs on the GEV likelihood
# --------------------------------------------------------------------------

def _geweke_z(chain: np.ndarray, first: float = 0.1, last: float = 0.5,
              bandwidth: str = "acf") -> np.ndarray:
    """Geweke diagnostic with spectral-density (HAC) variances.

    Using the naive sample variance here is a trap: an MCMC chain is strongly
    autocorrelated, so var/n understates the standard error of the mean by a
    factor of the integrated autocorrelation time, and a perfectly healthy chain
    can post |z| of 15. Geweke's test is *defined* with spectral-density
    variances at frequency zero; that is what is computed here (Bartlett kernel).

    ``bandwidth`` selects how far the kernel reaches:

    ``"fixed"``
        the Newey-West ``4*(m/100)**(2/9)`` rule this file used before the
        2026-07-19 remediation.
    ``"acf"`` (default)
        the same rule, but never shorter than the segment's own measured
        integrated autocorrelation time.

    The fixed rule grows as ``m**(2/9)``, which for a chain whose
    autocorrelation time is ~110 draws never reaches far enough: it truncates
    the autocovariance sum early, understates the standard error, and inflates
    ``|z|``. The symptom is diagnostic: measured on this sampler, tripling the
    number of draws moved R-hat 1.019 -> 1.006 and ESS 83 -> 218 while the
    fixed-rule Geweke sat at 5.7 -> 6.0. A statistic that does not improve as
    the chain improves is measuring its own bandwidth, not the chain. Sizing the
    window to the persistence being corrected for is the repo's standing HAC
    rule (`.claude/rules/experiments.md`), applied here to the same arithmetic.
    Both variants are reported so the change is auditable rather than a silently
    friendlier number.
    """
    n = len(chain)
    a = chain[: max(int(n * first), 10)]
    b = chain[int(n * (1 - last)):]

    def spec_var(x: np.ndarray) -> np.ndarray:
        m = len(x)
        fixed = int(np.ceil(4 * (m / 100.0) ** (2.0 / 9.0)))
        if bandwidth == "acf":
            tau = m / np.maximum(_effective_sample_size(x), 1.0)   # per column
            lag_col = np.ceil(np.maximum(fixed, tau)).astype(int)
        else:
            lag_col = np.full(x.shape[1], fixed, dtype=int)
        lag_col = np.clip(lag_col, 1, max(m // 4, 1))

        xc = x - x.mean(axis=0)
        v = np.mean(xc ** 2, axis=0)
        for l in range(1, int(lag_col.max()) + 1):
            use = lag_col >= l
            if not np.any(use):
                break
            w = 1.0 - l / (lag_col + 1.0)
            v = v + np.where(use, 2.0 * w * np.mean(xc[l:] * xc[:-l], axis=0), 0.0)
        return np.maximum(v, 1e-300) / m

    denom = np.sqrt(spec_var(a) + spec_var(b))
    return (a.mean(axis=0) - b.mean(axis=0)) / np.maximum(denom, 1e-12)


def _effective_sample_size(chain: np.ndarray) -> np.ndarray:
    """ESS per column via the initial-positive-sequence autocorrelation sum."""
    n = len(chain)
    xc = chain - chain.mean(axis=0)
    var = np.mean(xc ** 2, axis=0)
    ess = np.full(chain.shape[1], float(n))
    for j in range(chain.shape[1]):
        if var[j] <= 1e-300:
            continue
        tot = 0.0
        for l in range(1, min(n // 2, 1000)):
            r = np.mean(xc[l:, j] * xc[:-l, j]) / var[j]
            if r < 0.05:
                break
            tot += r
        ess[j] = n / (1.0 + 2.0 * tot)
    return ess


def ssvs_gev(y: np.ndarray, X: np.ndarray, scale_reg: np.ndarray,
             mle: dict, n_macro: int, n_draws: int = 20000, n_burnin: int = 5000,
             thin: int = 10, c_spike: float = 0.01, p_prior: float = 0.5,
             seed: int = 42, n_chains: int = 2) -> dict:
    """Spike-and-slab selection over the MIDAS macro coefficients only.

    The intercept, the three HAR terms, the scale parameters and xi are always
    included — the scientific question is which *macro* blocks earn their place,
    not whether volatility is persistent (it obviously is), and leaving the HAR
    controls subject to selection would let a macro variable win by proxying for
    persistence the model was not allowed to use.

    There is no conjugate update under a GEV likelihood, so this is a
    Metropolis-within-Gibbs sampler in three blocks:

      1. the always-included parameters, jointly, with a proposal covariance
         taken from the MLE Hessian;
      2. each macro coefficient *individually*, with a proposal scaled to its
         own current spike/slab width;
      3. delta, from its exact Bernoulli conditional.

    Block 2 is why it is split out. A single proposal covariance cannot serve
    both regimes: when delta_j = 0 the coefficient lives in a spike of width
    0.01*tau, and a proposal sized for the slab is ~100x too wide and is
    rejected essentially always, so the chain freezes in whichever regime it
    started. Sizing each proposal by its current width lets the sampler move in
    both. An earlier single-block version of this sampler produced Geweke |z|
    of 15.7 for exactly this reason.
    """
    rng = np.random.default_rng(seed)
    n_beta = X.shape[1]
    n_par = n_beta + 3
    macro_idx = np.arange(n_beta - n_macro, n_beta)   # last n_macro columns
    fixed_idx = np.array([i for i in range(n_par) if i not in set(macro_idx)])

    # Slab width from the MLE standard errors, as in k818 (tau = 10 * SE).
    try:
        h = _numerical_hessian(lambda p: gev_reg_nll(p, y, X, scale_reg), mle["params"])
        cov = np.linalg.inv((h + h.T) / 2.0)
        se = np.sqrt(np.maximum(np.diag(cov), 1e-12))
        prop_cov = cov.copy()
        if not np.all(np.linalg.eigvalsh((prop_cov + prop_cov.T) / 2) > 0):
            raise np.linalg.LinAlgError
    except Exception:
        se = np.full(n_par, 0.1)
        prop_cov = np.eye(n_par) * 0.01

    tau = 10.0 * se[macro_idx]
    tau = np.maximum(tau, 1e-4)

    # Proposal for the always-included block only.
    sub = prop_cov[np.ix_(fixed_idx, fixed_idx)]
    try:
        chol_fixed = np.linalg.cholesky((sub + sub.T) / 2 + np.eye(len(fixed_idx)) * 1e-12)
    except np.linalg.LinAlgError:
        chol_fixed = np.eye(len(fixed_idx)) * 0.05

    def log_prior(params, delta):
        beta, phi0, phi1, xi = _unpack(params, n_beta)
        if abs(xi) > 0.9:
            return -np.inf
        lp = -0.5 * (xi / 0.5) ** 2                       # weakly informative on xi
        keep = np.ones(n_beta, dtype=bool)
        keep[macro_idx] = False
        lp += float(np.sum(-0.5 * (beta[keep] / 100.0) ** 2))   # diffuse elsewhere
        lp += -0.5 * (phi0 / 100.0) ** 2 - 0.5 * (phi1 / 10.0) ** 2
        d = np.where(delta > 0.5, tau, c_spike * tau)
        lp += float(np.sum(-0.5 * (beta[macro_idx] / d) ** 2 - np.log(d)))
        return lp

    def log_post(params, delta):
        lp = log_prior(params, delta)
        if not np.isfinite(lp):
            return -np.inf
        # The posterior is exactly zero outside the support. Since the
        # remediated `gev_reg_nll` is a *penalized* objective that stays finite
        # there, feasibility has to be tested directly — a magnitude threshold
        # on the objective would let the chain drift outside the parameter
        # space and quietly sample from the penalty instead of the likelihood.
        if gev_reg_constraint_violation(params, y, X, scale_reg) > 0.0:
            return -np.inf
        nll = gev_reg_nll(params, y, X, scale_reg)
        if nll >= _BIG:
            return -np.inf
        return -nll + lp

    n_total = n_draws + n_burnin
    chains_delta, chains_params, chain_meta = [], [], []

    for chain_id in range(n_chains):
        crng = np.random.default_rng(seed + 1000 * chain_id)
        cur = mle["params"].copy()
        if chain_id > 0:
            # Overdisperse the start so R-hat can actually detect non-mixing.
            cur = cur + crng.normal(0, 1.0, n_par) * np.maximum(se, 1e-3)
            cur[-1] = float(np.clip(cur[-1], -0.5, 0.7))
        delta = (crng.uniform(size=n_macro) < 0.5).astype(float) if chain_id else np.ones(n_macro)

        cur_lp = log_post(cur, delta)
        if not np.isfinite(cur_lp):
            cur = mle["params"].copy()
            delta = np.ones(n_macro)
            cur_lp = log_post(cur, delta)
            if not np.isfinite(cur_lp):
                return {"ok": False, "reason": "MLE start has zero posterior mass"}

        scale_fixed = 0.4
        scale_macro = np.ones(n_macro) * 0.5
        acc_fixed = acc_fixed_win = 0
        acc_macro = np.zeros(n_macro)
        acc_macro_win = np.zeros(n_macro)
        acc_jump = np.zeros(n_macro)
        kept_delta, kept_params = [], []

        for it in range(n_total):
            # --- Block 1: always-included parameters, jointly ---------------
            prop = cur.copy()
            prop[fixed_idx] = cur[fixed_idx] + scale_fixed * (
                chol_fixed @ crng.standard_normal(len(fixed_idx)))
            prop_lp = log_post(prop, delta)
            if np.log(crng.uniform()) < prop_lp - cur_lp:
                cur, cur_lp = prop, prop_lp
                acc_fixed += 1
                acc_fixed_win += 1

            # --- Block 2: macro coefficients, one at a time, each proposal
            #     sized to that coefficient's *current* spike/slab width ------
            width = np.where(delta > 0.5, tau, c_spike * tau)
            for j in range(n_macro):
                prop = cur.copy()
                prop[macro_idx[j]] = cur[macro_idx[j]] + \
                    scale_macro[j] * width[j] * crng.standard_normal()
                prop_lp = log_post(prop, delta)
                if np.log(crng.uniform()) < prop_lp - cur_lp:
                    cur, cur_lp = prop, prop_lp
                    acc_macro[j] += 1
                    acc_macro_win[j] += 1

            # --- Block 2b: joint spike<->slab mode jump ----------------------
            # K1730 remediation (Codex finding 2). Blocks 2 and 3 alone cannot
            # cross between regimes: to move from spike to slab, beta_j has to
            # grow ~100x while the spike prior is still pulling it to zero, and
            # delta_j will not flip until it has. So the chain stays in whichever
            # regime it started, which is exactly the signature the diagnostics
            # showed (R-hat 1.61, ESS 6.25, PIP disagreeing across chains).
            # This move proposes the flip and the coefficient *together*, drawing
            # beta_j from the prior of the regime being proposed, which bridges
            # the two modes in one accept/reject.
            for j in range(n_macro):
                d_new = delta.copy()
                d_new[j] = 1.0 - delta[j]
                w_cur = tau[j] if delta[j] > 0.5 else c_spike * tau[j]
                w_new = tau[j] if d_new[j] > 0.5 else c_spike * tau[j]
                prop = cur.copy()
                prop[macro_idx[j]] = w_new * crng.standard_normal()
                prop_lp = log_post(prop, d_new)
                # Independence proposal within coordinate j; the delta flip is
                # its own inverse, so only the beta_j densities enter the ratio.
                log_q_fwd = (-0.5 * (prop[macro_idx[j]] / w_new) ** 2
                             - np.log(w_new))
                log_q_rev = (-0.5 * (cur[macro_idx[j]] / w_cur) ** 2
                             - np.log(w_cur))
                if np.log(crng.uniform()) < (prop_lp - cur_lp) + (log_q_rev - log_q_fwd):
                    cur, cur_lp, delta = prop, prop_lp, d_new
                    acc_jump[j] += 1

            # Adapt only during burn-in, so the sampled chain has a fixed kernel.
            if it < n_burnin and (it + 1) % 200 == 0:
                scale_fixed *= float(np.exp((acc_fixed_win / 200.0 - 0.25) * 1.5))
                scale_fixed = float(np.clip(scale_fixed, 1e-3, 20.0))
                scale_macro *= np.exp((acc_macro_win / 200.0 - 0.40) * 1.5)
                scale_macro = np.clip(scale_macro, 1e-3, 20.0)
                acc_fixed_win = 0
                acc_macro_win[:] = 0

            # --- Block 3: exact Bernoulli conditional for delta -------------
            beta_macro = cur[macro_idx]
            log_p1 = (np.log(p_prior) - np.log(tau) - 0.5 * (beta_macro / tau) ** 2)
            log_p0 = (np.log1p(-p_prior) - np.log(c_spike * tau)
                      - 0.5 * (beta_macro / (c_spike * tau)) ** 2)
            m = np.maximum(log_p1, log_p0)
            prob1 = np.exp(log_p1 - m) / (np.exp(log_p1 - m) + np.exp(log_p0 - m))
            delta = (crng.uniform(size=n_macro) < prob1).astype(float)
            cur_lp = log_post(cur, delta)   # prior changed → refresh cached value

            if it >= n_burnin and (it - n_burnin) % thin == 0:
                kept_delta.append(delta.copy())
                kept_params.append(cur.copy())

        chains_delta.append(np.array(kept_delta))
        chains_params.append(np.array(kept_params))
        chain_meta.append({
            "acceptance_fixed_block": float(acc_fixed / n_total),
            "acceptance_macro_mean": float(np.mean(acc_macro / n_total)),
            "acceptance_mode_jump_mean": float(np.mean(acc_jump / n_total)),
            "final_scale_fixed": float(scale_fixed),
        })

    all_delta = np.concatenate(chains_delta, axis=0)
    all_params = np.concatenate(chains_params, axis=0)
    pip = all_delta.mean(axis=0)

    # Worst case over *every* chain, not just the first one.
    geweke = max((_geweke_z(c) for c in chains_params),
                 key=lambda g: np.max(np.abs(g)))
    geweke_fixed_bw = max((_geweke_z(c, bandwidth="fixed") for c in chains_params),
                          key=lambda g: np.max(np.abs(g)))
    ess = _effective_sample_size(all_params)
    ess_delta = _effective_sample_size(all_delta)

    # Gelman-Rubin R-hat across the overdispersed chains.
    if n_chains > 1:
        m_ = min(len(c) for c in chains_params)
        arr = np.stack([c[:m_] for c in chains_params])          # (chains, draws, par)
        chain_means = arr.mean(axis=1)
        W = arr.var(axis=1, ddof=1).mean(axis=0)
        B = m_ * chain_means.var(axis=0, ddof=1)
        var_hat = (m_ - 1) / m_ * W + B / m_
        rhat = np.sqrt(np.maximum(var_hat / np.maximum(W, 1e-300), 0.0))
        pip_by_chain = np.stack([c.mean(axis=0) for c in chains_delta])
        pip_max_spread = float(np.max(np.abs(pip_by_chain[0] - pip_by_chain[-1])))
    else:
        rhat = np.full(all_params.shape[1], np.nan)
        pip_max_spread = float("nan")

    rhat_max = float(np.nanmax(rhat))
    ess_min = float(np.min(ess))
    ess_delta_min = float(np.min(ess_delta))
    geweke_max = float(np.max(np.abs(geweke)))
    # A single, mechanically-evaluated gate, fixed before the production run.
    # Whether the PIP and the posterior predictive may be read as inference —
    # rather than as a diagnostic of what this particular sampler did — is
    # decided here and nowhere else, so no downstream prose can quietly promote
    # them. Thresholds are the conventional ones (Vehtari et al. 2021).
    converged = bool(rhat_max < 1.05 and ess_min >= 400 and geweke_max < 2.0)

    return {
        "ok": True,
        "pip": pip,
        "delta_draws": all_delta,
        "param_draws": all_params,
        "n_chains": n_chains,
        "chain_diagnostics": chain_meta,
        "acceptance_rate": float(np.mean([c["acceptance_fixed_block"] for c in chain_meta])),
        "acceptance_macro_mean": float(np.mean([c["acceptance_macro_mean"] for c in chain_meta])),
        "acceptance_mode_jump_mean": float(
            np.mean([c["acceptance_mode_jump_mean"] for c in chain_meta])),
        "n_kept": int(len(all_params)),
        "geweke_max_abs_z": geweke_max,
        "geweke_max_abs_z_fixed_bandwidth": float(np.max(np.abs(geweke_fixed_bw))),
        "geweke_z": geweke,
        "rhat_max": rhat_max,
        "rhat": rhat,
        "ess_min": ess_min,
        "ess_delta_min": ess_delta_min,
        "ess_delta": ess_delta,
        "pip_max_chain_spread": pip_max_spread,
        "converged": converged,
        "convergence_gate": {"rhat_max_lt": 1.05, "ess_min_gte": 400,
                             "geweke_max_abs_z_lt": 2.0},
        "tau": tau,
    }


def ssvs_predictive_quantiles(ssvs: dict, X_row: np.ndarray, scale_reg_row: float,
                              n_beta: int, taus: np.ndarray,
                              n_draws_used: int = 500,
                              grid_size: int = 4000) -> np.ndarray:
    """Posterior predictive quantiles by inverting the mixture CDF.

    The predictive distribution is the *average of GEV CDFs* over posterior
    draws, not a GEV at the average parameters. Averaging quantiles instead of
    CDFs would understate predictive uncertainty — the whole point of carrying
    the posterior through to the interval.
    """
    draws = ssvs["param_draws"]
    if len(draws) > n_draws_used:
        idx = np.linspace(0, len(draws) - 1, n_draws_used).astype(int)
        draws = draws[idx]

    mus, sigmas, xis = [], [], []
    for p in draws:
        beta, phi0, phi1, xi = _unpack(p, n_beta)
        mus.append(float(X_row @ beta))
        sigmas.append(float(np.exp(phi0 + phi1 * scale_reg_row)))
        xis.append(float(xi))
    mus = np.array(mus); sigmas = np.array(sigmas); xis = np.array(xis)

    lo = float(np.min(mus - 6 * sigmas))
    hi = float(np.max(mus + 25 * sigmas))
    grid = np.linspace(lo, hi, grid_size)

    cdf = np.zeros(grid_size)
    for mu, sg, xi in zip(mus, sigmas, xis):
        cdf += gev_cdf(grid, mu, sg, xi)
    cdf /= len(mus)
    cdf = np.maximum.accumulate(cdf)     # guard against float noise

    return np.interp(taus, cdf, grid)


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------

def fit_gaussian_midas(y: np.ndarray, X: np.ndarray, scale_reg: np.ndarray) -> dict:
    """Same location and scale equations, Gaussian errors.

    This is the location-scale analogue of the GEV model: it isolates what the
    estimated tail shape xi contributes, because everything else is identical.
    """
    def nll(params):
        n_beta = X.shape[1]
        beta, phi0, phi1, _ = _unpack(np.append(params, 0.0), n_beta)
        log_sigma = phi0 + phi1 * scale_reg
        if np.any(np.abs(log_sigma) > 20):
            return 1e10
        sigma = np.exp(log_sigma)
        r = (y - X @ beta) / sigma
        val = float(np.sum(0.5 * r ** 2 + log_sigma + 0.5 * np.log(2 * np.pi)))
        return val if np.isfinite(val) else 1e10

    n_beta = X.shape[1]
    beta_ols, *_ = np.linalg.lstsq(X, y, rcond=None)
    p0 = np.append(beta_ols, [np.log(max(np.std(y - X @ beta_ols), 1e-3)), 0.0])
    r = optimize.minimize(nll, p0, method="L-BFGS-B",
                          options={"maxiter": 4000, "ftol": 1e-12})
    beta = r.x[:n_beta]
    return {"converged": bool(r.success), "beta": beta,
            "phi0": float(r.x[n_beta]), "phi1": float(r.x[n_beta + 1]),
            "log_likelihood": float(-r.fun)}


def gaussian_midas_quantiles(fit: dict, X_row: np.ndarray, scale_reg_row: float,
                             taus: np.ndarray) -> np.ndarray:
    mu = float(X_row @ fit["beta"])
    sigma = float(np.exp(fit["phi0"] + fit["phi1"] * scale_reg_row))
    return mu + sigma * stats.norm.ppf(taus)


def fit_har_quantile(y: np.ndarray, X_har: np.ndarray, taus: np.ndarray) -> dict:
    """Quantile regression of the block max on HAR terms only (one fit per tau).

    Uses statsmodels' QuantReg — the standard Koenker-Bassett estimator — so the
    baseline is a real quantile regression rather than a Gaussian model wearing
    quantile clothing.
    """
    import statsmodels.api as sm
    coefs = {}
    for tau in taus:
        try:
            res = sm.QuantReg(y, X_har).fit(q=float(tau), max_iter=5000)
            coefs[float(tau)] = np.asarray(res.params, dtype=float)
        except Exception:
            # Fall back to the empirical quantile of the residual-free target.
            c = np.zeros(X_har.shape[1]); c[0] = float(np.quantile(y, tau))
            coefs[float(tau)] = c
    return {"coefs": coefs}


def har_quantile_predict(fit: dict, X_har_row: np.ndarray, taus: np.ndarray) -> np.ndarray:
    out = np.array([float(X_har_row @ fit["coefs"][float(t)]) for t in taus])
    return np.maximum.accumulate(out)     # enforce monotonic quantiles


def empirical_quantiles(y_hist: np.ndarray, taus: np.ndarray) -> np.ndarray:
    """Expanding-window historical quantiles — the naive benchmark."""
    return np.quantile(y_hist, taus)
