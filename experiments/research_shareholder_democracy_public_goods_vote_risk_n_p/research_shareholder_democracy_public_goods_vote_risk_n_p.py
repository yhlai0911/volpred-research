"""Shareholder public-goods proposal vote risk event study.

Experiment id:
    research_shareholder_democracy_public_goods_vote_risk_n_p

This is a bounded public-data pilot. It uses the public Proxy Monitor API as
an event source for shareholder proposals and yfinance daily prices for firm
and sector ETF volatility. It does not observe the full Form N-PX mutual-fund
vote panel, index-manager holdings, or all ISS/FactSet proposal metadata.

Lookahead rule:
    Proposal/vote events are aligned to the first trading day on or after the
    proposal date. The predictive event signal is explicitly lagged with
    signal_lag1 = raw_event_signal.shift(1), so the return target at t is
    predicted only by the event signal available at t-1.
"""
from __future__ import annotations

import json
import math
import re
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "research_shareholder_democracy_public_goods_vote_risk_n_p"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"

SEED = 20260702
START_YEAR = 2020
END_YEAR = 2024
TRAIN_END_YEAR = 2022
PRICE_START = "2019-07-01"
PRICE_END = "2025-02-01"
ROLLING_BASELINE_DAYS = 60
ROLLING_MIN_DAYS = 40
BOOTSTRAP_REPS = 2000
EPS = 1e-12

PROXY_MONITOR_URL = "https://api.proxymonitor.org/proposals-search/"
AS_YOU_SOW_URL = "https://apps.asyousow.org/rs-data.php"

REFERENCES = [
    {
        "citation": "He, Kahraman, and Lowry (2023), ES Risks and Shareholder Voice, Review of Financial Studies.",
        "url": "https://academic.oup.com/rfs/article/36/12/4824/7180284",
        "use": "Motivates shareholder proposals and mutual-fund support as signals about environmental/social risk.",
    },
    {
        "citation": "Michaely, Ordonez-Calafi, and Rubio (2022), Mutual funds' strategic voting on environmental and social issues, Review of Accounting Studies.",
        "url": "https://ideas.repec.org/a/spr/reaccs/v27y2022i3d10.1007_s11142-022-09692-2.html",
        "use": "Motivates the gap between fund ESG positioning and proxy voting behavior.",
    },
    {
        "citation": "SEC (2022), SEC Adopts Rules to Enhance Proxy Voting Disclosure by Registered Funds and Require Disclosure of Say-on-Pay Votes for Institutional Investment Managers.",
        "url": "https://www.sec.gov/newsroom/press-releases/2022-198",
        "use": "Regulatory context for Form N-PX vote disclosure; full N-PX panel is outside this public-data pilot.",
    },
    {
        "citation": "Tidy Finance (2025), ISS Shareholder Proposals data tutorial.",
        "url": "https://www.tidy-finance.org/blog/iss-shareholder-proposals/",
        "use": "Documents richer WRDS/ISS proposal fields and highlights why this pilot is a bounded public-data substitute.",
    },
]

PUBLIC_GOODS_KEYWORDS = [
    "ai",
    "animal",
    "biodiversity",
    "civil rights",
    "climate",
    "deforestation",
    "diversity",
    "emission",
    "environment",
    "equality",
    "greenhouse",
    "health",
    "human rights",
    "labor",
    "lobbying",
    "misinformation",
    "net zero",
    "political",
    "privacy",
    "racial",
    "social",
    "sustainability",
    "worker",
]

DEMOCRACY_KEYWORDS = [
    "board",
    "chairman independence",
    "classified board",
    "cumulative voting",
    "director",
    "independent chair",
    "majority vote",
    "proxy access",
    "shareholder rights",
    "simple majority",
    "special meeting",
    "supermajority",
    "vote",
    "voting",
    "written consent",
]

SECTOR_ETFS = {
    "basic_materials": "XLB",
    "communication_services": "XLC",
    "consumer_discretionary": "XLY",
    "consumer_staples": "XLP",
    "energy": "XLE",
    "financials": "XLF",
    "health_care": "XLV",
    "industrials": "XLI",
    "real_estate": "XLRE",
    "technology": "XLK",
    "utilities": "XLU",
}


@dataclass
class EventBuildDiagnostics:
    rows_total: int
    rows_with_price: int
    rows_missing_price: int
    rows_missing_baseline: int
    unique_tickers_with_rows: int
    unique_tickers_requested: int


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def fetch_json(url: str, params: dict | None = None, timeout: tuple[int, int] = (8, 20)) -> dict:
    headers = {"User-Agent": "volpred-codex-research/1.0"}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after retries: {url} params={params}") from last_error


