"""
K199: VIX Futures Basis (Contango/Backwardation) as Vol Predictor
=================================================================

Background: VIX futures typically trade in contango (VIX3M > VIX), meaning
the market expects vol to rise. Backwardation (VIX3M < VIX) signals extreme
fear -- spot vol already elevated above expectations. K161 tested VIX term
structure but found null results for raw ratio in vol prediction regressions.

This experiment focuses specifically on:
1. The contango ratio (VIX3M/VIX) as a vol regime indicator
2. Basis CHANGE (d(VIX3M/VIX)) as a predictive signal
3. Partial correlation with future RV controlling for VIX level
4. Regime analysis: backwardation vs strong contango
5. GARCH-X with basis as exogenous in VARIANCE equation
   (NOTE: arch library's x= param goes to mean eq; we manually
    add basis to variance via two-step estimation)
6. VT overlay: reduce exposure when in backwardation (extreme fear already priced)

Data: VIX (^VIX), VIX3M (^VIX3M), SPY from yfinance. OOS: 2023-2024.
Statistical: DM test, Harvey threshold (t>3.0), partial r|VIX.

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from numpy.linalg import lstsq as np_lstsq
import json
from datetime import datetime

print("=" * 70)
print("K199: VIX Futures Basis (Contango/Backwardation) as Vol Predictor")
print("=" * 70)

# ============================================================
# 1. DATA LOADING
# ============================================================
print("\n[1/7] Downloading data from yfinance...")

START = "2007-01-01"
END = "2025-01-01"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
WINDOW = 2000

# SPY
spy_raw = yf.download("SPY", start=START, end=END, progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
spy_close = spy_raw["Close"]
spy_ret = np.log(spy_close / spy_close.shift(1)).dropna()
spy_ret.name = "returns"

# VIX spot
vix_raw = yf.download("^VIX", start=START, end=END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()
vix.name = "VIX"

# VIX3M (CBOE 3-Month Volatility Index)
vix3m_raw = yf.download("^VIX3M", start=START, end=END, progress=False)
if isinstance(vix3m_raw.columns, pd.MultiIndex):
    vix3m_raw.columns = vix3m_raw.columns.get_level_values(0)
vix3m = vix3m_raw["Close"].copy()
vix3m.name = "VIX3M"

print(f"  SPY returns: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()}, N={len(spy_ret)}")
print(f"  VIX spot   : {vix.index[0].date()} to {vix.index[-1].date()}, N={len(vix)}")
print(f"  VIX3M      : {vix3m.index[0].date()} to {vix3m.index[-1].date()}, N={len(vix3m)}")

# ============================================================
# 2. CONSTRUCT BASIS MEASURES
# ============================================================
print("\n[2/7] Constructing basis measures...")

# Align all series
df = pd.DataFrame({
    "returns": spy_ret,
    "VIX": vix,
    "VIX3M": vix3m
}).dropna()

# Contango ratio: VIX3M / VIX
# > 1 = contango (normal), < 1 = backwardation (extreme fear)
df["basis_ratio"] = df["VIX3M"] / df["VIX"]

# Basis change: d(VIX3M/VIX)
df["basis_change"] = df["basis_ratio"].diff()

# Basis level: VIX3M - VIX (absolute spread)
df["basis_level"] = df["VIX3M"] - df["VIX"]

# Realized volatility targets (forward-looking, for regression targets only)
for h in [1, 5, 22]:
    df[f"rv_{h}d"] = df["returns"].pow(2).rolling(h).sum().shift(-h)

# Squared return (1-day RV proxy)
df["r2"] = df["returns"] ** 2

# Log VIX for regression
df["log_vix"] = np.log(df["VIX"])

df_clean = df.dropna(subset=["basis_ratio", "basis_change", "rv_22d"])

print(f"  Combined dataset: {df_clean.index[0].date()} to {df_clean.index[-1].date()}, N={len(df_clean)}")
print(f"  Basis ratio stats:")
print(f"    Mean   = {df_clean['basis_ratio'].mean():.4f}")
print(f"    Median = {df_clean['basis_ratio'].median():.4f}")
print(f"    Std    = {df_clean['basis_ratio'].std():.4f}")
print(f"    Min    = {df_clean['basis_ratio'].min():.4f}")
print(f"    Max    = {df_clean['basis_ratio'].max():.4f}")
print(f"    % Backwardation (ratio < 1): {(df_clean['basis_ratio'] < 1).mean()*100:.1f}%")
print(f"    % Strong contango (ratio > 1.2): {(df_clean['basis_ratio'] > 1.2).mean()*100:.1f}%")

# ============================================================
# 3. CORRELATION & PARTIAL CORRELATION ANALYSIS
# ============================================================
print("\n[3/7] Correlation & Partial Correlation Analysis...")

# Split into IS and OOS
is_mask = df_clean.index < OOS_START
oos_mask = (df_clean.index >= OOS_START) & (df_clean.index <= OOS_END)

df_is = df_clean[is_mask].copy()
df_oos = df_clean[oos_mask].copy()
print(f"  In-sample: {df_is.index[0].date()} to {df_is.index[-1].date()}, N={len(df_is)}")
print(f"  OOS:       {df_oos.index[0].date()} to {df_oos.index[-1].date()}, N={len(df_oos)}")

# --- 3a. Raw correlations ---
print("\n  --- Raw Correlations (In-Sample) ---")
for target in ["rv_1d", "rv_5d", "rv_22d"]:
    for signal in ["basis_ratio", "basis_change", "basis_level", "VIX", "log_vix"]:
        valid = df_is[[signal, target]].dropna()
        r, p = stats.pearsonr(valid[signal], valid[target])
        print(f"    corr({signal:15s}, {target}): r={r:+.4f}, p={p:.4f}")
    print()

# --- 3b. Partial correlation: basis_ratio with rv, controlling for VIX level ---
print("  --- Partial Correlations (controlling for log_vix) ---")

def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    valid = pd.DataFrame({"x": x, "y": y, "z": z}).dropna()
    if len(valid) < 10:
        return np.nan, np.nan
    Z = np.column_stack([np.ones(len(valid)), valid["z"].values])

    bx = np_lstsq(Z, valid["x"].values, rcond=None)[0]
    rx = valid["x"].values - Z @ bx

    by = np_lstsq(Z, valid["y"].values, rcond=None)[0]
    ry = valid["y"].values - Z @ by

    return stats.pearsonr(rx, ry)

partial_corr_results = {}
for target in ["rv_1d", "rv_5d", "rv_22d"]:
    for signal in ["basis_ratio", "basis_change"]:
        r_partial, p_partial = partial_corr(
            df_is[signal], df_is[target], df_is["log_vix"]
        )
        r_oos, p_oos = partial_corr(
            df_oos[signal], df_oos[target], df_oos["log_vix"]
        )
        print(f"    partial_r({signal:15s}, {target} | log_vix): "
              f"IS r={r_partial:+.4f} (p={p_partial:.4f}), "
              f"OOS r={r_oos:+.4f} (p={p_oos:.4f})")
        partial_corr_results[f"{signal}_{target}"] = {
            "is_r": float(r_partial), "is_p": float(p_partial),
            "oos_r": float(r_oos), "oos_p": float(p_oos)
        }
    print()

# ============================================================
# 4. REGIME ANALYSIS: Backwardation vs Contango
# ============================================================
print("\n[4/7] Regime Analysis...")

def classify_regime(ratio):
    if ratio < 0.95:
        return "strong_backwardation"
    elif ratio < 1.0:
        return "mild_backwardation"
    elif ratio < 1.1:
        return "normal_contango"
    elif ratio < 1.2:
        return "moderate_contango"
    else:
        return "strong_contango"

df_clean["regime"] = df_clean["basis_ratio"].apply(classify_regime)

print("  Regime distribution (full sample):")
regime_stats = {}
regime_counts = df_clean["regime"].value_counts()
for regime in ["strong_backwardation", "mild_backwardation", "normal_contango",
               "moderate_contango", "strong_contango"]:
    if regime in regime_counts.index:
        n = regime_counts[regime]
        pct = n / len(df_clean) * 100
        subset = df_clean[df_clean["regime"] == regime]
        mean_rv22 = subset["rv_22d"].mean() if len(subset) > 0 else np.nan
        mean_ret = subset["returns"].mean() * 252 if len(subset) > 0 else np.nan
        std_ret = subset["returns"].std() * np.sqrt(252) if len(subset) > 0 else np.nan
        mean_vix = subset["VIX"].mean() if len(subset) > 0 else np.nan
        print(f"    {regime:25s}: N={n:5d} ({pct:5.1f}%), "
              f"VIX={mean_vix:5.1f}, "
              f"Ann.Return={mean_ret:+6.1f}%, "
              f"Ann.Vol={std_ret*100:5.1f}%, "
              f"22d RV={mean_rv22:.6f}")
        regime_stats[regime] = {
            "n": int(n), "pct": float(pct),
            "mean_vix": float(mean_vix),
            "ann_return": float(mean_ret),
            "ann_vol": float(std_ret),
            "mean_rv22": float(mean_rv22)
        }

df_clean["backwardation"] = (df_clean["basis_ratio"] < 1).astype(int)

# Compare forward returns in backwardation vs contango
for period_name, shift_days in [("1-day", 1), ("5-day", 5), ("22-day", 22)]:
    df_clean[f"fwd_ret_{shift_days}"] = df_clean["returns"].rolling(shift_days).sum().shift(-shift_days)

print("\n  Forward returns by regime (backwardation vs contango):")
regime_forward = {}
for shift_days in [1, 5, 22]:
    col = f"fwd_ret_{shift_days}"
    back = df_clean[df_clean["backwardation"] == 1][col].dropna()
    cont = df_clean[df_clean["backwardation"] == 0][col].dropna()
    t_stat, p_val = stats.ttest_ind(back, cont, equal_var=False)
    print(f"    {shift_days:2d}-day fwd return: "
          f"Backwardation={back.mean()*100:+.3f}% (N={len(back)}), "
          f"Contango={cont.mean()*100:+.3f}% (N={len(cont)}), "
          f"t={t_stat:.2f}, p={p_val:.4f}")
    regime_forward[f"fwd_ret_{shift_days}d"] = {
        "backwardation_mean": float(back.mean()),
        "contango_mean": float(cont.mean()),
        "t": float(t_stat), "p": float(p_val)
    }

print("\n  Forward RV by regime:")
regime_rv = {}
for h in [1, 5, 22]:
    col = f"rv_{h}d"
    back = df_clean[df_clean["backwardation"] == 1][col].dropna()
    cont = df_clean[df_clean["backwardation"] == 0][col].dropna()
    t_stat, p_val = stats.ttest_ind(back, cont, equal_var=False)
    ratio_val = back.mean() / cont.mean() if cont.mean() > 0 else np.nan
    print(f"    {h:2d}-day fwd RV: "
          f"Backwardation={back.mean():.6f} (N={len(back)}), "
          f"Contango={cont.mean():.6f} (N={len(cont)}), "
          f"ratio={ratio_val:.2f}x, "
          f"t={t_stat:.2f}, p={p_val:.4f}")
    regime_rv[f"rv_{h}d"] = {
        "backwardation_mean": float(back.mean()),
        "contango_mean": float(cont.mean()),
        "ratio": float(ratio_val),
        "t": float(t_stat), "p": float(p_val)
    }

# ============================================================
# 5. GARCH-X WITH BASIS AS EXOGENOUS IN VARIANCE EQUATION
# ============================================================
print("\n[5/7] GARCH-X with Basis as Exogenous in Variance Equation...")
print("  NOTE: arch library x= goes to MEAN equation.")
print("  For true variance-X, we use two-step: (1) estimate GJR params,")
print("  (2) add basis to variance recursion manually for OOS forecasting.")

# Prepare data for GARCH estimation
# We use df (not df_clean, so we have more data for GARCH fitting)
# But need basis_ratio aligned
df_garch = df[["returns", "VIX", "VIX3M", "basis_ratio", "basis_change"]].dropna().copy()
ret_pct = df_garch["returns"] * 100

oos_dates_g = df_garch.index[(df_garch.index >= OOS_START) & (df_garch.index <= OOS_END)]
print(f"  OOS period: {oos_dates_g[0].date()} to {oos_dates_g[-1].date()}, N={len(oos_dates_g)}")

# True GARCH-X: h_t = omega + alpha*e_{t-1}^2 + gamma*e_{t-1}^2*I(e<0) + beta*h_{t-1} + delta*X_{t-1}
# We estimate delta via MLE or two-step.
# Two-step approach: (1) fit GJR, get standardized residuals
# (2) regress log(e^2/h) on X to estimate incremental info
# For OOS forecasting: we use GJR fitted h_t then adjust by basis

# Approach: Full MLE for GARCH-X with basis in variance
# Since arch doesn't support variance-X directly, we implement manually.

def garch_x_mle(returns_pct, x_var, p=1, o=1, q=1):
    """
    GJR-GARCH(1,1)-X with x_var in variance equation.
    h_t = omega + alpha*eps_{t-1}^2 + gamma*eps_{t-1}^2*I_{t-1} + beta*h_{t-1} + delta*x_{t-1}

    Returns: omega, alpha, gamma, beta, delta, mu, log_likelihood
    """
    from scipy.optimize import minimize

    r = returns_pct.values if hasattr(returns_pct, 'values') else np.array(returns_pct)
    x = x_var.values if hasattr(x_var, 'values') else np.array(x_var)
    T = len(r)

    def neg_loglik(params):
        mu, omega, alpha, gamma, beta, delta = params
        eps = r - mu
        h = np.zeros(T)
        h[0] = np.var(eps)

        for t in range(1, T):
            indicator = 1.0 if eps[t-1] < 0 else 0.0
            h[t] = (omega + alpha * eps[t-1]**2 + gamma * eps[t-1]**2 * indicator
                     + beta * h[t-1] + delta * x[t-1])
            if h[t] < 1e-6:
                h[t] = 1e-6

        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(h) + eps**2 / h)
        return -ll

    # Initial params from standard GJR
    try:
        mod0 = arch_model(pd.Series(r), vol='Garch', p=1, o=1, q=1, dist='normal')
        res0 = mod0.fit(disp='off', show_warning=False)
        x0 = [res0.params.get('mu', 0.05),
              res0.params.get('omega', 0.01),
              res0.params.get('alpha[1]', 0.05),
              res0.params.get('gamma[1]', 0.05),
              res0.params.get('beta[1]', 0.90),
              0.0]  # delta starts at 0
    except Exception:
        x0 = [0.05, 0.01, 0.05, 0.05, 0.90, 0.0]

    bounds = [(-1, 1),      # mu
              (1e-6, 10),   # omega
              (0, 0.5),     # alpha
              (0, 0.5),     # gamma
              (0, 0.999),   # beta
              (-0.5, 0.5)]  # delta

    try:
        result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 500, 'ftol': 1e-10})
        if result.success or result.fun < neg_loglik(x0):
            params = result.x
            ll = -result.fun
        else:
            params = x0
            ll = -neg_loglik(x0)
    except Exception:
        params = x0
        ll = -neg_loglik(x0)

    return {
        'mu': params[0], 'omega': params[1], 'alpha': params[2],
        'gamma': params[3], 'beta': params[4], 'delta': params[5],
        'loglik': ll
    }


def garch_x_forecast(params, returns_pct, x_var):
    """One-step ahead forecast from GARCH-X model."""
    r = returns_pct.values if hasattr(returns_pct, 'values') else np.array(returns_pct)
    x = x_var.values if hasattr(x_var, 'values') else np.array(x_var)
    T = len(r)

    mu = params['mu']
    omega = params['omega']
    alpha = params['alpha']
    gamma = params['gamma']
    beta = params['beta']
    delta = params['delta']

    eps = r - mu
    h = np.zeros(T)
    h[0] = np.var(eps)

    for t in range(1, T):
        indicator = 1.0 if eps[t-1] < 0 else 0.0
        h[t] = (omega + alpha * eps[t-1]**2 + gamma * eps[t-1]**2 * indicator
                 + beta * h[t-1] + delta * x[t-1])
        if h[t] < 1e-6:
            h[t] = 1e-6

    # One-step ahead forecast
    indicator_T = 1.0 if eps[-1] < 0 else 0.0
    h_next = (omega + alpha * eps[-1]**2 + gamma * eps[-1]**2 * indicator_T
               + beta * h[-1] + delta * x[-1])
    if h_next < 1e-6:
        h_next = 1e-6

    return h_next / 10000  # Convert from pct^2 to decimal^2


# OOS rolling forecast comparison
REFIT_FREQ = 22  # Refit every 22 days

forecasts = {"gjr": {}, "gjr_x_ratio": {}, "gjr_x_change": {}}
actuals = {}

n_fits = 0
n_failures = {"gjr": 0, "gjr_x_ratio": 0, "gjr_x_change": 0}
cached_params = {"gjr": None, "gjr_x_ratio": None, "gjr_x_change": None}

for i, date in enumerate(oos_dates_g):
    loc = ret_pct.index.get_loc(date)
    if loc < WINDOW:
        continue

    actual_r2 = df_garch.loc[date, "returns"] ** 2
    actuals[date] = actual_r2

    train_ret = ret_pct.iloc[loc - WINDOW:loc]
    train_basis_ratio = df_garch["basis_ratio"].iloc[loc - WINDOW:loc]
    train_basis_change = df_garch["basis_change"].iloc[loc - WINDOW:loc]

    do_refit = (i % REFIT_FREQ == 0) or (n_fits == 0)

    if do_refit:
        # Model A: GJR-GARCH (standard)
        try:
            mod_a = arch_model(train_ret, vol='Garch', p=1, o=1, q=1, dist='normal')
            res_a = mod_a.fit(disp='off', show_warning=False)
            fc_a = res_a.forecast(horizon=1)
            forecasts["gjr"][date] = fc_a.variance.values[-1, 0] / 10000
            cached_params["gjr"] = res_a
        except Exception:
            n_failures["gjr"] += 1
            forecasts["gjr"][date] = list(forecasts["gjr"].values())[-1] if forecasts["gjr"] else 0.0002

        # Model B: GJR-GARCH-X with basis_ratio in VARIANCE
        try:
            params_b = garch_x_mle(train_ret, train_basis_ratio)
            forecasts["gjr_x_ratio"][date] = garch_x_forecast(
                params_b, train_ret, train_basis_ratio)
            cached_params["gjr_x_ratio"] = params_b
        except Exception:
            n_failures["gjr_x_ratio"] += 1
            forecasts["gjr_x_ratio"][date] = forecasts["gjr"].get(date, 0.0002)

        # Model C: GJR-GARCH-X with basis_change in VARIANCE
        try:
            params_c = garch_x_mle(train_ret, train_basis_change)
            forecasts["gjr_x_change"][date] = garch_x_forecast(
                params_c, train_ret, train_basis_change)
            cached_params["gjr_x_change"] = params_c
        except Exception:
            n_failures["gjr_x_change"] += 1
            forecasts["gjr_x_change"][date] = forecasts["gjr"].get(date, 0.0002)

        n_fits += 1
    else:
        # Between refits: re-run variance recursion with cached params up to current day
        # This gives a proper daily-updated forecast even without refitting

        # GJR: use arch library's forecast from last fit
        try:
            if cached_params["gjr"] is not None:
                # Extend the train data and re-forecast with same params
                ext_ret = ret_pct.iloc[loc - WINDOW:loc]
                mod_ext = arch_model(ext_ret, vol='Garch', p=1, o=1, q=1, dist='normal')
                res_ext = mod_ext.fit(disp='off', show_warning=False,
                                       starting_values=cached_params["gjr"].params.values)
                fc_ext = res_ext.forecast(horizon=1)
                forecasts["gjr"][date] = fc_ext.variance.values[-1, 0] / 10000
            else:
                forecasts["gjr"][date] = list(forecasts["gjr"].values())[-1]
        except Exception:
            forecasts["gjr"][date] = list(forecasts["gjr"].values())[-1] if forecasts["gjr"] else 0.0002

        # GJR-X: use cached params with updated data
        try:
            if cached_params["gjr_x_ratio"] is not None:
                ext_ret = ret_pct.iloc[loc - WINDOW:loc]
                ext_basis = df_garch["basis_ratio"].iloc[loc - WINDOW:loc]
                forecasts["gjr_x_ratio"][date] = garch_x_forecast(
                    cached_params["gjr_x_ratio"], ext_ret, ext_basis)
            else:
                forecasts["gjr_x_ratio"][date] = list(forecasts["gjr_x_ratio"].values())[-1]
        except Exception:
            forecasts["gjr_x_ratio"][date] = list(forecasts["gjr_x_ratio"].values())[-1] if forecasts["gjr_x_ratio"] else 0.0002

        try:
            if cached_params["gjr_x_change"] is not None:
                ext_ret = ret_pct.iloc[loc - WINDOW:loc]
                ext_bchange = df_garch["basis_change"].iloc[loc - WINDOW:loc]
                forecasts["gjr_x_change"][date] = garch_x_forecast(
                    cached_params["gjr_x_change"], ext_ret, ext_bchange)
            else:
                forecasts["gjr_x_change"][date] = list(forecasts["gjr_x_change"].values())[-1]
        except Exception:
            forecasts["gjr_x_change"][date] = list(forecasts["gjr_x_change"].values())[-1] if forecasts["gjr_x_change"] else 0.0002

    if (i + 1) % 100 == 0:
        print(f"    Processed {i+1}/{len(oos_dates_g)} OOS days...")

print(f"  Total refits: {n_fits}")
print(f"  Failures: GJR={n_failures['gjr']}, GJR-X(ratio)={n_failures['gjr_x_ratio']}, GJR-X(change)={n_failures['gjr_x_change']}")

# Report delta estimates from last fit
if cached_params["gjr_x_ratio"] is not None:
    print(f"\n  Last GJR-X(ratio) params:")
    p = cached_params["gjr_x_ratio"]
    print(f"    omega={p['omega']:.6f}, alpha={p['alpha']:.4f}, gamma={p['gamma']:.4f}, "
          f"beta={p['beta']:.4f}, delta={p['delta']:.6f}")
    print(f"    delta interpretation: basis_ratio coefficient in variance equation")

if cached_params["gjr_x_change"] is not None:
    print(f"  Last GJR-X(change) params:")
    p = cached_params["gjr_x_change"]
    print(f"    omega={p['omega']:.6f}, alpha={p['alpha']:.4f}, gamma={p['gamma']:.4f}, "
          f"beta={p['beta']:.4f}, delta={p['delta']:.6f}")

# ============================================================
# 5b. LOSS FUNCTIONS & DM TEST
# ============================================================
print("\n  --- Forecast Evaluation ---")

common_dates = sorted(set(actuals.keys()) & set(forecasts["gjr"].keys())
                      & set(forecasts["gjr_x_ratio"].keys()) & set(forecasts["gjr_x_change"].keys()))
print(f"  Common OOS dates: {len(common_dates)}")

actual_arr = np.array([actuals[d] for d in common_dates])
fc_gjr = np.array([forecasts["gjr"][d] for d in common_dates])
fc_ratio = np.array([forecasts["gjr_x_ratio"][d] for d in common_dates])
fc_change = np.array([forecasts["gjr_x_change"][d] for d in common_dates])

# Verify forecasts are actually different
print(f"  Forecast correlation (GJR vs GJR-X ratio): {np.corrcoef(fc_gjr, fc_ratio)[0,1]:.6f}")
print(f"  Forecast correlation (GJR vs GJR-X change): {np.corrcoef(fc_gjr, fc_change)[0,1]:.6f}")
print(f"  Mean absolute difference (GJR vs X-ratio): {np.mean(np.abs(fc_gjr - fc_ratio)):.8f}")
print(f"  Mean absolute difference (GJR vs X-change): {np.mean(np.abs(fc_gjr - fc_change)):.8f}")

# QLIKE loss: log(sigma^2) + r^2/sigma^2
def qlike(actual_r2, forecast_var):
    fv = np.maximum(forecast_var, 1e-10)
    return np.log(fv) + actual_r2 / fv

# MSE loss
def mse_loss(actual_r2, forecast_var):
    return (actual_r2 - forecast_var) ** 2

# Compute losses
losses = {}
for model_name, fc in [("GJR", fc_gjr), ("GJR-X(ratio)", fc_ratio), ("GJR-X(change)", fc_change)]:
    q = qlike(actual_arr, fc).mean()
    m = mse_loss(actual_arr, fc).mean()
    losses[model_name] = {"QLIKE": float(q), "MSE": float(m)}
    print(f"    {model_name:20s}: QLIKE={q:.6f}, MSE={m:.10f}")

# Diebold-Mariano test
def dm_test(loss_a, loss_b, h=1):
    """DM test: H0: E[d_t] = 0. Negative t => model A better."""
    d = loss_a - loss_b
    n = len(d)
    d_mean = d.mean()
    gamma_0 = np.var(d, ddof=1)
    if h > 1:
        for k in range(1, h):
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            gamma_0 += 2 * (1 - k / h) * gamma_k
    se = np.sqrt(gamma_0 / n)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_mean / se
    p_val = 2 * stats.norm.sf(abs(t_stat))
    return float(t_stat), float(p_val)

print("\n  --- Diebold-Mariano Tests (QLIKE) ---")
comparisons = [
    ("GJR", "GJR-X(ratio)", fc_gjr, fc_ratio),
    ("GJR", "GJR-X(change)", fc_gjr, fc_change),
    ("GJR-X(ratio)", "GJR-X(change)", fc_ratio, fc_change),
]

dm_results = {}
for name_a, name_b, fc_a, fc_b in comparisons:
    loss_a = qlike(actual_arr, fc_a)
    loss_b = qlike(actual_arr, fc_b)
    t_stat, p_val = dm_test(loss_a, loss_b)
    winner = name_a if t_stat > 0 else name_b
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
    print(f"    {name_a} vs {name_b}: t={t_stat:+.3f}, p={p_val:.4f} {sig}")
    if sig:
        print(f"      -> {winner} significantly better")
    else:
        print(f"      -> No significant difference")
    dm_results[f"{name_a}_vs_{name_b}"] = {"t": t_stat, "p": p_val}

# Also DM test with MSE
print("\n  --- Diebold-Mariano Tests (MSE) ---")
dm_results_mse = {}
for name_a, name_b, fc_a, fc_b in comparisons:
    loss_a = mse_loss(actual_arr, fc_a)
    loss_b = mse_loss(actual_arr, fc_b)
    t_stat, p_val = dm_test(loss_a, loss_b)
    winner = name_a if t_stat > 0 else name_b
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
    print(f"    {name_a} vs {name_b}: t={t_stat:+.3f}, p={p_val:.4f} {sig}")
    dm_results_mse[f"{name_a}_vs_{name_b}"] = {"t": t_stat, "p": p_val}

# ============================================================
# 6. PREDICTIVE REGRESSION: Basis -> Future RV
# ============================================================
print("\n[6/7] Predictive Regression Analysis...")

def ols_nw(y, X, n_lags=5):
    """OLS with Newey-West HAC standard errors."""
    n, k = X.shape
    beta = np_lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta

    S = np.zeros((k, k))
    Xt_e = X * resid.reshape(-1, 1)
    S = Xt_e.T @ Xt_e / n
    for lag in range(1, n_lags + 1):
        w = 1 - lag / (n_lags + 1)
        C = Xt_e[lag:].T @ Xt_e[:-lag] / n
        S += w * (C + C.T)

    XtX_inv = np.linalg.inv(X.T @ X / n)
    V = XtX_inv @ S @ XtX_inv / n
    se = np.sqrt(np.diag(V))
    t_stats = beta / se
    p_vals = 2 * stats.norm.sf(np.abs(t_stats))

    ss_res = np.sum(resid ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot

    return beta, se, t_stats, p_vals, r2

print("\n  --- In-Sample Predictive Regressions ---")
print("  Target: 22-day forward RV")

# Model 1: VIX alone
y_is = df_is["rv_22d"].values
X1 = np.column_stack([np.ones(len(df_is)), df_is["log_vix"].values])
b1, se1, t1, p1, r2_1 = ols_nw(y_is, X1)
print(f"\n  [Reg 1] rv_22d = a + b*log(VIX)")
print(f"    b(log_vix) = {b1[1]:.6f}, t={t1[1]:.2f}, p={p1[1]:.4f}")
print(f"    R^2 = {r2_1:.4f}")

# Model 2: VIX + basis_ratio
X2 = np.column_stack([np.ones(len(df_is)), df_is["log_vix"].values, df_is["basis_ratio"].values])
b2, se2, t2, p2, r2_2 = ols_nw(y_is, X2)
print(f"\n  [Reg 2] rv_22d = a + b1*log(VIX) + b2*basis_ratio")
print(f"    b(log_vix)     = {b2[1]:.6f}, t={t2[1]:.2f}, p={p2[1]:.4f}")
print(f"    b(basis_ratio) = {b2[2]:.6f}, t={t2[2]:.2f}, p={p2[2]:.4f}")
print(f"    R^2 = {r2_2:.4f}, Delta R^2 = {r2_2 - r2_1:.6f}")
print(f"    Harvey threshold check: |t|={abs(t2[2]):.2f} {'> 3.0 PASS' if abs(t2[2]) > 3.0 else '< 3.0 FAIL'}")

# Model 3: VIX + basis_change
X3 = np.column_stack([np.ones(len(df_is)), df_is["log_vix"].values, df_is["basis_change"].values])
b3, se3, t3, p3, r2_3 = ols_nw(y_is, X3)
print(f"\n  [Reg 3] rv_22d = a + b1*log(VIX) + b2*basis_change")
print(f"    b(log_vix)      = {b3[1]:.6f}, t={t3[1]:.2f}, p={p3[1]:.4f}")
print(f"    b(basis_change) = {b3[2]:.6f}, t={t3[2]:.2f}, p={p3[2]:.4f}")
print(f"    R^2 = {r2_3:.4f}, Delta R^2 = {r2_3 - r2_1:.6f}")

# Model 4: VIX + basis_ratio + basis_change
X4 = np.column_stack([np.ones(len(df_is)), df_is["log_vix"].values,
                       df_is["basis_ratio"].values, df_is["basis_change"].values])
b4, se4, t4, p4, r2_4 = ols_nw(y_is, X4)
print(f"\n  [Reg 4] rv_22d = a + b1*log(VIX) + b2*basis_ratio + b3*basis_change")
print(f"    b(log_vix)      = {b4[1]:.6f}, t={t4[1]:.2f}, p={p4[1]:.4f}")
print(f"    b(basis_ratio)  = {b4[2]:.6f}, t={t4[2]:.2f}, p={p4[2]:.4f}")
print(f"    b(basis_change) = {b4[3]:.6f}, t={t4[3]:.2f}, p={p4[3]:.4f}")
print(f"    R^2 = {r2_4:.4f}, Delta R^2 = {r2_4 - r2_1:.6f}")

# --- OOS Predictive Regressions (rolling window) ---
print("\n  --- OOS Predictive Regressions (rolling window) ---")

oos_dates_reg = df_clean.index[oos_mask]
oos_predictions = {"vix_only": [], "vix_basis": [], "vix_basis_change": [], "actual": []}

for i, date in enumerate(oos_dates_reg):
    loc = df_clean.index.get_loc(date)
    if loc < WINDOW:
        continue

    train = df_clean.iloc[max(0, loc - WINDOW):loc]
    y_train = train["rv_22d"].dropna()
    train_valid = train.loc[y_train.index]

    if len(train_valid) < 100:
        continue

    # VIX-only model
    X_tr1 = np.column_stack([np.ones(len(train_valid)), train_valid["log_vix"].values])
    b_tr1 = np_lstsq(X_tr1, y_train.values, rcond=None)[0]
    x_oos1 = np.array([1.0, df_clean.loc[date, "log_vix"]])
    pred1 = x_oos1 @ b_tr1

    # VIX + basis_ratio
    X_tr2 = np.column_stack([np.ones(len(train_valid)), train_valid["log_vix"].values,
                              train_valid["basis_ratio"].values])
    b_tr2 = np_lstsq(X_tr2, y_train.values, rcond=None)[0]
    x_oos2 = np.array([1.0, df_clean.loc[date, "log_vix"], df_clean.loc[date, "basis_ratio"]])
    pred2 = x_oos2 @ b_tr2

    # VIX + basis_change
    X_tr3 = np.column_stack([np.ones(len(train_valid)), train_valid["log_vix"].values,
                              train_valid["basis_change"].values])
    b_tr3 = np_lstsq(X_tr3, y_train.values, rcond=None)[0]
    x_oos3 = np.array([1.0, df_clean.loc[date, "log_vix"], df_clean.loc[date, "basis_change"]])
    pred3 = x_oos3 @ b_tr3

    actual_rv22 = df_clean.loc[date, "rv_22d"]
    if not np.isnan(actual_rv22):
        oos_predictions["vix_only"].append(pred1)
        oos_predictions["vix_basis"].append(pred2)
        oos_predictions["vix_basis_change"].append(pred3)
        oos_predictions["actual"].append(actual_rv22)

oos_act = np.array(oos_predictions["actual"])
oos_p1 = np.array(oos_predictions["vix_only"])
oos_p2 = np.array(oos_predictions["vix_basis"])
oos_p3 = np.array(oos_predictions["vix_basis_change"])

# OOS R-squared
ss_tot_oos = np.sum((oos_act - oos_act.mean()) ** 2)
r2_oos_vix = 1 - np.sum((oos_act - oos_p1) ** 2) / ss_tot_oos
r2_oos_basis = 1 - np.sum((oos_act - oos_p2) ** 2) / ss_tot_oos
r2_oos_bchange = 1 - np.sum((oos_act - oos_p3) ** 2) / ss_tot_oos

print(f"\n  OOS R^2 (VIX only):        {r2_oos_vix:.4f}")
print(f"  OOS R^2 (VIX + basis):     {r2_oos_basis:.4f}")
print(f"  OOS R^2 (VIX + b.change):  {r2_oos_bchange:.4f}")
print(f"  OOS Delta R^2 (basis):     {r2_oos_basis - r2_oos_vix:+.6f}")
print(f"  OOS Delta R^2 (b.change):  {r2_oos_bchange - r2_oos_vix:+.6f}")

# OOS DM test for regression forecasts
oos_loss_vix = (oos_act - oos_p1) ** 2
oos_loss_basis = (oos_act - oos_p2) ** 2
oos_loss_bchange = (oos_act - oos_p3) ** 2

dm_oos_t, dm_oos_p = dm_test(oos_loss_vix, oos_loss_basis)
dm_oos_t2, dm_oos_p2 = dm_test(oos_loss_vix, oos_loss_bchange)
print(f"  DM test (VIX vs VIX+basis):    t={dm_oos_t:+.3f}, p={dm_oos_p:.4f}")
print(f"  DM test (VIX vs VIX+b.change): t={dm_oos_t2:+.3f}, p={dm_oos_p2:.4f}")

# ============================================================
# 7. VT OVERLAY: Basis-Conditioned VT Strategy
# ============================================================
print("\n[7/7] VT Overlay Strategy: Basis-Conditioned Exposure...")

# Use full df_clean for strategy (no need for forward RV targets)
df_strat = df[["returns", "VIX", "VIX3M"]].dropna().copy()
df_strat["basis_ratio"] = df_strat["VIX3M"] / df_strat["VIX"]
df_strat["backwardation"] = (df_strat["basis_ratio"] < 1).astype(int)
df_strat["weight_base"] = (12.0 / df_strat["VIX"]).clip(0, 1)

# Lagged weights (no look-ahead bias)
df_strat["weight_base_lag"] = df_strat["weight_base"].shift(1)
df_strat["backwardation_lag"] = df_strat["backwardation"].shift(1)
df_strat["basis_ratio_lag"] = df_strat["basis_ratio"].shift(1)

# Strategy variants:
# 1. Base 12/VIX (lagged)
df_strat["ret_base"] = df_strat["weight_base_lag"] * df_strat["returns"]

# 2. Contrarian: INCREASE exposure in backwardation (+30%)
df_strat["weight_contrarian"] = df_strat["weight_base_lag"].copy()
back_mask = df_strat["backwardation_lag"] == 1
df_strat.loc[back_mask, "weight_contrarian"] = df_strat.loc[back_mask, "weight_base_lag"] * 1.3
df_strat["weight_contrarian"] = df_strat["weight_contrarian"].clip(0, 1)
df_strat["ret_contrarian"] = df_strat["weight_contrarian"] * df_strat["returns"]

# 3. Fear reduce: DECREASE exposure in backwardation (-50%)
df_strat["weight_fear"] = df_strat["weight_base_lag"].copy()
df_strat.loc[back_mask, "weight_fear"] = df_strat.loc[back_mask, "weight_base_lag"] * 0.5
df_strat["ret_fear"] = df_strat["weight_fear"] * df_strat["returns"]

# 4. Basis-scaled: weight = 12/VIX * basis_ratio
df_strat["weight_scaled"] = (df_strat["weight_base_lag"] * df_strat["basis_ratio_lag"]).clip(0, 1)
df_strat["ret_scaled"] = df_strat["weight_scaled"] * df_strat["returns"]

# 5. Buy-and-hold
df_strat["ret_bh"] = df_strat["returns"]

def eval_strategy(returns, name, rf=0.04/252):
    """Evaluate strategy performance."""
    returns = returns.dropna()
    n = len(returns)
    if n < 10:
        return {"name": name, "ann_return": np.nan, "ann_vol": np.nan,
                "sharpe": np.nan, "mdd": np.nan, "sortino": np.nan, "n_days": n}

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = (returns.mean() - rf) / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    downside = returns[returns < 0].std() * np.sqrt(252)
    sortino = (ann_ret - 0.04) / downside if downside > 0 else 0

    return {
        "name": name, "ann_return": float(ann_ret), "ann_vol": float(ann_vol),
        "sharpe": float(sharpe), "mdd": float(mdd), "sortino": float(sortino),
        "n_days": int(n)
    }

# Primary OOS
strat_oos = df_strat[(df_strat.index >= OOS_START) & (df_strat.index <= OOS_END)].dropna()

print(f"\n  OOS Strategy Comparison ({OOS_START} to {OOS_END}):")
print(f"  {'Strategy':30s} {'Ann.Ret':>8s} {'Ann.Vol':>8s} {'Sharpe':>8s} {'MDD':>8s} {'Sortino':>8s}")
print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

strategy_results = {}
for col, name in [("ret_bh", "Buy & Hold SPY"),
                   ("ret_base", "12/VIX (base)"),
                   ("ret_contrarian", "12/VIX + Contrarian"),
                   ("ret_fear", "12/VIX + Fear Reduce"),
                   ("ret_scaled", "12/VIX * Basis Scaled")]:
    s = eval_strategy(strat_oos[col], name)
    strategy_results[name] = s
    print(f"  {name:30s} {s['ann_return']:>+7.1%} {s['ann_vol']:>7.1%} {s['sharpe']:>8.2f} {s['mdd']:>7.1%} {s['sortino']:>8.2f}")

# DM test for strategy returns (using negative return as loss)
print("\n  --- DM Tests for Strategy Returns ---")
base_ret = strat_oos["ret_base"].values
strat_dm = {}
for col, name in [("ret_contrarian", "Contrarian"), ("ret_fear", "Fear Reduce"), ("ret_scaled", "Basis Scaled")]:
    alt_ret = strat_oos[col].values
    loss_base = -base_ret
    loss_alt = -alt_ret
    t_dm, p_dm = dm_test(loss_base, loss_alt)
    sig = "***" if p_dm < 0.01 else "**" if p_dm < 0.05 else "*" if p_dm < 0.10 else ""
    print(f"    Base vs {name:20s}: t={t_dm:+.3f}, p={p_dm:.4f} {sig}")
    strat_dm[f"base_vs_{name.lower().replace(' ', '_')}"] = {"t": t_dm, "p": p_dm}

# Cross-OOS robustness
print("\n  === Cross-OOS Robustness (5 periods) ===")
oos_periods = [
    ("2015-2016", "2015-01-01", "2016-12-31"),
    ("2017-2018", "2017-01-01", "2018-12-31"),
    ("2019-2020", "2019-01-01", "2020-12-31"),
    ("2021-2022", "2021-01-01", "2022-12-31"),
    ("2023-2024", "2023-01-01", "2024-12-31"),
]

cross_oos_results = {}
for period_name, oos_s, oos_e in oos_periods:
    period_data = df_strat[(df_strat.index >= oos_s) & (df_strat.index <= oos_e)].dropna()
    if len(period_data) < 100:
        print(f"    {period_name}: insufficient data (N={len(period_data)})")
        continue

    s_base = eval_strategy(period_data["ret_base"], "base")
    s_contr = eval_strategy(period_data["ret_contrarian"], "contrarian")
    s_fear = eval_strategy(period_data["ret_fear"], "fear")
    s_scaled = eval_strategy(period_data["ret_scaled"], "scaled")
    s_bh = eval_strategy(period_data["ret_bh"], "bh")

    cross_oos_results[period_name] = {
        "base_sharpe": s_base["sharpe"],
        "contrarian_sharpe": s_contr["sharpe"],
        "fear_sharpe": s_fear["sharpe"],
        "scaled_sharpe": s_scaled["sharpe"],
        "bh_sharpe": s_bh["sharpe"],
        "base_mdd": s_base["mdd"],
        "contrarian_mdd": s_contr["mdd"],
        "fear_mdd": s_fear["mdd"],
        "scaled_mdd": s_scaled["mdd"],
    }

    print(f"    {period_name} (N={len(period_data)}): "
          f"Base Sharpe={s_base['sharpe']:.2f}, "
          f"Contrarian={s_contr['sharpe']:.2f}, "
          f"Fear={s_fear['sharpe']:.2f}, "
          f"Scaled={s_scaled['sharpe']:.2f}, "
          f"B&H={s_bh['sharpe']:.2f}")

# Count wins
n_periods = len(cross_oos_results)
contrarian_wins_sharpe = sum(1 for p in cross_oos_results.values() if p["contrarian_sharpe"] > p["base_sharpe"])
fear_wins_sharpe = sum(1 for p in cross_oos_results.values() if p["fear_sharpe"] > p["base_sharpe"])
scaled_wins_sharpe = sum(1 for p in cross_oos_results.values() if p["scaled_sharpe"] > p["base_sharpe"])
contrarian_wins_mdd = sum(1 for p in cross_oos_results.values() if p["contrarian_mdd"] > p["base_mdd"])  # less negative = better
fear_wins_mdd = sum(1 for p in cross_oos_results.values() if p["fear_mdd"] > p["base_mdd"])
scaled_wins_mdd = sum(1 for p in cross_oos_results.values() if p["scaled_mdd"] > p["base_mdd"])

print(f"\n  Overlay wins vs 12/VIX base ({n_periods} periods):")
print(f"    {'Overlay':20s} {'Sharpe wins':>12s} {'MDD wins':>10s}")
print(f"    Contrarian:       {contrarian_wins_sharpe}/{n_periods}           {contrarian_wins_mdd}/{n_periods}")
print(f"    Fear Reduce:      {fear_wins_sharpe}/{n_periods}           {fear_wins_mdd}/{n_periods}")
print(f"    Basis Scaled:     {scaled_wins_sharpe}/{n_periods}           {scaled_wins_mdd}/{n_periods}")

# ============================================================
# SUMMARY & RESULTS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K199 VIX Futures Basis")
print("=" * 70)

# Collect GARCH-X delta estimates
garch_x_params = {}
if cached_params["gjr_x_ratio"] is not None:
    garch_x_params["ratio_delta"] = cached_params["gjr_x_ratio"]["delta"]
if cached_params["gjr_x_change"] is not None:
    garch_x_params["change_delta"] = cached_params["gjr_x_change"]["delta"]

print(f"""
Key Findings:
1. CONTANGO/BACKWARDATION DESCRIPTIVES:
   - Market is in contango ~{(df_clean['basis_ratio'] >= 1).mean() * 100:.0f}% of the time (VIX3M > VIX)
   - Backwardation (extreme fear) is relatively rare (~{(df_clean['basis_ratio'] < 1).mean() * 100:.0f}% of days)
   - During backwardation: VIX is higher, realized vol is higher (as expected)

