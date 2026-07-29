#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_6c6fa752 lazy pack."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6c6fa752/runs/lazypack-mile_6c6fa752/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1630/k1630_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6c6fa752/runs/lazypack-mile_6c6fa752/panels/"
    "mile_6c6fa752_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6c6fa752/runs/lazypack-mile_6c6fa752/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#12233F"
NAVY_2 = "#1D365E"
BLUE = "#2F6BFF"
BLUE_SOFT = "#EAF0FF"
TEAL = "#008D84"
TEAL_SOFT = "#E4F5F2"
AMBER = "#C87912"
AMBER_SOFT = "#FFF2DE"
RED = "#B94343"
RED_SOFT = "#FBEAEA"
INK = "#17243A"
MUTED = "#536176"
LINE = "#DDE4ED"
PAPER = "#F5F7FA"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{where} 必須是 object，實際為 {type(value).__name__}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    plan = require_dict(load_json(PLAN_PATH), str(PLAN_PATH))
    results = require_dict(load_json(RESULTS_PATH), str(RESULTS_PATH))

    # The article is part of the evidence package. Reading it here makes a
    # missing or empty package member fail loudly, while all plotted numbers
    # remain bound exclusively to results.json.
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"文章 evidence 是空的：{ARTICLE_PATH}")

    result_evidence = require_dict(
        require_dict(plan["evidence"], "plan.evidence")["results"],
        "plan.evidence.results",
    )
    expected_hash = result_evidence["sha256"]
    if not isinstance(expected_hash, str) or not expected_hash:
        raise TypeError("plan.evidence.results.sha256 必須是非空字串")
    actual_hash = sha256_file(RESULTS_PATH)
    if actual_hash != expected_hash:
        raise ValueError(
            "results.json 與 strict plan 的 SHA-256 不一致："
            f"expected={expected_hash}, actual={actual_hash}"
        )
    source_label = result_evidence["label"]
    if not isinstance(source_label, str) or not source_label:
        raise TypeError("plan.evidence.results.label 必須是非空字串")

    panels = plan["panels"]
    if not isinstance(panels, list):
        raise TypeError("plan.panels 必須是 array")
    expected_names = {"panel_question", "panel_result", "panel_takeaway"}
    actual_names = {
        require_dict(panel, "plan.panels[]")["name"] for panel in panels
    }
    if actual_names != expected_names:
        raise ValueError(
            f"panel 名稱不符：expected={sorted(expected_names)}, "
            f"actual={sorted(actual_names)}"
        )
    return plan, results


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"只接受絕對 JSON Pointer：{pointer!r}")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"results.json 缺少欄位：{pointer}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"results.json 缺少欄位：{pointer}") from exc
        else:
            raise KeyError(f"results.json 缺少欄位：{pointer}")
    return current


