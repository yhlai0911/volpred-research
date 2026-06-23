#!/usr/bin/env python3
"""K1363: Fedspeak forecast-revision shocks as equity/bond tail-vol priors.

This is a public-data dictionary pilot, not a replication of the multimodal NLP
model in the motivating literature. It fetches official Federal Reserve speech
pages and FOMC calendar pages, scores speeches for growth / inflation / labor
forecast-revision language, then tests whether the lagged signal adds to simple
HAR-style daily volatility proxies for SPY, TLT, IEF, and QQQ.

Lookahead protection
--------------------
Official speech text observed on calendar day t is first mapped to the next
available trading day at or after t, then every text signal is used through
`signal.shift(1)`. All HAR controls also use lagged daily returns only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
import urllib.request
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RAW_DIR = DATA_DIR / "raw"
FIG_DIR = HERE / "figures"
for directory in (DATA_DIR, RAW_DIR, FIG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

EXPERIMENT_ID = "K1363"
SEED = 42
np.random.seed(SEED)

START = "2020-01-01"
END = "2026-06-24"
CURRENT_DATE = pd.Timestamp("2026-06-23")
FED_YEARS = list(range(2020, 2027))
ROLL_Z = 126
HAC_LAGS = 5
HARVEY_T = 3.0
EPS = 1e-12

ASSETS: "OrderedDict[str, dict[str, str]]" = OrderedDict(
    [
        ("SPY", {"label": "US equities"}),
        ("QQQ", {"label": "Nasdaq growth equities"}),
        ("TLT", {"label": "long-duration Treasuries"}),
        ("IEF", {"label": "intermediate Treasuries"}),
    ]
)

FED_BASE = "https://www.federalreserve.gov"
SPEECH_INDEX_URL = FED_BASE + "/newsevents/speech/{year}-speeches.htm"
FOMC_CALENDAR_URL = FED_BASE + "/monetarypolicy/fomccalendars.htm"

LITERATURE = [
    {
        "citation": "Gorodnichenko, Pham, and Talavera (2023/2025), Mind Your Language: Market Responses to Central Bank Speeches, Journal of Econometrics",
        "url": "https://ideas.repec.org/a/eee/econom/v249y2025ipcs0304407624002720.html",
        "role": "direct motivation: speech-implied forecast revisions can explain equity and bond volatility and tail risk",
    },
    {
        "citation": "Jefferson (2025), Reading between the Lines? Textual Analysis of Central Bank Communications",
        "url": "https://www.federalreserve.gov/newsevents/speech/jefferson20250221a.htm",
        "role": "official Fed discussion of textual analysis and central-bank communication effects on markets",
    },
    {
        "citation": "Swanson and Jayawickrema (2024), Speeches by the Fed Chair Are More Important Than FOMC Announcements",
        "url": "https://sites.uci.edu/swanson/files/2024/07/speeches.pdf",
        "role": "motivates chair-weighted speech signal and between-meeting communication channel",
    },
    {
        "citation": "Cieslak and Schrimpf (2019), Non-monetary News in Central Bank Communication",
        "url": "https://www.bis.org/publ/work780.htm",
        "role": "central-bank communication can carry growth and inflation news beyond the pure policy-rate shock",
    },
]

CATEGORY_TERMS = {
    "growth": [
        "growth",
        "gdp",
        "economic activity",
        "output",
        "productivity",
        "demand",
        "spending",
        "investment",
        "business activity",
        "consumer spending",
    ],
    "inflation": [
        "inflation",
        "prices",
        "price pressures",
        "price pressure",
        "pce",
        "cpi",
        "disinflation",
        "costs",
        "cost pressures",
        "inflation expectations",
    ],
    "labor": [
        "labor",
        "labour",
        "employment",
        "unemployment",
        "jobs",
        "job growth",
        "payroll",
        "payrolls",
        "wage",
        "wages",
        "hiring",
        "workers",
        "labor market",
    ],
}

UP_TERMS = [
    "strong",
    "strength",
    "robust",
    "solid",
    "resilient",
    "accelerat",
    "expand",
    "increase",
    "increasing",
    "higher",
    "rise",
    "rising",
    "upside",
    "improv",
    "tight",
    "elevated",
    "persistent",
    "above",
    "hot",
]

DOWN_TERMS = [
    "weak",
    "soft",
    "slow",
    "slowing",
    "declin",
    "decrease",
    "fall",
    "falling",
    "lower",
    "downside",
    "recession",
    "contract",
    "deteriorat",
    "eas",
    "cool",
    "moderate",
    "subdued",
    "below",
]

OUTLOOK_TERMS = [
    "outlook",
    "forecast",
    "projection",
    "project",
    "expect",
    "anticipated",
    "likely",
    "future",
    "prospect",
]


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if not math.isfinite(value) else value
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _clean_float(value: Any) -> float | None:
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return None
    return fval if math.isfinite(fval) else None


def _safe_filename(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", url).strip("_")[:180]


def _speech_url_date(url: str) -> pd.Timestamp | None:
    match = re.search(r"(\d{8})[a-z]?\.htm", url)
    if not match:
        return None
    try:
        return pd.Timestamp(match.group(1)).normalize()
    except Exception:
        return None


def _urlopen_text(url: str, timeout: int = 30) -> str:
    headers = {
        "User-Agent": "volpred-k1363/1.0 (+research; contact=local)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _read_or_fetch_text(url: str, cache_name: str, refresh: bool = False) -> str:
    path = RAW_DIR / cache_name
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8", errors="replace")
    text = _urlopen_text(url)
    path.write_text(text, encoding="utf-8")
    time.sleep(0.05)
    return text


def html_to_text(fragment: str) -> str:
    fragment = re.sub(r"(?is)<script.*?</script>", " ", fragment)
    fragment = re.sub(r"(?is)<style.*?</style>", " ", fragment)
    fragment = re.sub(r"(?is)<noscript.*?</noscript>", " ", fragment)
    fragment = re.sub(r"(?is)<sup.*?</sup>", " ", fragment)
    fragment = re.sub(r"(?is)<a\s+name=[^>]+></a>", " ", fragment)
    fragment = re.sub(r"(?is)<br\s*/?>", ". ", fragment)
    fragment = re.sub(r"(?is)</p>|</li>|</div>|</h[1-6]>", ". ", fragment)
    text = re.sub(r"(?is)<[^>]+>", " ", fragment)
    text = unescape(text)
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_regex(pattern: str, text: str, flags: int = re.I | re.S) -> str | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return html_to_text(match.group(1))


def parse_speech_page(url: str, html: str) -> dict[str, Any] | None:
    date_text = _extract_regex(r"<p class=['\"]article__time['\"]>(.*?)</p>", html)
    title = _extract_regex(r"<h3 class=['\"]title['\"]>(.*?)</h3>", html)
    speaker = _extract_regex(r"<p class=['\"]speaker['\"]>(.*?)</p>", html)
    location = _extract_regex(r"<p class=['\"]location['\"]>(.*?)</p>", html) or ""

    if not date_text or not title:
        return None
    try:
        date = pd.Timestamp(date_text).normalize()
    except Exception:
        return None
    if date > CURRENT_DATE:
        return None

    marker = '<div class="col-xs-12 col-sm-8 col-md-8">'
    body_start = html.find(marker, html.find("<div id=\"article\""))
    if body_start != -1:
        body_start = html.find(marker, body_start + len(marker))
    if body_start == -1:
        body_start = html.find(marker)
    if body_start == -1:
        body_html = html
    else:
        body_end_candidates = [
            html.find("Last Update:", body_start + len(marker)),
            html.find("<footer", body_start + len(marker)),
            html.find("<!-- / .container -->", body_start + len(marker)),
        ]
        body_end_candidates = [idx for idx in body_end_candidates if idx != -1]
        body_end = min(body_end_candidates) if body_end_candidates else len(html)
        body_html = html[body_start:body_end]

    body_html = re.split(r"(?is)<p>\s*<strong>\s*References", body_html)[0]
    body_html = re.split(r"(?is)<hr[^>]*>", body_html)[0]
    body = html_to_text(body_html)
    word_count = len(re.findall(r"[A-Za-z]+", body))
    if word_count < 250:
        return None

    speaker_text = speaker or ""
    speaker_l = speaker_text.lower()
    chair_weight = 1.0
    if "chair" in speaker_l and "vice chair" not in speaker_l:
        chair_weight = 1.5
    elif "vice chair" in speaker_l:
        chair_weight = 1.2

    scores = score_speech_text(body)
    return {
        "date": date,
        "url": url,
        "title": title,
        "speaker": speaker_text,
        "location": location,
        "word_count": int(word_count),
        "chair_weight": float(chair_weight),
        **scores,
    }


def collect_speech_links(refresh: bool = False) -> list[str]:
    links: list[str] = []
    seen = set()
    for year in FED_YEARS:
        url = SPEECH_INDEX_URL.format(year=year)
        html = _read_or_fetch_text(url, f"fed_speech_index_{year}.html", refresh)
        for href in re.findall(r"href=['\"](/newsevents/speech/[^'\"]+\.htm)['\"]", html):
            full = FED_BASE + href
            url_date = _speech_url_date(full)
            if url_date is not None and url_date > CURRENT_DATE:
                continue
            if full not in seen:
                seen.add(full)
                links.append(full)
    return links


def fetch_speeches(refresh: bool = False, limit: int | None = None) -> pd.DataFrame:
    links = collect_speech_links(refresh)
    if limit:
        links = links[:limit]

    def load_parse(url: str) -> dict[str, Any] | None:
        cache_name = f"fed_speech_{_safe_filename(url)}.html"
        try:
            html = _read_or_fetch_text(url, cache_name, refresh)
            return parse_speech_page(url, html)
        except Exception as exc:
            return {
                "date": pd.NaT,
                "url": url,
                "title": None,
                "speaker": None,
                "word_count": 0,
                "parse_error": repr(exc),
            }

    records = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        for i, parsed in enumerate(executor.map(load_parse, links), start=1):
            if parsed is not None:
                records.append(parsed)
            if i % 25 == 0:
                print(f"[fed] processed {i}/{len(links)} speech links", flush=True)
    if len(links) % 25:
        print(f"[fed] processed {len(links)}/{len(links)} speech links", flush=True)

    df = pd.DataFrame(records)
    if df.empty:
        raise RuntimeError("No Federal Reserve speeches parsed")
    df = df.dropna(subset=["date", "title"]).sort_values(["date", "url"])
    df = df.loc[df["date"].between(pd.Timestamp(START), CURRENT_DATE)].copy()
    df.to_csv(DATA_DIR / "K1363_speech_corpus.csv", index=False)
    return df


def _count_terms(text: str, terms: list[str]) -> int:
    total = 0
    for term in terms:
        if " " in term:
            total += text.count(term)
        else:
            total += len(re.findall(rf"\b{re.escape(term)}", text))
    return int(total)


def score_speech_text(text: str) -> dict[str, float]:
    sentences = re.split(r"(?<=[.!?])\s+", text.lower())
    scores = {f"{category}_revision": 0.0 for category in CATEGORY_TERMS}
    scores.update({f"{category}_mentions": 0.0 for category in CATEGORY_TERMS})
    scores.update({f"{category}_outlook_mentions": 0.0 for category in CATEGORY_TERMS})
    sentence_count = 0
    outlook_count = 0

    for sentence in sentences:
        if len(sentence) < 20:
            continue
        sentence_count += 1
        up = _count_terms(sentence, UP_TERMS)
        down = _count_terms(sentence, DOWN_TERMS)
        outlook = _count_terms(sentence, OUTLOOK_TERMS)
        if outlook > 0:
            outlook_count += 1
        tone = float(up - down)
        for category, terms in CATEGORY_TERMS.items():
            cat_hits = _count_terms(sentence, terms)
            if cat_hits <= 0:
                continue
            scores[f"{category}_mentions"] += float(cat_hits)
            if outlook > 0:
                scores[f"{category}_outlook_mentions"] += float(cat_hits)
            if tone != 0.0:
                multiplier = 1.0 + 0.25 * min(outlook, 2)
                scores[f"{category}_revision"] += tone * multiplier

    denom = max(1.0, len(re.findall(r"[A-Za-z]+", text)) / 1000.0)
    for key in list(scores):
        scores[key] = float(scores[key] / denom)
    scores["sentence_count"] = float(sentence_count)
    scores["outlook_sentence_share"] = float(outlook_count / max(sentence_count, 1))
    scores["forecast_revision_shock"] = float(
        abs(scores["growth_revision"])
        + abs(scores["inflation_revision"])
        + abs(scores["labor_revision"])
    )
    return scores


def parse_fomc_calendar(refresh: bool = False) -> pd.DataFrame:
    html = _read_or_fetch_text(FOMC_CALENDAR_URL, "fed_fomc_calendars.html", refresh)
    text = html_to_text(html)
    records = []

    for month, start_day, end_day, year in re.findall(
        r"\b([A-Z][a-z]+)\s+(\d{1,2})-(\d{1,2}),\s+(20\d{2})\b", text
    ):
        try:
            date = pd.Timestamp(f"{month} {end_day}, {year}").normalize()
            records.append({"date": date, "source": "range_end"})
        except Exception:
            pass

    for month, day, year in re.findall(
        r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s+(20\d{2})\b", text
    ):
        try:
            date = pd.Timestamp(f"{month} {day}, {year}").normalize()
        except Exception:
            continue
        if pd.Timestamp(START) <= date <= CURRENT_DATE:
            records.append({"date": date, "source": "single_date"})

    out = pd.DataFrame(records).drop_duplicates(subset=["date"]).sort_values("date")
    out = out.loc[out["date"].between(pd.Timestamp(START), CURRENT_DATE)].copy()
    out.to_csv(DATA_DIR / "K1363_fomc_calendar.csv", index=False)
    return out


def exclude_fomc_window(speeches: pd.DataFrame, fomc: pd.DataFrame) -> pd.DataFrame:
    if fomc.empty:
        speeches["near_fomc_window"] = False
        return speeches
    fomc_dates = pd.to_datetime(fomc["date"]).dt.normalize()
    excluded = set()
    for dt in fomc_dates:
        for offset in (-1, 0, 1):
            excluded.add((dt + pd.offsets.BDay(offset)).normalize())
    out = speeches.copy()
    out["near_fomc_window"] = out["date"].dt.normalize().isin(excluded)
    return out.loc[~out["near_fomc_window"]].copy()


def fetch_ohlcv(refresh: bool = False) -> dict[str, pd.DataFrame]:
    tickers = list(ASSETS.keys())
    cached = {
        ticker: RAW_DIR / f"{ticker}_{START}_{END}_ohlcv.csv"
        for ticker in tickers
    }
    if not refresh and all(path.exists() for path in cached.values()):
        frames = {}
        for ticker, path in cached.items():
            frames[ticker] = pd.read_csv(path, parse_dates=["Date"], index_col="Date").sort_index()
        return frames

    print(f"[fetch] yfinance {tickers} {START} -> {END}", flush=True)
    downloaded = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    frames: dict[str, pd.DataFrame] = {}
    for ticker, path in cached.items():
        if isinstance(downloaded.columns, pd.MultiIndex):
            if ticker in downloaded.columns.get_level_values(0):
                frame = downloaded[ticker].copy()
            else:
                frame = downloaded.xs(ticker, axis=1, level=1).copy()
        else:
            frame = downloaded.copy()
        frame = frame[[c for c in ["Open", "High", "Low", "Close", "Volume"] if c in frame.columns]]
        if set(frame.columns) != {"Open", "High", "Low", "Close", "Volume"}:
            raise RuntimeError(f"Missing OHLCV columns for {ticker}")
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        frame = frame.dropna(subset=["Open", "High", "Low", "Close"]).sort_index()
        frame.to_csv(path, index_label="Date")
        frames[ticker] = frame
    return frames


def rolling_zscore(series: pd.Series, window: int = ROLL_Z) -> pd.Series:
    mean = series.rolling(window, min_periods=max(20, window // 2)).mean()
    std = series.rolling(window, min_periods=max(20, window // 2)).std()
    return (series - mean) / std.replace(0.0, np.nan)


def align_speech_signals(speeches: pd.DataFrame, trading_index: pd.DatetimeIndex) -> pd.DataFrame:
    trading = pd.DatetimeIndex(pd.to_datetime(trading_index).tz_localize(None)).sort_values()
    raw_cols = [
        "forecast_revision_shock",
        "growth_revision",
        "inflation_revision",
        "labor_revision",
    ]
    out = pd.DataFrame(index=trading)
    for col in raw_cols:
        out[col + "_raw"] = 0.0
    out["speech_count_raw"] = 0.0
    out["chair_weighted_shock_raw"] = 0.0

    for _, row in speeches.iterrows():
        date = pd.Timestamp(row["date"]).normalize()
        pos = trading.searchsorted(date)
        if pos >= len(trading):
            continue
        trade_date = trading[pos]
        for col in raw_cols:
            out.loc[trade_date, col + "_raw"] += float(row.get(col, 0.0))
        out.loc[trade_date, "speech_count_raw"] += 1.0
        out.loc[trade_date, "chair_weighted_shock_raw"] += float(
            row.get("chair_weight", 1.0)
        ) * float(row.get("forecast_revision_shock", 0.0))

    z_cols = [
        "forecast_revision_shock_raw",
        "chair_weighted_shock_raw",
        "growth_revision_raw",
        "inflation_revision_raw",
        "labor_revision_raw",
        "speech_count_raw",
    ]
    for col in z_cols:
        z = rolling_zscore(out[col].fillna(0.0), ROLL_Z).fillna(0.0)
        out[col.replace("_raw", "_z_l1")] = z.shift(1).fillna(0.0)

    out.to_csv(DATA_DIR / "K1363_daily_speech_signal.csv", index_label="Date")
    return out


def build_asset_panel(ticker: str, frame: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    ret = np.log(close).diff()
    rv = ret.pow(2).clip(lower=EPS)
    range_var = (np.log(high / low).pow(2) / (4.0 * np.log(2.0))).clip(lower=EPS)
    fwd5_rv = rv.rolling(5).sum().shift(-4).clip(lower=EPS)
    fwd5_ret = ret.rolling(5).sum().shift(-4)
    left_tail_threshold = float(fwd5_ret.dropna().quantile(0.05))

    out = pd.DataFrame(index=df.index)
    out["ticker"] = ticker
    out["ret"] = ret
    out["log_rv_1d"] = np.log(rv)
    out["log_range_var"] = np.log(range_var)
    out["log_forward5_rv"] = np.log(fwd5_rv)
    out["left_tail5"] = (fwd5_ret <= left_tail_threshold).astype(float)
    out.loc[fwd5_ret.isna(), "left_tail5"] = np.nan

    log_rv = out["log_rv_1d"]
    out["har_d_l1"] = log_rv.shift(1)
    out["har_w_l1"] = log_rv.shift(1).rolling(5, min_periods=5).mean()
    out["har_m_l1"] = log_rv.shift(1).rolling(22, min_periods=22).mean()
    out["range_l1"] = out["log_range_var"].shift(1)
    joined = out.join(signals, how="left").fillna(
        {
            "forecast_revision_shock_z_l1": 0.0,
            "chair_weighted_shock_z_l1": 0.0,
            "growth_revision_z_l1": 0.0,
            "inflation_revision_z_l1": 0.0,
            "labor_revision_z_l1": 0.0,
            "speech_count_z_l1": 0.0,
        }
    )
    joined.attrs["left_tail_threshold"] = left_tail_threshold
    return joined


def standardize(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    std = s.std(ddof=0)
    if not math.isfinite(std) or std == 0.0:
        return s * np.nan
    return (s - s.mean()) / std


def fit_ols_hac(
    panel: pd.DataFrame,
    target: str,
    signal_col: str,
    controls: list[str],
    binary_target: bool = False,
) -> dict[str, Any]:
    cols = [target, signal_col, *controls]
    data = panel[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if data.empty or len(data) < 252:
        return {
            "status": "too_few_observations",
            "n": int(len(data)),
            "target": target,
            "signal": signal_col,
        }

    y = data[target].astype(float)
    if not binary_target:
        y = standardize(y)
    x = pd.DataFrame(index=data.index)
    x[signal_col] = standardize(data[signal_col])
    for control in controls:
        x[control] = standardize(data[control])
    x = x.replace([np.inf, -np.inf], np.nan).dropna()
    y = y.loc[x.index]
    x = sm.add_constant(x)

    if len(x) < 252:
        return {
            "status": "too_few_observations_after_standardization",
            "n": int(len(x)),
            "target": target,
            "signal": signal_col,
        }

    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    coef = float(model.params[signal_col])
    tval = float(model.tvalues[signal_col])
    pval = float(model.pvalues[signal_col])
    return {
        "status": "ok",
        "n": int(model.nobs),
        "start": x.index.min().date().isoformat(),
        "end": x.index.max().date().isoformat(),
        "target": target,
        "signal": signal_col,
        "binary_target": bool(binary_target),
        "coef_per_1sd_signal": coef,
        "hac_t": tval,
        "p_value": pval,
        "r2": float(model.rsquared),
        "harvey_positive_pass": bool(tval >= HARVEY_T),
        "harvey_abs_pass": bool(abs(tval) >= HARVEY_T),
    }


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    n = len(pvalues)
    if n == 0:
        return []
    order = np.argsort(np.asarray(pvalues))
    q = np.empty(n, dtype=float)
    prev = 1.0
    for rank, idx in enumerate(order[::-1], start=1):
        original_rank = n - rank + 1
        val = min(prev, pvalues[idx] * n / original_rank)
        q[idx] = val
        prev = val
    return [float(min(max(v, 0.0), 1.0)) for v in q]


def run_regressions(asset_panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    signal_cols = [
        "forecast_revision_shock_z_l1",
        "chair_weighted_shock_z_l1",
        "growth_revision_z_l1",
        "inflation_revision_z_l1",
        "labor_revision_z_l1",
        "speech_count_z_l1",
    ]
    targets = [
        ("log_rv_1d", False),
        ("log_forward5_rv", False),
        ("left_tail5", True),
    ]
    controls = ["har_d_l1", "har_w_l1", "har_m_l1", "range_l1"]
    rows = []
    for ticker, panel in asset_panels.items():
        for signal_col in signal_cols:
            for target, binary in targets:
                result = fit_ols_hac(panel, target, signal_col, controls, binary)
                result["ticker"] = ticker
                result["asset_label"] = ASSETS[ticker]["label"]
                result["primary"] = bool(signal_col == "forecast_revision_shock_z_l1")
                rows.append(result)
    table = pd.DataFrame(rows)
    ok = table["status"].eq("ok")
    table["bh_q_all"] = np.nan
    if ok.any():
        table.loc[ok, "bh_q_all"] = benjamini_hochberg(
            [float(v) for v in table.loc[ok, "p_value"]]
        )
    primary = ok & table["primary"].astype(bool)
    table["bh_q_primary"] = np.nan
    if primary.any():
        table.loc[primary, "bh_q_primary"] = benjamini_hochberg(
            [float(v) for v in table.loc[primary, "p_value"]]
        )
    table["positive_discovery_pass"] = (
        table["primary"].fillna(False).astype(bool)
        & table["status"].eq("ok")
        & (table["hac_t"] >= HARVEY_T)
        & (table["bh_q_primary"] <= 0.05)
    )
    table.to_csv(HERE / "K1363_regression_table.csv", index=False)
    return table


def top_quintile_diagnostics(asset_panels: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows = []
    for ticker, panel in asset_panels.items():
        data = panel[["forecast_revision_shock_z_l1", "log_forward5_rv", "left_tail5"]].dropna()
        if len(data) < 252:
            continue
        positive_signal = data.loc[data["forecast_revision_shock_z_l1"] > 0.0]
        if len(positive_signal) < 20:
            continue
        threshold = positive_signal["forecast_revision_shock_z_l1"].quantile(0.8)
        top = data.loc[data["forecast_revision_shock_z_l1"] >= threshold]
        rest = data.loc[data["forecast_revision_shock_z_l1"] < threshold]
        if len(top) < 20 or len(rest) < 20:
            continue
        top_rv = np.exp(top["log_forward5_rv"])
        rest_rv = np.exp(rest["log_forward5_rv"])
        tstat, pval = stats.ttest_ind(top_rv, rest_rv, equal_var=False, nan_policy="omit")
        rows.append(
            {
                "ticker": ticker,
                "n_top": int(len(top)),
                "n_rest": int(len(rest)),
                "threshold_definition": "80th percentile among positive lagged speech-shock z-signal days",
                "signal_top_quintile_threshold": float(threshold),
                "top_forward5_rv_mean": float(top_rv.mean()),
                "rest_forward5_rv_mean": float(rest_rv.mean()),
                "diff_forward5_rv_mean": float(top_rv.mean() - rest_rv.mean()),
                "welch_t": _clean_float(tstat),
                "welch_p": _clean_float(pval),
                "top_left_tail_rate": float(top["left_tail5"].mean()),
                "rest_left_tail_rate": float(rest["left_tail5"].mean()),
            }
        )
    pd.DataFrame(rows).to_csv(HERE / "K1363_top_quintile_diagnostics.csv", index=False)
    return rows


def make_plots(reg_table: pd.DataFrame, signals: pd.DataFrame, asset_panels: dict[str, pd.DataFrame]) -> list[str]:
    paths = []
    primary = reg_table.loc[reg_table["primary"].fillna(False) & reg_table["status"].eq("ok")].copy()
    if not primary.empty:
        pivot = primary.pivot(index="ticker", columns="target", values="hac_t").reindex(list(ASSETS.keys()))
        fig, ax = plt.subplots(figsize=(8.5, 4.6))
        im = ax.imshow(pivot.values.astype(float), cmap="coolwarm", vmin=-4, vmax=4)
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns, rotation=25, ha="right")
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels(pivot.index)
        for i in range(pivot.shape[0]):
            for j in range(pivot.shape[1]):
                val = pivot.values[i, j]
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=9)
        ax.set_title("K1363 primary Fedspeak shock: HAC t-stat by asset and target")
        cbar = fig.colorbar(im, ax=ax)
        cbar.set_label("HAC t-stat")
        fig.tight_layout()
        path = FIG_DIR / "k1363_primary_hac_tstats.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(HERE)))

    if "SPY" in asset_panels:
        spy = asset_panels["SPY"][["log_forward5_rv"]].join(
            signals[["forecast_revision_shock_raw", "forecast_revision_shock_z_l1"]],
            how="left",
        )
        fig, axes = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True)
        axes[0].bar(
            spy.index,
            spy["forecast_revision_shock_raw"].fillna(0.0),
            width=2.5,
            color="#4C78A8",
        )
        axes[0].set_ylabel("Raw text shock")
        axes[0].set_title("K1363 official Fed speech shock and SPY forward 5d RV proxy")
        axes[1].plot(spy.index, np.exp(spy["log_forward5_rv"]), color="#E45756", lw=1.0)
        axes[1].set_ylabel("SPY fwd 5d RV")
        axes[1].set_xlabel("Date")
        fig.tight_layout()
        path = FIG_DIR / "k1363_signal_timeline_spy.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(HERE)))

    return paths


def summarize(
    speeches_all: pd.DataFrame,
    speeches_between: pd.DataFrame,
    fomc: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    reg_table: pd.DataFrame,
    top_quintile: list[dict[str, Any]],
    figures: list[str],
) -> dict[str, Any]:
    ok = reg_table.loc[reg_table["status"].eq("ok")].copy()
    primary = ok.loc[ok["primary"].astype(bool)].copy()
    n_positive_harvey = int((primary["hac_t"] >= HARVEY_T).sum())
    n_abs_harvey = int((primary["hac_t"].abs() >= HARVEY_T).sum())
    n_positive_discovery = int(primary["positive_discovery_pass"].sum())

    if n_positive_discovery >= 2:
        verdict = "SUPPORTED_PUBLIC_DICTIONARY_PROXY"
    elif n_positive_harvey >= 1 or n_abs_harvey >= 2:
        verdict = "CONDITIONAL_PASS_DIAGNOSTIC"
    else:
        verdict = "NULL_PUBLIC_DICTIONARY_PROXY"

    top_primary = (
        primary.sort_values("hac_t", ascending=False)
        .head(8)
        .to_dict(orient="records")
    )
    bottom_primary = (
        primary.sort_values("hac_t", ascending=True)
        .head(5)
        .to_dict(orient="records")
    )

    asset_samples = {}
    for ticker, frame in frames.items():
        asset_samples[ticker] = {
            "start": frame.index.min().date().isoformat(),
            "end": frame.index.max().date().isoformat(),
            "n_trading_days": int(len(frame)),
        }

    return {
        "experiment_id": EXPERIMENT_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data_sources": {
            "fed_speeches": {
                "source": "Federal Reserve Board official speech pages",
                "index_url_template": SPEECH_INDEX_URL,
                "years_requested": FED_YEARS,
                "parsed_speeches_total": int(len(speeches_all)),
                "between_meeting_speeches_used": int(len(speeches_between)),
                "sample_start": speeches_between["date"].min().date().isoformat()
                if not speeches_between.empty
                else None,
                "sample_end": speeches_between["date"].max().date().isoformat()
                if not speeches_between.empty
                else None,
                "raw_html_cache": "data/raw/fed_speech_*.html is generated locally on rerun; committed trace is the URL-level speech corpus CSV to avoid versioning large official HTML snapshots",
            },
            "fomc_calendar": {
                "source": "Federal Reserve official FOMC calendars",
                "url": FOMC_CALENDAR_URL,
                "parsed_dates": int(len(fomc)),
                "window_excluded": "speech dates within +/-1 business day of parsed FOMC dates",
            },
            "market_data": {
                "source": "yfinance daily adjusted OHLCV, auto_adjust=True",
                "requested_start": START,
                "requested_end_exclusive": END,
                "assets": asset_samples,
                "rv_proxy": "squared log close-to-close returns; range proxy is Parkinson high-low variance",
            },
        },
        "literature": LITERATURE,
        "method": {
            "dictionary_categories": CATEGORY_TERMS,
            "up_terms": UP_TERMS,
            "down_terms": DOWN_TERMS,
            "outlook_terms": OUTLOOK_TERMS,
            "primary_signal": "forecast_revision_shock_z_l1 = rolling z-score of abs(growth/inflation/labor revision tone), then signal.shift(1)",
            "controls": ["har_d_l1", "har_w_l1", "har_m_l1", "range_l1"],
            "targets": ["log_rv_1d", "log_forward5_rv", "left_tail5"],
            "inference": f"OLS-HAC Newey-West maxlags={HAC_LAGS}; Harvey threshold positive t >= {HARVEY_T}",
            "multiple_testing": "Benjamini-Hochberg q-values over all primary asset-target tests and over all tests",
        },
        "lookahead_policy": {
            "speech_alignment": "calendar speech date mapped to next available trading date, then signal.shift(1)",
            "explicit_code_guard": "align_speech_signals() creates *_z_l1 columns using z.shift(1); HAR controls use log_rv.shift(1)",
            "no_same_day_use": True,
        },
        "primary_summary": {
            "n_primary_tests": int(len(primary)),
            "n_positive_harvey_t_ge_3": n_positive_harvey,
            "n_abs_harvey_abs_t_ge_3": n_abs_harvey,
            "n_positive_discovery_pass_t_and_bh_q": n_positive_discovery,
            "top_positive_primary": top_primary,
            "most_negative_primary": bottom_primary,
        },
        "top_quintile_diagnostics": top_quintile,
        "outputs": {
            "speech_corpus_csv": "data/K1363_speech_corpus.csv",
            "fomc_calendar_csv": "data/K1363_fomc_calendar.csv",
            "daily_speech_signal_csv": "data/K1363_daily_speech_signal.csv",
            "regression_table_csv": "K1363_regression_table.csv",
            "top_quintile_csv": "K1363_top_quintile_diagnostics.csv",
            "figures": figures,
        },
        "limitations": [
            "Federal Reserve Board speech pages do not cover every Reserve Bank president speech; this is not a complete FOMC-member corpus.",
            "Dictionary scoring is a transparent proxy, not the paper's multimodal machine-learning forecast-revision model.",
            "Daily OHLCV cannot identify high-frequency event-window reactions and uses close-to-close RV proxies rather than true 5-minute RV.",
            "Forward 5-day targets overlap; HAC maxlags=5 mitigates serial correlation but does not replace non-overlapping robustness.",
            "Speech release times are not used; shifting by one trading day is deliberately conservative.",
        ],
        "claim_rule": "A strong claim requires at least two primary asset-target tests with positive HAC t>=3 and BH q<=0.05. Otherwise results remain diagnostic or null.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh Fed and yfinance caches")
    parser.add_argument("--limit-speeches", type=int, default=None, help="debug limit for speech pages")
    args = parser.parse_args()

    speeches_all = fetch_speeches(refresh=args.refresh, limit=args.limit_speeches)
    fomc = parse_fomc_calendar(refresh=args.refresh)
    speeches_between = exclude_fomc_window(speeches_all, fomc)
    speeches_between.to_csv(DATA_DIR / "K1363_speech_corpus_between_meetings.csv", index=False)

    frames = fetch_ohlcv(refresh=args.refresh)
    trading_index = frames["SPY"].index
    signals = align_speech_signals(speeches_between, trading_index)
    asset_panels = {
        ticker: build_asset_panel(ticker, frame, signals)
        for ticker, frame in frames.items()
    }
    for ticker, panel in asset_panels.items():
        panel.to_csv(DATA_DIR / f"K1363_panel_{ticker}.csv", index_label="Date")

    reg_table = run_regressions(asset_panels)
    top_quintile = top_quintile_diagnostics(asset_panels)
    figures = make_plots(reg_table, signals, asset_panels)

    results = summarize(
        speeches_all,
        speeches_between,
        fomc,
        frames,
        reg_table,
        top_quintile,
        figures,
    )
    out_path = HERE / "K1363_results.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    print(
        f"[{EXPERIMENT_ID}] verdict={results['verdict']} | "
        f"speeches={len(speeches_between)} | primary positive passes="
        f"{results['primary_summary']['n_positive_discovery_pass_t_and_bh_q']} | "
        f"wrote {out_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
