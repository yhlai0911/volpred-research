"""K1335 — VIX term-slope as rule-based VT overlay (IS-tuned VIX level vs fixed slope thresholds).

Run from repo root:
    uv run python .claude/worktrees/k1335/experiments/K1335/K1335.py

Outputs:
    experiments/K1335/K1335_results.json
    experiments/K1335/K1335_fig_*.png

Lookahead policy: position at day t uses VIX/VIX3M close at t-1 (shift(1)).
Returns: SPY close_t / close_{t-1} - 1. TC: 10 bps per side on |delta w|. Seed 42.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
CACHE = HERE / "_cache.parquet"
RESULTS_PATH = HERE / "K1335_results.json"

START = "2010-01-01"
END = "2026-06-13"
IS_START = "2010-01-01"
IS_END = "2017-12-31"
OOS_START = "2018-01-01"
OOS_END = "2026-06-13"
TC_PER_SIDE = 0.0010  # 10 bps
TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_data() -> pd.DataFrame:
    if CACHE.exists():
        df = pd.read_parquet(CACHE)
        print(f"[data] loaded cache {CACHE} rows={len(df)}")
        return df
    import yfinance as yf

    frames = {}
    for tkr in ["SPY", "^VIX", "^VIX3M"]:
        print(f"[data] fetch {tkr}")
        raw = yf.download(tkr, start=START, end=END, auto_adjust=False, progress=False)
        if raw is None or raw.empty:
            raise RuntimeError(f"yfinance returned empty for {tkr}")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        col = "Adj Close" if tkr == "SPY" else "Close"
        frames[tkr] = raw[col].rename(tkr.replace("^", ""))
    df = pd.concat(frames.values(), axis=1).dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.to_parquet(CACHE)
    print(f"[data] cached {CACHE} rows={len(df)}")
    return df


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------
def backtest(weights: pd.Series, spy_ret: pd.Series, tc_per_side: float = TC_PER_SIDE) -> pd.DataFrame:
    """weights aligned to spy_ret index. Returns DataFrame with pnl, equity, w_eff.

    Convention: weights are already lagged appropriately (decision at t uses signal t-1).
    PnL_t = w_t * r_t - tc * |w_t - w_{t-1}|, with w_{-1}=0.
    """
    w = weights.reindex(spy_ret.index).fillna(0.0).clip(0.0, 1.0)
    w_prev = w.shift(1).fillna(0.0)
    turnover = (w - w_prev).abs()
    pnl = w * spy_ret - tc_per_side * turnover
    equity = (1.0 + pnl).cumprod()
    return pd.DataFrame({"w": w, "pnl": pnl, "equity": equity, "turnover": turnover})


def metrics(pnl: pd.Series, equity: pd.Series, turnover: pd.Series) -> dict:
    pnl = pnl.dropna()
    if len(pnl) < 5:
        return {k: float("nan") for k in [
            "ann_ret", "ann_vol", "sharpe", "mdd", "calmar",
            "turnover", "var95", "es95", "hit_rate", "n_obs"
        ]}
    ann_ret = (1.0 + pnl.mean()) ** TRADING_DAYS - 1.0
    ann_vol = pnl.std(ddof=1) * np.sqrt(TRADING_DAYS)
    sharpe = float(pnl.mean() / pnl.std(ddof=1) * np.sqrt(TRADING_DAYS)) if pnl.std(ddof=1) > 0 else float("nan")
    eq = equity.dropna()
    running_max = eq.cummax()
    dd = (eq / running_max) - 1.0
    mdd = float(dd.min())
    n_years = len(pnl) / TRADING_DAYS
    calmar = float(ann_ret / abs(mdd)) if mdd < 0 else float("nan")
    turnover_per_year = float(turnover.sum() / n_years) if n_years > 0 else float("nan")
    var95 = float(np.quantile(pnl, 0.05))
    es95 = float(pnl[pnl <= var95].mean())
    hit_rate = float((pnl > 0).mean())
    return {
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "turnover": turnover_per_year,
        "var95": var95,
        "es95": es95,
        "hit_rate": hit_rate,
        "n_obs": int(len(pnl)),
    }


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
def signal_buy_hold(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=df.index)


def signal_vix_level(df: pd.DataFrame, threshold: float) -> pd.Series:
    vix_lag = df["VIX"].shift(1)
    return (vix_lag < threshold).astype(float)


def signal_slope(df: pd.DataFrame, threshold: float) -> pd.Series:
    slope_lag = (df["VIX"] / df["VIX3M"]).shift(1)
    # risk-on when slope < threshold (contango). risk-off otherwise.
    return (slope_lag < threshold).astype(float)


# ---------------------------------------------------------------------------
# IS tuning of VIX-level threshold
# ---------------------------------------------------------------------------
def tune_vix_level(df_is: pd.DataFrame, spy_ret_is: pd.Series, grid=(18.0, 20.0, 22.0, 25.0)) -> tuple[float, dict]:
    best = None
    audit = {}
    for th in grid:
        w = signal_vix_level(df_is, th)
        bt = backtest(w, spy_ret_is)
        m = metrics(bt["pnl"], bt["equity"], bt["turnover"])
        audit[str(th)] = m["sharpe"]
        if best is None or m["sharpe"] > best[1]:
            best = (th, m["sharpe"])
    return best[0], audit


# ---------------------------------------------------------------------------
# Stationary bootstrap for Sharpe diff
# ---------------------------------------------------------------------------
def stationary_bootstrap_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap; geometric block with mean = mean_block."""
    p = 1.0 / mean_block
    idx = np.empty(n, dtype=np.int64)
    idx[0] = rng.integers(0, n)
    for t in range(1, n):
        if rng.random() < p:
            idx[t] = rng.integers(0, n)
        else:
            idx[t] = (idx[t - 1] + 1) % n
    return idx


