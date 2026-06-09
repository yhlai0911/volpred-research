#!/usr/bin/env python3
"""K1434: TWII volatility around clustered Q1 earnings announcement days."""

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
PROJECT_ROOT = ROOT.parent.parent
TWII_PATH = PROJECT_ROOT / "storage" / "macro" / "yf_TWII.csv"
EA_PATH = PROJECT_ROOT / "財報公告日.txt"
RESULT_PATH = ROOT / "k1434_results.json"
FIG_COUNTS = ROOT / "k1434_cluster_counts.png"
FIG_CUMQLIKE = ROOT / "k1434_cum_qlike_diff.png"

IS_END = pd.Timestamp("2020-12-31")
START_DATE = pd.Timestamp("2014-01-01")
END_DATE = pd.Timestamp("2026-05-31")
SEED = 42
np.random.seed(SEED)

TWSE50_TICKERS = [
    '2330.TW','2454.TW','2317.TW','2308.TW','2303.TW','2412.TW','2002.TW','2382.TW',
    '2357.TW','2327.TW','1303.TW','1301.TW','1326.TW','2886.TW','2891.TW','2882.TW',
    '2884.TW','2881.TW','2892.TW','5880.TW','2885.TW','6505.TW','1402.TW','2408.TW',
    '3711.TW','4938.TW','2379.TW','3034.TW','2395.TW','6669.TW','2301.TW','2356.TW',
    '2324.TW','2353.TW','2880.TW','2883.TW','2887.TW','2890.TW','5871.TW','6415.TW',
    '3008.TW','2377.TW','2376.TW','3481.TW','2474.TW','2609.TW','2615.TW','2603.TW',
    '9910.TW','1216.TW',
]


def load_twii() -> pd.DataFrame:
    df = pd.read_csv(TWII_PATH, skiprows=[0, 1])
    df.columns = ["Date", "Close", "High", "Low", "Open", "Volume"]
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").set_index("Date")
    df = df.loc[(df.index >= START_DATE) & (df.index <= END_DATE)].copy()
    df["parkinson_var"] = (np.log(df["High"] / df["Low"]) ** 2) / (4.0 * np.log(2.0))
    df["log_rv"] = np.log(df["parkinson_var"].clip(lower=1e-12))
    df["log_rv_l1"] = df["log_rv"].shift(1)
    df["log_rv_7"] = df["log_rv"].shift(1).rolling(7).mean()
    df["log_rv_30"] = df["log_rv"].shift(1).rolling(30).mean()
    return df


def load_q1_cluster_series(index: pd.DatetimeIndex) -> pd.DataFrame:
    raw = EA_PATH.read_bytes().decode("big5", errors="replace").splitlines()
    records = []
    valid_codes = {t.replace(".TW", "") for t in TWSE50_TICKERS}
    for line in raw[1:]:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        code = parts[0].strip()
        ym = parts[2].strip()
        date_str = parts[3].strip()
        if code not in valid_codes or not date_str:
            continue
        if not ym.endswith("03"):
            continue
        try:
            dt = pd.Timestamp(date_str.replace("/", "-"))
        except Exception:
            continue
        if START_DATE <= dt <= END_DATE:
            records.append((dt, code, ym))

    ea = pd.DataFrame(records, columns=["date", "code", "ym"])
    daily = ea.groupby("date").size().rename("q1_cluster_count").to_frame()
    out = pd.DataFrame(index=index).join(daily, how="left").fillna(0.0)
    out["q1_cluster_count"] = out["q1_cluster_count"].astype(int)
    out["q1_cluster_day"] = (out["q1_cluster_count"] >= 3).astype(int)
    out["q1_cluster_count_l1"] = out["q1_cluster_count"].shift(1)
    out["q1_cluster_day_l1"] = out["q1_cluster_day"].shift(1)
    return out, ea


def fit_ols(y: pd.Series, x: pd.DataFrame):
    return sm.OLS(y, sm.add_constant(x)).fit()


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
    return {"n": int(n), "t_stat": float(t_stat), "p_value": float(p_value), "mean_diff": float(mean_d)}


