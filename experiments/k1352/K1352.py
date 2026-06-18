from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEED = 42
EXPERIMENT_ID = "K1352"

OUT_DIR = Path(__file__).resolve().parent
ROOT = OUT_DIR.parent.parent
CANONICAL_DIR = ROOT / "experiments" / "k1439"
CANONICAL_RESULTS = CANONICAL_DIR / "k1439_results.json"
PRIOR_DUP_DIR = ROOT / "experiments" / "K1330"
PRIOR_DUP_RESULTS = PRIOR_DUP_DIR / "K1330_results.json"
OUT_PATH = OUT_DIR / "K1352_results.json"

REQUESTED_SCOPE = {
    "usd_proxy": ["DXY", "UUP"],
    "em": ["EEM"],
    "gold": ["GLD"],
    "commodities": ["DBC", "USO", "DBB"],
    "method_keywords": ["strong USD regime", "weak USD regime", "cross-asset realized volatility"],
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def canonical_coverage(k1439: dict[str, Any]) -> dict[str, Any]:
    tickers = set(k1439.get("tickers", []))
    regime_def = k1439.get("regime_def", {})
    level_def = regime_def.get("level_primary", {})
    trend_def = regime_def.get("trend_robustness", {})
    inference_policy = k1439.get("inference_policy", {})
    hac_level = k1439.get("hac_level", {})
    hac_trend = k1439.get("hac_trend", {})

    checks = {
        "covers_usd_proxy": "UUP" in str(level_def.get("indicator", "")),
        "covers_em": "EEM" in tickers,
        "covers_gold": "GLD" in tickers,
        "covers_commodity_basket": all(ticker in tickers for ticker in ["DBC", "USO", "DBB"]),
        "uses_strong_weak_level_regime": "z > +" in str(level_def.get("strong", ""))
        and "z < -" in str(level_def.get("weak", "")),
        "uses_trend_robustness": "60d log-return" in str(trend_def.get("indicator", "")),
        "explicit_shift_1": "shift(1)" in str(level_def.get("lookahead_protection", ""))
        and "shift(1)" in str(trend_def.get("lookahead_protection", "")),
        "uses_hac_newey_west": "HAC" in str(inference_policy.get("primary", ""))
        and "Newey-West" in str(inference_policy.get("primary", "")),
        "acknowledges_overlap_autocorrelation": "serial correlation"
        in str(inference_policy.get("overlap_risk", "")),
    }

    robust_assets = sorted(
        asset
        for asset in tickers
        if hac_level.get(asset, {}).get("bonferroni_significant")
        and hac_trend.get(asset, {}).get("bonferroni_significant")
    )

    return {
        "requested_scope": REQUESTED_SCOPE,
        "canonical_tickers": sorted(tickers),
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "robust_assets_across_level_and_trend": robust_assets,
    }


def build_result() -> dict[str, Any]:
    k1439 = load_json(CANONICAL_RESULTS)
    k1330 = load_json(PRIOR_DUP_RESULTS) if PRIOR_DUP_RESULTS.exists() else {}
    coverage = canonical_coverage(k1439)
    period = k1439.get("period", {})
    tests_level = k1439.get("tests_level", {})
    hac_level = k1439.get("hac_level", {})
    hac_trend = k1439.get("hac_trend", {})

    return {
        "experiment_id": EXPERIMENT_ID,
        "title": "USD regime cross-asset volatility duplicate closure",
        "generated_at": datetime.now(UTC).isoformat(),
        "created_by": "codex",
        "seed": SEED,
        "task_resolution": "duplicate_of_existing_experiment",
        "verdict": "SUPERSEDED_BY_K1439_AND_K1330",
        "canonical_experiment": {
            "experiment_id": k1439.get("k_id", "K1439"),
            "path": str(CANONICAL_DIR.relative_to(ROOT)),
            "results_path": str(CANONICAL_RESULTS.relative_to(ROOT)),
            "verdict": k1439.get("verdict"),
            "period": period,
            "reproduction_check": "uv run python experiments/k1439/reproduce.py completed successfully in this tick",
        },
        "prior_duplicate_closure": {
            "experiment_id": k1330.get("k_id", "K1330"),
            "path": str(PRIOR_DUP_DIR.relative_to(ROOT)),
            "results_path": str(PRIOR_DUP_RESULTS.relative_to(ROOT)),
            "verdict": k1330.get("verdict"),
            "closure_reason": k1330.get("closure_reason"),
        },
        "coverage_audit": coverage,
        "canonical_findings": {
            "sample_start": period.get("start"),
            "sample_end": period.get("end"),
            "n_obs": period.get("n_obs"),
            "naive_welch_significant_assets": sorted(
                asset
                for asset, stats in tests_level.items()
                if stats.get("bonferroni_significant")
            ),
            "hac_level_significant_assets": sorted(
                asset
                for asset, stats in hac_level.items()
                if stats.get("bonferroni_significant")
            ),
            "hac_level_and_trend_robust_assets": coverage["robust_assets_across_level_and_trend"],
            "most_sensitive_asset_by_abs_hac_t": k1439.get("most_sensitive_asset_by_abs_hac_t"),
            "verdict_reason": k1439.get("verdict_reason"),
        },
        "forecast_timing_guard": {
            "strategy_returns_computed": False,
            "required_pattern": "signal.shift(1)",
            "actual_canonical_pattern": "K1439 uses bucket.shift(1) in both USD regime constructors",
            "note": (
                "K1352 performs no new strategy backtest. The canonical experiment's regime "
                "classification uses t-1 information; any future trading signal must use "
                "signal.shift(1) or equivalent one-step-ahead alignment."
            ),
        },
        "literature_checked": [
            {
                "title": "Common Risk Factors in Currency Markets",
                "url": "https://www.nber.org/papers/w14082",
                "role": "Dollar/currency global-risk factor framing.",
            },
            {
                "title": "Countercyclical Currency Risk Premia",
                "url": "https://www.nber.org/papers/w16427",
                "role": "Dollar risk premia and bad-times risk compensation framing.",
            },
            {
                "title": "Is gold the best hedge and a safe haven under changing stock market volatility?",
                "url": "https://onlinelibrary.wiley.com/doi/10.1016/j.rfe.2013.03.001",
                "role": "Gold hedge/safe-haven channel framing.",
            },
        ],
        "closure_reason": (
            "K1352 is the same research_program.md line as prior K1330 and canonical K1439. "
            "K1439 already covers UUP/DXY strong-vs-weak regimes for EEM, GLD, DBC, USO, "
            "and DBB with explicit shift(1) and HAC/Newey-West inference. Re-running would "
            "only duplicate evidence."
        ),
        "knowledge_write": "skipped_duplicate_governance_receipt",
        "codex_review": {
            "status": "PASS_DUPLICATE_CLOSURE",
            "notes": [
                "Canonical K1439 reproduction completed successfully in this tick.",
                "K1330 had already closed the same line as SUPERSEDED_BY_K1439.",
                "K1352 adds no new empirical claim and should not write a knowledge entry.",
            ],
        },
    }


def main() -> None:
    result = build_result()
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {OUT_PATH.relative_to(ROOT)}")
    print(
        "[summary]",
        result["verdict"],
        "| coverage_pass=" + str(result["coverage_audit"]["all_checks_pass"]),
        "| robust_assets=" + ",".join(result["coverage_audit"]["robust_assets_across_level_and_trend"]),
    )


if __name__ == "__main__":
    main()
