#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_dc8c018c lazypack.

All displayed statistics are resolved at runtime from the strict plan and its
results evidence.  Missing panels, blocks, JSON-pointer fields, or source labels
raise immediately so the caller receives a useful traceback.
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
from matplotlib.patches import FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_dc8c018c/runs/lazypack-mile_dc8c018c/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1654/k1654_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_dc8c018c/runs/lazypack-mile_dc8c018c/panels/"
    "mile_dc8c018c_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_dc8c018c/runs/lazypack-mile_dc8c018c/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#14263D"
INK = "#172638"
MUTED = "#5C6978"
BLUE = "#2767A8"
BLUE_SOFT = "#EAF2FA"
TEAL = "#168078"
TEAL_SOFT = "#E5F4F1"
RED = "#C84E4B"
RED_SOFT = "#FAECEB"
AMBER = "#B47718"
AMBER_SOFT = "#FBF2E3"
BORDER = "#D7E0E8"
PAPER = "#FFFFFF"
PALE = "#F5F8FB"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {where}, got {type(value).__name__}")
    return value


def require_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected list at {where}, got {type(value).__name__}")
    return value


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901 JSON pointer, raising on every missing field."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Not a JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing JSON pointer field {pointer!r} at {token!r}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing JSON pointer index in {pointer!r}") from exc
        else:
            raise KeyError(f"Cannot descend through {type(current).__name__} in {pointer!r}")
    return current


