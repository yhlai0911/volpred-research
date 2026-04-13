#!/usr/bin/env python3
"""
K1090: Cross-Asset A4f Meta-Regression — Quantitative Scope Prediction

Goal
----
Given Paper 9's 12 training assets with A4f DM t statistics (SPY/QQQ/IWM/EEM/FXI/EWZ
/EWT/0050.TW/GLD/USO/TLT/BTC), fit a meta-regression that predicts DM t from asset
characteristics.  Use the fitted model to forecast DM t for 6 untested assets
(EWJ / VGK / IEF / ETH-USD / CPER / SLV).

Methodology
-----------
1. Feature engineering (10 features) — asset class dummies, currency, diversification,
   liquidity, VIX co-movement, own volatility/persistence.
2. OLS + Ridge + LASSO meta-regression on N=12 samples.
3. Bootstrap (B=10,000) coefficient CIs and LOOCV RMSE.
4. Decision tree (depth-3) for scope classification (PASS if DM t >= 3.0).
5. Predict A4f DM t for 6 new assets with prediction intervals.

Guardrails
----------
- N=12 is small → report Bayesian / bootstrap CIs, do NOT overclaim.
- Random seed 42 for all stochastic steps.
- Training labels are from completed Paper 9 experiments (K1085-K1089 chain).
- Feature extraction uses 2018-01-01..2024-12-31 full OOS-compatible window.
- Caches prices locally to keep the run reproducible.

Authors / attribution
---------------------
Proposer: Claude (autonomous), executed under research-program Paper 9 scope work.
"""

from __future__ import annotations

import json
import os
import pathlib
import warnings
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from sklearn.linear_model import Lasso, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, plot_tree

warnings.filterwarnings("ignore")
np.random.seed(42)

HERE = pathlib.Path(__file__).resolve().parent
CACHE_DIR = HERE / "data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = HERE / "k1090_results.json"

START = "2018-01-01"
END = "2024-12-31"

# ----------------------------------------------------------------------------
# Training labels (Paper 9 A4f DM t, full OOS, provided by user prompt)
# ----------------------------------------------------------------------------
TRAINING = [
    # asset, dm_t, class, currency, n_constituents, hhi, source K
    ("SPY",      7.92, "equity_us_large",  "USD",  500,   0.07, "K1085"),
    ("QQQ",      5.99, "equity_us_tech",   "USD",  100,   0.12, "K1085"),
    ("EEM",      5.25, "equity_em_basket", "USD", 1100,   0.05, "K1086"),
    ("IWM",      4.80, "equity_us_small",  "USD", 2000,   0.004, "K1085"),
    ("GLD",      4.46, "commodity_gold",   "USD",    1,   1.00, "K1088"),
    ("USO",      4.48, "commodity_oil",    "USD",    1,   1.00, "K1088"),
    ("FXI",      3.61, "equity_china",     "USD",   50,   0.09, "K1086"),
    ("EWZ",      2.33, "equity_brazil",    "USD",   80,   0.16, "K1086"),
    ("EWT",      2.26, "equity_taiwan_usd","USD",   90,   0.25, "K1086"),
    ("TLT",      1.43, "bonds_long_dur",   "USD",   30,   0.20, "K1087"),
    ("BTC-USD",  1.13, "crypto",           "USD",    1,   1.00, "K1089"),
    ("0050.TW", -0.49, "equity_taiwan_twd","TWD",   50,   0.50, "K1088"),
]

NEW_ASSETS = [
    # ticker, class, currency, n_constituents, hhi
    ("EWJ",       "equity_japan",        "USD", 220,   0.05),
    ("VGK",       "equity_europe",       "USD", 1200,  0.04),
    ("IEF",       "bonds_medium_dur",    "USD", 10,    0.18),
    ("ETH-USD",   "crypto",              "USD", 1,     1.00),
    ("CPER",      "commodity_copper",    "USD", 1,     1.00),
    ("SLV",       "commodity_silver",    "USD", 1,     1.00),
]

