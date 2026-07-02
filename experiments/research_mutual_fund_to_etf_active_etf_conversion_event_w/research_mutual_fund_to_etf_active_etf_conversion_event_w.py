from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "research_mutual_fund_to_etf_active_etf_conversion_event_w"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_DIR = EXP_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
FIGURES_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"

RANDOM_SEED = 42
N_BOOT = 10_000
N_PLACEBO = 3_000
EPS = 1e-12

EVENTS = [
    {
        "batch_id": "guinness_20210326",
        "issuer": "Guinness Atkinson / SmartETFs",
        "fund": "Guinness Atkinson Dividend Builder Fund",
        "ticker": "DIVS",
        "proxy": "VIG",
        "category": "dividend_equity",
        "conversion_date": "2021-03-26",
        "listing_date": "2021-03-26",
        "source": "Business Wire 2021-03-02",
    },
    {
        "batch_id": "guinness_20210326",
        "issuer": "Guinness Atkinson / SmartETFs",
        "fund": "Guinness Atkinson Asia Pacific Dividend Builder Fund",
        "ticker": "ADIV",
        "proxy": "AAXJ",
        "category": "asia_pacific_equity",
        "conversion_date": "2021-03-26",
        "listing_date": "2021-03-26",
        "source": "Business Wire 2021-03-02",
    },
    {
        "batch_id": "dimensional_20210614",
        "issuer": "Dimensional",
        "fund": "DFA Tax-Managed US Equity Portfolio",
        "ticker": "DFUS",
        "proxy": "VTI",
        "category": "us_total_equity",
        "conversion_date": "2021-06-11",
        "listing_date": "2021-06-14",
        "source": "Dimensional 2021-06-14 / SEC 497",
    },
    {
        "batch_id": "dimensional_20210614",
        "issuer": "Dimensional",
        "fund": "DFA T.A. US Core Equity 2 Portfolio",
        "ticker": "DFAC",
        "proxy": "IWB",
        "category": "us_core_equity",
        "conversion_date": "2021-06-11",
        "listing_date": "2021-06-14",
        "source": "Dimensional 2021-06-14 / SEC 497",
    },
    {
        "batch_id": "dimensional_20210614",
        "issuer": "Dimensional",
        "fund": "DFA Tax-Managed US Small Cap Portfolio",
        "ticker": "DFAS",
        "proxy": "IWM",
        "category": "us_small_cap",
        "conversion_date": "2021-06-11",
        "listing_date": "2021-06-14",
        "source": "Dimensional 2021-06-14 / SEC 497",
    },
    {
        "batch_id": "dimensional_20210614",
        "issuer": "Dimensional",
        "fund": "DFA Tax-Managed US Targeted Value Portfolio",
        "ticker": "DFAT",
        "proxy": "IWN",
        "category": "us_small_value",
        "conversion_date": "2021-06-11",
        "listing_date": "2021-06-14",
        "source": "Dimensional 2021-06-14 / SEC 497",
    },
    {
        "batch_id": "jpm_20220411",
        "issuer": "J.P. Morgan Asset Management",
        "fund": "JPMorgan Inflation Managed Bond Fund",
        "ticker": "JCPI",
        "proxy": "TIP",
        "category": "inflation_bond",
        "conversion_date": "2022-04-08",
        "listing_date": "2022-04-11",
        "source": "Morningstar / J.P. Morgan conversion list",
    },
    {
        "batch_id": "jpm_20220509",
        "issuer": "J.P. Morgan Asset Management",
        "fund": "JPMorgan Market Expansion Enhanced Index Fund",
        "ticker": "JMEE",
        "proxy": "IWM",
        "category": "us_extended_market",
        "conversion_date": "2022-05-06",
        "listing_date": "2022-05-09",
        "source": "Morningstar / J.P. Morgan conversion list",
    },
    {
        "batch_id": "jpm_20220523",
        "issuer": "J.P. Morgan Asset Management",
        "fund": "JPMorgan Realty Income Fund",
        "ticker": "JPRE",
        "proxy": "VNQ",
        "category": "real_estate",
        "conversion_date": "2022-05-20",
        "listing_date": "2022-05-23",
        "source": "Morningstar / J.P. Morgan conversion list",
    },
    {
        "batch_id": "jpm_20220613",
        "issuer": "J.P. Morgan Asset Management",
        "fund": "JPMorgan International Research Enhanced Equity Fund",
        "ticker": "JIRE",
        "proxy": "EFA",
        "category": "international_equity",
        "conversion_date": "2022-06-10",
        "listing_date": "2022-06-13",
        "source": "Morningstar / J.P. Morgan conversion list",
    },
]


