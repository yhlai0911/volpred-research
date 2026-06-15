#!/usr/bin/env python3
"""
research_functional_role

Functional-role test for layered defensive allocations:
- TLT as a long-duration first responder
- DBMF as a managed-futures / trend-following proxy second responder
- A lagged vol-target overlay as a risk-budget responder

The crisis windows are ex-post descriptive labels. They are never used as
signals. The only dynamic allocation is the vol-target scale, and it is built
from t-1 realized information via .shift(1).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


EXPERIMENT_ID = "research_functional_role"
HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
FIG_DRAWDOWNS = HERE / "fig_strategy_drawdowns.png"
FIG_CONTRIB = HERE / "fig_crisis_contributions.png"

SEED = 42
np.random.seed(SEED)

DATA_START = "2019-05-01"
DATA_END = "2026-06-16"  # inclusive enough for yfinance through 2026-06-15 close if available
OOS_START = "2020-01-02"
ASSETS = ["SPY", "TLT", "DBMF"]

TRADING_DAYS = 252
VOL_TARGET = 0.12
VOL_LOOKBACK = 63
SCALE_MIN = 0.50
SCALE_MAX = 1.50

BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21

STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "SPY": {"SPY": 1.0, "TLT": 0.0, "DBMF": 0.0},
    "SPY_TLT_80_20": {"SPY": 0.80, "TLT": 0.20, "DBMF": 0.0},
    "SPY_DBMF_80_20": {"SPY": 0.80, "TLT": 0.0, "DBMF": 0.20},
    "MULTI_LAYER_70_15_15": {"SPY": 0.70, "TLT": 0.15, "DBMF": 0.15},
}

CRISIS_WINDOWS = {
    "2020_covid_liquidity": {
        "start": "2020-02-19",
        "end": "2020-03-23",
        "expected_first_responder": "TLT",
        "expected_second_responder": "DBMF",
        "description": "Fast liquidity crash from SPY pre-COVID peak to trough.",
    },
    "2022_rate_shock": {
        "start": "2022-01-03",
        "end": "2022-10-12",
        "expected_first_responder": "DBMF",
        "expected_second_responder": "vol_target_overlay",
        "description": "Persistent inflation/rate-hiking drawdown; long duration is expected to struggle.",
    },
    "2025_policy_shock": {
        "start": "2025-02-19",
        "end": "2025-04-08",
        "expected_first_responder": "vol_target_overlay",
        "expected_second_responder": "DBMF",
        "description": "Sharp policy/tariff shock window; used only as an ex-post stress label.",
    },
}


def download_close(ticker: str) -> pd.Series:
    data = yf.download(
        ticker,
        start=DATA_START,
        end=DATA_END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if data.empty:
        raise RuntimeError(f"yfinance returned no rows for {ticker}")
    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna().astype(float)
    close.name = ticker
    return close


def load_returns() -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = pd.concat([download_close(ticker) for ticker in ASSETS], axis=1).dropna(how="any")
    returns = prices.pct_change().dropna(how="any")
    if returns.loc[returns.index >= pd.Timestamp(OOS_START)].empty:
        raise RuntimeError("No OOS return rows after alignment")
    return prices, returns


def weighted_returns(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    weight_vec = pd.Series(weights).reindex(returns.columns).fillna(0.0)
    out = returns.mul(weight_vec, axis=1).sum(axis=1)
    out.name = "_".join(f"{k}{v:.2f}" for k, v in weights.items() if v)
    return out


def build_strategies(returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    strategy_returns = {}
    for name, weights in STRATEGY_WEIGHTS.items():
        strategy_returns[name] = weighted_returns(returns, weights)

    base = strategy_returns["MULTI_LAYER_70_15_15"]
    lagged_realized_vol = base.rolling(VOL_LOOKBACK).std() * math.sqrt(TRADING_DAYS)
    # Critical anti-lookahead line: scale used for return_t is estimated with
    # realized volatility available at t-1.
    vt_scale = (VOL_TARGET / lagged_realized_vol).clip(SCALE_MIN, SCALE_MAX).shift(1)
    vt_scale = vt_scale.reindex(base.index).fillna(1.0)
    strategy_returns["MULTI_LAYER_VT_70_15_15"] = base * vt_scale

    return pd.DataFrame(strategy_returns).dropna(how="any"), vt_scale


def max_drawdown(ret: pd.Series) -> float:
    wealth = (1.0 + ret).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    return float(drawdown.min())


def cagr(ret: pd.Series) -> float:
    if ret.empty:
        return float("nan")
    wealth = float((1.0 + ret).prod())
    years = len(ret) / TRADING_DAYS
    if wealth <= 0 or years <= 0:
        return float("nan")
    return wealth ** (1.0 / years) - 1.0


def sharpe(ret: pd.Series) -> float:
    sd = float(ret.std(ddof=1))
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(ret.mean() / sd * math.sqrt(TRADING_DAYS))


def perf_stats(ret: pd.Series) -> dict[str, float | int]:
    mdd = max_drawdown(ret)
    annual_return = cagr(ret)
    annual_vol = float(ret.std(ddof=1) * math.sqrt(TRADING_DAYS))
    calmar = annual_return / abs(mdd) if mdd < 0 else float("nan")
    tail_5 = float(np.percentile(ret, 5))
    cvar_5 = float(ret[ret <= tail_5].mean())
    return {
        "n_days": int(ret.shape[0]),
        "cagr": annual_return,
        "annual_vol": annual_vol,
        "sharpe": sharpe(ret),
        "max_drawdown": mdd,
        "calmar": calmar,
        "worst_day": float(ret.min()),
        "best_day": float(ret.max()),
        "left_tail_days_le_minus_2pct": int((ret <= -0.02).sum()),
        "left_tail_frequency_le_minus_2pct": float((ret <= -0.02).mean()),
        "daily_var_5pct": tail_5,
        "daily_cvar_5pct": cvar_5,
    }


def crisis_slice(series: pd.Series, start: str, end: str) -> pd.Series:
    return series.loc[(series.index >= pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))]


def crisis_metrics(
    returns: pd.DataFrame,
    strategy_returns: pd.DataFrame,
    vt_scale: pd.Series,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    multi_weights = STRATEGY_WEIGHTS["MULTI_LAYER_70_15_15"]
    base_multi = strategy_returns["MULTI_LAYER_70_15_15"]
    vt_multi = strategy_returns["MULTI_LAYER_VT_70_15_15"]

    for window_name, spec in CRISIS_WINDOWS.items():
        start = spec["start"]
        end = spec["end"]
        row: dict[str, object] = {**spec}
        row["strategy_metrics"] = {
            name: {
                "compound_return": float((1.0 + crisis_slice(ret, start, end)).prod() - 1.0),
                "max_drawdown": max_drawdown(crisis_slice(ret, start, end)),
                "n_days": int(crisis_slice(ret, start, end).shape[0]),
            }
            for name, ret in strategy_returns.items()
        }

        component_contrib = {
            asset: float((crisis_slice(returns[asset], start, end) * weight).sum())
            for asset, weight in multi_weights.items()
        }
        overlay_contrib = float(crisis_slice(vt_multi - base_multi, start, end).sum())
        row["multi_layer_arithmetic_contribution"] = {
            **component_contrib,
            "vol_target_overlay_incremental": overlay_contrib,
            "note": "Arithmetic contribution approximation; strategy metrics use compounded returns.",
        }
        row["vt_scale"] = {
            "mean": float(crisis_slice(vt_scale, start, end).mean()),
            "min": float(crisis_slice(vt_scale, start, end).min()),
            "max": float(crisis_slice(vt_scale, start, end).max()),
        }
        out[window_name] = row
    return out


def moving_block_bootstrap(
    candidate: pd.Series,
    benchmark: pd.Series,
    metric: Callable[[pd.Series, pd.Series], float],
    reps: int = BOOTSTRAP_REPS,
    block: int = BOOTSTRAP_BLOCK,
    seed: int = SEED,
) -> dict[str, float | int | list[float]]:
    paired = pd.concat([candidate, benchmark], axis=1, join="inner").dropna()
    paired.columns = ["candidate", "benchmark"]
    n = len(paired)
    if n < block * 2:
        raise ValueError(f"Need at least {block * 2} observations for block bootstrap; got {n}")

    rng = np.random.default_rng(seed)
    arr = paired.to_numpy()
    n_blocks = int(math.ceil(n / block))
    max_start = n - block
    draws = np.empty(reps)

    obs = metric(paired["candidate"], paired["benchmark"])
    for i in range(reps):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        sampled = arr[idx]
        cand = pd.Series(sampled[:, 0])
        bench = pd.Series(sampled[:, 1])
        draws[i] = metric(cand, bench)

    if obs >= 0:
        one_sided_p = float((draws <= 0).mean())
    else:
        one_sided_p = float((draws >= 0).mean())

    return {
        "observed": float(obs),
        "ci_95": [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))],
        "one_sided_p_against_zero": one_sided_p,
        "reps": int(reps),
        "block_size_days": int(block),
        "seed": int(seed),
    }


def metric_mdd_improvement(candidate: pd.Series, benchmark: pd.Series) -> float:
    return max_drawdown(candidate) - max_drawdown(benchmark)


def metric_cvar5_improvement(candidate: pd.Series, benchmark: pd.Series) -> float:
    cand_cut = np.percentile(candidate, 5)
    bench_cut = np.percentile(benchmark, 5)
    return float(candidate[candidate <= cand_cut].mean() - benchmark[benchmark <= bench_cut].mean())


def metric_left_tail_frequency_reduction(candidate: pd.Series, benchmark: pd.Series) -> float:
    return float((benchmark <= -0.02).mean() - (candidate <= -0.02).mean())


def bootstrap_tests(strategy_returns: pd.DataFrame) -> dict[str, dict[str, dict]]:
    comparisons = {
        "multi_layer_vt_vs_spy": (
            strategy_returns["MULTI_LAYER_VT_70_15_15"],
            strategy_returns["SPY"],
        ),
        "multi_layer_vt_vs_unscaled_multi_layer": (
            strategy_returns["MULTI_LAYER_VT_70_15_15"],
            strategy_returns["MULTI_LAYER_70_15_15"],
        ),
    }
    metrics = {
        "mdd_improvement": metric_mdd_improvement,
        "cvar5_improvement": metric_cvar5_improvement,
        "left_tail_frequency_reduction": metric_left_tail_frequency_reduction,
    }
    out: dict[str, dict[str, dict]] = {}
    for comp_name, (candidate, benchmark) in comparisons.items():
        out[comp_name] = {
            metric_name: moving_block_bootstrap(candidate, benchmark, metric_func)
            for metric_name, metric_func in metrics.items()
        }
    return out


def role_score(crisis: dict[str, dict]) -> dict[str, object]:
    rows = {}
    for window, data in crisis.items():
        contrib = data["multi_layer_arithmetic_contribution"]
        expected_first = data["expected_first_responder"]
        expected_second = data["expected_second_responder"]

        responder_map = {
            "TLT": contrib["TLT"],
            "DBMF": contrib["DBMF"],
            "SPY": contrib["SPY"],
            "vol_target_overlay": contrib["vol_target_overlay_incremental"],
        }
        positive_non_spy = {
            k: v
            for k, v in responder_map.items()
            if k != "SPY" and isinstance(v, (int, float)) and v > 0
        }
        sorted_positive = sorted(positive_non_spy.items(), key=lambda kv: kv[1], reverse=True)
        top = sorted_positive[0][0] if sorted_positive else None
        second = sorted_positive[1][0] if len(sorted_positive) > 1 else None

        rows[window] = {
            "expected_first": expected_first,
            "expected_second": expected_second,
            "observed_positive_rank": [k for k, _ in sorted_positive],
            "top_matches_first": top == expected_first,
            "top_two_include_expected_pair": expected_first in positive_non_spy
            and expected_second in positive_non_spy,
        }

    n = len(rows)
    first_hits = sum(bool(v["top_matches_first"]) for v in rows.values())
    pair_hits = sum(bool(v["top_two_include_expected_pair"]) for v in rows.values())
    return {
        "windows": rows,
        "first_responder_hits": int(first_hits),
        "expected_pair_hits": int(pair_hits),
        "n_windows": int(n),
    }


def decide_verdict(
    stats: dict[str, dict],
    crisis: dict[str, dict],
    boot: dict[str, dict[str, dict]],
    roles: dict[str, object],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    spy_mdd = stats["SPY"]["max_drawdown"]
    vt_mdd = stats["MULTI_LAYER_VT_70_15_15"]["max_drawdown"]
    spy_sharpe = stats["SPY"]["sharpe"]
    vt_sharpe = stats["MULTI_LAYER_VT_70_15_15"]["sharpe"]

    tail_boot = boot["multi_layer_vt_vs_spy"]["cvar5_improvement"]
    mdd_boot = boot["multi_layer_vt_vs_spy"]["mdd_improvement"]
    left_tail_boot = boot["multi_layer_vt_vs_spy"]["left_tail_frequency_reduction"]

    pair_hits = int(roles["expected_pair_hits"])
    first_hits = int(roles["first_responder_hits"])
    n_windows = int(roles["n_windows"])

    reasons.append(f"Expected responder pair positive in {pair_hits}/{n_windows} crisis windows.")
    reasons.append(f"Top first responder matched in {first_hits}/{n_windows} crisis windows.")
    reasons.append(f"SPY MDD {spy_mdd:.1%}; multi-layer VT MDD {vt_mdd:.1%}.")
    reasons.append(f"SPY Sharpe {spy_sharpe:.2f}; multi-layer VT Sharpe {vt_sharpe:.2f}.")
    reasons.append(
        "Bootstrap vs SPY: "
        f"MDD improvement p={mdd_boot['one_sided_p_against_zero']:.3f}, "
        f"CVaR5 improvement p={tail_boot['one_sided_p_against_zero']:.3f}, "
        f"left-tail reduction p={left_tail_boot['one_sided_p_against_zero']:.3f}."
    )

    bootstrap_pass = (
        mdd_boot["observed"] > 0
        and mdd_boot["ci_95"][0] > 0
        and tail_boot["observed"] > 0
        and tail_boot["ci_95"][0] > 0
        and left_tail_boot["observed"] > 0
        and left_tail_boot["ci_95"][0] >= 0
    )
    role_pass = pair_hits == n_windows and first_hits >= 2
    drawdown_pass = vt_mdd > spy_mdd
    sharpe_not_worse = vt_sharpe >= spy_sharpe - 0.10

    if role_pass and bootstrap_pass and drawdown_pass and sharpe_not_worse:
        verdict = "PASS_FUNCTIONAL_ROLES_AND_TAIL_IMPROVEMENT"
    elif pair_hits >= 2 and drawdown_pass and vt_sharpe > 0:
        verdict = "CONDITIONAL_PASS_MIXED_FUNCTIONAL_ROLES"
    else:
        verdict = "NULL_MIXED_RESPONDER_EVIDENCE"
    return verdict, reasons


def plot_drawdowns(strategy_returns: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    plot_cols = ["SPY", "SPY_TLT_80_20", "SPY_DBMF_80_20", "MULTI_LAYER_70_15_15", "MULTI_LAYER_VT_70_15_15"]
    for col in plot_cols:
        wealth = (1.0 + strategy_returns[col]).cumprod()
        drawdown = wealth / wealth.cummax() - 1.0
        ax.plot(drawdown.index, drawdown, label=col.replace("_", " "), linewidth=1.4)
    for spec in CRISIS_WINDOWS.values():
        ax.axvspan(pd.Timestamp(spec["start"]), pd.Timestamp(spec["end"]), color="0.85", alpha=0.35)
    ax.set_title("OOS Drawdowns: layered defensive allocations")
    ax.set_ylabel("Drawdown")
    ax.yaxis.set_major_formatter(lambda x, pos: f"{x:.0%}")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DRAWDOWNS, dpi=180)
    plt.close(fig)


def plot_contributions(crisis: dict[str, dict]) -> None:
    rows = []
    for window, data in crisis.items():
        contrib = data["multi_layer_arithmetic_contribution"]
        for component in ["SPY", "TLT", "DBMF", "vol_target_overlay_incremental"]:
            rows.append(
                {
                    "window": window.replace("_", "\n"),
                    "component": component.replace("_", " "),
                    "contribution": contrib[component],
                }
            )
    df = pd.DataFrame(rows)
    pivot = df.pivot(index="window", columns="component", values="contribution")
    colors = {
        "SPY": "#4C78A8",
        "TLT": "#59A14F",
        "DBMF": "#F28E2B",
        "vol target overlay incremental": "#E15759",
    }

    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    bottom_pos = np.zeros(len(pivot))
    bottom_neg = np.zeros(len(pivot))
    x = np.arange(len(pivot))
    for component in ["SPY", "TLT", "DBMF", "vol target overlay incremental"]:
        vals = pivot[component].to_numpy()
        pos = np.where(vals > 0, vals, 0.0)
        neg = np.where(vals < 0, vals, 0.0)
        ax.bar(x, pos, bottom=bottom_pos, label=component, color=colors[component])
        ax.bar(x, neg, bottom=bottom_neg, color=colors[component])
        bottom_pos += pos
        bottom_neg += neg
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index)
    ax.set_title("Multi-layer arithmetic contribution by crisis window")
    ax.set_ylabel("Sum of daily return contributions")
    ax.yaxis.set_major_formatter(lambda y, pos: f"{y:.0%}")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_CONTRIB, dpi=180)
    plt.close(fig)


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
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main() -> None:
    prices, returns = load_returns()
    full_strategy_returns, full_vt_scale = build_strategies(returns)
    strategy_returns = full_strategy_returns.loc[full_strategy_returns.index >= pd.Timestamp(OOS_START)]
    vt_scale = full_vt_scale.loc[strategy_returns.index]
    common_returns = returns.loc[strategy_returns.index]

    stats = {name: perf_stats(strategy_returns[name]) for name in strategy_returns.columns}
    crisis = crisis_metrics(common_returns, strategy_returns, vt_scale)
    boot = bootstrap_tests(strategy_returns)
    roles = role_score(crisis)
    verdict, verdict_reasons = decide_verdict(stats, crisis, boot, roles)

    plot_drawdowns(strategy_returns)
    plot_contributions(crisis)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "verdict": verdict,
        "verdict_reasons": verdict_reasons,
        "seed": SEED,
        "data": {
            "source": "yfinance auto_adjust=True close prices",
            "tickers": ASSETS,
            "data_start": DATA_START,
            "data_end_parameter": DATA_END,
            "aligned_price_start": prices.dropna().index.min(),
            "aligned_price_end": prices.dropna().index.max(),
            "oos_start": OOS_START,
            "oos_end": strategy_returns.index.max(),
            "oos_days": int(strategy_returns.shape[0]),
        },
        "method": {
            "crisis_windows_are_ex_post_descriptive": True,
            "dynamic_signal": "vol target scale only",
            "anti_lookahead": "vt_scale = (target / rolling_63d_vol).clip(0.50, 1.50).shift(1)",
            "vol_target": VOL_TARGET,
            "vol_lookback_days": VOL_LOOKBACK,
            "scale_bounds": [SCALE_MIN, SCALE_MAX],
            "transaction_costs": "Not subtracted; static ETF prices include fund-level expenses but not rebalancing costs/taxes.",
            "bootstrap": {
                "type": "paired moving block bootstrap on OOS daily returns",
                "reps": BOOTSTRAP_REPS,
                "block_size_days": BOOTSTRAP_BLOCK,
                "seed": SEED,
            },
        },
        "strategy_weights": STRATEGY_WEIGHTS,
        "performance": stats,
        "crisis_windows": crisis,
        "role_score": roles,
        "bootstrap_tests": boot,
        "figures": {
            "drawdowns": str(FIG_DRAWDOWNS.relative_to(HERE)),
            "crisis_contributions": str(FIG_CONTRIB.relative_to(HERE)),
        },
        "limitations": [
            "DBMF is an ETF proxy for managed futures and starts only in May 2019.",
            "Crisis windows are ex-post labels for decomposition, not train/test selectors or trading signals.",
            "No direct option-based tail hedge is included; vol targeting is only a risk-budget overlay.",
            "Transaction costs, taxes, and daily rebalancing frictions are not modeled.",
        ],
        "literature_context": [
            {
                "title": "Schwalbach and Auret (2025), Enhancing global equity returns with trend-following and tail risk hedging overlays",
                "url": "https://www.tandfonline.com/doi/full/10.1080/10293523.2025.2553254",
            },
            {
                "title": "J.P. Morgan Asset Management 2026 Long-Term Capital Market Assumptions",
                "url": "https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/portfolio-insights/ltcma/noindex/ltcma-full-report.pdf",
            },
            {
                "title": "Eastspring Investments, Smarter risk management overlays for multi-asset portfolios",
                "url": "https://www.eastspring.com/insights/deep-dives/smarter-risk-management-overlays-for-multi-asset-portfolios",
            },
            {
                "title": "Goldman Sachs Asset Management (2026), Finding the True Value of Tail-Risk Hedging",
                "url": "https://am.gs.com/en-us/advisors/insights/article/2026/finding-true-value-tail-risk-hedging",
            },
        ],
    }

    RESULTS_PATH.write_text(json.dumps(to_jsonable(results), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"experiment_id": EXPERIMENT_ID, "verdict": verdict, "results": str(RESULTS_PATH)}, indent=2))


if __name__ == "__main__":
    main()
