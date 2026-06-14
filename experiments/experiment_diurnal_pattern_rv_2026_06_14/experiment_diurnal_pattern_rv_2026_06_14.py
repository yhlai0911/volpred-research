"""Proxy assessment of whether deterministic diurnal seasonality is sufficient
to explain intraday realized-variance variation.

Data:
- Local 5-minute bars from data/intraday/
- SPY: 2026-01-14 to 2026-06-12
- 0050.TW: 2026-01-20 to 2026-06-11

Design:
1. Observation first: estimate train-sample diurnal RV profile by bin-of-day.
2. Test on a chronological holdout split.
3. Measure how much cross-bin variation in log(bar RV) is explained by the
   deterministic profile.
4. Re-test deseasonalized RV with a day-block permutation ANOVA effect-size
   test. If substantial bin effect remains, deterministic diurnal pattern is
   not sufficient.

This is an honest proxy implementation, not a full replication of the
Christensen-Hounyo-Podolskij jump/noise-robust test.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "intraday"
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "experiment_diurnal_pattern_rv_2026_06_14_results.json"
FIG_PROFILE = OUT_DIR / "fig_diurnal_profiles.png"
FIG_DESEASON = OUT_DIR / "fig_deseasonalized_effect.png"

SEED = 42
BOOTSTRAP_N = 1000
TRAIN_FRAC = 0.7
TICKER_CONFIG = {
    "SPY": {"safe_name": "SPY", "expected_bars_hint": 78},
    "0050.TW": {"safe_name": "0050_TW", "expected_bars_hint": 54},
}


@dataclass
class SampleInfo:
    ticker: str
    n_days_total: int
    n_days_train: int
    n_days_test: int
    bars_per_day: int
    start_date: str
    end_date: str


def load_intraday_bars(ticker: str, safe_name: str, expected_bars_hint: int) -> pd.DataFrame:
    files = sorted(DATA_DIR.glob(f"{safe_name}_5min_*.csv"))
    parts: list[pd.DataFrame] = []

    for path in files:
        df = pd.read_csv(path, skiprows=2)
        df.columns = ["Datetime", "Close", "High", "Low", "Open", "Volume"]
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        numeric_cols = ["Close", "High", "Low", "Open", "Volume"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Datetime", "Open", "Close"])
        df["date"] = df["Datetime"].dt.date
        parts.append(df[["Datetime", "Open", "Close", "date"]])

    if not parts:
        raise FileNotFoundError(f"No intraday data found for {ticker}")

    data = pd.concat(parts, ignore_index=True).sort_values("Datetime").reset_index(drop=True)
    counts = data.groupby("date").size()
    # Use the modal count to avoid throwing away almost all Taiwan days when the
    # collector consistently stores 53 bars rather than 54.
    modal_bars = int(counts.mode().iloc[0]) if not counts.empty else expected_bars_hint
    complete_days = counts[counts == modal_bars].index
    data = data[data["date"].isin(complete_days)].copy()
    data["bin_idx"] = data.groupby("date").cumcount()
    data["clock"] = data["Datetime"].dt.strftime("%H:%M")
    data.attrs["bars_per_day"] = modal_bars

    # Within-bar return uses open/close inside the same 5-minute bar.
    data["bar_log_ret"] = np.log(data["Close"] / data["Open"])
    data["bar_rv"] = data["bar_log_ret"] ** 2
    return data


def one_way_eta_squared(values: np.ndarray, groups: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    grand_mean = float(values.mean())
    total_ss = float(((values - grand_mean) ** 2).sum())
    if total_ss <= 0:
        return 0.0

    between_ss = 0.0
    for group in np.unique(groups):
        mask = groups == group
        group_vals = values[mask]
        between_ss += len(group_vals) * float((group_vals.mean() - grand_mean) ** 2)
    return between_ss / total_ss


def day_block_permutation_eta(df: pd.DataFrame, value_col: str, seed: int, n_boot: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    observed = one_way_eta_squared(df[value_col].to_numpy(), df["bin_idx"].to_numpy())
    null_stats = np.empty(n_boot)
    grouped = [g.copy() for _, g in df.groupby("date", sort=False)]

    for i in range(n_boot):
        permuted_vals: list[float] = []
        permuted_groups: list[int] = []
        for block in grouped:
            permuted_groups.extend(rng.permutation(block["bin_idx"].to_numpy()))
            permuted_vals.extend(block[value_col].to_numpy())
        null_stats[i] = one_way_eta_squared(np.asarray(permuted_vals), np.asarray(permuted_groups))

    p_value = float((np.sum(null_stats >= observed) + 1) / (n_boot + 1))
    return observed, p_value


def compute_daily_share_r2(test_df: pd.DataFrame, expected_share: np.ndarray) -> dict[str, float]:
    uniform_share = np.full_like(expected_share, 1.0 / len(expected_share))
    day_r2 = []

    for _, day in test_df.groupby("date", sort=False):
        actual = day.sort_values("bin_idx")["bar_rv"].to_numpy()
        total = actual.sum()
        if total <= 0:
            continue
        actual_share = actual / total
        sse_model = float(((actual_share - expected_share) ** 2).sum())
        sse_uniform = float(((actual_share - uniform_share) ** 2).sum())
        if sse_uniform <= 0:
            continue
        day_r2.append(1.0 - sse_model / sse_uniform)

    day_r2 = np.asarray(day_r2)
    if day_r2.size == 0:
        return {
            "mean": None,
            "median": None,
            "positive_ratio": None,
            "n_days": 0,
        }
    return {
        "mean": float(day_r2.mean()),
        "median": float(np.median(day_r2)),
        "positive_ratio": float((day_r2 > 0).mean()),
        "n_days": int(day_r2.size),
    }


def evaluate_ticker(ticker: str, data: pd.DataFrame, seed_offset: int) -> dict:
    unique_days = np.array(sorted(data["date"].unique()))
    split_idx = max(20, int(len(unique_days) * TRAIN_FRAC))
    split_idx = min(split_idx, max(len(unique_days) - 10, 1))
    train_days = unique_days[:split_idx]
    test_days = unique_days[split_idx:]

    train_df = data[data["date"].isin(train_days)].copy()
    test_df = data[data["date"].isin(test_days)].copy()

    seasonal_profile = train_df.groupby("bin_idx")["bar_rv"].mean().sort_index()
    seasonal_share = (seasonal_profile / seasonal_profile.sum()).to_numpy()
    seasonal_factor = seasonal_profile / seasonal_profile.mean()

    eps = max(float(train_df["bar_rv"].median()) * 1e-3, 1e-12)
    test_df["seasonal_factor"] = test_df["bin_idx"].map(seasonal_factor)
    test_df["log_rv_raw"] = np.log(test_df["bar_rv"] + eps)
    test_df["log_rv_adj"] = np.log(test_df["bar_rv"] / test_df["seasonal_factor"] + eps)

    eta_raw, p_raw = day_block_permutation_eta(test_df, "log_rv_raw", SEED + seed_offset, BOOTSTRAP_N)
    eta_adj, p_adj = day_block_permutation_eta(test_df, "log_rv_adj", SEED + 100 + seed_offset, BOOTSTRAP_N)

    share_r2 = compute_daily_share_r2(test_df, seasonal_share)
    removal_ratio = 1.0 - (eta_adj / eta_raw) if eta_raw > 0 else 0.0

    raw_bin_mean = test_df.groupby("bin_idx")["bar_rv"].mean().to_numpy()
    adj_bin_mean = test_df.groupby("bin_idx").apply(
        lambda x: (x["bar_rv"] / x["seasonal_factor"]).mean()
    ).to_numpy()

    verdict = "rejected"
    if len(test_days) < 10:
        verdict = "insufficient_data"
    elif p_adj >= 0.05 or eta_adj <= 0.01:
        verdict = "not_rejected"

    sample = SampleInfo(
        ticker=ticker,
        n_days_total=int(len(unique_days)),
        n_days_train=int(len(train_days)),
        n_days_test=int(len(test_days)),
        bars_per_day=int(data.attrs.get("bars_per_day", data.groupby("date").size().iloc[0])),
        start_date=str(unique_days[0]),
        end_date=str(unique_days[-1]),
    )

    return {
        "sample": asdict(sample),
        "seasonal_share_by_bin": seasonal_share.tolist(),
        "clock_by_bin": train_df.groupby("bin_idx")["clock"].first().sort_index().tolist(),
        "test_metrics": {
            "raw_eta_sq": float(eta_raw),
            "raw_p_value": float(p_raw),
            "deseasonalized_eta_sq": float(eta_adj),
            "deseasonalized_p_value": float(p_adj),
            "eta_reduction_ratio": float(removal_ratio),
            "daily_share_r2_vs_uniform": share_r2,
        },
        "test_bin_means": {
            "raw_bar_rv_mean": raw_bin_mean.tolist(),
            "deseasonalized_bar_rv_mean": adj_bin_mean.tolist(),
        },
        "verdict": verdict,
    }


def plot_profiles(results: dict[str, dict]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)

    for ax, ticker in zip(axes, results):
        res = results[ticker]
        x = np.arange(len(res["clock_by_bin"]))
        ax.plot(x, res["seasonal_share_by_bin"], label=f"{ticker} train diurnal share", linewidth=2)
        ax.set_title(f"{ticker} intraday RV share profile")
        ax.set_xlabel("Bin of day")
        ax.set_ylabel("Share of daily RV")
        xticks = np.linspace(0, len(x) - 1, num=min(8, len(x)), dtype=int)
        ax.set_xticks(xticks)
        ax.set_xticklabels([res["clock_by_bin"][i] for i in xticks], rotation=30, ha="right")
        ax.grid(alpha=0.3)
        ax.legend()

    fig.suptitle("Train-sample deterministic diurnal profiles", fontsize=14)
    fig.savefig(FIG_PROFILE, dpi=150)
    plt.close(fig)


def plot_deseasonalized_effect(results: dict[str, dict]) -> None:
    tickers = list(results)
    raw = [results[t]["test_metrics"]["raw_eta_sq"] for t in tickers]
    adj = [results[t]["test_metrics"]["deseasonalized_eta_sq"] for t in tickers]
    reduction = [results[t]["test_metrics"]["eta_reduction_ratio"] for t in tickers]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    x = np.arange(len(tickers))
    width = 0.35

    axes[0].bar(x - width / 2, raw, width, label="raw")
    axes[0].bar(x + width / 2, adj, width, label="deseasonalized")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(tickers)
    axes[0].set_ylabel("Eta-squared by bin")
    axes[0].set_title("Cross-bin effect size before/after deseasonalization")
    axes[0].legend()
    axes[0].grid(axis="y", alpha=0.3)

    axes[1].bar(x, reduction)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(tickers)
    axes[1].set_ylim(0, 1)
    axes[1].set_ylabel("Fraction of bin effect removed")
    axes[1].set_title("How much deterministic seasonality removes")
    axes[1].grid(axis="y", alpha=0.3)

    fig.savefig(FIG_DESEASON, dpi=150)
    plt.close(fig)


def main() -> None:
    ticker_results: dict[str, dict] = {}
    for idx, (ticker, cfg) in enumerate(TICKER_CONFIG.items()):
        data = load_intraday_bars(ticker, cfg["safe_name"], cfg["expected_bars_hint"])
        ticker_results[ticker] = evaluate_ticker(ticker, data, idx)

    plot_profiles(ticker_results)
    plot_deseasonalized_effect(ticker_results)

    verdict_summary = {
        ticker: res["verdict"] for ticker, res in ticker_results.items()
    }

    output = {
        "experiment_id": "experiment_diurnal_pattern_rv_2026_06_14",
        "title": "Diurnal pattern sufficiency proxy assessment on local 5-minute data",
        "date": "2026-06-14",
        "seed": SEED,
        "bootstrap_n": BOOTSTRAP_N,
        "methodology": {
            "design": "chronological train/test split with day-block permutation eta-squared test",
            "null": "deterministic bin-of-day diurnal profile is sufficient to explain cross-bin intraday RV variation",
            "proxy_note": "Not a full Christensen-Hounyo-Podolskij noise/jump-robust semimartingale test; this is a local 5-minute proxy assessment.",
        },
        "tickers": ticker_results,
        "overall_verdict": verdict_summary,
        "artifacts": {
            "profile_figure": str(FIG_PROFILE.relative_to(ROOT)),
            "deseasonalized_figure": str(FIG_DESEASON.relative_to(ROOT)),
        },
    }

    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output["overall_verdict"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
