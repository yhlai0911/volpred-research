#!/usr/bin/env python3
"""Render the K1683 VolPred lazypack as three JSON-bound PNG panels.

Every displayed research number is read from ``k1683_results.json`` at
runtime.  The README and article are also loaded as evidence-package integrity
checks.  Missing fields or inconsistent evidence raise immediately.
"""

from __future__ import annotations

import json
import math
import os
import re
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1683/k1683_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1683/README.md"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_531e4c87/panels/mile_531e4c87_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_531e4c87/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY = "#102A43"
INK = "#172B3A"
MUTED = "#556575"
PALE = "#F3F6F8"
WHITE = "#FFFFFF"
BLUE = "#1769AA"
BLUE_SOFT = "#E8F1F8"
TEAL = "#167C80"
TEAL_SOFT = "#E5F3F2"
RED = "#B83A3A"
RED_SOFT = "#F9E9E7"
AMBER = "#A66A16"
AMBER_SOFT = "#F8F0DF"
GREEN = "#2D7754"
GREEN_SOFT = "#E7F2EB"
LINE = "#D4DEE6"

ZH_DIGITS = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def load_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        value = handle.read()
    if not value.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return value


def require(data: Any, *parts: str) -> Any:
    current = data
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            raise KeyError(".".join(walked))
        current = current[part]
    return current


def require_number(data: Any, *parts: str) -> float:
    value = require(data, *parts)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {'.'.join(parts)}")
    if not math.isfinite(float(value)):
        raise ValueError(f"Non-finite number at {'.'.join(parts)}")
    return float(value)


def require_string(data: Any, *parts: str) -> str:
    value = require(data, *parts)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {'.'.join(parts)}")
    return value


def require_date(data: Any, *parts: str) -> str:
    value = require_string(data, *parts)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"Expected ISO date at {'.'.join(parts)}: {value!r}")
    return value


def require_contains(text: str, needle: str, path: Path) -> None:
    if needle not in text:
        raise ValueError(f"Required evidence text {needle!r} missing from {path}")


def zh_integer(value: int) -> str:
    if value not in ZH_DIGITS:
        raise ValueError(f"No Traditional-Chinese counter rendering for {value}")
    return ZH_DIGITS[value]


def zh_tenths_from_percent(value: float) -> str:
    tenths = value / 10.0
    rounded = int(round(tenths))
    if not math.isclose(tenths, rounded, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"Expected an exact multiple of ten percent, got {value}")
    return f"{zh_integer(rounded)}成"


def signed_percent(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}%"


def wrap_zh(text: str, width: int) -> str:
    wrapped: list[str] = []
    for paragraph in text.splitlines() or [text]:
        if not paragraph:
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                paragraph,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
        )
    return "\n".join(wrapped)


