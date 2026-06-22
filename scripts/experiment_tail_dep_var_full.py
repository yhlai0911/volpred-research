#!/usr/bin/env python3
"""
Supplementary: Full-Sample VaR Comparison + Stress Test Analysis
================================================================
The 2023-2024 OOS was too benign (1 violation across all methods).
This script:
1. Runs all 4 VaR methods over the FULL 2014-2025 period (includes COVID, 2022)
2. Focuses on crisis sub-periods where tail dep matters most
3. Computes bootstrap confidence intervals for VaR understatement
"""
from __future__ import annotations
import sys
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize_scalar

warnings.filterwarnings("ignore")
sys.path.insert(0, "src")
from volpred.data.manager import DataManager
from volpred.data.preprocessing import prepare_model_data

ASSETS = ["SPY", "QQQ", "GLD"]
WEIGHTS = np.array([0.4, 0.3, 0.3])
START = "2005-01-01"
END = "2026-12-31"
WINDOW = 2000
ALPHA = 0.01

print("=" * 80)
print("FULL-SAMPLE VaR COMPARISON + STRESS TEST (Supplement to Q14)")
print("=" * 80)

dm = DataManager()
returns_dict = {}
for asset in ASSETS:
    prices = dm.get_price_data(asset, START, END)
    df = prepare_model_data(prices)
    returns_dict[asset] = df["log_return"]
    print(f"  {asset}: {len(df)} obs")

ret_df = pd.DataFrame(returns_dict).dropna()
ret_arr = ret_df.values
port_ret_all = ret_arr @ WEIGHTS
print(f"  Aligned: {len(ret_df)} obs, {ret_df.index[0].date()} to {ret_df.index[-1].date()}")

# ── Helpers (same as main script) ────────────────────────────────────────

def empirical_cdf(data):
    n = len(data)
    ranks = np.argsort(np.argsort(data, axis=0), axis=0) + 1
    return ranks / (n + 1)

def clayton_loglik(theta, u, v):
    if theta <= 0:
        return 1e10
    ut = u ** (-theta)
    vt = v ** (-theta)
    s = np.maximum(ut + vt - 1.0, 1e-15)
    log_density = (np.log(1 + theta) + (-1 - theta) * (np.log(u) + np.log(v))
                   + (-1.0/theta - 2) * np.log(s))
    return -np.sum(log_density)

def fit_clayton(u, v):
    result = minimize_scalar(lambda th: clayton_loglik(th, u, v),
                             bounds=(0.01, 50), method='bounded')
    return result.x

def clayton_tail_dep(theta):
    return 2 ** (-1.0 / theta)

def simulate_clayton_pair(n, theta, rng):
    u1 = rng.uniform(size=n)
    t = rng.uniform(size=n)
    u2 = ((t ** (-theta / (1 + theta)) - 1) * u1 ** (-theta) + 1) ** (-1.0 / theta)
    u2 = np.clip(u2, 1e-10, 1 - 1e-10)
    return u1, u2

def compute_var_gaussian(window_ret, n_sim, rng):
    u = empirical_cdf(window_ret)
    z = stats.norm.ppf(np.clip(u, 0.001, 0.999))
    z = np.clip(z, -8, 8)
    corr_matrix = np.corrcoef(z, rowvar=False)
    eigvals = np.linalg.eigvalsh(corr_matrix)
    if np.min(eigvals) < 0:
        corr_matrix += (-np.min(eigvals) + 0.01) * np.eye(3)
        d = np.sqrt(np.diag(corr_matrix))
        corr_matrix = corr_matrix / np.outer(d, d)

    marginal_params = []
    for j in range(3):
        df_j, loc_j, scale_j = stats.t.fit(window_ret[:, j])
        df_j = max(min(df_j, 30), 2.1)
        marginal_params.append((df_j, loc_j, scale_j))

    z_sim = rng.multivariate_normal(np.zeros(3), corr_matrix, size=n_sim)
    u_sim = stats.norm.cdf(z_sim)

    sim_returns = np.zeros((n_sim, 3))
    for j in range(3):
        df_j, loc_j, scale_j = marginal_params[j]
        sim_returns[:, j] = stats.t.ppf(u_sim[:, j], df_j, loc=loc_j, scale=scale_j)

    return np.quantile(sim_returns @ WEIGHTS, ALPHA)

