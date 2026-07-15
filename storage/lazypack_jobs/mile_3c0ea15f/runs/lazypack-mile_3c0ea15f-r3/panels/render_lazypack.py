#!/usr/bin/env python3
"""Render the three data-bound lazypack panels for the sequence-risk article.

This program deliberately reads all copy, formats, source labels, and displayed
statistics from the strict evidence package. Missing or malformed evidence is a
hard error so that a caller never receives a plausible-looking fabricated chart.
"""

from __future__ import annotations

import json
import os
import textwrap
from numbers import Real
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f-r3/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1410/k1410_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f-r3/panels/"
    "mile_3c0ea15f_article.md"
)
OUT_DIR = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3c0ea15f/runs/lazypack-mile_3c0ea15f-r3/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#172033"
MUTED = "#5E697A"
FAINT = "#8A94A3"
PAPER = "#F6F7F9"
WHITE = "#FFFFFF"
NAVY = "#12233F"
BLUE = "#2B66B1"
BLUE_SOFT = "#E8F0FA"
TEAL = "#167D76"
TEAL_SOFT = "#E2F2EF"
RED = "#B84343"
RED_SOFT = "#F8E7E5"
GOLD = "#B77A20"
GOLD_SOFT = "#F5EBD8"
LINE = "#D8DEE8"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_path(data: Any, path: str) -> Any:
    """Resolve either a strict JSON Pointer or the plan's dotted path syntax."""
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
                raise KeyError(f"Missing evidence field at {path!r}: {part!r}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Invalid list index in evidence path {path!r}: {part!r}") from exc
        else:
            raise KeyError(f"Evidence path {path!r} descends into a scalar at {part!r}")
    return current


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object for {context}, got {type(value).__name__}")
    return value


def require_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty text for {context}")
    return value


def require_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"Expected numeric evidence at {path!r}, got {type(value).__name__}")
    return float(value)


def format_value(raw: Any, fmt: Any, path: str) -> str:
    spec = require_mapping(fmt, f"format for {path}")
    kind = spec.get("kind")
    digits = spec.get("digits")
    if not isinstance(digits, int) or isinstance(digits, bool) or digits < 0:
        raise TypeError(f"Invalid digits for {path!r}: {digits!r}")

    number = require_number(raw, path)
    if kind == "number":
        return f"{number:,.{digits}f}"
    if kind == "percent":
        if not 0.0 <= number <= 1.0:
            raise ValueError(f"Percent evidence outside [0, 1] at {path!r}: {number}")
        return f"{number * 100:.{digits}f}%"
    raise ValueError(f"Unsupported format kind for {path!r}: {kind!r}")


def get_panel(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    matches = [panel for panel in panels if isinstance(panel, dict) and panel.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}, found {len(matches)}")
    return matches[0]


def get_block(panel: dict[str, Any], kind: str, label_or_heading: str) -> dict[str, Any]:
    blocks = panel.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"Panel {panel.get('name')!r} has no valid blocks list")
    key = "label" if kind == "metric" else "heading"
    matches = [
        block
        for block in blocks
        if isinstance(block, dict)
        and block.get("kind") == kind
        and block.get(key) == label_or_heading
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one {kind!r} block {label_or_heading!r} in "
            f"panel {panel.get('name')!r}, found {len(matches)}"
        )
    return matches[0]


def metric(panel: dict[str, Any], results: dict[str, Any], label: str) -> tuple[str, float]:
    block = get_block(panel, "metric", label)
    value_spec = require_mapping(block.get("value"), f"value spec for {label}")
    if value_spec.get("source") != "result":
        raise ValueError(f"Metric {label!r} must bind to source 'result'")
    path = require_text(value_spec.get("path"), f"path for {label}")
    raw = resolve_path(results, path)
    number = require_number(raw, path)
    return format_value(raw, value_spec.get("format"), path), number


def source_label(plan: dict[str, Any], panel: dict[str, Any]) -> str:
    sources = panel.get("sources")
    if sources != ["result"]:
        raise ValueError(f"Panel {panel.get('name')!r} must declare exactly ['result']")
    evidence = require_mapping(plan.get("evidence"), "plan.evidence")
    result = require_mapping(evidence.get("result"), "plan.evidence.result")
    label = require_text(result.get("label"), "plan.evidence.result.label")
    if label != "報酬順序風險重跑結果":
        raise ValueError(f"Unexpected strict-plan source label: {label!r}")
    return label


