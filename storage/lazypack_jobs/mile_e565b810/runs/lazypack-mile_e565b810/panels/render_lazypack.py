#!/usr/bin/env python3
"""Render the three data-bound PNG panels for VolPred lazypack mile_e565b810."""

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
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1096/k1096_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1096/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_e565b810/"
    "runs/lazypack-mile_e565b810/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_e565b810/"
    "runs/lazypack-mile_e565b810/panels/mile_e565b810_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_e565b810/"
    "runs/lazypack-mile_e565b810/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#172033"
MUTED = "#596477"
FAINT = "#8490A3"
LINE = "#DDE3EA"
PAPER = "#FFFFFF"
SOFT = "#F4F6F9"
NAVY = "#142A46"
BLUE = "#2F67A7"
BLUE_SOFT = "#EAF1F8"
TEAL = "#16827B"
TEAL_SOFT = "#E6F3F1"
RED = "#B84843"
RED_SOFT = "#F8EAE8"
AMBER = "#B47722"
AMBER_SOFT = "#F7F0E4"


EXPECTED_PATHS = {
    "1_full_sample": [
        "metadata.n_oos_actual",
        "full_oos_vs_gjr.gjr_vs_vix.dm_t",
        "full_oos_vs_gjr.gjr_vs_reg_voff.dm_t",
        "full_oos_vs_gjr.gjr_vs_adaptive.dm_t",
    ],
    "2_panic_window": [
        "vix_buckets_vs_gjr.High.n",
        "vix_buckets_vs_gjr.High.models.vix.dm_t",
        "vix_buckets_vs_gjr.High.models.reg_voff.dm_t",
        "vix_buckets_vs_gjr.High.models.adaptive.dm_t",
    ],
    "3_reading_rules": ["metadata.corr_window"],
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return text


def resolve_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing evidence field: {dotted_path}")
        current = current[part]
    return current


def require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {context}, got {type(value).__name__}")
    return value


def require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"Expected list at {context}, got {type(value).__name__}")
    return value


def panel_by_name(plan: dict[str, Any], name: str) -> dict[str, Any]:
    panels = require_list(plan["panels"], "plan.panels")
    matches = [require_dict(panel, f"plan.panels[{index}]") for index, panel in enumerate(panels) if isinstance(panel, dict) and panel.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one plan panel named {name}, found {len(matches)}")
    panel = matches[0]
    for key in ("title", "alt", "sources", "blocks"):
        if key not in panel:
            raise KeyError(f"Missing plan field: panel {name}.{key}")
    if panel["sources"] != ["result"]:
        raise ValueError(f"Panel {name} must bind to result evidence")
    return panel


def metric_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = require_list(panel["blocks"], f"panel {panel['name']}.blocks")
    return [require_dict(block, f"panel {panel['name']}.blocks") for block in blocks if isinstance(block, dict) and block.get("kind") == "metric"]


def validate_panel_contract(panel: dict[str, Any]) -> None:
    name = str(panel["name"])
    paths = []
    for block in metric_blocks(panel):
        value = require_dict(block["value"], f"panel {name} metric.value")
        if value.get("source") != "result":
            raise ValueError(f"Panel {name} metric must use result source")
        if "path" not in value or "format" not in value:
            raise KeyError(f"Panel {name} metric is missing path or format")
        paths.append(value["path"])
    if paths != EXPECTED_PATHS[name]:
        raise ValueError(f"Panel {name} evidence paths differ from the required contract: {paths}")


def format_metric(result: dict[str, Any], block: dict[str, Any]) -> str:
    value_spec = require_dict(block["value"], "metric.value")
    path = str(value_spec["path"])
    raw = resolve_path(result, path)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}, got {type(raw).__name__}")
    numeric = float(raw)
    if not math.isfinite(numeric):
        raise ValueError(f"Non-finite evidence value at {path}: {raw}")

    fmt = require_dict(value_spec["format"], f"format for {path}")
    kind = fmt["kind"]
    suffix = str(fmt.get("suffix", ""))
    if kind == "integer":
        if not numeric.is_integer():
            raise ValueError(f"Expected integer-valued evidence at {path}, got {raw}")
        rendered = f"{int(numeric):,d}"
    elif kind == "number":
        digits = int(fmt["digits"])
        rendered = f"{numeric:+.{digits}f}" if fmt.get("show_plus") else f"{numeric:.{digits}f}"
    else:
        raise ValueError(f"Unsupported format kind for {path}: {kind}")
    return rendered + suffix


def make_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
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
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.018,
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


def wrapped(text: str, width: int) -> str:
    return "\n".join(
        textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
    )


