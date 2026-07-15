#!/usr/bin/env python3
"""Render the K1379 general-reader lazypack as three data-bound PNG panels."""

from __future__ import annotations

import hashlib
import json
import os
import re
import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


RESULT_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1379/k1379_results.json"
)
README_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k1379/README.md"
)
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e81bb0a/runs/lazypack-mile_6e81bb0a-r2/plan.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e81bb0a/runs/lazypack-mile_6e81bb0a-r2/panels/"
    "mile_6e81bb0a_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_6e81bb0a/runs/lazypack-mile_6e81bb0a-r2/panels"
)

WIDTH = 1600
HEIGHT = 1000
DPI = 150

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#172033"
MUTED = "#5E6878"
FAINT = "#8A94A4"
PAPER = "#FFFFFF"
SURFACE = "#F4F6F8"
LINE = "#DCE2E8"
NAVY = "#172A46"
BLUE = "#2D66B3"
BLUE_SOFT = "#EAF1FA"
GREEN = "#197252"
GREEN_SOFT = "#E5F3ED"
RED = "#B73535"
RED_SOFT = "#F9EAEA"
AMBER = "#A46412"
AMBER_SOFT = "#FAF1E2"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(data: Any, path: str) -> Any:
    """Resolve either a dotted path or an RFC 6901 JSON Pointer; fail closed."""
    if not isinstance(path, str) or not path:
        raise KeyError(f"Invalid evidence path: {path!r}")

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
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {path}") from exc
        else:
            raise KeyError(f"Missing evidence field: {path}")
    return current


def require_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number at {path}, got {type(value).__name__}")
    return float(value)


def format_bound_value(result: dict[str, Any], value_spec: dict[str, Any]) -> str:
    if value_spec.get("source") != "result":
        raise ValueError(f"Unsupported evidence source: {value_spec.get('source')!r}")

    path = value_spec["path"]
    raw = resolve_path(result, path)
    fmt = value_spec["format"]
    kind = fmt["kind"]
    suffix = fmt.get("suffix", "")

    if kind == "date":
        if not isinstance(raw, str):
            raise TypeError(f"Expected an ISO date string at {path}")
        rendered = date.fromisoformat(raw).isoformat()
    elif kind == "integer":
        numeric = require_number(raw, path)
        if not numeric.is_integer():
            raise ValueError(f"Expected an integer-valued number at {path}")
        rendered = f"{int(numeric):,}" if fmt.get("thousands") else str(int(numeric))
    elif kind == "number":
        numeric = require_number(raw, path)
        digits = fmt["digits"]
        if not isinstance(digits, int) or digits < 0:
            raise ValueError(f"Invalid digits setting for {path}: {digits!r}")
        sign = "+" if fmt.get("show_plus") else ""
        comma = "," if fmt.get("thousands") else ""
        rendered = format(numeric, f"{sign}{comma}.{digits}f")
    else:
        raise ValueError(f"Unsupported format kind {kind!r} for {path}")

    return rendered + suffix


def bind_text_body(result: dict[str, Any], body: list[Any]) -> list[str]:
    rendered: list[str] = []
    for item in body:
        if isinstance(item, str):
            rendered.append(item)
            continue
        if not isinstance(item, dict):
            raise TypeError(f"Unsupported text body item: {item!r}")
        template = item["template"]
        bindings = {
            key: format_bound_value(result, spec)
            for key, spec in item["bindings"].items()
        }
        rendered.append(template.format(**bindings))
    return rendered


