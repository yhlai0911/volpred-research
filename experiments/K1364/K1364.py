"""K1364: ETF sampling arbitrage proxy and liquid-constituent heterogeneity.

This is a free-data pilot.  It does not observe actual AP creation/redemption
baskets.  Instead it combines public top-10 ETF holdings from yfinance with
daily OHLCV data to test whether lagged ETF volume/tracking-error shocks are
followed by stronger high-liquidity minus low-liquidity constituent responses.
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

EXPERIMENT_ID = "K1364"
SEED = 42
START_DATE = "2020-01-01"
END_DATE = "2026-06-24"
ROLLING_WINDOW = 252
MIN_ROLLING = 126
LIQUIDITY_WINDOW = 63
BOOT_REPS = 1000
BOOT_BLOCK = 21

ETF_TICKERS = [
    "SPY",
    "IVV",
    "VTI",
    "IWM",
    "MDY",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLB",
    "XLU",
    "XLRE",
    "XLC",
]

RESULTS_PATH = HERE / "K1364_results.json"
FIG_COEF_PATH = HERE / "K1364_coefficients.png"
FIG_EVENT_PATH = HERE / "K1364_event_spreads.png"

np.random.seed(SEED)


def json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        if not np.isfinite(obj):
            return None
        return float(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.date().isoformat()
    return str(obj)


def safe_name(ticker: str) -> str:
    return ticker.replace("^", "").replace("/", "_").replace("-", "_").lower()


def rolling_z(series: pd.Series, window: int = ROLLING_WINDOW, min_periods: int = MIN_ROLLING) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std()
    return (series - mean) / std.replace(0.0, np.nan)


def load_top_holdings(etf: str) -> pd.DataFrame:
    path = DATA_DIR / f"{safe_name(etf)}_top_holdings.csv"
    if path.exists():
        return pd.read_csv(path)

    holdings = yf.Ticker(etf).funds_data.top_holdings
    if holdings is None or holdings.empty:
        raise RuntimeError(f"No top holdings available for {etf}")

    out = (
        holdings.reset_index()
        .rename(
            columns={
                "Symbol": "symbol",
                "Name": "name",
                "Holding Percent": "holding_percent",
            }
        )
        [["symbol", "name", "holding_percent"]]
    )
    out["etf"] = etf
    out["holding_percent"] = pd.to_numeric(out["holding_percent"], errors="coerce")
    out = out.dropna(subset=["symbol", "holding_percent"])
    out.to_csv(path, index=False)
    return out


def load_all_holdings() -> pd.DataFrame:
    frames = []
    errors = []
    for etf in ETF_TICKERS:
        try:
            frames.append(load_top_holdings(etf))
        except Exception as exc:  # pragma: no cover - network/data dependent
            errors.append({"etf": etf, "error": repr(exc)})
    if not frames:
        raise RuntimeError(f"No holdings loaded: {errors}")
    holdings = pd.concat(frames, ignore_index=True)
    holdings["symbol"] = holdings["symbol"].astype(str).str.strip()
    holdings = holdings[holdings["symbol"].ne("")]
    holdings.attrs["errors"] = errors
    return holdings


def extract_ticker_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    if raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0)
        level1 = raw.columns.get_level_values(1)
        if ticker in level0:
            sub = raw[ticker].copy()
        elif ticker in level1:
            sub = raw.xs(ticker, axis=1, level=1).copy()
        else:
            return None
    else:
        sub = raw.copy()

    required = ["Close", "High", "Low", "Volume"]
    missing = [col for col in required if col not in sub.columns]
    if missing:
        return None
    out = sub[required].copy()
    out.columns = ["close", "high", "low", "volume"]
    out = out.dropna(subset=["close"])
    if out.empty:
        return None
    out["ticker"] = ticker
    out["date"] = pd.to_datetime(out.index).tz_localize(None)
    return out.reset_index(drop=True)[["date", "ticker", "close", "high", "low", "volume"]]


def download_prices(tickers: list[str]) -> tuple[pd.DataFrame, list[dict]]:
    cache = DATA_DIR / f"prices_{START_DATE}_{END_DATE}.csv"
    if cache.exists():
        prices = pd.read_csv(cache, parse_dates=["date"])
        missing = sorted(set(tickers) - set(prices["ticker"].unique()))
        return prices, [{"ticker": ticker, "error": "missing_from_cache"} for ticker in missing]

    tickers = sorted(set(tickers))
    raw = yf.download(
        tickers,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True,
    )

    frames = []
    errors = []
    for ticker in tickers:
        frame = extract_ticker_frame(raw, ticker)
        if frame is None or frame.empty:
            errors.append({"ticker": ticker, "error": "no_ohlcv_rows"})
            continue
        frames.append(frame)
    if not frames:
        raise RuntimeError("No price data downloaded")
    prices = pd.concat(frames, ignore_index=True)
    prices.to_csv(cache, index=False)
    return prices, errors


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & (weights > 0)
    if valid.sum() == 0:
        return float("nan")
    return float(np.average(values[valid], weights=weights[valid]))


def weighted_mean_np(values: np.ndarray, weights: np.ndarray, positions: np.ndarray) -> float:
    vals = values[positions]
    w = weights[positions]
    valid = np.isfinite(vals) & np.isfinite(w) & (w > 0)
    if valid.sum() == 0:
        return float("nan")
    return float(np.average(vals[valid], weights=w[valid]))


def build_data() -> tuple[pd.DataFrame, dict]:
    holdings = load_all_holdings()
    stock_tickers = sorted(set(holdings["symbol"]) - set(ETF_TICKERS))
    all_tickers = sorted(set(ETF_TICKERS + stock_tickers + ["SPY"]))
    prices, price_errors = download_prices(all_tickers)

    close = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    high = prices.pivot(index="date", columns="ticker", values="high").sort_index()
    low = prices.pivot(index="date", columns="ticker", values="low").sort_index()
    volume = prices.pivot(index="date", columns="ticker", values="volume").sort_index()

    returns = np.log(close).diff()
    dollar_volume = close * volume.replace(0.0, np.nan)
    log_adv_lag1 = np.log1p(dollar_volume).rolling(
        LIQUIDITY_WINDOW, min_periods=30
    ).mean().shift(1)

    market_ret = returns["SPY"]
    market_rv_lag1 = market_ret.pow(2).shift(1)

    rv_z = returns.pow(2).apply(rolling_z)
    beta_contrib_z = returns.mul(market_ret, axis=0).apply(rolling_z)

    rows = []
    shock_rows = []
    skipped = []

    for etf in ETF_TICKERS:
        etf_holdings = holdings[holdings["etf"] == etf].copy()
        etf_holdings = etf_holdings[etf_holdings["symbol"].isin(returns.columns)]
        if etf not in returns.columns or len(etf_holdings) < 6:
            skipped.append({"etf": etf, "reason": "insufficient_holdings_or_etf_prices"})
            continue

        symbols = etf_holdings["symbol"].tolist()
        weights = etf_holdings.set_index("symbol")["holding_percent"].astype(float)
        weights = weights / weights.sum()

        basket_ret = returns[symbols].mul(weights, axis=1).sum(axis=1, min_count=4)
        etf_ret = returns[etf]
        tracking_error_abs = (etf_ret - basket_ret).abs()
        etf_dollar_volume = dollar_volume[etf]

        volume_z = rolling_z(np.log1p(etf_dollar_volume))
        tracking_error_z = rolling_z(tracking_error_abs)
        etf_shock_raw = pd.concat([volume_z, tracking_error_z], axis=1).mean(axis=1)

        # Explicit t-1 information set: ETF shock observed at t-1 predicts
        # high-minus-low constituent responses realized on day t.
        etf_shock_lag1 = etf_shock_raw.shift(1)
        volume_z_lag1 = volume_z.shift(1)
        tracking_error_z_lag1 = tracking_error_z.shift(1)
        abs_etf_ret_lag1 = etf_ret.abs().shift(1)

        comovement_z = returns[symbols].mul(etf_ret, axis=0).apply(rolling_z)

        liq_df = log_adv_lag1[symbols]
        valid_date_mask = etf_shock_lag1.notna() & (liq_df.notna().sum(axis=1) >= 6)
        valid_dates = liq_df.index[valid_date_mask.to_numpy()]
        if len(valid_dates) == 0:
            skipped.append({"etf": etf, "reason": "no_valid_lagged_shock_dates"})
            continue

        symbol_arr = np.asarray(symbols)
        weights_arr = weights.reindex(symbols).to_numpy(dtype=float)
        liq_values = liq_df.loc[valid_dates].to_numpy(dtype=float)
        rv_values = rv_z.loc[valid_dates, symbols].to_numpy(dtype=float)
        beta_values = beta_contrib_z.loc[valid_dates, symbols].to_numpy(dtype=float)
        comove_values = comovement_z.loc[valid_dates, symbols].to_numpy(dtype=float)
        shock_values = etf_shock_lag1.loc[valid_dates].to_numpy(dtype=float)
        volume_values = volume_z_lag1.loc[valid_dates].to_numpy(dtype=float)
        tracking_values = tracking_error_z_lag1.loc[valid_dates].to_numpy(dtype=float)
        abs_ret_values = abs_etf_ret_lag1.loc[valid_dates].to_numpy(dtype=float)
        market_rv_values = market_rv_lag1.loc[valid_dates].to_numpy(dtype=float)

        target_arrays = {
            "rv_spread": rv_values,
            "market_beta_proxy_spread": beta_values,
            "etf_comovement_spread": comove_values,
        }

        for i, date in enumerate(valid_dates):
            liq_arr = liq_values[i]
            valid_liq_pos = np.where(np.isfinite(liq_arr))[0]
            if len(valid_liq_pos) < 6:
                continue
            ordered_pos = valid_liq_pos[np.argsort(liq_arr[valid_liq_pos])]
            tercile_n = max(2, len(ordered_pos) // 3)
            low_pos = ordered_pos[:tercile_n]
            high_pos = ordered_pos[-tercile_n:]

            row = {
                "date": date,
                "etf": etf,
                "n_holdings_available": int(len(valid_liq_pos)),
                "high_liq_symbols": ",".join(symbol_arr[high_pos].tolist()),
                "low_liq_symbols": ",".join(symbol_arr[low_pos].tolist()),
                "high_liq_log_adv": float(np.nanmean(liq_arr[high_pos])),
                "low_liq_log_adv": float(np.nanmean(liq_arr[low_pos])),
                "holding_weight_high": float(np.nansum(weights_arr[high_pos])),
                "holding_weight_low": float(np.nansum(weights_arr[low_pos])),
                "etf_shock_lag1": float(shock_values[i]),
                "volume_z_lag1": float(volume_values[i]),
                "tracking_error_z_lag1": float(tracking_values[i]),
                "abs_etf_ret_lag1": float(abs_ret_values[i]),
                "market_rv_lag1": float(market_rv_values[i]),
            }

            for target_name, target_values in target_arrays.items():
                high_mean = weighted_mean_np(target_values[i], weights_arr, high_pos)
                low_mean = weighted_mean_np(target_values[i], weights_arr, low_pos)
                row[f"{target_name}_high"] = high_mean
                row[f"{target_name}_low"] = low_mean
                row[target_name] = high_mean - low_mean

            rows.append(row)

        shock_rows.append(
            {
                "etf": etf,
                "available_holdings": int(len(symbols)),
                "top10_weight_sum": float(etf_holdings["holding_percent"].sum()),
                "mean_abs_tracking_error": float(tracking_error_abs.mean(skipna=True)),
                "mean_log_dollar_volume": float(np.log1p(etf_dollar_volume).mean(skipna=True)),
            }
        )

    panel = pd.DataFrame(rows).sort_values(["date", "etf"]).reset_index(drop=True)
    for target in ["rv_spread", "market_beta_proxy_spread", "etf_comovement_spread"]:
        panel[f"{target}_lag1"] = panel.groupby("etf")[target].shift(1)

    diagnostics = {
        "holdings_source": "yfinance Ticker(...).funds_data.top_holdings top-10 snapshot",
        "price_source": "yfinance adjusted OHLCV",
        "start_date": START_DATE,
        "end_date_exclusive": END_DATE,
        "etfs_requested": ETF_TICKERS,
        "etfs_used": sorted(panel["etf"].dropna().unique().tolist()) if not panel.empty else [],
        "unique_constituents_requested": len(stock_tickers),
        "unique_tickers_with_prices": int(prices["ticker"].nunique()),
        "holdings_errors": holdings.attrs.get("errors", []),
        "price_errors": price_errors,
        "skipped_etfs": skipped,
        "shock_diagnostics": shock_rows,
    }
    return panel, diagnostics


def fit_spread_model(panel: pd.DataFrame, target: str) -> dict:
    cols = [
        "date",
        "etf",
        target,
        "etf_shock_lag1",
        "volume_z_lag1",
        "tracking_error_z_lag1",
        "abs_etf_ret_lag1",
        "market_rv_lag1",
        f"{target}_lag1",
    ]
    model_df = panel[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    y = model_df[target]
    x = model_df[
        [
            "etf_shock_lag1",
            "abs_etf_ret_lag1",
            "market_rv_lag1",
            f"{target}_lag1",
        ]
    ].copy()
    x = pd.concat([x, pd.get_dummies(model_df["etf"], prefix="etf", drop_first=True)], axis=1)
    x = sm.add_constant(x, has_constant="add").astype(float)

    fit = sm.OLS(y.astype(float), x).fit(
        cov_type="cluster",
        cov_kwds={"groups": model_df["date"]},
    )
    beta = float(fit.params["etf_shock_lag1"])
    se = float(fit.bse["etf_shock_lag1"])
    t_stat = beta / se if se > 0 else float("nan")
    p_value = float(2.0 * (1.0 - stats.norm.cdf(abs(t_stat)))) if np.isfinite(t_stat) else float("nan")

    return {
        "target": target,
        "n_obs": int(len(model_df)),
        "n_dates": int(model_df["date"].nunique()),
        "n_etfs": int(model_df["etf"].nunique()),
        "coef_etf_shock_lag1": beta,
        "se_cluster_by_date": se,
        "z_stat": t_stat,
        "p_value": p_value,
        "r_squared": float(fit.rsquared),
        "controls": [
            "abs_etf_ret_lag1",
            "market_rv_lag1",
            f"{target}_lag1",
            "ETF fixed effects",
        ],
        "interpretation": (
            "Positive coefficient means high-liquidity constituents have a "
            "larger next-day standardized response than low-liquidity "
            "constituents after a lagged ETF shock."
        ),
    }


def block_bootstrap_event_diff(model_df: pd.DataFrame, target: str) -> dict:
    clean = model_df[["date", "etf_shock_lag1", target]].dropna().copy()
    cutoff = float(clean["etf_shock_lag1"].quantile(0.90))
    high_mask = clean["etf_shock_lag1"] >= cutoff
    observed = float(clean.loc[high_mask, target].mean() - clean.loc[~high_mask, target].mean())

    dates = np.array(sorted(clean["date"].unique()))
    rng = np.random.default_rng(SEED)
    values = []
    for _ in range(BOOT_REPS):
        sampled_dates = []
        while len(sampled_dates) < len(dates):
            start = int(rng.integers(0, max(1, len(dates) - BOOT_BLOCK + 1)))
            sampled_dates.extend(dates[start : start + BOOT_BLOCK])
        sample = clean[clean["date"].isin(sampled_dates[: len(dates)])]
        if sample.empty:
            continue
        c = float(sample["etf_shock_lag1"].quantile(0.90))
        h = sample["etf_shock_lag1"] >= c
        if h.any() and (~h).any():
            values.append(float(sample.loc[h, target].mean() - sample.loc[~h, target].mean()))

    arr = np.asarray(values)
    return {
        "target": target,
        "shock_cutoff_top_decile": cutoff,
        "top_decile_mean_spread": float(clean.loc[high_mask, target].mean()),
        "other_mean_spread": float(clean.loc[~high_mask, target].mean()),
        "top_minus_other": observed,
        "bootstrap_reps": int(len(arr)),
        "bootstrap_block_days": BOOT_BLOCK,
        "bootstrap_ci_95": [
            float(np.quantile(arr, 0.025)),
            float(np.quantile(arr, 0.975)),
        ]
        if len(arr)
        else [None, None],
    }


def plot_coefficients(models: list[dict]) -> None:
    labels = [m["target"].replace("_spread", "") for m in models]
    coefs = np.array([m["coef_etf_shock_lag1"] for m in models])
    ses = np.array([m["se_cluster_by_date"] for m in models])

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(labels))
    ax.bar(x, coefs, color=["#3b7ea1" if c >= 0 else "#b8554f" for c in coefs])
    ax.errorbar(x, coefs, yerr=1.96 * ses, fmt="none", ecolor="#1f2933", capsize=4)
    ax.axhline(0.0, color="#111827", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=18, ha="right")
    ax.set_ylabel("Coefficient on lagged ETF shock")
    ax.set_title("K1364 high-liquidity minus low-liquidity response")
    ax.text(
        0.01,
        0.02,
        "Bars: cluster-by-date OLS coefficients; whiskers: 95% normal intervals.",
        transform=ax.transAxes,
        fontsize=9,
        color="#374151",
    )
    fig.tight_layout()
    fig.savefig(FIG_COEF_PATH, dpi=160)
    plt.close(fig)


def plot_events(events: list[dict]) -> None:
    labels = [e["target"].replace("_spread", "") for e in events]
    diffs = np.array([e["top_minus_other"] for e in events])
    lows = np.array([e["bootstrap_ci_95"][0] for e in events], dtype=float)
    highs = np.array([e["bootstrap_ci_95"][1] for e in events], dtype=float)

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(labels))
    ax.bar(x, diffs, color=["#52796f" if d >= 0 else "#ad6a6c" for d in diffs])
    ax.errorbar(
        x,
        diffs,
        yerr=np.vstack([diffs - lows, highs - diffs]),
        fmt="none",
        ecolor="#1f2933",
        capsize=4,
    )
    ax.axhline(0.0, color="#111827", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=18, ha="right")
    ax.set_ylabel("Top-decile shock spread minus other days")
    ax.set_title("K1364 event diagnostic: high ETF shocks")
    ax.text(
        0.01,
        0.02,
        "Moving-block bootstrap by date, seed=42, block=21 trading days.",
        transform=ax.transAxes,
        fontsize=9,
        color="#374151",
    )
    fig.tight_layout()
    fig.savefig(FIG_EVENT_PATH, dpi=160)
    plt.close(fig)


def make_results(panel: pd.DataFrame, diagnostics: dict) -> dict:
    targets = ["rv_spread", "market_beta_proxy_spread", "etf_comovement_spread"]
    models = [fit_spread_model(panel, target) for target in targets]
    for model in models:
        model["p_value_bonferroni_3_targets"] = min(1.0, model["p_value"] * len(targets))

    events = [block_bootstrap_event_diff(panel, target) for target in targets]
    plot_coefficients(models)
    plot_events(events)

    pass_targets = [
        m
        for m in models
        if m["coef_etf_shock_lag1"] > 0 and m["p_value_bonferroni_3_targets"] < 0.05
    ]
    if len(pass_targets) >= 2:
        verdict = "CONDITIONAL_PASS_PROXY"
        conclusion = (
            "The free-data proxy supports liquid-constituent heterogeneity for at "
            "least two response measures after Bonferroni correction, but not a "
            "causal AP basket claim."
        )
    elif len(pass_targets) == 1:
        verdict = "WEAK_DIAGNOSTIC"
        conclusion = (
            "Only one response measure clears the pre-set Bonferroni bar.  Treat "
            "the result as a diagnostic lead, not robust support for the full "
            "ETF sampling-arbitrage claim."
        )
    else:
        verdict = "NULL_PROXY"
        conclusion = (
            "The yfinance top-holdings proxy does not robustly show that lagged "
            "ETF shocks amplify high-liquidity constituents more than low-liquidity "
            "constituents across RV, market-beta proxy, and ETF-comovement targets."
        )

    sample = panel.dropna(
        subset=[
            "rv_spread",
            "market_beta_proxy_spread",
            "etf_comovement_spread",
            "etf_shock_lag1",
        ]
    )

    return {
        "experiment_id": EXPERIMENT_ID,
        "title": "ETF sampling arbitrage proxy and liquid-constituent heterogeneity",
        "seed": SEED,
        "verdict": verdict,
        "conclusion": conclusion,
        "data": {
            **diagnostics,
            "effective_sample_start": sample["date"].min() if not sample.empty else None,
            "effective_sample_end": sample["date"].max() if not sample.empty else None,
            "effective_panel_rows": int(len(sample)),
            "effective_dates": int(sample["date"].nunique()) if not sample.empty else 0,
            "effective_etfs": int(sample["etf"].nunique()) if not sample.empty else 0,
        },
        "method": {
            "design": (
                "For each ETF-date, split available top-10 holdings into high and "
                "low liquidity terciles using 63-day lagged log dollar volume. "
                "Regress the high-minus-low target spread on lagged ETF shock, "
                "controls, and ETF fixed effects."
            ),
            "etf_shock": (
                "Mean of rolling-z ETF dollar-volume shock and rolling-z absolute "
                "ETF-vs-top-holdings tracking-error proxy, then signal.shift(1)."
            ),
            "lookahead_policy": (
                "All predictive ETF-shock and liquidity-ranking variables use t-1 "
                "information: etf_shock_lag1 = etf_shock_raw.shift(1), "
                "log_adv_lag1 = rolling_mean(log dollar volume).shift(1)."
            ),
            "targets": {
                "rv_spread": "High-minus-low weighted mean of constituent r_t^2 rolling z-scores.",
                "market_beta_proxy_spread": (
                    "High-minus-low weighted mean of rolling-z stock_ret_t * SPY_ret_t "
                    "as a daily market-beta contribution proxy."
                ),
                "etf_comovement_spread": (
                    "High-minus-low weighted mean of rolling-z stock_ret_t * ETF_ret_t "
                    "as close-to-close ETF comovement proxy."
                ),
            },
            "formal_test": (
                "Cluster-by-date OLS coefficient on lagged ETF shock.  Pre-set "
                "support requires positive coefficients with Bonferroni p<0.05 "
                "for at least two of three targets."
            ),
        },
        "descriptive_diagnostics": {
            "avg_holding_weight_high_minus_low": float(
                (sample["holding_weight_high"] - sample["holding_weight_low"]).mean()
            )
            if not sample.empty
            else None,
            "avg_log_adv_high_minus_low": float(
                (sample["high_liq_log_adv"] - sample["low_liq_log_adv"]).mean()
            )
            if not sample.empty
            else None,
            "shock_lag1_summary": sample["etf_shock_lag1"].describe().to_dict()
            if not sample.empty
            else {},
        },
        "regression_results": models,
        "event_diagnostics": events,
        "figures": [str(FIG_COEF_PATH.relative_to(HERE)), str(FIG_EVENT_PATH.relative_to(HERE))],
        "literature": [
            {
                "citation": "Brogaard, Heath, Huang (2025/2026), ETF Sampling and Index Arbitrage, JFQA",
                "url": "https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/etf-sampling-and-index-arbitrage/EE6BA16F9C54C1E01DD726FF23796FC7",
                "use": "Primary heterogeneity hypothesis: AP arbitrage effects differ by constituent liquidity.",
            },
            {
                "citation": "Ben-David, Franzoni, Moussawi (2018), Do ETFs Increase Volatility?, Journal of Finance",
                "url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12727",
                "use": "ETF ownership/arbitrage channel motivates volatility target.",
            },
            {
                "citation": "Da and Shive (2018), Exchange Traded Funds and Asset Return Correlations, European Financial Management",
                "url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/eufm.12137",
                "use": "ETF arbitrage and constituent return comovement motivate comovement target.",
            },
            {
                "citation": "Brown, Davies, Ringgenberg (2021), ETF Arbitrage, Non-Fundamental Demand, and Return Predictability, Review of Finance",
                "url": "https://academic.oup.com/rof/article-abstract/25/4/937/5919085",
                "use": "Creation/redemption activity as non-fundamental ETF demand shock context.",
            },
        ],
        "limitations": [
            "This is not direct AP creation-redemption basket data.",
            "yfinance holdings are current top-10 snapshots, not historical full holdings; survivorship and composition drift remain.",
            "Tracking error is measured against the normalized top-10 basket, not official NAV.",
            "Daily OHLCV cannot identify intraday arbitrage trades or official bid-ask depth.",
            "Cluster-by-date inference handles common-day shocks but is still a low-frequency proxy test, not causal identification.",
        ],
    }


def main() -> None:
    warnings.filterwarnings("ignore", category=FutureWarning)
    panel, diagnostics = build_data()
    if panel.empty:
        raise RuntimeError("No panel rows constructed")
    results = make_results(panel, diagnostics)
    panel.to_csv(HERE / "K1364_panel.csv", index=False)
    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=json_default) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "verdict": results["verdict"], "rows": len(panel)}, indent=2))


if __name__ == "__main__":
    main()
