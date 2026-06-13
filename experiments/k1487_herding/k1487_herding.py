"""K1487: TWSE day-trading ratio and next-day Taiwan equity volatility.

Question:
    Does market-wide day-trading intensity predict next-day realized volatility
    in Taiwan, or is the relationship mostly volatility attracting day trading?

Data:
    - TWSE official monthly day-trading statistics API, market level.
    - Local yfinance snapshots for ^TWII and 0050.TW under storage/macro.

Timing:
    Target row is date t. Every predictor uses information through t-1 via
    explicit .shift(1). There is no same-day signal on same-day volatility.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.plot_style import apply_cjk_style
from src.volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "K1487"
SEED = 42
START_MONTH = "2014-01"
PRICE_FILES = {
    "TWII": REPO_ROOT / "storage" / "macro" / "yf_TWII.csv",
    "0050.TW": REPO_ROOT / "storage" / "macro" / "yf_0050.TW.csv",
}
TWSE_CACHE = ROOT / "data" / "twse_day_trading_market_monthly.csv"
RESULTS_PATH = ROOT / "k1487_herding_results.json"
FIG_DIR = ROOT / "figures"


@dataclass
class ModelSummary:
    qlike: float
    rel_improvement_pct: float
    dm_t_vs_har: float | None
    dm_p_vs_har: float | None
    harvey_pass_vs_har: bool | None
    mbb_mean_loss_diff_ci95: list[float] | None


def parse_number(x: object) -> float:
    if x is None:
        return np.nan
    s = str(x).strip().replace(",", "")
    if not s:
        return np.nan
    return float(s)


def parse_twse_date(x: object) -> pd.Timestamp:
    s = str(x).strip()
    parts = s.split("/")
    if len(parts) == 3 and len(parts[0]) <= 3:
        year = int(parts[0]) + 1911
        return pd.Timestamp(year=year, month=int(parts[1]), day=int(parts[2]))
    return pd.to_datetime(s)


def month_range(start: str, end: str) -> list[pd.Timestamp]:
    months = pd.period_range(start=start, end=end, freq="M")
    return [m.to_timestamp() for m in months]


def request_twse_month(month: pd.Timestamp, day: int) -> dict:
    query_date = month.replace(day=day)
    params = {"date": query_date.strftime("%Y%m%d"), "stockNo": "", "response": "json"}
    url = "https://www.twse.com.tw/exchangeReport/TWTB4U2?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "volpred-research/1.0 (+https://volpred.zeabur.app)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_twse_month(month: pd.Timestamp) -> pd.DataFrame:
    # The monthly endpoint returns the whole month for any valid trading date
    # inside that month. Some first-of-month dates return a misleading error,
    # so try several in-month candidates before declaring the month unavailable.
    payload = None
    errors = []
    for day in [15, 10, 20, 5, 25, 1, 28]:
        try:
            payload = request_twse_month(month, day)
        except ValueError:
            continue
        except Exception as exc:
            errors.append(f"{day}: {exc}")
            continue
        if payload.get("stat") == "OK":
            break
        errors.append(f"{day}: {payload.get('stat')}")
    else:
        raise RuntimeError(f"TWSE API failed for {month:%Y-%m}: {'; '.join(errors)}")

    tables = payload.get("tables") or []
    if not tables or not tables[0].get("data"):
        return pd.DataFrame()

    rows = []
    for row in tables[0]["data"]:
        rows.append(
            {
                "Date": parse_twse_date(row[0]),
                "day_trading_volume": parse_number(row[1]),
                "day_trading_volume_pct": parse_number(row[2]) / 100.0,
                "day_trading_buy_value": parse_number(row[3]),
                "day_trading_buy_value_pct": parse_number(row[4]) / 100.0,
                "day_trading_sell_value": parse_number(row[5]),
                "day_trading_sell_value_pct": parse_number(row[6]) / 100.0,
            }
        )
    out = pd.DataFrame(rows).sort_values("Date")
    out["day_trading_value_pct"] = (
        out["day_trading_buy_value_pct"] + out["day_trading_sell_value_pct"]
    ) / 2.0
    out["day_trading_value"] = (
        out["day_trading_buy_value"] + out["day_trading_sell_value"]
    ) / 2.0
    return out


def load_twse_day_trading(refresh: bool, end_month: str) -> pd.DataFrame:
    if TWSE_CACHE.exists() and not refresh:
        return pd.read_csv(TWSE_CACHE, parse_dates=["Date"]).sort_values("Date")

    frames = []
    for idx, month in enumerate(month_range(START_MONTH, end_month)):
        frames.append(fetch_twse_month(month))
        if idx % 12 == 0:
            print(f"Fetched TWSE through {month:%Y-%m}")
        time.sleep(0.05)

    df = pd.concat(frames, ignore_index=True).drop_duplicates("Date").sort_values("Date")
    TWSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(TWSE_CACHE, index=False)
    return df


def load_yfinance_snapshot(path: Path) -> pd.DataFrame:
    # yfinance multi-column CSV snapshot: header rows are Price/Ticker/Date.
    df = pd.read_csv(path, skiprows=[1, 2])
    df = df.rename(columns={"Price": "Date"})
    df["Date"] = pd.to_datetime(df["Date"])
    for col in ["Close", "High", "Low", "Open", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Date", "Close"]).sort_values("Date")


def build_panel(asset: str, price: pd.DataFrame, dt: pd.DataFrame) -> pd.DataFrame:
    px = price[["Date", "Close"]].copy()
    px["ret"] = np.log(px["Close"]).diff()
    px["rv"] = px["ret"].pow(2)

    panel = pd.merge(px, dt, on="Date", how="inner").sort_values("Date")
    panel["log_rv"] = np.log(panel["rv"].clip(lower=1e-12))

    # Target date t. All predictors below are known at t-1.
    panel["rv_lag1"] = panel["rv"].shift(1)
    panel["rv_lag5"] = panel["rv"].shift(1).rolling(5).mean()
    panel["rv_lag22"] = panel["rv"].shift(1).rolling(22).mean()
    panel["log_rv_lag1"] = np.log(panel["rv_lag1"].clip(lower=1e-12))
    panel["log_rv_lag5"] = np.log(panel["rv_lag5"].clip(lower=1e-12))
    panel["log_rv_lag22"] = np.log(panel["rv_lag22"].clip(lower=1e-12))

    for col in ["day_trading_value_pct", "day_trading_volume_pct"]:
        current_roll_mean = panel[col].rolling(252, min_periods=126).mean()
        current_roll_std = panel[col].rolling(252, min_periods=126).std()
        panel[f"{col}_z"] = (panel[col] - current_roll_mean) / current_roll_std.replace(0, np.nan)

        shifted = panel[col].shift(1)
        panel[f"{col}_lag1"] = shifted
        roll_mean = panel[col].shift(1).rolling(252, min_periods=126).mean()
        roll_std = panel[col].shift(1).rolling(252, min_periods=126).std()
        panel[f"{col}_z_lag1"] = (shifted - roll_mean) / roll_std.replace(0, np.nan)

    panel["asset"] = asset
    return panel.dropna().reset_index(drop=True)


def hac_fit(panel: pd.DataFrame, features: list[str]) -> dict[str, float]:
    fit = sm.OLS(panel["log_rv"], sm.add_constant(panel[features], has_constant="add")).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": 5},
    )
    out: dict[str, float] = {"r2": float(fit.rsquared), "n": int(fit.nobs)}
    for name in fit.params.index:
        out[name] = float(fit.params[name])
        out[f"{name}_pvalue"] = float(fit.pvalues[name])
        out[f"{name}_t"] = float(fit.tvalues[name])
    return out


def moving_block_bootstrap_ci(diff: np.ndarray, block_len: int = 22, reps: int = 2000) -> list[float]:
    rng = np.random.default_rng(SEED)
    d = np.asarray(diff, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < block_len * 3:
        return [float("nan"), float("nan")]
    starts = np.arange(0, n - block_len + 1)
    means = np.empty(reps)
    blocks_needed = int(np.ceil(n / block_len))
    for b in range(reps):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate([d[s : s + block_len] for s in chosen])[:n]
        means[b] = sample.mean()
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def run_oos(panel: pd.DataFrame) -> dict:
    models = {
        "har": ["log_rv_lag1", "log_rv_lag5", "log_rv_lag22"],
        "har_value_pct": [
            "log_rv_lag1",
            "log_rv_lag5",
            "log_rv_lag22",
            "day_trading_value_pct_lag1",
        ],
        "har_value_pct_z": [
            "log_rv_lag1",
            "log_rv_lag5",
            "log_rv_lag22",
            "day_trading_value_pct_z_lag1",
        ],
        "har_volume_pct_z": [
            "log_rv_lag1",
            "log_rv_lag5",
            "log_rv_lag22",
            "day_trading_volume_pct_z_lag1",
        ],
    }
    train_window = min(1000, max(504, int(len(panel) * 0.45)))
    oos_start = max(train_window, int(np.floor(len(panel) * 0.7)))
    refit_every = 21

    fits = {}
    predictions = {name: [] for name in models}
    actual = []
    dates = []

    for i in range(oos_start, len(panel)):
        if (i - oos_start) % refit_every == 0 or not fits:
            train = panel.iloc[i - train_window : i]
            for name, feats in models.items():
                fits[name] = sm.OLS(
                    train["log_rv"],
                    sm.add_constant(train[feats], has_constant="add"),
                ).fit()

        row = panel.iloc[[i]]
        actual.append(float(row["rv"].iloc[0]))
        dates.append(str(row["Date"].iloc[0].date()))
        for name, feats in models.items():
            x_row = sm.add_constant(row[feats], has_constant="add")
            pred = float(np.exp(fits[name].predict(x_row).iloc[0]))
            predictions[name].append(max(pred, 1e-12))

    actual_arr = np.asarray(actual)
    har_loss = qlike_pointwise(actual_arr, np.asarray(predictions["har"]))
    har_qlike = qlike(actual_arr, np.asarray(predictions["har"]))

    out = {
        "train_window": train_window,
        "oos_n": len(actual_arr),
        "oos_start": dates[0],
        "oos_end": dates[-1],
        "models": {
            "har": asdict(
                ModelSummary(
                    qlike=float(har_qlike),
                    rel_improvement_pct=0.0,
                    dm_t_vs_har=None,
                    dm_p_vs_har=None,
                    harvey_pass_vs_har=None,
                    mbb_mean_loss_diff_ci95=None,
                )
            )
        },
    }

    for name in [m for m in models if m != "har"]:
        loss = qlike_pointwise(actual_arr, np.asarray(predictions[name]))
        ql = qlike(actual_arr, np.asarray(predictions[name]))
        dm_t, dm_p = dm_test(loss, har_loss, h=1)
        diff = loss - har_loss
        out["models"][name] = asdict(
            ModelSummary(
                qlike=float(ql),
                rel_improvement_pct=float((har_qlike - ql) / abs(har_qlike) * 100.0),
                dm_t_vs_har=float(dm_t),
                dm_p_vs_har=float(dm_p),
                harvey_pass_vs_har=bool(abs(dm_t) > 3.0),
                mbb_mean_loss_diff_ci95=moving_block_bootstrap_ci(diff),
            )
        )
    return out


def run_granger(panel: pd.DataFrame) -> dict:
    gdf = panel[["log_rv", "day_trading_value_pct_z"]].dropna().copy()
    gdf = gdf.rename(columns={"day_trading_value_pct_z": "dt_z"})
    lags = [1, 5, 22]
    out = {
        "bonferroni_alpha_all_tests": 0.05 / (len(lags) * 2),
        "dt_z_leads_log_rv": {},
        "log_rv_leads_dt_z": {},
    }

    # statsmodels expects first column as dependent variable, second as candidate cause.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="verbose is deprecated", category=FutureWarning)
        dt_to_vol = grangercausalitytests(gdf[["log_rv", "dt_z"]], maxlag=max(lags), verbose=False)
        vol_to_dt = grangercausalitytests(gdf[["dt_z", "log_rv"]], maxlag=max(lags), verbose=False)

    for lag in lags:
        stat, pvalue, df_denom, df_num = dt_to_vol[lag][0]["ssr_ftest"]
        out["dt_z_leads_log_rv"][str(lag)] = {
            "f_stat": float(stat),
            "pvalue": float(pvalue),
            "df_denom": float(df_denom),
            "df_num": float(df_num),
            "bonferroni_pass": bool(pvalue < out["bonferroni_alpha_all_tests"]),
        }
        stat, pvalue, df_denom, df_num = vol_to_dt[lag][0]["ssr_ftest"]
        out["log_rv_leads_dt_z"][str(lag)] = {
            "f_stat": float(stat),
            "pvalue": float(pvalue),
            "df_denom": float(df_denom),
            "df_num": float(df_num),
            "bonferroni_pass": bool(pvalue < out["bonferroni_alpha_all_tests"]),
        }
    return out


def describe_panel(panel: pd.DataFrame) -> dict:
    corr_value, corr_value_p = stats.spearmanr(panel["day_trading_value_pct"], panel["rv"])
    corr_volume, corr_volume_p = stats.spearmanr(panel["day_trading_volume_pct"], panel["rv"])
    return {
        "n": int(len(panel)),
        "start": str(panel["Date"].iloc[0].date()),
        "end": str(panel["Date"].iloc[-1].date()),
        "mean_day_trading_value_pct": float(panel["day_trading_value_pct"].mean()),
        "median_day_trading_value_pct": float(panel["day_trading_value_pct"].median()),
        "p95_day_trading_value_pct": float(panel["day_trading_value_pct"].quantile(0.95)),
        "mean_day_trading_volume_pct": float(panel["day_trading_volume_pct"].mean()),
        "mean_daily_rv": float(panel["rv"].mean()),
        "annualized_vol_from_mean_rv": float(np.sqrt(panel["rv"].mean() * 252)),
        "same_day_spearman_value_pct_vs_rv": float(corr_value),
        "same_day_spearman_value_pct_vs_rv_pvalue": float(corr_value_p),
        "same_day_spearman_volume_pct_vs_rv": float(corr_volume),
        "same_day_spearman_volume_pct_vs_rv_pvalue": float(corr_volume_p),
    }


def make_figures(results: dict, panels: dict[str, pd.DataFrame]) -> None:
    apply_cjk_style(dpi=170)
    FIG_DIR.mkdir(exist_ok=True)

    tw = panels["TWII"].copy()
    tw["rv22_ann"] = np.sqrt(tw["rv"].rolling(22).mean() * 252)
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(
        tw["Date"],
        tw["day_trading_value_pct"] * 100,
        color="#a84a2a",
        lw=1.0,
        label="當沖成交值占比",
    )
    ax1.set_ylabel("當沖成交值占比 (%)")
    ax2 = ax1.twinx()
    ax2.plot(tw["Date"], tw["rv22_ann"] * 100, color="#255f85", lw=1.0, alpha=0.75, label="22日年化RV")
    ax2.set_ylabel("22日年化 realized vol (%)")
    ax1.set_title("K1487：台股當沖占比與市場波動")
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1487_day_trading_ratio_timeseries.png")
    plt.close(fig)

    assets = list(results["assets"].keys())
    models = ["har_value_pct", "har_value_pct_z", "har_volume_pct_z"]
    labels = ["HAR+當沖值占比", "HAR+當沖值z", "HAR+當沖量z"]
    colors = ["#b84e35", "#386c5f", "#4d638f"]
    x = np.arange(len(assets))
    width = 0.22
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for i, (model, label, color) in enumerate(zip(models, labels, colors)):
        vals = [
            results["assets"][asset]["oos"]["models"][model]["rel_improvement_pct"]
            for asset in assets
        ]
        ax.bar(x + (i - 1) * width, vals, width=width, color=color, label=label)
    ax.axhline(0, color="black", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("QLIKE 相對 HAR 改善 (%)")
    ax.set_title("當沖訊號對 next-day RV 的 OOS 增量")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1487_oos_qlike_improvement.png")
    plt.close(fig)


def summarize_key_findings(results: dict) -> dict:
    tw = results["assets"]["TWII"]
    tw_models = tw["oos"]["models"]
    best_model = min(tw_models.items(), key=lambda kv: kv[1]["qlike"])[0]
    best = tw_models[best_model]

    gr = tw["granger"]
    dt_pass = [
        lag for lag, item in gr["dt_z_leads_log_rv"].items() if item["bonferroni_pass"]
    ]
    vol_pass = [
        lag for lag, item in gr["log_rv_leads_dt_z"].items() if item["bonferroni_pass"]
    ]
    extended_pass = [
        name
        for name, item in tw_models.items()
        if name != "har" and item["harvey_pass_vs_har"]
    ]
    return {
        "primary_asset": "TWII",
        "best_oos_model": best_model,
        "best_oos_rel_improvement_pct": best["rel_improvement_pct"],
        "any_harvey_pass_vs_har": bool(extended_pass),
        "harvey_pass_models": extended_pass,
        "granger_dt_to_vol_bonferroni_pass_lags": dt_pass,
        "granger_vol_to_dt_bonferroni_pass_lags": vol_pass,
        "interpretation": (
            "Day-trading intensity is treated as a lagged public market-wide signal. "
            "Trust only OOS QLIKE/DM and Bonferroni-adjusted Granger evidence; "
            "same-day correlations are descriptive and not a forecast claim."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-twse", action="store_true", help="refetch TWSE monthly API cache")
    parser.add_argument("--end-month", default=None, help="YYYY-MM; defaults to latest local TWII month")
    args = parser.parse_args()

    prices = {asset: load_yfinance_snapshot(path) for asset, path in PRICE_FILES.items()}
    latest_price_date = min(df["Date"].max() for df in prices.values())
    end_month = args.end_month or latest_price_date.strftime("%Y-%m")
    dt = load_twse_day_trading(refresh=args.refresh_twse, end_month=end_month)

    panels = {
        asset: build_panel(asset, price, dt)
        for asset, price in prices.items()
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "TWSE day-trading ratio and next-day Taiwan volatility",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "seed": SEED,
        "task_id": "research_herding",
        "data_sources": {
            "day_trading": {
                "source": "TWSE official /exchangeReport/TWTB4U2 monthly API",
                "cache": str(TWSE_CACHE.relative_to(REPO_ROOT)),
                "requested_months": [START_MONTH, end_month],
                "notes": "Market-level Day Trading Statistics; available since 2014-01-06 per TWSE page.",
            },
            "prices": {
                asset: str(path.relative_to(REPO_ROOT))
                for asset, path in PRICE_FILES.items()
            },
        },
        "timing": {
            "target": "date t close-to-close squared log return",
            "predictors": "HAR volatility features and TWSE day-trading ratios shifted by 1 trading day",
            "lookahead_guard": "panel features use explicit .shift(1); no same-day signal for same-day RV",
        },
        "assets": {},
    }

    for asset, panel in panels.items():
        results["assets"][asset] = {
            "description": describe_panel(panel),
            "hac_full_sample": {
                "har": hac_fit(panel, ["log_rv_lag1", "log_rv_lag5", "log_rv_lag22"]),
                "har_value_pct": hac_fit(
                    panel,
                    [
                        "log_rv_lag1",
                        "log_rv_lag5",
                        "log_rv_lag22",
                        "day_trading_value_pct_lag1",
                    ],
                ),
                "har_value_pct_z": hac_fit(
                    panel,
                    [
                        "log_rv_lag1",
                        "log_rv_lag5",
                        "log_rv_lag22",
                        "day_trading_value_pct_z_lag1",
                    ],
                ),
                "har_volume_pct_z": hac_fit(
                    panel,
                    [
                        "log_rv_lag1",
                        "log_rv_lag5",
                        "log_rv_lag22",
                        "day_trading_volume_pct_z_lag1",
                    ],
                ),
            },
            "oos": run_oos(panel),
            "granger": run_granger(panel),
        }

    results["key_findings"] = summarize_key_findings(results)
    make_figures(results, panels)

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(results["key_findings"], ensure_ascii=False, indent=2))
    print(f"Wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
