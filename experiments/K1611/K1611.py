#!/usr/bin/env python3
"""K1611: Giacomini-White (2006) conditional predictive ability test --
HAR-RV vs GJR-GARCH horse race, is the winner regime-dependent?

Motivation
----------
Prior SPY/TAIEX HAR vs GJR-GARCH horse races (K1049/k1054/k1057/k1063) only ran
*unconditional* Diebold-Mariano (DM), producing a single full-sample winner.
Giacomini & White (2006, Econometrica) show that unconditional DM hides the
possibility that *which* model wins depends on the market state. This experiment
runs the GW conditional predictive ability test with a lagged VIX-regime
conditioning instrument to honestly test whether HAR vs GJR-GARCH relative
performance is regime-dependent rather than constant across the sample.

Design (per asset -- NO cross-asset asset-day pooling; K1355 hard rule)
----------------------------------------------------------------------
Assets:
  SPY       proxy period 2005-2026, regime instrument = ^VIX (lagged). yfinance
            close-to-close returns clean (0 impossible moves in-sample).
  0050.TW   proxy period 2014-01-06 .. 2021-12-31, regime instrument = 台指VIX
            (VIXTWN, lagged). Sample START is set AFTER a vendor (yfinance)
            adjustment break at 2014-01-02 (close 37.41 -> 9.33 overnight = a
            spurious -139% return) and after 2009 rows with several moves beyond
            Taiwan's +-7% daily price limit -- both impossible under exchange
            rules and thus data errors. A hard data-quality gate
            (assert_price_limit) aborts if any used-sample return exceeds the
            price limit, so the experiment cannot silently run on bad ticks.
            OOS ~2017-2021 crosses the 2018 vol spikes and the 2020 COVID crash.

Variance proxy (Patton 2011 proxy-robust QLIKE). Both proxies are conditionally
unbiased for the CLOSE-TO-CLOSE variance that BOTH HAR (fit on the proxy) and GJR
(fit on close-to-close returns) target -> QLIKE ranking is proxy-robust and the
race is fair to GJR:
  PRIMARY  = r^2, squared close-to-close log return (canonical, noisy; matches
             k1049/k1054/k782 horse-race convention).
  ROBUST   = rsov = Parkinson intraday range variance + squared overnight log
             return (less noisy on the intraday part while still capturing
             overnight; unbiased for close-to-close variance under a drift-free
             intraday diffusion and an overnight jump uncorrelated with the
             intraday range).
  EXCLUDED = pure Parkinson (intraday only) omits the overnight jump -> biased LOW
             for close-to-close variance -> mechanically penalises the GJR
             close-to-close forecast and spuriously inflates DM (0050.TW pure
             Parkinson captures only ~5% of close-to-close variance; see
             proxy_level_diagnostic). Kept diagnostic-only, OUT of the race.
  All in percent^2 (returns / log-ranges x100), consistent with GJR variance.
  OHLC use yfinance auto_adjust=True (vendor total-return-adjusted); log-ratios
  embed only the current-date (known ex-div) dividend -> no lookahead.

Models:
  HAR-RV     RV_t = b0 + b_d RV_{t-1} + b_w mean(RV_{t-1:t-5})
                       + b_m mean(RV_{t-1:t-22}); expanding OLS, explicit
             shift(1) lag on every feature (t-1 info predicts t).
  GJR-GARCH  GJR(1,1) normal on daily percent returns; MONTHLY refit
             (compute control); one-step forecast built by the exact GJR
             variance recursion with the month's fixed params -> the forecast
             sigma^2_t is F_{t-1}-measurable and target-aligned to proxy_t by
             construction (K445 hard rule: no origin/target off-by-one).
             Cross-validated at each refit day against arch's own
             forecast(horizon=1) one-step variance.

Losses / tests:
  QLIKE      canonical actual/predicted direction (K783c hard rule) via
             volpred.stats.model_evaluation.qlike_pointwise.
  d_t        = QLIKE_HAR,t - QLIKE_GJR,t  (positive -> GJR better).
  Unconditional DM  reported in two variants: (a) MDS/HLN (L=0, the one-step
             textbook DM with HLN small-sample correction) and (b) HAC-DM
             (Newey-West with data-driven lag, robust to serial correlation in
             the daily loss differential). Harvey (2016) |t|>3 bar.
  GW (2006) conditional test  h_{t-1} = [1, regime_{t-1}],
             z_t = h_{t-1} * d_t, S = n * zbar' Omega^{-1} zbar,
             Omega = HAC long-run covariance of z_t, S ~ chi2(2). NOTE: a df=2
             rejection means the models are NOT conditionally equivalent (E[d]=0
             and E[regime*d]=0 jointly fail); it does NOT by itself mean the
             WINNER flips with the regime -- that specific claim is tested by the
             regime-slope coefficient below.
  Regime-slope test  d_t = a + b regime_{t-1} + e_t, HAC se on b -> the DIRECT
             test of regime-dependence (b != 0 <=> loss differential differs by
             regime). This, and proxy-robustness of its sign/significance, is the
             gate for any 'regime-dependent' verdict.
  Regime subsample decomposition  mean d_t / winner / DM in high vs low regime.

Regime instrument (lookahead-free): regime_{t-1} = 1{VIX_{t-1} >
  expanding_median(VIX_{0..t-1})}, i.e. lagged VIX vs an expanding (past-only)
  median -> strictly F_{t-1}-measurable. A full-sample-median split is reported
  as a secondary robustness only.

seed = 42.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy import stats as scistats

# canonical volpred helpers
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))
from volpred.stats.model_evaluation import qlike_pointwise  # noqa: E402
from volpred.data.preprocessing import (  # noqa: E402
    compute_parkinson_vol,
    compute_garman_klass_vol,
)

SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# k1098-archived long 台指VIX (VIXTWN) daily series, 2007-2021
VIXTWN_CSV = os.path.abspath(os.path.join(HERE, "..", "k1098", "k1098_vixtwn_daily.csv"))

MIN_TRAIN = {"SPY": 1250, "0050.TW": 740}     # ~5y SPY, ~3y 0050 burn-in
INITIAL_HAR_TRAIN = 250                        # min rows before HAR OOS starts

# Data-quality gate: max plausible |daily log return|. 0050.TW has a hard
# exchange price limit (+-7% pre-2015-06, +-10% after) so any move beyond ~11%
# is a vendor data error (bad tick / adjustment break). SPY has no price limit;
# its true extremes (2008/2020) are ~12%, so 25% only ever catches bad ticks.
PRICE_LIMIT_LOGRET = {"SPY": 0.25, "0050.TW": 0.11}
GJR_DISC_TOL = 5e-3                             # abort if manual GJR recursion
#                                                diverges from arch beyond this
#                                                (guards bad-tick-poisoned fits)


def assert_price_limit(r_pct: pd.Series, name: str) -> None:
    """Abort loudly if any used-sample return exceeds the exchange price limit
    (fixes the process, not the data: forces a clean sample instead of silently
    running the horse race on impossible bad-tick returns)."""
    bound = PRICE_LIMIT_LOGRET.get(name)
    if bound is None:
        return
    bad = r_pct[(r_pct / 100.0).abs() > bound]
    if len(bad):
        raise ValueError(
            f"{name}: {len(bad)} return(s) exceed the +-{bound*100:.0f}% price "
            f"limit -> vendor data error, refuse to run:\n"
            + bad.to_string())


# ------------------------------------------------------------------ data ----
def load_yf(ticker: str, start: str, end: str, adjust: bool = True) -> pd.DataFrame:
    """Download (cached) OHLC from yfinance -> flat OHLC frame indexed by date.

    adjust=True -> dividend/split-adjusted OHLC. Proportional adjustment leaves
    intraday log-ranges log(H/L) unchanged while removing the spurious ex-dividend
    jump from overnight / close-to-close returns (important for 0050.TW whose
    large annual dividend otherwise inflates r^2 on ex-div days). Log-ratios only
    embed the current-date dividend (known on the ex-div date) -> no lookahead.
    Rows with any non-positive OHLC (bad ticks) are set NaN and dropped downstream.
    """
    safe = ticker.replace("^", "").replace(".", "_")
    cache = os.path.join(DATA_DIR, f"{safe}_ohlc_adj.csv")
    if os.path.exists(cache):
        return pd.read_csv(cache, parse_dates=["date"]).set_index("date")
    import yfinance as yf

    raw = yf.download(ticker, start=start, end=end, auto_adjust=adjust, progress=False)
    if len(raw) == 0:
        raise RuntimeError(f"yfinance empty for {ticker}")
    cols = {}
    for name in ["Open", "High", "Low", "Close"]:
        if isinstance(raw.columns, pd.MultiIndex):
            cols[name.lower()] = raw[(name, ticker)] if (name, ticker) in raw.columns else raw[name].iloc[:, 0]
        else:
            cols[name.lower()] = raw[name]
    df = pd.DataFrame(cols)
    # guard bad ticks: non-positive / non-finite prices -> NaN
    df = df.where((df > 0) & np.isfinite(df))
    df.index.name = "date"
    df.to_csv(cache)
    return df


def load_vix_yf(start: str, end: str) -> pd.Series:
    df = load_yf("^VIX", start, end)
    return df["close"].rename("vix")


def load_vixtwn() -> pd.Series:
    d = pd.read_csv(VIXTWN_CSV, parse_dates=["date"]).set_index("date")
    return d["VIXTWN"].rename("vix")


# ------------------------------------------------------------- proxies ------
def build_proxies(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Percent log return r and close-to-close-consistent variance proxies (pct^2).

    Proxies (both conditionally UNBIASED for the close-to-close variance that BOTH
    HAR-RV (fit on the proxy) and GJR-GARCH (fit on close-to-close returns) target,
    so QLIKE ranking is proxy-robust in the Patton (2011) sense):
      r2    = squared close-to-close log return (canonical, noisy, k1049/k1054/k782
              convention) -- PRIMARY.
      rsov  = Parkinson intraday range variance + squared overnight log return
              (range+overnight; less noisy than r2 on the intraday component while
              still capturing overnight -> unbiased for close-to-close) -- ROBUST.
    Diagnostic-only (NOT used for any test):
      parkinson = Parkinson intraday range variance ALONE. Excludes overnight ->
              BIASED LOW for close-to-close variance -> mechanically penalises the
              close-to-close GJR forecast and spuriously inflates the HAR-vs-GJR DM
              statistic (see K1611_results diagnostics; 0050.TW Parkinson captures
              only ~18% of close-to-close variance). Retained solely to document the
              proxy-bias artifact; excluded from the horse race.
    All in pct^2 (returns / log-ranges scaled x100), consistent with GJR variance.
    """
    close = ohlc["close"].astype(float)
    open_ = ohlc["open"].astype(float)
    high = ohlc["high"].astype(float)
    low = ohlc["low"].astype(float)
    r = 100.0 * np.log(close / close.shift(1))               # close-to-close pct return
    r2 = r ** 2
    log_hl = 100.0 * np.log(high / low)
    parkinson = (1.0 / (4.0 * np.log(2.0))) * log_hl ** 2     # intraday only
    overnight = 100.0 * np.log(open_ / close.shift(1))        # overnight gap return
    rsov = parkinson + overnight ** 2                         # close-to-close-consistent
    out = pd.DataFrame({"r": r, "r2": r2, "rsov": rsov, "parkinson": parkinson})
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    for c in ["r2", "rsov", "parkinson"]:
        out[c] = out[c].clip(lower=1e-8)
    return out


