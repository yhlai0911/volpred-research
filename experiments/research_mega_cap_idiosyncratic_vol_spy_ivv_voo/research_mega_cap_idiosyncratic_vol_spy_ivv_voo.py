"""Passive ETF-flow proxy and mega-cap idiosyncratic volatility.

This is a yfinance-only proxy experiment motivated by Jiang, Vayanos, and
Zheng (2025) and the ETF-volatility literature. Historical ETF AUM and
creation/redemption flows are not available from yfinance, so the experiment
does not claim to observe true passive flows.

Proxy:
    passive-flow shock = rolling z-score of monthly change in aggregate
    SPY+IVV+VOO dollar volume.

Primary test:
    Does lagged passive-flow shock raise next-month CAPM residual realized
    variance more for current mega-cap stocks than for other large caps?

Lookahead guard:
    The primary panel regression uses flow_shock_l1, lag_log_idio_rv,
    stock fixed effects, and month fixed effects. The target month t never
    uses ETF volume from month t in the primary test.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import yfinance as yf


SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "research_mega_cap_idiosyncratic_vol_spy_ivv_voo"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_START = "2010-09-01"
DATA_END = "2026-06-18"
MIN_DAILY_OBS_PER_MONTH = 15
ROLLING_Z_WINDOW_MONTHS = 36
ROLLING_Z_MIN_MONTHS = 24
BOOTSTRAP_REPS = 1000
EPS = 1e-12

ETF_TICKERS = ["SPY", "IVV", "VOO"]
MARKET_TICKER = "SPY"

# Current-name mega-cap proxy, deliberately limited and caveated in README.
TOP10_TICKERS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "BRK-B",
    "AVGO",
    "TSLA",
    "JPM",
]

CONTROL_TICKERS = [
    "JNJ",
    "XOM",
    "PG",
    "KO",
    "WMT",
    "V",
    "MA",
    "UNH",
    "HD",
    "MRK",
    "CVX",
    "BAC",
    "PFE",
    "CSCO",
    "IBM",
    "MCD",
    "DIS",
    "ORCL",
    "CRM",
    "CMCSA",
    "INTC",
    "QCOM",
    "TXN",
    "AMGN",
    "ADBE",
    "NKE",
    "ABT",
    "COST",
    "PEP",
    "TMO",
]

STOCK_TICKERS = TOP10_TICKERS + CONTROL_TICKERS
ALL_TICKERS = sorted(set(ETF_TICKERS + STOCK_TICKERS))


@dataclass
class RegressionResult:
    name: str
    coefficient: float
    t_stat: float
    p_value: float
    n_obs: int
    n_months: int
    n_stocks: int
    expected_sign: str
    harvey_pass: bool


def download_one(ticker: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        start=DATA_START,
        end=DATA_END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df.empty:
        raise RuntimeError(f"No yfinance data returned for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Close", "Volume"]].dropna().copy()
    out.columns = pd.MultiIndex.from_product([[ticker], out.columns])
    return out


def load_data() -> pd.DataFrame:
    frames = []
    failures = []
    for ticker in ALL_TICKERS:
        try:
            frames.append(download_one(ticker))
        except Exception as exc:  # pragma: no cover - recorded in results
            failures.append({"ticker": ticker, "error": str(exc)})
    if failures:
        failed = ", ".join(item["ticker"] for item in failures)
        raise RuntimeError(f"Download failures: {failed}")
    return pd.concat(frames, axis=1, sort=True).sort_index()


def rolling_zscore_monthly(x: pd.Series) -> pd.Series:
    mu = x.rolling(ROLLING_Z_WINDOW_MONTHS, min_periods=ROLLING_Z_MIN_MONTHS).mean()
    sd = x.rolling(ROLLING_Z_WINDOW_MONTHS, min_periods=ROLLING_Z_MIN_MONTHS).std()
    return (x - mu) / sd


def build_flow_proxy(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    dollar_volume = pd.DataFrame(index=close.index)
    for ticker in ETF_TICKERS:
        dollar_volume[ticker] = close[ticker] * volume[ticker]

    monthly_dv = dollar_volume.sum(axis=1).resample("ME").sum()
    log_dv = np.log(monthly_dv.replace(0.0, np.nan))
    log_dv_change = log_dv.diff()
    flow_shock = rolling_zscore_monthly(log_dv_change)

    out = pd.DataFrame(
        {
            "etf_dollar_volume": monthly_dv,
            "log_etf_dollar_volume": log_dv,
            "log_etf_dollar_volume_change": log_dv_change,
            "flow_shock": flow_shock,
            "flow_shock_l1": flow_shock.shift(1),
        }
    )
    return out


def capm_residual_month(stock_ret: pd.Series, market_ret: pd.Series) -> dict | None:
    df = pd.concat([stock_ret, market_ret], axis=1, keys=["stock", "market"]).dropna()
    if len(df) < MIN_DAILY_OBS_PER_MONTH:
        return None

    y = df["stock"].to_numpy(dtype=float)
    x = df["market"].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(x)), x])
    alpha, beta = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - alpha - beta * x
    idio_rv_ann = float(np.mean(residual**2) * 252.0)
    total_rv_ann = float(np.mean(y**2) * 252.0)
    return {
        "alpha": float(alpha),
        "beta": float(beta),
        "idio_rv_ann": idio_rv_ann,
        "total_rv_ann": total_rv_ann,
        "n_daily": int(len(df)),
    }


def build_monthly_panel(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = data.xs("Close", level=1, axis=1)
    volume = data.xs("Volume", level=1, axis=1)
    logret = np.log(close).diff()

    flow = build_flow_proxy(close, volume)
    market_monthly = pd.DataFrame(
        {
            "market_ret": logret[MARKET_TICKER].resample("ME").sum(),
            "market_abs_ret": logret[MARKET_TICKER].resample("ME").sum().abs(),
            "market_rv_ann": logret[MARKET_TICKER].pow(2).resample("ME").mean() * 252.0,
        }
    )
    month_controls = flow.join(market_monthly, how="left")
    month_controls["market_rv_ann_l1"] = month_controls["market_rv_ann"].shift(1)
    month_controls["market_abs_ret_l1"] = month_controls["market_abs_ret"].shift(1)

    rows: list[dict] = []
    for ticker in STOCK_TICKERS:
        if ticker not in logret:
            continue
        grouped_stock = logret[ticker].groupby(pd.Grouper(freq="ME"))
        grouped_market = logret[MARKET_TICKER].groupby(pd.Grouper(freq="ME"))
        market_by_month = {month: values for month, values in grouped_market}
        for month, stock_values in grouped_stock:
            capm = capm_residual_month(stock_values, market_by_month.get(month))
            if capm is None:
                continue
            rows.append(
                {
                    "month": month,
                    "month_str": month.strftime("%Y-%m"),
                    "ticker": ticker,
                    "is_top10": int(ticker in TOP10_TICKERS),
                    **capm,
                }
            )

    panel = pd.DataFrame(rows)
    month_controls = month_controls.copy()
    month_controls.index.name = "month"
    panel = panel.merge(month_controls.reset_index(), on="month", how="left")
    panel = panel.sort_values(["ticker", "month"]).reset_index(drop=True)
    panel["log_idio_rv"] = np.log(panel["idio_rv_ann"].clip(lower=EPS))
    panel["lag_log_idio_rv"] = panel.groupby("ticker")["log_idio_rv"].shift(1)
    panel["top10_flow_l1"] = panel["is_top10"] * panel["flow_shock_l1"]
    panel["top10_flow_current"] = panel["is_top10"] * panel["flow_shock"]
    panel["top10_market_rv_l1"] = panel["is_top10"] * panel["market_rv_ann_l1"]
    return panel, month_controls


def fit_interaction(panel: pd.DataFrame, name: str, interaction_col: str, month_fe: bool = True) -> RegressionResult:
    cols = [
        "log_idio_rv",
        "lag_log_idio_rv",
        interaction_col,
        "ticker",
        "month",
        "month_str",
    ]
    if not month_fe:
        cols += ["flow_shock_l1", "market_rv_ann_l1", "market_abs_ret_l1", "is_top10"]
    df = panel[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if month_fe:
        formula = f"log_idio_rv ~ {interaction_col} + lag_log_idio_rv + C(ticker) + C(month_str)"
    else:
        formula = (
            f"log_idio_rv ~ flow_shock_l1 + {interaction_col} + is_top10 "
            "+ lag_log_idio_rv + market_rv_ann_l1 + market_abs_ret_l1 + C(ticker)"
        )
    fit = smf.ols(formula, data=df).fit(cov_type="cluster", cov_kwds={"groups": df["month_str"]})
    coef = float(fit.params[interaction_col])
    tval = float(fit.tvalues[interaction_col])
    pval = float(fit.pvalues[interaction_col])
    return RegressionResult(
        name=name,
        coefficient=coef,
        t_stat=tval,
        p_value=pval,
        n_obs=int(len(df)),
        n_months=int(df["month_str"].nunique()),
        n_stocks=int(df["ticker"].nunique()),
        expected_sign="positive",
        harvey_pass=bool(coef > 0 and abs(tval) > 3.0),
    )


def top10_minus_control_spread(panel: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        panel.dropna(subset=["log_idio_rv", "flow_shock_l1"])
        .groupby(["month", "month_str", "is_top10"])["log_idio_rv"]
        .mean()
        .unstack("is_top10")
    )
    grouped = grouped.rename(columns={0: "control_log_idio", 1: "top10_log_idio"}).dropna()
    grouped["spread"] = grouped["top10_log_idio"] - grouped["control_log_idio"]
    monthly_flow = panel.groupby(["month", "month_str"])["flow_shock_l1"].first()
    grouped = grouped.join(monthly_flow, how="left")
    return grouped.reset_index()


def event_bootstrap(spread: pd.DataFrame) -> dict:
    df = spread.replace([np.inf, -np.inf], np.nan).dropna(subset=["spread", "flow_shock_l1"]).copy()
    threshold = df["flow_shock_l1"].quantile(0.90)
    high = df.loc[df["flow_shock_l1"] >= threshold, "spread"].to_numpy(dtype=float)
    normal = df.loc[df["flow_shock_l1"] < threshold, "spread"].to_numpy(dtype=float)
    rng = np.random.default_rng(SEED)
    diffs = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        high_sample = rng.choice(high, size=len(high), replace=True)
        normal_sample = rng.choice(normal, size=len(high), replace=True)
        diffs[i] = high_sample.mean() - normal_sample.mean()
    diff = float(high.mean() - normal.mean())
    return {
        "threshold_flow_shock_l1": float(threshold),
        "n_high_shock_months": int(len(high)),
        "n_normal_months": int(len(normal)),
        "spread_diff_high_minus_normal": diff,
        "ci95": [float(x) for x in np.percentile(diffs, [2.5, 97.5])],
        "p_gt_0": float((np.sum(diffs <= 0.0) + 1) / (BOOTSTRAP_REPS + 1)),
    }


def serialize_regression(result: RegressionResult) -> dict:
    return {
        "name": result.name,
        "coefficient": result.coefficient,
        "t_stat": result.t_stat,
        "p_value": result.p_value,
        "n_obs": result.n_obs,
        "n_months": result.n_months,
        "n_stocks": result.n_stocks,
        "expected_sign": result.expected_sign,
        "harvey_pass_abs_t_gt_3": result.harvey_pass,
    }


def make_plot(month_controls: pd.DataFrame, spread: pd.DataFrame, regressions: list[RegressionResult]) -> str:
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=False)

    ax = axes[0]
    ax.plot(month_controls.index, month_controls["flow_shock"], color="steelblue", lw=1.0, label="SPY+IVV+VOO dollar-volume shock")
    ax.axhline(0, color="black", lw=0.6, alpha=0.5)
    ax.axhline(month_controls["flow_shock"].quantile(0.90), color="red", ls="--", lw=0.8, label="90th pct")
    ax.set_title("Passive-flow proxy: monthly ETF dollar-volume shock")
    ax.set_ylabel("z-score")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8)

    ax = axes[1]
    plot_df = spread.sort_values("month")
    ax.plot(plot_df["month"], plot_df["spread"], color="darkgreen", lw=1.0, label="Top10 - controls log idio RV")
    ax.axhline(0, color="black", lw=0.6, alpha=0.5)
    ax.set_title("Mega-cap residual-vol spread")
    ax.set_ylabel("log RV spread")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8)

    plt.tight_layout()
    path = os.path.join(OUT_DIR, "fig_flow_shock_idio_spread.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    names = [r.name for r in regressions]
    coefs = [r.coefficient for r in regressions]
    tstats = [r.t_stat for r in regressions]
    colors = ["#4C78A8" if c > 0 else "#B55D60" for c in coefs]
    bars = ax.bar(names, tstats, color=colors, alpha=0.85)
    ax.axhline(3.0, color="black", ls="--", lw=0.8)
    ax.axhline(-3.0, color="black", ls="--", lw=0.8)
    ax.axhline(0.0, color="black", lw=0.6)
    for bar, coef in zip(bars, coefs):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"coef={coef:.3f}",
            ha="center",
            va="bottom" if bar.get_height() >= 0 else "top",
            fontsize=8,
        )
    ax.set_ylabel("clustered t-stat")
    ax.set_title("Top10 x ETF-flow-shock interaction tests")
    ax.grid(True, axis="y", alpha=0.25)
    plt.tight_layout()
    path2 = os.path.join(OUT_DIR, "fig_interaction_tstats.png")
    plt.savefig(path2, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def verdict_from_results(primary: RegressionResult, event: dict) -> str:
    ci_low, ci_high = event["ci95"]
    if primary.harvey_pass and event["spread_diff_high_minus_normal"] > 0 and ci_low > 0:
        return "PASS"
    if primary.coefficient > 0 and abs(primary.t_stat) >= 2.0:
        return "MIXED_WEAK_PROXY"
    return "NULL_PROXY"


def main() -> None:
    data = load_data()
    panel, month_controls = build_monthly_panel(data)

    primary = fit_interaction(panel, "lagged_monthFE", "top10_flow_l1", month_fe=True)
    pooled = fit_interaction(panel, "lagged_pooled_controls", "top10_flow_l1", month_fe=False)
    contemporaneous = fit_interaction(panel, "contemporaneous_monthFE", "top10_flow_current", month_fe=True)

    spread = top10_minus_control_spread(panel)
    event = event_bootstrap(spread)
    make_plot(month_controls, spread, [primary, pooled, contemporaneous])

    verdict = verdict_from_results(primary, event)
    actual_start = str(panel["month"].min().date())
    actual_end = str(panel["month"].max().date())

    output = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Passive ETF-flow proxy and mega-cap idiosyncratic volatility",
        "verdict": verdict,
        "seed": SEED,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "data": {
            "source": "yfinance auto_adjust=True daily close/volume",
            "requested_start": DATA_START,
            "requested_end_exclusive": DATA_END,
            "actual_monthly_panel_start": actual_start,
            "actual_monthly_panel_end": actual_end,
            "n_panel_rows": int(len(panel.dropna(subset=["log_idio_rv"]))),
            "n_months": int(panel["month_str"].nunique()),
            "n_stocks": int(panel["ticker"].nunique()),
            "etfs": ETF_TICKERS,
            "top10_tickers": TOP10_TICKERS,
            "control_tickers": CONTROL_TICKERS,
            "flow_data_limitation": "SPY/IVV/VOO dollar volume is a liquidity/attention proxy, not historical AUM flow or creation-redemption flow.",
        },
        "method": {
            "target": "monthly CAPM residual realized variance, annualized, log-transformed",
            "flow_proxy": "rolling 36-month z-score of monthly change in aggregate SPY+IVV+VOO dollar volume",
            "primary_spec": "log_idio_rv_t ~ top10 * flow_shock_{t-1} + lag_log_idio_rv + stock FE + month FE, clustered by month",
            "lookahead_guard": "primary uses flow_shock_l1; target month t does not use ETF volume from month t",
            "harvey_threshold": "|t| > 3.0 with expected positive sign",
            "bootstrap_reps": BOOTSTRAP_REPS,
        },
        "regressions": {
            "primary_lagged_monthFE": serialize_regression(primary),
            "lagged_pooled_controls": serialize_regression(pooled),
            "contemporaneous_monthFE_diagnostic": serialize_regression(contemporaneous),
        },
        "event_study": event,
        "interpretation": "",
        "references": [
            {
                "title": "Passive Investing and the Rise of Mega-Firms",
                "authors": "Hao Jiang, Dimitri Vayanos, Lu Zheng",
                "venue": "The Review of Financial Studies, 2025",
                "url": "https://academic.oup.com/rfs/article/38/12/3461/8280528",
            },
            {
                "title": "Do ETFs Increase Volatility?",
                "authors": "Itzhak Ben-David, Francesco Franzoni, Rabih Moussawi",
                "venue": "Journal of Finance / NBER working paper lineage",
                "url": "https://www.nber.org/papers/w20071",
            },
            {
                "title": "The implications of passive investing for securities markets",
                "authors": "Vladyslav Sushko, Grant Turner",
                "venue": "BIS Quarterly Review, 2018",
                "url": "https://www.bis.org/publ/qtrpdf/r_qt1803j.htm",
            },
        ],
        "artifacts": [
            "README.md",
            f"{EXPERIMENT_ID}.py",
            f"{EXPERIMENT_ID}_results.json",
            "fig_flow_shock_idio_spread.png",
            "fig_interaction_tstats.png",
        ],
    }

    primary_summary = output["regressions"]["primary_lagged_monthFE"]
    direction = "positive" if primary_summary["coefficient"] > 0 else "negative"
    output["interpretation"] = (
        f"Primary lagged month-FE interaction is {direction} "
        f"(coef={primary_summary['coefficient']:.6f}, t={primary_summary['t_stat']:.3f}, "
        f"p={primary_summary['p_value']:.4g}). Verdict={verdict}. Because the flow measure is ETF dollar volume, "
        "not AUM flow, the result should be read as a free-data proxy diagnostic rather than causal evidence."
    )

    out_path = os.path.join(OUT_DIR, f"{EXPERIMENT_ID}_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False, default=str)

    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