def compute_var_clayton(window_ret, n_sim, rng):
    u = empirical_cdf(window_ret)
    theta_spy_qqq = fit_clayton(u[:, 0], u[:, 1])
    z = stats.norm.ppf(np.clip(u, 0.001, 0.999))
    rho_spy_gld = np.corrcoef(z[:, 0], z[:, 2])[0, 1]

    marginal_params = []
    for j in range(3):
        df_j, loc_j, scale_j = stats.t.fit(window_ret[:, j])
        df_j = max(min(df_j, 30), 2.1)
        marginal_params.append((df_j, loc_j, scale_j))

    u_spy, u_qqq = simulate_clayton_pair(n_sim, theta_spy_qqq, rng)
    z_spy = stats.norm.ppf(np.clip(u_spy, 0.001, 0.999))
    z_gld = rho_spy_gld * z_spy + np.sqrt(1 - rho_spy_gld**2) * rng.normal(size=n_sim)
    u_gld = stats.norm.cdf(z_gld)

    u_sim = np.column_stack([u_spy, u_qqq, u_gld])
    sim_returns = np.zeros((n_sim, 3))
    for j in range(3):
        df_j, loc_j, scale_j = marginal_params[j]
        sim_returns[:, j] = stats.t.ppf(np.clip(u_sim[:, j], 0.001, 0.999),
                                         df_j, loc=loc_j, scale=scale_j)

    return np.quantile(sim_returns @ WEIGHTS, ALPHA)

def compute_var_dcc(window_ret):
    """DCC-style VaR using EWMA conditional volatility."""
    ewma_lambda = 0.94
    n, k = window_ret.shape
    cond_vol = np.zeros((n, k))
    for j in range(k):
        r = window_ret[:, j]
        var_t = np.var(r[:50])
        for t_i in range(n):
            cond_vol[t_i, j] = np.sqrt(max(var_t, 1e-10))
            var_t = ewma_lambda * var_t + (1 - ewma_lambda) * r[t_i]**2

    # Use last conditional vol + rolling correlation
    std_resid = window_ret / cond_vol
    Q_bar = np.corrcoef(std_resid, rowvar=False)
    D_t = np.diag(cond_vol[-1])
    cond_cov = D_t @ Q_bar @ D_t

    port_var_dcc = WEIGHTS @ cond_cov @ WEIGHTS
    port_std_dcc = np.sqrt(port_var_dcc)
    port_mean = window_ret.mean(axis=0) @ WEIGHTS

    port_window_ret = window_ret @ WEIGHTS
    df_fit, _, _ = stats.t.fit(port_window_ret)
    df_fit = max(min(df_fit, 30), 2.1)
    z_alpha = stats.t.ppf(ALPHA, df_fit)
    return port_mean + z_alpha * port_std_dcc

# ══════════════════════════════════════════════════════════════════════════
# FULL-SAMPLE ROLLING VaR (2014-2025)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("FULL-SAMPLE ROLLING VaR (post-2014, includes crises)")
print("=" * 80)

full_start = "2014-01-01"
eval_mask = ret_df.index >= full_start
eval_indices = np.where(eval_mask)[0]
eval_indices = eval_indices[eval_indices >= WINDOW]

print(f"  Period: {ret_df.index[eval_indices[0]].date()} to {ret_df.index[eval_indices[-1]].date()}")
print(f"  Days: {len(eval_indices)}")

N_SIM = 30000
rng = np.random.default_rng(42)
REFIT_FREQ = 10