# --------------------------------------------------------------- HAR --------
def har_expanding_forecast(rv: pd.Series, oos_start_idx: int) -> pd.Series:
    """Expanding-OLS HAR-RV one-step forecasts for rows >= oos_start_idx.

    Every feature is an explicit lag of RV (shift(1) equivalent): the design row
    predicting RV_t uses only RV_{t-1..t-22}. Training set for forecasting day t
    = all fully-observed rows j (target RV_j, j <= t-1). target_end < origin.
    """
    x_d = rv.shift(1)
    x_w = rv.rolling(5).mean().shift(1)
    x_m = rv.rolling(22).mean().shift(1)
    y = rv
    feat = pd.DataFrame({"d": x_d, "w": x_w, "m": x_m, "y": y}).dropna()
    idx = feat.index
    X = np.column_stack([np.ones(len(feat)), feat["d"], feat["w"], feat["m"]])
    yv = feat["y"].to_numpy()

    # map global oos_start_idx (into rv) to position within feat
    oos_date = rv.index[oos_start_idx]
    start_pos = idx.searchsorted(oos_date)
    start_pos = max(start_pos, INITIAL_HAR_TRAIN)

    preds = pd.Series(index=idx[start_pos:], dtype=float)
    for pos in range(start_pos, len(feat)):
        Xtr = X[:pos]          # rows 0..pos-1 : targets RV_j for j <= t-1
        ytr = yv[:pos]
        beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        f = float(X[pos] @ beta)
        tr_mean = float(ytr.mean())
        # clamp to [1%, 1000%] of training-mean RV (k1054 convention)
        f = min(max(f, 0.01 * tr_mean), 10.0 * tr_mean)
        f = max(f, 1e-8)
        preds.iloc[pos - start_pos] = f
    return preds