@dataclass(frozen=True)
class Window:
    values: pd.Series

    @property
    def ok(self) -> bool:
        return self.values.shape[0] > 0 and self.values.notna().all()

    def mean(self) -> float:
        return float(self.values.mean())


def ensure_dirs() -> None:
    for path in [DATA_DIR, RAW_DIR, FIGURES_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def to_jsonable(value):
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def extract_ohlcv(download: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if download.empty:
        raise ValueError(f"No yfinance data for {symbol}")
    data = download.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if symbol in data.columns.get_level_values(-1):
            data = data.xs(symbol, level=-1, axis=1)
        elif symbol in data.columns.get_level_values(0):
            data = data.xs(symbol, level=0, axis=1)
        else:
            data.columns = data.columns.get_level_values(0)
    needed = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    missing = [col for col in needed if col not in data.columns]
    if missing:
        raise ValueError(f"{symbol} missing columns {missing}")
    out = data[needed].copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out.dropna(subset=["Adj Close", "Volume"])


def download_ohlcv(symbol: str) -> pd.DataFrame | None:
    path = RAW_DIR / f"yfinance_ohlcv_{symbol}.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            data = yf.download(
                symbol,
                start="2020-01-01",
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=30,
            )
        out = extract_ohlcv(data, symbol)
    except Exception as exc:
        print(f"Skipping {symbol}: {exc}")
        return None
    out.index.name = "Date"
    out.reset_index().to_csv(path, index=False)
    return out


def build_panels() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    symbols = sorted({event["ticker"] for event in EVENTS} | {event["proxy"] for event in EVENTS})
    frames = {}
    vols = {}
    meta = {}
    for symbol in symbols:
        df = download_ohlcv(symbol)
        if df is None or df.shape[0] < 90:
            meta[symbol] = {"usable": False, "reason": "missing_or_short_history"}
            continue
        frames[symbol] = df["Adj Close"].astype(float)
        vols[symbol] = df["Volume"].astype(float)
        meta[symbol] = {
            "usable": True,
            "start": df.index.min(),
            "end": df.index.max(),
            "n_obs": int(df.shape[0]),
        }
    prices = pd.concat(frames, axis=1).sort_index()
    volume = pd.concat(vols, axis=1).reindex(prices.index).sort_index()
    prices.to_csv(DATA_DIR / "daily_adj_close.csv")
    volume.to_csv(DATA_DIR / "daily_volume.csv")
    return prices, volume, meta


def first_trading_date_on_or_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    candidates = index[index >= date]
    if candidates.empty:
        return None
    return candidates[0]


def window_by_position(series: pd.Series, origin: pd.Timestamp, start_offset: int, end_offset: int) -> Window:
    clean = series.dropna()
    trading_date = first_trading_date_on_or_after(clean.index, origin)
    if trading_date is None:
        return Window(pd.Series(dtype=float))
    loc = clean.index.get_loc(trading_date)
    if isinstance(loc, slice) or isinstance(loc, np.ndarray):
        return Window(pd.Series(dtype=float))
    start = loc + start_offset
    end = loc + end_offset
    if start < 0 or end >= clean.shape[0] or end < start:
        return Window(pd.Series(dtype=float))
    return Window(clean.iloc[start : end + 1])


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return np.log(prices / prices.shift(1)).replace([np.inf, -np.inf], np.nan)


def dollar_volume(prices: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    return (prices * volume).replace([np.inf, -np.inf], np.nan)


def amihud_abs_ret_per_dollar(ret: pd.DataFrame, dollar_vol: pd.DataFrame) -> pd.DataFrame:
    return (ret.abs() / dollar_vol.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def safe_log_ratio(num: float, den: float) -> float | None:
    if not np.isfinite(num) or not np.isfinite(den) or num <= EPS or den <= EPS:
        return None
    return float(np.log(num / den))


def build_wrapper_metrics(prices: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    ret = daily_returns(prices)
    dv = dollar_volume(prices, volume)
    amihud = amihud_abs_ret_per_dollar(ret, dv)
    rows = []
    for event in EVENTS:
        ticker = event["ticker"]
        proxy = event["proxy"]
        origin = pd.Timestamp(event["listing_date"])
        if ticker not in prices or proxy not in prices:
            continue

        early_dv = window_by_position(dv[ticker], origin, 1, 21)
        late_dv = window_by_position(dv[ticker], origin, 43, 63)
        proxy_early_dv = window_by_position(dv[proxy], origin, 1, 21)
        proxy_late_dv = window_by_position(dv[proxy], origin, 43, 63)

        early_ami = window_by_position(amihud[ticker], origin, 1, 21)
        late_ami = window_by_position(amihud[ticker], origin, 43, 63)
        proxy_early_ami = window_by_position(amihud[proxy], origin, 1, 21)
        proxy_late_ami = window_by_position(amihud[proxy], origin, 43, 63)

        aligned = pd.concat([ret[ticker], ret[proxy]], axis=1, keys=["converted", "proxy"]).dropna()
        tracking = (aligned["converted"] - aligned["proxy"]).abs()
        early_track = window_by_position(tracking, origin, 1, 21)
        late_track = window_by_position(tracking, origin, 43, 63)

        required = [
            early_dv,
            late_dv,
            proxy_early_dv,
            proxy_late_dv,
            early_ami,
            late_ami,
            proxy_early_ami,
            proxy_late_ami,
            early_track,
            late_track,
        ]
        if not all(w.ok and w.values.shape[0] >= 15 for w in required):
            continue

        conv_vol_ramp = safe_log_ratio(late_dv.mean(), early_dv.mean())
        proxy_vol_ramp = safe_log_ratio(proxy_late_dv.mean(), proxy_early_dv.mean())
        conv_ami_improve = safe_log_ratio(early_ami.mean(), late_ami.mean())
        proxy_ami_improve = safe_log_ratio(proxy_early_ami.mean(), proxy_late_ami.mean())
        track_improve = safe_log_ratio(early_track.mean(), late_track.mean())
        if None in [conv_vol_ramp, proxy_vol_ramp, conv_ami_improve, proxy_ami_improve, track_improve]:
            continue

        rows.append(
            {
                **event,
                "converted_volume_ramp": conv_vol_ramp,
                "proxy_volume_ramp": proxy_vol_ramp,
                "adjusted_volume_ramp": conv_vol_ramp - proxy_vol_ramp,
                "converted_amihud_improvement": conv_ami_improve,
                "proxy_amihud_improvement": proxy_ami_improve,
                "adjusted_amihud_improvement": conv_ami_improve - proxy_ami_improve,
                "tracking_noise_improvement": track_improve,
                "early_dollar_volume": early_dv.mean(),
                "late_dollar_volume": late_dv.mean(),
                "early_tracking_abs_diff": early_track.mean(),
                "late_tracking_abs_diff": late_track.mean(),
            }
        )
    panel = pd.DataFrame(rows)
    panel.to_csv(DATA_DIR / "wrapper_liquidity_metrics.csv", index=False)
    return panel


def rv_ratio_for_symbol(ret: pd.Series, origin: pd.Timestamp, horizon: int) -> float | None:
    baseline = window_by_position(ret, origin, -60, -11)
    post = window_by_position(ret, origin, 1, horizon)
    if not baseline.ok or not post.ok or baseline.values.shape[0] < 40 or post.values.shape[0] < horizon:
        return None
    baseline_rv = float(np.mean(np.square(baseline.values)))
    post_rv = float(np.mean(np.square(post.values)))
    return safe_log_ratio(post_rv, baseline_rv)


def build_underlying_metrics(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ret = daily_returns(prices)
    rows = []
    for event in EVENTS:
        proxy = event["proxy"]
        if proxy not in ret:
            continue
        origin = pd.Timestamp(event["listing_date"])
        for horizon in [5, 22]:
            value = rv_ratio_for_symbol(ret[proxy], origin, horizon)
            if value is None:
                continue
            rows.append({**event, "horizon": horizon, "underlying_log_rv_ratio": value})
    detail = pd.DataFrame(rows)
    detail.to_csv(DATA_DIR / "underlying_event_metrics.csv", index=False)

    date_level = (
        detail.groupby(["listing_date", "horizon"], as_index=False)
        .agg(
            n_conversions=("ticker", "count"),
            batch_ids=("batch_id", lambda x: ",".join(sorted(set(x)))),
            proxy_set=("proxy", lambda x: ",".join(sorted(set(x)))),
            underlying_log_rv_ratio=("underlying_log_rv_ratio", "mean"),
        )
        .sort_values(["horizon", "listing_date"])
    )
    date_level.to_csv(DATA_DIR / "underlying_date_level_metrics.csv", index=False)
    return detail, date_level


def holm_adjust(pvalues: list[float]) -> list[float]:
    n = len(pvalues)
    order = np.argsort(pvalues)
    adjusted = np.empty(n, dtype=float)
    running_max = 0.0
    for rank, idx in enumerate(order):
        value = min(1.0, (n - rank) * pvalues[idx])
        running_max = max(running_max, value)
        adjusted[idx] = running_max
    return adjusted.tolist()


def summarize(values: np.ndarray, *, alternative: str, rng: np.random.Generator) -> dict:
    values = values[np.isfinite(values)]
    n = int(values.shape[0])
    if n == 0:
        return {"n": 0}
    mean = float(values.mean())
    median = float(np.median(values))
    if n > 1 and float(values.std(ddof=1)) > EPS:
        t_stat = float(mean / (values.std(ddof=1) / math.sqrt(n)))
        p_two = float(stats.t.sf(abs(t_stat), n - 1) * 2.0)
        p_upper = float(stats.t.sf(t_stat, n - 1))
        p_lower = float(stats.t.cdf(t_stat, n - 1))
    else:
        t_stat = None
        p_two = None
        p_upper = None
        p_lower = None
    boot = rng.choice(values, size=(N_BOOT, n), replace=True).mean(axis=1)
    positive = int(np.sum(values > 0.0))
    p_sign_upper = float(stats.binomtest(positive, n=n, p=0.5, alternative="greater").pvalue)
    p_sign_two = float(stats.binomtest(positive, n=n, p=0.5, alternative="two-sided").pvalue)
    primary_p = {"upper": p_upper, "lower": p_lower, "two-sided": p_two}[alternative]
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "t_stat": t_stat,
        "p_t_upper": p_upper,
        "p_t_lower": p_lower,
        "p_t_two_sided": p_two,
        "p_primary": primary_p,
        "sign_positive": positive,
        "p_sign_upper": p_sign_upper,
        "p_sign_two_sided": p_sign_two,
        "boot_ci_low": float(np.quantile(boot, 0.025)),
        "boot_ci_high": float(np.quantile(boot, 0.975)),
        "boot_prob_mean_le_0": float(np.mean(boot <= 0.0)),
    }


def build_anchor_ratios(prices: pd.DataFrame) -> pd.DataFrame:
    ret = daily_returns(prices)
    event_dates = [pd.Timestamp(event["listing_date"]) for event in EVENTS]
    rows = []
    for proxy in sorted({event["proxy"] for event in EVENTS}):
        if proxy not in ret:
            continue
        dates = pd.DatetimeIndex(ret[proxy].dropna().index).unique().sort_values()
        for date in dates:
            if any(abs((date - event_date).days) <= 30 for event_date in event_dates):
                continue
            for horizon in [5, 22]:
                value = rv_ratio_for_symbol(ret[proxy], date, horizon)
                if value is not None:
                    rows.append(
                        {
                            "proxy": proxy,
                            "anchor_date": date,
                            "year": int(date.year),
                            "horizon": horizon,
                            "underlying_log_rv_ratio": value,
                        }
                    )
    panel = pd.DataFrame(rows)
    panel.to_csv(DATA_DIR / "underlying_anchor_metrics.csv", index=False)
    return panel


def placebo_for_underlying(
    anchor_panel: pd.DataFrame,
    detail: pd.DataFrame,
    horizon: int,
    observed_date_level_mean: float,
    rng: np.random.Generator,
) -> dict:
    sub_events = detail[detail["horizon"] == horizon].copy()
    if sub_events.empty:
        return {"n_placebo": 0}
    draws = []
    for _ in range(N_PLACEBO):
        sampled_rows = []
        for _, event in sub_events.iterrows():
            pool = anchor_panel[
                (anchor_panel["proxy"] == event["proxy"])
                & (anchor_panel["horizon"] == horizon)
                & (anchor_panel["year"] == pd.Timestamp(event["listing_date"]).year)
            ]["underlying_log_rv_ratio"].to_numpy(dtype=float)
            if pool.shape[0] == 0:
                continue
            sampled_rows.append(
                {
                    "listing_date": event["listing_date"],
                    "value": float(pool[int(rng.integers(0, pool.shape[0]))]),
                }
            )
        if len(sampled_rows) != sub_events.shape[0]:
            continue
        sampled = pd.DataFrame(sampled_rows)
        date_mean = sampled.groupby("listing_date")["value"].mean().mean()
        draws.append(float(date_mean))
    placebo = np.array(draws, dtype=float)
    if placebo.shape[0] == 0:
        return {"n_placebo": 0}
    return {
        "n_placebo": int(placebo.shape[0]),
        "placebo_mean": float(placebo.mean()),
        "placebo_ci_low": float(np.quantile(placebo, 0.025)),
        "placebo_ci_high": float(np.quantile(placebo, 0.975)),
        "p_placebo_two_sided": float((np.sum(np.abs(placebo) >= abs(observed_date_level_mean)) + 1) / (placebo.shape[0] + 1)),
        "p_placebo_upper": float((np.sum(placebo >= observed_date_level_mean) + 1) / (placebo.shape[0] + 1)),
        "p_placebo_lower": float((np.sum(placebo <= observed_date_level_mean) + 1) / (placebo.shape[0] + 1)),
    }


def summarize_all(wrapper: pd.DataFrame, underlying_detail: pd.DataFrame, date_level: pd.DataFrame, anchor_panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(RANDOM_SEED)
    rows = []
    metric_specs = [
        ("wrapper_adjusted_volume_ramp", "wrapper", "upper", wrapper["adjusted_volume_ramp"].to_numpy(dtype=float)),
        ("wrapper_adjusted_amihud_improvement", "wrapper", "upper", wrapper["adjusted_amihud_improvement"].to_numpy(dtype=float)),
        ("wrapper_tracking_noise_improvement", "wrapper", "upper", wrapper["tracking_noise_improvement"].to_numpy(dtype=float)),
    ]
    for metric, family, alternative, values in metric_specs:
        rows.append({"metric": metric, "family": family, "alternative": alternative, **summarize(values, alternative=alternative, rng=rng)})

    for horizon in [5, 22]:
        sub = date_level[date_level["horizon"] == horizon]
        values = sub["underlying_log_rv_ratio"].to_numpy(dtype=float)
        base = summarize(values, alternative="two-sided", rng=rng)
        placebo = placebo_for_underlying(anchor_panel, underlying_detail, horizon, base["mean"], rng) if base.get("n", 0) else {}
        rows.append(
            {
                "metric": f"underlying_log_rv_ratio_{horizon}d",
                "family": "underlying",
                "alternative": "two-sided",
                **base,
                **placebo,
            }
        )

    summary = pd.DataFrame(rows)
    for col in ["p_primary", "p_sign_upper", "p_sign_two_sided", "p_placebo_two_sided"]:
        if col not in summary:
            continue
        valid = summary[col].notna()
        adjusted = [None] * summary.shape[0]
        vals = summary.loc[valid, col].astype(float).tolist()
        if vals:
            for idx, value in zip(summary.index[valid], holm_adjust(vals)):
                adjusted[idx] = value
        summary[f"{col}_holm"] = adjusted

    summary.to_csv(DATA_DIR / "summary.csv", index=False)
    result_dict = {
        str(row["metric"]): {col: row[col] for col in summary.columns if col != "metric"}
        for _, row in summary.iterrows()
    }
    return summary, result_dict


def make_figures(wrapper: pd.DataFrame, date_level: pd.DataFrame, summary: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    metric_order = [
        "adjusted_volume_ramp",
        "adjusted_amihud_improvement",
        "tracking_noise_improvement",
    ]
    labels = ["Volume ramp", "Illiquidity improvement", "Tracking-noise improvement"]
    values = [wrapper[col].mean() for col in metric_order]
    ax.bar(labels, values, color=["#2f6f9f", "#8e7cc3", "#76a05f"], alpha=0.85)
    ax.axhline(0, color="#333333", linewidth=1)
    ax.set_ylabel("Mean log ratio")
    ax.set_title("Converted ETF wrapper liquidity diagnostics")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "wrapper_liquidity_diagnostics.png", dpi=180)
    plt.close(fig)

    heat = date_level.pivot(index="listing_date", columns="horizon", values="underlying_log_rv_ratio")
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    im = ax.imshow(heat.to_numpy(dtype=float), aspect="auto", cmap="coolwarm", vmin=-1.5, vmax=1.5)
    ax.set_xticks(np.arange(len(heat.columns)))
    ax.set_xticklabels([f"T+1..T+{int(h)}" for h in heat.columns])
    ax.set_yticks(np.arange(len(heat.index)))
    ax.set_yticklabels(heat.index)
    ax.set_title("Underlying proxy log-RV ratios by conversion listing date")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("log(post RV / baseline RV)")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "underlying_rv_event_heatmap.png", dpi=180)
    plt.close(fig)


def verdict(summary: pd.DataFrame) -> str:
    primary = summary.copy()
    strong_wrapper = primary[
        (primary["family"] == "wrapper")
        & (primary["mean"] > 0)
        & (primary["p_primary_holm"].fillna(1.0) < 0.05)
        & (primary["boot_ci_low"] > 0)
    ]
    strong_underlying = primary[
        (primary["family"] == "underlying")
        & (primary["p_primary_holm"].fillna(1.0) < 0.05)
        & (primary["p_placebo_two_sided_holm"].fillna(1.0) < 0.05)
    ]
    weak = primary[(primary["p_primary"].fillna(1.0) < 0.10) | (primary.get("p_placebo_two_sided", pd.Series(1.0, index=primary.index)).fillna(1.0) < 0.10)]
    if not strong_wrapper.empty or not strong_underlying.empty:
        return "positive_or_structural_change"
    if not weak.empty:
        return "weak_raw_only"
    return "null_or_inconclusive"


def main() -> None:
    ensure_dirs()
    prices, volume, price_meta = build_panels()
    wrapper = build_wrapper_metrics(prices, volume)
    underlying_detail, date_level = build_underlying_metrics(prices)
    anchor_panel = build_anchor_ratios(prices)
    if wrapper.empty or date_level.empty:
        raise RuntimeError("Required event panels are empty")
    summary_df, summary = summarize_all(wrapper, underlying_detail, date_level, anchor_panel)
    make_figures(wrapper, date_level, summary_df)
    result_verdict = verdict(summary_df)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now().astimezone().isoformat(),
        "random_seed": RANDOM_SEED,
        "events": EVENTS,
        "data_sources": {
            "prices": {
                "provider": "yfinance",
                "auto_adjust": False,
                "fields": ["Adj Close", "Volume"],
                "start": "2020-01-01",
                "price_meta": price_meta,
            },
            "event_sources": [
                "Business Wire Guinness Atkinson conversion date release",
                "Dimensional 2021-06-14 conversion/listing release",
                "SEC 497 Dimensional conversion information statement",
                "Morningstar/J.P. Morgan conversion listing dates",
                "Federal Reserve FEDS Notes 2025 mutual-fund-to-ETF conversion evidence",
            ],
        },
        "method": {
            "wrapper_liquidity": "Converted ETF T+1..T+21 vs T+43..T+63 dollar-volume ramp and Amihud improvement, adjusted by category proxy over the same windows.",
            "tracking_noise": "Mean absolute converted ETF return minus category proxy return, T+1..T+21 vs T+43..T+63.",
            "underlying_rv": "Category proxy log realized-variance ratio, baseline T-60..T-11 versus post T+1..T+5 or T+1..T+22.",
            "underlying_inference_unit": "unique listing-date mean, so same-day Dimensional/Guinness conversions do not multiply the same market date.",
            "same_day_treatment": "Listing/conversion day returns are excluded from primary RV windows.",
            "bootstrap": {"seed": RANDOM_SEED, "n_boot": N_BOOT, "unit": "ETF event for wrapper metrics; listing-date for underlying RV"},
            "placebo": {"seed": RANDOM_SEED, "n_placebo": N_PLACEBO, "rule": "same-proxy, same-year non-event anchors excluding +/-30 calendar days around true listing dates"},
        },
        "diagnostics": {
            "n_conversion_rows": len(EVENTS),
            "n_wrapper_rows": int(wrapper.shape[0]),
            "n_underlying_detail_rows": int(underlying_detail.shape[0]),
            "n_underlying_listing_dates": int(date_level["listing_date"].nunique()),
            "n_anchor_rows": int(anchor_panel.shape[0]),
        },
        "summary": summary,
        "verdict": result_verdict,
        "files": {
            "wrapper_liquidity_metrics": str(DATA_DIR / "wrapper_liquidity_metrics.csv"),
            "underlying_event_metrics": str(DATA_DIR / "underlying_event_metrics.csv"),
            "underlying_date_level_metrics": str(DATA_DIR / "underlying_date_level_metrics.csv"),
            "underlying_anchor_metrics": str(DATA_DIR / "underlying_anchor_metrics.csv"),
            "summary": str(DATA_DIR / "summary.csv"),
            "figures": [
                str(FIGURES_DIR / "wrapper_liquidity_diagnostics.png"),
                str(FIGURES_DIR / "underlying_rv_event_heatmap.png"),
            ],
        },
    }
    RESULTS_PATH.write_text(json.dumps(to_jsonable(results), indent=2), encoding="utf-8")
    print(json.dumps(to_jsonable({"verdict": result_verdict, "summary": summary}), indent=2))


if __name__ == "__main__":
    main()
