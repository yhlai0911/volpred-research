#!/usr/bin/env python3
"""
K1685: GARCH-X (A4f) vs GJR — extended-OOS re-check under the K988/K1393-faithful spec
======================================================================================
Paper 9 (garch-x-vix), review item P0-2.

THE OPEN QUESTION
-----------------
Paper 9's headline is "A4f (GARCH-X with VIX) beats GJR on QLIKE, DM t = 4.148,
Harvey-significant". The OOS stops at 2026-04-07. K1391 extended the OOS by 41
trading days and got DM t = -2.03 (GJR wins) — a sign flip. K1393 later showed
K1391/K1392 deviated from K988's A4f spec in three ways (theta0/theta1 bounds,
g initialisation) and, with the faithful spec, recovered t = +3.60 at the
2026-04-07 endpoint. But nobody ever re-ran the EXTENDED endpoint with the
correct spec. This script does that, on a freshly pinned snapshot.

WHY THE PINNED SNAPSHOT MATTERS (data-integrity finding)
--------------------------------------------------------
The paper's data file, paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv,
contains TEN DUPLICATED DATES (2026-05-04 .. 2026-05-15, each row present twice).
Read with the standard `read_csv -> sort_index -> pct/log-diff` idiom, each
duplicate emits a spurious ZERO-return day. Those ten days sit exactly inside the
41-day window K1391 blamed for the reversal, and `git show` confirms they were
already present in the CSV version K1391 read (commit f1bdea2d, 2026-05-20).
So K1391's -2.03 is confounded by BOTH a degraded A4f spec AND corrupted data.
K1685 therefore fetches and pins its own de-duplicated SPY/VIX snapshot
(experiments/k1685/data/, see fetch_snapshot.py) and hard-asserts no duplicates.

DESIGN (single spec, three data/endpoint configurations)
--------------------------------------------------------
Spec: K988/K1393-faithful A4f
  tau_t = max(theta0 + theta1 * VIX_{t-1}^2, eps),  g ~ GJR(1,1) with free omega,
  denom_mode='tau_t' (Engle-Ghysels-Sohn 2013), Gaussian QML, L-BFGS-B, 3 starts,
  bounds theta0 in [-1e-2, 1e-2], theta1 in [1e-8, 1e-3], g[0] = omega/(1-persist).
  Benchmark: GJR-GARCH(1,1), same rolling protocol and same lag convention.
Rolling: W=2000, refit every 63 OOS steps, state-based recursion, OOS from 2019-01-01.

  RUN A (pipeline gate)  : paper CSV, OOS end 2026-04-07  -> must reproduce K1393 (t ~ +3.60)
  RUN B (main)           : pinned snapshot, OOS end = last available day
  RUN C (prefix check)   : pinned snapshot, OOS end 2026-04-07 -> must equal RUN B's prefix

The refit schedule is keyed on the OOS step index and every recursion is causal,
so truncating RUN B at any date is exactly a shorter run. RUN C verifies that
empirically (rather than assuming it), which is what licenses the endpoint scan.

MULTISTART ROBUSTNESS (RUN D / RUN E) — why it is here
------------------------------------------------------
RUN A and RUN C forecast the SAME 1825 days from data whose log returns differ by
at most 1.98e-6 (identical date sets; the gap is pure adjusted-close rounding after
a new dividend re-scaled the back-adjustment factor). Yet the DM t moves 3.61 -> 3.92.
A contraction recursion cannot amplify 1e-6 into 0.3 of a t-statistic, so the jump
must come from the optimiser: K988's A4f/GJR fits use only THREE starts, and across
30 quarterly refits the L-BFGS-B runs land in different local optima under a
negligible data perturbation. That is the multistart-artifact class .claude/rules/
experiments.md warns about (K1213), and it means the published t carries an
estimation-noise band of order +-0.3 that Paper 9 never disclosed.

RUN D/E re-estimate with 12 starts (the 3 canonical ones + 9 seeded random draws
inside the bounds) for BOTH models symmetrically — refining only A4f would
manufacture exactly the asymmetric artifact K1216b was burned by. RUN D is the
extended endpoint (robustness column for the headline); RUN E is the anchor on the
paper CSV (does the 3.61/3.92 gap close once both models are properly optimised?).
This is a SUPPLEMENT, not a replacement: the headline stays on the faithful 3-start
K988 spec so it remains comparable with K988/K1393/the paper.

LOSSES AND TESTS
----------------
Primary loss  : canonical QLIKE, volpred.stats.model_evaluation.qlike_pointwise
                (actual/predicted - log(actual/predicted) - 1), actual = r_t^2.
Legacy loss   : K988/K1393 kernel log(sigma2) + r^2/sigma2, kept only so the gate
                can be compared with K1393's published numbers. The two differ by
                a model-independent term, so loss DIFFERENTIALS coincide (asserted).
Primary test  : canonical volpred.stats.model_evaluation.dm_test (Newey-West HAC,
                bandwidth ceil(h^(1/3) * n^(1/3)); NOT the degenerate lag = h-1).
                d = loss_GJR - loss_A4f, so positive t means A4f is better.
                acf(1) of d is reported before reading any t, and t is reported
                across a ladder of HAC bandwidths (lag sensitivity).
Threshold     : |t| > 3.0 (Harvey, Liu & Zhu 2016 multiple-testing threshold — the
                convention Paper 9 uses; not the Harvey-Leybourne-Newbold small-sample
                correction, which for h=1 is a factor sqrt((n-1)/n) ~ 1 and is reported
                separately as hln_t for completeness).

LOOKAHEAD AUDIT (see README for the full statement)
---------------------------------------------------
Forecast for day i uses: training data ret[i-W:i] / vix[i-W:i] (excludes day i),
r_{i-1} = ret[i-1], VIX_{i-1} = vix[i-1]. The realized r_i enters only the loss.
No model input is dated i or later. This is enforced mechanically, not asserted in prose:
every read of the return/VIX series goes through `CausalView`, which raises LookaheadError
if any index >= the current forecast origin is touched, on every OOS step. The realized
r_i is not reachable through that view at all — it is read from the raw array only in the
loss step, after the forecast has been produced.

Author: VolPred Research System | Date: 2026-07-12 | Seed: 42
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import optimize
from scipy.stats import t as t_dist

warnings.filterwarnings("ignore")
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1685"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402

RESULTS_PATH = os.path.join(SCRIPT_DIR, "k1685_garchx_oos_extension_results.json")
FIG_DIR = os.path.join(SCRIPT_DIR, "figures")
SNAPSHOT_PATH = os.path.join(SCRIPT_DIR, "data", "k1685_spy_vix_snapshot.csv")
PROVENANCE_PATH = os.path.join(SCRIPT_DIR, "data", "k1685_snapshot_provenance.json")
PAPER_CSV = os.path.join(PROJECT_ROOT, "paper", "garch-x-vix", "data",
                         "spy_vix_qqq_eem_fez_2000-2026.csv")

# --- protocol constants (K988 / K1393, unchanged) ---
OOS_START = "2019-01-01"
K1393_OOS_END = "2026-04-07"   # paper's stated OOS end == K1393 anchor
K1391_OOS_END = "2026-05-20"   # endpoint at which K1391 reported t = -2.03
WINDOW = 2000
REFIT_EVERY = 63
COVID_START = "2020-02-01"
COVID_END = "2020-06-30"
HARVEY_THRESHOLD = 3.0
SEED = 42
EXTRA_STARTS = 9   # RUN D/E/F: 3 canonical starts + 9 seeded random ones, both models

# K1393 published reference values (the gate)
K1393_REF = {"dm_t_legacy": 3.6029009651588626, "qlike_gjr": -8.267001519557294,
             "qlike_a4f": -8.359703082789737, "n": 1825}
GATE_T_TOL = 0.10          # |t_gate - 3.6029| must be under this
GATE_QLIKE_TOL = 0.01


# ============================================================
# MODELS — verbatim K988/K1393 spec (bounds, starts, g init, optimizer)
# ============================================================

def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = float(np.var(returns[: min(250, n)]))
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0.0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2.0 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t])
    return -ll


def _random_starts(bounds, n, rng):
    """Uniform draws inside `bounds` — deterministic given the seeded rng."""
    return [[float(rng.uniform(lo, hi)) for lo, hi in bounds] for _ in range(n)]


def fit_gjr(returns, extra_starts=0, rng=None):
    """K988-faithful GJR. extra_starts>0 adds seeded random inits (RUN D/E only);
    the first three starts are always K988's, so extra_starts=0 is bit-identical."""
    var0 = float(np.var(returns))
    bounds = [(1e-10, var0 * 0.5), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    n_canonical = len(starts)
    if extra_starts > 0:
        starts = starts + _random_starts(bounds, extra_starts, rng)

    best_ll, best_params = np.inf, None
    ll_canonical = np.inf
    n_converged = 0
    for i, s in enumerate(starts):
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,), method="L-BFGS-B",
                                    bounds=bounds, options={"maxiter": 500})
        except Exception as exc:  # pragma: no cover
            print(f"  [warn] GJR start {s} raised: {exc}", file=sys.stderr)
            continue
        if not (res.success and np.isfinite(res.fun) and np.all(np.isfinite(res.x))):
            print(f"  [warn] GJR start {i} did not converge: {res.message}", file=sys.stderr)
            continue
        n_converged += 1
        if i < n_canonical and res.fun < ll_canonical:
            ll_canonical = res.fun
        if res.fun < best_ll:
            best_ll, best_params = res.fun, res.x
    # No fallback: a failed fit must surface at the caller's gate, not be papered over.
    if best_params is None:
        print("  [warn] GJR: no start converged", file=sys.stderr)
        return None, {}
    return best_params, {"ll_canonical3": float(ll_canonical), "ll_best": float(best_ll),
                         "n_converged": n_converged, "n_starts": len(starts)}


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev ** 2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev ** 2 + asym + beta * h_prev, 1e-10)


