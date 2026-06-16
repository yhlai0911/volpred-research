#!/usr/bin/env python3
"""research_rp_05c316a53f: Overnight vs intraday decomposition of momentum.

Question
--------
Do 12-1 month momentum strategies earn their return primarily overnight
(close -> next open) or intraday (open -> close)?

Design
------
This is a free-data, daily-OHLC pilot inspired by Lou, Polk & Skouras'
"tug of war" evidence and newer overnight/intraday retail-flow papers.

Universe:
  - SPY, QQQ plus a liquid large-cap stock panel with long yfinance history.

Signal:
  - 12-1 month momentum = log(adj_close[t-21] / adj_close[t-252]).
  - Signals are sampled at actual month-end trading dates.
  - Daily weights are forward-filled and then shifted by one trading day:
        weights_t = month_end_signal.ffill().shift(1)
    so day t overnight and intraday returns only use information observable
    before the day t open.

Strategies:
  - TSMOM: sign of each asset's own 12-1M momentum, gross normalized to 1.
  - CSMOM: top/bottom 30% of the cross-section, dollar-neutral gross 1.

Evaluation:
  - Split the same weights into overnight and intraday component returns.
  - Compare annualized mean, volatility, Sharpe, skew, max drawdown.
  - Compare overnight vs intraday returns with the project strategy DM helper
    using negative-return loss. Negative t means overnight is better.
  - Stationary block bootstrap CI for annualized mean difference.

The experiment is deliberately conservative: it does not claim to test retail
order flow directly because yfinance has no investor-type flow data.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import strategy_dm_test

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

EXPERIMENT_ID = "research_rp_05c316a53f"
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = OUT_DIR / "fig_overnight_intraday_momentum.png"

SEED = 42
START = "2010-01-01"
END = "2026-06-17"
LOOKBACK_DAYS = 252
SKIP_DAYS = 21
TOP_BOTTOM_FRAC = 0.30
BOOTSTRAP_REPS = 5000
BOOTSTRAP_BLOCK = 20
MIN_OBS = 1500
TRADING_DAYS = 252.0

ETFS = ["SPY", "QQQ"]
STOCKS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA",
    "JPM", "XOM", "JNJ", "PG", "HD", "WMT",
    "BAC", "KO", "PEP", "CSCO", "INTC", "ORCL",
    "IBM", "DIS", "MCD", "V", "MA", "UNH",
    "CVX", "MRK", "PFE", "T", "VZ", "ADBE",
]
TICKERS = ETFS + STOCKS


@dataclass
class StrategyMetrics:
    n_days: int
    ann_mean: float
    ann_vol: float
    sharpe: float
    skew: float
    max_drawdown: float
    hit_rate: float


def _round_float(x: float, digits: int = 6) -> float | None:
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), digits)


def download_ohlc(tickers: Iterable[str]) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """Download yfinance OHLC and return adjusted open and adjusted close.

    yfinance provides Adj Close but not Adj Open when auto_adjust=False. We use
    the standard split/dividend adjustment factor AdjClose / Close and apply it
    to Open, allowing overnight and intraday returns to add up to adjusted
    close-to-close returns except for negligible vendor rounding.
    """
    raw = yf.download(
        list(tickers),
        start=START,
        end=END,
        auto_adjust=False,
        actions=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    adj_open: Dict[str, pd.Series] = {}
    adj_close: Dict[str, pd.Series] = {}
    dropped: Dict[str, str] = {}

    for ticker in tickers:
        try:
            frame = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
            need = frame[["Open", "Close", "Adj Close"]].dropna()
            if len(need) < MIN_OBS:
                dropped[ticker] = f"only {len(need)} observations"
                continue
            factor = need["Adj Close"] / need["Close"]
            ao = need["Open"] * factor
            ac = need["Adj Close"]
            valid = ao.gt(0) & ac.gt(0)
            if valid.sum() < MIN_OBS:
                dropped[ticker] = f"only {int(valid.sum())} positive adjusted OHLC observations"
                continue
            adj_open[ticker] = ao[valid]
            adj_close[ticker] = ac[valid]
        except Exception as exc:  # pragma: no cover - defensive vendor handling
            dropped[ticker] = str(exc)

    open_panel = pd.DataFrame(adj_open).sort_index()
    close_panel = pd.DataFrame(adj_close).sort_index()
    open_panel.index = pd.to_datetime(open_panel.index)
    close_panel.index = pd.to_datetime(close_panel.index)

    meta = {
        "requested_tickers": list(tickers),
        "used_tickers": list(close_panel.columns),
        "dropped_tickers": dropped,
        "start": str(close_panel.index.min().date()),
        "end": str(close_panel.index.max().date()),
        "n_trading_days": int(len(close_panel)),
    }
    return open_panel, close_panel, meta


def component_returns(adj_open: pd.DataFrame, adj_close: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Return overnight, intraday, and close-to-close log returns."""
    overnight = np.log(adj_open / adj_close.shift(1))
    intraday = np.log(adj_close / adj_open)
    close_to_close = overnight + intraday
    return {
        "overnight": overnight.replace([np.inf, -np.inf], np.nan),
        "intraday": intraday.replace([np.inf, -np.inf], np.nan),
        "close_to_close": close_to_close.replace([np.inf, -np.inf], np.nan),
    }


