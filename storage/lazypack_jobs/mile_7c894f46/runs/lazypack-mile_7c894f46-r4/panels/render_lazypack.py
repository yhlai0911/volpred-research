#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the K1801 reader article."""

from __future__ import annotations

import hashlib
import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1801/k1801_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1801/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_7c894f46/runs/lazypack-mile_7c894f46-r4/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_7c894f46/runs/lazypack-mile_7c894f46-r4/panels/"
    "mile_7c894f46_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_7c894f46/runs/lazypack-mile_7c894f46-r4/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

WHITE = "#FFFFFF"
INK = "#163034"
MUTED = "#617074"
RULE = "#D9E0DE"
SOFT = "#F3F5F2"
PM25 = "#B7633F"
PM25_SOFT = "#F4E6DE"
VIX = "#356D88"
VIX_SOFT = "#E4EEF2"
GOLD = "#D9A34A"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"{path} 的最外層必須是 JSON object")
    return payload


def require_text_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"必要 evidence 檔案是空的：{path}")
    return text


def require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"{context} 缺少必要欄位 {key!r}")
    return mapping[key]


def json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"無效 JSON Pointer：{pointer!r}")

    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"evidence 缺少 JSON Pointer {pointer!r}")
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise KeyError(f"陣列索引不是整數：{pointer!r}") from exc
            try:
                current = current[index]
            except IndexError as exc:
                raise KeyError(f"陣列索引超出範圍：{pointer!r}") from exc
        else:
            raise KeyError(f"JSON Pointer 無法繼續解析：{pointer!r}")
    return current


def format_metric(value: Any, format_spec: dict[str, Any]) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"metric value 必須是數字，實際為 {type(value).__name__}")

    kind = require(format_spec, "kind", "metric format")
    suffix = require(format_spec, "suffix", "metric format")
    if not isinstance(suffix, str):
        raise TypeError("metric suffix 必須是字串")

    if kind == "integer":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"integer metric 收到非整數值：{value!r}")
        rendered = f"{int(value):,}"
    elif kind == "number":
        digits = require(format_spec, "digits", "number format")
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            raise TypeError("number format 的 digits 必須是非負整數")
        rendered = f"{float(value):.{digits}f}"
    else:
        raise ValueError(f"不支援的 metric format kind：{kind!r}")
    return rendered + suffix


def find_panel(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require(plan, "panels", "plan")
    if not isinstance(panels, list):
        raise TypeError("plan.panels 必須是陣列")
    matches = [
        panel
        for panel in panels
        if isinstance(panel, dict) and panel.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"plan 中必須且只能有一個 panel：{name}")
    return matches[0]


def panel_content(
    panel: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    expected_metric_count: int,
) -> dict[str, Any]:
    title = require(panel, "title", "panel")
    alt = require(panel, "alt", "panel")
    blocks = require(panel, "blocks", "panel")
    source_ids = require(panel, "sources", "panel")
    if not isinstance(title, str) or not isinstance(alt, str):
        raise TypeError("panel title 與 alt 必須是字串")
    if not isinstance(blocks, list) or not isinstance(source_ids, list):
        raise TypeError("panel blocks 與 sources 必須是陣列")

    metrics: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise TypeError("panel block 必須是 object")
        kind = require(block, "kind", "panel block")
        if kind == "metric":
            label = require(block, "label", "metric block")
            value_spec = require(block, "value", "metric block")
            if not isinstance(label, str) or not isinstance(value_spec, dict):
                raise TypeError("metric label 必須是字串，value 必須是 object")
            source_id = require(value_spec, "source", "metric value")
            pointer = require(value_spec, "path", "metric value")
            format_spec = require(value_spec, "format", "metric value")
            if source_id not in evidence:
                raise KeyError(f"找不到 metric evidence source：{source_id!r}")
            if not isinstance(format_spec, dict):
                raise TypeError("metric format 必須是 object")
            raw_value = json_pointer(evidence[source_id], pointer)
            metrics.append(
                {
                    "label": label,
                    "raw": raw_value,
                    "display": format_metric(raw_value, format_spec),
                }
            )
        elif kind == "text":
            heading = require(block, "heading", "text block")
            body = require(block, "body", "text block")
            if (
                not isinstance(heading, str)
                or not isinstance(body, list)
                or not body
                or any(not isinstance(paragraph, str) for paragraph in body)
            ):
                raise TypeError("text block 必須含字串 heading 與非空字串陣列 body")
            texts.append({"heading": heading, "body": body})
        else:
            raise ValueError(f"不支援的 panel block kind：{kind!r}")

    if len(metrics) != expected_metric_count:
        raise ValueError(
            f"{panel.get('name')} 預期 {expected_metric_count} 個 metric，"
            f"實際 {len(metrics)} 個"
        )
    if len(texts) != 1:
        raise ValueError(f"{panel.get('name')} 必須恰有一個 text block")

    evidence_specs = require(plan, "evidence", "plan")
    if not isinstance(evidence_specs, dict):
        raise TypeError("plan.evidence 必須是 object")
    source_labels: list[str] = []
    for source_id in source_ids:
        if source_id not in evidence_specs:
            raise KeyError(f"plan.evidence 缺少來源：{source_id!r}")
        source_spec = evidence_specs[source_id]
        if not isinstance(source_spec, dict):
            raise TypeError(f"plan.evidence.{source_id} 必須是 object")
        label = require(source_spec, "label", f"plan.evidence.{source_id}")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"plan.evidence.{source_id}.label 必須是非空字串")
        source_labels.append(label)

    return {
        "title": title,
        "alt": alt,
        "metrics": metrics,
        "text": texts[0],
        "source_labels": source_labels,
    }


