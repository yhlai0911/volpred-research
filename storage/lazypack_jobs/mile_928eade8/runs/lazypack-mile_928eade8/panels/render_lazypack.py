#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the endpoint-sensitivity article."""

from __future__ import annotations

import hashlib
import json
import math
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1697/k1697_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1697/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_928eade8/"
    "runs/lazypack-mile_928eade8/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_928eade8/"
    "runs/lazypack-mile_928eade8/panels/mile_928eade8_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_928eade8/"
    "runs/lazypack-mile_928eade8/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

INK = "#14213D"
MUTED = "#5B6475"
FAINT = "#8A93A3"
RULE = "#DCE2EA"
PAPER = "#FFFFFF"
SOFT = "#F5F7FA"
BLUE = "#1F5A94"
BLUE_SOFT = "#E8F0F8"
TEAL = "#147D75"
TEAL_SOFT = "#E6F3F1"
AMBER = "#A56716"
AMBER_SOFT = "#FAF0DF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_nonempty_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON pointer and fail loudly on any missing field."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {pointer}")

    current = document
    for encoded_part in pointer[1:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing JSON field at {pointer}: {part}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing JSON list item at {pointer}: {part}") from exc
        else:
            raise KeyError(f"Cannot descend through non-container at {pointer}: {part}")
    return current


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected an object for {context}, got {type(value).__name__}")
    return value


def require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected a non-empty string for {context}")
    return value


def require_number(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected a finite number at {pointer}, got {number}")
    return number


def format_metric(raw: Any, fmt: dict[str, Any], pointer: str) -> str:
    kind = require_string(fmt.get("kind"), f"format kind for {pointer}")
    suffix = fmt.get("suffix", "")
    if not isinstance(suffix, str):
        raise TypeError(f"Expected a string suffix for {pointer}")

    number = require_number(raw, pointer)
    if kind == "number":
        digits = fmt.get("digits")
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            raise TypeError(f"Expected a non-negative integer digits value for {pointer}")
        return f"{number:.{digits}f}{suffix}"
    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected an integer-valued number at {pointer}, got {number}")
        return f"{int(number)}{suffix}"
    raise ValueError(f"Unsupported metric format kind for {pointer}: {kind}")


def get_panels(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_panels = plan.get("panels")
    if not isinstance(raw_panels, list):
        raise TypeError("plan.panels must be a list")
    panels: dict[str, dict[str, Any]] = {}
    for raw_panel in raw_panels:
        panel = require_mapping(raw_panel, "panel")
        name = require_string(panel.get("name"), "panel.name")
        if name in panels:
            raise ValueError(f"Duplicate panel name: {name}")
        panels[name] = panel
    for required in ("panel_reproduction", "panel_endpoint_shift", "panel_uncertainty"):
        if required not in panels:
            raise KeyError(f"Missing required panel in strict plan: {required}")
    return panels


def bind_panel(panel: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    title = require_string(panel.get("title"), "panel.title")
    alt = require_string(panel.get("alt"), "panel.alt")
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"blocks must be a list for {panel.get('name')}")

    metrics: list[dict[str, Any]] = []
    texts: list[dict[str, str]] = []
    for raw_block in blocks:
        block = require_mapping(raw_block, f"block in {panel.get('name')}")
        kind = require_string(block.get("kind"), "block.kind")
        if kind == "metric":
            label = require_string(block.get("label"), "metric.label")
            value_spec = require_mapping(block.get("value"), f"value spec for {label}")
            if value_spec.get("source") != "results":
                raise ValueError(f"Unsupported metric source for {label}: {value_spec.get('source')}")
            pointer = require_string(value_spec.get("path"), f"metric path for {label}")
            fmt = require_mapping(value_spec.get("format"), f"metric format for {label}")
            raw_value = json_pointer(results, pointer)
            metrics.append(
                {
                    "label": label,
                    "pointer": pointer,
                    "raw": require_number(raw_value, pointer),
                    "display": format_metric(raw_value, fmt, pointer),
                }
            )
        elif kind == "text":
            heading = require_string(block.get("heading"), "text.heading")
            body = block.get("body")
            if not isinstance(body, list) or not body:
                raise TypeError(f"text.body must be a non-empty list for {heading}")
            body_parts = [require_string(item, f"body text for {heading}") for item in body]
            texts.append({"heading": heading, "body": "".join(body_parts)})
        else:
            raise ValueError(f"Unsupported block kind in strict plan: {kind}")

    return {"title": title, "alt": alt, "metrics": metrics, "texts": texts}


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAPER)
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
    edgecolor: str = RULE,
    linewidth: float = 1.4,
    radius: float = 24,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def wrap_hant(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def draw_header(ax: plt.Axes, title: str, eyebrow: str) -> None:
    ax.text(80, 932, eyebrow, fontsize=14, fontweight="bold", color=BLUE, va="top")
    ax.text(80, 884, title, fontsize=32, fontweight="bold", color=INK, va="top")
    ax.plot([80, 1520], [815, 815], color=RULE, linewidth=1.5)


def draw_footer(ax: plt.Axes, source_label: str) -> None:
    ax.plot([80, 1520], [94, 94], color=RULE, linewidth=1.2)
    ax.text(
        80,
        61,
        f"資料來源：{source_label}",
        fontsize=11.5,
        color=FAINT,
        va="center",
    )


def save_panel(fig: plt.Figure, output_name: str, title: str, alt: str, source: str) -> None:
    output_path = Path(OUT_DIR) / f"{output_name}.png"
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": title, "Description": alt, "Source": source},
    )
    plt.close(fig)


def render_reproduction(bound: dict[str, Any], source_label: str) -> None:
    metrics = bound["metrics"]
    texts = bound["texts"]
    if len(metrics) != 2 or len(texts) != 1:
        raise ValueError("panel_reproduction must contain exactly two metrics and one text block")

    fig, ax = new_canvas()
    draw_header(ax, bound["title"], "重現檢查")

    steps = (
        ("01", "固定同一模型"),
        ("02", "截回舊端點"),
        ("03", "推進共同新端點"),
    )
    step_x = (90, 380, 670)
    for index, ((number, label), x) in enumerate(zip(steps, step_x)):
        rounded_box(ax, x, 535, 245, 170, facecolor=SOFT)
        ax.add_patch(Circle((x + 48, 657), 24, facecolor=BLUE, edgecolor="none"))
        ax.text(x + 48, 657, number, fontsize=12, fontweight="bold", color=PAPER, ha="center", va="center")
        ax.text(
            x + 28,
            594,
            wrap_hant(label, 6),
            fontsize=17,
            fontweight="bold",
            color=INK,
            va="center",
        )
        if index < len(steps) - 1:
            ax.add_patch(
                FancyArrowPatch(
                    (x + 252, 620),
                    (step_x[index + 1] - 8, 620),
                    arrowstyle="-|>",
                    mutation_scale=18,
                    linewidth=1.8,
                    color=BLUE,
                )
            )

    metric_y = (600, 405)
    metric_colors = ((BLUE_SOFT, BLUE), (TEAL_SOFT, TEAL))
    for metric, y, (fill, accent) in zip(metrics, metric_y, metric_colors):
        rounded_box(ax, 1010, y, 510, 160, facecolor=fill, edgecolor=accent, linewidth=1.8)
        ax.text(1050, y + 116, metric["label"], fontsize=15, fontweight="bold", color=accent, va="center")
        ax.text(1050, y + 54, metric["display"], fontsize=43, fontweight="bold", color=INK, va="center")

    text_block = texts[0]
    rounded_box(ax, 90, 165, 1400, 200, facecolor=PAPER, edgecolor=RULE, linewidth=1.4)
    ax.add_patch(Rectangle((90, 165), 12, 200, facecolor=TEAL, edgecolor="none"))
    ax.text(135, 315, text_block["heading"], fontsize=19, fontweight="bold", color=TEAL, va="top")
    ax.text(
        135,
        260,
        wrap_hant(text_block["body"], 36),
        fontsize=18,
        color=INK,
        va="top",
        linespacing=1.45,
    )

    draw_footer(ax, source_label)
    save_panel(fig, "panel_reproduction", bound["title"], bound["alt"], source_label)


def draw_gamma_card(
    ax: plt.Axes,
    x: float,
    metric: dict[str, Any],
    max_gamma: float,
    *,
    fill: str,
    accent: str,
) -> None:
    rounded_box(ax, x, 515, 420, 275, facecolor=fill, edgecolor=accent, linewidth=1.6)
    ax.text(x + 34, 744, wrap_hant(metric["label"], 12), fontsize=16, fontweight="bold", color=accent, va="top")
    ax.text(x + 34, 646, metric["display"], fontsize=46, fontweight="bold", color=INK, va="center")
    ax.add_patch(Rectangle((x + 34, 558), 340, 16, facecolor=PAPER, edgecolor=RULE, linewidth=0.8))
    bar_width = 340 * metric["raw"] / max_gamma
    ax.add_patch(Rectangle((x + 34, 558), bar_width, 16, facecolor=accent, edgecolor="none"))


def render_endpoint_shift(bound: dict[str, Any], source_label: str) -> None:
    metrics = bound["metrics"]
    texts = bound["texts"]
    if len(metrics) != 3 or len(texts) != 1:
        raise ValueError("panel_endpoint_shift must contain exactly three metrics and one text block")
    if metrics[0]["raw"] <= 0 or metrics[1]["raw"] <= 0:
        raise ValueError("Gamma comparison values must be positive for the data-bound bars")

    fig, ax = new_canvas()
    draw_header(ax, bound["title"], "窗口端點比較")

    gamma_max = max(metrics[0]["raw"], metrics[1]["raw"])
    draw_gamma_card(ax, 80, metrics[0], gamma_max, fill=AMBER_SOFT, accent=AMBER)
    draw_gamma_card(ax, 530, metrics[1], gamma_max, fill=BLUE_SOFT, accent=BLUE)

    rounded_box(ax, 980, 515, 540, 275, facecolor=TEAL_SOFT, edgecolor=TEAL, linewidth=1.6)
    ax.text(1018, 744, wrap_hant(metrics[2]["label"], 15), fontsize=16, fontweight="bold", color=TEAL, va="top")
    ax.text(1018, 630, metrics[2]["display"], fontsize=52, fontweight="bold", color=INK, va="center")
    ax.text(1018, 564, "穩健統計值", fontsize=14, color=MUTED, va="center")

    text_block = texts[0]
    rounded_box(ax, 80, 155, 1440, 300, facecolor=SOFT, edgecolor=RULE, linewidth=1.4)
    ax.text(125, 397, text_block["heading"], fontsize=21, fontweight="bold", color=INK, va="top")
    ax.text(
        125,
        330,
        wrap_hant(text_block["body"], 37),
        fontsize=20,
        color=MUTED,
        va="top",
        linespacing=1.5,
    )

    draw_footer(ax, source_label)
    save_panel(fig, "panel_endpoint_shift", bound["title"], bound["alt"], source_label)


def render_uncertainty(bound: dict[str, Any], source_label: str) -> None:
    metrics = bound["metrics"]
    texts = bound["texts"]
    if len(metrics) != 2 or len(texts) != 1:
        raise ValueError("panel_uncertainty must contain exactly two metrics and one text block")
    if metrics[0]["raw"] <= 0 or metrics[1]["raw"] < 0 or metrics[1]["raw"] > metrics[0]["raw"]:
        raise ValueError("Convergence counts are inconsistent")

    fig, ax = new_canvas()
    draw_header(ax, bound["title"], "讀者結論")

    rounded_box(ax, 80, 165, 690, 610, facecolor=INK, edgecolor=INK, linewidth=0)
    ax.text(130, 716, "最佳化診斷", fontsize=16, fontweight="bold", color="#AFC6DE", va="top")
    ax.text(130, 645, metrics[0]["label"], fontsize=16, color=PAPER, va="top")
    ax.text(130, 578, metrics[0]["display"], fontsize=49, fontweight="bold", color=PAPER, va="top")
    ax.plot([130, 720], [478, 478], color="#52647C", linewidth=1.4)
    ax.text(130, 430, metrics[1]["label"], fontsize=16, color=PAPER, va="top")
    ax.text(130, 363, metrics[1]["display"], fontsize=49, fontweight="bold", color="#8ED8CE", va="top")
    progress_width = 590 * metrics[1]["raw"] / metrics[0]["raw"]
    ax.add_patch(Rectangle((130, 244), 590, 18, facecolor="#52647C", edgecolor="none"))
    ax.add_patch(Rectangle((130, 244), progress_width, 18, facecolor="#8ED8CE", edgecolor="none"))
    ax.text(130, 207, "起點收斂情形", fontsize=13, color="#AFC6DE", va="center")

    text_block = texts[0]
    ax.text(850, 714, text_block["heading"], fontsize=25, fontweight="bold", color=TEAL, va="top")
    ax.text(
        850,
        620,
        wrap_hant(text_block["body"], 15),
        fontsize=21,
        color=INK,
        va="top",
        linespacing=1.55,
    )
    ax.plot([850, 1495], [280, 280], color=RULE, linewidth=1.4)
    ax.text(850, 235, "計算穩定 ≠ 端點穩定", fontsize=19, fontweight="bold", color=BLUE, va="center")

    draw_footer(ax, source_label)
    save_panel(fig, "panel_uncertainty", bound["title"], bound["alt"], source_label)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    results = require_mapping(load_json(RESULTS_PATH), "results evidence")
    plan = require_mapping(load_json(PLAN_PATH), "strict plan")
    require_nonempty_text(README_PATH)
    require_nonempty_text(ARTICLE_PATH)

    evidence = require_mapping(plan.get("evidence"), "plan.evidence")
    results_evidence = require_mapping(evidence.get("results"), "plan.evidence.results")
    source_label = require_string(results_evidence.get("label"), "plan.evidence.results.label")
    expected_sha256 = require_string(results_evidence.get("sha256"), "plan.evidence.results.sha256")
    actual_sha256 = hashlib.sha256(RESULTS_PATH.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Results evidence SHA-256 does not match strict plan: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    panels = get_panels(plan)
    reproduction = bind_panel(panels["panel_reproduction"], results)
    endpoint_shift = bind_panel(panels["panel_endpoint_shift"], results)
    uncertainty = bind_panel(panels["panel_uncertainty"], results)

    render_reproduction(reproduction, source_label)
    render_endpoint_shift(endpoint_shift, source_label)
    render_uncertainty(uncertainty, source_label)


if __name__ == "__main__":
    main()
