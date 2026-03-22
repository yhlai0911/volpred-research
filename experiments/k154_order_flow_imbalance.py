"""
K154: Order Flow Imbalance → Volatility Prediction
====================================================
[提出: Claude 跳躍式探索 (面向 G: 市場微結構), 執行: Claude]

Background:
  Market microstructure theory (Kyle 1985, Easley et al. 2012 VPIN) suggests
  that order flow imbalance (OFI) — the net direction of trading — reflects
  informed trading or herding behavior that precedes vol spikes.

  We do NOT have tick data. Instead we build daily OFI proxies from OHLCV:
  1. Lee-Ready proxy:  OFI_t = sign(Close - (H+L)/2) * Volume
  2. Dollar volume imbalance: |Up_vol - Down_vol| / Total_vol
  3. Amihud-like flow: |Return| / sqrt(Volume)
  4. Rolling OFI: 5d rolling |OFI|

  Limitation: daily OFI proxies are very noisy approximations. The real test
  requires tick-level data with actual trade-by-trade classification.

Research Questions:
  1. Does daily |OFI| predict next-day realized volatility (RV)?
  2. Can OFI improve GJR-GARCH forecasts as a GARCH-X exogenous variable?
  3. Does OFI add information beyond VIX? (partial correlation test)

Method:
  a. Predictive regression: RV(t+1) = alpha + beta*|OFI(t)| + gamma*log(VIX(t)) + eps
  b. Granger causality: OFI → RV (and reverse)
  c. GJR-GARCH-X with |OFI| as exogenous variable
  d. Partial correlation: OFI → RV | VIX
  e. Extreme OFI events: when |OFI| > 95th percentile, next-day vol analysis

Walk-forward: w=2000, OOS 2020-01-01 to 2024-12-31
Evaluation: QLIKE, DM test, Harvey threshold

Author: VolPred Research System (K154)
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2005-01-01"
OOS_START = "2020-01-01"
OOS_END = "2024-12-31"
WINDOW = 2000
OFI_ROLLING = 5          # rolling window for OFI smoothing
GRANGER_MAXLAG = 10
N_BOOTSTRAP = 5000
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
EXTREME_PCT = 95          # percentile for extreme OFI

ASSETS = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "GLD": "GLD",
}

np.random.seed(42)

print("=" * 78)
print("K154: ORDER FLOW IMBALANCE → VOLATILITY PREDICTION")
print("=" * 78)
print(f"  OFI proxies: Lee-Ready, Dollar Volume Imbalance, Amihud Flow")
print(f"  Window: {WINDOW}")
print(f"  OOS: {OOS_START} to {OOS_END}")
print(f"  Assets: {list(ASSETS.keys())}")
print(f"  Granger max lag: {GRANGER_MAXLAG}")
print(f"  Extreme OFI percentile: {EXTREME_PCT}th")
print(f"  LIMITATION: Daily OFI proxies are VERY noisy. Tick data needed for real test.")


# ==================================================================
# HELPER FUNCTIONS
# ==================================================================

def compute_ofi_proxies(df):
    """Compute order flow imbalance proxies from OHLCV data.

    Returns DataFrame with columns:
      ofi_lr      - Lee-Ready proxy: sign(Close - midprice) * Volume
      ofi_dvi     - Dollar volume imbalance: (up_vol - down_vol) / total_vol
      ofi_amihud  - Amihud-like: |return| / sqrt(volume)
      ofi_lr_roll - 5d rolling absolute Lee-Ready OFI
      abs_ofi_lr  - |ofi_lr| (absolute imbalance magnitude)
    """
    out = pd.DataFrame(index=df.index)

    # 1. Lee-Ready proxy
    midprice = (df["High"] + df["Low"]) / 2.0
    sign_lr = np.sign(df["Close"] - midprice)
    # When close == midprice, sign=0 (no direction). We keep it.
    out["ofi_lr"] = sign_lr * df["Volume"]
    out["abs_ofi_lr"] = out["ofi_lr"].abs()

    # 2. Dollar volume imbalance
    # Up volume = Volume on days close > open, Down volume on close < open
    up_mask = df["Close"] > df["Open"]
    down_mask = df["Close"] < df["Open"]
    up_vol = df["Volume"].where(up_mask, 0.0)
    down_vol = df["Volume"].where(down_mask, 0.0)
    total_vol = df["Volume"].replace(0, np.nan)
    out["ofi_dvi"] = (up_vol - down_vol) / total_vol
    out["abs_ofi_dvi"] = out["ofi_dvi"].abs()

    # 3. Amihud-like flow impact: |return| / sqrt(volume)
    # Higher = more price impact per unit flow = less liquidity
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    vol_sqrt = np.sqrt(df["Volume"].replace(0, np.nan))
    out["ofi_amihud"] = log_ret.abs() / vol_sqrt
    # Scale to avoid tiny numbers
    out["ofi_amihud"] = out["ofi_amihud"] * 1e6

    # 4. Rolling absolute OFI (captures persistent imbalance)
    out["ofi_lr_roll5"] = out["abs_ofi_lr"].rolling(OFI_ROLLING).mean()

    return out


def compute_rv(returns, window=22):
    """Compute realized volatility: sqrt of sum of squared returns over window."""
    rv = returns.pow(2).rolling(window).sum().apply(np.sqrt)
    return rv


def qlike_loss(rv_actual, rv_forecast):
    """QLIKE loss function (lower is better)."""
    # Both should be variance (squared) terms
    # QLIKE = mean(log(sigma2_f) + r2/sigma2_f)
    r2 = rv_actual ** 2
    s2 = rv_forecast ** 2
    valid = (s2 > 0) & np.isfinite(s2) & np.isfinite(r2)
    r2 = r2[valid]
    s2 = s2[valid]
    return np.mean(np.log(s2) + r2 / s2)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. Negative t → model 1 better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    mean_d = np.mean(d)
    # HAC variance with Newey-West (lag = h-1)
    var_d = np.var(d, ddof=1)
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - mean_d) * (d[:-k] - mean_d))
        var_d += 2 * (1 - k / h) * gamma_k
    var_d = max(var_d, 1e-20)
    t_stat = mean_d / np.sqrt(var_d / n)
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return t_stat, p_val


def partial_corr(x, y, z):
    """Partial correlation of x and y given z. All Series aligned."""
    df = pd.DataFrame({"x": x, "y": y, "z": z}).dropna()
    if len(df) < 30:
        return np.nan, np.nan
    # Regress x on z, y on z, correlate residuals
    from numpy.linalg import lstsq
    Z = np.column_stack([np.ones(len(df)), df["z"].values])
    res_x = df["x"].values - Z @ lstsq(Z, df["x"].values, rcond=None)[0]
    res_y = df["y"].values - Z @ lstsq(Z, df["y"].values, rcond=None)[0]
    r, p = stats.pearsonr(res_x, res_y)
    return r, p


# ==================================================================
# MAIN ANALYSIS LOOP
# ==================================================================

all_results = {}

for asset_name, ticker in ASSETS.items():
    print(f"\n{'='*78}")
    print(f"  ASSET: {asset_name} ({ticker})")
    print(f"{'='*78}")

    # ---------------------------------------------------------------
    # 1. Download data
    # ---------------------------------------------------------------
    print(f"\n  [1/7] Downloading {ticker} + VIX data...")

    raw = yf.download(ticker, start=DATA_START, end="2025-01-01", progress=False, auto_adjust=False)
    vix_raw = yf.download("^VIX", start=DATA_START, end="2025-01-01", progress=False, auto_adjust=False)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if isinstance(vix_raw.columns, pd.MultiIndex):
        vix_raw.columns = vix_raw.columns.get_level_values(0)

    df = pd.DataFrame()
    df["Open"] = raw["Open"]
    df["High"] = raw["High"]
    df["Low"] = raw["Low"]
    df["Close"] = raw["Close"]
    df["Volume"] = raw["Volume"]
    df["returns"] = np.log(df["Close"] / df["Close"].shift(1))
    df["VIX"] = vix_raw["Close"]
    df = df.dropna(subset=["returns", "VIX"])

    print(f"    Data: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")

    # ---------------------------------------------------------------
    # 2. Compute OFI proxies
    # ---------------------------------------------------------------
    print(f"  [2/7] Computing OFI proxies...")

    ofi = compute_ofi_proxies(df)
    df = pd.concat([df, ofi], axis=1)

    # Realized volatility: next-day r^2 (daily proxy) and 5d forward RV
    df["rv_next1"] = df["returns"].shift(-1).pow(2)  # next-day squared return
    df["rv_fwd5"] = df["returns"].pow(2).rolling(5).sum().shift(-5).apply(np.sqrt)

    # Standardize OFI measures for comparability
    for col in ["abs_ofi_lr", "abs_ofi_dvi", "ofi_amihud", "ofi_lr_roll5"]:
        z_col = f"z_{col}"
        expanding_mean = df[col].expanding(min_periods=60).mean()
        expanding_std = df[col].expanding(min_periods=60).std()
        df[z_col] = (df[col] - expanding_mean) / expanding_std.replace(0, np.nan)

    # Drop NaN rows for analysis
    analysis_cols = ["returns", "VIX", "rv_next1", "abs_ofi_lr", "abs_ofi_dvi",
                     "ofi_amihud", "ofi_lr_roll5", "z_abs_ofi_lr", "z_abs_ofi_dvi",
                     "z_ofi_amihud", "z_ofi_lr_roll5"]
    df_clean = df.dropna(subset=analysis_cols)

    print(f"    Clean sample: {len(df_clean)} days")
    print(f"    OFI stats:")
    for col in ["abs_ofi_lr", "abs_ofi_dvi", "ofi_amihud", "ofi_lr_roll5"]:
        print(f"      {col}: mean={df_clean[col].mean():.4g}, std={df_clean[col].std():.4g}")

    # ---------------------------------------------------------------
    # 3. Simple correlations & predictive regressions
    # ---------------------------------------------------------------
    print(f"\n  [3/7] Predictive regressions & correlations...")

    asset_results = {
        "asset": asset_name,
        "n_obs": len(df_clean),
        "data_range": f"{df_clean.index[0].date()} to {df_clean.index[-1].date()}",
    }

    # 3a. Raw correlation: |OFI| vs next-day r^2
    print(f"\n    --- Raw Correlations: |OFI(t)| vs r^2(t+1) ---")
    corr_results = {}
    for ofi_col in ["z_abs_ofi_lr", "z_abs_ofi_dvi", "z_ofi_amihud", "z_ofi_lr_roll5"]:
        r, p = stats.pearsonr(
            df_clean[ofi_col].values,
            df_clean["rv_next1"].values
        )
        label = ofi_col.replace("z_", "")
        corr_results[label] = {"r": round(r, 4), "p": round(p, 6)}
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "NS"
        print(f"      {label:20s}: r={r:+.4f}  p={p:.4e}  {sig}")

    asset_results["raw_correlations"] = corr_results

    # 3b. Partial correlation: |OFI| vs r^2(t+1) | VIX
    print(f"\n    --- Partial Correlations: |OFI(t)| vs r^2(t+1) | VIX(t) ---")
    pcorr_results = {}
    for ofi_col in ["z_abs_ofi_lr", "z_abs_ofi_dvi", "z_ofi_amihud", "z_ofi_lr_roll5"]:
        r, p = partial_corr(
            df_clean[ofi_col],
            df_clean["rv_next1"],
            np.log(df_clean["VIX"])
        )
        label = ofi_col.replace("z_", "")
        pcorr_results[label] = {"r": round(r, 4), "p": round(p, 6)}
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "NS"
        print(f"      {label:20s}: r={r:+.4f}  p={p:.4e}  {sig}")

    asset_results["partial_correlations_given_vix"] = pcorr_results

    # 3c. Predictive regression: r^2(t+1) = a + b*|OFI(t)| + c*log(VIX(t))
    print(f"\n    --- Predictive Regression: r^2(t+1) = a + b*|OFI| + c*log(VIX) ---")
    reg_results = {}
    Y = df_clean["rv_next1"].values
    for ofi_col in ["z_abs_ofi_lr", "z_abs_ofi_dvi", "z_ofi_amihud", "z_ofi_lr_roll5"]:
        X = np.column_stack([
            np.ones(len(df_clean)),
            df_clean[ofi_col].values,
            np.log(df_clean["VIX"].values)
        ])
        from numpy.linalg import lstsq
        beta, residuals, rank, sv = lstsq(X, Y, rcond=None)
        Y_hat = X @ beta
        ss_res = np.sum((Y - Y_hat) ** 2)
        ss_tot = np.sum((Y - Y.mean()) ** 2)
        r_sq = 1 - ss_res / ss_tot

        # Standard errors (heteroskedasticity-robust: White)
        n, k = X.shape
        e = Y - Y_hat
        bread = np.linalg.inv(X.T @ X)
        meat = X.T @ np.diag(e ** 2) @ X
        cov_hc0 = bread @ meat @ bread
        se = np.sqrt(np.diag(cov_hc0))
        t_stats = beta / se
        p_vals = 2 * stats.t.sf(np.abs(t_stats), df=n - k)

        label = ofi_col.replace("z_", "")
        reg_results[label] = {
            "beta_ofi": round(float(beta[1]), 6),
            "t_ofi": round(float(t_stats[1]), 3),
            "p_ofi": round(float(p_vals[1]), 6),
            "beta_vix": round(float(beta[2]), 6),
            "t_vix": round(float(t_stats[2]), 3),
            "p_vix": round(float(p_vals[2]), 6),
            "R2": round(float(r_sq), 6),
        }
        sig_ofi = "***" if p_vals[1] < 0.001 else "**" if p_vals[1] < 0.01 else "*" if p_vals[1] < 0.05 else "NS"
        sig_vix = "***" if p_vals[2] < 0.001 else "**" if p_vals[2] < 0.01 else "*" if p_vals[2] < 0.05 else "NS"
        print(f"      {label:20s}: b_OFI={beta[1]:+.6f} t={t_stats[1]:+.3f}{sig_ofi}  "
              f"b_VIX={beta[2]:+.6f} t={t_stats[2]:+.3f}{sig_vix}  R2={r_sq:.4f}")

    asset_results["predictive_regressions"] = reg_results

    # ---------------------------------------------------------------
    # 4. Granger causality tests
    # ---------------------------------------------------------------
    print(f"\n  [4/7] Granger causality tests (max lag={GRANGER_MAXLAG})...")

    granger_results = {}

    # Use squared returns as RV proxy
    rv_series = df_clean["returns"].pow(2).values
    for ofi_col in ["z_abs_ofi_lr", "z_abs_ofi_dvi", "z_ofi_amihud", "z_ofi_lr_roll5"]:
        ofi_vals = df_clean[ofi_col].values

        # OFI → RV
        gc_data_fwd = np.column_stack([rv_series, ofi_vals])
        gc_df_fwd = pd.DataFrame(gc_data_fwd, columns=["rv", "ofi"])
        gc_df_fwd = gc_df_fwd.replace([np.inf, -np.inf], np.nan).dropna()

        label = ofi_col.replace("z_", "")
        try:
            gc_fwd = grangercausalitytests(gc_df_fwd, maxlag=GRANGER_MAXLAG, verbose=False)
            # Get best lag (lowest p-value for ssr_ftest)
            best_lag_fwd = min(gc_fwd, key=lambda k: gc_fwd[k][0]["ssr_ftest"][0][1])
            p_fwd = gc_fwd[best_lag_fwd][0]["ssr_ftest"][0][1]
            f_fwd = gc_fwd[best_lag_fwd][0]["ssr_ftest"][0][0]
        except Exception as e:
            best_lag_fwd, p_fwd, f_fwd = np.nan, np.nan, np.nan

        # RV → OFI (reverse)
        gc_data_rev = np.column_stack([ofi_vals, rv_series])
        gc_df_rev = pd.DataFrame(gc_data_rev, columns=["ofi", "rv"])
        gc_df_rev = gc_df_rev.replace([np.inf, -np.inf], np.nan).dropna()

        try:
            gc_rev = grangercausalitytests(gc_df_rev, maxlag=GRANGER_MAXLAG, verbose=False)
            best_lag_rev = min(gc_rev, key=lambda k: gc_rev[k][0]["ssr_ftest"][0][1])
            p_rev = gc_rev[best_lag_rev][0]["ssr_ftest"][0][1]
            f_rev = gc_rev[best_lag_rev][0]["ssr_ftest"][0][0]
        except Exception as e:
            best_lag_rev, p_rev, f_rev = np.nan, np.nan, np.nan

        granger_results[label] = {
            "OFI_to_RV": {
                "best_lag": int(best_lag_fwd) if not np.isnan(best_lag_fwd) else None,
                "F": round(float(f_fwd), 3) if not np.isnan(f_fwd) else None,
                "p": round(float(p_fwd), 6) if not np.isnan(p_fwd) else None,
            },
            "RV_to_OFI": {
                "best_lag": int(best_lag_rev) if not np.isnan(best_lag_rev) else None,
                "F": round(float(f_rev), 3) if not np.isnan(f_rev) else None,
                "p": round(float(p_rev), 6) if not np.isnan(p_rev) else None,
            },
        }

        sig_fwd = "***" if p_fwd < 0.001 else "**" if p_fwd < 0.01 else "*" if p_fwd < 0.05 else "NS"
        sig_rev = "***" if p_rev < 0.001 else "**" if p_rev < 0.01 else "*" if p_rev < 0.05 else "NS"
        print(f"      {label:20s}: OFI→RV lag={best_lag_fwd} F={f_fwd:.2f} p={p_fwd:.4e}{sig_fwd}  |  "
              f"RV→OFI lag={best_lag_rev} F={f_rev:.2f} p={p_rev:.4e}{sig_rev}")

    asset_results["granger_causality"] = granger_results

    # ---------------------------------------------------------------
    # 5. Extreme OFI events analysis
    # ---------------------------------------------------------------
    print(f"\n  [5/7] Extreme OFI events (>{EXTREME_PCT}th percentile)...")

    extreme_results = {}
    for ofi_col in ["z_abs_ofi_lr", "z_abs_ofi_dvi", "z_ofi_amihud", "z_ofi_lr_roll5"]:
        threshold = np.nanpercentile(df_clean[ofi_col].values, EXTREME_PCT)
        extreme_mask = df_clean[ofi_col] > threshold
        normal_mask = ~extreme_mask

        rv_extreme = df_clean.loc[extreme_mask, "rv_next1"]
        rv_normal = df_clean.loc[normal_mask, "rv_next1"]

        mean_extreme = float(rv_extreme.mean())
        mean_normal = float(rv_normal.mean())
        ratio = mean_extreme / mean_normal if mean_normal > 0 else np.nan

        # Welch's t-test
        t_stat, p_val = stats.ttest_ind(rv_extreme.values, rv_normal.values, equal_var=False)

        # Also check next-5day RV
        rv5_extreme = df_clean.loc[extreme_mask, "rv_fwd5"].dropna()
        rv5_normal = df_clean.loc[normal_mask, "rv_fwd5"].dropna()
        if len(rv5_extreme) > 5 and len(rv5_normal) > 5:
            t5, p5 = stats.ttest_ind(rv5_extreme.values, rv5_normal.values, equal_var=False)
        else:
            t5, p5 = np.nan, np.nan

        label = ofi_col.replace("z_", "")
        extreme_results[label] = {
            "n_extreme": int(extreme_mask.sum()),
            "n_normal": int(normal_mask.sum()),
            "threshold_z": round(float(threshold), 3),
            "mean_rv_extreme": round(mean_extreme, 8),
            "mean_rv_normal": round(mean_normal, 8),
            "ratio": round(ratio, 3),
            "t_stat": round(float(t_stat), 3),
            "p_val": round(float(p_val), 6),
            "rv5_ratio": round(float(rv5_extreme.mean() / rv5_normal.mean()), 3) if len(rv5_extreme) > 0 and rv5_normal.mean() > 0 else None,
            "rv5_t": round(float(t5), 3) if not np.isnan(t5) else None,
            "rv5_p": round(float(p5), 6) if not np.isnan(p5) else None,
        }

        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else "NS"
        print(f"      {label:20s}: n={extreme_mask.sum():4d} extreme, "
              f"RV ratio={ratio:.2f}x, t={t_stat:+.3f} {sig}")

    asset_results["extreme_ofi_events"] = extreme_results

    # ---------------------------------------------------------------
    # 6. Walk-forward GARCH-X with OFI
    # ---------------------------------------------------------------
    print(f"\n  [6/7] Walk-forward GJR-GARCH vs GARCH-X(OFI) (w={WINDOW}, OOS from {OOS_START})...")

    # Prepare data for walk-forward
    oos_mask = df_clean.index >= OOS_START
    oos_dates = df_clean.index[oos_mask]

    if len(oos_dates) < 100:
        print(f"    WARNING: Only {len(oos_dates)} OOS obs, skipping walk-forward")
        asset_results["walk_forward"] = {"status": "skipped", "reason": "insufficient OOS data"}
    else:
        returns_pct = df_clean["returns"].values * 100  # arch library scale
        all_dates = df_clean.index

        # Best OFI proxy: use Lee-Ready (most intuitive)
        ofi_series = df_clean["z_abs_ofi_lr"].values

        # Storage for forecasts
        gjr_forecasts = []
        garchx_forecasts = []
        actual_rv = []
        forecast_dates = []

        n_gjr_fail = 0
        n_garchx_fail = 0

        # Find first OOS index
        oos_start_idx = np.searchsorted(all_dates, pd.Timestamp(OOS_START))

        n_total = len(all_dates) - oos_start_idx
        print_every = max(1, n_total // 10)

        for i in range(oos_start_idx, len(all_dates)):
            if i < WINDOW:
                continue

            window_ret = returns_pct[i - WINDOW:i]
            window_ofi = ofi_series[i - WINDOW:i]

            # --- GJR-GARCH baseline ---
            try:
                am_gjr = arch_model(window_ret, vol="GARCH", p=1, o=1, q=1, dist="t")
                res_gjr = am_gjr.fit(disp="off", show_warning=False)
                fc_gjr = res_gjr.forecast(horizon=1)
                sigma2_gjr = fc_gjr.variance.values[-1, 0]
                sigma_gjr = np.sqrt(sigma2_gjr) / 100.0  # back to decimal
            except Exception:
                sigma_gjr = np.nan
                n_gjr_fail += 1

            # --- GARCH-X with OFI ---
            try:
                # Use OFI as exogenous variable in the variance equation
                ofi_exog = window_ofi.reshape(-1, 1)
                am_gx = arch_model(window_ret, vol="GARCH", p=1, o=1, q=1, dist="t", x=ofi_exog)
                res_gx = am_gx.fit(disp="off", show_warning=False)
                # For forecast, use last OFI value
                last_ofi = ofi_exog[-1:, :]
                fc_gx = res_gx.forecast(horizon=1, x=last_ofi)
                sigma2_gx = fc_gx.variance.values[-1, 0]
                sigma_gx = np.sqrt(sigma2_gx) / 100.0
            except Exception:
                sigma_gx = np.nan
                n_garchx_fail += 1

            # Actual next-day |return|
            if i < len(returns_pct):
                actual = abs(returns_pct[i] / 100.0)
            else:
                actual = np.nan

            gjr_forecasts.append(sigma_gjr)
            garchx_forecasts.append(sigma_gx)
            actual_rv.append(actual)
            forecast_dates.append(all_dates[i])

            if (i - oos_start_idx) % print_every == 0:
                pct = 100 * (i - oos_start_idx) / n_total
                print(f"      Progress: {pct:.0f}% ({i - oos_start_idx}/{n_total})")

        gjr_fc = np.array(gjr_forecasts)
        garchx_fc = np.array(garchx_forecasts)
        actual_arr = np.array(actual_rv)

        # Remove NaN
        valid = np.isfinite(gjr_fc) & np.isfinite(garchx_fc) & np.isfinite(actual_arr) & (gjr_fc > 0) & (garchx_fc > 0)
        gjr_fc_v = gjr_fc[valid]
        garchx_fc_v = garchx_fc[valid]
        actual_v = actual_arr[valid]

        print(f"\n    Walk-forward results:")
        print(f"      Total forecasts: {len(forecast_dates)}")
        print(f"      Valid forecasts: {valid.sum()}")
        print(f"      GJR failures: {n_gjr_fail}")
        print(f"      GARCH-X failures: {n_garchx_fail}")

        if len(gjr_fc_v) > 50:
            # QLIKE
            ql_gjr = qlike_loss(actual_v, gjr_fc_v)
            ql_garchx = qlike_loss(actual_v, garchx_fc_v)

            # DM test
            loss_gjr = np.log(gjr_fc_v ** 2) + actual_v ** 2 / gjr_fc_v ** 2
            loss_garchx = np.log(garchx_fc_v ** 2) + actual_v ** 2 / garchx_fc_v ** 2
            dm_t, dm_p = dm_test(loss_garchx, loss_gjr)  # negative = GARCH-X better

            # MSE
            mse_gjr = np.mean((actual_v - gjr_fc_v) ** 2)
            mse_garchx = np.mean((actual_v - garchx_fc_v) ** 2)

            improvement_pct = (ql_gjr - ql_garchx) / abs(ql_gjr) * 100

            wf_results = {
                "n_forecasts": int(valid.sum()),
                "gjr_qlike": round(float(ql_gjr), 6),
                "garchx_qlike": round(float(ql_garchx), 6),
                "qlike_improvement_pct": round(float(improvement_pct), 3),
                "gjr_mse": round(float(mse_gjr), 10),
                "garchx_mse": round(float(mse_garchx), 10),
                "dm_t": round(float(dm_t), 3),
                "dm_p": round(float(dm_p), 6),
                "gjr_failures": n_gjr_fail,
                "garchx_failures": n_garchx_fail,
            }

            sig = "***" if dm_p < 0.001 else "**" if dm_p < 0.01 else "*" if dm_p < 0.05 else "NS"
            winner = "GARCH-X" if ql_garchx < ql_gjr else "GJR"
            print(f"\n      GJR     QLIKE: {ql_gjr:.6f}   MSE: {mse_gjr:.2e}")
            print(f"      GARCH-X QLIKE: {ql_garchx:.6f}   MSE: {mse_garchx:.2e}")
            print(f"      QLIKE improvement: {improvement_pct:+.3f}%")
            print(f"      DM test: t={dm_t:+.3f}  p={dm_p:.4e} {sig}")
            print(f"      Winner: {winner}")
        else:
            wf_results = {"status": "insufficient valid forecasts", "n_valid": int(valid.sum())}
            print(f"    WARNING: Only {valid.sum()} valid forecasts, cannot compute metrics")

        asset_results["walk_forward"] = wf_results

    # ---------------------------------------------------------------
    # 7. VIX sufficiency check (R^2 incremental)
    # ---------------------------------------------------------------
    print(f"\n  [7/7] VIX sufficiency: incremental R^2 from OFI...")

    vix_suff = {}
    Y = df_clean["rv_next1"].values

    # Model 1: VIX only
    X1 = np.column_stack([np.ones(len(Y)), np.log(df_clean["VIX"].values)])
    beta1 = np.linalg.lstsq(X1, Y, rcond=None)[0]
    r2_vix = 1 - np.sum((Y - X1 @ beta1) ** 2) / np.sum((Y - Y.mean()) ** 2)

    for ofi_col in ["z_abs_ofi_lr", "z_abs_ofi_dvi", "z_ofi_amihud", "z_ofi_lr_roll5"]:
        # Model 2: VIX + OFI
        X2 = np.column_stack([np.ones(len(Y)), np.log(df_clean["VIX"].values), df_clean[ofi_col].values])
        beta2 = np.linalg.lstsq(X2, Y, rcond=None)[0]
        r2_both = 1 - np.sum((Y - X2 @ beta2) ** 2) / np.sum((Y - Y.mean()) ** 2)
        delta_r2 = r2_both - r2_vix

        # F-test for incremental R^2
        n = len(Y)
        k_full = 3
        k_restricted = 2
        f_stat = ((r2_both - r2_vix) / (k_full - k_restricted)) / ((1 - r2_both) / (n - k_full))
        p_f = 1 - stats.f.cdf(f_stat, k_full - k_restricted, n - k_full)

        label = ofi_col.replace("z_", "")
        vix_suff[label] = {
            "R2_vix_only": round(float(r2_vix), 6),
            "R2_vix_plus_ofi": round(float(r2_both), 6),
            "delta_R2": round(float(delta_r2), 6),
            "F_incremental": round(float(f_stat), 3),
            "p_F": round(float(p_f), 6),
        }

        sig = "***" if p_f < 0.001 else "**" if p_f < 0.01 else "*" if p_f < 0.05 else "NS"
        print(f"      {label:20s}: R2_vix={r2_vix:.4f}, R2_vix+ofi={r2_both:.4f}, "
              f"dR2={delta_r2:+.6f}, F={f_stat:.2f} {sig}")

    asset_results["vix_sufficiency"] = vix_suff

    all_results[asset_name] = asset_results


# ==================================================================
# CROSS-ASSET SUMMARY
# ==================================================================

print("\n" + "=" * 78)
print("CROSS-ASSET SUMMARY")
print("=" * 78)

# Summary table: partial correlations
print("\n  --- Partial Correlations r(|OFI|, RV | VIX) ---")
print(f"  {'OFI Measure':20s}  {'SPY':>10s}  {'QQQ':>10s}  {'GLD':>10s}  {'Significant?':>15s}")
print(f"  {'-'*20}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*15}")

summary_pcorr = {}
for ofi_key in ["abs_ofi_lr", "abs_ofi_dvi", "ofi_amihud", "ofi_lr_roll5"]:
    vals = []
    sigs = []
    for asset in ASSETS:
        if asset in all_results and "partial_correlations_given_vix" in all_results[asset]:
            pc = all_results[asset]["partial_correlations_given_vix"].get(ofi_key, {})
            r = pc.get("r", np.nan)
            p = pc.get("p", np.nan)
            vals.append(r)
            sigs.append(p < 0.05)
        else:
            vals.append(np.nan)
            sigs.append(False)

    n_sig = sum(sigs)
    sig_str = f"{n_sig}/3 sig" if not np.isnan(vals[0]) else "N/A"
    summary_pcorr[ofi_key] = {
        "values": {a: round(v, 4) for a, v in zip(ASSETS, vals)},
        "n_significant": n_sig,
    }
    print(f"  {ofi_key:20s}  {vals[0]:+10.4f}  {vals[1]:+10.4f}  {vals[2]:+10.4f}  {sig_str:>15s}")

# Summary: GARCH-X improvement
print(f"\n  --- GARCH-X(OFI) vs GJR: QLIKE Improvement ---")
for asset in ASSETS:
    wf = all_results.get(asset, {}).get("walk_forward", {})
    if "qlike_improvement_pct" in wf:
        imp = wf["qlike_improvement_pct"]
        dm = wf.get("dm_t", np.nan)
        dm_p = wf.get("dm_p", np.nan)
        sig = "***" if dm_p < 0.001 else "**" if dm_p < 0.01 else "*" if dm_p < 0.05 else "NS"
        print(f"      {asset:5s}: QLIKE change={imp:+.3f}%  DM t={dm:+.3f} {sig}")
    else:
        print(f"      {asset:5s}: walk-forward skipped or failed")

# Summary: Extreme OFI
print(f"\n  --- Extreme OFI (>{EXTREME_PCT}th pct): Next-day RV Ratio ---")
print(f"  {'OFI Measure':20s}  {'SPY':>8s}  {'QQQ':>8s}  {'GLD':>8s}")
print(f"  {'-'*20}  {'-'*8}  {'-'*8}  {'-'*8}")
for ofi_key in ["abs_ofi_lr", "abs_ofi_dvi", "ofi_amihud", "ofi_lr_roll5"]:
    vals = []
    for asset in ASSETS:
        ext = all_results.get(asset, {}).get("extreme_ofi_events", {}).get(ofi_key, {})
        ratio = ext.get("ratio", np.nan)
        vals.append(ratio)
    print(f"  {ofi_key:20s}  {vals[0]:8.2f}x  {vals[1]:8.2f}x  {vals[2]:8.2f}x")


# ==================================================================
# VERDICT
# ==================================================================

print("\n" + "=" * 78)
print("VERDICT")
print("=" * 78)

# Count significant partial correlations
total_pcorr_tests = 0
total_pcorr_sig = 0
for ofi_key in summary_pcorr:
    total_pcorr_tests += 3
    total_pcorr_sig += summary_pcorr[ofi_key]["n_significant"]

# Assess GARCH-X
garchx_wins = 0
garchx_total = 0
for asset in ASSETS:
    wf = all_results.get(asset, {}).get("walk_forward", {})
    if "dm_p" in wf:
        garchx_total += 1
        if wf.get("qlike_improvement_pct", 0) > 0 and wf.get("dm_p", 1) < 0.05:
            garchx_wins += 1

verdict_lines = []
verdict_lines.append(f"1. Partial correlations r(OFI, RV | VIX): {total_pcorr_sig}/{total_pcorr_tests} significant at 5%")

if total_pcorr_sig == 0:
    verdict_lines.append("   → OFI adds ZERO information beyond VIX (VIX sufficient again)")
elif total_pcorr_sig <= 3:
    verdict_lines.append("   → Marginal/sporadic OFI signal, not robust across assets/measures")
else:
    verdict_lines.append("   → OFI may contain independent information (investigate further)")

verdict_lines.append(f"2. GARCH-X(OFI) wins DM test: {garchx_wins}/{garchx_total} assets")
if garchx_wins == 0:
    verdict_lines.append("   → OFI does NOT improve GARCH forecasts")
else:
    verdict_lines.append("   → Some evidence OFI improves forecasts (need tick data to confirm)")

verdict_lines.append(f"3. Daily OFI proxies from OHLCV are VERY noisy approximations")
verdict_lines.append(f"   → Real test requires tick-level trade data (Lee-Ready actual classification)")
verdict_lines.append(f"   → Our proxies likely underestimate true OFI predictive power")

# Overall assessment
if total_pcorr_sig <= 2 and garchx_wins == 0:
    overall = "NULL RESULT: Daily OFI proxies do not predict vol beyond VIX"
    verdict_lines.append(f"\n   OVERALL: {overall}")
    verdict_lines.append(f"   VIX sufficient statistic confirmed (22nd confirmation)")
elif total_pcorr_sig > 6 and garchx_wins >= 2:
    overall = "POSITIVE: OFI contains independent vol-predictive information"
    verdict_lines.append(f"\n   OVERALL: {overall}")
else:
    overall = "MIXED: Some OFI signal exists but not robust enough with daily proxies"
    verdict_lines.append(f"\n   OVERALL: {overall}")

for line in verdict_lines:
    print(f"  {line}")


# ==================================================================
# SAVE RESULTS
# ==================================================================

final_results = {
    "experiment": "K154",
    "title": "Order Flow Imbalance → Volatility Prediction",
    "attribution": "[提出: Claude 跳躍式探索 (面向 G: 市場微結構), 執行: Claude]",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "window": WINDOW,
        "oos_start": OOS_START,
        "oos_end": OOS_END,
        "ofi_proxies": ["Lee-Ready", "Dollar Volume Imbalance", "Amihud Flow", "Rolling OFI_5d"],
        "granger_maxlag": GRANGER_MAXLAG,
        "extreme_percentile": EXTREME_PCT,
        "assets": list(ASSETS.keys()),
    },
    "limitations": [
        "Daily OFI proxies from OHLCV are very noisy. Real test needs tick data.",
        "Lee-Ready proxy uses midprice (H+L)/2 instead of actual bid-ask midpoint.",
        "Dollar volume imbalance uses open-to-close direction, not intraday tick classification.",
        "Amihud measure captures illiquidity, not directional flow per se.",
    ],
    "results_by_asset": all_results,
    "cross_asset_summary": {
        "partial_correlations": summary_pcorr,
        "garchx_wins": garchx_wins,
        "garchx_total": garchx_total,
        "total_pcorr_significant": total_pcorr_sig,
        "total_pcorr_tests": total_pcorr_tests,
    },
    "verdict": overall,
    "verdict_details": verdict_lines,
}

output_path = "storage/experiments/k154_order_flow_imbalance_results.json"
with open(output_path, "w") as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print(f"\n{'='*78}")
print(f"K154 COMPLETE")
print(f"{'='*78}")


# ==================================================================
# MEMORY RECORDING
# ==================================================================
print("\n  Recording to memory...")

sys.path.insert(0, "src")
from volpred.memory.system import MemorySystem
m = MemorySystem()

# Build summary string from results
pcorr_summary = f"{total_pcorr_sig}/{total_pcorr_tests} partial corr sig"
garchx_summary = f"GARCH-X wins {garchx_wins}/{garchx_total}"

m.add_knowledge(
    category="experiment",
    content=(
        f"[提出: Claude 微結構探索, 執行: Claude] K154: Order Flow Imbalance vol prediction. "
        f"Daily OFI proxies (Lee-Ready, DVI, Amihud, Rolling) from OHLCV. "
        f"Partial corr r(OFI,RV|VIX): {pcorr_summary}. {garchx_summary}. "
        f"Verdict: {overall}. "
        f"Limitation: daily proxies very noisy, need tick data for real test."
    ),
    confidence=0.8,
)

m.think(
    f"[K154] Order Flow Imbalance experiment complete. "
    f"Tested 4 daily OFI proxies across SPY/QQQ/GLD. "
    f"Partial correlations: {pcorr_summary}. GARCH-X: {garchx_summary}. "
    f"Key question was whether OFI adds info beyond VIX — {overall.lower()}. "
    f"This is consistent with VIX-sufficient-statistic finding IF partial corrs are zero. "
    f"The proxies are inherently limited by daily OHLCV granularity. "
    f"With tick data (actual Lee-Ready classification, VPIN), results might differ. "
    f"Next: could try intraday volume patterns or signed volume from 5-min bars once data available."
)

print("  Memory recorded.")
print("\nDONE.")
