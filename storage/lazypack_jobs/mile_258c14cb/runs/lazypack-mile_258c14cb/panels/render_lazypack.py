#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_258c14cb article."""

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


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1366/k1366_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1366/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_258c14cb/runs/lazypack-mile_258c14cb/plan.json"
)
CANONICAL_RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1366/K1366_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_258c14cb/runs/lazypack-mile_258c14cb/panels/"
    "mile_258c14cb_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_258c14cb/runs/lazypack-mile_258c14cb/panels"
)

EXPECTED_PANELS = ("panel_question", "panel_variance", "panel_takeaway")

NAVY = "#102A43"
NAVY_2 = "#173F5F"
INK = "#172B3A"
MUTED = "#526777"
PALE = "#F3F7FA"
LINE = "#D7E1E8"
TEAL = "#168C8C"
GOLD = "#D89A28"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"{path} 的 JSON 根節點必須是 object")
    return payload


def require_nonempty_text(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"{path} 是空檔案")
    return content


def json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901-style JSON pointer; missing keys/indices raise."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer 必須以 / 開頭：{pointer}")

    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise TypeError(f"陣列索引不是整數：{pointer}") from exc
            current = current[index]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise TypeError(f"無法繼續解析 JSON Pointer：{pointer}")
    return current


def format_metric(raw_value: Any, format_spec: dict[str, Any]) -> str:
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise TypeError(f"metric 必須是數字，收到：{raw_value!r}")

    kind = format_spec["kind"]
    if kind == "integer":
        if isinstance(raw_value, float) and not raw_value.is_integer():
            raise ValueError(f"integer 格式收到非整數：{raw_value!r}")
        return f"{int(raw_value):,}"
    if kind == "percent":
        digits = int(format_spec["digits"])
        return f"{raw_value * 100:.{digits}f}%"
    if kind == "number":
        digits = int(format_spec["digits"])
        return f"{raw_value:.{digits}f}"
    raise ValueError(f"不支援的 metric 格式：{kind!r}")


def wrap_zh(text: str, width: int) -> str:
    return textwrap.fill(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )


def add_fitted_text(
    fig: plt.Figure,
    text: str,
    *,
    box: tuple[float, float, float, float],
    color: str,
    max_fontsize: float,
    min_fontsize: float,
    fontweight: str = "normal",
    linespacing: float = 1.2,
) -> None:
    """Draw top-left text inside a figure-coordinate box.

    Character-count wrapping is not sufficient for CJK fonts: at 150 DPI a
    nominally short line can still be hundreds of pixels wider than expected.
    Measure the actual Heiti TC glyph bounds and reduce the wrap width/font
    until the complete text fits.  The explicit box also keeps independently
    drawn labels from colliding with values.
    """
    if not isinstance(text, str) or not text:
        raise TypeError("繪圖文字必須是非空字串")

    left, bottom, right, top = box
    if not (0 <= left < right <= 1 and 0 <= bottom < top <= 1):
        raise ValueError(f"無效的文字框：{box!r}")

    canvas_width, canvas_height = fig.get_size_inches() * fig.dpi
    available_width = (right - left) * canvas_width
    available_height = (top - bottom) * canvas_height

    # A CJK glyph is approximately one em wide.  Start from that conservative
    # estimate, then use the renderer as the authoritative check.
    for fontsize in range(int(max_fontsize * 2), int(min_fontsize * 2) - 1, -1):
        size = fontsize / 2
        glyph_width = size * fig.dpi / 72
        initial_chars = max(1, int(available_width / glyph_width))
        for chars_per_line in range(initial_chars, 0, -1):
            artist = fig.text(
                left,
                top,
                wrap_zh(text, chars_per_line),
                color=color,
                fontsize=size,
                fontweight=fontweight,
                linespacing=linespacing,
                ha="left",
                va="top",
            )
            fig.canvas.draw()
            bounds = artist.get_window_extent(
                renderer=fig.canvas.get_renderer()
            )
            if (
                bounds.width <= available_width
                and bounds.height <= available_height
            ):
                return
            artist.remove()

    raise ValueError(f"文字無法放入指定框：{text}")


def add_rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 0.0,
    radius: float = 0.018,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            transform=ax.transAxes,
        )
    )