def fit_a4f_k988(returns, vix_vals, extra_starts=0, rng=None):
    """K988-faithful A4f: vix_squared tau, denom_mode='tau_t', free_omega=True.
    extra_starts>0 adds seeded random inits (RUN D/E only); the first three starts are
    always K988's, so extra_starts=0 is bit-identical to K1393."""
    n = len(returns)
    var0 = float(np.var(returns))

    log_vix_vals = np.log(np.maximum(vix_vals, 1.0))
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]
    vix_lag = np.exp(log_vix_lag)
    vix2_mean = float(np.mean(vix_lag ** 2)) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t - 1] / np.sqrt(max(tau[t], 1e-16))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev ** 2 + asym + beta * g[t - 1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2.0 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2)
        return -ll

    bounds = [
        (-1e-2, 1e-2),   # theta0
        (1e-8, 1e-3),    # theta1
        (1e-6, 1.0),     # omega_g
        (1e-4, 0.3),     # alpha
        (1e-4, 0.3),     # gamma
        (0.5, 0.999),    # beta
    ]
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    n_canonical = len(starts)
    if extra_starts > 0:
        # Keep every draw in the stationary region so the extra starts are usable,
        # not wasted on the 1e10 penalty branch.
        for s in _random_starts(bounds, extra_starts, rng):
            persist = s[3] + s[4] / 2.0 + s[5]
            if persist >= 0.999:
                s[5] = max(0.5, 0.95 - s[3] - s[4] / 2.0)
            starts.append(s)

    best_ll, best_params = np.inf, None
    ll_canonical = np.inf
    n_converged = 0
    for i, s in enumerate(starts):
        s_clipped = [float(np.clip(s[j], bounds[j][0], bounds[j][1])) for j in range(6)]
        try:
            res = optimize.minimize(neg_loglik, s_clipped, method="L-BFGS-B",
                                    bounds=bounds, options={"maxiter": 500})
        except Exception as exc:  # pragma: no cover
            print(f"  [warn] A4f start {s_clipped} raised: {exc}", file=sys.stderr)
            continue
        if not (res.success and np.isfinite(res.fun) and np.all(np.isfinite(res.x))):
            print(f"  [warn] A4f start {i} did not converge: {res.message}", file=sys.stderr)
            continue
        n_converged += 1
        if i < n_canonical and res.fun < ll_canonical:
            ll_canonical = res.fun
        if res.fun < best_ll:
            best_ll, best_params = res.fun, res.x
    if best_params is None:
        print("  [warn] A4f: no start converged", file=sys.stderr)
        return None, {}
    return best_params, {"ll_canonical3": float(ll_canonical), "ll_best": float(best_ll),
                         "n_converged": n_converged, "n_starts": len(starts)}


def a4f_get_g_state(params, returns, vix_vals):
    """Final g state and last tau from the training window (state-based rolling)."""
    n = len(returns)
    theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = params

    log_vix_vals = np.log(np.maximum(vix_vals, 1.0))
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]
    vix_lag = np.exp(log_vix_lag)
    tau_train = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)

    persist = alpha_p + gamma_p / 2.0 + beta_p
    g = omega_g / max(1.0 - persist, 1e-10)
    for i in range(1, n):
        u_prev = returns[i - 1] / np.sqrt(max(tau_train[i], 1e-16))
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g = max(omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g, 1e-10)
    return g, tau_train[-1]


