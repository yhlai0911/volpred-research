#!/usr/bin/env python3
"""K1678: public saliency and post-manipulation crash-risk diagnostic.

This is a retrospective, non-causal proxy experiment.  It combines:

* exact ticker-dates labelled "Dates of Manipulative Trading" in Attachment A
  of the SEC's 2026 complaint in SEC v. Harsh V. Patel; and
* daily Wikimedia pageviews for stable manipulation/retail-attention topics.

The SEC complaint was filed after every labelled trading date.  Consequently,
the label is a *weak retrospective stratifier*, never a real-time signal.  The
primary question is narrower: among labelled events, is the event-minus-matched
control increase in future crash risk larger when public saliency is unusually
high?

Timing convention
-----------------
The raw attention shock and SEC event indicator are formed on trading day t.
Both are explicitly shifted one trading row before being attached to targets
starting on t+1.  Every H-day outcome covers t+1,...,t+H.

Seed: 42
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats
from statsmodels.stats.multitest import multipletests


EXPERIMENT_ID = "K1678"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
REPO_ROOT = HERE.parents[1]
PRIOR_WIKI_CACHE_DIR = (
    REPO_ROOT
    / "experiments"
    / "research_anti_stockholder_identity_retail_risk_off_volati"
    / "data"
)
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
SUMMARY_PATH = HERE / f"{EXPERIMENT_ID}_primary_results.csv"
MATCHED_PATH = HERE / f"{EXPERIMENT_ID}_matched_events.csv.gz"
FIGURE_PATH = HERE / f"{EXPERIMENT_ID}_saliency_crash_risk.png"

SEED = 42
np.random.seed(SEED)

START_DATE = "2020-01-01"
END_DATE = "2024-02-16"  # exclusive for yfinance; includes all SEC dates + H=5
PAGEVIEW_START = "20200101"
PAGEVIEW_END = "20240215"
HORIZONS = (1, 5)
OUTCOMES = ("rv", "dsv", "left_tail", "downside_gap")
M_PRIMARY = len(HORIZONS) * len(OUTCOMES)

ROLLING_Z_WINDOW = 126
ROLLING_Z_MIN = 60
MATCH_CONTROLS = 3
MATCH_WINDOW = 252
BOOT_REPS = 2_000
EPS = 1e-12
DETERMINISTIC_GZIP = {"method": "gzip", "compresslevel": 6, "mtime": 0}

USER_AGENT = "volpred-research/1.0 (noncommercial research; repository owner contact)"
SEC_RELEASE_URL = "https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26532"
SEC_COMPLAINT_URL = "https://www.sec.gov/files/litigation/complaints/2026/comp26532.pdf"
SEC_FILED_DATE = "2026-04-20"

PRIMARY_PAGES = (
    "Pump_and_dump",
    "WallStreetBets",
    "Short_squeeze",
    "Day_trading",
    "Robinhood_Markets",
)
EPISODE_PAGES = ("Meme_stock", "GameStop_short_squeeze")
ANCHOR_PAGES = (
    "Stock_market",
    "S&P_500",
    "Nasdaq_Composite",
    "Dow_Jones_Industrial_Average",
    "Investment",
)

MATCH_FEATURES = (
    "ret1_lag1",
    "ret5_lag1",
    "log_rv21_lag1",
    "volume_z_lag1",
    "spy_ret_lag1",
    "vix_z_lag1",
)
REGRESSION_BALANCE_CONTROLS = (
    "ret1_lag1_diff",
    "log_rv21_lag1_diff",
    "volume_z_lag1_diff",
)

REFERENCES = [
    {
        "authors": "Li, Z.; Liu, J.; Liu, J.; Liu, X.; Wu, C.",
        "year": 2025,
        "title": "Investor attention and stock price manipulation: Evidence from daily quasi-natural experiments",
        "journal": "Journal of Banking & Finance 179, 107528",
        "doi": "https://doi.org/10.1016/j.jbankfin.2025.107528",
        "role": "Motivates an attention-manipulation link; its China rounding design is not replicated here.",
    },
    {
        "authors": "Chen, Z.; Li, Z.; Liu, J.; Liu, X.",
        "year": 2026,
        "title": "Information salience, investor attention, and stock price crash risk",
        "journal": "Journal of Empirical Finance 85, 101670",
        "doi": "https://doi.org/10.1016/j.jempfin.2025.101670",
        "role": "Motivates forward crash-risk outcomes after exogenous salience.",
    },
    {
        "authors": "Hong, Z.; Liu, Q.; Tse, Y.; Wang, Z.",
        "year": 2023,
        "title": "Black mouth, investor attention, and stock return",
        "journal": "International Review of Financial Analysis 90, 102921",
        "doi": "https://doi.org/10.1016/j.irfa.2023.102921",
        "role": "Supports enforcement cases as retrospective event evidence, not causal attention identification.",
    },
    {
        "authors": "Cheng, F.; Wang, C.; Chiao, C.; Yao, S.; Fang, Z.",
        "year": 2021,
        "title": "Retail attention, retail trades, and stock price crash risk",
        "journal": "Emerging Markets Review 49, 100821",
        "doi": "https://doi.org/10.1016/j.ememar.2021.100821",
        "role": "Motivates abnormal/detrended attention rather than attention levels.",
    },
    {
        "authors": "Da, Z.; Engelberg, J.; Gao, P.",
        "year": 2011,
        "title": "In Search of Attention",
        "journal": "Journal of Finance 66(5), 1461-1499",
        "doi": "https://doi.org/10.1111/j.1540-6261.2011.01679.x",
        "role": "Motivates a past-only abnormal public-attention shock.",
    },
]


@dataclass(frozen=True)
class SourceMetadata:
    url: str
    sha256: str
    n_bytes: int


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        out = float(value)
        return None if not np.isfinite(out) else out
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def past_only_zscore(series: pd.Series, window: int = ROLLING_Z_WINDOW) -> pd.Series:
    """Current value versus a baseline ending strictly at t-1."""
    prior = series.shift(1)
    mean = prior.rolling(window, min_periods=ROLLING_Z_MIN).mean()
    std = prior.rolling(window, min_periods=ROLLING_Z_MIN).std(ddof=1)
    return ((series - mean) / std.replace(0.0, np.nan)).clip(-8.0, 8.0)


def forward_mean(series: pd.Series, horizon: int) -> pd.Series:
    """Value at row i is the mean over i,...,i+H-1."""
    return series.rolling(horizon, min_periods=horizon).mean().shift(-(horizon - 1))


def forward_max(series: pd.Series, horizon: int) -> pd.Series:
    """Value at row i is the maximum over i,...,i+H-1."""
    return series.rolling(horizon, min_periods=horizon).max().shift(-(horizon - 1))


def download_sec_complaint() -> tuple[Path, SourceMetadata]:
    path = DATA_DIR / "sec_comp26532.pdf"
    if not path.exists() or path.stat().st_size < 100_000:
        response = requests.get(
            SEC_COMPLAINT_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"},
            timeout=90,
        )
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError("SEC complaint response is not a PDF")
        path.write_bytes(response.content)
    return path, SourceMetadata(SEC_COMPLAINT_URL, file_sha256(path), path.stat().st_size)


def _normalise_pdf_months(text: str) -> str:
    replacements = {
        "Jul y": "July",
        "Jun e": "June",
        "Apr il": "April",
        "Nov .": "Nov.",
        "Sep .": "Sep.",
        "Oct .": "Oct.",
        "Aug .": "Aug.",
        "Feb .": "Feb.",
        "Jan .": "Jan.",
        "Dec .": "Dec.",
        "Nov.06": "Nov. 06",
        "April29": "April 29",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def parse_sec_weak_labels(pdf_path: Path) -> tuple[pd.DataFrame, dict]:
    """Parse Attachment A using Poppler's layout-preserving text extraction."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-f", "21", "-l", "37", "-layout", str(pdf_path), "-"],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("pdftotext (Poppler) is required to parse SEC Attachment A") from exc
    text = proc.stdout.decode("utf-8", errors="replace")

    # A block starts whenever the first column contains a security identifier
    # and the second column begins with Account N.  This intentionally catches
    # option identifiers too; a later strict equity-ticker regex excludes them.
    block_start = re.compile(r"^\s*(\S+)\s+(Account\s+\d+)\b")
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    skip_fragments = (
        "ATTACHMENT A",
        "Tickers for",
        "Manipulated",
        "Securities",
        "Dates of Manipulative Trading",
        "Case 1:26-cv-03203",
        "Page ",
    )
    for line in text.splitlines():
        match = block_start.match(line)
        if match:
            if current is not None:
                blocks.append(current)
            current = {"identifier": match.group(1), "text": line.strip()}
            continue
        if current is None or any(fragment in line for fragment in skip_fragments):
            continue
        current["text"] += " " + line.strip()
    if current is not None:
        blocks.append(current)

    date_pattern = re.compile(
        r"\b(?:Jan|Feb|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug|Sep|Oct|Nov|Dec)"
        r"\.?\s*\d{1,2},\s*20\d{2}\b"
    )
    rows: list[dict[str, object]] = []
    raw_date_occurrences = 0
    excluded_identifiers: list[str] = []
    for block in blocks:
        ticker = block["identifier"]
        # Exchange-listed common-stock symbols in this attachment are 1-5
        # uppercase letters.  Option identifiers contain '.', '--', or digits.
        if not re.fullmatch(r"[A-Z]{1,5}", ticker):
            excluded_identifiers.append(ticker)
            continue
        normalised = _normalise_pdf_months(block["text"])
        # Multi-account rows wrap "Account N" into the visual date column.
        # Remove those fragments before scanning dates; otherwise they split
        # tokens such as "March 25, 2022" across the concatenated row block.
        normalised = re.sub(r"Account\s+\d+\s*;?", " ", normalised)
        for token in date_pattern.findall(normalised):
            date = pd.to_datetime(token.replace("Sept.", "Sep."), errors="coerce")
            if pd.notna(date):
                raw_date_occurrences += 1
                rows.append(
                    {
                        "ticker": ticker,
                        "event_date": pd.Timestamp(date).normalize(),
                        "label_source": "SEC complaint Attachment A",
                        "label_status": "alleged manipulative trading date; retrospective weak label",
                    }
                )

    labels = pd.DataFrame(rows).drop_duplicates(["ticker", "event_date"]).sort_values(
        ["ticker", "event_date"]
    )
    year_counts = labels["event_date"].dt.year.value_counts().sort_index().to_dict()
    expected_year_counts = {2021: 474, 2022: 225, 2023: 378, 2024: 2}
    if (
        labels["ticker"].nunique() != 412
        or raw_date_occurrences != 1_083
        or len(labels) != 1_079
        or year_counts != expected_year_counts
    ):
        raise RuntimeError(
            "SEC parser full-population invariant failed: "
            f"tickers={labels['ticker'].nunique()}, occurrences={raw_date_occurrences}, "
            f"unique={len(labels)}, years={year_counts}"
        )
    label_path = DATA_DIR / "sec_manipulation_weak_labels.csv"
    labels.to_csv(label_path, index=False)
    meta = {
        "attachment_pages": "21-37 of PDF (Attachment A pages 1-17)",
        "parsed_blocks": len(blocks),
        "equity_tickers": int(labels["ticker"].nunique()),
        "raw_date_occurrences": raw_date_occurrences,
        "unique_ticker_dates": int(len(labels)),
        "first_event_date": labels["event_date"].min().date().isoformat(),
        "last_event_date": labels["event_date"].max().date().isoformat(),
        "excluded_non_equity_identifier_count": len(set(excluded_identifiers)),
        "parser_rule": (
            "full Attachment-A population; strip wrapped Account-column fragments, retain only 1-5 "
            "uppercase-letter identifiers, exclude options/malformed rows, then enforce exact count/year invariants"
        ),
        "csv_sha256": file_sha256(label_path),
    }
    return labels, meta


