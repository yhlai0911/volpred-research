"""K713 reconstruction: SPY/GLD/TLT static allocation sweep.

Rebuilds the legacy K713 artifact into the canonical three-piece package.
Primary goal is reproducibility, not reverse-engineering the exact legacy
implementation byte-for-byte.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
START_DATE = "2006-01-01"
TICKERS = ["SPY", "GLD", "TLT"]
TLT_WEIGHTS = [0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
REBALANCE_FREQ = "annual"

LEGACY_RETAINED = {
    "tlt_0": {"sharpe": 0.860, "cagr": 11.4, "mdd": -36.8, "calmar": 0.31},
    "tlt_5": {"sharpe": 0.879, "cagr": 11.1, "mdd": -34.2, "calmar": 0.33},
    "tlt_10": {"sharpe": 0.898, "cagr": 10.8, "mdd": -31.6, "calmar": 0.34},
    "tlt_15": {"sharpe": 0.914, "cagr": 10.4, "mdd": -29.0, "calmar": 0.36},
    "tlt_20": {"sharpe": 0.926, "cagr": 10.1, "mdd": -26.4, "calmar": 0.38},
    "tlt_25": {"sharpe": 0.933, "cagr": 9.7, "mdd": -23.8, "calmar": 0.41},
    "tlt_30": {"sharpe": 0.932, "cagr": 9.3, "mdd": -24.3, "calmar": 0.38},
}


def download_prices() -> pd.DataFrame:
    data = yf.download(TICKERS, start=START_DATE, auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]].copy()
        prices.columns = TICKERS
    prices = prices.dropna()
    return prices


def simulate_static_mix(returns: pd.DataFrame, tlt_weight: float) -> dict:
    base_weight = (1.0 - tlt_weight) / 2.0
    target = np.array([base_weight, base_weight, tlt_weight], dtype=float)

    current = target.copy()
    last_rebalance_year = None
    port_returns = []

    for i, (dt, row) in enumerate(returns.iterrows()):
        if i == 0 or dt.year != last_rebalance_year:
            current = target.copy()
            last_rebalance_year = dt.year

        day_ret = float(np.dot(current, row.values))
        port_returns.append(day_ret)

        drifted = current * (1.0 + row.values)
        current = drifted / drifted.sum()

    series = pd.Series(port_returns, index=returns.index, name=f"tlt_{int(tlt_weight * 100)}")
    return compute_metrics(series, tlt_weight)


def compute_metrics(port_returns: pd.Series, tlt_weight: float) -> dict:
    wealth = (1.0 + port_returns).cumprod()
    standard_drawdown = wealth / wealth.cummax() - 1.0
    legacy_drawdown = port_returns.cumsum() - port_returns.cumsum().cummax()

    mean_daily = float(port_returns.mean())
    vol_daily = float(port_returns.std(ddof=1))
    sharpe = mean_daily / vol_daily * np.sqrt(252) if vol_daily > 0 else 0.0
    cagr = wealth.iloc[-1] ** (252 / len(port_returns)) - 1.0
    standard_mdd = float(standard_drawdown.min())
    legacy_mdd = float(legacy_drawdown.min())
    calmar = cagr / abs(standard_mdd) if standard_mdd != 0 else 0.0

    return {
        "tlt_weight": round(tlt_weight, 2),
        "spy_weight_at_rebalance": round((1.0 - tlt_weight) / 2.0, 4),
        "gld_weight_at_rebalance": round((1.0 - tlt_weight) / 2.0, 4),
        "rebalance_frequency": REBALANCE_FREQ,
        "n_days": int(len(port_returns)),
        "date_start": str(port_returns.index[0].date()),
        "date_end": str(port_returns.index[-1].date()),
        "sharpe": round(sharpe, 3),
        "cagr": round(cagr * 100, 1),
        "mdd": round(standard_mdd * 100, 1),
        "calmar": round(calmar, 2),
        "annual_vol": round(vol_daily * np.sqrt(252) * 100, 1),
        "legacy_like_mdd": round(legacy_mdd * 100, 1),
    }


def render_figures(metrics: list[dict]) -> None:
    tlt_pct = [int(m["tlt_weight"] * 100) for m in metrics]
    sharpe = [m["sharpe"] for m in metrics]
    cagr = [m["cagr"] for m in metrics]
    mdd = [m["mdd"] for m in metrics]
    legacy_mdd = [m["legacy_like_mdd"] for m in metrics]

    peak_idx = int(np.argmax(sharpe))

    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(tlt_pct, sharpe, marker="o", linewidth=2.5, color="#1f4e79")
    ax.scatter([tlt_pct[peak_idx]], [sharpe[peak_idx]], color="#d1495b", s=80, zorder=3)
    ax.annotate(
        f"Peak: {tlt_pct[peak_idx]}% TLT\nSharpe {sharpe[peak_idx]:.3f}",
        xy=(tlt_pct[peak_idx], sharpe[peak_idx]),
        xytext=(tlt_pct[peak_idx] + 1, sharpe[peak_idx] - 0.03),
        arrowprops={"arrowstyle": "->", "color": "#444"},
        fontsize=10,
    )
    ax.set_title("K713 Reconstruction: Sharpe by TLT Allocation")
    ax.set_xlabel("TLT Weight (%)")
    ax.set_ylabel("Sharpe (rf=0)")
    fig.tight_layout()
    fig.savefig(ROOT / "k713_tlt_peak.png", dpi=200)
    plt.close(fig)

    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax1.plot(tlt_pct, cagr, marker="o", linewidth=2.2, color="#2a9d8f", label="CAGR")
    ax1.set_xlabel("TLT Weight (%)")
    ax1.set_ylabel("CAGR (%)", color="#2a9d8f")
    ax1.tick_params(axis="y", labelcolor="#2a9d8f")

    ax2 = ax1.twinx()
    ax2.plot(tlt_pct, mdd, marker="s", linewidth=2.2, color="#e76f51", label="Standard MDD")
    ax2.plot(
        tlt_pct,
        legacy_mdd,
        marker="^",
        linewidth=1.4,
        linestyle="--",
        color="#6c757d",
        label="Legacy-like MDD",
    )
    ax2.set_ylabel("Drawdown (%)", color="#e76f51")
    ax2.tick_params(axis="y", labelcolor="#e76f51")

    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc="center right")
    ax1.set_title("K713 Reconstruction: Return vs Drawdown Trade-off")
    fig.tight_layout()
    fig.savefig(ROOT / "k713_return_vs_drawdown.png", dpi=200)
    plt.close(fig)


def build_results(metrics: list[dict], prices: pd.DataFrame) -> dict:
    top_level = {f"tlt_{int(m['tlt_weight'] * 100)}": {
        "sharpe": m["sharpe"],
        "cagr": m["cagr"],
        "mdd": m["mdd"],
        "calmar": m["calmar"],
        "legacy_like_mdd": m["legacy_like_mdd"],
    } for m in metrics}

    best = max(metrics, key=lambda item: item["sharpe"])
    delta_legacy = {}
    for key, legacy in LEGACY_RETAINED.items():
        current = top_level[key]
        delta_legacy[key] = {
            "sharpe_diff": round(current["sharpe"] - legacy["sharpe"], 3),
            "cagr_diff": round(current["cagr"] - legacy["cagr"], 1),
            "mdd_diff": round(current["mdd"] - legacy["mdd"], 1),
            "legacy_like_mdd_diff": round(current["legacy_like_mdd"] - legacy["mdd"], 1),
        }

    results = {
        **top_level,
        "metadata": {
            "experiment_id": "k713",
            "title": "SPY/GLD baseline with TLT allocation sweep",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "yfinance adjusted close",
            "tickers": TICKERS,
            "requested_start_date": START_DATE,
            "effective_start_date": str(prices.index[0].date()),
            "effective_end_date": str(prices.index[-1].date()),
            "sample_size": int(len(prices)),
            "return_observations": int(len(prices) - 1),
            "rebalance_frequency": REBALANCE_FREQ,
            "sharpe_definition": "daily mean / daily std * sqrt(252), rf=0",
            "mdd_definition": "primary mdd uses compounded wealth curve; legacy_like_mdd uses cumulative-return convention for audit comparison",
            "figures": [
                "experiments/k713/k713_tlt_peak.png",
                "experiments/k713/k713_return_vs_drawdown.png",
            ],
        },
        "reconstructed_grid": metrics,
        "best_configuration": best,
        "legacy_retained_results": LEGACY_RETAINED,
        "legacy_vs_reconstructed_delta": delta_legacy,
        "conclusion": (
            f"Using reproducible annual rebalancing on adjusted-close data through {prices.index[-1].date()}, "
            f"{int(best['tlt_weight'] * 100)}% TLT remains the peak Sharpe point ({best['sharpe']:.3f}). "
            f"Relative to 0% TLT, CAGR falls from {metrics[0]['cagr']:.1f}% to {best['cagr']:.1f}% while "
            f"standard MDD improves from {metrics[0]['mdd']:.1f}% to {best['mdd']:.1f}%."
        ),
        "reconstruction_notes": [
            "Legacy artifact preserved only summary metrics and two figures; no original source script exists in git history.",
            "Reconstruction prioritizes a transparent, current, reproducible convention rather than guessing every legacy implementation detail.",
            "Legacy retained MDD values align more closely with a cumulative-return drawdown convention than with compounded-wealth MDD.",
        ],
        "literature": [
            "Markowitz (1952) Portfolio Selection.",
            "DeMiguel, Garlappi, Uppal (2009) Optimal Versus Naive Diversification.",
            "Asness, Frazzini, Pedersen (2012) Leverage Aversion and Risk Parity.",
        ],
    }
    return results


def main() -> None:
    prices = download_prices()
    returns = prices.pct_change().dropna()
    metrics = [simulate_static_mix(returns, weight) for weight in TLT_WEIGHTS]
    render_figures(metrics)
    results = build_results(metrics, prices)
    (ROOT / "k713_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(results["best_configuration"], ensure_ascii=False, indent=2))
    print(results["conclusion"])


if __name__ == "__main__":
    main()
