#!/usr/bin/env python3
"""K136: BTC Derivatives-Conditioned Volatility Model

Codex Round 2 #2 suggests BTC volatility is "leverage-crowding-conditioned,
not equity-style leverage-effect-conditioned". K132 showed GJR capture rate
only 15% for BTC. This experiment tests BTC-specific vol predictors using
freely available data proxies.

Predictors tested:
1. Volume spike (volume / MA20_volume) — liquidation cascade proxy
2. Return asymmetry — separate up vs down vol contributions
3. Weekend effect — crypto 24/7 trading
4. Momentum state — sign(22d return)
5. VIX cross-effect — VIX changes affecting BTC vol
6. Realized vol regime — high/low RV state

Methods:
- GARCH-X models with each predictor
- Compare vs plain GARCH and EWMA(0.94)
- QLIKE + DM test for statistical evaluation
- OOS: 2023-01-01 ~ 2024-12-31

[提出: Codex Round 2 #2, 執行: Claude]
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime
import json


# ─── Helper functions ────────────────────────────────────────────
def qlike_loss(realized_var, forecast_var):
    """QLIKE loss: log(forecast) + realized/forecast. Lower is better."""
    valid = (forecast_var > 0) & (realized_var > 0) & np.isfinite(realized_var) & np.isfinite(forecast_var)
    r = realized_var[valid]
    f = forecast_var[valid]
    return np.mean(np.log(f) + r / f)


def dm_test(loss1, loss2):
    """Diebold-Mariano test. H0: equal predictive ability.
    Negative t-stat means loss1 < loss2 (model 1 better)."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    # Newey-West with lag = int(n^(1/3))
    lag = max(1, int(n ** (1 / 3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag + 1):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value


def ewma_variance(returns, lam=0.94):
    """EWMA variance with decay factor lambda."""
    n = len(returns)
    var = np.zeros(n)
    var[0] = returns[0] ** 2
    for i in range(1, n):
        var[i] = lam * var[i - 1] + (1 - lam) * returns[i - 1] ** 2
    return var


# ─── Data Download ───────────────────────────────────────────────
print("=" * 70)
print("K136: BTC Derivatives-Conditioned Volatility Model")
print("=" * 70)

# Download BTC-USD and VIX
print("\n[1] Downloading data...")
btc = yf.download("BTC-USD", start="2017-01-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2017-01-01", end="2025-01-01", progress=False)

# Handle MultiIndex columns from yfinance
if isinstance(btc.columns, pd.MultiIndex):
    btc.columns = btc.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  BTC-USD: {len(btc)} rows, {btc.index[0].strftime('%Y-%m-%d')} to {btc.index[-1].strftime('%Y-%m-%d')}")
print(f"  VIX:     {len(vix)} rows")

# Compute returns
btc["ret"] = np.log(btc["Close"] / btc["Close"].shift(1))
btc["ret_pct"] = btc["ret"] * 100  # percentage for GARCH
btc["realized_var"] = btc["ret"] ** 2  # squared return as proxy
btc["volume_raw"] = btc["Volume"]

# Align VIX to BTC dates (forward fill for weekends/holidays)
vix_close = vix[["Close"]].rename(columns={"Close": "vix"})
btc = btc.join(vix_close, how="left")
btc["vix"] = btc["vix"].ffill()
btc["vix_ret"] = btc["vix"].pct_change()

btc = btc.dropna(subset=["ret"])

print(f"  After cleaning: {len(btc)} rows")


# ─── Construct BTC-Specific Predictors ───────────────────────────
print("\n[2] Constructing BTC-specific predictors...")

# 1. Volume Spike: volume / MA(20, volume)
btc["vol_ma20"] = btc["volume_raw"].rolling(20).mean()
btc["volume_spike"] = btc["volume_raw"] / btc["vol_ma20"]

# 2. Return Asymmetry: separate up/down vol
btc["ret_pos"] = np.where(btc["ret"] > 0, btc["ret"], 0)
btc["ret_neg"] = np.where(btc["ret"] < 0, btc["ret"], 0)
btc["rv_up_22d"] = (btc["ret_pos"] ** 2).rolling(22).sum()
btc["rv_down_22d"] = (btc["ret_neg"] ** 2).rolling(22).sum()
btc["updown_ratio"] = btc["rv_up_22d"] / (btc["rv_down_22d"] + 1e-10)

# 3. Weekend Effect: is it a weekend? (crypto trades 24/7)
btc["is_weekend"] = btc.index.dayofweek.isin([5, 6]).astype(float)

# 4. Momentum State: sign of 22d return
btc["mom_22d"] = btc["Close"].pct_change(22)
btc["mom_state"] = np.sign(btc["mom_22d"])

# 5. VIX cross-effect: VIX level and change
btc["vix_level"] = btc["vix"]
btc["vix_chg"] = btc["vix_ret"]

# 6. Realized Vol Regime: 22d RV
btc["rv_22d"] = btc["ret"].rolling(22).std() * np.sqrt(252)
btc["rv_regime"] = np.where(btc["rv_22d"] > btc["rv_22d"].rolling(252).median(), 1, 0)

# 7. Absolute return (yesterday) — persistence proxy
btc["abs_ret_lag1"] = np.abs(btc["ret"]).shift(1)

# 8. Volume-weighted return magnitude
btc["vol_weighted_abs_ret"] = np.abs(btc["ret"]) * btc["volume_spike"]

# Drop NaN rows
btc_clean = btc.dropna(subset=[
    "volume_spike", "updown_ratio", "mom_state", "vix_level",
    "vix_chg", "rv_22d", "rv_regime", "abs_ret_lag1"
]).copy()

print(f"  Clean data: {len(btc_clean)} rows")
print(f"  Date range: {btc_clean.index[0].strftime('%Y-%m-%d')} to {btc_clean.index[-1].strftime('%Y-%m-%d')}")


# ─── Descriptive Statistics of Predictors ────────────────────────
print("\n" + "=" * 70)
print("[3] Descriptive Statistics of BTC-Specific Predictors")
print("=" * 70)

predictor_cols = [
    "volume_spike", "updown_ratio", "is_weekend", "mom_state",
    "vix_level", "vix_chg", "rv_22d", "rv_regime", "abs_ret_lag1"
]

for col in predictor_cols:
    s = btc_clean[col]
    print(f"\n  {col}:")
    print(f"    Mean={s.mean():.4f}, Std={s.std():.4f}, "
          f"Min={s.min():.4f}, Max={s.max():.4f}, "
          f"Skew={s.skew():.2f}, Kurt={s.kurtosis():.2f}")

# Correlation of predictors with next-day squared return
print("\n  Correlation with next-day squared return (r²_t+1):")
fwd_rv = btc_clean["realized_var"].shift(-1)
for col in predictor_cols:
    corr = btc_clean[col].corr(fwd_rv)
    print(f"    {col:25s}: r = {corr:.4f}")


# ─── Up-vol vs Down-vol Analysis ─────────────────────────────────
print("\n" + "=" * 70)
print("[4] BTC Up-Vol vs Down-Vol Decomposition")
print("=" * 70)

# Monthly decomposition
btc_clean["year_month"] = btc_clean.index.to_period("M")
monthly = btc_clean.groupby("year_month").agg(
    rv_up=("rv_up_22d", "last"),
    rv_down=("rv_down_22d", "last"),
    ret_total=("ret", "sum"),
).dropna()

# Overall stats
total_rv_up = btc_clean["ret_pos"].pow(2).sum()
total_rv_down = btc_clean["ret_neg"].pow(2).sum()
pct_up = total_rv_up / (total_rv_up + total_rv_down) * 100
pct_down = total_rv_down / (total_rv_up + total_rv_down) * 100

print(f"  Total RV from up-moves:   {pct_up:.1f}%")
print(f"  Total RV from down-moves: {pct_down:.1f}%")
print(f"  Up/Down ratio: {total_rv_up / total_rv_down:.3f}")

# By regime
bull = btc_clean[btc_clean["mom_state"] == 1]
bear = btc_clean[btc_clean["mom_state"] == -1]

if len(bull) > 0:
    bull_up = bull["ret_pos"].pow(2).sum()
    bull_down = bull["ret_neg"].pow(2).sum()
    print(f"\n  Bull regime ({len(bull)} days):")
    print(f"    Up-vol contribution: {bull_up / (bull_up + bull_down) * 100:.1f}%")

if len(bear) > 0:
    bear_up = bear["ret_pos"].pow(2).sum()
    bear_down = bear["ret_neg"].pow(2).sum()
    print(f"  Bear regime ({len(bear)} days):")
    print(f"    Up-vol contribution: {bear_up / (bear_up + bear_down) * 100:.1f}%")

# GJR gamma by regime
print("\n  GJR-GARCH gamma by momentum regime:")
for regime_name, regime_data in [("Bull", bull), ("Bear", bear)]:
    if len(regime_data) < 500:
        print(f"    {regime_name}: insufficient data ({len(regime_data)} < 500)")
        continue
    try:
        am = arch_model(regime_data["ret_pct"].values, vol="GARCH", p=1, o=1, q=1, dist="t")
        res = am.fit(disp="off")
        gamma = res.params.get("gamma[1]", np.nan)
        print(f"    {regime_name}: gamma = {gamma:.4f} (t = {gamma / res.std_err.get('gamma[1]', np.nan):.2f})")
    except Exception as e:
        print(f"    {regime_name}: GARCH failed ({e})")


# ─── Weekend Effect Analysis ─────────────────────────────────────
print("\n" + "=" * 70)
print("[5] Weekend vs Weekday Volatility")
print("=" * 70)

weekday = btc_clean[btc_clean["is_weekend"] == 0]
weekend = btc_clean[btc_clean["is_weekend"] == 1]

if len(weekend) > 10:
    wd_vol = weekday["ret"].std() * np.sqrt(252) * 100
    we_vol = weekend["ret"].std() * np.sqrt(252) * 100
    print(f"  Weekday annualized vol: {wd_vol:.1f}%  ({len(weekday)} days)")
    print(f"  Weekend annualized vol: {we_vol:.1f}%  ({len(weekend)} days)")
    print(f"  Weekend/Weekday ratio:  {we_vol / wd_vol:.3f}")

    # Welch t-test on squared returns
    t_stat, p_val = stats.ttest_ind(
        weekend["realized_var"].values,
        weekday["realized_var"].values,
        equal_var=False
    )
    print(f"  Welch t-test on squared returns: t={t_stat:.3f}, p={p_val:.4f}")
else:
    print("  Insufficient weekend data (BTC trades on weekends but yfinance may skip)")


# ─── Volume Spike and Volatility ─────────────────────────────────
print("\n" + "=" * 70)
print("[6] Volume Spike Analysis (Liquidation Cascade Proxy)")
print("=" * 70)

# Quintile analysis
btc_clean["vol_spike_q"] = pd.qcut(btc_clean["volume_spike"], 5, labels=False, duplicates="drop")
print("\n  Volume spike quintile → next-day volatility:")
for q in sorted(btc_clean["vol_spike_q"].dropna().unique()):
    subset = btc_clean[btc_clean["vol_spike_q"] == q]
    next_rv = subset["realized_var"].shift(-1).dropna()
    ann_vol = np.sqrt(next_rv.mean()) * np.sqrt(252) * 100
    print(f"    Q{int(q)}: mean next-day ann. vol = {ann_vol:.1f}% (n={len(next_rv)})")

# Extreme volume spike (>2x average)
extreme = btc_clean[btc_clean["volume_spike"] > 2.0]
normal = btc_clean[btc_clean["volume_spike"] <= 2.0]
if len(extreme) > 10:
    ext_rv = np.sqrt(extreme["realized_var"].shift(-1).dropna().mean()) * np.sqrt(252) * 100
    nor_rv = np.sqrt(normal["realized_var"].shift(-1).dropna().mean()) * np.sqrt(252) * 100
    print(f"\n  Extreme volume spike (>2x avg): next-day ann. vol = {ext_rv:.1f}% (n={len(extreme)})")
    print(f"  Normal volume (<= 2x avg):      next-day ann. vol = {nor_rv:.1f}% (n={len(normal)})")
    print(f"  Ratio: {ext_rv / nor_rv:.3f}")


# ─── GARCH-X Models ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("[7] GARCH-X Model Comparison (OOS: 2023-01-01 ~ 2024-12-31)")
print("=" * 70)

# Define OOS period
oos_start = "2023-01-01"
oos_end = "2024-12-31"
window = 1000  # rolling window

# Prepare data
data = btc_clean[["ret_pct", "realized_var", "volume_spike", "updown_ratio",
                   "is_weekend", "mom_state", "vix_level", "vix_chg",
                   "rv_22d", "rv_regime", "abs_ret_lag1"]].copy()
data = data.dropna()

# OOS indices
oos_mask = (data.index >= oos_start) & (data.index <= oos_end)
oos_indices = data.index[oos_mask]
n_oos = len(oos_indices)
print(f"  OOS period: {oos_indices[0].strftime('%Y-%m-%d')} to {oos_indices[-1].strftime('%Y-%m-%d')} ({n_oos} days)")

# Model specifications
models = {
    "GARCH(1,1)": {"type": "plain"},
    "GJR-GARCH": {"type": "gjr"},
    "EWMA(0.94)": {"type": "ewma", "lam": 0.94},
}

# GARCH-X models with external regressors
# We'll use a manual approach: fit GARCH, then regress standardized residuals on X
# Actually, arch library supports exogenous variables in mean equation
# But for variance equation, we need a different approach

# Approach: HAR-like regression with GARCH residuals
# 1. Fit plain GARCH to get conditional variance
# 2. Compute variance ratio = realized_var / garch_var
# 3. Regress variance ratio on predictors
# 4. Adjust GARCH forecast by predicted ratio

# Simpler approach: Use rolling regression
# σ²_t = α + β₁·GARCH_forecast_t + β₂·X_{t-1}

results = {}

# 1. Plain GARCH rolling forecast
print("\n  Running rolling GARCH forecasts...")
garch_forecasts = np.full(n_oos, np.nan)
gjr_forecasts = np.full(n_oos, np.nan)
ewma_forecasts = np.full(n_oos, np.nan)
realized = np.full(n_oos, np.nan)

ret_pct_arr = data["ret_pct"].values
realized_arr = data["realized_var"].values
all_indices = data.index.tolist()

for i, oos_date in enumerate(oos_indices):
    idx = all_indices.index(oos_date)
    if idx < window:
        continue

    train_ret = ret_pct_arr[idx - window:idx]
    realized[i] = realized_arr[idx]

    # Plain GARCH
    try:
        am = arch_model(train_ret, vol="GARCH", p=1, q=1, dist="t", rescale=False)
        res = am.fit(disp="off", show_warning=False)
        fc = res.forecast(horizon=1)
        garch_forecasts[i] = fc.variance.values[-1, 0] / 1e4  # convert back from pct²
    except Exception:
        pass

    # GJR-GARCH
    try:
        am = arch_model(train_ret, vol="GARCH", p=1, o=1, q=1, dist="t", rescale=False)
        res = am.fit(disp="off", show_warning=False)
        fc = res.forecast(horizon=1)
        gjr_forecasts[i] = fc.variance.values[-1, 0] / 1e4
    except Exception:
        pass

    # EWMA
    train_ret_dec = ret_pct_arr[idx - window:idx] / 100  # decimal returns
    ewma_var = ewma_variance(train_ret_dec, lam=0.94)
    ewma_forecasts[i] = ewma_var[-1]

    if (i + 1) % 100 == 0:
        print(f"    Progress: {i + 1}/{n_oos}")

print(f"    Done. Valid forecasts: GARCH={np.sum(~np.isnan(garch_forecasts))}, "
      f"GJR={np.sum(~np.isnan(gjr_forecasts))}, EWMA={np.sum(~np.isnan(ewma_forecasts))}")

# Compute QLIKE for base models
valid = ~np.isnan(garch_forecasts) & ~np.isnan(realized) & (realized > 0) & (garch_forecasts > 0)
qlike_garch = qlike_loss(realized[valid], garch_forecasts[valid])

valid_gjr = ~np.isnan(gjr_forecasts) & ~np.isnan(realized) & (realized > 0) & (gjr_forecasts > 0)
qlike_gjr = qlike_loss(realized[valid_gjr], gjr_forecasts[valid_gjr])

valid_ewma = ~np.isnan(ewma_forecasts) & ~np.isnan(realized) & (realized > 0) & (ewma_forecasts > 0)
qlike_ewma = qlike_loss(realized[valid_ewma], ewma_forecasts[valid_ewma])

print(f"\n  Base model QLIKE:")
print(f"    GARCH(1,1):  {qlike_garch:.6f}")
print(f"    GJR-GARCH:   {qlike_gjr:.6f}")
print(f"    EWMA(0.94):  {qlike_ewma:.6f}")


# ─── GARCH-X: Post-GARCH predictor regression ────────────────────
print("\n" + "=" * 70)
print("[8] GARCH-X Enhancement: Post-GARCH Predictor Regression")
print("=" * 70)

# For each predictor, test if it improves GARCH forecasts
# Method: rolling OLS regression
#   realized_var_t = a + b * garch_forecast_t + c * X_{t-1}
# Then forecast: hat_var_t = a + b * garch_forecast_t + c * X_{t-1}

predictor_names = {
    "volume_spike": "Volume Spike (liquidation proxy)",
    "abs_ret_lag1": "Abs Return Lag-1 (persistence)",
    "vix_chg": "VIX Change (cross-market)",
    "vix_level": "VIX Level",
    "rv_22d": "22d Realized Vol",
    "rv_regime": "RV Regime (high/low)",
    "updown_ratio": "Up/Down Vol Ratio",
    "mom_state": "Momentum State (22d)",
    "is_weekend": "Weekend Dummy",
}

garchx_results = {}
reg_window = 252  # 1 year regression window

for pred_key, pred_name in predictor_names.items():
    # Get predictor values at OOS dates (lagged by 1)
    pred_vals = data[pred_key].shift(1).values  # lag predictor
    garchx_forecasts = np.full(n_oos, np.nan)

    for i, oos_date in enumerate(oos_indices):
        idx = all_indices.index(oos_date)
        if idx < window or np.isnan(garch_forecasts[i]):
            continue

        # Get training data for regression (last reg_window days before OOS)
        reg_start = max(0, i - reg_window)
        reg_end = i

        # Need garch forecasts and predictor values for regression window
        y_reg = realized[reg_start:reg_end]
        x_garch = garch_forecasts[reg_start:reg_end]

        # Get predictor for regression period
        reg_oos_indices = oos_indices[reg_start:reg_end]
        x_pred = np.array([pred_vals[all_indices.index(d)] for d in reg_oos_indices
                           if d in all_indices])

        if len(x_pred) != len(y_reg):
            continue

        # Valid mask
        v = (~np.isnan(y_reg) & ~np.isnan(x_garch) & ~np.isnan(x_pred) &
             (y_reg > 0) & (x_garch > 0) & np.isfinite(x_pred))

        if v.sum() < 30:
            continue

        # OLS regression
        X = np.column_stack([np.ones(v.sum()), x_garch[v], x_pred[v]])
        y = y_reg[v]

        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            # Forecast
            x_pred_today = pred_vals[idx]
            if np.isnan(x_pred_today) or not np.isfinite(x_pred_today):
                continue
            forecast = beta[0] + beta[1] * garch_forecasts[i] + beta[2] * x_pred_today
            garchx_forecasts[i] = max(forecast, 1e-10)  # floor at 0
        except Exception:
            continue

    # Compute QLIKE
    valid_x = (~np.isnan(garchx_forecasts) & ~np.isnan(realized) &
               (realized > 0) & (garchx_forecasts > 0))
    n_valid = valid_x.sum()

    if n_valid > 50:
        ql = qlike_loss(realized[valid_x], garchx_forecasts[valid_x])

        # DM test vs plain GARCH
        loss_garch = np.log(garch_forecasts) + realized / garch_forecasts
        loss_garchx = np.log(garchx_forecasts) + realized / garchx_forecasts

        # Only compare where both valid
        both_valid = valid & valid_x
        if both_valid.sum() > 50:
            dm_t, dm_p = dm_test(loss_garchx[both_valid], loss_garch[both_valid])
        else:
            dm_t, dm_p = np.nan, np.nan

        improvement = (qlike_garch - ql) / abs(qlike_garch) * 100

        garchx_results[pred_key] = {
            "name": pred_name,
            "qlike": ql,
            "qlike_improvement": improvement,
            "dm_t": dm_t,
            "dm_p": dm_p,
            "n_valid": int(n_valid),
        }

        sig = "***" if dm_p < 0.01 else "**" if dm_p < 0.05 else "*" if dm_p < 0.10 else ""
        print(f"  {pred_name:40s}: QLIKE={ql:.6f} (Δ={improvement:+.2f}%) DM t={dm_t:.3f} p={dm_p:.4f} {sig} (n={n_valid})")
    else:
        print(f"  {pred_name:40s}: insufficient valid forecasts ({n_valid})")


# ─── Combined Model ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("[9] Combined GARCH-X (Top Predictors)")
print("=" * 70)

# Use top 3 predictors by QLIKE improvement
if len(garchx_results) >= 3:
    sorted_preds = sorted(garchx_results.items(), key=lambda x: x[1]["qlike"])
    top3 = [k for k, v in sorted_preds[:3]]
    print(f"  Top 3 predictors: {top3}")

    combined_forecasts = np.full(n_oos, np.nan)

    for i, oos_date in enumerate(oos_indices):
        idx = all_indices.index(oos_date)
        if idx < window or np.isnan(garch_forecasts[i]):
            continue

        reg_start = max(0, i - reg_window)
        reg_end = i

        y_reg = realized[reg_start:reg_end]
        x_garch = garch_forecasts[reg_start:reg_end]

        # Get all predictors
        x_preds = []
        for pk in top3:
            pred_vals_k = data[pk].shift(1).values
            reg_oos_indices = oos_indices[reg_start:reg_end]
            xp = np.array([pred_vals_k[all_indices.index(d)] for d in reg_oos_indices
                           if d in all_indices])
            if len(xp) != len(y_reg):
                break
            x_preds.append(xp)

        if len(x_preds) != len(top3):
            continue

        # Valid mask
        v = ~np.isnan(y_reg) & ~np.isnan(x_garch) & (y_reg > 0) & (x_garch > 0)
        for xp in x_preds:
            v = v & ~np.isnan(xp) & np.isfinite(xp)

        if v.sum() < 50:
            continue

        # OLS regression
        X = np.column_stack([np.ones(v.sum()), x_garch[v]] + [xp[v] for xp in x_preds])
        y = y_reg[v]

        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            # Forecast
            x_today = [data[pk].shift(1).values[idx] for pk in top3]
            if any(np.isnan(x) or not np.isfinite(x) for x in x_today):
                continue
            forecast = beta[0] + beta[1] * garch_forecasts[i]
            for j, x in enumerate(x_today):
                forecast += beta[j + 2] * x
            combined_forecasts[i] = max(forecast, 1e-10)
        except Exception:
            continue

    valid_comb = (~np.isnan(combined_forecasts) & ~np.isnan(realized) &
                  (realized > 0) & (combined_forecasts > 0))

    if valid_comb.sum() > 50:
        ql_comb = qlike_loss(realized[valid_comb], combined_forecasts[valid_comb])

        both_valid = valid & valid_comb
        dm_t_comb, dm_p_comb = dm_test(
            (np.log(combined_forecasts) + realized / combined_forecasts)[both_valid],
            (np.log(garch_forecasts) + realized / garch_forecasts)[both_valid]
        )

        improvement_comb = (qlike_garch - ql_comb) / abs(qlike_garch) * 100

        print(f"  Combined GARCH-X QLIKE: {ql_comb:.6f} (Δ={improvement_comb:+.2f}%)")
        print(f"  DM test vs plain GARCH: t={dm_t_comb:.3f}, p={dm_p_comb:.4f}")
        print(f"  Valid forecasts: {valid_comb.sum()}")


# ─── Capture Rate Analysis ───────────────────────────────────────
print("\n" + "=" * 70)
print("[10] Capture Rate Analysis (Mincer-Zarnowitz R²)")
print("=" * 70)

def mincer_zarnowitz(realized, forecast):
    """Mincer-Zarnowitz regression: realized = a + b*forecast. Returns R², a, b."""
    v = ~np.isnan(realized) & ~np.isnan(forecast) & (realized > 0) & (forecast > 0)
    if v.sum() < 30:
        return np.nan, np.nan, np.nan
    r = realized[v]
    f = forecast[v]
    slope, intercept, r_value, p_value, std_err = stats.linregress(f, r)
    return r_value**2, intercept, slope


# Base models
for name, fc in [("GARCH(1,1)", garch_forecasts),
                 ("GJR-GARCH", gjr_forecasts),
                 ("EWMA(0.94)", ewma_forecasts)]:
    r2, a, b = mincer_zarnowitz(realized, fc)
    print(f"  {name:20s}: R² = {r2:.4f} (a={a:.6f}, b={b:.4f})")

# Best GARCH-X
if garchx_results:
    best_key = min(garchx_results, key=lambda k: garchx_results[k]["qlike"])
    best_name = garchx_results[best_key]["name"]

    # Re-generate best GARCH-X forecasts for MZ
    pred_vals_best = data[best_key].shift(1).values
    best_fc = np.full(n_oos, np.nan)

    for i, oos_date in enumerate(oos_indices):
        idx = all_indices.index(oos_date)
        if idx < window or np.isnan(garch_forecasts[i]):
            continue

        reg_start = max(0, i - reg_window)
        reg_end = i
        y_reg = realized[reg_start:reg_end]
        x_garch = garch_forecasts[reg_start:reg_end]
        reg_oos_indices = oos_indices[reg_start:reg_end]
        x_pred = np.array([pred_vals_best[all_indices.index(d)] for d in reg_oos_indices
                           if d in all_indices])

        if len(x_pred) != len(y_reg):
            continue

        v = (~np.isnan(y_reg) & ~np.isnan(x_garch) & ~np.isnan(x_pred) &
             (y_reg > 0) & (x_garch > 0) & np.isfinite(x_pred))
        if v.sum() < 30:
            continue

        X = np.column_stack([np.ones(v.sum()), x_garch[v], x_pred[v]])
        y = y_reg[v]
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            x_pred_today = pred_vals_best[idx]
            if np.isnan(x_pred_today) or not np.isfinite(x_pred_today):
                continue
            forecast = beta[0] + beta[1] * garch_forecasts[i] + beta[2] * x_pred_today
            best_fc[i] = max(forecast, 1e-10)
        except Exception:
            continue

    r2_best, a_best, b_best = mincer_zarnowitz(realized, best_fc)
    print(f"  Best GARCH-X ({best_name[:20]:20s}): R² = {r2_best:.4f} (a={a_best:.6f}, b={b_best:.4f})")

    if valid_comb.sum() > 50:
        r2_comb, a_comb, b_comb = mincer_zarnowitz(realized, combined_forecasts)
        print(f"  Combined GARCH-X:      R² = {r2_comb:.4f} (a={a_comb:.6f}, b={b_comb:.4f})")


# ─── VIX Cross-Effect Deep Dive ──────────────────────────────────
print("\n" + "=" * 70)
print("[11] VIX Cross-Effect on BTC Volatility (Deep Dive)")
print("=" * 70)

# Does VIX spike predict BTC vol?
btc_clean["vix_spike"] = btc_clean["vix_chg"] > btc_clean["vix_chg"].quantile(0.90)
btc_clean["vix_crash"] = btc_clean["vix_chg"] < btc_clean["vix_chg"].quantile(0.10)

vix_spike_days = btc_clean[btc_clean["vix_spike"]]
vix_normal_days = btc_clean[~btc_clean["vix_spike"] & ~btc_clean["vix_crash"]]
vix_crash_days = btc_clean[btc_clean["vix_crash"]]

print(f"  VIX spike days (top 10%):   n={len(vix_spike_days)}, "
      f"next-day BTC vol = {np.sqrt(vix_spike_days['realized_var'].shift(-1).dropna().mean()) * np.sqrt(252) * 100:.1f}%")
print(f"  VIX normal days (10-90%):   n={len(vix_normal_days)}, "
      f"next-day BTC vol = {np.sqrt(vix_normal_days['realized_var'].shift(-1).dropna().mean()) * np.sqrt(252) * 100:.1f}%")
print(f"  VIX crash days (bot 10%):   n={len(vix_crash_days)}, "
      f"next-day BTC vol = {np.sqrt(vix_crash_days['realized_var'].shift(-1).dropna().mean()) * np.sqrt(252) * 100:.1f}%")

# Granger causality: VIX → BTC vol
print("\n  Granger-like test: VIX changes → BTC squared returns")
# Simple: regress r²_btc(t) on r²_btc(t-1) + ΔvIX(t-1)
y = btc_clean["realized_var"].iloc[1:].values
x1 = btc_clean["realized_var"].shift(1).iloc[1:].values
x2 = btc_clean["vix_chg"].shift(1).iloc[1:].values

v = ~np.isnan(y) & ~np.isnan(x1) & ~np.isnan(x2) & np.isfinite(x2)
X_full = np.column_stack([np.ones(v.sum()), x1[v], x2[v]])
X_restricted = np.column_stack([np.ones(v.sum()), x1[v]])
y_v = y[v]

# F-test
from numpy.linalg import lstsq
beta_full = lstsq(X_full, y_v, rcond=None)[0]
beta_rest = lstsq(X_restricted, y_v, rcond=None)[0]

rss_full = np.sum((y_v - X_full @ beta_full) ** 2)
rss_rest = np.sum((y_v - X_restricted @ beta_rest) ** 2)

n_obs = len(y_v)
k_full = X_full.shape[1]
k_rest = X_restricted.shape[1]

f_stat = ((rss_rest - rss_full) / (k_full - k_rest)) / (rss_full / (n_obs - k_full))
f_pval = 1 - stats.f.cdf(f_stat, k_full - k_rest, n_obs - k_full)

print(f"  F-statistic: {f_stat:.3f}, p-value: {f_pval:.4f}")
print(f"  ΔR²: {(1 - rss_full / np.sum((y_v - y_v.mean())**2)) - (1 - rss_rest / np.sum((y_v - y_v.mean())**2)):.6f}")
print(f"  VIX coefficient: {beta_full[2]:.6f}")


# ─── Regime-Dependent GARCH ──────────────────────────────────────
print("\n" + "=" * 70)
print("[12] Regime-Dependent GARCH (High vs Low RV)")
print("=" * 70)

# Full sample GARCH parameters by RV regime
high_rv = btc_clean[btc_clean["rv_regime"] == 1]
low_rv = btc_clean[btc_clean["rv_regime"] == 0]

for regime_name, regime_data in [("High RV", high_rv), ("Low RV", low_rv), ("Full Sample", btc_clean)]:
    if len(regime_data) < 500:
        print(f"  {regime_name}: insufficient data ({len(regime_data)})")
        continue
    try:
        am = arch_model(regime_data["ret_pct"].values, vol="GARCH", p=1, o=1, q=1, dist="t")
        res = am.fit(disp="off")
        print(f"\n  {regime_name} ({len(regime_data)} days):")
        print(f"    omega={res.params['omega']:.6f}, alpha={res.params['alpha[1]']:.4f}, "
              f"gamma={res.params.get('gamma[1]', 0):.4f}, beta={res.params['beta[1]']:.4f}")
        print(f"    Persistence: {res.params['alpha[1]'] + res.params.get('gamma[1]', 0) / 2 + res.params['beta[1]']:.4f}")
        print(f"    df(t): {res.params.get('nu', np.nan):.2f}")
    except Exception as e:
        print(f"  {regime_name}: GARCH failed ({e})")


# ─── Summary ─────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[13] SUMMARY: K136 BTC Derivatives-Conditioned Vol Model")
print("=" * 70)

print(f"""
DATA: BTC-USD {btc_clean.index[0].strftime('%Y-%m-%d')} to {btc_clean.index[-1].strftime('%Y-%m-%d')} ({len(btc_clean)} days)
OOS:  {oos_start} to {oos_end} ({n_oos} days)

BASE MODEL QLIKE:
  GARCH(1,1):  {qlike_garch:.6f}
  GJR-GARCH:   {qlike_gjr:.6f}
  EWMA(0.94):  {qlike_ewma:.6f}
""")

if garchx_results:
    print("GARCH-X RESULTS (ranked by QLIKE):")
    sorted_results = sorted(garchx_results.items(), key=lambda x: x[1]["qlike"])
    for key, val in sorted_results:
        sig = "***" if val["dm_p"] < 0.01 else "**" if val["dm_p"] < 0.05 else "*" if val["dm_p"] < 0.10 else "n.s."
        print(f"  {val['name']:40s}: QLIKE={val['qlike']:.6f} (Δ={val['qlike_improvement']:+.2f}%) "
              f"DM p={val['dm_p']:.4f} [{sig}]")

    # Key findings
    best = sorted_results[0]
    worst = sorted_results[-1]
    any_significant = any(v["dm_p"] < 0.05 for _, v in sorted_results)

    print(f"""
KEY FINDINGS:
  Best predictor:  {best[1]['name']} (QLIKE Δ={best[1]['qlike_improvement']:+.2f}%)
  Worst predictor: {worst[1]['name']} (QLIKE Δ={worst[1]['qlike_improvement']:+.2f}%)
  Any significant (p<0.05): {'YES' if any_significant else 'NO'}

INTERPRETATION:
  - Codex hypothesis: BTC vol is leverage-crowding-conditioned
  - Volume spike (liquidation proxy) predictive power: {'YES' if garchx_results.get('volume_spike', {}).get('dm_p', 1) < 0.10 else 'NO'}
  - VIX cross-effect on BTC: {'YES' if garchx_results.get('vix_chg', {}).get('dm_p', 1) < 0.10 else 'NO'}
  - Momentum regime matters: {'YES' if garchx_results.get('mom_state', {}).get('dm_p', 1) < 0.10 else 'NO'}
  - Weekend effect: {'YES' if garchx_results.get('is_weekend', {}).get('dm_p', 1) < 0.10 else 'NO'}
""")

# Save results
output = {
    "experiment": "K136",
    "title": "BTC Derivatives-Conditioned Volatility Model",
    "proposed_by": "Codex Round 2 #2",
    "executed_by": "Claude",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_range": f"{btc_clean.index[0].strftime('%Y-%m-%d')} to {btc_clean.index[-1].strftime('%Y-%m-%d')}",
    "oos_period": f"{oos_start} to {oos_end}",
    "n_oos": int(n_oos),
    "base_models": {
        "GARCH": {"qlike": round(qlike_garch, 6)},
        "GJR": {"qlike": round(qlike_gjr, 6)},
        "EWMA_094": {"qlike": round(qlike_ewma, 6)},
    },
    "garchx_results": {k: {kk: (round(vv, 6) if isinstance(vv, float) else vv)
                            for kk, vv in v.items()}
                       for k, v in garchx_results.items()},
}

output_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a861da78/experiments/btc_derivatives_vol_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
print("=" * 70)
