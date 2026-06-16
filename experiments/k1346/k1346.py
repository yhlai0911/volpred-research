"""K1346: Lottery-stock basket vol-of-vol and crisis amplification.

This is a yfinance-only pilot. It builds a monthly lottery-stock proxy basket
from lagged low-price, high-idiosyncratic-volatility, and high-MAX features,
then tests whether the basket's realized volatility and volatility-of-volatility
amplify in risk-off months and lead SPY/IWM tail volatility.
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

START_DATE = "2018-01-01"
END_DATE = "2026-06-17"  # yfinance end is exclusive
ROLL_IDIO_DAYS = 63
ROLL_MAX_DAYS = 21
ROLL_VOV_DAYS = 5
MIN_MONTH_DAYS = 10
MIN_FEATURE_DAYS = 40
MIN_TICKERS_PER_MONTH = 20
TOP_FRAC = 0.20
BOOT_REPS = 5000
HAC_LAG_MONTHS = 3
HARVEY_T_ABS = 3.0

# Current liquid retail / speculative / low-price candidate universe.
# This is intentionally a proxy universe, not a survivorship-free CRSP universe.
UNIVERSE_TICKERS = [
    "GME",
    "AMC",
    "KOSS",
    "BB",
    "OPEN",
    "KSS",
    "PLTR",
    "SOFI",
    "HOOD",
    "RIVN",
    "LCID",
    "F",
    "CHWY",
    "DKNG",
    "AFRM",
    "UPST",
    "MARA",
    "RIOT",
    "COIN",
    "CVNA",
    "TLRY",
    "RBLX",
    "SNAP",
    "PTON",
    "BYND",
    "NIO",
    "XPEV",
    "LI",
    "BILI",
    "U",
    "AI",
    "ROOT",
    "LMND",
    "FUBO",
    "BLNK",
    "QS",
    "RUN",
    "SPCE",
    "SNDL",
    "HUT",
    "CLSK",
    "WULF",
    "BTBT",
    "CIFR",
    "IONQ",
    "QBTS",
    "RGTI",
    "SOUN",
    "BBAI",
    "LUNR",
    "JOBY",
    "ACHR",
    "ENVX",
    "LAZR",
    "MVIS",
    "W",
    "GPRO",
    "CCL",
    "NCLH",
    "AAL",
    "JBLU",
    "CGC",
    "CRON",
    "GRAB",
    "NU",
    "SE",
    "ROKU",
    "PINS",
    "ETSY",
    "DASH",
    "UBER",
    "LYFT",
    "DNA",
    "RKLB",
    "ASTS",
]
BENCHMARK_TICKERS = ["SPY", "IWM", "^VIX"]
ALL_TICKERS = UNIVERSE_TICKERS + BENCHMARK_TICKERS


@dataclass
class MeanDiffTest:
    n_group: int
    n_other: int
    mean_group: float
    mean_other: float
    diff: float
    ratio: float
    welch_t: float
    welch_p_two_sided: float
    bootstrap_ci_95_low: float
    bootstrap_ci_95_high: float
    prob_diff_gt_zero: float
    harvey_pass_abs_t_gt_3: bool


@dataclass
class LeadTest:
    y: str
    x: str
    n_months: int
    coef: float
    hac_t: float
    hac_p_two_sided: float
    bonferroni_p: float
    positive_expected: bool
    harvey_pass_abs_t_gt_3: bool
    bonferroni_pass_5pct: bool


def zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(np.nan, index=s.index)
    return (s - s.mean()) / std


def safe_ratio(a: float, b: float) -> float:
    if not np.isfinite(a) or not np.isfinite(b) or b == 0:
        return float("nan")
    return float(a / b)


def last_complete_month_end() -> pd.Timestamp:
    return (pd.Timestamp(END_DATE).to_period("M") - 1).to_timestamp("M")


def extract_field(raw: pd.DataFrame, ticker: str, field: str) -> pd.Series | None:
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0)
        level1 = raw.columns.get_level_values(1)
        if ticker in level0 and field in raw[ticker]:
            return raw[ticker][field].rename(ticker)
        if field in level0 and ticker in level1:
            return raw[field][ticker].rename(ticker)
        return None
    if field in raw.columns:
        return raw[field].rename(ticker)
    return None


def fetch_close_prices() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / "close_prices_yfinance.csv"
    if cache_path.exists():
        return pd.read_csv(cache_path, index_col=0, parse_dates=True).sort_index()

    raw = yf.download(
        ALL_TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    closes: dict[str, pd.Series] = {}
    for ticker in ALL_TICKERS:
        close = extract_field(raw, ticker, "Close")
        if close is None:
            continue
        clean = close.dropna()
        if clean.empty:
            continue
        closes[ticker] = clean

    prices = pd.DataFrame(closes).sort_index()
    prices.to_csv(cache_path)
    return prices


def valid_stock_universe(prices: pd.DataFrame) -> list[str]:
    required_last = pd.Timestamp("2025-01-01")
    valid: list[str] = []
    for ticker in UNIVERSE_TICKERS:
        if ticker not in prices:
            continue
        s = prices[ticker].dropna()
        if len(s) >= 252 and s.index.max() >= required_last:
            valid.append(ticker)
    return valid


def rolling_beta_residuals(simple_ret: pd.DataFrame, spy_ret: pd.Series, tickers: list[str]) -> pd.DataFrame:
    spy_var = spy_ret.rolling(ROLL_IDIO_DAYS, min_periods=MIN_FEATURE_DAYS).var()
    residuals: dict[str, pd.Series] = {}
    for ticker in tickers:
        cov = simple_ret[ticker].rolling(ROLL_IDIO_DAYS, min_periods=MIN_FEATURE_DAYS).cov(spy_ret)
        beta = cov / spy_var
        residuals[ticker] = (simple_ret[ticker] - beta * spy_ret).rename(ticker)
    return pd.DataFrame(residuals)


def build_monthly_stock_panel(prices: pd.DataFrame, stock_tickers: list[str]) -> pd.DataFrame:
    simple_ret = prices[stock_tickers + ["SPY", "IWM"]].pct_change()
    log_ret = np.log(prices[stock_tickers + ["SPY", "IWM"]] / prices[stock_tickers + ["SPY", "IWM"]].shift(1))
    residuals = rolling_beta_residuals(simple_ret, simple_ret["SPY"], stock_tickers)
    idio_vol = residuals.rolling(ROLL_IDIO_DAYS, min_periods=MIN_FEATURE_DAYS).std() * np.sqrt(252)
    max_return = simple_ret[stock_tickers].rolling(ROLL_MAX_DAYS, min_periods=MIN_MONTH_DAYS).max()

    records: list[dict] = []
    for ticker in stock_tickers:
        df = pd.DataFrame(
            {
                "price": prices[ticker],
                "simple_ret": simple_ret[ticker],
                "log_ret": log_ret[ticker],
                "idio_vol_63_ann": idio_vol[ticker],
                "max_return_21d": max_return[ticker],
            }
        ).dropna(subset=["price", "simple_ret", "log_ret"])
        df["month"] = df.index.to_period("M").to_timestamp("M")
        for month, g in df.groupby("month", sort=True):
            if len(g) < MIN_MONTH_DAYS:
                continue
            rolling_vol = g["log_ret"].rolling(ROLL_VOV_DAYS, min_periods=ROLL_VOV_DAYS).std() * np.sqrt(252)
            records.append(
                {
                    "month": pd.Timestamp(month),
                    "ticker": ticker,
                    "n_days": int(len(g)),
                    "monthly_log_return": float(g["log_ret"].sum()),
                    "monthly_rv_ann": float(g["log_ret"].std(ddof=1) * np.sqrt(252)),
                    "monthly_vov": float(rolling_vol.std(ddof=1)),
                    "feature_price": float(g["price"].iloc[-1]),
                    "feature_log_price": float(np.log(g["price"].iloc[-1])),
                    "feature_idio_vol_63_ann": float(g["idio_vol_63_ann"].iloc[-1]),
                    "feature_max_return_21d": float(g["max_return_21d"].iloc[-1]),
                }
            )

    panel = pd.DataFrame(records).sort_values(["ticker", "month"])
    panel = panel[panel["month"] <= last_complete_month_end()].copy()
    feature_cols = [
        "feature_log_price",
        "feature_idio_vol_63_ann",
        "feature_max_return_21d",
    ]
    for col in feature_cols:
        # Explicit lookahead guard: month t basket uses month t-1 features.
        panel[f"{col}_lag1"] = panel.groupby("ticker")[col].shift(1)
    panel = panel.dropna(subset=[f"{col}_lag1" for col in feature_cols]).copy()

    scored_rows: list[pd.DataFrame] = []
    for month, g in panel.groupby("month", sort=True):
        if g["ticker"].nunique() < MIN_TICKERS_PER_MONTH:
            continue
        h = g.copy()
        h["z_low_price_lag1"] = -zscore(h["feature_log_price_lag1"])
        h["z_idio_vol_lag1"] = zscore(np.log(h["feature_idio_vol_63_ann_lag1"].clip(lower=1e-8)))
        h["z_max_return_lag1"] = zscore(h["feature_max_return_21d_lag1"])
        h["lottery_score_lag1"] = h[
            ["z_low_price_lag1", "z_idio_vol_lag1", "z_max_return_lag1"]
        ].mean(axis=1)
        scored_rows.append(h)
    return pd.concat(scored_rows, ignore_index=True).dropna(subset=["lottery_score_lag1"])


def realized_stats(log_returns: pd.Series) -> dict[str, float]:
    clean = log_returns.dropna()
    if len(clean) < MIN_MONTH_DAYS:
        return {"log_return": np.nan, "rv_ann": np.nan, "vov": np.nan, "n_days": len(clean)}
    rolling_vol = clean.rolling(ROLL_VOV_DAYS, min_periods=ROLL_VOV_DAYS).std() * np.sqrt(252)
    return {
        "log_return": float(clean.sum()),
        "rv_ann": float(clean.std(ddof=1) * np.sqrt(252)),
        "vov": float(rolling_vol.std(ddof=1)),
        "n_days": int(len(clean)),
    }


def build_monthly_basket(prices: pd.DataFrame, panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stock_tickers = sorted(panel["ticker"].unique())
    log_ret = np.log(prices[stock_tickers + ["SPY", "IWM"]] / prices[stock_tickers + ["SPY", "IWM"]].shift(1))
    selections: list[dict] = []
    monthly_rows: list[dict] = []

    for month, g in panel.groupby("month", sort=True):
        n_select = max(5, int(np.ceil(g["ticker"].nunique() * TOP_FRAC)))
        selected = g.sort_values("lottery_score_lag1", ascending=False).head(n_select)
        selected_tickers = selected["ticker"].tolist()
        month_mask = log_ret.index.to_period("M").to_timestamp("M") == month
        daily = log_ret.loc[month_mask, selected_tickers]
        min_names = max(3, int(np.ceil(len(selected_tickers) * 0.5)))
        basket_daily = daily.where(daily.notna().sum(axis=1) >= min_names).mean(axis=1)

        basket = realized_stats(basket_daily)
        spy = realized_stats(log_ret.loc[month_mask, "SPY"])
        iwm = realized_stats(log_ret.loc[month_mask, "IWM"])
        if not np.isfinite(basket["rv_ann"]):
            continue

        selections.append(
            {
                "month": month.strftime("%Y-%m-%d"),
                "n_selected": len(selected_tickers),
                "tickers": selected_tickers,
                "median_lag_price": float(np.exp(selected["feature_log_price_lag1"]).median()),
                "median_lag_idio_vol_ann": float(selected["feature_idio_vol_63_ann_lag1"].median()),
                "median_lag_max_return_21d": float(selected["feature_max_return_21d_lag1"].median()),
                "mean_lottery_score_lag1": float(selected["lottery_score_lag1"].mean()),
            }
        )
        monthly_rows.append(
            {
                "month": month,
                "n_selected": len(selected_tickers),
                "basket_log_return": basket["log_return"],
                "basket_rv_ann": basket["rv_ann"],
                "basket_vov": basket["vov"],
                "spy_log_return": spy["log_return"],
                "spy_rv_ann": spy["rv_ann"],
                "spy_vov": spy["vov"],
                "iwm_log_return": iwm["log_return"],
                "iwm_rv_ann": iwm["rv_ann"],
                "iwm_vov": iwm["vov"],
                "median_lag_price": float(np.exp(selected["feature_log_price_lag1"]).median()),
                "median_lag_idio_vol_ann": float(selected["feature_idio_vol_63_ann_lag1"].median()),
                "median_lag_max_return_21d": float(selected["feature_max_return_21d_lag1"].median()),
            }
        )

    monthly = pd.DataFrame(monthly_rows).sort_values("month")
    if "^VIX" in prices:
        vix = prices["^VIX"].dropna().copy()
        vix_month = (
            pd.DataFrame({"vix": vix, "month": vix.index.to_period("M").to_timestamp("M")})
            .groupby("month")["vix"]
            .agg(["mean", "last"])
            .rename(columns={"mean": "vix_mean", "last": "vix_last"})
            .reset_index()
        )
        monthly = monthly.merge(vix_month, on="month", how="left")
    else:
        monthly["vix_mean"] = np.nan
        monthly["vix_last"] = np.nan

    selections_df = pd.DataFrame(selections)
    return monthly, selections_df


def bootstrap_mean_diff(group: np.ndarray, other: np.ndarray) -> dict[str, float]:
    idx_g = RNG.integers(0, len(group), size=(BOOT_REPS, len(group)))
    idx_o = RNG.integers(0, len(other), size=(BOOT_REPS, len(other)))
    diffs = group[idx_g].mean(axis=1) - other[idx_o].mean(axis=1)
    return {
        "ci_low": float(np.quantile(diffs, 0.025)),
        "ci_high": float(np.quantile(diffs, 0.975)),
        "prob_gt_zero": float((diffs > 0).mean()),
    }


def mean_diff_test(df: pd.DataFrame, value_col: str, flag_col: str) -> MeanDiffTest:
    group = df.loc[df[flag_col], value_col].dropna().to_numpy(dtype=float)
    other = df.loc[~df[flag_col], value_col].dropna().to_numpy(dtype=float)
    t_stat, p_value = stats.ttest_ind(group, other, equal_var=False, nan_policy="omit")
    boot = bootstrap_mean_diff(group, other)
    mean_group = float(group.mean())
    mean_other = float(other.mean())
    return MeanDiffTest(
        n_group=int(len(group)),
        n_other=int(len(other)),
        mean_group=mean_group,
        mean_other=mean_other,
        diff=float(mean_group - mean_other),
        ratio=safe_ratio(mean_group, mean_other),
        welch_t=float(t_stat),
        welch_p_two_sided=float(p_value),
        bootstrap_ci_95_low=boot["ci_low"],
        bootstrap_ci_95_high=boot["ci_high"],
        prob_diff_gt_zero=boot["prob_gt_zero"],
        harvey_pass_abs_t_gt_3=bool(abs(t_stat) > HARVEY_T_ABS) if np.isfinite(t_stat) else False,
    )


def add_tail_targets(monthly: pd.DataFrame) -> pd.DataFrame:
    out = monthly.sort_values("month").copy()
    for col in ["spy_rv_ann", "iwm_rv_ann"]:
        q = out[col].shift(1).rolling(36, min_periods=24).quantile(0.80)
        out[f"{col}_tail_excess"] = (out[col] - q).clip(lower=0.0)
    for col in ["basket_vov", "basket_rv_ann", "spy_rv_ann", "iwm_rv_ann", "vix_last"]:
        out[f"{col}_lag1"] = out[col].shift(1)
    return out


def run_lead_test(df: pd.DataFrame, y_col: str, x_col: str, controls: list[str], n_tests: int) -> LeadTest:
    cols = [y_col, x_col] + controls
    reg = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
    y = reg[y_col].astype(float)
    x = sm.add_constant(reg[[x_col] + controls].astype(float))
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAG_MONTHS})
    coef = float(model.params[x_col])
    t_stat = float(model.tvalues[x_col])
    p_value = float(model.pvalues[x_col])
    return LeadTest(
        y=y_col,
        x=x_col,
        n_months=int(len(reg)),
        coef=coef,
        hac_t=t_stat,
        hac_p_two_sided=p_value,
        bonferroni_p=float(min(p_value * n_tests, 1.0)),
        positive_expected=bool(coef > 0),
        harvey_pass_abs_t_gt_3=bool(abs(t_stat) > HARVEY_T_ABS),
        bonferroni_pass_5pct=bool(min(p_value * n_tests, 1.0) < 0.05),
    )


def run_lead_tests(monthly: pd.DataFrame) -> list[LeadTest]:
    df = add_tail_targets(monthly)
    specs = [
        ("spy_rv_ann", "basket_vov_lag1", ["spy_rv_ann_lag1", "vix_last_lag1"]),
        ("iwm_rv_ann", "basket_vov_lag1", ["iwm_rv_ann_lag1", "vix_last_lag1"]),
        ("spy_rv_ann_tail_excess", "basket_vov_lag1", ["spy_rv_ann_lag1", "vix_last_lag1"]),
        ("iwm_rv_ann_tail_excess", "basket_vov_lag1", ["iwm_rv_ann_lag1", "vix_last_lag1"]),
        ("spy_rv_ann", "basket_rv_ann_lag1", ["spy_rv_ann_lag1", "vix_last_lag1"]),
        ("iwm_rv_ann", "basket_rv_ann_lag1", ["iwm_rv_ann_lag1", "vix_last_lag1"]),
    ]
    return [run_lead_test(df, y, x, controls, n_tests=len(specs)) for y, x, controls in specs]


def plot_outputs(monthly: pd.DataFrame, amplification: dict[str, MeanDiffTest], lead_tests: list[LeadTest]) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    metrics = ["basket_rv_ann", "basket_vov", "basket_minus_iwm_rv", "basket_minus_iwm_vov"]
    labels = ["Basket RV", "Basket VoV", "Basket-IWM RV", "Basket-IWM VoV"]
    normal = [amplification[m].mean_other for m in metrics]
    risk = [amplification[m].mean_group for m in metrics]
    x = np.arange(len(metrics))
    width = 0.36
    ax.bar(x - width / 2, normal, width, label="Normal months", color="#4c78a8")
    ax.bar(x + width / 2, risk, width, label="Risk-off months", color="#f58518")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=10, ha="right")
    ax.set_ylabel("Annualized vol / VoV units")
    ax.set_title("K1346: Lottery basket risk-off amplification")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1346_riskoff_amplification.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    y_labels = [f"{lt.x} -> {lt.y}" for lt in lead_tests]
    tstats = [lt.hac_t for lt in lead_tests]
    colors = ["#54a24b" if lt.positive_expected else "#e45756" for lt in lead_tests]
    ax.barh(np.arange(len(lead_tests)), tstats, color=colors)
    ax.axvline(3.0, color="black", linestyle="--", linewidth=1.0, label="Harvey +3")
    ax.axvline(-3.0, color="black", linestyle=":", linewidth=1.0, label="Harvey -3")
    ax.set_yticks(np.arange(len(lead_tests)))
    ax.set_yticklabels(y_labels, fontsize=8)
    ax.set_xlabel("HAC t-stat")
    ax.set_title("Lagged lottery basket risk -> next-month market volatility")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1346_lead_tstats.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def summarize_verdict(amplification: dict[str, MeanDiffTest], lead_tests: list[LeadTest]) -> tuple[str, str]:
    amp_primary = amplification["basket_minus_iwm_vov"]
    amp_pass = amp_primary.diff > 0 and amp_primary.harvey_pass_abs_t_gt_3
    lead_passes = [
        lt
        for lt in lead_tests
        if lt.positive_expected and lt.harvey_pass_abs_t_gt_3 and lt.bonferroni_pass_5pct
    ]
    if amp_pass and lead_passes:
        return (
            "PASS",
            "Lottery basket excess VoV amplifies in risk-off months and at least one lagged lead test survives Harvey plus Bonferroni.",
        )
    if amp_primary.diff > 0 and amp_primary.prob_diff_gt_zero >= 0.95 and not lead_passes:
        return (
            "CONDITIONAL_PASS",
            "Lottery basket excess VoV is descriptively higher in risk-off months, but lagged market-tail lead tests do not pass corrected thresholds.",
        )
    return (
        "NULL",
        "The yfinance-only lottery proxy does not provide corrected evidence of risk-off excess VoV amplification plus market-tail lead predictive power.",
    )


def main() -> None:
    prices = fetch_close_prices()
    stock_tickers = valid_stock_universe(prices)
    missing_benchmarks = [ticker for ticker in BENCHMARK_TICKERS if ticker not in prices]
    if missing_benchmarks:
        raise RuntimeError(f"Missing benchmark data: {missing_benchmarks}")
    if len(stock_tickers) < MIN_TICKERS_PER_MONTH:
        raise RuntimeError(f"Only {len(stock_tickers)} valid stock tickers; need {MIN_TICKERS_PER_MONTH}.")

    panel = build_monthly_stock_panel(prices, stock_tickers)
    monthly, selections = build_monthly_basket(prices, panel)
    monthly = monthly.dropna(subset=["basket_rv_ann", "basket_vov", "spy_rv_ann", "iwm_rv_ann"]).copy()
    monthly["risk_off"] = (monthly["spy_log_return"] <= -0.05) | (monthly["vix_mean"] >= 25.0)
    monthly["basket_minus_iwm_rv"] = monthly["basket_rv_ann"] - monthly["iwm_rv_ann"]
    monthly["basket_minus_iwm_vov"] = monthly["basket_vov"] - monthly["iwm_vov"]
    monthly["basket_minus_spy_rv"] = monthly["basket_rv_ann"] - monthly["spy_rv_ann"]
    monthly["basket_minus_spy_vov"] = monthly["basket_vov"] - monthly["spy_vov"]

    amplification_metrics = [
        "basket_rv_ann",
        "basket_vov",
        "basket_minus_iwm_rv",
        "basket_minus_iwm_vov",
        "basket_minus_spy_rv",
        "basket_minus_spy_vov",
    ]
    amplification = {
        metric: mean_diff_test(monthly, metric, "risk_off") for metric in amplification_metrics
    }
    lead_tests = run_lead_tests(monthly)
    verdict, conclusion = summarize_verdict(amplification, lead_tests)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(DATA_DIR / "monthly_lottery_basket.csv", index=False)
    selections.to_csv(DATA_DIR / "monthly_lottery_selections.csv", index=False)
    panel.to_csv(DATA_DIR / "monthly_stock_panel.csv", index=False)
    plot_outputs(monthly, amplification, lead_tests)

    results = {
        "experiment_id": "K1346",
        "title": "Lottery-stock basket vol-of-vol and crisis amplification",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "data_source": "yfinance adjusted close (auto_adjust=True)",
        "sample": {
            "start_requested": START_DATE,
            "end_requested_exclusive": END_DATE,
            "first_month": monthly["month"].min().strftime("%Y-%m-%d"),
            "last_month": monthly["month"].max().strftime("%Y-%m-%d"),
            "n_months": int(len(monthly)),
            "n_risk_off_months": int(monthly["risk_off"].sum()),
            "n_normal_months": int((~monthly["risk_off"]).sum()),
            "requested_universe_size": len(UNIVERSE_TICKERS),
            "valid_universe_size": len(stock_tickers),
            "valid_universe": stock_tickers,
        },
        "literature": [
            "Bali, Cakici, and Whitelaw (2011) JFE: stock-level MAX lottery effect.",
            "Zhang, Kappou, and Urquhart (2026) IRFA: conditional demand for lottery-type stocks around information spillovers.",
            "Wang and Zeng (2026 working paper): factor MAX predicts factor returns and is not subsumed by stock-level lottery anomalies.",
            "Lee (2023 working paper): positive idiosyncratic jumps relate to future skewness and lottery-like payoffs.",
        ],
        "lookahead_policy": (
            "Monthly features are shifted by one ticker-month via groupby('ticker').shift(1); "
            "month t returns/RV/VoV use only month t-1 lottery features. Lead regressions use "
            "basket_vov_lag1 or basket_rv_ann_lag1 for month t market-vol outcomes."
        ),
        "basket_construction": {
            "feature_window_idio_days": ROLL_IDIO_DAYS,
            "feature_window_max_days": ROLL_MAX_DAYS,
            "score": "mean(z_low_price_lag1, z_idio_vol_lag1, z_max_return_lag1)",
            "top_fraction_selected": TOP_FRAC,
            "min_tickers_per_month": MIN_TICKERS_PER_MONTH,
            "survivorship_bias_note": "The universe is a current liquid retail/speculative proxy basket, not CRSP.",
        },
        "risk_off_definition": "current month SPY log return <= -5% OR average VIX >= 25; descriptive, not a forecast signal",
        "amplification_tests": {k: asdict(v) for k, v in amplification.items()},
        "lead_tests": [asdict(v) for v in lead_tests],
        "selected_name_diagnostics": {
            "median_selected_names": int(monthly["n_selected"].median()),
            "median_lag_price": float(monthly["median_lag_price"].median()),
            "median_lag_idio_vol_ann": float(monthly["median_lag_idio_vol_ann"].median()),
            "median_lag_max_return_21d": float(monthly["median_lag_max_return_21d"].median()),
        },
        "figures": [
            "figures/k1346_riskoff_amplification.png",
            "figures/k1346_lead_tstats.png",
        ],
        "verdict": verdict,
        "conclusion": conclusion,
        "limitations": [
            "Current-name proxy universe creates survivorship and selection bias.",
            "Adjusted-close yfinance data cannot identify true penny-stock delistings or bankrupt lottery stocks.",
            "Monthly realized VoV is based on 5-day rolling close-to-close volatility, not intraday or option-implied VoV.",
            "Risk-off amplification is descriptive; the predictive claim is only tested through lagged monthly regressions.",
            "No transaction-cost or implementable trading strategy is claimed.",
        ],
    }
    with (OUT_DIR / "k1346_results.json").open("w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(json.dumps({"verdict": verdict, "conclusion": conclusion}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
