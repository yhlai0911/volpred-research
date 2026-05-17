"""K1371: HAR-RV-X — Financial Sector Lead as TSMC Volatility Predictor.

Tests whether Fubon/Cathay Financial lagged realized variance improves
TSMC HAR-RV out-of-sample QLIKE forecasts.

Grounded in K757 Granger finding: Fubon->TSMC F=6.11 p<0.001.

Usage:
    uv run python experiments/k1371/k1371.py
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

np.random.seed(42)
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent / "k1371_results.json"

# ── Parameters ─────────────────────────────────────────────────────────────
TICKERS = {
    "tsmc": "2330.TW",
    "fubon": "2881.TW",
    "cathay": "2882.TW",
}
START = "2015-01-01"
END = "2025-12-31"
OOS_START = "2022-01-01"
ANNUALIZE = 252
HAR_D = 1
HAR_W = 5
HAR_M = 22
NW_LAGS = 22
REFIT_MONTHS = 1  # expand window, refit monthly


# ── Data ───────────────────────────────────────────────────────────────────
def fetch_data() -> pd.DataFrame:
    """Download daily adjusted close prices and compute log returns."""
    print("[K1371] Fetching data from yfinance...")
    dfs = {}
    for name, ticker in TICKERS.items():
        raw = yf.download(ticker, start=START, end=END,
                          auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError(f"No data for {ticker}")
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        log_ret = np.log(close / close.shift(1)).dropna()
        rv = log_ret ** 2 * ANNUALIZE
        dfs[name] = rv
        print(f"  {ticker}: {len(rv)} days ({rv.index[0].date()} - {rv.index[-1].date()})")
    df = pd.DataFrame(dfs).dropna()
    print(f"[K1371] Aligned panel: {len(df)} days")
    return df


# ── Feature builder ────────────────────────────────────────────────────────
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build HAR features (daily/weekly/monthly lags) for TSMC + exog."""
    rv_t = df["tsmc"]
    rv_f = df["fubon"]
    rv_c = df["cathay"]

    feats = pd.DataFrame(index=df.index)
    # TSMC HAR lags (all shifted to avoid lookahead)
    feats["rv_d"] = rv_t.shift(HAR_D)          # lag 1
    feats["rv_w"] = rv_t.shift(HAR_D).rolling(HAR_W).mean()    # lag 5 average
    feats["rv_m"] = rv_t.shift(HAR_D).rolling(HAR_M).mean()    # lag 22 average
    # Fubon exogenous
    feats["fubon_d"] = rv_f.shift(HAR_D)
    feats["fubon_w"] = rv_f.shift(HAR_D).rolling(HAR_W).mean()
    feats["fubon_m"] = rv_f.shift(HAR_D).rolling(HAR_M).mean()
    # Cathay exogenous
    feats["cathay_d"] = rv_c.shift(HAR_D)

    feats["y"] = rv_t  # target: current TSMC RV

    return feats.dropna()


# ── Model specs ────────────────────────────────────────────────────────────
MODEL_SPECS = {
    "M0_HAR": ["rv_d", "rv_w", "rv_m"],
    "M1_HAR_X_d": ["rv_d", "rv_w", "rv_m", "fubon_d"],
    "M2_HAR_X_wm": ["rv_d", "rv_w", "rv_m", "fubon_w", "fubon_m"],
    "M3_HAR_X_full": ["rv_d", "rv_w", "rv_m", "fubon_d", "fubon_w", "fubon_m"],
    "M4_HAR_X_cat": ["rv_d", "rv_w", "rv_m", "cathay_d"],
    "M5_HAR_X_fin": ["rv_d", "rv_w", "rv_m", "fubon_d", "cathay_d"],
}


