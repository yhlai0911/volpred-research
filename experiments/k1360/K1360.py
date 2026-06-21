#!/usr/bin/env python3
"""K1360: prediction-market probability shocks as macro-event vol priors.

This is a feasibility-and-diagnostic experiment. It tests whether public
Kalshi macro-event prices can be transformed into a lagged daily probability
shock and whether that shock has any first-pass relationship with VIX9D/VIX,
SPY one-day absolute returns, or forward five-day SPY realized volatility.

The implementation is deliberately conservative:
- Polymarket is probed but excluded if the domain-block page is returned.
- Kalshi event-market rows are aggregated to date-level time-series signals.
- The primary signal is event-level max absolute close-price change, not a
  sum over overlapping CPI threshold markets.
- The signal used in regressions is explicitly signal.shift(1).
"""

from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.parse
import urllib.error
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RAW_DIR = DATA_DIR / "raw"
FIG_DIR = HERE / "figures"
for directory in [DATA_DIR, RAW_DIR, FIG_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

EXPERIMENT_ID = "K1360"
SEED = 42
ANALYSIS_START = pd.Timestamp("2025-09-01")
END_TS = int(time.time())
KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_SERIES = {
    "KXCPI": "headline_cpi",
    "KXCPICORE": "core_cpi",
    "KXFEDDECISION": "fomc",
    "KXPAYROLLS": "payrolls",
    "KXUSNFP": "us_nfp",
}
PROBE_SERIES = ["KXNFP", "KXNONFARM", "KXJOBS", "KXUNEMPLOY", "KXJOBLESSCLAIMS"]
MAX_MARKETS_PER_EVENT = 6
MIN_EVENT_VOLUME = 1.0
NW_LAG_DAILY = 5
HARVEY_T = 3.0

LITERATURE = [
    {
        "citation": "Wolfers and Zitzewitz (2004), Prediction Markets, Journal of Economic Perspectives",
        "url": "https://www.aeaweb.org/articles?id=10.1257/0895330041371321",
        "role": "prediction-market prices as probabilistic summaries of dispersed information",
    },
    {
        "citation": "Manski (2006), Interpreting the Predictions of Prediction Markets, Economics Letters",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S0165176505003336",
        "role": "market prices need not equal mean beliefs under all assumptions",
    },
    {
        "citation": "Snowberg, Wolfers, and Zitzewitz (2013), Prediction Markets for Economic Forecasting, Handbook of Economic Forecasting",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/B978044453683900017X",
        "role": "prediction markets as forecasting tools, with calibration and liquidity caveats",
    },
    {
        "citation": "Bernanke and Kuttner (2005), What Explains the Stock Market's Reaction to Federal Reserve Policy?, Journal of Finance",
        "url": "https://www.jstor.org/stable/3694737",
        "role": "policy surprises can move equity prices and discount rates",
    },
    {
        "citation": "Kuttner (2001), Monetary policy surprises and interest rates, Journal of Monetary Economics",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304393201000551",
        "role": "fed funds futures provide a conventional policy-surprise prior",
    },
]


def _float(value: Any) -> float:
    if value is None:
        return float("nan")
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return float("nan")


def _parse_time(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        return pd.Timestamp(value).tz_convert("UTC")
    except Exception:
        try:
            return pd.Timestamp(value).tz_localize("UTC")
        except Exception:
            return None


def _urlopen_text(url: str, timeout: int = 30, unverified_ssl: bool = False) -> str:
    headers = {
        "User-Agent": "volpred-k1360/1.0 (+research; contact=local)",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }
    request = urllib.request.Request(url, headers=headers)
    context = ssl._create_unverified_context() if unverified_ssl else None
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read().decode("utf-8", errors="replace")


def _read_or_fetch_json(url: str, cache_name: str, refresh: bool = False) -> dict:
    cache_path = RAW_DIR / cache_name
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    text = _urlopen_text(url)
    data = json.loads(text)
    cache_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def probe_polymarket(refresh: bool = False) -> dict:
    endpoints = [
        "https://gamma-api.polymarket.com/events?limit=1",
        "https://clob.polymarket.com/prices-history?market=0x0&interval=1d",
    ]
    probes = []
    for i, url in enumerate(endpoints, start=1):
        cache_path = RAW_DIR / f"polymarket_probe_{i}.html"
        text = ""
        status = None
        error = None
        try:
            if cache_path.exists() and not refresh:
                text = cache_path.read_text(encoding="utf-8", errors="replace")
            else:
                text = _urlopen_text(url, timeout=12, unverified_ssl=True)
                cache_path.write_text(text[:5000], encoding="utf-8")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            try:
                text = exc.read().decode("utf-8", errors="replace")
                cache_path.write_text(text[:5000], encoding="utf-8")
            except Exception:
                text = ""
            error = repr(exc)
        except Exception as exc:
            error = repr(exc)

        blocked = "此網域已經遭到封鎖" in text or "Domain Name Has Been Blocked" in text
        looks_json = bool(text and text.lstrip().startswith(("[", "{")))
        probes.append(
            {
                "url": url,
                "http_status": status,
                "ok": bool(looks_json and not blocked and status in (None, 200)),
                "blocked_domain_page_detected": blocked,
                "error": error,
                "bytes_saved": int(len(text[:5000])),
                "cache_path": str(cache_path.relative_to(HERE)),
            }
        )

    return {
        "ok": any(probe["ok"] for probe in probes),
        "blocked_domain_page_detected": any(
            probe["blocked_domain_page_detected"] for probe in probes
        ),
        "all_endpoints_failed": not any(probe["ok"] for probe in probes),
        "probes": probes,
    }


def kalshi_event_list(series_ticker: str, refresh: bool = False) -> list[dict]:
    url = f"{KALSHI_BASE}/events?series_ticker={series_ticker}&limit=200"
    data = _read_or_fetch_json(url, f"kalshi_events_{series_ticker}.json", refresh)
    return list(data.get("events", []))


def probe_missing_series(refresh: bool = False) -> dict:
    out = {}
    for series in PROBE_SERIES:
        try:
            events = kalshi_event_list(series, refresh)
            out[series] = {
                "events_returned": int(len(events)),
                "first_event_ticker": events[0]["event_ticker"] if events else None,
            }
        except Exception as exc:
            out[series] = {"events_returned": 0, "error": repr(exc)}
    return out


def kalshi_event_detail(event_ticker: str, refresh: bool = False) -> dict:
    safe = urllib.parse.quote(event_ticker, safe="")
    url = f"{KALSHI_BASE}/events/{safe}"
    return _read_or_fetch_json(url, f"kalshi_event_{event_ticker}.json", refresh)


def kalshi_candles(
    series_ticker: str,
    market_ticker: str,
    start_ts: int,
    end_ts: int,
    refresh: bool = False,
) -> list[dict]:
    safe_series = urllib.parse.quote(series_ticker, safe="")
    safe_market = urllib.parse.quote(market_ticker, safe="")
    url = (
        f"{KALSHI_BASE}/series/{safe_series}/markets/{safe_market}/candlesticks"
        f"?start_ts={start_ts}&end_ts={end_ts}&period_interval=1440"
        "&include_latest_before_start=true"
    )
    data = _read_or_fetch_json(
        url,
        f"kalshi_candles_{series_ticker}_{market_ticker}.json",
        refresh,
    )
    return list(data.get("candlesticks", []))


def market_score(market: dict) -> float:
    volume = _float(market.get("volume_fp") or market.get("volume_dollars"))
    open_interest = _float(market.get("open_interest_fp"))
    liquidity = _float(market.get("liquidity_dollars"))
    return max(volume, 0.0) + 0.05 * max(open_interest, 0.0) + 0.1 * max(liquidity, 0.0)


def market_close_probability(candle: dict) -> float:
    price = candle.get("price") or {}
    close = _float(price.get("close_dollars"))
    if np.isfinite(close):
        return close
    bid = _float((candle.get("yes_bid") or {}).get("close_dollars"))
    ask = _float((candle.get("yes_ask") or {}).get("close_dollars"))
    if np.isfinite(bid) and np.isfinite(ask) and 0.0 <= bid <= ask <= 1.0:
        return float((bid + ask) / 2.0)
    previous = _float(price.get("previous_dollars"))
    return previous if np.isfinite(previous) else float("nan")


def candle_date(candle: dict) -> pd.Timestamp:
    # end_period_ts marks the end of the daily candle. Subtract one second so
    # a candle ending at New York midnight is assigned to the trading date that
    # just ended.
    ts = int(candle["end_period_ts"]) - 1
    return (
        pd.to_datetime(ts, unit="s", utc=True)
        .tz_convert("America/New_York")
        .tz_localize(None)
        .normalize()
    )


def event_anchor_date(event: dict, markets: list[dict]) -> pd.Timestamp | None:
    candidates: list[pd.Timestamp] = []
    for key in ["strike_date"]:
        parsed = _parse_time(event.get(key))
        if parsed is not None:
            candidates.append(parsed)
    for market in markets:
        for key in ["occurrence_datetime", "close_time", "expected_expiration_time"]:
            parsed = _parse_time(market.get(key))
            if parsed is not None:
                candidates.append(parsed)
    if not candidates:
        return None
    return min(candidates).tz_convert("America/New_York").tz_localize(None).normalize()


def is_relevant_event(event: dict) -> bool:
    ticker = event.get("event_ticker", "")
    if "-26" not in ticker:
        return False
    return True


def build_kalshi_panel(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    selected_event_records = []
    candle_rows = []
    series_event_counts = {}
    unavailable_events = []

    for series, event_type in KALSHI_SERIES.items():
        events = [event for event in kalshi_event_list(series, refresh) if is_relevant_event(event)]
        series_event_counts[series] = int(len(events))
        for event_stub in events:
            event_ticker = event_stub["event_ticker"]
            detail = kalshi_event_detail(event_ticker, refresh)
            event = detail.get("event") or event_stub
            markets = list(detail.get("markets", []))
            if not markets:
                unavailable_events.append(
                    {"event_ticker": event_ticker, "series_ticker": series, "reason": "no_markets"}
                )
                continue

            anchor = event_anchor_date(event, markets)
            markets = [
                market
                for market in markets
                if market.get("ticker") and market_score(market) >= MIN_EVENT_VOLUME
            ]
            markets = sorted(markets, key=market_score, reverse=True)[:MAX_MARKETS_PER_EVENT]
            if not markets:
                unavailable_events.append(
                    {"event_ticker": event_ticker, "series_ticker": series, "reason": "no_liquid_markets"}
                )
                continue

            selected_event_records.append(
                {
                    "event_ticker": event_ticker,
                    "series_ticker": series,
                    "event_type": event_type,
                    "title": event.get("title"),
                    "mutually_exclusive": bool(event.get("mutually_exclusive")),
                    "anchor_date": str(anchor.date()) if anchor is not None else None,
                    "selected_markets": int(len(markets)),
                    "selected_market_tickers": [market["ticker"] for market in markets],
                    "source_names": [
                        source.get("name")
                        for source in event.get("settlement_sources", [])
                        if source.get("name")
                    ],
                }
            )

            for market in markets:
                open_time = _parse_time(market.get("open_time"))
                start_ts = int(open_time.timestamp()) if open_time is not None else int(ANALYSIS_START.timestamp())
                start_ts = max(start_ts, int(ANALYSIS_START.timestamp()) - 10 * 86400)
                try:
                    candles = kalshi_candles(series, market["ticker"], start_ts, END_TS, refresh)
                except Exception as exc:
                    unavailable_events.append(
                        {
                            "event_ticker": event_ticker,
                            "series_ticker": series,
                            "market_ticker": market["ticker"],
                            "reason": f"candles_error:{exc!r}",
                        }
                    )
                    continue
                for candle in candles:
                    close_prob = market_close_probability(candle)
                    if not np.isfinite(close_prob):
                        continue
                    date = candle_date(candle)
                    if date < ANALYSIS_START:
                        continue
                    candle_rows.append(
                        {
                            "date": date,
                            "event_ticker": event_ticker,
                            "series_ticker": series,
                            "event_type": event_type,
                            "market_ticker": market["ticker"],
                            "mutually_exclusive": bool(event.get("mutually_exclusive")),
                            "anchor_date": str(anchor.date()) if anchor is not None else None,
                            "close_prob": float(close_prob),
                            "volume": _float(candle.get("volume_fp")),
                            "open_interest": _float(candle.get("open_interest_fp")),
                            "market_score": float(market_score(market)),
                        }
                    )

    market_panel = pd.DataFrame(candle_rows)
    event_meta = pd.DataFrame(selected_event_records)
    if market_panel.empty:
        raise RuntimeError("Kalshi returned no usable candle rows")

    market_panel = market_panel.sort_values(["event_ticker", "market_ticker", "date"])
    market_panel["prob_change"] = market_panel.groupby(
        ["event_ticker", "market_ticker"], sort=False
    )["close_prob"].diff()
    market_panel["abs_prob_change"] = market_panel["prob_change"].abs()
    market_panel = market_panel.dropna(subset=["prob_change"])

    event_daily = (
        market_panel.groupby(["date", "event_ticker", "event_type"], as_index=False)
        .agg(
            anchor_date=("anchor_date", "first"),
            mutually_exclusive=("mutually_exclusive", "first"),
            shock_max_abs=("abs_prob_change", "max"),
            shock_mean_abs=("abs_prob_change", "mean"),
            shock_l1_sum=("abs_prob_change", "sum"),
            active_markets=("market_ticker", "nunique"),
            total_volume=("volume", "sum"),
            total_open_interest=("open_interest", "sum"),
        )
        .sort_values(["event_ticker", "date"])
    )

    daily = (
        event_daily.groupby("date", as_index=True)
        .agg(
            kalshi_shock_max_abs=("shock_max_abs", "max"),
            kalshi_shock_mean_abs=("shock_mean_abs", "mean"),
            kalshi_shock_l1_sum=("shock_l1_sum", "sum"),
            n_events_with_shock=("event_ticker", "nunique"),
            n_active_markets=("active_markets", "sum"),
        )
        .sort_index()
    )
    for event_type in sorted(event_daily["event_type"].unique()):
        sub = event_daily[event_daily["event_type"] == event_type]
        daily[f"{event_type}_shock_max_abs"] = sub.groupby("date")["shock_max_abs"].max()
    daily = daily.fillna(0.0)

    meta = {
        "kalshi_base_url": KALSHI_BASE,
        "series_requested": KALSHI_SERIES,
        "probe_series_without_usable_events": probe_missing_series(refresh),
        "series_event_counts_2026": series_event_counts,
        "selected_events": int(event_meta["event_ticker"].nunique()),
        "selected_markets": int(market_panel["market_ticker"].nunique()),
        "market_candle_rows": int(len(market_panel)),
        "event_daily_rows": int(len(event_daily)),
        "calendar_signal_days": int(len(daily)),
        "unavailable_events": unavailable_events,
        "market_selection": (
            f"top {MAX_MARKETS_PER_EVENT} markets per event by volume + 0.05*open_interest "
            f"+ 0.1*liquidity, requiring score >= {MIN_EVENT_VOLUME}"
        ),
        "primary_shock_definition": (
            "event-level max absolute daily close-probability change; calendar-day signal "
            "is max across events"
        ),
    }

    event_meta.to_csv(DATA_DIR / "kalshi_selected_events.csv", index=False)
    market_panel.to_csv(DATA_DIR / "kalshi_market_panel.csv", index=False)
    event_daily.to_csv(DATA_DIR / "kalshi_event_daily.csv", index=False)
    daily.to_csv(DATA_DIR / "kalshi_daily_signal_raw.csv")
    return daily, event_daily, meta


def _load_one_yfinance(ticker: str, refresh: bool = False) -> pd.Series:
    cache = DATA_DIR / f"yf_{ticker.replace('^', '').replace('=', '_')}.csv"
    if cache.exists() and not refresh:
        df = pd.read_csv(cache, parse_dates=["Date"])
        return df.set_index("Date")["Close"].sort_index()

    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=str(ANALYSIS_START.date()), auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError(f"empty yfinance history for {ticker}")
    close = hist["Close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(
        cache, index=False
    )
    return close


def load_market_targets(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    tickers = ["SPY", "^VIX", "^VIX9D", "ZQ=F"]
    closes = {ticker: _load_one_yfinance(ticker, refresh) for ticker in tickers}
    close = pd.DataFrame(closes).sort_index()
    close = close.dropna(subset=["SPY", "^VIX", "^VIX9D"])

    spy_logret = np.log(close["SPY"] / close["SPY"].shift(1))
    vix_log = np.log(close["^VIX"] / close["^VIX"].shift(1))
    vix9d_log = np.log(close["^VIX9D"] / close["^VIX9D"].shift(1))
    ratio = np.log(close["^VIX9D"] / close["^VIX"])
    zq_change = close["ZQ=F"].diff().abs()

    targets = pd.DataFrame(index=close.index)
    targets["spy_ret_1d"] = close["SPY"].pct_change()
    targets["spy_abs_ret_1d"] = targets["spy_ret_1d"].abs()
    targets["spy_left_tail_1d"] = (-spy_logret).clip(lower=0.0)
    targets["spy_rv5_forward"] = np.sqrt(
        spy_logret.pow(2).rolling(5).sum().shift(-4) * 252.0 / 5.0
    )
    targets["vix_log_change_1d"] = vix_log
    targets["vix9d_log_change_1d"] = vix9d_log
    targets["vix9d_vix_log_ratio"] = ratio
    targets["vix9d_vix_ratio_change"] = ratio.diff()
    targets["fedfunds_futures_abs_change"] = zq_change

    coverage = {}
    for ticker, series in closes.items():
        s = series.dropna()
        coverage[ticker] = {
            "first": str(s.index.min().date()) if not s.empty else None,
            "last": str(s.index.max().date()) if not s.empty else None,
            "n_obs": int(len(s)),
        }
    targets.to_csv(DATA_DIR / "market_targets.csv")
    return targets, {
        "source": "yfinance adjusted close; ZQ=F is 30-Day Fed Funds futures continuous ticker used as FedWatch-like baseline",
        "coverage": coverage,
    }


def build_analysis_panel(
    kalshi_daily: pd.DataFrame,
    market_targets: pd.DataFrame,
) -> pd.DataFrame:
    calendar_index = pd.date_range(
        min(kalshi_daily.index.min(), market_targets.index.min()),
        max(kalshi_daily.index.max(), market_targets.index.max()),
        freq="D",
    )
    raw = kalshi_daily.reindex(calendar_index).fillna(0.0)

    features = pd.DataFrame(index=calendar_index)
    features["kalshi_primary_raw"] = raw["kalshi_shock_max_abs"]
    features["kalshi_l1_raw"] = raw["kalshi_shock_l1_sum"]
    features["kalshi_n_events_raw"] = raw["n_events_with_shock"]
    for col in raw.columns:
        if col.endswith("_shock_max_abs"):
            features[col.replace("_shock_max_abs", "_raw")] = raw[col]

    zq_daily = market_targets["fedfunds_futures_abs_change"].reindex(calendar_index).fillna(0.0)
    features["fedfunds_prior_raw"] = zq_daily

    # LOOKAHEAD FIREWALL: all predictors are previous-calendar-day shocks.
    features["kalshi_signal"] = features["kalshi_primary_raw"].shift(1)
    features["kalshi_l1_signal"] = features["kalshi_l1_raw"].shift(1)
    features["fedfunds_prior_signal"] = features["fedfunds_prior_raw"].shift(1)
    for col in [c for c in features.columns if c.endswith("_raw") and c not in {"kalshi_primary_raw", "kalshi_l1_raw", "fedfunds_prior_raw"}]:
        features[col.replace("_raw", "_signal")] = features[col].shift(1)

    panel = market_targets.join(features.reindex(market_targets.index), how="left")
    panel = panel.dropna(subset=["kalshi_signal", "fedfunds_prior_signal"])
    panel.to_csv(HERE / "K1360_daily_panel.csv")
    return panel


def newey_west_regression(
    frame: pd.DataFrame,
    target: str,
    predictors: list[str],
    lags: int = NW_LAG_DAILY,
) -> dict:
    from scipy import stats

    dat = frame[[target] + predictors].replace([np.inf, -np.inf], np.nan).dropna()
    if len(dat) < 30:
        return {
            "n": int(len(dat)),
            "predictors": predictors,
            "error": "too_few_observations",
        }

    y = dat[target].to_numpy(dtype=float)
    x_cols = []
    predictor_stats = {}
    for predictor in predictors:
        x = dat[predictor].to_numpy(dtype=float)
        mean = float(np.mean(x))
        sd = float(np.std(x, ddof=0))
        predictor_stats[predictor] = {
            "raw_mean": mean,
            "raw_sd": sd,
            "raw_min": float(np.min(x)),
            "raw_max": float(np.max(x)),
        }
        if sd <= 0 or not np.isfinite(sd):
            x_cols.append(np.zeros_like(x))
        else:
            x_cols.append((x - mean) / sd)
    X = np.column_stack([np.ones(len(dat))] + x_cols)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta

    xtx_inv = np.linalg.inv(X.T @ X)
    S = np.zeros((X.shape[1], X.shape[1]))
    for t in range(len(dat)):
        xt = X[t : t + 1].T
        S += float(resid[t] ** 2) * (xt @ xt.T)
    max_lag = min(lags, len(dat) - 1)
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        gamma = np.zeros_like(S)
        for t in range(lag, len(dat)):
            gamma += float(resid[t] * resid[t - lag]) * (
                X[t : t + 1].T @ X[t - lag : t - lag + 1]
            )
        S += weight * (gamma + gamma.T)
    cov = xtx_inv @ S @ xtx_inv
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    t_stat = beta / se
    p_values = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stat), df=max(len(dat) - X.shape[1], 1)))

    r2 = 1.0 - float(np.sum(resid**2) / np.sum((y - y.mean()) ** 2)) if np.var(y) > 0 else np.nan
    out = {
        "n": int(len(dat)),
        "target_mean": float(np.mean(y)),
        "target_sd": float(np.std(y, ddof=0)),
        "r2": float(r2),
        "hac_lags": int(max_lag),
        "predictor_stats": predictor_stats,
        "intercept": {
            "beta": float(beta[0]),
            "se": float(se[0]),
            "t": float(t_stat[0]),
            "p": float(p_values[0]),
        },
        "slopes": {},
    }
    for i, predictor in enumerate(predictors, start=1):
        out["slopes"][predictor] = {
            "beta_per_1sd_signal": float(beta[i]),
            "hac_se": float(se[i]),
            "hac_t": float(t_stat[i]),
            "p": float(p_values[i]),
        }
    return out


def top_quintile_diagnostics(frame: pd.DataFrame, target: str, signal: str) -> dict:
    dat = frame[[target, signal]].replace([np.inf, -np.inf], np.nan).dropna()
    dat = dat[dat[signal].notna()]
    if len(dat) < 40 or dat[signal].nunique() < 5:
        return {"n": int(len(dat)), "error": "too_few_effective_observations"}
    cutoff = float(dat[signal].quantile(0.80))
    high = dat[dat[signal] >= cutoff][target]
    low = dat[dat[signal] < cutoff][target]
    from scipy import stats

    t_stat, p_value = stats.ttest_ind(high, low, equal_var=False, nan_policy="omit")
    return {
        "n": int(len(dat)),
        "cutoff": cutoff,
        "top_quintile_n": int(len(high)),
        "rest_n": int(len(low)),
        "top_quintile_mean": float(high.mean()),
        "rest_mean": float(low.mean()),
        "difference": float(high.mean() - low.mean()),
        "welch_t": float(t_stat),
        "welch_p": float(p_value),
    }


def event_study(
    event_daily: pd.DataFrame,
    market_targets: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    rows = []
    event_daily = event_daily.copy()
    event_daily["date"] = pd.to_datetime(event_daily["date"]).dt.normalize()
    for event_ticker, group in event_daily.groupby("event_ticker"):
        anchor_values = group.get("anchor_date")
        if anchor_values is None:
            continue
        anchor_str = next((x for x in anchor_values.dropna().unique() if x), None)
        if not anchor_str:
            continue
        anchor = pd.Timestamp(anchor_str).normalize()
        target_dates = market_targets.index[market_targets.index >= anchor]
        if len(target_dates) == 0:
            continue
        target_date = target_dates[0]
        if target_date > market_targets.index.max():
            continue
        pre = group[group["date"] < anchor].sort_values("date")
        if pre.empty or target_date not in market_targets.index:
            continue
        last_pre = pre.iloc[-1]
        rows.append(
            {
                "event_ticker": event_ticker,
                "event_type": last_pre["event_type"],
                "anchor_date": str(anchor.date()),
                "target_date": str(target_date.date()),
                "pre_event_signal_date": str(pd.Timestamp(last_pre["date"]).date()),
                "pre_event_shock_max_abs": float(last_pre["shock_max_abs"]),
                "pre_event_shock_l1_sum": float(last_pre["shock_l1_sum"]),
                "spy_abs_ret_1d": float(market_targets.at[target_date, "spy_abs_ret_1d"]),
                "spy_left_tail_1d": float(market_targets.at[target_date, "spy_left_tail_1d"]),
                "vix9d_vix_ratio_change": float(
                    market_targets.at[target_date, "vix9d_vix_ratio_change"]
                ),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        summary = {"n_events_with_market_target": 0}
        return table, summary

    from scipy import stats

    summary = {"n_events_with_market_target": int(len(table)), "spearman": {}}
    for target in ["spy_abs_ret_1d", "spy_left_tail_1d", "vix9d_vix_ratio_change"]:
        dat = table[["pre_event_shock_max_abs", target]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(dat) >= 5 and dat["pre_event_shock_max_abs"].nunique() > 1:
            rho, p_value = stats.spearmanr(dat["pre_event_shock_max_abs"], dat[target])
            summary["spearman"][target] = {
                "rho": float(rho),
                "p": float(p_value),
                "n": int(len(dat)),
            }
        else:
            summary["spearman"][target] = {"n": int(len(dat)), "error": "too_few_events"}
    table.to_csv(HERE / "K1360_event_study.csv", index=False)
    return table, summary


def run_tests(panel: pd.DataFrame) -> dict:
    targets = {
        "spy_abs_ret_1d": "next trading day's absolute SPY return, signal lagged one calendar day",
        "spy_rv5_forward": "five-trading-day forward SPY realized volatility beginning on target date",
        "spy_left_tail_1d": "next trading day's positive left-tail loss proxy",
        "vix9d_vix_ratio_change": "one-day change in log(VIX9D/VIX)",
        "vix_log_change_1d": "one-day log change in VIX",
        "vix9d_log_change_1d": "one-day log change in VIX9D",
    }
    models = {}
    top_quintile = {}
    for target in targets:
        models[target] = {
            "description": targets[target],
            "kalshi_only": newey_west_regression(panel, target, ["kalshi_signal"]),
            "fedfunds_prior_only": newey_west_regression(
                panel, target, ["fedfunds_prior_signal"]
            ),
            "combined": newey_west_regression(
                panel, target, ["kalshi_signal", "fedfunds_prior_signal"]
            ),
        }
        top_quintile[target] = top_quintile_diagnostics(panel, target, "kalshi_signal")
    return {"targets": targets, "models": models, "top_quintile": top_quintile}


def verdict_from_results(results: dict) -> tuple[str, dict]:
    data = results["data"]
    tests = results["tests"]["models"]
    kalshi_pass = []
    kalshi_weak = []
    for target, block in tests.items():
        slope = block["kalshi_only"].get("slopes", {}).get("kalshi_signal", {})
        beta = slope.get("beta_per_1sd_signal", float("nan"))
        t_stat = slope.get("hac_t", float("nan"))
        if np.isfinite(beta) and np.isfinite(t_stat) and beta > 0.0 and t_stat >= HARVEY_T:
            kalshi_pass.append(target)
        elif np.isfinite(beta) and np.isfinite(t_stat) and beta > 0.0 and t_stat >= 2.0:
            kalshi_weak.append(target)

    polymarket_ok = bool(data["polymarket_probe"]["ok"])
    n_obs = min(block["kalshi_only"].get("n", 0) for block in tests.values())
    n_events = data["kalshi"]["selected_events"]

    if kalshi_pass and polymarket_ok and n_events >= 20 and n_obs >= 180:
        verdict = "CONDITIONAL_SUPPORT_PREDICTION_MARKET_VOL_PRIOR"
    elif kalshi_pass:
        verdict = "KALSHI_ONLY_DIAGNOSTIC_SUPPORT_UNDERPOWERED"
    elif kalshi_weak:
        verdict = "WEAK_KALSHI_DIAGNOSTIC_UNDERPOWERED"
    else:
        verdict = "DATA_FEASIBLE_UNDERPOWERED_NULL"

    decision = {
        "kalshi_positive_t_ge_3_targets": kalshi_pass,
        "kalshi_positive_t_ge_2_targets": kalshi_weak,
        "polymarket_ok": polymarket_ok,
        "minimum_daily_regression_n": int(n_obs),
        "selected_kalshi_events": int(n_events),
        "claim_rule": (
            "A support claim requires positive Kalshi lagged-shock slope with HAC t>=3, "
            "usable Polymarket or a pre-specified cross-market replication, >=20 events, "
            "and >=180 daily observations. Otherwise results stay diagnostic."
        ),
    }
    return verdict, decision


def make_figures(panel: pd.DataFrame, tests: dict) -> list[str]:
    figures = []
    plot_panel = panel[["kalshi_signal", "vix9d_vix_log_ratio"]].dropna()
    if not plot_panel.empty:
        fig, ax1 = plt.subplots(figsize=(10, 4.8))
        ax1.plot(
            plot_panel.index,
            plot_panel["kalshi_signal"],
            color="#2563eb",
            linewidth=1.2,
            label="Kalshi lagged shock",
        )
        ax1.set_ylabel("Kalshi signal, probability points")
        ax2 = ax1.twinx()
        ax2.plot(
            plot_panel.index,
            plot_panel["vix9d_vix_log_ratio"],
            color="#dc2626",
            linewidth=1.0,
            alpha=0.80,
            label="log(VIX9D/VIX)",
        )
        ax2.set_ylabel("log(VIX9D/VIX)")
        ax1.set_title("K1360 lagged Kalshi shock and short-vol term structure")
        lines, labels = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines + lines2, labels + labels2, loc="upper left", frameon=False)
        fig.tight_layout()
        path = FIG_DIR / "k1360_signal_vix9d_ratio.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figures.append(str(path.relative_to(HERE)))

    targets = list(tests["models"].keys())
    kalshi_t = [
        tests["models"][target]["kalshi_only"].get("slopes", {})
        .get("kalshi_signal", {})
        .get("hac_t", np.nan)
        for target in targets
    ]
    fed_t = [
        tests["models"][target]["fedfunds_prior_only"].get("slopes", {})
        .get("fedfunds_prior_signal", {})
        .get("hac_t", np.nan)
        for target in targets
    ]
    x = np.arange(len(targets))
    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    width = 0.38
    ax.bar(x - width / 2, kalshi_t, width=width, color="#2563eb", label="Kalshi lag shock")
    ax.bar(x + width / 2, fed_t, width=width, color="#64748b", label="ZQ=F lag shock")
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.axhline(3.0, color="#16a34a", linewidth=0.8, linestyle="--")
    ax.axhline(-3.0, color="#16a34a", linewidth=0.8, linestyle="--")
    ax.set_xticks(x, labels=targets, rotation=25, ha="right")
    ax.set_ylabel("Newey-West HAC t-stat")
    ax.set_title("K1360 one-standard-deviation signal slopes")
    ax.legend(frameon=False)
    fig.tight_layout()
    path = FIG_DIR / "k1360_hac_tstats.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    figures.append(str(path.relative_to(HERE)))
    return figures


def run_experiment(refresh: bool = False) -> dict:
    np.random.seed(SEED)
    polymarket = probe_polymarket(refresh)
    kalshi_daily, kalshi_event_daily, kalshi_meta = build_kalshi_panel(refresh)
    market_targets, market_meta = load_market_targets(refresh)
    panel = build_analysis_panel(kalshi_daily, market_targets)
    tests = run_tests(panel)
    event_table, event_summary = event_study(kalshi_event_daily, market_targets)
    figures = make_figures(panel, tests)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Prediction-market implied probability shock as macro event volatility prior",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "methodology_type": "empirical_public_api_feasibility_and_lagged_time_series_diagnostic",
        "data": {
            "polymarket_probe": polymarket,
            "kalshi": kalshi_meta,
            "market_targets": market_meta,
            "analysis_panel": {
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "n_market_trading_days": int(len(panel)),
                "nonzero_kalshi_signal_days": int((panel["kalshi_signal"] > 0.0).sum()),
                "nonzero_fedfunds_signal_days": int((panel["fedfunds_prior_signal"] > 0.0).sum()),
            },
        },
        "config": {
            "seed": SEED,
            "analysis_start": str(ANALYSIS_START.date()),
            "kalshi_series": KALSHI_SERIES,
            "max_markets_per_event": MAX_MARKETS_PER_EVENT,
            "min_event_market_score": MIN_EVENT_VOLUME,
            "nw_lag_daily": NW_LAG_DAILY,
            "timing_rule": "Kalshi daily probability shock at calendar date t-1 predicts market target at trading date t via signal.shift(1)",
            "primary_inference_unit": "daily time series after event-market shocks are aggregated to calendar days",
            "baseline": "ZQ=F yfinance 30-Day Fed Funds futures absolute price change, lagged one calendar day; this is FedWatch-like, not the full CME FedWatch probability table",
            "harvey_threshold": "|t| >= 3 required for discovery-style volatility-prior claims",
        },
        "literature": LITERATURE,
        "tests": tests,
        "event_study": event_summary,
        "figures": figures,
        "artifacts": {
            "daily_panel": "K1360_daily_panel.csv",
            "event_study": "K1360_event_study.csv" if not event_table.empty else None,
            "kalshi_selected_events": "data/kalshi_selected_events.csv",
            "kalshi_market_panel": "data/kalshi_market_panel.csv",
            "kalshi_event_daily": "data/kalshi_event_daily.csv",
            "market_targets": "data/market_targets.csv",
        },
        "limitations": [
            "Polymarket public endpoint returned a Taiwan domain-block HTML page in this environment, so Polymarket is excluded from empirical claims.",
            "Kalshi public event-detail endpoints returned usable markets only for a subset of 2026 macro events; older 2025 events were listed but often had zero markets in the public detail response.",
            "The FedWatch comparison uses yfinance ZQ=F 30-Day Fed Funds futures price changes as a free baseline, not CME's full historical FedWatch probability API.",
            "Daily Kalshi candles are end-of-day public API aggregates; no intraday timestamp alignment with US equity close is attempted, so all signals are shifted by one calendar day.",
            "Forward five-day SPY RV targets overlap; Newey-West lag 5 is used, but this remains a diagnostic rather than a launch-ready forecast model.",
        ],
    }
    verdict, decision = verdict_from_results(results)
    results["verdict"] = verdict
    results["decision"] = decision

    (HERE / "K1360_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh API/yfinance caches")
    args = parser.parse_args()
    results = run_experiment(refresh=args.refresh)
    summary = {
        "experiment_id": results["experiment_id"],
        "verdict": results["verdict"],
        "period": [
            results["data"]["analysis_panel"]["start"],
            results["data"]["analysis_panel"]["end"],
        ],
        "n_market_trading_days": results["data"]["analysis_panel"]["n_market_trading_days"],
        "selected_kalshi_events": results["data"]["kalshi"]["selected_events"],
        "selected_kalshi_markets": results["data"]["kalshi"]["selected_markets"],
        "polymarket_blocked": results["data"]["polymarket_probe"][
            "blocked_domain_page_detected"
        ],
        "kalshi_t_ge_3_targets": results["decision"]["kalshi_positive_t_ge_3_targets"],
        "kalshi_t_ge_2_targets": results["decision"]["kalshi_positive_t_ge_2_targets"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
