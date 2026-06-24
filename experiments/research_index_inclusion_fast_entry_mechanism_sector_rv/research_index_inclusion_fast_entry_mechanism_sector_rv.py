#!/usr/bin/env python3
"""Index-inclusion event study for stock and sector realized volatility.

This is an event-study diagnostic, not a trading strategy.  All event-window
normalization uses only the pre-event window; post-event metrics are evaluated
after the effective index-inclusion date.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import NormalDist

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


warnings.filterwarnings("ignore", category=FutureWarning)

EXPERIMENT_ID = "research_index_inclusion_fast_entry_mechanism_sector_rv"
REPO_ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).resolve().parent
FIG_DIR = EXP_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = "2023-01-01"
END_DATE = "2026-06-24"
PRE_WINDOW = 30
POST_SHORT = 20
POST_FULL = 60
BOOTSTRAP_REPS = 5000
SEED = 42


@dataclass(frozen=True)
class Event:
    ticker: str
    company: str
    index_name: str
    effective_date: str
    sector_etf: str
    peers: tuple[str, ...]
    source: str
    source_url: str
    notes: str = ""


EVENTS: tuple[Event, ...] = (
    Event(
        "SMCI",
        "Super Micro Computer",
        "S&P 500",
        "2024-03-18",
        "XLK",
        ("NVDA", "AMD", "AVGO", "DELL", "HPE", "ANET", "CSCO", "NTAP"),
        "S&P Dow Jones Indices press release, 2024-03-01",
        "https://press.spglobal.com/2024-03-01-Super-Micro-Computer-and-Deckers-Outdoor-Set-to-Join-S-P-500-Others-to-Join-S-P-100%2C-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "DECK",
        "Deckers Outdoor",
        "S&P 500",
        "2024-03-18",
        "XLY",
        ("NKE", "ONON", "LULU", "CROX", "SKX", "RL", "TPR", "VFC"),
        "S&P Dow Jones Indices press release, 2024-03-01",
        "https://press.spglobal.com/2024-03-01-Super-Micro-Computer-and-Deckers-Outdoor-Set-to-Join-S-P-500-Others-to-Join-S-P-100%2C-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "KKR",
        "KKR & Co.",
        "S&P 500",
        "2024-06-24",
        "XLF",
        ("BX", "APO", "ARES", "CG", "BLK", "BAM", "TROW", "BEN"),
        "S&P Dow Jones Indices press release, 2024-06-07",
        "https://press.spglobal.com/2024-06-07-KKR%2C-CrowdStrike-Holdings-and-GoDaddy-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "CRWD",
        "CrowdStrike Holdings",
        "S&P 500",
        "2024-06-24",
        "XLK",
        ("PANW", "FTNT", "ZS", "OKTA", "DDOG", "NET", "S", "GEN"),
        "S&P Dow Jones Indices press release, 2024-06-07",
        "https://press.spglobal.com/2024-06-07-KKR%2C-CrowdStrike-Holdings-and-GoDaddy-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "GDDY",
        "GoDaddy",
        "S&P 500",
        "2024-06-24",
        "XLK",
        ("VRSN", "AKAM", "NET", "WIX", "SHOP", "CRM", "NOW", "DDOG"),
        "S&P Dow Jones Indices press release, 2024-06-07",
        "https://press.spglobal.com/2024-06-07-KKR%2C-CrowdStrike-Holdings-and-GoDaddy-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "PLTR",
        "Palantir Technologies",
        "S&P 500",
        "2024-09-23",
        "XLK",
        ("SNOW", "DDOG", "MDB", "CRM", "NOW", "ORCL", "MSFT", "AI"),
        "S&P Dow Jones Indices press release, 2024-09-06",
        "https://press.spglobal.com/2024-09-06-Palantir-Technologies%2C-Dell-Technologies%2C-and-Erie-Indemnity-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "DELL",
        "Dell Technologies",
        "S&P 500",
        "2024-09-23",
        "XLK",
        ("HPQ", "HPE", "SMCI", "NTAP", "WDC", "STX", "CSCO", "ANET"),
        "S&P Dow Jones Indices press release, 2024-09-06",
        "https://press.spglobal.com/2024-09-06-Palantir-Technologies%2C-Dell-Technologies%2C-and-Erie-Indemnity-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "ERIE",
        "Erie Indemnity",
        "S&P 500",
        "2024-09-23",
        "XLF",
        ("PGR", "ALL", "TRV", "CB", "AIG", "HIG", "CINF", "WRB"),
        "S&P Dow Jones Indices press release, 2024-09-06",
        "https://press.spglobal.com/2024-09-06-Palantir-Technologies%2C-Dell-Technologies%2C-and-Erie-Indemnity-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "PLTR",
        "Palantir Technologies",
        "Nasdaq-100",
        "2024-12-23",
        "XLK",
        ("SNOW", "DDOG", "MDB", "CRM", "NOW", "ORCL", "MSFT", "AI"),
        "Nasdaq-100 annual reconstitution notice as summarized by Invesco QQQ",
        "https://www.invesco.com/qqq-etf/en/etf-insights/innovation-loves-company.html",
        "Annual reconstitution proxy, not a fast-entry case.",
    ),
    Event(
        "MSTR",
        "MicroStrategy",
        "Nasdaq-100",
        "2024-12-23",
        "XLK",
        ("COIN", "MARA", "RIOT", "CLSK", "HUT", "HOOD", "IBKR", "SCHW"),
        "Nasdaq-100 annual reconstitution notice as summarized by Invesco QQQ",
        "https://www.invesco.com/qqq-etf/en/etf-insights/innovation-loves-company.html",
        "Annual reconstitution proxy; peer set mixes software, crypto-linked, and broker proxies.",
    ),
    Event(
        "AXON",
        "Axon Enterprise",
        "Nasdaq-100",
        "2024-12-23",
        "XLI",
        ("MSA", "TDG", "TXT", "HWM", "LHX", "RTX", "GD", "NOC"),
        "Nasdaq-100 annual reconstitution notice as summarized by Invesco QQQ",
        "https://www.invesco.com/qqq-etf/en/etf-insights/innovation-loves-company.html",
        "Annual reconstitution proxy, not a fast-entry case.",
    ),
    Event(
        "DASH",
        "DoorDash",
        "S&P 500",
        "2025-03-24",
        "XLY",
        ("UBER", "LYFT", "CART", "AMZN", "EBAY", "BKNG", "ABNB", "ETSY"),
        "S&P Dow Jones Indices press release, 2025-03-07",
        "https://press.spglobal.com/2025-03-07-DoorDash%2C-TKO-Group-Holdings%2C-Williams-Sonoma-and-Expand-Energy-Set-to-Join-S-P-500-Others-to-Join-S-P-100%2C-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "TKO",
        "TKO Group Holdings",
        "S&P 500",
        "2025-03-24",
        "XLC",
        ("LYV", "NFLX", "DIS", "FOXA", "WBD", "PARA", "SPOT", "ROKU"),
        "S&P Dow Jones Indices press release, 2025-03-07",
        "https://press.spglobal.com/2025-03-07-DoorDash%2C-TKO-Group-Holdings%2C-Williams-Sonoma-and-Expand-Energy-Set-to-Join-S-P-500-Others-to-Join-S-P-100%2C-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "WSM",
        "Williams-Sonoma",
        "S&P 500",
        "2025-03-24",
        "XLY",
        ("RH", "W", "HD", "LOW", "TGT", "COST", "BBY", "M"),
        "S&P Dow Jones Indices press release, 2025-03-07",
        "https://press.spglobal.com/2025-03-07-DoorDash%2C-TKO-Group-Holdings%2C-Williams-Sonoma-and-Expand-Energy-Set-to-Join-S-P-500-Others-to-Join-S-P-100%2C-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "EXE",
        "Expand Energy",
        "S&P 500",
        "2025-03-24",
        "XLE",
        ("XOM", "CVX", "COP", "EOG", "FANG", "OXY", "DVN", "EQT"),
        "S&P Dow Jones Indices press release, 2025-03-07",
        "https://press.spglobal.com/2025-03-07-DoorDash%2C-TKO-Group-Holdings%2C-Williams-Sonoma-and-Expand-Energy-Set-to-Join-S-P-500-Others-to-Join-S-P-100%2C-S-P-MidCap-400-and-S-P-SmallCap-600",
    ),
    Event(
        "COIN",
        "Coinbase Global",
        "S&P 500",
        "2025-05-19",
        "XLF",
        ("HOOD", "IBKR", "SCHW", "CME", "ICE", "NDAQ", "CBOE", "MKTX"),
        "S&P Dow Jones Indices press release, 2025-05-12",
        "https://press.spglobal.com/2025-05-12-Coinbase-Global-Set-to-Join-S-P-500",
    ),
)


def safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def annualized_rv(series: pd.Series) -> float:
    values = series.dropna().to_numpy(dtype=float)
    if values.size == 0:
        return math.nan
    return float(np.mean(values**2) * 252.0)


def log_ratio(post: float, pre: float) -> float:
    if not math.isfinite(post) or not math.isfinite(pre) or post <= 0 or pre <= 0:
        return math.nan
    return float(math.log(post / pre))


def avg_pairwise_corr(frame: pd.DataFrame) -> float:
    frame = frame.dropna(axis=1, thresh=max(10, int(len(frame) * 0.7))).dropna(how="all")
    if frame.shape[1] < 3:
        return math.nan
    corr = frame.corr()
    mask = np.triu(np.ones(corr.shape, dtype=bool), k=1)
    vals = corr.where(mask).stack().to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return math.nan
    return float(vals.mean())


def xs_variance(frame: pd.DataFrame) -> float:
    frame = frame.dropna(axis=1, thresh=max(10, int(len(frame) * 0.7))).dropna(how="all")
    if frame.shape[1] < 3:
        return math.nan
    daily = frame.var(axis=1, ddof=1).dropna()
    if daily.empty:
        return math.nan
    return float(daily.mean() * 252.0)


def jump_rate(series: pd.Series, threshold: float) -> float:
    values = series.dropna().abs().to_numpy(dtype=float)
    if values.size == 0 or not math.isfinite(threshold) or threshold <= 0:
        return math.nan
    return float(np.mean(values > threshold))


def normal_pvalue_from_t(t_stat: float) -> float:
    if not math.isfinite(t_stat):
        return math.nan
    norm = NormalDist()
    return float(2.0 * (1.0 - norm.cdf(abs(t_stat))))


def summarize_vector(values: pd.Series, seed_offset: int = 0) -> dict[str, float | int | None]:
    arr = values.dropna().to_numpy(dtype=float)
    n = int(arr.size)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "std": None,
            "t_stat": None,
            "p_value_normal": None,
            "bootstrap_ci_low": None,
            "bootstrap_ci_high": None,
            "positive_count": 0,
            "negative_count": 0,
        }
    mean = float(arr.mean())
    median = float(np.median(arr))
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    t_stat = mean / (std / math.sqrt(n)) if n > 1 and std > 0 else math.nan
    rng = np.random.default_rng(SEED + seed_offset)
    if n == 1:
        ci_low = ci_high = mean
    else:
        draws = rng.choice(arr, size=(BOOTSTRAP_REPS, n), replace=True).mean(axis=1)
        ci_low, ci_high = np.quantile(draws, [0.025, 0.975])
    return {
        "n": n,
        "mean": safe_float(mean),
        "median": safe_float(median),
        "std": safe_float(std),
        "t_stat": safe_float(t_stat),
        "p_value_normal": safe_float(normal_pvalue_from_t(t_stat)),
        "bootstrap_ci_low": safe_float(ci_low),
        "bootstrap_ci_high": safe_float(ci_high),
        "positive_count": int(np.sum(arr > 0)),
        "negative_count": int(np.sum(arr < 0)),
    }


def clustered_bootstrap_by_event_date(
    rows: pd.DataFrame, metric: str, seed_offset: int = 0
) -> dict[str, float | int | None]:
    valid = rows[["effective_date", metric]].dropna()
    if valid.empty:
        return {"n_clusters": 0, "bootstrap_ci_low": None, "bootstrap_ci_high": None}
    grouped = valid.groupby("effective_date")[metric].apply(list)
    clusters = grouped.index.to_list()
    values = grouped.to_dict()
    rng = np.random.default_rng(SEED + 1000 + seed_offset)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        sampled_clusters = rng.choice(clusters, size=len(clusters), replace=True)
        sampled_values: list[float] = []
        for cluster in sampled_clusters:
            sampled_values.extend(values[cluster])
        means.append(float(np.mean(sampled_values)))
    ci_low, ci_high = np.quantile(means, [0.025, 0.975])
    return {
        "n_clusters": int(len(clusters)),
        "bootstrap_ci_low": safe_float(ci_low),
        "bootstrap_ci_high": safe_float(ci_high),
    }


def download_prices(tickers: list[str]) -> pd.DataFrame:
    raw = yf.download(
        tickers,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")
    closes: dict[str, pd.Series] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for ticker in tickers:
            if ticker in raw.columns.get_level_values(0):
                sub = raw[ticker]
                if "Close" in sub.columns:
                    closes[ticker] = sub["Close"].rename(ticker)
    else:
        if "Close" in raw.columns and len(tickers) == 1:
            closes[tickers[0]] = raw["Close"].rename(tickers[0])
    close = pd.DataFrame(closes).sort_index()
    close = close.dropna(axis=1, how="all")
    if close.empty:
        raise RuntimeError("No adjusted close data could be extracted")
    return close


def valid_peer_list(returns: pd.DataFrame, peers: tuple[str, ...], pre: pd.Index, post: pd.Index) -> list[str]:
    valid: list[str] = []
    for peer in peers:
        if peer not in returns.columns:
            continue
        pre_n = int(returns.loc[pre, peer].dropna().shape[0])
        post_n = int(returns.loc[post, peer].dropna().shape[0])
        if pre_n >= 20 and post_n >= 40:
            valid.append(peer)
    return valid


def event_slices(index: pd.DatetimeIndex, effective_date: str) -> tuple[int, pd.Timestamp, pd.Index, pd.Index, pd.Index]:
    event_ts = pd.Timestamp(effective_date)
    pos = int(index.searchsorted(event_ts, side="left"))
    if pos >= len(index):
        raise ValueError(f"effective date {effective_date} is after data end")
    if pos < PRE_WINDOW or pos + POST_FULL >= len(index):
        raise ValueError(f"not enough window around {effective_date}")
    actual_date = index[pos]
    pre = index[pos - PRE_WINDOW : pos]
    post_short = index[pos : pos + POST_SHORT]
    post_full = index[pos : pos + POST_FULL]
    return pos, actual_date, pre, post_short, post_full


def collect_event_metrics(event: Event, returns: pd.DataFrame) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    required = {event.ticker, event.sector_etf}
    missing = sorted(t for t in required if t not in returns.columns)
    if missing:
        return None, [{"ticker": event.ticker, "reason": f"missing required columns {missing}"}]
    try:
        pos, actual_date, pre, post_short, post_full = event_slices(returns.index, event.effective_date)
    except ValueError as exc:
        return None, [{"ticker": event.ticker, "reason": str(exc)}]

    valid_peers = valid_peer_list(returns, event.peers, pre, post_full)
    if len(valid_peers) < 4:
        return None, [{"ticker": event.ticker, "reason": f"only {len(valid_peers)} valid peers"}]

    event_pre = returns.loc[pre, event.ticker]
    event_post20 = returns.loc[post_short, event.ticker]
    event_post60 = returns.loc[post_full, event.ticker]
    sector_pre = returns.loc[pre, event.sector_etf]
    sector_post60 = returns.loc[post_full, event.sector_etf]

    peer_pre_rv = []
    peer_post60_rv = []
    peer_jump_pre = []
    peer_jump_post60 = []
    peer_path_denoms: dict[str, float] = {}
    for peer in valid_peers:
        p_pre = returns.loc[pre, peer]
        p_post = returns.loc[post_full, peer]
        pre_sigma = float(p_pre.std(ddof=1))
        peer_pre_rv.append(annualized_rv(p_pre))
        peer_post60_rv.append(annualized_rv(p_post))
        peer_jump_pre.append(jump_rate(p_pre, 2.0 * pre_sigma))
        peer_jump_post60.append(jump_rate(p_post, 2.0 * pre_sigma))
        p_var = float(np.nanmean(p_pre.to_numpy(dtype=float) ** 2))
        if math.isfinite(p_var) and p_var > 0:
            peer_path_denoms[peer] = p_var

    group_cols = [event.ticker, *valid_peers]
    group_pre = returns.loc[pre, group_cols]
    group_post60 = returns.loc[post_full, group_cols]

    event_pre_rv = annualized_rv(event_pre)
    event_post20_rv = annualized_rv(event_post20)
    event_post60_rv = annualized_rv(event_post60)
    sector_pre_rv = annualized_rv(sector_pre)
    sector_post60_rv = annualized_rv(sector_post60)
    peer_pre_avg_rv = float(np.nanmean(peer_pre_rv))
    peer_post60_avg_rv = float(np.nanmean(peer_post60_rv))

    event_pre_sigma = float(event_pre.std(ddof=1))
    event_jump_pre = jump_rate(event_pre, 2.0 * event_pre_sigma)
    event_jump_post60 = jump_rate(event_post60, 2.0 * event_pre_sigma)

    pair_corr_pre = avg_pairwise_corr(group_pre)
    pair_corr_post60 = avg_pairwise_corr(group_post60)
    xs_var_pre = xs_variance(group_pre)
    xs_var_post60 = xs_variance(group_post60)

    row: dict[str, object] = {
        "ticker": event.ticker,
        "company": event.company,
        "index_name": event.index_name,
        "effective_date": event.effective_date,
        "actual_event_trading_date": actual_date.date().isoformat(),
        "sector_etf": event.sector_etf,
        "source": event.source,
        "source_url": event.source_url,
        "notes": event.notes,
        "valid_peer_count": len(valid_peers),
        "valid_peers": ",".join(valid_peers),
        "event_stock_pre_rv": event_pre_rv,
        "event_stock_post20_rv": event_post20_rv,
        "event_stock_post60_rv": event_post60_rv,
        "event_stock_rv_logratio_post20": log_ratio(event_post20_rv, event_pre_rv),
        "event_stock_rv_logratio_post60": log_ratio(event_post60_rv, event_pre_rv),
        "sector_etf_pre_rv": sector_pre_rv,
        "sector_etf_post60_rv": sector_post60_rv,
        "sector_etf_rv_logratio_post60": log_ratio(sector_post60_rv, sector_pre_rv),
        "peer_avg_pre_rv": peer_pre_avg_rv,
        "peer_avg_post60_rv": peer_post60_avg_rv,
        "peer_avg_rv_logratio_post60": log_ratio(peer_post60_avg_rv, peer_pre_avg_rv),
        "stock_minus_peer_rv_logratio_post60": log_ratio(event_post60_rv, event_pre_rv)
        - log_ratio(peer_post60_avg_rv, peer_pre_avg_rv),
        "event_stock_jump_rate_pre": event_jump_pre,
        "event_stock_jump_rate_post60": event_jump_post60,
        "event_stock_jump_rate_delta_post60": event_jump_post60 - event_jump_pre,
        "peer_avg_jump_rate_pre": float(np.nanmean(peer_jump_pre)),
        "peer_avg_jump_rate_post60": float(np.nanmean(peer_jump_post60)),
        "peer_avg_jump_rate_delta_post60": float(np.nanmean(peer_jump_post60))
        - float(np.nanmean(peer_jump_pre)),
        "pairwise_corr_pre": pair_corr_pre,
        "pairwise_corr_post60": pair_corr_post60,
        "pairwise_corr_delta_post60": pair_corr_post60 - pair_corr_pre,
        "xs_dispersion_pre": xs_var_pre,
        "xs_dispersion_post60": xs_var_post60,
        "xs_dispersion_logratio_post60": log_ratio(xs_var_post60, xs_var_pre),
    }

    event_var = float(np.nanmean(event_pre.to_numpy(dtype=float) ** 2))
    sector_var = float(np.nanmean(sector_pre.to_numpy(dtype=float) ** 2))
    path_rows: list[dict[str, object]] = []
    for tau in range(-PRE_WINDOW, POST_FULL + 1):
        idx = returns.index[pos + tau]
        peer_norm_values = []
        for peer, denom in peer_path_denoms.items():
            value = returns.loc[idx, peer]
            if pd.notna(value):
                peer_norm_values.append(float(value * value / denom))
        path_rows.append(
            {
                "ticker": event.ticker,
                "index_name": event.index_name,
                "effective_date": event.effective_date,
                "tau": tau,
                "date": idx.date().isoformat(),
                "event_stock_norm_sqret": safe_float(
                    returns.loc[idx, event.ticker] ** 2 / event_var
                    if math.isfinite(event_var) and event_var > 0
                    else math.nan
                ),
                "sector_etf_norm_sqret": safe_float(
                    returns.loc[idx, event.sector_etf] ** 2 / sector_var
                    if math.isfinite(sector_var) and sector_var > 0
                    else math.nan
                ),
                "peer_avg_norm_sqret": safe_float(np.nanmean(peer_norm_values))
                if peer_norm_values
                else None,
            }
        )
    return row, path_rows


def build_figures(per_event: pd.DataFrame, event_path: pd.DataFrame, summary: pd.DataFrame) -> None:
    path = event_path.copy()
    avg_path = path.groupby("tau")[
        ["event_stock_norm_sqret", "sector_etf_norm_sqret", "peer_avg_norm_sqret"]
    ].mean()
    smooth = avg_path.rolling(5, min_periods=1, center=True).mean()

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(smooth.index, smooth["event_stock_norm_sqret"], label="Included stock", linewidth=2.2)
    ax.plot(smooth.index, smooth["sector_etf_norm_sqret"], label="Sector ETF", linewidth=1.8)
    ax.plot(smooth.index, smooth["peer_avg_norm_sqret"], label="Same-sector peers", linewidth=1.8)
    ax.axvline(0, color="black", linewidth=1.0, linestyle="--")
    ax.axhline(1.0, color="gray", linewidth=0.8, linestyle=":")
    ax.set_title("Normalized Squared Returns Around Index Inclusion")
    ax.set_xlabel("Trading days from effective inclusion date")
    ax.set_ylabel("Squared return / pre-event daily variance")
    ax.legend(frameon=False)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "event_window_normalized_sqret.png", dpi=160)
    plt.close(fig)

    plot_metrics = [
        "event_stock_rv_logratio_post60",
        "sector_etf_rv_logratio_post60",
        "peer_avg_rv_logratio_post60",
        "stock_minus_peer_rv_logratio_post60",
        "event_stock_jump_rate_delta_post60",
        "pairwise_corr_delta_post60",
        "xs_dispersion_logratio_post60",
    ]
    labels = [
        "Stock RV",
        "Sector ETF RV",
        "Peer RV",
        "Stock - peer RV",
        "Stock jump rate",
        "Pairwise corr",
        "XS dispersion",
    ]
    plot_summary = summary.set_index("metric").loc[plot_metrics]
    means = plot_summary["mean"].astype(float).to_numpy()
    lows = plot_summary["bootstrap_ci_low"].astype(float).to_numpy()
    highs = plot_summary["bootstrap_ci_high"].astype(float).to_numpy()
    yerr = np.vstack([means - lows, highs - means])

    fig, ax = plt.subplots(figsize=(10.5, 5.7))
    x = np.arange(len(plot_metrics))
    colors = ["#2b6cb0" if m >= 0 else "#b83232" for m in means]
    ax.bar(x, means, yerr=yerr, capsize=4, color=colors, alpha=0.88)
    ax.axhline(0, color="black", linewidth=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_title("Mean Event Effects with Event-Level Bootstrap 95% CI")
    ax.set_ylabel("Log ratio or rate/correlation delta")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "summary_event_effects.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5.2))
    per_event_sorted = per_event.sort_values("stock_minus_peer_rv_logratio_post60")
    ax.barh(
        per_event_sorted["ticker"] + " " + per_event_sorted["effective_date"].str.slice(0, 7),
        per_event_sorted["stock_minus_peer_rv_logratio_post60"],
        color=[
            "#2b6cb0" if v >= 0 else "#b83232"
            for v in per_event_sorted["stock_minus_peer_rv_logratio_post60"]
        ],
    )
    ax.axvline(0, color="black", linewidth=0.9)
    ax.set_title("Per-Event Included-Stock RV Change Minus Peer RV Change")
    ax.set_xlabel("Post60/pre log RV ratio differential")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "per_event_stock_minus_peer_rv.png", dpi=160)
    plt.close(fig)


def determine_verdict(summary: pd.DataFrame) -> str:
    by_metric = summary.set_index("metric")
    key = by_metric.loc["stock_minus_peer_rv_logratio_post60"]
    jump = by_metric.loc["event_stock_jump_rate_delta_post60"]
    corr = by_metric.loc["pairwise_corr_delta_post60"]

    key_pass = (
        float(key["mean"]) > 0
        and float(key["t_stat"]) > 3.0
        and float(key["bootstrap_ci_low"]) > 0
    )
    broad_passes = sum(
        [
            key_pass,
            float(jump["mean"]) > 0 and float(jump["t_stat"]) > 3.0,
            float(corr["mean"]) > 0 and float(corr["t_stat"]) > 3.0,
        ]
    )
    if key_pass and broad_passes >= 2:
        return "positive_event_diagnostic_but_not_fast_entry_causal"
    if float(key["mean"]) > 0 or float(jump["mean"]) > 0 or float(corr["mean"]) > 0:
        return "weak_or_mixed_event_diagnostic"
    return "null_or_negative_event_diagnostic"


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    tickers = sorted(
        {
            ticker
            for event in EVENTS
            for ticker in (event.ticker, event.sector_etf, *event.peers)
        }
    )
    print(f"Downloading {len(tickers)} tickers from yfinance...")
    close = download_prices(tickers)
    returns = np.log(close).diff().dropna(how="all")

    rows: list[dict[str, object]] = []
    path_rows: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for event in EVENTS:
        row, event_paths = collect_event_metrics(event, returns)
        if row is None:
            skipped.extend(event_paths)
            continue
        rows.append(row)
        path_rows.extend(event_paths)

    if not rows:
        raise RuntimeError("No events survived data-quality filters")

    per_event = pd.DataFrame(rows)
    event_path = pd.DataFrame(path_rows)

    metrics = [
        "event_stock_rv_logratio_post20",
        "event_stock_rv_logratio_post60",
        "sector_etf_rv_logratio_post60",
        "peer_avg_rv_logratio_post60",
        "stock_minus_peer_rv_logratio_post60",
        "event_stock_jump_rate_delta_post60",
        "peer_avg_jump_rate_delta_post60",
        "pairwise_corr_delta_post60",
        "xs_dispersion_logratio_post60",
    ]
    summary_rows = []
    for i, metric in enumerate(metrics):
        stat = summarize_vector(per_event[metric], seed_offset=i)
        cluster = clustered_bootstrap_by_event_date(per_event, metric, seed_offset=i)
        summary_rows.append(
            {
                "metric": metric,
                **stat,
                "cluster_bootstrap_n_clusters": cluster["n_clusters"],
                "cluster_bootstrap_ci_low": cluster["bootstrap_ci_low"],
                "cluster_bootstrap_ci_high": cluster["bootstrap_ci_high"],
            }
        )
    summary = pd.DataFrame(summary_rows)
    verdict = determine_verdict(summary)

    per_event.to_csv(EXP_DIR / "per_event_table.csv", index=False)
    event_path.to_csv(EXP_DIR / "event_window_panel.csv", index=False)
    summary.to_csv(EXP_DIR / "summary_table.csv", index=False)
    build_figures(per_event, event_path, summary)

    key_summary = summary.set_index("metric").to_dict(orient="index")
    payload: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "run_date": date.today().isoformat(),
        "status": "completed",
        "verdict": verdict,
        "scope": "Recent S&P 500 and Nasdaq-100 large-addition/reconstitution event-study proxy; not a direct 2026 mega-IPO fast-entry sample.",
        "data": {
            "source": "yfinance adjusted close via auto_adjust=True",
            "start_date": START_DATE,
            "end_date_exclusive": END_DATE,
            "trading_dates": {
                "first": returns.index.min().date().isoformat(),
                "last": returns.index.max().date().isoformat(),
                "n": int(returns.shape[0]),
            },
            "downloaded_tickers": close.columns.to_list(),
            "missing_tickers": sorted(set(tickers) - set(close.columns)),
        },
        "event_window": {
            "pre_trading_days": PRE_WINDOW,
            "post_short_trading_days": POST_SHORT,
            "post_full_trading_days": POST_FULL,
            "event_date": "effective index-inclusion date, using first trading day on/after effective date when needed",
            "normalization": "pre-event daily variance only; no post-event data is used to set thresholds or denominators",
        },
        "sample": {
            "candidate_events": len(EVENTS),
            "valid_events": int(len(per_event)),
            "skipped_events": skipped,
            "events_by_index": per_event["index_name"].value_counts().to_dict(),
            "event_dates": sorted(per_event["effective_date"].unique().tolist()),
        },
        "summary": key_summary,
        "gate": {
            "primary_metric": "stock_minus_peer_rv_logratio_post60",
            "positive_rule": "mean > 0, event-level t > 3, bootstrap 95% CI low > 0, plus at least one corroborating jump/correlation metric",
            "rationale": "Harvey-style practical threshold for a small, multiple-metric event study.",
        },
        "outputs": {
            "per_event_table": "per_event_table.csv",
            "event_window_panel": "event_window_panel.csv",
            "summary_table": "summary_table.csv",
            "figures": [
                "figures/event_window_normalized_sqret.png",
                "figures/summary_event_effects.png",
                "figures/per_event_stock_minus_peer_rv.png",
            ],
        },
        "limitations": [
            "No observable 2026 mega-IPO fast-entry inclusion had completed in the available price history by 2026-06-24.",
            "S&P DJI publicly declined to add a mega-cap-only fast-track rule in June 2026; Nasdaq fast-entry rule is a methodology change but not yet a rich realized sample.",
            "Same-sector peer sets are hand-built public proxies and are not official GICS peer universes.",
            "Daily adjusted close cannot identify ETF creation/redemption flow, closing-auction demand, or intraday liquidity effects.",
            "Several events share effective dates, so event-level t-tests overstate independence; date-cluster bootstrap intervals are reported as a sensitivity.",
        ],
        "event_sources": [
            {
                "ticker": event.ticker,
                "index": event.index_name,
                "effective_date": event.effective_date,
                "source": event.source,
                "url": event.source_url,
                "notes": event.notes,
            }
            for event in EVENTS
        ],
    }
    write_json(EXP_DIR / f"{EXPERIMENT_ID}_results.json", payload)
    write_json(EXP_DIR / "results.json", payload)

    print(f"Valid events: {len(per_event)} / {len(EVENTS)}")
    print(f"Verdict: {verdict}")
    for metric in [
        "event_stock_rv_logratio_post60",
        "peer_avg_rv_logratio_post60",
        "stock_minus_peer_rv_logratio_post60",
        "event_stock_jump_rate_delta_post60",
        "pairwise_corr_delta_post60",
    ]:
        row = summary.set_index("metric").loc[metric]
        print(
            f"{metric}: mean={row['mean']:.4f}, t={row['t_stat']:.2f}, "
            f"CI=[{row['bootstrap_ci_low']:.4f}, {row['bootstrap_ci_high']:.4f}]"
        )


if __name__ == "__main__":
    main()