def month_end_trading_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    dates = pd.Series(index, index=index)
    return pd.DatetimeIndex(dates.groupby(index.to_period("M")).tail(1).values)


def momentum_signal(adj_close: pd.DataFrame) -> pd.DataFrame:
    """12-1 month log momentum sampled daily.

    At date t this uses close[t-21] and close[t-252]; the final trading weights
    are shifted one more day before returns are applied.
    """
    return np.log(adj_close.shift(SKIP_DAYS) / adj_close.shift(LOOKBACK_DAYS))


def tsmom_monthly_weights(signal_monthly: pd.DataFrame) -> pd.DataFrame:
    signs = np.sign(signal_monthly)
    gross = signs.abs().sum(axis=1)
    weights = signs.div(gross.replace(0, np.nan), axis=0)
    return weights.where(np.isfinite(weights), np.nan)


def csmom_monthly_weights(signal_monthly: pd.DataFrame) -> pd.DataFrame:
    rows: List[pd.Series] = []
    for _, row in signal_monthly.iterrows():
        valid = row.dropna()
        out = pd.Series(np.nan, index=row.index, dtype=float)
        n = len(valid)
        if n < 10:
            rows.append(out)
            continue
        k = max(1, int(math.floor(n * TOP_BOTTOM_FRAC)))
        ranked = valid.sort_values()
        shorts = ranked.index[:k]
        longs = ranked.index[-k:]
        out.loc[longs] = 0.5 / k
        out.loc[shorts] = -0.5 / k
        rows.append(out)
    weights = pd.DataFrame(rows, index=signal_monthly.index)
    return weights


