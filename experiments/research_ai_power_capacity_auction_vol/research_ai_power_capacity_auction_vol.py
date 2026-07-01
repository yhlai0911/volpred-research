#!/usr/bin/env python3
"""
Capacity-auction event windows for the AI electricity-supercycle theme.

Question:
    Did PJM/MISO capacity-auction announcements create a measurable next-day
    volatility shock in utility ETFs, independent power producers, or uranium
    proxies after AI/data-center power demand became a market narrative?

Lookahead policy:
    - Same-day event returns are descriptive only.
    - The primary target is the next trading day after the announcement date.
    - Volatility-normalization baselines use rolling 252-trading-day medians
      shifted by one day, so the target day never contributes to its own
      baseline.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


EXPERIMENT_ID = "research_ai_power_capacity_auction_vol"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
EVENT_ASSET_PATH = DATA_DIR / "capacity_auction_event_asset_panel.csv"
EVENT_GROUP_PATH = DATA_DIR / "capacity_auction_event_group_panel.csv"
CLOSE_PATH = DATA_DIR / "close_panel.csv"
FIG_PATH = FIG_DIR / "capacity_auction_next_day_rv_ratio.png"

SEED = 42
START_DATE = "2020-01-01"
END_DATE = "2026-07-02"
BASELINE_WINDOW = 252
MIN_BASELINE_OBS = 126
BOOT_REPS = 5000
BOOTSTRAP_BLACKOUT_TRADING_DAYS = 5
EPS = 1e-12

GROUPS = {
    "utility_etf": ["XLU", "VPU"],
    "ipp_capacity": ["VST", "CEG", "NRG"],
    "uranium": ["URA"],
    "market": ["SPY", "QQQ"],
}
TICKERS = sorted({ticker for members in GROUPS.values() for ticker in members})

EVENTS = [
    {
        "event_id": "pjm_2023_2024_bra",
        "date": "2022-06-21",
        "market": "PJM",
        "delivery_year": "2023/2024",
        "headline": "RTO capacity price $34.13/MW-day versus $50.00 prior auction.",
        "source_url": "https://insidelines.pjm.com/pjm-capacity-auction-secures-electricity-supplies-at-competitive-prices/",
        "confidence": "high",
    },
    {
        "event_id": "pjm_2024_2025_bra",
        "date": "2023-02-27",
        "market": "PJM",
        "delivery_year": "2024/2025",
        "headline": "RTO capacity price $28.92/MW-day.",
        "source_url": "https://insidelines.pjm.com/pjm-capacity-auction-procures-adequate-resources/",
        "confidence": "high",
    },
    {
        "event_id": "miso_2024_2025_pra",
        "date": "2024-04-26",
        "market": "MISO",
        "delivery_year": "2024/2025",
        "headline": "MISO 2024/2025 PRA results posting.",
        "source_url": "https://cdn.misoenergy.org/2024%20PRA%20Results%20Posting%2020240425632665.pdf",
        "confidence": "medium",
    },
    {
        "event_id": "pjm_2025_2026_bra",
        "date": "2024-07-30",
        "market": "PJM",
        "delivery_year": "2025/2026",
        "headline": "RTO capacity price $269.92/MW-day, up from $28.92.",
        "source_url": "https://www.pjm.com/-/media/DotCom/markets-ops/rpm/rpm-auction-info/2025-2026/2025-2026-base-residual-auction-report.pdf",
        "confidence": "high",
    },
    {
        "event_id": "miso_2025_2026_pra",
        "date": "2025-05-29",
        "market": "MISO",
        "delivery_year": "2025/2026",
        "headline": "Summer clearing price $666.50/MW-day in a tight planning-resource auction.",
        "source_url": "https://cdn.misoenergy.org/2025%20PRA%20Results%20Posting%2020250529_Corrections694160.pdf",
        "confidence": "high",
    },
    {
        "event_id": "pjm_2026_2027_bra",
        "date": "2025-07-22",
        "market": "PJM",
        "delivery_year": "2026/2027",
        "headline": "PJM capacity auction cleared near the price cap at $329.17/MW-day.",
        "source_url": "https://insidelines.pjm.com/pjm-auction-procures-134311-mw-of-generation-resources-supply-responds-to-price-signal/",
        "confidence": "high",
    },
    {
        "event_id": "pjm_2027_2028_bra",
        "date": "2025-12-17",
        "market": "PJM",
        "delivery_year": "2027/2028",
        "headline": "PJM capacity auction cleared at the $333.44/MW-day price cap.",
        "source_url": "https://insidelines.pjm.com/pjm-auction-procures-134479-mw-of-generation-resources/",
        "confidence": "high",
    },
    {
        "event_id": "miso_2026_2027_pra",
        "date": "2026-04-28",
        "market": "MISO",
        "delivery_year": "2026/2027",
        "headline": "MISO 2026/2027 PRA results released after the 2025/2026 price shock.",
        "source_url": "https://www.misoenergy.org/markets-and-operations/resource-adequacy/",
        "confidence": "medium",
    },
]

LITERATURE_AND_CONTEXT = [
    {
        "citation": "IEA (2025), Energy and AI",
        "url": "https://www.iea.org/reports/energy-and-ai/energy-demand-from-ai",
        "role": "Documents the data-centre electricity-demand acceleration motivating the AI power-capacity theme.",
    },
    {
        "citation": "Lawrence Berkeley National Laboratory (2024), United States Data Center Energy Usage Report",
        "url": "https://eta.lbl.gov/publications/2024-lbnl-data-center-energy-usage-report",
        "role": "Demand-growth validation source; not treated as a capacity-auction market shock in the primary test.",
    },
    {
        "citation": "U.S. Department of Energy (2026), Clean Energy Resources to Meet Data Center Electricity Demand",
        "url": "https://www.energy.gov/oe/clean-energy-resources-meet-data-center-electricity-demand",
        "role": "Policy and power-system framing source; not treated as a capacity-auction market shock in the primary test.",
    },
    {
        "citation": "PJM Base Residual Auction reports and PJM Inside Lines announcements",
        "url": "https://www.pjm.com/markets-and-operations/rpm",
        "role": "Primary source for PJM capacity-auction price announcements and delivery-year details.",
    },
    {
        "citation": "MISO Planning Resource Auction result postings",
        "url": "https://www.misoenergy.org/markets-and-operations/resource-adequacy/",
        "role": "Primary source family for MISO capacity-auction result dates.",
    },
    {
        "citation": "K1508: AI power-demand narrative and utility/grid ETF forward volatility",
        "url": "../k1508_ai_power_utility_vol/README.md",
        "role": "Prior broad-regime screen; this run isolates capacity-auction event timing.",
    },
    {
        "citation": "K_ai_infra_financing_spillover_2026_06_14",
        "url": "../k_ai_infra_financing_spillover_2026_06_14/README.md",
        "role": "Prior lead-lag spillover screen; this run tests an explicit power-market catalyst list.",
    },
]


@dataclass
class GroupSummary:
    group: str
    tickers: list[str]
    n_event_group_obs: int
    n_unique_events: int
    mean_same_day_abs_ratio: float
    mean_next_day_abs_ratio: float
    mean_same_day_rv_ratio: float
    mean_next_day_rv_ratio: float
    median_next_day_rv_ratio: float
    mean_next_day_rv_ratio_minus_market: float | None
    bootstrap_random_mean_next_day_rv_ratio: float
    bootstrap_ci95_next_day_rv_ratio: list[float]
    bootstrap_p_upper_next_day_rv_ratio: float
    primary_gate_pass: bool


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isfinite(value):
            return float(value)
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def _extract_close(data: pd.DataFrame, ticker: str) -> pd.Series:
    if isinstance(data.columns, pd.MultiIndex):
        if ticker in data.columns.get_level_values(0):
            close = data[ticker]["Close"]
        else:
            close = data.xs("Close", axis=1, level=-1)[ticker]
    else:
        close = data["Close"]
    close = close.copy()
    close.name = ticker
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    return close[~close.index.duplicated(keep="last")].sort_index()


def fetch_close_panel() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    data = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if data is None or data.empty:
        raise RuntimeError("yfinance returned an empty close panel")
    close = pd.DataFrame({ticker: _extract_close(data, ticker) for ticker in TICKERS})
    close = close.dropna(how="all").sort_index()
    close.to_csv(CLOSE_PATH, index_label="date")
    return close


def build_ratios(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    log_ret = np.log(close / close.shift(1))
    rv = log_ret.pow(2)
    abs_ret = log_ret.abs()
    rv_baseline = rv.shift(1).rolling(BASELINE_WINDOW, min_periods=MIN_BASELINE_OBS).median()
    abs_baseline = abs_ret.shift(1).rolling(BASELINE_WINDOW, min_periods=MIN_BASELINE_OBS).median()
    return {
        "log_ret": log_ret,
        "rv": rv,
        "abs_ret": abs_ret,
        "rv_baseline_shift1": rv_baseline,
        "abs_baseline_shift1": abs_baseline,
        "rv_ratio": rv / rv_baseline.clip(lower=EPS),
        "abs_ratio": abs_ret / abs_baseline.clip(lower=EPS),
    }


def first_trading_date_on_or_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    pos = index.searchsorted(date)
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def trading_day_offset(index: pd.DatetimeIndex, date: pd.Timestamp, offset: int) -> pd.Timestamp | None:
    pos = index.searchsorted(date)
    if pos >= len(index) or index[pos] != date:
        return None
    out_pos = pos + offset
    if out_pos < 0 or out_pos >= len(index):
        return None
    return pd.Timestamp(index[out_pos])


def _group_for_ticker(ticker: str) -> str:
    for group, members in GROUPS.items():
        if ticker in members:
            return group
    raise KeyError(ticker)


def event_asset_panel(close: pd.DataFrame, ratios: dict[str, pd.DataFrame]) -> pd.DataFrame:
    market_index = pd.DatetimeIndex(close["SPY"].dropna().index)
    rows = []
    for event in EVENTS:
        event_calendar_date = pd.Timestamp(event["date"])
        trade_date = first_trading_date_on_or_after(market_index, event_calendar_date)
        if trade_date is None:
            continue
        next_date = trading_day_offset(market_index, trade_date, 1)
        second_date = trading_day_offset(market_index, trade_date, 2)
        if next_date is None:
            continue
        for ticker in TICKERS:
            if ticker not in close.columns:
                continue
            values = {
                "same_day_abs_ratio": ratios["abs_ratio"].at[trade_date, ticker]
                if trade_date in ratios["abs_ratio"].index
                else np.nan,
                "next_day_abs_ratio": ratios["abs_ratio"].at[next_date, ticker]
                if next_date in ratios["abs_ratio"].index
                else np.nan,
                "t_plus_2_abs_ratio": ratios["abs_ratio"].at[second_date, ticker]
                if second_date is not None and second_date in ratios["abs_ratio"].index
                else np.nan,
                "same_day_rv_ratio": ratios["rv_ratio"].at[trade_date, ticker]
                if trade_date in ratios["rv_ratio"].index
                else np.nan,
                "next_day_rv_ratio": ratios["rv_ratio"].at[next_date, ticker]
                if next_date in ratios["rv_ratio"].index
                else np.nan,
                "t_plus_2_rv_ratio": ratios["rv_ratio"].at[second_date, ticker]
                if second_date is not None and second_date in ratios["rv_ratio"].index
                else np.nan,
                "same_day_return": ratios["log_ret"].at[trade_date, ticker]
                if trade_date in ratios["log_ret"].index
                else np.nan,
                "next_day_return": ratios["log_ret"].at[next_date, ticker]
                if next_date in ratios["log_ret"].index
                else np.nan,
            }
            if not np.isfinite(values["next_day_rv_ratio"]):
                continue
            rows.append(
                {
                    "event_id": event["event_id"],
                    "calendar_date": event["date"],
                    "event_trading_date": trade_date.strftime("%Y-%m-%d"),
                    "primary_target_date": next_date.strftime("%Y-%m-%d"),
                    "second_target_date": second_date.strftime("%Y-%m-%d") if second_date else None,
                    "market": event["market"],
                    "delivery_year": event["delivery_year"],
                    "headline": event["headline"],
                    "source_url": event["source_url"],
                    "source_confidence": event["confidence"],
                    "ticker": ticker,
                    "group": _group_for_ticker(ticker),
                    **values,
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(EVENT_ASSET_PATH, index=False)
    return out


def event_group_panel(asset_panel: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [
        "same_day_abs_ratio",
        "next_day_abs_ratio",
        "t_plus_2_abs_ratio",
        "same_day_rv_ratio",
        "next_day_rv_ratio",
        "t_plus_2_rv_ratio",
        "same_day_return",
        "next_day_return",
    ]
    group_cols = [
        "event_id",
        "calendar_date",
        "event_trading_date",
        "primary_target_date",
        "market",
        "delivery_year",
        "group",
    ]
    grouped = asset_panel.groupby(group_cols, dropna=False)
    rows = []
    for keys, grp in grouped:
        row = dict(zip(group_cols, keys))
        row["tickers_with_data"] = ",".join(sorted(grp["ticker"].unique()))
        row["n_tickers"] = int(grp["ticker"].nunique())
        for col in metric_cols:
            row[f"{col}_mean"] = float(grp[col].mean())
        rows.append(row)
    out = pd.DataFrame(rows).sort_values(["event_trading_date", "group"])
    out.to_csv(EVENT_GROUP_PATH, index=False)
    return out


def _blackout_dates(market_index: pd.DatetimeIndex, event_trade_dates: list[pd.Timestamp]) -> set[pd.Timestamp]:
    blackout: set[pd.Timestamp] = set()
    for event_date in event_trade_dates:
        pos = market_index.searchsorted(event_date)
        if pos >= len(market_index) or market_index[pos] != event_date:
            continue
        lo = max(0, pos - BOOTSTRAP_BLACKOUT_TRADING_DAYS)
        hi = min(len(market_index), pos + BOOTSTRAP_BLACKOUT_TRADING_DAYS + 1)
        blackout.update(pd.Timestamp(x) for x in market_index[lo:hi])
    return blackout


def _group_value_at_anchor(
    market_index: pd.DatetimeIndex,
    ratio_panel: pd.DataFrame,
    anchor_date: pd.Timestamp,
    tickers: list[str],
    horizon: int,
) -> float:
    target_date = trading_day_offset(market_index, anchor_date, horizon)
    if target_date is None or target_date not in ratio_panel.index:
        return np.nan
    vals = [ratio_panel.at[target_date, ticker] for ticker in tickers if ticker in ratio_panel.columns]
    vals = [float(v) for v in vals if np.isfinite(v)]
    if not vals:
        return np.nan
    return float(np.mean(vals))


def bootstrap_candidates_by_year(
    close: pd.DataFrame,
    ratio_panel: pd.DataFrame,
    tickers: list[str],
    horizon: int,
    event_trade_dates: list[pd.Timestamp],
) -> dict[int, list[float]]:
    market_index = pd.DatetimeIndex(close["SPY"].dropna().index)
    blackout = _blackout_dates(market_index, event_trade_dates)
    out: dict[int, list[float]] = {}
    for anchor in market_index:
        anchor_ts = pd.Timestamp(anchor)
        if anchor_ts in blackout:
            continue
        if trading_day_offset(market_index, anchor_ts, horizon) is None:
            continue
        value = _group_value_at_anchor(market_index, ratio_panel, anchor_ts, tickers, horizon)
        if np.isfinite(value):
            out.setdefault(anchor_ts.year, []).append(value)
    return out


def matched_bootstrap(
    observed: pd.DataFrame,
    candidates_by_year: dict[int, list[float]],
    value_col: str,
    rng: np.random.Generator,
) -> dict:
    obs = observed[["event_trading_date", value_col]].copy()
    obs["event_trading_date"] = pd.to_datetime(obs["event_trading_date"])
    obs = obs[np.isfinite(obs[value_col])]
    obs_mean = float(obs[value_col].mean()) if len(obs) else np.nan
    draws = []
    for _ in range(BOOT_REPS):
        vals = []
        for _, row in obs.iterrows():
            year = pd.Timestamp(row["event_trading_date"]).year
            pool = candidates_by_year.get(year, [])
            if not pool:
                continue
            vals.append(float(rng.choice(pool)))
        if vals:
            draws.append(float(np.mean(vals)))
    draw_arr = np.array(draws, dtype=float)
    if len(draw_arr) == 0:
        return {
            "observed_mean": obs_mean,
            "random_mean": np.nan,
            "ci95": [np.nan, np.nan],
            "p_upper": np.nan,
            "n_draws": 0,
        }
    return {
        "observed_mean": obs_mean,
        "random_mean": float(draw_arr.mean()),
        "ci95": [float(x) for x in np.percentile(draw_arr, [2.5, 97.5])],
        "p_upper": float((1.0 + np.sum(draw_arr >= obs_mean)) / (len(draw_arr) + 1.0)),
        "n_draws": int(len(draw_arr)),
    }


def summarize_groups(close: pd.DataFrame, ratios: dict[str, pd.DataFrame], group_panel: pd.DataFrame) -> list[GroupSummary]:
    market_index = pd.DatetimeIndex(close["SPY"].dropna().index)
    event_trade_dates = [
        first_trading_date_on_or_after(market_index, pd.Timestamp(event["date"]))
        for event in EVENTS
    ]
    event_trade_dates = [x for x in event_trade_dates if x is not None]
    rng = np.random.default_rng(SEED)
    market_next = (
        group_panel[group_panel["group"] == "market"]
        .set_index("event_id")["next_day_rv_ratio_mean"]
        .to_dict()
    )

    summaries: list[GroupSummary] = []
    for group, tickers in GROUPS.items():
        observed = group_panel[group_panel["group"] == group].copy()
        candidates = bootstrap_candidates_by_year(
            close=close,
            ratio_panel=ratios["rv_ratio"],
            tickers=tickers,
            horizon=1,
            event_trade_dates=event_trade_dates,
        )
        boot = matched_bootstrap(observed, candidates, "next_day_rv_ratio_mean", rng)
        diffs = []
        for _, row in observed.iterrows():
            market_value = market_next.get(row["event_id"])
            if market_value is None or not np.isfinite(market_value):
                continue
            diffs.append(float(row["next_day_rv_ratio_mean"] - market_value))
        mean_minus_market = float(np.mean(diffs)) if diffs else None
        gate_pass = bool(
            group in {"utility_etf", "ipp_capacity"}
            and np.isfinite(boot["observed_mean"])
            and boot["observed_mean"] > 2.0
            and np.isfinite(boot["p_upper"])
            and boot["p_upper"] < 0.05
            and mean_minus_market is not None
            and mean_minus_market > 0.25
        )
        summaries.append(
            GroupSummary(
                group=group,
                tickers=tickers,
                n_event_group_obs=int(len(observed)),
                n_unique_events=int(observed["event_id"].nunique()),
                mean_same_day_abs_ratio=float(observed["same_day_abs_ratio_mean"].mean()),
                mean_next_day_abs_ratio=float(observed["next_day_abs_ratio_mean"].mean()),
                mean_same_day_rv_ratio=float(observed["same_day_rv_ratio_mean"].mean()),
                mean_next_day_rv_ratio=float(observed["next_day_rv_ratio_mean"].mean()),
                median_next_day_rv_ratio=float(observed["next_day_rv_ratio_mean"].median()),
                mean_next_day_rv_ratio_minus_market=mean_minus_market,
                bootstrap_random_mean_next_day_rv_ratio=float(boot["random_mean"]),
                bootstrap_ci95_next_day_rv_ratio=[float(x) for x in boot["ci95"]],
                bootstrap_p_upper_next_day_rv_ratio=float(boot["p_upper"]),
                primary_gate_pass=gate_pass,
            )
        )
    return summaries


def make_figure(summaries: list[GroupSummary]) -> None:
    labels = [s.group for s in summaries]
    values = [s.mean_next_day_rv_ratio for s in summaries]
    random_means = [s.bootstrap_random_mean_next_day_rv_ratio for s in summaries]
    lo = [s.bootstrap_ci95_next_day_rv_ratio[0] for s in summaries]
    hi = [s.bootstrap_ci95_next_day_rv_ratio[1] for s in summaries]
    x = np.arange(len(labels))
    colors = ["#3b6ea8", "#c2573a", "#5d8f4e", "#6c6c6c"]

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    ax.bar(x, values, color=colors[: len(labels)], width=0.62, label="Event mean")
    ax.scatter(x, random_means, color="black", s=32, zorder=4, label="Matched random-date mean")
    for i, (lower, upper) in enumerate(zip(lo, hi)):
        if np.isfinite(lower) and np.isfinite(upper):
            ax.vlines(i, lower, upper, color="black", linewidth=1.2, alpha=0.75)
    ax.axhline(1.0, color="#222222", linestyle="--", linewidth=1.0)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Next-day squared-return ratio vs lagged 252d median")
    ax.set_title("Capacity Auction Announcements: Next-Day Volatility Ratios")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=180)
    plt.close(fig)


def build_results() -> dict:
    close = fetch_close_panel()
    ratios = build_ratios(close)
    asset_panel = event_asset_panel(close, ratios)
    if asset_panel.empty:
        raise RuntimeError("No event asset observations survived data filters")
    group_panel = event_group_panel(asset_panel)
    summaries = summarize_groups(close, ratios, group_panel)
    make_figure(summaries)

    passed_groups = [s.group for s in summaries if s.primary_gate_pass]
    verdict = "DIRECTIONAL_EVENT_SPIKE" if passed_groups else "NULL_NO_ROBUST_CAPACITY_AUCTION_VOL_SPIKE"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "AI power capacity-auction event windows and equity volatility",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "source": "yfinance adjusted close",
            "tickers": TICKERS,
            "groups": GROUPS,
            "start_date": START_DATE,
            "end_date_exclusive": END_DATE,
            "sample_first_price_date": close.index.min().strftime("%Y-%m-%d"),
            "sample_last_price_date": close.index.max().strftime("%Y-%m-%d"),
            "n_price_dates": int(len(close)),
        },
        "design": {
            "event_count": len(EVENTS),
            "primary_target": "next trading day after auction-result announcement",
            "descriptive_only": "same-day event-trading-date ratios are reported but not used as the primary target",
            "volatility_proxy": "daily squared log return",
            "normalization": (
                "squared return divided by its own lagged rolling 252-trading-day median; "
                "baseline uses rv.shift(1).rolling(252, min_periods=126).median()"
            ),
            "bootstrap": {
                "seed": SEED,
                "repetitions": BOOT_REPS,
                "matching": "random non-event trading dates matched by event calendar year",
                "blackout_trading_days_around_events": BOOTSTRAP_BLACKOUT_TRADING_DAYS,
                "p_value": "one-sided upper tail: share of matched random-date means >= observed event mean",
            },
            "primary_gate": (
                "utility_etf or ipp_capacity group must have mean next-day RV ratio > 2.0, "
                "year-matched bootstrap p_upper < 0.05, and mean next-day RV ratio at least "
                "0.25 above the same-event market group"
            ),
        },
        "events": EVENTS,
        "literature_and_context": LITERATURE_AND_CONTEXT,
        "group_summaries": [asdict(s) for s in summaries],
        "passed_groups": passed_groups,
        "event_group_panel_preview": group_panel.head(12).to_dict(orient="records"),
        "outputs": {
            "event_asset_panel": str(EVENT_ASSET_PATH.relative_to(HERE)),
            "event_group_panel": str(EVENT_GROUP_PATH.relative_to(HERE)),
            "close_panel": str(CLOSE_PATH.relative_to(HERE)),
            "figure": str(FIG_PATH.relative_to(HERE)),
        },
        "research_honesty_notes": [
            "This is an event-window diagnostic, not a tradable forecasting model.",
            "Capacity-auction release times are not standardized in this script; same-day ratios are therefore descriptive only.",
            "Daily closes are too coarse to identify intraday announcement reactions.",
            "Ticker exposures are public-market proxies and do not map perfectly to individual PJM/MISO load zones.",
            "The event list is small, so bootstrap p-values are screening evidence rather than a definitive structural test.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(_json_safe(results), ensure_ascii=False, indent=2))
    return results


def main() -> None:
    results = build_results()
    print(
        json.dumps(
            {
                "experiment_id": results["experiment_id"],
                "verdict": results["verdict"],
                "passed_groups": results["passed_groups"],
                "results_path": str(RESULTS_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