def footer(ax: plt.Axes, experiment_id: str) -> None:
    ax.plot([0.055, 0.945], [0.092, 0.092], color=LINE, linewidth=1.1)
    ax.text(
        0.055,
        0.052,
        f"資料來源：experiment {experiment_id}",
        fontsize=14,
        color=MUTED,
        va="center",
        ha="left",
    )
    ax.text(
        0.945,
        0.052,
        "VolPred｜研究展示，非投資建議",
        fontsize=13,
        color=FAINT,
        va="center",
        ha="right",
    )


def draw_metric_card(
    ax: plt.Axes,
    block: dict[str, Any],
    value: str,
    box: tuple[float, float, float, float],
    *,
    facecolor: str,
    accent: str,
    value_size: int = 43,
    note_wrap_width: int = 8,
) -> None:
    x, y, width, height = box
    rounded_box(ax, x, y, width, height, facecolor=facecolor, edgecolor=LINE, linewidth=0.8)
    ax.add_patch(Rectangle((x, y), 0.008, height, facecolor=accent, edgecolor="none"))
    ax.text(x + 0.034, y + height - 0.035, str(block["label"]), fontsize=18, color=MUTED, va="top", ha="left")
    ax.text(x + 0.034, y + height * 0.51, value, fontsize=value_size, fontweight="bold", color=INK, va="center", ha="left")
    note = block.get("note")
    if note:
        ax.text(
            x + 0.034,
            y + 0.020,
            wrapped(str(note), note_wrap_width),
            fontsize=15,
            color=accent,
            va="bottom",
            ha="left",
            linespacing=1.2,
        )


def render_full_sample(result: dict[str, Any], panel: dict[str, Any], experiment_id: str) -> None:
    blocks = metric_blocks(panel)
    values = [format_metric(result, block) for block in blocks]
    fig, ax = make_canvas()

    ax.text(0.055, 0.925, str(panel["title"]), fontsize=35, fontweight="bold", color=INK, va="top", ha="left")
    ax.text(0.055, 0.848, "完整樣本外比較｜比較強度 DM t", fontsize=17, color=MUTED, va="top", ha="left")
    ax.text(0.945, 0.851, "嚴格門檻：|t| > 3", fontsize=15, color=FAINT, va="top", ha="right")

    rounded_box(ax, 0.055, 0.185, 0.335, 0.565, facecolor=NAVY)
    ax.text(0.089, 0.690, str(blocks[0]["label"]), fontsize=16, color="#B9C7D8", va="top", ha="left")
    ax.text(0.089, 0.485, values[0], fontsize=50, fontweight="bold", color="white", va="center", ha="left")
    ax.text(0.089, 0.285, "相同期間\n公平比較四種用法", fontsize=18, color="#DCE5EF", va="bottom", ha="left", linespacing=1.45)

    draw_metric_card(
        ax,
        blocks[1],
        values[1],
        (0.425, 0.465, 0.245, 0.285),
        facecolor=TEAL_SOFT,
        accent=TEAL,
        note_wrap_width=8,
    )
    draw_metric_card(
        ax,
        blocks[2],
        values[2],
        (0.700, 0.465, 0.245, 0.285),
        facecolor=BLUE_SOFT,
        accent=BLUE,
        note_wrap_width=8,
    )
    draw_metric_card(
        ax,
        blocks[3],
        values[3],
        (0.425, 0.185, 0.520, 0.235),
        facecolor=RED_SOFT,
        accent=RED,
        value_size=46,
        note_wrap_width=18,
    )
    ax.text(0.915, 0.302, "未過線", fontsize=18, fontweight="bold", color=RED, va="center", ha="right")

    footer(ax, experiment_id)
    fig.savefig(os.path.join(out_dir, "1_full_sample.png"), dpi=DPI, facecolor=PAPER)
    plt.close(fig)


def render_panic_window(result: dict[str, Any], panel: dict[str, Any], experiment_id: str) -> None:
    blocks = metric_blocks(panel)
    values = [format_metric(result, block) for block in blocks]
    fig, ax = make_canvas()

    ax.add_patch(Rectangle((0, 0.735), 1, 0.265, facecolor=NAVY, edgecolor="none"))
    ax.text(0.055, 0.925, str(panel["title"]), fontsize=35, fontweight="bold", color="white", va="top", ha="left")
    ax.text(0.055, 0.845, "前一日 VIX 介於 25–40｜局部比較強度 DM t", fontsize=17, color="#C9D5E2", va="top", ha="left")
    ax.text(0.945, 0.845, "負值＝方向較差", fontsize=15, color="#AEBFD0", va="top", ha="right")

    card_y = 0.205
    card_h = 0.425
    card_w = 0.205
    xs = [0.055, 0.285, 0.515, 0.745]
    faces = [SOFT, RED_SOFT, TEAL_SOFT, RED_SOFT]
    accents = [NAVY, RED, TEAL, RED]
    for block, value, x, face, accent in zip(blocks, values, xs, faces, accents, strict=True):
        draw_metric_card(
            ax,
            block,
            value,
            (x, card_y, card_w, card_h),
            facecolor=face,
            accent=accent,
            value_size=40,
            note_wrap_width=7,
        )

    ax.text(0.055, 0.680, "同一高恐慌區間、同一基準", fontsize=16, color=MUTED, va="center", ha="left")
    ax.plot([0.330, 0.945], [0.680, 0.680], color=LINE, linewidth=1.2)

    footer(ax, experiment_id)
    fig.savefig(os.path.join(out_dir, "2_panic_window.png"), dpi=DPI, facecolor=PAPER)
    plt.close(fig)


