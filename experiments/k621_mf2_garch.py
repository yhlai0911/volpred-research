"""
K621: MF2-GARCH (Conrad & Engle, JAE 2025) — 1-step ahead daily vol forecasting
Reference: Conrad, C. & Engle, R.F. (2025). Modelling Volatility Cycles: The MF2-GARCH Model.
           Journal of Applied Econometrics, 40(4), 438-454.

The MF2-GARCH decomposes conditional variance multiplicatively:
    h_t = σ²_t × τ_t
  - Short-term: σ²_t follows GJR-GARCH(1,1) on standardized returns
  - Long-term: τ_t = λ₁ + λ₂ × V^m_{t-1} + λ₃ × τ_{t-1}
    where V^m_{t-1} = (1/m) Σ r²_{t-j}/σ²_{t-j} is rolling avg of standardized forecast errors
  - 7 parameters: ω(GJR), α, γ, β, λ₁, λ₂, λ₃ + m chosen by BIC

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
# MF2-GARCH implementation
# ═══════════════════════════════════════════════════════════════════════════════

def _gjr_filter(ret, omega, alpha, gamma, beta):
    """
    GJR-GARCH(1,1) conditional variance filter (no mean).
    σ²_t = ω + α ε²_{t-1} + γ ε²_{t-1} I(ε<0) + β σ²_{t-1}
    Returns array of σ²_t same length as ret.
    """
    n = len(ret)
    sigma2 = np.zeros(n)
    sigma2[0] = omega / (1 - alpha - gamma / 2 - beta + 1e-8)  # unconditional
    if sigma2[0] <= 0 or np.isnan(sigma2[0]):
        sigma2[0] = np.var(ret)
    for t in range(1, n):
        e2 = ret[t - 1] ** 2
        ind = 1.0 if ret[t - 1] < 0 else 0.0
        sigma2[t] = omega + alpha * e2 + gamma * e2 * ind + beta * sigma2[t - 1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return sigma2


def _tau_filter(V_m, lam1, lam2, lam3, n):
    """
    Long-term component: τ_t = λ₁ + λ₂ × V^m_{t-1} + λ₃ × τ_{t-1}
    V_m[t] = (1/m) Σ_{j=1}^{m} (ε²_{t-j}/σ²_{t-j})
    V_m should already be computed; here we just need to run the recursion.
    n = total length of the series.
    V_m has length n (with NaN for initial m-1 positions).
    """
    tau = np.ones(n)
    tau[0] = lam1 / (1 - lam3 + 1e-8) if lam3 < 1 else 1.0
    if tau[0] <= 0 or np.isnan(tau[0]):
        tau[0] = 1.0
    for t in range(1, n):
        vm_prev = V_m[t - 1] if not np.isnan(V_m[t - 1]) else 1.0
        tau[t] = lam1 + lam2 * vm_prev + lam3 * tau[t - 1]
        if tau[t] < 0.01:
            tau[t] = 0.01
        if tau[t] > 100:
            tau[t] = 100.0
    return tau


def _compute_V_m(ret, sigma2_short, m):
    """
    Compute rolling average of standardized squared residuals:
    V^m_t = (1/m) Σ_{j=1}^{m} (ε²_{t+1-j}/σ²_{t+1-j})
    where ε_t = r_t (zero mean).
    """
    n = len(ret)
    standardized = ret ** 2 / np.maximum(sigma2_short, 1e-10)
    V_m = np.full(n, np.nan)
    for t in range(m - 1, n):
        V_m[t] = np.mean(standardized[t - m + 1:t + 1])
    return V_m


def _mf2_negloglik(params, ret, m):
    """
    Negative log-likelihood for MF2-GARCH.
    params = [omega, alpha, gamma, beta, lam1, lam2, lam3]
    """
    omega, alpha, gamma_p, beta, lam1, lam2, lam3 = params
    n = len(ret)

    # Short-term GJR filter
    sigma2_short = _gjr_filter(ret, omega, alpha, gamma_p, beta)

    # Compute V^m
    V_m = _compute_V_m(ret, sigma2_short, m)

    # Long-term tau filter
    tau = _tau_filter(V_m, lam1, lam2, lam3, n)

    # Total variance
    h = sigma2_short * tau

    # Log-likelihood (Gaussian QML), skip first max(m, 1) obs for burn-in
    burn = max(m, 1)
    h_valid = h[burn:]
    r_valid = ret[burn:]

    # Guard against numerical issues
    h_valid = np.maximum(h_valid, 1e-10)

    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(h_valid) + r_valid ** 2 / h_valid)

    if np.isnan(ll) or np.isinf(ll):
        return 1e10
    return -ll


def fit_mf2_garch(ret, m, max_tries=5):
    """
    Fit MF2-GARCH with given m by QML.
    Returns: (params, negll, converged, h_insample, h_forecast)
    """
    n = len(ret)

    # Get initial GJR estimates for starting values
    try:
        am = arch_model(pd.Series(ret), vol="GARCH", p=1, o=1, q=1, mean="Zero", dist="normal")
        res0 = am.fit(disp="off", show_warning=False)
        omega0 = res0.params.get("omega", 0.05)
        alpha0 = res0.params.get("alpha[1]", 0.05)
        gamma0 = res0.params.get("gamma[1]", 0.05)
        beta0 = res0.params.get("beta[1]", 0.90)
    except Exception:
        omega0, alpha0, gamma0, beta0 = 0.05, 0.05, 0.05, 0.90

    # Bounds: omega>0, alpha>=0, gamma>=0, beta>=0; lam1>0, lam2>=0, lam3>=0
    bounds = [
        (1e-6, 10.0),    # omega
        (1e-6, 0.5),     # alpha
        (0.0, 0.5),      # gamma
        (0.01, 0.999),   # beta
        (1e-6, 5.0),     # lam1
        (0.0, 2.0),      # lam2
        (0.0, 0.999),    # lam3
    ]

    # Multiple starting points
    starts = [
        [omega0, alpha0, gamma0, beta0, 0.05, 0.1, 0.85],
        [omega0 * 0.5, alpha0 * 0.8, gamma0 * 1.2, beta0, 0.1, 0.2, 0.7],
        [0.02, 0.03, 0.06, 0.92, 0.02, 0.05, 0.90],
        [0.10, 0.08, 0.10, 0.85, 0.08, 0.15, 0.75],
        [omega0 * 1.5, alpha0 * 1.2, gamma0 * 0.8, beta0 * 0.95, 0.03, 0.08, 0.88],
    ]

    best_negll = 1e10
    best_params = None
    best_converged = False

    # Stationarity constraint for tau: lam2 + lam3 < 1
    constraints = [
        {"type": "ineq", "fun": lambda p: 0.999 - (p[5] + p[6])},  # lam2 + lam3 < 1
        {"type": "ineq", "fun": lambda p: 0.999 - (p[1] + p[2] / 2 + p[3])},  # GARCH stationarity
    ]

    for i, x0 in enumerate(starts[:max_tries]):
        try:
            result = minimize(
                _mf2_negloglik,
                x0,
                args=(ret, m),
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-10},
            )
            if result.fun < best_negll:
                best_negll = result.fun
                best_params = result.x
                best_converged = result.success
        except Exception:
            continue

    if best_params is None:
        # Fallback: return GJR only (tau=1)
        sigma2_short = _gjr_filter(ret, omega0, alpha0, gamma0, beta0)
        h_next = omega0 + alpha0 * ret[-1] ** 2 + gamma0 * ret[-1] ** 2 * (1.0 if ret[-1] < 0 else 0.0) + beta0 * sigma2_short[-1]
        return [omega0, alpha0, gamma0, beta0, 0.0, 0.0, 1.0], 1e10, False, sigma2_short, h_next

    # Reconstruct in-sample fit and forecast
    omega, alpha, gamma_p, beta, lam1, lam2, lam3 = best_params
    sigma2_short = _gjr_filter(ret, omega, alpha, gamma_p, beta)
    V_m = _compute_V_m(ret, sigma2_short, m)
    tau = _tau_filter(V_m, lam1, lam2, lam3, n)
    h_insample = sigma2_short * tau

    # 1-step-ahead forecast
    e2_last = ret[-1] ** 2
    ind_last = 1.0 if ret[-1] < 0 else 0.0
    sigma2_next = omega + alpha * e2_last + gamma_p * e2_last * ind_last + beta * sigma2_short[-1]
    tau_next = lam1 + lam2 * (V_m[-1] if not np.isnan(V_m[-1]) else 1.0) + lam3 * tau[-1]
    tau_next = max(tau_next, 0.01)
    h_next = sigma2_next * tau_next

    return list(best_params), best_negll, best_converged, h_insample, h_next


def select_m_by_bic(ret, m_candidates):
    """Select optimal m by BIC = -2*LL + k*ln(n) where k=7."""
    n = len(ret)
    k = 7
    best_bic = np.inf
    best_m = m_candidates[0]
    results = {}

    for m in m_candidates:
        params, negll, converged, _, _ = fit_mf2_garch(ret, m, max_tries=3)
        bic = 2 * negll + k * np.log(n)
        results[m] = {"bic": bic, "negll": negll, "converged": converged}
        if bic < best_bic:
            best_bic = bic
            best_m = m

    return best_m, results


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluation metrics
# ═══════════════════════════════════════════════════════════════════════════════

def qlike(proxy_arr, forecast_arr):
    """QLIKE loss: mean(proxy/forecast - log(proxy/forecast) - 1)"""
    ratio = proxy_arr / np.maximum(forecast_arr, 1e-10)
    return np.mean(ratio - np.log(np.maximum(ratio, 1e-10)) - 1)


def mse(proxy_arr, forecast_arr):
    """MSE loss: mean((proxy - forecast)^2)"""
    return np.mean((proxy_arr - forecast_arr) ** 2)


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
    return dm_stat, p_val


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

# Use pre-OOS data to select m
pre_oos_ret = returns_arr[:oos_start_idx]
print(f"Pre-OOS sample: {len(pre_oos_ret)} obs, selecting m from {M_CANDIDATES}...")

t0_m = time.time()
optimal_m, m_selection_results = select_m_by_bic(pre_oos_ret[-WINDOW:], M_CANDIDATES)
t_m = time.time() - t0_m
print(f"Optimal m = {optimal_m} (took {t_m:.1f}s)")
for m_val, mres in m_selection_results.items():
    print(f"  m={m_val:>3d}: BIC={mres['bic']:.2f}, negLL={mres['negll']:.2f}, converged={mres['converged']}")


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
print(f"OOS period: {dates[oos_start_idx].strftime('%Y-%m-%d')} to {dates[oos_end_idx-1].strftime('%Y-%m-%d')}")
print(f"OOS observations: {n_oos}")
print(f"Re-estimating every {REFIT_EVERY} days")

# Storage
fc_gjr = np.zeros(n_oos)
fc_mf2 = np.zeros(n_oos)
fc_ewma = np.zeros(n_oos)
proxy_oos = np.zeros(n_oos)

# Track parameters and convergence
gjr_params_log = []
mf2_params_log = []
mf2_convergence = []

t_start = time.time()
last_fit_gjr = None
last_fit_mf2 = None
last_fit_ewma = None

for k, t_idx in enumerate(oos_indices):
    need_refit = (k % REFIT_EVERY == 0) or (last_fit_gjr is None)

    # Window of returns for estimation
    w_start = t_idx - WINDOW
    if w_start < 0:
        w_start = 0
    ret_window = returns_arr[w_start:t_idx]

    if need_refit:
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
        except Exception as e:
            # Use last fit or fallback
            if last_fit_gjr is not None:
                p = last_fit_gjr
                sigma2_gjr = _gjr_filter(ret_window, p["omega"], p["alpha"], p["gamma"], p["beta"])
                e2 = ret_window[-1] ** 2
                ind = 1.0 if ret_window[-1] < 0 else 0.0
                h_gjr = p["omega"] + p["alpha"] * e2 + p["gamma"] * e2 * ind + p["beta"] * sigma2_gjr[-1]
            else:
                h_gjr = np.var(ret_window)

        # ── MF2-GARCH ──
        try:
            mf2_params, mf2_negll, mf2_conv, mf2_h_is, h_mf2 = fit_mf2_garch(ret_window, optimal_m, max_tries=5)
            last_fit_mf2 = {
                "params": mf2_params,
                "m": optimal_m,
                "converged": mf2_conv,
            }
            mf2_params_log.append({
                "omega": mf2_params[0], "alpha": mf2_params[1], "gamma": mf2_params[2],
                "beta": mf2_params[3], "lam1": mf2_params[4], "lam2": mf2_params[5],
                "lam3": mf2_params[6], "converged": mf2_conv,
            })
            mf2_convergence.append(mf2_conv)
        except Exception as e:
            if last_fit_mf2 is not None:
                p = last_fit_mf2["params"]
                sigma2_s = _gjr_filter(ret_window, p[0], p[1], p[2], p[3])
                V_m = _compute_V_m(ret_window, sigma2_s, optimal_m)
                tau = _tau_filter(V_m, p[4], p[5], p[6], len(ret_window))
                e2 = ret_window[-1] ** 2
                ind = 1.0 if ret_window[-1] < 0 else 0.0
                s2_next = p[0] + p[1] * e2 + p[2] * e2 * ind + p[3] * sigma2_s[-1]
                t_next = p[4] + p[5] * (V_m[-1] if not np.isnan(V_m[-1]) else 1.0) + p[6] * tau[-1]
                h_mf2 = s2_next * max(t_next, 0.01)
            else:
                h_mf2 = np.var(ret_window)
            mf2_convergence.append(False)

        # ── EWMA ──
        _, h_ewma = ewma_forecast(ret_window)
        last_fit_ewma = h_ewma

    else:
        # Update without re-estimation (use last params for 1-step forecast)
        # GJR update
        if last_fit_gjr is not None:
            p = last_fit_gjr
            # We need the last sigma2 — recompute from last few obs
            sigma2_gjr = _gjr_filter(ret_window, p["omega"], p["alpha"], p["gamma"], p["beta"])
            e2 = ret_window[-1] ** 2
            ind = 1.0 if ret_window[-1] < 0 else 0.0
            h_gjr = p["omega"] + p["alpha"] * e2 + p["gamma"] * e2 * ind + p["beta"] * sigma2_gjr[-1]
        else:
            h_gjr = np.var(ret_window)

        # MF2 update
        if last_fit_mf2 is not None:
            p = last_fit_mf2["params"]
            sigma2_s = _gjr_filter(ret_window, p[0], p[1], p[2], p[3])
            V_m = _compute_V_m(ret_window, sigma2_s, optimal_m)
            tau = _tau_filter(V_m, p[4], p[5], p[6], len(ret_window))
            e2 = ret_window[-1] ** 2
            ind = 1.0 if ret_window[-1] < 0 else 0.0
            s2_next = p[0] + p[1] * e2 + p[2] * e2 * ind + p[3] * sigma2_s[-1]
            t_next = p[4] + p[5] * (V_m[-1] if not np.isnan(V_m[-1]) else 1.0) + p[6] * tau[-1]
            h_mf2 = s2_next * max(t_next, 0.01)
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
              f"h_gjr={fc_gjr[k]:.4f}  h_mf2={fc_mf2[k]:.4f}  h_ewma={fc_ewma[k]:.4f}")


# ═══════════════════════════════════════════════════════════════════════════════
# Compute metrics
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("Phase 3: Results")
print("=" * 70)

# Filter out any zero-proxy observations (weekends/holidays shouldn't exist but guard)
valid = proxy_oos > 0
proxy_v = proxy_oos[valid]
fc_gjr_v = fc_gjr[valid]
fc_mf2_v = fc_mf2[valid]
fc_ewma_v = fc_ewma[valid]

# QLIKE
qlike_gjr = qlike(proxy_v, fc_gjr_v)
qlike_mf2 = qlike(proxy_v, fc_mf2_v)
qlike_ewma = qlike(proxy_v, fc_ewma_v)

# MSE
mse_gjr = mse(proxy_v, fc_gjr_v)
mse_mf2 = mse(proxy_v, fc_mf2_v)
mse_ewma = mse(proxy_v, fc_ewma_v)

# DM tests (QLIKE loss, MF2 vs GJR baseline)
loss_gjr_qlike = proxy_v / np.maximum(fc_gjr_v, 1e-10) - np.log(np.maximum(proxy_v / np.maximum(fc_gjr_v, 1e-10), 1e-10)) - 1
loss_mf2_qlike = proxy_v / np.maximum(fc_mf2_v, 1e-10) - np.log(np.maximum(proxy_v / np.maximum(fc_mf2_v, 1e-10), 1e-10)) - 1
loss_ewma_qlike = proxy_v / np.maximum(fc_ewma_v, 1e-10) - np.log(np.maximum(proxy_v / np.maximum(fc_ewma_v, 1e-10), 1e-10)) - 1

dm_mf2_vs_gjr_stat, dm_mf2_vs_gjr_pval = dm_test(loss_mf2_qlike, loss_gjr_qlike)
dm_ewma_vs_gjr_stat, dm_ewma_vs_gjr_pval = dm_test(loss_ewma_qlike, loss_gjr_qlike)
dm_mf2_vs_ewma_stat, dm_mf2_vs_ewma_pval = dm_test(loss_mf2_qlike, loss_ewma_qlike)

# MSE-based DM
loss_gjr_mse = (proxy_v - fc_gjr_v) ** 2
loss_mf2_mse = (proxy_v - fc_mf2_v) ** 2
loss_ewma_mse = (proxy_v - fc_ewma_v) ** 2

dm_mf2_vs_gjr_mse_stat, dm_mf2_vs_gjr_mse_pval = dm_test(loss_mf2_mse, loss_gjr_mse)

# Parameter summaries
if mf2_params_log:
    last_mf2 = mf2_params_log[-1]
    convergence_rate = sum(mf2_convergence) / len(mf2_convergence) * 100
else:
    last_mf2 = {}
    convergence_rate = 0

if gjr_params_log:
    last_gjr = gjr_params_log[-1]
else:
    last_gjr = {}

# ─── Print results ──────────────────────────────────────────────────────────
print(f"\nOOS period: {dates[oos_start_idx].strftime('%Y-%m-%d')} to {dates[oos_end_idx-1].strftime('%Y-%m-%d')}")
print(f"OOS observations: {sum(valid)} (valid)")
print(f"Optimal m: {optimal_m}")
print(f"MF2-GARCH convergence rate: {convergence_rate:.1f}%")
print(f"Total estimation time: {time.time() - t_start:.1f}s")

print(f"\n{'Model':<20} {'QLIKE':>10} {'MSE':>12}")
print("-" * 44)
print(f"{'GJR-GARCH(1,1)':<20} {qlike_gjr:>10.6f} {mse_gjr:>12.6f}")
print(f"{'MF2-GARCH':<20} {qlike_mf2:>10.6f} {mse_mf2:>12.6f}")
print(f"{'EWMA(0.94)':<20} {qlike_ewma:>10.6f} {mse_ewma:>12.6f}")

print(f"\nDiebold-Mariano Tests (QLIKE loss):")
print(f"  MF2 vs GJR:  DM = {dm_mf2_vs_gjr_stat:>7.4f}, p = {dm_mf2_vs_gjr_pval:.4f}  {'*' if dm_mf2_vs_gjr_pval < 0.05 else ''}")
print(f"  EWMA vs GJR: DM = {dm_ewma_vs_gjr_stat:>7.4f}, p = {dm_ewma_vs_gjr_pval:.4f}  {'*' if dm_ewma_vs_gjr_pval < 0.05 else ''}")
print(f"  MF2 vs EWMA: DM = {dm_mf2_vs_ewma_stat:>7.4f}, p = {dm_mf2_vs_ewma_pval:.4f}  {'*' if dm_mf2_vs_ewma_pval < 0.05 else ''}")

print(f"\nDiebold-Mariano Tests (MSE loss):")
print(f"  MF2 vs GJR:  DM = {dm_mf2_vs_gjr_mse_stat:>7.4f}, p = {dm_mf2_vs_gjr_mse_pval:.4f}  {'*' if dm_mf2_vs_gjr_mse_pval < 0.05 else ''}")

# QLIKE improvement
qlike_improvement = (qlike_gjr - qlike_mf2) / qlike_gjr * 100
mse_improvement = (mse_gjr - mse_mf2) / mse_gjr * 100
print(f"\nMF2 vs GJR improvement: QLIKE {qlike_improvement:+.2f}%, MSE {mse_improvement:+.2f}%")

# Last parameter estimates
print(f"\nLast MF2-GARCH parameter estimates (m={optimal_m}):")
if last_mf2:
    print(f"  ω={last_mf2.get('omega', 'N/A'):.6f}, α={last_mf2.get('alpha', 'N/A'):.6f}, "
          f"γ={last_mf2.get('gamma', 'N/A'):.6f}, β={last_mf2.get('beta', 'N/A'):.6f}")
    print(f"  λ₁={last_mf2.get('lam1', 'N/A'):.6f}, λ₂={last_mf2.get('lam2', 'N/A'):.6f}, "
          f"λ₃={last_mf2.get('lam3', 'N/A'):.6f}")
    persistence = last_mf2.get('alpha', 0) + last_mf2.get('gamma', 0) / 2 + last_mf2.get('beta', 0)
    tau_persistence = last_mf2.get('lam2', 0) + last_mf2.get('lam3', 0)
    print(f"  Short-term persistence: {persistence:.4f}")
    print(f"  Long-term persistence (λ₂+λ₃): {tau_persistence:.4f}")

print(f"\nLast GJR-GARCH parameter estimates:")
if last_gjr:
    print(f"  ω={last_gjr.get('omega', 'N/A'):.6f}, α={last_gjr.get('alpha', 'N/A'):.6f}, "
          f"γ={last_gjr.get('gamma', 'N/A'):.6f}, β={last_gjr.get('beta', 'N/A'):.6f}")

# ═══════════════════════════════════════════════════════════════════════════════
# Save results
# ═══════════════════════════════════════════════════════════════════════════════
results = {
    "experiment_id": "K621",
    "title": "MF2-GARCH (Conrad & Engle, JAE 2025) — 1-step daily vol forecasting",
    "reference": "Conrad, C. & Engle, R.F. (2025). Modelling Volatility Cycles: The MF2-GARCH Model. Journal of Applied Econometrics, 40(4), 438-454.",
    "asset": ASSET,
    "data_source": "yfinance",
    "data_period": f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
    "total_observations": int(T),
    "oos_period": f"{dates[oos_start_idx].strftime('%Y-%m-%d')} to {dates[oos_end_idx-1].strftime('%Y-%m-%d')}",
    "oos_observations": int(sum(valid)),
    "window_size": WINDOW,
    "refit_interval": REFIT_EVERY,
    "proxy": "squared returns (r²_t)",
    "optimal_m": int(optimal_m),
    "m_selection": {str(k): {
        "bic": round(v["bic"], 4),
        "negll": round(v["negll"], 4),
        "converged": v["converged"]
    } for k, v in m_selection_results.items()},
    "metrics": {
        "GJR_GARCH": {
            "QLIKE": round(float(qlike_gjr), 6),
            "MSE": round(float(mse_gjr), 6),
        },
        "MF2_GARCH": {
            "QLIKE": round(float(qlike_mf2), 6),
            "MSE": round(float(mse_mf2), 6),
        },
        "EWMA_094": {
            "QLIKE": round(float(qlike_ewma), 6),
            "MSE": round(float(mse_ewma), 6),
        },
    },
    "dm_tests": {
        "MF2_vs_GJR_QLIKE": {
            "DM_stat": round(float(dm_mf2_vs_gjr_stat), 4),
            "p_value": round(float(dm_mf2_vs_gjr_pval), 4),
            "significant_5pct": bool(dm_mf2_vs_gjr_pval < 0.05),
        },
        "EWMA_vs_GJR_QLIKE": {
            "DM_stat": round(float(dm_ewma_vs_gjr_stat), 4),
            "p_value": round(float(dm_ewma_vs_gjr_pval), 4),
            "significant_5pct": bool(dm_ewma_vs_gjr_pval < 0.05),
        },
        "MF2_vs_EWMA_QLIKE": {
            "DM_stat": round(float(dm_mf2_vs_ewma_stat), 4),
            "p_value": round(float(dm_mf2_vs_ewma_pval), 4),
            "significant_5pct": bool(dm_mf2_vs_ewma_pval < 0.05),
        },
        "MF2_vs_GJR_MSE": {
            "DM_stat": round(float(dm_mf2_vs_gjr_mse_stat), 4),
            "p_value": round(float(dm_mf2_vs_gjr_mse_pval), 4),
            "significant_5pct": bool(dm_mf2_vs_gjr_mse_pval < 0.05),
        },
    },
    "improvements": {
        "MF2_vs_GJR_QLIKE_pct": round(float(qlike_improvement), 2),
        "MF2_vs_GJR_MSE_pct": round(float(mse_improvement), 2),
    },
    "parameters": {
        "MF2_GARCH_last": {k: round(v, 6) if isinstance(v, float) else v for k, v in last_mf2.items()} if last_mf2 else {},
        "GJR_GARCH_last": {k: round(v, 6) if isinstance(v, float) else v for k, v in last_gjr.items()} if last_gjr else {},
    },
    "convergence": {
        "MF2_convergence_rate_pct": round(float(convergence_rate), 1),
        "n_refits": len(mf2_convergence),
    },
    "runtime_seconds": round(time.time() - t_start, 1),
    "timestamp": datetime.now().isoformat(),
}

results_path = "experiments/k621_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nResults saved to {results_path}")
print("\n" + "=" * 70)
print("K621 COMPLETE")
print("=" * 70)
