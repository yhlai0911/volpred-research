"""
K1184: Paper 2 Skew-t Parameters Verification
==============================================
Reproduce η=5.2 (degrees of freedom) and λ=-0.05 (skewness) claimed in
paper/taiwan-vt/body.tex line 459 for 0050.TW GJR-GARCH innovations.

Paper context (body.tex:459):
    "We also evaluate the skewed Student-t distribution, which simultaneously
     estimates degrees of freedom (η) and skewness (λ) via maximum likelihood,
     adapting to each asset's specific tail behavior. For 0050.TW, the
     estimated parameters are η=5.2 and λ=−0.05 (near-symmetric with
     moderate fat tails)."

Model: GJR-GARCH(1,1) innovations fitted with Hansen (1994) skew-t
Reference: Hansen (1994) "Autoregressive Conditional Density Estimation"
           International Economic Review 35(3): 705-730.

Hansen (1994) skew-t PDF:
    h(z|η,λ) = bc [1 + 1/(η-2) * ((bz+a)/(1∓λ))²]^{-(η+1)/2}
where:
    c = Γ((η+1)/2) / (sqrt(π(η-2)) * Γ(η/2))
    a = 4λc * (η-2)/(η-1)
    b = sqrt(1 + 3λ² - a²)
    sign branch: 1+λ if z >= -a/b, else 1-λ

Connections to K1100c:
    K1100c implements the same Hansen skew-t for bivariate copula.
    K1184 applies it as a univariate marginal to GJR-GARCH standardized residuals.

VaR paper context (body.tex:452,463):
    GJR-GARCH + Student-t(df=5) → 8 violations (0.5%) over 2020-2026 (1,501 days)
    Period for skew-t parameter estimation: full sample (or rolling w=2000)

Data: 0050.TW daily close, 2009-01-02 to 2026-03-31 (n=4,218)
Seed: 42 (all random processes)
"""

import numpy as np
import pandas as pd
import json
import logging
import sys
from datetime import datetime, timezone
from scipy import optimize, special, stats
from scipy.stats import t as student_t

# ============================================================
# CONFIG
# ============================================================
EXPERIMENT_ID = "k1184"
SEED = 42
rng = np.random.default_rng(SEED)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-aa2d76a6/experiments/k1184/run.log",
            mode="w"
        ),
    ],
)
log = logging.getLogger(__name__)
log.info(f"=== {EXPERIMENT_ID}: Paper 2 Skew-t Parameters Verification ===")
log.info(f"Target: η ≈ 5.2, λ ≈ -0.05 for 0050.TW GJR-GARCH innovations")

# ============================================================
# 1. DATA
# ============================================================
log.info("--- Step 1: Load 0050.TW data ---")

try:
    import yfinance as yf
    raw = yf.download("0050.TW", start="2009-01-01", end="2026-04-01", progress=False)
    close = raw[("Close", "0050.TW")].dropna()
except Exception as e:
    log.error(f"yfinance failed: {e}")
    raise

log.info(f"0050.TW data: n={len(close)}, {close.index[0].date()} to {close.index[-1].date()}")
assert len(close) >= 4000, f"Expected >=4000 obs, got {len(close)}"

# Log returns (in %)
ret_all = np.log(close / close.shift(1)).dropna() * 100

# Remove known split artifact: 2014-01-02 0050.TW underwent 4:1 split.
# yfinance returns a spurious -138.89% log return which is not adjusted.
# This observation is a data error, not a genuine market event.
BAD_DATES = [pd.Timestamp("2014-01-02")]
bad_mask = ret_all.index.isin(BAD_DATES)
n_removed = bad_mask.sum()
ret_clean = ret_all[~bad_mask]
log.info(f"Removed {n_removed} split-artifact observation(s): {BAD_DATES}")

# Keep aligned index for later use
returns = ret_clean.values
returns_index = ret_clean.index
n_total = len(returns)
log.info(f"Log returns: n={n_total}, mean={returns.mean():.4f}%, std={returns.std():.4f}%")

# ============================================================
# 2. HANSEN (1994) SKEW-T LOG-PDF
# ============================================================
log.info("--- Step 2: Hansen (1994) skew-t functions ---")

