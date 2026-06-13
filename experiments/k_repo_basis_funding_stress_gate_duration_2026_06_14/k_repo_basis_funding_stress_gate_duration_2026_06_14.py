from __future__ import annotations

import io
import json
import math
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

EXPERIMENT_ID = "k_repo_basis_funding_stress_gate_duration_2026_06_14"
EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXPERIMENT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_SIGNAL_PATH = EXPERIMENT_DIR / "fig_stress_index_timeseries.png"
FIG_SCATTER_PATH = EXPERIMENT_DIR / "fig_tlt_scatter.png"

START_DATE = "2018-04-03"
CAP_DATE = "2026-06-13"
SEED = 42
BOOTSTRAP_B = 2000
BOOTSTRAP_BLOCK = 8
TRAIN_WEEKS = 104
NYFED_TIMEOUT = 30
YEARS = list(range(2018, 2027))


@dataclass
class AssetResult:
    asset: str
    n_obs: int
    is_mean_ann_rv: float
    oos_n: int
    stress_coef: float
    stress_t_hac: float
    stress_p_hac: float
    stress_boot_p: float
    baseline_qlike: float
    full_qlike: float
    qlike_delta: float
    dm_t_qlike: float
    dm_p_qlike: float
    oos_r2: float
    verdict: str


def fetch_nyfed_rate(rate_family: str, code: str) -> pd.DataFrame:
    url = (
        f"https://markets.newyorkfed.org/api/rates/{rate_family}/{code}/search.json"
        f"?startDate={START_DATE}&endDate={CAP_DATE}"
    )
    resp = requests.get(url, timeout=NYFED_TIMEOUT, verify=False)
    resp.raise_for_status()
    payload = resp.json()["refRates"]
    df = pd.DataFrame(payload)
    df["effectiveDate"] = pd.to_datetime(df["effectiveDate"])
    out = (
        df[["effectiveDate", "percentRate"]]
        .rename(columns={"effectiveDate": "date", "percentRate": code.lower()})
        .sort_values("date")
        .reset_index(drop=True)
    )
    return out


def fetch_cftc_financial(year: int) -> pd.DataFrame:
    url = f"https://www.cftc.gov/files/dea/history/com_fin_txt_{year}.zip"
    resp = requests.get(url, timeout=NYFED_TIMEOUT, verify=False)
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    with zf.open(zf.namelist()[0]) as fh:
        df = pd.read_csv(fh)
    return df


def build_cftc_proxy() -> pd.DataFrame:
    frames = [fetch_cftc_financial(year) for year in YEARS]
    df = pd.concat(frames, ignore_index=True)
    names = {
        "UST 10Y NOTE - CHICAGO BOARD OF TRADE": "ust10y_short_share",
        "UST BOND - CHICAGO BOARD OF TRADE": "ustbond_short_share",
    }
    df = df[df["Market_and_Exchange_Names"].isin(names)].copy()
    df["report_date"] = pd.to_datetime(df["Report_Date_as_YYYY-MM-DD"])
    df["release_date"] = df["report_date"] + pd.Timedelta(days=3)
    df["short_share"] = (
        pd.to_numeric(df["Lev_Money_Positions_Short_All"], errors="coerce")
        / pd.to_numeric(df["Open_Interest_All"], errors="coerce")
    )
    pivot = (
        df.pivot_table(
            index="release_date",
            columns="Market_and_Exchange_Names",
            values="short_share",
            aggfunc="last",
        )
        .rename(columns=names)
        .sort_index()
    )
    pivot["basis_short_proxy"] = pivot.mean(axis=1)
    return pivot.reset_index().rename(columns={"release_date": "date"})


def fetch_asset(asset: str) -> pd.DataFrame:
    df = yf.download(
        asset,
        start=START_DATE,
        end=(pd.Timestamp(CAP_DATE) + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=False,
    )
    if df.empty:
        raise RuntimeError(f"yfinance returned empty frame for {asset}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Adj Close"]].rename(columns={"Adj Close": "adj_close"}).dropna().copy()
    out.index = pd.to_datetime(out.index)
    return out