def fetch_pageviews(article: str) -> tuple[pd.Series, dict]:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", article)
    cache = DATA_DIR / f"wikimedia_{safe}.csv"
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        f"en.wikipedia.org/all-access/user/{quote(article, safe='')}/daily/"
        f"{PAGEVIEW_START}/{PAGEVIEW_END}"
    )
    if cache.exists():
        frame = pd.read_csv(cache, parse_dates=["date"])
        series = pd.Series(frame["views"].to_numpy(float), index=frame["date"], name=article)
        return series, {
            "article": article,
            "url": url,
            "status": "cache",
            "n_obs": len(series),
            "first_date": series.index.min().date().isoformat(),
            "last_date": series.index.max().date().isoformat(),
            "sha256": file_sha256(cache),
        }

    # Reuse an earlier experiment's byte-traceable snapshot when available.
    # It came from the same official endpoint and covers a superset of K1678's
    # requested dates; copying the requested slice avoids redundant API load.
    prior_cache = PRIOR_WIKI_CACHE_DIR / f"wikimedia_pageviews_{safe}.csv"
    if prior_cache.exists():
        prior = pd.read_csv(prior_cache, parse_dates=["date"])
        prior = prior.loc[
            (prior["date"] >= pd.Timestamp(START_DATE))
            & (prior["date"] <= pd.to_datetime(PAGEVIEW_END, format="%Y%m%d"))
        ].copy()
        if len(prior) >= 100:
            prior.to_csv(cache, index=False)
            series = pd.Series(prior["views"].to_numpy(float), index=prior["date"], name=article)
            return series, {
                "article": article,
                "url": url,
                "status": "prior_official_cache",
                "prior_cache_path": str(prior_cache.relative_to(REPO_ROOT)),
                "prior_cache_sha256": file_sha256(prior_cache),
                "n_obs": len(series),
                "first_date": series.index.min().date().isoformat(),
                "last_date": series.index.max().date().isoformat(),
                "sha256": file_sha256(cache),
            }

    response = None
    for attempt in range(5):
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
        if response.status_code != 429:
            break
        retry_after = response.headers.get("Retry-After")
        wait_seconds = float(retry_after) if retry_after and retry_after.isdigit() else 6.0 * (attempt + 1)
        time.sleep(wait_seconds)
    if response is None:
        raise RuntimeError(f"Wikimedia request failed without a response for {article}")
    if response.status_code == 404:
        return pd.Series(dtype=float, name=article), {
            "article": article,
            "url": url,
            "status": "missing_article",
            "http_status": 404,
        }
    response.raise_for_status()
    rows = []
    for item in response.json().get("items", []):
        stamp = str(item.get("timestamp", ""))
        if len(stamp) >= 8:
            rows.append(
                {"date": pd.to_datetime(stamp[:8], format="%Y%m%d"), "views": float(item.get("views", 0.0))}
            )
    if not rows:
        raise RuntimeError(f"Wikimedia returned no pageviews for {article}")
    frame = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
    frame.to_csv(cache, index=False)
    series = pd.Series(frame["views"].to_numpy(float), index=frame["date"], name=article)
    time.sleep(0.1)
    return series, {
        "article": article,
        "url": url,
        "status": "download",
        "n_obs": len(series),
        "first_date": series.index.min().date().isoformat(),
        "last_date": series.index.max().date().isoformat(),
        "sha256": file_sha256(cache),
    }


