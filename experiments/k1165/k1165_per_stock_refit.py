#!/usr/bin/env python3
"""K1165 per-stock θ_EAV refit for 3 NEW markets (KR, CA, HK) + pooled θ_EAV.

Reuses K1166 spec exactly:
 - GJR(1,1) with Engle-Ghysels-Sohn (2013) E[g]=1 normalization
 - τ_t = max(θ0 + θ_VIX·VIX²_{t-1} + θ_EAV·EAV_{i,t-1}, ε)
 - 6 free params per stock: (θ0, α, γ, β, θ_VIX, θ_EAV)
 - multi-start L-BFGS-B, Hessian SE for θ_EAV

Also runs pooled MLE per market (K1145/K1147/K1150/K1153 spec):
 - shared (θ0, θ_VIX, θ_EAV) across stocks
 - per-stock (m_i, GJR_i)  — here simplified to shared GJR params for speed
   (matches the "market-level pooled" protocol we inherit: 4 GJR params +
    3 MIDAS = 7 free, like K1145)

Lookahead discipline: VIX²_{t-1}, EAV_{t-1} shifted; earnings filtered past only.
Random seed: 42.

Output: k1165_per_stock_table.csv + k1165_pooled_by_market.json.

Note: AU was attempted but dropped — yfinance earnings_dates returns <=3 past
events per ASX stock; insufficient to fit per-stock MLE (need >=15 events).
"""
from __future__ import annotations

import json
import os
import time
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
from scipy import optimize, stats

warnings.filterwarnings("ignore")

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# 3 NEW markets with enough yfinance earnings coverage (AU dropped — zero earnings in yfinance)
KR_TICKERS = ["005930.KS", "000660.KS", "207940.KS", "005380.KS", "035420.KS",
              "005490.KS", "035720.KS", "028260.KS", "105560.KS", "055550.KS"]
CA_TICKERS = ["RY.TO", "TD.TO", "ENB.TO", "BNS.TO", "BMO.TO",
              "CNQ.TO", "BCE.TO", "CP.TO", "MFC.TO", "CSU.TO"]
HK_TICKERS = ["0700.HK", "0388.HK", "0939.HK", "1299.HK", "0005.HK",
              "1398.HK", "0941.HK", "0883.HK", "0016.HK", "1109.HK"]

MARKET_TICKERS = {"KR": KR_TICKERS, "CA": CA_TICKERS, "HK": HK_TICKERS}


def _safe_name(ticker: str) -> str:
    return ticker.replace(".", "_").replace("-", "_").replace("^", "IDX_")


def load_price(ticker: str) -> pd.DataFrame | None:
    p = DATA / f"{_safe_name(ticker)}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def load_vix() -> pd.Series | None:
    p = DATA / "IDX_VIX.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"]


def build_eav(trading_days: pd.DatetimeIndex, ann_dates: pd.DatetimeIndex,
              window: int = 1) -> np.ndarray:
    eav = np.zeros(len(trading_days), dtype=float)
    if len(ann_dates) == 0:
        return eav
    pos_arr = trading_days.searchsorted(ann_dates.values)
    for p in pos_arr:
        p = int(p)
        for w in range(window):
            if 0 <= p + w < len(trading_days):
                eav[p + w] = 1.0
    return eav


def load_one_stock(market: str, ticker: str,
                   earnings_cache: dict) -> dict | None:
    raw = load_price(ticker)
    if raw is None:
        return None
    prices = raw["Close"].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix = load_vix()
    if vix is None:
        return None
    vix = vix.reindex(prices.index, method="ffill")
    df = pd.DataFrame({"r": log_ret, "vix": vix}).dropna()
    df = df[df["r"].abs() <= 0.30]
    dates_list = earnings_cache.get(ticker, [])
    ann_dates = pd.DatetimeIndex([pd.Timestamp(d) for d in dates_list]) \
        if dates_list else pd.DatetimeIndex([])
    eav_arr = build_eav(df.index, ann_dates, window=1)
    if len(df) < 500 or eav_arr.sum() < 15:
        return None
    return {
        "market": market, "ticker": ticker,
        "r": df["r"].values, "vix": df["vix"].values, "eav": eav_arr,
        "n_obs": len(df), "n_events": int(eav_arr.sum()),
        "sigma2_sample": float(np.var(df["r"].values, ddof=1)),
    }


