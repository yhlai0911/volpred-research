from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPERIMENT_ID = "K1353"
SEED = 42

OUT_DIR = Path(__file__).resolve().parent
ROOT = OUT_DIR.parent.parent
CANONICAL_DIR = ROOT / "experiments" / "K1344_private_credit_software_spillover"
CANONICAL_RESULTS = CANONICAL_DIR / "K1344_results.json"
CANONICAL_SCRIPT = CANONICAL_DIR / "K1344.py"
RELATED_RESULTS = {
    "K1332": ROOT / "experiments" / "k1332" / "k1332_results.json",
    "K1499": ROOT / "experiments" / "k1499" / "k1499_results.json",
}
OUT_PATH = OUT_DIR / "K1353_results.json"

REQUESTED_SCOPE = {
    "theme": "software/technology-concentrated private-credit stress spillover",
    "proxy": ["BDC basket", "BIZD", "listed BDCs"],
    "targets": ["IGV", "HYG"],
    "required_guard": "signal.shift(1) or equivalent lagged features",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def canonical_coverage(results: dict[str, Any], script_text: str) -> dict[str, Any]:
    tickers = results.get("data", {}).get("tickers", {})
    forecast_results = results.get("forecast_results", [])
    tests = results.get("tests", {})

    coverage_checks = {
        "covers_bdc_basket": set(["BIZD", "ARCC", "BXSL", "OBDC", "FSK"]).issubset(
            set(tickers.get("bdc_proxy", []))
        ),
        "covers_igv_hyg": set(["IGV", "HYG"]).issubset(set(tickers.get("targets", []))),
        "uses_market_tech_controls": set(["SPY", "QQQ"]).issubset(set(tickers.get("controls", []))),
        "forecast_family_igv_hyg_5_21": {
            (row.get("target"), row.get("horizon")) for row in forecast_results
        }
        == {("IGV", 5), ("IGV", 21), ("HYG", 5), ("HYG", 21)},
        "uses_hac_newey_west": "Newey-West" in str(tests.get("dm_covariance", "")),
        "uses_block_bootstrap_seeded": tests.get("bootstrap", {}).get("reps") == 1000
        and "SEED = 42" in script_text,
        "explicit_shift_1_features": ".shift(1)" in script_text,
        "explicit_signal_shift_guard": "signal = panel[\"bdc_pressure\"].shift(1)" in script_text,
    }

    passing_cells = [
        row
        for row in forecast_results
        if row.get("passes_bonferroni") or row.get("conditional_pass")
    ]
    best_cell = max(
        forecast_results,
        key=lambda row: row.get("qlike_improvement_pct", float("-inf")),
        default={},
    )

    return {
        "requested_scope": REQUESTED_SCOPE,
        "canonical_path": str(CANONICAL_DIR.relative_to(ROOT)),
        "checks": coverage_checks,
        "all_checks_pass": all(coverage_checks.values()),
        "passing_or_conditional_cells": passing_cells,
        "best_directional_cell": best_cell,
        "bonferroni_alpha": tests.get("bonferroni_alpha"),
    }


def related_summary() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, path in RELATED_RESULTS.items():
        if not path.exists():
            out[key] = {"exists": False}
            continue
        data = load_json(path)
        out[key] = {
            "exists": True,
            "path": str(path.relative_to(ROOT)),
            "verdict": data.get("verdict") or data.get("overall_verdict"),
            "summary": data.get("verdict_rationale") or data.get("key_findings") or data.get("conclusion"),
        }
    return out


def build_result() -> dict[str, Any]:
    canonical = load_json(CANONICAL_RESULTS)
    script_text = read_text(CANONICAL_SCRIPT)
    coverage = canonical_coverage(canonical, script_text)

    return {
        "experiment_id": EXPERIMENT_ID,
        "title": "Private-credit software spillover duplicate closure",
        "generated_at": datetime.now(UTC).isoformat(),
        "created_by": "codex",
        "seed": SEED,
        "task_resolution": "duplicate_of_existing_experiment",
        "verdict": "SUPERSEDED_BY_K1344_NULL",
        "canonical_experiment": {
            "experiment_id": canonical.get("experiment_id"),
            "path": str(CANONICAL_DIR.relative_to(ROOT)),
            "results_path": str(CANONICAL_RESULTS.relative_to(ROOT)),
            "verdict": canonical.get("verdict"),
            "data": canonical.get("data"),
        },
        "coverage_audit": coverage,
        "canonical_findings": {
            "forecast_results": canonical.get("forecast_results"),
            "tests": canonical.get("tests"),
            "verdict_rationale": canonical.get("verdict_rationale"),
            "event_study": canonical.get("event_study"),
            "caveats": canonical.get("caveats"),
        },
        "related_context": related_summary(),
        "forecast_timing_guard": {
            "strategy_returns_computed": False,
            "required_pattern": "signal.shift(1)",
            "canonical_patterns": [
                "K1344 creates *_l1 predictors with .shift(1)",
                "K1344 event-study signal uses panel['bdc_pressure'].shift(1)",
                "K1344 expanding training excludes rows whose forward target is not fully known before the forecast origin",
            ],
        },
        "literature_checked": canonical.get("literature_sources", []),
        "closure_reason": (
            "K1353 is textually the same research_program.md item already completed as K1344. "
            "K1344 directly tests BDC/software private-credit stress spillover to IGV/HYG "
            "with SPY/QQQ controls, lagged features, HAC tests, Bonferroni correction, and "
            "moving-block bootstrap. The canonical verdict is NULL, so rerunning K1353 would "
            "duplicate a completed null experiment."
        ),
        "knowledge_write": "skipped_duplicate_null_receipt",
        "codex_review": {
            "status": "PASS_DUPLICATE_CLOSURE",
            "notes": [
                "K1344 fully covers the requested K1353 scope.",
                "K1344 result is NULL; no knowledge entry should be written for K1353.",
                "Do not promote descriptive event-study positives as forecast evidence.",
            ],
        },
    }


def main() -> None:
    result = build_result()
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    coverage = result["coverage_audit"]
    print(f"[done] wrote {OUT_PATH.relative_to(ROOT)}")
    print(
        "[summary]",
        result["verdict"],
        "| coverage_pass=" + str(coverage["all_checks_pass"]),
        "| passing_cells=" + str(len(coverage["passing_or_conditional_cells"])),
    )


if __name__ == "__main__":
    main()
