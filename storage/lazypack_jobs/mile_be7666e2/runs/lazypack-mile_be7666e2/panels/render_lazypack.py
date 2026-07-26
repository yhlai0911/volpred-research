#!/usr/bin/env python3
"""Render the three data-bound PNG panels for the mile_be7666e2 lazypack."""

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
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_be7666e2/runs/lazypack-mile_be7666e2/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1686/"
    "k1686_contemporaneous_null_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_be7666e2/runs/lazypack-mile_be7666e2/panels/"
    "mile_be7666e2_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_be7666e2/runs/lazypack-mile_be7666e2/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

NAVY = "#102A43"
NAVY_2 = "#183B56"
BLUE = "#176B87"
TEAL = "#0E7C7B"
GREEN = "#2A7A5E"
AMBER = "#C07A22"
RED = "#B4473C"
INK = "#172B3A"
MUTED = "#526575"
PALE = "#F4F7FA"
LINE = "#D8E1E8"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"{path} 的頂層必須是 JSON object")
    return value


def load_text(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    if not value.strip():
        raise ValueError(f"{path} 不可為空")
    return value


def verify_results_hash(plan: dict[str, Any]) -> None:
    expected = plan["evidence"]["results"]["sha256"]
    actual = hashlib.sha256(RESULTS_PATH.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(
            f"results evidence SHA-256 不符：plan={expected}, actual={actual}"
        )


def panel_named(plan: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [panel for panel in plan["panels"] if panel["name"] == name]
    if len(matches) != 1:
        raise KeyError(f"plan 必須恰有一個 panel：{name}")
    return matches[0]


def text_block(panel: dict[str, Any], heading: str) -> dict[str, Any]:
    matches = [
        block
        for block in panel["blocks"]
        if block["kind"] == "text" and block["heading"] == heading
    ]
    if len(matches) != 1:
        raise KeyError(f"{panel['name']} 缺少文字區塊：{heading}")
    body = matches[0]["body"]
    if not isinstance(body, list) or not body or not all(
        isinstance(item, str) and item for item in body
    ):
        raise TypeError(f"{panel['name']} 的 {heading} body 格式錯誤")
    return matches[0]


def metric_block(panel: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [
        block
        for block in panel["blocks"]
        if block["kind"] == "metric" and block["label"] == label
    ]
    if len(matches) != 1:
        raise KeyError(f"{panel['name']} 缺少數字區塊：{label}")
    return matches[0]


def resolve_value(data: Any, path: str) -> Any:
    if not isinstance(path, str) or not path:
        raise ValueError("evidence path 不可為空")
    parts = path[1:].split("/") if path.startswith("/") else path.split("/")
    current = data
    for raw_part in parts:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"evidence 欄位不存在：{path}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"evidence 欄位不存在：{path}") from exc
        else:
            raise KeyError(f"evidence 欄位不存在：{path}")
    if current is None:
        raise ValueError(f"evidence 欄位不可為 null：{path}")
    return current


def format_metric(
    block: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> str:
    value_spec = block["value"]
    source = value_spec["source"]
    if source not in evidence:
        raise KeyError(f"未知 evidence source：{source}")
    path = value_spec["path"]
    value = resolve_value(evidence[source], path)
    format_spec = value_spec["format"]
    kind = format_spec["kind"]
    suffix = format_spec.get("suffix", "")

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{path} 必須是數字")
        digits = format_spec["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise TypeError(f"{path} 的 digits 必須是非負整數")
        return f"{value:.{digits}f}{suffix}"

    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{path} 必須是整數")
        if int(value) != value:
            raise ValueError(f"{path} 不是整數：{value}")
        return f"{int(value):,}{suffix}"

    if kind == "text":
        if not isinstance(value, str):
            raise TypeError(f"{path} 必須是文字")
        # Results stores the separator in English; only the separator is localized.
        return value.replace(" to ", " 至 ") + suffix

    raise ValueError(f"不支援的 format.kind：{kind}")


def wrap(text: str, width: int) -> str:
    return textwrap.fill(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )


def canvas() -> tuple[Any, Any]:
    figure = plt.figure(
        figsize=(WIDTH / DPI, HEIGHT / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    axis = figure.add_axes([0, 0, 1, 1])
    axis.set_xlim(0, WIDTH)
    axis.set_ylim(0, HEIGHT)
    axis.axis("off")
    return figure, axis


def rounded_box(
    axis: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    linewidth: float = 1.5,
    radius: float = 20,
) -> None:
    axis.add_patch(
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


def draw_header(axis: Any, panel: dict[str, Any]) -> None:
    axis.add_patch(
        FancyBboxPatch(
            (0, 820),
            WIDTH,
            180,
            boxstyle="square,pad=0",
            facecolor=NAVY,
            edgecolor=NAVY,
        )
    )
    axis.text(
        70,
        927,
        panel["title"],
        color=WHITE,
        fontsize=31,
        fontweight="bold",
        va="center",
        ha="left",
    )
    axis.text(
        70,
        860,
        panel["alt"],
        color="#DCE8F2",
        fontsize=17,
        va="center",
        ha="left",
    )


def source_text(
    plan: dict[str, Any], panel: dict[str, Any]
) -> str:
    sources = panel["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"{panel['name']} 必須至少有一個 source")
    labels = []
    for source in sources:
        label = plan["evidence"][source]["label"]
        if not isinstance(label, str) or not label:
            raise ValueError(f"{source} 的讀者向 label 不可為空")
        labels.append(label)
    return "資料來源：" + "、".join(labels)


def draw_footer(axis: Any, plan: dict[str, Any], panel: dict[str, Any]) -> None:
    axis.plot([70, 1530], [82, 82], color=LINE, linewidth=1.2)
    axis.text(
        70,
        42,
        source_text(plan, panel),
        color=MUTED,
        fontsize=12,
        va="center",
        ha="left",
    )


def draw_metric_card(
    axis: Any,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    value: str,
    accent: str,
    label_y_offset: float,
    value_y_offset: float,
    label_wrap: int = 24,
    value_size: int = 38,
) -> None:
    rounded_box(axis, x, y, width, height, facecolor=WHITE)
    axis.add_patch(
        FancyBboxPatch(
            (x, y),
            10,
            height,
            boxstyle="round,pad=0,rounding_size=5",
            facecolor=accent,
            edgecolor=accent,
        )
    )
    axis.text(
        x + 38,
        y + label_y_offset,
        wrap(label, label_wrap),
        color=MUTED,
        fontsize=15,
        fontweight="bold",
        va="top",
        ha="left",
        linespacing=1.25,
    )
    axis.text(
        x + 38,
        y + value_y_offset,
        value,
        color=accent,
        fontsize=value_size,
        fontweight="bold",
        va="center",
        ha="left",
    )


def render_concept(
    plan: dict[str, Any],
    results: dict[str, Any],
) -> None:
    panel = panel_named(plan, "1_concept")
    copy = text_block(panel, "這篇在講什麼")
    decline = metric_block(panel, "平靜→恐慌 衝擊放大比落差")
    sample = metric_block(panel, "樣本")
    evidence = {"results": results}

    figure, axis = canvas()
    draw_header(axis, panel)

    rounded_box(axis, 70, 170, 870, 590, facecolor=PALE, edgecolor=PALE)
    axis.text(
        115,
        710,
        copy["heading"],
        color=NAVY,
        fontsize=22,
        fontweight="bold",
        va="top",
        ha="left",
    )
    axis.plot([115, 890], [673, 673], color=LINE, linewidth=1.4)
    axis.text(
        115,
        630,
        wrap(copy["body"][0], 17),
        color=INK,
        fontsize=19,
        va="top",
        ha="left",
        linespacing=1.45,
    )
    axis.text(
        115,
        500,
        wrap(copy["body"][1], 17),
        color=INK,
        fontsize=19,
        va="top",
        ha="left",
        linespacing=1.45,
    )
    axis.add_patch(
        FancyArrowPatch(
            (825, 345),
            (825, 235),
            arrowstyle="-|>",
            mutation_scale=30,
            linewidth=5,
            color=TEAL,
        )
    )

    draw_metric_card(
        axis,
        x=990,
        y=470,
        width=540,
        height=290,
        label=decline["label"],
        value=format_metric(decline, evidence),
        accent=TEAL,
        label_y_offset=230,
        value_y_offset=96,
        label_wrap=18,
        value_size=46,
    )
    draw_metric_card(
        axis,
        x=990,
        y=170,
        width=540,
        height=260,
        label=sample["label"],
        value=format_metric(sample, evidence),
        accent=BLUE,
        label_y_offset=200,
        value_y_offset=90,
        value_size=36,
    )
    draw_footer(axis, plan, panel)
    save_panel(figure, panel["name"])


def render_method(
    plan: dict[str, Any],
    results: dict[str, Any],
) -> None:
    panel = panel_named(plan, "2_method")
    method = text_block(panel, "作法")
    simulations = metric_block(panel, "假世界模擬路徑")
    sample_period = metric_block(panel, "樣本期間")
    evidence = {"results": results}

    figure, axis = canvas()
    draw_header(axis, panel)
    axis.text(
        70,
        772,
        method["heading"],
        color=NAVY,
        fontsize=21,
        fontweight="bold",
        va="center",
        ha="left",
    )

    card_positions = [(70, 460), (570, 460), (1070, 460)]
    card_accents = [BLUE, TEAL, GREEN]
    for (x, y), accent, body in zip(
        card_positions, card_accents, method["body"], strict=True
    ):
        rounded_box(axis, x, y, 460, 265, facecolor=PALE)
        axis.plot(
            [x + 30, x + 100],
            [y + 222, y + 222],
            color=accent,
            linewidth=5,
            solid_capstyle="round",
        )
        axis.text(
            x + 30,
            y + 190,
            wrap(body, 12),
            color=INK,
            fontsize=14,
            va="top",
            ha="left",
            linespacing=1.4,
        )

    for x_start, x_end in ((535, 565), (1035, 1065)):
        axis.add_patch(
            FancyArrowPatch(
                (x_start, 592),
                (x_end, 592),
                arrowstyle="-|>",
                mutation_scale=17,
                linewidth=2,
                color=MUTED,
            )
        )

    draw_metric_card(
        axis,
        x=70,
        y=160,
        width=700,
        height=240,
        label=simulations["label"],
        value=format_metric(simulations, evidence),
        accent=TEAL,
        label_y_offset=185,
        value_y_offset=82,
        value_size=39,
    )
    draw_metric_card(
        axis,
        x=830,
        y=160,
        width=700,
        height=240,
        label=sample_period["label"],
        value=format_metric(sample_period, evidence),
        accent=BLUE,
        label_y_offset=185,
        value_y_offset=82,
        value_size=25,
    )
    draw_footer(axis, plan, panel)
    save_panel(figure, panel["name"])


def render_results(
    plan: dict[str, Any],
    results: dict[str, Any],
) -> None:
    panel = panel_named(plan, "3_results")
    old_test = metric_block(panel, "舊版檢定（時間標錯一天）p 值")
    corrected_test = metric_block(panel, "修正後主檢定 p 值（一度失守）")
    surviving_gap = metric_block(panel, "存活規格 真實落差")
    surviving_p = metric_block(panel, "存活規格 p 值")
    conclusion = text_block(panel, "結論與限制")
    evidence = {"results": results}

    figure, axis = canvas()
    draw_header(axis, panel)

    cards = [
        (70, 590, old_test, BLUE),
        (810, 590, corrected_test, RED),
        (70, 390, surviving_gap, TEAL),
        (810, 390, surviving_p, GREEN),
    ]
    for x, y, block, accent in cards:
        draw_metric_card(
            axis,
            x=x,
            y=y,
            width=720,
            height=180,
            label=block["label"],
            value=format_metric(block, evidence),
            accent=accent,
            label_y_offset=135,
            value_y_offset=45,
            label_wrap=28,
            value_size=34,
        )

    rounded_box(axis, 70, 105, 1460, 245, facecolor=PALE, edgecolor=PALE)
    axis.text(
        110,
        315,
        conclusion["heading"],
        color=NAVY,
        fontsize=20,
        fontweight="bold",
        va="top",
        ha="left",
    )
    axis.text(
        110,
        250,
        wrap(conclusion["body"][0], 46),
        color=INK,
        fontsize=14,
        va="top",
        ha="left",
        linespacing=1.35,
    )
    axis.text(
        110,
        145,
        wrap(conclusion["body"][1], 48),
        color=MUTED,
        fontsize=13,
        va="top",
        ha="left",
        linespacing=1.35,
    )
    draw_footer(axis, plan, panel)
    save_panel(figure, panel["name"])


def save_panel(figure: Any, name: str) -> None:
    output_path = os.path.join(out_dir, f"{name}.png")
    figure.savefig(
        output_path,
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
    )
    plt.close(figure)


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    load_text(ARTICLE_PATH)
    verify_results_hash(plan)

    render_concept(plan, results)
    render_method(plan, results)
    render_results(plan, results)


if __name__ == "__main__":
    main()
