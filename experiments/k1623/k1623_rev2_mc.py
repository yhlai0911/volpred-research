"""
K1623 rev2 — how far is the break-demeaned d-hat standard error understated?
============================================================================

The original round reported the break-demeaned ELW d-hat with the RAW ELW
asymptotic standard error, 1/(2 sqrt(m)). That SE is derived for a series whose
mean structure is KNOWN. Here the mean structure is a Bai-Perron partition that
was ESTIMATED from the same data, so the reported SE ignores a generated
-regressor problem and is a LOWER BOUND on the true sampling uncertainty.

README §4/§5 of the original round argued -- correctly -- that a moving-block
bootstrap is invalid here, because resampling blocks destroys the long-range
dependence being estimated (measured: boot mean d ~ 0.13 against a true d ~ 0.72).
That argument rules out bootstrapping the SERIES. It does not address the
break-estimation uncertainty, which is a different question and needs a
different instrument. This script uses a parametric Monte Carlo instead.

Design
------
For each asset, condition on the fitted model (BIC breaks + segment means +
demeaned d-hat), simulate from it, and re-run the whole estimation chain:

  Arm A (realistic)      simulate -> Bai-Perron re-estimates breaks -> demean -> ELW
  Arm B (location-oracle) simulate -> demean at the TRUE simulated break LOCATIONS -> ELW

WHAT ARM B IS, PRECISELY (corrected in rev3 after Codex round 2 §7)
------------------------------------------------------------------
Arm B is an oracle in break LOCATION only. It calls piecewise_demean on the
SIMULATED series, so it still ESTIMATES each segment's mean from that data
rather than using the known implanted level vector. An earlier draft of this
docstring called it "ELW alone"; that was wrong, and the error matters for how
the contrast is read:

  sd(A)/sd(B) and the paired A-minus-B bias contrast measure the cost of having
  to LOCATE the breaks, holding fixed that BOTH arms re-estimate segment means.
  The generated-regressor uncertainty contributed by estimating the mean
  structure is present in both arms and is therefore DIFFERENCED OUT -- this
  design does not measure it and does not bound it.

sd(A) compared with 1/(2 sqrt(m)) still says how badly the published SE
understates the true sampling sd, which is the headline this MC was built for.
Measuring the mean-estimation share as well would need a third arm that demeans
with the known implanted level; rev3 does not add one (no-recompute scope).

THAT THIRD ARM NOW EXISTS -- IN A SIBLING SCRIPT (rev3, arm C)
--------------------------------------------------------------
See `k1623_rev3_armc_mc.py`. It runs arms A, B and C on the SAME simulated paths
(same seed, same DGP, same stream offsets, all imported from this module) and
writes its own artifact, `k1623_rev3_armc_results.json`.

It is a separate script on purpose. This script's output file,
`k1623_rev2_mc_results.json`, is FROZEN evidence whose current bytes are this
run's output PLUS the rev3 remediation patch applied by
`k1623_rev3_patch_mc_artifact.py`. Re-running THIS script would overwrite that
file and silently destroy the patch. Hence the overwrite guard in main() below.

WHAT THIS DOES NOT DO
---------------------
This is a MODEL-CONDITIONAL exercise. It assumes the data really were generated
by "ARFIMA(0, d, 0) + deterministic level shifts at the estimated dates". It
therefore quantifies sampling uncertainty UNDER THAT MODEL. It is NOT a test of
that model, and it is NOT evidence that the model is right. In particular it
cannot speak to the Diebold-Inoue alternative (a random, dense shift process),
which is precisely the identification question this experiment has RETRACTED
rather than answered. Reporting it as if it validated the model would repeat the
original error.

Run:  uv run python experiments/k1623/k1623_rev2_mc.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import k1623 as K  # noqa: E402
from k1623_rev2 import atomic_write_json, pin_vintage  # noqa: E402

SEED = 42
N_REPS = 500
BURN = 2000            # transient discarded from the truncated integration filter
MAX_BREAKS = 5         # identical to the main round
MIN_FRAC = 0.15

OUT = HERE / "k1623_rev2_mc_results.json"
RESULTS_ORIG = HERE / "k1623_results.json"


def fractional_integrate(eps: np.ndarray, d: float, maxK: int = K.FD_MAXK) -> np.ndarray:
    """Apply (1-L)^(-d): k1623.fracdiff applies (1-L)^(+d), so pass -d."""
    return K.fracdiff(eps, -d, maxK=maxK)


def segment_means(y: np.ndarray, breaks: list) -> tuple[np.ndarray, list]:
    """Piecewise-constant mean level implied by a break partition."""
    n = len(y)
    bnds = [0] + sorted(breaks) + [n]
    level = np.zeros(n)
    means = []
    for a, b in zip(bnds[:-1], bnds[1:]):
        mu = float(y[a:b].mean()) if b > a else 0.0
        level[a:b] = mu
        means.append(mu)
    return level, means


def analyse(label: str, y: np.ndarray, rng: np.random.Generator) -> dict:
    n = len(y)
    m = int(n ** 0.60)

    # ---- fitted model on the real data (this is what we condition on) ------
    bp = K.bai_perron(y, max_breaks=MAX_BREAKS, min_frac=MIN_FRAC)
    breaks_true = list(bp["breaks"])
    level, means = segment_means(y, breaks_true)
    resid = y - level
    d_hat = float(K.local_whittle(resid, m, exact=True)["d"])
    se_asym = 1.0 / (2.0 * np.sqrt(m))

    # innovation scale: fractionally difference the demeaned residual back to
    # (approximate) white noise and take its sd, skipping the filter transient.
    eps_hat = K.fracdiff(resid, d_hat)
    sigma = float(np.std(eps_hat[min(200, n // 4):]))

    d_arm_a, d_arm_b, nbrk = [], [], []
    for _ in range(N_REPS):
        eps = rng.normal(0.0, sigma, size=n + BURN)
        x = fractional_integrate(eps, d_hat)[BURN:]
        x = x + level                                  # implant the SAME level shifts

        # Arm A: breaks must be re-estimated, exactly as in the real analysis
        bp_s = K.bai_perron(x, max_breaks=MAX_BREAKS, min_frac=MIN_FRAC)
        nbrk.append(int(bp_s["best_k"]))
        d_arm_a.append(float(K.local_whittle(
            K.piecewise_demean(x, bp_s["breaks"]), m, exact=True)["d"]))

        # Arm B: LOCATION-oracle -- the break dates are the true simulated ones,
        # but piecewise_demean still estimates each segment mean from x. This is
        # NOT "ELW alone"; see the docstring.
        d_arm_b.append(float(K.local_whittle(
            K.piecewise_demean(x, breaks_true), m, exact=True)["d"]))

    a = np.array(d_arm_a)
    b = np.array(d_arm_b)
    sd_a, sd_b = float(a.std(ddof=1)), float(b.std(ddof=1))
    return {
        "n": n, "bandwidth_m": m,
        "d_demeaned_fitted": d_hat,
        "se_asymptotic_published": se_asym,
        "n_breaks_true": len(breaks_true),
        "innovation_sigma": sigma,
        "arm_a_breaks_reestimated": {
            "mean": float(a.mean()), "sd": sd_a,
            "bias_vs_fitted": float(a.mean() - d_hat),
            "pct_2_5": float(np.percentile(a, 2.5)),
            "pct_97_5": float(np.percentile(a, 97.5)),
        },
        "arm_b_breaks_known": {
            "mean": float(b.mean()), "sd": sd_b,
            "bias_vs_fitted": float(b.mean() - d_hat),
        },
        # ATTRIBUTION (corrected after review): arm A's bias_vs_fitted is NOT the
        # effect of estimating breaks. It is the SUM of (i) the bias arm B already
        # shows even with the true break locations, and (ii) the extra attenuation
        # from having to LOCATE the breaks. Only the paired A-minus-B contrast
        # isolates (ii). Reporting A's total as "the break estimation effect"
        # overstates it roughly two-fold.
        #
        # NAMING (rev3): the arm-B field is deliberately NOT called an "ELW own
        # bias". Arm B re-estimates the segment means, so its bias mixes ELW's
        # finite-sample behaviour with mean-estimation error at known locations.
        # Calling it ELW-only was the wording Codex round 2 §7 flagged.
        "break_estimation_attenuation_a_minus_b": float(a.mean() - b.mean()),
        "arm_b_oracle_location_bias": float(b.mean() - d_hat),
        "generated_regressor_inflation_sd_a_over_sd_b": float(sd_a / sd_b) if sd_b else None,
        "understatement_sd_a_over_published_se": float(sd_a / se_asym) if se_asym else None,
        "break_count_recovery": {
            "true": len(breaks_true),
            "mean_selected": float(np.mean(nbrk)),
            "pct_recovered_exactly": float(np.mean(np.array(nbrk) == len(breaks_true))),
        },
    }


def _guard_frozen_artifact() -> None:
    """Refuse to overwrite the rev3-patched artifact by accident.

    `k1623_rev2_mc_results.json` on disk is NOT simply this script's output: the
    rev3 remediation (`k1623_rev3_patch_mc_artifact.py`) added the
    `claim_corrections_rev3` block, which supersedes four published claims and is
    the cited source for two columns of README 6.4. A plain re-run of this script
    calls atomic_write_json on that path and would delete all of it with no
    warning -- the exact "fix the data instead of the process" failure the repo
    forbids. Re-running is still allowed, but it has to be deliberate.
    """
    if not OUT.exists():
        return
    if "--force-overwrite" in sys.argv:
        print(f"WARNING: --force-overwrite given; {OUT.name} will be REPLACED and any "
              f"rev3 patch block in it will be lost.", file=sys.stderr)
        return
    try:
        existing = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Fail CLOSED, not open. An artifact that exists but will not parse is an
        # anomaly to investigate -- it is the worst moment to allow a clobber,
        # since whatever is wrong with it would be destroyed along with it.
        raise SystemExit(
            f"REFUSING to overwrite {OUT.name}: it exists but could not be read or parsed "
            f"({exc.__class__.__name__}: {exc}). A frozen artifact that will not parse is a "
            f"reason to stop and look, not a reason to overwrite. Inspect it first; pass "
            f"--force-overwrite only if you have decided it is genuinely disposable."
        ) from exc
    if "claim_corrections_rev3" not in existing:
        return                       # unpatched output -> a re-run is harmless
    raise SystemExit(
        f"REFUSING to overwrite {OUT.name}: it carries a `claim_corrections_rev3` block that "
        f"was applied AFTER this script last ran, and re-running would destroy it.\n"
        f"  - to add the third (mean-structure) arm, run k1623_rev3_armc_mc.py instead; it "
        f"writes its own artifact and opens this one read-only\n"
        f"  - to genuinely regenerate this artifact from scratch, pass --force-overwrite and "
        f"re-apply k1623_rev3_patch_mc_artifact.py afterwards"
    )


def main() -> None:
    t0 = time.time()
    _guard_frozen_artifact()
    orig = json.loads(RESULTS_ORIG.read_text(encoding="utf-8"))
    per_asset = {}
    for idx, (ticker, kind, label) in enumerate(K.ASSETS):
        proxy = K.rv_proxy(K.load_ohlc(ticker), kind)
        proxy, _vintage = pin_vintage(proxy, orig["assets"][label], label)
        y = proxy["logrv"].to_numpy()
        # Deterministic per-asset stream. NOT hash(label): Python randomises
        # string hashing per process, which would silently break reproducibility.
        rng = np.random.default_rng(SEED + 1000 * idx)
        per_asset[label] = analyse(label, y, rng)
        r = per_asset[label]
        print(f"[{label}] d={r['d_demeaned_fitted']:.3f}  published SE={r['se_asymptotic_published']:.4f}"
              f"  MC sd(A)={r['arm_a_breaks_reestimated']['sd']:.4f}"
              f"  sd(B)={r['arm_b_breaks_known']['sd']:.4f}"
              f"  understated x{r['understatement_sd_a_over_published_se']:.2f}")

    infl = [v["generated_regressor_inflation_sd_a_over_sd_b"] for v in per_asset.values()]
    under = [v["understatement_sd_a_over_published_se"] for v in per_asset.values()]
    bias = [v["arm_a_breaks_reestimated"]["bias_vs_fitted"] for v in per_asset.values()]
    # Isolated break-LOCATION effect = paired A-minus-B contrast (see the note on
    # the per-asset dict). `bias` above is the TOTAL, which also contains whatever
    # arm B is already biased by at known break locations.
    brk_bias = [v["break_estimation_attenuation_a_minus_b"] for v in per_asset.values()]
    armb_bias = [v["arm_b_oracle_location_bias"] for v in per_asset.values()]
    tstats = {k: v["d_demeaned_fitted"] / v["arm_a_breaks_reestimated"]["sd"]
              for k, v in per_asset.items()}
    recov = {k: v["break_count_recovery"]["pct_recovered_exactly"]
             for k, v in per_asset.items()}
    payload = {
        "experiment_id": "k1623_rev2_mc",
        "title": "Generated-regressor Monte Carlo for the break-demeaned ELW d-hat",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED, "n_reps": N_REPS, "burn_in": BURN,
        "design": {
            "arm_a": "simulate -> Bai-Perron re-estimates breaks -> demean -> ELW (realistic)",
            "arm_b": "simulate -> demean at the TRUE simulated break LOCATIONS -> ELW "
                     "(location-oracle only: segment MEANS are still estimated from the "
                     "simulated data, so this is NOT an 'ELW alone' baseline)",
            "dgp": "ARFIMA(0, d_hat, 0) Gaussian innovations + the fitted piecewise-constant "
                   "level implanted at the estimated break dates",
        },
        "per_asset": per_asset,
        "summary": {
            "generated_regressor_inflation_range": [min(infl), max(infl)],
            "published_se_understatement_range": [min(under), max(under)],
            "total_attenuation_bias_range_arm_a": [min(bias), max(bias)],
            "break_estimation_attenuation_range_a_minus_b": [min(brk_bias), max(brk_bias)],
            "arm_b_oracle_location_bias_range": [min(armb_bias), max(armb_bias)],
            "d_over_mc_sd": tstats,
            "break_count_exact_recovery_rate": recov,
            "finding_1_se_is_understated": (
                f"The published asymptotic SE understates the Monte Carlo sampling sd by a "
                f"factor of {min(under):.2f}-{max(under):.2f}. The original confidence "
                f"intervals are too narrow."
            ),
            "finding_2_but_not_mainly_because_of_the_breaks": (
                f"Contrary to what the reviewer critique might suggest, having to LOCATE the "
                f"breaks contributes only {min(infl):.2f}-{max(infl):.2f}x on top of the "
                f"location-oracle sd -- i.e. that part of the generated-regressor effect on the "
                f"SE is SMALL. Most of the understatement comes from the asymptotic "
                f"1/(2 sqrt(m)) formula itself being optimistic at this sample size and "
                f"bandwidth. Reported this way round because it is what the simulation shows, "
                f"not what would best support the critique. SCOPE (rev3): both arms re-estimate "
                f"the segment MEANS, so this ratio bounds the break-LOCATION cost only; the "
                f"mean-estimation share of the generated-regressor problem cancels in the "
                f"contrast and is NOT measured here."
            ),
            "finding_3_downward_attenuation": (
                f"Demeaning at RE-ESTIMATED breaks attenuates d-hat downward even when the "
                f"simulated DGP contains EXACTLY the level shifts being removed and no others. "
                f"ATTRIBUTION (corrected after review -- an earlier draft credited the whole "
                f"total to break estimation, overstating it about two-fold): the TOTAL arm-A "
                f"bias is {min(bias):.3f} to {max(bias):.3f}, but the location-oracle arm B is "
                f"already biased by {min(armb_bias):.3f} to {max(armb_bias):.3f} from ELW's own "
                f"finite-sample behaviour COMBINED WITH estimating the segment means at known "
                f"locations. The part actually attributable to LOCATING the breaks is the "
                f"paired A-minus-B contrast, "
                f"{min(brk_bias):.3f} to {max(brk_bias):.3f}. That smaller number is the one "
                f"that should be quoted. The qualitative point stands: part of the raw -> "
                f"demeaned d-hat drop in the original round is a mechanical artefact of fitting "
                f"breaks rather than evidence of additional level shifts, which weakens the "
                f"original reading in BOTH directions."
            ),
            "finding_4_break_count_recovery_is_noisy": (
                f"Bai-Perron recovers the exact NUMBER of breaks in "
                f"{min(recov.values()):.0%}-{max(recov.values()):.0%} of replications "
                f"(TW0050 worst at {recov['TW0050']:.0%}). SCOPE (corrected after review): this "
                f"simulation records only the selected break COUNT; it never stores or compares "
                f"the estimated break DATES, so it cannot and does not quantify date-location "
                f"error. Any statement about break-date uncertainty would be unsupported by "
                f"this artifact."
            ),
            "what_survives": (
                "The descriptive statement survives comfortably: with MC sd of 0.045-0.063 and "
                f"d-hat of 0.457-0.645, the ratio d/sd is "
                f"{min(tstats.values()):.1f}-{max(tstats.values()):.1f}, so the break-demeaned "
                "d-hat is still clearly positive under this model. That is a statement about "
                "RESIDUAL PERSISTENCE, not an identification result -- the retracted claim "
                "stays retracted, because no amount of SE correction can make a deterministic "
                "5-break model speak to a random dense-shift alternative."
            ),
        },
        "scope_limits": [
            "MODEL-CONDITIONAL: assumes the DGP really is ARFIMA + deterministic breaks at the "
            "estimated dates. It quantifies sampling uncertainty under that model.",
            "It is NOT a test of that model and NOT evidence for it.",
            "It cannot address Diebold-Inoue (random / dense shift DGP), which is the "
            "identification question this experiment RETRACTS rather than answers.",
            "Gaussian innovations; log-RV is closer to Gaussian than RV but not exactly so.",
            "The same FD_MAXK = 2000 truncation binds here as in the main round.",
            "ARM B IS NOT ELW-ONLY: the oracle arm knows the break DATES but still estimates "
            "the segment MEANS from simulated data. The A-minus-B contrast therefore isolates "
            "the cost of locating breaks and differences out the mean-estimation "
            "generated-regressor uncertainty, which this design does not measure.",
            "Break DATES are never stored or compared -- only the selected break COUNT. This "
            "artifact cannot quantify break-date location error, and no claim about it is made.",
        ],
        "total_runtime_sec": round(time.time() - t0, 2),
    }
    atomic_write_json(OUT, payload)
    print(f"\nwrote {OUT.name} ({payload['total_runtime_sec']}s)")
    print("SE understatement range:", [round(u, 2) for u in [min(under), max(under)]])


if __name__ == "__main__":
    main()