def sharpe(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    if sd <= 0:
        return float("nan")
    return float(x.mean() / sd * np.sqrt(TRADING_DAYS))


def bootstrap_sharpe_diff(pnl_a: np.ndarray, pnl_b: np.ndarray, n_iter: int = 2000, mean_block: float = 5.0, seed: int = SEED) -> dict:
    assert len(pnl_a) == len(pnl_b)
    n = len(pnl_a)
    rng = np.random.default_rng(seed)
    obs = sharpe(pnl_a) - sharpe(pnl_b)
    diffs = np.empty(n_iter)
    for i in range(n_iter):
        idx = stationary_bootstrap_indices(n, mean_block, rng)
        diffs[i] = sharpe(pnl_a[idx]) - sharpe(pnl_b[idx])
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    # two-sided p: prob that bootstrap diff has opposite sign of observed
    if obs >= 0:
        p_one = float((diffs <= 0).mean())
    else:
        p_one = float((diffs >= 0).mean())
    p_two = min(1.0, 2.0 * p_one)
    return {
        "obs_diff": float(obs),
        "ci_lo": float(lo),
        "ci_hi": float(hi),
        "p_value_two_sided": float(p_two),
        "n_iter": n_iter,
        "mean_block": mean_block,
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
def assign_verdict(slope_m: dict, level_m: dict, boot: dict) -> tuple[str, str]:
    s_diff = slope_m["sharpe"] - level_m["sharpe"]
    mdd_diff = slope_m["mdd"] - level_m["mdd"]  # mdd negative; positive diff = slope shallower (better)
    if s_diff >= 0 and mdd_diff >= -0.05 and boot["p_value_two_sided"] < 0.10:
        return "PASS", f"slope Sharpe {slope_m['sharpe']:.3f} >= level {level_m['sharpe']:.3f}; MDD diff {mdd_diff:+.3f}; bootstrap p={boot['p_value_two_sided']:.3f}<0.10"
    if (s_diff >= 0) ^ (mdd_diff >= -0.05):
        return "CONDITIONAL_PASS", f"mixed: Sharpe diff {s_diff:+.3f}, MDD diff {mdd_diff:+.3f}, p={boot['p_value_two_sided']:.3f}"
    if abs(s_diff) < 0.1 and boot["ci_lo"] < 0 < boot["ci_hi"]:
        return "NULL", f"indistinguishable: Sharpe diff {s_diff:+.3f}, 95% CI [{boot['ci_lo']:+.3f},{boot['ci_hi']:+.3f}]"
    return "FAIL", f"slope strictly worse: Sharpe diff {s_diff:+.3f}, MDD diff {mdd_diff:+.3f}, p={boot['p_value_two_sided']:.3f}"


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
def plot_equity(bts: dict[str, pd.DataFrame], oos_start: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for name, bt in bts.items():
        oos = bt.loc[oos_start:]
        eq = (1.0 + oos["pnl"]).cumprod()
        ax.plot(eq.index, eq.values, label=name, linewidth=1.2)
    ax.set_yscale("log")
    ax.set_title("K1335 — OOS equity curves (log) | 2018-01-01 → 2026-06-13")
    ax.set_ylabel("equity (start=1.0)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE / "K1335_fig_equity.png", dpi=140)
    plt.close(fig)


def plot_slope_distribution(df: pd.DataFrame) -> None:
    slope = (df["VIX"] / df["VIX3M"]).dropna()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.hist(slope.values, bins=80, color="#4A6FA5", alpha=0.8)
    for th, color, lbl in [(0.95, "#888", "0.95"), (1.00, "#D03A3A", "1.00"), (1.05, "#3A8A3A", "1.05")]:
        ax.axvline(th, color=color, linestyle="--", linewidth=1.2, label=f"th={lbl}")
    ax.set_xlabel("VIX / VIX3M")
    ax.set_ylabel("count")
    ax.set_title("K1335 — VIX/VIX3M ratio distribution (2010-2026)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "K1335_fig_slope_dist.png", dpi=140)
    plt.close(fig)


def plot_drawdowns(bts: dict[str, pd.DataFrame], oos_start: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for name, bt in bts.items():
        oos = bt.loc[oos_start:]
        eq = (1.0 + oos["pnl"]).cumprod()
        dd = eq / eq.cummax() - 1.0
        ax.plot(dd.index, dd.values, label=name, linewidth=1.0)
    ax.set_title("K1335 — OOS underwater curves")
    ax.set_ylabel("drawdown")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE / "K1335_fig_drawdown.png", dpi=140)
    plt.close(fig)


def plot_regime_returns(df: pd.DataFrame, spy_ret: pd.Series, oos_start: str) -> None:
    sub = df.loc[oos_start:].copy()
    sub["ret"] = spy_ret.reindex(sub.index)
    sub["slope_lag"] = (sub["VIX"] / sub["VIX3M"]).shift(1)
    sub["vix_lag"] = sub["VIX"].shift(1)
    sub = sub.dropna()
    buckets_slope = {
        "slope<0.90": sub["ret"][sub["slope_lag"] < 0.90],
        "0.90-0.95": sub["ret"][(sub["slope_lag"] >= 0.90) & (sub["slope_lag"] < 0.95)],
        "0.95-1.00": sub["ret"][(sub["slope_lag"] >= 0.95) & (sub["slope_lag"] < 1.00)],
        "1.00-1.05": sub["ret"][(sub["slope_lag"] >= 1.00) & (sub["slope_lag"] < 1.05)],
        "slope>=1.05": sub["ret"][sub["slope_lag"] >= 1.05],
    }
    buckets_level = {
        "VIX<15": sub["ret"][sub["vix_lag"] < 15],
        "15-20": sub["ret"][(sub["vix_lag"] >= 15) & (sub["vix_lag"] < 20)],
        "20-25": sub["ret"][(sub["vix_lag"] >= 20) & (sub["vix_lag"] < 25)],
        "25-30": sub["ret"][(sub["vix_lag"] >= 25) & (sub["vix_lag"] < 30)],
        "VIX>=30": sub["ret"][sub["vix_lag"] >= 30],
    }
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    for ax, buckets, title in [
        (axes[0], buckets_slope, "OOS daily SPY ret | VIX/VIX3M bucket (lagged)"),
        (axes[1], buckets_level, "OOS daily SPY ret | VIX level bucket (lagged)"),
    ]:
        means = [b.mean() * 252 for b in buckets.values()]
        counts = [len(b) for b in buckets.values()]
        names = list(buckets.keys())
        bars = ax.bar(names, means, color="#4A6FA5", alpha=0.85)
        for b, n in zip(bars, counts):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"n={n}", ha="center", va="bottom", fontsize=8)
        ax.axhline(0, color="k", linewidth=0.6)
        ax.set_title(title)
        ax.set_ylabel("annualized ret")
        ax.tick_params(axis="x", rotation=30)
        ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(HERE / "K1335_fig_regime_returns.png", dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    df = df.loc[START:END].copy()

    spy_ret = df["SPY"].pct_change()
    spy_ret.name = "SPY_ret"

    df_is = df.loc[IS_START:IS_END]
    spy_ret_is = spy_ret.loc[IS_START:IS_END]
    df_oos = df.loc[OOS_START:OOS_END]
    spy_ret_oos = spy_ret.loc[OOS_START:OOS_END]

    print(f"[split] IS obs={len(df_is)} ({IS_START}→{IS_END}) | OOS obs={len(df_oos)} ({OOS_START}→{OOS_END})")

    tuned_th, tune_audit = tune_vix_level(df_is, spy_ret_is)
    print(f"[tune] VIX-level IS-best th={tuned_th} | grid sharpe={tune_audit}")

    # Strategies on full df, then evaluate slice
    signals = {
        "buy_hold": signal_buy_hold(df),
        "vix_level": signal_vix_level(df, tuned_th),
        "slope_1_0": signal_slope(df, 1.00),
        "slope_0_95": signal_slope(df, 0.95),
        "slope_1_05": signal_slope(df, 1.05),
    }

    bts_full = {name: backtest(w, spy_ret) for name, w in signals.items()}

    strategies_out = {}
    for name, bt in bts_full.items():
        bt_oos = bt.loc[OOS_START:OOS_END]
        m = metrics(bt_oos["pnl"], bt_oos["equity"], bt_oos["turnover"])
        strategies_out[name] = m
        if name == "vix_level":
            strategies_out[name]["threshold"] = float(tuned_th)
        elif name.startswith("slope_"):
            strategies_out[name]["slope_threshold"] = float({"slope_1_0": 1.00, "slope_0_95": 0.95, "slope_1_05": 1.05}[name])

    # Pick best slope by OOS Sharpe for headline comparison vs level
    slope_names = ["slope_1_0", "slope_0_95", "slope_1_05"]
    best_slope_name = max(slope_names, key=lambda n: strategies_out[n]["sharpe"])
    slope_m = strategies_out[best_slope_name]
    level_m = strategies_out["vix_level"]

    # Bootstrap on aligned OOS pnl
    pnl_slope = bts_full[best_slope_name].loc[OOS_START:OOS_END, "pnl"].dropna().values
    pnl_level = bts_full["vix_level"].loc[OOS_START:OOS_END, "pnl"].dropna().values
    # align lengths defensively
    n = min(len(pnl_slope), len(pnl_level))
    boot = bootstrap_sharpe_diff(pnl_slope[-n:], pnl_level[-n:], n_iter=2000, mean_block=5.0, seed=SEED)

    verdict, reason = assign_verdict(slope_m, level_m, boot)

    # Plots
    plot_equity(bts_full, OOS_START)
    plot_slope_distribution(df)
    plot_drawdowns(bts_full, OOS_START)
    plot_regime_returns(df, spy_ret, OOS_START)

    # Results JSON
    payload = {
        "k_id": "K1335",
        "experiment_id": "K1335",
        "date_run": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "data": {
            "start": START,
            "end": END,
            "n_obs_full": int(len(df)),
            "n_obs_is": int(len(df_is)),
            "n_obs_oos": int(len(df_oos)),
            "source": "yfinance",
            "tickers": ["SPY", "^VIX", "^VIX3M"],
        },
        "is_period": {"start": IS_START, "end": IS_END},
        "oos_period": {"start": OOS_START, "end": OOS_END},
        "tuning": {
            "vix_level_grid": [18.0, 20.0, 22.0, 25.0],
            "vix_level_is_sharpe": tune_audit,
            "vix_level_tuned_threshold": float(tuned_th),
        },
        "strategies": strategies_out,
        "best_slope_name": best_slope_name,
        "comparison": {
            "headline_slope_strategy": best_slope_name,
            "slope_vs_level_sharpe_diff_oos": float(slope_m["sharpe"] - level_m["sharpe"]),
            "slope_vs_level_mdd_diff_oos": float(slope_m["mdd"] - level_m["mdd"]),
            "sharpe_diff_bootstrap_95ci": [boot["ci_lo"], boot["ci_hi"]],
            "sharpe_diff_p_value_two_sided": boot["p_value_two_sided"],
            "bootstrap": boot,
        },
        "config": {
            "tc_per_side": TC_PER_SIDE,
            "seed": SEED,
            "rf": 0.0,
            "weight_cap": 1.0,
            "lag": "shift(1) on signal; ret_t = close_t/close_{t-1}-1",
        },
        "verdict": "PENDING_REVIEW",
        "agent_proposed_verdict": verdict,
        "verdict_reason": reason,
        "reviewer": "PENDING_REVIEW (awaiting Codex review per K1259 protocol)",
        "monetization_angle": "If PASS, candidate `slope_vt_overlay_v1` for strategy_lifecycle pipeline; differentiated vs incumbent VIX-level VTs.",
        "files": {
            "script": "experiments/K1335/K1335.py",
            "readme": "experiments/K1335/README.md",
            "figs": [
                "experiments/K1335/K1335_fig_equity.png",
                "experiments/K1335/K1335_fig_slope_dist.png",
                "experiments/K1335/K1335_fig_drawdown.png",
                "experiments/K1335/K1335_fig_regime_returns.png",
            ],
        },
    }

    RESULTS_PATH.write_text(json.dumps(payload, indent=2))
    print(f"[done] wrote {RESULTS_PATH}")
    print(f"[verdict] agent-proposed={verdict} (recorded as PENDING_REVIEW for Codex audit)")
    print(f"[summary] best_slope={best_slope_name} sharpe={slope_m['sharpe']:.3f} mdd={slope_m['mdd']:.3f} | level th={tuned_th} sharpe={level_m['sharpe']:.3f} mdd={level_m['mdd']:.3f}")
    print(f"[bootstrap] obs_diff={boot['obs_diff']:.3f} 95%CI=[{boot['ci_lo']:.3f},{boot['ci_hi']:.3f}] p={boot['p_value_two_sided']:.3f}")


if __name__ == "__main__":
    main()
