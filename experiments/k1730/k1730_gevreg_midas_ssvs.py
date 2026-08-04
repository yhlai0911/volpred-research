"""
K1730 — GEVReg-MIDAS-SSVS: interval forecasts of SPY realized volatility from
monthly macro data.

Research question
-----------------
Do monthly macroeconomic variables, aggregated to weekly frequency by a MIDAS
filter and selected by Bayesian spike-and-slab, improve *interval* (tail)
forecasts of realized volatility relative to purely autoregressive benchmarks?

Design
------
Target      log of the maximum daily SPY Parkinson realized variance within a
            calendar week (non-overlapping weekly block maxima)
Origin      last trading day of the preceding week
Sample      1995-02 .. 2026-07 (1,640 weekly blocks)
Estimation  expanding window, re-estimated each 1 January
OOS         2008-01 .. 2026-07 (967 weekly forecasts), spanning the GFC,
            the post-crisis calm, COVID and the 2022 tightening bear market
Macro       CPI, payrolls, industrial production, unemployment (all ALFRED
            first-release point-in-time), VIX and the 10Y-3M term spread
Models      GEVReg-MIDAS-SSVS (posterior predictive), GEV-HAR (no macro),
            Gaussian-MIDAS, HAR quantile regression, expanding empirical quantile
Scoring     Kupiec UC, Christoffersen independence + CC, pinball loss,
            McNeil-Frey ES backtest, Diebold-Mariano (repo-canonical HAC)
Seed        42 throughout

Run:  uv run python k1730_gevreg_midas_ssvs.py [--quick]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import k1730_data as D          # noqa: E402
import k1730_models as M        # noqa: E402
import k1730_scoring as S       # noqa: E402

SEED = 42
OOS_START = "2008-01-01"
OMEGA_GRID = [1.01, 2.0, 3.0, 5.0, 8.0, 12.0]

TAUS = np.array([0.005, 0.01, 0.025, 0.05, 0.10, 0.25, 0.50,
                 0.75, 0.90, 0.95, 0.975, 0.99, 0.995])
IDX = {float(t): i for i, t in enumerate(TAUS)}

INTERVALS = [(0.90, 0.05, 0.95), (0.95, 0.025, 0.975)]
VAR_LEVELS = [0.95, 0.99]

SUBPERIODS = [
    ("2008-2009 GFC", "2008-01-01", "2009-12-31"),
    ("2010-2019 post-crisis", "2010-01-01", "2019-12-31"),
    ("2020-2021 COVID", "2020-01-01", "2021-12-31"),
    ("2022-2026 tightening", "2022-01-01", "2026-12-31"),
]

MODELS = ["GEVReg-MIDAS-SSVS", "GEV-HAR", "Gaussian-MIDAS", "HAR-QR", "Empirical"]
DISTRIBUTIONAL = {"GEVReg-MIDAS-SSVS", "GEV-HAR", "Gaussian-MIDAS"}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ==========================================================================
# Rolling out-of-sample engine
# ==========================================================================

def run_oos(weeks: pd.DataFrame, tensor: np.ndarray, cfg: dict,
            label: str = "main", valid: np.ndarray | None = None) -> dict:
    """Expanding-window OOS interval forecasts for every model.

    Parameters are re-estimated on each 1 January using only blocks that had
    already *closed* before that date; between refits the parameters are frozen
    and only the covariates update. Every forecast therefore uses parameters
    estimated on strictly prior data.

    ``valid`` optionally restricts which weekly blocks may enter estimation or
    scoring. The placebo arms need it: a shifted macro history is undefined for
    the first L weeks, and the real arm has to be re-run on the identical row
    set so the two differ only in the alignment of the macro block.
    """
    y = weeks["y"].values.astype(float)
    block_start = pd.to_datetime(weeks["block_start"])
    block_end = pd.to_datetime(weeks["block_end"])
    if valid is None:
        valid = np.ones(len(weeks), dtype=bool)

    oos_mask = (block_start >= pd.Timestamp(OOS_START)).values & valid
    oos_mask = pd.Series(oos_mask, index=block_start.index)
    refit_years = sorted(block_start[oos_mask].dt.year.unique())
    log(f"  [{label}] {int(oos_mask.sum())} OOS blocks, {len(refit_years)} annual refits")

    preds = {m: np.full((len(weeks), len(TAUS)), np.nan) for m in MODELS}
    es_pred = {m: {p: np.full(len(weeks), np.nan) for p in VAR_LEVELS}
               for m in DISTRIBUTIONAL}
    refit_records = []

    for year in refit_years:
        refit_date = pd.Timestamp(f"{year}-01-01")
        # Estimation set: blocks that finished strictly before the refit date.
        est = (block_end < refit_date).values & valid
        # Forecast set: blocks starting in this calendar year.
        fut = ((block_start >= refit_date)
               & (block_start < pd.Timestamp(f"{year + 1}-01-01"))).values & valid
        if est.sum() < 200 or fut.sum() == 0:
            continue

        t_refit = time.time()

        # --- select the MIDAS decay by profile likelihood on the est. sample --
        best = None
        for omega in OMEGA_GRID:
            X, sc, names = M.build_design(weeks, tensor, omega, D.MACRO_VARS)
            std = M.Standardizer(X[est])
            Xs = std.apply(X)
            f = M.fit_gev_reg(y[est], Xs[est], sc[est],
                              n_starts=cfg["n_starts"], seed=SEED)
            if not f.get("converged"):
                continue
            if best is None or f["log_likelihood"] > best["fit"]["log_likelihood"]:
                best = {"omega": omega, "fit": f, "X": X, "Xs": Xs,
                        "sc": sc, "names": names, "std": std}
        if best is None:
            log(f"    {year}: no omega produced a converged GEV fit — skipped")
            continue

        omega, gev_fit = best["omega"], best["fit"]
        Xs, sc, names = best["Xs"], best["sc"], best["names"]
        n_beta = Xs.shape[1]
        n_macro = len(D.MACRO_VARS)

        # --- SSVS on the GEV likelihood --------------------------------------
        ssvs = M.ssvs_gev(y[est], Xs[est], sc[est], gev_fit, n_macro=n_macro,
                          n_draws=cfg["n_draws"], n_burnin=cfg["n_burnin"],
                          thin=cfg["thin"], seed=SEED, n_chains=cfg["n_chains"])

        # --- GEV without any macro block (isolates what macro adds) ----------
        active = np.ones(n_beta)
        active[n_beta - n_macro:] = 0.0
        gev_har = M.fit_gev_reg(y[est], Xs[est], sc[est],
                                n_starts=cfg["n_starts"], seed=SEED, active=active)

        # --- baselines --------------------------------------------------------
        gauss = M.fit_gaussian_midas(y[est], Xs[est], sc[est])
        X_har = Xs[:, :4]                      # const + har_d + har_w + har_m
        har_qr = M.fit_har_quantile(y[est], X_har[est], TAUS)
        emp_q = M.empirical_quantiles(y[est], TAUS)

        # --- produce forecasts for every block in this year -------------------
        for i in np.where(fut)[0]:
            if ssvs.get("ok"):
                preds["GEVReg-MIDAS-SSVS"][i] = M.ssvs_predictive_quantiles(
                    ssvs, Xs[i], sc[i], n_beta, TAUS,
                    n_draws_used=cfg["n_pred_draws"])
            if gev_har.get("converged"):
                mu, sg, xi = M.gev_predict(gev_har, Xs[i], sc[i])
                preds["GEV-HAR"][i] = M.gev_quantile(TAUS, mu, sg, xi)
                for p in VAR_LEVELS:
                    es_pred["GEV-HAR"][p][i] = M.gev_expected_shortfall(p, mu, sg, xi)
            preds["Gaussian-MIDAS"][i] = M.gaussian_midas_quantiles(
                gauss, Xs[i], sc[i], TAUS)
            preds["HAR-QR"][i] = M.har_quantile_predict(har_qr, X_har[i], TAUS)
            preds["Empirical"][i] = emp_q

            mu_g = float(Xs[i] @ gauss["beta"])
            sg_g = float(np.exp(gauss["phi0"] + gauss["phi1"] * sc[i]))
            for p in VAR_LEVELS:
                # Gaussian ES: mu + sigma * phi(z_p)/(1-p)
                from scipy import stats as _st
                z = _st.norm.ppf(p)
                es_pred["Gaussian-MIDAS"][p][i] = mu_g + sg_g * _st.norm.pdf(z) / (1 - p)

        # SSVS expected shortfall: average the ES over posterior draws.
        if ssvs.get("ok"):
            draws = ssvs["param_draws"]
            sel = draws[np.linspace(0, len(draws) - 1,
                                    min(cfg["n_pred_draws"], len(draws))).astype(int)]
            for i in np.where(fut)[0]:
                for p in VAR_LEVELS:
                    vals = []
                    for prm in sel:
                        beta = prm[:n_beta]
                        mu = float(Xs[i] @ beta)
                        sg = float(np.exp(prm[n_beta] + prm[n_beta + 1] * sc[i]))
                        xi = float(prm[n_beta + 2])
                        vals.append(M.gev_expected_shortfall(p, mu, sg, xi))
                    es_pred["GEVReg-MIDAS-SSVS"][p][i] = float(np.nanmean(vals))

        refit_records.append({
            "year": int(year),
            "n_estimation": int(est.sum()),
            "n_forecast": int(fut.sum()),
            "selected_omega": float(omega),
            "gev": {
                "log_likelihood": gev_fit["log_likelihood"],
                "xi": gev_fit["xi"],
                "phi0": gev_fit["phi0"], "phi1": gev_fit["phi1"],
                "coefficients": {n: float(b) for n, b in zip(names, gev_fit["beta"])},
                # Start quality and surface shape are separate quantities; the
                # pre-remediation record conflated them under one name.
                "feasible_start_rate": gev_fit["feasible_start_rate"],
                "feasible_optimum_rate": gev_fit["feasible_optimum_rate"],
                "lbfgs_success_rate": gev_fit["lbfgs_success_rate"],
                "n_feasible_optima": gev_fit["n_feasible_optima"],
                "n_at_best_basin": gev_fit["n_at_best_basin"],
                "basin_concentration": gev_fit["basin_concentration"],
                "nll_spread": gev_fit["nll_spread"],
                "nelder_mead_improvement": gev_fit["nelder_mead_improvement"],
                "hessian_pd": gev_fit["hessian_pd"],
                "hessian_cond": gev_fit["hessian_cond"],
            },
            "gev_har_no_macro": {
                "converged": bool(gev_har.get("converged")),
                "log_likelihood": gev_har.get("log_likelihood"),
                "xi": gev_har.get("xi"),
            },
            "ssvs": ({
                "pip": {v: float(p) for v, p in zip(D.MACRO_VARS, ssvs["pip"])},
                "acceptance_fixed": ssvs["acceptance_rate"],
                "acceptance_macro": ssvs["acceptance_macro_mean"],
                "acceptance_mode_jump": ssvs["acceptance_mode_jump_mean"],
                "geweke_max_abs_z": ssvs["geweke_max_abs_z"],
                "geweke_max_abs_z_fixed_bandwidth":
                    ssvs["geweke_max_abs_z_fixed_bandwidth"],
                "rhat_max": ssvs["rhat_max"],
                "ess_min": ssvs["ess_min"],
                "ess_delta_min": ssvs["ess_delta_min"],
                "pip_max_chain_spread": ssvs["pip_max_chain_spread"],
                "n_kept": ssvs["n_kept"],
                "converged": ssvs["converged"],
            } if ssvs.get("ok") else {"ok": False, "reason": ssvs.get("reason")}),
            "gaussian_midas_loglik": gauss["log_likelihood"],
            "elapsed_sec": round(time.time() - t_refit, 1),
        })
        pip_str = ", ".join(
            f"{v}={p:.2f}" for v, p in zip(D.MACRO_VARS, ssvs["pip"])
        ) if ssvs.get("ok") else "SSVS failed"
        log(f"    {year}: n_est={int(est.sum())} omega={omega} xi={gev_fit['xi']:+.3f} "
            f"| {pip_str} | {time.time() - t_refit:.0f}s")

    return {"preds": preds, "es_pred": es_pred, "refits": refit_records,
            "oos_mask": oos_mask.values}


# ==========================================================================
# Non-circular lag-shift placebo
# ==========================================================================

# Lags, in weeks, at which the macro history is re-attached to the target. The
# MIDAS tensor spans the 12 most recent monthly releases, so the smallest shift
# (one year) already makes the freshest macro month older than the oldest month
# the real model sees: the two windows do not overlap at any shift used here.
PLACEBO_SHIFTS = [52, 104, 156, 208, 260]


def shift_rows(arr: np.ndarray, lag: int, fill) -> np.ndarray:
    """``out[i] = arr[i - lag]``; the first ``lag`` rows are undefined.

    Deliberately *not* circular. Wrapping the tail back onto the head is what
    makes a naive permutation unusable here: it would place macro values from
    2026 in front of 1995 origins, i.e. reintroduce exactly the lookahead the
    placebo exists to rule out. Leaving the head undefined and excluding it from
    every arm costs 260 of 1,640 weekly blocks and buys a placebo that is
    leakage-free by construction rather than by hope.
    """
    out = np.empty_like(arr)
    out[lag:] = arr[:-lag]
    out[:lag] = fill
    return out


def _arm_worker(payload: tuple) -> dict:
    """One placebo arm, in its own process. Returns only picklable summaries."""
    label, weeks, tensor_arm, valid, cfg = payload
    run = run_oos(weeks, tensor_arm, cfg, label=label, valid=valid)
    scored = score_all(weeks, run)
    pip_refits = [r for r in run["refits"] if "pip" in r.get("ssvs", {})]
    return {
        "label": label,
        "n_scored": scored["n_common_oos"],
        "mean_pinball": {m: scored["by_model"][m]["mean_pinball"] for m in MODELS},
        "coverage_0.90": {
            m: scored["by_model"][m]["intervals"]["0.90"]["empirical_coverage"]
            for m in MODELS},
        "mean_pip": {
            v: float(np.mean([r["ssvs"]["pip"][v] for r in pip_refits]))
            for v in D.MACRO_VARS} if pip_refits else {},
        "n_refits": len(run["refits"]),
    }


def placebo_submit(weeks: pd.DataFrame, tensor: np.ndarray, stamp: np.ndarray,
                   cfg: dict, n_workers: int = 6):
    """Verify the shifted histories, then launch every placebo arm.

    Returns ``(executor, futures, meta)``. The arms are independent of the main
    run, so the caller starts them here and then estimates the main arm in this
    process while they work — seven sequential re-estimations would otherwise
    take twice the wall clock for no reason.
    """
    n = len(weeks)
    l_max = max(PLACEBO_SHIFTS)
    valid = np.arange(n) >= l_max
    log(f"    matched sample: {int(valid.sum())}/{n} blocks "
        f"(first {l_max} dropped from every arm)")

    stamp_checks = {}
    for lag in PLACEBO_SHIFTS:
        rep = D.assert_no_lookahead(weeks, shift_rows(stamp, lag, 0))
        stamp_checks[f"shift_{lag}w"] = rep
        if not rep["passed"]:
            raise RuntimeError(f"placebo shift {lag} introduced lookahead: {rep}")
    log(f"    lookahead re-checked on all {len(PLACEBO_SHIFTS)} shifted "
        f"macro histories: 0 violations")

    payloads = [("real_matched", weeks, tensor, valid, cfg)]
    for lag in PLACEBO_SHIFTS:
        payloads.append((f"placebo_shift_{lag}w", weeks,
                         shift_rows(tensor, lag, np.nan), valid, cfg))

    meta = {"valid": valid, "l_max": l_max, "stamp_checks": stamp_checks}
    if n_workers <= 1:
        return None, [_arm_worker(p) for p in payloads], meta

    from concurrent.futures import ProcessPoolExecutor
    ex = ProcessPoolExecutor(max_workers=min(n_workers, len(payloads)))
    futures = [ex.submit(_arm_worker, p) for p in payloads]
    log(f"    {len(futures)} arms dispatched to {min(n_workers, len(payloads))} "
        f"workers; estimating the main arm meanwhile")
    return ex, futures, meta


def placebo_collect(executor, futures, meta: dict, scored_main: dict) -> dict:
    """Placebo test: re-attach the macro history at a set of time lags.

    Design, and the null it addresses
    ---------------------------------
    H0 is that the macro block carries no information about *this* week's block
    maximum beyond what the HAR terms already carry. A placebo has to break the
    correspondence between the macro history and the target week while leaving
    everything else — the target, the HAR inputs, the estimation protocol, the
    sample — untouched.

    A whole-sample permutation, which is what this experiment did before the
    2026-07-19 remediation, fails on two counts. It destroys the serial
    dependence of the macro tensor, so the placebo model is fed a covariate with
    statistical properties no real macro series has, and any degradation is
    attributable to that rather than to the loss of alignment. And it moves
    later values in front of earlier origins: recomputing the availability
    stamps under that permutation put 54,950 of 118,080 macro cells in the
    future of the origin using them. A placebo that itself leaks cannot be
    evidence about leakage.

    A lag shift breaks alignment and nothing else:

    * **preserved** — the macro tensor is the same sequence, so every
      autocorrelation, trend, level and cross-variable covariance survives
      intact, as does the within-row alignment across the 12 MIDAS lags;
    * **broken** — which target week each macro history is asked to predict;
    * **guaranteed** — week ``i`` receives the history of week ``i - L``, whose
      releases all predate origin ``i - L`` and therefore origin ``i``. Zero
      lookahead by construction, and verified below by re-running the same
      point-in-time check on the shifted stamps rather than trusting the
      argument.

    Every arm, including the real one, is scored on the identical row set
    (blocks ``>= max(shifts)``), so the real-vs-placebo comparison differs in
    the macro alignment and in nothing else. Note that each arm re-selects
    omega, re-standardizes, re-runs the MLE and re-runs the sampler: the
    placebo is a full re-estimation, not a re-scoring of frozen parameters.

    What the result can support: with 5 shifts the reference distribution has 6
    points, so the smallest attainable one-sided p-value is 1/6 = 0.167. This is
    a coarse placebo comparison and is reported as one. It cannot deliver a
    precise permutation p-value, and no claim here rests on it doing so.
    """
    if executor is None:
        arm_results = futures                      # already materialised
    else:
        arm_results = [f.result() for f in futures]
        executor.shutdown()
    valid, l_max = meta["valid"], meta["l_max"]
    stamp_checks = meta["stamp_checks"]

    by_label = {a["label"]: a for a in arm_results}
    focal = "GEVReg-MIDAS-SSVS"
    real = by_label["real_matched"]["mean_pinball"][focal]
    placebo = {a["label"]: a["mean_pinball"][focal]
               for a in arm_results if a["label"] != "real_matched"}
    pv = sorted(placebo.values())

    # One-sided: how often does a placebo do at least as well as the real macro?
    n_at_least_as_good = int(sum(v <= real for v in pv))
    p_value = (n_at_least_as_good + 1) / (len(pv) + 1)

    if n_at_least_as_good == 0:
        interp = ("Every placebo alignment scored worse than the real macro "
                  "alignment. Consistent with the macro block carrying "
                  "target-specific information, though with 5 shifts the "
                  "evidence is coarse.")
    elif n_at_least_as_good >= len(pv) / 2.0:
        interp = ("The real macro alignment sits inside the spread of placebo "
                  "alignments: re-attaching the macro history at an arbitrary "
                  "lag does the job about as well. That is what a null macro "
                  "contribution looks like, and it is the expected outcome "
                  "under H0 rather than a failed check.")
    else:
        interp = ("The real macro alignment scores better than most but not all "
                  "placebo alignments; the separation is not clean enough to "
                  "distinguish a small contribution from sampling noise.")

    out = {
        "design": "macro MIDAS tensor re-attached to the target at fixed weekly "
                  "lags (non-circular); target, HAR inputs, estimation protocol "
                  "and sample held identical across arms",
        "why_not_whole_sample_permutation":
            "a whole-sample shuffle destroys the serial dependence of the macro "
            "tensor and moves later releases in front of earlier origins "
            "(54,950/118,080 cells under the pre-remediation permutation), so "
            "it can support neither a placebo nor a leakage reading",
        "what_it_tests": "whether the macro block's *alignment with the target* "
                         "carries information; it is not a test of leakage and "
                         "not on its own evidence of signal",
        "shifts_weeks": PLACEBO_SHIFTS,
        "matched_sample_blocks": int(valid.sum()),
        "blocks_dropped_from_every_arm": int(l_max),
        "lookahead_recheck_on_shifted_stamps": stamp_checks,
        "seed": SEED,
        "mean_pinball_real_matched": real,
        "mean_pinball_placebo": placebo,
        "placebo_min": pv[0], "placebo_median": float(np.median(pv)),
        "placebo_max": pv[-1],
        "n_placebo_at_least_as_good_as_real": n_at_least_as_good,
        "n_placebo_arms": len(pv),
        "one_sided_p_value": float(p_value),
        "p_value_resolution_note":
            f"with {len(pv)} shifts the smallest attainable p-value is "
            f"{1.0 / (len(pv) + 1):.3f}; this is a coarse placebo comparison, "
            f"not a precise permutation test",
        "interpretation": interp,
        "mean_pinball_gev_har_no_macro":
            by_label["real_matched"]["mean_pinball"]["GEV-HAR"],
        "mean_pip_real_matched": by_label["real_matched"]["mean_pip"],
        "mean_pip_placebo": {a["label"]: a["mean_pip"]
                             for a in arm_results if a["label"] != "real_matched"},
        "mean_pip_note": "diagnostic only — the sampler does not meet the "
                         "convergence gate; see ssvs_summary.inference_tier",
        "full_sample_main_run_pinball":
            scored_main["by_model"][focal]["mean_pinball"],
        "arms": arm_results,
    }
    log(f"    real={real:.5f}  placebo range=[{pv[0]:.5f}, {pv[-1]:.5f}]  "
        f"p={p_value:.3f}")
    return out


# ==========================================================================
# Scoring
# ==========================================================================

def score_all(weeks: pd.DataFrame, run: dict) -> dict:
    y = weeks["y"].values.astype(float)
    block_start = pd.to_datetime(weeks["block_start"])
    preds, es_pred = run["preds"], run["es_pred"]

    # Score only rows where *every* model produced a forecast, so all models
    # face an identical evaluation sample. Comparing models on different
    # subsets would make the DM tests meaningless.
    common = run["oos_mask"].copy()
    for m in MODELS:
        common &= np.isfinite(preds[m]).all(axis=1)
    log(f"  Common evaluation sample: {int(common.sum())} blocks")

    results = {"n_common_oos": int(common.sum()),
               "oos_start": str(block_start[common].min().date()),
               "oos_end": str(block_start[common].max().date()),
               "by_model": {}, "dm_tests": {}, "subperiods": {}}

    pinball = {m: S.mean_pinball_across_taus(y[common], preds[m][common], TAUS)
               for m in MODELS}

    for m in MODELS:
        q = preds[m][common]
        entry = {"intervals": {}, "var_levels": {},
                 "mean_pinball": float(np.mean(pinball[m])),
                 "pinball_by_tau": {}, "qrmse_median": S.qrmse(y[common], q[:, IDX[0.5]])}
        for k, tau in enumerate(TAUS):
            entry["pinball_by_tau"][str(float(tau))] = float(
                np.mean(S.pinball_loss(y[common], q[:, k], float(tau))))
        for nominal, lo_t, hi_t in INTERVALS:
            entry["intervals"][f"{nominal:.2f}"] = S.interval_coverage_report(
                y[common], q[:, IDX[lo_t]], q[:, IDX[hi_t]], nominal)
        pit = S.pit_diagnostics(y[common], q, TAUS)
        entry["pit"] = {k: v for k, v in pit.items() if not k.startswith("_")}
        entry["_pit_values"] = pit["_pit"]
        for p in VAR_LEVELS:
            rep = S.var_coverage_report(y[common], q[:, IDX[p]], p)
            if m in DISTRIBUTIONAL:
                rep["expected_shortfall"] = S.es_backtest(
                    y[common], q[:, IDX[p]], es_pred[m][p][common], seed=SEED)
            else:
                rep["expected_shortfall"] = {
                    "note": "not computed — this model yields quantiles, not a "
                            "full predictive tail, so ES is not identified from it"}
            entry["var_levels"][f"{p:.3f}"] = rep
        results["by_model"][m] = entry

    # --- Diebold-Mariano: the GEV model against every benchmark -------------
    # nested-dm: diagnostic-only.  GEV-HAR nests inside GEVReg-MIDAS-SSVS
    # (zero the macro block), the loss is pinball (general, non-differentiable)
    # and the scheme is recursive/expanding — K1731 F1 established this triple
    # has NO published inference method (CW/GW/McCracken all inapplicable).
    # Per K1730_NESTED_DM_ADJUDICATION.md (2026-07-21) the vs-GEV-HAR DM was
    # RETRACTED as inference and re-labelled diagnostic-only; the NULL claim
    # rests on descriptive loss ordering + the lag-shift placebo, and the only
    # valid repair is the randomization test specified in that document §4.
    focal = "GEVReg-MIDAS-SSVS"
    for bench in MODELS:
        if bench == focal:
            continue
        results["dm_tests"][f"{focal}_vs_{bench}"] = S.dm_with_diagnostics(
            pinball[focal], pinball[bench], h=1)

    # --- subperiods ---------------------------------------------------------
    bs_common = block_start[common].reset_index(drop=True)
    y_common = y[common]
    for name, start, end in SUBPERIODS:
        sel = ((bs_common >= pd.Timestamp(start)) & (bs_common <= pd.Timestamp(end))).values
        if sel.sum() < 30:
            results["subperiods"][name] = {"n": int(sel.sum()),
                                           "note": "too few blocks to score"}
            continue
        sub = {"n": int(sel.sum()), "by_model": {}, "dm_tests": {}}
        for m in MODELS:
            q = preds[m][common][sel]
            sub["by_model"][m] = {
                "mean_pinball": float(np.mean(pinball[m][sel])),
                "coverage_0.90": S.interval_coverage_report(
                    y_common[sel], q[:, IDX[0.05]], q[:, IDX[0.95]], 0.90),
                "var_0.95": S.var_coverage_report(y_common[sel], q[:, IDX[0.95]], 0.95),
            }
        for bench in MODELS:
            if bench == focal:
                continue
            sub["dm_tests"][f"{focal}_vs_{bench}"] = S.dm_with_diagnostics(
                pinball[focal][sel], pinball[bench][sel], h=1)
        results["subperiods"][name] = sub

    results["_pinball_series"] = {m: pinball[m] for m in MODELS}
    results["_common_mask"] = common
    results["_pit_values"] = {m: results["by_model"][m].pop("_pit_values")
                              for m in MODELS}
    return results


# ==========================================================================
# Figures
# ==========================================================================

def make_figures(weeks: pd.DataFrame, run: dict, scored: dict) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    common = scored["_common_mask"]
    y = weeks["y"].values.astype(float)[common]
    dates = pd.to_datetime(weeks["block_start"])[common].reset_index(drop=True)
    preds = {m: run["preds"][m][common] for m in MODELS}
    written = []

    # --- Figure 1: rolling coverage of the 90% interval ---------------------
    fig, ax = plt.subplots(figsize=(12, 5.5))
    win = 104
    for m in MODELS:
        inside = ((y >= preds[m][:, IDX[0.05]]) & (y <= preds[m][:, IDX[0.95]])).astype(float)
        roll = pd.Series(inside).rolling(win).mean()
        ax.plot(dates, roll, label=m, lw=1.5, alpha=0.85)
    ax.axhline(0.90, color="k", ls="--", lw=1.2, label="nominal 90%")
    ax.set_title(f"Rolling {win}-week empirical coverage of the nominal 90% interval\n"
                 "SPY weekly block-maximum realized variance, out-of-sample")
    ax.set_ylabel("empirical coverage")
    ax.set_xlabel("block start")
    ax.set_ylim(0.5, 1.02)
    ax.legend(loc="lower left", fontsize=8, ncol=3)
    ax.grid(alpha=0.3)
    p = HERE / "fig1_rolling_coverage.png"
    fig.tight_layout(); fig.savefig(p, dpi=150); plt.close(fig)
    written.append(p.name)

    # --- Figure 2: SSVS posterior inclusion probabilities by refit vintage --
    refits = scored["_refits"]
    years = [r["year"] for r in refits if "pip" in r.get("ssvs", {})]
    if years:
        mat = np.array([[refits[i]["ssvs"]["pip"][v] for v in D.MACRO_VARS]
                        for i, r in enumerate(refits) if "pip" in r.get("ssvs", {})])
        fig, axes = plt.subplots(1, 2, figsize=(14, 5),
                                 gridspec_kw={"width_ratios": [1.35, 1]})
        im = axes[0].imshow(mat.T, aspect="auto", cmap="YlOrRd", vmin=0, vmax=1)
        axes[0].set_yticks(range(len(D.MACRO_VARS)))
        axes[0].set_yticklabels(D.MACRO_VARS)
        step = max(len(years) // 12, 1)
        axes[0].set_xticks(range(0, len(years), step))
        axes[0].set_xticklabels([years[i] for i in range(0, len(years), step)], rotation=45)
        axes[0].set_title("SSVS posterior inclusion probability by refit vintage\n"
                          "DIAGNOSTIC ONLY — sampler does not meet the "
                          "convergence gate (see README §6)", fontsize=10)
        fig.colorbar(im, ax=axes[0], label="PIP")

        mean_pip = mat.mean(axis=0)
        order = np.argsort(mean_pip)
        axes[1].barh([D.MACRO_VARS[i] for i in order], mean_pip[order], color="#c0392b")
        axes[1].axvline(0.5, color="k", ls="--", lw=1.2, label="median-model threshold")
        axes[1].set_xlim(0, 1)
        axes[1].set_xlabel("mean PIP across refits")
        axes[1].set_title("Average inclusion probability")
        axes[1].legend(fontsize=8)
        axes[1].grid(alpha=0.3, axis="x")
        p = HERE / "fig2_ssvs_pip.png"
        fig.tight_layout(); fig.savefig(p, dpi=150); plt.close(fig)
        written.append(p.name)

    # --- Figure 3: predicted interval vs realization ------------------------
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharey=False)
    for ax, (lo, hi, title) in zip(axes, [
        ("2007-06-01", "2010-06-30", "Global financial crisis"),
        ("2019-06-01", "2022-12-31", "COVID crash and 2022 tightening"),
    ]):
        sel = ((dates >= pd.Timestamp(lo)) & (dates <= pd.Timestamp(hi))).values
        if sel.sum() == 0:
            continue
        dd, yy = dates[sel], y[sel]
        g = preds["GEVReg-MIDAS-SSVS"][sel]
        h = preds["HAR-QR"][sel]
        ax.fill_between(dd, g[:, IDX[0.05]], g[:, IDX[0.95]], alpha=0.30,
                        color="#c0392b", label="GEVReg-MIDAS-SSVS 90% interval")
        ax.plot(dd, h[:, IDX[0.95]], color="#2980b9", lw=1.1, ls="--",
                label="HAR-QR 95th percentile")
        ax.plot(dd, g[:, IDX[0.5]], color="#c0392b", lw=1.0, label="GEV median")
        ax.plot(dd, yy, color="k", lw=1.0, label="realized log block-max RV")
        ax.set_title(title)
        ax.set_ylabel("log block-max RV")
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(alpha=0.3)
    fig.suptitle("Predicted intervals versus realized weekly block-maximum RV")
    p = HERE / "fig3_interval_vs_realized.png"
    fig.tight_layout(); fig.savefig(p, dpi=150); plt.close(fig)
    written.append(p.name)

    # --- Figure 4: PIT calibration histograms -------------------------------
    fig, axes = plt.subplots(1, len(MODELS), figsize=(4 * len(MODELS), 3.6),
                             sharey=True)
    for ax, m in zip(np.atleast_1d(axes), MODELS):
        pit = scored["_pit_values"][m]
        ax.hist(pit, bins=10, range=(0, 1), color="#34495e",
                edgecolor="white", alpha=0.9)
        ax.axhline(len(pit) / 10.0, color="#c0392b", ls="--", lw=1.5)
        chi2_p = scored["by_model"][m]["pit"]["chi2_p_value"]
        ax.set_title(f"{m}\nPIT uniformity chi2 p={chi2_p:.3g}", fontsize=9)
        ax.set_xlabel("PIT value")
        ax.grid(alpha=0.3, axis="y")
    np.atleast_1d(axes)[0].set_ylabel("count")
    fig.suptitle("Probability integral transform — a flat histogram means the "
                 "whole predictive distribution is calibrated "
                 "(dashed line = uniform)", fontsize=10)
    p = HERE / "fig4_pit_calibration.png"
    fig.tight_layout(); fig.savefig(p, dpi=150); plt.close(fig)
    written.append(p.name)

    return written


# ==========================================================================
# Main
# ==========================================================================

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="short MCMC / fewer starts, for wiring checks only")
    ap.add_argument("--skip-permutation", action="store_true",
                    help="skip the non-circular lag-shift placebo arms")
    ap.add_argument("--workers", type=int, default=6,
                    help="parallel processes for the placebo arms")
    args = ap.parse_args()

    t_start = time.time()
    np.random.seed(SEED)

    # n_chains 2 -> 4 and n_burnin 10k -> 15k are part of the 2026-07-19
    # remediation: four overdispersed chains are the minimum that makes R-hat
    # and the cross-chain PIP spread informative rather than decorative.
    cfg = dict(n_starts=30, n_draws=40000, n_burnin=15000, thin=10,
               n_chains=4, n_pred_draws=500)
    if args.quick:
        cfg = dict(n_starts=8, n_draws=3000, n_burnin=1000, thin=5,
                   n_chains=4, n_pred_draws=150)

    results = {
        "experiment_id": "K1730",
        "title": "GEVReg-MIDAS-SSVS — interval forecasts of SPY realized "
                 "volatility from point-in-time monthly macro data",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "quick_mode": bool(args.quick),
        "config": cfg,
        "data_sources": {
            "spy": "yfinance SPY daily OHLC; Parkinson realized-variance proxy "
                   "(volpred.data.preprocessing.compute_realized_variance_proxy)",
            "macro_revised": "ALFRED first-release (output_type=4) PIT vintages: "
                             "CPIAUCSL, PAYEMS, INDPRO, UNRATE",
            "macro_market": "FRED VIXCLS, DGS10, DTB3 (not revised)",
        },
        "target": "log of max daily Parkinson RV within a calendar week "
                  "(non-overlapping weekly block maxima)",
        "midas_lags": 12,
        "taus": [float(t) for t in TAUS],
    }

    # ---------------- 1. numerical validation ---------------------------
    log("[1] Validating GEV implementation against scipy...")
    results["gev_numerical_validation"] = M.validate_against_scipy(seed=SEED)
    log(f"    max |logpdf - scipy| = "
        f"{results['gev_numerical_validation']['max_abs_logpdf_err']:.2e}")

    # ---------------- 2. data -------------------------------------------
    log("[2] Building point-in-time data...")
    daily_rv = D.load_spy_rv()
    weeks_all = D.build_weekly_blocks(daily_rv)
    macro = D.build_monthly_macro()
    tensor_all, stamp_all = D.build_midas_lag_tensor(weeks_all, macro)

    keep = np.isfinite(tensor_all).all(axis=(1, 2))
    weeks = weeks_all[keep].reset_index(drop=True)
    tensor, stamp = tensor_all[keep], stamp_all[keep]

    results["lookahead_checks"] = D.assert_no_lookahead(weeks, stamp)
    results["sample"] = {
        "n_weekly_blocks": int(len(weeks)),
        "first_block_start": str(weeks["block_start"].min().date()),
        "last_block_end": str(weeks["block_end"].max().date()),
        "n_daily_observations": int(len(daily_rv)),
        "macro_variables": D.MACRO_VARS,
        "macro_transforms": D.MACRO_TRANSFORMS,
        "median_macro_staleness_days": {
            v: float(np.median(
                (D._to_ns(weeks["origin"]) - stamp[:, j, 0]) / 86400e9))
            for j, v in enumerate(D.MACRO_VARS)
        },
    }

    # ---------------- 3. placebo arms (dispatched first, collected last) ---
    placebo_ex, placebo_futs, placebo_meta = None, None, None
    if not args.skip_permutation:
        log("[3] Non-circular lag-shift placebo (matched sample, leakage-free by "
            "construction)...")
        placebo_ex, placebo_futs, placebo_meta = placebo_submit(
            weeks, tensor, stamp, cfg, n_workers=args.workers)

    # ---------------- 4. main OOS run ------------------------------------
    log("[4] Rolling out-of-sample estimation...")
    run = run_oos(weeks, tensor, cfg, label="main")
    scored = score_all(weeks, run)
    scored["_refits"] = run["refits"]
    results["refits"] = run["refits"]
    results["oos"] = {k: v for k, v in scored.items() if not k.startswith("_")}

    pip_refits = [r for r in run["refits"] if "pip" in r.get("ssvs", {})]
    results["ssvs_summary"] = {
        "n_refits_with_ssvs": len(pip_refits),
        "mean_pip": {v: float(np.mean([r["ssvs"]["pip"][v] for r in pip_refits]))
                     for v in D.MACRO_VARS},
        "min_pip": {v: float(np.min([r["ssvs"]["pip"][v] for r in pip_refits]))
                    for v in D.MACRO_VARS},
        "max_pip": {v: float(np.max([r["ssvs"]["pip"][v] for r in pip_refits]))
                    for v in D.MACRO_VARS},
        "n_refits_pip_above_half": {
            v: int(np.sum([r["ssvs"]["pip"][v] > 0.5 for r in pip_refits]))
            for v in D.MACRO_VARS},
        "worst_rhat": float(np.max([r["ssvs"]["rhat_max"] for r in pip_refits])),
        "worst_geweke_abs_z": float(np.max([r["ssvs"]["geweke_max_abs_z"]
                                            for r in pip_refits])),
        "worst_geweke_abs_z_fixed_bandwidth": float(np.max(
            [r["ssvs"]["geweke_max_abs_z_fixed_bandwidth"] for r in pip_refits])),
        "min_ess": float(np.min([r["ssvs"]["ess_min"] for r in pip_refits])),
        "min_ess_delta": float(np.min([r["ssvs"]["ess_delta_min"]
                                       for r in pip_refits])),
        "max_pip_chain_spread": float(np.max([r["ssvs"]["pip_max_chain_spread"]
                                              for r in pip_refits])),
        "n_refits_meeting_convergence_gate": int(
            sum(bool(r["ssvs"]["converged"]) for r in pip_refits)),
        "convergence_gate": {"rhat_max_lt": 1.05, "ess_min_gte": 400,
                             "geweke_max_abs_z_lt": 2.0},
        # Set from the gate, not from prose. Every PIP-derived statement in the
        # README and the collection document is labelled from this field.
        "inference_tier": (
            "inference" if all(bool(r["ssvs"]["converged"]) for r in pip_refits)
            else "diagnostic_only"),
        "inference_tier_note":
            "The sampler does not meet the pre-registered convergence gate at "
            "every refit vintage, so the posterior inclusion probabilities and "
            "the posterior predictive describe what this fixed-seed sampler did, "
            "not a converged posterior. They are reported as diagnostics and no "
            "claim in this experiment rests on them.",
    }
    results["mle_convergence_summary"] = {
        # `feasible_start_rate` is the quantity the pre-remediation JSON reported
        # as `convergence_rate`, and it is a property of the random start
        # distribution, not of the likelihood surface. Keeping both under
        # unambiguous names is the point of the rename.
        "min_feasible_start_rate": float(np.min([r["gev"]["feasible_start_rate"]
                                                 for r in run["refits"]])),
        "mean_feasible_start_rate": float(np.mean([r["gev"]["feasible_start_rate"]
                                                   for r in run["refits"]])),
        "min_feasible_optimum_rate": float(np.min([r["gev"]["feasible_optimum_rate"]
                                                   for r in run["refits"]])),
        "mean_feasible_optimum_rate": float(np.mean([r["gev"]["feasible_optimum_rate"]
                                                     for r in run["refits"]])),
        "min_lbfgs_success_rate": float(np.min([r["gev"]["lbfgs_success_rate"]
                                                for r in run["refits"]])),
        "min_basin_concentration": float(np.min([r["gev"]["basin_concentration"]
                                                 for r in run["refits"]])),
        "mean_basin_concentration": float(np.mean([r["gev"]["basin_concentration"]
                                                   for r in run["refits"]])),
        "min_starts_at_best_basin": int(np.min([r["gev"]["n_at_best_basin"]
                                                for r in run["refits"]])),
        "max_nll_spread": float(np.max([r["gev"]["nll_spread"]
                                        for r in run["refits"]])),
        "all_hessians_positive_definite": bool(all(r["gev"]["hessian_pd"]
                                                   for r in run["refits"])),
        "max_hessian_condition": float(np.max([r["gev"]["hessian_cond"]
                                               for r in run["refits"]])),
        "max_nelder_mead_improvement": float(np.max([r["gev"]["nelder_mead_improvement"]
                                                     for r in run["refits"]])),
        "xi_range": [float(np.min([r["gev"]["xi"] for r in run["refits"]])),
                     float(np.max([r["gev"]["xi"] for r in run["refits"]]))],
    }

    # ---------------- 5. collect the placebo arms -------------------------
    if placebo_futs is not None:
        log("[5] Collecting placebo arms...")
        results["placebo_test"] = placebo_collect(
            placebo_ex, placebo_futs, placebo_meta, scored)

    # ---------------- 6. figures -----------------------------------------
    log("[6] Figures...")
    results["figures"] = make_figures(weeks, run, scored)

    # ---------------- 7. persist -----------------------------------------
    results["runtime_seconds"] = round(time.time() - t_start, 1)
    results["finished_utc"] = datetime.now(timezone.utc).isoformat()

    # results + reproduce_spec written together at run time — code_trace and
    # spec.entrypoint take their identity from one trace_file call (K1708 rule:
    # a spec must be born in the run that produced the results, never
    # back-filled; the previous hand-written spec in this suite pinned a stale
    # entrypoint sha, which is the exact drift class this closes).
    repo_src = HERE.parent.parent / "src"
    if str(repo_src) not in sys.path:
        sys.path.insert(0, str(repo_src))
    from volpred.research.reproduce_spec import finalize_experiment

    out, _ = finalize_experiment(
        results=json.loads(json.dumps(results, default=_json_default)),
        entrypoint=__file__,
        canonical_result="k1730_gevreg_midas_ssvs_results.json",
        exp_dir=HERE,
        inputs=sorted((HERE / "data").glob("*.csv")),
        outputs=["k1730_gevreg_midas_ssvs_results.json"],
        seeds=[("numpy", SEED)],
        runtime_seconds=results["runtime_seconds"],
    )
    log(f"[7] Wrote {Path(out).name} ({Path(out).stat().st_size / 1024:.0f} KB) "
        f"in {results['runtime_seconds']:.0f}s")

    _print_summary(results)
    return 0


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return [None if not np.isfinite(v) else float(v) for v in o.ravel()]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)
    return str(o)


def _print_summary(r: dict) -> None:
    print("\n" + "=" * 78)
    print("K1730 SUMMARY")
    print("=" * 78)
    oos = r["oos"]
    print(f"OOS: {oos['n_common_oos']} weekly blocks, {oos['oos_start']} → {oos['oos_end']}\n")
    print(f"{'model':<24} {'pinball':>9} {'cov90':>7} {'lo/hi out':>10} "
          f"{'VaR95':>7} {'VaR99':>7} {'PIT p':>8}")
    print("-" * 78)
    for m in MODELS:
        e = oos["by_model"][m]
        iv = e["intervals"]["0.90"]
        v95, v99 = e["var_levels"]["0.950"], e["var_levels"]["0.990"]
        print(f"{m:<24} {e['mean_pinball']:>9.5f} {iv['empirical_coverage']:>7.3f} "
              f"{iv['below_lower']:>4d}/{iv['above_upper']:<5d} "
              f"{v95['empirical_exceedance_rate']:>7.3f} "
              f"{v99['empirical_exceedance_rate']:>7.3f} "
              f"{e['pit']['chi2_p_value']:>8.2e}")
    print("  (expected: cov90=0.900, lo/hi out ~48/48, VaR95=0.050, VaR99=0.010)")
    print("\nDiebold-Mariano (GEVReg-MIDAS-SSVS vs benchmark, pinball loss):")
    for k, v in oos["dm_tests"].items():
        star = " *Harvey-sig*" if v.get("harvey_significant") else ""
        print(f"  {k:<46} t={v['t_stat']:+.2f}  p={v['p_value']:.4f}  "
              f"favours {v['favours']}{star}")
    if "placebo_test" in r:
        p = r["placebo_test"]
        print(f"\nNon-circular lag-shift placebo ({p['n_placebo_arms']} shifts, "
              f"{p['matched_sample_blocks']} matched blocks):")
        print(f"  real={p['mean_pinball_real_matched']:.5f}  "
              f"placebo=[{p['placebo_min']:.5f}, {p['placebo_max']:.5f}]  "
              f"median={p['placebo_median']:.5f}")
        print(f"  {p['n_placebo_at_least_as_good_as_real']}/{p['n_placebo_arms']} "
              f"placebo arms at least as good as real  →  one-sided p="
              f"{p['one_sided_p_value']:.3f} ({p['p_value_resolution_note']})")
    s = r.get("ssvs_summary", {})
    if s:
        print(f"\nSSVS sampler: worst R-hat={s['worst_rhat']:.3f}  "
              f"min ESS={s['min_ess']:.0f}  "
              f"worst |Geweke z|={s['worst_geweke_abs_z']:.2f}  →  "
              f"inference tier: {s['inference_tier'].upper()}")
    m = r.get("mle_convergence_summary", {})
    if m:
        print(f"GEV multistart: feasible starts "
              f"{m['mean_feasible_start_rate']:.2f}, feasible optima "
              f"{m['mean_feasible_optimum_rate']:.2f}, basin concentration "
              f"{m['mean_basin_concentration']:.2f} "
              f"(min {m['min_basin_concentration']:.2f})")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    sys.exit(main())
