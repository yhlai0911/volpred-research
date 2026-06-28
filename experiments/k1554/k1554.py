#!/usr/bin/env python3
"""K1554: public social-transmission proxy feasibility test.

Convention:
    raw_signal[t] is formed with Stocktwits messages and trailing price data
    through day t. The market outcome test uses signal = raw_signal.shift(1),
    so the signal from t is applied to the first trading day after t.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1554"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRICE_START = "2024-01-01"
PRICE_END = "2026-06-28"
STOCKTWITS_MAX_PAGES = int(os.environ.get("K1554_STOCKTWITS_MAX_PAGES", "15"))
STOCKTWITS_PAGE_SLEEP = float(os.environ.get("K1554_STOCKTWITS_SLEEP", "0.05"))
FORCE_REFRESH = os.environ.get("K1554_FORCE_REFRESH", "0") == "1"

UNIVERSE: dict[str, str] = {
    "GME": "GameStop",
    "AMC": "AMC Entertainment",
    "KOSS": "Koss",
    "KSS": "Kohl's",
    "OPEN": "Opendoor Technologies",
    "UPST": "Upstart Holdings",
    "SOFI": "SoFi Technologies",
    "PLTR": "Palantir Technologies",
    "RIVN": "Rivian Automotive",
    "LCID": "Lucid Group",
    "HOOD": "Robinhood Markets",
    "COIN": "Coinbase Global",
    "MSTR": "MicroStrategy",
    "MARA": "Marathon Digital",
    "RIOT": "Riot Platforms",
    "CVNA": "Carvana",
    "DJT": "Trump Media & Technology",
    "RDDT": "Reddit",
}

TARGETS = [
    "abn_log_volume_1d",
    "abn_log_volume_5d",
    "range_vol_1d",
    "range_vol_5d",
    "abs_gap_1d",
    "reversal_5d",
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
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return obj


def fetch_stocktwits_messages(symbol: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
    session = requests.Session()
    headers = {"User-Agent": "volpred-research/1.0", "Accept": "application/json"}
    max_id = None
    rows: list[dict[str, Any]] = []
    status_codes: list[int] = []
    error: str | None = None
    for _page in range(STOCKTWITS_MAX_PAGES):
        params = {}
        if max_id is not None:
            params["max"] = max_id
        try:
            resp = session.get(url, params=params, headers=headers, timeout=20)
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}: {exc}"
            break
        status_codes.append(resp.status_code)
        if resp.status_code != 200:
            error = resp.text[:300]
            break
        payload = resp.json()
        messages = payload.get("messages", [])
        if not messages:
            break
        for msg in messages:
            sentiment = msg.get("entities", {}).get("sentiment")
            user = msg.get("user", {}) or {}
            rows.append(
                {
                    "ticker": symbol,
                    "message_id": msg.get("id"),
                    "created_at": msg.get("created_at"),
                    "sentiment": sentiment.get("basic") if isinstance(sentiment, dict) else None,
                    "user_id": user.get("id"),
                    "user_followers": user.get("followers"),
                }
            )
        cursor = payload.get("cursor", {}) or {}
        next_max = cursor.get("max")
        if not cursor.get("more") or next_max is None or next_max == max_id:
            break
        max_id = next_max
        time.sleep(STOCKTWITS_PAGE_SLEEP)

    created = [r["created_at"] for r in rows if r.get("created_at")]
    diag = {
        "ticker": symbol,
        "messages": len(rows),
        "status_codes": status_codes,
        "oldest_created_at": min(created) if created else None,
        "newest_created_at": max(created) if created else None,
        "error": error,
    }
    return rows, diag


def load_stocktwits_messages() -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    path = DATA_DIR / "stocktwits_messages.csv"
    diag_path = DATA_DIR / "stocktwits_fetch_diagnostics.json"
    if path.exists() and diag_path.exists() and not FORCE_REFRESH:
        cached = pd.read_csv(path)
        if "body" in cached.columns:
            cached = cached.drop(columns=["body"])
            cached.to_csv(path, index=False)
        return cached, json.loads(diag_path.read_text())

    all_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for symbol in UNIVERSE:
        rows, diag = fetch_stocktwits_messages(symbol)
        all_rows.extend(rows)
        diagnostics.append(diag)
    df = pd.DataFrame(all_rows)
    df.to_csv(path, index=False)
    diag_path.write_text(json.dumps(_json_safe(diagnostics), indent=2), encoding="utf-8")
    return df, diagnostics


def stocktwits_daily_counts(messages: pd.DataFrame) -> pd.DataFrame:
    if messages.empty:
        out = pd.DataFrame(columns=["ticker", "date", "stocktwits_messages", "bullish_messages", "bearish_messages"])
        out.to_csv(DATA_DIR / "stocktwits_daily_counts.csv", index=False)
        return out
    df = messages.copy()
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["created_at"])
    df["date"] = df["created_at"].dt.tz_convert(None).dt.date
    grouped = (
        df.groupby(["ticker", "date"])
        .agg(
            stocktwits_messages=("message_id", "count"),
            bullish_messages=("sentiment", lambda x: int((x == "Bullish").sum())),
            bearish_messages=("sentiment", lambda x: int((x == "Bearish").sum())),
        )
        .reset_index()
    )
    grouped["date"] = pd.to_datetime(grouped["date"])
    grouped.to_csv(DATA_DIR / "stocktwits_daily_counts.csv", index=False)
    return grouped


def download_prices() -> pd.DataFrame:
    path = DATA_DIR / "prices.csv"
    if path.exists() and not FORCE_REFRESH:
        df = pd.read_csv(path, parse_dates=["date"])
        return df

    raw = yf.download(
        list(UNIVERSE),
        start=PRICE_START,
        end=PRICE_END,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty data")
    rows: list[pd.DataFrame] = []
    for ticker in UNIVERSE:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                sub = raw.xs(ticker, axis=1, level=-1)
            else:
                sub = raw.copy()
            keep = sub[["Open", "High", "Low", "Close", "Volume"]].copy()
        except Exception:
            continue
        keep = keep.dropna(subset=["Open", "High", "Low", "Close"])
        keep.columns = ["open", "high", "low", "close", "volume"]
        keep["ticker"] = ticker
        keep["date"] = keep.index
        rows.append(keep.reset_index(drop=True))
    prices = pd.concat(rows, ignore_index=True)
    prices = prices[["ticker", "date", "open", "high", "low", "close", "volume"]]
    prices.to_csv(path, index=False)
    return prices


def forward_sum(s: pd.Series, horizon: int) -> pd.Series:
    out = pd.Series(0.0, index=s.index)
    for lag in range(horizon):
        out = out + s.shift(-lag)
    return out


def prepare_panel(prices: pd.DataFrame, daily_counts: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    counts = daily_counts.copy()
    if counts.empty:
        counts = pd.DataFrame(columns=["ticker", "date", "stocktwits_messages", "bullish_messages", "bearish_messages"])
    counts["date"] = pd.to_datetime(counts["date"])

    for ticker, px in prices.groupby("ticker"):
        px = px.sort_values("date").copy()
        px["date"] = pd.to_datetime(px["date"])
        c = counts[counts["ticker"] == ticker][["date", "stocktwits_messages", "bullish_messages", "bearish_messages"]]
        g = px.merge(c, on="date", how="left")
        for col in ["stocktwits_messages", "bullish_messages", "bearish_messages"]:
            g[col] = g[col].fillna(0.0)

        close = g["close"]
        ret = close.pct_change()
        log_volume = np.log(g["volume"].replace(0, np.nan))
        range_vol = np.log(g["high"] / g["low"]).replace([np.inf, -np.inf], np.nan)
        gap = g["open"] / g["close"].shift(1) - 1.0

        trailing_ret_5 = close / close.shift(5) - 1.0
        trailing_rv_5 = np.sqrt(ret.pow(2).rolling(5).sum())
        winner_threshold = trailing_ret_5.rolling(126, min_periods=20).quantile(0.75).shift(1)
        rv_threshold = trailing_rv_5.rolling(126, min_periods=20).quantile(0.75).shift(1)

        msg = g["stocktwits_messages"]
        msg_threshold = msg.rolling(63, min_periods=5).quantile(0.80).shift(1)
        msg_floor = 2.0
        social_shock = (msg >= np.maximum(msg_threshold.fillna(msg_floor), msg_floor)) & (msg > 0)
        recent_winner_highrv = (trailing_ret_5 > winner_threshold) & (trailing_rv_5 > rv_threshold)
        raw_signal = (social_shock & recent_winner_highrv).astype(int)
        # Required no-lookahead guard: social signal from t-1, outcome starts at t.
        signal = raw_signal.shift(1).fillna(0).astype(int)

        vol_base_1 = log_volume.rolling(63, min_periods=20).mean().shift(1)
        trailing_log_volume_5 = log_volume.rolling(5, min_periods=5).sum()
        vol_base_5 = trailing_log_volume_5.rolling(63, min_periods=20).mean().shift(1)
        fwd_ret_5 = forward_sum(ret, 5)
        g["ret_1d"] = ret
        g["trailing_ret_5"] = trailing_ret_5
        g["trailing_rv_5"] = trailing_rv_5
        g["raw_social_transmission_signal"] = raw_signal
        g["signal"] = signal
        g["abn_log_volume_1d"] = log_volume - vol_base_1
        g["abn_log_volume_5d"] = forward_sum(log_volume, 5) - vol_base_5
        g["range_vol_1d"] = range_vol
        g["range_vol_5d"] = forward_sum(range_vol, 5)
        g["abs_gap_1d"] = gap.abs()
        g["reversal_5d"] = -fwd_ret_5
        g["fwd_ret_5d"] = fwd_ret_5
        rows.append(g)

    panel = pd.concat(rows, ignore_index=True)
    panel.to_csv(DATA_DIR / "panel.csv", index=False)
    return panel


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


def bootstrap_ci(effects: np.ndarray, reps: int = 1000) -> dict[str, Any]:
    effects = np.asarray(effects, dtype=float)
    effects = effects[np.isfinite(effects)]
    if len(effects) < 2:
        return {"n": int(len(effects)), "mean": float(effects.mean()) if len(effects) else None, "ci95": [None, None]}
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(reps):
        sample = rng.choice(effects, size=len(effects), replace=True)
        draws.append(float(np.mean(sample)))
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return {"n": int(len(effects)), "mean": float(effects.mean()), "ci95": [float(lo), float(hi)]}


def analyze(panel: pd.DataFrame) -> dict[str, Any]:
    usable = panel.dropna(subset=TARGETS).copy()
    usable = usable[usable["volume"] > 0]
    event_rows = usable[usable["signal"] == 1]
    control_rows = usable[usable["signal"] == 0]

    target_tests: dict[str, Any] = {}
    ticker_effects: dict[str, Any] = {}
    for target in TARGETS:
        target_tests[target] = welch(event_rows[target], control_rows[target])
        effects = []
        per_ticker = {}
        for ticker, g in usable.groupby("ticker"):
            ev = g.loc[g["signal"] == 1, target].dropna()
            co = g.loc[g["signal"] == 0, target].dropna()
            if len(ev) < 1 or len(co) < 10:
                continue
            diff = float(ev.mean() - co.mean())
            effects.append(diff)
            per_ticker[ticker] = {"event_n": int(len(ev)), "control_n": int(len(co)), "diff": diff}
        effects_arr = np.asarray(effects, dtype=float)
        sign = stats.binomtest(int((effects_arr > 0).sum()), n=len(effects_arr), p=0.5, alternative="greater") if len(effects_arr) else None
        ticker_effects[target] = {
            "per_ticker": per_ticker,
            "positive_tickers": int((effects_arr > 0).sum()) if len(effects_arr) else 0,
            "tested_tickers": int(len(effects_arr)),
            "sign_test_p_value": float(sign.pvalue) if sign else None,
            "bootstrap": bootstrap_ci(effects_arr),
        }

    coverage = (
        panel.groupby("ticker")
        .agg(
            price_rows=("close", "count"),
            stocktwits_days=("stocktwits_messages", lambda x: int((x > 0).sum())),
            stocktwits_messages=("stocktwits_messages", "sum"),
            raw_signal_days=("raw_social_transmission_signal", "sum"),
            applied_event_days=("signal", "sum"),
            first_price_date=("date", "min"),
            last_price_date=("date", "max"),
        )
        .reset_index()
    )

    primary = target_tests["abn_log_volume_5d"]
    range_primary = target_tests["range_vol_5d"]
    total_events = int(event_rows.shape[0])
    event_tickers = int(event_rows["ticker"].nunique()) if total_events else 0
    positive_primary = primary.get("diff") is not None and primary["diff"] > 0
    primary_ci = ticker_effects["abn_log_volume_5d"]["bootstrap"]["ci95"]
    ci_excludes_zero = primary_ci[0] is not None and primary_ci[0] > 0
    range_ci = ticker_effects["range_vol_5d"]["bootstrap"]["ci95"]
    range_ci_excludes_zero = range_ci[0] is not None and range_ci[0] > 0
    if total_events < 10 or event_tickers < 5:
        label = "UNDERPOWERED"
        conclusion = (
            "Public Stocktwits stream history was too shallow for a serious social-transmission market test; "
            f"usable events came from only {event_tickers} ticker(s)."
        )
    elif total_events >= 30 and ((positive_primary and ci_excludes_zero) or range_ci_excludes_zero):
        label = "PASS"
        conclusion = "Public Stocktwits message shocks show robust next-window volume or range-vol amplification."
    elif total_events >= 10 and (
        (primary.get("diff") is not None and primary["diff"] > 0)
        or (range_primary.get("diff") is not None and range_primary["diff"] > 0)
    ):
        label = "CONDITIONAL_PASS"
        conclusion = "There is directional evidence, but it is sample-limited or not robust across ticker-level bootstrap tests."
    else:
        label = "NULL"
        conclusion = "Event days do not show reliable next-window abnormal volume or range-vol amplification."

    return {
        "verdict": {
            "label": label,
            "conclusion": conclusion,
            "total_event_rows": total_events,
            "event_tickers": event_tickers,
            "primary_abn_log_volume_5d_diff": primary.get("diff"),
            "range_vol_5d_diff": range_primary.get("diff"),
        },
        "coverage_by_ticker": coverage.to_dict(orient="records"),
        "target_tests": target_tests,
        "ticker_effects": ticker_effects,
    }


def plot_effects(results: dict[str, Any]) -> None:
    labels = TARGETS
    vals = [results["target_tests"][t].get("diff") or 0.0 for t in labels]
    colors = ["#2f6f73" if v >= 0 else "#b64f4a" for v in vals]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.bar(labels, vals, color=colors)
    ax.set_title("K1554 event-minus-control effects")
    ax.set_ylabel("Mean difference")
    ax.tick_params(axis="x", rotation=35)
    fig.tight_layout()
    fig.savefig(ROOT / "k1554_event_effects.png", dpi=160)
    plt.close(fig)


def main() -> None:
    messages, diagnostics = load_stocktwits_messages()
    daily_counts = stocktwits_daily_counts(messages)
    prices = download_prices()
    panel = prepare_panel(prices, daily_counts)
    results = analyze(panel)
    plot_effects(results)

    out = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data": {
            "price_source": "yfinance adjusted OHLCV",
            "social_source": "Stocktwits unauthenticated public symbol streams",
            "requested_price_start": PRICE_START,
            "requested_price_end": PRICE_END,
            "tickers": list(UNIVERSE),
            "stocktwits_max_pages_per_ticker": STOCKTWITS_MAX_PAGES,
            "price_rows": int(len(prices)),
            "panel_rows": int(len(panel)),
            "stocktwits_message_rows": int(len(messages)),
            "stocktwits_daily_count_rows": int(len(daily_counts)),
            "blocked_sources": [
                "Stocktwits Firestream historical sentiment/chart endpoint returned 401 Unauthorized in this environment.",
                "GDELT timeline probes returned 429 rate-limit responses during the live run; no media-title proxy is mixed into the Stocktwits result.",
            ],
        },
        "methods": {
            "raw_signal": "message-count shock AND trailing 5d winner AND trailing 5d high-RV",
            "lookahead_guard": "signal = raw_signal.shift(1); outcomes start on the applied day",
            "thresholds": "message count rolling 63d 80th percentile shifted by one day; winner/high-RV rolling 126d 75th percentiles shifted by one day",
            "tests": "pooled Welch diagnostics, ticker-level event-minus-control effects, seed-42 bootstrap over ticker effects, sign tests",
        },
        "stocktwits_fetch_diagnostics": diagnostics,
        **results,
        "limitations": [
            "The public Stocktwits stream is recent-message pagination, not a full historical archive.",
            "No follower graph, user portfolio, or transaction data are observed.",
            "Message timestamps are aggregated by UTC date, not market-session-local post timing.",
            "The fixed current ticker basket is not a survivorship-free historical universe.",
            "Overlapping 5-day targets are diagnostic; this is not a tradable strategy backtest.",
        ],
    }
    (ROOT / "k1554_results.json").write_text(json.dumps(_json_safe(out), indent=2), encoding="utf-8")
    print(json.dumps({"verdict": out["verdict"], "data": out["data"]}, indent=2))


if __name__ == "__main__":
    main()
