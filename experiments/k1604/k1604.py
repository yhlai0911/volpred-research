#!/usr/bin/env python3
"""K1604: sports-betting launch shocks and gambling-stock realized volatility.

Question: do state online sports-betting launch dates create abnormal realized
volatility or volume in public gambling / sportsbook equities, after controlling
for broad risk-on market movement?

This is an event-study screening experiment. Event dates are manually curated
from public state-launch trackers and recorded in README.md. Outcomes start on
the next trading day after launch, so there is no same-day event/return timing
claim. The statistical unit is the event-level equal-weighted betting-basket
differential, not pooled ticker-event rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

SEED = 42
START = "2018-01-01"
END = None
BOOT_REPS = 10000
RANDOM_REPS = 1000

BETTING_TICKERS = {
    "DKNG": "DraftKings sportsbook / iGaming",
    "PENN": "Penn Entertainment casinos / sportsbook",
    "MGM": "MGM Resorts / BetMGM exposure",
    "CZR": "Caesars / Caesars Sportsbook",
    "RSI": "Rush Street Interactive",
    "GENI": "Genius Sports sports-data betting infrastructure",
    "SRAD": "Sportradar sports-data betting infrastructure",
    "BETZ": "Roundhill Sports Betting & iGaming ETF",
}
CONTROL_TICKERS = {
    "SPY": "broad market",
    "IWM": "small-cap / retail-risk control",
    "QQQ": "growth / risk-on control",
}


EVENTS = [
    # Major online/mobile launch dates after PASPA. Retail-only launches are
    # excluded unless statewide online access started on the same date.
    ("2018-08-06", "NJ", "New Jersey online launch wave"),
    ("2019-05-31", "PA", "Pennsylvania online launch"),
    ("2019-08-15", "IA", "Iowa online launch"),
    ("2019-10-03", "IN", "Indiana online launch"),
    ("2019-12-30", "NH", "New Hampshire online launch"),
    ("2020-05-01", "CO", "Colorado online launch"),
    ("2020-06-18", "IL", "Illinois online launch"),
    ("2020-11-01", "TN", "Tennessee online-only launch"),
    ("2021-01-21", "VA", "Virginia online launch"),
    ("2021-01-22", "MI", "Michigan online launch"),
    ("2021-09-09", "AZ", "Arizona online launch"),
    ("2021-10-19", "CT", "Connecticut online launch"),
    ("2022-01-08", "NY", "New York online launch"),
    ("2022-01-28", "LA", "Louisiana online launch"),
    ("2022-09-01", "KS", "Kansas launch"),
    ("2022-11-23", "MD", "Maryland online launch"),
    ("2023-01-01", "OH", "Ohio launch"),
    ("2023-03-10", "MA", "Massachusetts online launch"),
    ("2023-09-28", "KY", "Kentucky online launch"),
    ("2023-11-03", "ME", "Maine online launch"),
    ("2024-01-11", "VT", "Vermont online launch"),
    ("2024-03-11", "NC", "North Carolina online launch"),
    ("2025-12-01", "MO", "Missouri online launch"),
]


@dataclass(frozen=True)
class Event:
    date: pd.Timestamp
    state: str
    label: str


def _event_objects() -> list[Event]:
    return [Event(pd.Timestamp(d), state, label) for d, state, label in EVENTS]


def download_ohlcv(ticker: str, refresh: bool = False) -> pd.DataFrame:
    cache = DATA_DIR / f"{ticker}.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, parse_dates=["Date"]).set_index("Date").sort_index()

    import yfinance as yf

    raw = yf.download(
        ticker,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        actions=False,
        threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"empty yfinance history for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    out = raw[["Close", "Volume"]].copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.reset_index().rename(columns={"index": "Date"}).to_csv(cache, index=False)
    return out


def load_panel(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    failed: list[str] = []
    for ticker in list(BETTING_TICKERS) + list(CONTROL_TICKERS):
        try:
            df = download_ohlcv(ticker, refresh=refresh)
            closes[ticker] = df["Close"]
            volumes[ticker] = df["Volume"]
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{ticker}: {exc}")
    close = pd.DataFrame(closes).sort_index()
    volume = pd.DataFrame(volumes).sort_index()
    return close, volume, failed


def realized_vol(log_returns: pd.Series) -> float:
    r = log_returns.dropna()
    if len(r) < 3:
        return float("nan")
    return float(np.sqrt(np.mean(np.square(r.to_numpy())) * 252.0))


def volume_mean(volumes: pd.Series) -> float:
    v = volumes.dropna()
    if len(v) < 3:
        return float("nan")
    return float(v.mean())


def _ratio(post: float, pre: float) -> float:
    if not np.isfinite(post) or not np.isfinite(pre) or pre <= 0:
        return float("nan")
    return float(post / pre)


def event_windows(index: pd.DatetimeIndex, event_date: pd.Timestamp) -> dict[str, pd.DatetimeIndex] | None:
    pos = int(index.searchsorted(event_date, side="left"))
    if pos <= 30 or pos + 22 >= len(index):
        return None
    return {
        "event_trading_day": pd.DatetimeIndex([index[pos]]),
        "pre": index[pos - 30 : pos - 5],
        "post5": index[pos + 1 : pos + 6],
        "post22": index[pos + 1 : pos + 23],
    }


def ticker_metrics(
    ticker: str,
    windows: dict[str, pd.DatetimeIndex],
    close: pd.DataFrame,
    volume: pd.DataFrame,
) -> dict[str, float]:
    lr = np.log(close[ticker] / close[ticker].shift(1))
    pre_rv = realized_vol(lr.reindex(windows["pre"]))
    post5_rv = realized_vol(lr.reindex(windows["post5"]))
    post22_rv = realized_vol(lr.reindex(windows["post22"]))
    pre_vol = volume_mean(volume[ticker].reindex(windows["pre"]))
    post5_vol = volume_mean(volume[ticker].reindex(windows["post5"]))
    post22_vol = volume_mean(volume[ticker].reindex(windows["post22"]))
    return {
        "pre_rv": pre_rv,
        "post5_rv": post5_rv,
        "post22_rv": post22_rv,
        "post5_rv_ratio": _ratio(post5_rv, pre_rv),
        "post22_rv_ratio": _ratio(post22_rv, pre_rv),
        "pre_volume": pre_vol,
        "post5_volume": post5_vol,
        "post22_volume": post22_vol,
        "post5_volume_ratio": _ratio(post5_vol, pre_vol),
        "post22_volume_ratio": _ratio(post22_vol, pre_vol),
    }


def log_mean_ratio(rows: list[dict[str, float]], key: str) -> float:
    vals = [r[key] for r in rows if np.isfinite(r.get(key, np.nan)) and r[key] > 0]
    if not vals:
        return float("nan")
    return float(np.mean(np.log(vals)))


def build_event_panel(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    events: list[Event],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    base_index = close.dropna(how="all").index
    event_rows: list[dict[str, object]] = []
    ticker_rows: list[dict[str, object]] = []
    betting_loaded = [t for t in BETTING_TICKERS if t in close.columns]
    controls_loaded = [t for t in CONTROL_TICKERS if t in close.columns]

    for event in events:
        windows = event_windows(base_index, event.date)
        if windows is None:
            continue

        betting_metrics: list[dict[str, float]] = []
        control_metrics: list[dict[str, float]] = []
        for ticker in betting_loaded + controls_loaded:
            if ticker not in close.columns:
                continue
            m = ticker_metrics(ticker, windows, close, volume)
            if all(np.isnan(m[k]) for k in ("post5_rv_ratio", "post22_rv_ratio")):
                continue
            row = {
                "state": event.state,
                "label": event.label,
                "event_date": event.date.date().isoformat(),
                "event_trading_day": windows["event_trading_day"][0].date().isoformat(),
                "ticker": ticker,
                "role": "betting" if ticker in BETTING_TICKERS else "control",
                **m,
            }
            ticker_rows.append(row)
            if ticker in BETTING_TICKERS:
                betting_metrics.append(m)
            else:
                control_metrics.append(m)

        if len(betting_metrics) < 3 or len(control_metrics) < 2:
            continue
        b5 = log_mean_ratio(betting_metrics, "post5_rv_ratio")
        c5 = log_mean_ratio(control_metrics, "post5_rv_ratio")
        b22 = log_mean_ratio(betting_metrics, "post22_rv_ratio")
        c22 = log_mean_ratio(control_metrics, "post22_rv_ratio")
        bv5 = log_mean_ratio(betting_metrics, "post5_volume_ratio")
        cv5 = log_mean_ratio(control_metrics, "post5_volume_ratio")
        bv22 = log_mean_ratio(betting_metrics, "post22_volume_ratio")
        cv22 = log_mean_ratio(control_metrics, "post22_volume_ratio")
        event_rows.append(
            {
                "state": event.state,
                "label": event.label,
                "event_date": event.date.date().isoformat(),
                "event_trading_day": windows["event_trading_day"][0].date().isoformat(),
                "n_betting_tickers": len(betting_metrics),
                "n_control_tickers": len(control_metrics),
                "betting_post5_rv_log_ratio": b5,
                "control_post5_rv_log_ratio": c5,
                "adj_post5_rv_log_ratio": b5 - c5,
                "betting_post22_rv_log_ratio": b22,
                "control_post22_rv_log_ratio": c22,
                "adj_post22_rv_log_ratio": b22 - c22,
                "adj_post5_volume_log_ratio": bv5 - cv5,
                "adj_post22_volume_log_ratio": bv22 - cv22,
            }
        )
    return pd.DataFrame(event_rows), pd.DataFrame(ticker_rows)


def one_sample_stats(x: np.ndarray, boot_reps: int = BOOT_REPS, seed: int = SEED) -> dict[str, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return {"n": n, "mean": float(np.nan), "se": float(np.nan), "t": float(np.nan), "p": float(np.nan),
                "ci_lo": float(np.nan), "ci_hi": float(np.nan), "frac_positive": float(np.nan)}
    mean = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n))
    t = mean / se if se > 0 else float("nan")
    p = float(2 * scipy_stats.t.sf(abs(t), df=n - 1)) if np.isfinite(t) else float("nan")
    rng = np.random.default_rng(seed)
    boots = np.empty(boot_reps)
    for i in range(boot_reps):
        boots[i] = x[rng.integers(0, n, size=n)].mean()
    return {
        "n": n,
        "mean": mean,
        "se": se,
        "t": float(t),
        "p": p,
        "ci_lo": float(np.percentile(boots, 2.5)),
        "ci_hi": float(np.percentile(boots, 97.5)),
        "frac_positive": float(np.mean(boots > 0)),
    }


def random_anchor_test(close: pd.DataFrame, volume: pd.DataFrame, events: list[Event]) -> dict[str, float]:
    index = close.dropna(how="all").index
    event_positions = [int(index.searchsorted(e.date, side="left")) for e in events]
    event_positions = [p for p in event_positions if 31 <= p < len(index) - 23]
    blocked = set()
    for p in event_positions:
        blocked.update(range(max(31, p - 30), min(len(index) - 23, p + 31)))
    by_year: dict[int, list[int]] = {}
    for p in range(31, len(index) - 23):
        if p in blocked:
            continue
        by_year.setdefault(index[p].year, []).append(p)

    observed_events = [e for e in events if 31 <= int(index.searchsorted(e.date, side="left")) < len(index) - 23]
    observed_panel, _ = build_event_panel(close, volume, observed_events)
    observed = float(observed_panel["adj_post5_rv_log_ratio"].mean())

    @lru_cache(maxsize=None)
    def metric_for_pos(pos: int) -> float:
        panel, _ = build_event_panel(close, volume, [Event(index[pos], "R", "matched random anchor")])
        if panel.empty:
            return float("nan")
        return float(panel["adj_post5_rv_log_ratio"].iloc[0])

    rng = np.random.default_rng(SEED)
    random_means: list[float] = []
    for _ in range(RANDOM_REPS):
        sampled_metrics: list[float] = []
        for e in observed_events:
            candidates = by_year.get(e.date.year) or []
            if not candidates:
                continue
            pos = int(rng.choice(candidates))
            sampled_metrics.append(metric_for_pos(pos))
        sampled = np.asarray(sampled_metrics, dtype=float)
        sampled = sampled[np.isfinite(sampled)]
        if len(sampled) < max(5, len(observed_events) // 2):
            continue
        random_means.append(float(sampled.mean()))

    arr = np.asarray(random_means, dtype=float)
    arr = arr[np.isfinite(arr)]
    return {
        "observed_mean": observed,
        "n_random_reps": int(len(arr)),
        "random_mean": float(arr.mean()) if len(arr) else float("nan"),
        "random_ci_lo": float(np.percentile(arr, 2.5)) if len(arr) else float("nan"),
        "random_ci_hi": float(np.percentile(arr, 97.5)) if len(arr) else float("nan"),
        "p_upper": float(np.mean(arr >= observed)) if len(arr) else float("nan"),
    }


def verdict_from(stats: dict[str, dict[str, float]], random_test: dict[str, float]) -> str:
    primary = stats["adj_post5_rv_log_ratio"]
    ci_pass = primary["ci_lo"] > 0
    random_pass = random_test.get("p_upper", 1.0) < 0.05
    if primary["t"] >= 3.0 and ci_pass and random_pass:
        return "PASS"
    if primary["t"] >= 2.0 and ci_pass:
        return "SUGGESTIVE"
    return "NULL"


def make_figures(events_df: pd.DataFrame, stats: dict[str, dict[str, float]], random_test: dict[str, float]) -> list[str]:
    paths: list[str] = []
    if events_df.empty:
        return paths

    ordered = events_df.sort_values("event_trading_day")
    fig, ax = plt.subplots(figsize=(10, 4.8))
    vals = ordered["adj_post5_rv_log_ratio"].to_numpy()
    colors = ["#2b8cbe" if v >= 0 else "#e34a33" for v in vals]
    labels = ordered["state"].tolist()
    ax.bar(np.arange(len(vals)), vals, color=colors)
    ax.axhline(0, color="black", lw=0.8)
    ax.axhline(vals.mean(), color="#31a354", ls="--", lw=1.2, label=f"mean {vals.mean():+.3f}")
    ax.set_xticks(np.arange(len(vals)))
    ax.set_xticklabels(labels, rotation=60, ha="right")
    ax.set_ylabel("Betting basket minus controls, log RV ratio")
    ax.set_title("K1604: post-launch T+1..T+5 adjusted RV by event")
    ax.legend()
    fig.tight_layout()
    p = FIG_DIR / "fig_a_event_adj_rv.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    paths.append(str(p))

    fig, ax = plt.subplots(figsize=(8, 4.8))
    metric_order = [
        ("adj_post5_rv_log_ratio", "RV T+5"),
        ("adj_post22_rv_log_ratio", "RV T+22"),
        ("adj_post5_volume_log_ratio", "Volume T+5"),
        ("adj_post22_volume_log_ratio", "Volume T+22"),
    ]
    means = [stats[m]["mean"] for m, _ in metric_order]
    los = [stats[m]["ci_lo"] for m, _ in metric_order]
    his = [stats[m]["ci_hi"] for m, _ in metric_order]
    xs = np.arange(len(metric_order))
    ax.bar(xs, means, color="#756bb1")
    ax.errorbar(xs, means, yerr=[np.array(means) - np.array(los), np.array(his) - np.array(means)],
                fmt="none", ecolor="black", capsize=4)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(xs)
    ax.set_xticklabels([label for _, label in metric_order])
    ax.set_ylabel("Mean adjusted log ratio, 95% event-bootstrap CI")
    ax.set_title("K1604 summary metrics")
    fig.tight_layout()
    p = FIG_DIR / "fig_b_summary.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    paths.append(str(p))
    return paths


def main() -> None:
    close, volume, failed = load_panel(refresh=False)
    events = _event_objects()
    events_df, ticker_df = build_event_panel(close, volume, events)
    metrics = [
        "adj_post5_rv_log_ratio",
        "adj_post22_rv_log_ratio",
        "adj_post5_volume_log_ratio",
        "adj_post22_volume_log_ratio",
    ]
    stats = {m: one_sample_stats(events_df[m].to_numpy()) for m in metrics}
    random_test = random_anchor_test(close, volume, events)
    verdict = verdict_from(stats, random_test)
    fig_paths = make_figures(events_df, stats, random_test)

    results = {
        "experiment_id": "K1604",
        "title": "Sports-betting legalization / launch shock and gambling-stock RV",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance adjusted close and volume; manually curated public online sports-betting launch dates",
        "sample_start": START,
        "data_start": str(close.index.min().date()) if len(close.index) else None,
        "data_end": str(close.index.max().date()) if len(close.index) else None,
        "seed": SEED,
        "failed_downloads": failed,
        "betting_tickers": BETTING_TICKERS,
        "control_tickers": CONTROL_TICKERS,
        "n_events_input": len(events),
        "n_events_used": int(len(events_df)),
        "events_used": events_df.to_dict(orient="records"),
        "ticker_event_rows": ticker_df.to_dict(orient="records"),
        "stats": stats,
        "random_anchor_test": random_test,
        "figures": fig_paths,
        "verdict": verdict,
        "lookahead_note": "Event dates are fixed ex ante; all post outcomes start on the next trading day after launch. Statistical unit is event-level basket differential.",
        "caveats": [
            "Launch dates are manually curated from public trackers and should be treated as a screening event set, not a legal database.",
            "No state-level handle surprise series is used; this tests access/launch dates only.",
            "Public equities have national revenue exposure and may price legalization before launch.",
            "Ticker universe is current/liquid and not a point-in-time sportsbook revenue-weighted basket.",
        ],
    }
    out = HERE / "k1604_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    events_df.to_csv(HERE / "k1604_event_panel.csv", index=False)
    ticker_df.to_csv(HERE / "k1604_ticker_event_panel.csv", index=False)

    p = stats["adj_post5_rv_log_ratio"]
    print(f"[K1604] events={len(events_df)} data={results['data_start']}..{results['data_end']} failed={len(failed)}")
    print(
        "  primary adj_post5_rv_log_ratio "
        f"mean={p['mean']:+.4f} t={p['t']:+.2f} p={p['p']:.3f} "
        f"CI=[{p['ci_lo']:+.4f},{p['ci_hi']:+.4f}] "
        f"random_p_upper={random_test.get('p_upper', float('nan')):.3f}"
    )
    print(f"  VERDICT={verdict}")
    print(f"  results -> {out}")


if __name__ == "__main__":
    main()
