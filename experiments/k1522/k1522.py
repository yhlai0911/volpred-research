"""
K1522: Corporate-bond ETF factor-zoo bias-correction audit.

This is an ETF-proxy pilot, not a TRACE bond-level replication. It tests whether
simple corporate-bond ETF factor premia survive a conservative extra-lag
correction that breaks the shared price denominator between price-based signals
at t and next-period returns from t to t+1.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import strategy_dm_test

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "k1522_results.json"
FIG_PATH = OUT_DIR / "k1522_factor_audit.png"

START = "2009-01-01"
OOS_START = "2015-01-02"
END = None
ETF_TICKERS = ["HYG", "JNK", "LQD", "VCIT", "VCSH", "VCLT", "IGSB", "IGIB"]
CORE_TASK_TICKERS = ["HYG", "LQD", "VCIT", "VCSH"]
MARKET_TICKERS = ["SPY", "TLT", "SHY"]
ALL_TICKERS = ETF_TICKERS + MARKET_TICKERS
TRADING_DAYS = 252


@dataclass(frozen=True)
class MetricRow:
    signal: str
    variant: str
    n: int
    ann_return: float
    ann_vol: float
    sharpe: float
    max_drawdown: float
    dm_t_vs_zero: float
    dm_p_vs_zero: float
    harvey_pass: bool


def _download_one(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start=START, end=END, auto_adjust=False, progress=False)
    if df.empty:
        raise RuntimeError(f"no yfinance data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    needed = ["Close", "High", "Low", "Volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise RuntimeError(f"{ticker} missing columns: {missing}")
    if "Adj Close" not in df.columns:
        df["Adj Close"] = df["Close"]
    out = df[["Adj Close", "Close", "High", "Low", "Volume"]].copy()
    out.columns = pd.MultiIndex.from_product([[ticker], out.columns])
    return out


def load_panel() -> pd.DataFrame:
    frames = [_download_one(t) for t in ALL_TICKERS]
    panel = pd.concat(frames, axis=1).sort_index()
    panel = panel.loc[panel.index >= pd.Timestamp(START)]
    return panel.dropna(how="all")


def rolling_beta(asset_returns: pd.DataFrame, factor: pd.Series, window: int) -> pd.DataFrame:
    out = {}
    factor_var = factor.rolling(window).var()
    for col in asset_returns:
        cov = asset_returns[col].rolling(window).cov(factor)
        out[col] = cov / factor_var
    return pd.DataFrame(out)


def build_signals(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    adj = panel.xs("Adj Close", level=1, axis=1)
    close = panel.xs("Close", level=1, axis=1)
    high = panel.xs("High", level=1, axis=1)
    low = panel.xs("Low", level=1, axis=1)
    volume = panel.xs("Volume", level=1, axis=1)

    returns = adj[ETF_TICKERS].pct_change()
    market_returns = adj[MARKET_TICKERS].pct_change()

    total_ret_252 = adj[ETF_TICKERS].pct_change(TRADING_DAYS)
    price_ret_252 = close[ETF_TICKERS].pct_change(TRADING_DAYS)
    carry_252 = total_ret_252 - price_ret_252

    dollar_volume_m = close[ETF_TICKERS] * volume[ETF_TICKERS] / 1_000_000.0
    amihud_21 = (returns.abs() / dollar_volume_m.replace(0, np.nan)).rolling(21).mean()
    range_vol_21 = ((high[ETF_TICKERS] - low[ETF_TICKERS]) / close[ETF_TICKERS]).rolling(21).mean()

    credit_factor = returns["HYG"] - returns["LQD"]
    credit_beta_126 = rolling_beta(returns, credit_factor, 126)
    term_beta_126 = rolling_beta(returns, market_returns["TLT"], 126)

    signals = {
        "momentum_63": adj[ETF_TICKERS].pct_change(63),
        "carry_252": carry_252,
        "illiquidity_amihud_21": amihud_21,
        "range_vol_21": range_vol_21,
        "credit_beta_126": credit_beta_126,
        "term_beta_126": term_beta_126,
    }
    return returns, signals


def rank_weighted_factor_return(signal: pd.DataFrame, future_returns: pd.DataFrame) -> pd.Series:
    rows = []
    for date, s in signal.iterrows():
        r = future_returns.loc[date]
        valid = s.notna() & r.notna()
        if valid.sum() < 4:
            rows.append(np.nan)
            continue
        ranks = s[valid].rank(method="average", pct=True)
        weights = ranks - ranks.mean()
        denom = weights.abs().sum()
        if denom <= 0:
            rows.append(np.nan)
            continue
        weights = weights / denom
        rows.append(float((weights * r[valid]).sum()))
    return pd.Series(rows, index=signal.index)


def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def evaluate_series(name: str, variant: str, returns: pd.Series) -> MetricRow:
    r = returns.dropna()
    n = len(r)
    if n < 252:
        return MetricRow(name, variant, n, np.nan, np.nan, np.nan, np.nan, 0.0, 1.0, False)
    ann_return = float(r.mean() * TRADING_DAYS)
    ann_vol = float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))
    sharpe = float(ann_return / ann_vol) if ann_vol > 0 else np.nan
    dm_t, dm_p = strategy_dm_test(r.to_numpy(), np.zeros(n), h=5, loss_fn="negative_return")
    harvey_pass = bool(dm_t < -3.0 and ann_return > 0)
    return MetricRow(
        signal=name,
        variant=variant,
        n=n,
        ann_return=ann_return,
        ann_vol=ann_vol,
        sharpe=sharpe,
        max_drawdown=max_drawdown(r),
        dm_t_vs_zero=float(dm_t),
        dm_p_vs_zero=float(dm_p),
        harvey_pass=harvey_pass,
    )


def summarize_periods(series_by_signal: dict[str, pd.Series]) -> dict[str, dict[str, dict[str, float]]]:
    periods = {
        "full_oos_2015_2026": ("2015-01-02", None),
        "pre_covid_2015_2019": ("2015-01-02", "2019-12-31"),
        "covid_rate_2020_2022": ("2020-01-01", "2022-12-31"),
        "post_rate_2023_2026": ("2023-01-01", None),
    }
    out: dict[str, dict[str, dict[str, float]]] = {}
    for period_name, (start, end) in periods.items():
        out[period_name] = {}
        for name, r in series_by_signal.items():
            sub = r.loc[pd.Timestamp(start):] if end is None else r.loc[pd.Timestamp(start):pd.Timestamp(end)]
            row = evaluate_series(name, "bias_corrected", sub)
            out[period_name][name] = {
                "n": row.n,
                "ann_return": round(row.ann_return, 6) if np.isfinite(row.ann_return) else None,
                "ann_vol": round(row.ann_vol, 6) if np.isfinite(row.ann_vol) else None,
                "sharpe": round(row.sharpe, 4) if np.isfinite(row.sharpe) else None,
                "dm_t_vs_zero": round(row.dm_t_vs_zero, 4),
                "dm_p_vs_zero": round(row.dm_p_vs_zero, 4),
                "harvey_pass": row.harvey_pass,
            }
    return out


def make_figure(metrics: list[MetricRow], corrected_returns: dict[str, pd.Series]) -> None:
    metric_df = pd.DataFrame([m.__dict__ for m in metrics])
    corrected = metric_df[metric_df["variant"] == "bias_corrected"].sort_values("sharpe")
    naive = metric_df[metric_df["variant"] == "naive"].set_index("signal")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    axes[0].barh(corrected["signal"], corrected["sharpe"], color="#3f6f68")
    axes[0].axvline(0, color="black", linewidth=0.8)
    axes[0].axvline(1, color="#c47f2d", linestyle="--", linewidth=0.8)
    axes[0].set_title("Bias-corrected OOS Sharpe by ETF factor proxy")
    axes[0].set_xlabel("Annualized Sharpe, 2015-2026")

    drops = []
    labels = []
    for _, row in corrected.iterrows():
        sig = row["signal"]
        labels.append(sig)
        drops.append(row["sharpe"] - float(naive.loc[sig, "sharpe"]))
    axes[1].barh(labels, drops, color=["#9b3d35" if v < 0 else "#3f6f68" for v in drops])
    axes[1].axvline(0, color="black", linewidth=0.8)
    axes[1].set_title("Sharpe change after extra-lag bias correction")
    axes[1].set_xlabel("Corrected minus naive Sharpe")

    fig.suptitle("K1522 corporate-bond ETF factor-zoo bias-correction audit", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    t0 = datetime.now(timezone.utc)
    panel = load_panel()
    returns, signals = build_signals(panel)
    future_returns = returns.shift(-1)

    metrics: list[MetricRow] = []
    factor_returns: dict[str, dict[str, pd.Series]] = {}

    for name, signal in signals.items():
        naive = rank_weighted_factor_return(signal, future_returns).loc[pd.Timestamp(OOS_START):]
        corrected = rank_weighted_factor_return(signal.shift(1), future_returns).loc[pd.Timestamp(OOS_START):]
        factor_returns[name] = {"naive": naive, "bias_corrected": corrected}
        metrics.append(evaluate_series(name, "naive", naive))
        metrics.append(evaluate_series(name, "bias_corrected", corrected))

    corrected_returns = {name: variants["bias_corrected"] for name, variants in factor_returns.items()}
    make_figure(metrics, corrected_returns)

    metric_records = []
    comparison_records = []
    for row in metrics:
        metric_records.append(
            {
                "signal": row.signal,
                "variant": row.variant,
                "n": row.n,
                "ann_return": round(row.ann_return, 6) if np.isfinite(row.ann_return) else None,
                "ann_vol": round(row.ann_vol, 6) if np.isfinite(row.ann_vol) else None,
                "sharpe": round(row.sharpe, 4) if np.isfinite(row.sharpe) else None,
                "max_drawdown": round(row.max_drawdown, 4) if np.isfinite(row.max_drawdown) else None,
                "dm_t_vs_zero": round(row.dm_t_vs_zero, 4),
                "dm_p_vs_zero": round(row.dm_p_vs_zero, 4),
                "harvey_pass": row.harvey_pass,
            }
        )

    for name, variants in factor_returns.items():
        aligned = pd.concat([variants["bias_corrected"], variants["naive"]], axis=1, keys=["corrected", "naive"]).dropna()
        dm_t, dm_p = strategy_dm_test(
            aligned["corrected"].to_numpy(),
            aligned["naive"].to_numpy(),
            h=5,
            loss_fn="negative_return",
        )
        naive_row = next(m for m in metrics if m.signal == name and m.variant == "naive")
        corr_row = next(m for m in metrics if m.signal == name and m.variant == "bias_corrected")
        comparison_records.append(
            {
                "signal": name,
                "naive_sharpe": round(naive_row.sharpe, 4),
                "corrected_sharpe": round(corr_row.sharpe, 4),
                "sharpe_delta_corrected_minus_naive": round(corr_row.sharpe - naive_row.sharpe, 4),
                "corrected_vs_naive_dm_t": round(float(dm_t), 4),
                "corrected_vs_naive_dm_p": round(float(dm_p), 4),
                "artifact_flag": bool(naive_row.harvey_pass and not corr_row.harvey_pass),
            }
        )

    corrected_passes = [
        m.signal for m in metrics if m.variant == "bias_corrected" and m.harvey_pass
    ]
    best_corrected = max(
        (m for m in metrics if m.variant == "bias_corrected"),
        key=lambda m: -999 if not np.isfinite(m.sharpe) else m.sharpe,
    )

    if corrected_passes:
        verdict = "PASS_NARROW_ETF_PROXY"
        summary = (
            f"Bias-corrected ETF proxy factor premia survive Harvey threshold for {corrected_passes}. "
            "This is still ETF-level evidence, not bond-level factor-zoo replication."
        )
    else:
        verdict = "NULL_ETF_PROXY"
        summary = (
            "No corporate-bond ETF proxy factor delivers a positive premium with Harvey-strength "
            "DM evidence after the extra-lag bias correction. The ETF proxy is insufficient to "
            "rescue a tradable factor-zoo claim."
        )

    output = {
        "experiment_id": "K1522",
        "title": "Corporate-bond ETF factor-zoo bias-correction audit",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": "research_factor_zoo_bias_corrected_etf_proxy_oos",
        "verdict": verdict,
        "summary": summary,
        "data": {
            "source": "yfinance",
            "start": str(panel.index.min().date()),
            "end": str(panel.index.max().date()),
            "tickers": ETF_TICKERS,
            "core_task_tickers": CORE_TASK_TICKERS,
            "market_tickers": MARKET_TICKERS,
            "oos_start": OOS_START,
            "n_panel_days": int(len(panel)),
        },
        "method": {
            "scope": "ETF proxy pilot; not TRACE bond-level replication",
            "signals": list(signals.keys()),
            "portfolio": "daily cross-sectional rank-weighted long-high/short-low among corporate-bond ETFs",
            "naive_alignment": "signal at t predicts adjusted-return t+1; this shares price P_t with next return denominator for price-based signals",
            "bias_correction_proxy": "extra one-trading-day signal lag, signal at t-1 predicts return t+1, reducing shared-denominator EIV bias",
            "lookahead_guard": "future returns are returns.shift(-1); all signals are current or lagged, and bias-corrected results use signal.shift(1)",
            "test": "strategy_dm_test against zero return, h=5, Harvey pass if DM t < -3 and annualized return > 0",
        },
        "metrics": metric_records,
        "naive_vs_corrected": comparison_records,
        "period_breakdown_bias_corrected": summarize_periods(corrected_returns),
        "key_numbers": {
            "corrected_passes": corrected_passes,
            "best_corrected_signal": best_corrected.signal,
            "best_corrected_sharpe": round(best_corrected.sharpe, 4),
            "best_corrected_dm_t": round(best_corrected.dm_t_vs_zero, 4),
            "signals_tested": len(signals),
        },
        "limitations": [
            "ETF cross-section is small and blends duration, credit quality, index construction, and fund microstructure.",
            "Extra-lag correction only approximates the Open Bond Asset Pricing denominator-bias correction; it is not a substitute for error-corrected TRACE bond-level data.",
            "Dividend/carry is inferred from adjusted-close versus close total-return difference, not from bond-level yield-to-maturity.",
            "Daily long-short ETF factor returns ignore borrow, financing, and ETF creation/redemption frictions.",
        ],
        "references": [
            {
                "title": "Dickerson, Robotti, Rossetti (2026), The Corporate Bond Factor Replication Crisis",
                "url": "https://arxiv.org/abs/2604.07880",
                "use": "Motivates denominator-bias and ex-post-filtering audit for corporate bond factors.",
            },
            {
                "title": "Open Bond Asset Pricing",
                "url": "https://openbondassetpricing.com/",
                "use": "Open-source benchmark for correctly constructed corporate bond factors; K1522 is only an ETF proxy.",
            },
            {
                "title": "The Co-Pricing Factor Zoo (2026), Journal of Financial Economics / RePEc listing",
                "url": "https://ideas.repec.org/a/eee/jfinec/v182y2026ics0304405x26000668.html",
                "use": "Context that corporate bond factor information may be redundant once common equity/term risks are accounted for.",
            },
        ],
        "elapsed_seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 2),
    }

    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"verdict": verdict, "summary": summary, "results": str(RESULTS_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
