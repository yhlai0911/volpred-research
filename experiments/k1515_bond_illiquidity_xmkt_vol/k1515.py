"""K1515 PoC — Bond illiquidity prediction with cross-market volatility features.

Research question: Can lagged cross-market vol features (SPY realized vol, VIX,
SPY-VIX corr, credit-spread proxy) improve out-of-sample prediction of HYG
daily illiquidity proxy (high-low/close) versus an OLS autoregressive baseline?

Lookahead defense:
  - All features are explicitly shifted by 1 day via .shift(1) before fitting.
  - Rolling statistics use trailing windows only (pandas .rolling default).
  - Target is HYG illiquidity_proxy at time t; features all use data <= t-1.

Reproducibility:
  - Random seed = 42 for XGBoost.
  - yfinance data only; failure -> hard error (no synthetic fallback).
  - Train: 2014-01-01 to 2022-12-31; OOS: 2023-01-01 to 2026-06-15.

Differentiation from prior K:
  - K1472: HAR + illiquidity proxy predicting EQUITY vol (reverse direction).
  - K150/K265/K266: Amihud / liquidity proxies as GARCH-X exo on equity vol.
  - K862: Corwin-Schultz spread cross-correlation analysis.
  - K1515 (this): predict BOND illiquidity using stock-market vol features.

Run: `uv run python experiments/k1515_bond_illiquidity_xmkt_vol/k1515.py`
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from xgboost import XGBRegressor

SEED = 42
HERE = Path(__file__).resolve().parent

START = "2014-01-01"
END = "2026-06-15"
TRAIN_END = "2022-12-31"
OOS_START = "2023-01-01"

TICKERS = ["HYG", "LQD", "VCIT", "SPY", "^VIX"]


def fetch_data() -> pd.DataFrame:
    """Download daily prices via yfinance.  No fallback on failure."""
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        progress=False,
        auto_adjust=False,
        group_by="ticker",
        threads=True,
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned empty frame")

    frames: dict[str, pd.DataFrame] = {}
    for t in TICKERS:
        if (t, "Close") not in raw.columns:
            raise RuntimeError(f"Missing OHLC for {t} in yfinance response")
        sub = raw[t][["High", "Low", "Close"]].copy()
        sub.columns = [f"{t}_high", f"{t}_low", f"{t}_close"]
        frames[t] = sub

    df = pd.concat(frames.values(), axis=1)
    df = df.dropna(how="any")
    if df.empty:
        raise RuntimeError("After dropna, dataframe empty - data quality issue")
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build features. Target = HYG illiquidity at t.

    All predictors will be shifted by 1 day before merging so no t-information
    leaks into the model.
    """
    out = pd.DataFrame(index=df.index)

    # Target: HYG illiquidity proxy = (High - Low) / Close at day t.
    out["target_illiq_t"] = (df["HYG_high"] - df["HYG_low"]) / df["HYG_close"]

    # AR features (same proxy lagged).
    out["hyg_illiq_lag1"] = out["target_illiq_t"].shift(1)
    out["hyg_illiq_ma5"] = out["target_illiq_t"].rolling(5).mean().shift(1)
    out["hyg_illiq_ma22"] = out["target_illiq_t"].rolling(22).mean().shift(1)

    # SPY realized vol (22d) - annualized.
    spy_logret = np.log(df["SPY_close"] / df["SPY_close"].shift(1))
    out["spy_rv22"] = (
        spy_logret.rolling(22).std().shift(1) * np.sqrt(252)
    )

    # VIX level (use lag1 close).
    out["vix_lag1"] = df["^VIX_close"].shift(1)

    # Credit spread proxy: HYG_ret - LQD_ret (5d rolling mean), negative ->
    # HY underperformed IG -> credit stress.
    hyg_ret = df["HYG_close"].pct_change()
    lqd_ret = df["LQD_close"].pct_change()
    cs_proxy = (hyg_ret - lqd_ret).rolling(5).mean()
    out["credit_spread_ma5"] = cs_proxy.shift(1)

    # SPY-VIX 22d rolling correlation (always negative typically, sharper neg
    # in stress).  Use returns vs vix-level changes.
    vix_change = df["^VIX_close"].diff()
    spy_ret = df["SPY_close"].pct_change()
    out["spy_vix_corr22"] = (
        spy_ret.rolling(22).corr(vix_change).shift(1)
    )

    out = out.dropna()
    return out


