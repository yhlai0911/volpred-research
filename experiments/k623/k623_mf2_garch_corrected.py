"""
K623: MF2-GARCH CORRECTED — Fixing 3 HIGH-severity bugs from K621 (Codex review)

Reference: Conrad, C. & Engle, R.F. (2025). Modelling Volatility Cycles: The MF2-GARCH Model.
           Journal of Applied Econometrics, 40(4), 438-454.

K621 Bugs Fixed:
  1. SHORT-RUN BLOCK: Was standard raw-return GJR with free omega.
     CORRECT: Unit-mean, dimensionless GJR driven by r²/τ with intercept (1 - α - γ/2 - β)
  2. V_m INPUT: Was ε²/σ² from wrong σ². CORRECT: V_t = (r-μ)²/(g_t × τ_t)
  3. BIC COMPARISON: Different m → different sample sizes → invalid comparison.
     CORRECT: Use same effective sample (discard first max(m_candidates) obs for ALL m)

Model specification:
  r_t = μ + sqrt(τ_t × g_t) × z_t,   z_t ~ N(0,1)

  Short-term (unit-mean GJR):
    g_t = (1 - α - γ/2 - β) + α × (r_{t-1} - μ)² / τ_{t-1}
          + γ × I_{t-1} × (r_{t-1} - μ)² / τ_{t-1} + β × g_{t-1}

  Long-term (MEM filter):
    τ_t = λ₁ + λ₂ × V^m_{t-1} + λ₃ × τ_{t-1}
    V^m_{t-1} = (1/m) × Σ_{j=1}^{m} V_{t-j}
    V_t = (r_t - μ)² / (g_t × τ_t)

  Conditional variance: h_t = g_t × τ_t

Data source: yfinance (SPY, 2006-01-01 to 2026-03-27)
Proxy: σ²_proxy = r²_t (squared daily returns)
OOS: 2023-01-01 to 2024-12-31, re-estimate every 21 trading days
"""

import json
import sys
import time
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

# ─── Configuration ───────────────────────────────────────────────────────────
ASSET = "SPY"
START = "2006-01-01"
END = "2026-03-27"
WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
REFIT_EVERY = 21
M_CANDIDATES = [22, 44, 66, 126, 252]
MAX_M = max(M_CANDIDATES)  # For uniform burn-in
EWMA_LAMBDA = 0.94
PRINT_EVERY = 50

