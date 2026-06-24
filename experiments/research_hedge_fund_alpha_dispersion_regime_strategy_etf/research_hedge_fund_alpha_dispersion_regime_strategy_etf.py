#!/usr/bin/env python3
"""Strategy-ETF dispersion as a free hedge-fund alpha-dispersion proxy."""

from __future__ import annotations

import json
import math
import time
import warnings
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_hedge_fund_alpha_dispersion_regime_strategy_etf"
OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
RESULTS_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"

START_DATE = "2018-01-01"
HORIZON = 22
MIN_STRATEGY_ETFS = 5
MIN_SP500_NAMES = 400
MIN_TOP_HOLDING_NAMES = 5
REFIT_EVERY = 21
EPS = 1e-12

STRATEGY_ETFS = ["QAI", "MNA", "CTA", "DBMF", "MRGR", "HFXI", "RPAR"]
MARKET_TICKERS = ["SPY", "^VIX"]

BASE_STATIC_COLS = [
    "spy_ret22_lag1",
    "spy_rv22_lag1",
    "vix_level_lag1",
    "vix_chg22_lag1",
]

STRATEGY_SIGNAL_COLS = [
    "strategy_disp21_lag1",
    "strategy_disp63_lag1",
]


@dataclass
class FittedOLS:
    cols: list[str]
    means: pd.Series
    stds: pd.Series
    params: pd.Series


def normalize_ticker(ticker: str) -> str:
    return str(ticker).strip().upper().replace(".", "-")


def get_sp500_constituents() -> pd.DataFrame:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    html = requests.get(url, headers=headers, timeout=30).text
    table = pd.read_html(StringIO(html))[0]
    table["yf_symbol"] = table["Symbol"].map(normalize_ticker)
    return table


def get_yfinance_top_holdings(etf: str) -> list[str]:
    funds_data = yf.Ticker(etf).funds_data
    holdings = funds_data.top_holdings
    if holdings is None or holdings.empty:
        return []
    return [normalize_ticker(t) for t in holdings.index.tolist()]


