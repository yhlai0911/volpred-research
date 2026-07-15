#!/usr/bin/env python3
"""Render the three data-bound K1379 VolPred lazypack panels."""

from __future__ import annotations

import hashlib
import json
import math
import os
import textwrap
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patches


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1379/k1379_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1379/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e81bb0a/runs/lazypack-mile_6e81bb0a/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e81bb0a/runs/lazypack-mile_6e81bb0a/panels/"
    "mile_6e81bb0a_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e81bb0a/runs/lazypack-mile_6e81bb0a/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

INK = "#142033"
MUTED = "#5D6B7E"
LINE = "#D9E1EA"
PALE = "#F4F7FA"
NAVY = "#17365D"
BLUE = "#2878B5"
TEAL = "#16867A"
PALE_TEAL = "#EAF6F3"
RED = "#B5463C"
PALE_RED = "#FAEFED"
AMBER = "#B7791F"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Evidence JSON must be an object: {path}")
    return value


def read_required_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return text


def resolve_path(data: Any, path: str) -> Any:
    """Resolve either RFC 6901 JSON Pointer or the plan's dotted path."""
    if not isinstance(path, str) or not path:
        raise ValueError(f"Invalid evidence path: {path!r}")
    if path.startswith("/"):
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    else:
        parts = path.split(".")

    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field: {path}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {path}") from exc
        else:
            raise KeyError(f"Evidence path crosses a scalar: {path}")
    return current


def format_bound_value(result: dict[str, Any], value_spec: dict[str, Any]) -> str:
    if value_spec.get("source") != "result":
        raise ValueError(f"Unsupported evidence source: {value_spec.get('source')!r}")
    path = value_spec["path"]
    raw = resolve_path(result, path)
    fmt = value_spec["format"]
    if not isinstance(fmt, dict):
        raise TypeError(f"Format must be an object for {path}")

    kind = fmt["kind"]
    if kind == "date":
        if not isinstance(raw, str):
            raise TypeError(f"Expected ISO date string at {path}")
        date.fromisoformat(raw)
        rendered = raw
    elif kind == "integer":
        if isinstance(raw, bool) or not isinstance(raw, Real):
            raise TypeError(f"Expected integer-compatible number at {path}")
        number = float(raw)
        if not math.isfinite(number) or not number.is_integer():
            raise ValueError(f"Expected finite integer-compatible number at {path}")
        rendered = format(int(number), ",d" if fmt.get("thousands", False) else "d")
    elif kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, Real):
            raise TypeError(f"Expected number at {path}")
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError(f"Expected finite number at {path}")
        digits = fmt["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits setting for {path}")
        format_spec = ""
        if fmt.get("show_plus", False):
            format_spec += "+"
        if fmt.get("thousands", False):
            format_spec += ","
        format_spec += f".{digits}f"
        rendered = format(number, format_spec)
    else:
        raise ValueError(f"Unsupported format kind {kind!r} for {path}")

    suffix = fmt.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"Suffix must be text for {path}")
    return rendered + suffix


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan["panels"]
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    matches = [panel for panel in panels if isinstance(panel, dict) and panel.get("name") == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one panel named {name!r}")
    panel = matches[0]
    if panel.get("sources") != ["result"]:
        raise ValueError(f"Panel {name!r} must be bound only to result evidence")
    for key in ("title", "alt", "blocks"):
        if key not in panel:
            raise KeyError(f"Missing plan field for {name}: {key}")
    return panel


def metric_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = panel["blocks"]
    if not isinstance(blocks, list):
        raise TypeError(f"blocks must be a list for {panel['name']}")
    return [block for block in blocks if isinstance(block, dict) and block.get("kind") == "metric"]


def text_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = panel["blocks"]
    if not isinstance(blocks, list):
        raise TypeError(f"blocks must be a list for {panel['name']}")
    return [block for block in blocks if isinstance(block, dict) and block.get("kind") == "text"]


def metric_content(block: dict[str, Any], result: dict[str, Any]) -> tuple[str, str, str]:
    label = block["label"]
    if not isinstance(label, str):
        raise TypeError("Metric label must be text")
    value = format_bound_value(result, block["value"])
    note = block.get("note", "")
    if not isinstance(note, str):
        raise TypeError(f"Metric note must be text: {label}")
    return label, value, note


def rendered_text_body(block: dict[str, Any], result: dict[str, Any]) -> list[str]:
    body = block["body"]
    if not isinstance(body, list):
        raise TypeError(f"Text body must be a list: {block.get('heading')}")
    rendered: list[str] = []
    for item in body:
        if isinstance(item, str):
            rendered.append(item)
            continue
        if not isinstance(item, dict):
            raise TypeError(f"Invalid text item in {block.get('heading')}")
        template = item["template"]
        bindings = item["bindings"]
        if not isinstance(template, str) or not isinstance(bindings, dict):
            raise TypeError(f"Invalid bound text in {block.get('heading')}")
        values = {
            key: format_bound_value(result, spec)
            for key, spec in bindings.items()
            if isinstance(spec, dict)
        }
        if len(values) != len(bindings):
            raise TypeError(f"Invalid binding in {block.get('heading')}")
        rendered.append(template.format(**values))
    return rendered


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


def new_figure() -> plt.Figure:
    return plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor="white")