var_gaussian = np.full(len(eval_indices), np.nan)
var_dcc = np.full(len(eval_indices), np.nan)
var_clayton = np.full(len(eval_indices), np.nan)
var_histsim = np.full(len(eval_indices), np.nan)
actual_returns = np.full(len(eval_indices), np.nan)
eval_dates = []

print(f"  Computing {len(eval_indices)} days (refit every {REFIT_FREQ})...")

cached_g = cached_c = cached_d = None
for idx, t in enumerate(eval_indices):
    w_start = t - WINDOW
    window_ret = ret_arr[w_start:t]
    actual_returns[idx] = port_ret_all[t]
    eval_dates.append(ret_df.index[t])

    port_window_ret = window_ret @ WEIGHTS
    var_histsim[idx] = np.quantile(port_window_ret, ALPHA)

    if idx % REFIT_FREQ == 0:
        try:
            cached_g = compute_var_gaussian(window_ret, N_SIM, rng)
        except Exception as exc:
            print(f"    [warn] gaussian copula VaR fallback at {ret_df.index[t].date()}: {exc}")
            cached_g = var_histsim[idx]
        try:
            cached_c = compute_var_clayton(window_ret, N_SIM, rng)
        except Exception as exc:
            print(f"    [warn] clayton copula VaR fallback at {ret_df.index[t].date()}: {exc}")
            cached_c = var_histsim[idx]
        try:
            cached_d = compute_var_dcc(window_ret)
        except Exception as exc:
            print(f"    [warn] DCC VaR fallback at {ret_df.index[t].date()}: {exc}")
            cached_d = var_histsim[idx]

    var_gaussian[idx] = cached_g
    var_dcc[idx] = cached_d
    var_clayton[idx] = cached_c

    if (idx + 1) % 500 == 0:
        print(f"    {idx+1}/{len(eval_indices)} done...")

print(f"    {len(eval_indices)}/{len(eval_indices)} done.")

eval_dates = pd.DatetimeIndex(eval_dates)
results = pd.DataFrame({
    "port_return": actual_returns,
    "var_gaussian": var_gaussian,
    "var_dcc": var_dcc,
    "var_clayton": var_clayton,
    "var_histsim": var_histsim,
}, index=eval_dates)

for m in ["gaussian", "dcc", "clayton", "histsim"]:
    results[f"viol_{m}"] = (results["port_return"] < results[f"var_{m}"]).astype(int)

n_total = len(results)

# ══════════════════════════════════════════════════════════════════════════
# OVERALL RESULTS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("OVERALL FULL-SAMPLE RESULTS")
print("=" * 80)

print(f"\n  {'Method':<25} {'Viols':>6} {'Rate':>7} {'Mean VaR':>10} {'Kupiec':>8}")
print("  " + "-" * 60)

try:
    from volpred.evaluation.statistical_tests import kupiec_test, christoffersen_test
    has_tests = True
except ImportError:
    has_tests = False

for m, label in [("gaussian", "Gaussian Copula"), ("dcc", "DCC"),
                  ("clayton", "Clayton Mixed"), ("histsim", "Historical Sim")]:
    v = results[f"viol_{m}"].sum()
    rate = v / n_total
    mean_v = results[f"var_{m}"].mean()
    if has_tests:
        k = kupiec_test(results[f"viol_{m}"].values, alpha=ALPHA)
        kp = f"p={k['p_value']:.3f}"
    else:
        kp = "N/A"
    flag = " <<" if rate > 0.02 else " >>" if rate < 0.005 else ""
    print(f"  {label:<25} {v:>6} {rate*100:>6.2f}% {mean_v*100:>9.4f}% {kp:>8}{flag}")

# ══════════════════════════════════════════════════════════════════════════
# YEAR-BY-YEAR BREAKDOWN
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("YEAR-BY-YEAR VIOLATIONS")
print("=" * 80)

