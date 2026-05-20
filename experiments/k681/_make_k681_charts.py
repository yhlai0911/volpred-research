"""Regenerate K681 charts (originals lost from disk).

Charts (2):
  1. cross_market_equity.png — cumulative return curves for Percentile vs
     12/VIX vs Buy-and-Hold, across 4 markets (SPY/GLD, 0050.TW, EFA,
     0050.TW+GLD). Single multi-panel figure.
  2. efa_drawdown.png        — drawdown time series for EFA Percentile vs
     EFA Buy-and-Hold (the headline international-developed-market case).

Re-runs minimal backtest paths from k681_percentile_global.py so that lag
conventions are preserved (vix_lag1 for Taiwan; contemporaneous VIX for
US/EFA — original K681 design). Final summary numbers must match
k681_results.json (sanity check printed at end).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Reuse identical functions from K681 source for lag fidelity
from k681_percentile_global import (  # noqa: E402
    EVAL_START,
    RF_DAILY,
    TC_BPS_TW,
    TC_BPS_US,
    compute_vix_percentile,
    compute_weights,
    download_data,
)


def equity_curve_single(data: pd.DataFrame, ret_col: str, weight_col: str,
                        tc_bps: float) -> pd.Series:
    """Return cumulative-return Series (1.0 base) for a single-asset VT strategy."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    valid = df[ret_col].notna() & df[weight_col].notna()
    df = df[valid]

    w = df[weight_col].values
    r = df[ret_col].values
    tc_rate = tc_bps / 10000.0
    strat = np.zeros(len(df))
    prev_w = 0.0
    for i in range(len(df)):
        wi = w[i] if not np.isnan(w[i]) else prev_w
        tc = abs(wi - prev_w) * tc_rate
        strat[i] = wi * r[i] + (1 - wi) * RF_DAILY - tc
        prev_w = wi
    cum = np.cumprod(1 + strat)
    return pd.Series(cum, index=df.index, name=weight_col)


