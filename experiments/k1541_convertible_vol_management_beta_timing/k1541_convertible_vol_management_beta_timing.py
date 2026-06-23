#!/usr/bin/env python3
"""K1541: convertible-bond volatility management vs equity/credit beta timing.

This experiment uses convertible-bond ETFs as tradable proxies. It does not
claim to replicate individual convertible bonds or convertible arbitrage books.

All portfolio weights are based on information available through t-1:
``asset_vol21_lag = asset_ret.rolling(21).std().shift(1)``. The return dated
t is then ``weight_t * return_t``. This is the trading-rule equivalent of the
project's ``signal.shift(1)`` lookahead guard.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf

from volpred.stats.model_evaluation import strategy_dm_test


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FIG = OUT / "figures"

EXPERIMENT_ID = "K1541"
SLUG = "k1541_convertible_vol_management_beta_timing"
SEED = 42

CB_TICKERS = ["CWB", "ICVT", "CONV"]
FACTOR_TICKERS = ["SPY", "QQQ", "HYG", "LQD"]
STATE_TICKERS = ["^VIX"]
ALL_TICKERS = CB_TICKERS + FACTOR_TICKERS + STATE_TICKERS

START = "2009-01-01"
END = "2026-06-24"
VOL_LOOKBACK = 21
BETA_LOOKBACK = 252
TARGET_VOL = 0.10
MAX_LEVERAGE = 2.0
TX_COST_BPS = 5.0
TX_COST = TX_COST_BPS / 10_000.0
BOOT_REPS = 1000
BOOT_BLOCK = 21
FRED_UMCSENT_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UMCSENT"


@dataclass
class Performance:
    n_days: int
    start: str
    end: str
    cagr: float
    ann_return_arith: float
    ann_vol: float
    sharpe: float
    max_drawdown: float
    mean_daily_return: float
    min_daily_return: float
    max_daily_return: float
    annual_turnover: float | None = None
    mean_exposure: float | None = None
    mean_gross_exposure: float | None = None


@dataclass
class Comparison:
    asset: str
    left: str
    right: str
    n_days: int
    sharpe_diff: float
    mean_ann_return_diff: float
    dm_t_negative_return: float
    dm_p_negative_return: float
    bootstrap_ci_low: float
    bootstrap_ci_high: float
    bootstrap_p_diff_le_0: float
    gate_pass: bool


@dataclass
class AlphaTest:
    asset: str
    model: str
    nobs: int
    alpha_daily: float
    alpha_annualized: float
    alpha_hac_t: float
    beta_to_baseline: float
    r2: float
    gate_pass: bool


def _annualized_sharpe(ret: np.ndarray) -> float:
    arr = np.asarray(ret, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 20:
        return float("nan")
    sd = float(np.std(arr, ddof=1))
    if sd <= 0:
        return float("nan")
    return float(np.mean(arr) / sd * math.sqrt(252))


def _max_drawdown(ret: pd.Series) -> float:
    wealth = (1.0 + ret.fillna(0.0)).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1.0
    return float(dd.min())


def performance(ret: pd.Series, turnover: pd.Series | None = None, exposure: pd.Series | None = None) -> Performance:
    r = ret.replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        raise ValueError("empty return series")
    wealth = float((1.0 + r).prod())
    n = len(r)
    cagr = wealth ** (252.0 / n) - 1.0 if wealth > 0 else float("nan")
    ann_vol = float(r.std(ddof=1) * math.sqrt(252))
    sharpe = float(r.mean() / r.std(ddof=1) * math.sqrt(252)) if r.std(ddof=1) > 0 else float("nan")
    annual_turnover = None
    if turnover is not None:
        annual_turnover = float(turnover.reindex(r.index).fillna(0.0).mean() * 252)
    mean_exposure = None
    mean_gross_exposure = None
    if exposure is not None:
        ex = exposure.reindex(r.index).replace([np.inf, -np.inf], np.nan).dropna()
        if not ex.empty:
            mean_exposure = float(ex.mean())
            mean_gross_exposure = float(ex.abs().mean())
    return Performance(
        n_days=int(n),
        start=str(r.index.min().date()),
        end=str(r.index.max().date()),
        cagr=float(cagr),
        ann_return_arith=float(r.mean() * 252),
        ann_vol=ann_vol,
        sharpe=sharpe,
        max_drawdown=_max_drawdown(r),
        mean_daily_return=float(r.mean()),
        min_daily_return=float(r.min()),
        max_daily_return=float(r.max()),
        annual_turnover=annual_turnover,
        mean_exposure=mean_exposure,
        mean_gross_exposure=mean_gross_exposure,
    )


def load_prices() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")

    close: dict[str, pd.Series] = {}
    volume: dict[str, pd.Series] = {}
    availability: dict[str, Any] = {}
    for ticker in ALL_TICKERS:
        if isinstance(raw.columns, pd.MultiIndex) and ticker in raw.columns.get_level_values(0):
            sub = raw[ticker].copy()
        else:
            availability[ticker] = {"available": False, "reason": "missing in yfinance response"}
            continue
        c = sub["Close"].dropna()
        if c.empty:
            availability[ticker] = {"available": False, "reason": "empty adjusted close"}
            continue
        close[ticker] = sub["Close"]
        volume[ticker] = sub["Volume"] if "Volume" in sub else pd.Series(index=sub.index, dtype=float)
        availability[ticker] = {
            "available": True,
            "n_close": int(c.shape[0]),
            "start": str(pd.to_datetime(c.index.min()).date()),
            "end": str(pd.to_datetime(c.index.max()).date()),
        }

    close_df = pd.DataFrame(close).sort_index()
    volume_df = pd.DataFrame(volume).sort_index()
    close_df.index = pd.to_datetime(close_df.index).tz_localize(None)
    volume_df.index = pd.to_datetime(volume_df.index).tz_localize(None)
    return close_df, volume_df, availability


def load_umcsent(daily_index: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, Any]]:
    response = requests.get(FRED_UMCSENT_URL, timeout=45)
    response.raise_for_status()
    rows = [line.split(",") for line in response.text.strip().splitlines()]
    header = rows[0]
    obs_idx = header.index("observation_date")
    value_idx = header.index("UMCSENT")
    monthly = []
    for row in rows[1:]:
        if len(row) <= value_idx or row[value_idx] in {"", "."}:
            continue
        monthly.append((pd.Timestamp(row[obs_idx]), float(row[value_idx])))
    m = pd.DataFrame(monthly, columns=["date", "umcsent"]).set_index("date").sort_index()
    m["umcsent_lag1m"] = m["umcsent"].shift(1)
    roll = m["umcsent_lag1m"].rolling(120, min_periods=36)
    # Percentile rank within the prior ten-year window. This is conservative:
    # month t uses at most the sentiment observation stamped month t-1.
    m["umcsent_pct_lag"] = roll.apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    daily = m[["umcsent_lag1m", "umcsent_pct_lag"]].reindex(daily_index, method="ffill")
    daily["sentiment_regime"] = np.where(
        daily["umcsent_pct_lag"] >= 0.5,
        "high",
        np.where(daily["umcsent_pct_lag"].notna(), "low", "unknown"),
    )
    meta = {
        "url": FRED_UMCSENT_URL,
        "source": "FRED UMCSENT CSV",
        "monthly_start": str(m.index.min().date()),
        "monthly_end": str(m.index.max().date()),
        "lag_policy": "daily regime uses UMCSENT shifted by one monthly observation before forward fill",
    }
    return daily, meta


def rolling_beta_replication(
    asset_ret: pd.Series,
    factor_ret: pd.DataFrame,
    lookback: int = BETA_LOOKBACK,
) -> tuple[pd.Series, pd.DataFrame]:
    aligned = pd.concat([asset_ret.rename("asset"), factor_ret], axis=1).dropna()
    factor_cols = list(factor_ret.columns)
    rep = pd.Series(np.nan, index=aligned.index, name="beta_rep_gross")
    betas = pd.DataFrame(np.nan, index=aligned.index, columns=factor_cols)
    y_all = aligned["asset"].to_numpy(dtype=float)
    x_all = aligned[factor_cols].to_numpy(dtype=float)
    for i in range(lookback, len(aligned)):
        x_train = x_all[i - lookback : i]
        y_train = y_all[i - lookback : i]
        valid = np.isfinite(y_train) & np.all(np.isfinite(x_train), axis=1)
        if valid.sum() < int(0.8 * lookback):
            continue
        beta = np.linalg.lstsq(x_train[valid], y_train[valid], rcond=None)[0]
        betas.iloc[i] = beta
        rep.iloc[i] = float(x_all[i] @ beta)
    return rep, betas


def strategy_panel_for_asset(
    asset: str,
    returns: pd.DataFrame,
    umcsent_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cols = [asset, *FACTOR_TICKERS]
    data = returns[cols].dropna().copy()
    vol21_lag = data[asset].rolling(VOL_LOOKBACK, min_periods=15).std().mul(math.sqrt(252)).shift(1)
    weight = (TARGET_VOL / vol21_lag).clip(lower=0.0, upper=MAX_LEVERAGE)
    weight = weight.rename("vm_weight")
    raw = data[asset].rename("raw_cb")
    weight_turnover = weight.diff().abs().fillna(weight.abs())
    vm_cb = (weight * raw - TX_COST * weight_turnover).rename("vm_cb_net")
    rep_gross, betas = rolling_beta_replication(raw, data[FACTOR_TICKERS])
    beta_turnover = betas.diff().abs().sum(axis=1).fillna(betas.abs().sum(axis=1))
    beta_rep = (rep_gross - TX_COST * beta_turnover).rename("beta_rep_net")
    combined_betas = betas.mul(weight, axis=0)
    combined_turnover = combined_betas.diff().abs().sum(axis=1).fillna(combined_betas.abs().sum(axis=1))
    vm_beta = (weight * rep_gross - TX_COST * combined_turnover).rename("vm_beta_rep_net")

    panel = pd.concat(
        [
            raw,
            vm_cb,
            beta_rep,
            vm_beta,
            weight,
            weight_turnover.rename("vm_weight_turnover"),
            beta_turnover.rename("beta_turnover"),
            combined_turnover.rename("vm_beta_turnover"),
            rep_gross,
            betas.add_prefix("beta_"),
            umcsent_daily[["umcsent_lag1m", "umcsent_pct_lag", "sentiment_regime"]],
        ],
        axis=1,
        sort=False,
    ).dropna(subset=["raw_cb", "vm_cb_net", "beta_rep_net", "vm_beta_rep_net"])
    panel = panel[panel.index >= data.index.min()].copy()
    meta = {
        "asset": asset,
        "effective_start": str(panel.index.min().date()) if not panel.empty else None,
        "effective_end": str(panel.index.max().date()) if not panel.empty else None,
        "n_days": int(len(panel)),
        "target_vol": TARGET_VOL,
        "vol_lookback_days": VOL_LOOKBACK,
        "beta_lookback_days": BETA_LOOKBACK,
        "max_leverage": MAX_LEVERAGE,
        "transaction_cost_bps_per_100pct_turnover": TX_COST_BPS,
    }
    return panel, meta


def bootstrap_sharpe_diff(
    left: pd.Series,
    right: pd.Series,
    reps: int = BOOT_REPS,
    block: int = BOOT_BLOCK,
    seed: int = SEED,
) -> tuple[float, float, float]:
    data = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna()
    arr = data.to_numpy(dtype=float)
    n = len(arr)
    rng = np.random.default_rng(seed)
    diffs = np.empty(reps)
    starts = np.arange(n)
    for b in range(reps):
        chunks = []
        while sum(len(c) for c in chunks) < n:
            start = int(rng.choice(starts))
            idx = (np.arange(start, start + block) % n).astype(int)
            chunks.append(arr[idx])
        sample = np.vstack(chunks)[:n]
        diffs[b] = _annualized_sharpe(sample[:, 0]) - _annualized_sharpe(sample[:, 1])
    low, high = np.quantile(diffs, [0.025, 0.975])
    p_le_zero = float(np.mean(diffs <= 0.0))
    return float(low), float(high), p_le_zero


def compare(asset: str, panel: pd.DataFrame, left: str, right: str) -> Comparison:
    data = panel[[left, right]].dropna()
    left_ret = data[left]
    right_ret = data[right]
    dm_t, dm_p = strategy_dm_test(left_ret.to_numpy(), right_ret.to_numpy(), h=1, loss_fn="negative_return")
    ci_low, ci_high, p_le_zero = bootstrap_sharpe_diff(left_ret, right_ret)
    sharpe_diff = _annualized_sharpe(left_ret.to_numpy()) - _annualized_sharpe(right_ret.to_numpy())
    mean_diff = float((left_ret.mean() - right_ret.mean()) * 252)
    gate_pass = bool(sharpe_diff > 0 and ci_low > 0 and dm_t <= -3.0)
    return Comparison(
        asset=asset,
        left=left,
        right=right,
        n_days=int(len(data)),
        sharpe_diff=float(sharpe_diff),
        mean_ann_return_diff=mean_diff,
        dm_t_negative_return=float(dm_t),
        dm_p_negative_return=float(dm_p),
        bootstrap_ci_low=ci_low,
        bootstrap_ci_high=ci_high,
        bootstrap_p_diff_le_0=p_le_zero,
        gate_pass=gate_pass,
    )


def alpha_test(asset: str, panel: pd.DataFrame, y_col: str, x_col: str) -> AlphaTest:
    data = panel[[y_col, x_col]].replace([np.inf, -np.inf], np.nan).dropna()
    y = data[y_col]
    x = sm.add_constant(data[[x_col]], has_constant="add")
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    alpha = float(model.params["const"])
    alpha_t = float(model.tvalues["const"])
    beta = float(model.params[x_col])
    return AlphaTest(
        asset=asset,
        model=f"{y_col} ~ {x_col}",
        nobs=int(model.nobs),
        alpha_daily=alpha,
        alpha_annualized=float(alpha * 252),
        alpha_hac_t=alpha_t,
        beta_to_baseline=beta,
        r2=float(model.rsquared),
        gate_pass=bool(alpha > 0 and alpha_t >= 3.0),
    )


def descriptive_stats(asset: str, panel: pd.DataFrame, returns: pd.DataFrame) -> dict[str, Any]:
    factor_cols = FACTOR_TICKERS
    corr = returns[[asset, *factor_cols]].dropna().corr().loc[asset, factor_cols].to_dict()
    beta_cols = [f"beta_{f}" for f in factor_cols]
    beta_summary = panel[beta_cols].describe(percentiles=[0.1, 0.5, 0.9]).to_dict()
    return {
        "asset": asset,
        "raw_performance": asdict(performance(panel["raw_cb"])),
        "correlations_with_factors": {k: float(v) for k, v in corr.items()},
        "rolling_beta_summary": {
            col.replace("beta_", ""): {k: float(v) for k, v in vals.items() if np.isfinite(v)}
            for col, vals in beta_summary.items()
        },
        "mean_vix_when_weight_below_0_75": None,
        "mean_vix_when_weight_above_1_25": None,
    }


def regime_metrics(asset: str, panel: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for regime in ["high", "low"]:
        sub = panel[panel["sentiment_regime"] == regime]
        if len(sub) < 252:
            continue
        out[regime] = {
            "n_days": int(len(sub)),
            "raw_cb": asdict(performance(sub["raw_cb"])),
            "vm_cb_net": asdict(
                performance(
                    sub["vm_cb_net"],
                    turnover=sub["vm_weight_turnover"],
                    exposure=sub["vm_weight"],
                )
            ),
            "vm_beta_rep_net": asdict(
                performance(
                    sub["vm_beta_rep_net"],
                    turnover=sub["vm_beta_turnover"],
                    exposure=sub[[f"beta_{f}" for f in FACTOR_TICKERS]].mul(sub["vm_weight"], axis=0).abs().sum(axis=1),
                )
            ),
            "vm_minus_raw_ann_return": float((sub["vm_cb_net"].mean() - sub["raw_cb"].mean()) * 252),
            "vm_minus_beta_ann_return": float((sub["vm_cb_net"].mean() - sub["vm_beta_rep_net"].mean()) * 252),
        }
    return {"asset": asset, "regimes": out}


def build_figures(asset_panels: dict[str, pd.DataFrame], perf_table: pd.DataFrame, comparisons: list[Comparison]) -> list[str]:
    FIG.mkdir(exist_ok=True)
    paths: list[str] = []

    fig, ax = plt.subplots(figsize=(11, 5))
    for asset, panel in asset_panels.items():
        panel["vm_weight"].rolling(21).mean().plot(ax=ax, label=asset)
    ax.axhline(1.0, color="#333333", linewidth=1, linestyle="--")
    ax.set_title("K1541: lagged 21d volatility-management weights")
    ax.set_ylabel("portfolio weight, capped at 2.0x")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = FIG / "k1541_vm_weights.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    sharpe = perf_table.pivot(index="strategy", columns="asset", values="sharpe")
    order = ["raw_cb", "vm_cb_net", "beta_rep_net", "vm_beta_rep_net"]
    sharpe = sharpe.reindex(order)
    fig, ax = plt.subplots(figsize=(10, 5.4))
    sharpe.plot(kind="bar", ax=ax, color=["#2E6F9E", "#C47B32", "#4F7D4A"])
    ax.axhline(0, color="#333333", linewidth=1)
    ax.set_title("K1541: net Sharpe comparison")
    ax.set_ylabel("annualized Sharpe")
    ax.set_xlabel("")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG / "k1541_sharpe_comparison.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    fig, ax = plt.subplots(figsize=(11, 5))
    for asset, panel in asset_panels.items():
        rel = (1.0 + panel["vm_cb_net"].fillna(0.0)).cumprod() / (
            1.0 + panel["vm_beta_rep_net"].fillna(0.0)
        ).cumprod()
        rel.plot(ax=ax, label=asset)
    ax.axhline(1.0, color="#333333", linewidth=1, linestyle="--")
    ax.set_title("K1541: convertible VM relative to VM beta replication")
    ax.set_ylabel("relative wealth, VM CB / VM beta replication")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = FIG / "k1541_vm_vs_beta_relative_wealth.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    comp_df = pd.DataFrame([asdict(c) for c in comparisons])
    comp_df = comp_df[comp_df["right"] == "vm_beta_rep_net"].copy()
    if not comp_df.empty:
        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        labels = comp_df["asset"].tolist()
        vals = comp_df["sharpe_diff"].to_numpy()
        lows = vals - comp_df["bootstrap_ci_low"].to_numpy()
        highs = comp_df["bootstrap_ci_high"].to_numpy() - vals
        ax.bar(labels, vals, color="#7A5C9E")
        ax.errorbar(labels, vals, yerr=[lows, highs], fmt="none", ecolor="#222222", capsize=5)
        ax.axhline(0, color="#333333", linewidth=1)
        ax.set_title("K1541: Sharpe edge over VM beta baseline")
        ax.set_ylabel("Sharpe difference, 95% block bootstrap CI")
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        path = FIG / "k1541_sharpe_diff_bootstrap.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(ROOT)))

    return paths


def main() -> None:
    np.random.seed(SEED)
    close, volume, availability = load_prices()
    returns = close.pct_change(fill_method=None)
    umcsent_daily, umcsent_meta = load_umcsent(close.index)

    available_cb = [
        ticker
        for ticker in CB_TICKERS
        if ticker in returns.columns and returns[ticker].dropna().shape[0] >= BETA_LOOKBACK + 252
    ]
    unavailable_cb = [ticker for ticker in CB_TICKERS if ticker not in available_cb]

    asset_panels: dict[str, pd.DataFrame] = {}
    asset_meta: dict[str, Any] = {}
    for asset in available_cb:
        panel, meta = strategy_panel_for_asset(asset, returns, umcsent_daily)
        if len(panel) < 756:
            availability[asset]["available"] = False
            availability[asset]["reason"] = "insufficient effective sample after beta lookback"
            unavailable_cb.append(asset)
            continue
        asset_panels[asset] = panel
        asset_meta[asset] = meta

    perf_rows: list[dict[str, Any]] = []
    descriptions: list[dict[str, Any]] = []
    comparisons: list[Comparison] = []
    alphas: list[AlphaTest] = []
    regimes: list[dict[str, Any]] = []

    for asset, panel in asset_panels.items():
        descriptions.append(descriptive_stats(asset, panel, returns))
        strategies = {
            "raw_cb": (panel["raw_cb"], None, None),
            "vm_cb_net": (panel["vm_cb_net"], panel["vm_weight_turnover"], panel["vm_weight"]),
            "beta_rep_net": (
                panel["beta_rep_net"],
                panel["beta_turnover"],
                panel[[f"beta_{f}" for f in FACTOR_TICKERS]].abs().sum(axis=1),
            ),
            "vm_beta_rep_net": (
                panel["vm_beta_rep_net"],
                panel["vm_beta_turnover"],
                panel[[f"beta_{f}" for f in FACTOR_TICKERS]].mul(panel["vm_weight"], axis=0).abs().sum(axis=1),
            ),
        }
        for name, (ret, turn, exp) in strategies.items():
            row = asdict(performance(ret, turnover=turn, exposure=exp))
            row.update({"asset": asset, "strategy": name})
            perf_rows.append(row)

        for left, right in [
            ("vm_cb_net", "raw_cb"),
            ("vm_cb_net", "beta_rep_net"),
            ("vm_cb_net", "vm_beta_rep_net"),
            ("raw_cb", "beta_rep_net"),
        ]:
            comparisons.append(compare(asset, panel, left, right))
        alphas.append(alpha_test(asset, panel, "vm_cb_net", "vm_beta_rep_net"))
        alphas.append(alpha_test(asset, panel, "raw_cb", "beta_rep_net"))
        regimes.append(regime_metrics(asset, panel))

    perf_table = pd.DataFrame(perf_rows)
    figures = build_figures(asset_panels, perf_table, comparisons)

    panel_paths: dict[str, str] = {}
    for asset, panel in asset_panels.items():
        path = OUT / f"{SLUG}_{asset.lower()}_daily_panel.csv"
        panel.to_csv(path, index_label="date")
        panel_paths[asset] = str(path.relative_to(ROOT))

    all_vm_vs_beta = [c for c in comparisons if c.left == "vm_cb_net" and c.right == "vm_beta_rep_net"]
    any_specific_pass = any(c.gate_pass for c in all_vm_vs_beta) or any(
        a.gate_pass for a in alphas if a.model == "vm_cb_net ~ vm_beta_rep_net"
    )
    any_vm_vs_raw_pass = any(c.gate_pass for c in comparisons if c.left == "vm_cb_net" and c.right == "raw_cb")

    if any_specific_pass:
        verdict = "CONVERTIBLE_VM_SPECIFIC_EDGE"
    elif any_vm_vs_raw_pass:
        verdict = "VM_EDGE_EXPLAINED_BY_BETA_TIMING"
    else:
        verdict = "NULL_OR_BETA_TIMING_DOMINATED"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "slug": SLUG,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": SEED,
        "verdict": verdict,
        "data": {
            "price_source": "yfinance adjusted daily close via yf.download(auto_adjust=True)",
            "requested_start": START,
            "requested_end": END,
            "availability": availability,
            "available_convertible_etfs_used": sorted(asset_panels.keys()),
            "unavailable_or_excluded_convertible_etfs": unavailable_cb,
            "umcsent": umcsent_meta,
            "volume_rows": {ticker: int(volume[ticker].dropna().shape[0]) for ticker in volume.columns},
        },
        "method": {
            "objective": "test whether convertible ETF volatility-management survives an equal equity/credit beta baseline",
            "convertible_proxy_warning": "ETF proxy only; no claim about individual convertible-bond replication or arbitrage books",
            "volatility_management": {
                "weight_formula": "clip(0.10 / asset_ret.rolling(21).std().sqrt252.shift(1), 0, 2)",
                "lookahead_guard": "asset_vol21_lag uses .shift(1); strategy return at t multiplies lagged weight_t by return_t",
                "target_annual_vol": TARGET_VOL,
                "max_leverage": MAX_LEVERAGE,
            },
            "beta_replication": {
                "factors": FACTOR_TICKERS,
                "window_days": BETA_LOOKBACK,
                "estimation": "rolling no-intercept OLS using observations t-252 through t-1",
                "baselines": [
                    "beta_rep_net: rolling beta factor basket minus turnover costs",
                    "vm_beta_rep_net: same lagged VM scalar applied to rolling beta factor basket",
                ],
            },
            "transaction_cost": {
                "bps_per_100pct_turnover": TX_COST_BPS,
                "raw_cb": "buy-and-hold adjusted ETF return, no daily turnover charge",
                "vm_cb_net": "cost on absolute change in VM weight",
                "beta_rep_net": "cost on sum absolute rolling factor-weight changes",
                "vm_beta_rep_net": "cost on sum absolute combined VM-factor weight changes",
            },
            "tests": {
                "dm": "volpred.stats.model_evaluation.strategy_dm_test(loss_fn='negative_return'); negative t means left strategy better",
                "bootstrap": f"{BOOT_REPS} circular {BOOT_BLOCK}-day block-bootstrap Sharpe-difference CI, seed={SEED}",
                "gate": "specific convertible VM edge requires Sharpe diff > 0, 95% CI lower > 0, and DM t <= -3 versus vm_beta_rep_net",
                "alpha": "HAC(maxlags=5) alpha of vm_cb_net on vm_beta_rep_net; alpha t >= 3 required for alpha gate",
            },
        },
        "asset_meta": asset_meta,
        "descriptive_stats": descriptions,
        "performance": perf_table.to_dict(orient="records"),
        "comparisons": [asdict(c) for c in comparisons],
        "alpha_tests": [asdict(a) for a in alphas],
        "sentiment_regime": regimes,
        "summary": {
            "vm_vs_beta_gate_pass_assets": [c.asset for c in all_vm_vs_beta if c.gate_pass],
            "vm_vs_raw_gate_pass_assets": [
                c.asset for c in comparisons if c.left == "vm_cb_net" and c.right == "raw_cb" and c.gate_pass
            ],
            "interpretation": (
                "The test is deliberately conservative. A convertible-specific claim is allowed only "
                "if the VM ETF strategy beats the same lagged VM scalar applied to a rolling "
                "SPY/QQQ/HYG/LQD beta replication. Otherwise the result is treated as beta timing "
                "or a null result rather than convertible-bond alpha."
            ),
        },
        "outputs": {
            "daily_panels": panel_paths,
            "figures": figures,
        },
        "limitations": [
            "CWB and ICVT are ETF proxies; CONV had no yfinance adjusted-close history in this run.",
            "Adjusted close includes ETF expense effects but not borrow or financing costs for leverage above 1x.",
            "Rolling ETF beta replication is a liquid proxy baseline, not a full convertible-bond structural model.",
            "UMCSENT is monthly and lagged one observation; AAII was not used because this run used only stable free CSV/API sources.",
            "The design tests daily ETF timing, not individual bond issue selection, call features, or delta/credit hedging.",
        ],
    }

    out_path = OUT / f"{SLUG}_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "verdict": verdict, "results": str(out_path)}, indent=2))


if __name__ == "__main__":
    main()