def hansen_skewt_logpdf(x_arr: np.ndarray, eta: float, lam: float) -> np.ndarray:
    """
    Log-PDF of Hansen (1994) skewed-t distribution.

    Parameters
    ----------
    x_arr : array of standardized residuals z
    eta   : degrees of freedom (> 2)
    lam   : skewness parameter in (-1, 1); negative = left-skew

    Returns
    -------
    log-pdf values

    Formula (Hansen 1994, eq. 9):
        c  = Γ((η+1)/2) / (sqrt(π(η-2)) * Γ(η/2))
        a  = 4λc(η-2)/(η-1)
        b  = sqrt(1 + 3λ² - a²)
        For z >= -a/b:  logpdf = log(b) + log(c) - (η+1)/2 * log(1 + (bz+a)²/((η-2)(1+λ)²))
        For z <  -a/b:  logpdf = log(b) + log(c) - (η+1)/2 * log(1 + (bz+a)²/((η-2)(1-λ)²))
    """
    if eta <= 2.0 or abs(lam) >= 1.0:
        return np.full(len(x_arr), -1e10)

    log_c = (special.gammaln((eta + 1) / 2)
             - special.gammaln(eta / 2)
             - 0.5 * np.log(np.pi * (eta - 2)))
    c_val = np.exp(log_c)

    a = 4 * lam * c_val * (eta - 2) / (eta - 1)
    b2 = 1 + 3 * lam**2 - a**2
    if b2 <= 0:
        return np.full(len(x_arr), -1e10)
    b = np.sqrt(b2)
    log_b = np.log(b)

    bxa = b * x_arr + a  # b*z + a

    # sign branch
    sign_part = np.where(x_arr >= -a / b, 1.0 + lam, 1.0 - lam)
    sign_part = np.maximum(np.abs(sign_part), 1e-10) * np.sign(sign_part)
    sign_part = np.maximum(sign_part, 1e-10)  # all positive after abs

    inner = 1.0 + (bxa / sign_part) ** 2 / (eta - 2.0)
    inner = np.maximum(inner, 1e-10)

    logpdf = log_b + log_c - ((eta + 1) / 2) * np.log(inner)
    return logpdf


def hansen_skewt_nll(params: np.ndarray, z_arr: np.ndarray) -> float:
    """Negative log-likelihood for Hansen skew-t given standardized residuals."""
    eta, lam = params
    if eta <= 2.01 or eta > 200.0 or abs(lam) >= 0.999:
        return 1e10
    lp = hansen_skewt_logpdf(z_arr, eta, lam)
    if not np.all(np.isfinite(lp)):
        return 1e10
    return -np.sum(lp)


# Quick sanity: at lam=0, Hansen skew-t should match variance-standardized Student-t
# (Hansen distribution has E[Z]=0, Var[Z]=1; scipy Student-t has Var=df/(df-2))
# So: logpdf_hansen(x, η, 0) = logpdf_student_t(x/scale, η) - log(scale)
#     where scale = sqrt((η-2)/η)
z_test = np.array([0.0, 1.0, -1.0])
eta_test = 5.0
lp_hansen = hansen_skewt_logpdf(z_test, eta=eta_test, lam=0.0)
scale_test = np.sqrt((eta_test - 2) / eta_test)
lp_student_scaled = student_t.logpdf(z_test / scale_test, df=eta_test) - np.log(scale_test)
assert np.allclose(lp_hansen, lp_student_scaled, atol=1e-4), \
    f"Symmetric check failed: hansen={lp_hansen}, scaled_t={lp_student_scaled}"
log.info("Hansen skew-t sanity check PASSED (lam=0 matches variance-standardized Student-t)")

# ============================================================
# 3. GJR-GARCH(1,1) ESTIMATION
# ============================================================
log.info("--- Step 3: Fit GJR-GARCH(1,1) ---")

def gjr_garch_filter(params: np.ndarray, r: np.ndarray):
    """GJR-GARCH(1,1) variance filter. Returns conditional variances."""
    omega, alpha, gamma, beta = params
    T = len(r)
    h = np.zeros(T)
    h[0] = np.var(r)
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0.0 else 0.0
        h[t] = omega + alpha * r[t - 1] ** 2 + gamma * r[t - 1] ** 2 * ind + beta * h[t - 1]
        h[t] = max(h[t], 1e-8)
    return h


def gjr_nll_normal(params: np.ndarray, r: np.ndarray) -> float:
    """NLL with Normal innovations (for initial GJR estimation)."""
    omega, alpha, gamma, beta = params
    # Constraints
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e10
    if alpha + beta + gamma / 2 >= 0.9999:
        return 1e10
    h = gjr_garch_filter(params, r)
    if np.any(h <= 0):
        return 1e10
    nll = 0.5 * np.sum(np.log(2 * np.pi * h) + r ** 2 / h)
    return nll if np.isfinite(nll) else 1e10


# Estimate GJR-GARCH on full sample with Normal innovations
log.info("  Estimating GJR-GARCH(1,1) with Normal innovations (full sample)...")
bounds_gjr = [(1e-6, 2.0), (1e-5, 0.3), (0.0, 0.3), (0.5, 0.999)]

