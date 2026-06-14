from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

SEED = 42

OUT_DIR = Path(__file__).resolve().parent
ROOT = OUT_DIR.parent.parent
CANONICAL_DIR = ROOT / "experiments" / "k1439"
CANONICAL_RESULTS = CANONICAL_DIR / "k1439_results.json"
OUT_PATH = OUT_DIR / "K1330_results.json"

REQUESTED_BUCKETS = {
    "usd_proxy": ["UUP", "DXY"],
    "em": ["EEM"],
    "gold": ["GLD"],
    "commodities": ["DBC", "DBB", "USO"],
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def canonical_coverage(results: dict) -> dict:
    tickers = set(results.get("tickers", []))
    hac_level = results.get("hac_level", {})
    hac_trend = results.get("hac_trend", {})
    regime_def = results.get("regime_def", {})
    inference_policy = results.get("inference_policy", {})
    level_def = regime_def.get("level_primary", {})
    trend_def = regime_def.get("trend_robustness", {})
    primary_inference = inference_policy.get("primary", "")
    overlap_note = inference_policy.get("overlap_risk", "")

    overlap = {
        "covers_em": "EEM" in tickers,
        "covers_gold": "GLD" in tickers,
        "covers_commodities": all(t in tickers for t in ["DBC", "DBB", "USO"]),
        "uses_usd_proxy_uup": "UUP" in str(level_def.get("indicator", "")),
        "uses_shift_1": all(
            "shift(1)" in str(defn.get("lookahead_protection", ""))
            for defn in [level_def, trend_def]
        ),
        "uses_hac_inference": "HAC" in primary_inference and "Newey-West" in primary_inference,
        "acknowledges_overlap_risk": "serial correlation" in overlap_note,
    }

    robust_assets = sorted(
        asset
        for asset in tickers
        if hac_level.get(asset, {}).get("bonferroni_significant")
        and hac_trend.get(asset, {}).get("bonferroni_significant")
    )

    return {
        "requested_buckets": REQUESTED_BUCKETS,
        "canonical_tickers": sorted(tickers),
        "overlap_checks": overlap,
        "all_overlap_checks_pass": all(overlap.values()),
        "robust_assets_across_both_regime_defs": robust_assets,
    }


def build_result() -> dict:
    canonical = load_json(CANONICAL_RESULTS)
    coverage = canonical_coverage(canonical)
    period = canonical.get("period", {})
    tests_level = canonical.get("tests_level", {})
    hac_level = canonical.get("hac_level", {})

    return {
        "k_id": "K1330",
        "title": "USD regime cross-asset vol task dedup closure",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "task_resolution": "duplicate_of_existing_experiment",
        "verdict": "SUPERSEDED_BY_K1439",
        "canonical_experiment": {
            "k_id": canonical.get("k_id", "K1439"),
            "path": str(CANONICAL_DIR.relative_to(ROOT)),
            "results_path": str(CANONICAL_RESULTS.relative_to(ROOT)),
            "verdict": canonical.get("verdict"),
            "period": period,
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
            "most_sensitive_asset_by_abs_hac_t": canonical.get("most_sensitive_asset_by_abs_hac_t"),
            "verdict_reason": canonical.get("verdict_reason"),
        },
        "closure_reason": (
            "K1439 already tests strong-vs-weak USD regime effects on EM, gold, and commodities "
            "with the stricter HAC inference path; rerunning K1330 would duplicate evidence rather "
            "than add a new empirical result."
        ),
        "notes": [
            "This artifact is a governance / dedup closure, not a new empirical experiment.",
            "Direct vol prediction by DXY was already a NULL in adjacent K878.",
            "Canonical underlying experiment K1439 has explicit shift(1) lookahead protection.",
        ],
    }


def main() -> None:
    results = build_result()
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {OUT_PATH}")
    print(
        "[summary]",
        results["verdict"],
        "| overlap_pass=" + str(results["coverage_audit"]["all_overlap_checks_pass"]),
        "| robust_assets=" + ",".join(results["coverage_audit"]["robust_assets_across_both_regime_defs"]),
    )


if __name__ == "__main__":
    main()
