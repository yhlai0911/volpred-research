#!/usr/bin/env python3
"""Maritime chokepoint stress as a volatility signal.

Question
--------
Can public maritime/supply-chain stress proxies improve forecasts of future
realized variance for commodity, retail, transportation, and shipping ETFs?

This is a proxy diagnostic, not a replication of proprietary Freightos/Harpex
or vessel-tracking studies. Signals are explicitly lagged:

* GSCPI monthly values are assumed available only after month-end + 10 business
  days, then shifted one trading day.
* BDRY shipping-price proxy features use only trailing prices and are shifted.
* Manual event calendar dummies are shifted before they enter any forecast.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = [
    "Arial Unicode MS",
    "PingFang TC",
    "Heiti TC",
    "Microsoft JhengHei",
    "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike_pointwise

SEED = 42
START = "2018-01-01"
END = "2026-06-30"
TRADING_DAYS = 252
INITIAL_TRAIN = 756
MIN_TRAIN = 504
ASSETS = ["USO", "DBA", "XRT", "IYT", "BDRY"]
VIX = "^VIX"
HORIZONS = [5, 22]
SIGNAL_COLUMNS = ["gscpi_z", "bdry_rv_z", "event_z", "maritime_composite_z"]

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

GSCPI_URL = (
    "https://www.newyorkfed.org/medialibrary/research/interactives/"
    "gscpi/downloads/gscpi_data.xlsx"
)


@dataclass(frozen=True)
class Event:
    name: str
    start: str
    end: str
    severity: float
    note: str


EVENTS = [
    Event(
        "Ever Given Suez blockage",
        "2021-03-23",
        "2021-03-29",
        1.0,
        "Suez Canal closure; short but clean chokepoint shock.",
    ),
    Event(
        "Black Sea grain/shipping shock",
        "2022-02-24",
        "2022-08-01",
        0.7,
        "Russia-Ukraine war disrupted grain/oil shipping routes; mixed with war risk.",
    ),
    Event(
        "Panama Canal drought restrictions",
        "2023-08-01",
        "2024-05-31",
        0.8,
        "Low-water transit restrictions and queue delays.",
    ),
    Event(
        "Red Sea / Suez rerouting",
        "2023-11-19",
        "2024-12-31",
        1.0,
        "Red Sea attacks and Suez rerouting; end date is diagnostic cutoff.",
    ),
    Event(
        "Hormuz oil-shipping stress",
        "2026-02-28",
        "2026-03-16",
        1.0,
        "Project event-calendar proxy for Hormuz stress; treated as diagnostic.",
    ),
]


def _download_prices() -> pd.DataFrame:
    cache = DATA_DIR / "yfinance_prices.csv"
    if cache.exists():
        return pd.read_csv(cache, index_col=0, parse_dates=True)

    raw = yf.download(ASSETS + [VIX], start=START, end=END, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = ASSETS + [VIX]
    close = close.dropna(axis=1, how="all")
    close.to_csv(cache, index_label="date")
    return close


def _load_gscpi(daily_index: pd.DatetimeIndex) -> pd.Series:
    cache = DATA_DIR / "gscpi_monthly.csv"
    if cache.exists():
        g = pd.read_csv(cache, parse_dates=["date"])
    else:
        raw = pd.read_excel(GSCPI_URL, sheet_name="GSCPI Monthly Data")
        g = raw[["Date", "GSCPI"]].dropna().copy()
        g.columns = ["date", "gscpi"]
        g["date"] = pd.to_datetime(g["date"])
        g["gscpi"] = pd.to_numeric(g["gscpi"], errors="coerce")
        g = g.dropna().sort_values("date")
        g.to_csv(cache, index=False)

    # Conservative availability: month-end observation becomes usable after
    # ten business days, then daily ffilled. This is intentionally slower than
    # actual NY Fed publication timing to avoid lookahead.
    release_idx = pd.DatetimeIndex(g["date"]) + pd.offsets.BDay(10)
    s = pd.Series(g["gscpi"].to_numpy(dtype=float), index=release_idx, name="gscpi")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.reindex(daily_index).ffill()


def _rolling_z(s: pd.Series, window: int = 756, min_periods: int = 126) -> pd.Series:
    mean = s.rolling(window, min_periods=min_periods).mean()
    std = s.rolling(window, min_periods=min_periods).std()
    z = ((s - mean) / std).replace([np.inf, -np.inf], np.nan)
    # Sparse event dummies can otherwise create 20+ sigma values when the
    # rolling variance is near zero. Winsorize forecast inputs to keep single
    # event-window observations from mechanically dominating OOS regressions.
    return z.clip(lower=-5.0, upper=5.0)


def _future_rv(ret: pd.Series, horizon: int) -> pd.Series:
    # Sum returns from t+1 to t+h, then annualize to daily variance scale.
    return (
        ret.pow(2)
        .shift(-1)
        .rolling(horizon, min_periods=horizon)
        .sum()
        .shift(-(horizon - 1))
        * TRADING_DAYS
        / horizon
    )


def _past_rv(ret: pd.Series, window: int) -> pd.Series:
    return ret.pow(2).rolling(window, min_periods=max(5, window // 2)).mean() * TRADING_DAYS


def _event_signal(index: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(0.0, index=index, name="event_raw")
    for event in EVENTS:
        start, end = pd.Timestamp(event.start), pd.Timestamp(event.end)
        s.loc[(s.index >= start) & (s.index <= end)] += event.severity
        # Keep a modest decay tail: route disruptions usually continue after
        # the first headline shock, but the tail is lower intensity.
        tail_start = end + pd.offsets.BDay(1)
        tail_end = end + pd.offsets.BDay(22)
        s.loc[(s.index >= tail_start) & (s.index <= tail_end)] += event.severity * 0.35
    return s.clip(upper=2.0)


def _build_signals(prices: pd.DataFrame) -> pd.DataFrame:
    idx = prices.index
    logp = np.log(prices)
    ret = logp.diff()
    out = pd.DataFrame(index=idx)
    out["gscpi_z"] = _rolling_z(_load_gscpi(idx)).shift(1)

    bdry_ret = ret["BDRY"]
    bdry_rv = _past_rv(bdry_ret, 21)
    bdry_mom = np.log(prices["BDRY"]).diff(21)
    out["bdry_rv_z"] = _rolling_z(np.log(bdry_rv.replace(0, np.nan))).shift(1)
    out["bdry_mom_z"] = _rolling_z(bdry_mom).shift(1)
    out["event_z"] = _rolling_z(_event_signal(idx), window=756, min_periods=60).shift(1)

    components = out[["gscpi_z", "bdry_rv_z", "bdry_mom_z", "event_z"]]
    out["maritime_composite_z"] = components.mean(axis=1, skipna=True)
    out["maritime_composite_z"] = _rolling_z(out["maritime_composite_z"], min_periods=126)
    return out


def _ols_predict_expanding(df: pd.DataFrame, y_col: str, x_cols: list[str]) -> pd.Series:
    preds = pd.Series(np.nan, index=df.index, name="pred")
    cols = [y_col] + x_cols
    clean = df[cols].replace([np.inf, -np.inf], np.nan)
    x_names = ["const"] + x_cols

    for i in range(INITIAL_TRAIN, len(clean)):
        row = clean.iloc[i]
        if row[x_cols].isna().any():
            continue
        train = clean.iloc[:i].dropna()
        if len(train) < MIN_TRAIN:
            continue
        y = train[y_col].to_numpy(dtype=float)
        x = np.column_stack([np.ones(len(train))] + [train[c].to_numpy(dtype=float) for c in x_cols])
        try:
            beta = np.linalg.lstsq(x, y, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        x_now = np.array([1.0] + [float(row[c]) for c in x_cols], dtype=float)
        pred_log = float(x_now @ beta)
        preds.iloc[i] = float(np.exp(np.clip(pred_log, -30, 5)))

    return preds


def _holm_adjust(rows: list[dict], p_key: str = "dm_p") -> None:
    valid = [(i, r[p_key]) for i, r in enumerate(rows) if np.isfinite(r.get(p_key, np.nan))]
    m = len(valid)
    running = 0.0
    for rank, (i, p) in enumerate(sorted(valid, key=lambda x: x[1]), start=1):
        adj = min(1.0, p * (m - rank + 1))
        running = max(running, adj)
        rows[i]["holm_p"] = float(running)
    for r in rows:
        r.setdefault("holm_p", None)


def _forecast_rv_tests(prices: pd.DataFrame, signals: pd.DataFrame) -> tuple[list[dict], pd.DataFrame]:
    logp = np.log(prices)
    ret = logp.diff()
    vix_var = (prices[VIX] / 100.0).pow(2)
    rows: list[dict] = []
    pred_panel = []

    for asset in ASSETS:
        r = ret[asset]
        base = pd.DataFrame(index=prices.index)
        for w in (5, 22, 63):
            base[f"log_rv_{w}"] = np.log(_past_rv(r, w).replace(0, np.nan)).shift(1)
        base["log_vix_var"] = np.log(vix_var.replace(0, np.nan)).shift(1)

        for horizon in HORIZONS:
            y = _future_rv(r, horizon)
            df = pd.concat([base, signals, y.rename("rv_fwd")], axis=1)
            df["log_rv_fwd"] = np.log(df["rv_fwd"].replace(0, np.nan))
            base_cols = ["log_rv_5", "log_rv_22", "log_rv_63", "log_vix_var"]
            pred_base = _ols_predict_expanding(df, "log_rv_fwd", base_cols)
            loss_base = qlike_pointwise(df["rv_fwd"].to_numpy(), pred_base.to_numpy())

            for signal in SIGNAL_COLUMNS:
                x_cols = base_cols + [signal]
                pred_ext = _ols_predict_expanding(df, "log_rv_fwd", x_cols)
                valid = (
                    np.isfinite(df["rv_fwd"].to_numpy())
                    & np.isfinite(pred_base.to_numpy())
                    & np.isfinite(pred_ext.to_numpy())
                    & (df["rv_fwd"].to_numpy() > 0)
                    & (pred_base.to_numpy() > 0)
                    & (pred_ext.to_numpy() > 0)
                )
                if valid.sum() < 252:
                    continue
                lb = loss_base[valid]
                le = qlike_pointwise(df["rv_fwd"].to_numpy(), pred_ext.to_numpy())[valid]
                dm_t, dm_p = dm_test(le, lb, h=horizon)
                mean_base = float(np.mean(lb))
                mean_ext = float(np.mean(le))
                improvement = (mean_base - mean_ext) / abs(mean_base) if mean_base != 0 else np.nan
                row = {
                    "target": asset,
                    "horizon": horizon,
                    "signal": signal,
                    "n_oos": int(valid.sum()),
                    "qlike_base": mean_base,
                    "qlike_extended": mean_ext,
                    "relative_qlike_improvement": float(improvement),
                    "dm_t_ext_minus_base": float(dm_t),
                    "dm_p": float(dm_p),
                    "harvey_pass": bool(dm_t < -3.0),
                    "oos_start": str(df.index[valid][0].date()),
                    "oos_end": str(df.index[valid][-1].date()),
                }
                rows.append(row)

                if signal == "maritime_composite_z":
                    tmp = pd.DataFrame({
                        "date": df.index[valid],
                        "asset": asset,
                        "horizon": horizon,
                        "rv_fwd": df["rv_fwd"].to_numpy()[valid],
                        "pred_base": pred_base.to_numpy()[valid],
                        "pred_extended": pred_ext.to_numpy()[valid],
                    })
                    pred_panel.append(tmp)

    _holm_adjust(rows)
    panel = pd.concat(pred_panel, ignore_index=True) if pred_panel else pd.DataFrame()
    return rows, panel


def _future_pairwise_corr(ret: pd.DataFrame, horizon: int = 22) -> pd.Series:
    vals = []
    dates = []
    cols = ["USO", "DBA", "XRT", "IYT"]
    for i, dt in enumerate(ret.index):
        sl = ret[cols].iloc[i + 1:i + 1 + horizon].dropna()
        if len(sl) < horizon:
            vals.append(np.nan)
        else:
            c = sl.corr().values
            tri = c[np.triu_indices_from(c, k=1)]
            vals.append(float(np.nanmean(tri)))
        dates.append(dt)
    return pd.Series(vals, index=pd.DatetimeIndex(dates), name="future_corr_22d")


def _forecast_corr_test(prices: pd.DataFrame, signals: pd.DataFrame) -> dict:
    ret = np.log(prices[ASSETS]).diff()
    vix = prices[VIX]
    y = _future_pairwise_corr(ret, horizon=22)

    past_corr = ret[["USO", "DBA", "XRT", "IYT"]].rolling(22).corr()
    corr_vals = []
    for dt in ret.index:
        try:
            mat = past_corr.loc[dt].values
            tri = mat[np.triu_indices_from(mat, k=1)]
            corr_vals.append(float(np.nanmean(tri)) if np.isfinite(tri).any() else np.nan)
        except Exception:
            corr_vals.append(np.nan)
    df = pd.DataFrame(index=ret.index)
    df["future_corr"] = y
    df["past_corr"] = pd.Series(corr_vals, index=ret.index).shift(1)
    df["vix_z"] = _rolling_z(vix).shift(1)
    df["maritime_composite_z"] = signals["maritime_composite_z"]

    pred_base = _ols_predict_expanding(df, "future_corr", ["past_corr", "vix_z"])
    pred_ext = _ols_predict_expanding(df, "future_corr", ["past_corr", "vix_z", "maritime_composite_z"])
    valid = np.isfinite(df["future_corr"]) & np.isfinite(pred_base) & np.isfinite(pred_ext)
    mse_base = (df.loc[valid, "future_corr"] - pred_base.loc[valid]).pow(2).to_numpy()
    mse_ext = (df.loc[valid, "future_corr"] - pred_ext.loc[valid]).pow(2).to_numpy()
    dm_t, dm_p = dm_test(mse_ext, mse_base, h=22)
    return {
        "target": "future_22d_avg_pairwise_corr_USO_DBA_XRT_IYT",
        "n_oos": int(valid.sum()),
        "mse_base": float(np.mean(mse_base)),
        "mse_extended": float(np.mean(mse_ext)),
        "relative_mse_improvement": float((np.mean(mse_base) - np.mean(mse_ext)) / abs(np.mean(mse_base))),
        "dm_t_ext_minus_base": float(dm_t),
        "dm_p": float(dm_p),
        "harvey_pass": bool(dm_t < -3.0),
        "oos_start": str(df.index[valid][0].date()) if valid.any() else None,
        "oos_end": str(df.index[valid][-1].date()) if valid.any() else None,
    }


def _plot_signals(signals: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 5.5))
    cols = ["gscpi_z", "bdry_rv_z", "event_z", "maritime_composite_z"]
    for col in cols:
        ax.plot(signals.index, signals[col], label=col, lw=1.3 if col != "maritime_composite_z" else 2.0)
    ax.axhline(0, color="black", lw=0.8, alpha=0.5)
    ax.set_title("Maritime stress proxy components (all forecast inputs lagged)")
    ax.set_ylabel("rolling z-score")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig_signal_components.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def _plot_improvements(rows: list[dict]) -> None:
    comp = [r for r in rows if r["signal"] == "maritime_composite_z"]
    if not comp:
        return
    df = pd.DataFrame(comp)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    for ax, horizon in zip(axes, HORIZONS):
        d = df[df["horizon"] == horizon].set_index("target").reindex(ASSETS)
        vals = d["relative_qlike_improvement"].to_numpy() * 100
        colors = ["#2b8cbe" if v >= 0 else "#e34a33" for v in vals]
        ax.bar(d.index, vals, color=colors)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title(f"H={horizon}d future RV")
        ax.set_ylabel("QLIKE improvement vs HAR+VIX (%)")
        for i, v in enumerate(vals):
            if np.isfinite(v):
                ax.text(i, v + (0.04 if v >= 0 else -0.04), f"{v:+.2f}", ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=8)
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle("Composite maritime stress adds little OOS forecasting value")
    fig.tight_layout()
    fig.savefig(HERE / "fig_oos_qlike_improvement.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def _plot_corr(prices: pd.DataFrame, signals: pd.DataFrame) -> None:
    ret = np.log(prices[ASSETS]).diff()
    corr = _future_pairwise_corr(ret, 22)
    common = pd.concat([signals["maritime_composite_z"], corr], axis=1).dropna()
    if len(common) < 100:
        return
    fig, ax1 = plt.subplots(figsize=(12, 5.0))
    ax1.plot(common.index, common["maritime_composite_z"], color="#2b8cbe", label="maritime_composite_z")
    ax1.set_ylabel("stress z-score", color="#2b8cbe")
    ax2 = ax1.twinx()
    ax2.plot(common.index, common["future_corr_22d"], color="#e34a33", alpha=0.75,
             label="future 22d avg correlation")
    ax2.set_ylabel("future avg pairwise corr", color="#e34a33")
    ax1.set_title("Stress proxy vs future 22-day commodity/retail/transport correlation")
    ax1.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig_corr_spike_proxy.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    np.random.seed(SEED)
    prices = _download_prices().sort_index()
    prices = prices[[c for c in ASSETS + [VIX] if c in prices.columns]].dropna(how="all")
    signals = _build_signals(prices)
    rows, pred_panel = _forecast_rv_tests(prices, signals)
    corr_test = _forecast_corr_test(prices, signals)

    comp_rows = [r for r in rows if r["signal"] == "maritime_composite_z"]
    harvey_hits = [r for r in rows if r["harvey_pass"]]
    holm_hits = [r for r in rows if r.get("holm_p") is not None and r["holm_p"] < 0.05 and r["dm_t_ext_minus_base"] < 0]
    comp_positive = [r for r in comp_rows if r["relative_qlike_improvement"] > 0]

    _plot_signals(signals)
    _plot_improvements(rows)
    _plot_corr(prices, signals)
    if not pred_panel.empty:
        pred_panel.to_csv(DATA_DIR / "composite_oos_predictions.csv", index=False)

    composite_holm_hits = [r for r in holm_hits if r["signal"] == "maritime_composite_z"]
    gscpi_retail_hits = [
        r for r in holm_hits
        if r["target"] == "XRT" and r["horizon"] == 5 and r["signal"] == "gscpi_z"
    ]

    results = {
        "experiment_id": "research_maritime_chokepoint_stress_commodity_retail_ship",
        "title": "Maritime chokepoint stress as commodity / retail / shipping volatility signal",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data": {
            "price_source": "yfinance auto-adjusted close",
            "assets": ASSETS,
            "vix": VIX,
            "start": START,
            "end": END,
            "actual_price_window": {
                "start": str(prices.index.min().date()),
                "end": str(prices.index.max().date()),
                "trading_days": int(len(prices)),
            },
            "gscpi_source": GSCPI_URL,
            "event_calendar": [event.__dict__ for event in EVENTS],
        },
        "method": {
            "signals": SIGNAL_COLUMNS,
            "lag_rule": "all signal columns are shifted before forecasting; GSCPI release assumed month-end + 10 business days",
            "baseline": "expanding OOS OLS: log future RV ~ log past RV 5/22/63 + log VIX variance",
            "extended": "baseline + one maritime stress proxy",
            "target": "future H-day annualized realized variance from t+1..t+H",
            "loss": "QLIKE on realized variance; DM-HAC via volpred.stats.model_evaluation.dm_test",
            "harvey_gate": "extended model pass only if DM t < -3.0; Holm p reported across all signal/asset/horizon tests",
            "corr_test": "future 22d average pairwise correlation among USO/DBA/XRT/IYT; OOS MSE baseline vs +composite",
        },
        "summary": {
            "n_rv_tests": len(rows),
            "harvey_pass_count": len(harvey_hits),
            "holm_positive_pass_count": len(holm_hits),
            "composite_holm_positive_pass_count": len(composite_holm_hits),
            "composite_positive_cells": len(comp_positive),
            "composite_total_cells": len(comp_rows),
            "verdict": None,
        },
        "rv_forecast_tests": rows,
        "correlation_spike_test": corr_test,
        "figures": [
            "fig_signal_components.png",
            "fig_oos_qlike_improvement.png",
            "fig_corr_spike_proxy.png",
        ],
        "limitations": [
            "BDRY is an ETF/futures proxy for dry bulk shipping, not Freightos/Harpex container-rate data.",
            "Manual event calendar is diagnostic and mixes pure chokepoint shocks with broader geopolitical shocks.",
            "GSCPI is monthly and heavily lagged here; this is conservative but can miss high-frequency disruptions.",
            "BDRY as both signal and target creates a partly self-referential shipping-vol cell; cross-asset cells are more informative.",
        ],
    }

    if len(composite_holm_hits) > 0:
        verdict = "PARTIAL_COMPOSITE_SUPPORT_NEEDS_REPLICATION"
    elif len(gscpi_retail_hits) > 0:
        verdict = "PARTIAL_GSCPI_RETAIL_5D_SUPPORT_NOT_BROAD_CHOKEPOINT_SIGNAL"
    elif len(holm_hits) > 0 or len(harvey_hits) > 0:
        verdict = "PARTIAL_SINGLE_SIGNAL_SUPPORT_NEEDS_REPLICATION"
    elif len(comp_positive) >= max(1, len(comp_rows) // 2):
        verdict = "WEAK_DIRECTIONAL_SUPPORT_NOT_SIGNIFICANT"
    else:
        verdict = "NULL_NO_ROBUST_OOS_VOL_SIGNAL"
    results["summary"]["verdict"] = verdict

    out = HERE / "research_maritime_chokepoint_stress_commodity_retail_ship_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
