"""Defensive factor ETF drawdown decomposition.

Question:
Do low-volatility, quality, and value factor ETFs reduce drawdown frequency,
drawdown depth, or both? Does a simple trend overlay add complementary
protection?

Data source: yfinance adjusted daily prices.

Research-honesty notes:
- This is ETF-level evidence, not stock-level factor-premium replication.
- The trend overlay is explicitly lagged: signal from t-1, return at t.
- Drawdown uses compounded wealth path, not cumulative-return shortcut.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "experiment_defensive_factor_drawdown_decomposition_2026_06_14_results.json"
FIG_BARS = OUT_DIR / "fig_drawdown_decomposition_bars.png"
FIG_WEALTH = OUT_DIR / "fig_wealth_drawdown_paths.png"
FIG_TREND = OUT_DIR / "fig_trend_overlay_effect.png"

TICKERS = {
    "SPY": "S&P 500",
    "USMV": "MSCI USA Minimum Volatility ETF",
    "SPLV": "S&P 500 Low Volatility ETF",
    "QUAL": "MSCI USA Quality ETF",
    "VLUE": "MSCI USA Value ETF",
}
START = "2010-01-01"
END = "2026-06-14"
ANALYSIS_START = "2013-07-19"
SEED = 42
BOOTSTRAP_REPS = 5000
BLOCK_SIZE = 21
MA_WINDOW = 200
TC_BPS = 5.0
BONFERRONI_TESTS = 8


@dataclass
class RiskMetrics:
    ann_return_pct: float
    ann_vol_pct: float
    sharpe: float
    max_drawdown_pct: float
    underwater_share_pct: float
    avg_underwater_depth_pct: float
    drawdown_burden_pct: float
    episodes_ge_5pct: int
    mean_episode_depth_pct: float
    mean_episode_duration_days: float
    worst_day_pct: float


def download_prices() -> pd.DataFrame:
    raw = yf.download(
        list(TICKERS),
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")

    closes = {}
    for ticker in TICKERS:
        if isinstance(raw.columns, pd.MultiIndex):
            closes[ticker] = raw[ticker]["Close"]
        else:
            closes[ticker] = raw["Close"]
    prices = pd.DataFrame(closes).dropna(how="all")
    prices = prices.dropna(subset=TICKERS.keys())
    prices = prices.loc[ANALYSIS_START:]
    if prices.empty:
        raise RuntimeError("No common sample after analysis start")
    return prices


def returns_from_prices(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().dropna()


def wealth_from_returns(returns: pd.Series) -> pd.Series:
    return (1.0 + returns.fillna(0.0)).cumprod()


def drawdown_from_wealth(wealth: pd.Series) -> pd.Series:
    return wealth / wealth.cummax() - 1.0


def find_drawdown_episodes(drawdown: pd.Series, threshold: float = 0.05) -> list[dict]:
    episodes: list[dict] = []
    in_episode = False
    start_idx = None

    for i, value in enumerate(drawdown.to_numpy()):
        if not in_episode and value < 0:
            in_episode = True
            start_idx = max(i - 1, 0)
        if in_episode and value >= 0:
            segment = drawdown.iloc[start_idx : i + 1]
            trough_date = segment.idxmin()
            max_dd = float(segment.min())
            if abs(max_dd) >= threshold:
                episodes.append(
                    {
                        "start": str(segment.index[0].date()),
                        "trough": str(trough_date.date()),
                        "recovery": str(segment.index[-1].date()),
                        "max_drawdown_pct": max_dd * 100,
                        "duration_days": int((segment.index[-1] - segment.index[0]).days),
                    }
                )
            in_episode = False
            start_idx = None

    if in_episode and start_idx is not None:
        segment = drawdown.iloc[start_idx:]
        trough_date = segment.idxmin()
        max_dd = float(segment.min())
        if abs(max_dd) >= threshold:
            episodes.append(
                {
                    "start": str(segment.index[0].date()),
                    "trough": str(trough_date.date()),
                    "recovery": None,
                    "max_drawdown_pct": max_dd * 100,
                    "duration_days": int((segment.index[-1] - segment.index[0]).days),
                }
            )
    return episodes


def compute_risk_metrics(returns: pd.Series) -> tuple[RiskMetrics, pd.Series, list[dict]]:
    returns = returns.dropna()
    wealth = wealth_from_returns(returns)
    drawdown = drawdown_from_wealth(wealth)
    underwater = drawdown[drawdown < 0]
    episodes = find_drawdown_episodes(drawdown)

    ann_ret = wealth.iloc[-1] ** (252 / len(returns)) - 1.0
    ann_vol = returns.std(ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    underwater_share = len(underwater) / len(drawdown)
    avg_depth = abs(float(underwater.mean())) if len(underwater) else 0.0
    burden = underwater_share * avg_depth
    episode_depths = [abs(e["max_drawdown_pct"]) for e in episodes]
    episode_durations = [e["duration_days"] for e in episodes]

    metrics = RiskMetrics(
        ann_return_pct=float(ann_ret * 100),
        ann_vol_pct=float(ann_vol * 100),
        sharpe=float(sharpe),
        max_drawdown_pct=float(drawdown.min() * 100),
        underwater_share_pct=float(underwater_share * 100),
        avg_underwater_depth_pct=float(avg_depth * 100),
        drawdown_burden_pct=float(burden * 100),
        episodes_ge_5pct=len(episodes),
        mean_episode_depth_pct=float(np.mean(episode_depths)) if episode_depths else 0.0,
        mean_episode_duration_days=float(np.mean(episode_durations)) if episode_durations else 0.0,
        worst_day_pct=float(returns.min() * 100),
    )
    return metrics, drawdown, episodes


def paired_block_frame(drawdowns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n_blocks = len(drawdowns) // BLOCK_SIZE
    for block_id in range(n_blocks):
        block = drawdowns.iloc[block_id * BLOCK_SIZE : (block_id + 1) * BLOCK_SIZE]
        for ticker in TICKERS:
            dd = block[ticker]
            underwater = dd[dd < 0]
            rows.append(
                {
                    "block": block_id,
                    "ticker": ticker,
                    "underwater_share": float(len(underwater) / len(dd)),
                    "avg_underwater_depth": float(abs(underwater.mean())) if len(underwater) else 0.0,
                    "drawdown_burden": float(abs(dd[dd < 0].sum()) / len(dd)),
                }
            )
    return pd.DataFrame(rows)


def bootstrap_mean_ci(diff: np.ndarray, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    draws = rng.choice(diff, size=(BOOTSTRAP_REPS, diff.size), replace=True).mean(axis=1)
    return {
        "mean": float(diff.mean()),
        "ci_95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
        "prob_less_than_zero": float((draws < 0).mean()),
    }


def paired_tests(blocks: pd.DataFrame) -> dict:
    tests = {}
    for peer_idx, ticker in enumerate(["USMV", "SPLV", "QUAL", "VLUE"]):
        tests[ticker] = {}
        peer = blocks[blocks["ticker"] == ticker].set_index("block")
        spy = blocks[blocks["ticker"] == "SPY"].set_index("block")
        common = peer.join(spy, lsuffix="_peer", rsuffix="_spy", how="inner")
        for metric_idx, metric in enumerate(["underwater_share", "avg_underwater_depth"]):
            diff = (common[f"{metric}_peer"] - common[f"{metric}_spy"]).to_numpy()
            if np.allclose(diff, 0):
                p_value = 1.0
                stat = 0.0
            else:
                stat, p_value = stats.wilcoxon(diff, alternative="less", zero_method="wilcox")
            boot = bootstrap_mean_ci(diff, SEED + 10 * peer_idx + metric_idx)
            tests[ticker][metric] = {
                "n_blocks": int(diff.size),
                "mean_diff_factor_minus_spy": float(diff.mean()),
                "wilcoxon_stat": float(stat),
                "wilcoxon_pvalue_one_sided_factor_less": float(p_value),
                "bootstrap_ci_95": boot["ci_95"],
                "bootstrap_prob_factor_less": boot["prob_less_than_zero"],
                "bonferroni_pass": bool(p_value < 0.05 / BONFERRONI_TESTS),
            }
    return tests


def trend_overlay_returns(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    ma = prices.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
    raw_signal = (prices > ma).astype(float)
    signal = raw_signal.shift(1).reindex(returns.index)
    turnover = signal.diff().abs().fillna(0.0)
    tc = turnover * (TC_BPS / 10000.0)
    overlay = signal * returns - tc
    return overlay.dropna()


def classify_protection(metrics: dict[str, RiskMetrics], tests: dict) -> dict:
    spy = metrics["SPY"]
    out = {}
    for ticker in ["USMV", "SPLV", "QUAL", "VLUE"]:
        m = metrics[ticker]
        freq_reduction = 1.0 - (m.underwater_share_pct / spy.underwater_share_pct)
        depth_reduction = 1.0 - (m.avg_underwater_depth_pct / spy.avg_underwater_depth_pct)
        freq_pass = tests[ticker]["underwater_share"]["bonferroni_pass"]
        depth_pass = tests[ticker]["avg_underwater_depth"]["bonferroni_pass"]
        burden_reduction = 1.0 - (m.drawdown_burden_pct / spy.drawdown_burden_pct)
        if freq_pass and depth_pass:
            protects = "frequency_and_depth"
        elif freq_pass:
            protects = "frequency"
        elif depth_pass:
            protects = "depth"
        elif burden_reduction > 0:
            protects = "descriptive_only_not_significant"
        else:
            protects = "no_defensive_edge_vs_spy"
        out[ticker] = {
            "underwater_frequency_reduction_vs_spy": float(freq_reduction),
            "conditional_depth_reduction_vs_spy": float(depth_reduction),
            "drawdown_burden_reduction_vs_spy": float(burden_reduction),
            "frequency_test_pass": bool(freq_pass),
            "depth_test_pass": bool(depth_pass),
            "dominant_channel": protects,
        }
    return out


def plot_outputs(
    metrics: dict[str, RiskMetrics],
    drawdowns: pd.DataFrame,
    overlay_metrics: dict[str, RiskMetrics],
    overlay_sample_baseline_metrics: dict[str, RiskMetrics],
) -> None:
    labels = list(TICKERS)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), constrained_layout=True)
    axes[0].bar(labels, [metrics[t].underwater_share_pct for t in labels])
    axes[0].set_title("Underwater frequency")
    axes[0].set_ylabel("% of days")
    axes[1].bar(labels, [metrics[t].avg_underwater_depth_pct for t in labels])
    axes[1].set_title("Conditional depth")
    axes[1].set_ylabel("Avg drawdown when underwater, %")
    axes[2].bar(labels, [metrics[t].drawdown_burden_pct for t in labels])
    axes[2].set_title("Drawdown burden")
    axes[2].set_ylabel("Frequency x depth, %")
    for ax in axes:
        ax.grid(axis="y", alpha=0.3)
    fig.savefig(FIG_BARS, dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5), constrained_layout=True)
    for ticker in labels:
        ax.plot(drawdowns.index, drawdowns[ticker] * 100, label=ticker, linewidth=1.2)
    ax.set_title("Compounded-wealth drawdown paths")
    ax.set_ylabel("Drawdown, %")
    ax.grid(alpha=0.3)
    ax.legend(ncol=3)
    fig.savefig(FIG_WEALTH, dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    x = np.arange(len(labels))
    width = 0.35
    ax.bar(
        x - width / 2,
        [overlay_sample_baseline_metrics[t].max_drawdown_pct for t in labels],
        width,
        label="buy-and-hold same sample",
    )
    ax.bar(x + width / 2, [overlay_metrics[t].max_drawdown_pct for t in labels], width, label="MA200 overlay")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title("Trend overlay effect on max drawdown")
    ax.set_ylabel("Max drawdown, %")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.savefig(FIG_TREND, dpi=150)
    plt.close(fig)


def main() -> None:
    prices = download_prices()
    returns = returns_from_prices(prices)

    metrics: dict[str, RiskMetrics] = {}
    drawdowns = pd.DataFrame(index=returns.index)
    episodes: dict[str, list[dict]] = {}
    for ticker in TICKERS:
        m, dd, eps = compute_risk_metrics(returns[ticker])
        metrics[ticker] = m
        drawdowns[ticker] = dd
        episodes[ticker] = eps

    blocks = paired_block_frame(drawdowns)
    tests = paired_tests(blocks)

    overlay_rets = trend_overlay_returns(prices, returns)
    overlay_metrics: dict[str, RiskMetrics] = {}
    overlay_sample_baseline_metrics: dict[str, RiskMetrics] = {}
    overlay_drawdowns = pd.DataFrame(index=overlay_rets.index)
    for ticker in TICKERS:
        m, dd, _ = compute_risk_metrics(overlay_rets[ticker])
        overlay_metrics[ticker] = m
        overlay_drawdowns[ticker] = dd
        base_m, _, _ = compute_risk_metrics(returns.loc[overlay_rets.index, ticker])
        overlay_sample_baseline_metrics[ticker] = base_m

    channel_classification = classify_protection(metrics, tests)
    plot_outputs(metrics, drawdowns, overlay_metrics, overlay_sample_baseline_metrics)

    result = {
        "experiment_id": "experiment_defensive_factor_drawdown_decomposition_2026_06_14",
        "title": "Defensive factor ETF drawdown frequency-depth decomposition",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_source": "yfinance adjusted close",
        "tickers": TICKERS,
        "sample": {
            "requested_start": START,
            "requested_end": END,
            "analysis_start": str(returns.index[0].date()),
            "analysis_end": str(returns.index[-1].date()),
            "n_days": int(len(returns)),
        },
        "methodology": {
            "drawdown_definition": "compounded wealth drawdown: wealth / cumulative peak - 1",
            "frequency_metric": "share of days with drawdown < 0",
            "depth_metric": "mean absolute drawdown conditional on drawdown < 0",
            "burden_metric": "frequency * conditional depth",
            "block_tests": f"non-overlapping {BLOCK_SIZE}-trading-day paired Wilcoxon tests versus SPY",
            "multiple_testing": f"Bonferroni alpha = {0.05 / BONFERRONI_TESTS:.5f} for {BONFERRONI_TESTS} primary tests",
            "trend_overlay": f"MA{MA_WINDOW}, signal.shift(1), cash return 0, transaction cost {TC_BPS} bps on signal changes",
        },
        "literature": [
            {
                "name": "The Best Defensive Strategies: Two Centuries of Evidence",
                "url": "https://rpc.cfainstitute.org/research/financial-analysts-journal/2026/best-defensive-strategies",
            },
            {
                "name": "Frazzini and Pedersen (2014), Betting Against Beta",
                "url": "https://www.aqr.com/Insights/Research/Journal-Article/Betting-Against-Beta",
            },
            {
                "name": "Asness, Frazzini, and Pedersen (2019), Quality Minus Junk",
                "url": "https://research.cbs.dk/en/publications/quality-minus-junk-2/",
            },
            {
                "name": "Blitz and van Vliet (2007), The Volatility Effect",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=980865",
            },
        ],
        "risk_metrics": {ticker: vars(m) for ticker, m in metrics.items()},
        "episodes_ge_5pct": episodes,
        "paired_block_tests_vs_spy": tests,
        "protection_channel_vs_spy": channel_classification,
        "trend_overlay_metrics": {ticker: vars(m) for ticker, m in overlay_metrics.items()},
        "trend_overlay_same_sample_baseline_metrics": {
            ticker: vars(m) for ticker, m in overlay_sample_baseline_metrics.items()
        },
        "trend_overlay_improvement": {
            ticker: {
                "max_drawdown_delta_pct": float(
                    overlay_metrics[ticker].max_drawdown_pct
                    - overlay_sample_baseline_metrics[ticker].max_drawdown_pct
                ),
                "drawdown_burden_delta_pct": float(
                    overlay_metrics[ticker].drawdown_burden_pct
                    - overlay_sample_baseline_metrics[ticker].drawdown_burden_pct
                ),
            }
            for ticker in TICKERS
        },
        "figures": [
            str(FIG_BARS.relative_to(ROOT)),
            str(FIG_WEALTH.relative_to(ROOT)),
            str(FIG_TREND.relative_to(ROOT)),
        ],
    }

    RESULTS_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        ticker: {
            "dominant_channel": channel_classification.get(ticker, {}).get("dominant_channel"),
            "mdd": metrics[ticker].max_drawdown_pct,
            "burden": metrics[ticker].drawdown_burden_pct,
        }
        for ticker in ["USMV", "SPLV", "QUAL", "VLUE"]
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
