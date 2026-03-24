"""
K217: Non-Equity Optimal VT — Best Vol Predictor per Non-Equity Asset
======================================================================
Background:
  - K207: VIX is NOT sufficient for GLD/TLT/BTC
  - K204: GLD momentum doesn't help VT (VIX prices it in at monthly freq)
  - K205: BTC range ratio VT has potential

This experiment systematically finds the BEST vol predictor for each
non-equity asset (GLD, TLT, BTC-USD).

Methodology:
  1. For each asset, test 6 predictors for 22d forward realized vol:
     - VIX level (annualized daily vol)
     - Own 22d rolling vol
     - Own range ratio (H-L)/C 22d avg
     - Own |MOM_12_1| (absolute 12-1 month momentum)
     - GJR-GARCH sigma (w=2000)
     - EWMA(0.94) sigma
  2. OOS predictive regression (2023-2024):
     RV_{t+22} = alpha + beta * predictor_t
     Metrics: OOS R², MAE, QLIKE
  3. Combination: best predictor + VIX (does adding VIX help?)
  4. Simple VT using best predictor vs 12/VIX vs B&H

Data: GLD, TLT, BTC-USD daily from yfinance. OOS: 2023-2024.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import json
from datetime import datetime

# ==================================================================
# CONFIG
# ==================================================================
ASSETS = {
    "GLD": {"ticker": "GLD", "start": "2006-01-01"},
    "TLT": {"ticker": "TLT", "start": "2006-01-01"},
    "BTC": {"ticker": "BTC-USD", "start": "2015-01-01"},
}

OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
IS_START = "2015-01-01"  # In-sample start for regression fitting
GARCH_WINDOW = 2000
EWMA_LAMBDA = 0.94
TARGET_VOL = 0.10  # 10% annualized for GLD/TLT; BTC uses 15%
BTC_TARGET_VOL = 0.15
MAX_LEVERAGE = 1.5
TX_COST_BPS = 2
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
FWD_WINDOW = 22  # 22-day forward realized vol

print("=" * 78)
print("K217: NON-EQUITY OPTIMAL VT — BEST VOL PREDICTOR PER ASSET")
print("=" * 78)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/7] Downloading data...")

tickers_to_download = ["GLD", "TLT", "BTC-USD", "^VIX"]
raw_data = {}
for t in tickers_to_download:
    df = yf.download(t, start="2005-01-01", end="2026-12-31", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[t] = df
    print(f"  {t}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

# ==================================================================
# 2. Prepare per-asset data
# ==================================================================
print("\n[2/7] Preparing per-asset data with all predictors...")

def compute_predictors(asset_name, ticker, price_df, vix_df):
    """Compute all 6 predictors for a given asset."""
    # Merge with VIX
    df = price_df[["Close", "High", "Low"]].copy()
    df.columns = ["Close", "High", "Low"]
    df = df.join(vix_df[["Close"]].rename(columns={"Close": "VIX"}), how="inner")
    df = df.dropna()

    # Log returns
    df["ret"] = np.log(df["Close"] / df["Close"].shift(1))
    df = df.dropna(subset=["ret"])

    # --- Target: 22d forward realized vol (annualized) ---
    df["fwd_rv"] = df["ret"].rolling(FWD_WINDOW).std().shift(-FWD_WINDOW) * np.sqrt(252)

    # --- Predictor 1: VIX level (annualized daily vol proxy) ---
    df["pred_vix"] = df["VIX"] / 100  # VIX is in %, convert to decimal annualized vol

    # --- Predictor 2: Own 22d rolling vol (annualized) ---
    df["pred_rv22"] = df["ret"].rolling(22).std() * np.sqrt(252)

    # --- Predictor 3: Range ratio (H-L)/C, 22d avg ---
    df["range_ratio"] = (df["High"] - df["Low"]) / df["Close"]
    df["pred_range"] = df["range_ratio"].rolling(22).mean()

    # --- Predictor 4: |MOM_12_1| absolute momentum ---
    # 12-month return minus 1-month return (skip most recent month)
    df["mom_12"] = df["Close"] / df["Close"].shift(252) - 1
    df["mom_1"] = df["Close"] / df["Close"].shift(21) - 1
    df["pred_absmom"] = (df["mom_12"] - df["mom_1"]).abs()

    # --- Predictor 5: GJR-GARCH sigma (rolling w=2000) ---
    ret_series = df["ret"].values * 100  # scale for arch
    n = len(ret_series)
    garch_sigma = np.full(n, np.nan)

    print(f"    Computing GJR-GARCH sigma for {asset_name} (w={GARCH_WINDOW})...")
    for i in range(GARCH_WINDOW, n):
        window_data = ret_series[i-GARCH_WINDOW:i]
        try:
            model = arch_model(window_data, vol="Garch", p=1, o=1, q=1,
                             dist="normal", mean="Zero", rescale=False)
            res = model.fit(disp="off", show_warning=False)
            forecast = res.forecast(horizon=1)
            garch_sigma[i] = np.sqrt(forecast.variance.values[-1, 0]) / 100 * np.sqrt(252)
        except Exception:
            if i > GARCH_WINDOW:
                garch_sigma[i] = garch_sigma[i-1]

    df["pred_garch"] = garch_sigma

    # --- Predictor 6: EWMA(0.94) sigma ---
    ewma_var = np.full(n, np.nan)
    ret_vals = df["ret"].values
    # Initialize with first 22 days variance
    init_var = np.var(ret_vals[:22])
    ewma_var[22] = init_var
    for i in range(23, n):
        ewma_var[i] = EWMA_LAMBDA * ewma_var[i-1] + (1 - EWMA_LAMBDA) * ret_vals[i-1]**2
    df["pred_ewma"] = np.sqrt(ewma_var) * np.sqrt(252)

    return df

# Build all predictor DataFrames
asset_data = {}
vix_df = raw_data["^VIX"]

for asset_name, config in ASSETS.items():
    ticker = config["ticker"]
    print(f"\n  Processing {asset_name} ({ticker})...")
    df = compute_predictors(asset_name, ticker, raw_data[ticker], vix_df)
    asset_data[asset_name] = df

    # Summary stats
    valid = df.dropna(subset=["fwd_rv", "pred_vix", "pred_rv22", "pred_range",
                               "pred_absmom", "pred_garch", "pred_ewma"])
    print(f"    Valid obs (all predictors): {len(valid)}")
    print(f"    Date range: {valid.index[0].date()} to {valid.index[-1].date()}")

# ==================================================================
# 3. OOS Predictive Regression
# ==================================================================
print("\n" + "=" * 78)
print("[3/7] OOS PREDICTIVE REGRESSIONS")
print("=" * 78)

predictor_names = {
    "pred_vix": "VIX Level",
    "pred_rv22": "Own 22d RV",
    "pred_range": "Range Ratio",
    "pred_absmom": "|MOM_12_1|",
    "pred_garch": "GJR-GARCH",
    "pred_ewma": "EWMA(0.94)",
}

def oos_regression(df, pred_col, oos_start, oos_end):
    """
    Rolling OOS regression:
    Fit on expanding IS window, predict OOS one step at a time.
    """
    df_valid = df.dropna(subset=["fwd_rv", pred_col]).copy()

    # Split
    is_mask = df_valid.index < oos_start
    oos_mask = (df_valid.index >= oos_start) & (df_valid.index <= oos_end)

    is_data = df_valid[is_mask]
    oos_data = df_valid[oos_mask]

    if len(is_data) < 100 or len(oos_data) < 50:
        return None

    # Fit on IS data
    y_is = is_data["fwd_rv"].values
    x_is = is_data[pred_col].values

    # Simple OLS: y = a + b*x
    slope, intercept, r_value, p_value, std_err = stats.linregress(x_is, y_is)

    # OOS predictions
    y_oos = oos_data["fwd_rv"].values
    x_oos = oos_data[pred_col].values
    y_pred = intercept + slope * x_oos

    # OOS R² (vs mean benchmark)
    ss_res = np.sum((y_oos - y_pred) ** 2)
    ss_tot = np.sum((y_oos - np.mean(y_oos)) ** 2)
    oos_r2 = 1 - ss_res / ss_tot

    # MAE
    mae = np.mean(np.abs(y_oos - y_pred))

    # QLIKE: mean(log(pred²) + actual² / pred²)
    # Use pred as sigma forecast
    y_pred_safe = np.maximum(y_pred, 1e-6)
    qlike = np.mean(np.log(y_pred_safe**2) + (y_oos**2) / (y_pred_safe**2))

    # Rank correlation (non-parametric)
    rank_corr, rank_p = stats.spearmanr(x_oos, y_oos)

    return {
        "is_n": len(is_data),
        "oos_n": len(oos_data),
        "is_r2": r_value**2,
        "slope": slope,
        "intercept": intercept,
        "oos_r2": oos_r2,
        "mae": mae,
        "qlike": qlike,
        "rank_corr": rank_corr,
        "rank_p": rank_p,
    }

results = {}

for asset_name in ASSETS:
    print(f"\n{'─' * 60}")
    print(f"  {asset_name}")
    print(f"{'─' * 60}")

    df = asset_data[asset_name]
    results[asset_name] = {}

    print(f"  {'Predictor':<16} {'OOS R²':>8} {'MAE':>8} {'QLIKE':>8} "
          f"{'Rank ρ':>8} {'Rank p':>8} {'IS R²':>8}")
    print(f"  {'─'*16} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")

    for pred_col, pred_name in predictor_names.items():
        res = oos_regression(df, pred_col, OOS_START, OOS_END)
        if res is None:
            print(f"  {pred_name:<16} {'N/A':>8}")
            continue

        results[asset_name][pred_name] = res

        print(f"  {pred_name:<16} {res['oos_r2']:>8.4f} {res['mae']:>8.4f} "
              f"{res['qlike']:>8.2f} {res['rank_corr']:>8.3f} {res['rank_p']:>8.4f} "
              f"{res['is_r2']:>8.4f}")

# ==================================================================
# 4. Best Predictor per Asset
# ==================================================================
print("\n" + "=" * 78)
print("[4/7] BEST PREDICTOR PER ASSET (by OOS R²)")
print("=" * 78)

best_predictors = {}

for asset_name in ASSETS:
    asset_results = results[asset_name]
    if not asset_results:
        print(f"  {asset_name}: No valid results")
        continue

    # Rank by OOS R² (highest wins)
    sorted_by_r2 = sorted(asset_results.items(), key=lambda x: x[1]["oos_r2"], reverse=True)
    # Rank by QLIKE (lowest wins)
    sorted_by_qlike = sorted(asset_results.items(), key=lambda x: x[1]["qlike"])
    # Rank by MAE (lowest wins)
    sorted_by_mae = sorted(asset_results.items(), key=lambda x: x[1]["mae"])

    best_r2_name = sorted_by_r2[0][0]
    best_qlike_name = sorted_by_qlike[0][0]
    best_mae_name = sorted_by_mae[0][0]

    print(f"\n  {asset_name}:")
    print(f"    Best by OOS R²:  {best_r2_name} ({sorted_by_r2[0][1]['oos_r2']:.4f})")
    print(f"    Best by QLIKE:   {best_qlike_name} ({sorted_by_qlike[0][1]['qlike']:.2f})")
    print(f"    Best by MAE:     {best_mae_name} ({sorted_by_mae[0][1]['mae']:.4f})")

    # Use QLIKE as primary criterion (proxy-robust, Patton 2011)
    best_predictors[asset_name] = {
        "best_r2": best_r2_name,
        "best_qlike": best_qlike_name,
        "best_mae": best_mae_name,
        "primary": best_qlike_name,  # QLIKE is primary
    }

    print(f"\n    Full ranking (by QLIKE):")
    for rank, (name, res) in enumerate(sorted_by_qlike, 1):
        marker = " ★" if name == best_qlike_name else ""
        print(f"      {rank}. {name:<16} QLIKE={res['qlike']:>7.2f}  "
              f"R²={res['oos_r2']:>7.4f}  MAE={res['mae']:>7.4f}{marker}")

# ==================================================================
# 5. Combination Test: Best + VIX
# ==================================================================
print("\n" + "=" * 78)
print("[5/7] COMBINATION: BEST PREDICTOR + VIX")
print("=" * 78)

pred_col_map = {
    "VIX Level": "pred_vix",
    "Own 22d RV": "pred_rv22",
    "Range Ratio": "pred_range",
    "|MOM_12_1|": "pred_absmom",
    "GJR-GARCH": "pred_garch",
    "EWMA(0.94)": "pred_ewma",
}

def oos_combo_regression(df, pred_col1, pred_col2, oos_start, oos_end):
    """OOS regression with two predictors: y = a + b1*x1 + b2*x2"""
    df_valid = df.dropna(subset=["fwd_rv", pred_col1, pred_col2]).copy()

    is_mask = df_valid.index < oos_start
    oos_mask = (df_valid.index >= oos_start) & (df_valid.index <= oos_end)

    is_data = df_valid[is_mask]
    oos_data = df_valid[oos_mask]

    if len(is_data) < 100 or len(oos_data) < 50:
        return None

    # IS fit (OLS with 2 predictors)
    X_is = np.column_stack([np.ones(len(is_data)),
                            is_data[pred_col1].values,
                            is_data[pred_col2].values])
    y_is = is_data["fwd_rv"].values

    try:
        betas = np.linalg.lstsq(X_is, y_is, rcond=None)[0]
    except Exception:
        return None

    # OOS predict
    X_oos = np.column_stack([np.ones(len(oos_data)),
                             oos_data[pred_col1].values,
                             oos_data[pred_col2].values])
    y_oos = oos_data["fwd_rv"].values
    y_pred = X_oos @ betas

    ss_res = np.sum((y_oos - y_pred) ** 2)
    ss_tot = np.sum((y_oos - np.mean(y_oos)) ** 2)
    oos_r2 = 1 - ss_res / ss_tot

    mae = np.mean(np.abs(y_oos - y_pred))

    y_pred_safe = np.maximum(y_pred, 1e-6)
    qlike = np.mean(np.log(y_pred_safe**2) + (y_oos**2) / (y_pred_safe**2))

    return {
        "oos_r2": oos_r2,
        "mae": mae,
        "qlike": qlike,
        "betas": betas.tolist(),
        "oos_n": len(oos_data),
    }

combo_results = {}

for asset_name in ASSETS:
    if asset_name not in best_predictors:
        continue

    best_name = best_predictors[asset_name]["primary"]
    best_col = pred_col_map[best_name]

    # Skip if best is already VIX
    if best_name == "VIX Level":
        print(f"\n  {asset_name}: Best predictor IS VIX — testing VIX + 2nd best")
        # Find 2nd best
        sorted_by_qlike = sorted(results[asset_name].items(), key=lambda x: x[1]["qlike"])
        second_best = sorted_by_qlike[1][0]
        second_col = pred_col_map[second_best]

        combo = oos_combo_regression(asset_data[asset_name], "pred_vix", second_col,
                                     OOS_START, OOS_END)
        if combo:
            vix_only = results[asset_name]["VIX Level"]
            print(f"    VIX only:        QLIKE={vix_only['qlike']:.2f}  R²={vix_only['oos_r2']:.4f}")
            print(f"    VIX + {second_best}: QLIKE={combo['qlike']:.2f}  R²={combo['oos_r2']:.4f}")
            delta_qlike = combo["qlike"] - vix_only["qlike"]
            print(f"    Delta QLIKE: {delta_qlike:+.2f} ({'worse' if delta_qlike > 0 else 'better'})")
            combo_results[asset_name] = combo
        continue

    # Test: best + VIX
    combo = oos_combo_regression(asset_data[asset_name], best_col, "pred_vix",
                                 OOS_START, OOS_END)
    single = results[asset_name][best_name]

    if combo:
        print(f"\n  {asset_name}:")
        print(f"    {best_name} only:    QLIKE={single['qlike']:.2f}  R²={single['oos_r2']:.4f}  "
              f"MAE={single['mae']:.4f}")
        print(f"    {best_name} + VIX:   QLIKE={combo['qlike']:.2f}  R²={combo['oos_r2']:.4f}  "
              f"MAE={combo['mae']:.4f}")
        delta_qlike = combo["qlike"] - single["qlike"]
        delta_r2 = combo["oos_r2"] - single["oos_r2"]
        print(f"    Delta QLIKE: {delta_qlike:+.2f} ({'worse' if delta_qlike > 0 else 'better'})")
        print(f"    Delta R²:    {delta_r2:+.4f} ({'better' if delta_r2 > 0 else 'worse'})")
        combo_results[asset_name] = combo

# ==================================================================
# 6. VT Backtest: Best Predictor vs 12/VIX vs B&H
# ==================================================================
print("\n" + "=" * 78)
print("[6/7] VT BACKTEST: BEST PREDICTOR vs 12/VIX vs B&H")
print("=" * 78)

def backtest_vt(df, sigma_series, target_vol, asset_name, strategy_name,
                max_lev=MAX_LEVERAGE, monthly=True):
    """
    Simple VT backtest.
    Weight = target_vol / sigma_forecast.
    Monthly rebalance.
    """
    df_bt = df.loc[OOS_START:OOS_END].copy()
    sigma_bt = sigma_series.loc[OOS_START:OOS_END].copy()

    # Align
    common_idx = df_bt.index.intersection(sigma_bt.index)
    df_bt = df_bt.loc[common_idx]
    sigma_bt = sigma_bt.loc[common_idx]

    if len(df_bt) < 50:
        return None

    ret = df_bt["ret"].values
    sigma = sigma_bt.values

    n = len(ret)
    weights = np.ones(n)

    if monthly:
        # Monthly rebalance: update weight only at month boundary
        current_weight = target_vol / sigma[0] if sigma[0] > 0 else 1.0
        current_weight = np.clip(current_weight, 0, max_lev)
        current_month = df_bt.index[0].month

        for i in range(n):
            if df_bt.index[i].month != current_month:
                if np.isfinite(sigma[i]) and sigma[i] > 0:
                    current_weight = target_vol / sigma[i]
                    current_weight = np.clip(current_weight, 0, max_lev)
                current_month = df_bt.index[i].month
            weights[i] = current_weight
    else:
        for i in range(n):
            if np.isfinite(sigma[i]) and sigma[i] > 0:
                weights[i] = target_vol / sigma[i]
            else:
                weights[i] = 1.0
        weights = np.clip(weights, 0, max_lev)

    # Apply TX costs
    weight_changes = np.abs(np.diff(weights, prepend=weights[0]))
    tx_costs = weight_changes * TX_COST_BPS / 10000

    vt_ret = weights * ret - tx_costs
    bh_ret = ret

    # Metrics
    def calc_metrics(returns, name):
        cum = np.cumsum(returns)
        total_ret = np.exp(cum[-1]) - 1
        ann_ret = (1 + total_ret) ** (252 / len(returns)) - 1
        ann_vol = np.std(returns) * np.sqrt(252)
        sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

        # MDD
        cum_wealth = np.exp(cum)
        running_max = np.maximum.accumulate(cum_wealth)
        drawdowns = cum_wealth / running_max - 1
        mdd = np.min(drawdowns)

        # Turnover
        total_turnover = np.sum(weight_changes)
        ann_turnover = total_turnover * 252 / len(returns)

        return {
            "name": name,
            "ann_ret": ann_ret,
            "ann_vol": ann_vol,
            "sharpe": sharpe,
            "mdd": mdd,
            "calmar": ann_ret / abs(mdd) if mdd != 0 else 0,
            "total_ret": total_ret,
            "ann_turnover": ann_turnover,
            "avg_weight": np.mean(weights),
        }

    vt_metrics = calc_metrics(vt_ret, strategy_name)
    bh_metrics = calc_metrics(bh_ret, "B&H")

    return vt_metrics, bh_metrics, weights

vt_results = {}

for asset_name in ASSETS:
    if asset_name not in best_predictors:
        continue

    df = asset_data[asset_name]
    target = BTC_TARGET_VOL if asset_name == "BTC" else TARGET_VOL

    print(f"\n{'─' * 60}")
    print(f"  {asset_name} (target vol = {target*100:.0f}%)")
    print(f"{'─' * 60}")

    strategies = {}

    # Strategy 1: Best predictor VT
    best_name = best_predictors[asset_name]["primary"]
    best_col = pred_col_map[best_name]
    sigma_best = df[best_col].copy()

    res = backtest_vt(df, sigma_best, target, asset_name, f"Best({best_name})")
    if res:
        strategies[f"Best({best_name})"] = res[0]
        bh = res[1]

    # Strategy 2: 12/VIX (standard)
    # sigma = VIX / sqrt(252) already annualized in pred_vix
    # weight = target / (VIX/100)  => equivalent to 12/VIX when target=0.12
    sigma_vix = df["pred_vix"].copy()  # This is VIX/100 = annualized vol

    res_vix = backtest_vt(df, sigma_vix, target, asset_name, f"{target*100:.0f}/VIX")
    if res_vix:
        strategies[f"{target*100:.0f}/VIX"] = res_vix[0]

    # Strategy 3: Own 22d RV VT
    sigma_rv = df["pred_rv22"].copy()
    res_rv = backtest_vt(df, sigma_rv, target, asset_name, "Own RV VT")
    if res_rv:
        strategies["Own RV VT"] = res_rv[0]

    # Strategy 4: GARCH VT
    sigma_garch = df["pred_garch"].copy()
    res_garch = backtest_vt(df, sigma_garch, target, asset_name, "GARCH VT")
    if res_garch:
        strategies["GARCH VT"] = res_garch[0]

    # Strategy 5: EWMA VT
    sigma_ewma = df["pred_ewma"].copy()
    res_ewma = backtest_vt(df, sigma_ewma, target, asset_name, "EWMA VT")
    if res_ewma:
        strategies["EWMA VT"] = res_ewma[0]

    # Strategy 6: Range VT
    sigma_range_raw = df["pred_range"].copy()
    # Range ratio needs to be converted to annualized vol scale
    # Approximate: range_ratio * sqrt(252) * scaling_factor
    # Fit scaling: range_ratio_avg / rv22_avg
    valid_mask = df["pred_range"].notna() & df["pred_rv22"].notna()
    if valid_mask.sum() > 100:
        scale_factor = df.loc[valid_mask, "pred_rv22"].mean() / df.loc[valid_mask, "pred_range"].mean()
        sigma_range_scaled = sigma_range_raw * scale_factor
        res_range = backtest_vt(df, sigma_range_scaled, target, asset_name, "Range VT")
        if res_range:
            strategies["Range VT"] = res_range[0]

    # Print results
    print(f"\n  {'Strategy':<22} {'Ann Ret':>8} {'Ann Vol':>8} {'Sharpe':>8} "
          f"{'MDD':>8} {'Calmar':>8} {'Avg Wt':>8}")
    print(f"  {'─'*22} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")

    # B&H first
    if bh:
        print(f"  {'B&H':<22} {bh['ann_ret']:>7.1%} {bh['ann_vol']:>7.1%} "
              f"{bh['sharpe']:>8.2f} {bh['mdd']:>7.1%} {bh['calmar']:>8.2f} {'1.00':>8}")

    for name, m in sorted(strategies.items(), key=lambda x: x[1]["sharpe"], reverse=True):
        print(f"  {name:<22} {m['ann_ret']:>7.1%} {m['ann_vol']:>7.1%} "
              f"{m['sharpe']:>8.2f} {m['mdd']:>7.1%} {m['calmar']:>8.2f} "
              f"{m['avg_weight']:>8.2f}")

    vt_results[asset_name] = {
        "strategies": strategies,
        "bh": bh if bh else None,
        "best_predictor": best_name,
    }

# ==================================================================
# 7. Statistical Significance (DM Test for Vol Forecasts)
# ==================================================================
print("\n" + "=" * 78)
print("[7/7] DIEBOLD-MARIANO TESTS: BEST vs VIX")
print("=" * 78)

def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test.
    H0: E[d_t] = 0 where d_t = e1_t² - e2_t²
    Positive t-stat means model 2 is better (lower loss).
    """
    d = e1**2 - e2**2
    d_mean = np.mean(d)
    d_var = np.var(d, ddof=1) / len(d)

    if d_var <= 0:
        return 0, 1.0

    t_stat = d_mean / np.sqrt(d_var)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))

    return t_stat, p_value

