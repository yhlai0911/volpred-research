#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the 2026-07-30 VolPred digest."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


ARTICLE_PATH = Path("/tmp/digest_20260730.md")
EVIDENCE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/assets/"
    "vol_three_tenses_20260730.json"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_plans/"
    "daily_digest_20260730_plan.json"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "daily_digest_20260730_panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#14213D"
MUTED = "#5B6578"
PAPER = "#F7F8FA"
WHITE = "#FFFFFF"
NAVY = "#102A43"
BLUE = "#2878B5"
BLUE_SOFT = "#E8F1F8"
TEAL = "#16877A"
TEAL_SOFT = "#E4F3F0"
AMBER = "#C27A17"
AMBER_SOFT = "#FAF0DE"
RED = "#B84646"
RED_SOFT = "#F7E8E8"
LINE = "#D8DEE8"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve a strict RFC 6901-style JSON pointer; missing fields raise."""
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must begin with '/': {pointer}")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(pointer)
    return current


def require_number(document: Any, pointer: str) -> float | int:
    value = resolve_pointer(document, pointer)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {pointer}, got {type(value).__name__}")
    return value


def format_bound_value(document: Any, value_spec: dict[str, Any]) -> str:
    if value_spec["source"] != "ev":
        raise KeyError(f"Unknown evidence source: {value_spec['source']}")
    value = require_number(document, value_spec["path"])
    fmt = value_spec["format"]
    kind = fmt["kind"]
    if kind == "integer":
        if int(value) != value:
            raise ValueError(f"Expected an integer at {value_spec['path']}")
        rendered = f"{int(value)}"
    elif kind == "number":
        digits = fmt["digits"]
        prefix = "+" if fmt.get("show_plus") and value >= 0 else ""
        rendered = f"{prefix}{value:.{digits}f}"
    else:
        raise ValueError(f"Unsupported number format: {kind}")
    return f"{rendered}{fmt.get('suffix', '')}"


def wrapped(text: str, width: int) -> str:
    """Wrap CJK copy to the character budget of its containing card.

    ``textwrap`` treats an uninterrupted Chinese sentence as one long word.
    Disabling ``break_long_words`` therefore made every wrap budget below a
    no-op and let labels, notes, and body copy run beyond their boxes.
    Preserve intentional newlines, but allow each logical line to break at
    the requested character width.
    """
    if width <= 0:
        raise ValueError("Wrap width must be positive")

    lines: list[str] = []
    for logical_line in text.splitlines() or [""]:
        lines.extend(
            textwrap.wrap(
                logical_line,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=True,
            )
            or [""]
        )
    return "\n".join(lines)


def add_round_rect(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.018,
    zorder: int = 1,
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
            zorder=zorder,
        )
    )


def make_canvas(background: str = PAPER) -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=background,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def add_header(
    ax: plt.Axes,
    title: str,
    subtitle: str,
    *,
    dark_bar: bool,
) -> None:
    if dark_bar:
        ax.add_patch(
            Rectangle(
                (0, 0.855),
                1,
                0.145,
                transform=ax.transAxes,
                facecolor=NAVY,
                edgecolor="none",
            )
        )
        title_color = WHITE
        subtitle_color = "#D7E2EC"
        title_y = 0.925
        subtitle_y = 0.875
    else:
        title_color = INK
        subtitle_color = MUTED
        title_y = 0.935
        subtitle_y = 0.885
    ax.text(
        0.055,
        title_y,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=29,
        fontweight="bold",
        color=title_color,
    )
    ax.text(
        0.057,
        subtitle_y,
        subtitle,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=13,
        color=subtitle_color,
    )


def add_source_footer(ax: plt.Axes, label: str) -> None:
    ax.plot(
        [0.055, 0.945],
        [0.074, 0.074],
        transform=ax.transAxes,
        color=LINE,
        linewidth=1,
    )
    ax.text(
        0.055,
        0.045,
        wrapped(f"資料來源：{label}", 104),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=8.5,
        color=MUTED,
        linespacing=1.25,
    )


def metric_card(
    ax: plt.Axes,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    note: str,
    accent: str,
    tint: str,
    label_wrap: int,
    note_wrap: int,
    value_size: float = 29,
) -> None:
    add_round_rect(
        ax,
        x,
        y,
        width,
        height,
        facecolor=WHITE,
        edgecolor=LINE,
        linewidth=0.8,
    )
    ax.add_patch(
        Rectangle(
            (x, y),
            0.008,
            height,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
            zorder=2,
        )
    )
    ax.add_patch(
        Circle(
            (x + width - 0.038, y + height - 0.045),
            0.017,
            transform=ax.transAxes,
            facecolor=tint,
            edgecolor="none",
            zorder=2,
        )
    )
    ax.text(
        x + 0.026,
        y + height - 0.033,
        wrapped(label, label_wrap),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12,
        fontweight="bold",
        color=INK,
        linespacing=1.18,
        zorder=3,
    )
    ax.text(
        x + 0.026,
        y + height * 0.47,
        value,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=value_size,
        fontweight="bold",
        color=accent,
        zorder=3,
    )
    ax.text(
        x + 0.026,
        y + 0.026,
        wrapped(note, note_wrap),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.5,
        color=MUTED,
        linespacing=1.28,
        zorder=3,
    )


def render_three_tenses(
    panel: dict[str, Any], evidence: dict[str, Any], source_label: str
) -> None:
    fig, ax = make_canvas("#F5F2EC")
    add_header(
        ax,
        panel["title"],
        "把報價、後照鏡與已發生的行情，放回各自的位置",
        dark_bar=False,
    )

    text_block = panel["blocks"][0]
    body = text_block["body"]
    metrics = panel["blocks"][1:]
    tense_specs = [
        ("未來式", "保險報價", AMBER, AMBER_SOFT, body[2], metrics[0]),
        ("過去式", "歷史後照鏡", BLUE, BLUE_SOFT, body[0], metrics[1]),
        ("現在式", "已發生行情", TEAL, TEAL_SOFT, body[1], metrics[2]),
    ]
    card_xs = [0.055, 0.357, 0.659]
    card_width = 0.286
    for x, spec in zip(card_xs, tense_specs):
        tense, role, accent, tint, description, metric = spec
        add_round_rect(
            ax,
            x,
            0.315,
            card_width,
            0.515,
            facecolor=WHITE,
            edgecolor=LINE,
            linewidth=0.9,
            radius=0.022,
        )
        ax.add_patch(
            Rectangle(
                (x, 0.775),
                card_width,
                0.055,
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor="none",
                zorder=2,
            )
        )
        ax.text(
            x + 0.024,
            0.802,
            tense,
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=17,
            fontweight="bold",
            color=WHITE,
            zorder=3,
        )
        ax.text(
            x + card_width - 0.024,
            0.802,
            role,
            transform=ax.transAxes,
            ha="right",
            va="center",
            fontsize=10,
            color=WHITE,
            zorder=3,
        )
        value = format_bound_value(evidence, metric["value"])
        ax.text(
            x + 0.024,
            0.713,
            value,
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=32,
            fontweight="bold",
            color=accent,
            zorder=3,
        )
        ax.text(
            x + 0.024,
            0.660,
            wrapped(metric["label"], 17),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=11,
            fontweight="bold",
            color=INK,
            linespacing=1.22,
            zorder=3,
        )
        ax.plot(
            [x + 0.024, x + card_width - 0.024],
            [0.600, 0.600],
            transform=ax.transAxes,
            color=LINE,
            linewidth=1,
            zorder=3,
        )
        ax.text(
            x + 0.024,
            0.570,
            wrapped(description, 18),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10.3,
            color=INK,
            linespacing=1.33,
            zorder=3,
        )
        ax.text(
            x + 0.024,
            0.345,
            wrapped(metric["note"], 18),
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9.2,
            color=MUTED,
            linespacing=1.25,
            zorder=3,
        )

    premium = metrics[3]
    add_round_rect(
        ax,
        0.055,
        0.112,
        0.890,
        0.158,
        facecolor=NAVY,
        radius=0.020,
    )
    ax.text(
        0.081,
        0.229,
        text_block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=12,
        fontweight="bold",
        color="#BFD3E3",
        zorder=3,
    )
    ax.text(
        0.081,
        0.175,
        format_bound_value(evidence, premium["value"]),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=31,
        fontweight="bold",
        color=WHITE,
        zorder=3,
    )
    ax.text(
        0.205,
        0.181,
        wrapped(premium["label"], 22),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=12,
        fontweight="bold",
        color=WHITE,
        linespacing=1.2,
        zorder=3,
    )
    ax.add_patch(
        FancyArrowPatch(
            (0.49, 0.190),
            (0.55, 0.190),
            transform=ax.transAxes,
            arrowstyle="-|>",
            mutation_scale=15,
            linewidth=1.8,
            color="#8FB3CB",
            zorder=3,
        )
    )
    ax.text(
        0.585,
        0.194,
        # Only the right-hand 36% of the 1600 px canvas is available here.
        # At 11 pt, 35 CJK glyphs overrun both the navy card and the canvas.
        wrapped(body[3], 22),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=11,
        color=WHITE,
        linespacing=1.28,
        zorder=3,
    )
    ax.text(
        0.585,
        0.137,
        premium["note"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=9.3,
        color="#BFD3E3",
        zorder=3,
    )
    add_source_footer(ax, source_label)
    fig.savefig(
        os.path.join(out_dir, "panel_three_tenses.png"),
        dpi=DPI,
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)


def render_price_tags(
    panel: dict[str, Any], evidence: dict[str, Any], source_label: str
) -> None:
    fig, ax = make_canvas()
    add_header(
        ax,
        panel["title"],
        "報價何時有資訊、模型承諾何時失準：用實測結果逐項對帳",
        dark_bar=True,
    )
    metrics = panel["blocks"]
    positions = [
        (0.055, 0.505),
        (0.357, 0.505),
        (0.659, 0.505),
        (0.055, 0.125),
        (0.357, 0.125),
        (0.659, 0.125),
    ]
    palettes = [
        (AMBER, AMBER_SOFT),
        (RED, RED_SOFT),
        (TEAL, TEAL_SOFT),
        (BLUE, BLUE_SOFT),
        (TEAL, TEAL_SOFT),
        (RED, RED_SOFT),
    ]
    for metric, (x, y), (accent, tint) in zip(metrics, positions, palettes):
        metric_card(
            ax,
            x=x,
            y=y,
            width=0.286,
            height=0.315,
            label=metric["label"],
            value=format_bound_value(evidence, metric["value"]),
            note=metric["note"],
            accent=accent,
            tint=tint,
            # The usable width after the left inset and badge is about 400 px.
            # Keep every 12 pt CJK line below that bound.
            label_wrap=16,
            note_wrap=20,
            value_size=29,
        )
    add_source_footer(ax, source_label)
    fig.savefig(
        os.path.join(out_dir, "panel-price-tags.png"),
        dpi=DPI,
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)


def render_cut_or_not(
    panel: dict[str, Any], evidence: dict[str, Any], source_label: str
) -> None:
    fig, ax = make_canvas()
    add_header(
        ax,
        panel["title"],
        "回撤變淺不等於抓對時機；先把曝險差異從帳面成績扣掉",
        dark_bar=True,
    )
    text_block = panel["blocks"][0]
    metrics = panel["blocks"][1:]

    add_round_rect(
        ax,
        0.055,
        0.125,
        0.355,
        0.685,
        facecolor=NAVY,
        radius=0.024,
    )
    ax.text(
        0.083,
        0.755,
        text_block["heading"],
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=WHITE,
        zorder=3,
    )
    ax.plot(
        [0.083, 0.382],
        [0.716, 0.716],
        transform=ax.transAxes,
        color="#41657F",
        linewidth=1,
        zorder=3,
    )
    body_y = [0.675, 0.505, 0.335]
    accents = [AMBER, BLUE, TEAL]
    for paragraph, y, accent in zip(text_block["body"], body_y, accents):
        ax.add_patch(
            Circle(
                (0.096, y + 0.012),
                0.011,
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor="none",
                zorder=3,
            )
        )
        ax.text(
            0.122,
            y + 0.024,
            # The navy card leaves about 470 px from this inset to its right
            # edge; 25 CJK glyphs at 10.5 pt exceeded it by roughly 73 px.
            wrapped(paragraph, 20),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10.5,
            color=WHITE,
            linespacing=1.38,
            zorder=3,
        )
    ax.text(
        0.083,
        0.166,
        "減碼是尺度調整，不是擇時能力",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=12.5,
        fontweight="bold",
        color="#BFD3E3",
        zorder=3,
    )

    positions = [
        (0.445, 0.485),
        (0.710, 0.485),
        (0.445, 0.125),
        (0.710, 0.125),
    ]
    palettes = [
        (TEAL, TEAL_SOFT),
        (RED, RED_SOFT),
        (RED, RED_SOFT),
        (BLUE, BLUE_SOFT),
    ]
    for metric, (x, y), (accent, tint) in zip(metrics, positions, palettes):
        metric_card(
            ax,
            x=x,
            y=y,
            width=0.235,
            height=0.325,
            label=metric["label"],
            value=format_bound_value(evidence, metric["value"]),
            note=metric["note"],
            accent=accent,
            tint=tint,
            # These cards are narrower than the six-card grid above.  Thirteen
            # 12 pt glyphs fit inside the post-inset width with guard margin.
            label_wrap=13,
            note_wrap=14,
            value_size=28,
        )
    add_source_footer(ax, source_label)
    fig.savefig(
        os.path.join(out_dir, "panel_cut_or_not.png"),
        dpi=DPI,
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)


def main() -> None:
    # Read every declared input through an absolute path. The article read is
    # intentional: a missing evidence package must fail loudly at render time.
    ARTICLE_PATH.read_text(encoding="utf-8")
    evidence = load_json(EVIDENCE_PATH)
    plan = load_json(PLAN_PATH)
    source_label = plan["evidence"]["ev"]["label"]
    expected_label = (
        "2026-07-30 精選導讀證據包（今日讀數取自同日每日策略建議與持倉建議；"
        "研究數字逐字取自八篇已發佈來源文章）"
    )
    if source_label != expected_label:
        raise ValueError("Strict-plan evidence label changed; refusing to guess a source label")

    panels = {panel["name"]: panel for panel in plan["panels"]}
    required_panels = {
        "panel_three_tenses",
        "panel-price-tags",
        "panel_cut_or_not",
    }
    missing = required_panels.difference(panels)
    if missing:
        raise KeyError(f"Missing strict-plan panels: {sorted(missing)}")

    os.makedirs(out_dir, exist_ok=True)
    render_three_tenses(panels["panel_three_tenses"], evidence, source_label)
    render_price_tags(panels["panel-price-tags"], evidence, source_label)
    render_cut_or_not(panels["panel_cut_or_not"], evidence, source_label)


if __name__ == "__main__":
    main()