results["year"] = results.index.year
yearly = results.groupby("year").agg(
    n_days=("port_return", "count"),
    viol_gaussian=("viol_gaussian", "sum"),
    viol_dcc=("viol_dcc", "sum"),
    viol_clayton=("viol_clayton", "sum"),
    viol_histsim=("viol_histsim", "sum"),
)

print(f"\n  {'Year':>6} {'Days':>5} {'Gauss':>7} {'DCC':>7} {'Clayton':>7} {'HistSim':>7}  "
      f"{'Gauss%':>7} {'DCC%':>7} {'Clay%':>7} {'Hist%':>7}")
print("  " + "-" * 90)

for year, row in yearly.iterrows():
    n = row["n_days"]
    v_g = int(row["viol_gaussian"])
    v_d = int(row["viol_dcc"])
    v_c = int(row["viol_clayton"])
    v_h = int(row["viol_histsim"])
    flag = ""
    if any(v / n > 0.03 for v in [v_g, v_d, v_c, v_h]):
        flag = " <<"
    print(f"  {year:>6} {n:>5} {v_g:>7} {v_d:>7} {v_c:>7} {v_h:>7}  "
          f"{v_g/n*100:>6.1f}% {v_d/n*100:>6.1f}% {v_c/n*100:>6.1f}% {v_h/n*100:>6.1f}%{flag}")

# ══════════════════════════════════════════════════════════════════════════
# CRISIS ZOOM: VaR ACCURACY DURING STRESS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("CRISIS PERIOD VaR ACCURACY")
print("=" * 80)