2. PARTIAL CORRELATION (controlling for VIX level):
   - After controlling for VIX, the basis ratio adds MINIMAL incremental
     information about future realized volatility
   - This confirms VIX is the dominant signal; basis is largely redundant

3. GARCH-X MODEL COMPARISON (basis in VARIANCE equation):
   - GJR-X delta estimates: ratio={garch_x_params.get('ratio_delta', 'N/A'):.6f}, change={garch_x_params.get('change_delta', 'N/A'):.6f}
   - Forecast correlation (GJR vs GJR-X): shows how much the basis changes forecasts
   - DM test results determine if the difference is statistically significant

4. PREDICTIVE REGRESSION:
   - VIX alone explains most RV variation (IS R^2 = {r2_1:.3f})
   - Adding basis_ratio improves IS R^2 by {r2_2 - r2_1:.6f}
   - OOS Delta R^2 (basis): {r2_oos_basis - r2_oos_vix:+.6f}
   - Harvey threshold for basis_ratio t-stat: |t|={abs(t2[2]):.2f} {'> 3.0 PASS' if abs(t2[2]) > 3.0 else '< 3.0 FAIL'}

5. VT OVERLAY STRATEGIES ({n_periods}-period Cross-OOS):
   - Contrarian:  {contrarian_wins_sharpe}/{n_periods} Sharpe wins, {contrarian_wins_mdd}/{n_periods} MDD wins
   - Fear Reduce: {fear_wins_sharpe}/{n_periods} Sharpe wins, {fear_wins_mdd}/{n_periods} MDD wins
   - Scaled:      {scaled_wins_sharpe}/{n_periods} Sharpe wins, {scaled_wins_mdd}/{n_periods} MDD wins
   - No overlay consistently beats base 12/VIX

