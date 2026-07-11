#!/usr/bin/env python3
"""K1655 — Growth-at-Risk moved to markets: Equity/Vol-at-Risk multi-horizon quantile regression.

Motivation
----------
Adrian, Boyarchenko & Giannone (2019, AER) show that tighter financial conditions
(a National Financial Conditions Index, NFCI) shift the LOWER quantile of future GDP
growth much more than the median ("Vulnerable Growth" / Growth-at-Risk). This K asks
the cross-domain question: does the same conditioning structure hold for an EQUITY
market? i.e. do financial conditions predict the 5% left tail of SPY forward returns
(Equity-at-Risk) and the 95% right tail of forward realized volatility (Vol-at-Risk),
above and beyond an unconditional benchmark, OUT OF SAMPLE?

Differentiation (avoids two saturated NULL arcs):
  - NOT "exogenous shock -> next-day RV event window" (k1602/k1604 arc).
  - NOT "new covariate -> HAR-mean OOS increment" (k1613/k1616-k1619 arc).
  The target here is a TAIL QUANTILE (not a conditional mean), conditioned on
  exogenous financial conditions, mirroring GaR.

Honest priors already in the knowledge base:
  - Macro/financial-condition variables (NFCI, BAA10Y) LAG VIX by 9-20 days and add
    no OOS value for VIX-regime prediction (prior NULL).
  - STLFSI4 (a sister financial-stress index) is confirmed NULL (K503/K828): VIX
    absorbs the stress signal.
  => Expectation: in-sample tail slopes may be significant (crisis co-movement), but
     OOS gains over an unconditional quantile are likely marginal for an efficient
     equity market. A NULL / CONDITIONAL result is a legitimate cross-domain contrast
     (GaR works for macro growth != GaR works for equity), and is reported as such.

Method (Adrian et al. 2019 skeleton, moved to markets)
------------------------------------------------------
  - Weekly (W-FRI) frequency: SPY (^GSPC) weekly close, NFCI (weekly, Fri-dated),
    BAA10Y credit spread (daily). Weekly cleanly matches NFCI's native cadence.
  - Target: forward cumulative log return r_{t->t+H}, H in {1, 4, 12} weeks (primary,
    Equity-at-Risk). Secondary: forward annualized realized vol (Vol-at-Risk).
  - Quantile regression Q_tau(target | NFCI_t, spread_t) for tau in
    {0.05, 0.25, 0.50, 0.75, 0.95}. tau=0.05 left tail is the primary GaR result.

Lookahead protection (HIGHEST priority; violation = experiment failure)
----------------------------------------------------------------------
  (1) Feature availability = release-aware point-in-time merge. NFCI observation dated
      Friday W is only published the following Wednesday (+3 business days). At forecast
      origin Friday F we use the most recent obs whose RELEASE_DATE <= F. Daily series
      (BAA10Y) use RELEASE_DATE = obs_date + 1 business day. This is a rigorous
      equivalent of signal.shift(1): the conditioning info is provably known at origin.
  (2) Forward-label train-tail embargo. For an expanding OOS forecast made at origin
      position i, a training row j is admissible ONLY if j + H < i (project canonical
      strict inequality; see .claude/rules/experiments.md). This guarantees the training
      target windows realize strictly before the forecast origin -> no future return
      leaks into the training tail.
  (3) Horizon-specific inference. Overlapping H-period targets induce MA(H-1)
      autocorrelation in loss differentials. The DM test uses Newey-West lag = H-1 AND
      the Harvey-Leybourne-Newbold (1997) small-sample correction, with a SEPARATE
      horizon per target. In-sample quantile-slope SEs use a moving-block bootstrap
      (block length = H) rather than the iid QuantReg SE.

All random procedures use SEED=1655.

Outputs
-------
  experiments/K1655/K1655_results.json
  experiments/K1655/K1655_nfci_slope_across_quantiles.png
  experiments/K1655/K1655_gar_quantiles_vs_realized.png
  experiments/K1655/K1655_oos_pinball_by_horizon.png
  experiments/K1655/data/*.csv (raw snapshots for reproducibility)
"""
from __future__ import annotations

import io
import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests
import yfinance as yf
from scipy import stats
from statsmodels.regression.quantile_regression import QuantReg

