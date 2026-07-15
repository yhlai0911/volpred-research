#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the private-credit lazypack."""

from __future__ import annotations

import json
import numbers
import os
import textwrap
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


INITIAL_RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1332/k1332_results.json"
INITIAL_README_PATH = "/Users/yhlai0911/volpred-research/experiments/k1332/README.md"
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_a89bdd96/runs/lazypack-mile_a89bdd96/plan.json"
ROBUSTNESS_RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1499/k1499_results.json"
ARTICLE_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_a89bdd96/runs/lazypack-mile_a89bdd96/panels/mile_a89bdd96_article.md"

out_dir = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_a89bdd96/runs/lazypack-mile_a89bdd96/panels"

WIDTH = 1600
HEIGHT = 1000
DPI = 150

INK = "#162536"
MUTED = "#617181"
NAVY = "#173B57"
TEAL = "#17827A"
TEAL_SOFT = "#E8F4F1"
BLUE_SOFT = "#EAF1F6"
AMBER = "#C47724"
AMBER_SOFT = "#FBF0E3"
PALE = "#F4F7F8"
LINE = "#D9E1E6"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def read_required_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        value = handle.read()
    if not value.strip():
        raise ValueError(f"Required evidence file is empty: {path}")
    return value


def require_path(root: Any, dotted_path: str) -> Any:
    """Resolve a dotted object/list path and raise on every mismatch."""
    current = root
    for segment in dotted_path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                raise KeyError(f"Missing evidence field: {dotted_path} (at {segment})")
            current = current[segment]
        elif isinstance(current, list):
            try:
                index = int(segment)
            except ValueError as exc:
                raise TypeError(
                    f"List index must be an integer in evidence path: {dotted_path}"
                ) from exc
            current = current[index]
        else:
            raise TypeError(
                f"Cannot descend through {type(current).__name__} in evidence path: {dotted_path}"
            )
    return current


def format_bound_value(value: Any, spec: dict[str, Any]) -> str:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"Metric value must be numeric, got {value!r}")

    kind = spec["kind"]
    suffix = spec.get("suffix", "")
    if kind == "number":
        digits = spec["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid number format digits: {digits!r}")
        return f"{float(value):.{digits}f}{suffix}"
    if kind == "integer":
        as_float = float(value)
        if not as_float.is_integer():
            raise ValueError(f"Expected integer evidence value, got {value!r}")
        return f"{int(as_float):,}{suffix}"
    raise ValueError(f"Unsupported metric format kind: {kind!r}")


def resolve_metric(block: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> dict[str, str]:
    if block["kind"] != "metric":
        raise ValueError(f"Expected metric block, got {block['kind']!r}")
    value_spec = block["value"]
    source_name = value_spec["source"]
    if source_name not in evidence:
        raise KeyError(f"Unknown evidence source: {source_name}")
    raw_value = require_path(evidence[source_name], value_spec["path"])
    return {
        "label": block["label"],
        "value": format_bound_value(raw_value, value_spec["format"]),
        "note": block.get("note", ""),
    }


def get_panel(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan["panels"]
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    matches = [panel for panel in panels if panel["name"] == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}, found {len(matches)}")
    return matches[0]


def new_canvas(background: str = WHITE) -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=background)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(0, HEIGHT)
    ax.axis("off")
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
    radius: float = 24,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def source_line(ax: plt.Axes, text: str) -> None:
    ax.plot([80, 1520], [82, 82], color=LINE, linewidth=1.2)
    ax.text(80, 43, text, fontsize=14, color=MUTED, va="center", ha="left")
    ax.text(1520, 43, "VolPred 研究展示｜非投資建議", fontsize=14, color=MUTED, va="center", ha="right")


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


def draw_direction_icon(ax: plt.Axes, x: float, y: float, improves: bool, color: str) -> None:
    if improves:
        start, end = (x, y + 42), (x, y - 32)
    else:
        start, end = (x, y - 32), (x, y + 42)
    ax.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops={"arrowstyle": "-|>", "color": color, "lw": 3.2, "mutation_scale": 18},
    )


def draw_calendar_icon(ax: plt.Axes, x: float, y: float, color: str) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x - 34, y - 30),
            68,
            60,
            boxstyle="round,pad=0,rounding_size=8",
            facecolor="none",
            edgecolor=color,
            linewidth=2.6,
        )
    )
    ax.plot([x - 34, x + 34], [y + 11, y + 11], color=color, linewidth=2.6)
    ax.plot([x - 18, x - 18], [y + 23, y + 36], color=color, linewidth=2.6)
    ax.plot([x + 18, x + 18], [y + 23, y + 36], color=color, linewidth=2.6)


