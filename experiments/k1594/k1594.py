"""K1594: KOWCPI-lite conformal VaR under volatility clustering.

Task: research_kowcpi_kernel_optimally_weighted_conformal.

The original KOWCPI paper proposes kernel/RNW weighted conformal intervals for
dependent time series.  This experiment implements a finance-specific,
one-sided VaR version: kernel-weighted conformal lower-tail quantiles using only
past nonconformity/return observations and lagged market-state features.

This is intentionally named "KOWCPI-lite": it tests whether the mechanism is
useful for daily ETF VaR, not whether the full paper algorithm is replicated.
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
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from volpred.stats.model_evaluation import dm_test  # noqa: E402


EXPERIMENT_ID = "k1594"
TASK_ID = "research_kowcpi_kernel_optimally_weighted_conformal"
SEED = 1594

HERE = Path(__file__).resolve().parent
DATA_PATH = REPO_ROOT / "experiments/k1571/data_cache.parquet"
RESULT_PATH = HERE / "k1594_results.json"
FORECAST_PATH = HERE / "k1594_oos_var_forecasts.csv"
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)

ASSETS = ["TLT", "HYG"]
ALPHAS = [0.05, 0.01]
MODELS = ["HS250", "HS1000", "VIXRegime1000", "KOWCPI-lite"]
FEATURE_COLS = ["rv5", "rv22", "abs_ret", "vix", "credit_chg", "ief_mom", "lqd_mom"]

VALID_START = pd.Timestamp("2013-01-01")
VALID_END = pd.Timestamp("2014-12-31")
OOS_START = pd.Timestamp("2015-01-01")
OOS_END = pd.Timestamp("2026-06-30")
CAL_WINDOW = 1000
VIX_HIGH = 20.0
MIN_ESS = 125.0
BANDWIDTH_GRID = [0.35, 0.50, 0.75, 1.00, 1.50, 2.25, 3.50]


def safe_float(x) -> float | None:
    try:
        y = float(x)
    except (TypeError, ValueError):
        return None
    return y if np.isfinite(y) else None


def load_close() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing frozen data cache: {DATA_PATH}")
    close = pd.read_parquet(DATA_PATH).sort_index()
    close = close.dropna(how="any")
    return close


def build_panel(close: pd.DataFrame, asset: str) -> pd.DataFrame:
    logret = np.log(close).diff()
    y = logret[asset]
    own = y
    feats = pd.DataFrame(
        {
            "rv5": own.rolling(5).std() * np.sqrt(252),
            "rv22": own.rolling(22).std() * np.sqrt(252),
            "abs_ret": own.abs(),
            "vix": close["^VIX"] / 100.0,
            "credit_chg": (close["HYG"] / close["IEF"]).pct_change(5),
            "ief_mom": logret["IEF"].rolling(5).sum(),
            "lqd_mom": logret["LQD"].rolling(5).sum(),
        },
        index=close.index,
    ).shift(1)
    panel = pd.concat([y.rename("return"), feats], axis=1).dropna()
    panel.index.name = "date"
    # Defensive finite filter.
    cols = ["return", *FEATURE_COLS]
    panel = panel[np.isfinite(panel[cols]).all(axis=1)]
    return panel


def weighted_quantile(values: np.ndarray, weights: np.ndarray, alpha: float) -> float:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    valid = np.isfinite(values) & np.isfinite(weights) & (weights >= 0)
    values = values[valid]
    weights = weights[valid]
    if len(values) == 0 or weights.sum() <= 0:
        return float("nan")
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cum = np.cumsum(weights) / weights.sum()
    idx = min(np.searchsorted(cum, alpha, side="left"), len(values) - 1)
    return float(values[idx])


def pinball_pointwise(y: np.ndarray, q: np.ndarray, alpha: float) -> np.ndarray:
    e = y - q
    return np.where(e >= 0, alpha * e, (alpha - 1.0) * e)


def effective_sample_size(w: np.ndarray) -> float:
    s = w.sum()
    if s <= 0:
        return 0.0
    wn = w / s
    denom = float(np.sum(wn**2))
    return 0.0 if denom <= 0 else 1.0 / denom


def shrink_to_ess(raw_w: np.ndarray, min_ess: float) -> tuple[np.ndarray, float, float]:
    n = len(raw_w)
    if n == 0:
        return raw_w, 0.0, 1.0
    if raw_w.sum() <= 0 or not np.isfinite(raw_w).all():
        raw_w = np.ones(n, dtype=float)
    w = raw_w / raw_w.sum()
    ess0 = effective_sample_size(w)
    if ess0 >= min_ess:
        return w, ess0, 0.0
    uniform = np.ones(n, dtype=float) / n

    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        mixed = (1 - mid) * w + mid * uniform
        if effective_sample_size(mixed) >= min_ess:
            hi = mid
        else:
            lo = mid
    mixed = (1 - hi) * w + hi * uniform
    return mixed / mixed.sum(), effective_sample_size(mixed), hi


def kernel_var(
    hist_y: np.ndarray,
    hist_x: np.ndarray,
    x_t: np.ndarray,
    alpha: float,
    bandwidth: float,
    min_ess: float,
) -> tuple[float, float, float]:
    d2 = np.sum((hist_x - x_t.reshape(1, -1)) ** 2, axis=1)
    bw = max(float(bandwidth), 1e-6)
    raw_w = np.exp(-0.5 * d2 / (bw**2))
    w, ess, shrink = shrink_to_ess(raw_w, min_ess=min(min_ess, len(hist_y)))
    q = weighted_quantile(hist_y, w, alpha)
    return q, ess, shrink


def regime_var(hist_y: np.ndarray, hist_vix: np.ndarray, vix_t: float, alpha: float) -> float:
    regime = hist_vix > (VIX_HIGH / 100.0)
    want = vix_t > (VIX_HIGH / 100.0)
    sample = hist_y[regime == want]
    min_bucket = 150 if alpha >= 0.05 else 250
    if len(sample) < min_bucket:
        sample = hist_y
    return float(np.quantile(sample, alpha))


def historical_var(hist_y: np.ndarray, alpha: float, window: int) -> float:
    sample = hist_y[-window:]
    return float(np.quantile(sample, alpha))


@dataclass
class ForecastBlock:
    dates: list[str]
    returns: np.ndarray
    forecasts: dict[str, np.ndarray]
    ess: np.ndarray
    shrink: np.ndarray


def forecast_period(
    panel: pd.DataFrame,
    mask: np.ndarray,
    scaler: StandardScaler,
    alpha: float,
    bandwidth: float,
) -> ForecastBlock:
    x_all = scaler.transform(panel[FEATURE_COLS].to_numpy(dtype=float))
    y_all = panel["return"].to_numpy(dtype=float)
    vix_all = panel["vix"].to_numpy(dtype=float)
    idxs = np.where(mask)[0]
    out = {m: np.full(len(idxs), np.nan) for m in MODELS}
    ess = np.full(len(idxs), np.nan)
    shrink = np.full(len(idxs), np.nan)
    dates = []
    rets = np.full(len(idxs), np.nan)

    for j, pos in enumerate(idxs):
        start_250 = pos - 250
        start_1000 = pos - CAL_WINDOW
        if start_250 < 0 or start_1000 < 0:
            continue
        hist_y_250 = y_all[start_250:pos]
        hist_y = y_all[start_1000:pos]
        hist_x = x_all[start_1000:pos]
        hist_vix = vix_all[start_1000:pos]
        qk, e, s = kernel_var(hist_y, hist_x, x_all[pos], alpha, bandwidth, MIN_ESS)
        out["HS250"][j] = historical_var(hist_y_250, alpha, 250)
        out["HS1000"][j] = historical_var(hist_y, alpha, CAL_WINDOW)
        out["VIXRegime1000"][j] = regime_var(hist_y, hist_vix, vix_all[pos], alpha)
        out["KOWCPI-lite"][j] = qk
        ess[j] = e
        shrink[j] = s
        dates.append(str(panel.index[pos].date()))
        rets[j] = y_all[pos]

    valid = np.isfinite(rets)
    dates_full = [str(panel.index[pos].date()) for pos in idxs]
    return ForecastBlock(
        dates=[d for d, ok in zip(dates_full, valid) if ok],
        returns=rets[valid],
        forecasts={m: v[valid] for m, v in out.items()},
        ess=ess[valid],
        shrink=shrink[valid],
    )


def backtest_direct_var(y: np.ndarray, q: np.ndarray, alpha: float) -> dict:
    valid = np.isfinite(y) & np.isfinite(q)
    y = y[valid]
    q = q[valid]
    hits = (y < q).astype(int)
    n = len(hits)
    n1 = int(hits.sum())
    n0 = n - n1
    rate = n1 / n if n else float("nan")

    phat = rate
    eps = 1e-300
    ll_null = n1 * math.log(max(alpha, eps)) + n0 * math.log(max(1 - alpha, eps))
    if phat <= 0:
        ll_alt = n0 * math.log(1.0)
    elif phat >= 1:
        ll_alt = n1 * math.log(1.0)
    else:
        ll_alt = n1 * math.log(phat) + n0 * math.log(1 - phat)
    lr_uc = max(0.0, -2.0 * (ll_null - ll_alt))
    kupiec_p = float(1 - stats.chi2.cdf(lr_uc, df=1))

    n00 = int(((hits[:-1] == 0) & (hits[1:] == 0)).sum())
    n01 = int(((hits[:-1] == 0) & (hits[1:] == 1)).sum())
    n10 = int(((hits[:-1] == 1) & (hits[1:] == 0)).sum())
    n11 = int(((hits[:-1] == 1) & (hits[1:] == 1)).sum())
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)
    pi0 = n01 / max(n00 + n01, 1)
    pi1 = n11 / max(n10 + n11, 1)
    if 0 < pi < 1 and 0 < pi0 < 1 and 0 < pi1 < 1:
        ll0 = (n00 + n10) * math.log(1 - pi) + (n01 + n11) * math.log(pi)
        ll1 = (
            n00 * math.log(1 - pi0)
            + n01 * math.log(pi0)
            + n10 * math.log(1 - pi1)
            + n11 * math.log(pi1)
        )
        lr_ind = max(0.0, -2.0 * (ll0 - ll1))
        ind_p = float(1 - stats.chi2.cdf(lr_ind, df=1))
    else:
        lr_ind = 0.0
        ind_p = 1.0

    green_cutoff = int(stats.binom.ppf(0.95, n, alpha))
    yellow_cutoff = int(stats.binom.ppf(0.9999, n, alpha))
    traffic = "green" if n1 <= green_cutoff else "yellow" if n1 <= yellow_cutoff else "red"
    return {
        "n": int(n),
        "n_violations": int(n1),
        "violation_rate": safe_float(rate),
        "expected_rate": float(alpha),
        "kupiec_lr": safe_float(lr_uc),
        "kupiec_p": safe_float(kupiec_p),
        "christoffersen_ind_lr": safe_float(lr_ind),
        "christoffersen_ind_p": safe_float(ind_p),
        "basel_traffic_light": traffic,
        "basel_green_cutoff": int(green_cutoff),
        "basel_yellow_cutoff": int(yellow_cutoff),
        "trinity_pass": bool(kupiec_p > 0.05 and ind_p > 0.05 and traffic == "green"),
    }


def evaluate_block(block: ForecastBlock, alpha: float) -> tuple[dict, pd.DataFrame]:
    y = block.returns
    rows = []
    out = pd.DataFrame({"date": block.dates, "return": y})
    for model in MODELS:
        q = block.forecasts[model]
        loss = pinball_pointwise(y, q, alpha)
        out[f"var_{model}"] = q
        out[f"loss_{model}"] = loss
        bt = backtest_direct_var(y, q, alpha)
        rolling_rate = pd.Series((y < q).astype(float)).rolling(250).mean()
        rows.append(
            {
                "model": model,
                "mean_pinball": safe_float(loss.mean()),
                "sum_pinball": safe_float(loss.sum()),
                "mean_var_width": safe_float((-q).mean()),
                "rolling250_abs_coverage_error": safe_float((rolling_rate - alpha).abs().mean()),
                "backtest": bt,
            }
        )
    out["kowcpi_ess"] = block.ess
    out["kowcpi_shrink_to_uniform"] = block.shrink

    dm_pairs = {}
    for base in ["HS250", "HS1000", "VIXRegime1000"]:
        t, p = dm_test(out["loss_KOWCPI-lite"].to_numpy(), out[f"loss_{base}"].to_numpy(), h=1)
        dm_pairs[f"KOWCPI-lite_minus_{base}"] = {
            "t": safe_float(t),
            "p": safe_float(p),
            "interpretation": "kowcpi_lower_loss" if t < -3 else "kowcpi_higher_loss" if t > 3 else "equal_accuracy_not_rejected",
        }
    return {"models": rows, "dm_tests": dm_pairs}, out


def choose_bandwidth(panel: pd.DataFrame, scaler: StandardScaler, alpha: float) -> dict:
    val_mask = np.asarray((panel.index >= VALID_START) & (panel.index <= VALID_END), dtype=bool)
    choices = []
    for bw in BANDWIDTH_GRID:
        block = forecast_period(panel, val_mask, scaler, alpha, bw)
        if len(block.returns) < 100:
            continue
        eval_res, _ = evaluate_block(block, alpha)
        krow = next(r for r in eval_res["models"] if r["model"] == "KOWCPI-lite")
        rate = krow["backtest"]["violation_rate"]
        loss = krow["mean_pinball"]
        # Pre-OOS tuning rule: prioritize not under-covering, then pinball.
        under = max(0.0, rate - alpha)
        over = max(0.0, alpha - rate)
        score = loss * (1.0 + 30.0 * under / max(alpha, 1e-6) + 2.0 * over / max(alpha, 1e-6))
        choices.append(
            {
                "bandwidth": float(bw),
                "validation_n": int(len(block.returns)),
                "validation_violation_rate": safe_float(rate),
                "validation_mean_pinball": safe_float(loss),
                "validation_mean_ess": safe_float(np.nanmean(block.ess)),
                "score": safe_float(score),
            }
        )
    if not choices:
        raise RuntimeError("No valid bandwidth choices")
    best = min(choices, key=lambda r: r["score"])
    return {"selected_bandwidth": best["bandwidth"], "grid": choices}


def holm_adjust(pairs: list[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted([(k, p) for k, p in pairs if p is not None and np.isfinite(p)], key=lambda x: x[1])
    m = len(ordered)
    out = {}
    running = 0.0
    for i, (key, p) in enumerate(ordered):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)
        out[key] = running
    return out


def make_figures(results: dict, oos_df: pd.DataFrame) -> list[str]:
    paths = []
    summary_rows = []
    for key, cell in results["cells"].items():
        asset, alpha = key.split("_alpha")
        for row in cell["oos_evaluation"]["models"]:
            summary_rows.append(
                {
                    "cell": key,
                    "asset": asset,
                    "alpha": float(alpha),
                    "model": row["model"],
                    "mean_pinball": row["mean_pinball"],
                    "violation_rate": row["backtest"]["violation_rate"],
                    "mean_var_width": row["mean_var_width"],
                }
            )
    sdf = pd.DataFrame(summary_rows)
    fig, ax = plt.subplots(figsize=(9, 4.6))
    piv = sdf.pivot(index="cell", columns="model", values="mean_pinball")
    piv[MODELS].plot(kind="bar", ax=ax)
    ax.set_title("K1594 mean pinball loss by asset-alpha cell")
    ax.set_ylabel("Mean pinball, lower is better")
    ax.set_xlabel("")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False)
    fig.tight_layout()
    p = FIG_DIR / "fig1_mean_pinball.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    paths.append(str(p.relative_to(REPO_ROOT)))

    fig, ax = plt.subplots(figsize=(9, 4.4))
    for model in MODELS:
        sub = sdf[sdf["model"] == model]
        ax.scatter(sub["cell"], sub["violation_rate"], label=model, s=42)
    for alpha in ALPHAS:
        ax.axhline(alpha, color="black", linestyle="--", linewidth=0.8)
    ax.set_title("OOS VaR violation rates")
    ax.set_ylabel("Violation rate")
    ax.tick_params(axis="x", rotation=20)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False)
    fig.tight_layout()
    p = FIG_DIR / "fig2_violation_rates.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    paths.append(str(p.relative_to(REPO_ROOT)))

    fig, ax = plt.subplots(figsize=(9, 4.6))
    pivw = sdf.pivot(index="cell", columns="model", values="mean_var_width")
    pivw[MODELS].plot(kind="bar", ax=ax)
    ax.set_title("Average VaR width")
    ax.set_ylabel("-VaR threshold")
    ax.set_xlabel("")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False)
    fig.tight_layout()
    p = FIG_DIR / "fig3_mean_var_width.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    paths.append(str(p.relative_to(REPO_ROOT)))
    return paths


def main() -> int:
    np.random.seed(SEED)
    close = load_close()
    all_oos = []
    cells = {}
    p_for_holm = []

    for asset in ASSETS:
        panel = build_panel(close, asset)
        scaler = StandardScaler().fit(panel.loc[panel.index <= VALID_END, FEATURE_COLS].to_numpy(dtype=float))
        oos_mask = np.asarray((panel.index >= OOS_START) & (panel.index <= OOS_END), dtype=bool)
        for alpha in ALPHAS:
            print(f"[{EXPERIMENT_ID}] {asset} alpha={alpha}", flush=True)
            bw = choose_bandwidth(panel, scaler, alpha)
            block = forecast_period(panel, oos_mask, scaler, alpha, bw["selected_bandwidth"])
            eval_res, odf = evaluate_block(block, alpha)
            cell_key = f"{asset}_alpha{alpha:.2f}"
            odf.insert(0, "asset", asset)
            odf.insert(1, "alpha", alpha)
            all_oos.append(odf)
            kow = next(r for r in eval_res["models"] if r["model"] == "KOWCPI-lite")
            best_model = min(eval_res["models"], key=lambda r: r["mean_pinball"])["model"]
            best_valid = min(
                [r for r in eval_res["models"] if r["backtest"]["kupiec_p"] > 0.05],
                key=lambda r: r["mean_var_width"],
                default=None,
            )
            for pair, rec in eval_res["dm_tests"].items():
                p_for_holm.append((f"{cell_key}:{pair}", rec["p"]))
            cells[cell_key] = {
                "asset": asset,
                "alpha": alpha,
                "n_oos": int(len(block.returns)),
                "bandwidth_selection": bw,
                "kowcpi_mean_ess": safe_float(np.nanmean(block.ess)),
                "kowcpi_median_ess": safe_float(np.nanmedian(block.ess)),
                "kowcpi_mean_shrink_to_uniform": safe_float(np.nanmean(block.shrink)),
                "best_mean_pinball_model": best_model,
                "narrowest_kupiec_valid_model": best_valid["model"] if best_valid else None,
                "oos_evaluation": eval_res,
                "kowcpi_trinity_pass": bool(kow["backtest"]["trinity_pass"]),
            }

    holm = holm_adjust(p_for_holm)
    for cell_key, cell in cells.items():
        for pair, rec in cell["oos_evaluation"]["dm_tests"].items():
            rec["holm_p_across_cells_pairs"] = safe_float(holm.get(f"{cell_key}:{pair}"))

    oos_df = pd.concat(all_oos, ignore_index=True)
    oos_df.to_csv(FORECAST_PATH, index=False)

    figures = make_figures({"cells": cells}, oos_df)

    kow_best_cells = sum(c["best_mean_pinball_model"] == "KOWCPI-lite" for c in cells.values())
    kow_trinity_cells = sum(c["kowcpi_trinity_pass"] for c in cells.values())
    kow_strict_wins = 0
    for c in cells.values():
        vs = c["oos_evaluation"]["dm_tests"]["KOWCPI-lite_minus_VIXRegime1000"]
        if vs["t"] is not None and vs["t"] < -3.0 and (vs["holm_p_across_cells_pairs"] or 1) < 0.05:
            kow_strict_wins += 1

    if kow_best_cells >= 3 and kow_trinity_cells >= 3 and kow_strict_wins >= 2:
        verdict = "KOWCPI_LITE_PASS"
    elif kow_best_cells >= 2 or kow_trinity_cells >= 3:
        verdict = "MIXED_WEAK"
    else:
        verdict = "NULL_OR_FRAGILE"

    result = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "seed": SEED,
        "task": TASK_ID,
        "data": {
            "source": str(DATA_PATH.relative_to(REPO_ROOT)),
            "source_rows": int(len(close)),
            "assets": ASSETS,
            "alphas": ALPHAS,
            "validation_window": [str(VALID_START.date()), str(VALID_END.date())],
            "oos_window": [str(OOS_START.date()), str(OOS_END.date())],
            "calibration_window_days": CAL_WINDOW,
            "features": FEATURE_COLS,
        },
        "method": {
            "name": "KOWCPI-lite one-sided VaR",
            "description": (
                "Gaussian-kernel weighted lower-tail quantile over the past 1000 observations; "
                "bandwidth selected on 2013-2014 validation; weights shrunk toward uniform "
                "when Kish ESS falls below 125."
            ),
            "not_full_replication_note": (
                "This is a finance-specific KOWCPI-style mechanism test, not an exact "
                "implementation of Lee-Xu-Xie KOWCPI."
            ),
        },
        "cells": cells,
        "conclusion": {
            "verdict": verdict,
            "kowcpi_best_mean_pinball_cells": int(kow_best_cells),
            "kowcpi_trinity_pass_cells": int(kow_trinity_cells),
            "kowcpi_strict_holm_wins_vs_vix_regime": int(kow_strict_wins),
            "headline": (
                "Kernel-weighted conformal VaR is not a robust improvement over simpler rolling/regime conformal baselines."
                if verdict == "NULL_OR_FRAGILE"
                else "Kernel-weighted conformal VaR has useful cells but is not yet a clean cross-asset result."
                if verdict == "MIXED_WEAK"
                else "KOWCPI-lite clears the pre-specified VaR width/coverage gate."
            ),
        },
        "artifacts": {
            "oos_forecasts": str(FORECAST_PATH.relative_to(REPO_ROOT)),
            "figures": figures,
        },
        "references_checked": [
            "Lee, Xu and Xie (2024), arXiv:2405.16828",
            "Tibshirani et al. (2019), Conformal Prediction Under Covariate Shift",
            "Gibbs and Candes (2021), Adaptive Conformal Inference",
            "Kupiec (1995) and Christoffersen (1998) VaR backtesting",
        ],
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "result_file": str(RESULT_PATH),
                "verdict": verdict,
                "kowcpi_best_mean_pinball_cells": int(kow_best_cells),
                "kowcpi_trinity_pass_cells": int(kow_trinity_cells),
                "kowcpi_strict_holm_wins_vs_vix_regime": int(kow_strict_wins),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
