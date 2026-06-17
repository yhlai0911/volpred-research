"""K1532 - VT / dynamic risk parity turnover-cost dominance.

Question
--------
When does monthly rebalancing beat daily rebalancing after transaction
costs for dynamic risk parity and volatility-targeted risk parity?

Design
------
- Universe: SPY, TLT, GLD, HYG plus SHY as the cash sleeve.
- Data: yfinance adjusted close, explicitly ``auto_adjust=True`` because
  total-return-like ETF performance is the object of the backtest.
- Dynamic risk parity: equal-risk-contribution (ERC) weights estimated from
  a trailing 252-trading-day covariance matrix, tested both as a four-risky-
  asset sleeve and as a conservative five-asset sleeve including SHY.
- VT overlay: ERC weights on the four risky ETFs scaled down to a 10%
  annual volatility target; residual weight goes to SHY. No leverage is used.
- Execution: weights applied to return date t are estimated from returns up
  to t-1. Rebalance happens at the prior close and earns the next close-to-
  close return. This is the explicit anti-lookahead convention.
- Costs: cost_bps is charged per dollar traded:
  cost_t = cost_bps / 10000 * sum(abs(new_weight - current_weight)).

All randomness is fixed (seed=42) for bootstrap-style routines if extended;
the current experiment is deterministic apart from yfinance source data.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy.optimize import minimize

warnings.filterwarnings("ignore", category=FutureWarning)

SEED = 42
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "k1532_results.json"

ASSETS_RISKY = ["SPY", "TLT", "GLD", "HYG"]
ASSET_CASH = "SHY"
UNIVERSE = ASSETS_RISKY + [ASSET_CASH]
START = "2007-01-01"
END = "2026-06-18"
LOOKBACK = 252
TARGET_VOL = 0.10
COST_BPS_GRID = [0.0, 8.0, 15.0, 25.0, 35.0]
FREQUENCIES = ["daily", "weekly", "monthly"]
TRADING_DAYS = 252
HAC_MAXLAG = 21


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        val = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(val) or math.isinf(val):
        return None
    return val


def _download_one(ticker: str) -> pd.Series:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / f"{ticker}_adjusted_close.csv"
    if cache_path.exists():
        df = pd.read_csv(cache_path, parse_dates=["Date"])
        s = df.set_index("Date")["adjusted_close"].astype(float)
        s.name = ticker
        return s

    raw = yf.download(
        ticker,
        start=START,
        end=END,
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError(f"yfinance returned no rows for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].iloc[:, 0].copy()
    else:
        close = raw["Close"].copy()
    close = close.dropna().astype(float)
    out = close.rename("adjusted_close").reset_index()
    out.to_csv(cache_path, index=False)
    close.name = ticker
    return close


def load_prices() -> pd.DataFrame:
    prices = pd.concat([_download_one(t) for t in UNIVERSE], axis=1)
    prices = prices.sort_index().dropna(how="any")
    prices = prices.loc[prices.index >= pd.Timestamp("2007-04-01")]
    if prices.empty:
        raise RuntimeError("No common price history after joining all tickers")
    return prices


def pct_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().dropna(how="any")


def shrink_cov(hist: pd.DataFrame) -> np.ndarray:
    cov = hist.cov().to_numpy(dtype=float) * TRADING_DAYS
    cov = np.nan_to_num(cov, nan=0.0, posinf=0.0, neginf=0.0)
    cov = (cov + cov.T) / 2.0
    diag = np.diag(np.clip(np.diag(cov), 1e-10, None))
    cov = 0.90 * cov + 0.10 * diag
    cov += np.eye(cov.shape[0]) * 1e-10
    return cov


def inverse_vol_weights(cov: np.ndarray) -> np.ndarray:
    vol = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    inv = 1.0 / vol
    w = inv / inv.sum()
    return w


def erc_weights(cov: np.ndarray, x0: np.ndarray | None = None) -> tuple[np.ndarray, bool]:
    n = cov.shape[0]
    if x0 is None or len(x0) != n:
        x0 = inverse_vol_weights(cov)
    else:
        x0 = np.clip(np.asarray(x0, dtype=float), 1e-6, 1.0)
        x0 = x0 / x0.sum()

    def objective(w: np.ndarray) -> float:
        mrc = cov @ w
        port_var = float(w @ mrc)
        if port_var <= 1e-14:
            return 1e6
        rc = w * mrc / port_var
        target = np.full(n, 1.0 / n)
        return float(np.sum((rc - target) ** 2))

    res = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * n,
        constraints=({"type": "eq", "fun": lambda w: np.sum(w) - 1.0},),
        options={"ftol": 1e-12, "maxiter": 300, "disp": False},
    )
    if not res.success or not np.all(np.isfinite(res.x)):
        return inverse_vol_weights(cov), False
    w = np.clip(res.x, 0.0, 1.0)
    w = w / w.sum()
    return w, True


@dataclass
class WeightBuild:
    weights: pd.DataFrame
    estimated_vol: pd.Series
    optimizer_failures: int


def build_target_weights(returns: pd.DataFrame, strategy: str) -> WeightBuild:
    """Build weights for each return date using information through t-1."""
    if strategy not in {"drp_4asset", "drp_5asset", "vt_drp_4asset_shy"}:
        raise ValueError(f"unknown strategy {strategy}")

    out = []
    vols = []
    dates = []
    failures = 0
    prev: np.ndarray | None = None

    for i in range(LOOKBACK, len(returns)):
        date = returns.index[i]
        if strategy == "drp_5asset":
            cols = UNIVERSE
        else:
            cols = ASSETS_RISKY

        # Strict lag: return at index i is predicted with the trailing window
        # ending at i-1. No value from return date i enters the covariance.
        hist = returns.loc[:, cols].iloc[i - LOOKBACK : i]
        cov = shrink_cov(hist)
        base_w, ok = erc_weights(cov, prev)
        if not ok:
            failures += 1
        prev = base_w

        if strategy == "drp_5asset":
            w_full = pd.Series(base_w, index=cols).reindex(UNIVERSE).fillna(0.0)
            est_vol = float(np.sqrt(base_w @ cov @ base_w))
        elif strategy == "drp_4asset":
            w_full = pd.Series(0.0, index=UNIVERSE)
            w_full.loc[ASSETS_RISKY] = base_w
            est_vol = float(np.sqrt(base_w @ cov @ base_w))
        else:
            base_vol = float(np.sqrt(base_w @ cov @ base_w))
            scale = 1.0 if base_vol <= 1e-12 else min(TARGET_VOL / base_vol, 1.0)
            w_full = pd.Series(0.0, index=UNIVERSE)
            w_full.loc[ASSETS_RISKY] = base_w * scale
            w_full.loc[ASSET_CASH] = 1.0 - float(w_full.loc[ASSETS_RISKY].sum())
            est_vol = base_vol * scale

        out.append(w_full)
        vols.append(est_vol)
        dates.append(date)

    weights = pd.DataFrame(out, index=pd.DatetimeIndex(dates), columns=UNIVERSE)
    estimated_vol = pd.Series(vols, index=weights.index, name="estimated_vol")
    return WeightBuild(weights=weights, estimated_vol=estimated_vol, optimizer_failures=failures)


def rebalance_mask(index: pd.DatetimeIndex, frequency: str) -> pd.Series:
    if frequency == "daily":
        mask = pd.Series(True, index=index)
    elif frequency == "weekly":
        week = index.to_period("W")
        mask = pd.Series(week != pd.Series(week, index=index).shift(1).to_numpy(), index=index)
    elif frequency == "monthly":
        month = index.to_period("M")
        mask = pd.Series(month != pd.Series(month, index=index).shift(1).to_numpy(), index=index)
    else:
        raise ValueError(f"unknown frequency {frequency}")
    if len(mask):
        mask.iloc[0] = True
    return mask


@dataclass
class Simulation:
    returns_gross: pd.Series
    returns_net: pd.Series
    costs: pd.Series
    turnover: pd.Series
    weights_before_return: pd.DataFrame
    n_rebalances: int


def simulate_strategy(
    returns: pd.DataFrame,
    target_weights: pd.DataFrame,
    frequency: str,
    cost_bps: float,
) -> Simulation:
    idx = target_weights.index.intersection(returns.index)
    r = returns.loc[idx, UNIVERSE]
    targets = target_weights.loc[idx, UNIVERSE]
    mask = rebalance_mask(idx, frequency)
    cost_rate = cost_bps / 10000.0

    w_current = targets.iloc[0].to_numpy(dtype=float)
    gross_vals: list[float] = []
    net_vals: list[float] = []
    cost_vals: list[float] = []
    turnover_vals: list[float] = []
    weight_rows: list[np.ndarray] = []
    n_rebalances = 0

    for j, date in enumerate(idx):
        if j == 0 or bool(mask.loc[date]):
            w_target = targets.loc[date].to_numpy(dtype=float)
            turnover = float(np.sum(np.abs(w_target - w_current)))
            w_current = w_target
            n_rebalances += 1
        else:
            turnover = 0.0

        day_ret = r.loc[date].to_numpy(dtype=float)
        gross = float(w_current @ day_ret)
        cost = float(turnover * cost_rate)
        net = gross - cost

        gross_vals.append(gross)
        net_vals.append(net)
        cost_vals.append(cost)
        turnover_vals.append(turnover)
        weight_rows.append(w_current.copy())

        denom = 1.0 + gross
        if denom <= 0:
            raise RuntimeError(f"non-positive portfolio wealth update at {date}")
        w_current = w_current * (1.0 + day_ret) / denom
        w_current = np.clip(w_current, 0.0, 1.0)
        w_current = w_current / w_current.sum()

    return Simulation(
        returns_gross=pd.Series(gross_vals, index=idx, name="gross_return"),
        returns_net=pd.Series(net_vals, index=idx, name="net_return"),
        costs=pd.Series(cost_vals, index=idx, name="cost"),
        turnover=pd.Series(turnover_vals, index=idx, name="turnover"),
        weights_before_return=pd.DataFrame(weight_rows, index=idx, columns=UNIVERSE),
        n_rebalances=n_rebalances,
    )


def max_drawdown(ret: pd.Series) -> float:
    wealth = (1.0 + ret).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1.0
    return float(dd.min())


def perf_metrics(sim: Simulation) -> dict[str, float | int | None]:
    r_net = sim.returns_net.dropna()
    r_gross = sim.returns_gross.loc[r_net.index]
    years = len(r_net) / TRADING_DAYS
    ann_net = float((1.0 + r_net).prod() ** (1.0 / years) - 1.0)
    ann_gross = float((1.0 + r_gross).prod() ** (1.0 / years) - 1.0)
    vol_net = float(r_net.std(ddof=1) * np.sqrt(TRADING_DAYS))
    vol_gross = float(r_gross.std(ddof=1) * np.sqrt(TRADING_DAYS))
    sharpe_net = None if vol_net <= 0 else float(r_net.mean() / r_net.std(ddof=1) * np.sqrt(TRADING_DAYS))
    sharpe_gross = None if vol_gross <= 0 else float(r_gross.mean() / r_gross.std(ddof=1) * np.sqrt(TRADING_DAYS))
    cost_drag_ann = float(sim.costs.sum() / years)
    annual_turnover = float(sim.turnover.sum() / years)
    drag_pct_gross = None
    if abs(ann_gross) > 1e-12:
        drag_pct_gross = float(cost_drag_ann / abs(ann_gross))
    return {
        "n_days": int(len(r_net)),
        "years": float(years),
        "ann_return_net": ann_net,
        "ann_return_gross": ann_gross,
        "ann_vol_net": vol_net,
        "sharpe_net": _json_float(sharpe_net),
        "sharpe_gross": _json_float(sharpe_gross),
        "max_drawdown_net": max_drawdown(r_net),
        "annual_turnover_l1": annual_turnover,
        "annual_cost_drag": cost_drag_ann,
        "cost_drag_pct_of_abs_gross_return": _json_float(drag_pct_gross),
        "n_rebalances": int(sim.n_rebalances),
        "rebalances_per_year": float(sim.n_rebalances / years),
        "mean_daily_turnover": float(sim.turnover.mean()),
        "mean_weight_shy": float(sim.weights_before_return[ASSET_CASH].mean()),
        "mean_weight_spy": float(sim.weights_before_return["SPY"].mean()),
    }


def hac_mean_test(x: pd.Series, maxlag: int = HAC_MAXLAG) -> dict[str, float | int | None]:
    y = x.dropna().astype(float)
    if len(y) < maxlag + 5:
        return {"n": int(len(y)), "mean": _json_float(y.mean()), "hac_t": None, "p_value": None}
    model = sm.OLS(y.to_numpy(), np.ones((len(y), 1)))
    res = model.fit(cov_type="HAC", cov_kwds={"maxlags": maxlag})
    return {
        "n": int(len(y)),
        "mean": float(y.mean()),
        "hac_t": float(res.tvalues[0]),
        "p_value": float(res.pvalues[0]),
        "maxlag": int(maxlag),
    }


def find_monthly_daily_threshold(rows: dict[str, dict[str, dict[str, dict[str, Any]]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for strategy, by_freq in rows.items():
        diffs = []
        for cost in COST_BPS_GRID:
            key = f"{cost:.1f}"
            daily = by_freq["daily"][key]["sharpe_net"]
            monthly = by_freq["monthly"][key]["sharpe_net"]
            if daily is None or monthly is None:
                diffs.append(np.nan)
            else:
                diffs.append(float(monthly) - float(daily))
        threshold = None
        relation = "not_reached"
        if np.isfinite(diffs[0]) and diffs[0] >= 0:
            threshold = 0.0
            relation = "monthly_already_beats_daily_at_zero_cost"
        else:
            for k in range(1, len(COST_BPS_GRID)):
                if not (np.isfinite(diffs[k - 1]) and np.isfinite(diffs[k])):
                    continue
                if diffs[k - 1] < 0 <= diffs[k]:
                    x0, x1 = COST_BPS_GRID[k - 1], COST_BPS_GRID[k]
                    y0, y1 = diffs[k - 1], diffs[k]
                    threshold = float(x0 + (0.0 - y0) * (x1 - x0) / (y1 - y0))
                    relation = "crosses_inside_grid"
                    break
            if threshold is None and np.isfinite(diffs[-1]) and diffs[-1] < 0:
                relation = "daily_still_beats_monthly_at_35bps"
            elif threshold is None and np.isfinite(diffs[-1]) and diffs[-1] >= 0:
                relation = "monthly_beats_daily_somewhere_grid_but_interpolation_failed"
        out[strategy] = {
            "cost_bps_grid": COST_BPS_GRID,
            "monthly_minus_daily_sharpe": [_json_float(v) for v in diffs],
            "threshold_bps": _json_float(threshold),
            "relation": relation,
        }
    return out


def plot_results(results: dict[str, Any]) -> None:
    rows = results["metrics"]
    for strategy, by_freq in rows.items():
        fig, ax = plt.subplots(figsize=(8, 4.5))
        for freq in FREQUENCIES:
            y = [by_freq[freq][f"{c:.1f}"]["sharpe_net"] for c in COST_BPS_GRID]
            ax.plot(COST_BPS_GRID, y, marker="o", label=freq)
        ax.set_title(f"K1532 {strategy}: net Sharpe vs transaction cost")
        ax.set_xlabel("Cost per dollar traded (bps)")
        ax.set_ylabel("Net Sharpe")
        ax.axhline(0, color="black", linewidth=0.8)
        ax.grid(True, alpha=0.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(HERE / f"fig_{strategy}_sharpe_cost.png", dpi=160)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    labels = []
    vals = []
    for strategy, by_freq in rows.items():
        for freq in FREQUENCIES:
            labels.append(f"{strategy}\n{freq}")
            vals.append(by_freq[freq]["0.0"]["annual_turnover_l1"])
    colors = ["#496a81", "#8f6f43", "#5c7f5d"] * ((len(labels) // 3) + 1)
    ax.bar(labels, vals, color=colors[: len(labels)])
    ax.set_ylabel("Annual L1 turnover")
    ax.set_title("K1532 annual turnover before transaction costs")
    ax.tick_params(axis="x", labelrotation=25)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(HERE / "fig_annual_turnover.png", dpi=160)
    plt.close(fig)


def main() -> None:
    print("[K1532] loading prices")
    prices = load_prices()
    returns = pct_returns(prices)
    print(f"[K1532] common sample {prices.index.min().date()}..{prices.index.max().date()}, n_prices={len(prices)}")

    builds = {
        "drp_4asset": build_target_weights(returns, "drp_4asset"),
        "drp_5asset": build_target_weights(returns, "drp_5asset"),
        "vt_drp_4asset_shy": build_target_weights(returns, "vt_drp_4asset_shy"),
    }

    metrics: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    simulations: dict[tuple[str, str, float], Simulation] = {}
    for strategy, build in builds.items():
        metrics[strategy] = {}
        for freq in FREQUENCIES:
            metrics[strategy][freq] = {}
            for cost_bps in COST_BPS_GRID:
                sim = simulate_strategy(returns, build.weights, freq, cost_bps)
                simulations[(strategy, freq, cost_bps)] = sim
                metrics[strategy][freq][f"{cost_bps:.1f}"] = perf_metrics(sim)
                print(
                    f"[K1532] {strategy:18s} {freq:7s} cost={cost_bps:4.1f}bp "
                    f"Sharpe={metrics[strategy][freq][f'{cost_bps:.1f}']['sharpe_net']:.3f} "
                    f"MDD={metrics[strategy][freq][f'{cost_bps:.1f}']['max_drawdown_net']:.2%} "
                    f"turnover={metrics[strategy][freq][f'{cost_bps:.1f}']['annual_turnover_l1']:.2f}"
                )

    thresholds = find_monthly_daily_threshold(metrics)

    pairwise_tests: dict[str, Any] = {}
    for strategy in builds:
        pairwise_tests[strategy] = {}
        for cost_bps in [0.0, 8.0, 35.0]:
            daily = simulations[(strategy, "daily", cost_bps)].returns_net
            weekly = simulations[(strategy, "weekly", cost_bps)].returns_net
            monthly = simulations[(strategy, "monthly", cost_bps)].returns_net
            common_dm = daily.index.intersection(monthly.index)
            common_wm = weekly.index.intersection(monthly.index)
            pairwise_tests[strategy][f"{cost_bps:.1f}"] = {
                "daily_minus_monthly_return_hac": hac_mean_test(daily.loc[common_dm] - monthly.loc[common_dm]),
                "weekly_minus_monthly_return_hac": hac_mean_test(weekly.loc[common_wm] - monthly.loc[common_wm]),
            }

    diagnostics = {}
    for strategy, build in builds.items():
        first_date = build.weights.index.min()
        first_return_pos = returns.index.get_loc(first_date)
        lookback_window_end = returns.index[first_return_pos - 1]
        diagnostics[strategy] = {
            "target_weight_start": str(first_date.date()),
            "first_target_uses_returns_through": str(lookback_window_end.date()),
            "optimizer_failures": int(build.optimizer_failures),
            "mean_estimated_vol": float(build.estimated_vol.mean()),
            "p10_estimated_vol": float(build.estimated_vol.quantile(0.10)),
            "p90_estimated_vol": float(build.estimated_vol.quantile(0.90)),
        }

    results = {
        "experiment_id": "k1532",
        "title": "VT / dynamic risk parity turnover-cost dominance",
        "created_at": _utc_now(),
        "seed": SEED,
        "data": {
            "source": "yfinance",
            "auto_adjust": True,
            "auto_adjust_reason": "ETF total-return-like strategy backtest; explicit to avoid yfinance default drift.",
            "tickers": UNIVERSE,
            "risky_tickers": ASSETS_RISKY,
            "cash_ticker": ASSET_CASH,
            "download_start": START,
            "download_end": END,
            "common_price_start": str(prices.index.min().date()),
            "common_price_end": str(prices.index.max().date()),
            "n_price_days": int(len(prices)),
            "n_return_days": int(len(returns)),
            "cache_files": [str((DATA_DIR / f"{t}_adjusted_close.csv").relative_to(HERE)) for t in UNIVERSE],
        },
        "method": {
            "lookback_days": LOOKBACK,
            "target_vol": TARGET_VOL,
            "frequencies": FREQUENCIES,
            "cost_bps_grid": COST_BPS_GRID,
            "turnover_definition": "L1 dollar turnover = sum(abs(new_weight - current_drifted_weight)); cost = turnover * cost_bps / 10000.",
            "lookahead_guard": "For return date i, covariance window is returns.iloc[i-252:i], ending at i-1; target weights are applied to return i.",
            "strategies": {
                "drp_4asset": "Long-only ERC over SPY/TLT/GLD/HYG, fully invested; SHY weight is zero.",
                "drp_5asset": "Long-only ERC over SPY/TLT/GLD/HYG/SHY, fully invested.",
                "vt_drp_4asset_shy": "Long-only ERC over SPY/TLT/GLD/HYG, scaled down to 10% annual vol; residual allocated to SHY; no leverage.",
            },
            "hac_tests": "Newey-West HAC t-tests on mean daily return difference, maxlag=21; these are not Sharpe-ratio tests.",
        },
        "diagnostics": diagnostics,
        "metrics": metrics,
        "thresholds": thresholds,
        "pairwise_tests": pairwise_tests,
        "figures": [
            "fig_drp_4asset_sharpe_cost.png",
            "fig_drp_5asset_sharpe_cost.png",
            "fig_vt_drp_4asset_shy_sharpe_cost.png",
            "fig_annual_turnover.png",
        ],
    }

    # Verdict is assigned mechanically after seeing the cost-grid dominance.
    verdict_notes = []
    for strategy, threshold in thresholds.items():
        relation = threshold["relation"]
        if relation == "crosses_inside_grid":
            verdict_notes.append(f"{strategy}: monthly crosses daily at {threshold['threshold_bps']:.2f} bps")
        elif relation == "monthly_already_beats_daily_at_zero_cost":
            verdict_notes.append(f"{strategy}: monthly already beats daily at zero cost")
        else:
            verdict_notes.append(f"{strategy}: {relation}")
    relations = [v["relation"] for v in thresholds.values()]
    if all(r in {"crosses_inside_grid", "monthly_already_beats_daily_at_zero_cost"} for r in relations):
        verdict = "CONDITIONAL_PASS"
    elif any(r in {"crosses_inside_grid", "monthly_already_beats_daily_at_zero_cost"} for r in relations):
        verdict = "MIXED"
    else:
        verdict = "NULL"
    results["verdict"] = verdict
    results["verdict_reason"] = (
        "Cost-frequency dominance is identifiable on the specified grid, but "
        "the result is a backtest engineering finding, not a new alpha claim. "
        + " | ".join(verdict_notes)
    )

    plot_results(results)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"[K1532] wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
