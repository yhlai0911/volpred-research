#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_e9325f74 article."""

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
    "mile_e9325f74/runs/lazypack-mile_e9325f74/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1680/K1680_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_e9325f74/runs/lazypack-mile_e9325f74/panels/"
    "mile_e9325f74_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_e9325f74/runs/lazypack-mile_e9325f74/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

NAVY = "#12243A"
INK = "#172538"
MUTED = "#536476"
PALE = "#F3F6F9"
LINE = "#D9E1E8"
TEAL = "#087F8C"
TEAL_PALE = "#E5F3F3"
AMBER = "#C27A19"
AMBER_PALE = "#F9F0E2"
RED = "#B44845"
RED_PALE = "#F8EAE9"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{context} 必須是 JSON object")
    return value


def require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{context} 必須是 JSON array")
    return value


def require_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{context} 必須是非空字串")
    return value


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style pointer and fail loudly on any missing field."""
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"無效 JSON pointer: {pointer!r}")

    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"results 缺少欄位 {pointer!r}（停在 {token!r}）")
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"results 無法解析欄位 {pointer!r}") from exc
        else:
            raise KeyError(f"results 欄位 {pointer!r} 穿越了非容器值")
    return current


def format_metric(raw_value: Any, format_spec: Any, pointer: str) -> str:
    spec = require_mapping(format_spec, f"{pointer} format")
    if spec.get("kind") != "number":
        raise ValueError(f"{pointer} 僅支援 number format")
    digits = spec.get("digits")
    if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
        raise TypeError(f"{pointer} digits 必須是非負整數")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise TypeError(f"{pointer} 必須是數值，實際為 {type(raw_value).__name__}")
    number = float(raw_value)
    if not math.isfinite(number):
        raise ValueError(f"{pointer} 必須是有限數值")
    return f"{number:.{digits}f}"


def wrap_zh(text: str, width: int) -> str:
    """Deterministically wrap Chinese or Latin text without relying on auto-layout."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        lines.extend(
            textwrap.wrap(
                paragraph,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
            or [""]
        )
    return "\n".join(lines)


def add_panel_icon(ax: plt.Axes, panel_name: str) -> None:
    """Add restrained geometric icons; they carry no quantitative meaning."""
    x, y = 0.075, 0.705
    if panel_name == "panel_question":
        ax.add_patch(
            Circle(
                (x, y),
                0.024,
                transform=ax.transAxes,
                facecolor="none",
                edgecolor=TEAL,
                linewidth=3,
            )
        )
        ax.plot(
            [x + 0.017, x + 0.038],
            [y - 0.017, y - 0.038],
            color=TEAL,
            linewidth=3,
            transform=ax.transAxes,
            solid_capstyle="round",
        )
    elif panel_name == "panel_result":
        for offset, length in ((0.021, 0.043), (0.0, 0.061), (-0.021, 0.030)):
            ax.plot(
                [x - 0.028, x - 0.028 + length],
                [y + offset, y + offset],
                color=AMBER,
                linewidth=5,
                transform=ax.transAxes,
                solid_capstyle="round",
            )
    elif panel_name == "panel_takeaway":
        ax.add_patch(
            FancyBboxPatch(
                (x - 0.029, y - 0.034),
                0.058,
                0.068,
                boxstyle="round,pad=0.004,rounding_size=0.012",
                transform=ax.transAxes,
                facecolor="none",
                edgecolor=RED,
                linewidth=3,
            )
        )
        ax.plot(
            [x - 0.015, x - 0.002, x + 0.019],
            [y, y - 0.014, y + 0.016],
            color=RED,
            linewidth=3,
            transform=ax.transAxes,
            solid_capstyle="round",
        )
    else:
        raise ValueError(f"不支援的 panel name: {panel_name}")


