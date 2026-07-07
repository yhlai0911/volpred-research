"""
K1624 — VALIDATION HARNESS (reproducibility follow-up, added 2026-07-08).

Purpose
-------
The K1624 README (§4.5 / checklist item, line ~53 + 121) and results.json
`methodology.identification_rationale` both claim the identification pipeline was
"validated on simulated true-I(0.4) (no reject) and short-memory + level-shift
(strong reject)". That validation was originally only "reproduced in the agent
log" — the delivered `k1624_rv_long_memory_vs_level_shifts.py` contains only
`simulate_fracint` (used to build the bootstrap null); it has NO standalone
harness that runs the two ground-truth DGPs through the identical identification
pipeline and reports a misjudgment rate. The 24h Codex review (mile_c538af9e,
CONDITIONAL_PASS) flagged this as reproducibility residual concern #1.

This harness closes that gap. It does NOT change any published result — the K1624
identification verdicts on real data stand as-is. It is a pure, re-runnable
Monte-Carlo confirmation that the pipeline (`bootstrap_identification`) has the
claimed error properties:

  DGP A — TRUE long memory, I(0.4)  (ARFIMA(0,0.4,0), `simulate_fracint`)
          Correct verdict = "true long memory" (n_significant_of_3 == 0).
          A "spurious" verdict here is a FALSE POSITIVE (false reject of true LM).

  DGP B — SPURIOUS: short-memory AR(0.3) + occasional mean/level shifts.
          Correct verdict = "spurious (level-shift-induced)" (n_sig >= 2).
          A "true long memory" verdict here is a FALSE NEGATIVE (missed the shifts).

We run N independent replications of each DGP through the *identical* pipeline
used on real data (Local-Whittle d_pre at T^0.6 -> `bootstrap_identification`),
tally the verdict distribution, and print/dump a MISJUDGMENT-RATE table.

Design notes
------------
- The pipeline functions are IMPORTED from the sibling experiment module (DRY);
  we do not re-implement GPH/LW/PELT/Shimotsu/bootstrap here. This guarantees the
  harness validates the *exact* code path used on real data.
- All randomness is seeded. Each replication `r` uses outer seed `BASE + r*STRIDE`;
  STRIDE (=100000) >> inner bootstrap fan-out (`seed + 1 + b`, b<B) so replication
  null draws never collide.
- `--smoke` runs a small/fast config for CI + quick reproduction; `--full` runs a
  statistically meaningful config (heavier — enqueue to compute_queue if needed).
- The AR(0.3)+level-shift DGP parameters are documented and CLI-tunable. Defaults
  mirror the qualitative construction in Granger & Hyung (2004): a low-order
  short-memory process whose unconditional mean jumps occasionally, so its ACF
  decays slowly and inflates d_hat, yet contains NO fractional integration.

Author: VolPred autonomous research agent (K1624 reproducibility follow-up).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent

# --- import the EXACT pipeline used on real data (DRY; validate the real code path) ---
sys.path.insert(0, str(HERE))
from k1624_rv_long_memory_vs_level_shifts import (  # noqa: E402
    simulate_fracint,
    local_whittle,
    bootstrap_identification,
)

SEED_BASE = 20260708
SEED_STRIDE = 100000  # >> inner bootstrap fan-out (seed+1+b, b<B) -> no cross-rep collision

# verdict strings emitted by bootstrap_identification (must match the sibling module)
V_TRUE = "true long memory"
V_SPURIOUS = "spurious (level-shift-induced)"
V_MIXED = "mixed"


# ------------------------------------------------------------------ DGPs


def dgp_true_lm(n: int, seed: int, d: float = 0.4) -> np.ndarray:
    """DGP A: a genuine stationary I(d) path (ARFIMA(0,d,0)).

    Reuses the SAME `simulate_fracint` the production bootstrap uses for its null,
    so 'true LM' here is exactly the null the pipeline calibrates against. The
    pipeline must NOT flag this as spurious.
    """
    return simulate_fracint(d, n, seed)


def dgp_ar_level_shift(
    n: int,
    seed: int,
    phi: float = 0.3,
    n_shifts: int = 8,
    shift_sd: float = 1.5,
    min_seg: int = 200,
) -> np.ndarray:
    """DGP B: SHORT-memory AR(1, phi) contaminated by occasional mean/level shifts.

    x_t = mu_t + u_t,  u_t = phi*u_{t-1} + eps_t  (eps ~ N(0,1)),
    mu_t piecewise-constant with `n_shifts` change-points; each segment level is a
    random-walk increment (N(0, shift_sd)) from the previous, i.e. occasional jumps
    in the unconditional mean. This is short-memory (no fractional integration) but
    its slowly-decaying ACF inflates d_hat -> the classic 'spurious long memory'
    (Granger & Hyung 2004). The pipeline must flag this as spurious.
    """
    # Guard (code-review note, 2026-07-08): below 2*min_seg the change-point window
    # collapses and DGP B silently degenerates to pure AR(1) (no shifts) — which is
    # NOT the intended 'short memory + occasional shifts' ground truth. Fail loud so a
    # careless --n override cannot quietly validate against the wrong DGP. The
    # documented --smoke/--full configs (n=2000/4000) are far above this floor.
    if n < 2 * min_seg + 1:
        raise ValueError(
            f"dgp_ar_level_shift: n={n} too small for min_seg={min_seg}; need n >= {2*min_seg+1} "
            f"so at least one level shift can be placed (else DGP B degenerates to pure AR(1))."
        )
    rng = np.random.default_rng(seed)
    # short-memory AR(1) component
    eps = rng.standard_normal(n)
    u = np.empty(n)
    u[0] = eps[0]
    for t in range(1, n):
        u[t] = phi * u[t - 1] + eps[t]
    # occasional level shifts with a minimum segment length.
    # NOTE: change-points are drawn without an explicit minimum-SPACING constraint, so
    # two shifts can occasionally land close together (a double jump). This does not
    # change DGP B's qualitative character (short memory + occasional shifts) and PELT's
    # own min_size absorbs close pairs; add spacing-aware sampling if this harness is
    # later reused for fine-grained shift-count sensitivity.
    lo, hi = min_seg, n - min_seg
    if hi <= lo:
        cps = np.array([], dtype=int)
    else:
        k = min(n_shifts, max(0, (hi - lo) // min_seg))
        cps = np.sort(rng.choice(np.arange(lo, hi), size=k, replace=False)) if k > 0 else np.array([], dtype=int)
    bounds = [0, *cps.tolist(), n]
    mu = np.empty(n)
    level = 0.0
    for a, b in zip(bounds[:-1], bounds[1:]):
        mu[a:b] = level
        level += rng.normal(0.0, shift_sd)
    return mu + u


# ------------------------------------------------------------------ pipeline call


def pipeline_verdict(y: np.ndarray, B: int, seed: int) -> dict:
    """Run the IDENTICAL identification pipeline used on real data.

    d_pre from Local Whittle at bandwidth m=T^0.6 (matches main() on real data),
    then the true-LM parametric-bootstrap identification. Returns verdict, the
    per-statistic bootstrap p-values (spurious direction), and n_significant_of_3.
    """
    y = np.asarray(y, float)
    T = len(y)
    m_lw = max(16, int(T ** 0.6))
    d_pre = local_whittle(y, m_lw)[0]
    d_pre = float(np.clip(d_pre, -0.49, 0.99))
    boot = bootstrap_identification(y, d_pre, B=B, seed=seed)
    return {
        "d_pre": d_pre,
        "d_post_obs": float(boot["observed"]["d_post"]),
        "n_breaks_obs": int(boot["observed"]["n_breaks"]),
        "boot_p": boot["boot_p_spurious_direction"],
        "n_sig_of_3": int(boot["n_significant_of_3"]),
        "verdict": boot["verdict"],
    }


def run_dgp(name: str, gen, n: int, N: int, B: int, correct_verdict: str, misjudge_verdicts) -> dict:
    """Run N replications of one DGP through the pipeline; tally verdicts + p-values."""
    verdicts = []
    n_sig = []
    p_dpost, p_w4, p_gap = [], [], []
    d_pre_list, d_post_list = [], []
    per_rep = []
    for r in range(N):
        seed = SEED_BASE + r * SEED_STRIDE
        y = gen(n, seed)
        res = pipeline_verdict(y, B=B, seed=seed + 1)  # +1: distinct from DGP gen seed
        verdicts.append(res["verdict"])
        n_sig.append(res["n_sig_of_3"])
        p_dpost.append(res["boot_p"]["d_post"])
        p_w4.append(res["boot_p"]["W4"])
        p_gap.append(res["boot_p"]["dfull_minus_dbar"])
        d_pre_list.append(res["d_pre"])
        d_post_list.append(res["d_post_obs"])
        per_rep.append({"rep": r, "verdict": res["verdict"], "n_sig": res["n_sig_of_3"],
                        "d_pre": round(res["d_pre"], 3), "d_post": round(res["d_post_obs"], 3),
                        "p_dpost": round(res["boot_p"]["d_post"], 3),
                        "p_W4": round(res["boot_p"]["W4"], 3),
                        "p_gap": round(res["boot_p"]["dfull_minus_dbar"], 3)})
        print(f"  [{name}] rep {r+1}/{N}: verdict={res['verdict']:<28} "
              f"n_sig={res['n_sig_of_3']} d_pre={res['d_pre']:.3f} d_post={res['d_post_obs']:.3f} "
              f"p[dpost={res['boot_p']['d_post']:.3f},W4={res['boot_p']['W4']:.3f},"
              f"gap={res['boot_p']['dfull_minus_dbar']:.3f}]", file=sys.stderr)

    from collections import Counter
    vc = dict(Counter(verdicts))
    n_misjudge = sum(1 for v in verdicts if v in misjudge_verdicts)
    return {
        "dgp": name,
        "N": N,
        "B": B,
        "n": n,
        "correct_verdict": correct_verdict,
        "misjudge_verdicts": list(misjudge_verdicts),
        "verdict_counts": vc,
        "correct_rate": float(np.mean([v == correct_verdict for v in verdicts])),
        "misjudgment_rate": float(n_misjudge / N),
        "n_sig_of_3": {"mean": float(np.mean(n_sig)), "min": int(np.min(n_sig)), "max": int(np.max(n_sig))},
        "boot_p_mean": {"d_post": float(np.mean(p_dpost)), "W4": float(np.mean(p_w4)),
                        "dfull_minus_dbar": float(np.mean(p_gap))},
        "boot_p_median": {"d_post": float(np.median(p_dpost)), "W4": float(np.median(p_w4)),
                          "dfull_minus_dbar": float(np.median(p_gap))},
        "d_pre": {"mean": float(np.mean(d_pre_list)), "min": float(np.min(d_pre_list)),
                  "max": float(np.max(d_pre_list))},
        "d_post": {"mean": float(np.mean(d_post_list)), "min": float(np.min(d_post_list)),
                   "max": float(np.max(d_post_list))},
        "per_rep": per_rep,
    }


# ------------------------------------------------------------------ main


def main():
    ap = argparse.ArgumentParser(description="K1624 identification-pipeline validation harness")
    ap.add_argument("--smoke", action="store_true",
                    help="fast config (N=6, B=60, n=2000) for CI / quick reproduction")
    ap.add_argument("--full", action="store_true",
                    help="statistically meaningful config (N=40, B=200, n=4000) — heavy")
    ap.add_argument("--N", type=int, default=None, help="replications per DGP (override)")
    ap.add_argument("--B", type=int, default=None, help="inner bootstrap draws (override)")
    ap.add_argument("--n", type=int, default=None, help="series length (override)")
    ap.add_argument("--d-true", type=float, default=0.4, help="true fractional-integration order for DGP A")
    args = ap.parse_args()

    if args.full:
        N, B, n = 40, 200, 4000
        config = "full"
    else:  # smoke default
        N, B, n = 6, 60, 2000
        config = "smoke"
    if args.N is not None:
        N = args.N
    if args.B is not None:
        B = args.B
    if args.n is not None:
        n = args.n
    if args.N is not None or args.B is not None or args.n is not None:
        config = "custom"

    t0 = time.time()
    print(f"[K1624-validation] config={config}  N={N} B={B} n={n} d_true={args.d_true}", file=sys.stderr)

    res_true = run_dgp(
        "true_I(d)", lambda nn, sd: dgp_true_lm(nn, sd, d=args.d_true),
        n=n, N=N, B=B, correct_verdict=V_TRUE,
        misjudge_verdicts={V_SPURIOUS},  # false reject of true LM
    )
    res_spur = run_dgp(
        "AR(0.3)+level_shift", dgp_ar_level_shift,
        n=n, N=N, B=B, correct_verdict=V_SPURIOUS,
        misjudge_verdicts={V_TRUE},  # missed the shifts
    )

    elapsed = time.time() - t0
    out = {
        "experiment_id": "k1624_rv_long_memory_vs_level_shifts",
        "artifact": "k1624_validation.py",
        "purpose": "reproducibility harness for the identification pipeline's claimed error properties "
                   "(README §4.5 / checklist; results.json methodology.identification_rationale)",
        "does_not_change_published_results": True,
        "seed_base": SEED_BASE,
        "seed_stride": SEED_STRIDE,
        "config": config,
        "params": {"N_per_dgp": N, "B_inner_bootstrap": B, "n_series_len": n, "d_true": args.d_true},
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(elapsed, 1),
        "results": {"true_lm": res_true, "spurious_ar_level_shift": res_spur},
        "claim_reproduced": {
            "true_I(0.4)_no_false_reject": res_true["misjudgment_rate"] == 0.0,
            "true_I(0.4)_misjudgment_rate": res_true["misjudgment_rate"],
            "ar_level_shift_correct_reject": res_spur["misjudgment_rate"] == 0.0,
            "ar_level_shift_misjudgment_rate": res_spur["misjudgment_rate"],
        },
    }

    outpath = HERE / f"k1624_validation_results_{config}.json"
    with open(outpath, "w") as f:
        json.dump(out, f, indent=2, default=str)

    # ---- misjudgment-rate table (stdout) ----
    print("\n=== K1624 IDENTIFICATION-PIPELINE VALIDATION (misjudgment rates) ===")
    print(f"config={config}  N={N}/DGP  B={B}  n={n}  elapsed={elapsed:.1f}s\n")
    hdr = f"{'DGP':<24}{'correct verdict':<30}{'correct%':>9}{'misjudge%':>11}{'mean n_sig':>12}"
    print(hdr)
    print("-" * len(hdr))
    for r in (res_true, res_spur):
        print(f"{r['dgp']:<24}{r['correct_verdict']:<30}"
              f"{100*r['correct_rate']:>8.1f}%{100*r['misjudgment_rate']:>10.1f}%"
              f"{r['n_sig_of_3']['mean']:>12.2f}")
    print("\nmean bootstrap p (spurious direction):")
    for r in (res_true, res_spur):
        bp = r["boot_p_mean"]
        print(f"  {r['dgp']:<24} d_post={bp['d_post']:.3f}  W4={bp['W4']:.3f}  gap={bp['dfull_minus_dbar']:.3f}")
    print(f"\n[done] wrote {outpath}")
    print(json.dumps(out["claim_reproduced"], indent=2))


if __name__ == "__main__":
    main()
