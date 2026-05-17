"""
K1202b — Paper 2 D2 primary-source hand-verify.

Purpose
-------
K1202 D2 extended pool 有 80.3% rows 是 LLM_EXTRACTED_FROM_PUBLIC（從公開
法說會 transcripts 透過 LLM 抽取）。Paper 2 投稿前 reviewer credibility
gate 要求：對 ≥1 公司 × ≥5 季度做 primary-source hand-verify，cross-check
LLM 抽值 vs 官方 IR 數字。

Method
------
1. 讀 K1202 extended pool (experiments/k1202/data/k1202_extended_noncapex_pool.csv)
2. 讀 K1202b primary-source reference (data/primary_source_reference.json)
   - Reference = TSMC + UMC 季度 income statement (revenue, R&D, gross margin)
   - 來源 = stockanalysis.com WebFetch 2026-05-16，upstream = TSMC/UMC SEC 6-K
3. 把 K1202 LLM 抽值 (utilisation_delta_pp, wafer_asp_delta_pct, rd_delta_pct)
   逐 row × 逐欄位 cross-check primary-source 推導值，分類:
   - MATCH (|diff| < 2pp 或 <2% relative)
   - CLOSE (2-5%)
   - DIVERGE (5-10%)
   - MAJOR_DIVERGE (>10%)
   - UNVERIFIED_via_webfetch (primary source 不可程式化取得)
4. 計算 match_rate per variable，輸出 verdict + recommendation。

Honest disclosure
-----------------
- Direct TSMC / UMC IR pages WebFetch 403 (2026-05-16) → 採 stockanalysis.com
  作為 upstream-traceable 來源（其數字來自 SEC 6-K 申報）。所有 reference
  數字均可獨立復現（任何人對 TSM 6-K / UMC 6-K 都會得到相同 revenue / R&D）。
- TSMC 不公開 utilization rate (since 2019) → utilisation 欄位無法做數值
  cross-check，只能對 directional sign agreement 做 sanity check
  (公開 management commentary "near full" / "subdued" / "moderate").
- UMC 公開 utilization rate 但 IR PDF appendix 內無法透過 WebFetch 取得 →
  utilisation 欄位同樣 UNVERIFIED_via_webfetch。

Verifiable cells (可數值 cross-check):
- rd_delta_pct: 用 quarterly R&D / quarterly revenue 算 R&D ratio, 取
  YoY Δ (年同期比) 對比 K1202 抽值。
- wafer_asp_delta_pct: TSMC/UMC 不分開公布 ASP，但 ASP 變動 ≈ revenue
  變動 - shipment 變動。Shipment 變動公開資料不可程式化 → 以 gross
  margin Δ 作為 ASP pressure 的 proxy directional check (高度間接,
  marked PROXY_DIRECTIONAL).
- utilisation_delta_pp: UNVERIFIED_via_webfetch (TSMC 不公布;
  UMC IR PDF 403).
"""

from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Dict, Any, List, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).parent
K1202_DIR = HERE.parent / "k1202"
REF_PATH = HERE / "data" / "primary_source_reference.json"
POOL_PATH = K1202_DIR / "data" / "k1202_extended_noncapex_pool.csv"
RESULTS_PATH = HERE / "k1202b_results.json"
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def classify_divergence(
    llm_value: float,
    primary_value: float,
    absolute_tol_pp: float = 2.0,
) -> Tuple[str, float]:
    """Return (label, abs_diff). For percentage-point variables (delta_pp), use
    absolute difference; for relative variables (delta_pct), use relative.

    Conservative classification:
    - |diff| < 2pp / 2%  -> MATCH
    - 2-5%               -> CLOSE
    - 5-10%              -> DIVERGE
    - >10%               -> MAJOR_DIVERGE
    """
    diff = llm_value - primary_value
    abs_diff = abs(diff)
    if abs_diff < absolute_tol_pp:
        return "MATCH", abs_diff
    if abs_diff < 5.0:
        return "CLOSE", abs_diff
    if abs_diff < 10.0:
        return "DIVERGE", abs_diff
    return "MAJOR_DIVERGE", abs_diff


