"""K1503: Factor-MAX and next-month factor ETF returns / volatility.

This experiment tests whether prior-month MAX for a small factor ETF universe
predicts next-month underperformance or higher volatility. The design is a
monthly, ex-ante cross-sectional pilot using yfinance data only.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

SEED = 42
RNG = np.random.default_rng(SEED)

OUT_DIR = Path(__file__).resolve().parent
DATA_DIR = OUT_DIR / "data"
FIG_DIR = OUT_DIR / "figures"

START_DATE = "2010-01-01"
END_DATE = "2026-06-16"  # yfinance end is exclusive
FACTOR_TICKERS = ["MTUM", "QUAL", "VLUE", "USMV", "SIZE"]
BENCHMARK_TICKER = "SPY"
ALL_TICKERS = FACTOR_TICKERS + [BENCHMARK_TICKER]
BOOT_REPS = 5000
HAC_LAG = 3
HARVEY_T_ABS = 3.0


@dataclass
class MeanTest:
    n_months: int
    mean: float
    annualized_mean: float
    hac_t: float
    hac_p_two_sided: float
    ci_95_low: float
    ci_95_high: float
    prob_mean_gt_zero: float
    harvey_pass_abs_t_gt_3: bool


def last_complete_month_end() -> pd.Timestamp:
    return (pd.Timestamp(END_DATE).to_period("M") - 1).to_timestamp("M")


def expected_sign_for_outcome(y_col: str) -> str:
    return "negative" if y_col in {"monthly_excess_vs_spy", "monthly_log_return"} else "positive"


def fetch_prices() -> pd.DataFrame:
    cache_path = DATA_DIR / "prices_yfinance.csv"
    if cache_path.exists():
        prices = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        return prices[ALL_TICKERS].sort_index()

    raw = yf.download(
        ALL_TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    prices: dict[str, pd.Series] = {}
    for ticker in ALL_TICKERS:
        try:
            close = raw[ticker]["Close"]
        except Exception:
            close = raw["Close"][ticker]
        prices[ticker] = close.rename(ticker).dropna()
    out = pd.DataFrame(prices).sort_index()
    out.to_csv(cache_path)
    return out


def month_end_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index.to_period("M").to_timestamp("M")


def top_k_mean(values: pd.Series, k: int = 5) -> float:
    clean = values.dropna()
    if clean.empty:
        return float("nan")
    return float(clean.nlargest(min(k, len(clean))).mean())


def build_monthly_panel(prices: pd.DataFrame) -> pd.DataFrame:
    simple_ret = prices.pct_change()
    log_ret = np.log(prices / prices.shift(1))
    month_idx = month_end_index(log_ret.index)

    records: list[dict] = []
    for ticker in ALL_TICKERS:
        df = pd.DataFrame(
            {
                "simple_ret": simple_ret[ticker],
                "log_ret": log_ret[ticker],
                "month_end": month_idx,
            },
            index=prices.index,
        ).dropna()
        grouped = df.groupby("month_end", sort=True)
        for month_end, g in grouped:
            if len(g) < 10:
                continue
            records.append(
                {
                    "month_end": pd.Timestamp(month_end),
                    "ticker": ticker,
                    "n_days": int(len(g)),
                    "monthly_log_return": float(g["log_ret"].sum()),
                    "monthly_simple_return": float(np.exp(g["log_ret"].sum()) - 1.0),
                    "monthly_rv_ann": float(g["log_ret"].std(ddof=1) * np.sqrt(252)),
                    "max_daily_return": float(g["simple_ret"].max()),
                    "avg_top5_daily_return": top_k_mean(g["simple_ret"], k=5),
                    "min_daily_return": float(g["simple_ret"].min()),
                }
            )

    monthly = pd.DataFrame(records).sort_values(["ticker", "month_end"])
    monthly = monthly[monthly["month_end"] <= last_complete_month_end()].copy()
    spy = (
        monthly[monthly["ticker"] == BENCHMARK_TICKER][
            ["month_end", "monthly_log_return"]
        ]
        .rename(columns={"monthly_log_return": "spy_monthly_log_return"})
        .copy()
    )
    panel = monthly[monthly["ticker"].isin(FACTOR_TICKERS)].merge(
        spy, on="month_end", how="inner"
    )
    panel["monthly_excess_vs_spy"] = (
        panel["monthly_log_return"] - panel["spy_monthly_log_return"]
    )

    lag_cols = [
        "max_daily_return",
        "avg_top5_daily_return",
        "monthly_log_return",
        "monthly_rv_ann",
    ]
    for col in lag_cols:
        # Explicit lag guard: signal from t-1, return/volatility at t.
        panel[f"{col}_lag1"] = panel.groupby("ticker")[col].shift(1)

    analysis = panel.dropna(
        subset=[
            "max_daily_return_lag1",
            "avg_top5_daily_return_lag1",
            "monthly_log_return_lag1",
            "monthly_rv_ann_lag1",
            "monthly_excess_vs_spy",
            "monthly_rv_ann",
        ]
    ).copy()
    for col in [
        "max_daily_return_lag1",
        "avg_top5_daily_return_lag1",
        "monthly_log_return_lag1",
        "monthly_rv_ann_lag1",
    ]:
        analysis[f"{col}_z"] = analysis.groupby("month_end")[col].transform(
            lambda s: (s - s.mean()) / s.std(ddof=0)
        )
    return analysis.replace([np.inf, -np.inf], np.nan).dropna()


def newey_west_mean_t(values: pd.Series, lag: int = HAC_LAG) -> tuple[float, float]:
    x = values.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    centered = x - x.mean()
    gamma0 = float(np.dot(centered, centered) / n)
    long_var = gamma0
    max_lag = min(lag, n - 1)
    for ell in range(1, max_lag + 1):
        gamma = float(np.dot(centered[ell:], centered[:-ell]) / n)
        weight = 1.0 - ell / (max_lag + 1.0)
        long_var += 2.0 * weight * gamma
    se = float(np.sqrt(max(long_var, 0.0) / n))
    if se == 0:
        return float("nan"), float("nan")
    t_stat = float(x.mean() / se)
    p_value = float(2.0 * stats.t.sf(abs(t_stat), df=n - 1))
    return t_stat, p_value


def bootstrap_mean(values: pd.Series, reps: int = BOOT_REPS) -> dict:
    x = values.dropna().to_numpy(dtype=float)
    idx = RNG.integers(0, len(x), size=(reps, len(x)))
    means = x[idx].mean(axis=1)
    return {
        "ci_95_low": float(np.quantile(means, 0.025)),
        "ci_95_high": float(np.quantile(means, 0.975)),
        "prob_mean_gt_zero": float((means > 0).mean()),
    }


def mean_test(values: pd.Series, annualize: bool) -> MeanTest:
    clean = values.dropna()
    t_stat, p_value = newey_west_mean_t(clean)
    boot = bootstrap_mean(clean)
    mean = float(clean.mean())
    return MeanTest(
        n_months=int(clean.shape[0]),
        mean=mean,
        annualized_mean=float(mean * 12 if annualize else mean),
        hac_t=t_stat,
        hac_p_two_sided=p_value,
        ci_95_low=boot["ci_95_low"],
        ci_95_high=boot["ci_95_high"],
        prob_mean_gt_zero=boot["prob_mean_gt_zero"],
        harvey_pass_abs_t_gt_3=bool(abs(t_stat) > HARVEY_T_ABS)
        if np.isfinite(t_stat)
        else False,
    )


def build_sort_tests(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows: list[dict] = []
    for month_end, g in panel.groupby("month_end", sort=True):
        if g["ticker"].nunique() < 4:
            continue
        sorted_g = g.sort_values("max_daily_return_lag1")
        low1 = sorted_g.iloc[0]
        high1 = sorted_g.iloc[-1]
        low2 = sorted_g.head(2)
        high2 = sorted_g.tail(2)
        rows.append(
            {
                "month_end": month_end,
                "low1_ticker": low1["ticker"],
                "high1_ticker": high1["ticker"],
                "low1_minus_high1_excess_return": float(
                    low1["monthly_excess_vs_spy"] - high1["monthly_excess_vs_spy"]
                ),
                "low2_minus_high2_excess_return": float(
                    low2["monthly_excess_vs_spy"].mean()
                    - high2["monthly_excess_vs_spy"].mean()
                ),
                "high1_minus_low1_rv": float(
                    high1["monthly_rv_ann"] - low1["monthly_rv_ann"]
                ),
                "high2_minus_low2_rv": float(
                    high2["monthly_rv_ann"].mean() - low2["monthly_rv_ann"].mean()
                ),
                "high1_max_lag1": float(high1["max_daily_return_lag1"]),
                "low1_max_lag1": float(low1["max_daily_return_lag1"]),
            }
        )
    sort_df = pd.DataFrame(rows).sort_values("month_end")
    tests = {
        "low1_minus_high1_excess_return": asdict(
            mean_test(sort_df["low1_minus_high1_excess_return"], annualize=True)
        ),
        "low2_minus_high2_excess_return": asdict(
            mean_test(sort_df["low2_minus_high2_excess_return"], annualize=True)
        ),
        "high1_minus_low1_rv": asdict(
            mean_test(sort_df["high1_minus_low1_rv"], annualize=False)
        ),
        "high2_minus_low2_rv": asdict(
            mean_test(sort_df["high2_minus_low2_rv"], annualize=False)
        ),
    }
    return sort_df, tests


def fama_macbeth(panel: pd.DataFrame, y_col: str, x_col: str) -> dict:
    betas: list[dict] = []
    for month_end, g in panel.groupby("month_end", sort=True):
        if g["ticker"].nunique() < 4:
            continue
        y = g[y_col].to_numpy(dtype=float)
        x = sm.add_constant(g[[x_col]].to_numpy(dtype=float), has_constant="add")
        fit = sm.OLS(y, x).fit()
        betas.append(
            {
                "month_end": pd.Timestamp(month_end),
                "beta": float(fit.params[1]),
                "n_assets": int(g["ticker"].nunique()),
            }
        )
    beta_df = pd.DataFrame(betas).sort_values("month_end")
    mt = asdict(mean_test(beta_df["beta"], annualize=False))
    mt["expected_sign"] = expected_sign_for_outcome(y_col)
    mt["mean_beta"] = mt.pop("mean")
    mt["beta_series_path"] = f"data/fama_macbeth_{y_col}_{x_col}.csv"
    beta_df.to_csv(OUT_DIR / mt["beta_series_path"], index=False)
    return mt


def pooled_fixed_effect(panel: pd.DataFrame, y_col: str, x_col: str) -> dict:
    df = panel[["month_end", "ticker", y_col, x_col]].dropna().copy()
    d_ticker = pd.get_dummies(df["ticker"], prefix="ticker", drop_first=True)
    d_month = pd.get_dummies(df["month_end"].astype(str), prefix="m", drop_first=True)
    x = pd.concat([df[[x_col]].astype(float), d_ticker, d_month], axis=1)
    x = sm.add_constant(x, has_constant="add")
    fit = sm.OLS(df[y_col].astype(float), x.astype(float)).fit(
        cov_type="cluster", cov_kwds={"groups": df["month_end"].astype(str)}
    )
    coef = float(fit.params[x_col])
    t_stat = float(fit.tvalues[x_col])
    p_value = float(fit.pvalues[x_col])
    return {
        "n_obs": int(df.shape[0]),
        "n_months": int(df["month_end"].nunique()),
        "n_assets": int(df["ticker"].nunique()),
        "coef": coef,
        "cluster_t_by_month": t_stat,
        "cluster_p_two_sided": p_value,
        "harvey_pass_abs_t_gt_3": bool(abs(t_stat) > HARVEY_T_ABS),
        "expected_sign": expected_sign_for_outcome(y_col),
    }


def make_figures(panel: pd.DataFrame, sort_df: pd.DataFrame, sort_tests: dict) -> list[str]:
    paths: list[str] = []

    avg_max = (
        panel.groupby("ticker")["max_daily_return_lag1"]
        .mean()
        .sort_values(ascending=False)
        * 100
    )
    avg_rv = panel.groupby("ticker")["monthly_rv_ann"].mean().reindex(avg_max.index) * 100
    fig, ax1 = plt.subplots(figsize=(8.5, 5))
    x = np.arange(len(avg_max))
    ax1.bar(x - 0.18, avg_max.values, width=0.36, label="Prior-month MAX", color="#3f6f8f")
    ax1.set_ylabel("MAX daily return (%)")
    ax2 = ax1.twinx()
    ax2.bar(x + 0.18, avg_rv.values, width=0.36, label="Current-month RV", color="#c26d3f")
    ax2.set_ylabel("Annualized RV (%)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(avg_max.index)
    ax1.set_title("K1503 Factor ETF MAX and Realized Volatility")
    ax1.grid(axis="y", alpha=0.25)
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
    fig.tight_layout()
    path = FIG_DIR / "k1503_factor_max_by_ticker.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(str(path.relative_to(OUT_DIR)))

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    axes[0].hist(sort_df["low2_minus_high2_excess_return"] * 100, bins=24, color="#5b7f5b", alpha=0.85)
    axes[0].axvline(
        sort_tests["low2_minus_high2_excess_return"]["mean"] * 100,
        color="black",
        linestyle="--",
        linewidth=1.2,
    )
    axes[0].set_title("Low-MAX minus High-MAX next-month excess return")
    axes[0].set_xlabel("Monthly spread (%)")
    axes[0].set_ylabel("Count")
    axes[0].grid(alpha=0.25)

    axes[1].hist(sort_df["high2_minus_low2_rv"] * 100, bins=24, color="#8b5f5b", alpha=0.85)
    axes[1].axvline(
        sort_tests["high2_minus_low2_rv"]["mean"] * 100,
        color="black",
        linestyle="--",
        linewidth=1.2,
    )
    axes[1].set_title("High-MAX minus Low-MAX next-month RV")
    axes[1].set_xlabel("Annualized RV spread (pp)")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "k1503_sort_spread_distributions.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(str(path.relative_to(OUT_DIR)))

    rolling = sort_df.set_index("month_end")[
        ["low2_minus_high2_excess_return", "high2_minus_low2_rv"]
    ].rolling(12, min_periods=6).mean()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(
        rolling.index,
        rolling["low2_minus_high2_excess_return"] * 100,
        label="Low2-High2 excess return (%, 12m avg)",
        color="#356b56",
    )
    ax.plot(
        rolling.index,
        rolling["high2_minus_low2_rv"] * 100,
        label="High2-Low2 RV (pp, 12m avg)",
        color="#9a593a",
    )
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("K1503 Rolling Sort Spread Diagnostics")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = FIG_DIR / "k1503_rolling_sort_spreads.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(str(path.relative_to(OUT_DIR)))

    return paths


def verdict_from_results(sort_tests: dict, fm: dict, pooled: dict) -> dict:
    return_tests = [
        sort_tests["low1_minus_high1_excess_return"],
        sort_tests["low2_minus_high2_excess_return"],
        fm["monthly_excess_vs_spy"],
        pooled["monthly_excess_vs_spy"],
    ]
    vol_tests = [
        sort_tests["high1_minus_low1_rv"],
        sort_tests["high2_minus_low2_rv"],
        fm["monthly_rv_ann"],
        pooled["monthly_rv_ann"],
    ]

    return_directional = [
        t["mean"] > 0 if "mean" in t else t.get("mean_beta", 0) < 0
        for t in return_tests
    ]
    vol_directional = [
        t["mean"] > 0 if "mean" in t else t.get("mean_beta", t.get("coef", 0)) > 0
        for t in vol_tests
    ]
    return_harvey_passes = sum(bool(t.get("harvey_pass_abs_t_gt_3")) for t in return_tests)
    vol_harvey_passes = sum(bool(t.get("harvey_pass_abs_t_gt_3")) for t in vol_tests)
    harvey_passes = return_harvey_passes + vol_harvey_passes

    if harvey_passes >= 2 and all(return_directional[:2]) and all(vol_directional[:2]):
        overall = "PASS"
    elif harvey_passes >= 1:
        overall = "MIXED"
    else:
        overall = "NULL"

    return {
        "overall": overall,
        "harvey_pass_count_across_8_main_tests": int(harvey_passes),
        "return_harvey_pass_count": int(return_harvey_passes),
        "vol_harvey_pass_count": int(vol_harvey_passes),
        "return_directional_count": int(sum(return_directional)),
        "vol_directional_count": int(sum(vol_directional)),
        "plain_english": (
            "Prior-month factor-MAX does not support the next-month "
            "underperformance hypothesis, but it strongly predicts higher "
            "next-month realized volatility in this small factor ETF universe."
            if vol_harvey_passes and not return_harvey_passes
            else "Prior-month factor-MAX does not produce a robust Harvey-level "
            "signal for next-month factor ETF underperformance or higher "
            "volatility in this small yfinance ETF universe."
            if overall == "NULL"
            else "At least one main test passes the Harvey threshold; inspect direction and robustness before using."
        ),
    }


def main() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    prices = fetch_prices()
    panel = build_monthly_panel(prices)
    panel.to_csv(DATA_DIR / "monthly_factor_max_panel.csv", index=False)

    sort_df, sort_tests = build_sort_tests(panel)
    sort_df.to_csv(DATA_DIR / "monthly_sort_spreads.csv", index=False)

    fm = {
        "monthly_excess_vs_spy": fama_macbeth(
            panel, "monthly_excess_vs_spy", "max_daily_return_lag1_z"
        ),
        "monthly_rv_ann": fama_macbeth(panel, "monthly_rv_ann", "max_daily_return_lag1_z"),
    }
    pooled = {
        "monthly_excess_vs_spy": pooled_fixed_effect(
            panel, "monthly_excess_vs_spy", "max_daily_return_lag1_z"
        ),
        "monthly_rv_ann": pooled_fixed_effect(panel, "monthly_rv_ann", "max_daily_return_lag1_z"),
    }
    figures = make_figures(panel, sort_df, sort_tests)

    data_summary = {
        "tickers": FACTOR_TICKERS,
        "benchmark": BENCHMARK_TICKER,
        "price_source": "yfinance adjusted close via yf.download(auto_adjust=True)",
        "price_start_by_ticker": {
            t: prices[t].dropna().index.min().strftime("%Y-%m-%d") for t in ALL_TICKERS
        },
        "price_end_by_ticker": {
            t: prices[t].dropna().index.max().strftime("%Y-%m-%d") for t in ALL_TICKERS
        },
        "analysis_start": panel["month_end"].min().strftime("%Y-%m-%d"),
        "analysis_end": panel["month_end"].max().strftime("%Y-%m-%d"),
        "last_complete_month_end_rule": last_complete_month_end().strftime("%Y-%m-%d"),
        "panel_rows": int(panel.shape[0]),
        "months": int(panel["month_end"].nunique()),
        "assets": int(panel["ticker"].nunique()),
    }
    results = {
        "experiment_id": "K1503",
        "title": "Factor-MAX as a predictor of next-month factor ETF returns and volatility",
        "run_timestamp": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "task_id": "research_factor_max",
        "data": data_summary,
        "literature_checked": [
            {
                "title": "Factor MAX and Predictable Factor Returns",
                "authors": "Liyao Wang and Ming Zeng",
                "source": "SSRN / HKBU Scholars, 2026 working paper",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6053114",
            },
            {
                "title": "Maxing out: Stocks as lotteries and the cross-section of expected returns",
                "authors": "Turan G. Bali, Nusret Cakici, Robert F. Whitelaw",
                "source": "Journal of Financial Economics 99(2), 2011",
                "url": "https://econpapers.repec.org/RePEc:eee:jfinec:v:99:y:2011:i:2:p:427-446",
            },
            {
                "title": "A lottery-demand-based explanation of the beta anomaly",
                "authors": "Turan G. Bali, Stephen J. Brown, Scott Murray, Yi Tang",
                "source": "Journal of Financial and Quantitative Analysis 52(6), 2017",
                "url": "https://doi.org/10.1017/S0022109017000928",
            },
        ],
        "related_prior_findings": [
            "K89: factor tilts did not improve the 50/50 VT framework.",
            "K566: factor timing plus VT was null; factor ETF correlations with SPY were high.",
            "K876: MTUM crash risk is partly distinct from SPY crashes, but VIX overlays did not pass.",
            "K1446: USMV is lower-risk than MTUM/QUAL/VLUE/SPY on descriptive risk metrics.",
        ],
        "methodology": {
            "max_definition": "maximum daily simple return during the prior calendar month",
            "top5_robustness_definition": "average of the five highest daily simple returns during the prior calendar month; computed but not used as main signal",
            "outcome_return": "current-month factor ETF log return minus current-month SPY log return",
            "outcome_volatility": "current-month realized volatility from daily log returns, annualized",
            "main_tests": [
                "Monthly sort: low prior-MAX ETF(s) minus high prior-MAX ETF(s) next-month excess return.",
                "Monthly sort: high prior-MAX ETF(s) minus low prior-MAX ETF(s) next-month realized volatility.",
                "Fama-MacBeth monthly cross-sectional beta of outcome on prior-MAX z-score.",
                "Pooled OLS with ticker and month fixed effects, clustered by month.",
            ],
            "statistical_gate": "Harvey-style internal threshold |t| > 3 for main tests; bootstrap CI with fixed seed for sort spreads.",
        },
        "lookahead_controls": {
            "feature_lag": "panel[f'{col}_lag1'] = panel.groupby('ticker')[col].shift(1)",
            "signal_timing": "month t-1 daily returns form MAX; month t return and volatility are outcomes",
            "same_day_rule": "No same-month MAX is used to predict same-month outcome.",
            "forward_label_overlap": "Monthly outcomes are one non-overlapping calendar month, so K1337 forward-label training leakage does not apply.",
        },
        "sort_tests": sort_tests,
        "fama_macbeth": fm,
        "pooled_fixed_effect": pooled,
        "verdict": verdict_from_results(sort_tests, fm, pooled),
        "figures": figures,
        "limitations": [
            "Only five liquid factor ETFs are used; this is not the original stock-level MAX anomaly universe.",
            "ETF-level MAX may mix underlying factor lottery demand with ETF trading microstructure.",
            "The common ETF sample begins after the newest ETF has enough observations, so it cannot test pre-2013 factor cycles.",
            "No options or short-sale borrow-fee data are used.",
        ],
    }

    out_path = OUT_DIR / "k1503_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


if __name__ == "__main__":
    payload = main()
    verdict = payload["verdict"]
    print(json.dumps({"experiment_id": payload["experiment_id"], "verdict": verdict}, indent=2))
