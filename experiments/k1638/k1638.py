#!/usr/bin/env python3
"""K1638: Distributional scoring audit for existing OOS volatility forecasts.

This experiment upgrades evaluation, not data collection.  It discovers a
curated set of byte-traceable OOS forecast CSV artifacts already in the repo,
wraps point variance forecasts into calibrated lognormal predictive
distributions, and evaluates them by CRPS, pinball loss, empirical coverage,
and a lightweight Hansen-Lunde-Nason-style MCS procedure.

Important scope limitation: this is a coverage-limited audit of available OOS
forecast rows, not a full re-ranking of all 1400+ K experiments.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / "k1638_results.json"

SEED = 42
RNG = np.random.default_rng(SEED)
EPS = 1e-12
PRIMARY_MIN_EVAL = 252
DIAGNOSTIC_MIN_EVAL = 40
CAL_MIN = 80
MCS_ALPHA = 0.10
MCS_BOOT = 500
MCS_BLOCK = 10
PINBALL_LEVELS = np.array([0.05, 0.25, 0.50, 0.75, 0.95])
CRPS_GRID_N = 129


@dataclass
class PanelSpec:
    panel_id: str
    path: str
    actual_col: str
    forecast_cols: list[str]
    group_cols: list[str] | None = None
    date_col: str = "date"
    source_k: str = ""
    note: str = ""


PANEL_SPECS = [
    PanelSpec(
        panel_id="K1637_daily_r2_by_asset",
        path="experiments/k1637/data/pooled_oos_forecasts.csv",
        actual_col="actual",
        forecast_cols=["CONST", "EWMA_094", "HAR", "FIGARCH_lite", "MS_vol_lite", "MSM_GMM"],
        group_cols=["asset"],
        source_k="K1637",
        note="daily close-to-close r^2 forecasts",
    ),
    PanelSpec(
        panel_id="K1613_taifex_noise_robust_rv",
        path="experiments/K1613/data/TAIFEX_TX_day_K1100h_oos_forecasts.csv",
        actual_col="actual_rv",
        forecast_cols=[
            "HAR_RV_forecast",
            "HAR_MedRV_input_forecast",
            "HAR_RK_input_forecast",
            "HAR_TSRV_input_forecast",
        ],
        source_k="K1613",
        note="TAIFEX 5-min RV input-measure comparison",
    ),
    PanelSpec(
        panel_id="K1582_tx_active_harq",
        path="experiments/k1582/data/TX_active_oos_forecasts.csv",
        actual_col="actual_rv",
        forecast_cols=["HAR_forecast", "HARQ_forecast", "HARQ_full_forecast", "SHARK_like_forecast"],
        source_k="K1582",
        note="TAIFEX HARQ/SHARK measurement-error comparison",
    ),
    PanelSpec(
        panel_id="K1582_spy_harq_short",
        path="experiments/k1582/data/SPY_oos_forecasts.csv",
        actual_col="actual_rv",
        forecast_cols=["HAR_forecast", "HARQ_forecast", "HARQ_full_forecast", "SHARK_like_forecast"],
        source_k="K1582",
        note="SPY short 5-min diagnostic, expected underpowered",
    ),
    PanelSpec(
        panel_id="K1582_0050_harq_short",
        path="experiments/k1582/data/0050_TW_oos_forecasts.csv",
        actual_col="actual_rv",
        forecast_cols=["HAR_forecast", "HARQ_forecast", "HARQ_full_forecast", "SHARK_like_forecast"],
        source_k="K1582",
        note="0050.TW short 5-min diagnostic, expected underpowered",
    ),
    PanelSpec(
        panel_id="K1601_agreed_disagreed_uncertainty_21d",
        path="experiments/k1601/data/k1601_oos_forecasts.csv",
        actual_col="actual_rv_21",
        forecast_cols=["VIX_forecast", "VIX_SPF_forecast", "VIX_SPF_JLN_forecast", "JLN_SPF_forecast"],
        source_k="K1601",
        note="21d forward RV forecasts",
    ),
    PanelSpec(
        panel_id="K1349_intraday_rv_short",
        path="experiments/k1349/K1349_oos_forecasts_intraday_rv.csv",
        actual_col="actual",
        forecast_cols=["expanding_mean", "rv_lag1", "ar1_logrv", "har_logrv", "har_bpv"],
        source_k="K1349",
        note="short intraday RV diagnostic",
    ),
    PanelSpec(
        panel_id="K1349_total_rv_short",
        path="experiments/k1349/K1349_oos_forecasts_total_rv.csv",
        actual_col="actual",
        forecast_cols=["expanding_mean", "rv_lag1", "ar1_logrv", "har_logrv", "har_bpv"],
        source_k="K1349",
        note="short total RV diagnostic",
    ),
    PanelSpec(
        panel_id="research_data_driven_vc_screening",
        path="experiments/research_data_driven_vc_screening_shock_public_innovation/data/oos_predictions.csv",
        actual_col="actual_var",
        forecast_cols=["pred_baseline", "pred_augmented"],
        group_cols=["ticker", "horizon"],
        source_k="research_data_driven_vc_screening_shock_public_innovation",
        note="public innovation ETF 5d/21d variance forecasts",
    ),
    PanelSpec(
        panel_id="research_intraday_har_vs_seasonal",
        path="experiments/research_intraday_garch_vs_har_rv_rv/research_intraday_garch_vs_har_rv_rv_oos_forecasts.csv",
        actual_col="actual_rv",
        forecast_cols=["har_pred", "seasonal_pred"],
        date_col="target_date",
        source_k="research_intraday_garch_vs_har_rv_rv",
        note="short intraday HAR vs seasonal diagnostic",
    ),
]


def _jsonify(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, tuple):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        if not np.isfinite(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    return obj


def pinball(y: np.ndarray, q: np.ndarray, alpha: float) -> np.ndarray:
    e = y - q
    return np.maximum(alpha * e, (alpha - 1.0) * e)


def lognormal_base_quantiles(sigma: float, n: int = CRPS_GRID_N) -> np.ndarray:
    u = (np.arange(1, n + 1) - 0.5) / n
    z = stats.norm.ppf(u)
    # Mean-one lognormal base: X = mu * base, E[base] = 1.
    return np.exp(sigma * z - 0.5 * sigma * sigma)


def crps_lognormal_mean_mu(y: np.ndarray, mu: np.ndarray, sigma: float) -> np.ndarray:
    base = lognormal_base_quantiles(sigma)
    pair_term = 0.5 * np.mean(np.abs(base[:, None] - base[None, :]))
    ratio = y / np.clip(mu, EPS, None)
    e_abs = np.mean(np.abs(base[None, :] - ratio[:, None]), axis=1)
    return np.clip(mu, EPS, None) * (e_abs - pair_term)


def interval_score(y: np.ndarray, lo: np.ndarray, hi: np.ndarray, alpha: float = 0.10) -> np.ndarray:
    width = hi - lo
    below = y < lo
    above = y > hi
    return width + (2.0 / alpha) * (lo - y) * below + (2.0 / alpha) * (y - hi) * above


def calibrate_sigma(actual: np.ndarray, pred: np.ndarray) -> float:
    mask = np.isfinite(actual) & np.isfinite(pred) & (actual > 0) & (pred > 0)
    ratio = np.log(np.clip(actual[mask], EPS, None) / np.clip(pred[mask], EPS, None))
    if len(ratio) < 20:
        return float("nan")
    lo, hi = np.nanquantile(ratio, [0.05, 0.95])
    ratio = np.clip(ratio, lo, hi)
    sigma = float(np.nanstd(ratio, ddof=1))
    return float(np.clip(sigma, 0.15, 2.50))


def score_panel(df: pd.DataFrame, spec: PanelSpec, panel_suffix: str = "") -> dict | None:
    needed = [spec.actual_col, *spec.forecast_cols]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        return {
            "panel_id": spec.panel_id + panel_suffix,
            "status": "skipped_missing_columns",
            "missing": missing,
            "path": spec.path,
        }
    use = df.copy()
    use[spec.date_col] = pd.to_datetime(use[spec.date_col], errors="coerce")
    cols = [spec.date_col, spec.actual_col, *spec.forecast_cols]
    use = use[cols].copy()
    for c in [spec.actual_col, *spec.forecast_cols]:
        use[c] = pd.to_numeric(use[c], errors="coerce")
    use = use.replace([np.inf, -np.inf], np.nan).dropna()
    use = use[(use[spec.actual_col] > 0)]
    for c in spec.forecast_cols:
        use = use[use[c] > 0]
    use = use.sort_values(spec.date_col).reset_index(drop=True)
    n_total = len(use)
    if n_total < DIAGNOSTIC_MIN_EVAL * 2:
        return {
            "panel_id": spec.panel_id + panel_suffix,
            "status": "skipped_too_short",
            "n_total": int(n_total),
            "path": spec.path,
        }

    cal_n = min(max(CAL_MIN, int(0.25 * n_total)), n_total // 2)
    eval_df = use.iloc[cal_n:].copy()
    calib_df = use.iloc[:cal_n].copy()
    n_eval = len(eval_df)
    scale = float(np.nanmedian(eval_df[spec.actual_col].values))
    if not np.isfinite(scale) or scale <= 0:
        scale = float(np.nanmean(eval_df[spec.actual_col].values))
    scale = max(scale, EPS)
    panel_kind = "primary" if n_eval >= PRIMARY_MIN_EVAL else "diagnostic"

    y_cal = calib_df[spec.actual_col].to_numpy(float)
    y_eval = eval_df[spec.actual_col].to_numpy(float)
    scores = {}
    row_losses = pd.DataFrame({spec.date_col: eval_df[spec.date_col]})
    row_losses["actual"] = y_eval
    for model in spec.forecast_cols:
        pred_cal = calib_df[model].to_numpy(float)
        pred_eval = eval_df[model].to_numpy(float)
        sigma = calibrate_sigma(y_cal, pred_cal)
        if not np.isfinite(sigma):
            continue
        crps = crps_lognormal_mean_mu(y_eval, pred_eval, sigma)
        quantiles = {}
        pin_losses = []
        for a in PINBALL_LEVELS:
            q = pred_eval * np.exp(sigma * stats.norm.ppf(a) - 0.5 * sigma * sigma)
            quantiles[str(a)] = q
            pin_losses.append(pinball(y_eval, q, float(a)))
        avg_pin = np.mean(np.vstack(pin_losses), axis=0)
        q05 = quantiles["0.05"]
        q95 = quantiles["0.95"]
        covered = (y_eval >= q05) & (y_eval <= q95)
        iscore = interval_score(y_eval, q05, q95, alpha=0.10)
        scores[model] = {
            "sigma_log_calibrated": sigma,
            "mean_crps": float(np.nanmean(crps)),
            "mean_crps_scaled": float(np.nanmean(crps / scale)),
            "mean_pinball": float(np.nanmean(avg_pin)),
            "mean_pinball_scaled": float(np.nanmean(avg_pin / scale)),
            "coverage_90": float(np.nanmean(covered)),
            "coverage_error_90_abs": float(abs(np.nanmean(covered) - 0.90)),
            "mean_interval_score_scaled": float(np.nanmean(iscore / scale)),
        }
        row_losses[f"crps__{model}"] = crps / scale
        row_losses[f"pinball__{model}"] = avg_pin / scale

    if len(scores) < 2:
        return {
            "panel_id": spec.panel_id + panel_suffix,
            "status": "skipped_less_than_two_scored_models",
            "n_total": int(n_total),
            "path": spec.path,
        }

    mcs_crps = mcs_range(row_losses[[f"crps__{m}" for m in scores]].to_numpy(float), list(scores), alpha=MCS_ALPHA)
    mcs_pinball = mcs_range(row_losses[[f"pinball__{m}" for m in scores]].to_numpy(float), list(scores), alpha=MCS_ALPHA)
    best_crps = min(scores, key=lambda m: scores[m]["mean_crps_scaled"])
    best_pinball = min(scores, key=lambda m: scores[m]["mean_pinball_scaled"])
    best_coverage = min(scores, key=lambda m: scores[m]["coverage_error_90_abs"])
    out_name = safe_name(spec.panel_id + panel_suffix) + "_distribution_scores.csv"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    row_losses.to_csv(DATA_DIR / out_name, index=False)
    return {
        "panel_id": spec.panel_id + panel_suffix,
        "source_k": spec.source_k,
        "path": spec.path,
        "note": spec.note,
        "status": "scored",
        "kind": panel_kind,
        "n_total": int(n_total),
        "n_calibration": int(cal_n),
        "n_eval": int(n_eval),
        "eval_start": str(eval_df[spec.date_col].min().date()),
        "eval_end": str(eval_df[spec.date_col].max().date()),
        "actual_scale_median": scale,
        "models": scores,
        "best_by_crps": best_crps,
        "best_by_pinball": best_pinball,
        "best_by_coverage_error": best_coverage,
        "mcs_crps_alpha10": mcs_crps,
        "mcs_pinball_alpha10": mcs_pinball,
        "row_loss_file": str((DATA_DIR / out_name).relative_to(HERE)),
    }


def mcs_range(loss_matrix: np.ndarray, model_names: list[str], alpha: float = MCS_ALPHA) -> dict:
    """Lightweight MCS range test using moving-block bootstrap.

    Lower loss is better. The procedure removes the current worst average-loss
    model while the range statistic rejects equal predictive ability.
    """
    L = np.asarray(loss_matrix, dtype=float)
    mask = np.all(np.isfinite(L), axis=1)
    L = L[mask]
    active = list(range(L.shape[1]))
    elimination = []
    if L.shape[0] < DIAGNOSTIC_MIN_EVAL or L.shape[1] < 2:
        return {"status": "skipped", "reason": "too_few_rows_or_models", "included": model_names}

    while len(active) > 1:
        sub = L[:, active]
        means = np.nanmean(sub, axis=0)
        centered = sub - means
        se = np.nanstd(sub, axis=0, ddof=1) / math.sqrt(len(sub))
        se = np.where(se <= 1e-12, 1e-12, se)
        obs = float(np.max((means - np.min(means)) / se))
        boot_stats = []
        n = len(sub)
        for _ in range(MCS_BOOT):
            idx = moving_block_indices(n, MCS_BLOCK)
            bmean = np.nanmean(centered[idx], axis=0)
            boot_stats.append(float(np.max((bmean - np.min(bmean)) / se)))
        p_value = float(np.mean(np.asarray(boot_stats) >= obs))
        worst_pos = int(np.argmax(means))
        worst_model = model_names[active[worst_pos]]
        elimination.append({
            "active_models": [model_names[i] for i in active],
            "worst_model": worst_model,
            "obs_range_t": obs,
            "p_value": p_value,
        })
        if p_value < alpha:
            active.pop(worst_pos)
        else:
            break
    return {
        "status": "ok",
        "alpha": alpha,
        "bootstrap": MCS_BOOT,
        "block": MCS_BLOCK,
        "included": [model_names[i] for i in active],
        "elimination_path": elimination,
    }


def moving_block_indices(n: int, block: int) -> np.ndarray:
    starts = RNG.integers(0, n, size=math.ceil(n / block))
    chunks = []
    for s in starts:
        chunks.extend([(s + j) % n for j in range(block)])
    return np.asarray(chunks[:n], dtype=int)


def safe_name(x: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in x)


def load_panels() -> tuple[list[dict], list[dict]]:
    scored = []
    skipped = []
    for spec in PANEL_SPECS:
        path = ROOT / spec.path
        if not path.exists():
            skipped.append({"panel_id": spec.panel_id, "status": "missing_file", "path": spec.path})
            continue
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            skipped.append({"panel_id": spec.panel_id, "status": "read_error", "path": spec.path, "error": repr(exc)})
            continue
        if spec.group_cols:
            missing_group = [g for g in spec.group_cols if g not in df.columns]
            if missing_group:
                skipped.append({"panel_id": spec.panel_id, "status": "missing_group_columns", "missing": missing_group})
                continue
            for key, gdf in df.groupby(spec.group_cols, dropna=False):
                key_tuple = key if isinstance(key, tuple) else (key,)
                suffix = "__" + "__".join(str(k) for k in key_tuple)
                result = score_panel(gdf, spec, suffix)
                (scored if result and result.get("status") == "scored" else skipped).append(result)
        else:
            result = score_panel(df, spec)
            (scored if result and result.get("status") == "scored" else skipped).append(result)
    return scored, skipped


def aggregate_results(panels: list[dict]) -> dict:
    primary = [p for p in panels if p["kind"] == "primary"]
    diagnostic = [p for p in panels if p["kind"] == "diagnostic"]
    rows = []
    for p in panels:
        for model, m in p["models"].items():
            rows.append({
                "panel_id": p["panel_id"],
                "kind": p["kind"],
                "model": model,
                "mean_crps_scaled": m["mean_crps_scaled"],
                "mean_pinball_scaled": m["mean_pinball_scaled"],
                "coverage_error_90_abs": m["coverage_error_90_abs"],
                "in_mcs_crps": model in p["mcs_crps_alpha10"]["included"],
                "in_mcs_pinball": model in p["mcs_pinball_alpha10"]["included"],
                "is_best_crps": model == p["best_by_crps"],
                "is_best_pinball": model == p["best_by_pinball"],
                "is_best_coverage": model == p["best_by_coverage_error"],
            })
    table = pd.DataFrame(rows)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(DATA_DIR / "k1638_model_score_table.csv", index=False)
    if table.empty:
        return {}
    primary_table = table[table["kind"] == "primary"].copy()
    summary = {
        "n_scored_panels": int(len(panels)),
        "n_primary_panels": int(len(primary)),
        "n_diagnostic_panels": int(len(diagnostic)),
        "primary_best_crps_counts": primary_table[primary_table["is_best_crps"]]["model"].value_counts().to_dict(),
        "primary_best_pinball_counts": primary_table[primary_table["is_best_pinball"]]["model"].value_counts().to_dict(),
        "primary_mcs_crps_inclusion_counts": primary_table[primary_table["in_mcs_crps"]]["model"].value_counts().to_dict(),
        "primary_mcs_pinball_inclusion_counts": primary_table[primary_table["in_mcs_pinball"]]["model"].value_counts().to_dict(),
        "score_table": str((DATA_DIR / "k1638_model_score_table.csv").relative_to(HERE)),
    }
    if len(primary) >= 3:
        summary["verdict"] = "CONDITIONAL_PASS_EVALUATION_LAYER_WORKS_COVERAGE_LIMITED"
    elif panels:
        summary["verdict"] = "DIAGNOSTIC_ONLY_INSUFFICIENT_PRIMARY_COVERAGE"
    else:
        summary["verdict"] = "FAIL_NO_SCOREABLE_FORECAST_ARTIFACTS"
    return summary


def plot_results(panels: list[dict], aggregate: dict) -> dict:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    primary = [p for p in panels if p["kind"] == "primary"]
    sorted_panels = sorted(primary, key=lambda p: p["n_eval"], reverse=True)[:12]
    labels = [p["panel_id"].replace("_", "\n")[:28] for p in sorted_panels]
    vals = [p["models"][p["best_by_crps"]]["mean_crps_scaled"] for p in sorted_panels]
    winners = [p["best_by_crps"] for p in sorted_panels]
    fig, ax = plt.subplots(figsize=(12, 6), dpi=140)
    ax.bar(range(len(vals)), vals, color="#4C78A8")
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("Best scaled CRPS (lower is better)")
    ax.set_title("K1638 primary panels: best distributional score by panel")
    for i, w in enumerate(winners):
        ax.text(i, vals[i], w[:16], rotation=90, va="bottom", ha="center", fontsize=7)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p1 = FIG_DIR / "k1638_best_crps_by_panel.png"
    fig.savefig(p1)
    plt.close(fig)

    counts = aggregate.get("primary_best_crps_counts", {})
    fig, ax = plt.subplots(figsize=(9, 5), dpi=140)
    names = list(counts.keys())
    values = [counts[n] for n in names]
    ax.bar(names, values, color="#54A24B")
    ax.set_ylabel("Primary panels won by CRPS")
    ax.set_title("K1638 CRPS winners across scoreable primary panels")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p2 = FIG_DIR / "k1638_crps_winner_counts.png"
    fig.savefig(p2)
    plt.close(fig)
    return {
        "best_crps_by_panel": str(p1.relative_to(HERE)),
        "crps_winner_counts": str(p2.relative_to(HERE)),
    }


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    panels, skipped = load_panels()
    aggregate = aggregate_results(panels)
    figures = plot_results(panels, aggregate) if panels else {}
    results = {
        "experiment_id": "k1638",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "question": "Can existing point-volatility OOS artifacts be re-evaluated with CRPS, pinball loss, coverage, and MCS?",
        "scope": {
            "claim": "coverage-limited evaluation-layer audit, not full 1400+ K re-ranking",
            "panel_specs_declared": len(PANEL_SPECS),
            "scored_panels": len(panels),
            "skipped_or_insufficient_panels": len(skipped),
            "primary_min_eval": PRIMARY_MIN_EVAL,
            "diagnostic_min_eval": DIAGNOSTIC_MIN_EVAL,
        },
        "method": {
            "distribution_wrapper": "point variance forecast mu_t converted to mean-mu lognormal predictive distribution; sigma estimated on each panel/model calibration slice only",
            "calibration": "first max(80, 25%) rows capped at half sample; evaluation uses later rows only",
            "scores": ["CRPS", "mean pinball loss at 5/25/50/75/95%", "90% empirical coverage", "90% interval score"],
            "mcs": f"range-statistic MCS-lite, alpha={MCS_ALPHA}, moving-block bootstrap B={MCS_BOOT}, block={MCS_BLOCK}",
            "lookahead_policy": "No new forecasts are fit; distribution dispersion is calibrated only on pre-evaluation OOS rows.",
        },
        "aggregate": aggregate,
        "panels": panels,
        "skipped": skipped,
        "figures": figures,
        "honesty": {
            "limitations": [
                "Most historical K experiments do not store full predictive distributions or per-date loss rows.",
                "Lognormal wrapper is a transparent post-processing proxy; it does not turn point forecasts into native probabilistic models.",
                "Cross-panel aggregate rankings are descriptive because targets and horizons differ.",
                "Primary inference is per panel; global winner counts are a platform audit signal, not a universal model theorem.",
            ]
        },
    }
    RESULTS_PATH.write_text(json.dumps(_jsonify(results), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(_jsonify({
        "verdict": aggregate.get("verdict"),
        "scored_panels": len(panels),
        "primary_panels": aggregate.get("n_primary_panels"),
        "diagnostic_panels": aggregate.get("n_diagnostic_panels"),
        "primary_best_crps_counts": aggregate.get("primary_best_crps_counts"),
    }), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