# ─── Data download ───────────────────────────────────────────────────────────
print(f"Downloading {ASSET} from {START} to {END}...")
df = yf.download(ASSET, start=START, end=END, auto_adjust=True, progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
prices = df["Close"].dropna()
returns = 100.0 * prices.pct_change().dropna()  # percentage returns
dates = returns.index
T = len(returns)
print(f"Total observations: {T}, from {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")

returns_arr = returns.values.astype(np.float64)
proxy = returns_arr ** 2  # squared returns as proxy


# ═══════════════════════════════════════════════════════════════════════════════
# GJR-GARCH(1,1) baseline using arch package
# ═══════════════════════════════════════════════════════════════════════════════
def fit_gjr(ret_window):
    """Fit GJR-GARCH(1,1) and return conditional variance array + 1-step forecast."""
    am = arch_model(ret_window, vol="GARCH", p=1, o=1, q=1, mean="Zero", dist="normal")
    res = am.fit(disp="off", show_warning=False)
    cond_var = res.conditional_volatility ** 2
    fc = res.forecast(horizon=1, reindex=False)
    h_next = fc.variance.values[0, 0]
    return cond_var.values, h_next, res


# ═══════════════════════════════════════════════════════════════════════════════
# EWMA baseline
# ═══════════════════════════════════════════════════════════════════════════════
def ewma_forecast(ret_window, lam=EWMA_LAMBDA):
    """EWMA variance filter + 1-step forecast."""
    n = len(ret_window)
    h = np.zeros(n)
    h[0] = np.var(ret_window)
    for t in range(1, n):
        h[t] = lam * h[t - 1] + (1 - lam) * ret_window[t - 1] ** 2
    h_next = lam * h[-1] + (1 - lam) * ret_window[-1] ** 2
    return h, h_next


# ═══════════════════════════════════════════════════════════════════════════════
# MF2-GARCH CORRECTED implementation
# ═══════════════════════════════════════════════════════════════════════════════

def _mf2_filter(ret, mu, alpha, gamma_p, beta, lam1, lam2, lam3, m):
    """
    CORRECTED MF2-GARCH filter. Returns (g, tau, h, V_m).

    Short-term (unit-mean, dimensionless):
      g_t = (1 - α - γ/2 - β) + α × (r_{t-1} - μ)² / τ_{t-1}
            + γ × I_{t-1} × (r_{t-1} - μ)² / τ_{t-1} + β × g_{t-1}

    Long-term:
      τ_t = λ₁ + λ₂ × V^m_{t-1} + λ₃ × τ_{t-1}
      V_t = (r_t - μ)² / (g_t × τ_t)    [complete standardized squared residual]

    h_t = g_t × τ_t
    """
    n = len(ret)
    g = np.ones(n)       # short-term (unit mean, init = 1)
    tau = np.ones(n)     # long-term
    h = np.ones(n)       # total variance
    V = np.ones(n)       # standardized squared residuals
    V_m = np.full(n, np.nan)  # rolling average of V

    # Intercept ensuring E[g_t] = 1
    intercept = 1.0 - alpha - gamma_p / 2.0 - beta

    # Initialize: τ_0 = unconditional variance of returns, g_0 = 1
    eps2 = (ret - mu) ** 2
    tau[0] = np.mean(eps2)  # sample variance as initial τ
    if tau[0] <= 0:
        tau[0] = 1.0
    g[0] = 1.0
    h[0] = g[0] * tau[0]

    # V_0: since h_0 = τ_0, V_0 = eps2_0 / h_0
    V[0] = eps2[0] / max(h[0], 1e-10)

    # Unconditional τ for initialization
    tau_unc = lam1 / max(1.0 - lam3, 1e-6) if (1.0 - lam3) > 1e-6 else np.mean(eps2)
    if tau_unc <= 0 or np.isnan(tau_unc):
        tau_unc = np.mean(eps2)

    for t in range(1, n):
        # ── Short-term: g_t uses r²/τ (dimensionless input) ──
        input_val = eps2[t - 1] / max(tau[t - 1], 1e-10)
        ind = 1.0 if ret[t - 1] < mu else 0.0
        g[t] = intercept + alpha * input_val + gamma_p * ind * input_val + beta * g[t - 1]

        # Guard g_t > 0
        if g[t] < 1e-6:
            g[t] = 1e-6

        # ── Long-term: τ_t uses V^m_{t-1} ──
        if t >= m and not np.isnan(V_m[t - 1]):
            tau[t] = lam1 + lam2 * V_m[t - 1] + lam3 * tau[t - 1]
        else:
            # Before enough V's accumulated, use simple AR(1) with unconditional level
            tau[t] = lam1 + lam2 * 1.0 + lam3 * tau[t - 1]

        # Guard τ_t > 0
        if tau[t] < 1e-4:
            tau[t] = 1e-4
        if tau[t] > 500.0:
            tau[t] = 500.0

        # ── Total variance ──
        h[t] = g[t] * tau[t]

        # ── V_t = (r_t - μ)² / (g_t × τ_t) = eps2_t / h_t  [CORRECT] ──
        V[t] = eps2[t] / max(h[t], 1e-10)

        # ── V^m_t = rolling mean of V_{t-m+1:t} ──
        if t >= m - 1:
            V_m[t] = np.mean(V[t - m + 1: t + 1])

    return g, tau, h, V, V_m


def _mf2_negloglik(params, ret, mu, m, burn):
    """
    Negative log-likelihood for MF2-GARCH.
    params = [alpha, gamma, beta, lam1, lam2, lam3]
    Note: NO omega — the intercept is determined by unit-mean constraint.
    burn = uniform burn-in for all m values (= max(M_CANDIDATES))
    """
    alpha, gamma_p, beta, lam1, lam2, lam3 = params

    # Check constraints before filtering
    persistence_g = alpha + gamma_p / 2.0 + beta
    if persistence_g >= 1.0:
        return 1e10
    intercept = 1.0 - persistence_g
    if intercept <= 0:
        return 1e10
    if lam2 + lam3 >= 1.0:
        return 1e10

    n = len(ret)
    g, tau, h, V, V_m = _mf2_filter(ret, mu, alpha, gamma_p, beta, lam1, lam2, lam3, m)

    # Log-likelihood (Gaussian QML)
    # Use UNIFORM burn-in = max(M_CANDIDATES) for all m — FIX for Bug #3
    h_valid = h[burn:]
    r_valid = ret[burn:]
    eps2_valid = (r_valid - mu) ** 2

    # Guard against numerical issues
    h_valid = np.maximum(h_valid, 1e-10)

    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(h_valid) + eps2_valid / h_valid)

    if np.isnan(ll) or np.isinf(ll):
        return 1e10
    return -ll