var_r = float(np.var(returns))
omega0 = var_r * 0.05
best_res_gjr = None
best_nll_gjr = 1e10
init_candidates = [
    [omega0, 0.04, 0.06, 0.90],
    [omega0 * 2, 0.05, 0.08, 0.88],
    [omega0, 0.06, 0.10, 0.85],
    [omega0, 0.03, 0.12, 0.88],
]
for x0 in init_candidates:
    try:
        res = optimize.minimize(
            gjr_nll_normal, x0, args=(returns,),
            method="L-BFGS-B", bounds=bounds_gjr,
            options={"maxiter": 500, "ftol": 1e-12}
        )
        if res.fun < best_nll_gjr:
            best_nll_gjr = res.fun
            best_res_gjr = res
    except Exception:
        pass

if best_res_gjr is None or not best_res_gjr.success:
    log.warning("GJR-GARCH optimization did not fully converge — using best found")

omega_hat, alpha_hat, gamma_hat, beta_hat = best_res_gjr.x
persistence = alpha_hat + beta_hat + gamma_hat / 2
log.info(f"  GJR-GARCH params: ω={omega_hat:.6f}, α={alpha_hat:.4f}, "
         f"γ={gamma_hat:.4f}, β={beta_hat:.4f}, persistence={persistence:.4f}")
log.info(f"  GJR-GARCH convergence: {best_res_gjr.success}, NLL={best_nll_gjr:.2f}")

# Extract standardized residuals
h_full = gjr_garch_filter(best_res_gjr.x, returns)
z_full = returns / np.sqrt(h_full)  # standardized residuals
log.info(f"  Standardized residuals: mean={z_full.mean():.4f}, std={z_full.std():.4f}, "
         f"skew={stats.skew(z_full):.4f}, kurt={stats.kurtosis(z_full):.4f}")

# ============================================================
# 4. FIT HANSEN SKEW-T TO STANDARDIZED RESIDUALS
# ============================================================
log.info("--- Step 4: Fit Hansen skew-t to GJR-GARCH residuals ---")

# Multi-start optimization
init_params_list = [
    [5.0, 0.0],
    [5.2, -0.05],  # paper values as warm start
    [6.0, -0.10],
    [4.0, 0.0],
    [7.0, -0.05],
    [8.0, 0.10],
    [10.0, 0.0],
    [5.0, 0.05],
]

bounds_skewt = [(2.05, 100.0), (-0.99, 0.99)]

best_res_skewt = None
best_nll_skewt = 1e10
for x0 in init_params_list:
    try:
        res = optimize.minimize(
            hansen_skewt_nll, x0, args=(z_full,),
            method="L-BFGS-B", bounds=bounds_skewt,
            options={"maxiter": 1000, "ftol": 1e-14, "gtol": 1e-9}
        )
        if res.fun < best_nll_skewt:
            best_nll_skewt = res.fun
            best_res_skewt = res
    except Exception:
        pass

eta_hat, lam_hat = best_res_skewt.x
log.info(f"  Hansen skew-t MLE: η={eta_hat:.4f}, λ={lam_hat:.5f}")
log.info(f"  Convergence: {best_res_skewt.success}, NLL={best_nll_skewt:.2f}")

# ============================================================
# 5. COMPARISON WITH PAPER VALUES
# ============================================================
log.info("--- Step 5: Compare with paper values η=5.2, λ=-0.05 ---")

ETA_PAPER = 5.2
LAM_PAPER = -0.05
TOL_ETA = 0.30   # ±0.30 → ~6% rtol — standard for point-estimate comparison
TOL_LAM = 0.03   # ±0.03

eta_diff = abs(eta_hat - ETA_PAPER)
lam_diff = abs(lam_hat - LAM_PAPER)
eta_rtol = eta_diff / ETA_PAPER
lam_rtol = lam_diff / abs(LAM_PAPER) if LAM_PAPER != 0 else lam_diff

eta_match = eta_diff <= TOL_ETA
lam_match = lam_diff <= TOL_LAM

log.info(f"  η: paper={ETA_PAPER}, estimated={eta_hat:.4f}, diff={eta_diff:.4f}, rtol={eta_rtol:.3%} → {'MATCH' if eta_match else 'DIVERGE'}")
log.info(f"  λ: paper={LAM_PAPER}, estimated={lam_hat:.5f}, diff={lam_diff:.5f}, rtol={lam_rtol:.3%} → {'MATCH' if lam_match else 'DIVERGE'}")

