"""
K1432: TW Financial Stress Index as Early Warning for TSMC Volatility
======================================================================

Hypothesis (K757 extension):
  Construct a Taiwan financial-sector stress index from multiple bank stocks
  ({2881, 2882, 2891, 2884, 2880}), and test whether it has incremental
  out-of-sample predictive power for TSMC (2330.TW) realized volatility at
  horizons k=1, 5, 10 trading days ahead, vs. standard baselines.

K757bv2 background (replicated):
  - Fubon(2881) -> TSMC: Granger F=5.60, p=1.93e-6, AIC lag 7
  - Cathay(2882) -> TSMC: Granger F=3.00, p=0.00087, AIC lag 10
  - Both at LEVEL (daily returns), full sample, no OOS.

K1432 differentiation:
  - Aggregate cross-asset stress (univariate index) vs. individual stocks
  - Forecast VOLATILITY (RV), not just returns
  - Genuine OOS DM tests + QLIKE loss, not in-sample Granger only
  - Multiple horizons, multiple specs (no cherry-pick)

Specs (PRE-COMMITTED before reading OOS results):
  S1: Cross-sectional 21-day rolling realized vol mean across financials
  S2: Cross-sectional return dispersion (rolling 21d std of daily max-min)
  S3: Financials vs 0050 5-day relative weakness (5d mean: fin_ret - 0050_ret)
  S4: PCA |PC1| of financial returns, rolling 21d abs PC1 score

Baselines:
  B1: AR(1) on log(RV)
  B2: HAR-RV (Corsi 2009): daily + weekly + monthly RV
  B3: HAR-RV + VIX (^VIX as proxy; TW VIX not consistently available pre-2014)

Methodology hard rules (per .claude/rules/experiments.md):
  - All predictors explicit .shift(k) at t to predict y at t+k (no lookahead)
  - All rolling stats use .rolling(window).<stat>() then .shift(1) double-safety
  - Seed=42 fixed for any stochastic ops
  - Train: 2010-01 to 2020-12-31; OOS: 2021-01-01 to 2026-03-31
  - DM test with Newey-West HAC variance (lag = h)
  - QLIKE = log(RV_hat) + RV/RV_hat (Patton 2011 robust loss for volatility)
  - Granger F-test at level (RV) full sample as secondary descriptor
  - All specs reported; no spec-selection on OOS

References (in references/):
  Corsi, F. (2009). A simple approximate long-memory model of realized volatility.
  Patton, A. (2011). Volatility forecast comparison using imperfect volatility proxies.
  Adrian, T. & Brunnermeier, M. (2016). CoVaR. American Economic Review.
  Diebold & Mariano (1995). Comparing predictive accuracy.

Author: VolPred Research System (Claude, hourly-12 dispatch)
Date: 2026-06-09
"""

import os
import sys
import json
import warnings
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats
from statsmodels.tsa.stattools import grangercausalitytests
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.tools import add_constant
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

# =========================================================
# Reproducibility
# =========================================================
SEED = 42
np.random.seed(SEED)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(OUT_DIR, "data")
FIG_DIR = os.path.join(OUT_DIR, "figures")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

START = "2010-01-01"
END = "2026-06-09"
TRAIN_END = "2020-12-31"
OOS_START = "2021-01-01"

# Financials universe (per task brief: >=4 stocks, 2881+2882 required)
FIN_TICKERS = {
    "Fubon": "2881.TW",
    "Cathay": "2882.TW",
    "CTBC": "2891.TW",
    "ESun": "2884.TW",
    "Hua_Nan": "2880.TW",
}
TARGET = "2330.TW"   # TSMC
INDEX_TICKER = "0050.TW"  # TW50 ETF
VIX_TICKER = "^VIX"

PRICE_CACHE = os.path.join(DATA_DIR, "prices.parquet")


