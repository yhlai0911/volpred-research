#!/usr/bin/env python3
"""Firm-level labor-shortage public-proxy volatility diagnostic.

This is not a replication of the RFS earnings-call FinBERT labor-shortage
measure. It uses only public SEC filing text phrase counts plus BLS JOLTS
industry tightness, then tests whether the lagged proxy predicts subsequent
firm idiosyncratic RV/downside.

Lookahead policy:
    - SEC filing text enters the signal only after the filing date and one
      trading-day lag.
    - BLS JOLTS monthly values are assumed observable 35 calendar days after
      month end, then shifted one trading day.
    - Forward RV/downside targets start at t+1.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "research_firm_level_labor_shortage_exposure_wage_sensitiv"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = FIG_DIR / "labor_shortage_proxy_summary.png"

SEED = 42
START_DATE = "2021-01-01"
END_DATE = "2026-07-03"
MAX_FILINGS_PER_TICKER = 12
SEC_SLEEP_SECONDS = 0.12
HORIZONS = [5, 22]
EPS = 1.0e-12

USER_AGENT = "volpred-research/1.0 yihao.lai@gmail.com"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
BLS_SERIES_URL = "https://download.bls.gov/pub/time.series/jt/jt.series"
BLS_DATA_URL = "https://download.bls.gov/pub/time.series/jt/jt.data.1.AllItems"

COMPANY_TICKERS_CACHE = DATA_DIR / "sec_company_tickers.json"
FILING_INDEX_CACHE = DATA_DIR / "sec_filing_index.csv"
FILING_SCORE_CACHE = DATA_DIR / "sec_labor_filing_scores.csv"
BLS_SERIES_CACHE = DATA_DIR / "bls_jolts_series.csv"
BLS_DATA_CACHE = DATA_DIR / "bls_jolts_allitems.csv"
JOLTS_PANEL_CACHE = DATA_DIR / "jolts_industry_monthly.csv"
PRICE_CACHE = DATA_DIR / "price_adjusted_close.csv"
REGRESSION_PANEL_CACHE = DATA_DIR / "firm_daily_regression_panel.csv"

FIRM_UNIVERSE: dict[str, dict[str, str]] = {
    "LEN": {"industry_code": "230000", "industry": "construction", "control": "XHB"},
    "DHI": {"industry_code": "230000", "industry": "construction", "control": "XHB"},
    "PHM": {"industry_code": "230000", "industry": "construction", "control": "XHB"},
    "HD": {"industry_code": "440000", "industry": "retail", "control": "XRT"},
    "LOW": {"industry_code": "440000", "industry": "retail", "control": "XRT"},
    "WMT": {"industry_code": "440000", "industry": "retail", "control": "XRT"},
    "TGT": {"industry_code": "440000", "industry": "retail", "control": "XRT"},
    "COST": {"industry_code": "440000", "industry": "retail", "control": "XRT"},
    "DG": {"industry_code": "440000", "industry": "retail", "control": "XRT"},
    "AMZN": {"industry_code": "440000", "industry": "retail", "control": "XRT"},
    "UPS": {"industry_code": "480099", "industry": "transport_utilities", "control": "IYT"},
    "FDX": {"industry_code": "480099", "industry": "transport_utilities", "control": "IYT"},
    "DAL": {"industry_code": "480099", "industry": "transport_utilities", "control": "IYT"},
    "UAL": {"industry_code": "480099", "industry": "transport_utilities", "control": "IYT"},
    "LUV": {"industry_code": "480099", "industry": "transport_utilities", "control": "IYT"},
    "MCD": {"industry_code": "720000", "industry": "food_lodging", "control": "XLY"},
    "SBUX": {"industry_code": "720000", "industry": "food_lodging", "control": "XLY"},
    "CMG": {"industry_code": "720000", "industry": "food_lodging", "control": "XLY"},
    "MAR": {"industry_code": "720000", "industry": "food_lodging", "control": "XLY"},
    "HLT": {"industry_code": "720000", "industry": "food_lodging", "control": "XLY"},
    "HCA": {"industry_code": "620000", "industry": "healthcare", "control": "XLV"},
    "THC": {"industry_code": "620000", "industry": "healthcare", "control": "XLV"},
    "CAT": {"industry_code": "300000", "industry": "manufacturing", "control": "XLI"},
    "DE": {"industry_code": "300000", "industry": "manufacturing", "control": "XLI"},
}

CONTROL_TICKERS = sorted({meta["control"] for meta in FIRM_UNIVERSE.values()} | {"SPY", "AIQ"})
PRICE_TICKERS = sorted(FIRM_UNIVERSE) + CONTROL_TICKERS

CORE_PATTERNS = [
    r"labor shortage(?:s)?",
    r"labour shortage(?:s)?",
    r"shortage(?:s)? of labor",
    r"shortage(?:s)? of labour",
    r"labor constraint(?:s)?",
    r"staffing shortage(?:s)?",
    r"worker shortage(?:s)?",
    r"employee shortage(?:s)?",
    r"shortage(?:s)? of qualified",
    r"availability of labor",
    r"availability of qualified",
]
WAGE_PATTERNS = [
    r"wage inflation",
    r"higher wage(?:s)?",
    r"increased labor cost(?:s)?",
    r"labor cost(?:s)? increase",
    r"higher labor cost(?:s)?",
    r"compensation cost(?:s)?",
]
AUTOMATION_PATTERNS = [
    r"automation",
    r"automated",
    r"robotic(?:s)?",
    r"artificial intelligence",
    r"machine learning",
]

LITERATURE_AND_DATA_CONTEXT = [
    {
        "citation": "Firm-Level Labor Shortage Exposure, Review of Financial Studies advance article",
        "url": "https://academic.oup.com/rfs/advance-article/doi/10.1093/rfs/hhag049/8678513",
        "role": "Motivates firm-level labor-shortage exposure; this experiment uses a public SEC phrase-count proxy, not their earnings-call FinBERT measure.",
    },
    {
        "citation": "BLS Job Openings and Labor Turnover Survey",
        "url": "https://www.bls.gov/jlt/",
        "role": "Official industry job-openings and quits rates used as monthly labor-market tightness proxy.",
    },
    {
        "citation": "SEC EDGAR data APIs",
        "url": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "role": "Official submissions API used for 10-K/10-Q filing dates and document locations.",
    },
    {
        "citation": "Mandelman, Yu, and Zanetti (2026), Immigration, Labor Shortages, and Labor Market Dynamics",
        "url": "https://www.lse.ac.uk/CFM/assets/pdf/CFM-Discussion-Papers-2026/CFMDP2026-04-Paper.pdf",
        "role": "Sectoral labor-shortage framing: low labor share plus high vacancy posting as bottleneck evidence.",
    },
]


@dataclass(frozen=True)
class RegressionResult:
    signal: str
    target: str
    horizon: int
    n_obs: int
    n_firms: int
    beta: float
    t_stat: float
    p_value: float
    high_low_diff: float
    high_low_t: float
    high_low_p: float
    high_count: int
    low_count: int
    gate_pass: bool


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


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
    if pd.isna(value):
        return None
    return value


def get_text(url: str, timeout: int = 60) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_company_tickers(refresh: bool = False) -> dict[str, int]:
    ensure_dirs()
    if COMPANY_TICKERS_CACHE.exists() and not refresh:
        raw = json.loads(COMPANY_TICKERS_CACHE.read_text())
    else:
        raw = requests.get(SEC_TICKERS_URL, headers=HEADERS, timeout=60).json()
        COMPANY_TICKERS_CACHE.write_text(json.dumps(raw, indent=2))
    return {entry["ticker"].upper(): int(entry["cik_str"]) for entry in raw.values()}


def fetch_filing_index(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if FILING_INDEX_CACHE.exists() and not refresh:
        return pd.read_csv(FILING_INDEX_CACHE, parse_dates=["filing_date", "report_date"])

    ticker_to_cik = fetch_company_tickers(refresh=refresh)
    rows: list[dict[str, Any]] = []
    for ticker in sorted(FIRM_UNIVERSE):
        cik = ticker_to_cik.get(ticker)
        if cik is None:
            continue
        cik10 = str(cik).zfill(10)
        sub = requests.get(SEC_SUBMISSIONS_URL.format(cik10=cik10), headers=HEADERS, timeout=60).json()
        recent = sub.get("filings", {}).get("recent", {})
        frame = pd.DataFrame(recent)
        if frame.empty:
            continue
        frame = frame[frame["form"].isin(["10-K", "10-Q"])].copy()
        frame["filing_date"] = pd.to_datetime(frame["filingDate"], errors="coerce")
        frame["report_date"] = pd.to_datetime(frame["reportDate"], errors="coerce")
        frame = frame.dropna(subset=["filing_date", "accessionNumber", "primaryDocument"])
        frame = frame[frame["filing_date"] >= START_DATE].sort_values("filing_date", ascending=False)
        frame = frame.head(MAX_FILINGS_PER_TICKER)
        for _, row in frame.iterrows():
            accession = str(row["accessionNumber"])
            document = str(row["primaryDocument"])
            rows.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "form": row["form"],
                    "filing_date": row["filing_date"],
                    "report_date": row["report_date"],
                    "accession": accession,
                    "primary_document": document,
                    "document_url": SEC_ARCHIVES_URL.format(
                        cik=str(cik), accession=accession.replace("-", ""), document=document
                    ),
                }
            )
        time.sleep(SEC_SLEEP_SECONDS)
    out = pd.DataFrame(rows).sort_values(["ticker", "filing_date"])
    out.to_csv(FILING_INDEX_CACHE, index=False)
    return out


def score_filing_text(text: str) -> dict[str, float]:
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"&[a-zA-Z]+;", " ", clean)
    clean = re.sub(r"\s+", " ", clean).lower()
    words = len(re.findall(r"[a-z]+", clean))

    def count_patterns(patterns: list[str]) -> int:
        return int(sum(len(re.findall(pattern, clean)) for pattern in patterns))

    core = count_patterns(CORE_PATTERNS)
    wage = count_patterns(WAGE_PATTERNS)
    automation = count_patterns(AUTOMATION_PATTERNS)
    weighted = core + 0.5 * wage
    per_10k = 10000.0 * weighted / max(words, 1000)
    return {
        "word_count": float(words),
        "core_labor_shortage_hits": float(core),
        "wage_pressure_hits": float(wage),
        "automation_hits": float(automation),
        "labor_shortage_score_per_10k": float(per_10k),
        "labor_shortage_score_log": float(np.log1p(per_10k)),
        "automation_score_log": float(np.log1p(10000.0 * automation / max(words, 1000))),
    }


def fetch_filing_scores(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if FILING_SCORE_CACHE.exists() and not refresh:
        return pd.read_csv(FILING_SCORE_CACHE, parse_dates=["filing_date", "report_date"])

    index = fetch_filing_index(refresh=refresh)
    rows: list[dict[str, Any]] = []
    for _, filing in index.iterrows():
        try:
            text = get_text(str(filing["document_url"]), timeout=60)
            scores = score_filing_text(text)
            error = ""
        except Exception as exc:  # noqa: BLE001 - preserve failed filing rows for audit
            scores = {
                "word_count": np.nan,
                "core_labor_shortage_hits": np.nan,
                "wage_pressure_hits": np.nan,
                "automation_hits": np.nan,
                "labor_shortage_score_per_10k": np.nan,
                "labor_shortage_score_log": np.nan,
                "automation_score_log": np.nan,
            }
            error = repr(exc)
        item = filing.to_dict()
        item.update(scores)
        item["download_error"] = error
        rows.append(item)
        time.sleep(SEC_SLEEP_SECONDS)
    out = pd.DataFrame(rows)
    out.to_csv(FILING_SCORE_CACHE, index=False)
    return out


def fetch_jolts(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if JOLTS_PANEL_CACHE.exists() and not refresh:
        return pd.read_csv(JOLTS_PANEL_CACHE, parse_dates=["month", "release_date"])

    if BLS_SERIES_CACHE.exists() and BLS_DATA_CACHE.exists() and not refresh:
        series = pd.read_csv(BLS_SERIES_CACHE)
        data = pd.read_csv(BLS_DATA_CACHE)
    else:
        series_text = get_text(BLS_SERIES_URL, timeout=60)
        data_text = get_text(BLS_DATA_URL, timeout=120)
        series = pd.read_csv(io.StringIO(series_text), sep="\t")
        data = pd.read_csv(io.StringIO(data_text), sep="\t", low_memory=False)
        series.columns = [c.strip() for c in series.columns]
        data.columns = [c.strip() for c in data.columns]
        series["series_id"] = series["series_id"].astype(str).str.strip()
        data["series_id"] = data["series_id"].astype(str).str.strip()
        series.to_csv(BLS_SERIES_CACHE, index=False)
        data.to_csv(BLS_DATA_CACHE, index=False)

    series.columns = [c.strip() for c in series.columns]
    data.columns = [c.strip() for c in data.columns]
    series["series_id"] = series["series_id"].astype(str).str.strip()
    data["series_id"] = data["series_id"].astype(str).str.strip()
    series["industry_code"] = series["industry_code"].astype(str).str.zfill(6)
    keep_industries = sorted({meta["industry_code"] for meta in FIRM_UNIVERSE.values()})
    keep_series = series[
        (series["seasonal"].astype(str).str.strip() == "S")
        & (series["ratelevel_code"].astype(str).str.strip() == "R")
        & (series["dataelement_code"].astype(str).str.strip().isin(["JO", "QU"]))
        & (series["industry_code"].isin(keep_industries))
    ][["series_id", "industry_code", "dataelement_code"]]
    merged = data.merge(keep_series, on="series_id", how="inner")
    merged = merged[merged["period"].astype(str).str.startswith("M")].copy()
    merged["month"] = pd.to_datetime(
        merged["year"].astype(str) + "-" + merged["period"].str[1:3] + "-01",
        errors="coerce",
    )
    merged["value"] = pd.to_numeric(merged["value"], errors="coerce")
    pivot = merged.pivot_table(
        index=["industry_code", "month"],
        columns="dataelement_code",
        values="value",
        aggfunc="last",
    ).reset_index()
    pivot = pivot.rename(columns={"JO": "job_openings_rate", "QU": "quits_rate"})
    pivot["openings_minus_quits"] = pivot["job_openings_rate"] - pivot["quits_rate"]
    pivot = pivot.sort_values(["industry_code", "month"])
    pivot["rolling_mean"] = pivot.groupby("industry_code")["openings_minus_quits"].transform(
        lambda s: s.rolling(60, min_periods=24).mean().shift(1)
    )
    pivot["rolling_std"] = pivot.groupby("industry_code")["openings_minus_quits"].transform(
        lambda s: s.rolling(60, min_periods=24).std(ddof=0).shift(1)
    )
    pivot["jolts_tightness_z"] = (
        pivot["openings_minus_quits"] - pivot["rolling_mean"]
    ) / pivot["rolling_std"].replace(0, np.nan)
    pivot["release_date"] = pivot["month"] + pd.offsets.MonthEnd(0) + pd.Timedelta(days=35)
    pivot = pivot[pivot["month"] >= "2020-01-01"].copy()
    pivot.to_csv(JOLTS_PANEL_CACHE, index=False)
    return pivot


def fetch_prices(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if PRICE_CACHE.exists() and not refresh:
        return pd.read_csv(PRICE_CACHE, parse_dates=["Date"]).set_index("Date").sort_index()
    raw = yf.download(
        PRICE_TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        group_by="ticker",
        threads=False,
        progress=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned no data")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw.xs("Close", axis=1, level=-1)
    else:
        close = raw[["Close"]].copy()
        close.columns = [PRICE_TICKERS[0]]
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.loc[:, [t for t in PRICE_TICKERS if t in close.columns]].dropna(how="all")
    close.to_csv(PRICE_CACHE, index_label="Date")
    return close


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    return series.shift(-1).rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def build_daily_panel(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if REGRESSION_PANEL_CACHE.exists() and not refresh:
        return pd.read_csv(REGRESSION_PANEL_CACHE, parse_dates=["date"])

    filing_scores = fetch_filing_scores(refresh=refresh)
    jolts = fetch_jolts(refresh=refresh)
    close = fetch_prices(refresh=refresh)
    returns = np.log(close).diff()
    trading_dates = pd.DataFrame({"date": pd.to_datetime(returns.index).normalize()})

    rows: list[pd.DataFrame] = []
    for ticker, meta in FIRM_UNIVERSE.items():
        if ticker not in returns.columns or meta["control"] not in returns.columns:
            continue
        firm = trading_dates.copy()
        firm["ticker"] = ticker
        firm["industry_code"] = meta["industry_code"]
        firm["industry"] = meta["industry"]
        firm["control"] = meta["control"]
        firm["firm_ret"] = returns[ticker].to_numpy()
        firm["control_ret"] = returns[meta["control"]].to_numpy()
        firm["aiq_ret"] = returns["AIQ"].to_numpy() if "AIQ" in returns.columns else np.nan
        firm["idio_ret"] = firm["firm_ret"] - firm["control_ret"]
        firm["aiq_relative_ret"] = firm["firm_ret"] - firm["aiq_ret"]

        score_cols = [
            "filing_date",
            "labor_shortage_score_log",
            "labor_shortage_score_per_10k",
            "core_labor_shortage_hits",
            "wage_pressure_hits",
            "automation_score_log",
            "form",
        ]
        scores = filing_scores[filing_scores["ticker"] == ticker][score_cols].dropna(
            subset=["filing_date", "labor_shortage_score_log"]
        )
        scores["score_release_date"] = pd.to_datetime(scores["filing_date"]).dt.normalize()
        scores = scores.sort_values("filing_date")
        firm = pd.merge_asof(
            firm.sort_values("date"),
            scores.drop(columns=["filing_date"]),
            left_on="date",
            right_on="score_release_date",
            direction="backward",
        )

        j = jolts[jolts["industry_code"].astype(str).str.zfill(6) == meta["industry_code"]][
            [
                "release_date",
                "job_openings_rate",
                "quits_rate",
                "openings_minus_quits",
                "jolts_tightness_z",
            ]
        ].dropna(subset=["release_date"])
        j["release_date"] = pd.to_datetime(j["release_date"]).dt.normalize()
        j = j.sort_values("release_date")
        firm = pd.merge_asof(
            firm.sort_values("date"),
            j,
            left_on="date",
            right_on="release_date",
            direction="backward",
        )
        firm["labor_shortage_score_log"] = firm["labor_shortage_score_log"].fillna(0.0)
        firm["labor_shortage_score_per_10k"] = firm["labor_shortage_score_per_10k"].fillna(0.0)
        firm["core_labor_shortage_hits"] = firm["core_labor_shortage_hits"].fillna(0.0)
        firm["wage_pressure_hits"] = firm["wage_pressure_hits"].fillna(0.0)
        firm["automation_score_log"] = firm["automation_score_log"].fillna(0.0)
        firm["jolts_tightness_z"] = firm["jolts_tightness_z"].fillna(0.0)
        firm["combined_signal_raw"] = firm["labor_shortage_score_log"] * firm["jolts_tightness_z"]
        for col in [
            "labor_shortage_score_log",
            "automation_score_log",
            "jolts_tightness_z",
            "combined_signal_raw",
        ]:
            firm[f"{col}_lag1"] = firm[col].shift(1)

        for horizon in HORIZONS:
            rv = firm["idio_ret"].pow(2)
            downside = firm["idio_ret"].where(firm["idio_ret"] < 0.0, 0.0).pow(2)
            aiq_rv = firm["aiq_relative_ret"].pow(2)
            baseline_rv = rv.rolling(63, min_periods=42).sum().shift(1) * horizon / 63.0
            baseline_down = downside.rolling(63, min_periods=42).sum().shift(1) * horizon / 63.0
            baseline_aiq = aiq_rv.rolling(63, min_periods=42).sum().shift(1) * horizon / 63.0
            firm[f"target_rv_{horizon}d"] = np.log((forward_sum(rv, horizon) + EPS) / (baseline_rv + EPS))
            firm[f"target_downside_{horizon}d"] = np.log(
                (forward_sum(downside, horizon) + EPS) / (baseline_down + EPS)
            )
            firm[f"target_aiq_relative_rv_{horizon}d"] = np.log(
                (forward_sum(aiq_rv, horizon) + EPS) / (baseline_aiq + EPS)
            )
        rows.append(firm)
    panel = pd.concat(rows, ignore_index=True)
    panel = panel[(panel["date"] >= "2021-06-01") & panel["score_release_date"].notna()].copy()
    panel.to_csv(REGRESSION_PANEL_CACHE, index=False)
    return panel


def standardize(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return series * np.nan
    return (series - series.mean()) / std


def run_regression(panel: pd.DataFrame, signal_col: str, target_col: str, horizon: int) -> RegressionResult:
    cols = list(dict.fromkeys([
        "ticker",
        "industry",
        signal_col,
        target_col,
        "labor_shortage_score_log_lag1",
        "jolts_tightness_z_lag1",
        "automation_score_log_lag1",
    ]))
    df = panel[cols].dropna().copy()
    df = df[np.isfinite(df[target_col]) & np.isfinite(df[signal_col])].copy()
    df["signal_z"] = standardize(df[signal_col])
    df["sec_z"] = standardize(df["labor_shortage_score_log_lag1"])
    df["jolts_z"] = standardize(df["jolts_tightness_z_lag1"])
    df["automation_z"] = standardize(df["automation_score_log_lag1"])
    control_cols = ["automation_z"]
    if signal_col != "labor_shortage_score_log_lag1":
        control_cols.append("sec_z")
    if signal_col != "jolts_tightness_z_lag1":
        control_cols.append("jolts_z")
    df = df.dropna(subset=["signal_z", *control_cols, target_col])
    industry_dummies = pd.get_dummies(df["industry"], prefix="ind", drop_first=True, dtype=float)
    x = pd.concat(
        [
            df[["signal_z", *control_cols]].astype(float),
            industry_dummies,
        ],
        axis=1,
    )
    x = sm.add_constant(x, has_constant="add")
    y = df[target_col].astype(float)
    model = sm.OLS(y, x).fit(cov_type="cluster", cov_kwds={"groups": df["ticker"]})
    beta = float(model.params["signal_z"])
    t_stat = float(model.tvalues["signal_z"])
    p_value = float(model.pvalues["signal_z"])

    signal_rank = df["signal_z"].rank(method="first", pct=True)
    high = df[signal_rank >= 0.8][target_col].dropna()
    low = df[signal_rank <= 0.5][target_col].dropna()
    if len(high) > 2 and len(low) > 2:
        welch = stats.ttest_ind(high, low, equal_var=False, nan_policy="omit")
        high_low_diff = float(high.mean() - low.mean())
        high_low_t = float(welch.statistic)
        high_low_p = float(welch.pvalue)
    else:
        high_low_diff = high_low_t = high_low_p = np.nan
    gate_pass = bool(beta > 0 and t_stat >= 3.0 and high_low_diff > 0 and high_low_t >= 3.0)
    return RegressionResult(
        signal=signal_col,
        target=target_col,
        horizon=horizon,
        n_obs=int(len(df)),
        n_firms=int(df["ticker"].nunique()),
        beta=beta,
        t_stat=t_stat,
        p_value=p_value,
        high_low_diff=high_low_diff,
        high_low_t=high_low_t,
        high_low_p=high_low_p,
        high_count=int(len(high)),
        low_count=int(len(low)),
        gate_pass=gate_pass,
    )


def make_figure(panel: pd.DataFrame, filing_scores: pd.DataFrame, jolts: pd.DataFrame, results: list[RegressionResult]) -> None:
    ensure_dirs()
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), dpi=150)
    fig.patch.set_facecolor("white")

    industry_mentions = (
        filing_scores.groupby("ticker")[
            ["core_labor_shortage_hits", "wage_pressure_hits", "automation_hits"]
        ]
        .sum()
        .sort_values("core_labor_shortage_hits", ascending=False)
        .head(12)
    )
    industry_mentions[["core_labor_shortage_hits", "wage_pressure_hits"]].plot(
        kind="bar", stacked=True, ax=axes[0, 0], color=["#1f4e79", "#9dc3e6"]
    )
    axes[0, 0].set_title("SEC 10-K/10-Q phrase-count exposure")
    axes[0, 0].set_ylabel("Hits in scored filings")
    axes[0, 0].tick_params(axis="x", rotation=45)

    for industry_code, sub in jolts.groupby("industry_code"):
        label = next((m["industry"] for m in FIRM_UNIVERSE.values() if m["industry_code"] == industry_code), industry_code)
        axes[0, 1].plot(sub["month"], sub["jolts_tightness_z"], label=label, linewidth=1.2)
    axes[0, 1].axhline(0, color="#666666", linewidth=0.8)
    axes[0, 1].set_title("BLS JOLTS openings-minus-quits z-score")
    axes[0, 1].set_ylabel("Rolling 60m z-score")
    axes[0, 1].legend(fontsize=7, ncol=2)

    combined = [r for r in results if r.signal == "combined_signal_raw_lag1"]
    labels = [f"{r.target.replace('target_', '')}\n{r.horizon}d" for r in combined]
    tstats = [r.t_stat for r in combined]
    colors = ["#2f6f4e" if r.gate_pass else "#8c8c8c" for r in combined]
    axes[1, 0].bar(range(len(tstats)), tstats, color=colors)
    axes[1, 0].axhline(3.0, color="#b22222", linestyle="--", linewidth=1.0)
    axes[1, 0].set_xticks(range(len(labels)))
    axes[1, 0].set_xticklabels(labels, rotation=45, ha="right")
    axes[1, 0].set_title("Combined SEC x JOLTS signal coefficient t-stat")
    axes[1, 0].set_ylabel("Clustered t-stat")

    signal = panel["combined_signal_raw_lag1"].replace([np.inf, -np.inf], np.nan)
    target = panel["target_rv_5d"].replace([np.inf, -np.inf], np.nan)
    tmp = pd.DataFrame({"signal": signal, "target": target}).dropna()
    tmp["bucket"] = pd.qcut(tmp["signal"].rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    bucket = tmp.groupby("bucket", observed=True)["target"].mean()
    axes[1, 1].bar(bucket.index.astype(str), bucket.values, color="#5b8db8")
    axes[1, 1].set_title("5d idio RV target by combined-signal quintile")
    axes[1, 1].set_ylabel("Mean log RV vs 63d baseline")

    for ax in axes.ravel():
        ax.grid(axis="y", alpha=0.2)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.tight_layout()
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PATH, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run(refresh: bool = False) -> dict[str, Any]:
    ensure_dirs()
    np.random.seed(SEED)
    filing_scores = fetch_filing_scores(refresh=refresh)
    jolts = fetch_jolts(refresh=refresh)
    panel = build_daily_panel(refresh=refresh)

    regression_results: list[RegressionResult] = []
    signal_specs = [
        "combined_signal_raw_lag1",
        "labor_shortage_score_log_lag1",
        "jolts_tightness_z_lag1",
    ]
    for signal in signal_specs:
        for horizon in HORIZONS:
            for target_base in ["rv", "downside", "aiq_relative_rv"]:
                regression_results.append(
                    run_regression(panel, signal, f"target_{target_base}_{horizon}d", horizon)
                )

    combined_results = [r for r in regression_results if r.signal == "combined_signal_raw_lag1"]
    verdict = {
        "verdict": "PASS_PUBLIC_PROXY" if any(r.gate_pass for r in combined_results) else "NULL_PUBLIC_PROXY_DIAGNOSTIC",
        "combined_gate_pass_count": int(sum(r.gate_pass for r in combined_results)),
        "combined_cells": int(len(combined_results)),
        "directional_combined_count": int(sum(r.beta > 0 for r in combined_results)),
        "all_cells": int(len(regression_results)),
        "gate": "PASS requires combined SEC labor-shortage text x lagged BLS JOLTS tightness coefficient >0 with clustered t>=3 and high-minus-low Welch t>=3.",
    }
    strongest_combined = max(combined_results, key=lambda r: r.t_stat)
    strongest_any = max(regression_results, key=lambda r: r.t_stat)
    make_figure(panel, filing_scores, jolts, regression_results)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "sample_start": START_DATE,
            "sample_end": END_DATE,
            "firm_count": int(len(FIRM_UNIVERSE)),
            "firms": sorted(FIRM_UNIVERSE),
            "control_tickers": CONTROL_TICKERS,
            "sec_scored_filings": int(len(filing_scores)),
            "sec_successful_filings": int(filing_scores["download_error"].fillna("").eq("").sum()),
            "sec_failed_filings": int(filing_scores["download_error"].fillna("").ne("").sum()),
            "sec_forms": filing_scores["form"].value_counts().to_dict(),
            "sec_filing_date_min": filing_scores["filing_date"].min().strftime("%Y-%m-%d"),
            "sec_filing_date_max": filing_scores["filing_date"].max().strftime("%Y-%m-%d"),
            "total_core_labor_shortage_hits": int(filing_scores["core_labor_shortage_hits"].fillna(0).sum()),
            "total_wage_pressure_hits": int(filing_scores["wage_pressure_hits"].fillna(0).sum()),
            "total_automation_hits": int(filing_scores["automation_hits"].fillna(0).sum()),
            "jolts_months": int(jolts["month"].nunique()),
            "jolts_industries": int(jolts["industry_code"].nunique()),
            "regression_panel_rows": int(len(panel)),
            "regression_panel_start": panel["date"].min().strftime("%Y-%m-%d"),
            "regression_panel_end": panel["date"].max().strftime("%Y-%m-%d"),
        },
        "lookahead_controls": {
            "sec": "SEC text score is merged by filing_date and shifted one trading day by ticker.",
            "jolts": "BLS JOLTS values are assumed observable 35 calendar days after month end and shifted one trading day.",
            "targets": "Forward RV/downside targets start at t+1; lagged 63d baselines are shifted before target start.",
        },
        "regression_results": [asdict(item) for item in regression_results],
        "strongest_combined_result": asdict(strongest_combined),
        "strongest_any_result": asdict(strongest_any),
        "literature_and_data_context": LITERATURE_AND_DATA_CONTEXT,
        "outputs": {
            "results_json": str(RESULTS_PATH.relative_to(HERE)),
            "figure": str(FIG_PATH.relative_to(HERE)),
            "filing_index": str(FILING_INDEX_CACHE.relative_to(HERE)),
            "filing_scores": str(FILING_SCORE_CACHE.relative_to(HERE)),
            "jolts_panel": str(JOLTS_PANEL_CACHE.relative_to(HERE)),
            "price_cache": str(PRICE_CACHE.relative_to(HERE)),
            "regression_panel": str(REGRESSION_PANEL_CACHE.relative_to(HERE)),
        },
        "limitations": [
            "This is a public SEC phrase-count proxy, not the earnings-call FinBERT measure from the RFS paper.",
            "The firm universe is a hand-built labor-sensitive listed-firm basket, not CRSP/Compustat coverage.",
            "JOLTS industry data are broad monthly aggregates and not firm-specific local labor markets.",
            "SEC 10-K/10-Q risk-factor language is sticky and legalistic; phrase counts can measure disclosure style as well as true exposure.",
            "Idiosyncratic RV from daily closes misses intraday labor/news timing and uses ETF controls rather than a full factor model.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(_json_safe(results), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"experiment_id": EXPERIMENT_ID, "verdict": verdict}, indent=2, ensure_ascii=False))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload SEC, BLS, and yfinance data")
    args = parser.parse_args()
    run(refresh=args.refresh)


if __name__ == "__main__":
    main()
