"""K1404 — HAR-RV Quantile Tail Forecasting on TW market (^TWII)

Cross-region replication of K1402 (SPY) / K1403 (QQQ/GLD/TLT) pipeline on
Taiwan equity index ^TWII. Tests whether the K1402 NULL / K1403
TAIL_CALIB_USABLE pattern (quantile-median QLIKE 顯著差於 OLS BUT tail
coverage ±2~5pp acceptable for VaR upper bound) extends to Asian market.

Method: HAR-RV (Corsi 2009) + Koenker-Bassett 1978 QuantReg at
τ ∈ {0.50, 0.75, 0.90, 0.95, 0.99}. Daily RV proxy = |daily log return %|.
Fixed-origin OOS (pre-OOS 一次 fit；OOS 期間不 refit) — aligned with K1402/K1403.

Output:
    experiments/K1404/K1404_results.json
    experiments/K1404/coverage_plot.png
    experiments/K1404/data/twii.csv (cache)
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
ASSET = "^TWII"
ASSET_SLUG = "twii"
DATA_START = "2007-01-03"
OOS_START = "2021-01-04"
QUANTILES = [0.50, 0.75, 0.90, 0.95, 0.99]
SEED = 42

ROOT = Path(__file__).parent
RESULTS_PATH = ROOT / "K1404_results.json"
CACHE_DIR = ROOT / "data"
FIG_PATH = ROOT / "coverage_plot.png"

np.random.seed(SEED)


# ============================================================
# Data
# ============================================================
def load_asset(asset: str, slug: str) -> pd.Series:
    """Load asset adj close, prefer local cache → yfinance."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{slug}.csv"
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
    s.name = slug
    s.to_frame().to_csv(cache)
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s.astype(float).sort_index()


