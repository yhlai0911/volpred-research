"""K1536 biodiversity transition-risk commodity proxy event study.

Research question
-----------------
Do publicly tradable high-biodiversity-footprint commodity proxies show higher
realized volatility, downside semivariance, or negative repricing around major
natural-capital policy/disclosure events?

This is a proxy diagnostic, not a replication of Guidolin and Pedio's commodity
futures biodiversity-footprint measure. The experiment uses public ETF/ETN
daily closes available through yfinance.

Information set
---------------
The primary event-window tests are descriptive. The pre-window uses only days
strictly before each event trading date, while the post-window starts at the
event trading date. There is no trading strategy and no same-day signal-return
forecast.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


warnings.filterwarnings("ignore")

EXPERIMENT_ID = "k1536"
SEED = 42
START = "2018-01-01"
END = "2026-06-24"
PRE_WINDOW = 20
POST_WINDOW = 20
BOOTSTRAP_REPS = 5000
HAC_LAGS = 21
TRADING_DAYS = 252

BASE_DIR = Path(__file__).resolve().parent
FIG_DIR = BASE_DIR / "figures"
RESULTS_PATH = BASE_DIR / f"{EXPERIMENT_ID}_results.json"

HIGH_BIODIVERSITY = {
    "CORN": "corn ETF proxy",
    "SOYB": "soybean ETF proxy",
    "WEAT": "wheat ETF proxy",
    "CANE": "sugar ETF proxy",
    "JO": "coffee ETN proxy",
    "WOOD": "global timber/forestry equity proxy",
    "DBA": "broad agriculture commodity ETF proxy",
}

CONTROL_COMMODITIES = {
    "GLD": "gold ETF control",
    "SLV": "silver ETF control",
    "CPER": "copper ETF control",
    "USO": "oil ETF control",
    "UNG": "natural gas ETF control",
    "PDBC": "broad commodity ETF benchmark/control",
}

EVENTS = [
    {
        "id": "kunming_declaration",
        "date": "2021-10-13",
        "name": "Kunming Declaration adopted at CBD COP15 part 1",
        "source": "Review of Finance biodiversity commodity event channel",
    },
    {
        "id": "gbf_adoption",
        "date": "2022-12-19",
        "name": "Kunming-Montreal Global Biodiversity Framework adopted",
        "source": "CBD official GBF page",
    },
    {
        "id": "eudr_signed",
        "date": "2023-05-31",
        "name": "EU Deforestation Regulation signed",
        "source": "EU Regulation 2023/1115 legislative timeline",
    },
    {
        "id": "eudr_entry_force",
        "date": "2023-06-29",
        "name": "EU Deforestation Regulation entered into force",
        "source": "European Commission EUDR page",
    },
    {
        "id": "tnfd_final",
        "date": "2023-09-18",
        "name": "TNFD final recommendations published",
        "source": "TNFD official release",
    },
    {
        "id": "eu_nature_restoration_adopted",
        "date": "2024-06-17",
        "name": "EU Council adopted Nature Restoration Regulation",
        "source": "European Commission Nature Restoration timeline",
    },
]


@dataclass(frozen=True)
class HACTest:
    metric: str
    n_obs: int
    mean: float
    hac_t: float
    hac_p: float
    ci95: list[float]


@dataclass(frozen=True)
class BootstrapResult:
    metric: str
    estimate: float
    ci95: list[float]
    p_two_sided: float
    reps: int
    seed: int


def finite_or_none(value):
    if isinstance(value, dict):
        return {k: finite_or_none(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite_or_none(v) for v in value]
    if isinstance(value, tuple):
        return [finite_or_none(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    return value


def download_prices(tickers: Iterable[str]) -> pd.DataFrame:
    data = yf.download(
        list(tickers),
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if data.empty:
        raise RuntimeError("yfinance returned no data")
    if isinstance(data.columns, pd.MultiIndex):
        if "Close" not in data.columns.get_level_values(0):
            raise RuntimeError("download did not contain Close columns")
        close = data["Close"].copy()
    else:
        close = data.copy()
    close = close.sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna(axis=1, how="all")


def next_trading_day(index: pd.DatetimeIndex, raw_date: str) -> pd.Timestamp | None:
    target = pd.Timestamp(raw_date)
    pos = index.searchsorted(target)
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def hac_intercept_test(series: pd.Series, metric: str, maxlags: int = HAC_LAGS) -> HACTest:
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()
    X = np.ones((len(clean), 1))
    model = sm.OLS(clean.to_numpy(dtype=float), X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    mean = float(model.params[0])
    se = float(model.bse[0])
    ci = [mean - 1.96 * se, mean + 1.96 * se]
    return HACTest(
        metric=metric,
        n_obs=int(model.nobs),
        mean=mean,
        hac_t=float(model.tvalues[0]),
        hac_p=float(model.pvalues[0]),
        ci95=[float(ci[0]), float(ci[1])],
    )


def bh_adjust(p_values: list[float]) -> list[float]:
    n = len(p_values)
    order = np.argsort(np.asarray(p_values, dtype=float))
    adjusted = np.empty(n, dtype=float)
    running = 1.0
    for rank_from_end, idx in enumerate(order[::-1], start=1):
        rank = n - rank_from_end + 1
        value = min(running, p_values[idx] * n / rank)
        running = value
        adjusted[idx] = value
    return [float(min(1.0, x)) for x in adjusted]


def bootstrap_event_blocks(
    event_df: pd.DataFrame,
    metric: str,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> BootstrapResult:
    rng = np.random.default_rng(seed)
    events = sorted(event_df["event_id"].unique())
    estimates: list[float] = []
    for _ in range(reps):
        sampled_events = rng.choice(events, size=len(events), replace=True)
        blocks = [event_df.loc[event_df["event_id"] == event_id] for event_id in sampled_events]
        sample = pd.concat(blocks, ignore_index=True)
        high = sample.loc[sample["group"] == "high_biodiversity", metric]
        control = sample.loc[sample["group"] == "control", metric]
        if high.notna().sum() == 0 or control.notna().sum() == 0:
            continue
        estimates.append(float(high.mean() - control.mean()))

    arr = np.asarray(estimates, dtype=float)
    ci = np.quantile(arr, [0.025, 0.975]).tolist()
    p_left = (1.0 + float(np.sum(arr <= 0.0))) / (len(arr) + 1.0)
    p_right = (1.0 + float(np.sum(arr >= 0.0))) / (len(arr) + 1.0)
    p_two = float(min(1.0, 2.0 * min(p_left, p_right)))
    estimate = float(
        event_df.loc[event_df["group"] == "high_biodiversity", metric].mean()
        - event_df.loc[event_df["group"] == "control", metric].mean()
    )
    return BootstrapResult(
        metric=metric,
        estimate=estimate,
        ci95=[float(ci[0]), float(ci[1])],
        p_two_sided=p_two,
        reps=int(len(arr)),
        seed=seed,
    )


def build_event_panel(
    returns: pd.DataFrame,
    groups: dict[str, str],
) -> tuple[pd.DataFrame, list[dict]]:
    rows: list[dict] = []
    mapped_events: list[dict] = []
    index = returns.index

    for event in EVENTS:
        event_day = next_trading_day(index, event["date"])
        if event_day is None:
            continue
        loc = index.get_loc(event_day)
        if loc < PRE_WINDOW or loc + POST_WINDOW >= len(index):
            continue

        pre_idx = index[loc - PRE_WINDOW : loc]
        post_idx = index[loc : loc + POST_WINDOW + 1]
        mapped_events.append(
            {
                **event,
                "event_trading_date": event_day.strftime("%Y-%m-%d"),
                "pre_window": [pre_idx[0].strftime("%Y-%m-%d"), pre_idx[-1].strftime("%Y-%m-%d")],
                "post_window": [post_idx[0].strftime("%Y-%m-%d"), post_idx[-1].strftime("%Y-%m-%d")],
            }
        )

        for ticker in returns.columns:
            series = returns[ticker]
            pre = series.loc[pre_idx].dropna()
            post = series.loc[post_idx].dropna()
            if len(pre) < PRE_WINDOW * 0.8 or len(post) < (POST_WINDOW + 1) * 0.8:
                continue
            pre_rv = float((pre**2).mean() * TRADING_DAYS)
            post_rv = float((post**2).mean() * TRADING_DAYS)
            pre_down = float((pre.clip(upper=0.0) ** 2).mean() * TRADING_DAYS)
            post_down = float((post.clip(upper=0.0) ** 2).mean() * TRADING_DAYS)
            pre_cum = float(pre.sum())
            post_cum = float(post.sum())
            rows.append(
                {
                    "event_id": event["id"],
                    "event_name": event["name"],
                    "event_trading_date": event_day.strftime("%Y-%m-%d"),
                    "ticker": ticker,
                    "group": groups[ticker],
                    "pre_rv_ann": pre_rv,
                    "post_rv_ann": post_rv,
                    "log_rv_ratio": float(np.log((post_rv + 1e-12) / (pre_rv + 1e-12))),
                    "pre_downside_ann": pre_down,
                    "post_downside_ann": post_down,
                    "log_downside_ratio": float(np.log((post_down + 1e-12) / (pre_down + 1e-12))),
                    "post_cum_log_return": post_cum,
                    "pre_cum_log_return": pre_cum,
                    "abnormal_post_minus_pre_cum": float(post_cum - pre_cum),
                }
            )

    return pd.DataFrame(rows), mapped_events


def make_figures(
    returns: pd.DataFrame,
    groups: dict[str, str],
    event_days: list[dict],
    event_tests: list[BootstrapResult],
) -> dict[str, str]:
    FIG_DIR.mkdir(exist_ok=True)

    high_cols = [ticker for ticker, group in groups.items() if group == "high_biodiversity"]
    control_cols = [ticker for ticker, group in groups.items() if group == "control"]
    high_ret = returns[high_cols].mean(axis=1)
    control_ret = returns[control_cols].mean(axis=1)
    high_rv21 = np.sqrt((high_ret**2).rolling(21).mean() * TRADING_DAYS)
    control_rv21 = np.sqrt((control_ret**2).rolling(21).mean() * TRADING_DAYS)

    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.plot(high_rv21.index, high_rv21, label="High biodiversity proxy basket", color="#1f7a5b", lw=1.8)
    ax.plot(control_rv21.index, control_rv21, label="Commodity control basket", color="#4e6e9e", lw=1.5)
    for event in event_days:
        day = pd.Timestamp(event["event_trading_date"])
        ax.axvline(day, color="#9a4d2f", lw=0.8, alpha=0.45)
    ax.set_title("21-day annualized realized volatility around biodiversity policy/disclosure events")
    ax.set_ylabel("Annualized realized volatility")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    rv_path = FIG_DIR / "basket_rv_event_windows.png"
    fig.savefig(rv_path, dpi=160)
    plt.close(fig)

    labels = {
        "log_rv_ratio": "log RV ratio",
        "log_downside_ratio": "log downside ratio",
        "abnormal_post_minus_pre_cum": "abnormal cum return",
    }
    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    xs = np.arange(len(event_tests))
    estimates = [test.estimate for test in event_tests]
    lower = [test.estimate - test.ci95[0] for test in event_tests]
    upper = [test.ci95[1] - test.estimate for test in event_tests]
    colors = ["#1f7a5b" if value >= 0 else "#b04a3f" for value in estimates]
    ax.bar(xs, estimates, yerr=[lower, upper], color=colors, alpha=0.85, capsize=4)
    ax.axhline(0.0, color="#222222", lw=0.9)
    ax.set_xticks(xs)
    ax.set_xticklabels([labels[test.metric] for test in event_tests], rotation=0)
    ax.set_title("High-biodiversity proxy minus control: event-window diff-in-diff")
    ax.set_ylabel("Post/pre change difference")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    did_path = FIG_DIR / "event_diff_in_diff.png"
    fig.savefig(did_path, dpi=160)
    plt.close(fig)

    return {
        "basket_rv_event_windows": str(rv_path.relative_to(BASE_DIR)),
        "event_diff_in_diff": str(did_path.relative_to(BASE_DIR)),
    }


def main() -> int:
    all_tickers = list(HIGH_BIODIVERSITY) + list(CONTROL_COMMODITIES)
    close = download_prices(all_tickers)
    available = [ticker for ticker in all_tickers if ticker in close.columns and close[ticker].notna().sum() >= 250]
    missing = [ticker for ticker in all_tickers if ticker not in available]
    close = close[available].dropna(how="all")
    returns = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan)

    groups = {
        ticker: "high_biodiversity" if ticker in HIGH_BIODIVERSITY else "control"
        for ticker in available
    }
    high_cols = [ticker for ticker, group in groups.items() if group == "high_biodiversity"]
    control_cols = [ticker for ticker, group in groups.items() if group == "control"]
    if len(high_cols) < 3 or len(control_cols) < 3:
        raise RuntimeError("insufficient high/control tickers after download")

    rv = returns**2 * TRADING_DAYS
    downside = returns.clip(upper=0.0) ** 2 * TRADING_DAYS
    daily_panel = pd.DataFrame(
        {
            "rv_high_minus_control": rv[high_cols].mean(axis=1) - rv[control_cols].mean(axis=1),
            "downside_high_minus_control": (
                downside[high_cols].mean(axis=1) - downside[control_cols].mean(axis=1)
            ),
        }
    ).dropna()
    unconditional_tests = [
        hac_intercept_test(daily_panel["rv_high_minus_control"], "rv_high_minus_control"),
        hac_intercept_test(daily_panel["downside_high_minus_control"], "downside_high_minus_control"),
    ]

    event_panel, mapped_events = build_event_panel(returns[available], groups)
    event_metrics = ["log_rv_ratio", "log_downside_ratio", "abnormal_post_minus_pre_cum"]
    event_tests = [bootstrap_event_blocks(event_panel, metric) for metric in event_metrics]

    # Cross-sectional event-level Welch diagnostics complement event-block bootstrap.
    welch_rows = []
    for metric in event_metrics:
        high = event_panel.loc[event_panel["group"] == "high_biodiversity", metric]
        control = event_panel.loc[event_panel["group"] == "control", metric]
        t_stat, p_val = stats.ttest_ind(high, control, equal_var=False, nan_policy="omit")
        welch_rows.append(
            {
                "metric": metric,
                "high_mean": float(high.mean()),
                "control_mean": float(control.mean()),
                "diff_high_minus_control": float(high.mean() - control.mean()),
                "welch_t": float(t_stat),
                "welch_p": float(p_val),
                "n_high": int(high.notna().sum()),
                "n_control": int(control.notna().sum()),
            }
        )
    q_values = bh_adjust([row["welch_p"] for row in welch_rows])
    for row, q_value in zip(welch_rows, q_values):
        row["bh_q"] = q_value
        row["bonferroni_p"] = float(min(1.0, row["welch_p"] * len(welch_rows)))

    figures = make_figures(returns[available], groups, mapped_events, event_tests)

    event_summary = (
        event_panel.groupby(["event_id", "group"])[event_metrics]
        .mean()
        .reset_index()
        .sort_values(["event_id", "group"])
    )

    positive_harvey_like_passes = [
        test.metric for test in unconditional_tests if test.hac_t >= 3.0
    ] + [row["metric"] for row in welch_rows if row["welch_t"] >= 3.0]
    negative_harvey_like_passes = [
        test.metric for test in unconditional_tests if test.hac_t <= -3.0
    ] + [row["metric"] for row in welch_rows if row["welch_t"] <= -3.0]
    bootstrap_excludes_zero = [
        test.metric for test in event_tests if test.ci95[0] > 0.0 or test.ci95[1] < 0.0
    ]

    if bootstrap_excludes_zero and positive_harvey_like_passes:
        verdict = "POSITIVE_PROXY"
    elif bootstrap_excludes_zero or positive_harvey_like_passes:
        verdict = "MIXED_WEAK_PROXY"
    elif negative_harvey_like_passes:
        verdict = "NULL_HIGHER_RV_REJECTED"
    else:
        verdict = "NULL_PROXY"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "task": "biodiversity transition-risk commodity basket RV and tail repricing",
        "verdict": verdict,
        "seed": SEED,
        "data": {
            "source": "yfinance daily adjusted close via auto_adjust=True",
            "requested_start": START,
            "requested_end": END,
            "effective_start": returns.dropna(how="all").index.min().strftime("%Y-%m-%d"),
            "effective_end": returns.dropna(how="all").index.max().strftime("%Y-%m-%d"),
            "n_union_days": int(len(returns)),
            "available_tickers": available,
            "missing_or_short_tickers": missing,
            "high_biodiversity_proxy": HIGH_BIODIVERSITY,
            "control_commodities": CONTROL_COMMODITIES,
            "ticker_observations": {
                ticker: int(returns[ticker].notna().sum()) for ticker in available
            },
        },
        "methodology": {
            "type": "empirical proxy diagnostic event study",
            "pre_window_trading_days": PRE_WINDOW,
            "post_window_trading_days": POST_WINDOW,
            "unconditional_test": "daily high-minus-control mean with HAC(21) intercept standard error",
            "event_test": "event-block bootstrap resampling event IDs for high-minus-control post/pre diff-in-diff",
            "multiple_testing": "BH and Bonferroni on Welch event-level diagnostics",
            "lookahead_guard": (
                "Pre-window uses t-20..t-1; post-window starts at event trading date. "
                "No predictive signal or same-day signal-return strategy is used."
            ),
        },
        "events": mapped_events,
        "unconditional_tests": [asdict(test) for test in unconditional_tests],
        "event_bootstrap_tests": [asdict(test) for test in event_tests],
        "event_welch_diagnostics": welch_rows,
        "event_group_summary": event_summary.to_dict(orient="records"),
        "positive_harvey_like_t_ge_3_metrics": positive_harvey_like_passes,
        "negative_harvey_like_t_le_minus_3_metrics": negative_harvey_like_passes,
        "event_bootstrap_ci_excludes_zero_metrics": bootstrap_excludes_zero,
        "figures": figures,
        "limitations": [
            "ETF/ETN proxies are not commodity futures excess returns and do not reproduce biodiversity-footprint scores.",
            "Group membership is an economic proxy, not a measured JNCC/SEI biodiversity-intensity sort.",
            "Only six policy/disclosure events are tested; event-block inference is low power.",
            "WOOD is an equity ETF proxy for forestry/timber exposure, not a physical commodity future.",
            "Daily close data cannot observe intraday repricing at announcement timestamps.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(finite_or_none(results), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(finite_or_none({
        "verdict": verdict,
        "effective_sample": [results["data"]["effective_start"], results["data"]["effective_end"]],
        "n_events": len(mapped_events),
        "unconditional_tests": results["unconditional_tests"],
        "event_bootstrap_tests": results["event_bootstrap_tests"],
    }), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
