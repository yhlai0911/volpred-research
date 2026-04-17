#!/usr/bin/env python3
"""
K195: Deep Dive into Copula Tail Dependence — Multi-Pair Extension
[提出: 用戶, 執行: Claude]

Background: K193 found SPY-GLD TDA passes Harvey threshold (partial r|VIX = 0.179, t=12.93).
This is the FIRST crack in VIX sufficient statistic. We need to verify this is not a fluke.

Methodology:
1. Compute rolling 252-day empirical tail dependence for ALL pairs (66 pairs from 12 assets)
2. For each pair: TDA = λ_L(q=0.10) - λ_U(q=0.10)
3. Partial correlation of TDA with SPY future 22-day RV, controlling for VIX
4. Rank pairs by |partial r| — which pairs carry the strongest signal?
5. Multi-pair GARCH-X: Use top-3 TDA features as regressors
6. Cross-validation: train on 2016-2022, test on 2023-2024
7. Does TDA signal survive multiple testing correction (Bonferroni for 66 pairs)?

Data: 12 assets from yfinance: SPY, QQQ, IWM, EEM, GLD, TLT, IEF, XLE, XLF, XLK, XLV, BTC-USD
OOS: 2023-2024

Statistical requirements: Bonferroni correction for 66 tests, DM test, Harvey threshold.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.optimize import minimize
from itertools import combinations
import warnings
import json
import os
from datetime import datetime

warnings.filterwarnings("ignore")

# ============================================================
# CONFIGURATION
# ============================================================
ASSETS = ["SPY", "QQQ", "IWM", "EEM", "GLD", "TLT", "IEF", "XLE", "XLF", "XLK", "XLV", "BTC-USD"]
START_DATE = "2014-01-01"  # enough history for 252-day rolling + train period
END_DATE = "2025-01-01"
TRAIN_START = "2016-01-01"
TRAIN_END = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
ROLLING_WINDOW = 252  # 1 year for tail dependence estimation
TAIL_QUANTILE = 0.10  # 10th percentile for tail dependence
FWD_RV_DAYS = 22  # 22-day forward realized vol
BONFERRONI_N = 66  # C(12,2) = 66 pairs
HARVEY_T = 3.0  # Harvey (2016) threshold for multiple testing

print("=" * 80)
print("K195: Deep Dive into Copula Tail Dependence — Multi-Pair Extension")
print("=" * 80)
print(f"Assets: {len(ASSETS)}")
print(f"Pairs: {BONFERRONI_N}")
print(f"Train: {TRAIN_START} to {TRAIN_END}")
print(f"OOS:   {OOS_START} to {OOS_END}")
print(f"Tail quantile: {TAIL_QUANTILE}")
print(f"Rolling window: {ROLLING_WINDOW} days")

# ============================================================
# 1. DATA LOADING
# ============================================================
print("\n" + "=" * 80)
print("[1] Loading data from yfinance ...")
print("=" * 80)

prices = {}
for asset in ASSETS:
    try:
        df = yf.download(asset, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        prices[asset] = df["Close"]
        print(f"  {asset}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"  {asset}: FAILED - {e}")

# Also download VIX for partial correlation control
vix_df = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_series = vix_df["Close"]
print(f"  VIX: {len(vix_df)} obs")

# Build returns DataFrame
price_df = pd.DataFrame(prices)
price_df = price_df.ffill()  # forward fill for missing days (holidays, BTC weekends)
ret_df = np.log(price_df / price_df.shift(1)).dropna()

# Align VIX
vix_aligned = vix_series.reindex(ret_df.index).ffill()
ret_df = ret_df.loc[vix_aligned.notna()]
vix_aligned = vix_aligned.loc[ret_df.index]

# Compute SPY forward 22-day realized vol (annualized)
spy_ret = ret_df["SPY"]
spy_rv22_fwd = spy_ret.rolling(FWD_RV_DAYS).std().shift(-FWD_RV_DAYS) * np.sqrt(252) * 100

print(f"\nAligned data: {len(ret_df)} obs, {ret_df.index[0].strftime('%Y-%m-%d')} to {ret_df.index[-1].strftime('%Y-%m-%d')}")
print(f"Available assets: {list(ret_df.columns)}")
n_assets = len(ret_df.columns)
n_pairs = n_assets * (n_assets - 1) // 2
print(f"Total pairs: {n_pairs}")

# ============================================================
# 2. COMPUTE ROLLING TAIL DEPENDENCE FOR ALL PAIRS
# ============================================================
print("\n" + "=" * 80)
print("[2] Computing rolling empirical tail dependence for all pairs ...")
print("=" * 80)


def empirical_tail_dependence(u, v, q=0.10):
    """
    Compute empirical lower and upper tail dependence coefficients.

    λ_L(q) = P(U < q | V < q) = P(U < q, V < q) / q
    λ_U(q) = P(U > 1-q | V > 1-q) = P(U > 1-q, V > 1-q) / q

    u, v: uniform marginals (rank-transformed)
    q: quantile threshold
    """
    n = len(u)
    # Lower tail: both below q
    lower_joint = np.sum((u <= q) & (v <= q)) / n
    lambda_L = lower_joint / q

    # Upper tail: both above 1-q
    upper_joint = np.sum((u >= 1 - q) & (v >= 1 - q)) / n
    lambda_U = upper_joint / q

    return lambda_L, lambda_U


def rolling_tda(ret_a, ret_b, window=252, q=0.10):
    """
    Compute rolling Tail Dependence Asymmetry (TDA = λ_L - λ_U)
    using empirical copula on rank-transformed returns.
    """
    n = len(ret_a)
    tda_series = pd.Series(index=ret_a.index, dtype=float)
    lambda_l_series = pd.Series(index=ret_a.index, dtype=float)
    lambda_u_series = pd.Series(index=ret_a.index, dtype=float)

    for i in range(window, n):
        # Window slice
        ra = ret_a.iloc[i - window:i].values
        rb = ret_b.iloc[i - window:i].values

        # Rank transform to uniform marginals
        u = stats.rankdata(ra) / (window + 1)
        v = stats.rankdata(rb) / (window + 1)

        lam_L, lam_U = empirical_tail_dependence(u, v, q)
        tda_series.iloc[i] = lam_L - lam_U
        lambda_l_series.iloc[i] = lam_L
        lambda_u_series.iloc[i] = lam_U

    return tda_series, lambda_l_series, lambda_u_series


# Generate all pairs
asset_list = list(ret_df.columns)
all_pairs = list(combinations(asset_list, 2))
print(f"Computing TDA for {len(all_pairs)} pairs with {ROLLING_WINDOW}-day rolling window ...")

tda_dict = {}
lambda_l_dict = {}
lambda_u_dict = {}

for idx, (a1, a2) in enumerate(all_pairs):
    pair_key = f"{a1}_{a2}"
    tda, lam_l, lam_u = rolling_tda(ret_df[a1], ret_df[a2], ROLLING_WINDOW, TAIL_QUANTILE)
    tda_dict[pair_key] = tda
    lambda_l_dict[pair_key] = lam_l
    lambda_u_dict[pair_key] = lam_u
    if (idx + 1) % 10 == 0:
        print(f"  ... {idx + 1}/{len(all_pairs)} pairs done")

tda_df = pd.DataFrame(tda_dict)
print(f"TDA DataFrame: {tda_df.shape}")
print(f"Non-null observations: {tda_df.dropna().shape[0]}")

# ============================================================
# 3. PARTIAL CORRELATION: TDA vs SPY Forward RV, controlling for VIX
# ============================================================
print("\n" + "=" * 80)
print("[3] Partial correlation of TDA with SPY 22-day forward RV, controlling for VIX ...")
print("=" * 80)


def partial_correlation(x, y, z):
    """
    Partial correlation of x and y, controlling for z.
    Uses regression residuals method.
    Returns (partial_r, t_stat, p_value, n)
    """
    # Remove NaN
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    n = len(x)
    if n < 30:
        return np.nan, np.nan, np.nan, n

    # Regress x on z, get residuals
    z_with_const = np.column_stack([np.ones(n), z])
    beta_xz = np.linalg.lstsq(z_with_const, x, rcond=None)[0]
    resid_x = x - z_with_const @ beta_xz

    # Regress y on z, get residuals
    beta_yz = np.linalg.lstsq(z_with_const, y, rcond=None)[0]
    resid_y = y - z_with_const @ beta_yz

    # Correlation of residuals
    r = np.corrcoef(resid_x, resid_y)[0, 1]
    # t-test with n-3 dof (controlling for 1 variable)
    t_stat = r * np.sqrt((n - 3) / (1 - r ** 2)) if abs(r) < 1 else np.inf
    p_value = 2 * stats.t.sf(abs(t_stat), df=n - 3)

    return r, t_stat, p_value, n


# Full sample analysis first
results_full = []
for pair_key in tda_df.columns:
    tda_vals = tda_df[pair_key].values
    rv_vals = spy_rv22_fwd.reindex(tda_df.index).values
    vix_vals = vix_aligned.reindex(tda_df.index).values

    r, t, p, n = partial_correlation(tda_vals, rv_vals, vix_vals)
    results_full.append({
        "pair": pair_key,
        "partial_r": r,
        "t_stat": t,
        "p_value": p,
        "n_obs": n,
        "bonferroni_p": min(p * BONFERRONI_N, 1.0) if np.isfinite(p) else np.nan,
        "passes_bonferroni": (p * BONFERRONI_N < 0.05) if np.isfinite(p) else False,
        "passes_harvey": abs(t) > HARVEY_T if np.isfinite(t) else False,
    })

results_full_df = pd.DataFrame(results_full).sort_values("t_stat", key=abs, ascending=False)

print("\n=== FULL SAMPLE: Top 20 pairs by |partial r(TDA, RV_fwd | VIX)| ===")
print(f"{'Pair':<18} {'partial_r':>10} {'t-stat':>8} {'p-value':>10} {'Bonf_p':>10} {'Harvey':>7} {'Bonf':>6} {'N':>5}")
print("-" * 85)
for _, row in results_full_df.head(20).iterrows():
    print(f"{row['pair']:<18} {row['partial_r']:>10.4f} {row['t_stat']:>8.2f} {row['p_value']:>10.2e} "
          f"{row['bonferroni_p']:>10.2e} {'PASS' if row['passes_harvey'] else 'fail':>7} "
          f"{'PASS' if row['passes_bonferroni'] else 'fail':>6} {row['n_obs']:>5.0f}")

n_harvey = results_full_df["passes_harvey"].sum()
n_bonferroni = results_full_df["passes_bonferroni"].sum()
print(f"\n  Pairs passing Harvey (|t|>3.0): {n_harvey}/{len(all_pairs)}")
print(f"  Pairs passing Bonferroni (p*66<0.05): {n_bonferroni}/{len(all_pairs)}")

# ============================================================
# 4. TRAIN vs OOS SPLIT — Verify signal stability
# ============================================================
print("\n" + "=" * 80)
print("[4] Train (2016-2022) vs OOS (2023-2024) split ...")
print("=" * 80)

# Train period
train_mask = (tda_df.index >= TRAIN_START) & (tda_df.index <= TRAIN_END)
oos_mask = (tda_df.index >= OOS_START) & (tda_df.index <= OOS_END)

results_train = []
results_oos = []

for pair_key in tda_df.columns:
    tda_vals_train = tda_df.loc[train_mask, pair_key].values
    rv_vals_train = spy_rv22_fwd.reindex(tda_df.index).loc[train_mask].values
    vix_vals_train = vix_aligned.reindex(tda_df.index).loc[train_mask].values

    r_tr, t_tr, p_tr, n_tr = partial_correlation(tda_vals_train, rv_vals_train, vix_vals_train)
    results_train.append({
        "pair": pair_key,
        "partial_r_train": r_tr,
        "t_stat_train": t_tr,
        "p_value_train": p_tr,
        "n_train": n_tr,
    })

    tda_vals_oos = tda_df.loc[oos_mask, pair_key].values
    rv_vals_oos = spy_rv22_fwd.reindex(tda_df.index).loc[oos_mask].values
    vix_vals_oos = vix_aligned.reindex(tda_df.index).loc[oos_mask].values

    r_oos, t_oos, p_oos, n_oos = partial_correlation(tda_vals_oos, rv_vals_oos, vix_vals_oos)
    results_oos.append({
        "pair": pair_key,
        "partial_r_oos": r_oos,
        "t_stat_oos": t_oos,
        "p_value_oos": p_oos,
        "n_oos": n_oos,
    })

train_df = pd.DataFrame(results_train)
oos_df = pd.DataFrame(results_oos)
combined_df = train_df.merge(oos_df, on="pair")
combined_df["sign_consistent"] = (
    np.sign(combined_df["partial_r_train"]) == np.sign(combined_df["partial_r_oos"])
)
combined_df["abs_t_train"] = combined_df["t_stat_train"].abs()
combined_df["abs_t_oos"] = combined_df["t_stat_oos"].abs()
combined_df["oos_passes_harvey"] = combined_df["abs_t_oos"] > HARVEY_T
combined_df["oos_bonferroni_p"] = np.minimum(combined_df["p_value_oos"] * BONFERRONI_N, 1.0)
combined_df["oos_passes_bonferroni"] = combined_df["oos_bonferroni_p"] < 0.05

combined_df = combined_df.sort_values("abs_t_train", ascending=False)

print("\n=== TRAIN vs OOS: Top 20 pairs by |t_train| ===")
print(f"{'Pair':<18} {'r_train':>8} {'t_train':>8} {'r_oos':>8} {'t_oos':>8} {'Sign':>5} {'Harvey_OOS':>10} {'Bonf_OOS':>9}")
print("-" * 90)
for _, row in combined_df.head(20).iterrows():
    print(f"{row['pair']:<18} {row['partial_r_train']:>8.4f} {row['t_stat_train']:>8.2f} "
          f"{row['partial_r_oos']:>8.4f} {row['t_stat_oos']:>8.2f} "
          f"{'OK' if row['sign_consistent'] else 'FLIP':>5} "
          f"{'PASS' if row['oos_passes_harvey'] else 'fail':>10} "
          f"{'PASS' if row['oos_passes_bonferroni'] else 'fail':>9}")

n_sign_consistent = combined_df["sign_consistent"].sum()
n_oos_harvey = combined_df["oos_passes_harvey"].sum()
n_oos_bonf = combined_df["oos_passes_bonferroni"].sum()
print(f"\n  Sign consistent train→OOS: {n_sign_consistent}/{len(all_pairs)}")
print(f"  OOS passes Harvey: {n_oos_harvey}/{len(all_pairs)}")
print(f"  OOS passes Bonferroni: {n_oos_bonf}/{len(all_pairs)}")

# Cross-period correlation of partial r
valid_both = combined_df.dropna(subset=["partial_r_train", "partial_r_oos"])
if len(valid_both) > 5:
    rho_cross, p_cross = stats.spearmanr(valid_both["partial_r_train"], valid_both["partial_r_oos"])
    print(f"\n  Spearman rank correlation of partial_r (train vs OOS): ρ = {rho_cross:.3f} (p = {p_cross:.4f})")
    if rho_cross > 0.5 and p_cross < 0.05:
        print("  → Cross-period consistency: GOOD (ranks are stable)")
    elif rho_cross > 0:
        print("  → Cross-period consistency: WEAK (some stability)")
    else:
        print("  → Cross-period consistency: NONE (signal not stable)")

# ============================================================
# 5. CATEGORIZE PAIRS BY ASSET CLASS
# ============================================================
print("\n" + "=" * 80)
print("[5] Asset class analysis — which categories carry TDA signal? ...")
print("=" * 80)

equity = {"SPY", "QQQ", "IWM", "EEM", "XLE", "XLF", "XLK", "XLV"}
bond = {"TLT", "IEF"}
commodity = {"GLD"}
crypto = {"BTC-USD"}


def classify_pair(pair_key):
    a1, a2 = pair_key.split("_", 1)
    classes = []
    for a in [a1, a2]:
        if a in equity:
            classes.append("equity")
        elif a in bond:
            classes.append("bond")
        elif a in commodity:
            classes.append("commodity")
        elif a in crypto:
            classes.append("crypto")
    classes.sort()
    return "-".join(classes)


combined_df["pair_type"] = combined_df["pair"].apply(classify_pair)

print("\n=== Signal strength by pair category ===")
print(f"{'Category':<20} {'N':>4} {'Mean|r_train|':>14} {'Mean|r_oos|':>12} {'Harvey_OOS':>10} {'Sign_OK':>8}")
print("-" * 75)
for cat, grp in combined_df.groupby("pair_type"):
    mean_abs_r_train = grp["partial_r_train"].abs().mean()
    mean_abs_r_oos = grp["partial_r_oos"].abs().mean()
    n_harv = grp["oos_passes_harvey"].sum()
    n_sign = grp["sign_consistent"].sum()
    print(f"{cat:<20} {len(grp):>4} {mean_abs_r_train:>14.4f} {mean_abs_r_oos:>12.4f} "
          f"{n_harv:>10} {n_sign:>8}")

# ============================================================
# 6. MULTI-PAIR GARCH-X: Top-3 TDA features as vol regressors
# ============================================================
print("\n" + "=" * 80)
print("[6] Multi-pair GARCH-X with top TDA regressors ...")
print("=" * 80)

# Select top-3 pairs from training period (by |t_stat_train|)
top3_train = combined_df.nlargest(3, "abs_t_train")
top3_pairs = top3_train["pair"].tolist()
print(f"Top-3 TDA pairs (train): {top3_pairs}")
for _, row in top3_train.iterrows():
    print(f"  {row['pair']}: train t={row['t_stat_train']:.2f}, OOS t={row['t_stat_oos']:.2f}")


def garch_x_estimate(returns, X_regressors=None, omega_init=0.00001, alpha_init=0.05,
                     beta_init=0.90, gamma_init=0.05, delta_inits=None):
    """
    GJR-GARCH(1,1)-X model via MLE.
    h_t = omega + alpha*e²_{t-1} + gamma*e²_{t-1}*I(e<0) + beta*h_{t-1} + delta'*X_{t-1}

    Returns: dict with parameters, log-likelihood, conditional variances
    """
    T = len(returns)
    r = returns.values if hasattr(returns, 'values') else np.array(returns)

    if X_regressors is not None:
        X = X_regressors.values if hasattr(X_regressors, 'values') else np.array(X_regressors)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        n_x = X.shape[1]
    else:
        X = None
        n_x = 0

    def neg_log_lik(params):
        omega = params[0]
        alpha = params[1]
        beta = params[2]
        gamma = params[3]
        deltas = params[4:4 + n_x] if n_x > 0 else []

        h = np.zeros(T)
        h[0] = np.var(r)

        for t in range(1, T):
            leverage = r[t - 1] ** 2 * (r[t - 1] < 0)
            h[t] = omega + alpha * r[t - 1] ** 2 + gamma * leverage + beta * h[t - 1]
            if n_x > 0:
                for k in range(n_x):
                    xval = X[t - 1, k] if np.isfinite(X[t - 1, k]) else 0.0
                    h[t] += deltas[k] * xval
            h[t] = max(h[t], 1e-10)

        # Gaussian log-likelihood
        ll = -0.5 * np.sum(np.log(h[1:]) + r[1:] ** 2 / h[1:])
        return -ll

    # Initial parameters
    p0 = [omega_init, alpha_init, beta_init, gamma_init]
    bounds = [(1e-8, 0.01), (0.001, 0.5), (0.5, 0.999), (0.0, 0.5)]
    if n_x > 0:
        for _ in range(n_x):
            p0.append(0.0)
            bounds.append((-0.001, 0.001))

    try:
        result = minimize(neg_log_lik, p0, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 5000, 'ftol': 1e-12})
        params = result.x
        ll = -result.fun

        # Reconstruct h series
        omega, alpha, beta, gamma = params[:4]
        deltas = params[4:4 + n_x]
        h = np.zeros(T)
        h[0] = np.var(r)
        for t in range(1, T):
            leverage = r[t - 1] ** 2 * (r[t - 1] < 0)
            h[t] = omega + alpha * r[t - 1] ** 2 + gamma * leverage + beta * h[t - 1]
            if n_x > 0:
                for k in range(n_x):
                    xval = X[t - 1, k] if np.isfinite(X[t - 1, k]) else 0.0
                    h[t] += deltas[k] * xval
                h[t] = max(h[t], 1e-10)

        return {
            "omega": omega, "alpha": alpha, "beta": beta, "gamma": gamma,
            "deltas": deltas.tolist() if n_x > 0 else [],
            "loglik": ll, "h": h, "converged": result.success,
            "n_params": len(params),
        }
    except Exception as e:
        return {"error": str(e), "converged": False}


# Prepare data for GARCH-X
train_idx = (ret_df.index >= TRAIN_START) & (ret_df.index <= TRAIN_END)
oos_idx = (ret_df.index >= OOS_START) & (ret_df.index <= OOS_END)

spy_train = ret_df.loc[train_idx, "SPY"]
spy_oos = ret_df.loc[oos_idx, "SPY"]

# TDA features for top pairs
tda_features_train = tda_df.loc[train_idx, top3_pairs].copy()
tda_features_oos = tda_df.loc[oos_idx, top3_pairs].copy()

# Fill NaN with 0 (beginning of rolling window)
tda_features_train = tda_features_train.fillna(0)
tda_features_oos = tda_features_oos.fillna(0)

# Model 1: Standard GJR-GARCH (baseline)
print("\n--- Model 1: Standard GJR-GARCH (baseline) ---")
result_base = garch_x_estimate(spy_train)
if result_base.get("converged"):
    print(f"  omega={result_base['omega']:.6f}, alpha={result_base['alpha']:.4f}, "
          f"beta={result_base['beta']:.4f}, gamma={result_base['gamma']:.4f}")
    print(f"  LogLik={result_base['loglik']:.2f}")
else:
    print(f"  Failed: {result_base.get('error', 'did not converge')}")

# Model 2: GJR-GARCH-X with top-3 TDA
print("\n--- Model 2: GJR-GARCH-X with top-3 TDA regressors ---")
result_x = garch_x_estimate(spy_train, tda_features_train)
if result_x.get("converged"):
    print(f"  omega={result_x['omega']:.6f}, alpha={result_x['alpha']:.4f}, "
          f"beta={result_x['beta']:.4f}, gamma={result_x['gamma']:.4f}")
    for i, pair in enumerate(top3_pairs):
        print(f"  delta[{pair}]={result_x['deltas'][i]:.8f}")
    print(f"  LogLik={result_x['loglik']:.2f}")

    # LR test: 2*(LL_x - LL_base) ~ chi2(3)
    lr_stat = 2 * (result_x['loglik'] - result_base['loglik'])
    lr_pval = 1 - stats.chi2.cdf(lr_stat, df=3)
    print(f"\n  LR test: stat={lr_stat:.4f}, p={lr_pval:.4e} (df=3)")
    if lr_pval < 0.05:
        print("  → TDA regressors SIGNIFICANTLY improve GARCH (p<0.05)")
    else:
        print("  → TDA regressors do NOT significantly improve GARCH")
else:
    print(f"  Failed: {result_x.get('error', 'did not converge')}")
    lr_stat = np.nan
    lr_pval = np.nan

# ============================================================
# 7. OOS FORECASTING: GARCH vs GARCH-X
# ============================================================
print("\n" + "=" * 80)
print("[7] OOS forecasting comparison (2023-2024) ...")
print("=" * 80)


def qlike_loss(h_pred, rv_actual):
    """QLIKE loss: sum(log(h) + rv²/h)"""
    mask = np.isfinite(h_pred) & np.isfinite(rv_actual) & (h_pred > 0)
    h = h_pred[mask]
    r2 = rv_actual[mask] ** 2
    return np.mean(np.log(h) + r2 / h)


def mse_loss(h_pred, rv_actual):
    """MSE loss: mean((h - rv²)²)"""
    mask = np.isfinite(h_pred) & np.isfinite(rv_actual)
    return np.mean((h_pred[mask] - rv_actual[mask] ** 2) ** 2)


def diebold_mariano(loss1, loss2, h=1):
    """
    Diebold-Mariano test for equal predictive accuracy.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Returns t_stat, p_value (two-sided)
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * (1 - k / h) * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0

    t_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return t_stat, p_value


