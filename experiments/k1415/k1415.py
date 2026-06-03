"""K1415 — VIX9D/VIX 短端期限結構作為 HAR-RV 基線之邊際 RV 預測因子

研究問題: 在 HAR-RV(daily/weekly/monthly) baseline 上加入 log(VIX9D/VIX) 短端
期限結構比率，是否帶來統計上顯著、樣本外可重複的邊際 RV 預測增量？

H1: log(VIX9D/VIX) 攜帶 imminent vol 衝擊 expectation；HAR-RV captures realized
    persistence，二者互補 -> β_tr > 0, DM p<0.05, QLIKE improvement ≥0.5%
H0: 增益微小或不顯著

Lookahead 防護: 所有 features 在 t 都用 t-1 (及之前) 資訊；signal.shift(1) 等效。
Seed: 42 (no stochastic estimation, OLS 為 closed-form; seed 保留以利 reproducibility)
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).parent
START = "2014-01-01"
END = "2026-05-30"
OOS_START = "2020-01-02"


def fetch_data() -> pd.DataFrame:
    """Download SPY + VIX + VIX9D, inner join on trading dates."""
    tickers = {"SPY": "SPY", "VIX": "^VIX", "VIX9D": "^VIX9D"}
    frames = {}
    for name, sym in tickers.items():
        df = yf.download(sym, start=START, end=END, progress=False, auto_adjust=False)
        # yfinance now returns MultiIndex columns for single ticker; flatten
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        frames[name] = df[[col]].rename(columns={col: name})
    merged = pd.concat(frames.values(), axis=1, join="inner").dropna()
    merged.index.name = "Date"
    return merged


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build RV proxy + HAR features + term-structure ratio.

    LOOKAHEAD PROTECTION: target RV_t uses return(t-1 -> t); all features use
    info up to t-1 (i.e., shift(1) applied where needed).
    """
    out = pd.DataFrame(index=df.index)
    # daily log return
    out["r"] = np.log(df["SPY"]).diff()
    # RV proxy: r^2 annualized × 252 (daily RV proxy)
    out["RV"] = (out["r"] ** 2) * 252.0
    # floor to avoid log(0) — tiny epsilon
    out["RV"] = out["RV"].clip(lower=1e-10)

    # HAR features at t: built from RV_{t-1}, mean RV_{t-5..t-1}, mean RV_{t-22..t-1}
    out["RV_lag1"] = out["RV"].shift(1)
    out["RV_w"] = out["RV"].shift(1).rolling(5).mean()
    out["RV_m"] = out["RV"].shift(1).rolling(22).mean()

    # Term ratio: log(VIX9D/VIX) at t-1
    out["TR"] = np.log(df["VIX9D"] / df["VIX"]).shift(1)

    # log-transform RV for stability (standard HAR practice)
    out["logRV"] = np.log(out["RV"])
    out["logRV_lag1"] = np.log(out["RV_lag1"])
    out["logRV_w"] = np.log(out["RV_w"])
    out["logRV_m"] = np.log(out["RV_m"])

    return out


def qlike(true_var: np.ndarray, pred_var: np.ndarray) -> np.ndarray:
    """QLIKE loss per obs.  L = true/pred - log(true/pred) - 1."""
    ratio = true_var / pred_var
    return ratio - np.log(ratio) - 1.0


def dm_test(loss_a: np.ndarray, loss_b: np.ndarray, hac_lag: int = 22) -> tuple[float, float]:
    """Diebold-Mariano test on loss differences with HAC Newey-West SE.

    H0: E[loss_a - loss_b] = 0 (equal predictive accuracy)
    Returns (DM stat, two-sided p-value).  Positive stat -> A worse than B.
    """
    d = loss_a - loss_b
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 30:
        return float("nan"), float("nan")
    # HAC SE via statsmodels
    mod = sm.OLS(d, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lag})
    stat = float(mod.tvalues[0])
    pval = float(mod.pvalues[0])
    return stat, pval


def fit_model(feat: pd.DataFrame, cols: list[str]) -> sm.regression.linear_model.RegressionResultsWrapper:
    """Fit OLS log(RV_t) ~ const + cols on supplied frame, HAC SE lag=22."""
    sub = feat.dropna(subset=["logRV"] + cols)
    y = sub["logRV"].values
    X = sm.add_constant(sub[cols].values)
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 22})