def fit_mf2_garch(ret, m, burn, max_tries=5):
    """
    Fit CORRECTED MF2-GARCH with given m by QML.
    params = [alpha, gamma, beta, lam1, lam2, lam3]  (6 params, no omega)
    burn = uniform burn-in for BIC comparability
    Returns: (params_dict, negll, converged, h_insample, h_forecast)
    """
    n = len(ret)
    mu = np.mean(ret)  # sample mean

    # Get initial GJR estimates for starting values
    try:
        am = arch_model(pd.Series(ret), vol="GARCH", p=1, o=1, q=1, mean="Zero", dist="normal")
        res0 = am.fit(disp="off", show_warning=False)
        alpha0 = float(res0.params.get("alpha[1]", 0.05))
        gamma0 = float(res0.params.get("gamma[1]", 0.05))
        beta0 = float(res0.params.get("beta[1]", 0.90))
    except Exception:
        alpha0, gamma0, beta0 = 0.05, 0.05, 0.90

    # Bounds: alpha>=0, gamma>=0, beta>=0; lam1>0, lam2>=0, lam3>=0
    bounds = [
        (1e-6, 0.4),     # alpha
        (0.0, 0.4),      # gamma
        (0.01, 0.998),   # beta
        (1e-6, 50.0),    # lam1
        (0.0, 5.0),      # lam2
        (0.0, 0.999),    # lam3
    ]

    # Multiple starting points
    starts = [
        [alpha0, gamma0, beta0, 0.05, 0.1, 0.85],
        [alpha0 * 0.8, gamma0 * 1.2, min(beta0 * 1.02, 0.98), 0.1, 0.2, 0.7],
        [0.03, 0.06, 0.92, 0.02, 0.05, 0.90],
        [0.08, 0.10, 0.85, 0.08, 0.15, 0.75],
        [alpha0 * 1.2, gamma0 * 0.8, beta0 * 0.95, 0.03, 0.08, 0.88],
    ]

    best_negll = 1e10
    best_params = None
    best_converged = False

    # Constraints
    constraints = [
        {"type": "ineq", "fun": lambda p: 0.999 - (p[3 + 1] + p[3 + 2])},  # lam2 + lam3 < 1
        {"type": "ineq", "fun": lambda p: 0.999 - (p[0] + p[1] / 2.0 + p[2])},  # g stationarity
    ]

    for i, x0 in enumerate(starts[:max_tries]):
        try:
            result = minimize(
                _mf2_negloglik,
                x0,
                args=(ret, mu, m, burn),
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-10},
            )
            if result.fun < best_negll:
                best_negll = result.fun
                best_params = result.x.copy()
                best_converged = result.success
        except Exception:
            continue

    if best_params is None:
        # Fallback: return g=1 (tau-only model)
        var_ret = np.var(ret)
        return None, 1e10, False, np.full(n, var_ret), var_ret

    alpha, gamma_p, beta, lam1, lam2, lam3 = best_params

    # Reconstruct in-sample fit
    g, tau, h_insample, V, V_m = _mf2_filter(ret, mu, alpha, gamma_p, beta, lam1, lam2, lam3, m)

    # 1-step-ahead forecast
    eps2_last = (ret[-1] - mu) ** 2
    ind_last = 1.0 if ret[-1] < mu else 0.0
    input_last = eps2_last / max(tau[-1], 1e-10)
    intercept = 1.0 - alpha - gamma_p / 2.0 - beta

    g_next = intercept + alpha * input_last + gamma_p * ind_last * input_last + beta * g[-1]
    g_next = max(g_next, 1e-6)

    vm_last = V_m[-1] if not np.isnan(V_m[-1]) else 1.0
    tau_next = lam1 + lam2 * vm_last + lam3 * tau[-1]
    tau_next = max(tau_next, 1e-4)

    h_next = g_next * tau_next

    params_dict = {
        "alpha": float(alpha),
        "gamma": float(gamma_p),
        "beta": float(beta),
        "lam1": float(lam1),
        "lam2": float(lam2),
        "lam3": float(lam3),
        "mu": float(mu),
        "intercept": float(intercept),
        "persistence_g": float(alpha + gamma_p / 2.0 + beta),
        "persistence_tau": float(lam2 + lam3),
    }

    return params_dict, best_negll, best_converged, h_insample, h_next


def select_m_by_bic(ret, m_candidates, burn):
    """
    Select optimal m by BIC.
    BUG FIX #3: Use SAME effective sample for all m.
    burn = max(m_candidates) ensures all models use identical observations.
    BIC = -2*(LL/n_eff) + k*ln(n_eff)/n_eff  (per-obs normalized)
    """
    k = 6  # 6 parameters (no omega in corrected version)
    n_eff = len(ret) - burn  # same for all m
    best_bic = np.inf
    best_m = m_candidates[0]
    results = {}

    for m in m_candidates:
        params_dict, negll, converged, _, _ = fit_mf2_garch(ret, m, burn=burn, max_tries=5)
        # BIC per observation (normalized)
        bic_per_obs = 2 * negll / n_eff + k * np.log(n_eff) / n_eff
        results[m] = {
            "bic_per_obs": float(bic_per_obs),
            "negll": float(negll),
            "negll_per_obs": float(negll / n_eff),
            "converged": converged,
            "params": params_dict,
        }
        if bic_per_obs < best_bic and converged:
            best_bic = bic_per_obs
            best_m = m

    return best_m, results


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluation metrics
# ═══════════════════════════════════════════════════════════════════════════════

