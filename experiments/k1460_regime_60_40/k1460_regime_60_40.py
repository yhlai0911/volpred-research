from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
SEED = 42
BOOT_REPS = 1000
BLOCK_SIZE = 3
OOS_START = "2022-01-31"


@dataclass
class StrategySpec:
    name: str
    description: str


def load_price(path: str, col: str) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"])
    s = df.set_index("Date")["Close"].rename(col).sort_index()
    return s


def load_term_spread() -> pd.Series:
    d10 = pd.read_csv("storage/macro/fred_DGS10.csv", parse_dates=["date"]).set_index("date")["DGS10"]
    d2 = pd.read_csv("storage/macro/fred_DGS2.csv", parse_dates=["date"]).set_index("date")["DGS2"]
    spread = (d10 - d2).rename("term_spread")
    return spread.sort_index()


def compute_metrics(r: pd.Series) -> dict:
    r = r.dropna()
    nav = (1 + r).cumprod()
    peak = nav.cummax()
    dd = nav / peak - 1
    ann_return = (1 + r.mean()) ** 12 - 1
    ann_vol = r.std(ddof=1) * np.sqrt(12)
    sharpe = np.nan if ann_vol == 0 else ann_return / ann_vol
    return {
        "n_months": int(r.shape[0]),
        "cumulative_return": float(nav.iloc[-1] - 1),
        "annual_return": float(ann_return),
        "annual_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "max_drawdown": float(dd.min()),
    }


def bootstrap_sharpe_diff(a: pd.Series, b: pd.Series, reps: int = BOOT_REPS, block: int = BLOCK_SIZE) -> dict:
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    n = len(df)
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(reps):
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n)
            idx.extend([(start + k) % n for k in range(block)])
        idx = idx[:n]
        sample = df.iloc[idx]
        diffs.append(compute_metrics(sample["a"])["sharpe"] - compute_metrics(sample["b"])["sharpe"])
    diffs = np.array(diffs)
    obs = compute_metrics(df["a"])["sharpe"] - compute_metrics(df["b"])["sharpe"]
    return {
        "observed_sharpe_diff": float(obs),
        "bootstrap_mean": float(diffs.mean()),
        "ci_95": [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))],
        "p_two_sided": float(2 * min((diffs <= 0).mean(), (diffs >= 0).mean())),
        "reps": reps,
        "block_size_months": block,
    }