def expanding_oos_forecast(feat: pd.DataFrame, cols: list[str], oos_start: str) -> pd.DataFrame:
    """Expanding-window OOS forecasts, refit annually (year-end refit -> predict next year).

    Lookahead-safe: at refit date r, use ALL feat rows with Date <= r; predictions for
    Date > r through next year-end use that frozen model on already-lagged features.
    """
    full = feat.dropna(subset=["logRV"] + cols).copy()
    oos_mask = full.index >= pd.Timestamp(oos_start)
    oos_dates = full.index[oos_mask]

    preds: list[tuple[pd.Timestamp, float, float]] = []  # (date, logRV_pred, RV_pred)
    # Group OOS dates by year, refit at start of each year using data strictly before
    years = sorted(set(d.year for d in oos_dates))
    for yr in years:
        train = full[full.index < pd.Timestamp(f"{yr}-01-01")]
        if len(train) < 100:
            continue
        y_tr = train["logRV"].values
        X_tr = sm.add_constant(train[cols].values, has_constant="add")
        # OLS via numpy lstsq (closed-form, no randomness, no need for HAC here)
        beta, *_ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
        # in-sample residual variance for log->level back-transform (smearing correction)
        resid = y_tr - X_tr @ beta
        sigma2_resid = float(np.var(resid, ddof=len(beta)))

        # predict for this year's OOS dates
        test = full[(full.index >= pd.Timestamp(f"{yr}-01-01")) & (full.index < pd.Timestamp(f"{yr + 1}-01-01"))]
        if test.empty:
            continue
        X_te = sm.add_constant(test[cols].values, has_constant="add")
        log_pred = X_te @ beta
        # back-transform: E[exp(logRV)] = exp(mu + sigma^2/2) (lognormal smearing)
        rv_pred = np.exp(log_pred + 0.5 * sigma2_resid)
        for dt, lp, rp in zip(test.index, log_pred, rv_pred):
            preds.append((dt, float(lp), float(rp)))

    pred_df = pd.DataFrame(preds, columns=["Date", "logRV_pred", "RV_pred"]).set_index("Date")
    pred_df["RV_true"] = full.loc[pred_df.index, "RV"].values
    pred_df["logRV_true"] = full.loc[pred_df.index, "logRV"].values
    return pred_df