dm_results = {}

for asset_name in ASSETS:
    if asset_name not in best_predictors:
        continue

    df = asset_data[asset_name]
    best_name = best_predictors[asset_name]["primary"]
    best_col = pred_col_map[best_name]

    # Skip if best IS VIX
    if best_name == "VIX Level":
        print(f"\n  {asset_name}: Best = VIX, skipping DM test")
        continue

    # Get OOS data
    df_oos = df.loc[OOS_START:OOS_END].dropna(subset=["fwd_rv", best_col, "pred_vix"])

    if len(df_oos) < 50:
        continue

    y_true = df_oos["fwd_rv"].values

    # Errors for best predictor (using IS-fitted regression)
    res_best = results[asset_name][best_name]
    y_pred_best = res_best["intercept"] + res_best["slope"] * df_oos[best_col].values
    e_best = y_true - y_pred_best

    # Errors for VIX
    res_vix = results[asset_name]["VIX Level"]
    y_pred_vix = res_vix["intercept"] + res_vix["slope"] * df_oos["pred_vix"].values
    e_vix = y_true - y_pred_vix

    t_stat, p_val = dm_test(e_vix, e_best)

    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
    direction = "Best wins" if t_stat > 0 else "VIX wins"

    print(f"\n  {asset_name}: {best_name} vs VIX")
    print(f"    DM t-stat: {t_stat:.3f}  p-value: {p_val:.4f}  {direction} {sig}")

    dm_results[asset_name] = {
        "best_name": best_name,
        "t_stat": t_stat,
        "p_val": p_val,
        "direction": direction,
    }