def oos_forecast(df: pd.DataFrame, features: list[str]) -> dict:
    test_dates = df.index[df.index > IS_END]
    preds = []
    actual = []
    for dt in test_dates:
        hist = df.loc[df.index < dt]
        model = fit_ols(hist["log_rv"], hist[features])
        x_t = sm.add_constant(df.loc[[dt], features], has_constant="add")
        pred_log = float(model.predict(x_t).iloc[0])
        preds.append(float(np.exp(pred_log)))
        actual.append(float(df.loc[dt, "parkinson_var"]))
    actual_arr = np.asarray(actual)
    pred_arr = np.asarray(preds)
    ql = qlike(actual_arr, pred_arr)
    mse = (actual_arr - pred_arr) ** 2
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in test_dates],
        "actual": actual_arr,
        "pred": pred_arr,
        "qlike_series": ql,
        "mse_series": mse,
        "qlike_mean": float(np.nanmean(ql)),
        "mse_mean": float(np.nanmean(mse)),
    }


def hac_regression(df: pd.DataFrame, features: list[str]) -> dict:
    robust = fit_ols(df["log_rv"], df[features]).get_robustcov_results(cov_type="HAC", maxlags=7)
    params = {}
    for name, coef, tval, pval in zip(robust.model.exog_names, robust.params, robust.tvalues, robust.pvalues):
        params[name] = {"coef": float(coef), "t_stat": float(tval), "p_value": float(pval)}
    return {"n_obs": int(robust.nobs), "r2": float(robust.rsquared), "adj_r2": float(robust.rsquared_adj), "params": params}


def descriptive_stats(df: pd.DataFrame, ea: pd.DataFrame) -> dict:
    cluster_days = df[df["q1_cluster_count"] > 0]
    non_cluster = df[df["q1_cluster_count"] == 0]
    high_cluster = df[df["q1_cluster_day"] == 1]
    low_cluster = df[(df["q1_cluster_count"] > 0) & (df["q1_cluster_day"] == 0)]
    welch = stats.ttest_ind(cluster_days["log_rv"], non_cluster["log_rv"], equal_var=False)
    welch_high = stats.ttest_ind(high_cluster["log_rv"], low_cluster["log_rv"], equal_var=False) if len(low_cluster) else (np.nan, np.nan)
    return {
        "n_q1_announcements": int(len(ea)),
        "n_unique_q1_dates": int(ea["date"].nunique()),
        "cluster_count_distribution": df["q1_cluster_count"].value_counts().sort_index().to_dict(),
        "cluster_vs_noncluster": {
            "n_cluster_days": int(len(cluster_days)),
            "n_noncluster_days": int(len(non_cluster)),
            "mean_log_rv_cluster": float(cluster_days["log_rv"].mean()),
            "mean_log_rv_noncluster": float(non_cluster["log_rv"].mean()),
            "welch_t": float(welch.statistic),
            "welch_p": float(welch.pvalue),
        },
        "high_cluster_vs_low_cluster": {
            "n_high_cluster_days": int(len(high_cluster)),
            "n_low_cluster_days": int(len(low_cluster)),
            "mean_log_rv_high": float(high_cluster["log_rv"].mean()) if len(high_cluster) else None,
            "mean_log_rv_low": float(low_cluster["log_rv"].mean()) if len(low_cluster) else None,
            "welch_t": float(welch_high.statistic) if len(low_cluster) else None,
            "welch_p": float(welch_high.pvalue) if len(low_cluster) else None,
        },
    }