# Rolling OOS forecast: re-estimate every 22 days
oos_dates = ret_df.loc[oos_idx].index
n_oos = len(oos_dates)

h_base_oos = np.full(n_oos, np.nan)
h_x_oos = np.full(n_oos, np.nan)
rv_oos = spy_oos.values ** 2  # squared return as RV proxy

# Use expanding window from TRAIN_START
print(f"OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
print(f"OOS observations: {n_oos}")

# For efficiency, estimate once on full training data, then forecast forward
if result_base.get("converged") and result_x.get("converged"):
    # Forecast using last h from training period and OOS returns
    # Baseline GARCH
    omega_b, alpha_b, beta_b, gamma_b = result_base['omega'], result_base['alpha'], result_base['beta'], result_base['gamma']
    h_prev = result_base['h'][-1]
    r_prev = spy_train.iloc[-1]

    all_returns_oos = spy_oos.values
    for t in range(n_oos):
        leverage = r_prev ** 2 * (r_prev < 0)
        h_new = omega_b + alpha_b * r_prev ** 2 + gamma_b * leverage + beta_b * h_prev
        h_new = max(h_new, 1e-10)
        h_base_oos[t] = h_new
        h_prev = h_new
        r_prev = all_returns_oos[t]

    # GARCH-X
    omega_x, alpha_x, beta_x, gamma_x = result_x['omega'], result_x['alpha'], result_x['beta'], result_x['gamma']
    deltas = result_x['deltas']
    h_prev = result_x['h'][-1]
    r_prev = spy_train.iloc[-1]
    x_prev = tda_features_train.iloc[-1].values

    tda_oos_vals = tda_features_oos.values
    for t in range(n_oos):
        leverage = r_prev ** 2 * (r_prev < 0)
        h_new = omega_x + alpha_x * r_prev ** 2 + gamma_x * leverage + beta_x * h_prev
        for k in range(len(deltas)):
            xv = x_prev[k] if np.isfinite(x_prev[k]) else 0.0
            h_new += deltas[k] * xv
        h_new = max(h_new, 1e-10)
        h_x_oos[t] = h_new
        h_prev = h_new
        r_prev = all_returns_oos[t]
        if t < n_oos - 1:
            x_prev = tda_oos_vals[t]

    # Compute losses
    ql_base = np.log(h_base_oos) + rv_oos / h_base_oos
    ql_x = np.log(h_x_oos) + rv_oos / h_x_oos

    qlike_base = np.mean(ql_base[np.isfinite(ql_base)])
    qlike_x = np.mean(ql_x[np.isfinite(ql_x)])

    mse_base_val = np.mean((h_base_oos - rv_oos) ** 2)
    mse_x_val = np.mean((h_x_oos - rv_oos) ** 2)

    print(f"\n  {'Metric':<15} {'GJR-GARCH':>12} {'GJR-GARCH-X':>14} {'Diff':>10} {'Better':>8}")
    print(f"  {'-' * 65}")
    print(f"  {'QLIKE':<15} {qlike_base:>12.6f} {qlike_x:>14.6f} {qlike_x - qlike_base:>10.6f} "
          f"{'GARCH-X' if qlike_x < qlike_base else 'GARCH':>8}")
    print(f"  {'MSE':<15} {mse_base_val:>12.4e} {mse_x_val:>14.4e} {mse_x_val - mse_base_val:>10.4e} "
          f"{'GARCH-X' if mse_x_val < mse_base_val else 'GARCH':>8}")

    # DM test
    dm_t, dm_p = diebold_mariano(ql_base, ql_x, h=22)
    print(f"\n  DM test (QLIKE): t={dm_t:.3f}, p={dm_p:.4f}")
    if dm_p < 0.05:
        winner = "GARCH-X" if dm_t > 0 else "GARCH"
        print(f"  → {winner} SIGNIFICANTLY better at QLIKE (p<0.05)")
    else:
        print("  → No significant difference in forecast accuracy")

    dm_t_mse, dm_p_mse = diebold_mariano(
        (h_base_oos - rv_oos) ** 2,
        (h_x_oos - rv_oos) ** 2,
        h=22
    )
    print(f"  DM test (MSE):   t={dm_t_mse:.3f}, p={dm_p_mse:.4f}")
else:
    print("  Skipping OOS comparison — model estimation failed")
    dm_t, dm_p = np.nan, np.nan
    dm_t_mse, dm_p_mse = np.nan, np.nan
    qlike_base, qlike_x = np.nan, np.nan

# ============================================================
# 8. ROBUSTNESS: Alternative tail quantiles
# ============================================================
print("\n" + "=" * 80)
print("[8] Robustness: TDA with alternative tail quantiles ...")
print("=" * 80)

# Check if top pair from full sample is robust to quantile choice
top_pair = results_full_df.iloc[0]["pair"]
print(f"Testing robustness for top pair: {top_pair}")

quantiles_to_test = [0.05, 0.10, 0.15, 0.20]
print(f"\n{'q':<6} {'partial_r (full)':>16} {'t_stat':>8} {'p_value':>10} {'partial_r (OOS)':>16} {'t_OOS':>8}")
print("-" * 70)

a1, a2 = top_pair.split("_", 1)
for q in quantiles_to_test:
    tda_q, _, _ = rolling_tda(ret_df[a1], ret_df[a2], ROLLING_WINDOW, q)

    # Full sample
    r_full, t_full, p_full, _ = partial_correlation(
        tda_q.values,
        spy_rv22_fwd.reindex(tda_q.index).values,
        vix_aligned.reindex(tda_q.index).values
    )

    # OOS only
    tda_q_oos = tda_q.loc[oos_mask]
    r_oos, t_oos, p_oos, _ = partial_correlation(
        tda_q_oos.values,
        spy_rv22_fwd.reindex(tda_q_oos.index).values,
        vix_aligned.reindex(tda_q_oos.index).values
    )

    print(f"{q:<6.2f} {r_full:>16.4f} {t_full:>8.2f} {p_full:>10.2e} {r_oos:>16.4f} {t_oos:>8.2f}")

# ============================================================
# 9. DIRECTION & INTERPRETATION: What drives TDA?
# ============================================================
print("\n" + "=" * 80)
print("[9] Interpreting TDA: Direction and economic meaning ...")
print("=" * 80)

# For top-5 pairs: show mean TDA, mean λ_L, mean λ_U
top5_full = results_full_df.head(5)
print(f"\n{'Pair':<18} {'Mean TDA':>10} {'Mean λ_L':>10} {'Mean λ_U':>10} {'TDA sign':>10} {'Interpretation'}")
print("-" * 90)
for _, row in top5_full.iterrows():
    pair_key = row['pair']
    mean_tda = tda_df[pair_key].mean()
    mean_ll = lambda_l_dict[pair_key].mean()
    mean_lu = lambda_u_dict[pair_key].mean()
    direction = "Left > Right" if mean_tda > 0 else "Right > Left"
    interpretation = ""
    if mean_tda > 0:
        interpretation = "Crash co-move > Rally co-move"
    else:
        interpretation = "Rally co-move > Crash co-move"
    print(f"{pair_key:<18} {mean_tda:>10.4f} {mean_ll:>10.4f} {mean_lu:>10.4f} "
          f"{direction:>10} {interpretation}")

# Correlation between TDA level and VIX
for _, row in top5_full.head(3).iterrows():
    pair_key = row['pair']
    tda_vals = tda_df[pair_key].dropna()
    vix_vals = vix_aligned.reindex(tda_vals.index)
    mask = np.isfinite(tda_vals) & np.isfinite(vix_vals)
    if mask.sum() > 30:
        r, p = stats.pearsonr(tda_vals[mask], vix_vals[mask])
        print(f"  corr(TDA_{pair_key}, VIX) = {r:.3f} (p={p:.4e})")

# ============================================================
# 10. SUMMARY & VERDICT
# ============================================================
print("\n" + "=" * 80)
print("[10] SUMMARY & VERDICT")
print("=" * 80)

# Count surviving signals
n_full_harvey = results_full_df["passes_harvey"].sum()
n_full_bonf = results_full_df["passes_bonferroni"].sum()

print(f"""
EXPERIMENT K195: Copula Tail Dependence Asymmetry — Multi-Pair Deep Dive
========================================================================

DATA:
  - {n_assets} assets, {n_pairs} pairs
  - Training: {TRAIN_START} to {TRAIN_END}
  - OOS: {OOS_START} to {OOS_END}
  - Rolling window: {ROLLING_WINDOW} days, tail quantile: {TAIL_QUANTILE}

FULL SAMPLE SCREENING (partial r of TDA with SPY RV_fwd | VIX):
  - Pairs passing Harvey (|t|>3.0): {n_full_harvey}/{n_pairs}
  - Pairs passing Bonferroni (p*{BONFERRONI_N}<0.05): {n_full_bonf}/{n_pairs}
""")

# Top signal
if len(results_full_df) > 0:
    best = results_full_df.iloc[0]
    print(f"  Top pair: {best['pair']}")
    print(f"    Full sample: partial r = {best['partial_r']:.4f}, t = {best['t_stat']:.2f}")

# OOS stability
if len(combined_df) > 0:
    print(f"\nTRAIN → OOS STABILITY:")
    print(f"  Sign consistent: {n_sign_consistent}/{n_pairs}")
    print(f"  OOS passes Harvey: {n_oos_harvey}/{n_pairs}")
    print(f"  OOS passes Bonferroni: {n_oos_bonf}/{n_pairs}")

# GARCH-X results
if not np.isnan(lr_pval if isinstance(lr_pval, float) else 0):
    print(f"\nGARCH-X WITH TOP-3 TDA REGRESSORS:")
    print(f"  LR test: stat={lr_stat:.4f}, p={lr_pval:.4e}")
    print(f"  OOS QLIKE: GARCH={qlike_base:.6f}, GARCH-X={qlike_x:.6f}")
    if np.isfinite(dm_t):
        print(f"  DM test (QLIKE): t={dm_t:.3f}, p={dm_p:.4f}")
    if np.isfinite(dm_t_mse):
        print(f"  DM test (MSE): t={dm_t_mse:.3f}, p={dm_p_mse:.4f}")

# Final verdict
print("\n" + "=" * 40)
print("VERDICT:")
print("=" * 40)

# Determine if TDA is genuine
if n_oos_bonf > 0:
    verdict = "GENUINE"
    detail = f"{n_oos_bonf} pair(s) pass Bonferroni after 66-pair correction in OOS"
elif n_oos_harvey > 0:
    verdict = "PROMISING BUT FRAGILE"
    detail = f"{n_oos_harvey} pair(s) pass Harvey in OOS, but none survive Bonferroni"
elif n_full_bonf > 0 and n_oos_harvey == 0:
    verdict = "IN-SAMPLE ONLY"
    detail = "Signal exists in-sample but vanishes in OOS — likely data mining"
else:
    verdict = "NULL"
    detail = "No pair passes even Harvey threshold"

print(f"  TDA as VIX supplement: {verdict}")
print(f"  Detail: {detail}")

if n_oos_harvey > 0:
    print(f"\n  VIX sufficient statistic status: FIRST CRACK confirmed across multiple pairs")
    print(f"  → TDA captures tail co-movement asymmetry that VIX does not reflect")
else:
    print(f"\n  VIX sufficient statistic status: INTACT")
    print(f"  → K193 SPY-GLD result was likely in-sample overfit across 66 pair tests")

# ============================================================
# SAVE RESULTS
# ============================================================
results_to_save = {
    "experiment": "K195",
    "title": "Copula Tail Dependence Asymmetry — Multi-Pair Deep Dive",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "assets": ASSETS,
        "n_pairs": n_pairs,
        "train_period": f"{TRAIN_START} to {TRAIN_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "rolling_window": ROLLING_WINDOW,
        "tail_quantile": TAIL_QUANTILE,
        "bonferroni_n": BONFERRONI_N,
    },
    "full_sample": {
        "n_harvey": int(n_full_harvey),
        "n_bonferroni": int(n_full_bonf),
        "top5_pairs": results_full_df.head(5)[["pair", "partial_r", "t_stat", "p_value"]].to_dict("records"),
    },
    "oos_stability": {
        "n_sign_consistent": int(n_sign_consistent),
        "n_oos_harvey": int(n_oos_harvey),
        "n_oos_bonferroni": int(n_oos_bonf),
        "cross_period_spearman_rho": float(rho_cross) if 'rho_cross' in dir() else None,
    },
    "garch_x": {
        "lr_stat": float(lr_stat) if np.isfinite(lr_stat) else None,
        "lr_pval": float(lr_pval) if np.isfinite(lr_pval) else None,
        "oos_qlike_base": float(qlike_base) if np.isfinite(qlike_base) else None,
        "oos_qlike_x": float(qlike_x) if np.isfinite(qlike_x) else None,
        "dm_t_qlike": float(dm_t) if np.isfinite(dm_t) else None,
        "dm_p_qlike": float(dm_p) if np.isfinite(dm_p) else None,
    },
    "verdict": verdict,
    "verdict_detail": detail,
}

save_path = os.path.join(os.path.dirname(__file__), "k195_tda_deep_dive_results.json")
with open(save_path, "w") as f:
    json.dump(results_to_save, f, indent=2, default=str)
print(f"\nResults saved to {save_path}")

# Also save full pair ranking for reference
pair_ranking = combined_df[["pair", "pair_type", "partial_r_train", "t_stat_train",
                             "partial_r_oos", "t_stat_oos", "sign_consistent",
                             "oos_passes_harvey", "oos_passes_bonferroni"]].to_dict("records")
ranking_path = os.path.join(os.path.dirname(__file__), "k195_pair_ranking.json")
with open(ranking_path, "w") as f:
    json.dump(pair_ranking, f, indent=2, default=str)
print(f"Full pair ranking saved to {ranking_path}")
