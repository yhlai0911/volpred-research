#!/usr/bin/env python3
"""
K1259 Phase 2: MCS (Model Confidence Set) algorithm + per-asset run.

Implements Hansen-Lunde-Nason (2011) MCS via iterative elimination applied to
the Phase-1 DM ledger. Because the ledger only records pairwise DM statistics
(not the full per-day loss series for every pair), this is a *variant A*
"ledger-only" implementation: t-statistics come from DM stats directly, and
bootstrap p-values are computed from resampled DM-stat matrices under the null
of equal predictive accuracy (t_ij ~ N(0,1) iid; H0: loss-differential has
zero mean).

See k1259_README_phase2_appendix.md for algorithmic detail, variants, and
limitations.

Usage:
    python3 experiments/k1259/k1259_mcs.py

Outputs:
    experiments/k1259/k1259_mcs_results.json
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / "experiments" / "k1259" / "dm_ledger.json"
OUT_PATH = ROOT / "experiments" / "k1259" / "k1259_mcs_results.json"

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
ASSETS = ["SPY", "QQQ", "GLD", "0050.TW", "USO"]
LOSS_FNS = ["QLIKE", "MSE"]
ALPHAS = [0.10, 0.20]
BOOTSTRAP_B = 1000
SEED = 42

# Minimum number of pair-observations involving a model before it enters the
# MCS candidate pool (guards against noise from one-off experiments).
MIN_PAIRS_PER_MODEL = 2

# Minimum number of distinct candidate models per (asset, loss) cell to run
# a meaningful MCS (otherwise return degenerate single-set).
MIN_CANDIDATE_MODELS = 3


# ------------------------------------------------------------------
# Model-name normalization
# ------------------------------------------------------------------
# Manual alias table for canonical names (lowercase keys → canonical form).
# Primary intent: merge {GJR, gjr, GJR-GARCH, gjr-garch} → "GJR", etc.
CANONICAL_ALIAS: dict[str, str] = {
    # GARCH family
    "gjr": "GJR",
    "gjr-garch": "GJR",
    "gjr-garch(1,1)": "GJR",
    "gjr_garch": "GJR",
    "garch": "GARCH",
    "garch(1,1)": "GARCH",
    "egarch": "EGARCH",
    "egarch(1,1)": "EGARCH",
    "ewma": "EWMA",
    # GJR variants (preserved when distinct)
    "gjr_n": "GJR-N",
    "gjr-n": "GJR-N",
    "gjr_t": "GJR-t",
    "gjr-t": "GJR-t",
    "gjr-x": "GJR-X",
    "gjr_x": "GJR-X",
    # HAR family
    "har": "HAR",
    "har-rv": "HAR-RV",
    "har_rv": "HAR-RV",
    "har-yz": "HAR-YZ",
    "har_yz": "HAR-YZ",
    "har-vix": "HAR-VIX",
    "har_vix": "HAR-VIX",
    "har_abs": "HAR-ABS",
    "har-abs": "HAR-ABS",
    "har_logrange": "HAR-LOGRANGE",
    "har-logrange": "HAR-LOGRANGE",
    # Baselines
    "ar1": "AR1",
    "rv21_baseline": "RV21",
    "rv22_baseline": "RV22",
    "threshold": "THRESHOLD",
    "naive": "NAIVE",
    # MEM
    "mem": "MEM",
    "amem": "AMEM",
    "dmem": "DMEM",
    # Combinations
    "equal_weight": "Equal_Weight",
    "bma": "BMA",
    "best_single": "Best_Single",
    "mcs_pvalue": "MCS_PValue",
    "mcs_subperiod": "MCS_Subperiod",
    "inv_qlike": "Inv_QLIKE",
    "inv_qlike_prev": "Inv_QLIKE_Prev",
    # Conformal & VaR buckets
    "b1_normal": "B1_Normal",
    "b2_studentt": "B2_StudentT",
    "b3_histsim": "B3_HistSim",
    "c1_naive_conformal": "C1_Naive_Conformal",
    "c2_proxy_robust": "C2_Proxy_Robust",
    "c3_exch_conformal": "C3_Exch_Conformal",
    # Research series
    "a4f-vix9d-n": "A4f-VIX9D-N",
    "a4f_vix9d_n": "A4f-VIX9D-N",
}

# Suspicious model names (parse artifacts / numeric / empty) that should be
# dropped before MCS:
#   - Empty string
#   - Pure numeric (quantile levels from VaR DM rows: "0.01", "0.05", etc.)
#   - Sample-size markers ("252")
#   - Two-letter ALL-CAPS acronyms that are almost certainly parse prefixes
#     such as "DM" (from "DM_vs_X" field names)
NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
BAD_NAMES = {"", "DM", "ttest_dense", "ttest_any", "none", "robust"}


def normalize_model_name(s: str) -> str | None:
    """Return canonical model name, or None if the name is junk.

    Normalization pipeline:
    1. Strip whitespace.
    2. Drop empty / numeric / sample-size / known-junk names → None.
    3. Apply CANONICAL_ALIAS (case-insensitive) if match.
    4. Otherwise return the stripped raw string (preserve distinct variants).
    """
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    if NUMERIC_RE.match(s):
        return None
    if s in BAD_NAMES:
        return None
    # length-2 token uppercased that is definitely not a model = noise
    if len(s) <= 2 and s.isupper() and s in {"DM", "RV", "IS"}:
        return None
    key = s.lower()
    if key in CANONICAL_ALIAS:
        return CANONICAL_ALIAS[key]
    return s


# ------------------------------------------------------------------
# Ledger loading
# ------------------------------------------------------------------
def load_ledger(path: Path) -> tuple[list[dict], dict]:
    """Load Phase-1 ledger; return (filtered_rows, drop_stats).

    Filter rules (enforced here):
      - asset tag required (non-empty, singleton ticker — no pipe union)
      - model_a AND model_b must normalize to canonical
      - dm_stat must be finite

    Note: loss_fn is NOT filtered here. All recognized and unrecognized
    loss_fn rows pass through; downstream `build_t_matrix` iterates only
    LOSS_FNS = ["QLIKE", "MSE"] cells, so non-target loss rows are
    naturally excluded at matrix construction. Phase 3 readers iterating
    `kept` directly should not assume Parkinson/ES/FZ rows are absent.
    """
    with path.open() as fh:
        obj = json.load(fh)
    rows_raw = obj.get("rows", [])
    drop = Counter()
    kept: list[dict] = []

    for r in rows_raw:
        asset = r.get("asset")
        if not asset:
            drop["empty_asset"] += 1
            continue
        if "|" in asset:
            drop["multi_asset"] += 1
            continue
        ma = normalize_model_name(r.get("model_a") or "")
        mb = normalize_model_name(r.get("model_b") or "")
        if ma is None or mb is None:
            drop["bad_model_name"] += 1
            continue
        if ma == mb:
            drop["same_model"] += 1
            continue
        dm = r.get("dm_stat")
        if dm is None or not isinstance(dm, (int, float)) or not math.isfinite(float(dm)):
            drop["invalid_dm"] += 1
            continue
        kept.append({
            "k_id": r.get("k_id"),
            "model_a": ma,
            "model_b": mb,
            "loss_fn": r.get("loss_fn") or "QLIKE",
            "asset": asset,
            "dm_stat": float(dm),
            "p_value": r.get("p_value"),
            "sample_n": r.get("sample_n"),
            "period": r.get("period") or "",
            "source_field_path": r.get("source_field_path", ""),
            "source_file": r.get("source_file", ""),
        })
    return kept, dict(drop)


# ------------------------------------------------------------------
# Build pairwise t-matrix
# ------------------------------------------------------------------
def build_t_matrix(rows: list[dict], asset: str, loss_fn: str) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Aggregate ledger rows into a pair-t-statistic matrix for (asset, loss).

    Sign convention: t_stat[i, j] represents studentized mean loss-diff of
    model i vs model j, where:
        d_ij,t = L_i,t - L_j,t
        t_ij = mean(d_ij,t) / se(d_ij,t)
    Larger t_ij > 0 ⇒ model i has *higher* loss ⇒ i is worse than j.

    DM ledger row semantics follow same convention (code-verified via
    `experiments/*/build_*.py` — `dm_stat = mean(L_a - L_b) / se`).
    Multiple DM rows for the same (model_a, model_b) pair (across K
    experiments) are aggregated via *inverse-variance-weighted mean*
    (treating each DM stat as one standard-normal-scaled estimate of the
    true loss-diff population mean).

    Returns:
        models: list of model names in matrix row/col order.
        T: (m, m) ndarray of t-statistics; T[i, i] = 0; T[i, j] = -T[j, i].
        W: (m, m) ndarray of effective weights (# of DM rows contributing).
    """
    # Gather pair observations
    pair_t: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        if r["asset"] != asset or r["loss_fn"] != loss_fn:
            continue
        a, b = r["model_a"], r["model_b"]
        t = r["dm_stat"]
        if (a, b) in pair_t or (b, a) not in pair_t:
            pair_t[(a, b)].append(t)
        else:
            # store under canonical orientation
            pair_t[(b, a)].append(-t)

    # Count model appearances (across both sides)
    model_count: Counter = Counter()
    for (a, b), ts in pair_t.items():
        model_count[a] += len(ts)
        model_count[b] += len(ts)

    # Keep only models with enough pair observations
    keep_models = sorted([m for m, c in model_count.items() if c >= MIN_PAIRS_PER_MODEL])
    idx = {m: i for i, m in enumerate(keep_models)}
    m = len(keep_models)
    T = np.zeros((m, m), dtype=float)
    W = np.zeros((m, m), dtype=float)

    for (a, b), ts in pair_t.items():
        if a not in idx or b not in idx:
            continue
        i, j = idx[a], idx[b]
        # aggregate multiple t-stats by inverse-variance weighting (equal
        # variance per observation → simple mean is the BLUE)
        t_agg = float(np.mean(ts))
        w = len(ts)
        T[i, j] = t_agg
        T[j, i] = -t_agg
        W[i, j] = w
        W[j, i] = w

    return keep_models, T, W


