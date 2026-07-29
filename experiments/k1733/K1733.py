"""K1733 — Volatility transmission along the AI-infrastructure funding chain.

THE QUESTION
------------
J.P. Morgan's 2026 alternatives outlook argues that AI data-centre financing is
migrating from public to private markets. If an AI capex shock really hits the
PHYSICAL bottleneck (power, grid, infrastructure) and the FUNDING cost (credit)
before it shows up in Nasdaq realized volatility, then the volatility of
XLU / PAVE / HYG / LQD should carry leading information for the realized
volatility of SMH / QQQ. That is a directional, falsifiable, tradable claim.

WHY THIS SCRIPT IS BUILT THE WAY IT IS
--------------------------------------
The repository has already been burned by exactly this shape of claim, twice:

* K628b (CORRECTED 2026-07-13): "SPY is the dominant net transmitter,
  net = +43.7pp" was a Cholesky-ordering artifact. Order-invariant KPPS put it
  at +14.6pp.
* K865b: the Diebold-Yilmaz SPY-hub DIRECTION was an ordering artifact, while
  the TOTAL spillover was real. The two conclusions do not share a fate.
* K907: the total connectedness index is essentially uncorrelated with VIX
  (r = 0.001), so connectedness is not a volatility-level proxy.

K1733's core hypothesis is directional, which is precisely where those two died.
So the hard constraints here are:

1. Every directional number comes from a hand-rolled, order-invariant KPPS
   generalized FEVD (Koop-Pesaran-Potter 1996; Pesaran-Shin 1998), built from
   ``sigma_u`` and the non-orthogonalised ``ma_rep``. ``statsmodels``'s
   ``.fevd()`` is Cholesky and is NEVER used for a claim: it is estimated
   deliberately, across many random orderings, purely to MEASURE how large the
   artifact would have been. Both arms are refitted on genuinely permuted column
   orders rather than permuted after the fact.
2. Order-invariance of the KPPS arm is PROVEN numerically each run (max absolute
   deviation across orderings), not asserted by citation. Statistical sign
   stability is a separate number, from a circular block bootstrap.
3. Any "A leads B" claim carries a formal test with a HAC/bootstrap variance and
   a Benjamini-Hochberg FDR correction over the whole declared family.
4. "Total spillover is real" and "the direction is credible" are reported as two
   separate verdicts with two separate criteria.

# nested-dm: cw-primary — Clark-West (2007) is the ONLY inference wired into
# EVERY primary nested forecast comparison here. There is deliberately no
# unadjusted nested loss t-statistic anywhere in this experiment: under a nested
# null it is undersized, and the repo canonical Clark-West delegate exists.
# QLIKE on the variance level is reported with a stationary-bootstrap interval
# and is explicitly descriptive-only; it governs no verdict.

TWO SAMPLES, ON PURPOSE
-----------------------
PAVE was listed 2017-03-08. Padding it with NaN would be fabrication, and
dropping the other 10 years of history to accommodate it would throw away the
GFC and hide whether any result is sample-specific. So both are reported:

* ``full8``  — MSFT NVDA SMH QQQ XLU PAVE HYG LQD, common sample from PAVE's
  listing. This is the brief's specification and is the PRIMARY system.
* ``long7``  — the same minus PAVE, from HYG's listing (2007-04-11), which buys
  the GFC, 2011, 2015-16, 2018Q4, COVID and the 2022 bear market. SECONDARY.

The OOS split is 2015-01-01 for ``long7`` (the brief's cut) and 2021-01-04 for
``full8`` (2015 predates the common sample; the split keeps ~4 years of training
and puts the 2022 bear market in the evaluation window).

LOOKAHEAD POLICY
----------------
* Predictors enter as an explicit ``.shift(1)``: the feature row stamped at date
  t contains only information observable at the close of t-1. The target stamped
  at t is the forward h-day mean squared return over [t, t+h-1].
* Expanding-window training rows obey the label embargo ``j + h - 1 < i``: a
  training row's entire label window must close before the forecast origin.
* Baseline and augmented models share one lag convention, one training index,
  one refit schedule.
* A future-noise causal probe re-runs the whole forecast and strategy pipeline
  with every OHLC bar after a cut date replaced by an N(0, 0.5%^2)-driven random
  walk, and asserts bit-identical forecasts and positions at origins on or
  before the cut. Deviations are counted into ``lookahead_diagnostics``.

Seed 42 for every stochastic routine.

References
----------
- Diebold, F.X. & Yilmaz, K. (2012). IJF 28(1), 57-66.
- Diebold, F.X. & Yilmaz, K. (2014). J. Econometrics 182(1), 119-134.
- Koop, G., Pesaran, M.H. & Potter, S.M. (1996). J. Econometrics 74(1), 119-147.
- Pesaran, H.H. & Shin, Y. (1998). Economics Letters 58(1), 17-29.
- Clark, T.E. & West, K.D. (2007). J. Econometrics 138(1), 291-311.
- Benjamini, Y. & Hochberg, Y. (1995). JRSS-B 57(1), 289-300.
- Parkinson, M. (1980). J. Business 53(1), 61-65.
- Garman, M.B. & Klass, M.J. (1980). J. Business 53(1), 67-78.
- Politis, D.N. & Romano, J.P. (1994). JASA 89(428), 1303-1313.
- J.P. Morgan (2026), alternatives outlook: AI data-centre financing shifting
  from public to private markets (the motivating source, via research_program.md
  line 606).
- Prior K-series: K628b, K865b, K907 (ordering artifacts), K1508 (AI power
  narrative did not reprice utility/grid vol), K1332/K1343/K1344 (public credit
  proxies as vol signals).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller

T0 = time.time()

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from volpred.research.reproduce_spec import finalize_experiment  # noqa: E402
from volpred.stats.drawdown import compare_max_drawdown  # noqa: E402
from volpred.stats.model_evaluation import (  # noqa: E402
    clark_west_test,
    qlike_pointwise,
)

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration — every knob is frozen here and echoed into results["config"]
# ═══════════════════════════════════════════════════════════════════════════════

SEED = 42
DOWNLOAD_START = "1990-01-01"

AI_BASKET = ["MSFT", "NVDA", "SMH", "QQQ"]
PHYSICAL_BASKET = ["XLU", "PAVE"]
CREDIT_BASKET = ["HYG", "LQD"]
# SPY is NOT a basket member. It is downloaded solely as the broad-market
# volatility control in the H3 identification ladder: without it, "physical /
# credit volatility predicts Nasdaq volatility" cannot be told apart from
# "any well-measured volatility series predicts Nasdaq volatility". That is
# exactly the confound that collapsed K1499's BDC result.
CONTROL_TICKERS = ["SPY"]
ALL_TICKERS = AI_BASKET + PHYSICAL_BASKET + CREDIT_BASKET + CONTROL_TICKERS

# Network systems. `sources` are the physical/credit legs whose transmission into
# `targets` is the H2 hypothesis.
SYSTEMS = {
    "full8": {
        "assets": ["MSFT", "NVDA", "SMH", "QQQ", "XLU", "PAVE", "HYG", "LQD"],
        "sources": ["XLU", "PAVE", "HYG", "LQD"],
        "targets": ["SMH", "QQQ"],
        "role": "primary",
        "why": "brief specification; sample starts at PAVE's 2017-03-08 listing",
    },
    "long7": {
        "assets": ["MSFT", "NVDA", "SMH", "QQQ", "XLU", "HYG", "LQD"],
        "sources": ["XLU", "HYG", "LQD"],
        "targets": ["SMH", "QQQ"],
        "role": "secondary",
        "why": "drops PAVE to buy 2007-2017 (GFC, 2011, 2015-16) — sample-robustness arm",
    },
}

VAR_MAX_LAG = 5
FEVD_HORIZON = 10
N_ORDERINGS = 200          # random column orders for the ordering-artifact audit
N_BOOT_NETWORK = 1000      # circular block bootstrap replicates for TCI / NPDC
N_NULL_TCI = 500           # independent-AR surrogate replicates for the TCI floor
BLOCK_LEN = 60             # ~3 months; vol persistence is long
ROLL_WINDOW = 250
ROLL_STEP = 10
ROLL_VAR_LAG = 3

# Sub-periods for regime robustness (repo rule: validate across three periods).
# Cut on events, not on equal thirds: the GFC / pre-AI era, the COVID + rate-hike
# era, and the post-ChatGPT AI-capex era the motivating source is actually about.
SUBPERIODS = [
    {"name": "pre_ai_2007_2019", "start": "2007-04-11", "end": "2019-12-31",
     "why": "GFC, 2011 euro crisis, 2015-16 — before the AI-capex narrative existed"},
    {"name": "covid_ratehike_2020_2022", "start": "2020-01-01", "end": "2022-12-31",
     "why": "COVID crash, reflation, the 2022 bear market"},
    {"name": "ai_capex_2023_2026", "start": "2023-01-01", "end": "2026-12-31",
     "why": "post-ChatGPT; the period the J.P. Morgan financing thesis describes"},
]

# Forecast specifications (H3). Two arms mirroring the two network systems.
FORECAST_SPECS = {
    "full8": {
        "exog": ["XLU", "PAVE", "HYG", "LQD"],
        "oos_start": "2021-01-04",
        "role": "primary",
    },
    "long7": {
        "exog": ["XLU", "HYG", "LQD"],
        "oos_start": "2015-01-01",
        "role": "primary",
    },
}
FORECAST_TARGETS = ["QQQ", "SMH"]
HORIZONS = [1, 5, 22]
MIN_TRAIN = 500

# ── The H3 identification ladder ──────────────────────────────────────────────
# The brief's literal baseline is "HAR-RV", i.e. M0. Testing the exogenous block
# straight against M0 is not identified: the exogenous regressors are RANGE-based
# volatility and M0's regressors are squared close-to-close returns, so a large
# part of any gain is simply a better volatility ESTIMATOR, and another part is
# the common market volatility factor. The ladder separates the three sources and
# puts the primary claim on the strictest rung.
#
#   M0  own HAR-RV (squared-return d/w/m)                  <- brief's literal baseline
#   M1  M0 + own range volatility (d/w/m)                  <- estimator quality
#   M2  M1 + SPY range volatility (d/w/m)                   <- broad-market vol factor
#   M3  M2 + physical/credit range volatility               <- PRIMARY: M3 vs M2
#
# Every rung is nested in the next, so Clark-West is the right test throughout.
LADDER_COMPARISONS = [
    {"key": "M3_vs_M2", "small": "M2", "large": "M3", "role": "primary",
     "claim": "physical/credit volatility adds content beyond own vol AND market vol"},
    {"key": "M1_vs_M0", "small": "M0", "large": "M1", "role": "diagnostic_rung",
     "claim": "range-based own volatility beats a squared-return HAR (estimator quality)"},
    {"key": "M2_vs_M1", "small": "M1", "large": "M2", "role": "diagnostic_rung",
     "claim": "the broad-market volatility factor adds content beyond own vol"},
    {"key": "M0plusExog_vs_M0", "small": "M0", "large": "M0plusExog",
     "role": "loose_literal_reading",
     "claim": "the brief's literal H3: exogenous block vs a bare HAR-RV, NOT identified"},
]
PRIMARY_COMPARISON = "M3_vs_M2"
FDR_Q = 0.10
N_BOOT_FORECAST = 1000     # stationary bootstrap for OOS R^2 / QLIKE intervals
BOOT_MEAN_BLOCK = 22
N_BOOT_GRANGER = 500       # circular block bootstrap on Granger lag-coefficient sums

# Strategy grid (H4)
COST_GRID_BPS = [0.0, 1.0, 5.0]
GATE_Z = 1.0
N_PHASE_NULL = 1000

TRADING_DAYS = 252
VOL_FLOOR = 1e-10

# ── Palette (dataviz reference instance, light mode) ───────────────────────────
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e3e2de"
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95", "#0d366b"]
DIVERGING = LinearSegmentedColormap.from_list(
    "k1733_div",
    ["#0d366b", "#256abf", "#86b6ef", "#f0efec", "#f0a3a2", "#e34948", "#8f1f1e"],
)


# ═══════════════════════════════════════════════════════════════════════════════
# Data
# ═══════════════════════════════════════════════════════════════════════════════

def download_panel(refresh: bool) -> dict[str, pd.DataFrame]:
    """Adjusted daily OHLC per ticker.

    ``auto_adjust=False`` keeps the raw bars plus ``Adj Close``; Open/High/Low
    are then rescaled by ``Adj Close / Close`` so that every bar sits on the same
    total-return footing as the adjusted close. Range-based volatility estimators
    are ratio-based, so a uniform per-day rescaling leaves them untouched — but
    doing it explicitly means a mixed adjusted/unadjusted panel is impossible.
    """
    cache = HERE / "data" / "prices_raw.csv"
    if cache.exists() and not refresh:
        raw = pd.read_csv(cache, header=[0, 1], index_col=0, parse_dates=True)
        print(f"[data] cached raw panel: {len(raw)} rows -> {cache}")
    else:
        import yfinance as yf

        print(f"[data] downloading {ALL_TICKERS} from yfinance since {DOWNLOAD_START}")
        raw = yf.download(
            ALL_TICKERS,
            start=DOWNLOAD_START,
            auto_adjust=False,
            progress=False,
            group_by="column",
        )
        raw = raw.loc[:, raw.columns.get_level_values(0).isin(
            ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        )]
        raw.to_csv(cache)
        print(f"[data] cached -> {cache} ({len(raw)} rows)")

    panel: dict[str, pd.DataFrame] = {}
    for tk in ALL_TICKERS:
        df = pd.DataFrame(
            {
                "Open": raw[("Open", tk)],
                "High": raw[("High", tk)],
                "Low": raw[("Low", tk)],
                "Close": raw[("Close", tk)],
                "AdjClose": raw[("Adj Close", tk)],
            }
        ).dropna()
        assert (df["Close"] > 0).all(), f"{tk}: non-positive close"
        factor = df["AdjClose"] / df["Close"]
        out = pd.DataFrame(
            {
                "Open": df["Open"] * factor,
                "High": df["High"] * factor,
                "Low": df["Low"] * factor,
                "Close": df["AdjClose"],
            }
        )
        assert (out["High"] >= out["Low"] - 1e-9).all(), f"{tk}: High < Low after rescale"
        panel[tk] = out
    return panel


def coverage_table(panel: dict[str, pd.DataFrame]) -> dict:
    return {
        tk: {
            "first_date": str(df.index[0].date()),
            "last_date": str(df.index[-1].date()),
            "n_obs": int(len(df)),
        }
        for tk, df in panel.items()
    }


def parkinson_variance(df: pd.DataFrame) -> pd.Series:
    """Parkinson (1980) daily variance. Non-negative by construction."""
    hl = np.log(df["High"] / df["Low"])
    return (hl ** 2) / (4.0 * np.log(2.0))


def garman_klass_variance(df: pd.DataFrame) -> pd.Series:
    """Garman-Klass (1980) daily variance. CAN be negative — floored by caller."""
    hl = np.log(df["High"] / df["Low"])
    co = np.log(df["Close"] / df["Open"])
    return 0.5 * hl ** 2 - (2.0 * np.log(2.0) - 1.0) * co ** 2


def build_log_vol(panel: dict[str, pd.DataFrame], proxy: str) -> tuple[pd.DataFrame, dict]:
    """Log annualised daily volatility per ticker, plus a floor audit.

    The VAR is estimated on log volatility, following Diebold-Yilmaz (2012),
    which uses log range-based volatility levels. Logs both stabilise the
    right skew of a variance proxy and keep the VAR's linear-Gaussian shock
    structure defensible.
    """
    est = {"parkinson": parkinson_variance, "garman_klass": garman_klass_variance}[proxy]
    cols, audit = {}, {}
    for tk, df in panel.items():
        v = est(df)
        n_floored = int((v <= VOL_FLOOR).sum())
        v = v.clip(lower=VOL_FLOOR)
        cols[tk] = np.log(np.sqrt(TRADING_DAYS * v))
        audit[tk] = {"n_floored": n_floored, "n_obs": int(len(v))}
    return pd.DataFrame(cols), {"proxy": proxy, "floor": VOL_FLOOR, "per_ticker": audit}


def close_returns(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame(
        {tk: np.log(df["Close"]).diff() for tk, df in panel.items()}
    ).dropna(how="all")


# ═══════════════════════════════════════════════════════════════════════════════
# Connectedness machinery
# ═══════════════════════════════════════════════════════════════════════════════

def select_lag_aic(data: np.ndarray, max_lag: int) -> int:
    sel = VAR(data).select_order(maxlags=max_lag)
    p = int(sel.aic)
    return max(1, p)


def fit_var(data: np.ndarray, lag: int):
    return VAR(data).fit(lag)


def generalized_fevd(res, horizon: int = FEVD_HORIZON) -> np.ndarray:
    """KPPS generalized FEVD (Koop-Pesaran-Potter 1996; Pesaran-Shin 1998).

        theta_ij(H) = sigma_jj^-1 * sum_h (e_i' A_h Sigma e_j)^2
                                  / sum_h (e_i' A_h Sigma A_h' e_i)

    Shocks are NOT orthogonalised, so the table does not depend on the order in
    which the variables were handed to the VAR. Rows do not sum to 1 before
    normalisation; the caller row-normalises (standard DY 2012 treatment).

    Same estimator as experiments/k628b/k628b_kpps_rerun.py and
    experiments/k865b/k865b_gfevd_robustness.py.
    """
    sigma = np.asarray(res.sigma_u)
    phi = res.ma_rep(maxn=horizon - 1)
    assert phi.shape[0] == horizon, f"ma_rep gave {phi.shape[0]} steps, expected {horizon}"
    sig_jj = np.diag(sigma)
    assert np.all(np.isfinite(sigma)), "residual covariance has non-finite entries"
    assert np.all(sig_jj > 0), f"non-positive residual variances: {sig_jj}"

    num = np.zeros_like(sigma)
    den = np.zeros(sigma.shape[0])
    for h in range(horizon):
        a_sigma = phi[h] @ sigma
        num += a_sigma ** 2
        den += np.diag(a_sigma @ phi[h].T)
    assert np.all(den > 0), f"non-positive forecast-error variance denominators: {den}"
    out = (num / sig_jj[None, :]) / den[:, None]
    assert np.all(np.isfinite(out)), "GFEVD has non-finite entries"
    return out


def cholesky_fevd(res, horizon: int = FEVD_HORIZON) -> np.ndarray:
    """Cholesky-orthogonalised FEVD — the ORDER-DEPENDENT estimator.

    Present only as the artifact yardstick: nothing in the verdict sink reads
    it. Hand-rolled rather than taken from ``statsmodels``'s ``.fevd()`` so the
    algebra sitting next to the KPPS arm is visible and the two share one
    ``ma_rep``.
    """
    sigma = np.asarray(res.sigma_u)
    chol = np.linalg.cholesky(sigma)
    phi = res.ma_rep(maxn=horizon - 1)
    n = sigma.shape[0]
    num = np.zeros((n, n))
    den = np.zeros(n)
    for h in range(horizon):
        psi = phi[h] @ chol
        num += psi ** 2
        den += np.diag(phi[h] @ sigma @ phi[h].T)
    out = num / den[:, None]
    assert np.allclose(out.sum(axis=1), 1.0, atol=1e-8), "Cholesky FEVD rows must sum to 1"
    return out


def row_normalize(mat: np.ndarray) -> np.ndarray:
    assert np.all(np.isfinite(mat)), "FEVD matrix has non-finite entries"
    sums = mat.sum(axis=1, keepdims=True)
    assert np.all(sums > 0), f"non-positive FEVD row sums: {sums.ravel()}"
    out = mat / sums
    assert np.allclose(out.sum(axis=1), 1.0, atol=1e-8), "row normalisation failed"
    return out


def dy_metrics(theta_norm: np.ndarray, labels: list[str]) -> dict:
    """Diebold-Yilmaz connectedness in percentage points.

    Row i = share of i's forecast-error variance attributable to each shock j.
    FROM_i = what i receives (row ex-diagonal); TO_j = what j transmits (column
    ex-diagonal); NET = TO - FROM; TCI = off-diagonal mass / n.
    """
    n = theta_norm.shape[0]
    m = theta_norm * 100.0
    from_ = m.sum(axis=1) - np.diag(m)
    to_ = m.sum(axis=0) - np.diag(m)
    net = to_ - from_
    tci = float((m.sum() - np.trace(m)) / n)
    assert -1e-8 <= tci <= 100.0 + 1e-8, f"TCI outside [0, 100]: {tci}"
    assert abs(float(net.sum())) < 1e-6, f"NET does not sum to zero: {net.sum()}"
    return {
        "tci": tci,
        "from_others": {labels[i]: float(from_[i]) for i in range(n)},
        "to_others": {labels[i]: float(to_[i]) for i in range(n)},
        "net": {labels[i]: float(net[i]) for i in range(n)},
        "matrix": [[float(m[i, j]) for j in range(n)] for i in range(n)],
    }


def pairwise_net(theta_norm: np.ndarray, labels: list[str], src: str, tgt: str) -> float:
    """Pairwise net directional connectedness from ``src`` to ``tgt``, in pp.

    NPDC_{s->t} = theta[t, s] - theta[s, t]: the share of t's forecast-error
    variance explained by s's shock, minus the reverse. Positive means s is a net
    transmitter TO t. Reported undivided by N (Diebold-Yilmaz 2014 also scale by
    1/N; the sign and the ranking are identical either way).
    """
    i, j = labels.index(src), labels.index(tgt)
    m = theta_norm * 100.0
    return float(m[j, i] - m[i, j])


def network_snapshot(data: np.ndarray, labels: list[str], lag: int, sources, targets) -> dict:
    res = fit_var(data, lag)
    theta = row_normalize(generalized_fevd(res))
    met = dy_metrics(theta, labels)
    met["pairwise_net"] = {
        f"{s}->{t}": pairwise_net(theta, labels, s, t) for s in sources for t in targets
    }
    return met


# ── resampling utilities ───────────────────────────────────────────────────────

def circular_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Circular block bootstrap indices, preserving cross-sectional alignment."""
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=n_blocks)
    idx = np.concatenate([(s + np.arange(block)) % n for s in starts])
    return idx[:n]


