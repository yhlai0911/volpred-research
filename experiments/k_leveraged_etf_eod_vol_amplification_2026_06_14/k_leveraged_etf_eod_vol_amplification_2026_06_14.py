"""
K_leveraged_etf_eod_vol_amplification_2026_06_14
================================================

研究問題：以 SPY / QQQ 為標的 proxy，在槓桿 ETF（TQQQ/SPXL/UPRO 等）需做
機械再平衡的高 |daily return| 日子，標的尾盤 (last 30 min) 已實現波動是否
顯著高於早盤同樣 30 min？

方法：
1. 拉 SPY / QQQ 5-min intraday (yfinance, period='60d')
2. 計算每日 RTH 內各 30-min bucket realized vol (sqrt sum of squared 5m log returns)
3. 計算每日 |close-to-close return|，以中位數分組 (high vs low |R|)；另跑 top vs bottom quartile
4. 配對 t / Wilcoxon / Mann-Whitney 比較 last 30 min vs first 30 min vol，by group
5. Bootstrap 95% CI (seed=20260614, B=1000)
6. 圖表：bucket vol by time-of-day x group bar chart

Caveat:
- 不直接觀察 issuer rebalancing flow，僅以標的 |daily return| 作 proxy
- yfinance 5-min period 最多 60 天 → 樣本 ~40-50 trading days
- 不可作 causal claim (correlation only)
- 與 K30 (Leveraged ETF VT, Sharpe invariance) 不同：K30 看 leveraged ETF 自身 VT
  策略；本實驗看標的 underlying intraday vol pattern

Seed: 20260614 (np.random.seed)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

SEED = 20260614
np.random.seed(SEED)

EXP_DIR = Path(__file__).resolve().parent
TICKERS = ["SPY", "QQQ"]
INTERVAL_PRIMARY = "5m"
INTERVAL_FALLBACK_1 = "15m"
INTERVAL_FALLBACK_2 = "1h"
PERIOD = "60d"

# US RTH 09:30 - 16:00 ET. yfinance returns timezone-aware index.
RTH_START = "09:30"
RTH_END = "16:00"

BOOTSTRAP_B = 1000


def fetch_intraday(ticker: str) -> tuple[pd.DataFrame, str]:
    """Try 5m → 15m → 1h. Return (df, interval_used)."""
    for interval in (INTERVAL_PRIMARY, INTERVAL_FALLBACK_1, INTERVAL_FALLBACK_2):
        try:
            df = yf.download(
                ticker,
                period=PERIOD,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            if df is None or df.empty:
                continue
            # Flatten multi-index columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            print(f"[fetch] {ticker} {interval} OK rows={len(df)}", flush=True)
            return df, interval
        except Exception as exc:  # noqa: BLE001
            print(f"[fetch] {ticker} {interval} FAIL: {exc}", flush=True)
            time.sleep(1)
    raise RuntimeError(f"All intervals failed for {ticker}")


def compute_buckets(
    df: pd.DataFrame, interval: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Return (daily_bucket_vol, daily_returns)
    daily_bucket_vol columns: bucket label (HH:MM start), index = date
    daily_returns: index = date, columns = ['close', 'log_ret', 'abs_ret']
    """
    df = df.copy()
    # Ensure tz-aware → convert to ET (US/Eastern)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")
    # Filter RTH: use [09:30, 16:00) — drop 16:00 boundary bar (5m bars are labeled
    # by start time, expected last bar is 15:55).
    df = df.between_time(RTH_START, "15:59")
    # Drop rows with NaN close
    df = df[df["Close"].notna()].copy()

    df["date"] = df.index.date
    # 5m log return WITHIN each trading day (reset across day boundary to avoid
    # overnight gap contaminating the first 09:30 bucket).
    df["ret"] = df.groupby("date")["Close"].transform(lambda s: np.log(s).diff())
    df["minute_of_day"] = df.index.hour * 60 + df.index.minute

    # Bucket size in minutes depending on interval
    if interval == "5m":
        bucket_size = 30
    elif interval == "15m":
        bucket_size = 30
    else:  # 1h fallback - use 60-min buckets
        bucket_size = 60

    # Assign bucket: 09:30 = minute 570, 16:00 = 960
    start_min = 9 * 60 + 30
    df["bucket_idx"] = ((df["minute_of_day"] - start_min) // bucket_size).astype(int)
    # Bucket label = start time
    df["bucket_start_min"] = start_min + df["bucket_idx"] * bucket_size
    df["bucket_label"] = df["bucket_start_min"].apply(
        lambda m: f"{m // 60:02d}:{m % 60:02d}"
    )

    # Realized vol per (date, bucket): sqrt(sum r^2)
    grouped = (
        df.dropna(subset=["ret"])
        .groupby(["date", "bucket_label"])["ret"]
        .apply(lambda s: float(np.sqrt(np.sum(s.values**2))))
    )
    bucket_vol = grouped.unstack("bucket_label")

    # Daily close-to-close return: take last RTH close per day
    daily_close = df.groupby("date")["Close"].last()
    daily_log_ret = np.log(daily_close).diff()
    daily_df = pd.DataFrame(
        {
            "close": daily_close,
            "log_ret": daily_log_ret,
            "abs_ret": daily_log_ret.abs(),
        }
    )

    # Align indices
    common_dates = bucket_vol.index.intersection(daily_df.index)
    bucket_vol = bucket_vol.loc[common_dates]
    daily_df = daily_df.loc[common_dates]

    return bucket_vol, daily_df


def paired_tests(open_vol: np.ndarray, close_vol: np.ndarray) -> dict:
    """Paired t, Wilcoxon, Mann-Whitney (independent for sanity)."""
    diff = close_vol - open_vol
    out: dict = {}
    out["n"] = int(len(diff))
    out["mean_open"] = float(np.mean(open_vol))
    out["mean_close"] = float(np.mean(close_vol))
    out["mean_diff"] = float(np.mean(diff))
    out["median_open"] = float(np.median(open_vol))
    out["median_close"] = float(np.median(close_vol))
    if len(diff) >= 3:
        t_res = stats.ttest_rel(close_vol, open_vol)
        out["paired_t_stat"] = float(t_res.statistic)
        out["paired_t_pvalue"] = float(t_res.pvalue)
        try:
            w_res = stats.wilcoxon(close_vol, open_vol, zero_method="wilcox")
            out["wilcoxon_stat"] = float(w_res.statistic)
            out["wilcoxon_pvalue"] = float(w_res.pvalue)
        except ValueError as e:
            out["wilcoxon_error"] = str(e)
        mw = stats.mannwhitneyu(close_vol, open_vol, alternative="two-sided")
        out["mannwhitney_stat"] = float(mw.statistic)
        out["mannwhitney_pvalue"] = float(mw.pvalue)
    return out


def bootstrap_ci_mean_diff(
    open_vol: np.ndarray,
    close_vol: np.ndarray,
    B: int = BOOTSTRAP_B,
    seed: int = SEED,
    group_tag: str = "",
) -> dict:
    # Per-group derived seed so same-sized groups don't reuse the exact same
    # bootstrap index pattern (Codex review note).
    derived_seed = (seed + (abs(hash(group_tag)) % 10_000_000)) % (2**32 - 1)
    rng = np.random.default_rng(derived_seed)
    diff = close_vol - open_vol
    n = len(diff)
    if n < 2:
        return {"ci_low": None, "ci_high": None, "B": B, "n": n}
    samples = np.empty(B)
    for i in range(B):
        idx = rng.integers(0, n, size=n)
        samples[i] = float(np.mean(diff[idx]))
    return {
        "ci_low": float(np.percentile(samples, 2.5)),
        "ci_high": float(np.percentile(samples, 97.5)),
        "mean": float(np.mean(diff)),
        "B": B,
        "n": n,
    }


def analyze_ticker(ticker: str) -> dict:
    raw_df, interval = fetch_intraday(ticker)
    bucket_vol, daily_df = compute_buckets(raw_df, interval)

    # First bucket label = 09:30 ; Last bucket: identify
    bucket_cols = sorted(bucket_vol.columns)
    first_bucket = bucket_cols[0]
    # Last bucket: use the one starting at 15:30 if available (covers 15:30-16:00),
    # else the maximum existing bucket
    if "15:30" in bucket_vol.columns:
        last_bucket = "15:30"
    else:
        last_bucket = bucket_cols[-1]

    # Filter days where both buckets and daily |return| are available
    sub = bucket_vol[[first_bucket, last_bucket]].dropna()
    sub = sub.join(daily_df["abs_ret"], how="inner").dropna()

    n_total = len(sub)
    # High vs low by median
    median_abs = float(sub["abs_ret"].median())
    high_mask = sub["abs_ret"] > median_abs
    low_mask = ~high_mask

    # Quartile groups
    q25 = float(sub["abs_ret"].quantile(0.25))
    q75 = float(sub["abs_ret"].quantile(0.75))
    top_q_mask = sub["abs_ret"] >= q75
    bot_q_mask = sub["abs_ret"] <= q25

    results: dict = {
        "ticker": ticker,
        "interval_used": interval,
        "first_bucket": first_bucket,
        "last_bucket": last_bucket,
        "all_buckets": bucket_cols,
        "sample_period": {
            "start": str(sub.index.min()),
            "end": str(sub.index.max()),
        },
        "n_total_days": int(n_total),
        "median_abs_ret": median_abs,
        "q25_abs_ret": q25,
        "q75_abs_ret": q75,
        "groups": {},
        "intraday_vol_path_mean": (
            bucket_vol[bucket_cols].mean(axis=0).to_dict()
        ),
    }

    # Run tests on each group
    for name, mask in (
        ("high_abs_ret_median_split", high_mask),
        ("low_abs_ret_median_split", low_mask),
        ("top_quartile_abs_ret", top_q_mask),
        ("bottom_quartile_abs_ret", bot_q_mask),
        ("all_days", pd.Series(True, index=sub.index)),
    ):
        if mask.sum() < 3:
            results["groups"][name] = {"n": int(mask.sum()), "skipped": True}
            continue
        open_v = sub.loc[mask, first_bucket].values
        close_v = sub.loc[mask, last_bucket].values
        tests = paired_tests(open_v, close_v)
        boot = bootstrap_ci_mean_diff(open_v, close_v, group_tag=f"{ticker}::{name}")
        # also amplification ratio
        amp_ratio = (
            float(np.mean(close_v) / np.mean(open_v))
            if np.mean(open_v) > 0
            else None
        )
        results["groups"][name] = {
            **tests,
            "bootstrap_ci_mean_diff": boot,
            "amplification_ratio_close_over_open": amp_ratio,
        }

    # Between-group tests: high vs low |return| group
    if high_mask.sum() >= 3 and low_mask.sum() >= 3:
        hi_close = sub.loc[high_mask, last_bucket].values
        lo_close = sub.loc[low_mask, last_bucket].values
        hi_open = sub.loc[high_mask, first_bucket].values
        lo_open = sub.loc[low_mask, first_bucket].values
        # Amplification = close - open (paired within day, then compared across groups)
        hi_amp = hi_close - hi_open
        lo_amp = lo_close - lo_open
        mw_close = stats.mannwhitneyu(hi_close, lo_close, alternative="greater")
        mw_amp = stats.mannwhitneyu(hi_amp, lo_amp, alternative="greater")
        results["between_group_high_vs_low"] = {
            "last_bucket_only": {
                "mannwhitney_U": float(mw_close.statistic),
                "mannwhitney_pvalue_one_sided_high_gt_low": float(mw_close.pvalue),
                "mean_high": float(np.mean(hi_close)),
                "mean_low": float(np.mean(lo_close)),
            },
            "amplification_close_minus_open": {
                "mannwhitney_U": float(mw_amp.statistic),
                "mannwhitney_pvalue_one_sided_high_amp_gt_low_amp": float(mw_amp.pvalue),
                "mean_high_amp": float(np.mean(hi_amp)),
                "mean_low_amp": float(np.mean(lo_amp)),
            },
        }

    return results, bucket_vol, sub, first_bucket, last_bucket


def plot_bucket_vol(ticker: str, bucket_vol: pd.DataFrame, sub: pd.DataFrame, out_path: Path) -> None:
    median_abs = float(sub["abs_ret"].median())
    high_dates = sub.index[sub["abs_ret"] > median_abs]
    low_dates = sub.index[sub["abs_ret"] <= median_abs]
    cols = sorted(bucket_vol.columns)
    hi_means = bucket_vol.loc[bucket_vol.index.isin(high_dates), cols].mean()
    lo_means = bucket_vol.loc[bucket_vol.index.isin(low_dates), cols].mean()
    x = np.arange(len(cols))
    width = 0.4
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(x - width / 2, hi_means.values * 100, width, label=f"High |R| (n={len(high_dates)})", color="#d62728")
    ax.bar(x + width / 2, lo_means.values * 100, width, label=f"Low |R| (n={len(low_dates)})", color="#1f77b4")
    ax.set_xticks(x)
    ax.set_xticklabels(cols, rotation=45)
    ax.set_ylabel("Realized vol (sqrt sum 5m r^2), %")
    ax.set_xlabel("Bucket start (ET)")
    ax.set_title(f"{ticker} intraday 30-min bucket vol by |daily return| group (median split)")
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    print(f"[plot] saved {out_path}", flush=True)


def plot_event_study(ticker: str, bucket_vol: pd.DataFrame, sub: pd.DataFrame, out_path: Path) -> None:
    """High |R| days vs low |R| days intraday vol path (with CI)."""
    median_abs = float(sub["abs_ret"].median())
    high_dates = sub.index[sub["abs_ret"] > median_abs]
    low_dates = sub.index[sub["abs_ret"] <= median_abs]
    cols = sorted(bucket_vol.columns)
    hi = bucket_vol.loc[bucket_vol.index.isin(high_dates), cols]
    lo = bucket_vol.loc[bucket_vol.index.isin(low_dates), cols]
    x = np.arange(len(cols))
    fig, ax = plt.subplots(figsize=(11, 5))
    if not hi.empty:
        m = hi.mean(axis=0).values * 100
        s = hi.std(axis=0).values / np.sqrt(max(len(hi), 1)) * 100
        ax.plot(x, m, color="#d62728", marker="o", label=f"High |R| (n={len(hi)})")
        ax.fill_between(x, m - 1.96 * s, m + 1.96 * s, color="#d62728", alpha=0.2)
    if not lo.empty:
        m = lo.mean(axis=0).values * 100
        s = lo.std(axis=0).values / np.sqrt(max(len(lo), 1)) * 100
        ax.plot(x, m, color="#1f77b4", marker="s", label=f"Low |R| (n={len(lo)})")
        ax.fill_between(x, m - 1.96 * s, m + 1.96 * s, color="#1f77b4", alpha=0.2)
    ax.set_xticks(x)
    ax.set_xticklabels(cols, rotation=45)
    ax.set_ylabel("Realized vol (sqrt sum 5m r^2), %")
    ax.set_xlabel("Bucket start (ET)")
    ax.set_title(f"{ticker} intraday vol path: high vs low |daily return| days (95% CI shaded)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    print(f"[plot] saved {out_path}", flush=True)


def main() -> int:
    summary = {
        "experiment_id": "k_leveraged_etf_eod_vol_amplification_2026_06_14",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "tickers": TICKERS,
        "params": {
            "interval_primary": INTERVAL_PRIMARY,
            "period": PERIOD,
            "bucket_minutes": 30,
            "bootstrap_B": BOOTSTRAP_B,
            "rth_start": RTH_START,
            "rth_end": RTH_END,
        },
        "results": {},
    }

    for ticker in TICKERS:
        print(f"\n=== analyzing {ticker} ===", flush=True)
        try:
            res, bucket_vol, sub, first_bk, last_bk = analyze_ticker(ticker)
        except Exception as exc:  # noqa: BLE001
            summary["results"][ticker] = {"error": str(exc)}
            print(f"[ERROR] {ticker}: {exc}", flush=True)
            continue
        summary["results"][ticker] = res

        # plots only if 5m or 15m used
        plot_bucket_vol(
            ticker, bucket_vol, sub, EXP_DIR / f"bucket_vol_by_return_group_{ticker}.png"
        )
        plot_event_study(
            ticker, bucket_vol, sub, EXP_DIR / f"event_study_amplification_{ticker}.png"
        )

    out_json = EXP_DIR / "k_leveraged_etf_eod_vol_amplification_2026_06_14_results.json"
    with out_json.open("w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n[save] {out_json}", flush=True)

    # Print concise verdict
    print("\n=== VERDICT SUMMARY ===", flush=True)
    for tkr in TICKERS:
        r = summary["results"].get(tkr, {})
        if "error" in r:
            print(f"{tkr}: ERROR {r['error']}")
            continue
        gh = r["groups"].get("high_abs_ret_median_split", {})
        ga = r["groups"].get("all_days", {})
        print(
            f"{tkr} interval={r['interval_used']} n={r['n_total_days']} "
            f"first={r['first_bucket']} last={r['last_bucket']}"
        )
        def _fmt(v, spec=".5f"):
            return format(v, spec) if isinstance(v, (int, float)) else "NA"

        if gh and not gh.get("skipped"):
            print(
                f"  high |R|: mean_diff={_fmt(gh.get('mean_diff'))} "
                f"paired_t_p={_fmt(gh.get('paired_t_pvalue'), '.4g')} "
                f"wilcox_p={_fmt(gh.get('wilcoxon_pvalue'), '.4g')} "
                f"amp_ratio={_fmt(gh.get('amplification_ratio_close_over_open'), '.3f')}"
            )
        if ga and not ga.get("skipped"):
            print(
                f"  all days: mean_diff={_fmt(ga.get('mean_diff'))} "
                f"paired_t_p={_fmt(ga.get('paired_t_pvalue'), '.4g')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