def main() -> dict:
    print(f"[K1415] start; seed={SEED}")
    df = fetch_data()
    print(f"  raw merged shape: {df.shape}; date range {df.index.min().date()} -> {df.index.max().date()}")

    feat = build_features(df)
    feat_full = feat.dropna(subset=["logRV", "logRV_lag1", "logRV_w", "logRV_m", "TR"])
    print(f"  feature panel shape: {feat_full.shape}")

    M0_COLS = ["logRV_lag1", "logRV_w", "logRV_m"]
    M1_COLS = M0_COLS + ["TR"]

    # ----- Full-sample fits for coefficient inference -----
    fit_M0 = fit_model(feat_full, M0_COLS)
    fit_M1 = fit_model(feat_full, M1_COLS)
    print(f"  full-sample R²: M0={fit_M0.rsquared:.4f}  M1={fit_M1.rsquared:.4f}")

    # ----- OOS expanding forecasts -----
    pred_M0 = expanding_oos_forecast(feat_full, M0_COLS, OOS_START)
    pred_M1 = expanding_oos_forecast(feat_full, M1_COLS, OOS_START)

    # align
    merged_pred = pred_M0[["RV_true", "RV_pred"]].rename(columns={"RV_pred": "RV_pred_M0"})
    merged_pred["RV_pred_M1"] = pred_M1["RV_pred"]
    merged_pred = merged_pred.dropna()
    n_oos = len(merged_pred)
    print(f"  OOS n={n_oos}, span {merged_pred.index.min().date()} -> {merged_pred.index.max().date()}")

    qlike_M0 = qlike(merged_pred["RV_true"].values, merged_pred["RV_pred_M0"].values)
    qlike_M1 = qlike(merged_pred["RV_true"].values, merged_pred["RV_pred_M1"].values)
    mean_q0 = float(np.nanmean(qlike_M0))
    mean_q1 = float(np.nanmean(qlike_M1))
    qlike_impr_pct = (mean_q0 - mean_q1) / mean_q0 * 100.0  # positive -> M1 better

    dm_stat, dm_p = dm_test(qlike_M1, qlike_M0, hac_lag=22)  # H0: E[q1 - q0] = 0
    # negative DM stat -> q1 < q0 -> M1 better
    print(f"  OOS QLIKE: M0={mean_q0:.5f}  M1={mean_q1:.5f}  Δ%={qlike_impr_pct:+.3f}%")
    print(f"  DM stat={dm_stat:.3f}  p={dm_p:.4f}")

    # ----- coefficient extraction -----
    coef_names_M1 = ["const"] + M1_COLS
    coef_M1 = {
        n: {
            "coef": float(fit_M1.params[i]),
            "stderr": float(fit_M1.bse[i]),
            "tstat": float(fit_M1.tvalues[i]),
            "pvalue": float(fit_M1.pvalues[i]),
        }
        for i, n in enumerate(coef_names_M1)
    }
    beta_tr = coef_M1["TR"]["coef"]
    beta_tr_p = coef_M1["TR"]["pvalue"]

    # ----- verdict -----
    if dm_p < 0.01 and qlike_impr_pct >= 1.0 and beta_tr > 0:
        verdict = "PASS"
    elif dm_p < 0.05 and qlike_impr_pct >= 0.5 and beta_tr > 0:
        verdict = "CONDITIONAL_PASS"
    elif qlike_impr_pct < -0.3:  # reverse direction
        verdict = "FAIL"
    elif dm_p >= 0.10 or abs(qlike_impr_pct) < 0.3:
        verdict = "NULL"
    else:
        verdict = "NULL"

    # ----- sub-sample sensitivity (post-COVID 2021+) -----
    sens = {}
    post = merged_pred[merged_pred.index >= "2021-01-01"]
    if len(post) > 100:
        q0_post = np.nanmean(qlike(post["RV_true"].values, post["RV_pred_M0"].values))
        q1_post = np.nanmean(qlike(post["RV_true"].values, post["RV_pred_M1"].values))
        dm_post = dm_test(
            qlike(post["RV_true"].values, post["RV_pred_M1"].values),
            qlike(post["RV_true"].values, post["RV_pred_M0"].values),
            hac_lag=22,
        )
        sens["post_2021"] = {
            "n": int(len(post)),
            "qlike_M0": float(q0_post),
            "qlike_M1": float(q1_post),
            "improvement_pct": float((q0_post - q1_post) / q0_post * 100.0),
            "dm_stat": float(dm_post[0]),
            "dm_pvalue": float(dm_post[1]),
        }
    # alternative HAC lag
    dm_alt = dm_test(qlike_M1, qlike_M0, hac_lag=10)
    sens["dm_hac_lag10"] = {"dm_stat": float(dm_alt[0]), "dm_pvalue": float(dm_alt[1])}

    # ----- plot rolling 60-day mean QLIKE -----
    plot_df = pd.DataFrame(
        {"M0": qlike_M0, "M1": qlike_M1}, index=merged_pred.index
    ).rolling(60).mean()
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(plot_df.index, plot_df["M0"], label="HAR-RV (M0)", lw=1.3, color="#444")
    ax.plot(plot_df.index, plot_df["M1"], label="HAR-RV + log(VIX9D/VIX) (M1)", lw=1.3, color="#c0392b")
    ax.set_title("K1415 — Rolling 60-day mean QLIKE: HAR-RV vs HAR-RV+TR (SPY OOS 2020-2026)")
    ax.set_xlabel("Date"); ax.set_ylabel("QLIKE (lower = better)")
    ax.legend(loc="upper right"); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "k1415_qlike_plot.png", dpi=140)
    plt.close(fig)

    results = {
        "experiment_id": "k1415",
        "seed": SEED,
        "lookahead_check": "signal.shift(1) confirmed: target RV_t uses return(t-1->t); HAR & TR features all built from data up to t-1",
        "sample": {
            "start": str(feat_full.index.min().date()),
            "end": str(feat_full.index.max().date()),
            "n_obs_total": int(len(feat_full)),
            "n_is": int((feat_full.index < pd.Timestamp(OOS_START)).sum()),
            "n_oos": int(n_oos),
            "oos_start": OOS_START,
        },
        "models": {
            "M0": {
                "spec": "log(RV_t) = a + b1 log(RV_lag1) + b2 log(RV_w) + b3 log(RV_m)",
                "r2_full_sample": float(fit_M0.rsquared),
                "r2_adj_full_sample": float(fit_M0.rsquared_adj),
                "oos_qlike": mean_q0,
            },
            "M1": {
                "spec": "M0 + b4 * log(VIX9D/VIX)",
                "r2_full_sample": float(fit_M1.rsquared),
                "r2_adj_full_sample": float(fit_M1.rsquared_adj),
                "oos_qlike": mean_q1,
            },
        },
        "test": {
            "dm_stat": float(dm_stat),
            "dm_pvalue": float(dm_p),
            "dm_h0": "E[QLIKE_M1 - QLIKE_M0] = 0; negative stat -> M1 better",
            "qlike_improvement_pct": float(qlike_impr_pct),
        },
        "coefficients": {"M1": coef_M1, "M0": {
            n: {
                "coef": float(fit_M0.params[i]),
                "stderr": float(fit_M0.bse[i]),
                "tstat": float(fit_M0.tvalues[i]),
                "pvalue": float(fit_M0.pvalues[i]),
            }
            for i, n in enumerate(["const"] + M0_COLS)
        }},
        "sensitivity": sens,
        "verdict": verdict,
        "limitations": [
            "RV proxy = daily squared log-return × 252; not 5-min realized variance (no intraday data)",
            "single asset (SPY); broad-index generalization untested",
            "12-year sample (2014-2026); pre-2014 VIX9D unavailable",
            "annual refit cadence vs daily/expanding refit — may understate adaptive gains",
        ],
        "interpretation": (
            f"M1 augmenting HAR-RV with log(VIX9D/VIX) yields ΔQLIKE={qlike_impr_pct:+.3f}% OOS, "
            f"DM p={dm_p:.4f}; β_tr={beta_tr:+.4f} (p={beta_tr_p:.4f}). Verdict={verdict}."
        ),
    }
    with open(OUT_DIR / "k1415_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"[K1415] verdict={verdict}; results.json written")
    return results


if __name__ == "__main__":
    main()
