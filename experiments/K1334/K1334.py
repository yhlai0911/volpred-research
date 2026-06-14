#!/usr/bin/env python3
"""K1334: Downside-CVaR (Expected Shortfall) target vs traditional volatility target.

Orthogonal companion to K1494 (CDaR target). Same base portfolio (equal-weight
SPY/TLT/GLD/DBC), same calibration scheme, same paired bootstrap; the only
difference is the alternative risk objective is the 1-day 99% historical CVaR
(left-tail Expected Shortfall) instead of CDaR95.

Anti-lookahead:
    Risk signals are computed from data up to t-1 via the natural rolling-window
    edge, then `.shift(1)` is applied as an explicit belt-and-suspenders lag
    before exposure is multiplied into base returns at day t.
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
RESULTS_PATH = HERE / "K1334_results.json"

TICKERS = ["SPY", "TLT", "GLD", "DBC"]
START_DATE = "2006-01-01"
END_DATE = "2026-06-01"
ANALYSIS_START = pd.Timestamp("2008-01-02")
IS_END = pd.Timestamp("2017-12-29")
OOS_START = pd.Timestamp("2018-01-02")

TARGET_VOL = 0.10
VOL_WINDOW = 63
CVAR_WINDOW = 252
CVAR_ALPHA = 0.99  # 99% CVaR -> worst 1% tail
CVAR_ALT_ALPHA = 0.95  # robustness alt
MAX_EXPOSURE = 1.50
TX_COST_ONE_WAY_HEADLINE = 0.0010  # 10 bps per task brief
TX_COST_ONE_WAY_ALT = 0.0005  # 5 bps for K1494 apples-to-apples comparison
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
SEED = 42
TRADING_DAYS = 252


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
    cvar1_daily: float
    var1_daily: float
    var1_breach_rate: float
    mean_exposure: float | None = None
    turnover_ann: float | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def download_prices() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "prices.csv"
    if cache.exists():
        prices = pd.read_csv(cache, index_col=0, parse_dates=True)
        prices = prices[TICKERS].dropna(how="any")
        return prices
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
    prices.to_csv(cache)
    return prices


def max_drawdown(returns: pd.Series) -> float:
    wealth = np.r_[1.0, (1.0 + returns.to_numpy()).cumprod()]
    peak = np.maximum.accumulate(wealth)
    drawdown = wealth / peak - 1.0
    return float(drawdown.min())


def cdar_from_returns(returns: pd.Series, alpha: float = 0.95) -> float:
    wealth = (1.0 + returns).cumprod()
    drawdown = 1.0 - wealth / wealth.cummax()
    drawdown = drawdown.dropna()
    if drawdown.empty:
        return 0.0
    tail_count = max(1, int(np.ceil((1.0 - alpha) * len(drawdown))))
    return float(np.sort(drawdown.to_numpy())[-tail_count:].mean())


def cvar_left_tail(returns_window: np.ndarray, alpha: float) -> float:
    """Historical CVaR (Expected Shortfall) at confidence alpha.

    Returns the absolute value (positive) of the mean of the worst (1-alpha)
    fraction of returns. For alpha=0.99 with 252 obs the worst-1% set has
    `ceil(0.01 * 252) = 3` returns.
    """
    if returns_window.size == 0:
        return float("nan")
    sorted_ret = np.sort(returns_window)
    tail_count = max(1, int(np.ceil((1.0 - alpha) * len(sorted_ret))))
    tail = sorted_ret[:tail_count]
    es = float(tail.mean())
    # ES of left tail will be negative for a risky asset; return magnitude
    return abs(es)


def rolling_cvar(returns: pd.Series, window: int, alpha: float) -> pd.Series:
    values = np.full(len(returns), np.nan)
    ret_values = returns.to_numpy()
    for i in range(window - 1, len(returns)):
        window_returns = ret_values[i - window + 1 : i + 1]
        values[i] = cvar_left_tail(window_returns, alpha=alpha)
    return pd.Series(values, index=returns.index, name=f"rolling_cvar_{int(alpha*100)}")


def compute_metrics(returns: pd.Series, exposure: pd.Series | None = None) -> Metrics:
    r = returns.dropna()
    wealth = (1.0 + r).cumprod()
    n = len(r)
    years = n / TRADING_DAYS if n else 1.0
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if n > 1 else 0.0
    ann_return = float(r.mean() * TRADING_DAYS) if n else 0.0
    ann_vol = float(r.std(ddof=1) * np.sqrt(TRADING_DAYS)) if n > 1 else 0.0
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0
    mdd = max_drawdown(r) if n else 0.0
    cdar95 = cdar_from_returns(r, alpha=0.95) if n else 0.0
    cvar5 = float(r[r <= r.quantile(0.05)].mean()) if n else 0.0
    cvar1 = float(r[r <= r.quantile(0.01)].mean()) if n else 0.0
    var1 = float(r.quantile(0.01)) if n else 0.0
    var1_breach = float((r <= var1).mean()) if n else 0.0
    left_tail = int((r <= -0.02).sum())

    mean_exposure = None
    turnover_ann = None
    if exposure is not None:
        e = exposure.reindex(r.index).dropna()
        mean_exposure = float(e.mean()) if len(e) else None
        turnover_ann = (
            float(e.diff().abs().fillna(0.0).mean() * TRADING_DAYS) if len(e) else None
        )

    def label_index(value) -> str:
        return str(value.date()) if hasattr(value, "date") else str(value)

    return Metrics(
        n_days=int(n),
        start=label_index(r.index[0]) if n else "",
        end=label_index(r.index[-1]) if n else "",
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
        cvar1_daily=cvar1,
        var1_daily=var1,
        var1_breach_rate=var1_breach,
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
        "cvar1_daily_pct": round(metrics.cvar1_daily * 100, 3),
        "var1_daily_pct": round(metrics.var1_daily * 100, 3),
        "var1_breach_rate": round(metrics.var1_breach_rate, 5),
        "mean_exposure": None
        if metrics.mean_exposure is None
        else round(metrics.mean_exposure, 4),
        "turnover_ann": None
        if metrics.turnover_ann is None
        else round(metrics.turnover_ann, 4),
    }


def calibrate_cvar_target(cvar_signal: pd.Series, vol_exposure_raw: pd.Series) -> dict:
    is_idx = cvar_signal.index[
        (cvar_signal.index >= ANALYSIS_START) & (cvar_signal.index <= IS_END)
    ]
    target_mean = float(vol_exposure_raw.reindex(is_idx).dropna().mean())
    candidates = np.linspace(0.001, 0.10, 991)
    best_target = None
    best_gap = float("inf")
    best_mean = None
    for target in candidates:
        exposure = (target / cvar_signal.reindex(is_idx)).clip(lower=0.0, upper=MAX_EXPOSURE)
        mean_exposure = float(exposure.dropna().mean())
        gap = abs(mean_exposure - target_mean)
        if gap < best_gap:
            best_gap = gap
            best_target = float(target)
            best_mean = mean_exposure
    return {
        "target_cvar": best_target,
        "vol_target_is_mean_exposure": target_mean,
        "cvar_is_mean_exposure": best_mean,
        "absolute_gap": best_gap,
        "calibration_period": [str(ANALYSIS_START.date()), str(IS_END.date())],
    }


def strategy_returns(
    base_ret: pd.Series, exposure: pd.Series, tx_cost: float
) -> pd.Series:
    aligned = pd.concat([base_ret.rename("base"), exposure.rename("exposure")], axis=1).dropna()
    cost = aligned["exposure"].diff().abs().fillna(0.0) * tx_cost
    out = aligned["exposure"] * aligned["base"] - cost
    out.name = exposure.name or "strategy"
    return out


def moving_block_bootstrap_diff(vol_ret: pd.Series, cvar_ret: pd.Series) -> dict:
    paired = pd.concat([vol_ret.rename("vol"), cvar_ret.rename("cvar")], axis=1).dropna()
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
        cvar = pd.Series(sample[:, 1])
        m_vol = compute_metrics(vol)
        m_cvar = compute_metrics(cvar)
        records.append(
            {
                "sharpe_diff_cvar_minus_vol": m_cvar.sharpe - m_vol.sharpe,
                "mdd_diff_pp_cvar_minus_vol": (m_cvar.mdd - m_vol.mdd) * 100,
                "cagr_diff_pp_cvar_minus_vol": (m_cvar.cagr - m_vol.cagr) * 100,
                "left_tail_freq_diff_cvar_minus_vol": m_cvar.left_tail_freq_2pct
                - m_vol.left_tail_freq_2pct,
                "cvar5_diff_pp_cvar_minus_vol": (m_cvar.cvar5_daily - m_vol.cvar5_daily)
                * 100,
                "cvar1_diff_pp_cvar_minus_vol": (m_cvar.cvar1_daily - m_vol.cvar1_daily)
                * 100,
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


def build_figures(
    returns: pd.DataFrame, exposures: pd.DataFrame, risk: pd.DataFrame
) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    wealth = (1.0 + returns).cumprod()

    fig, ax = plt.subplots(figsize=(10, 6))
    for col, color in [
        ("buy_hold", "#555555"),
        ("vol_target", "#1f77b4"),
        ("cvar_target", "#7a3f9d"),
    ]:
        ax.plot(wealth.index, wealth[col], label=col, linewidth=2.0, color=color)
    ax.set_title("K1334: Equity Curves (net of 10 bp turnover cost)")
    ax.set_ylabel("Growth of $1")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(HERE / "k1334_equity_curves.png", dpi=180)
    plt.close(fig)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax1.plot(exposures.index, exposures["vol_target"], label="vol target exposure", color="#1f77b4")
    ax1.plot(exposures.index, exposures["cvar_target"], label="CVaR target exposure", color="#7a3f9d")
    ax1.set_ylabel("Exposure")
    ax1.legend(frameon=False)
    ax2.plot(risk.index, risk["ann_vol_63"], label="63d annualized vol", color="#1f77b4")
    ax2.plot(
        risk.index,
        risk["cvar99_252"],
        label="252d |CVaR99| (left tail ES)",
        color="#7a3f9d",
    )
    ax2.set_ylabel("Risk estimate")
    ax2.legend(frameon=False)
    fig.suptitle("K1334: Lagged Exposure Signals and Risk Estimates")
    fig.tight_layout()
    fig.savefig(HERE / "k1334_exposure_and_risk_signals.png", dpi=180)
    plt.close(fig)


def main() -> None:
    prices = download_prices()
    returns = prices.pct_change().dropna()
    base_ret = returns.mean(axis=1).rename("base_equal_weight")
    base_ret = base_ret[base_ret.index >= ANALYSIS_START]

    # --- Vol target signal (same as K1494) ---
    ann_vol_63 = (
        base_ret.rolling(VOL_WINDOW).std(ddof=1) * np.sqrt(TRADING_DAYS)
    ).rename("ann_vol_63")
    vol_exposure_raw = (TARGET_VOL / ann_vol_63).clip(lower=0.0, upper=MAX_EXPOSURE)
    vol_exposure = vol_exposure_raw.shift(1).rename("vol_target")

    # --- CVaR99 target signal (this experiment) ---
    cvar99_252 = rolling_cvar(base_ret, window=CVAR_WINDOW, alpha=CVAR_ALPHA).rename(
        "cvar99_252"
    )
    calibration = calibrate_cvar_target(cvar99_252, vol_exposure_raw)
    cvar_exposure_raw = (
        calibration["target_cvar"] / cvar99_252
    ).clip(lower=0.0, upper=MAX_EXPOSURE)
    cvar_exposure = cvar_exposure_raw.shift(1).rename("cvar_target")

    # --- Robustness: CVaR95 (alpha=0.95) target ---
    cvar95_252 = rolling_cvar(
        base_ret, window=CVAR_WINDOW, alpha=CVAR_ALT_ALPHA
    ).rename("cvar95_252")
    calibration_alt = calibrate_cvar_target(cvar95_252, vol_exposure_raw)
    cvar95_exposure_raw = (
        calibration_alt["target_cvar"] / cvar95_252
    ).clip(lower=0.0, upper=MAX_EXPOSURE)
    cvar95_exposure = cvar95_exposure_raw.shift(1).rename("cvar95_target")

    buy_hold_exposure = pd.Series(1.0, index=base_ret.index, name="buy_hold")

    # --- Headline (10 bps cost) ---
    strategy_ret = pd.concat(
        [
            strategy_returns(base_ret, buy_hold_exposure, TX_COST_ONE_WAY_HEADLINE).rename(
                "buy_hold"
            ),
            strategy_returns(base_ret, vol_exposure, TX_COST_ONE_WAY_HEADLINE).rename(
                "vol_target"
            ),
            strategy_returns(base_ret, cvar_exposure, TX_COST_ONE_WAY_HEADLINE).rename(
                "cvar_target"
            ),
            strategy_returns(base_ret, cvar95_exposure, TX_COST_ONE_WAY_HEADLINE).rename(
                "cvar95_target"
            ),
        ],
        axis=1,
    ).dropna()
    exposures = pd.concat(
        [buy_hold_exposure, vol_exposure, cvar_exposure, cvar95_exposure], axis=1
    ).reindex(strategy_ret.index)
    risk_signals = pd.concat([ann_vol_63, cvar99_252, cvar95_252], axis=1).reindex(
        strategy_ret.index
    )

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

    # --- Robustness: 5 bps cost (K1494 parity) ---
    strategy_ret_5bp = pd.concat(
        [
            strategy_returns(base_ret, buy_hold_exposure, TX_COST_ONE_WAY_ALT).rename(
                "buy_hold"
            ),
            strategy_returns(base_ret, vol_exposure, TX_COST_ONE_WAY_ALT).rename(
                "vol_target"
            ),
            strategy_returns(base_ret, cvar_exposure, TX_COST_ONE_WAY_ALT).rename(
                "cvar_target"
            ),
        ],
        axis=1,
    ).dropna()
    oos_ret_5bp = strategy_ret_5bp[strategy_ret_5bp.index >= OOS_START]
    oos_metrics_5bp = {
        col: as_json_metrics(compute_metrics(oos_ret_5bp[col], oos_exp[col]))
        for col in oos_ret_5bp.columns
    }

    # Stress periods
    stress_periods = {
        "gfc": ("2008-01-02", "2009-06-30"),
        "covid_crash": ("2020-02-20", "2020-04-30"),
        "rates_2022": ("2022-01-03", "2022-10-31"),
        "post_2024": ("2024-01-02", "2026-05-29"),
    }
    stress_metrics = {}
    for name, (start, end) in stress_periods.items():
        sub = strategy_ret.loc[start:end]
        exp_sub = exposures.reindex(sub.index)
        if len(sub) < 20:
            continue
        stress_metrics[name] = {
            col: as_json_metrics(compute_metrics(sub[col], exp_sub[col]))
            for col in sub.columns
        }

    bootstrap = moving_block_bootstrap_diff(
        oos_ret["vol_target"], oos_ret["cvar_target"]
    )

    build_figures(
        strategy_ret[["buy_hold", "vol_target", "cvar_target"]],
        exposures[["buy_hold", "vol_target", "cvar_target"]],
        risk_signals,
    )

    # ---- Verdict logic ----
    sharpe_vol = oos_metrics["vol_target"]["sharpe"]
    sharpe_cvar = oos_metrics["cvar_target"]["sharpe"]
    mdd_vol = oos_metrics["vol_target"]["mdd_pct"]
    mdd_cvar = oos_metrics["cvar_target"]["mdd_pct"]
    ltf_vol = oos_metrics["vol_target"]["left_tail_freq_2pct"]
    ltf_cvar = oos_metrics["cvar_target"]["left_tail_freq_2pct"]
    boot_ltf_ci = bootstrap["left_tail_freq_diff_cvar_minus_vol"]
    boot_sharpe_ci = bootstrap["sharpe_diff_cvar_minus_vol"]
    boot_mdd_ci = bootstrap["mdd_diff_pp_cvar_minus_vol"]

    # PASS condition: CVaR Sharpe > vol Sharpe AND left-tail freq significantly improves
    # (CI on (cvar - vol) left_tail_freq < 0)
    is_pass = (
        sharpe_cvar > sharpe_vol
        and boot_ltf_ci["ci_97p5"] < 0
        and boot_sharpe_ci["ci_2p5"] > 0
    )
    # NULL: indistinguishable (CI crosses 0 on Sharpe & left-tail freq)
    is_null = (
        boot_sharpe_ci["ci_2p5"] <= 0 <= boot_sharpe_ci["ci_97p5"]
        or boot_ltf_ci["ci_2p5"] <= 0 <= boot_ltf_ci["ci_97p5"]
    )

    if is_pass:
        verdict = "CVAR_IMPROVES_TAIL"
        verdict_text = (
            "The 1-day 99% historical CVaR scaler beats traditional realized-vol "
            "targeting OOS on both Sharpe and left-tail day frequency (paired "
            "moving-block bootstrap 95% CI). Tail objective adds value beyond vol "
            "objective."
        )
    elif is_null:
        verdict = "NULL"
        verdict_text = (
            "The 1-day 99% historical CVaR scaler does not reliably beat realized-vol "
            "targeting OOS. Paired moving-block bootstrap CIs on Sharpe / left-tail "
            "frequency cross zero. Mechanism is the same as K1494: a backward-looking "
            "tail estimate cannot anticipate fast crashes. Combined with K1494 (CDaR "
            "NULL), the risk-target family (drawdown-aware and tail-aware) does not "
            "improve on a 63-day realized-vol target on this 4-ETF base."
        )
    else:
        verdict = "MIXED"
        verdict_text = (
            "CVaR target shows directional movement vs vol target but does not jointly "
            "satisfy the pre-specified PASS criteria; see metrics_oos and bootstrap "
            "details."
        )

    results = {
        "experiment_id": "K1334_cvar_vs_vol_target",
        "title": (
            "Downside-CVaR (Expected Shortfall) target vs traditional vol target"
        ),
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
            "cached_prices": "experiments/K1334/data/prices.csv",
        },
        "method": {
            "base_portfolio": "equal-weight daily return of SPY/TLT/GLD/DBC",
            "vol_target": {
                "target_ann_vol": TARGET_VOL,
                "lookback_days": VOL_WINDOW,
                "signal_lag": "shift(1) before applying returns",
                "exposure_clip": [0.0, MAX_EXPOSURE],
            },
            "cvar_target": {
                "alpha": CVAR_ALPHA,
                "lookback_days": CVAR_WINDOW,
                "target_cvar": calibration["target_cvar"],
                "target_calibration": calibration,
                "signal_lag": "shift(1) before applying returns",
                "exposure_clip": [0.0, MAX_EXPOSURE],
                "tail_definition": (
                    "Historical ES: mean of worst ceil((1-alpha)*N) daily returns "
                    "in trailing 252d window; absolute value as denominator."
                ),
            },
            "cvar95_target_alt": {
                "alpha": CVAR_ALT_ALPHA,
                "lookback_days": CVAR_WINDOW,
                "target_cvar": calibration_alt["target_cvar"],
                "target_calibration": calibration_alt,
            },
            "transaction_cost_one_way_headline_bps": TX_COST_ONE_WAY_HEADLINE * 10000,
            "transaction_cost_one_way_alt_bps": TX_COST_ONE_WAY_ALT * 10000,
            "oos_start": str(OOS_START.date()),
            "bootstrap": {
                "reps": BOOTSTRAP_REPS,
                "block_length": BOOTSTRAP_BLOCK,
                "seed": SEED,
            },
            "anti_lookahead": (
                "Rolling stats use only window ending at t (inclusive); risk signal "
                "is further .shift(1)-ed before being multiplied into returns at t. "
                "Net effect: exposure at t depends only on data up to t-1."
            ),
        },
        "metrics_full": full_metrics,
        "metrics_oos": oos_metrics,
        "metrics_oos_5bp_cost": oos_metrics_5bp,
        "stress_periods": stress_metrics,
        "formal_tests": {
            "paired_moving_block_bootstrap_oos_cvar_vs_vol": bootstrap,
        },
        "verdict": {
            "overall": verdict,
            "plain_english": verdict_text,
            "comparison_with_k1494": (
                "K1494 (CDaR target) NULL: Sharpe 0.93 vs vol 1.00, MDD -23% vs -16%, "
                "left-tail 29 vs 18 days. K1334 (CVaR target) verdict above. Both "
                "risk-target alternatives share the backward-looking pathology."
            ),
        },
        "figures": [
            "experiments/K1334/k1334_equity_curves.png",
            "experiments/K1334/k1334_exposure_and_risk_signals.png",
        ],
        "references": [
            {
                "citation": "Rockafellar & Uryasev (2000, 2002)",
                "note": "CVaR / Expected Shortfall optimization foundation.",
            },
            {
                "citation": "Acerbi & Tasche (2002)",
                "note": "Coherence of Expected Shortfall.",
            },
            {
                "citation": "VolPred K1494",
                "note": "CDaR target NULL — drawdown signal backward-looking.",
            },
            {
                "citation": "VolPred K5 / K648",
                "note": "Backward-looking risk signals lag realized tail events.",
            },
        ],
    }

    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(results["verdict"], indent=2, ensure_ascii=False))
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
