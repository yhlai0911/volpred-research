#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_62fa3fbc article."""

from __future__ import annotations

import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1493/k1493_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1493/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_62fa3fbc/runs/lazypack-mile_62fa3fbc/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_62fa3fbc/runs/lazypack-mile_62fa3fbc/panels/"
    "mile_62fa3fbc_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_62fa3fbc/runs/lazypack-mile_62fa3fbc/panels"
)

EXPECTED_PANELS = ("panel_question", "panel_result", "panel_takeaway")
EXPECTED_SOURCE_LABEL = (
    "experiment K1493 results "
    "(variance risk premium proxy decline vs short-vol product economics)"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

NAVY = "#102A43"
NAVY_2 = "#173F5F"
INK = "#1B2A3A"
MUTED = "#526476"
PAPER = "#F5F7FA"
WHITE = "#FFFFFF"
LINE = "#D8E0E8"
TEAL = "#087E8B"
TEAL_SOFT = "#E4F3F4"
AMBER = "#C27A16"
AMBER_SOFT = "#FFF4DE"
RED = "#B93A3A"
RED_SOFT = "#FBE9E9"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_required_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return text


def require_dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{where} must be an object")
    return value


def require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{where} must be a non-empty string")
    return value


def json_pointer(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field at {pointer!r}: {token!r}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Invalid evidence list index at {pointer!r}") from exc
        else:
            raise KeyError(
                f"Cannot descend through {type(current).__name__} at {pointer!r}"
            )
    return current


def format_bound_value(value: Any, spec: dict[str, Any], where: str) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{where} must resolve to a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where} must resolve to a finite number")

    kind = require_string(spec.get("kind"), f"{where}.format.kind")
    digits = spec.get("digits", 1)
    if not isinstance(digits, int) or isinstance(digits, bool) or not 0 <= digits <= 3:
        raise ValueError(f"{where}.format.digits must be an integer from 0 to 3")

    if kind == "percent":
        default_scale = 100.0
        suffix = "%"
    elif kind == "number":
        default_scale = 1.0
        suffix = ""
    else:
        raise ValueError(f"Unsupported numeric format kind at {where}: {kind!r}")

    scale = spec.get("scale", default_scale)
    if (
        not isinstance(scale, (int, float))
        or isinstance(scale, bool)
        or not math.isfinite(float(scale))
        or float(scale) <= 0
    ):
        raise ValueError(f"{where}.format.scale must be a positive finite number")
    return f"{number * float(scale):.{digits}f}{suffix}"


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


def wrap_to_pixels(
    fig: Any,
    text: str,
    *,
    max_width_px: float,
    fontsize: float,
    first_prefix: str = "",
    continuation_prefix: str = "",
) -> list[str]:
    """Wrap text against its rendered Heiti TC width, not a character estimate."""
    renderer = fig.canvas.get_renderer()

    def rendered_width(value: str) -> float:
        probe = fig.text(
            0,
            0,
            value,
            fontsize=fontsize,
            fontfamily="Heiti TC",
            alpha=0,
        )
        try:
            return probe.get_window_extent(renderer=renderer).width
        finally:
            probe.remove()

    lines: list[str] = []
    remaining = text.strip()
    prefix = first_prefix
    while remaining:
        available = max_width_px - rendered_width(prefix)
        if available <= 0:
            raise ValueError("Text prefix leaves no horizontal room in its card")

        low, high = 1, len(remaining)
        fit = 0
        while low <= high:
            midpoint = (low + high) // 2
            if rendered_width(remaining[:midpoint]) <= available:
                fit = midpoint
                low = midpoint + 1
            else:
                high = midpoint - 1
        if fit == 0:
            raise ValueError("A text glyph is wider than its card")

        lines.append(prefix + remaining[:fit])
        remaining = remaining[fit:]
        prefix = continuation_prefix

    return lines


def add_round_rect(
    ax: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = LINE,
    linewidth: float = 1.2,
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
            clip_on=False,
        )
    )