def build_attention_panel() -> tuple[pd.DataFrame, dict]:
    calendar = pd.date_range(START_DATE, pd.Timestamp(END_DATE) - pd.Timedelta(days=1), freq="D")
    metadata: dict[str, dict] = {}
    page_series: dict[str, pd.Series] = {}
    for article in (*PRIMARY_PAGES, *EPISODE_PAGES, *ANCHOR_PAGES):
        series, meta = fetch_pageviews(article)
        metadata[article] = meta
        if not series.empty:
            page_series[article] = series.reindex(calendar).fillna(0.0)

    missing_primary = sorted(set(PRIMARY_PAGES) - set(page_series))
    missing_anchor = sorted(set(ANCHOR_PAGES) - set(page_series))
    if missing_primary or missing_anchor:
        raise RuntimeError(f"Missing required Wikimedia pages: primary={missing_primary}, anchors={missing_anchor}")

    primary_views = pd.DataFrame({p: page_series[p] for p in PRIMARY_PAGES}).sum(axis=1)
    all_views = pd.DataFrame(
        {p: page_series[p] for p in (*PRIMARY_PAGES, *EPISODE_PAGES) if p in page_series}
    ).sum(axis=1)
    anchor_views = pd.DataFrame({p: page_series[p] for p in ANCHOR_PAGES}).sum(axis=1)
    pump_views = page_series["Pump_and_dump"]

    primary_rel_7d = np.log1p(primary_views.rolling(7, min_periods=7).sum()) - np.log1p(
        anchor_views.rolling(7, min_periods=7).sum()
    )
    all_rel_21d = np.log1p(all_views.rolling(21, min_periods=21).sum()) - np.log1p(
        anchor_views.rolling(21, min_periods=21).sum()
    )
    pump_rel_7d = np.log1p(pump_views.rolling(7, min_periods=7).sum()) - np.log1p(
        anchor_views.rolling(7, min_periods=7).sum()
    )

    panel = pd.DataFrame(index=calendar)
    panel["primary_views"] = primary_views
    panel["all_topic_views"] = all_views
    panel["pump_views"] = pump_views
    panel["anchor_views"] = anchor_views
    panel["saliency_raw_z"] = past_only_zscore(primary_rel_7d)
    panel["saliency21_raw_z"] = past_only_zscore(all_rel_21d)
    panel["pump_raw_z"] = past_only_zscore(pump_rel_7d)
    panel.index.name = "date"
    path = DATA_DIR / "wikimedia_attention_panel.csv"
    panel.to_csv(path)
    metadata["panel"] = {
        "definition": "past-only z-score of log 7-day topic views minus log 7-day anchor views",
        "primary_pages": list(PRIMARY_PAGES),
        "episode_pages_secondary_only": list(EPISODE_PAGES),
        "anchor_pages": list(ANCHOR_PAGES),
        "rolling_baseline_days": ROLLING_Z_WINDOW,
        "minimum_baseline_days": ROLLING_Z_MIN,
        "sha256": file_sha256(path),
    }
    return panel, metadata


