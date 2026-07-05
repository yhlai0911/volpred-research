#!/usr/bin/env python3
"""Render data-bound PNG lazypack panels for the Fed MOVE asymmetry article.

Every number displayed by this renderer is read from the adjacent results.json.
No image generation model or remote service is used.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

EXP_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXP_DIR / "results.json"

NAVY = "#152238"
INK = "#17202A"
MUTED = "#5C6675"
FAINT = "#8B95A4"
GRID = "#DCE2EA"
SOFT_BG = "#F5F7FA"
CARD = "#FFFFFF"
TEAL = "#0F766E"
TEAL_SOFT = "#D9F0ED"
RED = "#B83B3B"
RED_SOFT = "#F4DADA"
BLUE = "#2E5F9E"
BLUE_SOFT = "#E1EBF7"
AMBER = "#A46510"
AMBER_SOFT = "#F2E4CF"
GREEN = "#287A4B"
GREEN_SOFT = "#DCEFE4"

FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]
FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]


class FontBook:
    def __init__(self, regular_path: Path, bold_path: Path) -> None:
        self.regular_path = regular_path
        self.bold_path = bold_path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


def first_existing(paths: Iterable[str]) -> Path | None:
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    return None


def load_fonts() -> FontBook:
    regular = first_existing(FONT_CANDIDATES_REGULAR)
    bold = first_existing(FONT_CANDIDATES_BOLD)
    if regular is None or bold is None:
        raise RuntimeError("No Traditional Chinese capable font found.")

    probe = ImageFont.truetype(str(regular), size=48)
    bbox = probe.getbbox("美債波動率殖利率")
    if bbox is None or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise RuntimeError(f"Selected CJK font cannot render zh-Hant text: {regular}")
    return FontBook(regular_path=regular, bold_path=bold)


def load_results() -> dict:
    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh, parse_float=Decimal)


def get(data: dict, path: str):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            raise KeyError(path)
    return cur


def text_value(value) -> str:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def signed_value(value) -> str:
    text = text_value(value)
    if text.startswith("-"):
        return text
    return f"+{text}"


def pct(data: dict, path: str, signed: bool = True) -> str:
    value = get(data, path)
    return f"{signed_value(value) if signed else text_value(value)}%"


def pp(data: dict, path: str, signed: bool = True) -> str:
    value = get(data, path)
    return f"{signed_value(value) if signed else text_value(value)} pp"


def n(data: dict, path: str) -> str:
    return text_value(get(data, path))


def as_float(data: dict, path: str) -> float:
    return float(get(data, path))


def text_size(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox(xy, text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill: str = INK,
    anchor: str | None = None,
) -> None:
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def draw_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font,
    fill: str = INK,
) -> None:
    x1, y1, x2, y2 = box
    tw, th = text_size(draw, (0, 0), text, font)
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2), text, font=font, fill=fill)


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill: str,
    max_width: int,
    line_gap: int = 8,
) -> int:
    x, y = xy
    lines: list[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        width, _ = text_size(draw, (0, 0), candidate, font)
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)

    line_height = text_size(draw, (0, 0), "測", font)[1] + line_gap
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_height), line, font=font, fill=fill)
    return y + len(lines) * line_height


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None) -> None:
    draw.rounded_rectangle(box, radius=8, fill=fill, outline=outline, width=2 if outline else 1)


def draw_header(draw: ImageDraw.ImageDraw, fonts: FontBook, kicker: str, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, 178), fill=NAVY)
    draw_text(draw, (76, 42), kicker, fonts.bold(25), fill="#AFC5E6")
    draw_text(draw, (76, 80), title, fonts.bold(56), fill="#FFFFFF")
    draw_text(draw, (76, 140), subtitle, fonts.regular(26), fill="#D4DEEC")


def draw_footer(draw: ImageDraw.ImageDraw, fonts: FontBook, data: dict) -> None:
    source = f"資料來源：experiment {n(data, 'experiment_id')}；{n(data, 'data_source')}"
    draw.line((76, 930, WIDTH - 76, 930), fill=GRID, width=2)
    draw_text(draw, (76, 948), source, fonts.regular(21), fill=MUTED)
    draw_text(draw, (WIDTH - 76, 948), "同期描述性統計，非交易訊號或投資建議", fonts.regular(21), fill=MUTED, anchor="ra")


def draw_arrow_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], color: str, direction: str) -> None:
    cx, cy = center
    draw.ellipse((cx - 40, cy - 40, cx + 40, cy + 40), fill=color)
    if direction == "up":
        points = [(cx, cy - 26), (cx - 20, cy + 2), (cx - 7, cy + 2), (cx - 7, cy + 25), (cx + 7, cy + 25), (cx + 7, cy + 2), (cx + 20, cy + 2)]
    else:
        points = [(cx, cy + 26), (cx - 20, cy - 2), (cx - 7, cy - 2), (cx - 7, cy - 25), (cx + 7, cy - 25), (cx + 7, cy - 2), (cx + 20, cy - 2)]
    draw.polygon(points, fill="#FFFFFF")


def stat_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    note: str,
    accent: str,
    soft: str,
    icon: str | None = None,
) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, fill=CARD, outline=GRID)
    draw.rectangle((x1, y1, x1 + 12, y2), fill=accent)
    if icon:
        draw_arrow_icon(draw, (x1 + 72, y1 + 68), accent, icon)
        label_x = x1 + 132
    else:
        draw.rounded_rectangle((x1 + 38, y1 + 36, x1 + 98, y1 + 96), radius=8, fill=soft)
        draw.ellipse((x1 + 56, y1 + 54, x1 + 80, y1 + 78), fill=accent)
        label_x = x1 + 126
    draw_text(draw, (label_x, y1 + 36), label, fonts.bold(28), fill=INK)
    draw_text(draw, (label_x, y1 + 90), value, fonts.bold(70), fill=accent)
    draw_text(draw, (label_x, y1 + 172), note, fonts.regular(23), fill=MUTED)


def draw_horizontal_bar(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    x: int,
    y: int,
    width: int,
    label: str,
    value_label: str,
    value: float,
    max_value: float,
    color: str,
) -> None:
    draw_text(draw, (x, y), label, fonts.bold(27), fill=INK)
    draw_text(draw, (x + width, y), value_label, fonts.bold(31), fill=color, anchor="ra")
    ybar = y + 48
    draw.rounded_rectangle((x, ybar, x + width, ybar + 34), radius=8, fill="#EDF1F6")
    fill_w = int(width * min(value / max_value, 1.0))
    draw.rounded_rectangle((x, ybar, x + fill_w, ybar + 34), radius=8, fill=color)


def render_panel_1(data: dict, fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_header(draw, fonts, "01 全樣本方向差異", "利率往上時，MOVE 平均反應轉為正", "2010-01-05 至 2026-07-02 的同日條件化結果")

    rounded(draw, (76, 214, 1524, 292), fill=SOFT_BG, outline=None)
    strip = (
        f"樣本數 {n(data, 'n_obs')} 交易日  |  "
        f"上行日 {n(data, 'n_yield_up_days')}  |  "
        f"下行日 {n(data, 'n_yield_down_days')}"
    )
    draw_centered(draw, (76, 214, 1524, 292), strip, fonts.bold(28), fill=INK)

    stat_card(
        draw,
        fonts,
        (96, 340, 728, 618),
        "10 年期殖利率上行日",
        pct(data, "conditional_move_response.mean_move_ret_on_yield_up_pct"),
        "MOVE 當日平均變動",
        TEAL,
        TEAL_SOFT,
        icon="up",
    )
    stat_card(
        draw,
        fonts,
        (872, 340, 1504, 618),
        "10 年期殖利率下行日",
        pct(data, "conditional_move_response.mean_move_ret_on_yield_down_pct"),
        "MOVE 當日平均變動",
        RED,
        RED_SOFT,
        icon="down",
    )

    rounded(draw, (620, 660, 980, 848), fill=NAVY, outline=None)
    draw_text(draw, (800, 692), "上行 - 下行", fonts.bold(28), fill="#D4DEEC", anchor="ma")
    draw_text(draw, (800, 742), pp(data, "conditional_move_response.difference_pp"), fonts.bold(72), fill="#FFFFFF", anchor="ma")
    draw_text(draw, (800, 820), "條件平均差異", fonts.regular(23), fill="#D4DEEC", anchor="ma")

    rounded(draw, (96, 682, 568, 848), fill=CARD, outline=GRID)
    draw_text(draw, (132, 716), "Bootstrap 95% CI", fonts.bold(28), fill=BLUE)
    ci = f"[{n(data, 'conditional_move_response.bootstrap_95ci.0')}, {n(data, 'conditional_move_response.bootstrap_95ci.1')}] pp"
    draw_text(draw, (132, 772), ci, fonts.bold(46), fill=INK)
    draw_text(draw, (132, 826), "區間不含 0", fonts.regular(22), fill=MUTED)

    rounded(draw, (1032, 682, 1504, 848), fill=CARD, outline=GRID)
    draw_text(draw, (1068, 716), "Welch t-test", fonts.bold(28), fill=BLUE)
    test_line = f"t={n(data, 'conditional_move_response.welch_t')}  p={n(data, 'conditional_move_response.welch_p')}"
    draw_text(draw, (1068, 772), test_line, fonts.bold(42), fill=INK)
    draw_text(draw, (1068, 826), "方向條件差異顯著", fonts.regular(22), fill=MUTED)

    draw_footer(draw, fonts, data)
    path = OUT_DIR / "1_panel.png"
    img.save(path, dpi=DPI)
    return path


def render_panel_2(data: dict, fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_header(draw, fonts, "02 控制幅度後", "不只是利率上行日動得比較多", "同樣按每 bp 殖利率變動衡量，MOVE 對上行更敏感")

    rounded(draw, (76, 226, 562, 842), fill=CARD, outline=GRID)
    draw_text(draw, (118, 270), "核心比值", fonts.bold(31), fill=INK)
    draw_text(draw, (118, 335), f"{n(data, 'magnitude_controlled_slope.slope_ratio_up_over_down')} 倍", fonts.bold(92), fill=TEAL)
    draw_wrapped(
        draw,
        (118, 452),
        "控制殖利率變動幅度後，上行日的 MOVE 斜率仍高於下行日。",
        fonts.regular(30),
        MUTED,
        max_width=380,
        line_gap=10,
    )
    draw.rounded_rectangle((118, 676, 520, 764), radius=8, fill=TEAL_SOFT)
    draw_centered(draw, (118, 676, 520, 764), "上行斜率 / 下行斜率", fonts.bold(28), fill=TEAL)

    rounded(draw, (618, 226, 1504, 520), fill=SOFT_BG, outline=None)
    draw_text(draw, (662, 266), "MOVE 每 bp 反應", fonts.bold(34), fill=INK)
    max_slope = max(
        as_float(data, "magnitude_controlled_slope.beta_move_per_bp_yield_up"),
        as_float(data, "magnitude_controlled_slope.beta_move_per_bp_yield_down"),
    )
    draw_horizontal_bar(
        draw,
        fonts,
        662,
        334,
        750,
        "殖利率上行日",
        n(data, "magnitude_controlled_slope.beta_move_per_bp_yield_up"),
        as_float(data, "magnitude_controlled_slope.beta_move_per_bp_yield_up"),
        max_slope,
        TEAL,
    )
    draw_horizontal_bar(
        draw,
        fonts,
        662,
        430,
        750,
        "殖利率下行日",
        n(data, "magnitude_controlled_slope.beta_move_per_bp_yield_down"),
        as_float(data, "magnitude_controlled_slope.beta_move_per_bp_yield_down"),
        max_slope,
        RED,
    )

    rounded(draw, (618, 568, 1504, 842), fill=CARD, outline=GRID)
    draw_text(draw, (662, 608), "殖利率 realized semivariance", fonts.bold(34), fill=INK)
    draw_text(draw, (662, 660), "若只是利率上行日自己更劇烈，這裡的比值應該也很大。", fonts.regular(25), fill=MUTED)
    max_sv = max(
        as_float(data, "yield_realized_semivariance.up_semivar_bp2"),
        as_float(data, "yield_realized_semivariance.down_semivar_bp2"),
    )
    draw_horizontal_bar(
        draw,
        fonts,
        662,
        720,
        520,
        "上行半變異數",
        n(data, "yield_realized_semivariance.up_semivar_bp2"),
        as_float(data, "yield_realized_semivariance.up_semivar_bp2"),
        max_sv,
        BLUE,
    )
    draw_horizontal_bar(
        draw,
        fonts,
        662,
        810,
        520,
        "下行半變異數",
        n(data, "yield_realized_semivariance.down_semivar_bp2"),
        as_float(data, "yield_realized_semivariance.down_semivar_bp2"),
        max_sv,
        AMBER,
    )
    rounded(draw, (1240, 715, 1460, 815), fill=BLUE_SOFT, outline=None)
    draw_text(draw, (1350, 738), "比值", fonts.bold(26), fill=BLUE, anchor="ma")
    draw_text(draw, (1350, 777), n(data, "yield_realized_semivariance.up_over_down_ratio"), fonts.bold(45), fill=INK, anchor="ma")

    draw_footer(draw, fonts, data)
    path = OUT_DIR / "2_panel.png"
    img.save(path, dpi=DPI)
    return path


def draw_delta_line(draw: ImageDraw.ImageDraw, fonts: FontBook, data: dict) -> None:
    x0, x1 = 170, 1430
    y = 664
    draw.line((x0, y, x1, y), fill=GRID, width=5)
    draw.ellipse((x0 - 12, y - 12, x0 + 12, y + 12), fill=BLUE)
    draw.ellipse((x1 - 12, y - 12, x1 + 12, y + 12), fill=TEAL)
    draw_text(draw, (x0, y + 34), f"全樣本差異 {pp(data, 'conditional_move_response.difference_pp')}", fonts.bold(27), fill=BLUE, anchor="ma")
    draw_text(draw, (x1, y + 34), f"近 90 日差異 {pp(data, 'recent_90d_regime.difference_pp')}", fonts.bold(27), fill=TEAL, anchor="ma")
    for i in range(1, 6):
        x = x0 + (x1 - x0) * i / 6
        draw.line((x, y - 10, x, y + 10), fill=GRID, width=3)
    draw.polygon([(x1 + 28, y), (x1 - 8, y - 18), (x1 - 8, y + 18)], fill=TEAL)


def render_panel_3(data: dict, fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#FFFFFF")
    draw = ImageDraw.Draw(img)
    draw_header(draw, fonts, "03 近 90 日 regime", "近期方向差更大", "同樣是殖利率上行與下行分組，近 90 日的差距明顯擴張")

    stat_card(
        draw,
        fonts,
        (96, 240, 728, 510),
        "近 90 日：殖利率上行日",
        pct(data, "recent_90d_regime.mean_move_ret_on_yield_up_pct"),
        "MOVE 當日平均變動",
        TEAL,
        TEAL_SOFT,
        icon="up",
    )
    stat_card(
        draw,
        fonts,
        (872, 240, 1504, 510),
        "近 90 日：殖利率下行日",
        pct(data, "recent_90d_regime.mean_move_ret_on_yield_down_pct"),
        "MOVE 當日平均變動",
        RED,
        RED_SOFT,
        icon="down",
    )

    rounded(draw, (96, 554, 1504, 760), fill=SOFT_BG, outline=None)
    draw_text(draw, (800, 585), "方向差距擴張", fonts.bold(36), fill=INK, anchor="ma")
    draw_delta_line(draw, fonts, data)

    rounded(draw, (96, 802, 728, 892), fill=CARD, outline=GRID)
    latest_line = (
        f"最新觀測 {n(data, 'latest.date')}  |  "
        f"MOVE {n(data, 'latest.MOVE')}  |  "
        f"10Y {n(data, 'latest.TNX_yield_pct')}%"
    )
    draw_centered(draw, (96, 802, 728, 892), latest_line, fonts.bold(25), fill=INK)

    rounded(draw, (872, 802, 1504, 892), fill=GREEN_SOFT, outline=None)
    draw_centered(
        draw,
        (872, 802, 1504, 892),
        f"近 90 日上行 - 下行：{pp(data, 'recent_90d_regime.difference_pp')}",
        fonts.bold(33),
        fill=GREEN,
    )

    draw_footer(draw, fonts, data)
    path = OUT_DIR / "3_panel.png"
    img.save(path, dpi=DPI)
    return path


def verify_png(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing or empty PNG: {path}")
    with Image.open(path) as img:
        if img.size != (WIDTH, HEIGHT):
            raise RuntimeError(f"Unexpected dimensions for {path}: {img.size}")
        extrema = img.convert("L").getextrema()
        if extrema[0] == extrema[1]:
            raise RuntimeError(f"Blank PNG detected: {path}")


def main() -> None:
    data = load_results()
    fonts = load_fonts()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        render_panel_1(data, fonts),
        render_panel_2(data, fonts),
        render_panel_3(data, fonts),
    ]
    for path in paths:
        verify_png(path)
    print("Rendered lazypack PNGs:")
    for path in paths:
        print(path.resolve())
    print(f"CJK regular font: {fonts.regular_path}")
    print(f"CJK bold font: {fonts.bold_path}")


if __name__ == "__main__":
    main()