def extract_close(downloaded: pd.DataFrame, requested: list[str]) -> pd.DataFrame:
    if downloaded.empty:
        return pd.DataFrame()
    if isinstance(downloaded.columns, pd.MultiIndex):
        level0 = downloaded.columns.get_level_values(0)
        level1 = downloaded.columns.get_level_values(1)
        if "Close" in set(level1):
            close = downloaded.xs("Close", axis=1, level=1, drop_level=True)
        elif "Close" in set(level0):
            close = downloaded.xs("Close", axis=1, level=0, drop_level=True)
        else:
            raise ValueError("No Close column in yfinance MultiIndex download")
    else:
        if "Close" not in downloaded.columns:
            raise ValueError("No Close column in yfinance download")
        if len(requested) == 1:
            close = downloaded[["Close"]].rename(columns={"Close": requested[0]})
        else:
            close = downloaded["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(requested[0])
    close.columns = [normalize_ticker(c) for c in close.columns]
    close = close.loc[:, ~close.columns.duplicated()]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.sort_index()


def download_close(tickers: Iterable[str], start: str = START_DATE, chunk_size: int = 80) -> pd.DataFrame:
    unique = list(dict.fromkeys(normalize_ticker(t) for t in tickers if str(t).strip()))
    frames: list[pd.DataFrame] = []
    for i in range(0, len(unique), chunk_size):
        chunk = unique[i : i + chunk_size]
        if not chunk:
            continue
        for attempt in range(2):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", FutureWarning)
                    raw = yf.download(
                        chunk,
                        start=start,
                        auto_adjust=True,
                        progress=False,
                        threads=True,
                        group_by="ticker",
                    )
                close = extract_close(raw, chunk)
                frames.append(close)
                break
            except Exception as exc:
                if attempt == 1:
                    print(f"download failed for chunk {chunk[:3]}...: {exc}")
                else:
                    time.sleep(1.0)
    if not frames:
        return pd.DataFrame()
    close = pd.concat(frames, axis=1).sort_index()
    close = close.loc[:, ~close.columns.duplicated()]
    return close.dropna(axis=1, how="all")


def build_features(strategy_prices: pd.DataFrame, market_prices: pd.DataFrame) -> pd.DataFrame:
    strategy_returns = np.log(strategy_prices).diff()
    n_strategy = strategy_returns.notna().sum(axis=1).rename("strategy_n_etfs")
    daily_xs_std = strategy_returns.std(axis=1, skipna=True).where(n_strategy >= MIN_STRATEGY_ETFS)
    daily_xs_std.name = "strategy_daily_xs_std"

    strategy_disp21 = daily_xs_std.rolling(21, min_periods=15).mean().rename("strategy_disp21")
    strategy_disp63 = daily_xs_std.rolling(63, min_periods=45).mean().rename("strategy_disp63")

    spy_ret = np.log(market_prices["SPY"]).diff()
    spy_ret22 = spy_ret.rolling(22, min_periods=18).sum().rename("spy_ret22")
    spy_rv22 = spy_ret.pow(2).rolling(22, min_periods=18).sum().rename("spy_rv22")
    vix = market_prices["^VIX"].rename("vix_level")
    vix_chg22 = vix.diff(22).rename("vix_chg22")

    raw = pd.concat(
        [strategy_disp21, strategy_disp63, n_strategy, spy_ret22, spy_rv22, vix, vix_chg22],
        axis=1,
    )
    # Explicitly lag every signal/control by one trading day before prediction.
    return raw.shift(1).add_suffix("_lag1")


def forward_sum_df(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    return df.rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def backward_sum_df(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    return df.rolling(horizon, min_periods=horizon).sum().shift(1)


def build_universe_targets(
    close: pd.DataFrame,
    label: str,
    horizon: int,
    min_names: int,
    include_cross_sectional_return_var: bool,
) -> dict[str, pd.DataFrame]:
    returns = np.log(close).diff()
    out: dict[str, pd.DataFrame] = {}

    fwd_rv = forward_sum_df(returns.pow(2), horizon)
    back_rv = backward_sum_df(returns.pow(2), horizon)
    valid_fwd_rv = fwd_rv.notna().sum(axis=1)
    valid_back_rv = back_rv.notna().sum(axis=1)
    avg_rv_target = fwd_rv.mean(axis=1, skipna=True).where(valid_fwd_rv >= min_names)
    avg_rv_back = back_rv.mean(axis=1, skipna=True).where(valid_back_rv >= min_names)
    out[f"{label}_avg_individual_rv_{horizon}d"] = pd.DataFrame(
        {
            "target": avg_rv_target,
            "target_back_lag1": avg_rv_back,
            "target_valid_names": valid_fwd_rv,
        }
    )

    if include_cross_sectional_return_var:
        fwd_ret = forward_sum_df(returns, horizon)
        back_ret = backward_sum_df(returns, horizon)
        valid_fwd_ret = fwd_ret.notna().sum(axis=1)
        valid_back_ret = back_ret.notna().sum(axis=1)
        xs_var_target = fwd_ret.var(axis=1, skipna=True).where(valid_fwd_ret >= min_names)
        xs_var_back = back_ret.var(axis=1, skipna=True).where(valid_back_ret >= min_names)
        out[f"{label}_xs_return_var_{horizon}d"] = pd.DataFrame(
            {
                "target": xs_var_target,
                "target_back_lag1": xs_var_back,
                "target_valid_names": valid_fwd_ret,
            }
        )
    return out


def qlike(actual: pd.Series | np.ndarray, forecast: pd.Series | np.ndarray) -> np.ndarray:
    actual_arr = np.asarray(actual, dtype=float)
    forecast_arr = np.asarray(forecast, dtype=float)
    ratio = np.clip(actual_arr, EPS, None) / np.clip(forecast_arr, EPS, None)
    return ratio - np.log(ratio) - 1.0


def hac_mean_test(x: Iterable[float], maxlags: int) -> dict[str, float]:
    arr = pd.Series(list(x), dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(arr) < 30 or float(arr.std(ddof=1)) <= EPS:
        return {
            "mean": float(arr.mean()) if len(arr) else math.nan,
            "t": math.nan,
            "p": math.nan,
            "n": int(len(arr)),
        }
    model = sm.OLS(arr.to_numpy(), np.ones((len(arr), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": maxlags}
    )
    return {
        "mean": float(model.params[0]),
        "t": float(model.tvalues[0]),
        "p": float(model.pvalues[0]),
        "n": int(len(arr)),
    }


def fit_ols(train: pd.DataFrame, target_col: str, cols: list[str]) -> FittedOLS:
    x = train[cols].astype(float)
    means = x.mean()
    stds = x.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    xz = (x - means) / stds
    xz = sm.add_constant(xz, has_constant="add")
    y = np.log(train[target_col].clip(lower=EPS))
    result = sm.OLS(y, xz).fit()
    return FittedOLS(cols=cols, means=means, stds=stds, params=result.params)


def predict_ols(model: FittedOLS, row: pd.Series) -> float:
    x = row[model.cols].astype(float)
    xz = (x - model.means) / model.stds
    xz = pd.Series({"const": 1.0, **xz.to_dict()})
    xz = xz.reindex(model.params.index)
    pred_log = float(np.dot(xz.to_numpy(dtype=float), model.params.to_numpy(dtype=float)))
    return float(np.exp(np.clip(pred_log, -40.0, 20.0)))


def split_position(clean: pd.DataFrame, min_train: int) -> int:
    calendar_pos = int(clean.index.searchsorted(pd.Timestamp("2022-01-03")))
    if calendar_pos >= min_train + HORIZON and len(clean) - calendar_pos >= 252:
        pos = calendar_pos
    else:
        pos = int(len(clean) * 0.70)
    return max(pos, min_train + HORIZON)


def expanding_oos(
    data: pd.DataFrame,
    target_col: str,
    base_cols: list[str],
    aug_cols: list[str],
    min_train: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    cols = list(dict.fromkeys([target_col] + base_cols + aug_cols))
    clean = (
        data[cols]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .loc[lambda d: d[target_col] > EPS]
        .copy()
    )
    if len(clean) < min_train + HORIZON + 80:
        return pd.DataFrame(), {
            "status": "skipped",
            "reason": "insufficient_clean_rows",
            "clean_rows": int(len(clean)),
        }

    first_oos = split_position(clean, min_train)
    records: list[dict[str, object]] = []
    base_model: FittedOLS | None = None
    aug_model: FittedOLS | None = None
    last_refit_pos = -10**9
    refit_count = 0

    for i in range(first_oos, len(clean)):
        train_stop = i - HORIZON + 1
        if train_stop < min_train:
            continue
        if base_model is None or i - last_refit_pos >= REFIT_EVERY:
            train = clean.iloc[:train_stop]
            base_model = fit_ols(train, target_col, base_cols)
            aug_model = fit_ols(train, target_col, aug_cols)
            last_refit_pos = i
            refit_count += 1
        row = clean.iloc[i]
        assert base_model is not None and aug_model is not None
        records.append(
            {
                "date": clean.index[i],
                "actual": float(row[target_col]),
                "pred_base": predict_ols(base_model, row),
                "pred_aug": predict_ols(aug_model, row),
            }
        )

    pred = pd.DataFrame.from_records(records)
    if pred.empty:
        return pred, {"status": "skipped", "reason": "no_oos_predictions"}
    pred["date"] = pd.to_datetime(pred["date"])
    pred = pred.set_index("date").sort_index()
    meta = {
        "status": "ok",
        "clean_rows": int(len(clean)),
        "oos_rows": int(len(pred)),
        "first_clean_date": clean.index.min().date().isoformat(),
        "last_clean_date": clean.index.max().date().isoformat(),
        "first_oos_date": pred.index.min().date().isoformat(),
        "last_oos_date": pred.index.max().date().isoformat(),
        "min_train": int(min_train),
        "refit_every": int(REFIT_EVERY),
        "refit_count": int(refit_count),
    }
    return pred, meta


def evaluate_prediction(pred: pd.DataFrame) -> dict[str, object]:
    if pred.empty:
        return {"status": "skipped"}
    loss_base = qlike(pred["actual"], pred["pred_base"])
    loss_aug = qlike(pred["actual"], pred["pred_aug"])
    mse_base = np.square(pred["actual"] - pred["pred_base"])
    mse_aug = np.square(pred["actual"] - pred["pred_aug"])
    qlike_diff = loss_base - loss_aug
    mse_diff = mse_base - mse_aug
    return {
        "status": "ok",
        "qlike_base": float(np.mean(loss_base)),
        "qlike_aug": float(np.mean(loss_aug)),
        "qlike_improvement_pct": float(100.0 * (np.mean(loss_base) - np.mean(loss_aug)) / np.mean(loss_base)),
        "qlike_dm": hac_mean_test(qlike_diff, maxlags=HORIZON),
        "mse_base": float(np.mean(mse_base)),
        "mse_aug": float(np.mean(mse_aug)),
        "mse_improvement_pct": float(100.0 * (np.mean(mse_base) - np.mean(mse_aug)) / np.mean(mse_base)),
        "mse_dm": hac_mean_test(mse_diff, maxlags=HORIZON),
    }


def hac_coefficients(data: pd.DataFrame, target_col: str, cols: list[str]) -> dict[str, dict[str, float]]:
    clean = (
        data[[target_col] + cols]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .loc[lambda d: d[target_col] > EPS]
    )
    if len(clean) < 120:
        return {}
    x = clean[cols].astype(float)
    x = (x - x.mean()) / x.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    y = np.log(clean[target_col].clip(lower=EPS))
    result = sm.OLS(y, sm.add_constant(x, has_constant="add")).fit(
        cov_type="HAC", cov_kwds={"maxlags": HORIZON}
    )
    out: dict[str, dict[str, float]] = {}
    for col in STRATEGY_SIGNAL_COLS:
        if col in result.params.index:
            out[col] = {
                "coef": float(result.params[col]),
                "t": float(result.tvalues[col]),
                "p": float(result.pvalues[col]),
            }
    return out


def quintile_diagnostic(data: pd.DataFrame, target_col: str) -> list[dict[str, object]]:
    clean = data[[target_col, "strategy_disp21_lag1"]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 150:
        return []
    clean = clean.copy()
    clean["quintile"] = pd.qcut(clean["strategy_disp21_lag1"], 5, labels=False, duplicates="drop") + 1
    rows = []
    for q, grp in clean.groupby("quintile"):
        rows.append(
            {
                "quintile": int(q),
                "n": int(len(grp)),
                "strategy_disp21_mean": float(grp["strategy_disp21_lag1"].mean()),
                "target_mean": float(grp[target_col].mean()),
                "target_median": float(grp[target_col].median()),
            }
        )
    return rows


def plot_strategy_dispersion(features: pd.DataFrame) -> str:
    fig_path = FIG_DIR / "strategy_dispersion_timeseries.png"
    fig, ax = plt.subplots(figsize=(10, 4.8))
    cols = ["strategy_disp21_lag1", "strategy_disp63_lag1"]
    features[cols].dropna(how="all").plot(ax=ax, linewidth=1.0)
    ax.set_title("Lagged cross-strategy ETF return dispersion")
    ax.set_ylabel("Daily cross-sectional std. of strategy ETF returns")
    ax.set_xlabel("")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)
    return str(fig_path.relative_to(OUT_DIR))


def plot_dm(summary_rows: list[dict[str, object]]) -> str:
    fig_path = FIG_DIR / "oos_qlike_dm_tstats.png"
    rows = [r for r in summary_rows if r.get("status") == "ok"]
    labels = [str(r["target"]) for r in rows]
    vals = [float(r["qlike_dm_t"]) for r in rows]
    fig, ax = plt.subplots(figsize=(10, max(4.2, 0.55 * len(labels))))
    y = np.arange(len(labels))
    colors = ["#2f7d59" if v > 0 else "#b24b4b" for v in vals]
    ax.barh(y, vals, color=colors, alpha=0.82)
    ax.axvline(0.0, color="#222222", linewidth=0.8)
    ax.axvline(3.0, color="#555555", linewidth=0.8, linestyle="--")
    ax.axvline(-3.0, color="#555555", linewidth=0.8, linestyle="--")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("HAC/DM t-statistic, QLIKE loss: baseline minus strategy-dispersion augmented")
    ax.set_title("Out-of-sample forecast comparison")
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)
    return str(fig_path.relative_to(OUT_DIR))


def json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    sp500_table = get_sp500_constituents()
    sp500_tickers = sp500_table["yf_symbol"].tolist()
    iwm_top = get_yfinance_top_holdings("IWM")
    iwr_top = get_yfinance_top_holdings("IWR")

    strategy_prices = download_close(STRATEGY_ETFS, start="2009-01-01", chunk_size=20)
    market_prices = download_close(MARKET_TICKERS, start=START_DATE, chunk_size=20)
    sp500_prices = download_close(sp500_tickers, start=START_DATE, chunk_size=80)
    iwm_prices = download_close(iwm_top, start=START_DATE, chunk_size=20)
    iwr_prices = download_close(iwr_top, start=START_DATE, chunk_size=20)

    if len(strategy_prices.columns) < MIN_STRATEGY_ETFS:
        raise RuntimeError("Too few strategy ETFs downloaded")
    if "SPY" not in market_prices.columns or "^VIX" not in market_prices.columns:
        raise RuntimeError("Missing SPY or ^VIX market controls")
    if len(sp500_prices.columns) < MIN_SP500_NAMES:
        raise RuntimeError("Too few S&P 500 constituents downloaded")

    features = build_features(strategy_prices, market_prices)

    target_panels: dict[str, pd.DataFrame] = {}
    target_panels.update(
        build_universe_targets(
            sp500_prices,
            label="SP500_current_constituents",
            horizon=HORIZON,
            min_names=MIN_SP500_NAMES,
            include_cross_sectional_return_var=True,
        )
    )
    if len(iwm_prices.columns) >= MIN_TOP_HOLDING_NAMES:
        target_panels.update(
            build_universe_targets(
                iwm_prices,
                label="IWM_yfinance_top_holdings",
                horizon=HORIZON,
                min_names=MIN_TOP_HOLDING_NAMES,
                include_cross_sectional_return_var=False,
            )
        )
    if len(iwr_prices.columns) >= MIN_TOP_HOLDING_NAMES:
        target_panels.update(
            build_universe_targets(
                iwr_prices,
                label="IWR_yfinance_top_holdings",
                horizon=HORIZON,
                min_names=MIN_TOP_HOLDING_NAMES,
                include_cross_sectional_return_var=False,
            )
        )

    summary_rows: list[dict[str, object]] = []
    detailed: dict[str, object] = {}
    for target_name, panel in target_panels.items():
        target_col = f"{target_name}_target"
        data = panel.rename(columns={"target": target_col})
        data = pd.concat([data, features.reindex(data.index)], axis=1)
        base_cols = ["target_back_lag1"] + BASE_STATIC_COLS
        aug_cols = base_cols + STRATEGY_SIGNAL_COLS
        pred, meta = expanding_oos(data, target_col, base_cols, aug_cols, min_train=504)
        eval_result = evaluate_prediction(pred)
        coeffs = hac_coefficients(data, target_col, aug_cols)
        quints = quintile_diagnostic(data, target_col)
        detailed[target_name] = {
            "meta": meta,
            "eval": eval_result,
            "strategy_signal_hac_coefficients": coeffs,
            "quintile_diagnostic_full_sample_descriptive": quints,
            "base_columns": base_cols,
            "augmented_columns": aug_cols,
        }
        if eval_result.get("status") == "ok":
            qdm = eval_result["qlike_dm"]
            mdm = eval_result["mse_dm"]
            summary_rows.append(
                {
                    "target": target_name,
                    "status": "ok",
                    "oos_rows": meta["oos_rows"],
                    "first_oos_date": meta["first_oos_date"],
                    "last_oos_date": meta["last_oos_date"],
                    "qlike_base": eval_result["qlike_base"],
                    "qlike_aug": eval_result["qlike_aug"],
                    "qlike_improvement_pct": eval_result["qlike_improvement_pct"],
                    "qlike_dm_t": qdm["t"],
                    "qlike_dm_mean": qdm["mean"],
                    "mse_improvement_pct": eval_result["mse_improvement_pct"],
                    "mse_dm_t": mdm["t"],
                }
            )
        else:
            summary_rows.append(
                {
                    "target": target_name,
                    "status": eval_result.get("status", "skipped"),
                    "skip_meta": meta,
                }
            )

    ok_rows = [r for r in summary_rows if r.get("status") == "ok"]
    positive_harvey = [
        r
        for r in ok_rows
        if r.get("qlike_dm_t") is not None
        and float(r["qlike_dm_t"]) > 3.0
        and float(r["qlike_improvement_pct"]) > 0.0
    ]
    negative_harvey = [
        r
        for r in ok_rows
        if r.get("qlike_dm_t") is not None
        and float(r["qlike_dm_t"]) < -3.0
        and float(r["qlike_improvement_pct"]) < 0.0
    ]
    median_improvement = float(pd.Series([r["qlike_improvement_pct"] for r in ok_rows]).median())
    mean_improvement = float(pd.Series([r["qlike_improvement_pct"] for r in ok_rows]).mean())
    if positive_harvey and median_improvement > 0:
        verdict = "mixed_positive"
        conclusion = (
            "Strategy-ETF dispersion has at least one Harvey-significant OOS QLIKE win, "
            "but robustness depends on target coverage and proxy limitations."
        )
    else:
        verdict = "null_or_mixed_negative"
        conclusion = (
            "Strategy-ETF dispersion does not provide robust OOS QLIKE improvement for "
            "next-month stock cross-sectional dispersion or individual-RV targets after "
            "market-volatility and own-target persistence controls."
        )

    figures = {
        "strategy_dispersion_timeseries": plot_strategy_dispersion(features),
        "oos_qlike_dm_tstats": plot_dm(summary_rows),
    }

    result = {
        "experiment_id": EXPERIMENT_ID,
        "run_timestamp_local": datetime.now().astimezone().isoformat(),
        "data_sources": {
            "strategy_etfs": {
                "tickers_requested": STRATEGY_ETFS,
                "tickers_downloaded": strategy_prices.columns.tolist(),
                "first_date": strategy_prices.index.min().date().isoformat(),
                "last_date": strategy_prices.index.max().date().isoformat(),
            },
            "market_controls": {
                "tickers": MARKET_TICKERS,
                "first_date": market_prices.index.min().date().isoformat(),
                "last_date": market_prices.index.max().date().isoformat(),
            },
            "sp500_constituents": {
                "source": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                "constituents_requested": int(len(sp500_tickers)),
                "tickers_downloaded": int(len(sp500_prices.columns)),
                "first_date": sp500_prices.index.min().date().isoformat(),
                "last_date": sp500_prices.index.max().date().isoformat(),
                "survivorship_note": "Current S&P 500 constituents as of run date; not historical membership.",
            },
            "iwm_iwr_top_holdings": {
                "source": "yfinance funds_data.top_holdings",
                "IWM_top_holdings": iwm_top,
                "IWR_top_holdings": iwr_top,
                "IWM_downloaded": iwm_prices.columns.tolist(),
                "IWR_downloaded": iwr_prices.columns.tolist(),
                "limitation": "Only top holdings exposed by yfinance, not the full Russell 2000 or Russell Midcap membership.",
            },
        },
        "literature_checked": [
            {
                "title": "J.P. Morgan Alternative Investments Outlook 2026",
                "url": "https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/portfolio-insights/alternative-outlook.pdf",
                "role": "2026 practitioner motivation: elevated volatility and dispersion as hedge-fund alpha backdrop.",
            },
            {
                "title": "Wellington: Goldilocks and the three drivers of hedge fund outperformance",
                "url": "https://www.wellington.com/en-us/intermediary/insights/3-drivers-of-hedge-fund-outperformance",
                "role": "motivation linking dispersion, volatility, and hedge-fund opportunity set.",
            },
            {
                "title": "ECB Working Paper 1658: Commonality in hedge fund returns",
                "url": "https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1658.pdf",
                "role": "academic background for hedge-fund commonality/strategy-return structure.",
            },
        ],
        "design": {
            "strategy_dispersion_proxy": "Daily cross-sectional std. of strategy ETF log returns, smoothed as 21d and 63d rolling means; requires at least five ETFs available.",
            "feature_lag_rule": "All strategy and market controls are shifted by one trading day via raw.shift(1).",
            "target_alignment": "Target at date t is the forward 22-trading-day variance quantity; OOS training at forecast date t excludes rows whose target window ends after t-1.",
            "baseline_model": "log target OLS with own lagged target, SPY 22d return/RV, VIX level, and VIX 22d change.",
            "augmented_model": "baseline plus lagged 21d and 63d strategy-ETF dispersion.",
            "loss": "QLIKE(actual, predicted) = actual/predicted - log(actual/predicted) - 1; positive DM diff means augmented model has lower loss.",
            "formal_test": "HAC/DM test on baseline loss minus augmented loss; Harvey-style practical threshold |t| > 3.",
        },
        "summary": {
            "n_ok_cells": int(len(ok_rows)),
            "positive_harvey_cells": int(len(positive_harvey)),
            "negative_harvey_cells": int(len(negative_harvey)),
            "median_qlike_improvement_pct": median_improvement,
            "mean_qlike_improvement_pct": mean_improvement,
            "verdict": verdict,
            "conclusion": conclusion,
        },
        "summary_rows": summary_rows,
        "detailed_results": detailed,
        "figures": figures,
        "limitations": [
            "S&P 500 target uses current constituents from Wikipedia, so it has survivorship bias and is best treated as a public-proxy screening test.",
            "IWM/IWR individual-RV targets use yfinance top holdings only because full holdings CSV download was not reliably available in this session.",
            "Strategy ETF composition changes through time as DBMF/RPAR/CTA launch, so early signal values use fewer alternative-strategy ETFs.",
            "ETF proxies are not hedge-fund indices and include fee, replication, and retail ETF construction effects.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    (OUT_DIR / "results.json").write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    pd.DataFrame(summary_rows).to_csv(OUT_DIR / "summary_table.csv", index=False)
    print(json.dumps(json_safe(result["summary"]), indent=2))


if __name__ == "__main__":
    main()
