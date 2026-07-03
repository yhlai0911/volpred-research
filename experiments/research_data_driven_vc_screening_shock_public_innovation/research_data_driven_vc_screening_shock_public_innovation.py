#!/usr/bin/env python3
"""Public-proxy diagnostic for data-driven VC screening attention and innovation ETF volatility.

The experiment is intentionally narrower than the private-market mechanism in
Bonelli's RFS "Data-Driven Investors" paper. Free data do not identify VC-level
screening automation or startup financing decisions, so this script tests only a
public-market proxy:

    Do lagged SEC registration-statement bursts help forecast future volatility,
    downside variance, or dispersion in listed innovation proxies?

Lookahead policy:
    - SEC S-1/F-1 registration attention is bundled to trading days and then
      shifted by one trading day before it enters any model.
    - Forward 5d/21d variance targets use an embargo: a training row is allowed
      only if its target window ends strictly before the prediction date.
    - No same-day signal * same-day return PnL or causal private-VC claim is made.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "research_data_driven_vc_screening_shock_public_innovation"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
PRICE_CACHE = DATA_DIR / "innovation_etf_adjusted_close.csv"
SEC_CACHE = DATA_DIR / "sec_registration_attention_daily.csv"
TRADING_ATTENTION_CACHE = DATA_DIR / "sec_registration_attention_trading_day.csv"
PREDICTION_CACHE = DATA_DIR / "oos_predictions.csv"
FIG_PATH = FIG_DIR / "attention_oos_summary.png"

SEED = 42
EPS = 1.0e-12
DATA_START = "2018-01-01"
DATA_END_EXCLUSIVE = "2026-07-03"
OOS_START = "2021-01-01"
MIN_TRAIN_ROWS = 504
REFIT_EVERY = 21
HORIZONS = [5, 21]

PRIMARY_TICKERS = ["ARKK", "IPO", "IGV", "SOXX", "AIQ"]
CONTROL_TICKERS = ["QQQ", "SPY"]
TICKERS = PRIMARY_TICKERS + CONTROL_TICKERS

SEC_USER_AGENT = "VolPredResearch contact: research@example.com"
SEC_FORMS = {"S-1", "S-1/A", "F-1", "F-1/A"}
INNOVATION_NAME_RE = re.compile(
    r"\b(ARTIFICIAL|MACHINE LEARNING|ROBOT|SOFTWARE|CLOUD|DATA|SEMICONDUCTOR|BIOTECH|"
    r"GENOMIC|THERAPEUTICS|PHARMA|QUANTUM|AUTONOMOUS)\b",
    re.IGNORECASE,
)

LITERATURE_AND_CONTEXT = [
    {
        "citation": "Bonelli, Data-Driven Investors, The Review of Financial Studies",
        "url": "https://academic.oup.com/rfs/advance-article-abstract/doi/10.1093/rfs/hhaf078/8285007",
        "role": "Mechanism source: data-technology adoption by VCs changes innovation financing. This experiment does not replicate the paper's private VC data.",
    },
    {
        "citation": "CFA Institute Research Foundation (2025), AI in Asset Management: Tools, Applications, and Frontiers",
        "url": "https://rpc.cfainstitute.org/research/foundation/2025/ai-in-asset-management-book",
        "role": "Practitioner context for AI-enabled investment workflows and data-driven decision processes.",
    },
    {
        "citation": "Gompers et al. (2008), Venture Capital Investment Cycles: The Impact of Public Markets",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304405X07001419",
        "role": "Prior evidence that public-market signals and VC activity are linked; motivates a public-market spillover screen.",
    },
    {
        "citation": "Peters (2017), Volatility and Venture Capital",
        "url": "https://www.aeaweb.org/conference/2018/preliminary/paper/Y2HGh998",
        "role": "Context that VC performance can load on aggregate idiosyncratic volatility; not used as evidence of this proxy's result.",
    },
]


@dataclass(frozen=True)
class OOSSummary:
    ticker: str
    horizon: int
    n_oos: int
    oos_start: str
    oos_end: str
    qlike_baseline: float
    qlike_augmented: float
    qlike_improvement_pct: float
    dm_t_augmented_vs_baseline: float
    dm_p_value: float
    harvey_pass: bool
    mean_actual_variance: float
    mean_pred_baseline: float
    mean_pred_augmented: float


@dataclass(frozen=True)
class HACDiagnostic:
    target: str
    horizon: int
    n_obs: int
    beta_attention_z_lag1: float
    t_attention_z_lag1: float
    p_attention_z_lag1: float
    r2: float
    harvey_directional_pass: bool


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
    if value is pd.NA:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def fetch_close_panel(refresh: bool = False) -> pd.DataFrame:
    _ensure_dirs()
    if PRICE_CACHE.exists() and not refresh:
        return pd.read_csv(PRICE_CACHE, parse_dates=["Date"]).set_index("Date").sort_index()

    raw = yf.download(
        TICKERS,
        start=DATA_START,
        end=DATA_END_EXCLUSIVE,
        auto_adjust=True,
        progress=False,
        threads=False,
        group_by="ticker",
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned an empty dataframe")

    if isinstance(raw.columns, pd.MultiIndex):
        levels = [set(raw.columns.get_level_values(i)) for i in range(raw.columns.nlevels)]
        if "Close" in levels[0]:
            close = raw["Close"].copy()
        elif "Close" in levels[-1]:
            close = raw.xs("Close", axis=1, level=-1).copy()
        else:
            raise RuntimeError(f"Cannot locate Close columns in yfinance output: {raw.columns}")
    else:
        if "Close" not in raw.columns:
            raise RuntimeError(f"Cannot locate Close column in yfinance output: {raw.columns}")
        close = raw[["Close"]].copy()
        close.columns = [TICKERS[0]]

    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.loc[:, [ticker for ticker in TICKERS if ticker in close.columns]]
    close = close.dropna(how="all").sort_index()
    close.to_csv(PRICE_CACHE, index_label="Date")
    return close


def fetch_sec_registration_attention(refresh: bool = False) -> pd.DataFrame:
    _ensure_dirs()
    if SEC_CACHE.exists() and not refresh:
        return pd.read_csv(SEC_CACHE, parse_dates=["date"]).set_index("date").sort_index()

    rows: list[dict[str, Any]] = []
    for year in range(2018, 2027):
        max_qtr = 3 if year == 2026 else 4
        for qtr in range(1, max_qtr + 1):
            url = f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{qtr}/master.gz"
            print(f"[sec] fetch {year} QTR{qtr}", file=sys.stderr)
            completed = subprocess.run(
                ["curl", "-sS", "-L", "--max-time", "60", "-A", SEC_USER_AGENT, url],
                capture_output=True,
                timeout=75,
                check=False,
            )
            if completed.returncode != 0:
                if year == 2026 and qtr == 3:
                    continue
                raise RuntimeError((completed.stderr or completed.stdout)[:500])
            try:
                text = gzip.decompress(completed.stdout).decode("latin-1")
            except gzip.BadGzipFile:
                if year == 2026 and qtr == 3:
                    continue
                raise
            for line in text.splitlines():
                if "|" not in line or line.startswith("CIK|") or line.startswith("---"):
                    continue
                parts = line.split("|")
                if len(parts) != 5:
                    continue
                _, company_name, form_type, date_filed, _ = parts
                rows.append(
                    {
                        "date": pd.Timestamp(date_filed),
                        "company_name": company_name,
                        "form_type": form_type,
                        "is_registration": form_type in SEC_FORMS,
                        "is_innovation_name": bool(INNOVATION_NAME_RE.search(company_name)),
                    }
                )

    filings = pd.DataFrame(rows)
    if filings.empty:
        raise RuntimeError("SEC master indexes returned no parseable rows")
    grouped = filings.groupby("date").agg(
        event_count=("is_registration", "sum"),
        total_filings=("form_type", "size"),
        innovation_event_count=("is_innovation_name", lambda x: int((filings.loc[x.index, "is_registration"] & x).sum())),
    )
    full_index = pd.date_range(DATA_START, DATA_END_EXCLUSIVE, freq="D", inclusive="left")
    out = grouped.reindex(full_index).fillna(0.0)
    out.index.name = "date"
    out["events_per_1000_filings"] = out["event_count"] / out["total_filings"].replace(0.0, np.nan) * 1000.0
    out["events_per_1000_filings"] = out["events_per_1000_filings"].fillna(0.0)
    out.to_csv(SEC_CACHE, index_label="date")
    return out


def align_attention_to_trading_days(attention_daily: pd.DataFrame, trading_index: pd.Index) -> pd.DataFrame:
    """Bundle calendar-day financing-window attention into trading-day buckets.

    A Monday bucket includes weekend filings after the previous trading day and
    through Monday. Models then use bucket values only after shift(1).
    """
    rows: list[dict[str, Any]] = []
    prev_day: pd.Timestamp | None = None
    for trading_day in pd.to_datetime(trading_index).normalize():
        if prev_day is None:
            mask = attention_daily.index <= trading_day
        else:
            mask = (attention_daily.index > prev_day) & (attention_daily.index <= trading_day)
        chunk = attention_daily.loc[mask]
        total = float(chunk["total_filings"].sum())
        count = float(chunk["event_count"].sum())
        innovation_count = float(chunk.get("innovation_event_count", pd.Series(dtype=float)).sum())
        rows.append(
            {
                "Date": trading_day,
                "calendar_days_in_bucket": int(len(chunk)),
                "event_count": count,
                "innovation_event_count": innovation_count,
                "total_filings": total,
                "events_per_1000_filings": count / max(total, 1.0) * 1000.0,
            }
        )
        prev_day = trading_day

    out = pd.DataFrame(rows).set_index("Date").sort_index()
    log_attention = np.log1p(out["events_per_1000_filings"])
    rolling_mean = log_attention.rolling(252, min_periods=126).mean()
    rolling_std = log_attention.rolling(252, min_periods=126).std(ddof=0)
    out["log_events_per_1000_filings"] = log_attention
    out["attention_z"] = (log_attention - rolling_mean) / rolling_std.replace(0.0, np.nan)
    out["attention_z_5d"] = out["attention_z"].rolling(5, min_periods=3).mean()
    out.to_csv(TRADING_ATTENTION_CACHE, index_label="Date")
    return out


def _forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    return series.rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def build_asset_frame(
    *,
    ticker: str,
    horizon: int,
    returns: pd.DataFrame,
    attention: pd.DataFrame,
) -> pd.DataFrame:
    rv = returns[ticker].pow(2)
    market_rv21 = returns[[c for c in CONTROL_TICKERS if c in returns.columns]].pow(2).rolling(21).sum().mean(axis=1)

    frame = pd.DataFrame(index=returns.index)
    frame["date"] = frame.index
    frame["pos"] = np.arange(len(frame))
    frame["ticker"] = ticker
    frame["horizon"] = horizon
    frame["target_var"] = _forward_sum(rv, horizon)
    frame["target_end_pos"] = frame["pos"] + horizon - 1
    frame["log_rv_lag1"] = np.log(rv.shift(1) + EPS)
    frame["log_rv_lag5"] = np.log(rv.rolling(5, min_periods=5).sum().shift(1) + EPS)
    frame["log_rv_lag21"] = np.log(rv.rolling(21, min_periods=21).sum().shift(1) + EPS)
    frame["abs_ret_lag1"] = returns[ticker].abs().shift(1)
    frame["neg_ret_lag1"] = returns[ticker].clip(upper=0.0).shift(1)
    frame["market_log_rv21_lag1"] = np.log(market_rv21.shift(1) + EPS)
    frame["attention_z_lag1"] = attention["attention_z"].shift(1)
    frame["attention_z_5d_lag1"] = attention["attention_z_5d"].shift(1)
    return frame


BASE_FEATURES = [
    "log_rv_lag1",
    "log_rv_lag5",
    "log_rv_lag21",
    "abs_ret_lag1",
    "neg_ret_lag1",
    "market_log_rv21_lag1",
]
AUG_FEATURES = BASE_FEATURES + ["attention_z_lag1", "attention_z_5d_lag1"]


def _ols_fit_predict(train: pd.DataFrame, row: pd.Series, features: list[str]) -> float:
    x = train[features].to_numpy(dtype=float)
    y = np.log(train["target_var"].to_numpy(dtype=float) + EPS)
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    current = np.array([1.0] + [float(row[col]) for col in features], dtype=float)
    pred_log = float(current @ beta)
    return float(np.exp(np.clip(pred_log, np.log(EPS), np.log(1.0))))


def run_expanding_oos(frame: pd.DataFrame, horizon: int) -> tuple[pd.DataFrame, OOSSummary | None]:
    needed = AUG_FEATURES + ["target_var", "target_end_pos", "pos"]
    valid = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=needed).copy()
    valid = valid[valid["target_var"] > 0].copy()
    max_data_pos = int(frame["pos"].max())
    oos_rows = valid[valid.index >= pd.Timestamp(OOS_START)].copy()
    predictions: list[dict[str, Any]] = []
    last_fit_pos: int | None = None
    cached_train_base: pd.DataFrame | None = None
    cached_train_aug: pd.DataFrame | None = None

    for date, row in oos_rows.iterrows():
        current_pos = int(row["pos"])
        if int(row["target_end_pos"]) > max_data_pos:
            continue
        if last_fit_pos is None or current_pos - last_fit_pos >= REFIT_EVERY:
            train = valid[valid["target_end_pos"] < current_pos].copy()
            train = train[train.index < date]
            if len(train) < MIN_TRAIN_ROWS:
                continue
            cached_train_base = train.dropna(subset=BASE_FEATURES + ["target_var"])
            cached_train_aug = train.dropna(subset=AUG_FEATURES + ["target_var"])
            last_fit_pos = current_pos
        if cached_train_base is None or cached_train_aug is None:
            continue
        if len(cached_train_base) < MIN_TRAIN_ROWS or len(cached_train_aug) < MIN_TRAIN_ROWS:
            continue

        pred_base = _ols_fit_predict(cached_train_base, row, BASE_FEATURES)
        pred_aug = _ols_fit_predict(cached_train_aug, row, AUG_FEATURES)
        predictions.append(
            {
                "date": date,
                "ticker": row["ticker"],
                "horizon": horizon,
                "actual_var": float(row["target_var"]),
                "pred_baseline": pred_base,
                "pred_augmented": pred_aug,
            }
        )

    pred = pd.DataFrame(predictions)
    if len(pred) < 252:
        return pred, None

    loss_aug = qlike_pointwise(pred["actual_var"].to_numpy(), pred["pred_augmented"].to_numpy())
    loss_base = qlike_pointwise(pred["actual_var"].to_numpy(), pred["pred_baseline"].to_numpy())
    dm_t, dm_p = dm_test(loss_aug, loss_base, h=horizon)
    q_base = qlike(pred["actual_var"].to_numpy(), pred["pred_baseline"].to_numpy())
    q_aug = qlike(pred["actual_var"].to_numpy(), pred["pred_augmented"].to_numpy())
    improvement = (q_base - q_aug) / abs(q_base) * 100.0 if np.isfinite(q_base) and abs(q_base) > EPS else np.nan
    summary = OOSSummary(
        ticker=str(pred["ticker"].iloc[0]),
        horizon=horizon,
        n_oos=int(len(pred)),
        oos_start=pd.Timestamp(pred["date"].min()).strftime("%Y-%m-%d"),
        oos_end=pd.Timestamp(pred["date"].max()).strftime("%Y-%m-%d"),
        qlike_baseline=float(q_base),
        qlike_augmented=float(q_aug),
        qlike_improvement_pct=float(improvement),
        dm_t_augmented_vs_baseline=float(dm_t),
        dm_p_value=float(dm_p),
        harvey_pass=bool((q_aug < q_base) and (dm_t <= -3.0)),
        mean_actual_variance=float(pred["actual_var"].mean()),
        mean_pred_baseline=float(pred["pred_baseline"].mean()),
        mean_pred_augmented=float(pred["pred_augmented"].mean()),
    )
    return pred, summary


def run_oos_suite(close: pd.DataFrame, attention: pd.DataFrame) -> tuple[pd.DataFrame, list[OOSSummary]]:
    returns = np.log(close / close.shift(1))
    predictions: list[pd.DataFrame] = []
    summaries: list[OOSSummary] = []
    for ticker in [t for t in PRIMARY_TICKERS if t in returns.columns]:
        for horizon in HORIZONS:
            frame = build_asset_frame(ticker=ticker, horizon=horizon, returns=returns, attention=attention)
            pred, summary = run_expanding_oos(frame, horizon)
            if not pred.empty:
                predictions.append(pred)
            if summary is not None:
                summaries.append(summary)
    all_predictions = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    if not all_predictions.empty:
        all_predictions.to_csv(PREDICTION_CACHE, index=False)
    return all_predictions, summaries


def _hac_regression(df: pd.DataFrame, target_col: str, horizon: int) -> HACDiagnostic:
    regressors = [
        "attention_z_lag1",
        "attention_z_5d_lag1",
        "target_log_lag21",
        "market_log_rv21_lag1",
    ]
    model_df = df[[target_col] + regressors].replace([np.inf, -np.inf], np.nan).dropna().copy()
    model_df = model_df[model_df[target_col] > 0]
    y = np.log(model_df[target_col] + EPS)
    x = sm.add_constant(model_df[regressors], has_constant="add")
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": max(1, horizon - 1)})
    beta = float(fit.params.get("attention_z_lag1", np.nan))
    t_stat = float(fit.tvalues.get("attention_z_lag1", np.nan))
    p_value = float(fit.pvalues.get("attention_z_lag1", np.nan))
    return HACDiagnostic(
        target=target_col,
        horizon=horizon,
        n_obs=int(len(model_df)),
        beta_attention_z_lag1=beta,
        t_attention_z_lag1=t_stat,
        p_attention_z_lag1=p_value,
        r2=float(fit.rsquared),
        harvey_directional_pass=bool(beta > 0 and t_stat >= 3.0),
    )


def run_aggregate_diagnostics(close: pd.DataFrame, attention: pd.DataFrame) -> tuple[list[HACDiagnostic], dict[str, Any]]:
    returns = np.log(close / close.shift(1))
    primary = [ticker for ticker in PRIMARY_TICKERS if ticker in returns.columns]
    market_rv21 = returns[[c for c in CONTROL_TICKERS if c in returns.columns]].pow(2).rolling(21).sum().mean(axis=1)

    diagnostics: list[HACDiagnostic] = []
    shock_contrasts: dict[str, Any] = {}
    for horizon in HORIZONS:
        base = pd.DataFrame(index=returns.index)
        basket_ret = returns[primary].mean(axis=1)
        daily_dispersion = returns[primary].var(axis=1, ddof=0)
        base[f"innovation_basket_rv_{horizon}d"] = _forward_sum(basket_ret.pow(2), horizon)
        if "IPO" in returns.columns:
            base[f"ipo_downside_var_{horizon}d"] = _forward_sum(returns["IPO"].clip(upper=0.0).pow(2), horizon)
        base[f"innovation_dispersion_{horizon}d"] = _forward_sum(daily_dispersion, horizon)
        base["attention_z_lag1"] = attention["attention_z"].shift(1)
        base["attention_z_5d_lag1"] = attention["attention_z_5d"].shift(1)
        base["market_log_rv21_lag1"] = np.log(market_rv21.shift(1) + EPS)

        for target_col in [c for c in base.columns if c.endswith(f"_{horizon}d")]:
            past_metric = base[target_col].shift(horizon)
            base["target_log_lag21"] = np.log(past_metric.rolling(21, min_periods=10).mean().shift(1) + EPS)
            diagnostics.append(_hac_regression(base, target_col, horizon))

        if horizon == 5:
            target_col = "innovation_basket_rv_5d"
            threshold = base["attention_z_lag1"].rolling(504, min_periods=252).quantile(0.90).shift(1)
            shock = base["attention_z_lag1"] > threshold
            shock_df = base[[target_col]].copy()
            shock_df["shock"] = shock
            shock_df = shock_df.replace([np.inf, -np.inf], np.nan).dropna()
            shock_vals = shock_df.loc[shock_df["shock"], target_col]
            normal_vals = shock_df.loc[~shock_df["shock"], target_col]
            if len(shock_vals) >= 20 and len(normal_vals) >= 100:
                test = sm.stats.ttest_ind(shock_vals.to_numpy(), normal_vals.to_numpy(), usevar="unequal")
                shock_contrasts = {
                    "target": target_col,
                    "definition": "attention_z_lag1 above prior 504-trading-day rolling 90th percentile",
                    "n_shock": int(len(shock_vals)),
                    "n_nonshock": int(len(normal_vals)),
                    "mean_shock": float(shock_vals.mean()),
                    "mean_nonshock": float(normal_vals.mean()),
                    "mean_diff": float(shock_vals.mean() - normal_vals.mean()),
                    "welch_t": float(test[0]),
                    "welch_p": float(test[1]),
                }

    return diagnostics, shock_contrasts


def make_figure(attention: pd.DataFrame, summaries: list[OOSSummary]) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), dpi=150, gridspec_kw={"height_ratios": [1.4, 1.0]})

    plot_attention = attention["attention_z"].dropna()
    axes[0].plot(plot_attention.index, plot_attention.values, color="#1f4e79", linewidth=1.2)
    axes[0].axhline(0, color="#888888", linewidth=0.8)
    axes[0].axhline(2, color="#b35c00", linewidth=0.8, linestyle="--")
    axes[0].set_title("SEC S-1/F-1 registration attention z-score (trading-day buckets)")
    axes[0].set_ylabel("z-score")
    axes[0].grid(alpha=0.25)

    summary_df = pd.DataFrame([asdict(item) for item in summaries])
    if not summary_df.empty:
        summary_df["label"] = summary_df["ticker"] + " " + summary_df["horizon"].astype(str) + "d"
        colors = ["#0b6bcb" if v > 0 else "#9c2f2f" for v in summary_df["qlike_improvement_pct"]]
        axes[1].bar(summary_df["label"], summary_df["qlike_improvement_pct"], color=colors)
        axes[1].axhline(0, color="#555555", linewidth=0.8)
        axes[1].set_ylabel("QLIKE improvement vs baseline (%)")
        axes[1].set_title("OOS augmented model: positive bars mean lower QLIKE after adding attention")
        axes[1].tick_params(axis="x", rotation=45)
        axes[1].grid(axis="y", alpha=0.25)
    else:
        axes[1].text(0.5, 0.5, "No OOS summaries", ha="center", va="center")
        axes[1].axis("off")

    fig.tight_layout()
    fig.savefig(FIG_PATH)
    plt.close(fig)


def determine_verdict(oos_summaries: list[OOSSummary], diagnostics: list[HACDiagnostic]) -> dict[str, Any]:
    oos_passes = [item for item in oos_summaries if item.harvey_pass]
    hac_passes = [item for item in diagnostics if item.harvey_directional_pass]
    directionally_better = [
        item for item in oos_summaries if item.qlike_augmented < item.qlike_baseline and item.dm_t_augmented_vs_baseline < 0
    ]
    if len(oos_passes) >= 2:
        verdict = "PUBLIC_PROXY_OOS_PASS"
    elif len(oos_passes) == 1 or len(hac_passes) >= 2:
        verdict = "DIRECTIONAL_ONLY_PUBLIC_PROXY_DIAGNOSTIC"
    else:
        verdict = "NULL_PUBLIC_PROXY_DIAGNOSTIC"

    return {
        "verdict": verdict,
        "oos_harvey_pass_count": len(oos_passes),
        "hac_directional_pass_count": len(hac_passes),
        "oos_directionally_better_count": len(directionally_better),
        "total_oos_cells": len(oos_summaries),
        "strong_gate": "PASS requires >=2 OOS cells where augmented QLIKE is lower and DM t <= -3.0; otherwise report as diagnostic/null.",
    }


def run(refresh: bool = False) -> dict[str, Any]:
    np.random.seed(SEED)
    _ensure_dirs()
    close = fetch_close_panel(refresh=refresh)
    sec_daily = fetch_sec_registration_attention(refresh=refresh)
    attention = align_attention_to_trading_days(sec_daily, close.index)
    _, summaries = run_oos_suite(close, attention)
    diagnostics, shock_contrasts = run_aggregate_diagnostics(close, attention)
    make_figure(attention, summaries)

    loaded_primary = [ticker for ticker in PRIMARY_TICKERS if ticker in close.columns]
    verdict = determine_verdict(summaries, diagnostics)
    attention_summary = {
        "proxy": "SEC EDGAR daily count of S-1/S-1/A/F-1/F-1/A registration statements",
        "daily_calendar_start": sec_daily.index.min().strftime("%Y-%m-%d"),
        "daily_calendar_end": sec_daily.index.max().strftime("%Y-%m-%d"),
        "trading_start": attention.index.min().strftime("%Y-%m-%d"),
        "trading_end": attention.index.max().strftime("%Y-%m-%d"),
        "total_registration_count": float(sec_daily["event_count"].sum()),
        "total_innovation_name_registration_count": float(sec_daily["innovation_event_count"].sum()),
        "mean_trading_bucket_events_per_1000_filings": float(attention["events_per_1000_filings"].mean()),
        "max_attention_z": float(attention["attention_z"].max()),
        "max_attention_z_date": attention["attention_z"].idxmax().strftime("%Y-%m-%d"),
        "n_trading_attention_rows": int(len(attention)),
    }
    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "price_source": "yfinance adjusted close, auto_adjust=True",
            "attention_source": "SEC EDGAR full-index master.gz daily S-1/S-1-A/F-1/F-1-A registration counts",
            "sample_start": close.index.min().strftime("%Y-%m-%d"),
            "sample_end": close.index.max().strftime("%Y-%m-%d"),
            "loaded_tickers": list(close.columns),
            "primary_tickers_loaded": loaded_primary,
            "control_tickers_loaded": [ticker for ticker in CONTROL_TICKERS if ticker in close.columns],
            "n_price_rows": int(len(close)),
        },
        "lookahead_controls": {
            "attention": "attention_z_lag1 = trading-day SEC registration attention shifted by one trading day",
            "oos_embargo": "training rows require target_end_pos < prediction_pos for each 5d/21d forward target",
            "targets": "future variance targets are used only as dependent variables/evaluation targets, never as same-day signals",
        },
        "attention_summary": attention_summary,
        "oos_results": [asdict(item) for item in summaries],
        "aggregate_hac_diagnostics": [asdict(item) for item in diagnostics],
        "shock_contrast": shock_contrasts,
        "literature_and_context": LITERATURE_AND_CONTEXT,
        "outputs": {
            "results_json": str(RESULTS_PATH.relative_to(HERE)),
            "price_cache": str(PRICE_CACHE.relative_to(HERE)),
            "sec_registration_cache": str(SEC_CACHE.relative_to(HERE)),
            "trading_attention_cache": str(TRADING_ATTENTION_CACHE.relative_to(HERE)),
            "prediction_cache": str(PREDICTION_CACHE.relative_to(HERE)),
            "figure": str(FIG_PATH.relative_to(HERE)),
        },
        "limitations": [
            "SEC registration attention is a public financing-window proxy and does not observe VC screening automation adoption.",
            "ETF baskets are listed-market proxies and cannot identify startup financing gates or VC-backed private-company cohorts directly.",
            "Daily close-to-close variance is coarser than intraday volatility and can miss announcement-time effects.",
            "A null result here does not refute Bonelli's private-market mechanism; it only limits the publishable claim from free public proxies.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(_json_safe(results), indent=2, ensure_ascii=False) + "\n")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance and SEC index data")
    args = parser.parse_args()
    results = run(refresh=args.refresh)
    print(json.dumps(_json_safe({"experiment_id": EXPERIMENT_ID, "verdict": results["verdict"]}), indent=2))


if __name__ == "__main__":
    main()