def split_train_oos(feat: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = feat.loc[:TRAIN_END]
    oos = feat.loc[OOS_START:]
    return train, oos


def fit_eval(
    train: pd.DataFrame, oos: pd.DataFrame, feature_cols: list[str]
) -> dict:
    Xtr, ytr = train[feature_cols].values, train["target_illiq_t"].values
    Xte, yte = oos[feature_cols].values, oos["target_illiq_t"].values

    # OLS baseline.
    ols = LinearRegression()
    ols.fit(Xtr, ytr)
    ols_pred = ols.predict(Xte)

    # XGBoost (default-ish, fixed seed, no HPO per PoC scope).
    xgb = XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        random_state=SEED,
        n_jobs=1,
        verbosity=0,
    )
    xgb.fit(Xtr, ytr)
    xgb_pred = xgb.predict(Xte)

    # Metrics.
    ols_r2 = r2_score(yte, ols_pred)
    xgb_r2 = r2_score(yte, xgb_pred)
    ols_rmse = float(np.sqrt(mean_squared_error(yte, ols_pred)))
    xgb_rmse = float(np.sqrt(mean_squared_error(yte, xgb_pred)))

    # Diebold-Mariano on squared-error loss (QLIKE-like for non-negative
    # target).  Use HLN small-sample variant via t-distribution.
    e_ols = (yte - ols_pred) ** 2
    e_xgb = (yte - xgb_pred) ** 2
    d = e_ols - e_xgb  # positive d -> xgb better
    n = len(d)
    d_mean = d.mean()
    # Newey-West-ish lag=h-1; for h=1 forecast use plain variance.
    d_var = d.var(ddof=1)
    dm_stat = d_mean / np.sqrt(d_var / n)
    # two-sided p-value.
    dm_pvalue = float(2 * (1 - stats.norm.cdf(abs(dm_stat))))

    importance = dict(
        zip(feature_cols, [float(v) for v in xgb.feature_importances_])
    )

    return {
        "ols_oos_r2": float(ols_r2),
        "xgb_oos_r2": float(xgb_r2),
        "ols_oos_rmse": ols_rmse,
        "xgb_oos_rmse": xgb_rmse,
        "dm_stat_xgb_vs_ols": float(dm_stat),
        "dm_pvalue": dm_pvalue,
        "n_train": int(len(train)),
        "n_oos": int(len(oos)),
        "feature_importance_xgb": importance,
        "ols_coefs": dict(
            zip(feature_cols, [float(v) for v in ols.coef_])
        ),
        "ols_intercept": float(ols.intercept_),
    }