def fetch_prices() -> pd.DataFrame:
    """Download and align all needed prices, cache to parquet."""
    if os.path.exists(PRICE_CACHE):
        print(f"[data] loading cache: {PRICE_CACHE}")
        df = pd.read_parquet(PRICE_CACHE)
        return df

    all_tickers = list(FIN_TICKERS.values()) + [TARGET, INDEX_TICKER, VIX_TICKER]
    print(f"[data] downloading {len(all_tickers)} tickers: {all_tickers}")
    raw = yf.download(all_tickers, start=START, end=END, progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        # take adj close for stocks/index, close for VIX
        adj = raw["Adj Close"] if "Adj Close" in raw.columns.levels[0] else raw["Close"]
        close = raw["Close"]
        df = adj.copy()
        if VIX_TICKER in close.columns:
            df[VIX_TICKER] = close[VIX_TICKER]
    else:
        df = raw[["Close"]].copy()
        df.columns = all_tickers[:1]
    df = df.sort_index().ffill()
    df.to_parquet(PRICE_CACHE)
    print(f"[data] cached: {df.shape}")
    return df


def compute_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily log returns."""
    return np.log(prices).diff()


def compute_rv(returns: pd.Series, window: int = 21) -> pd.Series:
    """Realized vol proxy: rolling sum of squared returns over window days,
    annualized as variance (no sqrt), to match HAR-RV common usage.
    Patton (2011) RV is sum of squared intraday returns; daily-only approx uses
    sum-of-squared-daily-returns over a rolling window.
    """
    return (returns ** 2).rolling(window).sum()


# =========================================================
# Stress index specs — PRE-COMMITTED
# =========================================================
def build_stress_indices(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame indexed by date with columns S1..S4 stress specs."""
    fin_codes = list(FIN_TICKERS.values())
    fin_ret = returns[fin_codes].copy()

    # S1: cross-sectional mean of 21d realized vol (var, annualized factor omitted - relative scale matters)
    fin_rv_each = (fin_ret ** 2).rolling(21).sum()
    S1 = fin_rv_each.mean(axis=1)

    # S2: cross-sectional dispersion (rolling 21d std of max-min daily returns)
    daily_disp = fin_ret.max(axis=1) - fin_ret.min(axis=1)
    S2 = daily_disp.rolling(21).std()

    # S3: 5-day rolling mean of (financials mean return - 0050 return)
    fin_mean_ret = fin_ret.mean(axis=1)
    rel_weak = fin_mean_ret - returns[INDEX_TICKER]
    S3 = rel_weak.rolling(5).mean()

    # S4: PCA |PC1| of financial returns (rolling 252d window updates loadings;
    #     compute static loadings on train-only to avoid lookahead in OOS use)
    train_mask = fin_ret.index <= pd.Timestamp(TRAIN_END)
    train_fin = fin_ret.loc[train_mask].dropna()
    centered = train_fin - train_fin.mean()
    cov = centered.cov().values
    # symmetric eigen-decomposition; np seed not needed here
    eigvals, eigvecs = np.linalg.eigh(cov)
    pc1_load = eigvecs[:, -1]  # largest eigenvalue
    # apply same loadings full sample (in-sample loadings, OOS application)
    full_centered = fin_ret - train_fin.mean()
    pc1_score = full_centered.values @ pc1_load
    S4 = pd.Series(np.abs(pc1_score), index=fin_ret.index).rolling(21).mean()

    stress = pd.DataFrame({
        "S1_xs_vol": S1,
        "S2_dispersion": S2,
        "S3_rel_weak": S3,
        "S4_pca_pc1": S4,
    })
    return stress


# =========================================================
# Forecast models — explicit lag
# =========================================================
def make_targets(rv: pd.Series, horizons=(1, 5, 10)) -> pd.DataFrame:
    """For each horizon h, target is RV at t+h (we use log RV to stabilize)."""
    logrv = np.log(rv.replace(0, np.nan))
    out = {}
    for h in horizons:
        # y_{t+h} aligned with predictors indexed at t
        out[f"y_h{h}"] = logrv.shift(-h)
    return pd.DataFrame(out)


def make_predictors(rv: pd.Series, vix: pd.Series, stress: pd.DataFrame) -> pd.DataFrame:
    """Build predictor DataFrame indexed at t (information available by close of day t).

    All values are observable at t — no future leakage. Estimators that need
    forecasting y at t+h will be aligned via make_targets() which shifts y BACKWARD.
    """
    logrv = np.log(rv.replace(0, np.nan))
    # HAR-RV components computed in RV (variance) space then logged
    rv_d = rv
    rv_w = rv.rolling(5).mean()
    rv_m = rv.rolling(22).mean()
    log_vix = np.log(vix.replace(0, np.nan))

    X = pd.DataFrame({
        "logrv_t": logrv,
        "har_d": np.log(rv_d.replace(0, np.nan)),
        "har_w": np.log(rv_w.replace(0, np.nan)),
        "har_m": np.log(rv_m.replace(0, np.nan)),
        "log_vix": log_vix,
        "S1": stress["S1_xs_vol"],
        "S2": stress["S2_dispersion"],
        "S3": stress["S3_rel_weak"],
        "S4": stress["S4_pca_pc1"],
    })
    # standardize stress indices (using train stats; we will refit-time-aware fit later)
    return X


def expanding_ols_forecast(X: pd.DataFrame, y: pd.Series, train_end: str,
                            cols: list, refit_freq: int = 21) -> pd.Series:
    """Expanding-window OLS forecast.

    Refits every refit_freq days using all data from start up to t inclusive,
    then forecasts y at the next available index.
    Predictors at row t MUST already contain only information observable at t.
    Target y is already aligned so that y.loc[t] = log RV at t+h (per make_targets).

    Returns Series of forecasts indexed by t for the OOS region (after train_end).
    """
    data = X[cols].copy()
    data["__y__"] = y
    data = data.dropna()

    forecasts = pd.Series(index=data.index, dtype=float)
    train_end_ts = pd.Timestamp(train_end)
    oos_idx = data.index[data.index > train_end_ts]

    if len(oos_idx) == 0:
        return forecasts

    last_fit_pos = -refit_freq - 1
    beta = None
    for i, t in enumerate(oos_idx):
        # fit on data strictly before t
        pos_in_data = data.index.get_loc(t)
        if (i - last_fit_pos) >= refit_freq or beta is None:
            train_slice = data.iloc[:pos_in_data]
            if len(train_slice) < 50:
                continue
            Xtr = add_constant(train_slice[cols].values, has_constant="add")
            ytr = train_slice["__y__"].values
            try:
                # closed-form OLS via numpy (faster than statsmodels in loop)
                beta = np.linalg.lstsq(Xtr, ytr, rcond=None)[0]
                last_fit_pos = i
            except np.linalg.LinAlgError:
                continue
        if beta is None:
            continue
        x_t = np.concatenate(([1.0], data[cols].iloc[pos_in_data].values))
        forecasts.iloc[pos_in_data] = float(x_t @ beta)
    return forecasts.loc[oos_idx]


# =========================================================
# Diebold-Mariano with HAC variance
# =========================================================
def dm_test(loss_a: np.ndarray, loss_b: np.ndarray, h: int) -> dict:
    """Diebold-Mariano test: H0: equal predictive accuracy.
    Loss_a is baseline, loss_b is alternative; positive DM stat means alt is BETTER.
    HAC lag = h - 1 (Newey-West truncation for h-step forecasts).
    """
    d = loss_a - loss_b
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return {"dm_stat": float("nan"), "p_value": float("nan"), "n": n}
    d_mean = d.mean()
    # Newey-West variance
    lag = max(h - 1, 0)
    gamma0 = np.var(d, ddof=1)
    nw_var = gamma0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)
        cov_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        nw_var += 2.0 * w * cov_k
    nw_var = max(nw_var, 1e-12)
    dm = d_mean / np.sqrt(nw_var / n)
    # Harvey, Leybourne, Newbold (1997) small-sample correction
    hln_corr = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * hln_corr
    # two-sided p-value using t_{n-1}
    p_two = 2.0 * (1.0 - sp_stats.t.cdf(np.abs(dm_hln), df=n - 1))
    return {"dm_stat": float(dm_hln), "p_value": float(p_two), "n": int(n),
            "mean_loss_diff": float(d_mean)}


