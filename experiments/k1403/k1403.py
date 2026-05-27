"""K1403 — HAR-RV Quantile Forecasting Cross-Asset Robustness (QQQ / GLD / TLT)

Cross-asset replication of K1402 SPY result (DM NULL on quantile-median QLIKE).
Same pipeline (HAR-RV + Koenker-Bassett 1978 QuantReg, τ ∈ {0.50, 0.75, 0.90,
0.95, 0.99}) applied to QQQ / GLD / TLT. Aggregate verdict classifies whether
K1402 NULL is SPY-specific, universal, or method only viable for tail VaR.

Output: experiments/k1403/k1403_results.json
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
ASSETS = ["QQQ", "GLD", "TLT"]
DATA_START = "2007-01-03"
OOS_START = "2021-01-04"
QUANTILES = [0.50, 0.75, 0.90, 0.95, 0.99]
SEED = 42

ROOT = Path(__file__).parent
RESULTS_PATH = ROOT / "k1403_results.json"
CACHE_DIR = ROOT / "data"

np.random.seed(SEED)


# ============================================================
# Data
# ============================================================
def load_asset(asset: str) -> pd.Series:
    """Load asset adj close, prefer local cache → yfinance."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{asset}.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        s = df.iloc[:, 0].astype(float)
        s.index = pd.to_datetime(s.index)
        if s.index.tz is not None:
            s.index = s.index.tz_localize(None)
        return s.sort_index()
    import yfinance as yf
    df = yf.download(asset, start=DATA_START, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {asset}")
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s.name = asset
    s.to_frame().to_csv(cache)
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s.astype(float).sort_index()


def build_har_panel(px: pd.Series) -> pd.DataFrame:
    ret_pct = (np.log(px) - np.log(px.shift(1))) * 100.0
    daily_rv = ret_pct.abs()
    rv_d = daily_rv.shift(1)
    rv_w = daily_rv.rolling(5).mean().shift(1)
    rv_m = daily_rv.rolling(22).mean().shift(1)
    df = pd.DataFrame({
        "daily_rv": daily_rv,
        "rv_d": rv_d,
        "rv_w": rv_w,
        "rv_m": rv_m,
    }).dropna()
    return df


# ============================================================
# Loss & tests (porting from K1402)
# ============================================================
def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, tau: float) -> float:
    diff = y_true - y_pred
    return float(np.mean(np.maximum(tau * diff, (tau - 1.0) * diff)))


def kupiec_uc(violations: int, n: int, p_nominal: float) -> dict:
    p_hat = violations / n if n > 0 else 0.0
    if p_hat <= 0 or p_hat >= 1:
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


def dm_test(loss_1: np.ndarray, loss_2: np.ndarray, h: int = 1) -> dict:
    d = loss_1 - loss_2
    n = len(d)
    if n < 5:
        return {"dm_stat": float("nan"), "p_value": float("nan"), "n": int(n)}
    d_mean = float(np.mean(d))
    gamma0 = float(np.var(d, ddof=0))
    var_d = gamma0
    for lag in range(1, h):
        gl = float(np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean)))
        var_d += 2.0 * gl
    var_d = max(var_d, 1e-12)
    dm = d_mean / math.sqrt(var_d / n)
    k = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * k
    p_value = 2.0 * (1.0 - stats.t.cdf(abs(dm_hln), df=n - 1))
    return {
        "dm_stat": float(dm_hln),
        "p_value": float(p_value),
        "n": int(n),
        "mean_diff": d_mean,
    }