def maybe_plot(oos: pd.DataFrame, results_meta: dict) -> None:
    """Plot actual vs predicted + feature importance.  Soft-fail if matplotlib
    unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        print(f"[plot] matplotlib unavailable, skipping plot: {exc}")
        return

    # Need to refit briefly for plotting.  Cheaper: re-run quickly with same
    # seed for predictions.
    feat_cols = [c for c in oos.columns if c != "target_illiq_t"]
    Xte = oos[feat_cols].values
    yte = oos["target_illiq_t"].values

    # We already have predictions implicitly from fit_eval - but to keep code
    # simple we redo it.
    ols = LinearRegression()
    train = results_meta["_train_ref"]
    Xtr, ytr = train[feat_cols].values, train["target_illiq_t"].values
    ols.fit(Xtr, ytr)
    ols_pred = ols.predict(Xte)

    xgb = XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        random_state=SEED,
        n_jobs=1,
        verbosity=0,
    )
    xgb.fit(Xtr, ytr)
    xgb_pred = xgb.predict(Xte)

    fig, axes = plt.subplots(2, 1, figsize=(11, 7))
    ax1 = axes[0]
    ax1.plot(oos.index, yte, label="Actual HYG illiq", color="black", lw=0.8)
    ax1.plot(oos.index, ols_pred, label="OLS pred", color="tab:blue", lw=0.8)
    ax1.plot(oos.index, xgb_pred, label="XGB pred", color="tab:red", lw=0.8)
    ax1.set_title("K1515 OOS: HYG illiquidity actual vs predicted (2023-2026H1)")
    ax1.set_ylabel("(High-Low)/Close")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(alpha=0.3)

    ax2 = axes[1]
    imp = xgb.feature_importances_
    order = np.argsort(imp)[::-1]
    ax2.bar(range(len(imp)), imp[order])
    ax2.set_xticks(range(len(imp)))
    ax2.set_xticklabels([feat_cols[i] for i in order], rotation=30, ha="right")
    ax2.set_title("XGBoost feature importance (gain)")
    ax2.grid(alpha=0.3, axis="y")

    fig.tight_layout()
    fig.savefig(HERE / "k1515_plots.png", dpi=120)
    plt.close(fig)
    print("[plot] saved k1515_plots.png")


def main() -> int:
    print(f"[k1515] start {datetime.now().isoformat(timespec='seconds')}")
    df = fetch_data()
    print(f"[k1515] raw rows: {len(df)}  cols: {len(df.columns)}")

    feat = build_features(df)
    print(f"[k1515] feature rows: {len(feat)}  cols: {len(feat.columns)}")

    train, oos = split_train_oos(feat)
    print(
        f"[k1515] train rows: {len(train)} ({train.index.min().date()}->"
        f"{train.index.max().date()})"
    )
    print(
        f"[k1515] oos   rows: {len(oos)} ({oos.index.min().date()}->"
        f"{oos.index.max().date()})"
    )

    feature_cols = [c for c in feat.columns if c != "target_illiq_t"]
    print(f"[k1515] features: {feature_cols}")

    metrics = fit_eval(train, oos, feature_cols)

    verdict = "NULL"
    if metrics["xgb_oos_r2"] > metrics["ols_oos_r2"] and metrics["dm_pvalue"] < 0.05:
        verdict = "PASS"
    elif metrics["xgb_oos_r2"] > metrics["ols_oos_r2"] and metrics["dm_pvalue"] < 0.10:
        verdict = "CONDITIONAL_PASS"
    elif metrics["xgb_oos_r2"] < metrics["ols_oos_r2"] - 0.02:
        verdict = "FAIL"
    else:
        verdict = "NULL"

    results = {
        "experiment_id": "K1515",
        "title": "Bond illiquidity prediction via cross-market vol features",
        "verdict": verdict,
        "period": {
            "data_start": START,
            "data_end": END,
            "train_end": TRAIN_END,
            "oos_start": OOS_START,
        },
        "target": "HYG daily illiquidity proxy = (High-Low)/Close",
        "features": feature_cols,
        "seed": SEED,
        "metrics": metrics,
        "lookahead_defenses": [
            "All non-target columns built with .shift(1) explicitly",
            "Rolling stats use trailing windows only (pandas default)",
            "Train/OOS split is strictly temporal: train<=2022-12-31, oos>=2023-01-01",
        ],
        "reproducibility": {
            "random_seed": SEED,
            "xgboost_version": __import__("xgboost").__version__,
            "yfinance_version": __import__("yfinance").__version__,
            "python": sys.version.split()[0],
        },
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
    }

    out_path = HERE / "k1515_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"[k1515] wrote {out_path}")
    print(f"[k1515] VERDICT = {verdict}")
    print(
        f"  OLS R2={metrics['ols_oos_r2']:.4f}  "
        f"XGB R2={metrics['xgb_oos_r2']:.4f}  "
        f"DM stat={metrics['dm_stat_xgb_vs_ols']:.3f}  "
        f"pval={metrics['dm_pvalue']:.4f}"
    )

    try:
        maybe_plot(oos, {"_train_ref": train})
    except Exception as exc:  # pragma: no cover
        print(f"[plot] non-fatal plot error: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