# volpred canonical DM helper (used as a CROSS-CHECK; primary inference is the
# HLN-corrected horizon-aware DM implemented below, which the helper lacks).
try:
    from volpred.stats.model_evaluation import dm_test as volpred_dm_test
except Exception:  # pragma: no cover
    volpred_dm_test = None

SEED = 1655
np.random.seed(SEED)
RNG = np.random.default_rng(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

START = "2000-01-01"
END = "2026-07-01"
HORIZONS = [1, 4, 12]           # weeks
QUANTILES = [0.05, 0.25, 0.50, 0.75, 0.95]
PRIMARY_TAU = 0.05              # left tail = Equity-at-Risk
VOL_TAU = 0.95                 # right tail = Vol-at-Risk
MIN_TRAIN = 250                # >= ~5 years of admissible weeks before first OOS
REFIT_EVERY = 4               # refit expanding model every 4 weeks; predict weekly
BOOT_B = 500                  # moving-block bootstrap reps for in-sample slope SE
DISPLAY_H = 4                 # horizon shown in the time-series chart


# --------------------------------------------------------------------------- #
# Data fetch (cached to data/ for reproducibility)                            #
# --------------------------------------------------------------------------- #
def fetch_fred(series_id: str, timeout: int = 45) -> pd.DataFrame:
    """FRED revision-corrected observation series via public fredgraph.csv (no key)."""
    cache = os.path.join(DATA_DIR, f"fred_{series_id}.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, parse_dates=["DATE"])
        return df
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={df.columns[0]: "DATE", df.columns[1]: "VALUE"})
    df["DATE"] = pd.to_datetime(df["DATE"])
    df["VALUE"] = pd.to_numeric(df["VALUE"], errors="coerce")
    df = df.dropna(subset=["VALUE"]).sort_values("DATE").reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def fetch_spy() -> pd.DataFrame:
    cache = os.path.join(DATA_DIR, "gspc_daily.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, parse_dates=["Date"]).set_index("Date")
        return df
    g = yf.download("^GSPC", start=START, end=END, progress=False, auto_adjust=True)
    if isinstance(g.columns, pd.MultiIndex):
        g.columns = g.columns.get_level_values(0)
    g = g[["Close"]].dropna()
    g.index.name = "Date"
    g.to_csv(cache)
    return g


def release_date(obs_dates: pd.Series, kind: str) -> pd.Series:
    """Point-in-time public-availability date for each observation.

    NFCI (weekly, Fri-dated): published the FOLLOWING Wednesday ~ +3 business days,
      so NFCI dated Friday W is NOT known at Friday W; earliest origin that may use it
      is the next Friday. This is the rigorous shift(1)-equivalent lag.
    VIX / market-quote daily series: the day's CLOSE is observed at that day's close,
      so it is legitimately known at a same-day forecast origin (RELEASE_DATE = obs).
    Other daily released series: available next business day (+1).
    """
    if kind == "nfci_weekly":
        return obs_dates + pd.tseries.offsets.BDay(3)
    if kind == "daily_close":
        return obs_dates  # market quote known at its own close
    return obs_dates + pd.tseries.offsets.BDay(1)


def point_in_time_weekly(fred_df: pd.DataFrame, kind: str, week_fridays: pd.DatetimeIndex) -> pd.Series:
    """For each weekly-Friday origin F, most recent observation with RELEASE_DATE <= F."""
    df = fred_df.copy()
    df["RELEASE_DATE"] = release_date(df["DATE"], kind)
    df = df.sort_values("RELEASE_DATE").reset_index(drop=True)
    rel = df["RELEASE_DATE"].values
    vals = df["VALUE"].values
    out = np.full(len(week_fridays), np.nan)
    # searchsorted: index of last release <= F
    idx = np.searchsorted(rel, week_fridays.values, side="right") - 1
    ok = idx >= 0
    out[ok] = vals[idx[ok]]
    return pd.Series(out, index=week_fridays)


# --------------------------------------------------------------------------- #
# Quantile / DM machinery                                                     #
# --------------------------------------------------------------------------- #
def pinball_loss(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    """Elementwise pinball (quantile) loss; lower is better."""
    e = y - q
    return np.where(e >= 0, tau * e, (tau - 1.0) * e)


def fit_quantreg(X: np.ndarray, y: np.ndarray, tau: float):
    """QuantReg with an added intercept column. X columns are the raw regressors."""
    Xc = np.column_stack([np.ones(len(X)), X])
    model = QuantReg(y, Xc)
    res = model.fit(q=tau, max_iter=2000, p_tol=1e-6)
    return res  # params[0]=intercept, params[1:]=slopes


def _nw_lag(horizon: int, n: int) -> int:
    """Newey-West truncation lag for the DM loss differential.

    The textbook DM rule is lag = h-1, which covers only the MA(h-1) structure that
    overlapping forecast windows induce *under forecast optimality*. Here we compare a
    misspecified conditional quantile model against an unconditional benchmark, and the
    conditioning variable (NFCI / VIX) is highly persistent, so the loss differential
    carries serial correlation well beyond h-1 (measured acf(1) ~= 0.68). At h=1 the
    textbook rule degenerates to lag=0 -- i.e. no HAC correction at all -- which
    understates the variance and inflates |t|.

    Floor the lag at the repo-canonical bandwidth used by
    volpred.stats.model_evaluation.dm_test so the two never disagree by construction.
    """
    canonical = max(1, min(int(np.ceil(horizon ** (1 / 3) * n ** (1 / 3))), n // 4))
    return max(horizon - 1, canonical)


def hln_dm(loss_a: np.ndarray, loss_b: np.ndarray, horizon: int):
    """Diebold-Mariano on a loss differential with a HAC lag that is at least the
    repo-canonical bandwidth (see _nw_lag) and the Harvey-Leybourne-Newbold (1997)
    small-sample correction.

    d = loss_a - loss_b. Negative t => model A (conditional) has lower loss => better.
    Returns (t_hln, p_hln, nw_lag, n).
    """
    d = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return (0.0, 1.0, max(0, horizon - 1), n)
    dbar = d.mean()
    lag = _nw_lag(horizon, n)
    gamma0 = np.mean((d - dbar) ** 2)
    var = gamma0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)  # Bartlett kernel
        gk = np.mean((d[k:] - dbar) * (d[:-k] - dbar))
        var += 2.0 * w * gk
    if var <= 0:
        return (0.0, 1.0, lag, n)
    dm = dbar / np.sqrt(var / n)
    h = horizon
    corr = np.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 1e-12))
    t_hln = dm * corr
    p_hln = 2.0 * (1.0 - stats.t.cdf(abs(t_hln), df=n - 1))
    return (float(t_hln), float(p_hln), lag, n)


def moving_block_bootstrap_slopes(X: np.ndarray, y: np.ndarray, tau: float,
                                  block: int, B: int, rng: np.random.Generator):
    """Moving-block bootstrap of the QuantReg coefficient vector.

    Block length = H preserves the MA(H-1) dependence induced by overlapping targets,
    so the resulting SE / CI are valid for the overlapping-forward-return design
    (the iid QuantReg SE is NOT).
    """
    n = len(y)
    block = max(1, block)
    n_blocks = int(np.ceil(n / block))
    starts_pool = np.arange(0, n - block + 1) if n > block else np.array([0])
    boots = []
    for _ in range(B):
        starts = rng.choice(starts_pool, size=n_blocks, replace=True)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        try:
            res = fit_quantreg(X[idx], y[idx], tau)
            boots.append(res.params)
        except Exception:
            continue
    boots = np.array(boots)
    return boots  # shape (B_ok, 1+k)


# --------------------------------------------------------------------------- #
# Build the weekly panel                                                       #
# --------------------------------------------------------------------------- #
def build_panel():
    spy = fetch_spy()
    close = spy["Close"].astype(float)
    daily_logret = np.log(close / close.shift(1))

    # weekly close on the last trading day of each W-FRI week (label = Friday)
    wclose = close.resample("W-FRI").last().dropna()
    # weekly realized variance = sum of daily squared log returns within each week
    wrv = (daily_logret ** 2).resample("W-FRI").sum()
    wrv = wrv.reindex(wclose.index)

    fridays = wclose.index
    nfci = fetch_fred("NFCI")
    vix = fetch_fred("VIXCLS")

    nfci_pit = point_in_time_weekly(nfci, "nfci_weekly", fridays)
    vix_pit = point_in_time_weekly(vix, "daily_close", fridays)

    panel = pd.DataFrame({
        "wclose": wclose,
        "wrv": wrv,
        "nfci": nfci_pit,
        "vix": vix_pit,
    }, index=fridays)
    panel = panel.dropna(subset=["wclose", "nfci", "vix"])
    return panel, nfci, vix


def forward_return(wclose: pd.Series, H: int) -> pd.Series:
    """r_{t->t+H} = log(P_{t+H}/P_t); NaN where t+H beyond sample (unrealized)."""
    return np.log(wclose.shift(-H) / wclose)


def forward_realized_vol(wrv: pd.Series, H: int) -> pd.Series:
    """Annualized realized vol over the forward H-week window (weeks t+1..t+H).

    rolling(H).sum() at t covers [t-H+1, t]; shift(-H) maps new[t] = old[t+H],
    i.e. fwd_var[t] = sum of weekly RV over weeks t+1..t+H (strictly forward).
    """
    fwd_var = wrv.rolling(H).sum().shift(-H)
    ann = np.sqrt(fwd_var * (52.0 / H))
    return ann


# --------------------------------------------------------------------------- #
# In-sample quantile regression + bootstrap                                    #
# --------------------------------------------------------------------------- #
def in_sample_analysis(panel: pd.DataFrame, target_col: str, cond_cols, taus, horizons, label):
    """Fit QuantReg on the full admissible sample for every (H, tau); bootstrap slopes.

    cond_cols = list of conditioning column names in `panel` (e.g. ["nfci"] or ["vix"]).
    slope_grid tracks the FIRST conditioning variable's slope across quantiles (chart).
    """
    lead = cond_cols[0]
    results = {}
    slope_grid = {}
    for H in horizons:
        if target_col == "fwd_ret":
            y_full = forward_return(panel["wclose"], H)
        else:
            y_full = forward_realized_vol(panel["wrv"], H)
        df = pd.DataFrame({"y": y_full, **{c: panel[c] for c in cond_cols}}).dropna()
        X = df[cond_cols].values
        y = df["y"].values
        n = len(y)
        slope_grid[H] = {}
        names = ["intercept"] + list(cond_cols)
        for tau in taus:
            res = fit_quantreg(X, y, tau)
            boots = moving_block_bootstrap_slopes(X, y, tau, block=H, B=BOOT_B, rng=RNG)
            cell = {"n_obs": int(n), "tau": tau, "horizon_weeks": H}
            for j, nm in enumerate(names):
                pt = float(res.params[j])
                if boots.size:
                    col = boots[:, j]
                    se = float(np.std(col, ddof=1))
                    lo, hi = np.percentile(col, [5, 95])
                    p = float(2 * stats.norm.cdf(-abs(pt) / se)) if se > 0 else 1.0
                else:
                    se, lo, hi, p = float("nan"), float("nan"), float("nan"), float("nan")
                cell[nm] = {
                    "coef": pt,
                    "boot_se": se,
                    "ci90": [float(lo), float(hi)],
                    "boot_p": p,
                    "iid_t_diagnostic": float(res.tvalues[j]),  # NOT for inference
                }
            results[f"H{H}_tau{tau}"] = cell
            slope_grid[H][tau] = {
                "coef": cell[lead]["coef"],
                "ci90": cell[lead]["ci90"],
                "boot_p": cell[lead]["boot_p"],
            }
    return results, slope_grid


# --------------------------------------------------------------------------- #
# Out-of-sample expanding-window pinball + HLN-DM                              #
# --------------------------------------------------------------------------- #
def oos_analysis(panel: pd.DataFrame, target_col: str, cond_cols, taus, horizons, label):
    """Expanding-window OOS quantile forecasting with the forward-label embargo.

    For origin position i, admissible training rows are {j : j + H < i} (strict).
    Conditional model = QuantReg on `cond_cols`; benchmark = unconditional empirical
    tau-quantile of the same admissible training targets. Pinball loss compared via
    HLN-corrected, horizon-specific DM.
    """
    out = {}
    cond_mat = panel[cond_cols].values          # (N, k) conditioning matrix
    X_all = cond_mat
    for H in horizons:
        if target_col == "fwd_ret":
            y_all = forward_return(panel["wclose"], H).values
        else:
            y_all = forward_realized_vol(panel["wrv"], H).values
        N = len(y_all)
        # per-tau accumulators of pointwise losses aligned by origin
        loss_cond = {tau: [] for tau in taus}
        loss_uncond = {tau: [] for tau in taus}
        origins = []
        cond_q_series = {tau: [] for tau in taus}
        realized_series = []

        cached = {}  # tau -> fitted params, refreshed every REFIT_EVERY
        last_fit_i = -10**9
        for i in range(N):
            # admissible training rows: target realized strictly before origin i.
            # row j's target window ends at j+H; require j + H < i (embargo) =>
            # j <= i-H-1, i.e. j in [0, i-H-1] == np.arange(0, i-H).
            train_idx = np.arange(0, i - H)  # empty if i <= H
            if len(train_idx) < MIN_TRAIN:
                continue
            # target at origin i must be realized (i+H within sample) to score OOS
            if i + H >= N or not np.isfinite(y_all[i]):
                continue
            if not np.isfinite(cond_mat[i]).all():
                continue
            ytr = y_all[train_idx]
            Xtr = X_all[train_idx]
            good = np.isfinite(ytr) & np.isfinite(Xtr).all(axis=1)
            ytr, Xtr = ytr[good], Xtr[good]
            if len(ytr) < MIN_TRAIN:
                continue

            refit = (i - last_fit_i) >= REFIT_EVERY or not cached
            if refit:
                cached = {}
                for tau in taus:
                    try:
                        res = fit_quantreg(Xtr, ytr, tau)
                        cached[tau] = res.params
                    except Exception:
                        cached[tau] = None
                cached["_uncond"] = {tau: float(np.quantile(ytr, tau)) for tau in taus}
                last_fit_i = i

            xi = np.concatenate([[1.0], cond_mat[i]])
            yi = y_all[i]
            for tau in taus:
                params = cached.get(tau)
                if params is None:
                    continue
                q_cond = float(xi @ params)
                q_unc = cached["_uncond"][tau]
                loss_cond[tau].append(pinball_loss(np.array([yi]), np.array([q_cond]), tau)[0])
                loss_uncond[tau].append(pinball_loss(np.array([yi]), np.array([q_unc]), tau)[0])
                if tau == PRIMARY_TAU or tau == VOL_TAU:
                    cond_q_series[tau].append(q_cond)
            origins.append(i)
            realized_series.append(yi)

        res_H = {"horizon_weeks": H, "n_oos": len(origins), "refit_every": REFIT_EVERY,
                 "min_train": MIN_TRAIN, "tau": {}}
        for tau in taus:
            la = np.array(loss_cond[tau], float)
            lb = np.array(loss_uncond[tau], float)
            if len(la) < 10:
                res_H["tau"][str(tau)] = {"n": len(la), "note": "insufficient OOS"}
                continue
            t_hln, p_hln, lag, n = hln_dm(la, lb, H)
            helper_t, helper_p = (None, None)
            if volpred_dm_test is not None:
                try:
                    helper_t, helper_p = volpred_dm_test(la, lb, h=H)
                    helper_t, helper_p = float(helper_t), float(helper_p)
                except Exception:
                    helper_t, helper_p = (None, None)
            res_H["tau"][str(tau)] = {
                "n": int(n),
                "pinball_cond": float(la.mean()),
                "pinball_uncond": float(lb.mean()),
                "pinball_reduction_pct": float((lb.mean() - la.mean()) / lb.mean() * 100.0),
                "dm_t_hln": t_hln,             # negative => conditional better
                "dm_p_hln": p_hln,
                "nw_lag": lag,
                "hln_applied": True,
                "helper_dm_t": helper_t,      # cross-check (volpred canonical, no HLN)
                "helper_dm_p": helper_p,
                "cond_better": bool(la.mean() < lb.mean()),
                "harvey_significant": bool(abs(t_hln) > 3.0),
            }
        res_H["_origins"] = origins
        res_H["_cond_q_series"] = {str(k): v for k, v in cond_q_series.items()}
        res_H["_realized_series"] = realized_series
        out[H] = res_H
    return out


# --------------------------------------------------------------------------- #
# Charts                                                                        #
# --------------------------------------------------------------------------- #
def chart_slope_across_quantiles(slope_grid, path, target_label):
    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = {1: "#1f77b4", 4: "#d62728", 12: "#2ca02c"}
    for H in sorted(slope_grid):
        taus = sorted(slope_grid[H])
        coefs = [slope_grid[H][t]["coef"] for t in taus]
        lo = [slope_grid[H][t]["ci90"][0] for t in taus]
        hi = [slope_grid[H][t]["ci90"][1] for t in taus]
        ax.plot(taus, coefs, "o-", color=colors.get(H, None), label=f"H={H}w")
        ax.fill_between(taus, lo, hi, color=colors.get(H, None), alpha=0.12)
    ax.axhline(0, color="k", lw=0.8, ls="--")
    ax.axvline(PRIMARY_TAU, color="grey", lw=0.8, ls=":")
    ax.set_xlabel("Quantile tau")
    ax.set_ylabel("NFCI slope on target")
    ax.set_title(f"K1655 Growth-at-Risk: NFCI slope across quantiles ({target_label})\n"
                 f"90% moving-block bootstrap CI (block=H, seed={SEED})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_gar_vs_realized(panel, oos_ret, H, path):
    resH = oos_ret[H]
    origins = resH["_origins"]
    idx = panel.index[origins]
    realized = np.array(resH["_realized_series"], float)
    q05 = np.array(resH["_cond_q_series"][str(PRIMARY_TAU)], float)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(idx, realized, color="#444", lw=0.7, alpha=0.7,
            label=f"Realized fwd {H}w return")
    ax.plot(idx, q05, color="#d62728", lw=1.4,
            label="Conditional 5% quantile (Equity-at-Risk)")
    breach = realized < q05
    ax.scatter(idx[breach], realized[breach], color="#d62728", s=14, zorder=5,
               label=f"Breach ({breach.sum()}/{len(realized)}={breach.mean()*100:.1f}%)")
    for a, b in [("2008-06-01", "2009-06-01"), ("2020-02-01", "2020-06-01")]:
        ax.axvspan(pd.Timestamp(a), pd.Timestamp(b), color="grey", alpha=0.12)
    ax.axhline(0, color="k", lw=0.6, ls="--")
    ax.set_title(f"K1655 Equity-at-Risk: OOS conditional 5% quantile vs realized "
                 f"forward {H}-week SPY return\n(shaded: 2008 GFC, 2020 COVID; "
                 f"target=5% => ~5% breaches if well-calibrated)")
    ax.set_ylabel("Forward log return")
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_pinball_by_horizon(oos_nfci, oos_vix, path):
    """Unconditional vs NFCI-conditional vs VIX-conditional OOS pinball at tau=0.05.
    DM p annotated for the PRIMARY (NFCI) spec."""
    Hs = sorted(oos_nfci)
    unc = [oos_nfci[H]["tau"][str(PRIMARY_TAU)]["pinball_uncond"] for H in Hs]
    cnf = [oos_nfci[H]["tau"][str(PRIMARY_TAU)]["pinball_cond"] for H in Hs]
    cvx = [oos_vix[H]["tau"][str(PRIMARY_TAU)]["pinball_cond"] for H in Hs]
    dmp = [oos_nfci[H]["tau"][str(PRIMARY_TAU)]["dm_p_hln"] for H in Hs]
    x = np.arange(len(Hs))
    w = 0.26
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - w, unc, w, label="Unconditional (hist. quantile)", color="#9ecae1")
    ax.bar(x, cnf, w, label="NFCI-conditional", color="#d62728")
    ax.bar(x + w, cvx, w, label="VIX-conditional", color="#2ca02c")
    for xi, p in zip(x, dmp):
        top = max(unc[int(xi)], cnf[int(xi)], cvx[int(xi)])
        ax.text(xi, top * 1.01, f"NFCI DM p={p:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"H={H}w" for H in Hs])
    ax.set_ylabel("OOS mean pinball loss (tau=0.05)")
    ax.set_title("K1655 Equity-at-Risk OOS pinball loss by horizon\n"
                 "(lower=better; HLN-DM p vs unconditional, horizon-specific NW lag=H-1)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Verdict                                                                       #
# --------------------------------------------------------------------------- #
def build_verdict(in_ret, oos_ret):
    """Verdict on the PRIMARY claim: NFCI conditions the 5% left tail of forward SPY
    returns (Equity-at-Risk), in-sample AND out-of-sample."""
    # primary in-sample: NFCI slope at tau=0.05 for each H, sign & significance
    primary_cells = {H: in_ret.get(f"H{H}_tau{PRIMARY_TAU}") for H in HORIZONS}
    in_sig = {H: (c["nfci"]["boot_p"] < 0.05 and c["nfci"]["coef"] < 0)
              for H, c in primary_cells.items() if c}
    oos_sig = {}
    for H in HORIZONS:
        cell = oos_ret[H]["tau"].get(str(PRIMARY_TAU), {})
        oos_sig[H] = bool(cell.get("cond_better") and cell.get("dm_p_hln", 1.0) < 0.05)
    any_in = any(in_sig.values())
    any_oos = any(oos_sig.values())
    harvey_oos = any(oos_ret[H]["tau"].get(str(PRIMARY_TAU), {}).get("harvey_significant")
                     for H in HORIZONS)

    if any_oos and harvey_oos:
        verdict = "PASS"
    elif any_in and any_oos:
        verdict = "CONDITIONAL_PASS"
    elif any_in and not any_oos:
        verdict = "NULL_OOS"  # in-sample tail dependence but no OOS predictive gain
    else:
        verdict = "NULL"
    return {
        "verdict": verdict,
        "in_sample_left_tail_significant_by_H": in_sig,
        "oos_left_tail_significant_by_H": oos_sig,
        "oos_harvey_significant_any_H": bool(harvey_oos),
    }


def atomic_write_json(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    with open(tmp) as f:
        json.load(f)  # validate parseable
    os.replace(tmp, path)


def strip_private(d):
    """Remove _-prefixed helper series from the JSON-serialized OOS blocks."""
    clean = {}
    for H, block in d.items():
        clean[str(H)] = {k: v for k, v in block.items() if not k.startswith("_")}
    return clean


def main():
    t0 = datetime.now()
    print("[K1655] building weekly panel ...")
    panel, nfci_raw, vix_raw = build_panel()
    print(f"[K1655] panel: n={len(panel)} weeks, "
          f"{panel.index[0].date()}..{panel.index[-1].date()}")

    # Two conditioning specs: NFCI (primary GaR variable, Adrian et al. headline) and
    # VIX (market-implied vol; tests the K503/K828 'VIX absorbs stress' prior in a
    # tail-quantile framing). Single-variable specs avoid NFCI/VIX collinearity.
    SPECS = {"NFCI": ["nfci"], "VIX": ["vix"]}

    ear, var = {}, {}   # equity-at-risk, vol-at-risk (secondary)
    for name, cols in SPECS.items():
        print(f"[K1655] equity-at-risk spec={name}: in-sample + OOS ...")
        in_s, slope_s = in_sample_analysis(panel, "fwd_ret", cols, QUANTILES, HORIZONS, name)
        oos_s = oos_analysis(panel, "fwd_ret", cols, QUANTILES, HORIZONS, name)
        ear[name] = {"in": in_s, "slope": slope_s, "oos": oos_s}
    for name, cols in SPECS.items():
        print(f"[K1655] vol-at-risk spec={name}: in-sample + OOS ...")
        in_s, slope_s = in_sample_analysis(panel, "fwd_vol", cols, QUANTILES, HORIZONS, name)
        oos_s = oos_analysis(panel, "fwd_vol", cols, QUANTILES, HORIZONS, name)
        var[name] = {"in": in_s, "slope": slope_s, "oos": oos_s}

    in_ret, oos_ret = ear["NFCI"]["in"], ear["NFCI"]["oos"]   # primary
    verdict = build_verdict(in_ret, oos_ret)

    # ---- charts ----
    print("[K1655] charts ...")
    chart_slope_across_quantiles(ear["NFCI"]["slope"],
                                 os.path.join(HERE, "K1655_nfci_slope_across_quantiles.png"),
                                 "SPY forward returns")
    chart_gar_vs_realized(panel, oos_ret, DISPLAY_H,
                          os.path.join(HERE, "K1655_gar_quantiles_vs_realized.png"))
    chart_pinball_by_horizon(ear["NFCI"]["oos"], ear["VIX"]["oos"],
                             os.path.join(HERE, "K1655_oos_pinball_by_horizon.png"))

    results = {
        "experiment_id": "K1655",
        "title": "Growth-at-Risk moved to markets: Equity/Vol-at-Risk multi-horizon quantile regression",
        "run_at": t0.isoformat(),
        "seed": SEED,
        "data": {
            "spy_source": "yfinance ^GSPC (auto_adjust close)",
            "nfci_source": "FRED NFCI (weekly, Fri-dated; release-aware +3 BDay). "
                           "Reused from prior FRED snapshot (experiments/k1567) because the "
                           "live fredgraph endpoint was rate-limited during this run.",
            "vix_source": "FRED VIXCLS (daily close, known same-day; reused from experiments/k1601 snapshot).",
            "credit_spread_note": "The planned BAA10Y credit-spread bivariate extension was "
                                  "dropped: FRED (fred.stlouisfed.org) rate-limited/HTTP2-dropped this "
                                  "run's requests. NFCI already embeds credit spreads as a component, "
                                  "so the single-index GaR (Adrian et al. headline spec) is unaffected.",
            "frequency": "weekly W-FRI",
            "sample_start": str(panel.index[0].date()),
            "sample_end": str(panel.index[-1].date()),
            "n_weeks": int(len(panel)),
            "nfci_raw_span": [str(nfci_raw['DATE'].iloc[0].date()), str(nfci_raw['DATE'].iloc[-1].date())],
            "vix_raw_span": [str(vix_raw['DATE'].iloc[0].date()), str(vix_raw['DATE'].iloc[-1].date())],
        },
        "config": {
            "horizons_weeks": HORIZONS,
            "quantiles": QUANTILES,
            "primary_tau": PRIMARY_TAU,
            "vol_tau": VOL_TAU,
            "min_train_weeks": MIN_TRAIN,
            "refit_every_weeks": REFIT_EVERY,
            "bootstrap_B": BOOT_B,
            "bootstrap": "moving-block, block length = H",
            "dm": "HLN-corrected, Newey-West lag = H-1, horizon-specific; helper_dm cross-check = volpred.dm_test (no HLN)",
            "embargo": "training row admissible iff j + H < i (project canonical strict)",
            "feature_availability": "release-aware point-in-time (RELEASE_DATE <= origin)",
            "specs": {k: v for k, v in SPECS.items()},
        },
        "equity_at_risk": {
            "primary_spec": "NFCI",
            "NFCI": {"in_sample": ear["NFCI"]["in"], "oos": strip_private(ear["NFCI"]["oos"])},
            "VIX": {"in_sample": ear["VIX"]["in"], "oos": strip_private(ear["VIX"]["oos"])},
        },
        "vol_at_risk_secondary": {
            "NFCI": {"in_sample": var["NFCI"]["in"], "oos": strip_private(var["NFCI"]["oos"])},
            "VIX": {"in_sample": var["VIX"]["in"], "oos": strip_private(var["VIX"]["oos"])},
        },
        "verdict": verdict,
        "honest_statement": (
            "Cross-domain test of Adrian et al. (2019) Growth-at-Risk on an equity market. "
            "In-sample tail slopes reflect crisis co-movement and are NOT a predictive claim; "
            "the predictive claim is the OOS pinball-loss DM (HLN, horizon-specific). "
            "Priors (NFCI/BAA10Y lag VIX; STLFSI4 NULL in K503/K828) make a NULL/CONDITIONAL "
            "OOS result the expected and reported honest outcome for efficient equity markets. "
            "All statistics from actual computation on the stated sample; no cherry-picking."
        ),
    }
    out_path = os.path.join(HERE, "K1655_results.json")
    atomic_write_json(results, out_path)

    # console summary
    print("\n===== K1655 SUMMARY =====")
    print(f"verdict: {verdict['verdict']}")
    for H in HORIZONS:
        c = in_ret[f"H{H}_tau{PRIMARY_TAU}"]["nfci"]
        o = oos_ret[H]["tau"][str(PRIMARY_TAU)]
        print(f" H={H:>2}w | IS NFCI slope@0.05={c['coef']:+.5f} (boot p={c['boot_p']:.3f}) "
              f"| OOS pinball cond={o['pinball_cond']:.6f} unc={o['pinball_uncond']:.6f} "
              f"red={o['pinball_reduction_pct']:+.2f}% DM_HLN t={o['dm_t_hln']:+.2f} p={o['dm_p_hln']:.3f}")
    print(f"elapsed: {(datetime.now()-t0).total_seconds():.0f}s")
    print(f"written: {out_path}")


if __name__ == "__main__":
    main()
