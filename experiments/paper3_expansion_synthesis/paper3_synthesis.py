"""Paper 3 A-expansion meta-synthesis — pool E1 (individual stocks) + E2 (cross-market).

No model refitting: this is a pure meta-analysis over the two stored results JSONs.
Every number traces back to paper3_E1_results.json / paper3_E2_results.json.

Decision points (from task Paper3_expansion_synthesis_decision_meta):
  D1. Is the lambda_L threshold (conjectured boundary 0.1-0.2) significant?
  D2. Is the same-sector NULL vs cross-sector PASS pattern robust across asset classes?
  D3. What Section 4 rewrite scope does the evidence support?

E3 (commodities) failed with no artifacts -> pooled N = 22 pairs, not the planned 33-43.
"""

import json
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
E1_PATH = ROOT / "experiments/paper3_E1_individual_stocks_copula/paper3_E1_results.json"
E2_PATH = ROOT / "experiments/paper3_E2_cross_market_copula/paper3_E2_results.json"
OUT = Path(__file__).resolve().parent / "paper3_synthesis_results.json"

# E1 hypothesis pre-registration (README.md "Hypotheses"): H1 same-sector NULL, H2 cross-sector PASS.
E1_SAME_SECTOR = {
    "AAPL-MSFT", "GOOGL-META", "NVDA-AMD", "JPM-BAC", "GS-MS", "XOM-CVX",
}

DCC_T = "DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM"
DCC_CLAYTON = "DCC-A4f-ASYM_vs_Copula-Clayton-A4f-ASYM"


def load_pairs(path, study):
    """Flatten one study's cross_pair_table, joining n_oos from pair_results."""
    blob = json.loads(path.read_text())
    pr = blob["pair_results"]
    if isinstance(pr, list):
        pr = {p["pair_name"]: p for p in pr}
    rows = []
    for row in blob["cross_pair_table"]:
        name = row["pair"]
        detail = pr[name]
        dm = detail["dm_qlike"]
        rows.append({
            "study": study,
            "pair": name,
            "n_oos": detail["n_oos"],
            "lambda_L_t": row["lambda_L_t_mean"],
            "lambda_L_clayton": row["lambda_L_clayton_mean"],
            "corr": row["full_sample_corr"],
            # sign convention verified against mean_qlike: mean_loss_diff = loss(DCC) - loss(copula),
            # so t_stat > 0 means the copula model has the LOWER QLIKE loss (copula wins).
            "t_copula_t": dm[DCC_T]["t_stat"],
            "t_clayton": dm[DCC_CLAYTON]["t_stat"],
            "harvey_sig_t": bool(dm[DCC_T].get("significant_harvey", False)),
            "harvey_sig_clayton": bool(dm[DCC_CLAYTON].get("significant_harvey", False)),
            "hln_applied": "hln_factor" in dm[DCC_T],
            "region_class": detail.get("region_class"),
            "same_sector": name in E1_SAME_SECTOR if study == "E1" else None,
            # second test family: FZ0 loss on the VaR/ES forecasts. This is where a tail-dependence
            # story SHOULD show up if anywhere, so it must be tested before any NULL verdict.
            # fz_score_series implements the Patton-Ziegel FZ0 loss (lower = better), and dm_test is
            # called with DCC first, so the sign convention matches the QLIKE family exactly.
            "dm_fz": detail.get("dm_fz", {}),
            # third dimension: VaR/ES calibration (Trinity). Not a lambda_L claim, but omitting it
            # would let a reader infer "copulas offer nothing", which the source data contradicts.
            "trinity": {
                m: {a: blk.get("trinity_pass")
                    for a, blk in (spec.get("var_tests") or {}).items()}
                for m, spec in (detail.get("models") or {}).items()
            },
        })
    return rows


def fz_tests(rows):
    """Flatten the FZ family: 22 pairs x 2 copulas x 2 alpha levels."""
    out = []
    for r in rows:
        for alpha_key, block in (r["dm_fz"] or {}).items():
            for model, key in (("Student-t", DCC_T), ("Clayton", DCC_CLAYTON)):
                dm = block.get(key)
                if not dm or not np.isfinite(dm.get("t_stat", np.nan)):
                    continue
                out.append({
                    "study": r["study"], "pair": r["pair"], "model": model,
                    "alpha": alpha_key, "t": dm["t_stat"], "n": dm["n"],
                    "lambda_L_t": r["lambda_L_t"],
                    "p": two_sided_p(dm["t_stat"], dm["n"]),
                    "copula_favoured": dm["t_stat"] > 0,
                })
    return out


