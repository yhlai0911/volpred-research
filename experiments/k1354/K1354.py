"""K1354 - Monthly OPEX gamma-cliff event study.

Question
--------
Does realized volatility become unusually quiet during the three trading days
before monthly option expiration, and does it rebound after expiration?

Design
------
- Data: SPY daily OHLCV from yfinance with auto-adjusted OHLC.
- Calendar: monthly option expiration is proxied by the third Friday of each
  month; if that date is not an SPY trading day, use the previous trading day
  in the same month. March/June/September/December are tagged as quad-witching.
- Primary volatility proxy: Parkinson range variance, log(high/low)^2/(4log2).
- Unit of inference: event month. We compare event-window means with same-month
  non-event control days, so daily observations inside one event are not treated
  as independent.
- Lookahead: event dates are known calendar information. Any forecasting-style
  signal derived from the calendar is explicitly lagged with signal.shift(1).

Randomness is fixed with seed=42 for bootstrap and permutation routines.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as st
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)

SEED = 42
BOOTSTRAP_REPS = 5_000
TRADING_DAYS = 252
TICKER = "SPY"
START = "1993-01-29"
END = (date.today() + timedelta(days=1)).isoformat()
HARVEY_T = 3.0
BONFERRONI_ALPHA = 0.05 / 4.0

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / "K1354_results.json"
EVENT_PANEL_PATH = DATA_DIR / "K1354_event_panel.csv"
OFFSET_PANEL_PATH = DATA_DIR / "K1354_offset_panel.csv"
SPY_CACHE_PATH = DATA_DIR / "SPY_ohlcv_auto_adjusted.csv"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_float(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def third_friday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year=year, month=month, day=1)
    days_to_friday = (4 - first.weekday()) % 7
    return first + pd.Timedelta(days=days_to_friday + 14)


def load_spy_ohlcv() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SPY_CACHE_PATH.exists():
        out = pd.read_csv(SPY_CACHE_PATH, parse_dates=["Date"]).set_index("Date")
        return out.sort_index()

    raw = yf.download(
        TICKER,
        start=START,
        end=END,
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no SPY data")
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs(TICKER, axis=1, level=1, drop_level=True)
    cols = ["Open", "High", "Low", "Close", "Volume"]
    out = raw.loc[:, cols].dropna(how="any").copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.sort_index()
    out.reset_index(names="Date").to_csv(SPY_CACHE_PATH, index=False)
    return out


def add_volatility_measures(ohlcv: pd.DataFrame) -> pd.DataFrame:
    df = ohlcv.copy()
    df["log_close"] = np.log(df["Close"])
    df["log_ret"] = df["log_close"].diff()
    df["cc_var"] = df["log_ret"] ** 2
    df["abs_ret"] = df["log_ret"].abs()
    hl = np.log(df["High"] / df["Low"])
    df["range_var"] = (hl**2) / (4.0 * math.log(2.0))
    df["range_vol_ann"] = np.sqrt(df["range_var"] * TRADING_DAYS)
    return df.dropna(subset=["log_ret", "cc_var", "range_var"]).copy()


def build_opex_calendar(trading_dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    first = trading_dates.min()
    last = trading_dates.max()
    month_cursor = pd.Timestamp(first.year, first.month, 1)
    last_month = pd.Timestamp(last.year, last.month, 1)

    while month_cursor <= last_month:
        nominal = third_friday(month_cursor.year, month_cursor.month)
        eligible = trading_dates[(trading_dates <= nominal) & (trading_dates.month == month_cursor.month)]
        if len(eligible) > 0:
            expiration = eligible.max()
            if expiration >= nominal - pd.Timedelta(days=5):
                rows.append(
                    {
                        "event_month": month_cursor.strftime("%Y-%m"),
                        "nominal_third_friday": nominal.date().isoformat(),
                        "expiration_date": expiration.date().isoformat(),
                        "expiration_shift_days": int((nominal - expiration).days),
                        "is_quad_witching": month_cursor.month in {3, 6, 9, 12},
                    }
                )
        if month_cursor.month == 12:
            month_cursor = pd.Timestamp(month_cursor.year + 1, 1, 1)
        else:
            month_cursor = pd.Timestamp(month_cursor.year, month_cursor.month + 1, 1)

    return pd.DataFrame(rows)


def _window_mean(df: pd.DataFrame, pos: int, offsets: range, metric: str) -> float:
    idx = [pos + off for off in offsets]
    return float(df.iloc[idx][metric].mean())


def build_event_panel(df: pd.DataFrame, calendar: pd.DataFrame, metric: str = "range_var") -> tuple[pd.DataFrame, pd.DataFrame]:
    date_to_pos = {ts: i for i, ts in enumerate(df.index)}
    event_rows: list[dict[str, Any]] = []
    offset_rows: list[dict[str, Any]] = []

    for row in calendar.to_dict("records"):
        exp_ts = pd.Timestamp(row["expiration_date"])
        pos = date_to_pos.get(exp_ts)
        if pos is None or pos < 5 or pos + 5 >= len(df):
            continue

        exclusion_positions = set(range(pos - 5, pos + 6))
        same_month_positions = [
            i
            for i, ts in enumerate(df.index)
            if ts.year == exp_ts.year and ts.month == exp_ts.month and i not in exclusion_positions
        ]
        if len(same_month_positions) < 5:
            continue

        control = float(df.iloc[same_month_positions][metric].mean())
        pre3 = _window_mean(df, pos, range(-3, 0), metric)
        pre5 = _window_mean(df, pos, range(-5, 0), metric)
        expiration = _window_mean(df, pos, range(0, 1), metric)
        post3 = _window_mean(df, pos, range(1, 4), metric)
        post5 = _window_mean(df, pos, range(1, 6), metric)

        event_rows.append(
            {
                **row,
                "metric": metric,
                "control_n_days": len(same_month_positions),
                "control_mean": control,
                "pre3_mean": pre3,
                "pre5_mean": pre5,
                "expiration_mean": expiration,
                "post3_mean": post3,
                "post5_mean": post5,
                "pre3_minus_control": pre3 - control,
                "expiration_minus_control": expiration - control,
                "post3_minus_control": post3 - control,
                "post5_minus_control": post5 - control,
                "post3_minus_pre3": post3 - pre3,
                "post5_minus_pre5": post5 - pre5,
                "pre3_ratio_control": pre3 / control if control > 0 else np.nan,
                "expiration_ratio_control": expiration / control if control > 0 else np.nan,
                "post3_ratio_control": post3 / control if control > 0 else np.nan,
            }
        )

        for off in range(-5, 6):
            value = float(df.iloc[pos + off][metric])
            offset_rows.append(
                {
                    "event_month": row["event_month"],
                    "expiration_date": row["expiration_date"],
                    "is_quad_witching": row["is_quad_witching"],
                    "offset": off,
                    "value": value,
                    "control_mean": control,
                    "ratio_control": value / control if control > 0 else np.nan,
                }
            )

    return pd.DataFrame(event_rows), pd.DataFrame(offset_rows)


@dataclass
class OneSampleResult:
    n: int
    mean: float | None
    median: float | None
    std: float | None
    t_stat: float | None
    t_p_two_sided: float | None
    wilcoxon_p_two_sided: float | None
    cohen_d: float | None
    share_positive: float | None
    bootstrap_ci_low: float | None
    bootstrap_ci_high: float | None
    bootstrap_p_less: float | None
    bootstrap_p_greater: float | None
    bootstrap_p_two_sided: float | None


def one_sample_test(values: pd.Series | np.ndarray) -> OneSampleResult:
    x = pd.Series(values).dropna().astype(float).to_numpy()
    n = int(len(x))
    if n == 0:
        return OneSampleResult(0, *([None] * 13))  # type: ignore[arg-type]

    mean = float(np.mean(x))
    median = float(np.median(x))
    std = float(np.std(x, ddof=1)) if n > 1 else 0.0
    if n > 1 and std > 0:
        t_stat, t_p = st.ttest_1samp(x, popmean=0.0)
        cohen_d = mean / std
    else:
        t_stat, t_p, cohen_d = np.nan, np.nan, np.nan

    try:
        if n > 1 and np.any(np.abs(x) > 0):
            wilcoxon_p = float(st.wilcoxon(x, zero_method="wilcox", alternative="two-sided").pvalue)
        else:
            wilcoxon_p = np.nan
    except ValueError:
        wilcoxon_p = np.nan

    rng = np.random.default_rng(SEED)
    boot = rng.choice(x, size=(BOOTSTRAP_REPS, n), replace=True).mean(axis=1)
    p_less = float(np.mean(boot >= 0.0))
    p_greater = float(np.mean(boot <= 0.0))
    p_two = float(min(1.0, 2.0 * min(p_less, p_greater)))
    ci_low, ci_high = np.percentile(boot, [2.5, 97.5])

    return OneSampleResult(
        n=n,
        mean=_json_float(mean),
        median=_json_float(median),
        std=_json_float(std),
        t_stat=_json_float(t_stat),
        t_p_two_sided=_json_float(t_p),
        wilcoxon_p_two_sided=_json_float(wilcoxon_p),
        cohen_d=_json_float(cohen_d),
        share_positive=_json_float(np.mean(x > 0.0)),
        bootstrap_ci_low=_json_float(ci_low),
        bootstrap_ci_high=_json_float(ci_high),
        bootstrap_p_less=_json_float(p_less),
        bootstrap_p_greater=_json_float(p_greater),
        bootstrap_p_two_sided=_json_float(p_two),
    )


def two_group_test(values: pd.Series, groups: pd.Series) -> dict[str, Any]:
    x = pd.Series(values).astype(float)
    g = pd.Series(groups).astype(bool)
    a = x[g].dropna().to_numpy()
    b = x[~g].dropna().to_numpy()
    rng = np.random.default_rng(SEED)
    obs = float(np.mean(a) - np.mean(b))
    if len(a) > 1 and len(b) > 1:
        welch = st.ttest_ind(a, b, equal_var=False)
        boot = rng.choice(a, size=(BOOTSTRAP_REPS, len(a)), replace=True).mean(axis=1) - rng.choice(
            b, size=(BOOTSTRAP_REPS, len(b)), replace=True
        ).mean(axis=1)
        ci_low, ci_high = np.percentile(boot, [2.5, 97.5])
        p_greater = float(np.mean(boot <= 0.0))
        p_less = float(np.mean(boot >= 0.0))
    else:
        welch = None
        ci_low = ci_high = p_greater = p_less = np.nan
    return {
        "n_true": int(len(a)),
        "n_false": int(len(b)),
        "mean_true": _json_float(np.mean(a)) if len(a) else None,
        "mean_false": _json_float(np.mean(b)) if len(b) else None,
        "mean_diff_true_minus_false": _json_float(obs),
        "welch_t": _json_float(welch.statistic if welch else None),
        "welch_p_two_sided": _json_float(welch.pvalue if welch else None),
        "bootstrap_ci_low": _json_float(ci_low),
        "bootstrap_ci_high": _json_float(ci_high),
        "bootstrap_p_greater": _json_float(p_greater),
        "bootstrap_p_less": _json_float(p_less),
    }


def plot_offset_profile(offset_panel: pd.DataFrame) -> str:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    grouped = offset_panel.groupby("offset")["ratio_control"]
    offsets = np.array(sorted(offset_panel["offset"].unique()))
    means = grouped.mean().reindex(offsets).to_numpy()
    lo = []
    hi = []
    rng = np.random.default_rng(SEED)
    for off in offsets:
        x = offset_panel.loc[offset_panel["offset"] == off, "ratio_control"].dropna().to_numpy()
        boot = rng.choice(x, size=(BOOTSTRAP_REPS, len(x)), replace=True).mean(axis=1)
        q = np.percentile(boot, [2.5, 97.5])
        lo.append(q[0])
        hi.append(q[1])

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(offsets, means, marker="o", color="#1f77b4", label="Mean / same-month control")
    ax.fill_between(offsets, lo, hi, color="#1f77b4", alpha=0.18, label="Bootstrap 95% CI")
    ax.axhline(1.0, color="black", linewidth=1, linestyle="--")
    ax.axvline(0, color="#8c564b", linewidth=1, linestyle=":")
    ax.set_title("SPY Range Variance Around Monthly OPEX")
    ax.set_xlabel("Trading-day offset from OPEX")
    ax.set_ylabel("Range variance ratio vs same-month control")
    ax.legend(loc="best")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "K1354_opex_offset_profile.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path.relative_to(HERE))


def plot_event_differences(event_panel: pd.DataFrame) -> str:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    specs = [
        ("pre3_minus_control", "Pre3 - control"),
        ("expiration_minus_control", "OPEX - control"),
        ("post3_minus_pre3", "Post3 - Pre3"),
        ("post3_minus_control", "Post3 - control"),
    ]
    labels = []
    means = []
    err_low = []
    err_high = []
    for col, label in specs:
        res = one_sample_test(event_panel[col])
        labels.append(label)
        means.append(res.mean or 0.0)
        err_low.append((res.mean or 0.0) - (res.bootstrap_ci_low or 0.0))
        err_high.append((res.bootstrap_ci_high or 0.0) - (res.mean or 0.0))

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(labels))
    ax.bar(x, means, color=["#4c78a8", "#f58518", "#54a24b", "#b279a2"], alpha=0.85)
    ax.errorbar(x, means, yerr=[err_low, err_high], fmt="none", color="black", capsize=4, linewidth=1)
    ax.axhline(0.0, color="black", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_title("Event-Level Range Variance Differences")
    ax.set_ylabel("Daily range variance difference")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "K1354_event_differences.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path.relative_to(HERE))


def decide_verdict(tests: dict[str, Any]) -> tuple[str, str]:
    pre = tests["pre3_vs_control"]
    release = tests["post3_vs_pre3"]
    pre_pass = (
        pre["mean"] is not None
        and pre["mean"] < 0
        and pre["t_stat"] is not None
        and pre["t_stat"] < -HARVEY_T
        and pre["t_p_two_sided"] is not None
        and pre["t_p_two_sided"] < BONFERRONI_ALPHA
        and pre["bootstrap_ci_high"] is not None
        and pre["bootstrap_ci_high"] < 0
        and pre["bootstrap_p_less"] is not None
        and pre["bootstrap_p_less"] < BONFERRONI_ALPHA
    )
    release_pass = (
        release["mean"] is not None
        and release["mean"] > 0
        and release["t_stat"] is not None
        and release["t_stat"] > HARVEY_T
        and release["t_p_two_sided"] is not None
        and release["t_p_two_sided"] < BONFERRONI_ALPHA
        and release["bootstrap_ci_low"] is not None
        and release["bootstrap_ci_low"] > 0
        and release["bootstrap_p_greater"] is not None
        and release["bootstrap_p_greater"] < BONFERRONI_ALPHA
    )
    if pre_pass and release_pass:
        return "PASS", "Both pre-OPEX suppression and post-OPEX release pass paired event-level bootstrap gates."
    if pre_pass or release_pass:
        return "CONDITIONAL_PASS", "Only one of the two primary gamma-cliff gates passes; report as mechanism-specific, not a full gamma-cliff confirmation."
    return "NULL", "Neither primary event-level Harvey/Bonferroni/bootstrap gate supports a robust monthly OPEX gamma-cliff effect."


def main() -> None:
    np.random.seed(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    ohlcv = load_spy_ohlcv()
    df = add_volatility_measures(ohlcv)
    calendar = build_opex_calendar(df.index)

    # Explicit audit hook for the project anti-lookahead convention. This is not
    # used to classify the current event day; it is the lagged signal that would
    # be used by any forecasting or trading rule derived from the known calendar.
    event_dates = set(pd.to_datetime(calendar["expiration_date"]))
    pre_window = pd.Series(False, index=df.index)
    for exp in event_dates:
        if exp in df.index:
            pos = df.index.get_loc(exp)
            if isinstance(pos, int) and pos >= 3:
                pre_window.iloc[pos - 3 : pos] = True
    df["opex_pre3_calendar_signal_lag1"] = pre_window.astype(int).shift(1).fillna(0).astype(int)

    event_panel, offset_panel = build_event_panel(df, calendar, metric="range_var")
    if event_panel.empty:
        raise RuntimeError("No evaluable OPEX events after window/control filters")

    event_panel.to_csv(EVENT_PANEL_PATH, index=False)
    offset_panel.to_csv(OFFSET_PANEL_PATH, index=False)

    tests = {
        "pre3_vs_control": asdict(one_sample_test(event_panel["pre3_minus_control"])),
        "expiration_vs_control": asdict(one_sample_test(event_panel["expiration_minus_control"])),
        "post3_vs_pre3": asdict(one_sample_test(event_panel["post3_minus_pre3"])),
        "post3_vs_control": asdict(one_sample_test(event_panel["post3_minus_control"])),
        "post5_vs_pre5": asdict(one_sample_test(event_panel["post5_minus_pre5"])),
        "quad_vs_nonquad_post3_minus_pre3": two_group_test(
            event_panel["post3_minus_pre3"], event_panel["is_quad_witching"]
        ),
        "quad_vs_nonquad_pre3_minus_control": two_group_test(
            event_panel["pre3_minus_control"], event_panel["is_quad_witching"]
        ),
    }
    verdict, verdict_reason = decide_verdict(tests)

    fig_profile = plot_offset_profile(offset_panel)
    fig_diff = plot_event_differences(event_panel)

    data_start = df.index.min().date().isoformat()
    data_end = df.index.max().date().isoformat()
    results = {
        "experiment_id": "K1354",
        "title": "Monthly OPEX gamma-cliff event study on SPY daily range variance",
        "run_timestamp_utc": _utc_now(),
        "seed": SEED,
        "data": {
            "source": "yfinance",
            "ticker": TICKER,
            "start_requested": START,
            "end_requested": END,
            "sample_start": data_start,
            "sample_end": data_end,
            "trading_days": int(len(df)),
            "ohlcv_cache": str(SPY_CACHE_PATH.relative_to(HERE)),
            "auto_adjust": True,
        },
        "event_calendar": {
            "rule": "third Friday monthly option expiration; if not a trading day, previous SPY trading day in same month",
            "calendar_events": int(len(calendar)),
            "evaluable_events": int(len(event_panel)),
            "quad_witching_events": int(event_panel["is_quad_witching"].sum()),
            "nonquad_events": int((~event_panel["is_quad_witching"]).sum()),
            "first_event": str(event_panel["expiration_date"].iloc[0]),
            "last_event": str(event_panel["expiration_date"].iloc[-1]),
        },
        "methodology": {
            "primary_metric": "Parkinson range variance = log(High/Low)^2 / (4 log 2)",
            "unit_of_inference": "one row per monthly OPEX event",
            "control": "same calendar month trading days excluding offsets -5..+5 around OPEX",
            "primary_windows": {
                "pre3": "trading days -3,-2,-1",
                "expiration": "trading day 0",
                "post3": "trading days +1,+2,+3",
                "post5": "trading days +1..+5",
            },
            "formal_tests": "paired event-level t/Wilcoxon plus 5000-rep bootstrap; quad-vs-nonquad Welch plus bootstrap",
            "lookahead_policy": "Calendar events are known ex ante; code includes opex_pre3_calendar_signal_lag1 = signal.shift(1) for forecasting-style use.",
        },
        "success_gate": {
            "primary_pattern": "pre3_vs_control negative and post3_vs_pre3 positive",
            "t_stat_threshold": f"|t| > {HARVEY_T} in the pre-registered direction",
            "bonferroni_alpha": BONFERRONI_ALPHA,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "bootstrap_requirement": "95% CI excludes zero in the pre-registered direction and one-sided bootstrap p < Bonferroni alpha",
        },
        "descriptive": {
            "mean_control_range_var": _json_float(event_panel["control_mean"].mean()),
            "mean_pre3_range_var": _json_float(event_panel["pre3_mean"].mean()),
            "mean_expiration_range_var": _json_float(event_panel["expiration_mean"].mean()),
            "mean_post3_range_var": _json_float(event_panel["post3_mean"].mean()),
            "mean_pre3_ratio_control": _json_float(event_panel["pre3_ratio_control"].mean()),
            "mean_expiration_ratio_control": _json_float(event_panel["expiration_ratio_control"].mean()),
            "mean_post3_ratio_control": _json_float(event_panel["post3_ratio_control"].mean()),
        },
        "tests": tests,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "research_honesty_notes": [
            "This is a yfinance daily-OHLC range-variance proxy; it does not observe dealer gamma exposure or intraday hedging flow.",
            "A significant pre/post window pattern would be consistent with, but not proof of, dealer-long-gamma mechanics.",
            "Null results must not be interpreted as evidence that true options-market gamma exposure is irrelevant.",
        ],
        "references": [
            {
                "citation": "Ni, Pearson, and Poteshman (2005), Journal of Financial Economics, Stock price clustering on option expiration dates.",
                "url": "https://ideas.repec.org/a/eee/jfinec/v78y2005i1p49-87.html",
            },
            {
                "citation": "Avellaneda and Lipkin (2003), Quantitative Finance, A market-induced mechanism for stock pinning.",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=458020",
            },
            {
                "citation": "Feinstein and Goetzmann (1988), Federal Reserve Bank of Atlanta Economic Review, The effect of the triple witching hour on stock market volatility.",
                "url": "https://fraser.stlouisfed.org/files/docs/publications/frbatlreview/pages/67107_1985-1989.pdf",
            },
            {
                "citation": "Stoll and Whaley (1991), Financial Analysts Journal, Expiration-day effects: what has changed?",
                "url": "https://www.whaley.info/research-articles/1990-1999",
            },
        ],
        "artifacts": {
            "event_panel": str(EVENT_PANEL_PATH.relative_to(HERE)),
            "offset_panel": str(OFFSET_PANEL_PATH.relative_to(HERE)),
            "figures": [fig_profile, fig_diff],
        },
    }

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "events": len(event_panel), "sample_end": data_end}, ensure_ascii=False))


if __name__ == "__main__":
    main()
