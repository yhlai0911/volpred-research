#!/usr/bin/env python3
"""Render the K1386 general-reader lazypack panels as standalone PNG files."""

import json
import os
import textwrap
from collections.abc import Mapping

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULT_PATH = "/Users/yhlai0911/volpred-research/experiments/k1386/k1386_results.json"
README_PATH = "/Users/yhlai0911/volpred-research/experiments/k1386/README.md"
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_8e086903/runs/lazypack-mile_8e086903-r2/plan.json"
ARTICLE_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_8e086903/runs/lazypack-mile_8e086903-r2/panels/mile_8e086903_article.md"
out_dir = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_8e086903/runs/lazypack-mile_8e086903-r2/panels"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["savefig.facecolor"] = "white"


INK = "#17243A"
MUTED = "#5D6B7E"
BLUE = "#2563EB"
TEAL = "#0F766E"
AMBER = "#D97706"
RED = "#B5483A"
PALE_BLUE = "#EFF6FF"
PALE_TEAL = "#ECFDF5"
PALE_AMBER = "#FFF7E8"
PALE_RED = "#FFF3F0"
PAPER = "#F7F8FA"
LINE = "#DCE2EA"


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def load_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        value = handle.read()
    if not value.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return value


def require_path(root, dotted_path):
    current = root
    for key in dotted_path.split("."):
        if not isinstance(current, Mapping) or key not in current:
            raise KeyError(f"Missing required evidence field: {dotted_path}")
        current = current[key]
    return current


def require_panel(plan, name):
    panels = require_path(plan, "panels")
    if not isinstance(panels, list):
        raise TypeError("plan.panels must be a list")
    matches = [panel for panel in panels if panel.get("name") == name]
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one panel named {name}")
    panel = matches[0]
    for field in ("title", "alt", "sources", "blocks"):
        require_path(panel, field)
    return panel


def require_block(panel, label=None, heading=None):
    blocks = require_path(panel, "blocks")
    if not isinstance(blocks, list):
        raise TypeError(f"{panel['name']}.blocks must be a list")
    if label is not None:
        matches = [block for block in blocks if block.get("label") == label]
        description = f"label {label}"
    else:
        matches = [block for block in blocks if block.get("heading") == heading]
        description = f"heading {heading}"
    if len(matches) != 1:
        raise KeyError(f"Expected exactly one block with {description}")
    return matches[0]


def metric_value(result, block):
    value_spec = require_path(block, "value")
    if require_path(value_spec, "source") != "result":
        raise ValueError(f"Unsupported metric source for {block.get('label')}")
    raw = require_path(result, require_path(value_spec, "path"))
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"Metric {value_spec['path']} must be numeric")
    fmt = require_path(value_spec, "format")
    kind = require_path(fmt, "kind")
    prefix = fmt.get("prefix", "")
    suffix = fmt.get("suffix", "")
    if kind == "integer":
        if isinstance(raw, float) and not raw.is_integer():
            raise ValueError(f"Metric {value_spec['path']} is not an integer")
        rendered = f"{int(raw):,d}"
    elif kind == "number":
        digits = require_path(fmt, "digits")
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits for {value_spec['path']}")
        rendered = f"{raw:.{digits}f}"
    else:
        raise ValueError(f"Unsupported format kind: {kind}")
    return f"{prefix}{rendered}{suffix}"


def wrap_zh(text, width):
    return textwrap.fill(
        str(text),
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )


def new_canvas():
    fig = plt.figure(figsize=(1600 / 150, 1000 / 150), dpi=150, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def rounded_box(ax, x, y, w, h, facecolor, edgecolor="none", linewidth=1.2, radius=0.018):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def draw_footer(ax, experiment_id):
    ax.plot([0.055, 0.945], [0.098, 0.098], color=LINE, linewidth=1.0)
    ax.text(
        0.055,
        0.052,
        f"資料來源：experiment {experiment_id}",
        ha="left",
        va="center",
        fontsize=11.5,
        color=MUTED,
    )
    ax.text(
        0.945,
        0.052,
        "VolPred 研究展示｜非投資建議",
        ha="right",
        va="center",
        fontsize=11.5,
        color=MUTED,
    )


def draw_panel_header(ax, panel, dark=False):
    if dark:
        ax.add_patch(Rectangle((0, 0.80), 1, 0.20, facecolor=INK, edgecolor="none"))
        title_color = "white"
        subtitle_color = "#CBD5E1"
        title_y = 0.914
        subtitle_y = 0.847
    else:
        title_color = INK
        subtitle_color = MUTED
        title_y = 0.922
        subtitle_y = 0.854
    ax.text(
        0.055,
        title_y,
        require_path(panel, "title"),
        ha="left",
        va="center",
        fontsize=30,
        fontweight="bold",
        color=title_color,
    )
    ax.text(
        0.057,
        subtitle_y,
        require_path(panel, "alt"),
        ha="left",
        va="center",
        fontsize=15,
        color=subtitle_color,
    )


def render_scoreboard(result, panel, experiment_id):
    fig, ax = new_canvas()
    draw_panel_header(ax, panel)

    rounded_box(ax, 0.773, 0.817, 0.172, 0.052, PALE_BLUE, edgecolor="#C7D9FE", radius=0.026)
    ax.text(
        0.859,
        0.843,
        "QLIKE 越低越好",
        ha="center",
        va="center",
        fontsize=12.5,
        fontweight="bold",
        color=BLUE,
    )

    cards = [
        ("HAR 預測損失", 0.055, 0.455, PALE_BLUE, BLUE, True),
        ("單市場近似", 0.515, 0.455, PAPER, AMBER, False),
        ("跨市場近似", 0.055, 0.165, PAPER, RED, False),
        ("可評分預測", 0.515, 0.165, PALE_TEAL, TEAL, False),
    ]
    for label, x, y, fill, accent, primary in cards:
        block = require_block(panel, label=label)
        value = metric_value(result, block)
        rounded_box(ax, x, y, 0.43, 0.245, fill, edgecolor=LINE, radius=0.022)
        ax.add_patch(Rectangle((x, y + 0.225), 0.43, 0.020, facecolor=accent, edgecolor="none"))
        ax.text(
            x + 0.034,
            y + 0.176,
            require_path(block, "label"),
            ha="left",
            va="center",
            fontsize=17,
            fontweight="bold",
            color=INK,
        )
        ax.text(
            x + 0.034,
            y + 0.082,
            value,
            ha="left",
            va="center",
            fontsize=39 if primary else 36,
            fontweight="bold",
            color=accent if primary else INK,
        )
        ax.add_patch(
            FancyBboxPatch(
                (x + 0.365, y + 0.164),
                0.030,
                0.030,
                boxstyle="round,pad=0.005,rounding_size=0.010",
                facecolor=accent,
                edgecolor="none",
            )
        )

    draw_footer(ax, experiment_id)
    fig.savefig(os.path.join(out_dir, "1_scoreboard.png"), dpi=150, facecolor="white")
    plt.close(fig)


def render_rough_not_better(result, panel, experiment_id):
    fig, ax = new_canvas()
    draw_panel_header(ax, panel, dark=True)

    ax.text(
        0.055,
        0.734,
        "樣本內路徑診斷｜粗糙度 H",
        ha="left",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=TEAL,
    )
    ax.text(
        0.535,
        0.734,
        "樣本外預測驗收｜HAC-DM 比較",
        ha="left",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=RED,
    )

    cards = [
        ("SPY 粗糙度", 0.055, PALE_TEAL, TEAL),
        ("QQQ 粗糙度", 0.285, PALE_TEAL, TEAL),
        ("單市場比較強度", 0.535, PALE_RED, RED),
        ("跨市場比較強度", 0.765, PALE_RED, RED),
    ]
    for label, x, fill, accent in cards:
        block = require_block(panel, label=label)
        value = metric_value(result, block)
        rounded_box(ax, x, 0.385, 0.19, 0.285, fill, edgecolor=LINE, radius=0.018)
        ax.add_patch(Rectangle((x, 0.385), 0.012, 0.285, facecolor=accent, edgecolor="none"))
        ax.text(
            x + 0.027,
            0.615,
            wrap_zh(require_path(block, "label"), 9),
            ha="left",
            va="top",
            fontsize=15,
            fontweight="bold",
            color=INK,
            linespacing=1.18,
        )
        ax.text(
            x + 0.027,
            0.514,
            value,
            ha="left",
            va="center",
            fontsize=34,
            fontweight="bold",
            color=accent,
        )
        if "note" in block:
            ax.text(
                x + 0.027,
                0.432,
                wrap_zh(require_path(block, "note"), 10),
                ha="left",
                va="bottom",
                fontsize=11.2,
                color=MUTED,
                linespacing=1.25,
            )
        else:
            ax.text(
                x + 0.027,
                0.434,
                "H 越低，路徑越粗糙",
                ha="left",
                va="bottom",
                fontsize=11.2,
                color=MUTED,
            )

    rounded_box(ax, 0.055, 0.165, 0.89, 0.125, "white", edgecolor=LINE, radius=0.018)
    ax.add_patch(Rectangle((0.055, 0.165), 0.010, 0.125, facecolor=BLUE, edgecolor="none"))
    ax.text(
        0.09,
        0.228,
        "粗糙度描述路徑；比較強度驗收預測。兩者不能互相替代。",
        ha="left",
        va="center",
        fontsize=19,
        fontweight="bold",
        color=INK,
    )

    draw_footer(ax, experiment_id)
    fig.savefig(os.path.join(out_dir, "2_rough_not_better.png"), dpi=150, facecolor="white")
    plt.close(fig)


def render_reading_rule(result, panel, experiment_id):
    fig, ax = new_canvas()
    draw_panel_header(ax, panel)
    ax.plot([0.055, 0.945], [0.806, 0.806], color=INK, linewidth=2.0)

    rounded_box(ax, 0.055, 0.285, 0.335, 0.455, INK, radius=0.022)
    ax.text(
        0.085,
        0.682,
        "閱讀時先拆開",
        ha="left",
        va="center",
        fontsize=15,
        fontweight="bold",
        color="#93C5FD",
    )
    ax.text(
        0.2225,
        0.584,
        "路徑形狀",
        ha="center",
        va="center",
        fontsize=27,
        fontweight="bold",
        color="white",
    )
    ax.text(
        0.2225,
        0.502,
        "不等於",
        ha="center",
        va="center",
        fontsize=17,
        color="#CBD5E1",
    )
    ax.plot([0.120, 0.325], [0.465, 0.465], color="#475569", linewidth=1.2)
    ax.text(
        0.2225,
        0.388,
        "預測準度",
        ha="center",
        va="center",
        fontsize=27,
        fontweight="bold",
        color="white",
    )

    seed_block = require_block(panel, label="固定隨機種子")
    rounded_box(ax, 0.055, 0.145, 0.335, 0.095, PALE_AMBER, edgecolor="#F3D7A3", radius=0.018)
    ax.text(
        0.083,
        0.193,
        require_path(seed_block, "label"),
        ha="left",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.355,
        0.193,
        metric_value(result, seed_block),
        ha="right",
        va="center",
        fontsize=27,
        fontweight="bold",
        color=AMBER,
    )

    text_specs = [
        ("分開兩個問題", 0.585, BLUE, PALE_BLUE, "辨"),
        ("守住時間順序", 0.365, TEAL, PALE_TEAL, "時"),
        ("不要過度外推", 0.145, AMBER, PALE_AMBER, "界"),
    ]
    for heading, y, accent, fill, glyph in text_specs:
        block = require_block(panel, heading=heading)
        body = require_path(block, "body")
        if not isinstance(body, list) or not body or not all(isinstance(item, str) for item in body):
            raise TypeError(f"Body for {heading} must be a non-empty string list")
        rounded_box(ax, 0.435, y, 0.51, 0.165, fill, edgecolor=LINE, radius=0.018)
        rounded_box(ax, 0.458, y + 0.085, 0.052, 0.052, accent, radius=0.026)
        ax.text(
            0.484,
            y + 0.111,
            glyph,
            ha="center",
            va="center",
            fontsize=15,
            fontweight="bold",
            color="white",
        )
        ax.text(
            0.532,
            y + 0.112,
            require_path(block, "heading"),
            ha="left",
            va="center",
            fontsize=17,
            fontweight="bold",
            color=INK,
        )
        ax.text(
            0.458,
            y + 0.055,
            wrap_zh("".join(body), 26),
            ha="left",
            va="top",
            fontsize=13.6,
            color=MUTED,
            linespacing=1.28,
        )

    draw_footer(ax, experiment_id)
    fig.savefig(os.path.join(out_dir, "3_reading_rule.png"), dpi=150, facecolor="white")
    plt.close(fig)


def validate_evidence(result, plan, readme, article):
    experiment_id = require_path(result, "experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id.startswith("K"):
        raise ValueError("result.experiment_id must be a K-prefixed string")
    if experiment_id not in readme or experiment_id not in article:
        raise ValueError("README/article evidence does not identify the result experiment")
    sources = require_path(plan, "evidence")
    require_path(sources, "result.path")
    for panel_name in ("1_scoreboard", "2_rough_not_better", "3_reading_rule"):
        panel = require_panel(plan, panel_name)
        if require_path(panel, "sources") != ["result"]:
            raise ValueError(f"Unexpected evidence sources for {panel_name}")
    return experiment_id


def main():
    result = load_json(RESULT_PATH)
    plan = load_json(PLAN_PATH)
    readme = load_text(README_PATH)
    article = load_text(ARTICLE_PATH)
    experiment_id = validate_evidence(result, plan, readme, article)

    os.makedirs(out_dir, exist_ok=True)
    render_scoreboard(result, require_panel(plan, "1_scoreboard"), experiment_id)
    render_rough_not_better(result, require_panel(plan, "2_rough_not_better"), experiment_id)
    render_reading_rule(result, require_panel(plan, "3_reading_rule"), experiment_id)


if __name__ == "__main__":
    main()