def _extract_symbol_frame(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        ticker_level = 1 if symbol in raw.columns.get_level_values(1) else 0
        if symbol not in raw.columns.get_level_values(ticker_level):
            return pd.DataFrame()
        frame = raw.xs(symbol, axis=1, level=ticker_level).copy()
    else:
        frame = raw.copy()
    frame.columns = [str(c) for c in frame.columns]
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"], how="any")
    if frame.empty:
        return frame
    adjustment = (
        frame["Adj Close"] / frame["Close"]
        if "Adj Close" in frame.columns
        else pd.Series(1.0, index=frame.index)
    )
    out = pd.DataFrame(index=pd.to_datetime(frame.index).tz_localize(None))
    for field in ("Open", "High", "Low", "Close"):
        adjusted = pd.to_numeric(frame[field], errors="coerce") * adjustment
        # Assign positionally because yfinance can return a tz-aware index;
        # ``out`` deliberately strips that timezone for stable joins.
        out[field.lower()] = adjusted.to_numpy(float)
    out["volume"] = pd.to_numeric(frame["Volume"], errors="coerce").to_numpy(float)
    out["ticker"] = symbol
    out = out.loc[(out[["open", "high", "low", "close"]] > 0.0).all(axis=1)].copy()
    out.index.name = "date"
    return out.reset_index()


def load_or_fetch_prices(symbols: list[str]) -> tuple[pd.DataFrame, dict]:
    cache = DATA_DIR / "yfinance_adjusted_ohlcv.csv.gz"
    requested = sorted(set(symbols) | {"SPY", "^VIX"})
    if cache.exists():
        prices = pd.read_csv(cache, parse_dates=["date"])
        available = sorted(prices["ticker"].unique())
        return prices, {
            "status": "cache",
            "requested_symbols": len(requested),
            "available_symbols": len(available),
            "missing_symbols": sorted(set(requested) - set(available)),
            "rows": len(prices),
            "sha256": file_sha256(cache),
        }

    frames: list[pd.DataFrame] = []
    batch_errors: list[dict] = []
    batch_size = 50
    for start in range(0, len(requested), batch_size):
        batch = requested[start : start + batch_size]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = yf.download(
                    batch,
                    start=START_DATE,
                    end=END_DATE,
                    auto_adjust=False,
                    actions=False,
                    progress=False,
                    threads=True,
                    group_by="column",
                )
            for symbol in batch:
                frame = _extract_symbol_frame(raw, symbol)
                if not frame.empty:
                    frames.append(frame)
        except Exception as exc:  # external availability is part of provenance
            batch_errors.append({"symbols": batch, "error": repr(exc)})
        time.sleep(0.25)
    if not frames:
        raise RuntimeError("No yfinance data were downloaded")
    prices = pd.concat(frames, ignore_index=True).drop_duplicates(["ticker", "date"])
    prices = prices.sort_values(["ticker", "date"])
    prices.to_csv(cache, index=False, compression=DETERMINISTIC_GZIP)
    available = sorted(prices["ticker"].unique())
    return prices, {
        "status": "download",
        "requested_symbols": len(requested),
        "available_symbols": len(available),
        "missing_symbols": sorted(set(requested) - set(available)),
        "rows": len(prices),
        "batch_errors": batch_errors,
        "sha256": file_sha256(cache),
    }


def build_market_controls(prices: pd.DataFrame) -> pd.DataFrame:
    spy = prices.loc[prices["ticker"] == "SPY"].set_index("date").sort_index()
    vix = prices.loc[prices["ticker"] == "^VIX"].set_index("date").sort_index()
    if spy.empty or vix.empty:
        raise RuntimeError("SPY and ^VIX are required market controls")
    index = spy.index
    out = pd.DataFrame(index=index)
    out["spy_ret_lag1"] = np.log(spy["close"]).diff().shift(1)
    vix_close = vix["close"].reindex(index).ffill()
    out["vix_z_lag1"] = past_only_zscore(np.log(vix_close.clip(lower=EPS))).shift(1)
    out.index.name = "date"
    return out


def build_analysis_panel(
    prices: pd.DataFrame,
    labels: pd.DataFrame,
    attention: pd.DataFrame,
) -> pd.DataFrame:
    market = build_market_controls(prices)
    trading_dates = market.index
    wiki = attention.reindex(trading_dates, method="ffill")
    # HARD timing guard: the feature at target-start i is the raw shock known on
    # the immediately preceding trading row.  Targets begin at i.
    wiki_features = pd.DataFrame(index=trading_dates)
    wiki_features["saliency_z_lag1"] = wiki["saliency_raw_z"].shift(1)
    wiki_features["saliency21_z_lag1"] = wiki["saliency21_raw_z"].shift(1)
    wiki_features["pump_z_lag1"] = wiki["pump_raw_z"].shift(1)

    label_keys = set(zip(labels["ticker"], pd.to_datetime(labels["event_date"])))
    panels: list[pd.DataFrame] = []
    event_tickers = sorted(labels["ticker"].unique())
    price_tickers = set(prices["ticker"].unique())
    for ticker in event_tickers:
        if ticker not in price_tickers:
            continue
        group = prices.loc[prices["ticker"] == ticker].copy().sort_values("date")
        group = group.drop_duplicates("date").set_index("date")
        if len(group) < 80:
            continue
        ret = np.log(group["close"].clip(lower=EPS)).diff()
        gap = np.log(group["open"].clip(lower=EPS) / group["close"].shift(1).clip(lower=EPS))
        log_volume = np.log1p(group["volume"].clip(lower=0.0))

        out = group[["open", "high", "low", "close", "volume"]].copy()
        out["ticker"] = ticker
        out["sec_event"] = [int((ticker, pd.Timestamp(date)) in label_keys) for date in out.index]
        out["formation_date"] = pd.Series(out.index, index=out.index).shift(1)
        # Explicit signal.shift(1): a label formed on t is attached to the row
        # whose target starts on the next observed trading day.
        out["sec_event_lag1"] = out["sec_event"].shift(1).fillna(0).astype(int)
        out["ret1_lag1"] = ret.shift(1)
        out["ret5_lag1"] = ret.rolling(5, min_periods=5).sum().shift(1)
        out["log_rv21_lag1"] = np.log(ret.pow(2).rolling(21, min_periods=21).mean() + EPS).shift(1)
        out["volume_z_lag1"] = past_only_zscore(log_volume).shift(1)

        for horizon in HORIZONS:
            out[f"rv_h{horizon}"] = 10_000.0 * forward_mean(ret.pow(2), horizon)
            out[f"dsv_h{horizon}"] = 10_000.0 * forward_mean(ret.pow(2).where(ret < 0.0, 0.0), horizon)
            out[f"left_tail_h{horizon}"] = 100.0 * forward_max((-ret).clip(lower=0.0), horizon)
            out[f"downside_gap_h{horizon}"] = 100.0 * forward_max((-gap).clip(lower=0.0), horizon)

        out = out.join(market, how="left").join(wiki_features, how="left")
        out["row_position"] = np.arange(len(out), dtype=int)
        out.index.name = "date"
        panels.append(out.reset_index())

    if not panels:
        raise RuntimeError("No SEC-labelled ticker had sufficient yfinance history")
    panel = pd.concat(panels, ignore_index=True).sort_values(["ticker", "date"])
    panel_path = DATA_DIR / "analysis_panel.csv.gz"
    panel.to_csv(panel_path, index=False, compression=DETERMINISTIC_GZIP)
    return panel


def _decluster_event_rows(group: pd.DataFrame, horizon: int) -> list[int]:
    event_positions = group.loc[group["sec_event_lag1"] == 1, "row_position"].astype(int).tolist()
    kept: list[int] = []
    last = -10**9
    for position in event_positions:
        if position - last >= horizon:
            kept.append(position)
            last = position
    return kept


def build_matched_pairs(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    target_cols = [f"{outcome}_h{horizon}" for outcome in OUTCOMES]
    required = [
        "date",
        "formation_date",
        "ticker",
        "row_position",
        "sec_event_lag1",
        "saliency_z_lag1",
        "saliency21_z_lag1",
        "pump_z_lag1",
        *MATCH_FEATURES,
        *target_cols,
    ]
    pair_rows: list[dict] = []
    buffer = max(10, horizon)
    for ticker, raw_group in panel.groupby("ticker", sort=True):
        group = raw_group.sort_values("row_position").copy()
        group = group.dropna(subset=required[3:])
        if group.empty:
            continue
        all_event_positions = raw_group.loc[raw_group["sec_event_lag1"] == 1, "row_position"].to_numpy(int)
        if len(all_event_positions) == 0:
            continue
        kept_positions = set(_decluster_event_rows(raw_group, horizon))
        feature_scale = group[list(MATCH_FEATURES)].std(ddof=1).replace(0.0, np.nan)
        feature_scale = feature_scale.fillna(1.0)

        candidates = group.loc[group["sec_event_lag1"] == 0].copy()
        candidate_pos = candidates["row_position"].to_numpy(int)
        distance_to_event = np.min(
            np.abs(candidate_pos[:, None] - all_event_positions[None, :]), axis=1
        )
        candidates = candidates.loc[distance_to_event > buffer].copy()
        if len(candidates) < MATCH_CONTROLS:
            continue

        for _, event in group.loc[
            (group["sec_event_lag1"] == 1) & group["row_position"].isin(kept_positions)
        ].iterrows():
            pool = candidates.loc[
                (candidates["row_position"] - int(event["row_position"])).abs() <= MATCH_WINDOW
            ].copy()
            same_year = pool.loc[pool["date"].dt.year == pd.Timestamp(event["date"]).year]
            if len(same_year) >= max(10, MATCH_CONTROLS):
                pool = same_year
            if len(pool) < MATCH_CONTROLS:
                continue
            standardised = (pool[list(MATCH_FEATURES)] - event[list(MATCH_FEATURES)].astype(float)) / feature_scale
            pool["match_distance"] = standardised.pow(2).sum(axis=1)
            controls = pool.nsmallest(MATCH_CONTROLS, "match_distance")

            row: dict[str, object] = {
                "ticker": ticker,
                "horizon": horizon,
                "formation_date": pd.Timestamp(event["formation_date"]),
                "target_start_date": pd.Timestamp(event["date"]),
                "event_row_position": int(event["row_position"]),
                "control_dates": "|".join(controls["date"].dt.date.astype(str)),
                "mean_match_distance": float(controls["match_distance"].mean()),
                "saliency_diff": float(event["saliency_z_lag1"] - controls["saliency_z_lag1"].mean()),
                "saliency21_diff": float(
                    event["saliency21_z_lag1"] - controls["saliency21_z_lag1"].mean()
                ),
                "pump_diff": float(event["pump_z_lag1"] - controls["pump_z_lag1"].mean()),
            }
            for feature in MATCH_FEATURES:
                row[f"{feature}_diff"] = float(event[feature] - controls[feature].mean())
            for outcome in OUTCOMES:
                column = f"{outcome}_h{horizon}"
                row[f"{outcome}_event"] = float(event[column])
                row[f"{outcome}_control"] = float(controls[column].mean())
                row[f"{outcome}_diff"] = float(event[column] - controls[column].mean())
            pair_rows.append(row)
    pairs = pd.DataFrame(pair_rows)
    if pairs.empty:
        raise RuntimeError(f"No matched pairs for H={horizon}")
    return pairs.sort_values(["formation_date", "ticker"])


def _standardise_frame(frame: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, dict]:
    out = frame.copy()
    metadata: dict[str, dict] = {}
    for column in columns:
        mean = float(out[column].mean())
        std = float(out[column].std(ddof=1))
        if not np.isfinite(std) or std <= 0.0:
            raise RuntimeError(f"Cannot standardise {column}: std={std}")
        out[column] = (out[column] - mean) / std
        metadata[column] = {"mean": mean, "std": std}
    return out, metadata


def moving_block_bootstrap_beta(
    date_frame: pd.DataFrame,
    y_col: str,
    signal_col: str,
    controls: list[str],
    block: int,
    seed: int,
) -> dict:
    columns = [signal_col, *controls]
    data, _ = _standardise_frame(date_frame[[y_col, *columns]], columns)
    y = data[y_col].to_numpy(float)
    x = sm.add_constant(data[columns], has_constant="add").to_numpy(float)
    n = len(data)
    if n < max(30, block * 2):
        return {
            "reps": 0,
            "block": block,
            "seed": seed,
            "ci95": [None, None],
            "p_two_sided": None,
        }
    rng = np.random.default_rng(seed)
    starts = np.arange(0, max(1, n - block + 1))
    betas: list[float] = []
    for _ in range(BOOT_REPS):
        chosen: list[int] = []
        while len(chosen) < n:
            start = int(rng.choice(starts))
            chosen.extend(range(start, min(start + block, n)))
        index = np.asarray(chosen[:n], dtype=int)
        try:
            params, _, rank, _ = np.linalg.lstsq(x[index], y[index], rcond=None)
            if rank == x.shape[1] and np.isfinite(params[1]):
                betas.append(float(params[1]))
        except np.linalg.LinAlgError:
            continue
    if len(betas) < 1_000:
        raise RuntimeError(f"Only {len(betas)} valid bootstrap reps for {y_col}, {signal_col}")
    arr = np.asarray(betas)
    p_two = 2.0 * min(float(np.mean(arr <= 0.0)), float(np.mean(arr >= 0.0)))
    return {
        "reps": len(arr),
        "block": block,
        "seed": seed,
        "ci95": [float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975))],
        "p_two_sided": min(1.0, p_two),
        "median": float(np.median(arr)),
    }