def rounded_card(
    fig: plt.Figure,
    rect: tuple[float, float, float, float],
    facecolor: str = "white",
    edgecolor: str = LINE,
    linewidth: float = 1.2,
) -> plt.Axes:
    ax = fig.add_axes(rect)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        patches.FancyBboxPatch(
            (0.005, 0.005),
            0.99,
            0.99,
            boxstyle="round,pad=0.002,rounding_size=0.035",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            transform=ax.transAxes,
        )
    )
    return ax


def add_light_header(fig: plt.Figure, title: str, subtitle: str | None = None) -> None:
    ax = fig.add_axes((0.06, 0.835, 0.88, 0.125))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    wrapped_title = wrap_zh(title, 17)
    title_size = 19 if "\n" in wrapped_title else 24
    ax.text(
        0.0,
        0.68 if subtitle else 0.54,
        wrapped_title,
        fontsize=title_size,
        fontweight="bold",
        color=INK,
        va="center",
        linespacing=1.08,
        transform=ax.transAxes,
        clip_on=True,
    )
    if subtitle:
        ax.text(
            0.0,
            0.13,
            subtitle,
            fontsize=12,
            color=MUTED,
            va="center",
            transform=ax.transAxes,
            clip_on=True,
        )
    ax.plot([0.0, 1.0], [0.0, 0.0], color=LINE, linewidth=1.2, transform=ax.transAxes)


def add_footer(fig: plt.Figure, source_label: str) -> None:
    ax = fig.add_axes((0.06, 0.025, 0.88, 0.055))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.plot([0.0, 1.0], [0.92, 0.92], color=LINE, linewidth=1.0, transform=ax.transAxes)
    ax.text(
        0.0,
        0.22,
        f"資料來源：experiment {source_label}",
        fontsize=11,
        color=MUTED,
        va="center",
        transform=ax.transAxes,
        clip_on=True,
    )


def save_panel(fig: plt.Figure, panel: dict[str, Any], source_label: str) -> None:
    destination = Path(out_dir) / f"{panel['name']}.png"
    fig.savefig(
        destination,
        dpi=DPI,
        facecolor="white",
        edgecolor="none",
        metadata={
            "Title": panel["title"],
            "Description": panel["alt"],
            "Source": f"experiment {source_label}",
        },
    )
    plt.close(fig)


def draw_bento_metric(
    fig: plt.Figure,
    rect: tuple[float, float, float, float],
    content: tuple[str, str, str],
    accent: str,
    facecolor: str,
) -> None:
    label, value, note = content
    ax = rounded_card(fig, rect, facecolor=facecolor, edgecolor=LINE)
    ax.plot([0.045, 0.045], [0.16, 0.84], color=accent, linewidth=5, solid_capstyle="round")
    ax.text(0.09, 0.80, label, fontsize=14, color=MUTED, va="top", clip_on=True)
    ax.text(0.09, 0.48, value, fontsize=30, fontweight="bold", color=INK, va="center", clip_on=True)
    if note:
        ax.text(
            0.09,
            0.17,
            wrap_zh(note, 18),
            fontsize=11.5,
            color=accent,
            va="bottom",
            linespacing=1.18,
            clip_on=True,
        )


def render_stable_ranking(panel: dict[str, Any], result: dict[str, Any], source_label: str) -> None:
    metrics = metric_blocks(panel)
    if len(metrics) != 4 or text_blocks(panel):
        raise ValueError("1_stable_ranking must contain exactly four metric blocks")
    fig = new_figure()
    add_light_header(fig, panel["title"], "QLIKE 平均罰分｜越低越好")
    contents = [metric_content(block, result) for block in metrics]
    positions = [
        (0.06, 0.505, 0.42, 0.275),
        (0.52, 0.505, 0.42, 0.275),
        (0.06, 0.155, 0.42, 0.275),
        (0.52, 0.155, 0.42, 0.275),
    ]
    accents = [TEAL, BLUE, NAVY, AMBER]
    fills = [PALE_TEAL, "white", "white", "#FFF8E8"]
    for rect, content, accent, fill in zip(positions, contents, accents, fills, strict=True):
        draw_bento_metric(fig, rect, content, accent, fill)
    add_footer(fig, source_label)
    save_panel(fig, panel, source_label)


