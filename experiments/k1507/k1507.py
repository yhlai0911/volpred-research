#!/usr/bin/env python3
"""
K1507: Returns-only volatility-skew proxy and next-month ETF cross-section.

This experiment does not have option IV surfaces or stock-borrow data. It tests a
restricted proxy question: can lagged downside realized skewness measures, built
only from ETF returns, stand in for the option-smirk / borrow-fee channel in a
small liquid ETF universe?
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


for font_name in ["Arial Unicode MS", "PingFang TC", "Heiti TC", "Hiragino Sans GB"]:
    try:
        font_manager.findfont(font_name, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [font_name]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

SEED = 20260616
START = "2007-01-01"
ROLL_WINDOW = 63
MIN_ROLL_OBS = 50
MIN_ASSETS_PER_MONTH = 12
TERCILE_Q = 0.30
BOOT_REPS = 5000
BOOT_BLOCK_MONTHS = 6
OOS_START = "2018-01-31"

TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "EFA",
    "EEM",
    "XLF",
    "XLK",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLU",
    "XLB",
    "GLD",
    "TLT",
    "IEF",
    "HYG",
    "LQD",
    "VNQ",
    "USO",
]

LITERATURE = [
    {
        "citation": "Xing, Zhang, and Zhao (2010), What Does Individual Option Volatility Smirk Tell Us About Future Equity Returns?, JFQA",
        "url": "https://ideas.repec.org/a/cup/jfinqa/v45y2010i03p641-662_00.html",
        "role": "option smirk predicts lower future stock returns in individual-stock cross-section",
    },
    {
        "citation": "Muravyev, Pearson, and Pollet (2025), Why Does Options Market Information Predict Stock Returns?",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2851560",
        "role": "borrow fees explain much of option-signal return predictability",
    },
    {
        "citation": "Ofek, Richardson, and Whitelaw (2004), Limited Arbitrage and Short Sales Restrictions, NBER WP 9423",
        "url": "https://www.nber.org/papers/w9423",
        "role": "short-sale constraints and options-market parity deviations",
    },
    {
        "citation": "Harvey, Liu, and Zhu (2016), ... and the Cross-Section of Expected Returns, RFS",
        "url": "https://academic.oup.com/rfs/article/29/1/5/1843824",
        "role": "multiple-testing t-stat threshold for cross-sectional return predictors",
    },
]


@dataclass(frozen=True)
class SeriesStats:
    mean_monthly: float
    ann_mean: float
    t_hac: float | None
    ci95: list[float] | None
    n_months: int


def download_close(ticker: str, refresh: bool) -> pd.Series:
    cache = DATA_DIR / f"{ticker}.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, parse_dates=["Date"]).set_index("Date")["Close"].sort_index()

    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=START, auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError(f"empty yfinance history for {ticker}")
    close = hist["Close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(
        cache, index=False
    )
    return close


def drop_partial_current_month(monthly: pd.Series, last_obs: pd.Timestamp) -> pd.Series:
    today = pd.Timestamp.today().normalize()
    if last_obs.year == today.year and last_obs.month == today.month:
        return monthly.iloc[:-1]
    return monthly


def load_prices(refresh: bool) -> pd.DataFrame:
    closes = {}
    for ticker in TICKERS:
        closes[ticker] = download_close(ticker, refresh)
    close_df = pd.DataFrame(closes).sort_index()
    return close_df


def rolling_downside_upside_spread(log_returns: pd.DataFrame) -> pd.DataFrame:
    downside = log_returns.mask(log_returns > 0.0, 0.0)
    upside = log_returns.mask(log_returns < 0.0, 0.0)
    downside_vol = np.sqrt((downside.pow(2)).rolling(ROLL_WINDOW, MIN_ROLL_OBS).mean()) * np.sqrt(252)
    upside_vol = np.sqrt((upside.pow(2)).rolling(ROLL_WINDOW, MIN_ROLL_OBS).mean()) * np.sqrt(252)
    return downside_vol - upside_vol


def rolling_tail_loss(log_returns: pd.DataFrame) -> pd.DataFrame:
    return -log_returns.rolling(ROLL_WINDOW, MIN_ROLL_OBS).quantile(0.05)


def zscore_cross_section(frame: pd.DataFrame) -> pd.DataFrame:
    mean = frame.mean(axis=1)
    std = frame.std(axis=1, ddof=0).replace(0.0, np.nan)
    return frame.sub(mean, axis=0).div(std, axis=0)


def build_panel(refresh: bool) -> tuple[pd.DataFrame, dict]:
    close = load_prices(refresh)
    monthly_close = close.resample("ME").last()
    last_obs = close.dropna(how="all").index.max()
    monthly_close = monthly_close.apply(lambda s: drop_partial_current_month(s, last_obs))
    monthly_ret = monthly_close.pct_change()
    next_month_ret = monthly_ret.shift(-1)

    log_returns = np.log(close / close.shift(1))
    realized_skew = log_returns.rolling(ROLL_WINDOW, MIN_ROLL_OBS).skew()
    downside_spread = rolling_downside_upside_spread(log_returns)
    tail_loss = rolling_tail_loss(log_returns)
    realized_vol = log_returns.rolling(ROLL_WINDOW, MIN_ROLL_OBS).std() * np.sqrt(252)
    momentum_21 = close.pct_change(21)

    # All predictors are resampled at month-end t; target is explicitly t+1.
    monthly_features = {
        "bad_skew_z": zscore_cross_section((-realized_skew).resample("ME").last()),
        "downside_spread_z": zscore_cross_section(downside_spread.resample("ME").last()),
        "tail_loss_z": zscore_cross_section(tail_loss.resample("ME").last()),
        "realized_vol_z": zscore_cross_section(realized_vol.resample("ME").last()),
        "momentum_21_z": zscore_cross_section(momentum_21.resample("ME").last()),
    }
    skew_proxy = (
        monthly_features["bad_skew_z"]
        + monthly_features["downside_spread_z"]
        + monthly_features["tail_loss_z"]
    ) / 3.0
    monthly_features["skew_proxy_z"] = zscore_cross_section(skew_proxy)

    rows = []
    for date in monthly_ret.index:
        for ticker in TICKERS:
            row = {
                "date": date,
                "ticker": ticker,
                "next_ret": next_month_ret.at[date, ticker]
                if ticker in next_month_ret.columns and date in next_month_ret.index
                else np.nan,
            }
            for name, feature_df in monthly_features.items():
                row[name] = (
                    feature_df.at[date, ticker]
                    if ticker in feature_df.columns and date in feature_df.index
                    else np.nan
                )
            rows.append(row)

    panel = pd.DataFrame(rows).dropna()
    counts = panel.groupby("date")["ticker"].nunique()
    valid_dates = counts[counts >= MIN_ASSETS_PER_MONTH].index
    panel = panel[panel["date"].isin(valid_dates)].copy()

    data_meta = {
        "source": "yfinance adjusted close, auto_adjust=True",
        "tickers": TICKERS,
        "n_tickers_configured": len(TICKERS),
        "monthly_start": str(panel["date"].min().date()),
        "monthly_end": str(panel["date"].max().date()),
        "n_months": int(panel["date"].nunique()),
        "n_panel_rows": int(len(panel)),
        "min_assets_per_month": int(counts.loc[valid_dates].min()),
        "max_assets_per_month": int(counts.loc[valid_dates].max()),
        "rolling_window_days": ROLL_WINDOW,
        "min_rolling_obs": MIN_ROLL_OBS,
        "oos_start": OOS_START,
    }
    return panel, data_meta


def hac_tstat_mean(values: pd.Series | np.ndarray, lags: int = 3) -> tuple[float, float, list[float]]:
    x = pd.Series(values).dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 3:
        return float(np.nan), float(np.nan), [float(np.nan), float(np.nan)]
    centered = x - x.mean()
    gamma0 = float(np.dot(centered, centered) / n)
    lrv = gamma0
    max_lag = min(lags, n - 1)
    for lag in range(1, max_lag + 1):
        cov = float(np.dot(centered[lag:], centered[:-lag]) / n)
        weight = 1.0 - lag / (max_lag + 1.0)
        lrv += 2.0 * weight * cov
    se = np.sqrt(max(lrv, 0.0) / n)
    mean = float(x.mean())
    if se == 0:
        return mean, float(np.nan), [float(np.nan), float(np.nan)]
    t_stat = mean / se
    ci = [float(mean - 1.96 * se), float(mean + 1.96 * se)]
    return mean, float(t_stat), ci


def moving_block_bootstrap_ci(values: pd.Series, rng: np.random.Generator) -> list[float]:
    x = values.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < BOOT_BLOCK_MONTHS:
        return [float(np.nan), float(np.nan)]
    n_blocks = int(np.ceil(n / BOOT_BLOCK_MONTHS))
    max_start = n - BOOT_BLOCK_MONTHS
    means = np.empty(BOOT_REPS)
    for rep in range(BOOT_REPS):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sample = np.concatenate([x[s : s + BOOT_BLOCK_MONTHS] for s in starts])[:n]
        means[rep] = sample.mean()
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def tercile_spread(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, g in panel.groupby("date"):
        g = g.dropna(subset=["skew_proxy_z", "next_ret"]).copy()
        if len(g) < MIN_ASSETS_PER_MONTH:
            continue
        n_leg = max(3, int(np.floor(len(g) * TERCILE_Q)))
        ranked = g.sort_values("skew_proxy_z")
        low = ranked.head(n_leg)
        high = ranked.tail(n_leg)
        rows.append(
            {
                "date": date,
                "n_assets": int(len(g)),
                "low_proxy_ret": float(low["next_ret"].mean()),
                "high_proxy_ret": float(high["next_ret"].mean()),
                "high_minus_low": float(high["next_ret"].mean() - low["next_ret"].mean()),
                "low_minus_high": float(low["next_ret"].mean() - high["next_ret"].mean()),
                "high_avg_proxy": float(high["skew_proxy_z"].mean()),
                "low_avg_proxy": float(low["skew_proxy_z"].mean()),
            }
        )
    return pd.DataFrame(rows).set_index("date").sort_index()


def cross_sectional_ols(g: pd.DataFrame, y_col: str, x_cols: list[str]) -> dict[str, float] | None:
    dat = g[[y_col] + x_cols].dropna()
    if len(dat) < len(x_cols) + 4:
        return None
    y = dat[y_col].to_numpy(dtype=float)
    x = dat[x_cols].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(dat)), x])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    return {"intercept": float(beta[0]), **{col: float(beta[i + 1]) for i, col in enumerate(x_cols)}}


def fama_macbeth(panel: pd.DataFrame, x_cols: list[str]) -> pd.DataFrame:
    rows = []
    for date, g in panel.groupby("date"):
        coefs = cross_sectional_ols(g, "next_ret", x_cols)
        if coefs is None:
            continue
        coefs["date"] = date
        rows.append(coefs)
    return pd.DataFrame(rows).set_index("date").sort_index()


def monthly_rank_ic(panel: pd.DataFrame) -> pd.Series:
    rows = []
    for date, g in panel.groupby("date"):
        dat = g[["skew_proxy_z", "next_ret"]].dropna()
        if len(dat) < MIN_ASSETS_PER_MONTH:
            continue
        rows.append((date, dat["skew_proxy_z"].corr(dat["next_ret"], method="spearman")))
    return pd.Series({date: val for date, val in rows}).sort_index()


def summarize_series(series: pd.Series, rng: np.random.Generator) -> SeriesStats:
    mean, t_stat, hac_ci = hac_tstat_mean(series, lags=3)
    boot_ci = moving_block_bootstrap_ci(series, rng)
    # Report bootstrap CI for the monthly mean; HAC t is kept as the formal t-stat.
    ci = boot_ci if all(np.isfinite(boot_ci)) else hac_ci
    return SeriesStats(
        mean_monthly=float(mean),
        ann_mean=float(mean * 12.0),
        t_hac=float(t_stat) if np.isfinite(t_stat) else None,
        ci95=ci,
        n_months=int(series.dropna().shape[0]),
    )


def summarize_rank_ic(series: pd.Series, rng: np.random.Generator) -> dict:
    mean, t_stat, hac_ci = hac_tstat_mean(series, lags=3)
    boot_ci = moving_block_bootstrap_ci(series, rng)
    ci = boot_ci if all(np.isfinite(boot_ci)) else hac_ci
    return {
        "mean_monthly_ic": float(mean),
        "hac_t": float(t_stat) if np.isfinite(t_stat) else None,
        "ci95_mean_ic": ci,
        "n_months": int(series.dropna().shape[0]),
    }


def coefficient_summary(coefs: pd.DataFrame, rng: np.random.Generator) -> dict[str, dict]:
    out = {}
    for col in coefs.columns:
        stats = summarize_series(coefs[col], rng)
        out[col] = {
            "mean_monthly_coef": stats.mean_monthly,
            "ann_coef": stats.ann_mean,
            "hac_t": stats.t_hac,
            "ci95_monthly_mean": stats.ci95,
            "n_months": stats.n_months,
        }
    return out


def subset_panel(panel: pd.DataFrame, sample: str) -> pd.DataFrame:
    if sample == "full":
        return panel.copy()
    if sample == "pre_2018":
        return panel[panel["date"] < pd.Timestamp(OOS_START)].copy()
    if sample == "post_2018":
        return panel[panel["date"] >= pd.Timestamp(OOS_START)].copy()
    raise ValueError(sample)


def run_tests(panel: pd.DataFrame) -> dict:
    rng = np.random.default_rng(SEED)
    results = {}
    for sample in ["full", "pre_2018", "post_2018"]:
        p = subset_panel(panel, sample)
        spread = tercile_spread(p)
        fmb_simple = fama_macbeth(p, ["skew_proxy_z"])
        fmb_controls = fama_macbeth(p, ["skew_proxy_z", "realized_vol_z", "momentum_21_z"])
        ic = monthly_rank_ic(p)

        hm = summarize_series(spread["high_minus_low"], rng)
        lm = summarize_series(spread["low_minus_high"], rng)
        results[sample] = {
            "n_months": int(p["date"].nunique()),
            "n_panel_rows": int(len(p)),
            "tercile_spread": {
                "high_minus_low": hm.__dict__,
                "low_minus_high": lm.__dict__,
                "mean_high_proxy_next_ret": float(spread["high_proxy_ret"].mean()),
                "mean_low_proxy_next_ret": float(spread["low_proxy_ret"].mean()),
                "avg_assets_per_month": float(spread["n_assets"].mean()),
            },
            "fama_macbeth_simple": coefficient_summary(fmb_simple, rng),
            "fama_macbeth_controls": coefficient_summary(fmb_controls, rng),
            "rank_ic": summarize_rank_ic(ic, rng),
        }
    return results


def make_figures(panel: pd.DataFrame, tests: dict) -> None:
    spread = tercile_spread(panel)
    cum = (1.0 + spread[["high_proxy_ret", "low_proxy_ret"]]).cumprod()
    factor = (1.0 + spread["low_minus_high"]).cumprod()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    axes[0].plot(cum.index, cum["high_proxy_ret"], label="High proxy basket")
    axes[0].plot(cum.index, cum["low_proxy_ret"], label="Low proxy basket")
    axes[0].set_title("Next-month ETF basket wealth")
    axes[0].set_ylabel("Growth of $1")
    axes[0].legend(frameon=False)
    axes[1].plot(factor.index, factor, color="#4c78a8")
    axes[1].axhline(1.0, color="black", linewidth=0.8)
    axes[1].set_title("Low-minus-high proxy factor")
    axes[1].set_ylabel("Growth of $1")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1507_tercile_factor.png", dpi=180)
    plt.close(fig)

    samples = ["full", "pre_2018", "post_2018"]
    ann = [
        tests[s]["tercile_spread"]["high_minus_low"]["ann_mean"] * 100.0
        for s in samples
    ]
    tvals = [
        tests[s]["tercile_spread"]["high_minus_low"]["t_hac"] or np.nan
        for s in samples
    ]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    bars = ax.bar(samples, ann, color=["#4c78a8", "#f58518", "#54a24b"])
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_ylabel("High-minus-low annualized mean (%)")
    ax.set_title("Underperformance test by sample")
    for bar, tval in zip(bars, tvals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"t={tval:.2f}",
            ha="center",
            va="bottom" if bar.get_height() >= 0 else "top",
            fontsize=9,
        )
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1507_sample_spreads.png", dpi=180)
    plt.close(fig)


def run_experiment(refresh: bool) -> dict:
    panel, data_meta = build_panel(refresh)
    tests = run_tests(panel)
    make_figures(panel, tests)

    full_hml = tests["full"]["tercile_spread"]["high_minus_low"]
    full_fmb = tests["full"]["fama_macbeth_controls"]["skew_proxy_z"]
    verdict = "NULL"
    if full_hml["t_hac"] is not None and full_hml["t_hac"] < -3.0 and full_fmb["hac_t"] < -3.0:
        verdict = "SUPPORT"
    elif full_hml["t_hac"] is not None and full_hml["t_hac"] < -2.0:
        verdict = "WEAK_SUPPORT"

    results = {
        "experiment_id": "k1507",
        "title": "Returns-only volatility-skew proxy as ETF cross-section predictor",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_type": "empirical_proxy_test",
        "verdict": verdict,
        "data": data_meta,
        "config": {
            "seed": SEED,
            "start": START,
            "rolling_window_days": ROLL_WINDOW,
            "min_rolling_obs": MIN_ROLL_OBS,
            "tercile_quantile": TERCILE_Q,
            "bootstrap_reps": BOOT_REPS,
            "bootstrap_block_months": BOOT_BLOCK_MONTHS,
            "oos_start": OOS_START,
            "timing_rule": "month-end t features predict month t+1 returns; no month t+1 return is used in feature construction",
            "proxy_definition": "cross-sectional z-score average of lagged negative realized skewness, downside-upside realized-vol spread, and 5% left-tail loss",
            "harvey_threshold": "|t| > 3 for cross-sectional return predictor claims",
        },
        "literature": LITERATURE,
        "tests": tests,
        "limitations": [
            "No option IV surface and no stock-borrow fee data are used; the skew_proxy_z variable is a returns-only proxy, not observed option-implied skew or lending fee.",
            "The universe is liquid ETFs, not individual stocks; ETF borrow constraints are generally weaker than hard-to-borrow single names.",
            "Monthly factor returns are reported before transaction costs and are used only as a hypothesis test, not as a launch-ready strategy.",
            "Full-sample standardization is cross-sectional within each month, but no fitted prediction model is trained on future returns.",
        ],
    }
    (HERE / "k1507_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    panel.to_csv(HERE / "k1507_panel.csv", index=False)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh yfinance cache")
    args = parser.parse_args()
    results = run_experiment(args.refresh)
    full = results["tests"]["full"]
    print(
        json.dumps(
            {
                "experiment_id": results["experiment_id"],
                "verdict": results["verdict"],
                "period": [results["data"]["monthly_start"], results["data"]["monthly_end"]],
                "n_months": results["data"]["n_months"],
                "high_minus_low_ann": full["tercile_spread"]["high_minus_low"]["ann_mean"],
                "high_minus_low_t": full["tercile_spread"]["high_minus_low"]["t_hac"],
                "fmb_control_skew_t": full["fama_macbeth_controls"]["skew_proxy_z"]["hac_t"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
