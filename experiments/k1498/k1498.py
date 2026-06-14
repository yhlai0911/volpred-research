"""K1498: Option-liquidity crash-risk proxy without option microstructure.

The queued research idea asks whether option-market liquidity can act as a
crash-risk covariate. We do not have option microstructure data, so this script
tests an honest free-data proxy: SPY low-frequency liquidity stress plus
option-implied tail/fear indexes (VIX, SKEW, VVIX).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

EXPERIMENT_ID = "K1498"
SEED = 42
OOS_START = pd.Timestamp("2021-01-04")
BOOT_REPS = 1000
BOOT_BLOCK = 21

SPY_VIX_PATH = REPO / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv"
RESULTS_PATH = HERE / "k1498_results.json"
FIG_PATH = HERE / "k1498_oos_auc.png"

np.random.seed(SEED)


def fetch_or_read_index(symbol: str) -> pd.DataFrame:
    safe = symbol.replace("^", "")
    path = DATA_DIR / f"{safe.lower()}_2012_2026.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["date"])

    df = yf.download(
        symbol,
        start="2012-01-01",
        end="2026-06-10",
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if df.empty:
        raise RuntimeError(f"yfinance returned no rows for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        close = df[("Close", symbol)]
    else:
        close = df["Close"]
    out = pd.DataFrame({"date": close.index, f"{safe.lower()}_close": close.values})
    out.to_csv(path, index=False)
    return out


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    log_hl = np.log(high / low)
    beta = log_hl.pow(2) + log_hl.pow(2).shift(1)
    high_2d = pd.concat([high, high.shift(1)], axis=1).max(axis=1)
    low_2d = pd.concat([low, low.shift(1)], axis=1).min(axis=1)
    gamma = np.log(high_2d / low_2d).pow(2)
    k = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    alpha = alpha.clip(lower=0.0, upper=5.0)
    spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    spread[~np.isfinite(spread)] = np.nan
    return spread


def rolling_z(series: pd.Series, window: int = 252) -> pd.Series:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std()
    return (series - mean) / std.replace(0.0, np.nan)


def load_panel() -> pd.DataFrame:
    base = pd.read_csv(SPY_VIX_PATH, parse_dates=["date"])
    base = base[
        [
            "date",
            "spy_close",
            "spy_high",
            "spy_low",
            "spy_volume",
            "vix_close",
        ]
    ].dropna()
    skew = fetch_or_read_index("^SKEW")
    vvix = fetch_or_read_index("^VVIX")
    df = base.merge(skew, on="date", how="left").merge(vvix, on="date", how="left")
    df = df.sort_values("date").reset_index(drop=True)

    ret = np.log(df["spy_close"]).diff()
    dollar_volume = df["spy_close"] * df["spy_volume"].replace(0, np.nan)
    intraday_range = (df["spy_high"] - df["spy_low"]) / df["spy_close"]

    df["ret"] = ret
    df["rv"] = ret.pow(2)
    df["rv5_sum"] = df["rv"].rolling(5).sum()
    df["fwd5_ret"] = ret.rolling(5).sum().shift(-4)
    df["fwd5_rv"] = df["rv"].rolling(5).sum().shift(-4)

    df["amihud_raw"] = np.log1p((ret.abs() / dollar_volume) * 1e10)
    df["cs_spread_raw"] = corwin_schultz_spread(df["spy_high"], df["spy_low"])
    df["range_volume_raw"] = np.log1p(intraday_range / np.log1p(df["spy_volume"]))

    for col in [
        "amihud_raw",
        "cs_spread_raw",
        "range_volume_raw",
        "vix_close",
        "skew_close",
        "vvix_close",
        "rv",
    ]:
        df[col.replace("_raw", "") + "_z"] = rolling_z(df[col])

    df["vix_z"] = df["vix_close_z"]
    df["skew_z"] = df["skew_close_z"]
    df["vvix_z"] = df["vvix_close_z"]

    df["momentum22"] = ret.rolling(22).sum()
    df["rv22_z"] = rolling_z(df["rv"].rolling(22).mean())
    df["stock_liquidity_stress_raw"] = df[
        ["amihud_z", "cs_spread_z", "range_volume_z"]
    ].mean(axis=1)
    df["option_tail_stress_raw"] = df[["skew_z", "vvix_z"]].mean(axis=1)
    df["option_liquidity_proxy_raw"] = df[
        ["stock_liquidity_stress_raw", "option_tail_stress_raw"]
    ].mean(axis=1)

    signal_cols = [
        "vix_z",
        "rv22_z",
        "momentum22",
        "stock_liquidity_stress_raw",
        "option_tail_stress_raw",
        "option_liquidity_proxy_raw",
    ]
    for col in signal_cols:
        # Explicit t-1 information set: signal at t-1 predicts target at t.
        df[col.replace("_raw", "") + "_lag1"] = df[col].shift(1)

    ret_q05 = ret.rolling(252, min_periods=252).quantile(0.05).shift(1)
    rv_q95 = df["rv"].rolling(252, min_periods=252).quantile(0.95).shift(1)
    fwd5_ret_hist = ret.rolling(5).sum()
    fwd5_rv_hist = df["rv"].rolling(5).sum()
    fwd5_ret_q05 = fwd5_ret_hist.rolling(252, min_periods=252).quantile(0.05).shift(1)
    fwd5_rv_q95 = fwd5_rv_hist.rolling(252, min_periods=252).quantile(0.95).shift(1)

    df["crash_1d"] = (ret < ret_q05).astype(float)
    df["rv_jump_1d"] = (df["rv"] > rv_q95).astype(float)
    df["crash_5d"] = (df["fwd5_ret"] < fwd5_ret_q05).astype(float)
    df["rv_jump_5d"] = (df["fwd5_rv"] > fwd5_rv_q95).astype(float)

    model_cols = [
        "date",
        "crash_1d",
        "crash_5d",
        "rv_jump_1d",
        "rv_jump_5d",
        "vix_z_lag1",
        "rv22_z_lag1",
        "momentum22_lag1",
        "stock_liquidity_stress_lag1",
        "option_tail_stress_lag1",
        "option_liquidity_proxy_lag1",
    ]
    return df[model_cols].dropna().reset_index(drop=True)


def auc_score(y: np.ndarray, score: np.ndarray) -> float:
    y = np.asarray(y, dtype=int)
    score = np.asarray(score, dtype=float)
    n_pos = int(y.sum())
    n_neg = int(len(y) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = stats.rankdata(score)
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def fit_glm(train: pd.DataFrame, y_col: str, features: list[str]):
    x = sm.add_constant(train[features], has_constant="add")
    y = train[y_col]
    return sm.GLM(y, x, family=sm.families.Binomial()).fit(maxiter=200, disp=False)


def moving_block_ci(
    y: np.ndarray,
    score: np.ndarray,
    reps: int = BOOT_REPS,
    block: int = BOOT_BLOCK,
) -> dict:
    rng = np.random.default_rng(SEED)
    n = len(y)
    cutoff = np.quantile(score, 0.90)
    top = score >= cutoff
    base_diff = float(y[top].mean() - y[~top].mean())
    vals = []
    for _ in range(reps):
        idx = []
        while len(idx) < n:
            start = int(rng.integers(0, max(1, n - block + 1)))
            idx.extend(range(start, min(start + block, n)))
        idx_arr = np.asarray(idx[:n])
        y_b = y[idx_arr]
        score_b = score[idx_arr]
        c = np.quantile(score_b, 0.90)
        top_b = score_b >= c
        if top_b.any() and (~top_b).any():
            vals.append(float(y_b[top_b].mean() - y_b[~top_b].mean()))
    arr = np.asarray(vals)
    return {
        "top_decile_event_rate": float(y[top].mean()),
        "rest_event_rate": float(y[~top].mean()),
        "event_rate_lift": base_diff,
        "bootstrap_ci_95": [float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975))],
    }


def evaluate_target(df: pd.DataFrame, y_col: str) -> dict:
    train = df[df["date"] < OOS_START].copy()
    test = df[df["date"] >= OOS_START].copy()

    baseline_features = ["vix_z_lag1", "rv22_z_lag1", "momentum22_lag1"]
    augmentations = {
        "baseline": [],
        "stock_liquidity": ["stock_liquidity_stress_lag1"],
        "option_tail": ["option_tail_stress_lag1"],
        "combined_proxy": ["option_liquidity_proxy_lag1"],
    }

    out = {
        "event_rate_train": float(train[y_col].mean()),
        "event_rate_oos": float(test[y_col].mean()),
        "n_train": int(len(train)),
        "n_oos": int(len(test)),
        "models": {},
    }
    baseline_train_ll = None
    baseline_k = None
    baseline_auc = None
    baseline_brier = None

    for name, extra in augmentations.items():
        features = baseline_features + extra
        fit = fit_glm(train, y_col, features)
        pred = np.asarray(fit.predict(sm.add_constant(test[features], has_constant="add")))
        pred = np.clip(pred, 1e-6, 1 - 1e-6)
        y = test[y_col].values.astype(int)
        ll = float(np.sum(y * np.log(pred) + (1 - y) * np.log(1 - pred)))
        auc = auc_score(y, pred)
        brier = float(np.mean((y - pred) ** 2))

        if name == "baseline":
            baseline_train_ll = float(fit.llf)
            baseline_k = len(fit.params)
            baseline_auc = auc
            baseline_brier = brier
            lr = None
            lr_p = None
            p_bonf = None
        else:
            lr = max(0.0, 2.0 * (float(fit.llf) - float(baseline_train_ll)))
            df_diff = len(fit.params) - int(baseline_k)
            lr_p = float(1 - stats.chi2.cdf(lr, df=df_diff))
            p_bonf = min(1.0, lr_p * 12.0)

        out["models"][name] = {
            "features": features,
            "oos_loglik": ll,
            "oos_auc": auc,
            "oos_brier": brier,
            "delta_auc_vs_baseline": None if name == "baseline" else float(auc - baseline_auc),
            "delta_brier_vs_baseline": None if name == "baseline" else float(brier - baseline_brier),
            "train_lr_stat_vs_baseline": lr,
            "train_lr_p_vs_baseline": lr_p,
            "train_lr_p_bonferroni_12": p_bonf,
            "coef_train": {k: float(v) for k, v in fit.params.items()},
            "pvalues_train": {k: float(v) for k, v in fit.pvalues.items()},
            "top_decile_lift": moving_block_ci(y, pred),
        }
    return out


def make_figure(results: dict) -> None:
    targets = list(results["targets"].keys())
    models = ["baseline", "stock_liquidity", "option_tail", "combined_proxy"]
    labels = ["Baseline", "Stock liq", "Option tail", "Combined"]
    colors = ["#333333", "#4C78A8", "#F58518", "#54A24B"]

    x = np.arange(len(targets))
    width = 0.18
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    for i, (model, label, color) in enumerate(zip(models, labels, colors)):
        aucs = [results["targets"][t]["models"][model]["oos_auc"] for t in targets]
        ax.bar(x + (i - 1.5) * width, aucs, width=width, label=label, color=color)
    ax.axhline(0.5, color="black", linewidth=1, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels(targets, rotation=15, ha="right")
    ax.set_ylabel("OOS AUC")
    ax.set_title("K1498: OOS crash-risk classification")
    ax.legend(frameon=False, ncol=4)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=170, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    df = load_panel()
    target_cols = ["crash_1d", "crash_5d", "rv_jump_1d", "rv_jump_5d"]
    targets = {target: evaluate_target(df, target) for target in target_cols}

    bonf_passes = []
    for target, res in targets.items():
        for model in ["stock_liquidity", "option_tail", "combined_proxy"]:
            m = res["models"][model]
            if (
                m["train_lr_p_bonferroni_12"] is not None
                and m["train_lr_p_bonferroni_12"] < 0.05
                and m["delta_auc_vs_baseline"] is not None
                and m["delta_auc_vs_baseline"] > 0
                and m["delta_brier_vs_baseline"] is not None
                and m["delta_brier_vs_baseline"] < 0
            ):
                bonf_passes.append({"target": target, "model": model})

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Option-liquidity crash-risk proxy without option microstructure",
        "timestamp": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data": {
            "spy_vix_path": str(SPY_VIX_PATH.relative_to(REPO)),
            "cached_yfinance_files": [
                str((DATA_DIR / "skew_2012_2026.csv").relative_to(REPO)),
                str((DATA_DIR / "vvix_2012_2026.csv").relative_to(REPO)),
            ],
            "sample_start": str(df["date"].min().date()),
            "sample_end": str(df["date"].max().date()),
            "n_obs": int(len(df)),
            "oos_start": str(OOS_START.date()),
        },
        "references": [
            "Deng, Nguyen, Gebka (2026), European Journal of Finance, option market liquidity and stock price crash risk",
            "Christoffersen, Feunou, Jeon, Ornthanalai (2021), Review of Finance, time-varying crash risk and market liquidity",
            "Chang, Chen, Zolotoy (2017), JFQA, stock liquidity and stock price crash risk",
            "Amihud (2002), Journal of Financial Markets; Corwin and Schultz (2012), Journal of Finance",
        ],
        "lookahead_policy": "All model predictors use raw_signal.shift(1); targets are same-day or forward-window events indexed after the signal date.",
        "targets": targets,
        "summary": {
            "bonferroni_auc_brier_passes": bonf_passes,
            "n_bonferroni_auc_brier_passes": len(bonf_passes),
        },
        "verdict": "PASS" if bonf_passes else "NULL",
        "conclusion": (
            "The free-data option-liquidity proxy does not robustly improve crash-risk "
            "classification after VIX, realized variance, and momentum controls."
            if not bonf_passes
            else "At least one proxy-target pair improves OOS classification after multiple-testing control."
        ),
        "limitations": [
            "No direct option bid-ask, depth, or volume data.",
            "SKEW and VVIX are option-implied tail/fear proxies, not liquidity measures.",
            "Daily OHLCV liquidity proxies may miss intraday market-making stress.",
            "Rare crash targets make confidence intervals essential.",
        ],
    }
    make_figure(results)
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))
    for target in target_cols:
        base = results["targets"][target]["models"]["baseline"]["oos_auc"]
        combo = results["targets"][target]["models"]["combined_proxy"]["oos_auc"]
        print(f"{target}: baseline_auc={base:.3f} combined_auc={combo:.3f}")


if __name__ == "__main__":
    main()
