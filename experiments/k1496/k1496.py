#!/usr/bin/env python3
"""K1496 — HAR-RV window-length regime dependence on TAIFEX TX1.

Primary question:
  Does the optimal HAR-style realized-volatility window shorten in high-volatility
  regimes and lengthen in low-volatility regimes?

Design choices:
  - Target is true 5-minute realized variance from the local TAIFEX daily panel.
  - Forecast family isolates the window-length question:
        log(RV_t) = a + b1*log(RV_{t-1}) + bw*mean(log(RV_{t-w:t-1}))
  - Regimes are defined with expanding tertiles on lagged 22-day mean RV.
  - No full-sample thresholding, no same-day leakage.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.regression.rolling import RollingOLS

SEED = 42
RNG = np.random.default_rng(SEED)
EPS = 1e-12
WINDOWS = [5, 10, 22, 63]
PRIMARY_TRAIN = 1000
REGIME_WARMUP = 252
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE_PARQUET = ROOT / "experiments" / "k1303" / "data" / "_tx1_daily_cj_2017-2026.parquet"
OUT_JSON = HERE / "k1496_results.json"
FIG_PRIMARY = HERE / "k1496_primary_regime_qlike.png"
FIG_ROBUST = HERE / "k1496_robustness_heatmap.png"


@dataclass(frozen=True)
class Scheme:
    name: str
    kind: str
    train_window: int


SCHEMES = [
    Scheme("rolling_504", "rolling", 504),
    Scheme("rolling_1000", "rolling", 1000),
    Scheme("rolling_1500", "rolling", 1500),
    Scheme("expanding_1000", "expanding", 1000),
]


def git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def qlike(actual: pd.Series, predicted: pd.Series) -> pd.Series:
    a = actual.clip(lower=EPS).astype(float)
    f = predicted.clip(lower=EPS).astype(float)
    ratio = a / f
    return ratio - np.log(ratio) - 1.0


def load_tx1_daily_rv() -> pd.DataFrame:
    df = pd.read_parquet(SOURCE_PARQUET).copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["log_rv"] = np.log(df["rv"].clip(lower=EPS))
    return df[["date", "rv", "log_rv", "n_bars"]]


def build_window_panel(df: pd.DataFrame, window: int) -> pd.DataFrame:
    out = df[["date", "rv", "log_rv"]].copy()
    out["lag1"] = out["log_rv"].shift(1)
    out[f"avg_{window}"] = out["log_rv"].shift(1).rolling(window, min_periods=window).mean()
    return out.dropna().reset_index(drop=True)


def forecast_scheme(df: pd.DataFrame, window: int, scheme: Scheme) -> pd.DataFrame:
    panel = build_window_panel(df, window)
    X = pd.concat(
        [
            pd.Series(1.0, index=panel.index, name="const"),
            panel[["lag1", f"avg_{window}"]],
        ],
        axis=1,
    )
    y = panel["log_rv"]

    if scheme.kind == "rolling":
        fitted = RollingOLS(y, X, window=scheme.train_window).fit(params_only=True)
        params = fitted.params.shift(1)
        log_pred = (params * X).sum(axis=1)
        valid = params.notna().all(axis=1)
    elif scheme.kind == "expanding":
        preds = pd.Series(np.nan, index=panel.index, dtype=float)
        valid = pd.Series(False, index=panel.index)
        for i in range(scheme.train_window, len(panel)):
            x_train = X.iloc[:i].to_numpy()
            y_train = y.iloc[:i].to_numpy()
            beta = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
            preds.iloc[i] = float(X.iloc[i].to_numpy() @ beta)
            valid.iloc[i] = True
        log_pred = preds
    else:
        raise ValueError(f"unknown scheme kind: {scheme.kind}")

    out = panel.loc[valid, ["date", "rv"]].copy()
    out["pred"] = np.exp(np.clip(log_pred.loc[valid], -30, 10))
    out["qlike"] = qlike(out["rv"], out["pred"])
    out["window"] = window
    out["scheme"] = scheme.name
    return out.reset_index(drop=True)


def assign_expanding_rv_regimes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["lag_rv22"] = out["rv"].shift(1).rolling(22, min_periods=22).mean()
    regimes: list[str] = []
    q1s: list[float | None] = []
    q2s: list[float | None] = []
    for i, value in enumerate(out["lag_rv22"]):
        if i < REGIME_WARMUP or not np.isfinite(value):
            regimes.append("warmup")
            q1s.append(None)
            q2s.append(None)
            continue
        hist = out["lag_rv22"].iloc[:i].dropna()
        q1 = float(hist.quantile(1 / 3))
        q2 = float(hist.quantile(2 / 3))
        q1s.append(q1)
        q2s.append(q2)
        if value <= q1:
            regimes.append("low")
        elif value >= q2:
            regimes.append("high")
        else:
            regimes.append("mid")
    out["regime"] = regimes
    out["q1_cutoff"] = q1s
    out["q2_cutoff"] = q2s
    return out


def merge_scheme_outputs(df: pd.DataFrame, scheme: Scheme, regime_df: pd.DataFrame) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for window in WINDOWS:
        one = forecast_scheme(df, window, scheme)[["date", "rv", "pred", "qlike"]].rename(
            columns={"pred": f"pred_{window}", "qlike": f"qlike_{window}"}
        )
        merged = one if merged is None else merged.merge(one.drop(columns="rv"), on="date", how="inner")
    assert merged is not None
    merged = merged.merge(
        regime_df[["date", "regime", "lag_rv22", "q1_cutoff", "q2_cutoff"]],
        on="date",
        how="left",
    )
    return merged[merged["regime"] != "warmup"].reset_index(drop=True)


def mean_qlike_table(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for regime in ["low", "mid", "high"]:
        sub = df[df["regime"] == regime]
        out[regime] = {str(w): float(sub[f"qlike_{w}"].mean()) for w in WINDOWS}
    out["overall"] = {str(w): float(df[f"qlike_{w}"].mean()) for w in WINDOWS}
    return out


def best_window_by_regime(mean_table: dict[str, dict[str, float]]) -> dict[str, int]:
    out = {}
    for regime in ["low", "mid", "high", "overall"]:
        items = mean_table[regime]
        out[regime] = int(min(items, key=items.get))
    return out


def win_share_table(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    row_best = df[[f"qlike_{w}" for w in WINDOWS]].idxmin(axis=1).str.replace("qlike_", "", regex=False)
    tmp = df[["regime"]].copy()
    tmp["best_window"] = row_best
    for regime in ["low", "mid", "high"]:
        sub = tmp[tmp["regime"] == regime]
        shares = {}
        for w in WINDOWS:
            shares[str(w)] = float((sub["best_window"] == str(w)).mean())
        out[regime] = shares
    return out


def circular_block_bootstrap_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    idx: list[int] = []
    while len(idx) < n:
        start = int(rng.integers(0, n))
        idx.extend(((start + j) % n) for j in range(block))
    return np.asarray(idx[:n], dtype=int)


def bootstrap_pair_diffs(df: pd.DataFrame, left: int, right: int) -> dict[str, dict[str, float | list[float]]]:
    diff_col = f"diff_{left}_{right}"
    base = df.copy()
    base[diff_col] = base[f"qlike_{left}"] - base[f"qlike_{right}"]
    out: dict[str, dict[str, float | list[float]]] = {}
    n = len(base)
    for regime in ["low", "mid", "high"]:
        point = float(base.loc[base["regime"] == regime, diff_col].mean())
        reps: list[float] = []
        for _ in range(BOOTSTRAP_REPS):
            idx = circular_block_bootstrap_indices(n, BOOTSTRAP_BLOCK, RNG)
            sample = base.iloc[idx]
            sub = sample[sample["regime"] == regime][diff_col]
            if not sub.empty:
                reps.append(float(sub.mean()))
        arr = np.asarray(reps, dtype=float)
        out[regime] = {
            "point_estimate": point,
            "bootstrap_ci95": [float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975))],
            "bootstrap_median": float(np.quantile(arr, 0.50)),
            "prob_left_better": float(np.mean(arr < 0)),
            "n_reps": int(arr.size),
        }
    return out


def run_split_half_rule(df: pd.DataFrame) -> dict:
    half = len(df) // 2
    select = df.iloc[:half].copy()
    test = df.iloc[half:].copy()

    learned_rule: dict[str, int] = {}
    for regime in ["low", "mid", "high"]:
        regime_means = {w: float(select.loc[select["regime"] == regime, f"qlike_{w}"].mean()) for w in WINDOWS}
        learned_rule[regime] = int(min(regime_means, key=regime_means.get))

    for part in (select, test):
        part["qlike_rule"] = [
            row[f"qlike_{learned_rule[row.regime]}"]
            for _, row in part.iterrows()
        ]

    return {
        "learned_rule": learned_rule,
        "selection_mean_qlike": {
            "adaptive": float(select["qlike_rule"].mean()),
            **{str(w): float(select[f"qlike_{w}"].mean()) for w in WINDOWS},
        },
        "test_mean_qlike": {
            "adaptive": float(test["qlike_rule"].mean()),
            **{str(w): float(test[f"qlike_{w}"].mean()) for w in WINDOWS},
        },
    }


def plot_primary(mean_table: dict[str, dict[str, float]]) -> None:
    regimes = ["low", "mid", "high"]
    xs = np.arange(len(regimes))
    width = 0.18
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, w in enumerate(WINDOWS):
        vals = [mean_table[r][str(w)] for r in regimes]
        ax.bar(xs + (i - 1.5) * width, vals, width=width, label=f"{w}d")
    ax.set_xticks(xs)
    ax.set_xticklabels(["Low", "Mid", "High"])
    ax.set_ylabel("Mean QLIKE")
    ax.set_title("K1496 Primary Spec: TAIFEX TX1 Mean QLIKE by Regime")
    ax.legend(title="Window")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_PRIMARY, dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_robustness(best_map: dict[str, dict[str, int]]) -> None:
    schemes = list(best_map.keys())
    regimes = ["low", "mid", "high"]
    mat = np.array([[best_map[s][r] for r in regimes] for s in schemes], dtype=float)
    fig, ax = plt.subplots(figsize=(6, 4))
    im = ax.imshow(mat, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(np.arange(len(regimes)))
    ax.set_xticklabels(["Low", "Mid", "High"])
    ax.set_yticks(np.arange(len(schemes)))
    ax.set_yticklabels(schemes)
    ax.set_title("K1496 Robustness: Best Window by Regime")
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(j, i, f"{int(mat[i, j])}d", ha="center", va="center", color="black")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Best window (days)")
    fig.tight_layout()
    fig.savefig(FIG_ROBUST, dpi=160, bbox_inches="tight")
    plt.close(fig)


def finite_or_none(obj):
    if isinstance(obj, dict):
        return {k: finite_or_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [finite_or_none(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        if not np.isfinite(obj):
            return None
        return float(obj)
    return obj


def main() -> None:
    daily = load_tx1_daily_rv()
    regime_daily = assign_expanding_rv_regimes(daily[["date", "rv"]].copy())
    primary_scheme = next(s for s in SCHEMES if s.name == "rolling_1000")
    primary = merge_scheme_outputs(daily, primary_scheme, regime_daily)
    primary_means = mean_qlike_table(primary)
    primary_best = best_window_by_regime(primary_means)
    primary_win_shares = win_share_table(primary)

    robustness = {}
    robustness_best = {}
    for scheme in SCHEMES:
        merged = merge_scheme_outputs(daily, scheme, regime_daily)
        means = mean_qlike_table(merged)
        robustness[scheme.name] = means
        robustness_best[scheme.name] = best_window_by_regime(means)

    bootstrap = {
        "5_vs_22": bootstrap_pair_diffs(primary, 5, 22),
        "22_vs_63": bootstrap_pair_diffs(primary, 22, 63),
        "5_vs_63": bootstrap_pair_diffs(primary, 5, 63),
    }
    split_half = run_split_half_rule(primary)

    plot_primary(primary_means)
    plot_robustness(robustness_best)

    robustness_high_all_5 = all(v["high"] == 5 for v in robustness_best.values())
    robustness_low_has_63 = sum(v["low"] == 63 for v in robustness_best.values())

    results = {
        "experiment_id": "K1496",
        "title": "HAR-RV window length vs regime on TAIFEX TX1",
        "task_id": "research_realized_variance_regime",
        "seed": SEED,
        "git_commit": git_rev(),
        "data": {
            "source": str(SOURCE_PARQUET.relative_to(ROOT)),
            "asset": "TAIFEX TX1 day session",
            "date_start": str(daily["date"].min().date()),
            "date_end": str(daily["date"].max().date()),
            "n_daily_rows": int(len(daily)),
            "rv_definition": "sum of 5-minute squared log returns over the day session",
            "n_bars_min": int(daily["n_bars"].min()),
            "n_bars_median": float(daily["n_bars"].median()),
            "n_bars_max": int(daily["n_bars"].max()),
        },
        "methodology": {
            "target": "true intraday realized variance (not daily squared-return proxy)",
            "model_family": "log-HAR-style two-scale model: lag1 + lagged rolling mean(window)",
            "candidate_windows": WINDOWS,
            "primary_scheme": primary_scheme.name,
            "regime_signal": "lagged 22-day mean RV",
            "regime_assignment": "expanding tertiles with 252-day warmup",
            "bootstrap_reps": BOOTSTRAP_REPS,
            "bootstrap_block": BOOTSTRAP_BLOCK,
        },
        "primary_results": {
            "n_oos_rows": int(len(primary)),
            "regime_counts": {reg: int((primary["regime"] == reg).sum()) for reg in ["low", "mid", "high"]},
            "mean_qlike": primary_means,
            "best_window": primary_best,
            "win_share": primary_win_shares,
        },
        "robustness": {
            "mean_qlike_by_scheme": robustness,
            "best_window_by_scheme": robustness_best,
            "summary": {
                "high_regime_best_5_in_all_schemes": robustness_high_all_5,
                "low_regime_best_63_count": robustness_low_has_63,
            },
        },
        "bootstrap_loss_differences": bootstrap,
        "split_half_adaptive_rule_audit": split_half,
        "key_findings": [
            "High-volatility regimes robustly favor short HAR-RV memory windows; 5-day is best in all four estimation schemes.",
            "The primary rolling-1000 spec shows a tiny low-regime edge for 63-day over 5/10/22-day windows, but that edge disappears in most robustness schemes.",
            "Mid-regime performance also leans short: 5-day beats 22-day and 63-day in the primary spec, with bootstrap evidence against 63-day.",
            "An ex-ante split-half adaptive rule (low->63, mid/high->5) does not materially beat fixed 5-day overall, so low-regime lengthening is not strong enough to justify a production rule yet.",
            "Conclusion: regime dependence exists mainly on the stress side. The defensible operational rule is 'avoid long windows in high-RV states'; the symmetric 'always lengthen in calm states' claim is not supported robustly.",
        ],
        "figures": {
            "primary_regime_qlike": str(FIG_PRIMARY.relative_to(ROOT)),
            "robustness_heatmap": str(FIG_ROBUST.relative_to(ROOT)),
        },
    }

    OUT_JSON.write_text(json.dumps(finite_or_none(results), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "ok": True,
        "experiment_id": "K1496",
        "results_path": str(OUT_JSON),
        "primary_best": primary_best,
        "high_regime_best_5_in_all_schemes": robustness_high_all_5,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