# ==================================================================
# SUMMARY
# ==================================================================
print("\n" + "=" * 78)
print("K217 SUMMARY: NON-EQUITY OPTIMAL VOL PREDICTORS")
print("=" * 78)

for asset_name in ASSETS:
    if asset_name not in best_predictors:
        continue

    bp = best_predictors[asset_name]
    print(f"\n  {asset_name}:")
    print(f"    Primary (by QLIKE): {bp['primary']}")
    print(f"    By OOS R²:          {bp['best_r2']}")
    print(f"    By MAE:             {bp['best_mae']}")

    if asset_name in dm_results:
        dm = dm_results[asset_name]
        print(f"    DM vs VIX:          t={dm['t_stat']:.3f}, p={dm['p_val']:.4f} ({dm['direction']})")

    if asset_name in vt_results:
        vtr = vt_results[asset_name]
        strats = vtr["strategies"]
        if strats:
            best_strat = max(strats.items(), key=lambda x: x[1]["sharpe"])
            bh = vtr["bh"]
            print(f"    Best VT strategy:   {best_strat[0]} (Sharpe={best_strat[1]['sharpe']:.2f})")
            if bh:
                print(f"    vs B&H:             Sharpe={bh['sharpe']:.2f}, MDD={bh['mdd']:.1%}")

    if asset_name in combo_results:
        combo = combo_results[asset_name]
        single = results[asset_name][bp['primary']]
        print(f"    Adding VIX helps?   QLIKE delta={combo['qlike'] - single['qlike']:+.2f} "
              f"({'YES' if combo['qlike'] < single['qlike'] else 'NO'})")