def format_metric(value_spec: dict[str, Any], results: dict[str, Any]) -> str:
    if value_spec["source"] != "results":
        raise ValueError(f"不支援的 evidence source：{value_spec['source']!r}")
    pointer = value_spec["path"]
    value = resolve_json_pointer(results, pointer)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{pointer} 必須是數值，實際為 {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{pointer} 必須是有限數值")

    fmt = require_dict(value_spec["format"], f"{pointer}.format")
    if fmt["kind"] != "number":
        raise ValueError(f"{pointer} 使用未支援的格式：{fmt['kind']!r}")
    digits = fmt["digits"]
    if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
        raise TypeError(f"{pointer} 的 digits 必須是非負整數")
    return f"{number:.{digits}f}"


def display_units(text: str) -> float:
    return sum(0.55 if ord(char) < 128 else 1.0 for char in text)


def wrap_units(text: str, max_units: float) -> str:
    """Wrap Traditional Chinese and mixed Latin text without relying on spaces."""
    if max_units <= 0:
        raise ValueError("max_units 必須大於零")
    lines: list[str] = []
    current: list[str] = []
    used = 0.0
    last_break = -1
    break_chars = set("，。；：、！？）】 」")

    for char in text.strip():
        char_units = 0.55 if ord(char) < 128 else 1.0
        if current and used + char_units > max_units:
            if last_break >= 0:
                split_at = last_break + 1
                lines.append("".join(current[:split_at]).strip())
                current = current[split_at:]
            else:
                lines.append("".join(current).strip())
                current = []
            used = display_units("".join(current))
            last_break = max(
                (index for index, item in enumerate(current) if item in break_chars),
                default=-1,
            )
        current.append(char)
        used += char_units
        if char in break_chars:
            last_break = len(current) - 1

    if current:
        lines.append("".join(current).strip())
    return "\n".join(line for line in lines if line)


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        require_dict(panel, "plan.panels[]")
        for panel in plan["panels"]
        if require_dict(panel, "plan.panels[]")["name"] == name
    ]
    if len(matches) != 1:
        raise ValueError(f"plan 必須恰好包含一個 {name}")
    panel = matches[0]
    for required in ("title", "alt", "sources", "blocks"):
        if required not in panel:
            raise KeyError(f"panel {name} 缺少欄位：{required}")
    if panel["sources"] != ["results"]:
        raise ValueError(f"panel {name} 的 sources 必須是 ['results']")
    return panel


def metric_blocks(
    panel: dict[str, Any], results: dict[str, Any]
) -> list[tuple[str, str]]:
    metrics: list[tuple[str, str]] = []
    for block in panel["blocks"]:
        block = require_dict(block, f"{panel['name']}.blocks[]")
        if block["kind"] == "metric":
            label = block["label"]
            if not isinstance(label, str) or not label:
                raise TypeError(f"{panel['name']} 的 metric label 必須是非空字串")
            value_spec = require_dict(block["value"], f"{panel['name']}.metric.value")
            metrics.append((label, format_metric(value_spec, results)))
    return metrics


def text_block(panel: dict[str, Any]) -> dict[str, Any]:
    matches = [
        require_dict(block, f"{panel['name']}.blocks[]")
        for block in panel["blocks"]
        if require_dict(block, f"{panel['name']}.blocks[]")["kind"] == "text"
    ]
    if len(matches) != 1:
        raise ValueError(f"{panel['name']} 必須恰好有一個 text block")
    block = matches[0]
    if not isinstance(block["heading"], str) or not block["heading"]:
        raise TypeError(f"{panel['name']} 的 text heading 必須是非空字串")
    if (
        not isinstance(block["body"], list)
        or not block["body"]
        or any(not isinstance(line, str) or not line for line in block["body"])
    ):
        raise TypeError(f"{panel['name']} 的 text body 必須是非空字串陣列")
    return block


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    figure = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    axes = figure.add_axes([0, 0, 1, 1])
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)
    axes.axis("off")
    axes.add_patch(Rectangle((0, 0), 1, 1, facecolor=WHITE, edgecolor="none"))
    return figure, axes


def rounded_box(
    axes: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    edgecolor: str = LINE,
    linewidth: float = 1.0,
) -> None:
    axes.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.008,rounding_size=0.014",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def draw_header(axes: plt.Axes, panel: dict[str, Any], accent: str) -> None:
    axes.add_patch(Rectangle((0, 0.82), 1, 0.18, facecolor=NAVY, edgecolor="none"))
    axes.add_patch(Rectangle((0.050, 0.850), 0.007, 0.105, facecolor=accent))
    axes.text(
        0.073,
        0.965,
        "VolPred 研究圖卡",
        color="#BFCBE0",
        fontsize=11.5,
        ha="left",
        va="top",
    )
    axes.text(
        0.073,
        0.875,
        panel["title"],
        color=WHITE,
        fontsize=27,
        fontweight="bold",
        ha="left",
        va="center",
    )