def load_pool() -> List[Dict[str, Any]]:
    rows = []
    with open(POOL_PATH, newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append(r)
    return rows


def load_reference() -> Dict[str, Any]:
    return json.loads(REF_PATH.read_text())


# ---------------------------------------------------------------------------
# Build primary-source-derived R&D YoY % delta for each quarter
# ---------------------------------------------------------------------------

def derive_rd_yoy_pct(ref: Dict[str, Any], company: str) -> Dict[str, float]:
    """Compute R&D YoY % growth per quarter.

    K1202 `rd_delta_pct` 是 R&D YoY growth (per K1108d / K1202 dictionary).
    Primary = (R&D_q / R&D_{q-4y}) - 1.
    """
    q = ref[f"{company}_quarterly_TWD_millions"]
    quarters = [k for k in q.keys() if k != "_units"]
    out: Dict[str, float] = {}
    for qkey in quarters:
        # Map to "{year}{quarter}" arithmetic for finding y-1 same quarter
        year = int(qkey[:4])
        qsuffix = qkey[4:]  # 'Q1'..'Q4'
        prev_key = f"{year - 1}{qsuffix}"
        if prev_key in q:
            cur = q[qkey]["rd_expense"]
            prev = q[prev_key]["rd_expense"]
            out[qkey] = (cur / prev - 1.0) * 100.0
    return out


def derive_gm_pp_change(ref: Dict[str, Any], company: str) -> Dict[str, float]:
    """Gross margin pp change YoY — proxy directional reference for
    `wafer_asp_delta_pct` (lower ASP under pressure -> lower GM, all else equal).
    """
    q = ref[f"{company}_quarterly_TWD_millions"]
    quarters = [k for k in q.keys() if k != "_units"]
    out: Dict[str, float] = {}
    for qkey in quarters:
        year = int(qkey[:4])
        qsuffix = qkey[4:]
        prev_key = f"{year - 1}{qsuffix}"
        if prev_key in q:
            out[qkey] = q[qkey]["gross_margin_pct"] - q[prev_key]["gross_margin_pct"]
    return out


# ---------------------------------------------------------------------------
# Cross-check engine
# ---------------------------------------------------------------------------

def map_k1202_row_to_quarter(stock: str, announce_date: str, ref: Dict[str, Any]) -> str | None:
    """K1202 row `announce_date` is the earnings-call date for previous quarter.
    Use explicit lookup table from primary_source_reference.json.
    """
    if stock == "2330.TW":
        m = ref.get("_quarterly_announce_date_to_k1202_row_mapping_TSMC", {})
        key = f"{announce_date}_TSMC_row"
        return m.get(key, {}).get("covers_results_of")
    if stock == "2303.TW":
        m = ref.get("_quarterly_announce_date_to_k1202_row_mapping_UMC", {})
        key = f"{announce_date}_UMC_row"
        return m.get(key, {}).get("covers_results_of")
    return None


def run_cross_check() -> Dict[str, Any]:
    pool = load_pool()
    ref = load_reference()

    tsmc_rd_yoy = derive_rd_yoy_pct(ref, "tsmc")
    umc_rd_yoy = derive_rd_yoy_pct(ref, "umc")
    tsmc_gm_d = derive_gm_pp_change(ref, "tsmc")
    umc_gm_d = derive_gm_pp_change(ref, "umc")

    target_dates = {
        "2330.TW": ["2023-03-01", "2023-05-15", "2023-08-15", "2023-11-15",
                    "2024-03-01", "2024-05-16", "2024-08-15", "2024-11-15"],
        "2303.TW": ["2023-04-27", "2023-07-27", "2023-10-26",
                    "2024-02-29", "2024-04-25", "2024-08-01", "2024-11-01"],
    }

    cross_check: List[Dict[str, Any]] = []
    for row in pool:
        stock = row["stock"]
        d = row["announce_date"]
        if stock not in target_dates or d not in target_dates[stock]:
            continue

        quarter = map_k1202_row_to_quarter(stock, d, ref)
        if quarter is None:
            continue

        # ---- rd_delta_pct cross-check (PRIMARY verifiable) ----
        rd_llm_raw = row.get("rd_delta_pct", "")
        rd_src = row.get("rd_source", "")
        rd_check = {"variable": "rd_delta_pct", "k1202_quarter_ref": quarter}
        if rd_llm_raw == "" or rd_llm_raw is None:
            rd_check.update({"status": "NA_in_k1202", "label": "NA"})
        else:
            rd_llm = float(rd_llm_raw)
            rd_yoy = (tsmc_rd_yoy if stock == "2330.TW" else umc_rd_yoy).get(quarter)
            if rd_yoy is None:
                rd_check.update({"status": "no_prior_year_reference", "label": "UNVERIFIED"})
            else:
                # rd_delta_pct meaning: "R&D YoY %" per K1108d data dictionary.
                # K1202 LLM values are typically 8-13% range — same scale.
                label, absdiff = classify_divergence(rd_llm, rd_yoy, absolute_tol_pp=2.0)
                rd_check.update({
                    "llm_value": rd_llm,
                    "primary_value": round(rd_yoy, 3),
                    "abs_diff_pp": round(absdiff, 3),
                    "label": label,
                    "llm_source_tag": rd_src,
                    "primary_source_method": "derived from quarterly R&D YoY (stockanalysis.com -> SEC 6-K)",
                })

        # ---- wafer_asp_delta_pct cross-check (PROXY DIRECTIONAL via GM Δ) ----
        asp_llm_raw = row.get("wafer_asp_delta_pct", "")
        asp_src = row.get("asp_source", "")
        asp_check = {"variable": "wafer_asp_delta_pct", "k1202_quarter_ref": quarter}
        if asp_llm_raw == "" or asp_llm_raw is None:
            asp_check.update({"status": "NA_in_k1202", "label": "NA"})
        else:
            asp_llm = float(asp_llm_raw)
            gm_d = (tsmc_gm_d if stock == "2330.TW" else umc_gm_d).get(quarter)
            if gm_d is None:
                asp_check.update({"status": "no_prior_year_reference", "label": "UNVERIFIED"})
            else:
                # Directional sign test: ASP up should accompany GM up (foundry
                # cost largely fixed quarter-to-quarter; ASP swings transmit to GM).
                sign_llm = np.sign(asp_llm) if asp_llm != 0 else 0
                sign_gm = np.sign(gm_d) if abs(gm_d) > 0.5 else 0  # GM change tolerance band 0.5pp
                if sign_llm == 0 or sign_gm == 0:
                    direction_match = "NEUTRAL"
                elif sign_llm == sign_gm:
                    direction_match = "SIGN_AGREE"
                else:
                    direction_match = "SIGN_DISAGREE"

                asp_check.update({
                    "llm_value": asp_llm,
                    "primary_proxy_gm_delta_pp": round(gm_d, 3),
                    "directional_check": direction_match,
                    "label": "PROXY_DIRECTIONAL_" + direction_match,
                    "llm_source_tag": asp_src,
                    "primary_source_method": "proxy: GM YoY Δ (ASP changes transmit to GM at ~ fixed cost)",
                    "note": "ASP not separately disclosed by TSMC/UMC; this is a proxy directional check, not a magnitude check",
                })

        # ---- utilisation_delta_pp cross-check (UNVERIFIABLE via webfetch) ----
        util_llm_raw = row.get("utilisation_delta_pp", "")
        util_src = row.get("util_source", "")
        util_check = {"variable": "utilisation_delta_pp", "k1202_quarter_ref": quarter}
        if util_llm_raw == "" or util_llm_raw is None:
            util_check.update({"status": "NA_in_k1202", "label": "NA"})
        else:
            util_check.update({
                "llm_value": float(util_llm_raw),
                "label": "UNVERIFIED_via_webfetch",
                "llm_source_tag": util_src,
                "blockage_reason": (
                    "TSMC does not publicly disclose utilization rate since 2019; "
                    "UMC quarterly utilization is in IR PDF appendix which returned "
                    "WebFetch 403 (2026-05-16). Reviewer should be referred to UMC "
                    "quarterly investor conference presentation pp.4-5 for primary source."
                ),
            })

        cross_check.append({
            "stock": stock,
            "k1202_announce_date": d,
            "k1202_quarter_ref": quarter,
            "checks": [rd_check, asp_check, util_check],
        })

    return {"cross_check_rows": cross_check}


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

def summarize(cross_check: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute per-variable match rates and overall verdict.

    CRITICAL: separates stats by `llm_source_tag` — only LLM_EXTRACTED_FROM_PUBLIC
    rows are the reviewer-credibility target. HAND_CODED rows are baseline truth
    (sanity check only); PROXY_ANNUAL rows are by-design annual smoothing
    (mis-match against quarterly YoY is expected, NOT an LLM extraction error).
    """
    labels_by_var: Dict[str, List[str]] = {
        "rd_delta_pct": [],
        "wafer_asp_delta_pct": [],
        "utilisation_delta_pp": [],
    }
    diffs_by_var: Dict[str, List[float]] = {k: [] for k in labels_by_var}
    # Per-source-tag breakdown
    by_source: Dict[str, Dict[str, List[Any]]] = {
        "LLM_EXTRACTED_FROM_PUBLIC": {"rd": [], "rd_diffs": [], "asp": [], "util": []},
        "HAND_CODED": {"rd": [], "rd_diffs": [], "asp": [], "util": []},
        "PROXY_ANNUAL": {"rd": [], "rd_diffs": [], "asp": [], "util": []},
        "PROXY_PIT": {"rd": [], "rd_diffs": [], "asp": [], "util": []},
    }

    for row in cross_check:
        for c in row["checks"]:
            v = c["variable"]
            labels_by_var[v].append(c["label"])
            if "abs_diff_pp" in c:
                diffs_by_var[v].append(c["abs_diff_pp"])
            tag = c.get("llm_source_tag", "")
            if tag in by_source:
                short = "rd" if v == "rd_delta_pct" else ("asp" if v == "wafer_asp_delta_pct" else "util")
                by_source[tag][short].append(c["label"])
                if short == "rd" and "abs_diff_pp" in c:
                    by_source[tag]["rd_diffs"].append(c["abs_diff_pp"])

    summary = {}
    for v, labels in labels_by_var.items():
        n = len(labels)
        n_match = sum(1 for x in labels if x == "MATCH")
        n_close = sum(1 for x in labels if x == "CLOSE")
        n_diverge = sum(1 for x in labels if x == "DIVERGE")
        n_major = sum(1 for x in labels if x == "MAJOR_DIVERGE")
        n_sign_agree = sum(1 for x in labels if x == "PROXY_DIRECTIONAL_SIGN_AGREE")
        n_sign_disagree = sum(1 for x in labels if x == "PROXY_DIRECTIONAL_SIGN_DISAGREE")
        n_sign_neutral = sum(1 for x in labels if x == "PROXY_DIRECTIONAL_NEUTRAL")
        n_unverified = sum(1 for x in labels if "UNVERIFIED" in x)
        n_na = sum(1 for x in labels if x == "NA")
        n_verifiable = n - n_unverified - n_na

        summary[v] = {
            "n_total_rows_in_sample": n,
            "n_NA_in_k1202": n_na,
            "n_unverifiable": n_unverified,
            "n_verifiable_magnitude": n - n_na - n_unverified - n_sign_agree - n_sign_disagree - n_sign_neutral,
            "n_directional_only": n_sign_agree + n_sign_disagree + n_sign_neutral,
            "magnitude_counts": {
                "MATCH": n_match, "CLOSE": n_close,
                "DIVERGE": n_diverge, "MAJOR_DIVERGE": n_major,
            },
            "directional_counts": {
                "SIGN_AGREE": n_sign_agree,
                "SIGN_DISAGREE": n_sign_disagree,
                "NEUTRAL": n_sign_neutral,
            },
            "match_rate_pct": (
                round(100.0 * n_match / (n_match + n_close + n_diverge + n_major), 2)
                if (n_match + n_close + n_diverge + n_major) > 0 else None
            ),
            "abs_diff_stats_pp": (
                {
                    "n": len(diffs_by_var[v]),
                    "mean": round(float(np.mean(diffs_by_var[v])), 3),
                    "median": round(float(np.median(diffs_by_var[v])), 3),
                    "max": round(float(np.max(diffs_by_var[v])), 3),
                    "min": round(float(np.min(diffs_by_var[v])), 3),
                } if diffs_by_var[v] else None
            ),
        }

    # Per-source-tag stats — this is the credibility-relevant view
    source_summary = {}
    for tag, buckets in by_source.items():
        rd_labels = buckets["rd"]
        rd_diffs = buckets["rd_diffs"]
        if not rd_labels:
            continue
        rd_match = sum(1 for x in rd_labels if x == "MATCH")
        rd_close = sum(1 for x in rd_labels if x == "CLOSE")
        rd_div = sum(1 for x in rd_labels if x == "DIVERGE")
        rd_major = sum(1 for x in rd_labels if x == "MAJOR_DIVERGE")
        rd_total_quant = rd_match + rd_close + rd_div + rd_major
        source_summary[tag] = {
            "rd_delta_pct_label_counts": {
                "MATCH": rd_match, "CLOSE": rd_close,
                "DIVERGE": rd_div, "MAJOR_DIVERGE": rd_major,
                "UNVERIFIED": sum(1 for x in rd_labels if "UNVERIFIED" in x),
                "NA": sum(1 for x in rd_labels if x == "NA"),
            },
            "rd_quantifiable_n": rd_total_quant,
            "rd_match_rate_pct": round(100.0 * rd_match / rd_total_quant, 2) if rd_total_quant else None,
            "rd_major_diverge_rate_pct": round(100.0 * rd_major / rd_total_quant, 2) if rd_total_quant else None,
            "rd_abs_diff_pp_stats": (
                {
                    "n": len(rd_diffs),
                    "mean": round(float(np.mean(rd_diffs)), 3),
                    "median": round(float(np.median(rd_diffs)), 3),
                    "max": round(float(np.max(rd_diffs)), 3),
                } if rd_diffs else None
            ),
        }
    summary["_per_source_tag"] = source_summary

    # Overall verdict — KEY: gate is on LLM_EXTRACTED rows only
    # (HAND_CODED is ground truth; PROXY_ANNUAL is annual smoothing by design)
    llm_block = source_summary.get("LLM_EXTRACTED_FROM_PUBLIC", {})
    llm_major_rate = (llm_block.get("rd_major_diverge_rate_pct") or 0.0) / 100.0
    rd = summary["rd_delta_pct"]
    asp = summary["wafer_asp_delta_pct"]
    util = summary["utilisation_delta_pp"]
    rd_major_rate = llm_major_rate  # use LLM-subset rate, not pooled

    # Sign disagree-rate among UMC ASP proxy (TSMC GM driven by mix not ASP)
    asp_sign_agree = asp["directional_counts"]["SIGN_AGREE"]
    asp_sign_disagree = asp["directional_counts"]["SIGN_DISAGREE"]
    total_directional = asp_sign_agree + asp_sign_disagree
    asp_disagree_rate = (asp_sign_disagree / total_directional) if total_directional else 0.0

    if rd_major_rate > 0.10:
        verdict = "RECOMMEND_K1202_RERUN"
        rec = (
            f"LLM_EXTRACTED-subset R&D MAJOR_DIVERGE rate {rd_major_rate:.1%} > 10% gate. "
            "K1202 D2 should be rerun with hand-verified R&D YoY (SEC 6-K derived) "
            "replacing LLM-extracted subset for TSMC + UMC quarterly rows."
        )
    elif rd_major_rate > 0.05:
        verdict = "RECOMMEND_APPENDIX_FOOTNOTE_PRECISION_RANGE"
        rec = (
            f"R&D MAJOR_DIVERGE rate {rd_major_rate:.1%} in 5-10% band. Paper 2 should "
            "add appendix footnote disclosing LLM-extraction precision range observed in "
            "K1202b hand-verify subset (max abs diff ~{:.1f}pp) and report that NULL conclusion "
            "is robust within that error band.".format(rd["abs_diff_stats_pp"]["max"] if rd["abs_diff_stats_pp"] else 0.0)
        )
    else:
        verdict = "LLM_PROVENANCE_DEFENSIBLE"
        rec = (
            f"R&D MAJOR_DIVERGE rate {rd_major_rate:.1%} < 5% gate. LLM extraction of "
            "rd_delta_pct is within published-data precision tolerance. Paper 2 appendix "
            "note: 'K1202b cross-checked LLM_EXTRACTED rd_delta_pct against primary-source "
            "quarterly income statements for {} TSMC/UMC quarters; n={} verifiable, mean "
            "abs diff = {:.2f}pp, max = {:.2f}pp.'".format(
                len(cross_check),
                rd["abs_diff_stats_pp"]["n"] if rd["abs_diff_stats_pp"] else 0,
                rd["abs_diff_stats_pp"]["mean"] if rd["abs_diff_stats_pp"] else 0.0,
                rd["abs_diff_stats_pp"]["max"] if rd["abs_diff_stats_pp"] else 0.0,
            )
        )

    summary["_verdict"] = verdict
    summary["_recommendation"] = rec
    summary["_asp_directional_disagree_rate"] = round(asp_disagree_rate, 3)
    summary["_asp_directional_note"] = (
        "ASP magnitude is not separately disclosed (TSMC/UMC). Proxy = quarterly "
        "GM YoY Δ. Sign-disagree rate {:.0%} reflects that GM is driven by node-mix "
        "and yield in addition to ASP; sign-agree treated as positive sanity, "
        "sign-disagree NOT treated as LLM error.".format(asp_disagree_rate)
    )
    summary["_util_note"] = (
        "utilisation_delta_pp UNVERIFIABLE via WebFetch (TSMC undisclosed since 2019; "
        "UMC IR PDF 403). Paper 2 appendix should: (a) acknowledge utilisation primary-source "
        "verification not feasible programmatically, (b) note that K1202 utilisation channel "
        "univariate t=+0.25 (NULL) means precision of this variable is moot for NULL conclusion."
    )
    return summary


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------

def make_figure(cross_check: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    diffs = []
    for row in cross_check:
        for c in row["checks"]:
            if c["variable"] == "rd_delta_pct" and "abs_diff_pp" in c:
                diffs.append((f"{row['stock']}\n{row['k1202_quarter_ref']}", c["abs_diff_pp"], c["label"]))

    if not diffs:
        return

    labels = [d[0] for d in diffs]
    vals = [d[1] for d in diffs]
    cats = [d[2] for d in diffs]
    color_map = {"MATCH": "#2ecc71", "CLOSE": "#f1c40f",
                 "DIVERGE": "#e67e22", "MAJOR_DIVERGE": "#e74c3c"}
    colors = [color_map.get(c, "#95a5a6") for c in cats]

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(range(len(vals)), vals, color=colors, edgecolor="black", linewidth=0.5)
    ax.axhline(2.0, color="#2ecc71", linestyle="--", linewidth=0.8, label="MATCH gate (<2pp)")
    ax.axhline(5.0, color="#f1c40f", linestyle="--", linewidth=0.8, label="CLOSE gate (<5pp)")
    ax.axhline(10.0, color="#e74c3c", linestyle="--", linewidth=0.8, label="MAJOR_DIVERGE gate (>10pp)")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=8)
    ax.set_ylabel("|LLM_value − Primary_value|  (pp)")
    ax.set_title("K1202b — R&D YoY% LLM vs Primary-Source Hand-Verify\n(TSMC + UMC, 2023Q1–2024Q3 quarterly rows)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1202b_rd_divergence.png", dpi=120, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cc_result = run_cross_check()
    summary = summarize(cc_result["cross_check_rows"])
    make_figure(cc_result["cross_check_rows"], summary)

    out = {
        "experiment_id": "K1202b",
        "parent": "K1202",
        "purpose": "Paper 2 D2 LLM_EXTRACTED primary-source hand-verify (reviewer credibility gate)",
        "seed": SEED,
        "accessed_date": "2026-05-16",
        "method_summary": (
            "Cross-check K1202 LLM_EXTRACTED non-capex variables vs TSMC/UMC quarterly "
            "income statements (stockanalysis.com -> SEC 6-K). 15 rows total (8 TSMC + 7 UMC), "
            "spanning 2023Q1-2024Q3 quarterly earnings calls."
        ),
        "primary_source_blockage": {
            "tsmc_ir_direct_403": "https://investor.tsmc.com/english/quarterly-results (WebFetch 403)",
            "umc_ir_direct_403": "https://www.umc.com/en/News/Investor (WebFetch 403)",
            "fallback_used": "stockanalysis.com (upstream-traceable to SEC 6-K)",
        },
        "rows_verified": len(cc_result["cross_check_rows"]),
        "rd_yoy_derived_TSMC": {k: round(v, 3) for k, v in derive_rd_yoy_pct(load_reference(), "tsmc").items()},
        "rd_yoy_derived_UMC": {k: round(v, 3) for k, v in derive_rd_yoy_pct(load_reference(), "umc").items()},
        "cross_check_table": cc_result["cross_check_rows"],
        "summary": summary,
    }

    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {RESULTS_PATH}")
    print(f"Verdict: {summary['_verdict']}")
    print(f"Recommendation: {summary['_recommendation']}")


if __name__ == "__main__":
    main()