# ── OOS forecast engine ────────────────────────────────────────────────────
def oos_forecast(feats: pd.DataFrame, model_cols: list[str]) -> pd.Series:
    """Expanding-window OOS forecast, refit monthly."""
    oos_mask = feats.index >= pd.Timestamp(OOS_START)
    is_data = feats[~oos_mask]
    oos_data = feats[oos_mask]

    preds = {}
    current_train = is_data.copy()
    last_refit_month = None

    for i, (ts, row) in enumerate(oos_data.iterrows()):
        month_key = (ts.year, ts.month)
        if last_refit_month != month_key:
            X_tr = add_constant(current_train[model_cols].values)
            y_tr = current_train["y"].values
            model = OLS(y_tr, X_tr).fit()
            last_refit_month = month_key

        X_row = np.concatenate([[1.0], row[model_cols].values])
        pred = float(model.predict(X_row.reshape(1, -1))[0])
        pred = max(pred, 1e-8)  # floor to avoid log(0) in QLIKE
        preds[ts] = pred

        # expand training set
        current_train = pd.concat([current_train, oos_data.iloc[[i]]])

    return pd.Series(preds)


# ── Loss functions ──────────────────────────────────────────────────────────
def qlike(actual: np.ndarray, predicted: np.ndarray) -> float:
    """QLIKE = mean(-log(sigma2) + RV/sigma2) — Patton (2011)."""
    return float(np.mean(-np.log(predicted) + actual / predicted))


def mse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean((actual - predicted) ** 2))


