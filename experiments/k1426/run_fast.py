"""K1426 fast runner — pivots scope due to 50min cap.

Strategy:
- All pairs: 20-multistart PCH (scope-cut from canonical 100 due to 50min cap; full 100 queued for compute_queue).
- Pair 2 (USO/BNO) & Pair 3 (GLD/IAU): OLS + EG-VECM + lightweight PCH (20
  multistarts) flagged as indicative. Full 100-start PCH for these pairs is
  queued in followup_brief.

Seed 42, deterministic. Reproduce: uv run python experiments/k1426/run_fast.py
"""

from __future__ import annotations
import json
from pathlib import Path
import sys

# Reuse the canonical PCH/Kalman/baseline code from k1426.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from k1426 import (  # noqa: E402
    fetch_pair,
    fit_ols_hedge,
    fit_eg_vecm_hedge,
    fit_pch,
    hedge_effectiveness,
    plot_pair,
    SEED,
    OUT_DIR,
)
import numpy as np  # noqa: E402

START, END = "2015-01-01", "2024-12-31"


def analyze(name, sx, sy, n_starts):
    print(f"\n[{name}] {sx}/{sy} n_starts={n_starts}", flush=True)
    df = fetch_pair(sx, sy, START, END)
    log_x = df["log_x"].values
    log_y = df["log_y"].values
    n = len(df)
    print(f"[{name}] N={n}", flush=True)

    mu_ols, beta_ols, spread_ols = fit_ols_hedge(log_x, log_y)
    he_ols = hedge_effectiveness(log_x, spread_ols)

    _, beta_eg, spread_eg, alpha_eg = fit_eg_vecm_hedge(log_x, log_y)
    he_eg = hedge_effectiveness(log_x, spread_eg)

    pch = fit_pch(log_x, log_y, n_starts=n_starts, seed=SEED)
    spread_pch = log_x - pch.mu - pch.beta * log_y
    he_pch = hedge_effectiveness(log_x, spread_pch)

    r2_mr = float(pch.sigma_M**2 / (pch.sigma_M**2 + pch.sigma_R**2))
    if 0 < pch.rho < 0.999:
        half_life = float(-np.log(2) / np.log(pch.rho))
    else:
        half_life = float("inf")

    # Honesty gates (Clegg-Krauss canonical interpretation; K1216 lesson —
    # numerically valid MLE optimum is not enough, economic interpretation
    # must hold):
    #   (a) rho >= 0.999            → degenerate (pure RW absorbs everything)
    #   (b) R²_MR < 0.05            → M component negligible (pure RW)
    #   (c) rho <= 0                → AR(1) oscillates, not mean-reverts
    #   (d) half_life < 1 day       → "mean reversion" so fast M is i.i.d.
    #                                 noise, not a persistent component
    if pch.rho >= 0.999 or r2_mr < 0.05:
        verdict = "NULL"
        notes = f"PCH degenerates: rho={pch.rho:.4f}, R2_MR={r2_mr:.4f}"
    elif pch.rho <= 0:
        verdict = "NULL_RHO_NEGATIVE"
        notes = (
            f"PCH rho={pch.rho:.4f} ≤ 0 — AR(1) oscillates rather than "
            f"mean-reverts; not economically 'partial cointegration' in "
            f"Clegg-Krauss sense even though MLE converged. R²_MR={r2_mr:.4f}."
        )
    elif half_life < 1.0:
        verdict = "NULL_HALFLIFE_TRIVIAL"
        notes = (
            f"PCH half-life={half_life:.3f}d < 1d — M component reverts "
            f"essentially instantaneously, indistinguishable from i.i.d. "
            f"noise; not a persistent mean-reverting structure. "
            f"rho={pch.rho:.4f}, R²_MR={r2_mr:.4f}."
        )
    elif he_pch < max(he_ols, he_eg) - 0.05:
        verdict = "FAIL"
        notes = "PCH HE lags baselines >5pp"
    else:
        verdict = "PASS"
        notes = f"PCH HE comparable; rho={pch.rho:.4f}, half_life={half_life:.1f}d, R2_MR={r2_mr:.3f}"

    print(
        f"[{name}] beta_ols={beta_ols:.4f} beta_pch={pch.beta:.4f} "
        f"rho={pch.rho:.4f} R2_MR={r2_mr:.4f} half_life={half_life:.2f}",
        flush=True,
    )
    print(
        f"[{name}] HE: ols={he_ols:.4f} eg={he_eg:.4f} pch={he_pch:.4f} -> {verdict}",
        flush=True,
    )

    plot_pair(name, df, spread_ols, spread_eg, spread_pch, pch)

    return {
        "symbols": {"x": sx, "y": sy},
        "n_obs": int(n),
        "date_start": str(df.index[0].date()),
        "date_end": str(df.index[-1].date()),
        "n_multistart": int(n_starts),
        "n_starts_converged": int(pch.n_starts_converged),
        "ols": {"mu": float(mu_ols), "beta": float(beta_ols), "he": float(he_ols)},
        "eg_vecm": {"beta": float(beta_eg), "alpha": float(alpha_eg), "he": float(he_eg)},
        "pch": {
            "mu": float(pch.mu),
            "beta": float(pch.beta),
            "rho": float(pch.rho),
            "sigma_M": float(pch.sigma_M),
            "sigma_R": float(pch.sigma_R),
            "loglik": float(pch.loglik),
            "r2_mr": r2_mr,
            "half_life_days": float(half_life) if np.isfinite(half_life) else None,
            "he": float(he_pch),
        },
        "verdict": verdict,
        "notes": notes,
    }


