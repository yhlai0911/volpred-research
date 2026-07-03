"""K1610: frontier-market correlation convergence and diversification value.

Question
--------
Do frontier-market ETF proxies still diversify emerging-market exposure, or did
their correlations converge enough to erode the benefit?

Design
------
Primary public proxy is the iShares MSCI Frontier and Select EM ETF (FM).  The
ETF stopped producing current yfinance prices after 2025-01-08 in this runtime,
so all FM-based inference is explicitly limited to the investable sample that
exists in yfinance.  VNM and selected frontier / recently-frontier country ETFs
are included only as diagnostic proxies, not as a replacement for a broad
frontier-market index.

The main inference uses non-overlapping quarter-level correlations and daily
portfolio-return blocks.  Rolling 252-day correlations are diagnostic only.

Lookahead policy
----------------
This is a descriptive correlation / portfolio experiment, not a trading signal.
Portfolio weights are constant monthly-rebalanced 80/20 EM/FM weights.  Stress
classification is reported as within-sample descriptive conditioning; no trading
decision uses same-day or future information.

Seed: 42 for bootstrap inference.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

EXPERIMENT_ID = "K1610"
SEED = 42
START = "2009-01-01"
END = "2026-07-03"
BOOTSTRAP_REPS = 3000

PRIMARY_TICKERS = ["FM", "EEM", "VWO", "SPY", "ACWX", "EFA", "VNM"]
PROXY_TICKERS = ["KSA", "UAE", "QAT", "ARGT", "GREK", "EGPT", "PAK", "NGE"]
TICKERS = PRIMARY_TICKERS + PROXY_TICKERS

LITERATURE = [
    {
        "citation": "Berger, Pukthuanthong, and Yang (2011), Journal of Financial Economics, 'International diversification with frontier markets'",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304405X11000420",
        "use_in_design": "Baseline claim: frontier markets historically had low world-market integration and diversification value.",
    },
    {
        "citation": "Bekaert and Harvey (2017), 'Emerging equity markets in a globalizing world'",
        "url": "https://doi.org/10.2139/ssrn.2344817",
        "use_in_design": "Motivates time-varying EM integration and the possibility that diversification benefits decline as markets globalize.",
    },
    {
        "citation": "Converse, Levy-Yeyati, and Williams (2020), Federal Reserve IFDP 1268, 'How ETFs Amplify the Global Financial Cycle in Emerging Markets'",
        "url": "https://www.federalreserve.gov/econres/ifdp/files/ifdp1268.pdf",
        "use_in_design": "Motivates ETF-flow/global-financial-cycle channel for higher comovement in emerging/frontier ETF proxies.",
    },
    {
        "citation": "Baur (2012), 'Financial contagion and the real economy'",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S1042443111000242",
        "use_in_design": "Motivates separating ordinary interdependence from crisis-period correlation/contagion diagnostics.",
    },
]


@dataclass(frozen=True)
class PairSpec:
    left: str
    right: str
    label: str


PAIRS = [
    PairSpec("FM", "EEM", "FM vs EEM"),
    PairSpec("FM", "VWO", "FM vs VWO"),
    PairSpec("FM", "SPY", "FM vs SPY"),
    PairSpec("VNM", "EEM", "VNM vs EEM"),
]


def download_prices() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw.copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.sort_index()
    close.to_csv(DATA_DIR / "yfinance_adjusted_close.csv")
    return close


def build_returns(close: pd.DataFrame) -> pd.DataFrame:
    rets = np.log(close / close.shift(1))
    rets = rets.replace([np.inf, -np.inf], np.nan)
    rets.to_csv(DATA_DIR / "daily_log_returns.csv")
    return rets


def ticker_coverage(close: pd.DataFrame) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ticker in TICKERS:
        s = close[ticker].dropna() if ticker in close else pd.Series(dtype=float)
        out[ticker] = {
            "n_obs": int(len(s)),
            "first_date": str(s.index.min().date()) if len(s) else None,
            "last_date": str(s.index.max().date()) if len(s) else None,
        }
    return out


def common_sample(rets: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    return rets[tickers].dropna(how="any").copy()


def quarterly_pair_correlations(rets: pd.DataFrame, pairs: list[PairSpec]) -> pd.DataFrame:
    rows: list[dict] = []
    q_periods = rets.index.to_period("Q")
    for period, group in rets.groupby(q_periods):
        for pair in pairs:
            pair_df = group[[pair.left, pair.right]].dropna()
            if len(pair_df) < 30:
                continue
            corr = float(pair_df[pair.left].corr(pair_df[pair.right]))
            rows.append(
                {
                    "quarter": str(period),
                    "quarter_start": str(period.start_time.date()),
                    "quarter_end": str(period.end_time.date()),
                    "pair": pair.label,
                    "left": pair.left,
                    "right": pair.right,
                    "n_days": int(len(pair_df)),
                    "corr": corr,
                    "fisher_z": float(np.arctanh(np.clip(corr, -0.999999, 0.999999))),
                    "spy_quarter_return": float(np.expm1(group["SPY"].dropna().sum()))
                    if "SPY" in group
                    else np.nan,
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(DATA_DIR / "quarterly_pair_correlations.csv", index=False)
    return out


def hac_trend_test(qcorr: pd.DataFrame, pair_label: str) -> dict:
    df = qcorr.loc[qcorr["pair"] == pair_label].copy()
    df = df.sort_values("quarter_start").reset_index(drop=True)
    df["t"] = np.arange(len(df), dtype=float)
    y = df["fisher_z"].astype(float)
    x = sm.add_constant(df["t"])
    model = sm.OLS(y, x, missing="drop").fit(cov_type="HAC", cov_kwds={"maxlags": 4})
    slope = float(model.params["t"])
    t_stat = float(model.tvalues["t"])
    p_value = float(model.pvalues["t"])
    return {
        "pair": pair_label,
        "n_quarters": int(len(df)),
        "slope_fisher_z_per_quarter": slope,
        "hac_t": t_stat,
        "p_value": p_value,
        "annualized_corr_slope_approx": float(slope * 4),
        "first_corr": float(df["corr"].iloc[0]) if len(df) else None,
        "last_corr": float(df["corr"].iloc[-1]) if len(df) else None,
    }


def bootstrap_mean_diff(
    early: np.ndarray,
    late: np.ndarray,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> dict:
    rng = np.random.default_rng(seed)
    early = np.asarray(early, dtype=float)
    late = np.asarray(late, dtype=float)
    early = early[np.isfinite(early)]
    late = late[np.isfinite(late)]
    obs = float(np.mean(late) - np.mean(early))
    boot = np.empty(reps, dtype=float)
    for i in range(reps):
        e = rng.choice(early, size=len(early), replace=True)
        l = rng.choice(late, size=len(late), replace=True)
        boot[i] = np.mean(l) - np.mean(e)
    left_tail = int(np.sum(boot <= 0))
    right_tail = int(np.sum(boot >= 0))
    min_tail = min(left_tail, right_tail)
    p_two_sided = float(2 * min_tail / reps)
    p_is_upper_bound = False
    if min_tail == 0:
        p_two_sided = float(2 / reps)
        p_is_upper_bound = True
    return {
        "observed_diff": obs,
        "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "bootstrap_reps": reps,
        "seed": seed,
        "p_two_sided_centered": p_two_sided,
        "p_is_simulation_upper_bound": p_is_upper_bound,
    }


def early_late_tests(qcorr: pd.DataFrame) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pair_label in sorted(qcorr["pair"].unique()):
        df = qcorr.loc[qcorr["pair"] == pair_label].sort_values("quarter_start").reset_index(drop=True)
        if len(df) < 16:
            continue
        midpoint = len(df) // 2
        early = df.iloc[:midpoint]["fisher_z"].to_numpy()
        late = df.iloc[midpoint:]["fisher_z"].to_numpy()
        boot = bootstrap_mean_diff(early, late, seed=SEED + len(out))
        out[pair_label] = {
            "early_n_quarters": int(midpoint),
            "late_n_quarters": int(len(df) - midpoint),
            "early_mean_corr": float(np.tanh(np.mean(early))),
            "late_mean_corr": float(np.tanh(np.mean(late))),
            "late_minus_early_fisher_z": boot,
        }
    return out


def stress_calm_tests(qcorr: pd.DataFrame) -> dict[str, dict]:
    # Stress is descriptive: bottom quintile of SPY quarterly return within the
    # usable FM sample. It is not a tradable signal.
    out: dict[str, dict] = {}
    threshold = float(qcorr["spy_quarter_return"].quantile(0.2))
    for pair_label in sorted(qcorr["pair"].unique()):
        df = qcorr.loc[qcorr["pair"] == pair_label].dropna(subset=["spy_quarter_return"]).copy()
        stress = df.loc[df["spy_quarter_return"] <= threshold, "fisher_z"].to_numpy()
        calm = df.loc[df["spy_quarter_return"] > threshold, "fisher_z"].to_numpy()
        if len(stress) < 5 or len(calm) < 10:
            continue
        boot = bootstrap_mean_diff(calm, stress, seed=SEED + 100 + len(out))
        out[pair_label] = {
            "stress_definition": "SPY quarterly return <= sample 20th percentile",
            "spy_return_threshold": threshold,
            "stress_n_quarters": int(len(stress)),
            "calm_n_quarters": int(len(calm)),
            "stress_mean_corr": float(np.tanh(np.mean(stress))),
            "calm_mean_corr": float(np.tanh(np.mean(calm))),
            "stress_minus_calm_fisher_z": boot,
        }
    return out


def monthly_rebalanced_returns(rets: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    df = rets[list(weights)].dropna().copy()
    w = pd.Series(weights, dtype=float)
    simple = np.expm1(df)
    port = simple.mul(w, axis=1).sum(axis=1)
    return np.log1p(port)


def annual_stats(series: pd.Series) -> dict:
    s = series.dropna()
    ann_ret = float(np.expm1(s.mean() * 252))
    ann_vol = float(s.std(ddof=1) * np.sqrt(252))
    sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else np.nan
    cum = np.exp(s.cumsum())
    drawdown = cum / cum.cummax() - 1
    return {
        "n_days": int(len(s)),
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe_proxy_rf0": sharpe,
        "max_drawdown": float(drawdown.min()),
    }


def moving_block_bootstrap(
    df: pd.DataFrame,
    stat_fn: Callable[[pd.DataFrame], float],
    block_len: int = 21,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> dict:
    rng = np.random.default_rng(seed)
    arr = df.to_numpy()
    n = len(df)
    if n < block_len * 3:
        raise ValueError("not enough rows for moving block bootstrap")
    boot = np.empty(reps, dtype=float)
    starts = np.arange(0, n - block_len + 1)
    for i in range(reps):
        pieces = []
        while sum(len(p) for p in pieces) < n:
            st = int(rng.choice(starts))
            pieces.append(arr[st : st + block_len])
        sampled = np.vstack(pieces)[:n]
        sampled_df = pd.DataFrame(sampled, columns=df.columns)
        boot[i] = stat_fn(sampled_df)
    obs = stat_fn(df)
    left_tail = int(np.sum(boot <= 0))
    right_tail = int(np.sum(boot >= 0))
    min_tail = min(left_tail, right_tail)
    p_two_sided = float(2 * min_tail / reps)
    p_is_upper_bound = False
    if min_tail == 0:
        p_two_sided = float(2 / reps)
        p_is_upper_bound = True
    return {
        "observed": float(obs),
        "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "bootstrap_reps": reps,
        "block_len_days": block_len,
        "seed": seed,
        "p_two_sided_centered": p_two_sided,
        "p_is_simulation_upper_bound": p_is_upper_bound,
    }


def portfolio_tests(rets: pd.DataFrame) -> dict:
    df = rets[["FM", "EEM"]].dropna().copy()
    port_df = pd.DataFrame(
        {
            "EEM": df["EEM"],
            "EEM80_FM20": monthly_rebalanced_returns(df, {"EEM": 0.8, "FM": 0.2}).reindex(df.index),
            "EEM50_FM50": monthly_rebalanced_returns(df, {"EEM": 0.5, "FM": 0.5}).reindex(df.index),
        }
    ).dropna()
    port_df.to_csv(DATA_DIR / "portfolio_daily_returns.csv")

    midpoint_date = port_df.index[int(len(port_df) / 2)]
    stats = {
        "EEM": annual_stats(port_df["EEM"]),
        "EEM80_FM20": annual_stats(port_df["EEM80_FM20"]),
        "EEM50_FM50": annual_stats(port_df["EEM50_FM50"]),
        "early_end_date": str(midpoint_date.date()),
        "early": {
            "EEM": annual_stats(port_df.loc[port_df.index < midpoint_date, "EEM"]),
            "EEM80_FM20": annual_stats(port_df.loc[port_df.index < midpoint_date, "EEM80_FM20"]),
        },
        "late": {
            "EEM": annual_stats(port_df.loc[port_df.index >= midpoint_date, "EEM"]),
            "EEM80_FM20": annual_stats(port_df.loc[port_df.index >= midpoint_date, "EEM80_FM20"]),
        },
    }

    def vol_reduction(x: pd.DataFrame) -> float:
        return float((x["EEM"].std(ddof=1) - x["EEM80_FM20"].std(ddof=1)) * np.sqrt(252))

    def sharpe_diff(x: pd.DataFrame) -> float:
        eem = annual_stats(x["EEM"])["sharpe_proxy_rf0"]
        mix = annual_stats(x["EEM80_FM20"])["sharpe_proxy_rf0"]
        return float(mix - eem)

    boot_df = port_df[["EEM", "EEM80_FM20"]].dropna()
    stats["bootstrap_vol_reduction_80_20"] = moving_block_bootstrap(boot_df, vol_reduction, seed=SEED + 200)
    stats["bootstrap_sharpe_diff_80_20"] = moving_block_bootstrap(boot_df, sharpe_diff, seed=SEED + 201)
    return stats


def proxy_basket_diagnostics(rets: pd.DataFrame) -> dict:
    tickers = [t for t in ["VNM", "KSA", "UAE", "QAT", "ARGT", "GREK"] if t in rets.columns]
    rows = []
    for t in tickers:
        pair = rets[[t, "EEM", "SPY"]].dropna()
        if len(pair) < 500:
            continue
        rows.append(
            {
                "ticker": t,
                "n_days": int(len(pair)),
                "first_date": str(pair.index.min().date()),
                "last_date": str(pair.index.max().date()),
                "corr_with_eem": float(pair[t].corr(pair["EEM"])),
                "corr_with_spy": float(pair[t].corr(pair["SPY"])),
                "ann_vol": float(pair[t].std(ddof=1) * np.sqrt(252)),
                "ann_return": float(np.expm1(pair[t].mean() * 252)),
            }
        )
    out = pd.DataFrame(rows).sort_values("corr_with_eem", ascending=False)
    out.to_csv(DATA_DIR / "proxy_country_diagnostics.csv", index=False)
    return {"countries": out.to_dict(orient="records")}


def make_figures(qcorr: pd.DataFrame, early_late: dict, stress: dict, portfolio: dict) -> dict:
    figures: dict[str, str] = {}

    fig, ax = plt.subplots(figsize=(12, 6), dpi=160)
    for pair_label in ["FM vs EEM", "FM vs VWO", "FM vs SPY", "VNM vs EEM"]:
        df = qcorr.loc[qcorr["pair"] == pair_label].copy()
        if df.empty:
            continue
        dates = pd.to_datetime(df["quarter_start"]).to_numpy()
        ax.plot(dates, df["corr"].to_numpy(), marker="o", linewidth=1.8, label=pair_label)
    ax.axhline(0, color="#8A94A6", linewidth=1)
    ax.set_title("Quarterly return correlations: frontier proxies vs EM / global risk")
    ax.set_ylabel("Quarterly daily-return correlation")
    ax.set_xlabel("Quarter")
    ax.legend(loc="best")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "fig1_quarterly_correlations.png"
    fig.savefig(path)
    plt.close(fig)
    figures["quarterly_correlations"] = str(path.relative_to(HERE))

    fig, ax = plt.subplots(figsize=(10, 6), dpi=160)
    labels = ["FM vs EEM", "FM vs VWO", "FM vs SPY"]
    x = np.arange(len(labels))
    early_vals = [early_late[label]["early_mean_corr"] for label in labels]
    late_vals = [early_late[label]["late_mean_corr"] for label in labels]
    width = 0.35
    ax.bar(x - width / 2, early_vals, width, label="early half", color="#4C78A8")
    ax.bar(x + width / 2, late_vals, width, label="late half", color="#F58518")
    ax.set_xticks(x, labels, rotation=0)
    ax.set_ylabel("Mean quarterly correlation")
    ax.set_title("Early vs late sample: correlation convergence diagnostic")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "fig2_early_late_corr.png"
    fig.savefig(path)
    plt.close(fig)
    figures["early_late_corr"] = str(path.relative_to(HERE))

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=160)
    stats = portfolio
    names = ["EEM", "EEM80_FM20", "EEM50_FM50"]
    vols = [stats[n]["ann_vol"] for n in names]
    sharpes = [stats[n]["sharpe_proxy_rf0"] for n in names]
    axes[0].bar(names, vols, color=["#777777", "#4C78A8", "#72B7B2"])
    axes[0].set_title("Annualized volatility")
    axes[0].set_ylabel("Volatility")
    axes[0].grid(axis="y", alpha=0.25)
    axes[1].bar(names, sharpes, color=["#777777", "#4C78A8", "#72B7B2"])
    axes[1].set_title("Sharpe proxy (rf=0)")
    axes[1].grid(axis="y", alpha=0.25)
    fig.suptitle("Does adding FM reduce EM portfolio risk?")
    fig.tight_layout()
    path = FIG_DIR / "fig3_portfolio_diversification.png"
    fig.savefig(path)
    plt.close(fig)
    figures["portfolio_diversification"] = str(path.relative_to(HERE))

    return figures


def main() -> dict:
    close = download_prices()
    rets = build_returns(close)
    coverage = ticker_coverage(close)

    primary = common_sample(rets, ["FM", "EEM", "VWO", "SPY", "VNM"])
    primary.to_csv(DATA_DIR / "primary_common_daily_returns.csv")
    qcorr = quarterly_pair_correlations(primary, PAIRS)

    trend_tests = {pair.label: hac_trend_test(qcorr, pair.label) for pair in PAIRS if pair.label in set(qcorr["pair"])}
    early_late = early_late_tests(qcorr)
    stress = stress_calm_tests(qcorr)
    portfolio = portfolio_tests(rets)
    proxy_diag = proxy_basket_diagnostics(rets)
    figures = make_figures(qcorr, early_late, stress, portfolio)

    fm_end = coverage["FM"]["last_date"]
    fm_current_data_gap = fm_end is None or fm_end < "2026-01-01"

    fm_eem_late_diff = early_late["FM vs EEM"]["late_minus_early_fisher_z"]
    fm_eem_stress_diff = stress["FM vs EEM"]["stress_minus_calm_fisher_z"]
    vol_reduction = portfolio["bootstrap_vol_reduction_80_20"]
    sharpe_diff = portfolio["bootstrap_sharpe_diff_80_20"]

    verdict = "MIXED_DIVERSIFICATION_RETAINS_WITH_STRESS_EROSION"
    interpretation = (
        "FM still lowers EM portfolio volatility in the available ETF sample, but stress-quarter correlations rise sharply. "
        "There is no robust secular convergence trend, so the evidence supports conditional erosion during stress rather than "
        "full disappearance of diversification value."
    )
    if (
        fm_eem_late_diff["ci95"][0] > 0
        and fm_eem_stress_diff["ci95"][0] > 0
        and vol_reduction["ci95"][0] <= 0
    ):
        verdict = "EROSION_SUPPORTED"
        interpretation = "Correlation convergence/stress comovement is supported and FM no longer provides robust vol reduction."
    elif vol_reduction["ci95"][0] > 0 and fm_eem_stress_diff["ci95"][0] > 0 and fm_eem_late_diff["ci95"][0] <= 0:
        verdict = "MIXED_DIVERSIFICATION_RETAINS_WITH_STRESS_EROSION"
        interpretation = (
            "FM still lowers EM portfolio volatility in the available ETF sample, but stress-quarter correlations rise sharply. "
            "There is no robust secular convergence trend, so the evidence supports conditional erosion during stress rather than "
            "full disappearance of diversification value."
        )
    elif vol_reduction["ci95"][0] > 0 and fm_eem_late_diff["ci95"][0] <= 0:
        verdict = "DIVERSIFICATION_RETAINS_SUPPORT"
        interpretation = "FM still provides statistically supported vol reduction without robust correlation-convergence evidence."

    results = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_source": "yfinance adjusted close via yf.download(auto_adjust=True)",
        "start": START,
        "end": END,
        "literature": LITERATURE,
        "ticker_coverage": coverage,
        "primary_sample": {
            "tickers": ["FM", "EEM", "VWO", "SPY", "VNM"],
            "n_days": int(len(primary)),
            "first_date": str(primary.index.min().date()) if len(primary) else None,
            "last_date": str(primary.index.max().date()) if len(primary) else None,
            "fm_current_data_gap": bool(fm_current_data_gap),
            "note": "FM yfinance prices end at 2025-01-08 in this runtime; 2025-2026 current inference is unavailable.",
        },
        "quarterly_trend_tests": trend_tests,
        "early_late_correlation_tests": early_late,
        "stress_calm_correlation_tests": stress,
        "portfolio_tests": portfolio,
        "proxy_country_diagnostics": proxy_diag,
        "figures": figures,
        "verdict": verdict,
        "interpretation": interpretation,
        "limitations": [
            "FM ETF is not current after 2025-01-08 in yfinance; this is an investable-proxy sample ending before 2026.",
            "Country ETF proxies mix frontier, emerging, and recently reclassified markets; they are diagnostics, not a broad frontier index.",
            "Stress/calm comparison is descriptive within-sample conditioning, not a tradable signal.",
            "Quarterly correlations reduce overlap but leave modest sample size, so confidence intervals are wide.",
            "ETF prices include liquidity, fees, closures, and replication frictions; they may understate inaccessible local-market diversification.",
        ],
    }
    out_path = HERE / "K1610_results.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(json.dumps({"wrote": str(out_path), "verdict": verdict}, ensure_ascii=False))
    return results


if __name__ == "__main__":
    main()
