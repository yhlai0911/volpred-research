#!/usr/bin/env python3
"""Render the three data-bound K1365 general-reader lazypack panels."""

from __future__ import annotations

import hashlib
import json
import os
import re
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1365/k1365_results.json"
)
CERTIFIED_RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1365/K1365_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1365/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_bb33fd72/"
    "runs/lazypack-mile_bb33fd72/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_bb33fd72/"
    "runs/lazypack-mile_bb33fd72/panels/mile_bb33fd72_article.md"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_bb33fd72/"
    "runs/lazypack-mile_bb33fd72/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#102A43"
INK = "#17324D"
MUTED = "#5D6B78"
FAINT = "#8A98A6"
PAPER = "#FFFFFF"
MIST = "#F4F7FA"
LINE = "#DCE5EC"
TEAL = "#167D82"
TEAL_SOFT = "#E4F3F2"
BLUE = "#2C63A5"
BLUE_SOFT = "#E8F0F8"
AMBER = "#B97818"
AMBER_SOFT = "#FBF1DD"
RED = "#B94848"
RED_SOFT = "#F8E8E7"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["savefig.facecolor"] = PAPER


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing result field: {dotted_path}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing result field: {dotted_path}") from exc
        else:
            raise KeyError(f"Missing result field: {dotted_path}")
    return current


def require_number(value: Any, dotted_path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {dotted_path}")
    return float(value)


def format_bound_value(value: Any, fmt: dict[str, Any], dotted_path: str) -> str:
    number = require_number(value, dotted_path)
    kind = fmt["kind"]
    digits = int(fmt.get("digits", 0))
    suffix = str(fmt.get("suffix", ""))
    show_plus = bool(fmt.get("show_plus", False))

    if kind == "percent":
        return f"{number * 100:.{digits}f}%{suffix}"
    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected an integer-valued number at {dotted_path}")
        return f"{int(number)}{suffix}"
    if kind == "number":
        sign = "+" if show_plus else ""
        return f"{number:{sign}.{digits}f}{suffix}"
    raise ValueError(f"Unsupported value format at {dotted_path}: {kind}")


def load_evidence() -> tuple[dict[str, Any], dict[str, Any], str]:
    result = load_json(RESULT_PATH)
    certified_result = load_json(CERTIFIED_RESULT_PATH)
    plan = load_json(PLAN_PATH)
    load_text(README_PATH)
    load_text(ARTICLE_PATH)

    if not isinstance(result, dict) or not isinstance(certified_result, dict):
        raise TypeError("Both K1365 result files must contain JSON objects")
    if result != certified_result:
        raise ValueError("The two K1365 result files do not match")
    if not isinstance(plan, dict) or not isinstance(plan.get("panels"), list):
        raise TypeError("plan.json must contain a panels list")

    evidence_spec = resolve_path(plan, "evidence.result")
    expected_sha = evidence_spec["sha256"]
    actual_sha = file_sha256(CERTIFIED_RESULT_PATH)
    if expected_sha != actual_sha:
        raise ValueError("Certified result SHA-256 does not match plan.json")

    match = re.search(r"k\d+", RESULT_PATH.name, flags=re.IGNORECASE)
    if match is None:
        raise ValueError("Cannot determine the experiment number from the result filename")
    experiment_id = match.group(0).upper()
    return result, plan, experiment_id


def bind_panel(
    plan: dict[str, Any], result: dict[str, Any], name: str
) -> dict[str, Any]:
    matches = [panel for panel in plan["panels"] if panel.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name}")
    panel = matches[0]
    if panel.get("sources") != ["result"]:
        raise ValueError(f"Panel {name} must use only the result evidence source")

    bound_blocks: list[dict[str, Any]] = []
    for block in panel["blocks"]:
        bound = dict(block)
        if block["kind"] == "metric":
            value_spec = block["value"]
            if value_spec["source"] != "result":
                raise ValueError(f"Unsupported source in panel {name}")
            dotted_path = value_spec["path"]
            raw_value = resolve_path(result, dotted_path)
            bound["raw_value"] = raw_value
            bound["rendered_value"] = format_bound_value(
                raw_value, value_spec["format"], dotted_path
            )
        elif block["kind"] == "text":
            if not isinstance(block.get("body"), list) or not block["body"]:
                raise ValueError(f"Text block in panel {name} has no body")
        else:
            raise ValueError(f"Unsupported block kind in panel {name}")
        bound_blocks.append(bound)

    bound_panel = dict(panel)
    bound_panel["blocks"] = bound_blocks
    return bound_panel


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    figure = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=PAPER
    )
    axes = figure.add_axes((0, 0, 1, 1))
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)
    axes.axis("off")
    return figure, axes


def rounded_box(
    axes: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = PAPER,
    edgecolor: str = LINE,
    linewidth: float = 1.2,
    radius: float = 0.025,
    zorder: int = 1,
) -> None:
    axes.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            transform=axes.transAxes,
            zorder=zorder,
        )
    )