def draw_panel_1(panel: dict[str, Any], evidence: dict[str, dict[str, Any]], source: str) -> plt.Figure:
    blocks = panel["blocks"]
    if len(blocks) != 4:
        raise ValueError("Panel 1 requires exactly four metric blocks")
    metrics = [resolve_metric(block, evidence) for block in blocks]

    fig, ax = new_canvas()
    ax.text(80, 916, panel["title"], fontsize=44, fontweight="bold", color=INK, va="center")
    ax.text(
        80,
        850,
        "加入私募信貸公開代理後，HAR 模型的樣本外 QLIKE 誤差變化",
        fontsize=21,
        color=MUTED,
        va="center",
    )

    cards = [
        (80, 485, 870, 285, TEAL_SOFT, TEAL, "BKLN"),
        (990, 485, 530, 285, BLUE_SOFT, NAVY, "HYG"),
        (80, 155, 610, 275, AMBER_SOFT, AMBER, "KRE"),
        (730, 155, 790, 275, PALE, NAVY, "OOS"),
    ]

    for index, (metric, card) in enumerate(zip(metrics, cards)):
        x, y, width, height, fill, accent, ticker = card
        rounded_box(ax, x, y, width, height, facecolor=fill)
        ax.add_patch(Rectangle((x, y), 10, height, facecolor=accent, edgecolor="none"))
        ax.text(x + 42, y + height - 56, metric["label"], fontsize=20, color=INK, va="center")
        rounded_box(
            ax,
            x + width - 112,
            y + height - 76,
            78,
            42,
            facecolor=WHITE,
            radius=18,
        )
        ax.text(x + width - 73, y + height - 55, ticker, fontsize=13, color=accent, ha="center", va="center")
        ax.text(
            x + 42,
            y + 91,
            metric["value"],
            fontsize=55 if index != 3 else 52,
            fontweight="bold",
            color=accent,
            va="center",
        )
        if index < 3:
            draw_direction_icon(ax, x + width - 72, y + 94, index < 2, accent)
        else:
            draw_calendar_icon(ax, x + width - 78, y + 94, accent)

    ax.text(80, 116, "正值＝誤差下降；負值＝誤差上升", fontsize=15, color=MUTED, va="center")
    source_line(ax, source)
    return fig


def draw_panel_2(panel: dict[str, Any], evidence: dict[str, dict[str, Any]], source: str) -> plt.Figure:
    blocks = panel["blocks"]
    if len(blocks) != 4:
        raise ValueError("Panel 2 requires exactly four metric blocks")
    metrics = [resolve_metric(block, evidence) for block in blocks]

    fig, ax = new_canvas()
    ax.add_patch(Rectangle((0, 770), WIDTH, 230, facecolor=NAVY, edgecolor="none"))
    ax.text(80, 904, panel["title"], fontsize=43, fontweight="bold", color=WHITE, va="center")
    ax.text(
        80,
        830,
        "相對折價代理控制 SPY 與標的自身波動後的結果",
        fontsize=21,
        color="#DCE8EF",
        va="center",
    )

    rounded_box(ax, 80, 190, 400, 500, facecolor=TEAL_SOFT)
    ax.text(120, 630, metrics[0]["label"], fontsize=21, color=INK, va="center")
    ax.text(120, 468, metrics[0]["value"], fontsize=76, fontweight="bold", color=TEAL, va="center")
    ax.text(
        120,
        345,
        "唯一通過嚴格篩選的\n期程",
        fontsize=16,
        color=INK,
        va="center",
        linespacing=1.25,
    )
    ax.plot([120, 420], [300, 300], color="#BBD8D2", linewidth=2)
    ax.text(120, 255, "標的：高收益債 HYG", fontsize=17, color=MUTED, va="center")

    ax.text(540, 691, "不同期程的 t 統計量", fontsize=21, fontweight="bold", color=INK, va="center")
    right_cards = [
        (540, TEAL_SOFT, TEAL),
        (870, PALE, NAVY),
        (1200, PALE, MUTED),
    ]
    for metric, (x, fill, accent) in zip(metrics[1:], right_cards):
        rounded_box(
            ax,
            x,
            250,
            290,
            370,
            facecolor=fill,
            edgecolor=accent if x == 540 else LINE,
            linewidth=2.2 if x == 540 else 1.2,
        )
        ax.text(x + 32, 560, metric["label"], fontsize=19, color=INK, va="center")
        ax.text(
            x + 145,
            445,
            f"t = {metric['value']}",
            fontsize=24,
            fontweight="bold",
            color=accent,
            ha="center",
            va="center",
        )
        ax.plot([x + 32, x + 258], [380, 380], color=LINE, linewidth=1.5)
        ax.text(x + 32, 322, metric["note"], fontsize=17, color=MUTED, va="center")

    source_line(ax, source)
    return fig