# =========================================================================
# Per-stock numba likelihood — identical to K1166
# =========================================================================
@njit(cache=True, fastmath=True)
def _negll_stock(theta0, alpha, gamma_p, beta_p, theta_vix, theta_eav,
                 r, vix, eav):
    n = r.shape[0]
    persist = alpha + gamma_p / 2.0 + beta_p
    if alpha < 0.0 or gamma_p < 0.0 or beta_p < 0.0:
        return 1e12
    if persist >= 0.999:
        return 1e12
    omega_g = 1.0 - persist
    if omega_g <= 1e-6:
        return 1e12
    tau = np.empty(n)
    for t in range(n):
        if t == 0:
            vl = vix[0]; el = eav[0]
        else:
            vl = vix[t - 1]; el = eav[t - 1]
        raw = theta0 + theta_vix * vl * vl + theta_eav * el
        tau[t] = raw if raw > 1e-16 else 1e-16
    g = 1.0
    ll = 0.0
    log2pi = np.log(2.0 * np.pi)
    for t in range(1, n):
        tp = tau[t - 1]
        if tp < 1e-16:
            tp = 1e-16
        u = r[t - 1] / np.sqrt(tp)
        asym = gamma_p * u * u if u < 0.0 else 0.0
        g = omega_g + alpha * u * u + asym + beta_p * g
        if g < 1e-10:
            g = 1e-10
        sigma2 = tau[t] * g
        if sigma2 > 0.0:
            ll += -0.5 * (log2pi + np.log(sigma2) + r[t] * r[t] / sigma2)
    return -ll


def negll_wrap(params, r, vix, eav):
    t0, a, g, b, tv, te = params
    return _negll_stock(float(t0), float(a), float(g), float(b),
                        float(tv), float(te), r, vix, eav)


def fit_one_stock(stock: dict, verbose: bool = False) -> dict:
    r = stock["r"]; vix = stock["vix"]; eav = stock["eav"]
    var_r = float(np.var(r, ddof=1))
    vix2_mean = float(np.mean(vix * vix))
    starts = [
        [var_r * 0.5, 0.05, 0.05, 0.90, var_r / (2 * vix2_mean), var_r * 0.1],
        [var_r * 0.8, 0.03, 0.08, 0.88, var_r / (3 * vix2_mean), var_r * 0.2],
        [var_r * 0.3, 0.08, 0.10, 0.80, var_r / vix2_mean, 0.0],
        [var_r * 0.6, 0.06, 0.06, 0.85, var_r / (2 * vix2_mean), var_r * 0.5],
    ]
    bounds = [
        (1e-12, max(50.0 * var_r, 1e-4)),
        (1e-4, 0.5), (0.0, 0.5), (0.3, 0.999),
        (-2.0 * var_r / vix2_mean, 2.0 * var_r / vix2_mean),
        (-20.0 * var_r, 20.0 * var_r),
    ]
    best_ll = np.inf; best_p = None
    for s in starts:
        try:
            s = [max(lo, min(hi, v)) for v, (lo, hi) in zip(s, bounds)]
            res = optimize.minimize(
                negll_wrap, s, args=(r, vix, eav),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-10, "gtol": 1e-8})
            if np.isfinite(res.fun) and res.fun < best_ll:
                best_ll = res.fun; best_p = res.x.copy()
        except Exception:
            continue
    if best_p is None:
        return {"market": stock["market"], "ticker": stock["ticker"],
                "converged": False, "theta_eav": None, "theta_eav_t": None,
                "theta_eav_se": None, "n_obs": stock["n_obs"],
                "n_events": stock["n_events"],
                "sigma2_sample": stock["sigma2_sample"]}
    t0, a, g, b, tv, te = best_p
    loglik = -best_ll
    eps = max(abs(te) * 1e-3, max(var_r * 1e-5, 1e-9))
    try:
        pp = best_p.copy(); pp[5] = te + eps
        pm = best_p.copy(); pm[5] = te - eps
        llp = negll_wrap(pp, r, vix, eav); llm = negll_wrap(pm, r, vix, eav)
        h22 = (llp - 2 * best_ll + llm) / (eps ** 2)
        se = float(np.sqrt(1.0 / h22)) if h22 > 0 and np.isfinite(h22) else None
        tv_t = float(te / se) if se and se > 0 else None
    except Exception:
        se = None; tv_t = None
    at_bound = []
    for idx, (p, (lo, hi)) in enumerate(zip(best_p, bounds)):
        if (abs(p - lo) / max(abs(lo), 1e-10) < 0.01
                or abs(p - hi) / max(abs(hi), 1e-10) < 0.01):
            at_bound.append(idx)
    return {
        "market": stock["market"], "ticker": stock["ticker"],
        "converged": True,
        "theta0": float(t0), "alpha": float(a), "gamma": float(g),
        "beta": float(b), "theta_vix": float(tv), "theta_eav": float(te),
        "theta_eav_se": se, "theta_eav_t": tv_t,
        "loglik": float(loglik),
        "n_obs": stock["n_obs"], "n_events": stock["n_events"],
        "sigma2_sample": stock["sigma2_sample"],
        "persistence": float(a + g / 2.0 + b),
        "params_at_bound": at_bound,
    }