def verify_results_digest(plan: dict[str, Any]) -> None:
    evidence_specs = require(plan, "evidence", "plan")
    if not isinstance(evidence_specs, dict) or "k1801" not in evidence_specs:
        raise KeyError("plan.evidence 缺少 k1801")
    source_spec = evidence_specs["k1801"]
    if not isinstance(source_spec, dict):
        raise TypeError("plan.evidence.k1801 必須是 object")
    expected = require(source_spec, "sha256", "plan.evidence.k1801")
    if not isinstance(expected, str):
        raise TypeError("plan.evidence.k1801.sha256 必須是字串")
    actual = hashlib.sha256(RESULTS_PATH.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(
            "k1801_results.json 與 strict plan 的 sha256 不一致："
            f"expected={expected}, actual={actual}"
        )


def wrapped(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def canvas() -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(WHITE)
    return fig, ax


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.018,
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
            linewidth=linewidth,
        )
    )


def add_header(ax: plt.Axes, title: str, alt: str, accent: str) -> None:
    ax.add_patch(
        Rectangle(
            (0.065, 0.947),
            0.07,
            0.008,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        0.065,
        0.922,
        title,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=29,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.065,
        0.842,
        wrapped(alt, 58),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=14.5,
        color=MUTED,
        linespacing=1.4,
    )


def add_footer(ax: plt.Axes, source_labels: list[str]) -> None:
    if not source_labels:
        raise ValueError("panel 至少需要一個來源標籤")
    footer = "資料來源：" + "；".join(source_labels)
    ax.plot(
        [0.065, 0.935],
        [0.071, 0.071],
        transform=ax.transAxes,
        color=RULE,
        linewidth=1.0,
    )
    ax.text(
        0.065,
        0.047,
        footer,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=10.5,
        color=MUTED,
    )


def add_metric_card(
    ax: plt.Axes,
    metric: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    accent: str,
    value_size: float = 34,
) -> None:
    rounded_box(
        ax,
        x,
        y,
        width,
        height,
        facecolor=facecolor,
        edgecolor=RULE,
        linewidth=0.8,
    )
    ax.add_patch(
        Rectangle(
            (x + 0.022, y + height - 0.038),
            0.038,
            0.006,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        x + 0.025,
        y + height - 0.055,
        wrapped(metric["label"], 18),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12.5,
        color=MUTED,
        linespacing=1.25,
    )
    ax.text(
        x + 0.025,
        y + 0.025,
        metric["display"],
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=value_size,
        fontweight="bold",
        color=INK,
    )


def render_question(content: dict[str, Any], destination: Path) -> None:
    fig, ax = canvas()
    add_header(ax, content["title"], content["alt"], PM25)

    rounded_box(
        ax,
        0.065,
        0.355,
        0.545,
        0.395,
        facecolor=SOFT,
        edgecolor=RULE,
        linewidth=0.8,
    )
    ax.text(
        0.095,
        0.705,
        "把訊號與被觀察窗口分開",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=INK,
    )

    steps = [
        ("紐約五郡", "每日細懸浮微粒"),
        ("前一日數值", "由低到高分組"),
        ("接下來五個交易日", "大盤實際波動"),
    ]
    step_x = [0.095, 0.285, 0.475]
    step_colors = [PM25_SOFT, WHITE, VIX_SOFT]
    step_accents = [PM25, GOLD, VIX]
    for index, ((heading, detail), x_pos, fill, accent) in enumerate(
        zip(steps, step_x, step_colors, step_accents, strict=True)
    ):
        rounded_box(
            ax,
            x_pos,
            0.47,
            0.135,
            0.16,
            facecolor=fill,
            edgecolor=RULE,
            linewidth=0.7,
            radius=0.013,
        )
        ax.add_patch(
            Circle(
                (x_pos + 0.025, 0.598),
                0.009,
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )
        ax.text(
            x_pos + 0.02,
            0.565,
            wrapped(heading, 6),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=11.5,
            fontweight="bold",
            color=INK,
            linespacing=1.05,
        )
        ax.text(
            x_pos + 0.02,
            0.5,
            detail,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10.8,
            color=MUTED,
        )
        if index < len(steps) - 1:
            ax.add_patch(
                FancyArrowPatch(
                    (x_pos + 0.145, 0.55),
                    (step_x[index + 1] - 0.012, 0.55),
                    transform=ax.transAxes,
                    arrowstyle="-|>",
                    mutation_scale=12,
                    linewidth=1.4,
                    color=MUTED,
                )
            )

    ax.text(
        0.095,
        0.412,
        "同一批交易日再以 VIX 分組對照",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=12.5,
        color=VIX,
        fontweight="bold",
    )

    add_metric_card(
        ax,
        content["metrics"][0],
        0.64,
        0.555,
        0.295,
        0.195,
        facecolor=WHITE,
        accent=VIX,
        value_size=30,
    )
    add_metric_card(
        ax,
        content["metrics"][1],
        0.64,
        0.355,
        0.295,
        0.175,
        facecolor=PM25_SOFT,
        accent=PM25,
        value_size=28,
    )

    text_block = content["text"]
    rounded_box(
        ax,
        0.065,
        0.105,
        0.87,
        0.205,
        facecolor=WHITE,
        edgecolor=RULE,
        linewidth=0.9,
    )
    ax.text(
        0.092,
        0.275,
        text_block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=14,
        fontweight="bold",
        color=INK,
    )
    paragraph_y = [0.225, 0.155]
    for paragraph, y_pos in zip(text_block["body"], paragraph_y, strict=True):
        ax.add_patch(
            Circle(
                (0.096, y_pos - 0.006),
                0.0045,
                transform=ax.transAxes,
                facecolor=PM25 if y_pos == paragraph_y[0] else VIX,
                edgecolor="none",
            )
        )
        ax.text(
            0.112,
            y_pos,
            wrapped(paragraph, 62),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=11.8,
            color=INK,
            linespacing=1.35,
        )

    add_footer(ax, content["source_labels"])
    fig.savefig(destination, dpi=DPI, facecolor=WHITE)
    plt.close(fig)


def render_result(content: dict[str, Any], destination: Path) -> None:
    fig, ax = canvas()
    add_header(ax, content["title"], content["alt"], VIX)

    metrics = content["metrics"]
    raw_values = [metric["raw"] for metric in metrics]
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in raw_values
    ):
        raise TypeError("結果卡片的 bar scale 只能使用數字")
    scale = max(float(value) for value in raw_values)
    if scale <= 0:
        raise ValueError("結果卡片的 bar scale 必須大於零")

    card_specs = [
        (0.065, 0.545, PM25_SOFT, PM25),
        (0.515, 0.545, PM25_SOFT, PM25),
        (0.065, 0.305, VIX_SOFT, VIX),
        (0.515, 0.305, VIX_SOFT, VIX),
    ]
    for metric, (x_pos, y_pos, fill, accent) in zip(
        metrics, card_specs, strict=True
    ):
        rounded_box(
            ax,
            x_pos,
            y_pos,
            0.42,
            0.205,
            facecolor=fill,
            edgecolor=RULE,
            linewidth=0.8,
        )
        ax.text(
            x_pos + 0.028,
            y_pos + 0.162,
            metric["label"],
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=13,
            color=MUTED,
        )
        ax.text(
            x_pos + 0.028,
            y_pos + 0.067,
            metric["display"],
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=33,
            fontweight="bold",
            color=INK,
        )
        track_x = x_pos + 0.205
        track_width = 0.18
        ax.add_patch(
            FancyBboxPatch(
                (track_x, y_pos + 0.066),
                track_width,
                0.022,
                boxstyle="round,pad=0,rounding_size=0.008",
                transform=ax.transAxes,
                facecolor=WHITE,
                edgecolor="none",
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (track_x, y_pos + 0.066),
                track_width * (float(metric["raw"]) / scale),
                0.022,
                boxstyle="round,pad=0,rounding_size=0.008",
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )

    text_block = content["text"]
    rounded_box(
        ax,
        0.065,
        0.105,
        0.87,
        0.145,
        facecolor=INK,
        edgecolor="none",
    )
    ax.text(
        0.09,
        0.215,
        text_block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=13.5,
        fontweight="bold",
        color=WHITE,
    )
    ax.text(
        0.09,
        0.174,
        text_block["body"][0],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=11.5,
        color=WHITE,
    )
    ax.text(
        0.09,
        0.134,
        text_block["body"][1],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=11.5,
        color=WHITE,
    )

    add_footer(ax, content["source_labels"])
    fig.savefig(destination, dpi=DPI, facecolor=WHITE)
    plt.close(fig)


def render_takeaway(content: dict[str, Any], destination: Path) -> None:
    fig, ax = canvas()
    add_header(ax, content["title"], content["alt"], GOLD)

    hero_metric = content["metrics"][0]
    rounded_box(
        ax,
        0.065,
        0.355,
        0.405,
        0.395,
        facecolor=PM25_SOFT,
        edgecolor=RULE,
        linewidth=0.8,
    )
    ax.text(
        0.095,
        0.695,
        hero_metric["label"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=14,
        color=MUTED,
    )
    ax.add_patch(
        Circle(
            (0.267, 0.535),
            0.105,
            transform=ax.transAxes,
            facecolor=WHITE,
            edgecolor=PM25,
            linewidth=8,
        )
    )
    ax.add_patch(
        Circle(
            (0.267, 0.535),
            0.125,
            transform=ax.transAxes,
            facecolor="none",
            edgecolor=GOLD,
            linewidth=1.5,
        )
    )
    ax.text(
        0.267,
        0.535,
        hero_metric["display"],
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=41,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.267,
        0.395,
        "同期事件對照",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=11.5,
        color=MUTED,
    )

    rounded_box(
        ax,
        0.5,
        0.355,
        0.435,
        0.395,
        facecolor=SOFT,
        edgecolor=RULE,
        linewidth=0.8,
    )
    comparison_metrics = content["metrics"][1:]
    comparison_values = [float(metric["raw"]) for metric in comparison_metrics]
    comparison_scale = max(comparison_values)
    if comparison_scale <= 0:
        raise ValueError("事件比較的 bar scale 必須大於零")

    comparison_y = [0.61, 0.455]
    comparison_colors = [PM25, VIX]
    for metric, y_pos, color in zip(
        comparison_metrics, comparison_y, comparison_colors, strict=True
    ):
        ax.text(
            0.535,
            y_pos + 0.078,
            metric["label"],
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=12.5,
            color=MUTED,
        )
        ax.text(
            0.535,
            y_pos + 0.02,
            metric["display"],
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=29,
            fontweight="bold",
            color=INK,
        )
        ax.add_patch(
            FancyBboxPatch(
                (0.675, y_pos + 0.008),
                0.215,
                0.026,
                boxstyle="round,pad=0,rounding_size=0.008",
                transform=ax.transAxes,
                facecolor=WHITE,
                edgecolor="none",
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (0.675, y_pos + 0.008),
                0.215 * (float(metric["raw"]) / comparison_scale),
                0.026,
                boxstyle="round,pad=0,rounding_size=0.008",
                transform=ax.transAxes,
                facecolor=color,
                edgecolor="none",
            )
        )

    text_block = content["text"]
    rounded_box(
        ax,
        0.065,
        0.105,
        0.87,
        0.195,
        facecolor=INK,
        edgecolor="none",
    )
    ax.text(
        0.092,
        0.265,
        text_block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=14,
        fontweight="bold",
        color=GOLD,
    )
    ax.text(
        0.092,
        0.218,
        wrapped(text_block["body"][0], 64),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=11.6,
        color=WHITE,
        linespacing=1.35,
    )
    ax.text(
        0.092,
        0.158,
        wrapped(text_block["body"][1], 64),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=11.6,
        color=WHITE,
        linespacing=1.35,
    )

    add_footer(ax, content["source_labels"])
    fig.savefig(destination, dpi=DPI, facecolor=WHITE)
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)

    # These files are part of the fixed evidence package. A missing or empty file
    # must fail loudly even though the visible strings and statistics come from
    # strict plan and results.json.
    require_text_file(README_PATH)
    require_text_file(ARTICLE_PATH)
    verify_results_digest(plan)

    evidence = {"k1801": results}
    question = panel_content(
        find_panel(plan, "panel_question"),
        evidence,
        plan,
        expected_metric_count=2,
    )
    result = panel_content(
        find_panel(plan, "panel_result"),
        evidence,
        plan,
        expected_metric_count=4,
    )
    takeaway = panel_content(
        find_panel(plan, "panel_takeaway"),
        evidence,
        plan,
        expected_metric_count=3,
    )

    os.makedirs(out_dir, exist_ok=True)
    render_question(question, Path(out_dir) / "panel_question.png")
    render_result(result, Path(out_dir) / "panel_result.png")
    render_takeaway(takeaway, Path(out_dir) / "panel_takeaway.png")


if __name__ == "__main__":
    main()
