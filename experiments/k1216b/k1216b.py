#!/usr/bin/env python3
"""K1216b - Close the 5-EM multistart audit: CH (Shanghai SSE) + ID (IDX).

Context
-------
K1213 showed K1171 AU pooled theta_EAV was stuck in a secondary local
minimum under shared-MIDAS + stock-FE-GJR pooled MLE (basin-B best-LL LR
statistic >>> chi^2(1)). K1216 applied the same 100-multi-start pattern
to BR / IN / MX with verdict WIDESPREAD_FRAGILITY (LR = +146 / +411 / +347).

CH (K1168, N=10 stocks) and ID (K1172, N=10 stocks) are the remaining two
EM pooled fits in the K1168/K1172 set. K1216b completes the 5-EM audit:

  - If CH + ID ALSO fragile -> ALL_5_EM_FRAGILE; Paper 2 Section 5 EM
    optimizer-fragility pattern is universal; primary Spearman on N=13
    further decays after substituting both refined EM thetas.
  - If CH + ID ROBUST -> CH_ID_EXCEPTIONS; two EM markets resist the
    pathology, raising the question what CH/ID micro-structure protects
    them (both have LOW canonical theta_rel <0.31 vs the >1.0 off-ladder
    BR/IN/MX/AU cases, which is consistent with "only off-ladder EM pools
    are trapped" -- a potentially exculpatory reading for ladder results).
  - Mixed / BORDERLINE -> PARTIAL.

This script mirrors K1216 EXACTLY (no rewrite): same pooled_wrap import,
same bounds, same seed discipline, same basin analysis, same LR test,
same sensitivity pipeline.

Module mapping
--------------
  CH -> experiments/k1168/k1168_per_stock_refit.py (same module as BR/IN)
  ID -> experiments/k1172/k1172_per_stock_refit.py (same module as MX/ZA)

Random seed discipline: base 42, start seeds 43..142 (identical to
K1213/K1216; reproducible across markets). DE seed GLOBAL_SEED+7.
K-means seed 42.

Lookahead guard inherited from k1168/k1172 _pooled_negll (VIX^2_{t-1}
and EAV_{t-1} shifted).

Worktree contract: all outputs in experiments/k1216b/.
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

warnings.filterwarnings("ignore")

# =========================================================================
# Import K1168 / K1172 pooled MLE primitives AS-IS (no rewrite)
# =========================================================================
K1168_MAIN = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k1168")
K1172_MAIN = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k1172")
K1216_MAIN = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k1216")
K1171_MAIN = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k1171")
sys.path.insert(0, str(K1168_MAIN))
sys.path.insert(0, str(K1172_MAIN))
sys.path.insert(0, str(K1216_MAIN))
import k1168_per_stock_refit as k1168mod  # type: ignore
import k1172_per_stock_refit as k1172mod  # type: ignore

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)

ROOT = Path(__file__).resolve().parent

# -------------------------------------------------------------------------
# Market definitions: CH (k1168 module) + ID (k1172 module)
# -------------------------------------------------------------------------
MARKET_SPEC = {
    "CH": {"module": k1168mod, "data_dir": K1168_MAIN / "data",
           "tickers": k1168mod.CH_TICKERS,
           "earnings_cache": "earnings_dates_k1168.json"},
    "ID": {"module": k1172mod, "data_dir": K1172_MAIN / "data",
           "tickers": k1172mod.ID_TICKERS,
           "earnings_cache": "earnings_dates_k1172.json"},
}

# -------------------------------------------------------------------------
# Canonical K1168 (CH) / K1172 (ID) pooled references (the "fits under
# suspicion"). Source: k1168_pooled_by_market.json / k1172_pooled_by_market.json
# -------------------------------------------------------------------------
CANONICAL = {
    "CH": {"theta_eav": 0.00010701084944019206,
           "theta_vix": 9.128726678883752e-08,
           "theta0":    0.00035470115023506654,
           "theta_eav_se_hessian": 2.0284769501421138e-05,
           "theta_eav_t_hessian":  5.275428416018972,
           "loglik":    77922.50200605765,
           "mean_sigma2": 0.0003523132441568119,
           "source": "K1168 k1168_pooled_by_market.json CH"},
    "ID": {"theta_eav": 9.669065670307561e-05,
           "theta_vix": 2.444663541863884e-07,
           "theta0":    0.0003427338258295779,
           "theta_eav_se_hessian": 1.9723021174757918e-05,
           "theta_eav_t_hessian":  4.902426248308401,
           "loglik":    76494.22826334642,
           "mean_sigma2": 0.00040685674595126173,
           "source": "K1172 k1172_pooled_by_market.json ID"},
}

# K1172 cross-market baseline (N=12 Spearman, no corrections)
K1172_BASELINE_RHO = 0.44055944055944063
K1172_BASELINE_P   = 0.1517350357167303

# K1213 AU refined
K1213_AU_THETA_REL = 1.476       # basin-B best-LL (K1213 e4d376ad)

# K1216 EM refined theta_rel (read from K1216 results on disk -- authoritative)
def _load_k1216_refined() -> dict[str, float]:
    p = K1216_MAIN / "k1216_results.json"
    if not p.exists():
        raise FileNotFoundError(
            f"K1216 results JSON not found at {p}; K1216b depends on it "
            "for the 5-EM trajectory rebuild.")
    d = json.load(open(p))
    refined = {}
    for m in ("BR", "IN", "MX"):
        pm = d["per_market"].get(m, {})
        bf = pm.get("best_fit", {})
        if "theta_rel" in bf:
            refined[m] = float(bf["theta_rel"])
    return refined

K1216_EM_REFINED_THETA_REL = _load_k1216_refined()


# =========================================================================
# Copy K1216 optimization primitives (load_market_stocks, build_pooled_arrays,
# make_bounds, sample_start, fit_pooled_lbfgs, hessian_se, hac_se,
# kmeans_basins, run_sensitivity) -- re-imported by file path to avoid
# duplication while respecting the "DO NOT rewrite" brief.
# =========================================================================
import importlib.util

K1216_MODULE_PATH = K1216_MAIN / "k1216.py"
spec = importlib.util.spec_from_file_location("k1216_mod", K1216_MODULE_PATH)
k1216_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
# IMPORTANT: monkey-patch MARKET_SPEC / CANONICAL AFTER the module runs so
# K1216 helper functions use our market map (they read MARKET_SPEC globally).
spec.loader.exec_module(k1216_mod)  # type: ignore[union-attr]
# Replace K1216 module globals with K1216b's CH/ID mapping so its helpers
# (load_market_stocks, fit_pooled_lbfgs, etc.) route to the right module
# automatically. K1216's helpers are pure given MARKET_SPEC.
k1216_mod.MARKET_SPEC = MARKET_SPEC
k1216_mod.CANONICAL = CANONICAL
k1216_mod.ROOT = ROOT

# Re-export helpers we need
load_market_stocks   = k1216_mod.load_market_stocks
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
# Per-market runner (copied structurally from k1216.run_one_market but we
# cannot call it directly because it references global CANONICAL/MARKET_SPEC
# bindings that we already swapped. Those helpers are fine; the runner must
# be re-declared here so verdicts log under K1216b).
# =========================================================================
def run_one_market(market: str, n_starts: int = 100) -> dict:
    spec_m = MARKET_SPEC[market]
    mod = spec_m["module"]
    pooled_wrap = mod._pooled_wrap  # type: ignore[attr-defined]
    print(f"\n{'='*72}\n[K1216b {market}] loading stocks\n{'='*72}")
    stocks = load_market_stocks(market)
    print(f"[{market}] loaded {len(stocks)}/10 stocks")
    if len(stocks) < 10:
        print(f"[{market}] WARNING: only {len(stocks)}/10 loaded; canonical "
              "used 10. Running with what we have.")
    for s in stocks:
        print(f"   {s['ticker']}: n_obs={s['n_obs']}, "
              f"n_events={s['n_events']}, sigma2={s['sigma2_sample']:.3e}")

    S, _, _, _, _, mean_var, vix2_mean = build_pooled_arrays(stocks)
    print(f"[{market}] S={S} mean_sigma2={mean_var:.3e} "
          f"vix2_mean={vix2_mean:.3e}")

    canon = CANONICAL[market]
    canon_theta_rel = canon["theta_eav"] / mean_var
    print(f"[{market}] canonical theta_eav={canon['theta_eav']:.3e} "
          f"theta_rel={canon_theta_rel:.3f} LL={canon['loglik']:.2f}")

    start_seeds = list(range(43, 43 + n_starts))
    all_fits: list[dict] = []
    t0 = time.time()
    for i, seed in enumerate(start_seeds):
        rng = np.random.default_rng(seed)
        x0 = sample_start(rng, S, mean_var, vix2_mean)
        fit = fit_pooled_lbfgs(stocks, x0, pooled_wrap)
        fit["start_seed"] = seed
        fit["start_theta_eav"] = float(x0[2])
        fit["start_theta0"] = float(x0[0])
        all_fits.append(fit)
        if (i + 1) % 10 == 0:
            n_ok = sum(f.get("converged", False) for f in all_fits)
            print(f"  [start {i+1}/{n_starts}] converged={n_ok}/{i+1} "
                  f"elapsed={time.time() - t0:.1f}s")
    print(f"[{market}] fits done in {time.time() - t0:.1f}s")

    conv = [f for f in all_fits if f.get("converged")]
    n_conv = len(conv)
    print(f"[{market}] converged = {n_conv}/{n_starts}")
    if n_conv < 5:
        print(f"[{market}] FATAL: only {n_conv} converged; cannot assess "
              "basin structure. Returning INCONCLUSIVE.")
        return {
            "market": market, "n_stocks": S, "n_converged": n_conv,
            "verdict": "INCONCLUSIVE_TOO_FEW_CONVERGED",
            "canonical": canon, "canonical_theta_rel": canon_theta_rel,
            "mean_sigma2": mean_var,
            "all_fits": all_fits,
        }

    theta_eavs = np.array([f["theta_eav"] for f in conv], dtype=float)
    logliks = np.array([f["loglik"] for f in conv], dtype=float)
    labels, basin_stats = kmeans_basins(theta_eavs, logliks, seed=GLOBAL_SEED)
    print(f"[{market}] basin stats: A frac={basin_stats['basin_A_frac']:.2f} "
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
          f"LL={best_loglik:.2f} "
          f"basin={'A' if best_basin == 0 else 'B'} "
          f"theta_rel={best_theta_rel:.3f}")

    hess_se, hess_t = hessian_se_theta_eav(stocks, best_x, -best_loglik,
                                            pooled_wrap)
    hac_se = hac_se_theta_eav(stocks, best_x, pooled_wrap)
    hac_t = (best_theta_eav / hac_se) if hac_se and hac_se > 0 else None
    print(f"[{market}] SE: Hessian={hess_se} t={hess_t}; HAC={hac_se} t={hac_t}")

    print(f"[{market}] running NM + DE sensitivity...")
    sens = run_sensitivity(stocks, best_x, pooled_wrap)
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
    else:
        if sens_de is not None and not _is_valid_ll(sens_de_ll):
            print(f"[{market}] NOTE: DE landed in penalty trap "
                  f"(LL={sens_de_ll}), excluded from sens delta")
    max_sens_delta = max(deltas) if deltas else 0.0
    print(f"[{market}] NM theta_eav={sens_nm} LL={sens_nm_ll}")
    print(f"[{market}] DE theta_eav={sens_de} LL={sens_de_ll}")
    print(f"[{market}] max sensitivity delta (valid LL only) "
          f"= {max_sens_delta*100:.1f}%")

    best_optimizer = max(valid_sens_thetas.items(), key=lambda kv: kv[1][1])
    refined_theta_eav, refined_loglik = best_optimizer[1]
    refined_theta_rel = refined_theta_eav / mean_var
    if best_optimizer[0] != "L-BFGS-B best":
        print(f"[{market}] REFINED best LL from {best_optimizer[0]}: "
              f"theta_eav={refined_theta_eav:.3e} LL={refined_loglik:.2f} "
              f"theta_rel={refined_theta_rel:.3f}")
    else:
        print(f"[{market}] refined best == L-BFGS-B best (NM/DE did not improve)")

    lr_stat = 2.0 * (refined_loglik - canon["loglik"])
    ll_gap_refined_minus_canon = refined_loglik - canon["loglik"]
    lr_stat_lbfgs = 2.0 * (best_loglik - canon["loglik"])
    ll_gap_K1216b_minus_canon = best_loglik - canon["loglik"]
    print(f"[{market}] LR = 2*(LL_refined - LL_canonical) = "
          f"{lr_stat:+.2f}")

    theta_shift_pct = (abs(refined_theta_eav - canon["theta_eav"])
                       / max(abs(canon["theta_eav"]), 1e-12))
    if ll_gap_refined_minus_canon > 1.92 and theta_shift_pct >= 0.2:
        per_mkt_verdict = "FRAGILE"
    elif ll_gap_refined_minus_canon > 3.84:
        per_mkt_verdict = "BORDERLINE"
    elif ll_gap_refined_minus_canon <= 1.92:
        per_mkt_verdict = "ROBUST"
    else:
        per_mkt_verdict = "BORDERLINE"
    print(f"[{market}] VERDICT: {per_mkt_verdict} "
          f"(LL gap refined-canon={ll_gap_refined_minus_canon:+.2f}, "
          f"theta_shift={theta_shift_pct*100:.1f}%, "
          f"sens={max_sens_delta*100:.1f}%)")

    return {
        "market": market,
        "n_stocks": S,
        "n_starts": n_starts,
        "n_converged": n_conv,
        "canonical": canon,
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
        "lr_stat_refined_vs_canonical": lr_stat,
        "lr_stat_lbfgs_vs_canonical": lr_stat_lbfgs,
        "ll_gap_refined_minus_canonical": ll_gap_refined_minus_canon,
        "ll_gap_lbfgs_minus_canonical": ll_gap_K1216b_minus_canon,
        "theta_shift_pct_vs_canonical": theta_shift_pct * 100,
        "per_market_verdict": per_mkt_verdict,
        "all_fits": all_fits,
    }


# =========================================================================
# 5-EM refined Spearman trajectory rebuild
# =========================================================================
def rebuild_5em_spearman(ch_theta_rel_refined: float,
                         id_theta_rel_refined: float,
                         include_au_k1213: bool = False) -> dict:
    """Combine K1216 BR/IN/MX refined + K1216b CH/ID refined (+K1213 AU
    optional) into a cross-market Spearman. Developed markets keep K1172
    canonical theta_rel (CA/EU/HK/JP/KR/TW/US/CH? Note: CH is EM, not dev).
    """
    from scipy import stats as spstats
    k1172_res = json.load(open(K1172_MAIN / "k1172_results.json"))
    per_mkt = k1172_res["per_market_summary"]
    rows = {r["market"]: r for r in per_mkt}
    markets = sorted(rows.keys())

    # EM corrections: BR/IN/MX from K1216, CH/ID from K1216b
    corrections = dict(K1216_EM_REFINED_THETA_REL)
    corrections["CH"] = ch_theta_rel_refined
    corrections["ID"] = id_theta_rel_refined

    xs = [float(rows[m]["institutions_pct_mean"]) for m in markets]
    ys = []
    for m in markets:
        if m in corrections:
            ys.append(float(corrections[m]))
        else:
            ys.append(float(rows[m]["theta_rel"]))

    if include_au_k1213:
        k1171_res = json.load(open(K1171_MAIN / "k1171_results.json"))
        au_inst = None
        for r in k1171_res["per_market_summary"]:
            if r["market"] == "AU":
                au_inst = float(r["institutions_pct_mean"])
                break
        if au_inst is not None:
            markets = markets + ["AU"]
            xs.append(au_inst)
            ys.append(K1213_AU_THETA_REL)

    m_ok = [i for i in range(len(xs)) if np.isfinite(xs[i]) and np.isfinite(ys[i])]
    xs_ok = [xs[i] for i in m_ok]
    ys_ok = [ys[i] for i in m_ok]
    rho, p = spstats.spearmanr(xs_ok, ys_ok)
    return {
        "rho": float(rho), "p": float(p), "n": int(len(xs_ok)),
        "markets_ordered": [markets[i] for i in m_ok],
        "theta_rel_values": ys_ok,
        "institutions_pct_mean_values": xs_ok,
        "corrections_applied": corrections,
        "includes_au_k1213": include_au_k1213,
    }


def rebuild_baseline_spearman(include_au: bool = False) -> dict:
    """K1172 baseline (no corrections)."""
    from scipy import stats as spstats
    k1172_res = json.load(open(K1172_MAIN / "k1172_results.json"))
    per_mkt = k1172_res["per_market_summary"]
    markets = sorted([r["market"] for r in per_mkt])
    rows = {r["market"]: r for r in per_mkt}
    xs = [float(rows[m]["institutions_pct_mean"]) for m in markets]
    ys = [float(rows[m]["theta_rel"]) for m in markets]
    if include_au:
        k1171_res = json.load(open(K1171_MAIN / "k1171_results.json"))
        au_inst = None
        for r in k1171_res["per_market_summary"]:
            if r["market"] == "AU":
                au_inst = float(r["institutions_pct_mean"])
                break
        if au_inst is not None:
            markets = markets + ["AU"]
            xs.append(au_inst)
            ys.append(K1213_AU_THETA_REL)
    rho, p = spstats.spearmanr(xs, ys)
    return {"rho": float(rho), "p": float(p), "n": int(len(xs)),
            "markets_ordered": markets,
            "theta_rel_values": ys,
            "institutions_pct_mean_values": xs}


def rebuild_au_only_spearman() -> dict:
    """K1213-only correction (AU); EM canonical."""
    from scipy import stats as spstats
    k1172_res = json.load(open(K1172_MAIN / "k1172_results.json"))
    per_mkt = k1172_res["per_market_summary"]
    markets = sorted([r["market"] for r in per_mkt])
    rows = {r["market"]: r for r in per_mkt}
    xs = [float(rows[m]["institutions_pct_mean"]) for m in markets]
    ys = [float(rows[m]["theta_rel"]) for m in markets]
    # add AU
    k1171_res = json.load(open(K1171_MAIN / "k1171_results.json"))
    au_inst = None
    for r in k1171_res["per_market_summary"]:
        if r["market"] == "AU":
            au_inst = float(r["institutions_pct_mean"])
            break
    if au_inst is not None:
        markets = markets + ["AU"]
        xs.append(au_inst)
        ys.append(K1213_AU_THETA_REL)
    rho, p = spstats.spearmanr(xs, ys)
    return {"rho": float(rho), "p": float(p), "n": int(len(xs)),
            "markets_ordered": markets}


def rebuild_k1216_em_only_spearman(include_au: bool = False) -> dict:
    """K1216 EM (BR/IN/MX) refined only; CH/ID canonical; AU optional."""
    from scipy import stats as spstats
    k1172_res = json.load(open(K1172_MAIN / "k1172_results.json"))
    per_mkt = k1172_res["per_market_summary"]
    markets = sorted([r["market"] for r in per_mkt])
    rows = {r["market"]: r for r in per_mkt}
    xs = [float(rows[m]["institutions_pct_mean"]) for m in markets]
    ys = []
    corrections = dict(K1216_EM_REFINED_THETA_REL)  # BR/IN/MX only
    for m in markets:
        if m in corrections:
            ys.append(float(corrections[m]))
        else:
            ys.append(float(rows[m]["theta_rel"]))
    if include_au:
        k1171_res = json.load(open(K1171_MAIN / "k1171_results.json"))
        au_inst = None
        for r in k1171_res["per_market_summary"]:
            if r["market"] == "AU":
                au_inst = float(r["institutions_pct_mean"])
                break
        if au_inst is not None:
            markets = markets + ["AU"]
            xs.append(au_inst)
            ys.append(K1213_AU_THETA_REL)
    rho, p = spstats.spearmanr(xs, ys)
    return {"rho": float(rho), "p": float(p), "n": int(len(xs)),
            "markets_ordered": markets,
            "theta_rel_values": ys,
            "institutions_pct_mean_values": xs,
            "corrections_applied": corrections,
            "includes_au_k1213": include_au}


# =========================================================================
# Trajectory figure (combined)
# =========================================================================
def plot_5em_trajectory(out_path: Path, points: list[dict]):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 1, figsize=(12, 6))
    labels = [p["label"] for p in points]
    rhos   = [p["rho"] for p in points]
    ps     = [p["p"] for p in points]
    ns     = [p["n"] for p in points]
    xp = np.arange(len(labels))
    colors = []
    for lab in labels:
        if "K1172" in lab or "baseline" in lab:
            colors.append("#b22222")
        elif "K1216-" in lab and "+K1213" not in lab and "K1216b" not in lab:
            colors.append("#e58825")
        elif "K1213 AU" in lab and "K1216b" not in lab and "K1216" not in lab:
            colors.append("#d8a125")
        elif "K1216b" in lab:
            colors.append("#4a9b4a")
        else:
            colors.append("#8a8a8a")
    bars = ax.bar(xp, rhos, color=colors, alpha=0.85, edgecolor="black")
    for i, (r, p, n) in enumerate(zip(rhos, ps, ns)):
        if np.isfinite(r):
            ax.text(i, r + 0.015 if r >= 0 else r - 0.04,
                    f"{r:+.3f}\np={p:.3f}\nN={n}",
                    ha="center", fontsize=8,
                    fontweight="bold" if "5-EM" in labels[i] else "normal")
    ax.set_xticks(xp)
    ax.set_xticklabels(labels, fontsize=8, rotation=20, ha="right")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel(r"Spearman $\rho$(inst_pct_mean, $\theta_{rel}$)")
    ax.set_title("Paper 2 Section 5 cross-market Spearman: "
                 "K1172 baseline -> 5-EM multistart-audited refined trajectory")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# =========================================================================
# Main
# =========================================================================
def main():
    t_start = time.time()
    print(f"\n{'='*72}\nK1216b: Close 5-EM multistart audit with CH + ID\n"
          f"100 random starts per market, seeds 43..142\n{'='*72}")
    print(f"K1216 EM refined theta_rel loaded: {K1216_EM_REFINED_THETA_REL}")

    results_per_market: dict = {}
    for market in ("CH", "ID"):
        res = run_one_market(market, n_starts=100)
        results_per_market[market] = res
        if res.get("n_converged", 0) >= 5:
            theta_eavs = np.array(res["theta_eavs"])
            labels = np.array(res["labels"])
            plot_basin_hist(
                market, theta_eavs, labels,
                res["lbfgs_best_fit"]["theta_eav"],
                CANONICAL[market]["theta_eav"],
                ROOT / f"k1216b_{market}_basin_hist.png",
            )

    # -------------------------------------------------------------------
    # 5-EM Spearman rebuild scenarios
    # -------------------------------------------------------------------
    ch_best = results_per_market["CH"].get("best_fit", {})
    id_best = results_per_market["ID"].get("best_fit", {})
    ch_theta_rel_refined = ch_best.get("theta_rel")
    id_theta_rel_refined = id_best.get("theta_rel")

    sp_baseline_n12      = rebuild_baseline_spearman(include_au=False)
    sp_k1213_au_only_n13 = rebuild_au_only_spearman()
    sp_k1216_em_n12      = rebuild_k1216_em_only_spearman(include_au=False)
    sp_k1216_em_au_n13   = rebuild_k1216_em_only_spearman(include_au=True)
    sp_5em_n12           = rebuild_5em_spearman(
        ch_theta_rel_refined, id_theta_rel_refined, include_au_k1213=False)
    sp_5em_au_n13        = rebuild_5em_spearman(
        ch_theta_rel_refined, id_theta_rel_refined, include_au_k1213=True)

    print("\n[Spearman rebuilds]")
    scenarios = [
        ("K1172 baseline N=12 (canonical)",                  sp_baseline_n12),
        ("K1213 AU-only N=13 (canonical EM + AU refined)",   sp_k1213_au_only_n13),
        ("K1216 EM refined N=12 (BR/IN/MX; CH/ID canon)",    sp_k1216_em_n12),
        ("K1216 EM refined + K1213 AU N=13",                 sp_k1216_em_au_n13),
        ("K1216b 5-EM refined N=12 (BR/IN/MX/CH/ID)",        sp_5em_n12),
        ("K1216b 5-EM refined + K1213 AU N=13 (PRIMARY)",    sp_5em_au_n13),
    ]
    for label, s in scenarios:
        print(f"  {label}: rho={s['rho']:+.3f} p={s['p']:.4f} n={s['n']}")

    # Harvey t
    def harvey_t(rho: float, n: int) -> float | None:
        if not np.isfinite(rho) or n < 3:
            return None
        denom = max(1.0 - rho * rho, 1e-12)
        return float(rho * np.sqrt(n - 2) / np.sqrt(denom))
    harvey_ts = {lab: harvey_t(s["rho"], s["n"]) for lab, s in scenarios}
    print("\n[Harvey t per scenario]")
    for k, v in harvey_ts.items():
        print(f"  {k}: t={v}")

    # -------------------------------------------------------------------
    # Final cross-market verdict across 5 EM markets
    # -------------------------------------------------------------------
    # K1216 fragile: BR, IN, MX (all FRAGILE in k1216_results.json)
    k1216_verdicts = {"BR": "FRAGILE", "IN": "FRAGILE", "MX": "FRAGILE"}
    # AU: K1213 ABOVE_LADDER_OVERTURNED (FRAGILE in the same sense)
    au_verdict = "FRAGILE"
    # K1216b: CH, ID
    k1216b_verdicts = {m: results_per_market[m].get("per_market_verdict",
                                                     "INCONCLUSIVE")
                       for m in ("CH", "ID")}

    all5 = {**k1216_verdicts, **k1216b_verdicts, "AU": au_verdict}
    n_fragile = sum(1 for v in all5.values() if v == "FRAGILE")
    n_borderline = sum(1 for v in all5.values() if v == "BORDERLINE")
    n_robust = sum(1 for v in all5.values() if v == "ROBUST")

    if k1216b_verdicts["CH"] == "FRAGILE" and k1216b_verdicts["ID"] == "FRAGILE":
        cross = "ALL_5_EM_FRAGILE"
        narrative = (
            "All 5 EM markets (BR/IN/MX already K1216 FRAGILE; AU K1213 "
            "ABOVE_LADDER_OVERTURNED; CH + ID K1216b FRAGILE) show the same "
            "optimizer pathology: canonical pooled MLE trapped in secondary "
            "local minima. Paper 2 Section 5 EM above-ladder narrative based "
            "on K1168/K1172 canonical thetas is UNIVERSAL numerical artefact. "
            "Primary Spearman rho with ALL 5 EM thetas refined further "
            f"decays to {sp_5em_au_n13['rho']:+.3f} (p={sp_5em_au_n13['p']:.3f}, "
            f"N=13); institutional-ownership proxy prediction strength is "
            "substantially weaker than the K1172 baseline suggested."
        )
    elif k1216b_verdicts["CH"] == "ROBUST" and k1216b_verdicts["ID"] == "ROBUST":
        cross = "CH_ID_EXCEPTIONS"
        narrative = (
            "K1216b CH + ID pooled MLE ROBUST (canonical within LR chi^2 "
            "tolerance of multistart best-LL, sensitivity bounded). "
            "K1216 BR/IN/MX + K1213 AU remain FRAGILE. This partitions the "
            "EM panel: OFF-LADDER cases (high canonical theta_rel >=1) are "
            "trapped, ON-LADDER cases (CH 0.30, ID 0.24) are not. "
            "Supports a reading in which optimizer fragility is confined to "
            "high-theta starts where the identified shared-MIDAS coefficient "
            "falls near a penalty wall. Paper 2 Section 5 requires partial "
            "revision (BR/IN/MX/AU) but the on-ladder EM readings (CH/ID) "
            "stand."
        )
    else:
        cross = "PARTIAL"
        narrative = (
            f"Mixed verdict: CH={k1216b_verdicts['CH']}, "
            f"ID={k1216b_verdicts['ID']}. Combined with K1216 (BR/IN/MX "
            "FRAGILE) and K1213 AU (FRAGILE): 5-EM panel has "
            f"{n_fragile} FRAGILE / {n_borderline} BORDERLINE / {n_robust} "
            "ROBUST. Paper 2 Section 5 requires market-by-market disclosure "
            "of which pooled estimates are canonical and which are multistart-"
            "refined."
        )

    print(f"\n===== CROSS-MARKET 5-EM VERDICT: {cross} =====")
    print(narrative)

    # -------------------------------------------------------------------
    # Trajectory figure (combined 5-EM evolution)
    # -------------------------------------------------------------------
    trajectory_points = [
        {"label": "K1165 N=7\npre-EM",      "rho": 0.750,                  "p": 0.052, "n": 7},
        {"label": "K1168 N=10\n+BR/CH/IN",  "rho": 0.612,                  "p": 0.060, "n": 10},
        {"label": "K1172 N=12\n+MX/ID",     "rho": sp_baseline_n12["rho"], "p": sp_baseline_n12["p"], "n": sp_baseline_n12["n"]},
        {"label": "K1213 AU\nadded N=13",   "rho": sp_k1213_au_only_n13["rho"], "p": sp_k1213_au_only_n13["p"], "n": sp_k1213_au_only_n13["n"]},
        {"label": "K1216 EM refined\nN=12", "rho": sp_k1216_em_n12["rho"], "p": sp_k1216_em_n12["p"], "n": sp_k1216_em_n12["n"]},
        {"label": "K1216 EM + K1213 AU\nN=13", "rho": sp_k1216_em_au_n13["rho"], "p": sp_k1216_em_au_n13["p"], "n": sp_k1216_em_au_n13["n"]},
        {"label": "K1216b 5-EM refined\nN=12", "rho": sp_5em_n12["rho"],  "p": sp_5em_n12["p"],  "n": sp_5em_n12["n"]},
        {"label": "K1216b 5-EM + K1213 AU\nN=13 (FINAL)", "rho": sp_5em_au_n13["rho"], "p": sp_5em_au_n13["p"], "n": sp_5em_au_n13["n"]},
    ]
    plot_5em_trajectory(ROOT / "k1216b_5em_trajectory.png", trajectory_points)
    print("[figures] wrote per-market basin histograms + 5-EM trajectory.png")

    # -------------------------------------------------------------------
    # Per-start CSV and summary CSV
    # -------------------------------------------------------------------
    all_rows = []
    for m in ("CH", "ID"):
        for f in results_per_market[m].get("all_fits", []):
            r = dict(f)
            r["market"] = m
            if "x_final" in r:
                r.pop("x_final")
            all_rows.append(r)
    df = pd.DataFrame(all_rows)
    df.to_csv(ROOT / "k1216b_multistart_results.csv", index=False)
    print(f"[csv] wrote k1216b_multistart_results.csv ({len(df)} rows)")

    summary_rows = []
    for m in ("CH", "ID"):
        r = results_per_market[m]
        if "best_fit" not in r:
            continue
        summary_rows.append({
            "market": m,
            "n_stocks": r["n_stocks"],
            "n_converged": r["n_converged"],
            "canonical_theta_eav": CANONICAL[m]["theta_eav"],
            "canonical_theta_rel": r["canonical_theta_rel"],
            "canonical_loglik": CANONICAL[m]["loglik"],
            "k1216b_refined_theta_eav": r["best_fit"]["theta_eav"],
            "k1216b_refined_theta_rel": r["best_fit"]["theta_rel"],
            "k1216b_refined_loglik":    r["best_fit"]["loglik"],
            "k1216b_refined_source":    r["best_fit"]["source"],
            "k1216b_lbfgs_theta_eav":   r["lbfgs_best_fit"]["theta_eav"],
            "k1216b_lbfgs_theta_rel":   r["lbfgs_best_fit"]["theta_rel"],
            "k1216b_lbfgs_loglik":      r["lbfgs_best_fit"]["loglik"],
            "k1216b_lbfgs_basin":       r["lbfgs_best_fit"]["basin"],
            "k1216b_hessian_se":        r["best_fit"]["hessian_se"],
            "k1216b_hessian_t":         r["best_fit"]["hessian_t"],
            "k1216b_hac_se":            r["best_fit"]["hac_se"],
            "k1216b_hac_t":             r["best_fit"]["hac_t"],
            "ll_gap_refined_vs_canonical": r["ll_gap_refined_minus_canonical"],
            "ll_gap_lbfgs_vs_canonical":   r["ll_gap_lbfgs_minus_canonical"],
            "lr_stat_refined": r["lr_stat_refined_vs_canonical"],
            "theta_shift_pct": r["theta_shift_pct_vs_canonical"],
            "max_sens_delta_pct": r["max_sensitivity_delta_pct"],
            "basin_A_frac": r["basin_stats"]["basin_A_frac"],
            "basin_B_frac": r["basin_stats"]["basin_B_frac"],
            "per_market_verdict": r["per_market_verdict"],
        })
    pd.DataFrame(summary_rows).to_csv(
        ROOT / "k1216b_per_market_summary.csv", index=False)
    print("[csv] wrote k1216b_per_market_summary.csv")

    # -------------------------------------------------------------------
    # JSON results
    # -------------------------------------------------------------------
    def _strip(d):
        if isinstance(d, dict):
            return {k: _strip(v) for k, v in d.items() if k != "all_fits"}
        if isinstance(d, list):
            return [_strip(x) for x in d]
        return d

    out = {
        "experiment_id": "K1216b",
        "title": ("Close 5-EM multistart audit: CH + ID pooled MLE multi-start "
                  "search for secondary local minima"),
        "proposer": "User brief (K1216 WIDESPREAD_FRAGILITY follow-up)",
        "executor": "Claude (worktree agent agent-aa5753c4)",
        "global_seed": GLOBAL_SEED,
        "n_starts_per_market": 100,
        "start_seeds": list(range(43, 143)),
        "markets_tested": ["CH", "ID"],
        "runtime_sec": round(time.time() - t_start, 1),
        "per_market": {m: _strip(results_per_market[m]) for m in ("CH", "ID")},
        "canonical_reference": CANONICAL,
        "k1216_em_refined_theta_rel": K1216_EM_REFINED_THETA_REL,
        "k1213_au_refined_theta_rel": K1213_AU_THETA_REL,
        "spearman_rebuilds": {
            "baseline_k1172_n12":      sp_baseline_n12,
            "k1213_au_only_n13":       sp_k1213_au_only_n13,
            "k1216_em_refined_n12":    sp_k1216_em_n12,
            "k1216_em_refined_au_n13": sp_k1216_em_au_n13,
            "k1216b_5em_refined_n12":  sp_5em_n12,
            "k1216b_5em_refined_au_n13_primary": sp_5em_au_n13,
        },
        "harvey_t_per_scenario": harvey_ts,
        "all_5em_verdicts": all5,
        "n_fragile_5em": n_fragile,
        "n_borderline_5em": n_borderline,
        "n_robust_5em": n_robust,
        "cross_market_verdict_5em": cross,
        "cross_market_narrative_5em": narrative,
        "paper2_s5_full_trajectory_table": [
            {"label": "K1165 N=7 pre-EM (canonical dev markets)",
             "n": 7, "rho": 0.750, "p": 0.052},
            {"label": "K1168 N=10 +BR/CH/IN (canonical)",
             "n": 10, "rho": 0.612, "p": 0.060},
            {"label": "K1172 N=12 +MX/ID (canonical)",
             "n": sp_baseline_n12["n"], "rho": sp_baseline_n12["rho"],
             "p": sp_baseline_n12["p"]},
            {"label": "K1213 AU added N=13 (canonical EM, refined AU)",
             "n": sp_k1213_au_only_n13["n"],
             "rho": sp_k1213_au_only_n13["rho"],
             "p": sp_k1213_au_only_n13["p"]},
            {"label": "K1216 EM refined N=12 (BR/IN/MX refined)",
             "n": sp_k1216_em_n12["n"], "rho": sp_k1216_em_n12["rho"],
             "p": sp_k1216_em_n12["p"]},
            {"label": "K1216 EM + K1213 AU N=13",
             "n": sp_k1216_em_au_n13["n"], "rho": sp_k1216_em_au_n13["rho"],
             "p": sp_k1216_em_au_n13["p"]},
            {"label": "K1216b 5-EM refined N=12",
             "n": sp_5em_n12["n"], "rho": sp_5em_n12["rho"],
             "p": sp_5em_n12["p"]},
            {"label": "K1216b 5-EM + K1213 AU N=13 (FINAL PRIMARY)",
             "n": sp_5em_au_n13["n"], "rho": sp_5em_au_n13["rho"],
             "p": sp_5em_au_n13["p"]},
        ],
        "data_sources": [
            "experiments/k1168/data/ (CH parquet + VIX + earnings; unchanged)",
            "experiments/k1168/k1168_per_stock_refit.py (CH pooled MLE; "
            "imported as-is)",
            "experiments/k1172/data/ (ID parquet + VIX + earnings; unchanged)",
            "experiments/k1172/k1172_per_stock_refit.py (ID pooled MLE; "
            "imported as-is)",
            "experiments/k1172/k1172_results.json (N=12 baseline Spearman, "
            "canonical theta_rel values for dev markets)",
            "experiments/k1216/k1216_results.json (BR/IN/MX refined "
            "theta_rel for 5-EM rebuild)",
            "experiments/k1213/ via K1213_AU_THETA_REL constant (AU refined)",
            "experiments/k1171/k1171_results.json (AU inst_pct_mean for N=13)",
            "experiments/k1216/k1216.py (shared optimization helpers; "
            "re-imported by file path, not rewritten)",
        ],
        "rigor_notes": {
            "seed_discipline": "base=42; 100 starts = 43..142 "
                               "(identical to K1213/K1216; cross-market "
                               "reproducible)",
            "bounds": "identical to K1168 (CH) / K1172 (ID): same spec "
                      "ensures 5-EM comparability",
            "lookahead_guard": "inherited (_pooled_negll shifts "
                               "VIX^2_{t-1} and EAV_{t-1})",
            "optimizer_comparison": "L-BFGS-B primary; Nelder-Mead + "
                                    "differential_evolution sensitivity; "
                                    "refined best = max LL over all valid",
            "se_type": "Hessian + HAC-robust (stock-level score contributions)",
            "penalty_trap_guard": "reject fits with res.fun > 1e11 or LL<1000",
            "kmeans_seed": 42,
            "do_not_rewrite": ("K1216 helpers (load_market_stocks, "
                               "fit_pooled_lbfgs, kmeans_basins, "
                               "hessian_se, hac_se, run_sensitivity, "
                               "plot_basin_hist) imported by file path; "
                               "only MARKET_SPEC/CANONICAL/ROOT globals "
                               "monkey-patched"),
        },
    }
    with open(ROOT / "k1216b_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("[json] wrote k1216b_results.json")
    print(f"[done] total {time.time() - t_start:.1f}s")
    return out


if __name__ == "__main__":
    main()