def draw_source(
    axes: plt.Axes, plan: dict[str, Any], panel: dict[str, Any]
) -> None:
    evidence = require_dict(plan["evidence"], "plan.evidence")
    labels: list[str] = []
    for source_id in panel["sources"]:
        source = require_dict(evidence[source_id], f"plan.evidence.{source_id}")
        label = source["label"]
        if not isinstance(label, str) or not label:
            raise TypeError(f"plan.evidence.{source_id}.label 必須是非空字串")
        labels.append(label)
    source_text = "資料來源：" + "；".join(labels)

    axes.add_patch(Rectangle((0, 0), 1, 0.095, facecolor=PAPER, edgecolor="none"))
    axes.plot([0.050, 0.950], [0.095, 0.095], color=LINE, linewidth=1.0)
    axes.text(
        0.050,
        0.052,
        wrap_units(source_text, 65),
        color=MUTED,
        fontsize=9.5,
        ha="left",
        va="center",
        linespacing=1.28,
    )


def draw_text_card(
    axes: plt.Axes,
    block: dict[str, Any],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    accent: str,
    soft: str,
    wrap_at: float,
    body_size: float = 18,
) -> None:
    rounded_box(axes, x, y, width, height, WHITE)
    axes.add_patch(Rectangle((x, y), 0.010, height, facecolor=accent, edgecolor="none"))
    axes.text(
        x + 0.035,
        y + height - 0.050,
        block["heading"],
        color=INK,
        fontsize=22,
        fontweight="bold",
        ha="left",
        va="top",
    )

    cursor_y = y + height - 0.112
    for sentence in block["body"]:
        wrapped = wrap_units(sentence, wrap_at)
        line_count = wrapped.count("\n") + 1
        axes.text(
            x + 0.050,
            cursor_y,
            "●",
            color=accent,
            fontsize=9,
            ha="center",
            va="top",
        )
        axes.text(
            x + 0.068,
            cursor_y,
            wrapped,
            color=INK,
            fontsize=body_size,
            ha="left",
            va="top",
            linespacing=1.34,
        )
        cursor_y -= 0.050 * line_count + 0.026

    axes.add_patch(
        FancyBboxPatch(
            (x + width - 0.115, y + height - 0.070),
            0.070,
            0.026,
            boxstyle="round,pad=0.008,rounding_size=0.010",
            facecolor=soft,
            edgecolor="none",
        )
    )


def draw_metric_card(
    axes: plt.Axes,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    accent: str,
    soft: str,
    label_wrap: float,
    value_size: float,
    label_size: float = 13.0,
) -> None:
    rounded_box(axes, x, y, width, height, WHITE)
    axes.add_patch(
        Rectangle(
            (x, y + height - 0.018),
            width,
            0.018,
            facecolor=accent,
            edgecolor="none",
        )
    )
    axes.add_patch(
        FancyBboxPatch(
            (x + 0.028, y + height - 0.071),
            0.042,
            0.027,
            boxstyle="round,pad=0.006,rounding_size=0.010",
            facecolor=soft,
            edgecolor="none",
        )
    )
    axes.text(
        x + 0.030,
        y + height - 0.072,
        wrap_units(label, label_wrap),
        color=MUTED,
        fontsize=label_size,
        ha="left",
        va="top",
        linespacing=1.18,
    )
    axes.text(
        x + 0.030,
        y + 0.025,
        value,
        color=accent,
        fontsize=value_size,
        fontweight="bold",
        ha="left",
        va="bottom",
    )


