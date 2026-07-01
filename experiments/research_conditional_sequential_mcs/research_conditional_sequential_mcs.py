#!/usr/bin/env python3
"""Conditional / sequential MCS pilot on the K1259 DM ledger.

This is a deliberately limited, evidence-bound experiment:
- input is the K1259 pairwise DM ledger, not reconstructed per-day losses;
- "conditional" means source-label conditioning from existing regime/crisis
  fields, not a full Conditional Method Confidence Set implementation;
- "sequential" means K-number prefix monitoring, not time-uniform e-process
  inference.

The goal is to test whether the existing VolPred ledger is rich enough to
support conditional/sequential MCS research, and to quantify the first-pass
signals without fabricating missing loss series or regime labels.
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ID = "research_conditional_sequential_mcs"
LEDGER_PATH = ROOT / "experiments" / "k1259" / "dm_ledger.json"
K1259_MCS_PATH = ROOT / "experiments" / "k1259" / "k1259_mcs.py"
OUT_DIR = ROOT / "experiments" / EXPERIMENT_ID
OUT_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = OUT_DIR / f"{EXPERIMENT_ID}_sequential_jaccard.png"

SEED = 42
BOOTSTRAP_B = 1000
ALPHA = 0.10
MIN_PAIRS_PER_MODEL = 2
LOSS_FN = "QLIKE"


def load_k1259_module() -> Any:
    spec = importlib.util.spec_from_file_location("k1259_mcs", K1259_MCS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {K1259_MCS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


K1259 = load_k1259_module()


def load_raw_ledger() -> list[dict[str, Any]]:
    with LEDGER_PATH.open("r", encoding="utf-8") as fh:
        obj = json.load(fh)
    rows = obj.get("rows", [])
    if not isinstance(rows, list):
        raise TypeError("K1259 ledger schema changed: expected object with rows[]")
    return rows


def k_num(k_id: Any) -> int | None:
    match = re.search(r"K(\d+)", str(k_id or ""))
    return int(match.group(1)) if match else None


def classify_condition(row: dict[str, Any]) -> str | None:
    """Map existing ledger labels into stress/normal proxies.

    The classifier intentionally uses only explicit regime/crisis source labels.
    It does not infer regimes from dates or model names.
    """
    period = str(row.get("period") or "").lower()
    source = str(row.get("source_field_path") or "").lower()
    combined = f"{period} {source}"

    stress_token = re.compile(
        r"(^|[:._\-/ ])(covid|bear|gfc|ukraine|negoil|oilcrash|goldcrash|luna|stress)($|[:._\-/ ])"
    )
    if (
        "crisis_subperiods" in source
        or stress_token.search(combined)
        or "by_regime:high" in period
        or "by_regime.high" in source
    ):
        return "stress_proxy"

    if (
        "dm_tests_by_regime.calm" in source
        or "dm_tests_by_regime.normal" in source
        or "by_regime:low" in period
        or "by_regime.low" in source
    ):
        return "normal_proxy"

    return None


def clean_regime_rows(raw_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    drops: Counter[str] = Counter()

    for row in raw_rows:
        condition = classify_condition(row)
        if condition is None:
            continue
        if (row.get("loss_fn") or LOSS_FN) != LOSS_FN:
            drops["non_qlike"] += 1
            continue
        asset = row.get("asset") or ""
        if not asset:
            drops["missing_asset"] += 1
            continue
        model_a = K1259.normalize_model_name(row.get("model_a") or "")
        model_b = K1259.normalize_model_name(row.get("model_b") or "")
        if model_a is None or model_b is None or model_a == model_b:
            drops["bad_model_name"] += 1
            continue
        dm_stat = row.get("dm_stat")
        if not isinstance(dm_stat, (int, float)) or not math.isfinite(float(dm_stat)):
            drops["invalid_dm"] += 1
            continue
        cleaned.append(
            {
                "condition": condition,
                "k_id": row.get("k_id"),
                "model_a": model_a,
                "model_b": model_b,
                "loss_fn": row.get("loss_fn") or LOSS_FN,
                "asset": asset,
                "asset_scope": "multi_asset" if "|" in asset else "single_asset",
                "period": row.get("period") or "",
                "dm_stat": float(dm_stat),
                "p_value": row.get("p_value"),
                "source_file": row.get("source_file") or "",
                "source_field_path": row.get("source_field_path") or "",
            }
        )

    coverage = {
        "rows_cleaned": len(cleaned),
        "drops": dict(drops),
        "condition_counts": dict(Counter(r["condition"] for r in cleaned)),
        "asset_scope_counts": dict(Counter(r["asset_scope"] for r in cleaned)),
        "asset_top": {
            condition: Counter(r["asset"] for r in cleaned if r["condition"] == condition).most_common(8)
            for condition in sorted({r["condition"] for r in cleaned})
        },
        "k_id_top": {
            condition: Counter(r["k_id"] for r in cleaned if r["condition"] == condition).most_common(8)
            for condition in sorted({r["condition"] for r in cleaned})
        },
    }
    return cleaned, coverage


def build_matrix_from_rows(rows: list[dict[str, Any]]) -> tuple[list[str], np.ndarray, np.ndarray, dict[str, Any]]:
    pair_t: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        a, b = row["model_a"], row["model_b"]
        t_stat = row["dm_stat"]
        if (a, b) in pair_t or (b, a) not in pair_t:
            pair_t[(a, b)].append(t_stat)
        else:
            pair_t[(b, a)].append(-t_stat)

    model_count: Counter[str] = Counter()
    for (a, b), stats in pair_t.items():
        model_count[a] += len(stats)
        model_count[b] += len(stats)

    models = sorted([m for m, count in model_count.items() if count >= MIN_PAIRS_PER_MODEL])
    idx = {model: i for i, model in enumerate(models)}
    t_matrix = np.zeros((len(models), len(models)), dtype=float)
    w_matrix = np.zeros((len(models), len(models)), dtype=float)

    for (a, b), stats in pair_t.items():
        if a not in idx or b not in idx:
            continue
        i, j = idx[a], idx[b]
        value = float(np.mean(stats))
        t_matrix[i, j] = value
        t_matrix[j, i] = -value
        w_matrix[i, j] = len(stats)
        w_matrix[j, i] = len(stats)

    matrix_summary = {
        "n_rows": len(rows),
        "n_unique_pairs_raw": len(pair_t),
        "n_models_after_min_pair_filter": len(models),
        "models_after_min_pair_filter": models,
        "n_pairs_after_filter": int((w_matrix > 0).sum() // 2),
        "model_observation_counts": dict(model_count.most_common()),
    }
    return models, t_matrix, w_matrix, matrix_summary


def run_condition_mcs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for condition in ["stress_proxy", "normal_proxy"]:
        subset = [row for row in rows if row["condition"] == condition]
        models, t_matrix, _w_matrix, matrix_summary = build_matrix_from_rows(subset)
        block: dict[str, Any] = {
            "description": (
                "Rows are selected from explicit existing regime/crisis labels in K1259 ledger; "
                "multi-asset rows are kept as multi_asset evidence, not reassigned to a single ticker."
            ),
            "matrix_summary": matrix_summary,
            "source_examples": [
                {
                    "k_id": row["k_id"],
                    "asset": row["asset"],
                    "period": row["period"],
                    "model_a": row["model_a"],
                    "model_b": row["model_b"],
                    "dm_stat": row["dm_stat"],
                    "source_field_path": row["source_field_path"],
                }
                for row in subset[:10]
            ],
        }
        if len(models) < 3:
            block["status"] = "insufficient_models"
            block["message"] = f"only {len(models)} models after filter; need >=3"
        else:
            block["status"] = "ok"
            block["mcs_alpha_0.10"] = K1259.mcs_test(
                models,
                t_matrix,
                alpha=ALPHA,
                B=BOOTSTRAP_B,
                seed=SEED,
            )
        output[condition] = block
    return output


def run_sequential_prefix_monitor() -> dict[str, Any]:
    rows, drop_stats = K1259.load_ledger(LEDGER_PATH)
    target_rows = [row for row in rows if row["asset"] == "SPY" and row["loss_fn"] == LOSS_FN]
    unique_k = sorted({k for row in target_rows if (k := k_num(row.get("k_id"))) is not None})
    if not unique_k:
        return {"status": "insufficient_data", "message": "No SPY/QLIKE K rows found"}

    cut_indices = [max(0, int(len(unique_k) * q) - 1) for q in (0.25, 0.50, 0.75, 1.00)]
    cutoffs = [unique_k[i] for i in cut_indices]
    runs: list[dict[str, Any]] = []

    for cutoff in cutoffs:
        subset = [row for row in target_rows if (k_num(row.get("k_id")) or 10**9) <= cutoff]
        models, t_matrix, w_matrix = K1259.build_t_matrix(subset, "SPY", LOSS_FN)
        if len(models) < 3:
            runs.append(
                {
                    "cutoff_k": f"K{cutoff}",
                    "n_rows": len(subset),
                    "n_models": len(models),
                    "status": "insufficient_models",
                }
            )
            continue
        result = K1259.mcs_test(models, t_matrix, alpha=ALPHA, B=BOOTSTRAP_B, seed=SEED)
        runs.append(
            {
                "cutoff_k": f"K{cutoff}",
                "unique_k_count": sum(1 for k in unique_k if k <= cutoff),
                "n_rows": len(subset),
                "n_models": len(models),
                "n_pairs_total": int((w_matrix > 0).sum() // 2),
                "status": "ok",
                "n_survived": result["n_models_survived"],
                "final_stopping_p": result["final_stopping_p"],
                "first_five_eliminated": [item["model"] for item in result["eliminated_ordered"][:5]],
                "superior_set": result["superior_set"],
            }
        )

    final_set = set(runs[-1].get("superior_set", [])) if runs else set()
    previous_set: set[str] | None = None
    for run in runs:
        current = set(run.get("superior_set", []))
        if current and final_set:
            run["jaccard_vs_final"] = round(len(current & final_set) / len(current | final_set), 6)
        else:
            run["jaccard_vs_final"] = None
        if previous_set is not None and current:
            run["jaccard_vs_previous"] = round(len(current & previous_set) / len(current | previous_set), 6)
        else:
            run["jaccard_vs_previous"] = None
        if current:
            previous_set = current

    return {
        "status": "ok",
        "asset": "SPY",
        "loss_fn": LOSS_FN,
        "monitor_axis": "K-number prefix, used as an evidence-arrival proxy",
        "drop_stats_from_k1259_loader": drop_stats,
        "total_target_rows": len(target_rows),
        "unique_k_total": len(unique_k),
        "cutoffs": [f"K{k}" for k in cutoffs],
        "runs": runs,
    }


def maybe_plot_sequential(results: dict[str, Any]) -> str | None:
    seq = results.get("sequential_prefix_monitor", {})
    runs = [run for run in seq.get("runs", []) if run.get("status") == "ok"]
    if not runs:
        return None
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    x = [run["cutoff_k"] for run in runs]
    y = [run["jaccard_vs_final"] for run in runs]
    survived = [run["n_survived"] for run in runs]

    fig, ax1 = plt.subplots(figsize=(9, 5), dpi=150)
    ax1.plot(x, y, marker="o", color="#235A97", linewidth=2.5, label="Jaccard vs final MCS")
    ax1.set_ylim(0, 1.05)
    ax1.set_ylabel("Jaccard vs final")
    ax1.set_xlabel("SPY / QLIKE evidence prefix")
    ax1.grid(axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.bar(x, survived, alpha=0.25, color="#1F7A4D", label="Surviving models")
    ax2.set_ylabel("MCS surviving models")
    ax1.set_title("Sequential prefix monitor on K1259 SPY/QLIKE ledger")
    fig.tight_layout()
    fig.savefig(FIG_PATH)
    plt.close(fig)
    return str(FIG_PATH.relative_to(ROOT))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_rows = load_raw_ledger()
    regime_rows, regime_coverage = clean_regime_rows(raw_rows)
    conditional_mcs = run_condition_mcs(regime_rows)
    sequential_prefix_monitor = run_sequential_prefix_monitor()

    out: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": "research_conditional_sequential_mcs_jrss_b_2025_qkag066_a",
        "date": "2026-07-01",
        "random_seed": SEED,
        "input_data": {
            "ledger": str(LEDGER_PATH.relative_to(ROOT)),
            "ledger_source_experiment": "K1259",
            "raw_rows": len(raw_rows),
            "loss_fn": LOSS_FN,
        },
        "method_scope": {
            "what_this_is": (
                "A K1259-ledger pilot for regime-labeled MCS and K-prefix sequential monitoring."
            ),
            "what_this_is_not": (
                "Not a full CMCS/CSPA implementation and not a time-uniform sequential MCS, because "
                "K1259 stores pairwise DM statistics rather than per-day loss differentials."
            ),
            "bootstrap_B": BOOTSTRAP_B,
            "alpha": ALPHA,
            "min_pairs_per_model": MIN_PAIRS_PER_MODEL,
        },
        "literature_checked": [
            {
                "citation": "Hansen, Lunde & Nason (2011), The Model Confidence Set, Econometrica.",
                "url": "https://onlinelibrary.wiley.com/doi/abs/10.3982/ECTA5771",
                "used_for": "Baseline MCS framing and iterative elimination concept.",
            },
            {
                "citation": "Arnold, Gavrilopoulos, Schulz & Ziegel (2026), Sequential model confidence sets, JRSS-B qkag066.",
                "url": "https://academic.oup.com/jrsssb/advance-article/doi/10.1093/jrsssb/qkag066/8676743",
                "used_for": "Sequential monitoring motivation; this experiment only approximates evidence-arrival monitoring.",
            },
            {
                "citation": "Bauer & Kazak (2025), Conditional Method Confidence Set, arXiv:2505.21278.",
                "url": "https://arxiv.org/abs/2505.21278",
                "used_for": "Regime-conditional MCS motivation; this experiment only uses existing source-label regime proxies.",
            },
            {
                "citation": "Li, Liao & Quaedvlieg (2020), Conditional Superior Predictive Ability.",
                "url": "https://sites.duke.edu/jiali/files/2020/02/cspa-combined.pdf",
                "used_for": "Conditional forecast-evaluation caution: true conditioning requires loss series by state.",
            },
        ],
        "regime_coverage": regime_coverage,
        "conditional_mcs": conditional_mcs,
        "sequential_prefix_monitor": sequential_prefix_monitor,
        "main_findings": [],
        "limitations": [
            "Conditional rows are sparse and mostly multi-asset; they are not reassigned to individual tickers.",
            "Normal/calm proxy has only 6 QLIKE rows after cleaning; any conclusion is weak.",
            "Sequential monitor uses K-number prefix as evidence-arrival proxy, not calendar time.",
            "K1259 ledger-only DM statistics do not permit true stationary-block bootstrap on per-day losses.",
            "FRED recession conditioning cannot be implemented honestly from this ledger without dated loss series.",
        ],
    }

    stress = conditional_mcs.get("stress_proxy", {}).get("mcs_alpha_0.10", {})
    normal = conditional_mcs.get("normal_proxy", {}).get("mcs_alpha_0.10", {})
    seq_runs = sequential_prefix_monitor.get("runs", [])
    if stress:
        out["main_findings"].append(
            {
                "finding": "stress_proxy_mcs_no_elimination",
                "evidence": (
                    f"{regime_coverage['condition_counts'].get('stress_proxy', 0)} stress rows; "
                    f"{stress.get('n_models_survived')}/{stress.get('n_models_input')} models survived; "
                    f"stopping p={stress.get('final_stopping_p')}."
                ),
                "interpretation": "Stress-labeled evidence is too thin/heterogeneous to select a unique superior set.",
            }
        )
    if normal:
        out["main_findings"].append(
            {
                "finding": "normal_proxy_mcs_no_elimination",
                "evidence": (
                    f"{regime_coverage['condition_counts'].get('normal_proxy', 0)} normal/calm rows; "
                    f"{normal.get('n_models_survived')}/{normal.get('n_models_input')} models survived; "
                    f"stopping p={normal.get('final_stopping_p')}."
                ),
                "interpretation": "Normal-regime evidence coverage is currently insufficient for a strong CMCS claim.",
            }
        )
    if seq_runs:
        ok_runs = [run for run in seq_runs if run.get("status") == "ok"]
        if ok_runs:
            out["main_findings"].append(
                {
                    "finding": "spy_qlike_superior_set_drifts_as_evidence_accumulates",
                    "evidence": [
                        {
                            "cutoff_k": run["cutoff_k"],
                            "n_rows": run["n_rows"],
                            "n_models": run["n_models"],
                            "n_survived": run["n_survived"],
                            "jaccard_vs_final": run["jaccard_vs_final"],
                        }
                        for run in ok_runs
                    ],
                    "interpretation": (
                        "SPY/QLIKE MCS set is not stable in early ledger prefixes; "
                        "Jaccard rises as more K evidence enters, supporting sequential monitoring as useful diagnostics."
                    ),
                }
            )

    figure_rel = maybe_plot_sequential(out)
    if figure_rel:
        out["figure"] = figure_rel

    with OUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT_PATH}")
    if figure_rel:
        print(f"Wrote {ROOT / figure_rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