def qlike(proxy_arr, forecast_arr):
    """QLIKE loss: mean(proxy/forecast - log(proxy/forecast) - 1)"""
    ratio = proxy_arr / np.maximum(forecast_arr, 1e-10)
    return float(np.mean(ratio - np.log(np.maximum(ratio, 1e-10)) - 1))


def mse_loss(proxy_arr, forecast_arr):
    """MSE loss: mean((proxy - forecast)^2)"""
    return float(np.mean((proxy_arr - forecast_arr) ** 2))


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test (two-sided).
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Negative DM stat means model 1 is better.
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    if h > 1:
        for k in range(1, h):
            gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
            gamma0 += 2 * (1 - k / h) * gamma_k
    se = np.sqrt(gamma0 / n)
    if se < 1e-12:
        return 0.0, 1.0
    dm_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)


def _mf2_forecast_from_params(ret_window, params_dict, m):
    """
    Given a fitted MF2-GARCH params_dict and a window of returns,
    run the filter and produce a 1-step-ahead forecast.
    """
    mu = params_dict["mu"]
    alpha = params_dict["alpha"]
    gamma_p = params_dict["gamma"]
    beta = params_dict["beta"]
    lam1 = params_dict["lam1"]
    lam2 = params_dict["lam2"]
    lam3 = params_dict["lam3"]

    g, tau, h, V, V_m = _mf2_filter(ret_window, mu, alpha, gamma_p, beta, lam1, lam2, lam3, m)

    # 1-step-ahead forecast
    eps2_last = (ret_window[-1] - mu) ** 2
    ind_last = 1.0 if ret_window[-1] < mu else 0.0
    input_last = eps2_last / max(tau[-1], 1e-10)
    intercept = 1.0 - alpha - gamma_p / 2.0 - beta

    g_next = intercept + alpha * input_last + gamma_p * ind_last * input_last + beta * g[-1]
    g_next = max(g_next, 1e-6)

    vm_last = V_m[-1] if not np.isnan(V_m[-1]) else 1.0
    tau_next = lam1 + lam2 * vm_last + lam3 * tau[-1]
    tau_next = max(tau_next, 1e-4)

    return g_next * tau_next


# ═══════════════════════════════════════════════════════════════════════════════
# Rolling OOS evaluation
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Phase 1: Select optimal m on pre-OOS sample")
print("=" * 70)

# Find OOS start index
oos_start_idx = None
for i, d in enumerate(dates):
    if d >= pd.Timestamp(OOS_START):
        oos_start_idx = i
        break

if oos_start_idx is None:
    print("ERROR: OOS start date not found")
    sys.exit(1)

# Use pre-OOS data to select m (last WINDOW obs before OOS)
pre_oos_ret = returns_arr[max(0, oos_start_idx - WINDOW):oos_start_idx]
print(f"Pre-OOS sample: {len(pre_oos_ret)} obs, selecting m from {M_CANDIDATES}...")
print(f"Uniform burn-in = {MAX_M} (max of m candidates) — FIX for Bug #3")

t0_m = time.time()
optimal_m, m_selection_results = select_m_by_bic(pre_oos_ret, M_CANDIDATES, burn=MAX_M)
t_m = time.time() - t0_m
print(f"\nOptimal m = {optimal_m} (took {t_m:.1f}s)")
for m_val, mres in m_selection_results.items():
    tag = " ← BEST" if m_val == optimal_m else ""
    conv = "✓" if mres["converged"] else "✗"
    print(f"  m={m_val:>3d}: BIC/obs={mres['bic_per_obs']:.6f}, "
          f"negLL/obs={mres['negll_per_obs']:.4f}, conv={conv}{tag}")
    if mres["params"] is not None:
        p = mres["params"]
        print(f"         α={p['alpha']:.4f}, γ={p['gamma']:.4f}, β={p['beta']:.4f}, "
              f"persist_g={p['persistence_g']:.4f}")
        print(f"         λ₁={p['lam1']:.4f}, λ₂={p['lam2']:.4f}, λ₃={p['lam3']:.4f}, "
              f"persist_τ={p['persistence_tau']:.4f}")


print("\n" + "=" * 70)
print("Phase 2: Rolling OOS evaluation")
print("=" * 70)

# Find OOS end index
oos_end_idx = None
for i, d in enumerate(dates):
    if d > pd.Timestamp(OOS_END):
        oos_end_idx = i
        break
if oos_end_idx is None:
    oos_end_idx = T

