#!/usr/bin/env python3
"""K1361: Gaming / betting basket volatility spillover pilot.

The experiment asks whether public gaming, esports, and sports-betting
equity proxies become volatility transmitters during market stress, or whether
they are simply high-beta diversification sinks.

All predictive tests use lagged features (`shift(1)`).  The Diebold-Yilmaz
connectedness block is descriptive over trailing 21-day log variance proxies;
it does not claim causal identification.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.tools import add_constant
from statsmodels.tools.sm_exceptions import ValueWarning
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=ValueWarning)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

EXPERIMENT_ID = "K1361"
SEED = 42
START = "2016-01-01"
RV_WINDOW = 21
MIN_RV_OBS = 15
ROLLING_WINDOW = 252
ROLLING_STEP = 21
FEVD_HORIZON = 10
CORR_WINDOW = 63
HAC_LAGS = 5
BOOT_REPS = 1000
EPS = 1e-10

RAW_TICKERS = {
    "ESPO": "gaming ETF",
    "HERO": "gaming ETF",
    "NERD": "gaming ETF",
    "GAMR": "gaming ETF",
    "DKNG": "sports betting / gaming equity",
    "FLUT": "sports betting equity",
    "HOOD": "retail trading / betting-adjacent equity",
    "QQQ": "growth benchmark",
    "ARKK": "risk-on innovation benchmark",
    "BTC-USD": "crypto risk-on benchmark",
    "SPY": "market benchmark and trading calendar",
}

SERIES = {
    "GAMING_ETF": {
        "members": ["ESPO", "HERO", "NERD", "GAMR"],
        "min_members": 2,
        "label": "Gaming/esports ETF basket",
    },
    "BETTING_FINTECH": {
        "members": ["DKNG", "FLUT", "HOOD"],
        "min_members": 2,
        "label": "Sports-betting / trading-app basket",
    },
    "QQQ": {"members": ["QQQ"], "min_members": 1, "label": "QQQ"},
    "ARKK": {"members": ["ARKK"], "min_members": 1, "label": "ARKK"},
    "BTC": {"members": ["BTC-USD"], "min_members": 1, "label": "BTC-USD"},
    "SPY": {"members": ["SPY"], "min_members": 1, "label": "SPY"},
}

CONNECTEDNESS_SERIES = ["GAMING_ETF", "BETTING_FINTECH", "QQQ", "ARKK", "BTC", "SPY"]
LEAD_SOURCES = ["GAMING_ETF", "BETTING_FINTECH"]
LEAD_TARGETS = ["QQQ", "ARKK", "BTC", "SPY"]

LITERATURE = [
    {
        "citation": "Papathanasiou (2026), Reevaluating Diversification: The Evolving Role of Gaming in Market Turmoil, Journal of Alternative Investments",
        "url": "https://www.pm-research.com/content/iijaltinv/28/4/74",
        "role": "motivates testing gaming as a sector-level volatility spillover source during market turmoil",
    },
    {
        "citation": "Diebold and Yilmaz (2012), Better to give than to receive: Predictive directional measurement of volatility spillovers, International Journal of Forecasting",
        "url": "https://ideas.repec.org/a/eee/intfor/v28y2012i1p57-66.html",
        "role": "canonical generalized VAR connectedness / directional spillover framework",
    },
    {
        "citation": "Barunik and Krehlik (2018), Measuring the frequency dynamics of financial connectedness and systemic risk, Journal of Financial Econometrics",
        "url": "https://ideas.repec.org/a/oup/jfinec/v16y2018i2p271-296..html",
        "role": "supports treating connectedness as time-varying and stress-regime dependent",
    },
    {
        "citation": "Balli, Balli, Dang, and Gabauer (2023), Contemporaneous and lagged R2 decomposed connectedness approach, Finance Research Letters",
        "url": "https://ideas.repec.org/a/eee/finlet/v57y2023ics1544612323005408.html",
        "role": "motivates separating contemporaneous diversification from lagged predictive spillovers",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cache_name(ticker: str) -> str:
    return ticker.replace("^", "").replace("=", "_").replace("-", "_") + ".csv"


def read_cached_close(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"])
    if "Close" not in df.columns:
        raise ValueError(f"cache lacks Close column: {path}")
    out = df.set_index("Date")["Close"].sort_index()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out[~out.index.duplicated(keep="last")]


def load_close(ticker: str, refresh: bool) -> pd.Series:
    cache = DATA_DIR / cache_name(ticker)
    if cache.exists() and not refresh:
        return read_cached_close(cache)

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


def load_prices(refresh: bool) -> tuple[pd.DataFrame, dict]:
    closes: dict[str, pd.Series] = {}
    failures: dict[str, str] = {}
    for ticker in RAW_TICKERS:
        try:
            closes[ticker] = load_close(ticker, refresh=refresh)
        except Exception as exc:  # keep the experiment runnable if a minor proxy vanishes
            failures[ticker] = str(exc)

    if "SPY" not in closes:
        raise RuntimeError("SPY is required as the trading calendar")

    calendar = closes["SPY"].dropna().index
    prices = pd.DataFrame({k: s.reindex(calendar).ffill() for k, s in closes.items()})
    prices.index.name = "Date"
    prices.to_csv(DATA_DIR / "close_prices_yfinance.csv")

    coverage = {}
    for ticker, label in RAW_TICKERS.items():
        s = prices[ticker].dropna() if ticker in prices else pd.Series(dtype=float)
        coverage[ticker] = {
            "role": label,
            "first": str(s.index.min().date()) if not s.empty else None,
            "last": str(s.index.max().date()) if not s.empty else None,
            "n_daily_prices": int(len(s)),
            "load_error": failures.get(ticker),
        }
    return prices, coverage


def build_basket_returns(raw_returns: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    baskets = pd.DataFrame(index=raw_returns.index)
    basket_coverage = {}
    for name, cfg in SERIES.items():
        members = [m for m in cfg["members"] if m in raw_returns.columns]
        available = raw_returns[members].notna().sum(axis=1)
        basket = raw_returns[members].mean(axis=1, skipna=True)
        basket[available < int(cfg["min_members"])] = np.nan
        baskets[name] = basket
        ok = basket.dropna()
        basket_coverage[name] = {
            "label": cfg["label"],
            "members_requested": cfg["members"],
            "members_available": members,
            "min_members": int(cfg["min_members"]),
            "first_return": str(ok.index.min().date()) if not ok.empty else None,
            "last_return": str(ok.index.max().date()) if not ok.empty else None,
            "n_daily_returns": int(len(ok)),
            "median_member_count": float(available.loc[ok.index].median()) if not ok.empty else None,
        }
    baskets.to_csv(DATA_DIR / "daily_basket_returns.csv")
    return baskets, basket_coverage


def make_log_rv(basket_returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    variance = basket_returns.rolling(RV_WINDOW, min_periods=MIN_RV_OBS).var() * 252.0
    log_rv = np.log(variance + EPS)
    variance.to_csv(DATA_DIR / "daily_basket_rv21_variance.csv")
    log_rv.to_csv(DATA_DIR / "daily_basket_log_rv21.csv")
    return variance, log_rv


def zscore(df: pd.DataFrame) -> pd.DataFrame:
    std = df.std(ddof=1).replace(0.0, np.nan)
    return (df - df.mean()) / std


def select_lag(data: pd.DataFrame, maxlags: int = 5) -> int:
    maxlags = min(maxlags, max(1, len(data) // 80))
    if maxlags <= 1:
        return 1
    try:
        order = VAR(data).select_order(maxlags=maxlags)
        lag = order.selected_orders.get("aic")
        if lag is None or lag < 1:
            return 1
        return int(min(lag, maxlags))
    except Exception:
        return 1


def generalized_fevd(var_result, horizon: int = FEVD_HORIZON) -> pd.DataFrame:
    names = list(var_result.names)
    sigma = np.asarray(var_result.sigma_u, dtype=float)
    ma = var_result.ma_rep(maxn=horizon - 1)
    k = len(names)
    fevd = np.zeros((k, k), dtype=float)

    for i in range(k):
        denom = 0.0
        numer = np.zeros(k, dtype=float)
        for ah in ma:
            row = ah[i, :]
            denom += float(row @ sigma @ row.T)
            for j in range(k):
                sigma_jj = float(sigma[j, j])
                if sigma_jj <= 0:
                    continue
                impact = float(row @ sigma[:, j])
                numer[j] += (impact * impact) / sigma_jj
        if denom > 0:
            fevd[i, :] = numer / denom

    row_sums = fevd.sum(axis=1, keepdims=True)
    row_sums[row_sums <= 0] = 1.0
    fevd = fevd / row_sums
    return pd.DataFrame(fevd, index=names, columns=names)


def connectedness_table(fevd: pd.DataFrame) -> pd.DataFrame:
    off_values = np.array(fevd.to_numpy(dtype=float), copy=True)
    np.fill_diagonal(off_values, 0.0)
    off_diag = pd.DataFrame(off_values, index=fevd.index, columns=fevd.columns)
    from_others = off_diag.sum(axis=1)
    to_others = off_diag.sum(axis=0)
    net = to_others - from_others
    return pd.DataFrame(
        {
            "from_others": from_others,
            "to_others": to_others,
            "net": net,
        }
    )


def fit_connectedness(data: pd.DataFrame, lag: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    clean = zscore(data).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 120:
        raise ValueError("not enough observations for VAR connectedness")
    lag = select_lag(clean) if lag is None else lag
    result = VAR(clean).fit(lag)
    fevd = generalized_fevd(result, horizon=FEVD_HORIZON)
    table = connectedness_table(fevd)
    return fevd, table, lag


def rolling_connectedness(log_rv: pd.DataFrame, spy_variance: pd.Series) -> tuple[pd.DataFrame, dict]:
    data = log_rv[CONNECTEDNESS_SERIES].dropna(how="any")
    spy_rv = np.sqrt(spy_variance.reindex(data.index)).replace([np.inf, -np.inf], np.nan)
    stress_hi = float(spy_rv.quantile(0.75))
    stress_lo = float(spy_rv.quantile(0.25))

    rows = []
    for end in range(ROLLING_WINDOW, len(data) + 1, ROLLING_STEP):
        window = data.iloc[end - ROLLING_WINDOW : end]
        end_date = data.index[end - 1]
        try:
            _, table, lag = fit_connectedness(window, lag=1)
        except Exception:
            continue
        regime_value = float(spy_rv.loc[end_date]) if pd.notna(spy_rv.loc[end_date]) else np.nan
        if regime_value >= stress_hi:
            regime = "stress"
        elif regime_value <= stress_lo:
            regime = "calm"
        else:
            regime = "normal"
        row = {
            "date": end_date,
            "regime": regime,
            "spy_rv": regime_value,
            "lag": lag,
            "total_connectedness": float(table["from_others"].mean()),
        }
        for name in CONNECTEDNESS_SERIES:
            row[f"{name}_net"] = float(table.loc[name, "net"])
            row[f"{name}_to"] = float(table.loc[name, "to_others"])
            row[f"{name}_from"] = float(table.loc[name, "from_others"])
        rows.append(row)

    out = pd.DataFrame(rows)
    if not out.empty:
        out.to_csv(DATA_DIR / "rolling_connectedness.csv", index=False)
    thresholds = {"stress_spy_rv_q75": stress_hi, "calm_spy_rv_q25": stress_lo}
    return out, thresholds


def welch_diff(stress: pd.Series, calm: pd.Series) -> dict:
    stress = pd.Series(stress, dtype=float).dropna()
    calm = pd.Series(calm, dtype=float).dropna()
    out = {
        "stress_n": int(len(stress)),
        "calm_n": int(len(calm)),
        "stress_mean": float(stress.mean()) if len(stress) else None,
        "calm_mean": float(calm.mean()) if len(calm) else None,
        "diff_stress_minus_calm": None,
        "welch_t": None,
        "p_value": None,
        "bootstrap_ci": None,
        "bootstrap_p_diff_gt_0": None,
    }
    if len(stress) < 3 or len(calm) < 3:
        return out
    diff = float(stress.mean() - calm.mean())
    t_stat, p_val = stats.ttest_ind(stress, calm, equal_var=False)
    rng = np.random.default_rng(SEED)
    boot = []
    for _ in range(BOOT_REPS):
        s = rng.choice(stress.to_numpy(), size=len(stress), replace=True)
        c = rng.choice(calm.to_numpy(), size=len(calm), replace=True)
        boot.append(float(np.mean(s) - np.mean(c)))
    boot_arr = np.asarray(boot)
    out.update(
        {
            "diff_stress_minus_calm": diff,
            "welch_t": float(t_stat),
            "p_value": float(p_val),
            "bootstrap_ci": [float(np.quantile(boot_arr, 0.025)), float(np.quantile(boot_arr, 0.975))],
            "bootstrap_p_diff_gt_0": float(np.mean(boot_arr > 0)),
        }
    )
    return out


def summarize_rolling_connectedness(rolling: pd.DataFrame) -> dict:
    summary = {}
    if rolling.empty:
        return summary
    for name in CONNECTEDNESS_SERIES:
        col = f"{name}_net"
        summary[name] = welch_diff(
            rolling.loc[rolling["regime"] == "stress", col],
            rolling.loc[rolling["regime"] == "calm", col],
        )
    return summary


def hac_regression(y: pd.Series, x: pd.DataFrame) -> dict:
    df = pd.concat([y.rename("target"), x], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 120:
        return {"n": int(len(df)), "error": "too_few_observations"}
    df = (df - df.mean()) / df.std(ddof=1).replace(0.0, np.nan)
    df = df.dropna()
    y_arr = df["target"]
    x_arr = add_constant(df.drop(columns=["target"]), has_constant="add")
    model = OLS(y_arr, x_arr).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return {
        "n": int(len(df)),
        "r2": float(model.rsquared),
        "params": {k: float(v) for k, v in model.params.items()},
        "tvalues": {k: float(v) for k, v in model.tvalues.items()},
        "pvalues": {k: float(v) for k, v in model.pvalues.items()},
    }


def lead_lag_tests(log_rv: pd.DataFrame) -> dict:
    results = {}
    for source in LEAD_SOURCES:
        for target in LEAD_TARGETS:
            if source == target:
                continue
            cols = {
                f"{target}_lag1": log_rv[target].shift(1),
                f"{source}_lag1": log_rv[source].shift(1),
            }
            if target != "SPY":
                cols["SPY_lag1"] = log_rv["SPY"].shift(1)
            if target != "QQQ":
                cols["QQQ_lag1"] = log_rv["QQQ"].shift(1)
            key = f"{source}_to_{target}"
            results[key] = hac_regression(log_rv[target], pd.DataFrame(cols, index=log_rv.index))
            results[key]["source_term"] = f"{source}_lag1"
            source_t = results[key].get("tvalues", {}).get(f"{source}_lag1")
            source_b = results[key].get("params", {}).get(f"{source}_lag1")
            results[key]["source_coef"] = source_b
            results[key]["source_t"] = source_t
            results[key]["harvey_pass_positive"] = bool(
                source_b is not None and source_t is not None and source_b > 0 and source_t >= 3.0
            )
    return results


def rolling_correlation_tests(basket_returns: pd.DataFrame, spy_variance: pd.Series) -> dict:
    spy_rv = np.sqrt(spy_variance).replace([np.inf, -np.inf], np.nan)
    stress_hi = float(spy_rv.quantile(0.75))
    stress_lo = float(spy_rv.quantile(0.25))
    summary = {}
    for source in LEAD_SOURCES:
        for target in LEAD_TARGETS:
            key = f"{source}_corr_{target}"
            rc = basket_returns[source].rolling(CORR_WINDOW, min_periods=45).corr(basket_returns[target])
            aligned = pd.DataFrame({"corr": rc, "spy_rv": spy_rv}).dropna()
            stress = aligned.loc[aligned["spy_rv"] >= stress_hi, "corr"]
            calm = aligned.loc[aligned["spy_rv"] <= stress_lo, "corr"]
            summary[key] = welch_diff(stress, calm)
    return summary


def stationarity(log_rv: pd.DataFrame) -> dict:
    out = {}
    for col in log_rv.columns:
        s = log_rv[col].dropna()
        if len(s) < 50:
            out[col] = {"n": int(len(s)), "adf_p": None}
            continue
        stat, p_val = adfuller(s, maxlag=5)[:2]
        out[col] = {"n": int(len(s)), "adf_stat": float(stat), "adf_p": float(p_val)}
    return out


def verdict_from_results(rolling_summary: dict, lead_results: dict, corr_summary: dict) -> tuple[str, list[str]]:
    findings = []
    transmitter_pass = []
    for name in ["GAMING_ETF", "BETTING_FINTECH"]:
        row = rolling_summary.get(name, {})
        t_val = row.get("welch_t")
        diff = row.get("diff_stress_minus_calm")
        stress_mean = row.get("stress_mean")
        if diff is not None and t_val is not None and stress_mean is not None and diff > 0 and stress_mean > 0 and t_val >= 3.0:
            transmitter_pass.append(name)

    lead_pass = [
        key
        for key, row in lead_results.items()
        if row.get("harvey_pass_positive")
    ]
    corr_pass = [
        key
        for key, row in corr_summary.items()
        if row.get("diff_stress_minus_calm") is not None
        and row.get("welch_t") is not None
        and row["diff_stress_minus_calm"] > 0
        and row["welch_t"] >= 3.0
    ]

    findings.append(f"transmitter_pass_count={len(transmitter_pass)} ({', '.join(transmitter_pass) or 'none'})")
    findings.append(f"lagged_vol_harvey_pass_count={len(lead_pass)}")
    findings.append(f"stress_correlation_increase_pass_count={len(corr_pass)}")

    if transmitter_pass and len(lead_pass) >= 2:
        return "PASS_SPILLOVER_TRANSMITTER", findings
    if len(corr_pass) >= 2 and not transmitter_pass and len(lead_pass) <= 1:
        return "DIVERSIFICATION_SINK_PLUS_WEAK_LEAD_NULL_TRANSMITTER", findings
    if transmitter_pass or lead_pass or corr_pass:
        return "MIXED_WEAK_DIAGNOSTIC", findings
    return "NULL_NO_TRANSMITTER_NO_SINK", findings


def write_figures(fevd: pd.DataFrame, rolling: pd.DataFrame, corr_summary: dict) -> list[str]:
    paths = []
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(fevd.values, vmin=0, vmax=max(0.5, float(fevd.values.max())), cmap="viridis")
    ax.set_xticks(range(len(fevd.columns)))
    ax.set_xticklabels(fevd.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(fevd.index)))
    ax.set_yticklabels(fevd.index)
    ax.set_title("Generalized FEVD shares (row: affected, col: shock source)")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    path = FIG_DIR / "k1361_fevd_heatmap.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(HERE)))

    if not rolling.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        for name in ["GAMING_ETF", "BETTING_FINTECH", "QQQ", "ARKK", "BTC"]:
            ax.plot(pd.to_datetime(rolling["date"]), rolling[f"{name}_net"], label=name, linewidth=1.5)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_title("Rolling 252d net connectedness")
        ax.set_ylabel("TO - FROM")
        ax.legend(ncol=3, fontsize=8)
        fig.tight_layout()
        path = FIG_DIR / "k1361_rolling_net_connectedness.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(HERE)))

    corr_rows = []
    for key, row in corr_summary.items():
        corr_rows.append(
            {
                "pair": key.replace("_corr_", " vs "),
                "diff": row.get("diff_stress_minus_calm"),
                "t": row.get("welch_t"),
            }
        )
    corr_df = pd.DataFrame(corr_rows).dropna()
    if not corr_df.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        colors = ["#d55e00" if v >= 3 else "#0072b2" for v in corr_df["t"]]
        ax.bar(corr_df["pair"], corr_df["diff"], color=colors)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_title("Stress minus calm rolling return correlation")
        ax.set_ylabel("Correlation difference")
        ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        path = FIG_DIR / "k1361_stress_corr_diffs.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(HERE)))
    return paths


def run(refresh: bool = False) -> dict:
    prices, raw_coverage = load_prices(refresh=refresh)
    raw_returns = np.log(prices / prices.shift(1))
    basket_returns, basket_coverage = build_basket_returns(raw_returns)
    rv_variance, log_rv = make_log_rv(basket_returns)

    analysis = log_rv[CONNECTEDNESS_SERIES].replace([np.inf, -np.inf], np.nan).dropna(how="any")
    if len(analysis) < 400:
        raise RuntimeError(f"analysis sample too small: {len(analysis)}")
    basket_returns = basket_returns.loc[analysis.index.min() : analysis.index.max()]
    rv_variance = rv_variance.loc[analysis.index.min() : analysis.index.max()]
    log_rv = log_rv.loc[analysis.index.min() : analysis.index.max()]

    fevd, table, lag = fit_connectedness(analysis, lag=None)
    rolling, thresholds = rolling_connectedness(log_rv, rv_variance["SPY"])
    rolling_summary = summarize_rolling_connectedness(rolling)
    lead_results = lead_lag_tests(log_rv[CONNECTEDNESS_SERIES])
    corr_summary = rolling_correlation_tests(basket_returns[CONNECTEDNESS_SERIES], rv_variance["SPY"])
    verdict, key_findings = verdict_from_results(rolling_summary, lead_results, corr_summary)
    figures = write_figures(fevd, rolling, corr_summary)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Gaming / betting basket volatility spillover and diversification-sink test",
        "created_at": utc_now(),
        "seed": SEED,
        "verdict": verdict,
        "key_findings": key_findings,
        "data_source": "yfinance adjusted close via yf.Ticker(...).history(auto_adjust=True)",
        "sample": {
            "start": str(analysis.index.min().date()),
            "end": str(analysis.index.max().date()),
            "n_daily_observations": int(len(analysis)),
            "rv_window_days": RV_WINDOW,
            "connectedness_series": CONNECTEDNESS_SERIES,
        },
        "raw_ticker_coverage": raw_coverage,
        "basket_coverage": basket_coverage,
        "literature": LITERATURE,
        "method": {
            "vol_proxy": "annualized trailing 21-trading-day close-to-close variance; VAR uses log variance",
            "connectedness": "generalized Diebold-Yilmaz FEVD from VAR on standardized log-RV",
            "rolling_window_days": ROLLING_WINDOW,
            "rolling_step_days": ROLLING_STEP,
            "stress_regime": "SPY 21d realized vol top quartile at rolling window end",
            "predictive_tests": "OLS/HAC on standardized log-RV with source_lag1 = source log-RV shifted by 1 day",
            "harvey_bar": "positive lagged source coefficient with HAC t >= 3 for strong predictive claim",
        },
        "diagnostics": {
            "stationarity_adf_log_rv": stationarity(log_rv[CONNECTEDNESS_SERIES]),
            "full_sample_var_lag_aic": int(lag),
            "rolling_windows": int(len(rolling)),
            "stress_thresholds": thresholds,
        },
        "full_sample_fevd": fevd.round(6).to_dict(),
        "full_sample_connectedness": table.round(6).to_dict(),
        "rolling_connectedness_stress_vs_calm": rolling_summary,
        "lagged_vol_hac_tests": lead_results,
        "rolling_return_correlation_stress_vs_calm": corr_summary,
        "figures": figures,
        "limitations": [
            "Current listed proxies are survivorship-biased and do not cover delisted gaming/betting firms.",
            "FLUT yfinance history may reflect symbol/listing continuity rather than a pure NYSE-only listing history; it is treated only as a public betting-equity proxy.",
            "BTC is aligned to the SPY trading calendar, so weekend crypto moves enter the next US trading-session return.",
            "Close-to-close rolling variance is a public-data proxy, not intraday realized variance or option-implied volatility.",
            "Diebold-Yilmaz connectedness is descriptive and model-dependent; causal transmitter claims require lagged tests to pass.",
            "Rolling-window stress/calm differences are diagnostic because adjacent windows overlap.",
        ],
    }
    with (HERE / "K1361_results.json").open("w") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="ignore cached yfinance data")
    args = parser.parse_args()
    results = run(refresh=args.refresh)
    print(json.dumps({"ok": True, "verdict": results["verdict"], "sample": results["sample"]}, indent=2))


if __name__ == "__main__":
    main()