def fetch_proxy_monitor(force: bool = False) -> list[dict]:
    cache = RAW_DIR / "proxy_monitor_proposals_2020_2024_window_raw.json"
    partial_cache = RAW_DIR / "proxy_monitor_proposals_2020_2024_window_partial.json"
    meta_cache = RAW_DIR / "proxy_monitor_fetch_meta.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text())

    first = fetch_json(PROXY_MONITOR_URL, {"limit": 200, "offset": 0})
    count = int(first.get("count", 0))
    proposals = list(first.get("results", []))
    offset = len(proposals)
    stop_reason = "api_exhausted"
    partial_cache.write_text(json.dumps(proposals, indent=2, sort_keys=True))

    while offset < count:
        payload = fetch_json(PROXY_MONITOR_URL, {"limit": 200, "offset": offset})
        batch = payload.get("results", [])
        if not batch:
            stop_reason = "empty_batch"
            break
        proposals.extend(batch)
        offset += len(batch)
        partial_cache.write_text(json.dumps(proposals, indent=2, sort_keys=True))

        batch_dates = pd.to_datetime(
            [((item.get("vote_results") or {}).get("date") or item.get("date")) for item in batch],
            errors="coerce",
        )
        batch_years = [int(ts.year) for ts in batch_dates if not pd.isna(ts)]
        if batch_years and max(batch_years) < START_YEAR:
            stop_reason = f"reached_batch_before_{START_YEAR}"
            break
        if offset % 1000 == 0:
            print(f"Fetched Proxy Monitor rows: {offset}/{count}", flush=True)
        time.sleep(0.05)

    cache.write_text(json.dumps(proposals, indent=2, sort_keys=True))
    meta_cache.write_text(
        json.dumps(
            {
                "api_reported_count": count,
                "fetched_rows": len(proposals),
                "analysis_window": [START_YEAR, END_YEAR],
                "stop_reason": stop_reason,
                "note": "API appears date-descending; fetch stops once a whole batch is before the analysis start year.",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return proposals


def fetch_as_you_sow_snapshot(force: bool = False) -> list[dict]:
    cache = RAW_DIR / "as_you_sow_resolutions_snapshot.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text())
    response = requests.get(AS_YOU_SOW_URL, timeout=30, headers={"User-Agent": "volpred-codex-research/1.0"})
    response.raise_for_status()
    data = response.json()
    cache.write_text(json.dumps(data, indent=2, sort_keys=True))
    return data


def nested_name(value: dict | None) -> str:
    if not isinstance(value, dict):
        return ""
    name = value.get("name")
    return str(name).strip() if name is not None else ""


def parse_vote_fraction(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        text = str(value)
        match = re.search(r"[-+]?\d*\.?\d+", text)
        if not match:
            return None
        out = float(match.group(0))
    if out > 1:
        out = out / 100.0
    if out < 0 or out > 1:
        return None
    return out


def normalize_ticker(ticker: object) -> str | None:
    if ticker is None:
        return None
    text = str(ticker).strip().upper()
    if not text:
        return None
    text = text.replace("/", "-").replace(".", "-")
    if not re.match(r"^[A-Z0-9-]+$", text):
        return None
    if not re.search(r"[A-Z0-9]", text):
        return None
    return text


def classify_public_goods(general: str, specific: str, title: str, description: str) -> bool:
    text = " ".join([general, specific, title, description]).lower()
    if general.lower() in {"social policy", "environmental"}:
        return True
    return any(keyword in text for keyword in PUBLIC_GOODS_KEYWORDS)


def classify_democracy(general: str, specific: str, title: str, description: str) -> bool:
    text = " ".join([general, specific, title, description]).lower()
    if general.lower() in {"voting rules"}:
        return True
    if general.lower() == "corporate governance" and any(keyword in text for keyword in DEMOCRACY_KEYWORDS):
        return True
    return any(keyword in text for keyword in DEMOCRACY_KEYWORDS)


def normalize_proposals(proposals: list[dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for item in proposals:
        company = item.get("company") or {}
        vote = item.get("vote_results") or {}
        general = nested_name(item.get("proposal_type_general"))
        specific = nested_name(item.get("proposal_type_specific"))
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        event_date_raw = vote.get("date") or item.get("date")
        event_date = pd.to_datetime(event_date_raw, errors="coerce")
        if pd.isna(event_date):
            continue
        ticker = normalize_ticker(company.get("ticker"))
        public_goods = classify_public_goods(general, specific, title, description)
        democracy = classify_democracy(general, specific, title, description)
        vote_for = parse_vote_fraction(vote.get("perc_for_votes"))
        rows.append(
            {
                "proposal_id": item.get("id"),
                "accession_number": item.get("accession_number"),
                "event_date": event_date.normalize(),
                "year": int(event_date.year),
                "company_name": str(company.get("name") or "").strip(),
                "ticker": ticker,
                "raw_ticker": company.get("ticker"),
                "industry": nested_name(company.get("primary_industry")),
                "title": title,
                "description": description,
                "proposal_type_general": general,
                "proposal_type_specific": specific,
                "proponent_name": nested_name(item.get("proponent")),
                "vote_for_fraction": vote_for,
                "close_vote_30_70": bool(vote_for is not None and 0.30 <= vote_for <= 0.70),
                "public_goods": bool(public_goods),
                "shareholder_democracy": bool(democracy),
                "def_14a_url": item.get("def_fourteen_a_ref"),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["event_date", "ticker", "proposal_id"], na_position="last").reset_index(drop=True)
    return df


def aggregate_firm_events(proposals: pd.DataFrame) -> pd.DataFrame:
    sample = proposals[
        proposals["ticker"].notna()
        & proposals["event_date"].notna()
        & proposals["year"].between(START_YEAR, END_YEAR)
    ].copy()
    if sample.empty:
        return sample

    def compact_titles(values: pd.Series) -> str:
        titles = [str(v) for v in values.dropna().head(3)]
        return " | ".join(titles)

    grouped = (
        sample.groupby(["ticker", "event_date"], as_index=False)
        .agg(
            company_name=("company_name", "first"),
            industry=("industry", "first"),
            year=("year", "first"),
            proposal_count=("proposal_id", "count"),
            public_goods_count=("public_goods", "sum"),
            democracy_count=("shareholder_democracy", "sum"),
            close_vote_count=("close_vote_30_70", "sum"),
            max_vote_for=("vote_for_fraction", "max"),
            mean_vote_for=("vote_for_fraction", "mean"),
            proposal_type_general=("proposal_type_general", lambda x: "|".join(sorted(set(x.dropna())))),
            proposal_type_specific=("proposal_type_specific", lambda x: "|".join(sorted(set(x.dropna()))[:5])),
            titles=("title", compact_titles),
        )
        .sort_values(["event_date", "ticker"])
        .reset_index(drop=True)
    )
    grouped["public_goods_event"] = grouped["public_goods_count"] > 0
    grouped["democracy_event"] = grouped["democracy_count"] > 0
    grouped["close_vote_event"] = grouped["close_vote_count"] > 0
    grouped["treatment_public_or_democracy"] = grouped["public_goods_event"] | grouped["democracy_event"]
    return grouped


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for idx in range(0, len(values), size):
        yield values[idx : idx + size]


def extract_adj_close(downloaded: pd.DataFrame, requested: list[str]) -> pd.DataFrame:
    if downloaded is None or downloaded.empty:
        return pd.DataFrame()
    if isinstance(downloaded.columns, pd.MultiIndex):
        levels = downloaded.columns
        if "Adj Close" in levels.get_level_values(1):
            adj = downloaded.xs("Adj Close", axis=1, level=1)
        elif "Adj Close" in levels.get_level_values(0):
            adj = downloaded.xs("Adj Close", axis=1, level=0)
        elif "Close" in levels.get_level_values(1):
            adj = downloaded.xs("Close", axis=1, level=1)
        elif "Close" in levels.get_level_values(0):
            adj = downloaded.xs("Close", axis=1, level=0)
        else:
            return pd.DataFrame()
        adj.columns = [str(c).upper().replace(".", "-").replace("/", "-") for c in adj.columns]
        return adj
    column = "Adj Close" if "Adj Close" in downloaded.columns else "Close"
    if column not in downloaded.columns:
        return pd.DataFrame()
    symbol = requested[0]
    return downloaded[[column]].rename(columns={column: symbol})


def download_one_price_series(symbol: str, force: bool = False) -> pd.Series | None:
    cache = RAW_DIR / f"yfinance_{symbol}_{PRICE_START}_{PRICE_END}_adj_close.csv"
    if cache.exists() and not force:
        frame = pd.read_csv(cache, parse_dates=["Date"], index_col="Date")
        if "Adj Close" in frame.columns:
            series = pd.to_numeric(frame["Adj Close"], errors="coerce").dropna()
            series.name = symbol
            return series

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            downloaded = yf.download(
                symbol,
                start=PRICE_START,
                end=PRICE_END,
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=15,
            )
        except Exception:
            return None
    adj = extract_adj_close(downloaded, [symbol])
    if adj.empty or symbol not in adj.columns:
        return None
    series = pd.to_numeric(adj[symbol], errors="coerce").dropna()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    if series.size < ROLLING_BASELINE_DAYS + 5:
        return None
    series.to_frame("Adj Close").to_csv(cache, index_label="Date")
    series.name = symbol
    return series


def download_price_panel(tickers: Iterable[str], force: bool = False) -> pd.DataFrame:
    requested = sorted({t for t in tickers if t})
    cache = RAW_DIR / f"yfinance_adj_close_{PRICE_START}_{PRICE_END}_{len(requested)}tickers.csv"
    if cache.exists() and not force:
        prices = pd.read_csv(cache, parse_dates=["Date"], index_col="Date")
        prices.index = pd.to_datetime(prices.index).tz_localize(None)
        return prices.sort_index()

    frames: list[pd.Series] = []
    failures: list[str] = []
    for idx, symbol in enumerate(requested, start=1):
        series = download_one_price_series(symbol, force=force)
        if series is None:
            failures.append(symbol)
        else:
            frames.append(series)
        if idx % 25 == 0 or idx == len(requested):
            print(
                f"Downloaded yfinance symbols: {idx}/{len(requested)} "
                f"(ok={len(frames)}, failed={len(failures)})",
                flush=True,
            )
        time.sleep(0.05)

    if not frames:
        return pd.DataFrame()
    prices = pd.concat(frames, axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()].sort_index()
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    prices.to_csv(cache, index_label="Date")
    (RAW_DIR / "yfinance_failed_symbols.json").write_text(json.dumps(failures, indent=2, sort_keys=True))
    return prices


def map_industry_to_sector_etf(industry: str) -> tuple[str | None, str | None]:
    text = (industry or "").lower()
    rules = [
        ("energy", "XLE", ["oil", "gas", "energy", "coal", "petroleum"]),
        ("financials", "XLF", ["bank", "financial", "insurance", "broker", "investment"]),
        ("health_care", "XLV", ["drug", "health", "medical", "pharma", "biotech", "hospital"]),
        ("technology", "XLK", ["software", "computer", "semiconductor", "electronic", "internet", "information"]),
        ("communication_services", "XLC", ["telecom", "media", "broadcast", "entertainment"]),
        ("consumer_discretionary", "XLY", ["retail", "auto", "hotel", "restaurant", "apparel", "consumer"]),
        ("consumer_staples", "XLP", ["food", "beverage", "tobacco", "grocery", "household"]),
        ("industrials", "XLI", ["air", "transport", "machinery", "aerospace", "industrial", "railroad"]),
        ("basic_materials", "XLB", ["chemical", "metal", "mining", "paper", "materials"]),
        ("utilities", "XLU", ["utility", "electric", "water", "power"]),
        ("real_estate", "XLRE", ["real estate", "reit"]),
    ]
    for sector, etf, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return sector, etf
    return None, None


def build_event_rows(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    symbol_col: str,
    event_kind: str,
) -> tuple[pd.DataFrame, EventBuildDiagnostics]:
    rows: list[dict] = []
    missing_price = 0
    missing_baseline = 0
    requested_symbols = sorted(set(events[symbol_col].dropna()))

    for symbol, symbol_events in events.groupby(symbol_col):
        if symbol not in prices.columns:
            missing_price += len(symbol_events)
            continue
        close = pd.to_numeric(prices[symbol], errors="coerce").dropna()
        close = close[~close.index.duplicated(keep="last")].sort_index()
        if close.size < ROLLING_BASELINE_DAYS + 5:
            missing_price += len(symbol_events)
            continue

        returns = np.log(close).diff()
        r2 = returns.pow(2)
        baseline = r2.rolling(ROLLING_BASELINE_DAYS, min_periods=ROLLING_MIN_DAYS).mean().shift(1)

        raw_event_signal = pd.Series(0.0, index=close.index)
        event_map: dict[pd.Timestamp, list[dict]] = {}
        for _, event in symbol_events.iterrows():
            pos = close.index.searchsorted(pd.Timestamp(event["event_date"]), side="left")
            if pos >= len(close.index) - 1:
                missing_price += 1
                continue
            event_trade_date = close.index[pos]
            raw_event_signal.loc[event_trade_date] += float(event.get("event_weight", 1.0))
            event_map.setdefault(event_trade_date, []).append(event.to_dict())

        # Explicit no-lookahead alignment: signal observed at t-1, return target at t.
        signal_lag1 = raw_event_signal.shift(1).fillna(0.0)

        for event_trade_date, event_dicts in event_map.items():
            target_pos = close.index.get_loc(event_trade_date) + 1
            if target_pos >= len(close.index):
                missing_price += len(event_dicts)
                continue
            target_date = close.index[target_pos]
            if signal_lag1.loc[target_date] <= 0:
                raise RuntimeError("Lagged event signal alignment failed; potential lookahead bug.")
            target_r2 = float(r2.loc[target_date])
            baseline_var = float(baseline.loc[target_date])
            if not np.isfinite(target_r2) or not np.isfinite(baseline_var) or baseline_var <= 0:
                missing_baseline += len(event_dicts)
                continue
            event_frame = pd.DataFrame(event_dicts)
            row = {
                "event_kind": event_kind,
                "symbol": symbol,
                "event_trade_date": event_trade_date,
                "target_date": target_date,
                "target_year": int(target_date.year),
                "target_r2": target_r2,
                "baseline_var": baseline_var,
                "abnormal_var": target_r2 - baseline_var,
                "abnormal_var_scaled": target_r2 / max(baseline_var, EPS) - 1.0,
                "abnormal_log_rv": math.log(max(target_r2, EPS)) - math.log(max(baseline_var, EPS)),
                "event_count": int(event_frame.get("proposal_count", pd.Series([1])).sum()),
                "public_goods_count": int(event_frame.get("public_goods_count", pd.Series([0])).sum()),
                "democracy_count": int(event_frame.get("democracy_count", pd.Series([0])).sum()),
                "close_vote_count": int(event_frame.get("close_vote_count", pd.Series([0])).sum()),
                "public_goods_event": bool(event_frame.get("public_goods_event", pd.Series([False])).any()),
                "democracy_event": bool(event_frame.get("democracy_event", pd.Series([False])).any()),
                "close_vote_event": bool(event_frame.get("close_vote_event", pd.Series([False])).any()),
                "company_name": str(event_frame.get("company_name", pd.Series([""])).iloc[0]),
                "industry": str(event_frame.get("industry", pd.Series([""])).iloc[0]),
                "titles": str(event_frame.get("titles", pd.Series([""])).iloc[0]),
            }
            rows.append(row)

    out = pd.DataFrame(rows)
    diagnostics = EventBuildDiagnostics(
        rows_total=int(len(events)),
        rows_with_price=int(len(out)),
        rows_missing_price=int(missing_price),
        rows_missing_baseline=int(missing_baseline),
        unique_tickers_with_rows=int(out["symbol"].nunique()) if not out.empty else 0,
        unique_tickers_requested=int(len(requested_symbols)),
    )
    return out, diagnostics


def one_sample_summary(values: pd.Series, label: str, rng: np.random.Generator) -> dict:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if clean.size == 0:
        return {"label": label, "n": 0}
    if clean.size >= 2:
        t_stat, p_value = stats.ttest_1samp(clean, 0.0)
    else:
        t_stat, p_value = np.nan, np.nan
    reps = []
    for _ in range(BOOTSTRAP_REPS):
        reps.append(float(rng.choice(clean, size=clean.size, replace=True).mean()))
    ci_low, ci_high = np.percentile(reps, [2.5, 97.5])
    return {
        "label": label,
        "n": int(clean.size),
        "mean": float(clean.mean()),
        "median": float(np.median(clean)),
        "std": float(clean.std(ddof=1)) if clean.size >= 2 else 0.0,
        "t_stat": float(t_stat) if np.isfinite(t_stat) else None,
        "p_value": float(p_value) if np.isfinite(p_value) else None,
        "bootstrap_mean_ci_95": [float(ci_low), float(ci_high)],
    }


def welch_summary(a: pd.Series, b: pd.Series, label: str, rng: np.random.Generator) -> dict:
    x = pd.to_numeric(a, errors="coerce").dropna().to_numpy(dtype=float)
    y = pd.to_numeric(b, errors="coerce").dropna().to_numpy(dtype=float)
    if x.size == 0 or y.size == 0:
        return {"label": label, "n_a": int(x.size), "n_b": int(y.size)}
    if x.size >= 2 and y.size >= 2:
        t_stat, p_value = stats.ttest_ind(x, y, equal_var=False)
    else:
        t_stat, p_value = np.nan, np.nan
    reps = []
    for _ in range(BOOTSTRAP_REPS):
        reps.append(
            float(
                rng.choice(x, size=x.size, replace=True).mean()
                - rng.choice(y, size=y.size, replace=True).mean()
            )
        )
    ci_low, ci_high = np.percentile(reps, [2.5, 97.5])
    return {
        "label": label,
        "n_a": int(x.size),
        "n_b": int(y.size),
        "mean_a": float(x.mean()),
        "mean_b": float(y.mean()),
        "mean_diff_a_minus_b": float(x.mean() - y.mean()),
        "t_stat": float(t_stat) if np.isfinite(t_stat) else None,
        "p_value": float(p_value) if np.isfinite(p_value) else None,
        "bootstrap_mean_diff_ci_95": [float(ci_low), float(ci_high)],
    }


def clustered_ols_summary(rows: pd.DataFrame) -> dict:
    needed = ["abnormal_var_scaled", "public_goods_event", "democracy_event", "close_vote_event", "event_count", "target_date"]
    frame = rows[needed].dropna().copy()
    if frame.empty or frame["target_date"].nunique() < 10:
        return {"available": False, "reason": "insufficient rows or date clusters"}
    frame["const"] = 1.0
    frame["public_goods_event"] = frame["public_goods_event"].astype(float)
    frame["democracy_event"] = frame["democracy_event"].astype(float)
    frame["close_vote_event"] = frame["close_vote_event"].astype(float)
    frame["log_event_count"] = np.log1p(frame["event_count"].astype(float))
    xcols = ["const", "public_goods_event", "democracy_event", "close_vote_event", "log_event_count"]
    model = sm.OLS(frame["abnormal_var_scaled"].astype(float), frame[xcols].astype(float))
    try:
        fit = model.fit().get_robustcov_results(cov_type="cluster", groups=frame["target_date"].astype(str))
        params = dict(zip(xcols, fit.params))
        tvals = dict(zip(xcols, fit.tvalues))
        pvals = dict(zip(xcols, fit.pvalues))
    except Exception as exc:
        return {"available": False, "reason": f"clustered OLS failed: {exc}"}
    return {
        "available": True,
        "dependent_variable": "target_r2 / prior_60d_baseline_var - 1",
        "n_obs": int(frame.shape[0]),
        "date_clusters": int(frame["target_date"].nunique()),
        "coefficients": {k: float(v) for k, v in params.items()},
        "cluster_t": {k: float(v) for k, v in tvals.items()},
        "p_values": {k: float(v) for k, v in pvals.items()},
    }


def qlike(y: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    y = np.maximum(y.astype(float), EPS)
    forecast = np.maximum(forecast.astype(float), EPS)
    return np.log(forecast) + y / forecast


def oos_qlike_test(rows: pd.DataFrame, rng: np.random.Generator) -> dict:
    public_rows = rows[rows["public_goods_event"]].copy()
    train = public_rows[public_rows["target_year"] <= TRAIN_END_YEAR]
    test = public_rows[public_rows["target_year"] > TRAIN_END_YEAR]
    if train.shape[0] < 20 or test.shape[0] < 20:
        return {
            "available": False,
            "reason": "insufficient public-goods train/test event rows",
            "train_n": int(train.shape[0]),
            "test_n": int(test.shape[0]),
        }
    gamma = float(train["abnormal_var_scaled"].mean())
    multiplier = max(0.05, 1.0 + gamma)
    y = test["target_r2"].to_numpy(dtype=float)
    base = test["baseline_var"].to_numpy(dtype=float)
    addon = np.maximum(base * multiplier, EPS)
    base_loss = qlike(y, base)
    addon_loss = qlike(y, addon)
    loss_diff = addon_loss - base_loss
    t_stat, p_value = stats.ttest_1samp(loss_diff, 0.0)
    reps = []
    for _ in range(BOOTSTRAP_REPS):
        sample = rng.choice(loss_diff, size=loss_diff.size, replace=True)
        reps.append(float(sample.mean()))
    ci_low, ci_high = np.percentile(reps, [2.5, 97.5])
    return {
        "available": True,
        "train_n": int(train.shape[0]),
        "test_n": int(test.shape[0]),
        "train_mean_scaled_abnormal_var_gamma": gamma,
        "forecast_variance_multiplier": multiplier,
        "baseline_mean_qlike": float(base_loss.mean()),
        "addon_mean_qlike": float(addon_loss.mean()),
        "loss_diff_addon_minus_baseline": float(loss_diff.mean()),
        "paired_t_stat": float(t_stat) if np.isfinite(t_stat) else None,
        "paired_p_value": float(p_value) if np.isfinite(p_value) else None,
        "bootstrap_loss_diff_ci_95": [float(ci_low), float(ci_high)],
        "interpretation": "negative loss_diff means the event add-on improved QLIKE",
    }


def build_sector_events(firm_events: pd.DataFrame) -> pd.DataFrame:
    public_events = firm_events[firm_events["public_goods_event"]].copy()
    sector_rows: list[dict] = []
    for _, row in public_events.iterrows():
        sector, etf = map_industry_to_sector_etf(str(row.get("industry") or ""))
        if etf is None:
            continue
        sector_rows.append(
            {
                "sector": sector,
                "sector_etf": etf,
                "event_date": row["event_date"],
                "company_name": row["company_name"],
                "industry": row["industry"],
                "proposal_count": row["public_goods_count"],
                "public_goods_count": row["public_goods_count"],
                "democracy_count": row["democracy_count"],
                "close_vote_count": row["close_vote_count"],
                "public_goods_event": True,
                "democracy_event": bool(row["democracy_event"]),
                "close_vote_event": bool(row["close_vote_event"]),
                "titles": row["titles"],
                "event_weight": 1.0,
            }
        )
    if not sector_rows:
        return pd.DataFrame()
    sector_events = pd.DataFrame(sector_rows)
    grouped = (
        sector_events.groupby(["sector_etf", "event_date"], as_index=False)
        .agg(
            company_name=("company_name", lambda x: "|".join(sorted(set(x.dropna().astype(str)))[:5])),
            industry=("sector", "first"),
            proposal_count=("proposal_count", "sum"),
            public_goods_count=("public_goods_count", "sum"),
            democracy_count=("democracy_count", "sum"),
            close_vote_count=("close_vote_count", "sum"),
            public_goods_event=("public_goods_event", "max"),
            democracy_event=("democracy_event", "max"),
            close_vote_event=("close_vote_event", "max"),
            titles=("titles", "first"),
            event_weight=("event_weight", "sum"),
        )
        .sort_values(["event_date", "sector_etf"])
        .reset_index(drop=True)
    )
    return grouped


def make_figures(proposals: pd.DataFrame, firm_rows: pd.DataFrame, sector_rows: pd.DataFrame) -> list[str]:
    paths: list[str] = []

    fig, ax = plt.subplots(figsize=(9, 5))
    counts = proposals[proposals["year"].between(START_YEAR, END_YEAR)].groupby(["year", "public_goods"]).size().unstack(fill_value=0)
    counts = counts.rename(columns={False: "other", True: "public_goods"})
    counts.plot(kind="bar", stacked=True, ax=ax, color=["#6b7280", "#0f766e"])
    ax.set_title("Proxy Monitor shareholder proposal counts")
    ax.set_xlabel("Year")
    ax.set_ylabel("Proposal count")
    ax.legend(loc="upper left")
    fig.tight_layout()
    path = FIG_DIR / "proposal_counts_by_year.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    if not firm_rows.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        public_vals = firm_rows.loc[firm_rows["public_goods_event"], "abnormal_var_scaled"].clip(-1, 5)
        control_vals = firm_rows.loc[~firm_rows["public_goods_event"], "abnormal_var_scaled"].clip(-1, 5)
        ax.hist(control_vals, bins=50, alpha=0.55, label="other proposal events", color="#64748b", density=True)
        ax.hist(public_vals, bins=50, alpha=0.55, label="public-goods events", color="#dc2626", density=True)
        ax.axvline(0, color="black", linewidth=1)
        ax.set_title("Firm next-day scaled abnormal realized variance")
        ax.set_xlabel("target r2 / prior 60-day baseline variance - 1 (clipped at 5 for display)")
        ax.set_ylabel("Density")
        ax.legend()
        fig.tight_layout()
        path = FIG_DIR / "firm_scaled_abnormal_rv_distribution.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(ROOT)))

    if not sector_rows.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        sector_means = sector_rows.groupby("symbol")["abnormal_var_scaled"].agg(["mean", "count"]).sort_values("mean")
        sector_means["mean"].plot(kind="barh", ax=ax, color="#2563eb")
        ax.axvline(0, color="black", linewidth=1)
        ax.set_title("Sector ETF next-day scaled abnormal RV after public-goods proposal events")
        ax.set_xlabel("Mean target r2 / prior 60-day baseline variance - 1")
        for idx, (_, row) in enumerate(sector_means.iterrows()):
            ax.text(row["mean"], idx, f" n={int(row['count'])}", va="center", fontsize=8)
        fig.tight_layout()
        path = FIG_DIR / "sector_spillover_scaled_abnormal_rv.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(ROOT)))

    return paths


def json_default(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def determine_verdict(firm_public: dict, diff_public_vs_other: dict, oos: dict, sector_public: dict) -> str:
    firm_ci = firm_public.get("bootstrap_mean_ci_95") or [None, None]
    diff_ci = diff_public_vs_other.get("bootstrap_mean_diff_ci_95") or [None, None]
    sector_ci = sector_public.get("bootstrap_mean_ci_95") or [None, None]
    firm_positive = firm_ci[0] is not None and firm_ci[0] > 0
    diff_positive = diff_ci[0] is not None and diff_ci[0] > 0
    sector_positive = sector_ci[0] is not None and sector_ci[0] > 0
    oos_improves = bool(
        oos.get("available")
        and oos.get("bootstrap_loss_diff_ci_95", [1, 1])[1] < 0
    )
    if firm_positive and diff_positive and oos_improves:
        return "positive_firm_predictive"
    if firm_positive or diff_positive or sector_positive:
        return "mixed_weak_positive"
    return "null_or_inconclusive"


def main() -> None:
    ensure_dirs()
    rng = np.random.default_rng(SEED)

    raw_proposals = fetch_proxy_monitor()
    proxy_meta_path = RAW_DIR / "proxy_monitor_fetch_meta.json"
    proxy_fetch_meta = json.loads(proxy_meta_path.read_text()) if proxy_meta_path.exists() else {}
    as_you_sow = fetch_as_you_sow_snapshot()
    proposals = normalize_proposals(raw_proposals)
    proposals.to_csv(DATA_DIR / "proxy_monitor_proposals_normalized.csv", index=False)

    firm_events = aggregate_firm_events(proposals)
    firm_events.to_csv(DATA_DIR / "firm_proposal_events_aggregated.csv", index=False)

    unique_tickers = sorted(set(firm_events["ticker"].dropna()))
    sector_events = build_sector_events(firm_events)
    sector_tickers = sorted(set(sector_events["sector_etf"].dropna())) if not sector_events.empty else []
    prices = download_price_panel(unique_tickers + sector_tickers)

    firm_rows, firm_diag = build_event_rows(firm_events, prices, "ticker", "firm")
    firm_rows.to_csv(DATA_DIR / "firm_event_risk_rows.csv", index=False)

    if not sector_events.empty:
        sector_rows, sector_diag = build_event_rows(sector_events, prices, "sector_etf", "sector_etf")
    else:
        sector_rows, sector_diag = pd.DataFrame(), EventBuildDiagnostics(0, 0, 0, 0, 0, 0)
    sector_rows.to_csv(DATA_DIR / "sector_event_risk_rows.csv", index=False)

    public_rows = firm_rows[firm_rows["public_goods_event"]] if not firm_rows.empty else pd.DataFrame()
    other_rows = firm_rows[~firm_rows["public_goods_event"]] if not firm_rows.empty else pd.DataFrame()
    democracy_rows = firm_rows[firm_rows["democracy_event"]] if not firm_rows.empty else pd.DataFrame()
    close_public_rows = firm_rows[firm_rows["public_goods_event"] & firm_rows["close_vote_event"]] if not firm_rows.empty else pd.DataFrame()

    firm_public = one_sample_summary(
        public_rows.get("abnormal_var_scaled", pd.Series(dtype=float)),
        "firm_public_goods_scaled_abnormal_rv",
        rng,
    )
    firm_other = one_sample_summary(
        other_rows.get("abnormal_var_scaled", pd.Series(dtype=float)),
        "firm_other_proposal_scaled_abnormal_rv",
        rng,
    )
    firm_democracy = one_sample_summary(
        democracy_rows.get("abnormal_var_scaled", pd.Series(dtype=float)),
        "firm_shareholder_democracy_scaled_abnormal_rv",
        rng,
    )
    firm_close_public = one_sample_summary(
        close_public_rows.get("abnormal_var_scaled", pd.Series(dtype=float)),
        "firm_close_vote_public_goods_scaled_abnormal_rv",
        rng,
    )
    diff_public_vs_other = welch_summary(
        public_rows.get("abnormal_var_scaled", pd.Series(dtype=float)),
        other_rows.get("abnormal_var_scaled", pd.Series(dtype=float)),
        "public_goods_minus_other_proposal_events",
        rng,
    )
    clustered_ols = clustered_ols_summary(firm_rows)
    oos = oos_qlike_test(firm_rows, rng)

    sector_public = one_sample_summary(
        sector_rows.get("abnormal_var_scaled", pd.Series(dtype=float)),
        "sector_etf_public_goods_event_scaled_abnormal_rv",
        rng,
    )

    figure_paths = make_figures(proposals, firm_rows, sector_rows)
    verdict = determine_verdict(firm_public, diff_public_vs_other, oos, sector_public)

    sample = proposals[proposals["year"].between(START_YEAR, END_YEAR)].copy()
    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "research_question": "Do shareholder-democracy/public-goods proposal votes predict next-day firm realized variance or sector spillover?",
        "bounded_pilot_note": (
            "This uses public Proxy Monitor proposal/vote events and daily yfinance prices. "
            "It is not a full Form N-PX or ISS/FactSet mutual-fund-vote panel."
        ),
        "lookahead_control": "Event signal is aligned with raw_event_signal.shift(1); target r2 is the next close-to-close return variance.",
        "data_sources": {
            "proxy_monitor_api": PROXY_MONITOR_URL,
            "as_you_sow_snapshot": AS_YOU_SOW_URL,
            "prices": "yfinance daily adjusted close downloaded with auto_adjust=False, then explicit Adj Close column",
        },
        "sample": {
            "proxy_monitor_api_reported_count": proxy_fetch_meta.get("api_reported_count"),
            "proxy_monitor_fetch_stop_reason": proxy_fetch_meta.get("stop_reason"),
            "proxy_monitor_raw_proposals": int(len(raw_proposals)),
            "proxy_monitor_normalized_proposals": int(len(proposals)),
            "analysis_years": [START_YEAR, END_YEAR],
            "analysis_proposals": int(len(sample)),
            "analysis_unique_firms": int(sample["ticker"].nunique()),
            "public_goods_proposals": int(sample["public_goods"].sum()),
            "shareholder_democracy_proposals": int(sample["shareholder_democracy"].sum()),
            "close_vote_30_70_proposals": int(sample["close_vote_30_70"].sum()),
            "firm_aggregated_events": int(len(firm_events)),
            "sector_aggregated_events": int(len(sector_events)),
            "as_you_sow_snapshot_rows": int(len(as_you_sow)),
        },
        "classification_counts": {
            "by_year_public_goods": {
                str(k[0]) + "|" + str(k[1]): int(v)
                for k, v in sample.groupby(["year", "public_goods"]).size().to_dict().items()
            },
            "proposal_type_general": {
                str(k): int(v) for k, v in sample["proposal_type_general"].value_counts(dropna=False).to_dict().items()
            },
            "top_proposal_type_specific": {
                str(k): int(v)
                for k, v in sample["proposal_type_specific"].value_counts(dropna=False).head(20).to_dict().items()
            },
        },
        "event_build_diagnostics": {
            "firm": firm_diag.__dict__,
            "sector": sector_diag.__dict__,
            "price_panel_shape": list(prices.shape),
            "price_panel_start": prices.index.min().isoformat() if not prices.empty else None,
            "price_panel_end": prices.index.max().isoformat() if not prices.empty else None,
        },
        "firm_event_results": {
            "public_goods": firm_public,
            "other_proposals": firm_other,
            "shareholder_democracy": firm_democracy,
            "close_vote_public_goods": firm_close_public,
            "public_goods_vs_other": diff_public_vs_other,
            "clustered_ols": clustered_ols,
            "oos_qlike_public_goods_addon": oos,
        },
        "sector_spillover_results": {
            "public_goods_sector_etf": sector_public,
            "sector_event_counts": {
                str(k): int(v) for k, v in sector_rows["symbol"].value_counts().to_dict().items()
            }
            if not sector_rows.empty
            else {},
        },
        "figures": figure_paths,
        "references": REFERENCES,
        "limitations": [
            "Proxy Monitor is not the complete N-PX mutual-fund-vote panel and may overrepresent large-cap proxy-monitoring coverage.",
            "Ticker-based yfinance histories introduce survivorship/ticker-change gaps; missing-price rows are reported in diagnostics.",
            "Meeting/vote dates are aligned conservatively to next trading-day returns, not intraday announcement times.",
            "Sector spillover uses coarse industry-to-sector ETF mapping, not full supply-chain or sector-neutral peer portfolios.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True, default=json_default))
    print(json.dumps({"ok": True, "results_path": str(RESULTS_PATH), "verdict": verdict}, indent=2))


if __name__ == "__main__":
    main()