def equity_curve_portfolio(data: pd.DataFrame, ret_cols, alloc_weights,
                           weight_col: str, tc_bps: float) -> pd.Series:
    """Equity curve for multi-asset portfolio VT strategy."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    df["port_ret"] = sum(alloc_weights[i] * df[rc] for i, rc in enumerate(ret_cols))
    valid = df["port_ret"].notna() & df[weight_col].notna()
    df = df[valid]

    w = df[weight_col].values
    r = df["port_ret"].values
    tc_rate = tc_bps / 10000.0
    strat = np.zeros(len(df))
    prev_w = 0.0
    for i in range(len(df)):
        wi = w[i] if not np.isnan(w[i]) else prev_w
        tc = abs(wi - prev_w) * tc_rate
        strat[i] = wi * r[i] + (1 - wi) * RF_DAILY - tc
        prev_w = wi
    cum = np.cumprod(1 + strat)
    return pd.Series(cum, index=df.index, name=weight_col)


def equity_curve_buyhold_single(data: pd.DataFrame, ret_col: str) -> pd.Series:
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    r = df[ret_col].dropna()
    return (1 + r).cumprod()


def equity_curve_buyhold_portfolio(data: pd.DataFrame, ret_cols, alloc_weights) -> pd.Series:
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()
    port = sum(alloc_weights[i] * df[rc] for i, rc in enumerate(ret_cols))
    port = port.dropna()
    return (1 + port).cumprod()


def drawdown(curve: pd.Series) -> pd.Series:
    running_max = curve.cummax()
    return (curve - running_max) / running_max


def main() -> None:
    np.random.seed(681)  # deterministic; no actual randomness used
    plt.rcParams["font.family"] = ["DejaVu Sans"]

    print("Downloading data (yfinance)...")
    data = download_data()
    data = compute_vix_percentile(data)
    data = compute_weights(data)

    # --- Equity curves ------------------------------------------------------
    panels = []

    # 1. SPY/GLD 50/50 (US baseline)
    panels.append({
        "title": "US: 50/50 SPY+GLD",
        "pct": equity_curve_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5],
                                      "w_pct_us", TC_BPS_US),
        "vix12": equity_curve_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5],
                                        "w_12vix_us", TC_BPS_US),
        "bh": equity_curve_buyhold_portfolio(data, ["SPY_ret", "GLD_ret"], [0.5, 0.5]),
        "bh_label": "B&H 50/50",
    })

    # 2. 0050.TW (Taiwan; uses lagged VIX)
    panels.append({
        "title": "Taiwan: 0050.TW (VIX_{t-1})",
        "pct": equity_curve_single(data, "0050.TW_ret", "w_pct_tw", TC_BPS_TW),
        "vix12": equity_curve_single(data, "0050.TW_ret", "w_12vix_tw", TC_BPS_TW),
        "bh": equity_curve_buyhold_single(data, "0050.TW_ret"),
        "bh_label": "B&H 0050",
    })

    # 3. 0050.TW + GLD 50/50 (Taiwan portfolio; lagged VIX)
    panels.append({
        "title": "Taiwan + Gold: 50/50 0050.TW+GLD",
        "pct": equity_curve_portfolio(data, ["0050.TW_ret", "GLD_ret"], [0.5, 0.5],
                                      "w_pct_tw", TC_BPS_TW),
        "vix12": equity_curve_portfolio(data, ["0050.TW_ret", "GLD_ret"], [0.5, 0.5],
                                        "w_12vix_tw", TC_BPS_TW),
        "bh": equity_curve_buyhold_portfolio(data, ["0050.TW_ret", "GLD_ret"], [0.5, 0.5]),
        "bh_label": "B&H 50/50",
    })

    # 4. EFA International
    panels.append({
        "title": "International (ex-US): EFA",
        "pct": equity_curve_single(data, "EFA_ret", "w_pct_us", TC_BPS_US),
        "vix12": equity_curve_single(data, "EFA_ret", "w_12vix_us", TC_BPS_US),
        "bh": equity_curve_buyhold_single(data, "EFA_ret"),
        "bh_label": "B&H EFA",
    })

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=False)
    axes = axes.flatten()
    for ax, panel in zip(axes, panels):
        ax.plot(panel["pct"].index, panel["pct"].values,
                color="#1f77b4", linewidth=1.6, label="Percentile (1−VIX pct)")
        ax.plot(panel["vix12"].index, panel["vix12"].values,
                color="#ff7f0e", linewidth=1.3, label="12/VIX")
        ax.plot(panel["bh"].index, panel["bh"].values,
                color="#7f7f7f", linewidth=1.1, alpha=0.8, label=panel["bh_label"])
        ax.set_title(panel["title"], fontsize=11, fontweight="bold")
        ax.set_ylabel("Cumulative return (×)")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    fig.suptitle("K681: VIX-Percentile vs 12/VIX vs Buy-and-Hold across four markets",
                 fontsize=13, fontweight="bold", y=1.00)
    fig.tight_layout()
    fig.savefig(HERE / "cross_market_equity.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote cross_market_equity.png")

    # --- EFA drawdown chart -------------------------------------------------
    efa_pct = panels[3]["pct"]
    efa_bh = panels[3]["bh"]
    efa_pct_dd = drawdown(efa_pct) * 100
    efa_bh_dd = drawdown(efa_bh) * 100

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.fill_between(efa_pct_dd.index, efa_pct_dd.values, 0,
                    color="#1f77b4", alpha=0.35, label="Percentile drawdown")
    ax.plot(efa_pct_dd.index, efa_pct_dd.values, color="#1f77b4", linewidth=1.0)
    ax.fill_between(efa_bh_dd.index, efa_bh_dd.values, 0,
                    color="#7f7f7f", alpha=0.30, label="B&H EFA drawdown")
    ax.plot(efa_bh_dd.index, efa_bh_dd.values, color="#555555", linewidth=1.0)

    pct_mdd = float(efa_pct_dd.min())
    bh_mdd = float(efa_bh_dd.min())
    ax.axhline(pct_mdd, color="#1f77b4", linestyle=":", linewidth=1.0)
    ax.axhline(bh_mdd, color="#555555", linestyle=":", linewidth=1.0)
    ax.text(efa_pct_dd.index[10], pct_mdd + 0.5,
            f"Percentile MDD = {pct_mdd:.2f}%", color="#1f77b4", fontsize=9)
    ax.text(efa_bh_dd.index[10], bh_mdd - 1.5,
            f"B&H MDD = {bh_mdd:.2f}%", color="#333333", fontsize=9)

    ax.set_ylabel("Drawdown (%)")
    ax.set_title("K681: EFA — Percentile vs Buy-and-Hold drawdown",
                 fontsize=12, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    ax.legend(loc="lower left", fontsize=10, framealpha=0.85)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(HERE / "efa_drawdown.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote efa_drawdown.png")

    # --- Sanity check: compare to results.json ------------------------------
    res = json.loads((HERE / "k681_results.json").read_text())
    expected = {
        "EFA Percentile MDD (results.json)": res["market_results"]["EFA_International"]["percentile"]["mdd_pct"],
        "EFA Buy-Hold MDD (results.json)":   res["market_results"]["EFA_International"]["buy_hold"]["mdd_pct"],
    }
    print("\nSanity check (recomputed vs stored):")
    print(f"  EFA Percentile MDD: regen={pct_mdd:.2f}%, stored={expected['EFA Percentile MDD (results.json)']}%")
    print(f"  EFA Buy-Hold MDD:   regen={bh_mdd:.2f}%, stored={expected['EFA Buy-Hold MDD (results.json)']}%")


if __name__ == "__main__":
    main()
