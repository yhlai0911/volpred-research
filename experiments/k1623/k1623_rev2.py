"""
K1623 rev2 — retract the identification claim; add the MSE DM tests and the
multiple-comparison correction that the original round omitted.
=============================================================================

Why this script exists
----------------------
K1623 was independently re-reviewed (codex gpt-5.6-sol, reasoning=high,
2026-07-17) and judged FAIL. The arithmetic was not the problem -- every number
in `k1623_results.json` reproduces. The problem is that the *claims* in
`README.md` outran the *evidence*. Three claims are retracted here:

  (a) "genuine long memory exists / the pure level-shift hypothesis is rejected"
      -- an identification claim that <=5 (permissive 15) deterministic
      Bai-Perron MEAN breaks cannot support against Diebold-Inoue, whose data
      generating process is a RANDOM, potentially dense shift process.
  (b) "not tradable" -- no strategy, cost or utility test was ever run.
  (c) "several comparisons are significantly worse" -- 1 of 20 was nominally
      significant, and it does not survive any multiple-comparison correction.

and one omission is repaired: the original round ran DM tests on QLIKE only,
while ARFIMA's MSE is *lower* than HAR's in 4 of 5 assets. README §4 claimed
both losses were tested. They were not. The loss-dependent sign reversal is the
main deliverable of this round.

Inference fix (mandatory, not optional)
---------------------------------------
`k1623.dm_hln` computes its Newey-West sum as `for lag in range(1, h)`. At h=1
that loop is EMPTY, i.e. no HAC correction at all. That site is already frozen
in `storage/ops/dm_hac_lag_baseline.json` under `degenerate_sites`, and
`.claude/rules/experiments.md` requires `lag = max(h-1, canonical bandwidth)`.
Building this round's headline MSE result on that estimator would repeat K1655.

So all rev2 inference uses the canonical
`volpred.stats.model_evaluation.dm_test` (Newey-West, bandwidth
ceil(h^(1/3) n^(1/3)), floored at 1). The original degenerate t-statistics are
recomputed and reported side by side so the revision is auditable, and the
lag-1 autocorrelation of every loss differential is reported so the DIRECTION
of the correction is visible rather than asserted. Omitting HAC is a two-sided
misspecification: positive autocorrelation inflates |t|, negative
autocovariance deflates it (k621: |t| 2.26 -> 3.64 after the fix).

Reproduction guard
------------------
The OOS loop below is a copy of `k1623.run_oos` whose ONLY change is that it
retains the pointwise loss vectors (the original discarded them, which is why
no MSE test could be run post hoc). `k1623.py` is left byte-identical. To prove
the copy has not drifted, every reproduced qlike_mean / qlike_median / mse /
clip_hit_rate is asserted equal to the value stored in `k1623_results.json` to a
1e-9 relative tolerance.

LIMIT OF THAT PROOF (be precise -- this round exists because a previous round was
not): the original artifact stores only these AGGREGATES; it never stored the
per-period forecast vectors, so a pointwise forecast-by-forecast comparison is
IMPOSSIBLE against it. Agreement of four independent functionals (two different
moments of the loss distribution, plus a median, plus a guard-hit count) to 1e-9
is very strong evidence that the forecast paths coincide, but it is EVIDENCE, not
proof. The honest claim is "the reproduced aggregate losses are identical", not
"the forecasts are identical". TW0050 is excluded from the assertion entirely
(revised upstream history) and is measured and disclosed instead.

Scope discipline: no new assets, no new models, no new sample period. This
round changes what is CLAIMED, and fixes the test used to support it.

Run:  uv run python experiments/k1623/k1623_rev2.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402

import k1623 as K  # noqa: E402  (module-level DB resolution happens on import)

SEED = 42
np.random.seed(SEED)

MODELS = ["HAR", "AR1", "ARFIMA", "BreakHAR", "EWMA"]
CHALLENGERS = [m for m in MODELS if m != "HAR"]
# The two models the identification story actually rides on. Reported as a
# pre-specified focal subset alongside the full family, because "does exploiting
# fractional integration / adapting to breaks help?" is the question K1623 asked.
FOCAL = ["ARFIMA", "BreakHAR"]

RESULTS_ORIG = HERE / "k1623_results.json"
OUT = HERE / "k1623_rev2_results.json"


# --------------------------------------------------------------------------- #
# OOS re-run that retains pointwise losses
# --------------------------------------------------------------------------- #
def run_oos_with_losses(logrv: np.ndarray, rv: np.ndarray) -> dict:
    """Byte-faithful copy of k1623.run_oos, extended to keep the loss vectors.

    Every forecasting line is identical to the original; the additions are the
    `losses` dict at the end. The reproduction assertion in main() is what makes
    that claim checkable rather than a promise.
    """
    n = len(logrv)
    i0 = max(K.HAR_MINTRAIN + 22, n - K.OOS_TEST_N)
    origins = list(range(i0, n - 1))
    if len(origins) < 60:
        return {"error": "insufficient OOS window", "n": n}

    Xall, yall, _ = K.har_design(logrv)
    fc = {k: [] for k in MODELS}
    clip_hits = {k: 0 for k in fc}
    actual = []

    d_arf = None
    w_arf = None
    arf_mu = None
    arf_sig2 = 0.0
    brk_start = None
    ewma_var = float(rv[:i0].mean())
    for t in range(i0):
        ewma_var = K.EWMA_LAMBDA * ewma_var + (1 - K.EWMA_LAMBDA) * rv[t]

    for step, i in enumerate(origins):
        y_tr = logrv[0:i + 1]
        x_next = Xall[i + 1]

        lf_lo = float(np.min(y_tr)) - 1.0
        lf_hi = float(np.max(y_tr)) + 1.0

        def var_fc(logf, name):
            if logf < lf_lo or logf > lf_hi:
                clip_hits[name] += 1
            return float(np.exp(np.clip(logf, lf_lo, lf_hi)))

        rows = np.arange(22, i + 1)
        beta_h, sig2_h = K.ols_fit(Xall[rows], yall[rows])
        mu_h = float(x_next @ beta_h)
        fc["HAR"].append(var_fc(mu_h + 0.5 * sig2_h, "HAR"))

        y1 = logrv[1:i + 1]
        y0 = logrv[0:i]
        A = np.column_stack([np.ones(len(y0)), y0])
        b_ar, sig2_ar = K.ols_fit(A, y1)
        mu_ar = float(b_ar[0] + b_ar[1] * logrv[i])
        fc["AR1"].append(var_fc(mu_ar + 0.5 * sig2_ar, "AR1"))

        if (step % K.REEST_EVERY == 0) or (d_arf is None):
            m_lw = int(len(y_tr) ** 0.65)
            d_arf = float(np.clip(K.local_whittle(y_tr, m_lw, exact=True)["d"], -0.45, 0.95))
            arf_mu = float(y_tr.mean())
            Kk = min(K.FD_MAXK, i)
            w_arf = K._fd_weights(d_arf, Kk)
            fd_tr = K.fracdiff(y_tr - arf_mu, d_arf)
            arf_sig2 = float(np.var(fd_tr[22:])) if len(fd_tr) > 40 else float(np.var(fd_tr))
        Kw = len(w_arf) - 1
        kmax = min(Kw, i + 1)
        hist = logrv[i + 1 - kmax:i + 1][::-1] - arf_mu
        contrib = float(np.dot(w_arf[1:kmax + 1], hist))
        mu_arf = arf_mu - contrib
        fc["ARFIMA"].append(var_fc(mu_arf + 0.5 * arf_sig2, "ARFIMA"))

        if (step % K.REEST_EVERY == 0) or (brk_start is None):
            lb = K.latest_break(logrv[:i + 1], min_seg=60, look=1000)
            brk_start = lb if lb is not None else max(0, i + 1 - 750)
        wstart = max(0, min(brk_start, i - 22 - 60))
        rows_b = np.arange(max(wstart, 22), i + 1)
        if len(rows_b) >= 60:
            beta_b, sig2_b = K.ols_fit(Xall[rows_b], yall[rows_b])
            mu_b = float(x_next @ beta_b)
            fc["BreakHAR"].append(var_fc(mu_b + 0.5 * sig2_b, "BreakHAR"))
        else:
            fc["BreakHAR"].append(var_fc(mu_h + 0.5 * sig2_h, "BreakHAR"))

        ewma_var = K.EWMA_LAMBDA * ewma_var + (1 - K.EWMA_LAMBDA) * rv[i]
        fc["EWMA"].append(ewma_var)

        actual.append(rv[i + 1])

    actual = np.array(actual)
    qlike, sqerr, summary = {}, {}, {}
    for k, v in fc.items():
        pred = np.maximum(np.array(v), K.LOG_FLOOR)
        qlike[k] = qlike_pointwise(actual, pred)
        sqerr[k] = (actual - pred) ** 2
        summary[k] = {
            "qlike_mean": float(np.mean(qlike[k])),
            "qlike_median": float(np.median(qlike[k])),
            "mse": float(np.mean(sqerr[k])),
            "clip_hit_rate": float(clip_hits[k] / len(actual)),
        }
    return {"n_oos": len(actual), "summary": summary,
            "losses": {"QLIKE": qlike, "MSE": sqerr}}


# --------------------------------------------------------------------------- #
# Inference helpers
# --------------------------------------------------------------------------- #
def hln_factor(T: int, h: int = 1) -> float:
    """Harvey-Leybourne-Newbold small-sample multiplier. At h=1 this is
    sqrt((T-1)/T) -- ~0.9993 for T=749, i.e. immaterial, but reported rather
    than hand-waved so the rev2 t-stats stay comparable to the original ones."""
    return float(np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T))


def lag1_autocorr(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    xc = x - x.mean()
    denom = float(np.sum(xc ** 2))
    if denom <= 0:
        return float("nan")
    return float(np.sum(xc[1:] * xc[:-1]) / denom)


def hac_bandwidth(n: int, h: int = 1) -> int:
    """The canonical dm_test bandwidth, recomputed for disclosure."""
    return max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    """BH step-up adjusted p-values (monotone-enforced)."""
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m, dtype=float)
    running = 1.0
    for rank in range(m - 1, -1, -1):
        idx = order[rank]
        val = pvals[idx] * m / (rank + 1)
        running = min(running, val)
        adj[idx] = running
    return [float(min(1.0, v)) for v in adj]


def bonferroni(pvals: list[float]) -> list[float]:
    m = len(pvals)
    return [float(min(1.0, p * m)) for p in pvals]


def apply_corrections(rows: list[dict], family_key: str, label: str) -> None:
    """Attach BH / Bonferroni adjusted p-values for a named family, in place."""
    pv = [r["p_hac"] for r in rows]
    bh = benjamini_hochberg(pv)
    bf = bonferroni(pv)
    for r, b, f in zip(rows, bh, bf):
        r.setdefault("corrections", {})[family_key] = {
            "family": label, "family_size": len(rows),
            "p_bh": b, "p_bonferroni": f,
            "sig_bh_05": bool(b < 0.05), "sig_bonferroni_05": bool(f < 0.05),
        }


def pin_vintage(proxy, orig_asset: dict, label: str):
    """Truncate the series to the ORIGINAL round's data vintage.

    The price cache has advanced since k1623 was run (every asset gained ~10
    trading days: 2026-07-02/03 -> 2026-07-17). Because the OOS window is
    defined as the trailing 750 observations, fresh data slides that window
    forward and changes every forecast -- which would confound "the claim
    changed because the test was fixed" with "the claim changed because the
    sample moved". This round is about claims vs evidence, so the sample is
    pinned and ONLY the inference changes.

    Truncation is by date and is safe to apply after rv_proxy: the degenerate
    -observation filter (high > low) is row-local, so dropping later rows cannot
    alter earlier ones.
    """
    end = str(orig_asset["period"][1])
    out = proxy[proxy["date"] <= end].reset_index(drop=True)
    n_now, n_orig = len(out), int(orig_asset["n"])
    if n_now == n_orig:
        return out, {"exact": True, "n": n_now}

    # A revision, not merely an extension. Do NOT hand-pick a row to force the
    # count to match -- that would be fabricating a reproduction. Disclose it,
    # and let the caller measure how far the near-replication actually drifts.
    drift = abs(n_now - n_orig) / n_orig
    if drift > 0.01:
        raise RuntimeError(
            f"{label}: vintage pin to {end} gave n={n_now} vs original {n_orig} "
            f"({drift:.2%} drift). Too large to be an isolated OHLC revision -- stop and "
            "investigate before treating any rev2 number as a revision of the original."
        )
    return out, {
        "exact": False, "n": n_now, "n_original": n_orig,
        "note": f"{label} cannot be reproduced exactly: the cached history was REVISED, not "
                f"just extended. At the pin date the raw row count is unchanged, but one "
                f"formerly degenerate (high == low) row now has high > low, so it is retained "
                f"where the original round dropped it. rev2 {label} statistics are therefore a "
                f"NEAR-replication (n differs by {abs(n_now - n_orig)}); the measured deviation "
                f"from the original summary statistics is reported in max_relative_deviation.",
    }


def atomic_write_json(path: Path, payload: dict) -> None:
    """Preamble §4: write to tmp, re-parse to verify, then os.replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    with open(tmp, encoding="utf-8") as fh:
        json.load(fh)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
