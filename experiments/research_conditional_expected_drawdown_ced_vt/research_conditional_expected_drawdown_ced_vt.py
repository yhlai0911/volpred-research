#!/usr/bin/env python3
"""Conditional Expected Drawdown target vs realized-vol target.

This is a cross-asset robustness check for the drawdown-aware risk-target
family. It differs from K1494 by using an equity-only SPY/QQQ/IWM basket and
fixed-horizon 20d/60d CED signals computed from adjusted OHLC data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


SEED = 42
TICKERS = ["SPY", "QQQ", "IWM"]
START = "2003-01-01"
END = "2026-06-14"
ANALYSIS_START = pd.Timestamp("2005-01-03")
IS_END = pd.Timestamp("2017-12-29")
OOS_START = pd.Timestamp("2018-01-02")

TRADING_DAYS = 252
TARGET_VOL = 0.12
VOL_WINDOW = 63
CED_LOOKBACK = 252
CED_ALPHA = 0.95
CED_HORIZONS = [20, 60]
MAX_EXPOSURE = 1.50
TX_COST_ONE_WAY = 0.0005
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "research_conditional_expected_drawdown_ced_vt_results.json"
FIG_EQUITY = HERE / "fig_equity_curves.png"
FIG_EXPOSURE = HERE / "fig_exposures_and_risk_signals.png"


@dataclass(frozen=True)
class Metrics:
    n_days: int
    start: str
    end: str
    cagr: float
    ann_return: float
    ann_vol: float
    sharpe: float
    mdd: float
    calmar: float
    cdar95: float
    left_tail_days_2pct: int
    left_tail_freq_2pct: float
    cvar5_daily: float
    mean_exposure: float | None = None
    turnover_ann: float | None = None


def download_ohlc() -> dict[str, pd.DataFrame]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    if not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("Expected MultiIndex OHLC columns for multiple tickers")

    out: dict[str, pd.DataFrame] = {}
    for field in ["Open", "High", "Low", "Close"]:
        frame = raw[field].copy()[TICKERS].dropna(how="any")
        frame.index = pd.to_datetime(frame.index)
        out[field.lower()] = frame
        frame.to_csv(DATA_DIR / f"{field.lower()}.csv")
    return out


def max_drawdown(returns: pd.Series) -> float:
    r = returns.dropna()
    wealth = np.r_[1.0, (1.0 + r.to_numpy()).cumprod()]
    peak = np.maximum.accumulate(wealth)
    drawdown = wealth / peak - 1.0
    return float(drawdown.min())


def cdar_from_returns(returns: pd.Series, alpha: float = CED_ALPHA) -> float:
    r = returns.dropna()
    wealth = (1.0 + r).cumprod()
    drawdown = 1.0 - wealth / wealth.cummax()
    if drawdown.empty:
        return 0.0
    tail_count = max(1, int(np.ceil((1.0 - alpha) * len(drawdown))))
    return float(np.sort(drawdown.to_numpy())[-tail_count:].mean())


def horizon_path_drawdown(close_returns: np.ndarray, low_returns: np.ndarray) -> float:
    wealth = 1.0
    peak = 1.0
    worst = 0.0
    for close_r, low_r in zip(close_returns, low_returns):
        low_wealth = wealth * (1.0 + low_r)
        worst = min(worst, low_wealth / peak - 1.0)
        wealth *= 1.0 + close_r
        peak = max(peak, wealth)
        worst = min(worst, wealth / peak - 1.0)
    return float(-worst)


def rolling_horizon_ced(
    close_returns: pd.Series,
    low_returns: pd.Series,
    horizon: int,
    lookback: int = CED_LOOKBACK,
    alpha: float = CED_ALPHA,
) -> pd.Series:
    aligned = pd.concat([close_returns.rename("close"), low_returns.rename("low")], axis=1).dropna()
    close = aligned["close"].to_numpy(dtype=float)
    low = aligned["low"].to_numpy(dtype=float)
    out = np.full(len(aligned), np.nan, dtype=float)
    tail_frac = 1.0 - alpha

    for i in range(lookback - 1, len(aligned)):
        start = i - lookback + 1
        drawdowns = []
        for j in range(start, i - horizon + 2):
            drawdowns.append(horizon_path_drawdown(close[j : j + horizon], low[j : j + horizon]))
        if drawdowns:
            arr = np.sort(np.asarray(drawdowns, dtype=float))
            tail_count = max(1, int(np.ceil(tail_frac * len(arr))))
            out[i] = float(arr[-tail_count:].mean())
    return pd.Series(out, index=aligned.index, name=f"ced{horizon}_252")


def compute_metrics(returns: pd.Series, exposure: pd.Series | None = None) -> Metrics:
    r = returns.dropna()
    n = len(r)
    years = n / TRADING_DAYS
    wealth = (1.0 + r).cumprod()
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if n > 1 else 0.0
    ann_return = float(r.mean() * TRADING_DAYS)
    ann_vol = float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0
    mdd = max_drawdown(r)
    cdar95 = cdar_from_returns(r)
    cvar5 = float(r[r <= r.quantile(0.05)].mean())
    left_tail = int((r <= -0.02).sum())

    mean_exposure = None
    turnover_ann = None
    if exposure is not None:
        e = exposure.reindex(r.index).dropna()
        mean_exposure = float(e.mean())
        turnover_ann = float(e.diff().abs().fillna(0.0).mean() * TRADING_DAYS)

    def label_index(value) -> str:
        return str(value.date()) if hasattr(value, "date") else str(value)

    return Metrics(
        n_days=int(n),
        start=label_index(r.index[0]),
        end=label_index(r.index[-1]),
        cagr=cagr,
        ann_return=ann_return,
        ann_vol=ann_vol,
        sharpe=sharpe,
        mdd=mdd,
        calmar=cagr / abs(mdd) if mdd < 0 else 0.0,
        cdar95=cdar95,
        left_tail_days_2pct=left_tail,
        left_tail_freq_2pct=left_tail / n if n else 0.0,
        cvar5_daily=cvar5,
        mean_exposure=mean_exposure,
        turnover_ann=turnover_ann,
    )


def json_metrics(metrics: Metrics) -> dict:
    d = asdict(metrics)
    for key in ["cagr", "ann_return", "ann_vol", "mdd", "cdar95", "left_tail_freq_2pct", "cvar5_daily"]:
        d[f"{key}_pct"] = round(float(d.pop(key)) * 100, 4)
    d["sharpe"] = round(float(d["sharpe"]), 4)
    d["calmar"] = round(float(d["calmar"]), 4)
    if d["mean_exposure"] is not None:
        d["mean_exposure"] = round(float(d["mean_exposure"]), 4)
    if d["turnover_ann"] is not None:
        d["turnover_ann"] = round(float(d["turnover_ann"]), 4)
    return d


def calibrate_target(risk_signal_raw: pd.Series, baseline_exposure_raw: pd.Series) -> dict:
    is_idx = risk_signal_raw.index[(risk_signal_raw.index >= ANALYSIS_START) & (risk_signal_raw.index <= IS_END)]
    target_mean = float(baseline_exposure_raw.reindex(is_idx).dropna().mean())
    candidates = np.linspace(0.01, 0.35, 341)
    best = {"target": None, "mean_exposure": None, "gap": float("inf")}
    for target in candidates:
        exposure = (target / risk_signal_raw.reindex(is_idx)).clip(lower=0.0, upper=MAX_EXPOSURE).dropna()
        if exposure.empty:
            continue
        mean_exposure = float(exposure.mean())
        gap = abs(mean_exposure - target_mean)
        if gap < best["gap"]:
            best = {"target": float(target), "mean_exposure": mean_exposure, "gap": float(gap)}
    return {
        "target_ced": best["target"],
        "ced_is_mean_exposure": best["mean_exposure"],
        "vol_target_is_mean_exposure": target_mean,
        "absolute_gap": best["gap"],
        "calibration_period": [str(ANALYSIS_START.date()), str(IS_END.date())],
    }


def strategy_returns(base_ret: pd.Series, exposure: pd.Series) -> pd.Series:
    aligned = pd.concat([base_ret.rename("base"), exposure.rename("exposure")], axis=1).dropna()
    cost = aligned["exposure"].diff().abs().fillna(0.0) * TX_COST_ONE_WAY
    out = aligned["exposure"] * aligned["base"] - cost
    out.name = exposure.name or "strategy"
    return out


def moving_block_bootstrap_diff(baseline: pd.Series, challenger: pd.Series, label: str) -> dict:
    paired = pd.concat([baseline.rename("base"), challenger.rename("challenger")], axis=1).dropna()
    arr = paired.to_numpy()
    n = len(arr)
    rng = np.random.default_rng(SEED)

    def sample_once() -> np.ndarray:
        chosen: list[int] = []
        while len(chosen) < n:
            start = int(rng.integers(0, n - BOOTSTRAP_BLOCK + 1))
            chosen.extend(range(start, start + BOOTSTRAP_BLOCK))
        return arr[np.asarray(chosen[:n])]

    rows = []
    for _ in range(BOOTSTRAP_REPS):
        sample = sample_once()
        base = compute_metrics(pd.Series(sample[:, 0]))
        challenger_m = compute_metrics(pd.Series(sample[:, 1]))
        rows.append(
            {
                f"sharpe_diff_{label}_minus_vol": challenger_m.sharpe - base.sharpe,
                f"mdd_diff_pp_{label}_minus_vol": (challenger_m.mdd - base.mdd) * 100.0,
                f"calmar_diff_{label}_minus_vol": challenger_m.calmar - base.calmar,
                f"cagr_diff_pp_{label}_minus_vol": (challenger_m.cagr - base.cagr) * 100.0,
                f"left_tail_freq_diff_{label}_minus_vol": challenger_m.left_tail_freq_2pct - base.left_tail_freq_2pct,
            }
        )

    df = pd.DataFrame(rows)
    out = {}
    for col in df.columns:
        vals = df[col].to_numpy()
        out[col] = {
            "mean": round(float(vals.mean()), 6),
            "ci_2p5": round(float(np.quantile(vals, 0.025)), 6),
            "ci_97p5": round(float(np.quantile(vals, 0.975)), 6),
            "p_gt_0": round(float((vals > 0).mean()), 4),
        }
    return out


def build_figures(strategy_ret: pd.DataFrame, exposures: pd.DataFrame, risk: pd.DataFrame) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    wealth = (1.0 + strategy_ret).cumprod()

    fig, ax = plt.subplots(figsize=(11, 6))
    for col, color in [
        ("buy_hold", "#555555"),
        ("vol_target", "#1f77b4"),
        ("ced20_target", "#d1495b"),
        ("ced60_target", "#2ca02c"),
    ]:
        ax.plot(wealth.index, wealth[col], label=col, linewidth=1.8, color=color)
    ax.set_title("CED Target vs Realized-Vol Target: SPY/QQQ/IWM Basket")
    ax.set_ylabel("Growth of $1")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_EQUITY, dpi=180)
    plt.close(fig)

    recent = exposures.loc[exposures.index >= "2018-01-01"]
    risk_recent = risk.reindex(recent.index)
    fig2, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for col, color in [("vol_target", "#1f77b4"), ("ced20_target", "#d1495b"), ("ced60_target", "#2ca02c")]:
        ax1.plot(recent.index, recent[col], label=col, color=color, linewidth=1.0)
    ax1.set_ylabel("Lagged exposure")
    ax1.legend(frameon=False, ncol=3)
    ax2.plot(risk_recent.index, risk_recent["ann_vol_63"], label="63d annualized vol", color="#1f77b4")
    ax2.plot(risk_recent.index, risk_recent["ced20_252"], label="CED20 252d", color="#d1495b")
    ax2.plot(risk_recent.index, risk_recent["ced60_252"], label="CED60 252d", color="#2ca02c")
    ax2.set_ylabel("Risk estimate")
    ax2.legend(frameon=False, ncol=3)
    fig2.suptitle("Lagged Exposure and Risk Signals")
    fig2.tight_layout()
    fig2.savefig(FIG_EXPOSURE, dpi=180)
    plt.close(fig2)


def main() -> None:
    np.random.seed(SEED)
    ohlc = download_ohlc()
    close = ohlc["close"]
    low = ohlc["low"]
    close_ret = close.pct_change().dropna()
    low_ret = (low / close.shift(1) - 1.0).dropna()

    base_close_ret = close_ret.mean(axis=1).rename("base_equal_weight_close_ret")
    base_low_ret = low_ret.reindex(base_close_ret.index).mean(axis=1).rename("base_equal_weight_low_ret")
    base_close_ret = base_close_ret[base_close_ret.index >= ANALYSIS_START]
    base_low_ret = base_low_ret.reindex(base_close_ret.index)

    ann_vol_63 = (base_close_ret.rolling(VOL_WINDOW).std(ddof=1) * np.sqrt(TRADING_DAYS)).rename("ann_vol_63")
    vol_exposure_raw = (TARGET_VOL / ann_vol_63).clip(lower=0.0, upper=MAX_EXPOSURE)
    vol_exposure = vol_exposure_raw.shift(1).rename("vol_target")

    ced_signals = {}
    ced_exposures = {}
    calibrations = {}
    for horizon in CED_HORIZONS:
        signal = rolling_horizon_ced(base_close_ret, base_low_ret, horizon=horizon).rename(f"ced{horizon}_252")
        calibration = calibrate_target(signal, vol_exposure_raw)
        exposure_raw = (calibration["target_ced"] / signal).clip(lower=0.0, upper=MAX_EXPOSURE)
        exposure = exposure_raw.shift(1).rename(f"ced{horizon}_target")
        ced_signals[horizon] = signal
        ced_exposures[horizon] = exposure
        calibrations[horizon] = calibration

    buy_hold_exposure = pd.Series(1.0, index=base_close_ret.index, name="buy_hold")
    strategy_ret = pd.concat(
        [
            strategy_returns(base_close_ret, buy_hold_exposure).rename("buy_hold"),
            strategy_returns(base_close_ret, vol_exposure).rename("vol_target"),
            strategy_returns(base_close_ret, ced_exposures[20]).rename("ced20_target"),
            strategy_returns(base_close_ret, ced_exposures[60]).rename("ced60_target"),
        ],
        axis=1,
    ).dropna()

    exposures = pd.concat([buy_hold_exposure, vol_exposure, ced_exposures[20], ced_exposures[60]], axis=1).reindex(
        strategy_ret.index
    )
    risk = pd.concat([ann_vol_63, ced_signals[20], ced_signals[60]], axis=1).reindex(strategy_ret.index)

    oos_ret = strategy_ret[strategy_ret.index >= OOS_START]
    oos_exp = exposures.reindex(oos_ret.index)
    full_metrics = {col: json_metrics(compute_metrics(strategy_ret[col], exposures[col])) for col in strategy_ret.columns}
    oos_metrics = {col: json_metrics(compute_metrics(oos_ret[col], oos_exp[col])) for col in oos_ret.columns}

    bootstrap = {
        "ced20_target_vs_vol_target": moving_block_bootstrap_diff(oos_ret["vol_target"], oos_ret["ced20_target"], "ced20"),
        "ced60_target_vs_vol_target": moving_block_bootstrap_diff(oos_ret["vol_target"], oos_ret["ced60_target"], "ced60"),
    }

    build_figures(strategy_ret, exposures, risk)

    verdict = "NULL"
    winners = []
    for label in ["ced20", "ced60"]:
        b = bootstrap[f"{label}_target_vs_vol_target"]
        mdd = b[f"mdd_diff_pp_{label}_minus_vol"]
        calmar = b[f"calmar_diff_{label}_minus_vol"]
        sharpe = b[f"sharpe_diff_{label}_minus_vol"]
        left_tail = b[f"left_tail_freq_diff_{label}_minus_vol"]
        if mdd["ci_2p5"] > 0 and calmar["ci_2p5"] > 0 and sharpe["ci_2p5"] > -0.05 and left_tail["ci_97p5"] <= 0:
            winners.append(label)
    if winners:
        verdict = "CED_IMPROVES_DRAWDOWN"

    results = {
        "experiment_id": "research_conditional_expected_drawdown_ced_vt",
        "title": "Conditional Expected Drawdown risk target vs realized-vol target on SPY/QQQ/IWM",
        "date_run": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "source": "yfinance adjusted OHLC; auto_adjust=True",
            "tickers": TICKERS,
            "download_start": START,
            "download_end": END,
            "analysis_start": str(strategy_ret.index[0].date()),
            "analysis_end": str(strategy_ret.index[-1].date()),
            "oos_start": str(OOS_START.date()),
            "n_days_analysis": int(len(strategy_ret)),
            "n_days_oos": int(len(oos_ret)),
            "cached_ohlc_dir": "experiments/research_conditional_expected_drawdown_ced_vt/data/",
        },
        "method": {
            "base_portfolio": "equal-weight daily close returns of SPY/QQQ/IWM",
            "ohlc_usage": "daily adjusted Low versus previous adjusted Close is used inside each horizon drawdown path",
            "vol_target": {
                "target_ann_vol": TARGET_VOL,
                "lookback_days": VOL_WINDOW,
                "exposure_rule": "TARGET_VOL / ann_vol_63, clipped [0,1.5], then shift(1)",
            },
            "ced_target": {
                "lookback_days": CED_LOOKBACK,
                "horizons": CED_HORIZONS,
                "alpha": CED_ALPHA,
                "rule": "target_ced / trailing fixed-horizon CED, clipped [0,1.5], then shift(1)",
                "calibrations": {f"ced{h}": calibrations[h] for h in CED_HORIZONS},
            },
            "transaction_cost_one_way": TX_COST_ONE_WAY,
            "bootstrap": {"reps": BOOTSTRAP_REPS, "block_length": BOOTSTRAP_BLOCK, "seed": SEED},
            "lookahead_protection": [
                "vol_exposure = vol_exposure_raw.shift(1)",
                "ced20/ced60 exposures are shifted by one trading day",
                "CED signals use only trailing 252 trading days ending at t before shift",
            ],
        },
        "metrics_full": full_metrics,
        "metrics_oos": oos_metrics,
        "formal_tests": {"paired_moving_block_bootstrap_oos": bootstrap},
        "figures": [FIG_EQUITY.name, FIG_EXPOSURE.name],
        "related_knowledge": [
            "K1494: CDaR scaler did not beat realized-vol targeting on SPY/TLT/GLD/DBC.",
            "K1334: CVaR target did not reliably improve on realized-vol targeting.",
        ],
        "literature": [
            {
                "citation": "Chekhlov, Uryasev, Zabarankin (2005), Drawdown Measure in Portfolio Optimization",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=544742",
            },
            {
                "citation": "Chekhlov, Uryasev, Zabarankin (2003), Portfolio Optimization with Drawdown Constraints",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=223323",
            },
            {
                "citation": "PyPortfolioOpt EfficientCDaR documentation",
                "url": "https://pyportfolioopt.readthedocs.io/en/latest/GeneralEfficientFrontier.html",
            },
            {
                "citation": "scikit-portfolio Efficient Conditional Drawdown at Risk documentation",
                "url": "https://scikit-portfolio.github.io/scikit-portfolio/efficient_cdar/",
            },
        ],
        "research_honesty_notes": [
            "CED is backward-looking and path-dependent; it should not be described as anticipating fast crashes unless the OOS evidence supports that.",
            "This is an equity-only robustness check, not an investable strategy launch gate.",
            "All exposure signals are explicitly shifted by one trading day before returns are applied.",
        ],
        "verdict": {
            "overall": verdict,
            "winning_ced_variants": winners,
            "plain_english": (
                "Fixed-horizon CED targeting improves the pre-specified drawdown/Calmar/left-tail bootstrap gate."
                if winners
                else "Fixed-horizon CED targeting does not pass the pre-specified gate versus 63d realized-vol targeting."
            ),
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results["verdict"], indent=2, ensure_ascii=False))
    print(json.dumps(results["metrics_oos"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