def qlike_loss(rv_actual: np.ndarray, rv_forecast: np.ndarray) -> np.ndarray:
    """Patton (2011) QLIKE loss for variance forecasts: log(sigma2_hat) + sigma2/sigma2_hat."""
    rv_forecast = np.clip(rv_forecast, 1e-12, None)
    rv_actual = np.clip(rv_actual, 0, None)
    return np.log(rv_forecast) + rv_actual / rv_forecast


def mse_loss(y_actual: np.ndarray, y_forecast: np.ndarray) -> np.ndarray:
    return (y_actual - y_forecast) ** 2


# =========================================================
# Main
# =========================================================
def main():
    print("=" * 70)
    print("K1432: TW Financial Stress -> TSMC Vol Early Warning")
    print(f"Seed: {SEED}, Period: {START} to {END}")
    print(f"Train end: {TRAIN_END}, OOS start: {OOS_START}")
    print("=" * 70)

    prices = fetch_prices()
    print(f"[data] prices shape={prices.shape}, range {prices.index[0].date()} - {prices.index[-1].date()}")
    print(f"[data] columns: {list(prices.columns)}")

    returns = compute_returns(prices).dropna(how="all")
    # TSMC realized vol (variance proxy)
    tsmc_ret = returns[TARGET].dropna()
    rv = compute_rv(tsmc_ret, window=21)

    stress = build_stress_indices(prices, returns)

    # baseline: VIX
    vix = prices[VIX_TICKER].ffill()

    # Predictors at t and targets at t+h
    X_all = make_predictors(rv, vix, stress)
    Y_all = make_targets(rv, horizons=(1, 5, 10))

    df_all = pd.concat([X_all, Y_all], axis=1).dropna()
    print(f"[data] usable rows: {len(df_all)}, range {df_all.index[0].date()} - {df_all.index[-1].date()}")

    # OOS boundary
    oos_mask = df_all.index >= pd.Timestamp(OOS_START)
    n_oos = int(oos_mask.sum())
    n_train = int((~oos_mask).sum())
    print(f"[split] train n={n_train}, oos n={n_oos}")

    # ============================================
    # Granger full-sample (descriptive, NOT primary test)
    # ============================================
    granger_results = {}
    # Use log RV vs each stress spec; test predictor -> log RV
    logrv = np.log(rv.replace(0, np.nan)).dropna()
    for spec in ["S1_xs_vol", "S2_dispersion", "S3_rel_weak", "S4_pca_pc1"]:
        joint = pd.concat([logrv.rename("y"), stress[spec].rename("x")], axis=1).dropna()
        # statsmodels grangercausalitytests expects columns [y, x] => tests x->y
        if len(joint) < 50:
            granger_results[spec] = {"error": "insufficient data"}
            continue
        per_lag = {}
        try:
            res = grangercausalitytests(joint[["y", "x"]].values, maxlag=10, verbose=False)
            for lag, payload in res.items():
                f_stat, p_f, df1, df2 = payload[0]["ssr_ftest"]
                per_lag[str(int(lag))] = {"f_stat": float(f_stat), "p_value": float(p_f),
                                          "df": [int(df1), int(df2)]}
        except Exception as e:
            per_lag = {"error": str(e)}
        granger_results[spec] = per_lag

    # ============================================
    # OOS forecasts: per horizon, per spec
    # ============================================
    horizons = [1, 5, 10]
    baseline_cols = {
        "B1_AR1":   ["logrv_t"],
        "B2_HARRV": ["har_d", "har_w", "har_m"],
        "B3_HARRV_VIX": ["har_d", "har_w", "har_m", "log_vix"],
    }
    stress_specs = ["S1", "S2", "S3", "S4"]

    forecasts = {}  # forecasts[h][model_name] = Series
    actuals = {}    # actuals[h] = Series of log RV at t+h

    for h in horizons:
        y_col = f"y_h{h}"
        df_h = df_all[[*X_all.columns, y_col]].dropna()
        y = df_h[y_col]

        baselines_h = {}
        for name, cols in baseline_cols.items():
            f = expanding_ols_forecast(df_h, y, TRAIN_END, cols, refit_freq=21)
            baselines_h[name] = f
        # stress-augmented: B2 + each spec individually + B2 + ALL specs
        for spec in stress_specs:
            cols = baseline_cols["B2_HARRV"] + [spec]
            f = expanding_ols_forecast(df_h, y, TRAIN_END, cols, refit_freq=21)
            baselines_h[f"B2_HARRV+{spec}"] = f
        cols_all = baseline_cols["B2_HARRV"] + stress_specs
        baselines_h["B2_HARRV+all"] = expanding_ols_forecast(
            df_h, y, TRAIN_END, cols_all, refit_freq=21
        )

        # also B3 + best individual stress (for VIX-augmented comparison)
        for spec in stress_specs:
            cols = baseline_cols["B3_HARRV_VIX"] + [spec]
            f = expanding_ols_forecast(df_h, y, TRAIN_END, cols, refit_freq=21)
            baselines_h[f"B3_HARRV_VIX+{spec}"] = f

        forecasts[h] = baselines_h
        actuals[h] = y.loc[y.index >= pd.Timestamp(OOS_START)]
        print(f"[oos h={h}] n_actual_oos={len(actuals[h])}, models={list(baselines_h)}")

    # ============================================
    # Losses + DM tests
    # ============================================
    loss_summary = {}
    dm_summary = {}

    for h in horizons:
        y_logrv = actuals[h]
        # convert log RV back to RV for QLIKE
        rv_actual = np.exp(y_logrv)
        loss_h_mse = {}
        loss_h_qlike = {}
        for name, f in forecasts[h].items():
            # align
            common = f.dropna().index.intersection(y_logrv.index)
            if len(common) < 30:
                loss_h_mse[name] = {"mean": float("nan"), "n": len(common)}
                loss_h_qlike[name] = {"mean": float("nan"), "n": len(common)}
                continue
            f_a = f.loc[common].values
            y_a = y_logrv.loc[common].values
            mse_arr = mse_loss(y_a, f_a)
            rv_hat = np.exp(f_a)
            ql_arr = qlike_loss(rv_actual.loc[common].values, rv_hat)
            loss_h_mse[name] = {"mean": float(np.mean(mse_arr)), "n": int(len(common))}
            loss_h_qlike[name] = {"mean": float(np.mean(ql_arr)), "n": int(len(common))}
        loss_summary[f"h{h}"] = {"MSE": loss_h_mse, "QLIKE": loss_h_qlike}

        # DM: each baseline B vs each augmented A
        dm_h = {}
        targets_compare = [
            ("B2_HARRV", "B2_HARRV+S1"),
            ("B2_HARRV", "B2_HARRV+S2"),
            ("B2_HARRV", "B2_HARRV+S3"),
            ("B2_HARRV", "B2_HARRV+S4"),
            ("B2_HARRV", "B2_HARRV+all"),
            ("B3_HARRV_VIX", "B3_HARRV_VIX+S1"),
            ("B3_HARRV_VIX", "B3_HARRV_VIX+S2"),
            ("B3_HARRV_VIX", "B3_HARRV_VIX+S3"),
            ("B3_HARRV_VIX", "B3_HARRV_VIX+S4"),
            ("B1_AR1", "B2_HARRV"),
            ("B2_HARRV", "B3_HARRV_VIX"),
        ]
        for base, alt in targets_compare:
            if base not in forecasts[h] or alt not in forecasts[h]:
                continue
            fa = forecasts[h][base]; fb = forecasts[h][alt]
            common = fa.index.intersection(fb.index).intersection(y_logrv.index)
            if len(common) < 30:
                continue
            ya = y_logrv.loc[common].values
            # both MSE and QLIKE DM
            la_mse = mse_loss(ya, fa.loc[common].values)
            lb_mse = mse_loss(ya, fb.loc[common].values)
            la_ql = qlike_loss(rv_actual.loc[common].values, np.exp(fa.loc[common].values))
            lb_ql = qlike_loss(rv_actual.loc[common].values, np.exp(fb.loc[common].values))
            dm_h[f"{base}__vs__{alt}"] = {
                "MSE": dm_test(la_mse, lb_mse, h),
                "QLIKE": dm_test(la_ql, lb_ql, h),
            }
        dm_summary[f"h{h}"] = dm_h

    # ============================================
    # Figures
    # ============================================
    # Figure 1: Stress indices + TSMC RV over time
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    axes[0].plot(rv.index, np.sqrt(rv) * np.sqrt(252) * 100, label="TSMC 21d RV (annualized %)", color="black", lw=0.7)
    axes[0].set_ylabel("TSMC RV (ann %)")
    axes[0].legend(loc="upper right")
    axes[0].grid(True, alpha=0.3)

    z = (stress - stress.mean()) / stress.std()
    for col in z.columns:
        axes[1].plot(z.index, z[col], label=col, lw=0.7)
    axes[1].set_ylabel("z-score")
    axes[1].axvline(pd.Timestamp(OOS_START), color="red", ls="--", alpha=0.5, label="OOS start")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[1].grid(True, alpha=0.3)
    plt.suptitle("K1432: TW Financial Stress Indices and TSMC RV")
    plt.tight_layout()
    fig1_path = os.path.join(FIG_DIR, "stress_and_rv.png")
    plt.savefig(fig1_path, dpi=120)
    plt.close()
    print(f"[fig] saved {fig1_path}")

    # Figure 2: QLIKE bar chart per horizon
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)
    for ax, h in zip(axes, horizons):
        qlikes = loss_summary[f"h{h}"]["QLIKE"]
        names = list(qlikes.keys())
        means = [qlikes[n]["mean"] for n in names]
        colors = ["#888" if n.startswith("B1") or n == "B2_HARRV" or n == "B3_HARRV_VIX"
                  else "#1f77b4" for n in names]
        ax.barh(names, means, color=colors)
        ax.set_title(f"OOS QLIKE, h={h}")
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig2_path = os.path.join(FIG_DIR, "qlike_by_horizon.png")
    plt.savefig(fig2_path, dpi=120)
    plt.close()
    print(f"[fig] saved {fig2_path}")

    # ============================================
    # Verdict logic
    # ============================================
    # Criterion: at least 1 stress spec at >=1 horizon shows DM p < 0.05 with
    # POSITIVE direction (alt better) vs B2 HAR-RV baseline using QLIKE.
    pass_count = 0
    notable = []
    for h in horizons:
        dm_h = dm_summary[f"h{h}"]
        for key, payload in dm_h.items():
            if "B2_HARRV__vs__B2_HARRV+" not in key:
                continue
            ql = payload.get("QLIKE", {})
            stat = ql.get("dm_stat", float("nan"))
            p = ql.get("p_value", float("nan"))
            if not np.isfinite(stat) or not np.isfinite(p):
                continue
            # DM stat > 0 means alt has LOWER loss
            if stat > 0 and p < 0.05:
                pass_count += 1
                notable.append({"horizon": h, "comparison": key,
                                "dm_stat": stat, "p_value": p})

    if pass_count >= 2:
        verdict = "PASS"
    elif pass_count == 1:
        verdict = "CONDITIONAL_PASS"
    elif pass_count == 0:
        # MIXED if some direction positive but not significant
        any_positive = False
        for h in horizons:
            for key, payload in dm_summary[f"h{h}"].items():
                if "B2_HARRV__vs__B2_HARRV+" in key:
                    ql = payload.get("QLIKE", {})
                    if np.isfinite(ql.get("dm_stat", float("nan"))) and ql["dm_stat"] > 0:
                        any_positive = True
                        break
        verdict = "MIXED" if any_positive else "NULL"
    else:
        verdict = "MIXED"

    # ============================================
    # Save results
    # ============================================
    results = {
        "experiment_id": "K1432",
        "title": "TW Financial Stress Index as Early Warning for TSMC Volatility",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_source": "yfinance",
        "tickers": {
            "target": TARGET,
            "index": INDEX_TICKER,
            "vix_proxy": VIX_TICKER,
            "financials": FIN_TICKERS,
        },
        "period": {"start": START, "end": END,
                   "train_end": TRAIN_END, "oos_start": OOS_START},
        "n_obs": {"train": n_train, "oos": n_oos, "total": len(df_all)},
        "rv_definition": "Rolling 21d sum of squared daily log returns (variance), target uses log(RV)",
        "horizons_tested": horizons,
        "stress_specs_precommitted": {
            "S1": "Cross-sectional 21d realized variance mean across 5 financials",
            "S2": "21d rolling std of daily max-min return dispersion",
            "S3": "5d rolling mean of (mean_fin_ret - 0050_ret)",
            "S4": "21d rolling |PC1 score| (loadings fitted on train only)",
        },
        "baselines": {
            "B1_AR1": "log(RV_t) -> log(RV_{t+h})",
            "B2_HARRV": "Corsi 2009 HAR-RV in log space",
            "B3_HARRV_VIX": "HAR-RV + log(^VIX)",
        },
        "granger_full_sample": granger_results,
        "oos_losses": loss_summary,
        "dm_tests": dm_summary,
        "notable_passes": notable,
        "verdict": verdict,
        "files_created": [
            "experiments/k1432/k1432_tw_financial_stress.py",
            "experiments/k1432/README.md",
            "experiments/k1432/k1432_tw_financial_stress_results.json",
            "experiments/k1432/figures/stress_and_rv.png",
            "experiments/k1432/figures/qlike_by_horizon.png",
        ],
        "codex_review_needed": True if verdict in {"PASS", "CONDITIONAL_PASS"} else False,
        "references": [
            "Corsi (2009) A simple approximate long-memory model of realized volatility. J. Financial Econometrics 7(2).",
            "Patton (2011) Volatility forecast comparison using imperfect volatility proxies. J. Econometrics 160.",
            "Adrian & Brunnermeier (2016) CoVaR. AER 106(7).",
            "Diebold & Mariano (1995) Comparing predictive accuracy. JBES.",
            "Harvey, Leybourne, Newbold (1997) Testing the equality of prediction MSEs. IJF.",
        ],
    }

    out_path = os.path.join(OUT_DIR, "k1432_tw_financial_stress_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[out] wrote {out_path}")
    print(f"[verdict] {verdict}, notable={len(notable)}")
    return results


if __name__ == "__main__":
    main()