def main() -> None:
    spy = load_price("experiments/k1090/data/SPY.csv", "SPY")
    tlt = load_price("experiments/k1090/data/TLT.csv", "TLT")
    ief = load_price("experiments/k1090/data/IEF.csv", "IEF")
    prices = pd.concat([spy, tlt, ief], axis=1).dropna()

    daily_ret = prices.pct_change()
    corr_tlt_60d = daily_ret["SPY"].rolling(60).corr(daily_ret["TLT"]).rename("corr_tlt_60d")
    corr_ief_60d = daily_ret["SPY"].rolling(60).corr(daily_ret["IEF"]).rename("corr_ief_60d")

    monthly_prices = prices.resample("ME").last()
    monthly_ret = monthly_prices.pct_change()
    signal = pd.concat([corr_tlt_60d, corr_ief_60d], axis=1).resample("ME").last().shift(1)
    term_spread = load_term_spread().resample("ME").last().reindex(monthly_ret.index)

    df = pd.concat([monthly_ret, signal, term_spread], axis=1).dropna()

    strat = pd.DataFrame(index=df.index)
    strat["static_60_40_tlt"] = 0.6 * df["SPY"] + 0.4 * df["TLT"]
    strat["static_60_40_ief"] = 0.6 * df["SPY"] + 0.4 * df["IEF"]

    pos_corr_tlt = df["corr_tlt_60d"] > 0
    strat["dynamic_weight_tlt"] = np.where(
        pos_corr_tlt,
        0.8 * df["SPY"] + 0.2 * df["TLT"],
        0.6 * df["SPY"] + 0.4 * df["TLT"],
    )
    strat["dynamic_duration"] = np.where(
        pos_corr_tlt,
        0.6 * df["SPY"] + 0.4 * df["IEF"],
        0.6 * df["SPY"] + 0.4 * df["TLT"],
    )
    strat["dynamic_defensive"] = np.where(
        pos_corr_tlt,
        0.4 * df["SPY"] + 0.6 * df["IEF"],
        0.6 * df["SPY"] + 0.4 * df["TLT"],
    )
    strat["spy_bh"] = df["SPY"]

    full_metrics = {k: compute_metrics(strat[k]) for k in strat.columns}
    oos = strat.loc[OOS_START:]
    oos_metrics = {k: compute_metrics(oos[k]) for k in oos.columns}

    best_static = "static_60_40_ief" if oos_metrics["static_60_40_ief"]["sharpe"] >= oos_metrics["static_60_40_tlt"]["sharpe"] else "static_60_40_tlt"
    bootstrap_tests = {
        "dynamic_weight_tlt_vs_best_static": bootstrap_sharpe_diff(oos["dynamic_weight_tlt"], oos[best_static]),
        "dynamic_duration_vs_best_static": bootstrap_sharpe_diff(oos["dynamic_duration"], oos[best_static]),
        "dynamic_defensive_vs_best_static": bootstrap_sharpe_diff(oos["dynamic_defensive"], oos[best_static]),
    }

    regime_diag = {
        "oos_positive_corr_share_tlt": float(pos_corr_tlt.loc[OOS_START:].mean()),
        "oos_negative_corr_share_tlt": float((~pos_corr_tlt.loc[OOS_START:]).mean()),
        "oos_mean_corr_tlt": float(df.loc[OOS_START:, "corr_tlt_60d"].mean()),
        "oos_mean_corr_ief": float(df.loc[OOS_START:, "corr_ief_60d"].mean()),
        "oos_term_spread_positive_corr_mean": float(df.loc[OOS_START:].loc[pos_corr_tlt.loc[OOS_START:], "term_spread"].mean()),
        "oos_term_spread_negative_corr_mean": float(df.loc[OOS_START:].loc[~pos_corr_tlt.loc[OOS_START:], "term_spread"].mean()),
        "n_oos_months": int(len(df.loc[OOS_START:])),
    }

    strategy_specs = [
        StrategySpec("static_60_40_tlt", "60% SPY + 40% TLT, monthly rebalance"),
        StrategySpec("static_60_40_ief", "60% SPY + 40% IEF, monthly rebalance"),
        StrategySpec("dynamic_weight_tlt", "If lagged 60d SPY-TLT corr > 0, use 80/20 SPY/TLT; else keep 60/40"),
        StrategySpec("dynamic_duration", "If lagged 60d SPY-TLT corr > 0, switch bond sleeve from TLT to IEF while keeping 60/40"),
        StrategySpec("dynamic_defensive", "If lagged 60d SPY-TLT corr > 0, de-risk to 40% SPY + 60% IEF; else 60/40 SPY/TLT"),
        StrategySpec("spy_bh", "100% SPY benchmark"),
    ]

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(df.index, df["corr_tlt_60d"], label="SPY-TLT 60d corr")
    axes[0].plot(df.index, df["corr_ief_60d"], label="SPY-IEF 60d corr", alpha=0.7)
    axes[0].axhline(0, color="black", linestyle="--", linewidth=1)
    axes[0].axvline(pd.Timestamp(OOS_START), color="red", linestyle=":", linewidth=1)
    axes[0].set_title("Lagged 60-Day Stock-Bond Correlation")
    axes[0].legend()
    axes[0].grid(alpha=0.25)

    nav = (1 + oos).cumprod()
    for col in ["static_60_40_tlt", "static_60_40_ief", "dynamic_weight_tlt", "dynamic_duration", "dynamic_defensive", "spy_bh"]:
        axes[1].plot(nav.index, nav[col], label=col)
    axes[1].set_title("OOS Cumulative Returns (2022-01 to 2024-12)")
    axes[1].legend(ncol=2, fontsize=8)
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig_path = ROOT / "k1460_corr_and_nav.png"
    fig.savefig(fig_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    results = {
        "experiment_id": "k1460",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "seed": SEED,
        "data_window": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "oos_start": OOS_START,
        },
        "signal_definition": {
            "corr_window_days": 60,
            "rebalance_frequency": "monthly",
            "lag_rule": "signal at month t-1 end applied to month t return",
        },
        "strategy_specs": [s.__dict__ for s in strategy_specs],
        "full_sample_metrics": full_metrics,
        "oos_metrics": oos_metrics,
        "best_static_oos": best_static,
        "bootstrap_tests": bootstrap_tests,
        "regime_diagnostics": regime_diag,
        "figure": fig_path.name,
    }

    out = ROOT / "k1460_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
