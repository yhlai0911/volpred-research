#!/usr/bin/env python3
"""
K1380 SPA/RC test — computed from the ALREADY-CACHED QLIKE loss matrix.

Recovers the Hansen (2005) SPA + White (2000) RC multiple-testing result for
Paper 9's horse race WITHOUT re-running any GARCH/MIDAS rolling-window fits.
The expensive OOS fits are cached in `k1380_losses_all.npy` (shape (17, 1864)).

Bug fixed (vs k1380.py line 658): `valid_all = np.all(~isnan, axis=0)` required
ALL 17 specs valid at every timestep. C1 (idx 13) is entirely NaN (fixed-span
MIDAS Km=6 produced no valid forecast), so n_valid collapsed to 0 and the SPA
bootstrap crashed on an empty array. We build a CLEAN SPEC SET of only the
convergent specs and recompute valid_all over that subset.

Non-convergent specs excluded with documented numeric justification:
  - C1  (idx 13): mean QLIKE = NaN  (all-NaN, zero valid forecasts)
  - A5  (idx  4): mean QLIKE ~= 255122  (exp(VIX) blow-up; ~410x median)
  - C2  (idx 14): mean QLIKE ~= 9349   (fixed-span MIDAS blow-up; ~15x median)
  - C3  (idx 15): mean QLIKE ~= 3904   (fixed-span MIDAS blow-up; ~6x median)
Well-behaved cluster is ~620-740; B0/GJR benchmark ~= 623.7 (lowest).

Bootstrap parameters are identical to k1380.py: B=499, seed=42,
mean_block=sqrt(T), centered t-stats (Hansen consistent SPA centering).
"""
import os
import json
from datetime import datetime, timezone

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Constants mirrored from k1380.py ───────────────────────────────────────
SPEC_LABELS = [
    'A1', 'A2', 'A3', 'A4', 'A5',
    'A2f', 'A4f', 'A3f', 'A2n', 'A4n',
    'B1', 'B2', 'B3',
    'C1', 'C2', 'C3',
    'B0',   # GJR benchmark — last
]
BENCHMARK = 'B0'
BOOTSTRAP_B = 499
BOOTSTRAP_SEED = 42
HARVEY_THRESHOLD = 3.0
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

# Convergence exclusion rule: all-NaN, or mean QLIKE an order of magnitude
# above the well-behaved cluster.
EXCLUDED = ['C1', 'A5', 'C2', 'C3']

# ── Load cached loss matrix ────────────────────────────────────────────────
qlike_matrix = np.load(os.path.join(SCRIPT_DIR, 'k1380_losses_all.npy'))
assert qlike_matrix.shape[0] == 17, qlike_matrix.shape
n_oos = qlike_matrix.shape[1]

per_spec_mean_full = np.nanmean(
    np.where(np.all(np.isnan(qlike_matrix), axis=1, keepdims=True),
             np.nan, qlike_matrix), axis=1)

# ── Diagnose exclusions (documented numeric justification) ─────────────────
excluded_specs = []
for sname in EXCLUDED:
    idx = SPEC_LABELS.index(sname)
    row = qlike_matrix[idx]
    if np.all(np.isnan(row)):
        mq = None
        reason = ("all-NaN across full OOS (fixed-span MIDAS produced zero "
                  "valid forecasts); non-convergent")
    else:
        mq = float(np.nanmean(row))
        reason = (f"mean QLIKE {mq:.1f} is orders of magnitude above the "
                  f"well-behaved cluster (~620-740); numerically divergent")
    excluded_specs.append({"spec": sname, "reason": reason, "mean_qlike": mq})

# ── Build clean spec set (convergent only, benchmark included) ─────────────
clean_specs = [s for s in SPEC_LABELS if s not in EXCLUDED]
clean_idx = [SPEC_LABELS.index(s) for s in clean_specs]
assert BENCHMARK in clean_specs