def draw_panel_3(panel: dict[str, Any], evidence: dict[str, dict[str, Any]], source: str) -> plt.Figure:
    blocks = panel["blocks"]
    if len(blocks) != 4:
        raise ValueError("Panel 3 requires three text blocks and one metric block")
    text_blocks = blocks[:3]
    if any(block["kind"] != "text" for block in text_blocks):
        raise ValueError("Panel 3 first three blocks must be text blocks")
    seed_metric = resolve_metric(blocks[3], evidence)

    fig, ax = new_canvas()
    ax.text(80, 916, panel["title"], fontsize=43, fontweight="bold", color=INK, va="center")
    ax.text(80, 850, "公開價格能提示異常，但不能替代私募信貸帳本", fontsize=21, color=MUTED, va="center")
    ax.plot([80, 1520], [810, 810], color=INK, linewidth=2.2)

    ax.add_patch(Circle((365, 505), 206, facecolor=BLUE_SOFT, edgecolor="none"))
    ax.add_patch(Circle((365, 505), 160, facecolor=WHITE, edgecolor=NAVY, linewidth=2.4))
    ax.add_patch(Circle((365, 505), 118, facecolor=WHITE, edgecolor=LINE, linewidth=1.5))
    ax.text(
        365,
        520,
        "檢查起點\n≠\n危機預報器",
        fontsize=32,
        fontweight="bold",
        color=NAVY,
        ha="center",
        va="center",
        linespacing=1.25,
    )

    rounded_box(ax, 130, 130, 470, 125, facecolor=PALE)
    ax.text(165, 215, seed_metric["label"], fontsize=17, color=MUTED, va="center")
    ax.text(165, 165, seed_metric["value"], fontsize=31, fontweight="bold", color=INK, va="center")
    ax.text(245, 165, "固定以利重現", fontsize=16, color=MUTED, va="center")

    card_positions = [(760, 610), (760, 405), (760, 200)]
    fills = [TEAL_SOFT, BLUE_SOFT, AMBER_SOFT]
    accents = [TEAL, NAVY, AMBER]
    for block, (x, y), fill, accent in zip(text_blocks, card_positions, fills, accents):
        body = block["body"]
        if not isinstance(body, list) or not body or not all(isinstance(item, str) for item in body):
            raise TypeError("Panel 3 text block body must be a non-empty list of strings")
        body_text = wrap_zh("".join(body), 22)
        rounded_box(ax, x, y, 760, 160, facecolor=fill)
        ax.add_patch(Rectangle((x, y), 9, 160, facecolor=accent, edgecolor="none"))
        ax.text(
            x + 38,
            y + 125,
            block["heading"],
            fontsize=19,
            fontweight="bold",
            color=INK,
            va="center",
        )
        ax.text(
            x + 38,
            y + 88,
            body_text,
            fontsize=14,
            color=MUTED,
            va="top",
            linespacing=1.25,
        )

    source_line(ax, source)
    return fig


def save_panel(fig: plt.Figure, panel: dict[str, Any], source: str) -> None:
    output_path = os.path.join(out_dir, f"{panel['name']}.png")
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
            "Source": source,
        },
    )
    plt.close(fig)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)

    initial = load_json(INITIAL_RESULTS_PATH)
    robustness = load_json(ROBUSTNESS_RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    read_required_text(INITIAL_README_PATH)
    read_required_text(ARTICLE_PATH)

    evidence = {"initial": initial, "robustness": robustness}
    initial_id = str(require_path(initial, "experiment_id")).upper()
    robustness_id = str(require_path(robustness, "experiment_id")).upper()

    panel_1 = get_panel(plan, "1_initial_signal")
    panel_2 = get_panel(plan, "2_robustness_filter")
    panel_3 = get_panel(plan, "3_honest_use")

    source_1 = f"資料來源：experiment {initial_id}"
    source_2 = f"資料來源：experiment {robustness_id}"
    source_3 = f"資料來源：experiment {initial_id}、{robustness_id}"

    save_panel(draw_panel_1(panel_1, evidence, source_1), panel_1, source_1)
    save_panel(draw_panel_2(panel_2, evidence, source_2), panel_2, source_2)
    save_panel(draw_panel_3(panel_3, evidence, source_3), panel_3, source_3)


if __name__ == "__main__":
    main()
