#!/usr/bin/env python3
"""Cornish-Fisher HMM regime tail adjustment for sector rotation.

The strategy uses only information available at each rebalance close, shifts
weights by one trading day, and compares net returns against equal-weight and
volatility-targeted sector baselines.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from hmmlearn.hmm import GaussianHMM
from scipy import stats

from volpred.stats.model_evaluation import strategy_dm_test


EXP_ID = "research_cornish_fisher_regime_tail_adjustment_sector_rot"
SEED = 20260624
START_DATE = "2018-01-01"
TRAIN_DAYS = 756
CF_ALPHA = 0.05
TRANSACTION_COST = 0.001
VT_TARGET_VOL = 0.12
VT_LOOKBACK = 63
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
TRADING_DAYS = 252

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXP_ID}_results.json"

SECTOR_TICKERS = [
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
]
DEFENSIVE_TICKERS = {"XLP", "XLU"}
PRICE_TICKERS = SECTOR_TICKERS + ["SPY"]


@dataclass(frozen=True)
class Performance:
    strategy: str
    n_days: int
    ann_return: float
    ann_vol: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    cumulative_return: float
    mean_daily_turnover: float
    total_transaction_cost: float


def _download_prices() -> pd.DataFrame:
    cache_path = DATA_DIR / "prices.csv"
    if cache_path.exists():
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if all(ticker in cached.columns for ticker in PRICE_TICKERS):
            print(f"Using cached prices from {cache_path}")
            return cached[PRICE_TICKERS].sort_index()

    print(f"Downloading {len(PRICE_TICKERS)} adjusted-close series from yfinance ...")
    raw = yf.download(
        PRICE_TICKERS,
        start=START_DATE,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].rename(columns={"Close": PRICE_TICKERS[0]})
    missing = sorted(set(PRICE_TICKERS) - set(prices.columns))
    if missing:
        raise RuntimeError(f"Missing price columns: {missing}")
    prices = prices[PRICE_TICKERS].dropna(how="any").sort_index()
    prices.to_csv(cache_path)
    return prices


def _month_end_rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    dates = pd.Series(index=index, data=index)
    return pd.DatetimeIndex(dates.groupby(index.to_period("M")).max().to_list())


def _fit_hmm(spy_returns: pd.Series) -> tuple[np.ndarray, int, int, float, dict]:
    x = (spy_returns.dropna().to_numpy(dtype=float) * 100.0).reshape(-1, 1)
    if x.shape[0] < 250:
        raise ValueError("not enough observations for HMM")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = GaussianHMM(
            n_components=2,
            covariance_type="diag",
            n_iter=250,
            tol=1e-4,
            min_covar=1e-4,
            random_state=SEED,
        )
        model.fit(x)
        states = model.predict(x)
        posteriors = model.predict_proba(x)
    variances = np.ravel(model.covars_)
    means = np.ravel(model.means_)
    turbulent_state = int(np.argmax(variances))
    current_state = int(states[-1])
    current_state_prob = float(posteriors[-1, current_state])
    meta = {
        "state_0_mean_pct": float(means[0]),
        "state_1_mean_pct": float(means[1]),
        "state_0_vol_ann": float(math.sqrt(variances[0]) / 100.0 * math.sqrt(TRADING_DAYS)),
        "state_1_vol_ann": float(math.sqrt(variances[1]) / 100.0 * math.sqrt(TRADING_DAYS)),
        "turbulent_state": turbulent_state,
    }
    return states, turbulent_state, current_state, current_state_prob, meta


def _cornish_fisher_tail_score(returns: pd.Series, alpha: float = CF_ALPHA) -> dict:
    x = returns.dropna().astype(float)
    if x.shape[0] < 40:
        return {
            "n": int(x.shape[0]),
            "mean": None,
            "vol": None,
            "skew": None,
            "excess_kurtosis": None,
            "cf_var_loss": None,
            "cf_es_loss": None,
            "tail_score": None,
        }
    mu = float(x.mean())
    sigma = float(x.std(ddof=1))
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError("non-positive sector return volatility")

    skew = float(stats.skew(x, bias=False))
    excess_kurt = float(stats.kurtosis(x, fisher=True, bias=False))
    # CF quantiles can become non-monotone with extreme sample moments. Clipping
    # keeps this diagnostic strategy from turning estimation noise into leverage.
    skew_for_cf = float(np.clip(skew, -2.0, 2.0))
    kurt_for_cf = float(np.clip(excess_kurt, -1.0, 10.0))
    z = float(stats.norm.ppf(alpha))
    z_cf = (
        z
        + (z * z - 1.0) * skew_for_cf / 6.0
        + (z**3 - 3.0 * z) * kurt_for_cf / 24.0
        - (2.0 * z**3 - 5.0 * z) * (skew_for_cf**2) / 36.0
    )
    z_cf = float(np.clip(z_cf, -5.0, -0.10))
    q_cf = mu + sigma * z_cf
    var_loss = max(-q_cf, 0.0)
    tail = x.loc[x <= q_cf]
    es_loss = float(-tail.mean()) if not tail.empty else var_loss
    tail_score = 0.65 * var_loss + 0.35 * es_loss
    return {
        "n": int(x.shape[0]),
        "mean": mu,
        "vol": sigma,
        "skew": skew,
        "excess_kurtosis": excess_kurt,
        "cf_z": z_cf,
        "cf_var_loss": float(var_loss),
        "cf_es_loss": float(es_loss),
        "tail_score": float(tail_score),
    }


def _cap_and_normalize(weights: pd.Series, cap: float = 0.25) -> pd.Series:
    w = weights.clip(lower=0.0).astype(float)
    if w.sum() <= 0:
        return pd.Series(1.0 / len(w), index=w.index)
    w = w / w.sum()
    fixed = pd.Series(False, index=w.index)
    for _ in range(10):
        too_high = (w > cap) & (~fixed)
        if not too_high.any():
            break
        fixed |= too_high
        w.loc[fixed] = cap
        remaining = 1.0 - w.loc[fixed].sum()
        free = ~fixed
        if remaining <= 0 or not free.any():
            break
        w.loc[free] = w.loc[free] / w.loc[free].sum() * remaining
    return w / w.sum()


def _rotation_weights(tail_scores: dict[str, dict], turbulent: bool) -> pd.Series:
    scores = pd.Series(
        {
            ticker: stats_dict["tail_score"]
            for ticker, stats_dict in tail_scores.items()
            if stats_dict["tail_score"] is not None and np.isfinite(stats_dict["tail_score"])
        }
    )
    if scores.empty:
        return pd.Series(1.0 / len(SECTOR_TICKERS), index=SECTOR_TICKERS)
    inv_risk = 1.0 / (scores.clip(lower=1e-6))
    if turbulent:
        for ticker in DEFENSIVE_TICKERS:
            if ticker in inv_risk.index:
                inv_risk.loc[ticker] *= 1.75
    weights = _cap_and_normalize(inv_risk.reindex(SECTOR_TICKERS).fillna(0.0), cap=0.25)
    return weights.reindex(SECTOR_TICKERS).fillna(0.0)


def _build_monthly_weights(returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rebalance_dates = _month_end_rebalance_dates(returns.index)
    strategy_rows = []
    ew_rows = []
    vt_rows = []
    diagnostics = []

    sector_returns = returns[SECTOR_TICKERS]
    ew_daily = sector_returns.mean(axis=1)
    for rebalance_date in rebalance_dates:
        pos = returns.index.get_loc(rebalance_date)
        if pos < TRAIN_DAYS:
            continue
        train = returns.iloc[pos - TRAIN_DAYS : pos + 1].copy()
        states, turbulent_state, current_state, current_prob, hmm_meta = _fit_hmm(train["SPY"])
        current_is_turbulent = current_state == turbulent_state
        regime_mask = states == current_state

        tail_scores = {}
        for ticker in SECTOR_TICKERS:
            sector_train = train[ticker].iloc[-len(states) :]
            regime_returns = sector_train.loc[regime_mask]
            if regime_returns.shape[0] < 60:
                regime_returns = sector_train
            tail_scores[ticker] = _cornish_fisher_tail_score(regime_returns)
        weights = _rotation_weights(tail_scores, turbulent=current_is_turbulent)
        strategy_rows.append({"date": rebalance_date, **weights.to_dict()})
        ew_rows.append({"date": rebalance_date, **{ticker: 1.0 / len(SECTOR_TICKERS) for ticker in SECTOR_TICKERS}})

        vol = float(ew_daily.iloc[max(0, pos - VT_LOOKBACK + 1) : pos + 1].std(ddof=1) * math.sqrt(TRADING_DAYS))
        scale = float(np.clip(VT_TARGET_VOL / vol, 0.25, 1.50)) if vol > 0 else 1.0
        vt_rows.append({"date": rebalance_date, **{ticker: scale / len(SECTOR_TICKERS) for ticker in SECTOR_TICKERS}})

        ranked_scores = {
            ticker: tail_scores[ticker]["tail_score"]
            for ticker in SECTOR_TICKERS
            if tail_scores[ticker]["tail_score"] is not None
        }
        diagnostics.append(
            {
                "date": rebalance_date,
                "current_state": current_state,
                "turbulent_state": turbulent_state,
                "current_is_turbulent": current_is_turbulent,
                "current_state_prob": current_prob,
                "regime_obs": int(regime_mask.sum()),
                "vt_scale": scale,
                "lowest_tail_sector": min(ranked_scores, key=ranked_scores.get),
                "highest_tail_sector": max(ranked_scores, key=ranked_scores.get),
                **hmm_meta,
                **{f"weight_{k}": float(v) for k, v in weights.items()},
                **{f"tail_score_{k}": float(v) for k, v in ranked_scores.items()},
            }
        )

    if not strategy_rows:
        raise RuntimeError("no rebalance weights built; increase sample or reduce TRAIN_DAYS")

    strategy_weights = pd.DataFrame(strategy_rows).set_index("date").sort_index()
    ew_weights = pd.DataFrame(ew_rows).set_index("date").sort_index()
    vt_weights = pd.DataFrame(vt_rows).set_index("date").sort_index()
    diagnostics_df = pd.DataFrame(diagnostics).sort_values("date")
    return strategy_weights, ew_weights, vt_weights, diagnostics_df


def _apply_weights(
    returns: pd.DataFrame,
    rebalance_weights: pd.DataFrame,
    strategy_name: str,
    transaction_cost: float = TRANSACTION_COST,
) -> tuple[pd.Series, pd.DataFrame]:
    daily_weights = rebalance_weights.reindex(returns.index).ffill().shift(1)
    daily_weights = daily_weights.dropna(how="all")
    weights = daily_weights.reindex(returns.index).fillna(0.0)
    gross = (weights[SECTOR_TICKERS] * returns[SECTOR_TICKERS]).sum(axis=1)
    turnover = weights[SECTOR_TICKERS].diff().abs().sum(axis=1)
    first_active = weights[SECTOR_TICKERS].sum(axis=1) > 0
    turnover.loc[first_active & turnover.isna()] = weights.loc[first_active, SECTOR_TICKERS].abs().sum(axis=1)
    turnover = turnover.fillna(0.0)
    cost = turnover * transaction_cost
    net = gross - cost
    active = first_active
    detail = pd.DataFrame(
        {
            f"{strategy_name}_gross_return": gross,
            f"{strategy_name}_transaction_cost": cost,
            f"{strategy_name}_turnover": turnover,
            f"{strategy_name}_net_return": net,
            f"{strategy_name}_active": active,
        }
    )
    return net.loc[active], detail.loc[active]


def _performance(name: str, returns: pd.Series, detail: pd.DataFrame) -> Performance:
    returns = returns.dropna()
    n = returns.shape[0]
    growth = (1.0 + returns).cumprod()
    cumulative = float(growth.iloc[-1] - 1.0)
    ann_return = float(growth.iloc[-1] ** (TRADING_DAYS / n) - 1.0)
    ann_vol = float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS))
    sharpe = float(ann_return / ann_vol) if ann_vol > 0 else float("nan")
    downside = returns.loc[returns < 0]
    downside_vol = float(downside.std(ddof=1) * math.sqrt(TRADING_DAYS)) if downside.shape[0] > 1 else float("nan")
    sortino = float(ann_return / downside_vol) if downside_vol > 0 else float("nan")
    drawdown = growth / growth.cummax() - 1.0
    mdd = float(drawdown.min())
    calmar = float(ann_return / abs(mdd)) if mdd < 0 else float("nan")
    turnover_col = f"{name}_turnover"
    cost_col = f"{name}_transaction_cost"
    return Performance(
        strategy=name,
        n_days=int(n),
        ann_return=ann_return,
        ann_vol=ann_vol,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=mdd,
        calmar=calmar,
        cumulative_return=cumulative,
        mean_daily_turnover=float(detail[turnover_col].mean()),
        total_transaction_cost=float(detail[cost_col].sum()),
    )


def _bootstrap_sharpe_diff(
    returns_a: pd.Series,
    returns_b: pd.Series,
    reps: int = BOOTSTRAP_REPS,
    block: int = BOOTSTRAP_BLOCK,
) -> dict:
    aligned = pd.concat([returns_a, returns_b], axis=1).dropna()
    aligned.columns = ["a", "b"]
    values = aligned.to_numpy(dtype=float)
    n = values.shape[0]
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(reps):
        chunks = []
        while sum(chunk.shape[0] for chunk in chunks) < n:
            start = int(rng.integers(0, n))
            idx = (np.arange(start, start + block) % n).astype(int)
            chunks.append(values[idx])
        sample = np.vstack(chunks)[:n]
        ret_a = pd.Series(sample[:, 0])
        ret_b = pd.Series(sample[:, 1])
        sharpe_a = (1 + ret_a).prod() ** (TRADING_DAYS / n) - 1
        sharpe_b = (1 + ret_b).prod() ** (TRADING_DAYS / n) - 1
        vol_a = ret_a.std(ddof=1) * math.sqrt(TRADING_DAYS)
        vol_b = ret_b.std(ddof=1) * math.sqrt(TRADING_DAYS)
        diffs.append((sharpe_a / vol_a) - (sharpe_b / vol_b))
    arr = np.asarray(diffs, dtype=float)
    return {
        "reps": reps,
        "block": block,
        "mean": float(np.mean(arr)),
        "ci_low": float(np.quantile(arr, 0.025)),
        "ci_high": float(np.quantile(arr, 0.975)),
        "p_gt_0": float(np.mean(arr > 0)),
    }


def _dm_rows(strategy_returns: dict[str, pd.Series]) -> list[dict]:
    rows = []
    comparisons = [("cf_hmm_rotation", "sector_ew"), ("cf_hmm_rotation", "sector_ew_vt")]
    for model, baseline in comparisons:
        aligned = pd.concat([strategy_returns[model], strategy_returns[baseline]], axis=1).dropna()
        aligned.columns = [model, baseline]
        for loss_fn in ["negative_return", "downside"]:
            t_stat, p_value = strategy_dm_test(
                aligned[model].to_numpy(),
                aligned[baseline].to_numpy(),
                h=1,
                loss_fn=loss_fn,
            )
            rows.append(
                {
                    "model": model,
                    "baseline": baseline,
                    "loss_fn": loss_fn,
                    "n_obs": int(aligned.shape[0]),
                    "dm_t": float(t_stat),
                    "p_value": float(p_value),
                    "harvey_pass": bool(abs(t_stat) > 3.0),
                    "model_better": bool(t_stat < -3.0),
                }
            )
    return rows


def _plot_cumulative(strategy_returns: dict[str, pd.Series]) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    for name, returns in strategy_returns.items():
        cumulative = (1.0 + returns.dropna()).cumprod()
        ax.plot(cumulative.index, cumulative, label=name)
    ax.set_title("Net cumulative return: CF-HMM sector rotation vs baselines")
    ax.set_ylabel("Growth of $1")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "cumulative_returns.png", dpi=180)
    plt.close(fig)


def _plot_regime_weights(diagnostics: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(diagnostics["date"], diagnostics["current_is_turbulent"].astype(int), drawstyle="steps-post")
    axes[0].set_title("HMM turbulent-regime signal at monthly rebalance")
    axes[0].set_ylabel("Turbulent")
    axes[0].grid(alpha=0.25)
    for ticker in ["XLP", "XLU", "XLK", "XLF", "XLE"]:
        axes[1].plot(diagnostics["date"], diagnostics[f"weight_{ticker}"], label=ticker)
    axes[1].set_title("Selected CF-HMM strategy weights")
    axes[1].set_ylabel("Weight")
    axes[1].grid(alpha=0.25)
    axes[1].legend(ncol=5, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "regime_weights.png", dpi=180)
    plt.close(fig)


def _record_to_builtin(obj):
    if isinstance(obj, dict):
        return {k: _record_to_builtin(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_record_to_builtin(v) for v in obj]
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        return obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    FIG_DIR.mkdir(exist_ok=True)
    np.random.seed(SEED)

    prices = _download_prices()
    returns = prices.pct_change(fill_method=None).dropna(how="any")
    returns.to_csv(DATA_DIR / "daily_returns.csv")

    strategy_weights, ew_weights, vt_weights, diagnostics = _build_monthly_weights(returns)
    strategy_weights.to_csv(DATA_DIR / "cf_hmm_rotation_rebalance_weights.csv")
    ew_weights.to_csv(DATA_DIR / "sector_ew_rebalance_weights.csv")
    vt_weights.to_csv(DATA_DIR / "sector_ew_vt_rebalance_weights.csv")
    diagnostics.to_csv(DATA_DIR / "rebalance_diagnostics.csv", index=False)

    cf_returns, cf_detail = _apply_weights(returns, strategy_weights, "cf_hmm_rotation")
    ew_returns, ew_detail = _apply_weights(returns, ew_weights, "sector_ew")
    vt_returns, vt_detail = _apply_weights(returns, vt_weights, "sector_ew_vt")
    return_panel = pd.concat(
        [cf_returns.rename("cf_hmm_rotation"), ew_returns.rename("sector_ew"), vt_returns.rename("sector_ew_vt")],
        axis=1,
    ).dropna()
    return_panel.to_csv(DATA_DIR / "strategy_net_returns.csv")
    pd.concat([cf_detail, ew_detail, vt_detail], axis=1).to_csv(DATA_DIR / "strategy_daily_details.csv")

    strategy_returns = {
        "cf_hmm_rotation": return_panel["cf_hmm_rotation"],
        "sector_ew": return_panel["sector_ew"],
        "sector_ew_vt": return_panel["sector_ew_vt"],
    }
    performance = [
        asdict(_performance("cf_hmm_rotation", return_panel["cf_hmm_rotation"], cf_detail.loc[return_panel.index])),
        asdict(_performance("sector_ew", return_panel["sector_ew"], ew_detail.loc[return_panel.index])),
        asdict(_performance("sector_ew_vt", return_panel["sector_ew_vt"], vt_detail.loc[return_panel.index])),
    ]
    pd.DataFrame(performance).to_csv(DATA_DIR / "performance_summary.csv", index=False)
    dm_tests = _dm_rows(strategy_returns)
    pd.DataFrame(dm_tests).to_csv(DATA_DIR / "dm_tests.csv", index=False)

    bootstrap = {
        "cf_hmm_minus_sector_ew": _bootstrap_sharpe_diff(
            return_panel["cf_hmm_rotation"], return_panel["sector_ew"]
        ),
        "cf_hmm_minus_sector_ew_vt": _bootstrap_sharpe_diff(
            return_panel["cf_hmm_rotation"], return_panel["sector_ew_vt"]
        ),
    }

    _plot_cumulative(strategy_returns)
    _plot_regime_weights(diagnostics)

    perf_by_name = {row["strategy"]: row for row in performance}
    return_passes = [
        row for row in dm_tests if row["loss_fn"] == "negative_return" and row["model_better"]
    ]
    downside_passes = [row for row in dm_tests if row["loss_fn"] == "downside" and row["model_better"]]
    cf_perf = perf_by_name["cf_hmm_rotation"]
    better_sharpe_than_both = (
        cf_perf["sharpe"] > perf_by_name["sector_ew"]["sharpe"]
        and cf_perf["sharpe"] > perf_by_name["sector_ew_vt"]["sharpe"]
    )
    better_mdd_than_both = (
        cf_perf["max_drawdown"] > perf_by_name["sector_ew"]["max_drawdown"]
        and cf_perf["max_drawdown"] > perf_by_name["sector_ew_vt"]["max_drawdown"]
    )
    if len(return_passes) == 2 and better_sharpe_than_both:
        verdict = "CF_HMM_ROTATION_RETURN_PASS"
    elif len(downside_passes) == 2 and better_mdd_than_both:
        verdict = "RISK_REDUCTION_ONLY"
    else:
        verdict = "NULL_CF_HMM_ROTATION_NO_EDGE"

    results = {
        "experiment_id": EXP_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "price_source": "yfinance adjusted close",
            "tickers": PRICE_TICKERS,
            "sector_tickers": SECTOR_TICKERS,
            "price_start": prices.index.min().strftime("%Y-%m-%d"),
            "price_end": prices.index.max().strftime("%Y-%m-%d"),
            "return_start": returns.index.min().strftime("%Y-%m-%d"),
            "return_end": returns.index.max().strftime("%Y-%m-%d"),
            "oos_start": return_panel.index.min().strftime("%Y-%m-%d"),
            "oos_end": return_panel.index.max().strftime("%Y-%m-%d"),
            "oos_days": int(return_panel.shape[0]),
            "rebalance_count": int(strategy_weights.shape[0]),
        },
        "method": {
            "hmm": "2-state GaussianHMM fit on trailing SPY daily returns at each month-end rebalance",
            "turbulent_state": "state with higher fitted return variance",
            "cf_tail_score": "0.65 * Cornish-Fisher 5% VaR loss + 0.35 * empirical ES loss below the CF quantile",
            "lookahead_guard": "rebalance weights are computed at month-end close and shifted one trading day before return application",
            "transaction_cost": TRANSACTION_COST,
            "vt_baseline": f"sector equal weight scaled monthly to {VT_TARGET_VOL:.0%} annualized vol using trailing {VT_LOOKBACK} daily returns",
            "bootstrap": f"{BOOTSTRAP_REPS} circular block bootstrap samples, block length {BOOTSTRAP_BLOCK}",
        },
        "performance": performance,
        "dm_tests": dm_tests,
        "bootstrap_sharpe_diff": bootstrap,
        "regime_summary": {
            "turbulent_rebalance_share": float(diagnostics["current_is_turbulent"].mean()),
            "mean_turbulent_state_prob": float(
                diagnostics.loc[diagnostics["current_is_turbulent"], "current_state_prob"].mean()
            )
            if diagnostics["current_is_turbulent"].any()
            else None,
            "mean_calm_state_prob": float(
                diagnostics.loc[~diagnostics["current_is_turbulent"], "current_state_prob"].mean()
            )
            if (~diagnostics["current_is_turbulent"]).any()
            else None,
            "top_lowest_tail_sector_counts": diagnostics["lowest_tail_sector"].value_counts().to_dict(),
            "top_highest_tail_sector_counts": diagnostics["highest_tail_sector"].value_counts().to_dict(),
        },
        "literature_and_source_links": [
            "https://medium.com/@tandel/options-volatility-analysis-what-cornish-fisher-tail-risk-reveals-about-the-february-2026-sector-e7a4a4fffd66",
            "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1997178",
            "https://www.mdpi.com/1911-8074/13/12/311",
            "https://www.rdocumentation.org/packages/PerformanceAnalytics/versions/0.9.6/topics/VaR.CornishFisher",
        ],
        "files": {
            "daily_returns": "data/daily_returns.csv",
            "cf_hmm_weights": "data/cf_hmm_rotation_rebalance_weights.csv",
            "ew_weights": "data/sector_ew_rebalance_weights.csv",
            "vt_weights": "data/sector_ew_vt_rebalance_weights.csv",
            "rebalance_diagnostics": "data/rebalance_diagnostics.csv",
            "strategy_net_returns": "data/strategy_net_returns.csv",
            "strategy_daily_details": "data/strategy_daily_details.csv",
            "performance_summary": "data/performance_summary.csv",
            "dm_tests": "data/dm_tests.csv",
            "figure_cumulative": "figures/cumulative_returns.png",
            "figure_regime_weights": "figures/regime_weights.png",
        },
    }
    RESULTS_PATH.write_text(json.dumps(_record_to_builtin(results), indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "verdict": verdict,
                "oos_days": int(return_panel.shape[0]),
                "performance": performance,
                "dm_tests": dm_tests,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