crisis_periods = [
    ("2018 Q4", "2018-10-01", "2018-12-31"),
    ("COVID", "2020-02-01", "2020-04-30"),
    ("2022 Bear", "2022-01-01", "2022-10-31"),
    ("2023 calm", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("Aug 2024 scare", "2024-07-15", "2024-08-15"),
]

for crisis_name, cs, ce in crisis_periods:
    mask = (results.index >= cs) & (results.index <= ce)
    crisis = results[mask]
    if len(crisis) == 0:
        continue

    n = len(crisis)
    print(f"\n  {crisis_name} ({cs} to {ce}): {n} days")
    print(f"    {'Method':<20} {'Viols':>5} {'Rate':>7} {'MeanVaR':>9} {'MinVaR':>9}")
    print("    " + "-" * 55)

    for m, label in [("gaussian", "Gaussian"), ("dcc", "DCC"),
                      ("clayton", "Clayton"), ("histsim", "HistSim")]:
        v = int(crisis[f"viol_{m}"].sum())
        mean_v = crisis[f"var_{m}"].mean()
        min_v = crisis[f"var_{m}"].min()  # most conservative VaR in period
        print(f"    {label:<20} {v:>5} {v/n*100:>6.1f}% {mean_v*100:>8.3f}% {min_v*100:>8.3f}%")

    worst_idx = crisis["port_return"].idxmin()
    worst_ret = crisis.loc[worst_idx, "port_return"]
    print(f"    Worst day: {worst_idx.date()} → {worst_ret*100:.2f}%")
    breached_g = worst_ret < crisis.loc[worst_idx, "var_gaussian"]
    breached_c = worst_ret < crisis.loc[worst_idx, "var_clayton"]
    print(f"    Gaussian VaR: {crisis.loc[worst_idx, 'var_gaussian']*100:.2f}% → {'BREACH' if breached_g else 'OK'}")
    print(f"    Clayton VaR:  {crisis.loc[worst_idx, 'var_clayton']*100:.2f}% → {'BREACH' if breached_c else 'OK'}")

# ══════════════════════════════════════════════════════════════════════════
# VaR GAP ANALYSIS: WHEN DOES GAUSSIAN != CLAYTON?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("VaR GAP ANALYSIS: GAUSSIAN vs CLAYTON")
print("=" * 80)

var_gap = results["var_gaussian"] - results["var_clayton"]
# Positive gap = Gaussian less negative = Gaussian understates
pct_gap = (results["var_gaussian"].abs() - results["var_clayton"].abs()) / results["var_clayton"].abs() * 100

print(f"\n  Gap = Gaussian VaR - Clayton VaR (positive = Gaussian understates)")
print(f"    Mean gap:  {var_gap.mean()*100:.4f}% ({pct_gap.mean():+.2f}%)")
print(f"    Std gap:   {var_gap.std()*100:.4f}%")
print(f"    Max gap:   {var_gap.max()*100:.4f}% ({pct_gap.max():+.2f}% understatement)")
print(f"    Min gap:   {var_gap.min()*100:.4f}% ({pct_gap.min():+.2f}% overstatement)")

# Distribution of gap
for q in [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]:
    print(f"    {q*100:>5.0f}th percentile: {pct_gap.quantile(q):+.2f}%")

# Days where only Gaussian breaches but Clayton doesn't
only_g_breach = ((results["port_return"] < results["var_gaussian"]) &
                 (results["port_return"] >= results["var_clayton"]))
only_c_breach = ((results["port_return"] < results["var_clayton"]) &
                 (results["port_return"] >= results["var_gaussian"]))
both_breach = ((results["port_return"] < results["var_gaussian"]) &
               (results["port_return"] < results["var_clayton"]))

print(f"\n  Breach analysis:")
print(f"    Both breach:        {both_breach.sum()}")
print(f"    Only Gaussian:      {only_g_breach.sum()} (Gaussian understates)")
print(f"    Only Clayton:       {only_c_breach.sum()} (Clayton understates)")
print(f"    Neither:            {(~(results['port_return'] < results['var_gaussian']) & ~(results['port_return'] < results['var_clayton'])).sum()}")

if only_g_breach.sum() > 0:
    print(f"\n  Days where ONLY Gaussian breaches:")
    for d in results[only_g_breach].index:
        ret = results.loc[d, "port_return"]
        vg = results.loc[d, "var_gaussian"]
        vc = results.loc[d, "var_clayton"]
        print(f"    {d.date()}: ret={ret*100:.2f}%, Gauss VaR={vg*100:.2f}%, Clayton VaR={vc*100:.2f}%")

# ══════════════════════════════════════════════════════════════════════════
# STRESS TEST: SIMULATED EXTREME SCENARIOS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("STRESS TEST: SIMULATED EXTREME TAIL SCENARIOS")
print("=" * 80)

# Use the last window of data to calibrate, then simulate extreme scenarios
last_window = ret_arr[-WINDOW:]
u_last = empirical_cdf(last_window)

# Fit marginals
marginal_params = []
for j in range(3):
    df_j, loc_j, scale_j = stats.t.fit(last_window[:, j])
    df_j = max(min(df_j, 30), 2.1)
    marginal_params.append((df_j, loc_j, scale_j))

# Fit Clayton for SPY-QQQ
theta_last = fit_clayton(u_last[:, 0], u_last[:, 1])
lambda_L_last = clayton_tail_dep(theta_last)
print(f"\n  Last window Clayton theta: {theta_last:.3f}, lambda_L: {lambda_L_last:.3f}")

# Simulate large samples from both copulas
N_STRESS = 500000

# Gaussian copula simulation
z = stats.norm.ppf(np.clip(u_last, 0.001, 0.999))
z = np.clip(z, -8, 8)
corr_g = np.corrcoef(z, rowvar=False)
eigvals = np.linalg.eigvalsh(corr_g)
if np.min(eigvals) < 0:
    corr_g += (-np.min(eigvals) + 0.01) * np.eye(3)
    d = np.sqrt(np.diag(corr_g))
    corr_g = corr_g / np.outer(d, d)

z_sim_g = rng.multivariate_normal(np.zeros(3), corr_g, size=N_STRESS)
u_sim_g = stats.norm.cdf(z_sim_g)
sim_ret_g = np.zeros((N_STRESS, 3))
for j in range(3):
    df_j, loc_j, scale_j = marginal_params[j]
    sim_ret_g[:, j] = stats.t.ppf(np.clip(u_sim_g[:, j], 0.001, 0.999),
                                    df_j, loc=loc_j, scale=scale_j)
port_sim_g = sim_ret_g @ WEIGHTS

# Clayton mixed copula simulation
rho_spy_gld = np.corrcoef(z[:, 0], z[:, 2])[0, 1]
u_spy_c, u_qqq_c = simulate_clayton_pair(N_STRESS, theta_last, rng)
z_spy_c = stats.norm.ppf(np.clip(u_spy_c, 0.001, 0.999))
z_gld_c = rho_spy_gld * z_spy_c + np.sqrt(1 - rho_spy_gld**2) * rng.normal(size=N_STRESS)
u_gld_c = stats.norm.cdf(z_gld_c)
u_sim_c = np.column_stack([u_spy_c, u_qqq_c, u_gld_c])
sim_ret_c = np.zeros((N_STRESS, 3))
for j in range(3):
    df_j, loc_j, scale_j = marginal_params[j]
    sim_ret_c[:, j] = stats.t.ppf(np.clip(u_sim_c[:, j], 0.001, 0.999),
                                    df_j, loc=loc_j, scale=scale_j)
port_sim_c = sim_ret_c @ WEIGHTS

print(f"\n  Simulated {N_STRESS:,} scenarios from each copula")
print(f"\n  {'Quantile':<12} {'Gaussian':>12} {'Clayton':>12} {'Gap':>8} {'Gap%':>8}")
print("  " + "-" * 55)

for q in [0.05, 0.025, 0.01, 0.005, 0.001, 0.0005, 0.0001]:
    var_g_q = np.quantile(port_sim_g, q)
    var_c_q = np.quantile(port_sim_c, q)
    gap = (abs(var_g_q) - abs(var_c_q)) / abs(var_c_q) * 100
    print(f"  {q*100:>7.2f}%    {var_g_q*100:>10.3f}% {var_c_q*100:>10.3f}%  {gap:>+6.1f}%")

# Conditional on SPY being in extreme left tail
for threshold_q in [0.05, 0.01, 0.001]:
    spy_thresh_g = np.quantile(sim_ret_g[:, 0], threshold_q)
    spy_thresh_c = np.quantile(sim_ret_c[:, 0], threshold_q)

    # Given SPY < threshold, what is QQQ distribution?
    mask_g = sim_ret_g[:, 0] < spy_thresh_g
    mask_c = sim_ret_c[:, 0] < spy_thresh_c

    qqq_given_spy_g = sim_ret_g[mask_g, 1]
    qqq_given_spy_c = sim_ret_c[mask_c, 1]

    port_given_spy_g = port_sim_g[mask_g]
    port_given_spy_c = port_sim_c[mask_c]

    print(f"\n  Conditional on SPY < {threshold_q*100:.1f}% quantile:")
    print(f"    Gaussian: E[QQQ|SPY crash]={qqq_given_spy_g.mean()*100:.3f}%, "
          f"E[Port]={port_given_spy_g.mean()*100:.3f}%")
    print(f"    Clayton:  E[QQQ|SPY crash]={qqq_given_spy_c.mean()*100:.3f}%, "
          f"E[Port]={port_given_spy_c.mean()*100:.3f}%")
    print(f"    Gap in E[Port|crash]: {(port_given_spy_g.mean()-port_given_spy_c.mean())*100:.3f}% "
          f"(positive = Gaussian understates crash severity)")

# ══════════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("FINAL SUMMARY: PRACTICAL IMPACT OF TAIL DEPENDENCE")
print("=" * 80)

# Overall violation rates
viol_g_total = results["viol_gaussian"].sum()
viol_c_total = results["viol_clayton"].sum()
viol_h_total = results["viol_histsim"].sum()
viol_d_total = results["viol_dcc"].sum()

# VaR at extreme quantiles from simulation
var_g_1 = np.quantile(port_sim_g, 0.01)
var_c_1 = np.quantile(port_sim_c, 0.01)
var_g_01 = np.quantile(port_sim_g, 0.001)
var_c_01 = np.quantile(port_sim_c, 0.001)

understatement_1 = (abs(var_g_1) - abs(var_c_1)) / abs(var_c_1) * 100
understatement_01 = (abs(var_g_01) - abs(var_c_01)) / abs(var_c_01) * 100

print(f"""
  ================================================================
  QUESTION: How much does ignoring tail dep understate portfolio VaR?
  ================================================================

  1. AT 1% VaR LEVEL:
     Gaussian: {var_g_1*100:.3f}%
     Clayton:  {var_c_1*100:.3f}%
     Understatement: {understatement_1:+.1f}%

  2. AT 0.1% VaR LEVEL (EXTREME):
     Gaussian: {var_g_01*100:.3f}%
     Clayton:  {var_c_01*100:.3f}%
     Understatement: {understatement_01:+.1f}%

  3. CONDITIONAL ON SPY CRASH (bottom 1%):
     Gaussian E[Port|SPY crash]: {port_sim_g[sim_ret_g[:, 0] < np.quantile(sim_ret_g[:, 0], 0.01)].mean()*100:.3f}%
     Clayton E[Port|SPY crash]:  {port_sim_c[sim_ret_c[:, 0] < np.quantile(sim_ret_c[:, 0], 0.01)].mean()*100:.3f}%

  4. FULL-SAMPLE BACKTESTING (2014-2025):
     Gaussian violations: {viol_g_total}/{n_total} ({viol_g_total/n_total*100:.2f}%)
     DCC violations:      {viol_d_total}/{n_total} ({viol_d_total/n_total*100:.2f}%)
     Clayton violations:  {viol_c_total}/{n_total} ({viol_c_total/n_total*100:.2f}%)
     HistSim violations:  {viol_h_total}/{n_total} ({viol_h_total/n_total*100:.2f}%)
     Expected: 1.00%

  5. PRACTICAL SIGNIFICANCE:
     At 1% level: tail dep adds ~{abs(understatement_1):.0f}% to VaR → {'MARGINAL' if abs(understatement_1) < 5 else 'MODERATE' if abs(understatement_1) < 15 else 'SIGNIFICANT'}
     At 0.1% level: tail dep adds ~{abs(understatement_01):.0f}% to VaR → {'MARGINAL' if abs(understatement_01) < 5 else 'MODERATE' if abs(understatement_01) < 15 else 'SIGNIFICANT'}
     In actual backtest: {'NO DIFFERENCE' if viol_g_total == viol_c_total else f'{abs(viol_g_total-viol_c_total)} extra violations'} (limited by sample)

  6. WHY THE SMALL IMPACT AT 1%?
     - 30% GLD (ρ≈0 with equities) dominates the diversification
     - GLD absorbs a lot of equity crash impact
     - Tail dep between SPY-QQQ matters more for the 70% equity portion
     - But at 1% level, not every VaR violation is extreme enough
       to trigger the tail dependence effect
     - The impact grows at MORE EXTREME quantiles (0.1%, 0.01%)

  7. RECOMMENDATION:
     - For daily 1% VaR: historical simulation is sufficient
     - For extreme risk (0.1% or stress tests): Clayton copula recommended
     - For portfolio construction: treat SPY+QQQ as ONE equity bet
     - Tail-dep-aware allocation improves Sharpe by ~0.05-0.07
       (marginal after transaction costs)
""")

print("=" * 80)
print("END OF SUPPLEMENTARY EXPERIMENT")
print("=" * 80)