def text_block(panel: dict[str, Any], heading: str) -> tuple[str, str]:
    block = get_block(panel, "text", heading)
    body = block.get("body")
    if not isinstance(body, list) or not body:
        raise TypeError(f"Text block {heading!r} requires a non-empty body list")
    body_lines = [require_text(line, f"body line in {heading}") for line in body]
    return require_text(block.get("heading"), f"heading {heading}"), "\n".join(body_lines)


def new_canvas(background: str = WHITE) -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=background)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(background)
    return fig, ax


def rounded_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    linewidth: float = 1.2,
    radius: float = 0.025,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def title(ax: plt.Axes, text: str, *, color: str = INK, y: float = 0.925) -> None:
    ax.text(
        0.055,
        y,
        require_text(text, "panel title"),
        ha="left",
        va="top",
        fontsize=33,
        fontweight="bold",
        color=color,
    )


def footer(ax: plt.Axes, label: str, *, color: str = MUTED) -> None:
    ax.plot([0.055, 0.945], [0.082, 0.082], color=LINE, linewidth=1.1)
    ax.text(
        0.055,
        0.047,
        f"資料來源：{label}",
        ha="left",
        va="center",
        fontsize=12.5,
        color=color,
    )


def save(fig: plt.Figure, filename: str) -> None:
    path = OUT_DIR / filename
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)


def render_same_returns(plan: dict[str, Any], results: dict[str, Any]) -> None:
    panel = get_panel(plan, "1_same_returns")
    if panel.get("style") != "editorial":
        raise ValueError("1_same_returns must use editorial style")

    product_text, _ = metric(panel, results, "固定籃子的報酬乘積")
    best_text, _ = metric(panel, results, "固定提款後最好終值")
    worst_text, _ = metric(panel, results, "固定提款後最差終值")
    no_withdrawal_heading, no_withdrawal_body = text_block(panel, "沒有提款")

    fig, ax = new_canvas("#FBFAF7")
    title(ax, panel.get("title"))
    ax.text(
        0.057,
        0.835,
        "乘法的順序不影響乘積；提款把減法插入路徑後，終值開始分岔。",
        ha="left",
        va="top",
        fontsize=16.5,
        color=MUTED,
    )

    # Main editorial visual: an invariant-return card feeding two withdrawal outcomes.
    rounded_card(ax, 0.055, 0.165, 0.455, 0.585, facecolor=WHITE, edgecolor="#E2DDD4")
    ax.add_patch(Rectangle((0.055, 0.165), 0.012, 0.585, facecolor=TEAL, edgecolor="none"))
    ax.text(0.095, 0.695, no_withdrawal_heading, fontsize=20, fontweight="bold", color=INK, va="top")
    # At the fixed 150 DPI output, 22 full-width Heiti TC glyphs exceed the
    # usable width of this card. Keep the evidence copy intact while wrapping
    # it early enough to leave a safe inset on both sides.
    wrapped = textwrap.fill(
        no_withdrawal_body,
        width=18,
        break_long_words=True,
        break_on_hyphens=False,
    )
    ax.text(
        0.095,
        0.635,
        wrapped,
        fontsize=16,
        color=MUTED,
        va="top",
        linespacing=1.55,
    )
    ax.plot([0.095, 0.465], [0.405, 0.405], color=LINE, linewidth=1.2)
    ax.text(0.095, 0.355, "固定籃子的報酬乘積", fontsize=14.5, color=MUTED, va="top")
    ax.text(0.095, 0.29, product_text, fontsize=47, fontweight="bold", color=TEAL, va="top")

    ax.text(0.57, 0.735, "加入固定提款", fontsize=16, fontweight="bold", color=GOLD, va="top")
    ax.plot([0.56, 0.56], [0.235, 0.67], color="#D8C7A7", linewidth=2.2)
    ax.plot([0.56, 0.595], [0.62, 0.62], color="#D8C7A7", linewidth=2.2)
    ax.plot([0.56, 0.595], [0.34, 0.34], color="#D8C7A7", linewidth=2.2)
    ax.add_patch(Circle((0.56, 0.48), 0.012, facecolor=GOLD, edgecolor=WHITE, linewidth=2))

    rounded_card(ax, 0.595, 0.505, 0.35, 0.19, facecolor=GOLD_SOFT, edgecolor="#E6D2AE")
    ax.text(0.625, 0.645, "固定提款後最好終值", fontsize=14.5, color=MUTED, va="top")
    ax.text(0.625, 0.585, best_text, fontsize=38, fontweight="bold", color=GOLD, va="top")

    rounded_card(ax, 0.595, 0.225, 0.35, 0.19, facecolor=RED_SOFT, edgecolor="#EBC7C3")
    ax.text(0.625, 0.365, "固定提款後最差終值", fontsize=14.5, color=MUTED, va="top")
    ax.text(0.625, 0.305, worst_text, fontsize=38, fontweight="bold", color=RED, va="top")

    footer(ax, source_label(plan, panel))
    save(fig, "1_same_returns.png")


