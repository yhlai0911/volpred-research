"""K1025 v3 — Crypto fear channel: corrected Diebold-Yilmaz connectedness.

WHY v3 EXISTS
-------------
`k1025_v2.py:368` computed the Diebold-Yilmaz spillover matrix as
``fevd.decomp[-1]``, annotating the array as ``(horizon, n_vars, n_vars)``.
statsmodels' ``FEVD.decomp`` is actually ``(n_vars, horizon, n_vars)``, so
``decomp[-1]`` returns the LAST VARIABLE's (horizon, n) table -- forecast
horizon steps were read as assets. Every DY number in v2 (total spillover
90.11%, BTC net receiver -76.89) is an artifact of that mis-slice: the same
formula returns ~90% on pure iid noise, because the "diagonal" of the
mis-sliced matrix is no longer own-variance.

v3 fixes the slice (``decomp[:, -1, :]``) and, because the Cholesky FEVD is
order-dependent and the paper's headline ("BTC is a fear amplifier, not an
originator") is a claim about NET DIRECTION, promotes the order-invariant
KPPS generalized FEVD (Koop-Pesaran-Potter 1996; Pesaran-Shin 1998) to the
primary estimator, with two Cholesky orderings retained as sensitivity.

Additional corrections over v2 (each is a separate defect, see README):
  * SPY returns were simple, BTC log -> both are log returns now.
  * Data now comes from the pinned snapshot CSV, never a live yfinance fetch.
  * Weekend-NaN alignment bug (see `build_panel`): prices are dropna'd BEFORE
    differencing, not after. Doing it the other way silently deletes Mondays.
  * The OOS AR lag grid is extended to 22; the FEVD VAR keeps the paper's
    pre-specified maxlags=5 so the estimator correction is not confounded with
    an unrequested lag-grid change.
  * Quantile regression gains a lagged-VIX control (quantile-Granger form) and
    a moving-block bootstrap, since an iid bootstrap on a persistent series
    understates the standard error.
  * Nested OOS comparison reports Clark-West alongside raw DM (raw DM is
    biased against the larger model under the null -- docs/error_log.md
    2026-07-11, K1681).

Usage:
    uv run --extra dev python experiments/k1025/k1025_v3.py
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.quantile_regression import QuantReg
from statsmodels.tools.sm_exceptions import IterationLimitWarning
from statsmodels.tsa.api import VAR
from statsmodels.tsa.ar_model import AutoReg
from statsmodels.tsa.stattools import adfuller

from volpred.stats.model_evaluation import dm_test  # canonical DM + Newey-West HAC

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SEED = 42
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
# Pinned snapshot (auto_adjust=False vintage -> *_adj_close columns). Never fetch live:
# the paper's replication package must reproduce bit-for-bit. See paper-workflow rules.
SNAPSHOT = REPO_ROOT / "paper" / "crypto-fear-channel" / "data" / "spy_btc_usd_vix_2015-2026.csv"

RV_WINDOW = 20  # trading days, matches v2 and the manuscript
ANNUALIZE = np.sqrt(252)
FEVD_HORIZON = 10
VAR_MAXLAGS_FULL = 5  # preserve the paper/v2 FEVD specification; AR_MAXLAGS below is the 22-lag extension
ROLL_WINDOW = 252  # preserve the paper/v2 rolling specification (512 windows on the pinned snapshot)
ROLL_STEP = 5
ROLL_MAXLAGS = 5  # 22 lags on a 252-obs window is 67 params/eq -- too parameter-heavy
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)
N_BOOT = 1_000  # experiment preamble minimum for bootstrap inference
QR_MAX_ITER = 5_000
MIN_BOOT_SUCCESS_RATE = 0.95
OOS_START = "2019-01-01"
IS_END = "2018-12-31"
AR_MAXLAGS = 22  # v2 capped at 10
ROLL_TRAIN = 756
VAR_NAMES = ("BTC_RV", "SPY_RV", "VIX")
# The window the manuscript reports, so the v2/v3 before-after is on a common span.
PAPER_WINDOW_END = "2026-04-08"


# ----------------------------------------------------------------------------
# 1. Data
# ----------------------------------------------------------------------------
def build_panel(alignment: str = "trading_day") -> pd.DataFrame:
    """Build the BTC_RV / SPY_RV / VIX panel from the pinned snapshot.

    The snapshot is on a CALENDAR index: BTC trades every day, SPY and VIX only
    on exchange days, so weekend rows carry NaN for the equity columns. Taking a
    return on that index directly (``series.pct_change()``) makes Monday's return
    NaN -- its previous CALENDAR row is Sunday, which is NaN -- and the
    subsequent dropna deletes almost every Monday (measured on this snapshot:
    543 Mondays -> 12). That is a ~19% sample loss concentrated on the single
    weekday that carries the weekend's news, and it is silent.

    So: drop NaNs on the price level FIRST, then difference.

    alignment:
      "trading_day" (primary) -- restrict prices to the common exchange calendar,
          THEN take log returns. BTC's Monday return therefore spans Fri->Mon,
          exactly like SPY's. No BTC weekend information is discarded.
      "calendar" (sensitivity) -- take BTC log returns on its own 7-day calendar,
          then subset to exchange days. BTC's Monday return spans Sun->Mon and
          the weekend move is dropped. This is v2's convention; it is reported as
          a robustness row to show the connectedness result is not an artifact of
          the alignment choice.
    """
    if alignment not in {"trading_day", "calendar"}:
        raise ValueError(f"unknown alignment: {alignment!r}")

    raw = pd.read_csv(SNAPSHOT, parse_dates=["date"], index_col="date").sort_index()

    btc_px = raw["btc_usd_adj_close"].dropna()
    spy_px = raw["spy_adj_close"].dropna()
    vix_lv = raw["vix_adj_close"].dropna()

    # Exchange calendar = days on which BOTH equity series exist and BTC has a price.
    exch = spy_px.index.intersection(vix_lv.index).intersection(btc_px.index)

    if alignment == "trading_day":
        btc_ret = np.log(btc_px.loc[exch] / btc_px.loc[exch].shift(1)).dropna()
    else:
        btc_ret = np.log(btc_px / btc_px.shift(1)).dropna().reindex(exch).dropna()

    # v2 used a SIMPLE return for SPY and a LOG return for BTC. Both are log here.
    spy_ret = np.log(spy_px.loc[exch] / spy_px.loc[exch].shift(1)).dropna()

    idx = btc_ret.index.intersection(spy_ret.index)
    btc_rv = (btc_ret.loc[idx].rolling(RV_WINDOW).std() * ANNUALIZE).dropna()
    spy_rv = (spy_ret.loc[idx].rolling(RV_WINDOW).std() * ANNUALIZE).dropna()

    panel = pd.DataFrame(
        {"BTC_RV": btc_rv, "SPY_RV": spy_rv, "VIX": vix_lv, "BTC_RET": btc_ret, "SPY_RET": spy_ret}
    ).dropna()
    return panel


# ----------------------------------------------------------------------------
# 2. FEVD / connectedness
# ----------------------------------------------------------------------------
def cholesky_fevd(res, horizon: int = FEVD_HORIZON) -> np.ndarray:
    """Orthogonalized (Cholesky) FEVD at the final horizon: (n, n), row=eq, col=shock.

    THE v2 BUG LIVED HERE. `decomp` is (n_vars, horizon, n_vars); `decomp[-1]`
    picks the last VARIABLE, not the last horizon. The assert makes a future
    statsmodels axis change fail loudly instead of silently returning garbage.
    """
    n = res.neqs
    decomp = res.fevd(horizon).decomp
    assert decomp.shape == (n, horizon, n), (
        f"statsmodels FEVD.decomp shape is {decomp.shape}, expected {(n, horizon, n)} "
        "= (variable, horizon, shock). The final-horizon table is decomp[:, -1, :]."
    )
    return decomp[:, -1, :]


def generalized_fevd(res, horizon: int = FEVD_HORIZON) -> np.ndarray:
    """KPPS generalized FEVD (Koop-Pesaran-Potter 1996; Pesaran-Shin 1998).

        theta_ij(H) = sigma_jj^-1 * sum_h (e_i' A_h Sigma e_j)^2
                                  / sum_h (e_i' A_h Sigma A_h' e_i)

    Shocks are not orthogonalized, so the result does NOT depend on the ordering
    of the variables -- which is exactly why it, not Cholesky, carries the paper's
    net-direction claim. Rows do not sum to 1 pre-normalisation; the caller
    row-normalises (standard DY 2012 treatment).
    """
    sigma = np.asarray(res.sigma_u)
    phi = res.ma_rep(maxn=horizon - 1)  # (horizon, n, n), phi[0] = I
    assert phi.shape[0] == horizon, f"ma_rep returned {phi.shape[0]} steps, expected {horizon}"

    sig_jj = np.diag(sigma)
    num = np.zeros_like(sigma)
    den = np.zeros(sigma.shape[0])
    for h in range(horizon):
        a_sigma = phi[h] @ sigma
        num += a_sigma**2  # (i,j) = (e_i' A_h Sigma e_j)^2
        den += np.diag(a_sigma @ phi[h].T)  # (i)   = e_i' A_h Sigma A_h' e_i

    return (num / sig_jj[None, :]) / den[:, None]


def connectedness(matrix: np.ndarray, names=VAR_NAMES) -> dict:
    """Diebold-Yilmaz (2012) connectedness table from a raw FEVD matrix.

    Row i = share of variable i's forecast-error variance from each shock j, so
    the ROW (ex-diagonal) is what i RECEIVES and the COLUMN (ex-diagonal) is what
    j TRANSMITS. v2 had these two labels swapped on top of the slicing bug.
    """
    m = matrix / matrix.sum(axis=1, keepdims=True)  # rows -> 1
    n = m.shape[0]
    off_diag = m.sum() - np.trace(m)
    from_ = (m.sum(axis=1) - np.diag(m)) * 100.0  # received by i
    to_ = (m.sum(axis=0) - np.diag(m)) * 100.0  # transmitted by j
    return {
        "total_connectedness": float(off_diag / n * 100.0),
        "matrix": {names[i]: {names[j]: float(m[i, j] * 100.0) for j in range(n)} for i in range(n)},
        "from_others": {names[i]: float(from_[i]) for i in range(n)},
        "to_others": {names[i]: float(to_[i]) for i in range(n)},
        "net": {names[i]: float(to_[i] - from_[i]) for i in range(n)},
    }


def fit_var(data: pd.DataFrame, maxlags: int):
    """Fit a VAR with an AIC-selected lag. Returns (results, chosen_lag)."""
    model = VAR(data)
    lag = int(max(model.select_order(maxlags=maxlags).aic, 1))
    return model.fit(lag), lag


def buggy_v2_index(res, horizon: int = FEVD_HORIZON) -> float:
    """Reproduce v2's mis-sliced total spillover, so the before/after is MEASURED, not asserted.

    The value this returns is a diagnostic of the error's size. It must never be
    reported as a connectedness estimate.
    """
    n = res.neqs
    bad = res.fevd(horizon).decomp[-1][:n]  # fevd-bug-reproduction: v2's (horizon, n) read as (n, n)
    m = bad / bad.sum(axis=1, keepdims=True)
    return float((m.sum() - np.trace(m)) / n * 100.0)


# ----------------------------------------------------------------------------
# 3. Quantile regression with a moving-block bootstrap
# ----------------------------------------------------------------------------
def moving_block_indices(n: int, block_len: int, rng: np.random.Generator) -> np.ndarray:
    """Moving-block bootstrap (Kunsch 1989): resample overlapping blocks of rows.

    An iid row bootstrap (v2) assumes exchangeable observations. VIX and RV are
    strongly persistent, so iid resampling destroys the dependence and shrinks the
    bootstrap SE -- i.e. it manufactures significance. Blocks preserve it.
    """
    n_blocks = int(np.ceil(n / block_len))
    starts = rng.integers(0, n - block_len + 1, size=n_blocks)
    return np.concatenate([np.arange(s, s + block_len) for s in starts])[:n]


def quantile_regression(y: pd.Series, x: pd.DataFrame, block_len: int, key: str) -> dict:
    """QR of y on x at each tau, with moving-block bootstrap CIs (seed fixed)."""
    x_c = sm.add_constant(x)
    n = len(y)
    out = {}
    for tau in QUANTILES:
        with warnings.catch_warnings():
            warnings.simplefilter("error", IterationLimitWarning)
            fitted = QuantReg(y, x_c).fit(q=tau, max_iter=QR_MAX_ITER)
        beta = float(fitted.params[key])

        rng = np.random.default_rng(SEED)  # same block draws across taus -> comparable CIs
        boot = []
        failed = 0
        for _ in range(N_BOOT):
            idx = moving_block_indices(n, block_len, rng)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", IterationLimitWarning)
                    b = QuantReg(y.iloc[idx], x_c.iloc[idx]).fit(q=tau, max_iter=QR_MAX_ITER)
                boot.append(float(b.params[key]))
            except Exception:  # noqa: BLE001
                # A resample can be rank-deficient or fail to converge. Count it;
                # never let an IterationLimitWarning masquerade as a successful draw.
                failed += 1
        boot_arr = np.asarray(boot)
        min_ok = int(np.ceil(N_BOOT * MIN_BOOT_SUCCESS_RATE))
        if len(boot_arr) < min_ok:
            raise RuntimeError(
                f"QR bootstrap tau={tau} retained {len(boot_arr)}/{N_BOOT} draws; "
                f"minimum required is {min_ok}."
            )
        if failed:
            print(f"    [warn] QR bootstrap tau={tau}: excluded {failed}/{N_BOOT} failed draws")
        lo, hi = np.percentile(boot_arr, [2.5, 97.5])
        se = float(boot_arr.std(ddof=1))
        out[f"{tau:.2f}"] = {
            "beta": beta,
            "se_block_boot": se,
            "ci_lo": float(lo),
            "ci_hi": float(hi),
            "t_stat": float(beta / se) if se > 0 else 0.0,
            "significant_5pct": bool(lo > 0 or hi < 0),
            "n_boot_ok": int(len(boot_arr)),
            "n_boot_failed": int(failed),
        }
    return out


# ----------------------------------------------------------------------------
# 4. HAC / DM helpers
# ----------------------------------------------------------------------------
def hac_bandwidth(n: int, h: int = 1) -> int:
    """Rule from .claude/rules/experiments.md: max(h-1, canonical), canonical =
    ceil(h^(1/3) * n^(1/3)) -- the same bandwidth volpred's dm_test uses. At h=1 a
    naive `h-1` gives ZERO lags, i.e. no HAC at all; the canonical rule floors it."""
    canonical = int(np.ceil(h ** (1 / 3) * n ** (1 / 3)))
    return max(1, max(h - 1, min(canonical, n // 4)))


def hac_tstat(d: np.ndarray, h: int = 1) -> tuple[float, int]:
    """Newey-West t-stat for mean(d) = 0. Used ONLY for Clark-West, which the
    canonical dm_test does not implement. Its bandwidth is the canonical rule, and
    `test_mean_zero_matches_canonical_dm` pins it against dm_test so this cannot
    silently drift away from the repo standard."""
    d = np.asarray(d, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return 0.0, 0
    mu = d.mean()
    max_lag = hac_bandwidth(n, h)
    var = np.mean((d - mu) ** 2)
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        var += 2 * w * np.mean((d[lag:] - mu) * (d[:-lag] - mu))
    if var <= 0:
        return 0.0, max_lag
    return float(mu / np.sqrt(var / n)), max_lag


def clark_west(y: np.ndarray, pred_small: np.ndarray, pred_big: np.ndarray, h: int = 1) -> dict:
    """Clark & West (2007) MSPE-adjusted statistic for NESTED models.

    Under the null (BTC's coefficient is zero in population) the larger model still
    estimates an extra parameter, so its MSPE is biased UP: raw DM systematically
    favours the small model and cannot be read as evidence of "no predictive
    content" (docs/error_log.md 2026-07-11, K1681). CW removes that bias term.

    Read them as different questions: CW asks "does BTC carry information?";
    raw DM asks "does adding BTC actually forecast better in this sample?".
    """
    e_small = y - pred_small
    e_big = y - pred_big
    f = e_small**2 - (e_big**2 - (pred_small - pred_big) ** 2)
    t, lag = hac_tstat(f, h)
    return {"cw_t": t, "cw_hac_lag": lag, "cw_mean_adj": float(np.mean(f))}


def acf1(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)] - np.mean(x[np.isfinite(x)])
    if len(x) < 3 or np.all(x == 0):
        return 0.0
    return float(np.corrcoef(x[1:], x[:-1])[0, 1])


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> dict:
    np.random.seed(SEED)
    results: dict = {
        "experiment_id": "k1025_v3",
        "supersedes": "k1025_v2_results.json",
        "seed": SEED,
        "data_source": {
            "snapshot": str(SNAPSHOT.relative_to(REPO_ROOT)),
            "live_fetch": False,
            "price_column_vintage": "auto_adjust=False (*_adj_close)",
            "returns": "log returns for BOTH SPY and BTC (v2 mixed simple/log)",
        },
    }

    print("=" * 78)
    print("K1025 v3 — corrected Diebold-Yilmaz connectedness (crypto fear channel)")
    print("=" * 78)

    # ---- 1. Data ------------------------------------------------------------
    print("\n[1/7] Building panel from pinned snapshot...")
    panel = build_panel("trading_day")
    panel_cal = build_panel("calendar")
    var_data = panel[list(VAR_NAMES)]
    print(f"  N = {len(var_data)}  ({var_data.index[0].date()} .. {var_data.index[-1].date()})")
    print(f"  calendar-alignment variant: N = {len(panel_cal)}")

    results["data"] = {
        "n_obs": int(len(var_data)),
        "start": str(var_data.index[0].date()),
        "end": str(var_data.index[-1].date()),
        "alignment_primary": "trading_day",
        "n_obs_calendar_variant": int(len(panel_cal)),
        "descriptive_stats": {
            c: {
                "mean": float(var_data[c].mean()),
                "std": float(var_data[c].std()),
                "min": float(var_data[c].min()),
                "max": float(var_data[c].max()),
            }
            for c in VAR_NAMES
        },
    }

    # ---- 2. Stationarity ----------------------------------------------------
    print("\n[2/7] ADF tests (levels)...")
    adf = {}
    for c in VAR_NAMES:
        stat, pval = adfuller(var_data[c].dropna(), autolag="AIC")[:2]
        adf[c] = {"adf_stat": float(stat), "p_value": float(pval), "stationary_5pct": bool(pval < 0.05)}
        print(f"  {c:8s} ADF={stat:8.3f}  p={pval:.4f}  {'stationary' if pval < 0.05 else 'UNIT ROOT'}")
    results["adf_levels"] = adf

    # ---- 3. Full-sample connectedness --------------------------------------
    print(f"\n[3/7] Full-sample connectedness (VAR lag by AIC, maxlags={VAR_MAXLAGS_FULL})...")
    res_var, lag = fit_var(var_data, VAR_MAXLAGS_FULL)
    print(f"  AIC-selected VAR lag = {lag}")

    gen = connectedness(generalized_fevd(res_var))
    chol_a = connectedness(cholesky_fevd(res_var))  # order as VAR_NAMES: BTC, SPY, VIX
    order_b = ["VIX", "SPY_RV", "BTC_RV"]
    res_b, lag_b = fit_var(var_data[order_b], VAR_MAXLAGS_FULL)
    chol_b = connectedness(cholesky_fevd(res_b), names=tuple(order_b))
    v2_bug = buggy_v2_index(res_var)

    print(f"  Generalized (KPPS)  total = {gen['total_connectedness']:.2f}%   "
          f"BTC net = {gen['net']['BTC_RV']:+.2f}pp")
    print(f"  Cholesky {{BTC,SPY,VIX}} total = {chol_a['total_connectedness']:.2f}%   "
          f"BTC net = {chol_a['net']['BTC_RV']:+.2f}pp")
    print(f"  Cholesky {{VIX,SPY,BTC}} total = {chol_b['total_connectedness']:.2f}%   "
          f"BTC net = {chol_b['net']['BTC_RV']:+.2f}pp")
    print(f"  [v2 mis-sliced index on the SAME fit: {v2_bug:.2f}%]")

    # Order-invariance check: permuting the columns must not move the generalized table.
    perm = ["SPY_RV", "VIX", "BTC_RV"]
    res_p, _ = fit_var(var_data[perm], VAR_MAXLAGS_FULL)
    gen_p = connectedness(generalized_fevd(res_p), names=tuple(perm))
    gen_order_gap = abs(gen["total_connectedness"] - gen_p["total_connectedness"])
    chol_order_gap = abs(chol_a["total_connectedness"] - chol_b["total_connectedness"])
    chol_net_gap = abs(chol_a["net"]["BTC_RV"] - chol_b["net"]["BTC_RV"])
    print(f"  order sensitivity: generalized {gen_order_gap:.3f}pp vs Cholesky {chol_order_gap:.3f}pp "
          f"(BTC net swing across orderings: {chol_net_gap:.2f}pp)")

    results["connectedness_full_sample"] = {
        "var_lag_aic": lag,
        "var_maxlags_grid": VAR_MAXLAGS_FULL,
        "fevd_horizon": FEVD_HORIZON,
        "generalized_kpps": gen,
        "cholesky_btc_spy_vix": chol_a,
        "cholesky_vix_spy_btc": chol_b,
        "generalized_permuted_check": {
            "order": perm,
            "total_connectedness": gen_p["total_connectedness"],
            "net": gen_p["net"],
            "total_gap_vs_primary_pp": float(gen_order_gap),
        },
        "order_sensitivity": {
            "generalized_total_gap_pp": float(gen_order_gap),
            "cholesky_total_gap_pp": float(chol_order_gap),
            "cholesky_btc_net_gap_pp": float(chol_net_gap),
        },
        "v2_bug_reproduction": {
            "mis_sliced_total_connectedness": v2_bug,
            "note": "decomp[-1] on the SAME VAR fit; v2 reported 90.11%",
        },
    }

    # ---- 3b. Robustness: lag grid, differences, alignment, paper window -----
    print("\n[3b] Robustness of the total connectedness index...")
    lag_sens = {}
    for lg in (1, 2, 5, 10, 22):
        r = VAR(var_data).fit(lg)
        lag_sens[str(lg)] = {
            "generalized_total": connectedness(generalized_fevd(r))["total_connectedness"],
            "generalized_btc_net": connectedness(generalized_fevd(r))["net"]["BTC_RV"],
        }
        print(f"  lag={lg:2d}: total={lag_sens[str(lg)]['generalized_total']:.2f}%  "
              f"BTC net={lag_sens[str(lg)]['generalized_btc_net']:+.2f}pp")

    diffs = var_data.diff().dropna()
    res_d, lag_d = fit_var(diffs, VAR_MAXLAGS_FULL)
    gen_d = connectedness(generalized_fevd(res_d))
    print(f"  first differences (v2's VAR input): total={gen_d['total_connectedness']:.2f}%  "
          f"BTC net={gen_d['net']['BTC_RV']:+.2f}pp  (lag={lag_d})")

    cal_data = panel_cal[list(VAR_NAMES)]
    res_c, lag_c = fit_var(cal_data, VAR_MAXLAGS_FULL)
    gen_c = connectedness(generalized_fevd(res_c))
    print(f"  calendar alignment:  total={gen_c['total_connectedness']:.2f}%  "
          f"BTC net={gen_c['net']['BTC_RV']:+.2f}pp")

    pw = var_data.loc[:PAPER_WINDOW_END]
    res_pw, lag_pw = fit_var(pw, VAR_MAXLAGS_FULL)
    gen_pw = connectedness(generalized_fevd(res_pw))
    print(f"  paper window (<= {PAPER_WINDOW_END}, n={len(pw)}): "
          f"total={gen_pw['total_connectedness']:.2f}%  BTC net={gen_pw['net']['BTC_RV']:+.2f}pp")

    results["connectedness_robustness"] = {
        "lag_sensitivity": lag_sens,
        "first_differences": {
            "var_lag_aic": lag_d,
            "total_connectedness": gen_d["total_connectedness"],
            "net": gen_d["net"],
        },
        "calendar_alignment": {
            "var_lag_aic": lag_c,
            "n_obs": int(len(cal_data)),
            "total_connectedness": gen_c["total_connectedness"],
            "net": gen_c["net"],
        },
        "paper_window": {
            "end": PAPER_WINDOW_END,
            "n_obs": int(len(pw)),
            "var_lag_aic": lag_pw,
            "total_connectedness": gen_pw["total_connectedness"],
            "net": gen_pw["net"],
        },
    }

    # ---- 4. Rolling connectedness ------------------------------------------
    print(f"\n[4/7] Rolling connectedness (window={ROLL_WINDOW}, step={ROLL_STEP}, "
          f"maxlags={ROLL_MAXLAGS})...")
    roll_rows = []
    data_b = var_data[order_b]
    for i in range(ROLL_WINDOW, len(var_data), ROLL_STEP):
        w = var_data.iloc[i - ROLL_WINDOW : i]
        wb = data_b.iloc[i - ROLL_WINDOW : i]
        window_end = var_data.index[i - 1]
        try:
            rw, lw = fit_var(w, ROLL_MAXLAGS)
            g = connectedness(generalized_fevd(rw))
            ca = connectedness(cholesky_fevd(rw))
            rb, _ = fit_var(wb, ROLL_MAXLAGS)
            cb = connectedness(cholesky_fevd(rb), names=tuple(order_b))
        except Exception as exc:  # noqa: BLE001
            print(f"    [warn] window ending {window_end.date()} failed: {exc}")
            continue
        roll_rows.append(
            {
                "date": str(window_end.date()),
                "lag": lw,
                "gen_total": g["total_connectedness"],
                "gen_net_btc": g["net"]["BTC_RV"],
                "gen_to_btc": g["to_others"]["BTC_RV"],
                "gen_from_btc": g["from_others"]["BTC_RV"],
                "chol_a_total": ca["total_connectedness"],
                "chol_a_net_btc": ca["net"]["BTC_RV"],
                "chol_b_total": cb["total_connectedness"],
                "chol_b_net_btc": cb["net"]["BTC_RV"],
            }
        )

    roll = pd.DataFrame(roll_rows)
    roll["dt"] = pd.to_datetime(roll["date"])
    peak = roll.loc[roll["gen_total"].idxmax()]
    covid = roll[(roll["dt"] >= "2020-02-01") & (roll["dt"] <= "2020-06-30")]
    calm = roll[(roll["dt"] >= "2017-01-01") & (roll["dt"] <= "2019-12-31")]
    net_recv_share = float((roll["gen_net_btc"] < 0).mean() * 100)
    sign_agree = float((np.sign(roll["chol_a_net_btc"]) == np.sign(roll["chol_b_net_btc"])).mean() * 100)

    print(f"  windows = {len(roll)}")
    print(f"  generalized total: mean={roll.gen_total.mean():.2f}%  sd={roll.gen_total.std():.2f}  "
          f"min={roll.gen_total.min():.2f}  max={roll.gen_total.max():.2f}")
    print(f"  peak {peak['gen_total']:.2f}% on {peak['date']}")
    print(f"  COVID (2020-02..06) mean = {covid.gen_total.mean():.2f}%  vs calm (2017-19) "
          f"= {calm.gen_total.mean():.2f}%")
    print(f"  BTC net receiver in {net_recv_share:.1f}% of windows")
    print(f"  two Cholesky orderings agree on BTC net SIGN in {sign_agree:.1f}% of windows")

    results["rolling_connectedness"] = {
        "window": ROLL_WINDOW,
        "step": ROLL_STEP,
        "maxlags": ROLL_MAXLAGS,
        "date_convention": "last observation included in each trailing window",
        "n_windows": int(len(roll)),
        "generalized_total": {
            "mean": float(roll.gen_total.mean()),
            "std": float(roll.gen_total.std()),
            "min": float(roll.gen_total.min()),
            "max": float(roll.gen_total.max()),
            "peak_date": str(peak["date"]),
            "peak_value": float(peak["gen_total"]),
        },
        "covid_2020H1_mean": float(covid.gen_total.mean()),
        "calm_2017_2019_mean": float(calm.gen_total.mean()),
        "btc_net_receiver_share_pct": net_recv_share,
        "cholesky_orderings_net_sign_agreement_pct": sign_agree,
        "series": roll.drop(columns=["dt"]).to_dict(orient="records"),
    }

    # ---- 5. Quantile regression --------------------------------------------
    block_len = int(np.ceil(len(var_data) ** (1 / 3)))
    print(f"\n[5/7] Quantile regression (moving-block bootstrap, B={N_BOOT}, "
          f"block={block_len}, seed={SEED})...")
    qr_df = pd.DataFrame(
        {
            "VIX": var_data["VIX"],
            "BTC_RV_lag1": var_data["BTC_RV"].shift(1),
            "VIX_lag1": var_data["VIX"].shift(1),
        }
    ).dropna()

    print("  (a) v2 spec: VIX_t ~ BTC_RV_{t-1}")
    qr_nc = quantile_regression(qr_df["VIX"], qr_df[["BTC_RV_lag1"]], block_len, "BTC_RV_lag1")
    for tau, v in qr_nc.items():
        print(f"    tau={tau}: beta={v['beta']:+8.4f}  CI=[{v['ci_lo']:+.3f}, {v['ci_hi']:+.3f}]  "
              f"{'SIG' if v['significant_5pct'] else 'ns'}")

    print("  (b) with lagged-VIX control: VIX_t ~ BTC_RV_{t-1} + VIX_{t-1}")
    qr_c = quantile_regression(
        qr_df["VIX"], qr_df[["BTC_RV_lag1", "VIX_lag1"]], block_len, "BTC_RV_lag1"
    )
    for tau, v in qr_c.items():
        print(f"    tau={tau}: beta={v['beta']:+8.4f}  CI=[{v['ci_lo']:+.3f}, {v['ci_hi']:+.3f}]  "
              f"{'SIG' if v['significant_5pct'] else 'ns'}")

    b05_nc, b95_nc = qr_nc["0.05"]["beta"], qr_nc["0.95"]["beta"]
    b05_c, b95_c = qr_c["0.05"]["beta"], qr_c["0.95"]["beta"]
    reversal_nc = bool(b05_nc < 0 < b95_nc)
    reversal_c = bool(b05_c < 0 < b95_c)
    # "Survives" = the sign flip is still there AND the negative low-tail slope is
    # actually distinguishable from zero. A flip built on an insignificant beta is
    # not a finding.
    reversal_c_sig = bool(reversal_c and qr_c["0.05"]["significant_5pct"] and qr_c["0.95"]["significant_5pct"])
    print(f"\n  sign reversal (beta<0 at tau=0.05, beta>0 at tau=0.95):")
    print(f"    without control: {reversal_nc}  (b05={b05_nc:+.3f}, b95={b95_nc:+.3f})")
    print(f"    with VIX control: {reversal_c}  (b05={b05_c:+.3f}, b95={b95_c:+.3f})  "
          f"both tails significant: {reversal_c_sig}")

    results["quantile_regression"] = {
        "spec": "VIX_t ~ BTC_RV_{t-1} [+ VIX_{t-1}]",
        "bootstrap": {
            "type": "moving_block",
            "B": N_BOOT,
            "block_length": block_len,
            "block_rule": "ceil(n^(1/3))",
            "seed": SEED,
            "max_iter": QR_MAX_ITER,
            "min_success_rate": MIN_BOOT_SUCCESS_RATE,
        },
        "n_obs": int(len(qr_df)),
        "no_control": qr_nc,
        "with_lagged_vix_control": qr_c,
        "sign_reversal": {
            "no_control": reversal_nc,
            "with_control": reversal_c,
            "with_control_both_tails_significant": reversal_c_sig,
            "survives": reversal_c_sig,
        },
    }

    # ---- 6. OOS forecasting + nested DM ------------------------------------
    print(f"\n[6/7] OOS forecast: AR(p) vs AR(p)+BTC_RV_lag1 (rolling {ROLL_TRAIN})...")
    fdict = {"VIX": var_data["VIX"], "BTC_RV_lag1": var_data["BTC_RV"].shift(1)}
    for lg in range(1, AR_MAXLAGS + 1):
        fdict[f"VIX_lag{lg}"] = var_data["VIX"].shift(lg)
    fdata = pd.DataFrame(fdict).dropna()

    is_data = fdata.loc[:IS_END]
    oos_data = fdata.loc[OOS_START:]
    # Every candidate must be compared on the SAME observations. AutoReg's
    # default hold_back=p silently gives AR(p) a different effective sample and
    # mechanically drove the old implementation to the upper grid boundary.
    ar_candidates = {
        p: AutoReg(is_data["VIX"], lags=p, hold_back=AR_MAXLAGS).fit()
        for p in range(1, AR_MAXLAGS + 1)
    }
    selection_nobs = {int(fit.nobs) for fit in ar_candidates.values()}
    assert len(selection_nobs) == 1, f"AR AIC candidates use unequal samples: {selection_nobs}"
    aic = {p: fit.aic for p, fit in ar_candidates.items()}
    ar_p = int(min(aic, key=aic.get))
    print(f"  IS n={len(is_data)}  OOS n={len(oos_data)}  AIC-selected AR order p={ar_p} "
          f"(grid 1..{AR_MAXLAGS})")

    ar_f = [f"VIX_lag{p}" for p in range(1, ar_p + 1)]
    ext_f = ar_f + ["BTC_RV_lag1"]
    pos = fdata.index.get_indexer(oos_data.index)

    pred_ar, pred_ext, actual, dates = [], [], [], []
    for rp in pos:
        train = fdata.iloc[max(0, rp - ROLL_TRAIN) : rp]  # strictly before rp -> no lookahead
        test = fdata.iloc[rp : rp + 1]
        if len(train) < ar_p + 2 or test.empty:
            continue
        y = train["VIX"].to_numpy()
        for feats, store in ((ar_f, pred_ar), (ext_f, pred_ext)):
            xtr = np.column_stack([np.ones(len(train)), train[feats].to_numpy()])
            beta, *_ = np.linalg.lstsq(xtr, y, rcond=None)
            xte = np.concatenate([[1.0], test[feats].to_numpy()[0]])
            store.append(float(xte @ beta))
        actual.append(float(test["VIX"].iloc[0]))
        dates.append(test.index[0])

    actual = np.asarray(actual)
    pred_ar = np.asarray(pred_ar)
    pred_ext = np.asarray(pred_ext)
    loss_ar = (actual - pred_ar) ** 2
    loss_ext = (actual - pred_ext) ** 2
    idx = pd.DatetimeIndex(dates)

    def dm_block(mask, label):
        n = int(mask.sum())
        if n < 30:
            return None
        la, le = loss_ar[mask], loss_ext[mask]
        d = le - la  # >0 => extended model worse
        t, p = dm_test(la, le, h=1)  # canonical: negative t => model 1 (AR) better
        # The local HAC engine (used for Clark-West, which dm_test does not provide) must
        # stay numerically identical to the canonical one. If it ever drifts, fail here
        # rather than quietly publishing a second, divergent DM variant.
        assert np.isclose(hac_tstat(d, h=1)[0], -t, atol=1e-8), (
            f"local hac_tstat diverged from canonical dm_test on {label}: "
            f"{hac_tstat(d, h=1)[0]:.6f} vs {-t:.6f}"
        )
        cw = clark_west(actual[mask], pred_ar[mask], pred_ext[mask], h=1)
        row = {
            "period": label,
            "n": n,
            "mse_ar": float(la.mean()),
            "mse_ext": float(le.mean()),
            "mse_improvement_pct": float((la.mean() - le.mean()) / la.mean() * 100),
            "loss_diff_acf1": acf1(d),
            "hac_lag": hac_bandwidth(n, 1),
            "dm_t_canonical": float(t),
            "dm_p_canonical": float(p),
            "dm_harvey_significant": bool(abs(t) > 3.0),
            **cw,
            "cw_significant_5pct": bool(cw["cw_t"] > 1.645),  # one-sided, per Clark-West
        }
        print(f"  {label:14s} n={n:5d}  dMSE={row['mse_improvement_pct']:+6.2f}%  "
              f"acf1(d)={row['loss_diff_acf1']:+.3f}  HAC lag={row['hac_lag']:2d}  "
              f"DM t={t:+6.2f}  CW t={cw['cw_t']:+6.2f}")
        return row

    subsamples = [
        ("full_oos", np.ones(len(idx), dtype=bool)),
        ("2019", (idx.year == 2019)),
        ("2020_covid", (idx.year == 2020)),
        ("2021_2022", (idx.year >= 2021) & (idx.year <= 2022)),
        ("2023_2026", (idx.year >= 2023)),
    ]
    dm_rows = [r for name, m in subsamples if (r := dm_block(np.asarray(m), name)) is not None]

    # Bandwidth sensitivity on the full OOS -- the rule requires reporting it.
    d_full = loss_ext - loss_ar
    lag_sens_dm = {}
    for lg in (0, 1, 5, hac_bandwidth(len(d_full), 1), 30):
        mu = d_full.mean()
        var = np.mean((d_full - mu) ** 2)
        for k in range(1, lg + 1):
            w = 1 - k / (lg + 1)
            var += 2 * w * np.mean((d_full[k:] - mu) * (d_full[:-k] - mu))
        lag_sens_dm[str(lg)] = float(mu / np.sqrt(var / len(d_full))) if var > 0 else 0.0

    print(f"  loss-differential acf(1) = {acf1(d_full):+.3f} -> HAC is "
          f"{'REQUIRED' if abs(acf1(d_full)) > 0.05 else 'near-innocuous'}; "
          f"DM |t| by bandwidth: {', '.join(f'{k}:{v:+.2f}' for k, v in lag_sens_dm.items())}")

    results["oos_forecast"] = {
        "spec": "VIX_t ~ AR(p) [+ BTC_RV_{t-1}], rolling window, one-step",
        "is_end": IS_END,
        "oos_start": OOS_START,
        "ar_order_aic": ar_p,
        "ar_maxlags_grid": AR_MAXLAGS,
        "ar_selection_hold_back": AR_MAXLAGS,
        "ar_selection_nobs": int(next(iter(selection_nobs))),
        "ar_selection_rule": "AIC on a common IS sample (AutoReg hold_back=AR_MAXLAGS)",
        "rolling_train_size": ROLL_TRAIN,
        "n_oos": int(len(actual)),
        "hac_rule": "max(h-1, ceil(h^(1/3)*n^(1/3))) — canonical volpred.stats dm_test bandwidth",
        "nested_models": True,
        "subsample_dm": dm_rows,
        "dm_bandwidth_sensitivity_full_oos": lag_sens_dm,
        "loss_diff_acf1_full_oos": acf1(d_full),
    }

    # ---- 7. Figure ----------------------------------------------------------
    print("\n[7/7] Rendering figure...")
    fig, axes = plt.subplots(3, 2, figsize=(16, 13))
    fig.suptitle(
        "K1025 v3 — Corrected Diebold-Yilmaz connectedness (BTC RV / SPY RV / VIX)\n"
        f"pinned snapshot, N={len(var_data)}, {var_data.index[0].date()}..{var_data.index[-1].date()}",
        fontsize=13,
        fontweight="bold",
    )

    ax = axes[0, 0]
    ax.plot(roll["dt"], roll["gen_total"], lw=1.2, color="#1f4e79", label="Generalized (KPPS)")
    ax.plot(roll["dt"], roll["chol_a_total"], lw=0.7, alpha=0.55, color="#c00000",
            label="Cholesky {BTC,SPY,VIX}")
    ax.axvspan(pd.Timestamp("2020-02-01"), pd.Timestamp("2020-06-30"), color="orange", alpha=0.18)
    ax.axhline(90.11, ls="--", lw=1, color="grey")
    ax.text(roll["dt"].iloc[len(roll) // 3], 91.5, "v2 reported 90.11% (mis-sliced)",
            fontsize=8, color="grey")
    ax.set_title(f"(a) Rolling total connectedness ({ROLL_WINDOW}d)", fontsize=11)
    ax.set_ylabel("Total connectedness (%)")
    ax.set_ylim(0, 100)
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(alpha=0.3)

    ax = axes[0, 1]
    ax.plot(roll["dt"], roll["gen_net_btc"], lw=1.2, color="#1f4e79", label="Generalized (KPPS)")
    ax.plot(roll["dt"], roll["chol_a_net_btc"], lw=0.8, alpha=0.7, color="#c00000",
            label="Cholesky {BTC,SPY,VIX}")
    ax.plot(roll["dt"], roll["chol_b_net_btc"], lw=0.8, alpha=0.7, color="#2e7d32",
            label="Cholesky {VIX,SPY,BTC}")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title("(b) BTC net connectedness — order dependence", fontsize=11)
    ax.set_ylabel("Net = TO − FROM (pp)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[1, 0]
    mat = np.array([[gen["matrix"][i][j] for j in VAR_NAMES] for i in VAR_NAMES])
    im = ax.imshow(mat, cmap="YlOrRd", vmin=0, vmax=100)
    ax.set_xticks(range(3), VAR_NAMES)
    ax.set_yticks(range(3), VAR_NAMES)
    ax.set_xlabel("Shock source (j)")
    ax.set_ylabel("Variance decomposed (i)")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{mat[i, j]:.1f}", ha="center", va="center",
                    color="white" if mat[i, j] > 55 else "black", fontsize=10)
    ax.set_title(f"(c) Generalized FEVD table — TCI = {gen['total_connectedness']:.1f}%", fontsize=11)
    fig.colorbar(im, ax=ax, fraction=0.046)

    ax = axes[1, 1]
    taus = [float(t) for t in qr_nc]
    for spec, res_qr, colr in (("no control", qr_nc, "#c00000"), ("+ VIX_{t-1}", qr_c, "#1f4e79")):
        betas = [res_qr[f"{t:.2f}"]["beta"] for t in taus]
        lo = [res_qr[f"{t:.2f}"]["ci_lo"] for t in taus]
        hi = [res_qr[f"{t:.2f}"]["ci_hi"] for t in taus]
        ax.plot(taus, betas, "o-", color=colr, label=spec)
        ax.fill_between(taus, lo, hi, color=colr, alpha=0.15)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title("(d) QR: β on BTC_RV$_{t-1}$ (moving-block CI)", fontsize=11)
    ax.set_xlabel("Quantile τ")
    ax.set_ylabel("β")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[2, 0]
    ax.plot(idx, np.cumsum(loss_ar - loss_ext), lw=1.2, color="#1f4e79")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title("(e) Cumulative SSE advantage of AR+BTC over AR\n(rising = BTC helps)", fontsize=11)
    ax.set_ylabel("Σ(loss$_{AR}$ − loss$_{AR+BTC}$)")
    ax.grid(alpha=0.3)

    ax = axes[2, 1]
    labs = [r["period"] for r in dm_rows]
    xs = np.arange(len(labs))
    ax.bar(xs - 0.2, [r["dm_t_canonical"] for r in dm_rows], 0.4, label="DM t (raw)", color="#c00000")
    ax.bar(xs + 0.2, [r["cw_t"] for r in dm_rows], 0.4, label="Clark-West t (nested)", color="#1f4e79")
    ax.axhline(3.0, ls="--", lw=1, color="grey")
    ax.axhline(-3.0, ls="--", lw=1, color="grey")
    ax.axhline(1.645, ls=":", lw=1, color="#1f4e79")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(xs, labs, rotation=20, fontsize=8)
    ax.set_title("(f) Subsample DM vs Clark-West (HAC)\ndashed = Harvey ±3.0, dotted = CW 5% one-sided",
                 fontsize=11)
    ax.set_ylabel("t-statistic")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")

    fig.tight_layout(rect=[0, 0, 1, 0.955])
    out_png = HERE / "k1025_v3_results.png"
    tmp_png = HERE / ".k1025_v3_results.tmp.png"
    fig.savefig(tmp_png, dpi=150)
    plt.close(fig)
    tmp_png.replace(out_png)
    print(f"  saved {out_png.name}")

    out_json = HERE / "k1025_v3_results.json"
    tmp_json = HERE / ".k1025_v3_results.tmp.json"
    tmp_json.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    # Parse the staged payload before replacing the canonical result. A killed run
    # must leave either the previous complete JSON or the new complete JSON, never
    # a truncated half-write.
    json.loads(tmp_json.read_text(encoding="utf-8"))
    tmp_json.replace(out_json)
    print(f"  saved {out_json.name}")
    return results


if __name__ == "__main__":
    main()
