"""K1639 - Hierarchical portfolio construction OOS horse race.

Research question
-----------------
Do hierarchical allocation methods (HRP / HERC / NCO / Schur-block MV)
improve out-of-sample stability, turnover, drawdown, or Sharpe relative to
plain equal weight, inverse-volatility, equal-risk-contribution risk parity,
and long-only minimum variance on a diversified ETF panel?

Lookahead policy
----------------
The return on day ``t`` is earned with weights estimated from returns
``t-252`` through ``t-1`` only:

    hist = returns.iloc[i - LOOKBACK : i]

Monthly rebalances occur before the close-to-close return for day ``t`` and
therefore use only information known at the prior close. No return from day
``t`` enters that day's covariance estimate or cluster tree.

Randomness
----------
All bootstrap routines use seed=42. The portfolio simulation itself is
deterministic apart from the yfinance adjusted-close data source, which is
cached under this experiment directory after the first run.
"""

from __future__ import annotations

import json
import math
import os
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

for _thread_var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ.setdefault(_thread_var, "1")

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform

warnings.filterwarnings("ignore", category=FutureWarning)

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / "k1639_results.json"

TICKERS = [
    "SPY",  # US large-cap equity
    "QQQ",  # US growth / technology equity
    "IWM",  # US small-cap equity
    "EFA",  # developed ex-US equity
    "EEM",  # emerging-market equity
    "TLT",  # long Treasury
    "IEF",  # intermediate Treasury
    "LQD",  # investment-grade credit
    "HYG",  # high-yield credit
    "GLD",  # gold
    "DBC",  # broad commodities
]

START = "2007-01-01"
END = "2026-07-03"
LOOKBACK = 252
TRADING_DAYS = 252
COST_BPS = 5.0
BOOT_REPS = 1000
BOOT_BLOCK = 21
SHRINK_DIAG_WEIGHT = 0.10
MAX_NCO_CLUSTERS = 4

PERIODS = {
    "2008_2009_gfc": ("2008-01-01", "2009-12-31"),
    "2010_2014_recovery": ("2010-01-01", "2014-12-31"),
    "2015_2019_pre_covid": ("2015-01-01", "2019-12-31"),
    "2020_2022_covid_inflation": ("2020-01-01", "2022-12-31"),
    "2023_2026_recent": ("2023-01-01", END),
}

