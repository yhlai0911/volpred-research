#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_d3d4aebd lazypack."""

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


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_d3d4aebd/runs/lazypack-mile_d3d4aebd/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1714/K1714_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_d3d4aebd/runs/lazypack-mile_d3d4aebd/panels/"
    "mile_d3d4aebd_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_d3d4aebd/runs/lazypack-mile_d3d4aebd/panels"
)

EXPECTED_PANEL_NAMES = (
    "panel_numbers",
    "panel_framework",
    "panel_takeaway",
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#102A43"
NAVY_2 = "#173F5F"
BLUE = "#1677A8"
TEAL = "#168C82"
AMBER = "#C47B16"
INK = "#17212B"
MUTED = "#52606D"
PALE = "#F3F7FA"
LINE = "#D8E2EA"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    """Load one required JSON object, failing loudly on every malformed input."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object at {path}, got {type(payload).__name__}")
    return payload


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON pointer and raise if any segment is absent."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")

    node = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if part not in node:
                raise KeyError(f"Missing results field at {pointer!r}: segment {part!r}")
            node = node[part]
        elif isinstance(node, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise KeyError(f"Non-integer list segment {part!r} in {pointer!r}") from exc
            node = node[index]
        else:
            raise KeyError(
                f"Cannot descend through {type(node).__name__} at segment {part!r} "
                f"in {pointer!r}"
            )
    return node


def require_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty text for {context}")
    return value


def format_metric(results: dict[str, Any], value_spec: dict[str, Any]) -> str:
    """Read and format a metric strictly from the results evidence."""
    if value_spec.get("source") != "results":
        raise ValueError(f"Unsupported metric source: {value_spec.get('source')!r}")

    pointer = require_text(value_spec.get("path"), "metric path")
    raw_value = resolve_pointer(results, pointer)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise TypeError(f"Expected numeric value at {pointer!r}, got {raw_value!r}")
    value = float(raw_value)
    if not math.isfinite(value):
        raise ValueError(f"Expected finite value at {pointer!r}, got {raw_value!r}")

    fmt = value_spec.get("format")
    if not isinstance(fmt, dict):
        raise TypeError(f"Missing format object for {pointer!r}")
    kind = fmt.get("kind")
    digits = fmt.get("digits")
    if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
        raise TypeError(f"Invalid digits for {pointer!r}: {digits!r}")

    if kind == "percent":
        return f"{value * 100:.{digits}f}%"
    if kind == "number":
        return f"{value:.{digits}f}"
    raise ValueError(f"Unsupported format kind for {pointer!r}: {kind!r}")


def wrap_text(text: str, width: int) -> str:
    """Wrap Chinese or Latin text at a deterministic character budget."""
    return textwrap.fill(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )


def add_header(fig: plt.Figure, title: str, accent: str) -> None:
    fig.patches.append(
        Rectangle(
            (0, 0.82),
            1,
            0.18,
            transform=fig.transFigure,
            facecolor=NAVY,
            edgecolor="none",
            zorder=-10,
        )
    )
    fig.patches.append(
        Rectangle(
            (0.055, 0.865),
            0.008,
            0.09,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
        )
    )
    fig.text(
        0.082,
        0.91,
        title,
        color=WHITE,
        fontsize=27,
        fontweight="bold",
        ha="left",
        va="center",
    )

    # Small, non-textual analytical mark; it stays wholly inside the header.
    x0 = 0.895
    for index, height in enumerate((0.028, 0.050, 0.038, 0.070)):
        fig.patches.append(
            Rectangle(
                (x0 + index * 0.018, 0.875),
                0.009,
                height,
                transform=fig.transFigure,
                facecolor=accent if index == 3 else "#6F8FA8",
                edgecolor="none",
            )
        )


def add_explainer(fig: plt.Figure, text_block: dict[str, Any], accent: str) -> None:
    heading = require_text(text_block.get("heading"), "text block heading")
    body = text_block.get("body")
    if not isinstance(body, list) or len(body) != 2:
        raise ValueError("Each panel text block must contain exactly two body paragraphs")
    paragraphs = [require_text(item, "text block paragraph") for item in body]

    fig.patches.append(
        FancyBboxPatch(
            (0.055, 0.545),
            0.89,
            0.225,
            boxstyle="round,pad=0.008,rounding_size=0.012",
            transform=fig.transFigure,
            facecolor=PALE,
            edgecolor=LINE,
            linewidth=1.0,
            zorder=-5,
        )
    )
    fig.patches.append(
        Circle(
            (0.083, 0.716),
            0.008,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
        )
    )
    fig.text(
        0.102,
        0.716,
        heading,
        color=INK,
        fontsize=17,
        fontweight="bold",
        ha="left",
        va="center",
    )
    # Heiti TC's full-width glyphs are substantially wider than the Latin
    # character budget previously assumed here.  Keep every paragraph to at
    # most 36 glyphs so the rendered line remains inside the explainer card;
    # the slightly smaller type and tighter leading leave room for the four
    # lines produced by the longest planned copy without vertical overflow.
    body_text = "\n".join(wrap_text(paragraph, 36) for paragraph in paragraphs)
    fig.text(
        0.083,
        0.674,
        body_text,
        color=MUTED,
        fontsize=11.8,
        linespacing=1.30,
        ha="left",
        va="top",
    )


def add_metric_cards(
    fig: plt.Figure,
    metric_blocks: list[dict[str, Any]],
    results: dict[str, Any],
    accent: str,
) -> None:
    if len(metric_blocks) != 3:
        raise ValueError("Each panel must contain exactly three metric blocks")

    card_x = (0.055, 0.365, 0.675)
    card_width = 0.27
    for index, (x, block) in enumerate(zip(card_x, metric_blocks, strict=True)):
        if block.get("kind") != "metric":
            raise ValueError(f"Expected metric block, got {block.get('kind')!r}")
        label = require_text(block.get("label"), f"metric {index + 1} label")
        value_spec = block.get("value")
        if not isinstance(value_spec, dict):
            raise TypeError(f"Metric {index + 1} is missing its value specification")
        value = format_metric(results, value_spec)
        note = block.get("note")
        if note is not None:
            note = require_text(note, f"metric {index + 1} note")

        fig.patches.append(
            FancyBboxPatch(
                (x, 0.222),
                card_width,
                0.278,
                boxstyle="round,pad=0.008,rounding_size=0.012",
                transform=fig.transFigure,
                facecolor=WHITE,
                edgecolor=LINE,
                linewidth=1.2,
                zorder=-5,
            )
        )
        fig.patches.append(
            Rectangle(
                (x, 0.486),
                card_width,
                0.014,
                transform=fig.transFigure,
                facecolor=accent if index == 1 else NAVY_2,
                edgecolor="none",
            )
        )
        fig.text(
            x + 0.018,
            0.452,
            wrap_text(label, 18),
            color=MUTED,
            fontsize=12.2,
            fontweight="bold",
            linespacing=1.25,
            ha="left",
            va="top",
        )
        fig.text(
            x + 0.018,
            0.337,
            value,
            color=accent if index == 1 else INK,
            fontsize=31,
            fontweight="bold",
            ha="left",
            va="center",
        )
        if note is not None:
            fig.patches.append(
                FancyBboxPatch(
                    (x + 0.018, 0.252),
                    min(0.205, 0.016 + len(note) * 0.014),
                    0.040,
                    boxstyle="round,pad=0.004,rounding_size=0.009",
                    transform=fig.transFigure,
                    facecolor="#EAF2F7",
                    edgecolor="none",
                    zorder=-2,
                )
            )
            fig.text(
                x + 0.027,
                0.272,
                note,
                color=NAVY_2,
                fontsize=10.5,
                fontweight="bold",
                ha="left",
                va="center",
            )


def add_source(fig: plt.Figure, panel: dict[str, Any], evidence: dict[str, Any]) -> None:
    sources = panel.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"Panel {panel.get('name')!r} must list at least one source")

    labels: list[str] = []
    for source_key in sources:
        if not isinstance(source_key, str) or source_key not in evidence:
            raise KeyError(f"Unknown evidence source key: {source_key!r}")
        source_spec = evidence[source_key]
        if not isinstance(source_spec, dict):
            raise TypeError(f"Evidence entry {source_key!r} must be an object")
        labels.append(require_text(source_spec.get("label"), f"evidence {source_key!r} label"))

    fig.patches.append(
        Rectangle(
            (0.055, 0.174),
            0.89,
            0.0015,
            transform=fig.transFigure,
            facecolor=LINE,
            edgecolor="none",
        )
    )
    exact_label_text = "；".join(labels)
    fig.text(
        0.055,
        0.146,
        "資料來源：" + wrap_text(exact_label_text, 151),
        color=MUTED,
        fontsize=8.0,
        linespacing=1.36,
        ha="left",
        va="top",
    )


def validate_evidence_paths(plan: dict[str, Any]) -> dict[str, Any]:
    evidence = plan.get("evidence")
    if not isinstance(evidence, dict):
        raise TypeError("plan.json must contain an evidence object")
    results_evidence = evidence.get("results")
    if not isinstance(results_evidence, dict):
        raise TypeError("plan.json must contain evidence.results")
    require_text(results_evidence.get("label"), "evidence.results.label")
    return evidence


def render_panel(
    panel: dict[str, Any],
    evidence: dict[str, Any],
    results: dict[str, Any],
    accent: str,
) -> None:
    name = require_text(panel.get("name"), "panel name")
    if name not in EXPECTED_PANEL_NAMES:
        raise ValueError(f"Unexpected panel name: {name!r}")
    title = require_text(panel.get("title"), f"{name} title")
    alt = require_text(panel.get("alt"), f"{name} alt")

    blocks = panel.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != 4:
        raise ValueError(f"Panel {name!r} must contain one text block and three metrics")
    text_block = blocks[0]
    if not isinstance(text_block, dict) or text_block.get("kind") != "text":
        raise ValueError(f"First block in {name!r} must be a text block")
    metric_blocks = blocks[1:]
    if not all(isinstance(block, dict) for block in metric_blocks):
        raise TypeError(f"Metric blocks in {name!r} must be objects")

    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI, facecolor=WHITE)
    add_header(fig, title, accent)
    add_explainer(fig, text_block, accent)
    add_metric_cards(fig, metric_blocks, results, accent)
    add_source(fig, panel, evidence)

    output_path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    with ARTICLE_PATH.open("r", encoding="utf-8") as handle:
        article = handle.read()
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    evidence = validate_evidence_paths(plan)
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("plan.json must contain a panels array")
    panels_by_name: dict[str, dict[str, Any]] = {}
    for panel in panels:
        if not isinstance(panel, dict):
            raise TypeError("Every plan panel must be an object")
        name = require_text(panel.get("name"), "panel name")
        if name in panels_by_name:
            raise ValueError(f"Duplicate panel name: {name!r}")
        panels_by_name[name] = panel
    if set(panels_by_name) != set(EXPECTED_PANEL_NAMES):
        raise ValueError(
            f"Expected panels {EXPECTED_PANEL_NAMES!r}, got {tuple(panels_by_name)!r}"
        )

    os.makedirs(out_dir, exist_ok=True)
    accents = {
        "panel_numbers": BLUE,
        "panel_framework": AMBER,
        "panel_takeaway": TEAL,
    }
    for name in EXPECTED_PANEL_NAMES:
        render_panel(panels_by_name[name], evidence, results, accents[name])


if __name__ == "__main__":
    main()