def render_unstable_signal(panel: dict[str, Any], result: dict[str, Any], source_label: str) -> None:
    metrics = metric_blocks(panel)
    texts = text_blocks(panel)
    if len(metrics) != 3 or len(texts) != 1:
        raise ValueError("2_unstable_extra_signal must contain three metrics and one text block")
    count = metric_content(metrics[0], result)
    full_sample = metric_content(metrics[1], result)
    diagnostic = metric_content(metrics[2], result)
    date_lines = rendered_text_body(texts[0], result)
    if len(date_lines) != 1:
        raise ValueError("The occurrence-date block must render exactly one paragraph")

    fig = new_figure()
    add_light_header(fig, panel["title"])

    ax = rounded_card(fig, (0.06, 0.275, 0.34, 0.515), facecolor=PALE_RED, edgecolor="#E9C7C2")
    ax.plot([0.06, 0.06], [0.12, 0.88], color=RED, linewidth=6, solid_capstyle="round")
    ax.text(0.14, 0.83, count[0], fontsize=15, color=RED, va="top", clip_on=True)
    ax.text(0.14, 0.57, count[1], fontsize=46, fontweight="bold", color=RED, va="center", clip_on=True)
    ax.add_patch(patches.Circle((0.78, 0.26), 0.10, facecolor="white", edgecolor=RED, linewidth=2))
    ax.text(0.78, 0.25, "!", fontsize=31, fontweight="bold", color=RED, ha="center", va="center", clip_on=True)

    ax = rounded_card(fig, (0.43, 0.57, 0.51, 0.22), facecolor="white")
    ax.text(0.055, 0.79, texts[0]["heading"], fontsize=14, fontweight="bold", color=INK, va="top", clip_on=True)
    ax.text(
        0.055,
        0.49,
        wrap_zh(date_lines[0], 20),
        fontsize=13,
        color=MUTED,
        va="top",
        linespacing=1.25,
        clip_on=True,
    )

    ax = rounded_card(fig, (0.43, 0.305, 0.51, 0.22), facecolor="white")
    ax.text(0.055, 0.80, full_sample[0], fontsize=13, color=MUTED, va="top", clip_on=True)
    ax.text(0.055, 0.49, full_sample[1], fontsize=25, fontweight="bold", color=INK, va="center", clip_on=True)
    ax.text(0.055, 0.14, wrap_zh(full_sample[2], 24), fontsize=11, color=RED, va="bottom", clip_on=True)

    ax = rounded_card(fig, (0.06, 0.115, 0.88, 0.135), facecolor=PALE_TEAL, edgecolor="#C8E5DE")
    ax.text(0.035, 0.72, diagnostic[0], fontsize=11.5, color=TEAL, va="center", clip_on=True)
    ax.text(0.035, 0.25, diagnostic[1], fontsize=22, fontweight="bold", color=INK, va="center", clip_on=True)
    ax.text(
        0.43,
        0.50,
        wrap_zh(diagnostic[2], 14),
        fontsize=10.5,
        color=MUTED,
        va="center",
        linespacing=1.18,
        clip_on=True,
    )

    add_footer(fig, source_label)
    save_panel(fig, panel, source_label)


def draw_compact_metric(
    fig: plt.Figure,
    rect: tuple[float, float, float, float],
    content: tuple[str, str, str],
) -> None:
    label, value, note = content
    if note:
        raise ValueError(f"Unexpected note in compact metric: {label}")
    ax = rounded_card(fig, rect, facecolor=PALE, edgecolor="#D7E0EA")
    ax.text(
        0.07,
        0.82,
        wrap_zh(label, 12),
        fontsize=11,
        color=MUTED,
        va="top",
        linespacing=1.15,
        clip_on=True,
    )
    ax.text(0.07, 0.19, value, fontsize=22, fontweight="bold", color=NAVY, va="bottom", clip_on=True)