def daily_weights(monthly_weights: pd.DataFrame, full_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward-fill month-end weights, then lag one trading day."""
    daily = monthly_weights.reindex(full_index).ffill()
    return daily.shift(1)  # explicit anti-lookahead guard


def strategy_returns(weights: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    aligned_w, aligned_r = weights.align(returns, join="inner", axis=0)
    valid_gross = aligned_w.abs().sum(axis=1)
    pnl = (aligned_w * aligned_r).sum(axis=1, min_count=1)
    pnl = pnl.where(valid_gross > 0).dropna()
    return pnl


def max_drawdown(log_returns: pd.Series) -> float:
    if len(log_returns) < 2:
        return float("nan")
    equity = np.exp(log_returns.cumsum())
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def summarize_returns(log_returns: pd.Series) -> StrategyMetrics:
    x = log_returns.dropna()
    if len(x) < 30:
        return StrategyMetrics(0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan)
    ann_mean = float(x.mean() * TRADING_DAYS)
    ann_vol = float(x.std(ddof=1) * math.sqrt(TRADING_DAYS))
    sharpe = ann_mean / ann_vol if ann_vol > 0 else np.nan
    return StrategyMetrics(
        n_days=int(len(x)),
        ann_mean=ann_mean,
        ann_vol=ann_vol,
        sharpe=float(sharpe),
        skew=float(x.skew()),
        max_drawdown=max_drawdown(x),
        hit_rate=float((x > 0).mean()),
    )


def stationary_bootstrap_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / block
    idx = np.empty(n, dtype=int)
    idx[0] = rng.integers(0, n)
    for i in range(1, n):
        if rng.random() < p:
            idx[i] = rng.integers(0, n)
        else:
            idx[i] = (idx[i - 1] + 1) % n
    return idx


def bootstrap_mean_diff_ci(
    overnight: pd.Series,
    intraday: pd.Series,
    reps: int = BOOTSTRAP_REPS,
    block: int = BOOTSTRAP_BLOCK,
    seed: int = SEED,
) -> Dict:
    aligned = pd.concat({"overnight": overnight, "intraday": intraday}, axis=1).dropna()
    diff = (aligned["overnight"] - aligned["intraday"]).values
    if len(diff) < 50:
        return {"n": int(len(diff)), "ann_mean_diff": None, "ci95": [None, None]}
    rng = np.random.default_rng(seed)
    boot = np.empty(reps)
    for b in range(reps):
        idx = stationary_bootstrap_indices(len(diff), block, rng)
        boot[b] = diff[idx].mean() * TRADING_DAYS
    return {
        "n": int(len(diff)),
        "ann_mean_diff": _round_float(diff.mean() * TRADING_DAYS),
        "ci95": [
            _round_float(np.percentile(boot, 2.5)),
            _round_float(np.percentile(boot, 97.5)),
        ],
        "reps": reps,
        "block": block,
        "seed": seed,
    }


def metric_dict(metrics: StrategyMetrics) -> Dict:
    return {
        "n_days": metrics.n_days,
        "ann_mean": _round_float(metrics.ann_mean),
        "ann_vol": _round_float(metrics.ann_vol),
        "sharpe": _round_float(metrics.sharpe),
        "skew": _round_float(metrics.skew),
        "max_drawdown": _round_float(metrics.max_drawdown),
        "hit_rate": _round_float(metrics.hit_rate),
    }


def compare_components(overnight: pd.Series, intraday: pd.Series) -> Dict:
    aligned = pd.concat({"overnight": overnight, "intraday": intraday}, axis=1).dropna()
    if len(aligned) < 50:
        return {"n": int(len(aligned)), "dm": None, "bootstrap": None}
    t_stat, p_value = strategy_dm_test(
        aligned["overnight"].values,
        aligned["intraday"].values,
        h=1,
        loss_fn="negative_return",
    )
    winner = "overnight" if t_stat < 0 else "intraday"
    return {
        "n": int(len(aligned)),
        "dm_negative_return_loss": {
            "t_stat": _round_float(t_stat),
            "p_value": _round_float(p_value),
            "significant_harvey": bool(abs(t_stat) > 3.0),
            "winner": winner,
            "interpretation": "negative t means overnight has higher mean return",
        },
        "bootstrap_ann_mean_diff_overnight_minus_intraday": bootstrap_mean_diff_ci(
            aligned["overnight"], aligned["intraday"]
        ),
    }


def subperiod_signs(overnight: pd.Series, intraday: pd.Series) -> Dict:
    aligned = pd.concat({"overnight": overnight, "intraday": intraday}, axis=1).dropna()
    if len(aligned) < 100:
        return {}
    split_date = aligned.index[int(len(aligned) / 2)]
    periods = {
        "early": aligned.loc[:split_date],
        "late": aligned.loc[split_date:],
    }
    out = {}
    for name, frame in periods.items():
        diff = frame["overnight"] - frame["intraday"]
        out[name] = {
            "start": str(frame.index.min().date()),
            "end": str(frame.index.max().date()),
            "n": int(len(frame)),
            "ann_mean_overnight": _round_float(frame["overnight"].mean() * TRADING_DAYS),
            "ann_mean_intraday": _round_float(frame["intraday"].mean() * TRADING_DAYS),
            "ann_mean_diff": _round_float(diff.mean() * TRADING_DAYS),
            "overnight_gt_intraday": bool(diff.mean() > 0),
        }
    return out


def build_weights_for_universe(adj_close: pd.DataFrame, tickers: List[str]) -> Dict[str, pd.DataFrame]:
    close = adj_close[tickers].dropna(how="all")
    signals = momentum_signal(close)
    mdates = month_end_trading_dates(close.index)
    monthly_signal = signals.loc[signals.index.intersection(mdates)]
    return {
        "TSMOM_12_1": daily_weights(tsmom_monthly_weights(monthly_signal), close.index),
        "CSMOM_top_bottom_30pct_12_1": daily_weights(csmom_monthly_weights(monthly_signal), close.index),
    }


def evaluate_universe(
    universe_name: str,
    tickers: List[str],
    adj_close: pd.DataFrame,
    returns_by_component: Dict[str, pd.DataFrame],
) -> Dict:
    weights_by_strategy = build_weights_for_universe(adj_close, tickers)
    universe_results = {
        "tickers": tickers,
        "n_tickers": len(tickers),
        "strategies": {},
    }
    for strategy_name, weights in weights_by_strategy.items():
        if strategy_name.startswith("CSMOM") and len(tickers) < 10:
            continue
        component_series = {
            comp: strategy_returns(weights, rets[tickers])
            for comp, rets in returns_by_component.items()
        }
        component_metrics = {
            comp: metric_dict(summarize_returns(series))
            for comp, series in component_series.items()
        }
        comparison = compare_components(component_series["overnight"], component_series["intraday"])
        universe_results["strategies"][strategy_name] = {
            "component_metrics": component_metrics,
            "overnight_vs_intraday": comparison,
            "subperiods": subperiod_signs(component_series["overnight"], component_series["intraday"]),
        }
    return universe_results


def derive_verdict(results: Dict) -> Tuple[str, List[str]]:
    findings = []
    primary = results["universes"].get("stocks_only", {})
    strategies = primary.get("strategies", {})
    harvey_positive = 0
    point_positive = 0
    tested = 0

    for name, detail in strategies.items():
        comp = detail.get("overnight_vs_intraday", {})
        dm = comp.get("dm_negative_return_loss") or {}
        boot = comp.get("bootstrap_ann_mean_diff_overnight_minus_intraday") or {}
        diff = boot.get("ann_mean_diff")
        if diff is None:
            continue
        tested += 1
        if diff > 0:
            point_positive += 1
        if dm.get("significant_harvey") and dm.get("winner") == "overnight":
            harvey_positive += 1
        findings.append(
            f"{name}: ann overnight-intraday diff={diff}, "
            f"DM t={dm.get('t_stat')}, p={dm.get('p_value')}, winner={dm.get('winner')}"
        )

    if tested == 0:
        return "INSUFFICIENT_DATA", findings
    if harvey_positive == tested and tested >= 2:
        return "PASS", findings
    if point_positive == tested and harvey_positive >= 1:
        return "CONDITIONAL_PASS", findings
    if point_positive > 0:
        return "NULL", findings
    return "FAIL", findings


def make_plot(results: Dict) -> None:
    rows = []
    for universe, ures in results["universes"].items():
        if universe != "stocks_only":
            continue
        for strategy, sres in ures["strategies"].items():
            for component in ["overnight", "intraday", "close_to_close"]:
                metrics = sres["component_metrics"][component]
                rows.append({
                    "strategy": strategy.replace("_12_1", "").replace("_top_bottom_30pct", ""),
                    "component": component,
                    "ann_mean": metrics["ann_mean"],
                    "sharpe": metrics["sharpe"],
                })
    df = pd.DataFrame(rows)
    if df.empty:
        return

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    colors = {"overnight": "#315f72", "intraday": "#b66b3d", "close_to_close": "#6f7f3f"}
    for ax, metric, title in [
        (axes[0], "ann_mean", "Annualized mean log return"),
        (axes[1], "sharpe", "Annualized Sharpe"),
    ]:
        pivot = df.pivot(index="strategy", columns="component", values=metric)
        pivot[["overnight", "intraday", "close_to_close"]].plot(
            kind="bar",
            ax=ax,
            color=[colors["overnight"], colors["intraday"], colors["close_to_close"]],
            width=0.72,
        )
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel("")
        ax.tick_params(axis="x", rotation=20)
        ax.legend(frameon=False)
    fig.suptitle("12-1M momentum: overnight vs intraday components (stocks-only universe)")
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=170)
    plt.close(fig)


def main() -> Dict:
    np.random.seed(SEED)
    adj_open, adj_close, data_meta = download_ohlc(TICKERS)
    used = data_meta["used_tickers"]
    stock_used = [t for t in STOCKS if t in used]
    etf_used = [t for t in ETFS if t in used]

    returns = component_returns(adj_open[used], adj_close[used])
    universes = {
        "stocks_only": stock_used,
        "large_cap_plus_etf": etf_used + stock_used,
        "etf_only": etf_used,
    }

    result = {
        "experiment_id": EXPERIMENT_ID,
        "title": "12-1M momentum overnight vs intraday decomposition",
        "status": "completed",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance daily OHLC; adjusted open reconstructed from Adj Close / Close factor",
        "sample": {
            "start_requested": START,
            "end_requested": END,
            "actual_start": data_meta["start"],
            "actual_end": data_meta["end"],
            "n_trading_days": data_meta["n_trading_days"],
        },
        "parameters": {
            "lookback_days": LOOKBACK_DAYS,
            "skip_days": SKIP_DAYS,
            "rebalance": "month-end signal, daily forward-fill, weights.shift(1)",
            "top_bottom_frac": TOP_BOTTOM_FRAC,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "bootstrap_block": BOOTSTRAP_BLOCK,
            "seed": SEED,
        },
        "universe_meta": data_meta,
        "lookahead_audit": {
            "momentum_signal": "log(adj_close.shift(21) / adj_close.shift(252)); excludes most recent month",
            "trading_weights": "monthly weights are forward-filled and shifted one trading day before applying returns",
            "return_timing": "overnight_t = log(adj_open_t / adj_close_{t-1}); intraday_t = log(adj_close_t / adj_open_t)",
            "same_day_signal_return": "blocked by daily_weights(...).shift(1)",
        },
        "literature_context": [
            {
                "source": "Lou, Polk & Skouras, A tug of war: Overnight versus intraday expected returns",
                "url": "https://personal.lse.ac.uk/polk/research/TugOfWar.pdf",
                "role": "benchmark finding: momentum-related profits can concentrate overnight with intraday reversal",
            },
            {
                "source": "Ahn, Fan, Noh & Park (2024), Retail Ebb and Flow and the Overnight-Intraday Return Gap",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4752520",
                "role": "mechanism prior: investor-type flow can drive overnight-intraday gap",
            },
            {
                "source": "He (2025), Decoding Momentum Spillover Effects, JFQA",
                "url": "https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/decoding-momentum-spillover-effects/EB6BE5A096753108881E1514E54035DF",
                "role": "mechanism prior: retail/professional split in overnight continuation vs daytime reversal",
            },
            {
                "source": "Perreten & Wallmeier (2025), Overnight Returns and the Timing of Trading Volume",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5004991",
                "role": "recent challenge: volume timing predicts overnight returns beyond simple retail-pressure story",
            },
        ],
        "universes": {},
    }

    for universe_name, tickers in universes.items():
        if not tickers:
            continue
        result["universes"][universe_name] = evaluate_universe(
            universe_name, tickers, adj_close[used], returns
        )

    verdict, findings = derive_verdict(result)
    result["verdict"] = verdict
    result["key_findings"] = findings
    result["limitations"] = [
        "Daily yfinance OHLC cannot observe investor-type retail/institutional flow.",
        "Current-large-cap universe is survivorship-biased and should not be read as CRSP cross-section evidence.",
        "Adjusted open is reconstructed with same-day AdjClose/Close factor; this is standard for split/dividend adjustment but remains vendor-dependent.",
        "Transaction costs, borrow constraints, and opening auction fill uncertainty are not modeled.",
        "This is a return decomposition pilot, not a volatility forecasting experiment.",
    ]

    make_plot(result)
    result["artifacts"] = {
        "results_json": str(RESULTS_PATH.relative_to(OUT_DIR.parent.parent)),
        "figure": str(FIG_PATH.relative_to(OUT_DIR.parent.parent)) if FIG_PATH.exists() else None,
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(json.dumps({
        "experiment_id": EXPERIMENT_ID,
        "verdict": verdict,
        "actual_start": result["sample"]["actual_start"],
        "actual_end": result["sample"]["actual_end"],
        "used_tickers": len(used),
        "results": str(RESULTS_PATH),
    }, indent=2))
    return result


if __name__ == "__main__":
    main()