oos_indices = list(range(oos_start_idx, oos_end_idx))
n_oos = len(oos_indices)
print(f"OOS period: {dates[oos_start_idx].strftime('%Y-%m-%d')} to "
      f"{dates[oos_end_idx-1].strftime('%Y-%m-%d')}")
print(f"OOS observations: {n_oos}")
print(f"Re-estimating every {REFIT_EVERY} days, window={WINDOW}")

# Storage
fc_gjr = np.zeros(n_oos)
fc_mf2 = np.zeros(n_oos)
fc_ewma = np.zeros(n_oos)
proxy_oos = np.zeros(n_oos)
oos_dates = []

# Track parameters and convergence
gjr_params_log = []
mf2_params_log = []
mf2_convergence = []
g_mean_log = []
tau_mean_log = []

t_start = time.time()
last_fit_gjr = None
last_fit_mf2 = None
refit_count = 0

for k, t_idx in enumerate(oos_indices):
    need_refit = (k % REFIT_EVERY == 0) or (last_fit_mf2 is None)

    # Window of returns for estimation
    w_start = max(0, t_idx - WINDOW)
    ret_window = returns_arr[w_start:t_idx]

    oos_dates.append(dates[t_idx].strftime("%Y-%m-%d"))

    if need_refit:
        refit_count += 1

        # ── GJR-GARCH ──
        try:
            cond_var_gjr, h_gjr, res_gjr = fit_gjr(pd.Series(ret_window, name="ret"))
            last_fit_gjr = {
                "omega": float(res_gjr.params.get("omega", 0.05)),
                "alpha": float(res_gjr.params.get("alpha[1]", 0.05)),
                "gamma": float(res_gjr.params.get("gamma[1]", 0.05)),
                "beta": float(res_gjr.params.get("beta[1]", 0.90)),
            }
            gjr_params_log.append(last_fit_gjr.copy())
        except Exception:
            if last_fit_gjr is not None:
                p = last_fit_gjr
                sigma2 = np.zeros(len(ret_window))
                sigma2[0] = np.var(ret_window)
                for tt in range(1, len(ret_window)):
                    e2 = ret_window[tt-1] ** 2
                    ind = 1.0 if ret_window[tt-1] < 0 else 0.0
                    sigma2[tt] = p["omega"] + p["alpha"] * e2 + p["gamma"] * e2 * ind + p["beta"] * sigma2[tt-1]
                e2 = ret_window[-1] ** 2
                ind = 1.0 if ret_window[-1] < 0 else 0.0
                h_gjr = p["omega"] + p["alpha"] * e2 + p["gamma"] * e2 * ind + p["beta"] * sigma2[-1]
            else:
                h_gjr = np.var(ret_window)

        # ── MF2-GARCH (CORRECTED) ──
        try:
            params_dict, mf2_negll, mf2_conv, mf2_h_is, h_mf2 = fit_mf2_garch(
                ret_window, optimal_m, burn=MAX_M, max_tries=5
            )
            if params_dict is not None:
                last_fit_mf2 = params_dict.copy()
                mf2_params_log.append(params_dict.copy())
                mf2_convergence.append(mf2_conv)

                # Log diagnostics: mean of g and tau
                mu = params_dict["mu"]
                g, tau, h_is, V, V_m = _mf2_filter(
                    ret_window, mu, params_dict["alpha"], params_dict["gamma"],
                    params_dict["beta"], params_dict["lam1"], params_dict["lam2"],
                    params_dict["lam3"], optimal_m
                )
                g_mean_log.append(float(np.mean(g[MAX_M:])))
                tau_mean_log.append(float(np.mean(tau[MAX_M:])))
            else:
                h_mf2 = np.var(ret_window)
                mf2_convergence.append(False)
        except Exception as e:
            if last_fit_mf2 is not None:
                h_mf2 = _mf2_forecast_from_params(ret_window, last_fit_mf2, optimal_m)
            else:
                h_mf2 = np.var(ret_window)
            mf2_convergence.append(False)

        # ── EWMA ──
        _, h_ewma = ewma_forecast(ret_window)

    else:
        # Update without re-estimation
        # GJR update
        if last_fit_gjr is not None:
            p = last_fit_gjr
            sigma2 = np.zeros(len(ret_window))
            sigma2[0] = np.var(ret_window)
            for tt in range(1, len(ret_window)):
                e2 = ret_window[tt-1] ** 2
                ind = 1.0 if ret_window[tt-1] < 0 else 0.0
                sigma2[tt] = p["omega"] + p["alpha"] * e2 + p["gamma"] * e2 * ind + p["beta"] * sigma2[tt-1]
            e2 = ret_window[-1] ** 2
            ind = 1.0 if ret_window[-1] < 0 else 0.0
            h_gjr = p["omega"] + p["alpha"] * e2 + p["gamma"] * e2 * ind + p["beta"] * sigma2[-1]
        else:
            h_gjr = np.var(ret_window)

        # MF2 update
        if last_fit_mf2 is not None:
            h_mf2 = _mf2_forecast_from_params(ret_window, last_fit_mf2, optimal_m)
        else:
            h_mf2 = np.var(ret_window)

        # EWMA update
        _, h_ewma = ewma_forecast(ret_window)

    # Store forecasts and proxy
    fc_gjr[k] = max(h_gjr, 1e-10)
    fc_mf2[k] = max(h_mf2, 1e-10)
    fc_ewma[k] = max(h_ewma, 1e-10)
    proxy_oos[k] = proxy[t_idx]

    if (k + 1) % PRINT_EVERY == 0 or k == n_oos - 1:
        elapsed = time.time() - t_start
        pct = 100 * (k + 1) / n_oos
        print(f"  [{k+1:>4d}/{n_oos}] {pct:5.1f}%  date={dates[t_idx].strftime('%Y-%m-%d')}  "
              f"elapsed={elapsed:.0f}s  "
              f"h_gjr={h_gjr:.4f}  h_mf2={h_mf2:.4f}  h_ewma={h_ewma:.4f}  "
              f"proxy={proxy_oos[k]:.4f}")