# ============================================================
# ROLLING OOS ENGINE
# ============================================================

class LookaheadError(AssertionError):
    pass


class CausalView:
    """Guarded read-only view of the series, enforcing the information set mechanically.

    Every read of `ret` / `vix` goes through here, and every read is checked against the
    current forecast origin: index i is readable only while origin > i. The realized
    return of the origin day is deliberately NOT reachable through this object — it is
    taken straight from the raw array in the loss step, after the forecast exists.

    (The previous version of this check took hand-constructed indices as arguments and
    could therefore only ever pass. Codex review 2026-07-12, finding P0-1.)
    """

    def __init__(self, ret, vix):
        self._ret = ret
        self._vix = vix
        self._origin = None
        self.reads = 0

    def set_origin(self, abs_idx):
        self._origin = abs_idx

    def _check(self, i, what):
        if self._origin is None:
            raise LookaheadError("forecast origin not set")
        if not (i < self._origin):
            raise LookaheadError(
                f"LOOKAHEAD: read {what}[{i}] while forecasting day {self._origin}")
        self.reads += 1

    def ret_at(self, i):
        self._check(i, "ret")
        return self._ret[i]

    def vix_at(self, i):
        self._check(i, "vix")
        return self._vix[i]

    def train_slice(self, start, end):
        """Training window [start, end). `end` must not exceed the forecast origin."""
        if not (end <= self._origin):
            raise LookaheadError(
                f"LOOKAHEAD: training window ends at {end} while forecasting day {self._origin}")
        self.reads += 1
        return self._ret[start:end], self._vix[start:end]


def self_test_causal_view():
    """A guard that cannot fail is not a guard. Prove this one bites before trusting it."""
    v = CausalView(np.arange(10.0), np.arange(10.0))
    v.set_origin(5)
    assert v.ret_at(4) == 4.0 and v.vix_at(0) == 0.0        # strictly past: allowed
    for bad in (5, 6):                                       # origin and future: must raise
        for fn in (v.ret_at, v.vix_at):
            try:
                fn(bad)
            except LookaheadError:
                continue
            raise AssertionError(f"CausalView failed to block a read of index {bad}")
    try:
        v.train_slice(0, 6)                                  # window overshooting the origin
    except LookaheadError:
        pass
    else:
        raise AssertionError("CausalView failed to block an overshooting training window")
    print("  causal-view guard self-test: PASS (blocks origin-day and future reads)")


def run_rolling(df, oos_start, oos_end, label, extra_starts=0, frozen_params=None):
    """Rolling one-step-ahead OOS forecasts. Returns (per-day DataFrame, refit diagnostics).

    extra_starts=0 reproduces K988/K1393 exactly. extra_starts>0 adds seeded random
    inits to BOTH models symmetrically (RUN D/E/F multistart robustness).

    frozen_params: {t_idx: {"gjr": array, "a4f": array}} — skip estimation and reuse the
    parameters another run fitted. Used by RUN G to hold the fits constant while swapping
    the data, which is what separates a data effect from an estimation effect.

    Estimation is fail-closed: any refit that does not produce finite, converged
    parameters for BOTH models aborts the run. There is no fallback and no silent reuse
    of a previous quarter's fit (Codex review 2026-07-12, finding P0-2).
    """
    ret = df["log_ret"].values
    vix = df["VIX"].values
    view = CausalView(ret, vix)

    oos_mask = (df.index >= pd.Timestamp(oos_start)) & (df.index <= pd.Timestamp(oos_end))
    oos_indices = np.where(oos_mask)[0]
    n_steps = len(oos_indices)
    mode = "frozen params" if frozen_params is not None else f"extra_starts={extra_starts}"
    print(f"\n[{label}] rolling OOS: {oos_start} .. {oos_end}  n={n_steps}  "
          f"(W={WINDOW}, refit every {REFIT_EVERY}, {mode})")

    sigma2_gjr = np.full(n_steps, np.nan)
    sigma2_a4f = np.full(n_steps, np.nan)
    gjr_state = {"params": None, "h": None}
    a4f_state = {"params": None, "g": None}
    refit_diag = []
    fitted_params = {}

    for t_idx, abs_idx in enumerate(oos_indices):
        if t_idx % 300 == 0:
            print(f"  step {t_idx}/{n_steps} ({time.time() - START_TIME:.0f}s)")
        if abs_idx < WINDOW:
            continue

        # Every read below is checked against this origin.
        view.set_origin(abs_idx)

        need_refit = (t_idx % REFIT_EVERY == 0) or (gjr_state["params"] is None) \
            or (a4f_state["params"] is None)
        if need_refit:
            train_start = max(0, abs_idx - WINDOW)
            train_ret, train_vix = view.train_slice(train_start, abs_idx)  # excludes abs_idx

            if frozen_params is not None:
                if t_idx not in frozen_params:
                    raise RuntimeError(f"{label}: no frozen params for refit step {t_idx}")
                gjr_p = frozen_params[t_idx]["gjr"]
                a4f_p = frozen_params[t_idx]["a4f"]
                gjr_d = a4f_d = {}
            else:
                # Seeded per refit: reproducible and independent of call order.
                rng = np.random.default_rng(SEED + t_idx) if extra_starts > 0 else None
                gjr_p, gjr_d = fit_gjr(train_ret, extra_starts=extra_starts, rng=rng)
                a4f_p, a4f_d = fit_a4f_k988(train_ret, train_vix,
                                            extra_starts=extra_starts, rng=rng)

            # Fail-closed estimation gate — no fallback, no stale reuse.
            for name, p in (("GJR", gjr_p), ("A4f", a4f_p)):
                if p is None or not np.all(np.isfinite(p)):
                    raise RuntimeError(
                        f"{label}: {name} refit failed at step {t_idx} "
                        f"({df.index[abs_idx].date()}) — aborting rather than falling back")

            gjr_state["params"] = gjr_p
            h = float(np.var(train_ret))
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_p, h, train_ret[i - 1])
            gjr_state["h"] = h

            a4f_state["params"] = a4f_p
            a4f_state["g"], _ = a4f_get_g_state(a4f_p, train_ret, train_vix)

            fitted_params[t_idx] = {"gjr": np.asarray(gjr_p, dtype=float),
                                    "a4f": np.asarray(a4f_p, dtype=float)}
            refit_diag.append({"t_idx": int(t_idx), "date": str(df.index[abs_idx].date()),
                               "gjr": gjr_d, "a4f": a4f_d})

        # --- GJR one-step forecast: uses r_{t-1}, h_{t-1} ---
        r_prev = view.ret_at(abs_idx - 1)
        h_new = gjr_forecast_1step(gjr_state["params"], gjr_state["h"], r_prev)
        sigma2_gjr[t_idx] = h_new
        gjr_state["h"] = h_new

        # --- A4f one-step forecast: uses VIX_{t-1}, r_{t-1}, g_{t-1} ---
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_state["params"]
        tau_t = max(theta0 + theta1 * view.vix_at(abs_idx - 1) ** 2, 1e-16)
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev ** 2 + asym + beta_p * a4f_state["g"], 1e-10)
        sigma2_a4f[t_idx] = tau_t * g_new
        a4f_state["g"] = g_new

    out = pd.DataFrame(
        {"r": ret[oos_indices], "vix_lag": vix[oos_indices - 1],
         "sigma2_gjr": sigma2_gjr, "sigma2_a4f": sigma2_a4f},
        index=df.index[oos_indices],
    ).dropna()
    print(f"  valid forecasts: {len(out)}  | guarded reads: {view.reads}  | "
          f"refits: {len(fitted_params)}  (all converged)")
    return out, {"refit_diag": refit_diag, "fitted_params": fitted_params}