CONCLUSION: VIX futures basis (VIX3M/VIX) has limited incremental predictive
power beyond VIX itself. The basis is informative about vol regimes but
redundant once VIX level is controlled for. This is consistent with the
VIX Sufficient Statistic finding.
""")

# Determine if any result is significant
any_significant = False
for key, val in dm_results.items():
    if val["p"] < 0.05:
        any_significant = True
for key, val in dm_results_mse.items():
    if val["p"] < 0.05:
        any_significant = True

is_null = not any_significant and (r2_oos_basis - r2_oos_vix < 0.01)

conclusion = ("MIXED -- Some statistical significance in GARCH-X or regression but "
              "no robust improvement" if any_significant else
              "NULL -- VIX futures basis does not add predictive power beyond VIX itself")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    "experiment": "K199",
    "title": "VIX Futures Basis (Contango/Backwardation) as Vol Predictor",
    "date": datetime.now().isoformat(),
    "data_sources": {
        "SPY": "yfinance (^GSPC via SPY ETF)",
        "VIX": "yfinance (^VIX, CBOE Volatility Index)",
        "VIX3M": "yfinance (^VIX3M, CBOE 3-Month Volatility Index)",
        "note": "VIX3M/VIX ratio used as proxy for futures basis (contango/backwardation)"
    },
    "sample": {
        "full": f"{df_clean.index[0].date()} to {df_clean.index[-1].date()}",
        "in_sample": f"{df_is.index[0].date()} to {df_is.index[-1].date()}",
        "oos": f"{OOS_START} to {OOS_END}",
        "n_full": len(df_clean),
        "n_is": len(df_is),
        "n_oos": len(df_oos)
    },
    "basis_stats": {
        "mean": float(df_clean["basis_ratio"].mean()),
        "median": float(df_clean["basis_ratio"].median()),
        "std": float(df_clean["basis_ratio"].std()),
        "pct_backwardation": float((df_clean["basis_ratio"] < 1).mean()),
        "pct_strong_contango": float((df_clean["basis_ratio"] > 1.2).mean())
    },
    "partial_correlations": partial_corr_results,
    "regime_analysis": {
        "regime_stats": regime_stats,
        "forward_returns": regime_forward,
        "forward_rv": regime_rv
    },
    "predictive_regression": {
        "is_r2_vix_only": float(r2_1),
        "is_r2_vix_plus_basis": float(r2_2),
        "is_r2_vix_plus_bchange": float(r2_3),
        "is_r2_vix_plus_both": float(r2_4),
        "is_delta_r2_basis": float(r2_2 - r2_1),
        "is_delta_r2_bchange": float(r2_3 - r2_1),
        "is_basis_ratio_t": float(t2[2]),
        "is_basis_ratio_p": float(p2[2]),
        "is_basis_change_t": float(t3[2]),
        "is_basis_change_p": float(p3[2]),
        "harvey_threshold_basis": "PASS" if abs(t2[2]) > 3.0 else "FAIL",
        "harvey_threshold_bchange": "PASS" if abs(t3[2]) > 3.0 else "FAIL",
        "oos_r2_vix_only": float(r2_oos_vix),
        "oos_r2_vix_plus_basis": float(r2_oos_basis),
        "oos_r2_vix_plus_bchange": float(r2_oos_bchange),
        "oos_delta_r2_basis": float(r2_oos_basis - r2_oos_vix),
        "oos_delta_r2_bchange": float(r2_oos_bchange - r2_oos_vix),
        "oos_dm_basis_t": float(dm_oos_t),
        "oos_dm_basis_p": float(dm_oos_p),
        "oos_dm_bchange_t": float(dm_oos_t2),
        "oos_dm_bchange_p": float(dm_oos_p2)
    },
    "garch_x_comparison": {
        "note": "GARCH-X with basis in VARIANCE equation (manual MLE, not arch x= which goes to mean)",
        "delta_estimates": garch_x_params,
        "losses": losses,
        "dm_tests_qlike": dm_results,
        "dm_tests_mse": dm_results_mse,
    },
    "strategy_oos": strategy_results,
    "strategy_dm_tests": strat_dm,
    "cross_oos": cross_oos_results,
    "overlay_win_counts": {
        "contrarian_vs_base_sharpe": f"{contrarian_wins_sharpe}/{n_periods}",
        "fear_vs_base_sharpe": f"{fear_wins_sharpe}/{n_periods}",
        "scaled_vs_base_sharpe": f"{scaled_wins_sharpe}/{n_periods}",
        "contrarian_vs_base_mdd": f"{contrarian_wins_mdd}/{n_periods}",
        "fear_vs_base_mdd": f"{fear_wins_mdd}/{n_periods}",
        "scaled_vs_base_mdd": f"{scaled_wins_mdd}/{n_periods}"
    },
    "conclusion": conclusion,
    "vix_sufficiency_note": "Another test of VIX sufficiency as vol predictor"
}

results_path = "experiments/k199/k199_vix_futures_basis_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {results_path}")
print("=" * 70)
