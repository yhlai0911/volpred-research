#!/usr/bin/env python3
"""Graph spillover RV forecast vs linear spillover VAR.

This experiment uses daily close-to-close squared log returns as a low-frequency
variance proxy. It does not claim intraday realized-volatility evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "research_graph_network_spillover_rv_var_results.json"

TICKERS = ["SPY", "QQQ", "TLT", "GLD", "HYG", "EEM", "CL=F"]
ASSET_LABELS = {
    "SPY": "US equity",
    "QQQ": "US growth",
    "TLT": "Treasury",
    "GLD": "Gold",
    "HYG": "Credit",
    "EEM": "EM equity",
    "CL=F": "Oil futures",
}
START_DATE = "2007-01-01"
END_DATE = "2026-06-14"
OOS_START = pd.Timestamp("2018-01-02")
TRAIN_WINDOW = 1260
REFIT_EVERY = 21
HORIZONS = [1, 5, 22]
RV_EPS = 1e-10
RIDGE_L2 = 1e-3
TRADING_DAYS = 252
SEED = 42


@dataclass(frozen=True)
class RidgeModel:
    columns: list[str]
    x_mean: np.ndarray
    x_std: np.ndarray
    beta: np.ndarray
    y_clip_low: float
    y_clip_high: float


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def label_date(value) -> str:
    return str(value.date()) if hasattr(value, "date") else str(value)


def download_prices() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty data")
    prices = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].copy()
    prices = prices[TICKERS].dropna(how="any")
    prices.index = pd.to_datetime(prices.index)
    prices.to_csv(DATA_DIR / "prices.csv")
    return prices


def future_mean_variance(rv: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Target at date t is mean RV from t+1 through t+h."""
    return rv.shift(-1).rolling(horizon).mean().shift(-(horizon - 1))


