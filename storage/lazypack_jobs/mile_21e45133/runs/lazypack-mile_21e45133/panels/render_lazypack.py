#!/usr/bin/env python3
"""Render the four data-bound lazypack panels for mile_21e45133.

All displayed prose and metric specifications come from the strict plan.  All
displayed metric values are resolved from the evidence JSON at render time.
Missing fields deliberately raise instead of producing partial graphics.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_21e45133/runs/lazypack-mile_21e45133/plan.json"
)
EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/article_assets/"
    "jpy_carry_move_transmission/evidence.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_21e45133/runs/lazypack-mile_21e45133/panels/"
    "mile_21e45133_article.md"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_21e45133/runs/lazypack-mile_21e45133/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#12263A"
INK = "#182536"
MUTED = "#5D6B7A"
FAINT = "#8793A1"
LINE = "#D9E1E8"
PAPER = "#FFFFFF"
SOFT = "#F4F7FA"
BLUE = "#1F5A8A"
BLUE_SOFT = "#E8F1F8"
TEAL = "#147D76"
TEAL_SOFT = "#E5F3F1"
RED = "#B0443C"
RED_SOFT = "#F8ECEA"
AMBER = "#9B681D"
AMBER_SOFT = "#F8F0E3"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    plan = load_json(PLAN_PATH)
    evidence = load_json(EVIDENCE_PATH)
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article is empty: {ARTICLE_PATH}")
    if plan.get("schema_version") != 1:
        raise ValueError("Expected strict lazypack plan schema_version=1")
    if "move" not in plan["evidence"]:
        raise KeyError("plan.evidence.move")
    if not plan["evidence"]["move"].get("label"):
        raise KeyError("plan.evidence.move.label")
    return plan, evidence


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


def numeric(value: Any, dotted_path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {dotted_path}, got {type(value).__name__}")
    return float(value)


def format_bound_value(evidence: dict[str, Any], spec: dict[str, Any]) -> str:
    if spec["source"] != "move":
        raise KeyError(f"Unknown evidence source: {spec['source']}")
    dotted_path = spec["path"]
    value = resolve_path(evidence, dotted_path)
    fmt = spec["format"]
    kind = fmt["kind"]
    suffix = fmt.get("suffix", "")

    if kind == "integer":
        number = numeric(value, dotted_path)
        if not number.is_integer():
            raise ValueError(f"Expected integer-valued number at {dotted_path}")
        return f"{int(number):,}{suffix}"
    if kind == "number":
        number = numeric(value, dotted_path)
        digits = int(fmt["digits"])
        sign = "+" if fmt.get("show_plus", False) else ""
        return f"{number:{sign}.{digits}f}{suffix}"
    if kind == "date":
        if not isinstance(value, str) or not value:
            raise TypeError(f"Expected date string at {dotted_path}")
        return value
    raise ValueError(f"Unsupported format kind: {kind}")


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [panel for panel in plan["panels"] if panel.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name}")
    return matches[0]


def text_block(panel: dict[str, Any]) -> dict[str, Any]:
    matches = [block for block in panel["blocks"] if block.get("kind") == "text"]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one text block in {panel['name']}")
    block = matches[0]
    if not block.get("heading") or not block.get("body"):
        raise KeyError(f"Incomplete text block in {panel['name']}")
    return block


def metric_blocks(
    panel: dict[str, Any], evidence: dict[str, Any]
) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for block in panel["blocks"]:
        if block.get("kind") != "metric":
            continue
        if "label" not in block or "value" not in block:
            raise KeyError(f"Incomplete metric block in {panel['name']}")
        rendered.append(
            {
                "label": block["label"],
                "rendered": format_bound_value(evidence, block["value"]),
                "note": block.get("note"),
                "path": block["value"]["path"],
            }
        )
    if not rendered:
        raise ValueError(f"No metric blocks in {panel['name']}")
    return rendered


def wrap(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def new_canvas() -> tuple[Any, Any]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=PAPER,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_rect(
    ax: Any,
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
            boxstyle=f"round,pad=0.006,rounding_size={radius}",
            linewidth=linewidth,
            edgecolor=edgecolor,
            facecolor=facecolor,
            transform=ax.transAxes,
        )
    )


def draw_header(ax: Any, title: str, kicker: str) -> None:
    ax.add_patch(
        plt.Rectangle((0, 0.84), 1, 0.16, transform=ax.transAxes, color=NAVY)
    )
    ax.text(
        0.065,
        0.975,
        kicker,
        transform=ax.transAxes,
        ha="left",
        va="top",
        color="#BFD5E6",
        fontsize=12,
        fontweight="normal",
    )
    ax.text(
        0.065,
        0.892,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=PAPER,
        fontsize=28,
        fontweight="bold",
    )


def source_line(plan: dict[str, Any], panel: dict[str, Any]) -> str:
    labels: list[str] = []
    for source in panel["sources"]:
        label = plan["evidence"][source]["label"]
        if not isinstance(label, str) or not label:
            raise KeyError(f"plan.evidence.{source}.label")
        labels.append(label)
    return "資料來源：" + "、".join(labels)


def draw_footer(ax: Any, plan: dict[str, Any], panel: dict[str, Any]) -> None:
    ax.plot([0.065, 0.935], [0.075, 0.075], color=LINE, linewidth=1.0)
    ax.text(
        0.065,
        0.043,
        source_line(plan, panel),
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=13,
    )


def save_panel(fig: Any, panel: dict[str, Any]) -> None:
    destination = OUT_DIR / f"{panel['name']}.png"
    fig.savefig(
        destination,
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def render_concept(
    plan: dict[str, Any], evidence: dict[str, Any], panel: dict[str, Any]
) -> None:
    if panel["style"] != "professional":
        raise ValueError("1_concept must use professional style")
    block = text_block(panel)
    metrics = metric_blocks(panel, evidence)
    if len(block["body"]) != 3 or len(metrics) != 2:
        raise ValueError("1_concept contract changed")

    fig, ax = new_canvas()
    draw_header(ax, panel["title"], "從一條直覺合理的市場說法開始")
    ax.text(
        0.065,
        0.790,
        block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=21,
        fontweight="bold",
    )

    card_x = [0.065, 0.365, 0.665]
    card_titles = ["風險預算受壓", "平倉買回日圓", "鏈條必須完整"]
    card_colors = [BLUE_SOFT, TEAL_SOFT, AMBER_SOFT]
    title_colors = [BLUE, TEAL, AMBER]
    for index, (x, body) in enumerate(zip(card_x, block["body"])):
        rounded_rect(
            ax,
            x,
            0.485,
            0.270,
            0.250,
            facecolor=card_colors[index],
        )
        ax.text(
            x + 0.022,
            0.692,
            card_titles[index],
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=title_colors[index],
            fontsize=18,
            fontweight="bold",
        )
        ax.text(
            x + 0.022,
            0.642,
            wrap(body, 11),
            transform=ax.transAxes,
            ha="left",
            va="top",
            color=INK,
            fontsize=14,
            linespacing=1.28,
        )

    for x in (0.344, 0.644):
        ax.annotate(
            "",
            xy=(x + 0.015, 0.610),
            xytext=(x - 0.015, 0.610),
            xycoords=ax.transAxes,
            arrowprops={"arrowstyle": "-|>", "color": FAINT, "lw": 1.8},
        )

    metric_x = [0.065, 0.515]
    for index, metric in enumerate(metrics):
        x = metric_x[index]
        rounded_rect(
            ax,
            x,
            0.165,
            0.420,
            0.235,
            facecolor=PAPER,
            edgecolor=LINE,
            linewidth=1.2,
        )
        ax.text(
            x + 0.025,
            0.343,
            metric["label"],
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=MUTED,
            fontsize=17,
        )
        ax.text(
            x + 0.025,
            0.245,
            metric["rendered"],
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=NAVY,
            fontsize=39,
            fontweight="bold",
        )

    draw_footer(ax, plan, panel)
    save_panel(fig, panel)


def render_method(
    plan: dict[str, Any], evidence: dict[str, Any], panel: dict[str, Any]
) -> None:
    if panel["style"] != "scientific":
        raise ValueError("2_method must use scientific style")
    block = text_block(panel)
    metrics = metric_blocks(panel, evidence)
    if len(block["body"]) != 3 or len(metrics) != 3:
        raise ValueError("2_method contract changed")

    fig, ax = new_canvas()
    draw_header(ax, panel["title"], "資料、事件門檻與統計檢定")
    ax.text(
        0.065,
        0.790,
        block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=21,
        fontweight="bold",
    )

    positions = [0.065, 0.355, 0.645]
    widths = [0.260, 0.260, 0.290]
    for x, width, metric in zip(positions, widths, metrics):
        rounded_rect(
            ax,
            x,
            0.625,
            width,
            0.120,
            facecolor=SOFT,
            edgecolor=LINE,
            linewidth=1.0,
            radius=0.012,
        )
        ax.text(
            x + 0.018,
            0.718,
            metric["label"],
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=MUTED,
            fontsize=12,
        )
        ax.text(
            x + 0.018,
            0.663,
            metric["rendered"],
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=NAVY,
            fontsize=22,
            fontweight="bold",
        )

    ax.plot([0.105, 0.895], [0.585, 0.585], color=BLUE, linewidth=2.0)
    ax.scatter([0.105, 0.895], [0.585, 0.585], s=52, color=BLUE, zorder=3)

    row_titles = ["資料", "事件", "檢定"]
    row_y = [0.425, 0.285, 0.145]
    for index, (title, body, y) in enumerate(zip(row_titles, block["body"], row_y)):
        rounded_rect(
            ax,
            0.065,
            y,
            0.870,
            0.105,
            facecolor=PAPER,
            edgecolor=LINE,
            linewidth=1.0,
            radius=0.010,
        )
        ax.add_patch(
            plt.Rectangle(
                (0.065, y),
                0.010,
                0.105,
                transform=ax.transAxes,
                color=[BLUE, TEAL, AMBER][index],
            )
        )
        ax.text(
            0.095,
            y + 0.052,
            title,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=[BLUE, TEAL, AMBER][index],
            fontsize=18,
            fontweight="bold",
        )
        ax.text(
            0.205,
            y + 0.052,
            wrap(body, 36),
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=INK,
            fontsize=15,
            linespacing=1.35,
        )

    draw_footer(ax, plan, panel)
    save_panel(fig, panel)


def render_results(
    plan: dict[str, Any], evidence: dict[str, Any], panel: dict[str, Any]
) -> None:
    if panel["style"] != "bento-grid":
        raise ValueError("3_results must use bento-grid style")
    metrics = metric_blocks(panel, evidence)
    if len(metrics) != 4:
        raise ValueError("3_results contract changed")

    fig, ax = new_canvas()
    draw_header(ax, panel["title"], "主要結果：方向與統計強度分開看")

    cards = [
        (0.065, 0.480, 0.560, 0.285, BLUE_SOFT, BLUE),
        (0.650, 0.480, 0.285, 0.285, SOFT, NAVY),
        (0.065, 0.145, 0.560, 0.285, TEAL_SOFT, TEAL),
        (0.650, 0.145, 0.285, 0.285, AMBER_SOFT, AMBER),
    ]
    for metric, (x, y, width, height, fill, accent) in zip(metrics, cards):
        rounded_rect(ax, x, y, width, height, facecolor=fill, radius=0.020)
        ax.text(
            x + 0.025,
            y + height - 0.055,
            wrap(metric["label"], 21 if width > 0.4 else 13),
            transform=ax.transAxes,
            ha="left",
            va="top",
            color=INK,
            fontsize=17,
            linespacing=1.25,
            fontweight="bold",
        )
        ax.text(
            x + 0.025,
            y + 0.125,
            metric["rendered"],
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=accent,
            fontsize=40 if width > 0.4 else 34,
            fontweight="bold",
        )
        if metric["note"]:
            ax.text(
                x + 0.025,
                y + 0.046,
                wrap(metric["note"], 30 if width > 0.4 else 15),
                transform=ax.transAxes,
                ha="left",
                va="bottom",
                color=MUTED,
                fontsize=13,
                linespacing=1.25,
            )

    draw_footer(ax, plan, panel)
    save_panel(fig, panel)


def render_takeaway(
    plan: dict[str, Any], evidence: dict[str, Any], panel: dict[str, Any]
) -> None:
    if panel["style"] != "editorial":
        raise ValueError("4_takeaway must use editorial style")
    block = text_block(panel)
    metrics = metric_blocks(panel, evidence)
    if len(block["body"]) != 3 or len(metrics) != 2:
        raise ValueError("4_takeaway contract changed")

    fig, ax = new_canvas()
    draw_header(ax, panel["title"], "最強的子樣本結果，仍需保守解讀")

    rounded_rect(ax, 0.065, 0.535, 0.555, 0.240, facecolor=RED_SOFT, radius=0.022)
    ax.text(
        0.095,
        0.725,
        wrap(metrics[0]["label"], 21),
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=INK,
        fontsize=16,
        linespacing=1.25,
        fontweight="bold",
    )
    ax.text(
        0.095,
        0.590,
        metrics[0]["rendered"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=RED,
        fontsize=46,
        fontweight="bold",
    )

    rounded_rect(ax, 0.645, 0.535, 0.290, 0.240, facecolor=SOFT, radius=0.022)
    ax.text(
        0.672,
        0.725,
        metrics[1]["label"],
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=INK,
        fontsize=17,
        fontweight="bold",
    )
    ax.text(
        0.672,
        0.645,
        metrics[1]["rendered"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=NAVY,
        fontsize=34,
        fontweight="bold",
    )
    if not metrics[1]["note"]:
        raise KeyError("4_takeaway p-value note")
    ax.text(
        0.672,
        0.575,
        wrap(metrics[1]["note"], 16),
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=13,
        linespacing=1.25,
    )

    ax.text(
        0.065,
        0.485,
        block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        color=INK,
        fontsize=21,
        fontweight="bold",
    )
    bullet_y = [0.390, 0.285, 0.180]
    for y, body in zip(bullet_y, block["body"]):
        ax.scatter([0.077], [y + 0.008], s=42, color=TEAL, transform=ax.transAxes)
        ax.text(
            0.105,
            y,
            wrap(body, 51),
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=INK,
            fontsize=17,
            linespacing=1.35,
        )

    draw_footer(ax, plan, panel)
    save_panel(fig, panel)


def main() -> None:
    plan, evidence = load_inputs()
    os.makedirs(OUT_DIR, exist_ok=True)

    concept = panel_by_name(plan, "1_concept")
    method = panel_by_name(plan, "2_method")
    results = panel_by_name(plan, "3_results")
    takeaway = panel_by_name(plan, "4_takeaway")

    render_concept(plan, evidence, concept)
    render_method(plan, evidence, method)
    render_results(plan, evidence, results)
    render_takeaway(plan, evidence, takeaway)


if __name__ == "__main__":
    main()
