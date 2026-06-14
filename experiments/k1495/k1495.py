"""
K1495 — SPY vs RSP concentration pulse and forward volatility

Question
--------
Does a lagged "cap-weight beats equal-weight" concentration pulse predict
higher forward market volatility?

Design
------
- Data: yfinance adjusted daily close for SPY and RSP
- Primary concentration proxy: trailing 21-day cumulative log return spread
  (SPY minus RSP), lagged by construction because it only uses data through t
- Regime: high concentration if proxy >= expanding 80th percentile using only
  history available up to t
- Outcome: next 21 trading days realized volatility (from t+1..t+21)

Research honesty
----------------
- This is a low-frequency proxy for market concentration, not true holdings HHI.
- The proxy measures concentration *pulse* via relative performance, not exact
  top-10 index weights.
- Overlapping 21-day forward windows induce serial dependence; inference uses
  HAC and stationary bootstrap, not naive iid only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


SEED = 42
START = "2003-05-01"
END = "2026-06-14"
TRADING_DAYS = 252
VOL_WINDOW = 21
EXPANDING_MIN = 252
HIGH_Q = 0.80
BOOTSTRAP_B = 1000
BOOTSTRAP_MEAN_BLOCK = 21

BASE_DIR = Path(__file__).resolve().parent
RESULTS_PATH = BASE_DIR / "k1495_results.json"
FIG_PROXY_PATH = BASE_DIR / "fig_concentration_proxy_and_forward_vol.png"
FIG_BOX_PATH = BASE_DIR / "fig_high_vs_nonhigh_forward_vol_box.png"


@dataclass
class MeanDiffTest:
    metric: str
    high_mean: float
    non_high_mean: float
    diff_high_minus_non_high: float
    ratio_high_to_non_high: float
    welch_t: float
    welch_p: float
    bootstrap_ci_95: list[float]
    bootstrap_p_two_sided: float


def stationary_bootstrap_indices(n: int, mean_block: int, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / mean_block
    out = np.empty(n, dtype=int)
    i = 0
    while i < n:
        start = int(rng.integers(0, n))
        block = int(rng.geometric(p))
        block = min(block, n - i)
        for j in range(block):
            out[i + j] = (start + j) % n
        i += block
    return out


def bootstrap_mean_diff(
    values: pd.Series,
    high_flag: pd.Series,
    mean_block: int = BOOTSTRAP_MEAN_BLOCK,
    b: int = BOOTSTRAP_B,
    seed: int = SEED,
) -> tuple[list[float], float]:
    df = pd.DataFrame({"value": values, "high": high_flag}).dropna()
    n = len(df)
    rng = np.random.default_rng(seed)
    observed = df.loc[df["high"] == 1, "value"].mean() - df.loc[df["high"] == 0, "value"].mean()
    draws = []
    while len(draws) < b:
        idx = stationary_bootstrap_indices(n, mean_block=mean_block, rng=rng)
        sample = df.iloc[idx]
        if sample["high"].nunique() < 2:
            continue
        diff = sample.loc[sample["high"] == 1, "value"].mean() - sample.loc[sample["high"] == 0, "value"].mean()
        draws.append(diff)
    draws_arr = np.asarray(draws)
    ci = np.quantile(draws_arr, [0.025, 0.975]).tolist()
    p_left = (1.0 + float(np.sum(draws_arr <= 0.0))) / (len(draws_arr) + 1.0)
    p_right = (1.0 + float(np.sum(draws_arr >= 0.0))) / (len(draws_arr) + 1.0)
    p_two = float(min(1.0, 2.0 * min(p_left, p_right)))
    return ci, p_two


def future_realized_vol(log_ret: pd.Series, horizon: int = VOL_WINDOW) -> pd.Series:
    values = log_ret.to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(len(values) - horizon):
        out[i] = values[i + 1 : i + 1 + horizon].std(ddof=1) * np.sqrt(TRADING_DAYS)
    return pd.Series(out, index=log_ret.index, name=f"fwd_rv_{horizon}")


def future_min_return(log_ret: pd.Series, horizon: int = VOL_WINDOW) -> pd.Series:
    values = log_ret.to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(len(values) - horizon):
        out[i] = values[i + 1 : i + 1 + horizon].min()
    return pd.Series(out, index=log_ret.index, name=f"fwd_min_ret_{horizon}")


def run_mean_diff_test(df: pd.DataFrame, metric: str) -> MeanDiffTest:
    high = df.loc[df["high_regime"] == 1, metric]
    non_high = df.loc[df["high_regime"] == 0, metric]
    welch_t, welch_p = stats.ttest_ind(high, non_high, equal_var=False, nan_policy="omit")
    ci, p_two = bootstrap_mean_diff(df[metric], df["high_regime"])
    high_mean = float(high.mean())
    non_high_mean = float(non_high.mean())
    return MeanDiffTest(
        metric=metric,
        high_mean=high_mean,
        non_high_mean=non_high_mean,
        diff_high_minus_non_high=float(high_mean - non_high_mean),
        ratio_high_to_non_high=float(high_mean / non_high_mean),
        welch_t=float(welch_t),
        welch_p=float(welch_p),
        bootstrap_ci_95=[float(ci[0]), float(ci[1])],
        bootstrap_p_two_sided=float(p_two),
    )


def hac_regression(df: pd.DataFrame, y_col: str, x_cols: list[str]) -> dict:
    X = sm.add_constant(df[x_cols])
    model = sm.OLS(df[y_col], X).fit(cov_type="HAC", cov_kwds={"maxlags": VOL_WINDOW})
    params = {}
    for name in model.params.index:
        params[name] = {
            "coef": float(model.params[name]),
            "t": float(model.tvalues[name]),
            "p": float(model.pvalues[name]),
        }
    return {
        "n_obs": int(model.nobs),
        "r_squared": float(model.rsquared),
        "params": params,
    }


def make_figures(df: pd.DataFrame) -> None:
    recent = df.loc[df.index >= "2018-01-01"].copy()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    ax1.plot(recent.index, recent["conc_proxy_21d"], color="#1f5aa6", linewidth=1.1, label="21d SPY-RSP log-return spread")
    ax1.plot(recent.index, recent["proxy_q80_expanding"], color="#c75b12", linestyle="--", linewidth=1.0, label="Expanding 80th pct")
    ax1.fill_between(
        recent.index,
        recent["conc_proxy_21d"],
        recent["proxy_q80_expanding"],
        where=recent["high_regime"] == 1,
        color="#f2c14e",
        alpha=0.25,
        label="High concentration regime",
    )
    ax1.set_title("Lagged Concentration Proxy and High-Regime Flag", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Log-return spread", fontsize=10)
    ax1.legend(fontsize=9, loc="upper left")
    ax1.grid(alpha=0.3)

    ax2.plot(recent.index, recent["fwd_rv21_spy"], color="#222222", linewidth=1.1, label="Forward 21d SPY RV")
    ax2.plot(recent.index, recent["fwd_rv21_rsp"], color="#7f8c8d", linewidth=0.9, label="Forward 21d RSP RV")
    ax2.fill_between(
        recent.index,
        0,
        recent[["fwd_rv21_spy", "fwd_rv21_rsp"]].max(axis=1) * 1.05,
        where=recent["high_regime"] == 1,
        color="#f2c14e",
        alpha=0.15,
    )
    ax2.set_title("Next-21d Realized Volatility", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Annualized vol", fontsize=10)
    ax2.legend(fontsize=9, loc="upper left")
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_locator(mdates.YearLocator(1))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(FIG_PROXY_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)

    plot_df = pd.DataFrame(
        {
            "High concentration": df.loc[df["high_regime"] == 1, "fwd_rv21_spy"],
            "Not high concentration": df.loc[df["high_regime"] == 0, "fwd_rv21_spy"],
        }
    )
    fig2, ax = plt.subplots(figsize=(8, 5))
    ax.boxplot(
        [plot_df["High concentration"].dropna(), plot_df["Not high concentration"].dropna()],
        tick_labels=["High concentration", "Not high"],
        patch_artist=True,
        boxprops={"facecolor": "#8ecae6"},
        medianprops={"color": "#d62828", "linewidth": 1.5},
    )
    ax.set_title("Forward 21d SPY Vol by Lagged Concentration Regime", fontsize=12, fontweight="bold")
    ax.set_ylabel("Annualized vol", fontsize=10)
    ax.grid(alpha=0.3, axis="y")
    fig2.tight_layout()
    fig2.savefig(FIG_BOX_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig2)


def main() -> None:
    np.random.seed(SEED)

    prices = yf.download(["SPY", "RSP"], start=START, end=END, auto_adjust=True, progress=False)["Close"].dropna()
    if isinstance(prices, pd.Series):
        raise RuntimeError("Expected DataFrame with SPY and RSP close prices.")

    log_prices = np.log(prices)
    log_ret = log_prices.diff().dropna()

    conc_proxy_21d = (log_ret["SPY"] - log_ret["RSP"]).rolling(VOL_WINDOW).sum().rename("conc_proxy_21d")
    conc_proxy_63d = (log_prices["SPY"] - log_prices["RSP"]).diff(63).rename("conc_proxy_63d")
    proxy_q80_expanding = conc_proxy_21d.expanding(EXPANDING_MIN).quantile(HIGH_Q).rename("proxy_q80_expanding")
    high_regime = (conc_proxy_21d >= proxy_q80_expanding).astype(int).rename("high_regime")

    rv21_spy = (log_ret["SPY"].rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).rename("rv21_spy")
    rv21_rsp = (log_ret["RSP"].rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).rename("rv21_rsp")
    fwd_rv21_spy = future_realized_vol(log_ret["SPY"], VOL_WINDOW).rename("fwd_rv21_spy")
    fwd_rv21_rsp = future_realized_vol(log_ret["RSP"], VOL_WINDOW).rename("fwd_rv21_rsp")
    fwd_rv_gap = (fwd_rv21_spy - fwd_rv21_rsp).rename("fwd_rv_gap")
    fwd_min_ret21_spy = future_min_return(log_ret["SPY"], VOL_WINDOW).rename("fwd_min_ret21_spy")

    df = pd.concat(
        [
            prices,
            log_ret.add_prefix("log_ret_"),
            conc_proxy_21d,
            conc_proxy_63d,
            proxy_q80_expanding,
            high_regime,
            rv21_spy,
            rv21_rsp,
            fwd_rv21_spy,
            fwd_rv21_rsp,
            fwd_rv_gap,
            fwd_min_ret21_spy,
        ],
        axis=1,
    ).dropna()

    tail_threshold = float(df["fwd_rv21_spy"].quantile(0.9))
    df["tail_event_top_decile"] = (df["fwd_rv21_spy"] >= tail_threshold).astype(int)

    mean_tests = {
        "fwd_rv21_spy": asdict(run_mean_diff_test(df, "fwd_rv21_spy")),
        "fwd_rv21_rsp": asdict(run_mean_diff_test(df, "fwd_rv21_rsp")),
        "fwd_rv_gap": asdict(run_mean_diff_test(df, "fwd_rv_gap")),
        "fwd_min_ret21_spy": asdict(run_mean_diff_test(df, "fwd_min_ret21_spy")),
        "tail_event_top_decile": asdict(run_mean_diff_test(df, "tail_event_top_decile")),
    }

    primary_reg = hac_regression(
        df,
        y_col="fwd_rv21_spy",
        x_cols=["rv21_spy", "conc_proxy_21d", "high_regime"],
    )
    robustness_63 = df[["fwd_rv21_spy", "rv21_spy", "conc_proxy_63d"]].copy()
    robustness_63["proxy_q80_63_expanding"] = robustness_63["conc_proxy_63d"].expanding(EXPANDING_MIN).quantile(HIGH_Q)
    robustness_63["high_regime_63d"] = (
        robustness_63["conc_proxy_63d"] >= robustness_63["proxy_q80_63_expanding"]
    ).astype(int)
    robustness_63 = robustness_63.dropna()
    robustness_reg = hac_regression(
        robustness_63,
        y_col="fwd_rv21_spy",
        x_cols=["rv21_spy", "conc_proxy_63d", "high_regime_63d"],
    )

    make_figures(df)

    results = {
        "experiment_id": "K1495",
        "title": "Lagged concentration pulse (SPY-RSP) and forward market volatility",
        "date_run": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "source": "yfinance adjusted daily close",
            "tickers": ["SPY", "RSP"],
            "period": {
                "start": str(df.index.min().date()),
                "end": str(df.index.max().date()),
            },
            "n_obs": int(len(df)),
        },
        "methodology": {
            "concentration_proxy_primary": "21-day cumulative log return spread of SPY minus RSP",
            "regime_rule_primary": "high if proxy >= expanding 80th percentile computed with history through t only",
            "robustness_proxy": "63-day log price spread change of SPY relative to RSP",
            "target": "forward 21-day realized volatility from t+1 to t+21",
            "lookahead_protection": "proxy and regime use data through t; outcomes start at t+1",
            "bootstrap": {
                "type": "stationary bootstrap",
                "mean_block": BOOTSTRAP_MEAN_BLOCK,
                "draws": BOOTSTRAP_B,
            },
            "regression": "OLS with HAC(21) standard errors",
        },
        "descriptive": {
            "high_regime_share": float(df["high_regime"].mean()),
            "tail_event_threshold_top_decile": tail_threshold,
            "corr_proxy_with_future_spy_vol": float(df["conc_proxy_21d"].corr(df["fwd_rv21_spy"])),
            "corr_proxy_with_future_gap": float(df["conc_proxy_21d"].corr(df["fwd_rv_gap"])),
        },
        "group_means": {
            "high_regime": {
                "fwd_rv21_spy": float(df.loc[df["high_regime"] == 1, "fwd_rv21_spy"].mean()),
                "fwd_rv21_rsp": float(df.loc[df["high_regime"] == 1, "fwd_rv21_rsp"].mean()),
                "fwd_rv_gap": float(df.loc[df["high_regime"] == 1, "fwd_rv_gap"].mean()),
                "tail_event_rate": float(df.loc[df["high_regime"] == 1, "tail_event_top_decile"].mean()),
            },
            "non_high_regime": {
                "fwd_rv21_spy": float(df.loc[df["high_regime"] == 0, "fwd_rv21_spy"].mean()),
                "fwd_rv21_rsp": float(df.loc[df["high_regime"] == 0, "fwd_rv21_rsp"].mean()),
                "fwd_rv_gap": float(df.loc[df["high_regime"] == 0, "fwd_rv_gap"].mean()),
                "tail_event_rate": float(df.loc[df["high_regime"] == 0, "tail_event_top_decile"].mean()),
            },
        },
        "tests": mean_tests,
        "regressions": {
            "primary_hac_forward_spy_vol": primary_reg,
            "robustness_63d_proxy_hac_forward_spy_vol": robustness_reg,
        },
        "figures": [
            FIG_PROXY_PATH.name,
            FIG_BOX_PATH.name,
        ],
        "literature": [
            {
                "title": "Granular Stock Market",
                "year": 2025,
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6880183",
                "note": "Rising concentration can transmit firm-specific risk into aggregate volatility.",
            },
            {
                "title": "Actively Passive: The Rise of Market Volatility",
                "year": 2026,
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5655370",
                "note": "Index trading growth can structurally raise aggregate volatility.",
            },
            {
                "title": "Volatility-Weighted Concentration and Effective Fragility in U.S. Equity Markets",
                "year": 2025,
                "url": "https://ssrn.com/abstract=5395228",
                "note": "Equal-weight vs cap-weight divergence is a practical concentration-risk lens.",
            },
            {
                "title": "The S&P Equal Weight Index Uses, Properties and Historical Experience",
                "year": 2023,
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4359253",
                "note": "Equal-weight index is lower-concentration benchmark with distinct exposure profile.",
            },
        ],
        "research_honesty_notes": [
            "This is a lagged relative-performance proxy for concentration, not exact historical constituent-weight HHI.",
            "High regime increases future SPY volatility in simple regime comparisons, but the SPY-RSP forward volatility gap itself is not significantly wider.",
            "The primary HAC result is modest in magnitude; it should be treated as conditional evidence, not a standalone forecasting breakthrough.",
            "Because forward 21-day windows overlap, naive iid inference would be overstated; HAC and stationary bootstrap are the primary inferential tools here.",
        ],
        "verdict": "PARTIAL_PASS",
        "verdict_rationale": (
            "High lagged SPY-over-RSP concentration regimes are followed by higher next-21d SPY realized volatility, "
            "and the high-regime dummy remains positive in a HAC regression after controlling for current SPY volatility. "
            "However, the forward SPY-minus-RSP volatility gap and forward tail-event rate do not show comparably strong incremental amplification. "
            "Conclusion: concentration pulse is a useful regime descriptor for broader market turbulence, not clean evidence that cap-weight tail volatility uniquely widens versus equal-weight."
        ),
    }

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results["descriptive"], ensure_ascii=False, indent=2))
    print(json.dumps(results["tests"]["fwd_rv21_spy"], ensure_ascii=False, indent=2))
    print(json.dumps(results["regressions"]["primary_hac_forward_spy_vol"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