def render_crash_timing(plan: dict[str, Any], results: dict[str, Any]) -> None:
    panel = get_panel(plan, "2_crash_timing")
    if panel.get("style") != "bento-grid":
        raise ValueError("2_crash_timing must use bento-grid style")

    metrics = {
        label: metric(panel, results, label)[0]
        for label in (
            "美股第一年大跌",
            "美股最後一年大跌",
            "台股第一年大跌",
            "台股最後一年大跌",
        )
    }

    fig, ax = new_canvas(PAPER)
    title(ax, panel.get("title"))
    ax.text(
        0.057,
        0.835,
        "同一大跌情境，不同發生時間",
        ha="left",
        va="top",
        fontsize=16.5,
        color=MUTED,
    )

    cards = [
        (0.055, 0.47, "美股第一年大跌", metrics["美股第一年大跌"], RED_SOFT, RED, "早"),
        (0.525, 0.47, "美股最後一年大跌", metrics["美股最後一年大跌"], BLUE_SOFT, BLUE, "晚"),
        (0.055, 0.16, "台股第一年大跌", metrics["台股第一年大跌"], RED_SOFT, RED, "早"),
        (0.525, 0.16, "台股最後一年大跌", metrics["台股最後一年大跌"], TEAL_SOFT, TEAL, "晚"),
    ]
    for x, y, label, value, fill, accent, badge in cards:
        rounded_card(ax, x, y, 0.42, 0.245, facecolor=WHITE, edgecolor="#DDE3EB", radius=0.022)
        ax.add_patch(Circle((x + 0.055, y + 0.18), 0.026, facecolor=fill, edgecolor="none"))
        ax.text(
            x + 0.055,
            y + 0.18,
            badge,
            ha="center",
            va="center",
            fontsize=12.5,
            fontweight="bold",
            color=accent,
        )
        ax.text(x + 0.095, y + 0.19, label, fontsize=16, fontweight="bold", color=INK, va="center")
        ax.text(x + 0.038, y + 0.105, value, fontsize=43, fontweight="bold", color=accent, va="center")
        ax.text(x + 0.265, y + 0.095, "資產耗盡率", fontsize=13.5, color=MUTED, va="center")

    footer(ax, source_label(plan, panel))
    save(fig, "2_crash_timing.png")