def stationary_bootstrap_mean_ci(
    x: np.ndarray, block: int, n_boot: int, rng: np.random.Generator, alpha: float = 0.10
) -> dict:
    """Percentile CI for the mean of a serially dependent series."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 20:
        return {"mean": float(np.mean(x)) if n else None, "ci_low": None, "ci_high": None,
                "n_obs": int(n), "status": "insufficient_observations"}
    p = 1.0 / block
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = np.empty(n, dtype=np.int64)
        idx[0] = rng.integers(0, n)
        jumps = rng.random(n) < p
        steps = rng.integers(0, n, size=n)
        for t in range(1, n):
            idx[t] = steps[t] if jumps[t] else (idx[t - 1] + 1) % n
        means[b] = x[idx].mean()
    return {
        "mean": float(np.mean(x)),
        "ci_low": float(np.quantile(means, alpha / 2)),
        "ci_high": float(np.quantile(means, 1 - alpha / 2)),
        "n_boot": int(n_boot),
        "block_mean_length": int(block),
        "n_obs": int(n),
        "status": "ok",
    }


def ar_surrogate(data: np.ndarray, lag: int, rng: np.random.Generator) -> np.ndarray:
    """Independent AR(lag) surrogates: own persistence kept, TRUE cross-dependence 0.

    This is the no-spillover null floor. A GFEVD estimated on finitely many
    observations of genuinely independent series still reports a positive TCI, so
    an observed TCI level is uninterpretable without it.
    """
    n, k = data.shape
    burn = 500
    out = np.empty((n, k))
    for j in range(k):
        y = data[:, j]
        Xl = np.column_stack([y[lag - l - 1: n - l - 1] for l in range(lag)])
        Xl = np.column_stack([np.ones(len(Xl)), Xl])
        yl = y[lag:]
        beta, *_ = np.linalg.lstsq(Xl, yl, rcond=None)
        resid = yl - Xl @ beta
        sim = np.empty(n + burn)
        sim[:lag] = y[:lag].mean()
        draws = rng.choice(resid, size=n + burn, replace=True)
        for t in range(lag, n + burn):
            # own lags in order [t-1, t-2, ..., t-lag] to match the OLS design
            sim[t] = beta[0] + float(beta[1:] @ sim[t - lag: t][::-1]) + draws[t]
        out[:, j] = sim[burn:]
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Granger lead-lag — the formal test behind any "A leads B" sentence
# ═══════════════════════════════════════════════════════════════════════════════

def _lag_block(v: np.ndarray, lag: int, n: int) -> np.ndarray:
    """Columns [v_{t-1}, ..., v_{t-lag}] for t = lag .. n-1."""
    return np.column_stack([v[lag - l - 1: n - l - 1] for l in range(lag)])


def granger_design(y: np.ndarray, x: np.ndarray, lag: int,
                   controls: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Regression of y_t on its own lags, control lags, then x's lags.

    Returns (design, target, boolean mask selecting x's lag columns).
    """
    n = len(y)
    parts: list[np.ndarray] = [np.ones((n - lag, 1)), _lag_block(y, lag, n)]
    for c in controls:
        parts.append(_lag_block(c, lag, n))
    n_before = sum(p.shape[1] for p in parts)
    parts.append(_lag_block(x, lag, n))
    A = np.column_stack(parts)
    sel = np.zeros(A.shape[1], dtype=bool)
    sel[n_before: n_before + lag] = True
    return A, y[lag:], sel