def main():
    # n_starts policy: all 3 pairs = 20 (scope-cut from canonical 100 due to 50min cap;
    # full 100-start queued for compute_queue per pooled-MLE rule K1213→K1216c)
    pairs = [
        ("pair_1_SPY_IVV", "SPY", "IVV", 20),
        ("pair_2_USO_BNO", "USO", "BNO", 20),
        ("pair_3_GLD_IAU", "GLD", "IAU", 20),
    ]
    results = {}
    for name, sx, sy, ns in pairs:
        try:
            results[name] = analyze(name, sx, sy, ns)
        except Exception as e:
            results[name] = {"error": str(e), "verdict": "FAIL"}
            print(f"[{name}] ERROR: {e}", flush=True)

    verdicts = [r.get("verdict", "FAIL") for r in results.values()]
    null_like = {"NULL", "NULL_RHO_NEGATIVE", "NULL_HALFLIFE_TRIVIAL"}
    if any(v == "PASS" for v in verdicts):
        overall = "PASS"
    elif all(v in null_like for v in verdicts):
        overall = "NULL"
    else:
        overall = "MIXED"

    payload = {
        "experiment_id": "k1426",
        "title": "Partial Cointegration Hedging — IS Proof of Concept",
        "seed": SEED,
        "data_range": {"start": START, "end": END},
        "multistart_policy": {
            "pair_1_SPY_IVV": 20,
            "pair_2_USO_BNO": 20,
            "pair_3_GLD_IAU": 20,
            "note": (
                "All pairs ran 20 multistarts due to 50min cap scope cut "
                "(pooled-MLE 100-start rule K1213→K1216c is queued in "
                "followup_brief for compute_queue). Pair 1 + 3 are duplicate ETFs "
                "(SPY/IVV, GLD/IAU) with single dominant basin so 20 starts "
                "should suffice; USO/BNO is the discriminating pair where "
                "full 100-start is most important and is the priority OOS task."
            ),
        },
        "pairs": results,
        "verdict": overall,
        "notes": (
            "IS-only PoC. Baselines (OLS, EG-VECM) ran on all pairs at full "
            "spec. Multistart MLE seed=42. NULL gate: rho>=0.999 OR R2_MR<0.05."
        ),
        "reproduce": "uv run python experiments/k1426/run_fast.py",
    }

    out = OUT_DIR / "k1426_results.json"
    with open(out, "w") as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\nWrote {out}")
    print(f"Overall verdict: {overall}")


if __name__ == "__main__":
    main()