def _mp_worker(stock):
    t0 = time.time()
    r = fit_one_stock(stock, verbose=False)
    r["fit_time_sec"] = round(time.time() - t0, 2)
    return r


# =========================================================================
# Pooled-per-market MLE (shared θ0, θ_VIX, θ_EAV across stocks in market;
# separate stock-FE via stock-specific GJR params)
# =========================================================================
@njit(cache=True, fastmath=True)
def _pooled_negll(theta0, theta_vix, theta_eav,
                  alpha_arr, gamma_arr, beta_arr,
                  r_flat, vix_flat, eav_flat, offsets):
    """Pooled LL with shared MIDAS(θ0, θ_VIX, θ_EAV) and stock-specific GJR(α,γ,β).

    offsets: int array length S+1 marking start/end of each stock in flat arrays.
    """
    S = offsets.shape[0] - 1
    ll = 0.0
    log2pi = np.log(2.0 * np.pi)
    for s in range(S):
        a = alpha_arr[s]; gp = gamma_arr[s]; bp = beta_arr[s]
        if a < 0.0 or gp < 0.0 or bp < 0.0:
            return 1e13
        persist = a + gp / 2.0 + bp
        if persist >= 0.999:
            return 1e13
        omega_g = 1.0 - persist
        if omega_g <= 1e-6:
            return 1e13
        lo = offsets[s]; hi = offsets[s + 1]
        ns = hi - lo
        # tau
        tau_prev = theta0 + theta_vix * vix_flat[lo] * vix_flat[lo] + theta_eav * eav_flat[lo]
        if tau_prev < 1e-16:
            tau_prev = 1e-16
        g = 1.0
        for i in range(1, ns):
            t_idx = lo + i
            v_lag = vix_flat[t_idx - 1]
            e_lag = eav_flat[t_idx - 1]
            tau_t = theta0 + theta_vix * v_lag * v_lag + theta_eav * e_lag
            if tau_t < 1e-16:
                tau_t = 1e-16
            u = r_flat[t_idx - 1] / np.sqrt(tau_prev)
            asym = gp * u * u if u < 0.0 else 0.0
            g = omega_g + a * u * u + asym + bp * g
            if g < 1e-10:
                g = 1e-10
            sigma2 = tau_t * g
            if sigma2 > 0.0:
                ll += -0.5 * (log2pi + np.log(sigma2) + r_flat[t_idx] * r_flat[t_idx] / sigma2)
            tau_prev = tau_t
    return -ll


def _pooled_wrap(params, S, r_flat, vix_flat, eav_flat, offsets):
    theta0 = params[0]; theta_vix = params[1]; theta_eav = params[2]
    alpha_arr = params[3:3 + S]
    gamma_arr = params[3 + S:3 + 2 * S]
    beta_arr = params[3 + 2 * S:3 + 3 * S]
    return _pooled_negll(float(theta0), float(theta_vix), float(theta_eav),
                         np.asarray(alpha_arr, dtype=np.float64),
                         np.asarray(gamma_arr, dtype=np.float64),
                         np.asarray(beta_arr, dtype=np.float64),
                         r_flat, vix_flat, eav_flat, offsets)