def main() -> None:
    t_start = time.time()
    orig = json.loads(RESULTS_ORIG.read_text(encoding="utf-8"))

    per_asset: dict[str, dict] = {}
    dm_rows: list[dict] = []
    repro_max_rel = 0.0
    vintage_report: dict[str, dict] = {}

    for ticker, kind, label in K.ASSETS:
        t0 = time.time()
        proxy = K.rv_proxy(K.load_ohlc(ticker), kind)
        proxy, vintage = pin_vintage(proxy, orig["assets"][label], label)
        vintage_report[label] = vintage
        logrv = proxy["logrv"].to_numpy()
        rv = proxy["rv"].to_numpy()
        oos = run_oos_with_losses(logrv, rv)
        if "error" in oos:
            raise RuntimeError(f"{label}: {oos['error']}")

        # --- reproduction guard against the frozen original artifact --------
        # Exact-pin assets must reproduce to 1e-9: that is the proof the rev2 OOS
        # loop is the original loop and only the test statistic changed. The one
        # revised-history asset is measured, not asserted, and its deviation is
        # published so a reader can judge whether the revision matters.
        orig_models = orig["assets"][label]["oos"]["models"]
        asset_max_rel = 0.0
        for m in MODELS:
            # Four independent functionals, not one: two loss moments, a median
            # (robust to the tail that dominates MSE), and the guard-hit count.
            # Agreeing on all four to 1e-9 is much harder to achieve by accident
            # than agreeing on the mean alone. It is still not a pointwise check
            # -- see the module docstring for why that is impossible here.
            for field in ("qlike_mean", "qlike_median", "mse", "clip_hit_rate"):
                got, want = oos["summary"][m][field], orig_models[m][field]
                rel = abs(got - want) / max(abs(want), 1e-300)
                asset_max_rel = max(asset_max_rel, rel)
        vintage["max_relative_deviation_vs_original"] = asset_max_rel
        if vintage["exact"]:
            repro_max_rel = max(repro_max_rel, asset_max_rel)
            assert oos["n_oos"] == orig["assets"][label]["oos"]["n_oos"], label
            assert asset_max_rel < 1e-9, (
                f"{label}: exact vintage pin but max rel dev {asset_max_rel:.3e} -- the rev2 "
                "OOS loop has drifted from k1623.run_oos. Fix the copy before trusting any "
                "rev2 statistic."
            )

        n_oos = oos["n_oos"]
        hln = hln_factor(n_oos, h=1)
        bw = hac_bandwidth(n_oos, h=1)

        for loss_name in ("QLIKE", "MSE"):
            L = oos["losses"][loss_name]
            for model in CHALLENGERS:
                diff = L[model] - L["HAR"]
                t_hac, p_hac = dm_test(L[model], L["HAR"], h=1)
                # Same HLN multiplier as the original round, applied to the
                # HAC-corrected statistic so the two columns are comparable.
                t_hac_hln = t_hac * hln
                # p implied by the HLN-adjusted statistic. NOTE: p_hac (the value
                # actually fed to BH/Bonferroni below) corresponds to t_hac, NOT
                # to t_hac_hln. At h=1, n=749 the multiplier is ~0.9993 so the two
                # p-values differ in the 4th decimal and no 5% verdict changes --
                # but the asymmetry is disclosed rather than left for a reader to
                # discover, and both columns are published so it can be checked.
                p_hac_hln = float(2 * stats.t.sf(abs(t_hac_hln), df=n_oos - 1))
                # The original, degenerate (zero-lag) statistic, recomputed.
                t_deg, p_deg = K.dm_hln(L[model], L["HAR"], h=1)
                mean_a, mean_b = float(np.mean(L[model])), float(np.mean(L["HAR"]))
                dm_rows.append({
                    "asset": label, "loss": loss_name, "model": model,
                    "benchmark": "HAR", "n_oos": n_oos,
                    "loss_model": mean_a, "loss_HAR": mean_b,
                    "loss_ratio_model_over_HAR": float(mean_a / mean_b) if mean_b else float("nan"),
                    "winner": "model" if mean_a < mean_b else "HAR",
                    "t_hac": float(t_hac), "t_hac_hln": float(t_hac_hln),
                    "p_hac": float(p_hac), "p_hac_hln": p_hac_hln,
                    "hac_bandwidth": bw,
                    "loss_diff_acf1": lag1_autocorr(diff),
                    "t_original_degenerate_no_hac": float(t_deg),
                    "p_original_degenerate_no_hac": float(p_deg),
                    "abs_t_change_from_hac": float(abs(t_hac_hln) - abs(t_deg)),
                    "focal": model in FOCAL,
                })

        per_asset[label] = {
            "n_oos": n_oos, "hln_factor_h1": hln, "hac_bandwidth": bw,
            "models": oos["summary"],
            "best_by_qlike": min(MODELS, key=lambda m: oos["summary"][m]["qlike_mean"]),
            "best_by_mse": min(MODELS, key=lambda m: oos["summary"][m]["mse"]),
            "runtime_sec": round(time.time() - t0, 2),
        }
        print(f"[{label}] n_oos={n_oos} best_QLIKE={per_asset[label]['best_by_qlike']} "
              f"best_MSE={per_asset[label]['best_by_mse']} ({per_asset[label]['runtime_sec']}s)")

    # ---- multiple-comparison corrections over explicit families ------------
    # PRE-SPECIFIED PRIMARY FAMILY: within_loss_20, i.e. corrections are applied
    # separately within QLIKE and within MSE, each of size 20. Every conclusion
    # drawn in README.md uses BH at that family. This is fixed here, in code,
    # ahead of the results, precisely so that "which family" cannot be chosen
    # after seeing which one gives the nicer answer.
    #
    # HONEST LABELLING: the loop below builds FIVE hypothesis sets, not three,
    # and they are NESTED rather than disjoint -- QLIKE-20, MSE-20, QLIKE-focal-10,
    # MSE-focal-10, pooled-40. focal_10 is a subset of its within_loss_20, and
    # pooled_40 is the union of both. The extra sets are published as sensitivity
    # (the conclusion is the same in all of them: zero focal comparisons survive),
    # NOT as a menu to select from.
    for loss_name in ("QLIKE", "MSE"):
        fam = [r for r in dm_rows if r["loss"] == loss_name]
        apply_corrections(fam, "within_loss_20", f"{loss_name}: 5 assets x 4 challengers")
        focal = [r for r in fam if r["focal"]]
        apply_corrections(focal, "focal_10", f"{loss_name}: 5 assets x {{ARFIMA, BreakHAR}}")
    apply_corrections(dm_rows, "pooled_40", "both losses: 5 assets x 4 challengers x 2 losses")

    # ---- headline: the loss-dependent sign reversal -------------------------
    reversal = []
    for label in [a[2] for a in K.ASSETS]:
        q = next(r for r in dm_rows if r["asset"] == label and r["loss"] == "QLIKE"
                 and r["model"] == "ARFIMA")
        m = next(r for r in dm_rows if r["asset"] == label and r["loss"] == "MSE"
                 and r["model"] == "ARFIMA")
        reversal.append({
            "asset": label,
            "qlike_ratio_arfima_over_har": q["loss_ratio_model_over_HAR"],
            "qlike_winner": q["winner"],
            "qlike_p_hac": q["p_hac"],
            "mse_ratio_arfima_over_har": m["loss_ratio_model_over_HAR"],
            "mse_winner": m["winner"],
            "mse_p_hac": m["p_hac"],
            "sign_reversal": q["winner"] != m["winner"],
        })

    def _count(pred) -> int:
        return sum(1 for r in dm_rows if pred(r))

    summary = {
        "n_dm_comparisons_total": len(dm_rows),
        "nominal_sig_05": {
            "QLIKE": _count(lambda r: r["loss"] == "QLIKE" and r["p_hac"] < 0.05),
            "MSE": _count(lambda r: r["loss"] == "MSE" and r["p_hac"] < 0.05),
        },
        "bh_sig_05_within_loss": {
            "QLIKE": _count(lambda r: r["loss"] == "QLIKE"
                            and r["corrections"]["within_loss_20"]["sig_bh_05"]),
            "MSE": _count(lambda r: r["loss"] == "MSE"
                          and r["corrections"]["within_loss_20"]["sig_bh_05"]),
        },
        "bonferroni_sig_05_within_loss": {
            "QLIKE": _count(lambda r: r["loss"] == "QLIKE"
                            and r["corrections"]["within_loss_20"]["sig_bonferroni_05"]),
            "MSE": _count(lambda r: r["loss"] == "MSE"
                          and r["corrections"]["within_loss_20"]["sig_bonferroni_05"]),
        },
        "focal_arfima_breakhar_nominal_sig_05": _count(
            lambda r: r["focal"] and r["p_hac"] < 0.05),
        "focal_arfima_breakhar_bh_sig_05": _count(
            lambda r: r["focal"] and r["corrections"]["focal_10"]["sig_bh_05"]),
        "n_sign_reversals_arfima": sum(1 for r in reversal if r["sign_reversal"]),
        "hac_changed_significance_at_05": [
            {"asset": r["asset"], "loss": r["loss"], "model": r["model"],
             "p_degenerate": r["p_original_degenerate_no_hac"], "p_hac": r["p_hac"],
             "loss_diff_acf1": r["loss_diff_acf1"]}
            for r in dm_rows
            if (r["p_original_degenerate_no_hac"] < 0.05) != (r["p_hac"] < 0.05)
        ],
        # Empirical demonstration, on this very dataset, that omitting HAC is a
        # TWO-SIDED misspecification -- the repo rule states it, these rows show it.
        "hac_is_two_sided": {
            "n_abs_t_shrunk": _count(lambda r: r["abs_t_change_from_hac"] < 0),
            "n_abs_t_grew": _count(lambda r: r["abs_t_change_from_hac"] > 0),
            "all_negative_acf1_rows_grew": all(
                r["abs_t_change_from_hac"] > 0 for r in dm_rows if r["loss_diff_acf1"] < 0),
            "examples_grew_negative_acf1": [
                {"cell": f'{r["asset"]}/{r["loss"]}/{r["model"]}',
                 "acf1": round(r["loss_diff_acf1"], 3),
                 "abs_t_degenerate": round(abs(r["t_original_degenerate_no_hac"]), 2),
                 "abs_t_hac": round(abs(r["t_hac_hln"]), 2)}
                for r in dm_rows if r["loss_diff_acf1"] < 0
            ],
            "note": "Rows with negative loss-differential acf(1) all see |t| INCREASE under "
                    "HAC; rows with strongly positive acf(1) see |t| decrease. A reviewer "
                    "cannot assume a missing HAC correction only ever inflates significance.",
        },
    }

    payload = {
        "experiment_id": "k1623_rev2",
        "title": "K1623 rev2 — retract the identification claim; add MSE DM tests "
                 "and multiple-comparison correction",
        "supersedes": "k1623_results.json (inference and claims revised; the forecasting code "
                      "is byte-identical and the reproduced AGGREGATE losses match to 1e-9 for "
                      "the 4 exact-pin assets -- see reproduction_guard.scope_and_limits for "
                      "what that does and does not establish, and note TW0050 is a near-"
                      "replication on revised upstream history, not an exact one)",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "reproduction_guard": {
            "checked_cells": len(K.ASSETS) * len(MODELS) * 4,
            "exactly_reproduced_assets": [k for k, v in vintage_report.items() if v["exact"]],
            "near_replicated_assets": [k for k, v in vintage_report.items() if not v["exact"]],
            "max_relative_deviation_exact_assets": repro_max_rel,
            "tolerance": 1e-9,
            "per_asset_vintage": vintage_report,
            "note": "For the 4 exact-pin assets, all four stored functionals (qlike_mean, "
                    "qlike_median, mse, clip_hit_rate) reproduce k1623_results.json to 1e-9. "
                    "Assets under near_replicated_assets had their cached history revised "
                    "upstream and are disclosed, not forced to match.",
            "scope_and_limits": {
                "what_is_checked": "Four aggregate functionals per model per asset: two loss "
                                   "moments (qlike_mean, mse), a median (qlike_median, robust "
                                   "to the tail that dominates MSE), and the forecast-guard hit "
                                   "count (clip_hit_rate).",
                "what_is_NOT_checked": "Per-period forecast vectors. The original artifact "
                                       "NEVER STORED THEM, so a pointwise comparison against it "
                                       "is impossible -- not merely omitted.",
                "therefore": "The defensible claim is 'the reproduced aggregate losses are "
                             "identical', NOT 'the forecasts are identical'. Agreement of four "
                             "independent functionals to 1e-9 is strong EVIDENCE the forecast "
                             "paths coincide; it is not proof.",
                "tw0050_exception": "TW0050 is excluded from the assertion entirely and is "
                                    "measured instead (n 4263 -> 4264, max relative deviation "
                                    "2.5e-3). Any statement of the form 'same forecasts, same "
                                    "sample' is FALSE for TW0050 and must not be made.",
            },
            "data_vintage_pinned": {
                "reason": "price_cache.db has advanced ~10 trading days since the original "
                          "run (to 2026-07-17). The trailing-750 OOS window would slide, "
                          "confounding 'the test was fixed' with 'the sample moved'.",
                "pinned_end_dates": {a[2]: orig["assets"][a[2]]["period"][1] for a in K.ASSETS},
                "consequence": "rev2 t-statistics are like-for-like revisions of the original "
                               "ones. They are NOT an updated-sample result.",
            },
        },
        "inference_method": {
            "primary": "volpred.stats.model_evaluation.dm_test (Newey-West HAC, "
                       "bandwidth = max(1, ceil(h^(1/3) n^(1/3)))), h=1",
            "hln": "Harvey-Leybourne-Newbold multiplier reported as t_hac_hln; at h=1, "
                   "n=749 the factor is ~0.9993 and is immaterial.",
            "hln_p_asymmetry_disclosed": "p_hac -- the value fed to BH/Bonferroni -- corresponds "
                                         "to t_hac, NOT to t_hac_hln. The HLN-implied p is "
                                         "published alongside as p_hac_hln so the gap is "
                                         "checkable: it appears in the 4th decimal (e.g. "
                                         "VIX/QLIKE/ARFIMA 0.08822 vs 0.08843) and changes no 5% "
                                         "verdict and no BH outcome. Disclosed rather than left "
                                         "for a reader to find.",
            "hac_estimator_caveats": "The canonical dm_test normalises gamma0 by n but gamma_l "
                                     "by (n - lag), which is a valid variant but not the "
                                     "textbook finite-sample Newey-West form (common 1/n). "
                                     "Recomputing VIX/QLIKE/ARFIMA with a common 1/n gives "
                                     "t = 1.70601 vs the reported 1.70711 -- immaterial here. "
                                     "dm_test also returns (0.0, 1.0) if the estimated long-run "
                                     "variance is non-positive, which would disguise estimator "
                                     "failure as a perfectly insignificant result; VERIFIED that "
                                     "this branch is not triggered by any of the 40 rows.",
            "superseded": "k1623.dm_hln used `for lag in range(1, h)`, which at h=1 is an "
                          "EMPTY loop -> no HAC correction. That site is frozen in "
                          "storage/ops/dm_hac_lag_baseline.json under degenerate_sites. "
                          "Its statistics are retained per row as "
                          "t_original_degenerate_no_hac for audit.",
            "multiple_comparison": "BH FDR (primary) and Bonferroni (secondary). PRIMARY FAMILY "
                                   "IS PRE-SPECIFIED IN CODE as within_loss_20 (corrections "
                                   "applied separately within QLIKE and within MSE, each of size "
                                   "20); every README conclusion uses BH at that family. "
                                   "CORRECTION TO EARLIER WORDING: this is FIVE nested "
                                   "hypothesis sets, not 'three explicit families' -- QLIKE-20, "
                                   "MSE-20, QLIKE-focal-10, MSE-focal-10, pooled-40, where each "
                                   "focal_10 is a SUBSET of its within_loss_20 and pooled_40 is "
                                   "the union. The non-primary sets are reported as sensitivity, "
                                   "not as a menu: zero focal comparisons survive BH in ANY of "
                                   "them, so the conclusion does not depend on the choice.",
        },
        "headline_finding": {
            "statement": "Under QLIKE, HAR has the lower mean loss against ARFIMA in 4 of 5 "
                         "assets. Under MSE, ARFIMA has the lower mean loss in 4 of 5 assets, "
                         "by 11-16%. Same forecasting code, same models, same forecasts scored "
                         "two ways (for the 4 exact-pin assets the reproduced aggregate losses "
                         "match the original to 1e-9; TW0050 is a near-replication on revised "
                         "upstream history) -- the model "
                         "ranking flips with the loss function in 3 of 5 assets. But under "
                         "canonical HAC inference NEITHER loss makes the ARFIMA-vs-HAR "
                         "difference statistically significant after multiple-comparison "
                         "correction, so the defensible conclusion is that the two are "
                         "indistinguishable and that reporting a single loss would have "
                         "manufactured a directional conclusion in either direction.",
            "what_this_is_not": "This is NOT a finding that ARFIMA beats HAR under MSE. No "
                                "ARFIMA-vs-HAR MSE comparison is significant even nominally "
                                "(p in [0.265, 0.974]), and NO MSE comparison of any kind "
                                "survives BH or Bonferroni. (Precision matters here: 2 of the 20 "
                                "MSE comparisons ARE nominally significant at 5% -- both against "
                                "the deliberately naive EWMA baseline -- so the blanket phrasing "
                                "'no MSE comparison reaches significance' would be wrong.) It is "
                                "a methodological result about loss-function dependence of "
                                "model rankings.",
            "verifiable_from": "loss_function_sign_reversal[] and dm_comparisons[] below.",
        },
        "per_asset": per_asset,
        "dm_comparisons": dm_rows,
        "loss_function_sign_reversal": reversal,
        "summary": summary,
        "retracted_claims": build_retractions(orig, dm_rows, reversal, summary),
        "residual_limitations": RESIDUAL_LIMITATIONS,
        "total_runtime_sec": round(time.time() - t_start, 2),
    }
    atomic_write_json(OUT, payload)
    print(f"\nwrote {OUT.name}  ({payload['total_runtime_sec']}s)")
    print(f"reproduction: max rel dev = {repro_max_rel:.3e} over "
          f"{payload['reproduction_guard']['checked_cells']} cells")
    print(f"sign reversals (ARFIMA, QLIKE vs MSE): {summary['n_sign_reversals_arfima']}/5")
    print(f"nominal sig: {summary['nominal_sig_05']}  |  BH: {summary['bh_sig_05_within_loss']}")


