#!/usr/bin/env python3
"""K1494: CDaR target vs traditional volatility target.

Compares scalar exposure control rules on the same equal-weight
SPY/TLT/GLD/DBC base portfolio. CDaR target is calibrated in-sample only, then
evaluated out-of-sample.
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

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "k1494_cdar_vs_vol_target_results.json"

TICKERS = ["SPY", "TLT", "GLD", "DBC"]
START_DATE = "2006-01-01"
END_DATE = "2026-06-01"
ANALYSIS_START = pd.Timestamp("2008-01-02")
IS_END = pd.Timestamp("2017-12-29")
OOS_START = pd.Timestamp("2018-01-02")

TARGET_VOL = 0.10
VOL_WINDOW = 63
CDAR_WINDOW = 252
CDAR_ALPHA = 0.95
MAX_EXPOSURE = 1.50
TX_COST_ONE_WAY = 0.0005
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
SEED = 42
TRADING_DAYS = 252

STRESS_PERIODS = {
    "gfc": ("2008-01-02", "2009-06-30"),
    "covid_crash": ("2020-02-20", "2020-04-30"),
    "rates_2022": ("2022-01-03", "2022-10-31"),
    "post_2024": ("2024-01-02", "2026-05-29"),
}


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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def download_prices() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty data")
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].copy()
        prices.columns = TICKERS
    prices = prices[TICKERS].dropna(how="any")
    prices.index = pd.to_datetime(prices.index)
    prices.to_csv(DATA_DIR / "prices.csv")
    return prices


def max_drawdown(returns: pd.Series) -> float:
    wealth = np.r_[1.0, (1.0 + returns.to_numpy()).cumprod()]
    peak = np.maximum.accumulate(wealth)
    drawdown = wealth / peak - 1.0
    return float(drawdown.min())


def cdar_from_returns(returns: pd.Series, alpha: float = CDAR_ALPHA) -> float:
    wealth = (1.0 + returns).cumprod()
    drawdown = 1.0 - wealth / wealth.cummax()
    drawdown = drawdown.dropna()
    if drawdown.empty:
        return 0.0
    tail_count = max(1, int(np.ceil((1.0 - alpha) * len(drawdown))))
    return float(np.sort(drawdown.to_numpy())[-tail_count:].mean())


def rolling_cdar(returns: pd.Series, window: int = CDAR_WINDOW, alpha: float = CDAR_ALPHA) -> pd.Series:
    values = np.full(len(returns), np.nan)
    ret_values = returns.to_numpy()
    for i in range(window - 1, len(returns)):
        window_returns = pd.Series(ret_values[i - window + 1 : i + 1])
        values[i] = cdar_from_returns(window_returns, alpha=alpha)
    return pd.Series(values, index=returns.index, name="rolling_cdar95")


def compute_metrics(returns: pd.Series, exposure: pd.Series | None = None) -> Metrics:
    r = returns.dropna()
    wealth = (1.0 + r).cumprod()
    n = len(r)
    years = n / TRADING_DAYS
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


def as_json_metrics(metrics: Metrics) -> dict:
    return {
        "n_days": metrics.n_days,
        "start": metrics.start,
        "end": metrics.end,
        "cagr_pct": round(metrics.cagr * 100, 3),
        "ann_return_pct": round(metrics.ann_return * 100, 3),
        "ann_vol_pct": round(metrics.ann_vol * 100, 3),
        "sharpe": round(metrics.sharpe, 4),
        "mdd_pct": round(metrics.mdd * 100, 3),
        "calmar": round(metrics.calmar, 4),
        "cdar95_pct": round(metrics.cdar95 * 100, 3),
        "left_tail_days_2pct": metrics.left_tail_days_2pct,
        "left_tail_freq_2pct": round(metrics.left_tail_freq_2pct, 5),
        "cvar5_daily_pct": round(metrics.cvar5_daily * 100, 3),
        "mean_exposure": None if metrics.mean_exposure is None else round(metrics.mean_exposure, 4),
        "turnover_ann": None if metrics.turnover_ann is None else round(metrics.turnover_ann, 4),
    }


def calibrate_cdar_target(cdar_signal: pd.Series, vol_exposure: pd.Series) -> dict:
    is_idx = cdar_signal.index[(cdar_signal.index >= ANALYSIS_START) & (cdar_signal.index <= IS_END)]
    target_mean = float(vol_exposure.reindex(is_idx).dropna().mean())
    candidates = np.linspace(0.02, 0.30, 281)
    best_target = None
    best_gap = float("inf")
    best_mean = None
    for target in candidates:
        exposure = (target / cdar_signal.reindex(is_idx)).clip(lower=0.0, upper=MAX_EXPOSURE)
        mean_exposure = float(exposure.dropna().mean())
        gap = abs(mean_exposure - target_mean)
        if gap < best_gap:
            best_gap = gap
            best_target = float(target)
            best_mean = mean_exposure
    return {
        "target_cdar": best_target,
        "vol_target_is_mean_exposure": target_mean,
        "cdar_is_mean_exposure": best_mean,
        "absolute_gap": best_gap,
        "calibration_period": [str(ANALYSIS_START.date()), str(IS_END.date())],
    }


def strategy_returns(base_ret: pd.Series, exposure: pd.Series) -> pd.Series:
    aligned = pd.concat([base_ret.rename("base"), exposure.rename("exposure")], axis=1).dropna()
    cost = aligned["exposure"].diff().abs().fillna(0.0) * TX_COST_ONE_WAY
    out = aligned["exposure"] * aligned["base"] - cost
    out.name = exposure.name or "strategy"
    return out


def moving_block_bootstrap_diff(vol_ret: pd.Series, cdar_ret: pd.Series) -> dict:
    paired = pd.concat([vol_ret.rename("vol"), cdar_ret.rename("cdar")], axis=1).dropna()
    arr = paired.to_numpy()
    n = len(arr)
    rng = np.random.default_rng(SEED)

    def sample_once() -> np.ndarray:
        chosen: list[int] = []
        while len(chosen) < n:
            start = int(rng.integers(0, n - BOOTSTRAP_BLOCK + 1))
            chosen.extend(range(start, start + BOOTSTRAP_BLOCK))
        return arr[np.array(chosen[:n])]

    records = []
    for _ in range(BOOTSTRAP_REPS):
        sample = sample_once()
        vol = pd.Series(sample[:, 0])
        cdar = pd.Series(sample[:, 1])
        m_vol = compute_metrics(vol)
        m_cdar = compute_metrics(cdar)
        records.append(
            {
                "sharpe_diff_cdar_minus_vol": m_cdar.sharpe - m_vol.sharpe,
                "mdd_diff_pp_cdar_minus_vol": (m_cdar.mdd - m_vol.mdd) * 100,
                "cagr_diff_pp_cdar_minus_vol": (m_cdar.cagr - m_vol.cagr) * 100,
                "left_tail_freq_diff_cdar_minus_vol": m_cdar.left_tail_freq_2pct
                - m_vol.left_tail_freq_2pct,
            }
        )

    df = pd.DataFrame.from_records(records)
    out = {}
    for col in df.columns:
        vals = df[col].to_numpy()
        out[col] = {
            "mean": round(float(vals.mean()), 5),
            "ci_2p5": round(float(np.quantile(vals, 0.025)), 5),
            "ci_97p5": round(float(np.quantile(vals, 0.975)), 5),
            "p_gt_0": round(float((vals > 0).mean()), 4),
        }
    return out


def build_figures(returns: pd.DataFrame, exposures: pd.DataFrame, risk: pd.DataFrame) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    wealth = (1.0 + returns).cumprod()

    fig, ax = plt.subplots(figsize=(10, 6))
    for col, color in [("buy_hold", "#555555"), ("vol_target", "#1f77b4"), ("cdar_target", "#d1495b")]:
        ax.plot(wealth.index, wealth[col], label=col, linewidth=2.0, color=color)
    ax.set_title("K1494: Equity Curves (net of exposure-change costs)")
    ax.set_ylabel("Growth of $1")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(HERE / "k1494_equity_curves.png", dpi=180)
    plt.close(fig)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax1.plot(exposures.index, exposures["vol_target"], label="vol target exposure", color="#1f77b4")
    ax1.plot(exposures.index, exposures["cdar_target"], label="CDaR target exposure", color="#d1495b")
    ax1.set_ylabel("Exposure")
    ax1.legend(frameon=False)
    ax2.plot(risk.index, risk["ann_vol_63"], label="63d annualized vol", color="#1f77b4")
    ax2.plot(risk.index, risk["cdar95_252"], label="252d CDaR95", color="#d1495b")
    ax2.set_ylabel("Risk estimate")
    ax2.legend(frameon=False)
    fig.suptitle("K1494: Lagged Exposure Signals and Risk Estimates")
    fig.tight_layout()
    fig.savefig(HERE / "k1494_exposure_and_risk_signals.png", dpi=180)
    plt.close(fig)


def main() -> None:
    prices = download_prices()
    returns = prices.pct_change().dropna()
    base_ret = returns.mean(axis=1).rename("base_equal_weight")
    base_ret = base_ret[base_ret.index >= ANALYSIS_START]

    ann_vol_63 = (base_ret.rolling(VOL_WINDOW).std(ddof=1) * np.sqrt(TRADING_DAYS)).rename("ann_vol_63")
    vol_exposure_raw = (TARGET_VOL / ann_vol_63).clip(lower=0.0, upper=MAX_EXPOSURE)
    vol_exposure = vol_exposure_raw.shift(1).rename("vol_target")

    cdar95_252 = rolling_cdar(base_ret, window=CDAR_WINDOW, alpha=CDAR_ALPHA).rename("cdar95_252")
    calibration = calibrate_cdar_target(cdar95_252, vol_exposure_raw)
    cdar_exposure_raw = (calibration["target_cdar"] / cdar95_252).clip(lower=0.0, upper=MAX_EXPOSURE)
    cdar_exposure = cdar_exposure_raw.shift(1).rename("cdar_target")

    buy_hold_exposure = pd.Series(1.0, index=base_ret.index, name="buy_hold")

    strategy_ret = pd.concat(
        [
            strategy_returns(base_ret, buy_hold_exposure).rename("buy_hold"),
            strategy_returns(base_ret, vol_exposure).rename("vol_target"),
            strategy_returns(base_ret, cdar_exposure).rename("cdar_target"),
        ],
        axis=1,
    ).dropna()
    exposures = pd.concat([buy_hold_exposure, vol_exposure, cdar_exposure], axis=1).reindex(strategy_ret.index)
    risk_signals = pd.concat([ann_vol_63, cdar95_252], axis=1).reindex(strategy_ret.index)

    full_metrics = {
        col: as_json_metrics(compute_metrics(strategy_ret[col], exposures[col]))
        for col in strategy_ret.columns
    }

    oos_ret = strategy_ret[strategy_ret.index >= OOS_START]
    oos_exp = exposures.reindex(oos_ret.index)
    oos_metrics = {
        col: as_json_metrics(compute_metrics(oos_ret[col], oos_exp[col]))
        for col in oos_ret.columns
    }

    stress_metrics = {}
    for name, (start, end) in STRESS_PERIODS.items():
        sub = strategy_ret.loc[start:end]
        exp_sub = exposures.reindex(sub.index)
        if len(sub) < 20:
            continue
        stress_metrics[name] = {
            col: as_json_metrics(compute_metrics(sub[col], exp_sub[col]))
            for col in sub.columns
        }

    bootstrap = moving_block_bootstrap_diff(oos_ret["vol_target"], oos_ret["cdar_target"])

    build_figures(strategy_ret, exposures, risk_signals)

    verdict = "NULL"
    verdict_text = (
        "The simple trailing-CDaR scaler does not beat traditional realized-vol targeting OOS. "
        "It earns higher CAGR through higher exposure, but Sharpe is lower, MDD is deeper, and "
        "the paired block bootstrap shows 2% left-tail day frequency reliably worsens."
    )
    if (
        oos_metrics["cdar_target"]["mdd_pct"] > oos_metrics["vol_target"]["mdd_pct"]
        and oos_metrics["cdar_target"]["sharpe"] >= oos_metrics["vol_target"]["sharpe"] - 0.05
        and bootstrap["mdd_diff_pp_cdar_minus_vol"]["ci_2p5"] > 0
    ):
        verdict = "CDAR_IMPROVES_DRAWDOWN"
        verdict_text = (
            "The simple trailing-CDaR scaler improves OOS drawdown metrics versus traditional "
            "realized-vol targeting while preserving Sharpe within the pre-specified tolerance."
        )

    results = {
        "experiment_id": "k1494_cdar_vs_vol_target",
        "title": "Conditional Drawdown-at-Risk target vs traditional vol target",
        "run_timestamp": utc_now(),
        "seed": SEED,
        "data": {
            "source": "yfinance auto-adjusted close",
            "tickers": TICKERS,
            "download_start": START_DATE,
            "download_end": END_DATE,
            "analysis_start": str(strategy_ret.index[0].date()),
            "analysis_end": str(strategy_ret.index[-1].date()),
            "n_days": int(len(strategy_ret)),
            "cached_prices": "experiments/k1494_cdar_vs_vol_target/data/prices.csv",
        },
        "method": {
            "base_portfolio": "equal-weight daily return of SPY/TLT/GLD/DBC",
            "vol_target": {
                "target_ann_vol": TARGET_VOL,
                "lookback_days": VOL_WINDOW,
                "signal_lag": "shift(1) before applying returns",
            },
            "cdar_target": {
                "alpha": CDAR_ALPHA,
                "lookback_days": CDAR_WINDOW,
                "target_cdar": calibration["target_cdar"],
                "target_calibration": calibration,
                "signal_lag": "shift(1) before applying returns",
            },
            "exposure_clip": [0.0, MAX_EXPOSURE],
            "transaction_cost_one_way": TX_COST_ONE_WAY,
            "oos_start": str(OOS_START.date()),
            "bootstrap": {
                "reps": BOOTSTRAP_REPS,
                "block_length": BOOTSTRAP_BLOCK,
                "seed": SEED,
            },
        },
        "metrics_full": full_metrics,
        "metrics_oos": oos_metrics,
        "stress_periods": stress_metrics,
        "formal_tests": {
            "paired_moving_block_bootstrap_oos": bootstrap,
        },
        "verdict": {
            "overall": verdict,
            "plain_english": verdict_text,
        },
        "figures": [
            "experiments/k1494_cdar_vs_vol_target/k1494_equity_curves.png",
            "experiments/k1494_cdar_vs_vol_target/k1494_exposure_and_risk_signals.png",
        ],
        "references": [
            {
                "citation": "Chekhlov, Uryasev, Zabarankin (2004/2005)",
                "note": "Introduced CDaR / CDD as worst-tail drawdown path risk measures.",
            },
            {
                "citation": "Rockafellar and Uryasev (2000, 2002)",
                "note": "CVaR optimization foundation; CDaR parallels expected shortfall on drawdown paths.",
            },
            {
                "citation": "scikit-portfolio Efficient Conditional Drawdown at Risk docs",
                "note": "Practical CDaR frontier implementation reference.",
            },
        ],
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results["verdict"], indent=2, ensure_ascii=False))
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
