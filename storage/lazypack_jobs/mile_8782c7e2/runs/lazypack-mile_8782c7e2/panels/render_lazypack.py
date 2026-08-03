#!/usr/bin/env python3
"""Render the four evidence-bound PNG panels for mile_8782c7e2."""

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
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_8782c7e2/runs/lazypack-mile_8782c7e2/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1744/K1744_results.json"
)
MANIFEST_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1744/raw_cache_manifest.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_8782c7e2/runs/lazypack-mile_8782c7e2/panels/"
    "mile_8782c7e2_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_8782c7e2/runs/lazypack-mile_8782c7e2/panels"
)

FIG_W_PX = 1600
FIG_H_PX = 1000
DPI = 150

INK = "#12263A"
NAVY = "#173B57"
BLUE = "#147D92"
TEAL = "#18A0A8"
PALE_BLUE = "#EAF4F7"
PALE_GOLD = "#FFF5DC"
GOLD = "#C98B22"
PALE_RED = "#FCEEEB"
RED = "#B85245"
MUTED = "#536575"
LINE = "#D9E3E8"
PANEL_BG = "#F7FAFB"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    """Load a required JSON object; malformed or missing evidence must raise."""
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object at {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required field {context}/{key}")
    return mapping[key]


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901-style JSON Pointer and raise on any miss."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON Pointer: {pointer!r}")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing JSON Pointer field {pointer!r} at {part!r}")
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit():
                raise TypeError(f"Expected list index in JSON Pointer {pointer!r}")
            index = int(part)
            if index >= len(current):
                raise IndexError(f"List index out of range in JSON Pointer {pointer!r}")
            current = current[index]
        else:
            raise TypeError(f"Cannot descend through scalar in JSON Pointer {pointer!r}")
    return current


def expect_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {context}")
    return value


def expect_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected list at {context}")
    return value


def expect_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty text at {context}")
    return value


def verify_inputs(
    plan: dict[str, Any], results: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """Confirm that the files still match the evidence package locked by the plan."""
    evidence = expect_dict(require(plan, "evidence", "plan"), "plan/evidence")
    paths = {"results": RESULTS_PATH, "manifest": MANIFEST_PATH}
    documents = {"results": results, "manifest": manifest}
    for source_name, source_path in paths.items():
        spec = expect_dict(
            require(evidence, source_name, "plan/evidence"),
            f"plan/evidence/{source_name}",
        )
        declared_hash = expect_text(
            require(spec, "sha256", f"plan/evidence/{source_name}"),
            f"plan/evidence/{source_name}/sha256",
        )
        expect_text(
            require(spec, "label", f"plan/evidence/{source_name}"),
            f"plan/evidence/{source_name}/label",
        )
        actual_hash = sha256_file(source_path)
        if actual_hash != declared_hash:
            raise ValueError(
                f"Evidence hash mismatch for {source_name}: "
                f"plan={declared_hash}, actual={actual_hash}"
            )
        if not isinstance(documents[source_name], dict):
            raise TypeError(f"Evidence {source_name} is not a JSON object")

    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"Article evidence is empty: {ARTICLE_PATH}")

    # The conclusion panel depends on these actual counts being unknown, not zero.
    for pointer in (
        "/data/sample/eligible_proxy_events",
        "/data/sample/nonzero_exposure_months",
        "/data/sample/effective_common_months",
    ):
        if resolve_pointer(results, pointer) is not None:
            raise ValueError(f"Expected an unknown/null actual value at {pointer}")


def wrap_text(text: str, width: int) -> str:
    return textwrap.fill(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )


def wrap_paragraphs(lines: list[Any], width: int) -> str:
    rendered: list[str] = []
    for index, line in enumerate(lines):
        sentence = expect_text(line, f"body/{index}")
        rendered.append(
            textwrap.fill(
                sentence,
                width=width,
                initial_indent="• ",
                subsequent_indent="  ",
                break_long_words=True,
                break_on_hyphens=False,
            )
        )
    return "\n".join(rendered)


