"""K1119: BTC native IV (Deribit DVOL) vs US VIX for BTC vol prediction.

Paper 4 Universal IV Sufficiency — crypto case.

Context:
    K916 (MF-GJR on BTC with VIX): QLIKE -2.93% vs GARCH, DM t=-2.81 (Harvey FAIL).
        BTC-VIX lag1 correlation only 0.055 (SPY: 0.547, ~10x weaker).
    K1118 (cross-asset alt-data): BTC used 30-day rolling RV as IV PROXY (DVOL
        not on yfinance) -> weak "native IV" story.
    K1119 NOW: replace that proxy with the REAL Deribit DVOL (2021-03-24 onwards).

Research question:
    Does BTC's own native IV (DVOL) predict future BTC vol — the crypto analogue
    of VIX -> SPY — or does the crypto VIX-sufficiency story break down too?

Hypotheses:
    H1 SUFFICIENT: A4f-DVOL beats GJR on BTC daily vol (DM-HLN |t|>3 at Harvey)
                   AND VaR Trinity PASS -> native IV works for BTC.
    H2 NULL      : DVOL adds no value vs GJR -> BTC is IV-insufficient.
    H3 PARTIAL   : marginal improvement (2 < t < 3) but unstable across sub-periods.

Design:
    Data (UTC aligned, daily):
        BTC-USD log return r_t (yfinance)
        Deribit DVOL close DVOL_t (public API get_volatility_index_data)
        US VIX close VIX_t (yfinance) -- for head-to-head with DVOL
    Panel: 2021-03-24 to 2026-04-13 (constrained by DVOL start).

    Weekly aggregation (Friday-Friday to match K1116/K1118):
        RV_w = sqrt(sum r_t^2 over week)
        DVOL_w = weekly mean of close
        VIX_w = weekly mean of close

    Weekly OLS battery (K1118-style):
        M1 AR1          : y_lag1
        M2 AR1+VIX      : y_lag1 + VIX_lag1   (tests US-VIX channel)
        M3 AR1+DVOL     : y_lag1 + DVOL_lag1  (tests native IV)
        M4 AR1+DVOL+VIX : y_lag1 + DVOL_lag1 + VIX_lag1
        M5 AR1+DVOL+r|lag|: add residual abs-return signal

    Baseline = M1. DM-HLN of all challengers vs M1 on OOS QLIKE.
    Extra DM: M3 vs M2 (does DVOL beat VIX head-to-head?).

    Daily GJR-GARCH vs DVOL-MIDAS long-run overlay (A4f-style):
        GJR(1,1): sigma_t^2 = omega + alpha*r_{t-1}^2 + gamma*r_{t-1}^2*I(r_{t-1}<0)
                              + beta*sigma_{t-1}^2
        A4f-DVOL: sigma_t^2 = g_t * tau_t
                  g_t follows GJR(1,1) with E[g]=1
                  log(tau_t) = m + theta * DVOL^2_{t-1} / 10000
                  (EGS-normalized via E[g]=1 constraint)
        OOS: rolling 252-day window, one-step-ahead forecasts.

    Evaluation:
        QLIKE = mean(log(h) + r^2/h)  (Patton 2011 proxy-robust)
        DM-HLN: Harvey (2016) threshold |t| > 3.0
        VaR @ 1% and 5% (Student-t scaled for excess kurtosis):
            VaR_a = mu - sigma * sqrt((df-2)/df) * t_a(df)
            Kupiec unconditional LR; Christoffersen CC LR; Basel traffic light
        ES @ 1% and 5% (parametric student-t)

    Sub-period stability: 2022 (bear), 2023 (recovery), 2024-2026 (post-halving).

    Lookahead discipline:
        RV_w predicts week w using info through week w-1.
        DVOL_t-1 is Deribit published end-of-day UTC on day t-1 -> known at day t.
        All regressors enter with .shift(1).

References:
    Alexander & Imeraj (2021) "Inferring the BTC index methodology from Deribit DVOL"
    Daniel & Hodrick (1998) -- option-implied vol predictability
    Conrad, Custovic & Ghysels (2018) JFQA -- GARCH-MIDAS
    Engle, Ghysels & Sohn (2013) REStud -- GARCH-MIDAS foundational
    Patton (2011) JoE -- QLIKE proxy-robust
    Harvey, Leybourne, Newbold (1997) IJF -- HLN DM correction
    Kupiec (1995); Christoffersen (1998); Basel Committee (1996)
    K916 -- MF-GJR BTC with VIX, QLIKE -2.93% Harvey FAIL
    K1116/K1118 -- SPY/GLD/TLT/BTC native IV sufficiency (Paper 4 compendium)
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize
from scipy import stats as sst
import statsmodels.api as sm

warnings.filterwarnings("ignore")

OUT = Path(__file__).parent
DATA = OUT / "data"

RESULTS: dict = {
    "experiment_id": "K1119",
    "title": "BTC native IV (Deribit DVOL) vs US VIX — Paper 4 crypto case",
    "started_utc": datetime.now(timezone.utc).isoformat(),
    "data_source": (
        "Deribit DVOL via public API get_volatility_index_data | "
        "yfinance BTC-USD, ^VIX"
    ),
    "period": "2021-03-24 to 2026-04-13 (DVOL-constrained)",
    "predecessors": {
        "K916": "MF-GJR BTC with VIX: QLIKE -2.93%, DM t=-2.81 Harvey FAIL; "
                "BTC-VIX lag1 corr only 0.055 (SPY 0.547)",
        "K1118": "Cross-asset alt-data sufficiency; BTC used 30-day rolling "
                 "RV as IV PROXY because DVOL not on yfinance",
        "K1116": "SPY native VIX sufficient vs EPU/NFCI/STLFSI",
    },
    "hypotheses": {
        "H1_SUFFICIENT": "DVOL beats GJR (|t|>3) AND VaR Trinity PASS",
        "H2_NULL": "DVOL adds no value",
        "H3_PARTIAL": "marginal 2<|t|<3 or unstable across sub-periods",
    },
    "references": [
        "Deribit API docs (public get_volatility_index_data)",
        "Conrad, Custovic, Ghysels (2018) JFQA — GARCH-MIDAS on crypto",
        "Engle, Ghysels, Sohn (2013) REStud — GARCH-MIDAS",
        "Patton (2011) JoE — QLIKE proxy-robust",
        "Harvey, Leybourne, Newbold (1997) IJF — HLN DM correction",
        "Kupiec (1995); Christoffersen (1998)",
        "K916, K1116, K1118 — VolPred internal predecessors",
    ],
}


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------

def load_panels():
    btc = pd.read_csv(DATA / "btc_ohlcv.csv", parse_dates=["date"]).set_index("date")
    dvol = pd.read_csv(DATA / "dvol_daily.csv", parse_dates=["date"]).set_index("date")
    vix = pd.read_csv(DATA / "vix_daily.csv", parse_dates=["date"]).set_index("date")

    btc["log_r"] = np.log(btc["Close"]).diff()
    dvol = dvol.rename(columns={"close": "dvol"})[["dvol"]]
    # BTC trades 7d, DVOL published 7d, VIX only 5d (US trading days)
    daily = btc[["Close", "log_r"]].join(dvol, how="left").join(vix[["vix"]], how="left")
    # Forward-fill VIX over weekends to align (at most 3 days)
    daily["vix"] = daily["vix"].ffill(limit=3)
    # Only keep rows where DVOL exists (defines sample)
    daily = daily.dropna(subset=["dvol"]).copy()
    return daily


def daily_to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily.copy()
    df["week"] = df.index.to_period("W-FRI").to_timestamp("W-FRI")
    g = df.groupby("week")
    weekly = pd.DataFrame({
        "rv": g["log_r"].apply(lambda x: np.sqrt(np.nansum(x.dropna() ** 2))),
        "n_days": g["log_r"].count(),
        "dvol_mean": g["dvol"].mean(),
        "dvol_last": g["dvol"].last(),
        "vix_mean": g["vix"].mean(),
        "vix_last": g["vix"].last(),
        "ret_sum": g["log_r"].apply(lambda x: np.nansum(x.dropna())),
    })
    weekly = weekly[weekly["n_days"] >= 5].dropna(subset=["rv", "dvol_mean"]).sort_index()
    return weekly


# ---------------------------------------------------------------------
# Weekly OLS battery
# ---------------------------------------------------------------------

def weekly_battery(weekly: pd.DataFrame, is_end: str, oos_start: str) -> dict:
    df = weekly.copy()
    df_is = df.loc[:is_end]
    df_oos = df.loc[oos_start:]

    def make_X(sub: pd.DataFrame, spec: str) -> pd.DataFrame:
        X = pd.DataFrame(index=sub.index)
        X["y_lag1"] = sub["rv"].shift(1)
        if spec == "M1":
            pass
        elif spec == "M2":
            X["vix_lag1"] = sub["vix_mean"].shift(1)
        elif spec == "M3":
            X["dvol_lag1"] = sub["dvol_mean"].shift(1)
        elif spec == "M4":
            X["dvol_lag1"] = sub["dvol_mean"].shift(1)
            X["vix_lag1"] = sub["vix_mean"].shift(1)
        elif spec == "M5":
            X["dvol_lag1"] = sub["dvol_mean"].shift(1)
            X["absr_lag1"] = sub["ret_sum"].abs().shift(1)
        return X.dropna()

    specs = ["M1", "M2", "M3", "M4", "M5"]
    names = {
        "M1": "M1_AR1",
        "M2": "M2_AR1_VIX",
        "M3": "M3_AR1_DVOL",
        "M4": "M4_AR1_DVOL_VIX",
        "M5": "M5_AR1_DVOL_absr",
    }
    fitted: dict = {}
    oos_losses: dict = {}
    oos_forecasts: dict = {}
    is_records: dict = {}

    for spec in specs:
        name = names[spec]
        X_is = make_X(df_is, spec)
        y_is = df_is["rv"].loc[X_is.index]
        Xc_is = sm.add_constant(X_is, has_constant="add")
        ols = sm.OLS(y_is, Xc_is).fit()
        fitted[name] = (ols, Xc_is.columns.tolist())
        is_records[name] = {
            "r2": float(ols.rsquared),
            "adj_r2": float(ols.rsquared_adj),
            "aic": float(ols.aic),
            "bic": float(ols.bic),
            "n": int(len(y_is)),
            "params": {k: float(v) for k, v in ols.params.to_dict().items()},
            "pvalues": {k: float(v) for k, v in ols.pvalues.to_dict().items()},
        }
        X_oos = make_X(df_oos, spec)
        Xc_oos = sm.add_constant(X_oos, has_constant="add").reindex(columns=Xc_is.columns, fill_value=0.0)
        pred = ols.predict(Xc_oos).clip(lower=1e-6)
        actual = df_oos["rv"].loc[X_oos.index]
        oos_forecasts[name] = {"pred": pred, "actual": actual}
        eps = 1e-10
        pred_sq = np.maximum(pred.values ** 2, eps)
        actual_sq = np.maximum(actual.values ** 2, eps)
        oos_losses[name] = pd.Series(
            np.log(pred_sq) + actual_sq / pred_sq, index=pred.index
        )

    return {
        "fitted": fitted,
        "oos_losses": oos_losses,
        "oos_forecasts": oos_forecasts,
        "is_records": is_records,
        "names": names,
    }


# ---------------------------------------------------------------------
# DM-HLN
# ---------------------------------------------------------------------

def dm_hln(e1, e2, h: int = 1):
    d = np.asarray(e1, dtype=float) - np.asarray(e2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    dbar = d.mean()
    g0 = float(np.var(d, ddof=1))
    if g0 <= 0:
        return np.nan, np.nan
    corr = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(g0 / n)
    t = (dbar / se) * corr
    p = 2 * (1 - sst.t.cdf(abs(t), df=n - 1))
    return float(t), float(p)


def qlike(actual, pred):
    eps = 1e-10
    actual = np.maximum(actual, eps)
    pred = np.maximum(pred, eps)
    return float(np.mean(np.log(pred) + actual / pred))


# ---------------------------------------------------------------------
# Daily GJR-GARCH (pure) + A4f-DVOL (GARCH-MIDAS style)
# ---------------------------------------------------------------------

def _gjr_loglik(params, r):
    omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or gamma < -alpha:
        return 1e10
    if alpha + 0.5 * gamma + beta >= 0.9999:
        return 1e10
    T = len(r)
    h = np.empty(T)
    h[0] = np.var(r)
    ll = 0.0
    for t in range(1, T):
        h[t] = omega + alpha * r[t - 1] ** 2 + gamma * r[t - 1] ** 2 * (r[t - 1] < 0) + beta * h[t - 1]
        if h[t] <= 0:
            return 1e10
        ll += 0.5 * (np.log(2 * np.pi) + np.log(h[t]) + r[t] ** 2 / h[t])
    return ll


def fit_gjr(r: np.ndarray) -> dict:
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    r = r - r.mean()
    var_r = np.var(r)
    x0 = [0.1 * var_r, 0.05, 0.05, 0.9]
    bounds = [(1e-10, None), (0, 0.4), (-0.3, 0.5), (0, 0.999)]
    res = optimize.minimize(_gjr_loglik, x0, args=(r,), method="L-BFGS-B", bounds=bounds)
    omega, alpha, gamma, beta = res.x
    T = len(r)
    h = np.empty(T)
    h[0] = np.var(r)
    for t in range(1, T):
        h[t] = omega + alpha * r[t - 1] ** 2 + gamma * r[t - 1] ** 2 * (r[t - 1] < 0) + beta * h[t - 1]
    # forecast for t+1 using last observed r
    next_h = omega + alpha * r[-1] ** 2 + gamma * r[-1] ** 2 * (r[-1] < 0) + beta * h[-1]
    return {
        "params": {"omega": float(omega), "alpha": float(alpha), "gamma": float(gamma), "beta": float(beta)},
        "success": bool(res.success),
        "neg_loglik": float(res.fun),
        "persistence": float(alpha + 0.5 * gamma + beta),
        "h_insample": h,
        "next_h": float(next_h),
        "r_demean": r,
    }


def _a4f_dvol_loglik(params, r, dvol2_scaled):
    m, theta, alpha, gamma, beta = params
    if alpha < 0 or beta < 0 or gamma < -alpha:
        return 1e10
    if alpha + 0.5 * gamma + beta >= 0.9999:
        return 1e10
    T = len(r)
    tau = np.exp(m + theta * dvol2_scaled)
    g = np.ones(T)
    ll = 0.0
    for t in range(1, T):
        eps_prev = r[t - 1] / np.sqrt(max(g[t - 1] * tau[t - 1], 1e-12))
        g[t] = (1 - alpha - 0.5 * gamma - beta) + alpha * eps_prev ** 2 + gamma * eps_prev ** 2 * (r[t - 1] < 0) + beta * g[t - 1]
        if g[t] <= 0:
            return 1e10
        h_t = g[t] * tau[t]
        if h_t <= 0:
            return 1e10
        ll += 0.5 * (np.log(2 * np.pi) + np.log(h_t) + r[t] ** 2 / h_t)
    return ll


def fit_a4f_dvol(r: np.ndarray, dvol: np.ndarray) -> dict:
    r = np.asarray(r, dtype=float)
    dvol = np.asarray(dvol, dtype=float)
    mask = ~(np.isnan(r) | np.isnan(dvol))
    r = r[mask]
    dvol = dvol[mask]
    r = r - r.mean()
    # DVOL in percent (e.g., 60 => 60% annualized). Convert to daily variance
    # then standardize so theta is scale-free and the optimizer stays well behaved.
    dvol2 = (dvol / 100.0) ** 2 / 252.0  # annualized var -> daily var
    dvol2_std = dvol2.std()
    if dvol2_std <= 0:
        dvol2_std = 1.0
    dvol2c = (dvol2 - dvol2.mean()) / dvol2_std  # unit-std z-score
    var_r = np.var(r)
    x0 = [np.log(var_r), 0.1, 0.05, 0.05, 0.85]
    bounds = [(None, None), (-5.0, 5.0), (0, 0.4), (-0.3, 0.5), (0, 0.999)]
    res = optimize.minimize(
        _a4f_dvol_loglik, x0, args=(r, dvol2c), method="L-BFGS-B", bounds=bounds
    )
    m, theta, alpha, gamma, beta = res.x
    T = len(r)
    tau = np.exp(m + theta * dvol2c)
    g = np.ones(T)
    for t in range(1, T):
        eps_prev = r[t - 1] / np.sqrt(max(g[t - 1] * tau[t - 1], 1e-12))
        g[t] = (1 - alpha - 0.5 * gamma - beta) + alpha * eps_prev ** 2 + gamma * eps_prev ** 2 * (r[t - 1] < 0) + beta * g[t - 1]
    h_insample = g * tau
    # forecast t+1 using last info; dvol2c[-1] is the last known dvol (already lag-safe because
    # we always match DVOL_t with r_t and forecast h_{t+1})
    eps_last = r[-1] / np.sqrt(max(g[-1] * tau[-1], 1e-12))
    g_next = (1 - alpha - 0.5 * gamma - beta) + alpha * eps_last ** 2 + gamma * eps_last ** 2 * (r[-1] < 0) + beta * g[-1]
    next_h = g_next * tau[-1]  # tau uses DVOL known at t (lag-safe forecasting of t+1)
    return {
        "params": {
            "m": float(m), "theta": float(theta),
            "alpha": float(alpha), "gamma": float(gamma), "beta": float(beta),
        },
        "success": bool(res.success),
        "neg_loglik": float(res.fun),
        "persistence_g": float(alpha + 0.5 * gamma + beta),
        "h_insample": h_insample,
        "next_h": float(next_h),
        "r_demean": r,
        "dvol2c": dvol2c,
    }


def rolling_oos_daily(daily: pd.DataFrame, window: int = 504) -> dict:
    """Rolling-window one-step-ahead forecasts: GJR vs A4f-DVOL.

    window: training window size (days). 504 = ~2y.
    """
    r_all = daily["log_r"].values
    dvol_all = daily["dvol"].values
    idx = daily.index
    T = len(daily)
    records = []
    log(f"Rolling OOS: T={T}, window={window}, OOS length={T - window}")
    next_progress = window + 50
    for t in range(window, T):
        r_train = r_all[t - window:t]
        dvol_train = dvol_all[t - window:t]
        r_t = r_all[t]  # realised return at t (target for h_t forecast made at t-1... see note)
        # We build training on [t-window, t), use info through t-1 to forecast h_t.
        # fit_gjr / fit_a4f return next_h = h_t forecast using info up to t-1.
        try:
            gjr = fit_gjr(r_train)
            a4f = fit_a4f_dvol(r_train, dvol_train)
        except Exception as e:
            log(f"  fit failed at t={t}: {e}")
            continue
        records.append({
            "date": idx[t],
            "r_t": float(r_t),
            "r2_t": float(r_t ** 2),
            "h_gjr": float(gjr["next_h"]),
            "h_a4f": float(a4f["next_h"]),
            "gjr_alpha": gjr["params"]["alpha"],
            "gjr_beta": gjr["params"]["beta"],
            "gjr_gamma": gjr["params"]["gamma"],
            "gjr_persist": gjr["persistence"],
            "a4f_theta": a4f["params"]["theta"],
            "a4f_persist_g": a4f["persistence_g"],
        })
        if t >= next_progress:
            log(f"  progress t={t}/{T} date={idx[t].date()}")
            next_progress = t + 100
    return {"records": records}


# ---------------------------------------------------------------------
# VaR / ES
# ---------------------------------------------------------------------

def student_t_df_from_returns(z: np.ndarray) -> float:
    # Maximum likelihood fit of df from standardized residuals
    z = z[~np.isnan(z)]
    try:
        df, _, _ = sst.t.fit(z, floc=0, fscale=1)
        return max(2.5, min(df, 50))
    except Exception:
        return 7.0


def var_es_student_t(h: np.ndarray, df: float, alpha: float) -> tuple[np.ndarray, np.ndarray]:
    sigma = np.sqrt(np.maximum(h, 1e-12))
    # Scale correction so Var(sigma*T) = sigma^2
    scale = np.sqrt((df - 2) / df)
    q = sst.t.ppf(alpha, df=df)  # negative (left tail)
    var = sigma * scale * q  # negative loss threshold
    # ES_alpha closed-form for Student-t
    pdf_q = sst.t.pdf(q, df=df)
    es = -sigma * scale * (df + q ** 2) / (df - 1) * pdf_q / alpha
    return var, es


def kupiec_test(hits: np.ndarray, alpha: float) -> dict:
    n = len(hits)
    x = int(np.sum(hits))
    p_hat = x / n if n > 0 else np.nan
    if x == 0 or x == n:
        lr = 0.0
    else:
        lr = -2 * (x * np.log(alpha) + (n - x) * np.log(1 - alpha)
                   - x * np.log(p_hat) - (n - x) * np.log(1 - p_hat))
    p = 1 - sst.chi2.cdf(lr, df=1)
    return {"n": int(n), "violations": int(x), "rate": float(p_hat),
            "LR": float(lr), "p_value": float(p), "pass": bool(p > 0.05)}


def cc_test(hits: np.ndarray, alpha: float) -> dict:
    n = len(hits)
    if n < 2:
        return {"LR_ind": np.nan, "LR_cc": np.nan, "p_value": np.nan, "pass": False}
    # Christoffersen CC = LR_uc + LR_ind
    t00 = t01 = t10 = t11 = 0
    for i in range(1, n):
        if hits[i - 1] == 0 and hits[i] == 0:
            t00 += 1
        elif hits[i - 1] == 0 and hits[i] == 1:
            t01 += 1
        elif hits[i - 1] == 1 and hits[i] == 0:
            t10 += 1
        elif hits[i - 1] == 1 and hits[i] == 1:
            t11 += 1
    if (t01 + t11) == 0 or (t00 + t10) == 0:
        lr_ind = 0.0
    else:
        p01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        p11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi = (t01 + t11) / (t00 + t01 + t10 + t11)
        if 0 < p01 < 1 and 0 < p11 < 1 and 0 < pi < 1:
            l_null = (t00 + t10) * np.log(1 - pi) + (t01 + t11) * np.log(pi)
            l_alt = (t00 * np.log(1 - p01) if t00 > 0 else 0) + (t01 * np.log(p01) if t01 > 0 else 0) \
                    + (t10 * np.log(1 - p11) if t10 > 0 else 0) + (t11 * np.log(p11) if t11 > 0 else 0)
            lr_ind = -2 * (l_null - l_alt)
        else:
            lr_ind = 0.0
    kup = kupiec_test(hits, alpha)
    lr_cc = kup["LR"] + lr_ind
    p = 1 - sst.chi2.cdf(lr_cc, df=2)
    return {
        "LR_uc": kup["LR"], "LR_ind": float(lr_ind), "LR_cc": float(lr_cc),
        "p_value": float(p), "pass": bool(p > 0.05),
        "violations": kup["violations"], "rate": kup["rate"], "n": kup["n"],
    }


def basel_light(hits: np.ndarray) -> str:
    # Basel uses 250-day rolling; here we just classify total violations
    n = len(hits)
    x = int(np.sum(hits))
    if n < 100:
        return "insufficient"
    # Expected 2.5 at 1% over 250 days
    expected = 0.01 * n
    if x <= expected * 1.6:
        return "green"
    elif x <= expected * 2.5:
        return "yellow"
    else:
        return "red"


def var_trinity(oos_r: np.ndarray, h_gjr: np.ndarray, h_a4f: np.ndarray,
                z_gjr: np.ndarray, z_a4f: np.ndarray) -> dict:
    df_gjr = student_t_df_from_returns(z_gjr)
    df_a4f = student_t_df_from_returns(z_a4f)
    out: dict = {"df_gjr": df_gjr, "df_a4f": df_a4f}
    for alpha in (0.01, 0.05):
        var_g, es_g = var_es_student_t(h_gjr, df_gjr, alpha)
        var_a, es_a = var_es_student_t(h_a4f, df_a4f, alpha)
        hits_g = (oos_r < var_g).astype(int)
        hits_a = (oos_r < var_a).astype(int)
        out[f"alpha_{alpha:.2f}"] = {
            "GJR": {
                "kupiec": kupiec_test(hits_g, alpha),
                "cc": cc_test(hits_g, alpha),
                "basel": basel_light(hits_g),
                "mean_VaR": float(np.mean(var_g)),
                "mean_ES": float(np.mean(es_g)),
            },
            "A4f_DVOL": {
                "kupiec": kupiec_test(hits_a, alpha),
                "cc": cc_test(hits_a, alpha),
                "basel": basel_light(hits_a),
                "mean_VaR": float(np.mean(var_a)),
                "mean_ES": float(np.mean(es_a)),
            },
        }
        # Trinity pass
        for model in ("GJR", "A4f_DVOL"):
            out[f"alpha_{alpha:.2f}"][model]["trinity_PASS"] = bool(
                out[f"alpha_{alpha:.2f}"][model]["kupiec"]["pass"]
                and out[f"alpha_{alpha:.2f}"][model]["cc"]["pass"]
                and out[f"alpha_{alpha:.2f}"][model]["basel"] == "green"
            )
    return out


# ---------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------

def plot_dvol_vs_vix(daily: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(daily.index, daily["dvol"], color="#d62728", lw=1.2, label="Deribit DVOL (BTC IV)")
    ax2 = ax.twinx()
    ax2.plot(daily.index, daily["vix"], color="#1f77b4", lw=1.0, label="CBOE VIX", alpha=0.85)
    ax.set_ylabel("DVOL (%)", color="#d62728")
    ax2.set_ylabel("VIX (%)", color="#1f77b4")
    ax.set_title("K1119 — BTC Deribit DVOL vs CBOE VIX (daily UTC, 2021-03 to 2026-04)")
    ax.set_xlabel("Date")
    fig.autofmt_xdate()
    corr = daily[["dvol", "vix"]].dropna().corr().iloc[0, 1]
    ax.text(0.02, 0.05, f"Pearson corr (daily, aligned) = {corr:.3f}",
            transform=ax.transAxes, fontsize=9, bbox=dict(boxstyle="round", fc="w", alpha=0.8))
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_qlike_timeseries(records: list, out_path: Path) -> None:
    df = pd.DataFrame(records)
    df = df.set_index("date").sort_index()
    # daily QLIKE-per-observation for visualization
    eps = 1e-12
    df["qlike_gjr"] = np.log(df["h_gjr"].clip(lower=eps)) + df["r2_t"] / df["h_gjr"].clip(lower=eps)
    df["qlike_a4f"] = np.log(df["h_a4f"].clip(lower=eps)) + df["r2_t"] / df["h_a4f"].clip(lower=eps)
    # 30d rolling mean
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(df.index, df["qlike_gjr"].rolling(30).mean(), color="#7f7f7f", lw=1.2, label="GJR (30d MA)")
    ax.plot(df.index, df["qlike_a4f"].rolling(30).mean(), color="#d62728", lw=1.2, label="A4f-DVOL (30d MA)")
    ax.axhline(0, color="k", lw=0.3, alpha=0.4)
    ax.set_title("K1119 — Rolling 30d QLIKE: GJR vs A4f-DVOL (daily one-step-ahead, OOS)")
    ax.set_ylabel("QLIKE (lower better)")
    ax.set_xlabel("Date")
    ax.legend(loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> int:
    np.random.seed(42)
    log("K1119 start: BTC DVOL vs VIX")

    daily = load_panels()
    log(f"Daily panel: n={len(daily)} range={daily.index.min().date()}..{daily.index.max().date()}")
    RESULTS["daily_n"] = int(len(daily))
    RESULTS["daily_start"] = str(daily.index.min().date())
    RESULTS["daily_end"] = str(daily.index.max().date())

    # Descriptive
    desc = {}
    for col in ["log_r", "dvol", "vix"]:
        s = daily[col].dropna()
        desc[col] = {
            "n": int(len(s)), "mean": float(s.mean()), "std": float(s.std()),
            "skew": float(s.skew()), "kurt": float(s.kurt()),
            "min": float(s.min()), "max": float(s.max()),
        }
    corr = daily[["dvol", "vix", "log_r"]].corr().to_dict()
    desc["corr"] = corr
    RESULTS["descriptive_daily"] = desc
    log(
        f"  DVOL mean={desc['dvol']['mean']:.2f}%  VIX mean={desc['vix']['mean']:.2f}%  "
        f"corr(DVOL,VIX)={daily[['dvol','vix']].dropna().corr().iloc[0,1]:.3f}"
    )

    # Weekly battery
    weekly = daily_to_weekly(daily)
    log(f"Weekly panel: n={len(weekly)}")
    RESULTS["weekly_n"] = int(len(weekly))

    # Use 2021-2023 as IS, 2024-2026 as OOS (balance sample)
    is_end = "2023-12-31"
    oos_start = "2024-01-01"
    bat = weekly_battery(weekly, is_end, oos_start)
    RESULTS["weekly"] = {
        "is_end": is_end, "oos_start": oos_start,
        "is_records": bat["is_records"],
    }

    # Weekly DM vs M1 and head-to-head
    names = list(bat["names"].values())
    baseline_name = bat["names"]["M1"]
    common = bat["oos_losses"][baseline_name].index
    for n in names:
        common = common.intersection(bat["oos_losses"][n].index)
    base_loss = bat["oos_losses"][baseline_name].reindex(common).values

    weekly_dm = {}
    weekly_qlike = {}
    for name in names:
        l = bat["oos_losses"][name].reindex(common).values
        weekly_qlike[name] = float(np.mean(l))
    for name in names:
        if name == baseline_name:
            continue
        l = bat["oos_losses"][name].reindex(common).values
        t, p = dm_hln(base_loss, l)
        weekly_dm[f"{baseline_name}_vs_{name}"] = {
            "t_stat": t, "p_value": p,
            "harvey_pass_challenger_beats": bool(t > 3.0),
            "harvey_pass_baseline_beats": bool(t < -3.0),
            "standard_pass_challenger_beats": bool(t > 1.96),
        }
    # Head-to-head DVOL vs VIX
    e2 = bat["oos_losses"][bat["names"]["M2"]].reindex(common).values
    e3 = bat["oos_losses"][bat["names"]["M3"]].reindex(common).values
    t, p = dm_hln(e2, e3)
    weekly_dm["M2_AR1_VIX_vs_M3_AR1_DVOL"] = {
        "t_stat": t, "p_value": p,
        "interpretation": ("DVOL beats VIX" if t and t > 0 else "VIX beats DVOL or tie"),
    }
    RESULTS["weekly"]["oos_qlike"] = weekly_qlike
    RESULTS["weekly"]["dm_tests"] = weekly_dm
    RESULTS["weekly"]["oos_n"] = int(len(common))
    log(
        f"Weekly OOS QLIKE: M1={weekly_qlike[bat['names']['M1']]:.4f}  "
        f"M2(VIX)={weekly_qlike[bat['names']['M2']]:.4f}  "
        f"M3(DVOL)={weekly_qlike[bat['names']['M3']]:.4f}  "
        f"M4={weekly_qlike[bat['names']['M4']]:.4f}  "
        f"M5={weekly_qlike[bat['names']['M5']]:.4f}"
    )

    # ---- Daily rolling GJR vs A4f-DVOL ----
    window = 504
    roll = rolling_oos_daily(daily, window=window)
    records = roll["records"]
    if not records:
        log("Rolling OOS produced 0 records — aborting.")
        RESULTS["daily"] = {"status": "failed"}
        (OUT / "k1119_results.json").write_text(json.dumps(RESULTS, indent=2, default=str))
        return 1

    df_r = pd.DataFrame(records).set_index("date").sort_index()
    eps = 1e-12
    df_r["qlike_gjr"] = np.log(df_r["h_gjr"].clip(lower=eps)) + df_r["r2_t"] / df_r["h_gjr"].clip(lower=eps)
    df_r["qlike_a4f"] = np.log(df_r["h_a4f"].clip(lower=eps)) + df_r["r2_t"] / df_r["h_a4f"].clip(lower=eps)

    qlike_gjr = float(df_r["qlike_gjr"].mean())
    qlike_a4f = float(df_r["qlike_a4f"].mean())
    t_dm, p_dm = dm_hln(df_r["qlike_gjr"].values, df_r["qlike_a4f"].values)
    improvement_pct = (qlike_gjr - qlike_a4f) / abs(qlike_gjr) * 100

    # Sub-period DM
    sub_dm: dict = {}
    for label, mask in (
        ("2023", df_r.index.year == 2023),
        ("2024", df_r.index.year == 2024),
        ("2025", df_r.index.year == 2025),
        ("2026", df_r.index.year == 2026),
    ):
        n_yr = int(mask.sum())
        if n_yr < 30:
            sub_dm[label] = {"n": n_yr, "note": "insufficient"}
            continue
        sub = df_r[mask]
        t, p = dm_hln(sub["qlike_gjr"].values, sub["qlike_a4f"].values)
        sub_dm[label] = {
            "n": n_yr,
            "qlike_gjr": float(sub["qlike_gjr"].mean()),
            "qlike_a4f": float(sub["qlike_a4f"].mean()),
            "dm_t": t, "dm_p": p,
            "harvey_pass_a4f_beats": bool(t and t > 3.0),
            "harvey_pass_gjr_beats": bool(t and t < -3.0),
        }

    # VaR/ES trinity
    z_gjr = df_r["r_t"].values / np.sqrt(df_r["h_gjr"].clip(lower=eps).values)
    z_a4f = df_r["r_t"].values / np.sqrt(df_r["h_a4f"].clip(lower=eps).values)
    var_block = var_trinity(df_r["r_t"].values, df_r["h_gjr"].values, df_r["h_a4f"].values,
                            z_gjr, z_a4f)

    # Average parameters
    avg_params = {
        "gjr_alpha": float(df_r["gjr_alpha"].mean()),
        "gjr_beta": float(df_r["gjr_beta"].mean()),
        "gjr_gamma": float(df_r["gjr_gamma"].mean()),
        "gjr_persist": float(df_r["gjr_persist"].mean()),
        "a4f_theta": float(df_r["a4f_theta"].mean()),
        "a4f_theta_median": float(df_r["a4f_theta"].median()),
        "a4f_theta_share_positive": float((df_r["a4f_theta"] > 0).mean()),
        "a4f_persist_g": float(df_r["a4f_persist_g"].mean()),
    }

    RESULTS["daily"] = {
        "training_window": window,
        "oos_n": int(len(df_r)),
        "oos_start": str(df_r.index.min().date()),
        "oos_end": str(df_r.index.max().date()),
        "oos_qlike_GJR": qlike_gjr,
        "oos_qlike_A4f_DVOL": qlike_a4f,
        "qlike_improvement_pct_A4f_over_GJR": float(improvement_pct),
        "dm_A4f_minus_GJR": {
            "t_stat": t_dm, "p_value": p_dm,
            "sign_convention": "positive t => A4f-DVOL beats GJR",
            "harvey_pass_A4f_beats_GJR": bool(t_dm and t_dm > 3.0),
            "harvey_pass_GJR_beats_A4f": bool(t_dm and t_dm < -3.0),
            "standard_pass_A4f_beats_GJR": bool(t_dm and t_dm > 1.96),
        },
        "subperiod_dm": sub_dm,
        "avg_params": avg_params,
        "var_es_trinity": var_block,
    }
    log(
        f"Daily OOS QLIKE  GJR={qlike_gjr:.4f}  A4f-DVOL={qlike_a4f:.4f}  "
        f"improvement={improvement_pct:+.2f}%  DM t={t_dm:+.3f} p={p_dm:.4f}"
    )

    # Verdict
    daily_beats = bool(RESULTS["daily"]["dm_A4f_minus_GJR"]["harvey_pass_A4f_beats_GJR"])
    daily_worse = bool(RESULTS["daily"]["dm_A4f_minus_GJR"]["harvey_pass_GJR_beats_A4f"])
    qlike_gate = improvement_pct > 5.0
    var_pass_01 = var_block["alpha_0.01"]["A4f_DVOL"]["trinity_PASS"]
    var_pass_05 = var_block["alpha_0.05"]["A4f_DVOL"]["trinity_PASS"]
    stability = sum(
        1 for v in sub_dm.values() if isinstance(v, dict) and v.get("harvey_pass_a4f_beats", False)
    )

    if daily_beats and qlike_gate and (var_pass_01 or var_pass_05):
        verdict = "H1_SUFFICIENT"
    elif daily_worse or not bool(t_dm and t_dm > 2.0):
        verdict = "H2_NULL"
    else:
        verdict = "H3_PARTIAL"

    RESULTS["verdict"] = verdict
    RESULTS["decision_trace"] = {
        "A4f_beats_GJR_Harvey": daily_beats,
        "GJR_beats_A4f_Harvey": daily_worse,
        "QLIKE_improvement_gt_5pct": bool(qlike_gate),
        "VaR_trinity_PASS_1pct": bool(var_pass_01),
        "VaR_trinity_PASS_5pct": bool(var_pass_05),
        "subperiod_a4f_wins_count": stability,
    }

    # Paper 4 narrative
    if verdict == "H1_SUFFICIENT":
        narrative = (
            "Paper 4 extension: crypto native IV (DVOL) IS sufficient for BTC vol — "
            "US VIX was the wrong instrument in K916/K1118, not the hypothesis. "
            "Native IV sufficiency extends to crypto when the right IV is used."
        )
    elif verdict == "H2_NULL":
        narrative = (
            "Paper 4 extension: even native DVOL fails to beat pure GJR for BTC. "
            "Crypto is an IV-insufficient asset class — consistent with K1118's "
            "BTC EPU/NFCI/FinStress null. Native IV helps SPY/GLD/TLT but NOT BTC."
        )
    else:
        narrative = (
            "Paper 4 extension: DVOL shows marginal but not Harvey-robust improvement; "
            "crypto IV adds information in some sub-periods (post-halving) but not "
            "universally. Classify as PARTIAL — needs longer history or "
            "regime-conditional spec."
        )
    RESULTS["paper4_narrative"] = narrative

    # Self-skepticism per preamble rule #5
    if t_dm is not None and abs(t_dm) > 6.0:
        RESULTS["self_skepticism_flag"] = (
            f"DVOL A4f |t|={abs(t_dm):.2f} exceeds 6.0 — crypto high-vol regime may "
            "inflate DM statistic. Inspect rolling QLIKE series, re-run with wider "
            "training window, and check that DVOL lag is truly t-1 (no same-day leak)."
        )

    # ---- Plots ----
    plot_dvol_vs_vix(daily, OUT / "k1119_dvol_vs_vix.png")
    log(f"Saved plot -> {OUT / 'k1119_dvol_vs_vix.png'}")
    plot_qlike_timeseries(records, OUT / "k1119_qlike_timeseries.png")
    log(f"Saved plot -> {OUT / 'k1119_qlike_timeseries.png'}")

    RESULTS["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (OUT / "k1119_results.json").write_text(json.dumps(RESULTS, indent=2, default=str))
    log(f"Saved -> {OUT / 'k1119_results.json'}")

    # Summary print
    print("\n" + "=" * 90)
    print("K1119 SUMMARY — BTC native IV (DVOL) vs US VIX")
    print("=" * 90)
    print(f"Panel: {daily.index.min().date()}..{daily.index.max().date()}, daily n={len(daily)} weekly n={len(weekly)}")
    print(f"DVOL mean={desc['dvol']['mean']:.2f}  VIX mean={desc['vix']['mean']:.2f}  "
          f"corr(DVOL,VIX) daily={daily[['dvol','vix']].dropna().corr().iloc[0,1]:.3f}")
    print("\n-- Weekly battery (OOS 2024+) --")
    for n in names:
        print(f"  {n:<20} OOS QLIKE = {weekly_qlike[n]:.4f}")
    for k, v in weekly_dm.items():
        print(f"  DM {k}: t={v.get('t_stat')} p={v.get('p_value')}")
    print("\n-- Daily rolling GJR vs A4f-DVOL --")
    print(f"  OOS window={window}  n_oos={len(df_r)}")
    print(f"  QLIKE: GJR={qlike_gjr:.4f}  A4f-DVOL={qlike_a4f:.4f}  improvement {improvement_pct:+.2f}%")
    print(f"  DM t={t_dm:+.3f} p={p_dm:.4f}  (Harvey t>3 for A4f wins)")
    print(f"  Sub-period wins (A4f beats GJR, Harvey): {stability}")
    print("\n-- VaR Trinity --")
    for a in ("0.01", "0.05"):
        blk = var_block[f"alpha_{a}"]
        print(f"  alpha={a}  GJR trinity={blk['GJR']['trinity_PASS']}  A4f trinity={blk['A4f_DVOL']['trinity_PASS']}")
    print(f"\nVERDICT: {verdict}")
    print(f"Paper 4 narrative: {narrative}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