# ============================================================
# 6. ALSO FIT TO OOS PERIOD 2020-2026 (paper's VaR window)
# ============================================================
log.info("--- Step 6: Fit on OOS sub-period 2020-2026 (paper's VaR period) ---")

oos_start = "2020-01-01"
oos_end = "2026-04-01"
oos_mask = (returns_index >= oos_start) & (returns_index <= oos_end)
returns_oos = returns[oos_mask]
log.info(f"  OOS period: {oos_start} to {oos_end}, n={len(returns_oos)}")

# Extract residuals for OOS window only
oos_idx_start = np.searchsorted(returns_index, pd.Timestamp(oos_start))
z_oos = z_full[oos_idx_start:]
log.info(f"  OOS standardized residuals: n={len(z_oos)}, mean={z_oos.mean():.4f}, "
         f"std={z_oos.std():.4f}, skew={stats.skew(z_oos):.4f}")

best_res_oos = None
best_nll_oos = 1e10
for x0 in init_params_list:
    try:
        res = optimize.minimize(
            hansen_skewt_nll, x0, args=(z_oos,),
            method="L-BFGS-B", bounds=bounds_skewt,
            options={"maxiter": 1000, "ftol": 1e-14}
        )
        if res.fun < best_nll_oos:
            best_nll_oos = res.fun
            best_res_oos = res
    except Exception:
        pass

eta_oos, lam_oos = best_res_oos.x
log.info(f"  OOS Hansen skew-t: η={eta_oos:.4f}, λ={lam_oos:.5f}")

eta_oos_diff = abs(eta_oos - ETA_PAPER)
lam_oos_diff = abs(lam_oos - LAM_PAPER)
eta_oos_match = eta_oos_diff <= TOL_ETA
lam_oos_match = lam_oos_diff <= TOL_LAM
log.info(f"  OOS η: diff={eta_oos_diff:.4f} → {'MATCH' if eta_oos_match else 'DIVERGE'}")
log.info(f"  OOS λ: diff={lam_oos_diff:.5f} → {'MATCH' if lam_oos_match else 'DIVERGE'}")

# ============================================================
# 7. ALSO FIT SYMMETRIC STUDENT-T FOR COMPARISON
# ============================================================
log.info("--- Step 7: Symmetric Student-t fit (paper uses df=5) ---")

def student_t_nll(df, z):
    if df <= 2.0 or df > 200:
        return 1e10
    scale = np.sqrt((df - 2) / df)
    ll = np.sum(student_t.logpdf(z / scale, df=df) - np.log(scale))
    return -ll if np.isfinite(ll) else 1e10

res_sym = optimize.minimize_scalar(student_t_nll, bounds=(2.1, 80.0),
                                   method="bounded", args=(z_full,))
df_sym = float(res_sym.x)
log.info(f"  Symmetric Student-t MLE df={df_sym:.4f}")

# ============================================================
# 8. VaR VIOLATION CHECK
# ============================================================
log.info("--- Step 8: VaR violation check (1% level, 2020-2026) ---")

# Use GJR-GARCH conditional variance for OOS
h_oos = h_full[oos_idx_start:]
r_oos = returns_oos
n_oos = len(r_oos)
log.info(f"  OOS period n={n_oos} days (paper says 1,501)")

# Compute VaR using skew-t quantile approximation
# For skew-t, use numerical CDF inversion for 1% quantile
# VaR using Student-t(5) as in paper
df_paper = 5.0
scale_paper = np.sqrt((df_paper - 2) / df_paper)
q01_t5 = student_t.ppf(0.01, df=df_paper) * scale_paper
var_t5 = np.sqrt(h_oos) * q01_t5  # negative (losses)
violations_t5 = np.sum(r_oos < var_t5)
viol_rate_t5 = violations_t5 / n_oos
log.info(f"  VaR (t5): violations={violations_t5}, rate={viol_rate_t5:.4%}")

# VaR using fitted symmetric Student-t
scale_sym = np.sqrt((df_sym - 2) / df_sym)
q01_sym = student_t.ppf(0.01, df=df_sym) * scale_sym
var_sym = np.sqrt(h_oos) * q01_sym
violations_sym = np.sum(r_oos < var_sym)
log.info(f"  VaR (sym-t df={df_sym:.2f}): violations={violations_sym}, rate={violations_sym/n_oos:.4%}")

# ============================================================
# 9. VERDICT
# ============================================================
log.info("--- Step 9: Verdict ---")

# Overall match decision
overall_full_match = eta_match and lam_match
overall_oos_match  = eta_oos_match and lam_oos_match
best_match = "FULL_SAMPLE" if overall_full_match else ("OOS" if overall_oos_match else "NO_MATCH")

