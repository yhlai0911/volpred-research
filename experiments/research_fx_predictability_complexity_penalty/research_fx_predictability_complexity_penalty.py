#!/usr/bin/env python3
"""FX predictability complexity penalty screen.

This experiment tests whether nonlinear Ridge-RFF forecasts improve over a
random-walk / historical-mean benchmark and a linear Ridge model for FX ETFs.
All predictors are dated t-1 or earlier and the OOS target is month t.
"""
from __future__ import annotations

import json
import math
import warnings
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


SEED = 42
EXPERIMENT_ID = "research_fx_predictability_complexity_penalty"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / EXPERIMENT_ID
FIG = OUT / "figures"
DATA = OUT / "data"
MACRO = ROOT / "storage" / "macro"

TICKERS = ["FXE", "FXY", "FXB", "FXA", "UUP", "CEW"]
START = "2006-01-01"
END = "2026-06-23"
TRAIN_WINDOWS = [12, 60, 120]
TARGETS = ["return", "rv", "left_tail"]
MODELS = ["linear_ridge", "rff_ridge"]
RFF_COMPONENTS = 64
RFF_ALPHA = 10.0
RIDGE_ALPHA = 10.0


@dataclass
class ForecastRecord:
    ticker: str
    target: str
    train_window_months: int
    model: str
    date: str
    y: float
    pred_model: float
    pred_benchmark: float
    pred_linear: float | None = None


def _ensure_dirs() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)


