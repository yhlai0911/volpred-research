"""
HF Microstructure sub-5min demonstration figures for daily_article
(2026-04-18, audience=research).

Generates 2 figures:
  1. Signature plot: RV estimator as function of sampling frequency
     (illustrates microstructure-noise-induced bias at sub-5min).
  2. Return-autocorr plot at sub-5min vs 5-min (shows bid-ask bounce
     footprint — negative lag-1 autocorr at 1-min collapses by 5-min).

Data: yfinance SPY
  - 5-min: period=60d, interval=5m
  - 1-min: period=7d, interval=1m  (yfinance hard cap)

Methodology references:
  - Andersen & Bollerslev (1997) "Heterogeneous information arrivals ...
    realized volatilities..." J. Empirical Finance
  - Bandi & Russell (2008) "Microstructure noise, realized variance, and
    optimal sampling" Rev. Econ. Studies
  - Barndorff-Nielsen, Hansen, Lunde, Shephard (2008) "Designing realized
    kernels..." Econometrica

Seed: 42 (deterministic; yfinance download is the only stochastic source —
identical under same date window).

Output:
  - storage/figures/daily_2026_04_18_hf_microstructure_signature.png
  - storage/figures/daily_2026_04_18_hf_microstructure_autocorr.png
  - results JSON alongside for traceability
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

SEED = 42
np.random.seed(SEED)

FIG_DIR = Path("storage/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = FIG_DIR / "daily_2026_04_18_hf_microstructure_results.json"

TICKER = "SPY"


def _fetch(period: str, interval: str) -> pd.DataFrame:
    df = yf.download(
        TICKER,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=True,
    )
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {period}/{interval}")
    # collapse multi-index columns (yfinance newer API)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[["Close"]].dropna()
    return df


def _log_returns_per_day(close: pd.Series, bars_per_period: int) -> list[np.ndarray]:
    """Group by local date, compute log returns, then downsample by bars_per_period."""
    close = close.copy()
    # utc -> US eastern regular session; yfinance returns UTC naive for intraday.
    # Group by calendar date (enough for our demonstration).
    close.index = pd.to_datetime(close.index, utc=True)
    daily_rets: list[np.ndarray] = []
    for _, group in close.groupby(close.index.date):
        if len(group) < bars_per_period + 2:
            continue
        # downsample: take every bars_per_period-th close
        sampled = group.iloc[::bars_per_period]
        if len(sampled) < 3:
            continue
        r = np.log(sampled.values / sampled.shift(1).values)
        r = r[~np.isnan(r)]
        daily_rets.append(r)
    return daily_rets


def compute_signature_plot():
    """
    For each sampling frequency, compute mean daily RV and plot vs freq.
    Key observation: naive sum-of-squared-returns biases upward as freq ->
    infinity (Bandi & Russell 2008).
    """
    # 1-min base (7d cap) for fine end; 5-min base (60d) for coarse end
    close_1m = _fetch(period="7d", interval="1m")["Close"]
    close_5m = _fetch(period="60d", interval="5m")["Close"]

    # sub-5min frequencies use 1-min base
    freqs_sub5 = [1, 2, 3]  # minutes
    rv_sub5 = {}
    for f in freqs_sub5:
        daily_rets = _log_returns_per_day(close_1m, bars_per_period=f)
        # annualized RV per day
        rv_daily = np.array([np.sum(r**2) for r in daily_rets])
        # scale to annualized % sigma
        ann = np.sqrt(rv_daily * 252) * 100
        rv_sub5[f] = {
            "mean_ann_sigma_pct": float(np.mean(ann)),
            "median_ann_sigma_pct": float(np.median(ann)),
            "n_days": int(len(ann)),
        }

    # ≥5 min frequencies use 5-min base
    freqs_ge5 = [1, 2, 3, 6, 13, 26]  # in 5-min units → 5/10/15/30/65/130 min
    rv_ge5 = {}
    for f in freqs_ge5:
        daily_rets = _log_returns_per_day(close_5m, bars_per_period=f)
        rv_daily = np.array([np.sum(r**2) for r in daily_rets])
        ann = np.sqrt(rv_daily * 252) * 100
        mins = f * 5
        rv_ge5[mins] = {
            "mean_ann_sigma_pct": float(np.mean(ann)),
            "median_ann_sigma_pct": float(np.median(ann)),
            "n_days": int(len(ann)),
        }

    # plot
    fig, ax = plt.subplots(figsize=(9, 5.5))
    xs_sub5 = list(freqs_sub5)
    ys_sub5 = [rv_sub5[f]["mean_ann_sigma_pct"] for f in xs_sub5]
    xs_ge5 = sorted(rv_ge5.keys())
    ys_ge5 = [rv_ge5[m]["mean_ann_sigma_pct"] for m in xs_ge5]

    ax.plot(xs_sub5, ys_sub5, "o-", color="crimson", label="1-min base (7d)", linewidth=2)
    ax.plot(xs_ge5, ys_ge5, "s-", color="steelblue", label="5-min base (60d)", linewidth=2)
    ax.axvline(5, color="grey", linestyle="--", alpha=0.5, label="5-min convention")
    ax.set_xlabel("Sampling interval (minutes)", fontsize=11)
    ax.set_ylabel("Mean annualized RV (%)", fontsize=11)
    ax.set_xscale("log")
    ax.set_xticks([1, 2, 3, 5, 10, 15, 30, 65, 130])
    ax.set_xticklabels(["1", "2", "3", "5", "10", "15", "30", "65", "130"])
    ax.set_title(
        "SPY Signature Plot — RV estimator vs sampling frequency\n"
        "(microstructure noise inflates RV at sub-5min; 5-min is the conventional noise-robust choice)",
        fontsize=11,
    )
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=10)

    # annotate the sub-5min inflation magnitude
    if 5 in rv_ge5 and 1 in rv_sub5:
        lift = (rv_sub5[1]["mean_ann_sigma_pct"] / rv_ge5[5]["mean_ann_sigma_pct"] - 1) * 100
        ax.annotate(
            f"1-min vs 5-min: +{lift:.1f}% inflation",
            xy=(1.1, rv_sub5[1]["mean_ann_sigma_pct"]),
            xytext=(2, rv_sub5[1]["mean_ann_sigma_pct"] * 1.05),
            fontsize=10,
            color="crimson",
            arrowprops=dict(arrowstyle="->", color="crimson", alpha=0.6),
        )

    out_path = FIG_DIR / "daily_2026_04_18_hf_microstructure_signature.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_path}")
    return {
        "sub5_min_base": rv_sub5,
        "ge5_min_base": rv_ge5,
        "figure_path": str(out_path),
    }


def compute_autocorr_plot():
    """
    Return autocorrelation at lag 1 for 1-min, 2-min, 3-min, 5-min returns.
    Bid-ask bounce predicts negative lag-1 at finest grid, attenuating as we
    coarsen (Roll 1984; Hasbrouck 2007).
    """
    close_1m = _fetch(period="7d", interval="1m")["Close"]
    close_5m = _fetch(period="60d", interval="5m")["Close"]

    acf = {}

    for f in [1, 2, 3]:
        daily_rets = _log_returns_per_day(close_1m, bars_per_period=f)
        all_r = np.concatenate(daily_rets) if daily_rets else np.array([])
        if len(all_r) >= 20:
            lag1 = float(np.corrcoef(all_r[:-1], all_r[1:])[0, 1])
            n = len(all_r)
            se = 1 / np.sqrt(n)
            acf[f"{f}-min"] = {"lag1_acf": lag1, "n_obs": n, "se": float(se)}

    for f_units, mins in [(1, 5), (2, 10), (3, 15), (6, 30)]:
        daily_rets = _log_returns_per_day(close_5m, bars_per_period=f_units)
        all_r = np.concatenate(daily_rets) if daily_rets else np.array([])
        if len(all_r) >= 20:
            lag1 = float(np.corrcoef(all_r[:-1], all_r[1:])[0, 1])
            n = len(all_r)
            se = 1 / np.sqrt(n)
            acf[f"{mins}-min"] = {"lag1_acf": lag1, "n_obs": n, "se": float(se)}

    # plot
    order = ["1-min", "2-min", "3-min", "5-min", "10-min", "15-min", "30-min"]
    labels = [k for k in order if k in acf]
    vals = [acf[k]["lag1_acf"] for k in labels]
    ses = [acf[k]["se"] for k in labels]
    colors = ["crimson" if v < -1.96 * s else "steelblue" for v, s in zip(vals, ses)]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    xs = np.arange(len(labels))
    bars = ax.bar(xs, vals, yerr=[1.96 * s for s in ses], capsize=5, color=colors, alpha=0.85)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axhline(0, color="grey", linestyle=":", alpha=0)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Lag-1 return autocorrelation", fontsize=11)
    ax.set_title(
        "SPY return autocorrelation vs sampling frequency\n"
        "(bid-ask bounce → negative lag-1 at 1-min; attenuates by 5-min)",
        fontsize=11,
    )
    ax.grid(True, alpha=0.3, axis="y")

    # annotate values
    for x, v, s in zip(xs, vals, ses):
        ax.text(x, v - 0.008 if v < 0 else v + 0.008,
                f"{v:+.3f}\n(SE={s:.3f})",
                ha="center",
                va="top" if v < 0 else "bottom",
                fontsize=9)

    out_path = FIG_DIR / "daily_2026_04_18_hf_microstructure_autocorr.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_path}")
    return {"acf_by_freq": acf, "figure_path": str(out_path)}


def main():
    print(f"=== HF Microstructure sub-5min demonstration ({TICKER}) ===")
    print(f"Seed: {SEED}")
    print(f"Run time (UTC): {datetime.now(timezone.utc).isoformat()}")

    sig = compute_signature_plot()
    acf = compute_autocorr_plot()

    summary = {
        "ticker": TICKER,
        "seed": SEED,
        "run_time_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance",
        "windows": {
            "1-min": "period=7d (yfinance hard cap)",
            "5-min": "period=60d",
        },
        "signature_plot": sig,
        "autocorr_plot": acf,
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Saved results JSON: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
