#!/usr/bin/env python3
"""Generate the machine-readable K1396 scope audit and corrected figures.

K1396's stored result is a historical artifact.  This script deliberately
never rewrites ``k1396_results.json``.  It verifies that byte-for-byte artifact,
records why its public interpretation was withdrawn, and renders replacement
figures from the frozen K1396 and certified K1379 result files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEGACY_RESULTS = HERE / "k1396_results.json"
CORRECTED_RESULTS = ROOT / "experiments" / "k1379" / "k1379_results.json"
DATA_FILE = ROOT / "paper" / "garch-x-vix" / "data" / "spy_vix_qqq_eem_fez_2000-2026.csv"
AUDIT_FILE = HERE / "k1396_scope_audit.json"
LEGACY_CHART = HERE / "k1396_general_article_chart.png"
CORRECTION_CHART = HERE / "k1396_scope_correction_chart.png"

EXPECTED_LEGACY_SHA256 = "c2816e6e0d2a2f7b18d3b78421e342ff9606c8c39fd5fab9064574042c7c1a10"
EXPECTED_CORRECTED_SHA256 = "bc430da7b03ba23a0090b246641a0a5899b712281c80dc8551befe1b844b8517"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def load_inputs() -> tuple[dict, dict]:
    actual_sha = sha256(LEGACY_RESULTS)
    if actual_sha != EXPECTED_LEGACY_SHA256:
        raise RuntimeError(
            "refusing to repair an altered K1396 historical artifact: "
            f"expected {EXPECTED_LEGACY_SHA256}, got {actual_sha}"
        )
    corrected_sha = sha256(CORRECTED_RESULTS)
    if corrected_sha != EXPECTED_CORRECTED_SHA256:
        raise RuntimeError(
            "refusing to use a drifted K1379 certified result: "
            f"expected {EXPECTED_CORRECTED_SHA256}, got {corrected_sha}"
        )
    legacy = json.loads(LEGACY_RESULTS.read_text(encoding="utf-8"))
    corrected = json.loads(CORRECTED_RESULTS.read_text(encoding="utf-8"))
    if legacy.get("experiment_id") != "K1396":
        raise ValueError("unexpected legacy experiment id")
    if corrected.get("experiment_id") != "k1379":
        raise ValueError("unexpected corrected experiment id")
    return legacy, corrected


def current_input_diagnostic() -> dict:
    """Describe today's file without pretending it is K1396's run vintage."""
    frame = pd.read_csv(DATA_FILE, index_col=0)
    index = pd.Index(frame.index.astype(str))
    oos = frame.loc[index >= "2019-01-01"]
    return {
        "path": str(DATA_FILE.relative_to(ROOT)),
        "sha256_at_scope_repair": sha256(DATA_FILE),
        "rows_at_scope_repair": int(len(frame)),
        "oos_rows_at_scope_repair_before_cleaning": int(len(oos)),
        "duplicate_index_rows": int(index.duplicated(keep=False).sum()),
        "duplicate_index_excess_rows": int(index.duplicated(keep="first").sum()),
        "interpretation": (
            "Repair-time diagnostic only. K1396 did not store its run-time input "
            "hash or endpoint, so this file cannot establish the original vintage."
        ),
    }


def build_audit(legacy: dict, corrected: dict) -> dict:
    corrected_dm = corrected["dm_tests"]["A4f vs HAR-RV"]
    return {
        "schema_version": 1,
        "experiment_id": "K1396",
        "audit_date": "2026-07-16",
        "status": "SUPERSEDED_HISTORICAL_DIAGNOSTIC_ONLY",
        "public_claim_verdict": "FAIL_PUBLIC_CLAIM",
        "historical_artifact": {
            "path": str(LEGACY_RESULTS.relative_to(ROOT)),
            "sha256": sha256(LEGACY_RESULTS),
            "preserved_byte_for_byte": True,
            "stored_n_oos": legacy["sample_sizes"]["n_oos"],
            "stored_values_are_fabricated": False,
            "independent_reproduction_status": "UNAVAILABLE_UNPINNED_INPUT_VINTAGE",
        },
        "model_label_corrections": {
            "HAR": "HAR-style daily-r-squared NNLS",
            "HAR_VIX": "HAR-style daily-r-squared-VIX NNLS",
            "A4f": "blockwise-fitted steady-state-g A4f approximation",
        },
        "protocol_scope": {
            "evaluation_target": "daily squared close-to-close log return (r_t^2)",
            "canonical_intraday_realized_variance": False,
            "a4f_forecast": (
                "tau_t multiplied by unconditional steady-state g at every OOS date; "
                "the short-run state is not recursively carried forward"
            ),
            "matches_k988_exactly": False,
            "legacy_dm": (
                "custom Bartlett/Newey-West-style raw-loss DM diagnostic with lag cap 12; "
                "not the canonical repository helper and not an HLN correction"
            ),
            "nested_comparison": (
                "HAR_VIX_vs_HAR is nested; its raw QLIKE DM value is diagnostic only"
            ),
        },
        "withdrawn_claims": [
            "canonical HAR-RV benchmark",
            "exact K988 protocol match",
            "A4f non-inferiority or equivalence",
            "three-model parity or statistically indistinguishable performance",
            "incremental VIX conclusion from HAR_VIX_vs_HAR raw QLIKE DM",
            "cross-proxy consistency",
        ],
        "historical_values": {
            "mean_qlike": legacy["mean_qlike"],
            "dm_tests": legacy["dm_tests"],
            "interpretation": "withdrawn 2026-05 approximation; audit trail only",
        },
        "superseded_by": {
            "experiment_id": "K1379",
            "results_path": str(CORRECTED_RESULTS.relative_to(ROOT)),
            "results_sha256": EXPECTED_CORRECTED_SHA256,
            "scope": (
                "corrected daily-r-squared protocol; still not canonical intraday HAR-RV"
            ),
            "a4f_vs_daily_r2_har": {
                "dm_t": corrected_dm["dm_t"],
                "dm_p": corrected_dm["dm_p"],
                "qlike_advantage_pct": corrected_dm["model1_qlike_advantage_pct"],
                "harvey_screen_pass": corrected_dm["harvey_pass"],
                "winner": corrected_dm["harvey_winner"],
            },
        },
        "current_input_file_diagnostic": current_input_diagnostic(),
        "references": [
            {
                "citation": "Corsi (2009)",
                "doi": "10.1093/jjfinec/nbp001",
                "relevance": "HAR-RV is defined on realized-volatility measures",
            },
            {
                "citation": "Patton (2011)",
                "doi": "10.1016/j.jeconom.2010.03.034",
                "relevance": "QLIKE robustness does not relabel daily r-squared as intraday RV",
            },
            {
                "citation": "Diebold and Mariano (1995)",
                "doi": "10.1080/07350015.1995.10524599",
                "relevance": "tests equal predictive accuracy, not equivalence",
            },
            {
                "citation": "Schuirmann (1987)",
                "doi": "10.1007/BF01068419",
                "relevance": "non-inferiority/equivalence needs an explicit margin and reversed null",
            },
        ],
    }


def render_legacy_chart(legacy: dict) -> None:
    means = legacy["mean_qlike"]
    tests = legacy["dm_tests"]
    labels = [
        "HAR-style\ndaily-r2",
        "A4f steady-state-g\napproximation",
        "HAR-style daily-r2\n+ VIX",
    ]
    values = [means["HAR"], means["A4f"], means["HAR_VIX"]]
    dm_labels = [
        "daily-r2 HAR vs\nA4f approximation",
        "daily-r2-VIX HAR vs\nA4f approximation",
        "daily-r2-VIX HAR vs\ndaily-r2 HAR (nested)",
    ]
    dm_values = [
        tests["HAR_vs_A4f"]["t_stat"],
        tests["HAR_VIX_vs_A4f"]["t_stat"],
        tests["HAR_VIX_vs_HAR"]["t_stat"],
    ]

    fig, axes = plt.subplots(1, 2, figsize=(20, 10))
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.20, top=0.82, wspace=0.28)
    colors = ["#607D8B", "#2F80ED", "#5B9F68"]
    bars = axes[0].bar(labels, values, color=colors, width=0.66)
    axes[0].set_title("Withdrawn K1396 point estimates", fontsize=20, pad=18)
    axes[0].set_ylabel("Historical mean QLIKE (lower is better)", fontsize=14)
    axes[0].set_ylim(0, max(values) * 1.20)
    axes[0].grid(axis="y", alpha=0.22)
    axes[0].tick_params(axis="x", labelsize=11)
    for bar, value in zip(bars, values, strict=True):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.015,
            f"{value:.3f}",
            ha="center",
            fontsize=14,
        )

    y = np.arange(len(dm_values))
    axes[1].barh(y, dm_values, color="#9AA5B1", height=0.62)
    axes[1].set_yticks(y, dm_labels)
    axes[1].axvline(0, color="#263238", linewidth=1.2)
    axes[1].axvline(-3, color="#B0BEC5", linestyle="--")
    axes[1].axvline(3, color="#B0BEC5", linestyle="--")
    axes[1].set_xlim(-3.4, 3.4)
    axes[1].set_title("Legacy custom raw-loss DM diagnostics", fontsize=20, pad=18)
    axes[1].set_xlabel("Historical t statistic; diagnostic only", fontsize=14)
    axes[1].grid(axis="x", alpha=0.22)
    axes[1].invert_yaxis()
    for row, value in enumerate(dm_values):
        offset = 0.10 if value >= 0 else -0.10
        axes[1].text(
            value + offset,
            row,
            f"{value:+.2f}",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=14,
        )

    fig.suptitle(
        "K1396 historical approximation — not canonical HAR-RV or non-inferiority evidence",
        fontsize=23,
        fontweight="bold",
        y=0.96,
    )
    fig.text(
        0.50,
        0.50,
        "SUPERSEDED",
        ha="center",
        va="center",
        fontsize=72,
        color="#B71C1C",
        alpha=0.08,
        rotation=-12,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.035,
        "Daily r2 proxy; steady-state-g A4f approximation; unpinned run-time input. "
        "The nested comparison is not a valid incremental-content test.",
        ha="center",
        fontsize=12,
        color="#455A64",
    )
    fig.savefig(LEGACY_CHART, dpi=160, bbox_inches="tight")
    plt.close(fig)


def render_correction_chart(legacy: dict, corrected: dict) -> None:
    old_dm = legacy["dm_tests"]["HAR_vs_A4f"]["t_stat"]
    old_adv = (
        (legacy["mean_qlike"]["HAR"] - legacy["mean_qlike"]["A4f"])
        / legacy["mean_qlike"]["HAR"]
        * 100.0
    )
    new_dm = corrected["dm_tests"]["A4f vs HAR-RV"]
    new_adv = new_dm["model1_qlike_advantage_pct"]
    # Orient both bars so positive values favor A4f. K1379's canonical sign is
    # model1-model2, hence its reported negative t is negated for this display.
    evidence_scores = [old_dm, -new_dm["dm_t"]]

    fig, axes = plt.subplots(1, 2, figsize=(18, 9))
    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.21, top=0.82, wspace=0.24)
    xlabels = ["K1396\nwithdrawn\napproximation", "K1379\ncorrected daily-r2\nprotocol"]
    bars = axes[0].bar(xlabels, [old_adv, new_adv], color=["#B0BEC5", "#2F80ED"], width=0.6)
    axes[0].set_title("A4f QLIKE advantage over daily-r2 HAR-style model", fontsize=18)
    axes[0].set_ylabel("Lower QLIKE (%)", fontsize=14)
    axes[0].set_ylim(0, max(new_adv, old_adv) * 1.28)
    axes[0].grid(axis="y", alpha=0.22)
    for bar, value in zip(bars, [old_adv, new_adv], strict=True):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.28,
            f"{value:.2f}%",
            ha="center",
            fontsize=16,
            fontweight="bold",
        )

    bars = axes[1].bar(xlabels, evidence_scores, color=["#B0BEC5", "#2F80ED"], width=0.6)
    axes[1].axhline(3, color="#78909C", linestyle="--", label="|t| > 3 reporting screen")
    axes[1].set_title("Evidence score oriented to favor A4f", fontsize=18)
    axes[1].set_ylabel("Oriented |DM t|", fontsize=14)
    axes[1].set_ylim(0, max(evidence_scores) * 1.25)
    axes[1].grid(axis="y", alpha=0.22)
    axes[1].legend(loc="upper left")
    for bar, value in zip(bars, evidence_scores, strict=True):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.24,
            f"{value:.2f}",
            ha="center",
            fontsize=16,
            fontweight="bold",
        )

    fig.suptitle(
        "Why the original 'only a 1% gap' story was withdrawn",
        fontsize=23,
        fontweight="bold",
        y=0.96,
    )
    fig.text(
        0.5,
        0.035,
        "The protocols differ jointly; this figure documents supersession, not the causal effect of one fix. "
        "Neither experiment is a canonical intraday HAR-RV benchmark.",
        ha="center",
        fontsize=12,
        color="#455A64",
    )
    fig.savefig(CORRECTION_CHART, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    legacy, corrected = load_inputs()
    atomic_write_json(AUDIT_FILE, build_audit(legacy, corrected))
    render_legacy_chart(legacy)
    render_correction_chart(legacy, corrected)
    print(f"wrote {AUDIT_FILE.relative_to(ROOT)}")
    print(f"wrote {LEGACY_CHART.relative_to(ROOT)}")
    print(f"wrote {CORRECTION_CHART.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
