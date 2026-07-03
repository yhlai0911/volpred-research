#!/usr/bin/env python3
"""Direct power-price RV pilot with renewable penetration.

Question:
    Do high renewable-penetration days forecast or coincide with higher
    realized volatility / left-tail outcomes in wholesale power prices?

Lookahead policy:
    - The formal forecasting test predicts daily CAISO day-ahead hub-price RV_t
      using HAR lags plus renewable_share_{t-1}. No same-day renewable signal is
      used in the primary OOS forecast.
    - Same-day high-renewable contrasts are reported as descriptive diagnostics
      because CAISO day-ahead renewable forecasts are known before operating
      hours but the script does not model publication timestamps.
    - OOS expanding-window fits train only on rows strictly before the forecast
      date.

Data note:
    The queued task proposed EIA Electricity Data Browser. EIA v2 requires an
    API key in this environment, so this reproducible pilot uses public CAISO
    OASIS ZIP endpoints (no key) for day-ahead hub LMP, renewable forecast, and
    load forecast.
"""

from __future__ import annotations

import io
import json
import math
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


EXPERIMENT_ID = "research_rv_proxy"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
PANEL_PATH = DATA_DIR / "caiso_daily_panel.csv"
FIG_PATH = FIG_DIR / "caiso_renewable_rv_summary.png"

SEED = 42
START_DATE = "2024-01-01"
END_DATE = "2025-12-31"
OOS_START = "2025-01-01"
MIN_TRAIN = 250
EPS = 1e-9
BOOT_REPS = 5000

OASIS_BASE = "https://oasis.caiso.com/oasisapi/SingleZip"
PRICE_NODES = {
    "NP15": "TH_NP15_GEN-APND",
    "SP15": "TH_SP15_GEN-APND",
    "ZP26": "TH_ZP26_GEN-APND",
}


@dataclass(frozen=True)
class ForecastSummary:
    hub: str
    n_oos: int
    base_qlike: float
    augmented_qlike: float
    qlike_improve_pct: float
    dm_t_aug_minus_base: float
    dm_p_value: float
    log_mse_base: float
    log_mse_augmented: float
    log_mse_improve_pct: float


@dataclass(frozen=True)
class CoefSummary:
    hub: str
    n_obs: int
    beta_renewable_share_lag1: float
    t_renewable_share_lag1_hac5: float
    p_renewable_share_lag1_hac5: float
    r_squared: float


@dataclass(frozen=True)
class DescriptiveSummary:
    hub: str
    high_renew_threshold: float
    n_high: int
    n_low: int
    mean_log_rv_high: float
    mean_log_rv_low: float
    diff_high_minus_low: float
    welch_t: float
    welch_p: float
    bootstrap_ci95_diff: list[float]
    negative_price_day_rate_high: float
    negative_price_day_rate_low: float
    negative_price_rate_diff: float


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def date_chunks(start: str, end: str, days: int = 30) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """CAISO OASIS rejects some calendar-month requests as >31 days; use short chunks."""
    chunks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    cur = pd.Timestamp(start)
    final_exclusive = pd.Timestamp(end) + pd.Timedelta(days=1)
    while cur < final_exclusive:
        nxt = min(cur + pd.Timedelta(days=days), final_exclusive)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


def _oasis_params(queryname: str, start: pd.Timestamp, end: pd.Timestamp, **kwargs: str) -> dict[str, str]:
    params = {
        "queryname": queryname,
        "startdatetime": start.strftime("%Y%m%dT00:00-0000"),
        "enddatetime": end.strftime("%Y%m%dT00:00-0000"),
        "resultformat": "6",
        "version": "1",
    }
    params.update(kwargs)
    return params


