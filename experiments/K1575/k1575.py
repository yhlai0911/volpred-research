"""K1575 - critical-minerals export-restriction shocks and ETF realized volatility.

Question: Do public critical-minerals export-restriction announcements transmit into
next-day / next-month realized-volatility spikes in listed ETF proxies for clean-tech,
defense, semiconductors, and mineral producers?

Design:
- Events are manually curated in events.csv from official or policy-tracker sources.
- T=0 is the first trading day >= the public announcement date.
- Pre baseline is T-30..T-6. Post windows start strictly at T+1.
- Metrics: T+1 r^2 ratio, T+1..T+5 RV ratio, T+1..T+22 RV ratio, and T+1..T+5
  absolute-return jump ratio.
- Significance: random-anchor bootstrap on each ticker's full daily series, seed=42.

This is an event-study diagnostic, not a trading backtest. Daily close data cannot see
intraday reaction timing. Small N and multiple tests imply low power; null results are
reported as null.
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

EXPERIMENT_ID = "K1575"
SEED = 42
B_REPS = 1000

PRE_START_REL = -30
PRE_END_REL = -6
POST_START_REL = 1

HERE = Path(__file__).resolve().parent
EVENTS_CSV = HERE / "events.csv"
RESULTS_JSON = HERE / "k1575_results.json"
DETAIL_CSV = HERE / "event_ticker_metric_results.csv"
PRICES_CSV = HERE / "close_yfinance.csv"

TICKER_META = {
    "REMX": {"channel": "direct_minerals", "description": "rare earth / strategic metals ETF"},
    "LIT": {"channel": "battery_clean", "description": "lithium and battery value chain ETF"},
    "COPX": {"channel": "industrial_metals", "description": "copper miners ETF"},
    "URA": {"channel": "uranium_nuclear", "description": "uranium and nuclear ETF"},
    "PICK": {"channel": "industrial_metals", "description": "global metals and mining ETF"},
    "ICLN": {"channel": "clean_energy", "description": "global clean-energy ETF"},
    "TAN": {"channel": "clean_energy", "description": "solar ETF"},
    "SMH": {"channel": "semiconductor", "description": "semiconductor ETF"},
    "SOXX": {"channel": "semiconductor", "description": "semiconductor ETF"},
    "ITA": {"channel": "defense", "description": "aerospace and defense ETF"},
    "XLI": {"channel": "industrials", "description": "US industrial sector ETF"},
    "SPY": {"channel": "benchmark", "description": "S&P 500 ETF control"},
    "QQQ": {"channel": "benchmark", "description": "Nasdaq 100 ETF control"},
}

TICKERS = sorted(TICKER_META)

METRICS = {
    "t1_r2": {"post_len": 1, "series": "rsq", "post_agg": "mean"},
    "rv5": {"post_len": 5, "series": "rsq", "post_agg": "mean"},
    "rv22": {"post_len": 22, "series": "rsq", "post_agg": "mean"},
    "jump5_abs": {"post_len": 5, "series": "absret", "post_agg": "max"},
}

RV_CONFIRMATORY_METRICS = {"t1_r2", "rv5", "rv22"}


def load_events() -> pd.DataFrame:
    events = pd.read_csv(EVENTS_CSV, parse_dates=["event_date"])
    expected = {
        "event_date",
        "event_id",
        "country",
        "material_group",
        "shock_type",
        "source_url",
        "source_note",
    }
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
        progress=False,
        auto_adjust=True,
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
                print(f"[data] WARN {ticker} missing entirely")
                continue
            if len(close) < 80:
                missing.append(ticker)
                print(f"[data] WARN {ticker} sparse ({len(close)} obs)")
                continue
            closes[ticker] = close
    else:
        ticker = tickers[0]
        close = raw["Close"].dropna()
        if len(close) < 80:
            missing.append(ticker)
        else:
            closes[ticker] = close
    if not closes:
        raise RuntimeError("No usable yfinance closes returned")
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
    target = pos + k
    if target < 0 or target >= len(idx):
        return None
    return idx[target]


def window_values(series: pd.Series, event_date: pd.Timestamp, post_len: int) -> dict | None:
    clean = series.dropna()
    idx = clean.index
    pre_start = trading_day_offset(idx, event_date, PRE_START_REL)
    pre_end = trading_day_offset(idx, event_date, PRE_END_REL)
    post_start = trading_day_offset(idx, event_date, POST_START_REL)
    post_end = trading_day_offset(idx, event_date, POST_START_REL + post_len - 1)
    if None in (pre_start, pre_end, post_start, post_end):
        return None
    pre = clean.loc[pre_start:pre_end].dropna()
    post = clean.loc[post_start:post_end].dropna()
    if len(pre) < 15 or len(post) < max(1, int(0.6 * post_len)):
        return None
    anchor = trading_day_offset(idx, event_date, 0)
    return {
        "anchor_date": anchor.strftime("%Y-%m-%d") if anchor is not None else None,
        "pre": pre,
        "post": post,
        "pre_start": pre_start.strftime("%Y-%m-%d"),
        "pre_end": pre_end.strftime("%Y-%m-%d"),
        "post_start": post_start.strftime("%Y-%m-%d"),
        "post_end": post_end.strftime("%Y-%m-%d"),
        "n_pre": int(len(pre)),
        "n_post": int(len(post)),
    }


def ratio_from_values(pre: pd.Series | np.ndarray, post: pd.Series | np.ndarray, post_agg: str) -> float | None:
    pre_arr = np.asarray(pre, dtype=float)
    post_arr = np.asarray(post, dtype=float)
    pre_mean = float(np.nanmean(pre_arr))
    if not np.isfinite(pre_mean) or pre_mean <= 0:
        return None
    if post_agg == "mean":
        post_value = float(np.nanmean(post_arr))
    elif post_agg == "max":
        post_value = float(np.nanmax(post_arr))
    else:
        raise ValueError(f"unknown post_agg={post_agg}")
    if not np.isfinite(post_value):
        return None
    return float(post_value / pre_mean)


def random_anchor_pvalue(
    series: pd.Series,
    observed_ratio: float,
    post_len: int,
    post_agg: str,
    rng: np.random.Generator,
    b_reps: int = B_REPS,
) -> dict:
    x = series.dropna().to_numpy(dtype=float)
    n = len(x)
    needed_left = abs(PRE_START_REL)
    needed_right = POST_START_REL + post_len - 1
    valid_anchors = np.arange(needed_left, n - needed_right)
    if len(valid_anchors) < 50:
        return {"p_value": None, "n_anchors": int(len(valid_anchors)), "null_mean": None}
    null_ratios = np.empty(b_reps, dtype=np.float64)
    for b in range(b_reps):
        a = int(rng.choice(valid_anchors))
        pre = x[a + PRE_START_REL : a + PRE_END_REL + 1]
        post = x[a + POST_START_REL : a + POST_START_REL + post_len]
        ratio = ratio_from_values(pre, post, post_agg)
        null_ratios[b] = ratio if ratio is not None else np.nan
    null_ratios = null_ratios[np.isfinite(null_ratios)]
    if len(null_ratios) < 50:
        return {"p_value": None, "n_anchors": int(len(valid_anchors)), "null_mean": None}
    return {
        "p_value": float(np.mean(null_ratios >= observed_ratio)),
        "n_anchors": int(len(valid_anchors)),
        "null_mean": float(np.mean(null_ratios)),
        "null_p95": float(np.percentile(null_ratios, 95)),
        "null_p99": float(np.percentile(null_ratios, 99)),
    }


def build_detail_rows(events: pd.DataFrame, returns: pd.DataFrame, missing_tickers: list[str]) -> pd.DataFrame:
    rsq = returns.pow(2)
    absret = returns.abs()
    source_map = {"rsq": rsq, "absret": absret}
    usable_tickers = [t for t in TICKERS if t not in missing_tickers and t in returns.columns]
    rng = np.random.default_rng(SEED)
    rows = []

    for _, event in events.iterrows():
        for ticker in usable_tickers:
            for metric, spec in METRICS.items():
                series = source_map[spec["series"]][ticker]
                values = window_values(series, event.event_date, spec["post_len"])
                if values is None:
                    continue
                ratio = ratio_from_values(values["pre"], values["post"], spec["post_agg"])
                if ratio is None:
                    continue
                boot = random_anchor_pvalue(
                    series,
                    ratio,
                    spec["post_len"],
                    spec["post_agg"],
                    rng,
                )
                rows.append(
                    {
                        "event_date": event.event_date.strftime("%Y-%m-%d"),
                        "event_id": event.event_id,
                        "country": event.country,
                        "material_group": event.material_group,
                        "shock_type": event.shock_type,
                        "ticker": ticker,
                        "channel": TICKER_META[ticker]["channel"],
                        "metric": metric,
                        "ratio": ratio,
                        "pre_mean": float(values["pre"].mean()),
                        "post_mean": float(values["post"].mean()),
                        "anchor_date": values["anchor_date"],
                        "pre_start": values["pre_start"],
                        "pre_end": values["pre_end"],
                        "post_start": values["post_start"],
                        "post_end": values["post_end"],
                        "n_pre": values["n_pre"],
                        "n_post": values["n_post"],
                        **{f"boot_{k}": v for k, v in boot.items()},
                    }
                )
    if not rows:
        raise RuntimeError("no event-ticker-metric rows produced")
    df = pd.DataFrame(rows)
    df.to_csv(DETAIL_CSV, index=False)
    return df


def sign_test_summary(values: pd.Series, alternative: str = "greater") -> dict:
    clean = values.dropna()
    if clean.empty:
        return {
            "n": 0,
            "mean_ratio": None,
            "median_ratio": None,
            "frac_ratio_gt1": None,
            "sign_test_p_one_sided": None,
        }
    n_up = int((clean > 1.0).sum())
    pval = binomtest(n_up, n=int(len(clean)), p=0.5, alternative=alternative).pvalue
    return {
        "n": int(len(clean)),
        "mean_ratio": float(clean.mean()),
        "median_ratio": float(clean.median()),
        "frac_ratio_gt1": float(n_up / len(clean)),
        "sign_test_p_one_sided": float(pval),
    }


def metric_ratio_summary(metric: str, values: pd.Series) -> dict:
    if metric in RV_CONFIRMATORY_METRICS:
        out = sign_test_summary(values)
        out["ratio_gt1_sign_test_interpretation"] = "valid: post mean r^2 ratio > 1"
        return out
    clean = values.dropna()
    if clean.empty:
        return {
            "n": 0,
            "mean_ratio": None,
            "median_ratio": None,
            "frac_ratio_gt1": None,
            "sign_test_p_one_sided": None,
            "ratio_gt1_sign_test_interpretation": (
                "not used: jump max/mean ratio is not tested against ratio>1"
            ),
        }
    return {
        "n": int(len(clean)),
        "mean_ratio": float(clean.mean()),
        "median_ratio": float(clean.median()),
        "frac_ratio_gt1": float((clean > 1).mean()),
        "sign_test_p_one_sided": None,
        "ratio_gt1_sign_test_interpretation": (
            "not used: max(abs return over 5 days) divided by pre mean abs return "
            "is mechanically expected to exceed 1 under the null; use bootstrap p-values."
        ),
    }


def summarize(df: pd.DataFrame) -> dict:
    pvals = df["boot_p_value"].dropna().to_numpy(dtype=float)
    bonf_alpha = 0.05 / max(len(pvals), 1)
    df = df.copy()
    df["boot_sig_unadj_0p05"] = df["boot_p_value"] < 0.05
    df["boot_sig_bonferroni"] = df["boot_p_value"] < bonf_alpha

    metric_summary = []
    for metric, sub in df.groupby("metric"):
        item = {"metric": metric, **metric_ratio_summary(metric, sub["ratio"])}
        item["n_sig_unadj_0p05"] = int((sub["boot_p_value"] < 0.05).sum())
        item["n_sig_bonferroni"] = int((sub["boot_p_value"] < bonf_alpha).sum())
        metric_summary.append(item)

    channel_summary = []
    for (metric, channel), sub in df.groupby(["metric", "channel"]):
        channel_summary.append({"metric": metric, "channel": channel, **metric_ratio_summary(metric, sub["ratio"])})

    material_summary = []
    for (metric, material), sub in df.groupby(["metric", "material_group"]):
        material_summary.append(
            {"metric": metric, "material_group": material, **metric_ratio_summary(metric, sub["ratio"])}
        )

    ticker_summary = []
    for (metric, ticker), sub in df.groupby(["metric", "ticker"]):
        ticker_summary.append(
            {
                "metric": metric,
                "ticker": ticker,
                "channel": TICKER_META[ticker]["channel"],
                **sign_test_summary(sub["ratio"]),
            }
        )

    spillover_rows = []
    direct_channels = {"direct_minerals", "battery_clean", "industrial_metals", "uranium_nuclear"}
    for (event_id, metric), sub in df.groupby(["event_id", "metric"]):
        direct = sub[sub["channel"].isin(direct_channels)]["ratio"]
        clean = sub[sub["channel"].eq("clean_energy")]["ratio"]
        semi = sub[sub["channel"].eq("semiconductor")]["ratio"]
        defense = sub[sub["channel"].eq("defense")]["ratio"]
        bench = sub[sub["channel"].eq("benchmark")]["ratio"]
        if direct.empty or bench.empty:
            continue
        spillover_rows.append(
            {
                "event_id": event_id,
                "event_date": sub["event_date"].iloc[0],
                "material_group": sub["material_group"].iloc[0],
                "metric": metric,
                "direct_mean_ratio": float(direct.mean()),
                "clean_energy_mean_ratio": float(clean.mean()) if not clean.empty else None,
                "semiconductor_mean_ratio": float(semi.mean()) if not semi.empty else None,
                "defense_mean_ratio": float(defense.mean()) if not defense.empty else None,
                "benchmark_mean_ratio": float(bench.mean()),
                "direct_minus_benchmark": float(direct.mean() - bench.mean()),
                "semiconductor_minus_benchmark": float(semi.mean() - bench.mean()) if not semi.empty else None,
                "defense_minus_benchmark": float(defense.mean() - bench.mean()) if not defense.empty else None,
            }
        )

    spillover_df = pd.DataFrame(spillover_rows)
    spillover_summary = []
    if not spillover_df.empty:
        for metric, sub in spillover_df.groupby("metric"):
            for col in [
                "direct_minus_benchmark",
                "semiconductor_minus_benchmark",
                "defense_minus_benchmark",
            ]:
                vals = sub[col].dropna()
                if vals.empty:
                    continue
                n_pos = int((vals > 0).sum())
                pval = binomtest(n_pos, n=int(len(vals)), p=0.5, alternative="greater").pvalue
                spillover_summary.append(
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

    aggregate_all = {
        "n": int(len(df)),
        "mean_ratio": float(df["ratio"].mean()),
        "median_ratio": float(df["ratio"].median()),
        "note": "descriptive only; mixes RV mean-ratio metrics and jump max/mean ratio",
    }
    rv_family = df[df["metric"].isin(RV_CONFIRMATORY_METRICS)]
    jump_family = df[df["metric"].eq("jump5_abs")]
    confirmatory_rv_aggregate = sign_test_summary(rv_family["ratio"])
    rv_pvals = rv_family["boot_p_value"].dropna().to_numpy(dtype=float)
    jump_pvals = jump_family["boot_p_value"].dropna().to_numpy(dtype=float)
    confirmatory_rv_aggregate.update(
        {
            "n_event_ticker_metric_tests": int(len(rv_family)),
            "n_pvalues": int(len(rv_pvals)),
            "bonferroni_alpha": float(bonf_alpha),
            "n_sig_unadj_0p05": int((rv_pvals < 0.05).sum()),
            "n_sig_bonferroni": int((rv_pvals < bonf_alpha).sum()),
            "metric_family": sorted(RV_CONFIRMATORY_METRICS),
        }
    )
    jump_bootstrap_summary = {
        "n_event_ticker_metric_tests": int(len(jump_family)),
        "n_pvalues": int(len(jump_pvals)),
        "bonferroni_alpha": float(bonf_alpha),
        "n_sig_unadj_0p05": int((jump_pvals < 0.05).sum()),
        "n_sig_bonferroni": int((jump_pvals < bonf_alpha).sum()),
        "note": (
            "jump5_abs uses random-anchor bootstrap only; ratio>1 sign tests are not "
            "interpretable because a five-day max is expected to exceed a one-period mean."
        ),
    }
    multiple_testing_all = {
        "n_pvalues_all_metrics": int(len(pvals)),
        "bonferroni_alpha_all_metrics": float(bonf_alpha),
        "n_sig_unadj_0p05_all_metrics": int((pvals < 0.05).sum()),
        "n_sig_bonferroni_all_metrics": int((pvals < bonf_alpha).sum()),
    }

    sig_jump = df[df["boot_sig_bonferroni"] & df["metric"].eq("jump5_abs")]
    significant_tests = sig_jump.sort_values("boot_p_value")[
        [
            "event_date",
            "event_id",
            "material_group",
            "ticker",
            "channel",
            "metric",
            "ratio",
            "boot_p_value",
            "boot_null_p99",
            "post_start",
            "post_end",
        ]
    ].to_dict(orient="records")

    market_confound_notes = []
    if (df["event_id"] == "china_medium_heavy_rare_earths_20250404").any():
        market_confound_notes.append(
            "2025-04-04 rare-earth event is confounded by the same week's broad tariff-driven "
            "market volatility. In this event, SPY/QQQ rv5 and jump5_abs ratios are also high, "
            "and direct mineral mean rv5/jump ratios do not exceed benchmark mean ratios."
        )

    if confirmatory_rv_aggregate["n_sig_bonferroni"] == 0 and jump_bootstrap_summary["n_sig_bonferroni"] == 0:
        verdict_code = "NULL_NO_SYSTEMATIC_RV_SPIKE"
    elif confirmatory_rv_aggregate["n_sig_bonferroni"] == 0 and jump_bootstrap_summary["n_sig_bonferroni"] > 0:
        verdict_code = "MIXED_JUMP_ONLY_MARKET_CONFOUNDED"
    elif confirmatory_rv_aggregate["n_sig_bonferroni"] > 0:
        verdict_code = "MIXED_RV_SINGLE_EVENT_SIGNALS"
    else:
        verdict_code = "MIXED_DESCRIPTIVE_ONLY"

    return {
        "aggregate_all_metrics_descriptive": aggregate_all,
        "confirmatory_rv_aggregate": confirmatory_rv_aggregate,
        "jump_bootstrap_summary": jump_bootstrap_summary,
        "multiple_testing_all_metrics": multiple_testing_all,
        "significant_tests_after_bonferroni": significant_tests,
        "market_confound_notes": market_confound_notes,
        "metric_summary": metric_summary,
        "channel_summary": channel_summary,
        "material_summary": material_summary,
        "ticker_summary": ticker_summary,
        "spillover_event_contrasts": spillover_rows,
        "spillover_summary": spillover_summary,
        "verdict_code": verdict_code,
    }


def make_figures(df: pd.DataFrame, summary: dict) -> None:
    rv5 = df[df["metric"].eq("rv5")].copy()
    order = [
        "direct_minerals",
        "battery_clean",
        "industrial_metals",
        "uranium_nuclear",
        "clean_energy",
        "semiconductor",
        "defense",
        "industrials",
        "benchmark",
    ]
    order = [c for c in order if c in set(rv5["channel"])]
    fig, ax = plt.subplots(figsize=(11, 5))
    data = [rv5[rv5["channel"].eq(ch)]["ratio"].dropna().to_numpy() for ch in order]
    bp = ax.boxplot(data, tick_labels=order, showmeans=True, patch_artist=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#d8eef5")
    ax.axhline(1.0, color="#a22", linestyle="--", linewidth=1, label="null ratio=1")
    ax.set_ylabel("T+1..T+5 RV ratio vs T-30..T-6")
    ax.set_xlabel("ETF channel")
    ax.set_title("K1575 critical-minerals export restrictions: 5-day RV ratios by channel")
    ax.tick_params(axis="x", rotation=30)
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "fig_a.png", dpi=140)
    plt.close(fig)

    channel_df = pd.DataFrame(summary["channel_summary"])
    pivot = channel_df.pivot(index="channel", columns="metric", values="mean_ratio")
    pivot = pivot.reindex([c for c in order if c in pivot.index])
    metric_order = [m for m in ["t1_r2", "rv5", "rv22", "jump5_abs"] if m in pivot.columns]
    pivot = pivot[metric_order]
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(pivot.to_numpy(dtype=float), aspect="auto", cmap="RdBu_r", vmin=0.0, vmax=2.5)
    ax.set_xticks(np.arange(len(metric_order)), labels=metric_order)
    ax.set_yticks(np.arange(len(pivot.index)), labels=pivot.index)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            val = pivot.iloc[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=9)
    ax.set_title("Mean post/pre ratio by channel and metric")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("mean ratio")
    fig.tight_layout()
    fig.savefig(HERE / "fig_b.png", dpi=140)
    plt.close(fig)


def run() -> None:
    print("=" * 72)
    print(f"{EXPERIMENT_ID} starting {datetime.now().isoformat(timespec='seconds')} seed={SEED}")
    print("=" * 72)
    events = load_events()
    start = (events.event_date.min() - pd.Timedelta(days=180)).strftime("%Y-%m-%d")
    end = (events.event_date.max() + pd.Timedelta(days=180)).strftime("%Y-%m-%d")
    closes, missing_tickers = download_prices(TICKERS, start, end)
    returns = compute_returns(closes)
    detail = build_detail_rows(events, returns, missing_tickers)
    summary = summarize(detail)
    make_figures(detail, summary)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Critical-minerals export-restriction shocks and ETF realized-volatility transmission",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "seed": SEED,
        "data": {
            "events_file": str(EVENTS_CSV.relative_to(HERE)),
            "n_events": int(len(events)),
            "events": events.assign(event_date=events["event_date"].dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
            "tickers_requested": TICKERS,
            "ticker_meta": TICKER_META,
            "tickers_missing_or_sparse": missing_tickers,
            "tickers_used": [t for t in TICKERS if t not in missing_tickers and t in closes.columns],
            "n_tickers_used": int(len([t for t in TICKERS if t not in missing_tickers and t in closes.columns])),
            "sample_start": start,
            "sample_end": end,
            "price_source": "yfinance adjusted close, auto_adjust=True",
            "price_cache": str(PRICES_CSV.relative_to(HERE)),
        },
        "method": {
            "pre_window": [PRE_START_REL, PRE_END_REL],
            "post_start": POST_START_REL,
            "metrics": METRICS,
            "bootstrap": {
                "method": "random-anchor one-sided right-tail p-value on each ticker full sample",
                "B_reps": B_REPS,
                "seed": SEED,
            },
            "lookahead_protection": (
                "T=0 maps to first trading day >= announcement date. All post-event metrics "
                "start at T+1. Pre baseline ends at T-6, leaving T-5..T as a discarded gap."
            ),
        },
        "literature_and_context": [
            {
                "source": "OECD Inventory of Export Restrictions on Critical Raw Materials 2026",
                "url": "https://www.oecd.org/en/publications/oecd-inventory-of-export-restrictions-on-critical-raw-materials-2026_d5ca8f62-en/full-report.html",
                "use": "Motivates export restrictions as a growing CRM supply-chain risk.",
            },
            {
                "source": "IEA Global Critical Minerals Outlook 2025",
                "url": "https://www.iea.org/reports/global-critical-minerals-outlook-2025",
                "use": "Motivates critical minerals as energy, technology, and broader-economy supply-chain risks.",
            },
            {
                "source": "IEA Critical Minerals Policy Tracker",
                "url": "https://www.iea.org/policies",
                "use": "Cross-checks graphite and DRC cobalt policy-event dates.",
            },
        ],
        "outputs": {
            "detail_csv": str(DETAIL_CSV.relative_to(HERE)),
            "figures": ["fig_a.png", "fig_b.png"],
        },
        **summary,
    }

    verdict = results["verdict_code"]
    agg = results["confirmatory_rv_aggregate"]
    jump = results["jump_bootstrap_summary"]
    results["honest_summary"] = (
        f"{verdict}: confirmatory RV family has {agg['n_event_ticker_metric_tests']} "
        f"event-ticker-metric tests, mean ratio={agg['mean_ratio']:.3f}, "
        f"fraction ratio>1={agg['frac_ratio_gt1']:.3f}, sign-test p={agg['sign_test_p_one_sided']:.3f}, "
        f"Bonferroni RV significant={agg['n_sig_bonferroni']}/{agg['n_pvalues']}; "
        f"jump5_abs bootstrap significant={jump['n_sig_bonferroni']}/{jump['n_pvalues']}."
    )

    with RESULTS_JSON.open("w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"[results] wrote {DETAIL_CSV}")
    print(f"[results] wrote {RESULTS_JSON}")
    print("[verdict]", results["honest_summary"])


if __name__ == "__main__":
    run()
