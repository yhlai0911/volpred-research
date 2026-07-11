#!/usr/bin/env python3
"""Render the K1683 Treasury-futures crowding lazypack as three PNG files.

Every displayed statistic is loaded from the experiment results JSON.  The
article markdown is also loaded as part of the evidence package and checked
against the experiment id before rendering.  Missing or malformed evidence is
an error by design.
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
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_531e4c87-r3/panels/mile_531e4c87_article.md"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1683/k1683_results.json"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_531e4c87-r3/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#13263D"
INK = "#172334"
MUTED = "#596778"
PAPER = "#F4F7FA"
WHITE = "#FFFFFF"
LINE = "#D5DEE8"
BLUE = "#2E68A1"
BLUE_SOFT = "#E8F0F8"
TEAL = "#147D78"
TEAL_SOFT = "#E5F3F1"
AMBER = "#B47417"
AMBER_SOFT = "#FAF0DF"
RED = "#B8423D"
RED_SOFT = "#F9E9E7"
GREEN = "#2D7651"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def require_path(data: Any, dotted_path: str) -> Any:
    """Resolve a dotted JSON path and fail loudly when any part is absent."""
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing required evidence field: {dotted_path}")
        current = current[part]
    return current


def require_dict(data: Any, dotted_path: str) -> dict[str, Any]:
    value = require_path(data, dotted_path)
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {dotted_path}, got {type(value).__name__}")
    return value


def require_list(data: Any, dotted_path: str) -> list[Any]:
    value = require_path(data, dotted_path)
    if not isinstance(value, list):
        raise TypeError(f"Expected array at {dotted_path}, got {type(value).__name__}")
    return value


def require_str(data: Any, dotted_path: str) -> str:
    value = require_path(data, dotted_path)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {dotted_path}")
    return value


def require_number(data: Any, dotted_path: str) -> float:
    value = require_path(data, dotted_path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric value at {dotted_path}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite value at {dotted_path}")
    return number


def require_int(data: Any, dotted_path: str) -> int:
    number = require_number(data, dotted_path)
    if not number.is_integer():
        raise ValueError(f"Expected integer-valued evidence at {dotted_path}")
    return int(number)


def signed_pct(value: float) -> str:
    return f"{value:+.2f}%"


def number_2(value: float) -> str:
    return f"{value:.2f}"


def compact_number(value: float) -> str:
    return f"{int(value)}" if value.is_integer() else f"{value:g}"


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


def zh_count(value: int) -> str:
    if value not in ZH_DIGITS:
        raise ValueError(f"No Traditional Chinese count formatter for {value}")
    return ZH_DIGITS[value]


def wrap_text(text: str, width: int) -> str:
    """Wrap Chinese/mixed text deterministically before handing it to matplotlib."""
    wrapped: list[str] = []
    for paragraph in text.splitlines() or [""]:
        lines = textwrap.wrap(
            paragraph,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=True,
        )
        wrapped.extend(lines or [""])
    return "\n".join(wrapped)


def load_evidence() -> tuple[dict[str, Any], str]:
    with RESULTS_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError("The results evidence root must be a JSON object")

    article = ARTICLE_PATH.read_text(encoding="utf-8")
    experiment_id = require_str(data, "experiment_id")
    expected_reference = (
        f"experiments/{experiment_id.lower()}/{experiment_id.lower()}_results.json"
    )
    if expected_reference not in article:
        raise ValueError(
            "Article evidence does not cite the loaded results file: "
            f"{expected_reference}"
        )
    if f"實驗 {experiment_id}" not in article:
        raise ValueError(f"Article evidence does not identify experiment {experiment_id}")
    return data, article


def cell_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = require_dict(data, "results")
    mapped: dict[str, dict[str, Any]] = {}
    for cell, payload in results.items():
        if not isinstance(payload, dict):
            raise TypeError(f"results.{cell} must be an object")
        mapped[cell] = payload
    return mapped


def require_cells(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cells = cell_map(data)
    expected = ("TLT_RV5", "IEF_RV5", "DGS10_JUMP5", "SPY_TLT_CORR20")
    missing = [cell for cell in expected if cell not in cells]
    if missing:
        raise KeyError(f"Missing required primary result cells: {missing}")
    return {cell: cells[cell] for cell in expected}


def subperiod(cell: dict[str, Any], cell_name: str, period_name: str) -> dict[str, Any]:
    periods = cell.get("subperiods")
    if not isinstance(periods, list):
        raise TypeError(f"results.{cell_name}.subperiods must be an array")
    matches = [p for p in periods if isinstance(p, dict) and p.get("name") == period_name]
    if len(matches) != 1:
        raise KeyError(
            f"Expected one {period_name!r} subperiod in results.{cell_name}.subperiods"
        )
    return matches[0]


def nested_number(obj: dict[str, Any], path: str, context: str) -> float:
    current: Any = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing required evidence field: {context}.{path}")
        current = current[part]
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        raise TypeError(f"Expected numeric value at {context}.{path}")
    value = float(current)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite value at {context}.{path}")
    return value


def nested_int(obj: dict[str, Any], path: str, context: str) -> int:
    value = nested_number(obj, path, context)
    if not value.is_integer():
        raise ValueError(f"Expected integer-valued evidence at {context}.{path}")
    return int(value)


def target_labels(cells: dict[str, dict[str, Any]]) -> list[str]:
    """Build reader labels while sourcing every horizon/maturity digit from cell ids."""
    labels: list[str] = []

    for cell_id, asset in (("TLT_RV5", "TLT"), ("IEF_RV5", "IEF")):
        match = re.fullmatch(rf"{asset}_RV(\d+)", cell_id)
        if not match or cell_id not in cells:
            raise ValueError(f"Unexpected duration-volatility cell id: {cell_id}")
        labels.append(f"{asset} {int(match.group(1))} 日波動")

    yield_match = re.fullmatch(r"DGS(\d+)_JUMP(\d+)", "DGS10_JUMP5")
    if not yield_match or "DGS10_JUMP5" not in cells:
        raise ValueError("Unexpected yield-jump cell id")
    labels.append(f"{int(yield_match.group(1))} 年殖利率跳動")

    corr_match = re.fullmatch(r"SPY_TLT_CORR(\d+)", "SPY_TLT_CORR20")
    if not corr_match or "SPY_TLT_CORR20" not in cells:
        raise ValueError("Unexpected stock-bond-correlation cell id")
    labels.append(f"股債 {int(corr_match.group(1))} 日相關")
    return labels


def contract_labels(data: dict[str, Any]) -> list[str]:
    contracts = require_dict(data, "data_provenance.cftc.contracts")
    maturities: list[tuple[int, str]] = []
    bond_seen = False
    for name in contracts.values():
        if not isinstance(name, str):
            raise TypeError("CFTC contract labels must be strings")
        match = re.fullmatch(r"UST_(\d+)Y", name)
        if match:
            years = int(match.group(1))
            maturities.append((years, f"{years} 年"))
        elif name == "UST_BOND":
            bond_seen = True
        else:
            raise ValueError(f"Unexpected Treasury contract label: {name}")
    if len(maturities) != 3 or not bond_seen:
        raise ValueError("Expected three numbered Treasury maturities plus UST_BOND")
    return [label for _, label in sorted(maturities)] + ["長債"]


def formula_multiplier(data: dict[str, Any]) -> int:
    formula = require_str(data, "signal.formula")
    match = re.search(
        r"\(long\+short\+(\d+)\*spread\)/\((\d+)\*open_interest\)", formula
    )
    if not match:
        raise ValueError("signal.formula does not contain the expected participation ratio")
    numerator_multiplier = int(match.group(1))
    denominator_multiplier = int(match.group(2))
    if numerator_multiplier != denominator_multiplier:
        raise ValueError("Expected the same spread/open-interest multiplier")
    return numerator_multiplier


def gate_values(data: dict[str, Any]) -> tuple[int, float, float]:
    gate = require_str(data, "primary_family.gate")
    required_fragments = (
        "improvement>0",
        "HLN-DM t<",
        "BH q<",
        "positive association coefficient",
        "early/late improvements both positive",
    )
    absent = [fragment for fragment in required_fragments if fragment not in gate]
    if absent:
        raise ValueError(f"primary_family.gate is missing expected rules: {absent}")

    t_match = re.search(r"HLN-DM t<(-?\d+(?:\.\d+)?)", gate)
    q_match = re.search(r"BH q<(-?\d+(?:\.\d+)?)", gate)
    if not t_match or not q_match:
        raise ValueError("Could not parse t/q thresholds from primary_family.gate")
    return len(required_fragments), float(t_match.group(1)), float(q_match.group(1))


def top_fund_context(data: dict[str, Any]) -> tuple[int, str]:
    context = require_dict(data, "external_context_not_model_input")
    matching_keys = [
        key
        for key in context
        if re.fullmatch(r"top_\d+_share_percent_\d{4}_sep", key)
    ]
    if len(matching_keys) != 1:
        raise KeyError("Expected exactly one top-N Form PF share field")
    key = matching_keys[0]
    count_match = re.fullmatch(r"top_(\d+)_share_percent_\d{4}_sep", key)
    if not count_match:
        raise ValueError(f"Could not parse fund count from {key}")
    fund_count = int(count_match.group(1))
    share = require_number(data, f"external_context_not_model_input.{key}")
    tenths = share / 10.0
    rounded = int(round(tenths))
    if not math.isclose(tenths, rounded) or rounded not in ZH_DIGITS:
        raise ValueError("Top-fund share cannot be expressed exactly as Chinese tenths")
    return fund_count, f"{zh_count(rounded)}成"


def new_canvas(title: str) -> tuple[Figure, Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, color=PAPER, zorder=0))
    ax.add_patch(Rectangle((0, 0.855), 1, 0.145, transform=ax.transAxes, color=NAVY, zorder=1))
    ax.text(
        0.05,
        0.965,
        "VOLPRED｜國債期貨擁擠度懶人包",
        transform=ax.transAxes,
        color="#BFD1E3",
        fontsize=11,
        fontweight="bold",
        va="top",
        zorder=2,
    )
    ax.text(
        0.05,
        0.916,
        title,
        transform=ax.transAxes,
        color=WHITE,
        fontsize=28,
        fontweight="bold",
        va="center",
        zorder=2,
    )
    return fig, ax


def card(
    ax: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    accent: str | None = None,
    radius: float = 0.016,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=1.1,
            zorder=1,
        )
    )
    if accent:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                0.008,
                height,
                boxstyle=f"round,pad=0,rounding_size={radius / 2}",
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor=accent,
                linewidth=0,
                zorder=2,
            )
        )


def footer(ax: Axes, experiment_id: str, qualifier: str) -> None:
    ax.plot([0.05, 0.95], [0.078, 0.078], transform=ax.transAxes, color=LINE, lw=1)
    ax.text(
        0.05,
        0.042,
        f"資料來源：experiment {experiment_id}",
        transform=ax.transAxes,
        fontsize=10.5,
        color=MUTED,
        va="center",
    )
    ax.text(
        0.95,
        0.042,
        qualifier,
        transform=ax.transAxes,
        fontsize=9.5,
        color=MUTED,
        ha="right",
        va="center",
    )


def save(fig: Figure, filename: str) -> None:
    destination = os.path.join(out_dir, filename)
    fig.savefig(destination, dpi=DPI, facecolor=WHITE, bbox_inches=None, pad_inches=0)
    plt.close(fig)


def render_panel_1(data: dict[str, Any]) -> None:
    experiment_id = require_str(data, "experiment_id")
    gross = require_number(
        data,
        "external_context_not_model_input.gross_treasury_exposure_2025_sep_trillion_usd",
    )
    long = require_number(
        data,
        "external_context_not_model_input.long_exposure_2025_sep_trillion_usd",
    )
    short = require_number(
        data,
        "external_context_not_model_input.short_exposure_2025_sep_trillion_usd",
    )
    fund_count, fund_share = top_fund_context(data)
    contracts = contract_labels(data)
    multiplier = formula_multiplier(data)
    context_note = require_str(data, "external_context_not_model_input.note")
    normalized_note = " ".join(context_note.casefold().split())
    explicitly_not_used = re.search(
        r"\b(?:not|never)\b[^.;:\n]{0,80}\bused\b"
        r"|\bno\b[^.;:\n]{0,160}\b(?:was|were)\b[^.;:\n]{0,80}\bused\b",
        normalized_note,
    )
    if "context only" not in normalized_note or explicitly_not_used is None:
        raise ValueError("External-context note no longer says the data were not used")

    external_sentence = (
        "機密資料：Form PF 顯示對沖基金美國國債曝險約 "
        f"{gross:.1f} 兆美元（多 {long:.1f} 兆 / 空 {short:.1f} 兆，"
        f"前 {fund_count} 大佔{fund_share}）"
    )
    public_sentence = "免費替代品：CFTC 每週公佈的 Leveraged Funds 期貨持倉"
    formula = (
        "代理指標 = "
        f"(多單 + 空單 + {multiplier}×價差單) ÷ "
        f"({multiplier}×未平倉量)"
    )
    contract_sentence = f"涵蓋 {' / '.join(contracts)}四個國債期貨合約"

    fig, ax = new_canvas("從機密曝險，到人人可用的公開代理指標")

    card(ax, 0.05, 0.15, 0.42, 0.64, facecolor=WHITE, accent=AMBER)
    ax.text(
        0.08,
        0.755,
        "機密的 Form PF",
        transform=ax.transAxes,
        fontsize=16,
        fontweight="bold",
        color=AMBER,
        va="top",
    )
    ax.text(
        0.08,
        0.695,
        f"{gross:.1f} 兆美元",
        transform=ax.transAxes,
        fontsize=39,
        fontweight="bold",
        color=INK,
        va="top",
    )
    ax.text(
        0.08,
        0.585,
        wrap_text(external_sentence, 25),
        transform=ax.transAxes,
        fontsize=14.5,
        color=INK,
        linespacing=1.35,
        va="top",
    )
    ax.add_patch(
        FancyBboxPatch(
            (0.08, 0.205),
            0.34,
            0.075,
            boxstyle="round,pad=0.008,rounding_size=0.012",
            transform=ax.transAxes,
            facecolor=AMBER_SOFT,
            edgecolor="none",
            zorder=2,
        )
    )
    ax.text(
        0.25,
        0.242,
        "這是外部脈絡，不是模型輸入",
        transform=ax.transAxes,
        fontsize=13.5,
        fontweight="bold",
        color=AMBER,
        ha="center",
        va="center",
        zorder=3,
    )

    ax.add_patch(
        FancyArrowPatch(
            (0.475, 0.635),
            (0.525, 0.635),
            transform=ax.transAxes,
            arrowstyle="-|>",
            mutation_scale=20,
            linewidth=2,
            color=BLUE,
            zorder=4,
        )
    )

    card(ax, 0.53, 0.51, 0.42, 0.28, facecolor=BLUE_SOFT, edgecolor="#C9D9EA", accent=BLUE)
    ax.text(
        0.56,
        0.748,
        "公開資料入口",
        transform=ax.transAxes,
        fontsize=13,
        fontweight="bold",
        color=BLUE,
        va="top",
    )
    ax.text(
        0.56,
        0.695,
        wrap_text(public_sentence, 20),
        transform=ax.transAxes,
        fontsize=18,
        fontweight="bold",
        color=INK,
        linespacing=1.28,
        va="top",
    )
    ax.text(
        0.56,
        0.55,
        "用公開分類部位描述擁擠程度",
        transform=ax.transAxes,
        fontsize=12.5,
        color=MUTED,
        va="bottom",
    )

    card(ax, 0.53, 0.15, 0.42, 0.31, facecolor=WHITE, accent=TEAL)
    ax.text(
        0.56,
        0.42,
        "怎麼算",
        transform=ax.transAxes,
        fontsize=13,
        fontweight="bold",
        color=TEAL,
        va="top",
    )
    formula_lines = formula.replace(" ÷ ", " ÷\n")
    ax.text(
        0.56,
        0.365,
        formula_lines,
        transform=ax.transAxes,
        fontsize=17,
        fontweight="bold",
        color=INK,
        linespacing=1.35,
        va="top",
    )
    ax.text(
        0.56,
        0.205,
        wrap_text(contract_sentence, 29),
        transform=ax.transAxes,
        fontsize=12.5,
        color=MUTED,
        linespacing=1.25,
        va="top",
    )

    footer(ax, experiment_id, "Form PF 僅作外部脈絡；模型使用 CFTC 公開資料")
    save(fig, "01_free_proxy_concept.png")


def render_panel_2(data: dict[str, Any]) -> None:
    experiment_id = require_str(data, "experiment_id")
    cells = require_cells(data)
    labels = target_labels(cells)
    target_count = len(labels)
    gate_count, t_threshold, q_threshold = gate_values(data)

    timing = require_str(data, "signal.timing")
    if "signal.shift(1)" not in timing or "targets start strictly after origin" not in timing:
        raise ValueError("signal.timing no longer documents the required lag and target order")

    oos_sizes = [nested_int(cell, "n_oos", f"results.{name}") for name, cell in cells.items()]
    oos_starts: list[str] = []
    for name, cell in cells.items():
        start = cell.get("oos_start")
        if not isinstance(start, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
            raise TypeError(f"results.{name}.oos_start must be an ISO date string")
        oos_starts.append(start)

    proxy_start_date = require_str(data, "signal.descriptive_proxy_change.start_report")
    proxy_end_date = require_str(data, "signal.descriptive_proxy_change.end_report")
    proxy_start = require_number(
        data, "signal.descriptive_proxy_change.gross_participation_start"
    )
    proxy_end = require_number(data, "signal.descriptive_proxy_change.gross_participation_end")
    proxy_change = require_number(data, "signal.descriptive_proxy_change.change_pct")

    target_sentence = f"{zh_count(target_count)}個預測目標：{'、'.join(labels)}"
    sample_sentence = (
        f"樣本外約 {min(oos_sizes)} 至 {max(oos_sizes)} 週，起自 {min(oos_starts)}"
    )
    gate_sentence = (
        f"{zh_count(gate_count)}道關卡要同時過：誤差變小、檢定統計量低於 "
        f"{compact_number(t_threshold)}\n多重檢定校正後 q 值低於 "
        f"{compact_number(q_threshold)}、關聯方向為正、前後半段都改善"
    )
    proxy_sentence = (
        "指標本身確實在上升："
        f"{proxy_start_date} 的 {proxy_start:.4f} 到 "
        f"{proxy_end_date} 的 {proxy_end:.4f}，漲 {proxy_change:.2f}%"
    )

    fig, ax = new_canvas("我們怎麼測：先鎖時間，再讓五道關卡一起把關")

    card(ax, 0.05, 0.675, 0.42, 0.135, facecolor=TEAL_SOFT, edgecolor="#C5E2DE", accent=TEAL)
    ax.text(
        0.08,
        0.775,
        "時間處理",
        transform=ax.transAxes,
        fontsize=11.5,
        color=TEAL,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.08,
        0.733,
        "指標一律落後使用，避免看到未來資料",
        transform=ax.transAxes,
        fontsize=16,
        color=INK,
        fontweight="bold",
        va="top",
    )

    card(ax, 0.51, 0.675, 0.44, 0.135, facecolor=BLUE_SOFT, edgecolor="#C9D9EA", accent=BLUE)
    ax.text(
        0.54,
        0.775,
        "代理指標走勢",
        transform=ax.transAxes,
        fontsize=11.5,
        color=BLUE,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.54,
        0.737,
        wrap_text(proxy_sentence, 39),
        transform=ax.transAxes,
        fontsize=12.3,
        color=INK,
        linespacing=1.25,
        va="top",
    )

    card(ax, 0.05, 0.395, 0.90, 0.225, facecolor=WHITE, accent=BLUE)
    ax.text(
        0.08,
        0.58,
        target_sentence,
        transform=ax.transAxes,
        fontsize=17,
        color=INK,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.08,
        0.525,
        sample_sentence,
        transform=ax.transAxes,
        fontsize=12.5,
        color=MUTED,
        va="top",
    )

    chip_y = 0.425
    chip_width = 0.195
    chip_gap = 0.02
    chip_colors = (BLUE_SOFT, TEAL_SOFT, AMBER_SOFT, RED_SOFT)
    for index, label in enumerate(labels):
        x = 0.08 + index * (chip_width + chip_gap)
        ax.add_patch(
            FancyBboxPatch(
                (x, chip_y),
                chip_width,
                0.065,
                boxstyle="round,pad=0.006,rounding_size=0.01",
                transform=ax.transAxes,
                facecolor=chip_colors[index],
                edgecolor="none",
                zorder=2,
            )
        )
        ax.text(
            x + chip_width / 2,
            chip_y + 0.0325,
            label,
            transform=ax.transAxes,
            fontsize=11.5,
            color=INK,
            fontweight="bold",
            ha="center",
            va="center",
            zorder=3,
        )

    card(ax, 0.05, 0.13, 0.90, 0.215, facecolor=WHITE, accent=AMBER)
    ax.text(
        0.08,
        0.305,
        wrap_text(gate_sentence, 40),
        transform=ax.transAxes,
        fontsize=15.2,
        color=INK,
        fontweight="bold",
        linespacing=1.3,
        va="top",
    )
    gate_labels = (
        "誤差↓",
        f"t < {compact_number(t_threshold)}",
        f"q < {compact_number(q_threshold)}",
        "方向為正",
        "前後期皆改善",
    )
    start_x = 0.105
    gap = 0.185
    for index, label in enumerate(gate_labels):
        x = start_x + index * gap
        ax.plot(
            [x - 0.028, x + 0.028],
            [0.18, 0.18],
            transform=ax.transAxes,
            color=TEAL,
            lw=5,
            solid_capstyle="round",
        )
        ax.text(
            x,
            0.152,
            label,
            transform=ax.transAxes,
            fontsize=10.5,
            color=MUTED,
            ha="center",
            va="top",
        )

    footer(ax, experiment_id, "所有目標皆採嚴格落後訊號與樣本外滾動預測")
    save(fig, "02_how_we_tested.png")


def render_panel_3(data: dict[str, Any]) -> None:
    experiment_id = require_str(data, "experiment_id")
    cells = require_cells(data)
    labels = target_labels(cells)
    total = len(labels)
    passed = require_int(data, "verdict.n_primary_pass")
    status = require_str(data, "verdict.status")
    if status != "NULL_NO_ROBUST_INCREMENT":
        raise ValueError(f"Unexpected verdict.status: {status}")
    if passed != sum(
        1 for cell in require_list(data, "primary_family.audit") if isinstance(cell, dict) and cell.get("pass") is True
    ):
        raise ValueError("verdict.n_primary_pass disagrees with primary_family.audit")

    _, t_threshold, _ = gate_values(data)
    tlt = cells["TLT_RV5"]
    ief = cells["IEF_RV5"]
    corr = cells["SPY_TLT_CORR20"]
    tlt_early = subperiod(tlt, "TLT_RV5", "early")
    tlt_late = subperiod(tlt, "TLT_RV5", "late")
    corr_late = subperiod(corr, "SPY_TLT_CORR20", "late")

    tlt_improvement = nested_number(tlt, "loss_improvement_pct", "results.TLT_RV5")
    tlt_t = nested_number(tlt, "dm_hln.t_hln", "results.TLT_RV5")
    tlt_q = nested_number(
        tlt,
        "dm_hln.bh_fdr_q_primary_family_4",
        "results.TLT_RV5",
    )
    ief_t = nested_number(ief, "dm_hln.t_hln", "results.IEF_RV5")
    tlt_early_improvement = nested_number(
        tlt_early, "loss_improvement_pct", "results.TLT_RV5.subperiods.early"
    )
    tlt_late_improvement = nested_number(
        tlt_late, "loss_improvement_pct", "results.TLT_RV5.subperiods.late"
    )
    corr_improvement = nested_number(
        corr, "loss_improvement_pct", "results.SPY_TLT_CORR20"
    )
    corr_late_improvement = nested_number(
        corr_late,
        "loss_improvement_pct",
        "results.SPY_TLT_CORR20.subperiods.late",
    )

    pass_sentence = f"{zh_count(total)}個目標通過數"
    conclusion = "結論：免費的公開擁擠度指標，不能當風險預警儀表板"
    caveat = (
        "這個 null 不能否定強制去槓桿機制本身，只說這個公開代理變數沒有穩健預測力"
    )

    fig, ax = new_canvas(f"{zh_count(total)}格全滅：有方向感，不等於有預警力")

    card(ax, 0.05, 0.65, 0.90, 0.16, facecolor=RED_SOFT, edgecolor="#EBCAC7", accent=RED)
    ax.text(
        0.08,
        0.785,
        pass_sentence,
        transform=ax.transAxes,
        fontsize=14,
        color=RED,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.08,
        0.700,
        f"{passed} / {total}",
        transform=ax.transAxes,
        fontsize=36,
        color=INK,
        fontweight="bold",
        va="center",
    )
    ax.text(
        0.32,
        0.723,
        wrap_text(conclusion, 32),
        transform=ax.transAxes,
        fontsize=19,
        color=INK,
        fontweight="bold",
        linespacing=1.25,
        va="center",
    )

    metric_y = 0.345
    metric_h = 0.255
    metric_w = 0.205
    metric_xs = (0.05, 0.28, 0.51, 0.74)
    metric_faces = (BLUE_SOFT, BLUE_SOFT, AMBER_SOFT, RED_SOFT)
    metric_accents = (BLUE, BLUE, AMBER, RED)
    for x, face, accent in zip(metric_xs, metric_faces, metric_accents):
        card(ax, x, metric_y, metric_w, metric_h, facecolor=face, accent=accent)

    ax.text(
        0.075,
        0.565,
        labels[0],
        transform=ax.transAxes,
        fontsize=13.5,
        color=BLUE,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.075,
        0.512,
        f"誤差改善 {signed_pct(tlt_improvement)}",
        transform=ax.transAxes,
        fontsize=17,
        color=INK,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.075,
        0.447,
        f"統計量 {number_2(tlt_t)}\n校正後 q 值 {tlt_q:.3f}",
        transform=ax.transAxes,
        fontsize=12.5,
        color=MUTED,
        linespacing=1.35,
        va="top",
    )

    ax.text(
        0.305,
        0.565,
        labels[1],
        transform=ax.transAxes,
        fontsize=13.5,
        color=BLUE,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.305,
        0.512,
        f"統計量 {number_2(ief_t)}",
        transform=ax.transAxes,
        fontsize=20,
        color=INK,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.305,
        0.432,
        wrap_text(
            f"同樣離門檻 {compact_number(t_threshold)} 很遠",
            15,
        ),
        transform=ax.transAxes,
        fontsize=12.5,
        color=MUTED,
        linespacing=1.3,
        va="top",
    )

    ax.text(
        0.535,
        0.565,
        "前後半段不穩定",
        transform=ax.transAxes,
        fontsize=13.5,
        color=AMBER,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.535,
        0.505,
        wrap_text(
            "TLT 前半段改善 "
            f"{signed_pct(tlt_early_improvement)}，後半段翻負 "
            f"{signed_pct(tlt_late_improvement)}（不穩定）",
            17,
        ),
        transform=ax.transAxes,
        fontsize=13,
        color=INK,
        fontweight="bold",
        linespacing=1.35,
        va="top",
    )

    ax.text(
        0.765,
        0.565,
        "股債相關是最差的一格",
        transform=ax.transAxes,
        fontsize=12.8,
        color=RED,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.765,
        0.505,
        signed_pct(corr_improvement),
        transform=ax.transAxes,
        fontsize=25,
        color=INK,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.765,
        0.425,
        f"後半段 {signed_pct(corr_late_improvement)}",
        transform=ax.transAxes,
        fontsize=12.5,
        color=MUTED,
        va="top",
    )

    card(ax, 0.05, 0.12, 0.90, 0.17, facecolor=WHITE, accent=TEAL)
    ax.text(
        0.08,
        0.255,
        "這個 null 能講到哪裡？",
        transform=ax.transAxes,
        fontsize=12.5,
        color=TEAL,
        fontweight="bold",
        va="top",
    )
    ax.text(
        0.08,
        0.205,
        wrap_text(caveat, 66),
        transform=ax.transAxes,
        fontsize=15.5,
        color=INK,
        fontweight="bold",
        linespacing=1.3,
        va="top",
    )

    footer(ax, experiment_id, "null result：未發現穩健增量預測力，不是機制否定")
    save(fig, "03_null_result.png")


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    data, _article = load_evidence()
    render_panel_1(data)
    render_panel_2(data)
    render_panel_3(data)


if __name__ == "__main__":
    main()