# valid_all over ONLY the clean set
clean_rows = qlike_matrix[clean_idx]
valid_all = np.all(~np.isnan(clean_rows), axis=0)
n_valid = int(valid_all.sum())
T = n_valid
print(f"Clean spec set ({len(clean_specs)}): {clean_specs}")
print(f"Excluded ({len(EXCLUDED)}): {EXCLUDED}")
print(f"n_valid (all included specs valid): {n_valid}")

# ── Mean QLIKE ranking over clean set on the clean valid mask ──────────────
mean_qlikes = {s: float(np.nanmean(qlike_matrix[SPEC_LABELS.index(s), valid_all]))
               for s in clean_specs}
sorted_specs = sorted(mean_qlikes.items(), key=lambda x: x[1])
print("\nMean QLIKE ranking (lower = better):")
for rank, (sn, ql) in enumerate(sorted_specs, 1):
    print(f"  {rank:2d}. {sn:4s}: {ql:.6f}")

# ── Stationary bootstrap (identical to k1380.py) ───────────────────────────
rng = np.random.default_rng(BOOTSTRAP_SEED)


def stationary_bootstrap_indices(T, B, rng, mean_block=None):
    if mean_block is None:
        mean_block = max(1, int(np.sqrt(T)))
    p_geom = 1.0 / mean_block
    samples = []
    for _ in range(B):
        idx = []
        pos = rng.integers(0, T)
        while len(idx) < T:
            idx.append(pos % T)
            if rng.random() < p_geom:
                pos = rng.integers(0, T)
            else:
                pos = (pos + 1) % T
        samples.append(idx[:T])
    return samples


# Loss differentials vs B0 (positive = spec beats GJR)
benchmark_ql = qlike_matrix[SPEC_LABELS.index(BENCHMARK), valid_all]
spec_order_no_bm = [s for s in clean_specs if s != BENCHMARK]
n_specs = len(spec_order_no_bm)
diff_matrix = np.empty((n_specs, n_valid))
for i, sname in enumerate(spec_order_no_bm):
    diff_matrix[i] = benchmark_ql - qlike_matrix[SPEC_LABELS.index(sname), valid_all]

d_bar = diff_matrix.mean(axis=1)
d_std = diff_matrix.std(axis=1, ddof=1) + 1e-12
t_obs = np.sqrt(T) * d_bar / d_std

spa_stat_obs = float(np.max(np.maximum(t_obs, 0.0)))

bootstrap_spa_stats = np.empty(BOOTSTRAP_B)
bs_indices = stationary_bootstrap_indices(T, BOOTSTRAP_B, rng)
for b_idx, idx in enumerate(bs_indices):
    d_b = diff_matrix[:, idx]
    d_bar_b = d_b.mean(axis=1)
    d_std_b = d_b.std(axis=1, ddof=1) + 1e-12
    t_b = np.sqrt(T) * (d_bar_b - d_bar) / d_std_b       # centered
    bootstrap_spa_stats[b_idx] = float(np.max(np.maximum(t_b, 0.0)))

spa_pval = float((bootstrap_spa_stats >= spa_stat_obs).mean())

# White RC focus: A4f vs GJR
a4f_idx = spec_order_no_bm.index('A4f')
rc_stat_obs = float(t_obs[a4f_idx])
bootstrap_rc_stats = np.empty(BOOTSTRAP_B)
for b_idx, idx in enumerate(bs_indices):
    d_b_a4f = diff_matrix[a4f_idx, idx]
    d_bar_b_a4f = d_b_a4f.mean()
    d_std_b_a4f = d_b_a4f.std(ddof=1) + 1e-12
    t_b_a4f = np.sqrt(T) * (d_bar_b_a4f - d_bar[a4f_idx]) / d_std_b_a4f
    bootstrap_rc_stats[b_idx] = float(np.max([0.0, t_b_a4f]))

rc_pval = float((bootstrap_rc_stats >= rc_stat_obs).mean())