def find_subperiod(result: dict[str, Any], name: str) -> dict[str, Any]:
    subperiods = require(result, "subperiods")
    if not isinstance(subperiods, list):
        raise TypeError("results.<cell>.subperiods must be a list")
    matches = [row for row in subperiods if isinstance(row, dict) and row.get("name") == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one subperiod named {name!r}")
    return matches[0]


def number_from_row(row: dict[str, Any], field: str, label: str) -> float:
    if field not in row:
        raise KeyError(f"{label}.{field}")
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {label}.{field}")
    return float(value)


def parse_contract_labels(results: dict[str, Any]) -> tuple[list[str], int]:
    contracts = require(results, "data_provenance", "cftc", "contracts")
    if not isinstance(contracts, dict):
        raise TypeError("data_provenance.cftc.contracts must be an object")

    parsed: list[tuple[int, str]] = []
    for contract_name in contracts.values():
        if not isinstance(contract_name, str):
            raise TypeError("Every CFTC contract label must be a string")
        maturity = re.fullmatch(r"UST_(\d+)Y", contract_name)
        if maturity:
            years = int(maturity.group(1))
            parsed.append((years, f"{years} 年"))
        elif contract_name == "UST_BOND":
            parsed.append((10_000, "長債"))
        else:
            raise ValueError(f"Unsupported Treasury contract label: {contract_name}")

    parsed.sort(key=lambda item: item[0])
    labels = [label for _, label in parsed]
    if len(labels) != 4:
        raise ValueError(f"Panel plan requires four Treasury contracts; got {len(labels)}")
    return labels, len(labels)


def parse_formula(results: dict[str, Any]) -> tuple[int, int]:
    formula = require_string(results, "signal", "formula")
    match = re.search(
        r"\(long\+short\+(\d+)\*spread\)/\((\d+)\*open_interest\)",
        formula,
    )
    if not match:
        raise ValueError("signal.formula does not contain the expected participation ratio")
    return int(match.group(1)), int(match.group(2))


def parse_target_labels(primary_results: dict[str, Any]) -> list[str]:
    required_cells = ["TLT_RV5", "IEF_RV5", "DGS10_JUMP5", "SPY_TLT_CORR20"]
    for cell in required_cells:
        if cell not in primary_results:
            raise KeyError(f"results.{cell}")

    tlt_horizon = int(re.fullmatch(r"TLT_RV(\d+)", required_cells[0]).group(1))
    ief_horizon = int(re.fullmatch(r"IEF_RV(\d+)", required_cells[1]).group(1))
    dgs_match = re.fullmatch(r"DGS(\d+)_JUMP(\d+)", required_cells[2])
    corr_match = re.fullmatch(r"SPY_TLT_CORR(\d+)", required_cells[3])
    if dgs_match is None or corr_match is None:
        raise ValueError("Unexpected primary result cell naming")
    dgs_maturity = int(dgs_match.group(1))
    corr_horizon = int(corr_match.group(1))
    return [
        f"TLT {tlt_horizon} 日波動",
        f"IEF {ief_horizon} 日波動",
        f"{dgs_maturity} 年殖利率跳動",
        f"股債 {corr_horizon} 日相關",
    ]


def parse_gate(results: dict[str, Any]) -> tuple[int, str, str]:
    gate = require_string(results, "primary_family", "gate")
    normalized = gate.replace(", and ", ", ")
    conditions = [part.strip() for part in normalized.split(",") if part.strip()]
    if len(conditions) != 5:
        raise ValueError(f"Expected five primary gates, got {len(conditions)}")
    dm_match = re.search(r"HLN-DM t<(-?\d+(?:\.\d+)?)", gate)
    q_match = re.search(r"BH q<(-?\d+(?:\.\d+)?)", gate)
    if dm_match is None or q_match is None:
        raise ValueError("Primary gate thresholds are missing")
    if "positive association coefficient" not in gate:
        raise ValueError("Positive-association gate is missing")
    if "early/late improvements both positive" not in gate:
        raise ValueError("Early/late stability gate is missing")
    return len(conditions), dm_match.group(1), q_match.group(1)


def extract_panel_data(results: dict[str, Any]) -> dict[str, Any]:
    experiment_id = require_string(results, "experiment_id")
    if experiment_id.upper() != "K1683":
        raise ValueError(f"Unexpected experiment_id: {experiment_id}")

    context = require(results, "external_context_not_model_input")
    if not isinstance(context, dict):
        raise TypeError("external_context_not_model_input must be an object")
    top_keys = [
        key
        for key in context
        if re.fullmatch(r"top_(\d+)_share_percent_\d{4}_\w+", key)
    ]
    if len(top_keys) != 1:
        raise KeyError("Expected one top-N share field in external_context_not_model_input")
    top_key = top_keys[0]
    top_match = re.fullmatch(r"top_(\d+)_share_percent_\d{4}_\w+", top_key)
    if top_match is None:
        raise ValueError(f"Unexpected top-N field: {top_key}")
    top_n = int(top_match.group(1))
    top_share = number_from_row(context, top_key, "external_context_not_model_input")

    contracts, contract_count = parse_contract_labels(results)
    spread_multiplier, oi_multiplier = parse_formula(results)

    timing = require_string(results, "signal", "timing")
    lag_match = re.search(r"shift\((\d+)\)", timing)
    if lag_match is None or "targets start strictly after origin" not in timing:
        raise ValueError("signal.timing is missing the lag or strict target ordering")
    lag_weeks = int(lag_match.group(1))

    primary_results = require(results, "results")
    if not isinstance(primary_results, dict):
        raise TypeError("results must be an object")
    target_labels = parse_target_labels(primary_results)
    target_cells = ["TLT_RV5", "IEF_RV5", "DGS10_JUMP5", "SPY_TLT_CORR20"]
    n_values = [
        int(require_number(primary_results, cell, "n_oos")) for cell in target_cells
    ]
    oos_starts = [require_date(primary_results, cell, "oos_start") for cell in target_cells]

    gate_count, dm_threshold, q_threshold = parse_gate(results)
    proxy = require(results, "signal", "descriptive_proxy_change")
    if not isinstance(proxy, dict):
        raise TypeError("signal.descriptive_proxy_change must be an object")
    proxy_start_date = require_date(proxy, "start_report")
    proxy_end_date = require_date(proxy, "end_report")
    proxy_start = require_number(proxy, "gross_participation_start")
    proxy_end = require_number(proxy, "gross_participation_end")
    proxy_change = require_number(proxy, "change_pct")

    audit = require(results, "primary_family", "audit")
    if not isinstance(audit, list):
        raise TypeError("primary_family.audit must be a list")
    n_total = len(audit)
    if n_total != len(target_cells):
        raise ValueError("Primary audit count does not match the four planned targets")
    for index, row in enumerate(audit):
        if not isinstance(row, dict) or "pass" not in row:
            raise KeyError(f"primary_family.audit.{index}.pass")
    computed_pass = sum(bool(row["pass"]) for row in audit)
    n_pass = int(require_number(results, "verdict", "n_primary_pass"))
    if n_pass != computed_pass:
        raise ValueError("verdict.n_primary_pass disagrees with primary_family.audit")
    verdict_status = require_string(results, "verdict", "status")
    if verdict_status != "NULL_NO_ROBUST_INCREMENT":
        raise ValueError(f"Unexpected verdict status: {verdict_status}")

    tlt = require(primary_results, "TLT_RV5")
    ief = require(primary_results, "IEF_RV5")
    corr = require(primary_results, "SPY_TLT_CORR20")
    if not all(isinstance(item, dict) for item in (tlt, ief, corr)):
        raise TypeError("Primary result cells must be objects")
    tlt_early = find_subperiod(tlt, "early")
    tlt_late = find_subperiod(tlt, "late")
    corr_late = find_subperiod(corr, "late")

    corr_improvement = require_number(corr, "loss_improvement_pct")
    all_improvements = [
        require_number(primary_results, cell, "loss_improvement_pct")
        for cell in target_cells
    ]
    if not math.isclose(corr_improvement, min(all_improvements), abs_tol=1e-12):
        raise ValueError("SPY_TLT_CORR20 is no longer the worst primary cell")

    proxy_limits = require(results, "proxy_limits")
    if not isinstance(proxy_limits, list) or not any(
        isinstance(item, str) and "predictive null cannot reject" in item
        for item in proxy_limits
    ):
        raise ValueError("proxy_limits lacks the forced-deleveraging caveat")
    claim_scope = require_string(results, "verdict", "claim_scope")
    if "not forced-deleveraging causality" not in claim_scope:
        raise ValueError("verdict.claim_scope lacks the causal limitation")

    return {
        "experiment_id": experiment_id,
        "gross_exposure": require_number(
            context, "gross_treasury_exposure_2025_sep_trillion_usd"
        ),
        "long_exposure": require_number(
            context, "long_exposure_2025_sep_trillion_usd"
        ),
        "short_exposure": require_number(
            context, "short_exposure_2025_sep_trillion_usd"
        ),
        "top_n": top_n,
        "top_share_tenths": zh_tenths_from_percent(top_share),
        "contracts": contracts,
        "contract_count": contract_count,
        "spread_multiplier": spread_multiplier,
        "oi_multiplier": oi_multiplier,
        "lag_weeks": lag_weeks,
        "target_labels": target_labels,
        "n_oos_min": min(n_values),
        "n_oos_max": max(n_values),
        "oos_start": min(oos_starts),
        "gate_count": gate_count,
        "dm_threshold": dm_threshold,
        "q_threshold": q_threshold,
        "proxy_start_date": proxy_start_date,
        "proxy_end_date": proxy_end_date,
        "proxy_start": proxy_start,
        "proxy_end": proxy_end,
        "proxy_change": proxy_change,
        "n_pass": n_pass,
        "n_total": n_total,
        "tlt_improvement": require_number(tlt, "loss_improvement_pct"),
        "tlt_t": require_number(tlt, "dm_hln", "t_hln"),
        "tlt_q": require_number(tlt, "dm_hln", "bh_fdr_q_primary_family_4"),
        "ief_t": require_number(ief, "dm_hln", "t_hln"),
        "tlt_early": number_from_row(
            tlt_early, "loss_improvement_pct", "results.TLT_RV5.subperiods.early"
        ),
        "tlt_late": number_from_row(
            tlt_late, "loss_improvement_pct", "results.TLT_RV5.subperiods.late"
        ),
        "corr_improvement": corr_improvement,
        "corr_late": number_from_row(
            corr_late,
            "loss_improvement_pct",
            "results.SPY_TLT_CORR20.subperiods.late",
        ),
    }


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def add_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    linewidth: float = 1.2,
    radius: float = 0.016,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.006,rounding_size={radius}",
            transform=ax.transAxes,
            linewidth=linewidth,
            edgecolor=edgecolor,
            facecolor=facecolor,
        )
    )