def panel_accent(name: str) -> tuple[str, str]:
    if name == "panel_question":
        return AMBER, AMBER_SOFT
    if name == "panel_result":
        return TEAL, TEAL_SOFT
    if name == "panel_takeaway":
        return RED, RED_SOFT
    raise ValueError(f"Unexpected panel name: {name}")


def render_panel(
    panel: dict[str, Any],
    results: dict[str, Any],
    source_label: str,
) -> None:
    name = require_string(panel.get("name"), "panel.name")
    if name not in EXPECTED_PANELS:
        raise ValueError(f"Unexpected panel name: {name}")
    title = require_string(panel.get("title"), f"{name}.title")
    alt = require_string(panel.get("alt"), f"{name}.alt")

    sources = panel.get("sources")
    if sources != ["results"]:
        raise ValueError(f"{name}.sources must be exactly ['results']")

    blocks = panel.get("blocks")
    if not isinstance(blocks, list) or len(blocks) < 2:
        raise ValueError(f"{name}.blocks must contain text and metric blocks")
    text_block = require_dict(blocks[0], f"{name}.blocks[0]")
    if text_block.get("kind") != "text":
        raise ValueError(f"{name}.blocks[0] must be a text block")
    heading = require_string(text_block.get("heading"), f"{name}.text.heading")
    body = text_block.get("body")
    if (
        not isinstance(body, list)
        or len(body) != 2
        or any(not isinstance(item, str) or not item.strip() for item in body)
    ):
        raise ValueError(f"{name}.text.body must contain exactly two strings")

    metric_blocks = [require_dict(item, f"{name}.metric") for item in blocks[1:]]
    if len(metric_blocks) not in (2, 3):
        raise ValueError(f"{name} must contain two or three metric blocks")

    metrics: list[tuple[str, str]] = []
    for index, block in enumerate(metric_blocks):
        where = f"{name}.blocks[{index + 1}]"
        if block.get("kind") != "metric":
            raise ValueError(f"{where} must be a metric block")
        label = require_string(block.get("label"), f"{where}.label")
        binding = require_dict(block.get("value"), f"{where}.value")
        if binding.get("source") != "results":
            raise ValueError(f"{where}.value.source must be 'results'")
        pointer = require_string(binding.get("path"), f"{where}.value.path")
        format_spec = require_dict(binding.get("format"), f"{where}.value.format")
        raw_value = json_pointer(results, pointer)
        metrics.append((label, format_bound_value(raw_value, format_spec, where)))

    accent, accent_soft = panel_accent(name)
    fig = plt.figure(
        figsize=(WIDTH / DPI, HEIGHT / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(
        Rectangle(
            (0, 0),
            1,
            1,
            transform=ax.transAxes,
            facecolor=WHITE,
            edgecolor="none",
        )
    )
    ax.add_patch(
        Rectangle(
            (0, 0.80),
            1,
            0.20,
            transform=ax.transAxes,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    ax.add_patch(
        Rectangle(
            (0, 0.80),
            0.018,
            0.20,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.add_patch(
        Circle(
            (0.925, 0.90),
            0.030,
            transform=ax.transAxes,
            facecolor="none",
            edgecolor=WHITE,
            linewidth=2.0,
            alpha=0.72,
        )
    )
    ax.plot(
        [0.904, 0.946],
        [0.90, 0.90],
        transform=ax.transAxes,
        color=WHITE,
        linewidth=2.0,
        alpha=0.72,
    )
    fig.text(
        0.055,
        0.902,
        wrap_zh(title, 29),
        ha="left",
        va="center",
        color=WHITE,
        fontsize=29,
        fontweight="bold",
        linespacing=1.14,
    )

    add_round_rect(
        ax,
        0.055,
        0.460,
        0.89,
        0.280,
        facecolor=PAPER,
        edgecolor=LINE,
    )
    ax.add_patch(
        Circle(
            (0.085, 0.687),
            0.010,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    fig.text(
        0.105,
        0.687,
        heading,
        ha="left",
        va="center",
        color=NAVY_2,
        fontsize=21,
        fontweight="bold",
    )
    body_fontsize = 15.0
    body_linespacing = 1.28
    body_max_width_px = WIDTH * (0.915 - 0.084)
    wrapped_body = [
        wrap_to_pixels(
            fig,
            item,
            max_width_px=body_max_width_px,
            fontsize=body_fontsize,
            first_prefix="• ",
            continuation_prefix="  ",
        )
        for item in body
    ]
    line_step = body_fontsize * DPI / 72.0 * body_linespacing / HEIGHT
    body_top = 0.632
    bullet_gap = 0.014
    second_body_top = body_top - len(wrapped_body[0]) * line_step - bullet_gap
    for lines, top in zip(wrapped_body, (body_top, second_body_top), strict=True):
        fig.text(
            0.084,
            top,
            "\n".join(lines),
            ha="left",
            va="top",
            color=INK,
            fontsize=body_fontsize,
            linespacing=body_linespacing,
        )

    left = 0.055
    right = 0.945
    gap = 0.018
    card_width = (right - left - gap * (len(metrics) - 1)) / len(metrics)
    for index, (label, rendered) in enumerate(metrics):
        x = left + index * (card_width + gap)
        add_round_rect(
            ax,
            x,
            0.175,
            card_width,
            0.235,
            facecolor=WHITE,
            edgecolor=LINE,
            linewidth=1.4,
        )
        ax.add_patch(
            Rectangle(
                (x, 0.392),
                card_width,
                0.018,
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )
        fig.text(
            x + 0.025,
            0.345,
            wrap_zh(label, 14 if len(metrics) == 3 else 21),
            ha="left",
            va="top",
            color=MUTED,
            fontsize=14.5,
            linespacing=1.22,
        )
        fig.text(
            x + 0.025,
            0.235,
            rendered,
            ha="left",
            va="center",
            color=accent,
            fontsize=35 if len(metrics) == 3 else 39,
            fontweight="bold",
        )
        ax.add_patch(
            Circle(
                (x + card_width - 0.037, 0.218),
                0.013,
                transform=ax.transAxes,
                facecolor=accent_soft,
                edgecolor=accent,
                linewidth=1.2,
            )
        )

    ax.plot(
        [0.055, 0.945],
        [0.115, 0.115],
        transform=ax.transAxes,
        color=LINE,
        linewidth=1.0,
    )
    fig.text(
        0.055,
        0.078,
        "資料來源｜" + source_label,
        ha="left",
        va="center",
        color=MUTED,
        fontsize=9.2,
    )

    destination = Path(out_dir) / f"{name}.png"
    fig.savefig(
        destination,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        metadata={
            "Title": title,
            "Description": alt,
            "Source": source_label,
        },
    )
    plt.close(fig)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)

    results = require_dict(load_json(RESULTS_PATH), "results")
    plan = require_dict(load_json(PLAN_PATH), "plan")
    load_required_text(README_PATH)
    load_required_text(ARTICLE_PATH)

    evidence = require_dict(plan.get("evidence"), "plan.evidence")
    results_evidence = require_dict(evidence.get("results"), "plan.evidence.results")
    source_label = require_string(
        results_evidence.get("label"), "plan.evidence.results.label"
    )
    if source_label != EXPECTED_SOURCE_LABEL:
        raise ValueError(
            "The strict-plan source label changed; refusing to render a rewritten source"
        )

    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    panel_names = tuple(
        require_string(require_dict(panel, "panel").get("name"), "panel.name")
        for panel in panels
    )
    if panel_names != EXPECTED_PANELS:
        raise ValueError(
            f"Expected panels {EXPECTED_PANELS!r}, found {panel_names!r}"
        )

    for panel in panels:
        render_panel(require_dict(panel, "panel"), results, source_label)


if __name__ == "__main__":
    main()
