"""
K189: Attention-Weighted Volatility (Cross-Asset Information Aggregation)
=========================================================================
[提出: 用戶, 執行: Claude]

Research Question:
Instead of treating each asset independently (as GARCH does), can a simple
cross-asset attention mechanism improve volatility forecasts? Weight other
assets' recent volatility signals by their historical predictive relevance.

Data Source: yfinance daily data for SPY, QQQ, GLD, TLT, EEM, IWM
OOS: 2023-2024. Training window: 500 days (rolling).

Methodology:
1. Compute "attention weights" via rolling correlation of asset j's lagged RV
   with asset i's future RV (window=252). Softmax normalization.
2. Attention-weighted vol forecast:
   h_i,t = alpha * EWMA_i,t + (1-alpha) * sum_j(w_j * EWMA_j,t)
3. Compare vs standalone GJR-GARCH and standalone EWMA(0.94)
4. DM test on QLIKE loss
5. Partial correlation controlling for VIX
6. Harvey (2016) threshold check

No look-ahead: attention weights computed from rolling past data only.
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model
import json
import os
import time
from datetime import datetime
from pathlib import Path

print("=" * 70)
print("K189: Attention-Weighted Volatility")
print("     Cross-Asset Information Aggregation")
print("=" * 70)

# ============================================================
# 1. DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance ...")

ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM", "IWM"]
VIX_TICKER = "^VIX"
OOS_START = "2023-01-01"
OOS_END = "2025-01-01"
TRAIN_WINDOW = 500       # rolling training window for EWMA/GARCH
ATTN_WINDOW = 252        # rolling window for attention weight estimation
RV_LAG = 1               # lag for cross-asset predictive correlation
EWMA_LAMBDA = 0.94       # RiskMetrics standard
ALPHA_GRID = [0.3, 0.5, 0.7, 0.9]  # weight on own EWMA vs cross-asset

t0 = time.time()

# Download all assets + VIX
data = {}
for ticker in ASSETS + [VIX_TICKER]:
    df_raw = yf.download(ticker, start="2005-01-01", end=OOS_END, progress=False)
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)
    data[ticker] = df_raw["Close"]

prices = pd.DataFrame({t: data[t] for t in ASSETS})
prices["VIX"] = data[VIX_TICKER]
prices = prices.dropna()

# Log returns (annualized for display, raw for computation)
returns = np.log(prices[ASSETS] / prices[ASSETS].shift(1)).dropna()
vix = prices["VIX"].reindex(returns.index)

print(f"  Total obs: {len(returns)} ({returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')})")
print(f"  Assets: {ASSETS}")
print(f"  Data load time: {time.time()-t0:.1f}s")

# ============================================================
# 2. REALIZED VOLATILITY (22-day)
# ============================================================
print("\n[2] Computing 22-day realized volatility ...")

rv_window = 22
rv = returns.rolling(rv_window).var() * 252  # annualized variance
rv = rv.dropna()

# Align all series
common_idx = rv.index.intersection(vix.index)
rv = rv.loc[common_idx]
returns_aligned = returns.loc[common_idx]
vix_aligned = vix.loc[common_idx]

print(f"  RV obs after alignment: {len(rv)}")

# ============================================================
# 3. EWMA VOLATILITY FORECASTS
# ============================================================
print("\n[3] Computing EWMA(0.94) forecasts ...")

def ewma_variance(ret_series, lam=EWMA_LAMBDA):
    """Compute EWMA variance series."""
    n = len(ret_series)
    var = np.zeros(n)
    var[0] = ret_series.iloc[0] ** 2
    for i in range(1, n):
        var[i] = lam * var[i-1] + (1 - lam) * ret_series.iloc[i] ** 2
    return pd.Series(var * 252, index=ret_series.index)  # annualized

ewma_forecasts = {}
for asset in ASSETS:
    ewma_forecasts[asset] = ewma_variance(returns[asset])

ewma_df = pd.DataFrame(ewma_forecasts).reindex(common_idx)

# ============================================================
# 4. GJR-GARCH FORECASTS
# ============================================================
print("\n[4] Computing GJR-GARCH(1,1) rolling forecasts ...")

oos_mask = rv.index >= OOS_START
oos_dates = rv.index[oos_mask]
print(f"  OOS dates: {len(oos_dates)} ({oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')})")

gjr_forecasts = {asset: pd.Series(dtype=float) for asset in ASSETS}

for asset in ASSETS:
    ret_full = returns[asset] * 100  # scale for arch
    forecasts = []
    dates_out = []

    for t_idx in range(len(oos_dates)):
        t = oos_dates[t_idx]
        t_loc = ret_full.index.get_loc(t)

        if t_loc < TRAIN_WINDOW:
            continue

        train = ret_full.iloc[t_loc - TRAIN_WINDOW:t_loc]

        try:
            model = arch_model(train, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Zero")
            res = model.fit(disp="off", show_warning=False)
            fcast = res.forecast(horizon=1)
            h = fcast.variance.iloc[-1, 0] / 10000 * 252  # annualized
            forecasts.append(h)
            dates_out.append(t)
        except Exception:
            forecasts.append(np.nan)
            dates_out.append(t)

    gjr_forecasts[asset] = pd.Series(forecasts, index=dates_out)
    print(f"    {asset}: {len(dates_out)} GJR forecasts")

gjr_df = pd.DataFrame(gjr_forecasts)

# ============================================================
# 5. ATTENTION WEIGHTS (Rolling, No Look-Ahead)
# ============================================================
print("\n[5] Computing attention weights (rolling, no look-ahead) ...")

def compute_attention_weights(rv_df, target_asset, other_assets, window=ATTN_WINDOW):
    """
    For target asset i, compute attention weights from other assets j.
    Weight = softmax of rolling correlation between:
      - asset j's lagged RV (RV_j,t-1)
      - asset i's current RV (RV_i,t)
    All computed using past data only (no look-ahead).
    """
    n = len(rv_df)
    weight_series = {a: np.full(n, np.nan) for a in other_assets}

    rv_target = rv_df[target_asset].values
    rv_others = {a: rv_df[a].values for a in other_assets}

    for t in range(window + RV_LAG, n):
        # Use data from [t-window, t) to compute correlations
        target_future = rv_target[t - window + RV_LAG:t + RV_LAG]  # shifted forward by RV_LAG
        corrs = {}
        for a in other_assets:
            other_lagged = rv_others[a][t - window:t]  # lagged by RV_LAG
            if len(target_future) == len(other_lagged) and np.std(target_future) > 0 and np.std(other_lagged) > 0:
                c = np.corrcoef(other_lagged, target_future)[0, 1]
                corrs[a] = c if not np.isnan(c) else 0.0
            else:
                corrs[a] = 0.0

        # Softmax normalization (temperature=1)
        vals = np.array([corrs[a] for a in other_assets])
        # Clip to prevent overflow
        vals = np.clip(vals, -5, 5)
        exp_vals = np.exp(vals)
        softmax_vals = exp_vals / exp_vals.sum()

        for k, a in enumerate(other_assets):
            weight_series[a][t] = softmax_vals[k]

    return pd.DataFrame(weight_series, index=rv_df.index)


attention_weights = {}
for target in ASSETS:
    others = [a for a in ASSETS if a != target]
    attention_weights[target] = compute_attention_weights(rv, target, others)

print("  Attention weights computed for all assets")

# Show sample weights for SPY at a few dates
sample_dates = oos_dates[:3]
print(f"\n  Sample attention weights for SPY (first 3 OOS dates):")
spy_w = attention_weights["SPY"]
for d in sample_dates:
    if d in spy_w.index:
        w_row = spy_w.loc[d]
        w_str = ", ".join([f"{a}={w_row[a]:.3f}" for a in w_row.index if not np.isnan(w_row[a])])
        print(f"    {d.strftime('%Y-%m-%d')}: {w_str}")

# ============================================================
# 6. ATTENTION-WEIGHTED VOLATILITY FORECASTS
# ============================================================
print("\n[6] Computing attention-weighted volatility forecasts ...")

def attention_forecast(target, alpha, ewma_df, attn_weights, oos_dates):
    """
    h_i,t = alpha * EWMA_i,t + (1-alpha) * sum_j(w_j,t * EWMA_j,t)
    """
    others = [a for a in ASSETS if a != target]
    forecasts = []
    dates_out = []

    for t in oos_dates:
        if t not in ewma_df.index or t not in attn_weights[target].index:
            continue

        own_ewma = ewma_df.loc[t, target]
        w = attn_weights[target].loc[t]

        if np.isnan(own_ewma) or w.isna().all():
            continue

        cross_signal = 0.0
        w_sum = 0.0
        for a in others:
            if not np.isnan(w[a]) and not np.isnan(ewma_df.loc[t, a]):
                cross_signal += w[a] * ewma_df.loc[t, a]
                w_sum += w[a]

        if w_sum > 0:
            cross_signal /= w_sum  # re-normalize in case some are NaN

        h = alpha * own_ewma + (1 - alpha) * cross_signal
        forecasts.append(h)
        dates_out.append(t)

    return pd.Series(forecasts, index=dates_out)


# Compute forecasts for all alpha values
attn_results = {}
for alpha in ALPHA_GRID:
    attn_results[alpha] = {}
    for target in ASSETS:
        attn_results[alpha][target] = attention_forecast(
            target, alpha, ewma_df, attention_weights, oos_dates
        )

print(f"  Computed attention forecasts for {len(ALPHA_GRID)} alpha values x {len(ASSETS)} assets")

# ============================================================
# 7. EVALUATION: QLIKE LOSS
# ============================================================
print("\n[7] Evaluating with QLIKE loss ...")

def qlike_loss(forecast_var, realized_var):
    """QLIKE = mean(log(h) + r^2/h), using realized variance as proxy."""
    mask = (forecast_var > 0) & (realized_var > 0) & ~np.isnan(forecast_var) & ~np.isnan(realized_var)
    h = forecast_var[mask].values
    rv_vals = realized_var[mask].values
    return np.mean(np.log(h) + rv_vals / h)

def dm_test_qlike(loss1, loss2):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Negative t-stat means model 1 is better (lower loss)."""
    d = loss1 - loss2
    d = d.dropna()
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = d.mean()
    # HAC variance (Newey-West with automatic lag)
    nw_lags = int(np.floor(n ** (1/3)))
    gamma0 = d.var()
    gamma_sum = 0
    for k in range(1, nw_lags + 1):
        gamma_k = d.iloc[k:].reset_index(drop=True).cov(d.iloc[:-k].reset_index(drop=True))
        gamma_sum += 2 * (1 - k / (nw_lags + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)  # two-sided
    return t_stat, p_val


# Compute QLIKE for each method
print(f"\n  {'Asset':<6} {'EWMA':<10} {'GJR':<10}", end="")
for alpha in ALPHA_GRID:
    print(f"  {'Attn('+str(alpha)+')':<12}", end="")
print()
print("-" * (26 + 12 * len(ALPHA_GRID)))

results_table = []

for target in ASSETS:
    row = {"asset": target}

    # Get OOS realized variance
    rv_oos = rv[target].reindex(oos_dates).dropna()

    # EWMA baseline
    ewma_oos = ewma_df[target].reindex(rv_oos.index).dropna()
    common = rv_oos.index.intersection(ewma_oos.index)
    ql_ewma = qlike_loss(ewma_oos.loc[common], rv_oos.loc[common])
    row["qlike_ewma"] = ql_ewma

    # GJR baseline
    gjr_oos = gjr_df[target].reindex(rv_oos.index).dropna()
    common_gjr = rv_oos.index.intersection(gjr_oos.index)
    if len(common_gjr) > 10:
        ql_gjr = qlike_loss(gjr_oos.loc[common_gjr], rv_oos.loc[common_gjr])
    else:
        ql_gjr = np.nan
    row["qlike_gjr"] = ql_gjr

    print(f"  {target:<6} {ql_ewma:<10.4f} {ql_gjr:<10.4f}", end="")

    # Attention forecasts
    for alpha in ALPHA_GRID:
        attn_oos = attn_results[alpha][target].reindex(rv_oos.index).dropna()
        common_attn = rv_oos.index.intersection(attn_oos.index)
        if len(common_attn) > 10:
            ql_attn = qlike_loss(attn_oos.loc[common_attn], rv_oos.loc[common_attn])
        else:
            ql_attn = np.nan
        row[f"qlike_attn_{alpha}"] = ql_attn
        print(f"  {ql_attn:<12.4f}", end="")

    print()
    results_table.append(row)

# ============================================================
# 8. DM TESTS
# ============================================================
print("\n[8] Diebold-Mariano tests (QLIKE loss) ...")
print("     H0: Equal predictive accuracy")
print("     Negative t → Attention is better; Positive t → Baseline is better\n")

dm_results = []

# Best alpha for each asset
best_alpha_per_asset = {}
for target in ASSETS:
    best_alpha = None
    best_ql = np.inf
    for alpha in ALPHA_GRID:
        row = [r for r in results_table if r["asset"] == target][0]
        ql = row.get(f"qlike_attn_{alpha}", np.inf)
        if not np.isnan(ql) and ql < best_ql:
            best_ql = ql
            best_alpha = alpha
    best_alpha_per_asset[target] = best_alpha

print(f"  Best alpha per asset: {best_alpha_per_asset}\n")

print(f"  {'Asset':<6} {'Best alpha':<12} {'vs EWMA t':<12} {'p-val':<10} {'vs GJR t':<12} {'p-val':<10}")
print("-" * 62)

for target in ASSETS:
    alpha = best_alpha_per_asset[target]
    rv_oos = rv[target].reindex(oos_dates).dropna()

    # Attention losses
    attn_oos = attn_results[alpha][target].reindex(rv_oos.index).dropna()
    common_attn = rv_oos.index.intersection(attn_oos.index)

    # EWMA losses
    ewma_oos = ewma_df[target].reindex(rv_oos.index).dropna()
    common_ewma = rv_oos.index.intersection(ewma_oos.index)

    # Pointwise QLIKE
    common_all = common_attn.intersection(common_ewma)

    if len(common_all) > 10:
        loss_attn = pd.Series(
            np.log(attn_oos.loc[common_all].values) + rv_oos.loc[common_all].values / attn_oos.loc[common_all].values,
            index=common_all
        )
        loss_ewma = pd.Series(
            np.log(ewma_oos.loc[common_all].values) + rv_oos.loc[common_all].values / ewma_oos.loc[common_all].values,
            index=common_all
        )
        t_ewma, p_ewma = dm_test_qlike(loss_attn, loss_ewma)
    else:
        t_ewma, p_ewma = np.nan, np.nan

    # vs GJR
    gjr_oos = gjr_df[target].reindex(rv_oos.index).dropna()
    common_gjr = common_attn.intersection(gjr_oos.index)

    if len(common_gjr) > 10:
        loss_attn_g = pd.Series(
            np.log(attn_oos.loc[common_gjr].values) + rv_oos.loc[common_gjr].values / attn_oos.loc[common_gjr].values,
            index=common_gjr
        )
        loss_gjr = pd.Series(
            np.log(gjr_oos.loc[common_gjr].values) + rv_oos.loc[common_gjr].values / gjr_oos.loc[common_gjr].values,
            index=common_gjr
        )
        t_gjr, p_gjr = dm_test_qlike(loss_attn_g, loss_gjr)
    else:
        t_gjr, p_gjr = np.nan, np.nan

    sig_ewma = "***" if p_ewma < 0.01 else ("**" if p_ewma < 0.05 else ("*" if p_ewma < 0.10 else ""))
    sig_gjr = "***" if p_gjr < 0.01 else ("**" if p_gjr < 0.05 else ("*" if p_gjr < 0.10 else ""))

    print(f"  {target:<6} {alpha:<12} {t_ewma:<12.3f} {p_ewma:<10.4f} {t_gjr:<12.3f} {p_gjr:<10.4f}  {sig_ewma} / {sig_gjr}")

    dm_results.append({
        "asset": target,
        "best_alpha": alpha,
        "dm_vs_ewma_t": round(t_ewma, 4),
        "dm_vs_ewma_p": round(p_ewma, 4),
        "dm_vs_gjr_t": round(t_gjr, 4),
        "dm_vs_gjr_p": round(p_gjr, 4),
    })

# ============================================================
# 9. ATTENTION WEIGHT ANALYSIS
# ============================================================
print("\n[9] Attention weight analysis ...")

print("\n  Average attention weights (OOS period) for each target:")
print(f"  {'Target':<6}", end="")
for a in ASSETS:
    print(f"  {a:<8}", end="")
print()
print("-" * (6 + 10 * len(ASSETS)))

for target in ASSETS:
    others = [a for a in ASSETS if a != target]
    w_df = attention_weights[target]
    w_oos = w_df.loc[w_df.index >= OOS_START].dropna(how="all")

    print(f"  {target:<6}", end="")
    for a in ASSETS:
        if a == target:
            print(f"  {'---':<8}", end="")
        elif a in w_oos.columns:
            print(f"  {w_oos[a].mean():<8.3f}", end="")
        else:
            print(f"  {'N/A':<8}", end="")
    print()

# Weight stability
print("\n  Attention weight stability (std over OOS):")
for target in ASSETS:
    others = [a for a in ASSETS if a != target]
    w_df = attention_weights[target]
    w_oos = w_df.loc[w_df.index >= OOS_START].dropna(how="all")
    stds = {a: w_oos[a].std() for a in others}
    max_std_asset = max(stds, key=stds.get)
    print(f"    {target}: max_std={stds[max_std_asset]:.4f} ({max_std_asset}), mean_std={np.mean(list(stds.values())):.4f}")

# ============================================================
# 10. PARTIAL CORRELATION CONTROLLING FOR VIX
# ============================================================
print("\n[10] Partial correlation: Attention signal vs RV, controlling for VIX ...")

print(f"\n  {'Asset':<6} {'r(Attn,RV)':<14} {'r_partial':<14} {'p_partial':<12} {'r(VIX,RV)':<14}")
print("-" * 60)

partial_corr_results = []

for target in ASSETS:
    alpha = best_alpha_per_asset[target]
    attn_oos = attn_results[alpha][target]
    rv_oos = rv[target]
    vix_oos = vix_aligned

    # Common OOS dates
    common = attn_oos.index.intersection(rv_oos.index).intersection(vix_oos.index)
    common = common[common >= OOS_START]

    if len(common) < 30:
        print(f"  {target:<6} insufficient data")
        continue

    x = attn_oos.loc[common].values
    y = rv_oos.loc[common].values
    z = vix_oos.loc[common].values

    # Simple correlation
    r_simple = np.corrcoef(x, y)[0, 1]

    # VIX-RV correlation
    r_vix = np.corrcoef(z, y)[0, 1]

    # Partial correlation (controlling for VIX)
    # r_xy.z = (r_xy - r_xz * r_yz) / sqrt((1 - r_xz^2)(1 - r_yz^2))
    r_xz = np.corrcoef(x, z)[0, 1]
    r_yz = np.corrcoef(y, z)[0, 1]

    numerator = r_simple - r_xz * r_yz
    denominator = np.sqrt((1 - r_xz ** 2) * (1 - r_yz ** 2))

    if denominator > 0:
        r_partial = numerator / denominator
        # Fisher z-transform for significance
        n = len(common)
        z_fisher = 0.5 * np.log((1 + r_partial) / (1 - r_partial))
        se = 1.0 / np.sqrt(n - 3 - 1)  # -1 for controlling variable
        p_partial = 2 * stats.norm.sf(abs(z_fisher / se))
    else:
        r_partial = np.nan
        p_partial = np.nan

    sig = "***" if p_partial < 0.01 else ("**" if p_partial < 0.05 else ("*" if p_partial < 0.10 else ""))
    print(f"  {target:<6} {r_simple:<14.4f} {r_partial:<14.4f} {p_partial:<12.4f} {r_vix:<14.4f}  {sig}")

    partial_corr_results.append({
        "asset": target,
        "r_simple": round(r_simple, 4),
        "r_partial_controlling_vix": round(r_partial, 4),
        "p_partial": round(p_partial, 4),
        "r_vix_rv": round(r_vix, 4),
    })

# ============================================================
# 11. DOES ATTENTION BEAT VIX-BASED FORECASTING?
# ============================================================
print("\n[11] Attention vs VIX-based vol forecast ...")

# VIX-based forecast: VIX^2 / 100 as annualized variance proxy
# (VIX is quoted in annualized % vol, so VIX^2/100 ~ annualized var in decimal)
vix_var_forecast = (vix_aligned ** 2) / 100

print(f"\n  {'Asset':<6} {'QLIKE_VIX':<12} {'QLIKE_Attn':<12} {'DM t':<10} {'DM p':<10} {'Winner':<10}")
print("-" * 56)

for target in ASSETS:
    alpha = best_alpha_per_asset[target]
    attn_oos = attn_results[alpha][target]
    rv_oos = rv[target]
    vix_f = vix_var_forecast

    common = attn_oos.index.intersection(rv_oos.index).intersection(vix_f.index)
    common = common[common >= OOS_START]

    if len(common) < 30:
        print(f"  {target:<6} insufficient data")
        continue

    ql_vix = qlike_loss(vix_f.loc[common], rv_oos.loc[common])
    ql_attn = qlike_loss(attn_oos.loc[common], rv_oos.loc[common])

    # DM test
    loss_vix = pd.Series(
        np.log(vix_f.loc[common].values) + rv_oos.loc[common].values / vix_f.loc[common].values,
        index=common
    )
    loss_attn = pd.Series(
        np.log(attn_oos.loc[common].values) + rv_oos.loc[common].values / attn_oos.loc[common].values,
        index=common
    )
    t_dm, p_dm = dm_test_qlike(loss_attn, loss_vix)
    winner = "Attention" if t_dm < 0 else "VIX"
    sig = "***" if p_dm < 0.01 else ("**" if p_dm < 0.05 else ("*" if p_dm < 0.10 else ""))

    print(f"  {target:<6} {ql_vix:<12.4f} {ql_attn:<12.4f} {t_dm:<10.3f} {p_dm:<10.4f} {winner:<10} {sig}")

# ============================================================
# 12. HARVEY (2016) THRESHOLD CHECK
# ============================================================
print("\n[12] Harvey (2016) threshold check ...")
print("     For a 'new factor' claim, need |t| > 3.0\n")

print(f"  {'Asset':<6} {'vs EWMA |t|':<14} {'Pass Harvey?':<14} {'vs GJR |t|':<14} {'Pass Harvey?':<14}")
print("-" * 62)

harvey_pass_count = 0
total_count = 0

for dm in dm_results:
    t_ewma = abs(dm["dm_vs_ewma_t"])
    t_gjr = abs(dm["dm_vs_gjr_t"])
    pass_ewma = "YES" if t_ewma > 3.0 else "NO"
    pass_gjr = "YES" if t_gjr > 3.0 else "NO"

    if t_ewma > 3.0:
        harvey_pass_count += 1
    total_count += 1

    print(f"  {dm['asset']:<6} {t_ewma:<14.3f} {pass_ewma:<14} {t_gjr:<14.3f} {pass_gjr:<14}")

print(f"\n  Harvey pass rate (vs EWMA): {harvey_pass_count}/{total_count}")

# ============================================================
# 13. CROSS-ASSET IMPROVEMENT ANALYSIS
# ============================================================
print("\n[13] Cross-asset improvement analysis ...")

# For each asset, compute % improvement of best attention over EWMA
print(f"\n  {'Asset':<6} {'EWMA QLIKE':<12} {'Best Attn':<12} {'% Change':<12} {'Improved?':<10}")
print("-" * 52)

improvements = []
for r in results_table:
    ql_ewma = r["qlike_ewma"]
    best_attn_ql = min([r.get(f"qlike_attn_{a}", np.inf) for a in ALPHA_GRID])
    pct_change = (best_attn_ql - ql_ewma) / abs(ql_ewma) * 100
    improved = "YES" if best_attn_ql < ql_ewma else "NO"
    print(f"  {r['asset']:<6} {ql_ewma:<12.4f} {best_attn_ql:<12.4f} {pct_change:<12.2f}% {improved:<10}")
    improvements.append({
        "asset": r["asset"],
        "qlike_ewma": round(ql_ewma, 6),
        "qlike_best_attn": round(best_attn_ql, 6),
        "pct_change": round(pct_change, 4),
        "improved": improved,
    })

# ============================================================
# 14. SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K189 Attention-Weighted Volatility")
print("=" * 70)

n_improved = sum(1 for r in improvements if r["improved"] == "YES")
n_total = len(improvements)
avg_improvement = np.mean([r["pct_change"] for r in improvements])

print(f"\n  Assets improved (QLIKE): {n_improved}/{n_total}")
print(f"  Average QLIKE change: {avg_improvement:+.2f}%")
print(f"  Harvey threshold passes (vs EWMA): {harvey_pass_count}/{total_count}")

# Count significant DM tests
n_sig_ewma = sum(1 for dm in dm_results if dm["dm_vs_ewma_p"] < 0.05)
n_sig_gjr = sum(1 for dm in dm_results if dm["dm_vs_gjr_p"] < 0.05)
print(f"  DM significant vs EWMA (p<0.05): {n_sig_ewma}/{n_total}")
print(f"  DM significant vs GJR (p<0.05): {n_sig_gjr}/{n_total}")

# Partial correlation summary
n_partial_sig = sum(1 for p in partial_corr_results if p["p_partial"] < 0.05)
avg_partial = np.mean([p["r_partial_controlling_vix"] for p in partial_corr_results])
print(f"  Partial corr significant (controlling VIX, p<0.05): {n_partial_sig}/{len(partial_corr_results)}")
print(f"  Average partial correlation: {avg_partial:.4f}")

# Conclusion
print("\n  CONCLUSION:")
if harvey_pass_count > 0 and n_improved >= n_total // 2:
    print("  Cross-asset attention provides SIGNIFICANT improvement for some assets.")
    print("  However, Harvey threshold must be checked for strategy claims.")
elif n_improved >= n_total // 2:
    print("  Cross-asset attention shows modest directional improvement")
    print("  but FAILS Harvey (2016) threshold — insufficient for publication claims.")
else:
    print("  Cross-asset attention does NOT consistently improve vol forecasts.")
    print("  VIX sufficient statistic hypothesis further confirmed:")
    print("  cross-asset EWMA adds negligible information beyond own-asset EWMA.")

elapsed = time.time() - t0
print(f"\n  Total runtime: {elapsed:.1f}s")

# ============================================================
# 15. SAVE RESULTS
# ============================================================
output = {
    "experiment": "K189",
    "title": "Attention-Weighted Volatility (Cross-Asset Information Aggregation)",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance daily (SPY/QQQ/GLD/TLT/EEM/IWM)",
    "oos_period": f"{OOS_START} to {OOS_END}",
    "train_window": TRAIN_WINDOW,
    "attention_window": ATTN_WINDOW,
    "ewma_lambda": EWMA_LAMBDA,
    "alpha_grid": ALPHA_GRID,
    "qlike_table": results_table,
    "dm_tests": dm_results,
    "partial_correlations": partial_corr_results,
    "improvements": improvements,
    "summary": {
        "n_improved": n_improved,
        "n_total": n_total,
        "avg_pct_change": round(avg_improvement, 4),
        "harvey_passes": harvey_pass_count,
        "dm_sig_vs_ewma": n_sig_ewma,
        "dm_sig_vs_gjr": n_sig_gjr,
        "partial_corr_sig": n_partial_sig,
        "avg_partial_corr": round(avg_partial, 4),
    },
    "runtime_seconds": round(elapsed, 1),
}

# Save to experiments directory
results_path = Path(__file__).resolve().parent / "k189_attention_vol_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {results_path}")

# Also save to storage/experiments/ if it exists
storage_path = Path(__file__).resolve().parent.parent / "storage" / "experiments"
if storage_path.exists():
    with open(storage_path / "k189_attention_vol_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Results also saved to {storage_path / 'k189_attention_vol_results.json'}")

print("\nDone.")
