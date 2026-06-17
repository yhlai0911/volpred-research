"""K1529: Credit-spread FOMC volatility precursor ETF-proxy pilot.

Research question:
Do corporate-bond ETF credit-stress proxies react unusually around FOMC
meetings, and do those reactions add out-of-sample information for SPY
realized variance beyond lagged SPY RV and VIX?

Scope discipline:
- This is an ETF-proxy pilot. It is not a firm-level or TRACE bond-level test
  of industry credit spreads.
- Sticky/flexible price-setting groups are represented by crude sector ETF
  baskets. They are mechanism diagnostics only.
- FOMC surprises come from the SF Fed public Monetary Policy Surprises chart
  CSV. If the CSV is unavailable, the script hard-fails rather than inventing
  surprises.

Lookahead discipline:
- Pre-FOMC model: predictors use information through t-1 and target is t..t+5.
- Post-response model: predictors include t..t+5 credit response, and target is
  t+6..t+26, so the predictor window never overlaps the target window.
- yfinance calls pin auto_adjust=False and use Adj Close for ETF total returns.

Run:
    uv run python experiments/k1529_credit_spread_fomc_vol/k1529_credit_spread_fomc_vol.py
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

warnings.filterwarnings("ignore", category=FutureWarning)

SEED = 42
RNG = np.random.default_rng(SEED)

EXPERIMENT_ID = "K1529"
EXPERIMENT_SLUG = "k1529_credit_spread_fomc_vol"
TASK_ID = "research_credit_spread_fomc_vol"
HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / f"{EXPERIMENT_SLUG}_results.json"
FIG_PATH = HERE / "k1529_credit_spread_fomc_vol.png"

START = "2012-01-01"
END = "2026-06-18"
OOS_START = pd.Timestamp("2019-01-01")
TRADING_DAYS = 252
BONFERRONI_TESTS = 5
BONFERRONI_ALPHA = 0.05 / BONFERRONI_TESTS
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 5

SURPRISE_CSV_URL = (
    "https://www.frbsf.org/wp-content/uploads/"
    "chart1-monetary-policy-surprises.csv?2026-06-16"
)

CREDIT_TICKERS = ["HYG", "LQD", "VCIT", "VCSH"]
MARKET_TICKERS = ["SPY", "^VIX"]
STICKY_SECTORS = ["XLP", "XLU", "XLV"]
FLEXIBLE_SECTORS = ["XLE", "XLB", "XLK"]
ALL_TICKERS = CREDIT_TICKERS + MARKET_TICKERS + STICKY_SECTORS + FLEXIBLE_SECTORS


@dataclass(frozen=True)
class OOSResult:
    model: str
    target: str
    train_n: int
    oos_n: int
    baseline_qlike: float
    augmented_qlike: float
    qlike_improvement_pct: float
    dm_t_augmented_vs_baseline: float
    dm_p_augmented_vs_baseline: float
    harvey_pass: bool


def _round_or_none(x: float, ndigits: int = 6) -> float | None:
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), ndigits)


def load_surprises() -> pd.DataFrame:
    df = pd.read_csv(SURPRISE_CSV_URL, encoding="utf-8-sig")
    needed = {"Date", "Surprise", "Orthogonalized Surprise"}
    missing = needed - set(df.columns)
    if missing:
        raise RuntimeError(f"SF Fed surprise CSV missing columns: {sorted(missing)}")
    df = df.rename(
        columns={
            "Date": "fomc_date",
            "Surprise": "surprise_bp",
            "Orthogonalized Surprise": "orth_surprise_bp",
        }
    )
    df["fomc_date"] = pd.to_datetime(df["fomc_date"])
    df = df.dropna(subset=["fomc_date", "surprise_bp", "orth_surprise_bp"])
    df = df[(df["fomc_date"] >= START) & (df["fomc_date"] <= END)]
    return df.sort_values("fomc_date").reset_index(drop=True)


def _download_one(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start=START, end=END, auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"no yfinance data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    needed = ["High", "Low", "Close"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise RuntimeError(f"{ticker} missing yfinance columns: {missing}")
    if "Adj Close" not in df.columns:
        df["Adj Close"] = df["Close"]
    out = df[["High", "Low", "Close", "Adj Close"]].copy()
    out.columns = pd.MultiIndex.from_product([[ticker], out.columns])
    return out


def load_panel() -> pd.DataFrame:
    frames = [_download_one(ticker) for ticker in ALL_TICKERS]
    panel = pd.concat(frames, axis=1, sort=True).sort_index()
    return panel.dropna(how="all")


def trading_date_on_or_after(index: pd.DatetimeIndex, date: pd.Timestamp, max_gap_days: int = 3) -> pd.Timestamp | None:
    later = index[index >= date]
    if len(later) == 0:
        return None
    candidate = later[0]
    if (candidate - date).days > max_gap_days:
        return None
    return candidate


def window_sum(series: pd.Series, event_date: pd.Timestamp, start_offset: int, end_offset: int) -> float:
    idx = series.index
    if event_date not in idx:
        return float("nan")
    pos = idx.get_loc(event_date)
    lo = pos + start_offset
    hi = pos + end_offset
    if lo < 0 or hi >= len(idx):
        return float("nan")
    vals = series.iloc[lo : hi + 1].dropna()
    expected_n = hi - lo + 1
    if len(vals) < expected_n:
        return float("nan")
    return float(vals.sum())


def window_mean(series: pd.Series, event_date: pd.Timestamp, start_offset: int, end_offset: int) -> float:
    idx = series.index
    if event_date not in idx:
        return float("nan")
    pos = idx.get_loc(event_date)
    lo = pos + start_offset
    hi = pos + end_offset
    if lo < 0 or hi >= len(idx):
        return float("nan")
    vals = series.iloc[lo : hi + 1].dropna()
    expected_n = hi - lo + 1
    if len(vals) < expected_n:
        return float("nan")
    return float(vals.mean())


def window_rv(logret: pd.Series, event_date: pd.Timestamp, start_offset: int, end_offset: int) -> float:
    idx = logret.index
    if event_date not in idx:
        return float("nan")
    pos = idx.get_loc(event_date)
    lo = pos + start_offset
    hi = pos + end_offset
    if lo < 0 or hi >= len(idx):
        return float("nan")
    vals = logret.iloc[lo : hi + 1].dropna()
    expected_n = hi - lo + 1
    if len(vals) < expected_n:
        return float("nan")
    return float((vals**2).sum() * TRADING_DAYS / expected_n)


def build_baseline_exclusion(index: pd.DatetimeIndex, event_dates: list[pd.Timestamp], half_width: int = 5) -> set[int]:
    excluded: set[int] = set()
    for d in event_dates:
        if d not in index:
            continue
        pos = index.get_loc(d)
        for j in range(max(0, pos - half_width), min(len(index), pos + half_width + 1)):
            excluded.add(j)
    return excluded


def same_month_baseline_window_sum(
    series: pd.Series,
    event_date: pd.Timestamp,
    event_dates: list[pd.Timestamp],
    start_offset: int,
    end_offset: int,
) -> tuple[float, int]:
    idx = series.index
    if event_date not in idx:
        return float("nan"), 0
    excluded = build_baseline_exclusion(idx, event_dates, half_width=5)
    event_month = event_date.to_period("M")
    vals: list[float] = []
    for i, date in enumerate(idx):
        if i in excluded or date.to_period("M") != event_month:
            continue
        lo = i + start_offset
        hi = i + end_offset
        if lo < 0 or hi >= len(idx):
            continue
        w = series.iloc[lo : hi + 1].dropna()
        if len(w) == hi - lo + 1:
            vals.append(float(w.sum()))
    if not vals:
        return float("nan"), 0
    return float(np.mean(vals)), len(vals)


def hac_ols(y: pd.Series, x: pd.DataFrame, maxlags: int = 1) -> dict[str, dict[str, float]]:
    valid = pd.concat([y.rename("y"), x], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) < 20:
        return {}
    model = sm.OLS(valid["y"], sm.add_constant(valid.drop(columns=["y"]))).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": maxlags},
    )
    out: dict[str, dict[str, float]] = {}
    for name in model.params.index:
        out[name] = {
            "coef": float(model.params[name]),
            "t": float(model.tvalues[name]),
            "p": float(model.pvalues[name]),
        }
    out["_model"] = {
        "n": int(model.nobs),
        "r2": float(model.rsquared),
        "aic": float(model.aic),
    }
    return out


def paired_bootstrap_p_greater(values: np.ndarray, reps: int, block: int, rng: np.random.Generator) -> float:
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) < 10:
        return float("nan")
    obs = float(vals.mean())
    centered = vals - obs
    n = len(centered)
    n_blocks = int(math.ceil(n / block))
    count = 0
    for _ in range(reps):
        starts = rng.integers(0, n, size=n_blocks)
        sample = []
        for s in starts:
            sample.extend(centered[(s + np.arange(block)) % n])
        boot_mean = float(np.mean(sample[:n]))
        if boot_mean >= obs:
            count += 1
    return float((count + 1) / (reps + 1))


def fit_log_rv_oos(
    events: pd.DataFrame,
    target_col: str,
    baseline_cols: list[str],
    augmented_cols: list[str],
    model_name: str,
) -> OOSResult:
    cols = [target_col] + sorted(set(baseline_cols + augmented_cols))
    data = events[["event_date"] + cols].replace([np.inf, -np.inf], np.nan).dropna()
    data = data[data[target_col] > 0].copy()
    train = data[data["event_date"] < OOS_START]
    oos = data[data["event_date"] >= OOS_START]
    if len(train) < 30 or len(oos) < 15:
        return OOSResult(model_name, target_col, len(train), len(oos), np.nan, np.nan, np.nan, 0.0, 1.0, False)

    eps = 1e-12
    y_train = np.log(train[target_col].to_numpy() + eps)
    y_oos_actual = oos[target_col].to_numpy()

    def fit_predict(feature_cols: list[str]) -> np.ndarray:
        x_train = sm.add_constant(train[feature_cols], has_constant="add")
        x_oos = sm.add_constant(oos[feature_cols], has_constant="add")
        model = sm.OLS(y_train, x_train).fit()
        pred_log = model.predict(x_oos).to_numpy()
        return np.exp(pred_log)

    base_pred = fit_predict(baseline_cols)
    aug_pred = fit_predict(augmented_cols)
    base_loss = qlike_pointwise(y_oos_actual, base_pred)
    aug_loss = qlike_pointwise(y_oos_actual, aug_pred)
    dm_t, dm_p = dm_test(aug_loss, base_loss, h=5)
    base_q = qlike(y_oos_actual, base_pred)
    aug_q = qlike(y_oos_actual, aug_pred)
    improvement = (base_q - aug_q) / abs(base_q) * 100 if np.isfinite(base_q) and base_q != 0 else np.nan
    return OOSResult(
        model=model_name,
        target=target_col,
        train_n=int(len(train)),
        oos_n=int(len(oos)),
        baseline_qlike=float(base_q),
        augmented_qlike=float(aug_q),
        qlike_improvement_pct=float(improvement),
        dm_t_augmented_vs_baseline=float(dm_t),
        dm_p_augmented_vs_baseline=float(dm_p),
        harvey_pass=bool(dm_t < -3.0),
    )


def build_event_panel(panel: pd.DataFrame, surprises: pd.DataFrame) -> pd.DataFrame:
    adj = panel.xs("Adj Close", level=1, axis=1)
    close = panel.xs("Close", level=1, axis=1)
    high = panel.xs("High", level=1, axis=1)
    low = panel.xs("Low", level=1, axis=1)

    logret = np.log(adj / adj.shift(1))
    close_ret = np.log(close / close.shift(1))
    event_dates: list[pd.Timestamp] = []
    mapped_rows = []
    for row in surprises.itertuples(index=False):
        event_date = trading_date_on_or_after(panel.index, row.fomc_date)
        if event_date is None:
            continue
        event_dates.append(event_date)
        mapped_rows.append((row, event_date))

    credit_hyg_lqd = -(logret["HYG"] - logret["LQD"])
    credit_hyg_vcit = -(logret["HYG"] - logret["VCIT"])
    credit_lqd_vcsh = -(logret["LQD"] - logret["VCSH"])
    hyg_range = (high["HYG"] - low["HYG"]) / close["HYG"]

    sticky_ret = logret[STICKY_SECTORS].mean(axis=1)
    flexible_ret = logret[FLEXIBLE_SECTORS].mean(axis=1)

    rows: list[dict[str, float | str]] = []
    for source_row, event_date in mapped_rows:
        baseline_hyg_lqd, baseline_n = same_month_baseline_window_sum(
            credit_hyg_lqd,
            event_date,
            event_dates,
            0,
            5,
        )
        row = {
            "fomc_date": source_row.fomc_date.date().isoformat(),
            "event_date": event_date,
            "surprise_bp": float(source_row.surprise_bp),
            "orth_surprise_bp": float(source_row.orth_surprise_bp),
            "abs_orth_surprise_bp": abs(float(source_row.orth_surprise_bp)),
            "credit_hyg_lqd_pre_m5_m1": window_sum(credit_hyg_lqd, event_date, -5, -1),
            "credit_hyg_lqd_event_0_5": window_sum(credit_hyg_lqd, event_date, 0, 5),
            "credit_hyg_lqd_event_m1_5": window_sum(credit_hyg_lqd, event_date, -1, 5),
            "credit_hyg_lqd_same_month_baseline_0_5": baseline_hyg_lqd,
            "credit_hyg_lqd_baseline_n": baseline_n,
            "credit_hyg_vcit_event_0_5": window_sum(credit_hyg_vcit, event_date, 0, 5),
            "credit_lqd_vcsh_event_0_5": window_sum(credit_lqd_vcsh, event_date, 0, 5),
            "hyg_range_pre_m5_m1": window_mean(hyg_range, event_date, -5, -1),
            "hyg_range_event_0_5": window_mean(hyg_range, event_date, 0, 5),
            "sticky_sector_rv_0_5": window_rv(sticky_ret, event_date, 0, 5),
            "flexible_sector_rv_0_5": window_rv(flexible_ret, event_date, 0, 5),
            "spy_rv_pre_21": window_rv(logret["SPY"], event_date, -21, -1),
            "spy_rv_event_0_5": window_rv(logret["SPY"], event_date, 0, 5),
            "spy_rv_post_6_26": window_rv(logret["SPY"], event_date, 6, 26),
            "vix_lag1": float(close["^VIX"].shift(1).loc[event_date]) if event_date in close.index else np.nan,
            "spy_ret_event_0_5": window_sum(close_ret["SPY"], event_date, 0, 5),
        }
        rows.append(row)

    events = pd.DataFrame(rows)
    events["credit_hyg_lqd_diff_vs_baseline_0_5"] = (
        events["credit_hyg_lqd_event_0_5"] - events["credit_hyg_lqd_same_month_baseline_0_5"]
    )
    events["hyg_range_change_event_minus_pre"] = (
        events["hyg_range_event_0_5"] - events["hyg_range_pre_m5_m1"]
    )
    events["sticky_minus_flexible_rv_0_5"] = (
        events["sticky_sector_rv_0_5"] - events["flexible_sector_rv_0_5"]
    )
    events["log_spy_rv_pre_21"] = np.log(events["spy_rv_pre_21"].clip(lower=1e-12))
    events["log_vix_var_lag1"] = np.log(((events["vix_lag1"] / 100.0) ** 2).clip(lower=1e-12))
    return events


def summarize_event_tests(events: pd.DataFrame) -> dict:
    paired = events[
        [
            "credit_hyg_lqd_event_0_5",
            "credit_hyg_lqd_same_month_baseline_0_5",
            "credit_hyg_lqd_diff_vs_baseline_0_5",
        ]
    ].replace([np.inf, -np.inf], np.nan).dropna()
    valid_diff = paired["credit_hyg_lqd_diff_vs_baseline_0_5"]
    t_stat, t_p_two = stats.ttest_1samp(valid_diff, popmean=0.0, nan_policy="omit")
    if len(valid_diff) >= 10 and not np.allclose(valid_diff, 0):
        wilcoxon = stats.wilcoxon(valid_diff, alternative="greater")
        wilcoxon_p = float(wilcoxon.pvalue)
    else:
        wilcoxon_p = float("nan")

    surprise_reg = hac_ols(
        events["credit_hyg_lqd_event_0_5"],
        events[["abs_orth_surprise_bp", "log_vix_var_lag1", "credit_hyg_lqd_pre_m5_m1"]],
        maxlags=1,
    )
    sticky_reg = hac_ols(
        events["sticky_minus_flexible_rv_0_5"],
        events[["abs_orth_surprise_bp", "log_vix_var_lag1", "credit_hyg_lqd_event_0_5"]],
        maxlags=1,
    )

    oos_pre = fit_log_rv_oos(
        events,
        target_col="spy_rv_event_0_5",
        baseline_cols=["log_spy_rv_pre_21", "log_vix_var_lag1"],
        augmented_cols=["log_spy_rv_pre_21", "log_vix_var_lag1", "credit_hyg_lqd_pre_m5_m1"],
        model_name="pre_fomc_credit_to_event_spy_rv",
    )
    oos_post = fit_log_rv_oos(
        events,
        target_col="spy_rv_post_6_26",
        baseline_cols=["log_spy_rv_pre_21", "log_vix_var_lag1", "abs_orth_surprise_bp"],
        augmented_cols=[
            "log_spy_rv_pre_21",
            "log_vix_var_lag1",
            "abs_orth_surprise_bp",
            "credit_hyg_lqd_event_0_5",
        ],
        model_name="post_response_credit_to_next_month_spy_rv",
    )

    return {
        "credit_stress_event_vs_same_month_baseline": {
            "n_events": int(len(valid_diff)),
            "event_mean": _round_or_none(paired["credit_hyg_lqd_event_0_5"].mean()),
            "same_month_baseline_mean": _round_or_none(paired["credit_hyg_lqd_same_month_baseline_0_5"].mean()),
            "diff_mean": _round_or_none(valid_diff.mean()),
            "diff_median": _round_or_none(valid_diff.median()),
            "paired_t_stat": _round_or_none(t_stat, 4),
            "paired_t_p_two_sided": _round_or_none(t_p_two, 6),
            "wilcoxon_p_one_sided_greater": _round_or_none(wilcoxon_p, 6),
            "block_bootstrap_p_one_sided_greater": _round_or_none(
                paired_bootstrap_p_greater(valid_diff.to_numpy(), BOOTSTRAP_REPS, BOOTSTRAP_BLOCK, RNG),
                6,
            ),
            "bonferroni_alpha": BONFERRONI_ALPHA,
        },
        "surprise_to_credit_response_hac_ols": surprise_reg,
        "sticky_flexible_sector_proxy_hac_ols": sticky_reg,
        "oos_models": [oos_pre.__dict__, oos_post.__dict__],
    }


def make_figure(events: pd.DataFrame, tests: dict) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))

    diff = events["credit_hyg_lqd_diff_vs_baseline_0_5"].dropna()
    axes[0].hist(diff, bins=18, color="#526d82", edgecolor="white")
    axes[0].axvline(0, color="black", linewidth=0.8)
    axes[0].axvline(diff.mean(), color="#b45f43", linewidth=1.2)
    axes[0].set_title("HYG-LQD stress around FOMC")
    axes[0].set_xlabel("Event t0 to t+5 minus same-month baseline")
    axes[0].set_ylabel("Events")

    scatter = events.dropna(subset=["abs_orth_surprise_bp", "credit_hyg_lqd_event_0_5"])
    axes[1].scatter(
        scatter["abs_orth_surprise_bp"],
        scatter["credit_hyg_lqd_event_0_5"],
        s=28,
        color="#38755b",
        alpha=0.8,
    )
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("Policy surprise vs credit stress")
    axes[1].set_xlabel("|orthogonalized surprise|, bp")
    axes[1].set_ylabel("HYG underperformance vs LQD, 0..5")

    oos = tests["oos_models"]
    labels = ["pre-credit\nSPY RV t0 to t+5", "post-credit\nSPY RV t+6 to t+26"]
    base = [m["baseline_qlike"] for m in oos]
    aug = [m["augmented_qlike"] for m in oos]
    x = np.arange(len(labels))
    width = 0.35
    axes[2].bar(x - width / 2, base, width, label="Baseline", color="#7d8790")
    axes[2].bar(x + width / 2, aug, width, label="Augmented", color="#b47f3d")
    axes[2].set_xticks(x, labels)
    axes[2].set_title("OOS QLIKE, lower is better")
    axes[2].legend(frameon=False)

    fig.suptitle("K1529 credit-spread FOMC vol precursor ETF-proxy pilot", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def build_output(events: pd.DataFrame, panel: pd.DataFrame, tests: dict, elapsed: float) -> dict:
    oos_models = tests["oos_models"]
    oos_passes = [m for m in oos_models if m["harvey_pass"]]
    diff_p = tests["credit_stress_event_vs_same_month_baseline"]["paired_t_p_two_sided"]
    surprise_t = tests["surprise_to_credit_response_hac_ols"].get("abs_orth_surprise_bp", {}).get("t")
    sticky_t = tests["sticky_flexible_sector_proxy_hac_ols"].get("credit_hyg_lqd_event_0_5", {}).get("t")

    if oos_passes:
        verdict = "PASS_NARROW_ETF_PROXY"
        summary = (
            "At least one event-level OOS RV model improves QLIKE at Harvey strength. "
            "This remains an ETF-proxy result, not firm-level sticky-price credit evidence."
        )
    else:
        verdict = "NULL_ETF_PROXY"
        summary = (
            "Corporate-bond ETF credit-stress proxies do not provide Harvey-strength OOS "
            "incremental information for SPY realized variance around FOMC meetings. "
            "Any event-window effects are small or statistically fragile after multiple-testing discipline."
        )

    return {
        "experiment_id": EXPERIMENT_ID,
        "task_id": TASK_ID,
        "title": "Credit-spread FOMC volatility precursor ETF-proxy pilot",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "summary": summary,
        "data": {
            "sources": {
                "prices": "yfinance daily OHLC, auto_adjust=False",
                "monetary_policy_surprises": SURPRISE_CSV_URL,
            },
            "price_start": str(panel.index.min().date()),
            "price_end": str(panel.index.max().date()),
            "tickers": ALL_TICKERS,
            "credit_tickers": CREDIT_TICKERS,
            "sticky_sector_proxy": STICKY_SECTORS,
            "flexible_sector_proxy": FLEXIBLE_SECTORS,
            "n_fomc_events_after_alignment": int(len(events)),
            "first_event": str(pd.to_datetime(events["event_date"]).min().date()),
            "last_event": str(pd.to_datetime(events["event_date"]).max().date()),
            "oos_start": str(OOS_START.date()),
        },
        "method": {
            "credit_stress_proxy": "-(log_return(HYG) - log_return(LQD)); positive means HY underperforms IG, a spread-stress proxy",
            "event_window": "FOMC event date t; credit response t..t+5; pre-credit t-5..t-1",
            "same_month_baseline": "same calendar month candidate windows excluding all FOMC +/-5 trading days",
            "pre_fomc_oos_model": "predict SPY RV t..t+5 using only lagged SPY RV, lagged VIX variance, and credit stress t-5..t-1",
            "post_response_oos_model": "predict SPY RV t+6..t+26; augmented model may use credit stress t..t+5 because target starts after response window",
            "inference": "paired tests, HAC OLS, Patton QLIKE OOS loss, DM HAC h=5, Harvey pass if DM t < -3",
            "multiple_testing": f"{BONFERRONI_TESTS} headline tests; Bonferroni alpha={BONFERRONI_ALPHA:.4f}",
            "lookahead_guard": "all predictor/target windows are non-overlapping where post-event predictors are used; no same-day signal times same-day return strategy",
        },
        "tests": tests,
        "key_numbers": {
            "credit_diff_mean": tests["credit_stress_event_vs_same_month_baseline"]["diff_mean"],
            "credit_diff_p_two_sided": diff_p,
            "surprise_abs_t_to_credit": _round_or_none(surprise_t, 4) if surprise_t is not None else None,
            "sticky_gap_credit_t": _round_or_none(sticky_t, 4) if sticky_t is not None else None,
            "oos_pass_models": [m["model"] for m in oos_passes],
            "best_oos_improvement_pct": _round_or_none(
                max([m["qlike_improvement_pct"] for m in oos_models if np.isfinite(m["qlike_improvement_pct"])], default=np.nan),
                4,
            ),
        },
        "limitations": [
            "ETF proxies blend duration, liquidity, credit quality, and fund microstructure; they are not bond-level credit spreads.",
            "Sector sticky/flexible baskets are crude public-market proxies, not NFIB or firm-level markup/price-duration measures.",
            "SF Fed surprise chart begins in 2012, limiting sample size and excluding older monetary-policy regimes.",
            "Daily data cannot isolate the 2pm ET FOMC announcement window; intraday bond/ETF data would be needed for a true high-frequency shock response.",
            "Five headline tests are reported with Bonferroni discipline; exploratory coefficients should not be marketed as standalone discoveries.",
        ],
        "related_prior": [
            "K513: FOMC raises event-day vol but exposure reduction did not improve strategy Sharpe.",
            "K651/T14/G5/K730: credit-spread and cross-asset stress signals are usually absorbed by VIX or economically too small for daily SPY vol timing.",
            "K1515: HYG illiquidity cross-market features needed AR-only feature-set testing before feature-power claims.",
            "K1522: corporate-bond ETF factor proxies do not rescue factor-zoo premia after conservative lag discipline.",
        ],
        "references": [
            {
                "title": "Augustin, Cong, Corhay, Weber, Price Rigidities and Credit Risk, JFQA",
                "url": "https://jfqa.org/2025/12/04/price-rigidities-and-credit-risk/",
                "use": "Motivates sticky-price firms' stronger credit-spread response to monetary shocks.",
            },
            {
                "title": "SF Fed Monetary Policy Surprises data",
                "url": "https://www.frbsf.org/research-and-insights/data-and-indicators/monetary-policy-surprises/",
                "use": "Public FOMC surprise series used for event-level shock size.",
            },
            {
                "title": "Bernanke and Kuttner (2005), What Explains the Stock Market's Reaction to Federal Reserve Policy?",
                "url": "https://www.newyorkfed.org/research/staff_reports/sr174.html",
                "use": "Canonical monetary-policy surprise event-study motivation.",
            },
            {
                "title": "Gilchrist and Zakrajsek (2012), Credit Spreads and Business Cycle Fluctuations",
                "url": "https://www.aeaweb.org/articles?id=10.1257%2Faer.102.4.1692",
                "use": "Credit spreads contain macro-financial stress information; ETF proxy here is narrower.",
            },
        ],
        "artifacts": {
            "results_json": str(RESULTS_PATH.relative_to(HERE.parents[1])),
            "figure": str(FIG_PATH.relative_to(HERE.parents[1])),
            "script": str(Path(__file__).relative_to(HERE.parents[1])),
        },
        "elapsed_seconds": round(elapsed, 2),
    }


def main() -> None:
    start_time = datetime.now(timezone.utc)
    surprises = load_surprises()
    panel = load_panel()
    events = build_event_panel(panel, surprises)
    events = events.replace([np.inf, -np.inf], np.nan)
    tests = summarize_event_tests(events)
    make_figure(events, tests)
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    output = build_output(events, panel, tests, elapsed)
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"experiment_id": EXPERIMENT_ID, "verdict": output["verdict"], "results": str(RESULTS_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
