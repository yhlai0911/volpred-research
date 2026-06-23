#!/usr/bin/env python3
"""Generate JSON-bound 懶人包 infographic PNGs with local free tooling.

This is the programmatic renderer counterpart to
``scripts/gen_lazypack_infographic.py``.  The NotebookLM path can produce good
images for free, but it may reject evidence JSON uploads and then force the
workflow back to article prose.  This renderer binds every displayed number to a
field in the evidence JSON, draws the posters locally with Pillow, and writes
deterministic PNGs.  It never calls a paid image API.

CLI shape intentionally mirrors the NotebookLM generator where useful:

    uv run python scripts/gen_lazypack_codex.py \
        --evidence /tmp/spacex_trending/evidence_numbers.json \
        --article-markdown /tmp/trending_spacex_vol.md \
        --plan /tmp/spacex_lazypack_plan.json \
        --out-dir /tmp/spacex_lazypack_codex

Plan format accepts either the existing NotebookLM-style list:

    [
      {"name": "1_framework", "style": "professional", "prompt": "...",
       "template": "concept_framework"},
      {"name": "2_sigma", "style": "bento-grid", "prompt": "...",
       "template": "sigma_compare"}
    ]

or {"panels": [...]}.

Default SpaceX panel mapping used by the built-in templates:

concept_framework
  - framing2_postipo_rv.spacex_realized.monday_single_day_ret_pct
    -> hero SPCX one-day return
  - framing2_postipo_rv.spacex_realized.annualized_rv_pct
    -> SpaceX annualized realized volatility card
  - framing2_postipo_rv.spacex_realized.first_day_close_2026_06_12
    -> first-day close context
  - framing2_postipo_rv.spacex_realized.monday_close_2026_06_22
    -> Monday close context
  - single_day_returns.^GSPC.ret_pct and single_day_returns.TSM.ret_pct
    -> market-structure comparison cards

sigma_compare
  - framing1_sigma_context.single_day_drop_pct
    -> benchmark drop in the panel subtitle
  - framing1_sigma_context.per_asset.{GOOGL,AMZN,TSM,AVGO}.sigma_of_neg16pct
    -> sigma bar labels
  - framing1_sigma_context.per_asset.{GOOGL,AMZN,TSM,AVGO}.daily_sd_pct
    -> daily standard deviation mini table

rate_takeaway
  - vol_index_levels.^VIX.current and vol_index_levels.^VIX.change_1m
    -> equity-volatility card
  - vol_index_levels.^MOVE.current and vol_index_levels.^MOVE.change_1m
    -> bond-volatility card
  - single_day_returns.{GOOGL,AMZN,AVGO,^GSPC,TSM}.ret_pct
    -> breadth/market-structure strip
  - framing2_postipo_rv.spacex_realized.annualized_rv_pct
    -> SpaceX volatility-regime reminder

If a number is not present in the evidence JSON, do not render it.  For example,
the current SpaceX evidence package describes "SpaceX 100x vs Apple 10x P/S" in
article prose, but does not provide JSON fields for those values, so the default
templates intentionally omit them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
WIDTH = 1600
HEIGHT = 2200
RANDOM_SEED = 42  # kept explicit; rendering itself is deterministic.

VALID_STYLES = {
    "auto",
    "professional",
    "bento-grid",
    "editorial",
    "scientific",
    "sketch-note",
    "instructional",
    "bricks",
    "clay",
    "anime",
    "kawaii",
}
PRO_STYLES = {"professional", "bento-grid", "editorial", "scientific", "auto"}
CARTOON_STYLES = {"sketch-note", "instructional", "bricks", "clay", "anime", "kawaii"}

INK = "#17202A"
MUTED = "#5A6472"
FAINT = "#8792A0"
PAPER = "#F7F4EF"
CARD = "#FFFFFF"
GRID = "#D8DEE7"
RED = "#C83E3A"
RED_SOFT = "#F4D9D7"
TEAL = "#177C7D"
TEAL_SOFT = "#D8EFEE"
BLUE = "#235A97"
BLUE_SOFT = "#DFEAF7"
AMBER = "#A96A12"
AMBER_SOFT = "#F4E6CF"
GREEN = "#257A4C"
GREEN_SOFT = "#DCEEE3"


FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
    "/Library/Fonts/Noto Sans CJK TC Regular.otf",
]
FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/NotoSansCJKtc-Bold.otf",
    "/Library/Fonts/Noto Sans CJK TC Bold.otf",
]


@dataclass(frozen=True)
class FieldSpec:
    id: str
    path: str
    fmt: str
    label: str


@dataclass
class BoundField:
    id: str
    path: str
    value: Any
    rendered: str
    label: str


@dataclass
class FontBook:
    regular_path: Path
    bold_path: Path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


def _first_existing(paths: list[str]) -> Path | None:
    for raw in paths:
        path = Path(raw).expanduser()
        if path.exists():
            return path
    return None


def load_fonts() -> FontBook:
    regular = _first_existing(FONT_CANDIDATES_REGULAR)
    bold = _first_existing(FONT_CANDIDATES_BOLD)
    if not regular or not bold:
        raise RuntimeError(
            "No local CJK font found. Install a Traditional Chinese capable font "
            "(for example Noto Sans CJK TC) and rerun."
        )
    probe = ImageFont.truetype(str(regular), size=40)
    bbox = probe.getbbox("波動率測試")
    if not bbox or bbox[2] <= bbox[0]:
        raise RuntimeError(f"Selected font does not render zh_Hant text: {regular}")
    return FontBook(regular_path=regular, bold_path=bold)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(path)
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(path) from exc
        else:
            raise KeyError(path)
    return cur


def as_float(value: Any, path: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"Expected numeric value at {path}, got {type(value).__name__}")


def fmt_value(value: Any, fmt: str, path: str) -> str:
    if fmt == "str":
        return str(value)
    num = as_float(value, path)
    if fmt == "pct_0":
        return f"{num:.0f}%"
    if fmt == "pct_1":
        return f"{num:.1f}%"
    if fmt == "pct_2":
        return f"{num:.2f}%"
    if fmt == "signed_pct_1":
        return f"{num:+.1f}%"
    if fmt == "signed_pct_2":
        return f"{num:+.2f}%"
    if fmt == "signed_number_2":
        return f"{num:+.2f}"
    if fmt == "sigma_1":
        return f"{num:.1f}σ"
    if fmt == "number_1":
        return f"{num:.1f}"
    if fmt == "number_2":
        return f"{num:.2f}"
    if fmt == "price_2":
        return f"{num:.2f}"
    if fmt == "int":
        return f"{num:.0f}"
    raise ValueError(f"Unknown format '{fmt}' for {path}")


def default_field_specs(template: str) -> list[FieldSpec]:
    if template == "concept_framework":
        return [
            FieldSpec("spcx_ret", "framing2_postipo_rv.spacex_realized.monday_single_day_ret_pct", "signed_pct_2", "SPCX 週一單日報酬"),
            FieldSpec("spcx_rv", "framing2_postipo_rv.spacex_realized.annualized_rv_pct", "pct_1", "SPCX 年化實現波動"),
            FieldSpec("first_close", "framing2_postipo_rv.spacex_realized.first_day_close_2026_06_12", "price_2", "首日收盤"),
            FieldSpec("monday_close", "framing2_postipo_rv.spacex_realized.monday_close_2026_06_22", "price_2", "週一收盤"),
            FieldSpec("gspc_ret", "single_day_returns.^GSPC.ret_pct", "signed_pct_2", "S&P 500 單日報酬"),
            FieldSpec("tsm_ret", "single_day_returns.TSM.ret_pct", "signed_pct_2", "台積電 ADR 單日報酬"),
        ]
    if template == "sigma_compare":
        specs = [
            FieldSpec("drop_anchor", "framing1_sigma_context.single_day_drop_pct", "signed_pct_1", "基準跌幅"),
        ]
        for ticker in ("GOOGL", "AMZN", "TSM", "AVGO"):
            specs.append(
                FieldSpec(
                    f"{ticker}_sigma",
                    f"framing1_sigma_context.per_asset.{ticker}.sigma_of_neg16pct",
                    "sigma_1",
                    f"{ticker} sigma 倍數",
                )
            )
            specs.append(
                FieldSpec(
                    f"{ticker}_sd",
                    f"framing1_sigma_context.per_asset.{ticker}.daily_sd_pct",
                    "pct_2",
                    f"{ticker} 日標準差",
                )
            )
        return specs
    if template == "rate_takeaway":
        return [
            FieldSpec("vix", "vol_index_levels.^VIX.current", "number_2", "VIX"),
            FieldSpec("vix_chg", "vol_index_levels.^VIX.change_1m", "signed_number_2", "VIX 近月變化"),
            FieldSpec("move", "vol_index_levels.^MOVE.current", "number_2", "MOVE"),
            FieldSpec("move_chg", "vol_index_levels.^MOVE.change_1m", "signed_number_2", "MOVE 近月變化"),
            FieldSpec("spcx_rv", "framing2_postipo_rv.spacex_realized.annualized_rv_pct", "pct_1", "SPCX 年化實現波動"),
            FieldSpec("googl_ret", "single_day_returns.GOOGL.ret_pct", "signed_pct_2", "GOOGL 單日報酬"),
            FieldSpec("amzn_ret", "single_day_returns.AMZN.ret_pct", "signed_pct_2", "AMZN 單日報酬"),
            FieldSpec("avgo_ret", "single_day_returns.AVGO.ret_pct", "signed_pct_2", "AVGO 單日報酬"),
            FieldSpec("gspc_ret", "single_day_returns.^GSPC.ret_pct", "signed_pct_2", "S&P 500 單日報酬"),
            FieldSpec("tsm_ret", "single_day_returns.TSM.ret_pct", "signed_pct_2", "TSM 單日報酬"),
        ]
    raise ValueError(f"Unknown template: {template}")


def infer_template(panel: dict[str, Any], index: int) -> str:
    explicit = panel.get("template") or panel.get("kind") or panel.get("panel_type")
    if explicit:
        return str(explicit)
    name = str(panel.get("name", "")).lower()
    prompt = str(panel.get("prompt", "")).lower()
    if "sigma" in name or "sigma" in prompt or "標準差" in prompt:
        return "sigma_compare"
    if "rate" in name or "takeaway" in name or "vix" in prompt or "move" in prompt or "升息" in prompt:
        return "rate_takeaway"
    if index == 1:
        return "concept_framework"
    if index == 2:
        return "sigma_compare"
    return "rate_takeaway"


def extra_field_specs(panel: dict[str, Any]) -> list[FieldSpec]:
    raw = panel.get("bindings") or panel.get("fields") or []
    specs: list[FieldSpec] = []
    if isinstance(raw, dict):
        iterable = [
            {"id": key, **value} if isinstance(value, dict) else {"id": key, "path": value}
            for key, value in raw.items()
        ]
    else:
        iterable = raw
    for item in iterable:
        if not isinstance(item, dict):
            raise ValueError("Panel bindings/fields must be objects")
        specs.append(
            FieldSpec(
                id=str(item["id"]),
                path=str(item["path"]),
                fmt=str(item.get("format", item.get("fmt", "number_2"))),
                label=str(item.get("label", item["id"])),
            )
        )
    return specs


def bind_fields(evidence: dict[str, Any], specs: list[FieldSpec]) -> dict[str, BoundField]:
    bound: dict[str, BoundField] = {}
    for spec in specs:
        raw = resolve_path(evidence, spec.path)
        bound[spec.id] = BoundField(
            id=spec.id,
            path=spec.path,
            value=raw,
            rendered=fmt_value(raw, spec.fmt, spec.path),
            label=spec.label,
        )
    return bound


def load_plan(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return [
            {"name": "1_framework", "style": "professional", "template": "concept_framework", "prompt": "只講概念框架。"},
            {"name": "2_sigma", "style": "bento-grid", "template": "sigma_compare", "prompt": "只講 sigma 數據對比。"},
            {"name": "3_takeaway", "style": "editorial", "template": "rate_takeaway", "prompt": "只講升息結論 takeaway。"},
        ]
    raw = load_json(path)
    panels = raw.get("panels") if isinstance(raw, dict) else raw
    if not isinstance(panels, list) or not panels:
        raise ValueError("--plan must be a non-empty JSON list or an object with panels")
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError("Each panel in --plan must be an object")
    return panels


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            trial = current + ch
            if text_size(draw, trial, font)[0] <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 10,
) -> int:
    x, y = xy
    lines = wrap_text(draw, text, font, max_width)
    line_h = font.size + line_gap
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


def draw_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    x1, y1, x2, y2 = box
    w, h = text_size(draw, text, font)
    draw.text((x1 + (x2 - x1 - w) / 2, y1 + (y2 - y1 - h) / 2), text, font=font, fill=fill)


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int = 28,
    fill: str = CARD,
    outline: str | None = None,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def add_header(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    title: str,
    subtitle: str,
    accent: str,
) -> None:
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=PAPER)
    draw.rounded_rectangle((84, 84, 244, 104), radius=10, fill=accent)
    draw.text((84, 132), "VolPred 懶人包", font=fonts.bold(38), fill=accent)
    title_font = fonts.bold(86)
    title_lines = wrap_text(draw, title, title_font, 1360)
    for size in range(82, 66, -4):
        if len(title_lines) <= 2 and all(len(line.strip()) > 1 for line in title_lines):
            break
        title_font = fonts.bold(size)
        title_lines = wrap_text(draw, title, title_font, 1360)
    y = 210
    for line in title_lines:
        draw.text((84, y), line, font=title_font, fill=INK)
        y += title_font.size + 22
    draw_wrapped(draw, (88, y + 28), subtitle, fonts.regular(38), MUTED, 1280, line_gap=12)


def add_footer(draw: ImageDraw.ImageDraw, fonts: FontBook, evidence_path: Path, fields: dict[str, BoundField]) -> None:
    source = f"資料來源：{evidence_path.name} / yfinance daily OHLC；圖上數字皆由 JSON 欄位渲染"
    draw.line((84, HEIGHT - 132, WIDTH - 84, HEIGHT - 132), fill=GRID, width=2)
    draw_wrapped(draw, (84, HEIGHT - 102), source, fonts.regular(26), FAINT, 1040, line_gap=8)


def draw_metric_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    accent: str,
    note: str = "",
    soft: str = CARD,
) -> None:
    rounded(draw, box, radius=26, fill=soft, outline="#E1E6EE", width=2)
    x1, y1, x2, y2 = box
    draw.text((x1 + 34, y1 + 30), label, font=fonts.bold(32), fill=accent)
    draw.text((x1 + 34, y1 + 88), value, font=fonts.bold(74), fill=INK)
    if note:
        draw_wrapped(draw, (x1 + 34, y1 + 188), note, fonts.regular(26), MUTED, x2 - x1 - 68, line_gap=8)


def draw_pill(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    accent: str,
) -> None:
    rounded(draw, box, radius=24, fill=CARD, outline="#E5E9EF", width=2)
    x1, y1, x2, y2 = box
    draw.text((x1 + 28, y1 + 26), label, font=fonts.bold(28), fill=accent)
    draw.text((x1 + 28, y1 + 78), value, font=fonts.bold(52), fill=INK)


def render_concept_framework(
    out_path: Path,
    fonts: FontBook,
    fields: dict[str, BoundField],
    evidence_path: Path,
) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    add_header(
        draw,
        fonts,
        "先別問跌多少，先問拿誰的尺在量",
        "同一根黑K，放進不同波動率體制，會得到完全不同的風險解讀。",
        RED,
    )

    rounded(draw, (84, 560, 1516, 1010), radius=34, fill=CARD, outline="#E2E7EF", width=2)
    draw.text((132, 618), "SPCX 週一單日報酬", font=fonts.bold(42), fill=RED)
    draw.text((132, 690), fields["spcx_ret"].rendered, font=fonts.bold(150), fill=INK)
    draw_wrapped(
        draw,
        (132, 875),
        f"首日收盤 {fields['first_close'].rendered}；週一收盤 {fields['monday_close'].rendered}。百分比很大，但還要放回自己的波動率尺度。",
        fonts.regular(34),
        MUTED,
        850,
        line_gap=10,
    )
    draw_metric_card(
        draw,
        fonts,
        (1050, 642, 1438, 930),
        "SPCX 年化實現波動",
        fields["spcx_rv"].rendered,
        TEAL,
        "新股短樣本，代表量級參考，不當成長期穩態估計。",
        TEAL_SOFT,
    )

    y = 1120
    stage_boxes = [
        ((84, y, 506, y + 310), "百分比跌幅", "先看價格移動本身，但不要立刻把大跌幅等同崩盤。", RED, RED_SOFT),
        ((589, y, 1011, y + 310), "波動率尺", "把同一個跌幅除以各標的自己的日常波動，才知道尾端程度。", BLUE, BLUE_SOFT),
        ((1094, y, 1516, y + 310), "市場結構", "再看大盤與同族群標的，分辨是全市場壓力或局部重估。", TEAL, TEAL_SOFT),
    ]
    for box, label, text, accent, fill in stage_boxes:
        rounded(draw, box, radius=28, fill=fill, outline="#DDE5EE", width=2)
        x1, y1, x2, _ = box
        draw.rounded_rectangle((x1 + 32, y1 + 32, x1 + 96, y1 + 96), radius=16, fill=accent)
        draw.text((x1 + 126, y1 + 42), label, font=fonts.bold(34), fill=INK)
        draw_wrapped(draw, (x1 + 32, y1 + 126), text, fonts.regular(30), MUTED, x2 - x1 - 64, line_gap=10)

    draw_metric_card(
        draw,
        fonts,
        (84, 1532, 774, 1848),
        "大盤同步性",
        fields["gspc_ret"].rendered,
        BLUE,
        "美股大盤當天只是小幅回落，顯示不是整個市場同時崩壞。",
        BLUE_SOFT,
    )
    draw_metric_card(
        draw,
        fonts,
        (826, 1532, 1516, 1848),
        "同日防守對照",
        fields["tsm_ret"].rendered,
        GREEN,
        "TSM ADR 收紅，壓力集中在高估值科技，而非所有科技股。",
        GREEN_SOFT,
    )
    add_footer(draw, fonts, evidence_path, fields)
    img.save(out_path, "PNG", optimize=True)


def render_sigma_compare(
    out_path: Path,
    fonts: FontBook,
    fields: dict[str, BoundField],
    evidence_path: Path,
) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    add_header(
        draw,
        fonts,
        "同一根黑K，sigma 尺度差一整個量級",
        f"基準跌幅 {fields['drop_anchor'].rendered} 套回各股日報酬標準差，才看得出哪裡是尾端事件。",
        BLUE,
    )

    rounded(draw, (84, 560, 1516, 1460), radius=34, fill=CARD, outline="#E2E7EF", width=2)
    draw.text((132, 628), "sigma 倍數", font=fonts.bold(44), fill=BLUE)
    draw.text((132, 690), "同一跌幅對不同標的的尾端程度", font=fonts.regular(30), fill=MUTED)
    tickers = ["GOOGL", "AMZN", "TSM", "AVGO"]
    values = [as_float(fields[f"{t}_sigma"].value, fields[f"{t}_sigma"].path) for t in tickers]
    max_value = max(values)
    chart_x = 320
    chart_y = 815
    chart_w = 900
    bar_h = 96
    gap = 58
    for idx, ticker in enumerate(tickers):
        y = chart_y + idx * (bar_h + gap)
        val = values[idx]
        w = int(chart_w * val / max_value)
        draw.text((132, y + 24), ticker, font=fonts.bold(36), fill=INK)
        draw.rounded_rectangle((chart_x, y, chart_x + chart_w, y + bar_h), radius=24, fill="#EEF2F7")
        accent = RED if val >= 8 else (AMBER if val >= 6 else TEAL)
        draw.rounded_rectangle((chart_x, y, chart_x + w, y + bar_h), radius=24, fill=accent)
        draw.text((chart_x + w + 28, y + 18), fields[f"{ticker}_sigma"].rendered, font=fonts.bold(44), fill=INK)

    rounded(draw, (84, 1550, 1516, 1862), radius=30, fill=BLUE_SOFT, outline="#D3E0EF", width=2)
    draw.text((132, 1608), "日報酬標準差", font=fonts.bold(40), fill=BLUE)
    col_x = [132, 480, 828, 1176]
    for ticker, x in zip(tickers, col_x, strict=True):
        draw.text((x, 1688), ticker, font=fonts.bold(34), fill=INK)
        draw.text((x, 1750), fields[f"{ticker}_sd"].rendered, font=fonts.bold(54), fill=INK)
    draw_wrapped(
        draw,
        (132, 1888),
        "讀法：sigma 越高，代表同樣跌幅越不符合該標的平常的日常波動。",
        fonts.regular(32),
        MUTED,
        1300,
        line_gap=10,
    )
    add_footer(draw, fonts, evidence_path, fields)
    img.save(out_path, "PNG", optimize=True)


def render_rate_takeaway(
    out_path: Path,
    fonts: FontBook,
    fields: dict[str, BoundField],
    evidence_path: Path,
) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    add_header(
        draw,
        fonts,
        "升息結論：這不是全市場崩盤，而是高估值重估",
        "股市波動升、債市波動降；真正受壓的是靠更遠未來現金流撐估值的科技股。",
        TEAL,
    )

    draw_metric_card(
        draw,
        fonts,
        (84, 560, 774, 895),
        "VIX 現值",
        fields["vix"].rendered,
        TEAL,
        f"近月變化 {fields['vix_chg'].rendered} 點：股市端壓力上升。",
        TEAL_SOFT,
    )
    draw_metric_card(
        draw,
        fonts,
        (826, 560, 1516, 895),
        "MOVE 現值",
        fields["move"].rendered,
        AMBER,
        f"近月變化 {fields['move_chg'].rendered} 點：債市端沒有同步恐慌。",
        AMBER_SOFT,
    )

    rounded(draw, (84, 1018, 1516, 1388), radius=34, fill=CARD, outline="#E2E7EF", width=2)
    draw.text((132, 1084), "當天誰真的受傷？", font=fonts.bold(44), fill=INK)
    strip = [
        ("GOOGL", "googl_ret", RED),
        ("AMZN", "amzn_ret", RED),
        ("AVGO", "avgo_ret", RED),
        ("美股大盤", "gspc_ret", BLUE),
        ("TSM", "tsm_ret", GREEN),
    ]
    x = 132
    for label, key, accent in strip:
        draw_pill(draw, fonts, (x, 1166, x + 246, 1324), label, fields[key].rendered, accent)
        x += 268

    rounded(draw, (84, 1512, 1516, 1856), radius=34, fill=TEAL_SOFT, outline="#C9E5E4", width=2)
    draw.text((132, 1576), "Takeaway", font=fonts.bold(42), fill=TEAL)
    draw_wrapped(
        draw,
        (132, 1650),
        f"SpaceX 的年化實現波動是 {fields['spcx_rv'].rendered}。這種波動體制下，單日大跌不只是在講公司新聞，更是在講貼現率與估值久期重新定價。",
        fonts.regular(40),
        INK,
        1280,
        line_gap=14,
    )
    add_footer(draw, fonts, evidence_path, fields)
    img.save(out_path, "PNG", optimize=True)


RENDERERS = {
    "concept_framework": render_concept_framework,
    "sigma_compare": render_sigma_compare,
    "rate_takeaway": render_rate_takeaway,
}


def render_panel(
    panel: dict[str, Any],
    index: int,
    evidence: dict[str, Any],
    evidence_path: Path,
    out_dir: Path,
    fonts: FontBook,
) -> tuple[Path, dict[str, Any]]:
    style = str(panel.get("style", "professional"))
    if style in CARTOON_STYLES:
        raise ValueError(f"Cartoon/cute style is forbidden for finance lazypack: {style}")
    if style not in PRO_STYLES:
        raise ValueError(f"Unsupported style '{style}'. Use one of {sorted(PRO_STYLES)}")
    template = infer_template(panel, index)
    if template not in RENDERERS:
        raise ValueError(f"Unsupported template '{template}' in panel {panel.get('name')}")
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(panel.get("name") or f"panel_{index}")).strip("_")
    if not name:
        name = f"panel_{index}"

    specs = default_field_specs(template) + extra_field_specs(panel)
    fields = bind_fields(evidence, specs)
    out_path = out_dir / f"{name}.png"
    RENDERERS[template](out_path, fonts, fields, evidence_path)
    manifest = {
        "name": name,
        "template": template,
        "style": style,
        "output": str(out_path),
        "fields": [
            {
                "id": field.id,
                "label": field.label,
                "path": field.path,
                "value": field.value,
                "rendered": field.rendered,
            }
            for field in fields.values()
        ],
    }
    return out_path, manifest


def parse_article_title(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', text, flags=re.MULTILINE)
    return match.group(1) if match else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", required=True, help="evidence JSON; all displayed numbers are bound to this file")
    ap.add_argument("--article-markdown", help="optional article markdown; used only for non-numeric context/title")
    ap.add_argument("--plan", help="panel plan JSON; NotebookLM-style list plus optional template/bindings")
    ap.add_argument("--out-dir", required=True, help="directory for generated PNG panels")
    ap.add_argument("--title", help="optional non-numeric package title override")
    args = ap.parse_args()

    evidence_path = Path(args.evidence)
    article_path = Path(args.article_markdown) if args.article_markdown else None
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    evidence = load_json(evidence_path)
    if not isinstance(evidence, dict):
        print("ERROR: evidence JSON must be an object", file=sys.stderr)
        return 1
    try:
        panels = load_plan(Path(args.plan) if args.plan else None)
        fonts = load_fonts()
        _ = args.title or parse_article_title(article_path)
        manifests: list[dict[str, Any]] = []
        written: list[Path] = []
        for idx, panel in enumerate(panels, 1):
            out, manifest = render_panel(panel, idx, evidence, evidence_path, out_dir, fonts)
            written.append(out)
            manifests.append(manifest)
            print(f"OK: {out} ({out.stat().st_size} bytes)")
        manifest_path = out_dir / "lazypack_manifest.json"
        manifest_path.write_text(json.dumps(manifests, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"DONE: {len(written)}/{len(panels)} panels -> {out_dir}")
        print(f"MANIFEST: {manifest_path}")
        print(f"FONT_REGULAR: {fonts.regular_path}")
        print(f"FONT_BOLD: {fonts.bold_path}")
        return 0 if len(written) == len(panels) else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
