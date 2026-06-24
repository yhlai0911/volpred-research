"""K1547: Managed-futures ETF proxy crisis-alpha test.

Research question:
Do free managed-futures ETF proxies deliver crisis alpha in stress regimes, or
does a 12-month trend timing overlay merely add noise?

Lookahead rule:
- Momentum signal uses trailing 252 trading-day return and is shifted by one day.
- VIX stress threshold and SPY drawdown state use t-1 information.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


EXPERIMENT_ID = "K1547"
OUT_DIR = Path(__file__).resolve().parent
SEED = 1547
START = "2019-01-01"
END = None
CTA_TICKERS = ["DBMF", "KMLM", "CTA"]
BENCHMARKS = ["SPY", "AGG"]
VIX = "^VIX"
ALL_TICKERS = CTA_TICKERS + BENCHMARKS + [VIX]


@dataclass
class PerfStats:
    n: int
    start: str | None
    end: str | None
    ann_return: float | None
    ann_vol: float | None
    sharpe: float | None
    max_drawdown: float | None
    total_return: float | None
    mean_daily: float | None
    win_rate: float | None


def _safe_float(x):
    if x is None:
        return None
    if isinstance(x, (np.floating, np.integer)):
        x = float(x)
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return _safe_float(float(obj))
    return obj


def max_drawdown(returns: pd.Series) -> float | None:
    r = returns.dropna()
    if r.empty:
        return None
    equity = (1.0 + r).cumprod()
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def perf_stats(returns: pd.Series) -> PerfStats:
    r = returns.dropna()
    if r.empty:
        return PerfStats(0, None, None, None, None, None, None, None, None, None)
    n = int(r.shape[0])
    total = float((1.0 + r).prod() - 1.0)
    ann_return = float((1.0 + total) ** (252.0 / n) - 1.0) if n > 0 and total > -1 else None
    ann_vol = float(r.std(ddof=1) * np.sqrt(252.0)) if n > 1 else None
    sharpe = float(ann_return / ann_vol) if ann_return is not None and ann_vol and ann_vol > 0 else None
    return PerfStats(
        n=n,
        start=r.index.min().strftime("%Y-%m-%d"),
        end=r.index.max().strftime("%Y-%m-%d"),
        ann_return=ann_return,
        ann_vol=ann_vol,
        sharpe=sharpe,
        max_drawdown=max_drawdown(r),
        total_return=total,
        mean_daily=float(r.mean()),
        win_rate=float((r > 0).mean()),
    )


def block_bootstrap_mean_ci(x: pd.Series, *, block: int = 10, reps: int = 5000) -> dict:
    arr = x.dropna().to_numpy(dtype=float)
    n = arr.shape[0]
    if n < 10:
        return {"n": int(n), "block": block, "reps": reps, "mean": None, "ci95": [None, None], "p_mean_le_0": None}
    rng = np.random.default_rng(SEED)
    means = np.empty(reps)
    for i in range(reps):
        sample = []
        while len(sample) < n:
            start = rng.integers(0, n)
            idx = (start + np.arange(block)) % n
            sample.extend(arr[idx].tolist())
        sample_arr = np.asarray(sample[:n], dtype=float)
        means[i] = sample_arr.mean()
    return {
        "n": int(n),
        "block": int(block),
        "reps": int(reps),
        "mean": float(arr.mean()),
        "ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
        "p_mean_le_0": float((means <= 0).mean()),
    }


def paired_and_welch_tests(strategy: pd.Series, benchmark: pd.Series) -> dict:
    aligned = pd.concat({"strategy": strategy, "benchmark": benchmark}, axis=1).dropna()
    if aligned.shape[0] < 10:
        return {"n": int(aligned.shape[0]), "paired_t": None, "welch_t": None, "bootstrap": None}
    s = aligned["strategy"]
    b = aligned["benchmark"]
    diff = s - b
    paired_t = diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff))) if diff.std(ddof=1) > 0 else None
    welch_denom = np.sqrt(s.var(ddof=1) / len(s) + b.var(ddof=1) / len(b))
    welch_t = (s.mean() - b.mean()) / welch_denom if welch_denom > 0 else None
    boot = block_bootstrap_mean_ci(diff)
    return {
        "n": int(aligned.shape[0]),
        "mean_daily_excess": float(diff.mean()),
        "ann_mean_excess": float(diff.mean() * 252.0),
        "paired_t": _safe_float(float(paired_t)) if paired_t is not None else None,
        "welch_t": _safe_float(float(welch_t)) if welch_t is not None else None,
        "harvey_gate_abs_t_gt_3": bool(paired_t is not None and abs(paired_t) > 3.0),
        "bootstrap": boot,
    }


def download_close() -> pd.DataFrame:
    raw = yf.download(ALL_TICKERS, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("yfinance returned an empty frame")
    close = raw["Close"].copy()
    close = close.dropna(how="all")
    close.index = pd.to_datetime(close.index)
    missing = [ticker for ticker in ALL_TICKERS if ticker not in close.columns]
    if missing:
        raise RuntimeError(f"Missing tickers from yfinance close data: {missing}")
    close.to_csv(OUT_DIR / "k1547_data.csv", index_label="date")
    return close


def build_returns(close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = close.pct_change(fill_method=None)
    cta_rets = returns[CTA_TICKERS]
    cta_available_count = cta_rets.notna().sum(axis=1)
    # Equal weight among listed/available ETFs on that date. This is an ETF proxy
    # portfolio, not a tradable pre-launch backfill.
    returns["CTA_EW"] = cta_rets.mean(axis=1, skipna=True)
    returns.loc[cta_available_count == 0, "CTA_EW"] = np.nan

    cta_ew_valid = returns["CTA_EW"].dropna()
    trailing_valid = (1.0 + cta_ew_valid).rolling(252, min_periods=252).apply(np.prod, raw=True) - 1.0
    trailing_252 = trailing_valid.reindex(returns.index)
    signal = np.sign(trailing_valid).shift(1).reindex(returns.index)
    # Do not credit pre-history cash as crisis alpha: before a 252-day signal
    # exists, the timing strategy is undefined and excluded from tests.
    returns["CTA_TSMOM_252D"] = signal * returns["CTA_EW"]
    signal_frame = pd.DataFrame(
        {
            "cta_ew_trailing_252_return": trailing_252,
            "cta_ew_tsmom_signal_shift1": signal,
            "cta_available_count": cta_available_count,
        },
        index=returns.index,
    )
    return returns, signal_frame


def build_regimes(close: pd.DataFrame) -> pd.DataFrame:
    spy = close["SPY"]
    vix_lag = close[VIX].shift(1)
    vix_threshold = vix_lag.rolling(756, min_periods=252).quantile(0.80)
    spy_drawdown_lag = (spy / spy.cummax() - 1.0).shift(1)
    regimes = pd.DataFrame(index=close.index)
    regimes["vix_lag1"] = vix_lag
    regimes["vix_rolling_80p_lagged"] = vix_threshold
    regimes["stress_vix80_lagged"] = vix_lag >= vix_threshold
    regimes["spy_drawdown_lag1"] = spy_drawdown_lag
    regimes["stress_spy_dd10_lagged"] = spy_drawdown_lag <= -0.10
    regimes["stress_union"] = regimes["stress_vix80_lagged"] | regimes["stress_spy_dd10_lagged"]
    regimes["covid_2020"] = (regimes.index >= "2020-02-19") & (regimes.index <= "2020-03-23")
    regimes["inflation_2022"] = (regimes.index >= "2022-01-03") & (regimes.index <= "2022-10-14")
    regimes["tariff_2025"] = (regimes.index >= "2025-04-02") & (regimes.index <= "2025-04-30")
    return regimes


def summarize_regimes(returns: pd.DataFrame, regimes: pd.DataFrame) -> dict:
    strategies = ["CTA_EW", "CTA_TSMOM_252D", "DBMF", "KMLM", "CTA", "SPY", "AGG"]
    regime_defs = {
        "full_overlap": pd.Series(True, index=returns.index),
        "stress_vix80_lagged": regimes["stress_vix80_lagged"],
        "stress_spy_dd10_lagged": regimes["stress_spy_dd10_lagged"],
        "stress_union": regimes["stress_union"],
        "covid_2020": regimes["covid_2020"],
        "inflation_2022": regimes["inflation_2022"],
        "tariff_2025": regimes["tariff_2025"],
    }
    out: dict[str, dict] = {}
    for regime_name, mask in regime_defs.items():
        regime_out: dict[str, dict] = {"n_calendar_days": int(mask.sum())}
        for strategy in strategies:
            if strategy in returns.columns:
                regime_out[strategy] = asdict(perf_stats(returns.loc[mask, strategy]))
        for strategy in ["CTA_EW", "CTA_TSMOM_252D", "DBMF", "KMLM", "CTA"]:
            if strategy in returns.columns:
                regime_out[f"{strategy}_vs_SPY"] = paired_and_welch_tests(returns.loc[mask, strategy], returns.loc[mask, "SPY"])
        out[regime_name] = regime_out
    return out


def make_figures(returns: pd.DataFrame, regimes: pd.DataFrame, regime_summary: dict) -> list[str]:
    figure_paths: list[str] = []
    plot_rets = returns[["CTA_EW", "CTA_TSMOM_252D", "SPY", "AGG"]].dropna(how="all")
    cumulative = (1.0 + plot_rets.fillna(0.0)).cumprod()
    fig, ax = plt.subplots(figsize=(10, 5))
    cumulative.plot(ax=ax, linewidth=1.6)
    ax.set_title("K1547 cumulative returns: managed-futures ETF proxy vs SPY/AGG")
    ax.set_ylabel("Growth of $1")
    ax.grid(True, alpha=0.25)
    path = OUT_DIR / "fig1_cumulative_returns.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    figure_paths.append(path.name)

    excess = pd.DataFrame(
        {
            "CTA_EW_minus_SPY": returns["CTA_EW"] - returns["SPY"],
            "CTA_TSMOM_minus_SPY": returns["CTA_TSMOM_252D"] - returns["SPY"],
        }
    )
    stress_excess = excess.where(regimes["stress_union"]).dropna(how="all")
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ((1.0 + stress_excess.fillna(0.0)).cumprod() - 1.0).plot(ax=ax, linewidth=1.5)
    ax.set_title("K1547 cumulative excess return during lagged stress-union days")
    ax.set_ylabel("Cumulative excess return")
    ax.grid(True, alpha=0.25)
    path = OUT_DIR / "fig2_stress_excess.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    figure_paths.append(path.name)

    regimes_to_plot = ["full_overlap", "stress_vix80_lagged", "stress_spy_dd10_lagged", "stress_union"]
    rows = []
    for regime_name in regimes_to_plot:
        for strategy in ["CTA_EW", "CTA_TSMOM_252D"]:
            test = regime_summary[regime_name][f"{strategy}_vs_SPY"]
            rows.append(
                {
                    "regime": regime_name,
                    "strategy": strategy,
                    "ann_mean_excess": test.get("ann_mean_excess"),
                    "ci_low": None if not test.get("bootstrap") else test["bootstrap"]["ci95"][0] * 252.0,
                    "ci_high": None if not test.get("bootstrap") else test["bootstrap"]["ci95"][1] * 252.0,
                }
            )
    plot_df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    x = np.arange(len(regimes_to_plot))
    width = 0.36
    for offset, strategy in [(-width / 2, "CTA_EW"), (width / 2, "CTA_TSMOM_252D")]:
        subset = plot_df[plot_df["strategy"] == strategy].set_index("regime").loc[regimes_to_plot]
        y = subset["ann_mean_excess"].astype(float).to_numpy()
        yerr = np.vstack([y - subset["ci_low"].astype(float).to_numpy(), subset["ci_high"].astype(float).to_numpy() - y])
        ax.bar(x + offset, y, width=width, label=strategy, yerr=yerr, capsize=3)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(regimes_to_plot, rotation=18, ha="right")
    ax.set_title("K1547 annualized mean excess return vs SPY with block-bootstrap CI")
    ax.set_ylabel("Annualized mean excess return")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    path = OUT_DIR / "fig3_regime_excess_ci.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    figure_paths.append(path.name)

    crisis_rows = []
    for regime_name in ["covid_2020", "inflation_2022", "tariff_2025"]:
        for strategy in ["CTA_EW", "CTA_TSMOM_252D", "SPY", "AGG"]:
            stats = regime_summary[regime_name][strategy]
            crisis_rows.append({"regime": regime_name, "strategy": strategy, "total_return": stats["total_return"]})
    crisis_df = pd.DataFrame(crisis_rows)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    pivot = crisis_df.pivot(index="regime", columns="strategy", values="total_return").loc[
        ["covid_2020", "inflation_2022", "tariff_2025"]
    ]
    pivot.plot(kind="bar", ax=ax)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("K1547 crisis-window total returns")
    ax.set_ylabel("Total return")
    ax.set_xlabel("")
    ax.grid(True, axis="y", alpha=0.25)
    path = OUT_DIR / "fig4_crisis_windows.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    figure_paths.append(path.name)
    return figure_paths


def build_verdict(regime_summary: dict) -> dict:
    tests = {
        "CTA_EW_stress_union_vs_SPY": regime_summary["stress_union"]["CTA_EW_vs_SPY"],
        "CTA_TSMOM_stress_union_vs_SPY": regime_summary["stress_union"]["CTA_TSMOM_252D_vs_SPY"],
        "CTA_EW_full_vs_SPY": regime_summary["full_overlap"]["CTA_EW_vs_SPY"],
        "CTA_TSMOM_full_vs_SPY": regime_summary["full_overlap"]["CTA_TSMOM_252D_vs_SPY"],
    }
    stress = tests["CTA_EW_stress_union_vs_SPY"]
    tsmom_stress = tests["CTA_TSMOM_stress_union_vs_SPY"]
    stress_pass = bool(
        stress.get("paired_t") is not None
        and stress["paired_t"] > 3.0
        and stress.get("bootstrap")
        and stress["bootstrap"]["ci95"][0] > 0
    )
    tsmom_pass = bool(
        tsmom_stress.get("paired_t") is not None
        and tsmom_stress["paired_t"] > 3.0
        and tsmom_stress.get("bootstrap")
        and tsmom_stress["bootstrap"]["ci95"][0] > 0
    )
    if stress_pass and tsmom_pass:
        label = "SUPPORTED_ETF_PROXY_AND_TSMOM_STRESS_ALPHA"
    elif stress_pass and not tsmom_pass:
        label = "SUPPORTED_LONG_ONLY_ETF_PROXY_NOT_TSMOM_TIMING"
    elif stress.get("ann_mean_excess") and stress["ann_mean_excess"] > 0:
        label = "WEAK_POSITIVE_STRESS_ALPHA_NO_HARVEY_PASS"
    else:
        label = "NULL_OR_NEGATIVE_STRESS_ALPHA_FOR_FREE_ETF_PROXY"
    return {
        "label": label,
        "stress_long_only_pass_harvey_and_bootstrap": stress_pass,
        "stress_tsmom_pass_harvey_and_bootstrap": tsmom_pass,
        "decision_rule": "Pass requires paired excess-return t > 3 and block-bootstrap 95% CI lower bound > 0 in stress_union.",
        "key_tests": tests,
    }


def main() -> None:
    close = download_close()
    returns, signals = build_returns(close)
    regimes = build_regimes(close)
    regime_summary = summarize_regimes(returns, regimes)
    figures = make_figures(returns, regimes, regime_summary)
    verdict = build_verdict(regime_summary)

    valid = pd.concat(
        {
            "CTA_EW": returns["CTA_EW"],
            "CTA_TSMOM_252D": returns["CTA_TSMOM_252D"],
            "SPY": returns["SPY"],
            "AGG": returns["AGG"],
            "stress_union": regimes["stress_union"],
        },
        axis=1,
    )
    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Managed-futures ETF proxy crisis-alpha test",
        "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "data_source": "yfinance adjusted close",
        "tickers": {"managed_futures": CTA_TICKERS, "benchmarks": BENCHMARKS, "stress": [VIX]},
        "data_period": {
            "start": close.index.min().strftime("%Y-%m-%d"),
            "end": close.index.max().strftime("%Y-%m-%d"),
            "n_price_rows": int(close.shape[0]),
        },
        "methodology": {
            "cta_proxy": "Equal-weight daily return across listed/available DBMF, KMLM, CTA. No pre-launch backfill.",
            "tsmom_signal": "sign trailing 252 trading-day CTA_EW return, shifted by one day; undefined before signal availability and excluded from tests.",
            "stress_vix": "VIX prior close >= rolling 756-trading-day 80th percentile computed on prior closes, min 252 observations.",
            "stress_drawdown": "SPY drawdown computed from prior close <= -10%.",
            "lookahead_policy": [
                "cta_ew_tsmom_signal_shift1 explicitly uses .shift(1)",
                "VIX and SPY drawdown stress states use lagged close information",
                "No same-day signal multiplied by same-day return",
            ],
            "bootstrap": {"seed": SEED, "reps": 5000, "block_length": 10},
            "harvey_gate": "abs paired excess-return t-stat > 3; positive alpha pass also requires t > 3 and bootstrap CI lower > 0.",
        },
        "sample_diagnostics": {
            "first_valid_return": {col: returns[col].first_valid_index().strftime("%Y-%m-%d") for col in ["DBMF", "KMLM", "CTA", "CTA_EW", "CTA_TSMOM_252D"] if returns[col].first_valid_index() is not None},
            "last_valid_return": {col: returns[col].last_valid_index().strftime("%Y-%m-%d") for col in ["DBMF", "KMLM", "CTA", "CTA_EW", "CTA_TSMOM_252D"] if returns[col].last_valid_index() is not None},
            "stress_union_days_with_cta": int(valid.dropna(subset=["CTA_EW"])["stress_union"].sum()),
            "stress_union_days_with_tsmom": int(valid.dropna(subset=["CTA_TSMOM_252D"])["stress_union"].sum()),
            "cta_available_count_distribution": signals["cta_available_count"].value_counts().sort_index().to_dict(),
        },
        "regime_summary": regime_summary,
        "verdict": verdict,
        "figures": figures,
        "references": [
            "Moskowitz, Ooi, and Pedersen (2012), Time Series Momentum, Journal of Financial Economics.",
            "Hurst, Ooi, and Pedersen (2017), A Century of Evidence on Trend-Following Investing, Journal of Portfolio Management.",
            "Greyserman and Kaminski (2014), Trend Following with Managed Futures: The Search for Crisis Alpha.",
            "Kaminski (2011), In Search of Crisis Alpha: A Short Guide to Investing in Managed Futures.",
        ],
        "limitations": [
            "ETF proxy sample is short and begins after the main 2020 Covid selloff for 252-day timing purposes.",
            "DBMF/KMLM/CTA are investable managed-futures products, not the diversified futures universe in Moskowitz-Ooi-Pedersen.",
            "Equal weighting among available ETFs can overweight single-fund periods before all products are listed.",
            "Stress-regime tests are descriptive OOS-style diagnostics, not a production strategy listing gate.",
        ],
    }
    (OUT_DIR / "k1547_results.json").write_text(json.dumps(to_jsonable(results), indent=2, ensure_ascii=False))
    print(json.dumps(to_jsonable({"verdict": verdict["label"], "data_period": results["data_period"], "figures": figures}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