def draw_boundary_card(
    fig: plt.Figure,
    rect: tuple[float, float, float, float],
    block: dict[str, Any],
    result: dict[str, Any],
    accent: str,
    facecolor: str,
) -> None:
    heading = block["heading"]
    if not isinstance(heading, str):
        raise TypeError("Boundary heading must be text")
    body = rendered_text_body(block, result)
    if len(body) != 2:
        raise ValueError(f"Boundary block must contain two statements: {heading}")
    ax = rounded_card(fig, rect, facecolor=facecolor, edgecolor=LINE)
    ax.text(0.06, 0.87, heading, fontsize=16, fontweight="bold", color=accent, va="top", clip_on=True)
    ax.plot([0.06, 0.94], [0.72, 0.72], color=LINE, linewidth=1.0)
    for y, statement in zip((0.62, 0.29), body, strict=True):
        ax.add_patch(patches.Circle((0.075, y - 0.012), 0.018, facecolor=accent, edgecolor="none"))
        ax.text(
            0.12,
            y,
            wrap_zh(statement, 18),
            fontsize=13,
            color=INK,
            va="top",
            linespacing=1.30,
            clip_on=True,
        )


def render_honest_boundary(panel: dict[str, Any], result: dict[str, Any], source_label: str) -> None:
    metrics = metric_blocks(panel)
    texts = text_blocks(panel)
    if len(metrics) != 3 or len(texts) != 2:
        raise ValueError("3_honest_boundary must contain three metrics and two text blocks")
    fig = new_figure()

    header = fig.add_axes((0.0, 0.82, 1.0, 0.18))
    header.set_xlim(0, 1)
    header.set_ylim(0, 1)
    header.set_facecolor(NAVY)
    header.set_xticks([])
    header.set_yticks([])
    for spine in header.spines.values():
        spine.set_visible(False)
    header.text(
        0.06,
        0.53,
        wrap_zh(panel["title"], 22),
        fontsize=25,
        fontweight="bold",
        color="white",
        va="center",
        transform=header.transAxes,
        clip_on=True,
    )
    header.plot(
        [0.06, 0.94],
        [0.12, 0.12],
        color="#6683A7",
        linewidth=1.0,
        transform=header.transAxes,
    )

    contents = [metric_content(block, result) for block in metrics]
    metric_positions = [
        (0.06, 0.585, 0.28, 0.185),
        (0.36, 0.585, 0.28, 0.185),
        (0.66, 0.585, 0.28, 0.185),
    ]
    for rect, content in zip(metric_positions, contents, strict=True):
        draw_compact_metric(fig, rect, content)

    draw_boundary_card(fig, (0.06, 0.12, 0.42, 0.405), texts[0], result, TEAL, PALE_TEAL)
    draw_boundary_card(fig, (0.52, 0.12, 0.42, 0.405), texts[1], result, RED, PALE_RED)
    add_footer(fig, source_label)
    save_panel(fig, panel, source_label)


def load_evidence_package() -> tuple[dict[str, Any], dict[str, Any], str]:
    result = load_json(RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    readme = read_required_text(README_PATH)
    _article = read_required_text(ARTICLE_PATH)

    experiment_id = result["experiment_id"]
    if not isinstance(experiment_id, str) or not experiment_id:
        raise TypeError("result.experiment_id must be non-empty text")
    source_label = experiment_id.upper()
    if source_label not in readme.upper():
        raise ValueError("README does not identify the result experiment")

    result_evidence = plan["evidence"]["result"]
    if not isinstance(result_evidence, dict):
        raise TypeError("plan.evidence.result must be an object")
    expected_hash = result_evidence["sha256"]
    if not isinstance(expected_hash, str):
        raise TypeError("plan evidence hash must be text")
    actual_hash = hashlib.sha256(RESULTS_PATH.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(
            f"Result evidence hash mismatch: expected {expected_hash}, got {actual_hash}"
        )
    return result, plan, source_label


def main() -> int:
    result, plan, source_label = load_evidence_package()
    panels = {
        name: panel_by_name(plan, name)
        for name in (
            "1_stable_ranking",
            "2_unstable_extra_signal",
            "3_honest_boundary",
        )
    }
    os.makedirs(out_dir, exist_ok=True)
    render_stable_ranking(panels["1_stable_ranking"], result, source_label)
    render_unstable_signal(panels["2_unstable_extra_signal"], result, source_label)
    render_honest_boundary(panels["3_honest_boundary"], result, source_label)
    return 0


if __name__ == "__main__":
    # The repository layout guard executes this file with runpy and must regain
    # control after rendering so it can report any collected layout violations.
    # Raising SystemExit(0) here would mask those violations as a successful run
    # while the guard deliberately withholds the rejected PNG files.
    main()
