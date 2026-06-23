#!/usr/bin/env python3
"""BHC AI/operational-loss disclosure as a bank RV predictor.

Uses public SEC 10-K filings to build a disclosure proxy and tests whether the
lagged proxy predicts next-month realized volatility for large U.S. bank stocks
and bank ETFs.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.formula.api as smf
import yfinance as yf


EXP_ID = "research_bhc_ai_loss_disclosure_rv"
SEED = 20260624
TRADING_DAYS = 252
START_DATE = "2019-01-01"
PANEL_START = pd.Timestamp("2020-01-31")
EXPECTED_REPORT_YEARS = set(range(2019, 2026))
SEC_HEADERS = {
    "User-Agent": "VolPredResearch codex-vscode contact: research@example.com",
    "Accept-Encoding": "gzip, deflate",
}

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXP_ID}_results.json"


@dataclass(frozen=True)
class Bank:
    ticker: str
    name: str
    cik: str


BANKS = [
    Bank("JPM", "JPMorgan Chase", "0000019617"),
    Bank("BAC", "Bank of America", "0000070858"),
    Bank("WFC", "Wells Fargo", "0000072971"),
    Bank("C", "Citigroup", "0000831001"),
    Bank("GS", "Goldman Sachs", "0000886982"),
    Bank("MS", "Morgan Stanley", "0000895421"),
    Bank("USB", "U.S. Bancorp", "0000036104"),
    Bank("PNC", "PNC Financial", "0000713676"),
    Bank("TFC", "Truist Financial", "0000092230"),
    Bank("COF", "Capital One", "0000927628"),
]

BANK_TICKERS = [bank.ticker for bank in BANKS]
ETF_TICKERS = ["KBE", "KRE", "XLF", "SPY"]
PRICE_TICKERS = BANK_TICKERS + ETF_TICKERS

TERM_GROUPS = {
    "ai_terms": [
        r"\bartificial intelligence\b",
        r"\bgenerative ai\b",
        r"\bmachine learning\b",
        r"\blarge language model[s]?\b",
        r"\balgorithmic\b",
        r"\bautomated decision(?:ing|s)?\b",
    ],
    "model_risk_terms": [
        r"\bmodel risk\b",
        r"\bmodel governance\b",
        r"\bmodel validation\b",
        r"\bmodel control[s]?\b",
        r"\bmodel risk management\b",
    ],
    "operational_loss_terms": [
        r"\boperational loss(?:es)?\b",
        r"\boperational risk\b",
        r"\btechnology risk\b",
        r"\bthird[- ]party risk\b",
        r"\bcybersecurity risk\b",
        r"\bvendor risk\b",
    ],
}


def _request_json(url: str) -> dict:
    response = requests.get(url, headers=SEC_HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def _request_text(url: str) -> str:
    response = requests.get(url, headers=SEC_HEADERS, timeout=60)
    response.raise_for_status()
    return response.text


def _clean_text(raw: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def _count_terms(text: str) -> dict[str, int | float]:
    words = re.findall(r"[a-zA-Z]+", text)
    word_count = len(words)
    counts: dict[str, int | float] = {"word_count": word_count}
    for group, patterns in TERM_GROUPS.items():
        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, text, flags=re.I))
        counts[group] = int(count)
        counts[f"{group}_per_10k"] = float(count / max(word_count, 1) * 10_000.0)
    counts["combined_ai_model_operational_per_10k"] = float(
        counts["ai_terms_per_10k"]
        + counts["model_risk_terms_per_10k"]
        + counts["operational_loss_terms_per_10k"]
    )
    return counts


def _sec_filing_url(cik: str, accession: str, primary_document: str) -> str:
    cik_int = str(int(cik))
    acc_no_dash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_dash}/{primary_document}"


def _filing_history_frame(submission_data: dict) -> pd.DataFrame:
    recent = pd.DataFrame(submission_data["filings"]["recent"])
    frames = [recent]
    for file_meta in submission_data["filings"].get("files", []):
        filing_from = file_meta.get("filingFrom", "")
        filing_to = file_meta.get("filingTo", "")
        if filing_to < "2019-01-01" or filing_from > "2026-12-31":
            continue
        shard_url = f"https://data.sec.gov/submissions/{file_meta['name']}"
        shard = pd.DataFrame(_request_json(shard_url))
        frames.append(shard)
        time.sleep(0.12)
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(subset=["accessionNumber", "form"], keep="first")


def _cache_has_expected_years(cached: pd.DataFrame) -> bool:
    for ticker in BANK_TICKERS:
        years = set(cached.loc[cached["ticker"] == ticker, "report_year"].dropna().astype(int))
        if not EXPECTED_REPORT_YEARS.issubset(years):
            return False
    return True


def _collect_filing_counts() -> pd.DataFrame:
    cache_path = DATA_DIR / "filing_counts.csv"
    if cache_path.exists():
        cached = pd.read_csv(cache_path, parse_dates=["filing_date", "report_date"])
        if _cache_has_expected_years(cached):
            print(f"Using cached SEC filing counts from {cache_path}")
            return cached
        print(f"Refreshing incomplete SEC filing-count cache at {cache_path}")

    rows = []
    for bank in BANKS:
        url = f"https://data.sec.gov/submissions/CIK{bank.cik}.json"
        print(f"Fetching SEC submissions for {bank.ticker}")
        data = _request_json(url)
        history = _filing_history_frame(data)
        filings = history.loc[history["form"].eq("10-K")].copy()
        filings["report_date"] = pd.to_datetime(filings["reportDate"], errors="coerce")
        filings["filing_date"] = pd.to_datetime(filings["filingDate"], errors="coerce")
        filings = filings.loc[filings["report_date"].dt.year.between(2019, 2025)]
        for _, filing in filings.iterrows():
            filing_url = _sec_filing_url(bank.cik, filing["accessionNumber"], filing["primaryDocument"])
            print(f"  {bank.ticker} {filing['reportDate']} {filing['primaryDocument']}")
            raw = _request_text(filing_url)
            text = _clean_text(raw)
            counts = _count_terms(text)
            row = {
                "ticker": bank.ticker,
                "bank_name": bank.name,
                "cik": bank.cik,
                "form": filing["form"],
                "accession": filing["accessionNumber"],
                "filing_date": filing["filing_date"],
                "report_date": filing["report_date"],
                "report_year": int(filing["report_date"].year),
                "primary_document": filing["primaryDocument"],
                "filing_url": filing_url,
            }
            row.update(counts)
            rows.append(row)
            time.sleep(0.12)
    out = pd.DataFrame(rows).sort_values(["ticker", "report_date"])
    out.to_csv(cache_path, index=False)
    return out


def _download_prices() -> pd.DataFrame:
    cache_path = DATA_DIR / "prices.csv"
    if cache_path.exists():
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if all(ticker in cached.columns for ticker in PRICE_TICKERS):
            print(f"Using cached prices from {cache_path}")
            return cached[PRICE_TICKERS].sort_index()

    print(f"Downloading {len(PRICE_TICKERS)} price series via yfinance ...")
    raw = yf.download(
        PRICE_TICKERS,
        start=START_DATE,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].rename(columns={"Close": PRICE_TICKERS[0]})
    missing = sorted(set(PRICE_TICKERS) - set(prices.columns))
    if missing:
        raise RuntimeError(f"Missing price columns: {missing}")
    prices = prices[PRICE_TICKERS].dropna(how="all").sort_index()
    prices.to_csv(cache_path)
    return prices


def _monthly_realized_vol(returns: pd.DataFrame) -> pd.DataFrame:
    rv = returns.pow(2).groupby(pd.Grouper(freq="ME")).mean().pow(0.5) * math.sqrt(TRADING_DAYS)
    last_observed_month = returns.index.max().to_period("M").to_timestamp("M")
    rv = rv.loc[rv.index < last_observed_month]
    return rv.dropna(how="all")


def _monthly_return(returns: pd.DataFrame) -> pd.DataFrame:
    monthly = (1.0 + returns).groupby(pd.Grouper(freq="ME")).prod() - 1.0
    last_observed_month = returns.index.max().to_period("M").to_timestamp("M")
    return monthly.loc[monthly.index < last_observed_month]


def _active_disclosure_panel(filings: pd.DataFrame, month_ends: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    signal_cols = [
        "ai_terms_per_10k",
        "model_risk_terms_per_10k",
        "operational_loss_terms_per_10k",
        "combined_ai_model_operational_per_10k",
    ]
    for ticker in BANK_TICKERS:
        f = filings.loc[filings["ticker"] == ticker].sort_values("filing_date")
        base = pd.DataFrame({"month_end": pd.to_datetime(month_ends)})
        if f.empty:
            continue
        f = f.copy()
        f["filing_date"] = pd.to_datetime(f["filing_date"])
        merged = pd.merge_asof(
            base.sort_values("month_end"),
            f[["filing_date", "report_year"] + signal_cols].sort_values("filing_date"),
            left_on="month_end",
            right_on="filing_date",
            direction="backward",
        )
        merged["ticker"] = ticker
        rows.append(merged)
    active = pd.concat(rows, ignore_index=True)
    for col in signal_cols:
        # Explicit one-month lag.  Month m target is m+1 RV; this uses the
        # disclosure state observed no later than m-1.
        active[f"{col}_lag1"] = active.groupby("ticker")[col].shift(1)
    return active


def _standardize(series: pd.Series) -> pd.Series:
    std = series.std(ddof=1)
    if not np.isfinite(std) or std <= 0:
        return series * np.nan
    return (series - series.mean()) / std


def _build_bank_panel(
    filings: pd.DataFrame,
    monthly_rv: pd.DataFrame,
    monthly_ret: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    month_ends = monthly_rv.index
    active = _active_disclosure_panel(filings, month_ends)
    active.to_csv(DATA_DIR / "active_disclosure_by_month.csv", index=False)
    rows = []
    for ticker in BANK_TICKERS:
        df = pd.DataFrame(
            {
                "month_end": month_ends,
                "ticker": ticker,
                "rv_current": monthly_rv[ticker].reindex(month_ends).to_numpy(),
                "target_rv_next": monthly_rv[ticker].shift(-1).reindex(month_ends).to_numpy(),
                "ret_current": monthly_ret[ticker].reindex(month_ends).to_numpy(),
                "kbe_rv_current": monthly_rv["KBE"].reindex(month_ends).to_numpy(),
                "kbe_target_rv_next": monthly_rv["KBE"].shift(-1).reindex(month_ends).to_numpy(),
                "xlf_rv_current": monthly_rv["XLF"].reindex(month_ends).to_numpy(),
                "spy_rv_current": monthly_rv["SPY"].reindex(month_ends).to_numpy(),
            }
        )
        rows.append(df)
    panel = pd.concat(rows, ignore_index=True)
    panel = panel.merge(
        active[
            [
                "month_end",
                "ticker",
                "filing_date",
                "report_year",
                "ai_terms_per_10k_lag1",
                "model_risk_terms_per_10k_lag1",
                "operational_loss_terms_per_10k_lag1",
                "combined_ai_model_operational_per_10k_lag1",
            ]
        ],
        on=["month_end", "ticker"],
        how="left",
    )
    panel = panel.loc[panel["month_end"] >= PANEL_START].copy()
    signal_cols = [
        "ai_terms_per_10k_lag1",
        "model_risk_terms_per_10k_lag1",
        "operational_loss_terms_per_10k_lag1",
        "combined_ai_model_operational_per_10k_lag1",
    ]
    for col in signal_cols:
        panel[f"{col}_z"] = _standardize(panel[col])
    panel["abs_ret_current"] = panel["ret_current"].abs()
    panel["year"] = panel["month_end"].dt.year.astype(str)
    panel["month_key"] = panel["month_end"].dt.strftime("%Y-%m")
    panel = panel.dropna(
        subset=[
            "target_rv_next",
            "rv_current",
            "kbe_rv_current",
            "combined_ai_model_operational_per_10k_lag1_z",
        ]
    )
    return panel, active


def _fit_bank_panel(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    tests = {
        "ai_only": "ai_terms_per_10k_lag1_z",
        "model_risk_only": "model_risk_terms_per_10k_lag1_z",
        "operational_only": "operational_loss_terms_per_10k_lag1_z",
        "combined": "combined_ai_model_operational_per_10k_lag1_z",
    }
    rows = []
    meta = {}
    for name, signal in tests.items():
        formula = (
            f"target_rv_next ~ {signal} + rv_current + abs_ret_current + "
            "kbe_rv_current + xlf_rv_current + spy_rv_current + C(ticker) + C(year)"
        )
        model = smf.ols(formula, data=panel).fit(
            cov_type="cluster",
            cov_kwds={"groups": panel["month_key"]},
        )
        meta[name] = {"n_obs": int(model.nobs), "r_squared": float(model.rsquared)}
        conf = model.conf_int()
        for term, coef in model.params.items():
            rows.append(
                {
                    "model": name,
                    "term": term,
                    "coef": float(coef),
                    "std_err": float(model.bse[term]),
                    "t": float(model.tvalues[term]),
                    "p": float(model.pvalues[term]),
                    "ci_low": float(conf.loc[term, 0]),
                    "ci_high": float(conf.loc[term, 1]),
                    "harvey_pass": bool(abs(float(model.tvalues[term])) > 3.0),
                    "primary_signal": term == signal,
                }
            )
    return pd.DataFrame(rows), meta


def _fit_etf_aggregate(panel: pd.DataFrame, monthly_rv: pd.DataFrame) -> pd.DataFrame:
    agg = (
        panel.groupby("month_end", as_index=False)[
            [
                "ai_terms_per_10k_lag1",
                "model_risk_terms_per_10k_lag1",
                "operational_loss_terms_per_10k_lag1",
                "combined_ai_model_operational_per_10k_lag1",
            ]
        ]
        .mean()
        .sort_values("month_end")
    )
    for col in [c for c in agg.columns if c.endswith("_lag1")]:
        agg[f"{col}_z"] = _standardize(agg[col])
    rows = []
    for etf in ["KBE", "KRE", "XLF"]:
        df = agg.copy()
        df["rv_current"] = monthly_rv[etf].reindex(pd.to_datetime(df["month_end"])).to_numpy()
        df["target_rv_next"] = monthly_rv[etf].shift(-1).reindex(pd.to_datetime(df["month_end"])).to_numpy()
        df = df.dropna(subset=["target_rv_next", "rv_current", "combined_ai_model_operational_per_10k_lag1_z"])
        for model_name, signal in {
            "aggregate_ai": "ai_terms_per_10k_lag1_z",
            "aggregate_model_risk": "model_risk_terms_per_10k_lag1_z",
            "aggregate_operational": "operational_loss_terms_per_10k_lag1_z",
            "aggregate_combined": "combined_ai_model_operational_per_10k_lag1_z",
        }.items():
            model = smf.ols(f"target_rv_next ~ {signal} + rv_current", data=df).fit(
                cov_type="HAC",
                cov_kwds={"maxlags": 3},
            )
            conf = model.conf_int()
            term = signal
            rows.append(
                {
                    "target": etf,
                    "model": model_name,
                    "term": term,
                    "n_obs": int(model.nobs),
                    "coef": float(model.params[term]),
                    "std_err": float(model.bse[term]),
                    "t": float(model.tvalues[term]),
                    "p": float(model.pvalues[term]),
                    "ci_low": float(conf.loc[term, 0]),
                    "ci_high": float(conf.loc[term, 1]),
                    "harvey_pass": bool(abs(float(model.tvalues[term])) > 3.0),
                    "r_squared": float(model.rsquared),
                }
            )
    return pd.DataFrame(rows)


def _filing_event_windows(filings: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, filing in filings.iterrows():
        ticker = filing["ticker"]
        date = pd.Timestamp(filing["filing_date"])
        if ticker not in returns.columns:
            continue
        ret = returns[ticker].dropna()
        pre = ret.loc[(ret.index >= date - pd.Timedelta(days=35)) & (ret.index < date)].tail(20)
        post = ret.loc[(ret.index > date) & (ret.index <= date + pd.Timedelta(days=35))].head(20)
        if pre.shape[0] < 10 or post.shape[0] < 10:
            continue
        rows.append(
            {
                "ticker": ticker,
                "filing_date": date.strftime("%Y-%m-%d"),
                "report_year": int(filing["report_year"]),
                "pre_n": int(pre.shape[0]),
                "post_n": int(post.shape[0]),
                "pre_ann_vol": float(pre.std(ddof=1) * math.sqrt(TRADING_DAYS)),
                "post_ann_vol": float(post.std(ddof=1) * math.sqrt(TRADING_DAYS)),
                "post_pre_vol_ratio": float(post.std(ddof=1) / pre.std(ddof=1)),
                "combined_score": float(filing["combined_ai_model_operational_per_10k"]),
            }
        )
    return pd.DataFrame(rows)


def _plot_primary_coefficients(bank_results: pd.DataFrame, etf_results: pd.DataFrame) -> None:
    primary = bank_results.loc[bank_results["primary_signal"]].copy()
    primary["label"] = "bank_panel:" + primary["model"]
    etf_primary = etf_results.loc[etf_results["model"].eq("aggregate_combined")].copy()
    etf_primary["label"] = "ETF_" + etf_primary["target"]
    plot_df = pd.concat(
        [
            primary[["label", "coef", "ci_low", "ci_high"]],
            etf_primary[["label", "coef", "ci_low", "ci_high"]],
        ],
        ignore_index=True,
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    y = np.arange(plot_df.shape[0])
    ax.errorbar(
        plot_df["coef"],
        y,
        xerr=[plot_df["coef"] - plot_df["ci_low"], plot_df["ci_high"] - plot_df["coef"]],
        fmt="o",
        capsize=4,
    )
    ax.axvline(0, color="black", linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(plot_df["label"])
    ax.set_title("Lagged disclosure coefficient on next-month realized volatility")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "primary_coefficients.png", dpi=180)
    plt.close(fig)


def _plot_disclosure_trends(filings: pd.DataFrame) -> None:
    yearly = filings.groupby("report_year")[
        [
            "ai_terms_per_10k",
            "model_risk_terms_per_10k",
            "operational_loss_terms_per_10k",
            "combined_ai_model_operational_per_10k",
        ]
    ].mean()
    fig, ax = plt.subplots(figsize=(10, 5))
    for col in yearly.columns:
        ax.plot(yearly.index, yearly[col], marker="o", label=col.replace("_per_10k", ""))
    ax.set_title("Mean disclosure term intensity across sampled BHC 10-Ks")
    ax.set_ylabel("mentions per 10k words")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "disclosure_trends.png", dpi=180)
    plt.close(fig)


def _record_to_builtin(obj):
    if isinstance(obj, dict):
        return {k: _record_to_builtin(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_record_to_builtin(v) for v in obj]
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        return obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    FIG_DIR.mkdir(exist_ok=True)
    np.random.seed(SEED)

    filings = _collect_filing_counts()
    prices = _download_prices()
    returns = prices.pct_change(fill_method=None).dropna(how="all")
    returns.to_csv(DATA_DIR / "daily_returns.csv")

    monthly_rv = _monthly_realized_vol(returns)
    monthly_ret = _monthly_return(returns)
    monthly_rv.to_csv(DATA_DIR / "monthly_realized_vol.csv")
    monthly_ret.to_csv(DATA_DIR / "monthly_returns.csv")

    bank_panel, active = _build_bank_panel(filings, monthly_rv, monthly_ret)
    bank_panel.to_csv(DATA_DIR / "bank_monthly_panel.csv", index=False)

    bank_results, bank_meta = _fit_bank_panel(bank_panel)
    bank_results.to_csv(DATA_DIR / "bank_panel_regressions.csv", index=False)
    etf_results = _fit_etf_aggregate(bank_panel, monthly_rv)
    etf_results.to_csv(DATA_DIR / "etf_aggregate_regressions.csv", index=False)

    filing_windows = _filing_event_windows(filings, returns)
    filing_windows.to_csv(DATA_DIR / "filing_event_windows.csv", index=False)

    _plot_primary_coefficients(bank_results, etf_results)
    _plot_disclosure_trends(filings)

    primary_bank = bank_results.loc[bank_results["primary_signal"]].copy()
    primary_etf = etf_results.copy()
    bank_passes = primary_bank.loc[primary_bank["harvey_pass"], ["model", "term", "coef", "t"]]
    etf_passes = primary_etf.loc[primary_etf["harvey_pass"], ["target", "model", "coef", "t"]]
    n_positive_bank = int((primary_bank["coef"] > 0).sum())
    n_positive_etf = int((primary_etf["coef"] > 0).sum())

    if bank_passes.empty and etf_passes.empty:
        verdict = "NULL_DISCLOSURE_PROXY_NO_RV_EDGE"
    elif not bank_passes.empty and etf_passes.empty:
        verdict = "PANEL_ONLY_DISCLOSURE_SIGNAL"
    else:
        verdict = "MIXED_DISCLOSURE_SIGNAL"

    results = {
        "experiment_id": EXP_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "sec_source": "SEC data.sec.gov submissions and Archives primary 10-K documents",
            "price_source": "yfinance adjusted close",
            "banks": [asdict(bank) for bank in BANKS],
            "filings_n": int(filings.shape[0]),
            "filing_report_year_min": int(filings["report_year"].min()),
            "filing_report_year_max": int(filings["report_year"].max()),
            "price_start": prices.index.min().strftime("%Y-%m-%d"),
            "price_end": prices.index.max().strftime("%Y-%m-%d"),
            "monthly_rv_policy": "final observed price month is dropped so next-month RV targets do not use partial-month realized volatility",
            "panel_obs": int(bank_panel.shape[0]),
            "panel_month_min": bank_panel["month_end"].min().strftime("%Y-%m-%d"),
            "panel_month_max": bank_panel["month_end"].max().strftime("%Y-%m-%d"),
            "explicit_lag": "active disclosure state is grouped by ticker and shifted one month with groupby('ticker').shift(1)",
        },
        "literature_and_source_links": [
            "https://doi.org/10.1093/rcfs/cfag003",
            "https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm",
            "https://www.nist.gov/itl/ai-risk-management-framework",
            "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        ],
        "bank_panel_meta": bank_meta,
        "primary_bank_tests": primary_bank.to_dict(orient="records"),
        "primary_etf_tests": primary_etf.to_dict(orient="records"),
        "bank_harvey_passes": bank_passes.to_dict(orient="records"),
        "etf_harvey_passes": etf_passes.to_dict(orient="records"),
        "direction_counts": {
            "bank_positive_coefficients": n_positive_bank,
            "bank_tests": int(primary_bank.shape[0]),
            "etf_positive_coefficients": n_positive_etf,
            "etf_tests": int(primary_etf.shape[0]),
        },
        "filing_event_window_summary": {
            "n_windows": int(filing_windows.shape[0]),
            "median_post_pre_vol_ratio": float(filing_windows["post_pre_vol_ratio"].median()),
            "mean_post_pre_vol_ratio": float(filing_windows["post_pre_vol_ratio"].mean()),
        },
        "files": {
            "filing_counts": "data/filing_counts.csv",
            "prices": "data/prices.csv",
            "daily_returns": "data/daily_returns.csv",
            "monthly_realized_vol": "data/monthly_realized_vol.csv",
            "monthly_returns": "data/monthly_returns.csv",
            "active_disclosure": "data/active_disclosure_by_month.csv",
            "bank_panel": "data/bank_monthly_panel.csv",
            "bank_panel_regressions": "data/bank_panel_regressions.csv",
            "etf_aggregate_regressions": "data/etf_aggregate_regressions.csv",
            "filing_event_windows": "data/filing_event_windows.csv",
            "figure_coefficients": "figures/primary_coefficients.png",
            "figure_trends": "figures/disclosure_trends.png",
        },
    }
    RESULTS_PATH.write_text(json.dumps(_record_to_builtin(results), indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "verdict": verdict,
                "filings_n": int(filings.shape[0]),
                "panel_obs": int(bank_panel.shape[0]),
                "bank_passes": bank_passes.to_dict(orient="records"),
                "etf_passes": etf_passes.to_dict(orient="records"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
