"""Duplicate-closure audit for the HARQ realized-quarticity backlog item.

The pending task asks for a realized-quarticity HARQ experiment:

    HARQ (RV x sqrt(RQ) measurement-error correction) vs standard HAR-RV,
    using local 5-minute realized quarticity, OOS QLIKE / DM.

That exact experiment already exists as K1582. This script is deliberately a
closure audit, not a second model run. Re-running the same model family under a
new slug would create duplicate conclusions and publication-candidate noise.

The audit verifies that K1582 has the required three-piece artifact, uses the
requested realized-quarticity construction, has explicit lagged features, and
reports the gateable TX_active OOS QLIKE/DM results.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CANON = ROOT / "experiments" / "k1582"
RESULTS_PATH = HERE / "research_harq_5_min_realized_quarticity_harq_rv_rq_vs_rv_results.json"
SUMMARY_CSV = HERE / "research_harq_5_min_realized_quarticity_harq_rv_rq_vs_rv_summary.csv"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def has_pattern(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.MULTILINE | re.DOTALL) is not None


def main() -> None:
    script = CANON / "K1582.py"
    results_file = CANON / "K1582_results.json"
    readme = CANON / "README.md"
    review = CANON / "CODEX_REVIEW.md"
    tx_forecasts = CANON / "data" / "TX_active_oos_forecasts.csv"
    tx_measures = CANON / "data" / "tx_active_daily_measures_2017_2026.parquet"

    required = {
        "script": require(script),
        "results": require(results_file),
        "readme": require(readme),
        "codex_review": require(review),
        "tx_forecasts": require(tx_forecasts),
        "tx_daily_measures": require(tx_measures),
    }

    missing = [name for name, meta in required.items() if not meta["exists"] or meta["size_bytes"] <= 0]
    if missing:
        raise RuntimeError(f"K1582 required artifact missing or empty: {missing}")

    src = read_text(script)
    res = json.loads(read_text(results_file))
    tx = next(m for m in res["markets"] if m["market"] == "TX_active")

    source_checks = {
        "realized_quarticity_formula_present": has_pattern(src, r"rq\s*=\s*float\(\(n\s*/\s*3\.0\).*rets\s*\*\*\s*4"),
        "measurement_error_proxy_present": has_pattern(src, r"np\.sqrt\(d\[\"rq\"\]\)\s*/\s*d\[\"rv\"\]"),
        "shift1_feature_lag_present": ".shift(1)" in src,
        "expanding_oos_train_before_forecast_present": "features.iloc[:pos]" in src and "features.iloc[[pos]]" in src,
        "qlike_pointwise_present": "qlike_pointwise" in src,
        "dm_test_present": "dm_test" in src,
        "mcs_present": "model_confidence_set" in src,
    }
    failed_checks = [k for k, ok in source_checks.items() if not ok]
    if failed_checks:
        raise RuntimeError(f"K1582 source check failed: {failed_checks}")

    summary_rows = []
    for model, metrics in tx["models"].items():
        row = {
            "market": "TX_active",
            "model": model,
            "qlike": metrics["qlike"],
            "mse_level": metrics["mse_level"],
            "r2_oos_level": metrics["r2_oos_level"],
            "n_oos": tx["n_oos"],
            "gateable": tx["gateable"],
        }
        if model in tx["pairwise_vs_har"]:
            row.update(tx["pairwise_vs_har"][model])
        summary_rows.append(row)
    pd.DataFrame(summary_rows).to_csv(SUMMARY_CSV, index=False)

    closure = {
        "experiment_id": "research_harq_5_min_realized_quarticity_harq_rv_rq_vs_rv",
        "generated_at": utc_now(),
        "verdict": "DUPLICATE_CLOSED_BY_K1582",
        "canonical_experiment": "K1582",
        "canonical_path": "experiments/k1582/",
        "reason": (
            "The pending backlog item is already fully covered by K1582: local 5-minute realized "
            "quarticity, HARQ/RQ measurement-error interaction, standard HAR baseline, OOS QLIKE/DM, "
            "MCS, Codex review, and knowledge entry."
        ),
        "task_match": {
            "requested_realized_quarticity": "RQ_t = n/3 * sum intraday_returns^4",
            "k1582_realized_quarticity_verified": True,
            "requested_harq_rv_rq_vs_har": True,
            "k1582_models": list(tx["models"].keys()),
            "requested_oos_qlike_dm": True,
            "k1582_statistics": res["statistics"],
            "requested_shift1": True,
            "source_checks": source_checks,
        },
        "canonical_artifacts": required,
        "canonical_key_result": {
            "market": "TX_active",
            "date_range_raw": tx["date_range_raw"],
            "n_daily_raw": tx["n_daily_raw"],
            "n_oos": tx["n_oos"],
            "gateable": tx["gateable"],
            "har_qlike": tx["models"]["HAR"]["qlike"],
            "harq_qlike": tx["models"]["HARQ"]["qlike"],
            "harq_improvement_pct": tx["pairwise_vs_har"]["HARQ"]["qlike_improvement_pct"],
            "harq_dm_t": tx["pairwise_vs_har"]["HARQ"]["dm_t_model_minus_har"],
            "shark_like_qlike": tx["models"]["SHARK_like"]["qlike"],
            "shark_like_improvement_pct": tx["pairwise_vs_har"]["SHARK_like"]["qlike_improvement_pct"],
            "shark_like_dm_t": tx["pairwise_vs_har"]["SHARK_like"]["dm_t_model_minus_har"],
            "mcs_members": tx["mcs"]["members"],
            "k1582_verdict": tx["verdict"],
        },
        "closure_interpretation": (
            "Do not rerun this as a fresh experiment without new data or a materially different estimator. "
            "K1582 found directional but non-Harvey-significant improvement: HARQ QLIKE +1.94% with "
            "DM t=-2.60 and SHARK_like QLIKE +2.05% with DM t=-1.77 on the only gateable TX_active panel."
        ),
        "outputs": {
            "summary_csv": str(SUMMARY_CSV),
            "results_json": str(RESULTS_PATH),
        },
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(closure, fh, ensure_ascii=False, indent=2)

    print(json.dumps({
        "verdict": closure["verdict"],
        "canonical": closure["canonical_experiment"],
        "n_oos": tx["n_oos"],
        "harq_improvement_pct": tx["pairwise_vs_har"]["HARQ"]["qlike_improvement_pct"],
        "harq_dm_t": tx["pairwise_vs_har"]["HARQ"]["dm_t_model_minus_har"],
        "shark_like_improvement_pct": tx["pairwise_vs_har"]["SHARK_like"]["qlike_improvement_pct"],
        "shark_like_dm_t": tx["pairwise_vs_har"]["SHARK_like"]["dm_t_model_minus_har"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
