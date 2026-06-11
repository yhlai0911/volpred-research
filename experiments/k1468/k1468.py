"""K1468 — CTA/Managed-Futures ETF vs SPY: drawdown 深度 / 頻率 / 持續時間描述統計

研究問題：trend-following / CTA 策略宣稱 drawdown「頻繁但淺」(FAJ/Man Group/AlphaSimplex
2025 managed-futures literature)，本實驗用免費可得 ETF 代理 (KMLM, DBMF) 對照 SPY 在共同
overlap 窗口的 drawdown 形態描述統計，提供 hedge / diversifier 配置討論的實證 baseline。

特性：
- 純描述統計 (no return / Sharpe / vol — descriptive-only)
- yfinance 免費 data
- Lookahead-safe：cummax 只用 ≤t 的歷史
- Deterministic（no random component）

Proxies:
- KMLM (KFA Mt Lucas Managed Futures Index, ~2020-12 上市)
- DBMF (iMGP DBi Managed Futures, ~2019-05 上市)
- SPY (S&P 500, full history)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

EXPERIMENT_ID = "k1468"
OUT_DIR = Path(__file__).parent
RESULTS_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = OUT_DIR / f"{EXPERIMENT_ID}_drawdown_comparison.png"

TICKERS = ["SPY", "KMLM", "DBMF"]
DD_THRESHOLD = -0.05  # 5%


def fetch_prices(tickers: list[str], start: str = "2010-01-01") -> pd.DataFrame:
    df = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
    return df.dropna(how="all")


def compute_drawdown(price: pd.Series) -> pd.Series:
    """Daily drawdown vs running max (lookahead-safe)."""
    cummax = price.cummax()
    return (price / cummax) - 1.0


def episode_stats(dd: pd.Series, threshold: float = DD_THRESHOLD) -> dict:
    """Identify drawdown episodes: start when dd crosses below threshold, end at recovery to 0."""
    episodes: list[dict] = []
    start_idx: int | None = None
    trough: float = 0.0
    trough_idx: int | None = None
    dd_vals = dd.values
    dd_dates = dd.index
    for i, d in enumerate(dd_vals):
        if start_idx is None and d <= threshold:
            start_idx = i
            trough = d
            trough_idx = i
        elif start_idx is not None:
            if d < trough:
                trough = d
                trough_idx = i
            if d >= 0:
                episodes.append({
                    "start": str(dd_dates[start_idx].date()),
                    "trough_date": str(dd_dates[trough_idx].date()) if trough_idx is not None else None,
                    "end": str(dd_dates[i].date()),
                    "trough_pct": float(trough),
                    "duration_days": int(i - start_idx),
                    "trough_to_recovery_days": int(i - trough_idx) if trough_idx is not None else None,
                })
                start_idx = None
                trough = 0.0
                trough_idx = None

    in_dd = dd <= threshold
    n_total = len(dd)
    max_dd = float(dd.min())

    if not episodes:
        return {
            "n_episodes": 0,
            "max_drawdown": max_dd,
            "pct_time_below_threshold": float(in_dd.mean()),
            "n_observations": int(n_total),
        }

    depths = [e["trough_pct"] for e in episodes]
    durations = [e["duration_days"] for e in episodes]
    recoveries = [e["trough_to_recovery_days"] for e in episodes if e["trough_to_recovery_days"] is not None]

    # Depth bins
    depth_bins = {
        "-5%_to_-10%": sum(1 for d in depths if -0.10 < d <= -0.05),
        "-10%_to_-20%": sum(1 for d in depths if -0.20 < d <= -0.10),
        "deeper_than_-20%": sum(1 for d in depths if d <= -0.20),
    }

    years = (dd.index[-1] - dd.index[0]).days / 365.25

    return {
        "n_episodes": len(episodes),
        "episodes_per_year": float(len(episodes) / years) if years > 0 else None,
        "mean_depth": float(np.mean(depths)),
        "median_depth": float(np.median(depths)),
        "mean_duration_days": float(np.mean(durations)),
        "median_duration_days": float(np.median(durations)),
        "mean_recovery_days": float(np.mean(recoveries)) if recoveries else None,
        "median_recovery_days": float(np.median(recoveries)) if recoveries else None,
        "max_drawdown": max_dd,
        "pct_time_below_threshold": float(in_dd.mean()),
        "depth_bins": depth_bins,
        "years_covered": float(years),
        "n_observations": int(n_total),
        "episodes_sample": episodes[:5],
    }


def make_plot(dd_dict: dict[str, pd.Series], window_label: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    colors = {"SPY": "#1f77b4", "KMLM": "#d62728", "DBMF": "#2ca02c"}
    for name, dd in dd_dict.items():
        ax.plot(dd.index, dd.values * 100, label=name, color=colors.get(name, "gray"), lw=1.2, alpha=0.85)
    ax.axhline(0, color="black", lw=0.6, ls="--", alpha=0.6)
    ax.axhline(-5, color="orange", lw=0.4, ls=":", alpha=0.5)
    ax.axhline(-10, color="red", lw=0.4, ls=":", alpha=0.5)
    ax.set_title(f"Drawdown: SPY vs CTA proxies (KMLM, DBMF), {window_label}")
    ax.set_ylabel("Drawdown (%)")
    ax.set_xlabel("Date")
    ax.legend(loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=130)
    plt.close(fig)


def main() -> dict:
    prices = fetch_prices(TICKERS)
    overlap = prices.dropna(how="any")
    if overlap.empty:
        raise RuntimeError("No overlap window across SPY/KMLM/DBMF")
    overlap_start = str(overlap.index[0].date())
    overlap_end = str(overlap.index[-1].date())

    # Full-history SPY baseline (context)
    spy_full = prices["SPY"].dropna()
    spy_full_dd = compute_drawdown(spy_full)
    spy_full_stats = episode_stats(spy_full_dd, threshold=DD_THRESHOLD)

    # Overlap-window stats — compute drawdown FROM overlap-window start
    dd_overlap = {col: compute_drawdown(overlap[col]) for col in overlap.columns}
    overlap_stats = {col: episode_stats(dd, threshold=DD_THRESHOLD) for col, dd in dd_overlap.items()}

    make_plot(dd_overlap, f"{overlap_start} ~ {overlap_end}")

    out = {
        "experiment_id": EXPERIMENT_ID,
        "title": "CTA/Managed-Futures ETF vs SPY drawdown descriptive comparison",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_question": "Trend-following CTA 策略宣稱 drawdown 頻繁但淺，免費 ETF proxy (KMLM, DBMF) 對照 SPY 是否驗證？",
        "data": {
            "tickers": TICKERS,
            "source": "yfinance Close (auto_adjust=True)",
            "full_history": {"start": str(prices.index[0].date()), "end": str(prices.index[-1].date())},
            "overlap_window": {"start": overlap_start, "end": overlap_end, "n_days": int(len(overlap))},
            "asset_start_dates": {col: str(prices[col].dropna().index[0].date()) for col in prices.columns},
        },
        "spy_full_baseline": {
            "window": {"start": str(spy_full.index[0].date()), "end": str(spy_full.index[-1].date())},
            "stats": spy_full_stats,
        },
        "overlap_window_comparison": overlap_stats,
        "figure": FIG_PATH.name,
        "methodology_notes": [
            f"Drawdown threshold: {DD_THRESHOLD * 100:.0f}%",
            "Episode = drawdown crosses below threshold; ends when recovers to running max (dd>=0).",
            "Overlap-window cummax 從 overlap_start 起算（局部 max），非 full-history max。",
            "Pure descriptive — no statistical test / no return-based comparison（K-followup 可加 vol-scaled return + Sharpe + DM）。",
            "Lookahead-safe: cummax 只用 ≤t 資料。",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    out = main()
    print("=== Overlap-window comparison ===")
    for k, v in out["overlap_window_comparison"].items():
        print(f"\n[{k}]")
        for key in ("n_episodes", "episodes_per_year", "mean_depth", "median_depth",
                    "max_drawdown", "mean_duration_days", "mean_recovery_days",
                    "pct_time_below_threshold", "depth_bins"):
            if key in v:
                print(f"  {key}: {v[key]}")
    print(f"\nFigure: {FIG_PATH}")
    print(f"Results: {RESULTS_PATH}")
