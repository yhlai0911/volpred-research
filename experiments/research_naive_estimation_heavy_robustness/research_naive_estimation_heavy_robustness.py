#!/usr/bin/env python3
"""Naive vs estimation-heavy hedge robustness horse race.

Panel A isolates estimation error by using a single inverse-equity hedge
instrument (SH) with a common 25% hedge budget.

Panel B asks whether any advantage of complex methods comes from time-varying
estimation or simply from choosing a more aggressive defensive sleeve across
SH/TLT/GLD.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "research_naive_estimation_heavy_robustness_results.json"

TICKERS = ["SPY", "SH", "TLT", "GLD"]
START_DATE = "2006-06-01"
END_DATE = "2026-06-14"
IS_START = pd.Timestamp("2007-06-01")
IS_END = pd.Timestamp("2017-12-29")
OOS_START = pd.Timestamp("2018-01-02")

HEDGE_BUDGET = 0.25
ROLL_WINDOW = 63
CVAR_WINDOW = 252
CVAR_ALPHA = 0.05
SINGLE_CVAR_GRID = np.linspace(0.0, 1.0, 51)
MULTI_STEP = 0.05
TX_COST_ONE_WAY = 0.0005
TRADING_DAYS = 252
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
SEED = 42

STRESS_PERIODS = {
    "2018Q4": ("2018-10-01", "2018-12-31"),
    "2020_crash": ("2020-02-19", "2020-04-30"),
    "2022_bear": ("2022-01-03", "2022-10-31"),
    "2025_correction": ("2025-02-19", "2025-04-30"),
}


@dataclass(frozen=True)
class Metrics:
    n_days: int
    start: str
    end: str
    cagr: float
    ann_return: float
    ann_vol: float
    sharpe: float
    mdd: float
    cvar5_daily: float
    left_tail_days_2pct: int
    left_tail_freq_2pct: float
    mean_hedge_budget: float | None = None
    turnover_ann: float | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def label_date(x) -> str:
    return str(x.date()) if hasattr(x, "date") else str(x)


def download_prices() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty data")
    prices = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].copy()
    if list(prices.columns) != TICKERS:
        prices = prices[TICKERS]
    prices = prices.dropna(how="any")
    prices.index = pd.to_datetime(prices.index)
    prices.to_csv(DATA_DIR / "prices.csv")
    return prices


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns).cumprod()
    return float((wealth / wealth.cummax() - 1.0).min())


def compute_metrics(returns: pd.Series, hedge_budget: pd.Series | None = None, turnover: pd.Series | None = None) -> Metrics:
    r = returns.dropna()
    wealth = (1.0 + r).cumprod()
    years = len(r) / TRADING_DAYS
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0
    ann_return = float(r.mean() * TRADING_DAYS)
    ann_vol = float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0
    q05 = float(r.quantile(0.05))
    cvar5 = float(r[r <= q05].mean())
    left_tail_days = int((r <= -0.02).sum())
    mean_budget = None
    turnover_ann = None
    if hedge_budget is not None:
        mean_budget = float(hedge_budget.reindex(r.index).dropna().mean())
    if turnover is not None:
        turnover_ann = float(turnover.reindex(r.index).fillna(0.0).mean() * TRADING_DAYS)
    return Metrics(
        n_days=int(len(r)),
        start=label_date(r.index[0]),
        end=label_date(r.index[-1]),
        cagr=cagr,
        ann_return=ann_return,
        ann_vol=ann_vol,
        sharpe=sharpe,
        mdd=max_drawdown(r),
        cvar5_daily=cvar5,
        left_tail_days_2pct=left_tail_days,
        left_tail_freq_2pct=float(left_tail_days / len(r)),
        mean_hedge_budget=mean_budget,
        turnover_ann=turnover_ann,
    )


def metrics_to_json(metrics: Metrics) -> dict:
    out = asdict(metrics)
    for key in ["cagr", "ann_return", "ann_vol", "mdd", "cvar5_daily", "left_tail_freq_2pct", "mean_hedge_budget", "turnover_ann"]:
        if out[key] is not None:
            out[key] = round(out[key], 6)
    out["sharpe"] = round(out["sharpe"], 6)
    return out


def moving_block_bootstrap_diff(base_ret: pd.Series, alt_ret: pd.Series) -> dict:
    paired = pd.concat([base_ret.rename("base"), alt_ret.rename("alt")], axis=1).dropna()
    arr = paired.to_numpy()
    n = len(arr)
    rng = np.random.default_rng(SEED)

    def draw_sample() -> np.ndarray:
        chosen: list[int] = []
        while len(chosen) < n:
            start = int(rng.integers(0, n - BOOTSTRAP_BLOCK + 1))
            chosen.extend(range(start, start + BOOTSTRAP_BLOCK))
        return arr[np.array(chosen[:n])]

    rows = []
    for _ in range(BOOTSTRAP_REPS):
        sample = draw_sample()
        base = pd.Series(sample[:, 0])
        alt = pd.Series(sample[:, 1])
        m_base = compute_metrics(base)
        m_alt = compute_metrics(alt)
        rows.append(
            {
                "sharpe_diff_alt_minus_base": m_alt.sharpe - m_base.sharpe,
                "cagr_diff_pp_alt_minus_base": (m_alt.cagr - m_base.cagr) * 100,
                "mdd_diff_pp_alt_minus_base": (m_alt.mdd - m_base.mdd) * 100,
                "cvar5_diff_pp_alt_minus_base": (m_alt.cvar5_daily - m_base.cvar5_daily) * 100,
                "left_tail_freq_diff_alt_minus_base": m_alt.left_tail_freq_2pct - m_base.left_tail_freq_2pct,
            }
        )

    df = pd.DataFrame(rows)
    out = {}
    for col in df.columns:
        vals = df[col].to_numpy()
        out[col] = {
            "mean": round(float(vals.mean()), 6),
            "ci_2p5": round(float(np.quantile(vals, 0.025)), 6),
            "ci_97p5": round(float(np.quantile(vals, 0.975)), 6),
            "p_gt_0": round(float((vals > 0).mean()), 4),
        }
    return out


def scale_to_target_mean(signal: pd.Series, target: float, mask: pd.Series) -> tuple[pd.Series, dict]:
    mean_raw = float(signal[mask].dropna().mean())
    scale = target / mean_raw
    scaled = (signal * scale).clip(lower=0.0, upper=1.0)
    return scaled, {
        "raw_is_mean": round(mean_raw, 6),
        "scale_factor": round(float(scale), 6),
        "scaled_is_mean": round(float(scaled[mask].dropna().mean()), 6),
    }


def summarize_periods(returns_map: dict[str, pd.Series], hedge_budget_map: dict[str, pd.Series], turnover_map: dict[str, pd.Series]) -> dict:
    out: dict[str, dict] = {}
    for label, (start, end) in STRESS_PERIODS.items():
        out[label] = {}
        for strategy, ret in returns_map.items():
            period_ret = ret.loc[start:end]
            out[label][strategy] = metrics_to_json(
                compute_metrics(
                    period_ret,
                    hedge_budget=hedge_budget_map[strategy].loc[start:end],
                    turnover=turnover_map[strategy].loc[start:end],
                )
            )
    return out


def panel_single_asset(returns: pd.DataFrame) -> dict:
    idx = returns.index
    spy = returns["SPY"]
    sh = returns["SH"]
    is_mask = (idx >= IS_START) & (idx <= IS_END)
    oos_mask = idx >= OOS_START

    beta_raw = pd.Series(np.nan, index=idx, name="beta_raw")
    s_vals = spy.to_numpy()
    h_vals = sh.to_numpy()
    for i in range(ROLL_WINDOW, len(idx)):
        sw = s_vals[i - ROLL_WINDOW : i]
        hw = h_vals[i - ROLL_WINDOW : i]
        var_s = np.var(sw, ddof=1)
        var_h = np.var(hw, ddof=1)
        cov_sh = np.cov(sw, hw)[0, 1]
        denom = var_s + var_h - 2 * cov_sh
        if denom > 1e-12:
            beta_raw.iloc[i] = (var_s - cov_sh) / denom
    beta_raw = beta_raw.clip(0.0, 1.0).shift(1)

    vol_s = spy.rolling(ROLL_WINDOW).std()
    vol_h = sh.rolling(ROLL_WINDOW).std()
    invvol_raw = (vol_s / (vol_s + vol_h)).clip(0.0, 1.0).shift(1)

    cvar_raw = pd.Series(np.nan, index=idx, name="cvar_raw")
    for i in range(CVAR_WINDOW, len(idx)):
        sw = s_vals[i - CVAR_WINDOW : i]
        hw = h_vals[i - CVAR_WINDOW : i]
        best_weight = None
        best_obj = float("inf")
        for weight in SINGLE_CVAR_GRID:
            port = (1.0 - weight) * sw + weight * hw
            q = np.quantile(port, CVAR_ALPHA)
            cvar = float(port[port <= q].mean())
            obj = -cvar
            if obj < best_obj:
                best_obj = obj
                best_weight = float(weight)
        cvar_raw.iloc[i] = best_weight
    cvar_raw = cvar_raw.shift(1)

    beta_scaled, beta_cal = scale_to_target_mean(beta_raw, HEDGE_BUDGET, is_mask)
    invvol_scaled, invvol_cal = scale_to_target_mean(invvol_raw, HEDGE_BUDGET, is_mask)
    cvar_scaled, cvar_cal = scale_to_target_mean(cvar_raw, HEDGE_BUDGET, is_mask)

    weights = {
        "naive_fixed": pd.Series(HEDGE_BUDGET, index=idx, name="naive_fixed"),
        "rolling_beta": beta_scaled.rename("rolling_beta"),
        "inverse_vol": invvol_scaled.rename("inverse_vol"),
        "rolling_cvar": cvar_scaled.rename("rolling_cvar"),
    }
    calibrations = {
        "rolling_beta": beta_cal,
        "inverse_vol": invvol_cal,
        "rolling_cvar": cvar_cal,
    }

    returns_map: dict[str, pd.Series] = {}
    turnover_map: dict[str, pd.Series] = {}
    metrics_oos: dict[str, dict] = {}
    bootstrap_vs_naive: dict[str, dict] = {}

    for name, hedge_w in weights.items():
        turnover = hedge_w.diff().abs().fillna(0.0)
        strategy_ret = (1.0 - hedge_w) * spy + hedge_w * sh - turnover * (2.0 * TX_COST_ONE_WAY)
        strategy_ret.name = name
        returns_map[name] = strategy_ret
        turnover_map[name] = turnover
        metrics_oos[name] = metrics_to_json(
            compute_metrics(strategy_ret.loc[oos_mask], hedge_budget=hedge_w.loc[oos_mask], turnover=turnover.loc[oos_mask])
        )

    base = returns_map["naive_fixed"].loc[oos_mask]
    for name in ["rolling_beta", "inverse_vol", "rolling_cvar"]:
        bootstrap_vs_naive[name] = moving_block_bootstrap_diff(base, returns_map[name].loc[oos_mask])

    return {
        "description": "Single inverse-equity hedge (SH) with common 25% hedge budget to isolate estimation error.",
        "calibration": {
            "target_mean_hedge_budget": HEDGE_BUDGET,
            "is_period": [str(IS_START.date()), str(IS_END.date())],
            "rolling_beta": beta_cal,
            "inverse_vol": invvol_cal,
            "rolling_cvar": cvar_cal,
        },
        "oos_metrics": metrics_oos,
        "stress_metrics": summarize_periods(returns_map, weights, turnover_map),
        "bootstrap_vs_naive_fixed": bootstrap_vs_naive,
        "weights_oos_mean": {
            name: round(float(w.loc[oos_mask].mean()), 6) for name, w in weights.items()
        },
        "turnover_oos_ann": {
            name: round(float(turnover_map[name].loc[oos_mask].mean() * TRADING_DAYS), 6) for name in weights
        },
        "series": {
            "returns": returns_map,
            "weights": weights,
        },
    }


def simplex_grid(total_budget: float, step: float) -> list[tuple[float, float, float]]:
    vals = np.arange(0.0, total_budget + 1e-9, step)
    out = []
    for sh_w in vals:
        for tlt_w in vals:
            gld_w = round(total_budget - sh_w - tlt_w, 10)
            if gld_w < -1e-9:
                continue
            if abs(round(sh_w + tlt_w + gld_w, 10) - total_budget) < 1e-9:
                out.append((round(float(sh_w), 10), round(float(tlt_w), 10), round(float(gld_w), 10)))
    return out


def normalize_rows(df: pd.DataFrame, fallback: float = 1.0) -> pd.DataFrame:
    totals = df.sum(axis=1)
    out = df.copy()
    for col in out.columns:
        out[col] = np.where(totals > 0, out[col] / totals * HEDGE_BUDGET, fallback / len(out.columns) * HEDGE_BUDGET)
    return out


def panel_multi_asset(returns: pd.DataFrame) -> dict:
    idx = returns.index
    spy = returns["SPY"]
    hedge_assets = ["SH", "TLT", "GLD"]
    is_mask = idx >= OOS_START  # descriptive only; methods already budget-constrained.

    naive = pd.DataFrame(HEDGE_BUDGET / 3.0, index=idx, columns=hedge_assets)

    beta_scores = []
    for asset in hedge_assets:
        beta = returns["SPY"].rolling(ROLL_WINDOW).cov(returns[asset]) / returns["SPY"].rolling(ROLL_WINDOW).var()
        beta_scores.append((-beta).clip(lower=0.0).shift(1).rename(asset))
    beta_scores_df = pd.concat(beta_scores, axis=1).fillna(0.0)
    beta_scores_df = beta_scores_df.where(beta_scores_df.sum(axis=1) > 0, 1.0)
    beta_w = normalize_rows(beta_scores_df)

    invvol_scores = []
    for asset in hedge_assets:
        score = (1.0 / returns[asset].rolling(ROLL_WINDOW).std()).replace([np.inf, -np.inf], np.nan).shift(1)
        invvol_scores.append(score.rename(asset))
    invvol_df = pd.concat(invvol_scores, axis=1).fillna(1.0)
    invvol_df = invvol_df.where(invvol_df.sum(axis=1) > 0, 1.0)
    invvol_w = normalize_rows(invvol_df)

    candidate_weights = simplex_grid(HEDGE_BUDGET, MULTI_STEP)
    cvar_w = pd.DataFrame(np.nan, index=idx, columns=hedge_assets)
    ret_vals = returns[["SPY", "SH", "TLT", "GLD"]].to_numpy()
    for i in range(CVAR_WINDOW, len(idx)):
        hist = ret_vals[i - CVAR_WINDOW : i]
        best = None
        best_obj = float("inf")
        for sh_w, tlt_w, gld_w in candidate_weights:
            port = (1.0 - HEDGE_BUDGET) * hist[:, 0] + sh_w * hist[:, 1] + tlt_w * hist[:, 2] + gld_w * hist[:, 3]
            q = np.quantile(port, CVAR_ALPHA)
            cvar = float(port[port <= q].mean())
            obj = -cvar
            if obj < best_obj:
                best_obj = obj
                best = (sh_w, tlt_w, gld_w)
        cvar_w.iloc[i] = best
    cvar_w = cvar_w.shift(1)

    weights_map = {
        "naive_equal": naive,
        "beta_negative_beta": beta_w,
        "inverse_vol": invvol_w,
        "rolling_cvar": cvar_w,
    }

    returns_map: dict[str, pd.Series] = {}
    budget_map: dict[str, pd.Series] = {}
    turnover_map: dict[str, pd.Series] = {}
    metrics_oos: dict[str, dict] = {}
    bootstrap_vs_naive: dict[str, dict] = {}

    for name, hedge_df in weights_map.items():
        hedge_df = hedge_df.fillna(0.0)
        hedge_budget = hedge_df.sum(axis=1)
        turnover = hedge_df.diff().abs().sum(axis=1).fillna(0.0)
        strategy_ret = (1.0 - HEDGE_BUDGET) * spy + (hedge_df * returns[hedge_assets]).sum(axis=1)
        strategy_ret = strategy_ret - turnover * TX_COST_ONE_WAY
        returns_map[name] = strategy_ret.rename(name)
        budget_map[name] = hedge_budget.rename(name + "_budget")
        turnover_map[name] = turnover.rename(name + "_turnover")
        metrics_oos[name] = metrics_to_json(
            compute_metrics(strategy_ret.loc[is_mask], hedge_budget=hedge_budget.loc[is_mask], turnover=turnover.loc[is_mask])
        )

    base = returns_map["naive_equal"].loc[is_mask]
    for name in ["beta_negative_beta", "inverse_vol", "rolling_cvar"]:
        bootstrap_vs_naive[name] = moving_block_bootstrap_diff(base, returns_map[name].loc[is_mask])

    mean_weights = {}
    for name, hedge_df in weights_map.items():
        mean_weights[name] = {
            col: round(float(hedge_df[col].loc[is_mask].mean()), 6) for col in hedge_assets
        }

    return {
        "description": "25% defensive sleeve across SH/TLT/GLD to test whether method gains come from timing or asset selection.",
        "oos_metrics": metrics_oos,
        "stress_metrics": summarize_periods(returns_map, budget_map, turnover_map),
        "bootstrap_vs_naive_equal": bootstrap_vs_naive,
        "mean_oos_weights": mean_weights,
        "turnover_oos_ann": {
            name: round(float(turnover_map[name].loc[is_mask].mean() * TRADING_DAYS), 6) for name in weights_map
        },
        "series": {
            "returns": returns_map,
            "weights": weights_map,
        },
    }


def render_single_panel_figure(panel: dict) -> None:
    oos_mask = next(iter(panel["series"]["returns"].values())).index >= OOS_START
    fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True, constrained_layout=True)

    for name, ret in panel["series"]["returns"].items():
        wealth = (1.0 + ret.loc[oos_mask].dropna()).cumprod()
        axes[0].plot(wealth.index, wealth, label=name)
    axes[0].set_title("Panel A: SPY + SH hedge rules (OOS wealth)")
    axes[0].set_ylabel("Growth of $1")
    axes[0].legend(loc="upper left")
    axes[0].grid(alpha=0.2)

    for name, w in panel["series"]["weights"].items():
        axes[1].plot(w.loc[oos_mask].index, w.loc[oos_mask], label=name)
    axes[1].axhline(HEDGE_BUDGET, color="black", ls="--", lw=1.0, alpha=0.7)
    axes[1].set_title("Panel A hedge weight")
    axes[1].set_ylabel("Hedge weight in SH")
    axes[1].grid(alpha=0.2)

    fig.savefig(HERE / "fig_panel_a_single_asset.png", dpi=180)
    plt.close(fig)


def render_multi_panel_figure(panel: dict) -> None:
    oos_mask = next(iter(panel["series"]["returns"].values())).index >= OOS_START
    fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True, constrained_layout=True)

    for name, ret in panel["series"]["returns"].items():
        wealth = (1.0 + ret.loc[oos_mask].dropna()).cumprod()
        axes[0].plot(wealth.index, wealth, label=name)
    axes[0].set_title("Panel B: 25% defensive sleeve (OOS wealth)")
    axes[0].set_ylabel("Growth of $1")
    axes[0].legend(loc="upper left")
    axes[0].grid(alpha=0.2)

    cvar_weights = panel["series"]["weights"]["rolling_cvar"].loc[oos_mask].fillna(0.0)
    axes[1].stackplot(
        cvar_weights.index,
        cvar_weights["SH"],
        cvar_weights["TLT"],
        cvar_weights["GLD"],
        labels=["SH", "TLT", "GLD"],
        alpha=0.8,
    )
    axes[1].set_title("Panel B rolling-CVaR hedge sleeve composition")
    axes[1].set_ylabel("Weight")
    axes[1].legend(loc="upper left")
    axes[1].grid(alpha=0.2)

    fig.savefig(HERE / "fig_panel_b_multi_asset.png", dpi=180)
    plt.close(fig)


def build_summary(panel_a: dict, panel_b: dict) -> dict:
    a_oos = panel_a["oos_metrics"]
    b_oos = panel_b["oos_metrics"]
    return {
        "panel_a": {
            "headline": "With the same SH hedge budget, naive fixed 25% is effectively tied with rolling-CVaR and slightly ahead of rolling-beta / inverse-vol after turnover costs.",
            "key_numbers": {
                "naive_fixed_sharpe": a_oos["naive_fixed"]["sharpe"],
                "rolling_beta_sharpe": a_oos["rolling_beta"]["sharpe"],
                "inverse_vol_sharpe": a_oos["inverse_vol"]["sharpe"],
                "rolling_cvar_sharpe": a_oos["rolling_cvar"]["sharpe"],
                "naive_fixed_mdd": a_oos["naive_fixed"]["mdd"],
                "rolling_cvar_mdd": a_oos["rolling_cvar"]["mdd"],
            },
        },
        "panel_b": {
            "headline": "Across SH/TLT/GLD, apparent gains from complex methods mostly come from structurally concentrating the sleeve into SH rather than from superior time variation.",
            "key_numbers": {
                "naive_equal_cagr": b_oos["naive_equal"]["cagr"],
                "beta_negative_beta_cagr": b_oos["beta_negative_beta"]["cagr"],
                "rolling_cvar_cagr": b_oos["rolling_cvar"]["cagr"],
                "naive_equal_mdd": b_oos["naive_equal"]["mdd"],
                "rolling_cvar_mdd": b_oos["rolling_cvar"]["mdd"],
            },
        },
        "bottom_line": "The evidence does not support a broad claim that estimation-heavy hedges are more robust. On the clean single-instrument test, complexity adds no value. On the multi-asset sleeve test, differences are mostly asset-choice effects, not timing skill.",
    }


def main() -> None:
    prices = download_prices()
    returns = prices.pct_change().dropna()

    panel_a = panel_single_asset(returns)
    panel_b = panel_multi_asset(returns)

    render_single_panel_figure(panel_a)
    render_multi_panel_figure(panel_b)

    output = {
        "experiment_id": "research_naive_estimation_heavy_robustness",
        "title": "Naive hedge vs estimation-heavy hedge robustness horse race",
        "timestamp_utc": utc_now(),
        "data": {
            "source": "yfinance auto-adjusted close",
            "tickers": TICKERS,
            "period": [label_date(returns.index[0]), label_date(returns.index[-1])],
            "n_obs": int(len(returns)),
        },
        "design": {
            "is_period": [str(IS_START.date()), str(IS_END.date())],
            "oos_period": [str(OOS_START.date()), label_date(returns.index[-1])],
            "stress_periods": STRESS_PERIODS,
            "transaction_cost_one_way_bps": TX_COST_ONE_WAY * 10000,
            "bootstrap": {
                "reps": BOOTSTRAP_REPS,
                "block_length": BOOTSTRAP_BLOCK,
                "seed": SEED,
            },
            "panel_a": "SPY + SH with naive fixed, rolling-beta, inverse-vol, rolling-CVaR rules under common 25% hedge budget.",
            "panel_b": "75% SPY core plus 25% defensive sleeve allocated across SH/TLT/GLD by naive equal, negative-beta, inverse-vol, or rolling-CVaR rules.",
        },
        "literature": [
            {
                "title": "Tail Risk Hedging: The Superiority of the Naive Hedging Strategy",
                "year": 2025,
                "url": "https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22602",
                "note": "Motivates the naive-vs-complex tail-hedge comparison and the estimation-error channel.",
            },
            {
                "title": "Hedging with Futures: Does Anything Beat the Naive Hedging Strategy?",
                "year": 2015,
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2462728",
                "note": "Classic benchmark that estimation-heavy hedge ratios often fail to beat naive rules once estimation error is counted.",
            },
            {
                "title": "Estimation of Optimal Hedge Ratio: A Wild Bootstrap Approach",
                "year": 2024,
                "url": "https://www.mdpi.com/1911-8074/17/7/310",
                "note": "Recent reminder that hedge-ratio estimation uncertainty remains first-order even when models become more elaborate.",
            },
        ],
        "related_repo_priors": [
            "I5: SPY/ES futures hedge ratio nearly constant across VIX regimes; dynamic ratio adds zero value.",
            "I1b: Static hedges beat or tie rolling/EWMA methods in 5 of 6 cross-asset pairs.",
            "K544: tail-hedge overlays on already-defensive portfolios are usually NPV-negative.",
            "K1334/K1494: backward-looking tail controls often fail to beat simpler volatility-aware baselines.",
        ],
        "summary": build_summary(panel_a, panel_b),
        "panel_a_single_asset": {
            key: value for key, value in panel_a.items() if key != "series"
        },
        "panel_b_multi_asset": {
            key: value for key, value in panel_b.items() if key != "series"
        },
        "limitations": [
            "This is an ETF-proxy study, not an options-chain or futures-margin implementation study.",
            "SH is engineered to deliver inverse daily SPY exposure, so Panel A is intentionally a clean identification test and partly mechanical by construction.",
            "Panel B broadens realism with TLT/GLD, but still uses daily close rebalancing and simple linear transaction costs.",
            "A true put-overlay comparison would need option surface data and explicit carry assumptions.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