# ------------------------------------------------------------ GJR-GARCH -----
def gjr_monthly_forecast(r: pd.Series, oos_start_idx: int) -> tuple[pd.Series, float]:
    """Monthly-refit GJR-GARCH(1,1) one-step forecasts via exact variance
    recursion with the month's fixed params.

    Returns (forecast sigma^2_t series aligned to target day t, max cross-val
    discrepancy vs arch forecast(horizon=1) at refit days).
    """
    from arch import arch_model

    rv = r.to_numpy(dtype=float)
    dates = r.index
    n = len(rv)
    months = dates.to_period("M")

    fc = pd.Series(index=dates[oos_start_idx:], dtype=float)
    mu = omega = alpha = gamma = beta = None
    last_h = None            # sigma^2 for the last training day (index origin-1)
    last_origin = None
    cur_month = None
    disc = 0.0

    def refit(origin: int):
        """Fit GJR on returns[:origin]; return params + last in-sample h + arch
        one-step forecast variance for day `origin`."""
        am = arch_model(rv[:origin], mean="Constant", vol="GARCH",
                        p=1, o=1, q=1, dist="normal", rescale=False)
        res = am.fit(disp="off", show_warning=False)
        p = res.params
        h_last = float(res.conditional_volatility[-1] ** 2)
        arch_fc = float(res.forecast(horizon=1, reindex=False).variance.values[-1, 0])
        return (float(p["mu"]), float(p["omega"]), float(p["alpha[1]"]),
                float(p["gamma[1]"]), float(p["beta[1]"]), h_last, arch_fc)

    for t in range(oos_start_idx, n):
        m = months[t]
        if cur_month is None or m != cur_month:
            # refit on all returns strictly before day t (info through t-1)
            origin = t
            mu, omega, alpha, gamma, beta, last_h, arch_fc = refit(origin)
            last_origin = origin
            cur_month = m
            # sigma^2_t = one-step forecast for first day of month (day t)
            eps_prev = rv[t - 1] - mu
            ind = 1.0 if eps_prev < 0 else 0.0
            h_t = omega + (alpha + gamma * ind) * eps_prev ** 2 + beta * last_h
            # cross-validate against arch's own one-step forecast for day t
            disc = max(disc, abs(h_t - arch_fc) / max(arch_fc, 1e-12))
            prev_h = h_t
        else:
            eps_prev = rv[t - 1] - mu
            ind = 1.0 if eps_prev < 0 else 0.0
            h_t = omega + (alpha + gamma * ind) * eps_prev ** 2 + beta * prev_h
            prev_h = h_t
        fc.iloc[t - oos_start_idx] = max(h_t, 1e-10)
    return fc, disc