def summarize_refits(diag, label):
    """How often did the 9 extra starts beat K988's 3 starts, and by how much?
    (neg-loglik: lower is better, so a positive gap means the 3-start fit was stuck.)"""
    out = {"label": label, "n_refits": len(diag)}
    for model in ("gjr", "a4f"):
        gaps = [d[model]["ll_canonical3"] - d[model]["ll_best"]
                for d in diag if d[model].get("ll_best") is not None]
        gaps = [g for g in gaps if np.isfinite(g)]
        if not gaps:
            continue
        out[model] = {
            "n_refits_where_extra_starts_won": int(sum(1 for g in gaps if g > 1e-6)),
            "mean_loglik_gain": float(np.mean(gaps)),
            "max_loglik_gain": float(np.max(gaps)),
        }
        print(f"  {label} [{model}]: extra starts found a better optimum in "
              f"{out[model]['n_refits_where_extra_starts_won']}/{len(gaps)} refits "
              f"(mean gain {out[model]['mean_loglik_gain']:.3f}, "
              f"max {out[model]['max_loglik_gain']:.3f} log-lik)")
    return out


# ============================================================
# LOSSES AND TESTS
# ============================================================

def losses(panel):
    """Canonical QLIKE (primary) and the K988/K1393 kernel (legacy, for the gate)."""
    r2 = panel["r"].values ** 2
    can_gjr = qlike_pointwise(r2, panel["sigma2_gjr"].values)
    can_a4f = qlike_pointwise(r2, panel["sigma2_a4f"].values)
    leg_gjr = np.log(panel["sigma2_gjr"].values) + r2 / panel["sigma2_gjr"].values
    leg_a4f = np.log(panel["sigma2_a4f"].values) + r2 / panel["sigma2_a4f"].values
    return can_gjr, can_a4f, leg_gjr, leg_a4f


def acf1(d):
    d = np.asarray(d, dtype=np.float64)
    dm = d - d.mean()
    denom = float(np.sum(dm ** 2))
    if denom <= 0 or len(d) < 3:
        return float("nan")
    return float(np.sum(dm[1:] * dm[:-1]) / denom)


def nw_t(d, lag):
    """Newey-West t on mean(d) at a fixed bandwidth (lag=0 -> no HAC)."""
    n = len(d)
    d_mean = float(np.mean(d))
    gamma0 = float(np.mean((d - d_mean) ** 2))
    var_d = gamma0
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        var_d += 2 * w * float(np.mean((d[k:] - d_mean) * (d[:-k] - d_mean)))
    if var_d <= 0:
        return float("nan")
    return d_mean / np.sqrt(var_d / n)


def legacy_dm_k1393(loss_gjr, loss_a4f):
    """K1393's own local DM (q = int(n^(1/3))) — reproduced ONLY to compare with
    K1393's published t. Not used for any K1685 conclusion."""
    d = loss_gjr - loss_a4f
    n = len(d)
    q = max(1, int(n ** (1 / 3)))
    t_stat = nw_t(d, q)
    return {"t_stat": float(t_stat), "hac_lag": int(q), "n": int(n),
            "p_value": float(2.0 * t_dist.sf(abs(t_stat), df=n - 1))}


