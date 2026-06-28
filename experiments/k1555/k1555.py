#!/usr/bin/env python3
"""K1555: tariff uncertainty -> FX/USD -> EM/commodity risk proxy.

Convention:
    raw_event_* is stamped on a public tariff-policy event's trading date.
    Applied signals use raw_event_*.shift(1), so outcomes start after the
    information is public.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1555"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRICE_START = "2024-01-01"
PRICE_END = "2026-06-28"
TICKERS = ["UUP", "DX-Y.NYB", "FXY", "FXE", "CEW", "EMLC", "EEM", "DBC", "GLD"]
HORIZONS = [1, 5, 22]
TARGET_COLUMNS = [
    "fx_rv_1d_z",
    "fx_rv_5d_z",
    "fx_rv_22d_z",
    "usd_drawdown_1d_z",
    "usd_drawdown_5d_z",
    "usd_drawdown_22d_z",
    "em_left_tail_5d_z",
    "em_left_tail_22d_z",
    "commodity_rv_5d_z",
    "commodity_rv_22d_z",
]

EVENTS = [
    {
        "date": "2025-02-13",
        "label": "Reciprocal tariff memorandum directs review",
        "signed_intensity": 1.0,
        "abs_intensity": 1.0,
        "source": "White House reciprocal tariff memorandum cited by Apr 2 order",
    },
    {
        "date": "2025-04-02",
        "label": "Liberation Day reciprocal tariff executive order",
        "signed_intensity": 3.0,
        "abs_intensity": 3.0,
        "source": "White House Executive Order 14257",
    },
    {
        "date": "2025-04-09",
        "label": "Ninety-day pause excluding China; China tariff raised",
        "signed_intensity": 2.0,
        "abs_intensity": 2.0,
        "source": "CFR trade calendar / USTR presidential tariff actions",
    },
    {
        "date": "2025-05-12",
        "label": "US-China 90-day tariff reduction",
        "signed_intensity": -2.0,
        "abs_intensity": 2.0,
        "source": "USTR Executive Order 14298 / public trade-calendar sources",
    },
    {
        "date": "2025-07-07",
        "label": "Extension of reciprocal tariff-rate modification",
        "signed_intensity": 1.0,
        "abs_intensity": 1.0,
        "source": "USTR presidential tariff actions",
    },
    {
        "date": "2025-07-31",
        "label": "Further modification of reciprocal tariff rates",
        "signed_intensity": 2.0,
        "abs_intensity": 2.0,
        "source": "White House / USTR presidential tariff actions",
    },
    {
        "date": "2025-08-11",
        "label": "Further China-rate modification during ongoing discussions",
        "signed_intensity": -1.0,
        "abs_intensity": 1.0,
        "source": "White House / USTR presidential tariff actions",
    },
    {
        "date": "2025-09-05",
        "label": "Scope/procedure changes for trade and security agreements",
        "signed_intensity": -1.0,
        "abs_intensity": 1.0,
        "source": "USTR presidential tariff actions",
    },
    {
        "date": "2026-02-23",
        "label": "Temporary global tariff threat after legal ruling",
        "signed_intensity": 3.0,
        "abs_intensity": 3.0,
        "source": "The Guardian live market report, 2026-02-23",
    },
]


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if not math.isfinite(v) else v
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat()
    return obj


def download_prices() -> pd.DataFrame:
    path = DATA_DIR / "prices.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["date"])

    raw = yf.download(TICKERS, start=PRICE_START, end=PRICE_END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("yfinance returned empty data")
    rows: list[pd.DataFrame] = []
    for ticker in TICKERS:
        if isinstance(raw.columns, pd.MultiIndex):
            sub = raw.xs(ticker, axis=1, level=-1)
        else:
            sub = raw.copy()
        keep = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"]).copy()
        keep.columns = ["open", "high", "low", "close", "volume"]
        keep["ticker"] = ticker
        keep["date"] = keep.index
        rows.append(keep.reset_index(drop=True))
    prices = pd.concat(rows, ignore_index=True)
    prices = prices[["ticker", "date", "open", "high", "low", "close", "volume"]]
    prices.to_csv(path, index=False)
    return prices


def close_panel(prices: pd.DataFrame) -> pd.DataFrame:
    close = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    close = close.ffill()
    return close


def forward_sum(s: pd.Series, horizon: int) -> pd.Series:
    out = pd.Series(0.0, index=s.index)
    for lag in range(horizon):
        out = out + s.shift(-lag)
    return out


def trailing_sum(s: pd.Series, horizon: int) -> pd.Series:
    out = pd.Series(0.0, index=s.index)
    for lag in range(1, horizon + 1):
        out = out + s.shift(lag)
    return out


def forward_rv(rets: pd.DataFrame, horizon: int) -> pd.Series:
    rv = pd.Series(0.0, index=rets.index)
    for col in rets.columns:
        s = pd.Series(0.0, index=rets.index)
        for lag in range(horizon):
            s = s + rets[col].shift(-lag).pow(2)
        rv = rv + np.sqrt(s * 252.0 / horizon)
    return rv / len(rets.columns)


def trailing_rv(rets: pd.DataFrame, horizon: int) -> pd.Series:
    rv = pd.Series(0.0, index=rets.index)
    for col in rets.columns:
        s = pd.Series(0.0, index=rets.index)
        for lag in range(1, horizon + 1):
            s = s + rets[col].shift(lag).pow(2)
        rv = rv + np.sqrt(s * 252.0 / horizon)
    return rv / len(rets.columns)


def abnormal_z(forward_metric: pd.Series, trailing_metric: pd.Series) -> pd.Series:
    mu = trailing_metric.rolling(252, min_periods=63).mean().shift(1)
    sigma = trailing_metric.rolling(252, min_periods=63).std(ddof=1).shift(1)
    return (forward_metric - mu) / sigma.replace(0, np.nan)


def map_events_to_trading_days(index: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    event_rows = []
    raw = pd.DataFrame(index=index)
    raw["raw_event_abs"] = 0.0
    raw["raw_event_signed"] = 0.0
    for event in EVENTS:
        event_date = pd.Timestamp(event["date"])
        pos = index.searchsorted(event_date)
        if pos >= len(index):
            mapped = pd.NaT
        else:
            mapped = index[pos]
            raw.loc[mapped, "raw_event_abs"] += float(event["abs_intensity"])
            raw.loc[mapped, "raw_event_signed"] += float(event["signed_intensity"])
        event_rows.append({**event, "mapped_trading_date": mapped})
    events_df = pd.DataFrame(event_rows)
    events_df.to_csv(DATA_DIR / "tariff_events.csv", index=False)
    return raw, events_df


def build_targets(close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = close.pct_change()
    fx_cols = [c for c in ["FXY", "FXE", "CEW", "EMLC"] if c in returns]
    em_cols = [c for c in ["CEW", "EMLC", "EEM"] if c in returns]
    commodity_cols = [c for c in ["DBC", "GLD"] if c in returns]
    uup = returns["UUP"]

    raw_events, events_df = map_events_to_trading_days(close.index)
    daily = raw_events.copy()
    # Required no-lookahead guard: event known at t, applied from t+1 onward.
    daily["event_abs_signal"] = daily["raw_event_abs"].shift(1).fillna(0.0)
    daily["event_signed_signal"] = daily["raw_event_signed"].shift(1).fillna(0.0)

    for h in HORIZONS:
        fx_fwd = forward_rv(returns[fx_cols], h)
        fx_trail = trailing_rv(returns[fx_cols], h)
        daily[f"fx_rv_{h}d"] = fx_fwd
        daily[f"fx_rv_{h}d_z"] = abnormal_z(fx_fwd, fx_trail)

        usd_fwd = -forward_sum(uup, h)
        usd_trail = -trailing_sum(uup, h)
        daily[f"usd_drawdown_{h}d"] = usd_fwd
        daily[f"usd_drawdown_{h}d_z"] = abnormal_z(usd_fwd, usd_trail)

        em_ret = returns[em_cols].mean(axis=1)
        em_fwd = -forward_sum(em_ret, h)
        em_trail = -trailing_sum(em_ret, h)
        daily[f"em_left_tail_{h}d"] = em_fwd
        daily[f"em_left_tail_{h}d_z"] = abnormal_z(em_fwd, em_trail)

        comm_fwd = forward_rv(returns[commodity_cols], h)
        comm_trail = trailing_rv(returns[commodity_cols], h)
        daily[f"commodity_rv_{h}d"] = comm_fwd
        daily[f"commodity_rv_{h}d_z"] = abnormal_z(comm_fwd, comm_trail)

    event_window = pd.Series(False, index=daily.index)
    for mapped in events_df["mapped_trading_date"].dropna():
        loc = daily.index.get_loc(pd.Timestamp(mapped))
        start = min(loc + 1, len(daily.index) - 1)
        end = min(loc + 22, len(daily.index) - 1)
        event_window.iloc[start : end + 1] = True
    daily["post_event_window"] = event_window
    daily = daily.reset_index(names="date")
    daily.to_csv(DATA_DIR / "daily_targets.csv", index=False)
    return daily, events_df


def welch(event: pd.Series, control: pd.Series) -> dict[str, Any]:
    e = event.dropna().astype(float)
    c = control.dropna().astype(float)
    if len(e) < 2 or len(c) < 2:
        return {"event_n": int(len(e)), "control_n": int(len(c)), "diff": None, "t_stat": None, "p_value": None}
    test = stats.ttest_ind(e, c, equal_var=False, nan_policy="omit")
    return {
        "event_n": int(len(e)),
        "control_n": int(len(c)),
        "event_mean": float(e.mean()),
        "control_mean": float(c.mean()),
        "diff": float(e.mean() - c.mean()),
        "t_stat": float(test.statistic),
        "p_value": float(test.pvalue),
    }


def bootstrap_event_mean(values: np.ndarray, reps: int = 1000) -> dict[str, Any]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return {"n": int(len(values)), "mean": float(values.mean()) if len(values) else None, "ci95": [None, None]}
    rng = np.random.default_rng(SEED)
    draws = [float(np.mean(rng.choice(values, size=len(values), replace=True))) for _ in range(reps)]
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return {"n": int(len(values)), "mean": float(values.mean()), "ci95": [float(lo), float(hi)]}


def analyze(daily: pd.DataFrame) -> dict[str, Any]:
    event_rows = daily[daily["event_abs_signal"] > 0].copy()
    controls = daily[(daily["event_abs_signal"] == 0) & (~daily["post_event_window"])].copy()
    tests = {}
    for target in TARGET_COLUMNS:
        tests[target] = welch(event_rows[target], controls[target])
        tests[target]["event_bootstrap"] = bootstrap_event_mean(event_rows[target].dropna().to_numpy())

    coherent_direction = {
        "fx_1d_positive": (tests["fx_rv_1d_z"].get("diff") or 0.0) > 0,
        "usd_drawdown_5d_positive": (tests["usd_drawdown_5d_z"].get("diff") or 0.0) > 0,
        "em_left_tail_5d_positive": (tests["em_left_tail_5d_z"].get("diff") or 0.0) > 0,
        "commodity_rv_5d_positive": (tests["commodity_rv_5d_z"].get("diff") or 0.0) > 0,
    }
    t_ge_3 = [
        k
        for k, v in tests.items()
        if v.get("t_stat") is not None and np.isfinite(v["t_stat"]) and v["t_stat"] >= 3.0
    ]
    ci_positive = [
        k
        for k, v in tests.items()
        if v["event_bootstrap"]["ci95"][0] is not None and v["event_bootstrap"]["ci95"][0] > 0
    ]
    event_n = int(event_rows.shape[0])
    if event_n < 7:
        label = "UNDERPOWERED"
        conclusion = "Too few tariff event rows survive the lagged-event alignment for serious inference."
    elif sum(coherent_direction.values()) >= 3 and (len(t_ge_3) >= 2 or len(ci_positive) >= 2):
        label = "PASS"
        conclusion = "Tariff events show a coherent public-proxy FX/USD/EM risk-premium wedge pattern."
    elif sum(coherent_direction.values()) >= 3:
        label = "CONDITIONAL_PASS"
        conclusion = "Direction is broadly coherent, but evidence is event-count limited and does not clear strict statistical gates."
    else:
        label = "NULL"
        conclusion = "The public ETF/FX event study does not show a coherent tariff-uncertainty FX-to-EM spillover pattern."

    return {
        "verdict": {
            "label": label,
            "conclusion": conclusion,
            "event_rows": event_n,
            "coherent_direction_flags": coherent_direction,
            "t_ge_3_targets": t_ge_3,
            "positive_bootstrap_ci_targets": ci_positive,
        },
        "target_tests": tests,
        "event_rows": event_rows[["date", "event_abs_signal", "event_signed_signal"] + TARGET_COLUMNS].to_dict(orient="records"),
    }


def plot_effects(results: dict[str, Any]) -> None:
    labels = TARGET_COLUMNS
    values = [results["target_tests"][c].get("diff") or 0.0 for c in labels]
    colors = ["#2f6f73" if v >= 0 else "#b64f4a" for v in values]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.bar(labels, values, color=colors)
    ax.set_title("K1555 tariff event-minus-control abnormal z effects")
    ax.set_ylabel("Event minus control z-score")
    ax.tick_params(axis="x", rotation=40)
    fig.tight_layout()
    fig.savefig(ROOT / "k1555_event_effects.png", dpi=160)
    plt.close(fig)


def main() -> None:
    prices = download_prices()
    close = close_panel(prices)
    daily, events_df = build_targets(close)
    results = analyze(daily)
    plot_effects(results)
    out = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data": {
            "price_source": "yfinance adjusted OHLCV",
            "tickers": TICKERS,
            "requested_price_start": PRICE_START,
            "requested_price_end": PRICE_END,
            "price_rows": int(len(prices)),
            "daily_rows": int(len(daily)),
            "event_calendar_rows": int(len(events_df)),
            "blocked_sources": [
                "GDELT DOC timeline headline-intensity was not used because project experience and current probes hit HTTP 429 rate limits.",
                "No proprietary tariff-volatility state variable, dealer flow, forward points, or investor-level FX risk premium data are observed.",
            ],
        },
        "methods": {
            "event_alignment": "calendar event mapped to next trading day; raw_event signal then shifted one trading day before outcomes",
            "lookahead_guard": "event_abs_signal = raw_event_abs.shift(1); abnormal baselines use trailing realized windows only",
            "targets": TARGET_COLUMNS,
            "tests": "Welch event-vs-control diagnostics and seed-42 event-date bootstrap",
        },
        "events": events_df.to_dict(orient="records"),
        **results,
        "limitations": [
            "Event calendar is hand-curated from public tariff-policy pages, not a continuous tariff-uncertainty index.",
            "The event count is small and 5/22-day targets overlap.",
            "ETF proxies mix local equity, commodity, duration, and USD-liquidity effects.",
            "CEW/EMLC/EEM are imperfect EM FX/risk-premium proxies.",
            "A null public ETF proxy result would not refute the AEA/NBER model mechanism.",
        ],
    }
    (ROOT / "k1555_results.json").write_text(json.dumps(_json_safe(out), indent=2), encoding="utf-8")
    print(json.dumps({"verdict": out["verdict"], "data": out["data"]}, indent=2))


if __name__ == "__main__":
    main()