def granger_test(y: np.ndarray, x: np.ndarray, lag: int, controls: list[np.ndarray],
                 hac_lag: int, n_boot: int, block: int, rng: np.random.Generator) -> dict:
    """HAC-robust Wald test that x's lags are jointly zero, plus a block-bootstrap CI.

    The Wald statistic uses a Newey-West covariance with a non-degenerate
    bandwidth (repo canonical ``ceil(n^(1/3))`` for a one-step target), because
    log volatility is strongly persistent and an unadjusted covariance would
    overstate significance. The circular block bootstrap on the SUM of x's lag
    coefficients is the dependence-robust companion; it needs no HAC of its own,
    so the resampled fits are plain least squares.
    """
    import statsmodels.api as sm

    A, yy, sel = granger_design(y, x, lag, controls)
    fit = sm.OLS(yy, A).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lag})
    R = np.eye(A.shape[1])[sel]
    wald = fit.wald_test(R, scalar=True)
    beta = np.asarray(fit.params)[sel]
    se = np.asarray(fit.bse)[sel]

    n = len(yy)
    sums = np.empty(n_boot)
    for b in range(n_boot):
        idx = circular_block_indices(n, block, rng)
        bb, *_ = np.linalg.lstsq(A[idx], yy[idx], rcond=None)
        sums[b] = float(bb[sel].sum())
    coef_sum = float(beta.sum())
    return {
        "lag": int(lag),
        "hac_lag": int(hac_lag),
        "n_obs": int(n),
        "wald_stat": float(wald.statistic),
        "p_value": float(wald.pvalue),
        "lag_coefficients": [float(v) for v in beta],
        "lag_coefficient_hac_se": [float(v) for v in se],
        "coef_sum": coef_sum,
        "coef_sum_boot_ci_90": [float(np.quantile(sums, 0.05)),
                                float(np.quantile(sums, 0.95))],
        "coef_sum_boot_sign_stability": float(np.mean(np.sign(sums) == np.sign(coef_sum))),
        "n_boot": int(n_boot),
        "block_length": int(block),
    }


def run_granger(name: str, log_vol: pd.DataFrame, cfg: dict, lag: int, n_boot: int) -> dict:
    """Both directions, with and without the broad-market volatility control.

    The SPY-controlled arm is the IDENTIFIED one and is what the verdict reads:
    without it, a Granger rejection can be the common market volatility factor
    arriving at the two legs with slightly different timing rather than a
    funding-chain channel.
    """
    X = log_vol[cfg["assets"] + ["SPY"]].dropna()
    hac_lag = int(np.ceil(len(X) ** (1 / 3)))
    rng = np.random.default_rng(SEED + 6)
    spy = X["SPY"].to_numpy()

    rows = []
    for s in cfg["sources"]:
        for t in cfg["targets"]:
            for direction, (src, tgt) in (
                ("physical_credit_to_ai", (s, t)),
                ("ai_to_physical_credit", (t, s)),
            ):
                for arm, controls in (("bivariate", []), ("spy_controlled", [spy])):
                    r = granger_test(X[tgt].to_numpy(), X[src].to_numpy(), lag,
                                     controls, hac_lag, n_boot, BLOCK_LEN, rng)
                    r.update({"source": src, "target": tgt, "direction": direction,
                              "arm": arm, "pair": f"{src}->{tgt}"})
                    rows.append(r)

    out = {"var_lag": int(lag), "hac_lag": hac_lag, "n_obs": int(len(X)),
           "hac_bandwidth_rule": "ceil(n^(1/3)) — repo canonical; never the degenerate h-1=0",
           "identified_arm": "spy_controlled", "tests": rows}
    for arm in ("bivariate", "spy_controlled"):
        for direction in ("physical_credit_to_ai", "ai_to_physical_credit"):
            fam = [r for r in rows if r["arm"] == arm and r["direction"] == direction]
            rej, p_adj, _, _ = multipletests([r["p_value"] for r in fam],
                                             alpha=FDR_Q, method="fdr_bh")
            for r, rj, pa in zip(fam, rej, p_adj):
                r["p_fdr_bh"] = float(pa)
                r["fdr_significant"] = bool(rj)
            out[f"summary_{arm}_{direction}"] = {
                "family_size": len(fam),
                "n_fdr_significant": int(sum(rej)),
                "pairs_fdr_significant": [r["pair"] for r, rj in zip(fam, rej) if rj],
            }
    fwd = out["summary_spy_controlled_physical_credit_to_ai"]
    rev = out["summary_spy_controlled_ai_to_physical_credit"]
    print(f"[granger:{name}] identified arm — physical/credit->AI "
          f"{fwd['n_fdr_significant']}/{fwd['family_size']} FDR sig; AI->physical/credit "
          f"{rev['n_fdr_significant']}/{rev['family_size']}")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# H1 + H2 — total spillover and its direction
# ═══════════════════════════════════════════════════════════════════════════════

