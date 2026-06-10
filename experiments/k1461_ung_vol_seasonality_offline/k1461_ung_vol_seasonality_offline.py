#!/usr/bin/env python3
"""
K1461: UNG realized volatility seasonality under offline DBA constraint.

Question:
    Does UNG realized volatility show a statistically significant month-of-year
    pattern, and how much of its variation co-moves with energy and inflation
    proxies available locally?

Constraint:
    DBA raw OHLC is not available in the local repository, and network access is
    blocked in this sandbox, so the original UNG/DBA pair cannot be fully
    reconstructed. This experiment therefore treats DBA as an explicit blocked
    leg and completes an honest UNG-only partial replication.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm


ROOT = Path(__file__).resolve().parent
SEED = 42
UNG_PATH = Path("experiments/k1422/data/UNG.csv")
USO_PATH = Path("experiments/k1422/data/USO.csv")
CPI_PATH = Path("storage/macro/fred_CPIAUCSL.csv")
T10YIE_PATH = Path("storage/macro/fred_T10YIE.csv")


def load_ohlc(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df[["Date", "Open", "High", "Low", "Close"]].copy()
    df = df.sort_values("Date").dropna()
    df = df.set_index("Date")
    return df


def load_fred_series(path: Path, value_name: str) -> pd.Series:
    df = pd.read_csv(path)
    date_col = df.columns[0]
    value_col = df.columns[1]
    out = df.rename(columns={date_col: "Date", value_col: value_name})
    out["Date"] = pd.to_datetime(out["Date"])
    out[value_name] = pd.to_numeric(out[value_name], errors="coerce")
    return out.set_index("Date")[value_name].dropna()


def parkinson_vol(df: pd.DataFrame, window: int = 21) -> pd.Series:
    hl = np.log(df["High"] / df["Low"])
    daily_var = (hl ** 2) / (4 * np.log(2))
    return np.sqrt(252 * daily_var.rolling(window).mean()).dropna()


def close_to_close_vol(df: pd.DataFrame, window: int = 21) -> pd.Series:
    ret = np.log(df["Close"] / df["Close"].shift(1))
    return (ret.rolling(window).std() * np.sqrt(252)).dropna()


def month_seasonality_test(series: pd.Series, seed: int = SEED) -> dict:
    groups = [grp.values for _, grp in series.groupby(series.index.month)]
    f_stat, p_anova = stats.f_oneway(*groups)

    rng = np.random.default_rng(seed)
    month_labels = series.index.month.to_numpy()
    values = series.to_numpy()
    perm_stats = []
    for _ in range(2000):
        shuffled = rng.permutation(month_labels)
        perm_groups = [values[shuffled == m] for m in range(1, 13)]
        perm_stats.append(stats.f_oneway(*perm_groups).statistic)
    perm_stats = np.asarray(perm_stats)
    p_perm = float(np.mean(perm_stats >= f_stat))

    monthly = (
        series.groupby(series.index.month)
        .agg(["mean", "median", "std", "count"])
        .rename_axis("calendar_month")
        .reset_index()
    )
    monthly["month_name"] = monthly["calendar_month"].map(
        {
            1: "Jan",
            2: "Feb",
            3: "Mar",
            4: "Apr",
            5: "May",
            6: "Jun",
            7: "Jul",
            8: "Aug",
            9: "Sep",
            10: "Oct",
            11: "Nov",
            12: "Dec",
        }
    )
    top_month = monthly.sort_values("mean", ascending=False).iloc[0]
    bot_month = monthly.sort_values("mean", ascending=True).iloc[0]

    return {
        "anova_f_stat": float(f_stat),
        "anova_p_value": float(p_anova),
        "permutation_p_value": p_perm,
        "monthly_table": monthly.to_dict(orient="records"),
        "top_month": {
            "calendar_month": int(top_month["calendar_month"]),
            "month_name": str(top_month["month_name"]),
            "mean": float(top_month["mean"]),
        },
        "bottom_month": {
            "calendar_month": int(bot_month["calendar_month"]),
            "month_name": str(bot_month["month_name"]),
            "mean": float(bot_month["mean"]),
        },
    }


def monthly_proxy_frame(
    ung_cc: pd.Series,
    ung_pk: pd.Series,
    uso_cc: pd.Series,
    t10yie: pd.Series,
    cpi: pd.Series,
) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "ung_rv_cc": ung_cc.resample("ME").mean(),
            "ung_rv_pk": ung_pk.resample("ME").mean(),
            "uso_rv_cc": uso_cc.resample("ME").mean(),
            "t10yie": t10yie.resample("ME").last(),
            "cpi": cpi.resample("ME").last(),
        }
    ).dropna()
    df["cpi_yoy"] = df["cpi"].pct_change(12) * 100
    df["uso_rv_cc_lag1"] = df["uso_rv_cc"].shift(1)
    df["t10yie_lag1"] = df["t10yie"].shift(1)
    df["ung_rv_cc_lag1"] = df["ung_rv_cc"].shift(1)
    return df.dropna()


def hac_regression(df: pd.DataFrame) -> dict:
    y = df["ung_rv_cc"]
    x = df[["ung_rv_cc_lag1", "uso_rv_cc_lag1", "t10yie_lag1"]]
    x = sm.add_constant(x)
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
    return {
        "n_obs": int(model.nobs),
        "r_squared": float(model.rsquared),
        "adj_r_squared": float(model.rsquared_adj),
        "params": {k: float(v) for k, v in model.params.items()},
        "tvalues": {k: float(v) for k, v in model.tvalues.items()},
        "pvalues": {k: float(v) for k, v in model.pvalues.items()},
    }


def save_figure(
    daily_pk: pd.Series,
    monthly_stats: list[dict],
    proxy_df: pd.DataFrame,
    out_path: Path,
) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(11, 12), constrained_layout=True)

    axes[0].plot(daily_pk.index.to_pydatetime(), daily_pk.to_numpy(), color="#1f4e79", lw=1.0)
    axes[0].set_title("UNG 21d Parkinson Realized Volatility")
    axes[0].set_ylabel("Annualized vol")
    axes[0].grid(alpha=0.2)

    month_labels = [row["month_name"] for row in monthly_stats]
    month_means = [row["mean"] for row in monthly_stats]
    axes[1].bar(month_labels, month_means, color="#d68000")
    axes[1].set_title("UNG Volatility by Calendar Month")
    axes[1].set_ylabel("Mean 21d vol")
    axes[1].grid(axis="y", alpha=0.2)

    ax2 = axes[2]
    ax2.plot(proxy_df.index.to_pydatetime(), proxy_df["ung_rv_cc"].to_numpy(), label="UNG RV", color="#1f4e79")
    ax2.plot(proxy_df.index.to_pydatetime(), proxy_df["uso_rv_cc"].to_numpy(), label="USO RV", color="#6a3d9a", alpha=0.8)
    ax2.set_ylabel("Monthly avg vol")
    ax2.set_title("UNG vs USO Volatility Proxy")
    ax2.grid(alpha=0.2)
    ax2.legend(loc="upper left")

    ax3 = ax2.twinx()
    ax3.plot(proxy_df.index.to_pydatetime(), proxy_df["t10yie"].to_numpy(), label="T10YIE", color="#2ca25f", alpha=0.7)
    ax3.set_ylabel("Breakeven inflation (%)")

    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def main() -> None:
    ung = load_ohlc(UNG_PATH)
    uso = load_ohlc(USO_PATH)
    cpi = load_fred_series(CPI_PATH, "CPIAUCSL")
    t10yie = load_fred_series(T10YIE_PATH, "T10YIE")

    ung_cc = close_to_close_vol(ung)
    ung_pk = parkinson_vol(ung)
    uso_cc = close_to_close_vol(uso)

    season_cc = month_seasonality_test(ung_cc)
    season_pk = month_seasonality_test(ung_pk)

    proxy_df = monthly_proxy_frame(ung_cc, ung_pk, uso_cc, t10yie, cpi)

    corr_same_uso = stats.pearsonr(proxy_df["ung_rv_cc"], proxy_df["uso_rv_cc"])
    corr_lag_uso = stats.pearsonr(proxy_df["ung_rv_cc"], proxy_df["uso_rv_cc_lag1"])
    corr_same_t10y = stats.pearsonr(proxy_df["ung_rv_cc"], proxy_df["t10yie"])
    corr_lag_t10y = stats.pearsonr(proxy_df["ung_rv_cc"], proxy_df["t10yie_lag1"])
    corr_same_cpi = stats.pearsonr(proxy_df["ung_rv_cc"], proxy_df["cpi_yoy"])

    reg = hac_regression(proxy_df)

    fig_path = ROOT / "k1461_ung_vol_seasonality.png"
    save_figure(ung_pk, season_pk["monthly_table"], proxy_df, fig_path)

    results = {
        "experiment_id": "k1461",
        "title": "UNG realized volatility seasonality under offline DBA constraint",
        "seed": SEED,
        "constraint": {
            "dba_local_ohlc_available": False,
            "network_download_available": False,
            "note": "DBA raw yfinance data could not be reconstructed in this offline sandbox; results are UNG-only."
        },
        "data_sources": {
            "ung": str(UNG_PATH),
            "uso": str(USO_PATH),
            "cpi": str(CPI_PATH),
            "t10yie": str(T10YIE_PATH),
        },
        "sample": {
            "ung_start": str(ung.index.min().date()),
            "ung_end": str(ung.index.max().date()),
            "ung_n_daily_rows": int(len(ung)),
            "proxy_monthly_rows": int(len(proxy_df)),
        },
        "seasonality_close_to_close": season_cc,
        "seasonality_parkinson": season_pk,
        "proxy_relationships": {
            "same_month_corr_ung_vs_uso_rv": {
                "rho": float(corr_same_uso.statistic),
                "p_value": float(corr_same_uso.pvalue),
            },
            "lag1_corr_ung_vs_uso_rv": {
                "rho": float(corr_lag_uso.statistic),
                "p_value": float(corr_lag_uso.pvalue),
            },
            "same_month_corr_ung_vs_t10yie": {
                "rho": float(corr_same_t10y.statistic),
                "p_value": float(corr_same_t10y.pvalue),
            },
            "lag1_corr_ung_vs_t10yie": {
                "rho": float(corr_lag_t10y.statistic),
                "p_value": float(corr_lag_t10y.pvalue),
            },
            "same_month_corr_ung_vs_cpi_yoy": {
                "rho": float(corr_same_cpi.statistic),
                "p_value": float(corr_same_cpi.pvalue),
            },
        },
        "hac_regression_monthly": reg,
    }

    verdict = "NULL"
    if (
        results["seasonality_parkinson"]["permutation_p_value"] < 0.05
        or results["seasonality_close_to_close"]["permutation_p_value"] < 0.05
    ):
        verdict = "PARTIAL_SIGNAL"

    results["verdict"] = verdict
    results["summary"] = [
        f"UNG month-of-year seasonality verdict={verdict}",
        f"Parkinson permutation p={results['seasonality_parkinson']['permutation_p_value']:.4f}",
        f"UNG-USO same-month vol corr={results['proxy_relationships']['same_month_corr_ung_vs_uso_rv']['rho']:.3f}",
        "DBA leg blocked by missing local OHLC and offline sandbox",
    ]

    out_path = ROOT / "k1461_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