def fetch_oasis_csv(cache_name: str, queryname: str, refresh: bool = False, **kwargs: str) -> pd.DataFrame:
    ensure_dirs()
    cache = DATA_DIR / cache_name
    if cache.exists() and not refresh:
        return pd.read_csv(cache)

    parts: list[pd.DataFrame] = []
    for start, end in date_chunks(START_DATE, END_DATE):
        params = _oasis_params(queryname, start, end, **kwargs)
        url = f"{OASIS_BASE}?{urlencode(params)}"
        for attempt in range(6):
            r = requests.get(url, timeout=45)
            if r.status_code != 429:
                break
            time.sleep(2.0 * (attempt + 1))
        r.raise_for_status()
        try:
            zf = zipfile.ZipFile(io.BytesIO(r.content))
        except zipfile.BadZipFile as exc:
            raise RuntimeError(f"CAISO OASIS returned non-zip for {queryname} {start.date()}: {r.text[:500]}") from exc
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError(f"CAISO OASIS zip had no CSV for {queryname} {start.date()}: {zf.namelist()}")
        with zf.open(names[0]) as fh:
            df = pd.read_csv(fh)
        parts.append(df)
        time.sleep(0.25)

    out = pd.concat(parts, ignore_index=True)
    if "OPR_DT" in out.columns:
        out["OPR_DT"] = pd.to_datetime(out["OPR_DT"], errors="coerce")
        out = out[(out["OPR_DT"] >= START_DATE) & (out["OPR_DT"] <= END_DATE)]
    out.to_csv(cache, index=False)
    return out


def build_price_daily(refresh: bool = False) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for hub, node in PRICE_NODES.items():
        raw = fetch_oasis_csv(
            f"caiso_prc_lmp_dam_{hub}.csv",
            "PRC_LMP",
            refresh=refresh,
            market_run_id="DAM",
            node=node,
        )
        raw = raw[raw["LMP_TYPE"].astype(str).eq("LMP")].copy()
        raw["date"] = pd.to_datetime(raw["OPR_DT"], errors="coerce").dt.normalize()
        raw["hour"] = pd.to_numeric(raw["OPR_HR"], errors="coerce").astype("Int64")
        raw["price"] = pd.to_numeric(raw["MW"], errors="coerce")
        raw = raw.dropna(subset=["date", "hour", "price"])
        raw = raw.sort_values(["date", "hour"])
        daily_rows = []
        for date, g in raw.groupby("date"):
            prices = g.drop_duplicates("hour").sort_values("hour")["price"].to_numpy(dtype=float)
            if len(prices) < 20:
                continue
            diff = np.diff(prices)
            daily_rows.append(
                {
                    "date": date,
                    "hub": hub,
                    "n_hours_price": int(len(prices)),
                    "price_mean": float(np.mean(prices)),
                    "price_std": float(np.std(prices, ddof=1)),
                    "price_range": float(np.max(prices) - np.min(prices)),
                    "price_min": float(np.min(prices)),
                    "negative_price_hours": int(np.sum(prices < 0)),
                    "price_rv": float(np.sum(diff * diff)),
                }
            )
        rows.append(pd.DataFrame(daily_rows))
    return pd.concat(rows, ignore_index=True)