# ------------------------------------------------------- statistical tests --
def newey_west_lag(n: int) -> int:
    return int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))


def _dm_lrv(dd: np.ndarray, lags: int) -> float:
    """Bartlett-kernel long-run variance of the demeaned loss differential."""
    n = len(dd)
    var = np.mean(dd ** 2)
    for j in range(1, lags + 1):
        w = 1.0 - j / (lags + 1.0)
        var += 2 * w * np.mean(dd[j:] * dd[:-j])
    return max(var, 1e-300)


def dm_hln(d: np.ndarray, h: int = 1) -> dict:
    """Diebold-Mariano loss-differential test, two variants (negative t -> model1
    HAR better; positive -> model2 GJR better):
      t_hln : one-step (L=h-1=0) DM with Harvey-Leybourne-Newbold small-sample
              correction -- the textbook one-step DM (loss diff a MDS under H0).
      t_hac : Newey-West HAC-DM with data-driven Bartlett lag (robust to serial
              correlation in the daily loss differential; the more conservative,
              honest variant given QLIKE losses cluster).
    p_value keys report each variant; the primary reported bar is Harvey |t|>3 on
    t_hac (conservative)."""
    d = np.asarray(d, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    dbar = d.mean()
    dd = d - dbar
    # (a) one-step MDS + HLN
    var0 = _dm_lrv(dd, h - 1)
    dm0 = dbar / np.sqrt(var0 / n)
    corr = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_hln = dm0 * corr
    p_hln = 2 * (1 - scistats.t.cdf(abs(t_hln), df=n - 1))
    # (b) HAC-DM, data-driven lag
    L = newey_west_lag(n)
    var_hac = _dm_lrv(dd, L)
    t_hac = dbar / np.sqrt(var_hac / n)
    p_hac = 2 * (1 - scistats.t.cdf(abs(t_hac), df=n - 1))
    return {"t_dm": float(dm0), "t_hln": float(t_hln), "p_value": float(p_hln),
            "t_hac": float(t_hac), "p_value_hac": float(p_hac), "hac_lag": int(L),
            "mean_d": float(dbar), "n": int(n)}


def newey_west_cov(z: np.ndarray, lags: int) -> np.ndarray:
    """HAC long-run covariance of z_t (q-vector rows), NOT demeaned
    (GW: under H0 E[z_t]=0). Bartlett weights."""
    n, q = z.shape
    S = (z.T @ z) / n
    for j in range(1, lags + 1):
        w = 1.0 - j / (lags + 1.0)
        G = (z[j:].T @ z[:-j]) / n
        S += w * (G + G.T)
    return S


def gw_conditional_test(d: np.ndarray, regime_lag: np.ndarray) -> dict:
    """Giacomini-White (2006) conditional predictive ability test.
    h_{t-1} = [1, regime_{t-1}], z_t = h_{t-1} * d_t,
    S = n * zbar' Omega^{-1} zbar ~ chi2(2)."""
    d = np.asarray(d, dtype=float)
    reg = np.asarray(regime_lag, dtype=float)
    valid = np.isfinite(d) & np.isfinite(reg)
    d, reg = d[valid], reg[valid]
    n = len(d)
    hmat = np.column_stack([np.ones(n), reg])           # n x 2
    z = hmat * d[:, None]                                # n x 2
    zbar = z.mean(0)
    L = newey_west_lag(n)
    # primary: HAC (Newey-West); h=1 -> z is MDS under H0 so L=0 also reported
    Omega_hac = newey_west_cov(z, L)
    Omega_0 = newey_west_cov(z, 0)
    out = {}
    for tag, Om, lag in [("hac", Omega_hac, L), ("l0", Omega_0, 0)]:
        try:
            Om_inv_zbar = np.linalg.solve(Om, zbar)
        except np.linalg.LinAlgError:
            Om_inv_zbar = np.linalg.pinv(Om) @ zbar     # singular HAC fallback
        S = float(n * zbar @ Om_inv_zbar)
        out[tag] = {"stat": S, "df": 2, "p_value": float(1 - scistats.chi2.cdf(S, df=2)),
                    "nw_lag": int(lag)}
    out["n"] = int(n)
    out["zbar"] = [float(x) for x in zbar]
    return out


def regime_slope_test(d: np.ndarray, regime_lag: np.ndarray) -> dict:
    """d_t = a + b regime_{t-1} + e_t ; HAC (Newey-West) se on b.
    b = extra loss differential in high regime (direct regime-dependence test)."""
    d = np.asarray(d, dtype=float)
    reg = np.asarray(regime_lag, dtype=float)
    valid = np.isfinite(d) & np.isfinite(reg)
    d, reg = d[valid], reg[valid]
    n = len(d)
    X = np.column_stack([np.ones(n), reg])
    beta, *_ = np.linalg.lstsq(X, d, rcond=None)
    resid = d - X @ beta
    L = newey_west_lag(n)
    XtX_inv = np.linalg.inv(X.T @ X)
    # Newey-West meat
    S = np.zeros((2, 2))
    u = X * resid[:, None]
    S += (u.T @ u)
    for j in range(1, L + 1):
        w = 1.0 - j / (L + 1.0)
        G = u[j:].T @ u[:-j]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se_b = float(np.sqrt(cov[1, 1]))
    b = float(beta[1])
    t_b = b / se_b
    p_b = 2 * (1 - scistats.t.cdf(abs(t_b), df=n - 2))
    return {"intercept_a": float(beta[0]), "slope_b": b, "se_b": se_b,
            "t_b": float(t_b), "p_value_b": float(p_b), "nw_lag": int(L), "n": int(n)}


# --------------------------------------------------------------- per asset --
def run_asset(name: str, ohlc: pd.DataFrame, vix: pd.Series,
              period_start: str, period_end: str) -> dict:
    print(f"\n===== {name} ({period_start} -> {period_end}) =====")
    ohlc = ohlc.loc[period_start:period_end]
    px = build_proxies(ohlc)
    r = px["r"]
    assert_price_limit(r, name)   # abort on impossible bad-tick returns

    # regime instrument: lagged VIX vs expanding (past-only) median
    vix = vix.reindex(px.index).ffill().dropna()
    common = px.index.intersection(vix.index)
    px = px.loc[common]
    r = r.loc[common]
    vix = vix.loc[common]
    exp_med = vix.expanding().median()
    regime_now = (vix > exp_med).astype(float)          # regime_t (F_t)
    regime_lag_full = regime_now.shift(1)               # regime_{t-1} (F_{t-1})
    # full-sample-median robustness split
    fs_med = float(vix.median())
    regime_fs_lag_full = (vix.shift(1) > fs_med).astype(float)

    oos_start_idx = MIN_TRAIN[name]
    # GJR forecasts (proxy-independent)
    print("  fitting GJR-GARCH monthly refit ...")
    gjr_fc, gjr_disc = gjr_monthly_forecast(r, oos_start_idx)
    print(f"  GJR arch cross-val max rel discrepancy = {gjr_disc:.2e}")
    # K445 alignment guard: if the manual one-step recursion diverges from arch's
    # own forecast(horizon=1) beyond tolerance, the GJR forecasts are unreliable
    # (typically a bad-tick-poisoned fit) -> abort rather than publish.
    if gjr_disc > GJR_DISC_TOL:
        raise ValueError(
            f"{name}: GJR manual-recursion vs arch forecast(horizon=1) max rel "
            f"discrepancy {gjr_disc:.3e} > tol {GJR_DISC_TOL:.1e} -> unreliable "
            f"GJR alignment (check for bad ticks / non-convergence).")

    proxy_results = {}
    per_proxy_series = {}
    for proxy_name in ["r2", "rsov"]:
        rv = px[proxy_name]
        print(f"  [{proxy_name}] fitting HAR expanding OLS ...")
        har_fc = har_expanding_forecast(rv, oos_start_idx)

        # align HAR, GJR, actual, regime on common OOS dates
        idx = har_fc.index.intersection(gjr_fc.index).intersection(rv.index)
        idx = idx.intersection(regime_lag_full.dropna().index)
        actual = rv.loc[idx].to_numpy()
        f_har = har_fc.loc[idx].to_numpy()
        f_gjr = gjr_fc.loc[idx].to_numpy()

        q_har = qlike_pointwise(actual, f_har)
        q_gjr = qlike_pointwise(actual, f_gjr)
        d = q_har - q_gjr                                # + -> GJR better

        reg_lag = regime_lag_full.loc[idx].to_numpy()
        reg_fs_lag = regime_fs_lag_full.loc[idx].to_numpy()

        # keep finite mask
        mask = np.isfinite(d) & np.isfinite(reg_lag)
        d_m, reg_m, reg_fs_m = d[mask], reg_lag[mask], reg_fs_lag[mask]
        idx_m = idx[mask]

        dm = dm_hln(d_m, h=1)
        gw = gw_conditional_test(d_m, reg_m)
        slope = regime_slope_test(d_m, reg_m)
        slope_fs = regime_slope_test(d_m, reg_fs_m)

        # regime subsample decomposition (expanding-median split)
        hi = reg_m == 1
        lo = reg_m == 0
        def sub(mvec):
            dd = d_m[mvec]
            return {
                "n": int(mvec.sum()),
                "mean_d": float(dd.mean()) if mvec.sum() else float("nan"),
                "qlike_har": float(np.mean(q_har[mask][mvec])),
                "qlike_gjr": float(np.mean(q_gjr[mask][mvec])),
                "winner": ("GJR" if dd.mean() > 0 else "HAR") if mvec.sum() else None,
                "dm_t_hln": dm_hln(dd, h=1)["t_hln"] if mvec.sum() > 10 else None,
            }

        proxy_results[proxy_name] = {
            "n_oos": int(len(d_m)),
            "oos_start": str(idx_m[0].date()),
            "oos_end": str(idx_m[-1].date()),
            "qlike_har_mean": float(np.mean(q_har[mask])),
            "qlike_gjr_mean": float(np.mean(q_gjr[mask])),
            "unconditional_dm": dm,
            "gw_conditional_test": gw,
            "regime_slope_test_expanding_median": slope,
            "regime_slope_test_fullsample_median": slope_fs,
            "regime_subsample_high": sub(hi),
            "regime_subsample_low": sub(lo),
            "n_high_regime": int(hi.sum()),
            "n_low_regime": int(lo.sum()),
        }
        per_proxy_series[proxy_name] = {
            "dates": idx_m, "d": d_m, "regime": reg_m,
        }
        print(f"    [{proxy_name}] n={len(d_m)}  uncond DM t_hln={dm['t_hln']:.3f} (p={dm['p_value']:.3f}) "
              f"| GW chi2={gw['hac']['stat']:.3f} (p={gw['hac']['p_value']:.4f}) "
              f"| regime b={slope['slope_b']:.4f} t={slope['t_b']:.3f} (p={slope['p_value_b']:.4f})")
        print(f"      high-regime mean_d={proxy_results[proxy_name]['regime_subsample_high']['mean_d']:.4f} "
              f"(winner {proxy_results[proxy_name]['regime_subsample_high']['winner']}, n={hi.sum()}) | "
              f"low-regime mean_d={proxy_results[proxy_name]['regime_subsample_low']['mean_d']:.4f} "
              f"(winner {proxy_results[proxy_name]['regime_subsample_low']['winner']}, n={lo.sum()})")

    # proxy-level diagnostic over the OOS window (evidences why pure Parkinson is
    # an invalid proxy for the GJR close-to-close forecast: it is biased low)
    oos_idx = gjr_fc.index.intersection(px.index)
    gjr_oos = gjr_fc.loc[oos_idx]
    diag = {
        "mean_r2": float(px.loc[oos_idx, "r2"].mean()),
        "mean_rsov_range_plus_overnight": float(px.loc[oos_idx, "rsov"].mean()),
        "mean_parkinson_intraday_only": float(px.loc[oos_idx, "parkinson"].mean()),
        "mean_gjr_forecast": float(gjr_oos.mean()),
        "parkinson_over_r2_ratio": float(px.loc[oos_idx, "parkinson"].mean()
                                         / px.loc[oos_idx, "r2"].mean()),
        "note": ("pure-Parkinson mean << r2/rsov/GJR means confirms overnight-gap "
                 "downward bias; pure Parkinson is EXCLUDED from the horse race and "
                 "only r2 (primary) and rsov (robust) are used."),
    }

    return {
        "asset": name,
        "period": [period_start, period_end],
        "gjr_arch_crossval_max_rel_discrepancy": float(gjr_disc),
        "regime_instrument": "VIX_lag1_vs_expanding_median",
        "fullsample_vix_median": fs_med,
        "proxy_level_diagnostic": diag,
        "proxies": proxy_results,
        "_series": per_proxy_series,   # popped before JSON dump
    }


# --------------------------------------------------------------- plotting ---
def plot_asset(res: dict, outpath: str):
    name = res["asset"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for col, proxy in enumerate(["r2", "rsov"]):
        s = res["_series"][proxy]
        pr = res["proxies"][proxy]
        dates = s["dates"]
        d = s["d"]
        reg = s["regime"]
        cum = np.cumsum(d)

        ax = axes[0, col]
        ax.plot(dates, cum, color="#1f77b4", lw=1.1)
        ax.axhline(0, color="k", lw=0.7, ls="--")
        # shade high-regime spans
        hi = reg == 1
        ax.fill_between(dates, cum.min(), cum.max(), where=hi, color="#d62728",
                        alpha=0.12, step="pre", label="high-VIX regime")
        ax.set_title(f"{name} [{proxy}] cumulative d_t = QLIKE_HAR - QLIKE_GJR\n"
                     f"(up = GJR winning) | uncond HAC-DM t={pr['unconditional_dm']['t_hac']:.2f} "
                     f"p={pr['unconditional_dm']['p_value_hac']:.3f}", fontsize=9)
        ax.set_ylabel("cumulative loss differential")
        ax.legend(fontsize=7, loc="upper left")
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.tick_params(labelsize=7)

        ax2 = axes[1, col]
        hm = pr["regime_subsample_high"]["mean_d"]
        lm = pr["regime_subsample_low"]["mean_d"]
        bars = ax2.bar(["low-VIX\nregime", "high-VIX\nregime"], [lm, hm],
                       color=["#2ca02c", "#d62728"], alpha=0.8)
        ax2.axhline(0, color="k", lw=0.8)
        ax2.set_title(f"[{proxy}] mean d_t by regime | GW chi2={pr['gw_conditional_test']['hac']['stat']:.2f} "
                      f"p={pr['gw_conditional_test']['hac']['p_value']:.3f}\n"
                      f"regime-slope b={pr['regime_slope_test_expanding_median']['slope_b']:.4f} "
                      f"t={pr['regime_slope_test_expanding_median']['t_b']:.2f} "
                      f"p={pr['regime_slope_test_expanding_median']['p_value_b']:.3f}", fontsize=9)
        ax2.set_ylabel("mean d_t (+ = GJR better)")
        for b, v in zip(bars, [lm, hm]):
            ax2.text(b.get_x() + b.get_width() / 2, v, f"{v:.3f}",
                     ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
    fig.suptitle(f"K1611 Giacomini-White conditional predictive ability: "
                 f"{name} HAR-RV vs GJR-GARCH", fontsize=12, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(outpath, dpi=130)
    plt.close(fig)
    print(f"  saved {outpath}")


# --------------------------------------------------------------- main -------
def main():
    t0 = datetime.now(timezone.utc)
    results = {
        "experiment_id": "K1611",
        "title": "Giacomini-White (2006) conditional predictive ability: "
                 "HAR-RV vs GJR-GARCH regime-dependence",
        "seed": SEED,
        "run_utc": t0.isoformat(),
        "assets": {},
    }

    # SPY: 2005-2026, ^VIX regime
    spy = load_yf("SPY", "2005-01-01", "2026-07-02")
    vix_us = load_vix_yf("2005-01-01", "2026-07-02")
    res_spy = run_asset("SPY", spy, vix_us, "2005-01-01", "2026-07-01")

    # 0050.TW: clean post-break window 2014-01-06 .. 2021-12-31 (vendor break at
    # 2014-01-02 + unreliable 2009 rows excluded; VIXTWN covers through 2021).
    tw = load_yf("0050.TW", "2009-01-01", "2026-07-02")
    vix_tw = load_vixtwn()
    res_tw = run_asset("0050.TW", tw, vix_tw, "2014-01-06", "2021-12-31")

    for res in (res_spy, res_tw):
        png = os.path.join(HERE, f"K1611_{res['asset'].replace('.', '_')}_gw.png")
        plot_asset(res, png)
        res.pop("_series", None)
        results["assets"][res["asset"]] = res

    # honest verdict synthesis. Regime-dependence is claimed ONLY from the DIRECT
    # regime-slope coefficient (proxy-robust in sign AND significance). A GW joint
    # rejection alone means the models are not conditionally equivalent, NOT that
    # the winner flips with the VIX regime (Codex review MAJOR-1). Unconditional
    # significance uses the conservative HAC-DM (Harvey |t|>3).
    verdict = {}
    for asset, res in results["assets"].items():
        flags = {}
        for px in ["r2", "rsov"]:
            pr = res["proxies"][px]
            sl = pr["regime_slope_test_expanding_median"]
            flags[px] = {
                "uncond_hacdm_harvey_sig": bool(abs(pr["unconditional_dm"]["t_hac"]) > 3.0),
                "uncond_hacdm_t": pr["unconditional_dm"]["t_hac"],
                "gw_hac_sig_5pct": bool(pr["gw_conditional_test"]["hac"]["p_value"] < 0.05),
                "gw_hac_p": pr["gw_conditional_test"]["hac"]["p_value"],
                "regime_slope_sig_5pct": bool(sl["p_value_b"] < 0.05),
                "regime_slope_b": sl["slope_b"],
                "regime_slope_t": sl["t_b"],
            }
        r2f, rsf = flags["r2"], flags["rsov"]
        gw_both = r2f["gw_hac_sig_5pct"] and rsf["gw_hac_sig_5pct"]
        gw_any = r2f["gw_hac_sig_5pct"] or rsf["gw_hac_sig_5pct"]
        uncond_any = r2f["uncond_hacdm_harvey_sig"] or rsf["uncond_hacdm_harvey_sig"]
        slope_robust = (r2f["regime_slope_sig_5pct"] and rsf["regime_slope_sig_5pct"]
                        and np.sign(r2f["regime_slope_b"]) == np.sign(rsf["regime_slope_b"]))
        slope_any = r2f["regime_slope_sig_5pct"] or rsf["regime_slope_sig_5pct"]

        if slope_robust:
            v = ("REGIME-DEPENDENT (robust): the direct VIX-regime slope on the loss "
                 "differential is significant with a consistent sign on BOTH proxies.")
        elif slope_any:
            v = ("regime-dependence SUGGESTIVE but NOT proxy-robust: the direct "
                 "regime-slope is significant on only one proxy.")
        elif gw_both and not uncond_any:
            v = ("CONDITIONAL HETEROGENEITY (no clean regime channel): GW rejects equal "
                 "conditional predictive ability on both proxies, but the direct "
                 "VIX-regime slope is NOT significant on either -> models are not "
                 "conditionally equivalent yet the difference is not attributable to "
                 "the high/low VIX regime (unconditional level and/or other F_{t-1} "
                 "structure), and there is no Harvey-significant unconditional winner.")
        elif gw_any and not uncond_any:
            v = ("weak/proxy-sensitive conditional difference: GW rejects on one proxy "
                 "only; no significant regime slope; no unconditional winner.")
        elif uncond_any and not slope_any:
            v = "unconditional winner (HAC-DM Harvey-significant), NOT regime-dependent."
        else:
            v = "NULL: no unconditional winner and no significant regime-dependence."
        verdict[asset] = {"primary_proxy": "r2", "regime_dependent_robust": bool(slope_robust),
                          "flags": flags, "verdict": v}
    results["verdict"] = verdict

    outp = os.path.join(HERE, "K1611_results.json")
    with open(outp, "w") as f:
        json.dump(results, f, indent=2)
    dt = (datetime.now(timezone.utc) - t0).total_seconds()
    print(f"\nsaved {outp}  (runtime {dt:.1f}s)")
    for a, vd in verdict.items():
        print(f"VERDICT {a}: {vd['verdict']}")


if __name__ == "__main__":
    main()
