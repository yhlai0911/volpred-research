#!/usr/bin/env python3
"""K1596: Multiplicative Volatility Factor (MVF)-lite test.

The Journal of Econometrics MVF paper models each asset variance as a common
variance factor times an idiosyncratic multiplicative exposure. This local test
asks a narrower question with daily public data: can a transparent common-factor
variance decomposition improve next-day ETF variance forecasts under Patton
QLIKE versus HAR, EWMA, and annual-refit GJR-GARCH?
"""

from __future__ import annotations

import json
import math
import sys
import warnings
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise, spearman_corr  # noqa: E402


EXPERIMENT_ID = "k1596"
SEED = 1596
DATA_PATH = ROOT / "experiments" / "k1552" / "data" / "prices.parquet"
OUT_DIR = ROOT / "experiments" / EXPERIMENT_ID
FIG_DIR = OUT_DIR / "figures"

ASSETS = ["SPY", "QQQ", "IWM", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
TRAIN_START = "2005-01-01"
OOS_START = "2016-01-01"
OOS_END = "2026-06-26"
EPS = 1e-10
EWMA_LAMBDA = 0.94

MODEL_ORDER = [
    "EWMA94",
    "HAR_LogOLS",
    "GJR_GARCH_Annual",
    "CommonFactorOnly",
    "MVF_StaticExposure",
    "MVF_LogARExposure",
]


def to_float(x: object) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def read_prices() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(DATA_PATH)
    prices = pd.read_parquet(DATA_PATH)
    prices.index = pd.to_datetime(prices.index)
    return prices.sort_index()


def get_field(prices: pd.DataFrame, field: str) -> pd.DataFrame:
    if not isinstance(prices.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex OHLCV columns.")
    out = prices[field].copy()
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def build_panels(prices: pd.DataFrame) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    close = get_field(prices, "Close")
    high = get_field(prices, "High")
    low = get_field(prices, "Low")

    r2_cols = {}
    panels: Dict[str, pd.DataFrame] = {}
    for asset in ASSETS:
        px = close[asset].replace(0, np.nan).ffill()
        ret = np.log(px).diff()
        r2 = (ret**2).clip(lower=EPS)
        parkinson = (np.log(high[asset] / low[asset]) ** 2 / (4.0 * np.log(2))).replace(
            [np.inf, -np.inf], np.nan
        )
        df = pd.DataFrame(index=close.index)
        df["ret"] = ret
        df["r2"] = r2
        df["log_r2"] = np.log(r2.clip(lower=EPS))
        df["parkinson"] = parkinson.clip(lower=EPS)
        df["log_r2_l1"] = df["log_r2"].shift(1)
        df["log_rv5_l1"] = np.log(r2.rolling(5, min_periods=5).mean().shift(1).clip(lower=EPS))
        df["log_rv22_l1"] = np.log(r2.rolling(22, min_periods=22).mean().shift(1).clip(lower=EPS))
        df["log_rv66_l1"] = np.log(r2.rolling(66, min_periods=66).mean().shift(1).clip(lower=EPS))
        df["abs_ret_l1"] = ret.abs().shift(1)
        panels[asset] = df.replace([np.inf, -np.inf], np.nan)
        r2_cols[asset] = r2

    r2_panel = pd.DataFrame(r2_cols).replace([np.inf, -np.inf], np.nan)
    return panels, r2_panel


def har_features(series: pd.Series) -> pd.DataFrame:
    s = series.clip(lower=EPS)
    return pd.DataFrame(
        {
            "log_l1": np.log(s.shift(1).clip(lower=EPS)),
            "log_ma5_l1": np.log(s.rolling(5, min_periods=5).mean().shift(1).clip(lower=EPS)),
            "log_ma22_l1": np.log(s.rolling(22, min_periods=22).mean().shift(1).clip(lower=EPS)),
            "log_ma66_l1": np.log(s.rolling(66, min_periods=66).mean().shift(1).clip(lower=EPS)),
        }
    ).replace([np.inf, -np.inf], np.nan)


def annual_log_ols_forecast(
    target_var: pd.Series,
    features: pd.DataFrame,
    *,
    fit_start: str = TRAIN_START,
    oos_start: str = OOS_START,
    oos_end: str = OOS_END,
) -> pd.Series:
    pred = pd.Series(np.nan, index=target_var.index, dtype=float)
    y_log = np.log(target_var.clip(lower=EPS))
    oos_index = target_var.loc[oos_start:oos_end].index
    years = sorted(pd.Index(oos_index.year).unique())
    for year in years:
        seg_idx = target_var.loc[f"{year}-01-01" : f"{year}-12-31"].loc[:oos_end].index
        seg_idx = seg_idx[seg_idx >= pd.Timestamp(oos_start)]
        if len(seg_idx) == 0:
            continue
        train_mask = (
            (features.index >= pd.Timestamp(fit_start))
            & (features.index < seg_idx[0])
            & features.notna().all(axis=1)
            & y_log.notna()
        )
        if int(train_mask.sum()) < 1000:
            continue
        model = LinearRegression()
        model.fit(features.loc[train_mask], y_log.loc[train_mask])
        valid_seg = features.loc[seg_idx].notna().all(axis=1)
        idx = seg_idx[valid_seg.to_numpy()]
        if len(idx):
            yhat = model.predict(features.loc[idx])
            pred.loc[idx] = np.exp(np.clip(yhat, np.log(EPS), np.log(0.25)))
    return pred


def ewma_forecast(r2: pd.Series) -> pd.Series:
    pred = pd.Series(np.nan, index=r2.index, dtype=float)
    pre = r2.loc[: pd.Timestamp(OOS_START) - pd.Timedelta(days=1)].dropna()
    if len(pre) < 252:
        return pred
    h = float(pre.tail(252).mean())
    prev_r2 = float(pre.iloc[-1])
    for dt in r2.index[(r2.index >= OOS_START) & (r2.index <= OOS_END)]:
        h = EWMA_LAMBDA * h + (1.0 - EWMA_LAMBDA) * prev_r2
        pred.loc[dt] = max(h, EPS)
        if np.isfinite(r2.loc[dt]):
            prev_r2 = float(r2.loc[dt])
    return pred


def gjr_garch_annual_forecast(ret: pd.Series) -> pd.Series:
    pred = pd.Series(np.nan, index=ret.index, dtype=float)
    try:
        from arch import arch_model
    except Exception as exc:  # pragma: no cover
        warnings.warn(f"arch unavailable: {exc}")
        return pred

    r = ret.dropna()
    oos_years = sorted(pd.Index(r.loc[OOS_START:OOS_END].index.year).unique())
    for year in oos_years:
        seg_idx = r.loc[f"{year}-01-01" : f"{year}-12-31"].loc[:OOS_END].index
        seg_idx = seg_idx[seg_idx >= pd.Timestamp(OOS_START)]
        if len(seg_idx) == 0:
            continue
        train = r.loc[TRAIN_START : seg_idx[0] - pd.Timedelta(days=1)].dropna()
        if len(train) < 1000:
            continue
        y = train * 100.0
        try:
            model = arch_model(
                y,
                mean="Zero",
                vol="GARCH",
                p=1,
                o=1,
                q=1,
                dist="normal",
                rescale=False,
            )
            res = model.fit(disp="off", show_warning=False, options={"maxiter": 400})
            params = res.params
            omega = float(params.get("omega", np.nan))
            alpha = float(params.get("alpha[1]", 0.0))
            gamma = float(params.get("gamma[1]", 0.0))
            beta = float(params.get("beta[1]", 0.0))
            h_prev = float(res.conditional_volatility.iloc[-1] ** 2)
            prev_ret = float(y.iloc[-1])
        except Exception as exc:
            warnings.warn(f"GJR fit failed for {seg_idx[0].date()}: {exc}")
            continue
        for dt in seg_idx:
            h = omega + alpha * prev_ret**2 + gamma * prev_ret**2 * (prev_ret < 0) + beta * h_prev
            if math.isfinite(h) and h > 0:
                pred.loc[dt] = max(h / 10000.0, EPS)
                h_prev = h
            if dt in r.index and math.isfinite(float(r.loc[dt])):
                prev_ret = float(r.loc[dt] * 100.0)
    return pred


def build_mvf_forecasts(r2_panel: pd.DataFrame) -> pd.DataFrame:
    # The paper uses common variance; here the common factor is the daily
    # cross-sectional average of ETF variance proxies. This is observed only
    # after date t, so all forecasts use HAR features shifted to t-1.
    common = r2_panel[ASSETS].mean(axis=1).clip(lower=EPS)
    common_features = har_features(common)
    common_pred = annual_log_ols_forecast(common, common_features)

    rows = []
    for asset in ASSETS:
        asset_r2 = r2_panel[asset].clip(lower=EPS)
        ratio = (asset_r2 / common).replace([np.inf, -np.inf], np.nan).clip(lower=0.01, upper=100.0)
        static_exposure = ratio.rolling(252, min_periods=126).mean().shift(1).clip(lower=0.05, upper=20.0)

        log_ratio = np.log(ratio.clip(lower=0.01, upper=100.0))
        exp_features = pd.DataFrame(
            {
                "log_ratio_l1": log_ratio.shift(1),
                "log_ratio_ma22_l1": log_ratio.rolling(22, min_periods=10).mean().shift(1),
                "log_ratio_ma252_l1": log_ratio.rolling(252, min_periods=126).mean().shift(1),
            }
        ).replace([np.inf, -np.inf], np.nan)
        log_ar_exposure = annual_log_ols_forecast(ratio, exp_features)

        for dt in r2_panel.loc[OOS_START:OOS_END].index:
            rows.append(
                {
                    "date": dt,
                    "asset": asset,
                    "actual_var": float(asset_r2.loc[dt]),
                    "CommonFactorOnly": float(common_pred.loc[dt]) if np.isfinite(common_pred.loc[dt]) else np.nan,
                    "MVF_StaticExposure": (
                        float(common_pred.loc[dt] * static_exposure.loc[dt])
                        if np.isfinite(common_pred.loc[dt]) and np.isfinite(static_exposure.loc[dt])
                        else np.nan
                    ),
                    "MVF_LogARExposure": (
                        float(common_pred.loc[dt] * log_ar_exposure.loc[dt])
                        if np.isfinite(common_pred.loc[dt]) and np.isfinite(log_ar_exposure.loc[dt])
                        else np.nan
                    ),
                    "static_exposure": to_float(static_exposure.loc[dt]),
                    "log_ar_exposure": to_float(log_ar_exposure.loc[dt]),
                    "common_pred": to_float(common_pred.loc[dt]),
                    "common_realized": to_float(common.loc[dt]),
                }
            )
    out = pd.DataFrame(rows)
    for col in ["CommonFactorOnly", "MVF_StaticExposure", "MVF_LogARExposure"]:
        out[col] = out[col].clip(lower=EPS, upper=0.25)
    return out


def build_forecast_frame(panels: Dict[str, pd.DataFrame], r2_panel: pd.DataFrame) -> pd.DataFrame:
    forecasts = build_mvf_forecasts(r2_panel)
    for model in ["EWMA94", "HAR_LogOLS", "GJR_GARCH_Annual"]:
        forecasts[model] = np.nan

    for asset in ASSETS:
        panel = panels[asset]
        rows = forecasts["asset"] == asset
        har_pred = annual_log_ols_forecast(panel["r2"], panel[["log_r2_l1", "log_rv5_l1", "log_rv22_l1", "log_rv66_l1"]])
        ewma_pred = ewma_forecast(panel["r2"])
        gjr_pred = gjr_garch_annual_forecast(panel["ret"])
        forecasts.loc[rows, "HAR_LogOLS"] = forecasts.loc[rows, "date"].map(har_pred).to_numpy()
        forecasts.loc[rows, "EWMA94"] = forecasts.loc[rows, "date"].map(ewma_pred).to_numpy()
        forecasts.loc[rows, "GJR_GARCH_Annual"] = forecasts.loc[rows, "date"].map(gjr_pred).to_numpy()

    for model in MODEL_ORDER:
        forecasts[model] = forecasts[model].clip(lower=EPS, upper=0.25)
    return forecasts.sort_values(["asset", "date"]).reset_index(drop=True)


def holm_adjust(pvals: Iterable[float]) -> List[float]:
    p = np.asarray([float(x) if x is not None and np.isfinite(x) else 1.0 for x in pvals])
    m = len(p)
    order = np.argsort(p)
    adjusted = np.empty(m, dtype=float)
    running = 0.0
    for rank, idx in enumerate(order):
        val = min(1.0, (m - rank) * p[idx])
        running = max(running, val)
        adjusted[idx] = running
    return adjusted.tolist()


def evaluate(forecasts: pd.DataFrame) -> Dict[str, object]:
    clean = forecasts.copy()
    for model in MODEL_ORDER:
        clean[f"loss_{model}"] = qlike_pointwise(clean["actual_var"].to_numpy(), clean[model].to_numpy())

    metrics: List[Dict[str, object]] = []
    dm_records: List[Dict[str, object]] = []
    for asset in ASSETS:
        sub = clean[clean["asset"] == asset].copy()
        for model in MODEL_ORDER:
            valid = sub[["actual_var", model, f"loss_{model}"]].replace([np.inf, -np.inf], np.nan).dropna()
            if len(valid) < 252:
                continue
            rho, rho_p = spearman_corr(valid["actual_var"].to_numpy(), valid[model].to_numpy())
            metrics.append(
                {
                    "asset": asset,
                    "model": model,
                    "n": int(len(valid)),
                    "mean_qlike": float(valid[f"loss_{model}"].mean()),
                    "median_qlike": float(valid[f"loss_{model}"].median()),
                    "mse": float(np.mean((valid["actual_var"].to_numpy() - valid[model].to_numpy()) ** 2)),
                    "spearman": to_float(rho),
                    "spearman_p": to_float(rho_p),
                    "mean_forecast_var": float(valid[model].mean()),
                    "mean_actual_var": float(valid["actual_var"].mean()),
                }
            )

        for mvf_model in ["CommonFactorOnly", "MVF_StaticExposure", "MVF_LogARExposure"]:
            for base in ["EWMA94", "HAR_LogOLS", "GJR_GARCH_Annual"]:
                pair = sub[[f"loss_{mvf_model}", f"loss_{base}"]].replace([np.inf, -np.inf], np.nan).dropna()
                if len(pair) < 252:
                    continue
                stat, p = dm_test(pair[f"loss_{mvf_model}"].to_numpy(), pair[f"loss_{base}"].to_numpy(), h=1)
                dm_records.append(
                    {
                        "scope": "asset",
                        "asset": asset,
                        "pair": f"{mvf_model}_minus_{base}",
                        "mvf_model": mvf_model,
                        "baseline": base,
                        "n": int(len(pair)),
                        "dm_stat": float(stat),
                        "p": float(p),
                        "strict_harvey_abs_t_gt_3": bool(abs(stat) > 3.0),
                        "direction_favors_mvf": bool(stat < 0),
                    }
                )

    p_adj = holm_adjust([r["p"] for r in dm_records])
    for rec, adj in zip(dm_records, p_adj):
        rec["holm_p"] = float(adj)
        rec["strict_holm_win"] = bool(
            rec["direction_favors_mvf"] and rec["strict_harvey_abs_t_gt_3"] and rec["holm_p"] < 0.05
        )
        rec["strict_holm_loss"] = bool(
            (not rec["direction_favors_mvf"]) and rec["strict_harvey_abs_t_gt_3"] and rec["holm_p"] < 0.05
        )

    pooled = []
    for mvf_model in ["CommonFactorOnly", "MVF_StaticExposure", "MVF_LogARExposure"]:
        for base in ["EWMA94", "HAR_LogOLS", "GJR_GARCH_Annual"]:
            pair = clean[[f"loss_{mvf_model}", f"loss_{base}"]].replace([np.inf, -np.inf], np.nan).dropna()
            stat, p = dm_test(pair[f"loss_{mvf_model}"].to_numpy(), pair[f"loss_{base}"].to_numpy(), h=1)
            pooled.append(
                {
                    "scope": "pooled_asset_day_diagnostic",
                    "pair": f"{mvf_model}_minus_{base}",
                    "mvf_model": mvf_model,
                    "baseline": base,
                    "n": int(len(pair)),
                    "dm_stat": float(stat),
                    "p": float(p),
                    "direction_favors_mvf": bool(stat < 0),
                    "caveat": "Pooled asset-day DM is diagnostic only; per-asset Holm tests are primary.",
                }
            )

    metric_df = pd.DataFrame(metrics)
    best_by_asset = []
    for asset in ASSETS:
        sub = metric_df[metric_df["asset"] == asset].sort_values("mean_qlike")
        if len(sub):
            best_by_asset.append({"asset": asset, "best_model": str(sub.iloc[0]["model"])})
    mvf_models = {"CommonFactorOnly", "MVF_StaticExposure", "MVF_LogARExposure"}
    mvf_best_assets = sum(1 for r in best_by_asset if r["best_model"] in mvf_models)
    mvf_gjr_wins = sum(1 for r in dm_records if r["baseline"] == "GJR_GARCH_Annual" and r["strict_holm_win"])
    mvf_all_wins = sum(1 for r in dm_records if r["strict_holm_win"])
    mvf_losses = sum(1 for r in dm_records if r["strict_holm_loss"])

    if mvf_best_assets >= 7 and mvf_gjr_wins >= 6 and mvf_losses == 0:
        verdict = "PASS"
    elif mvf_best_assets >= 3 and mvf_gjr_wins >= 2:
        verdict = "WEAK_PARTIAL"
    else:
        verdict = "NULL_OR_NEGATIVE"

    return {
        "metrics": metrics,
        "dm_tests": dm_records,
        "pooled_asset_day_dm_diagnostic": pooled,
        "best_by_asset": best_by_asset,
        "conclusion": {
            "verdict": verdict,
            "mvf_best_mean_qlike_assets": int(mvf_best_assets),
            "mvf_strict_holm_wins_all_pairs": int(mvf_all_wins),
            "mvf_strict_holm_wins_vs_gjr": int(mvf_gjr_wins),
            "mvf_strict_holm_losses": int(mvf_losses),
            "primary_inference": "per-asset Holm-adjusted DM tests; pooled asset-day DM is diagnostic only",
        },
    }


def plot_results(forecasts: pd.DataFrame, eval_res: Dict[str, object]) -> List[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    metrics = pd.DataFrame(eval_res["metrics"])
    paths: List[str] = []

    pivot = metrics.pivot(index="asset", columns="model", values="mean_qlike")
    rel = pivot.sub(pivot["HAR_LogOLS"], axis=0)
    fig, ax = plt.subplots(figsize=(14, 7))
    rel[MODEL_ORDER].plot(kind="bar", ax=ax)
    ax.axhline(0, color="black", lw=0.9)
    ax.set_title("K1596 mean QLIKE relative to HAR_LogOLS (lower is better)")
    ax.set_ylabel("Mean QLIKE difference")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / "fig1_relative_qlike_vs_har.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    paths.append(str(p.relative_to(OUT_DIR)))

    fig, axes = plt.subplots(4, 3, figsize=(15, 11), sharex=False)
    axes = axes.ravel()
    for ax, asset in zip(axes, ASSETS):
        sub = forecasts[forecasts["asset"] == asset].sort_values("date")
        loss_mvf = qlike_pointwise(sub["actual_var"].to_numpy(), sub["MVF_LogARExposure"].to_numpy())
        loss_gjr = qlike_pointwise(sub["actual_var"].to_numpy(), sub["GJR_GARCH_Annual"].to_numpy())
        diff = pd.Series(loss_mvf - loss_gjr, index=sub["date"]).replace([np.inf, -np.inf], np.nan)
        ax.plot(diff.cumsum(), lw=1.1)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title(asset)
        ax.grid(alpha=0.25)
    fig.suptitle("Cumulative QLIKE loss difference: MVF_LogARExposure minus GJR_GARCH_Annual")
    fig.tight_layout()
    p = FIG_DIR / "fig2_cumulative_loss_diff_vs_gjr.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    paths.append(str(p.relative_to(OUT_DIR)))

    exposure_rows = (
        forecasts.groupby("asset")[["static_exposure", "log_ar_exposure"]]
        .agg(["mean", "std", "min", "max"])
        .reset_index()
    )
    exp_plot = forecasts.groupby("asset")[["static_exposure", "log_ar_exposure"]].mean()
    fig, ax = plt.subplots(figsize=(11, 5))
    exp_plot.plot(kind="bar", ax=ax)
    ax.axhline(1.0, color="black", lw=0.9)
    ax.set_title("Average MVF multiplicative exposures")
    ax.set_ylabel("Exposure to common variance factor")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / "fig3_average_exposures.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    paths.append(str(p.relative_to(OUT_DIR)))

    (OUT_DIR / "k1596_exposure_summary.csv").write_text(exposure_rows.to_csv(index=False), encoding="utf-8")
    return paths


def main() -> None:
    np.random.seed(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prices = read_prices()
    panels, r2_panel = build_panels(prices)
    forecasts = build_forecast_frame(panels, r2_panel)
    eval_res = evaluate(forecasts)
    fig_paths = plot_results(forecasts, eval_res)

    forecast_path = OUT_DIR / "k1596_oos_forecasts.csv"
    forecasts.to_csv(forecast_path, index=False)

    result = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": "research_multiplicative_volatility_factor_mvf",
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "data": {
            "source": str(DATA_PATH.relative_to(ROOT)),
            "assets": ASSETS,
            "rows_in_price_cache": int(len(prices)),
            "train_start": TRAIN_START,
            "oos_window": [OOS_START, OOS_END],
            "oos_rows": int(len(forecasts)),
            "oos_rows_by_asset": {k: int(v) for k, v in forecasts.groupby("asset").size().items()},
        },
        "method": {
            "scope": "MVF-lite using daily ETF squared-return variance proxies; not a high-frequency stock-universe replication",
            "target": "next-day close-to-close squared log return",
            "common_factor": "daily cross-sectional average of ETF squared returns",
            "loss": "Patton QLIKE actual/predicted - log(actual/predicted) - 1",
            "lookahead_control": [
                "common factor forecast uses HAR features shifted to t-1",
                "static exposure is a rolling 252-day mean of r2_i/common shifted to t-1",
                "log-AR exposure uses lagged ratio features only",
                "HAR baseline uses explicit lagged r2 features",
                "GJR annual recursion forecasts date t from fitted params, h_{t-1}, and return_{t-1}",
            ],
            "models": MODEL_ORDER,
        },
        "evaluation": eval_res,
        "artifacts": {
            "forecasts_csv": str(forecast_path.relative_to(OUT_DIR)),
            "exposure_summary_csv": "k1596_exposure_summary.csv",
            "figures": fig_paths,
        },
        "literature_checked": [
            {
                "title": "Multiplicative factor model for volatility",
                "authors": "Ding, Engle, Li, Zheng",
                "venue": "Journal of Econometrics 249, 105959",
                "doi": "10.1016/j.jeconom.2025.105959",
                "url": "https://ideas.repec.org/a/eee/econom/v249y2025ipbs0304407625000132.html",
            },
            {
                "title": "Modelling Volatility Cycles: The MF2-GARCH Model",
                "authors": "Conrad and Engle",
                "venue": "Journal of Applied Econometrics 40(4), 438-454",
                "doi": "10.1002/jae.3118",
                "url": "https://onlinelibrary.wiley.com/doi/abs/10.1002/jae.3118",
            },
            {
                "title": "Volatility comovement: A multifrequency approach",
                "authors": "Calvet, Fisher, Thompson",
                "venue": "Journal of Econometrics 131(1-2), 179-215",
                "doi": "10.1016/j.jeconom.2005.01.008",
                "url": "https://doi.org/10.1016/j.jeconom.2005.01.008",
            },
            {
                "title": "Volatility forecast comparison using imperfect volatility proxies",
                "authors": "Patton",
                "venue": "Journal of Econometrics 160(1), 246-256",
                "url": "https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf",
            },
        ],
    }

    result_path = OUT_DIR / "k1596_results.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "result_file": str(result_path),
                "verdict": eval_res["conclusion"]["verdict"],
                "mvf_best_mean_qlike_assets": eval_res["conclusion"]["mvf_best_mean_qlike_assets"],
                "mvf_strict_holm_wins_all_pairs": eval_res["conclusion"]["mvf_strict_holm_wins_all_pairs"],
                "mvf_strict_holm_wins_vs_gjr": eval_res["conclusion"]["mvf_strict_holm_wins_vs_gjr"],
                "mvf_strict_holm_losses": eval_res["conclusion"]["mvf_strict_holm_losses"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
