"""EM equity volatility regimes conditional on AI-trade coupling.

Question:
    Does stronger ex-ante coupling between emerging-market ETFs and a US
    AI/semiconductor trading proxy signal a higher future EM volatility regime?

Information set:
    All coupling signals at date t use returns through t-1 only. The target is
    future realized volatility from t through t+20. Regime thresholds are
    recursive expanding quantiles shifted again before assignment.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_em_ai_vol_regime"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
np.random.seed(SEED)

START_DATE = "2012-01-01"
END_DATE = "2026-06-15"
EM_TICKERS = ["EEM", "INDA", "EWZ", "EWY", "EWT", "EWW", "FXI"]
AI_PROXY_TICKERS = ["SMH", "SOXX", "NVDA", "MSFT", "QQQ"]
CONTROL_TICKERS = ["SPY", "^VIX"]
ALL_TICKERS = EM_TICKERS + AI_PROXY_TICKERS + CONTROL_TICKERS

COUPLING_WINDOW = 126
BETA_WINDOW = 252
RV_HORIZON = 21
REGIME_MIN_OBS = 504
LOW_Q = 0.30
HIGH_Q = 0.70
TRADING_DAYS = 252.0
HAC_LAGS = RV_HORIZON


REFERENCES = [
    {
        "title": "Volatility spillovers and contagion from mature to emerging stock markets",
        "url": "https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1113.pdf",
        "use": "Motivates mature-market-to-EM volatility transmission and contagion tests.",
    },
    {
        "title": "Exploring volatility interconnections between AI tokens, AI stocks, and fossil fuel markets",
        "url": "https://ideas.repec.org/a/eee/eneeco/v133y2024ics0140988324001981.html",
        "use": "Motivates AI-stock volatility connectedness as an empirical object.",
    },
    {
        "title": "IMF Global Financial Stability Report, October 2024, Chapter 3",
        "url": "https://www.imf.org/-/media/files/publications/gfsr/2024/october/english/ch3.pdf",
        "use": "Motivates AI-driven trading as a possible source of faster stress transmission.",
    },
    {
        "title": "Goldman Sachs: Emerging Markets Stocks Can Balance Volatility from the AI Trade",
        "url": "https://www.goldmansachs.com/insights/articles/emerging-markets-stocks-can-balance-volatility-from-the-ai-trade",
        "use": "Practitioner claim tested here with transparent ETF proxies.",
    },
]


@dataclass
class RegressionResult:
    coef: float
    se_hac: float
    t_hac: float
    p_hac: float


def fetch_prices() -> pd.DataFrame:
    cache_path = DATA_DIR / "adjusted_close.csv"
    if cache_path.exists():
        return pd.read_csv(cache_path, parse_dates=["Date"]).set_index("Date").sort_index()

    raw = yf.download(
        ALL_TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")

    out: dict[str, pd.Series] = {}
    for ticker in ALL_TICKERS:
        if isinstance(raw.columns, pd.MultiIndex) and ticker in raw.columns.get_level_values(0):
            close = raw[ticker]["Close"]
        elif isinstance(raw.columns, pd.MultiIndex) and "Close" in raw.columns.get_level_values(0):
            close = raw["Close"][ticker]
        else:
            close = raw["Close"]
        out[ticker] = close.rename(ticker).dropna()

    prices = pd.DataFrame(out).sort_index()
    prices.to_csv(cache_path, index_label="Date")
    return prices


def rolling_partial_corr(
    asset_ret: pd.Series,
    ai_ret: pd.Series,
    market_ret: pd.Series,
    window: int = COUPLING_WINDOW,
) -> pd.Series:
    frame = pd.concat(
        [asset_ret.rename("asset"), ai_ret.rename("ai"), market_ret.rename("market")],
        axis=1,
    ).dropna()
    values: list[tuple[pd.Timestamp, float]] = []
    for i in range(window, len(frame)):
        # Assign at date i; the window ends at i-1, so the signal is tradable at i.
        w = frame.iloc[i - window : i]
        x = sm.add_constant(w["market"], has_constant="add")
        asset_resid = sm.OLS(w["asset"], x).fit().resid
        ai_resid = sm.OLS(w["ai"], x).fit().resid
        corr = asset_resid.corr(ai_resid)
        values.append((frame.index[i], float(corr)))
    return pd.Series(dict(values), name=asset_ret.name).sort_index()


def future_realized_vol(ret: pd.Series, horizon: int = RV_HORIZON) -> pd.Series:
    return ret.rolling(horizon).std(ddof=1).shift(-(horizon - 1)) * np.sqrt(TRADING_DAYS)


def lagged_realized_vol(ret: pd.Series, horizon: int = RV_HORIZON) -> pd.Series:
    return ret.rolling(horizon).std(ddof=1).shift(1) * np.sqrt(TRADING_DAYS)


def expanding_regime(signal: pd.Series) -> pd.Series:
    low = signal.expanding(min_periods=REGIME_MIN_OBS).quantile(LOW_Q).shift(1)
    high = signal.expanding(min_periods=REGIME_MIN_OBS).quantile(HIGH_Q).shift(1)
    regime = pd.Series(index=signal.index, dtype="object", name="coupling_regime")
    valid = signal.notna() & low.notna() & high.notna()
    regime.loc[valid] = "mid"
    regime.loc[valid & (signal <= low)] = "low"
    regime.loc[valid & (signal >= high)] = "high"
    return regime


def zscore_expanding_lag(series: pd.Series, min_obs: int = 252) -> pd.Series:
    lag = series.shift(1)
    mean = lag.expanding(min_periods=min_obs).mean()
    std = lag.expanding(min_periods=min_obs).std(ddof=1)
    return (lag - mean) / std.replace(0.0, np.nan)


def fit_hac(y: pd.Series, x: pd.DataFrame) -> tuple[sm.regression.linear_model.RegressionResultsWrapper, dict[str, dict[str, float]]]:
    work = pd.concat([y.rename("future_rv"), x], axis=1).dropna()
    fit = sm.OLS(work["future_rv"], sm.add_constant(work[x.columns], has_constant="add")).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": HAC_LAGS},
    )
    table: dict[str, dict[str, float]] = {}
    for name in fit.params.index:
        table[name] = asdict(
            RegressionResult(
                coef=float(fit.params[name]),
                se_hac=float(fit.bse[name]),
                t_hac=float(fit.tvalues[name]),
                p_hac=float(fit.pvalues[name]),
            )
        )
    table["meta"] = {
        "n_obs": int(fit.nobs),
        "r_squared": float(fit.rsquared),
        "hac_maxlags": HAC_LAGS,
    }
    return fit, table


def linear_contrast(
    fit: sm.regression.linear_model.RegressionResultsWrapper,
    weights: dict[str, float],
) -> dict[str, float]:
    row = np.zeros(len(fit.params))
    index = list(fit.params.index)
    for name, weight in weights.items():
        row[index.index(name)] = weight
    test = fit.t_test(row)
    return {
        "coef": float(test.effect[0]),
        "se_hac": float(test.sd[0][0]),
        "t_hac": float(test.tvalue[0][0]),
        "p_hac": float(test.pvalue),
    }


def ai_shock_indicator(ai_ret: pd.Series) -> pd.Series:
    abs_ai = ai_ret.abs()
    threshold = abs_ai.expanding(min_periods=REGIME_MIN_OBS).quantile(0.95).shift(2)
    shock = (abs_ai.shift(1) >= threshold).astype(float)
    shock[threshold.isna()] = np.nan
    return shock.rename("ai_shock_lag1")


def summarize_asset(
    ticker: str,
    returns: pd.DataFrame,
    ai_ret: pd.Series,
    vix: pd.Series,
) -> dict:
    coupling = rolling_partial_corr(returns[ticker], ai_ret, returns["SPY"])
    regime = expanding_regime(coupling)
    future_rv = future_realized_vol(returns[ticker])
    lag_rv = lagged_realized_vol(returns[ticker])
    vix_lag = np.log(vix).shift(1).rename("log_vix_lag1")
    coupling_z = zscore_expanding_lag(coupling.rename("coupling"), REGIME_MIN_OBS).rename("coupling_z_lag1")
    shock = ai_shock_indicator(ai_ret)

    frame = pd.DataFrame(
        {
            "future_rv": future_rv,
            "coupling": coupling,
            "coupling_z_lag1": coupling_z,
            "regime": regime,
            "high": (regime == "high").astype(float),
            "low": (regime == "low").astype(float),
            "lag_rv": lag_rv,
            "log_vix_lag1": vix_lag,
            "ai_shock_lag1": shock,
        }
    )
    frame.loc[frame["regime"].isna(), ["high", "low"]] = np.nan

    regime_fit, regime_table = fit_hac(
        frame["future_rv"],
        frame[["high", "low", "lag_rv", "log_vix_lag1"]],
    )
    continuous_fit, continuous_table = fit_hac(
        frame["future_rv"],
        frame[["coupling_z_lag1", "lag_rv", "log_vix_lag1"]],
    )
    shock_fit, shock_table = fit_hac(
        frame["future_rv"],
        frame[["ai_shock_lag1", "lag_rv", "log_vix_lag1"]],
    )

    high_low = linear_contrast(regime_fit, {"high": 1.0, "low": -1.0})
    regime_counts = frame["regime"].dropna().value_counts().to_dict()
    regime_means = frame.dropna(subset=["future_rv", "regime"]).groupby("regime")["future_rv"].mean().to_dict()

    return {
        "ticker": ticker,
        "sample": {
            "first_date": str(frame.dropna(subset=["future_rv", "coupling"]).index.min().date()),
            "last_date": str(frame.dropna(subset=["future_rv", "coupling"]).index.max().date()),
            "n_signal_obs": int(frame["coupling"].dropna().shape[0]),
            "n_regression_obs": int(regime_table["meta"]["n_obs"]),
            "regime_counts": {k: int(v) for k, v in regime_counts.items()},
        },
        "regime_forward_rv_mean": {k: float(v) for k, v in regime_means.items()},
        "regime_regression_hac": regime_table,
        "high_minus_low_contrast": high_low,
        "continuous_coupling_regression_hac": continuous_table,
        "ai_shock_regression_hac": shock_table,
        "series": {
            "coupling": coupling,
            "future_rv": future_rv,
            "regime": regime,
        },
    }


def make_plots(asset_results: dict[str, dict]) -> list[str]:
    coupling_panel = pd.DataFrame({k: v["series"]["coupling"] for k, v in asset_results.items()})
    future_rv_panel = pd.DataFrame({k: v["series"]["future_rv"] for k, v in asset_results.items()})

    median_coupling = coupling_panel.median(axis=1)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(median_coupling.index, median_coupling, color="#12355b", lw=1.6, label="Median EM-AI partial corr")
    ax.axhline(0.0, color="black", lw=1, linestyle="--")
    ax.set_title("Ex-ante EM coupling to AI/semiconductor proxy")
    ax.set_ylabel("126d partial correlation, net of SPY")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    p1 = FIG_DIR / "median_ai_coupling.png"
    fig.savefig(p1, dpi=160)
    plt.close(fig)

    rows = []
    for ticker, result in asset_results.items():
        means = result["regime_forward_rv_mean"]
        for regime in ["low", "mid", "high"]:
            if regime in means:
                rows.append((ticker, regime, means[regime]))
    plot_df = pd.DataFrame(rows, columns=["ticker", "regime", "future_rv"])
    fig, ax = plt.subplots(figsize=(11, 5.5))
    x = np.arange(len(EM_TICKERS))
    width = 0.24
    colors = {"low": "#3a86ff", "mid": "#8d99ae", "high": "#d00000"}
    for j, regime in enumerate(["low", "mid", "high"]):
        vals = [
            float(plot_df[(plot_df["ticker"] == ticker) & (plot_df["regime"] == regime)]["future_rv"].iloc[0])
            if not plot_df[(plot_df["ticker"] == ticker) & (plot_df["regime"] == regime)].empty
            else np.nan
            for ticker in EM_TICKERS
        ]
        ax.bar(x + (j - 1) * width, vals, width=width, label=regime, color=colors[regime])
    ax.set_xticks(x)
    ax.set_xticklabels(EM_TICKERS)
    ax.set_ylabel("Mean future 21d RV, annualized")
    ax.set_title("Future EM volatility by recursive AI-coupling regime")
    ax.legend()
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    p2 = FIG_DIR / "future_rv_by_coupling_regime.png"
    fig.savefig(p2, dpi=160)
    plt.close(fig)

    effects = pd.Series({k: v["high_minus_low_contrast"]["coef"] for k, v in asset_results.items()})
    tvals = pd.Series({k: v["high_minus_low_contrast"]["t_hac"] for k, v in asset_results.items()})
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    bar_colors = ["#d00000" if val > 0 else "#3a86ff" for val in effects]
    ax.bar(effects.index, effects.values, color=bar_colors)
    for i, ticker in enumerate(effects.index):
        ax.text(i, effects.iloc[i], f"t={tvals.iloc[i]:.2f}", ha="center", va="bottom" if effects.iloc[i] >= 0 else "top", fontsize=9)
    ax.axhline(0.0, color="black", lw=1)
    ax.set_ylabel("High minus low future RV")
    ax.set_title("HAC high-low contrast after lagged RV and VIX controls")
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    p3 = FIG_DIR / "high_minus_low_hac_effects.png"
    fig.savefig(p3, dpi=160)
    plt.close(fig)

    avg_future_rv = future_rv_panel.mean(axis=1)
    fig, ax1 = plt.subplots(figsize=(11, 5.5))
    ax1.plot(median_coupling.index, median_coupling, color="#12355b", lw=1.4, label="Median AI coupling")
    ax1.set_ylabel("Median partial corr", color="#12355b")
    ax1.tick_params(axis="y", labelcolor="#12355b")
    ax2 = ax1.twinx()
    ax2.plot(avg_future_rv.index, avg_future_rv, color="#d00000", lw=1.0, alpha=0.55, label="Mean future RV")
    ax2.set_ylabel("Mean future 21d RV", color="#d00000")
    ax2.tick_params(axis="y", labelcolor="#d00000")
    ax1.set_title("EM-AI coupling and next-month EM realized volatility")
    fig.tight_layout()
    p4 = FIG_DIR / "coupling_vs_future_rv.png"
    fig.savefig(p4, dpi=160)
    plt.close(fig)

    return [str(p.relative_to(ROOT)) for p in [p1, p2, p3, p4]]


def strip_series(asset_results: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ticker, result in asset_results.items():
        clean = dict(result)
        clean.pop("series", None)
        out[ticker] = clean
    return out


def main() -> dict:
    prices = fetch_prices()
    required = EM_TICKERS + AI_PROXY_TICKERS + ["SPY", "^VIX"]
    close = prices[required].dropna(how="any").sort_index()
    returns = np.log(close.drop(columns=["^VIX"])).diff()
    returns = returns.dropna(how="any")
    vix = close["^VIX"].reindex(returns.index).ffill()
    ai_ret = returns[AI_PROXY_TICKERS].mean(axis=1).rename("ai_proxy")
    returns["SPY"] = returns["SPY"]

    asset_results = {
        ticker: summarize_asset(ticker, returns, ai_ret, vix)
        for ticker in EM_TICKERS
    }
    figures = make_plots(asset_results)

    high_low_pvals = {k: v["high_minus_low_contrast"]["p_hac"] for k, v in asset_results.items()}
    high_low_effects = {k: v["high_minus_low_contrast"]["coef"] for k, v in asset_results.items()}
    high_low_t = {k: v["high_minus_low_contrast"]["t_hac"] for k, v in asset_results.items()}
    continuous_pvals = {
        k: v["continuous_coupling_regression_hac"]["coupling_z_lag1"]["p_hac"]
        for k, v in asset_results.items()
    }
    continuous_t = {
        k: v["continuous_coupling_regression_hac"]["coupling_z_lag1"]["t_hac"]
        for k, v in asset_results.items()
    }
    shock_pvals = {
        k: v["ai_shock_regression_hac"]["ai_shock_lag1"]["p_hac"]
        for k, v in asset_results.items()
    }
    shock_effects = {
        k: v["ai_shock_regression_hac"]["ai_shock_lag1"]["coef"]
        for k, v in asset_results.items()
    }
    bonf_alpha = 0.05 / len(EM_TICKERS)
    high_low_sig = [k for k, p in high_low_pvals.items() if p < bonf_alpha]
    continuous_sig = [k for k, p in continuous_pvals.items() if p < bonf_alpha]
    shock_sig = [k for k, p in shock_pvals.items() if p < bonf_alpha]
    high_low_positive = [k for k, v in high_low_effects.items() if v > 0]
    shock_positive = [k for k, v in shock_effects.items() if v > 0]

    if len(high_low_sig) >= 2 and len(high_low_positive) >= 5:
        verdict = "PASS"
        verdict_reason = (
            "High AI-coupling regimes robustly predict higher future EM RV across multiple ETFs "
            "after lagged RV/VIX controls and Bonferroni correction."
        )
    elif len(high_low_positive) >= 5 or len(continuous_sig) >= 2 or len(shock_sig) >= 2:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (
            "The direction is economically coherent for several EM ETFs, but strict HAC plus "
            "Bonferroni evidence is not broad enough for a strong regime-switching claim."
        )
    else:
        verdict = "NULL"
        verdict_reason = (
            "Lagged AI-specific coupling does not provide robust evidence of a distinct future "
            "EM volatility regime after controls."
        )

    result = {
        "experiment_id": EXPERIMENT_ID,
        "title": "EM equity volatility regimes conditional on AI-trade coupling",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "status": "done",
        "seed": SEED,
        "data": {
            "source": "yfinance adjusted close, cached under experiments/research_em_ai_vol_regime/data/",
            "sample_start": str(close.index.min().date()),
            "sample_end": str(close.index.max().date()),
            "joint_price_obs": int(len(close)),
            "em_tickers": EM_TICKERS,
            "ai_proxy_tickers": AI_PROXY_TICKERS,
            "controls": ["SPY", "^VIX"],
        },
        "methodology": {
            "ai_proxy": "Equal-weight daily log return of SMH, SOXX, NVDA, MSFT, and QQQ.",
            "coupling_signal": (
                "126d rolling partial correlation between each EM ETF and AI proxy, "
                "controlling for SPY; signal at t uses returns through t-1."
            ),
            "regime_assignment": (
                "Recursive expanding 30/70 quantiles of the coupling signal with 504-observation "
                "warm-up; thresholds are shifted one additional day before assignment."
            ),
            "target": "Future 21 trading-day realized volatility from returns t..t+20, annualized.",
            "controls": "Lagged 21d own realized volatility and log(VIX_{t-1}).",
            "inference": "OLS with Newey-West HAC standard errors, maxlags=21, because target RV overlaps.",
            "multiple_testing": f"Bonferroni alpha across {len(EM_TICKERS)} EM ETFs = {bonf_alpha:.6f}.",
            "randomness": "No bootstrap or Monte Carlo; seed fixed for reproducibility.",
        },
        "summary": {
            "bonferroni_alpha": bonf_alpha,
            "high_minus_low_positive_count": len(high_low_positive),
            "high_minus_low_bonferroni_significant": high_low_sig,
            "continuous_coupling_bonferroni_significant": continuous_sig,
            "lagged_ai_shock_positive_count": len(shock_positive),
            "lagged_ai_shock_bonferroni_significant": shock_sig,
            "high_minus_low_effects": {k: float(v) for k, v in high_low_effects.items()},
            "high_minus_low_t_hac": {k: float(v) for k, v in high_low_t.items()},
            "continuous_coupling_t_hac": {k: float(v) for k, v in continuous_t.items()},
        },
        "asset_results": strip_series(asset_results),
        "figures": figures,
        "references": REFERENCES,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "limitations": [
            "The AI proxy is a transparent public-market proxy, not observed AI-trading flow or AI capex surprises.",
            "ETF prices are USD-denominated; local-currency EM effects and FX translation are not separated.",
            "The design tests conditioning and forecast association, not structural causality.",
        ],
    }

    out_path = ROOT / f"{EXPERIMENT_ID}_results.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "verdict": verdict, "reason": verdict_reason}, indent=2))
    return result


if __name__ == "__main__":
    main()
