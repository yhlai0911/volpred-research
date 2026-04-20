#!/usr/bin/env python3
"""Paper 10 (crypto-fear-channel) — Reproducibility check.

Scaffolded 2026-04-20 per pre-body review Gap E (`paper/crypto-fear-channel/
review_history/pre_body_v0/claude_pre_review.md`). Blocks review-stage gate
per `.claude/rules/paper-workflow.md` "Reproduce Gate — paper 不能進 review
stage 除非先通過 reproduce gate".

Reads paper-cited statistics from `experiments/k1025/k1025_results.json`
(primary spillover experiment) and validates against numbers claimed in
`body_v0_intro.tex`. Extends to K639 (BTC→SPY RV Granger) and K746b
(BTC vol asymmetrically Granger-causes VIX) once body sections cite those.

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

    # Table of paper claims (source: body_v0_intro.tex + abstract as of 2026-04-20
    # v0 draft). Update paper_value when body revises per pre_review H1/H3.
    paper_claims = [
        {
            "metric": "QR beta at tau=0.5 (VIX|BTC vol quantile slope, median)",
            "paper_value": 2.61,
            "source_path": "k1025.quantile_regression['0.5'].beta",
            "actual": k1025["quantile_regression"]["0.5"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "QR beta at tau=0.95 (upper-tail amplification)",
            "paper_value": 22.31,
            "source_path": "k1025.quantile_regression['0.95'].beta",
            "actual": k1025["quantile_regression"]["0.95"]["beta"],
            "tol_pct": 1.0,
        },
        {
            "metric": "QR beta at tau=0.05 (low-quantile — H3 sign reversal)",
            "paper_value": -2.86,
            "source_path": "k1025.quantile_regression['0.05'].beta",
            "actual": k1025["quantile_regression"]["0.05"]["beta"],
            "tol_pct": 2.0,
        },
        {
            "metric": "DM test t-statistic (BTC-ext vs BTC-AR baseline)",
            "paper_value": -0.98,
            "source_path": "k1025.forecast_evaluation.dm_stat",
            "actual": k1025["forecast_evaluation"]["dm_stat"],
            "tol_pct": 2.0,
        },
        {
            "metric": "COVID subperiod Granger F-statistic (structural watershed)",
            "paper_value": 11.05,
            "source_path": "k1025.subperiod_granger['2020 (COVID)'].F",
            "actual": k1025["subperiod_granger"]["2020 (COVID)"]["F"],
            "tol_pct": 1.0,
        },
        {
            "metric": "COVID subperiod n (small-sample caveat per M2)",
            "paper_value": 253,
            "source_path": "k1025.subperiod_granger['2020 (COVID)'].n",
            "actual": k1025["subperiod_granger"]["2020 (COVID)"]["n"],
            "tol_pct": 0.5,
        },
        {
            "metric": "DY net spillover index for BTC (net receiver)",
            "paper_value": -76.89,
            "source_path": "k1025.spillover_index.mean_net_btc",
            "actual": k1025["spillover_index"]["mean_net_btc"],
            "tol_pct": 1.0,
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
        "stage": "kickoff (body pending)",
        "notes": [
            "Scaffolded per pre-body review Gap E (claude_pre_review.md).",
            "Covers K1025 only; extend to K639 + K746b when body sections cite them.",
            "Pre-review H3 flagged QR beta sign reversal — paper body revision may change tau=0.5 framing.",
            "Pre-review H1 flagged asymmetric Granger lag coverage (1-5 not 1-10); body_v0_intro.tex abstract needs fix.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[write] {REPORT_PATH.relative_to(PROJECT)}")
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
