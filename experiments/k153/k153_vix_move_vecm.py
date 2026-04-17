"""
K153: VIX-MOVE Vol-Spread VECM
================================
[提出: Gemini R5#3, 執行: Claude]

Hypothesis (Gemini):
  VIX and MOVE (bond volatility) are co-integrated. The MOVE/VIX ratio's
  deviation from its long-run mean (the error correction term) predicts
  whether equity vol mean-reversion is accelerated or delayed.

Prior results:
  T11: MOVE alone has null predictive power for equities.
  But Gemini's VECM approach is different: it uses the *error correction term*
  from the VIX-MOVE cointegrating relationship, not MOVE alone.

Research Questions:
  1. Are VIX and MOVE co-integrated?
  2. Does the VIX-MOVE error correction term improve GJR-GARCH vol forecasts?
  3. Can the MOVE/VIX ratio identify when equity vol is "too high" or "too low"
     relative to bond market information?

Method:
  a. Cointegration test: Engle-Granger + Johansen for log(VIX) vs log(MOVE)
  b. Error correction term: ECT = log(VIX) - beta*log(MOVE) - c
  c. VECM: Delta_log(VIX_t) = alpha*ECT_{t-1} + lagged terms
  d. GARCH-X with ECT: ECT as exogenous in GJR-GARCH variance equation
  e. Threshold model: when |ECT| > 1 std, use modified forecast
  f. VT strategy: MOVE/VIX ratio overlay on 12/VIX
  Walk-forward: w=2000, 1-step-ahead, OOS 2020-01-01 to 2024-12-31

Usage:
    uv run python experiments/k153_vix_move_vecm.py
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ======================================================================
# CONFIG
# ======================================================================
VIX_TICKER = "^VIX"
MOVE_TICKER = "^MOVE"
SPY_TICKER = "SPY"
GLD_TICKER = "GLD"

DATA_START = "2005-01-01"
DATA_END = "2026-03-22"
OOS_START = "2020-01-01"
OOS_END = "2024-12-31"
WINDOW = 2000
REFIT_FREQ = 22  # monthly refit

print("=" * 80)
print("K153: VIX-MOVE Vol-Spread VECM")
print("=" * 80)
print(f"  [提出: Gemini R5#3, 執行: Claude]")
print(f"  Data: {DATA_START} to {DATA_END}")
print(f"  OOS:  {OOS_START} to {OOS_END}")
print(f"  Window: {WINDOW}, Refit: every {REFIT_FREQ} days")
print()


# ======================================================================
# 1. DATA LOADING
# ======================================================================
print("-" * 60)
print("1. LOADING DATA")
print("-" * 60)

import yfinance as yf
from scipy import stats
from arch import arch_model

tickers = {
    VIX_TICKER: "VIX",
    MOVE_TICKER: "MOVE",
    SPY_TICKER: "SPY",
    GLD_TICKER: "GLD",
}

data = {}
for ticker, name in tickers.items():
    print(f"  Downloading {name} ({ticker})...", end="", flush=True)
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_localize(None)
    data[name] = df["Close"]
    print(f" {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Align all on common dates
df_all = pd.DataFrame(data)
df_all = df_all.dropna()
print(f"\n  Aligned dataset: {len(df_all)} days ({df_all.index[0].date()} to {df_all.index[-1].date()})")

# Compute returns
spy_ret = np.log(df_all["SPY"] / df_all["SPY"].shift(1)).dropna() * 100  # in percent
gld_ret = np.log(df_all["GLD"] / df_all["GLD"].shift(1)).dropna() * 100

# Log series for cointegration
log_vix = np.log(df_all["VIX"])
log_move = np.log(df_all["MOVE"])

# Realized vol proxy (squared returns)
rv_spy = spy_ret ** 2

# Align
common_idx = spy_ret.index.intersection(log_vix.index).intersection(log_move.index)
spy_ret = spy_ret.loc[common_idx]
gld_ret = gld_ret.loc[common_idx]
log_vix = log_vix.loc[common_idx]
log_move = log_move.loc[common_idx]
rv_spy = rv_spy.loc[common_idx]

print(f"  Final aligned: {len(common_idx)} obs")
print(f"  VIX range: {df_all['VIX'].min():.1f} - {df_all['VIX'].max():.1f}")
print(f"  MOVE range: {df_all['MOVE'].min():.1f} - {df_all['MOVE'].max():.1f}")
print()


# ======================================================================
# 2. COINTEGRATION TESTS
# ======================================================================
print("-" * 60)
print("2. COINTEGRATION TESTS: log(VIX) vs log(MOVE)")
print("-" * 60)

from statsmodels.tsa.stattools import coint, adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

# 2a. Unit root tests first
adf_vix = adfuller(log_vix.values, maxlag=20, regression="ct")
adf_move = adfuller(log_move.values, maxlag=20, regression="ct")
print(f"  ADF log(VIX):  stat={adf_vix[0]:.4f}, p={adf_vix[1]:.4f} (lags={adf_vix[2]})")
print(f"  ADF log(MOVE): stat={adf_move[0]:.4f}, p={adf_move[1]:.4f} (lags={adf_move[2]})")

# Check if I(1)
d_log_vix = log_vix.diff().dropna()
d_log_move = log_move.diff().dropna()
adf_dvix = adfuller(d_log_vix.values, maxlag=20, regression="c")
adf_dmove = adfuller(d_log_move.values, maxlag=20, regression="c")
print(f"  ADF d(log(VIX)):  stat={adf_dvix[0]:.4f}, p={adf_dvix[1]:.4f}")
print(f"  ADF d(log(MOVE)): stat={adf_dmove[0]:.4f}, p={adf_dmove[1]:.4f}")

vix_is_i1 = adf_vix[1] > 0.05 and adf_dvix[1] < 0.05
move_is_i1 = adf_move[1] > 0.05 and adf_dmove[1] < 0.05
print(f"  VIX is I(1)? {vix_is_i1}  |  MOVE is I(1)? {move_is_i1}")

# 2b. Engle-Granger cointegration test
eg_stat, eg_pval, eg_crit = coint(log_vix.values, log_move.values, trend="c")
print(f"\n  Engle-Granger test:")
print(f"    t-stat = {eg_stat:.4f}")
print(f"    p-value = {eg_pval:.4f}")
print(f"    Critical values: 1%={eg_crit[0]:.4f}, 5%={eg_crit[1]:.4f}, 10%={eg_crit[2]:.4f}")
eg_coint = eg_pval < 0.05

# 2c. Johansen cointegration test
coint_data = np.column_stack([log_vix.values, log_move.values])
joh_result = coint_johansen(coint_data, det_order=0, k_ar_diff=5)
print(f"\n  Johansen test (trace):")
for i in range(2):
    print(f"    r={i}: trace_stat={joh_result.lr1[i]:.4f}, "
          f"crit_95%={joh_result.cvt[i, 1]:.4f}, "
          f"reject={'YES' if joh_result.lr1[i] > joh_result.cvt[i, 1] else 'NO'}")
print(f"  Johansen test (max eigenvalue):")
for i in range(2):
    print(f"    r={i}: max_eig={joh_result.lr2[i]:.4f}, "
          f"crit_95%={joh_result.cvm[i, 1]:.4f}, "
          f"reject={'YES' if joh_result.lr2[i] > joh_result.cvm[i, 1] else 'NO'}")

joh_coint = joh_result.lr1[0] > joh_result.cvt[0, 1]

print(f"\n  Cointegration result:")
print(f"    Engle-Granger: {'COINTEGRATED (p<0.05)' if eg_coint else 'NOT cointegrated'}")
print(f"    Johansen:      {'COINTEGRATED' if joh_coint else 'NOT cointegrated'}")

# 2d. Estimate cointegrating regression: log(VIX) = beta*log(MOVE) + c + eps
X_coint = add_constant(log_move.values)
ols_coint = OLS(log_vix.values, X_coint).fit()
beta_coint = ols_coint.params[1]
const_coint = ols_coint.params[0]
ect_full = log_vix.values - beta_coint * log_move.values - const_coint
ect_series = pd.Series(ect_full, index=log_vix.index, name="ECT")

print(f"\n  Cointegrating regression: log(VIX) = {beta_coint:.4f}*log(MOVE) + {const_coint:.4f}")
print(f"  R-squared: {ols_coint.rsquared:.4f}")
print(f"  ECT stats: mean={ect_series.mean():.4f}, std={ect_series.std():.4f}")

# ADF on ECT residual
adf_ect = adfuller(ect_full, maxlag=20, regression="c")
print(f"  ADF on ECT residual: stat={adf_ect[0]:.4f}, p={adf_ect[1]:.4f}")
print(f"  ECT is stationary? {'YES' if adf_ect[1] < 0.05 else 'NO'}")

# 2e. Sub-period stability
mid_idx = len(log_vix) // 2
ect_first_half = ect_series.iloc[:mid_idx]
ect_second_half = ect_series.iloc[mid_idx:]
print(f"\n  ECT sub-period stability:")
print(f"    First half:  mean={ect_first_half.mean():.4f}, std={ect_first_half.std():.4f}")
print(f"    Second half: mean={ect_second_half.mean():.4f}, std={ect_second_half.std():.4f}")

# Check structural break around 2022
post2022 = ect_series.loc["2022-01-01":]
pre2022 = ect_series.loc[:"2021-12-31"]
print(f"    Pre-2022:  mean={pre2022.mean():.4f}, std={pre2022.std():.4f}")
print(f"    Post-2022: mean={post2022.mean():.4f}, std={post2022.std():.4f}")
print()


# ======================================================================
# 3. ERROR CORRECTION MODEL
# ======================================================================
print("-" * 60)
print("3. ERROR CORRECTION MODEL")
print("-" * 60)

# Build VECM-style regression manually for flexibility
# Delta_log(VIX_t) = alpha*ECT_{t-1} + sum(beta_i * Delta_log(VIX_{t-i})) + sum(gamma_i * Delta_log(MOVE_{t-i})) + eps

d_log_vix_all = log_vix.diff().dropna()
d_log_move_all = log_move.diff().dropna()

# Align with ECT (lagged by 1)
ect_lag1 = ect_series.shift(1).dropna()
common_ecm = d_log_vix_all.index.intersection(d_log_move_all.index).intersection(ect_lag1.index)
d_vix = d_log_vix_all.loc[common_ecm]
d_move = d_log_move_all.loc[common_ecm]
ect_l1 = ect_lag1.loc[common_ecm]

# Build ECM design matrix (p=5 lags)
p_lags = 5
X_ecm_list = [ect_l1.values]
col_names = ["ECT_lag1"]

for lag in range(1, p_lags + 1):
    X_ecm_list.append(d_vix.shift(lag).values)
    col_names.append(f"dVIX_lag{lag}")
    X_ecm_list.append(d_move.shift(lag).values)
    col_names.append(f"dMOVE_lag{lag}")

X_ecm = np.column_stack(X_ecm_list)
y_ecm = d_vix.values

# Drop NaN rows from lagging
valid = ~np.any(np.isnan(X_ecm), axis=1) & ~np.isnan(y_ecm)
X_ecm_clean = add_constant(X_ecm[valid])
y_ecm_clean = y_ecm[valid]
col_names_with_const = ["const"] + col_names

ecm_ols = OLS(y_ecm_clean, X_ecm_clean).fit(cov_type="HC1")

print(f"  ECM regression (y = Delta_log(VIX)):")
print(f"  N = {len(y_ecm_clean)}, R-squared = {ecm_ols.rsquared:.4f}")
print(f"\n  {'Variable':<15} {'Coef':>10} {'t-stat':>10} {'p-value':>10}")
print(f"  {'-'*45}")
for name, coef, tval, pval in zip(col_names_with_const, ecm_ols.params,
                                   ecm_ols.tvalues, ecm_ols.pvalues):
    sig = "*" if pval < 0.05 else ""
    print(f"  {name:<15} {coef:>10.5f} {tval:>10.3f} {pval:>10.4f} {sig}")

alpha_ecm = ecm_ols.params[1]  # ECT coefficient (index 1, after const)
alpha_t = ecm_ols.tvalues[1]
alpha_p = ecm_ols.pvalues[1]
print(f"\n  Error correction speed (alpha): {alpha_ecm:.5f} (t={alpha_t:.3f}, p={alpha_p:.4f})")
print(f"  Expected sign: negative (VIX reverts to equilibrium)")
print(f"  Half-life: {-np.log(2)/alpha_ecm:.1f} days" if alpha_ecm < 0 else "  WARNING: Positive alpha!")


# ======================================================================
# 4. PARTIAL CORRELATION: ECT -> vol | VIX
# ======================================================================
print("\n" + "-" * 60)
print("4. PARTIAL CORRELATION: ECT -> realized vol | controlling for VIX")
print("-" * 60)

# Key question: Does ECT add info beyond VIX itself?
# rv_t+1 = a + b1*VIX_t + b2*ECT_t + eps
rv_fwd = rv_spy.shift(-1).dropna()
common_pc = rv_fwd.index.intersection(log_vix.index).intersection(ect_series.index)
rv_fwd_c = rv_fwd.loc[common_pc]
vix_c = log_vix.loc[common_pc]
ect_c = ect_series.loc[common_pc]

# Full model: rv ~ VIX + ECT
X_full = add_constant(np.column_stack([vix_c.values, ect_c.values]))
ols_full = OLS(rv_fwd_c.values, X_full).fit(cov_type="HC1")

# Restricted model: rv ~ VIX only
X_restr = add_constant(vix_c.values)
ols_restr = OLS(rv_fwd_c.values, X_restr).fit(cov_type="HC1")

print(f"  Model: RV(t+1) = a + b1*log(VIX_t) + b2*ECT_t + eps")
print(f"  Full model R-sq:       {ols_full.rsquared:.6f}")
print(f"  VIX-only model R-sq:   {ols_restr.rsquared:.6f}")
print(f"  Incremental R-sq:      {ols_full.rsquared - ols_restr.rsquared:.6f}")
print(f"\n  ECT coefficient: {ols_full.params[2]:.5f}")
print(f"  ECT t-statistic: {ols_full.tvalues[2]:.3f}")
print(f"  ECT p-value:     {ols_full.pvalues[2]:.4f}")

# Partial correlation
from scipy.stats import pearsonr

# Residualize both rv and ECT on VIX
resid_rv = OLS(rv_fwd_c.values, X_restr).fit().resid
resid_ect = OLS(ect_c.values, X_restr).fit().resid
partial_r, partial_p = pearsonr(resid_rv, resid_ect)
print(f"\n  Partial corr(ECT, RV | VIX): r={partial_r:.5f}, p={partial_p:.4f}")
print(f"  Interpretation: {'ECT adds info beyond VIX' if partial_p < 0.05 else 'ECT is REDUNDANT given VIX'}")

# Also check: is ECT just another way of saying "VIX is too high/low"?
r_ect_vix, p_ect_vix = pearsonr(ect_c.values, vix_c.values)
print(f"\n  corr(ECT, log(VIX)): r={r_ect_vix:.4f}, p={p_ect_vix:.4f}")
print(f"  If |r| > 0.8, ECT is essentially redundant with VIX level")

# MOVE/VIX ratio stats
ratio_mv = df_all["MOVE"] / df_all["VIX"]
print(f"\n  MOVE/VIX ratio: mean={ratio_mv.mean():.2f}, std={ratio_mv.std():.2f}")
print(f"  MOVE/VIX range: {ratio_mv.min():.2f} to {ratio_mv.max():.2f}")
print()


# ======================================================================
# 5. WALK-FORWARD GJR-GARCH vs GARCH-X (with ECT)
# ======================================================================
print("-" * 60)
print("5. WALK-FORWARD FORECAST COMPARISON")
print("-" * 60)
print(f"  Window: {WINDOW}, OOS: {OOS_START} to {OOS_END}")

oos_mask = (spy_ret.index >= OOS_START) & (spy_ret.index <= OOS_END)
oos_idx = spy_ret.index[oos_mask]
print(f"  OOS days: {len(oos_idx)}")

results = {
    "gjr_base": {"forecasts": [], "dates": []},
    "gjr_ect": {"forecasts": [], "dates": []},
    "gjr_threshold": {"forecasts": [], "dates": []},
}

t0 = time.time()
n_refits = 0
last_gjr_params = None
last_ect_beta = None
last_ect_const = None
last_ect_std = None

for i, date in enumerate(oos_idx):
    pos = spy_ret.index.get_loc(date)
    if pos < WINDOW:
        continue

    # Training window
    train_ret = spy_ret.iloc[pos - WINDOW:pos]
    train_vix = log_vix.iloc[pos - WINDOW:pos]
    train_move = log_move.iloc[pos - WINDOW:pos]

    need_refit = (i % REFIT_FREQ == 0) or (last_gjr_params is None)

    if need_refit:
        n_refits += 1

        # --- Base GJR-GARCH ---
        try:
            gjr = arch_model(train_ret, vol="GARCH", p=1, o=1, q=1,
                             mean="Constant", dist="t")
            gjr_fit = gjr.fit(disp="off", show_warning=False)
            last_gjr_params = gjr_fit.params
        except Exception:
            pass

        # --- Cointegrating regression on training window ---
        try:
            X_tr = add_constant(train_move.values)
            ols_tr = OLS(train_vix.values, X_tr).fit()
            last_ect_beta = ols_tr.params[1]
            last_ect_const = ols_tr.params[0]
            ect_train = train_vix.values - last_ect_beta * train_move.values - last_ect_const
            last_ect_std = np.std(ect_train)
        except Exception:
            pass

    # Compute ECT for current observation
    if last_ect_beta is not None:
        ect_now = log_vix.iloc[pos - 1] - last_ect_beta * log_move.iloc[pos - 1] - last_ect_const
    else:
        ect_now = 0.0

    # --- Base GJR forecast ---
    try:
        gjr_model = arch_model(train_ret, vol="GARCH", p=1, o=1, q=1,
                               mean="Constant", dist="t")
        gjr_res = gjr_model.fit(disp="off", show_warning=False,
                                starting_values=last_gjr_params)
        fc = gjr_res.forecast(horizon=1)
        base_var = fc.variance.values[-1, 0]
    except Exception:
        base_var = train_ret.var()

    results["gjr_base"]["forecasts"].append(base_var)
    results["gjr_base"]["dates"].append(str(date.date()))

    # --- GARCH-X with ECT: Adjust variance by ECT ---
    # Idea: if ECT > 0, VIX is "too high" relative to MOVE -> vol may revert down
    # Simple approach: sigma^2_adj = sigma^2_base * exp(delta * ECT_{t-1})
    # where delta is estimated from training regression of log(rv) on ECT
    try:
        # Estimate delta: relationship between ECT and next-day vol
        ect_train_vals = train_vix.values - last_ect_beta * train_move.values - last_ect_const
        rv_train = (train_ret.values ** 2)
        # Regression: log(rv+eps) = a + delta*ECT + e  (on training window)
        valid_rv = rv_train[1:] > 0
        if np.sum(valid_rv) > 100:
            log_rv_train = np.log(rv_train[1:][valid_rv] + 1e-8)
            ect_train_lag = ect_train_vals[:-1][valid_rv]
            X_delta = add_constant(ect_train_lag)
            delta_ols = OLS(log_rv_train, X_delta).fit()
            delta_hat = delta_ols.params[1]
        else:
            delta_hat = 0.0

        ect_adj = np.exp(delta_hat * ect_now)
        ect_var = base_var * np.clip(ect_adj, 0.5, 2.0)  # bound adjustment
    except Exception:
        ect_var = base_var

    results["gjr_ect"]["forecasts"].append(ect_var)
    results["gjr_ect"]["dates"].append(str(date.date()))

    # --- Threshold model ---
    # When |ECT| > 1 std, scale variance
    if last_ect_std is not None and last_ect_std > 0:
        z_ect = ect_now / last_ect_std
        if z_ect > 1.0:
            # VIX too high -> vol likely to decrease -> scale down slightly
            thresh_var = base_var * 0.95
        elif z_ect < -1.0:
            # VIX too low relative to MOVE -> vol likely to increase
            thresh_var = base_var * 1.05
        else:
            thresh_var = base_var
    else:
        thresh_var = base_var

    results["gjr_threshold"]["forecasts"].append(thresh_var)
    results["gjr_threshold"]["dates"].append(str(date.date()))

    if (i + 1) % 250 == 0:
        print(f"    {i+1}/{len(oos_idx)} forecasts done ({n_refits} refits)")

elapsed = time.time() - t0
print(f"\n  Done: {len(results['gjr_base']['forecasts'])} forecasts, "
      f"{n_refits} refits, {elapsed:.1f}s")


# ======================================================================
# 6. FORECAST EVALUATION
# ======================================================================
print("\n" + "-" * 60)
print("6. FORECAST EVALUATION")
print("-" * 60)

# Realized variance (squared returns as proxy)
fc_dates = pd.DatetimeIndex(results["gjr_base"]["dates"])
rv_actual = rv_spy.loc[fc_dates].values


def qlike(actual, forecast):
    """QLIKE loss function (Patton 2011)."""
    forecast = np.maximum(forecast, 1e-8)
    return np.mean(np.log(forecast) + actual / forecast)


def mse(actual, forecast):
    return np.mean((actual - forecast) ** 2)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (one-sided: loss1 < loss2 means model1 better)."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)
    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * (1 - k / h) * gamma_k
    se = np.sqrt(nw_var / n)
    if se < 1e-12:
        return 0.0, 1.0
    t_stat = d_bar / se
    p_val = stats.t.cdf(t_stat, df=n - 1)  # one-sided: negative t means model1 better
    return t_stat, p_val


print(f"\n  {'Model':<25} {'QLIKE':>10} {'MSE':>12} {'vs Base DM-t':>12} {'DM-p':>8}")
print(f"  {'-'*67}")

model_metrics = {}
for model_name in ["gjr_base", "gjr_ect", "gjr_threshold"]:
    fc = np.array(results[model_name]["forecasts"])
    q = qlike(rv_actual, fc)
    m = mse(rv_actual, fc)

    if model_name == "gjr_base":
        dm_t, dm_p = 0.0, 0.5
        base_loss_q = np.log(fc) + rv_actual / fc
    else:
        alt_loss_q = np.log(fc) + rv_actual / fc
        dm_t, dm_p = dm_test(alt_loss_q, base_loss_q)

    model_metrics[model_name] = {"qlike": q, "mse": m, "dm_t": dm_t, "dm_p": dm_p}
    label = model_name.replace("gjr_", "GJR-")
    print(f"  {label:<25} {q:>10.4f} {m:>12.4f} {dm_t:>12.3f} {dm_p:>8.4f}")

print(f"\n  DM test interpretation (one-sided):")
for model_name in ["gjr_ect", "gjr_threshold"]:
    dm_t = model_metrics[model_name]["dm_t"]
    dm_p = model_metrics[model_name]["dm_p"]
    label = model_name.replace("gjr_", "GJR-")
    if dm_p < 0.05:
        print(f"    {label}: SIGNIFICANTLY BETTER than base (t={dm_t:.3f}, p={dm_p:.4f})")
    elif dm_p > 0.95:
        print(f"    {label}: SIGNIFICANTLY WORSE than base (t={dm_t:.3f}, p={1-dm_p:.4f})")
    else:
        print(f"    {label}: NOT significantly different (t={dm_t:.3f}, p={dm_p:.4f})")


# ======================================================================
# 7. VT STRATEGY: MOVE/VIX RATIO OVERLAY
# ======================================================================
print("\n" + "-" * 60)
print("7. VT STRATEGY: MOVE/VIX RATIO OVERLAY on 12/VIX")
print("-" * 60)

# Base 12/VIX strategy
vix_daily = df_all["VIX"]
move_daily = df_all["MOVE"]
spy_price = df_all["SPY"]
spy_daily_ret = np.log(spy_price / spy_price.shift(1)).dropna()

oos_mask_strat = (spy_daily_ret.index >= OOS_START) & (spy_daily_ret.index <= OOS_END)
strat_dates = spy_daily_ret.index[oos_mask_strat]

# Base 12/VIX (lagged)
vix_lag = vix_daily.shift(1)
w_base = np.clip(12.0 / vix_lag.loc[strat_dates], 0, 1.5)
ret_base = (w_base * spy_daily_ret.loc[strat_dates]).dropna()

# MOVE/VIX ratio overlay
ratio_lag = (move_daily / vix_daily).shift(1)
ratio_mean = ratio_lag.loc[:OOS_START].mean()
ratio_std = ratio_lag.loc[:OOS_START].std()

# Strategy: When MOVE/VIX ratio is high (bond vol > equity vol relative to history),
# equity vol may be underpriced -> reduce allocation
# When ratio is low, equity vol may be overpriced -> increase allocation
ratio_z = (ratio_lag.loc[strat_dates] - ratio_mean) / ratio_std

# Overlay: Scale weight by ratio signal
# High ratio_z -> VIX is "too low" relative to MOVE -> reduce weight
overlay_scale = np.clip(1.0 - 0.15 * ratio_z, 0.5, 1.5)
w_overlay = np.clip(w_base * overlay_scale, 0, 1.5)
ret_overlay = (w_overlay * spy_daily_ret.loc[strat_dates]).dropna()

# Threshold overlay: Only modify when |z| > 1
w_thresh = w_base.copy()
mask_high = ratio_z > 1.0
mask_low = ratio_z < -1.0
w_thresh[mask_high] = w_base[mask_high] * 0.85
w_thresh[mask_low] = w_base[mask_low] * 1.15
w_thresh = np.clip(w_thresh, 0, 1.5)
ret_thresh = (w_thresh * spy_daily_ret.loc[strat_dates]).dropna()

# Buy-and-hold
ret_bh = spy_daily_ret.loc[strat_dates]


def compute_strat_metrics(ret_series, name):
    """Compute strategy metrics."""
    ann_ret = ret_series.mean() * 252
    ann_vol = ret_series.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (ret_series / 100).cumsum() if ret_series.abs().mean() > 1 else ret_series.cumsum()
    # Convert from log returns (percent) to cumulative
    cum_ret = np.exp(ret_series.cumsum() / 100) - 1 if ret_series.abs().mean() > 0.1 else np.exp(ret_series.cumsum()) - 1
    running_max = (1 + cum_ret).cummax()
    drawdown = (1 + cum_ret) / running_max - 1
    mdd = drawdown.min()
    # Sharpe t-stat
    n_years = len(ret_series) / 252
    sharpe_t = sharpe * np.sqrt(n_years)
    return {
        "name": name,
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "sharpe_t": float(sharpe_t),
        "mdd": float(mdd),
        "n_days": len(ret_series),
    }


strat_results = {}
for name, ret in [("Buy&Hold", ret_bh), ("12/VIX_base", ret_base),
                   ("12/VIX+MOVE_overlay", ret_overlay),
                   ("12/VIX+MOVE_thresh", ret_thresh)]:
    m = compute_strat_metrics(ret, name)
    strat_results[name] = m

print(f"\n  {'Strategy':<25} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'t-stat':>8} {'MDD':>8}")
print(f"  {'-'*68}")
for name, m in strat_results.items():
    print(f"  {name:<25} {m['ann_ret']:>8.4f} {m['ann_vol']:>8.4f} "
          f"{m['sharpe']:>8.3f} {m['sharpe_t']:>8.2f} {m['mdd']:>8.3%}")

# DM test for strategy returns
base_ret_arr = ret_base.values
overlay_ret_arr = ret_overlay.reindex(ret_base.index).values
thresh_ret_arr = ret_thresh.reindex(ret_base.index).values
valid_strat = ~np.isnan(overlay_ret_arr) & ~np.isnan(thresh_ret_arr)

sharpe_diff_overlay = strat_results["12/VIX+MOVE_overlay"]["sharpe"] - strat_results["12/VIX_base"]["sharpe"]
sharpe_diff_thresh = strat_results["12/VIX+MOVE_thresh"]["sharpe"] - strat_results["12/VIX_base"]["sharpe"]

print(f"\n  Sharpe difference (overlay vs base): {sharpe_diff_overlay:+.4f}")
print(f"  Sharpe difference (thresh vs base):  {sharpe_diff_thresh:+.4f}")
print(f"  Harvey threshold (t>3.0) required for claims")


# ======================================================================
# 8. REDUNDANCY CHECK
# ======================================================================
print("\n" + "-" * 60)
print("8. REDUNDANCY CHECK: Is ECT just VIX level in disguise?")
print("-" * 60)

# ECT = log(VIX) - beta*log(MOVE) - c
# If beta is small, ECT ≈ log(VIX) - c (just VIX level)
# Check correlation structure
print(f"  Cointegrating beta: {beta_coint:.4f}")
print(f"  If beta ~ 0, ECT is just VIX level")
print(f"  If beta ~ 1, ECT = log(VIX/MOVE) - c (true spread)")
print()

# Correlation matrix
corr_ect_vix = np.corrcoef(ect_series.values, log_vix.values)[0, 1]
corr_ect_move = np.corrcoef(ect_series.values, log_move.values)[0, 1]
corr_vix_move = np.corrcoef(log_vix.values, log_move.values)[0, 1]

print(f"  corr(ECT, log(VIX)):  {corr_ect_vix:.4f}")
print(f"  corr(ECT, log(MOVE)): {corr_ect_move:.4f}")
print(f"  corr(log(VIX), log(MOVE)): {corr_vix_move:.4f}")

# Variance decomposition: how much of ECT variance comes from VIX vs MOVE?
# ECT = logVIX - beta*logMOVE - c
var_vix_contrib = np.var(log_vix.values)
var_move_contrib = beta_coint**2 * np.var(log_move.values)
cov_contrib = -2 * beta_coint * np.cov(log_vix.values, log_move.values)[0, 1]
total_ect_var = np.var(ect_series.values)

print(f"\n  ECT variance decomposition:")
print(f"    Total ECT variance: {total_ect_var:.6f}")
print(f"    Var(logVIX) contrib: {var_vix_contrib:.6f} ({100*var_vix_contrib/(var_vix_contrib+var_move_contrib+abs(cov_contrib)):.1f}%)")
print(f"    beta^2*Var(logMOVE) contrib: {var_move_contrib:.6f} ({100*var_move_contrib/(var_vix_contrib+var_move_contrib+abs(cov_contrib)):.1f}%)")

# Granger causality: does MOVE Granger-cause VIX?
from statsmodels.tsa.stattools import grangercausalitytests

print(f"\n  Granger causality tests:")
gc_data = pd.DataFrame({"d_vix": d_log_vix_all, "d_move": d_log_move_all}).dropna()
try:
    print(f"    MOVE -> VIX:")
    gc_mv = grangercausalitytests(gc_data[["d_vix", "d_move"]].values, maxlag=5, verbose=False)
    for lag in [1, 5]:
        f_stat = gc_mv[lag][0]["ssr_ftest"][0]
        f_p = gc_mv[lag][0]["ssr_ftest"][1]
        print(f"      Lag {lag}: F={f_stat:.3f}, p={f_p:.4f} {'*' if f_p < 0.05 else ''}")

    print(f"    VIX -> MOVE:")
    gc_vm = grangercausalitytests(gc_data[["d_move", "d_vix"]].values, maxlag=5, verbose=False)
    for lag in [1, 5]:
        f_stat = gc_vm[lag][0]["ssr_ftest"][0]
        f_p = gc_vm[lag][0]["ssr_ftest"][1]
        print(f"      Lag {lag}: F={f_stat:.3f}, p={f_p:.4f} {'*' if f_p < 0.05 else ''}")
except Exception as e:
    print(f"    Granger test failed: {e}")


# ======================================================================
# 9. STRUCTURAL BREAK ANALYSIS (post-2022)
# ======================================================================
print("\n" + "-" * 60)
print("9. STRUCTURAL BREAK ANALYSIS (post-2022)")
print("-" * 60)

# Re-run cointegration on sub-periods
for period_name, start, end in [
    ("Pre-COVID (2007-2019)", "2007-01-01", "2019-12-31"),
    ("COVID+Post (2020-2024)", "2020-01-01", "2024-12-31"),
    ("Post-2022 (2022-2024)", "2022-01-01", "2024-12-31"),
]:
    mask_p = (log_vix.index >= start) & (log_vix.index <= end)
    lv = log_vix[mask_p]
    lm = log_move[mask_p]
    if len(lv) < 100:
        continue
    eg_s, eg_p, _ = coint(lv.values, lm.values, trend="c")
    # Also estimate beta
    X_p = add_constant(lm.values)
    ols_p = OLS(lv.values, X_p).fit()
    b_p = ols_p.params[1]
    r2_p = ols_p.rsquared
    print(f"  {period_name}: beta={b_p:.4f}, R2={r2_p:.4f}, EG_p={eg_p:.4f} "
          f"({'COINT' if eg_p < 0.05 else 'NOT coint'})")


# ======================================================================
# 10. SUMMARY & CONCLUSIONS
# ======================================================================
print("\n" + "=" * 80)
print("10. SUMMARY & CONCLUSIONS")
print("=" * 80)

# Determine key findings
coint_result = "COINTEGRATED" if (eg_coint or joh_coint) else "NOT cointegrated"
ect_significant_ecm = alpha_p < 0.05
ect_adds_info = partial_p < 0.05
ect_redundant = abs(corr_ect_vix) > 0.8

forecast_improves = model_metrics["gjr_ect"]["dm_p"] < 0.05
threshold_improves = model_metrics["gjr_threshold"]["dm_p"] < 0.05

strat_overlay_better = sharpe_diff_overlay > 0.05
strat_thresh_better = sharpe_diff_thresh > 0.05

print(f"\n  Q1: Are VIX and MOVE co-integrated?")
print(f"      Engle-Granger: p={eg_pval:.4f} -> {'YES' if eg_coint else 'NO'}")
print(f"      Johansen:      {'YES' if joh_coint else 'NO'}")
print(f"      -> {coint_result}")

print(f"\n  Q2: Does ECT improve GJR-GARCH forecasts?")
print(f"      GARCH-X (ECT): DM t={model_metrics['gjr_ect']['dm_t']:.3f}, p={model_metrics['gjr_ect']['dm_p']:.4f}")
print(f"      Threshold:     DM t={model_metrics['gjr_threshold']['dm_t']:.3f}, p={model_metrics['gjr_threshold']['dm_p']:.4f}")
print(f"      -> {'YES, significant improvement' if forecast_improves else 'NO, null result'}")

print(f"\n  Q3: Does MOVE/VIX ratio add info beyond VIX?")
print(f"      Partial corr(ECT, RV | VIX): r={partial_r:.5f}, p={partial_p:.4f}")
print(f"      corr(ECT, log(VIX)): {corr_ect_vix:.4f}")
print(f"      -> {'ECT adds unique info' if ect_adds_info else 'ECT is REDUNDANT (bond info already in VIX)'}")

print(f"\n  ECM alpha = {alpha_ecm:.5f} (t={alpha_t:.3f})")
print(f"  Error correction is {'significant' if ect_significant_ecm else 'NOT significant'}")

print(f"\n  Strategy results (OOS {OOS_START} to {OOS_END}):")
print(f"    12/VIX base:         Sharpe = {strat_results['12/VIX_base']['sharpe']:.3f}")
print(f"    12/VIX+MOVE overlay: Sharpe = {strat_results['12/VIX+MOVE_overlay']['sharpe']:.3f} (diff={sharpe_diff_overlay:+.4f})")
print(f"    12/VIX+MOVE thresh:  Sharpe = {strat_results['12/VIX+MOVE_thresh']['sharpe']:.3f} (diff={sharpe_diff_thresh:+.4f})")

# Final verdict
if not (eg_coint or joh_coint):
    verdict = "NULL: VIX and MOVE are NOT co-integrated. VECM approach invalid."
elif not ect_adds_info:
    verdict = "NULL: VIX-MOVE are co-integrated but ECT is redundant given VIX. Bond info already priced into VIX."
elif not forecast_improves:
    verdict = "PARTIAL: Co-integration exists and ECT has some info, but no OOS forecast improvement."
else:
    verdict = "POSITIVE: ECT from VIX-MOVE co-integration improves vol forecasts."

print(f"\n  VERDICT: {verdict}")
print(f"\n  Consistency with T11: {'CONSISTENT' if not forecast_improves else 'NEW FINDING'}")
print(f"  (T11 found MOVE null for direct prediction; VECM ECT is a different mechanism)")
print()


# ======================================================================
# 11. SAVE RESULTS
# ======================================================================
print("-" * 60)
print("11. SAVING RESULTS")
print("-" * 60)

output = {
    "experiment": "K153",
    "title": "VIX-MOVE Vol-Spread VECM",
    "attribution": "[提出: Gemini R5#3, 執行: Claude]",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "data_start": DATA_START,
        "data_end": DATA_END,
        "oos_start": OOS_START,
        "oos_end": OOS_END,
        "window": WINDOW,
        "refit_freq": REFIT_FREQ,
        "n_oos_days": len(oos_idx),
        "n_refits": n_refits,
        "elapsed_seconds": round(elapsed, 1),
    },
    "cointegration": {
        "engle_granger": {
            "t_stat": float(eg_stat),
            "p_value": float(eg_pval),
            "cointegrated": bool(eg_coint),
        },
        "johansen": {
            "trace_stat_r0": float(joh_result.lr1[0]),
            "crit_95_r0": float(joh_result.cvt[0, 1]),
            "cointegrated": bool(joh_coint),
        },
        "cointegrating_beta": float(beta_coint),
        "cointegrating_const": float(const_coint),
        "cointegrating_R2": float(ols_coint.rsquared),
        "ect_stationary": bool(adf_ect[1] < 0.05),
        "ect_adf_p": float(adf_ect[1]),
    },
    "unit_roots": {
        "log_vix_adf_p": float(adf_vix[1]),
        "log_move_adf_p": float(adf_move[1]),
        "d_log_vix_adf_p": float(adf_dvix[1]),
        "d_log_move_adf_p": float(adf_dmove[1]),
        "vix_is_I1": bool(vix_is_i1),
        "move_is_I1": bool(move_is_i1),
    },
    "error_correction": {
        "alpha_ecm": float(alpha_ecm),
        "alpha_t_stat": float(alpha_t),
        "alpha_p_value": float(alpha_p),
        "significant": bool(ect_significant_ecm),
        "half_life_days": float(-np.log(2) / alpha_ecm) if alpha_ecm < 0 else None,
    },
    "partial_correlation": {
        "partial_r_ect_rv_given_vix": float(partial_r),
        "partial_p": float(partial_p),
        "ect_adds_info_beyond_vix": bool(ect_adds_info),
        "corr_ect_log_vix": float(corr_ect_vix),
        "corr_ect_log_move": float(corr_ect_move),
        "corr_vix_move": float(corr_vix_move),
        "ect_redundant_with_vix": bool(ect_redundant),
    },
    "forecast_evaluation": {
        model_name: {
            "qlike": float(m["qlike"]),
            "mse": float(m["mse"]),
            "dm_t_vs_base": float(m["dm_t"]),
            "dm_p_vs_base": float(m["dm_p"]),
        }
        for model_name, m in model_metrics.items()
    },
    "strategy": {
        name: {
            "ann_return": float(m["ann_ret"]),
            "ann_vol": float(m["ann_vol"]),
            "sharpe": float(m["sharpe"]),
            "sharpe_t": float(m["sharpe_t"]),
            "mdd": float(m["mdd"]),
            "n_days": m["n_days"],
        }
        for name, m in strat_results.items()
    },
    "strategy_sharpe_diffs": {
        "overlay_vs_base": float(sharpe_diff_overlay),
        "threshold_vs_base": float(sharpe_diff_thresh),
    },
    "verdict": verdict,
    "conclusions": {
        "q1_cointegrated": coint_result,
        "q2_forecast_improvement": bool(forecast_improves),
        "q3_ect_adds_info_beyond_vix": bool(ect_adds_info),
        "ect_redundant_with_vix_level": bool(ect_redundant),
        "consistent_with_T11": not forecast_improves,
    },
}

# Save
results_path = project_root / "storage" / "experiments" / "k153_vix_move_vecm_results.json"
results_path.parent.mkdir(parents=True, exist_ok=True)
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Saved: {results_path}")


# ======================================================================
# 12. RECORD TO MEMORY
# ======================================================================
print("\n" + "-" * 60)
print("12. RECORDING TO MEMORY")
print("-" * 60)

try:
    from volpred.memory.system import MemorySystem
    m = MemorySystem()

    # Build concise result string
    ect_info = f"partial_r={partial_r:.4f},p={partial_p:.4f}"
    dm_ect = f"DM_t={model_metrics['gjr_ect']['dm_t']:.3f}"
    strat_info = f"overlay Sharpe diff={sharpe_diff_overlay:+.4f}"

    result_str = (
        f"[提出: Gemini R5#3, 執行: Claude] K153: VIX-MOVE Vol-Spread VECM. "
        f"Cointegration: EG p={eg_pval:.4f} ({'YES' if eg_coint else 'NO'}), "
        f"Johansen {'YES' if joh_coint else 'NO'}. "
        f"ECM alpha={alpha_ecm:.5f} (t={alpha_t:.2f}). "
        f"Partial corr(ECT,RV|VIX): {ect_info}. "
        f"GARCH-X with ECT: {dm_ect}. "
        f"Strategy: {strat_info}. "
        f"VERDICT: {verdict}"
    )
    m.add_knowledge(category="experiment", content=result_str, confidence=0.8)

    thinking_str = (
        f"K153 thinking: Gemini hypothesized VIX-MOVE VECM could capture cross-market vol info. "
        f"Cointegration {'confirmed' if (eg_coint or joh_coint) else 'rejected'}. "
        f"ECT adds info beyond VIX? {ect_adds_info}. "
        f"ECT redundant with VIX level? corr={corr_ect_vix:.3f}. "
        f"Key insight: {'Bond info in ECT is already captured by VIX level.' if ect_redundant else 'ECT provides unique cross-market signal.'} "
        f"This {'extends' if not forecast_improves else 'contradicts'} T11 (MOVE null for direct prediction). "
        f"VECM mechanism different from direct MOVE but {'still null' if not forecast_improves else 'shows promise'}."
    )
    m.think(thinking_str)

    print(f"  Knowledge and thinking recorded.")
except Exception as e:
    print(f"  Memory recording failed: {e}")

print("\n" + "=" * 80)
print("K153 COMPLETE")
print("=" * 80)
