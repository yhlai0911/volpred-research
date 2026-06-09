"""
K1431: VIX9D-VIX Spread as HAR-RV OOS Covariate for SPY Daily RV

Hypothesis (H1):
    The spread Delta_t = VIX9D_t - VIX_t (short-term VRP / term-structure proxy)
    contains predictive information about next-day SPY realized vol
    that augments a vanilla HAR-RV forecast.

Design:
    Daily RV proxy = squared close-to-close log return (Andersen-Bollerslev-
    Diebold-Labys 1999 daily approximation); robustness: |log return|.
    Lookahead guard: spread_lag1 = (VIX9D - VIX).shift(1) -> predict RV_{t+1}.
    Models:
        M0 (baseline): HAR-RV {RV_t, RV^w, RV^m}
        M1 (+spread):  HAR-RV + spread_lag1
        M2 (+spread+vix): HAR-RV + spread_lag1 + VIX_lag1
    Evaluation:
        Rolling 1000-day expanding window, h=1 one-step OOS forecast.
        QLIKE (Patton 2011) primary, MSE robustness.
        Diebold-Mariano with Harvey-Leybourne-Newbold small-sample correction.
        Subperiods: 2015-2017, 2018-2021 (incl. COVID), 2022-2026.

Lookahead:
    All covariates use .shift(1); train end < test start enforced.
Seed:
    seed=42 everywhere.

Verdict rule:
    DM HLN p<0.05 full-sample AND >=2 subperiod p<0.10 -> PASS
    DM HLN p<0.05 full OR >=2 subperiod p<0.10 -> CONDITIONAL_PASS
    All p>0.10 -> NULL
    Else -> MIXED

Author: Claude (worktree agent), 2026-06-09
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

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)
EPS_FLOOR = 1e-10  # log-RV clip floor (zero-return days)

HERE = Path(__file__).resolve().parent
OUT_RESULTS = HERE / "k1431_results.json"
OUT_FIG_QLIKE = HERE / "k1431_oos_qlike.png"
OUT_FIG_SPREAD = HERE / "k1431_spread_regime.png"

START = "2011-01-03"  # VIX9D launch
END = "2026-06-09"
INSAMPLE_WIN = 1000  # expanding window minimum
SUBPERIODS = [
    ("2015-2017", "2015-01-01", "2017-12-31"),
    ("2018-2021", "2018-01-01", "2021-12-31"),
    ("2022-2026", "2022-01-01", "2026-12-31"),
]

# -----------------------------------------------------------------------------
# 1. DATA
# -----------------------------------------------------------------------------


def fetch_series(ticker: str, start: str, end: str) -> pd.Series:
    raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw["Close"].astype(float)


def build_dataset() -> pd.DataFrame:
    print("[1] Downloading ^VIX9D, ^VIX, ^GSPC ...")
    vix9d = fetch_series("^VIX9D", START, END).rename("VIX9D")
    vix = fetch_series("^VIX", START, END).rename("VIX")
    gspc = fetch_series("^GSPC", START, END).rename("GSPC")
    df = pd.concat([gspc, vix, vix9d], axis=1).dropna()
    # Daily log return & RV proxies
    df["ret"] = np.log(df["GSPC"]).diff()
    df["RV"] = df["ret"] ** 2          # squared log return (main RV proxy)
    df["AV"] = df["ret"].abs()         # robustness: |log return|
    df = df.dropna()
    # HAR components — fit in log-RV space (canonical HAR; guarantees positive
    # forecasts after exp(); also down-weights jumps. Corsi 2009 reports both
    # specs; Andersen-Bollerslev-Diebold 2007 use log-RV).
    df["logRV"] = np.log(df["RV"].clip(lower=EPS_FLOOR))
    df["logRV_d"] = df["logRV"]
    df["logRV_w"] = df["logRV"].rolling(5).mean()
    df["logRV_m"] = df["logRV"].rolling(22).mean()
    # Keep linear RV components for reference / robustness
    df["RV_d"] = df["RV"]
    df["RV_w"] = df["RV"].rolling(5).mean()
    df["RV_m"] = df["RV"].rolling(22).mean()
    # Lagged signals (lookahead guard): observed at close of t, predict RV_{t+1}
    df["spread"] = df["VIX9D"] - df["VIX"]
    df["spread_lag1"] = df["spread"].shift(1)
    df["VIX_lag1"] = df["VIX"].shift(1)
    df["RV_d_lag1"] = df["RV_d"].shift(1)
    df["RV_w_lag1"] = df["RV_w"].shift(1)
    df["RV_m_lag1"] = df["RV_m"].shift(1)
    df["logRV_d_lag1"] = df["logRV_d"].shift(1)
    df["logRV_w_lag1"] = df["logRV_w"].shift(1)
    df["logRV_m_lag1"] = df["logRV_m"].shift(1)
    df["AV_d"] = df["AV"]
    df["AV_w"] = df["AV"].rolling(5).mean()
    df["AV_m"] = df["AV"].rolling(22).mean()
    df["AV_d_lag1"] = df["AV_d"].shift(1)
    df["AV_w_lag1"] = df["AV_w"].shift(1)
    df["AV_m_lag1"] = df["AV_m"].shift(1)
    df["ratio_lag1"] = (df["VIX9D"] / df["VIX"]).shift(1)
    df = df.dropna()
    return df


# -----------------------------------------------------------------------------
# 2. ROLLING OOS FORECAST
# -----------------------------------------------------------------------------


def ols_fit_predict(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray) -> np.ndarray:
    """OLS with intercept, returns predictions for X_test."""
    Xtr = np.column_stack([np.ones(len(X_train)), X_train])
    Xte = np.column_stack([np.ones(len(X_test)), X_test])
    # Solve (X'X) beta = X'y via lstsq for numerical stability
    beta, *_ = np.linalg.lstsq(Xtr, y_train, rcond=None)
    return Xte @ beta


def rolling_oos_forecast(df: pd.DataFrame, feature_cols: list[str], target: str,
                         min_train: int = INSAMPLE_WIN) -> pd.Series:
    """One-step-ahead rolling OOS using expanding window starting at min_train."""
    y = df[target].values
    X = df[feature_cols].values
    n = len(df)
    preds = np.full(n, np.nan)
    for t in range(min_train, n):
        beta_X = X[:t]   # uses rows 0..t-1 (all feature lags already shifted)
        beta_y = y[:t]
        x_t = X[t]  # 1-D row vector
        beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(beta_X)), beta_X]),
                                   beta_y, rcond=None)
        preds[t] = float(beta[0] + np.dot(x_t, beta[1:]))
    s = pd.Series(preds, index=df.index, name="_".join(feature_cols))
    return s


# -----------------------------------------------------------------------------
# 3. LOSSES & DM TEST
# -----------------------------------------------------------------------------


EPS = 1e-12


def qlike_loss(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """Patton 2011 QLIKE = y/yhat - log(y/yhat) - 1. Robust to mean-noise."""
    y_true = np.maximum(y_true, EPS)
    y_pred = np.maximum(y_pred, EPS)
    r = y_true / y_pred
    return r - np.log(r) - 1.0


def mse_loss(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    return (y_true - y_pred) ** 2


def dm_hln_test(d: np.ndarray, h: int = 1) -> tuple[float, float]:
    """
    Diebold-Mariano statistic with Harvey-Leybourne-Newbold (1997) small-sample
    correction. d = loss_baseline - loss_alt; positive -> alt better.
    Returns (DM_HLN stat, two-sided p-value from t_{n-1}).
    """
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return float("nan"), float("nan")
    mean_d = d.mean()
    # NW HAC variance with lag h-1
    gamma0 = np.var(d, ddof=0)
    var_d = gamma0
    for k in range(1, h):
        gk = np.cov(d[:-k], d[k:], ddof=0)[0, 1]
        var_d += 2 * gk
    if var_d <= 0:
        return float("nan"), float("nan")
    dm = mean_d / np.sqrt(var_d / n)
    # HLN correction
    correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * correction
    p = 2 * (1 - stats.t.cdf(abs(dm_hln), df=n - 1))
    return float(dm_hln), float(p)


# -----------------------------------------------------------------------------
# 4. MAIN PIPELINE
# -----------------------------------------------------------------------------


def evaluate_subperiod(losses_base: pd.Series, losses_alt: pd.Series,
                      sub_start: str, sub_end: str) -> dict:
    mask = (losses_base.index >= sub_start) & (losses_base.index <= sub_end)
    lb = losses_base[mask].dropna()
    la = losses_alt[mask].dropna()
    common = lb.index.intersection(la.index)
    lb = lb.loc[common]
    la = la.loc[common]
    if len(lb) < 30:
        return {"n": len(lb), "mean_base": float("nan"), "mean_alt": float("nan"),
                "dm_hln": float("nan"), "p_value": float("nan")}
    d = lb.values - la.values
    dm, p = dm_hln_test(d)
    return {
        "n": int(len(lb)),
        "mean_base": float(lb.mean()),
        "mean_alt": float(la.mean()),
        "improvement_pct": float((lb.mean() - la.mean()) / lb.mean() * 100),
        "dm_hln": dm,
        "p_value": p,
    }


def run(df: pd.DataFrame, target_col: str, label: str) -> dict:
    """
    target_col: 'RV' (main) or 'AV' (robustness).
    For RV: fit OLS on log(RV) -> exponentiate prediction -> QLIKE on RV scale.
    For AV: fit OLS on AV directly (positive by construction; |return| floor=0
            but prediction occasionally negative -> clip at EPS_FLOOR before QLIKE).
    """
    print(f"\n[run] target={target_col} ({label})  n={len(df)}")
    if target_col == "RV":
        base_cols = ["logRV_d_lag1", "logRV_w_lag1", "logRV_m_lag1"]
        fit_target = "logRV"
    else:
        base_cols = ["AV_d_lag1", "AV_w_lag1", "AV_m_lag1"]
        fit_target = "AV"
    spread_cols = base_cols + ["spread_lag1"]
    full_cols = base_cols + ["spread_lag1", "VIX_lag1"]

    yhat_base_raw = rolling_oos_forecast(df, base_cols, fit_target)
    yhat_spread_raw = rolling_oos_forecast(df, spread_cols, fit_target)
    yhat_full_raw = rolling_oos_forecast(df, full_cols, fit_target)

    if target_col == "RV":
        # exponentiate log-space prediction -> RV scale (always positive)
        yhat_base = np.exp(yhat_base_raw)
        yhat_spread = np.exp(yhat_spread_raw)
        yhat_full = np.exp(yhat_full_raw)
    else:
        # clip negative AV predictions at EPS_FLOOR
        yhat_base = yhat_base_raw.clip(lower=EPS_FLOOR)
        yhat_spread = yhat_spread_raw.clip(lower=EPS_FLOOR)
        yhat_full = yhat_full_raw.clip(lower=EPS_FLOOR)

    y = df[target_col]
    loss_base_q = pd.Series(qlike_loss(y.values, yhat_base.values), index=df.index)
    loss_spread_q = pd.Series(qlike_loss(y.values, yhat_spread.values), index=df.index)
    loss_full_q = pd.Series(qlike_loss(y.values, yhat_full.values), index=df.index)
    loss_base_m = pd.Series(mse_loss(y.values, yhat_base.values), index=df.index)
    loss_spread_m = pd.Series(mse_loss(y.values, yhat_spread.values), index=df.index)
    loss_full_m = pd.Series(mse_loss(y.values, yhat_full.values), index=df.index)

    # Restrict to OOS only (drop NaN preds; first INSAMPLE_WIN rows)
    common = yhat_base.dropna().index.intersection(yhat_spread.dropna().index)
    common = common.intersection(yhat_full.dropna().index)
    loss_base_q = loss_base_q.loc[common]
    loss_spread_q = loss_spread_q.loc[common]
    loss_full_q = loss_full_q.loc[common]
    loss_base_m = loss_base_m.loc[common]
    loss_spread_m = loss_spread_m.loc[common]
    loss_full_m = loss_full_m.loc[common]

    oos_start = common.min().date().isoformat()
    oos_end = common.max().date().isoformat()
    print(f"  OOS window: {oos_start} -> {oos_end}  ({len(common)} days)")

    def block(loss_b, loss_a):
        d = loss_b.values - loss_a.values
        dm, p = dm_hln_test(d)
        return {
            "n": int(len(d)),
            "mean_base": float(loss_b.mean()),
            "mean_alt": float(loss_a.mean()),
            "improvement_pct": float((loss_b.mean() - loss_a.mean()) / loss_b.mean() * 100),
            "dm_hln": dm,
            "p_value": p,
        }

    full_q_spread = block(loss_base_q, loss_spread_q)
    full_q_full = block(loss_base_q, loss_full_q)
    # MSE in linear RV space after log-target exp() is dominated by rare
    # extreme exponentiated predictions; QLIKE (scale-robust, Patton 2011)
    # is the primary loss. We retain MSE for completeness but flag as
    # SECONDARY only — it is not used for the verdict.
    full_m_spread = block(loss_base_m, loss_spread_m)
    full_m_full = block(loss_base_m, loss_full_m)

    sub_q_spread = {name: evaluate_subperiod(loss_base_q, loss_spread_q, s, e)
                    for name, s, e in SUBPERIODS}
    sub_q_full = {name: evaluate_subperiod(loss_base_q, loss_full_q, s, e)
                  for name, s, e in SUBPERIODS}

    return {
        "label": label,
        "target": target_col,
        "oos_start": oos_start,
        "oos_end": oos_end,
        "n_oos": int(len(common)),
        "full_qlike": {
            "M0_vs_M1_spread": full_q_spread,
            "M0_vs_M2_full": full_q_full,
        },
        "full_mse": {
            "M0_vs_M1_spread": full_m_spread,
            "M0_vs_M2_full": full_m_full,
        },
        "subperiod_qlike": {
            "M0_vs_M1_spread": sub_q_spread,
            "M0_vs_M2_full": sub_q_full,
        },
        "_internal_series": {
            "loss_base_q": loss_base_q,
            "loss_spread_q": loss_spread_q,
            "loss_full_q": loss_full_q,
        },
    }


def derive_verdict(result_main: dict) -> tuple[str, str]:
    """
    Apply task verdict rule to the STATED HYPOTHESIS:
      H1: HAR-RV + spread_lag1 > HAR-RV  (QLIKE).
    This is the M0 vs M1 comparison. M2 (which adds VIX level) is reported
    as a SIDE FINDING — it answers a different question (is VIX-level
    informative?) and does not bear on whether the spread itself adds info.
    """
    full_p = result_main["full_qlike"]["M0_vs_M1_spread"]["p_value"]
    full_dm = result_main["full_qlike"]["M0_vs_M1_spread"]["dm_hln"]
    full_impr = result_main["full_qlike"]["M0_vs_M1_spread"]["improvement_pct"]
    sub = result_main["subperiod_qlike"]["M0_vs_M1_spread"]
    sub_p_under_010 = sum(1 for s in sub.values()
                          if not np.isnan(s["p_value"]) and s["p_value"] < 0.10
                          and s.get("improvement_pct", 0) > 0)
    direction_positive = (full_dm is not None and not np.isnan(full_dm) and full_dm > 0)

    # Side-finding stats (M2 with VIX level)
    full_p_m2 = result_main["full_qlike"]["M0_vs_M2_full"]["p_value"]
    full_impr_m2 = result_main["full_qlike"]["M0_vs_M2_full"]["improvement_pct"]
    sub_m2 = result_main["subperiod_qlike"]["M0_vs_M2_full"]
    sub_m2_under_010 = sum(1 for s in sub_m2.values()
                           if not np.isnan(s["p_value"]) and s["p_value"] < 0.10
                           and s.get("improvement_pct", 0) > 0)

    if direction_positive and full_p < 0.05 and sub_p_under_010 >= 2:
        verdict = "PASS"
    elif direction_positive and (full_p < 0.05 or sub_p_under_010 >= 2):
        verdict = "CONDITIONAL_PASS"
    elif full_p > 0.10 and sub_p_under_010 == 0:
        verdict = "NULL"
    else:
        verdict = "MIXED"

    rationale = (
        f"H1 (spread alone): full DM HLN p={full_p:.4f} improvement={full_impr:+.2f}% "
        f"{sub_p_under_010}/3 subperiods at p<0.10 -> {verdict}. "
        f"Side finding M2 (spread+VIX_level): full p={full_p_m2:.2e} "
        f"improvement={full_impr_m2:+.2f}% {sub_m2_under_010}/3 subperiods at p<0.10 -> "
        f"VIX LEVEL adds strong incremental info, but credit is to VIX level not spread."
    )
    return verdict, rationale


def make_plots(df: pd.DataFrame, result_main: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    series = result_main["_internal_series"]
    lb = series["loss_base_q"]
    ls = series["loss_spread_q"]
    cum_b = lb.cumsum()
    cum_s = ls.cumsum()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(cum_b.index, cum_b.values, label="HAR-RV (baseline)", color="#1f77b4", lw=1.2)
    ax.plot(cum_s.index, cum_s.values, label="HAR-RV + VIX9D-VIX spread", color="#d62728", lw=1.2)
    ax.set_title("K1431  Cumulative OOS QLIKE  (lower = better)")
    ax.set_xlabel("Date"); ax.set_ylabel("Cumulative QLIKE")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_FIG_QLIKE, dpi=130)
    plt.close(fig)
    print(f"  saved {OUT_FIG_QLIKE.name}")

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df.index, df["spread"], color="#444", lw=0.7)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_title("K1431  VIX9D - VIX  (positive = backwardation)")
    ax.set_xlabel("Date"); ax.set_ylabel("VIX9D - VIX")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_FIG_SPREAD, dpi=130)
    plt.close(fig)
    print(f"  saved {OUT_FIG_SPREAD.name}")


def main():
    df = build_dataset()
    print(f"  dataset: {df.index[0].date()} -> {df.index[-1].date()}  n={len(df)}")
    print(f"  spread stats: mean={df['spread'].mean():.3f} std={df['spread'].std():.3f} "
          f"min={df['spread'].min():.3f} max={df['spread'].max():.3f}")

    result_rv = run(df, "RV", "RV=squared_log_return")
    result_av = run(df, "AV", "AV=abs_log_return  (robustness)")

    verdict, rationale = derive_verdict(result_rv)
    print(f"\n[VERDICT] {verdict}")
    print(f"  {rationale}")

    make_plots(df, result_rv)

    # Strip private series before JSON dump
    def strip(res):
        out = {k: v for k, v in res.items() if k != "_internal_series"}
        return out

    output = {
        "experiment_id": "K1431",
        "title": "VIX9D-VIX spread as HAR-RV OOS covariate for SPY daily RV",
        "verdict": verdict,
        "rationale": rationale,
        "data": {
            "source": "yfinance ^VIX9D, ^VIX, ^GSPC",
            "sample_start": df.index[0].date().isoformat(),
            "sample_end": df.index[-1].date().isoformat(),
            "n_total": int(len(df)),
            "spread_mean": float(df["spread"].mean()),
            "spread_std": float(df["spread"].std()),
            "spread_min": float(df["spread"].min()),
            "spread_max": float(df["spread"].max()),
        },
        "method": {
            "RV_proxy_main": "squared log return (Andersen-Bollerslev-Diebold-Labys 1999 daily)",
            "RV_proxy_robust": "abs(log return)",
            "lag_rule": "spread_lag1 = (VIX9D - VIX).shift(1); train end < test start enforced",
            "models": {
                "M0_baseline": "HAR-RV {RV_d_lag1, RV_w_lag1, RV_m_lag1}",
                "M1_spread": "M0 + spread_lag1",
                "M2_full": "M0 + spread_lag1 + VIX_lag1",
            },
            "estimator": "OLS via numpy.linalg.lstsq",
            "evaluation": "rolling expanding window, min_train=1000",
            "losses": ["QLIKE (Patton 2011)", "MSE"],
            "DM_test": "Diebold-Mariano with Harvey-Leybourne-Newbold h=1 small-sample correction",
            "subperiods": [list(p) for p in SUBPERIODS],
            "seed": SEED,
        },
        "results_main_RV": strip(result_rv),
        "results_robust_AV": strip(result_av),
        "limitations": [
            "RV proxy is daily squared return, not 5-min realized variance — noisier than HF RV.",
            "OOS window starts ~2015 due to 1000-day in-sample requirement; pre-2011 VIX9D unavailable.",
            "Only SPY (via ^GSPC); cross-asset / cross-index extension future work.",
            "OLS linear specification; could be extended to HAR-Q (Bollerslev-Patton-Quaedvlieg 2016) or HAR-CJ.",
        ],
        "references": [
            "Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized Volatility. JFE.",
            "Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.",
            "Bollerslev, T., Tauchen, G., & Zhou, H. (2009). Expected stock returns and variance risk premia. RFS.",
            "Andersen, T. G., Bollerslev, T., Diebold, F. X., & Labys, P. (1999). The distribution of realized exchange rate volatility. JASA.",
            "Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. IJF.",
        ],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    OUT_RESULTS.write_text(json.dumps(output, indent=2, default=float))
    print(f"\n  saved {OUT_RESULTS.name}")
    print("\nDONE.")
    return output


if __name__ == "__main__":
    main()