RESIDUAL_LIMITATIONS = [
    {
        "id": "identification_not_restored",
        "text": "This round RETRACTS the identification claim; it does not replace it. "
                "Testing genuine vs spurious long memory needs a test built for a random / "
                "dense shift process -- Qu (2011) score test, Shimotsu (2006) splitting, or "
                "Perron-Qu (2010). None is implemented here. The surviving demeaned d-hat is "
                "descriptive only.",
    },
    {
        "id": "generated_regressor_se",
        "text": "Demeaned d-hat SEs are the raw ELW asymptotic 1/(2 sqrt(m)). They do NOT "
                "account for the break dates being ESTIMATED, so they are a LOWER BOUND on "
                "the true sampling uncertainty. The Monte Carlo in k1623_rev2_mc.py quantifies "
                "the gap but is not a substitute for a correct analytic SE.",
    },
    {
        "id": "elw_is_sample_mean_demeaned",
        "text": "The ELW implementation demeans by the SAMPLE MEAN, not the Shimotsu-Phillips "
                "mu-hat(d) weighted mean. For VIX (d-hat = 0.723 > 0.5, non-stationary region) "
                "the sample mean is not a valid level estimator, so VIX d-hat is the least "
                "trustworthy of the five.",
    },
    {
        "id": "fd_maxk_binding",
        "text": "FD_MAXK = 2000 truncates the fractional-difference filter. With n = 2,565-4,655 "
                "the truncation BINDS for every asset, and it bites hardest where d is largest "
                "(VIX), because the neglected weight tail decays as k^(-d-1).",
    },
    {
        "id": "vix_permissive_cap_binding",
        "text": "VIX selected 15 of a maximum 15 permissive breaks. The cap binds, so the "
                "20.3% permissive level-shift share is NOT an upper bound for VIX -- allowing "
                "more breaks could push it higher. The bracket is open-ended on that side.",
    },
    {
        "id": "no_tradability_test",
        "text": "No strategy, transaction-cost or utility evaluation was run in any round. "
                "This experiment takes no position on tradability.",
    },
    {
        "id": "range_proxy",
        "text": "RV proxy is a daily Parkinson high-low range (intraday history is ~115 days, "
                "too short). Measurement error affects the LEVEL of d-hat.",
    },
    {
        "id": "one_step_only",
        "text": "OOS is one-step. h=5/22 with overlapping-forecast HAC is untested.",
    },
    {
        "id": "tw0050_near_replication",
        "text": "TW0050 is a NEAR-replication, not an exact one. Its cached history was REVISED "
                "upstream (not merely extended): at the pinned end date one formerly degenerate "
                "high==low row now has high > low and is retained, so n is 4264 vs the original "
                "4263. Max relative deviation from the original summary statistics is 2.5e-3. "
                "Statements of the form 'same forecasts, same sample' are FALSE for TW0050.",
    },
    {
        "id": "temporary_spikes_not_removed",
        "text": "Piecewise-mean demeaning removes permanent LEVEL shifts only. It cannot remove "
                "TEMPORARY spikes such as VIX during the GFC and COVID, so part of VIX's high "
                "d-hat may reflect a few extreme episodes rather than smooth long memory.",
    },
    {
        "id": "cross_asset_diagnostic_only",
        "text": "Cross-asset figures are diagnostic. Asset-days are never pooled, because "
                "same-date cross-asset loss differentials share market-wide shocks and stacking "
                "them would understate standard errors (repo rule: no asset-day iid pooling).",
    },
]


