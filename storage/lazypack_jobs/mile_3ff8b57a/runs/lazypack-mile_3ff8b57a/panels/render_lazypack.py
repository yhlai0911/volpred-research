#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the mile_3ff8b57a article.

All displayed statistics are resolved from the strict plan into the archived
results JSON at run time.  Missing fields, malformed values, or evidence drift
raise immediately instead of producing a plausible-looking fallback graphic.
"""

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
from matplotlib.patches import FancyBboxPatch, Rectangle


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3ff8b57a/runs/lazypack-mile_3ff8b57a/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1479/k1479_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3ff8b57a/runs/lazypack-mile_3ff8b57a/panels/"
    "mile_3ff8b57a_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_3ff8b57a/runs/lazypack-mile_3ff8b57a/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#13263D"
NAVY_2 = "#1C3655"
BLUE = "#2673B8"
TEAL = "#16847A"
AMBER = "#C47B18"
RED = "#B64A4A"
INK = "#172435"
MUTED = "#5D6A78"
LIGHT = "#EEF3F7"
LINE = "#D8E1E9"
WHITE = "#FFFFFF"
PALE_BLUE = "#EAF3FB"
PALE_TEAL = "#E8F5F2"
PALE_AMBER = "#FBF2E5"
PALE_RED = "#F9ECEC"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence article is empty: {path}")
    return text


def require_dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {where}, got {type(value).__name__}")
    return value


def require_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected array at {where}, got {type(value).__name__}")
    return value


def require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {where}")
    return value


def require_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {where}, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected finite number at {where}, got {value!r}")
    return number


def verify_results_identity(plan: dict[str, Any]) -> None:
    evidence = require_dict(plan["evidence"], "/evidence")
    results_spec = require_dict(evidence["results"], "/evidence/results")
    expected = require_string(results_spec["sha256"], "/evidence/results/sha256")
    actual = hashlib.sha256(RESULTS_PATH.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(
            "Results evidence SHA-256 does not match plan: "
            f"expected {expected}, got {actual}"
        )


def json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Missing evidence field: {pointer}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {pointer}") from exc
        else:
            raise KeyError(f"Cannot traverse evidence field: {pointer}")
    return current


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require_list(plan["panels"], "/panels")
    matches = [
        require_dict(panel, f"/panels/{index}")
        for index, panel in enumerate(panels)
        if isinstance(panel, dict) and panel.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one panel named {name!r}, found {len(matches)}")
    return matches[0]


def panel_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    raw_blocks = require_list(panel["blocks"], f"/panels/{panel.get('name')}/blocks")
    return [
        require_dict(block, f"/panels/{panel.get('name')}/blocks/{index}")
        for index, block in enumerate(raw_blocks)
    ]


def source_label(plan: dict[str, Any], panel: dict[str, Any]) -> str:
    sources = require_list(panel["sources"], f"/panels/{panel.get('name')}/sources")
    if sources != ["results"]:
        raise ValueError(f"Panel {panel.get('name')} must use only the results evidence")
    evidence = require_dict(plan["evidence"], "/evidence")
    spec = require_dict(evidence["results"], "/evidence/results")
    return require_string(spec["label"], "/evidence/results/label")


def format_metric(
    block: dict[str, Any], results: dict[str, Any], *, magnitude: bool = False
) -> str:
    value_spec = require_dict(block["value"], f"metric {block.get('label')}/value")
    if value_spec.get("source") != "results":
        raise ValueError(f"Metric {block.get('label')} does not point to results evidence")
    pointer = require_string(value_spec["path"], f"metric {block.get('label')}/path")
    number = require_number(json_pointer(results, pointer), pointer)
    if magnitude:
        number = abs(number)
    format_spec = require_dict(
        value_spec["format"], f"metric {block.get('label')}/format"
    )
    kind = require_string(format_spec["kind"], "metric format kind")
    suffix = str(format_spec.get("suffix", ""))

    if kind == "integer":
        if not number.is_integer():
            raise ValueError(f"Expected integer-valued evidence at {pointer}, got {number}")
        rendered = f"{int(number):,d}"
    elif kind == "percent":
        digits = int(format_spec["digits"])
        rendered = f"{number * 100:.{digits}f}%"
    elif kind == "number":
        digits = int(format_spec["digits"])
        rendered = f"{number:.{digits}f}"
    else:
        raise ValueError(f"Unsupported metric format kind: {kind!r}")
    return rendered.replace("-", "−") + suffix


def wrap(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def wrap_for_box(
    text: str,
    box_width: float,
    fontsize: float,
    *,
    left_pad: float = 0.0,
    right_pad: float = 0.0,
    max_chars: int | None = None,
) -> str:
    """Wrap text using the rendered CJK width, not an abstract char count.

    Matplotlib font sizes are points.  At 150 DPI a 13 pt full-width glyph is
    about 27 px wide, so the old 30/78-character limits could not fit inside
    680/1424 px cards.  The small safety factor also leaves room for Chinese
    punctuation and Heiti TC's glyph bearings.
    """
    usable_px = (box_width - left_pad - right_pad) * WIDTH_PX
    if usable_px <= 0:
        raise ValueError("Text box has no usable horizontal space")
    full_width_glyph_px = fontsize * DPI / 72.0 * 1.12
    measured_limit = max(1, int(usable_px // full_width_glyph_px))
    if max_chars is not None:
        measured_limit = min(measured_limit, max_chars)
    return wrap(text, measured_limit)


def add_box(
    fig: plt.Figure,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    radius: float = 0.014,
    linewidth: float = 1.0,
) -> None:
    fig.add_artist(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=fig.transFigure,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            zorder=1,
        )
    )


def new_figure(panel: dict[str, Any]) -> plt.Figure:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    fig.add_artist(
        Rectangle(
            (0, 0.865),
            1,
            0.135,
            transform=fig.transFigure,
            facecolor=NAVY,
            edgecolor="none",
            zorder=0,
        )
    )
    fig.text(
        0.055,
        0.935,
        require_string(panel["title"], f"panel {panel.get('name')} title"),
        ha="left",
        va="center",
        fontsize=27,
        fontweight="bold",
        color=WHITE,
        zorder=3,
    )
    return fig


def add_footer(fig: plt.Figure, label: str) -> None:
    fig.add_artist(
        Rectangle(
            (0.045, 0.105),
            0.91,
            0.0015,
            transform=fig.transFigure,
            facecolor=LINE,
            edgecolor="none",
            zorder=1,
        )
    )
    fig.text(
        0.055,
        0.083,
        wrap_for_box("資料來源｜" + label, 0.89, 8.6, max_chars=66),
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
        linespacing=1.28,
        zorder=3,
    )


def save_panel(fig: plt.Figure, panel: dict[str, Any], label: str) -> None:
    name = require_string(panel["name"], "panel name")
    alt = require_string(panel["alt"], f"panel {name} alt")
    out_path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(
        out_path,
        dpi=DPI,
        facecolor=WHITE,
        metadata={
            "Title": require_string(panel["title"], f"panel {name} title"),
            "Description": alt,
            "Source": label,
        },
    )
    plt.close(fig)


def add_text_card(
    fig: plt.Figure,
    block: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    accent: str,
    fill: str = WHITE,
    body_wrap: int = 39,
    body_size: float = 13.0,
    heading_size: float = 15.0,
    paragraph_gap: bool = True,
) -> None:
    if block.get("kind") != "text":
        raise ValueError(f"Expected text block, got {block.get('kind')!r}")
    add_box(fig, x, y, width, height, facecolor=fill)
    fig.add_artist(
        Rectangle(
            (x, y),
            0.008,
            height,
            transform=fig.transFigure,
            facecolor=accent,
            edgecolor="none",
            zorder=2,
        )
    )
    heading = wrap_for_box(
        require_string(block["heading"], "text block heading"),
        width,
        heading_size,
        left_pad=0.025,
        right_pad=0.025,
    )
    heading_top = y + height - 0.040
    fig.text(
        x + 0.025,
        heading_top,
        heading,
        ha="left",
        va="top",
        fontsize=heading_size,
        fontweight="bold",
        color=INK,
        linespacing=1.20,
        zorder=3,
    )
    body = require_list(block["body"], f"text block {block.get('heading')}/body")
    paragraphs = [require_string(item, "text block paragraph") for item in body]
    rendered_paragraphs = [
        wrap_for_box(
            paragraph,
            width,
            body_size,
            left_pad=0.025,
            right_pad=0.025,
            max_chars=body_wrap,
        )
        for paragraph in paragraphs
    ]
    rendered = ("\n\n" if paragraph_gap else "\n").join(rendered_paragraphs)
    heading_lines = heading.count("\n") + 1
    heading_line_height = heading_size * DPI / 72.0 * 1.20 / HEIGHT_PX
    body_top = heading_top - heading_lines * heading_line_height - 0.014
    fig.text(
        x + 0.025,
        body_top,
        rendered,
        ha="left",
        va="top",
        fontsize=body_size,
        color=INK,
        linespacing=1.35,
        zorder=3,
    )


def add_metric_card(
    fig: plt.Figure,
    block: dict[str, Any],
    value: str,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    accent: str,
    fill: str,
) -> None:
    if block.get("kind") != "metric":
        raise ValueError(f"Expected metric block, got {block.get('kind')!r}")
    add_box(fig, x, y, width, height, facecolor=fill, edgecolor=fill)
    label = wrap_for_box(
        require_string(block["label"], "metric label"),
        width,
        10.0,
        left_pad=0.022,
        right_pad=0.018,
        max_chars=16,
    )
    fig.text(
        x + 0.022,
        y + height - 0.028,
        label,
        ha="left",
        va="top",
        fontsize=10.0,
        fontweight="bold",
        color=INK,
        linespacing=1.15,
        zorder=3,
    )
    fig.text(
        x + 0.022,
        y + height * 0.38,
        value,
        ha="left",
        va="bottom",
        fontsize=24,
        fontweight="bold",
        color=accent,
        zorder=3,
    )
    note = wrap_for_box(
        require_string(block["note"], "metric note"),
        width,
        8.2,
        left_pad=0.022,
        right_pad=0.018,
        max_chars=18,
    )
    fig.text(
        x + 0.022,
        y + 0.022,
        note,
        ha="left",
        va="bottom",
        fontsize=8.2,
        color=MUTED,
        linespacing=1.15,
        zorder=3,
    )


def render_concept(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    blocks = panel_blocks(panel)
    if len(blocks) != 2:
        raise ValueError("panel_concept must contain exactly two text blocks")
    feasibility = require_dict(results["feasibility"], "/feasibility")
    feasible_flags = []
    for ticker, raw in feasibility.items():
        event = require_dict(raw, f"/feasibility/{ticker}")
        flag = event["exact_intraday_launch_did_feasible_with_free_data"]
        if not isinstance(flag, bool):
            raise TypeError(f"Expected boolean feasibility flag for {ticker}")
        feasible_flags.append(flag)
    if not feasible_flags:
        raise ValueError("No feasibility events found")
    unavailable = sum(not flag for flag in feasible_flags)

    fig = new_figure(panel)
    add_box(fig, 0.055, 0.745, 0.89, 0.075, facecolor=LIGHT, edgecolor=LIGHT)
    fig.text(
        0.078,
        0.783,
        f"{unavailable} / {len(feasible_flags)}",
        ha="left",
        va="center",
        fontsize=24,
        fontweight="bold",
        color=RED,
        zorder=3,
    )
    fig.text(
        0.205,
        0.783,
        "掛牌事件都缺少掛牌前的盤中紀錄，原題無法誠實檢驗",
        ha="left",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=INK,
        zorder=3,
    )
    add_text_card(
        fig,
        blocks[0],
        0.055,
        0.155,
        0.425,
        0.535,
        accent=BLUE,
        fill=PALE_BLUE,
        body_wrap=22,
        body_size=12.0,
    )
    add_text_card(
        fig,
        blocks[1],
        0.52,
        0.155,
        0.425,
        0.535,
        accent=RED,
        fill=PALE_RED,
        body_wrap=22,
        body_size=12.0,
    )
    label = source_label(plan, panel)
    add_footer(fig, label)
    save_panel(fig, panel, label)


def render_method(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    blocks = panel_blocks(panel)
    if len(blocks) != 4 or blocks[0].get("kind") != "text":
        raise ValueError("panel_method must contain one text block and three metrics")
    metrics = blocks[1:]
    values = [format_metric(block, results) for block in metrics]

    # These three proxy fields must exist even though their reader-facing names
    # come from the article/plan rather than the English result keys.
    proxies = require_dict(
        json_pointer(results, "/methodology/daily_proxies"),
        "/methodology/daily_proxies",
    )
    for key in ("abs_ret", "park_var", "signed_clv"):
        require_string(proxies[key], f"/methodology/daily_proxies/{key}")

    fig = new_figure(panel)
    add_text_card(
        fig,
        blocks[0],
        0.055,
        0.625,
        0.89,
        0.185,
        accent=BLUE,
        fill=WHITE,
        body_wrap=62,
        body_size=9.0,
        heading_size=13.5,
        paragraph_gap=False,
    )
    card_x = [0.055, 0.36, 0.665]
    card_colors = [(BLUE, PALE_BLUE), (TEAL, PALE_TEAL), (AMBER, PALE_AMBER)]
    for block, value, x, (accent, fill) in zip(
        metrics, values, card_x, card_colors, strict=True
    ):
        add_metric_card(
            fig, block, value, x, 0.36, 0.28, 0.225, accent=accent, fill=fill
        )

    add_box(fig, 0.055, 0.145, 0.89, 0.19, facecolor=NAVY_2, edgecolor=NAVY_2)
    columns = [
        (
            "① 每天看三件事",
            "開盤到收盤的變動幅度\n最高與最低價拉開的幅度\n順著當天方向收在極端",
        ),
        (
            "② 每檔配兩檔同業",
            "特斯拉：福特、通用\n輝達：超微、博通\nCoinbase：Robinhood、MicroStrategy",
        ),
        (
            "③ 做兩層比較",
            "先比標的股與同業的差距\n再比這個差距在掛牌前後\n有沒有額外變化",
        ),
    ]
    for index, (heading, body) in enumerate(columns):
        x = 0.078 + index * 0.295
        if index:
            fig.add_artist(
                Rectangle(
                    (x - 0.022, 0.165),
                    0.001,
                    0.145,
                    transform=fig.transFigure,
                    facecolor="#50657C",
                    edgecolor="none",
                    zorder=2,
                )
            )
        fig.text(
            x,
            0.294,
            heading,
            ha="left",
            va="top",
            fontsize=13.5,
            fontweight="bold",
            color=WHITE,
            zorder=3,
        )
        fig.text(
            x,
            0.251,
            body,
            ha="left",
            va="top",
            fontsize=10.2,
            color="#DFE8F1",
            linespacing=1.45,
            zorder=3,
        )
    label = source_label(plan, panel)
    add_footer(fig, label)
    save_panel(fig, panel, label)


def render_results(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    blocks = panel_blocks(panel)
    if len(blocks) != 4 or blocks[3].get("kind") != "text":
        raise ValueError("panel_results must contain three metrics and one text block")
    metric_blocks = blocks[:3]
    values = [
        format_metric(metric_blocks[0], results),
        format_metric(metric_blocks[1], results),
        # did_t is signed in the regression output.  This card explicitly asks
        # for strength in multiples of measurement error, so display magnitude,
        # matching the article's 1.30-times interpretation.
        format_metric(metric_blocks[2], results, magnitude=True) + " 倍",
    ]

    events = require_dict(results["event_results"], "/event_results")
    comparisons = 0
    significant = 0
    for event_name, raw_event in events.items():
        event = require_dict(raw_event, f"/event_results/{event_name}")
        for proxy_name, raw_proxy in event.items():
            proxy = require_dict(
                raw_proxy, f"/event_results/{event_name}/{proxy_name}"
            )
            p_value = require_number(
                proxy["did_p"], f"/event_results/{event_name}/{proxy_name}/did_p"
            )
            comparisons += 1
            significant += int(p_value < 0.05)
    if comparisons == 0:
        raise ValueError("No event comparisons found")

    fig = new_figure(panel)
    fig.text(
        0.945,
        0.886,
        f"{comparisons} 次比對｜{significant} 次達 5% 顯著門檻",
        ha="right",
        va="center",
        fontsize=11.5,
        color="#C9D6E3",
        zorder=3,
    )
    card_x = [0.055, 0.36, 0.665]
    card_colors = [(BLUE, PALE_BLUE), (AMBER, PALE_AMBER), (RED, PALE_RED)]
    for block, value, x, (accent, fill) in zip(
        metric_blocks, values, card_x, card_colors, strict=True
    ):
        add_metric_card(
            fig, block, value, x, 0.555, 0.28, 0.255, accent=accent, fill=fill
        )
    add_text_card(
        fig,
        blocks[3],
        0.055,
        0.145,
        0.89,
        0.35,
        accent=RED,
        fill=WHITE,
        body_wrap=48,
        body_size=11.5,
    )
    label = source_label(plan, panel)
    add_footer(fig, label)
    save_panel(fig, panel, label)


def render_takeaway(
    plan: dict[str, Any], results: dict[str, Any], panel: dict[str, Any]
) -> None:
    blocks = panel_blocks(panel)
    if len(blocks) != 3 or any(block.get("kind") != "text" for block in blocks):
        raise ValueError("panel_takeaway must contain exactly three text blocks")
    verdict = require_dict(results["verdict"], "/verdict")
    overall = require_string(verdict["overall"], "/verdict/overall")
    any_significant = verdict["daily_proxy_did_any_significant"]
    if not isinstance(any_significant, bool):
        raise TypeError("/verdict/daily_proxy_did_any_significant must be boolean")
    events = require_dict(results["event_results"], "/event_results")
    comparison_count = sum(
        len(require_dict(event, f"/event_results/{event_name}"))
        for event_name, event in events.items()
    )
    if comparison_count == 0:
        raise ValueError("No event comparisons found")
    detected_count = comparison_count if any_significant else 0

    fig = new_figure(panel)
    add_box(fig, 0.055, 0.74, 0.89, 0.075, facecolor=PALE_RED, edgecolor=PALE_RED)
    fig.text(
        0.078,
        0.778,
        f"結論等級：{overall}",
        ha="left",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=RED,
        zorder=3,
    )
    fig.text(
        0.925,
        0.778,
        f"{comparison_count} 次日頻比對中，{detected_count} 次量得出可辨識的新差距",
        ha="right",
        va="center",
        fontsize=14,
        fontweight="bold",
        color=INK,
        zorder=3,
    )
    add_text_card(
        fig,
        blocks[0],
        0.055,
        0.495,
        0.89,
        0.19,
        accent=RED,
        fill=WHITE,
        body_wrap=58,
        body_size=9.2,
        heading_size=13.5,
        paragraph_gap=False,
    )
    add_text_card(
        fig,
        blocks[1],
        0.055,
        0.145,
        0.425,
        0.325,
        accent=TEAL,
        fill=PALE_TEAL,
        body_wrap=24,
        body_size=10.2,
        heading_size=13.5,
    )
    add_text_card(
        fig,
        blocks[2],
        0.52,
        0.145,
        0.425,
        0.325,
        accent=BLUE,
        fill=PALE_BLUE,
        body_wrap=24,
        body_size=10.2,
        heading_size=13.5,
    )
    label = source_label(plan, panel)
    add_footer(fig, label)
    save_panel(fig, panel, label)


def main() -> None:
    plan = require_dict(load_json(PLAN_PATH), str(PLAN_PATH))
    results = require_dict(load_json(RESULTS_PATH), str(RESULTS_PATH))
    load_text(ARTICLE_PATH)
    verify_results_identity(plan)
    os.makedirs(OUT_DIR, exist_ok=True)

    renderers = {
        "panel_concept": render_concept,
        "panel_method": render_method,
        "panel_results": render_results,
        "panel_takeaway": render_takeaway,
    }
    for name, renderer in renderers.items():
        panel = panel_by_name(plan, name)
        renderer(plan, results, panel)


if __name__ == "__main__":
    main()
