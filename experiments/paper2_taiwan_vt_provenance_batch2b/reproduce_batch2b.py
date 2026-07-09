#!/usr/bin/env python3
"""
Provenance sweep Batch2b for paper/taiwan-vt body_v3.tex.

This is a governance artifact, not a new research experiment. It binds the
remaining taiwan-vt provenance gaps from PROVENANCE_SWEEP_20260710.md to live
experiment JSON where possible, and marks the rest as unresolved/sign-off.
It does not modify manuscript numbers.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BODY = ROOT / "paper" / "taiwan-vt" / "body_v3.tex"
OUT = HERE / "paper2_taiwan_vt_provenance_batch2b_results.json"


def load_json(rel: str) -> Any:
    with (ROOT / rel).open() as fh:
        return json.load(fh)


def body_text() -> str:
    return BODY.read_text()


def rel(path: str) -> str:
    return path


def status_numeric(
    paper_value: float,
    source_value: float,
    *,
    abs_tol: float | None = None,
    rel_tol: float = 0.006,
) -> str:
    diff = abs(float(paper_value) - float(source_value))
    if abs_tol is not None and diff <= abs_tol:
        return "matched"
    denom = max(abs(float(paper_value)), 1e-12)
    return "matched" if diff / denom <= rel_tol else "drift_requires_signoff"


def add(
    checks: list[dict[str, Any]],
    *,
    group: str,
    claim: str,
    paper_value: Any,
    source_value: Any,
    source: str,
    status: str,
    body_pattern: str | None = None,
    note: str = "",
) -> None:
    text = body_text()
    checks.append(
        {
            "group": group,
            "claim": claim,
            "paper_value": paper_value,
            "source_value": source_value,
            "source": source,
            "status": status,
            "body_pattern_present": (body_pattern in text) if body_pattern else None,
            "note": note,
        }
    )


def add_numeric(
    checks: list[dict[str, Any]],
    *,
    group: str,
    claim: str,
    paper_value: float,
    source_value: float,
    source: str,
    body_pattern: str | None = None,
    abs_tol: float | None = None,
    rel_tol: float = 0.006,
    note: str = "",
) -> None:
    add(
        checks,
        group=group,
        claim=claim,
        paper_value=paper_value,
        source_value=round(float(source_value), 6),
        source=source,
        status=status_numeric(paper_value, source_value, abs_tol=abs_tol, rel_tol=rel_tol),
        body_pattern=body_pattern,
        note=note,
    )


def section_present(pattern: str) -> bool:
    return bool(re.search(pattern, body_text(), flags=re.MULTILINE | re.DOTALL))


def main() -> None:
    checks: list[dict[str, Any]] = []

    k1175 = load_json("experiments/k1175/k1175_results.json")
    k900 = load_json("experiments/k900/k900_taiwan_vt_performance_results.json")
    k1176 = load_json("experiments/k1176/k1176_results.json")
    k1180 = load_json("experiments/k1180/k1180_results.json")
    k1182 = load_json("experiments/k1182/k1182_results.json")
    k892 = load_json("experiments/k892/k892_verify_tw_gamma_results.json")
    k896 = load_json("experiments/k896/k896_taiwan_es_supplement_results.json")
    k515 = load_json("experiments/k515/k515_overnight_gap_results.json")
    k516 = load_json("experiments/k516/k516_overnight_futures_results.json")
    tsmc_vt = load_json("experiments/paper2_sec45_tsmc_vt/tsmc_vt_strategy_results.json")
    gamma_refit = load_json("experiments/paper2_sec45_gamma_refit/refit_concentration_gamma_results.json")
    indiv_gamma = load_json(
        "experiments/paper2_taiwan_indiv_rolling_gamma/paper2_taiwan_indiv_rolling_gamma_results.json"
    )
    twd_usd = load_json("experiments/paper2_sec3_twd_usd_test/twd_usd_granger_test_results.json")
    twii_gamma = load_json("experiments/paper2_twii_fullsample_gamma_provenance/results.json")

    # Table 3: revised body_v3 values are now the K1175 canonical replication.
    table3 = {
        "buy_hold": {"sharpe": 0.799, "mdd_pct": -33.8, "ann_return_pct": 14.48, "ann_vol_pct": 18.13, "ann_turnover_pct": 0},
        "ewma_vt": {"sharpe": 0.701, "mdd_pct": -21.2, "ann_return_pct": 7.42, "ann_vol_pct": 10.58, "ann_turnover_pct": 480},
        "garch_vt": {"sharpe": 0.950, "mdd_pct": -22.2, "ann_return_pct": 10.50, "ann_vol_pct": 11.06, "ann_turnover_pct": 678},
        "gjr_vt": {"sharpe": 1.074, "mdd_pct": -22.3, "ann_return_pct": 12.19, "ann_vol_pct": 11.35, "ann_turnover_pct": 694},
        "vix_863": {"sharpe": 1.137, "mdd_pct": -13.7, "ann_return_pct": 10.72, "ann_vol_pct": 9.43, "ann_turnover_pct": 102},
    }
    for strategy, metrics in table3.items():
        for metric, paper_value in metrics.items():
            source_value = k1175["k1175_results"][strategy][metric]
            add_numeric(
                checks,
                group="Table 3 VT performance",
                claim=f"{strategy}.{metric}",
                paper_value=paper_value,
                source_value=source_value,
                source=rel("experiments/k1175/k1175_results.json"),
                abs_tol=0.11 if metric in {"mdd_pct", "ann_turnover_pct"} else 0.006,
                body_pattern=str(paper_value).rstrip("0").rstrip("."),
            )

    # Table 5/common-period: source is K900, not K1175.
    common = {
        "buy_hold": {"sharpe": 1.122, "mdd_pct": -33.8, "ann_return_pct": 24.6, "ann_vol_pct": 21.9, "ann_turnover_pct": 0},
        "ewma_vt": {"sharpe": 1.018, "mdd_pct": -21.2, "ann_return_pct": 11.0, "ann_vol_pct": 10.8, "ann_turnover_pct": 448},
        "garch_vt": {"sharpe": 0.950, "mdd_pct": -22.2, "ann_return_pct": 10.5, "ann_vol_pct": 11.1, "ann_turnover_pct": 678},
        "gjr_vt": {"sharpe": 1.084, "mdd_pct": -22.2, "ann_return_pct": 12.3, "ann_vol_pct": 11.3, "ann_turnover_pct": 689},
        "vix_863": {"sharpe": 1.132, "mdd_pct": -13.7, "ann_return_pct": 11.3, "ann_vol_pct": 10.0, "ann_turnover_pct": 94},
    }
    for strategy, metrics in common.items():
        for metric, paper_value in metrics.items():
            if strategy == "garch_vt":
                source_value = k1175["k1175_results"][strategy][metric]
                source_path = rel("experiments/k1175/k1175_results.json")
            else:
                source_value = k900["table_common_period"][strategy][metric]
                source_path = rel("experiments/k900/k900_taiwan_vt_performance_results.json")
            add_numeric(
                checks,
                group="Table 5/common-period VT performance",
                claim=f"{strategy}.{metric}",
                paper_value=paper_value,
                source_value=source_value,
                source=source_path,
                abs_tol=0.16 if metric in {"mdd_pct", "ann_turnover_pct", "ann_return_pct", "ann_vol_pct"} else 0.006,
                body_pattern=str(paper_value).rstrip("0").rstrip("."),
            )

    # Time-zone Table 4 after body_v3 split-corrected rewrite.
    tz_claims = [
        ("TW c2c Sharpe", 1.915, k1176["individual_markets"]["TW"]["c2c"]["sharpe"], "1.915"),
        ("TW o2o Sharpe", 2.350, k1176["individual_markets"]["TW"]["o2o"]["sharpe"], "2.350"),
        ("TW c2c t", 6.76, k1176["individual_markets"]["TW"]["c2c"]["nw_tstat"], "6.76"),
        ("TW o2o t", 8.13, k1176["individual_markets"]["TW"]["o2o"]["nw_tstat"], "8.13"),
        ("JP c2c Sharpe", 1.773, k1176["individual_markets"]["JP"]["c2c"]["sharpe"], "1.773"),
        ("JP o2o Sharpe", 2.224, k1176["individual_markets"]["JP"]["o2o"]["sharpe"], "2.224"),
        ("JP o2o t", 8.34, k1176["individual_markets"]["JP"]["o2o"]["nw_tstat"], "8.34"),
        ("TW+JP 50/50 Sharpe", 2.192, k1176["combinations"]["tw_jp_5050_c2c"]["sharpe"], "2.192"),
        ("Global proxy Sharpe", 1.899, k1176["combinations"]["global_spy_tw_c2c_proxy"]["sharpe"], "1.899"),
        ("HK c2c t", 2.92, k1176["individual_markets"]["HK"]["c2c"]["nw_tstat"], "2.92"),
        ("AU c2c t", 4.52, k1176["individual_markets"]["AU"]["c2c"]["nw_tstat"], "4.52"),
        ("SG c2c t", 4.83, k1176["individual_markets"]["SG"]["c2c"]["nw_tstat"], "4.83"),
        ("KR c2c t", 4.88, k1176["individual_markets"]["KR"]["c2c"]["nw_tstat"], "4.88"),
        ("JP c2c t", 6.91, k1176["individual_markets"]["JP"]["c2c"]["nw_tstat"], "6.91"),
    ]
    for claim, paper_value, source_value, body_pattern in tz_claims:
        add_numeric(
            checks,
            group="Table 4 time-zone strategy",
            claim=claim,
            paper_value=paper_value,
            source_value=source_value,
            source=rel("experiments/k1176/k1176_results.json"),
            abs_tol=0.006,
            body_pattern=body_pattern,
        )

    # Overnight gap diagnostics.
    add_numeric(
        checks,
        group="Appendix overnight gap",
        claim="gap share of total return",
        paper_value=87.0,
        source_value=k515["gap_return_diagnostics"]["gap_share_of_total_return_pct"],
        source=rel("experiments/k515/k515_overnight_gap_results.json"),
        abs_tol=0.6,
        body_pattern="87\\%",
    )
    add_numeric(
        checks,
        group="Appendix overnight gap",
        claim="SPY+VIX conditioned up-gap bps",
        paper_value=10.73,
        source_value=k515["strategies"]["spy_vix_combined"]["avg_gap_signal_bps"],
        source=rel("experiments/k515/k515_overnight_gap_results.json"),
        abs_tol=0.01,
        body_pattern="+10.73",
    )
    add_numeric(
        checks,
        group="Appendix overnight gap",
        claim="SPY+VIX conditioned t-stat",
        paper_value=6.845,
        source_value=k515["strategies"]["spy_vix_combined"]["t_stat_gross"],
        source=rel("experiments/k515/k515_overnight_gap_results.json"),
        abs_tol=0.001,
        body_pattern="6.845",
    )
    add_numeric(
        checks,
        group="Appendix overnight gap",
        claim="TAIFEX/futures 5bp net Sharpe",
        paper_value=0.93,
        source_value=k516["strategies"]["spy_vix_combined"]["tx_scenarios"]["tx_5bp"]["sharpe_net"],
        source=rel("experiments/k516/k516_overnight_futures_results.json"),
        abs_tol=0.01,
        body_pattern="0.93",
        note="Mentioned in paper experiments registry / source audit, not necessarily rendered in current body_v3.",
    )
    add(
        checks,
        group="Appendix overnight gap",
        claim="SPY down-day opening gap -8.91bp",
        paper_value=-8.91,
        source_value=k515["statistical_tests"]["spy_conditioning"]["gap_spy_dn_bps"],
        source=rel("experiments/k515/k515_overnight_gap_results.json"),
        status="still_no_source",
        body_pattern="-8.91",
        note="K515/K847 store about -0.95bp for SPY-down conditioning; exact -8.91bp remains unreproduced.",
    )
    add(
        checks,
        group="Appendix overnight gap",
        claim="block-bootstrap CI [0.65, 2.24]",
        paper_value="[0.65, 2.24]",
        source_value=None,
        source="none found",
        status="still_no_source",
        body_pattern="[0.65, \\, 2.24]",
        note="No stored JSON contains this bootstrap interval; needs new bootstrap on K1176 c2c strategy.",
    )

    # Macro and business-cycle indicators.
    add(
        checks,
        group="Section 6 macro",
        claim="import growth r=0.214 / OOS +5.6% / DM p=0.043",
        paper_value={"partial_r": 0.214, "oos_improvement_pct": 5.6, "dm_p": 0.043},
        source_value=None,
        source="knowledge-only G12 per paper/taiwan-vt/reproducibility_audit/nosource_rescan_report.md",
        status="no_formal_experiment",
        body_pattern="partial $r = 0.214$",
        note="Exact values are knowledge-entry sourced only; no README/script/results JSON exists.",
    )
    add_numeric(
        checks,
        group="Section 6 macro",
        claim="BCI level t",
        paper_value=-0.53,
        source_value=k1180["part_a_null_test"]["result"]["t_stat"],
        source=rel("experiments/k1180/k1180_results.json"),
        abs_tol=0.01,
        body_pattern="$t = -0.53$",
    )
    add(
        checks,
        group="Section 6 macro",
        claim="leading indicator t and R2",
        paper_value={"t": 3.74, "r2": 0.071},
        source_value={
            "all_sample": k1180["part_b_predictive"]["result_all_sample"],
            "best_2016_plus": k1180["part_b_predictive"]["result_2016_plus"],
        },
        source=rel("experiments/k1180/k1180_results.json"),
        status="period_sensitive_drift",
        body_pattern="$t = 3.74$",
        note="Direction survives, but exact t=3.74/R2=7.1% is not reproduced by K1180 stored specs.",
    )
    add_numeric(
        checks,
        group="Section 6 macro",
        claim="coincident indicator in-sample Sharpe",
        paper_value=0.413,
        source_value=k1180["part_c_strategy"]["result"]["full_sharpe"],
        source=rel("experiments/k1180/k1180_results.json"),
        abs_tol=0.002,
        body_pattern="0.413",
    )
    add_numeric(
        checks,
        group="Section 6 macro",
        claim="coincident indicator OOS Sharpe",
        paper_value=1.260,
        source_value=k1180["part_c_strategy"]["result"]["oos_sharpe"],
        source=rel("experiments/k1180/k1180_results.json"),
        abs_tol=0.011,
        body_pattern="1.260",
    )

    # Gamma provenance.
    add(
        checks,
        group="Table 2 gamma",
        claim="TWII rendered gamma/t",
        paper_value={"gamma": 0.272, "t": 3.18},
        source_value={"reestimate": twii_gamma["reestimate"], "k892_full_sample": k892["assets"]["^TWII"]["full_sample"]},
        source=rel("experiments/paper2_twii_fullsample_gamma_provenance/results.json"),
        status="disputed_requires_owner_signoff",
        body_pattern="DISPUTED PROVENANCE",
        note="body_v3 already labels rendered 0.272/3.18 as untraceable pending sign-off.",
    )
    add_numeric(
        checks,
        group="Table 2 gamma",
        claim="0050.TW full-sample gamma",
        paper_value=0.097,
        source_value=k892["assets"]["0050.TW"]["full_sample"]["gamma"],
        source=rel("experiments/k892/k892_verify_tw_gamma_results.json"),
        abs_tol=0.001,
        body_pattern="0050.TW & 0.097",
    )
    add_numeric(
        checks,
        group="Table 2 gamma",
        claim="TSMC full-sample gamma",
        paper_value=0.052,
        source_value=k892["assets"]["2330.TW"]["full_sample"]["gamma"],
        source=rel("experiments/k892/k892_verify_tw_gamma_results.json"),
        abs_tol=0.001,
        body_pattern="TSMC (2330) & 0.052",
    )
    add(
        checks,
        group="Table 2 gamma",
        claim="individual-stock rolling rows and averages",
        paper_value={
            "2317": 0.052,
            "2454": 0.044,
            "2886": 0.179,
            "0056": 0.112,
            "avg_9": 0.054,
            "avg_10": 0.060,
        },
        source_value={
            "calendar_aligned_common_end": indiv_gamma["calendar_alignment_common_end"],
            "2317": indiv_gamma["per_stock"]["2317.TW"]["gamma"],
            "2454": indiv_gamma["per_stock"]["2454.TW"]["gamma"],
            "2886": indiv_gamma["per_stock"]["2886.TW"]["gamma"],
            "0056": indiv_gamma["etf_0056"]["gamma"],
            "avg_9": indiv_gamma["rolling_averages_and_ratio"]["gamma_mean_9stock"],
            "avg_10": indiv_gamma["rolling_averages_and_ratio"]["gamma_mean_10security_incl_0056"],
        },
        source=rel("experiments/paper2_taiwan_indiv_rolling_gamma/paper2_taiwan_indiv_rolling_gamma_results.json"),
        status="rendered_legacy_non_reproducible_requires_paper_body_signoff",
        body_pattern="N121 NON-REPRODUCIBLE",
        note="Dedicated JSON exists and uses one documented estimation path; rendered legacy rows intentionally unchanged pending paper rewrite.",
    )

    # Sec 3 spillover and TWD/USD.
    add_numeric(
        checks,
        group="Section 3 spillover",
        claim="VIX Granger F",
        paper_value=58.8,
        source_value=k1182["outcome"]["best_F"],
        source=rel("experiments/k1182/k1182_results.json"),
        abs_tol=0.2,
        body_pattern="F = 58.8",
    )
    add(
        checks,
        group="Section 3 spillover",
        claim="TWD/USD p after VIX controls",
        paper_value=0.08,
        source_value=twd_usd["p_value"],
        source=rel("experiments/paper2_sec3_twd_usd_test/twd_usd_granger_test_results.json"),
        status="drift_large_requires_signoff",
        body_pattern="$p = 0.08$",
        note="Primary and sensitivity specs do not recover p=0.08; all are much larger.",
    )
    add(
        checks,
        group="Section 3 spillover",
        claim="SPY lagged correlation r=0.376 and contemporaneous r=0.161",
        paper_value={"lagged": 0.376, "contemporaneous": 0.161},
        source_value=None,
        source="none found",
        status="still_no_source",
        body_pattern="r = 0.376",
        note="Prior audit found only K847 2017-2026 gap correlation near 0.399, not this c2c 2012-2025 claim.",
    )

    # TSMC decomposition and gamma refit.
    add(
        checks,
        group="Section 4.5 TSMC concentration",
        claim="TSMC VT Sharpe",
        paper_value=1.121,
        source_value={
            "primary_garch": tsmc_vt["number_a_tsmc_vt_sharpe"]["primary_sharpe"],
            "closest_gjr": tsmc_vt["number_a_tsmc_vt_sharpe"]["closest_sharpe"],
        },
        source=rel("experiments/paper2_sec45_tsmc_vt/tsmc_vt_strategy_results.json"),
        status="matched_with_spec_caveat",
        body_pattern="1.121",
        note="Primary GARCH spec is within stated tolerance; closest GJR spec is 1.1299.",
    )
    add_numeric(
        checks,
        group="Section 4.5 TSMC concentration",
        claim="TSMC variance share",
        paper_value=0.525,
        source_value=tsmc_vt["number_b_variance_share"]["primary_r_squared"],
        source=rel("experiments/paper2_sec45_tsmc_vt/tsmc_vt_strategy_results.json"),
        abs_tol=0.005,
        body_pattern="52.5\\%",
    )
    add(
        checks,
        group="Section 4.5 TSMC concentration",
        claim="ex-TSMC Sharpe range",
        paper_value="[0.193, 0.637]",
        source_value=None,
        source="none found in paper2_sec45_tsmc_vt",
        status="still_no_source",
        body_pattern="0.193 to 0.637",
        note="The TSMC VT JSON has bootstrap CI values but no ex-TSMC synthetic-portfolio Sharpe range.",
    )
    add(
        checks,
        group="Section 4.5 TSMC concentration",
        claim="2020-2026 gamma refit ordering",
        paper_value={"0050_gamma": 0.155, "2330_gamma": 0.044, "0050_t": 1.77, "2330_t": 1.12},
        source_value=gamma_refit["single_window_fits"]["common_vt"],
        source=rel("experiments/paper2_sec45_gamma_refit/refit_concentration_gamma_results.json"),
        status="matched",
        body_pattern="0050.TW $\\gamma = 0.155$",
    )

    # VaR / ES model rows and skewed-t params.
    add_numeric(
        checks,
        group="Section 7 VaR/ES",
        claim="GJR+Cornish-Fisher 1% violation rate",
        paper_value=0.005,
        source_value=k896["results"]["1%"]["GJR+Cornish-Fisher"]["violation_rate"],
        source=rel("experiments/k896/k896_taiwan_es_supplement_results.json"),
        abs_tol=0.0002,
        body_pattern="0.5\\%",
    )
    add_numeric(
        checks,
        group="Section 7 VaR/ES",
        claim="GJR+Student-t 1% violation rate",
        paper_value=0.0103,
        source_value=k896["results"]["1%"]["GJR+Student-t"]["violation_rate"],
        source=rel("experiments/k896/k896_taiwan_es_supplement_results.json"),
        abs_tol=0.0001,
        body_pattern="1.03\\%",
    )
    add(
        checks,
        group="Section 7 VaR/ES",
        claim="skewed Student-t eta/lambda",
        paper_value={"eta": 5.2, "lambda": -0.05},
        source_value=None,
        source="none found in K896",
        status="still_no_source",
        body_pattern="$\\eta = 5.2$",
        note="K896 stores VaR/ES outcomes but not skewed-t MLE parameters.",
    )

    by_status: dict[str, int] = {}
    by_group: dict[str, dict[str, int]] = {}
    for check in checks:
        by_status[check["status"]] = by_status.get(check["status"], 0) + 1
        by_group.setdefault(check["group"], {})
        by_group[check["group"]][check["status"]] = by_group[check["group"]].get(check["status"], 0) + 1

    unresolved = [c for c in checks if c["status"] not in {"matched", "matched_with_spec_caveat"}]
    result = {
        "experiment_id": "paper2_taiwan_vt_provenance_batch2b",
        "title": "taiwan-vt remaining provenance sweep Batch2b",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": [
            "Table 3/5 VT Sharpe and common-period values",
            "Table 4 time-zone strategy values",
            "Table 2 gamma rows and individual-stock legacy rows",
            "Section 3 spillover/TWD-USD",
            "Section 6 macro indicators",
            "Section 4.5 TSMC concentration",
            "Appendix overnight gap",
            "Section 7 VaR/skewed-t parameters",
        ],
        "research_honesty": {
            "paper_modified": False,
            "no_silent_value_changes": True,
            "no_new_estimation": True,
            "script_role": "reads existing JSON artifacts and classifies provenance; no live fetch; no random procedure",
            "seed_required": False,
        },
        "body_v3_loaded": str(BODY.relative_to(ROOT)),
        "body_v3_integrity_flags": {
            "twii_disputed_comment_present": section_present(r"DISPUTED PROVENANCE.*0\.272"),
            "individual_gamma_non_reproducible_comment_present": section_present(r"N121 NON-REPRODUCIBLE"),
            "table3_k1175_source_comment_present": "experiments/k1175/k1175_results.json" in body_text(),
            "table4_k1176_values_present": all(x in body_text() for x in ["1.915", "2.350", "2.192", "1.899"]),
        },
        "summary": {
            "n_checks": len(checks),
            "by_status": by_status,
            "by_group": by_group,
            "matched_or_caveated": len(checks) - len(unresolved),
            "unresolved_or_signoff": len(unresolved),
            "verdict": "PARTIAL_REPRODUCIBLE_WITH_SIGNOFF_ITEMS",
        },
        "unresolved_or_signoff_items": unresolved,
        "checks": checks,
        "next_actions": [
            "Do not silently rewrite body_v3 numbers. Manuscript changes require main-thread paper revision and owner sign-off.",
            "If owner approves, replace TWII gamma 0.272/3.18 and legacy individual-stock gamma rows with the dedicated provenance estimates.",
            "Run a dedicated macro import-growth experiment for G12 values and a dedicated TZ bootstrap/correlation experiment for -8.91bp, [0.65, 2.24], r=0.376.",
            "Extend K896 or add a small artifact to store skewed-t eta/lambda if those parameters remain in the manuscript.",
            "Either remove or formally reproduce the ex-TSMC Sharpe range 0.193-0.637.",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"ok": True, "out": str(OUT.relative_to(ROOT)), "summary": result["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