def get_panel_parts(panel: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blocks = panel["blocks"]
    if not isinstance(blocks, list):
        raise TypeError(f"{panel['name']}.blocks 必須是陣列")
    text_blocks = [block for block in blocks if block["kind"] == "text"]
    metric_blocks = [block for block in blocks if block["kind"] == "metric"]
    if len(text_blocks) != 1 or len(metric_blocks) != 3:
        raise ValueError(f"{panel['name']} 必須恰有一個 text block 與三個 metric blocks")
    return text_blocks[0], metric_blocks


def render_panel(
    panel: dict[str, Any],
    results: dict[str, Any],
    source_label: str,
) -> None:
    title = panel["title"]
    alt = panel["alt"]
    name = panel["name"]
    if panel["sources"] != ["results"]:
        raise ValueError(f"{name} 的 sources 必須只包含 results")

    text_block, metric_blocks = get_panel_parts(panel)

    fig = plt.figure(figsize=(1600 / 150, 1000 / 150), dpi=150, facecolor=WHITE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Deep header with a restrained visual rule.
    ax.add_patch(Rectangle((0, 0.775), 1, 0.225, color=NAVY, transform=ax.transAxes))
    ax.add_patch(Rectangle((0.055, 0.832), 0.008, 0.095, color=TEAL, transform=ax.transAxes))
    fig.text(
        0.083,
        0.885,
        title,
        color=WHITE,
        fontsize=31,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.083,
        0.824,
        "歷史事件後的跨資產波動與相關性檢定",
        color="#C8D8E4",
        fontsize=15,
        ha="left",
        va="center",
    )

    # Narrative region.
    add_rounded_box(
        ax,
        0.055,
        0.175,
        0.515,
        0.545,
        facecolor=PALE,
        edgecolor=LINE,
        linewidth=1.2,
    )
    ax.add_patch(Rectangle((0.055, 0.675), 0.515, 0.045, color=NAVY_2, transform=ax.transAxes))
    fig.text(
        0.078,
        0.697,
        text_block["heading"],
        color=WHITE,
        fontsize=20,
        fontweight="bold",
        ha="left",
        va="center",
    )

    body = text_block["body"]
    if not isinstance(body, list) or len(body) != 2 or not all(
        isinstance(paragraph, str) for paragraph in body
    ):
        raise TypeError(f"{name} 的 text body 必須是兩段文字")

    body_boxes = (
        (0.082, 0.465, 0.548, 0.640),
        (0.082, 0.205, 0.548, 0.445),
    )
    for paragraph, box in zip(body, body_boxes, strict=True):
        add_fitted_text(
            fig,
            paragraph,
            box=box,
            color=INK,
            max_fontsize=16,
            min_fontsize=11,
            linespacing=1.28,
        )

    # Three independent metric cards.
    card_y_positions = (0.548, 0.363, 0.178)
    accent_colors = (TEAL, GOLD, NAVY_2)
    for metric, y, accent in zip(
        metric_blocks, card_y_positions, accent_colors, strict=True
    ):
        value_spec = metric["value"]
        if value_spec["source"] != "results":
            raise ValueError(f"{name} 的 metric source 必須是 results")
        pointer = value_spec["path"]
        raw_value = json_pointer(results, pointer)
        display_value = format_metric(raw_value, value_spec["format"])

        add_rounded_box(
            ax,
            0.612,
            y,
            0.333,
            0.158,
            facecolor=WHITE,
            edgecolor=LINE,
            linewidth=1.2,
        )
        ax.add_patch(
            Rectangle((0.612, y), 0.009, 0.158, color=accent, transform=ax.transAxes)
        )
        add_fitted_text(
            fig,
            metric["label"],
            box=(0.642, y + 0.025, 0.795, y + 0.133),
            color=MUTED,
            max_fontsize=13,
            min_fontsize=9,
            fontweight="bold",
            linespacing=1.12,
        )
        fig.text(
            0.918,
            y + 0.079,
            display_value,
            color=INK,
            fontsize=29,
            fontweight="bold",
            ha="right",
            va="center",
        )

    # The evidence label is deliberately used verbatim from plan.json.
    ax.add_patch(Rectangle((0.055, 0.125), 0.89, 0.002, color=LINE, transform=ax.transAxes))
    fig.text(
        0.055,
        0.088,
        "資料來源：",
        color=MUTED,
        fontsize=10.5,
        fontweight="bold",
        ha="left",
        va="center",
    )
    fig.text(
        0.119,
        0.088,
        source_label,
        color=MUTED,
        fontsize=9.8,
        ha="left",
        va="center",
    )

    output_path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(
        output_path,
        dpi=150,
        facecolor=WHITE,
        metadata={"Title": title, "Description": alt},
    )
    plt.close(fig)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)

    results = load_json(RESULTS_PATH)
    canonical_results = load_json(CANONICAL_RESULTS_PATH)
    plan = load_json(PLAN_PATH)
    require_nonempty_text(README_PATH)
    require_nonempty_text(ARTICLE_PATH)

    if results != canonical_results:
        raise ValueError("兩份指定 results evidence 內容不一致，拒絕繪製")

    evidence = plan["evidence"]
    source_label = evidence["results"]["label"]
    if not isinstance(source_label, str) or not source_label:
        raise TypeError("plan evidence.results.label 必須是非空字串")

    panels = plan["panels"]
    if not isinstance(panels, list):
        raise TypeError("plan.panels 必須是陣列")
    panels_by_name = {panel["name"]: panel for panel in panels}
    if set(panels_by_name) != set(EXPECTED_PANELS):
        raise ValueError(
            f"plan panel 名稱不符：預期 {EXPECTED_PANELS!r}，"
            f"收到 {tuple(panels_by_name)!r}"
        )

    for panel_name in EXPECTED_PANELS:
        render_panel(panels_by_name[panel_name], results, source_label)


if __name__ == "__main__":
    main()