def draw_metric_card(
    ax: plt.Axes,
    *,
    y: float,
    label: str,
    value: str,
    accent: str,
    fill: str,
) -> None:
    x, width, height = 0.585, 0.355, 0.155
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.008,rounding_size=0.014",
            transform=ax.transAxes,
            facecolor=fill,
            edgecolor=LINE,
            linewidth=1.1,
        )
    )
    ax.add_patch(
        Rectangle(
            (x, y),
            0.008,
            height,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    ax.text(
        x + 0.032,
        y + 0.112,
        wrap_zh(label, 20),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=14,
        color=MUTED,
        linespacing=1.15,
    )
    ax.text(
        x + 0.032,
        y + 0.049,
        value,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=32,
        fontweight="bold",
        color=accent,
    )


def render_panel(
    panel: dict[str, Any],
    *,
    results: dict[str, Any],
    source_label: str,
) -> None:
    name = require_text(panel.get("name"), "panel.name")
    title = require_text(panel.get("title"), f"{name}.title")
    alt = require_text(panel.get("alt"), f"{name}.alt")
    sources = require_list(panel.get("sources"), f"{name}.sources")
    if sources != ["results"]:
        raise ValueError(f"{name}.sources 必須精確等於 ['results']")

    blocks = require_list(panel.get("blocks"), f"{name}.blocks")
    text_blocks = [block for block in blocks if block.get("kind") == "text"]
    metric_blocks = [block for block in blocks if block.get("kind") == "metric"]
    if len(text_blocks) != 1 or len(metric_blocks) != 3:
        raise ValueError(f"{name} 必須恰有一個文字區塊與三個數據區塊")

    text_block = require_mapping(text_blocks[0], f"{name}.text_block")
    heading = require_text(text_block.get("heading"), f"{name}.heading")
    body = require_list(text_block.get("body"), f"{name}.body")
    if len(body) != 2:
        raise ValueError(f"{name}.body 必須恰有兩段")
    body_texts = [
        require_text(paragraph, f"{name}.body[{index}]")
        for index, paragraph in enumerate(body)
    ]

    bound_metrics: list[tuple[str, str]] = []
    for index, raw_block in enumerate(metric_blocks):
        block = require_mapping(raw_block, f"{name}.metric[{index}]")
        label = require_text(block.get("label"), f"{name}.metric[{index}].label")
        value_spec = require_mapping(
            block.get("value"), f"{name}.metric[{index}].value"
        )
        if value_spec.get("source") != "results":
            raise ValueError(f"{name}.metric[{index}] 必須引用 results")
        pointer = require_text(
            value_spec.get("path"), f"{name}.metric[{index}].path"
        )
        raw_value = resolve_json_pointer(results, pointer)
        rendered_value = format_metric(raw_value, value_spec.get("format"), pointer)
        bound_metrics.append((label, rendered_value))

    palette = {
        "panel_question": (TEAL, TEAL_PALE),
        "panel_result": (AMBER, AMBER_PALE),
        "panel_takeaway": (RED, RED_PALE),
    }
    if name not in palette:
        raise ValueError(f"不支援的 panel name: {name}")
    accent, card_fill = palette[name]

    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=WHITE)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(
        Rectangle((0, 0.79), 1, 0.21, transform=ax.transAxes, color=NAVY)
    )
    ax.add_patch(
        Rectangle((0.055, 0.845), 0.008, 0.085, transform=ax.transAxes, color=accent)
    )
    ax.text(
        0.085,
        0.888,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=28,
        fontweight="bold",
        color=WHITE,
    )

    add_panel_icon(ax, name)
    ax.text(
        0.12,
        0.715,
        heading,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=21,
        fontweight="bold",
        color=INK,
    )
    ax.plot(
        [0.06, 0.53],
        [0.655, 0.655],
        transform=ax.transAxes,
        color=LINE,
        linewidth=1.2,
    )

    paragraph_y = (0.60, 0.40)
    for y, paragraph in zip(paragraph_y, body_texts, strict=True):
        ax.text(
            0.06,
            y,
            wrap_zh(paragraph, 25),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=16,
            color=INK,
            linespacing=1.55,
        )

    for y, (label, value) in zip(
        (0.60, 0.39, 0.18), bound_metrics, strict=True
    ):
        draw_metric_card(
            ax,
            y=y,
            label=label,
            value=value,
            accent=accent,
            fill=card_fill,
        )

    ax.plot(
        [0.055, 0.945],
        [0.105, 0.105],
        transform=ax.transAxes,
        color=LINE,
        linewidth=1,
    )
    source_text = f"資料來源：{source_label}"
    ax.text(
        0.055,
        0.067,
        wrap_zh(source_text, 112),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=8.5,
        color=MUTED,
        linespacing=1.2,
    )

    output_path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        metadata={
            "Title": title,
            "Description": alt,
            "Source": source_label,
        },
    )
    plt.close(fig)


def main() -> None:
    plan = require_mapping(load_json(PLAN_PATH), "plan")
    results = require_mapping(load_json(RESULTS_PATH), "results")
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    if not article.strip():
        raise ValueError(f"文章 evidence 是空檔案：{ARTICLE_PATH}")

    evidence = require_mapping(plan.get("evidence"), "plan.evidence")
    result_evidence = require_mapping(evidence.get("results"), "plan.evidence.results")
    source_label = require_text(
        result_evidence.get("label"), "plan.evidence.results.label"
    )
    panels = require_list(plan.get("panels"), "plan.panels")
    expected_names = ["panel_question", "panel_result", "panel_takeaway"]
    actual_names = [
        require_text(require_mapping(panel, "panel").get("name"), "panel.name")
        for panel in panels
    ]
    if actual_names != expected_names:
        raise ValueError(
            f"panel 順序或名稱不符：預期 {expected_names!r}，實際 {actual_names!r}"
        )

    os.makedirs(out_dir, exist_ok=True)
    for raw_panel in panels:
        render_panel(
            require_mapping(raw_panel, "panel"),
            results=results,
            source_label=source_label,
        )


if __name__ == "__main__":
    main()