def make_figures(df: pd.DataFrame, forecasts: dict[str, dict]) -> None:
    cluster_sub = df.loc[df["q1_cluster_count"] > 0, ["q1_cluster_count"]].copy()
    yearly = cluster_sub.groupby(cluster_sub.index.year)["q1_cluster_count"].sum()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(yearly.index.astype(str), yearly.values)
    ax.set_title("K1434: TWSE50 Q1 Earnings Cluster Counts by Year")
    ax.set_ylabel("Total Q1 announcements on trading dates")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(FIG_COUNTS, dpi=160)
    plt.close(fig)

    base = forecasts["har"]["qlike_series"]
    fig, ax = plt.subplots(figsize=(10, 5))
    for key, label in [("har_cluster_count", "HAR + cluster_count"), ("har_cluster_day", "HAR + cluster_day")]:
        ax.plot(np.nancumsum(base - forecasts[key]["qlike_series"]), label=label)
    ax.axhline(0, color="black", linestyle="--", linewidth=1)
    ax.set_title("Cumulative QLIKE Gain vs HAR Baseline")
    ax.set_ylabel("Cumulative (QLIKE_HAR - QLIKE_alt)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_CUMQLIKE, dpi=160)
    plt.close(fig)


def main() -> None:
    twii = load_twii()
    cluster_df, ea = load_q1_cluster_series(twii.index)
    df = twii.join(cluster_df, how="left")
    df = df.dropna()

    feature_sets = {
        "har": ["log_rv_l1", "log_rv_7", "log_rv_30"],
        "har_cluster_count": ["log_rv_l1", "log_rv_7", "log_rv_30", "q1_cluster_count_l1"],
        "har_cluster_day": ["log_rv_l1", "log_rv_7", "log_rv_30", "q1_cluster_day_l1"],
    }

    forecasts = {k: oos_forecast(df, v) for k, v in feature_sets.items()}
    regs = {k: hac_regression(df, v) for k, v in feature_sets.items()}
    desc = descriptive_stats(df, ea)
    make_figures(df, forecasts)

    result = {
        "experiment_id": "K1434",
        "title": "TWII volatility around clustered Q1 earnings announcement days",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": {
            "twii_file": str(TWII_PATH.relative_to(PROJECT_ROOT)),
            "earnings_file": str(EA_PATH.relative_to(PROJECT_ROOT)),
            "twii_start": df.index.min().strftime("%Y-%m-%d"),
            "twii_end": df.index.max().strftime("%Y-%m-%d"),
            "n_obs": int(len(df)),
        },
        "methodology": {
            "target": "TWII Parkinson variance proxy",
            "transform": "log(RV)",
            "cluster_definition": "TWSE50 Q1 earnings announcement count per trading date; cluster_day=1{count>=3}",
            "is_end": IS_END.strftime("%Y-%m-%d"),
            "oos_start": df.index[df.index > IS_END].min().strftime("%Y-%m-%d"),
            "seed": SEED,
            "lookahead_policy": {
                "har_terms": "shift(1)",
                "cluster_terms": "announcement density on t used only via shift(1) to predict t+1",
            },
        },
        "descriptive_stats": desc,
        "full_sample_regressions_hac7": regs,
        "oos": {
            k: {"qlike_mean": forecasts[k]["qlike_mean"], "mse_mean": forecasts[k]["mse_mean"], "n_oos": int(len(forecasts[k]["actual"]))}
            for k in forecasts
        },
        "dm_tests": {
            "har_vs_har_cluster_count": dm_test(forecasts["har"]["qlike_series"], forecasts["har_cluster_count"]["qlike_series"]),
            "har_vs_har_cluster_day": dm_test(forecasts["har"]["qlike_series"], forecasts["har_cluster_day"]["qlike_series"]),
        },
        "artifacts": {
            "cluster_counts": FIG_COUNTS.name,
            "cum_qlike_diff": FIG_CUMQLIKE.name,
        },
    }

    with open(RESULT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({
        "ok": True,
        "result_path": str(RESULT_PATH),
        "qlike_har": forecasts["har"]["qlike_mean"],
        "qlike_count": forecasts["har_cluster_count"]["qlike_mean"],
        "qlike_day": forecasts["har_cluster_day"]["qlike_mean"],
        "dm_count": result["dm_tests"]["har_vs_har_cluster_count"],
        "dm_day": result["dm_tests"]["har_vs_har_cluster_day"],
    }, indent=2))


if __name__ == "__main__":
    main()