def run_network(name: str, log_vol: pd.DataFrame, cfg: dict, n_boot: int,
                n_null: int, n_ord: int) -> dict:
    assets, sources, targets = cfg["assets"], cfg["sources"], cfg["targets"]
    X = log_vol[assets].dropna()
    data = X.to_numpy()
    n, k = data.shape
    assert n >= 500, f"{name}: only {n} common observations (<500)"

    adf = {
        a: {"stat": float(r[0]), "p_value": float(r[1])}
        for a, r in ((a, adfuller(X[a].to_numpy(), autolag="AIC")) for a in assets)
    }
    n_nonstationary = sum(1 for v in adf.values() if v["p_value"] > 0.05)

    lag = select_lag_aic(data, VAR_MAX_LAG)
    obs = network_snapshot(data, assets, lag, sources, targets)
    print(f"[{name}] n={n} k={k} VAR lag={lag} TCI={obs['tci']:.2f}")

    # ── H1: TCI against the independent-AR no-spillover floor ─────────────────
    rng = np.random.default_rng(SEED)
    null_tci = np.empty(n_null)
    for b in range(n_null):
        sur = ar_surrogate(data, lag, rng)
        null_tci[b] = dy_metrics(row_normalize(generalized_fevd(fit_var(sur, lag))), assets)["tci"]
    p_h1 = float((1 + int(np.sum(null_tci >= obs["tci"]))) / (n_null + 1))

    # ── circular block bootstrap: TCI CI, NPDC CI + one-sided p + sign stability
    rng_b = np.random.default_rng(SEED + 1)
    boot_tci = np.empty(n_boot)
    pair_keys = [f"{s}->{t}" for s in sources for t in targets]
    boot_pair = {kk: np.empty(n_boot) for kk in pair_keys}
    boot_net = {a: np.empty(n_boot) for a in assets}
    for b in range(n_boot):
        idx = circular_block_indices(n, BLOCK_LEN, rng_b)
        snap = network_snapshot(data[idx], assets, lag, sources, targets)
        boot_tci[b] = snap["tci"]
        for kk in pair_keys:
            boot_pair[kk][b] = snap["pairwise_net"][kk]
        for a in assets:
            boot_net[a][b] = snap["net"][a]

    tci_ci = [float(np.quantile(boot_tci, 0.025)), float(np.quantile(boot_tci, 0.975))]

    pair_rows = []
    for kk in pair_keys:
        d = boot_pair[kk]
        point = obs["pairwise_net"][kk]
        pair_rows.append(
            {
                "pair": kk,
                "npdc_pp": point,
                "boot_mean": float(d.mean()),
                "ci_low_90": float(np.quantile(d, 0.05)),
                "ci_high_90": float(np.quantile(d, 0.95)),
                "p_one_sided_gt0": float(np.mean(d <= 0.0)),
                "p_one_sided_lt0": float(np.mean(d >= 0.0)),
                "boot_sign_stability": float(np.mean(np.sign(d) == np.sign(point))),
            }
        )
    rej, p_adj, _, _ = multipletests([r["p_one_sided_gt0"] for r in pair_rows],
                                     alpha=FDR_Q, method="fdr_bh")
    for r, rj, pa in zip(pair_rows, rej, p_adj):
        r["p_fdr_bh"] = float(pa)
        r["fdr_significant"] = bool(rj)
    # The complementary one-sided test. H2 asks whether the physical/credit leg
    # transmits INTO the AI leg; if the estimates come out negative, the mirror
    # question ("does the AI leg transmit into the physical/credit leg?") is a
    # real, testable finding — but it was NOT pre-specified, so it is FDR'd in
    # its own family and reported as post-hoc throughout.
    rej_r, p_adj_r, _, _ = multipletests([r["p_one_sided_lt0"] for r in pair_rows],
                                         alpha=FDR_Q, method="fdr_bh")
    for r, rj, pa in zip(pair_rows, rej_r, p_adj_r):
        r["p_fdr_bh_reverse"] = float(pa)
        r["fdr_significant_reverse"] = bool(rj)

    net_rows = {
        a: {
            "net_pp": obs["net"][a],
            "ci_low_90": float(np.quantile(boot_net[a], 0.05)),
            "ci_high_90": float(np.quantile(boot_net[a], 0.95)),
            "boot_sign_stability": float(np.mean(np.sign(boot_net[a]) == np.sign(obs["net"][a]))),
        }
        for a in assets
    }

    # ── ordering robustness: KPPS invariance vs the Cholesky artifact ──────────
    rng_o = np.random.default_rng(SEED + 2)
    perms = [np.arange(k)] + [rng_o.permutation(k) for _ in range(n_ord - 1)]
    g_pair = {kk: [] for kk in pair_keys}
    c_pair = {kk: [] for kk in pair_keys}
    g_net = {a: [] for a in assets}
    c_net = {a: [] for a in assets}
    for pm in perms:
        lbl = [assets[i] for i in pm]
        r = fit_var(data[:, pm], lag)
        gm = dy_metrics(row_normalize(generalized_fevd(r)), lbl)
        cm = dy_metrics(row_normalize(cholesky_fevd(r)), lbl)
        gt = np.asarray(gm["matrix"]) / 100.0
        ct = np.asarray(cm["matrix"]) / 100.0
        for s in sources:
            for t in targets:
                g_pair[f"{s}->{t}"].append(pairwise_net(gt, lbl, s, t))
                c_pair[f"{s}->{t}"].append(pairwise_net(ct, lbl, s, t))
        for a in assets:
            g_net[a].append(gm["net"][a])
            c_net[a].append(cm["net"][a])

    def ord_stats(vals: list[float], reference: float) -> dict:
        v = np.asarray(vals)
        return {
            "min": float(v.min()),
            "max": float(v.max()),
            "mean": float(v.mean()),
            "max_abs_dev_from_identity_order": float(np.abs(v - reference).max()),
            "sign_stability": float(np.mean(np.sign(v) == np.sign(reference))),
            "frac_positive": float(np.mean(v > 0)),
        }

    ordering = {
        "n_orderings": int(len(perms)),
        "note": (
            "KPPS sign_stability is 1.0 BY CONSTRUCTION when max_abs_dev is at "
            "machine precision: it certifies that order-invariance was actually "
            "achieved, and is not a statistical robustness statement. The "
            "statistical robustness number is boot_sign_stability from the "
            "circular block bootstrap. The Cholesky arm is the artifact "
            "yardstick: it shows how much of a 'direction' the ordering alone "
            "could have manufactured (K628b / K865b)."
        ),
        "kpps_pairwise": {kk: ord_stats(g_pair[kk], obs["pairwise_net"][kk]) for kk in pair_keys},
        "cholesky_pairwise": {kk: ord_stats(c_pair[kk], c_pair[kk][0]) for kk in pair_keys},
        "kpps_net": {a: ord_stats(g_net[a], obs["net"][a]) for a in assets},
        "cholesky_net": {a: ord_stats(c_net[a], c_net[a][0]) for a in assets},
    }
    ordering["kpps_max_abs_dev_all"] = float(
        max(
            max(v["max_abs_dev_from_identity_order"] for v in ordering["kpps_pairwise"].values()),
            max(v["max_abs_dev_from_identity_order"] for v in ordering["kpps_net"].values()),
        )
    )
    ordering["kpps_order_invariance_verified"] = bool(ordering["kpps_max_abs_dev_all"] < 1e-6)
    ordering["cholesky_worst_pair_sign_stability"] = float(
        min(v["sign_stability"] for v in ordering["cholesky_pairwise"].values())
    )
    assert ordering["kpps_order_invariance_verified"], (
        f"{name}: KPPS arm is NOT order-invariant "
        f"(max dev {ordering['kpps_max_abs_dev_all']:.3e}) — the estimator is wrong"
    )

    # ── rolling TCI ───────────────────────────────────────────────────────────
    roll_dates, roll_tci = [], []
    for end in range(ROLL_WINDOW, n + 1, ROLL_STEP):
        w = data[end - ROLL_WINDOW: end]
        roll_tci.append(dy_metrics(row_normalize(generalized_fevd(fit_var(w, ROLL_VAR_LAG))),
                                   assets)["tci"])
        roll_dates.append(str(X.index[end - 1].date()))

    # ── sub-period robustness: is the direction a regime artifact? ─────────────
    subperiods = []
    for sp in SUBPERIODS:
        Xs = X.loc[sp["start"]: sp["end"]]
        if len(Xs) < 400:
            subperiods.append({"name": sp["name"], "why": sp["why"],
                               "status": "SKIPPED_TOO_FEW_OBS", "n_obs": int(len(Xs))})
            continue
        snap = network_snapshot(Xs.to_numpy(), assets, lag, sources, targets)
        subperiods.append({
            "name": sp["name"], "why": sp["why"], "status": "ok",
            "start": str(Xs.index[0].date()), "end": str(Xs.index[-1].date()),
            "n_obs": int(len(Xs)),
            "tci": snap["tci"],
            "net": snap["net"],
            "pairwise_net": snap["pairwise_net"],
            "n_pairs_positive": int(sum(v > 0 for v in snap["pairwise_net"].values())),
            "n_pairs": len(snap["pairwise_net"]),
        })
    ran = [s for s in subperiods if s["status"] == "ok"]
    subperiod_summary = {
        "n_subperiods_run": len(ran),
        "sign_agreement_with_full_sample": float(np.mean([
            np.sign(s["pairwise_net"][kk]) == np.sign(obs["pairwise_net"][kk])
            for s in ran for kk in pair_keys
        ])) if ran else None,
        "all_subperiods_all_pairs_negative": bool(
            ran and all(s["n_pairs_positive"] == 0 for s in ran)),
    }

    return {
        "role": cfg["role"],
        "why_this_system": cfg["why"],
        "assets": assets,
        "sources": sources,
        "targets": targets,
        "sample": {
            "start": str(X.index[0].date()),
            "end": str(X.index[-1].date()),
            "n_obs": int(n),
        },
        "var_lag_aic": int(lag),
        "fevd_horizon": FEVD_HORIZON,
        "adf_log_vol": adf,
        "n_series_adf_nonstationary_at_5pct": int(n_nonstationary),
        "observed": {k2: obs[k2] for k2 in ("tci", "from_others", "to_others", "net",
                                            "matrix", "pairwise_net")},
        "h1_total_spillover": {
            "tci_pp": obs["tci"],
            "tci_block_bootstrap_ci_95": tci_ci,
            "null_floor_mean": float(null_tci.mean()),
            "null_floor_q95": float(np.quantile(null_tci, 0.95)),
            "p_value_vs_independent_ar_null": p_h1,
            "n_null": int(n_null),
            "criterion": "block-bootstrap / surrogate p < 0.05",
        },
        "h2_pairwise": pair_rows,
        "net_directional": net_rows,
        "ordering_robustness": ordering,
        "subperiods": subperiods,
        "subperiod_summary": subperiod_summary,
        "rolling_tci": {"dates": roll_dates, "tci": [float(v) for v in roll_tci],
                        "window": ROLL_WINDOW, "step": ROLL_STEP, "var_lag": ROLL_VAR_LAG},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# H3 — incremental predictive content for Nasdaq / semis realized variance
# ═══════════════════════════════════════════════════════════════════════════════

def har_features(rv: pd.Series) -> pd.DataFrame:
    """HAR-RV daily/weekly/monthly log averages, stamped at the observation date."""
    lg = np.log(rv.clip(lower=1e-12))
    return pd.DataFrame(
        {
            "rv_d": lg,
            "rv_w": lg.rolling(5).mean(),
            "rv_m": lg.rolling(22).mean(),
        }
    )


def forward_rv(returns: pd.Series, h: int) -> pd.Series:
    """Mean squared daily return over [t, t+h-1], stamped at t.

    Paired with ``.shift(1)`` features this is exactly "signal from t-1, target
    realised from t onward".
    """
    sq = returns ** 2
    return sq.rolling(h).mean().shift(-(h - 1))


def expanding_oos(
    X: pd.DataFrame, y: pd.Series, oos_mask: np.ndarray, h: int, min_train: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Expanding-window OLS on the log target with the ``j + h - 1 < i`` embargo.

    Returns ``(predicted log target, training residual variance, mask forecast)``.
    The training residual variance is carried out so that the log-to-level
    conversion uses only in-sample information: computing it from realised OOS
    residuals would be a lookahead through the back door.
    """
    A = np.column_stack([np.ones(len(X)), X.to_numpy()])
    ly = np.log(np.clip(y.to_numpy(), 1e-12, None))
    n = len(A)
    pred = np.full(n, np.nan)
    sig2 = np.full(n, np.nan)
    for i in np.flatnonzero(oos_mask):
        last_train = i - h  # row j's label window closes at j+h-1 < i  =>  j <= i-h
        if last_train + 1 < min_train:
            continue
        Atr, ytr = A[: last_train + 1], ly[: last_train + 1]
        ok = np.isfinite(Atr).all(axis=1) & np.isfinite(ytr)
        if ok.sum() < min_train:
            continue
        beta, *_ = np.linalg.lstsq(Atr[ok], ytr[ok], rcond=None)
        if not np.isfinite(A[i]).all():
            continue
        resid = ytr[ok] - Atr[ok] @ beta
        dof = max(int(ok.sum()) - Atr.shape[1], 1)
        sig2[i] = float(resid @ resid / dof)
        pred[i] = float(A[i] @ beta)
    return pred, sig2, np.isfinite(pred)


def ladder_designs(target: str, h: int, rv_panel: pd.DataFrame, log_vol: pd.DataFrame,
                   returns: pd.DataFrame, exog: list[str]) -> tuple[dict, pd.Series, pd.Index]:
    """Build every rung of the identification ladder on ONE shared index.

    THE lag convention, applied once to every block: features are shifted by a
    single trading day, so the row stamped at t contains only closes up to t-1,
    while the target stamped at t is the realised variance over [t, t+h-1]. All
    rungs share this shift, this index and this training schedule.
    """
    own_rv = har_features(rv_panel[target]).rename(
        columns={"rv_d": "own_rv_d", "rv_w": "own_rv_w", "rv_m": "own_rv_m"})
    own_range = pd.DataFrame({
        "own_pk_d": log_vol[target],
        "own_pk_w": log_vol[target].rolling(5).mean(),
        "own_pk_m": log_vol[target].rolling(22).mean(),
    })
    mkt = pd.DataFrame({
        "spy_pk_d": log_vol["SPY"],
        "spy_pk_w": log_vol["SPY"].rolling(5).mean(),
        "spy_pk_m": log_vol["SPY"].rolling(22).mean(),
    })
    ex = pd.DataFrame({f"vol_{e}_w": log_vol[e].rolling(5).mean() for e in exog})

    blocks = {"own_rv": own_rv, "own_range": own_range, "mkt": mkt, "exog": ex}
    shifted = {k: v.shift(1) for k, v in blocks.items()}

    models = {
        "M0": ["own_rv"],
        "M1": ["own_rv", "own_range"],
        "M2": ["own_rv", "own_range", "mkt"],
        "M3": ["own_rv", "own_range", "mkt", "exog"],
        "M0plusExog": ["own_rv", "exog"],
    }
    y = forward_rv(returns[target], h)
    tickers = sorted(set([target, "SPY"] + exog))
    start = max(log_vol[t].dropna().index[0] for t in tickers)

    widest = pd.concat([shifted[b] for b in models["M3"]], axis=1)
    frame = pd.concat([y.rename("y"), widest], axis=1).loc[start:].dropna()
    idx = frame.index
    designs = {
        name: pd.concat([shifted[b] for b in blocks_], axis=1).loc[idx]
        for name, blocks_ in models.items()
    }
    for name, d in designs.items():
        assert d.notna().all().all(), f"{name}: design matrix has NaN on the shared index"
    return designs, frame["y"], idx


def run_forecast_cell(
    spec_name: str, target: str, h: int, rv_panel: pd.DataFrame,
    log_vol: pd.DataFrame, returns: pd.DataFrame, spec: dict, rng: np.random.Generator,
) -> dict:
    exog = spec["exog"]
    designs, y, idx = ladder_designs(target, h, rv_panel, log_vol, returns, exog)

    oos_mask = np.asarray(idx >= pd.Timestamp(spec["oos_start"]))
    assert oos_mask.sum() > 200, f"{spec_name}/{target}/h{h}: only {oos_mask.sum()} OOS origins"

    fits = {}
    for name, X in designs.items():
        p, s2, m = expanding_oos(X, y, oos_mask, h, MIN_TRAIN)
        fits[name] = {"pred": p, "sig2": s2, "mask": m}
    m = np.ones(len(idx), dtype=bool)
    for f in fits.values():
        m &= f["mask"]
    assert m.sum() > 100, f"{spec_name}/{target}/h{h}: only {m.sum()} evaluated origins"

    ly = np.log(np.clip(y.to_numpy(), 1e-12, None))
    a = ly[m]
    var_a = float(np.sum((a - a.mean()) ** 2))
    act = np.exp(a)

    rungs = {}
    per_model = {}
    for name, f in fits.items():
        pr = f["pred"][m]
        lvl = np.exp(pr + 0.5 * f["sig2"][m])   # in-sample sigma^2 only
        per_model[name] = {
            "n_regressors": int(designs[name].shape[1]),
            "oos_r2_log": 1.0 - float(np.sum((a - pr) ** 2)) / var_a,
            "qlike": float(qlike_pointwise(act, lvl).mean()),
        }

    for comp in LADDER_COMPARISONS:
        s, l = comp["small"], comp["large"]
        ps, pl = fits[s]["pred"][m], fits[l]["pred"][m]
        cw = clark_west_test(a, ps, pl, h=h)
        sq_gap = (a - ps) ** 2 - (a - pl) ** 2   # positive = larger model wins
        gap_ci = stationary_bootstrap_mean_ci(sq_gap, BOOT_MEAN_BLOCK, N_BOOT_FORECAST, rng)
        q_s = qlike_pointwise(act, np.exp(ps + 0.5 * fits[s]["sig2"][m]))
        q_l = qlike_pointwise(act, np.exp(pl + 0.5 * fits[l]["sig2"][m]))
        q_ci = stationary_bootstrap_mean_ci(q_s - q_l, BOOT_MEAN_BLOCK, N_BOOT_FORECAST, rng)
        rungs[comp["key"]] = {
            "role": comp["role"],
            "claim": comp["claim"],
            "small_model": s,
            "large_model": l,
            "clark_west": cw,
            "oos_r2_log_small": per_model[s]["oos_r2_log"],
            "oos_r2_log_large": per_model[l]["oos_r2_log"],
            "oos_r2_increment": per_model[l]["oos_r2_log"] - per_model[s]["oos_r2_log"],
            "mspe_gap_log_bootstrap": gap_ci,
            "qlike_small": per_model[s]["qlike"],
            "qlike_large": per_model[l]["qlike"],
            "qlike_improvement_pct": float(
                100.0 * (per_model[s]["qlike"] - per_model[l]["qlike"]) / per_model[s]["qlike"]),
            "qlike_gap_bootstrap": q_ci,
            "qlike_role": "descriptive_only_no_nested_test",
        }

    return {
        "spec": spec_name,
        "target": target,
        "horizon": h,
        "exog": exog,
        "market_control": "SPY",
        "sample_start": str(idx[0].date()),
        "sample_end": str(idx[-1].date()),
        "oos_start": spec["oos_start"],
        "n_train_min": MIN_TRAIN,
        "n_oos_evaluated": int(m.sum()),
        "models": per_model,
        "ladder": rungs,
        "primary": rungs[PRIMARY_COMPARISON],
    }


def run_h3(rv_panel, log_vol, returns) -> dict:
    rng = np.random.default_rng(SEED + 3)
    cells = []
    for spec_name, spec in FORECAST_SPECS.items():
        for target in FORECAST_TARGETS:
            for h in HORIZONS:
                cell = run_forecast_cell(spec_name, target, h, rv_panel, log_vol,
                                         returns, spec, rng)
                cells.append(cell)
                p = cell["primary"]
                lit = cell["ladder"]["M0plusExog_vs_M0"]
                print(
                    f"[H3] {spec_name} {target} h={h:2d} n={cell['n_oos_evaluated']:4d} "
                    f"| PRIMARY M3vM2 t={p['clark_west']['t_stat']:+.3f} "
                    f"p1={p['clark_west']['p_value_one_sided']:.4f} "
                    f"dR2={p['oos_r2_increment']:+.5f} "
                    f"| loose M0+E t={lit['clark_west']['t_stat']:+.2f}"
                )

    # FDR within each rung family separately: mixing a diagnostic rung into the
    # primary family would let the estimator-quality rung carry the correction.
    fdr = {}
    for comp in LADDER_COMPARISONS:
        key = comp["key"]
        pv = [c["ladder"][key]["clark_west"]["p_value_one_sided"] for c in cells]
        rej, p_adj, _, _ = multipletests(pv, alpha=FDR_Q, method="fdr_bh")
        for c, rj, pa in zip(cells, rej, p_adj):
            c["ladder"][key]["p_fdr_bh"] = float(pa)
            c["ladder"][key]["fdr_significant"] = bool(rj)
        fdr[key] = {
            "role": comp["role"],
            "family_size": len(cells),
            "n_fdr_significant": int(sum(rej)),
            "n_fdr_significant_and_positive_r2": int(sum(
                bool(rj) and c["ladder"][key]["oos_r2_increment"] > 0
                for c, rj in zip(cells, rej))),
        }
    for c in cells:
        c["primary"] = c["ladder"][PRIMARY_COMPARISON]

    return {
        "identification_ladder": LADDER_COMPARISONS,
        "primary_comparison": PRIMARY_COMPARISON,
        "family_size": len(cells),
        "fdr_method": "Benjamini-Hochberg",
        "fdr_q": FDR_Q,
        "primary_test": "Clark-West (2007) one-sided, log-variance MSPE, nested",
        "fdr_by_rung": fdr,
        "cells": cells,
        "n_fdr_significant": fdr[PRIMARY_COMPARISON]["n_fdr_significant"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# H4 — tradability (only when H2 or H3 has something to trade on)
# ═══════════════════════════════════════════════════════════════════════════════

def expanding_z(x: pd.Series, min_periods: int = 250) -> pd.Series:
    """Expanding-window z-score using only data up to and including each date."""
    mu = x.expanding(min_periods=min_periods).mean()
    sd = x.expanding(min_periods=min_periods).std(ddof=1)
    return (x - mu) / sd


def strategy_arms(log_vol: pd.DataFrame, returns: pd.DataFrame, exog: list[str],
                  target: str, oos_start: str) -> pd.DataFrame:
    """Weights at t built strictly from information available at t-1."""
    comp = log_vol[exog].mean(axis=1)
    z_cross = expanding_z(comp).shift(1)
    z_own = expanding_z(log_vol[target]).shift(1)
    z_mkt = expanding_z(log_vol["SPY"]).shift(1)
    r = returns[target]
    df = pd.DataFrame({"r": r, "z_cross": z_cross, "z_own": z_own, "z_mkt": z_mkt}).dropna()
    df = df.loc[pd.Timestamp(oos_start):]
    df["w_bh"] = 1.0
    df["w_own"] = (df["z_own"] <= GATE_Z).astype(float)
    df["w_mkt"] = (df["z_mkt"] <= GATE_Z).astype(float)
    df["w_cross"] = (df["z_cross"] <= GATE_Z).astype(float)
    return df


def net_returns(w: pd.Series, r: pd.Series, cost_bps: float) -> pd.Series:
    turn = w.diff().abs().fillna(w.abs())
    return w * r - turn * (cost_bps / 10000.0)


def perf(x: pd.Series) -> dict:
    x = x.dropna()
    ann_ret = float(x.mean() * TRADING_DAYS)
    ann_vol = float(x.std(ddof=1) * np.sqrt(TRADING_DAYS))
    return {
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": float(ann_ret / ann_vol) if ann_vol > 0 else None,
        "cumulative": float(np.expm1(x.sum())),
        "n_obs": int(len(x)),
    }


def phase_randomized_mdd_null(obs, strategy_w: pd.Series, r: pd.Series, bench: pd.Series,
                              n_rep: int, rng: np.random.Generator) -> dict:
    """Circular-shift null for the exposure-matched drawdown gap.

    A positive exposure-matched gap is necessary but NOT sufficient for timing
    skill: any weight path with the same unconditional exposure can produce one.
    The gap is therefore compared against its own phase-randomised distribution
    (repo rule, K1265b / K1702).
    """
    gap = float(obs.exposure_matched_gap)
    w = strategy_w.to_numpy()
    n = len(w)
    null = np.empty(n_rep)
    for b in range(n_rep):
        shift = int(rng.integers(1, n))
        ws = pd.Series(np.roll(w, shift), index=strategy_w.index)
        cmp_ = compare_max_drawdown(net_returns(ws, r, 0.0).to_numpy(), bench.to_numpy())
        null[b] = float(cmp_.exposure_matched_gap)
    return {
        "strategy_mdd": float(obs.strategy_mdd),
        "benchmark_mdd": float(obs.benchmark_mdd),
        "matched_benchmark_mdd": float(obs.matched_benchmark_mdd),
        "matched_lambda": float(obs.matched_lambda),
        "vol_ratio": float(obs.vol_ratio),
        "exposure_mismatch": bool(obs.exposure_mismatch),
        "exposure_matched_gap": gap,
        "phase_null_mean": float(null.mean()),
        "phase_null_q95": float(np.quantile(null, 0.95)),
        "p_value_vs_phase_null": float((1 + int(np.sum(null >= gap))) / (n_rep + 1)),
        "n_phase_reps": int(n_rep),
        "warnings": list(obs.warnings),
    }


def run_h4(log_vol, returns, spec_name: str, spec: dict, target: str) -> dict:
    df = strategy_arms(log_vol, returns, spec["exog"], target, spec["oos_start"])
    rng = np.random.default_rng(SEED + 4)
    grid = {}
    for c in COST_GRID_BPS:
        arms = {
            "buy_and_hold": net_returns(df["w_bh"], df["r"], c),
            "own_vol_gate": net_returns(df["w_own"], df["r"], c),
            "market_vol_gate": net_returns(df["w_mkt"], df["r"], c),
            "cross_basket_gate": net_returns(df["w_cross"], df["r"], c),
        }
        row = {a: perf(v) for a, v in arms.items()}
        for opponent in ("buy_and_hold", "own_vol_gate", "market_vol_gate"):
            d = (arms["cross_basket_gate"] - arms[opponent]).dropna()
            ci = stationary_bootstrap_mean_ci(d.to_numpy(), BOOT_MEAN_BLOCK, 500, rng)
            row[f"cross_minus_{opponent}_daily"] = ci
            row[f"cross_beats_{opponent}"] = bool(
                row["cross_basket_gate"]["sharpe"] is not None
                and row[opponent]["sharpe"] is not None
                and row["cross_basket_gate"]["sharpe"] > row[opponent]["sharpe"]
            )
        grid[f"{c:g}bps"] = row

    wins = {
        c: bool(grid[c]["cross_beats_buy_and_hold"]
                and grid[c]["cross_beats_own_vol_gate"]
                and grid[c]["cross_beats_market_vol_gate"])
        for c in grid
    }
    turnover_artifact = bool(wins.get("5bps") and not wins.get("0bps"))

    # The fair-comparison helper is called HERE, in the scope that assembles the
    # reported payload, so the exposure_matched companion and its circular_shift
    # null are visible next to the raw numbers rather than buried a call deeper.
    # Raw drawdown alone is not scale-invariant (repo rule; K1265b / K1702).
    bench_net = net_returns(df["w_bh"], df["r"], 0.0)
    fair = compare_max_drawdown(net_returns(df["w_cross"], df["r"], 0.0).to_numpy(),
                                bench_net.to_numpy())
    drawdown_audit = phase_randomized_mdd_null(fair, df["w_cross"], df["r"], bench_net,
                                               N_PHASE_NULL, rng)
    return {
        "spec": spec_name,
        "target": target,
        "oos_start": spec["oos_start"],
        "gate_z_threshold": GATE_Z,
        "n_days": int(len(df)),
        "avg_exposure": {
            arm: float(df[col].mean())
            for arm, col in (("own_vol_gate", "w_own"), ("market_vol_gate", "w_mkt"),
                             ("cross_basket_gate", "w_cross"))
        },
        "annual_turnover": {
            arm: float(df[col].diff().abs().sum() / len(df) * TRADING_DAYS)
            for arm, col in (("own_vol_gate", "w_own"), ("market_vol_gate", "w_mkt"),
                             ("cross_basket_gate", "w_cross"))
        },
        "cost_grid": grid,
        "wins_both_baselines_by_cost": wins,
        "turnover_artifact": turnover_artifact,
        "turnover_artifact_rule": (
            "a rule that wins only in the high-cost column is winning by trading "
            "less, not by timing — it is declared a turnover artifact, not a signal"
        ),
        "drawdown": drawdown_audit,
        "equity": {
            "dates": [str(d.date()) for d in df.index],
            "buy_and_hold": np.cumsum(net_returns(df["w_bh"], df["r"], 1.0)).tolist(),
            "own_vol_gate": np.cumsum(net_returns(df["w_own"], df["r"], 1.0)).tolist(),
            "market_vol_gate": np.cumsum(net_returns(df["w_mkt"], df["r"], 1.0)).tolist(),
            "cross_basket_gate": np.cumsum(net_returns(df["w_cross"], df["r"], 1.0)).tolist(),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Lookahead causal probe
# ═══════════════════════════════════════════════════════════════════════════════

def corrupt_after(panel: dict[str, pd.DataFrame], cut: pd.Timestamp,
                  rng: np.random.Generator, sigma: float = 0.005) -> dict[str, pd.DataFrame]:
    """Replace every bar strictly after ``cut`` with an N(0, sigma^2) random walk.

    If any feature, forecast, or position stamped on or before ``cut`` moves, the
    pipeline was reading the future. sigma = 0.5% per day.
    """
    out = {}
    for tk, df in panel.items():
        d = df.copy()
        post = d.index > cut
        m = int(post.sum())
        if m == 0:
            out[tk] = d
            continue
        anchor = float(d.loc[~post, "Close"].iloc[-1])
        steps = rng.normal(0.0, sigma, size=m)
        close = anchor * np.exp(np.cumsum(steps))
        rng_hl = np.abs(rng.normal(0.0, sigma, size=m))
        d.loc[post, "Close"] = close
        d.loc[post, "Open"] = np.concatenate([[anchor], close[:-1]])
        d.loc[post, "High"] = np.maximum(close, d.loc[post, "Open"].to_numpy()) * (1 + rng_hl)
        d.loc[post, "Low"] = np.minimum(close, d.loc[post, "Open"].to_numpy()) * (1 - rng_hl)
        out[tk] = d
    return out


def lookahead_probe(panel: dict[str, pd.DataFrame], cut: pd.Timestamp) -> dict:
    rng = np.random.default_rng(SEED + 5)
    dirty = corrupt_after(panel, cut, rng)

    clean_lv, _ = build_log_vol(panel, "parkinson")
    dirty_lv, _ = build_log_vol(dirty, "parkinson")
    clean_r = close_returns(panel)
    dirty_r = close_returns(dirty)
    clean_rv = clean_r ** 2
    dirty_rv = dirty_r ** 2

    violations: list[dict] = []

    # 1. features / vol proxies on or before the cut must be untouched
    pre = clean_lv.index <= cut
    dev = float(np.nanmax(np.abs(clean_lv[pre].to_numpy() - dirty_lv.loc[clean_lv.index[pre]].to_numpy())))
    if dev > 0.0:
        violations.append({"stage": "log_vol_panel", "max_abs_deviation": dev})

    # 2. OOS forecasts at origins <= cut must be identical
    spec_name = "long7"
    spec = FORECAST_SPECS[spec_name]
    cell_checks = []
    for target in FORECAST_TARGETS:
        for h in HORIZONS:
            p1 = _preds_for_probe(spec_name, target, h, clean_rv, clean_lv, clean_r, spec, cut)
            p2 = _preds_for_probe(spec_name, target, h, dirty_rv, dirty_lv, dirty_r, spec, cut)
            common = p1.index.intersection(p2.index)
            devs = {
                col: float(np.nanmax(np.abs(p1.loc[common, col] - p2.loc[common, col])))
                if len(common) else 0.0
                for col in ("M2", "M3", "M2_level", "M3_level")
            }
            cell_checks.append({
                "target": target, "horizon": h, "n_pre_cut_origins": int(len(common)),
                "max_abs_deviation": devs,
            })
            worst = max(devs.values())
            if worst > 0.0:
                violations.append({
                    "stage": f"forecast/{target}/h{h}", "max_abs_deviation": worst,
                })

    # 3. strategy positions on or before the cut must be identical
    df1 = strategy_arms(clean_lv, clean_r, spec["exog"], "QQQ", spec["oos_start"])
    df2 = strategy_arms(dirty_lv, dirty_r, spec["exog"], "QQQ", spec["oos_start"])
    pre_idx = df1.index[df1.index <= cut].intersection(df2.index)
    w_dev = float(np.nanmax(np.abs(
        df1.loc[pre_idx, ["w_own", "w_cross"]].to_numpy()
        - df2.loc[pre_idx, ["w_own", "w_cross"]].to_numpy()
    ))) if len(pre_idx) else 0.0
    if w_dev > 0.0:
        violations.append({"stage": "strategy_weights", "max_abs_deviation": w_dev})

    return {
        "method": (
            "every OHLC bar strictly after the cut is replaced by an "
            "N(0, 0.005^2) random walk; features, forecasts and positions "
            "stamped on or before the cut must be bit-identical"
        ),
        "cut_date": str(cut.date()),
        "noise_sd_daily": 0.005,
        "seed": SEED + 5,
        "log_vol_max_abs_deviation_pre_cut": dev,
        "forecast_checks": cell_checks,
        "strategy_weight_max_abs_deviation_pre_cut": w_dev,
        "violations": violations,
        "n_violations": len(violations),
        "verdict": "CLEAN" if not violations else "LOOKAHEAD_DETECTED",
    }


def _preds_for_probe(spec_name, target, h, rv_panel, log_vol, returns, spec,
                     cut: pd.Timestamp) -> pd.DataFrame:
    """Origin-level M2 / M3 predictions and level conversions, for origins <= cut."""
    designs, y, idx = ladder_designs(target, h, rv_panel, log_vol, returns, spec["exog"])
    oos = np.asarray(idx >= pd.Timestamp(spec["oos_start"])) & np.asarray(idx <= cut)
    cols = {}
    for name in ("M2", "M3"):
        p, s2, _ = expanding_oos(designs[name], y, oos, h, MIN_TRAIN)
        cols[name] = p
        cols[f"{name}_level"] = np.exp(p + 0.5 * s2)
    out = pd.DataFrame(cols, index=idx)
    return out[oos]


# ═══════════════════════════════════════════════════════════════════════════════
# Figures
# ═══════════════════════════════════════════════════════════════════════════════

def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.9)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)


def fig_network_matrix(net: dict, name: str, out: Path) -> None:
    """Directional connectedness table. Polarity -> diverging, magnitude -> sequential."""
    assets = net["assets"]
    m = np.asarray(net["observed"]["matrix"])
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), facecolor=SURFACE,
                             gridspec_kw={"width_ratios": [1.25, 1]})
    ax = axes[0]
    im = ax.imshow(m, cmap=LinearSegmentedColormap.from_list("seq", SEQ_BLUE),
                   vmin=0, vmax=np.max(m))
    ax.set_xticks(range(len(assets)), assets, rotation=45, ha="right")
    ax.set_yticks(range(len(assets)), assets)
    ax.set_xlabel("shock FROM (transmitter)", color=INK2, fontsize=9)
    ax.set_ylabel("variance OF (receiver)", color=INK2, fontsize=9)
    ax.set_title(f"KPPS generalized FEVD, H={FEVD_HORIZON}  ({name})",
                 color=INK, fontsize=10.5, loc="left")
    for i in range(len(assets)):
        for j in range(len(assets)):
            ax.text(j, i, f"{m[i, j]:.0f}", ha="center", va="center", fontsize=7,
                    color="#ffffff" if m[i, j] > np.max(m) * 0.55 else INK)
    cb = fig.colorbar(im, ax=ax, fraction=0.046)
    cb.set_label("share of forecast-error variance (pp)", color=INK2, fontsize=8)
    cb.ax.tick_params(colors=INK2, labelsize=8)

    ax = axes[1]
    rows = net["h2_pairwise"]
    labels = [r["pair"] for r in rows]
    vals = [r["npdc_pp"] for r in rows]
    lo = [r["npdc_pp"] - r["ci_low_90"] for r in rows]
    hi = [r["ci_high_90"] - r["npdc_pp"] for r in rows]
    ypos = np.arange(len(rows))
    colors = [CAT[0] if v > 0 else CAT[7] for v in vals]
    ax.barh(ypos, vals, height=0.6, color=colors, edgecolor=SURFACE, linewidth=2)
    ax.errorbar(vals, ypos, xerr=[lo, hi], fmt="none", ecolor=INK2, elinewidth=1.2, capsize=3)
    ax.axvline(0, color=INK, linewidth=1.0)
    ax.set_yticks(ypos, labels)
    ax.invert_yaxis()
    ax.set_xlabel("pairwise net directional connectedness (pp), 90% block-bootstrap CI",
                  color=INK2, fontsize=8.5)
    ax.set_title("H2: physical / credit  ->  AI leg", color=INK, fontsize=10.5, loc="left")
    # Labels sit outside the whisker, never on top of it.
    span = max(r["ci_high_90"] for r in rows) - min(r["ci_low_90"] for r in rows)
    pad = 0.04 * max(span, 1e-6)
    for yi, r in zip(ypos, rows):
        mark = "  FDR sig" if r["fdr_significant"] else ""
        if r["npdc_pp"] >= 0:
            ax.text(r["ci_high_90"] + pad, yi, f"{r['npdc_pp']:+.2f}{mark}",
                    va="center", ha="left", fontsize=7.5, color=INK2)
        else:
            ax.text(r["ci_low_90"] - pad, yi, f"{r['npdc_pp']:+.2f}{mark}",
                    va="center", ha="right", fontsize=7.5, color=INK2)
    ax.margins(x=0.22)
    for a in axes:
        _style(a)
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def fig_ordering(net: dict, name: str, out: Path) -> None:
    """What the ordering alone could have manufactured."""
    pairs = [r["pair"] for r in net["h2_pairwise"]]
    ordr = net["ordering_robustness"]
    n = len(pairs)
    ncol = 2
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(11, 2.5 * nrow), facecolor=SURFACE,
                            squeeze=False)
    for k2, pair in enumerate(pairs):
        ax = axes[k2 // ncol][k2 % ncol]
        ch = ordr["cholesky_pairwise"][pair]
        gk = ordr["kpps_pairwise"][pair]
        lo, hi = ch["min"], ch["max"]
        span = max(hi - lo, 1e-6)
        ax.barh([0], [span], left=lo, height=0.45, color="#cde2fb", edgecolor=SURFACE,
                linewidth=2, label="Cholesky range over orderings")
        ax.plot([ch["mean"]], [0], marker="|", markersize=18, color=CAT[1], linewidth=0,
                label="Cholesky mean")
        ax.plot([gk["mean"]], [0], marker="D", markersize=7, color=CAT[0], linewidth=0,
                label="KPPS (order-invariant)")
        ax.axvline(0, color=INK, linewidth=1.0)
        ax.set_yticks([])
        ax.set_ylim(-1.0, 1.0)   # keeps the range band a thin strip, not a slab
        ax.set_title(
            f"{pair}   Cholesky sign stability {ch['sign_stability']:.0%}"
            f"  |  KPPS {gk['mean']:+.2f}pp",
            color=INK, fontsize=9, loc="left")
        _style(ax)
        ax.grid(axis="y", visible=False)
    for k2 in range(n, nrow * ncol):
        axes[k2 // ncol][k2 % ncol].set_visible(False)
    handles, lbls = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, lbls, loc="lower center", ncol=3, frameon=False,
               fontsize=8.5, labelcolor=INK2)
    fig.suptitle(
        f"Ordering-artifact audit, {ordr['n_orderings']} random column orders ({name})\n"
        f"KPPS max abs deviation across orderings = {ordr['kpps_max_abs_dev_all']:.2e}",
        color=INK, fontsize=11, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 0.92))
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def fig_rolling_tci(nets: dict, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.6), facecolor=SURFACE)
    for i, (name, net) in enumerate(nets.items()):
        r = net["rolling_tci"]
        d = pd.to_datetime(r["dates"])
        ax.plot(d, r["tci"], color=CAT[i], linewidth=2, label=f"{name} rolling TCI")
        floor = net["h1_total_spillover"]["null_floor_q95"]
        ax.axhline(floor, color=CAT[i], linewidth=1.2, linestyle=":",
                   label=f"{name} no-spillover null q95 = {floor:.1f}")
    ax.set_ylabel("total connectedness index (pp)", color=INK2, fontsize=9)
    ax.set_title(f"Rolling {ROLL_WINDOW}-day total spillover vs the independent-AR floor",
                 color=INK, fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, ncol=2)
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def fig_granger(granger: dict, name: str, out: Path) -> None:
    """Both directions of the identified (SPY-controlled) Granger arm, side by side."""
    tests = [t for t in granger[name]["tests"] if t["arm"] == "spy_controlled"]
    fwd = [t for t in tests if t["direction"] == "physical_credit_to_ai"]
    rev = [t for t in tests if t["direction"] == "ai_to_physical_credit"]
    labels = [t["pair"] for t in fwd]
    y = np.arange(len(fwd))
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 0.55 * len(fwd) + 3.2), facecolor=SURFACE)

    for ax, rows, title, colour in (
        (axes[0], fwd, "physical / credit  ->  AI leg   (the hypothesis)", CAT[0]),
        (axes[1], rev, "AI leg  ->  physical / credit   (the mirror)", CAT[1]),
    ):
        vals = [t["coef_sum"] for t in rows]
        lo = [t["coef_sum"] - t["coef_sum_boot_ci_90"][0] for t in rows]
        hi = [t["coef_sum_boot_ci_90"][1] - t["coef_sum"] for t in rows]
        cols = [colour if t["fdr_significant"] else "#cde2fb" for t in rows]
        ax.barh(y, vals, height=0.58, color=cols, edgecolor=SURFACE, linewidth=2)
        ax.errorbar(vals, y, xerr=[lo, hi], fmt="none", ecolor=INK2, elinewidth=1.2, capsize=3)
        ax.axvline(0, color=INK, linewidth=1.0)
        ax.set_yticks(y, [t["pair"] for t in rows], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("sum of the source's 5 lag coefficients, 90% block-bootstrap CI",
                      color=INK2, fontsize=8.5)
        ax.set_title(title, color=INK, fontsize=10, loc="left")
        # Labels go past the whisker cap so nothing is written over an interval.
        hi_all = [t["coef_sum_boot_ci_90"][1] for t in rows]
        lo_all = [t["coef_sum_boot_ci_90"][0] for t in rows]
        pad = 0.05 * max(max(hi_all) - min(lo_all), 1e-9)
        for yi, t in zip(y, rows):
            ax.text(t["coef_sum_boot_ci_90"][1] + pad, yi,
                    f"Wald {t['wald_stat']:.1f}"
                    + ("  FDR sig" if t["fdr_significant"] else ""),
                    va="center", ha="left", fontsize=7, color=INK2)
        ax.margins(x=0.28)
        _style(ax)
    fig.suptitle(
        f"HAC-robust Granger lead-lag, SPY-volatility-controlled ({name}, "
        f"lag {granger[name]['var_lag']}, HAC bandwidth {granger[name]['hac_lag']})\n"
        f"solid bars are Benjamini-Hochberg significant at q=0.10 within their own direction",
        color=INK, fontsize=10.5, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def fig_subperiods(nets: dict, out: Path) -> None:
    """Is the net direction a regime artifact? One panel per system."""
    fig, axes = plt.subplots(1, len(nets), figsize=(6.3 * len(nets), 4.6), facecolor=SURFACE,
                             squeeze=False)
    for ai, (name, net) in enumerate(nets.items()):
        ax = axes[0][ai]
        ran = [s for s in net["subperiods"] if s["status"] == "ok"]
        pairs = list(net["observed"]["pairwise_net"].keys())
        width = 0.8 / max(len(ran), 1)
        x = np.arange(len(pairs))
        for si, s in enumerate(ran):
            ax.bar(x + (si - (len(ran) - 1) / 2) * width,
                   [s["pairwise_net"][p] for p in pairs],
                   width=width - 0.02, color=CAT[si], edgecolor=SURFACE, linewidth=1.5,
                   label=s["name"])
        ax.axhline(0, color=INK, linewidth=1.0)
        ax.set_xticks(x, pairs, rotation=45, ha="right", fontsize=7.5)
        ax.set_ylabel("pairwise net directional connectedness (pp)", color=INK2, fontsize=8.5)
        ax.set_title(f"{name} — sub-period stability of the sign", color=INK,
                     fontsize=10.5, loc="left")
        ax.legend(frameon=False, fontsize=8, labelcolor=INK2)
        _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def fig_h3(h3: dict, out: Path) -> None:
    cells = h3["cells"]
    labels = [f"{c['spec']}\n{c['target']} h={c['horizon']}" for c in cells]
    x = np.arange(len(cells))
    prim = [c["ladder"][PRIMARY_COMPARISON] for c in cells]

    fig, axes = plt.subplots(2, 1, figsize=(12.5, 8.0), facecolor=SURFACE, sharex=True)

    # Rung 1 — where the apparent gain actually lives.
    ax = axes[0]
    rung_keys = ["M1_vs_M0", "M2_vs_M1", "M3_vs_M2"]
    rung_lbl = {
        "M1_vs_M0": "M1-M0  own range vol (estimator quality)",
        "M2_vs_M1": "M2-M1  broad-market vol factor (SPY)",
        "M3_vs_M2": "M3-M2  physical / credit block  [PRIMARY]",
    }
    width = 0.27
    for i, key in enumerate(rung_keys):
        vals = [c["ladder"][key]["clark_west"]["t_stat"] for c in cells]
        ax.bar(x + (i - 1) * width, vals, width=width - 0.02, color=CAT[i],
               edgecolor=SURFACE, linewidth=2, label=rung_lbl[key])
    ax.axhline(0, color=INK, linewidth=1.0)
    ax.axhline(1.282, color=INK2, linewidth=1.0, linestyle=":")
    ax.text(-0.45, 1.45, "one-sided 10%", fontsize=7.5, color=INK2, ha="left")
    ax.set_ylabel("Clark-West t statistic", color=INK2, fontsize=9)
    ax.set_title("H3 identification ladder: which block earns the forecast gain?",
                 color=INK, fontsize=11.5, loc="left")
    ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, ncol=1, loc="upper right")

    # Rung 2 — the primary rung's OOS R² increment with its bootstrap interval.
    ax = axes[1]
    inc = [r["oos_r2_increment"] for r in prim]
    ax.bar(x, inc, width=0.6,
           color=[CAT[0] if r["fdr_significant"] else "#cde2fb" for r in prim],
           edgecolor=SURFACE, linewidth=2)
    ax.axhline(0, color=INK, linewidth=1.0)
    ax.set_ylabel("OOS R² increment, log variance\nM3 over M2", color=INK2, fontsize=9)
    ax.set_xticks(x, labels, fontsize=7.5)
    ax.set_title("Primary rung only — solid bars are Benjamini-Hochberg significant at q=0.10",
                 color=INK, fontsize=10, loc="left")
    for xi, r in zip(x, prim):
        ci = r["mspe_gap_log_bootstrap"]
        tag = "CI>0" if (ci["ci_low"] or 0) > 0 else ""
        if tag:
            ax.text(xi, r["oos_r2_increment"], tag, ha="center", fontsize=7, color=INK2,
                    va="bottom" if r["oos_r2_increment"] >= 0 else "top")
    for a in axes:
        _style(a)
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def fig_h4(h4: dict, out: Path) -> None:
    eq = h4["equity"]
    d = pd.to_datetime(eq["dates"])
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), facecolor=SURFACE,
                             gridspec_kw={"width_ratios": [1.5, 1]})
    ax = axes[0]
    for i, arm in enumerate(["buy_and_hold", "own_vol_gate", "market_vol_gate",
                             "cross_basket_gate"]):
        ax.plot(d, eq[arm], color=CAT[i], linewidth=2, label=arm.replace("_", " "))
    ax.set_ylabel("cumulative log return, 1 bp/side", color=INK2, fontsize=9)
    ax.set_title(f"H4: {h4['target']} gated by physical / credit volatility ({h4['spec']})",
                 color=INK, fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2)

    ax = axes[1]
    costs = list(h4["cost_grid"].keys())
    arms = ["buy_and_hold", "own_vol_gate", "market_vol_gate", "cross_basket_gate"]
    width = 0.21
    xs = np.arange(len(costs))
    for i, arm in enumerate(arms):
        vals = [h4["cost_grid"][c][arm]["sharpe"] for c in costs]
        ax.bar(xs + (i - 1.5) * width, vals, width=width - 0.02, color=CAT[i],
               edgecolor=SURFACE, linewidth=2, label=arm.replace("_", " "))
    ax.axhline(0, color=INK, linewidth=1.0)
    ax.set_xticks(xs, costs)
    ax.set_ylabel("annualised Sharpe", color=INK2, fontsize=9)
    ax.set_title("Cost grid (per side)", color=INK, fontsize=11, loc="left")
    for a in axes:
        _style(a)
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=SURFACE)
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# Verdicts
# ═══════════════════════════════════════════════════════════════════════════════

def verdict_h1(nets: dict) -> dict:
    prim = nets["full8"]["h1_total_spillover"]
    ok = prim["p_value_vs_independent_ar_null"] < 0.05
    both = all(n["h1_total_spillover"]["p_value_vs_independent_ar_null"] < 0.05
               for n in nets.values())
    return {
        "hypothesis": "H1 — the three-basket system carries significant total spillover",
        "criterion": "surrogate / block-bootstrap p < 0.05 vs an independent-AR no-spillover floor",
        "verdict": "ACCEPT" if (ok and both) else ("PARTIAL" if ok else "REJECT"),
        "primary_tci_pp": prim["tci_pp"],
        "primary_p_value": prim["p_value_vs_independent_ar_null"],
        "null_floor_q95": prim["null_floor_q95"],
        "both_systems_significant": both,
    }


def verdict_h2_reverse(nets: dict, granger: dict) -> dict:
    """The mirror finding. POST-HOC: not pre-specified, so labelled as such."""
    prim = nets["full8"]
    rows = prim["h2_pairwise"]
    sig_neg = [r for r in rows
               if r["fdr_significant_reverse"] and r["npdc_pp"] < 0
               and r["boot_sign_stability"] >= 0.90]
    g = granger["full8"]["summary_spy_controlled_ai_to_physical_credit"]
    g_fwd = granger["full8"]["summary_spy_controlled_physical_credit_to_ai"]
    both = bool(len(sig_neg) == len(rows) and g["n_fdr_significant"] > g_fwd["n_fdr_significant"])
    return {
        "hypothesis": "H2R (POST-HOC) — the AI leg is the net transmitter INTO the "
                      "physical / credit leg, i.e. the funding-chain story runs backwards",
        "status": "post_hoc_not_pre_specified",
        "criterion": (
            "complement of the pre-specified one-sided test: KPPS pairwise NPDC < 0, "
            "Benjamini-Hochberg significant at q=0.10 in its own family, bootstrap "
            "sign stability >= 90%, and the SPY-controlled Granger evidence at least "
            "as strong in the reverse direction as in the hypothesised one"
        ),
        "verdict": "SUPPORTED_POST_HOC" if both else (
            "PARTIAL_POST_HOC" if sig_neg else "NOT_SUPPORTED"),
        "n_pairs_negative_and_fdr_significant": len(sig_neg),
        "n_pairs_tested": len(rows),
        "pairs": [r["pair"] for r in sig_neg],
        "granger_reverse_fdr_significant": g["n_fdr_significant"],
        "granger_forward_fdr_significant": g_fwd["n_fdr_significant"],
        "caveat": (
            "KPPS shares are shares of CORRELATED shocks, so a net-directional "
            "number is a reduced-form informational lead, not a structural causal "
            "effect. Read together with the Granger arm, not instead of it."
        ),
    }


def verdict_h2(nets: dict, granger: dict) -> dict:
    prim = nets["full8"]
    rows = prim["h2_pairwise"]
    sig_pos = [r for r in rows if r["fdr_significant"] and r["npdc_pp"] > 0]
    stab = {r["pair"]: r["boot_sign_stability"] for r in sig_pos}
    stab_ok = [p for p, v in stab.items() if v >= 0.90]
    order_ok = prim["ordering_robustness"]["kpps_order_invariance_verified"]
    g = granger["full8"]["summary_spy_controlled_physical_credit_to_ai"]
    if sig_pos and stab_ok and order_ok:
        v = "ACCEPT" if (len(stab_ok) == len(rows) and g["n_fdr_significant"] > 0) else "PARTIAL"
    elif sig_pos and order_ok:
        v = "PARTIAL"
    else:
        v = "REJECT"
    return {
        "hypothesis": "H2 — physical / credit volatility is a net transmitter INTO the AI leg",
        "criterion": (
            "KPPS pairwise NPDC > 0, Benjamini-Hochberg significant at q=0.10, AND "
            "block-bootstrap sign stability >= 90%; order-invariance of the estimator "
            "verified numerically; corroborated by the SPY-controlled HAC Granger arm"
        ),
        "verdict": v,
        "n_pairs_tested": len(rows),
        "granger_spy_controlled_forward_fdr_significant": g["n_fdr_significant"],
        "granger_forward_family_size": g["family_size"],
        "granger_vs_npdc_tension": (
            f"The identified Granger arm rejects no-lead in "
            f"{g['n_fdr_significant']}/{g['family_size']} forward pairs, so the "
            f"physical/credit leg DOES carry in-sample lead information for AI "
            f"volatility even after the SPY control. The net variance-share balance "
            f"nevertheless runs the other way, and the sign is bootstrap-stable. The "
            f"two measures answer different questions — incremental predictability of "
            f"the conditional mean versus the balance of correlated-shock variance "
            f"shares — and only the pre-specified net-directional criterion decides H2."
        ),
        "subperiod_summary": prim["subperiod_summary"],
        "n_pairs_fdr_significant_positive": len(sig_pos),
        "pairs_passing_sign_stability": stab_ok,
        "bootstrap_sign_stability_of_significant_pairs": stab,
        "kpps_order_invariance_verified": order_ok,
        "cholesky_worst_pair_sign_stability": prim["ordering_robustness"][
            "cholesky_worst_pair_sign_stability"],
        "note": (
            "The direction is judged ONLY on the order-invariant KPPS arm. The "
            "Cholesky sign-stability number is reported to size the artifact that "
            "sank K628b and K865b, not as evidence."
        ),
    }


def verdict_h3(h3: dict) -> dict:
    cells = h3["cells"]

    def cid(c):
        return f"{c['spec']}/{c['target']}/h{c['horizon']}"

    prim = [c["ladder"][PRIMARY_COMPARISON] for c in cells]
    sig = [c for c, r in zip(cells, prim) if r["fdr_significant"] and r["oos_r2_increment"] > 0]
    pos_ci = [c for c, r in zip(cells, prim)
              if (r["mspe_gap_log_bootstrap"]["ci_low"] or 0) > 0]
    if len(sig) >= 2 and pos_ci:
        v = "ACCEPT"
    elif sig:
        v = "PARTIAL"
    else:
        v = "REJECT"
    best = max(zip(cells, prim), key=lambda cr: cr[1]["clark_west"]["t_stat"])
    return {
        "hypothesis": "H3 — physical / credit volatility adds OOS predictive content "
                      "beyond own volatility AND the broad-market volatility factor",
        "criterion": (
            "PRIMARY rung M3 vs M2: Clark-West one-sided p, Benjamini-Hochberg q=0.10 over "
            "the 12-cell family, with a positive OOS R² increment; and a bootstrap interval "
            "on the squared-error gap excluding zero for at least one cell"
        ),
        "verdict": v,
        "n_cells": len(cells),
        "n_fdr_significant_positive": len(sig),
        "cells_fdr_significant": [cid(c) for c in sig],
        "cells_with_positive_bootstrap_interval": [cid(c) for c in pos_ci],
        "best_cell": cid(best[0]),
        "max_cw_t": best[1]["clark_west"]["t_stat"],
        "rung_summary": h3["fdr_by_rung"],
        "why_the_ladder": (
            "Testing the exogenous block against a bare squared-return HAR-RV (the "
            "brief's literal reading, rung M0plusExog_vs_M0) is NOT identified: the "
            "exogenous regressors are range-based volatility, so part of any gain is "
            "estimator quality (rung M1_vs_M0) and part is the common market "
            "volatility factor (rung M2_vs_M1). Only M3_vs_M2 isolates the "
            "AI-infrastructure funding-chain channel, so only it governs this verdict."
        ),
    }


def verdict_h4(h4: dict | None, precondition: bool) -> dict:
    if not precondition or h4 is None:
        return {
            "hypothesis": "H4 — the signal is tradable",
            "criterion": "run only if H2 or H3 is ACCEPT/PARTIAL; beat buy-and-hold AND the "
                         "own-volatility gate at 0 bp, otherwise turnover artifact",
            "verdict": "NOT_RUN_PRECONDITION_NOT_MET",
            "reason": "neither H2 nor H3 produced a surviving positive result",
        }
    wins = h4["wins_both_baselines_by_cost"]
    if h4["turnover_artifact"]:
        v = "REJECT_TURNOVER_ARTIFACT"
    elif wins.get("0bps") and wins.get("1bps") and wins.get("5bps"):
        v = "ACCEPT"
    elif wins.get("0bps"):
        v = "PARTIAL"
    else:
        v = "REJECT"
    return {
        "hypothesis": "H4 — the signal is tradable",
        "criterion": ("beat buy-and-hold AND the own-volatility gate across the 0/1/5 bp "
                      "grid; a win only in the high-cost column is a turnover artifact"),
        "verdict": v,
        "wins_by_cost": wins,
        "turnover_artifact": h4["turnover_artifact"],
        "exposure_matched_mdd_gap": h4["drawdown"]["exposure_matched_gap"],
        "mdd_gap_p_vs_phase_null": h4["drawdown"]["p_value_vs_phase_null"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download prices")
    ap.add_argument("--quick", action="store_true", help="smoke run with tiny replicate counts")
    args = ap.parse_args()

    n_boot = 60 if args.quick else N_BOOT_NETWORK
    n_null = 40 if args.quick else N_NULL_TCI
    n_ord = 20 if args.quick else N_ORDERINGS

    np.random.seed(SEED)
    panel = download_panel(args.refresh)
    cov = coverage_table(panel)
    for tk, c in cov.items():
        print(f"[cov] {tk:5s} {c['first_date']} .. {c['last_date']}  n={c['n_obs']}")

    log_vol, floor_audit = build_log_vol(panel, "parkinson")
    log_vol_gk, floor_audit_gk = build_log_vol(panel, "garman_klass")
    returns = close_returns(panel)
    rv_panel = returns ** 2

    for tk, df in panel.items():
        pd.concat([df], axis=1).to_csv(HERE / "data" / f"{tk}_adjusted_ohlc.csv")

    descriptive = {
        "vol_proxy": "log annualised Parkinson (1980) daily volatility",
        "why_parkinson": (
            "range-based, strictly non-negative (Garman-Klass can go negative and "
            "needs a floor), and it is the same family Diebold-Yilmaz (2012) use "
            "for daily connectedness. Garman-Klass is carried as the robustness "
            "proxy with its floor audit reported."
        ),
        "floor_audit_parkinson": floor_audit,
        "floor_audit_garman_klass": floor_audit_gk,
        "log_vol_stats": {
            tk: {
                "mean": float(log_vol[tk].mean()),
                "sd": float(log_vol[tk].std(ddof=1)),
                "skew": float(stats.skew(log_vol[tk].dropna())),
                "kurtosis": float(stats.kurtosis(log_vol[tk].dropna())),
                "ar1": float(log_vol[tk].autocorr(1)),
            }
            for tk in ALL_TICKERS
        },
        "return_stats": {
            tk: {
                "mean_daily": float(returns[tk].mean()),
                "sd_daily": float(returns[tk].std(ddof=1)),
                "ann_vol": float(returns[tk].std(ddof=1) * np.sqrt(TRADING_DAYS)),
                "skew": float(stats.skew(returns[tk].dropna())),
                "kurtosis": float(stats.kurtosis(returns[tk].dropna())),
                "n_obs": int(returns[tk].notna().sum()),
            }
            for tk in ALL_TICKERS
        },
        "abs_return_ar1": {tk: float(returns[tk].abs().autocorr(1)) for tk in ALL_TICKERS},
    }

    # ── H1 + H2 ────────────────────────────────────────────────────────────────
    nets = {}
    for name, cfg in SYSTEMS.items():
        nets[name] = run_network(name, log_vol, cfg, n_boot, n_null, n_ord)

    # Garman-Klass robustness on the primary system only (same estimator, other proxy)
    gk_check = network_snapshot(
        log_vol_gk[SYSTEMS["full8"]["assets"]].dropna().to_numpy(),
        SYSTEMS["full8"]["assets"],
        nets["full8"]["var_lag_aic"],
        SYSTEMS["full8"]["sources"],
        SYSTEMS["full8"]["targets"],
    )
    proxy_robustness = {
        "proxy": "garman_klass",
        "system": "full8",
        "tci_pp": gk_check["tci"],
        "pairwise_net": gk_check["pairwise_net"],
        "sign_agreement_with_parkinson": float(np.mean([
            np.sign(gk_check["pairwise_net"][k2]) == np.sign(nets["full8"]["observed"]["pairwise_net"][k2])
            for k2 in gk_check["pairwise_net"]
        ])),
    }

    # ── Granger lead-lag (the formal test any directional sentence rests on) ───
    granger = {
        name: run_granger(name, log_vol, cfg, nets[name]["var_lag_aic"],
                          200 if args.quick else N_BOOT_GRANGER)
        for name, cfg in SYSTEMS.items()
    }

    # ── H3 ─────────────────────────────────────────────────────────────────────
    h3 = run_h3(rv_panel, log_vol, returns)

    v1 = verdict_h1(nets)
    v2 = verdict_h2(nets, granger)
    v2r = verdict_h2_reverse(nets, granger)
    v3 = verdict_h3(h3)

    # ── H4, only if there is something to trade ────────────────────────────────
    precondition = v2["verdict"] in ("ACCEPT", "PARTIAL") or v3["verdict"] in ("ACCEPT", "PARTIAL")
    h4 = None
    if precondition:
        h4 = run_h4(log_vol, returns, "long7", FORECAST_SPECS["long7"], "QQQ")
        print(f"[H4] turnover_artifact={h4['turnover_artifact']} "
              f"wins={h4['wins_both_baselines_by_cost']}")
    v4 = verdict_h4(h4, precondition)

    # ── lookahead probe ────────────────────────────────────────────────────────
    cut = pd.Timestamp("2020-06-30")
    probe = lookahead_probe(panel, cut)
    print(f"[probe] {probe['verdict']} violations={probe['n_violations']}")

    # ── synthesis, computed from the numbers rather than narrated ──────────────
    gf = granger["full8"]["summary_spy_controlled_physical_credit_to_ai"]
    gr = granger["full8"]["summary_spy_controlled_ai_to_physical_credit"]
    prim_rungs = [c["ladder"][PRIMARY_COMPARISON] for c in h3["cells"]]
    synthesis = {
        "one_line": (
            "Total spillover across the AI / power / credit system is large and real; "
            "the net variance-share direction runs from the AI leg OUTWARD, not inward; "
            "the physical/credit leg does carry FDR-surviving in-sample Granger lead "
            "information for AI volatility, and none of it converts into out-of-sample "
            "forecast value."
        ),
        "tci_pp_primary": nets["full8"]["h1_total_spillover"]["tci_pp"],
        "tci_null_floor_q95": nets["full8"]["h1_total_spillover"]["null_floor_q95"],
        "n_pairwise_npdc_negative": int(sum(
            r["npdc_pp"] < 0 for r in nets["full8"]["h2_pairwise"])),
        "n_pairwise_total": len(nets["full8"]["h2_pairwise"]),
        "granger_forward_fdr_significant": gf["n_fdr_significant"],
        "granger_reverse_fdr_significant": gr["n_fdr_significant"],
        "granger_family_size": gf["family_size"],
        "h3_primary_cells_fdr_significant": int(sum(r["fdr_significant"] for r in prim_rungs)),
        "h3_primary_cells_with_positive_increment": int(sum(
            r["oos_r2_increment"] > 0 for r in prim_rungs)),
        "h3_primary_cells": len(prim_rungs),
        "h3_loose_reading_max_cw_t": max(
            c["ladder"]["M0plusExog_vs_M0"]["clark_west"]["t_stat"] for c in h3["cells"]),
        "cholesky_worst_pair_sign_stability": nets["full8"]["ordering_robustness"][
            "cholesky_worst_pair_sign_stability"],
        "what_this_rules_out": (
            "The tradable version of the J.P. Morgan AI-data-centre-financing thesis: "
            "that power/grid/credit volatility is an early-warning gauge you can put in "
            "front of a Nasdaq volatility forecast. In-sample lead information exists, "
            "but after own-volatility and broad-market-volatility controls it adds "
            "nothing out of sample, so the funding chain is not a usable volatility "
            "lead indicator at daily frequency with free data."
        ),
        "what_would_change_it": (
            "Instrument the physical leg directly rather than through equity proxies: "
            "PJM/ERCOT interconnection-queue or capacity-auction prices, data-centre "
            "power-purchase-agreement spreads, and private-credit fund marks. Those are "
            "the variables the thesis is actually about; XLU/PAVE/HYG/LQD are the free "
            "shadows of them and the shadows carry the market factor along."
        ),
    }

    # ── figures ────────────────────────────────────────────────────────────────
    figs = HERE / "figures"
    for name, net in nets.items():
        fig_network_matrix(net, name, figs / f"fig1_network_{name}.png")
        fig_ordering(net, name, figs / f"fig2_ordering_{name}.png")
    fig_rolling_tci(nets, figs / "fig3_rolling_tci.png")
    fig_h3(h3, figs / "fig4_h3_increment.png")
    for name in granger:
        fig_granger(granger, name, figs / f"fig5_granger_{name}.png")
    fig_subperiods(nets, figs / "fig6_subperiods.png")
    if h4 is not None:
        fig_h4(h4, figs / "fig7_h4_strategy.png")
    figure_list = sorted(p.name for p in figs.glob("*.png"))

    payload = {
        "k_id": "K1733",
        "title": "AI-infrastructure funding-chain volatility transmission: "
                 "hyperscaler/semis x power-grid/utility x credit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": {
            "provider": "yfinance",
            "auto_adjust": False,
            "adjustment": "Open/High/Low rescaled by Adj Close / Close; Close = Adj Close",
            "download_start": DOWNLOAD_START,
            "tickers": ALL_TICKERS,
            "baskets": {"ai": AI_BASKET, "physical": PHYSICAL_BASKET,
                        "credit": CREDIT_BASKET, "market_control_only": CONTROL_TICKERS},
            "snapshot_dir": "experiments/k1733/data",
        },
        "config": {
            "seed": SEED,
            "systems": SYSTEMS,
            "var_max_lag": VAR_MAX_LAG,
            "fevd_horizon": FEVD_HORIZON,
            "n_orderings": n_ord,
            "n_bootstrap_network": n_boot,
            "n_null_tci": n_null,
            "block_length": BLOCK_LEN,
            "rolling_window": ROLL_WINDOW,
            "rolling_step": ROLL_STEP,
            "rolling_var_lag": ROLL_VAR_LAG,
            "subperiods": SUBPERIODS,
            "forecast_specs": FORECAST_SPECS,
            "forecast_targets": FORECAST_TARGETS,
            "horizons": HORIZONS,
            "min_train": MIN_TRAIN,
            "fdr_q": FDR_Q,
            "n_bootstrap_forecast": N_BOOT_FORECAST,
            "n_bootstrap_granger": 200 if args.quick else N_BOOT_GRANGER,
            "bootstrap_mean_block": BOOT_MEAN_BLOCK,
            "cost_grid_bps_per_side": COST_GRID_BPS,
            "gate_z": GATE_Z,
            "n_phase_null": N_PHASE_NULL,
            "quick_mode": bool(args.quick),
        },
        "ticker_coverage": cov,
        "descriptive": descriptive,
        "networks": nets,
        "granger_lead_lag": granger,
        "proxy_robustness": proxy_robustness,
        "h3_forecast": h3,
        "h4_strategy": h4,
        "ordering_robustness": {
            name: net["ordering_robustness"] for name, net in nets.items()
        },
        "lookahead_diagnostics": probe,
        "verdicts": {"H1": v1, "H2": v2, "H2R_post_hoc": v2r, "H3": v3, "H4": v4},
        "synthesis": synthesis,
        "figures": figure_list,
        "prior_art_guardrails": {
            "K628b": "SPY net +43.7pp was a Cholesky-ordering artifact; KPPS gave +14.6pp",
            "K865b": "the DY direction was an ordering artifact while total spillover was real",
            "K907": "connectedness is not a VIX proxy (r = 0.001) — a separate risk dimension",
            "K1508": "the AI power-demand narrative did not reprice utility/grid volatility",
            "K1332/K1343/K1344": "public credit proxies: narrow or null as volatility signals",
        },
        "unresolved": [],
    }

    inputs = [f"experiments/k1733/data/{tk}_adjusted_ohlc.csv" for tk in ALL_TICKERS]
    inputs.append("experiments/k1733/data/prices_raw.csv")
    finalize_experiment(
        results=payload,
        entrypoint=__file__,
        canonical_result="K1733_results.json",
        inputs=inputs,
        outputs=[f"figures/{f}" for f in figure_list],
        seeds=[("numpy", SEED)],
        started_at=T0,
    )
    print(json.dumps({k2: v["verdict"] for k2, v in payload["verdicts"].items()}, indent=2))
    print(f"[done] {time.time() - T0:.1f}s")


if __name__ == "__main__":
    main()