def rounded_box(
    fig: plt.Figure,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = LINE,
    linewidth: float = 1.0,
    radius: float = 0.012,
) -> None:
    fig.add_artist(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.006,rounding_size={radius}",
            transform=fig.transFigure,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            clip_on=False,
        )
    )


def new_figure(title: str) -> plt.Figure:
    fig = plt.figure(
        figsize=(FIG_W_PX / DPI, FIG_H_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    fig.add_artist(
        Rectangle(
            (0, 0.835),
            1,
            0.165,
            transform=fig.transFigure,
            facecolor=NAVY,
            edgecolor="none",
        )
    )
    fig.add_artist(
        Rectangle(
            (0.052, 0.865),
            0.009,
            0.085,
            transform=fig.transFigure,
            facecolor=TEAL,
            edgecolor="none",
        )
    )
    fig.text(
        0.076,
        0.908,
        title,
        ha="left",
        va="center",
        color=WHITE,
        fontsize=29,
        fontweight="bold",
    )
    return fig


def draw_intro(fig: plt.Figure, block: dict[str, Any]) -> None:
    rounded_box(fig, 0.065, 0.674, 0.87, 0.115, facecolor=PALE_BLUE, edgecolor="#C7E0E6")
    fig.add_artist(
        Circle(
            (0.091, 0.731),
            0.011,
            transform=fig.transFigure,
            facecolor=TEAL,
            edgecolor="none",
        )
    )
    heading = expect_text(require(block, "heading", "text block"), "text block/heading")
    body = expect_list(require(block, "body", "text block"), "text block/body")
    fig.text(
        0.115,
        0.756,
        heading,
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.115,
        0.716,
        wrap_paragraphs(body, 62),
        ha="left",
        va="center",
        fontsize=11.5,
        linespacing=1.35,
        color=MUTED,
    )


def metric_value(
    block: dict[str, Any], evidence_documents: dict[str, dict[str, Any]]
) -> str:
    value_spec = expect_dict(require(block, "value", "metric block"), "metric block/value")
    source_name = expect_text(
        require(value_spec, "source", "metric block/value"),
        "metric block/value/source",
    )
    if source_name not in evidence_documents:
        raise KeyError(f"Unknown metric evidence source: {source_name}")
    pointer = expect_text(
        require(value_spec, "path", "metric block/value"),
        "metric block/value/path",
    )
    format_spec = expect_dict(
        require(value_spec, "format", "metric block/value"),
        "metric block/value/format",
    )
    format_kind = expect_text(
        require(format_spec, "kind", "metric block/value/format"),
        "metric block/value/format/kind",
    )
    raw_value = resolve_pointer(evidence_documents[source_name], pointer)
    if format_kind != "integer":
        raise ValueError(f"Unsupported metric format: {format_kind}")
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise TypeError(f"Expected integer at {source_name}:{pointer}, got {raw_value!r}")
    return f"{raw_value:,}"


def draw_metric_cards(
    fig: plt.Figure,
    blocks: list[dict[str, Any]],
    evidence_documents: dict[str, dict[str, Any]],
) -> None:
    if len(blocks) != 3:
        raise ValueError("Professional metric row requires exactly three metric blocks")
    card_x = (0.065, 0.363, 0.661)
    accents = (BLUE, TEAL, GOLD)
    backgrounds = ("#F2F8FA", "#EFF9F8", "#FFF8E8")
    for index, (block, x) in enumerate(zip(blocks, card_x, strict=True)):
        rounded_box(
            fig,
            x,
            0.252,
            0.274,
            0.355,
            facecolor=backgrounds[index],
            edgecolor=LINE,
        )
        fig.add_artist(
            Rectangle(
                (x, 0.582),
                0.274,
                0.025,
                transform=fig.transFigure,
                facecolor=accents[index],
                edgecolor="none",
            )
        )
        value = metric_value(block, evidence_documents)
        label = expect_text(require(block, "label", "metric block"), "metric block/label")
        note_value = block.get("note")
        if note_value is not None and not isinstance(note_value, str):
            raise TypeError("Metric note must be text when present")
        fig.text(
            x + 0.022,
            0.525,
            value,
            ha="left",
            va="center",
            fontsize=36,
            fontweight="bold",
            color=accents[index],
        )
        fig.text(
            x + 0.022,
            0.455,
            # Heiti TC CJK glyphs are wider than textwrap's character-count
            # estimate.  Fourteen characters preserve the card's right inset.
            wrap_text(label, 14),
            ha="left",
            va="top",
            fontsize=13,
            fontweight="bold",
            linespacing=1.28,
            color=INK,
        )
        if note_value:
            fig.text(
                x + 0.022,
                0.345,
                wrap_text(note_value, 21),
                ha="left",
                va="top",
                fontsize=9.5,
                linespacing=1.34,
                color=MUTED,
            )


def draw_source_footer(fig: plt.Figure, panel: dict[str, Any], plan: dict[str, Any]) -> None:
    evidence_specs = expect_dict(require(plan, "evidence", "plan"), "plan/evidence")
    source_names = expect_list(require(panel, "sources", "panel"), "panel/sources")
    labels: list[str] = []
    for source_name_value in source_names:
        source_name = expect_text(source_name_value, "panel/sources/item")
        source_spec = expect_dict(
            require(evidence_specs, source_name, "plan/evidence"),
            f"plan/evidence/{source_name}",
        )
        labels.append(
            expect_text(
                require(source_spec, "label", f"plan/evidence/{source_name}"),
                f"plan/evidence/{source_name}/label",
            )
        )
    if not labels:
        raise ValueError("Every panel must declare at least one evidence source")

    fig.add_artist(
        Rectangle(
            (0, 0),
            1,
            0.172,
            transform=fig.transFigure,
            facecolor=PANEL_BG,
            edgecolor="none",
        )
    )
    fig.add_artist(
        Rectangle(
            (0.065, 0.149),
            0.87,
            0.002,
            transform=fig.transFigure,
            facecolor=LINE,
            edgecolor="none",
        )
    )
    footer = "資料來源：" + "\n".join(wrap_text(label, 154) for label in labels)
    fig.text(
        0.065,
        0.128,
        footer,
        ha="left",
        va="top",
        fontsize=6.8,
        linespacing=1.28,
        color=MUTED,
    )


def draw_takeaway(
    fig: plt.Figure,
    panel: dict[str, Any],
    evidence_documents: dict[str, dict[str, Any]],
) -> None:
    blocks_raw = expect_list(require(panel, "blocks", "takeaway panel"), "takeaway panel/blocks")
    blocks = [expect_dict(block, "takeaway panel/block") for block in blocks_raw]
    if len(blocks) != 4 or [block.get("kind") for block in blocks] != [
        "text",
        "text",
        "metric",
        "text",
    ]:
        raise ValueError("Unexpected takeaway panel block structure")

    top_positions = ((0.065, PALE_RED, RED), (0.51, PALE_BLUE, BLUE))
    for block, (x, background, accent) in zip(blocks[:2], top_positions, strict=True):
        rounded_box(fig, x, 0.585, 0.425, 0.19, facecolor=background, edgecolor=LINE)
        fig.add_artist(
            Circle(
                (x + 0.027, 0.733),
                0.010,
                transform=fig.transFigure,
                facecolor=accent,
                edgecolor="none",
            )
        )
        heading = expect_text(require(block, "heading", "takeaway text"), "takeaway/heading")
        body = expect_list(require(block, "body", "takeaway text"), "takeaway/body")
        fig.text(
            x + 0.048,
            0.735,
            heading,
            ha="left",
            va="center",
            fontsize=15,
            fontweight="bold",
            color=INK,
        )
        fig.text(
            x + 0.025,
            0.690,
            wrap_paragraphs(body, 31),
            ha="left",
            va="top",
            fontsize=10.5,
            linespacing=1.34,
            color=MUTED,
        )

    metric = blocks[2]
    rounded_box(fig, 0.065, 0.235, 0.278, 0.295, facecolor=PALE_GOLD, edgecolor="#E8D6A8")
    fig.add_artist(
        Rectangle(
            (0.065, 0.505),
            0.278,
            0.025,
            transform=fig.transFigure,
            facecolor=GOLD,
            edgecolor="none",
        )
    )
    value = metric_value(metric, evidence_documents)
    label = expect_text(require(metric, "label", "takeaway metric"), "takeaway metric/label")
    note = expect_text(require(metric, "note", "takeaway metric"), "takeaway metric/note")
    fig.text(
        0.087,
        0.453,
        value,
        ha="left",
        va="center",
        fontsize=34,
        fontweight="bold",
        color=GOLD,
    )
    fig.text(
        0.184,
        0.453,
        "門檻值",
        ha="left",
        va="center",
        fontsize=11,
        fontweight="bold",
        color=GOLD,
    )
    fig.text(
        0.087,
        0.395,
        wrap_text(label, 17),
        ha="left",
        va="top",
        fontsize=12,
        fontweight="bold",
        linespacing=1.25,
        color=INK,
    )
    fig.text(
        0.087,
        0.305,
        wrap_text(note, 20),
        ha="left",
        va="top",
        fontsize=9.5,
        linespacing=1.28,
        color=MUTED,
    )

    final_text = blocks[3]
    rounded_box(fig, 0.375, 0.235, 0.56, 0.295, facecolor="#F3F7F9", edgecolor=LINE)
    heading = expect_text(
        require(final_text, "heading", "takeaway final text"),
        "takeaway final text/heading",
    )
    body = expect_list(
        require(final_text, "body", "takeaway final text"),
        "takeaway final text/body",
    )
    fig.text(
        0.401,
        0.475,
        heading,
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.401,
        0.430,
        # Keep full-width Chinese bullets within the narrower text inset.
        wrap_paragraphs(body, 36),
        ha="left",
        va="top",
        fontsize=11,
        linespacing=1.4,
        color=MUTED,
    )


def render_panel(
    panel: dict[str, Any],
    plan: dict[str, Any],
    evidence_documents: dict[str, dict[str, Any]],
) -> None:
    name = expect_text(require(panel, "name", "panel"), "panel/name")
    title = expect_text(require(panel, "title", "panel"), "panel/title")
    alt = expect_text(require(panel, "alt", "panel"), "panel/alt")
    fig = new_figure(title)

    if name == "panel_takeaway":
        draw_takeaway(fig, panel, evidence_documents)
    else:
        blocks_raw = expect_list(require(panel, "blocks", "panel"), "panel/blocks")
        blocks = [expect_dict(block, "panel/block") for block in blocks_raw]
        if len(blocks) != 4 or blocks[0].get("kind") != "text":
            raise ValueError(f"Unexpected block structure for {name}")
        metric_blocks = blocks[1:]
        if any(block.get("kind") != "metric" for block in metric_blocks):
            raise ValueError(f"Expected three metric blocks for {name}")
        draw_intro(fig, blocks[0])
        draw_metric_cards(fig, metric_blocks, evidence_documents)

    draw_source_footer(fig, panel, plan)
    output_path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def main() -> None:
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    manifest = load_json(MANIFEST_PATH)
    verify_inputs(plan, results, manifest)

    panels_raw = expect_list(require(plan, "panels", "plan"), "plan/panels")
    panels = [expect_dict(panel, "plan/panels/item") for panel in panels_raw]
    expected_names = {
        "panel_concept",
        "panel_method",
        "panel_results",
        "panel_takeaway",
    }
    actual_names = {
        expect_text(require(panel, "name", "panel"), "panel/name") for panel in panels
    }
    if actual_names != expected_names or len(panels) != len(expected_names):
        raise ValueError(
            f"Expected exactly {sorted(expected_names)}, got {sorted(actual_names)}"
        )

    os.makedirs(OUT_DIR, exist_ok=True)
    evidence_documents = {"results": results, "manifest": manifest}
    for panel in panels:
        render_panel(panel, plan, evidence_documents)


if __name__ == "__main__":
    main()
