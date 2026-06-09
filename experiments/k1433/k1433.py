#!/usr/bin/env python3
"""K1433: BTC weekend/weekday seasonality in daily range-vol forecasting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT.parent / "k1119" / "data" / "btc_ohlcv.csv"
RESULT_PATH = ROOT / "k1433_results.json"
FIG_WEEKDAY = ROOT / "k1433_weekday_boxplot.png"
FIG_CUMQLIKE = ROOT / "k1433_cum_qlike_diff.png"

IS_END = pd.Timestamp("2023-12-31")
SEED = 42
np.random.seed(SEED)


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.rename(columns={"date": "Date"})
    df = df.sort_values("Date").set_index("Date")
    df["parkinson_var"] = (np.log(df["High"] / df["Low"]) ** 2) / (4.0 * np.log(2.0))
    df["log_rv"] = np.log(df["parkinson_var"].clip(lower=1e-12))
    df["dow"] = df.index.dayofweek
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["log_rv_l1"] = df["log_rv"].shift(1)
    df["log_rv_7"] = df["log_rv"].shift(1).rolling(7).mean()
    df["log_rv_30"] = df["log_rv"].shift(1).rolling(30).mean()
    for dow in range(1, 7):
        name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dow]
        df[f"dow_{name.lower()}"] = (df["dow"] == dow).astype(int)
    df = df.dropna()
    return df


def fit_ols(y: pd.Series, x: pd.DataFrame):
    model = sm.OLS(y, sm.add_constant(x)).fit()
    return model


def qlike(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    a = np.asarray(actual)
    f = np.asarray(forecast)
    valid = np.isfinite(a) & np.isfinite(f) & (a > 0) & (f > 0)
    out = np.full_like(a, np.nan, dtype=float)
    out[valid] = np.log(f[valid]) + a[valid] / f[valid]
    return out


def dm_test(loss_base: np.ndarray, loss_alt: np.ndarray) -> dict:
    d = np.asarray(loss_base) - np.asarray(loss_alt)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 20:
        return {"n": n, "t_stat": None, "p_value": None, "mean_diff": None}
    mean_d = d.mean()
    gamma0 = np.var(d, ddof=1)
    se = np.sqrt(max(gamma0, 1e-18) / n)
    t_stat = mean_d / se
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return {
        "n": int(n),
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "mean_diff": float(mean_d),
    }


def oos_forecast(df: pd.DataFrame, features: list[str]) -> dict:
    train_mask = df.index <= IS_END
    test_mask = df.index > IS_END
    test_dates = df.index[test_mask]

    preds_log = []
    preds_level = []
    actual = []

    for dt in test_dates:
        hist = df.loc[df.index < dt]
        y = hist["log_rv"]
        x = hist[features]
        model = fit_ols(y, x)
        x_t = sm.add_constant(df.loc[[dt], features], has_constant="add")
        pred_log = float(model.predict(x_t).iloc[0])
        pred_level = float(np.exp(pred_log))
        preds_log.append(pred_log)
        preds_level.append(pred_level)
        actual.append(float(df.loc[dt, "parkinson_var"]))

    actual_arr = np.asarray(actual)
    pred_arr = np.asarray(preds_level)
    ql = qlike(actual_arr, pred_arr)
    mse = (actual_arr - pred_arr) ** 2
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in test_dates],
        "actual": actual_arr,
        "pred_level": pred_arr,
        "pred_log": np.asarray(preds_log),
        "qlike_series": ql,
        "mse_series": mse,
        "qlike_mean": float(np.nanmean(ql)),
        "mse_mean": float(np.nanmean(mse)),
    }


def weekday_summary(df: pd.DataFrame) -> dict:
    rows = {}
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, name in enumerate(names):
        sub = df[df["dow"] == i]
        rows[name] = {
            "n": int(len(sub)),
            "mean_rv": float(sub["parkinson_var"].mean()),
            "median_rv": float(sub["parkinson_var"].median()),
            "mean_log_rv": float(sub["log_rv"].mean()),
        }
    weekend = df[df["is_weekend"] == 1]["log_rv"]
    weekday = df[df["is_weekend"] == 0]["log_rv"]
    welch = stats.ttest_ind(weekend, weekday, equal_var=False)
    premium = np.exp(weekend.mean() - weekday.mean()) - 1.0
    return {
        "by_day": rows,
        "weekend_vs_weekday": {
            "n_weekend": int(len(weekend)),
            "n_weekday": int(len(weekday)),
            "mean_log_diff": float(weekend.mean() - weekday.mean()),
            "approx_level_premium": float(premium),
            "welch_t": float(welch.statistic),
            "welch_p": float(welch.pvalue),
        },
    }


def hac_regression(df: pd.DataFrame, features: list[str]) -> dict:
    model = fit_ols(df["log_rv"], df[features])
    robust = model.get_robustcov_results(cov_type="HAC", maxlags=7)
    params = {}
    for name, coef, tval, pval in zip(robust.model.exog_names, robust.params, robust.tvalues, robust.pvalues):
        params[name] = {
            "coef": float(coef),
            "t_stat": float(tval),
            "p_value": float(pval),
        }
    return {
        "n_obs": int(model.nobs),
        "r2": float(model.rsquared),
        "adj_r2": float(model.rsquared_adj),
        "params": params,
    }


def make_figures(df: pd.DataFrame, forecasts: dict[str, dict]) -> None:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    box_data = [df.loc[df["dow"] == i, "log_rv"].values for i in range(7)]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.boxplot(box_data, labels=names, showfliers=False)
    ax.set_title("K1433: BTC log(Parkinson RV) by Weekday")
    ax.set_ylabel("log(RV)")
    fig.tight_layout()
    fig.savefig(FIG_WEEKDAY, dpi=160)
    plt.close(fig)

    base = forecasts["har"]["qlike_series"]
    fig, ax = plt.subplots(figsize=(10, 5))
    for key, label in [("har_weekend", "HAR + weekend"), ("har_weekday", "HAR + weekday")]:
        diff = base - forecasts[key]["qlike_series"]
        ax.plot(np.nancumsum(diff), label=label)
    ax.axhline(0.0, color="black", linewidth=1, linestyle="--")
    ax.set_title("Cumulative QLIKE Gain vs HAR Baseline")
    ax.set_ylabel("Cumulative (QLIKE_HAR - QLIKE_alt)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_CUMQLIKE, dpi=160)
    plt.close(fig)


def main() -> None:
    df = load_data()

    feature_sets = {
        "har": ["log_rv_l1", "log_rv_7", "log_rv_30"],
        "har_weekend": ["log_rv_l1", "log_rv_7", "log_rv_30", "is_weekend"],
        "har_weekday": [
            "log_rv_l1", "log_rv_7", "log_rv_30",
            "dow_tue", "dow_wed", "dow_thu", "dow_fri", "dow_sat", "dow_sun",
        ],
    }

    forecasts = {name: oos_forecast(df, feats) for name, feats in feature_sets.items()}
    regressions = {name: hac_regression(df, feats) for name, feats in feature_sets.items()}
    summary = weekday_summary(df)
    make_figures(df, forecasts)

    dm_weekend = dm_test(forecasts["har"]["qlike_series"], forecasts["har_weekend"]["qlike_series"])
    dm_weekday = dm_test(forecasts["har"]["qlike_series"], forecasts["har_weekday"]["qlike_series"])

    result = {
        "experiment_id": "K1433",
        "title": "BTC weekend / weekday seasonality in HAR-style daily range-vol forecasting",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": {
            "file": str(DATA_PATH.relative_to(ROOT.parent.parent)),
            "asset": "BTC-USD",
            "date_start": df.index.min().strftime("%Y-%m-%d"),
            "date_end": df.index.max().strftime("%Y-%m-%d"),
            "n_obs": int(len(df)),
        },
        "methodology": {
            "target": "Parkinson variance proxy from daily high/low",
            "transform": "log(RV)",
            "baseline": "HAR(1,7,30)",
            "oos_design": "Expanding-window one-step forecast",
            "is_end": IS_END.strftime("%Y-%m-%d"),
            "oos_start": (df.index[df.index > IS_END].min()).strftime("%Y-%m-%d"),
            "seed": SEED,
            "lookahead_policy": {
                "log_rv_l1": "shift(1)",
                "log_rv_7": "shift(1).rolling(7).mean()",
                "log_rv_30": "shift(1).rolling(30).mean()",
                "calendar_dummies": "forecast-day calendar known ex ante",
            },
        },
        "descriptive_stats": summary,
        "full_sample_regressions_hac7": regressions,
        "oos": {
            name: {
                "qlike_mean": forecasts[name]["qlike_mean"],
                "mse_mean": forecasts[name]["mse_mean"],
                "n_oos": int(len(forecasts[name]["actual"])),
            }
            for name in forecasts
        },
        "dm_tests": {
            "har_vs_har_weekend": dm_weekend,
            "har_vs_har_weekday": dm_weekday,
        },
        "artifacts": {
            "weekday_boxplot": FIG_WEEKDAY.name,
            "cum_qlike_diff": FIG_CUMQLIKE.name,
        },
    }

    with open(RESULT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({
        "ok": True,
        "result_path": str(RESULT_PATH),
        "qlike_har": forecasts["har"]["qlike_mean"],
        "qlike_har_weekend": forecasts["har_weekend"]["qlike_mean"],
        "qlike_har_weekday": forecasts["har_weekday"]["qlike_mean"],
        "dm_weekend": dm_weekend,
        "dm_weekday": dm_weekday,
    }, indent=2))


if __name__ == "__main__":
    main()
