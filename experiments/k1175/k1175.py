"""
K1175: Paper 2 Table 3 VT Performance 2010-2026 Canonical Replication
======================================================================
BLOCKER D1 resolution: replicate K900 methodology with data_start=2010-01-01
to produce canonical Table 3 numbers for paper/taiwan-vt/main.tex.

Paper 2 Table 3 claims (body.tex lines 254-258):
  Buy & Hold:       Sharpe=0.729, MDD=-41.3%, Ann Return=10.2%, Ann Vol=20.8%, TO=0
  EWMA VT (10%):    Sharpe=0.796, MDD=-18.4%, Ann Return=7.8%, Ann Vol=10.2%, TO=116
  GARCH VT (10%):   Sharpe=0.994, MDD=-16.8%, Ann Return=8.1%, Ann Vol=10.5%, TO=98
  GJR VT (10%):     Sharpe=1.108, MDD=-15.1%, Ann Return=8.4%, Ann Vol=10.3%, TO=102
  8.63/VIX (monthly): Sharpe=0.690, MDD=-15.3%, Ann Return=7.2%, Ann Vol=12.1%, TO=24

Notes (body.tex line 264):
  Buy & Hold and EWMA VT cover 2010--2026
  GARCH VT and GJR VT cover 2020--2026
  8.63/VIX covers 2016--2026

Methodology: identical to K900 except DATA_START=2010-01-01 and OOS_START=2010-01-01

Author: VolPred Research System (Yi-Hao Lai)
Date: 2026-04-17
Seed: 42
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats as sp_stats

# CRITICAL: clean 0050.TW split artifact (same as K900)
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from volpred.utils import clean_tw50_data
from volpred.stats.model_evaluation import strategy_dm_test

warnings.filterwarnings("ignore")
np.random.seed(42)

# ============================================================================
# Configuration — IDENTICAL to K900 except data/OOS periods
# ============================================================================
DATA_START = "2008-01-01"    # same as K900 — need pre-2010 for GARCH warmup
DATA_END = "2026-03-31"
OOS_START_BH_EWMA = "2010-01-01"  # Buy & Hold + EWMA cover 2010-2026
OOS_START_GARCH = "2020-01-01"    # GARCH VT + GJR VT cover 2020-2026 per paper note
OOS_START_VIX863 = "2016-01-01"   # 8.63/VIX covers 2016-2026 per paper note

EWMA_LAMBDA = 0.94
TARGET_VOL = 0.10           # 10% annualized
GARCH_WINDOW = 2000
TX_COST = 0.00186           # Round-trip: ETF tax 0.10% + commission 0.04275%×2

RESULTS_DIR = Path(__file__).resolve().parent

print("=" * 70)
print("K1175: Paper 2 Table 3 VT 2010-2026 Canonical Replication")
print("=" * 70)

# ============================================================================
# 1. Data Download
# ============================================================================
print("\n[1] Downloading data...")

tw_raw = yf.download("0050.TW", start=DATA_START, end=DATA_END, progress=False)
if isinstance(tw_raw.columns, pd.MultiIndex):
    tw_raw.columns = tw_raw.columns.get_level_values(0)
tw_prices_raw = tw_raw["Close"].copy()
tw_prices, tw_returns = clean_tw50_data(tw_prices_raw)
print(f"  0050.TW (CLEAN): {len(tw_prices)} days "
      f"({tw_prices.index[0].date()} to {tw_prices.index[-1].date()})")

vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw["Close"].copy()
print(f"  ^VIX: {len(vix_series)} days")

# ============================================================================
# 2. Build VIX-for-Taiwan (lagged: use previous US trading day's VIX)
# ============================================================================
print("\n[2] Building lagged VIX for Taiwan...")

tw_dates = sorted(tw_returns.index)
vix_sorted = vix_series.sort_index()

vix_for_tw = pd.Series(index=pd.DatetimeIndex(tw_dates), dtype=float, name="VIX_lag")
for d in tw_dates:
    mask = vix_sorted.index < d
    if mask.any():
        vix_for_tw.loc[d] = float(vix_sorted.loc[mask].iloc[-1])
    else:
        vix_for_tw.loc[d] = np.nan

vix_for_tw = vix_for_tw.dropna()
print(f"  VIX-for-Taiwan: {len(vix_for_tw)} days")

# ============================================================================
# 3. EWMA Volatility Model
# ============================================================================
def compute_ewma_vol(returns, lam=EWMA_LAMBDA):
    """EWMA volatility (annualized). Identical to K900."""
    var = np.zeros(len(returns))
    var[0] = returns.iloc[0] ** 2
    for i in range(1, len(returns)):
        var[i] = lam * var[i - 1] + (1 - lam) * returns.iloc[i] ** 2
    vol_ann = np.sqrt(var) * np.sqrt(252)
    return pd.Series(vol_ann, index=returns.index, name="ewma_vol")


# ============================================================================
# 4. Standard GARCH(1,1) OOS Forecasting (day-by-day recursive)
# ============================================================================
def garch_oos_forecast(returns, oos_start, window=GARCH_WINDOW, refit_every=21):
    """
    GARCH(1,1) OOS forecasting — analogous to K900's GJR-GARCH but symmetric.
    Uses rolling window; refits every refit_every days.
    """
    returns = returns.dropna()
    oos_mask = returns.index >= oos_start
    oos_dates = returns.index[oos_mask]
    forecasts = pd.Series(index=oos_dates, dtype=float, name="garch_vol")

    omega, alpha, beta = 0, 0, 0
    last_h = None
    last_r = None
    last_fit_idx = -refit_every

    for i, date in enumerate(oos_dates):
        date_loc = returns.index.get_loc(date)

        if i - last_fit_idx >= refit_every or last_h is None:
            train_start = max(0, date_loc - window)
            train_data = returns.iloc[train_start:date_loc]

            if len(train_data) < 500:
                forecasts.loc[date] = np.nan
                continue

            try:
                am = arch_model(train_data * 100, vol="Garch", p=1, o=0, q=1,
                                mean="Zero", dist="normal")
                res = am.fit(disp="off", show_warning=False)
                omega = res.params.get("omega", 0)
                alpha = res.params.get("alpha[1]", 0)
                beta = res.params.get("beta[1]", 0)
                last_h = float(res.conditional_volatility.iloc[-1]) ** 2
                last_r = float(train_data.iloc[-1] * 100)
                last_fit_idx = i
            except Exception:
                forecasts.loc[date] = np.nan
                continue

        if last_h is not None and last_r is not None:
            h_t = omega + alpha * last_r**2 + beta * last_h
            vol_daily = np.sqrt(max(h_t, 1e-10)) / 100
            vol_ann = vol_daily * np.sqrt(252)
            forecasts.loc[date] = vol_ann
            last_h = h_t
            last_r = float(returns.iloc[date_loc] * 100) if date_loc < len(returns) else last_r
        else:
            forecasts.loc[date] = np.nan

    return forecasts.dropna()


# ============================================================================
# 5. GJR-GARCH OOS Forecasting (identical to K900)
# ============================================================================
def gjr_garch_oos_forecast(returns, oos_start, window=GARCH_WINDOW, refit_every=21):
    """
    GJR-GARCH(1,1) OOS — identical to K900.
    """
    returns = returns.dropna()
    oos_mask = returns.index >= oos_start
    oos_dates = returns.index[oos_mask]
    forecasts = pd.Series(index=oos_dates, dtype=float, name="gjr_vol")

    omega, alpha, gamma_gjr, beta = 0, 0, 0, 0
    last_h = None
    last_r = None
    last_fit_idx = -refit_every

    for i, date in enumerate(oos_dates):
        date_loc = returns.index.get_loc(date)

        if i - last_fit_idx >= refit_every or last_h is None:
            train_start = max(0, date_loc - window)
            train_data = returns.iloc[train_start:date_loc]

            if len(train_data) < 500:
                forecasts.loc[date] = np.nan
                continue

            try:
                am = arch_model(train_data * 100, vol="Garch", p=1, o=1, q=1,
                                mean="Zero", dist="normal")
                res = am.fit(disp="off", show_warning=False)
                omega = res.params.get("omega", 0)
                alpha = res.params.get("alpha[1]", 0)
                gamma_gjr = res.params.get("gamma[1]", 0)
                beta = res.params.get("beta[1]", 0)
                last_h = float(res.conditional_volatility.iloc[-1]) ** 2
                last_r = float(train_data.iloc[-1] * 100)
                last_fit_idx = i
            except Exception:
                forecasts.loc[date] = np.nan
                continue

        if last_h is not None and last_r is not None:
            indicator = 1.0 if last_r < 0 else 0.0
            h_t = omega + alpha * last_r**2 + gamma_gjr * indicator * last_r**2 + beta * last_h
            vol_daily = np.sqrt(max(h_t, 1e-10)) / 100
            vol_ann = vol_daily * np.sqrt(252)
            forecasts.loc[date] = vol_ann
            last_h = h_t
            last_r = float(returns.iloc[date_loc] * 100) if date_loc < len(returns) else last_r
        else:
            forecasts.loc[date] = np.nan

    return forecasts.dropna()


# ============================================================================
# 6. Strategy Backtest Engine (identical to K900)
# ============================================================================
def backtest_strategy(returns, weights, name, tx_cost=TX_COST):
    """
    Backtest a VT strategy. Identical to K900.
    weights: already lagged via shift(1) before calling this function.
    """
    idx = returns.index.intersection(weights.dropna().index)
    r = returns.loc[idx]
    w = weights.loc[idx]

    w_change = w.diff().abs().fillna(0)
    tc = w_change * tx_cost

    port_ret = w * r - tc
    port_ret = port_ret.dropna()

    if len(port_ret) < 100:
        return {"name": name, "error": "insufficient data", "n_days": len(port_ret)}

    n_years = len(port_ret) / 252

    ann_ret = (1 + port_ret).prod() ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + port_ret).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min()
    calmar = ann_ret / abs(mdd) if mdd < 0 else 0

    down_ret = port_ret[port_ret < 0]
    sortino = ann_ret / (down_ret.std() * np.sqrt(252)) if len(down_ret) > 10 else 0

    ann_turnover = float(w_change.sum() / n_years) if n_years > 0 else 0
    ann_tx_drag = float(tc.sum() / n_years) if n_years > 0 else 0

    var_1pct = np.percentile(port_ret, 1)
    var_5pct = np.percentile(port_ret, 5)
    es_1pct = port_ret[port_ret <= var_1pct].mean() if (port_ret <= var_1pct).sum() > 0 else var_1pct
    es_5pct = port_ret[port_ret <= var_5pct].mean() if (port_ret <= var_5pct).sum() > 0 else var_5pct

    return {
        "name": name,
        "n_days": len(port_ret),
        "n_years": round(n_years, 2),
        "period": f"{port_ret.index[0].date()} to {port_ret.index[-1].date()}",
        "ann_return_pct": round(float(ann_ret) * 100, 2),
        "ann_vol_pct": round(float(ann_vol) * 100, 2),
        "sharpe": round(float(sharpe), 4),
        "sortino": round(float(sortino), 4),
        "mdd_pct": round(float(mdd) * 100, 2),
        "calmar": round(float(calmar), 4),
        "var_1pct": round(float(var_1pct) * 100, 4),
        "var_5pct": round(float(var_5pct) * 100, 4),
        "es_1pct": round(float(es_1pct) * 100, 4),
        "es_5pct": round(float(es_5pct) * 100, 4),
        "ann_turnover_pct": round(ann_turnover * 100, 1),
        "ann_tx_drag_bps": round(ann_tx_drag * 10000, 1),
        "daily_returns": port_ret,
    }


# ============================================================================
# 7. Build All Strategies
# ============================================================================
print("\n[3] Building strategies...")

# --- Strategy 1: Buy & Hold ---
bh_weights = pd.Series(1.0, index=tw_returns.index)

# --- Strategy 2: 8.63/VIX VT (monthly) ---
def build_vix_vt_weights(vix, target_k, rebal="monthly"):
    """Build VIX VT weights with proper lag. Identical to K900."""
    raw_signal = (target_k / vix).clip(0, 1)
    signal_lagged = raw_signal.shift(1)  # CRITICAL: enforce lag

    if rebal == "monthly":
        month_start = signal_lagged.index.to_series().dt.month.diff().ne(0)
        w = signal_lagged.copy()
        w[~month_start] = np.nan
        w = w.ffill().dropna()
    else:
        w = signal_lagged.dropna()
    return w

vix_863_weights = build_vix_vt_weights(vix_for_tw, 8.63, rebal="monthly")
print(f"  8.63/VIX weights: {len(vix_863_weights)} days, "
      f"first={vix_863_weights.index[0].date()}")

# --- Strategy 3: GARCH VT (10%) ---
print("\n  Fitting GARCH(1,1) OOS (this may take several minutes)...")
# For GARCH/GJR we use OOS_START_GARCH per paper's Table 3 note
garch_vol_forecast = garch_oos_forecast(tw_returns, oos_start=OOS_START_GARCH,
                                         window=GARCH_WINDOW, refit_every=21)
print(f"  GARCH forecasts: {len(garch_vol_forecast)} days "
      f"({garch_vol_forecast.index[0].date()} to {garch_vol_forecast.index[-1].date()})")

garch_raw = (TARGET_VOL / garch_vol_forecast).clip(0, 1)
garch_weights = garch_raw.shift(1).dropna()
print(f"  GARCH weights: {len(garch_weights)} days")

# --- Strategy 4: GJR-GARCH VT (10%) ---
print("\n  Fitting GJR-GARCH OOS (this may take several minutes)...")
gjr_vol_forecast = gjr_garch_oos_forecast(tw_returns, oos_start=OOS_START_GARCH,
                                            window=GARCH_WINDOW, refit_every=21)
print(f"  GJR-GARCH forecasts: {len(gjr_vol_forecast)} days "
      f"({gjr_vol_forecast.index[0].date()} to {gjr_vol_forecast.index[-1].date()})")

gjr_raw = (TARGET_VOL / gjr_vol_forecast).clip(0, 1)
gjr_weights = gjr_raw.shift(1).dropna()
print(f"  GJR weights: {len(gjr_weights)} days")

# --- Strategy 5: EWMA VT (10%) ---
ewma_vol = compute_ewma_vol(tw_returns.dropna(), lam=EWMA_LAMBDA)
ewma_raw = (TARGET_VOL / ewma_vol).clip(0, 1)
ewma_weights = ewma_raw.shift(1).dropna()
print(f"  EWMA weights: {len(ewma_weights)} days, "
      f"first={ewma_weights.index[0].date()}")


# ============================================================================
# 8. Evaluate Per-Strategy (per-paper periods)
# ============================================================================
print("\n[4] Evaluating strategies per paper's stated periods...")

# Buy & Hold 2010-2026
bh_w = bh_weights[bh_weights.index >= OOS_START_BH_EWMA]
bh_r = tw_returns[tw_returns.index >= OOS_START_BH_EWMA]
res_bh = backtest_strategy(bh_r, bh_w, "Buy & Hold (2010-2026)")
if "daily_returns" in res_bh:
    res_bh.pop("daily_returns")
print(f"  Buy & Hold:  Sharpe={res_bh['sharpe']:.4f}, MDD={res_bh['mdd_pct']:.2f}%, "
      f"Return={res_bh['ann_return_pct']:.2f}%, Vol={res_bh['ann_vol_pct']:.2f}%, "
      f"TO={res_bh['ann_turnover_pct']:.1f}")
print(f"    Period: {res_bh['period']}, N={res_bh['n_days']}")

# EWMA VT 2010-2026
ewma_w = ewma_weights[ewma_weights.index >= OOS_START_BH_EWMA]
ewma_r = tw_returns[tw_returns.index >= OOS_START_BH_EWMA]
res_ewma = backtest_strategy(ewma_r, ewma_w, "EWMA VT 10% (2010-2026)")
if "daily_returns" in res_ewma:
    res_ewma.pop("daily_returns")
print(f"  EWMA VT:     Sharpe={res_ewma['sharpe']:.4f}, MDD={res_ewma['mdd_pct']:.2f}%, "
      f"Return={res_ewma['ann_return_pct']:.2f}%, Vol={res_ewma['ann_vol_pct']:.2f}%, "
      f"TO={res_ewma['ann_turnover_pct']:.1f}")
print(f"    Period: {res_ewma['period']}, N={res_ewma['n_days']}")

# GARCH VT 2020-2026 (per paper note)
garch_w = garch_weights[garch_weights.index >= OOS_START_GARCH]
garch_r = tw_returns[tw_returns.index >= OOS_START_GARCH]
res_garch = backtest_strategy(garch_r, garch_w, "GARCH VT 10% (2020-2026)")
if "daily_returns" in res_garch:
    res_garch.pop("daily_returns")
print(f"  GARCH VT:    Sharpe={res_garch['sharpe']:.4f}, MDD={res_garch['mdd_pct']:.2f}%, "
      f"Return={res_garch['ann_return_pct']:.2f}%, Vol={res_garch['ann_vol_pct']:.2f}%, "
      f"TO={res_garch['ann_turnover_pct']:.1f}")
print(f"    Period: {res_garch['period']}, N={res_garch['n_days']}")

# GJR VT 2020-2026 (per paper note)
gjr_w = gjr_weights[gjr_weights.index >= OOS_START_GARCH]
gjr_r = tw_returns[tw_returns.index >= OOS_START_GARCH]
res_gjr = backtest_strategy(gjr_r, gjr_w, "GJR VT 10% (2020-2026)")
if "daily_returns" in res_gjr:
    res_gjr.pop("daily_returns")
print(f"  GJR VT:      Sharpe={res_gjr['sharpe']:.4f}, MDD={res_gjr['mdd_pct']:.2f}%, "
      f"Return={res_gjr['ann_return_pct']:.2f}%, Vol={res_gjr['ann_vol_pct']:.2f}%, "
      f"TO={res_gjr['ann_turnover_pct']:.1f}")
print(f"    Period: {res_gjr['period']}, N={res_gjr['n_days']}")

# 8.63/VIX 2016-2026 (per paper note)
vix_w = vix_863_weights[vix_863_weights.index >= OOS_START_VIX863]
vix_r = tw_returns[tw_returns.index >= OOS_START_VIX863]
res_vix = backtest_strategy(vix_r, vix_w, "8.63/VIX monthly (2016-2026)")
if "daily_returns" in res_vix:
    res_vix.pop("daily_returns")
print(f"  8.63/VIX:    Sharpe={res_vix['sharpe']:.4f}, MDD={res_vix['mdd_pct']:.2f}%, "
      f"Return={res_vix['ann_return_pct']:.2f}%, Vol={res_vix['ann_vol_pct']:.2f}%, "
      f"TO={res_vix['ann_turnover_pct']:.1f}")
print(f"    Period: {res_vix['period']}, N={res_vix['n_days']}")


# ============================================================================
# 9. Diff vs Paper Table 3
# ============================================================================
print("\n[5] Computing diff vs Paper 2 Table 3...")

paper_table3 = {
    "buy_hold": {
        "sharpe": 0.729, "mdd_pct": -41.3, "ann_return_pct": 10.2, "ann_vol_pct": 20.8, "ann_turnover_pct": 0
    },
    "ewma_vt": {
        "sharpe": 0.796, "mdd_pct": -18.4, "ann_return_pct": 7.8, "ann_vol_pct": 10.2, "ann_turnover_pct": 116
    },
    "garch_vt": {
        "sharpe": 0.994, "mdd_pct": -16.8, "ann_return_pct": 8.1, "ann_vol_pct": 10.5, "ann_turnover_pct": 98
    },
    "gjr_vt": {
        "sharpe": 1.108, "mdd_pct": -15.1, "ann_return_pct": 8.4, "ann_vol_pct": 10.3, "ann_turnover_pct": 102
    },
    "vix_863": {
        "sharpe": 0.690, "mdd_pct": -15.3, "ann_return_pct": 7.2, "ann_vol_pct": 12.1, "ann_turnover_pct": 24
    },
}

k1175_results = {
    "buy_hold": {
        "sharpe": res_bh["sharpe"], "mdd_pct": res_bh["mdd_pct"],
        "ann_return_pct": res_bh["ann_return_pct"], "ann_vol_pct": res_bh["ann_vol_pct"],
        "ann_turnover_pct": res_bh["ann_turnover_pct"]
    },
    "ewma_vt": {
        "sharpe": res_ewma["sharpe"], "mdd_pct": res_ewma["mdd_pct"],
        "ann_return_pct": res_ewma["ann_return_pct"], "ann_vol_pct": res_ewma["ann_vol_pct"],
        "ann_turnover_pct": res_ewma["ann_turnover_pct"]
    },
    "garch_vt": {
        "sharpe": res_garch["sharpe"], "mdd_pct": res_garch["mdd_pct"],
        "ann_return_pct": res_garch["ann_return_pct"], "ann_vol_pct": res_garch["ann_vol_pct"],
        "ann_turnover_pct": res_garch["ann_turnover_pct"]
    },
    "gjr_vt": {
        "sharpe": res_gjr["sharpe"], "mdd_pct": res_gjr["mdd_pct"],
        "ann_return_pct": res_gjr["ann_return_pct"], "ann_vol_pct": res_gjr["ann_vol_pct"],
        "ann_turnover_pct": res_gjr["ann_turnover_pct"]
    },
    "vix_863": {
        "sharpe": res_vix["sharpe"], "mdd_pct": res_vix["mdd_pct"],
        "ann_return_pct": res_vix["ann_return_pct"], "ann_vol_pct": res_vix["ann_vol_pct"],
        "ann_turnover_pct": res_vix["ann_turnover_pct"]
    },
}

diff_table = {}
for strat in paper_table3:
    paper = paper_table3[strat]
    k1175 = k1175_results[strat]
    diffs = {}
    for metric in ["sharpe", "mdd_pct", "ann_return_pct", "ann_vol_pct", "ann_turnover_pct"]:
        p_val = paper[metric]
        k_val = k1175[metric]
        abs_diff = k_val - p_val
        rel_diff = abs((k_val - p_val) / p_val) if p_val != 0 else float("inf")
        status = "MATCHED" if rel_diff <= 0.05 else ("APPROX" if rel_diff <= 0.10 else "DIVERGENT")
        diffs[metric] = {
            "paper": p_val, "k1175": k_val,
            "abs_diff": round(abs_diff, 4),
            "rel_diff_pct": round(rel_diff * 100, 1),
            "status": status,
        }
    diff_table[strat] = diffs
    print(f"\n  [{strat.upper()}]")
    for metric, d in diffs.items():
        flag = "OK" if d["status"] == "MATCHED" else ("~OK" if d["status"] == "APPROX" else "!!!DIVERGENT!!!")
        print(f"    {metric:20s}: paper={d['paper']:8.3f}  k1175={d['k1175']:8.3f}  "
              f"diff={d['abs_diff']:+.4f} ({d['rel_diff_pct']:.1f}%)  [{flag}]")


# ============================================================================
# 10. Save Results
# ============================================================================
print("\n[6] Saving results...")

results = {
    "experiment_id": "K1175",
    "title": "Paper 2 Table 3 VT 2010-2026 Canonical Replication",
    "purpose": (
        "BLOCKER D1 resolution: replicate K900 methodology with data_start=2010-01-01 "
        "to produce canonical numbers for Paper 2 Table 3 (VT Performance). "
        "Diagnosing match status to guide (a)/(b)/(c) decision."
    ),
    "data_source": "yfinance (0050.TW, ^VIX) with clean_tw50_data split correction",
    "data_period": f"{tw_prices.index[0].date()} to {tw_prices.index[-1].date()}",
    "data_period_bh_ewma": "2010-01-01 to 2026-03-31",
    "data_period_garch_gjr": "2020-01-01 to 2026-03-31",
    "data_period_vix863": "2016-01-01 to 2026-03-31",
    "n_tw_trading_days_total": len(tw_returns),

    "configuration": {
        "ewma_lambda": EWMA_LAMBDA,
        "target_vol": TARGET_VOL,
        "garch_window": GARCH_WINDOW,
        "tx_cost_roundtrip": TX_COST,
        "vix_lag": "Previous US trading day close (strictly < Taiwan date)",
        "rebalancing": "Monthly for VIX strategies, daily rebalancing for GARCH/EWMA",
        "seed": 42,
        "methodology": "Identical to K900 except per-strategy OOS periods match paper's Table 3 notes",
    },

    "paper_table3_claimed": paper_table3,
    "k1175_results": {
        "buy_hold": res_bh,
        "ewma_vt": res_ewma,
        "garch_vt": res_garch,
        "gjr_vt": res_gjr,
        "vix_863": res_vix,
    },

    "diff_vs_paper_table3": diff_table,

    "timestamp": datetime.now().isoformat(),
    "proposer": "User (K1175 BLOCKER D1)",
    "executor": "Claude (worktree agent-a65a26a5)",
}

output_path = RESULTS_DIR / "k1175_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str, ensure_ascii=False)

print(f"\nResults saved to {output_path}")

# ============================================================================
# 11. Summary Table
# ============================================================================
print("\n" + "=" * 100)
print("K1175 vs PAPER TABLE 3 SUMMARY")
print("=" * 100)
print(f"{'Strategy':<20s} {'Metric':<22s} {'Paper':>9s} {'K1175':>9s} {'Diff%':>7s}  {'Status'}")
print("-" * 100)
for strat in ["buy_hold", "ewma_vt", "garch_vt", "gjr_vt", "vix_863"]:
    for metric in ["sharpe", "mdd_pct", "ann_return_pct", "ann_vol_pct", "ann_turnover_pct"]:
        d = diff_table[strat][metric]
        print(f"  {strat:<18s} {metric:<22s} {d['paper']:>9.3f} {d['k1175']:>9.3f} "
              f"{d['rel_diff_pct']:>6.1f}%  {d['status']}")
    print()

print("=" * 70)
print("K1175 COMPLETE — Paper 2 Table 3 VT 2010-2026 Canonical Replication")
print("=" * 70)
