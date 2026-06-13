#!/usr/bin/env python3
"""
K1490 — Crypto Vol-of-Vol Cross-Market Tail Spillover

Research Q: Does BTC/ETH vol-of-vol (VoV) predict tail-event risk in traditional
            markets (SPY/GLD/USO/TLT)? Is crypto a leading indicator of cross-
            market tail spillover, or a useful tail hedge predictor?

Differentiation vs prior K:
  - K168 (GARCH Vol-of-Vol): single-asset VoV within one market
  - K649 (VoV NULL for regime prediction): VIX/VVIX self-prediction, NULL result
  - K1490: CROSS-MARKET spillover where CRYPTO VoV is the predictor of
           traditional-market tail events. New angle (not done before).

Method:
  - Daily close data, 2018-01-01 -> 2025-12-31
  - log returns r_t = ln(P_t / P_{t-1})
  - sigma_t  = 20-day rolling std of r_t  (vol proxy)
  - VoV_t    = 20-day rolling std of sigma_t  (vol-of-vol)
  - Tail event indicator on target market: I(|r_target_t| > 2 * sigma_target_t)
  - Predictor: VoV of crypto at t-1 (.shift(1) to prevent lookahead)
  - Tests:
      (a) Granger causality: crypto VoV (lag 1) -> target tail indicator
      (b) Quantile regression: 5th percentile of target return on lagged crypto VoV
      (c) Pearson correlation matrix of VoV across all assets
  - Seed = 42 throughout
  - Bootstrap 95% CI on quantile reg coefficient (n=1000, seed=42)

Hard rules enforced:
  - Lookahead: every cross-asset predictor uses .shift(1) (lag 1 day)
  - Seed = 42 for all random procedures
  - Honest reporting: NULL results reported as-is; no overclaiming
  - Same sample / same frequency for fair comparison
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import statsmodels.api as sm
from statsmodels.tsa.stattools import grangercausalitytests
from statsmodels.regression.quantile_regression import QuantReg
from scipy import stats

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, "k1490_results.json")
OUT_PLOT_TS = os.path.join(HERE, "k1490_vov_timeseries.png")
OUT_PLOT_HEAT = os.path.join(HERE, "k1490_spillover_heatmap.png")

START = "2018-01-01"
END = "2025-12-31"
ROLL = 20  # window for sigma and VoV

CRYPTO = ["BTC-USD", "ETH-USD"]
TRAD = ["SPY", "GLD", "USO", "TLT"]
ALL_TICKERS = CRYPTO + TRAD


# ---------------------------------------------------------------------------
# 1. Fetch data
# ---------------------------------------------------------------------------
def fetch_prices(tickers, start, end):
    """Download daily close prices, align on common business-day index."""
    data = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    # multi-index columns: ('Close','BTC-USD'), etc.
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"].copy()
    else:
        close = data[["Close"]].copy()
        close.columns = tickers
    close = close.dropna(how="all")
    return close


# ---------------------------------------------------------------------------
# 2. Compute returns / sigma / VoV
# ---------------------------------------------------------------------------
def compute_vol_metrics(close: pd.DataFrame, roll: int = 20):
    """Return log_ret, sigma (rolling std), vov (rolling std of sigma)."""
    log_ret = np.log(close / close.shift(1))
    sigma = log_ret.rolling(roll).std()
    vov = sigma.rolling(roll).std()
    return log_ret, sigma, vov


# ---------------------------------------------------------------------------
# 3. Descriptive statistics
# ---------------------------------------------------------------------------
def describe(df: pd.DataFrame) -> dict:
    out = {}
    for col in df.columns:
        s = df[col].dropna()
        out[col] = {
            "n_obs": int(s.shape[0]),
            "mean": float(s.mean()),
            "std": float(s.std()),
            "min": float(s.min()),
            "max": float(s.max()),
            "median": float(s.median()),
            "skew": float(s.skew()),
            "kurtosis": float(s.kurtosis()),
        }
    return out


# ---------------------------------------------------------------------------
# 4. Granger causality (crypto VoV -> target tail indicator)
# ---------------------------------------------------------------------------
def granger_test(predictor: pd.Series, target_abs_ret: pd.Series, maxlag: int = 5) -> dict:
    """
    Run Granger causality of `predictor` (continuous, e.g. crypto VoV)
    causing `target_abs_ret` (continuous |return|, used as a tail-magnitude proxy).

    Note: original draft passed a binary 0/1 tail indicator here, which under
    statsmodels' internal lag-shift can produce all-constant sub-windows and
    raise "x values include a column with constant values". Continuous |r| is
    both more informative and numerically stable for the F-test.
    """
    df = pd.concat([target_abs_ret, predictor], axis=1).dropna()
    df.columns = ["y", "x"]
    if df.shape[0] < 60:
        return {"error": "insufficient_samples", "n": int(df.shape[0])}
    # Guard: skip degenerate columns
    if df["y"].std() < 1e-10 or df["x"].std() < 1e-10:
        return {"error": "constant_column", "n": int(df.shape[0])}
    try:
        res = grangercausalitytests(df[["y", "x"]], maxlag=maxlag, verbose=False)
    except Exception as exc:
        return {"error": f"granger_failed: {exc}", "n": int(df.shape[0])}
    p_per_lag = {}
    for lag, val in res.items():
        ftest = val[0].get("ssr_ftest")
        if ftest is None:
            continue
        p_per_lag[lag] = {
            "F": float(ftest[0]),
            "p_value": float(ftest[1]),
        }
    if not p_per_lag:
        return {"error": "no_ftest_returned", "n": int(df.shape[0])}
    best_lag = min(p_per_lag, key=lambda k: p_per_lag[k]["p_value"])
    return {
        "n": int(df.shape[0]),
        "per_lag": p_per_lag,
        "best_lag": int(best_lag),
        "best_p_value": float(p_per_lag[best_lag]["p_value"]),
    }


# ---------------------------------------------------------------------------
# 5. Quantile regression: 5th pct of target return on lagged crypto VoV
# ---------------------------------------------------------------------------
def quantile_reg(predictor_lag1: pd.Series, target_return: pd.Series, q: float = 0.05) -> dict:
    """
    QuantReg with intercept of target_return on lag-1 predictor.
    Bootstrap (seed=42, n=1000) for 95% CI on slope.
    """
    df = pd.concat([target_return, predictor_lag1], axis=1).dropna()
    df.columns = ["y", "x"]
    if df.shape[0] < 200:
        return {"error": "insufficient_samples", "n": int(df.shape[0])}
    X = sm.add_constant(df["x"].values)
    y = df["y"].values
    try:
        model = QuantReg(y, X).fit(q=q)
    except Exception as exc:
        return {"error": f"quantreg_failed: {exc}", "n": int(df.shape[0])}
    coef = float(model.params[1])
    intercept = float(model.params[0])
    p_value = float(model.pvalues[1])
    t_stat = float(model.tvalues[1])

    # Bootstrap CI on slope
    rng = np.random.default_rng(SEED)
    n = X.shape[0]
    boot_coefs = []
    n_boot = 1000
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        try:
            m = QuantReg(y[idx], X[idx]).fit(q=q)
            boot_coefs.append(m.params[1])
        except Exception:
            continue
    boot_coefs = np.array(boot_coefs)
    if boot_coefs.size < 100:
        ci_low = ci_high = float("nan")
    else:
        ci_low = float(np.quantile(boot_coefs, 0.025))
        ci_high = float(np.quantile(boot_coefs, 0.975))

    return {
        "n": int(df.shape[0]),
        "q": q,
        "intercept": intercept,
        "slope": coef,
        "t_stat": t_stat,
        "p_value_asymptotic": p_value,
        "bootstrap_ci95_low": ci_low,
        "bootstrap_ci95_high": ci_high,
        "n_bootstrap": int(boot_coefs.size),
    }


# ---------------------------------------------------------------------------
# 5b. Logistic regression: P(tail event | lagged crypto VoV)
# ---------------------------------------------------------------------------
def logit_tail(predictor_lag1: pd.Series, tail_indicator: pd.Series) -> dict:
    df = pd.concat([tail_indicator, predictor_lag1], axis=1).dropna()
    df.columns = ["y", "x"]
    if df.shape[0] < 200 or df["y"].sum() < 10:
        return {"error": "insufficient_events", "n": int(df.shape[0]),
                "n_events": int(df["y"].sum())}
    X = sm.add_constant(df["x"].values)
    y = df["y"].values
    try:
        model = sm.Logit(y, X).fit(disp=0, method="bfgs", maxiter=200)
    except Exception as exc:
        return {"error": f"logit_failed: {exc}", "n": int(df.shape[0])}
    return {
        "n": int(df.shape[0]),
        "n_events": int(df["y"].sum()),
        "event_rate": float(df["y"].mean()),
        "intercept": float(model.params[0]),
        "slope_logit": float(model.params[1]),
        "z_stat": float(model.tvalues[1]),
        "p_value": float(model.pvalues[1]),
        "pseudo_r2": float(model.prsquared),
    }


# ---------------------------------------------------------------------------
# 6. Cross-market VoV correlation matrix
# ---------------------------------------------------------------------------
def corr_matrix(vov: pd.DataFrame) -> dict:
    aligned = vov.dropna()
    if aligned.shape[0] < 60:
        return {"error": "insufficient_samples", "n": int(aligned.shape[0])}
    cm = aligned.corr(method="pearson")
    return {
        "n": int(aligned.shape[0]),
        "columns": list(cm.columns),
        "matrix": cm.round(4).to_dict(),
    }


# ---------------------------------------------------------------------------
# 7. Plots
# ---------------------------------------------------------------------------
def plot_vov_timeseries(vov: pd.DataFrame, path: str):
    fig, ax = plt.subplots(figsize=(11, 6))
    for col in vov.columns:
        ax.plot(vov.index, vov[col], label=col, lw=1.0, alpha=0.85)
    ax.set_title("K1490 — Vol-of-Vol (20d rolling std of 20d rolling vol)")
    ax.set_ylabel("VoV")
    ax.set_xlabel("Date")
    ax.legend(ncol=3, fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=140)
    plt.close(fig)


def plot_spillover_heatmap(p_matrix: pd.DataFrame, slope_matrix: pd.DataFrame, path: str):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    im0 = axes[0].imshow(p_matrix.values.astype(float), cmap="viridis_r", vmin=0, vmax=0.2)
    axes[0].set_xticks(range(len(p_matrix.columns)))
    axes[0].set_yticks(range(len(p_matrix.index)))
    axes[0].set_xticklabels(p_matrix.columns, rotation=30)
    axes[0].set_yticklabels(p_matrix.index)
    axes[0].set_title("Granger p-value (best lag, capped @ 0.2)")
    for i in range(p_matrix.shape[0]):
        for j in range(p_matrix.shape[1]):
            v = p_matrix.values[i, j]
            txt = "n/a" if (isinstance(v, float) and np.isnan(v)) else f"{v:.3f}"
            axes[0].text(j, i, txt, ha="center", va="center", color="white", fontsize=8)
    fig.colorbar(im0, ax=axes[0], fraction=0.046)

    im1 = axes[1].imshow(slope_matrix.values.astype(float), cmap="coolwarm")
    axes[1].set_xticks(range(len(slope_matrix.columns)))
    axes[1].set_yticks(range(len(slope_matrix.index)))
    axes[1].set_xticklabels(slope_matrix.columns, rotation=30)
    axes[1].set_yticklabels(slope_matrix.index)
    axes[1].set_title("QuantReg(q=0.05) slope: target_ret on lagged crypto VoV")
    for i in range(slope_matrix.shape[0]):
        for j in range(slope_matrix.shape[1]):
            v = slope_matrix.values[i, j]
            txt = "n/a" if (isinstance(v, float) and np.isnan(v)) else f"{v:.2f}"
            axes[1].text(j, i, txt, ha="center", va="center", color="black", fontsize=8)
    fig.colorbar(im1, ax=axes[1], fraction=0.046)

    fig.suptitle("K1490 — Crypto VoV (t-1) -> traditional-market tail dynamics")
    plt.tight_layout()
    plt.savefig(path, dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 8. Main
# ---------------------------------------------------------------------------
def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    print(f"[K1490] start UTC={started} seed={SEED}")

    close = fetch_prices(ALL_TICKERS, START, END)
    print(f"[K1490] price panel: {close.shape}, range {close.index.min().date()} -> {close.index.max().date()}")

    log_ret, sigma, vov = compute_vol_metrics(close, ROLL)

    # Tail indicator per target (binary): I(|r_t| > 2 * sigma_t-1)
    # sigma_t-1 used to avoid lookahead in the threshold itself.
    tail_indicator = pd.DataFrame(index=log_ret.index, columns=TRAD, dtype=float)
    for t in TRAD:
        sigma_lag = sigma[t].shift(1)
        tail_indicator[t] = (log_ret[t].abs() > 2.0 * sigma_lag).astype(float)
    tail_indicator = tail_indicator.dropna(how="all")

    results = {
        "experiment_id": "K1490",
        "title": "Crypto Vol-of-Vol Cross-Market Tail Spillover",
        "started_utc": started,
        "data_source": "yfinance daily close, 2018-01-01 to 2025-12-31",
        "seed": SEED,
        "roll_window": ROLL,
        "tickers": ALL_TICKERS,
        "crypto": CRYPTO,
        "traditional": TRAD,
        "price_panel_shape": list(close.shape),
        "price_panel_start": str(close.index.min().date()),
        "price_panel_end": str(close.index.max().date()),
        "lag_policy": "All cross-asset predictors lagged by .shift(1); tail indicator threshold uses sigma_{t-1}",
    }

    # Descriptives
    results["descriptive_returns"] = describe(log_ret)
    results["descriptive_sigma_20d"] = describe(sigma)
    results["descriptive_vov_20d"] = describe(vov)
    results["tail_event_freq_per_asset"] = {
        t: {
            "n": int(tail_indicator[t].dropna().shape[0]),
            "n_tail": int(tail_indicator[t].dropna().sum()),
            "freq": float(tail_indicator[t].dropna().mean()),
        }
        for t in TRAD
    }

    # Correlation matrix on VoV
    results["vov_corr_matrix"] = corr_matrix(vov)

    # Granger causality + quantile regression + logit: each (crypto -> target)
    granger_results = {}
    quant_results = {}
    logit_results = {}
    p_grid = pd.DataFrame(index=CRYPTO, columns=TRAD, dtype=float)
    slope_grid = pd.DataFrame(index=CRYPTO, columns=TRAD, dtype=float)
    logit_p_grid = pd.DataFrame(index=CRYPTO, columns=TRAD, dtype=float)

    abs_ret = log_ret.abs()

    for c in CRYPTO:
        predictor_lag1 = vov[c].shift(1)  # explicit lookahead control
        for t in TRAD:
            tail = tail_indicator[t]
            target_ret = log_ret[t]
            target_absret = abs_ret[t]

            # Granger on continuous |return| as tail-magnitude proxy
            gres = granger_test(predictor_lag1.dropna(), target_absret.dropna())
            granger_results[f"{c}__to__{t}"] = gres
            if "best_p_value" in gres:
                p_grid.loc[c, t] = gres["best_p_value"]

            qres = quantile_reg(predictor_lag1, target_ret, q=0.05)
            quant_results[f"{c}__to__{t}"] = qres
            if "slope" in qres:
                slope_grid.loc[c, t] = qres["slope"]

            lres = logit_tail(predictor_lag1, tail)
            logit_results[f"{c}__to__{t}"] = lres
            if "p_value" in lres:
                logit_p_grid.loc[c, t] = lres["p_value"]

    results["granger_lag1_to_5_on_abs_returns"] = granger_results
    results["quantile_reg_q05"] = quant_results
    results["logit_tail_event"] = logit_results
    results["granger_p_value_grid"] = p_grid.round(4).to_dict()
    results["quant_slope_grid"] = slope_grid.round(4).to_dict()
    results["logit_p_value_grid"] = logit_p_grid.round(4).to_dict()

    # Verdict heuristic — aggregate across 3 tests
    def _summarise(grid: pd.DataFrame, label: str) -> dict:
        arr = grid.values.astype(float).ravel()
        arr = arr[~np.isnan(arr)]
        if arr.size == 0:
            return {"label": label, "n_tests": 0}
        bonf = 0.05 / max(arr.size, 1)
        return {
            "label": label,
            "n_tests": int(arr.size),
            "min_p": float(arr.min()),
            "n_sig_p_lt_0_10": int((arr < 0.10).sum()),
            "n_sig_p_lt_0_05": int((arr < 0.05).sum()),
            "bonferroni_alpha": float(bonf),
            "n_sig_bonferroni": int((arr < bonf).sum()),
        }

    quant_p_grid = pd.DataFrame(index=CRYPTO, columns=TRAD, dtype=float)
    for c in CRYPTO:
        for t in TRAD:
            qv = quant_results.get(f"{c}__to__{t}", {})
            if "p_value_asymptotic" in qv:
                quant_p_grid.loc[c, t] = qv["p_value_asymptotic"]
    results["quant_p_value_grid"] = quant_p_grid.round(4).to_dict()

    granger_summary = _summarise(p_grid, "granger_on_abs_returns")
    quant_summary = _summarise(quant_p_grid, "quantile_q05_slope")
    logit_summary = _summarise(logit_p_grid, "logit_tail_event")

    # Total tests across the 3 families: Bonferroni at family level
    total_bonf = 0.05 / max(
        granger_summary.get("n_tests", 0)
        + quant_summary.get("n_tests", 0)
        + logit_summary.get("n_tests", 0),
        1,
    )
    n_bonf_global = (
        granger_summary.get("n_sig_bonferroni", 0)
        + quant_summary.get("n_sig_bonferroni", 0)
        + logit_summary.get("n_sig_bonferroni", 0)
    )

    if n_bonf_global > 0:
        verdict = "PARTIAL: at least one crypto -> target spillover survives Bonferroni; warrants follow-up CoVaR study (K1490b)."
    elif (
        granger_summary.get("n_sig_p_lt_0_05", 0)
        + quant_summary.get("n_sig_p_lt_0_05", 0)
        + logit_summary.get("n_sig_p_lt_0_05", 0)
    ) > 0:
        verdict = "WEAK-EVIDENCE: nominal p<0.05 in some pairs but none survive Bonferroni across the 3-test family."
    else:
        verdict = "NULL-LEAN: crypto VoV does not robustly predict traditional-market tails."

    results["verdict_summary"] = {
        "granger": granger_summary,
        "quantile_q05": quant_summary,
        "logit": logit_summary,
        "global_bonferroni_alpha": float(total_bonf),
        "n_sig_bonferroni_global": int(n_bonf_global),
        "interpretation": verdict,
    }

    # Plots
    vov_plot_cols = [c for c in CRYPTO + TRAD if c in vov.columns]
    plot_vov_timeseries(vov[vov_plot_cols], OUT_PLOT_TS)
    plot_spillover_heatmap(p_grid.fillna(np.nan), slope_grid.fillna(np.nan), OUT_PLOT_HEAT)

    ended = datetime.now(timezone.utc).isoformat()
    results["finished_utc"] = ended

    with open(OUT_JSON, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"[K1490] wrote {OUT_JSON}")
    print(f"[K1490] wrote {OUT_PLOT_TS}")
    print(f"[K1490] wrote {OUT_PLOT_HEAT}")
    print(f"[K1490] verdict: {results['verdict_summary']['interpretation']}")
    print(f"  Granger min_p={granger_summary.get('min_p', 'n/a')}, sig@0.05={granger_summary.get('n_sig_p_lt_0_05', 0)}")
    print(f"  QuantReg min_p={quant_summary.get('min_p', 'n/a')}, sig@0.05={quant_summary.get('n_sig_p_lt_0_05', 0)}")
    print(f"  Logit min_p={logit_summary.get('min_p', 'n/a')}, sig@0.05={logit_summary.get('n_sig_p_lt_0_05', 0)}")
    print(f"  Bonferroni alpha={total_bonf:.4f}, n_sig_global={n_bonf_global}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