def fit_date_hac(
    pairs: pd.DataFrame,
    outcome: str,
    horizon: int,
    signal_col: str,
    bootstrap: bool,
    seed_offset: int,
) -> tuple[dict, pd.DataFrame]:
    y_col = f"{outcome}_diff"
    aggregation = {
        y_col: "mean",
        signal_col: "mean",
        **{column: "mean" for column in REGRESSION_BALANCE_CONTROLS},
        "ticker": "count",
        f"{outcome}_event": "mean",
        f"{outcome}_control": "mean",
    }
    date_frame = (
        pairs.groupby("formation_date", as_index=False)
        .agg(aggregation)
        .rename(columns={"ticker": "event_count"})
        .sort_values("formation_date")
    )
    model_columns = [signal_col, *REGRESSION_BALANCE_CONTROLS]
    date_frame = date_frame.dropna(subset=[y_col, *model_columns])
    if len(date_frame) < 30:
        raise RuntimeError(f"Insufficient event-date clusters for {outcome} H={horizon}: {len(date_frame)}")
    standardised, scale_meta = _standardise_frame(date_frame, model_columns)
    x = sm.add_constant(standardised[model_columns], has_constant="add")
    maxlags = horizon - 1
    fit = sm.OLS(standardised[y_col], x).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": maxlags, "use_correction": True},
    )
    beta = float(fit.params[signal_col])
    se = float(fit.bse[signal_col])
    t_stat = float(fit.tvalues[signal_col])
    p_value = float(fit.pvalues[signal_col])

    # Intercept-only date-clustered diagnostic: average event-minus-control
    # effect irrespective of saliency.  This is secondary and cannot establish
    # that attention caused manipulation.
    direct = sm.OLS(date_frame[y_col], np.ones((len(date_frame), 1))).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": maxlags, "use_correction": True},
    )
    result = {
        "outcome": outcome,
        "horizon": horizon,
        "signal": signal_col,
        "beta_per_1sd": beta,
        "se_hac": se,
        "t_hac": t_stat,
        "p_hac_two_sided": p_value,
        "hac_maxlags": maxlags,
        "n_event_rows": int(len(pairs)),
        "n_event_date_clusters": int(len(date_frame)),
        "n_tickers": int(pairs["ticker"].nunique()),
        "signal_scale": scale_meta[signal_col],
        "direct_event_minus_control_mean": float(direct.params.iloc[0]),
        "direct_event_minus_control_t_hac": float(direct.tvalues.iloc[0]),
        "event_target_mean": float(pairs[f"{outcome}_event"].mean()),
        "control_target_mean": float(pairs[f"{outcome}_control"].mean()),
    }
    if bootstrap:
        result["moving_block_bootstrap"] = moving_block_bootstrap_beta(
            date_frame,
            y_col=y_col,
            signal_col=signal_col,
            controls=list(REGRESSION_BALANCE_CONTROLS),
            block=max(10, horizon),
            seed=SEED + seed_offset,
        )
    return result, date_frame