total_time = time.time() - t_start
conv_rate = sum(mf2_convergence) / len(mf2_convergence) if mf2_convergence else 0

print(f"\nDone! Total time: {total_time:.1f}s")
print(f"Refits: {refit_count}, MF2 convergence rate: {conv_rate:.1%}")
if g_mean_log:
    print(f"Mean g (should ≈ 1.0): {np.mean(g_mean_log):.4f} ± {np.std(g_mean_log):.4f}")
    print(f"Mean τ: {np.mean(tau_mean_log):.4f} ± {np.std(tau_mean_log):.4f}")

# ═══════════════════════════════════════════════════════════════════════════════
# Results
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Phase 3: OOS Evaluation Results")
print("=" * 70)

# Per-observation QLIKE losses (for DM test)
qlike_gjr_arr = proxy_oos / np.maximum(fc_gjr, 1e-10) - np.log(
    np.maximum(proxy_oos / np.maximum(fc_gjr, 1e-10), 1e-10)) - 1
qlike_mf2_arr = proxy_oos / np.maximum(fc_mf2, 1e-10) - np.log(
    np.maximum(proxy_oos / np.maximum(fc_mf2, 1e-10), 1e-10)) - 1
qlike_ewma_arr = proxy_oos / np.maximum(fc_ewma, 1e-10) - np.log(
    np.maximum(proxy_oos / np.maximum(fc_ewma, 1e-10), 1e-10)) - 1

# MSE per-obs losses
mse_gjr_arr = (proxy_oos - fc_gjr) ** 2
mse_mf2_arr = (proxy_oos - fc_mf2) ** 2
mse_ewma_arr = (proxy_oos - fc_ewma) ** 2

# Aggregate losses
qlike_gjr = float(np.mean(qlike_gjr_arr))
qlike_mf2 = float(np.mean(qlike_mf2_arr))
qlike_ewma = float(np.mean(qlike_ewma_arr))

mse_gjr = float(np.mean(mse_gjr_arr))
mse_mf2 = float(np.mean(mse_mf2_arr))
mse_ewma = float(np.mean(mse_ewma_arr))

print(f"\n{'Model':<20s} {'QLIKE':>10s} {'MSE':>12s}")
print("-" * 45)
print(f"{'GJR-GARCH(1,1)':<20s} {qlike_gjr:>10.6f} {mse_gjr:>12.4f}")
print(f"{'MF2-GARCH (corr.)':<20s} {qlike_mf2:>10.6f} {mse_mf2:>12.4f}")
print(f"{'EWMA(0.94)':<20s} {qlike_ewma:>10.6f} {mse_ewma:>12.4f}")

# DM tests (QLIKE)
print("\n--- Diebold-Mariano Tests (QLIKE) ---")
dm_mf2_gjr, p_mf2_gjr = dm_test(qlike_mf2_arr, qlike_gjr_arr)
dm_mf2_ewma, p_mf2_ewma = dm_test(qlike_mf2_arr, qlike_ewma_arr)
dm_gjr_ewma, p_gjr_ewma = dm_test(qlike_gjr_arr, qlike_ewma_arr)

print(f"  MF2 vs GJR:   DM = {dm_mf2_gjr:+.4f}, p = {p_mf2_gjr:.4f}  "
      f"{'MF2 better' if dm_mf2_gjr < 0 else 'GJR better'}")
