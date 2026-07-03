"""K1609: COMEX scarcity proxy and precious-metal volatility.

Primary intended data source: CME COMEX Gold_Stocks.xls and Silver_stocks.xls.
In this runtime, those endpoints time out without returning bytes.  The script
therefore records that data limitation and runs a clearly labeled fallback
diagnostic using only public yfinance + FRED data:

- futures/ETF tracking basis z-score
- ETF dollar-volume attention / demand z-score
- lagged real-yield controls from FRED DFII10

The fallback does not claim to measure COMEX registered/eligible inventory or
LBMA lease rates.  It only asks whether a weak public-market tightness proxy
has a next-week RV footprint.

Lookahead guard:
- raw same-day proxy values are transformed to `scarcity_proxy_lag1` using
  `.shift(1)`.
- weekly origins use data available at origin close; targets are strictly
  origin+1 through origin+5 trading days.

Seed: 42 for all bootstrap inference.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

EXPERIMENT_ID = "K1609"
SEED = 42
START = "2006-01-01"
END = "2026-07-03"
HORIZON = 5
CORR_HORIZON = 21
ROLLING_Z = 252
BOOTSTRAP_REPS = 5000

METALS = {
    "gold": {
        "etf": "GLD",
        "future": "GC=F",
        "etf_to_future_scale": 10.0,  # GLD share is designed to track about 1/10 oz gold before expenses.
        "cme_url": "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls",
    },
    "silver": {
        "etf": "SLV",
        "future": "SI=F",
        "etf_to_future_scale": 1.0,
        "cme_url": "https://www.cmegroup.com/delivery_reports/Silver_stocks.xls",
    },
}
YF_TICKERS = ["GLD", "SLV", "GC=F", "SI=F", "^VIX"]
FRED_DFII10_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"

LITERATURE = [
    {
        "citation": "Barone-Adesi, Geman, and Theal (2010), 'On the Lease Rate, Convenience Yield and Speculative Effects in the Gold Futures Market'",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1365180",
        "use_in_design": "Motivates inventory / lease-rate tightness as a gold-futures state variable; this K cannot observe lease rates directly.",
    },
    {
        "citation": "Le and Zhu (2013), 'Risk Premia in Gold Lease Rates'",
        "url": "https://conference.nber.org/confer/2013/CWf13/Le_Zhu.pdf",
        "use_in_design": "Motivates links among lease rates, Treasury yields, VIX, and COMEX inventory growth.",
    },
    {
        "citation": "Fama and French (1987), Journal of Business, 'Commodity Futures Prices: Some Evidence on Forecast Power, Premiums, and the Theory of Storage'",
        "url": "https://www.jstor.org/stable/2352877",
        "use_in_design": "Theory-of-storage motivation for inventory scarcity and convenience yield; not directly replicated.",
    },
    {
        "citation": "CME Group Warehouse & Depository Stocks reports",
        "url": "https://www.cmegroup.com/solutions/clearing/operations-and-deliveries/nymex-delivery-notices.html",
        "use_in_design": "Primary intended public source for registered and eligible stocks; endpoint availability is audited in this script.",
    },
]


def try_fetch_cme_snapshot(name: str, url: str, timeout: int = 8) -> dict:
    started = time.time()
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 VolPredResearchBot/1.0"},
            timeout=timeout,
        )
        elapsed = time.time() - started
        return {
            "metal": name,
            "url": url,
            "ok": response.ok and len(response.content) > 0,
            "status_code": int(response.status_code),
            "bytes": int(len(response.content)),
            "content_type": response.headers.get("content-type"),
            "elapsed_sec": round(elapsed, 3),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "metal": name,
            "url": url,
            "ok": False,
            "status_code": None,
            "bytes": 0,
            "content_type": None,
            "elapsed_sec": round(time.time() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def extract_close_volume(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("expected yfinance MultiIndex columns")
    close = raw["Close"].copy()
    volume = raw["Volume"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    volume.index = pd.to_datetime(volume.index).tz_localize(None).normalize()
    return close.sort_index(), volume.sort_index()


def download_yfinance() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = yf.download(
        YF_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    close, volume = extract_close_volume(raw)
    close.to_csv(DATA_DIR / "yfinance_close.csv")
    volume.to_csv(DATA_DIR / "yfinance_volume.csv")
    return close, volume


def download_fred_dfii10() -> pd.DataFrame:
    df = pd.read_csv(FRED_DFII10_URL)
    df["date"] = pd.to_datetime(df["observation_date"]).dt.tz_localize(None).dt.normalize()
    df["DFII10"] = pd.to_numeric(df["DFII10"], errors="coerce")
    out = df[["date", "DFII10"]].dropna().set_index("date").sort_index()
    out.to_csv(DATA_DIR / "fred_dfii10.csv")
    return out


def rolling_zscore(series: pd.Series, window: int = ROLLING_Z) -> pd.Series:
    mean = series.rolling(window, min_periods=max(60, window // 3)).mean()
    sd = series.rolling(window, min_periods=max(60, window // 3)).std(ddof=1)
    return (series - mean) / sd.replace(0, np.nan)


def build_daily_proxy(close: pd.DataFrame, volume: pd.DataFrame, real_yield: pd.DataFrame) -> pd.DataFrame:
    idx = close.index.union(real_yield.index).sort_values()
    frames = []
    vix = close["^VIX"].reindex(idx).ffill()
    dfii10 = real_yield["DFII10"].reindex(idx).ffill()
    real_yield_change5 = dfii10.diff(5)

    for metal, cfg in METALS.items():
        etf = cfg["etf"]
        future = cfg["future"]
        scale = cfg["etf_to_future_scale"]

        etf_close = close[etf].reindex(idx).ffill()
        future_close = close[future].reindex(idx).ffill()
        etf_volume = volume[etf].reindex(idx)
        ret = np.log(etf_close / etf_close.shift(1))
        future_ret = np.log(future_close / future_close.shift(1))

        tracking_basis = np.log(future_close / (etf_close * scale))
        basis_z = rolling_zscore(tracking_basis)
        dollar_volume = np.log1p(etf_close * etf_volume)
        dollar_volume_z = rolling_zscore(dollar_volume)
        raw_proxy = basis_z + 0.5 * dollar_volume_z

        metal_df = pd.DataFrame(
            {
                "metal": metal,
                "etf": etf,
                "future": future,
                "etf_close": etf_close,
                "future_close": future_close,
                "etf_return": ret,
                "future_return": future_ret,
                "tracking_basis": tracking_basis,
                "basis_z": basis_z,
                "dollar_volume_z": dollar_volume_z,
                "scarcity_proxy_raw": raw_proxy,
                "scarcity_proxy_lag1": raw_proxy.shift(1),
                "prior5_return": ret.rolling(5).sum().shift(1),
                "prior21_rv_ann": (ret.rolling(21).std(ddof=1) * np.sqrt(252)).shift(1),
                "vix_lag1": vix.shift(1),
                "real_yield_lag1": dfii10.shift(1),
                "real_yield_change5_lag1": real_yield_change5.shift(1),
            },
            index=idx,
        )
        frames.append(metal_df)
    out = pd.concat(frames).sort_index()
    out.index.name = "date"
    out.to_csv(DATA_DIR / "daily_proxy_panel.csv")
    return out


def future_window(values: pd.Series, pos: int, horizon: int) -> pd.Series:
    return values.iloc[pos + 1 : pos + 1 + horizon].dropna()


def build_weekly_origin_panel(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metal, group in daily.groupby("metal"):
        group = group.sort_index()
        ret = group["etf_return"]
        ry = group["real_yield_lag1"].diff()
        dates = group.index
        for pos, date in enumerate(dates):
            if date.weekday() != 4:
                continue
            if pos + CORR_HORIZON >= len(group):
                continue
            target_ret5 = future_window(ret, pos, HORIZON)
            target_ret21 = future_window(ret, pos, CORR_HORIZON)
            target_ry21 = future_window(ry, pos, CORR_HORIZON)
            if len(target_ret5) < HORIZON or len(target_ret21) < CORR_HORIZON or len(target_ry21) < CORR_HORIZON:
                continue

            row = group.iloc[pos]
            fwd5_rv_ann = float(target_ret5.std(ddof=1) * np.sqrt(252))
            prior21_rv = float(row["prior21_rv_ann"]) if pd.notna(row["prior21_rv_ann"]) else np.nan
            corr = float(target_ret21.corr(target_ry21)) if target_ry21.std(ddof=1) > 0 else np.nan
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "metal": metal,
                    "etf": row["etf"],
                    "future": row["future"],
                    "scarcity_proxy_lag1": float(row["scarcity_proxy_lag1"]) if pd.notna(row["scarcity_proxy_lag1"]) else np.nan,
                    "basis_z_lag1": float(group["basis_z"].shift(1).iloc[pos]) if pd.notna(group["basis_z"].shift(1).iloc[pos]) else np.nan,
                    "dollar_volume_z_lag1": float(group["dollar_volume_z"].shift(1).iloc[pos])
                    if pd.notna(group["dollar_volume_z"].shift(1).iloc[pos])
                    else np.nan,
                    "prior5_return": float(row["prior5_return"]) if pd.notna(row["prior5_return"]) else np.nan,
                    "prior21_rv_ann": prior21_rv,
                    "vix_lag1": float(row["vix_lag1"]) if pd.notna(row["vix_lag1"]) else np.nan,
                    "real_yield_lag1": float(row["real_yield_lag1"]) if pd.notna(row["real_yield_lag1"]) else np.nan,
                    "real_yield_change5_lag1": float(row["real_yield_change5_lag1"])
                    if pd.notna(row["real_yield_change5_lag1"])
                    else np.nan,
                    "fwd5_return": float(target_ret5.sum()),
                    "fwd5_rv_ann": fwd5_rv_ann,
                    "log_fwd5_rv_ratio": float(np.log((fwd5_rv_ann + 1e-8) / (prior21_rv + 1e-8)))
                    if prior21_rv > 0
                    else np.nan,
                    "downside_semivar_5d_ann": float(np.mean(np.minimum(target_ret5.to_numpy(), 0.0) ** 2) * 252),
                    "fwd21_return_real_yield_corr": corr,
                    "year": int(date.year),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(DATA_DIR / "weekly_origin_panel.csv", index=False)
    return out


def ols_hac(df: pd.DataFrame, y_col: str) -> dict:
    controls = [
        "scarcity_proxy_lag1",
        "prior5_return",
        "prior21_rv_ann",
        "vix_lag1",
        "real_yield_lag1",
        "real_yield_change5_lag1",
    ]
    sample = df.dropna(subset=[y_col, *controls]).copy()
    if len(sample) < 120:
        return {"ok": False, "reason": "insufficient sample", "n": int(len(sample))}
    x = sm.add_constant(sample[controls].astype(float), has_constant="add")
    y = sample[y_col].astype(float)
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
    coef = float(fit.params["scarcity_proxy_lag1"])
    se = float(fit.bse["scarcity_proxy_lag1"])
    return {
        "ok": True,
        "n": int(len(sample)),
        "coef": coef,
        "se_hac_lag4": se,
        "t_hac_lag4": float(fit.tvalues["scarcity_proxy_lag1"]),
        "p_hac_lag4": float(fit.pvalues["scarcity_proxy_lag1"]),
        "ci95_low": coef - 1.96 * se,
        "ci95_high": coef + 1.96 * se,
        "r2": float(fit.rsquared),
    }


def bootstrap_year_diff(df: pd.DataFrame, y_col: str) -> dict:
    sample = df.dropna(subset=[y_col, "scarcity_proxy_lag1"]).copy()
    sample["high_proxy"] = sample["scarcity_proxy_lag1"] >= sample["scarcity_proxy_lag1"].quantile(0.8)
    if sample["high_proxy"].nunique() < 2:
        return {"ok": False, "reason": "no high-proxy variation"}
    observed = float(sample.loc[sample["high_proxy"], y_col].mean() - sample.loc[~sample["high_proxy"], y_col].mean())
    stats = []
    for year, group in sample.groupby("year"):
        hi = group.loc[group["high_proxy"], y_col].astype(float)
        lo = group.loc[~group["high_proxy"], y_col].astype(float)
        stats.append(
            {
                "year": int(year),
                "hi_sum": float(hi.sum()),
                "hi_n": int(hi.count()),
                "lo_sum": float(lo.sum()),
                "lo_n": int(lo.count()),
            }
        )
    stats_df = pd.DataFrame(stats).sort_values("year")
    rng = np.random.default_rng(SEED)
    draw = rng.integers(0, len(stats_df), size=(BOOTSTRAP_REPS, len(stats_df)))
    hi_sum = stats_df["hi_sum"].to_numpy()[draw].sum(axis=1)
    hi_n = stats_df["hi_n"].to_numpy()[draw].sum(axis=1)
    lo_sum = stats_df["lo_sum"].to_numpy()[draw].sum(axis=1)
    lo_n = stats_df["lo_n"].to_numpy()[draw].sum(axis=1)
    valid = (hi_n > 0) & (lo_n > 0)
    diffs = hi_sum[valid] / hi_n[valid] - lo_sum[valid] / lo_n[valid]
    ci_low, ci_high = np.percentile(diffs, [2.5, 97.5])
    p_two = 2 * min(np.mean(diffs <= 0), np.mean(diffs >= 0))
    return {
        "ok": True,
        "n_boot": int(len(diffs)),
        "observed_high_minus_low": observed,
        "ci95_low": float(ci_low),
        "ci95_high": float(ci_high),
        "p_sign_two_sided": float(min(1.0, p_two)),
        "high_proxy_threshold": float(sample["scarcity_proxy_lag1"].quantile(0.8)),
    }


def analyze(panel: pd.DataFrame) -> dict:
    outcomes = ["log_fwd5_rv_ratio", "downside_semivar_5d_ann", "fwd21_return_real_yield_corr"]
    results = {}
    for metal, metal_df in panel.groupby("metal"):
        results[metal] = {}
        for outcome in outcomes:
            results[metal][outcome] = {
                "ols_hac": ols_hac(metal_df, outcome),
                "year_bootstrap_high_proxy_diff": bootstrap_year_diff(metal_df, outcome),
            }
    return results


def make_figures(daily: pd.DataFrame, weekly: pd.DataFrame, results: dict) -> list[str]:
    paths: list[str] = []

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for ax, (metal, group) in zip(axes, daily.groupby("metal"), strict=True):
        group = group.sort_index()
        ax.plot(group.index, group["scarcity_proxy_lag1"], color="#4263EB", linewidth=0.8)
        ax.axhline(group["scarcity_proxy_lag1"].quantile(0.8), color="#E03131", linestyle="--", linewidth=0.9)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_title(f"{metal.title()} fallback tightness proxy (lagged)")
        ax.set_ylabel("z-score")
    fig.tight_layout()
    p1 = FIG_DIR / "fig1_fallback_proxy_timeseries.png"
    fig.savefig(p1, dpi=150)
    plt.close(fig)
    paths.append(str(p1))

    coef_rows = []
    for metal, metal_results in results.items():
        for outcome in ["log_fwd5_rv_ratio", "fwd21_return_real_yield_corr"]:
            res = metal_results[outcome]["ols_hac"]
            if res.get("ok"):
                coef_rows.append({"metal": metal, "outcome": outcome, **res})
    coef_df = pd.DataFrame(coef_rows)
    if not coef_df.empty:
        fig2, axes2 = plt.subplots(1, 2, figsize=(12, 4.5))
        labels = {
            "log_fwd5_rv_ratio": "next-week log RV ratio",
            "fwd21_return_real_yield_corr": "future 21d return-real yield corr",
        }
        colors = {"log_fwd5_rv_ratio": "#F76707", "fwd21_return_real_yield_corr": "#2F9E44"}
        for ax, outcome in zip(axes2, ["log_fwd5_rv_ratio", "fwd21_return_real_yield_corr"], strict=True):
            sub = coef_df.loc[coef_df["outcome"] == outcome].copy()
            x = np.arange(len(sub))
            ax.bar(x, sub["coef"], color=colors[outcome], alpha=0.85)
            ax.errorbar(
                x,
                sub["coef"],
                yerr=[sub["coef"] - sub["ci95_low"], sub["ci95_high"] - sub["coef"]],
                fmt="none",
                color="black",
                capsize=3,
            )
            ax.axhline(0, color="black", linewidth=0.8)
            ax.set_xticks(x)
            ax.set_xticklabels(sub["metal"])
            ax.set_title(labels[outcome])
            ax.set_ylabel("scarcity proxy coefficient, HAC 95% CI")
        fig2.tight_layout()
        p2 = FIG_DIR / "fig2_proxy_coefficients.png"
        fig2.savefig(p2, dpi=150)
        plt.close(fig2)
        paths.append(str(p2))

    fig3, ax3 = plt.subplots(figsize=(7, 5))
    for metal, group in weekly.groupby("metal"):
        clean = group.dropna(subset=["scarcity_proxy_lag1", "log_fwd5_rv_ratio"])
        ax3.scatter(clean["scarcity_proxy_lag1"], clean["log_fwd5_rv_ratio"], s=12, alpha=0.35, label=metal)
    ax3.axhline(0, color="black", linewidth=0.8)
    ax3.axvline(0, color="black", linewidth=0.8)
    ax3.set_xlabel("lagged fallback tightness proxy")
    ax3.set_ylabel("next-week log RV ratio")
    ax3.set_title("Fallback proxy vs next-week RV")
    ax3.legend(frameon=False)
    fig3.tight_layout()
    p3 = FIG_DIR / "fig3_proxy_vs_rv_scatter.png"
    fig3.savefig(p3, dpi=150)
    plt.close(fig3)
    paths.append(str(p3))
    return paths


def verdict(cme_attempts: list[dict], results: dict) -> dict:
    cme_ok = all(item.get("ok") for item in cme_attempts)
    any_strong = False
    strong_cells = []
    for metal, metal_results in results.items():
        for outcome, payload in metal_results.items():
            res = payload["ols_hac"]
            if res.get("ok") and abs(res.get("t_hac_lag4", 0.0)) >= 3:
                any_strong = True
                strong_cells.append({"metal": metal, "outcome": outcome, "t": res["t_hac_lag4"], "coef": res["coef"]})

    if not cme_ok and not any_strong:
        label = "DATA_LIMITATION_PROXY_NULL"
        claim = (
            "CME warehouse stock endpoints did not return data in this runtime, and the fallback "
            "ETF/futures proxy does not show a strict |t|>=3 RV/correlation signal."
        )
    elif not cme_ok and any_strong:
        label = "DATA_LIMITATION_PROXY_SIGNAL_ONLY"
        claim = (
            "CME warehouse stock endpoints did not return data; fallback proxy has at least one "
            "strict signal cell, but this is not COMEX-inventory evidence."
        )
    elif cme_ok and any_strong:
        label = "CONDITIONAL_PASS"
        claim = "CME endpoint was reachable and at least one proxy cell clears |t|>=3."
    else:
        label = "NULL"
        claim = "CME endpoint was reachable but no strict fallback signal cell clears |t|>=3."
    return {"verdict": label, "claim": claim, "strong_cells": strong_cells}


def main() -> None:
    run_at = datetime.now(timezone.utc).isoformat()
    cme_attempts = [try_fetch_cme_snapshot(name, cfg["cme_url"]) for name, cfg in METALS.items()]
    close, volume = download_yfinance()
    real_yield = download_fred_dfii10()
    daily = build_daily_proxy(close, volume, real_yield)
    weekly = build_weekly_origin_panel(daily)
    results = analyze(weekly)
    figures = make_figures(daily, weekly, results)
    verdict_payload = verdict(cme_attempts, results)

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "title": "COMEX warehouse scarcity proxy and precious-metal volatility",
        "run_at": run_at,
        "seed": SEED,
        "verdict": verdict_payload,
        "literature": LITERATURE,
        "data_sources": {
            "intended_cme_warehouse_reports": [cfg["cme_url"] for cfg in METALS.values()],
            "yfinance": YF_TICKERS,
            "fred": {"DFII10": FRED_DFII10_URL},
        },
        "cme_fetch_attempts": cme_attempts,
        "methodology": {
            "primary_data_limitation": (
                "CME Gold_Stocks.xls and Silver_stocks.xls were attempted with explicit timeouts. "
                "No bytes were returned in this runtime, so no registered/eligible inventory "
                "time-series inference is made."
            ),
            "fallback_proxy": (
                "scarcity_proxy_raw = rolling_z(future / scaled ETF tracking basis) + "
                "0.5 * rolling_z(log ETF dollar volume); scarcity_proxy_lag1 = scarcity_proxy_raw.shift(1)."
            ),
            "targets": [
                "log_fwd5_rv_ratio: next 5 trading days annualized RV vs prior 21d RV",
                "downside_semivar_5d_ann: next 5 trading days downside semivariance",
                "fwd21_return_real_yield_corr: future 21d ETF return correlation with real-yield changes",
            ],
            "controls": [
                "prior5_return",
                "prior21_rv_ann",
                "vix_lag1",
                "real_yield_lag1",
                "real_yield_change5_lag1",
            ],
            "inference": "Weekly Friday origins; OLS with HAC lag 4 plus year-cluster high-proxy bootstrap.",
            "lookahead_controls": [
                "scarcity_proxy_lag1 is created with `.shift(1)`",
                "targets use origin+1 through origin+5 or origin+21 trading days",
                "FRED real yield controls are lagged",
            ],
        },
        "sample": {
            "weekly_origin_rows": int(len(weekly)),
            "rows_by_metal": weekly.groupby("metal").size().astype(int).to_dict(),
            "start": str(pd.to_datetime(weekly["date"]).min().date()),
            "end": str(pd.to_datetime(weekly["date"]).max().date()),
        },
        "results": results,
        "figures": figures,
        "limitations": [
            "No COMEX registered/eligible warehouse time series was obtained; this is the binding limitation.",
            "The fallback proxy uses ETF/futures tracking basis and ETF dollar volume, not physical inventory or lease rates.",
            "GLD and SLV are ETF wrappers with fees, share mechanics, and tracking error; futures-ETF basis is not a clean convenience-yield measure.",
            "FRED DFII10 is daily and sometimes revised/missing; it is used only as a lagged control.",
            "Weekly origins reduce overlap but do not make the fallback proxy causal.",
        ],
    }
    out = HERE / "K1609_results.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps({"out": str(out), "verdict": verdict_payload, "sample": payload["sample"]}, indent=2))


if __name__ == "__main__":
    main()