# ----------------------------------------------------------------------------
# Data loading helpers (yfinance + cache)
# ----------------------------------------------------------------------------
def _load_price(ticker: str) -> pd.DataFrame:
    cache = CACHE_DIR / f"{ticker.replace('/', '_')}.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        if not df.empty and df.index.max() >= pd.Timestamp(END) - pd.Timedelta(days=10):
            return df
    raw = yf.download(ticker, start=START, end=END,
                      auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.to_csv(cache)
    return raw

def _load_vix() -> pd.Series:
    df = _load_price("^VIX")
    if df.empty:
        return pd.Series(dtype=float)
    return df["Close"].astype(float)

# ----------------------------------------------------------------------------
# Feature engineering
# ----------------------------------------------------------------------------
def _class_dummies(cls: str) -> dict:
    return {
        "class_equity": int("equity" in cls),
        "class_commodity": int("commodity" in cls),
        "class_bond": int("bond" in cls),
        "class_crypto": int("crypto" in cls),
    }

def _currency_dummy(cur: str) -> int:
    return int(cur.upper() == "USD")

def build_features(ticker: str, cls: str, cur: str,
                   n_const: int, hhi: float,
                   vix: pd.Series) -> dict:
    px = _load_price(ticker)
    feats: dict = {
        "ticker": ticker,
        "class_label": cls,
        "currency": cur,
        "n_constituents": int(n_const),
        "hhi": float(hhi),
        "log_n_constituents": float(np.log(max(n_const, 1))),
    }
    feats.update(_class_dummies(cls))
    feats["currency_usd"] = _currency_dummy(cur)

    if px.empty:
        for k in ("log_avg_dollar_volume", "corr_ret_vix", "corr_r2_vix2",
                  "annualized_vol", "r2_acf1"):
            feats[k] = np.nan
        return feats

    close = px["Close"].astype(float).dropna()
    vol_col = "Volume" if "Volume" in px.columns else None
    if vol_col is not None:
        adv = (close * px[vol_col].astype(float)).replace([np.inf, -np.inf], np.nan).dropna().mean()
    else:
        adv = np.nan

    ret = np.log(close).diff().dropna()
    r2 = ret ** 2
    vix_aligned = vix.reindex(ret.index).ffill()
    vix_change = vix_aligned.diff()

    corr_ret_vix = ret.corr(vix_change) if vix_change.notna().sum() > 50 else np.nan
    corr_r2_vix2 = r2.corr((vix_aligned ** 2)) if vix_aligned.notna().sum() > 50 else np.nan
    ann_vol = float(ret.std() * np.sqrt(252)) if len(ret) > 50 else np.nan
    r2_acf1 = float(r2.autocorr(lag=1)) if len(r2) > 50 else np.nan

    feats.update({
        "log_avg_dollar_volume": float(np.log(adv)) if adv and adv > 0 else np.nan,
        "corr_ret_vix": float(corr_ret_vix) if not np.isnan(corr_ret_vix) else np.nan,
        "corr_r2_vix2": float(corr_r2_vix2) if not np.isnan(corr_r2_vix2) else np.nan,
        "annualized_vol": ann_vol,
        "r2_acf1": r2_acf1,
    })
    return feats

FEATURE_COLS = [
    "class_equity", "class_commodity", "class_bond", "class_crypto",
    "currency_usd", "log_n_constituents", "hhi",
    "log_avg_dollar_volume", "corr_ret_vix", "corr_r2_vix2",
    "annualized_vol", "r2_acf1",
]

# ----------------------------------------------------------------------------
# Main pipeline
# ----------------------------------------------------------------------------
def main() -> dict:
    print("[K1090] loading VIX ...")
    vix = _load_vix()
    print(f"[K1090] VIX rows = {len(vix)}")

    rows = []
    print("[K1090] building features for 12 training assets ...")
    for ticker, dm_t, cls, cur, n_c, hhi, src in TRAINING:
        feats = build_features(ticker, cls, cur, n_c, hhi, vix)
        feats["dm_t"] = float(dm_t)
        feats["source_K"] = src
        feats["pass"] = int(dm_t >= 3.0)  # Harvey (2016) PASS boundary
        rows.append(feats)
    df_train = pd.DataFrame(rows)

    print("[K1090] building features for 6 new assets ...")
    new_rows = []
    for ticker, cls, cur, n_c, hhi in NEW_ASSETS:
        feats = build_features(ticker, cls, cur, n_c, hhi, vix)
        new_rows.append(feats)
    df_new = pd.DataFrame(new_rows)

    # Impute missing features with training-set mean to allow prediction
    X_train_raw = df_train[FEATURE_COLS].copy()
    col_means = X_train_raw.mean(numeric_only=True)
    X_train = X_train_raw.fillna(col_means)
    y = df_train["dm_t"].values.astype(float)

    scaler = StandardScaler()
    X_std = scaler.fit_transform(X_train.values)

    # ---------- OLS full ----------
    Xc = np.hstack([np.ones((len(y), 1)), X_train.values])
    ols_full = sm.OLS(y, Xc).fit()
    r2_full = float(ols_full.rsquared)
    r2_adj_full = float(ols_full.rsquared_adj)

    # ---------- Ridge (alpha chosen by LOOCV grid) ----------
    alpha_grid = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0]
    def loocv_rmse(model_fn):
        preds = np.zeros_like(y)
        for i in range(len(y)):
            mask = np.arange(len(y)) != i
            m = model_fn()
            m.fit(X_std[mask], y[mask])
            preds[i] = m.predict(X_std[i:i+1])[0]
        rmse = float(np.sqrt(np.mean((preds - y) ** 2)))
        return rmse, preds

    ridge_results = {}
    best_alpha = None
    best_rmse = np.inf
    for a in alpha_grid:
        rmse, _ = loocv_rmse(lambda a=a: Ridge(alpha=a, random_state=42))
        ridge_results[a] = rmse
        if rmse < best_rmse:
            best_rmse, best_alpha = rmse, a
    ridge = Ridge(alpha=best_alpha, random_state=42).fit(X_std, y)
    ridge_rmse, ridge_preds = loocv_rmse(lambda: Ridge(alpha=best_alpha, random_state=42))

    # ---------- LASSO ----------
    lasso_alpha_grid = [0.01, 0.03, 0.1, 0.3, 1.0]
    lasso_results = {}
    best_lasso_alpha, best_lasso_rmse = None, np.inf
    for a in lasso_alpha_grid:
        rmse, _ = loocv_rmse(lambda a=a: Lasso(alpha=a, random_state=42, max_iter=20000))
        lasso_results[a] = rmse
        if rmse < best_lasso_rmse:
            best_lasso_rmse, best_lasso_alpha = rmse, a
    lasso = Lasso(alpha=best_lasso_alpha, random_state=42, max_iter=20000).fit(X_std, y)
    lasso_rmse, lasso_preds = loocv_rmse(lambda: Lasso(alpha=best_lasso_alpha, random_state=42, max_iter=20000))

    # ---------- Compact OLS: only LASSO-selected features (well-identified) ----------
    compact_feats = [n for n, c in zip(FEATURE_COLS, lasso.coef_) if abs(c) > 1e-8]
    if not compact_feats:
        compact_feats = ["currency_usd", "corr_ret_vix"]
    X_compact = X_train[compact_feats].values
    Xc_compact = np.hstack([np.ones((len(y), 1)), X_compact])
    ols_compact = sm.OLS(y, Xc_compact).fit()
    # LOOCV for compact
    compact_preds = np.zeros_like(y)
    for i in range(len(y)):
        mask = np.arange(len(y)) != i
        fit = sm.OLS(y[mask], Xc_compact[mask]).fit()
        compact_preds[i] = fit.params @ Xc_compact[i]
    compact_loocv_rmse = float(np.sqrt(np.mean((compact_preds - y) ** 2)))
    compact_loocv_r2 = float(1 - np.sum((compact_preds - y) ** 2) / np.sum((y - y.mean()) ** 2))
    compact_coef_table = []
    for i, name in enumerate(["const"] + compact_feats):
        compact_coef_table.append({
            "feature": name,
            "coef":  float(ols_compact.params[i]),
            "se":    float(ols_compact.bse[i]),
            "t":     float(ols_compact.tvalues[i]),
            "p":     float(ols_compact.pvalues[i]),
        })

    # ---------- OLS reduced: stepwise by p-value (simple backward elimination) ----------
    def backward_elim(X_df: pd.DataFrame, y: np.ndarray, p_thresh=0.10):
        cols = list(X_df.columns)
        while cols:
            Xc_ = sm.add_constant(X_df[cols].values)
            fit = sm.OLS(y, Xc_).fit()
            pvals = fit.pvalues[1:]  # drop const
            worst = np.argmax(pvals)
            if pvals[worst] > p_thresh:
                cols.pop(worst)
            else:
                return cols, fit
        return cols, None
    sel_cols, ols_sel = backward_elim(X_train, y, p_thresh=0.10)
    if ols_sel is None:
        sel_cols = FEATURE_COLS
        ols_sel = ols_full

    # ---------- Bootstrap CIs for OLS full coefficients ----------
    B = 10_000
    rng = np.random.default_rng(42)
    boot_coefs = np.zeros((B, Xc.shape[1]))
    n = len(y)
    for b in range(B):
        idx = rng.integers(0, n, n)
        fit = sm.OLS(y[idx], Xc[idx]).fit()
        boot_coefs[b] = fit.params
    ci_low = np.percentile(boot_coefs, 2.5, axis=0)
    ci_hi  = np.percentile(boot_coefs, 97.5, axis=0)

    coef_table = []
    for i, name in enumerate(["const"] + FEATURE_COLS):
        coef_table.append({
            "feature": name,
            "coef_ols": float(ols_full.params[i]),
            "se_ols": float(ols_full.bse[i]),
            "t_ols": float(ols_full.tvalues[i]),
            "p_ols": float(ols_full.pvalues[i]),
            "boot_ci95_low": float(ci_low[i]),
            "boot_ci95_hi":  float(ci_hi[i]),
        })

    # ---------- LOOCV for OLS full ----------
    # Manually prepend constant to avoid sm.add_constant surprises on small subsets
    Xc_manual = np.hstack([np.ones((len(y), 1)), X_train.values])
    ols_full_preds = np.zeros_like(y)
    for i in range(len(y)):
        mask = np.arange(len(y)) != i
        fit = sm.OLS(y[mask], Xc_manual[mask]).fit()
        ols_full_preds[i] = fit.params @ Xc_manual[i]
    ols_loocv_rmse = float(np.sqrt(np.mean((ols_full_preds - y) ** 2)))
    ols_loocv_r2 = float(1 - np.sum((ols_full_preds - y) ** 2) / np.sum((y - y.mean()) ** 2))

    # ---------- Decision tree (depth 3) on PASS flag ----------
    tree = DecisionTreeClassifier(max_depth=3, random_state=42)
    tree.fit(X_train.values, df_train["pass"].values)
    tree_preds = tree.predict(X_train.values)
    tree_acc = float((tree_preds == df_train["pass"].values).mean())

    # ---------- Predict 6 new assets ----------
    X_new_raw = df_new[FEATURE_COLS].copy().fillna(col_means)
    X_new_std = scaler.transform(X_new_raw.values)

    Xc_new = np.hstack([np.ones((len(df_new), 1)), X_new_raw.values])
    new_preds_ols = Xc_new @ ols_full.params
    new_preds_ridge = ridge.predict(X_new_std)
    new_preds_lasso = lasso.predict(X_new_std)

    # Bootstrap prediction intervals using refit OLS (manual constant)
    new_pred_boot = np.zeros((B, len(df_new)))
    for b in range(B):
        idx = rng.integers(0, n, n)
        fit = sm.OLS(y[idx], Xc_manual[idx]).fit()
        new_pred_boot[b] = Xc_new @ fit.params
    pi_low = np.percentile(new_pred_boot, 2.5, axis=0)
    pi_hi  = np.percentile(new_pred_boot, 97.5, axis=0)

    # Also bootstrap Ridge predictions for a regularized PI (more honest with small N)
    new_pred_boot_ridge = np.zeros((B, len(df_new)))
    for b in range(B):
        idx = rng.integers(0, n, n)
        m = Ridge(alpha=best_alpha, random_state=42)
        m.fit(X_std[idx], y[idx])
        new_pred_boot_ridge[b] = m.predict(X_new_std)
    pi_low_r = np.percentile(new_pred_boot_ridge, 2.5, axis=0)
    pi_hi_r  = np.percentile(new_pred_boot_ridge, 97.5, axis=0)

    predictions = []
    for i, row in df_new.iterrows():
        recommended = float(new_preds_ridge[i])  # Ridge is the selected model (best LOOCV)
        predictions.append({
            "ticker": row["ticker"],
            "class_label": row["class_label"],
            "currency": row["currency"],
            "ols_full_pred": float(new_preds_ols[i]),
            "ridge_pred": float(new_preds_ridge[i]),
            "lasso_pred": float(new_preds_lasso[i]),
            "recommended_pred": recommended,
            "pi95_low_ridge": float(pi_low_r[i]),
            "pi95_hi_ridge":  float(pi_hi_r[i]),
            "pi95_low_ols":  float(pi_low[i]),
            "pi95_hi_ols":   float(pi_hi[i]),
            "pass_prob_ridge": float(np.mean(new_pred_boot_ridge[:, i] >= 3.0)),
            "pass_prob_ols":   float(np.mean(new_pred_boot[:, i] >= 3.0)),
            "tree_pass": int(tree.predict(X_new_raw.iloc[[i]].values)[0]),
            "recommendation": (
                "strong_run"   if new_preds_ridge[i] >= 4.0 else
                "run"          if new_preds_ridge[i] >= 3.0 else
                "marginal"     if new_preds_ridge[i] >= 2.0 else
                "likely_fail"
            ),
        })

    # ---------- Persist results ----------
    results = {
        "meta": {
            "experiment_id": "K1090",
            "title": "Cross-asset A4f meta-regression — scope prediction",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "random_seed": 42,
            "n_train": len(df_train),
            "n_new": len(df_new),
            "feature_cols": FEATURE_COLS,
            "window_for_features": f"{START} .. {END}",
            "training_source_Ks": sorted({r[6] for r in TRAINING}),
            "pass_threshold_dm_t": 3.0,
            "caveat": "N=12 sample. Bootstrap CIs are wide. Predictions are directional hypotheses, not guarantees.",
        },
        "training": df_train.to_dict(orient="records"),
        "new_assets_raw": df_new.to_dict(orient="records"),
        "ols_full": {
            "r2": r2_full,
            "adj_r2": r2_adj_full,
            "loocv_rmse": ols_loocv_rmse,
            "loocv_r2":   ols_loocv_r2,
            "saturated_warning": "N=p+1=12; full model is saturated, t and p are undefined; LOOCV exposes overfit.",
            "coefficients": coef_table,
            "loocv_predictions": [
                {"ticker": t, "actual": float(a), "pred": float(p)}
                for t, a, p in zip(df_train["ticker"], y, ols_full_preds)
            ],
        },
        "ols_compact": {
            "features": compact_feats,
            "r2": float(ols_compact.rsquared),
            "adj_r2": float(ols_compact.rsquared_adj),
            "loocv_rmse": compact_loocv_rmse,
            "loocv_r2": compact_loocv_r2,
            "coefficients": compact_coef_table,
            "loocv_predictions": [
                {"ticker": t, "actual": float(a), "pred": float(p)}
                for t, a, p in zip(df_train["ticker"], y, compact_preds)
            ],
        },
        "ols_stepwise": {
            "selected_features": sel_cols,
            "r2": float(ols_sel.rsquared),
            "adj_r2": float(ols_sel.rsquared_adj),
            "coefficients": [
                {"feature": n, "coef": float(c), "p": float(p)}
                for n, c, p in zip(["const"] + sel_cols, ols_sel.params, ols_sel.pvalues)
            ],
        },
        "ridge": {
            "alpha_grid_loocv_rmse": {str(k): float(v) for k, v in ridge_results.items()},
            "best_alpha": float(best_alpha),
            "loocv_rmse": float(ridge_rmse),
            "coefficients_standardized": [
                {"feature": n, "coef": float(c)}
                for n, c in zip(FEATURE_COLS, ridge.coef_)
            ],
            "loocv_predictions": [
                {"ticker": t, "actual": float(a), "pred": float(p)}
                for t, a, p in zip(df_train["ticker"], y, ridge_preds)
            ],
        },
        "lasso": {
            "alpha_grid_loocv_rmse": {str(k): float(v) for k, v in lasso_results.items()},
            "best_alpha": float(best_lasso_alpha),
            "loocv_rmse": float(lasso_rmse),
            "coefficients_standardized": [
                {"feature": n, "coef": float(c)}
                for n, c in zip(FEATURE_COLS, lasso.coef_)
            ],
            "nonzero_features": [n for n, c in zip(FEATURE_COLS, lasso.coef_) if abs(c) > 1e-8],
        },
        "decision_tree": {
            "max_depth": 3,
            "train_accuracy": tree_acc,
            "feature_importances": [
                {"feature": n, "importance": float(c)}
                for n, c in zip(FEATURE_COLS, tree.feature_importances_)
            ],
        },
        "new_asset_predictions": predictions,
    }
    OUT_JSON.write_text(json.dumps(results, indent=2))
    print(f"[K1090] wrote {OUT_JSON}")

    # ------------------------------------------------------------------
    # Figures
    # ------------------------------------------------------------------
    # 1. feature correlation heatmap
    corr = X_train.corr()
    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdBu_r")
    ax.set_xticks(range(len(FEATURE_COLS)))
    ax.set_yticks(range(len(FEATURE_COLS)))
    ax.set_xticklabels(FEATURE_COLS, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(FEATURE_COLS, fontsize=9)
    for i in range(len(FEATURE_COLS)):
        for j in range(len(FEATURE_COLS)):
            ax.text(j, i, f"{corr.iat[i, j]:.2f}", ha="center", va="center",
                    fontsize=7, color="black" if abs(corr.iat[i, j]) < 0.6 else "white")
    ax.set_title("K1090 — feature correlation (N=12)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(HERE / "k1090_features.png", dpi=140)
    plt.close(fig)

    # 2. coefficients + bootstrap CI (skip const)
    names = [c["feature"] for c in coef_table if c["feature"] != "const"]
    coefs = [c["coef_ols"] for c in coef_table if c["feature"] != "const"]
    lows  = [c["boot_ci95_low"] for c in coef_table if c["feature"] != "const"]
    highs = [c["boot_ci95_hi"]  for c in coef_table if c["feature"] != "const"]
    order = np.argsort(coefs)
    fig, ax = plt.subplots(figsize=(8, 7))
    y_pos = np.arange(len(names))
    err_low  = [max(0.0, coefs[i] - lows[i]) for i in order]
    err_high = [max(0.0, highs[i] - coefs[i]) for i in order]
    ax.errorbar([coefs[i] for i in order], y_pos,
                xerr=[err_low, err_high],
                fmt="o", capsize=3)
    ax.set_yticks(y_pos)
    ax.set_yticklabels([names[i] for i in order])
    ax.axvline(0, color="grey", linestyle="--")
    ax.set_xlabel("OLS coefficient (bootstrap 95% CI, B=10000)")
    ax.set_title("K1090 — meta-regression coefficients")
    fig.tight_layout()
    fig.savefig(HERE / "k1090_coefficients.png", dpi=140)
    plt.close(fig)

    # 3. LOOCV fit quality (Ridge + compact OLS — the honest models)
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(y, ridge_preds, label=f"Ridge a={best_alpha:g} (RMSE={ridge_rmse:.2f})",
               s=60, marker="s")
    ax.scatter(y, compact_preds,
               label=f"OLS compact ({'+'.join(compact_feats)}) RMSE={compact_loocv_rmse:.2f}",
               s=60, marker="o", alpha=0.7)
    for t, a, p in zip(df_train["ticker"], y, compact_preds):
        ax.annotate(t, (a, p), fontsize=8, xytext=(4, 2), textcoords="offset points")
    all_preds = np.concatenate([ridge_preds, compact_preds])
    lim = [min(y.min(), all_preds.min()) - 1,
           max(y.max(), all_preds.max()) + 1]
    ax.plot(lim, lim, color="grey", linestyle="--")
    ax.axhline(3.0, color="red", linestyle=":", alpha=0.6, label="PASS boundary (DM t=3)")
    ax.axvline(3.0, color="red", linestyle=":", alpha=0.6)
    ax.set_xlabel("actual DM t")
    ax.set_ylabel("LOOCV predicted DM t")
    ax.set_title("K1090 — LOOCV predictions vs actual")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "k1090_loocv.png", dpi=140)
    plt.close(fig)

    # 4. New asset predictions with PIs (Ridge, selected model)
    fig, ax = plt.subplots(figsize=(8, 6))
    tickers = [p["ticker"] for p in predictions]
    preds_v = [p["ridge_pred"] for p in predictions]
    lo = [p["pi95_low_ridge"] for p in predictions]
    hi = [p["pi95_hi_ridge"] for p in predictions]
    y_pos = np.arange(len(tickers))
    err_lo = np.clip(np.array(preds_v) - np.array(lo), 0, None)
    err_hi = np.clip(np.array(hi) - np.array(preds_v), 0, None)
    ax.errorbar(preds_v, y_pos, xerr=[err_lo, err_hi],
                fmt="o", capsize=4, color="steelblue")
    for i, p in enumerate(predictions):
        ax.text(p["ridge_pred"] + 0.1, i + 0.15,
                f"P(PASS)={p['pass_prob_ridge']:.2f}  [{p['recommendation']}]",
                fontsize=8)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(tickers)
    ax.axvline(3.0, color="red", linestyle="--", label="PASS boundary (Harvey t=3)")
    ax.axvline(0.0, color="grey", linestyle=":")
    ax.set_xlabel("Ridge-predicted A4f DM t")
    ax.set_title("K1090 — predicted A4f DM t for 6 untested assets (Ridge, 95% PI)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "k1090_new_asset_predictions.png", dpi=140)
    plt.close(fig)

    # 5. Decision tree plot
    fig, ax = plt.subplots(figsize=(12, 7))
    plot_tree(tree, feature_names=FEATURE_COLS, class_names=["FAIL", "PASS"],
              filled=True, rounded=True, ax=ax, fontsize=8)
    ax.set_title("K1090 — A4f PASS/FAIL decision tree (depth 3)")
    fig.tight_layout()
    fig.savefig(HERE / "k1090_scope_decision_tree.png", dpi=140)
    plt.close(fig)

    # 6. Training summary: DM t ordered with class label colouring
    fig, ax = plt.subplots(figsize=(9, 6))
    order2 = np.argsort(-y)
    colors = []
    for i in order2:
        cls = df_train.iloc[i]["class_label"]
        if "equity" in cls:
            colors.append("steelblue")
        elif "commodity" in cls:
            colors.append("goldenrod")
        elif "bond" in cls:
            colors.append("seagreen")
        else:
            colors.append("purple")
    ax.barh(range(len(y)), y[order2], color=colors)
    ax.set_yticks(range(len(y)))
    ax.set_yticklabels([df_train.iloc[i]["ticker"] for i in order2])
    ax.axvline(3.0, color="red", linestyle="--", label="PASS boundary")
    ax.axvline(0.0, color="grey", linestyle=":")
    ax.set_xlabel("actual A4f DM t (Paper 9)")
    ax.set_title("K1090 — training DM t by asset (N=12)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "k1090_training_dm_t.png", dpi=140)
    plt.close(fig)

    print("[K1090] done.")
    return results


if __name__ == "__main__":
    main()
