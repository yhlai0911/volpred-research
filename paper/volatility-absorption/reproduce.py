#!/usr/bin/env python3
"""Paper 8 (volatility-absorption) reproducibility gate for active v3 scope."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
PAPER_DIR = Path(__file__).resolve().parent
REPORT_PATH = PAPER_DIR / "reproduce_report.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def rel_diff(actual: float, paper: float) -> float:
    if paper == 0:
        return 0.0
    return abs(actual - paper) / abs(paper) * 100


def approx(actual: float, paper: float, tol_pct: float) -> bool:
    if paper == 0:
        return abs(actual) < 1e-12
    return rel_diff(actual, paper) <= tol_pct


def main() -> int:
    k716 = load_json(PAPER_DIR / "experiments" / "k716_results.json")
    k741 = load_json(PAPER_DIR / "experiments" / "k741_nfp_event_study_results.json")
    k897 = load_json(PAPER_DIR / "experiments" / "k897_sar_null_simulation_results.json")
    k903 = load_json(PROJECT / "experiments" / "k903" / "k903_paper8_robustness_results.json")
    k1418 = load_json(PROJECT / "experiments" / "k1418" / "k1418_results.json")

    cross_asset = {row["asset"]: row for row in k1418["results"]}

    claims = [
        ("T3 calm SAR", 3.16, k716["calm (<15)"]["ratio"], 1.0, "k716.calm (<15).ratio"),
        ("T3 normal SAR", 2.77, k716["normal (15-20)"]["ratio"], 1.0, "k716.normal (15-20).ratio"),
        ("T3 elevated SAR", 2.37, k716["elevated (20-25)"]["ratio"], 1.0, "k716.elevated (20-25).ratio"),
        ("T3 high SAR", 2.32, k716["high (25-30)"]["ratio"], 1.0, "k716.high (25-30).ratio"),
        ("T3 crisis SAR", 2.43, k716["crisis (>30)"]["ratio"], 1.0, "k716.crisis (>30).ratio"),
        ("K897 empirical decline", 0.816, k897["sar_decline_comparison"]["empirical_decline"], 1.0, "k897.sar_decline_comparison.empirical_decline"),
        ("K897 sim CI low", -0.281, k897["sar_decline_comparison"]["sim_ci_95"][0], 1.0, "k897.sar_decline_comparison.sim_ci_95[0]"),
        ("K897 sim CI high", 0.558, k897["sar_decline_comparison"]["sim_ci_95"][1], 1.0, "k897.sar_decline_comparison.sim_ci_95[1]"),
        ("K897 regimes outside CI", 5.0, float(k897["regimes_outside_ci"].split("/")[0]), 0.0, "k897.regimes_outside_ci"),
        ("T4 SPY beta", -0.000273, cross_asset["SPY"]["beta"], 1.0, "k1418.results[SPY].beta"),
        ("T4 SPY t", -1.85, cross_asset["SPY"]["beta_t"], 2.0, "k1418.results[SPY].beta_t"),
        ("T4 GLD beta", -0.000434, cross_asset["GLD"]["beta"], 1.0, "k1418.results[GLD].beta"),
        ("T4 GLD t", -2.90, cross_asset["GLD"]["beta_t"], 2.0, "k1418.results[GLD].beta_t"),
        ("T4 TLT beta", -0.000437, cross_asset["TLT"]["beta"], 1.0, "k1418.results[TLT].beta"),
        ("T4 TLT t", -3.31, cross_asset["TLT"]["beta_t"], 2.0, "k1418.results[TLT].beta_t"),
        ("T4 0050 beta", 0.000092, cross_asset["0050.TW"]["beta"], 2.0, "k1418.results[0050.TW].beta"),
        ("T5 Low NFP n", 62.0, float(k741["part_b_vix_regimes"]["Low (VIX<15)"]["n"]), 0.0, "k741.part_b_vix_regimes.Low.n"),
        ("T5 Low NFP mean abs", 0.498, k741["part_b_vix_regimes"]["Low (VIX<15)"]["mean_abs_return_pct"], 1.0, "k741.part_b_vix_regimes.Low.mean_abs_return_pct"),
        ("T5 Medium NFP mean abs", 0.757, k741["part_b_vix_regimes"]["Medium (15-20)"]["mean_abs_return_pct"], 1.0, "k741.part_b_vix_regimes.Medium.mean_abs_return_pct"),
        ("T5 High NFP mean abs", 1.488, k741["part_b_vix_regimes"]["High (VIX>=25)"]["mean_abs_return_pct"], 1.0, "k741.part_b_vix_regimes.High.mean_abs_return_pct"),
        ("Baseline beta", -0.000267, k903["baseline_regression"]["beta_hat"], 1.0, "k903.baseline_regression.beta_hat"),
        ("Baseline t", -1.77, k903["baseline_regression"]["t_stat_NW"], 2.0, "k903.baseline_regression.t_stat_NW"),
        ("T9 tau=2 N", 768.0, float(k903["task2_table9_alternative_thresholds"]["2.0"]["N_shock"]), 0.0, "k903.task2_table9_alternative_thresholds.2.0.N_shock"),
        ("T9 tau=3 beta", -0.000311, k903["task2_table9_alternative_thresholds"]["3.0"]["beta_hat"], 1.0, "k903.task2_table9_alternative_thresholds.3.0.beta_hat"),
        ("T10 2006-2012 beta", -0.000408, k903["task2_table10_subperiod"]["2006-2012 (GFC era)"]["beta_hat"], 1.0, "k903.task2_table10_subperiod.2006-2012.beta_hat"),
        ("T10 2020-2026 beta", 0.000141, k903["task2_table10_subperiod"]["2020-2026 (COVID era)"]["beta_hat"], 1.0, "k903.task2_table10_subperiod.2020-2026.beta_hat"),
        ("RV-normalized beta", -0.01249, k903["task2_rv_normalization"]["beta_hat"], 1.0, "k903.task2_rv_normalization.beta_hat"),
        ("RV-normalized t", -8.2, k903["task2_rv_normalization"]["t_stat_NW"], 1.0, "k903.task2_rv_normalization.t_stat_NW"),
        ("Controlled beta", -0.000216, k903["task2_controlled_regression"]["beta_VIX"], 1.0, "k903.task2_controlled_regression.beta_VIX"),
        ("Controlled t", -1.26, k903["task2_controlled_regression"]["t_stat_VIX"], 2.0, "k903.task2_controlled_regression.t_stat_VIX"),
    ]

    checks = []
    for metric, paper_value, actual_value, tol_pct, source_path in claims:
        checks.append(
            {
                "metric": metric,
                "paper_value": paper_value,
                "actual_value": actual_value,
                "tol_pct": tol_pct,
                "rel_diff_pct": rel_diff(actual_value, paper_value),
                "status": "match" if approx(actual_value, paper_value, tol_pct) else "mismatch",
                "source_path": source_path,
            }
        )

    total = len(checks)
    matched = sum(1 for c in checks if c["status"] == "match")
    match_rate = matched / total * 100 if total else 0.0
    alert_level = "green" if match_rate >= 95 else ("amber" if match_rate >= 80 else "red")
    gate_status = "pass" if match_rate >= 95 else "fail"

    print(f"{'Metric':<34} {'Paper':>12} {'Actual':>12} {'diff %':>8} {'status':>10}")
    print("-" * 84)
    for c in checks:
        print(f"{c['metric'][:32]:<34} {c['paper_value']:>12.6f} {c['actual_value']:>12.6f} {c['rel_diff_pct']:>7.2f}% {c['status']:>10}")
    print("-" * 84)
    print(f"Matched: {matched}/{total}  rate: {match_rate:.1f}%  alert: {alert_level}  gate: {gate_status}")

    report = {
        "paper": "volatility-absorption",
        "paper_version": "v3-active-scope",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "alert_level": alert_level,
        "gate_status": gate_status,
        "match_rate": round(match_rate / 100, 4),
        "verification_rate": f"{match_rate:.1f}%",
        "total_checks": total,
        "matches": matched,
        "mismatches": total - matched,
        "critical_flags": [
            "Active gate restricted to reproducible evidence retained in main_v3.tex",
            "Legacy shock-type / VRP / hedging tables intentionally excluded pending pinned-snapshot rebuild",
        ],
        "checks": checks,
        "notes": [
            "Coverage: T3 SAR, K897 null simulation, T4 pinned cross-asset, T5 NFP, baseline NSI, T9 thresholds, T10 subperiods, RV-normalized and controlled regressions.",
            "This gate no longer validates legacy deferred sections that lack stable JSON bindings under the current pinned snapshot.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[write] {REPORT_PATH.relative_to(PROJECT)}")
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
