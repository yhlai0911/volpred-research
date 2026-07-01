"""K1599: daily co-jump proxy and HAR-CJ-style volatility forecast test.

Backlog source:
    Co-jump / HAR-CJ jump axis: systemic co-jumps, BNS/Lee-Mykland jump
    decomposition, and co-jump counts as volatility-regime triggers.

Scope discipline:
    The local repository does not contain a synchronized multi-asset 5-minute
    ETF panel.  This experiment is therefore a daily proxy diagnostic, not a
    high-frequency BNS/Lee-Mykland replication.  It uses a BNS-style bipower
    scale from daily returns to flag large idiosyncratic jumps and same-day
    cross-ETF co-jump counts, then tests whether those lagged co-jump features
    improve one-day-ahead r^2 QLIKE forecasts over HAR/HAR-J baselines.

Lookahead discipline:
    jump_t is detected after observing return_t, and is only used in features
    dated t+1 or later.  Every forecast for date t uses features computed from
    returns and co-jump counts through date t-1.
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

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 1599
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_PATH = ROOT / "experiments/k1552/data/prices.parquet"
RESULTS_PATH = HERE / "k1599_results.json"
FORECASTS_PATH = HERE / "k1599_oos_forecasts.csv.gz"
FIG_PATH = HERE / "k1599_cojump_har_proxy.png"

ASSETS = ["SPY", "QQQ", "IWM", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
TRAIN_START = pd.Timestamp("2005-01-01")
OOS_START = pd.Timestamp("2016-01-01")
BPV_WINDOW = 63
JUMP_Z_THRESHOLD = 2.5
EPS = 1e-10

MODELS = ["HAR_daily", "HAR_J_proxy", "HAR_CJ_proxy"]

REFERENCES = [
    {
        "key": "bollerslev_law_tauchen_2017",
        "citation": "Bollerslev, Law, and Tauchen (2017), Journal of Financial Economics 126(3), 563-591",
        "role": "systemic co-jumps as market-wide events with short-run predictability and volatility/correlation persistence",
        "url": "https://ideas.repec.org/a/eee/jfinec/v126y2017i3p563-591.html",
    },
    {
        "key": "barndorff_nielsen_shephard_2004",
        "citation": "Barndorff-Nielsen and Shephard (2004), Journal of Financial Econometrics 2(1), 1-37",
        "role": "bipower variation as a continuous-variation estimator robust to rare jumps",
        "url": "https://academic.oup.com/jfec/article-abstract/2/1/1/960705",
    },
    {
        "key": "andersen_bollerslev_diebold_2007",
        "citation": "Andersen, Bollerslev, and Diebold (2007), Review of Economics and Statistics 89(4), 701-720",
        "role": "HAR-style volatility forecasts with separated jump and continuous components",
        "url": "https://ideas.repec.org/a/tpr/restat/v89y2007i4p701-720.html",
    },
    {
        "key": "lee_mykland_2008",
        "citation": "Lee and Mykland (2008), Review of Financial Studies 21(6), 2535-2563",
        "role": "nonparametric high-frequency jump-arrival detection",
        "url": "https://academic.oup.com/rfs/article-abstract/21/6/2535/1574138",
    },
    {
        "key": "lee_lee_kim_2022",
        "citation": "Lee, Lee, and Kim (2022), Journal of Risk and Financial Management 15(8), 334",
        "role": "sector ETF co-jumps and volatility forecasting motivation",
        "url": "https://www.mdpi.com/1911-8074/15/8/334",
    },
]


@dataclass
class Fit:
    beta: np.ndarray
    x_mean: np.ndarray
    x_std: np.ndarray
    resid_var: float


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


def load_close() -> pd.DataFrame:
    raw = pd.read_parquet(DATA_PATH)
    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("Expected k1552 OHLCV MultiIndex parquet")
    close = raw["Close"][ASSETS].sort_index()
    close.index = pd.to_datetime(close.index)
    close = close.loc[close.index >= TRAIN_START]
    return close.dropna(how="all")


def bns_style_daily_jump_flags(returns: pd.DataFrame) -> dict:
    """Daily BPV-scale jump proxy.

    For asset i, scale_t uses rolling mean of |r_{t-1}|*|r_{t-2}| times pi/2.
    That keeps jump classification for t based on a volatility scale known
    before the close of t, while the jump flag itself is only used at t+1.
    """
    abs_ret = returns.abs()
    bpv_var = (np.pi / 2.0) * (abs_ret.shift(1) * abs_ret.shift(2)).rolling(BPV_WINDOW, min_periods=BPV_WINDOW // 2).mean()
    bpv_scale = np.sqrt(bpv_var.clip(lower=EPS))
    z = returns.abs() / bpv_scale
    jump = (z > JUMP_Z_THRESHOLD) & z.notna()
    down_jump = jump & (returns < 0)
    jump_var = (returns.pow(2) - bpv_var).clip(lower=0.0).where(jump, 0.0)
    jump_ratio = (jump_var / returns.pow(2).clip(lower=EPS)).clip(lower=0.0, upper=1.0).fillna(0.0)
    return {
        "bpv_var": bpv_var,
        "bpv_scale": bpv_scale,
        "jump_z": z,
        "jump": jump.astype(int),
        "down_jump": down_jump.astype(int),
        "jump_var": jump_var,
        "jump_ratio": jump_ratio,
    }


def make_global_features(returns: pd.DataFrame, jumps: dict) -> pd.DataFrame:
    valid_count = returns.notna().sum(axis=1).replace(0, np.nan)
    cojump_count = jumps["jump"].sum(axis=1)
    down_cojump_count = jumps["down_jump"].sum(axis=1)
    cojump_frac = (cojump_count / valid_count).fillna(0.0)
    down_cojump_frac = (down_cojump_count / valid_count).fillna(0.0)
    market_r2 = returns.pow(2).mean(axis=1)
    out = pd.DataFrame(
        {
            "cojump_count": cojump_count,
            "cojump_frac": cojump_frac,
            "down_cojump_count": down_cojump_count,
            "down_cojump_frac": down_cojump_frac,
            "market_r2": market_r2,
            "market_abs_ret": returns.abs().mean(axis=1),
        },
        index=returns.index,
    )
    out["cojump_frac_5"] = out["cojump_frac"].rolling(5, min_periods=1).mean()
    out["down_cojump_frac_5"] = out["down_cojump_frac"].rolling(5, min_periods=1).mean()
    out["next_market_r2"] = out["market_r2"].shift(-1)
    out["next_market_abs_ret"] = out["market_abs_ret"].shift(-1)
    return out


def build_asset_panel(asset: str, returns: pd.DataFrame, jumps: dict, global_features: pd.DataFrame) -> pd.DataFrame:
    r = returns[asset]
    r2 = r.pow(2).clip(lower=EPS)
    log_r2 = np.log(r2)
    panel = pd.DataFrame(index=returns.index)
    panel["target_r2"] = r2
    panel["target_log_r2"] = log_r2
    panel["har_d"] = log_r2.shift(1)
    panel["har_w"] = log_r2.shift(1).rolling(5, min_periods=5).mean()
    panel["har_m"] = log_r2.shift(1).rolling(22, min_periods=22).mean()
    panel["own_jump_lag1"] = jumps["jump"][asset].shift(1)
    panel["own_down_jump_lag1"] = jumps["down_jump"][asset].shift(1)
    panel["own_jump_5"] = jumps["jump"][asset].shift(1).rolling(5, min_periods=1).mean()
    panel["own_jump_ratio_lag1"] = jumps["jump_ratio"][asset].shift(1)
    panel["cojump_frac_lag1"] = global_features["cojump_frac"].shift(1)
    panel["cojump_frac_5_lag1"] = global_features["cojump_frac_5"].shift(1)
    panel["down_cojump_frac_lag1"] = global_features["down_cojump_frac"].shift(1)
    panel["down_cojump_frac_5_lag1"] = global_features["down_cojump_frac_5"].shift(1)
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna()
    return panel


def features_for_model(model: str) -> List[str]:
    base = ["har_d", "har_w", "har_m"]
    own_jump = ["own_jump_lag1", "own_down_jump_lag1", "own_jump_5", "own_jump_ratio_lag1"]
    cojump = ["cojump_frac_lag1", "cojump_frac_5_lag1", "down_cojump_frac_lag1", "down_cojump_frac_5_lag1"]
    if model == "HAR_daily":
        return base
    if model == "HAR_J_proxy":
        return base + own_jump
    if model == "HAR_CJ_proxy":
        return base + own_jump + cojump
    raise ValueError(model)


def fit_ols(y: np.ndarray, x: np.ndarray) -> Fit:
    x_mean = x.mean(axis=0)
    x_std = x.std(axis=0)
    x_std[x_std < 1e-12] = 1.0
    xs = (x - x_mean) / x_std
    design = np.column_stack([np.ones(len(xs)), xs])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    resid = y - design @ beta
    dof = max(1, len(y) - x.shape[1] - 1)
    return Fit(beta=beta, x_mean=x_mean, x_std=x_std, resid_var=float(np.sum(resid**2) / dof))


def predict_r2(fit: Fit, row: Iterable[float]) -> float:
    x = np.asarray(list(row), dtype=float)
    xs = (x - fit.x_mean) / fit.x_std
    pred_log = float(np.r_[1.0, xs] @ fit.beta + 0.5 * fit.resid_var)
    pred_log = float(np.clip(pred_log, -30.0, 0.0))
    return float(max(math.exp(pred_log), EPS))


def run_oos_for_asset(asset: str, panel: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    eval_dates = panel.index[panel.index >= OOS_START]
    fits: Dict[str, Fit] = {}
    fit_year = None
    for date in eval_dates:
        if fit_year != date.year:
            train = panel.loc[panel.index < date].copy()
            if len(train) < 1000:
                continue
            fits = {}
            for model in MODELS:
                cols = features_for_model(model)
                train_model = train[["target_log_r2"] + cols].dropna()
                if len(train_model) < 1000:
                    continue
                fits[model] = fit_ols(train_model["target_log_r2"].values, train_model[cols].values)
            fit_year = date.year
        if set(MODELS) - set(fits):
            continue
        actual = float(panel.loc[date, "target_r2"])
        row_base = {"date": date, "asset": asset, "actual_r2": actual}
        for model in MODELS:
            cols = features_for_model(model)
            x = panel.loc[date, cols].values.astype(float)
            pred = predict_r2(fits[model], x)
            rows.append({**row_base, "model": model, "forecast_r2": pred})
    return pd.DataFrame(rows)


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


def event_diagnostic(global_features: pd.DataFrame) -> dict:
    gf = global_features.dropna(subset=["next_market_r2", "next_market_abs_ret"]).copy()
    threshold = max(3.0, float(np.nanquantile(gf["cojump_count"], 0.90)))
    gf["high_cojump"] = gf["cojump_count"] >= threshold
    high = gf[gf["high_cojump"]]
    low = gf[~gf["high_cojump"]]

    def compare(col: str) -> dict:
        a = high[col].values.astype(float)
        b = low[col].values.astype(float)
        t_stat, p_value = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
        rng = np.random.default_rng(SEED)
        diffs = []
        for _ in range(2000):
            aa = rng.choice(a, size=len(a), replace=True)
            bb = rng.choice(b, size=len(b), replace=True)
            diffs.append(float(np.nanmean(aa) - np.nanmean(bb)))
        lo, hi = np.quantile(diffs, [0.025, 0.975])
        return {
            "high_mean": float(np.nanmean(a)),
            "low_mean": float(np.nanmean(b)),
            "diff": float(np.nanmean(a) - np.nanmean(b)),
            "welch_t": float(t_stat),
            "p_value": float(p_value),
            "bootstrap_ci_95": [float(lo), float(hi)],
            "n_high": int(len(a)),
            "n_low": int(len(b)),
        }

    return {
        "high_cojump_definition": f"cojump_count >= {threshold:.0f} (max of 3 and 90th percentile)",
        "cojump_count_summary": {
            "mean": float(gf["cojump_count"].mean()),
            "median": float(gf["cojump_count"].median()),
            "p90": float(np.nanquantile(gf["cojump_count"], 0.90)),
            "max": float(gf["cojump_count"].max()),
            "days_ge_3": int((gf["cojump_count"] >= 3).sum()),
            "days_ge_6": int((gf["cojump_count"] >= 6).sum()),
        },
        "next_market_r2": compare("next_market_r2"),
        "next_market_abs_ret": compare("next_market_abs_ret"),
    }


def summarize_forecasts(forecasts: pd.DataFrame) -> dict:
    out = forecasts.copy()
    losses = []
    for (asset, model), g in out.groupby(["asset", "model"]):
        actual = g["actual_r2"].values.astype(float)
        pred = g["forecast_r2"].values.astype(float)
        loss = qlike_pointwise(actual, pred)
        out.loc[g.index, "qlike_loss"] = loss
        losses.append(
            {
                "asset": asset,
                "model": model,
                "n_oos": int(len(g)),
                "qlike": float(qlike(actual, pred)),
                "mean_forecast_r2": float(np.mean(pred)),
                "mean_actual_r2": float(np.mean(actual)),
            }
        )

    metric_df = pd.DataFrame(losses)
    raw_tests: Dict[str, dict] = {}
    for asset, g in out.groupby("asset"):
        pivot = g.pivot(index="date", columns="model", values="qlike_loss").dropna()
        pairs = [
            ("HAR_J_proxy", "HAR_daily"),
            ("HAR_CJ_proxy", "HAR_daily"),
            ("HAR_CJ_proxy", "HAR_J_proxy"),
        ]
        for candidate, benchmark in pairs:
            t_stat, p_value = dm_test(pivot[candidate].values, pivot[benchmark].values, h=1)
            key = f"{asset}_{candidate}_vs_{benchmark}"
            raw_tests[key] = {
                "asset": asset,
                "candidate": candidate,
                "benchmark": benchmark,
                "t_stat": float(t_stat),
                "p_value": float(p_value),
                "candidate_lower_loss": bool(t_stat < 0),
                "harvey_abs_t_gt_3": bool(abs(t_stat) > 3.0),
                "sign_convention": "negative t => candidate lower QLIKE loss than benchmark",
            }
    dm_tests = holm_adjust(raw_tests)
    strict_wins = [
        key
        for key, item in dm_tests.items()
        if item["candidate"] == "HAR_CJ_proxy"
        and item["candidate_lower_loss"]
        and item["harvey_abs_t_gt_3"]
        and item["holm_5pct"]
    ]
    strict_losses = [
        key
        for key, item in dm_tests.items()
        if item["candidate"] == "HAR_CJ_proxy"
        and (not item["candidate_lower_loss"])
        and item["harvey_abs_t_gt_3"]
        and item["holm_5pct"]
    ]
    best_by_asset = {}
    for asset, g in metric_df.groupby("asset"):
        best = g.sort_values("qlike").iloc[0]
        best_by_asset[asset] = str(best["model"])
    return {
        "forecast_rows": out,
        "metrics_by_asset_model": metric_df.to_dict(orient="records"),
        "mean_qlike_by_model": {m: float(v) for m, v in metric_df.groupby("model")["qlike"].mean().to_dict().items()},
        "best_model_by_asset": best_by_asset,
        "dm_tests": dm_tests,
        "har_cj_strict_wins": strict_wins,
        "har_cj_strict_losses": strict_losses,
    }


def make_figure(global_features: pd.DataFrame, summary: dict) -> None:
    metric_df = pd.DataFrame(summary["metrics_by_asset_model"])
    mean_q = metric_df.groupby("model")["qlike"].mean().reindex(MODELS)
    forecast_rows = summary["forecast_rows"]
    pivot = forecast_rows.pivot_table(index=["date", "asset"], columns="model", values="qlike_loss").dropna()
    loss_diff = (pivot["HAR_CJ_proxy"] - pivot["HAR_daily"]).groupby(level="date").mean()

    fig, axes = plt.subplots(1, 3, figsize=(15.0, 4.5))
    rolling_cj = global_features["cojump_count"].rolling(21, min_periods=1).mean()
    axes[0].plot(rolling_cj.index, rolling_cj.values, color="#4C78A8", linewidth=1.2)
    axes[0].set_title("21-day mean co-jump count")
    axes[0].set_ylabel("Count")
    axes[0].tick_params(axis="x", labelrotation=25)

    colors = ["#4C78A8", "#F28E2B", "#59A14F"]
    axes[1].bar(np.arange(len(MODELS)), mean_q.values, color=colors)
    axes[1].set_xticks(np.arange(len(MODELS)))
    axes[1].set_xticklabels(MODELS, rotation=25, ha="right")
    axes[1].set_ylabel("Mean asset QLIKE")
    axes[1].set_title("OOS forecast race")

    axes[2].plot(loss_diff.index, np.cumsum(loss_diff.values), color="#59A14F", linewidth=1.3)
    axes[2].axhline(0.0, color="black", linewidth=0.8)
    axes[2].set_title("HAR-CJ proxy loss diff vs HAR")
    axes[2].set_ylabel("Cumulative mean loss diff")
    axes[2].tick_params(axis="x", labelrotation=25)

    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    close = load_close()
    returns = np.log(close).diff().dropna(how="all")
    jumps = bns_style_daily_jump_flags(returns)
    global_features = make_global_features(returns, jumps)

    forecast_frames = []
    sample_info = {}
    jump_summary = {}
    for asset in ASSETS:
        panel = build_asset_panel(asset, returns, jumps, global_features)
        if (panel.index < OOS_START).sum() < 1000:
            continue
        f = run_oos_for_asset(asset, panel)
        if len(f):
            forecast_frames.append(f)
        jump_summary[asset] = {
            "n_return_days": int(returns[asset].dropna().shape[0]),
            "jump_days": int(jumps["jump"][asset].sum()),
            "jump_rate": float(jumps["jump"][asset].mean()),
            "down_jump_days": int(jumps["down_jump"][asset].sum()),
        }
        sample_info[asset] = {
            "start": str(panel.index[0].date()),
            "end": str(panel.index[-1].date()),
            "n_panel_rows": int(len(panel)),
            "n_train_before_oos": int((panel.index < OOS_START).sum()),
            "n_oos_candidate": int((panel.index >= OOS_START).sum()),
        }

    forecasts = pd.concat(forecast_frames, ignore_index=True)
    forecast_summary = summarize_forecasts(forecasts)
    forecast_rows = forecast_summary.pop("forecast_rows")
    forecast_rows.to_csv(FORECASTS_PATH, index=False, compression="gzip", float_format="%.10g")
    event_summary = event_diagnostic(global_features)
    figure_summary = {**forecast_summary, "forecast_rows": forecast_rows}
    make_figure(global_features, figure_summary)

    wins = len(forecast_summary["har_cj_strict_wins"])
    losses = len(forecast_summary["har_cj_strict_losses"])
    event_pass = bool(abs(event_summary["next_market_r2"]["welch_t"]) > 3.0 and event_summary["next_market_r2"]["diff"] > 0)
    if wins >= 3 and losses == 0:
        verdict = "SUPPORTED_DAILY_PROXY"
    elif wins == 0 and losses == 0 and event_pass:
        verdict = "COJUMP_STRESS_SIGNAL_NO_FORECAST_EDGE"
    elif losses > wins:
        verdict = "NULL_OR_NEGATIVE_DAILY_PROXY"
    else:
        verdict = "MIXED_DAILY_PROXY"

    conclusion = (
        "Daily ETF co-jump counts identify stress days, but lagged HAR-CJ proxy features do not deliver a "
        "panel-level Harvey/Holm QLIKE forecasting edge over HAR/HAR-J."
        if verdict in {"COJUMP_STRESS_SIGNAL_NO_FORECAST_EDGE", "MIXED_DAILY_PROXY"}
        else (
            "Lagged daily co-jump proxy features clear the strict HAR-CJ forecast gate in this ETF panel."
            if verdict == "SUPPORTED_DAILY_PROXY"
            else "Daily co-jump proxy features do not clear the local HAR-CJ contribution gate."
        )
    )

    results = {
        "experiment_id": "k1599",
        "title": "Daily Co-Jump Proxy and HAR-CJ-Style Volatility Forecast Test",
        "timestamp_utc": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "task_id": "research_co_jump_har_cj_jump_jfe_2017_systemic_co_jumps_j",
        "references": REFERENCES,
        "dataset": {
            "source": str(DATA_PATH.relative_to(ROOT)),
            "assets": ASSETS,
            "train_start": str(TRAIN_START.date()),
            "oos_start": str(OOS_START.date()),
            "sample_by_asset": sample_info,
        },
        "jump_detection": {
            "status": "daily_proxy_not_high_frequency_replication",
            "bpv_window_days": BPV_WINDOW,
            "threshold": f"|r_t| / sqrt((pi/2) * rolling_mean(|r_t-1|*|r_t-2|)) > {JUMP_Z_THRESHOLD}",
            "jump_summary_by_asset": jump_summary,
            "global_cojump_summary": event_summary["cojump_count_summary"],
        },
        "event_diagnostic": event_summary,
        "oos_model_race": forecast_summary,
        "primary_test": {
            "target": "next-day close-to-close squared log return",
            "loss": "QLIKE(actual_r2, forecast_r2)",
            "models": MODELS,
            "strict_gate": "HAR_CJ_proxy must have lower QLIKE loss with Harvey |DM t|>3 and Holm 5pct",
            "lookahead_rule": "all jump/co-jump variables are shifted at least one trading day before target date",
        },
        "verdict": verdict,
        "conclusion": conclusion,
        "research_implication": (
            "The co-jump axis remains interesting as a stress-state measurement channel, but this daily proxy "
            "does not yet justify a paper-level HAR-CJ forecasting claim.  A publishable test needs synchronized "
            "5-minute cross-asset data and formal BNS/Lee-Mykland co-jump flags."
        ),
        "limitations": [
            "This is a daily proxy; it is not a high-frequency BNS/Lee-Mykland replication.",
            "Close-to-close squared returns are noisy volatility proxies and include overnight effects.",
            "The co-jump threshold is fixed at 2.5 standardized daily BPV units; sensitivity and formal high-frequency thresholds are follow-ups.",
            "Forecast models are annual-refit log-OLS HAR variants, not full realized-kernel or Hawkes-network models.",
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
                    "har_cj_wins": wins,
                    "har_cj_losses": losses,
                    "mean_qlike_by_model": forecast_summary["mean_qlike_by_model"],
                    "event_t_next_market_r2": event_summary["next_market_r2"]["welch_t"],
                }
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