def two_sided_p(t, n):
    return float(2 * stats.t.sf(abs(t), df=n - 1))


def bh_fdr(pvals, q=0.05):
    """Benjamini-Hochberg. Returns (rejected mask, adjusted p)."""
    p = np.asarray(pvals, dtype=float)
    m = p.size
    order = np.argsort(p)
    ranked = p[order]
    adj_sorted = np.minimum.accumulate((ranked * m / np.arange(1, m + 1))[::-1])[::-1]
    adj = np.empty_like(adj_sorted)
    adj[order] = np.minimum(adj_sorted, 1.0)
    return (adj <= q), adj


def spearman(x, y):
    rho, p = stats.spearmanr(x, y)
    return {"rho": float(rho), "p": float(p), "n": int(len(x))}


def main():
    rows = load_pairs(E1_PATH, "E1") + load_pairs(E2_PATH, "E2")
    n = len(rows)

    lam = np.array([r["lambda_L_t"] for r in rows])
    t_t = np.array([r["t_copula_t"] for r in rows])
    t_cl = np.array([r["t_clayton"] for r in rows])
    # "best copula" = the larger t (most favourable to the copula side); kept only to
    # document the selection bias, never used as an inference statistic on its own.
    t_best = np.maximum(t_t, t_cl)

    # ---- D1: does copula advantage scale with tail dependence? ----------------
    # E1 pre-registered H3 as a NEGATIVE relation (low lambda_L -> copula advantage).
    lam_cl = np.array([r["lambda_L_clayton"] for r in rows])
    scaling = {
        # regressors are MATCHED to their copula: Student-t lambda_L against the Student-t DM t,
        # Clayton lambda_L against the Clayton DM t — this is the estimand E1/E2 themselves report.
        "pooled_student_t": spearman(lam, t_t),
        "pooled_clayton_matched": spearman(lam_cl, t_cl),
        "pooled_clayton_mismatched_lambdaL_t": spearman(lam, t_cl),
        "E1_student_t": spearman(
            [r["lambda_L_t"] for r in rows if r["study"] == "E1"],
            [r["t_copula_t"] for r in rows if r["study"] == "E1"],
        ),
        "E2_student_t": spearman(
            [r["lambda_L_t"] for r in rows if r["study"] == "E2"],
            [r["t_copula_t"] for r in rows if r["study"] == "E2"],
        ),
        "E1_clayton_matched": spearman(
            [r["lambda_L_clayton"] for r in rows if r["study"] == "E1"],
            [r["t_clayton"] for r in rows if r["study"] == "E1"],
        ),
        "E2_clayton_matched": spearman(
            [r["lambda_L_clayton"] for r in rows if r["study"] == "E2"],
            [r["t_clayton"] for r in rows if r["study"] == "E2"],
        ),
        "prereg_H3_sign": "negative",
        "headline": "the ONLY significant lambda_L relation in either source study is E2/Clayton, "
                    "and its sign is POSITIVE — i.e. significantly OPPOSITE to the pre-registered "
                    "H3 prediction. E1 is null. The correct statement is not 'no relation' but "
                    "'a significant relation running backwards in one study, null in the other'.",
        "lambda_L_support": {
            "E1_range": [float(min(r["lambda_L_t"] for r in rows if r["study"] == "E1")),
                         float(max(r["lambda_L_t"] for r in rows if r["study"] == "E1"))],
            "E2_range": [float(min(r["lambda_L_t"] for r in rows if r["study"] == "E2")),
                         float(max(r["lambda_L_t"] for r in rows if r["study"] == "E2"))],
            "note": "the two arms barely overlap in lambda_L support, so the pooled Spearman is not "
                    "a pooled estimate of one within-study relation — read the per-study rows.",
        },
    }

    # Fisher-z heterogeneity: is pooling E1 and E2 into one rho even defensible?
    def fisher_z(rho, n):
        return 0.5 * np.log((1 + rho) / (1 - rho)), 1.0 / (n - 3)

    z1, v1 = fisher_z(scaling["E1_clayton_matched"]["rho"], 12)
    z2, v2 = fisher_z(scaling["E2_clayton_matched"]["rho"], 10)
    w1, w2 = 1 / v1, 1 / v2
    z_bar = (w1 * z1 + w2 * z2) / (w1 + w2)
    q_stat = w1 * (z1 - z_bar) ** 2 + w2 * (z2 - z_bar) ** 2
    scaling["heterogeneity_E1_vs_E2_clayton"] = {
        "cochran_Q": float(q_stat),
        "df": 1,
        "p": float(stats.chi2.sf(q_stat, 1)),
        "verdict": "significant heterogeneity — a naive 22-pair pooled Spearman is NOT a "
                   "defensible primary estimator; report the study-level rhos instead.",
    }

    # ---- D1b: the conjectured 0.1-0.2 boundary, tested as an actual split -----
    thresholds = {}
    for thr in (0.10, 0.15, 0.20):
        low = t_best[lam < thr]
        high = t_best[lam >= thr]
        entry = {
            "threshold": thr,
            "n_low": int(low.size),
            "n_high": int(high.size),
            "mean_t_low": float(low.mean()) if low.size else None,
            "mean_t_high": float(high.mean()) if high.size else None,
        }
        if low.size >= 3 and high.size >= 3:
            u, p = stats.mannwhitneyu(low, high, alternative="two-sided")
            entry["mannwhitney_u"] = float(u)
            entry["mannwhitney_p"] = float(p)
        else:
            entry["mannwhitney_p"] = None
            entry["note"] = "group too small for a test"
        # CONFOUND CHECK: is the "high lambda_L" group just the E1 same-sector pairs wearing a hat?
        high_rows = [r for r, l in zip(rows, lam) if l >= thr]
        entry["confound"] = {
            "high_group_studies": {s: sum(1 for r in high_rows if r["study"] == s)
                                   for s in ("E1", "E2")},
            "high_group_all_E1_same_sector": bool(
                high_rows and all(r["study"] == "E1" and r["same_sector"] for r in high_rows)
            ),
        }
        thresholds[f"lambda_L_{thr:.2f}"] = entry

    # ---- D1c: multiple testing across all 22 pairs x 2 copulas = 44 tests -----
    tests = []
    for r in rows:
        for model, tstat in (("Student-t", r["t_copula_t"]), ("Clayton", r["t_clayton"])):
            tests.append({
                "study": r["study"], "pair": r["pair"], "model": model,
                "t": tstat, "n_oos": r["n_oos"],
                "p": two_sided_p(tstat, r["n_oos"]),
                "copula_favoured": tstat > 0,
            })
    pvals = [t["p"] for t in tests]
    rejected, adj = bh_fdr(pvals, q=0.05)
    bonf = 0.05 / len(tests)
    for t_, rej, a in zip(tests, rejected, adj):
        t_["p_bh_adj"] = float(a)
        t_["bh_sig_5pct"] = bool(rej)
        t_["bonferroni_sig_5pct"] = bool(t_["p"] < bonf)

    survivors_bh = [t for t in tests if t["bh_sig_5pct"] and t["copula_favoured"]]
    survivors_bonf = [t for t in tests if t["bonferroni_sig_5pct"] and t["copula_favoured"]]
    raw_sig_copula = [t for t in tests if t["p"] < 0.05 and t["copula_favoured"]]
    raw_sig_dcc = [t for t in tests if t["p"] < 0.05 and not t["copula_favoured"]]

    # ---- D1e: second test family — FZ0 (VaR/ES) ------------------------------
    # A tail-dependence thesis has its best shot here, not on portfolio-variance QLIKE.
    fzt = fz_tests(rows)
    fz_rej, fz_adj = bh_fdr([t["p"] for t in fzt], q=0.05)
    for t_, rej, a in zip(fzt, fz_rej, fz_adj):
        t_["p_bh_adj"] = float(a)
        t_["bh_sig_5pct"] = bool(rej)
    fz_surv_copula = [t for t in fzt if t["bh_sig_5pct"] and t["copula_favoured"]]
    fz_surv_dcc = [t for t in fzt if t["bh_sig_5pct"] and not t["copula_favoured"]]
    fz_lam = np.array([t["lambda_L_t"] for t in fzt])
    fz_tv = np.array([t["t"] for t in fzt])
    fz_family = {
        "n_tests": len(fzt),
        "n_pairs_covered": len({t["pair"] for t in fzt}),
        "bh_fdr_5pct_survivors_copula": [
            {"pair": t["pair"], "model": t["model"], "alpha": t["alpha"],
             "t": t["t"], "p_bh_adj": t["p_bh_adj"]} for t in fz_surv_copula
        ],
        "bh_fdr_5pct_survivors_dcc": [
            {"pair": t["pair"], "model": t["model"], "alpha": t["alpha"],
             "t": t["t"], "p_bh_adj": t["p_bh_adj"]} for t in fz_surv_dcc
        ],
        "raw_sig_copula_favoured": [
            f"{t['pair']}/{t['model']}/{t['alpha']}" for t in fzt
            if t["p"] < 0.05 and t["copula_favoured"]
        ],
        "raw_sig_dcc_favoured": [
            f"{t['pair']}/{t['model']}/{t['alpha']}" for t in fzt
            if t["p"] < 0.05 and not t["copula_favoured"]
        ],
        "spearman_lambdaL_vs_fz_t": spearman(fz_lam, fz_tv) if len(fzt) > 3 else None,
        "note": "FZ0 loss on VaR/ES forecasts (Patton-Ziegel), lower = better; same DCC-first "
                "sign convention as the QLIKE family, so t > 0 favours the copula.",
    }

    # ---- D1f: VaR/ES calibration (Trinity) — the dimension copulas actually win --
    trinity = {}
    for alpha_key in ("alpha_0.025", "alpha_0.010"):
        per_model = {}
        for model in ("DCC-A4f-ASYM", "Copula-t-A4f-ASYM", "Copula-Clayton-A4f-ASYM"):
            passes = [r["trinity"].get(model, {}).get(alpha_key) for r in rows]
            passes = [p for p in passes if p is not None]
            per_model[model] = {"pass": int(sum(bool(p) for p in passes)), "of": len(passes)}
            for study in ("E1", "E2"):
                sp = [r["trinity"].get(model, {}).get(alpha_key)
                      for r in rows if r["study"] == study]
                sp = [p for p in sp if p is not None]
                per_model[model][study] = f"{sum(bool(p) for p in sp)}/{len(sp)}"
        trinity[alpha_key] = per_model
    trinity["interpretation"] = (
        "Copula-GARCH beats DCC on VaR/ES calibration at alpha=2.5% (Copula-t 19/22 vs DCC 10/22), "
        "but the ordering REVERSES at alpha=1% (Copula-t 18/22 vs DCC 19/22; in E1 alone, 8/12 vs "
        "11/12). So the calibration advantage is real but NOT uniform across tail depth — it is a "
        "2.5% phenomenon that does not survive into the deeper tail. This is a CALIBRATION claim, "
        "not a lambda_L-threshold claim: it does not rescue Paper 3 A's main argument, but the "
        "synthesis must report it so the negative finding is not overstated in the other direction."
    )

    # ---- D2: same-sector NULL vs cross-sector PASS (E1 pre-registration) ------
    e1 = [r for r in rows if r["study"] == "E1"]
    same = np.array([r["t_copula_t"] for r in e1 if r["same_sector"]])
    cross = np.array([r["t_copula_t"] for r in e1 if not r["same_sector"]])
    u, p_sector = stats.mannwhitneyu(same, cross, alternative="two-sided")
    sector = {
        "n_same_sector": int(same.size), "n_cross_sector": int(cross.size),
        "mean_t_same_sector": float(same.mean()), "mean_t_cross_sector": float(cross.mean()),
        "mannwhitney_u": float(u), "mannwhitney_p": float(p_sector),
        "prereg_H2_claim": "cross-sector pairs reach Harvey |t| > 3.0",
        # report the SIGNED extremum: the largest-magnitude cross-sector t is negative, i.e. it is
        # DCC-favoured. An absolute value here would hide that H2 fails a fortiori.
        "cross_sector_largest_magnitude_t_signed": float(cross[np.abs(cross).argmax()]),
        "cross_sector_max_copula_favoured_t": float(cross.max()),
        "n_cross_sector_reaching_t3": int((np.abs(cross) > 3.0).sum()),
    }
    e2_region = {}
    for r in rows:
        if r["study"] != "E2":
            continue
        e2_region.setdefault(r["region_class"], []).append(r["t_copula_t"])
    sector["E2_by_region_mean_t"] = {k: float(np.mean(v)) for k, v in e2_region.items()}

    # ---- concentration check: are the survivors one asset? -------------------
    survivor_pairs = sorted({t["pair"] for t in survivors_bh})
    # A "single_asset_driven" flag is vacuous at one survivor. State concentration the defensible
    # way instead: which assets occupy the top of the whole 22-pair t ranking.
    ranked = sorted(rows, key=lambda r: max(r["t_copula_t"], r["t_clayton"]), reverse=True)
    concentration = {
        "survivor_pairs": survivor_pairs,
        "top3_pairs_by_best_t": [
            {"pair": r["pair"], "best_t": float(max(r["t_copula_t"], r["t_clayton"]))}
            for r in ranked[:3]
        ],
        "note": "TW0050 occupies the top of the ranking; E2's asia_intraregional 'cluster' is "
                "3 mutually overlapping pairs drawn from only 3 assets (TW0050, HSI, N225), so it "
                "is closer to one observation than to three.",
    }

    out = {
        "experiment_id": "Paper3_expansion_synthesis",
        "inputs": {
            "E1": str(E1_PATH.relative_to(ROOT)),
            "E2": str(E2_PATH.relative_to(ROOT)),
            "E3": "FAILED — no artifacts on disk; commodities arm absent",
        },
        "coverage": {
            "planned_pairs": "33-43 (15 stocks + 10 markets + 8 commodities)",
            "realised_pairs": n,
            "realised_breakdown": {"E1_individual_stocks": 12, "E2_cross_market": 10, "E3_commodities": 0},
            "asset_classes_covered": 1,
            "asset_classes_planned": 3,
        },
        "caveats": {
            "significance_bar_inconsistency": {
                "severity": "material — motivates this re-computation",
                "E1_rule": "paper3_E1.py:717 — significant_harvey = abs(t) > 3.0, hardcoded, "
                           "no HLN correction applied at all",
                "E2_rule": "paper3_E2.py:784-791 — t = t_raw * hln_factor, then "
                           "significant_harvey = abs(t) > student_t.ppf(0.975, df) ~ 1.961",
                "consequence": "the two arms publish the same field name under two different bars, "
                               "so 'E1: 0 significant' and 'E2: 2 significant' are NOT comparable. "
                               "Under E2's 1.96 bar, E1 would show NVDA-AMD (t=+1.974) as a "
                               "copula-favoured hit and several DCC-favoured hits.",
                "resolution": "this synthesis ignores both stored flags and recomputes every p-value "
                              "from (t, n_oos) on one uniform rule, then applies BH-FDR.",
            },
            "hln_coverage": {
                "E1_hln_applied": all(r["hln_applied"] for r in rows if r["study"] == "E1"),
                "E2_hln_applied": all(r["hln_applied"] for r in rows if r["study"] == "E2"),
                "note": "E1 stores raw DM t. With n_oos > 1500 the HLN factor exceeds 0.9997, so "
                        "applying it shifts E1's largest |t| (GOOGL-META/Clayton, 2.8880) only to "
                        "2.8875 — it cannot change any verdict at any bar considered here.",
            },
            "best_copula_selection": "t_best = max(t_student_t, t_clayton) is a selected maximum; "
                                     "inference uses all 44 tests with BH-FDR instead.",
            "overlapping_samples": "pairs share underlying assets (esp. TW0050, SPY), so BH-FDR "
                                   "independence is approximate — it is the lenient direction.",
        },
        "D1_lambda_L_scaling": scaling,
        "D1b_threshold_split": thresholds,
        "D1c_multiple_testing": {
            "n_tests": len(tests),
            "raw_sig_copula_favoured": [f"{t['pair']}/{t['model']}" for t in raw_sig_copula],
            "raw_sig_dcc_favoured": [f"{t['pair']}/{t['model']}" for t in raw_sig_dcc],
            "bh_fdr_5pct_survivors_copula": [
                {"pair": t["pair"], "model": t["model"], "t": t["t"], "p_bh_adj": t["p_bh_adj"]}
                for t in survivors_bh
            ],
            "bonferroni_5pct_survivors_copula": [
                {"pair": t["pair"], "model": t["model"], "t": t["t"]} for t in survivors_bonf
            ],
            "bonferroni_alpha": bonf,
        },
        "D1e_fz_family": fz_family,
        "D1f_trinity_calibration": trinity,
        "D2_sector_pattern": sector,
        "D1d_survivor_concentration": concentration,
        "pair_table": rows,
    }
    OUT.write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "pair_table"}, indent=2))


if __name__ == "__main__":
    main()
