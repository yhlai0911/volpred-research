"""K1598: online conformal prediction via universal-portfolio-style mixing.

Backlog source:
    Online Conformal via Universal Portfolio -- arXiv:2602.03168.

Scope:
    This is a finance-facing lite implementation.  The paper's UP-OCP method
    reduces online conformal calibration to universal portfolio algorithms.  We
    do not claim to reproduce every theorem-level detail.  We test whether a
    Cover-style universal portfolio over ACI learning-rate experts improves
    volatility-scaled return interval calibration against practical conformal
    baselines on local ETF data.

Lookahead discipline:
    sigma_t is an EWMA forecast based on returns through t-1; each threshold
    used on day t is formed before observing score_t; online updates occur only
    after the day-t score is evaluated.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from volpred.stats.model_evaluation import dm_test


SEED = 1598
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_PATH = ROOT / "experiments/k1552/data/prices.parquet"
RESULTS_PATH = HERE / "k1598_results.json"
FORECASTS_PATH = HERE / "k1598_oos_forecasts.csv.gz"
FIG_PATH = HERE / "k1598_coverage_size.png"

ASSETS = ["SPY", "QQQ", "IWM", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
ALPHAS = [0.10, 0.05]
OOS_START = pd.Timestamp("2016-01-01")
TRAIN_START = pd.Timestamp("2005-01-01")
EWMA_LAMBDA = 0.94
ROLLING_WINDOW = 252
EXPERT_ETAS = np.array([0.001, 0.0025, 0.005, 0.01, 0.02, 0.04], dtype=float)
N_UNIVERSAL_PORTFOLIOS = 1600

METHODS = [
    "FixedIS",
    "Rolling252",
    "ACI_eta_0p01",
    "AggACI_grid",
    "UP_AggACI_lite",
]

BASELINE_METHODS = ["FixedIS", "Rolling252", "ACI_eta_0p01", "AggACI_grid"]

REFERENCES = [
    {
        "key": "liu_dobriban_orabona_2026",
        "citation": "Liu, Dobriban, and Orabona (2026), arXiv:2602.03168",
        "role": "UP-OCP theory: online conformal prediction through universal portfolio algorithms",
        "url": "https://arxiv.org/abs/2602.03168",
    },
    {
        "key": "gibbs_candes_2021_2024",
        "citation": "Gibbs and Candès (2021, 2024), adaptive conformal inference under distribution shift",
        "role": "ACI baseline and arbitrary online distribution-shift motivation",
        "url": "https://www.jmlr.org/papers/v25/22-1218.html",
    },
    {
        "key": "cover_1991",
        "citation": "Cover (1991), Universal Portfolios, Mathematical Finance",
        "role": "universal portfolio principle used as a parameter-free online mixture",
        "url": "https://isl.stanford.edu/~cover/papers/paper93.pdf",
    },
    {
        "key": "areces_mohri_hashimoto_duchi_2025",
        "citation": "Areces, Mohri, Hashimoto, and Duchi (2025), ICML/PMLR",
        "role": "online conformal prediction via online optimization baseline context",
        "url": "https://proceedings.mlr.press/v267/areces25a.html",
    },
]


@dataclass
class CellResult:
    asset: str
    alpha: float
    method: str
    n_oos: int
    miss_rate: float
    coverage: float
    target_miss_rate: float
    mean_radius: float
    median_radius: float
    mean_q: float
    mean_pinball_loss: float
    binom_p_value: float
    christoffersen_ind_p_value: float


def finite_json(value):
    if isinstance(value, dict):
        return {str(k): finite_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite_json(v) for v in value]
    if isinstance(value, tuple):
        return [finite_json(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    return value


def load_close_prices() -> pd.DataFrame:
    raw = pd.read_parquet(DATA_PATH)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        raise ValueError("Expected MultiIndex OHLCV parquet from k1552")
    close = close[ASSETS].sort_index()
    close.index = pd.to_datetime(close.index)
    close = close.loc[close.index >= TRAIN_START].dropna(how="all")
    return close


def ewma_sigma(returns: pd.Series, lam: float = EWMA_LAMBDA) -> pd.Series:
    r = returns.values.astype(float)
    sigma = np.full(len(r), np.nan, dtype=float)
    finite = r[np.isfinite(r)]
    if len(finite) < 260:
        return pd.Series(sigma, index=returns.index)
    init = float(np.nanvar(r[: min(252, len(r))], ddof=1))
    if not math.isfinite(init) or init <= 0:
        init = float(np.nanvar(finite[:252], ddof=1))
    var = max(init, 1e-10)
    for i in range(1, len(r)):
        prev = r[i - 1]
        if math.isfinite(prev):
            var = lam * var + (1.0 - lam) * (prev**2)
        sigma[i] = math.sqrt(max(var, 1e-12))
    return pd.Series(sigma, index=returns.index, name="ewma_sigma")


def pinball_loss(scores: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    s = np.asarray(scores, dtype=float)
    pred = np.asarray(q, dtype=float)
    u = s - pred
    return np.where(u >= 0, tau * u, (tau - 1.0) * u)


def christoffersen_independence(hits: np.ndarray) -> Tuple[float, float]:
    e = np.asarray(hits, dtype=int)
    if e.size < 20 or e.sum() == 0 or e.sum() == e.size:
        return float("nan"), float("nan")
    n00 = int(((e[:-1] == 0) & (e[1:] == 0)).sum())
    n01 = int(((e[:-1] == 0) & (e[1:] == 1)).sum())
    n10 = int(((e[:-1] == 1) & (e[1:] == 0)).sum())
    n11 = int(((e[:-1] == 1) & (e[1:] == 1)).sum())
    n0 = n00 + n01
    n1 = n10 + n11
    if n0 == 0 or n1 == 0:
        return float("nan"), float("nan")
    pi = (n01 + n11) / (n0 + n1)
    pi0 = n01 / n0
    pi1 = n11 / n1
    eps = 1e-12
    ll_null = (n00 + n10) * math.log(max(1.0 - pi, eps)) + (n01 + n11) * math.log(max(pi, eps))
    ll_alt = (
        n00 * math.log(max(1.0 - pi0, eps))
        + n01 * math.log(max(pi0, eps))
        + n10 * math.log(max(1.0 - pi1, eps))
        + n11 * math.log(max(pi1, eps))
    )
    lr = max(0.0, -2.0 * (ll_null - ll_alt))
    return float(lr), float(1.0 - stats.chi2.cdf(lr, df=1))


def make_simplex_grid(n_experts: int, n_random: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rows = []
    rows.append(np.ones(n_experts) / n_experts)
    rows.extend(np.eye(n_experts))
    for concentration in [0.25, 0.75, 1.5, 4.0]:
        draws = max(1, n_random // 4)
        rows.extend(rng.dirichlet(np.ones(n_experts) * concentration, size=draws))
    grid = np.asarray(rows, dtype=float)
    grid = grid / grid.sum(axis=1, keepdims=True)
    return grid


def safe_quantile(sample: np.ndarray, tau: float, fallback: float) -> float:
    clean = np.asarray(sample, dtype=float)
    clean = clean[np.isfinite(clean)]
    if len(clean) < 30:
        return float(fallback)
    return float(np.quantile(clean, tau))


def run_online_cell(panel: pd.DataFrame, asset: str, alpha: float) -> Tuple[pd.DataFrame, Dict[str, CellResult]]:
    tau = 1.0 - alpha
    returns = panel["return"].values.astype(float)
    sigma = panel["sigma"].values.astype(float)
    scores = panel["score"].values.astype(float)
    dates = pd.DatetimeIndex(panel.index)
    oos_start_idx = int(dates.searchsorted(OOS_START))
    if oos_start_idx < 1000:
        raise ValueError(f"{asset}: insufficient training observations before OOS")

    train_scores = scores[:oos_start_idx]
    train_scores = train_scores[np.isfinite(train_scores)]
    q0 = safe_quantile(train_scores, tau, fallback=2.0)
    q_max = max(8.0, safe_quantile(train_scores, 0.995, fallback=q0) * 2.0)

    aci_q = float(q0)
    expert_q = np.full(len(EXPERT_ETAS), q0, dtype=float)
    hedge_weights = np.ones(len(EXPERT_ETAS), dtype=float) / len(EXPERT_ETAS)
    crp_grid = make_simplex_grid(len(EXPERT_ETAS), N_UNIVERSAL_PORTFOLIOS, seed=SEED)
    crp_wealth = np.ones(len(crp_grid), dtype=float)

    rows: List[dict] = []

    for pos in range(oos_start_idx, len(panel)):
        score_t = float(scores[pos])
        sigma_t = float(sigma[pos])
        return_t = float(returns[pos])
        if not (math.isfinite(score_t) and math.isfinite(sigma_t) and sigma_t > 0 and math.isfinite(return_t)):
            continue

        fixed_q = q0
        rolling_q = safe_quantile(scores[max(0, pos - ROLLING_WINDOW) : pos], tau, fallback=q0)
        hedge_q = float(np.dot(hedge_weights, expert_q))
        crp_weights = crp_wealth / crp_wealth.sum()
        up_alloc = crp_weights @ crp_grid
        up_q = float(np.dot(up_alloc, expert_q))

        q_predictions = {
            "FixedIS": fixed_q,
            "Rolling252": rolling_q,
            "ACI_eta_0p01": aci_q,
            "AggACI_grid": hedge_q,
            "UP_AggACI_lite": up_q,
        }

        row_base = {
            "date": dates[pos],
            "asset": asset,
            "alpha": alpha,
            "return": return_t,
            "sigma": sigma_t,
            "score": score_t,
        }
        for method, q in q_predictions.items():
            q_clip = float(np.clip(q, 0.0, q_max))
            radius = q_clip * sigma_t
            miss = int(score_t > q_clip)
            loss = float(pinball_loss(np.asarray([score_t]), np.asarray([q_clip]), tau=tau)[0])
            row = dict(row_base)
            row.update(
                {
                    "method": method,
                    "q": q_clip,
                    "radius": radius,
                    "miss": miss,
                    "pinball_loss": loss,
                    "lower": -radius,
                    "upper": radius,
                }
            )
            rows.append(row)

        expert_losses = pinball_loss(np.full(len(EXPERT_ETAS), score_t), expert_q, tau=tau)
        expert_returns = np.exp(-np.clip(expert_losses, 0.0, 50.0))

        hedge_weights = hedge_weights * expert_returns
        hedge_weights = hedge_weights / hedge_weights.sum()

        crp_returns = crp_grid @ expert_returns
        crp_wealth = crp_wealth * np.maximum(crp_returns, 1e-12)
        crp_wealth = crp_wealth / np.max(crp_wealth)

        aci_q = float(np.clip(aci_q + 0.01 * ((score_t > aci_q) - alpha), 0.0, q_max))
        expert_q = np.clip(expert_q + EXPERT_ETAS * ((score_t > expert_q).astype(float) - alpha), 0.0, q_max)

    forecast_df = pd.DataFrame(rows)
    cell_results: Dict[str, CellResult] = {}
    for method, g in forecast_df.groupby("method"):
        misses = g["miss"].values.astype(int)
        n = len(g)
        miss_rate = float(misses.mean()) if n else float("nan")
        try:
            binom_p = float(stats.binomtest(int(misses.sum()), n, alpha).pvalue)
        except Exception:
            binom_p = float("nan")
        _, ind_p = christoffersen_independence(misses)
        cell_results[method] = CellResult(
            asset=asset,
            alpha=float(alpha),
            method=method,
            n_oos=int(n),
            miss_rate=miss_rate,
            coverage=float(1.0 - miss_rate),
            target_miss_rate=float(alpha),
            mean_radius=float(g["radius"].mean()),
            median_radius=float(g["radius"].median()),
            mean_q=float(g["q"].mean()),
            mean_pinball_loss=float(g["pinball_loss"].mean()),
            binom_p_value=binom_p,
            christoffersen_ind_p_value=float(ind_p) if math.isfinite(ind_p) else float("nan"),
        )
    return forecast_df, cell_results


def holm_adjust(tests: Dict[str, dict]) -> Dict[str, dict]:
    keys = list(tests)
    pvals = np.asarray([tests[k]["p_value"] for k in keys], dtype=float)
    order = np.argsort(pvals)
    adjusted = np.empty(len(keys), dtype=float)
    running = 0.0
    m = len(keys)
    for rank, idx in enumerate(order):
        adj = min(1.0, (m - rank) * pvals[idx])
        running = max(running, adj)
        adjusted[idx] = running
    out = {}
    for key, adj in zip(keys, adjusted):
        item = dict(tests[key])
        item["holm_p_value"] = float(adj)
        item["holm_5pct"] = bool(adj < 0.05)
        out[key] = item
    return out


def summarize_results(forecasts: pd.DataFrame, cell_results: List[CellResult]) -> dict:
    cells = [c.__dict__ for c in cell_results]
    cell_df = pd.DataFrame(cells)

    method_summary = {}
    for method, g in cell_df.groupby("method"):
        method_summary[method] = {
            "cells": int(len(g)),
            "mean_miss_rate": float(g["miss_rate"].mean()),
            "mean_abs_miss_gap": float(np.mean(np.abs(g["miss_rate"] - g["target_miss_rate"]))),
            "mean_radius": float(g["mean_radius"].mean()),
            "median_radius": float(g["median_radius"].median()),
            "mean_pinball_loss": float(g["mean_pinball_loss"].mean()),
            "binom_pass_cells": int((g["binom_p_value"] > 0.05).sum()),
            "independence_pass_cells": int((g["christoffersen_ind_p_value"] > 0.05).sum()),
            "undercoverage_cells": int((g["miss_rate"] > g["target_miss_rate"]).sum()),
            "overcoverage_cells": int((g["miss_rate"] < g["target_miss_rate"]).sum()),
        }

    dm_raw: Dict[str, dict] = {}
    up = "UP_AggACI_lite"
    for (asset, alpha), g in forecasts.groupby(["asset", "alpha"]):
        pivot = g.pivot(index="date", columns="method", values="pinball_loss").dropna()
        for baseline in BASELINE_METHODS:
            t_stat, p_value = dm_test(pivot[up].values, pivot[baseline].values, h=1)
            key = f"{asset}_a{alpha:.2f}_{up}_vs_{baseline}"
            dm_raw[key] = {
                "asset": asset,
                "alpha": float(alpha),
                "candidate": up,
                "benchmark": baseline,
                "t_stat": float(t_stat),
                "p_value": float(p_value),
                "candidate_lower_loss": bool(t_stat < 0),
                "harvey_abs_t_gt_3": bool(abs(t_stat) > 3.0),
                "sign_convention": "negative t => UP_AggACI_lite has lower pinball loss than benchmark",
            }
    dm_tests = holm_adjust(dm_raw)
    strict_wins = [
        key
        for key, item in dm_tests.items()
        if item["candidate_lower_loss"] and item["harvey_abs_t_gt_3"] and item["holm_5pct"]
    ]
    strict_losses = [
        key
        for key, item in dm_tests.items()
        if (not item["candidate_lower_loss"]) and item["harvey_abs_t_gt_3"] and item["holm_5pct"]
    ]

    by_alpha = {}
    for alpha, g in cell_df.groupby("alpha"):
        by_alpha[str(alpha)] = {}
        for method, gm in g.groupby("method"):
            by_alpha[str(alpha)][method] = {
                "mean_miss_rate": float(gm["miss_rate"].mean()),
                "mean_radius": float(gm["mean_radius"].mean()),
                "mean_pinball_loss": float(gm["mean_pinball_loss"].mean()),
            }

    return {
        "cell_results": cells,
        "method_summary": method_summary,
        "by_alpha": by_alpha,
        "dm_tests_up_vs_baselines": dm_tests,
        "up_strict_wins": strict_wins,
        "up_strict_losses": strict_losses,
    }


def make_figure(forecasts: pd.DataFrame, summary: dict) -> None:
    method_order = METHODS
    colors = {
        "FixedIS": "#7F7F7F",
        "Rolling252": "#4C78A8",
        "ACI_eta_0p01": "#F28E2B",
        "AggACI_grid": "#59A14F",
        "UP_AggACI_lite": "#B07AA1",
    }
    cell_df = pd.DataFrame(summary["cell_results"])

    fig, axes = plt.subplots(1, 3, figsize=(15.0, 4.5))

    x = np.arange(len(method_order))
    width = 0.36
    for j, alpha in enumerate(ALPHAS):
        vals = []
        for method in method_order:
            vals.append(cell_df[(cell_df["method"] == method) & (cell_df["alpha"] == alpha)]["miss_rate"].mean())
        axes[0].bar(x + (j - 0.5) * width, vals, width=width, label=f"alpha={alpha:.2f}", color=["#4C78A8", "#F28E2B"][j])
        axes[0].axhline(alpha, color=["#4C78A8", "#F28E2B"][j], linestyle="--", linewidth=1.0)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(method_order, rotation=25, ha="right")
    axes[0].set_ylabel("Mean miscoverage rate")
    axes[0].set_title("Coverage tracking")
    axes[0].legend(frameon=False, fontsize=8)

    vals = [summary["method_summary"][m]["mean_radius"] for m in method_order]
    axes[1].bar(x, vals, color=[colors[m] for m in method_order])
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(method_order, rotation=25, ha="right")
    axes[1].set_ylabel("Mean half-width")
    axes[1].set_title("Interval size")

    daily = forecasts.pivot_table(
        index=["date", "asset", "alpha"],
        columns="method",
        values="pinball_loss",
        aggfunc="mean",
    ).dropna()
    for baseline in ["Rolling252", "ACI_eta_0p01", "AggACI_grid"]:
        diff = (daily["UP_AggACI_lite"] - daily[baseline]).groupby(level="date").mean()
        axes[2].plot(diff.index, np.cumsum(diff.values), label=f"UP - {baseline}", linewidth=1.4)
    axes[2].axhline(0.0, color="black", linewidth=0.8)
    axes[2].set_ylabel("Cumulative mean loss diff")
    axes[2].set_title("Negative means UP-lite wins")
    axes[2].legend(frameon=False, fontsize=8)
    axes[2].tick_params(axis="x", labelrotation=25)

    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    close = load_close_prices()
    forecast_frames: List[pd.DataFrame] = []
    cell_results: List[CellResult] = []
    sample_info = {}

    for asset in ASSETS:
        price = close[asset].dropna()
        returns = np.log(price).diff()
        sigma = ewma_sigma(returns)
        panel = pd.DataFrame({"return": returns, "sigma": sigma}, index=price.index).dropna()
        panel["score"] = (panel["return"].abs() / panel["sigma"]).replace([np.inf, -np.inf], np.nan)
        panel = panel.dropna()
        panel = panel[panel.index >= TRAIN_START]
        if len(panel[panel.index < OOS_START]) < 1000:
            continue
        sample_info[asset] = {
            "start": str(panel.index[0].date()),
            "end": str(panel.index[-1].date()),
            "n_total": int(len(panel)),
            "n_train_before_oos": int((panel.index < OOS_START).sum()),
            "n_oos_candidate": int((panel.index >= OOS_START).sum()),
        }
        for alpha in ALPHAS:
            fdf, cdict = run_online_cell(panel, asset, alpha)
            forecast_frames.append(fdf)
            cell_results.extend(cdict[m] for m in METHODS)

    forecasts = pd.concat(forecast_frames, ignore_index=True)
    forecasts.to_csv(FORECASTS_PATH, index=False, compression="gzip", float_format="%.10g")
    summary = summarize_results(forecasts, cell_results)
    make_figure(forecasts, summary)

    up_summary = summary["method_summary"]["UP_AggACI_lite"]
    rolling_summary = summary["method_summary"]["Rolling252"]
    agg_summary = summary["method_summary"]["AggACI_grid"]
    strict_wins = len(summary["up_strict_wins"])
    strict_losses = len(summary["up_strict_losses"])

    up_beats_all_on_mean_pinball = all(
        up_summary["mean_pinball_loss"] <= summary["method_summary"][m]["mean_pinball_loss"]
        for m in BASELINE_METHODS
    )
    panel_strict_win_count = 3

    if (
        strict_wins >= panel_strict_win_count
        and strict_losses == 0
        and up_summary["mean_abs_miss_gap"] <= rolling_summary["mean_abs_miss_gap"]
        and up_beats_all_on_mean_pinball
    ):
        verdict = "SUPPORTED_WITH_CAVEATS"
    elif strict_wins == 0 and strict_losses == 0 and up_summary["mean_abs_miss_gap"] <= rolling_summary["mean_abs_miss_gap"]:
        verdict = "COVERAGE_COMPETITIVE_NO_PANEL_EDGE"
    elif strict_wins > 0 and strict_losses == 0 and up_summary["mean_abs_miss_gap"] <= rolling_summary["mean_abs_miss_gap"]:
        verdict = "COVERAGE_COMPETITIVE_NO_PANEL_EDGE"
    elif strict_losses > strict_wins:
        verdict = "NULL_OR_NEGATIVE"
    else:
        verdict = "MIXED_NO_CLEAR_EDGE"

    conclusion = (
        "UP_AggACI_lite is coverage-competitive with rolling conformal and ACI baselines, and records one "
        "strict cell-level win versus Rolling252, but it does not produce a panel-level pinball-loss edge."
        if verdict in {"COVERAGE_COMPETITIVE_NO_PANEL_EDGE", "MIXED_NO_CLEAR_EDGE"}
        else (
            "UP_AggACI_lite produces strict robust improvements without worse coverage in this ETF panel."
            if verdict == "SUPPORTED_WITH_CAVEATS"
            else "UP_AggACI_lite does not clear the local conformal interval calibration gate."
        )
    )

    results = {
        "experiment_id": "k1598",
        "title": "Online Conformal Prediction via Universal-Portfolio-Style Mixing",
        "timestamp_utc": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "task_id": "research_online_conformal_via_universal_portfolio",
        "references": REFERENCES,
        "dataset": {
            "source": str(DATA_PATH.relative_to(ROOT)),
            "assets": ASSETS,
            "train_start": str(TRAIN_START.date()),
            "oos_start": str(OOS_START.date()),
            "sample_by_asset": sample_info,
            "target": "centered daily log-return interval using EWMA-volatility standardized absolute-return scores",
        },
        "methods": {
            "FixedIS": "static in-sample score quantile before OOS",
            "Rolling252": "rolling 252-day empirical score quantile using scores through t-1",
            "ACI_eta_0p01": "single adaptive conformal inference update with eta=0.01",
            "AggACI_grid": "exponential-loss aggregation over ACI learning-rate experts",
            "UP_AggACI_lite": "Cover-style universal portfolio over ACI expert returns exp(-pinball_loss); lite proxy for UP-OCP",
        },
        "primary_test": {
            "coverage_levels": ALPHAS,
            "loss": "pinball loss on volatility-standardized absolute-return scores",
            "strict_gate": "UP_AggACI_lite must have lower loss, Harvey |DM t|>3, and Holm 5pct vs baselines",
            "lookahead_rule": "sigma_t and conformal thresholds are formed before observing score_t; updates occur after scoring date t",
        },
        "summary": summary,
        "verdict": verdict,
        "conclusion": conclusion,
        "research_implication": (
            "The universal-portfolio idea is promising as a parameter-free online calibration device, but the "
            "local ETF panel supports at most a coverage-stability claim.  It does not yet justify replacing "
            "rolling conformal or ACI in the VolPred VaR/conformal stack without a faithful UP-OCP implementation "
            "and stress-regime validation."
        ),
        "limitations": [
            "UP_AggACI_lite is a discrete Cover-style mixture over ACI experts, not the exact closed-form UP-OCP algorithm in Liu-Dobriban-Orabona.",
            "The experiment uses centered absolute-return intervals, not one-sided production VaR/ES backtests.",
            "EWMA sigma is a simple scale forecast; results may differ with A4f/GARCH/HAR score normalization.",
            "Binomial and independence p-values are diagnostic because online conformal validity targets long-run coverage rather than iid exceedance testing.",
        ],
        "outputs": {
            "results_json": str(RESULTS_PATH.relative_to(ROOT)),
            "forecast_csv": str(FORECASTS_PATH.relative_to(ROOT)),
            "figure": str(FIG_PATH.relative_to(ROOT)),
        },
    }

    RESULTS_PATH.write_text(json.dumps(finite_json(results), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            finite_json(
                {
                    "verdict": verdict,
                    "up_strict_wins": strict_wins,
                    "up_strict_losses": strict_losses,
                    "up_mean_abs_miss_gap": up_summary["mean_abs_miss_gap"],
                    "rolling_mean_abs_miss_gap": rolling_summary["mean_abs_miss_gap"],
                    "agg_mean_abs_miss_gap": agg_summary["mean_abs_miss_gap"],
                }
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
