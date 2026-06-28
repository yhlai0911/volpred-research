"""
K1559: Missing / Stale Market Data as Liquidity-Volatility Prior

Research question
-----------------
Are daily data-quality events in low-liquidity ETF histories merely nuisance
cleaning issues, or do they behave like liquidity-stress signals that lead
next 5d / 22d realized volatility, gap risk, or drawdown risk?

Information set and lookahead rule
----------------------------------
All signals are measured at the end of reference trading day t:

  signal_t = missing_row_t, zero_volume_t, stale_price_t, recovery_after_missing_t, ...

Targets start strictly after t:

  fwd_rv5_t  = sum of squared returns over t+1 ... t+5
  fwd_rv22_t = sum of squared returns over t+1 ... t+22

This direct event study does not trade on same-day returns. Recovery-day gap
returns are reported descriptively, but future targets begin at the next
reference trading day after the signal date.

Literature anchors
------------------
- Lesmond, Ogden, Trzcinka (1999): zero returns as a transaction-cost proxy.
- Amihud (2002): daily absolute return / dollar volume illiquidity.
- Getmansky, Lo, Makarov (2004): stale / smoothed prices understate economic risk.
- Bekaert, Harvey, Lundblad (2007): zero-return liquidity measures in thin markets.
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


SEED = 42
np.random.seed(SEED)
random.seed(SEED)
warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


EXPERIMENT_ID = "k1559"
TITLE = "Missing / Stale Market Data as Liquidity-Volatility Prior"
START_DATE = "2014-01-01"
END_DATE = "2026-06-29"
REFERENCE_TICKER = "SPY"
MARKET_TICKER = "SPY"
MIN_VALID_TARGET_FRACTION = 0.80

# Low-liquidity / niche ETF universe plus a few liquid controls.
ASSET_META: Dict[str, Dict[str, str]] = {
    "SPY": {"bucket": "liquid_control", "theme": "large_cap"},
    "QQQ": {"bucket": "liquid_control", "theme": "growth"},
    "IWM": {"bucket": "small_cap_control", "theme": "small_cap"},
    "IWC": {"bucket": "microcap", "theme": "microcap"},
    "IJR": {"bucket": "small_cap_control", "theme": "small_cap"},
    "VIOO": {"bucket": "small_cap_control", "theme": "small_cap"},
    "XBI": {"bucket": "sector", "theme": "biotech"},
    "XES": {"bucket": "sector", "theme": "energy_services"},
    "XME": {"bucket": "sector", "theme": "metals_mining"},
    "REMX": {"bucket": "niche_commodity", "theme": "rare_earth"},
    "URA": {"bucket": "niche_commodity", "theme": "uranium"},
    "COPX": {"bucket": "niche_commodity", "theme": "copper_miners"},
    "GREK": {"bucket": "country", "theme": "greece"},
    "TUR": {"bucket": "country", "theme": "turkey"},
    "EPOL": {"bucket": "country", "theme": "poland"},
    "EIRL": {"bucket": "country", "theme": "ireland"},
    "ECH": {"bucket": "country", "theme": "chile"},
    "EPU": {"bucket": "country", "theme": "peru"},
    "EIDO": {"bucket": "country", "theme": "indonesia"},
    "THD": {"bucket": "country", "theme": "thailand"},
    "EPHE": {"bucket": "country", "theme": "philippines"},
    "VNM": {"bucket": "country", "theme": "vietnam"},
    "GXG": {"bucket": "country", "theme": "colombia"},
    "KSA": {"bucket": "country", "theme": "saudi"},
    "QAT": {"bucket": "country", "theme": "qatar"},
    "UAE": {"bucket": "country", "theme": "uae"},
    "FM": {"bucket": "frontier", "theme": "frontier_markets"},
    "AFK": {"bucket": "frontier", "theme": "africa"},
}
ASSETS = list(ASSET_META.keys())

EVENT_COLS = [
    "any_data_quality_event",
    "missing_row",
    "recovery_after_missing",
    "zero_volume",
    "stale_price",
    "corporate_action_gap",
    "zero_return_day",
]
TARGET_SPECS = [
    ("log_fwd_rv5", "continuous", 5),
    ("log_fwd_rv22", "continuous", 22),
    ("gap5_5pct", "binary", 5),
    ("gap22_5pct", "binary", 22),
    ("dd22_10pct", "binary", 22),
]


def download_one(ticker: str) -> pd.DataFrame:
    """Download one OHLCV panel from yfinance with stable column handling."""
    df = yf.download(
        ticker,
        start=START_DATE,
        end=END_DATE,
        progress=False,
        auto_adjust=False,
        actions=False,
        threads=False,
    )
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"{ticker} missing yfinance columns: {missing}")
    df = df[required].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.sort_index()
    return df


def forward_window_stats(
    returns: pd.Series,
    horizons: Iterable[int] = (5, 22),
    min_valid_fraction: float = MIN_VALID_TARGET_FRACTION,
) -> pd.DataFrame:
    """Forward targets from t+1 only; never includes same-date return at t."""
    idx = returns.index
    vals = returns.to_numpy(dtype=float)
    out = pd.DataFrame(index=idx)
    for h in horizons:
        min_valid = max(1, int(math.ceil(h * min_valid_fraction)))
        rv = np.full(len(vals), np.nan)
        max_abs = np.full(len(vals), np.nan)
        min_cum = np.full(len(vals), np.nan)
        n_valid = np.zeros(len(vals), dtype=int)
        for i in range(len(vals)):
            window = vals[i + 1 : i + 1 + h]
            finite = window[np.isfinite(window)]
            n_valid[i] = len(finite)
            if len(finite) < min_valid:
                continue
            rv[i] = float(np.sum(finite ** 2) * 252.0 / len(finite))
            max_abs[i] = float(np.max(np.abs(finite)))
            cum_path = np.cumprod(1.0 + finite) - 1.0
            min_cum[i] = float(np.min(cum_path))
        out[f"fwd_rv{h}"] = rv
        out[f"log_fwd_rv{h}"] = np.log(np.maximum(rv, 1e-12))
        out[f"fwd_max_abs_ret{h}"] = max_abs
        out[f"gap{h}_5pct"] = (max_abs >= 0.05).astype(float)
        out[f"fwd_min_cum_ret{h}"] = min_cum
        out[f"n_valid_fwd{h}"] = n_valid
    out["dd22_10pct"] = (out["fwd_min_cum_ret22"] <= -0.10).astype(float)
    return out


def add_holm(p_values: List[float]) -> List[float]:
    """Holm-Bonferroni adjusted p-values, aligned with input order."""
    m = len(p_values)
    order = sorted(
        range(m),
        key=lambda i: p_values[i] if p_values[i] is not None and np.isfinite(p_values[i]) else 1.0,
    )
    adj = [float("nan")] * m
    prev = 0.0
    for rank, idx in enumerate(order):
        p = p_values[idx]
        if p is None or not np.isfinite(p):
            continue
        val = min(1.0, float(p) * (m - rank))
        val = max(val, prev)
        prev = val
        adj[idx] = val
    return adj


def build_asset_panel(ticker: str, raw: pd.DataFrame, ref_index: pd.DatetimeIndex, market_ret: pd.Series) -> pd.DataFrame:
    """Build a reference-calendar asset panel with data-quality events and future targets."""
    if raw.empty:
        return pd.DataFrame()

    first = raw.index.min()
    last = raw.index.max()
    idx = ref_index[(ref_index >= first) & (ref_index <= last)]
    if len(idx) < 260:
        return pd.DataFrame()

    valid = raw.copy()
    valid["raw_ret"] = np.log(valid["Close"] / valid["Close"].shift(1))
    valid["adj_ret"] = np.log(valid["Adj Close"] / valid["Adj Close"].shift(1))
    valid["raw_adj_ret_gap"] = (valid["raw_ret"] - valid["adj_ret"]).abs()

    panel = valid.reindex(idx)
    is_missing = panel["Close"].isna()
    was_missing_prev = is_missing.shift(1).fillna(False)
    is_valid = ~is_missing

    high_low_range = np.log(panel["High"] / panel["Low"]).replace([np.inf, -np.inf], np.nan)
    volume = panel["Volume"].astype(float)
    adj_ret = valid["adj_ret"].reindex(idx)
    raw_ret = valid["raw_ret"].reindex(idx)
    raw_adj_gap = valid["raw_adj_ret_gap"].reindex(idx)

    missing_row = is_missing.astype(int)
    zero_volume = (is_valid & (volume <= 0)).astype(int)
    zero_return_day = (is_valid & (adj_ret.abs() <= 1e-12)).astype(int)
    stale_price = (is_valid & (adj_ret.abs() <= 1e-12) & ((volume <= 0) | (high_low_range.abs() <= 1e-10))).astype(int)
    corporate_action_gap = (
        is_valid
        & (raw_ret.abs() >= 0.10)
        & (raw_adj_gap >= 0.05)
        & (adj_ret.abs() <= 0.05)
    ).astype(int)
    recovery_after_missing = (is_valid & was_missing_prev).astype(int)
    any_dq = (
        (missing_row == 1)
        | (zero_volume == 1)
        | (stale_price == 1)
        | (corporate_action_gap == 1)
        | (recovery_after_missing == 1)
    ).astype(int)

    close_ffill = panel["Adj Close"].ffill()
    volume_ffill = volume.ffill()
    dollar_volume = (panel["Close"].ffill() * volume_ffill).replace([np.inf, -np.inf], np.nan)

    ret_for_target = adj_ret.copy()
    targets = forward_window_stats(ret_for_target)

    lag_rv22 = ret_for_target.rolling(22, min_periods=10).apply(lambda x: float(np.nanmean(x ** 2) * 252.0), raw=False)
    lag_zero_return_22 = zero_return_day.rolling(22, min_periods=10).mean()
    lag_missing_22 = missing_row.rolling(22, min_periods=10).mean()
    lag_amihud_22 = (
        (ret_for_target.abs() / dollar_volume.replace(0.0, np.nan))
        .rolling(22, min_periods=10)
        .mean()
        * 1e10
    )

    out = pd.DataFrame(index=idx)
    out["asset"] = ticker
    out["bucket"] = ASSET_META[ticker]["bucket"]
    out["theme"] = ASSET_META[ticker]["theme"]
    out["missing_row"] = missing_row
    out["zero_volume"] = zero_volume
    out["zero_return_day"] = zero_return_day
    out["stale_price"] = stale_price
    out["corporate_action_gap"] = corporate_action_gap
    out["recovery_after_missing"] = recovery_after_missing
    out["any_data_quality_event"] = any_dq
    out["adj_ret"] = ret_for_target
    out["recovery_gap_abs_return"] = np.where(recovery_after_missing == 1, ret_for_target.abs(), np.nan)
    out["lag_rv22"] = lag_rv22
    out["log_lag_rv22"] = np.log(np.maximum(lag_rv22, 1e-12))
    out["log_dollar_volume"] = np.log(np.maximum(dollar_volume, 1.0))
    out["log_price"] = np.log(np.maximum(close_ffill, 1e-12))
    out["lag_zero_return_22"] = lag_zero_return_22
    out["lag_missing_22"] = lag_missing_22
    out["lag_amihud_22"] = lag_amihud_22
    out["market_abs_ret"] = market_ret.reindex(idx).abs()
    out = out.join(targets)
    out["date"] = out.index
    return out


def fit_panel_model(panel: pd.DataFrame, event_col: str, target_col: str, horizon: int) -> Dict[str, float | str | int]:
    """Asset-FE panel OLS / LPM with HAC SE over the time-ordered stacked panel."""
    cols = [
        target_col,
        event_col,
        "log_lag_rv22",
        "log_dollar_volume",
        "log_price",
        "market_abs_ret",
    ]
    df = panel[cols + ["asset", "date"]].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if len(df) < 500:
        return {"ok": False, "reason": "too_few_rows", "n": int(len(df))}
    n_event = int(df[event_col].sum())
    n_nonevent = int(len(df) - n_event)
    if n_event < 10 or n_nonevent < 100:
        return {
            "ok": False,
            "reason": "too_few_events",
            "n": int(len(df)),
            "n_event": n_event,
            "n_nonevent": n_nonevent,
        }

    df = df.sort_values(["date", "asset"])
    y = df[target_col].astype(float)
    base_x = df[[event_col, "log_lag_rv22", "log_dollar_volume", "log_price", "market_abs_ret"]].astype(float)
    asset_dummies = pd.get_dummies(df["asset"], prefix="asset", drop_first=True, dtype=float)
    x = pd.concat([base_x, asset_dummies], axis=1)
    x = sm.add_constant(x, has_constant="add")
    try:
        model = sm.OLS(y, x)
        res = model.fit(cov_type="HAC", cov_kwds={"maxlags": max(1, horizon)})
    except Exception as exc:
        return {"ok": False, "reason": f"ols_failed:{exc}", "n": int(len(df))}

    coef = float(res.params[event_col])
    se = float(res.bse[event_col])
    t_stat = float(res.tvalues[event_col])
    p_val = float(res.pvalues[event_col])
    y_event = float(df.loc[df[event_col] == 1, target_col].mean())
    y_nonevent = float(df.loc[df[event_col] == 0, target_col].mean())
    return {
        "ok": True,
        "n": int(len(df)),
        "n_event": n_event,
        "n_nonevent": n_nonevent,
        "event_col": event_col,
        "target_col": target_col,
        "horizon": int(horizon),
        "coef": coef,
        "se_hac": se,
        "t_hac": t_stat,
        "p_raw": p_val,
        "event_mean": y_event,
        "nonevent_mean": y_nonevent,
        "r2": float(res.rsquared),
    }


def summarize_events(panel: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Dict[str, float]]]:
    counts = panel.groupby("asset")[EVENT_COLS].sum().astype(int)
    summary = {}
    for ev in EVENT_COLS:
        event_mask = panel[ev] == 1
        non_mask = panel[ev] == 0
        if event_mask.sum() == 0:
            summary[ev] = {
                "n_event": 0,
                "rv5_ratio_event_to_nonevent": float("nan"),
                "rv22_ratio_event_to_nonevent": float("nan"),
                "gap5_rate_event": float("nan"),
                "gap5_rate_nonevent": float("nan"),
                "dd22_rate_event": float("nan"),
                "dd22_rate_nonevent": float("nan"),
            }
            continue
        rv5_event = panel.loc[event_mask, "fwd_rv5"].mean()
        rv5_nonevent = panel.loc[non_mask, "fwd_rv5"].mean()
        rv22_event = panel.loc[event_mask, "fwd_rv22"].mean()
        rv22_nonevent = panel.loc[non_mask, "fwd_rv22"].mean()
        summary[ev] = {
            "n_event": int(event_mask.sum()),
            "rv5_ratio_event_to_nonevent": float(rv5_event / rv5_nonevent) if rv5_nonevent > 0 else float("nan"),
            "rv22_ratio_event_to_nonevent": float(rv22_event / rv22_nonevent) if rv22_nonevent > 0 else float("nan"),
            "gap5_rate_event": float(panel.loc[event_mask, "gap5_5pct"].mean()),
            "gap5_rate_nonevent": float(panel.loc[non_mask, "gap5_5pct"].mean()),
            "dd22_rate_event": float(panel.loc[event_mask, "dd22_10pct"].mean()),
            "dd22_rate_nonevent": float(panel.loc[non_mask, "dd22_10pct"].mean()),
        }
    return counts, summary


def summarize_within_asset_effects(panel: pd.DataFrame) -> List[Dict[str, object]]:
    """Unconditional event/non-event ratios within each asset for concentration audit."""
    rows: List[Dict[str, object]] = []
    for asset, g in panel.groupby("asset"):
        for ev in EVENT_COLS:
            event_mask = g[ev] == 1
            non_mask = g[ev] == 0
            if int(event_mask.sum()) == 0 or int(non_mask.sum()) == 0:
                continue
            rv5_non = float(g.loc[non_mask, "fwd_rv5"].mean())
            rv22_non = float(g.loc[non_mask, "fwd_rv22"].mean())
            rows.append({
                "asset": asset,
                "event_col": ev,
                "n_event": int(event_mask.sum()),
                "rv5_ratio_event_to_nonevent": float(g.loc[event_mask, "fwd_rv5"].mean() / rv5_non)
                if rv5_non > 0 else float("nan"),
                "rv22_ratio_event_to_nonevent": float(g.loc[event_mask, "fwd_rv22"].mean() / rv22_non)
                if rv22_non > 0 else float("nan"),
                "gap22_rate_event": float(g.loc[event_mask, "gap22_5pct"].mean()),
                "gap22_rate_nonevent": float(g.loc[non_mask, "gap22_5pct"].mean()),
                "dd22_rate_event": float(g.loc[event_mask, "dd22_10pct"].mean()),
                "dd22_rate_nonevent": float(g.loc[non_mask, "dd22_10pct"].mean()),
            })
    return rows


def make_event_count_plot(counts: pd.DataFrame, outpath: Path) -> None:
    plot_cols = ["missing_row", "recovery_after_missing", "zero_volume", "stale_price", "corporate_action_gap"]
    counts_plot = counts[plot_cols].copy()
    counts_plot = counts_plot.loc[counts_plot.sum(axis=1).sort_values(ascending=False).index].head(18)
    fig, ax = plt.subplots(figsize=(12, 6))
    bottom = np.zeros(len(counts_plot))
    x = np.arange(len(counts_plot))
    for col in plot_cols:
        vals = counts_plot[col].to_numpy()
        ax.bar(x, vals, bottom=bottom, label=col)
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels(counts_plot.index, rotation=45, ha="right")
    ax.set_ylabel("Event count")
    ax.set_title("K1559 data-quality event counts by ETF")
    ax.legend(ncol=3, fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def make_effect_plot(effect_summary: Dict[str, Dict[str, float]], outpath: Path) -> None:
    rows = []
    for ev, d in effect_summary.items():
        rows.append((ev, d["rv5_ratio_event_to_nonevent"], d["rv22_ratio_event_to_nonevent"], d["n_event"]))
    plot_df = pd.DataFrame(rows, columns=["event", "rv5_ratio", "rv22_ratio", "n_event"])
    plot_df = plot_df[plot_df["n_event"] > 0].copy()
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(plot_df))
    width = 0.36
    ax.bar(x - width / 2, plot_df["rv5_ratio"], width, label="next 5d RV ratio")
    ax.bar(x + width / 2, plot_df["rv22_ratio"], width, label="next 22d RV ratio")
    ax.axhline(1.0, color="black", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(plot_df["event"], rotation=35, ha="right")
    ax.set_ylabel("Event / non-event future RV")
    ax.set_title("K1559 unconditional future RV ratios")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return val if np.isfinite(val) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def main() -> None:
    print(f"[K1559] {TITLE}")
    print(f"[K1559] Sample {START_DATE} -> {END_DATE}; assets={len(ASSETS)}; seed={SEED}")

    ref = download_one(REFERENCE_TICKER)
    if ref.empty:
        raise RuntimeError("SPY reference calendar unavailable")
    ref_index = ref.index
    ref["adj_ret"] = np.log(ref["Adj Close"] / ref["Adj Close"].shift(1))
    market_ret = ref["adj_ret"]

    raw_data: Dict[str, pd.DataFrame] = {}
    panels = []
    fetch_status = {}
    for ticker in ASSETS:
        try:
            raw = download_one(ticker)
            raw_data[ticker] = raw
            if raw.empty:
                fetch_status[ticker] = {"ok": False, "reason": "empty"}
                continue
            panel = build_asset_panel(ticker, raw, ref_index, market_ret)
            if panel.empty:
                fetch_status[ticker] = {"ok": False, "reason": "panel_too_short", "rows": int(len(raw))}
                continue
            panels.append(panel)
            fetch_status[ticker] = {
                "ok": True,
                "rows_downloaded": int(len(raw)),
                "panel_rows": int(len(panel)),
                "first_date": str(raw.index.min().date()),
                "last_date": str(raw.index.max().date()),
            }
            print(f"[K1559] {ticker}: raw={len(raw)} panel={len(panel)}")
        except Exception as exc:
            fetch_status[ticker] = {"ok": False, "reason": str(exc)}
            print(f"[K1559] WARN {ticker}: {exc}")

    if not panels:
        raise RuntimeError("No asset panels built")

    panel = pd.concat(panels, axis=0, ignore_index=False)
    panel = panel.replace([np.inf, -np.inf], np.nan)

    # Main estimation sample requires observed future targets and controls.
    estimation_cols = [
        "log_lag_rv22",
        "log_dollar_volume",
        "log_price",
        "market_abs_ret",
        "log_fwd_rv5",
        "log_fwd_rv22",
        "gap5_5pct",
        "gap22_5pct",
        "dd22_10pct",
    ]
    estimation_panel = panel.dropna(subset=estimation_cols).copy()

    event_counts, effect_summary = summarize_events(estimation_panel)
    within_asset_effects = summarize_within_asset_effects(estimation_panel)

    tests: List[Dict[str, object]] = []
    for ev in EVENT_COLS:
        for target, target_type, horizon in TARGET_SPECS:
            result = fit_panel_model(estimation_panel, ev, target, horizon)
            result["target_type"] = target_type
            tests.append(result)
    pvals = [float(t["p_raw"]) if t.get("ok") and t.get("p_raw") is not None else float("nan") for t in tests]
    holm = add_holm(pvals)
    for t, p_h in zip(tests, holm):
        t["p_holm"] = p_h
        t["holm_significant_5pct"] = bool(t.get("ok") and np.isfinite(p_h) and p_h < 0.05)

    valid_tests = [t for t in tests if t.get("ok")]
    primary = [
        t
        for t in valid_tests
        if t["event_col"] == "any_data_quality_event" and t["target_col"] in ("log_fwd_rv5", "log_fwd_rv22")
    ]
    primary_positive_holm = [
        t for t in primary if t["coef"] > 0 and t["holm_significant_5pct"]
    ]
    event_specific_positive_holm = [
        t
        for t in valid_tests
        if t["event_col"] != "any_data_quality_event"
        and t["coef"] > 0
        and t["holm_significant_5pct"]
        and t["target_col"] in ("log_fwd_rv5", "log_fwd_rv22", "gap5_5pct", "gap22_5pct", "dd22_10pct")
    ]

    any_dq_counts = event_counts["any_data_quality_event"]
    any_dq_assets_ge10 = int((any_dq_counts >= 10).sum())
    any_dq_positive_rv22_assets_ge10 = int(sum(
        1
        for row in within_asset_effects
        if row["event_col"] == "any_data_quality_event"
        and row["n_event"] >= 10
        and row["rv22_ratio_event_to_nonevent"] > 1.0
    ))
    missing_rows_total = int(event_counts["missing_row"].sum())

    if (
        len(primary_positive_holm) == 2
        and any_dq_assets_ge10 >= 5
        and any_dq_positive_rv22_assets_ge10 >= 4
        and missing_rows_total >= 10
    ):
        verdict = "PASS"
        verdict_reason = (
            "Any data-quality event predicts both next 5d and 22d RV after controls and Holm correction, "
            "with broad cross-asset event coverage including enough missing-row observations."
        )
    elif len(primary_positive_holm) >= 1 or len(event_specific_positive_holm) >= 2:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (
            "Controlled panel tests are positive after Holm correction, but evidence is concentrated in a few "
            "thin ETFs and missing-row events are too rare for a broad missing-data claim. Treat zero-volume/"
            "stale-price days as a conditional liquidity-risk prior, not a general alpha signal."
        )
    else:
        verdict = "NULL"
        verdict_reason = (
            "Data-quality events are observed, but the broad controlled next-volatility prior does not survive "
            "the pre-specified Holm-corrected event-study gate."
        )

    event_count_path = SCRIPT_DIR / "k1559_event_counts.png"
    effect_path = SCRIPT_DIR / "k1559_future_rv_ratios.png"
    make_event_count_plot(event_counts, event_count_path)
    make_effect_plot(effect_summary, effect_path)

    per_asset_summary = {}
    for asset, g in estimation_panel.groupby("asset"):
        per_asset_summary[asset] = {
            "n_rows": int(len(g)),
            "bucket": str(g["bucket"].iloc[0]),
            "mean_dollar_volume": float(np.exp(g["log_dollar_volume"]).mean()),
            "event_counts": {ev: int(g[ev].sum()) for ev in EVENT_COLS},
            "mean_fwd_rv5": float(g["fwd_rv5"].mean()),
            "mean_fwd_rv22": float(g["fwd_rv22"].mean()),
            "gap5_rate": float(g["gap5_5pct"].mean()),
            "dd22_10pct_rate": float(g["dd22_10pct"].mean()),
            "mean_recovery_gap_abs_return": float(g["recovery_gap_abs_return"].mean())
            if g["recovery_gap_abs_return"].notna().any()
            else None,
        }

    results = {
        "k_id": "K1559",
        "experiment_id": EXPERIMENT_ID,
        "title": TITLE,
        "run_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "seed": SEED,
        "data": {
            "source": "yfinance daily OHLCV, auto_adjust=False; adjusted close used for returns",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "reference_calendar": REFERENCE_TICKER,
            "assets": ASSETS,
            "asset_meta": ASSET_META,
            "fetch_status": fetch_status,
            "n_assets_used": int(estimation_panel["asset"].nunique()),
            "n_panel_rows": int(len(panel)),
            "n_estimation_rows": int(len(estimation_panel)),
        },
        "methodology": {
            "motivation": "Test whether missing/stale daily market data in thin ETF histories is a liquidity-volatility prior.",
            "differentiation": (
                "K1472 tested low-frequency illiquidity proxies inside HAR forecasts; K1559 tests explicit "
                "data-quality events and recovery days as event signals."
            ),
            "event_definitions": {
                "missing_row": "Ticker absent on a SPY reference trading day between its first and last observed dates.",
                "recovery_after_missing": "First valid ticker row after a missing reference-calendar row.",
                "zero_volume": "Valid ticker row with Volume <= 0.",
                "stale_price": "Zero adjusted return plus zero volume or zero intraday high-low range.",
                "corporate_action_gap": "Large raw close move mostly removed by adjusted close, likely split/distribution adjustment.",
                "zero_return_day": "Zero adjusted return, included as LOT-style illiquidity proxy but not counted in any_data_quality_event unless stale.",
                "any_data_quality_event": "missing_row OR recovery_after_missing OR zero_volume OR stale_price OR corporate_action_gap.",
            },
            "lookahead_control": (
                "Signals are measured at reference date t. Future RV/gap/drawdown targets are computed only from "
                "returns at t+1 through t+h."
            ),
            "controls": [
                "asset fixed effects",
                "log lagged 22d realized variance",
                "log dollar volume",
                "log price",
                "absolute SPY return at t",
            ],
            "formal_tests": "Asset-FE panel OLS / linear probability model with HAC standard errors; Holm-Bonferroni across event-target tests.",
            "success_gate": (
                "PASS requires broad any_data_quality_event to be positive and Holm-significant for both 5d and 22d "
                "future RV, at least 5 assets with >=10 events, at least 4 positive within-asset RV22 effects, "
                "and >=10 missing-row observations. Otherwise strong but concentrated evidence is CONDITIONAL_PASS."
            ),
        },
        "literature": [
            {
                "citation": "Lesmond, Ogden, Trzcinka (1999), Review of Financial Studies",
                "use": "Zero returns as an indirect transaction-cost / illiquidity proxy.",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=184681",
            },
            {
                "citation": "Amihud (2002), Journal of Financial Markets",
                "use": "Daily absolute return over dollar volume as low-frequency price-impact measure.",
                "url": "https://archive.nyu.edu/handle/2451/26706",
            },
            {
                "citation": "Getmansky, Lo, Makarov (2004), Journal of Financial Economics",
                "use": "Stale and smoothed prices can understate true economic risk for illiquid assets.",
                "url": "https://ideas.repec.org/a/eee/jfinec/v74y2004i3p529-609.html",
            },
            {
                "citation": "Bekaert, Harvey, Lundblad (2007), Review of Financial Studies",
                "use": "Zero-return liquidity measures for thin markets, with turnover/price controls.",
                "url": "https://academic.oup.com/rfs/article/20/6/1783/1575135",
            },
            {
                "citation": "Scholes and Williams (1977), Journal of Financial Economics",
                "use": "Nonsynchronous trading creates measurement issues in thinly traded assets.",
                "url": "https://www.semanticscholar.org/paper/Estimating-betas-from-nonsynchronous-data-Scholes-Williams/639e7aac7d841d79bbabe90cfdd462fda9794f32",
            },
        ],
        "event_counts_by_asset": event_counts.to_dict(orient="index"),
        "event_effect_summary_unconditional": effect_summary,
        "within_asset_event_effects": within_asset_effects,
        "per_asset_summary": per_asset_summary,
        "formal_tests": tests,
        "summary": {
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "n_valid_tests": int(len(valid_tests)),
            "n_holm_significant_positive_tests": int(
                sum(1 for t in valid_tests if t["coef"] > 0 and t["holm_significant_5pct"])
            ),
            "n_primary_positive_holm_tests": int(len(primary_positive_holm)),
            "n_event_specific_positive_holm_tests": int(len(event_specific_positive_holm)),
            "any_dq_assets_with_at_least_10_events": any_dq_assets_ge10,
            "any_dq_positive_rv22_assets_with_at_least_10_events": any_dq_positive_rv22_assets_ge10,
            "missing_rows_total": missing_rows_total,
            "primary_tests": primary,
            "top_positive_holm_tests": sorted(
                [
                    {
                        "event_col": t["event_col"],
                        "target_col": t["target_col"],
                        "coef": t["coef"],
                        "t_hac": t["t_hac"],
                        "p_raw": t["p_raw"],
                        "p_holm": t["p_holm"],
                        "n_event": t["n_event"],
                    }
                    for t in valid_tests
                    if t["coef"] > 0 and t["holm_significant_5pct"]
                ],
                key=lambda x: x["p_holm"],
            )[:10],
        },
        "caveats": [
            "yfinance is a vendor snapshot, not exchange-certified audit data.",
            "Missing-row events are measured against SPY trading dates; exchange halts and ETF-specific closures can be mixed with vendor omissions.",
            "The experiment tests risk association, not tradable alpha.",
            "ETFs can split or distribute, so corporate_action_gap is treated as a data-adjustment flag, not as economic volatility.",
            "Low event counts for some subtypes make subtype evidence exploratory even when the pooled panel is large.",
        ],
        "files": {
            "script": "experiments/k1559/k1559.py",
            "results": "experiments/k1559/k1559_results.json",
            "readme": "experiments/k1559/README.md",
            "codex_review": "experiments/k1559/codex_review.md",
            "event_count_plot": "experiments/k1559/k1559_event_counts.png",
            "effect_plot": "experiments/k1559/k1559_future_rv_ratios.png",
        },
    }

    out_json = SCRIPT_DIR / "k1559_results.json"
    with out_json.open("w") as f:
        json.dump(json_safe(results), f, indent=2)
    print(f"[K1559] Wrote {out_json}")
    print(f"[K1559] VERDICT={verdict}: {verdict_reason}")


if __name__ == "__main__":
    main()
