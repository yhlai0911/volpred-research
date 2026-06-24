"""K1549: Russell Reconstitution Announcement-to-Effective Window Event Study.

Tests whether the ex-ante known 1-month Russell reconstitution window
(announcement -> effective) elevates RV / volume / abs-return for IWM /
IWO / IWN / IWP vs. a 90-day pre-event baseline.

Lookahead policy
----------------
- Anchor = announcement_date, a publicly known calendar date (no
  signal-shift needed — this is descriptive, no trading rule).
- Baseline window strictly precedes announcement_date by >= 1 day.
- No metric uses information past the trading day on which it is computed.

Seed
----
- np.random.default_rng(seed=42) for the wild bootstrap CI.

Author: VolPred Research Platform
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

EXPERIMENT_ID = "K1549"
ETFS = ["IWM", "IWO", "IWN", "IWP"]
SEED = 42
OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------
# Russell reconstitution calendar (FTSE Russell historical schedule).
# Announcement date: preliminary list published, typically first Friday of June
#   (historical; the "queries period" begin date). FTSE Russell official
#   schedule names this the "Rank Day" + ~1 week. We use the published
#   "preliminary list" date as a robust proxy for the ex-ante public anchor.
# Effective date: last Friday of June (2007-2021); fourth Friday of June from
#   2022 onward. Source: FTSE Russell official "Russell US Indexes
#   Reconstitution Schedule" PDFs (2010-2026).
# ----------------------------------------------------------------------------
RUSSELL_CALENDAR = {
    2010: ("2010-06-11", "2010-06-25"),  # last Friday of June
    2011: ("2011-06-10", "2011-06-24"),
    2012: ("2012-06-08", "2012-06-22"),
    2013: ("2013-06-14", "2013-06-28"),
    2014: ("2014-06-13", "2014-06-27"),
    2015: ("2015-06-12", "2015-06-26"),
    2016: ("2016-06-10", "2016-06-24"),
    2017: ("2017-06-09", "2017-06-23"),
    2018: ("2018-06-08", "2018-06-22"),
    2019: ("2019-06-07", "2019-06-28"),
    2020: ("2020-06-05", "2020-06-26"),
    2021: ("2021-06-04", "2021-06-25"),
    2022: ("2022-06-03", "2022-06-24"),  # fourth Friday from 2022
    2023: ("2023-06-02", "2023-06-23"),
    2024: ("2024-05-31", "2024-06-28"),
    2025: ("2025-06-06", "2025-06-27"),
}


def fetch_etf(ticker: str, start: str = "2009-10-01", end: str = "2026-06-24") -> pd.DataFrame:
    """Fetch daily OHLCV from yfinance, return DataFrame indexed by date.

    Falls back gracefully on missing data; caller checks for NaN coverage.
    """
    df = yf.download(
        ticker,
        start=start,
        end=end,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df["log_ret"] = np.log(df["Close"] / df["Close"].shift(1))
    df["sq_ret"] = df["log_ret"] ** 2
    df["abs_ret"] = df["log_ret"].abs()
    return df


def window_stats(
    df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> dict:
    """Return mean sq_ret / volume / abs_ret over [start, end] (inclusive).

    Skips the first row of df (NaN log_ret) automatically via dropna.
    """
    sub = df.loc[(df.index >= start) & (df.index <= end)].dropna(
        subset=["log_ret", "sq_ret", "abs_ret", "Volume"]
    )
    if len(sub) == 0:
        return {
            "n": 0,
            "mean_sq_ret": np.nan,
            "mean_volume": np.nan,
            "mean_abs_ret": np.nan,
        }
    return {
        "n": int(len(sub)),
        "mean_sq_ret": float(sub["sq_ret"].mean()),
        "mean_volume": float(sub["Volume"].mean()),
        "mean_abs_ret": float(sub["abs_ret"].mean()),
    }


def per_event_ratios(df: pd.DataFrame) -> list[dict]:
    """For each Russell year in calendar, compute event/baseline ratios."""
    out = []
    for year, (ann_str, eff_str) in RUSSELL_CALENDAR.items():
        ann = pd.Timestamp(ann_str)
        eff = pd.Timestamp(eff_str)
        # Baseline strictly precedes announcement: [ann - 90 cal days, ann - 1]
        bl_start = ann - pd.Timedelta(days=90)
        bl_end = ann - pd.Timedelta(days=1)
        ev_start = ann
        ev_end = eff

        bl = window_stats(df, bl_start, bl_end)
        ev = window_stats(df, ev_start, ev_end)

        rec = {
            "year": year,
            "ann_date": ann_str,
            "eff_date": eff_str,
            "baseline_n": bl["n"],
            "event_n": ev["n"],
        }
        for metric in ("sq_ret", "volume", "abs_ret"):
            bl_mean = bl[f"mean_{metric}"]
            ev_mean = ev[f"mean_{metric}"]
            if (
                np.isnan(bl_mean)
                or np.isnan(ev_mean)
                or bl_mean <= 0
                or ev_mean <= 0
            ):
                ratio = np.nan
                log_ratio = np.nan
            else:
                ratio = ev_mean / bl_mean
                log_ratio = float(np.log(ratio))
            rec[f"ratio_{metric}"] = float(ratio) if not np.isnan(ratio) else None
            rec[f"log_ratio_{metric}"] = (
                float(log_ratio) if not np.isnan(log_ratio) else None
            )
        out.append(rec)
    return out


def pooled_tests(per_event: list[dict], metric_key: str) -> dict:
    """Pool log-ratios across years; t-test and Wilcoxon vs. 0.

    Returns t-stat, t-pval (two-sided), Wilcoxon-stat, Wilcoxon-pval, n,
    mean ratio (geometric, i.e., exp(mean log_ratio)).
    """
    vals = [
        e[f"log_ratio_{metric_key}"]
        for e in per_event
        if e.get(f"log_ratio_{metric_key}") is not None
    ]
    arr = np.asarray(vals, dtype=float)
    n = int(arr.size)
    if n < 3:
        return {
            "n": n,
            "mean_log_ratio": None,
            "geom_mean_ratio": None,
            "t_stat": None,
            "t_pval_twosided": None,
            "wilcoxon_stat": None,
            "wilcoxon_pval": None,
        }
    t_stat, t_p = stats.ttest_1samp(arr, popmean=0.0)
    try:
        w_stat, w_p = stats.wilcoxon(arr, zero_method="wilcox", alternative="two-sided")
    except ValueError:
        w_stat, w_p = (np.nan, np.nan)
    return {
        "n": n,
        "mean_log_ratio": float(np.mean(arr)),
        "geom_mean_ratio": float(np.exp(np.mean(arr))),
        "t_stat": float(t_stat),
        "t_pval_twosided": float(t_p),
        "wilcoxon_stat": float(w_stat) if not np.isnan(w_stat) else None,
        "wilcoxon_pval": float(w_p) if not np.isnan(w_p) else None,
    }


def bootstrap_ci(per_event: list[dict], metric_key: str, n_boot: int = 5000) -> dict:
    """Wild bootstrap 95% CI on the mean log-ratio. Seed = 42."""
    rng = np.random.default_rng(SEED)
    vals = np.asarray(
        [
            e[f"log_ratio_{metric_key}"]
            for e in per_event
            if e.get(f"log_ratio_{metric_key}") is not None
        ],
        dtype=float,
    )
    if vals.size < 3:
        return {"lo": None, "hi": None}
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, vals.size, size=vals.size)
        boots[i] = float(vals[idx].mean())
    lo, hi = np.quantile(boots, [0.025, 0.975])
    return {"lo": float(lo), "hi": float(hi)}


def run() -> dict:
    results: dict = {
        "experiment_id": EXPERIMENT_ID,
        "run_date": "2026-06-24",
        "seed": SEED,
        "etfs": ETFS,
        "n_years": len(RUSSELL_CALENDAR),
        "calendar_source": "FTSE Russell official reconstitution schedule",
        "calendar": RUSSELL_CALENDAR,
        "per_etf": {},
        "bonferroni": {
            "n_tests": 4 * 3,
            "alpha_family": 0.05,
            "alpha_adjusted": 0.05 / 12,
        },
        "data_coverage": {},
    }

    for etf in ETFS:
        print(f"[K1549] fetching {etf} ...")
        df = fetch_etf(etf)
        first = df.index.min().strftime("%Y-%m-%d") if len(df) else None
        last = df.index.max().strftime("%Y-%m-%d") if len(df) else None
        results["data_coverage"][etf] = {
            "n_rows": int(len(df)),
            "first": first,
            "last": last,
        }

        per_event = per_event_ratios(df)
        results["per_etf"][etf] = {
            "per_year": per_event,
            "pooled_sq_ret": pooled_tests(per_event, "sq_ret"),
            "pooled_volume": pooled_tests(per_event, "volume"),
            "pooled_abs_ret": pooled_tests(per_event, "abs_ret"),
            "bootstrap_ci_sq_ret": bootstrap_ci(per_event, "sq_ret"),
            "bootstrap_ci_volume": bootstrap_ci(per_event, "volume"),
            "bootstrap_ci_abs_ret": bootstrap_ci(per_event, "abs_ret"),
        }

    # Bonferroni-marked significance map
    sig_map = {}
    alpha = results["bonferroni"]["alpha_adjusted"]
    for etf in ETFS:
        sig_map[etf] = {}
        for metric in ("sq_ret", "volume", "abs_ret"):
            p = results["per_etf"][etf][f"pooled_{metric}"]["t_pval_twosided"]
            sig_map[etf][metric] = bool(p is not None and p < alpha)
    results["bonferroni"]["significant"] = sig_map

    return results


def make_figures(results: dict) -> None:
    """Figure 1: per-ETF mean ratio across 3 metrics bar chart.
    Figure 2: pooled-year log-ratio distribution per ETF (squared return)."""

    # Fig 1: 3-metric bar per ETF, geometric mean ratio
    fig, ax = plt.subplots(figsize=(9, 5))
    metrics = ["sq_ret", "volume", "abs_ret"]
    metric_labels = {"sq_ret": "RV (sq ret)", "volume": "Volume", "abs_ret": "Abs return"}
    x = np.arange(len(ETFS))
    width = 0.25
    for i, m in enumerate(metrics):
        vals = [
            results["per_etf"][etf][f"pooled_{m}"]["geom_mean_ratio"] or np.nan
            for etf in ETFS
        ]
        ax.bar(x + (i - 1) * width, vals, width, label=metric_labels[m])
    ax.axhline(1.0, color="k", linestyle="--", alpha=0.6, label="null = 1.0")
    ax.set_xticks(x)
    ax.set_xticklabels(ETFS)
    ax.set_ylabel("Geometric-mean event/baseline ratio")
    ax.set_title(
        "K1549 — Russell reconstitution window (announcement→effective)\n"
        "ETF event-window / 90d-baseline mean ratios (pooled across 16 years)"
    )
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig1_etf_metric_ratios.png", dpi=150)
    plt.close(fig)

    # Fig 2: per-year log-ratio distribution (sq_ret) per ETF
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharex=True)
    for ax, etf in zip(axes.flat, ETFS):
        per_event = results["per_etf"][etf]["per_year"]
        vals = [
            e["log_ratio_sq_ret"]
            for e in per_event
            if e.get("log_ratio_sq_ret") is not None
        ]
        ax.hist(vals, bins=10, edgecolor="k", alpha=0.7)
        ax.axvline(0.0, color="r", linestyle="--", label="null log-ratio = 0")
        ax.axvline(np.mean(vals), color="b", linestyle="-", label=f"mean = {np.mean(vals):.3f}")
        ax.set_title(f"{etf} — log-ratio per year (sq_ret)")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    fig.suptitle(
        "K1549 — pooled-year log-ratio distribution of squared returns\n"
        "(event window vs. 90-day pre-event baseline)"
    )
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig2_logratio_distribution.png", dpi=150)
    plt.close(fig)


def main() -> None:
    results = run()
    out_json = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
    with out_json.open("w") as fp:
        json.dump(results, fp, indent=2, default=str)
    print(f"[K1549] wrote {out_json}")
    make_figures(results)
    print(f"[K1549] wrote figures to {FIG_DIR}")

    # Compact stdout summary
    alpha = results["bonferroni"]["alpha_adjusted"]
    print(f"\n=== K1549 SUMMARY (Bonferroni alpha = {alpha:.5f}) ===")
    for etf in ETFS:
        print(f"\n{etf}:")
        for metric in ("sq_ret", "volume", "abs_ret"):
            p = results["per_etf"][etf][f"pooled_{metric}"]
            gm = p["geom_mean_ratio"]
            pv = p["t_pval_twosided"]
            sig = "***" if (pv is not None and pv < alpha) else ""
            gm_str = f"{gm:.3f}" if gm is not None else "NA"
            pv_str = f"{pv:.4f}" if pv is not None else "NA"
            print(f"  {metric:8s}  geom-mean ratio = {gm_str}  t-p = {pv_str}  {sig}")


if __name__ == "__main__":
    main()
