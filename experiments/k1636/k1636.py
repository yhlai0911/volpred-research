#!/usr/bin/env python3
"""K1636: Volume-leads-price / high-volume selloff myth test.

Question
--------
Does high trading volume, especially a high-volume down day, predict the
next-day direction of SPY / 0050.TW / 2330.TW?

Design guardrails
-----------------
* Signal date t uses only information observable by the close of t:
  return_t and volume_t.
* Rolling volume baselines are computed from strictly prior observations via
  shift(1); today's volume is never included in its own threshold.
* Primary targets start at t+1: next close-to-close return, next-day down
  probability, and secondary T+1..T+5 return / realized volatility.
* Same-day price-volume relation is reported only as descriptive context.
* Random procedures use SEED and primary tests are BH-FDR adjusted.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.proportion import proportions_ztest


HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS_PATH = HERE / "k1636_results.json"

SEED = 1636
N_BOOT = 10000
START = "2010-01-01"
END = "2026-07-05"

VOL_Q_WINDOW = 252
VOL_Q_MIN = 126
VOL_MED_WINDOW = 60
VOL_MED_MIN = 40
VOL_Q = 0.90
VOL_RATIO_THRESHOLD = 2.0
DOWN_DAY_THRESHOLD = -0.02
HORIZON_5D = 5
HAC_MAXLAGS_DAILY = 5

ASSETS = {
    "SPY": {
        "symbol": "SPY",
        "label": "SPY",
        "market": "US large-cap ETF",
        "fallback": None,
        "volume_note": "ETF share volume",
    },
    "0050.TW": {
        "symbol": "0050.TW",
        "label": "0050.TW",
        "market": "Taiwan broad-market ETF proxy",
        "fallback": Path("storage/macro/yf_0050.TW.csv"),
        "volume_note": "ETF share volume; used because ^TWII index volume is not a clean traded volume series",
    },
    "2330.TW": {
        "symbol": "2330.TW",
        "label": "2330.TW",
        "market": "TSMC common stock",
        "fallback": None,
        "volume_note": "single-stock share volume",
    },
}

PRIMARY_SIGNALS = ["volume_q90", "volume_q90_down_m2pct"]
SECONDARY_SIGNALS = ["volume_2x", "volume_2x_down_m2pct"]


@dataclass
class AssetPanel:
    asset: str
    symbol: str
    source: str
    start: str
    end: str
    n_raw: int
    panel: pd.DataFrame


def _flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    return df


def _read_project_yf_snapshot(path: Path) -> pd.DataFrame:
    """Read project yfinance snapshots with the 3-row yfinance CSV header."""
    with path.open() as f:
        first = f.readline().strip()
        second = f.readline().strip()
        third = f.readline().strip()
    if first.startswith("Price,") and second.startswith("Ticker,") and third.startswith("Date,"):
        df = pd.read_csv(path, skiprows=3, names=["Date", "Close", "High", "Low", "Open", "Volume"])
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        out["Adj Close"] = out["Close"]
        return out
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    cols = {}
    for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
        if col in df.columns:
            cols[col] = df[col]
    out = pd.DataFrame(cols)
    if "Adj Close" not in out and "Close" in out:
        out["Adj Close"] = out["Close"]
    return out


def _download_or_cache(asset: str, cfg: dict) -> tuple[pd.DataFrame, str]:
    DATA.mkdir(exist_ok=True)
    cache = DATA / f"{asset.replace('.', '_').lower()}_ohlcv.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        return df.sort_index(), f"cache:{cache.relative_to(HERE)}"

    try:
        import yfinance as yf

        raw = yf.download(
            cfg["symbol"],
            start=START,
            end=END,
            progress=False,
            auto_adjust=False,
        )
        raw = _flatten_yfinance_columns(raw)
        required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        if raw.empty or any(c not in raw.columns for c in required):
            raise RuntimeError(f"empty or incomplete yfinance result for {cfg['symbol']}")
        df = raw[required].dropna(subset=["Close", "Adj Close"]).sort_index()
        df.to_csv(cache)
        return df, f"yfinance:{cfg['symbol']} auto_adjust=False"
    except Exception as exc:
        fallback = cfg.get("fallback")
        if fallback is None or not fallback.exists():
            raise RuntimeError(f"failed to load {asset}; no fallback available") from exc
        df = _read_project_yf_snapshot(fallback)
        if df.empty:
            raise RuntimeError(f"empty fallback for {asset}: {fallback}") from exc
        df.to_csv(cache)
        return df, f"fallback:{fallback}"


def _strict_forward_rv(ret: pd.Series, horizon: int = HORIZON_5D) -> pd.Series:
    values = ret.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    ann = math.sqrt(252.0)
    for i in range(len(values) - horizon):
        window = values[i + 1 : i + 1 + horizon]
        if len(window) == horizon and np.isfinite(window).all():
            out[i] = np.std(window, ddof=1) * ann
    return pd.Series(out, index=ret.index)


def build_panel(asset: str, cfg: dict) -> AssetPanel:
    raw, source = _download_or_cache(asset, cfg)
    raw = raw[~raw.index.duplicated(keep="first")].sort_index()
    raw = raw[(raw.index >= pd.Timestamp(START)) & (raw.index < pd.Timestamp(END))]
    raw = raw.copy()
    raw["Volume"] = pd.to_numeric(raw["Volume"], errors="coerce")
    raw.loc[raw["Volume"] <= 0, "Volume"] = np.nan

    close = raw["Adj Close"].astype(float)
    ret = close.pct_change()
    next_ret = ret.shift(-1)
    fwd5_ret = close.shift(-HORIZON_5D) / close - 1.0
    fwd5_rv = _strict_forward_rv(ret)

    log_vol = np.log(raw["Volume"])
    prior_q90 = log_vol.shift(1).rolling(VOL_Q_WINDOW, min_periods=VOL_Q_MIN).quantile(VOL_Q)
    prior_median_log = log_vol.shift(1).rolling(VOL_MED_WINDOW, min_periods=VOL_MED_MIN).median()
    prior_median_vol = raw["Volume"].shift(1).rolling(VOL_MED_WINDOW, min_periods=VOL_MED_MIN).median()
    vol_ratio = raw["Volume"] / prior_median_vol
    log_vol_surprise = log_vol - prior_median_log

    panel = pd.DataFrame(
        {
            "open": raw["Open"].astype(float),
            "close": raw["Close"].astype(float),
            "adj_close": close,
            "volume": raw["Volume"],
            "ret": ret,
            "abs_ret": ret.abs(),
            "next_ret": next_ret,
            "fwd5_ret": fwd5_ret,
            "fwd5_rv": fwd5_rv,
            "log_volume": log_vol,
            "prior_log_volume_q90": prior_q90,
            "prior_log_volume_median": prior_median_log,
            "volume_ratio_60d_median": vol_ratio,
            "log_vol_surprise": log_vol_surprise,
        }
    )
    panel["volume_q90"] = panel["log_volume"] >= panel["prior_log_volume_q90"]
    panel["volume_2x"] = panel["volume_ratio_60d_median"] >= VOL_RATIO_THRESHOLD
    panel["down_m2pct"] = panel["ret"] <= DOWN_DAY_THRESHOLD
    panel["volume_q90_down_m2pct"] = panel["volume_q90"] & panel["down_m2pct"]
    panel["volume_2x_down_m2pct"] = panel["volume_2x"] & panel["down_m2pct"]
    # Target-date equivalent alignment for auditability:
    # signal_at_t.shift(1) is the information available for return date t+1.
    for col in PRIMARY_SIGNALS + SECONDARY_SIGNALS:
        panel[f"{col}_lag1_target_date"] = panel[col].shift(1)

    valid_signal = panel["log_volume"].notna() & panel["prior_log_volume_q90"].notna()
    panel = panel.loc[valid_signal].copy()
    return AssetPanel(
        asset=asset,
        symbol=cfg["symbol"],
        source=source,
        start=str(raw.index.min().date()),
        end=str(raw.index.max().date()),
        n_raw=int(len(raw)),
        panel=panel,
    )


def welch_t(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return float(t), float(p)


def positive_log(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    return np.log(x)


def prop_test(event_down: np.ndarray, comp_down: np.ndarray) -> dict:
    event_down = np.asarray(event_down, dtype=bool)
    comp_down = np.asarray(comp_down, dtype=bool)
    n_event = int(len(event_down))
    n_comp = int(len(comp_down))
    k_event = int(event_down.sum())
    k_comp = int(comp_down.sum())
    if n_event == 0 or n_comp == 0:
        return {
            "event_down_count": k_event,
            "nonevent_down_count": k_comp,
            "z": None,
            "p": None,
            "fisher_p": None,
        }
    z, p = proportions_ztest([k_event, k_comp], [n_event, n_comp])
    _, fisher_p = stats.fisher_exact([[k_event, n_event - k_event], [k_comp, n_comp - k_comp]])
    return {
        "event_down_count": k_event,
        "nonevent_down_count": k_comp,
        "z": float(z),
        "p": float(p),
        "fisher_p": float(fisher_p),
    }


def bootstrap_mean_diff(event: np.ndarray, comp: np.ndarray, rng: np.random.Generator) -> dict:
    event = np.asarray(event, dtype=float)
    comp = np.asarray(comp, dtype=float)
    event = event[np.isfinite(event)]
    comp = comp[np.isfinite(comp)]
    if len(event) == 0 or len(comp) == 0:
        return {"diff": None, "ci95": [None, None], "p_centered_two_sided": None}
    boot = (
        rng.choice(event, size=(N_BOOT, len(event)), replace=True).mean(axis=1)
        - rng.choice(comp, size=(N_BOOT, len(comp)), replace=True).mean(axis=1)
    )
    point = float(event.mean() - comp.mean())
    centered = boot - point
    p_centered = float((np.abs(centered) >= abs(point)).mean())
    return {
        "diff": point,
        "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
        "p_centered_two_sided": p_centered,
    }


def bootstrap_prop_diff(event_down: np.ndarray, comp_down: np.ndarray, rng: np.random.Generator) -> dict:
    event = np.asarray(event_down, dtype=float)
    comp = np.asarray(comp_down, dtype=float)
    if len(event) == 0 or len(comp) == 0:
        return {"diff": None, "ci95": [None, None]}
    boot = (
        rng.choice(event, size=(N_BOOT, len(event)), replace=True).mean(axis=1)
        - rng.choice(comp, size=(N_BOOT, len(comp)), replace=True).mean(axis=1)
    )
    return {
        "diff": float(event.mean() - comp.mean()),
        "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
    }


def bh_adjust(pvals: list[float | None]) -> list[float | None]:
    valid = [(i, float(p)) for i, p in enumerate(pvals) if p is not None and np.isfinite(p)]
    out: list[float | None] = [None] * len(pvals)
    if not valid:
        return out
    m = len(valid)
    valid_sorted = sorted(valid, key=lambda x: x[1])
    raw_adj = [0.0] * m
    for rank, (_, p) in enumerate(valid_sorted, start=1):
        raw_adj[rank - 1] = min(1.0, p * m / rank)
    running = 1.0
    for j in range(m - 1, -1, -1):
        running = min(running, raw_adj[j])
        out[valid_sorted[j][0]] = running
    return out


def _round_value(x, digits: int = 6):
    if x is None:
        return None
    if isinstance(x, (bool, str, int)):
        return x
    if isinstance(x, float):
        if not np.isfinite(x):
            return None
        return round(x, digits)
    if isinstance(x, list):
        return [_round_value(v, digits) for v in x]
    if isinstance(x, dict):
        return {k: _round_value(v, digits) for k, v in x.items()}
    return x


def evaluate_signal(
    panel: pd.DataFrame,
    signal: str,
    rng: np.random.Generator,
) -> dict:
    valid = panel.dropna(subset=["next_ret", "fwd5_ret", "fwd5_rv", signal]).copy()
    event_mask = valid[signal].astype(bool)
    comp_mask = ~event_mask
    event = valid.loc[event_mask]
    comp = valid.loc[comp_mask]

    ret_t, ret_p = welch_t(event["next_ret"].values, comp["next_ret"].values)
    fwd5_t, fwd5_p = welch_t(event["fwd5_ret"].values, comp["fwd5_ret"].values)
    logrv_t, logrv_p = welch_t(positive_log(event["fwd5_rv"].values), positive_log(comp["fwd5_rv"].values))
    prop = prop_test((event["next_ret"] < 0).values, (comp["next_ret"] < 0).values)

    return _round_value(
        {
            "n_total": int(len(valid)),
            "n_events": int(len(event)),
            "event_rate": float(len(event) / len(valid)) if len(valid) else None,
            "same_day_mean_ret_descriptive": float(event["ret"].mean()) if len(event) else None,
            "same_day_median_volume_ratio_descriptive": float(event["volume_ratio_60d_median"].median()) if len(event) else None,
            "next_day": {
                "event_mean_ret": float(event["next_ret"].mean()) if len(event) else None,
                "nonevent_mean_ret": float(comp["next_ret"].mean()) if len(comp) else None,
                "mean_diff_event_minus_nonevent": float(event["next_ret"].mean() - comp["next_ret"].mean())
                if len(event) and len(comp)
                else None,
                "welch_t": ret_t,
                "welch_p": ret_p,
                "event_p_down": float((event["next_ret"] < 0).mean()) if len(event) else None,
                "nonevent_p_down": float((comp["next_ret"] < 0).mean()) if len(comp) else None,
                "p_down_diff": float((event["next_ret"] < 0).mean() - (comp["next_ret"] < 0).mean())
                if len(event) and len(comp)
                else None,
                "prop_z": prop["z"],
                "prop_z_p": prop["p"],
                "prop_fisher_p": prop["fisher_p"],
                "event_down_count": prop["event_down_count"],
                "nonevent_down_count": prop["nonevent_down_count"],
                "boot_mean_diff": bootstrap_mean_diff(event["next_ret"].values, comp["next_ret"].values, rng),
                "boot_p_down_diff": bootstrap_prop_diff(
                    (event["next_ret"] < 0).values, (comp["next_ret"] < 0).values, rng
                ),
            },
            "fwd5_return": {
                "event_mean": float(event["fwd5_ret"].mean()) if len(event) else None,
                "nonevent_mean": float(comp["fwd5_ret"].mean()) if len(comp) else None,
                "mean_diff_event_minus_nonevent": float(event["fwd5_ret"].mean() - comp["fwd5_ret"].mean())
                if len(event) and len(comp)
                else None,
                "welch_t": fwd5_t,
                "welch_p": fwd5_p,
                "boot_mean_diff": bootstrap_mean_diff(event["fwd5_ret"].values, comp["fwd5_ret"].values, rng),
            },
            "fwd5_realized_vol": {
                "event_mean_ann": float(event["fwd5_rv"].mean()) if len(event) else None,
                "nonevent_mean_ann": float(comp["fwd5_rv"].mean()) if len(comp) else None,
                "ratio_event_vs_nonevent": float(event["fwd5_rv"].mean() / comp["fwd5_rv"].mean())
                if len(event) and len(comp) and comp["fwd5_rv"].mean() != 0
                else None,
                "welch_logrv_t": logrv_t,
                "welch_logrv_p": logrv_p,
                "boot_mean_diff": bootstrap_mean_diff(event["fwd5_rv"].values, comp["fwd5_rv"].values, rng),
            },
        }
    )


def continuous_regression(panel: pd.DataFrame) -> dict:
    d = panel.dropna(subset=["next_ret", "log_vol_surprise", "ret", "abs_ret"]).copy()
    if len(d) < 100:
        return {}
    X = sm.add_constant(d[["log_vol_surprise", "ret", "abs_ret"]])
    y = d["next_ret"]
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_MAXLAGS_DAILY})

    d2 = panel.dropna(subset=["fwd5_rv", "log_vol_surprise", "ret", "abs_ret"]).copy()
    d2 = d2[d2["fwd5_rv"] > 0].copy()
    X2 = sm.add_constant(d2[["log_vol_surprise", "ret", "abs_ret"]])
    y2 = np.log(d2["fwd5_rv"])
    model2 = sm.OLS(y2, X2).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_MAXLAGS_DAILY})
    return _round_value(
        {
            "spec_next_ret": "next_ret[t+1] ~ log_vol_surprise[t] + ret[t] + abs_ret[t]",
            "n_next_ret": int(len(d)),
            "log_vol_surprise_beta_next_ret": float(model.params["log_vol_surprise"]),
            "log_vol_surprise_t_next_ret": float(model.tvalues["log_vol_surprise"]),
            "log_vol_surprise_p_next_ret": float(model.pvalues["log_vol_surprise"]),
            "r2_next_ret": float(model.rsquared),
            "spec_fwd5_logrv": "log(fwd5_rv[t+1..t+5]) ~ log_vol_surprise[t] + ret[t] + abs_ret[t]",
            "n_fwd5_logrv": int(len(d2)),
            "log_vol_surprise_beta_fwd5_logrv": float(model2.params["log_vol_surprise"]),
            "log_vol_surprise_t_fwd5_logrv": float(model2.tvalues["log_vol_surprise"]),
            "log_vol_surprise_p_fwd5_logrv": float(model2.pvalues["log_vol_surprise"]),
            "r2_fwd5_logrv": float(model2.rsquared),
            "hac_maxlags": HAC_MAXLAGS_DAILY,
        }
    )


def add_primary_q_values(asset_results: dict) -> dict:
    refs = []
    pvals = []
    for asset, payload in asset_results.items():
        for signal in PRIMARY_SIGNALS:
            sig = payload["signals"][signal]
            refs.append((asset, signal, "next_day_mean_welch"))
            pvals.append(sig["next_day"]["welch_p"])
            refs.append((asset, signal, "next_day_down_prop_z"))
            pvals.append(sig["next_day"]["prop_z_p"])

    qvals = bh_adjust(pvals)
    family = []
    for (asset, signal, test), p, q in zip(refs, pvals, qvals):
        asset_results[asset]["signals"][signal]["next_day"][f"{test}_bh_q"] = None if q is None else round(q, 6)
        family.append({"asset": asset, "signal": signal, "test": test, "p": p, "bh_q": None if q is None else round(q, 6)})
    return {"n_tests": len(refs), "method": "Benjamini-Hochberg FDR across primary next-day mean/proportion tests", "tests": family}


def summarize_verdict(asset_results: dict, primary_family: dict) -> dict:
    supporting = []
    reversed_or_null = []
    for test in primary_family["tests"]:
        asset = test["asset"]
        signal = test["signal"]
        q = test["bh_q"]
        nd = asset_results[asset]["signals"][signal]["next_day"]
        direction_ok = False
        if test["test"] == "next_day_mean_welch":
            direction_ok = nd["mean_diff_event_minus_nonevent"] is not None and nd["mean_diff_event_minus_nonevent"] < 0
        elif test["test"] == "next_day_down_prop_z":
            direction_ok = nd["p_down_diff"] is not None and nd["p_down_diff"] > 0
        passed = q is not None and q < 0.05
        row = {**test, "direction_supports_downside": direction_ok}
        if passed and direction_ok:
            supporting.append(row)
        else:
            reversed_or_null.append(row)

    # Volatility is secondary: record whether high-volume down days reliably lift fwd5 RV.
    vol_lift = []
    for asset, payload in asset_results.items():
        for signal in ["volume_q90_down_m2pct", "volume_2x_down_m2pct"]:
            sig = payload["signals"][signal]
            rv = sig["fwd5_realized_vol"]
            p = rv["welch_logrv_p"]
            ratio = rv["ratio_event_vs_nonevent"]
            if p is not None and p < 0.05 and ratio is not None and ratio > 1:
                vol_lift.append({"asset": asset, "signal": signal, "ratio": ratio, "welch_logrv_p": p})

    if not supporting:
        myth_verdict = "not_supported_as_next_day_direction_rule"
    elif len(supporting) < 3:
        myth_verdict = "asset_specific_weak_support_not_general_rule"
    else:
        myth_verdict = "partially_supported_for_next_day_downside"

    return {
        "myth_verdict": myth_verdict,
        "primary_downside_supporting_tests": supporting,
        "secondary_fwd5_vol_lift_tests_raw_p_lt_0_05": vol_lift,
        "interpretation": (
            "High volume is a strong same-day stress/attention marker, but the primary "
            "BH-adjusted next-day direction tests do not justify a general 'volume leads price' "
            "or 'high-volume down day means next-day distribution' rule unless listed in "
            "primary_downside_supporting_tests. Forward volatility evidence is secondary risk "
            "conditioning, not a direction forecast."
        ),
    }


def plot_next_day_means(asset_results: dict, path: Path) -> None:
    rows = []
    for asset, payload in asset_results.items():
        for signal in PRIMARY_SIGNALS:
            sig = payload["signals"][signal]
            rows.append(
                {
                    "asset": asset,
                    "signal": "High volume" if signal == "volume_q90" else "High volume down day",
                    "diff": sig["next_day"]["mean_diff_event_minus_nonevent"] * 100.0,
                    "n": sig["n_events"],
                }
            )
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(rows))
    colors = ["#4c78a8" if r["signal"] == "High volume" else "#c44e52" for r in rows]
    ax.bar(x, [r["diff"] for r in rows], color=colors)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r['asset']}\n{r['signal']}\nn={r['n']}" for r in rows], rotation=0, fontsize=8)
    ax.set_ylabel("Next-day mean return diff vs non-event (pp)")
    ax.set_title("K1636 primary signals: event minus non-event next-day return")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_down_prob(asset_results: dict, path: Path) -> None:
    rows = []
    for asset, payload in asset_results.items():
        for signal in PRIMARY_SIGNALS:
            sig = payload["signals"][signal]
            rows.append(
                {
                    "asset": asset,
                    "signal": "High volume" if signal == "volume_q90" else "High volume down day",
                    "diff": sig["next_day"]["p_down_diff"] * 100.0,
                    "event_p": sig["next_day"]["event_p_down"] * 100.0,
                    "comp_p": sig["next_day"]["nonevent_p_down"] * 100.0,
                    "n": sig["n_events"],
                }
            )
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(rows))
    colors = ["#59a14f" if r["signal"] == "High volume" else "#c44e52" for r in rows]
    ax.bar(x, [r["diff"] for r in rows], color=colors)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r['asset']}\n{r['signal']}\nn={r['n']}" for r in rows], fontsize=8)
    ax.set_ylabel("P(next day down) lift vs non-event (pp)")
    ax.set_title("K1636 primary signals: next-day downside probability lift")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_fwd_vol(asset_results: dict, path: Path) -> None:
    rows = []
    for asset, payload in asset_results.items():
        for signal in ["volume_q90", "volume_q90_down_m2pct", "volume_2x_down_m2pct"]:
            sig = payload["signals"][signal]
            label = {
                "volume_q90": "High volume",
                "volume_q90_down_m2pct": "High volume down day",
                "volume_2x_down_m2pct": "2x volume down day",
            }[signal]
            rows.append(
                {
                    "asset": asset,
                    "signal": label,
                    "ratio": sig["fwd5_realized_vol"]["ratio_event_vs_nonevent"],
                    "n": sig["n_events"],
                }
            )
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(rows))
    ax.bar(x, [r["ratio"] for r in rows], color="#8172b3")
    ax.axhline(1, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r['asset']}\n{r['signal']}\nn={r['n']}" for r in rows], fontsize=7)
    ax.set_ylabel("Forward 5-day RV ratio: event / non-event")
    ax.set_title("K1636 secondary risk result: high-volume events and next-week volatility")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> None:
    rng = np.random.default_rng(SEED)
    asset_results: dict = {}
    data_meta: dict = {}

    for asset, cfg in ASSETS.items():
        panel = build_panel(asset, cfg)
        data_meta[asset] = {
            "symbol": panel.symbol,
            "market": cfg["market"],
            "source": panel.source,
            "raw_period": [panel.start, panel.end],
            "n_raw": panel.n_raw,
            "n_signal_rows": int(len(panel.panel)),
            "volume_note": cfg["volume_note"],
        }
        signals = {}
        for signal in PRIMARY_SIGNALS + SECONDARY_SIGNALS:
            signals[signal] = evaluate_signal(panel.panel, signal, rng)
        asset_results[asset] = {
            "signals": signals,
            "continuous_regression": continuous_regression(panel.panel),
        }

    primary_family = add_primary_q_values(asset_results)
    verdict = summarize_verdict(asset_results, primary_family)

    plot_next_day_means(asset_results, HERE / "fig1_next_day_mean_diff.png")
    plot_down_prob(asset_results, HERE / "fig2_next_day_down_prob_lift.png")
    plot_fwd_vol(asset_results, HERE / "fig3_forward_volatility_ratio.png")

    results = {
        "experiment_id": "k1636",
        "title": "投資迷思驗證：量先價行 / 爆量長黑是出貨",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "assets": data_meta,
            "download_start": START,
            "download_end_exclusive": END,
            "return_type": "simple pct_change on Adj Close when available",
            "seed": SEED,
            "n_bootstrap": N_BOOT,
        },
        "method": {
            "primary_question": "Do volume events at date t predict next-day direction/return?",
            "volume_q90": f"log(volume[t]) >= rolling prior {VOL_Q_WINDOW}d {VOL_Q:.0%} quantile, min {VOL_Q_MIN}; threshold uses shift(1)",
            "volume_2x": f"volume[t] >= {VOL_RATIO_THRESHOLD}x rolling prior {VOL_MED_WINDOW}d median volume, min {VOL_MED_MIN}; threshold uses shift(1)",
            "down_day": f"same-day adjusted close-to-close return <= {DOWN_DAY_THRESHOLD:.0%}; used only as event condition",
            "targets": {
                "next_day": "ret[t+1], aligned to signal date t with pct_change().shift(-1)",
                "fwd5_return": "close[t+5] / close[t] - 1; strictly after signal date",
                "fwd5_realized_vol": "annualized stdev of returns t+1..t+5; strictly forward",
            },
            "primary_multiple_testing": primary_family["method"],
            "same_day_relation": "descriptive only; not treated as prediction evidence",
        },
        "literature_basis": [
            {
                "citation": "Karpoff (1987), The Relation Between Price Changes and Trading Volume, JFQA",
                "role": "Price-volume relation is mostly contemporaneous and volume relates strongly to absolute price changes.",
                "url": "https://www.jstor.org/stable/2330874",
            },
            {
                "citation": "Campbell, Grossman, and Wang (1993), Trading Volume and Serial Correlation in Stock Returns, QJE",
                "role": "High volume can condition return autocorrelation, motivating a short-horizon next-day test.",
                "url": "https://academic.oup.com/qje/article-abstract/108/4/905/1899978",
            },
            {
                "citation": "Lee and Swaminathan (2000), Price Momentum and Trading Volume, Journal of Finance",
                "role": "Volume is linked to momentum persistence at intermediate horizons; this experiment tests whether a daily folk version survives.",
                "url": "https://doi.org/10.1111/0022-1082.00280",
            },
        ],
        "related_project_knowledge": [
            "K113: daily volume/order-flow proxies did not improve next-day volatility prediction in GARCH-X.",
            "K160: volume-volatility relation is mostly contemporaneous; lagged volume has weak predictive value.",
            "K418: Taiwan yfinance volume proxies were comprehensive null for institutional-sentiment-style prediction.",
        ],
        "asset_results": asset_results,
        "primary_family": primary_family,
        "verdict": verdict,
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[K1636] wrote {RESULTS_PATH}")
    print(f"[K1636] verdict={verdict['myth_verdict']}")
    for asset, payload in asset_results.items():
        q = payload["signals"]["volume_q90"]
        d = payload["signals"]["volume_q90_down_m2pct"]
        print(
            f"  {asset}: high-vol n={q['n_events']} next_mean_diff={q['next_day']['mean_diff_event_minus_nonevent']} "
            f"p={q['next_day']['welch_p']} q={q['next_day']['next_day_mean_welch_bh_q']} | "
            f"high-vol-down n={d['n_events']} next_mean_diff={d['next_day']['mean_diff_event_minus_nonevent']} "
            f"p={d['next_day']['welch_p']} q={d['next_day']['next_day_mean_welch_bh_q']}"
        )


if __name__ == "__main__":
    main()