def build_renewable_daily(refresh: bool = False) -> pd.DataFrame:
    ren = fetch_oasis_csv(
        "caiso_sld_ren_fcst_dam.csv",
        "SLD_REN_FCST",
        refresh=refresh,
        market_run_id="DAM",
    )
    load = fetch_oasis_csv(
        "caiso_sld_fcst_dam.csv",
        "SLD_FCST",
        refresh=refresh,
        market_run_id="DAM",
    )

    ren["date"] = pd.to_datetime(ren["OPR_DT"], errors="coerce").dt.normalize()
    ren["hour"] = pd.to_numeric(ren["OPR_HR"], errors="coerce").astype("Int64")
    ren["MW"] = pd.to_numeric(ren["MW"], errors="coerce")
    ren = ren[ren["RENEWABLE_TYPE"].isin(["Solar", "Wind"])].dropna(subset=["date", "hour", "MW"])
    ren_hour = (
        ren.groupby(["date", "hour", "RENEWABLE_TYPE"], as_index=False)["MW"].sum()
        .pivot_table(index=["date", "hour"], columns="RENEWABLE_TYPE", values="MW", aggfunc="sum")
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for col in ["Solar", "Wind"]:
        if col not in ren_hour.columns:
            ren_hour[col] = 0.0
    ren_hour["renew_mw"] = ren_hour["Solar"].fillna(0.0) + ren_hour["Wind"].fillna(0.0)

    load["date"] = pd.to_datetime(load["OPR_DT"], errors="coerce").dt.normalize()
    load["hour"] = pd.to_numeric(load["OPR_HR"], errors="coerce").astype("Int64")
    load["MW"] = pd.to_numeric(load["MW"], errors="coerce")
    load = load[load["TAC_AREA_NAME"].astype(str).eq("CA ISO-TAC")].dropna(subset=["date", "hour", "MW"])
    load_hour = load.groupby(["date", "hour"], as_index=False)["MW"].mean().rename(columns={"MW": "load_mw"})

    hour = ren_hour.merge(load_hour, on=["date", "hour"], how="inner")
    hour = hour[(hour["load_mw"] > 0) & np.isfinite(hour["load_mw"])]
    hour["renew_share"] = hour["renew_mw"] / hour["load_mw"]
    hour["solar_share"] = hour["Solar"] / hour["load_mw"]
    hour["wind_share"] = hour["Wind"] / hour["load_mw"]

    daily = hour.groupby("date").agg(
        n_hours_renew=("renew_share", "size"),
        renew_share_mean=("renew_share", "mean"),
        renew_share_max=("renew_share", "max"),
        solar_share_mean=("solar_share", "mean"),
        wind_share_mean=("wind_share", "mean"),
        load_mean_mw=("load_mw", "mean"),
        renewable_mean_mw=("renew_mw", "mean"),
    )
    return daily.reset_index()


def build_panel(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if PANEL_PATH.exists() and not refresh:
        return pd.read_csv(PANEL_PATH, parse_dates=["date"])
    prices = build_price_daily(refresh=refresh)
    renew = build_renewable_daily(refresh=refresh)
    panel = prices.merge(renew, on="date", how="inner")
    panel = panel[(panel["n_hours_price"] >= 20) & (panel["n_hours_renew"] >= 20)].copy()
    panel["log_rv"] = np.log(panel["price_rv"].clip(lower=EPS))
    panel["negative_price_day"] = (panel["negative_price_hours"] > 0).astype(int)
    panel = panel.sort_values(["hub", "date"]).reset_index(drop=True)
    for col in ["log_rv", "renew_share_mean", "renew_share_max", "solar_share_mean", "wind_share_mean"]:
        panel[f"{col}_lag1"] = panel.groupby("hub")[col].shift(1)
    panel["log_rv_week_lag1"] = panel.groupby("hub")["log_rv"].transform(lambda s: s.shift(1).rolling(5).mean())
    panel["log_rv_month_lag1"] = panel.groupby("hub")["log_rv"].transform(lambda s: s.shift(1).rolling(22).mean())
    panel["weekday"] = panel["date"].dt.dayofweek.astype(int)
    panel.to_csv(PANEL_PATH, index=False)
    return panel


def _design(df: pd.DataFrame, augmented: bool) -> pd.DataFrame:
    cols = ["log_rv_lag1", "log_rv_week_lag1", "log_rv_month_lag1"]
    x = df[cols].copy()
    if augmented:
        x["renew_share_mean_lag1"] = df["renew_share_mean_lag1"]
    weekday = pd.get_dummies(df["weekday"], prefix="dow", drop_first=True, dtype=float)
    x = pd.concat([x, weekday], axis=1)
    return sm.add_constant(x, has_constant="add")


def expanding_forecast_one_hub(df: pd.DataFrame) -> tuple[pd.DataFrame, ForecastSummary, CoefSummary]:
    work = df.dropna(
        subset=[
            "log_rv",
            "price_rv",
            "log_rv_lag1",
            "log_rv_week_lag1",
            "log_rv_month_lag1",
            "renew_share_mean_lag1",
        ]
    ).sort_values("date").reset_index(drop=True)
    rows = []
    for pos in range(len(work)):
        if work.loc[pos, "date"] < pd.Timestamp(OOS_START):
            continue
        train = work.iloc[:pos].copy()
        if len(train) < MIN_TRAIN:
            continue
        test = work.iloc[[pos]].copy()
        y_train = train["log_rv"].astype(float)
        xb = _design(train, augmented=False)
        xa = _design(train, augmented=True)
        xb_test = _design(test, augmented=False).reindex(columns=xb.columns, fill_value=0.0)
        xa_test = _design(test, augmented=True).reindex(columns=xa.columns, fill_value=0.0)
        try:
            mb = sm.OLS(y_train, xb).fit()
            ma = sm.OLS(y_train, xa).fit()
        except Exception:
            continue
        pred_b = float(mb.predict(xb_test).iloc[0])
        pred_a = float(ma.predict(xa_test).iloc[0])
        rows.append(
            {
                "date": test["date"].iloc[0],
                "hub": test["hub"].iloc[0],
                "actual_log_rv": float(test["log_rv"].iloc[0]),
                "actual_rv": float(test["price_rv"].iloc[0]),
                "pred_log_rv_base": pred_b,
                "pred_log_rv_augmented": pred_a,
                "pred_rv_base": float(math.exp(pred_b)),
                "pred_rv_augmented": float(math.exp(pred_a)),
                "renew_share_mean_lag1": float(test["renew_share_mean_lag1"].iloc[0]),
            }
        )
    fc = pd.DataFrame(rows)
    if fc.empty:
        raise RuntimeError(f"no OOS forecasts for {df['hub'].iloc[0]}")
    loss_b = qlike_pointwise(fc["actual_rv"], fc["pred_rv_base"])
    loss_a = qlike_pointwise(fc["actual_rv"], fc["pred_rv_augmented"])
    dm_t, dm_p = dm_test(loss_a, loss_b, h=1)
    base_ql = float(np.mean(loss_b))
    aug_ql = float(np.mean(loss_a))
    log_mse_b = float(np.mean((fc["actual_log_rv"] - fc["pred_log_rv_base"]) ** 2))
    log_mse_a = float(np.mean((fc["actual_log_rv"] - fc["pred_log_rv_augmented"]) ** 2))
    fsum = ForecastSummary(
        hub=str(df["hub"].iloc[0]),
        n_oos=int(len(fc)),
        base_qlike=base_ql,
        augmented_qlike=aug_ql,
        qlike_improve_pct=float((base_ql - aug_ql) / abs(base_ql) * 100.0) if abs(base_ql) > EPS else float("nan"),
        dm_t_aug_minus_base=float(dm_t),
        dm_p_value=float(dm_p),
        log_mse_base=log_mse_b,
        log_mse_augmented=log_mse_a,
        log_mse_improve_pct=float((log_mse_b - log_mse_a) / abs(log_mse_b) * 100.0) if abs(log_mse_b) > EPS else float("nan"),
    )

    x_full = _design(work, augmented=True)
    y_full = work["log_rv"].astype(float)
    hac = sm.OLS(y_full, x_full).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    csum = CoefSummary(
        hub=str(df["hub"].iloc[0]),
        n_obs=int(len(work)),
        beta_renewable_share_lag1=float(hac.params.get("renew_share_mean_lag1", np.nan)),
        t_renewable_share_lag1_hac5=float(hac.tvalues.get("renew_share_mean_lag1", np.nan)),
        p_renewable_share_lag1_hac5=float(hac.pvalues.get("renew_share_mean_lag1", np.nan)),
        r_squared=float(hac.rsquared),
    )
    return fc, fsum, csum


def descriptive_one_hub(df: pd.DataFrame, rng: np.random.Generator) -> DescriptiveSummary:
    work = df.dropna(subset=["log_rv", "renew_share_mean"]).copy()
    threshold = float(work["renew_share_mean"].quantile(0.75))
    high = work[work["renew_share_mean"] >= threshold]
    low = work[work["renew_share_mean"] < threshold]
    diff = float(high["log_rv"].mean() - low["log_rv"].mean())
    t_stat, p_val = stats.ttest_ind(high["log_rv"], low["log_rv"], equal_var=False)
    boot = np.empty(BOOT_REPS)
    hv = high["log_rv"].to_numpy(dtype=float)
    lv = low["log_rv"].to_numpy(dtype=float)
    for i in range(BOOT_REPS):
        boot[i] = rng.choice(hv, size=len(hv), replace=True).mean() - rng.choice(lv, size=len(lv), replace=True).mean()
    return DescriptiveSummary(
        hub=str(df["hub"].iloc[0]),
        high_renew_threshold=threshold,
        n_high=int(len(high)),
        n_low=int(len(low)),
        mean_log_rv_high=float(high["log_rv"].mean()),
        mean_log_rv_low=float(low["log_rv"].mean()),
        diff_high_minus_low=diff,
        welch_t=float(t_stat),
        welch_p=float(p_val),
        bootstrap_ci95_diff=[float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        negative_price_day_rate_high=float(high["negative_price_day"].mean()),
        negative_price_day_rate_low=float(low["negative_price_day"].mean()),
        negative_price_rate_diff=float(high["negative_price_day"].mean() - low["negative_price_day"].mean()),
    )


def make_figure(forecasts: list[ForecastSummary], desc: list[DescriptiveSummary]) -> None:
    hubs = [f.hub for f in forecasts]
    qimp = [f.qlike_improve_pct for f in forecasts]
    mseimp = [f.log_mse_improve_pct for f in forecasts]
    dmap = {d.hub: d for d in desc}
    diff = [dmap[h].diff_high_minus_low for h in hubs]
    neg = [dmap[h].negative_price_rate_diff * 100.0 for h in hubs]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    axes[0].bar(hubs, qimp, color=["#1b9e77" if v > 0 else "#d95f02" for v in qimp])
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_title("OOS QLIKE improvement\nHAR + lagged renewable share")
    axes[0].set_ylabel("% improvement vs HAR")
    axes[1].bar(hubs, mseimp, color=["#1b9e77" if v > 0 else "#d95f02" for v in mseimp])
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("OOS log-RV MSE improvement")
    axes[2].bar(np.arange(len(hubs)) - 0.18, diff, width=0.36, label="log RV high-low")
    axes[2].bar(np.arange(len(hubs)) + 0.18, neg, width=0.36, label="neg-price day diff pp")
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].set_xticks(range(len(hubs)), hubs)
    axes[2].set_title("Same-day high-renew diagnostic")
    axes[2].legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(FIG_PATH, dpi=140)
    plt.close()


def main(refresh: bool = False) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    panel = build_panel(refresh=refresh)
    forecasts: list[pd.DataFrame] = []
    forecast_summaries: list[ForecastSummary] = []
    coef_summaries: list[CoefSummary] = []
    desc_summaries: list[DescriptiveSummary] = []
    for hub, g in panel.groupby("hub"):
        fc, fs, cs = expanding_forecast_one_hub(g)
        forecasts.append(fc)
        forecast_summaries.append(fs)
        coef_summaries.append(cs)
        desc_summaries.append(descriptive_one_hub(g, rng))
    fc_all = pd.concat(forecasts, ignore_index=True)
    fc_all.to_csv(DATA_DIR / "oos_forecasts.csv", index=False)
    make_figure(forecast_summaries, desc_summaries)

    pass_hubs = [
        f.hub
        for f in forecast_summaries
        if f.qlike_improve_pct > 0 and f.dm_t_aug_minus_base < -3.0
    ]
    positive_beta_hubs = [
        c.hub
        for c in coef_summaries
        if c.beta_renewable_share_lag1 > 0 and c.t_renewable_share_lag1_hac5 > 3.0
    ]
    descriptive_high_hubs = [
        d.hub
        for d in desc_summaries
        if d.diff_high_minus_low > 0 and d.bootstrap_ci95_diff[0] > 0
    ]

    if len(pass_hubs) >= 2 and len(positive_beta_hubs) >= 2:
        verdict = "PASS"
    elif len(pass_hubs) >= 1 or len(positive_beta_hubs) >= 1:
        verdict = "DIRECTIONAL_ONLY"
    elif len(descriptive_high_hubs) >= 2:
        verdict = "DESCRIPTIVE_ONLY"
    else:
        verdict = "NULL"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "sample": {
            "start": START_DATE,
            "end": END_DATE,
            "oos_start": OOS_START,
            "n_daily_hub_rows": int(len(panel)),
            "hubs": sorted(panel["hub"].unique().tolist()),
        },
        "data_sources": {
            "primary": "CAISO OASIS public ZIP endpoints (PRC_LMP DAM, SLD_REN_FCST DAM, SLD_FCST DAM)",
            "eia_status": "EIA v2 route tested but API key absent in local environment; no paid-data fallback used.",
        },
        "literature": [
            {
                "citation": "Rintamäki, Siddiqui & Salo (2017), Energy Economics",
                "role": "VRE can increase or decrease electricity price volatility depending on regional flexibility and wind/solar profiles.",
                "url": "https://doi.org/10.1016/j.eneco.2016.12.019",
            },
            {
                "citation": "Owolabi et al. (2023), Data Science in Science",
                "role": "U.S. ISO evidence on nonlinear VRE penetration and electricity-price volatility.",
                "url": "https://doi.org/10.1080/26941899.2022.2158145",
            },
            {
                "citation": "Brown & Yucel (2024), Dallas Fed Working Paper 2408",
                "role": "Fuel mix and marginal generation matter for real-time electricity price volatility; wind intensity changes the channel.",
                "url": "https://www.dallasfed.org/research/papers/2024/wp2408",
            },
        ],
        "lookahead_policy": {
            "formal_forecast": "HAR uses log_rv lag1/week/month plus renewable_share_mean.shift(1); OOS train rows end strictly before forecast date.",
            "same_day_diagnostics": "High-renewable same-day contrasts are descriptive only, not the PASS gate.",
        },
        "forecast_summaries": [asdict(f) for f in forecast_summaries],
        "coef_summaries": [asdict(c) for c in coef_summaries],
        "descriptive_summaries": [asdict(d) for d in desc_summaries],
        "gate": {
            "pass_hubs": pass_hubs,
            "positive_beta_hubs": positive_beta_hubs,
            "descriptive_high_hubs": descriptive_high_hubs,
            "pass_rule": "PASS requires >=2 hubs with QLIKE improvement and DM t<-3 plus >=2 hubs with positive HAC t>3 lagged renewable-share coefficient.",
        },
        "outputs": {
            "panel": str(PANEL_PATH.relative_to(HERE)),
            "oos_forecasts": "data/oos_forecasts.csv",
            "figure": str(FIG_PATH.relative_to(HERE)),
        },
    }
    RESULTS_PATH.write_text(json.dumps(_json_safe(results), indent=2, ensure_ascii=False))
    print(f"[{EXPERIMENT_ID}] verdict={verdict} -> {RESULTS_PATH}")
    return results


if __name__ == "__main__":
    main(refresh=False)
