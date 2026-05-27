"""K1402 — HAR-RV Quantile Forecasting (Pinball Loss)

Research question
-----------------
HAR-RV (Corsi 2009) 是 RV point forecast 標竿之一。將 OLS (MSE) 換成
quantile regression (Koenker & Bassett 1978，pinball loss) 訓練 conditional
quantiles 後：
  1. 條件分位數能否準確刻劃 SPY 22d RV 條件分佈（特別右尾）？
  2. τ=0.95/0.99 提供的信賴上界是否通過 Kupiec UC 檢定（可作 VaR-equivalent
     upper bound 餵 Risk Forecast 頁）？

Data:    SPY adj-close 2007-01-03 至 today（yfinance；cache 與 K1312 共用）
Target:  daily_rv_t  = |ret_pct_t|（單日 realized vol proxy，one-step-ahead）
Feat:    HAR-RV — rv_d = daily_rv[t-1], rv_w = mean(daily_rv[t-5:t-1]),
         rv_m = mean(daily_rv[t-22:t-1])；signal at t-1, target at t
OOS:     2021-01-04 起 (與 K1263 / K1312 對齊)

Output:  experiments/k1402/k1402_results.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from statsmodels.regression.quantile_regression import QuantReg

# ============================================================
# Config
# ============================================================
ASSET = "SPY"
DATA_START = "2007-01-03"
OOS_START = "2021-01-04"
QUANTILES = [0.50, 0.75, 0.90, 0.95, 0.99]
SEED = 42

ROOT = Path(__file__).parent
RESULTS_PATH = ROOT / "k1402_results.json"
LOCAL_DATA_CACHE = ROOT / "data" / "SPY.csv"
SHARED_CACHE = ROOT.parent / "k1312" / "data" / "SPY.csv"

np.random.seed(SEED)


# ============================================================
# Data
# ============================================================
def load_spy() -> pd.Series:
    """Load SPY adj close, preferring K1312 shared cache → local cache → yfinance."""
    for cache in (SHARED_CACHE, LOCAL_DATA_CACHE):
        if cache.exists():
            df = pd.read_csv(cache, index_col=0, parse_dates=True)
            s = df.iloc[:, 0].astype(float)
            s.index = pd.to_datetime(s.index)
            if s.index.tz is not None:
                s.index = s.index.tz_localize(None)
            return s.sort_index()
    # fallback to yfinance
    import yfinance as yf
    df = yf.download(ASSET, start=DATA_START, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError("yfinance returned empty for SPY")
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s.name = ASSET
    LOCAL_DATA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_csv(LOCAL_DATA_CACHE)
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s.astype(float).sort_index()


def build_har_panel(px: pd.Series) -> pd.DataFrame:
    """Build standard HAR-RV (Corsi 2009) panel.

    Daily realized vol proxy: |daily log return %|. Features 用 1/5/22 日
    rolling mean of daily RV，全部 .shift(1) 確保 signal at t-1, target at t。
    """
    ret_pct = (np.log(px) - np.log(px.shift(1))) * 100.0  # daily log return %
    daily_rv = ret_pct.abs()  # one-day realized vol proxy
    rv_d = daily_rv.shift(1)                    # lag-1 daily RV
    rv_w = daily_rv.rolling(5).mean().shift(1)  # lagged 5-day mean
    rv_m = daily_rv.rolling(22).mean().shift(1) # lagged 22-day mean
    df = pd.DataFrame({
        "daily_rv": daily_rv,   # target
        "rv_d": rv_d,
        "rv_w": rv_w,
        "rv_m": rv_m,
    }).dropna()
    return df


# ============================================================
# Pinball loss
# ============================================================
def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, tau: float) -> float:
    diff = y_true - y_pred
    return float(np.mean(np.maximum(tau * diff, (tau - 1.0) * diff)))


# ============================================================
# Kupiec UC test (unconditional coverage)
# ============================================================
def kupiec_uc(violations: int, n: int, p_nominal: float) -> dict:
    """Likelihood ratio test for proportion of failures (POF).

    H0: violation rate == p_nominal
    """
    p_hat = violations / n if n > 0 else 0.0
    if p_hat <= 0 or p_hat >= 1:
        # avoid log(0); use small epsilon
        eps = 1e-12
        p_hat_safe = min(max(p_hat, eps), 1 - eps)
    else:
        p_hat_safe = p_hat
    ll_null = (
        violations * math.log(p_nominal)
        + (n - violations) * math.log(1.0 - p_nominal)
    )
    ll_alt = (
        violations * math.log(p_hat_safe)
        + (n - violations) * math.log(1.0 - p_hat_safe)
    )
    lr = -2.0 * (ll_null - ll_alt)
    p_value = 1.0 - stats.chi2.cdf(lr, df=1)
    return {
        "violations": int(violations),
        "n": int(n),
        "p_hat": float(p_hat),
        "p_nominal": float(p_nominal),
        "lr_stat": float(lr),
        "p_value": float(p_value),
    }


# ============================================================
# DM test (Diebold–Mariano, HLN small-sample adjusted)
# ============================================================
def dm_test(loss_1: np.ndarray, loss_2: np.ndarray, h: int = 1) -> dict:
    """DM test of equal forecast accuracy. H0: E[loss_1 - loss_2] = 0.

    Positive stat => loss_1 > loss_2 (model 2 better).
    Returns Harvey–Leybourne–Newbold (HLN) small-sample-adjusted t-stat.
    """
    d = loss_1 - loss_2
    n = len(d)
    if n < 5:
        return {"dm_stat": float("nan"), "p_value": float("nan"), "n": int(n)}
    d_mean = float(np.mean(d))
    # Newey-West-style HAC with lag = h - 1
    gamma0 = float(np.var(d, ddof=0))
    var_d = gamma0
    for lag in range(1, h):
        gl = float(np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean)))
        var_d += 2.0 * gl
    var_d = max(var_d, 1e-12)
    dm = d_mean / math.sqrt(var_d / n)
    # HLN adjustment
    k = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * k
    p_value = 2.0 * (1.0 - stats.t.cdf(abs(dm_hln), df=n - 1))
    return {
        "dm_stat": float(dm_hln),
        "p_value": float(p_value),
        "n": int(n),
        "mean_diff": d_mean,
    }


# ============================================================
# QLIKE loss
# ============================================================
def qlike(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """QLIKE per-obs loss: log(σ̂²) + y²/σ̂². y_true is realized sigma (rv22),
    y_pred is predicted sigma. Convert to variance internally."""
    sigma2_pred = np.maximum(y_pred ** 2, 1e-12)
    sigma2_true = y_true ** 2
    return np.log(sigma2_pred) + sigma2_true / sigma2_pred


# ============================================================
# Main
# ============================================================
def main() -> dict:
    px = load_spy()
    panel = build_har_panel(px)
    oos_start = pd.Timestamp(OOS_START)
    train_mask = panel.index < oos_start
    oos_mask = panel.index >= oos_start
    if oos_mask.sum() < 50:
        raise RuntimeError(
            f"Insufficient OOS samples ({int(oos_mask.sum())}) — check OOS_START / data range"
        )

    X_train = sm.add_constant(panel.loc[train_mask, ["rv_d", "rv_w", "rv_m"]])
    y_train = panel.loc[train_mask, "daily_rv"].values
    X_oos = sm.add_constant(panel.loc[oos_mask, ["rv_d", "rv_w", "rv_m"]])
    y_oos = panel.loc[oos_mask, "daily_rv"].values
    oos_index = panel.loc[oos_mask].index

    # ---- Baseline OLS ----
    ols = sm.OLS(y_train, X_train).fit()
    yhat_ols = np.asarray(ols.predict(X_oos))

    # ---- Quantile regression for each τ ----
    quantile_results: dict[str, dict] = {}
    yhat_q: dict[float, np.ndarray] = {}
    for tau in QUANTILES:
        qr = QuantReg(y_train, X_train).fit(q=tau, max_iter=5000)
        yhat_tau = np.asarray(qr.predict(X_oos))
        yhat_q[tau] = yhat_tau

        loss_tau = pinball_loss(y_oos, yhat_tau, tau)
        emp_cov = float(np.mean(y_oos <= yhat_tau))
        violations = int(np.sum(y_oos > yhat_tau))
        # Kupiec UC: nominal violation rate = 1 - τ
        kupiec = kupiec_uc(
            violations=violations, n=len(y_oos), p_nominal=1.0 - tau,
        )
        quantile_results[f"q{int(tau * 100):02d}"] = {
            "tau": tau,
            "params": {k: float(v) for k, v in qr.params.to_dict().items()},
            "pinball_loss_oos": loss_tau,
            "empirical_coverage": emp_cov,
            "nominal_coverage": tau,
            "coverage_gap_pp": float((emp_cov - tau) * 100.0),
            "kupiec_uc": kupiec,
        }

    # ---- OLS QLIKE vs quantile-median (τ=0.5) QLIKE: DM test ----
    qlike_ols = qlike(y_oos, yhat_ols)
    qlike_qmed = qlike(y_oos, yhat_q[0.50])
    dm = dm_test(qlike_ols, qlike_qmed, h=1)

    # ---- Summary ----
    ols_pinball_at_50 = pinball_loss(y_oos, yhat_ols, 0.50)
    qmed_pinball_at_50 = pinball_loss(y_oos, yhat_q[0.50], 0.50)

    verdict = classify_verdict(quantile_results, dm)

    out = {
        "experiment_id": "K1402",
        "title": "HAR-RV Quantile Forecasting (Pinball Loss) — SPY",
        "asset": ASSET,
        "n_train": int(train_mask.sum()),
        "n_oos": int(oos_mask.sum()),
        "oos_start": OOS_START,
        "oos_first_date": str(oos_index.min().date()),
        "oos_last_date": str(oos_index.max().date()),
        "ols_baseline": {
            "qlike_mean_oos": float(np.mean(qlike_ols)),
            "pinball_at_tau_0.50": ols_pinball_at_50,
        },
        "quantile_median_vs_ols": {
            "qlike_mean_oos_qmed": float(np.mean(qlike_qmed)),
            "pinball_at_tau_0.50": qmed_pinball_at_50,
            "dm_qmed_vs_ols": dm,
        },
        "quantile_forecasts": quantile_results,
        "verdict": verdict["label"],
        "verdict_reasons": verdict["reasons"],
        "config": {
            "seed": SEED,
            "data_start": DATA_START,
            "oos_start": OOS_START,
            "quantiles": QUANTILES,
            "model": "HAR-RV + statsmodels.QuantReg (Koenker-Bassett 1978)",
            "refit": "none (single expanding fit through OOS_START)",
        },
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({
        "experiment_id": out["experiment_id"],
        "verdict": out["verdict"],
        "n_oos": out["n_oos"],
        "tail_coverage_95": quantile_results["q95"]["empirical_coverage"],
        "tail_coverage_99": quantile_results["q99"]["empirical_coverage"],
        "kupiec_95_p": quantile_results["q95"]["kupiec_uc"]["p_value"],
        "kupiec_99_p": quantile_results["q99"]["kupiec_uc"]["p_value"],
        "dm_qmed_vs_ols_p": dm["p_value"],
    }, indent=2))
    return out


def classify_verdict(qres: dict, dm: dict) -> dict:
    """Classify PASS / CONDITIONAL_PASS / NULL per README success criteria.

    Logic:
      - DM significantly negative (qmed loss > ols loss, p<0.10) → NULL
        即使 coverage 與 Kupiec 漂亮，quantile median 顯著 worse than OLS
        代表整體 forecast quality 退步，不該掛 conditional pass
      - PASS: coverage ±2pp 內 + Kupiec UC PASS both tails + DM 顯著 qmed>ols
      - CONDITIONAL_PASS: coverage ±5pp 內 + Kupiec UC PASS both tails + DM NS (p≥0.10)
      - NULL: 其他
    """
    reasons: list[str] = []
    q95 = qres["q95"]
    q99 = qres["q99"]
    gap_95 = abs(q95["coverage_gap_pp"])
    gap_99 = abs(q99["coverage_gap_pp"])
    kupiec_95_pass = q95["kupiec_uc"]["p_value"] > 0.05
    kupiec_99_pass = q99["kupiec_uc"]["p_value"] > 0.05
    dm_p = dm["p_value"]
    dm_stat = dm["dm_stat"]
    dm_sig_neg = dm_p < 0.10 and dm_stat < 0  # qmed loss > ols loss 顯著
    dm_sig_pos = dm_p < 0.10 and dm_stat > 0  # qmed loss < ols loss 顯著
    dm_ns = dm_p >= 0.10
    cov_tight = gap_95 <= 2.0 and gap_99 <= 2.0
    cov_acceptable = gap_95 <= 5.0 and gap_99 <= 5.0

    # Hard fail: DM 顯著為負（quantile median forecast 顯著差於 OLS）
    if dm_sig_neg:
        reasons.append(
            f"DM significantly NEGATIVE (qmed worse than OLS, stat={dm_stat:.2f} p={dm_p:.3f}) "
            f"— quantile median forecast 顯著退步，整體 QLIKE quality 下降"
        )
        return {"label": "NULL", "reasons": reasons}

    if cov_tight and kupiec_95_pass and kupiec_99_pass and dm_sig_pos:
        reasons.append("Coverage ±2pp, Kupiec UC PASS both tails, DM qmed>ols p<0.10")
        return {"label": "PASS", "reasons": reasons}
    if cov_acceptable and kupiec_95_pass and kupiec_99_pass and dm_ns:
        reasons.append(
            f"Coverage gap 95={gap_95:.2f}pp 99={gap_99:.2f}pp, Kupiec PASS, "
            f"DM NS (p={dm_p:.3f}) — tail calibration usable, median 不顯著超 OLS"
        )
        return {"label": "CONDITIONAL_PASS", "reasons": reasons}
    if not cov_acceptable:
        reasons.append(
            f"Tail coverage gap > ±5pp (95={gap_95:.2f}, 99={gap_99:.2f})"
        )
    if not (kupiec_95_pass and kupiec_99_pass):
        reasons.append(
            f"Kupiec UC reject (95 p={q95['kupiec_uc']['p_value']:.3f}, "
            f"99 p={q99['kupiec_uc']['p_value']:.3f})"
        )
    return {"label": "NULL", "reasons": reasons}


if __name__ == "__main__":
    main()