# ── DM test ────────────────────────────────────────────────────────────────
def dm_test(actual: np.ndarray, pred1: np.ndarray, pred2: np.ndarray,
            loss_fn=qlike) -> dict:
    """Harvey-Leybourne-Newbold (1997) DM test: H0 equal predictive accuracy.

    loss_diff_t = L(e1_t) - L(e2_t)
    If DM stat > 0 => model 1 worse than model 2.
    Two-sided p-value.
    """
    d = np.array([loss_fn(np.array([a]), np.array([p1])) -
                  loss_fn(np.array([a]), np.array([p2]))
                  for a, p1, p2 in zip(actual, pred1, pred2)])
    n = len(d)
    d_bar = d.mean()
    # Newey-West variance of d_bar
    _m = OLS(d, np.ones((n, 1))).fit(cov_type="HAC",
                                      cov_kwds={"maxlags": NW_LAGS})
    var_d_bar = float(_m.bse[0] ** 2)
    dm_stat = d_bar / np.sqrt(var_d_bar) if var_d_bar > 1e-15 else 0.0
    p_val = 2 * stats.norm.sf(abs(dm_stat))
    return {"dm_stat": float(dm_stat), "p_value": float(p_val),
            "d_bar": float(d_bar), "n": n}


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    df = fetch_data()
    feats = build_features(df)

    oos_mask = feats.index >= pd.Timestamp(OOS_START)
    oos_actual = feats.loc[oos_mask, "y"].values
    n_oos = len(oos_actual)
    print(f"\n[K1371] OOS period: {OOS_START} to {END}  N={n_oos}")
    print(f"[K1371] IS period : {feats.index[0].date()} to {pd.Timestamp(OOS_START).date()}  N={(~oos_mask).sum()}")

    # Generate OOS forecasts for all models
    all_preds: dict[str, np.ndarray] = {}
    for model_name, cols in MODEL_SPECS.items():
        print(f"[K1371] Forecasting {model_name}...")
        pred_series = oos_forecast(feats, cols)
        all_preds[model_name] = pred_series.values

    # Compute losses
    losses: dict[str, dict] = {}
    for model_name, preds in all_preds.items():
        losses[model_name] = {
            "qlike": qlike(oos_actual, preds),
            "mse": mse(oos_actual, preds),
            "n_oos": n_oos,
        }

    # DM tests vs M0_HAR benchmark
    dm_results: dict[str, dict] = {}
    baseline_preds = all_preds["M0_HAR"]
    for model_name in ["M1_HAR_X_d", "M2_HAR_X_wm", "M3_HAR_X_full",
                       "M4_HAR_X_cat", "M5_HAR_X_fin"]:
        dm_results[model_name] = dm_test(oos_actual, baseline_preds,
                                         all_preds[model_name])

    # Fubon vs Cathay comparison (DM between M1 and M4)
    fubon_vs_cathay_dm = dm_test(oos_actual, all_preds["M1_HAR_X_d"],
                                  all_preds["M4_HAR_X_cat"])

    # Hypothesis evaluation
    base_qlike = losses["M0_HAR"]["qlike"]
    # DM convention: d_t = loss(baseline) - loss(model_x), DM > 0 => model_x better
    h1_pass = (losses["M1_HAR_X_d"]["qlike"] < base_qlike and
               dm_results["M1_HAR_X_d"]["p_value"] < 0.05 and
               dm_results["M1_HAR_X_d"]["dm_stat"] > 0)
    h2_pass = any(
        losses[m]["qlike"] < base_qlike
        and dm_results[m]["p_value"] < 0.05
        and dm_results[m]["dm_stat"] > 0
        for m in dm_results
    )
    h3_pass = losses["M1_HAR_X_d"]["qlike"] < losses["M4_HAR_X_cat"]["qlike"]
    best_x_model = min(dm_results, key=lambda m: losses[m]["qlike"])
    h4_pass = (losses[best_x_model]["qlike"] < base_qlike and
               dm_results[best_x_model]["dm_stat"] > 2.0)  # directional Harvey threshold

    hypotheses = {
        "H1_HAR_X_d_improves_QLIKE": h1_pass,
        "H2_any_HAR_X_improves_QLIKE": h2_pass,
        "H3_fubon_better_than_cathay": h3_pass,
        "H4_harvey_t_gt2_for_best": h4_pass,
    }
    n_pass = sum(hypotheses.values())

    if n_pass >= 2:
        verdict = "PASS"
    elif n_pass == 1:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "FAIL"

    print(f"\n[K1371] Results:")
    print(f"  HAR QLIKE:          {base_qlike:.6f}")
    for m, l in losses.items():
        if m != "M0_HAR":
            imp = (base_qlike - l['qlike']) / base_qlike * 100
            dm = dm_results[m]
            print(f"  {m:20s}: QLIKE={l['qlike']:.6f} ({imp:+.2f}%) DM-t={dm['dm_stat']:.3f} p={dm['p_value']:.4f}")
    print(f"\n  Hypotheses: {n_pass}/4 pass")
    for h, r in hypotheses.items():
        print(f"  {'✓' if r else '✗'} {h}")
    print(f"\n  VERDICT: {verdict}")

    # Save results
    results = {
        "experiment_id": "K1371",
        "title": "HAR-RV-X: Financial Sector Lead as TSMC Volatility Predictor",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "tickers": TICKERS,
            "period": f"{START} to {END}",
            "oos_period": f"{OOS_START} to {END}",
            "har_lags": {"daily": HAR_D, "weekly": HAR_W, "monthly": HAR_M},
            "rv_proxy": "squared_log_returns_annualized",
            "estimation": "OLS_NW_HAC",
            "nw_lags": NW_LAGS,
            "refit_frequency": "monthly",
            "seed": 42,
        },
        "oos_n": n_oos,
        "losses": losses,
        "dm_tests_vs_M0_HAR": dm_results,
        "fubon_vs_cathay_dm": fubon_vs_cathay_dm,
        "hypotheses": hypotheses,
        "n_hypotheses_passed": n_pass,
        "verdict": verdict,
        "key_finding": (
            f"HAR base QLIKE={base_qlike:.6f}. "
            f"Best extension {best_x_model}: QLIKE={losses[best_x_model]['qlike']:.6f} "
            f"({(base_qlike-losses[best_x_model]['qlike'])/base_qlike*100:+.2f}%), "
            f"DM t={dm_results[best_x_model]['dm_stat']:.3f} p={dm_results[best_x_model]['p_value']:.4f}."
        ),
        "motivating_prior": "K757: Fubon->TSMC Granger F=6.11 p<0.001 (2010-2026)",
        "data_source": "yfinance daily adjusted close (2330.TW, 2881.TW, 2882.TW)",
    }

    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n[K1371] Results saved to {OUT}")


if __name__ == "__main__":
    main()