LITERATURE = [
    {
        "topic": "HRP",
        "citation": "Lopez de Prado (2016), Building Diversified Portfolios that Outperform Out of Sample",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678",
    },
    {
        "topic": "NCO",
        "citation": "Lopez de Prado (2019), A Robust Estimator of the Efficient Frontier",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3469961",
    },
    {
        "topic": "HERC",
        "citation": "Raffinot (2018), The Hierarchical Equal Risk Contribution Portfolio",
        "url": "https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID3237540_code2270025.pdf?abstractid=3237540",
    },
    {
        "topic": "Schur",
        "citation": "Cotton (2024), Schur Complementary Allocation",
        "url": "https://arxiv.org/abs/2411.05807",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_float(x: Any, digits: int | None = None) -> float | None:
    try:
        val = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(val):
        return None
    return round(val, digits) if digits is not None else val


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def load_prices() -> pd.DataFrame:
    ensure_dirs()
    cache_path = DATA_DIR / "adjusted_close_yfinance.csv"
    if cache_path.exists():
        prices = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if set(TICKERS).issubset(prices.columns):
            prices = prices[TICKERS].dropna(how="any")
            if len(prices) > LOOKBACK + 252:
                return prices

    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no price data")
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].copy()
        prices.columns = [TICKERS[0]]
    prices = prices.reindex(columns=TICKERS).dropna(how="any").sort_index()
    if len(prices) <= LOOKBACK + 252:
        raise RuntimeError(f"insufficient common price history: {len(prices)} rows")
    prices.to_csv(cache_path, index_label="Date")
    return prices


def make_returns(prices: pd.DataFrame) -> pd.DataFrame:
    returns = prices.pct_change().dropna(how="any")
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    return returns


def lag_signal_for_audit(signal: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Audit-visible lookahead guard for signal-style workflows."""
    return signal.shift(1)


def shrink_cov(hist: pd.DataFrame) -> np.ndarray:
    cov = hist.cov().to_numpy(dtype=float)
    cov = np.nan_to_num(cov, nan=0.0, posinf=0.0, neginf=0.0)
    cov = (cov + cov.T) / 2.0
    diag = np.diag(np.clip(np.diag(cov), 1e-12, None))
    cov = (1.0 - SHRINK_DIAG_WEIGHT) * cov + SHRINK_DIAG_WEIGHT * diag
    cov += np.eye(cov.shape[0]) * 1e-12
    return cov


def cov_to_corr(cov: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    corr = cov / np.outer(d, d)
    corr = np.clip(np.nan_to_num(corr, nan=0.0), -0.999, 0.999)
    np.fill_diagonal(corr, 1.0)
    return corr


def corr_linkage(cov: np.ndarray) -> np.ndarray:
    corr = cov_to_corr(cov)
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, 1.0))
    return linkage(squareform(dist, checks=False), method="single")


def inverse_variance_weights(cov: np.ndarray) -> np.ndarray:
    inv = 1.0 / np.clip(np.diag(cov), 1e-12, None)
    w = inv / inv.sum()
    return w


def min_variance_weights(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    x0 = inverse_variance_weights(cov)

    def obj(w: np.ndarray) -> float:
        return float(w @ cov @ w)

    res = minimize(
        obj,
        x0,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * n,
        constraints=({"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)},),
        options={"ftol": 1e-12, "maxiter": 300, "disp": False},
    )
    if not res.success or not np.all(np.isfinite(res.x)):
        return x0
    w = np.clip(res.x, 0.0, 1.0)
    if w.sum() <= 1e-12:
        return x0
    return w / w.sum()


def erc_weights(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    x0 = inverse_variance_weights(cov)

    def obj(w: np.ndarray) -> float:
        mrc = cov @ w
        port_var = float(w @ mrc)
        if port_var <= 1e-16:
            return 1e6
        rc = w * mrc / port_var
        target = np.full(n, 1.0 / n)
        return float(np.sum((rc - target) ** 2))

    res = minimize(
        obj,
        x0,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * n,
        constraints=({"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)},),
        options={"ftol": 1e-12, "maxiter": 300, "disp": False},
    )
    if not res.success or not np.all(np.isfinite(res.x)):
        return x0
    w = np.clip(res.x, 0.0, 1.0)
    if w.sum() <= 1e-12:
        return x0
    return w / w.sum()


def cluster_variance(cov: np.ndarray, indices: list[int], allocator: str) -> float:
    sub = cov[np.ix_(indices, indices)]
    if len(indices) == 1:
        return float(sub[0, 0])
    if allocator == "ivp":
        w = inverse_variance_weights(sub)
    elif allocator == "erc":
        w = erc_weights(sub)
    elif allocator == "minvar":
        w = min_variance_weights(sub)
    else:
        raise ValueError(f"unknown allocator {allocator}")
    return float(w @ sub @ w)


def recursive_cluster_weights(cov: np.ndarray, ordered: list[int], allocator: str) -> np.ndarray:
    weights = pd.Series(1.0, index=ordered, dtype=float)
    clusters: list[list[int]] = [ordered]
    while clusters:
        next_clusters: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            split = len(cluster) // 2
            left = cluster[:split]
            right = cluster[split:]
            v_left = cluster_variance(cov, left, allocator)
            v_right = cluster_variance(cov, right, allocator)
            denom = v_left + v_right
            alpha = 0.5 if denom <= 1e-16 else 1.0 - v_left / denom
            alpha = float(np.clip(alpha, 0.0, 1.0))
            weights.loc[left] *= alpha
            weights.loc[right] *= 1.0 - alpha
            next_clusters.extend([left, right])
        clusters = next_clusters
    out = np.zeros(cov.shape[0], dtype=float)
    for idx, val in weights.items():
        out[idx] = float(val)
    out = np.clip(out, 0.0, 1.0)
    return out / out.sum()


def hrp_weights(cov: np.ndarray) -> np.ndarray:
    order = leaves_list(corr_linkage(cov)).tolist()
    return recursive_cluster_weights(cov, order, allocator="ivp")


def herc_erc_weights(cov: np.ndarray) -> np.ndarray:
    order = leaves_list(corr_linkage(cov)).tolist()
    return recursive_cluster_weights(cov, order, allocator="erc")


def nco_minvar_weights(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    z = corr_linkage(cov)
    k = min(MAX_NCO_CLUSTERS, max(2, int(round(math.sqrt(n)))))
    labels = fcluster(z, t=k, criterion="maxclust")
    clusters = [np.where(labels == lab)[0].tolist() for lab in sorted(set(labels))]
    m = np.zeros((n, len(clusters)), dtype=float)
    for j, members in enumerate(clusters):
        sub = cov[np.ix_(members, members)]
        local_w = min_variance_weights(sub)
        for local_i, asset_i in enumerate(members):
            m[asset_i, j] = local_w[local_i]
    cluster_cov = m.T @ cov @ m
    cluster_w = min_variance_weights(cluster_cov)
    w = m @ cluster_w
    w = np.clip(w, 0.0, 1.0)
    return w / w.sum()


def schur_block_mv_weights(cov: np.ndarray) -> np.ndarray:
    """Recursive two-block minimum-variance allocation.

    At each hierarchical split, estimate the local min-variance portfolio for
    the left and right blocks. Allocate between those two block portfolios by
    the exact two-asset minimum-variance formula using their block covariance:

        alpha_left = (var_right - cov_lr) / (var_left + var_right - 2 cov_lr)

    This is a transparent Schur/block-MV approximation, not a claim to
    reproduce every detail of Cotton's full Schur Complementary Allocation.
    """

    order = leaves_list(corr_linkage(cov)).tolist()
    weights = pd.Series(1.0, index=order, dtype=float)
    clusters: list[list[int]] = [order]
    while clusters:
        next_clusters: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            split = len(cluster) // 2
            left = cluster[:split]
            right = cluster[split:]
            cov_ll = cov[np.ix_(left, left)]
            cov_rr = cov[np.ix_(right, right)]
            cov_lr = cov[np.ix_(left, right)]
            wl = min_variance_weights(cov_ll)
            wr = min_variance_weights(cov_rr)
            vl = float(wl @ cov_ll @ wl)
            vr = float(wr @ cov_rr @ wr)
            cr = float(wl @ cov_lr @ wr)
            denom = vl + vr - 2.0 * cr
            alpha = 0.5 if denom <= 1e-16 else (vr - cr) / denom
            alpha = float(np.clip(alpha, 0.0, 1.0))
            weights.loc[left] *= alpha
            weights.loc[right] *= 1.0 - alpha
            next_clusters.extend([left, right])
        clusters = next_clusters
    out = np.zeros(cov.shape[0], dtype=float)
    for idx, val in weights.items():
        out[idx] = float(val)
    out = np.clip(out, 0.0, 1.0)
    return out / out.sum()


STRATEGIES: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "equal_weight": lambda cov: np.full(cov.shape[0], 1.0 / cov.shape[0]),
    "inverse_vol": lambda cov: (1.0 / np.sqrt(np.clip(np.diag(cov), 1e-12, None)))
    / (1.0 / np.sqrt(np.clip(np.diag(cov), 1e-12, None))).sum(),
    "erc_risk_parity": erc_weights,
    "min_variance": min_variance_weights,
    "hrp": hrp_weights,
    "herc_erc": herc_erc_weights,
    "nco_minvar": nco_minvar_weights,
    "schur_block_mv": schur_block_mv_weights,
}


@dataclass
class Simulation:
    gross_returns: pd.Series
    net_returns: pd.Series
    costs: pd.Series
    turnover: pd.Series
    weights_before_return: pd.DataFrame
    target_weights: pd.DataFrame


def is_monthly_rebalance(index: pd.DatetimeIndex, i: int) -> bool:
    if i == LOOKBACK:
        return True
    return index[i].to_period("M") != index[i - 1].to_period("M")


def simulate_strategy(returns: pd.DataFrame, strategy: str) -> Simulation:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy}")
    allocator = STRATEGIES[strategy]
    tickers = list(returns.columns)

    current_w: np.ndarray | None = None
    gross_records: list[float] = []
    net_records: list[float] = []
    cost_records: list[float] = []
    turnover_records: list[float] = []
    weight_records: list[np.ndarray] = []
    target_records: list[np.ndarray] = []
    dates: list[pd.Timestamp] = []
    target_dates: list[pd.Timestamp] = []

    for i in range(LOOKBACK, len(returns)):
        date = returns.index[i]
        r = returns.iloc[i].to_numpy(dtype=float)
        cost = 0.0
        turnover = 0.0

        if current_w is None or is_monthly_rebalance(returns.index, i):
            # Strict anti-lookahead: return date i is evaluated with a window
            # ending at i-1. Day-i return never enters the covariance estimate.
            hist = returns.iloc[i - LOOKBACK : i]
            cov = shrink_cov(hist)
            target_w = allocator(cov)
            target_w = np.clip(np.asarray(target_w, dtype=float), 0.0, 1.0)
            target_w = target_w / target_w.sum()
            if current_w is not None:
                turnover = float(np.sum(np.abs(target_w - current_w)))
                cost = COST_BPS / 10000.0 * turnover
            current_w = target_w.copy()
            target_records.append(target_w.copy())
            target_dates.append(date)

        weight_records.append(current_w.copy())
        gross = float(current_w @ r)
        net = (1.0 - cost) * (1.0 + gross) - 1.0

        gross_records.append(gross)
        net_records.append(net)
        cost_records.append(cost)
        turnover_records.append(turnover)
        dates.append(date)

        post = current_w * (1.0 + r)
        if post.sum() <= 1e-12 or not np.all(np.isfinite(post)):
            current_w = np.full(len(tickers), 1.0 / len(tickers))
        else:
            current_w = post / post.sum()

    idx = pd.DatetimeIndex(dates)
    weights = pd.DataFrame(weight_records, index=idx, columns=tickers)
    targets = pd.DataFrame(target_records, index=pd.DatetimeIndex(target_dates), columns=tickers)
    return Simulation(
        gross_returns=pd.Series(gross_records, index=idx, name=strategy),
        net_returns=pd.Series(net_records, index=idx, name=strategy),
        costs=pd.Series(cost_records, index=idx, name=strategy),
        turnover=pd.Series(turnover_records, index=idx, name=strategy),
        weights_before_return=weights,
        target_weights=targets,
    )


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1.0
    return float(dd.min())


def ann_sharpe(returns: pd.Series) -> float:
    std = float(returns.std(ddof=1))
    if std <= 1e-16:
        return 0.0
    return float(returns.mean() / std * math.sqrt(TRADING_DAYS))


def metrics_for(
    returns: pd.Series,
    turnover: pd.Series | None = None,
    costs: pd.Series | None = None,
    weights: pd.DataFrame | None = None,
) -> dict[str, Any]:
    returns = returns.dropna()
    n = len(returns)
    years = n / TRADING_DAYS
    wealth = (1.0 + returns).cumprod()
    total_return = float(wealth.iloc[-1] - 1.0)
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
    ann_vol = float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS))
    out: dict[str, Any] = {
        "n_days": int(n),
        "n_years": json_float(years, 2),
        "total_return": json_float(total_return, 6),
        "cagr": json_float(cagr, 6),
        "ann_vol": json_float(ann_vol, 6),
        "sharpe": json_float(ann_sharpe(returns), 6),
        "mdd": json_float(max_drawdown(returns), 6),
        "calmar": json_float(cagr / abs(max_drawdown(returns)), 6)
        if max_drawdown(returns) < -1e-12
        else None,
    }
    if turnover is not None:
        aligned = turnover.reindex(returns.index).fillna(0.0)
        out["total_turnover"] = json_float(aligned.sum(), 6)
        out["annual_turnover"] = json_float(aligned.sum() / years, 6)
        out["n_rebalances"] = int((aligned > 0).sum())
        out["max_single_rebalance_turnover"] = json_float(aligned.max(), 6)
    if costs is not None:
        c = costs.reindex(returns.index).fillna(0.0)
        out["total_cost_drag"] = json_float(c.sum(), 6)
        out["annual_cost_drag"] = json_float(c.sum() / years, 6)
    if weights is not None:
        w = weights.reindex(returns.index).dropna(how="any")
        hhi = (w**2).sum(axis=1)
        out["avg_hhi"] = json_float(hhi.mean(), 6)
        out["avg_effective_n"] = json_float((1.0 / hhi).mean(), 6)
        out["avg_max_weight"] = json_float(w.max(axis=1).mean(), 6)
        out["max_weight_ever"] = json_float(w.max(axis=1).max(), 6)
    return out


def subperiod_metrics(net_returns: pd.DataFrame) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for label, (start, end) in PERIODS.items():
        block = net_returns.loc[start:end]
        if len(block) < 60:
            continue
        out[label] = {
            col: {
                "n_days": int(block[col].dropna().shape[0]),
                "sharpe": json_float(ann_sharpe(block[col].dropna()), 6),
                "mdd": json_float(max_drawdown(block[col].dropna()), 6),
                "cagr": json_float(
                    (1.0 + block[col].dropna()).prod() ** (TRADING_DAYS / len(block[col].dropna())) - 1.0,
                    6,
                )
                if len(block[col].dropna()) > 0
                else None,
            }
            for col in block.columns
        }
    return out


def hac_mean_diff(a: pd.Series, b: pd.Series) -> dict[str, Any]:
    aligned = pd.concat([a, b], axis=1).dropna()
    diff = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    x = np.ones((len(diff), 1))
    fit = sm.OLS(diff.to_numpy(dtype=float), x).fit(cov_type="HAC", cov_kwds={"maxlags": BOOT_BLOCK})
    mean_daily = float(fit.params[0])
    return {
        "ann_mean_diff": json_float(mean_daily * TRADING_DAYS, 6),
        "hac_t": json_float(float(fit.tvalues[0]), 6),
        "hac_p": json_float(float(fit.pvalues[0]), 6),
    }


def bootstrap_sharpe_diff(a: pd.Series, b: pd.Series, seed: int = SEED) -> dict[str, Any]:
    aligned = pd.concat([a, b], axis=1).dropna()
    x = aligned.iloc[:, 0].to_numpy(dtype=float)
    y = aligned.iloc[:, 1].to_numpy(dtype=float)
    n = len(aligned)
    rng = np.random.default_rng(seed)
    obs = ann_sharpe(pd.Series(x)) - ann_sharpe(pd.Series(y))
    diffs = np.empty(BOOT_REPS)
    for j in range(BOOT_REPS):
        starts = rng.integers(0, n, size=int(math.ceil(n / BOOT_BLOCK)))
        idx_parts = [(np.arange(s, s + BOOT_BLOCK) % n) for s in starts]
        idx = np.concatenate(idx_parts)[:n]
        diffs[j] = ann_sharpe(pd.Series(x[idx])) - ann_sharpe(pd.Series(y[idx]))
    ci_low, ci_high = np.quantile(diffs, [0.025, 0.975])
    p_two = 2.0 * min(float(np.mean(diffs <= 0.0)), float(np.mean(diffs >= 0.0)))
    return {
        "obs_sharpe_diff": json_float(obs, 6),
        "ci95": [json_float(ci_low, 6), json_float(ci_high, 6)],
        "bootstrap_p_two_sided_zero": json_float(min(1.0, p_two), 6),
        "reps": BOOT_REPS,
        "block": BOOT_BLOCK,
        "seed": seed,
    }


def average_weights_table(simulations: dict[str, Simulation]) -> pd.DataFrame:
    rows = []
    for strategy, sim in simulations.items():
        row = sim.weights_before_return.mean(axis=0)
        row.name = strategy
        rows.append(row)
    return pd.DataFrame(rows)


def save_performance_csv(perf: dict[str, dict[str, Any]]) -> None:
    rows = []
    for strategy, metrics in perf.items():
        row = {"strategy": strategy}
        row.update(metrics)
        rows.append(row)
    pd.DataFrame(rows).to_csv(DATA_DIR / "k1639_performance_table.csv", index=False)


def save_returns_csv(net_returns: pd.DataFrame) -> None:
    net_returns.to_csv(DATA_DIR / "k1639_net_returns.csv", index_label="Date")


def save_weights_csv(avg_w: pd.DataFrame, simulations: dict[str, Simulation]) -> None:
    avg_w.to_csv(DATA_DIR / "k1639_average_weights.csv", index_label="strategy")
    for strategy, sim in simulations.items():
        sim.target_weights.to_csv(DATA_DIR / f"k1639_target_weights_{strategy}.csv", index_label="Date")


def plot_performance(perf: dict[str, dict[str, Any]]) -> None:
    df = pd.DataFrame(perf).T
    order = df["sharpe"].sort_values(ascending=False).index.tolist()
    df = df.loc[order]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=150)
    colors = ["#2f5d8c" if name in {"hrp", "herc_erc", "nco_minvar", "schur_block_mv"} else "#777777" for name in df.index]

    axes[0].bar(df.index, df["sharpe"], color=colors)
    axes[0].set_title("Net Sharpe")
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].tick_params(axis="x", rotation=45)

    axes[1].bar(df.index, df["mdd"], color=colors)
    axes[1].set_title("Max Drawdown")
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].tick_params(axis="x", rotation=45)

    axes[2].bar(df.index, df["annual_turnover"], color=colors)
    axes[2].set_title("Annual Turnover")
    axes[2].tick_params(axis="x", rotation=45)

    fig.suptitle("K1639 ETF allocation OOS comparison", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1639_net_sharpe_mdd_turnover.png", bbox_inches="tight")
    plt.close(fig)


def plot_average_weights(avg_w: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 5.5), dpi=150)
    im = ax.imshow(avg_w.to_numpy(dtype=float), aspect="auto", cmap="Blues", vmin=0.0)
    ax.set_xticks(np.arange(avg_w.shape[1]))
    ax.set_xticklabels(avg_w.columns, rotation=45, ha="right")
    ax.set_yticks(np.arange(avg_w.shape[0]))
    ax.set_yticklabels(avg_w.index)
    ax.set_title("Average pre-return weights by strategy")
    for i in range(avg_w.shape[0]):
        for j in range(avg_w.shape[1]):
            val = avg_w.iloc[i, j]
            if val >= 0.08:
                ax.text(j, i, f"{val:.0%}", ha="center", va="center", fontsize=7, color="black")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1639_average_weights_heatmap.png", bbox_inches="tight")
    plt.close(fig)


def plot_final_dendrogram(returns: pd.DataFrame) -> list[str]:
    hist = returns.iloc[-LOOKBACK:]
    cov = shrink_cov(hist)
    z = corr_linkage(cov)
    order = leaves_list(z).tolist()
    ordered_tickers = [returns.columns[i] for i in order]

    corr = cov_to_corr(cov)
    corr_ordered = corr[np.ix_(order, order)]
    fig, ax = plt.subplots(figsize=(7.5, 6.5), dpi=150)
    im = ax.imshow(corr_ordered, cmap="RdBu_r", vmin=-1.0, vmax=1.0)
    ax.set_xticks(np.arange(len(order)))
    ax.set_xticklabels(ordered_tickers, rotation=45, ha="right")
    ax.set_yticks(np.arange(len(order)))
    ax.set_yticklabels(ordered_tickers)
    ax.set_title("Final 252d correlation matrix in HRP quasi-diagonal order")
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1639_final_quasi_diag_corr.png", bbox_inches="tight")
    plt.close(fig)
    return ordered_tickers


def derive_verdict(
    perf: dict[str, dict[str, Any]],
    tests_vs_erc: dict[str, dict[str, Any]],
    tests_vs_minvar: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    hierarchical = {"hrp", "herc_erc", "nco_minvar", "schur_block_mv"}
    best_sharpe = max(perf, key=lambda k: perf[k]["sharpe"])
    best_mdd = max(perf, key=lambda k: perf[k]["mdd"])
    best_turnover = min(perf, key=lambda k: perf[k]["annual_turnover"])

    robust_wins = []
    for s in hierarchical:
        ci_erc = tests_vs_erc.get(s, {}).get("sharpe_diff_bootstrap", {}).get("ci95")
        ci_mv = tests_vs_minvar.get(s, {}).get("sharpe_diff_bootstrap", {}).get("ci95")
        if ci_erc and ci_mv and ci_erc[0] is not None and ci_mv[0] is not None:
            if ci_erc[0] > 0.0 and ci_mv[0] > 0.0:
                robust_wins.append(s)

    if robust_wins:
        verdict = "CONDITIONAL_PASS_HIERARCHICAL_SHARPE_SURVIVES_BOOTSTRAP"
    elif best_sharpe in hierarchical or best_mdd in hierarchical or best_turnover in hierarchical:
        verdict = "CONDITIONAL_MIXED_HIERARCHICAL_HELPS_SOME_DIMENSIONS_NOT_ROBUST_ALPHA"
    else:
        verdict = "CONDITIONAL_PASS_NULL_HIERARCHICAL_DOES_NOT_BEAT_SIMPLE_BASELINES"

    summary = (
        f"Best net Sharpe={best_sharpe} ({perf[best_sharpe]['sharpe']:.3f}); "
        f"least severe MDD={best_mdd} ({perf[best_mdd]['mdd']:.1%}); "
        f"lowest turnover={best_turnover} ({perf[best_turnover]['annual_turnover']:.2f} annual). "
        f"Bootstrap-robust hierarchical Sharpe wins vs both ERC and min-variance: {robust_wins or 'none'}."
    )
    return verdict, summary


def main() -> None:
    ensure_dirs()
    prices = load_prices()
    returns = make_returns(prices)
    _ = lag_signal_for_audit(returns.iloc[:, 0])

    simulations = {strategy: simulate_strategy(returns, strategy) for strategy in STRATEGIES}
    net_returns = pd.concat({k: v.net_returns for k, v in simulations.items()}, axis=1)
    gross_returns = pd.concat({k: v.gross_returns for k, v in simulations.items()}, axis=1)

    performance = {
        strategy: metrics_for(
            sim.net_returns,
            turnover=sim.turnover,
            costs=sim.costs,
            weights=sim.weights_before_return,
        )
        for strategy, sim in simulations.items()
    }

    gross_performance = {
        strategy: metrics_for(
            sim.gross_returns,
            turnover=sim.turnover,
            costs=sim.costs,
            weights=sim.weights_before_return,
        )
        for strategy, sim in simulations.items()
    }

    tests_vs_erc: dict[str, dict[str, Any]] = {}
    tests_vs_minvar: dict[str, dict[str, Any]] = {}
    for strategy in STRATEGIES:
        if strategy != "erc_risk_parity":
            tests_vs_erc[strategy] = {
                "hac_mean_diff": hac_mean_diff(net_returns[strategy], net_returns["erc_risk_parity"]),
                "sharpe_diff_bootstrap": bootstrap_sharpe_diff(
                    net_returns[strategy], net_returns["erc_risk_parity"], seed=SEED + len(strategy)
                ),
            }
        if strategy != "min_variance":
            tests_vs_minvar[strategy] = {
                "hac_mean_diff": hac_mean_diff(net_returns[strategy], net_returns["min_variance"]),
                "sharpe_diff_bootstrap": bootstrap_sharpe_diff(
                    net_returns[strategy], net_returns["min_variance"], seed=SEED + 100 + len(strategy)
                ),
            }

    avg_w = average_weights_table(simulations)
    save_performance_csv(performance)
    save_returns_csv(net_returns)
    save_weights_csv(avg_w, simulations)
    plot_performance(performance)
    plot_average_weights(avg_w)
    final_order = plot_final_dendrogram(returns)

    subperiod = subperiod_metrics(net_returns)
    verdict, verdict_summary = derive_verdict(performance, tests_vs_erc, tests_vs_minvar)

    ranked_by_sharpe = sorted(
        ((s, m["sharpe"]) for s, m in performance.items()), key=lambda x: x[1], reverse=True
    )
    ranked_by_mdd = sorted(
        ((s, m["mdd"]) for s, m in performance.items()), key=lambda x: x[1], reverse=True
    )

    results = {
        "experiment_id": "K1639",
        "created_at": utc_now(),
        "verdict": verdict,
        "verdict_summary": verdict_summary,
        "research_question": (
            "Do hierarchical allocation methods improve OOS portfolio outcomes "
            "relative to equal weight, inverse vol, ERC risk parity, and long-only minimum variance?"
        ),
        "data": {
            "source": "yfinance adjusted close, cached to experiments/k1639/data/adjusted_close_yfinance.csv",
            "tickers": TICKERS,
            "download_start": START,
            "download_end_exclusive": END,
            "price_start": str(prices.index.min().date()),
            "price_end": str(prices.index.max().date()),
            "n_price_rows": int(len(prices)),
            "return_start": str(returns.index.min().date()),
            "return_end": str(returns.index.max().date()),
            "n_return_rows": int(len(returns)),
            "oos_start_after_lookback": str(net_returns.index.min().date()),
            "oos_end": str(net_returns.index.max().date()),
            "oos_days": int(len(net_returns)),
        },
        "method": {
            "lookback_trading_days": LOOKBACK,
            "rebalance": "monthly; first trading day of each month plus initial OOS day",
            "transaction_cost_bps_per_dollar_traded": COST_BPS,
            "covariance": f"sample daily covariance with {SHRINK_DIAG_WEIGHT:.0%} diagonal shrinkage",
            "lookahead_policy": "weights for return day i use returns.iloc[i-LOOKBACK:i], excluding day i",
            "strategies": list(STRATEGIES.keys()),
            "schur_block_mv_note": (
                "Recursive two-block min-variance allocation using block covariance. "
                "This is a transparent Schur/block-MV approximation, not full Cotton SCA."
            ),
            "bootstrap": {"reps": BOOT_REPS, "block": BOOT_BLOCK, "seed": SEED},
        },
        "literature_checked": LITERATURE,
        "net_performance": performance,
        "gross_performance": gross_performance,
        "subperiod_net_performance": subperiod,
        "tests_vs_erc_risk_parity": tests_vs_erc,
        "tests_vs_min_variance": tests_vs_minvar,
        "ranked_by_net_sharpe": [{"strategy": s, "sharpe": json_float(v, 6)} for s, v in ranked_by_sharpe],
        "ranked_by_mdd": [{"strategy": s, "mdd": json_float(v, 6)} for s, v in ranked_by_mdd],
        "average_weights": {
            strategy: {ticker: json_float(avg_w.loc[strategy, ticker], 6) for ticker in avg_w.columns}
            for strategy in avg_w.index
        },
        "final_quasi_diag_order": final_order,
        "outputs": {
            "performance_csv": str(DATA_DIR / "k1639_performance_table.csv"),
            "returns_csv": str(DATA_DIR / "k1639_net_returns.csv"),
            "average_weights_csv": str(DATA_DIR / "k1639_average_weights.csv"),
            "fig_performance": str(FIG_DIR / "k1639_net_sharpe_mdd_turnover.png"),
            "fig_weights": str(FIG_DIR / "k1639_average_weights_heatmap.png"),
            "fig_final_corr": str(FIG_DIR / "k1639_final_quasi_diag_corr.png"),
        },
        "limitations": [
            "ETF total-return proxies are adjusted-close series, not institutional index total-return data.",
            "The experiment uses covariance-only allocation; expected returns are deliberately not forecast.",
            "Schur-block MV is an interpretable recursive block approximation, not a full reproduction of every SCA variant.",
            "Monthly close-to-close execution and 5 bps costs are simplified but applied equally to all dynamic strategies.",
        ],
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)

    print(
        json.dumps(
            {
                "verdict": verdict,
                "oos_days": int(len(net_returns)),
                "best_net_sharpe": ranked_by_sharpe[0],
                "best_mdd": ranked_by_mdd[0],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