def qlike(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    sigma2_pred = np.maximum(y_pred ** 2, 1e-12)
    sigma2_true = y_true ** 2
    return np.log(sigma2_pred) + sigma2_true / sigma2_pred


# ============================================================
# Per-asset run
# ============================================================
def run_asset(asset: str) -> dict:
    px = load_asset(asset)
    panel = build_har_panel(px)
    oos_start = pd.Timestamp(OOS_START)
    train_mask = panel.index < oos_start
    oos_mask = panel.index >= oos_start
    if oos_mask.sum() < 50:
        raise RuntimeError(
            f"{asset}: insufficient OOS samples ({int(oos_mask.sum())})"
        )

    X_train = sm.add_constant(panel.loc[train_mask, ["rv_d", "rv_w", "rv_m"]])
    y_train = panel.loc[train_mask, "daily_rv"].values
    X_oos = sm.add_constant(panel.loc[oos_mask, ["rv_d", "rv_w", "rv_m"]])
    y_oos = panel.loc[oos_mask, "daily_rv"].values
    oos_index = panel.loc[oos_mask].index

    ols = sm.OLS(y_train, X_train).fit()
    yhat_ols = np.asarray(ols.predict(X_oos))

    quantile_results: dict[str, dict] = {}
    yhat_q: dict[float, np.ndarray] = {}
    for tau in QUANTILES:
        qr = QuantReg(y_train, X_train).fit(q=tau, max_iter=5000)
        yhat_tau = np.asarray(qr.predict(X_oos))
        yhat_q[tau] = yhat_tau

        loss_tau = pinball_loss(y_oos, yhat_tau, tau)
        emp_cov = float(np.mean(y_oos <= yhat_tau))
        violations = int(np.sum(y_oos > yhat_tau))
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

    qlike_ols = qlike(y_oos, yhat_ols)
    qlike_qmed = qlike(y_oos, yhat_q[0.50])
    dm = dm_test(qlike_ols, qlike_qmed, h=1)

    ols_pinball_at_50 = pinball_loss(y_oos, yhat_ols, 0.50)
    qmed_pinball_at_50 = pinball_loss(y_oos, yhat_q[0.50], 0.50)

    verdict = classify_verdict(quantile_results, dm)
    dm_status = classify_dm_status(dm)
    tail_status = classify_tail_status(quantile_results)

    return {
        "asset": asset,
        "n_train": int(train_mask.sum()),
        "n_oos": int(oos_mask.sum()),
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
        "dm_status": dm_status,
        "tail_status": tail_status,
    }


def classify_dm_status(dm: dict) -> str:
    """Explicit DM dimension: SIG_POS / SIG_NEG / NS."""
    dm_p = dm["p_value"]
    dm_stat = dm["dm_stat"]
    if dm_p < 0.10 and dm_stat > 0:
        return "SIG_POS"
    if dm_p < 0.10 and dm_stat < 0:
        return "SIG_NEG"
    return "NS"


def classify_tail_status(qres: dict) -> str:
    """Explicit tail dimension: TIGHT (≤±2pp + Kupiec PASS) / ACCEPTABLE
    (≤±5pp + Kupiec PASS) / FAIL (otherwise)."""
    q95 = qres["q95"]
    q99 = qres["q99"]
    gap_95 = abs(q95["coverage_gap_pp"])
    gap_99 = abs(q99["coverage_gap_pp"])
    kupiec_95_pass = q95["kupiec_uc"]["p_value"] > 0.05
    kupiec_99_pass = q99["kupiec_uc"]["p_value"] > 0.05
    if not (kupiec_95_pass and kupiec_99_pass):
        return "FAIL"
    if gap_95 <= 2.0 and gap_99 <= 2.0:
        return "TIGHT"
    if gap_95 <= 5.0 and gap_99 <= 5.0:
        return "ACCEPTABLE"
    return "FAIL"


def classify_verdict(qres: dict, dm: dict) -> dict:
    """Per-asset classification, identical criteria to K1402."""
    reasons: list[str] = []
    q95 = qres["q95"]
    q99 = qres["q99"]
    gap_95 = abs(q95["coverage_gap_pp"])
    gap_99 = abs(q99["coverage_gap_pp"])
    kupiec_95_pass = q95["kupiec_uc"]["p_value"] > 0.05
    kupiec_99_pass = q99["kupiec_uc"]["p_value"] > 0.05
    dm_p = dm["p_value"]
    dm_stat = dm["dm_stat"]
    dm_sig_neg = dm_p < 0.10 and dm_stat < 0
    dm_sig_pos = dm_p < 0.10 and dm_stat > 0
    dm_ns = dm_p >= 0.10
    cov_tight = gap_95 <= 2.0 and gap_99 <= 2.0
    cov_acceptable = gap_95 <= 5.0 and gap_99 <= 5.0

    if dm_sig_neg:
        reasons.append(
            f"DM significantly NEGATIVE (qmed worse than OLS, stat={dm_stat:.2f} "
            f"p={dm_p:.3f})"
        )
        # 仍要回報 tail coverage 狀態以便 aggregate 用
        if cov_acceptable and kupiec_95_pass and kupiec_99_pass:
            reasons.append(
                f"Tail coverage acceptable (gap95={gap_95:.2f}pp gap99={gap_99:.2f}pp) "
                f"+ Kupiec PASS → tail upper bound usable despite NULL on DM"
            )
        return {"label": "NULL", "reasons": reasons}

    if cov_tight and kupiec_95_pass and kupiec_99_pass and dm_sig_pos:
        reasons.append("Coverage ±2pp, Kupiec UC PASS both tails, DM qmed>ols p<0.10")
        return {"label": "PASS", "reasons": reasons}
    if cov_acceptable and kupiec_95_pass and kupiec_99_pass and dm_ns:
        reasons.append(
            f"Coverage gap 95={gap_95:.2f}pp 99={gap_99:.2f}pp, Kupiec PASS, "
            f"DM NS (p={dm_p:.3f})"
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


def aggregate_verdict(per_asset: list[dict]) -> dict:
    """Cross-asset aggregate classification — uses explicit dm_status /
    tail_status fields (not the conflated per-asset verdict label).

    Definitions:
      - dm_sig_pos = dm_status == "SIG_POS"  (quantile median 顯著超 OLS)
      - dm_sig_neg = dm_status == "SIG_NEG"  (quantile median 顯著差 OLS)
      - tail_usable = tail_status in {"TIGHT", "ACCEPTABLE"}

    Aggregate labels (互斥 + 完整覆蓋)：
      - METHOD_RECOVERY  : ≥2/3 dm_sig_pos (K1402 SPY NULL is asset-specific)
      - TAIL_CALIB_USABLE: 0 dm_sig_pos AND ≥2/3 dm_sig_neg AND ≥2/3 tail_usable
                          (method 整體無法超 OLS 點預測，但 tail band 可用)
      - UNIVERSAL_NULL   : ≥2/3 dm_sig_neg AND ≤1 tail_usable
                          (method 完全無 usable application)
      - MIXED            : 其餘（含 dm 全 NS、partial recovery 等）
    """
    n_dm_sig_pos = sum(1 for r in per_asset if r["dm_status"] == "SIG_POS")
    n_dm_sig_neg = sum(1 for r in per_asset if r["dm_status"] == "SIG_NEG")
    n_dm_ns = sum(1 for r in per_asset if r["dm_status"] == "NS")
    n_tail_usable = sum(
        1 for r in per_asset if r["tail_status"] in ("TIGHT", "ACCEPTABLE")
    )
    n = len(per_asset)

    if n_dm_sig_pos >= 2:
        label = "METHOD_RECOVERY"
        reason = (
            f"{n_dm_sig_pos}/{n} dm_sig_pos (qmed 顯著超 OLS) — "
            "K1402 SPY DM NULL is asset-specific, method recovers cross-asset"
        )
    elif n_dm_sig_neg >= 2 and n_tail_usable >= 2 and n_dm_sig_pos == 0:
        label = "TAIL_CALIB_USABLE"
        reason = (
            f"{n_dm_sig_neg}/{n} dm_sig_neg AND {n_tail_usable}/{n} tail usable — "
            "method 無法超 OLS 但 tail VaR upper bound 可用"
        )
    elif n_dm_sig_neg >= 2 and n_tail_usable <= 1:
        label = "UNIVERSAL_NULL"
        reason = (
            f"{n_dm_sig_neg}/{n} dm_sig_neg AND only {n_tail_usable}/{n} tail "
            "usable — method has no usable application"
        )
    else:
        label = "MIXED"
        reason = (
            f"dm: {n_dm_sig_pos} pos / {n_dm_sig_neg} neg / {n_dm_ns} NS; "
            f"tail usable {n_tail_usable}/{n} — no clean aggregate verdict"
        )
    return {
        "label": label,
        "reason": reason,
        "n_dm_sig_pos": n_dm_sig_pos,
        "n_dm_sig_neg": n_dm_sig_neg,
        "n_dm_ns": n_dm_ns,
        "n_tail_usable": n_tail_usable,
    }


def main() -> dict:
    per_asset = [run_asset(a) for a in ASSETS]
    agg = aggregate_verdict(per_asset)

    out = {
        "experiment_id": "K1403",
        "title": "HAR-RV Quantile Forecasting Cross-Asset Robustness (QQQ/GLD/TLT)",
        "assets": ASSETS,
        "oos_start": OOS_START,
        "per_asset": per_asset,
        "aggregate_verdict": agg,
        "config": {
            "seed": SEED,
            "data_start": DATA_START,
            "oos_start": OOS_START,
            "quantiles": QUANTILES,
            "model": "HAR-RV + statsmodels.QuantReg (Koenker-Bassett 1978)",
            "refit": "none (single fixed-origin fit)",
        },
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({
        "experiment_id": out["experiment_id"],
        "aggregate_label": agg["label"],
        "per_asset_verdicts": {r["asset"]: r["verdict"] for r in per_asset},
        "tail_usable_count": agg["n_tail_usable"],
    }, indent=2))
    return out


if __name__ == "__main__":
    main()