def find_panel(plan: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [panel for panel in plan["panels"] if panel.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one plan panel named {name!r}")
    return matches[0]


def require_panel_contract(panel: dict[str, Any], *, style: str, block_count: int) -> None:
    if panel.get("style") != style:
        raise ValueError(f"Unexpected style for {panel.get('name')}: {panel.get('style')!r}")
    if panel.get("sources") != ["result"]:
        raise ValueError(f"Unexpected evidence sources for {panel.get('name')}")
    if len(panel["blocks"]) != block_count:
        raise ValueError(f"Unexpected block count for {panel.get('name')}")


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def card(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = SURFACE,
    edge: str = LINE,
    radius: float = 0.018,
    linewidth: float = 1.1,
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=face,
        edgecolor=edge,
        linewidth=linewidth,
    )
    ax.add_patch(patch)


def put(
    ax: plt.Axes,
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    color: str = INK,
    weight: int = 400,
    ha: str = "left",
    va: str = "top",
    wrap_chars: int | None = None,
    linespacing: float = 1.22,
) -> None:
    if wrap_chars is not None:
        text = textwrap.fill(
            text,
            width=wrap_chars,
            break_long_words=False,
            break_on_hyphens=False,
        )
    ax.text(
        x,
        y,
        text,
        transform=ax.transAxes,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=linespacing,
    )


def title_block(ax: plt.Axes, title: str, subtitle: str) -> None:
    put(ax, 0.06, 0.91, title, size=29, weight=500, va="center")
    put(ax, 0.06, 0.835, subtitle, size=14, color=MUTED, va="center")
    ax.plot([0.06, 0.94], [0.79, 0.79], color=LINE, linewidth=1.2, transform=ax.transAxes)


def source_footer(ax: plt.Axes, source_label: str) -> None:
    ax.plot([0.06, 0.94], [0.075, 0.075], color=LINE, linewidth=1.0, transform=ax.transAxes)
    put(ax, 0.06, 0.037, source_label, size=11, color=FAINT, va="center")


def save_panel(fig: plt.Figure, panel: dict[str, Any]) -> None:
    destination = os.path.join(out_dir, f"{panel['name']}.png")
    fig.savefig(
        destination,
        dpi=DPI,
        facecolor=PAPER,
        metadata={"Title": panel["title"], "Description": panel["alt"]},
    )
    plt.close(fig)


def render_stable_ranking(
    result: dict[str, Any], panel: dict[str, Any], source_label: str
) -> None:
    require_panel_contract(panel, style="bento-grid", block_count=4)
    blocks = panel["blocks"]
    if any(block.get("kind") != "metric" for block in blocks):
        raise ValueError("Panel 1 requires four metric blocks")

    fig, ax = new_canvas()
    title_block(ax, panel["title"], "平均 QLIKE 罰分越低越好；先比較沒有非正預測的做法")

    positions = [
        (0.06, 0.48, 0.425, 0.26),
        (0.515, 0.48, 0.425, 0.26),
        (0.06, 0.16, 0.425, 0.25),
        (0.515, 0.16, 0.425, 0.25),
    ]
    faces = [GREEN_SOFT, SURFACE, SURFACE, BLUE_SOFT]
    edges = [GREEN, LINE, LINE, BLUE]
    value_colors = [GREEN, INK, INK, BLUE]

    for index, (block, (x, y, w, h)) in enumerate(zip(blocks, positions, strict=True)):
        value = format_bound_value(result, block["value"])
        card(ax, x, y, w, h, face=faces[index], edge=edges[index])
        ax.add_patch(
            Rectangle(
                (x + 0.02, y + h - 0.025),
                0.055,
                0.006,
                transform=ax.transAxes,
                facecolor=value_colors[index],
                edgecolor="none",
            )
        )
        put(ax, x + 0.025, y + h - 0.055, block["label"], size=14, weight=500)
        put(
            ax,
            x + 0.025,
            y + h * 0.48,
            value,
            size=36 if index != 3 else 34,
            color=value_colors[index],
            weight=500,
            va="center",
        )
        note = block.get("note")
        if note:
            put(ax, x + 0.025, y + 0.035, note, size=11.5, color=MUTED, va="bottom")

    source_footer(ax, source_label)
    save_panel(fig, panel)


def render_unstable_extra_signal(
    result: dict[str, Any], panel: dict[str, Any], source_label: str
) -> None:
    require_panel_contract(panel, style="editorial", block_count=4)
    count_block, dates_block, full_block, diagnostic_block = panel["blocks"]
    if [block.get("kind") for block in panel["blocks"]] != ["metric", "text", "metric", "metric"]:
        raise ValueError("Panel 2 block kinds do not match the plan contract")

    count_value = format_bound_value(result, count_block["value"])
    dates = bind_text_body(result, dates_block["body"])
    if len(dates) != 1:
        raise ValueError("Panel 2 requires one bound date sentence")
    full_value = format_bound_value(result, full_block["value"])
    diagnostic_value = format_bound_value(result, diagnostic_block["value"])

    fig, ax = new_canvas()
    title_block(ax, panel["title"], "資訊變多之前，模型必須先守住波動預測應為正值的基本限制")

    card(ax, 0.06, 0.17, 0.415, 0.56, face=RED_SOFT, edge=RED, linewidth=1.4)
    ax.add_patch(
        Rectangle(
            (0.06, 0.17),
            0.012,
            0.56,
            transform=ax.transAxes,
            facecolor=RED,
            edgecolor="none",
        )
    )
    put(ax, 0.095, 0.665, count_block["label"], size=15, color=RED, weight=500)
    put(ax, 0.095, 0.575, count_value, size=47, color=RED, weight=500, va="center")
    ax.plot([0.095, 0.44], [0.465, 0.465], color="#E5BABA", linewidth=1.2, transform=ax.transAxes)
    put(ax, 0.095, 0.415, dates_block["heading"], size=14, weight=500)
    put(ax, 0.095, 0.35, dates[0], size=14, color=INK, wrap_chars=27, linespacing=1.35)

    card(ax, 0.515, 0.46, 0.425, 0.27, face=AMBER_SOFT, edge="#E7C996")
    put(ax, 0.545, 0.665, full_block["label"], size=14, color=AMBER, weight=500)
    put(ax, 0.545, 0.585, full_value, size=30, color=INK, weight=500, va="center")
    put(ax, 0.545, 0.505, full_block["note"], size=11.5, color=MUTED, va="center")

    card(ax, 0.515, 0.17, 0.425, 0.23, face=SURFACE, edge=LINE)
    put(ax, 0.545, 0.345, diagnostic_block["label"], size=14, weight=500)
    put(ax, 0.545, 0.272, diagnostic_value, size=33, color=BLUE, weight=500, va="center")
    put(ax, 0.545, 0.205, diagnostic_block["note"], size=11.5, color=MUTED, va="center")

    source_footer(ax, source_label)
    save_panel(fig, panel)


def draw_bullet_group(
    ax: plt.Axes,
    block: dict[str, Any],
    *,
    x: float,
    y: float,
    marker_color: str,
) -> None:
    if block.get("kind") != "text":
        raise ValueError("Panel 3 conclusion blocks must be text blocks")
    put(ax, x, y, block["heading"], size=17, weight=500)
    cursor_y = y - 0.072
    for sentence in block["body"]:
        if not isinstance(sentence, str):
            raise TypeError("Panel 3 bullet body must contain strings")
        wrapped = textwrap.wrap(
            sentence,
            width=18,
            # Chinese sentences contain no spaces, so textwrap otherwise treats
            # the entire sentence as one word and lets it escape the card.
            break_long_words=True,
            break_on_hyphens=False,
        )
        if not wrapped:
            raise ValueError("Panel 3 contains an empty bullet")
        ax.scatter([x + 0.005], [cursor_y - 0.012], s=34, color=marker_color, transform=ax.transAxes)
        put(ax, x + 0.025, cursor_y, "\n".join(wrapped), size=13.5, linespacing=1.35)
        cursor_y -= 0.052 * len(wrapped) + 0.028


def render_honest_boundary(
    result: dict[str, Any], panel: dict[str, Any], source_label: str
) -> None:
    require_panel_contract(panel, style="professional", block_count=5)
    metric_blocks = panel["blocks"][:3]
    if any(block.get("kind") != "metric" for block in metric_blocks):
        raise ValueError("Panel 3 requires three leading metric blocks")

    values = [format_bound_value(result, block["value"]) for block in metric_blocks]

    fig, ax = new_canvas()
    ax.add_patch(
        Rectangle((0, 0.78), 1, 0.22, transform=ax.transAxes, facecolor=NAVY, edgecolor="none")
    )
    put(ax, 0.06, 0.905, panel["title"], size=29, color=PAPER, weight=500, va="center")
    put(
        ax,
        0.06,
        0.835,
        "負值表示第一個方法的平均罰分較低；結論只限於這套固定協議",
        size=13.5,
        color="#CFDAE8",
        va="center",
    )

    xs = [0.06, 0.365, 0.67]
    for index, (block, value, x) in enumerate(zip(metric_blocks, values, xs, strict=True)):
        card(ax, x, 0.555, 0.27, 0.17, face=PAPER, edge=LINE, linewidth=1.2)
        put(ax, x + 0.02, 0.69, block["label"], size=12.5, color=MUTED, weight=500, wrap_chars=15)
        put(
            ax,
            x + 0.02,
            0.595,
            value,
            size=30 if index == 0 else 29,
            color=NAVY if index == 0 else BLUE,
            weight=500,
            va="center",
        )

    card(ax, 0.06, 0.13, 0.425, 0.35, face=GREEN_SOFT, edge="#B8DCCF")
    card(ax, 0.515, 0.13, 0.425, 0.35, face=AMBER_SOFT, edge="#E7C996")
    draw_bullet_group(ax, panel["blocks"][3], x=0.09, y=0.43, marker_color=GREEN)
    draw_bullet_group(ax, panel["blocks"][4], x=0.545, y=0.43, marker_color=AMBER)

    source_footer(ax, source_label)
    save_panel(fig, panel)


def main() -> None:
    result = load_json(RESULT_PATH)
    plan = load_json(PLAN_PATH)
    readme = load_text(README_PATH)
    load_text(ARTICLE_PATH)

    match = re.fullmatch(r"(k\d+)_results\.json", RESULT_PATH.name, flags=re.IGNORECASE)
    if match is None:
        raise ValueError(f"Cannot infer experiment id from {RESULT_PATH.name}")
    experiment_id = match.group(1).upper()
    if experiment_id not in readme:
        raise ValueError(f"README does not identify {experiment_id}")

    evidence_spec = plan["evidence"]["result"]
    if evidence_spec["path"] != "experiments/k1379/k1379_results.json":
        raise ValueError("Plan points to an unexpected result artifact")
    expected_sha256 = evidence_spec["sha256"]
    actual_sha256 = sha256_file(RESULT_PATH)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"Result evidence hash mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    os.makedirs(out_dir, exist_ok=True)
    source_label = f"資料來源：experiment {experiment_id}"

    render_stable_ranking(result, find_panel(plan, "1_stable_ranking"), source_label)
    render_unstable_extra_signal(
        result, find_panel(plan, "2_unstable_extra_signal"), source_label
    )
    render_honest_boundary(result, find_panel(plan, "3_honest_boundary"), source_label)


if __name__ == "__main__":
    main()