print(f"  MF2 vs EWMA:  DM = {dm_mf2_ewma:+.4f}, p = {p_mf2_ewma:.4f}  "
      f"{'MF2 better' if dm_mf2_ewma < 0 else 'EWMA better'}")
print(f"  GJR vs EWMA:  DM = {dm_gjr_ewma:+.4f}, p = {p_gjr_ewma:.4f}  "
      f"{'GJR better' if dm_gjr_ewma < 0 else 'EWMA better'}")

# DM tests (MSE)
print("\n--- Diebold-Mariano Tests (MSE) ---")
dm_mf2_gjr_mse, p_mf2_gjr_mse = dm_test(mse_mf2_arr, mse_gjr_arr)
dm_mf2_ewma_mse, p_mf2_ewma_mse = dm_test(mse_mf2_arr, mse_ewma_arr)
dm_gjr_ewma_mse, p_gjr_ewma_mse = dm_test(mse_gjr_arr, mse_ewma_arr)

print(f"  MF2 vs GJR:   DM = {dm_mf2_gjr_mse:+.4f}, p = {p_mf2_gjr_mse:.4f}  "
      f"{'MF2 better' if dm_mf2_gjr_mse < 0 else 'GJR better'}")
print(f"  MF2 vs EWMA:  DM = {dm_mf2_ewma_mse:+.4f}, p = {p_mf2_ewma_mse:.4f}  "
      f"{'MF2 better' if dm_mf2_ewma_mse < 0 else 'EWMA better'}")
print(f"  GJR vs EWMA:  DM = {dm_gjr_ewma_mse:+.4f}, p = {p_gjr_ewma_mse:.4f}  "
      f"{'GJR better' if dm_gjr_ewma_mse < 0 else 'EWMA better'}")

# Forecast statistics
print("\n--- Forecast Diagnostics ---")
for name, fc in [("GJR", fc_gjr), ("MF2", fc_mf2), ("EWMA", fc_ewma)]:
    print(f"  {name}: mean={np.mean(fc):.4f}, std={np.std(fc):.4f}, "
          f"min={np.min(fc):.4f}, max={np.max(fc):.4f}")
print(f"  Proxy: mean={np.mean(proxy_oos):.4f}, std={np.std(proxy_oos):.4f}")

# Correlation between forecasts
corr_mf2_gjr = np.corrcoef(fc_mf2, fc_gjr)[0, 1]
corr_mf2_ewma = np.corrcoef(fc_mf2, fc_ewma)[0, 1]
print(f"\n  Corr(MF2, GJR) = {corr_mf2_gjr:.4f}")
print(f"  Corr(MF2, EWMA) = {corr_mf2_ewma:.4f}")