def dm_report(panel, label):
    """Canonical DM (primary), plus acf(1), HAC-lag sensitivity, HLN correction."""
    can_gjr, can_a4f, leg_gjr, leg_a4f = losses(panel)
    d = can_gjr - can_a4f
    n = len(d)

    # The two kernels differ only by the model-independent term (-log r^2 - 1), so the
    # loss DIFFERENTIALS must coincide exactly. The one exception is a day with r == 0:
    # qlike_pointwise clamps actual to 1e-16 while the legacy kernel keeps the true zero.
    # That clamp is applied identically to both models, so even then the differential is
    # unchanged — but we check rather than assert it in prose (Codex finding P1-3).
    d_leg = leg_gjr - leg_a4f
    kernel_gap = float(np.max(np.abs(d - d_leg)))
    n_zero_ret = int(np.sum(panel["r"].values == 0.0))
    scale = float(np.mean(np.abs(d))) or 1.0
    if kernel_gap > 1e-8 * max(scale, 1.0):
        raise RuntimeError(
            f"{label}: canonical and legacy QLIKE differentials disagree "
            f"(max gap {kernel_gap:.3e}, {n_zero_ret} zero-return days) — the DM test would "
            "depend on which kernel was used, which must never happen")

    t_stat, p_val = dm_test(can_gjr, can_a4f, h=1)          # canonical, HAC ceil(n^(1/3))
    hac_lag = max(1, min(int(np.ceil(1 ** (1 / 3) * n ** (1 / 3))), n // 4))
    hln_factor = float(np.sqrt((n + 1 - 2 * 1 + 1 * (1 - 1) / n) / n))  # h=1 -> ~1

    rep = {
        "label": label,
        "n": int(n),
        "start": str(panel.index[0].date()),
        "end": str(panel.index[-1].date()),
        "qlike_mean_gjr_canonical": float(np.mean(can_gjr)),
        "qlike_mean_a4f_canonical": float(np.mean(can_a4f)),
        "qlike_mean_gjr_legacy_kernel": float(np.mean(leg_gjr)),
        "qlike_mean_a4f_legacy_kernel": float(np.mean(leg_a4f)),
        "loss_diff_mean": float(np.mean(d)),
        "loss_diff_acf1": acf1(d),
        "dm_t_canonical": float(t_stat),
        "dm_p_canonical": float(p_val),
        "dm_hac_lag": int(hac_lag),
        "dm_t_hln_corrected": float(t_stat * hln_factor),
        "harvey_significant": bool(abs(t_stat) > HARVEY_THRESHOLD),
        "winner": "A4f" if t_stat > 0 else "GJR",
        "hac_lag_sensitivity": {f"lag_{lg}": float(nw_t(d, lg))
                                for lg in (0, 5, 10, hac_lag, 20, 30)},
        "legacy_dm_k1393_convention": legacy_dm_k1393(leg_gjr, leg_a4f),
        "kernel_differential_max_gap": kernel_gap,
        "n_zero_return_days": n_zero_ret,
    }
    sig = "HARVEY-SIG" if rep["harvey_significant"] else "not sig"
    print(f"  {label:<34} n={n:<5} acf1={rep['loss_diff_acf1']:+.3f}  "
          f"DM t={t_stat:+.3f} (lag={hac_lag}) p={p_val:.4f} [{sig}] -> {rep['winner']}")
    return rep


# ============================================================
# DATA LOADERS
# ============================================================

def load_snapshot():
    df = pd.read_csv(SNAPSHOT_PATH, parse_dates=["date"], index_col="date").sort_index()
    assert not df.index.has_duplicates, "pinned snapshot has duplicate dates"
    assert df.index.is_monotonic_increasing
    out = pd.DataFrame({
        "log_ret": np.log(df["spy_adj_close"] / df["spy_adj_close"].shift(1)),
        "VIX": df["vix_close"],
    }).dropna()
    return out


def load_paper_csv():
    """Read exactly as K1393 did (no de-duplication) so the gate is a true replication.
    The duplicate block (2026-05-04..05-15) lies strictly after K1393's OOS end, so it
    cannot touch the gate; it is what disqualifies this file for the EXTENDED run."""
    df = pd.read_csv(PAPER_CSV, parse_dates=["date"], index_col="date").sort_index()
    spy = df["spy_adj_close"].dropna()
    vix = df["vix_close"].dropna()
    common = spy.index.intersection(vix.index)
    spy, vix = spy.loc[common], vix.loc[common]
    out = pd.DataFrame({"log_ret": np.log(spy / spy.shift(1)), "VIX": vix}).dropna()
    return out


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 78)
    print(f"{EXPERIMENT_ID}: extended-OOS re-check, A4f vs GJR (K988/K1393-faithful spec)")
    print("=" * 78)

    self_test_causal_view()

    with open(PROVENANCE_PATH) as fh:
        provenance = json.load(fh)
    print(f"\nSnapshot : {provenance['snapshot_file']}")
    print(f"  sha256 : {provenance['snapshot_sha256']}")
    print(f"  window : {provenance['first_date']} .. {provenance['last_date']}  "
          f"(n={provenance['n_rows']}, fetched {provenance['fetched_at_utc']})")

    df_snap = load_snapshot()
    df_paper = load_paper_csv()
    last_date = str(df_snap.index[-1].date())
    print(f"  snapshot usable rows: {len(df_snap)}  ({df_snap.index[0].date()} .. {last_date})")

    # ---------- RUN A: pipeline gate against K1393 ----------
    print("\n" + "-" * 78)
    print("[GATE] RUN A — paper CSV, OOS end 2026-04-07: must reproduce K1393")
    panel_a, out_a = run_rolling(df_paper, OOS_START, K1393_OOS_END, "RUN A / gate")
    _, _, leg_gjr_a, leg_a4f_a = losses(panel_a)
    gate_legacy = legacy_dm_k1393(leg_gjr_a, leg_a4f_a)
    gate_rep = dm_report(panel_a, "RUN A gate (paper CSV, 04-07)")

    dt = abs(gate_legacy["t_stat"] - K1393_REF["dm_t_legacy"])
    dq_gjr = abs(gate_rep["qlike_mean_gjr_legacy_kernel"] - K1393_REF["qlike_gjr"])
    dq_a4f = abs(gate_rep["qlike_mean_a4f_legacy_kernel"] - K1393_REF["qlike_a4f"])
    gate_pass = (dt < GATE_T_TOL) and (dq_gjr < GATE_QLIKE_TOL) and (dq_a4f < GATE_QLIKE_TOL) \
        and (gate_rep["n"] == K1393_REF["n"])
    print(f"\n  K1393 published : t={K1393_REF['dm_t_legacy']:+.4f}  "
          f"QLIKE GJR={K1393_REF['qlike_gjr']:.4f} A4f={K1393_REF['qlike_a4f']:.4f} n={K1393_REF['n']}")
    print(f"  K1685 gate run  : t={gate_legacy['t_stat']:+.4f}  "
          f"QLIKE GJR={gate_rep['qlike_mean_gjr_legacy_kernel']:.4f} "
          f"A4f={gate_rep['qlike_mean_a4f_legacy_kernel']:.4f} n={gate_rep['n']}")
    print(f"  GATE: {'PASS' if gate_pass else 'FAIL'}  "
          f"(|dt|={dt:.4f}, |dQLIKE_gjr|={dq_gjr:.4f}, |dQLIKE_a4f|={dq_a4f:.4f})")
    if not gate_pass:
        print("\n  GATE FAILED — the pipeline does not reproduce K1393. "
              "Downstream numbers are NOT trustworthy; stopping.", file=sys.stderr)
        sys.exit(1)

    # ---------- RUN B: main extended run on the pinned snapshot ----------
    print("\n" + "-" * 78)
    print(f"[MAIN] RUN B — pinned snapshot, OOS end {last_date} (extended)")
    panel_b, _ = run_rolling(df_snap, OOS_START, last_date, "RUN B / main")

    # ---------- RUN C: prefix property check ----------
    print("\n" + "-" * 78)
    print("[CHECK] RUN C — pinned snapshot truncated at 2026-04-07 (prefix property)")
    panel_c, out_c = run_rolling(df_snap, OOS_START, K1393_OOS_END, "RUN C / prefix")
    params_c = out_c["fitted_params"]
    pre_b = panel_b.loc[: pd.Timestamp(K1393_OOS_END)]
    prefix_gap = float(np.max(np.abs(
        pre_b[["sigma2_gjr", "sigma2_a4f"]].values - panel_c[["sigma2_gjr", "sigma2_a4f"]].values
    ))) if len(pre_b) == len(panel_c) else float("inf")
    prefix_ok = prefix_gap < 1e-12
    print(f"  prefix identical: {prefix_ok} (max |dsigma2| = {prefix_gap:.2e}, "
          f"n_prefix={len(pre_b)} vs n_runC={len(panel_c)})")
    if not prefix_ok:
        print("  Prefix property violated — the endpoint scan would be invalid; stopping.",
              file=sys.stderr)
        sys.exit(1)

    # ---------- Headline comparisons ----------
    print("\n" + "-" * 78)
    print("[RESULTS] canonical DM (d = QLIKE_GJR - QLIKE_A4f; t>0 => A4f better)")
    reports = {}
    reports["anchor_2026_04_07_paper_csv"] = gate_rep
    reports["anchor_2026_04_07_new_snapshot"] = dm_report(panel_c, "anchor 04-07 (new snapshot)")
    panel_k1391 = panel_b.loc[: pd.Timestamp(K1391_OOS_END)]
    reports["k1391_endpoint_2026_05_20"] = dm_report(panel_k1391, "K1391 endpoint 05-20 (faithful)")
    reports["full_extended_oos"] = dm_report(panel_b, f"FULL extended OOS -> {last_date}")

    ext_only = panel_b.loc[panel_b.index > pd.Timestamp(K1393_OOS_END)]
    reports["extension_window_only"] = dm_report(ext_only, "extension window only (new days)")

    # COVID subperiods on the extended sample (continuity with K1393's C1 table)
    covid = (panel_b.index >= pd.Timestamp(COVID_START)) & (panel_b.index <= pd.Timestamp(COVID_END))
    reports["extended_non_covid"] = dm_report(panel_b.loc[~covid], "extended, non-COVID")
    reports["extended_covid_window"] = dm_report(panel_b.loc[covid], "extended, COVID window")

    # ---------- Endpoint scan ----------
    print("\n" + "-" * 78)
    print("[SCAN] DM t as a function of the OOS endpoint (month ends, 2020-01 -> last)")
    can_gjr_b, can_a4f_b, _, _ = losses(panel_b)
    d_b = can_gjr_b - can_a4f_b
    month_ends = panel_b.resample("ME").last().index
    scan = []
    for me in month_ends:
        sub = panel_b.loc[: me]
        if len(sub) < 250:
            continue
        k = len(sub)
        t_s, p_s = dm_test(can_gjr_b[:k], can_a4f_b[:k], h=1)
        scan.append({
            "oos_end": str(sub.index[-1].date()), "n": int(k),
            "dm_t": float(t_s), "p_value": float(p_s),
            "harvey_significant": bool(abs(t_s) > HARVEY_THRESHOLD),
            "cum_loss_diff": float(np.sum(d_b[:k])),
        })
    print(f"  scanned {len(scan)} endpoints; "
          f"t range [{min(s['dm_t'] for s in scan):+.2f}, {max(s['dm_t'] for s in scan):+.2f}]")
    print("  last 8 endpoints:")
    for s in scan[-8:]:
        print(f"    {s['oos_end']}  n={s['n']:<5} t={s['dm_t']:+.3f}  "
              f"{'HARVEY-SIG' if s['harvey_significant'] else 'not sig'}")
    n_sig = sum(1 for s in scan if s["harvey_significant"] and s["dm_t"] > 0)
    n_neg = sum(1 for s in scan if s["dm_t"] < 0)
    print(f"  endpoints with A4f Harvey-sig: {n_sig}/{len(scan)} | with t<0 (GJR ahead): {n_neg}")

    # ---------- Numerical sensitivity: decompose data effect vs estimation effect ----------
    t_paper_anchor = reports["anchor_2026_04_07_paper_csv"]["dm_t_canonical"]
    t_snap_anchor = reports["anchor_2026_04_07_new_snapshot"]["dm_t_canonical"]
    idx_p = df_paper.index[df_paper.index <= pd.Timestamp(K1393_OOS_END)]
    idx_s = df_snap.index[df_snap.index <= pd.Timestamp(K1393_OOS_END)]
    same_dates = bool(idx_p.equals(idx_s))
    common = idx_p.intersection(idx_s)
    max_ret_gap = float(np.max(np.abs(
        df_paper.loc[common, "log_ret"].values - df_snap.loc[common, "log_ret"].values)))
    gap_3start = abs(t_snap_anchor - t_paper_anchor)

    print("\n" + "-" * 78)
    print("[SENSITIVITY] same 1825 forecast days, two data vintages")
    print(f"  identical date sets    : {same_dates}")
    print(f"  max |dlog_ret|         : {max_ret_gap:.3e}  (adjusted-close rounding only)")
    print(f"  DM t on paper CSV      : {t_paper_anchor:+.3f}")
    print(f"  DM t on new snapshot   : {t_snap_anchor:+.3f}")
    print(f"  raw gap                : {gap_3start:.3f}")

    # RUN G — hold the FITS constant, swap only the data. Whatever moves now is the pure
    # data effect; the rest of the raw gap is the estimation (local-optimum) effect.
    # Without this, "it's optimiser noise" would be a story, not a measurement.
    print("\n[DECOMP] RUN G — RUN C's fitted params, evaluated on the paper CSV")
    panel_g, _ = run_rolling(df_paper, OOS_START, K1393_OOS_END, "RUN G / frozen params",
                             frozen_params=params_c)
    rep_g = dm_report(panel_g, "frozen RUN C params on paper CSV")
    reports["frozen_params_c_on_paper_csv"] = rep_g

    data_effect = abs(rep_g["dm_t_canonical"] - t_snap_anchor)
    estimation_effect = abs(rep_g["dm_t_canonical"] - t_paper_anchor)
    print(f"\n  DM t, snapshot data + snapshot fits : {t_snap_anchor:+.3f}")
    print(f"  DM t, paper data    + snapshot fits : {rep_g['dm_t_canonical']:+.3f}   "
          f"<- only the data changed  => data effect      = {data_effect:.3f}")
    print(f"  DM t, paper data    + paper fits    : {t_paper_anchor:+.3f}   "
          f"<- only the fits changed  => estimation effect = {estimation_effect:.3f}")

    # ---------- RUN D / RUN E: symmetric multistart robustness ----------
    print("\n" + "-" * 78)
    print(f"[ROBUST] RUN D — pinned snapshot, extended endpoint, {EXTRA_STARTS} extra starts "
          "(both models)")
    panel_d, out_d = run_rolling(df_snap, OOS_START, last_date, "RUN D / multistart",
                                 extra_starts=EXTRA_STARTS)
    refit_d = summarize_refits(out_d["refit_diag"], "RUN D")
    reports["multistart_full_extended_oos"] = dm_report(panel_d, "MULTISTART full extended OOS")

    print("\n" + "-" * 78)
    print(f"[ROBUST] RUN E — paper CSV, 2026-04-07 anchor, {EXTRA_STARTS} extra starts")
    panel_e, out_e = run_rolling(df_paper, OOS_START, K1393_OOS_END, "RUN E / multistart",
                                 extra_starts=EXTRA_STARTS)
    refit_e = summarize_refits(out_e["refit_diag"], "RUN E")
    reports["multistart_anchor_paper_csv"] = dm_report(panel_e, "MULTISTART anchor (paper CSV)")

    print("\n" + "-" * 78)
    print("[ROBUST] RUN F — pinned snapshot, 2026-04-07 anchor, multistart")
    panel_f, _ = run_rolling(df_snap, OOS_START, K1393_OOS_END, "RUN F / multistart",
                             extra_starts=EXTRA_STARTS)
    reports["multistart_anchor_new_snapshot"] = dm_report(panel_f, "MULTISTART anchor (snapshot)")

    ms_gap = abs(reports["multistart_anchor_new_snapshot"]["dm_t_canonical"]
                 - reports["multistart_anchor_paper_csv"]["dm_t_canonical"])
    print("\n  anchor DM t gap between the two data vintages:")
    print(f"    3 starts  (K988 spec) : {gap_3start:.3f}")
    print(f"    {3 + EXTRA_STARTS} starts (multistart): {ms_gap:.3f}")
    print(f"  => multistart {'SHRINKS' if ms_gap < gap_3start else 'does NOT shrink'} the gap")

    numerical_sensitivity = {
        "question": "at the SAME endpoint on near-identical data, how much does the headline "
                    "t move, and does it move because of the data or because of the fitting?",
        "identical_date_sets_through_anchor": same_dates,
        "max_abs_logret_gap_through_anchor": max_ret_gap,
        "n_zero_return_days_anchor": reports["anchor_2026_04_07_new_snapshot"]["n_zero_return_days"],
        "anchor_dm_t_paper_csv_3start": t_paper_anchor,
        "anchor_dm_t_new_snapshot_3start": t_snap_anchor,
        "anchor_t_gap_3start": gap_3start,
        "decomposition_run_g": {
            "method": "hold RUN C's fitted parameters fixed and re-evaluate them on the paper "
                      "CSV; the residual movement is the pure data effect, and what is left of "
                      "the raw gap is the estimation (local-optimum selection) effect",
            "dm_t_snapshot_data_snapshot_fits": t_snap_anchor,
            "dm_t_paper_data_snapshot_fits": rep_g["dm_t_canonical"],
            "dm_t_paper_data_paper_fits": t_paper_anchor,
            "data_effect": data_effect,
            "estimation_effect": estimation_effect,
        },
        "anchor_dm_t_paper_csv_multistart": reports["multistart_anchor_paper_csv"]["dm_t_canonical"],
        "anchor_dm_t_new_snapshot_multistart":
            reports["multistart_anchor_new_snapshot"]["dm_t_canonical"],
        "anchor_t_gap_multistart": ms_gap,
        "multistart_shrinks_the_gap": bool(ms_gap < gap_3start),
    }

    # ---------- Verdict ----------
    full = reports["full_extended_oos"]
    ms_full = reports["multistart_full_extended_oos"]
    scan_txt = (f"none of the {len(scan)} monthly endpoints turns negative"
                if n_neg == 0 else
                f"{n_neg} of the {len(scan)} monthly endpoints turn negative")
    if full["harvey_significant"] and full["dm_t_canonical"] > 0:
        verdict, verdict_txt = "GO", (
            f"Headline holds. Extending the OOS to {last_date} (n={full['n']}) leaves the A4f "
            f"advantage Harvey-significant (canonical DM t = {full['dm_t_canonical']:+.3f}); "
            f"{scan_txt}, and the symmetric multistart re-estimation gives "
            f"t = {ms_full['dm_t_canonical']:+.3f}. Paper 9 can ship the headline and update the "
            "data-section endpoint — but it must disclose the estimation-noise band on t "
            "(see numerical_sensitivity) and stop sourcing the extended sample from the "
            "duplicate-ridden paper CSV.")
    elif full["dm_t_canonical"] > 0:
        verdict, verdict_txt = "NO-GO (weakened)", (
            f"A4f still wins on average but no longer clears |t|>3 at the extended endpoint "
            f"(t = {full['dm_t_canonical']:+.3f}, n={full['n']}). The headline must be softened "
            "and a sample-sensitivity subsection added.")
    else:
        verdict, verdict_txt = "NO-GO (reversal)", (
            f"The sign flips at the extended endpoint (t = {full['dm_t_canonical']:+.3f}, "
            f"n={full['n']}): GJR is ahead. The headline must be rewritten around "
            "sample-dependence, per the K1027 seven-window framing.")
    print("\n" + "=" * 78)
    print(f"VERDICT: {verdict}\n  {verdict_txt}")
    print("=" * 78)

    # ---------- Figures ----------
    make_figures(scan, panel_b, d_b, last_date, reports)

    # ---------- Save ----------
    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Extended-OOS re-check of A4f vs GJR under the K988/K1393-faithful spec",
        "paper": "garch-x-vix (Paper 9), review item P0-2",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - START_TIME, 1),
        "verdict": verdict,
        "verdict_text": verdict_txt,
        "configuration": {
            "oos_start": OOS_START,
            "oos_end_extended": last_date,
            "oos_end_k1393_anchor": K1393_OOS_END,
            "oos_end_k1391": K1391_OOS_END,
            "window": WINDOW,
            "refit_every": REFIT_EVERY,
            "seed": SEED,
            "a4f_spec": "vix_squared tau, denom_mode='tau_t', free_omega=True, L-BFGS-B, 3 starts",
            "theta0_bounds": "[-1e-2, 1e-2] (K988-faithful)",
            "theta1_bounds": "[1e-8, 1e-3] (K988-faithful)",
            "g_init": "omega/(1-persist) (K988-faithful)",
            "loss_primary": "volpred.stats.model_evaluation.qlike_pointwise (actual/pred - log(actual/pred) - 1), actual = r^2",
            "loss_legacy_for_gate": "log(sigma2) + r^2/sigma2 (K988/K1393 kernel)",
            "dm_test": "volpred.stats.model_evaluation.dm_test, HAC bandwidth ceil(h^(1/3) n^(1/3)), h=1",
            "dm_sign_convention": "d = QLIKE_GJR - QLIKE_A4f; positive t => A4f better",
            "significance_threshold": "|t| > 3.0 (Harvey, Liu & Zhu 2016)",
        },
        "data_provenance": provenance,
        "data_integrity_finding": {
            "file": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
            "issue": "10 duplicated dates (2026-05-04..2026-05-15, each row twice); "
                     "read with the standard sort_index+shift idiom they emit spurious "
                     "zero-return days and a doubled return on the following day",
            "also": "3 US-market-holiday rows (2026-05-25, 2026-06-19, 2026-07-03) with NaN SPY "
                    "(harmless: dropped by dropna)",
            "present_when_k1391_ran": True,
            "evidence": "git show f1bdea2d (2026-05-20, the version K1391 read) has the same 10 dups",
            "impact": "the duplicate block sits INSIDE the 41-day window K1391 blamed for the "
                      "reversal, so K1391's -2.03 is confounded by corrupted data as well as by "
                      "the degraded A4f spec K1393 identified",
            "k1393_unaffected": "duplicates are strictly after K1393's 2026-04-07 OOS end",
            "action_for_main_thread": "fix the collector that appends to this CSV (de-dup on date, "
                                      "use the SPY trading calendar); do not hand-edit the file",
        },
        "pipeline_gate": {
            "description": "RUN A must reproduce K1393 on the paper CSV at the 2026-04-07 endpoint",
            "k1393_published": K1393_REF,
            "k1685_gate_run": {
                "dm_t_k1393_convention": gate_legacy["t_stat"],
                "qlike_mean_gjr_legacy_kernel": gate_rep["qlike_mean_gjr_legacy_kernel"],
                "qlike_mean_a4f_legacy_kernel": gate_rep["qlike_mean_a4f_legacy_kernel"],
                "n": gate_rep["n"],
            },
            "abs_diff_t": dt,
            "passed": bool(gate_pass),
        },
        "prefix_property_check": {
            "description": "RUN B truncated at 2026-04-07 must equal RUN C run-to-2026-04-07; "
                           "this is what licenses the endpoint scan",
            "max_abs_sigma2_gap": prefix_gap,
            "passed": bool(prefix_ok),
        },
        "numerical_sensitivity": numerical_sensitivity,
        "multistart_robustness": {
            "description": f"RUN D/E/F: 3 canonical starts + {EXTRA_STARTS} seeded random starts, "
                           "applied SYMMETRICALLY to GJR and A4f (refining only one model would "
                           "manufacture the K1216b asymmetric artifact). Supplement, not headline: "
                           "the headline stays on the faithful 3-start K988 spec.",
            "extra_starts": EXTRA_STARTS,
            "refit_summary_extended": refit_d,
            "refit_summary_anchor_paper_csv": refit_e,
        },
        "dm_reports": reports,
        "endpoint_scan": scan,
        "endpoint_scan_summary": {
            "n_endpoints": len(scan),
            "n_a4f_harvey_significant": int(n_sig),
            "n_gjr_ahead": int(n_neg),
            "t_min": float(min(s["dm_t"] for s in scan)),
            "t_max": float(max(s["dm_t"] for s in scan)),
        },
        "references": {
            "K988": "original A4f vs GJR spec comparison (canonical spec source)",
            "K1391": "extended OOS with degraded spec AND duplicated data -> t = -2.03",
            "K1392": "COVID re-run with degraded spec -> t = -1.61",
            "K1393": "K988-faithful replication at the 2026-04-07 endpoint -> t = +3.60",
            "K1027": "seven-window sample-sensitivity evidence",
        },
    }

    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return super().default(obj)

    with open(RESULTS_PATH, "w") as fh:
        json.dump(results, fh, indent=2, cls=NpEncoder)
    print(f"\nResults -> {RESULTS_PATH}")
    print(f"Elapsed : {time.time() - START_TIME:.0f}s")