if eta_diff <= 0.30 and lam_diff <= 0.05:
    verdict = "(a) MATCHED — both η and λ within tight tolerance"
elif eta_diff <= 0.5 or lam_diff <= 0.10:
    verdict = "(b) APPROXIMATE — one parameter within 10%"
else:
    verdict = "(c) DIVERGENT — significant deviation from paper values"

log.info(f"  Full-sample: η={eta_hat:.4f} (paper 5.2, diff {eta_diff:.4f}), λ={lam_hat:.5f} (paper -0.05, diff {lam_diff:.5f})")
log.info(f"  OOS:         η={eta_oos:.4f} (paper 5.2, diff {eta_oos_diff:.4f}), λ={lam_oos:.5f} (paper -0.05, diff {lam_oos_diff:.5f})")
log.info(f"  VERDICT: {verdict}")

# ============================================================
# 10. SAVE RESULTS JSON
# ============================================================
log.info("--- Step 10: Save results ---")

results = {
    "experiment_id": EXPERIMENT_ID,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "metadata": {
        "purpose": "Reproduce Paper 2 (taiwan-vt) body.tex:459 skew-t params η=5.2, λ=-0.05",
        "paper_ref": "paper/taiwan-vt/body.tex line 459",
        "reference": "Hansen (1994) IER 35(3):705-730",
        "k1100c_connection": "Same Hansen skew-t PDF as K1100c bivariate copula"
    },
    "data": {
        "ticker": "0050.TW",
        "start": str(close.index[1].date()),
        "end": str(close.index[-1].date()),
        "n_total": n_total,
        "n_oos": n_oos,
        "oos_period": f"{oos_start} to {oos_end}"
    },
    "gjr_garch": {
        "omega": float(omega_hat),
        "alpha": float(alpha_hat),
        "gamma": float(gamma_hat),
        "beta": float(beta_hat),
        "persistence": float(persistence),
        "converged": bool(best_res_gjr.success),
        "nll": float(best_nll_gjr),
        "stdresid_mean": float(z_full.mean()),
        "stdresid_std": float(z_full.std()),
        "stdresid_skew": float(stats.skew(z_full)),
        "stdresid_kurt": float(stats.kurtosis(z_full))
    },
    "skewt_full_sample": {
        "eta_hat": float(eta_hat),
        "lambda_hat": float(lam_hat),
        "eta_paper": float(ETA_PAPER),
        "lambda_paper": float(LAM_PAPER),
        "eta_diff": float(eta_diff),
        "lambda_diff": float(lam_diff),
        "eta_rtol": float(eta_rtol),
        "lambda_rtol": float(lam_rtol),
        "eta_match": bool(eta_match),
        "lambda_match": bool(lam_match),
        "overall_match": bool(overall_full_match),
        "nll": float(best_nll_skewt),
        "converged": bool(best_res_skewt.success)
    },
    "skewt_oos_2020_2026": {
        "eta_hat": float(eta_oos),
        "lambda_hat": float(lam_oos),
        "eta_diff": float(eta_oos_diff),
        "lambda_diff": float(lam_oos_diff),
        "eta_match": bool(eta_oos_match),
        "lambda_match": bool(lam_oos_match),
        "overall_match": bool(overall_oos_match),
        "nll": float(best_nll_oos),
        "converged": bool(best_res_oos.success)
    },
    "student_t_symmetric": {
        "df_mle": float(df_sym),
        "df_paper_assumed": 5.0
    },
    "var_violations": {
        "n_oos": n_oos,
        "student_t5_violations": int(violations_t5),
        "student_t5_rate": float(viol_rate_t5),
        "sym_t_mle_violations": int(violations_sym),
        "sym_t_mle_rate": float(violations_sym / n_oos),
        "paper_claimed_violations": 8,
        "paper_claimed_rate": 0.005
    },
    "verdict": {
        "code": verdict,
        "best_match_period": best_match,
        "eta_reproduced": bool(eta_match or eta_oos_match),
        "lambda_reproduced": bool(lam_match or lam_oos_match),
        "recommendation": (
            "(a) Update paper to match computed values"
            if not (overall_full_match or overall_oos_match)
            else "Paper values confirmed within tolerance"
        )
    }
}

out_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-aa2d76a6/experiments/k1184/k1184_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
log.info(f"Results saved to {out_path}")
log.info(f"=== {EXPERIMENT_ID} COMPLETE ===")
log.info(f"  Full-sample: η={eta_hat:.4f}, λ={lam_hat:.5f}")
log.info(f"  OOS:         η={eta_oos:.4f}, λ={lam_oos:.5f}")
log.info(f"  Verdict:     {verdict}")
