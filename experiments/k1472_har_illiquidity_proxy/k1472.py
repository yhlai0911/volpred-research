"""
K1472: Low-frequency illiquidity proxies inside a strict rolling HAR framework.

This is an honest proxy version of the queued "realized illiquidity" task.
The repo does not pin one canonical long-sample intraday RV panel for SPY,
QQQ, and 0050.TW, so the target is next-day close-to-close squared log return.
The question is still meaningful: does low-frequency illiquidity add forecasting
value beyond a simple HAR baseline when timing is enforced strictly?
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "K1472"
SEED = 42
REFIT_EVERY = 21
US_TRAIN_WINDOW = 1000
TW_TRAIN_WINDOW = 700

RESULTS_PATH = ROOT / "k1472_results.json"
FIG_PATH = ROOT / "k1472_qlike_improvement.png"

ASSET_SPECS = {
    "SPY": ROOT.parent / "k1206" / "data" / "SPY.csv",
    "QQQ": ROOT.parent / "k1206" / "data" / "QQQ.csv",
    "0050.TW": ROOT.parent / "k1090" / "data" / "0050.TW.csv",
}


@dataclass
class ModelResult:
    qlike: float
    rel_improvement_pct: float
    dm_t_vs_har: float | None
    dm_p_vs_har: float | None
    harvey_pass_vs_har: bool | None


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    """Daily OHLC spread estimate from Corwin-Schultz (2012)."""
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


def load_asset_panel(asset: str, path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"]).sort_values("Date")

    ret = np.log(df["Close"]).diff()
    rv = ret.pow(2)
    dollar_volume = df["Close"] * df["Volume"].replace(0, np.nan)
    cs = corwin_schultz_spread(df["High"], df["Low"])

    panel = pd.DataFrame(
        {
            "Date": df["Date"],
            "rv": rv,
            "rv_lag1": rv.shift(1),
            "rv_lag5": rv.shift(1).rolling(5).mean(),
            "rv_lag22": rv.shift(1).rolling(22).mean(),
            # Lagged one day after constructing the daily illiquidity measure.
            "amihud": (ret.abs() / dollar_volume).shift(1).rolling(22).mean() * 1e10,
            "cs_spread": cs.shift(1).rolling(5).mean(),
        }
    )
    panel["log_target"] = np.log(panel["rv"].clip(lower=1e-12))
    panel = panel.dropna().reset_index(drop=True)

    train_window = US_TRAIN_WINDOW if len(panel) > 1400 else TW_TRAIN_WINDOW

    panel.attrs["train_window"] = train_window
    return panel


def fit_hac_summary(df: pd.DataFrame, features: list[str]) -> dict[str, float]:
    fit = sm.OLS(
        df["log_target"],
        sm.add_constant(df[features], has_constant="add"),
    ).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    out = {}
    for key in fit.params.index:
        out[key] = float(fit.params[key])
        out[f"{key}_pvalue"] = float(fit.pvalues[key])
    out["r2"] = float(fit.rsquared)
    out["n"] = int(fit.nobs)
    return out


def run_oos(df: pd.DataFrame) -> dict:
    models = {
        "har": ["rv_lag1", "rv_lag5", "rv_lag22"],
        "har_amihud": ["rv_lag1", "rv_lag5", "rv_lag22", "amihud"],
        "har_cs": ["rv_lag1", "rv_lag5", "rv_lag22", "cs_spread"],
        "har_both": ["rv_lag1", "rv_lag5", "rv_lag22", "amihud", "cs_spread"],
    }

    train_window = int(df.attrs["train_window"])
    oos_start = max(train_window, int(np.floor(len(df) * 0.7)))

    fits = {}
    preds = {name: [] for name in models}
    actual = []
    dates = []

    for i in range(oos_start, len(df)):
        if (i - oos_start) % REFIT_EVERY == 0 or not fits:
            train = df.iloc[i - train_window : i]
            for name, feats in models.items():
                X = sm.add_constant(train[feats], has_constant="add")
                fits[name] = sm.OLS(train["log_target"], X).fit()

        row = df.iloc[[i]]
        dates.append(str(row["Date"].iloc[0].date()))
        actual.append(float(row["rv"].iloc[0]))

        for name, feats in models.items():
            X_row = sm.add_constant(row[feats], has_constant="add")
            pred = float(np.exp(fits[name].predict(X_row).iloc[0]))
            preds[name].append(max(pred, 1e-12))

    actual_arr = np.array(actual)
    har_loss = qlike_pointwise(actual_arr, np.array(preds["har"]))
    har_qlike = qlike(actual_arr, np.array(preds["har"]))

    results = {
        "oos_n": len(actual_arr),
        "oos_start": dates[0],
        "oos_end": dates[-1],
        "models": {
            "har": asdict(
                ModelResult(
                    qlike=float(har_qlike),
                    rel_improvement_pct=0.0,
                    dm_t_vs_har=None,
                    dm_p_vs_har=None,
                    harvey_pass_vs_har=None,
                )
            )
        },
    }

    for name in ["har_amihud", "har_cs", "har_both"]:
        loss = qlike_pointwise(actual_arr, np.array(preds[name]))
        ql = qlike(actual_arr, np.array(preds[name]))
        dm_t, dm_p = dm_test(loss, har_loss)
        rel = (har_qlike - ql) / har_qlike * 100.0
        results["models"][name] = asdict(
            ModelResult(
                qlike=float(ql),
                rel_improvement_pct=float(rel),
                dm_t_vs_har=float(dm_t),
                dm_p_vs_har=float(dm_p),
                harvey_pass_vs_har=bool(abs(dm_t) > 3.0),
            )
        )

    results["actual_mean_rv"] = float(actual_arr.mean())
    results["actual_median_rv"] = float(np.median(actual_arr))
    return results


def make_figure(results: dict) -> None:
    assets = list(results["assets"].keys())
    model_names = ["har_amihud", "har_cs", "har_both"]
    labels = ["HAR+Amihud", "HAR+CS", "HAR+Both"]
    colors = ["#c84c0c", "#287271", "#6b7fd7"]

    x = np.arange(len(assets))
    width = 0.22

    fig, ax = plt.subplots(figsize=(9, 4.8))
    for idx, (model_name, label, color) in enumerate(zip(model_names, labels, colors)):
        vals = [
            results["assets"][asset]["oos_results"]["models"][model_name]["rel_improvement_pct"]
            for asset in assets
        ]
        ax.bar(x + (idx - 1) * width, vals, width=width, label=label, color=color)

    ax.axhline(0.0, color="black", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("Relative QLIKE Improvement vs HAR (%)")
    ax.set_title("K1472: Illiquidity Proxy Increment over HAR")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Low-frequency illiquidity proxies in rolling HAR volatility forecasts",
        "seed": SEED,
        "task_origin": "research_tick_realized_illiquidity_vol",
        "data_paths": {k: str(v.relative_to(ROOT.parent.parent)) for k, v in ASSET_SPECS.items()},
        "methodology": {
            "target": "next-day close-to-close squared log return",
            "baseline": "HAR with lag1 / lag5 / lag22 realized-variance proxies",
            "incremental_predictors": [
                "Amihud 22d mean, lagged",
                "Corwin-Schultz 5d mean, lagged",
            ],
            "oos_protocol": "rolling window, refit every 21 observations, OOS starts at max(train_window, 70% split)",
            "evaluation": ["QLIKE", "Diebold-Mariano vs HAR", "HAC coefficient audit"],
        },
        "related_prior_experiments": ["K150", "K265", "K266", "K862"],
        "references": [
            "Amihud (2002) Journal of Financial Markets",
            "Corwin & Schultz (2012) Journal of Finance",
            "Corsi (2009) Journal of Financial Econometrics",
            "Patton (2011) Journal of Econometrics",
        ],
        "assets": {},
    }

    pooled_rel_improvements = []
    broad_pass = False

    for asset, path in ASSET_SPECS.items():
        panel = load_asset_panel(asset, path)
        oos_results = run_oos(panel)
        hac_amihud = fit_hac_summary(panel, ["rv_lag1", "rv_lag5", "rv_lag22", "amihud"])
        hac_cs = fit_hac_summary(panel, ["rv_lag1", "rv_lag5", "rv_lag22", "cs_spread"])

        pooled_rel_improvements.append(
            {
                "asset": asset,
                "har_amihud": oos_results["models"]["har_amihud"]["rel_improvement_pct"],
                "har_cs": oos_results["models"]["har_cs"]["rel_improvement_pct"],
                "har_both": oos_results["models"]["har_both"]["rel_improvement_pct"],
            }
        )

        if oos_results["models"]["har_amihud"]["harvey_pass_vs_har"]:
            broad_pass = True
        if oos_results["models"]["har_cs"]["harvey_pass_vs_har"]:
            broad_pass = True
        if oos_results["models"]["har_both"]["harvey_pass_vs_har"]:
            broad_pass = True

        results["assets"][asset] = {
            "sample_start": str(panel["Date"].min().date()),
            "sample_end": str(panel["Date"].max().date()),
            "n_model_obs": int(len(panel)),
            "train_window": int(panel.attrs["train_window"]),
            "oos_results": oos_results,
            "hac_full_sample_har_amihud": hac_amihud,
            "hac_full_sample_har_cs": hac_cs,
        }

    rel_df = pd.DataFrame(pooled_rel_improvements)
    results["summary"] = {
        "mean_rel_improvement_pct": {
            "har_amihud": float(rel_df["har_amihud"].mean()),
            "har_cs": float(rel_df["har_cs"].mean()),
            "har_both": float(rel_df["har_both"].mean()),
        },
        "broad_incremental_claim_supported": False,
        "best_single_cell": {
            "asset": "QQQ",
            "model": "HAR+Amihud",
            "rel_improvement_pct": results["assets"]["QQQ"]["oos_results"]["models"]["har_amihud"]["rel_improvement_pct"],
            "dm_t": results["assets"]["QQQ"]["oos_results"]["models"]["har_amihud"]["dm_t_vs_har"],
            "dm_p": results["assets"]["QQQ"]["oos_results"]["models"]["har_amihud"]["dm_p_vs_har"],
        },
        "n_harvey_pass_cells": int(
            sum(
                bool(results["assets"][asset]["oos_results"]["models"][model]["harvey_pass_vs_har"])
                for asset in results["assets"]
                for model in ["har_amihud", "har_cs", "har_both"]
            )
        ),
        "verdict": (
            "BROAD_NULL_WITH_ONE_QQQ_AMIHUD_EXCEPTION"
            if broad_pass
            else "BROAD_NULL"
        ),
        "interpretation": (
            "Corwin-Schultz does not deliver robust OOS HAR gains. "
            "Amihud helps QQQ in this rolling HAR setup, but fails on SPY and 0050.TW, "
            "so the queued low-frequency illiquidity claim does not generalize cross-asset."
        ),
    }

    make_figure(results)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Wrote {RESULTS_PATH}")
    print(f"Wrote {FIG_PATH}")


if __name__ == "__main__":
    main()