def fit_pooled_market(stocks: list[dict]) -> dict:
    """Pooled per-market MLE (shared MIDAS + stock-specific GJR)."""
    S = len(stocks)
    r_flat = np.concatenate([s["r"] for s in stocks]).astype(np.float64)
    vix_flat = np.concatenate([s["vix"] for s in stocks]).astype(np.float64)
    eav_flat = np.concatenate([s["eav"] for s in stocks]).astype(np.float64)
    offsets = np.empty(S + 1, dtype=np.int64)
    offsets[0] = 0
    for i, s in enumerate(stocks):
        offsets[i + 1] = offsets[i] + len(s["r"])
    mean_var = float(np.mean([s["sigma2_sample"] for s in stocks]))
    vix2_mean = float(np.mean(vix_flat * vix_flat))

    # x0 and bounds
    alpha_init = np.full(S, 0.05); gamma_init = np.full(S, 0.05); beta_init = np.full(S, 0.90)
    x0 = np.concatenate([
        [mean_var * 0.5, mean_var / (2.0 * vix2_mean), mean_var * 0.1],
        alpha_init, gamma_init, beta_init,
    ])
    bounds = (
        [(1e-12, max(50.0 * mean_var, 1e-4)),
         (-2.0 * mean_var / vix2_mean, 2.0 * mean_var / vix2_mean),
         (-20.0 * mean_var, 20.0 * mean_var)]
        + [(1e-4, 0.5)] * S + [(0.0, 0.5)] * S + [(0.3, 0.999)] * S
    )
    res = optimize.minimize(
        _pooled_wrap, x0,
        args=(S, r_flat, vix_flat, eav_flat, offsets),
        method="L-BFGS-B", bounds=bounds,
        options={"maxiter": 2000, "ftol": 1e-10, "gtol": 1e-7})
    if not np.isfinite(res.fun):
        return {"converged": False}
    theta0, theta_vix, theta_eav = res.x[:3]

    # Hessian SE for theta_eav (central diff)
    eps = max(abs(theta_eav) * 1e-3, mean_var * 1e-5, 1e-9)
    try:
        xp = res.x.copy(); xp[2] = theta_eav + eps
        xm = res.x.copy(); xm[2] = theta_eav - eps
        llp = _pooled_wrap(xp, S, r_flat, vix_flat, eav_flat, offsets)
        llm = _pooled_wrap(xm, S, r_flat, vix_flat, eav_flat, offsets)
        h22 = (llp - 2 * res.fun + llm) / (eps ** 2)
        se = float(np.sqrt(1.0 / h22)) if h22 > 0 and np.isfinite(h22) else None
        t = float(theta_eav / se) if se and se > 0 else None
        p = float(2 * (1.0 - stats.norm.cdf(abs(t)))) if t else None
    except Exception:
        se = None; t = None; p = None
    return {
        "converged": True, "S": S,
        "theta0": float(theta0), "theta_vix": float(theta_vix),
        "theta_eav": float(theta_eav),
        "theta_eav_se_hessian": se, "theta_eav_t_hessian": t,
        "theta_eav_p_hessian": p,
        "loglik": float(-res.fun),
        "mean_sigma2": mean_var,
    }


# =========================================================================
# Main
# =========================================================================
def main():
    t0 = time.time()
    print(f"\n{'='*72}\nK1165: per-stock refit + pooled MLE for new markets (KR, CA, HK)\n{'='*72}\n")
    earnings_cache = json.load(open(DATA / "earnings_dates.json"))
    info_cache = json.load(open(DATA / "ticker_info.json"))

    # Load stocks
    all_stocks = []; per_market_stocks: dict[str, list[dict]] = {}
    for m, tickers in MARKET_TICKERS.items():
        loaded = 0; skipped = []
        for tk in tickers:
            st = load_one_stock(m, tk, earnings_cache)
            if st is None:
                skipped.append(tk); continue
            all_stocks.append(st)
            per_market_stocks.setdefault(m, []).append(st)
            loaded += 1
        print(f"[{m}] loaded {loaded}/{len(tickers)} (skipped: {skipped})")

    # --- Per-stock MLE ---
    n_workers = min(8, os.cpu_count() or 4)
    print(f"\n[per-stock] MP n_workers={n_workers}")
    t_fit = time.time()
    with Pool(n_workers) as pool:
        fit_results = pool.map(_mp_worker, all_stocks)
    print(f"  fits done in {time.time() - t_fit:.1f}s ({len(fit_results)} stocks)")
    df_fits = pd.DataFrame(fit_results)

    # --- Merge analyst/mcap/institutions_pct from fetch cache ---
    ih = json.load(open(DATA / "institutional_ownership_new.json"))
    ih_map = {}
    for rec in ih["records"]:
        mh = rec.get("major_holders") or {}
        ih_map[rec["ticker"]] = mh.get("institutionsPercentHeld")
    df_fits["analyst_count"] = df_fits["ticker"].map(
        lambda t: info_cache.get(t, {}).get("analyst_count"))
    df_fits["market_cap"] = df_fits["ticker"].map(
        lambda t: info_cache.get(t, {}).get("marketCap"))
    df_fits["institutions_pct"] = df_fits["ticker"].map(lambda t: ih_map.get(t))

    csv_path = ROOT / "k1165_per_stock_table_newmkts.csv"
    df_fits.to_csv(csv_path, index=False)
    print(f"  wrote {csv_path}")

    # --- Pooled per-market MLE ---
    print("\n[pooled] per-market pooled MLE (shared MIDAS + stock-FE GJR)")
    pooled_out = {}
    for m, ss in per_market_stocks.items():
        tp = time.time()
        r = fit_pooled_market(ss)
        print(f"  {m}: pooled fit ({time.time() - tp:.1f}s) θ_EAV={r.get('theta_eav'):.3e} "
              f"t={r.get('theta_eav_t_hessian'):.2f}" if r.get('converged') else f"  {m}: FAILED")
        pooled_out[m] = r

    # Write pooled JSON
    with open(ROOT / "k1165_pooled_by_market.json", "w") as f:
        json.dump(pooled_out, f, indent=2, default=str)
    print(f"  wrote k1165_pooled_by_market.json")

    print(f"\n[done] total {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