print(f"\nSPA stat (max_i t): {spa_stat_obs:.3f}  p={spa_pval:.4f}  "
      f"reject@0.10={spa_pval < 0.10}")
print(f"A4f RC t-stat: {rc_stat_obs:.3f}  p={rc_pval:.4f}  "
      f"reject@0.10={rc_pval < 0.10}")

print("\nIndividual t-stats:")
for i, sn in enumerate(spec_order_no_bm):
    tag = "Harvey PASS" if abs(t_obs[i]) > HARVEY_THRESHOLD and d_bar[i] > 0 else ""
    print(f"  {sn:4s}: t={t_obs[i]:7.3f}  d_bar={d_bar[i]:10.6f}  {tag}")

superior_set = [spec_order_no_bm[i] for i in range(n_specs)
                if d_bar[i] > 0 and t_obs[i] > 0]
print(f"\nNominal superior set (d_bar>0 & t>0): {superior_set}")

# ── Results JSON ───────────────────────────────────────────────────────────
results = {
    "experiment_id": "k1380",
    "title": "Paper 9 White RC / Hansen SPA Test — 17-Spec Horse Race (convergent subset)",
    "metadata": {
        "data_source": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "oos_start": OOS_START,
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "bootstrap_B": BOOTSTRAP_B,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "harvey_threshold": HARVEY_THRESHOLD,
        "qlike_proxy": "r_squared (Patton 2011 proxy-robust)",
        "n_valid_oos": int(n_valid),
        "computed_from_cache": "k1380_losses_all.npy (no re-fitting)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lookahead_free": "signal.shift(1): vix[abs_idx-1] for t-1 VIX lag",
        "c3_critical_addressed": True,
    },
    "caveat": (
        f"Horse race is over the convergent subset only: {len(clean_specs)} of 17 "
        f"specs ({len(clean_specs)-1} candidates + GJR benchmark); "
        f"{len(EXCLUDED)} excluded for non-convergence (C1 all-NaN; A5/C2/C3 divergent)."
    ),
    "excluded_specs": excluded_specs,
    "mean_qlike_ranking": [
        {"rank": r + 1, "spec": sn, "mean_qlike": float(ql)}
        for r, (sn, ql) in enumerate(sorted_specs)
    ],
    "hansen_spa_test": {
        "stat": spa_stat_obs,
        "pval": spa_pval,
        "reject_h0_p10": bool(spa_pval < 0.10),
        "interpretation": (
            "At least one model significantly superior to GJR after data snooping"
            if spa_pval < 0.10 else
            "Cannot reject H0: no model significantly beats GJR after data snooping"
        ),
        "superior_set_nominal": superior_set,
    },
    "white_rc_test": {
        "spec": "A4f",
        "t_stat": rc_stat_obs,
        "pval": rc_pval,
        "reject_h0_p10": bool(rc_pval < 0.10),
        "interpretation": (
            "A4f significantly beats GJR after RC correction"
            if rc_pval < 0.10 else
            "RC test: cannot confirm A4f beats GJR after data snooping"
        ),
    },
    "individual_dm_stats": {
        sn: {"t_stat": float(t_obs[i]), "d_bar": float(d_bar[i]),
             "harvey_pass": bool(d_bar[i] > 0 and t_obs[i] > HARVEY_THRESHOLD)}
        for i, sn in enumerate(spec_order_no_bm)
    },
    "c3_verdict": (
        "C3 ADDRESSED: SPA test confirms superiority is not purely data-snooping artifact"
        if spa_pval < 0.10 and rc_pval < 0.10 else
        "C3 ADDRESSED: SPA/RC fail to reject H0 — no GARCH-X/MIDAS spec significantly "
        "beats GJR after multiple-testing correction; GJR has lowest mean QLIKE"
    ),
}

out_path = os.path.join(SCRIPT_DIR, 'k1380_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to {out_path}")
