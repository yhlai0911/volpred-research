"""K1550 - FINRA short-volume squeeze-risk proxy and 5-day forward volatility.

This experiment is intentionally a public-data proxy test. FINRA daily
short-sale volume is short-selling flow, not exchange-wide short interest, and
there is no borrow-rate tape here. The tested signal is therefore a squeeze-risk
proxy: short-volume ratio shock plus flow-based days-to-cover pressure.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


SEED = 1550
START = "2023-01-03"
END = "2026-06-12"
EXPERIMENT_ID = "K1550"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FIG_DIR = BASE_DIR / "figures"
RESULT_PATH = BASE_DIR / "k1550_results.json"

K1502_DATA = BASE_DIR.parent / "k1502_proxy_idio_vol" / "data"

TICKERS = [
    "GME",
    "AMC",
    "BB",
    "KOSS",
    "OPEN",
    "KSS",
    "PLTR",
    "SOFI",
    "HOOD",
    "RIVN",
    "LCID",
    "CHWY",
    "DKNG",
    "AFRM",
    "UPST",
    "MARA",
    "RIOT",
    "COIN",
    "CVNA",
    "TLRY",
    "F",
]


@dataclass
class TickerResult:
    ticker: str
    observations: int
    event_days: int
    event_rate: float
    mean_log_fwd5_rv_event: float
    mean_log_fwd5_rv_control: float
    log_rv_diff: float
    welch_t_log_rv: float
    jump_rate_event: float
    jump_rate_control: float
    jump_rate_diff: float
    left_tail_rate_event: float
    left_tail_rate_control: float
    left_tail_rate_diff: float


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def _as_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype(float)


def fetch_finra(symbols: list[str]) -> pd.DataFrame:
    cache = DATA_DIR / "finra_cnms_filtered.csv"
    required = set(symbols)
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        if required.issubset(set(df["Symbol"].unique())):
            return df[df["Symbol"].isin(symbols)].copy()

    k1502_cache = K1502_DATA / "finra_cnms_filtered.csv"
    if not k1502_cache.exists():
        raise FileNotFoundError(f"Required FINRA cache missing: {k1502_cache}")
    df = pd.read_csv(k1502_cache, parse_dates=["date"])
    available = set(df["Symbol"].unique())
    missing = sorted(required - available)
    if missing:
        raise RuntimeError(f"K1502 FINRA cache missing requested symbols: {missing}")
    df = df[df["Symbol"].isin(symbols)].copy()
    df.to_csv(cache, index=False)
    return df


def fetch_prices(symbols: list[str]) -> pd.DataFrame:
    cache = DATA_DIR / "prices.parquet"
    all_symbols = sorted(set(symbols + ["SPY", "IWM"]))
    if cache.exists():
        px = pd.read_parquet(cache)
        if set(all_symbols).issubset(set(px.columns.get_level_values(1))):
            return px.loc[:, pd.IndexSlice[:, all_symbols]].copy()

    k1502_cache = K1502_DATA / "prices.parquet"
    if not k1502_cache.exists():
        raise FileNotFoundError(f"Required yfinance price cache missing: {k1502_cache}")
    px = pd.read_parquet(k1502_cache)
    available = set(px.columns.get_level_values(1))
    missing = sorted(set(all_symbols) - available)
    if missing:
        raise RuntimeError(f"K1502 price cache missing requested symbols: {missing}")
    px = px.loc[:, pd.IndexSlice[:, all_symbols]].copy()
    px.to_parquet(cache)
    return px


def rolling_z(series: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std(ddof=1)
    return (series - mean) / std.replace(0, np.nan)


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    total = pd.Series(0.0, index=series.index)
    for step in range(1, horizon + 1):
        total = total + series.shift(-step)
    return total


def forward_max_abs(series: pd.Series, horizon: int) -> pd.Series:
    frame = pd.concat([series.shift(-step).abs() for step in range(1, horizon + 1)], axis=1)
    return frame.max(axis=1)


def forward_min(series: pd.Series, horizon: int) -> pd.Series:
    frame = pd.concat([series.shift(-step) for step in range(1, horizon + 1)], axis=1)
    return frame.min(axis=1)


def build_panel(finra: pd.DataFrame, prices: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    close_field = "Adj Close" if "Adj Close" in prices.columns.get_level_values(0) else "Close"
    close = prices[close_field]
    volume = prices["Volume"]
    log_returns = np.log(close).diff()
    rows: list[pd.DataFrame] = []
    for ticker in tickers:
        if ticker not in close.columns:
            continue
        df = pd.DataFrame(
            {
                "date": close.index,
                "ticker": ticker,
                "ret": log_returns[ticker],
                "yf_volume": volume[ticker],
            }
        ).dropna(subset=["ret"])
        fin = finra[finra["Symbol"] == ticker].copy()
        merged = df.merge(fin, on="date", how="left")
        merged["short_ratio"] = merged["short_volume"] / merged["offex_total_volume"].replace(0, np.nan)
        merged["short_ratio_change_21d"] = merged["short_ratio"] - merged["short_ratio"].shift(21)
        merged["short_ratio_change_z"] = rolling_z(merged["short_ratio_change_21d"])
        avg_yf_volume_21d = merged["yf_volume"].rolling(21, min_periods=10).mean()
        # Flow-based pressure proxy. This is not true days-to-cover because it
        # uses short-selling flow rather than outstanding shares short.
        merged["flow_dtc_proxy"] = (
            merged["short_volume"].rolling(21, min_periods=10).sum() / avg_yf_volume_21d.replace(0, np.nan)
        )
        merged["flow_dtc_proxy_z"] = rolling_z(merged["flow_dtc_proxy"])
        merged["squeeze_pressure_score"] = merged["short_ratio_change_z"] + merged["flow_dtc_proxy_z"]
        threshold = merged["squeeze_pressure_score"].rolling(252, min_periods=126).quantile(0.90).shift(1)
        merged["squeeze_event"] = (merged["squeeze_pressure_score"] >= threshold).astype(float)
        trailing_sigma = merged["ret"].rolling(63, min_periods=30).std(ddof=1)
        merged["fwd5_rv"] = forward_sum(merged["ret"] ** 2, 5)
        merged["log_fwd5_rv"] = np.log(merged["fwd5_rv"].clip(lower=1e-12))
        merged["fwd5_jump"] = (forward_max_abs(merged["ret"], 5) > 2.0 * trailing_sigma).astype(float)
        merged["fwd5_cum_ret"] = np.exp(forward_sum(merged["ret"], 5)) - 1.0
        left_tail_threshold = merged["fwd5_cum_ret"].rolling(252, min_periods=126).quantile(0.10).shift(1)
        merged["fwd5_left_tail"] = (merged["fwd5_cum_ret"] <= left_tail_threshold).astype(float)
        merged["fwd5_min_ret"] = forward_min(merged["ret"], 5)
        rows.append(merged)
    panel = pd.concat(rows, ignore_index=True)
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel.to_parquet(DATA_DIR / "panel.parquet")
    panel.to_csv(DATA_DIR / "panel_preview.csv", index=False)
    return panel


def bootstrap_ci(values: np.ndarray, reps: int = 5000) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return float("nan"), float("nan")
    draws = rng.choice(values, size=(reps, len(values)), replace=True).mean(axis=1)
    return tuple(np.quantile(draws, [0.025, 0.975]).astype(float))


def summarize(panel: pd.DataFrame) -> tuple[list[TickerResult], dict]:
    rows: list[TickerResult] = []
    effects: list[float] = []
    jump_effects: list[float] = []
    tail_effects: list[float] = []
    for ticker, df in panel.groupby("ticker"):
        usable = df.dropna(
            subset=[
                "squeeze_pressure_score",
                "squeeze_event",
                "log_fwd5_rv",
                "fwd5_jump",
                "fwd5_left_tail",
            ]
        ).copy()
        if len(usable) < 200 or usable["squeeze_event"].sum() < 10:
            continue
        event = usable[usable["squeeze_event"] == 1.0]
        control = usable[usable["squeeze_event"] == 0.0]
        log_diff = float(event["log_fwd5_rv"].mean() - control["log_fwd5_rv"].mean())
        tstat = float(stats.ttest_ind(event["log_fwd5_rv"], control["log_fwd5_rv"], equal_var=False).statistic)
        jump_diff = float(event["fwd5_jump"].mean() - control["fwd5_jump"].mean())
        tail_diff = float(event["fwd5_left_tail"].mean() - control["fwd5_left_tail"].mean())
        rows.append(
            TickerResult(
                ticker=ticker,
                observations=int(len(usable)),
                event_days=int(event.shape[0]),
                event_rate=float(event.shape[0] / len(usable)),
                mean_log_fwd5_rv_event=float(event["log_fwd5_rv"].mean()),
                mean_log_fwd5_rv_control=float(control["log_fwd5_rv"].mean()),
                log_rv_diff=log_diff,
                welch_t_log_rv=tstat,
                jump_rate_event=float(event["fwd5_jump"].mean()),
                jump_rate_control=float(control["fwd5_jump"].mean()),
                jump_rate_diff=jump_diff,
                left_tail_rate_event=float(event["fwd5_left_tail"].mean()),
                left_tail_rate_control=float(control["fwd5_left_tail"].mean()),
                left_tail_rate_diff=tail_diff,
            )
        )
        effects.append(log_diff)
        jump_effects.append(jump_diff)
        tail_effects.append(tail_diff)

    effects_arr = np.asarray(effects)
    jump_arr = np.asarray(jump_effects)
    tail_arr = np.asarray(tail_effects)
    agg = {
        "tickers_tested": len(rows),
        "median_log_rv_diff": float(np.nanmedian(effects_arr)) if len(effects_arr) else float("nan"),
        "mean_log_rv_diff": float(np.nanmean(effects_arr)) if len(effects_arr) else float("nan"),
        "positive_log_rv_tickers": int(np.sum(effects_arr > 0)),
        "log_rv_effect_bootstrap_ci": bootstrap_ci(effects_arr),
        "median_jump_rate_diff": float(np.nanmedian(jump_arr)) if len(jump_arr) else float("nan"),
        "positive_jump_tickers": int(np.sum(jump_arr > 0)),
        "jump_effect_bootstrap_ci": bootstrap_ci(jump_arr),
        "median_left_tail_rate_diff": float(np.nanmedian(tail_arr)) if len(tail_arr) else float("nan"),
        "positive_left_tail_tickers": int(np.sum(tail_arr > 0)),
        "left_tail_effect_bootstrap_ci": bootstrap_ci(tail_arr),
        "sign_test_log_rv_pvalue": float(stats.binomtest(int(np.sum(effects_arr > 0)), len(effects_arr), 0.5).pvalue)
        if len(effects_arr)
        else float("nan"),
    }
    return rows, agg


def make_figures(rows: list[TickerResult]) -> None:
    frame = pd.DataFrame(asdict(r) for r in rows).sort_values("log_rv_diff")
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(frame["ticker"], frame["log_rv_diff"], color=np.where(frame["log_rv_diff"] > 0, "#b84a3a", "#386cb0"))
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Event minus control mean log forward 5d RV")
    ax.set_title("K1550 squeeze-pressure events and next-5d realized volatility")
    ax.tick_params(axis="x", rotation=60)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1550_log_fwd5_rv_event_effect.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(frame["jump_rate_diff"], frame["left_tail_rate_diff"], s=45)
    for _, row in frame.iterrows():
        ax.text(row["jump_rate_diff"], row["left_tail_rate_diff"], row["ticker"], fontsize=8)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Jump-rate diff")
    ax.set_ylabel("Left-tail-rate diff")
    ax.set_title("K1550 jump and left-tail event effects")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1550_jump_tail_effects.png", dpi=160)
    plt.close(fig)


def run() -> dict:
    _ensure_dirs()
    np.random.seed(SEED)
    finra = fetch_finra(TICKERS)
    prices = fetch_prices(TICKERS)
    panel = build_panel(finra, prices, TICKERS)
    rows, agg = summarize(panel)
    make_figures(rows)
    verdict = "NULL_NO_ROBUST_SQUEEZE_RISK_VOL_SIGNAL"
    ci = agg["log_rv_effect_bootstrap_ci"]
    if agg["tickers_tested"] >= 10 and agg["positive_log_rv_tickers"] >= math.ceil(0.7 * agg["tickers_tested"]) and ci[0] > 0:
        verdict = "PARTIAL_SUPPORT_SHORT_VOLUME_SQUEEZE_PROXY"
    result = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Public FINRA short-volume squeeze-risk proxy -> small-cap 5-day RV",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "finra_source": "K1502 cached FINRA CNMS daily short-sale volume files",
            "price_source": "K1502 cached yfinance prices",
            "start": START,
            "end": END,
            "tickers_requested": TICKERS,
            "universe_note": "Fixed 21-name liquid small-cap / meme-risk basket from the K1502 cache; not historical Russell 2000 constituents.",
            "finra_rows": int(len(finra)),
            "panel_rows": int(len(panel)),
        },
        "related_prior": {
            "K1502": "FINRA off-exchange short-volume ratio did not robustly forecast next-day idiosyncratic volatility; K1550 instead tests 5-day squeeze-risk event outcomes.",
        },
        "design": {
            "signal": "squeeze_pressure_score = rolling z(21d change in FINRA short_ratio) + rolling z(flow days-to-cover proxy)",
            "event_rule": "score_t >= rolling 252d 90th percentile through t-1",
            "lookahead_control": "event date t uses FINRA/price information through t; all targets start at t+1 and run through t+5",
            "targets": ["log forward 5d realized variance", "forward 5d jump indicator", "forward 5d left-tail indicator"],
            "critical_limitation": "FINRA daily short-sale volume is public short-selling flow, not true short interest or borrow rate.",
        },
        "ticker_results": [asdict(r) for r in rows],
        "aggregate": agg,
        "figures": [
            "figures/k1550_log_fwd5_rv_event_effect.png",
            "figures/k1550_jump_tail_effects.png",
        ],
        "verdict": verdict,
        "limitations": [
            "No true short interest, securities-lending utilization, borrow fee, recall, or options-gamma data.",
            "FINRA daily files cover public off-exchange short-sale volume and are not consolidated exchange-wide short interest.",
            "Universe is a liquid/current-name small-cap and meme-risk basket, not historical Russell 2000 constituents.",
            "Event rule is reduced-form and should not be marketed as a short-squeeze predictor.",
            "Knowledge promotion is deferred to the main K1259 writer gate.",
        ],
        "literature_basis": [
            {
                "name": "FINRA Short Sale Volume Data",
                "url": "https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data",
            },
            {
                "name": "Hong, Li, Ni, Scheinkman, and Yan (2015), Days to Cover and Stock Returns",
                "url": "https://www.nber.org/system/files/working_papers/w21166/w21166.pdf",
            },
            {
                "name": "Foucault, Sraer, and Thesmar (2011), Individual Investors and Volatility",
                "url": "https://faculty.haas.berkeley.edu/dsraer/SRD.pdf",
            },
            {
                "name": "FINRA Information Notice 5/10/19",
                "url": "https://www.finra.org/rules-guidance/notices/information-notice-051019",
            },
        ],
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    result = run()
    print(json.dumps({"experiment_id": result["experiment_id"], "verdict": result["verdict"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