def make_figures(scan, panel_b, d_b, last_date, reports):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(FIG_DIR, exist_ok=True)
    ends = [pd.Timestamp(s["oos_end"]) for s in scan]
    ts = [s["dm_t"] for s in scan]

    # Figure 1 — DM t vs OOS endpoint
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(ends, ts, lw=1.8, color="#1f4e79", label="canonical DM $t$ (A4f vs GJR)")
    ax.axhline(HARVEY_THRESHOLD, ls="--", lw=1.2, color="#c00000",
               label="Harvey threshold $|t|=3$")
    ax.axhline(-HARVEY_THRESHOLD, ls="--", lw=1.2, color="#c00000")
    ax.axhline(0, lw=0.8, color="grey")
    anchor = pd.Timestamp(K1393_OOS_END)
    t_anchor = min(scan, key=lambda s: abs(pd.Timestamp(s["oos_end"]) - anchor))
    ax.plot([pd.Timestamp(t_anchor["oos_end"])], [t_anchor["dm_t"]], "o", ms=9,
            color="#2e7d32", zorder=5,
            label=f"paper / K1393 endpoint 2026-04-07 ($t$={t_anchor['dm_t']:+.2f})")
    ax.plot([ends[-1]], [ts[-1]], "D", ms=9, color="#e65100", zorder=5,
            label=f"extended endpoint {last_date} ($t$={ts[-1]:+.2f})")
    ms_t = reports["multistart_full_extended_oos"]["dm_t_canonical"]
    ax.plot([ends[-1]], [ms_t], "*", ms=15, color="#6a1b9a", zorder=6,
            label=f"same endpoint, symmetric multistart ($t$={ms_t:+.2f})")
    ax.axvspan(anchor, ends[-1], color="#ffd54f", alpha=0.25,
               label="extension window (new data)")
    ax.set_xlabel("OOS end date")
    ax.set_ylabel("DM $t$   (>0: A4f better)")
    ax.set_title("K1685 — is the GARCH-X headline sensitive to where the sample stops?\n"
                 "expanding OOS endpoint, K988/K1393-faithful spec, canonical QLIKE + HAC DM")
    ax.legend(loc="lower left", fontsize=9, framealpha=0.9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "k1685_dm_t_vs_oos_end.png"), dpi=150)
    plt.close(fig)

    # Figure 2 — cumulative loss differential
    fig, ax = plt.subplots(figsize=(11, 5.0))
    ax.plot(panel_b.index, np.cumsum(d_b), lw=1.5, color="#1f4e79")
    ax.axhline(0, lw=0.8, color="grey")
    ax.axvline(anchor, ls="--", lw=1.2, color="#2e7d32")
    ax.axvspan(anchor, panel_b.index[-1], color="#ffd54f", alpha=0.25)
    ax.text(anchor, ax.get_ylim()[1] * 0.95, " paper OOS end (2026-04-07)",
            fontsize=9, color="#2e7d32", va="top")
    ax.set_xlabel("date")
    ax.set_ylabel(r"cumulative $\sum (QLIKE_{GJR} - QLIKE_{A4f})$")
    ax.set_title("K1685 — where does A4f's QLIKE advantage accrue?  "
                 "(rising = A4f pulling ahead)")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "k1685_cumulative_loss_diff.png"), dpi=150)
    plt.close(fig)
    print(f"\nFigures -> {FIG_DIR}/")


if __name__ == "__main__":
    main()
