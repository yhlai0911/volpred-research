#!/usr/bin/env python3
"""Paper 10 (crypto-fear-channel) — Reproducibility check.

Validates numbers cited in the active `main.tex` against
`experiments/k1025/k1025_v2_results.json`.

Coverage reflects the current major-revision manuscript scope:
- T1 Descriptive statistics
- T2 Asymmetric Granger
- T3 Quantile regression coefficients / bootstrap intervals
- T4 5-subperiod Granger
- T5 EWMA-by-regime correlation
- Spillover summary
- T6 OOS forecast evaluation

Legacy K1025b cross-asset checks were removed after that section was downgraded
to deferred work pending a method-symmetric rerun.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
PAPER_DIR = Path(__file__).resolve().parent
EXP_DIR = PROJECT / "experiments"
REPORT_PATH = PAPER_DIR / "reproduce_report.json"


def _load(rel_path: str) -> dict:
    path = EXP_DIR / rel_path
    if not path.exists():
        raise FileNotFoundError(f"missing: {path}")
    return json.loads(path.read_text())


def _approx(actual: float, paper: float, tol_pct: float = 1.0) -> bool:
    if paper == 0:
        return abs(actual) < 1e-12
    return abs(actual - paper) / abs(paper) * 100 <= tol_pct


def _rel_diff(actual: float, paper: float) -> float:
    if paper == 0:
        return 0.0
    return abs(actual - paper) / abs(paper) * 100


def main() -> int:
    k1025 = _load("k1025/k1025_v2_results.json")

    paper_claims = [
        {
            "metric": "Sample N (§3.1, abstract)",
            "paper_value": 2812,
            "source_path": "k1025_v2.n_observations",
            "actual": k1025["n_observations"],
            "tol_pct": 0.0,
        },
        {
            "metric": "T1: btc_ret mean (%)",
            "paper_value": 0.158,
            "source_path": "k1025_v2.descriptive_statistics.btc_ret.mean (×100)",
            "actual": k1025["descriptive_statistics"]["btc_ret"]["mean"] * 100,
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: btc_ret std (%)",
            "paper_value": 3.790,
            "source_path": "k1025_v2.descriptive_statistics.btc_ret.std (×100)",
            "actual": k1025["descriptive_statistics"]["btc_ret"]["std"] * 100,
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: btc_ret excess kurtosis",
            "paper_value": 11.826,
            "source_path": "k1025_v2.descriptive_statistics.btc_ret.kurtosis",
            "actual": k1025["descriptive_statistics"]["btc_ret"]["kurtosis"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: spy_ret excess kurtosis",
            "paper_value": 14.150,
            "source_path": "k1025_v2.descriptive_statistics.spy_ret.kurtosis",
            "actual": k1025["descriptive_statistics"]["spy_ret"]["kurtosis"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: VIX mean",
            "paper_value": 18.382,
            "source_path": "k1025_v2.descriptive_statistics.vix.mean",
            "actual": k1025["descriptive_statistics"]["vix"]["mean"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: VIX max",
            "paper_value": 82.69,
            "source_path": "k1025_v2.descriptive_statistics.vix.max",
            "actual": k1025["descriptive_statistics"]["vix"]["max"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: VIX min",
            "paper_value": 9.14,
            "source_path": "k1025_v2.descriptive_statistics.vix.min",
            "actual": k1025["descriptive_statistics"]["vix"]["min"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T2: BTC- → VIX lag 1 F-stat",
            "paper_value": 21.78,
            "source_path": "k1025_v2.asymmetric_granger.btc_neg_to_vix.1.F",
            "actual": k1025["asymmetric_granger"]["btc_neg_to_vix"]["1"]["F"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T2: BTC- → VIX lag 5 F-stat",
            "paper_value": 8.27,
            "source_path": "k1025_v2.asymmetric_granger.btc_neg_to_vix.5.F",
            "actual": k1025["asymmetric_granger"]["btc_neg_to_vix"]["5"]["F"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T2: BTC+ → VIX lag 1 F-stat",
            "paper_value": 2.04,
            "source_path": "k1025_v2.asymmetric_granger.btc_pos_to_vix.1.F",
            "actual": k1025["asymmetric_granger"]["btc_pos_to_vix"]["1"]["F"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T2: BTC+ → VIX lag 5 p-value",
            "paper_value": 0.919,
            "source_path": "k1025_v2.asymmetric_granger.btc_pos_to_vix.5.p",
            "actual": k1025["asymmetric_granger"]["btc_pos_to_vix"]["5"]["p"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T3: QR beta tau=0.05",
            "paper_value": -2.78,
            "source_path": "k1025_v2.quantile_regression['0.05'].beta",
            "actual": k1025["quantile_regression"]["0.05"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR beta tau=0.25",
            "paper_value": -2.12,
            "source_path": "k1025_v2.quantile_regression['0.25'].beta",
            "actual": k1025["quantile_regression"]["0.25"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR beta tau=0.50",
            "paper_value": 2.82,
            "source_path": "k1025_v2.quantile_regression['0.5'].beta",
            "actual": k1025["quantile_regression"]["0.5"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR beta tau=0.75",
            "paper_value": 9.39,
            "source_path": "k1025_v2.quantile_regression['0.75'].beta",
            "actual": k1025["quantile_regression"]["0.75"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR beta tau=0.95",
            "paper_value": 19.85,
            "source_path": "k1025_v2.quantile_regression['0.95'].beta",
            "actual": k1025["quantile_regression"]["0.95"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR 95% CI tau=0.05 lower",
            "paper_value": -3.32,
            "source_path": "k1025_v2.quantile_regression['0.05'].ci_lo",
            "actual": k1025["quantile_regression"]["0.05"]["ci_lo"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR 95% CI tau=0.95 upper",
            "paper_value": 23.21,
            "source_path": "k1025_v2.quantile_regression['0.95'].ci_hi",
            "actual": k1025["quantile_regression"]["0.95"]["ci_hi"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T4: 2015-2017 Granger F",
            "paper_value": 2.88,
            "source_path": "k1025_v2.subperiod_granger['2015-2017 (Pre-mania)'].F",
            "actual": k1025["subperiod_granger"]["2015-2017 (Pre-mania)"]["F"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T4: 2018-2019 Granger F",
            "paper_value": 0.37,
            "source_path": "k1025_v2.subperiod_granger['2018-2019 (Crypto winter)'].F",
            "actual": k1025["subperiod_granger"]["2018-2019 (Crypto winter)"]["F"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T4: 2020 Granger F",
            "paper_value": 12.31,
            "source_path": "k1025_v2.subperiod_granger['2020 (COVID)'].F",
            "actual": k1025["subperiod_granger"]["2020 (COVID)"]["F"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T4: 2021-2022 Granger F",
            "paper_value": 2.03,
            "source_path": "k1025_v2.subperiod_granger['2021-2022 (Bull-Bear)'].F",
            "actual": k1025["subperiod_granger"]["2021-2022 (Bull-Bear)"]["F"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T4: 2023-2026 Granger F",
            "paper_value": 0.16,
            "source_path": "k1025_v2.subperiod_granger['2023-2026 (Recovery+ETF)'].F",
            "actual": k1025["subperiod_granger"]["2023-2026 (Recovery+ETF)"]["F"],
            "tol_pct": 5.0,
        },
        {
            "metric": "T5: EWMA Low regime mean correlation",
            "paper_value": 0.068,
            "source_path": "k1025_v2.dcc_correlation_by_regime.Low.mean",
            "actual": k1025["dcc_correlation_by_regime"]["Low"]["mean"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T5: EWMA Crisis regime mean correlation",
            "paper_value": 0.409,
            "source_path": "k1025_v2.dcc_correlation_by_regime.Crisis.mean",
            "actual": k1025["dcc_correlation_by_regime"]["Crisis"]["mean"],
            "tol_pct": 1.0,
        },
        {
            "metric": "DY: total spillover mean (%)",
            "paper_value": 90.11,
            "source_path": "k1025_v2.spillover_index.mean_total",
            "actual": k1025["spillover_index"]["mean_total"],
            "tol_pct": 0.5,
        },
        {
            "metric": "DY: total spillover std (%)",
            "paper_value": 0.22,
            "source_path": "k1025_v2.spillover_index.std_total",
            "actual": k1025["spillover_index"]["std_total"],
            "tol_pct": 5.0,
        },
        {
            "metric": "DY: BTC net spillover (pp)",
            "paper_value": -74.41,
            "source_path": "k1025_v2.spillover_index.mean_net_btc",
            "actual": k1025["spillover_index"]["mean_net_btc"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T6: OOS DM t-stat",
            "paper_value": -1.14,
            "source_path": "k1025_v2.forecast_evaluation.dm_stat_harvey",
            "actual": k1025["forecast_evaluation"]["dm_stat_harvey"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T6: AR baseline MSE",
            "paper_value": 4.649,
            "source_path": "k1025_v2.forecast_evaluation.mse_ar",
            "actual": k1025["forecast_evaluation"]["mse_ar"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T6: OOS N",
            "paper_value": 1826,
            "source_path": "k1025_v2.forecast_evaluation.oos_n",
            "actual": k1025["forecast_evaluation"]["oos_n"],
            "tol_pct": 0.0,
        },
    ]

    checks = []
    for claim in paper_claims:
        match = _approx(claim["actual"], claim["paper_value"], claim["tol_pct"])
        checks.append(
            {
                "metric": claim["metric"],
                "paper_value": claim["paper_value"],
                "actual_value": claim["actual"],
                "tol_pct": claim["tol_pct"],
                "rel_diff_pct": _rel_diff(claim["actual"], claim["paper_value"]),
                "status": "match" if match else "mismatch",
                "source_path": claim["source_path"],
            }
        )

    total = len(checks)
    matched = sum(1 for c in checks if c["status"] == "match")
    match_rate = (matched / total) * 100 if total else 0.0
    alert_level = "green" if match_rate >= 95 else ("amber" if match_rate >= 80 else "red")
    gate_status = "pass" if match_rate >= 95 else "fail"

    print(f"{'Metric':<52} {'Paper':>10} {'Actual':>10} {'diff %':>8} {'status':>10}")
    print("-" * 96)
    for c in checks:
        print(
            f"{c['metric'][:50]:<52} {c['paper_value']:>10.3f} "
            f"{c['actual_value']:>10.3f} {c['rel_diff_pct']:>7.2f}% {c['status']:>10}"
        )
    print("-" * 96)
    print(f"Matched: {matched}/{total}  rate: {match_rate:.1f}%  alert: {alert_level}  gate: {gate_status}")

    report = {
        "paper_id": "crypto-fear-channel",
        "paper_title": "The Crypto Fear Channel — Asymmetric BTC-Equity Volatility Spillover",
        "target_journal": "JIMFIM / JEF / FRL",
        "alert_level": alert_level,
        "gate_status": gate_status,
        "match_rate_pct": round(match_rate, 1),
        "matched": matched,
        "total_checks": total,
        "checks": checks,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "major-revision manuscript after 2026-06-11 audit sync",
        "notes": [
            "2026-06-11 gate scope aligned to the active manuscript after removing legacy K1025b claims.",
            "Coverage: T1 Descriptive / T2 Asymmetric Granger / T3 QR coeff+CI / "
            "T4 5-subperiod Granger / T5 EWMA by regime / Spillover / T6 OOS forecast.",
            "Per .claude/rules/paper-workflow.md hard rule 3: each table row or numeric body claim "
            "kept in the manuscript has a traceable JSON field path in source_path.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[write] {REPORT_PATH.relative_to(PROJECT)}")
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
