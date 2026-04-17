#!/usr/bin/env python3
"""K1216c - Root-cause diagnostic: Does the K1213/K1216 multistart fragility
affect DEVELOPED markets too?

Context
-------
K1213 AU + K1216 BR/IN/MX + K1216b CH/ID -> 5/5 EM pooled MLE stuck in
secondary local minima (LR 146--598). Primary Spearman N=13 collapsed from
+0.441 to -0.071. The open question: is this an **EM-specific** pathology
(high vol / stock heterogeneity / outlier events) or a **universal MLE
design issue** that also traps DEV markets?

Protocol
--------
Re-run the K1216 100-multistart pipeline on 4 DEV markets (US / EU / JP /
TW) using the IDENTICAL joint pooled MLE from k1168 / k1172 (shared
theta0 / theta_VIX / theta_EAV + stock-specific GJR(alpha, gamma, beta);
single-shot L-BFGS-B; not the original K1145/K1147/K1150/K1153 BCD).

Specifically for each of US / EU / JP / TW:
  1. Load 10 DEV tickers per market (first 10 by market cap, matching
     K1147/K1150/K1153/K1145 ticker lists) + local VIX index cached in the
     source experiment directories + earnings cache.
  2. Run the k1168/k1172 joint _pooled_wrap with x0 = canonical k1168-style
     init once -> this is the K1216c canonical joint-MLE reference LL.
  3. Run 100 multistart L-BFGS-B with seeds 43..142 (identical to K1213 /
     K1216 / K1216b). K-means(K=2) basin identification.
  4. L-BFGS-B best -> Nelder-Mead + differential_evolution sensitivity.
  5. LR = 2*(LL_refined - LL_canonical_joint); theta_shift vs canonical.
  6. Combined 9-market (5 EM + 4 DEV) Spearman trajectory.

Verdict
-------
  - ROOT_CAUSE_METHODOLOGY: 4/4 DEV FRAGILE -> K1216 pathology is the
    joint pooled MLE itself. Paper 2 Section 5 methodology revision
    affects the entire panel; every market's canonical theta_rel is
    in doubt.
  - EM_SPECIFIC: 0/4 DEV FRAGILE -> EM markets have a separate feature
    (vol level / event density / stock heterogeneity) that creates the
    secondary basin. Paper 2 Section 5 revision stays confined to EM
    (+ AU K1213). DEV numbers stand.
  - PARTIAL: 1-3 DEV FRAGILE.

Seeds: base=42, multistart 43..142, DE seed GLOBAL_SEED+7, K-means seed 42
(IDENTICAL to K1213/K1216/K1216b for reproducibility across the 9-market
panel).

Worktree contract: all outputs in experiments/k1216c/.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
from scipy import optimize, stats as spstats

warnings.filterwarnings("ignore")

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent  # volpred-research/

K1145_DIR = PROJECT / "experiments" / "k1145"
K1147_DIR = PROJECT / "experiments" / "k1147"
K1150_DIR = PROJECT / "experiments" / "k1150"
K1153_DIR = PROJECT / "experiments" / "k1153"
K1166_DIR = PROJECT / "experiments" / "k1166"
K1172_DIR = PROJECT / "experiments" / "k1172"
K1171_DIR = PROJECT / "experiments" / "k1171"
K1216_DIR = PROJECT / "experiments" / "k1216"
K1216B_DIR = PROJECT / "experiments" / "k1216b"

# Import K1216's shared helpers (fit_pooled_lbfgs, make_bounds, sample_start,
# kmeans_basins, run_sensitivity, hessian_se_theta_eav, hac_se_theta_eav,
# plot_basin_hist) via file-path import so we obey "DO NOT rewrite".
import importlib.util
spec = importlib.util.spec_from_file_location(
    "k1216_mod", K1216_DIR / "k1216.py")
k1216_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(k1216_mod)  # type: ignore[union-attr]

# Pull helpers we need
build_pooled_arrays  = k1216_mod.build_pooled_arrays
make_bounds          = k1216_mod.make_bounds
sample_start         = k1216_mod.sample_start
fit_pooled_lbfgs     = k1216_mod.fit_pooled_lbfgs
hessian_se_theta_eav = k1216_mod.hessian_se_theta_eav
hac_se_theta_eav     = k1216_mod.hac_se_theta_eav
kmeans_basins        = k1216_mod.kmeans_basins
run_sensitivity      = k1216_mod.run_sensitivity
plot_basin_hist      = k1216_mod.plot_basin_hist


# =========================================================================
# Joint pooled MLE primitives (identical to k1168/k1172 _pooled_wrap,
# copied verbatim so K1216c is self-contained without re-importing market-
# specific k1168/k1172 modules that would pull in their EM data loaders).
# =========================================================================
@njit(cache=True, fastmath=True)
def _pooled_negll(theta0, theta_vix, theta_eav,
                  alpha_arr, gamma_arr, beta_arr,
                  r_flat, vix_flat, eav_flat, offsets):
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
        tau_prev = (theta0 + theta_vix * vix_flat[lo] * vix_flat[lo]
                    + theta_eav * eav_flat[lo])
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
                ll += -0.5 * (log2pi + np.log(sigma2)
                              + r_flat[t_idx] * r_flat[t_idx] / sigma2)
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


# =========================================================================
# DEV market loaders (K1147 / K1150 / K1153 / K1145 parquet + earnings)
# =========================================================================
DEV_SPEC = {
    "US": {"data_dir": K1147_DIR / "data",
           "tickers_first10": ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN',
                               'META', 'TSLA', 'BRK-B', 'UNH', 'V'],
           "earnings_cache": "earnings_dates.json",
           "vix_file": "IDX_VIX.parquet",
           "safe_rule": "us"},
    "EU": {"data_dir": K1153_DIR / "data",
           "tickers_first10": ['SAP.DE', 'SIE.DE', 'ALV.DE', 'MRK.DE',
                               'BMW.DE', 'BAS.DE', 'MBG.DE', 'DTE.DE',
                               'ADS.DE', 'VOW3.DE'],
           "earnings_cache": "earnings_dates.json",
           "vix_file": "IDX_VIX.parquet",
           "safe_rule": "eu"},
    "JP": {"data_dir": K1150_DIR / "data",
           "tickers_first10": ['7203.T', '6758.T', '9984.T', '8306.T',
                               '6861.T', '9432.T', '6098.T', '7974.T',
                               '6594.T', '8035.T'],
           "earnings_cache": "earnings_dates.json",
           "vix_file": "IDX_VIX.parquet",
           "safe_rule": "jp"},
    "TW": {"data_dir": K1145_DIR / "data",
           "tickers_first10": ['2330.TW', '2303.TW', '6239.TW', '2454.TW',
                               '2379.TW', '3034.TW', '3035.TW', '3443.TW',
                               '2388.TW', '2881.TW'],
           "earnings_cache": None,  # TW earnings loaded from 財報公告日.txt
           "vix_file": "IDX_VIX.parquet",
           "safe_rule": "tw"},
}

TW_EARNINGS_FILE = PROJECT / "財報公告日.txt"


def _safe_name(market: str, ticker: str) -> str:
    if market == "US":
        # K1147 convention: keep BRK-B -> BRK_B, strip ^ -> IDX_
        return ticker.replace("-", "_").replace("^", "IDX_")
    if market == "TW":
        # K1145 convention: keep '2330.TW' literal ('2330.TW.parquet')
        return ticker.replace("^", "IDX_")
    # JP / EU: '.' -> '_'
    return ticker.replace(".", "_").replace("-", "_").replace("^", "IDX_")


def load_price(market: str, ticker: str) -> pd.DataFrame | None:
    spec_m = DEV_SPEC[market]
    p = spec_m["data_dir"] / f"{_safe_name(market, ticker)}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def load_vix(market: str) -> pd.Series | None:
    spec_m = DEV_SPEC[market]
    p = spec_m["data_dir"] / spec_m["vix_file"]
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"]


def load_tw_earnings_for_code(code: str) -> pd.DatetimeIndex:
    """TW 財報公告日.txt -> DatetimeIndex for stock-code.
    code '2330.TW' -> look up '2330' in column 0 of big5 file.
    """
    if not TW_EARNINGS_FILE.exists():
        return pd.DatetimeIndex([])
    stock_code = code.split(".")[0]
    with open(TW_EARNINGS_FILE, "rb") as f:
        raw = f.read().decode("big5", errors="replace")
    lines = raw.strip().split("\n")
    recs = []
    for line in lines[1:]:
        parts = line.strip().split("\t")
        if len(parts) >= 4 and parts[0].strip() == stock_code:
            ds = parts[3].strip()
            if ds:
                try:
                    recs.append(pd.Timestamp(ds.replace("/", "-")))
                except Exception:
                    pass
    if not recs:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(recs).sort_values()


def load_earnings_from_json(market: str, ticker: str) -> pd.DatetimeIndex:
    spec_m = DEV_SPEC[market]
    if spec_m["earnings_cache"] is None:
        return pd.DatetimeIndex([])
    p = spec_m["data_dir"] / spec_m["earnings_cache"]
    if not p.exists():
        return pd.DatetimeIndex([])
    cache = json.load(open(p))
    if ticker not in cache:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex([pd.Timestamp(d) for d in cache[ticker]])


def build_eav(trading_days: pd.DatetimeIndex,
              ann_dates: pd.DatetimeIndex, window: int = 1) -> np.ndarray:
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


def load_one_stock(market: str, ticker: str) -> dict | None:
    raw = load_price(market, ticker)
    if raw is None:
        return None
    prices = raw["Close"].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix = load_vix(market)
    if vix is None:
        return None
    vix = vix.reindex(prices.index, method="ffill")
    df = pd.DataFrame({"r": log_ret, "vix": vix}).dropna()
    df = df[df["r"].abs() <= 0.30]
    if market == "TW":
        ann_dates = load_tw_earnings_for_code(ticker)
    else:
        ann_dates = load_earnings_from_json(market, ticker)
    eav_arr = build_eav(df.index, ann_dates, window=1)
    if len(df) < 500 or eav_arr.sum() < 15:
        return None
    return {
        "market": market, "ticker": ticker,
        "r": df["r"].values, "vix": df["vix"].values, "eav": eav_arr,
        "n_obs": len(df), "n_events": int(eav_arr.sum()),
        "sigma2_sample": float(np.var(df["r"].values, ddof=1)),
    }


def load_market_stocks(market: str) -> list[dict]:
    tickers = DEV_SPEC[market]["tickers_first10"]
    stocks: list[dict] = []
    for tk in tickers:
        st = load_one_stock(market, tk)
        if st is not None:
            stocks.append(st)
    return stocks


# =========================================================================
# Joint-MLE canonical reference (the fit under suspicion). We re-estimate
# with k1168/k1172 joint spec because the published K1145/K1147/K1150/K1153
# canonical used BCD; the K1216 LR test must compare like-with-like.
# =========================================================================
def fit_canonical_joint(stocks: list[dict]) -> dict:
    """One-shot joint L-BFGS-B with k1168/k1172 default init (the same init
    fit_pooled_market uses). Returns (theta_eav, theta_vix, theta0, loglik,
    mean_sigma2)."""
    S, r_flat, vix_flat, eav_flat, offsets, mean_var, vix2_mean = (
        build_pooled_arrays(stocks))
    alpha_init = np.full(S, 0.05)
    gamma_init = np.full(S, 0.05)
    beta_init = np.full(S, 0.90)
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
    if not np.isfinite(res.fun) or res.fun > 1e11:
        return {"converged": False, "fun": float(res.fun)}
    theta0, theta_vix, theta_eav = res.x[:3]
    return {
        "converged": True,
        "theta0": float(theta0), "theta_vix": float(theta_vix),
        "theta_eav": float(theta_eav),
        "loglik": float(-res.fun), "x_final": res.x,
        "mean_sigma2": mean_var,
    }


# =========================================================================
# Per-market runner (K1216-style multistart + sensitivity + basin + LR)
# =========================================================================
def run_one_market(market: str, n_starts: int = 100) -> dict:
    print(f"\n{'='*72}\n[K1216c {market}] loading stocks\n{'='*72}")
    stocks = load_market_stocks(market)
    print(f"[{market}] loaded {len(stocks)}/10 DEV tickers")
    if len(stocks) == 0:
        return {"market": market, "n_stocks": 0,
                "verdict": "INCONCLUSIVE_NO_DATA"}
    for s in stocks:
        print(f"   {s['ticker']}: n_obs={s['n_obs']}, "
              f"n_events={s['n_events']}, sigma2={s['sigma2_sample']:.3e}")

    S, _, _, _, _, mean_var, vix2_mean = build_pooled_arrays(stocks)
    print(f"[{market}] S={S} mean_sigma2={mean_var:.3e} "
          f"vix2_mean={vix2_mean:.3e}")

    # -----------------------------------------------------------------
    # K1216c canonical joint-MLE reference
    # -----------------------------------------------------------------
    print(f"[{market}] fitting K1216c canonical joint MLE (single init)...")
    canon_fit = fit_canonical_joint(stocks)
    if not canon_fit.get("converged"):
        print(f"[{market}] canonical joint MLE failed; returning INCONCLUSIVE")
        return {"market": market, "n_stocks": S,
                "verdict": "INCONCLUSIVE_CANONICAL_FAILED",
                "canonical_joint": canon_fit}
    canon_theta_rel = canon_fit["theta_eav"] / mean_var
    print(f"[{market}] canonical joint: theta_eav={canon_fit['theta_eav']:.3e} "
          f"theta_rel={canon_theta_rel:.3f} LL={canon_fit['loglik']:.2f}")

    # -----------------------------------------------------------------
    # 100 multistart
    # -----------------------------------------------------------------
    start_seeds = list(range(43, 43 + n_starts))
    all_fits: list[dict] = []
    t0 = time.time()
    # Patch k1216_mod.build_pooled_arrays etc. to use our stocks via closure
    # (they operate on the stocks list passed in; pooled_wrap is ours)
    for i, seed in enumerate(start_seeds):
        rng = np.random.default_rng(seed)
        x0 = sample_start(rng, S, mean_var, vix2_mean)
        fit = fit_pooled_lbfgs(stocks, x0, _pooled_wrap)
        fit["start_seed"] = seed
        fit["start_theta_eav"] = float(x0[2])
        fit["start_theta0"] = float(x0[0])
        all_fits.append(fit)
        if (i + 1) % 10 == 0:
            n_ok = sum(f.get("converged", False) for f in all_fits)
            print(f"  [start {i+1}/{n_starts}] converged={n_ok}/{i+1} "
                  f"elapsed={time.time() - t0:.1f}s")
    print(f"[{market}] multistart done in {time.time() - t0:.1f}s")

    conv = [f for f in all_fits if f.get("converged")]
    n_conv = len(conv)
    print(f"[{market}] converged = {n_conv}/{n_starts}")
    if n_conv < 5:
        return {
            "market": market, "n_stocks": S, "n_converged": n_conv,
            "verdict": "INCONCLUSIVE_TOO_FEW_CONVERGED",
            "canonical_joint": canon_fit,
            "canonical_theta_rel": canon_theta_rel,
            "mean_sigma2": mean_var,
            "all_fits": all_fits,
        }

    theta_eavs = np.array([f["theta_eav"] for f in conv], dtype=float)
    logliks = np.array([f["loglik"] for f in conv], dtype=float)
    labels, basin_stats = kmeans_basins(theta_eavs, logliks, seed=GLOBAL_SEED)
    print(f"[{market}] basin: A frac={basin_stats['basin_A_frac']:.2f} "
          f"theta_mean={basin_stats['basin_A_theta_mean']} "
          f"ll_max={basin_stats['basin_A_ll_max']} | "
          f"B frac={basin_stats['basin_B_frac']:.2f} "
          f"theta_mean={basin_stats['basin_B_theta_mean']} "
          f"ll_max={basin_stats['basin_B_ll_max']}")

    best_idx = int(np.argmax(logliks))
    best_fit = conv[best_idx]
    best_theta_eav = float(best_fit["theta_eav"])
    best_loglik = float(best_fit["loglik"])
    best_x = np.array(best_fit["x_final"], dtype=float)
    best_basin = int(labels[best_idx])
    best_theta_rel = best_theta_eav / mean_var
    print(f"[{market}] best LL theta_eav={best_theta_eav:.3e} "
          f"LL={best_loglik:.2f} basin={'A' if best_basin == 0 else 'B'} "
          f"theta_rel={best_theta_rel:.3f}")

    hess_se, hess_t = hessian_se_theta_eav(stocks, best_x, -best_loglik,
                                            _pooled_wrap)
    hac_se = hac_se_theta_eav(stocks, best_x, _pooled_wrap)
    hac_t = (best_theta_eav / hac_se) if hac_se and hac_se > 0 else None
    print(f"[{market}] SE: Hessian={hess_se} t={hess_t}; HAC={hac_se} t={hac_t}")

    # -----------------------------------------------------------------
    # NM + DE sensitivity
    # -----------------------------------------------------------------
    print(f"[{market}] running NM + DE sensitivity...")
    sens = run_sensitivity(stocks, best_x, _pooled_wrap)
    sens_nm    = sens.get("nelder_mead", {}).get("theta_eav")
    sens_nm_ll = sens.get("nelder_mead", {}).get("loglik")
    sens_de    = sens.get("differential_evolution", {}).get("theta_eav")
    sens_de_ll = sens.get("differential_evolution", {}).get("loglik")

    def _is_valid_ll(ll):
        return ll is not None and np.isfinite(ll) and ll > 1000.0

    deltas = []
    valid_sens_thetas = {"L-BFGS-B best": (best_theta_eav, best_loglik)}
    if sens_nm is not None and _is_valid_ll(sens_nm_ll) and best_theta_eav != 0:
        deltas.append(abs(sens_nm - best_theta_eav) / abs(best_theta_eav))
        valid_sens_thetas["Nelder-Mead"] = (sens_nm, sens_nm_ll)
    if sens_de is not None and _is_valid_ll(sens_de_ll) and best_theta_eav != 0:
        deltas.append(abs(sens_de - best_theta_eav) / abs(best_theta_eav))
        valid_sens_thetas["DiffEvolution"] = (sens_de, sens_de_ll)
    max_sens_delta = max(deltas) if deltas else 0.0
    print(f"[{market}] NM theta_eav={sens_nm} LL={sens_nm_ll}")
    print(f"[{market}] DE theta_eav={sens_de} LL={sens_de_ll}")
    print(f"[{market}] max sens delta = {max_sens_delta*100:.1f}%")

    best_optimizer = max(valid_sens_thetas.items(), key=lambda kv: kv[1][1])
    refined_theta_eav, refined_loglik = best_optimizer[1]
    refined_theta_rel = refined_theta_eav / mean_var
    if best_optimizer[0] != "L-BFGS-B best":
        print(f"[{market}] REFINED best LL from {best_optimizer[0]}: "
              f"theta_eav={refined_theta_eav:.3e} LL={refined_loglik:.2f} "
              f"theta_rel={refined_theta_rel:.3f}")

    # LR vs K1216c canonical joint
    lr_stat = 2.0 * (refined_loglik - canon_fit["loglik"])
    ll_gap = refined_loglik - canon_fit["loglik"]
    theta_shift_pct = (abs(refined_theta_eav - canon_fit["theta_eav"])
                       / max(abs(canon_fit["theta_eav"]), 1e-12))
    print(f"[{market}] LR = 2*(LL_refined - LL_canon_joint) = {lr_stat:+.2f}")

    if ll_gap > 1.92 and theta_shift_pct >= 0.2:
        verdict = "FRAGILE"
    elif ll_gap > 3.84:
        verdict = "BORDERLINE"
    elif ll_gap <= 1.92:
        verdict = "ROBUST"
    else:
        verdict = "BORDERLINE"
    print(f"[{market}] VERDICT: {verdict} "
          f"(LL gap={ll_gap:+.2f}, theta_shift={theta_shift_pct*100:.1f}%, "
          f"sens={max_sens_delta*100:.1f}%)")

    return {
        "market": market,
        "n_stocks": S,
        "n_starts": n_starts,
        "n_converged": n_conv,
        "canonical_joint": {
            "theta0": canon_fit["theta0"],
            "theta_vix": canon_fit["theta_vix"],
            "theta_eav": canon_fit["theta_eav"],
            "loglik": canon_fit["loglik"],
        },
        "canonical_theta_rel": canon_theta_rel,
        "mean_sigma2": mean_var,
        "tickers": [s["ticker"] for s in stocks],
        "n_obs_per_stock": [s["n_obs"] for s in stocks],
        "n_events_per_stock": [s["n_events"] for s in stocks],
        "best_fit": {
            "theta_eav": refined_theta_eav,
            "theta_rel": refined_theta_rel,
            "loglik": refined_loglik,
            "source": best_optimizer[0],
            "hessian_se": hess_se, "hessian_t": hess_t,
            "hac_se": hac_se, "hac_t": hac_t,
        },
        "lbfgs_best_fit": {
            "theta_eav": best_theta_eav,
            "theta_vix": float(best_x[1]),
            "theta0": float(best_x[0]),
            "loglik": best_loglik,
            "basin": "A" if best_basin == 0 else "B",
            "theta_rel": best_theta_rel,
            "start_seed": int(best_fit["start_seed"]),
        },
        "basin_stats": basin_stats,
        "theta_eavs": theta_eavs.tolist(),
        "logliks": logliks.tolist(),
        "labels": labels.tolist(),
        "sensitivity": sens,
        "max_sensitivity_delta_pct": max_sens_delta * 100,
        "lr_stat_refined_vs_canon_joint": lr_stat,
        "ll_gap_refined_minus_canon_joint": ll_gap,
        "theta_shift_pct_vs_canon_joint": theta_shift_pct * 100,
        "per_market_verdict": verdict,
        "all_fits": all_fits,
    }


# =========================================================================
# 9-market combined Spearman (5 EM + 4 DEV)
# =========================================================================
def build_9market_spearman(dev_refined_theta_rel: dict[str, float]) -> dict:
    """Combine K1216/K1216b/K1213 EM refined + K1216c DEV refined +
    K1172 canonical unrefined (for anything not refined). Uses K1172's
    institutions_pct_mean as predictor across all 12 K1172 markets, plus
    AU from K1171.
    """
    k1172_res = json.load(open(K1172_DIR / "k1172_results.json"))
    per_mkt = k1172_res["per_market_summary"]
    rows = {r["market"]: r for r in per_mkt}

    # EM refined from K1216 + K1216b
    k1216_res = json.load(open(K1216_DIR / "k1216_results.json"))
    em_refined: dict[str, float] = {}
    for m in ("BR", "IN", "MX"):
        pm = k1216_res["per_market"].get(m, {})
        bf = pm.get("best_fit", {})
        if "theta_rel" in bf:
            em_refined[m] = float(bf["theta_rel"])
    k1216b_res = json.load(open(K1216B_DIR / "k1216b_results.json"))
    for m in ("CH", "ID"):
        pm = k1216b_res["per_market"].get(m, {})
        bf = pm.get("best_fit", {})
        if "theta_rel" in bf:
            em_refined[m] = float(bf["theta_rel"])

    # AU from K1213 (basin-B best-LL = 1.476)
    K1213_AU_THETA_REL = 1.476
    au_inst = None
    k1171_res = json.load(open(K1171_DIR / "k1171_results.json"))
    for r in k1171_res["per_market_summary"]:
        if r["market"] == "AU":
            au_inst = float(r["institutions_pct_mean"])
            break

    # Start from K1172 sorted markets
    markets = sorted(rows.keys())
    xs = [float(rows[m]["institutions_pct_mean"]) for m in markets]
    ys = []
    applied = {}
    for m in markets:
        if m in dev_refined_theta_rel:
            ys.append(float(dev_refined_theta_rel[m]))
            applied[m] = ("DEV_K1216c_refined", dev_refined_theta_rel[m])
        elif m in em_refined:
            ys.append(float(em_refined[m]))
            applied[m] = ("EM_K1216_K1216b_refined", em_refined[m])
        else:
            v = float(rows[m]["theta_rel"])
            ys.append(v)
            applied[m] = ("K1172_canonical", v)

    if au_inst is not None:
        markets = markets + ["AU"]
        xs.append(au_inst)
        ys.append(K1213_AU_THETA_REL)
        applied["AU"] = ("K1213_refined", K1213_AU_THETA_REL)

    rho, p = spstats.spearmanr(xs, ys)
    return {
        "rho": float(rho), "p": float(p), "n": int(len(xs)),
        "markets_ordered": markets,
        "theta_rel_values": ys,
        "institutions_pct_mean_values": xs,
        "corrections_applied": applied,
    }


def build_9market_variants(dev_refined: dict[str, float]) -> dict:
    """Multiple Spearman scenarios for the full trajectory figure."""
    variants: dict = {}
    # K1172 baseline N=12
    k1172_res = json.load(open(K1172_DIR / "k1172_results.json"))
    per_mkt = k1172_res["per_market_summary"]
    rows = {r["market"]: r for r in per_mkt}
    mk_sorted = sorted(rows.keys())
    xs_b = [float(rows[m]["institutions_pct_mean"]) for m in mk_sorted]
    ys_b = [float(rows[m]["theta_rel"]) for m in mk_sorted]
    rho_b, p_b = spstats.spearmanr(xs_b, ys_b)
    variants["K1172_baseline_N12"] = {
        "rho": float(rho_b), "p": float(p_b), "n": int(len(xs_b))}

    # K1216b 5-EM + K1213 AU N=13 (the "EM-only refined" endpoint)
    k1216b_res = json.load(open(K1216B_DIR / "k1216b_results.json"))
    sp5 = k1216b_res["spearman_rebuilds"]["k1216b_5em_refined_au_n13_primary"]
    variants["K1216b_5EM_refined_plus_K1213_AU_N13"] = {
        "rho": float(sp5["rho"]), "p": float(sp5["p"]), "n": int(sp5["n"])}

    # K1216c DEV refined + K1216b EM refined + K1213 AU N=13
    v_all = build_9market_spearman(dev_refined)
    variants["K1216c_FULL_9market_refined_plus_AU_N13"] = {
        "rho": v_all["rho"], "p": v_all["p"], "n": v_all["n"],
        "markets_ordered": v_all["markets_ordered"],
        "theta_rel_values": v_all["theta_rel_values"],
        "corrections_applied": v_all["corrections_applied"],
    }

    return variants


# =========================================================================
# Trajectory figure
# =========================================================================
def plot_9market_trajectory(out_path: Path, points: list[dict]):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 1, figsize=(13, 6))
    labels = [p["label"] for p in points]
    rhos = [p["rho"] for p in points]
    ps = [p["p"] for p in points]
    ns = [p["n"] for p in points]
    xp = np.arange(len(labels))
    colors = []
    for lab in labels:
        if "K1172" in lab and "baseline" in lab:
            colors.append("#b22222")
        elif "K1216b" in lab and "DEV" not in lab:
            colors.append("#4a9b4a")
        elif "K1216c" in lab:
            colors.append("#1f77b4")
        else:
            colors.append("#8a8a8a")
    ax.bar(xp, rhos, color=colors, alpha=0.85, edgecolor="black")
    for i, (r, p, n) in enumerate(zip(rhos, ps, ns)):
        if np.isfinite(r):
            ax.text(i, r + 0.015 if r >= 0 else r - 0.04,
                    f"{r:+.3f}\np={p:.3f}\nN={n}",
                    ha="center", fontsize=9,
                    fontweight="bold" if "K1216c" in labels[i] else "normal")
    ax.set_xticks(xp)
    ax.set_xticklabels(labels, fontsize=9, rotation=15, ha="right")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel(r"Spearman $\rho$(inst_pct_mean, $\theta_{rel}$)")
    ax.set_title("Paper 2 Section 5 cross-market Spearman: 9-market audit "
                 "trajectory (K1172 baseline -> K1216b 5-EM refined -> "
                 "K1216c 4-DEV refined)")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# =========================================================================
# Main
# =========================================================================
def main():
    t_start = time.time()
    print(f"\n{'='*72}\nK1216c: Root-cause diagnostic -- DEV multistart audit\n"
          f"100 random starts per DEV market, seeds 43..142\n{'='*72}")

    results_per_market: dict = {}
    for market in ("US", "EU", "JP", "TW"):
        res = run_one_market(market, n_starts=100)
        results_per_market[market] = res
        if res.get("n_converged", 0) >= 5:
            theta_eavs = np.array(res["theta_eavs"])
            labels = np.array(res["labels"])
            plot_basin_hist(
                market, theta_eavs, labels,
                res["lbfgs_best_fit"]["theta_eav"],
                res["canonical_joint"]["theta_eav"],
                ROOT / f"k1216c_{market}_basin_hist.png",
            )

    # Cross-market verdict
    verdicts = {m: results_per_market[m].get("per_market_verdict",
                                              "INCONCLUSIVE")
                for m in ("US", "EU", "JP", "TW")}
    n_fragile = sum(1 for v in verdicts.values() if v == "FRAGILE")
    n_borderline = sum(1 for v in verdicts.values() if v == "BORDERLINE")
    n_robust = sum(1 for v in verdicts.values() if v == "ROBUST")

    if n_fragile == 4:
        cross_verdict = "ROOT_CAUSE_METHODOLOGY"
        narrative = (
            "All 4 DEV markets (US/EU/JP/TW) show the same K1216 "
            "pathology: joint pooled MLE canonical trapped in a secondary "
            "local minimum. Combined with K1213 AU + K1216 BR/IN/MX + "
            "K1216b CH/ID, the optimizer fragility is UNIVERSAL across "
            "the 9-market Paper 2 panel. Section 5 methodology requires "
            "panel-wide revision: every market's canonical theta_rel in "
            "K1165/K1168/K1172 must be replaced with the multistart-"
            "refined estimate. The K1172 N=12 primary Spearman is a "
            "single-init artefact."
        )
    elif n_fragile == 0:
        cross_verdict = "EM_SPECIFIC"
        narrative = (
            "0/4 DEV markets FRAGILE. The K1216 fragility is EM-specific. "
            "The most likely mechanism is that EM stocks' higher volatility "
            "and/or event density push the joint likelihood into a multi-"
            "basin regime that DEV markets escape. Paper 2 Section 5 "
            "revision stays confined to EM (5-EM + AU); DEV canonical "
            "theta_rel values (US=0.59/JP=0.39/EU=0.14/TW=0.17) stand."
        )
    else:
        cross_verdict = f"PARTIAL_{n_fragile}_of_4_DEV_FRAGILE"
        narrative = (
            f"Mixed DEV verdict: {n_fragile} FRAGILE / {n_borderline} "
            f"BORDERLINE / {n_robust} ROBUST across US/EU/JP/TW. The K1216 "
            "pathology is neither universal nor strictly EM-specific. "
            "Paper 2 Section 5 methodology revision must be applied market-"
            f"by-market. Fragile markets: "
            f"{[m for m, v in verdicts.items() if v == 'FRAGILE']}."
        )

    print(f"\n===== CROSS-MARKET 4-DEV VERDICT: {cross_verdict} =====")
    print(narrative)

    # -----------------------------------------------------------------
    # Combined 9-market Spearman
    # -----------------------------------------------------------------
    dev_refined = {m: results_per_market[m]["best_fit"]["theta_rel"]
                   for m in ("US", "EU", "JP", "TW")
                   if "best_fit" in results_per_market[m]}
    variants = build_9market_variants(dev_refined)
    print("\n[Spearman variants]")
    for k, v in variants.items():
        print(f"  {k}: rho={v['rho']:+.3f} p={v['p']:.4f} n={v['n']}")

    # Harvey t
    def harvey_t(rho: float, n: int) -> float | None:
        if not np.isfinite(rho) or n < 3:
            return None
        denom = max(1.0 - rho * rho, 1e-12)
        return float(rho * np.sqrt(n - 2) / np.sqrt(denom))
    harvey_ts = {k: harvey_t(v["rho"], v["n"]) for k, v in variants.items()}

    # -----------------------------------------------------------------
    # Trajectory figure (combined)
    # -----------------------------------------------------------------
    traj_points = [
        {"label": "K1172 baseline\nN=12 (canonical)",
         "rho": variants["K1172_baseline_N12"]["rho"],
         "p":   variants["K1172_baseline_N12"]["p"],
         "n":   variants["K1172_baseline_N12"]["n"]},
        {"label": "K1216b 5-EM refined\n+K1213 AU N=13",
         "rho": variants["K1216b_5EM_refined_plus_K1213_AU_N13"]["rho"],
         "p":   variants["K1216b_5EM_refined_plus_K1213_AU_N13"]["p"],
         "n":   variants["K1216b_5EM_refined_plus_K1213_AU_N13"]["n"]},
        {"label": "K1216c 9-market full refined\n(5-EM + 4-DEV + AU, N=13)",
         "rho": variants["K1216c_FULL_9market_refined_plus_AU_N13"]["rho"],
         "p":   variants["K1216c_FULL_9market_refined_plus_AU_N13"]["p"],
         "n":   variants["K1216c_FULL_9market_refined_plus_AU_N13"]["n"]},
    ]
    plot_9market_trajectory(ROOT / "k1216c_9market_trajectory.png",
                            traj_points)
    print("[figures] wrote 4 basin hists + 9-market trajectory")

    # -----------------------------------------------------------------
    # CSVs
    # -----------------------------------------------------------------
    all_rows = []
    for m in ("US", "EU", "JP", "TW"):
        for f in results_per_market[m].get("all_fits", []):
            r = dict(f)
            r["market"] = m
            if "x_final" in r:
                r.pop("x_final")
            all_rows.append(r)
    pd.DataFrame(all_rows).to_csv(
        ROOT / "k1216c_multistart_results.csv", index=False)
    print(f"[csv] wrote k1216c_multistart_results.csv ({len(all_rows)} rows)")

    summary_rows = []
    for m in ("US", "EU", "JP", "TW"):
        r = results_per_market[m]
        if "best_fit" not in r:
            continue
        summary_rows.append({
            "market": m,
            "n_stocks": r["n_stocks"],
            "n_converged": r["n_converged"],
            "canonical_joint_theta_eav": r["canonical_joint"]["theta_eav"],
            "canonical_joint_theta_rel": r["canonical_theta_rel"],
            "canonical_joint_loglik": r["canonical_joint"]["loglik"],
            "k1216c_refined_theta_eav": r["best_fit"]["theta_eav"],
            "k1216c_refined_theta_rel": r["best_fit"]["theta_rel"],
            "k1216c_refined_loglik":    r["best_fit"]["loglik"],
            "k1216c_refined_source":    r["best_fit"]["source"],
            "k1216c_lbfgs_theta_rel":   r["lbfgs_best_fit"]["theta_rel"],
            "k1216c_lbfgs_basin":       r["lbfgs_best_fit"]["basin"],
            "k1216c_hessian_se":        r["best_fit"]["hessian_se"],
            "k1216c_hessian_t":         r["best_fit"]["hessian_t"],
            "k1216c_hac_se":            r["best_fit"]["hac_se"],
            "k1216c_hac_t":             r["best_fit"]["hac_t"],
            "ll_gap_refined_vs_canon_joint":
                r["ll_gap_refined_minus_canon_joint"],
            "lr_stat_refined": r["lr_stat_refined_vs_canon_joint"],
            "theta_shift_pct": r["theta_shift_pct_vs_canon_joint"],
            "max_sens_delta_pct": r["max_sensitivity_delta_pct"],
            "basin_A_frac": r["basin_stats"]["basin_A_frac"],
            "basin_B_frac": r["basin_stats"]["basin_B_frac"],
            "per_market_verdict": r["per_market_verdict"],
        })
    pd.DataFrame(summary_rows).to_csv(
        ROOT / "k1216c_per_market_summary.csv", index=False)
    print("[csv] wrote k1216c_per_market_summary.csv")

    # -----------------------------------------------------------------
    # JSON results
    # -----------------------------------------------------------------
    def _strip(d):
        if isinstance(d, dict):
            return {k: _strip(v) for k, v in d.items() if k != "all_fits"}
        if isinstance(d, list):
            return [_strip(x) for x in d]
        return d

    out = {
        "experiment_id": "K1216c",
        "title": ("DEV markets multistart fragility audit: US/EU/JP/TW "
                  "joint pooled MLE 100-start search for secondary local "
                  "minima; root-cause diagnostic for K1213/K1216/K1216b "
                  "WIDESPREAD_FRAGILITY"),
        "proposer": "User brief (K1216 WIDESPREAD_FRAGILITY follow-up)",
        "executor": "Claude (worktree agent agent-a7d6ed91)",
        "global_seed": GLOBAL_SEED,
        "n_starts_per_market": 100,
        "start_seeds": list(range(43, 143)),
        "markets_tested": ["US", "EU", "JP", "TW"],
        "runtime_sec": round(time.time() - t_start, 1),
        "per_market": {m: _strip(results_per_market[m])
                       for m in ("US", "EU", "JP", "TW")},
        "dev_verdicts_4markets": verdicts,
        "n_fragile_dev": n_fragile,
        "n_borderline_dev": n_borderline,
        "n_robust_dev": n_robust,
        "cross_market_verdict_4dev": cross_verdict,
        "cross_market_narrative_4dev": narrative,
        "spearman_variants": variants,
        "harvey_t_per_variant": harvey_ts,
        "paper2_s5_9market_table": [
            {"label": "K1172 baseline N=12 (canonical all markets)",
             "n": variants["K1172_baseline_N12"]["n"],
             "rho": variants["K1172_baseline_N12"]["rho"],
             "p":   variants["K1172_baseline_N12"]["p"]},
            {"label": "K1216b 5-EM refined + K1213 AU N=13",
             "n": variants["K1216b_5EM_refined_plus_K1213_AU_N13"]["n"],
             "rho": variants["K1216b_5EM_refined_plus_K1213_AU_N13"]["rho"],
             "p":   variants["K1216b_5EM_refined_plus_K1213_AU_N13"]["p"]},
            {"label": "K1216c full 9-market refined + AU N=13 (FINAL)",
             "n": variants["K1216c_FULL_9market_refined_plus_AU_N13"]["n"],
             "rho": variants["K1216c_FULL_9market_refined_plus_AU_N13"]["rho"],
             "p":   variants["K1216c_FULL_9market_refined_plus_AU_N13"]["p"]},
        ],
        "data_sources": [
            "experiments/k1147/data/ (US parquet + VIX + earnings)",
            "experiments/k1150/data/ (JP parquet + VIX + earnings)",
            "experiments/k1153/data/ (EU parquet + VIX + earnings)",
            "experiments/k1145/data/ (TW parquet + VIX); "
            "財報公告日.txt (TW earnings)",
            "experiments/k1172/k1172_results.json (K1172 baseline Spearman)",
            "experiments/k1216/k1216_results.json (EM BR/IN/MX refined)",
            "experiments/k1216b/k1216b_results.json (EM CH/ID refined)",
            "experiments/k1171/k1171_results.json (AU inst_pct_mean)",
            "experiments/k1216/k1216.py (shared optimization helpers)",
        ],
        "rigor_notes": {
            "seed_discipline": "base=42; 100 starts = 43..142 identical "
                               "to K1213/K1216/K1216b for reproducibility "
                               "across the 9-market panel",
            "mle_spec": "k1168/k1172 joint pooled MLE (shared theta0, "
                         "theta_VIX, theta_EAV + stock-specific GJR(alpha, "
                         "gamma, beta), single-shot L-BFGS-B) -- NOT the "
                         "BCD spec used by the original K1145/K1147/K1150/"
                         "K1153 canonicals, because K1216 LR tests require "
                         "like-with-like comparison",
            "canonical_reference": "K1216c canonical joint-MLE (single init, "
                                    "same default init as k1168/k1172 "
                                    "fit_pooled_market), re-estimated here; "
                                    "this is the 'fit under suspicion' that "
                                    "the multistart may overturn",
            "bounds": "identical to K1168/K1172 (via make_bounds helper "
                      "imported from k1216.py)",
            "lookahead_guard": "_pooled_negll shifts VIX^2_{t-1} and "
                                "EAV_{t-1}; identical to k1168/k1172",
            "optimizer_comparison": "L-BFGS-B primary; Nelder-Mead + "
                                    "differential_evolution sensitivity; "
                                    "refined best = max LL over all valid",
            "se_type": "Hessian + HAC-robust (stock-level score)",
            "kmeans_seed": 42,
            "do_not_rewrite": "K1216 helpers (fit_pooled_lbfgs, "
                               "sample_start, kmeans_basins, "
                               "hessian/hac_se_theta_eav, run_sensitivity, "
                               "plot_basin_hist) imported from "
                               "experiments/k1216/k1216.py verbatim",
        },
    }
    with open(ROOT / "k1216c_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("[json] wrote k1216c_results.json")
    print(f"[done] total {time.time() - t_start:.1f}s")
    return out


if __name__ == "__main__":
    main()
