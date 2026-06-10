"""K1446: Factor ETF volatility and downside-risk diagnostics.

Question:
  Are factor ETFs materially different in realized volatility and downside risk,
  and does USMV actually deliver lower risk than MTUM / QUAL / VLUE / SPY?

Design:
  - Descriptive, no predictive claim.
  - yfinance adjusted close for MTUM / QUAL / USMV / VLUE / SPY.
  - Compare full-sample risk metrics on the common sample.
  - Use non-overlapping 21-trading-day blocks for paired risk comparisons to
    avoid overlap-induced pseudo-significance.
  - Paired Wilcoxon + bootstrap CI with fixed seed.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import wilcoxon

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
END_DATE = "2026-06-10"  # exclusive in yfinance -> includes 2026-06-09
START_DATE = "2010-01-01"
TICKERS = ["MTUM", "QUAL", "USMV", "VLUE", "SPY"]
BLOCK = 21
BOOT_REPS = 5000
ALPHA = 0.05
BONF_ALPHA = ALPHA / ((len(TICKERS) - 1) * 2)  # 4 peers x 2 metrics


@dataclass
class RiskSummary:
    ann_return_pct: float
    ann_vol_pct: float
    downside_dev_pct: float
    var_5_pct: float
    es_5_pct: float
    max_drawdown_pct: float
    neg_day_share_pct: float
    worst_day_pct: float
    n_obs: int
    start: str
    end: str


def fetch_prices() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    out = {}
    for ticker in TICKERS:
        try:
            ser = raw[ticker]["Close"].rename(ticker)
        except Exception:
            ser = raw["Close"][ticker].rename(ticker)
        out[ticker] = ser.dropna()
    return pd.DataFrame(out).sort_index()


def log_returns(prices: pd.Series) -> pd.Series:
    return np.log(prices / prices.shift(1)).dropna()


def downside_deviation(ret: pd.Series) -> float:
    downside = np.minimum(ret.values, 0.0)
    return float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252))


def max_drawdown_from_logret(ret: pd.Series) -> float:
    cum = np.exp(ret.cumsum())
    dd = cum / cum.cummax() - 1.0
    return float(dd.min())


def risk_summary(ret: pd.Series) -> RiskSummary:
    q5 = float(ret.quantile(0.05))
    tail = ret[ret <= q5]
    return RiskSummary(
        ann_return_pct=float(ret.mean() * 252 * 100),
        ann_vol_pct=float(ret.std(ddof=1) * np.sqrt(252) * 100),
        downside_dev_pct=float(downside_deviation(ret) * 100),
        var_5_pct=q5 * 100,
        es_5_pct=float(tail.mean() * 100),
        max_drawdown_pct=max_drawdown_from_logret(ret) * 100,
        neg_day_share_pct=float((ret < 0).mean() * 100),
        worst_day_pct=float(ret.min() * 100),
        n_obs=int(ret.shape[0]),
        start=ret.index.min().strftime("%Y-%m-%d"),
        end=ret.index.max().strftime("%Y-%m-%d"),
    )


def block_metrics(ret: pd.Series, block_size: int = BLOCK) -> pd.DataFrame:
    usable = (len(ret) // block_size) * block_size
    trimmed = ret.iloc[:usable]
    arr = trimmed.values.reshape(-1, block_size)
    block_end_dates = trimmed.index[block_size - 1::block_size]
    block_rv = arr.std(axis=1, ddof=1) * np.sqrt(252)
    downside = np.sqrt(np.mean(np.minimum(arr, 0.0) ** 2, axis=1)) * np.sqrt(252)
    return pd.DataFrame(
        {
            "block_end": block_end_dates,
            "rv": block_rv,
            "downside_dev": downside,
        }
    ).set_index("block_end")


def paired_bootstrap_mean(diff: np.ndarray, reps: int = BOOT_REPS) -> dict:
    idx = np.random.randint(0, len(diff), size=(reps, len(diff)))
    sample_means = diff[idx].mean(axis=1)
    return {
        "mean_diff": float(diff.mean()),
        "ci_95_low": float(np.quantile(sample_means, 0.025)),
        "ci_95_high": float(np.quantile(sample_means, 0.975)),
        "p_mean_diff_gt_zero": float((sample_means > 0).mean()),
    }


def paired_compare(usmv: pd.Series, peer: pd.Series) -> dict:
    diff = peer.values - usmv.values
    boot = paired_bootstrap_mean(diff)
    w_stat, w_p = wilcoxon(diff, alternative="greater", zero_method="wilcox")
    return {
        "n_blocks": int(len(diff)),
        "mean_usmv": float(usmv.mean()),
        "mean_peer": float(peer.mean()),
        "mean_diff_peer_minus_usmv": boot["mean_diff"],
        "bootstrap_ci_95": [boot["ci_95_low"], boot["ci_95_high"]],
        "bootstrap_prob_peer_gt_usmv": boot["p_mean_diff_gt_zero"],
        "wilcoxon_stat": float(w_stat),
        "wilcoxon_pvalue_one_sided": float(w_p),
        "passes_bonferroni_0_00625": bool(w_p < BONF_ALPHA and boot["ci_95_low"] > 0),
    }


def make_figures(common_returns: pd.DataFrame, summaries: dict[str, RiskSummary], blocks: dict[str, pd.DataFrame]) -> list[str]:
    fig_paths: list[str] = []

    rolling_vol = common_returns.rolling(63, min_periods=63).std(ddof=1) * np.sqrt(252) * 100
    fig, ax = plt.subplots(figsize=(10, 5))
    for ticker in TICKERS:
        ax.plot(rolling_vol.index, rolling_vol[ticker], label=ticker, linewidth=1.1)
    ax.set_title("K1446 Fig 1 — Rolling 63-Day Annualized Volatility (%)")
    ax.set_ylabel("Vol (%)")
    ax.grid(alpha=0.25)
    ax.legend(ncols=3)
    fig.tight_layout()
    path1 = OUT_DIR / "fig1_rolling_vol_63d.png"
    fig.savefig(path1, dpi=150)
    plt.close(fig)
    fig_paths.append(path1.name)

    risk_df = pd.DataFrame(
        {
            "ann_vol_pct": {k: v.ann_vol_pct for k, v in summaries.items()},
            "downside_dev_pct": {k: v.downside_dev_pct for k, v in summaries.items()},
        }
    )
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(risk_df.index))
    width = 0.38
    ax.bar(x - width / 2, risk_df["ann_vol_pct"], width=width, label="Ann vol")
    ax.bar(x + width / 2, risk_df["downside_dev_pct"], width=width, label="Downside dev")
    ax.set_xticks(x)
    ax.set_xticklabels(risk_df.index)
    ax.set_ylabel("%")
    ax.set_title("K1446 Fig 2 — Full-Sample Risk Level Comparison")
    ax.legend()
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    path2 = OUT_DIR / "fig2_full_sample_risk_bars.png"
    fig.savefig(path2, dpi=150)
    plt.close(fig)
    fig_paths.append(path2.name)

    peer_names = [t for t in TICKERS if t != "USMV"]
    peer_means = [blocks[t]["rv"].mean() * 100 for t in peer_names]
    usmv_means = [blocks["USMV"]["rv"].mean() * 100 for _ in peer_names]
    fig, ax = plt.subplots(figsize=(8.5, 5))
    x = np.arange(len(peer_names))
    ax.bar(x - 0.18, usmv_means, width=0.36, label="USMV")
    ax.bar(x + 0.18, peer_means, width=0.36, label="Peer")
    ax.set_xticks(x)
    ax.set_xticklabels(peer_names)
    ax.set_ylabel("Block RV mean (%)")
    ax.set_title("K1446 Fig 3 — Non-Overlapping 21-Day Realized Vol")
    ax.legend()
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    path3 = OUT_DIR / "fig3_block_rv_usmv_vs_peers.png"
    fig.savefig(path3, dpi=150)
    plt.close(fig)
    fig_paths.append(path3.name)

    return fig_paths


def main() -> dict:
    prices = fetch_prices()
    returns = {ticker: log_returns(prices[ticker].dropna()) for ticker in TICKERS}

    periods = {
        ticker: {
            "start": ret.index.min().strftime("%Y-%m-%d"),
            "end": ret.index.max().strftime("%Y-%m-%d"),
            "n_obs": int(ret.shape[0]),
        }
        for ticker, ret in returns.items()
    }

    common_returns = pd.concat(returns, axis=1, join="inner").dropna()
    summaries = {ticker: risk_summary(common_returns[ticker]) for ticker in TICKERS}
    blocks = {ticker: block_metrics(common_returns[ticker]) for ticker in TICKERS}

    paired = {}
    usmv_blocks = blocks["USMV"]
    for peer in TICKERS:
        if peer == "USMV":
            continue
        peer_blocks = blocks[peer]
        aligned = usmv_blocks.join(peer_blocks, how="inner", lsuffix="_usmv", rsuffix=f"_{peer.lower()}")
        paired[peer] = {
            "rv": paired_compare(aligned["rv_usmv"], aligned[f"rv_{peer.lower()}"]),
            "downside_dev": paired_compare(
                aligned["downside_dev_usmv"],
                aligned[f"downside_dev_{peer.lower()}"],
            ),
        }

    figures = make_figures(common_returns, summaries, blocks)

    rv_pass = sum(int(paired[peer]["rv"]["passes_bonferroni_0_00625"]) for peer in paired)
    dd_pass = sum(int(paired[peer]["downside_dev"]["passes_bonferroni_0_00625"]) for peer in paired)
    usmv_lowest_ann_vol = min(summaries, key=lambda k: summaries[k].ann_vol_pct) == "USMV"
    usmv_lowest_downside = min(summaries, key=lambda k: summaries[k].downside_dev_pct) == "USMV"

    if usmv_lowest_ann_vol and usmv_lowest_downside and rv_pass >= 3 and dd_pass >= 3:
        verdict = "PASS"
        verdict_reason = "USMV is the lowest-risk asset on full-sample vol/downside metrics and beats at least 3 peers under non-overlapping 21d paired tests."
    elif usmv_lowest_ann_vol or usmv_lowest_downside or rv_pass >= 2 or dd_pass >= 2:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = "USMV looks defensively lower-risk on some but not all metrics/tests; treat as descriptive evidence only."
    else:
        verdict = "NULL"
        verdict_reason = "USMV does not dominate peer factor ETFs on common-sample risk diagnostics once compared fairly."

    result = {
        "experiment_id": "K1446",
        "title": "Factor ETF volatility and downside-risk diagnostics",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "data_source": "yfinance (MTUM, QUAL, USMV, VLUE, SPY)",
        "seed": SEED,
        "sample": {
            "raw_period_per_asset": periods,
            "common_sample_start": common_returns.index.min().strftime("%Y-%m-%d"),
            "common_sample_end": common_returns.index.max().strftime("%Y-%m-%d"),
            "common_sample_n_obs": int(common_returns.shape[0]),
        },
        "method": {
            "type": "descriptive risk comparison",
            "common_sample_only": True,
            "block_design": f"non-overlapping {BLOCK}-trading-day blocks",
            "bootstrap_reps": BOOT_REPS,
            "wilcoxon_alternative": "peer risk > USMV risk",
            "multiple_testing": {
                "n_tests": (len(TICKERS) - 1) * 2,
                "bonferroni_alpha": BONF_ALPHA,
            },
        },
        "full_sample_risk": {ticker: asdict(summary) for ticker, summary in summaries.items()},
        "paired_block_tests_usmv_vs_peer": paired,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "figures": figures,
        "literature_refs": [
            "Blitz & van Vliet (2007) The Volatility Effect",
            "Frazzini & Pedersen (2014) Betting Against Beta",
            "Baker, Bradley & Wurgler (2011) Benchmarks as Limits to Arbitrage",
        ],
        "related_ks": [
            "K89 factor tilts + VT null",
            "K566 factor timing VT null",
            "K876 MTUM crash risk and VIX",
        ],
    }

    out_path = OUT_DIR / "k1446_results.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": verdict_reason, "out": str(out_path)}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