def numeric(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric value at {where}, got {type(value).__name__}")
    return float(value)


def format_metric(value: Any, spec: dict[str, Any], pointer: str) -> str:
    kind = spec.get("kind")
    number = numeric(value, pointer)
    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer-valued number at {pointer}: {number}")
        return str(int(number))
    if kind == "number":
        digits = spec.get("digits")
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits setting for {pointer}: {digits!r}")
        sign = "+" if spec.get("show_plus") else ""
        return format(number, f"{sign}.{digits}f")
    raise ValueError(f"Unsupported metric format at {pointer}: {kind!r}")


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require_list(plan.get("panels"), "/panels")
    matches = [require_dict(p, "/panels/*") for p in panels if isinstance(p, dict) and p.get("name") == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one panel named {name!r}, found {len(matches)}")
    panel = matches[0]
    for key in ("title", "alt", "sources", "blocks"):
        if key not in panel:
            raise KeyError(f"Panel {name!r} is missing {key!r}")
    return panel


def blocks_of_kind(panel: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    blocks = require_list(panel["blocks"], f"panel {panel['name']}/blocks")
    return [require_dict(block, "panel block") for block in blocks if isinstance(block, dict) and block.get("kind") == kind]


def text_block(panel: dict[str, Any], index: int) -> dict[str, Any]:
    blocks = blocks_of_kind(panel, "text")
    try:
        block = blocks[index]
    except IndexError as exc:
        raise KeyError(f"Panel {panel['name']!r} is missing text block {index}") from exc
    if not isinstance(block.get("heading"), str):
        raise TypeError(f"Text heading {index} in {panel['name']!r} must be a string")
    bodies = require_list(block.get("body"), f"panel {panel['name']}/text/{index}/body")
    if not bodies or not all(isinstance(body, str) and body for body in bodies):
        raise TypeError(f"Text body {index} in {panel['name']!r} must contain strings")
    return block


def metric_block(panel: dict[str, Any], index: int, results: dict[str, Any]) -> dict[str, Any]:
    blocks = blocks_of_kind(panel, "metric")
    try:
        block = blocks[index]
    except IndexError as exc:
        raise KeyError(f"Panel {panel['name']!r} is missing metric block {index}") from exc
    value_spec = require_dict(block.get("value"), f"panel {panel['name']}/metric/{index}/value")
    if value_spec.get("source") != "results":
        raise ValueError(f"Metric {index} in {panel['name']!r} must use results evidence")
    pointer = value_spec.get("path")
    if not isinstance(pointer, str):
        raise TypeError(f"Metric {index} in {panel['name']!r} has no JSON pointer")
    raw = resolve_pointer(results, pointer)
    fmt = require_dict(value_spec.get("format"), f"panel {panel['name']}/metric/{index}/format")
    return {
        "label": block["label"],
        "note": block["note"],
        "raw": numeric(raw, pointer),
        "rendered": format_metric(raw, fmt, pointer),
        "pointer": pointer,
    }


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


def add_card(
    fig: plt.Figure,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = PAPER,
    edge: str = BORDER,
    radius: float = 0.018,
    linewidth: float = 1.2,
) -> None:
    fig.add_artist(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=fig.transFigure,
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
            clip_on=False,
        )
    )


def add_text(
    fig: plt.Figure,
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "top",
    linespacing: float = 1.28,
) -> None:
    fig.text(
        x,
        y,
        text,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=linespacing,
    )


def base_figure(title: str, source_label: str) -> plt.Figure:
    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=PAPER)
    fig.add_artist(Rectangle((0, 0.88), 1, 0.12, transform=fig.transFigure, color=NAVY))
    title_size = 29 if len(title) <= 16 else 25
    add_text(fig, 0.055, 0.942, title, size=title_size, color="white", weight="bold", va="center")
    fig.add_artist(Rectangle((0.05, 0.091), 0.90, 0.0015, transform=fig.transFigure, color=BORDER))
    source = f"資料來源｜{source_label}"
    # The evidence label is deliberately complete and can be long.  Keep it in
    # the footer's 0.89-wide safe area instead of relying on the canvas edge to
    # clip an overlong first line.
    add_text(fig, 0.055, 0.058, wrap_zh(source, 76), size=7.0, color=MUTED, va="center", linespacing=1.12)
    return fig


def save(fig: plt.Figure, filename: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    fig.savefig(
        os.path.join(out_dir, filename),
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        metadata={"Software": "VolPred deterministic matplotlib renderer"},
    )
    plt.close(fig)


def render_framework(panel: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    first = text_block(panel, 0)
    second = text_block(panel, 1)
    skew = metric_block(panel, 0, results)
    kurt = metric_block(panel, 1, results)
    fig = base_figure(panel["title"], source_label)

    cards = [
        (0.055, first, BLUE_SOFT, BLUE),
        (0.520, second, TEAL_SOFT, TEAL),
    ]
    for x, block, face, accent in cards:
        add_card(fig, x, 0.535, 0.425, 0.295, face=face, edge=face)
        fig.add_artist(Rectangle((x, 0.535), 0.008, 0.295, transform=fig.transFigure, color=accent))
        add_text(fig, x + 0.026, 0.792, wrap_zh(block["heading"], 18), size=15, color=accent, weight="bold")
        body = require_list(block["body"], "framework text body")
        # Render both paragraphs as one artist.  Independent fixed y positions
        # made the first paragraph collide with the second whenever it wrapped
        # to an additional line.
        copy = f"{wrap_zh(body[0], 27)}\n\n{wrap_zh(body[1], 27)}"
        add_text(fig, x + 0.026, 0.742, copy, size=9.2, color=INK, linespacing=1.22)

    for x, metric, face, accent in (
        (0.055, skew, RED_SOFT, RED),
        (0.520, kurt, AMBER_SOFT, AMBER),
    ):
        add_card(fig, x, 0.145, 0.425, 0.335, face=face, edge=face)
        add_text(fig, x + 0.026, 0.432, wrap_zh(metric["label"], 20), size=12.5, color=INK, weight="bold")
        add_text(fig, x + 0.026, 0.330, metric["rendered"], size=39, color=accent, weight="bold")
        add_text(fig, x + 0.026, 0.225, wrap_zh(metric["note"], 26), size=10, color=MUTED, linespacing=1.24)

    save(fig, "panel_framework.png")


def result_number(results: dict[str, Any], pointer: str) -> float:
    return numeric(resolve_pointer(results, pointer), pointer)


def render_numbers(panel: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    summary = text_block(panel, 0)
    metrics = [metric_block(panel, i, results) for i in range(6)]
    fig = base_figure(panel["title"], source_label)

    add_card(fig, 0.055, 0.745, 0.890, 0.095, face=PALE, edge=PALE)
    add_text(fig, 0.075, 0.815, wrap_zh(summary["heading"], 14), size=11.8, color=NAVY, weight="bold")
    body = require_list(summary["body"], "numbers summary body")
    add_text(fig, 0.305, 0.817, wrap_zh(body[0], 24), size=9.2, color=INK, linespacing=1.18)
    add_text(fig, 0.635, 0.817, wrap_zh(body[1], 23), size=9.2, color=INK, linespacing=1.18)

    asset_keys = ["SPY", "QQQ", "^TWII", "^N225"]
    asset_labels = ["標普 500 ETF", "那斯達克 100 ETF", "台灣加權指數", "日經 225"]
    baseline = [
        result_number(results, f"/results/{key.replace('~', '~0').replace('/', '~1')}/var_backtests/alpha_0.01/M0/n_violations")
        for key in asset_keys
    ]
    reshaped = [
        result_number(results, f"/results/{key.replace('~', '~0').replace('/', '~1')}/var_backtests/alpha_0.01/M2/n_violations")
        for key in asset_keys
    ]
    expected = [
        result_number(results, f"/results/{key.replace('~', '~0').replace('/', '~1')}/var_backtests/alpha_0.01/M0/expected_violations")
        for key in asset_keys
    ]

    # Reserve enough left margin for the longest CJK market label.  The old
    # 7.5% margin placed several tick labels outside the 1600 px canvas.
    # Keep a dedicated caption band below the plot.  Putting the legend inside
    # the data area made its final row cover the N225 value label ("35").
    ax = fig.add_axes([0.155, 0.405, 0.435, 0.285], facecolor=PAPER)
    positions = list(range(len(asset_keys)))
    height = 0.25
    ax.barh([p + height / 2 for p in positions], baseline, height=height, color=RED, label="左右對稱常態假設")
    ax.barh([p - height / 2 for p in positions], reshaped, height=height, color=TEAL, label="允許偏斜厚尾")
    ax.scatter(expected, positions, marker="|", s=300, linewidths=2.3, color=NAVY, label="承諾天數", zorder=4)
    for p, value in zip(positions, baseline):
        ax.text(value + 0.65, p + height / 2, f"{int(value)}", va="center", fontsize=10, color=RED, fontweight="bold")
    for p, value in zip(positions, reshaped):
        ax.text(value + 0.65, p - height / 2, f"{int(value)}", va="center", fontsize=10, color=TEAL, fontweight="bold")
    ax.set_yticks(positions, asset_labels, fontsize=9, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, max(baseline) + 5)
    # The title already names the unit as 破線天數.  A separate x-axis
    # label occupied the same fixed row as the evidence note below the chart.
    ax.set_title("承諾與實際破線天數", loc="left", fontsize=13, color=NAVY, fontweight="bold", pad=8)
    ax.grid(axis="x", color=BORDER, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(BORDER)
    ax.tick_params(axis="x", colors=MUTED, labelsize=9)
    ax.tick_params(axis="y", length=0)
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(0.0, -0.18),
        borderaxespad=0,
        frameon=False,
        fontsize=7.8,
        ncol=3,
        columnspacing=1.0,
        handlelength=1.5,
    )
    add_text(
        fig,
        0.075,
        0.315,
        wrap_zh(metrics[0]["note"] + "；" + metrics[1]["note"], 36),
        size=8.4,
        color=MUTED,
    )

    add_card(fig, 0.645, 0.355, 0.300, 0.350, face=BLUE_SOFT, edge=BLUE_SOFT)
    add_text(fig, 0.670, 0.665, wrap_zh(metrics[2]["label"], 15), size=11.5, color=NAVY, weight="bold")
    add_text(fig, 0.670, 0.555, metrics[2]["rendered"], size=31, color=RED, weight="bold")
    add_text(fig, 0.780, 0.555, "→", size=26, color=MUTED, weight="bold")
    add_text(fig, 0.835, 0.555, metrics[3]["rendered"], size=31, color=TEAL, weight="bold")
    add_text(fig, 0.670, 0.477, "對稱模型", size=10.5, color=RED, weight="bold")
    add_text(fig, 0.835, 0.477, "換形狀後", size=10.5, color=TEAL, weight="bold")
    add_text(fig, 0.670, 0.424, wrap_zh(metrics[2]["note"], 22), size=9.5, color=MUTED)
    add_text(fig, 0.670, 0.378, wrap_zh(metrics[3]["note"], 22), size=9.5, color=MUTED)

    for x, metric, face, accent in (
        (0.055, metrics[4], RED_SOFT, RED),
        (0.505, metrics[5], TEAL_SOFT, TEAL),
    ):
        add_card(fig, x, 0.130, 0.440, 0.155, face=face, edge=face)
        add_text(fig, x + 0.025, 0.252, wrap_zh(metric["label"], 22), size=11.5, color=INK, weight="bold")
        add_text(fig, x + 0.025, 0.190, metric["rendered"], size=27, color=accent, weight="bold", va="center")
        add_text(fig, x + 0.110, 0.190, wrap_zh(metric["note"], 22), size=9.5, color=MUTED, va="center")

    save(fig, "panel_numbers.png")


def render_takeaway(panel: dict[str, Any], results: dict[str, Any], source_label: str) -> None:
    context = text_block(panel, 0)
    takeaway = text_block(panel, 1)
    metrics = [metric_block(panel, i, results) for i in range(3)]
    fig = base_figure(panel["title"], source_label)

    add_card(fig, 0.055, 0.665, 0.890, 0.175, face=PALE, edge=PALE)
    add_text(fig, 0.078, 0.805, context["heading"], size=16, color=NAVY, weight="bold")
    context_body = require_list(context["body"], "takeaway context body")
    add_text(fig, 0.078, 0.752, wrap_zh(context_body[0], 30), size=9.8, color=INK, linespacing=1.20)
    add_text(fig, 0.520, 0.752, wrap_zh(context_body[1], 29), size=9.8, color=INK, linespacing=1.20)

    metric_cards = [
        (0.055, metrics[0], RED_SOFT, RED),
        (0.358, metrics[1], BLUE_SOFT, BLUE),
        (0.661, metrics[2], AMBER_SOFT, AMBER),
    ]
    for x, metric, face, accent in metric_cards:
        add_card(fig, x, 0.425, 0.284, 0.190, face=face, edge=face)
        add_text(fig, x + 0.020, 0.582, wrap_zh(metric["label"], 16), size=11, color=INK, weight="bold")
        suffix = "%" if metric is metrics[0] else ""
        add_text(fig, x + 0.020, 0.505, metric["rendered"] + suffix, size=26, color=accent, weight="bold", va="center")
        add_text(fig, x + 0.020, 0.463, wrap_zh(metric["note"], 19), size=8.8, color=MUTED, linespacing=1.16)

    add_card(fig, 0.055, 0.130, 0.890, 0.245, face=TEAL_SOFT, edge=TEAL_SOFT)
    add_text(fig, 0.078, 0.340, takeaway["heading"], size=16, color=TEAL, weight="bold")
    takeaway_body = require_list(takeaway["body"], "takeaway body")
    if len(takeaway_body) != 3:
        raise ValueError("Panel takeaway must contain exactly three reader takeaways")
    for index, (x, body) in enumerate(zip((0.078, 0.375, 0.672), takeaway_body), start=1):
        fig.add_artist(
            plt.Circle((x + 0.018, 0.285), 0.018, transform=fig.transFigure, facecolor=TEAL, edgecolor="none")
        )
        add_text(fig, x + 0.018, 0.285, str(index), size=10.5, color="white", weight="bold", ha="center", va="center")
        add_text(fig, x, 0.246, wrap_zh(body, 18), size=9.0, color=INK, linespacing=1.20)

    save(fig, "panel_takeaway.png")


def main() -> None:
    plan = require_dict(load_json(PLAN_PATH), str(PLAN_PATH))
    results = require_dict(load_json(RESULTS_PATH), str(RESULTS_PATH))
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = require_dict(plan.get("evidence"), "/evidence")
    result_evidence = require_dict(evidence.get("results"), "/evidence/results")
    source_label = result_evidence.get("label")
    if not isinstance(source_label, str) or not source_label.strip():
        raise KeyError("Strict plan is missing /evidence/results/label")

    framework = panel_by_name(plan, "panel_framework")
    numbers = panel_by_name(plan, "panel_numbers")
    takeaway = panel_by_name(plan, "panel_takeaway")
    for panel in (framework, numbers, takeaway):
        if panel["sources"] != ["results"]:
            raise ValueError(f"Panel {panel['name']!r} must cite only results evidence")

    render_framework(framework, results, source_label)
    render_numbers(numbers, results, source_label)
    render_takeaway(takeaway, results, source_label)


if __name__ == "__main__":
    main()