# ═══════════════════════════════════════════════════════════════════════════════
# Save results
# ═══════════════════════════════════════════════════════════════════════════════
results = {
    "experiment_id": "K623",
    "title": "MF2-GARCH CORRECTED (fixing K621 Codex-identified bugs)",
    "description": (
        "Corrected MF2-GARCH (Conrad & Engle, JAE 2025) implementation fixing 3 HIGH bugs from K621: "
        "(1) short-run block now unit-mean dimensionless GJR driven by r²/τ, not raw r² with free omega; "
        "(2) V_t now uses complete model variance g_t×τ_t in denominator; "
        "(3) BIC uses uniform burn-in max(m_candidates) for valid comparison across m values."
    ),
    "reference": "Conrad, C. & Engle, R.F. (2025). JAE, 40(4), 438-454.",
    "data_source": "yfinance",
    "asset": ASSET,
    "sample_period": f"{START} to {END}",
    "total_obs": T,
    "oos_period": f"{OOS_START} to {OOS_END}",
    "oos_obs": n_oos,
    "window": WINDOW,
    "refit_every": REFIT_EVERY,
    "proxy": "squared returns (r²)",
    "bugs_fixed": {
        "bug1_short_run": "g_t now unit-mean with intercept (1-α-γ/2-β), input r²/τ not raw r²",
        "bug2_Vm_input": "V_t = (r-μ)²/(g_t×τ_t) using full model variance",
        "bug3_bic": f"Uniform burn-in = {MAX_M} for all m candidates",
    },
    "model_spec": {
        "n_params": 6,
        "params": "alpha, gamma, beta, lam1, lam2, lam3 (no omega — unit-mean constraint)",
        "mu": "sample mean of estimation window",
    },
    "m_selection": {
        "candidates": M_CANDIDATES,
        "uniform_burn_in": MAX_M,
        "optimal_m": optimal_m,
        "details": {str(m): {
            "bic_per_obs": v["bic_per_obs"],
            "negll_per_obs": v["negll_per_obs"],
            "converged": v["converged"],
        } for m, v in m_selection_results.items()},
    },
    "oos_results": {
        "qlike": {
            "gjr": qlike_gjr,
            "mf2": qlike_mf2,
            "ewma": qlike_ewma,
            "best": min(
                [("GJR", qlike_gjr), ("MF2", qlike_mf2), ("EWMA", qlike_ewma)],
                key=lambda x: x[1]
            )[0],
        },
        "mse": {
            "gjr": mse_gjr,
            "mf2": mse_mf2,
            "ewma": mse_ewma,
            "best": min(
                [("GJR", mse_gjr), ("MF2", mse_mf2), ("EWMA", mse_ewma)],
                key=lambda x: x[1]
            )[0],
        },
    },
    "dm_tests_qlike": {
        "mf2_vs_gjr": {"dm_stat": dm_mf2_gjr, "p_value": p_mf2_gjr},
        "mf2_vs_ewma": {"dm_stat": dm_mf2_ewma, "p_value": p_mf2_ewma},
        "gjr_vs_ewma": {"dm_stat": dm_gjr_ewma, "p_value": p_gjr_ewma},
    },
    "dm_tests_mse": {
        "mf2_vs_gjr": {"dm_stat": dm_mf2_gjr_mse, "p_value": p_mf2_gjr_mse},
        "mf2_vs_ewma": {"dm_stat": dm_mf2_ewma_mse, "p_value": p_mf2_ewma_mse},
        "gjr_vs_ewma": {"dm_stat": dm_gjr_ewma_mse, "p_value": p_gjr_ewma_mse},
    },
    "convergence": {
        "rate": conv_rate,
        "total_refits": refit_count,
        "converged_refits": sum(mf2_convergence),
    },
    "diagnostics": {
        "g_mean_across_refits": float(np.mean(g_mean_log)) if g_mean_log else None,
        "g_std_across_refits": float(np.std(g_mean_log)) if g_mean_log else None,
        "tau_mean_across_refits": float(np.mean(tau_mean_log)) if tau_mean_log else None,
        "tau_std_across_refits": float(np.std(tau_mean_log)) if tau_mean_log else None,
        "forecast_corr_mf2_gjr": float(corr_mf2_gjr),
        "forecast_corr_mf2_ewma": float(corr_mf2_ewma),
    },
    "forecast_stats": {
        "gjr": {"mean": float(np.mean(fc_gjr)), "std": float(np.std(fc_gjr)),
                "min": float(np.min(fc_gjr)), "max": float(np.max(fc_gjr))},
        "mf2": {"mean": float(np.mean(fc_mf2)), "std": float(np.std(fc_mf2)),
                "min": float(np.min(fc_mf2)), "max": float(np.max(fc_mf2))},
        "ewma": {"mean": float(np.mean(fc_ewma)), "std": float(np.std(fc_ewma)),
                 "min": float(np.min(fc_ewma)), "max": float(np.max(fc_ewma))},
        "proxy": {"mean": float(np.mean(proxy_oos)), "std": float(np.std(proxy_oos))},
    },
    "mf2_params_log": mf2_params_log[:5],  # first 5 refits for inspection
    "gjr_params_log": gjr_params_log[:5],
    "runtime_seconds": total_time,
    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}

out_path = "experiments/k623_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SUMMARY: K623 MF2-GARCH CORRECTED")
print("=" * 70)
print(f"Bugs fixed: 3 HIGH from K621 Codex review")
print(f"  1. Short-run g_t: unit-mean, r²/τ input (not raw r² + free ω)")
print(f"  2. V_t denominator: g_t×τ_t (not just σ²_short)")
print(f"  3. BIC: uniform burn-in {MAX_M} for all m values")
print(f"\nOptimal m: {optimal_m}")
print(f"MF2 convergence: {conv_rate:.0%} ({sum(mf2_convergence)}/{len(mf2_convergence)})")
if g_mean_log:
    print(f"Mean g (unit-mean check, should ≈ 1.0): {np.mean(g_mean_log):.4f}")
print(f"\nQLIKE:  GJR={qlike_gjr:.6f}  MF2={qlike_mf2:.6f}  EWMA={qlike_ewma:.6f}")
print(f"MSE:    GJR={mse_gjr:.4f}  MF2={mse_mf2:.4f}  EWMA={mse_ewma:.4f}")
print(f"\nDM(QLIKE) MF2 vs GJR: stat={dm_mf2_gjr:+.4f}, p={p_mf2_gjr:.4f}")
print(f"DM(QLIKE) MF2 vs EWMA: stat={dm_mf2_ewma:+.4f}, p={p_mf2_ewma:.4f}")

winner_qlike = min([("GJR", qlike_gjr), ("MF2", qlike_mf2), ("EWMA", qlike_ewma)], key=lambda x: x[1])
print(f"\nBest model (QLIKE): {winner_qlike[0]} ({winner_qlike[1]:.6f})")
