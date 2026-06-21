#!/usr/bin/env python3
"""K1359: Tail-asymmetry estimator horse race across liquid ETFs.

Question
--------
Do simple, returns-only tail-asymmetry estimators produce a robust multi-asset
tail premium at monthly frequency?

Design
------
For each ETF and each month, compute several trailing 63-trading-day
asymmetry estimators from daily log returns. The signal is then shifted by
one month and used to sort ETFs for the current month's return, realized
volatility, and left-tail exposure. The primary statistic is a monthly
high-minus-low spread; inference is over the monthly spread series, not over
pooled ticker-month rows.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

EXPERIMENT_ID = "K1359"
SEED = 42
START = "2006-01-01"
ROLL_WINDOW = 63
MIN_ROLL_OBS = 50
MIN_ASSETS_PER_MONTH = 7
TOP_N = 3
NW_LAG = 3
BOOT_REPS = 1000
BOOT_BLOCK_MONTHS = 6

UNIVERSE = ["SPY", "QQQ", "TLT", "GLD", "USO", "UUP", "FXY", "HYG", "EEM"]

LITERATURE = [
    {
        "citation": "Kelly and Jiang (2014), Tail Risk and Asset Prices, Review of Financial Studies",
        "url": "https://academic.oup.com/rfs/article-abstract/27/10/2841/1607080",
        "role": "tail risk is priced, but canonical measure uses cross-section of individual-stock crashes rather than ETF trailing moments",
    },
    {
        "citation": "Bali, Cakici, and Whitelaw (2011), Maxing out: Stocks as lotteries and the cross-section of expected returns, Journal of Financial Economics",
        "url": "https://econpapers.repec.org/RePEc:eee:jfinec:v:99:y:2011:i:2:p:427-446",
        "role": "lottery-like right-tail measures motivate testing whether tail-shape proxies forecast returns",
    },
    {
        "citation": "Conrad, Dittmar, and Ghysels (2013), Ex Ante Skewness and Expected Stock Returns, Journal of Finance",
        "url": "https://econpapers.repec.org/RePEc:bla:jfinan:v:68:y:2013:i:1:p:85-124",
        "role": "option-implied skewness matters for expected returns; K1359 tests a cheaper realized-return proxy only",
    },
    {
        "citation": "Kozhan, Neuberger, and Schneider (2013), The Skew Risk Premium in the Equity Index Market, Review of Financial Studies",
        "url": "https://academic.oup.com/rfs/article-abstract/26/9/2174/1663145",
        "role": "skew risk premium is option-surface based and tightly connected to variance risk; realized-return proxies may be insufficient",
    },
    {
        "citation": "Harvey, Liu, and Zhu (2016), ... and the Cross-Section of Expected Returns, Review of Financial Studies",
        "url": "https://academic.oup.com/rfs/article/29/1/5/1843824",
        "role": "uses |t| > 3 as the discovery bar for return-predictor claims",
    },
]


def _read_cached_close(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"])
    if "Close" not in df.columns:
        raise ValueError(f"cache lacks Close column: {path}")
    s = df.set_index("Date")["Close"].sort_index()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s[~s.index.duplicated(keep="last")]


def load_close(ticker: str, refresh: bool) -> pd.Series:
    cache = DATA_DIR / f"{ticker}.csv"
    if cache.exists() and not refresh:
        return _read_cached_close(cache)

    # Reuse already versioned local yfinance caches where available, then
    # write a self-contained cache for this experiment.
    fallback = HERE.parent / "k1507" / "data" / f"{ticker}.csv"
    if fallback.exists() and not refresh:
        s = _read_cached_close(fallback)
        s.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(
            cache, index=False
        )
        return s

    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=START, auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError(f"empty yfinance history for {ticker}")
    s = hist["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(
        cache, index=False
    )
    return s


def load_prices(refresh: bool) -> tuple[pd.DataFrame, dict]:
    closes = {ticker: load_close(ticker, refresh) for ticker in UNIVERSE}
    close = pd.DataFrame(closes).sort_index()
    close = close.dropna(how="all")

    # Avoid treating the current, incomplete calendar month as a completed
    # monthly target.
    current_month = pd.Timestamp(datetime.now().date()).to_period("M")
    close = close[close.index.to_period("M") < current_month]

    coverage = {}
    for ticker in UNIVERSE:
        s = close[ticker].dropna()
        coverage[ticker] = {
            "first": str(s.index.min().date()) if not s.empty else None,
            "last": str(s.index.max().date()) if not s.empty else None,
            "n_daily_prices": int(len(s)),
        }
    return close, coverage


def _safe_skew(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 20:
        return np.nan
    sd = x.std(ddof=1)
    if sd <= 0:
        return np.nan
    centered = (x - x.mean()) / sd
    return float(np.mean(centered**3))


def _trimmed_skew(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return np.nan
    lo, hi = np.quantile(x, [0.05, 0.95])
    kept = x[(x >= lo) & (x <= hi)]
    return _safe_skew(kept)


def _winsorized_skew(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return np.nan
    lo, hi = np.quantile(x, [0.05, 0.95])
    return _safe_skew(np.clip(x, lo, hi))


def _semivar_log_ratio(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    neg = x[x < 0.0]
    pos = x[x > 0.0]
    if len(neg) < 5 or len(pos) < 5:
        return np.nan
    downside = float(np.sum(neg**2))
    upside = float(np.sum(pos**2))
    if downside <= 0 or upside <= 0:
        return np.nan
    return float(np.log(downside / upside))


def _tail_mean_gap(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 30:
        return np.nan
    q05, q95 = np.quantile(x, [0.05, 0.95])
    left_loss = -float(x[x <= q05].mean())
    right_gain = float(x[x >= q95].mean())
    return left_loss - right_gain


def _max_loss_gain_gap(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 20:
        return np.nan
    return -float(np.min(x)) - float(np.max(x))


def rolling_apply(frame: pd.DataFrame, func: Callable[[np.ndarray], float]) -> pd.DataFrame:
    return frame.rolling(ROLL_WINDOW, min_periods=MIN_ROLL_OBS).apply(func, raw=True)


def build_daily_estimators(log_returns: pd.DataFrame) -> dict[str, pd.DataFrame]:
    raw_skew = log_returns.rolling(ROLL_WINDOW, min_periods=MIN_ROLL_OBS).skew()
    estimators = {
        "bad_skew": -raw_skew,
        "bad_trimmed_skew": -rolling_apply(log_returns, _trimmed_skew),
        "bad_winsor_skew": -rolling_apply(log_returns, _winsorized_skew),
        "semivar_log_ratio": rolling_apply(log_returns, _semivar_log_ratio),
        "tail_mean_gap": rolling_apply(log_returns, _tail_mean_gap),
        "max_loss_gain_gap": rolling_apply(log_returns, _max_loss_gain_gap),
    }
    return estimators


def monthly_outcomes(close: pd.DataFrame, log_returns: pd.DataFrame) -> dict[str, pd.DataFrame]:
    monthly_close = close.resample("ME").last()
    ret = monthly_close.pct_change()

    month_count = log_returns.resample("ME").count()
    rv_ann = np.sqrt(log_returns.pow(2).resample("ME").sum(min_count=10) / month_count * 252.0)
    downside_vol_ann = np.sqrt(
        log_returns.mask(log_returns > 0.0, 0.0).pow(2).resample("ME").sum(min_count=10)
        / month_count
        * 252.0
    )
    left_tail_loss = -log_returns.resample("ME").min()
    return {
        "ret": ret,
        "rv_ann": rv_ann,
        "downside_vol_ann": downside_vol_ann,
        "left_tail_loss": left_tail_loss,
    }


def build_panel(refresh: bool) -> tuple[pd.DataFrame, dict]:
    close, coverage = load_prices(refresh)
    log_returns = np.log(close / close.shift(1))
    estimator_daily = build_daily_estimators(log_returns)
    outcomes = monthly_outcomes(close, log_returns)

    monthly_features = {
        name: value.resample("ME").last() for name, value in estimator_daily.items()
    }

    rows = []
    for estimator_name, feature in monthly_features.items():
        # LOOKAHEAD FIREWALL: month-end t-1 signal predicts month-t outcomes.
        signal = feature.shift(1)
        for date in outcomes["ret"].index:
            for ticker in UNIVERSE:
                row = {
                    "date": date,
                    "ticker": ticker,
                    "estimator": estimator_name,
                    "signal": signal.at[date, ticker]
                    if date in signal.index and ticker in signal.columns
                    else np.nan,
                }
                for target_name, target_df in outcomes.items():
                    row[target_name] = (
                        target_df.at[date, ticker]
                        if date in target_df.index and ticker in target_df.columns
                        else np.nan
                    )
                rows.append(row)

    panel = pd.DataFrame(rows).dropna(subset=["signal", "ret", "rv_ann", "left_tail_loss"])
    counts = panel.groupby(["estimator", "date"])["ticker"].nunique()
    valid_pairs = counts[counts >= MIN_ASSETS_PER_MONTH].index
    valid_index = pd.MultiIndex.from_frame(panel[["estimator", "date"]])
    panel = panel[valid_index.isin(valid_pairs)].copy()

    meta = {
        "source": "yfinance adjusted close, auto_adjust=True; overlapping tickers reused from local K1507 cache when present",
        "universe": UNIVERSE,
        "coverage": coverage,
        "monthly_start": str(panel["date"].min().date()),
        "monthly_end": str(panel["date"].max().date()),
        "n_months": int(panel["date"].nunique()),
        "n_panel_rows": int(len(panel)),
        "min_assets_per_estimator_month": int(counts.loc[valid_pairs].min()),
        "max_assets_per_estimator_month": int(counts.loc[valid_pairs].max()),
    }
    return panel, meta


def newey_west_mean_test(values: pd.Series | np.ndarray, lags: int = NW_LAG) -> dict:
    from scipy import stats

    x = pd.Series(values).dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 5:
        return {"mean": np.nan, "se": np.nan, "t": np.nan, "p": np.nan, "n": n}
    mean = float(x.mean())
    dev = x - mean
    gamma0 = float(np.dot(dev, dev) / n)
    lrv = gamma0
    max_lag = min(lags, n - 1)
    for lag in range(1, max_lag + 1):
        cov = float(np.dot(dev[lag:], dev[:-lag]) / n)
        weight = 1.0 - lag / (max_lag + 1.0)
        lrv += 2.0 * weight * cov
    se = math.sqrt(max(lrv, 0.0) / n)
    t_stat = mean / se if se > 0 else np.nan
    p_val = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1)) if np.isfinite(t_stat) else np.nan
    return {"mean": mean, "se": float(se), "t": float(t_stat), "p": float(p_val), "n": int(n)}


def block_bootstrap_mean_ci(
    values: pd.Series | np.ndarray,
    rng: np.random.Generator,
    block: int = BOOT_BLOCK_MONTHS,
    reps: int = BOOT_REPS,
) -> list[float]:
    x = pd.Series(values).dropna().to_numpy(dtype=float)
    n = len(x)
    if n < block * 2:
        return [float("nan"), float("nan")]
    n_blocks = int(np.ceil(n / block))
    out = np.empty(reps)
    for i in range(reps):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) % n for s in starts])[:n]
        out[i] = x[idx].mean()
    return [float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975))]


def summarize_spread(series: pd.Series, target: str, rng: np.random.Generator) -> dict:
    test = newey_west_mean_test(series)
    ci = block_bootstrap_mean_ci(series, rng)
    out = {
        "mean": test["mean"],
        "hac_se": test["se"],
        "hac_t": test["t"],
        "p_value": test["p"],
        "bootstrap_ci95_mean": ci,
        "n_months": test["n"],
    }
    if target == "ret":
        out["ann_mean"] = float(test["mean"] * 12.0) if np.isfinite(test["mean"]) else np.nan
    return out


def high_low_spreads(panel: pd.DataFrame, estimator: str, target: str) -> pd.DataFrame:
    rows = []
    sub = panel[panel["estimator"] == estimator]
    for date, g in sub.groupby("date"):
        dat = g[["ticker", "signal", target]].dropna().sort_values("signal")
        if len(dat) < MIN_ASSETS_PER_MONTH:
            continue
        n_leg = max(2, min(TOP_N, len(dat) // 3))
        low = dat.head(n_leg)
        high = dat.tail(n_leg)
        rows.append(
            {
                "date": date,
                "n_assets": int(len(dat)),
                "n_leg": int(n_leg),
                "low_mean": float(low[target].mean()),
                "high_mean": float(high[target].mean()),
                "high_minus_low": float(high[target].mean() - low[target].mean()),
                "high_signal_mean": float(high["signal"].mean()),
                "low_signal_mean": float(low["signal"].mean()),
            }
        )
    return pd.DataFrame(rows).set_index("date").sort_index()


def fama_macbeth_slopes(panel: pd.DataFrame, estimator: str, target: str) -> pd.Series:
    rows = {}
    sub = panel[panel["estimator"] == estimator]
    for date, g in sub.groupby("date"):
        dat = g[["signal", target]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(dat) < MIN_ASSETS_PER_MONTH:
            continue
        x_raw = dat["signal"]
        x_std = x_raw.std(ddof=0)
        if not np.isfinite(x_std) or x_std <= 0:
            continue
        x = ((x_raw - x_raw.mean()) / x_std).to_numpy(dtype=float)
        y = dat[target].to_numpy(dtype=float)
        X = np.column_stack([np.ones(len(dat)), x])
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        rows[date] = float(beta[1])
    return pd.Series(rows).sort_index()


def run_horse_race(panel: pd.DataFrame) -> dict:
    rng = np.random.default_rng(SEED)
    targets = ["ret", "rv_ann", "downside_vol_ann", "left_tail_loss"]
    results = {}
    for estimator in sorted(panel["estimator"].unique()):
        est_results = {}
        for target in targets:
            spreads = high_low_spreads(panel, estimator, target)
            fmb = fama_macbeth_slopes(panel, estimator, target)
            est_results[target] = {
                "high_low_spread": summarize_spread(spreads["high_minus_low"], target, rng),
                "mean_high": float(spreads["high_mean"].mean()),
                "mean_low": float(spreads["low_mean"].mean()),
                "avg_assets_per_month": float(spreads["n_assets"].mean()),
                "avg_leg_size": float(spreads["n_leg"].mean()),
                "fama_macbeth_signal_slope": summarize_spread(fmb, target, rng),
            }
        results[estimator] = est_results
    return results


def verdict_from_results(horse_race: dict) -> tuple[str, dict]:
    return_pass = []
    return_weak = []
    risk_signal = []
    for estimator, block in horse_race.items():
        ret = block["ret"]["high_low_spread"]
        rv = block["rv_ann"]["high_low_spread"]
        tail = block["left_tail_loss"]["high_low_spread"]
        if ret["mean"] > 0 and ret["hac_t"] >= 3.0:
            return_pass.append(estimator)
        elif ret["mean"] > 0 and ret["hac_t"] >= 2.0:
            return_weak.append(estimator)
        if (rv["mean"] > 0 and rv["hac_t"] >= 3.0) or (
            tail["mean"] > 0 and tail["hac_t"] >= 3.0
        ):
            risk_signal.append(estimator)

    if len(return_pass) >= 2:
        verdict = "SUPPORT_ROBUST_PREMIUM"
    elif return_pass:
        verdict = "SINGLE_ESTIMATOR_PREMIUM"
    elif return_weak:
        verdict = "WEAK_RETURN_PREMIUM"
    elif risk_signal:
        verdict = "RISK_SIGNAL_ONLY_NULL_PREMIUM"
    else:
        verdict = "NULL"

    return verdict, {
        "return_pass_estimators": return_pass,
        "return_weak_estimators": return_weak,
        "risk_signal_estimators": risk_signal,
        "success_rule": "robust premium requires >=2 estimators with high-left-asymmetry minus low-left-asymmetry next-month return HAC t >= +3; risk targets are secondary confirmation only",
    }


def make_figures(horse_race: dict) -> list[str]:
    estimators = list(horse_race.keys())
    targets = ["ret", "rv_ann", "downside_vol_ann", "left_tail_loss"]

    ret_ann = [
        horse_race[e]["ret"]["high_low_spread"]["ann_mean"] * 100.0 for e in estimators
    ]
    ret_t = [horse_race[e]["ret"]["high_low_spread"]["hac_t"] for e in estimators]
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(estimators, ret_ann, color="#3b82f6", alpha=0.85)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_ylabel("High-minus-low next-month return, annualized (%)")
    ax.set_title("K1359 return premium horse race")
    ax.tick_params(axis="x", rotation=30)
    for bar, t in zip(bars, ret_t):
        y = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            y,
            f"t={t:.2f}",
            ha="center",
            va="bottom" if y >= 0 else "top",
            fontsize=8,
        )
    fig.tight_layout()
    ret_path = FIG_DIR / "k1359_return_spreads.png"
    fig.savefig(ret_path, dpi=180)
    plt.close(fig)

    matrix = np.array(
        [[horse_race[e][t]["high_low_spread"]["hac_t"] for t in targets] for e in estimators],
        dtype=float,
    )
    fig, ax = plt.subplots(figsize=(8.8, 5.4))
    im = ax.imshow(matrix, cmap="coolwarm", vmin=-4, vmax=4)
    ax.set_xticks(range(len(targets)), labels=targets, rotation=25)
    ax.set_yticks(range(len(estimators)), labels=estimators)
    ax.set_title("K1359 HAC t-stat heatmap")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, f"{matrix[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=0.78, label="HAC t")
    fig.tight_layout()
    heat_path = FIG_DIR / "k1359_tstat_heatmap.png"
    fig.savefig(heat_path, dpi=180)
    plt.close(fig)

    return [str(ret_path.relative_to(HERE)), str(heat_path.relative_to(HERE))]


def run_experiment(refresh: bool = False) -> dict:
    panel, data_meta = build_panel(refresh)
    horse_race = run_horse_race(panel)
    verdict, decision = verdict_from_results(horse_race)
    figures = make_figures(horse_race)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "tailasym5 joimskews tail-asymmetry estimator horse race",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "methodology_type": "empirical_returns_only_proxy_test",
        "verdict": verdict,
        "data": data_meta,
        "config": {
            "seed": SEED,
            "start": START,
            "rolling_window_days": ROLL_WINDOW,
            "min_rolling_obs": MIN_ROLL_OBS,
            "min_assets_per_month": MIN_ASSETS_PER_MONTH,
            "top_bottom_leg_max_n": TOP_N,
            "nw_lag_months": NW_LAG,
            "bootstrap_reps": BOOT_REPS,
            "bootstrap_block_months": BOOT_BLOCK_MONTHS,
            "timing_rule": "daily trailing estimator -> month-end value -> signal.shift(1) -> current-month outcomes",
            "primary_inference_unit": "monthly high-minus-low spread or monthly Fama-MacBeth slope; no pooled ticker-month t-test",
            "harvey_threshold": "|t| >= 3 for return-premium discovery claims",
        },
        "literature": LITERATURE,
        "decision": decision,
        "estimators": {
            "bad_skew": "negative 63d rolling realized skewness",
            "bad_trimmed_skew": "negative skewness after dropping 5%/95% tail observations inside the rolling window",
            "bad_winsor_skew": "negative skewness after 5%/95% winsorization inside the rolling window",
            "semivar_log_ratio": "log downside semivariance / upside semivariance",
            "tail_mean_gap": "left 5% average loss minus right 5% average gain",
            "max_loss_gain_gap": "absolute worst daily loss minus best daily gain",
        },
        "targets": {
            "ret": "same-month ETF return predicted by previous-month-end signal",
            "rv_ann": "same-month realized volatility, annualized from daily squared log returns",
            "downside_vol_ann": "same-month realized downside volatility, annualized",
            "left_tail_loss": "same-month worst daily log-return loss",
        },
        "horse_race": horse_race,
        "figures": figures,
        "limitations": [
            "This is a returns-only proxy test. It does not observe option-implied skew, skew swaps, or securities-lending constraints.",
            "ETF universe has only nine assets; cross-sectional legs contain two or three ETFs per month, so inference is based on time-series variation of basket spreads.",
            "Monthly tests are before transaction costs and are not a launch-ready strategy backtest.",
            "The sample starts only when ETF histories become available; UUP, FXY, and HYG inception dates limit early coverage.",
        ],
    }
    (HERE / "K1359_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    panel.to_csv(HERE / "K1359_panel.csv", index=False)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh yfinance caches")
    args = parser.parse_args()
    results = run_experiment(refresh=args.refresh)
    summary = {
        "experiment_id": results["experiment_id"],
        "verdict": results["verdict"],
        "period": [results["data"]["monthly_start"], results["data"]["monthly_end"]],
        "n_months": results["data"]["n_months"],
        "return_pass_estimators": results["decision"]["return_pass_estimators"],
        "risk_signal_estimators": results["decision"]["risk_signal_estimators"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
