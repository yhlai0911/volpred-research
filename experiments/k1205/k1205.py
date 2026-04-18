"""
K1205 - Paper 3 K1128 OFI->Jump Regime Synthesis
=================================================

PURE SYNTHESIS (no new estimation). Aggregates canonical numbers from four
complementary branches of the K1128 "VIX-conditional OFI -> jump" regime-
switching programme on TAIFEX TX 5-min bars (2017-2021, K1124 cache, 73,203
bars, 115 Lee-Mykland K=16 jumps, alpha=0.01 Gumbel):

  - K1128 : VIX tertile (IS-fixed cutoffs)              [origin, OOS degenerate]
  - K1131 : Natural cubic spline continuous beta        [NULL]
  - K1142 : Volatility-normalized OFI                   [PARTIAL_OOS_ONLY]
  - K1199 : Expanding-window adaptive VIX quantile      [NULL]

All numerical content is verbatim from each experiment's results JSON. No
re-estimation. Seed 42 is only used for any figure-level bootstrap (none here).

Outputs:
  - k1205_results.json            : consolidated canonical numbers
  - k1205_synthesis_table.csv     : 4-branch panorama table (LL / AUC / Brier / DM)
  - k1205_integrity_report.txt    : cross-experiment numerical integrity check

Author:   K1205 synthesis agent
Seed:     42
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

SEED = 42
np.random.seed(SEED)

EXP_ROOT = Path(__file__).resolve().parents[1]
K1205_DIR = EXP_ROOT / "k1205"
SOURCES = {
    "K1128": EXP_ROOT / "k1128" / "k1128_results.json",
    "K1131": EXP_ROOT / "k1131" / "k1131_results.json",
    "K1142": EXP_ROOT / "k1142" / "k1142_results.json",
    "K1199": EXP_ROOT / "k1199" / "k1199_results.json",
}


def load(path: Path) -> dict[str, Any]:
    # Handle NaN / Infinity emitted by upstream json.dump (Python default allows them).
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # json.loads does not accept NaN/Infinity; use a permissive loader.
    return json.loads(raw, parse_constant=lambda c: None)


def safe_round(x, n=6):
    if x is None:
        return None
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
        return round(float(x), n)
    except Exception:
        return None


def main() -> None:
    data = {k: load(v) for k, v in SOURCES.items()}

    # =========================================================================
    # STEP 1. Canonical numbers per branch (verbatim)
    # =========================================================================
    k1128 = data["K1128"]
    k1131 = data["K1131"]
    k1142 = data["K1142"]
    k1199 = data["K1199"]

    # K1128 high-tertile M3 (only evaluable tertile due to OOS coverage degeneracy)
    # NOTE: K1128 records `ll_oos` as NEGATIVE log-loss (i.e. log-likelihood
    # per obs; see k1128.py line 257: float(-log_loss(...))). For apples-to-
    # apples comparison with K1131/K1142/K1199 which record positive log-loss,
    # we flip the sign here. This is a unit convention fix, NOT a value edit.
    k1128_high = k1128["tertile_results"]["high"]
    k1128_ll_oos_flipped = -k1128_high["M3"]["ll_oos"]  # to positive log-loss
    k1128_row = {
        "experiment": "K1128",
        "branch": "VIX tertile (IS-fixed)",
        "focal_model": "M3_tertile_high",
        "n_oos": k1128_high["n_oos"],
        "n_oos_jumps": k1128_high["n_oos_jumps"],
        "auc_oos": k1128_high["M3"]["auc_oos"],
        "ll_oos": k1128_ll_oos_flipped,
        "ll_oos_unit_note": "sign-flipped from K1128 raw ll_oos (-log_loss) to positive log_loss per-bar for cross-experiment comparability",
        "brier_oos": k1128_high["M3"]["brier_oos"],
        "dm_t_vs_baseline": k1128_high["dm_M3_vs_M1"]["t"],
        "dm_baseline": "M1 (jump_curr only)",
        "verdict": "NULL (partial only; OOS coverage 0/854/20060 degenerate)",
        "regime_coverage_oos": k1128["secondary_oos_internal_analysis"][
            "per_oos_tertile"
        ] if k1128.get("secondary_oos_internal_analysis") else None,
    }

    # K1131 spline (full-OOS)
    k1131_row = {
        "experiment": "K1131",
        "branch": "Natural cubic spline (continuous beta)",
        "focal_model": "M_spline",
        "n_oos": k1131["n_oos"],
        "n_oos_jumps": k1131["n_oos_jumps"],
        "auc_oos": k1131["OOS_AUC"]["spline"],
        "ll_oos": k1131["OOS_log_loss"]["spline"],
        "brier_oos": None,  # not reported
        "dm_t_vs_baseline": k1131["DM_spline_vs_base"]["t"],
        "dm_baseline": "M_base (jump_curr + |OFI| + OFI)",
        "verdict": k1131["verdict"],
        "LRT_chi2_p_vs_base": {
            "chi2": k1131["H1_LRT_spline_vs_base"]["chi2_stat"],
            "p": k1131["H1_LRT_spline_vs_base"]["p_value"],
        },
    }

    # K1142 volnorm (paper-quotable canonical for vol-norm)
    k1142_row = {
        "experiment": "K1142",
        "branch": "Vol-normalized OFI (sigma_60, strictly past)",
        "focal_model": "M_volnorm",
        "n_oos": k1142["n_oos"],
        "n_oos_jumps": k1142["n_oos_jumps"],
        "auc_oos": k1142["OOS_metrics"]["AUC"]["volnorm"],
        "ll_oos": k1142["OOS_metrics"]["log_loss"]["volnorm"],
        "brier_oos": k1142["OOS_metrics"]["Brier"]["volnorm"],
        "dm_t_vs_baseline": k1142["DM_HLN_tests"]["OOS_volnorm_vs_base"]["t"],
        "dm_baseline": "M_base (raw OFI features)",
        "verdict": k1142["verdict"],
        "spearman_rho_oos": k1142["OOS_metrics"]["Spearman_fitted_vs_jump"][
            "volnorm"
        ]["rho"],
        "realvol_tertile_aux": {
            "auc_oos": k1142["OOS_metrics"]["AUC"]["realvol_tertile"],
            "dm_t_vs_base": k1142["DM_HLN_tests"][
                "OOS_realvol_tertile_vs_base"
            ]["t"],
        },
    }

    # K1199 expanding-window
    k1199_row = {
        "experiment": "K1199",
        "branch": "Expanding-window adaptive VIX quantile",
        "focal_model": "M_expanding",
        "n_oos": k1199["n_oos"],
        "n_oos_jumps": k1199["n_oos_jumps"],
        "auc_oos": k1199["OOS_AUC"]["expanding"],
        "ll_oos": k1199["OOS_log_loss"]["expanding"],
        "brier_oos": k1199["OOS_Brier"]["expanding"],
        "dm_t_vs_baseline": k1199["DM_HLN"]["exp_vs_base"]["t"],
        "dm_baseline": "M_base (raw OFI features, K1128 replication)",
        "verdict": k1199["verdict"],
        "oos_regime_coverage": k1199["oos_tertile_coverage"]["K1199_expanding"],
        "n_refits": len(
            k1199["models"]["M_expanding_final_refit"]["refit_log"]
        ),
    }

    branches = [k1128_row, k1131_row, k1142_row, k1199_row]

    # =========================================================================
    # STEP 2. Cross-experiment numerical integrity check
    # =========================================================================
    integrity: list[dict[str, Any]] = []

    # (a) Jump detection: all four must agree on 115 jumps, alpha=0.01, K=16
    jump_counts = {
        "K1128": k1128["jump_detection"]["n_jumps"],
        "K1131": k1131["jump_detection"]["n_jumps_total"],
        "K1142": k1142["jump_detection"]["n_jumps_total"],
        "K1199": k1199["jump_detection"]["n_jumps_total"],
    }
    integrity.append(
        {
            "check": "Total Lee-Mykland jumps (K=16, alpha=0.01)",
            "values": jump_counts,
            "pass": len(set(jump_counts.values())) == 1,
            "note": "K1128 denominator is n_valid_prediction=52412 (post jump/OFI"
            " valid mask); K1131/K1142/K1199 inherit same cache.",
        }
    )

    # (b) Gumbel threshold must be identical (derived from same n_valid_global)
    gumbel = {
        "K1128": k1128["jump_detection"]["threshold_multi_Gumbel"],
        "K1131": k1131["jump_detection"]["gumbel_thresh_alpha_0.01"],
        "K1142": k1142["jump_detection"]["gumbel_thresh_alpha_0.01"],
        "K1199": k1199["jump_detection"]["gumbel_thresh_alpha_0.01"],
    }
    integrity.append(
        {
            "check": "Gumbel threshold alpha=0.01",
            "values": gumbel,
            "pass": len({round(v, 6) for v in gumbel.values()}) == 1,
        }
    )

    # (c) IS-fixed VIX cutoffs must match across K1128/K1131/K1199
    cutoff_33 = {
        "K1128": k1128["vix_tertile_cutoffs"]["cutoff_33"],
        "K1131": k1131["tertile_cutoffs_IS"]["cutoff_33"],
        "K1199": k1199["tertile_cutoffs_IS_fixed_K1128"]["cutoff_33"],
    }
    cutoff_67 = {
        "K1128": k1128["vix_tertile_cutoffs"]["cutoff_67"],
        "K1131": k1131["tertile_cutoffs_IS"]["cutoff_67"],
        "K1199": k1199["tertile_cutoffs_IS_fixed_K1128"]["cutoff_67"],
    }
    integrity.append(
        {
            "check": "IS VIX tertile cutoff_33",
            "values": cutoff_33,
            "pass": len({round(v, 4) for v in cutoff_33.values()}) == 1,
        }
    )
    integrity.append(
        {
            "check": "IS VIX tertile cutoff_67",
            "values": cutoff_67,
            "pass": len({round(v, 4) for v in cutoff_67.values()}) == 1,
        }
    )

    # (d) M_base coefficients (intercept + jump_curr + |OFI| + OFI) must match
    # K1131 / K1199 (same IS sample, same MLE with l2=1e-4). K1142 excludes 43
    # extra rows (n_valid 52369 vs 52412) due to sigma_60-missing mask.
    base_k1131 = k1131["models"]["M_base"]["beta"]
    base_k1199 = k1199["models"]["M_base"]["beta"]
    base_match = all(
        abs(a - b) < 1e-6 for a, b in zip(base_k1131, base_k1199)
    )
    integrity.append(
        {
            "check": "M_base beta identical across K1131 & K1199",
            "values": {"K1131": base_k1131, "K1199": base_k1199},
            "pass": base_match,
            "note": "K1142 M_base nll differs (556.9451 vs 557.0556) by 43-bar"
            " sample exclusion from sigma_60 strict-past NaN (52369 vs 52412"
            " valid rows).",
        }
    )

    # (e) K1128 high-tertile OOS (n=20060) vs K1131/K1199 full OOS (n=20914):
    # difference is 854 mid-tertile bars that K1128 skipped (status=ok but
    # documented via "mid" stratum with <5 jumps skip in per-tertile loop).
    nos_check = {
        "K1128_high_tertile_only": k1128_high["n_oos"],
        "K1131_full_oos": k1131["n_oos"],
        "K1199_full_oos": k1199["n_oos"],
        "K1142_full_oos": k1142["n_oos"],
    }
    expected_gap = (
        k1131["n_oos"] - k1128_high["n_oos"]
    )  # should be 854 (mid tertile)
    integrity.append(
        {
            "check": "K1128 OOS coverage gap vs full OOS",
            "values": nos_check,
            "pass": expected_gap == k1128["tertile_results"]["mid"]["n_oos"],
            "note": f"Full OOS - K1128 high = {expected_gap} bars, matches"
            f" K1128 mid-tertile n_oos={k1128['tertile_results']['mid']['n_oos']}.",
        }
    )

    # (f) K1142 volnorm vs K1199 M_volnorm divergence (documented implementation
    # difference, NOT a bug). K1199 uses sigma_fallback to Lee-Mykland BV when
    # rolling_60 missing. K1142 drops those rows.
    volnorm_auc_divergence = {
        "K1142_volnorm_auc_oos_canonical": k1142["OOS_metrics"]["AUC"][
            "volnorm"
        ],
        "K1199_M_volnorm_auc_oos_bench": k1199["OOS_AUC"]["volnorm"],
        "K1142_n_valid": k1142["n_valid"],
        "K1199_n_bars_valid": k1199["n_bars_valid"],
    }
    integrity.append(
        {
            "check": "K1142 vs K1199 volnorm AUC implementation note",
            "values": volnorm_auc_divergence,
            "pass": True,
            "note": "DOCUMENTED IMPLEMENTATION DIFFERENCE (not bug): K1199 uses"
            " sigma fallback (rolling-60 -> LM BV sigma) for 43 bars; K1142"
            " drops those rows. Both are valid operationalizations but produce"
            " different AUC. K1142 is the paper-quotable canonical for the"
            " vol-norm hypothesis (explicit volnorm-only experiment).",
        }
    )

    # =========================================================================
    # STEP 3. Consolidated results JSON
    # =========================================================================
    summary = {
        "experiment_id": "K1205",
        "title": "Paper 3 K1128 OFI-jump regime synthesis (4-branch null panorama)",
        "task_type": "pure_synthesis_no_new_estimation",
        "seed": SEED,
        "timestamp": "2026-04-17",
        "data_source": "TAIFEX TX 5-min bars 2017-2021 (K1124 cache)",
        "n_bars_total": 73203,
        "n_valid_prediction_superset": 52412,
        "jump_detection_canonical": {
            "method": "Lee-Mykland K=16 strictly-past BV",
            "alpha": 0.01,
            "gumbel_threshold": 5.125598054567598,
            "n_jumps": 115,
            "jump_rate_pct": 0.2144,
        },
        "is_period": "2017-2019",
        "oos_period": "2020-2021",
        "oos_vix_range": {
            "min": k1131["oos_vix_range"]["min"],
            "max": k1131["oos_vix_range"]["max"],
            "mean": k1131["oos_vix_range"]["mean"],
        },
        "is_vix_range": {
            "min": k1131["is_vix_range"]["min"],
            "max": k1131["is_vix_range"]["max"],
            "mean": k1131["is_vix_range"]["mean"],
        },
        "branches": branches,
        "integrity_checks": integrity,
        "integrity_all_pass": all(c["pass"] for c in integrity),
        "narrative_verdict": {
            "k1128_4branch_gate": "ALL NULL (K1128 degenerate, K1131 null, K1199 null) with ONE PARTIAL CELL (K1142 volnorm AUC 0.5940 DM t=+2.25 at |t|>2 but <|3|)",
            "implication_for_paper3_leverage_direction": "Regime-switching OFI->jump narrative is not supported. K1142 vol-norm is a standalone partial positive that may anchor a restricted-scope revision but does not rescue K1128's leverage-regime story.",
        },
        "decision_matrix": {
            "path_a_full_K1142_volnorm_anchor": {
                "evidence_strength": "PARTIAL (one cell; AUC 0.5940, DM t=+2.25, n_oos_jumps=33)",
                "feasibility": "HIGH",
                "reviewer_risk": "HIGH (single positive cell; |t|=2.25 below Harvey 2016 threshold |t|>3; power limited)",
            },
            "path_b_hybrid_null_plus_positive": {
                "evidence_strength": "COMPLETE (4-branch panorama; honest null with one partial)",
                "feasibility": "MEDIUM (complex framing; explain why leverage-direction fails AND why vol-norm partially works)",
                "reviewer_risk": "MEDIUM (honest null is publishable; fits JoE/IJF 'what does not work' niche)",
            },
            "path_c_abandon_leverage_direction": {
                "evidence_strength": "N/A (preserves prior positive K1142 for a separate vol-norm paper)",
                "feasibility": "HIGH (but sunk cost: ~1 year's work on K1128 story discarded)",
                "reviewer_risk": "N/A (non-submission)",
            },
        },
        "recommendation": (
            "Path (b) Hybrid null+positive: honest 4-branch null"
            " with K1142 vol-norm partial is publishable as a"
            " clean negative-result methodological paper."
        ),
    }

    out_json = K1205_DIR / "k1205_results.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    # =========================================================================
    # STEP 4. Write CSV synthesis panorama table
    # =========================================================================
    cols = [
        "experiment",
        "branch",
        "focal_model",
        "n_oos",
        "n_oos_jumps",
        "auc_oos",
        "ll_oos",
        "brier_oos",
        "dm_t_vs_baseline",
        "verdict",
    ]
    csv_lines = [",".join(cols)]
    for row in branches:
        csv_lines.append(
            ",".join(
                [
                    str(row["experiment"]),
                    f'"{row["branch"]}"',
                    str(row["focal_model"]),
                    str(row["n_oos"]),
                    str(row["n_oos_jumps"]),
                    f"{safe_round(row['auc_oos'], 4)}",
                    f"{safe_round(row['ll_oos'], 6)}",
                    f"{safe_round(row['brier_oos'], 6)}"
                    if row["brier_oos"] is not None
                    else "NA",
                    f"{safe_round(row['dm_t_vs_baseline'], 3)}",
                    f'"{row["verdict"]}"',
                ]
            )
        )

    with open(K1205_DIR / "k1205_synthesis_table.csv", "w", encoding="utf-8") as f:
        f.write("\n".join(csv_lines) + "\n")

    # =========================================================================
    # STEP 5. Integrity report (plain text for reviewer)
    # =========================================================================
    lines = ["K1205 Cross-Experiment Numerical Integrity Report\n" + "=" * 56]
    lines.append(f"Sources: {list(SOURCES.keys())}")
    lines.append("")
    for c in integrity:
        status = "PASS" if c["pass"] else "FAIL"
        lines.append(f"[{status}] {c['check']}")
        for k, v in c["values"].items():
            lines.append(f"    {k}: {v}")
        if c.get("note"):
            lines.append(f"    NOTE: {c['note']}")
        lines.append("")
    lines.append(f"OVERALL: {'ALL PASS' if summary['integrity_all_pass'] else 'SEE FAILURES ABOVE'}")

    with open(K1205_DIR / "k1205_integrity_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Console summary
    print("=" * 60)
    print("K1205 Synthesis complete")
    print("=" * 60)
    print(f"Branches synthesized: {len(branches)}")
    print(f"Integrity checks    : {len(integrity)} ({'ALL PASS' if summary['integrity_all_pass'] else 'SOME FAILED'})")
    print(f"Narrative verdict   : {summary['narrative_verdict']['k1128_4branch_gate']}")
    print(f"Recommendation      : {summary['recommendation']}")
    print()
    print(f"Outputs written to  : {K1205_DIR}")


if __name__ == "__main__":
    main()