def apply_multiple_testing(primary: list[dict]) -> None:
    if len(primary) != M_PRIMARY:
        raise RuntimeError(f"Primary family must contain exactly m={M_PRIMARY}; got {len(primary)}")
    p_values = np.asarray([row["p_hac_two_sided"] for row in primary], dtype=float)
    reject_bh, q_values, _, _ = multipletests(p_values, alpha=0.05, method="fdr_bh")
    bonferroni = np.minimum(1.0, p_values * M_PRIMARY)
    for row, bh_reject, q_value, bonf in zip(primary, reject_bh, q_values, bonferroni):
        bootstrap = row["moving_block_bootstrap"]
        ci_low = bootstrap["ci95"][0]
        row["bonferroni_p"] = float(bonf)
        row["bh_q"] = float(q_value)
        row["bh_reject_5pct"] = bool(bh_reject)
        row["harvey_directional_pass"] = bool(row["t_hac"] >= 3.0)
        row["strict_cell_pass"] = bool(
            row["beta_per_1sd"] > 0.0
            and row["t_hac"] >= 3.0
            and bonf < 0.05
            and q_value < 0.05
            and ci_low is not None
            and ci_low > 0.0
        )


def make_figure(primary: list[dict], attention: pd.DataFrame) -> None:
    labels = [f"{row['outcome']} H={row['horizon']}" for row in primary]
    t_stats = [row["t_hac"] for row in primary]
    betas = [row["beta_per_1sd"] for row in primary]

    fig, axes = plt.subplots(2, 1, figsize=(12, 9), constrained_layout=True)
    colors = ["#b2182b" if value >= 3.0 else "#4d6a87" for value in t_stats]
    positions = np.arange(len(labels))
    axes[0].bar(positions, t_stats, color=colors)
    axes[0].axhline(3.0, color="#b2182b", linestyle="--", linewidth=1.2, label="Harvey t=3")
    axes[0].axhline(0.0, color="black", linewidth=0.8)
    axes[0].set_xticks(positions, labels, rotation=30, ha="right")
    axes[0].set_ylabel("HAC t-stat on saliency amplification")
    axes[0].set_title("K1678 primary family (m=8): SEC-labelled matched events")
    axes[0].legend(frameon=False)
    for x, beta, t_stat in zip(positions, betas, t_stats):
        axes[0].text(x, t_stat, f"β={beta:.3g}", ha="center", va="bottom" if t_stat >= 0 else "top", fontsize=8)

    signal = attention["saliency_raw_z"].dropna()
    axes[1].plot(signal.index, signal, color="#2c7fb8", linewidth=0.8, label="raw close-t saliency z")
    axes[1].axhline(0.0, color="black", linewidth=0.8)
    axes[1].set_ylabel("Past-only Wikimedia saliency z")
    axes[1].set_title(
        "Public manipulation/retail-attention proxy (used only after an explicit one-trading-row shift)"
    )
    axes[1].legend(frameon=False)
    fig.savefig(FIGURE_PATH, dpi=180)
    plt.close(fig)


