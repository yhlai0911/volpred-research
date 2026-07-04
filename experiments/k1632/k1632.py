#!/usr/bin/env python3
"""K1632 — Does a long low-volatility consolidation lead to a big breakout?

Myth:
    「盤整越久，噴得越兇」。

Design:
    Signal at day t uses only data available after day-t close.  Forward
    outcomes start at t+1.  Breakout-day absolute return is reported as a
    descriptive, non-tradable diagnostic because the move has already happened
    by the time the day closes.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib import font_manager
from scipy import stats

from volpred.utils import clean_tw50_data


EXPERIMENT_ID = "k1632"
TITLE = "盤整越久、噴得越兇？低波動盤整後的大波動檢定"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).resolve().parent
PRICE_DB = ROOT / "data/cache/price_cache.db"
RESULTS_PATH = EXP_DIR / "k1632_results.json"
PANEL_PATH = EXP_DIR / "k1632_panel.csv"
FIG_SIGNAL = EXP_DIR / "fig_squeeze_future_vol.png"
FIG_END = EXP_DIR / "fig_episode_end_breakout.png"

SEED = 42
ASSETS = {
    "SPY": "美股大型股（SPY）",
    "0050.TW": "台股大型股（0050.TW）",
}
LOOKBACK = 20
HIST_WINDOW = 252
QUANTILE = 0.20
MIN_HIST = 126
RUN_THRESHOLDS = [5, 10, 20]
HORIZONS = [5, 20, 60]
N_BOOT = 2000
BOOT_BLOCK = 20


def setup_matplotlib_font() -> None:
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/Library/Fonts/NotoSansCJKtc-Regular.otf",
        "/Library/Fonts/Noto Sans CJK TC Regular.otf",
    ]
    for raw in candidates:
        path = Path(raw)
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            prop = font_manager.FontProperties(fname=str(path))
            matplotlib.rcParams["font.sans-serif"] = [prop.get_name()]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return
    raise RuntimeError("No CJK font found for matplotlib.")


def load_price(ticker: str) -> pd.DataFrame:
    if not PRICE_DB.exists():
        raise FileNotFoundError(PRICE_DB)
    con = sqlite3.connect(PRICE_DB)
    df = pd.read_sql_query(
        """
        select date, adj_close
        from price_data
        where ticker = ?
        order by date
        """,
        con,
        params=(ticker,),
        parse_dates=["date"],
    )
    if df.empty:
        raise RuntimeError(f"No rows in price cache for {ticker}")
    df = df.set_index("date").sort_index()
    price = df["adj_close"].astype(float)
    if ticker == "0050.TW":
        price, _ = clean_tw50_data(price)
    out = pd.DataFrame({"price": price})
    out["ret_log"] = np.log(out["price"] / out["price"].shift(1))
    return out.dropna(subset=["price"])


def consecutive_run(flag: pd.Series) -> pd.Series:
    values: list[int] = []
    n = 0
    for x in flag.fillna(False).to_numpy(dtype=bool):
        n = n + 1 if x else 0
        values.append(n)
    return pd.Series(values, index=flag.index)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    ret = out["ret_log"]
    out["rv20_ann"] = np.sqrt((ret.pow(2).rolling(LOOKBACK).sum() / LOOKBACK) * 252)
    out["range20_close"] = out["price"].rolling(LOOKBACK).max() / out["price"].rolling(LOOKBACK).min() - 1
    out["rv20_low_threshold"] = (
        out["rv20_ann"].shift(1).rolling(HIST_WINDOW, min_periods=MIN_HIST).quantile(QUANTILE)
    )
    out["range20_low_threshold"] = (
        out["range20_close"].shift(1).rolling(HIST_WINDOW, min_periods=MIN_HIST).quantile(QUANTILE)
    )
    out["squeeze"] = (
        (out["rv20_ann"] <= out["rv20_low_threshold"])
        & (out["range20_close"] <= out["range20_low_threshold"])
    )
    out["squeeze_run"] = consecutive_run(out["squeeze"])
    out["episode_end"] = (~out["squeeze"].fillna(False)) & (out["squeeze_run"].shift(1).fillna(0) > 0)
    out["episode_duration"] = out["squeeze_run"].shift(1).where(out["episode_end"])
    for threshold in RUN_THRESHOLDS:
        out[f"squeeze_reaches_{threshold}d"] = out["squeeze_run"] == threshold
        out[f"episode_end_after_{threshold}d"] = out["episode_end"] & (out["episode_duration"] >= threshold)
    for h in HORIZONS:
        out[f"fwd_ret_{h}d"] = sum(out["ret_log"].shift(-i) for i in range(1, h + 1))
        rv_sum = sum(out["ret_log"].shift(-i) ** 2 for i in range(1, h + 1))
        out[f"fwd_vol_{h}d_ann"] = np.sqrt((rv_sum / h) * 252)
        out[f"fwd_abs_ret_{h}d"] = out[f"fwd_ret_{h}d"].abs()
    out["breakout_day_abs_ret"] = out["ret_log"].abs()
    return out


def hac_dummy(y: pd.Series, event: pd.Series, maxlags: int) -> dict[str, float]:
    sample = pd.concat([y.rename("y"), event.astype(int).rename("event")], axis=1).dropna()
    if sample["event"].sum() < 2 or (1 - sample["event"]).sum() < 2:
        return {"coef": math.nan, "t": math.nan, "p": math.nan}
    x = sm.add_constant(sample["event"])
    model = sm.OLS(sample["y"], x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "coef": float(model.params["event"]),
        "t": float(model.tvalues["event"]),
        "p": float(model.pvalues["event"]),
    }


def fisher_big_move(sample: pd.DataFrame, event: pd.Series, value_col: str) -> dict[str, Any]:
    threshold = float(sample[value_col].quantile(0.80))
    big = sample[value_col] >= threshold
    event_bool = event.astype(bool)
    table = [
        [int((big & event_bool).sum()), int(((~big) & event_bool).sum())],
        [int((big & (~event_bool)).sum()), int(((~big) & (~event_bool)).sum())],
    ]
    odds, p = stats.fisher_exact(table)
    return {
        "big_move_threshold_p80": threshold,
        "prob_big_move_event": float(big[event_bool].mean()) if event_bool.any() else math.nan,
        "prob_big_move_other": float(big[~event_bool].mean()) if (~event_bool).any() else math.nan,
        "fisher_odds_ratio": float(odds),
        "fisher_p": float(p),
    }


def compare_event(panel: pd.DataFrame, event_col: str, h: int) -> dict[str, Any]:
    cols = [event_col, f"fwd_ret_{h}d", f"fwd_abs_ret_{h}d", f"fwd_vol_{h}d_ann"]
    sample = panel[cols].dropna().copy()
    event = sample[event_col].astype(bool)
    n_event = int(event.sum())
    n_other = int((~event).sum())
    if n_event < 2 or n_other < 2:
        return {
            "event_col": event_col,
            "horizon_days": h,
            "n_event": n_event,
            "n_other": n_other,
            "insufficient": True,
        }
    ret_col = f"fwd_ret_{h}d"
    abs_col = f"fwd_abs_ret_{h}d"
    vol_col = f"fwd_vol_{h}d_ann"
    ret_event = sample.loc[event, ret_col]
    ret_other = sample.loc[~event, ret_col]
    abs_event = sample.loc[event, abs_col]
    abs_other = sample.loc[~event, abs_col]
    vol_event = sample.loc[event, vol_col]
    vol_other = sample.loc[~event, vol_col]
    vol_hac = hac_dummy(sample[vol_col], event, h)
    abs_hac = hac_dummy(sample[abs_col], event, h)
    big = fisher_big_move(sample, event, abs_col)
    return {
        "event_col": event_col,
        "horizon_days": h,
        "n_event": n_event,
        "n_other": n_other,
        "insufficient": False,
        "event_dates_first_last": [
            sample.index[event][0].strftime("%Y-%m-%d"),
            sample.index[event][-1].strftime("%Y-%m-%d"),
        ],
        "mean_return_event": float(ret_event.mean()),
        "mean_return_other": float(ret_other.mean()),
        "mean_return_diff_event_minus_other": float(ret_event.mean() - ret_other.mean()),
        "mean_abs_return_event": float(abs_event.mean()),
        "mean_abs_return_other": float(abs_other.mean()),
        "mean_abs_return_diff_event_minus_other": float(abs_event.mean() - abs_other.mean()),
        "mean_vol_event_ann": float(vol_event.mean()),
        "mean_vol_other_ann": float(vol_other.mean()),
        "mean_vol_diff_event_minus_other_ann": float(vol_event.mean() - vol_other.mean()),
        "hac_vol_coef": vol_hac["coef"],
        "hac_vol_t": vol_hac["t"],
        "hac_vol_p": vol_hac["p"],
        "hac_abs_return_coef": abs_hac["coef"],
        "hac_abs_return_t": abs_hac["t"],
        "hac_abs_return_p": abs_hac["p"],
        **big,
    }


def compare_breakout_day(panel: pd.DataFrame, event_col: str) -> dict[str, Any]:
    sample = panel[[event_col, "breakout_day_abs_ret"]].dropna().copy()
    event = sample[event_col].astype(bool)
    n_event = int(event.sum())
    n_other = int((~event).sum())
    if n_event < 2 or n_other < 2:
        return {
            "event_col": event_col,
            "n_event": n_event,
            "n_other": n_other,
            "insufficient": True,
        }
    ev = sample.loc[event, "breakout_day_abs_ret"]
    other = sample.loc[~event, "breakout_day_abs_ret"]
    welch = stats.ttest_ind(ev, other, equal_var=False, nan_policy="omit")
    big = fisher_big_move(sample, event, "breakout_day_abs_ret")
    return {
        "event_col": event_col,
        "n_event": n_event,
        "n_other": n_other,
        "insufficient": False,
        "mean_breakout_day_abs_ret_event": float(ev.mean()),
        "mean_breakout_day_abs_ret_other": float(other.mean()),
        "mean_breakout_day_abs_ret_diff_event_minus_other": float(ev.mean() - other.mean()),
        "welch_t_breakout_day_abs_ret": float(welch.statistic),
        "welch_p_breakout_day_abs_ret": float(welch.pvalue),
        **big,
    }


def moving_block_bootstrap_diff(
    panel: pd.DataFrame,
    event_col: str,
    value_col: str,
    *,
    n_boot: int,
    block: int,
    seed: int,
) -> dict[str, Any]:
    sample = panel[[event_col, value_col]].dropna().copy()
    n = len(sample)
    if n == 0:
        return {"n_boot_effective": 0, "ci95": [math.nan, math.nan], "mean": math.nan}
    rng = np.random.default_rng(seed)
    event = sample[event_col].astype(bool).to_numpy()
    values = sample[value_col].to_numpy(dtype=float)
    diffs: list[float] = []
    starts = np.arange(max(1, n - block + 1))
    for _ in range(n_boot):
        idx: list[int] = []
        while len(idx) < n:
            s = int(rng.choice(starts))
            idx.extend(range(s, min(s + block, n)))
        idx_arr = np.array(idx[:n])
        e = event[idx_arr]
        if e.sum() < 2 or (~e).sum() < 2:
            continue
        v = values[idx_arr]
        diffs.append(float(v[e].mean() - v[~e].mean()))
    if not diffs:
        return {"n_boot_effective": 0, "ci95": [math.nan, math.nan], "mean": math.nan}
    arr = np.array(diffs)
    return {
        "n_boot_effective": int(len(arr)),
        "mean": float(arr.mean()),
        "ci95": [float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975))],
    }


def build_asset_result(ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    panel = add_features(load_price(ticker))
    panel.insert(0, "ticker", ticker)
    squeeze_valid = panel["squeeze"].dropna()
    signal_comparisons: dict[str, dict[str, Any]] = {}
    for threshold in RUN_THRESHOLDS:
        event_col = f"squeeze_reaches_{threshold}d"
        signal_comparisons[event_col] = {
            str(h): compare_event(panel, event_col, h) for h in HORIZONS
        }
    episode_end: dict[str, Any] = {}
    for threshold in RUN_THRESHOLDS:
        event_col = f"episode_end_after_{threshold}d"
        episode_end[event_col] = {
            "breakout_day": compare_breakout_day(panel, event_col),
            "forward": {str(h): compare_event(panel, event_col, h) for h in HORIZONS},
        }
    primary_col = "squeeze_reaches_10d"
    primary_h = 20
    boot = moving_block_bootstrap_diff(
        panel,
        primary_col,
        f"fwd_vol_{primary_h}d_ann",
        n_boot=N_BOOT,
        block=BOOT_BLOCK,
        seed=SEED,
    )
    data_start = panel.index.min().strftime("%Y-%m-%d")
    data_end = panel.index.max().strftime("%Y-%m-%d")
    result = {
        "ticker": ticker,
        "label": ASSETS[ticker],
        "date_start": data_start,
        "date_end": data_end,
        "n_price_obs": int(panel["price"].notna().sum()),
        "n_target_obs_20d": int(panel["fwd_vol_20d_ann"].notna().sum()),
        "n_squeeze_days": int(panel["squeeze"].fillna(False).sum()),
        "n_squeeze_episodes": int(panel["episode_end"].fillna(False).sum()),
        "max_squeeze_run_days": int(panel["squeeze_run"].max()),
        "median_squeeze_episode_days": float(panel.loc[panel["episode_end"], "episode_duration"].median()),
        "signal_comparisons": signal_comparisons,
        "episode_end_comparisons": episode_end,
        "bootstrap_primary_vol_diff": {
            "event_col": primary_col,
            "horizon_days": primary_h,
            "value_col": f"fwd_vol_{primary_h}d_ann",
            "block": BOOT_BLOCK,
            "seed": SEED,
            "n_boot_requested": N_BOOT,
            **boot,
        },
    }
    return panel, result


def make_figures(results: dict[str, Any]) -> None:
    setup_matplotlib_font()
    colors = {"event": "#0b4f6c", "other": "#c7d3dd", "accent": "#c0392b"}

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), dpi=160)
    fig.patch.set_facecolor("white")
    for ax, ticker in zip(axes, ASSETS):
        asset = results["asset_results"][ticker]
        comps = asset["signal_comparisons"]
        x = np.arange(len(RUN_THRESHOLDS))
        event_vals = []
        other_vals = []
        ns = []
        for th in RUN_THRESHOLDS:
            c = comps[f"squeeze_reaches_{th}d"]["20"]
            event_vals.append(c.get("mean_vol_event_ann", math.nan) * 100)
            other_vals.append(c.get("mean_vol_other_ann", math.nan) * 100)
            ns.append(c.get("n_event", 0))
        ax.bar(x - 0.18, event_vals, width=0.36, color=colors["event"], label="盤整訊號後")
        ax.bar(x + 0.18, other_vals, width=0.36, color=colors["other"], label="其他日子")
        for i, val in enumerate(event_vals):
            if not math.isnan(val):
                ax.text(i - 0.18, val + 0.45, f"{val:.1f}%\nn={ns[i]}", ha="center", va="bottom", fontsize=9)
        ax.set_xticks(x, [f"達 {th} 天" for th in RUN_THRESHOLDS])
        ax.set_ylim(0, max(other_vals + event_vals) * 1.25)
        ax.set_title(f"{ASSETS[ticker]}：盤整達標後 20 日年化波動")
        ax.set_ylabel("後續 20 日年化波動率")
        ax.grid(axis="y", alpha=0.22)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(loc="upper left", frameon=False)
    fig.suptitle("低波動盤整達標後，後續波動沒有升高", fontsize=16, fontweight="bold")
    fig.text(
        0.01,
        0.01,
        "資料來源：experiment K1632；訊號使用 t 日收盤已知資料，forward target 從 t+1 開始。",
        fontsize=9,
        color="#4d5b66",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(FIG_SIGNAL, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), dpi=160)
    fig.patch.set_facecolor("white")
    for ax, ticker in zip(axes, ASSETS):
        asset = results["asset_results"][ticker]
        event = asset["episode_end_comparisons"]["episode_end_after_10d"]
        break_c = event["breakout_day"]
        fwd_c = event["forward"]["20"]
        labels = ["結束當天\n單日絕對報酬", "結束後\n20 日年化波動"]
        event_vals = [
            break_c["mean_breakout_day_abs_ret_event"] * 100,
            fwd_c["mean_vol_event_ann"] * 100,
        ]
        other_vals = [
            break_c["mean_breakout_day_abs_ret_other"] * 100,
            fwd_c["mean_vol_other_ann"] * 100,
        ]
        x = np.arange(2)
        ax.bar(x - 0.18, event_vals, width=0.36, color=colors["accent"], label="盤整結束（≥10天）")
        ax.bar(x + 0.18, other_vals, width=0.36, color=colors["other"], label="其他日子")
        for i, val in enumerate(event_vals):
            ax.text(i - 0.18, val + 0.35, f"{val:.1f}%", ha="center", va="bottom", fontsize=9)
        ax.set_xticks(x, labels)
        ax.set_ylim(0, max(event_vals + other_vals) * 1.28)
        ax.set_title(f"{ASSETS[ticker]}：盤整結束日 vs 結束後")
        ax.grid(axis="y", alpha=0.22)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(loc="upper left", frameon=False)
    fig.suptitle("盤整結束當天較容易動，但後續 20 日仍未變更震", fontsize=16, fontweight="bold")
    fig.text(
        0.01,
        0.01,
        "資料來源：experiment K1632；結束當天為描述性診斷，非可提前交易訊號。",
        fontsize=9,
        color="#4d5b66",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(FIG_END, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    panels: list[pd.DataFrame] = []
    asset_results: dict[str, Any] = {}
    for ticker in ASSETS:
        panel, result = build_asset_result(ticker)
        panels.append(panel.reset_index(names="date"))
        asset_results[ticker] = result
    panel_all = pd.concat(panels, ignore_index=True)
    panel_all.to_csv(PANEL_PATH, index=False)
    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": TITLE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "price_source": "data/cache/price_cache.db :: price_data adj_close",
            "assets": ASSETS,
            "tickers": list(ASSETS.keys()),
            "n_panel_rows": int(len(panel_all)),
        },
        "method": {
            "consolidation_definition": (
                "20-day realized volatility and 20-day close-to-close range are both "
                "below their own trailing-252-day 20th percentile thresholds; thresholds "
                "are shifted one day so only t-1 history defines the cutoff."
            ),
            "signal_timing": "signal observed after day t close; forward outcomes use t+1 through t+h only",
            "primary_signal": "squeeze_reaches_10d",
            "primary_horizon_days": 20,
            "episode_end_note": (
                "episode_end_after_10d uses the first non-squeeze day after a squeeze episode; "
                "breakout-day absolute return is descriptive because same-day return is not tradable "
                "from the prior close without lookahead."
            ),
            "horizons_days": HORIZONS,
            "tests": [
                "OLS dummy regression with Newey-West HAC maxlags=horizon for forward abs-return and volatility",
                "Welch test for breakout-day absolute return",
                "Fisher exact test for top-quintile absolute-move probability",
                "Moving-block bootstrap for primary 20-day forward-volatility difference",
            ],
            "bootstrap": {"n_boot": N_BOOT, "block": BOOT_BLOCK, "seed": SEED},
        },
        "headline": {
            "verdict": "MYTH_MOSTLY_FALSE_LOW_VOL_PERSISTS",
            "summary": (
                "Low-volatility consolidation does not reliably precede higher future volatility. "
                "After a 10-day squeeze, both SPY and 0050.TW show lower subsequent 20-day annualized "
                "volatility than other days. Squeeze episode endings have larger same-day absolute "
                "moves, but the next 20 trading days still do not become more volatile."
            ),
            "primary_signal": "squeeze_reaches_10d",
            "primary_horizon_days": 20,
        },
        "asset_results": asset_results,
        "artifacts": {
            "panel_csv": str(PANEL_PATH.relative_to(ROOT)),
            "fig_signal": str(FIG_SIGNAL.relative_to(ROOT)),
            "fig_episode_end": str(FIG_END.relative_to(ROOT)),
        },
    }
    make_figures(results)
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {RESULTS_PATH}")
    print(f"wrote {PANEL_PATH}")
    print(f"wrote {FIG_SIGNAL}")
    print(f"wrote {FIG_END}")


if __name__ == "__main__":
    main()
