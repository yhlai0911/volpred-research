"""K1714 — Realized-covariance HAR vs shrinkage/EWMA in out-of-sample GMV portfolios.

Research question
-----------------
Does modelling the *realized covariance matrix* with a HAR cascade (Cholesky
parameterisation, Chiriac & Voev 2011) deliver a lower out-of-sample realised
variance for a global-minimum-variance (GMV) portfolio than the standard
covariance estimators used in practice (rolling sample second moment,
Ledoit-Wolf shrinkage, RiskMetrics EWMA)?

Every configuration constant in the CONFIG block below is PRE-REGISTERED: it was
fixed before any result was inspected, and the README states the win/tie/lose
rule ex ante. Nothing here is tuned on the outcome.

Honesty notes that matter for reading the numbers
-------------------------------------------------
* We have DAILY data only, so there is no intraday realised covariance. The
  proxy is a NON-OVERLAPPING k-day block sum of daily return outer products
  (French-Schwert-Stambaugh 1987 style). Non-overlap is the whole point: a
  rolling-window proxy would share k-1 of k days between consecutive
  observations, so "forecasting" it would be ~mechanical and the HAR advantage
  would be tautological. See README §3.
* The horse race is scored on the realised variance of ACTUAL daily portfolio
  returns, never on how well anyone predicts the proxy. So proxy choice affects
  the estimator, not the scorer.
* GMV weights are scale invariant (w = S^-1 1 / 1'S^-1 1 is unchanged by
  S -> cS), so the k-day scale of the block RCov never enters the weights.

Run:  uv run python experiments/K1714/K1714.py
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("K1714")

# ---------------------------------------------------------------------------
# CONFIG — frozen before any result was seen. Do not tune on outcomes.
# ---------------------------------------------------------------------------

ASSETS: Tuple[str, ...] = ("SPY", "QQQ", "GLD", "TLT")  # canonical Cholesky order
DOWNLOAD_START = "2004-01-01"

# Block length in trading days for the realised-covariance proxy.
# 5 is the headline; 10 is a PRE-REGISTERED co-reported robustness check.
# If the two disagree we report the disagreement; we do not pick the winner.
BLOCK_LENS: Tuple[int, ...] = (5, 10)
HEADLINE_BLOCK_LEN = 5

# HAR cascade in *blocks*. With 5-day blocks (1, 4, 12) ~ (week, month, quarter).
HAR_LAGS: Tuple[int, int, int] = (1, 4, 12)

# Burn-in measured in TRADING DAYS so both block lengths share an OOS start date.
BURNIN_DAYS = 780  # ~3 years -> OOS starts late 2007, so the GFC is in-sample-out.

BENCH_WINDOW_DAYS = 252  # rolling window for sample cov and Ledoit-Wolf
EWMA_LAMBDA = 0.94  # RiskMetrics

SEED = 42
ALPHA = 0.05
HARVEY_T = 3.0  # Harvey (2016) bar for a new finding in finance

# PRE-REGISTERED multiple-comparison family: the three covariance benchmarks the
# HAR-RCov model is being tested against. equal_weight is a REFERENCE point, not
# a member of the test family (it is not a covariance estimator).
PRIMARY_FAMILY: Tuple[str, ...] = ("sample", "ledoit_wolf", "ewma")
REFERENCE_STRATEGIES: Tuple[str, ...] = ("equal_weight",)
MODEL_NAME = "har_rcov_chol"

BOOTSTRAP_REPS = 2000
HAC_LAG_GRID: Tuple[int, ...] = (0, 5, 10, 20, 40, 63)
COST_BPS_GRID: Tuple[float, ...] = (0.0, 5.0, 10.0, 20.0)

TRADING_DAYS_PER_YEAR = 252

rng_global = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def load_prices() -> pd.DataFrame:
    """Adjusted closes for ASSETS, cached to disk for byte-level reproducibility."""
    cache = HERE / "data" / "prices_raw.csv"
    if cache.exists():
        px = pd.read_csv(cache, index_col=0, parse_dates=True)
        log.info("loaded cached prices: %s rows from %s", len(px), cache.name)
        return px[list(ASSETS)]

    import yfinance as yf

    raw = yf.download(
        list(ASSETS), start=DOWNLOAD_START, auto_adjust=True, progress=False
    )["Close"]
    px = raw[list(ASSETS)].dropna()
    cache.parent.mkdir(parents=True, exist_ok=True)
    px.to_csv(cache)
    log.info("downloaded and cached %s rows -> %s", len(px), cache.name)
    return px


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Realised covariance proxy
# ---------------------------------------------------------------------------


def build_block_rcov(returns: np.ndarray, block_len: int) -> Tuple[np.ndarray, np.ndarray]:
    """Non-overlapping block realised covariance from daily simple returns.

    RCov_b = sum_{t in block b} r_t r_t'  (NOT demeaned: demeaning a k-obs block
    costs a rank and the daily mean is negligible relative to daily vol).

    With N assets and k > N observations per block the sum of k rank-1 matrices
    is generically full rank, hence positive definite. That is why block_len
    must exceed the number of assets.

    Returns
    -------
    rcov : (B, N, N)
    day_index : (B, 2) inclusive [first_day, last_day] row index of each block
    """
    n_days, n_assets = returns.shape
    if block_len <= n_assets:
        raise ValueError(
            f"block_len={block_len} must exceed n_assets={n_assets} for a PD block RCov"
        )
    n_blocks = n_days // block_len
    rcov = np.empty((n_blocks, n_assets, n_assets))
    day_index = np.empty((n_blocks, 2), dtype=int)
    for b in range(n_blocks):
        lo, hi = b * block_len, (b + 1) * block_len
        r = returns[lo:hi]
        rcov[b] = r.T @ r
        day_index[b] = (lo, hi - 1)
    return rcov, day_index


def chol_vec(mat: np.ndarray) -> np.ndarray:
    """Lower-Cholesky factor flattened to its N(N+1)/2 free elements."""
    L = np.linalg.cholesky(mat)
    idx = np.tril_indices(mat.shape[0])
    return L[idx]


def chol_unvec(vec: np.ndarray, n: int) -> np.ndarray:
    """Inverse of chol_vec: rebuild L then return L L'.

    L L' is positive definite for ANY real L with non-zero diagonal — the sign of
    the diagonal is irrelevant. This is the reason we forecast the raw Cholesky
    elements rather than log-diagonal ones: positive definiteness is guaranteed
    by construction, not by luck or by a numerical repair step.
    """
    L = np.zeros((n, n))
    L[np.tril_indices(n)] = vec
    return L @ L.T


def logm_vec(mat: np.ndarray) -> np.ndarray:
    """vech of the matrix logarithm (Bauer & Vorkink 2011 parameterisation).

    log(S) = Q diag(log w) Q' from the symmetric eigendecomposition. Unlike the
    Cholesky factor this map is permutation EQUIVARIANT, so re-running the whole
    pipeline under it is the clean test of whether the Cholesky ordering
    dependence is what drives the headline result.
    """
    w, Q = np.linalg.eigh(mat)
    if w.min() <= 0:
        raise np.linalg.LinAlgError(f"non-PD matrix in logm_vec: min eig {w.min():.3e}")
    logs = (Q * np.log(w)) @ Q.T
    return logs[np.tril_indices(mat.shape[0])]


def logm_unvec(vec: np.ndarray, n: int) -> np.ndarray:
    """Inverse of logm_vec: rebuild the symmetric log-matrix, then exponentiate.

    exp(A) is positive definite for ANY real symmetric A in exact arithmetic —
    but float64 is not exact arithmetic. When the eigenvalue dynamic range of
    exp(A) exceeds ~1/eps, the matrix product (Q * exp(w)) @ Q.T carries
    rounding noise of order eps * max(exp(w)), which can push the smallest true
    eigenvalue (possibly ~exp(-20)) below zero (2026-08-04 certification review,
    blocking defect). Symmetrising removes the asymmetric half of that noise;
    the eigenvalue clip at the rounding floor restores the PD-by-construction
    contract at exactly the magnitude where float64 stops being able to
    represent the true value anyway. Inputs from the actual pipeline sit far
    above this floor, so the clip is a no-op there.
    """
    A = np.zeros((n, n))
    A[np.tril_indices(n)] = vec
    A = A + A.T - np.diag(np.diag(A))
    w, Q = np.linalg.eigh(A)
    w_exp = np.exp(w)
    s = (Q * w_exp) @ Q.T
    s = (s + s.T) / 2.0
    floor = np.finfo(float).eps * w_exp.max()
    v, U = np.linalg.eigh(s)
    if v.min() < floor:
        s = (U * np.maximum(v, floor)) @ U.T
        s = (s + s.T) / 2.0
    return s


# Both maps guarantee positive definiteness on inversion, which is why the
# PD-failure rate reported in the results is structurally zero for both.
PARAMETERISATIONS = {
    "chol": (chol_vec, chol_unvec),
    "logm": (logm_vec, logm_unvec),
}


# ---------------------------------------------------------------------------
# HAR on the transformed covariance elements
# ---------------------------------------------------------------------------


def _har_regressors(vecs: np.ndarray, lags: Sequence[int]) -> np.ndarray:
    """Design tensor X of shape (B, 1 + len(lags), K).

    X[o, :, k] = [1, mean(v_{o-l+1..o}, k) for l in lags]

    Row o encodes information available at the END of block o, i.e. it is the
    regressor set used to forecast block o+1. Rows with o < max(lags) - 1 are
    filled with NaN and are never used.
    """
    B, K = vecs.shape
    max_lag = max(lags)
    X = np.full((B, 1 + len(lags), K), np.nan)
    csum = np.vstack([np.zeros((1, K)), np.cumsum(vecs, axis=0)])  # (B+1, K)
    for o in range(max_lag - 1, B):
        X[o, 0, :] = 1.0
        for j, l in enumerate(lags):
            X[o, 1 + j, :] = (csum[o + 1] - csum[o + 1 - l]) / l
    return X


def har_forecast_path(
    vecs: np.ndarray, first_forecast_block: int, lags: Sequence[int] = HAR_LAGS
) -> Tuple[np.ndarray, np.ndarray]:
    """Expanding-window HAR forecasts of the Cholesky vector, refit every block.

    Timing contract (this is the lookahead-critical part)
    -----------------------------------------------------
    To forecast block t we use origin o = t-1 (information through the end of
    block t-1) and train on origin/target pairs (o', o'+1) with o' <= t-2, so the
    latest training TARGET is block t-1 — itself fully observed at the end of
    block t-1. No training row and no regressor touches block t or later.

    Returns
    -------
    fcst : (B, K) forecast Cholesky vectors, NaN before first_forecast_block
    n_train : (B,) number of training rows used at each forecast block
    """
    B, K = vecs.shape
    max_lag = max(lags)
    X = _har_regressors(vecs, lags)
    first_origin = max_lag - 1  # earliest usable origin

    fcst = np.full((B, K), np.nan)
    n_train = np.zeros(B, dtype=int)

    for t in range(first_forecast_block, B):
        origin = t - 1
        train_origins = np.arange(first_origin, t - 1)  # o' <= t-2
        if len(train_origins) < 2 * (1 + len(lags)):
            raise ValueError(
                f"block {t}: only {len(train_origins)} training rows, "
                "burn-in is too short for a stable HAR fit"
            )
        n_train[t] = len(train_origins)
        for k in range(K):
            Xk = X[train_origins, :, k]  # (n, 1+len(lags))
            yk = vecs[train_origins + 1, k]
            beta, *_ = np.linalg.lstsq(Xk, yk, rcond=None)
            fcst[t, k] = X[origin, :, k] @ beta
    return fcst, n_train


# ---------------------------------------------------------------------------
# Benchmark covariance estimators
# ---------------------------------------------------------------------------


def sample_second_moment(window: np.ndarray) -> np.ndarray:
    """Non-demeaned sample second moment.

    Non-demeaned on purpose: with this convention the mean of m consecutive block
    RCovs divided by block_len is EXACTLY this estimator over the same
    5m days, which makes the HAR model and this benchmark measurable functions of
    the identical daily return history. The comparison is then a pure test of the
    weighting scheme, not of who saw more data.
    """
    return window.T @ window / len(window)


def ledoit_wolf_cov(window: np.ndarray) -> np.ndarray:
    from sklearn.covariance import LedoitWolf

    lw = LedoitWolf(assume_centered=True).fit(window)
    return lw.covariance_


def ewma_path(returns: np.ndarray, lam: float, init_window: int) -> np.ndarray:
    """RiskMetrics EWMA second moment available AFTER observing each day.

    ewma[d] uses returns[0..d] inclusive and nothing later.
    """
    n_days, n_assets = returns.shape
    out = np.full((n_days, n_assets, n_assets), np.nan)
    S = sample_second_moment(returns[:init_window])
    out[init_window - 1] = S
    for d in range(init_window, n_days):
        r = returns[d][:, None]
        S = lam * S + (1.0 - lam) * (r @ r.T)
        out[d] = S
    return out


# ---------------------------------------------------------------------------
# Portfolio construction
# ---------------------------------------------------------------------------


def gmv_weights(cov: np.ndarray) -> np.ndarray:
    ones = np.ones(cov.shape[0])
    z = np.linalg.solve(cov, ones)
    return z / z.sum()


def gmv_weights_long_only(cov: np.ndarray) -> np.ndarray:
    from scipy.optimize import minimize

    n = cov.shape[0]
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1.0},)
    res = minimize(
        lambda w: w @ cov @ w,
        x0=np.full(n, 1.0 / n),
        jac=lambda w: 2.0 * cov @ w,
        bounds=[(0.0, 1.0)] * n,
        constraints=cons,
        method="SLSQP",
        options={"maxiter": 500, "ftol": 1e-14},
    )
    if not res.success:
        # Fail loud: a silent fallback here would quietly corrupt the robustness
        # branch (see .claude/rules/no-silent-fallback.md).
        raise RuntimeError(f"long-only GMV solver failed: {res.message}")
    w = np.clip(res.x, 0.0, None)
    return w / w.sum()


def drifted_weights(w: np.ndarray, block_returns: np.ndarray) -> np.ndarray:
    """Weights at the end of a holding block, after returns drift the portfolio."""
    gross = np.prod(1.0 + block_returns, axis=0)
    v = w * gross
    return v / v.sum()


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    name: str
    daily_returns: np.ndarray  # OOS daily portfolio returns
    daily_dates: pd.DatetimeIndex
    weights: np.ndarray  # (n_rebal, N) weights applied to each block
    turnover: np.ndarray  # (n_rebal,) one-way turnover at each rebalance
    block_returns: np.ndarray  # (n_rebal,) compounded block returns


def run_backtest(
    name: str,
    covs: np.ndarray,
    returns: np.ndarray,
    dates: pd.DatetimeIndex,
    day_index: np.ndarray,
    first_forecast_block: int,
    long_only: bool = False,
) -> BacktestResult:
    """Apply block-t covariance forecast to block-t returns.

    covs[t] must be a function of returns up to and including day
    day_index[t-1, 1]; the weights it produces are applied to days
    day_index[t, 0] .. day_index[t, 1]. This is the block-level shift(1).
    """
    n_blocks = covs.shape[0]
    weight_fn = gmv_weights_long_only if long_only else gmv_weights

    daily_rets: List[float] = []
    daily_idx: List[int] = []
    w_list: List[np.ndarray] = []
    turn_list: List[float] = []
    blk_list: List[float] = []

    prev_drift: np.ndarray | None = None
    for t in range(first_forecast_block, n_blocks):
        w = weight_fn(covs[t])
        lo, hi = day_index[t]
        blk = returns[lo : hi + 1]
        pr = blk @ w
        daily_rets.extend(pr.tolist())
        daily_idx.extend(range(lo, hi + 1))
        w_list.append(w)
        turn_list.append(
            float(np.abs(w - prev_drift).sum()) if prev_drift is not None else float("nan")
        )
        blk_list.append(float(np.prod(1.0 + pr) - 1.0))
        prev_drift = drifted_weights(w, blk)

    return BacktestResult(
        name=name,
        daily_returns=np.asarray(daily_rets),
        daily_dates=dates[np.asarray(daily_idx)],
        weights=np.asarray(w_list),
        turnover=np.asarray(turn_list),
        block_returns=np.asarray(blk_list),
    )


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def newey_west_lag(n: int, h: int = 1) -> int:
    """Repo canonical bandwidth: ceil(h^(1/3) * n^(1/3)).

    NOTE (.claude/rules/experiments.md hard rule): never use lag = h-1, which
    degenerates to zero HAC correction at h=1. Squared portfolio returns are
    strongly autocorrelated (volatility clustering), so this matters a lot here.
    """
    return max(1, min(int(math.ceil((h ** (1 / 3)) * (n ** (1 / 3)))), n // 4))


def _hac_omega(z: np.ndarray, lag: int) -> np.ndarray:
    """Newey-West long-run covariance of a demeaned multivariate series."""
    n = z.shape[0]
    omega = z.T @ z / n
    for l in range(1, lag + 1):
        w = 1.0 - l / (lag + 1.0)
        g = z[l:].T @ z[:-l] / n
        omega += w * (g + g.T)
    return omega


def variance_difference_test(
    a: np.ndarray, b: np.ndarray, lag: int | None = None
) -> Dict[str, float]:
    """Ledoit & Wolf (2011) style HAC test for equality of two portfolio variances.

    H0: Var(a) - Var(b) = 0, with the pair observed on the same dates.
    Delta method on the moment vector (E a, E b, E a^2, E b^2); the HAC estimator
    handles the volatility clustering in the squared-return components.

    Negative statistic => `a` has the LOWER variance.
    """
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if a.shape != b.shape:
        raise ValueError("paired series must have equal length")
    n = len(a)
    lag = newey_west_lag(n) if lag is None else lag

    m = np.array([a.mean(), b.mean(), (a**2).mean(), (b**2).mean()])
    var_a = m[2] - m[0] ** 2
    var_b = m[3] - m[1] ** 2
    delta = var_a - var_b
    grad = np.array([-2.0 * m[0], 2.0 * m[1], 1.0, -1.0])

    z = np.column_stack([a, b, a**2, b**2]) - m
    omega = _hac_omega(z, lag) if lag > 0 else z.T @ z / n
    se = math.sqrt(max(grad @ omega @ grad, 0.0) / n)
    if se <= 0:
        raise RuntimeError("degenerate standard error in variance_difference_test")

    t_stat = delta / se
    from scipy import stats as sps

    p = 2.0 * (1.0 - sps.norm.cdf(abs(t_stat)))
    return {
        "var_a": float(var_a),
        "var_b": float(var_b),
        "delta": float(delta),
        "se": float(se),
        "t_stat": float(t_stat),
        "p_value": float(p),
        "hac_lag": int(lag),
        "n_obs": int(n),
    }


def studentized_cbb_pvalue(
    a: np.ndarray, b: np.ndarray, reps: int, seed: int, block: int | None = None
) -> Dict[str, float]:
    """Studentized circular block bootstrap p-value for the variance difference.

    Ledoit & Wolf (2011) recommend this over the plain asymptotic test because the
    fourth-moment dependence in squared returns makes the delta-method standard
    error unreliable in finite samples.
    """
    n = len(a)
    lag = newey_west_lag(n)
    block = lag if block is None else block
    obs = variance_difference_test(a, b, lag=lag)
    t_obs = obs["t_stat"]
    delta_obs = obs["delta"]

    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    count = 0
    valid = 0
    for _ in range(reps):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        res = variance_difference_test(a[idx], b[idx], lag=lag)
        t_star = (res["delta"] - delta_obs) / res["se"]
        valid += 1
        if abs(t_star) >= abs(t_obs):
            count += 1
    return {
        "p_value_bootstrap": float((count + 1) / (valid + 1)),
        "reps": int(valid),
        "block_len": int(block),
        "seed": int(seed),
    }


def holm_bonferroni(pvals: Sequence[float]) -> List[float]:
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(running, 1.0)
    return adj.tolist()


def benjamini_hochberg(pvals: Sequence[float]) -> List[float]:
    m = len(pvals)
    order = np.argsort(pvals)[::-1]
    adj = np.empty(m)
    running = 1.0
    for rank, i in enumerate(order):
        j = m - rank
        running = min(running, m / j * pvals[i])
        adj[i] = min(running, 1.0)
    return adj.tolist()


def autocorr(x: np.ndarray, nlags: int) -> List[float]:
    x = np.asarray(x, float)
    x = x - x.mean()
    denom = float(x @ x)
    return [float(x[l:] @ x[:-l] / denom) for l in range(1, nlags + 1)]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def strategy_metrics(res: BacktestResult) -> Dict[str, float]:
    r = res.daily_returns
    w = res.weights
    turn = res.turnover[~np.isnan(res.turnover)]
    ann = math.sqrt(TRADING_DAYS_PER_YEAR)
    return {
        "ann_vol": float(r.std(ddof=1) * ann),
        "daily_var": float(r.var(ddof=1)),
        "ann_mean": float(r.mean() * TRADING_DAYS_PER_YEAR),
        "sharpe": float(r.mean() / r.std(ddof=1) * ann),
        "n_days": int(len(r)),
        "n_rebalances": int(len(w)),
        "turnover_mean_per_rebalance": float(turn.mean()),
        "turnover_median_per_rebalance": float(np.median(turn)),
        "turnover_annualized": float(
            turn.mean() * TRADING_DAYS_PER_YEAR / (len(r) / len(w))
        ),
        "hhi_mean": float((w**2).sum(axis=1).mean()),
        "gross_leverage_mean": float(np.abs(w).sum(axis=1).mean()),
        "max_abs_weight": float(np.abs(w).max()),
        "frac_rebal_with_short": float((w < 0).any(axis=1).mean()),
        "min_weight": float(w.min()),
    }


def net_of_cost_metrics(res: BacktestResult, bps: float) -> Dict[str, float]:
    """Descriptive only. Costs hit the MEAN; the headline claim is about variance."""
    c = bps / 10000.0
    turn = np.nan_to_num(res.turnover, nan=0.0)
    net_block = res.block_returns - c * turn
    n_per_year = TRADING_DAYS_PER_YEAR / (len(res.daily_returns) / len(res.weights))
    return {
        "cost_bps": bps,
        "net_ann_mean": float(net_block.mean() * n_per_year),
        "net_ann_vol": float(net_block.std(ddof=1) * math.sqrt(n_per_year)),
        "net_sharpe": float(
            net_block.mean() / net_block.std(ddof=1) * math.sqrt(n_per_year)
        ),
    }


# ---------------------------------------------------------------------------
# One full pipeline for a given block length / asset ordering / constraint
# ---------------------------------------------------------------------------


def build_all_covariances(
    returns: np.ndarray,
    day_index: np.ndarray,
    rcov: np.ndarray,
    first_forecast_block: int,
    chol_order: Sequence[int] | None = None,
    parameterisation: str = "chol",
) -> Tuple[Dict[str, np.ndarray], Dict[str, object]]:
    """Covariance forecast for every block t >= first_forecast_block, all methods.

    Every method reads data up to and including day day_index[t-1, 1] and no
    further. The returned diagnostics record that boundary for machine
    verification.
    """
    n_blocks, n_assets, _ = rcov.shape
    order = np.arange(n_assets) if chol_order is None else np.asarray(chol_order)
    inv = np.argsort(order)
    to_vec, from_vec = PARAMETERISATIONS[parameterisation]

    # --- HAR on the transformed elements (in the requested asset ordering) ---
    rcov_ord = rcov[:, order][:, :, order]
    vecs = np.empty((n_blocks, n_assets * (n_assets + 1) // 2))
    transform_failures = 0
    conds = np.empty(n_blocks)
    for b in range(n_blocks):
        conds[b] = float(np.linalg.cond(rcov_ord[b]))
        try:
            vecs[b] = to_vec(rcov_ord[b])
        except np.linalg.LinAlgError as exc:
            transform_failures += 1
            log.warning(
                "block %s: %s transform failed (%s); block RCov is singular",
                b,
                parameterisation,
                exc,
            )
            raise

    fcst_vec, n_train = har_forecast_path(vecs, first_forecast_block, HAR_LAGS)

    diag_idx = np.cumsum(np.arange(1, n_assets + 1)) - 1  # positions of the diagonal
    neg_diag = 0
    har_cov = np.full((n_blocks, n_assets, n_assets), np.nan)
    for t in range(first_forecast_block, n_blocks):
        v = fcst_vec[t]
        neg_diag += int((v[diag_idx] < 0).sum())
        S_ord = from_vec(v, n_assets)
        har_cov[t] = S_ord[inv][:, inv]  # un-permute back to canonical asset order

    # --- Benchmarks, all read off at the last day of block t-1 ---
    ewma_all = ewma_path(returns, EWMA_LAMBDA, BENCH_WINDOW_DAYS)
    sample_cov = np.full_like(har_cov, np.nan)
    lw_cov = np.full_like(har_cov, np.nan)
    ewma_cov = np.full_like(har_cov, np.nan)
    ew_cov = np.full_like(har_cov, np.nan)

    info_end_days: List[int] = []
    apply_start_days: List[int] = []
    for t in range(first_forecast_block, n_blocks):
        d_end = int(day_index[t - 1, 1])  # last day whose return is known
        info_end_days.append(d_end)
        apply_start_days.append(int(day_index[t, 0]))
        win = returns[d_end - BENCH_WINDOW_DAYS + 1 : d_end + 1]
        if len(win) != BENCH_WINDOW_DAYS:
            raise ValueError(f"block {t}: benchmark window is {len(win)} days")
        sample_cov[t] = sample_second_moment(win)
        lw_cov[t] = ledoit_wolf_cov(win)
        ewma_cov[t] = ewma_all[d_end]
        ew_cov[t] = np.eye(n_assets)  # yields w = 1/N exactly

    # --- Machine-checkable lookahead audit ---
    info_end = np.asarray(info_end_days)
    apply_start = np.asarray(apply_start_days)
    audit = {
        "rule": "every estimator uses daily returns through info_end_day; weights "
        "are applied starting at apply_start_day",
        "all_apply_start_after_info_end": bool((apply_start > info_end).all()),
        "min_gap_days": int((apply_start - info_end).min()),
        "max_gap_days": int((apply_start - info_end).max()),
        "har_last_training_target_block_offset": -1,
        "har_forecast_origin_block_offset": -1,
        "n_rebalances": int(len(info_end)),
        "parameterisation": parameterisation,
        "transform_failures": int(transform_failures),
        "forecast_negative_diagonal_count": int(neg_diag),
        "forecast_negative_diagonal_rate": float(
            neg_diag / max(1, len(info_end) * n_assets)
        ),
        "forecast_negative_diagonal_note": (
            "Cholesky: a negative L_ii still yields a PD matrix but signals the "
            "linear model extrapolating the variance channel through zero. "
            "Matrix-log: negative diagonals are the NORM (log of a small variance), "
            "so this count carries no diagnostic meaning under 'logm'."
        ),
        "block_rcov_condition_number": {
            "min": float(conds.min()),
            "median": float(np.median(conds)),
            "p95": float(np.percentile(conds, 95)),
            "max": float(conds.max()),
        },
        "har_first_train_rows": int(n_train[first_forecast_block]),
        "har_last_train_rows": int(n_train[-1]),
    }

    covs = {
        MODEL_NAME: har_cov,
        "sample": sample_cov,
        "ledoit_wolf": lw_cov,
        "ewma": ewma_cov,
        "equal_weight": ew_cov,
    }

    # Positive-definiteness check on every forecast actually used.
    pd_fail = {}
    for name, arr in covs.items():
        fails = 0
        for t in range(first_forecast_block, n_blocks):
            try:
                np.linalg.cholesky(arr[t])
            except np.linalg.LinAlgError:
                fails += 1
                log.warning("%s block %s: forecast covariance is not PD", name, t)
        pd_fail[name] = {
            "n_checked": int(n_blocks - first_forecast_block),
            "n_not_pd": int(fails),
            "rate": float(fails / max(1, n_blocks - first_forecast_block)),
        }
    audit["positive_definite_check"] = pd_fail

    return covs, audit


def run_pipeline(
    returns: np.ndarray,
    dates: pd.DatetimeIndex,
    block_len: int,
    long_only: bool = False,
    chol_order: Sequence[int] | None = None,
    parameterisation: str = "chol",
) -> Tuple[Dict[str, BacktestResult], Dict[str, object]]:
    rcov, day_index = build_block_rcov(returns, block_len)
    first_block = BURNIN_DAYS // block_len
    covs, audit = build_all_covariances(
        returns,
        day_index,
        rcov,
        first_block,
        chol_order=chol_order,
        parameterisation=parameterisation,
    )
    results = {
        name: run_backtest(
            name, arr, returns, dates, day_index, first_block, long_only=long_only
        )
        for name, arr in covs.items()
    }
    audit["block_len"] = block_len
    audit["first_forecast_block"] = int(first_block)
    audit["n_blocks_total"] = int(rcov.shape[0])
    audit["oos_start_date"] = str(dates[day_index[first_block, 0]].date())
    audit["oos_end_date"] = str(dates[day_index[-1, 1]].date())
    return results, audit


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def compare_family(
    results: Dict[str, BacktestResult], run_bootstrap: bool
) -> Dict[str, object]:
    """Test MODEL_NAME against every member of the pre-registered family."""
    model_r = results[MODEL_NAME].daily_returns
    tests: Dict[str, Dict] = {}
    raw_p: List[float] = []
    for bench in PRIMARY_FAMILY:
        bench_r = results[bench].daily_returns
        if len(bench_r) != len(model_r):
            raise ValueError(f"{bench}: OOS length mismatch")
        t = variance_difference_test(model_r, bench_r)
        t["lag_sensitivity"] = {
            str(l): {
                k: v
                for k, v in variance_difference_test(model_r, bench_r, lag=l).items()
                if k in ("t_stat", "p_value")
            }
            for l in HAC_LAG_GRID
        }
        d = model_r**2 - bench_r**2
        t["loss_differential_acf"] = autocorr(d, 10)
        try:
            from volpred.stats.model_evaluation import dm_test

            dm_t, dm_p = dm_test(model_r**2, bench_r**2, h=1)
            t["dm_test_on_squared_returns"] = {
                "t_stat": float(dm_t),
                "p_value": float(dm_p),
                "note": "canonical repo dm_test; tests SECOND MOMENT equality, "
                "not variance equality (means are not removed)",
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("canonical dm_test unavailable: %s", exc)
            t["dm_test_on_squared_returns"] = {"error": str(exc)}
        if run_bootstrap:
            t["bootstrap"] = studentized_cbb_pvalue(
                model_r, bench_r, BOOTSTRAP_REPS, SEED
            )
        tests[bench] = t
        raw_p.append(t["p_value"])

    holm = holm_bonferroni(raw_p)
    bh = benjamini_hochberg(raw_p)
    for i, bench in enumerate(PRIMARY_FAMILY):
        tests[bench]["p_holm"] = holm[i]
        tests[bench]["p_bh_fdr"] = bh[i]
        tests[bench]["survives_holm_at_005"] = bool(holm[i] < ALPHA)
        tests[bench]["meets_harvey_t3"] = bool(abs(tests[bench]["t_stat"]) > HARVEY_T)
    return {
        "family": list(PRIMARY_FAMILY),
        "family_size": len(PRIMARY_FAMILY),
        "correction": "Holm-Bonferroni (primary, FWER); Benjamini-Hochberg reported",
        "tests": tests,
    }


def adjudicate(results: Dict[str, BacktestResult], family: Dict[str, object]) -> Dict:
    """Apply the PRE-REGISTERED win/tie/lose rule. No post-hoc reinterpretation."""
    model_var = results[MODEL_NAME].daily_returns.var(ddof=1)
    lower_than_all = all(
        model_var < results[b].daily_returns.var(ddof=1) for b in PRIMARY_FAMILY
    )
    tests = family["tests"]  # type: ignore[index]
    wins_sig = [
        b
        for b in PRIMARY_FAMILY
        if tests[b]["survives_holm_at_005"] and tests[b]["t_stat"] < 0
    ]
    loses_sig = [
        b
        for b in PRIMARY_FAMILY
        if tests[b]["survives_holm_at_005"] and tests[b]["t_stat"] > 0
    ]

    if loses_sig:
        verdict = "LOSE"
    elif lower_than_all and "ledoit_wolf" in wins_sig:
        verdict = "WIN"
    elif wins_sig:
        verdict = "MIXED"
    else:
        verdict = "TIE_NULL"
    return {
        "verdict": verdict,
        "model_lower_point_estimate_than_all_three": bool(lower_than_all),
        "benchmarks_beaten_after_holm": wins_sig,
        "benchmarks_losing_to_after_holm": loses_sig,
        "rule": {
            "WIN": "point estimate lower than all three AND the Ledoit-Wolf "
            "comparison survives Holm at alpha=0.05",
            "MIXED": "some comparison survives Holm in the model's favour but the "
            "WIN condition is not met",
            "TIE_NULL": "no comparison survives Holm in either direction",
            "LOSE": "some benchmark has significantly lower variance after Holm",
        },
    }


def subperiod_table(results: Dict[str, BacktestResult]) -> Dict[str, Dict[str, float]]:
    periods = {
        "gfc_2007_12_to_2009_06": ("2007-12-01", "2009-06-30"),
        "post_gfc_2009_07_to_2019_12": ("2009-07-01", "2019-12-31"),
        "covid_and_after_2020_01_to_end": ("2020-01-01", "2100-01-01"),
    }
    out: Dict[str, Dict[str, float]] = {}
    ann = math.sqrt(TRADING_DAYS_PER_YEAR)
    for pname, (lo, hi) in periods.items():
        out[pname] = {}
        for sname, res in results.items():
            m = (res.daily_dates >= lo) & (res.daily_dates <= hi)
            if m.sum() < 60:
                log.warning("subperiod %s / %s: only %s days, skipped", pname, sname, m.sum())
                continue
            out[pname][sname] = float(res.daily_returns[m].std(ddof=1) * ann)
            out[pname]["_n_days"] = int(m.sum())
    return out


def permutation_sensitivity(
    returns: np.ndarray, dates: pd.DatetimeIndex, block_len: int
) -> Dict[str, object]:
    """Cholesky is not permutation invariant. Quantify how much that matters."""
    n = returns.shape[1]
    vols = []
    for order in itertools.permutations(range(n)):
        res, _ = run_pipeline(returns, dates, block_len, chol_order=order)
        vols.append(
            {
                "order": [ASSETS[i] for i in order],
                "ann_vol": float(
                    res[MODEL_NAME].daily_returns.std(ddof=1)
                    * math.sqrt(TRADING_DAYS_PER_YEAR)
                ),
            }
        )
    arr = np.array([v["ann_vol"] for v in vols])
    return {
        "n_orderings": len(vols),
        "ann_vol_min": float(arr.min()),
        "ann_vol_max": float(arr.max()),
        "ann_vol_mean": float(arr.mean()),
        "ann_vol_std": float(arr.std(ddof=1)),
        "ann_vol_spread": float(arr.max() - arr.min()),
        "canonical_order": list(ASSETS),
        "per_ordering": vols,
    }


def make_figures(results: Dict[str, BacktestResult], audit: Dict, outdir: Path) -> List[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    made = []
    order = [n for n in
             [MODEL_NAME, "har_rcov_logm", "ledoit_wolf", "ewma", "sample", "equal_weight"]
             if n in results]
    colors = {
        MODEL_NAME: "#c0392b",
        "har_rcov_logm": "#e67e22",
        "ledoit_wolf": "#2c6fbb",
        "ewma": "#27ae60",
        "sample": "#8e6bbf",
        "equal_weight": "#7f8c8d",
    }

    # Fig 1: rolling 63-day annualised vol
    fig, ax = plt.subplots(figsize=(11, 5))
    for name in order:
        r = pd.Series(results[name].daily_returns, index=results[name].daily_dates)
        ax.plot(
            r.index,
            r.rolling(63).std() * math.sqrt(TRADING_DAYS_PER_YEAR) * 100,
            label=name,
            color=colors[name],
            lw=1.1,
            alpha=0.9,
        )
    ax.set_title("OOS 63-day rolling annualised volatility of the GMV portfolio")
    ax.set_ylabel("annualised vol (%)")
    ax.legend(ncol=5, fontsize=8)
    ax.grid(alpha=0.25)
    p = outdir / "fig1_rolling_vol.png"
    fig.tight_layout()
    fig.savefig(p, dpi=140)
    plt.close(fig)
    made.append(p.name)

    # Fig 2: cumulative squared-return differential vs Ledoit-Wolf
    fig, ax = plt.subplots(figsize=(11, 4.2))
    d = results[MODEL_NAME].daily_returns ** 2 - results["ledoit_wolf"].daily_returns ** 2
    ax.plot(results[MODEL_NAME].daily_dates, np.cumsum(d) * 1e4, color="#c0392b", lw=1.2)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title(
        "Cumulative squared-return differential: HAR-RCov minus Ledoit-Wolf\n"
        "(below zero = HAR-RCov accumulating lower realised variance)"
    )
    ax.set_ylabel("cumulative $r^2$ difference (bp)")
    ax.grid(alpha=0.25)
    p = outdir / "fig2_cumulative_variance_differential.png"
    fig.tight_layout()
    fig.savefig(p, dpi=140)
    plt.close(fig)
    made.append(p.name)

    # Fig 3: turnover and concentration
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    names = [n for n in order if n != "equal_weight"]
    axes[0].bar(
        range(len(names)),
        [np.nanmean(results[n].turnover) for n in names],
        color=[colors[n] for n in names],
    )
    axes[0].set_xticks(range(len(names)))
    axes[0].set_xticklabels(names, rotation=20, ha="right", fontsize=8)
    axes[0].set_title("Mean one-way turnover per rebalance")
    axes[0].grid(alpha=0.25, axis="y")
    for n in names:
        axes[1].plot(
            results[n].weights.sum(axis=1) * 0 + np.abs(results[n].weights).sum(axis=1),
            label=n,
            color=colors[n],
            lw=0.8,
            alpha=0.85,
        )
    axes[1].set_title("Gross leverage $\\sum_i |w_i|$ per rebalance")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.25)
    p = outdir / "fig3_turnover_leverage.png"
    fig.tight_layout()
    fig.savefig(p, dpi=140)
    plt.close(fig)
    made.append(p.name)

    # Fig 4: conditioning of the block RCov proxy
    fig, ax = plt.subplots(figsize=(7, 4.2))
    c = audit["block_rcov_condition_number"]
    ax.bar(
        range(4),
        [c["min"], c["median"], c["p95"], c["max"]],
        color="#34495e",
    )
    ax.set_yscale("log")
    ax.set_xticks(range(4))
    ax.set_xticklabels(["min", "median", "p95", "max"])
    ax.set_title("Condition number of the block realised-covariance proxy")
    ax.grid(alpha=0.25, axis="y")
    p = outdir / "fig4_rcov_conditioning.png"
    fig.tight_layout()
    fig.savefig(p, dpi=140)
    plt.close(fig)
    made.append(p.name)
    return made


def main() -> None:
    px = load_prices()
    dates = pd.DatetimeIndex(px.index)
    returns = px.pct_change().dropna().to_numpy(float)
    dates = dates[1:]
    log.info("sample: %s rows %s -> %s", len(returns), dates[0].date(), dates[-1].date())

    out: Dict[str, object] = {
        "experiment_id": "K1714",
        "title": "Realized-covariance HAR vs shrinkage/EWMA for out-of-sample GMV portfolios",
        "run_utc": pd.Timestamp.utcnow().isoformat(),
        "config": {
            "assets": list(ASSETS),
            "cholesky_order": list(ASSETS),
            "sample_start": str(dates[0].date()),
            "sample_end": str(dates[-1].date()),
            "n_daily_returns": int(len(returns)),
            "block_lens": list(BLOCK_LENS),
            "headline_block_len": HEADLINE_BLOCK_LEN,
            "har_lags_in_blocks": list(HAR_LAGS),
            "burnin_days": BURNIN_DAYS,
            "benchmark_window_days": BENCH_WINDOW_DAYS,
            "ewma_lambda": EWMA_LAMBDA,
            "seed": SEED,
            "alpha": ALPHA,
            "harvey_t_threshold": HARVEY_T,
            "primary_family": list(PRIMARY_FAMILY),
            "reference_strategies": list(REFERENCE_STRATEGIES),
            "bootstrap_reps": BOOTSTRAP_REPS,
            "return_type": "simple (arithmetic) returns throughout, so that "
            "w'r is the exact portfolio return and Cov(r) is the exact GMV input",
            "demeaning": "none — block RCov and the sample/LW benchmarks all use the "
            "non-demeaned second moment, which makes the benchmark exactly nested "
            "in the HAR information set",
        },
        "data_provenance": {
            "source": "yfinance adjusted close (auto_adjust=True)",
            "cache_file": "data/prices_raw.csv",
            "cache_sha256": file_sha256(HERE / "data" / "prices_raw.csv"),
        },
    }

    by_block: Dict[str, object] = {}
    headline_results = None
    headline_audit = None

    for bl in BLOCK_LENS:
        log.info("=== block length %s ===", bl)
        results, audit = run_pipeline(returns, dates, bl)
        is_headline = bl == HEADLINE_BLOCK_LEN
        family = compare_family(results, run_bootstrap=is_headline)
        verdict = adjudicate(results, family)
        entry: Dict[str, object] = {
            "audit": audit,
            "metrics": {n: strategy_metrics(r) for n, r in results.items()},
            "inference": family,
            "adjudication": verdict,
            "subperiods_ann_vol": subperiod_table(results),
            "cost_sensitivity_descriptive": {
                n: [net_of_cost_metrics(r, b) for b in COST_BPS_GRID]
                for n, r in results.items()
            },
        }
        if is_headline:
            headline_results, headline_audit = dict(results), audit
            log.info("long-only robustness ...")
            lo_results, lo_audit = run_pipeline(returns, dates, bl, long_only=True)
            lo_family = compare_family(lo_results, run_bootstrap=False)
            entry["long_only_robustness"] = {
                "audit_gap_check": lo_audit["all_apply_start_after_info_end"],
                "metrics": {n: strategy_metrics(r) for n, r in lo_results.items()},
                "inference": lo_family,
                "adjudication": adjudicate(lo_results, lo_family),
            }
            log.info("permutation sensitivity (24 orderings) ...")
            entry["cholesky_permutation_sensitivity"] = permutation_sensitivity(
                returns, dates, bl
            )

            # SECONDARY SPECIFICATION — added AFTER the primary result was seen.
            # Motivation: the primary spec loses, and a reviewer is entitled to
            # ask whether that is an artifact of the (order-dependent) Cholesky
            # map rather than of the HAR-on-realized-covariance idea itself. The
            # matrix logarithm is permutation equivariant, so it isolates that.
            # Because this is post-hoc, any claim in the model's FAVOUR would
            # need the widened 6-comparison correction reported below; a claim
            # AGAINST the model does not benefit from the extra look.
            log.info("secondary parameterisation: matrix log ...")
            lm_results, lm_audit = run_pipeline(
                returns, dates, bl, parameterisation="logm"
            )
            lm_family = compare_family(lm_results, run_bootstrap=False)
            combined_p = [
                family["tests"][b]["p_value"] for b in PRIMARY_FAMILY  # type: ignore[index]
            ] + [lm_family["tests"][b]["p_value"] for b in PRIMARY_FAMILY]  # type: ignore[index]
            combined_holm = holm_bonferroni(combined_p)
            entry["matrix_log_parameterisation_secondary"] = {
                "status": "POST-HOC — declared after the primary result was known",
                "audit": lm_audit,
                "metrics": {n: strategy_metrics(r) for n, r in lm_results.items()},
                "inference": lm_family,
                "adjudication": adjudicate(lm_results, lm_family),
                "widened_correction_over_both_specs": {
                    "n_comparisons": len(combined_p),
                    "labels": [f"chol_vs_{b}" for b in PRIMARY_FAMILY]
                    + [f"logm_vs_{b}" for b in PRIMARY_FAMILY],
                    "raw_p": combined_p,
                    "holm_adjusted": combined_holm,
                },
            }
            headline_results["har_rcov_logm"] = lm_results[MODEL_NAME]
        by_block[f"block_{bl}d"] = entry

    out["results_by_block_length"] = by_block

    assert headline_results is not None and headline_audit is not None
    out["figures"] = make_figures(headline_results, headline_audit, HERE / "figures")

    head = by_block[f"block_{HEADLINE_BLOCK_LEN}d"]
    other = by_block[f"block_{[b for b in BLOCK_LENS if b != HEADLINE_BLOCK_LEN][0]}d"]
    sec = head["matrix_log_parameterisation_secondary"]  # type: ignore[index]
    out["headline"] = {
        "block_len": HEADLINE_BLOCK_LEN,
        "verdict": head["adjudication"]["verdict"],  # type: ignore[index]
        "robustness_block_len_verdict": other["adjudication"]["verdict"],  # type: ignore[index]
        "verdicts_agree_across_block_lengths": (
            head["adjudication"]["verdict"] == other["adjudication"]["verdict"]  # type: ignore[index]
        ),
        "long_only_verdict": head["long_only_robustness"]["adjudication"]["verdict"],  # type: ignore[index]
        "matrix_log_spec_verdict": sec["adjudication"]["verdict"],
        "model_beats_no_benchmark_in_any_specification": all(
            not v
            for v in [
                head["adjudication"]["benchmarks_beaten_after_holm"],  # type: ignore[index]
                other["adjudication"]["benchmarks_beaten_after_holm"],  # type: ignore[index]
                head["long_only_robustness"]["adjudication"][  # type: ignore[index]
                    "benchmarks_beaten_after_holm"
                ],
                sec["adjudication"]["benchmarks_beaten_after_holm"],
            ]
        ),
        "ann_vol": {
            n: head["metrics"][n]["ann_vol"] for n in head["metrics"]  # type: ignore[index]
        },
        "ann_vol_matrix_log_spec": sec["metrics"][MODEL_NAME]["ann_vol"],
    }

    # results + reproduce_spec written together at run time — code_trace and
    # spec.entrypoint take their identity from one trace_file call (K1708 rule:
    # a spec must be born in the run that produced the results, never back-filled)
    from volpred.research.reproduce_spec import finalize_experiment

    path, _ = finalize_experiment(
        results=out,
        entrypoint=__file__,
        canonical_result="K1714_results.json",
        exp_dir=HERE,
        inputs=[HERE / "data" / "prices_raw.csv"],
        outputs=["K1714_results.json"],
        seeds=[("numpy", SEED)],
    )
    log.info("wrote %s", path)

    print("\n" + "=" * 78)
    print(f"HEADLINE VERDICT (block={HEADLINE_BLOCK_LEN}d): {out['headline']['verdict']}")
    print(f"robustness (block=10d):  {out['headline']['robustness_block_len_verdict']}")
    print("-" * 78)
    for n, v in out["headline"]["ann_vol"].items():  # type: ignore[index]
        print(f"  {n:16s} ann vol = {v*100:6.3f}%")
    print("-" * 78)
    for b in PRIMARY_FAMILY:
        t = head["inference"]["tests"][b]  # type: ignore[index]
        print(
            f"  HAR vs {b:12s} t={t['t_stat']:+7.3f}  p={t['p_value']:.4f}  "
            f"p_holm={t['p_holm']:.4f}  boot_p={t.get('bootstrap',{}).get('p_value_bootstrap','-')}"
        )
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