def text_blocks(panel: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = require_list(panel["blocks"], f"panel {panel['name']}.blocks")
    found = [require_dict(block, f"panel {panel['name']} text block") for block in blocks if isinstance(block, dict) and block.get("kind") == "text"]
    if len(found) != 3:
        raise ValueError(f"Panel {panel['name']} must contain exactly three text blocks")
    for block in found:
        if "heading" not in block or "body" not in block:
            raise KeyError(f"Panel {panel['name']} text block lacks heading or body")
        body = require_list(block["body"], f"panel {panel['name']} text body")
        if len(body) != 1 or not isinstance(body[0], str) or not body[0].strip():
            raise ValueError(f"Panel {panel['name']} text body must contain one non-empty paragraph")
    return found


def render_reading_rules(result: dict[str, Any], panel: dict[str, Any], experiment_id: str) -> None:
    texts = text_blocks(panel)
    metric = metric_blocks(panel)[0]
    value = format_metric(result, metric)
    fig, ax = make_canvas()

    ax.text(0.055, 0.925, str(panel["title"]), fontsize=35, fontweight="bold", color=INK, va="top", ha="left")
    ax.plot([0.055, 0.945], [0.832, 0.832], color=INK, linewidth=1.5)

    rounded_box(ax, 0.055, 0.195, 0.365, 0.575, facecolor=NAVY)
    ax.text(0.090, 0.690, "局部改善", fontsize=22, color="#D8E5F0", va="top", ha="left")
    ax.text(0.2375, 0.535, "≠", fontsize=68, fontweight="bold", color="#75C5BD", va="center", ha="center")
    ax.text(0.090, 0.390, "整體勝出", fontsize=31, fontweight="bold", color="white", va="center", ha="left")
    ax.text(0.090, 0.284, "兩張成績單\n必須分開閱讀", fontsize=18, color="#C7D5E2", va="top", ha="left", linespacing=1.4)

    y_positions = [0.620, 0.435, 0.250]
    numerals = ["一", "二", "三"]
    for block, y, numeral in zip(texts, y_positions, numerals, strict=True):
        ax.text(0.470, y + 0.083, numeral, fontsize=14, fontweight="bold", color=BLUE, va="center", ha="center", bbox={"boxstyle": "circle,pad=0.42", "facecolor": BLUE_SOFT, "edgecolor": "none"})
        ax.text(0.510, y + 0.105, str(block["heading"]), fontsize=20, fontweight="bold", color=INK, va="top", ha="left")
        body = require_list(block["body"], "reading-rule body")[0]
        ax.text(0.510, y + 0.052, wrapped(str(body), 20), fontsize=15.5, color=MUTED, va="top", ha="left", linespacing=1.35)
        if y > 0.250:
            ax.plot([0.470, 0.945], [y - 0.025, y - 0.025], color=LINE, linewidth=1.0)

    rounded_box(ax, 0.055, 0.105, 0.365, 0.078, facecolor=AMBER_SOFT)
    ax.text(0.077, 0.158, str(metric["label"]), fontsize=13.5, color=AMBER, va="center", ha="left")
    ax.text(0.397, 0.158, value, fontsize=18, fontweight="bold", color=INK, va="center", ha="right")
    ax.text(0.077, 0.126, str(metric.get("note", "")), fontsize=12, color=MUTED, va="center", ha="left")

    footer(ax, experiment_id)
    fig.savefig(os.path.join(out_dir, "3_reading_rules.png"), dpi=DPI, facecolor=PAPER)
    plt.close(fig)


def main() -> None:
    result = require_dict(load_json(RESULT_PATH), "results.json")
    plan = require_dict(load_json(PLAN_PATH), "plan.json")
    load_text(README_PATH)
    load_text(ARTICLE_PATH)

    experiment_id = resolve_path(result, "metadata.experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise TypeError("metadata.experiment_id must be a non-empty string")

    panels = {name: panel_by_name(plan, name) for name in EXPECTED_PATHS}
    for panel in panels.values():
        validate_panel_contract(panel)

    os.makedirs(out_dir, exist_ok=True)
    render_full_sample(result, panels["1_full_sample"], experiment_id)
    render_panic_window(result, panels["2_panic_window"], experiment_id)
    render_reading_rules(result, panels["3_reading_rules"], experiment_id)


if __name__ == "__main__":
    main()