def add_header(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.add_patch(Rectangle((0, 0.865), 1, 0.135, color=NAVY, transform=ax.transAxes))
    ax.text(
        0.055,
        0.967,
        "VOLPRED｜國債期貨擁擠度",
        color="#9FC4DC",
        fontsize=13,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.055,
        0.925,
        title,
        color=WHITE,
        fontsize=28,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.945,
        0.908,
        subtitle,
        color="#D5E4EE",
        fontsize=15,
        ha="right",
        va="top",
        transform=ax.transAxes,
    )


def add_footer(ax: plt.Axes, experiment_id: str) -> None:
    ax.plot([0.055, 0.945], [0.048, 0.048], color=LINE, lw=1, transform=ax.transAxes)
    ax.text(
        0.055,
        0.029,
        f"資料來源：experiment {experiment_id}",
        color=MUTED,
        fontsize=12,
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.945,
        0.029,
        "公開代理變數｜非因果識別",
        color=MUTED,
        fontsize=12,
        ha="right",
        va="center",
        transform=ax.transAxes,
    )


def save_panel(fig: plt.Figure, filename: str) -> None:
    output_path = os.path.join(out_dir, filename)
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        transparent=False,
    )
    plt.close(fig)


def render_panel_1(data: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    add_header(
        ax,
        "拿不到機密曝險，只能用公開期貨部位做代理",
        "同方向，不等於同一把尺",
    )

    context_line = (
        "機密資料：Form PF 顯示對沖基金美國國債曝險約 "
        f"{data['gross_exposure']:.1f} 兆美元"
        f"（多 {data['long_exposure']:.1f} 兆 / 空 {data['short_exposure']:.1f} 兆，"
        f"前 {data['top_n']} 大佔{data['top_share_tenths']}）"
    )
    add_card(ax, 0.055, 0.675, 0.89, 0.14, facecolor=BLUE_SOFT, edgecolor="#B8D1E4")
    ax.text(
        0.078,
        0.787,
        "監管機關看得到的全貌",
        color=BLUE,
        fontsize=14,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.748,
        wrap_zh(context_line, 56),
        color=INK,
        fontsize=22,
        fontweight="bold",
        va="top",
        linespacing=1.35,
        transform=ax.transAxes,
    )
    ax.text(
        0.922,
        0.697,
        "這是外部脈絡，不是模型輸入",
        color=BLUE,
        fontsize=13,
        ha="right",
        va="bottom",
        transform=ax.transAxes,
    )

    ax.add_patch(
        FancyArrowPatch(
            (0.5, 0.665),
            (0.5, 0.625),
            arrowstyle="-|>",
            mutation_scale=16,
            color=MUTED,
            linewidth=1.8,
            transform=ax.transAxes,
        )
    )
    ax.text(
        0.515,
        0.645,
        "資料落差",
        color=MUTED,
        fontsize=12,
        va="center",
        transform=ax.transAxes,
    )

    add_card(ax, 0.055, 0.452, 0.89, 0.16, facecolor=TEAL_SOFT, edgecolor="#B9DCD9")
    ax.text(
        0.078,
        0.582,
        "一般人拿得到的免費替代品",
        color=TEAL,
        fontsize=14,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.535,
        "免費替代品：CFTC 每週公佈的 Leveraged Funds 期貨持倉",
        color=INK,
        fontsize=24,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.485,
        "它量到的是合約參與度，不是基金層級的現貨、融資、保證金或槓桿。",
        color=MUTED,
        fontsize=15,
        va="top",
        transform=ax.transAxes,
    )

    formula_line = (
        "代理指標 = (多單 + 空單 + "
        f"{data['spread_multiplier']}×價差單) ÷ "
        f"({data['oi_multiplier']}×未平倉量)"
    )
    add_card(ax, 0.055, 0.258, 0.56, 0.14, facecolor=WHITE)
    ax.text(
        0.078,
        0.367,
        "公開代理怎麼算",
        color=MUTED,
        fontsize=14,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.319,
        wrap_zh(formula_line, 37),
        color=NAVY,
        fontsize=22,
        fontweight="bold",
        va="top",
        linespacing=1.35,
        transform=ax.transAxes,
    )

    contracts_line = (
        f"涵蓋 {' / '.join(data['contracts'])}"
        f"{zh_integer(data['contract_count'])}個國債期貨合約"
    )
    add_card(ax, 0.64, 0.258, 0.305, 0.14, facecolor=WHITE)
    ax.text(
        0.663,
        0.367,
        "四個核心期限",
        color=MUTED,
        fontsize=14,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.663,
        0.324,
        wrap_zh(contracts_line, 22),
        color=INK,
        fontsize=19,
        fontweight="bold",
        va="top",
        linespacing=1.35,
        transform=ax.transAxes,
    )

    add_card(ax, 0.055, 0.096, 0.89, 0.11, facecolor=PALE, edgecolor=PALE)
    ax.text(
        0.078,
        0.17,
        "讀法",
        color=AMBER,
        fontsize=14,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.16,
        0.166,
        "公開指標適合描述『現在站得多擠』，但它不是機密曝險資料的平替。",
        color=INK,
        fontsize=20,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )

    add_footer(ax, data["experiment_id"])
    save_panel(fig, "01_free_proxy_concept.png")


def render_panel_2(data: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    add_header(
        ax,
        "怎麼測：先鎖死時間順序，再過五道關卡",
        "逐週擴張式樣本外檢驗",
    )

    add_card(ax, 0.055, 0.657, 0.42, 0.155, facecolor=BLUE_SOFT, edgecolor="#B8D1E4")
    ax.text(
        0.078,
        0.784,
        f"訊號先落後 {data['lag_weeks']} 週",
        color=BLUE,
        fontsize=15,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.737,
        wrap_zh("指標一律落後使用，避免看到未來資料", 27),
        color=INK,
        fontsize=23,
        fontweight="bold",
        va="top",
        linespacing=1.35,
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.683,
        "預測目標只從起點後的交易日開始計算。",
        color=MUTED,
        fontsize=14,
        va="top",
        transform=ax.transAxes,
    )

    targets_line = "四個預測目標：" + "、".join(data["target_labels"])
    add_card(ax, 0.5, 0.657, 0.445, 0.155, facecolor=WHITE)
    ax.text(
        0.523,
        0.784,
        "一次看四種可能先出事的風險",
        color=TEAL,
        fontsize=15,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.523,
        0.74,
        wrap_zh(targets_line, 31),
        color=INK,
        fontsize=20,
        fontweight="bold",
        va="top",
        linespacing=1.4,
        transform=ax.transAxes,
    )

    sample_line = (
        f"樣本外約 {data['n_oos_min']} 至 {data['n_oos_max']} 週，"
        f"起自 {data['oos_start']}"
    )
    add_card(ax, 0.055, 0.522, 0.89, 0.09, facecolor=PALE, edgecolor=PALE)
    ax.text(
        0.078,
        0.568,
        sample_line,
        color=NAVY,
        fontsize=23,
        fontweight="bold",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.922,
        0.568,
        "每週重估｜基準模型與擴充模型公平比較",
        color=MUTED,
        fontsize=13,
        ha="right",
        va="center",
        transform=ax.transAxes,
    )

    gate_intro = (
        f"{zh_integer(data['gate_count'])}道關卡要同時過：誤差變小、檢定統計量低於 "
        f"{data['dm_threshold']}、多重檢定校正後 q 值低於 {data['q_threshold']}、"
        "關聯方向為正、前後半段都改善"
    )
    add_card(ax, 0.055, 0.247, 0.89, 0.23, facecolor=WHITE)
    ax.text(
        0.078,
        0.445,
        wrap_zh(gate_intro, 70),
        color=INK,
        fontsize=19,
        fontweight="bold",
        va="top",
        linespacing=1.35,
        transform=ax.transAxes,
    )

    gate_labels = [
        ("一", "誤差變小"),
        ("二", f"統計量 < {data['dm_threshold']}"),
        ("三", f"q 值 < {data['q_threshold']}"),
        ("四", "關聯方向為正"),
        ("五", "前後半段都改善"),
    ]
    gate_x = 0.078
    gate_width = 0.158
    for ordinal, label in gate_labels:
        add_card(
            ax,
            gate_x,
            0.278,
            gate_width,
            0.085,
            facecolor=TEAL_SOFT,
            edgecolor="#C5E2E0",
            radius=0.012,
        )
        ax.text(
            gate_x + 0.018,
            0.337,
            ordinal,
            color=TEAL,
            fontsize=13,
            fontweight="bold",
            va="top",
            transform=ax.transAxes,
        )
        ax.text(
            gate_x + 0.018,
            0.309,
            wrap_zh(label, 12),
            color=INK,
            fontsize=15,
            fontweight="bold",
            va="top",
            transform=ax.transAxes,
        )
        gate_x += 0.171

    rise_line = (
        "指標本身確實在上升："
        f"{data['proxy_start_date']} 的 {data['proxy_start']:.4f} 到 "
        f"{data['proxy_end_date']} 的 {data['proxy_end']:.4f}，"
        f"漲 {data['proxy_change']:.2f}%"
    )
    add_card(ax, 0.055, 0.085, 0.89, 0.112, facecolor=AMBER_SOFT, edgecolor="#E8D4AA")
    ax.text(
        0.078,
        0.158,
        "先確認描述事實",
        color=AMBER,
        fontsize=14,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.119,
        rise_line,
        color=INK,
        fontsize=21,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )

    add_footer(ax, data["experiment_id"])
    save_panel(fig, "02_how_we_tested.png")


def render_panel_3(data: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    add_header(
        ax,
        "結果：曲線看得到擁擠，卻預警不了下一週",
        "四個目標，沒有一格過關",
    )

    add_card(ax, 0.055, 0.657, 0.25, 0.155, facecolor=RED_SOFT, edgecolor="#E5BAB6")
    ax.text(
        0.078,
        0.782,
        "四個目標通過數",
        color=RED,
        fontsize=16,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.743,
        f"{data['n_pass']} / {data['n_total']}",
        color=RED,
        fontsize=52,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.682,
        f"四個目標通過數：{data['n_pass']} / {data['n_total']}",
        color=INK,
        fontsize=14,
        va="top",
        transform=ax.transAxes,
    )

    tlt_line = (
        f"TLT 5 日波動：誤差改善 {signed_percent(data['tlt_improvement'])}，"
        f"統計量 {data['tlt_t']:.2f}，校正後 q 值 {data['tlt_q']:.3f}"
    )
    add_card(ax, 0.33, 0.657, 0.615, 0.155, facecolor=WHITE)
    ax.text(
        0.353,
        0.782,
        "看似改善，但證據強度不夠",
        color=BLUE,
        fontsize=15,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.353,
        0.738,
        wrap_zh(tlt_line, 49),
        color=INK,
        fontsize=22,
        fontweight="bold",
        va="top",
        linespacing=1.4,
        transform=ax.transAxes,
    )

    ief_line = (
        f"IEF 5 日波動：統計量 {data['ief_t']:.2f}，"
        f"同樣離門檻 {data['dm_threshold']} 很遠"
    )
    add_card(ax, 0.055, 0.517, 0.89, 0.09, facecolor=PALE, edgecolor=PALE)
    ax.text(
        0.078,
        0.562,
        ief_line,
        color=INK,
        fontsize=22,
        fontweight="bold",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.922,
        0.562,
        "沒有接近預先寫死的通過線",
        color=MUTED,
        fontsize=13,
        ha="right",
        va="center",
        transform=ax.transAxes,
    )

    stability_line = (
        f"TLT 前半段改善 {signed_percent(data['tlt_early'])}，後半段翻負 "
        f"{signed_percent(data['tlt_late'])}（不穩定）"
    )
    add_card(ax, 0.055, 0.326, 0.55, 0.145, facecolor=BLUE_SOFT, edgecolor="#B8D1E4")
    ax.text(
        0.078,
        0.442,
        "最關鍵的破綻：前後半段翻轉",
        color=BLUE,
        fontsize=14,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.078,
        0.399,
        wrap_zh(stability_line, 40),
        color=INK,
        fontsize=20,
        fontweight="bold",
        va="top",
        linespacing=1.4,
        transform=ax.transAxes,
    )
    baseline_x = 0.338
    ax.plot([baseline_x, baseline_x], [0.342, 0.37], color=MUTED, lw=1.2, transform=ax.transAxes)
    positive_width = min(abs(data["tlt_early"]) / 12.0, 0.19)
    negative_width = min(abs(data["tlt_late"]) / 12.0, 0.19)
    ax.add_patch(
        Rectangle(
            (baseline_x, 0.357),
            positive_width,
            0.012,
            color=GREEN,
            transform=ax.transAxes,
        )
    )
    ax.add_patch(
        Rectangle(
            (baseline_x - negative_width, 0.341),
            negative_width,
            0.012,
            color=RED,
            transform=ax.transAxes,
        )
    )

    corr_line = (
        "股債相關是最差的一格："
        f"{signed_percent(data['corr_improvement'])}，後半段 "
        f"{signed_percent(data['corr_late'])}"
    )
    add_card(ax, 0.63, 0.326, 0.315, 0.145, facecolor=RED_SOFT, edgecolor="#E5BAB6")
    ax.text(
        0.653,
        0.442,
        "直接惡化",
        color=RED,
        fontsize=14,
        fontweight="bold",
        va="top",
        transform=ax.transAxes,
    )
    ax.text(
        0.653,
        0.4,
        wrap_zh(corr_line, 23),
        color=INK,
        fontsize=19,
        fontweight="bold",
        va="top",
        linespacing=1.4,
        transform=ax.transAxes,
    )

    add_card(ax, 0.055, 0.202, 0.89, 0.08, facecolor=NAVY, edgecolor=NAVY)
    ax.text(
        0.078,
        0.241,
        "結論：免費的公開擁擠度指標，不能當風險預警儀表板",
        color=WHITE,
        fontsize=23,
        fontweight="bold",
        va="center",
        transform=ax.transAxes,
    )

    caveat = (
        "這個 null 不能否定強制去槓桿機制本身，只說這個公開代理變數沒有穩健預測力"
    )
    add_card(ax, 0.055, 0.085, 0.89, 0.075, facecolor=AMBER_SOFT, edgecolor="#E8D4AA")
    ax.text(
        0.078,
        0.123,
        caveat,
        color=INK,
        fontsize=18,
        fontweight="bold",
        va="center",
        transform=ax.transAxes,
    )

    add_footer(ax, data["experiment_id"])
    save_panel(fig, "03_null_result.png")


def main() -> None:
    results = load_json(RESULTS_PATH)
    readme = load_text(README_PATH)
    article = load_text(ARTICLE_PATH)

    experiment_id = require_string(results, "experiment_id")
    require_contains(readme, experiment_id, README_PATH)
    require_contains(readme, "所有數字以 `k1683_results.json` 為準", README_PATH)
    require_contains(
        article,
        "對沖基金在國債期貨越站越擠，但免費的擁擠度指標預警不了下一週",
        ARTICLE_PATH,
    )
    require_contains(article, f"實驗 {experiment_id}", ARTICLE_PATH)

    data = extract_panel_data(results)
    os.makedirs(out_dir, exist_ok=True)
    render_panel_1(data)
    render_panel_2(data)
    render_panel_3(data)


if __name__ == "__main__":
    main()