# ==================================================================
# Save Results
# ==================================================================
output = {
    "experiment": "K217",
    "title": "Non-Equity Optimal VT — Best Vol Predictor per Asset",
    "timestamp": datetime.now().isoformat(),
    "oos_period": f"{OOS_START} to {OOS_END}",
    "predictors_tested": list(predictor_names.values()),
    "assets": {},
}

for asset_name in ASSETS:
    if asset_name not in best_predictors:
        continue

    asset_out = {
        "best_predictors": best_predictors[asset_name],
        "predictor_results": {},
        "dm_test": dm_results.get(asset_name),
        "combo_results": combo_results.get(asset_name),
    }

    for pred_name, res in results.get(asset_name, {}).items():
        asset_out["predictor_results"][pred_name] = {
            k: v for k, v in res.items() if k != "is_n" and k != "oos_n"
        }

    if asset_name in vt_results:
        vtr = vt_results[asset_name]
        asset_out["vt_backtest"] = {}
        for strat_name, m in vtr["strategies"].items():
            asset_out["vt_backtest"][strat_name] = {
                k: float(v) if isinstance(v, (np.floating, float)) else v
                for k, v in m.items()
            }
        if vtr["bh"]:
            asset_out["vt_backtest"]["B&H"] = {
                k: float(v) if isinstance(v, (np.floating, float)) else v
                for k, v in vtr["bh"].items()
            }

    output["assets"][asset_name] = asset_out

results_path = "experiments/k217_nonequity_optimal_vt_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {results_path}")
print(f"\n{'=' * 78}")
print("K217 COMPLETE")
print(f"{'=' * 78}")
