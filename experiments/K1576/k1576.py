"""K1576 - defence-spending boom announcements and ETF volatility / beta.

Question: Do public rearmament and defence-budget announcements change the next-day
or next-month volatility of defence, industrial, rate, and dollar ETF proxies? Do they
raise defence ETF beta to the broad equity market?

This is an event-study diagnostic using listed ETF proxies and daily adjusted-close
data. It is not a causal structural model of government procurement. The design keeps
announcement day T out of the post window and reports null / confounded results as such.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import binomtest

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.simplefilter("ignore", FutureWarning)
warnings.simplefilter("ignore", UserWarning)

EXPERIMENT_ID = "K1576"
SEED = 42
B_REPS = 1000

PRE_START_REL = -30
PRE_END_REL = -6
POST_START_REL = 1
BETA_PRE_START_REL = -90
BETA_POST_LEN = 63
MAX_ANCHOR_LAG_DAYS = 7

HERE = Path(__file__).resolve().parent
EVENTS_CSV = HERE / "events.csv"
RESULTS_JSON = HERE / "k1576_results.json"
DETAIL_CSV = HERE / "event_ticker_metric_results.csv"
PRICES_CSV = HERE / "close_yfinance.csv"

TICKER_META = {
    "ITA": {"channel": "defense", "description": "US aerospace and defense ETF"},
    "PPA": {"channel": "defense", "description": "US aerospace and defense ETF"},
    "XAR": {"channel": "defense", "description": "equal-weight aerospace and defense ETF"},
    "XLI": {"channel": "industrials", "description": "US industrial sector ETF"},
    "IYT": {"channel": "transport_industrials", "description": "transportation ETF"},
    "TLT": {"channel": "rates", "description": "20+ year US Treasury ETF"},
    "IEF": {"channel": "rates", "description": "7-10 year US Treasury ETF"},
    "UUP": {"channel": "dollar", "description": "US dollar ETF"},
    "SPY": {"channel": "benchmark", "description": "S&P 500 ETF benchmark"},
    "QQQ": {"channel": "benchmark", "description": "Nasdaq 100 ETF benchmark"},
}

TICKERS = sorted(TICKER_META)
BETA_TICKERS = ["ITA", "PPA", "XAR", "XLI", "IYT"]

RV_METRICS = {
    "t1_r2": {"post_len": 1},
    "rv5": {"post_len": 5},
    "rv22": {"post_len": 22},
}


def load_events() -> pd.DataFrame:
    events = pd.read_csv(EVENTS_CSV, parse_dates=["event_date"])
    expected = {"event_date", "event_id", "region", "announcement_type", "source_url", "source_note"}
    missing = expected - set(events.columns)
    if missing:
        raise ValueError(f"events.csv missing columns: {sorted(missing)}")
    return events.sort_values("event_date").reset_index(drop=True)


def download_prices(tickers: list[str], start: str, end: str) -> tuple[pd.DataFrame, list[str]]:
    print(f"[data] downloading {len(tickers)} tickers {start} -> {end}")
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    closes: dict[str, pd.Series] = {}
    missing: list[str] = []
    if isinstance(raw.columns, pd.MultiIndex):
        for ticker in tickers:
            try:
                close = raw[ticker]["Close"].dropna()
            except KeyError:
                missing.append(ticker)
                print(f"[data] WARN {ticker} missing")
                continue
            if len(close) < 200:
                missing.append(ticker)
                print(f"[data] WARN {ticker} sparse ({len(close)} obs)")
                continue
            closes[ticker] = close
    else:
        ticker = tickers[0]
        close = raw["Close"].dropna()
        if len(close) < 200:
            missing.append(ticker)
        else:
            closes[ticker] = close
    if not closes:
        raise RuntimeError("No usable yfinance data")
    out = pd.DataFrame(closes).sort_index().dropna(how="all")
    out.to_csv(PRICES_CSV)
    print(f"[data] aligned {out.shape[0]} rows x {out.shape[1]} tickers; missing={missing}")
    return out, missing


def compute_returns(closes: pd.DataFrame) -> pd.DataFrame:
    return np.log(closes / closes.shift(1))


def trading_day_offset(idx: pd.DatetimeIndex, event_date: pd.Timestamp, k: int) -> pd.Timestamp | None:
    pos = idx.searchsorted(event_date, side="left")
    if pos >= len(idx):
        return None
    anchor = idx[pos]
    if (anchor - event_date).days > MAX_ANCHOR_LAG_DAYS:
        return None
    target = pos + k
    if target < 0 or target >= len(idx):
        return None
    return idx[target]


def rv_window(series: pd.Series, event_date: pd.Timestamp, post_len: int) -> dict | None:
    clean = series.dropna()
    idx = clean.index
    anchor = trading_day_offset(idx, event_date, 0)
    pre_start = trading_day_offset(idx, event_date, PRE_START_REL)
    pre_end = trading_day_offset(idx, event_date, PRE_END_REL)
    post_start = trading_day_offset(idx, event_date, POST_START_REL)
    post_end = trading_day_offset(idx, event_date, POST_START_REL + post_len - 1)
    if None in (anchor, pre_start, pre_end, post_start, post_end):
        return None
    pre = clean.loc[pre_start:pre_end].dropna()
    post = clean.loc[post_start:post_end].dropna()
    if len(pre) < 15 or len(post) < max(1, int(0.6 * post_len)):
        return None
    pre_mean = float(pre.mean())
    if not np.isfinite(pre_mean) or pre_mean <= 0:
        return None
    ratio = float(post.mean() / pre_mean)
    return {
        "anchor_date": anchor.strftime("%Y-%m-%d"),
        "effect_value": ratio,
        "pre_value": pre_mean,
        "post_value": float(post.mean()),
        "pre_start": pre_start.strftime("%Y-%m-%d"),
        "pre_end": pre_end.strftime("%Y-%m-%d"),
        "post_start": post_start.strftime("%Y-%m-%d"),
        "post_end": post_end.strftime("%Y-%m-%d"),
        "n_pre": int(len(pre)),
        "n_post": int(len(post)),
    }


def random_anchor_rv_pvalue(
    rsq: pd.Series,
    observed_ratio: float,
    post_len: int,
    rng: np.random.Generator,
    b_reps: int = B_REPS,
) -> dict:
    x = rsq.dropna().to_numpy(dtype=float)
    n = len(x)
    valid_anchors = np.arange(abs(PRE_START_REL), n - (POST_START_REL + post_len - 1))
    if len(valid_anchors) < 80:
        return {"p_value": None, "n_anchors": int(len(valid_anchors)), "null_mean": None}
    null = np.empty(b_reps, dtype=float)
    for b in range(b_reps):
        a = int(rng.choice(valid_anchors))
        pre = x[a + PRE_START_REL : a + PRE_END_REL + 1]
        post = x[a + POST_START_REL : a + POST_START_REL + post_len]
        pre_mean = float(np.nanmean(pre))
        null[b] = float(np.nanmean(post) / pre_mean) if pre_mean > 0 else np.nan
    null = null[np.isfinite(null)]
    if len(null) < 80:
        return {"p_value": None, "n_anchors": int(len(valid_anchors)), "null_mean": None}
    return {
        "p_value": float(np.mean(null >= observed_ratio)),
        "n_anchors": int(len(valid_anchors)),
        "null_mean": float(np.mean(null)),
        "null_p95": float(np.percentile(null, 95)),
        "null_p99": float(np.percentile(null, 99)),
    }


def ols_beta(y: pd.Series, x: pd.Series) -> float | None:
    both = pd.concat([y, x], axis=1).dropna()
    if both.shape[0] < 40:
        return None
    yy = both.iloc[:, 0].to_numpy(dtype=float)
    xx = both.iloc[:, 1].to_numpy(dtype=float)
    var_x = float(np.var(xx, ddof=1))
    if not np.isfinite(var_x) or var_x <= 0:
        return None
    cov = float(np.cov(yy, xx, ddof=1)[0, 1])
    return cov / var_x


def beta_window(returns: pd.DataFrame, ticker: str, event_date: pd.Timestamp) -> dict | None:
    if "SPY" not in returns.columns or ticker not in returns.columns:
        return None
    clean = returns[[ticker, "SPY"]].dropna()
    idx = clean.index
    anchor = trading_day_offset(idx, event_date, 0)
    pre_start = trading_day_offset(idx, event_date, BETA_PRE_START_REL)
    pre_end = trading_day_offset(idx, event_date, PRE_END_REL)
    post_start = trading_day_offset(idx, event_date, POST_START_REL)
    post_end = trading_day_offset(idx, event_date, POST_START_REL + BETA_POST_LEN - 1)
    if None in (anchor, pre_start, pre_end, post_start, post_end):
        return None
    pre = clean.loc[pre_start:pre_end]
    post = clean.loc[post_start:post_end]
    beta_pre = ols_beta(pre[ticker], pre["SPY"])
    beta_post = ols_beta(post[ticker], post["SPY"])
    if beta_pre is None or beta_post is None:
        return None
    return {
        "anchor_date": anchor.strftime("%Y-%m-%d"),
        "effect_value": float(beta_post - beta_pre),
        "pre_value": float(beta_pre),
        "post_value": float(beta_post),
        "pre_start": pre_start.strftime("%Y-%m-%d"),
        "pre_end": pre_end.strftime("%Y-%m-%d"),
        "post_start": post_start.strftime("%Y-%m-%d"),
        "post_end": post_end.strftime("%Y-%m-%d"),
        "n_pre": int(pre.dropna().shape[0]),
        "n_post": int(post.dropna().shape[0]),
    }


def random_anchor_beta_pvalue(
    returns: pd.DataFrame,
    ticker: str,
    observed_delta: float,
    rng: np.random.Generator,
    b_reps: int = B_REPS,
) -> dict:
    clean = returns[[ticker, "SPY"]].dropna()
    n = len(clean)
    needed_left = abs(BETA_PRE_START_REL)
    needed_right = POST_START_REL + BETA_POST_LEN - 1
    valid_anchors = np.arange(needed_left, n - needed_right)
    if len(valid_anchors) < 100:
        return {"p_value": None, "n_anchors": int(len(valid_anchors)), "null_mean": None}
    deltas = np.empty(b_reps, dtype=float)
    for b in range(b_reps):
        a = int(rng.choice(valid_anchors))
        pre = clean.iloc[a + BETA_PRE_START_REL : a + PRE_END_REL + 1]
        post = clean.iloc[a + POST_START_REL : a + POST_START_REL + BETA_POST_LEN]
        beta_pre = ols_beta(pre[ticker], pre["SPY"])
        beta_post = ols_beta(post[ticker], post["SPY"])
        deltas[b] = (beta_post - beta_pre) if beta_pre is not None and beta_post is not None else np.nan
    deltas = deltas[np.isfinite(deltas)]
    if len(deltas) < 100:
        return {"p_value": None, "n_anchors": int(len(valid_anchors)), "null_mean": None}
    return {
        "p_value": float(np.mean(deltas >= observed_delta)),
        "n_anchors": int(len(valid_anchors)),
        "null_mean": float(np.mean(deltas)),
        "null_p95": float(np.percentile(deltas, 95)),
        "null_p99": float(np.percentile(deltas, 99)),
    }


def sign_test(values: pd.Series, threshold: float = 1.0, alternative: str = "greater") -> dict:
    clean = values.dropna()
    if clean.empty:
        return {"n": 0, "mean": None, "median": None, "frac_gt_threshold": None, "sign_test_p": None}
    n_up = int((clean > threshold).sum())
    pval = binomtest(n_up, n=int(len(clean)), p=0.5, alternative=alternative).pvalue
    return {
        "n": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "frac_gt_threshold": float(n_up / len(clean)),
        "sign_test_p": float(pval),
    }


def build_detail(events: pd.DataFrame, returns: pd.DataFrame, missing_tickers: list[str]) -> pd.DataFrame:
    rsq = returns.pow(2)
    tickers = [t for t in TICKERS if t not in missing_tickers and t in returns.columns]
    rng = np.random.default_rng(SEED)
    rows = []

    for _, event in events.iterrows():
        for ticker in tickers:
            for metric, spec in RV_METRICS.items():
                res = rv_window(rsq[ticker], event.event_date, spec["post_len"])
                if res is None:
                    continue
                boot = random_anchor_rv_pvalue(rsq[ticker], res["effect_value"], spec["post_len"], rng)
                rows.append(
                    {
                        "event_date": event.event_date.strftime("%Y-%m-%d"),
                        "event_id": event.event_id,
                        "region": event.region,
                        "announcement_type": event.announcement_type,
                        "ticker": ticker,
                        "channel": TICKER_META[ticker]["channel"],
                        "metric": metric,
                        "metric_family": "rv_ratio",
                        "effect_value": res["effect_value"],
                        "effect_units": "post_pre_rsq_ratio",
                        **{k: v for k, v in res.items() if k != "effect_value"},
                        **{f"boot_{k}": v for k, v in boot.items()},
                    }
                )
        for ticker in [t for t in BETA_TICKERS if t in tickers]:
            res = beta_window(returns, ticker, event.event_date)
            if res is None:
                continue
            boot = random_anchor_beta_pvalue(returns, ticker, res["effect_value"], rng)
            rows.append(
                {
                    "event_date": event.event_date.strftime("%Y-%m-%d"),
                    "event_id": event.event_id,
                    "region": event.region,
                    "announcement_type": event.announcement_type,
                    "ticker": ticker,
                    "channel": TICKER_META[ticker]["channel"],
                    "metric": "beta63_delta",
                    "metric_family": "beta_delta",
                    "effect_value": res["effect_value"],
                    "effect_units": "post63_beta_minus_pre85_beta_to_SPY",
                    **{k: v for k, v in res.items() if k != "effect_value"},
                    **{f"boot_{k}": v for k, v in boot.items()},
                }
            )

    if not rows:
        raise RuntimeError("No event-ticker-metric rows produced")
    detail = pd.DataFrame(rows)
    detail.to_csv(DETAIL_CSV, index=False)
    return detail


def summarize(detail: pd.DataFrame) -> dict:
    pvals = detail["boot_p_value"].dropna().to_numpy(dtype=float)
    bonf = 0.05 / max(len(pvals), 1)
    detail = detail.copy()
    detail["boot_sig_unadj_0p05"] = detail["boot_p_value"] < 0.05
    detail["boot_sig_bonferroni"] = detail["boot_p_value"] < bonf

    metric_summary = []
    for metric, sub in detail.groupby("metric"):
        threshold = 0.0 if metric == "beta63_delta" else 1.0
        summary = sign_test(sub["effect_value"], threshold=threshold)
        metric_summary.append(
            {
                "metric": metric,
                "metric_family": sub["metric_family"].iloc[0],
                "threshold_for_sign_test": threshold,
                **summary,
                "n_sig_unadj_0p05": int((sub["boot_p_value"] < 0.05).sum()),
                "n_sig_bonferroni": int((sub["boot_p_value"] < bonf).sum()),
            }
        )

    channel_summary = []
    for (metric, channel), sub in detail.groupby(["metric", "channel"]):
        threshold = 0.0 if metric == "beta63_delta" else 1.0
        channel_summary.append(
            {
                "metric": metric,
                "channel": channel,
                **sign_test(sub["effect_value"], threshold=threshold),
            }
        )

    announcement_summary = []
    for (metric, atype), sub in detail.groupby(["metric", "announcement_type"]):
        threshold = 0.0 if metric == "beta63_delta" else 1.0
        announcement_summary.append(
            {
                "metric": metric,
                "announcement_type": atype,
                **sign_test(sub["effect_value"], threshold=threshold),
            }
        )

    contrast_rows = []
    for (event_id, metric), sub in detail.groupby(["event_id", "metric"]):
        if metric == "beta63_delta":
            defense = sub[sub["channel"].eq("defense")]["effect_value"]
            industrial = sub[sub["channel"].isin(["industrials", "transport_industrials"])]["effect_value"]
            if defense.empty or industrial.empty:
                continue
            contrast_rows.append(
                {
                    "event_id": event_id,
                    "event_date": sub["event_date"].iloc[0],
                    "metric": metric,
                    "defense_mean": float(defense.mean()),
                    "industrial_mean": float(industrial.mean()),
                    "defense_minus_industrial": float(defense.mean() - industrial.mean()),
                }
            )
            continue
        defense = sub[sub["channel"].eq("defense")]["effect_value"]
        benchmark = sub[sub["channel"].eq("benchmark")]["effect_value"]
        rates = sub[sub["channel"].eq("rates")]["effect_value"]
        industrial = sub[sub["channel"].isin(["industrials", "transport_industrials"])]["effect_value"]
        if defense.empty or benchmark.empty:
            continue
        contrast_rows.append(
            {
                "event_id": event_id,
                "event_date": sub["event_date"].iloc[0],
                "metric": metric,
                "defense_mean": float(defense.mean()),
                "benchmark_mean": float(benchmark.mean()),
                "industrial_mean": float(industrial.mean()) if not industrial.empty else None,
                "rates_mean": float(rates.mean()) if not rates.empty else None,
                "defense_minus_benchmark": float(defense.mean() - benchmark.mean()),
                "defense_minus_industrial": float(defense.mean() - industrial.mean()) if not industrial.empty else None,
                "rates_minus_benchmark": float(rates.mean() - benchmark.mean()) if not rates.empty else None,
            }
        )

    contrast_summary = []
    contrast_df = pd.DataFrame(contrast_rows)
    if not contrast_df.empty:
        for metric, sub in contrast_df.groupby("metric"):
            for col in [
                "defense_minus_benchmark",
                "defense_minus_industrial",
                "rates_minus_benchmark",
            ]:
                if col not in sub.columns:
                    continue
                vals = sub[col].dropna()
                if vals.empty:
                    continue
                n_pos = int((vals > 0).sum())
                pval = binomtest(n_pos, n=int(len(vals)), p=0.5, alternative="greater").pvalue
                contrast_summary.append(
                    {
                        "metric": metric,
                        "contrast": col,
                        "n_events": int(len(vals)),
                        "mean_diff": float(vals.mean()),
                        "median_diff": float(vals.median()),
                        "frac_positive": float(n_pos / len(vals)),
                        "sign_test_p_one_sided": float(pval),
                    }
                )

    rv = detail[detail["metric_family"].eq("rv_ratio")]
    beta = detail[detail["metric_family"].eq("beta_delta")]
    rv_p = rv["boot_p_value"].dropna().to_numpy(dtype=float)
    beta_p = beta["boot_p_value"].dropna().to_numpy(dtype=float)
    rv_agg = sign_test(rv["effect_value"], threshold=1.0)
    rv_agg.update(
        {
            "n_tests": int(len(rv)),
            "n_pvalues": int(len(rv_p)),
            "n_sig_unadj_0p05": int((rv_p < 0.05).sum()),
            "n_sig_bonferroni": int((rv_p < bonf).sum()),
            "bonferroni_alpha_all_pvalues": float(bonf),
        }
    )
    beta_agg = sign_test(beta["effect_value"], threshold=0.0)
    beta_agg.update(
        {
            "n_tests": int(len(beta)),
            "n_pvalues": int(len(beta_p)),
            "n_sig_unadj_0p05": int((beta_p < 0.05).sum()),
            "n_sig_bonferroni": int((beta_p < bonf).sum()),
            "bonferroni_alpha_all_pvalues": float(bonf),
        }
    )

    significant = detail[detail["boot_sig_bonferroni"]].sort_values("boot_p_value")[
        [
            "event_date",
            "event_id",
            "announcement_type",
            "ticker",
            "channel",
            "metric",
            "effect_value",
            "effect_units",
            "boot_p_value",
            "boot_null_p99",
            "post_start",
            "post_end",
        ]
    ].to_dict(orient="records")

    if rv_agg["n_sig_bonferroni"] == 0 and beta_agg["n_sig_bonferroni"] == 0:
        verdict_code = "NULL_NO_ROBUST_DEFENSE_SPENDING_RV_OR_BETA_EFFECT"
    elif rv_agg["n_sig_bonferroni"] == 0 and beta_agg["n_sig_bonferroni"] > 0:
        verdict_code = "MIXED_BETA_ONLY_SIGNAL"
    elif rv_agg["n_sig_bonferroni"] > 0:
        verdict_code = "MIXED_SINGLE_EVENT_RV_SIGNALS"
    else:
        verdict_code = "MIXED_DESCRIPTIVE_ONLY"

    return {
        "multiple_testing": {
            "n_pvalues_all": int(len(pvals)),
            "bonferroni_alpha_all": float(bonf),
            "n_sig_unadj_0p05_all": int((pvals < 0.05).sum()),
            "n_sig_bonferroni_all": int((pvals < bonf).sum()),
        },
        "rv_aggregate": rv_agg,
        "beta_aggregate": beta_agg,
        "metric_summary": metric_summary,
        "channel_summary": channel_summary,
        "announcement_summary": announcement_summary,
        "event_contrasts": contrast_rows,
        "contrast_summary": contrast_summary,
        "significant_tests_after_bonferroni": significant,
        "verdict_code": verdict_code,
    }


def make_figures(detail: pd.DataFrame, summary: dict) -> None:
    rv5 = detail[detail["metric"].eq("rv5")]
    order = ["defense", "industrials", "transport_industrials", "rates", "dollar", "benchmark"]
    order = [c for c in order if c in set(rv5["channel"])]
    fig, ax = plt.subplots(figsize=(10, 5))
    data = [rv5[rv5["channel"].eq(ch)]["effect_value"].dropna().to_numpy() for ch in order]
    bp = ax.boxplot(data, tick_labels=order, showmeans=True, patch_artist=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#dcecdf")
    ax.axhline(1.0, color="#a22", linestyle="--", linewidth=1, label="null ratio=1")
    ax.set_ylabel("T+1..T+5 RV ratio vs T-30..T-6")
    ax.set_xlabel("ETF channel")
    ax.set_title("K1576 defence-spending announcements: 5-day RV ratio by channel")
    ax.tick_params(axis="x", rotation=25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "fig_a.png", dpi=140)
    plt.close(fig)

    beta = detail[detail["metric"].eq("beta63_delta")]
    fig, ax = plt.subplots(figsize=(8, 5))
    beta_order = [t for t in BETA_TICKERS if t in set(beta["ticker"])]
    data = [beta[beta["ticker"].eq(t)]["effect_value"].dropna().to_numpy() for t in beta_order]
    bp = ax.boxplot(data, tick_labels=beta_order, showmeans=True, patch_artist=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#e9dfef")
    ax.axhline(0.0, color="#333", linestyle="--", linewidth=1, label="null delta=0")
    ax.set_ylabel("Post63 beta to SPY minus pre85 beta")
    ax.set_xlabel("Ticker")
    ax.set_title("K1576 beta-to-SPY change after defence-spending announcements")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "fig_b.png", dpi=140)
    plt.close(fig)

    ch_df = pd.DataFrame(summary["channel_summary"])
    mean_df = ch_df.pivot(index="channel", columns="metric", values="mean")
    mean_df = mean_df.reindex([c for c in order if c in mean_df.index])
    metric_order = [m for m in ["t1_r2", "rv5", "rv22"] if m in mean_df.columns]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    mat = mean_df[metric_order].to_numpy(dtype=float)
    im = ax.imshow(mat, aspect="auto", cmap="RdBu_r", vmin=0.0, vmax=2.5)
    ax.set_xticks(np.arange(len(metric_order)), labels=metric_order)
    ax.set_yticks(np.arange(len(mean_df.index)), labels=mean_df.index)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=9)
    ax.set_title("Mean RV post/pre ratio by channel")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("mean ratio")
    fig.tight_layout()
    fig.savefig(HERE / "fig_c.png", dpi=140)
    plt.close(fig)


def run() -> None:
    print("=" * 72)
    print(f"{EXPERIMENT_ID} starting {datetime.now().isoformat(timespec='seconds')} seed={SEED}")
    print("=" * 72)
    events = load_events()
    start = (events.event_date.min() - pd.Timedelta(days=220)).strftime("%Y-%m-%d")
    end = (events.event_date.max() + pd.Timedelta(days=220)).strftime("%Y-%m-%d")
    closes, missing_tickers = download_prices(TICKERS, start, end)
    returns = compute_returns(closes)
    detail = build_detail(events, returns, missing_tickers)
    summary = summarize(detail)
    make_figures(detail, summary)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Defence-spending boom announcements and ETF volatility / beta response",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "seed": SEED,
        "data": {
            "n_events": int(len(events)),
            "events_file": str(EVENTS_CSV.relative_to(HERE)),
            "events": events.assign(event_date=events["event_date"].dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
            "tickers_requested": TICKERS,
            "tickers_used": [t for t in TICKERS if t not in missing_tickers and t in closes.columns],
            "tickers_missing_or_sparse": missing_tickers,
            "ticker_meta": TICKER_META,
            "sample_start": start,
            "sample_end": end,
            "price_source": "yfinance adjusted close, auto_adjust=True",
            "price_cache": str(PRICES_CSV.relative_to(HERE)),
        },
        "method": {
            "lookahead_protection": (
                "T=0 maps to first trading day >= announcement date; post metrics start "
                "strictly at T+1. Pre RV window ends at T-6. Beta pre window is T-90..T-6 "
                "and beta post window is T+1..T+63."
            ),
            "rv_metrics": RV_METRICS,
            "beta_metric": {
                "metric": "beta63_delta",
                "definition": "OLS beta to SPY over T+1..T+63 minus OLS beta over T-90..T-6",
                "tickers": BETA_TICKERS,
            },
            "bootstrap": {
                "method": "random-anchor one-sided right-tail p-value on ticker full sample",
                "B_reps": B_REPS,
                "seed": SEED,
            },
        },
        "literature_and_context": [
            {
                "source": "Ramey (2011), Identifying Government Spending Shocks: It's All in the Timing",
                "url": "https://www.nber.org/papers/w15464",
                "use": "Motivates treating defence-news timing as the shock rather than realized spending alone.",
            },
            {
                "source": "Caldara and Iacoviello geopolitical risk research",
                "url": "https://www.matteoiacoviello.com/gpr.htm",
                "use": "Motivates separating budget-news events from generic geopolitical-risk shocks.",
            },
            {
                "source": "SIPRI Trends in World Military Expenditure 2024",
                "url": "https://www.sipri.org/sites/default/files/2025-04/2504_fs_milex_2024.pdf",
                "use": "Context for the post-2022 global military-spending surge.",
            },
            {
                "source": "NATO defence expenditures and 5% commitment",
                "url": "https://www.nato.int/en/what-we-do/introduction-to-nato/defence-expenditures-and-natos-5-commitment",
                "use": "Official NATO context for 2% and 5% spending-path commitments.",
            },
        ],
        "outputs": {
            "detail_csv": str(DETAIL_CSV.relative_to(HERE)),
            "figures": ["fig_a.png", "fig_b.png", "fig_c.png"],
        },
        **summary,
    }
    rv = results["rv_aggregate"]
    beta = results["beta_aggregate"]
    results["honest_summary"] = (
        f"{results['verdict_code']}: RV family {rv['n_tests']} tests, mean={rv['mean']:.3f}, "
        f"median={rv['median']:.3f}, frac>1={rv['frac_gt_threshold']:.3f}, sign p={rv['sign_test_p']:.3f}, "
        f"Bonferroni RV sig={rv['n_sig_bonferroni']}/{rv['n_pvalues']}; beta family {beta['n_tests']} tests, "
        f"mean delta={beta['mean']:.3f}, frac>0={beta['frac_gt_threshold']:.3f}, "
        f"Bonferroni beta sig={beta['n_sig_bonferroni']}/{beta['n_pvalues']}."
    )
    with RESULTS_JSON.open("w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"[results] wrote {DETAIL_CSV}")
    print(f"[results] wrote {RESULTS_JSON}")
    print("[verdict]", results["honest_summary"])


if __name__ == "__main__":
    run()