def wrap_zh(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def add_source(axes: plt.Axes, experiment_id: str) -> None:
    axes.plot((0.055, 0.945), (0.074, 0.074), color=LINE, linewidth=1.0)
    axes.text(
        0.055,
        0.041,
        f"資料來源：experiment {experiment_id}",
        transform=axes.transAxes,
        ha="left",
        va="center",
        fontsize=10.5,
        color=FAINT,
    )


def save_panel(
    figure: plt.Figure, panel: dict[str, Any], experiment_id: str
) -> None:
    output_path = OUT_DIR / f"{panel['name']}.png"
    figure.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
            "Source": f"experiment {experiment_id}",
        },
    )
    plt.close(figure)


def render_concentration(panel: dict[str, Any], experiment_id: str) -> None:
    if panel.get("style") != "bento-grid" or len(panel["blocks"]) != 4:
        raise ValueError("Panel 1 contract is invalid")

    figure, axes = new_canvas()
    axes.text(
        0.055,
        0.925,
        panel["title"],
        ha="left",
        va="center",
        fontsize=31,
        fontweight="bold",
        color=NAVY,
    )
    axes.text(
        0.055,
        0.862,
        "同指數產品很多，短線成交卻高度集中在既有領先者。",
        ha="left",
        va="center",
        fontsize=14,
        color=MUTED,
    )

    positions = [
        (0.055, 0.515),
        (0.515, 0.515),
        (0.055, 0.175),
        (0.515, 0.175),
    ]
    accents = [BLUE, TEAL, AMBER, RED]
    soft_colors = [BLUE_SOFT, TEAL_SOFT, AMBER_SOFT, RED_SOFT]

    for block, (x, y), accent, soft in zip(
        panel["blocks"], positions, accents, soft_colors, strict=True
    ):
        if block["kind"] != "metric":
            raise ValueError("Panel 1 accepts metric blocks only")
        rounded_box(axes, x, y, 0.43, 0.27, facecolor=PAPER)
        axes.add_patch(
            Circle(
                (x + 0.065, y + 0.197),
                0.028,
                transform=axes.transAxes,
                facecolor=soft,
                edgecolor="none",
            )
        )
        axes.add_patch(
            Circle(
                (x + 0.065, y + 0.197),
                0.012,
                transform=axes.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )
        axes.text(
            x + 0.11,
            y + 0.205,
            block["label"],
            ha="left",
            va="center",
            fontsize=17,
            fontweight="bold",
            color=INK,
        )
        axes.text(
            x + 0.035,
            y + 0.105,
            block["rendered_value"],
            ha="left",
            va="center",
            fontsize=42,
            fontweight="bold",
            color=accent,
        )
        share = require_number(block["raw_value"], block["value"]["path"])
        if not 0 <= share <= 1:
            raise ValueError(f"Share outside [0, 1]: {block['value']['path']}")
        bar_x, bar_y, bar_width = x + 0.245, y + 0.092, 0.145
        axes.add_patch(
            FancyBboxPatch(
                (bar_x, bar_y),
                bar_width,
                0.025,
                boxstyle="round,pad=0,rounding_size=0.012",
                transform=axes.transAxes,
                facecolor=MIST,
                edgecolor="none",
            )
        )
        axes.add_patch(
            FancyBboxPatch(
                (bar_x, bar_y),
                bar_width * share,
                0.025,
                boxstyle="round,pad=0,rounding_size=0.012",
                transform=axes.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )

    add_source(axes, experiment_id)
    save_panel(figure, panel, experiment_id)


def render_prediction(panel: dict[str, Any], experiment_id: str) -> None:
    if panel.get("style") != "professional" or len(panel["blocks"]) != 4:
        raise ValueError("Panel 2 contract is invalid")

    figure, axes = new_canvas()
    axes.add_patch(
        Rectangle(
            (0, 0.735),
            1,
            0.265,
            transform=axes.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    axes.text(
        0.055,
        0.902,
        panel["title"],
        ha="left",
        va="center",
        fontsize=30,
        fontweight="bold",
        color=PAPER,
    )
    axes.text(
        0.055,
        0.817,
        "老牌 ETF 的熱門度，沒有成為穩定的正向風險警報。",
        ha="left",
        va="center",
        fontsize=14,
        color="#C8D6E3",
    )

    positions = [
        (0.055, 0.425),
        (0.515, 0.425),
        (0.055, 0.135),
        (0.515, 0.135),
    ]
    accents = [BLUE, TEAL, RED, AMBER]
    soft_colors = [BLUE_SOFT, TEAL_SOFT, RED_SOFT, AMBER_SOFT]

    for block, (x, y), accent, soft in zip(
        panel["blocks"], positions, accents, soft_colors, strict=True
    ):
        if block["kind"] != "metric":
            raise ValueError("Panel 2 accepts metric blocks only")
        rounded_box(axes, x, y, 0.43, 0.235, facecolor=PAPER)
        axes.add_patch(
            Rectangle(
                (x + 0.025, y + 0.19),
                0.055,
                0.008,
                transform=axes.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )
        axes.text(
            x + 0.025,
            y + 0.157,
            block["label"],
            ha="left",
            va="center",
            fontsize=16,
            fontweight="bold",
            color=INK,
        )
        axes.text(
            x + 0.025,
            y + 0.079,
            block["rendered_value"],
            ha="left",
            va="center",
            fontsize=39,
            fontweight="bold",
            color=accent,
        )
        note = block.get("note")
        if note:
            axes.text(
                x + 0.205,
                y + 0.075,
                wrap_zh(note, 12),
                ha="left",
                va="center",
                fontsize=12.5,
                color=MUTED,
                linespacing=1.35,
            )
        axes.add_patch(
            Circle(
                (x + 0.385, y + 0.188),
                0.018,
                transform=axes.transAxes,
                facecolor=soft,
                edgecolor="none",
            )
        )

    add_source(axes, experiment_id)
    save_panel(figure, panel, experiment_id)


def render_boundary(panel: dict[str, Any], experiment_id: str) -> None:
    if panel.get("style") != "editorial" or len(panel["blocks"]) != 4:
        raise ValueError("Panel 3 contract is invalid")
    text_blocks = [block for block in panel["blocks"] if block["kind"] == "text"]
    metric_blocks = [block for block in panel["blocks"] if block["kind"] == "metric"]
    if len(text_blocks) != 3 or len(metric_blocks) != 1:
        raise ValueError("Panel 3 requires three text blocks and one metric block")

    figure, axes = new_canvas()
    axes.text(
        0.055,
        0.925,
        panel["title"],
        ha="left",
        va="center",
        fontsize=30,
        fontweight="bold",
        color=NAVY,
    )
    axes.text(
        0.055,
        0.858,
        "這項研究最適合描述交易往哪裡聚集，不適合直接當買賣訊號。",
        ha="left",
        va="center",
        fontsize=14,
        color=MUTED,
    )

    metric = metric_blocks[0]
    rounded_box(
        axes,
        0.055,
        0.17,
        0.31,
        0.59,
        facecolor=NAVY,
        edgecolor=NAVY,
        radius=0.03,
    )
    axes.text(
        0.085,
        0.694,
        metric["label"],
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color="#C8D6E3",
    )
    axes.text(
        0.085,
        0.555,
        metric["rendered_value"],
        ha="left",
        va="center",
        fontsize=49,
        fontweight="bold",
        color=PAPER,
    )
    axes.plot(
        (0.085, 0.335),
        (0.452, 0.452),
        color="#49637A",
        linewidth=2.0,
        solid_capstyle="round",
    )
    axes.add_patch(
        Circle(
            (0.107, 0.452),
            0.016,
            transform=axes.transAxes,
            facecolor=TEAL,
            edgecolor=PAPER,
            linewidth=1.5,
        )
    )
    axes.add_patch(
        Circle(
            (0.313, 0.452),
            0.016,
            transform=axes.transAxes,
            facecolor=AMBER,
            edgecolor=PAPER,
            linewidth=1.5,
        )
    )
    axes.text(
        0.085,
        0.365,
        "先建立近期常態",
        ha="left",
        va="center",
        fontsize=13,
        color="#DCE6EE",
    )
    axes.text(
        0.085,
        0.285,
        "再延後使用訊號",
        ha="left",
        va="center",
        fontsize=13,
        color="#DCE6EE",
    )

    block_positions = [0.585, 0.365, 0.145]
    block_colors = [TEAL, AMBER, RED]
    block_soft = [TEAL_SOFT, AMBER_SOFT, RED_SOFT]
    for block, y, accent, soft in zip(
        text_blocks, block_positions, block_colors, block_soft, strict=True
    ):
        rounded_box(axes, 0.415, y, 0.53, 0.175, facecolor=PAPER)
        axes.add_patch(
            Circle(
                (0.455, y + 0.128),
                0.019,
                transform=axes.transAxes,
                facecolor=soft,
                edgecolor="none",
            )
        )
        axes.add_patch(
            Circle(
                (0.455, y + 0.128),
                0.008,
                transform=axes.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )
        axes.text(
            0.487,
            y + 0.13,
            block["heading"],
            ha="left",
            va="center",
            fontsize=16,
            fontweight="bold",
            color=INK,
        )
        body = "".join(str(part) for part in block["body"])
        axes.text(
            0.45,
            y + 0.055,
            wrap_zh(body, 29),
            ha="left",
            va="center",
            fontsize=12.2,
            color=MUTED,
            linespacing=1.35,
        )

    add_source(axes, experiment_id)
    save_panel(figure, panel, experiment_id)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    result, plan, experiment_id = load_evidence()
    panel_1 = bind_panel(plan, result, "1_concentration_facts")
    panel_2 = bind_panel(plan, result, "2_prediction_result")
    panel_3 = bind_panel(plan, result, "3_honest_boundary")

    render_concentration(panel_1, experiment_id)
    render_prediction(panel_2, experiment_id)
    render_boundary(panel_3, experiment_id)


if __name__ == "__main__":
    main()
