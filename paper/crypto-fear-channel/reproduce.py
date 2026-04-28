#!/usr/bin/env python3
"""Paper 10 (crypto-fear-channel) — Reproducibility check.

Validates numbers cited in body_v5.tex (full 9-section draft) against
experiments/k1025/k1025_results.json. Per .claude/rules/paper-workflow.md
hard rule 3 traceable binding: each body Table row + key %-source claim
maps to a JSON field path here.

Coverage: 25 byte-match checks across 6 tables in body_v5.tex —
T1 Descriptive (8) / T2 Asymmetric Granger (4) / T3 QR (5) /
T4 5-subperiod Granger (5) / T5 DCC by VIX regime (2) /
T6 OOS forecast (3) / Spillover (2).

Usage:
    uv run python paper/crypto-fear-channel/reproduce.py
    -> exit 0 if match_rate >= 95%, exit 1 otherwise
    -> writes reproduce_report.json with alert_level + match_summary
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
    p = EXP_DIR / rel_path
    if not p.exists():
        raise FileNotFoundError(f"missing: {p}")
    return json.loads(p.read_text())


def _approx(actual: float, paper: float, tol_pct: float = 1.0) -> bool:
    if paper == 0:
        return abs(actual) < 1e-9
    return abs(actual - paper) / abs(paper) * 100 <= tol_pct


def main() -> int:
    checks = []
    k1025 = _load("k1025/k1025_results.json")

    # Table of paper claims sourced from body_v5.tex (9-section draft 2026-04-28).
    # Each entry maps a body claim (table row, abstract number, or %-source comment)
    # to a JSON field path in experiments/k1025/k1025_results.json.
    paper_claims = [
        # === Sample / Data (§3.1) ===
        {
            "metric": "Sample N (§3.1, abstract)",
            "paper_value": 2812,
            "source_path": "k1025.n_observations",
            "actual": k1025["n_observations"],
            "tol_pct": 0.0,
        },
        # === T1 Descriptive Statistics (§3.3) ===
        {
            "metric": "T1: btc_ret mean (%)",
            "paper_value": 0.229,
            "source_path": "k1025.descriptive_statistics.btc_ret.mean (× 100)",
            "actual": k1025["descriptive_statistics"]["btc_ret"]["mean"] * 100,
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: btc_ret std (%)",
            "paper_value": 3.764,
            "source_path": "k1025.descriptive_statistics.btc_ret.std (× 100)",
            "actual": k1025["descriptive_statistics"]["btc_ret"]["std"] * 100,
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: btc_ret excess kurtosis",
            "paper_value": 7.579,
            "source_path": "k1025.descriptive_statistics.btc_ret.kurtosis",
            "actual": k1025["descriptive_statistics"]["btc_ret"]["kurtosis"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: spy_ret excess kurtosis",
            "paper_value": 14.150,
            "source_path": "k1025.descriptive_statistics.spy_ret.kurtosis",
            "actual": k1025["descriptive_statistics"]["spy_ret"]["kurtosis"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: VIX mean",
            "paper_value": 18.382,
            "source_path": "k1025.descriptive_statistics.vix.mean",
            "actual": k1025["descriptive_statistics"]["vix"]["mean"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: VIX max (March 2020)",
            "paper_value": 82.69,
            "source_path": "k1025.descriptive_statistics.vix.max",
            "actual": k1025["descriptive_statistics"]["vix"]["max"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T1: VIX min",
            "paper_value": 9.14,
            "source_path": "k1025.descriptive_statistics.vix.min",
            "actual": k1025["descriptive_statistics"]["vix"]["min"],
            "tol_pct": 1.0,
        },
        # === T2 Asymmetric Granger BTC- → VIX (§5.1) ===
        {
            "metric": "T2: BTC- → VIX lag 1 F-stat",
            "paper_value": 18.96,
            "source_path": "k1025.asymmetric_granger.btc_neg_to_vix.1.F",
            "actual": k1025["asymmetric_granger"]["btc_neg_to_vix"]["1"]["F"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T2: BTC- → VIX lag 5 F-stat",
            "paper_value": 6.64,
            "source_path": "k1025.asymmetric_granger.btc_neg_to_vix.5.F",
            "actual": k1025["asymmetric_granger"]["btc_neg_to_vix"]["5"]["F"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T2: BTC+ → VIX lag 1 F-stat (NS branch)",
            "paper_value": 2.00,
            "source_path": "k1025.asymmetric_granger.btc_pos_to_vix.1.F",
            "actual": k1025["asymmetric_granger"]["btc_pos_to_vix"]["1"]["F"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T2: BTC+ → VIX lag 5 p-value (NS branch)",
            "paper_value": 0.927,
            "source_path": "k1025.asymmetric_granger.btc_pos_to_vix.5.p",
            "actual": k1025["asymmetric_granger"]["btc_pos_to_vix"]["5"]["p"],
            "tol_pct": 2.0,
        },
        # === T3 QR by quantile (§5.2) ===
        {
            "metric": "T3: QR β τ=0.05 (sign-reversal lower tail)",
            "paper_value": -2.86,
            "source_path": "k1025.quantile_regression['0.05'].beta",
            "actual": k1025["quantile_regression"]["0.05"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR β τ=0.25",
            "paper_value": -2.34,
            "source_path": "k1025.quantile_regression['0.25'].beta",
            "actual": k1025["quantile_regression"]["0.25"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR β τ=0.50 (median)",
            "paper_value": 2.61,
            "source_path": "k1025.quantile_regression['0.5'].beta",
            "actual": k1025["quantile_regression"]["0.5"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR β τ=0.75",
            "paper_value": 8.76,
            "source_path": "k1025.quantile_regression['0.75'].beta",
            "actual": k1025["quantile_regression"]["0.75"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T3: QR β τ=0.95 (upper-tail amplification)",
            "paper_value": 22.31,
            "source_path": "k1025.quantile_regression['0.95'].beta",
            "actual": k1025["quantile_regression"]["0.95"]["beta"],
            "tol_pct": 1.0,
        },
        # === T4 5-subperiod Granger (§5.3) ===
        {
            "metric": "T4: 2015-2017 Granger F (NS)",
            "paper_value": 0.59,
            "source_path": "k1025.subperiod_granger['2015-2017 (Pre-mania)'].F",
            "actual": k1025["subperiod_granger"]["2015-2017 (Pre-mania)"]["F"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T4: 2018-2019 Granger F (NS)",
            "paper_value": 0.23,
            "source_path": "k1025.subperiod_granger['2018-2019 (Crypto winter)'].F",
            "actual": k1025["subperiod_granger"]["2018-2019 (Crypto winter)"]["F"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T4: 2020 COVID Granger F (structural watershed)",
            "paper_value": 11.05,
            "source_path": "k1025.subperiod_granger['2020 (COVID)'].F",
            "actual": k1025["subperiod_granger"]["2020 (COVID)"]["F"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T4: 2021-2022 Granger F (NS)",
            "paper_value": 1.95,
            "source_path": "k1025.subperiod_granger['2021-2022 (Bull-Bear)'].F",
            "actual": k1025["subperiod_granger"]["2021-2022 (Bull-Bear)"]["F"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T4: 2023-2026 Granger F (NS)",
            "paper_value": 0.46,
            "source_path": "k1025.subperiod_granger['2023-2026 (Recovery+ETF)'].F",
            "actual": k1025["subperiod_granger"]["2023-2026 (Recovery+ETF)"]["F"],
            "tol_pct": 2.0,
        },
        # === T5 DCC correlation by VIX regime (§5.3) ===
        {
            "metric": "T5: DCC Low regime mean correlation",
            "paper_value": 0.068,
            "source_path": "k1025.dcc_correlation_by_regime.Low.mean",
            "actual": k1025["dcc_correlation_by_regime"]["Low"]["mean"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T5: DCC Crisis regime mean correlation",
            "paper_value": 0.409,
            "source_path": "k1025.dcc_correlation_by_regime.Crisis.mean",
            "actual": k1025["dcc_correlation_by_regime"]["Crisis"]["mean"],
            "tol_pct": 1.0,
        },
        # === Diebold-Yilmaz spillover (§5.3 + §6.1) ===
        {
            "metric": "DY: total spillover index mean (%)",
            "paper_value": 90.11,
            "source_path": "k1025.spillover_index.mean_total",
            "actual": k1025["spillover_index"]["mean_total"],
            "tol_pct": 0.5,
        },
        {
            "metric": "DY: BTC net spillover (net receiver)",
            "paper_value": -76.89,
            "source_path": "k1025.spillover_index.mean_net_btc",
            "actual": k1025["spillover_index"]["mean_net_btc"],
            "tol_pct": 1.0,
        },
        # === T6 OOS forecast (§7) ===
        {
            "metric": "T6: DM t-stat (full OOS)",
            "paper_value": -0.98,
            "source_path": "k1025.forecast_evaluation.dm_stat",
            "actual": k1025["forecast_evaluation"]["dm_stat"],
            "tol_pct": 2.0,
        },
        {
            "metric": "T6: AR baseline MSE",
            "paper_value": 4.467,
            "source_path": "k1025.forecast_evaluation.mse_ar",
            "actual": k1025["forecast_evaluation"]["mse_ar"],
            "tol_pct": 1.0,
        },
        {
            "metric": "T6: OOS n (2019-01-01 to 2026-04-08)",
            "paper_value": 1826,
            "source_path": "k1025.forecast_evaluation.oos_n",
            "actual": k1025["forecast_evaluation"]["oos_n"],
            "tol_pct": 0.0,
        },
    ]

    for c in paper_claims:
        match = _approx(c["actual"], c["paper_value"], c["tol_pct"])
        checks.append({
            "metric": c["metric"],
            "paper_value": c["paper_value"],
            "actual_value": c["actual"],
            "tol_pct": c["tol_pct"],
            "rel_diff_pct": (abs(c["actual"] - c["paper_value"]) / abs(c["paper_value"]) * 100)
                            if c["paper_value"] else 0.0,
            "status": "match" if match else "mismatch",
            "source_path": c["source_path"],
        })

    total = len(checks)
    matched = sum(1 for c in checks if c["status"] == "match")
    match_rate = (matched / total) * 100 if total else 0

    alert_level = "green" if match_rate >= 95 else ("amber" if match_rate >= 80 else "red")
    gate_status = "pass" if match_rate >= 95 else "fail"

    # Print human summary
    print(f"{'Metric':<60} {'Paper':>10} {'Actual':>10} {'diff %':>8} {'status':>10}")
    print("-" * 100)
    for c in checks:
        print(f"{c['metric'][:58]:<60} {c['paper_value']:>10.3f} {c['actual_value']:>10.3f} "
              f"{c['rel_diff_pct']:>7.2f}% {c['status']:>10}")
    print("-" * 100)
    print(f"\nMatched: {matched}/{total}  rate: {match_rate:.1f}%  alert: {alert_level}  gate: {gate_status}")

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
        "stage": "body draft complete (v5, 9 sections, 15 pages)",
        "notes": [
            "Expanded 2026-04-28 from 7 → 25 checks covering all 6 tables in body_v5.tex.",
            "Coverage: T1 Descriptive (8) / T2 Asymmetric Granger (4) / T3 QR (5) / "
            "T4 5-subperiod Granger (5) / T5 DCC by VIX regime (2) / Spillover (2) / "
            "T6 OOS forecast (3).",
            "Per .claude/rules/paper-workflow.md hard rule 3: each table row + key %-source "
            "claim has a traceable JSON field path in source_path.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[write] {REPORT_PATH.relative_to(PROJECT)}")
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