def build_retractions(orig: dict, dm_rows: list[dict], reversal: list[dict],
                      summary: dict) -> list[dict]:
    """Explicit before/after ledger. Every 'after' figure is computed above."""
    arfima_mse_wins = [r["asset"] for r in reversal if r["mse_winner"] == "model"]
    mse_ratios = {r["asset"]: round(r["mse_ratio_arfima_over_har"], 4) for r in reversal}
    focal_q_nominal = [f'{r["asset"]}/{r["model"]} (p={r["p_hac"]:.4f})' for r in dm_rows
                       if r["loss"] == "QLIKE" and r["focal"] and r["p_hac"] < 0.05]
    nonfocal_q_nominal = [f'{r["asset"]}/{r["model"]}' for r in dm_rows
                          if r["loss"] == "QLIKE" and not r["focal"] and r["p_hac"] < 0.05]
    mse_p_range = [round(min(r["p_hac"] for r in dm_rows
                             if r["loss"] == "MSE" and r["model"] == "ARFIMA"), 4),
                   round(max(r["p_hac"] for r in dm_rows
                             if r["loss"] == "MSE" and r["model"] == "ARFIMA"), 4)]
    return [
        {
            "claim_id": "genuine_long_memory_identified",
            "where": "README.md Verdict line, §6.2 '純 level-shift 假象假說被拒絕', §7",
            "before": "All assets retain a significant d-hat after break-demeaning, therefore "
                      "the pure level-shift (Diebold-Inoue) hypothesis is REJECTED and a "
                      "genuine long-memory component is present.",
            "after": "Break-demeaned d-hat stays positive (BIC 0.46-0.65; permissive "
                     "0.19-0.58). This is DESCRIPTIVE residual persistence. It does not "
                     "reject Diebold-Inoue.",
            "basis": "Diebold-Inoue's DGP is a RANDOM, potentially dense shift process. "
                     "Removing <=5 (permissive <=15) DETERMINISTIC Bai-Perron mean breaks "
                     "cannot subtract it, so surviving d-hat > 0 is not evidence against it. "
                     "No identification theorem licenses the inference. Compounding this, the "
                     "demeaned SEs ignore that the break dates were estimated.",
            "status": "RETRACTED",
        },
        {
            "claim_id": "not_tradable",
            "where": "README.md Verdict line '不可交易', §6.3 heading, §7",
            "before": "The genuine long-memory component is 'not tradable'.",
            "after": "Removed. No strategy, cost or utility test was run, so the experiment "
                     "takes no position on tradability. The defensible statement is narrower: "
                     "under QLIKE, neither ARFIMA nor BreakRobustHAR beat HAR one step ahead.",
            "basis": "Pure rhetoric -- zero supporting computation existed in any round.",
            "status": "RETRACTED",
        },
        {
            "claim_id": "significantly_worse_in_several_places",
            "where": "README.md §3 differentiation paragraph, §6.3 '多處反而顯著更差'",
            "before": "ARFIMA / break-robust models are 'significantly worse in several "
                      "places' than HAR.",
            "after": f"The claim concerns ARFIMA / BreakRobustHAR. Of those 10 QLIKE "
                     f"comparisons, {len(focal_q_nominal)} is nominally significant at 5% under "
                     f"canonical HAC ({', '.join(focal_q_nominal) or 'none'}), and "
                     f"{summary['focal_arfima_breakhar_bh_sig_05']} survive BH FDR under any "
                     f"family definition tried. 'Several places' is therefore wrong; the correct "
                     f"statement is 'one nominally significant comparison, which does not "
                     f"survive multiple-comparison correction'. For completeness, the "
                     f"significant QLIKE comparisons in the wider 20-comparison family are all "
                     f"against the deliberately naive baselines "
                     f"({', '.join(nonfocal_q_nominal)}) -- HAR beating AR(1) and EWMA is not "
                     f"the contested claim.",
            "basis": "Recount against the current results table with HAC-corrected inference "
                     "and an explicit multiple-comparison family (repo rule: uniqueness / "
                     "count claims must be re-verified after any inference retrofit).",
            "status": "RETRACTED",
        },
        {
            "claim_id": "both_losses_tested",
            "where": "README.md §4.5 'Loss：QLIKE + MSE，報 mean 與 median。DM + HLN'",
            "before": "Implies DM tests were run on both QLIKE and MSE.",
            "after": f"DM was run on QLIKE ONLY. Under MSE, ARFIMA's point estimate beats HAR "
                     f"in {len(arfima_mse_wins)} of 5 assets ({', '.join(arfima_mse_wins)}), "
                     f"MSE ratios {mse_ratios} -- i.e. 11-16% lower. The omitted loss reverses "
                     f"the model RANKING in "
                     f"{sum(1 for r in reversal if r['sign_reversal'])} of 5 assets. "
                     f"IMPORTANT and stated plainly: not one ARFIMA-vs-HAR MSE comparison is "
                     f"statistically significant (p in {mse_p_range}), so this is a reversal of "
                     f"the point-estimate ordering, NOT evidence that ARFIMA beats HAR under "
                     f"MSE. The honest reading is that the two models are statistically "
                     f"indistinguishable under both losses, while a reader who saw only one "
                     f"loss table would draw opposite conclusions about which model is better. "
                     f"MSE on variance-level data is dominated by a few extreme observations, "
                     f"which is why an 11-16% mean gap still carries a large standard error.",
            "basis": "Direct inspection of k1623.run_oos: dm_vs_HAR is built from the QLIKE "
                     "loss vector only. MSE was stored as a summary mean and never tested.",
            "status": "CORRECTED (omission repaired in this round)",
        },
        {
            "claim_id": "elw_is_shimotsu_phillips",
            "where": "README.md §4.2, §9 headline",
            "before": "ELW described as 'Shimotsu-Phillips, estimates non-stationary d'.",
            "after": "The implementation demeans by the SAMPLE MEAN; it does not use the "
                     "Shimotsu-Phillips unknown-mean mu-hat(d) weighted estimator. It is "
                     "'ELW with sample-mean demeaning'. For VIX (d-hat > 0.5) the sample mean "
                     "is not a valid level estimator.",
            "basis": "k1623.local_whittle(exact=True) computes xd = x - mean(x) once, then "
                     "optimises only over d.",
            "status": "CORRECTED (method description)",
        },
        {
            "claim_id": "shift_share_upper_bound",
            "where": "README.md §6.2 bracket column, §7 caveat 3",
            "before": "VIX level-shift contribution bracketed at [11%, 20%], the upper end "
                      "described as an upper bound.",
            "after": "VIX selected 15 of a maximum 15 permissive breaks -- the cap BINDS, so "
                     "20.3% is not an upper bound. The VIX bracket is open-ended above. "
                     "The other four assets selected 10-13 of 15 and are unaffected.",
            "basis": "k1623_results.json: VIX n_breaks_selected = 15 = max_breaks_cap.",
            "status": "CORRECTED (bound downgraded)",
        },
        {
            "claim_id": "breakrobust_har_window",
            "where": "README.md §4.5 'BreakRobustHAR（只用最近 latest-break 之後樣本 refit）'",
            "before": "BreakRobustHAR refits HAR on the post-latest-break sample only.",
            "after": "k1623.py:475 sets wstart = max(0, min(brk_start, i-22-60)), which "
                     "deliberately pushes the window START BACK BEFORE the break when the "
                     "break is too recent (to keep >=60 usable rows); with no detected break "
                     "it falls back to a trailing 750 window. The description is corrected to "
                     "match the code; the code is unchanged, so all numbers stand.",
            "basis": "Direct code read. Option (i) of the brief: fix the description, not the "
                     "code, because this round is about claims vs evidence.",
            "status": "CORRECTED (description aligned to code)",
        },
        {
            "claim_id": "dm_inference_no_hac",
            "where": "k1623.py dm_hln, all t-statistics in README §6.3",
            "before": "DM t-statistics computed with `for lag in range(1, h)`, which at h=1 "
                      "applies NO HAC correction.",
            "after": "All rev2 inference uses canonical dm_test (Newey-West, bandwidth "
                     "ceil(n^(1/3))). Per-row t_original_degenerate_no_hac retains the old "
                     "statistic. Comparisons whose 5% verdict changed: "
                     f"{len(summary['hac_changed_significance_at_05'])}.",
            "basis": ".claude/rules/experiments.md 'DM 的 HAC 落後期不可只用 h-1'; the site is "
                     "already frozen in storage/ops/dm_hac_lag_baseline.json degenerate_sites. "
                     "Omitting HAC is two-sided: it can inflate OR deflate |t| depending on the "
                     "sign of the loss-differential autocovariance (see loss_diff_acf1).",
            "status": "CORRECTED (inference upgraded)",
        },
    ]


if __name__ == "__main__":
    main()