def _download_prices() -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = yf.download(
            TICKERS,
            start=START,
            end=END,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].rename(columns={"Close": TICKERS[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close.sort_index()
    close.to_csv(DATA / "daily_close.csv")
    return close


def _read_fred(series: str) -> pd.Series:
    path = MACRO / f"fred_{series}.csv"
    if not path.exists():
        return pd.Series(dtype=float, name=series)
    df = pd.read_csv(path, parse_dates=["date"])
    if series not in df.columns:
        return pd.Series(dtype=float, name=series)
    out = pd.to_numeric(df[series], errors="coerce")
    out.index = pd.to_datetime(df["date"])
    out.name = series
    return out.sort_index()


def _macro_monthly() -> pd.DataFrame:
    series = {
        "dgs10": _read_fred("DGS10"),
        "dgs2": _read_fred("DGS2"),
        "effr": _read_fred("EFFR"),
        "breakeven10y": _read_fred("T10YIE"),
    }
    daily = pd.concat(series.values(), axis=1)
    daily.columns = list(series)
    monthly = daily.resample("ME").last().ffill()
    monthly["term_spread"] = monthly["dgs10"] - monthly["dgs2"]
    for col in list(monthly.columns):
        monthly[f"{col}_chg1"] = monthly[col].diff()
    # Month t macro values are not assumed known at the month open. Shift all
    # macro predictors one month so forecast month t uses information through
    # month t-1.
    return monthly.shift(1)


def _make_monthly_panel(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    macro = _macro_monthly()
    monthly_close = close.resample("ME").last()
    daily_ret = np.log(close / close.shift(1))
    monthly_ret = np.log(monthly_close / monthly_close.shift(1))
    monthly_rv = daily_ret.pow(2).resample("ME").sum(min_count=10)
    uup_ret = monthly_ret.get("UUP", pd.Series(index=monthly_ret.index, dtype=float))
    uup_rv = monthly_rv.get("UUP", pd.Series(index=monthly_rv.index, dtype=float))

    panels: dict[str, pd.DataFrame] = {}
    for ticker in TICKERS:
        if ticker not in monthly_ret.columns:
            continue
        ret = monthly_ret[ticker]
        rv = monthly_rv[ticker]
        if ret.dropna().shape[0] < 72:
            continue
        tail_threshold = ret.shift(1).rolling(60, min_periods=12).quantile(0.20)
        panel = pd.DataFrame(index=ret.index)
        panel["y_return"] = ret
        panel["y_rv"] = rv
        panel["y_left_tail"] = (ret <= tail_threshold).astype(float)
        panel.loc[tail_threshold.isna(), "y_left_tail"] = np.nan

        panel["ret_lag1"] = ret.shift(1)
        panel["ret_lag3"] = ret.shift(1).rolling(3, min_periods=2).sum()
        panel["ret_lag6"] = ret.shift(1).rolling(6, min_periods=3).sum()
        panel["ret_lag12"] = ret.shift(1).rolling(12, min_periods=6).sum()
        panel["rv_lag1"] = rv.shift(1)
        panel["rv_mean3"] = rv.shift(1).rolling(3, min_periods=2).mean()
        panel["rv_mean12"] = rv.shift(1).rolling(12, min_periods=6).mean()
        panel["rv_chg1"] = rv.shift(1).diff()
        panel["uup_ret_lag1"] = uup_ret.shift(1)
        panel["uup_rv_lag1"] = uup_rv.shift(1)
        panel["is_uup_asset"] = 1.0 if ticker == "UUP" else 0.0
        panel = panel.join(macro, how="left")
        panels[ticker] = panel
        panel.to_csv(DATA / f"{ticker}_monthly_panel.csv")
    return panels


def _nw_tstat(x: np.ndarray, lags: int = 3) -> float | None:
    vals = np.asarray(x, dtype=float)
    vals = vals[np.isfinite(vals)]
    n = vals.size
    if n < 12:
        return None
    demeaned = vals - vals.mean()
    gamma0 = float(np.dot(demeaned, demeaned) / n)
    lrv = gamma0
    max_lag = min(lags, n - 1)
    for lag in range(1, max_lag + 1):
        cov = float(np.dot(demeaned[lag:], demeaned[:-lag]) / n)
        lrv += 2.0 * (1.0 - lag / (max_lag + 1.0)) * cov
    if lrv <= 0 or not math.isfinite(lrv):
        return None
    se = math.sqrt(lrv / n)
    if se <= 0:
        return None
    return float(vals.mean() / se)


def _rff_features(x: np.ndarray, *, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_features = x.shape[1]
    gamma = 1.0 / max(1, n_features)
    weights = rng.normal(0.0, math.sqrt(2.0 * gamma), size=(n_features, RFF_COMPONENTS))
    bias = rng.uniform(0.0, 2.0 * math.pi, size=RFF_COMPONENTS)
    return math.sqrt(2.0 / RFF_COMPONENTS) * np.cos(x @ weights + bias)


def _target_column(target: str) -> str:
    return {
        "return": "y_return",
        "rv": "y_rv",
        "left_tail": "y_left_tail",
    }[target]


def _fit_predict_oos(
    ticker: str,
    panel: pd.DataFrame,
    target: str,
    train_window: int,
) -> list[ForecastRecord]:
    y_col = _target_column(target)
    feature_cols = [c for c in panel.columns if not c.startswith("y_")]
    df = panel[feature_cols + [y_col]].replace([np.inf, -np.inf], np.nan).dropna()
    if df.shape[0] < train_window + 24:
        return []

    records: list[ForecastRecord] = []
    for pos in range(train_window, df.shape[0]):
        train = df.iloc[pos - train_window:pos]
        test = df.iloc[[pos]]
        x_train = train[feature_cols].to_numpy(dtype=float)
        y_train = train[y_col].to_numpy(dtype=float)
        x_test = test[feature_cols].to_numpy(dtype=float)
        y_true = float(test[y_col].iloc[0])

        if target == "return":
            pred_benchmark = 0.0
        elif target == "rv":
            pred_benchmark = max(float(np.mean(y_train)), 1e-10)
        else:
            pred_benchmark = float(np.clip(np.mean(y_train), 0.01, 0.99))

        scaler = StandardScaler()
        x_train_s = scaler.fit_transform(x_train)
        x_test_s = scaler.transform(x_test)

        ridge = Ridge(alpha=RIDGE_ALPHA, fit_intercept=True)
        ridge.fit(x_train_s, y_train)
        pred_linear = float(ridge.predict(x_test_s)[0])

        rff_key = f"{ticker}|{target}|{train_window}".encode("utf-8")
        rff_seed = SEED + zlib.crc32(rff_key) % 100_000
        x_train_rff = _rff_features(x_train_s, seed=rff_seed)
        x_test_rff = _rff_features(x_test_s, seed=rff_seed)
        rff = Ridge(alpha=RFF_ALPHA, fit_intercept=True)
        rff.fit(x_train_rff, y_train)
        pred_rff = float(rff.predict(x_test_rff)[0])

        if target == "rv":
            pred_linear = max(pred_linear, 1e-10)
            pred_rff = max(pred_rff, 1e-10)
        elif target == "left_tail":
            pred_linear = float(np.clip(pred_linear, 0.01, 0.99))
            pred_rff = float(np.clip(pred_rff, 0.01, 0.99))

        date = test.index[0].strftime("%Y-%m-%d")
        records.append(
            ForecastRecord(
                ticker=ticker,
                target=target,
                train_window_months=train_window,
                model="linear_ridge",
                date=date,
                y=y_true,
                pred_model=pred_linear,
                pred_benchmark=pred_benchmark,
            )
        )
        records.append(
            ForecastRecord(
                ticker=ticker,
                target=target,
                train_window_months=train_window,
                model="rff_ridge",
                date=date,
                y=y_true,
                pred_model=pred_rff,
                pred_benchmark=pred_benchmark,
                pred_linear=pred_linear,
            )
        )
    return records


def _records_to_frame(records: list[ForecastRecord]) -> pd.DataFrame:
    return pd.DataFrame([r.__dict__ for r in records])


def _summarize_forecasts(forecasts: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for keys, group in forecasts.groupby(["ticker", "target", "train_window_months", "model"]):
        ticker, target, window, model = keys
        y = group["y"].to_numpy(float)
        p = group["pred_model"].to_numpy(float)
        b = group["pred_benchmark"].to_numpy(float)
        loss_b = (y - b) ** 2
        loss_m = (y - p) ** 2
        loss_diff = loss_b - loss_m
        improvement = 100.0 * (np.mean(loss_b) - np.mean(loss_m)) / np.mean(loss_b)
        dm_t = _nw_tstat(loss_diff)

        cw_t = None
        if target == "return":
            cw_diff = loss_b - (loss_m - (b - p) ** 2)
            cw_t = _nw_tstat(cw_diff)

        rff_vs_linear_t = None
        rff_vs_linear_improvement = None
        if model == "rff_ridge":
            p_lin = group["pred_linear"].to_numpy(float)
            loss_lin = (y - p_lin) ** 2
            rff_vs_linear = loss_lin - loss_m
            rff_vs_linear_t = _nw_tstat(rff_vs_linear)
            rff_vs_linear_improvement = (
                100.0 * (np.mean(loss_lin) - np.mean(loss_m)) / np.mean(loss_lin)
            )

        sharpe = None
        sharpe_diff_vs_buyhold = None
        sharpe_boot_ci = None
        if target == "return":
            strategy = np.sign(p) * y
            buyhold = y
            sharpe = _annualized_sharpe(strategy)
            sharpe_diff_vs_buyhold = (
                sharpe - _annualized_sharpe(buyhold)
                if _annualized_sharpe(buyhold) is not None
                else None
            )
            sharpe_boot_ci = _bootstrap_sharpe_diff(strategy, buyhold)

        rows.append({
            "ticker": ticker,
            "target": target,
            "train_window_months": int(window),
            "model": model,
            "n_oos_months": int(group.shape[0]),
            "sample_start": str(group["date"].iloc[0]),
            "sample_end": str(group["date"].iloc[-1]),
            "benchmark_mspe": float(np.mean(loss_b)),
            "model_mspe": float(np.mean(loss_m)),
            "mspe_improvement_pct": float(improvement),
            "dm_t_model_vs_benchmark": dm_t,
            "clark_west_t_return": cw_t,
            "rff_vs_linear_mspe_improvement_pct": (
                None if rff_vs_linear_improvement is None else float(rff_vs_linear_improvement)
            ),
            "rff_vs_linear_dm_t": rff_vs_linear_t,
            "strategy_sharpe_monthly_annualized": sharpe,
            "strategy_sharpe_diff_vs_buyhold": sharpe_diff_vs_buyhold,
            "strategy_sharpe_diff_bootstrap_ci_95": sharpe_boot_ci,
        })

    summary = {
        "total_tests": len(rows),
        "harvey_pass_model_vs_benchmark": int(
            sum(
                1 for r in rows
                if r["dm_t_model_vs_benchmark"] is not None
                and r["dm_t_model_vs_benchmark"] >= 3.0
            )
        ),
        "harvey_pass_clark_west_return": int(
            sum(
                1 for r in rows
                if r["clark_west_t_return"] is not None
                and r["clark_west_t_return"] >= 3.0
            )
        ),
        "rff_beats_linear_harvey": int(
            sum(
                1 for r in rows
                if r["rff_vs_linear_dm_t"] is not None and r["rff_vs_linear_dm_t"] >= 3.0
            )
        ),
        "median_mspe_improvement_pct_by_model_target_window": _aggregate_table(rows),
    }
    return rows, summary


def _annualized_sharpe(x: np.ndarray) -> float | None:
    vals = np.asarray(x, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size < 24:
        return None
    sd = vals.std(ddof=1)
    if sd <= 0:
        return None
    return float(vals.mean() / sd * math.sqrt(12.0))


def _bootstrap_sharpe_diff(strategy: np.ndarray, benchmark: np.ndarray) -> dict[str, float] | None:
    strategy = np.asarray(strategy, dtype=float)
    benchmark = np.asarray(benchmark, dtype=float)
    mask = np.isfinite(strategy) & np.isfinite(benchmark)
    strategy = strategy[mask]
    benchmark = benchmark[mask]
    n = strategy.size
    if n < 36:
        return None
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(1000):
        idx = rng.integers(0, n, size=n)
        s = _annualized_sharpe(strategy[idx])
        b = _annualized_sharpe(benchmark[idx])
        if s is not None and b is not None:
            diffs.append(s - b)
    if not diffs:
        return None
    arr = np.array(diffs)
    return {
        "low": float(np.quantile(arr, 0.025)),
        "median": float(np.quantile(arr, 0.50)),
        "high": float(np.quantile(arr, 0.975)),
        "p_gt_0": float(np.mean(arr > 0)),
    }


def _aggregate_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    df = pd.DataFrame(rows)
    out = []
    for keys, g in df.groupby(["model", "target", "train_window_months"]):
        model, target, window = keys
        out.append({
            "model": model,
            "target": target,
            "train_window_months": int(window),
            "median_mspe_improvement_pct": float(g["mspe_improvement_pct"].median()),
            "mean_mspe_improvement_pct": float(g["mspe_improvement_pct"].mean()),
            "positive_count": int((g["mspe_improvement_pct"] > 0).sum()),
            "test_count": int(g.shape[0]),
        })
    return out


def _plot_summary(rows: list[dict[str, Any]]) -> None:
    df = pd.DataFrame(rows)
    agg = (
        df.groupby(["model", "target", "train_window_months"])["mspe_improvement_pct"]
        .median()
        .reset_index()
    )
    for model in MODELS:
        sub = agg[agg["model"] == model]
        pivot = sub.pivot(index="target", columns="train_window_months", values="mspe_improvement_pct")
        fig, ax = plt.subplots(figsize=(7, 3.8))
        im = ax.imshow(pivot.to_numpy(), cmap="RdYlGn", vmin=-10, vmax=10)
        ax.set_xticks(range(len(pivot.columns)), [str(c) for c in pivot.columns])
        ax.set_yticks(range(len(pivot.index)), pivot.index)
        ax.set_title(f"Median MSPE improvement vs benchmark: {model}")
        for i in range(pivot.shape[0]):
            for j in range(pivot.shape[1]):
                val = pivot.iloc[i, j]
                ax.text(j, i, f"{val:.1f}%", ha="center", va="center", fontsize=9)
        ax.set_xlabel("training window (months)")
        fig.colorbar(im, ax=ax, label="MSPE improvement (%)")
        fig.tight_layout()
        fig.savefig(FIG / f"{model}_median_mspe_improvement.png", dpi=150)
        plt.close(fig)

    rff = df[df["model"] == "rff_ridge"].copy()
    rff = rff.dropna(subset=["rff_vs_linear_mspe_improvement_pct"])
    if not rff.empty:
        agg2 = (
            rff.groupby(["target", "train_window_months"])["rff_vs_linear_mspe_improvement_pct"]
            .median()
            .reset_index()
        )
        pivot = agg2.pivot(index="target", columns="train_window_months", values="rff_vs_linear_mspe_improvement_pct")
        fig, ax = plt.subplots(figsize=(7, 3.8))
        im = ax.imshow(pivot.to_numpy(), cmap="RdYlGn", vmin=-5, vmax=5)
        ax.set_xticks(range(len(pivot.columns)), [str(c) for c in pivot.columns])
        ax.set_yticks(range(len(pivot.index)), pivot.index)
        ax.set_title("Median Ridge-RFF improvement vs linear Ridge")
        for i in range(pivot.shape[0]):
            for j in range(pivot.shape[1]):
                val = pivot.iloc[i, j]
                ax.text(j, i, f"{val:.1f}%", ha="center", va="center", fontsize=9)
        ax.set_xlabel("training window (months)")
        fig.colorbar(im, ax=ax, label="RFF vs linear MSPE improvement (%)")
        fig.tight_layout()
        fig.savefig(FIG / "rff_vs_linear_median_improvement.png", dpi=150)
        plt.close(fig)


def _overall_verdict(summary: dict[str, Any]) -> str:
    if summary["harvey_pass_clark_west_return"] == 0:
        if summary["harvey_pass_model_vs_benchmark"] > 0:
            return "PARTIAL_RV_ONLY_NO_RETURN_PREDICTABILITY"
        return "NULL_COMPLEXITY_PREMIUM"
    if summary["rff_beats_linear_harvey"] > 0:
        return "MIXED_RETURN_PASS_NEEDS_MULTIPLE_TESTING_CAUTION"
    return "LINEAR_OR_BENCHMARK_DOMINANT"


def main() -> int:
    _ensure_dirs()
    close = _download_prices()
    panels = _make_monthly_panel(close)

    records: list[ForecastRecord] = []
    for ticker, panel in panels.items():
        for target in TARGETS:
            for window in TRAIN_WINDOWS:
                records.extend(_fit_predict_oos(ticker, panel, target, window))

    if not records:
        raise RuntimeError("no OOS forecasts produced")

    forecasts = _records_to_frame(records)
    forecasts.to_csv(OUT / "forecast_records.csv", index=False)
    rows, summary = _summarize_forecasts(forecasts)
    _plot_summary(rows)

    result = {
        "experiment_id": EXPERIMENT_ID,
        "title": "FX predictability complexity penalty",
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "data_sources": {
            "prices": "Yahoo Finance via yfinance, auto_adjust=True",
            "tickers": TICKERS,
            "macro": [
                "storage/macro/fred_DGS10.csv",
                "storage/macro/fred_DGS2.csv",
                "storage/macro/fred_EFFR.csv",
                "storage/macro/fred_T10YIE.csv",
            ],
            "price_period": f"{START} to {END}",
        },
        "method": {
            "frequency": "monthly",
            "targets": {
                "return": "month-t log return",
                "rv": "sum of daily squared log returns in month t",
                "left_tail": "month-t return below trailing 60-month 20th percentile known at t-1",
            },
            "benchmarks": {
                "return": "random-walk zero return forecast",
                "rv": "training-window historical mean RV",
                "left_tail": "training-window historical event probability",
            },
            "models": {
                "linear_ridge": {"alpha": RIDGE_ALPHA},
                "rff_ridge": {"alpha": RFF_ALPHA, "components": RFF_COMPONENTS},
            },
            "lookahead_control": "All features, macro values, and thresholds are shifted at least one month; code uses shift(1) for predictors.",
            "training_windows_months": TRAIN_WINDOWS,
            "tests": [
                "Newey-West t-stat of benchmark loss minus model loss",
                "Clark-West adjusted t-stat for return forecasts",
                "Bootstrap Sharpe difference for sign strategy vs buy-hold, seed=42",
            ],
            "publication_gate": "Harvey-style |t| >= 3; positive model claims require t >= 3 after sign orientation.",
        },
        "summary": summary,
        "verdict": _overall_verdict(summary),
        "per_test_results": rows,
        "limitations": [
            "ETF monthly proxy, not spot FX with real-time macro vintages.",
            "Ridge-RFF hyperparameters are fixed ex ante; no nested tuning loop.",
            "Local macro predictors are end-of-month FRED levels shifted one month; this is not a real-time vintage macro forecast design.",
            "This is a free-data screen of the complexity-penalty hypothesis, not a replication of Kiliç (2025).",
        ],
        "figures": [
            "figures/linear_ridge_median_mspe_improvement.png",
            "figures/rff_ridge_median_mspe_improvement.png",
            "figures/rff_vs_linear_median_improvement.png",
        ],
    }
    (OUT / f"{EXPERIMENT_ID}_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "experiment_id": EXPERIMENT_ID,
        "verdict": result["verdict"],
        "records": int(forecasts.shape[0]),
        "tests": len(rows),
        "harvey_pass_model_vs_benchmark": summary["harvey_pass_model_vs_benchmark"],
        "harvey_pass_clark_west_return": summary["harvey_pass_clark_west_return"],
        "rff_beats_linear_harvey": summary["rff_beats_linear_harvey"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