def render_withdrawal_rule(plan: dict[str, Any], results: dict[str, Any]) -> None:
    panel = get_panel(plan, "3_withdrawal_rule")
    if panel.get("style") != "professional":
        raise ValueError("3_withdrawal_rule must use professional style")

    labels = (
        "美股固定提款",
        "美股動態提款",
        "台股固定提款",
        "台股動態提款",
    )
    values = {label: metric(panel, results, label) for label in labels}
    cost_heading, cost_body = text_block(panel, "代價")

    fig, ax = new_canvas(WHITE)
    ax.add_patch(Rectangle((0, 0.805), 1, 0.195, facecolor=NAVY, edgecolor="none"))
    title(ax, panel.get("title"), color=WHITE, y=0.945)
    ax.text(0.057, 0.865, "資產未耗盡比例", fontsize=16.5, color="#CED8E8", va="top")

    # Two market sections, each comparing fixed and dynamic rules on the same scale.
    sections = [
        (0.055, 0.485, "美股固定提款", "美股動態提款", BLUE),
        (0.525, 0.485, "台股固定提款", "台股動態提款", TEAL),
    ]
    for x, y, fixed_label, dynamic_label, accent in sections:
        rounded_card(ax, x, y, 0.42, 0.255, facecolor=WHITE, edgecolor=LINE, radius=0.02)
        market = fixed_label[:2]
        ax.text(x + 0.03, y + 0.205, market, fontsize=18, fontweight="bold", color=INK, va="center")

        fixed_text, fixed_raw = values[fixed_label]
        dynamic_text, dynamic_raw = values[dynamic_label]
        rows = [
            (y + 0.135, "固定提款", fixed_text, fixed_raw, MUTED, "#C8CFDA"),
            (y + 0.055, "動態提款", dynamic_text, dynamic_raw, accent, accent),
        ]
        for row_y, row_label, rendered, raw, text_color, bar_color in rows:
            ax.text(x + 0.03, row_y + 0.026, row_label, fontsize=13.5, color=MUTED, va="center")
            ax.add_patch(
                FancyBboxPatch(
                    (x + 0.135, row_y),
                    0.18,
                    0.045,
                    boxstyle="round,pad=0,rounding_size=0.018",
                    facecolor="#EEF1F5",
                    edgecolor="none",
                )
            )
            ax.add_patch(
                FancyBboxPatch(
                    (x + 0.135, row_y),
                    0.18 * raw,
                    0.045,
                    boxstyle="round,pad=0,rounding_size=0.018",
                    facecolor=bar_color,
                    edgecolor="none",
                )
            )
            ax.text(
                x + 0.385,
                row_y + 0.026,
                rendered,
                fontsize=20,
                fontweight="bold",
                color=text_color,
                ha="right",
                va="center",
            )

    rounded_card(ax, 0.055, 0.165, 0.89, 0.235, facecolor="#F5F7FA", edgecolor="#E1E6ED")
    ax.add_patch(Rectangle((0.055, 0.165), 0.01, 0.235, facecolor=GOLD, edgecolor="none"))
    ax.text(0.095, 0.35, cost_heading, fontsize=18, fontweight="bold", color=INK, va="top")
    ax.text(
        0.095,
        0.285,
        textwrap.fill(cost_body, width=43),
        fontsize=16,
        color=MUTED,
        va="top",
        linespacing=1.5,
    )

    footer(ax, source_label(plan, panel))
    save(fig, "3_withdrawal_rule.png")


def validate_package(plan: dict[str, Any], results: dict[str, Any], article: str) -> None:
    if plan.get("schema_version") != 1:
        raise ValueError(f"Unsupported plan schema_version: {plan.get('schema_version')!r}")
    require_mapping(results, "results.json root")
    require_text(article, "article markdown")

    expected_names = {"1_same_returns", "2_crash_timing", "3_withdrawal_rule"}
    panels = plan.get("panels")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    actual_names = {panel.get("name") for panel in panels if isinstance(panel, dict)}
    if actual_names != expected_names:
        raise ValueError(f"Unexpected panel set: {actual_names!r}")

    # The article is part of the package; require each strict-plan alt string to
    # appear there so a stale plan/article pairing fails loudly.
    for panel in panels:
        panel_map = require_mapping(panel, "panel")
        alt = require_text(panel_map.get("alt"), f"alt for {panel_map.get('name')}")
        if alt not in article:
            raise ValueError(f"Panel alt text is absent from article markdown: {alt!r}")


def main() -> None:
    plan = require_mapping(load_json(PLAN_PATH), "plan.json root")
    results = require_mapping(load_json(RESULTS_PATH), "results.json root")
    article = ARTICLE_PATH.read_text(encoding="utf-8")
    validate_package(plan, results, article)

    os.makedirs(OUT_DIR, exist_ok=True)
    render_same_returns(plan, results)
    render_crash_timing(plan, results)
    render_withdrawal_rule(plan, results)


if __name__ == "__main__":
    main()