def make_weekly_asset_frame(asset: str) -> pd.DataFrame:
    px = fetch_asset(asset)
    px["log_ret"] = np.log(px["adj_close"]).diff()
    px["daily_rv"] = px["log_ret"] ** 2

    signal_fridays = pd.date_range(START_DATE, CAP_DATE, freq="W-FRI")
    rows = []
    for date in signal_fridays:
        hist = px.loc[:date]
        future = px.loc[px.index > date].head(5)
        if len(hist) < 5 or len(future) < 5:
            continue
        lag_rv = hist["daily_rv"].tail(5).sum() * (252 / 5)
        future_rv = future["daily_rv"].sum() * (252 / 5)
        rows.append(
            {
                "date": date,
                f"{asset}_lag_rv": lag_rv,
                f"{asset}_future_rv": future_rv,
            }
        )
    return pd.DataFrame(rows)


def expanding_zscore(series: pd.Series, min_periods: int = 52) -> pd.Series:
    mean = series.expanding(min_periods=min_periods).mean()
    std = series.expanding(min_periods=min_periods).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def qlike(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    y_pred = np.clip(y_pred, 1e-8, None)
    y_true = np.clip(y_true, 1e-8, None)
    return np.log(y_pred) + (y_true / y_pred)


def hac_t_p(diff: np.ndarray, lags: int = 4) -> tuple[float, float]:
    model = sm.OLS(diff, np.ones(len(diff)))
    fit = model.fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(fit.tvalues[0]), float(fit.pvalues[0])


def block_bootstrap_beta(df: pd.DataFrame, rng: np.random.Generator) -> float:
    n = len(df)
    if n < BOOTSTRAP_BLOCK:
        return float("nan")
    starts = np.arange(0, n - BOOTSTRAP_BLOCK + 1)
    betas = []
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    for _ in range(BOOTSTRAP_B):
        picks = rng.choice(starts, size=blocks_needed, replace=True)
        parts = [df.iloc[s : s + BOOTSTRAP_BLOCK] for s in picks]
        sample = pd.concat(parts, ignore_index=True).iloc[:n]
        X = sm.add_constant(sample[["log_lag_rv", "stress_index"]])
        y = sample["log_future_rv"]
        fit = sm.OLS(y, X).fit()
        betas.append(float(fit.params["stress_index"]))
    betas = np.asarray(betas)
    return float(2 * min((betas >= 0).mean(), (betas <= 0).mean()))


def fit_asset(panel: pd.DataFrame, asset: str, rng: np.random.Generator) -> AssetResult:
    work = panel[
        [
            "date",
            "stress_index",
            f"{asset}_lag_rv",
            f"{asset}_future_rv",
        ]
    ].dropna()
    work = work.rename(
        columns={
            f"{asset}_lag_rv": "lag_rv",
            f"{asset}_future_rv": "future_rv",
        }
    ).copy()
    work["log_lag_rv"] = np.log(work["lag_rv"])
    work["log_future_rv"] = np.log(work["future_rv"])

    X = sm.add_constant(work[["log_lag_rv", "stress_index"]])
    fit = sm.OLS(work["log_future_rv"], X).fit(cov_type="HAC", cov_kwds={"maxlags": 4})

    boot_p = block_bootstrap_beta(work[["log_lag_rv", "stress_index", "log_future_rv"]], rng)

    baseline_fcsts = []
    full_fcsts = []
    truths = []
    for i in range(TRAIN_WEEKS, len(work)):
        train = work.iloc[:i]
        test = work.iloc[i]
        base_fit = sm.OLS(train["log_future_rv"], sm.add_constant(train[["log_lag_rv"]])).fit()
        full_fit = sm.OLS(
            train["log_future_rv"],
            sm.add_constant(train[["log_lag_rv", "stress_index"]]),
        ).fit()

        base_pred = float(
            base_fit.predict(
                sm.add_constant(pd.DataFrame([{"log_lag_rv": test["log_lag_rv"]}]), has_constant="add")
            )[0]
        )
        full_pred = float(
            full_fit.predict(
                sm.add_constant(
                    pd.DataFrame(
                        [{"log_lag_rv": test["log_lag_rv"], "stress_index": test["stress_index"]}]
                    ),
                    has_constant="add",
                )
            )[0]
        )
        baseline_fcsts.append(math.exp(base_pred))
        full_fcsts.append(math.exp(full_pred))
        truths.append(float(test["future_rv"]))

    truths_arr = np.asarray(truths)
    base_arr = np.asarray(baseline_fcsts)
    full_arr = np.asarray(full_fcsts)
    base_loss = qlike(truths_arr, base_arr)
    full_loss = qlike(truths_arr, full_arr)
    dm_t, dm_p = hac_t_p(base_loss - full_loss)
    oos_r2 = float(1 - np.sum((truths_arr - full_arr) ** 2) / np.sum((truths_arr - base_arr) ** 2))
    qlike_delta = float(base_loss.mean() - full_loss.mean())

    stress_coef = float(fit.params["stress_index"])

    if stress_coef > 0 and qlike_delta > 0 and dm_t > 0 and dm_p < 0.05 and oos_r2 > 0:
        verdict = "PASS"
    elif stress_coef < 0 and qlike_delta > 0 and oos_r2 > 0:
        verdict = "REVERSE_SIGN"
    elif float(fit.pvalues["stress_index"]) < 0.10 or qlike_delta > 0 or oos_r2 > 0:
        verdict = "MIXED"
    else:
        verdict = "NULL"

    return AssetResult(
        asset=asset,
        n_obs=len(work),
        is_mean_ann_rv=float(work["future_rv"].mean()),
        oos_n=len(truths_arr),
        stress_coef=stress_coef,
        stress_t_hac=float(fit.tvalues["stress_index"]),
        stress_p_hac=float(fit.pvalues["stress_index"]),
        stress_boot_p=boot_p,
        baseline_qlike=float(base_loss.mean()),
        full_qlike=float(full_loss.mean()),
        qlike_delta=qlike_delta,
        dm_t_qlike=dm_t,
        dm_p_qlike=dm_p,
        oos_r2=oos_r2,
        verdict=verdict,
    )


def build_panel() -> pd.DataFrame:
    sofr = fetch_nyfed_rate("secured", "sofr")
    effr = fetch_nyfed_rate("unsecured", "effr")
    tgcr = fetch_nyfed_rate("secured", "tgcr")
    rates = sofr.merge(effr, on="date", how="inner").merge(tgcr, on="date", how="inner")
    rates["sofr_effr"] = rates["sofr"] - rates["effr"]
    rates["sofr_tgcr"] = rates["sofr"] - rates["tgcr"]
    weekly_rates = (
        rates.set_index("date")[["sofr_effr", "sofr_tgcr"]]
        .resample("W-FRI")
        .mean()
        .dropna()
        .reset_index()
    )

    cftc = build_cftc_proxy()
    panel = weekly_rates.merge(cftc, on="date", how="inner")

    components = pd.DataFrame(
        {
            "date": panel["date"],
            "sofr_effr_z": expanding_zscore(panel["sofr_effr"]),
            "sofr_tgcr_z": expanding_zscore(panel["sofr_tgcr"]),
            "basis_short_z": expanding_zscore(panel["basis_short_proxy"]),
        }
    )
    panel = panel.merge(components, on="date", how="left")
    panel["stress_index"] = panel[["sofr_effr_z", "sofr_tgcr_z", "basis_short_z"]].mean(axis=1)

    for asset in ["TLT", "IEF", "ZN=F"]:
        panel = panel.merge(make_weekly_asset_frame(asset), on="date", how="inner")

    required = ["stress_index"] + [f"{asset}_future_rv" for asset in ["TLT", "IEF", "ZN=F"]]
    return panel.dropna(subset=required).sort_values("date").reset_index(drop=True)


def save_figures(panel: pd.DataFrame) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax1 = plt.subplots(figsize=(11, 5.5))
    ax1.plot(panel["date"], panel["stress_index"], color="#8c2f39", lw=1.8, label="Stress index")
    ax1.axhline(0, color="#666666", lw=0.8, alpha=0.7)
    ax1.set_ylabel("Z-scored stress index")
    ax1.set_title("Repo funding + leveraged short stress index")

    ax2 = ax1.twinx()
    ax2.plot(panel["date"], panel["TLT_future_rv"], color="#1d4e89", lw=1.2, alpha=0.8, label="Next-week TLT RV")
    ax2.set_ylabel("Next-week TLT annualized RV")

    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [line.get_label() for line in lines], loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG_SIGNAL_PATH, dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.scatter(panel["stress_index"], panel["TLT_future_rv"], s=18, alpha=0.65, color="#8c2f39")
    slope, intercept = np.polyfit(panel["stress_index"], panel["TLT_future_rv"], 1)
    x = np.linspace(panel["stress_index"].min(), panel["stress_index"].max(), 200)
    ax.plot(x, intercept + slope * x, color="#1d4e89", lw=1.5)
    ax.set_xlabel("Stress index")
    ax.set_ylabel("Next-week TLT annualized RV")
    ax.set_title("Stress proxy vs next-week TLT RV")
    fig.tight_layout()
    fig.savefig(FIG_SCATTER_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    rng = np.random.default_rng(SEED)
    panel = build_panel()
    results = [fit_asset(panel, asset, rng) for asset in ["TLT", "IEF", "ZN=F"]]
    save_figures(panel)

    verdict_counts = pd.Series([r.verdict for r in results]).value_counts().to_dict()
    if verdict_counts.get("PASS", 0) >= 2:
        overall = "PASS"
    elif verdict_counts.get("REVERSE_SIGN", 0) >= 1:
        overall = "REVERSE_SIGN_MIXED"
    elif verdict_counts.get("MIXED", 0) >= 1:
        overall = "MIXED"
    else:
        overall = "NULL"
    if overall == "PASS":
        headline = "The composite proxy improves duration-RV forecasts in at least two assets."
    elif overall == "REVERSE_SIGN_MIXED":
        headline = (
            "The composite proxy has reverse-sign weekly links to duration RV: "
            "elevated basis/funding activity aligns with lower, not higher, next-week volatility."
        )
    elif overall == "MIXED":
        headline = "The composite proxy has partial in-sample or OOS signal but does not form a robust cross-asset result."
    else:
        headline = "After lookahead-safe expanding standardization, the repo-basis stress proxy does not robustly predict next-week duration RV."

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Repo-basis funding stress gate predicts duration-asset volatility",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "data": {
            "sample_start": str(panel["date"].min().date()),
            "sample_end": str(panel["date"].max().date()),
            "n_weekly_obs": int(len(panel)),
            "train_weeks": TRAIN_WEEKS,
            "sources": {
                "nyfed_rates_api": [
                    "SOFR secured search.json",
                    "EFFR unsecured search.json",
                    "TGCR secured search.json",
                ],
                "cftc": [f"com_fin_txt_{year}.zip" for year in YEARS],
                "yfinance_assets": ["TLT", "IEF", "ZN=F"],
            },
        },
        "design": {
            "signal_timing_guard": (
                "CFTC Traders in Financial Futures report_date is Tuesday but "
                "becomes usable only on Friday release_date = report_date + 3 "
                "calendar days; next-week RV starts after release_date."
            ),
            "features": [
                "weekly mean SOFR-EFFR",
                "weekly mean SOFR-TGCR",
                "basis short proxy = mean(UST 10Y leveraged short share, UST Bond leveraged short share)",
                "stress index = mean(expanding z-scored feature components)",
            ],
            "target": "next 5 trading-day annualized realized variance",
            "baseline_model": "AR(1) on log weekly RV",
            "full_model": "AR(1) on log weekly RV + stress index",
            "tests": [
                "full-sample OLS with Newey-West HAC(4)",
                "block bootstrap for stress coefficient sign (block=8, B=2000, seed=42)",
                "expanding-window OOS QLIKE + HAC Diebold-Mariano vs baseline",
            ],
            "seed": SEED,
        },
        "summary": {
            "overall_verdict": overall,
            "headline": headline,
        },
        "asset_results": [r.__dict__ for r in results],
    }

    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    for result in results:
        print(
            f"{result.asset}: verdict={result.verdict}, beta={result.stress_coef:.4f}, "
            f"HAC t={result.stress_t_hac:.2f}, boot p={result.stress_boot_p:.3f}, "
            f"QLIKE Δ={result.qlike_delta:.4f}, OOS R²={result.oos_r2:.4f}"
        )


if __name__ == "__main__":
    main()