# ------------------------------------------------------------------
# HLN-style MCS via iterative elimination (variant A: ledger-only)
# ------------------------------------------------------------------
def mcs_test(models: list[str], T: np.ndarray, alpha: float, B: int = BOOTSTRAP_B, seed: int = SEED) -> dict:
    """Iterative MCS elimination (variant A).

    Algorithm:
        Candidate set M_0 = {all models}.
        While |M| > 1:
            For each i in M, compute t_max(i) = max_{j in M, j != i} T[i, j]
                (how much worse model i is than its toughest rival in M).
            Observed test statistic: T_max = max_i t_max(i).
            The "worst" candidate is i* = argmax_i t_max(i).
            Bootstrap H0: t_ij,b ~ N(0, 1) i.i.d. (equal predictive ability).
                For b = 1..B, sample m×m antisymmetric matrix with N(0,1)
                entries; compute T_max,b the same way on the current M.
            p = (1 + #{T_max,b >= T_max}) / (B + 1).
            If p < alpha: eliminate i*; else stop.
        Surviving M = superior set (MCS-hat).

    Returns dict with superior_set, eliminated_ordered (list of
    (model, p_value_at_elimination)), final_p_values (empty here because
    the final stopping p is reported once), and iteration trace.
    """
    rng = np.random.default_rng(seed)
    surviving = list(range(len(models)))
    eliminated_ordered: list[dict] = []
    final_p = None
    trace: list[dict] = []

    while len(surviving) > 1:
        sub = T[np.ix_(surviving, surviving)]
        # For each i in surviving, t_max_i = max over j != i of sub[i, j]
        m = len(surviving)
        # zero-out diagonal then take row max
        sub_off = sub.copy()
        np.fill_diagonal(sub_off, -np.inf)
        t_max_per_model = sub_off.max(axis=1)
        T_max_obs = float(t_max_per_model.max())
        worst_local_idx = int(np.argmax(t_max_per_model))
        worst_model = models[surviving[worst_local_idx]]

        # Bootstrap null: symmetric-antisymmetric N(0,1) matrix of same shape
        # (H0: all pair loss diffs are zero-mean standard-normal studentized)
        boot_tmax = np.empty(B, dtype=float)
        for b in range(B):
            g = rng.standard_normal((m, m))
            # antisymmetrize so upper & lower halves are negatives
            g = (g - g.T) / math.sqrt(2.0)
            np.fill_diagonal(g, -np.inf)
            boot_tmax[b] = g.max(axis=1).max()

        # p-value: fraction of bootstrap T_max >= observed (one-sided)
        p = (1.0 + float(np.sum(boot_tmax >= T_max_obs))) / (B + 1)
        p = max(p, 1.0 / (B + 1))  # lower bound

        trace.append({
            "surviving_n": m,
            "T_max": round(T_max_obs, 6),
            "worst_model": worst_model,
            "p_value": round(p, 6),
        })

        if p < alpha:
            eliminated_ordered.append({
                "model": worst_model,
                "T_max_at_elim": round(T_max_obs, 6),
                "p_value": round(p, 6),
            })
            # drop worst
            surviving.pop(worst_local_idx)
        else:
            final_p = p
            break

    if final_p is None:
        # loop exited due to |M|==1
        final_p = 1.0

    superior_set = sorted(models[i] for i in surviving)
    return {
        "superior_set": superior_set,
        "eliminated_ordered": eliminated_ordered,
        "n_models_input": len(models),
        "n_models_survived": len(surviving),
        "final_stopping_p": round(float(final_p), 6),
        "bootstrap_B": B,
        "seed": seed,
        "trace": trace,
    }


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main() -> int:
    rows, drop_stats = load_ledger(LEDGER_PATH)
    print(f"Loaded {len(rows)} rows after filtering.")
    print(f"Drop stats: {drop_stats}")

    # Build normalization map (raw → canonical) for reporting
    # We only record non-identity mappings that actually fired on ledger input.
    normalization_map: dict[str, str] = {}
    with LEDGER_PATH.open() as fh:
        raw_rows = json.load(fh).get("rows", [])
    for r in raw_rows:
        for side in ("model_a", "model_b"):
            raw = r.get(side)
            if not isinstance(raw, str):
                continue
            canon = normalize_model_name(raw)
            if canon is not None and canon != raw:
                normalization_map[raw] = canon

    per_asset_results: dict = {}
    total_mcs_runs = 0
    for asset in ASSETS:
        per_asset_results[asset] = {}
        for loss_fn in LOSS_FNS:
            models, T, W = build_t_matrix(rows, asset, loss_fn)
            print(f"\n[{asset} / {loss_fn}] candidates = {len(models)}")
            if len(models) < MIN_CANDIDATE_MODELS:
                per_asset_results[asset][loss_fn] = {
                    "status": "insufficient_models",
                    "n_models_input": len(models),
                    "message": f"only {len(models)} candidates (need >={MIN_CANDIDATE_MODELS}); MCS skipped",
                    "candidate_models": models,
                }
                continue

            loss_block: dict = {
                "n_models_input": len(models),
                "candidate_models": models,
                "n_pairs_total": int((W > 0).sum() // 2),
            }
            for alpha in ALPHAS:
                res = mcs_test(models, T, alpha=alpha, B=BOOTSTRAP_B, seed=SEED)
                loss_block[f"alpha_{alpha:.2f}"] = res
                total_mcs_runs += 1
                print(
                    f"  α={alpha}: superior={res['superior_set']} "
                    f"(survived {res['n_models_survived']}/{res['n_models_input']}, "
                    f"stop p={res['final_stopping_p']})"
                )
            per_asset_results[asset][loss_fn] = loss_block

    out = {
        "experiment_id": "K1259",
        "phase": "2_mcs_algorithm",
        "variant": "A_ledger_only",
        "variant_rationale": (
            "Phase-1 ledger stores pairwise DM statistics but not per-day "
            "loss series; variant A treats DM stats as studentized loss "
            "differentials and uses Gaussian null for T_max bootstrap. "
            "Variant B (reconstruct loss series from source JSON + stationary "
            "bootstrap) was evaluated but <50% asset coverage would have "
            "per-day losses available in ledger source files; see appendix."
        ),
        "config": {
            "bootstrap_B": BOOTSTRAP_B,
            "seed": SEED,
            "alphas": ALPHAS,
            "loss_fns": LOSS_FNS,
            "assets": ASSETS,
            "min_pairs_per_model": MIN_PAIRS_PER_MODEL,
            "min_candidate_models": MIN_CANDIDATE_MODELS,
        },
        "results": per_asset_results,
        "summary": {
            "total_rows_consumed": len(rows),
            "total_mcs_runs": total_mcs_runs,
            "rows_dropped_multi_asset": drop_stats.get("multi_asset", 0),
            "rows_dropped_empty_asset": drop_stats.get("empty_asset", 0),
            "rows_dropped_bad_model_name": drop_stats.get("bad_model_name", 0),
            "rows_dropped_same_model_pair": drop_stats.get("same_model", 0),
            "rows_dropped_invalid_dm": drop_stats.get("invalid_dm", 0),
            "model_name_normalization_map": normalization_map,
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f"\nWrote {OUT_PATH}")
    print(f"Total MCS runs: {total_mcs_runs} (expected {len(ASSETS) * len(LOSS_FNS) * len(ALPHAS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