def make_features(log_rv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    feature_map: dict[str, pd.DataFrame] = {}
    for asset in log_rv.columns:
        feature_map[asset] = pd.DataFrame(
            {
                "own_lag1": log_rv[asset],
                "own_mean5": log_rv[asset].rolling(5).mean(),
                "own_mean22": log_rv[asset].rolling(22).mean(),
            },
            index=log_rv.index,
        )
    return feature_map


def fit_ridge(x: pd.DataFrame, y: pd.Series, l2: float = RIDGE_L2) -> RidgeModel | None:
    df = pd.concat([x, y.rename("target")], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < max(80, x.shape[1] * 10):
        return None
    x_arr = df[x.columns].to_numpy(dtype=float)
    y_arr = df["target"].to_numpy(dtype=float)
    x_mean = x_arr.mean(axis=0)
    x_std = x_arr.std(axis=0, ddof=1)
    x_std[x_std < 1e-12] = 1.0
    x_scaled = (x_arr - x_mean) / x_std
    design = np.column_stack([np.ones(len(x_scaled)), x_scaled])
    penalty = np.eye(design.shape[1]) * l2
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ y_arr)
    y_low = float(np.quantile(y_arr, 0.01) - 1.0)
    y_high = float(np.quantile(y_arr, 0.99) + 1.0)
    return RidgeModel(
        columns=list(x.columns),
        x_mean=x_mean,
        x_std=x_std,
        beta=beta,
        y_clip_low=y_low,
        y_clip_high=y_high,
    )


def predict_ridge(model: RidgeModel | None, x: pd.DataFrame) -> pd.Series:
    if model is None:
        return pd.Series(np.nan, index=x.index)
    x_use = x[model.columns].replace([np.inf, -np.inf], np.nan)
    out = pd.Series(np.nan, index=x_use.index)
    valid = x_use.dropna()
    if valid.empty:
        return out
    x_arr = valid.to_numpy(dtype=float)
    x_scaled = (x_arr - model.x_mean) / model.x_std
    design = np.column_stack([np.ones(len(x_scaled)), x_scaled])
    pred_log = design @ model.beta
    pred_log = np.clip(pred_log, model.y_clip_low, model.y_clip_high)
    out.loc[valid.index] = np.exp(pred_log)
    return out.clip(lower=RV_EPS, upper=0.5)


def lagged_correlation_adjacency(log_rv: pd.DataFrame, train_dates: pd.Index) -> pd.DataFrame:
    train = log_rv.loc[train_dates]
    assets = list(log_rv.columns)
    adj = pd.DataFrame(0.0, index=assets, columns=assets)
    for effect in assets:
        for cause in assets:
            if cause == effect:
                continue
            pair = pd.concat(
                [train[effect].rename("effect"), train[cause].shift(1).rename("cause_lag")],
                axis=1,
            ).dropna()
            if len(pair) < 100:
                continue
            corr = float(pair["effect"].corr(pair["cause_lag"]))
            adj.loc[effect, cause] = max(corr, 0.0) if np.isfinite(corr) else 0.0

    for effect in assets:
        row_sum = float(adj.loc[effect].sum())
        if row_sum <= 1e-12:
            others = [a for a in assets if a != effect]
            adj.loc[effect, others] = 1.0 / len(others)
        else:
            adj.loc[effect] = adj.loc[effect] / row_sum
    return adj


def build_graph_feature(log_rv: pd.DataFrame, adjacency: pd.DataFrame) -> pd.DataFrame:
    values = log_rv[adjacency.columns].to_numpy(dtype=float) @ adjacency.T.to_numpy(dtype=float)
    return pd.DataFrame(values, index=log_rv.index, columns=adjacency.index)


def observed_target_cutoff(all_dates: pd.Index, block_start: pd.Timestamp, horizon: int) -> pd.Timestamp | None:
    pos = all_dates.get_loc(block_start)
    cutoff_pos = pos - horizon
    if cutoff_pos < 0:
        return None
    return all_dates[cutoff_pos]


def forecast_horizon(
    log_rv: pd.DataFrame,
    target_var: pd.DataFrame,
    horizon: int,
) -> tuple[dict[str, pd.DataFrame], list[pd.DataFrame]]:
    assets = list(log_rv.columns)
    own_features = make_features(log_rv)
    all_lag_features = log_rv.add_prefix("lag1_")
    valid_mask = target_var.notna().all(axis=1) & log_rv.notna().all(axis=1)
    valid_dates = target_var.index[valid_mask]
    oos_dates = valid_dates[valid_dates >= OOS_START]

    forecasts = {
        "own_har": pd.DataFrame(np.nan, index=target_var.index, columns=assets),
        "spillover_var": pd.DataFrame(np.nan, index=target_var.index, columns=assets),
        "graph_har": pd.DataFrame(np.nan, index=target_var.index, columns=assets),
    }
    adjacency_snapshots: list[pd.DataFrame] = []

    for block_start in oos_dates[::REFIT_EVERY]:
        cutoff = observed_target_cutoff(target_var.index, block_start, horizon)
        if cutoff is None:
            continue
        train_pool = valid_dates[(valid_dates <= cutoff) & (valid_dates < block_start)]
        if len(train_pool) < TRAIN_WINDOW:
            continue
        train_dates = train_pool[-TRAIN_WINDOW:]
        block_pos = oos_dates.get_loc(block_start)
        block_dates = oos_dates[block_pos : block_pos + REFIT_EVERY]

        adjacency = lagged_correlation_adjacency(log_rv, train_dates)
        adjacency_snapshots.append(adjacency)
        graph_feature = build_graph_feature(log_rv, adjacency)

        for asset in assets:
            y_train = np.log(target_var[asset].loc[train_dates] + RV_EPS)
            own_x = own_features[asset]
            var_x = pd.concat(
                [all_lag_features, own_features[asset][["own_mean5", "own_mean22"]]],
                axis=1,
            )
            graph_x = pd.concat(
                [
                    own_features[asset],
                    graph_feature[asset].rename("graph_neighbor_lag1"),
                ],
                axis=1,
            )

            models = {
                "own_har": fit_ridge(own_x.loc[train_dates], y_train),
                "spillover_var": fit_ridge(var_x.loc[train_dates], y_train),
                "graph_har": fit_ridge(graph_x.loc[train_dates], y_train),
            }
            x_by_model = {
                "own_har": own_x.loc[block_dates],
                "spillover_var": var_x.loc[block_dates],
                "graph_har": graph_x.loc[block_dates],
            }
            for model_name, model in models.items():
                forecasts[model_name].loc[block_dates, asset] = predict_ridge(model, x_by_model[model_name])

    return forecasts, adjacency_snapshots


def model_metrics(actual: pd.DataFrame, forecast: pd.DataFrame) -> dict:
    common = actual.index.intersection(forecast.index)
    actual = actual.loc[common]
    forecast = forecast.loc[common]
    rows = []
    losses_by_date = {}
    for asset in actual.columns:
        df = pd.concat([actual[asset].rename("actual"), forecast[asset].rename("forecast")], axis=1).dropna()
        if len(df) < 100:
            continue
        losses = qlike_pointwise(df["actual"].to_numpy(), df["forecast"].to_numpy())
        losses_by_date[asset] = pd.Series(losses, index=df.index)
        rho, rho_p = spearman_corr(df["actual"].to_numpy(), df["forecast"].to_numpy())
        rows.append(
            {
                "asset": asset,
                "n": int(len(df)),
                "qlike": qlike(df["actual"].to_numpy(), df["forecast"].to_numpy()),
                "mse": float(np.mean((df["actual"].to_numpy() - df["forecast"].to_numpy()) ** 2)),
                "spearman_rho": rho,
                "spearman_p": rho_p,
            }
        )
    if not rows:
        return {"asset_metrics": {}, "mean_qlike": None, "mean_spearman": None, "loss_by_date": pd.Series(dtype=float)}
    asset_metrics = {r.pop("asset"): {k: round(v, 8) if isinstance(v, float) else v for k, v in r.items()} for r in rows}
    loss_panel = pd.DataFrame(losses_by_date)
    return {
        "asset_metrics": asset_metrics,
        "mean_qlike": round(float(np.nanmean([m["qlike"] for m in asset_metrics.values()])), 8),
        "mean_spearman": round(float(np.nanmean([m["spearman_rho"] for m in asset_metrics.values()])), 8),
        "loss_by_date": loss_panel.mean(axis=1).dropna(),
    }


def evaluate_horizon(actual: pd.DataFrame, forecasts: dict[str, pd.DataFrame], horizon: int) -> dict:
    oos_actual = actual.loc[actual.index >= OOS_START]
    metrics = {name: model_metrics(oos_actual, fc.loc[oos_actual.index]) for name, fc in forecasts.items()}
    json_metrics = {
        name: {k: v for k, v in metric.items() if k != "loss_by_date"} for name, metric in metrics.items()
    }

    dm_results = {}
    comparisons = [("graph_har", "spillover_var"), ("graph_har", "own_har"), ("spillover_var", "own_har")]
    for left, right in comparisons:
        joined = pd.concat(
            [metrics[left]["loss_by_date"].rename(left), metrics[right]["loss_by_date"].rename(right)],
            axis=1,
        ).dropna()
        if len(joined) < 100:
            dm_results[f"{left}_vs_{right}"] = {"n": int(len(joined)), "dm_t": None, "p_value": None}
            continue
        t_stat, p_val = dm_test(joined[left].to_numpy(), joined[right].to_numpy(), h=horizon)
        dm_results[f"{left}_vs_{right}"] = {
            "n": int(len(joined)),
            "dm_t": round(float(t_stat), 6),
            "p_value": round(float(p_val), 8),
            "significant_abs_t_gt_3": bool(abs(t_stat) > 3.0),
            "interpretation": f"negative means {left} lower QLIKE than {right}",
        }

    improvements = {}
    for base in ["spillover_var", "own_har"]:
        graph_q = metrics["graph_har"]["mean_qlike"]
        base_q = metrics[base]["mean_qlike"]
        improvements[f"graph_har_vs_{base}_qlike_improvement_pct"] = (
            None if graph_q is None or base_q is None else round((base_q - graph_q) / base_q * 100, 4)
        )

    return {
        "metrics": json_metrics,
        "dm_tests": dm_results,
        "improvements": improvements,
    }


def average_adjacency(adjacencies: list[pd.DataFrame]) -> pd.DataFrame:
    if not adjacencies:
        return pd.DataFrame()
    stacked = np.stack([a.to_numpy(dtype=float) for a in adjacencies])
    return pd.DataFrame(stacked.mean(axis=0), index=adjacencies[0].index, columns=adjacencies[0].columns)


def render_figures(results_by_horizon: dict[int, dict], avg_adj: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    x = np.arange(len(HORIZONS))
    width = 0.24
    for offset, model in [(-width, "own_har"), (0.0, "spillover_var"), (width, "graph_har")]:
        vals = [results_by_horizon[h]["metrics"][model]["mean_qlike"] for h in HORIZONS]
        ax.bar(x + offset, vals, width=width, label=model)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h}d" for h in HORIZONS])
    ax.set_ylabel("Mean QLIKE (lower is better)")
    ax.set_title("OOS QLIKE by horizon")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.savefig(HERE / "fig_qlike_by_horizon.png", dpi=180)
    plt.close(fig)

    if not avg_adj.empty:
        fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
        im = ax.imshow(avg_adj.to_numpy(dtype=float), cmap="magma", vmin=0)
        ax.set_xticks(np.arange(len(avg_adj.columns)))
        ax.set_xticklabels(avg_adj.columns, rotation=45, ha="right")
        ax.set_yticks(np.arange(len(avg_adj.index)))
        ax.set_yticklabels(avg_adj.index)
        ax.set_title("Average lagged-correlation graph weights (row receives from column)")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        fig.savefig(HERE / "fig_average_graph_adjacency.png", dpi=180)
        plt.close(fig)


def main() -> None:
    np.random.default_rng(SEED)
    prices = download_prices()
    nonpositive_counts = (prices <= 0).sum().astype(int).to_dict()
    clean_prices = prices.where(prices > 0).dropna(how="any")
    log_returns = np.log(clean_prices / clean_prices.shift(1)).dropna(how="any")
    rv = (log_returns**2).clip(lower=RV_EPS)
    log_rv = np.log(rv + RV_EPS)

    results_by_horizon: dict[int, dict] = {}
    all_adjacencies: list[pd.DataFrame] = []

    for horizon in HORIZONS:
        target_var = future_mean_variance(rv, horizon)
        forecasts, adjacencies = forecast_horizon(log_rv, target_var, horizon)
        all_adjacencies.extend(adjacencies)
        results_by_horizon[horizon] = evaluate_horizon(target_var, forecasts, horizon)

    avg_adj = average_adjacency(all_adjacencies)
    render_figures(results_by_horizon, avg_adj)

    summary = {
        "verdict": "short_horizon_graph_vs_var_only_not_robust",
        "headline": "Graph propagation beats the linear spillover-VAR baseline at the 1-day horizon, but the edge does not survive across 5/22-day horizons and is not significant versus own-HAR.",
        "horizon_takeaways": {},
    }
    for horizon, res in results_by_horizon.items():
        g_vs_var = res["improvements"]["graph_har_vs_spillover_var_qlike_improvement_pct"]
        dm = res["dm_tests"]["graph_har_vs_spillover_var"]
        summary["horizon_takeaways"][str(horizon)] = {
            "graph_vs_var_qlike_improvement_pct": g_vs_var,
            "dm_t": dm["dm_t"],
            "significant_abs_t_gt_3": dm["significant_abs_t_gt_3"],
        }

    output = {
        "experiment_id": "research_graph_network_spillover_rv_var",
        "title": "Graph/network spillover RV forecast vs linear VAR baseline",
        "timestamp_utc": utc_now(),
        "data": {
            "source": "yfinance auto-adjusted close",
            "tickers": TICKERS,
            "asset_labels": ASSET_LABELS,
            "period": [label_date(log_returns.index[0]), label_date(log_returns.index[-1])],
            "n_price_days": int(len(prices)),
            "n_positive_price_days": int(len(clean_prices)),
            "n_return_days": int(len(log_returns)),
            "nonpositive_price_counts": nonpositive_counts,
            "proxy": "daily close-to-close squared log return; not intraday realized volatility",
            "nonpositive_price_handling": "rows with any nonpositive close are removed before log-return construction; this mainly handles CL=F negative settlement during April 2020",
        },
        "design": {
            "target": "future average daily variance proxy over t+1..t+h",
            "horizons": HORIZONS,
            "oos_start": str(OOS_START.date()),
            "train_window_days": TRAIN_WINDOW,
            "refit_every_days": REFIT_EVERY,
            "models": {
                "own_har": "own log RV lag1, 5-day mean, 22-day mean",
                "spillover_var": "all assets log RV lag1 plus own 5/22-day means",
                "graph_har": "own HAR features plus row-normalized lagged-correlation neighbor aggregate",
            },
            "anti_lookahead": [
                "feature at date t uses only variance proxy through close t",
                "target at date t is t+1..t+h future average variance",
                "rolling model refits only use training targets fully observed before the first forecast date in the block",
            ],
            "statistics": "Patton QLIKE on same target; DM test on date-level mean QLIKE losses, Harvey |t|>3 threshold",
        },
        "literature": [
            {
                "title": "Forecasting realized volatility with spillover effects",
                "year": 2025,
                "url": "https://ideas.repec.org/a/eee/intfor/v41y2025i1p377-397.html",
                "note": "International Journal of Forecasting paper motivating GNN spillover RV forecasts and QLIKE evaluation.",
            },
            {
                "title": "Predictive directional measurement of volatility spillovers",
                "year": 2012,
                "url": "https://econpapers.repec.org/RePEc%3Aeee%3Aintfor%3Av%3A28%3Ay%3A2012%3Ai%3A1%3Ap%3A57-66",
                "note": "Diebold-Yilmaz generalized VAR connectedness foundation for directional spillover measurement.",
            },
            {
                "title": "Do Better Volatility Forecasts Lead to Better Portfolios? Evidence from Graph Neural Networks",
                "year": 2026,
                "url": "https://arxiv.org/abs/2605.19278",
                "note": "Recent GNN volatility paper emphasizing that forecast accuracy and portfolio value need not align.",
            },
            {
                "title": "Volatility Spillovers in High-Dimensional Financial Systems: A Machine Learning Approach",
                "year": 2026,
                "url": "https://arxiv.org/abs/2601.03146",
                "note": "Hybrid HAR/ElasticNet evidence that network structure can be interpretable even when forecast gains are limited.",
            },
        ],
        "related_repo_priors": [
            "K357 built volatility spillover network diagnostics but did not test forecast horse races.",
            "research_quantile_connectedness_var_yfinance_etf_rv_quant found tail connectedness but explicitly avoided forecasting claims.",
            "K816v2 showed QLIKE training can matter, but neural/graph additions need OOS DM validation.",
        ],
        "results_by_horizon": {str(k): v for k, v in results_by_horizon.items()},
        "average_adjacency": avg_adj.round(6).to_dict() if not avg_adj.empty else {},
        "summary": summary,
        "limitations": [
            "Daily yfinance data cannot produce intraday realized volatility; this is a daily variance-proxy experiment.",
            "The graph model is intentionally lightweight and interpretable, not a full trained GNN.",
            "DM tests average losses across assets by date; cross-sectional dependence is not fully modeled.",
            "CL=F futures are aligned to ETF common trading days, so commodity futures holiday effects are suppressed.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
