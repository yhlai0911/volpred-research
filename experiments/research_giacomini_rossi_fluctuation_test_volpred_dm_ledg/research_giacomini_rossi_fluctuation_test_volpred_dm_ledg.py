#!/usr/bin/env python3
"""Giacomini-Rossi fluctuation-test feasibility audit for the K1259 DM ledger.

The strict Giacomini-Rossi fluctuation test requires a chronological
out-of-sample loss-differential series d_t.  K1259 stores pairwise DM summary
statistics, so this script first checks whether the requested A4f/HAR or
CF/HAR rows expose any date-indexed loss series through their source files.
If not, it records a method-diagnosis null instead of forcing an invalid test.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ID = "research_giacomini_rossi_fluctuation_test_volpred_dm_ledg"
EXP_DIR = ROOT / "experiments" / EXPERIMENT_ID
LEDGER_PATH = ROOT / "experiments" / "k1259" / "dm_ledger.json"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"
FIGURE_PATH = EXP_DIR / "ledger_fluctuation_precondition_audit.png"
SEED = 42
MIN_GR_OBSERVATIONS = 252


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with tmp.open("r", encoding="utf-8") as f:
        json.load(f)
    os.replace(tmp, path)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _k_number(k_id: str) -> int:
    m = re.search(r"(\d+)", str(k_id))
    return int(m.group(1)) if m else -1


def _pair_model_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(k, ""))
        for k in ("model_a", "model_b")
    ).lower()


def _has_a4f(row: dict[str, Any]) -> bool:
    return "a4f" in _pair_model_text(row)


def _has_har(row: dict[str, Any]) -> bool:
    return re.search(r"\bhar\b|har-|har_", _pair_model_text(row)) is not None


def _has_cf(row: dict[str, Any]) -> bool:
    text = _pair_model_text(row)
    return (
        "cf-rolling" in text
        or "cf_rolling" in text
        or "cfrolling" in text
        or "cornish" in text
        or "cornish-fisher" in text
    )


def _classify_candidate(row: dict[str, Any]) -> str:
    if _has_a4f(row) and _has_har(row):
        return "a4f_har"
    if _has_cf(row) and _has_har(row):
        return "cf_har"
    if _has_a4f(row) and _has_cf(row):
        return "a4f_cf"
    return "other"


def _iter_path_parts(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for segment in str(path).split("."):
        if not segment:
            continue
        pos = 0
        prefix = re.match(r"^[^\[]+", segment)
        if prefix:
            parts.append(prefix.group(0))
            pos = len(prefix.group(0))
        while pos < len(segment):
            m = re.match(r"\[(\d+)\]", segment[pos:])
            if not m:
                break
            parts.append(int(m.group(1)))
            pos += len(m.group(0))
    return parts


def _get_by_source_path(data: Any, source_field_path: str) -> Any | None:
    cur = data
    for part in _iter_path_parts(source_field_path):
        try:
            if isinstance(part, int):
                cur = cur[part]
            else:
                cur = cur[part]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


DATE_KEYS = {"date", "datetime", "timestamp", "time", "forecast_date", "target_date"}
LOSS_KEYS = {"loss", "loss_a", "loss_b", "qlike", "mse", "error", "squared_error"}
FORECAST_KEYS = {"forecast", "prediction", "variance_forecast", "model", "model_name"}


def _looks_like_temporal_loss_series(seq: Any) -> bool:
    if not isinstance(seq, list) or len(seq) < MIN_GR_OBSERVATIONS:
        return False
    probe = [x for x in seq[: min(len(seq), 20)] if isinstance(x, dict)]
    if len(probe) < max(3, min(10, len(seq) // 20)):
        return False
    keys = {str(k).lower() for item in probe for k in item.keys()}
    has_date = bool(keys & DATE_KEYS)
    has_loss_or_forecast = bool(keys & LOSS_KEYS) or bool(keys & FORECAST_KEYS)
    return has_date and has_loss_or_forecast


def _scan_temporal_series(node: Any, path: str = "$") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if _looks_like_temporal_loss_series(node):
        sample_keys: list[str] = []
        for item in node[:5]:
            if isinstance(item, dict):
                sample_keys = sorted(str(k) for k in item.keys())
                break
        found.append({"path": path, "n": len(node), "sample_keys": sample_keys})
        return found
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(_scan_temporal_series(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node[:20]):
            found.extend(_scan_temporal_series(value, f"{path}[{i}]"))
    return found


def _source_metadata(row: dict[str, Any]) -> dict[str, Any]:
    source_file = ROOT / str(row.get("source_file", ""))
    source_path = str(row.get("source_field_path", ""))
    metadata: dict[str, Any] = {
        "source_file": str(row.get("source_file", "")),
        "source_field_path": source_path,
        "source_exists": source_file.exists(),
        "pair_node_found": False,
        "pair_temporal_series": [],
        "source_temporal_series": [],
        "sidecar_files": [],
        "direction_label": "unknown",
        "winner_raw": None,
        "direction_raw": None,
    }
    if not source_file.exists():
        return metadata

    try:
        source_json = _load_json(source_file)
    except Exception as exc:  # pragma: no cover - recorded for audit only
        metadata["source_read_error"] = f"{type(exc).__name__}: {exc}"
        return metadata

    pair_node = _get_by_source_path(source_json, source_path)
    metadata["pair_node_found"] = pair_node is not None
    if isinstance(pair_node, dict):
        winner = pair_node.get("winner") or pair_node.get("best_model")
        direction = pair_node.get("direction") or pair_node.get("interpretation")
        metadata["winner_raw"] = winner
        metadata["direction_raw"] = direction
        text = f"{winner or ''} {direction or ''}".lower()
        if "a4f" in text and ("better" in text or "winner" in text or winner):
            metadata["direction_label"] = "a4f_better"
        elif "har" in text and ("better" in text or "winner" in text or winner):
            metadata["direction_label"] = "har_better"
        metadata["pair_temporal_series"] = _scan_temporal_series(pair_node)

    # Scan the full source JSON, but only use this as a feasibility hint.
    metadata["source_temporal_series"] = _scan_temporal_series(source_json)

    source_dir = source_file.parent
    sidecars: list[dict[str, Any]] = []
    for pattern in ("*loss*.csv", "*loss*.parquet", "*forecast*.csv", "*forecast*.parquet"):
        for candidate in sorted(source_dir.glob(pattern)):
            sidecars.append({"path": str(candidate.relative_to(ROOT)), "bytes": candidate.stat().st_size})
    metadata["sidecar_files"] = sidecars
    return metadata


def _period_is_calendar_like(period: str) -> bool:
    return bool(re.search(r"\d{4}-\d{2}-\d{2}", str(period or "")))


def _make_figure(results: dict[str, Any]) -> None:
    candidate_rows = results["coverage"]["candidate_rows"]
    k_counts = Counter(r["k_id"] for r in candidate_rows)
    abs_by_k: dict[str, list[float]] = defaultdict(list)
    for row in candidate_rows:
        abs_by_k[row["k_id"]].append(abs(float(row["dm_stat"])))

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))

    pre = results["formal_gr_precondition_audit"]
    labels = [
        "A4f/HAR rows",
        "unique K",
        "CF rows",
        "raw d_t series",
        "calendar periods",
    ]
    values = [
        results["coverage"]["n_a4f_har_rows"],
        len(results["coverage"]["candidate_k_ids"]),
        results["coverage"]["n_cf_related_rows"],
        pre["raw_loss_series_found"],
        results["coverage"]["rows_with_calendar_period"],
    ]
    colors = ["#2f6f9f", "#6a9f58", "#b85c38", "#b85c38", "#8d7a35"]
    axes[0].bar(labels, values, color=colors)
    axes[0].set_title("Strict GR input audit")
    axes[0].set_ylabel("count")
    axes[0].tick_params(axis="x", rotation=30)
    for i, v in enumerate(values):
        axes[0].text(i, v + 0.2, str(v), ha="center", fontsize=9)

    ks = sorted(abs_by_k, key=_k_number)
    y = [float(np.mean(abs_by_k[k])) for k in ks]
    n = [k_counts[k] for k in ks]
    axes[1].bar(ks, y, color="#4f6d7a")
    axes[1].axhline(3.0, color="#9b3d3d", linestyle="--", linewidth=1, label="|DM| = 3")
    axes[1].set_title("Descriptive only: abs(DM stat) by source K")
    axes[1].set_ylabel("mean abs(DM stat)")
    axes[1].tick_params(axis="x", rotation=30)
    for i, (v, nn) in enumerate(zip(y, n, strict=True)):
        axes[1].text(i, v + 0.15, f"n={nn}", ha="center", fontsize=9)
    axes[1].legend(frameon=False, fontsize=9)

    fig.tight_layout()
    fig.savefig(FIGURE_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    rng = np.random.default_rng(SEED)
    del rng  # seed recorded; no stochastic inference is used in the audit.

    ledger = _load_json(LEDGER_PATH)
    rows = ledger["rows"]
    classified = [(row, _classify_candidate(row)) for row in rows]
    a4f_har_rows = [row for row, label in classified if label == "a4f_har"]
    cf_related_rows = [row for row in rows if _has_cf(row)]
    candidates = sorted(
        a4f_har_rows + [row for row, label in classified if label in {"cf_har", "a4f_cf"}],
        key=lambda r: (_k_number(r.get("k_id", "")), str(r.get("source_file", "")), str(r.get("source_field_path", ""))),
    )

    source_audits = [_source_metadata(row) for row in candidates]
    raw_loss_series_found = sum(
        1
        for audit in source_audits
        if audit["pair_temporal_series"] or audit["sidecar_files"]
    )

    dm_values = [float(row["dm_stat"]) for row in candidates if row.get("dm_stat") is not None]
    abs_dm_values = [abs(x) for x in dm_values]
    direction_counts = Counter(audit["direction_label"] for audit in source_audits)
    loss_counts = Counter(str(row.get("loss_fn", "")) for row in candidates)
    k_counts = Counter(str(row.get("k_id", "")) for row in candidates)
    period_counts = Counter(str(row.get("period", "")) or "(blank)" for row in candidates)

    candidate_rows_compact = [
        {
            "k_id": row.get("k_id"),
            "asset": row.get("asset"),
            "loss_fn": row.get("loss_fn"),
            "model_a": row.get("model_a"),
            "model_b": row.get("model_b"),
            "dm_stat": row.get("dm_stat"),
            "p_value": row.get("p_value"),
            "sample_n": row.get("sample_n"),
            "period": row.get("period"),
            "source_file": row.get("source_file"),
            "source_field_path": row.get("source_field_path"),
        }
        for row in candidates
    ]

    rows_with_calendar_period = sum(
        1 for row in candidates if _period_is_calendar_like(str(row.get("period", "")))
    )

    if candidates:
        high_abs_count = sum(1 for x in abs_dm_values if x > 3.0)
        descriptive = {
            "status": "descriptive_only_not_formal_gr",
            "n_rows": len(candidates),
            "abs_dm_mean": float(np.mean(abs_dm_values)),
            "abs_dm_median": float(np.median(abs_dm_values)),
            "abs_dm_max": float(np.max(abs_dm_values)),
            "share_abs_dm_gt_3": high_abs_count / len(candidates),
            "dm_stat_sign_counts_unstandardized": dict(Counter("positive" if x > 0 else "negative" if x < 0 else "zero" for x in dm_values)),
            "direction_metadata_counts": dict(direction_counts),
            "loss_fn_counts": dict(loss_counts),
            "rows_by_k_id": dict(k_counts),
            "period_counts": dict(period_counts),
            "warning": (
                "DM-stat signs are not normalized across source experiments; "
                "this block is a coverage/instability diagnostic, not a "
                "Giacomini-Rossi fluctuation test."
            ),
        }
    else:
        descriptive = {"status": "no_candidate_rows"}

    strict_gr_ok = raw_loss_series_found > 0 and rows_with_calendar_period > 0
    formal_status = "not_run_preconditions_failed"
    if strict_gr_ok:
        formal_status = "not_run_requires_pair_specific_series_extraction"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": "research_giacomini_rossi_fluctuation_test_volpred_dm_ledg",
        "title": "Giacomini-Rossi fluctuation-test feasibility audit for VolPred's K1259 DM ledger",
        "seed": SEED,
        "generated_at": "2026-07-08",
        "data": {
            "ledger_path": str(LEDGER_PATH.relative_to(ROOT)),
            "ledger_n_rows": int(ledger["n_rows"]),
            "ledger_phase": ledger.get("phase"),
            "source_scope": "K1259 Phase 1.5 DM summary ledger; no historical JSON edited.",
        },
        "literature": [
            {
                "reference": "Giacomini and Rossi (2010), Forecast comparisons in unstable environments, Journal of Applied Econometrics.",
                "role": "Defines fluctuation tests for local out-of-sample relative forecast performance.",
            },
            {
                "reference": "Diebold and Mariano (1995), Comparing predictive accuracy, Journal of Business & Economic Statistics.",
                "role": "Base equal-predictive-accuracy test on loss differentials.",
            },
            {
                "reference": "Harvey, Leybourne, and Newbold (1997), Testing the equality of prediction mean squared errors, International Journal of Forecasting.",
                "role": "Small-sample modification used by many project DM-HLN tests.",
            },
            {
                "reference": "Hansen, Lunde, and Nason (2011), Model Confidence Set, Econometrica.",
                "role": "Context for K1259's MCS extension and why raw loss vectors matter.",
            },
        ],
        "formal_gr_precondition_audit": {
            "strict_gr_status": formal_status,
            "required_inputs": [
                "date-indexed out-of-sample loss differential d_t for a fixed model pair",
                f"at least {MIN_GR_OBSERVATIONS} chronological observations",
                "consistent loss function and forecast target across the whole path",
            ],
            "raw_loss_series_found": raw_loss_series_found,
            "candidate_rows_with_pair_node_found": sum(1 for audit in source_audits if audit["pair_node_found"]),
            "reason": (
                "K1259 stores pairwise DM summary statistics. The requested "
                "A4f/HAR rows do not expose pair-level date-indexed loss "
                "differentials or sidecar forecast/loss files, and the ledger "
                "contains zero CF-Rolling rows."
            ),
        },
        "coverage": {
            "n_total_ledger_rows": len(rows),
            "n_a4f_rows_any_pair": sum(1 for row in rows if _has_a4f(row)),
            "n_har_rows_any_pair": sum(1 for row in rows if _has_har(row)),
            "n_a4f_har_rows": len(a4f_har_rows),
            "n_cf_related_rows": len(cf_related_rows),
            "candidate_k_ids": sorted(k_counts, key=_k_number),
            "candidate_source_files": sorted({str(row.get("source_file", "")) for row in candidates}),
            "rows_with_calendar_period": rows_with_calendar_period,
            "candidate_rows": candidate_rows_compact,
        },
        "source_audit": source_audits,
        "ledger_proxy_diagnostic": descriptive,
        "conclusion": {
            "verdict": "METHOD_DIAGNOSIS_NULL",
            "claim": (
                "The current VolPred DM ledger cannot support a formal "
                "Giacomini-Rossi fluctuation test for A4f/CF-Rolling vs HAR. "
                "It supports only a summary-stat coverage audit."
            ),
            "not_supported": [
                "No claim about regime concentration of A4f or CF-Rolling superiority.",
                "No claim that the observed DM-stat clustering is a formal instability rejection.",
                "No publication claim beyond a data-infrastructure diagnosis.",
            ],
        },
        "next_steps": [
            "Extend future DM-producing experiments to save date, model_a_loss, model_b_loss, and loss_diff sidecars.",
            "Add an optional loss_series_uri field to a future K1259-style ledger schema.",
            "Re-run the strict Giacomini-Rossi fluctuation test only after raw d_t coverage exists for the target model pair.",
        ],
        "figure": str(FIGURE_PATH.relative_to(ROOT)),
    }

    _make_figure(results)
    _atomic_write_json(RESULTS_PATH, results)
    print(json.dumps({
        "experiment_id": EXPERIMENT_ID,
        "verdict": results["conclusion"]["verdict"],
        "formal_gr_status": formal_status,
        "candidate_rows": len(candidates),
        "raw_loss_series_found": raw_loss_series_found,
        "figure": str(FIGURE_PATH.relative_to(ROOT)),
        "results": str(RESULTS_PATH.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