def render_question(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    metrics = metric_blocks(panel, results)
    if len(metrics) != 2:
        raise ValueError("panel_question 必須恰好有兩個 metric blocks")
    block = text_block(panel)

    figure, axes = new_canvas()
    draw_header(axes, panel, BLUE)
    draw_text_card(
        axes,
        block,
        x=0.050,
        y=0.575,
        width=0.900,
        height=0.215,
        accent=BLUE,
        soft=BLUE_SOFT,
        wrap_at=35,
        body_size=17,
    )
    positions = [(0.050, 0.205), (0.515, 0.205)]
    accents = [(BLUE, BLUE_SOFT), (TEAL, TEAL_SOFT)]
    for (label, value), (x, y), (accent, soft) in zip(
        metrics, positions, accents, strict=True
    ):
        draw_metric_card(
            axes,
            x=x,
            y=y,
            width=0.435,
            height=0.285,
            label=label,
            value=value,
            accent=accent,
            soft=soft,
            label_wrap=21,
            value_size=43,
            label_size=13.5,
        )
    draw_source(axes, plan, panel)
    save_panel(figure, panel)


def render_result(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    metrics = metric_blocks(panel, results)
    if len(metrics) != 4:
        raise ValueError("panel_result 必須恰好有四個 metric blocks")
    block = text_block(panel)

    figure, axes = new_canvas()
    draw_header(axes, panel, TEAL)
    draw_text_card(
        axes,
        block,
        x=0.050,
        y=0.575,
        width=0.900,
        height=0.215,
        accent=TEAL,
        soft=TEAL_SOFT,
        wrap_at=38,
        body_size=15.5,
    )
    positions = [
        (0.050, 0.365),
        (0.515, 0.365),
        (0.050, 0.130),
        (0.515, 0.130),
    ]
    accents = [
        (TEAL, TEAL_SOFT),
        (TEAL, TEAL_SOFT),
        (NAVY_2, BLUE_SOFT),
        (NAVY_2, BLUE_SOFT),
    ]
    for (label, value), (x, y), (accent, soft) in zip(
        metrics, positions, accents, strict=True
    ):
        draw_metric_card(
            axes,
            x=x,
            y=y,
            width=0.435,
            height=0.195,
            label=label,
            value=value,
            accent=accent,
            soft=soft,
            label_wrap=25,
            value_size=24,
            label_size=11.0,
        )
    draw_source(axes, plan, panel)
    save_panel(figure, panel)


def render_takeaway(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    metrics = metric_blocks(panel, results)
    if len(metrics) != 3:
        raise ValueError("panel_takeaway 必須恰好有三個 metric blocks")
    block = text_block(panel)

    figure, axes = new_canvas()
    draw_header(axes, panel, AMBER)
    # Keep the label and value in distinct vertical rows.  The first label
    # wraps to two lines; extending the cards downward preserves its top
    # position while moving the value baseline safely below the label.
    positions = [(0.050, 0.590), (0.365, 0.590), (0.680, 0.590)]
    accents = [
        (AMBER, AMBER_SOFT),
        (RED, RED_SOFT),
        (NAVY_2, BLUE_SOFT),
    ]
    for (label, value), (x, y), (accent, soft) in zip(
        metrics, positions, accents, strict=True
    ):
        draw_metric_card(
            axes,
            x=x,
            y=y,
            width=0.270,
            height=0.200,
            label=label,
            value=value,
            accent=accent,
            soft=soft,
            label_wrap=18,
            value_size=20,
            label_size=9.0,
        )
    draw_text_card(
        axes,
        block,
        x=0.050,
        y=0.125,
        width=0.900,
        height=0.435,
        accent=AMBER,
        soft=AMBER_SOFT,
        wrap_at=38,
        body_size=15.5,
    )
    draw_source(axes, plan, panel)
    save_panel(figure, panel)


def save_panel(figure: plt.Figure, panel: dict[str, Any]) -> None:
    destination = Path(out_dir) / f"{panel['name']}.png"
    figure.savefig(
        destination,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(figure)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    plan, results = load_evidence()
    render_question(plan, results, panel_by_name(plan, "panel_question"))
    render_result(plan, results, panel_by_name(plan, "panel_result"))
    render_takeaway(plan, results, panel_by_name(plan, "panel_takeaway"))


if __name__ == "__main__":
    main()