def main() -> None:
    ensure_dirs()
    pdf_path, sec_source = download_sec_complaint()
    labels, label_meta = parse_sec_weak_labels(pdf_path)
    attention, wiki_meta = build_attention_panel()
    prices, price_meta = load_or_fetch_prices(sorted(labels["ticker"].unique()))
    panel = build_analysis_panel(prices, labels, attention)

    all_pairs: list[pd.DataFrame] = []
    pairs_by_horizon: dict[int, pd.DataFrame] = {}
    for horizon in HORIZONS:
        pairs = build_matched_pairs(panel, horizon)
        pairs_by_horizon[horizon] = pairs
        all_pairs.append(pairs)
    matched = pd.concat(all_pairs, ignore_index=True)
    matched.to_csv(MATCHED_PATH, index=False, compression=DETERMINISTIC_GZIP)

    primary: list[dict] = []
    sensitivity: list[dict] = []
    date_panels: dict[str, pd.DataFrame] = {}
    for horizon in HORIZONS:
        pairs = pairs_by_horizon[horizon]
        for outcome_index, outcome in enumerate(OUTCOMES):
            result, date_frame = fit_date_hac(
                pairs,
                outcome=outcome,
                horizon=horizon,
                signal_col="saliency_diff",
                bootstrap=True,
                seed_offset=horizon * 100 + outcome_index,
            )
            primary.append(result)
            date_panels[f"{outcome}_h{horizon}"] = date_frame
            for sensitivity_index, signal in enumerate(("pump_diff", "saliency21_diff")):
                alt, _ = fit_date_hac(
                    pairs,
                    outcome=outcome,
                    horizon=horizon,
                    signal_col=signal,
                    bootstrap=False,
                    seed_offset=10_000 + horizon * 100 + outcome_index * 10 + sensitivity_index,
                )
                sensitivity.append(alt)

    apply_multiple_testing(primary)
    summary = pd.DataFrame(primary)
    summary.to_csv(SUMMARY_PATH, index=False)
    make_figure(primary, attention)

    strict_passes = [row for row in primary if row["strict_cell_pass"]]
    fdr_only = [
        row
        for row in primary
        if row["beta_per_1sd"] > 0.0 and row["bh_q"] < 0.05 and not row["strict_cell_pass"]
    ]
    min_pairs = min(row["n_event_rows"] for row in primary)
    min_tickers = min(row["n_tickers"] for row in primary)
    if min_pairs < 100 or min_tickers < 30:
        verdict = "UNDERPOWERED_SEC_WEAK_LABEL_COVERAGE"
        conclusion = "SEC-labelled matched-event coverage is too small for the predeclared inference gate."
    elif len(strict_passes) >= 2:
        verdict = "CONDITIONAL_PASS_RETROSPECTIVE_PROXY"
        conclusion = (
            "At least two crash-risk cells pass the conservative HAC, Harvey, Bonferroni, BH, and block-bootstrap gates; "
            "the result remains a retrospective public-proxy association, not causal manipulation detection."
        )
    elif len(strict_passes) == 1:
        verdict = "WEAK_SINGLE_CELL_ONLY"
        conclusion = (
            "Only one of eight primary cells passes all gates, which is insufficient for a broad saliency-amplification claim."
        )
    elif fdr_only:
        verdict = "WEAK_FDR_ONLY"
        conclusion = "Some positive cells survive BH but none survives the full Harvey/Bonferroni/bootstrap gate."
    else:
        verdict = "NULL_NO_ROBUST_SALIENCY_AMPLIFICATION"
        conclusion = (
            "The public Wikimedia saliency shock does not robustly amplify post-event crash risk across the eight predeclared cells."
        )

    labels_with_price = labels.loc[labels["ticker"].isin(set(prices["ticker"].unique()))]
    label_price_keys = set(zip(labels_with_price["ticker"], labels_with_price["event_date"]))
    observed_keys = set(
        zip(
            panel.loc[panel["sec_event"] == 1, "ticker"],
            pd.to_datetime(panel.loc[panel["sec_event"] == 1, "date"]),
        )
    )
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "research_question": (
            "Within retrospective SEC-labelled manipulative trading events, does an abnormal public saliency shock "
            "amplify next-day or next-five-day RV, downside semivariance, left-tail loss, or downside opening-gap risk?"
        ),
        "methodology_type": "empirical retrospective proxy diagnostic; non-causal",
        "verdict": {
            "label": verdict,
            "conclusion": conclusion,
            "strict_primary_pass_count": len(strict_passes),
            "fdr_only_positive_count": len(fdr_only),
        },
        "data": {
            "sec": {
                "litigation_release": SEC_RELEASE_URL,
                "complaint_url": sec_source.url,
                "complaint_filed_date": SEC_FILED_DATE,
                "complaint_sha256": sec_source.sha256,
                "complaint_bytes": sec_source.n_bytes,
                **label_meta,
                "status_warning": (
                    "These are allegations in a complaint filed after all event dates; they are not convictions and were not available in real time."
                ),
            },
            "wikimedia": {
                "source": "Wikimedia Analytics Pageviews API",
                "requested_period": [START_DATE, "2024-02-15"],
                "metadata": wiki_meta,
                "proxy_warning": (
                    "Topic pageviews are broad public-attention proxies, not ticker-specific searches, posts, trades, or proof of manipulation."
                ),
            },
            "prices": {
                "source": "yfinance daily OHLCV, split/dividend-adjusted OHLC",
                "requested_period": [START_DATE, "2024-02-15"],
                **price_meta,
            },
            "coverage": {
                "sec_label_tickers": int(labels["ticker"].nunique()),
                "sec_label_ticker_dates": int(len(labels)),
                "label_tickers_with_price": int(labels_with_price["ticker"].nunique()),
                "label_ticker_dates_for_available_tickers": int(len(label_price_keys)),
                "exact_label_ticker_dates_observed_in_price_panel": int(len(observed_keys)),
                "analysis_panel_rows": int(len(panel)),
                "analysis_panel_tickers": int(panel["ticker"].nunique()),
                "matched_rows_by_horizon": {
                    str(h): int(len(pairs_by_horizon[h])) for h in HORIZONS
                },
                "matched_tickers_by_horizon": {
                    str(h): int(pairs_by_horizon[h]["ticker"].nunique()) for h in HORIZONS
                },
                "matched_event_date_clusters_by_horizon": {
                    str(h): int(pairs_by_horizon[h]["formation_date"].nunique()) for h in HORIZONS
                },
            },
        },
        "timing_and_lookahead": {
            "formation_day": "t",
            "target_windows": {"H1": "t+1", "H5": "t+1 through t+5"},
            "code_guard": (
                "sec_event_lag1 = sec_event.shift(1); Wikimedia raw past-only z-scores are shifted one trading row before joining targets"
            ),
            "attention_baseline": "rolling mean/std use values ending at t-1",
            "event_overlap": "within-ticker labelled events are de-clustered by H trading rows",
            "control_exclusion": "candidate control rows within max(10,H) trading rows of any labelled event are excluded",
        },
        "design": {
            "matching": {
                "controls_per_event": MATCH_CONTROLS,
                "same_ticker": True,
                "preferred_same_calendar_year": True,
                "maximum_trading_row_distance": MATCH_WINDOW,
                "features": list(MATCH_FEATURES),
                "clean_control_warning": (
                    "A no-label control day means only that this SEC complaint did not label it; it is not proven manipulation-free."
                ),
            },
            "primary_family": {
                "m": M_PRIMARY,
                "horizons": list(HORIZONS),
                "outcomes": {
                    "rv": "mean squared close-to-close log return × 10,000",
                    "dsv": "mean squared negative close-to-close log return × 10,000",
                    "left_tail": "maximum downside close-to-close loss in percent",
                    "downside_gap": "maximum downside open-versus-prior-close gap in percent",
                },
                "coefficient": (
                    "date-aggregated matched outcome difference on matched saliency difference, per one sample SD"
                ),
            },
            "inference": {
                "date_aggregation": "average multiple tickers sharing the same SEC event date before inference",
                "hac_maxlags_by_horizon": {str(h): h - 1 for h in HORIZONS},
                "harvey_directional_threshold": "t >= 3.0",
                "multiple_testing": "Bonferroni and Benjamini-Hochberg over m=8 primary cells",
                "bootstrap_reps": BOOT_REPS,
                "bootstrap_base_seed": SEED,
                "bootstrap_cell_seed_rule": "SEED + 100 * horizon + outcome_index (0=RV, 1=DSV, 2=left-tail, 3=gap)",
                "bootstrap_block_by_horizon": {str(h): max(10, h) for h in HORIZONS},
            },
        },
        "primary_results": primary,
        "sensitivity_results": {
            "description": (
                "Same matched design using Pump_and_dump-only 7-day attention and broader 21-day topic attention; "
                "secondary, not included in the m=8 verdict family."
            ),
            "cells": sensitivity,
        },
        "limitations": [
            "The April 2026 SEC complaint is a post-sample allegation, not a conviction and not a point-in-time detector.",
            "The complaint concerns one alleged trader and is not a random or complete population of U.S. manipulation.",
            "Current yfinance availability creates survivorship and delisting attrition, especially among thinly traded issuers.",
            "Wikimedia topic pageviews are market-wide and not ticker-specific search, Reddit, Stocktwits, news, or investor-flow data.",
            "Daily OHLCV cannot identify the complaint's intraday odd-lot, spoofing, or order-book mechanism.",
            "Matched no-label dates are not verified clean dates; contamination biases the contrast toward zero.",
            "The same official case supplied the retrospective sample definition, so p-values are conditional on this case and not population-wide discovery probabilities.",
        ],
        "related_prior_evidence": {
            "K1554": "Public Stocktwits history was underpowered (22 events from two tickers).",
            "K1340": "Daily price-volume retail-pressure proxy had no directional crash-risk pass.",
            "K1487": "Coarse GDELT theme attention did not improve OOS RV forecasts.",
            "anti_stockholder_identity_proxy": (
                "Wikimedia retail-attention 22-day RV had a raw t=2.85 but failed Holm and OOS gates; K1678 differs via exact SEC event labels and H=1/H=5 crash-risk targets."
            ),
        },
        "references": REFERENCES,
        "artifacts": {
            "script": str(Path(__file__).name),
            "results": RESULTS_PATH.name,
            "summary_csv": SUMMARY_PATH.name,
            "matched_events": MATCHED_PATH.name,
            "figure": FIGURE_PATH.name,
            "matched_events_sha256": file_sha256(MATCHED_PATH),
            "summary_sha256": file_sha256(SUMMARY_PATH),
            "figure_sha256": file_sha256(FIGURE_PATH),
        },
    }
    atomic_write_json(RESULTS_PATH, payload)
    print(json.dumps(payload["verdict"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["data"]["coverage"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