def build_har_panel(px: pd.Series) -> pd.DataFrame:
    """HAR-RV features — ALL `.shift(1)` to ensure signal at t-1, target at t.

    Lookahead self-check: rv_d/rv_w/rv_m all derived from daily_rv.shift(1)
    or rolling().shift(1); daily_rv (target) is at index t.
    """
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
# Loss & tests (ported from K1402/K1403)
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
    """Diebold-Mariano with HLN small-sample correction (K1322 lesson).

    H0: E[loss_1 - loss_2] = 0. dm_stat > 0 → loss_1 > loss_2 → model 2 better.
    Here loss_1 = OLS QLIKE, loss_2 = qmed QLIKE; dm_stat > 0 means qmed better.
    """
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
# Per-asset run (single asset, ^TWII)
# ============================================================
def run_asset(asset: str, slug: str) -> dict:
    px = load_asset(asset, slug)
    panel = build_har_panel(px)
    oos_start = pd.Timestamp(OOS_START)
    # ^TWII may not trade on 2021-01-04; use first trading day on/after
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

    # OLS baseline (point forecast)
    ols = sm.OLS(y_train, X_train).fit()
    yhat_ols = np.asarray(ols.predict(X_oos))

    # Quantile regressions
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

    # DM test: OLS QLIKE vs qmed QLIKE (h=1, HLN corrected)
    qlike_ols = qlike(y_oos, yhat_ols)
    qlike_qmed = qlike(y_oos, yhat_q[0.50])
    dm = dm_test(qlike_ols, qlike_qmed, h=1)

    ols_pinball_at_50 = pinball_loss(y_oos, yhat_ols, 0.50)
    qmed_pinball_at_50 = pinball_loss(y_oos, yhat_q[0.50], 0.50)

    verdict = classify_verdict(quantile_results, dm)
    dm_status = classify_dm_status(dm)
    tail_status = classify_tail_status(quantile_results)

    # Lookahead self-check sample print
    first3_oos = panel.loc[oos_mask].head(3)
    print("[lookahead self-check] first 3 OOS rows (target = daily_rv at t; "
          "features = rv_d/rv_w/rv_m at t-1 via .shift(1)):")
    print(first3_oos.to_string())

    return {
        "asset": asset,
        "asset_slug": slug,
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
    """Explicit DM dimension: SIG_POS / SIG_NEG / NS.

    dm_stat > 0 → qmed better than OLS; < 0 → qmed worse.
    """
    dm_p = dm["p_value"]
    dm_stat = dm["dm_stat"]
    if dm_p < 0.10 and dm_stat > 0:
        return "SIG_POS"
    if dm_p < 0.10 and dm_stat < 0:
        return "SIG_NEG"
    return "NS"


def classify_tail_status(qres: dict) -> str:
    """Tail dimension: TIGHT (≤±2pp + Kupiec PASS) / ACCEPTABLE
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
    """Per-asset classification, identical criteria to K1402/K1403.

    Order: DM SIG_NEG first → NULL (with tail usability note);
    then PASS / CONDITIONAL_PASS / TAIL_CALIB_USABLE / NULL.
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
    dm_sig_neg = dm_p < 0.10 and dm_stat < 0
    dm_sig_pos = dm_p < 0.10 and dm_stat > 0
    dm_ns = dm_p >= 0.10
    cov_tight = gap_95 <= 2.0 and gap_99 <= 2.0
    cov_acceptable = gap_95 <= 5.0 and gap_99 <= 5.0

    if dm_sig_neg:
        # NULL on DM; but tail may still be usable → label TAIL_CALIB_USABLE
        # if tail coverage acceptable + Kupiec PASS (matches K1403 single-asset
        # promotion rule).
        if cov_acceptable and kupiec_95_pass and kupiec_99_pass:
            reasons.append(
                f"DM significantly NEGATIVE (qmed worse than OLS stat={dm_stat:.2f} "
                f"p={dm_p:.3f}) BUT tail coverage acceptable "
                f"(gap95={gap_95:.2f}pp gap99={gap_99:.2f}pp) + Kupiec PASS "
                f"(p95={q95['kupiec_uc']['p_value']:.3f} "
                f"p99={q99['kupiec_uc']['p_value']:.3f}) → "
                "tail VaR upper bound usable"
            )
            return {"label": "TAIL_CALIB_USABLE", "reasons": reasons}
        reasons.append(
            f"DM significantly NEGATIVE (qmed worse than OLS, stat={dm_stat:.2f} "
            f"p={dm_p:.3f})"
        )
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


# ============================================================
# Figure: empirical vs nominal coverage band
# ============================================================
def plot_coverage(qres: dict, asset: str, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    taus = []
    nominals = []
    empiricals = []
    for key, v in qres.items():
        taus.append(v["tau"])
        nominals.append(v["nominal_coverage"])
        empiricals.append(v["empirical_coverage"])
    order = np.argsort(taus)
    taus = np.array(taus)[order]
    nominals = np.array(nominals)[order]
    empiricals = np.array(empiricals)[order]

    fig, ax = plt.subplots(figsize=(7, 5))
    # 45° diagonal = perfect calibration
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey",
            alpha=0.6, label="perfect calibration")
    # ±2pp tight band
    ax.fill_between([0, 1], [-0.02, 0.98], [0.02, 1.02], color="green",
                    alpha=0.10, label="±2pp tight band")
    # ±5pp acceptable band
    ax.fill_between([0, 1], [-0.05, 0.95], [0.05, 1.05], color="orange",
                    alpha=0.08, label="±5pp acceptable band")
    ax.plot(nominals, empiricals, marker="o", linewidth=2,
            color="C0", label=f"{asset} HAR-RV QuantReg")
    for t, n_cov, e_cov in zip(taus, nominals, empiricals):
        gap = (e_cov - n_cov) * 100
        ax.annotate(f"τ={t:.2f}\n({gap:+.2f}pp)",
                    xy=(n_cov, e_cov),
                    xytext=(5, -10), textcoords="offset points",
                    fontsize=8)
    ax.set_xlim(0.4, 1.02)
    ax.set_ylim(0.4, 1.02)
    ax.set_xlabel("Nominal coverage τ")
    ax.set_ylabel("Empirical coverage")
    ax.set_title(f"K1404 — {asset} HAR-RV Quantile Coverage (OOS {OOS_START}+)")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ============================================================
# Main
# ============================================================
def main() -> dict:
    result = run_asset(ASSET, ASSET_SLUG)
    plot_coverage(result["quantile_forecasts"], ASSET, FIG_PATH)

    out = {
        "experiment_id": "K1404",
        "title": "HAR-RV Quantile Tail Forecasting on TW market (^TWII)",
        "asset": ASSET,
        "oos_start": OOS_START,
        "n_test": result["n_oos"],
        "pinball_by_tau": {
            k: v["pinball_loss_oos"]
            for k, v in result["quantile_forecasts"].items()
        },
        "coverage_by_tau": {
            k: {
                "nominal": v["nominal_coverage"],
                "empirical": v["empirical_coverage"],
                "gap_pp": v["coverage_gap_pp"],
            }
            for k, v in result["quantile_forecasts"].items()
        },
        "kupiec_uc_by_tau": {
            k: v["kupiec_uc"]
            for k, v in result["quantile_forecasts"].items()
        },
        "dm_test": result["quantile_median_vs_ols"]["dm_qmed_vs_ols"],
        "verdict": result["verdict"],
        "verdict_reason": "; ".join(result["verdict_reasons"]),
        "dm_status": result["dm_status"],
        "tail_status": result["tail_status"],
        "per_asset_full": result,
        "config": {
            "seed": SEED,
            "data_start": DATA_START,
            "oos_start": OOS_START,
            "quantiles": QUANTILES,
            "model": "HAR-RV + statsmodels.QuantReg (Koenker-Bassett 1978)",
            "refit": "none (single fixed-origin fit)",
            "target": "daily_rv = |daily log return %|",
            "features": "rv_d/rv_w/rv_m all via .shift(1) — signal at t-1, target at t",
        },
        "related_k": ["K1402", "K1403", "K1322", "K783c"],
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({
        "experiment_id": out["experiment_id"],
        "asset": out["asset"],
        "n_test": out["n_test"],
        "verdict": out["verdict"],
        "dm_status": out["dm_status"],
        "tail_status": out["tail_status"],
        "dm_stat": round(out["dm_test"]["dm_stat"], 3),
        "dm_p": round(out["dm_test"]["p_value"], 4),
        "tau95_gap_pp": round(out["coverage_by_tau"]["q95"]["gap_pp"], 3),
        "tau99_gap_pp": round(out["coverage_by_tau"]["q99"]["gap_pp"], 3),
        "kupiec95_p": round(out["kupiec_uc_by_tau"]["q95"]["p_value"], 4),
        "kupiec99_p": round(out["kupiec_uc_by_tau"]["q99"]["p_value"], 4),
    }, indent=2))
    return out


if __name__ == "__main__":
    main()
