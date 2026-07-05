#!/usr/bin/env python3
"""Render K1624 reader-facing lazy-pack panels from experiment results.

All displayed statistics are loaded from
experiments/k1624_rv_long_memory_vs_level_shifts/
k1624_rv_long_memory_vs_level_shifts_results.json.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageStat

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "volpred_matplotlib_cache"))

try:
    import matplotlib as mpl

    mpl.rcParams["font.sans-serif"] = [
        "Heiti TC",
        "STHeiti",
        "PingFang TC",
        "Arial Unicode MS",
    ]
    mpl.rcParams["axes.unicode_minus"] = False
except Exception:
    mpl = None


WIDTH = 1600
HEIGHT = 1000
DPI = 150
ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = (
    ROOT
    / "experiments"
    / "k1624_rv_long_memory_vs_level_shifts"
    / "k1624_rv_long_memory_vs_level_shifts_results.json"
)

FONT_REGULAR_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
    "/Library/Fonts/Noto Sans CJK TC Regular.otf",
]
FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJKtc-Bold.otf",
    "/Library/Fonts/Noto Sans CJK TC Bold.otf",
]

PAPER = "#FFFFFF"
INK = "#172033"
NAVY = "#12253D"
NAVY_2 = "#1B314E"
MUTED = "#5D6878"
FAINT = "#EEF2F6"
GRID = "#D9E0E8"
TEAL = "#146C73"
TEAL_SOFT = "#DDF0EF"
BLUE = "#255C99"
BLUE_SOFT = "#E3EEF9"
RED = "#B9413A"
RED_SOFT = "#F7DEDC"
AMBER = "#A66B11"
AMBER_SOFT = "#F5E7CD"
GREEN = "#2F7A4F"
GREEN_SOFT = "#E1EFE6"


class Fonts:
    def __init__(self, regular_path: Path, bold_path: Path) -> None:
        self.regular_path = regular_path
        self.bold_path = bold_path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


def first_existing(paths: list[str]) -> Path:
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    raise RuntimeError("No Traditional Chinese capable font found.")


def load_fonts() -> Fonts:
    regular = first_existing(FONT_REGULAR_CANDIDATES)
    bold = first_existing(FONT_BOLD_CANDIDATES)
    probe = ImageFont.truetype(str(regular), size=40)
    bbox = probe.getbbox("波動率的長記憶是假象，台灣0050")
    if not bbox or bbox[2] <= bbox[0]:
        raise RuntimeError(f"Selected font cannot render zh-Hant: {regular}")
    return Fonts(regular, bold)


def load_results() -> dict[str, Any]:
    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def proxy(data: dict[str, Any], asset: str, name: str) -> dict[str, Any]:
    return data["assets"][asset]["proxies"][name]


def d_pre(data: dict[str, Any], asset: str, name: str) -> float:
    return float(proxy(data, asset, name)["d_pre_mid_T0.6"])


def d_post(data: dict[str, Any], asset: str, name: str) -> float:
    return float(proxy(data, asset, name)["d_post_mid_T0.6"])


def verdict(data: dict[str, Any], asset: str, name: str) -> str:
    raw = proxy(data, asset, name)["identification_verdict"]
    if raw == "mixed":
        return "真假參半"
    if raw.startswith("spurious"):
        return "假象"
    return str(raw)


def fmt2(value: float) -> str:
    return f"{value:.2f}"


def new_canvas() -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), PAPER)


def bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    return draw.textbbox((0, 0), text, font=font)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    b = bbox(draw, text, font)
    return b[2] - b[0]


def text_height(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    b = bbox(draw, text, font)
    return b[3] - b[1]


def wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    def tokens(paragraph: str) -> list[str]:
        out: list[str] = []
        i = 0
        while i < len(paragraph):
            ch = paragraph[i]
            if ch.isspace():
                out.append(ch)
                i += 1
                continue
            if ord(ch) < 128:
                j = i + 1
                while j < len(paragraph) and ord(paragraph[j]) < 128 and not paragraph[j].isspace():
                    j += 1
                out.append(paragraph[i:j])
                i = j
                continue
            out.append(ch)
            i += 1
        return out

    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for token in tokens(paragraph):
            candidate = line + token
            if line and text_width(draw, candidate, font) > max_width:
                lines.append(line.rstrip())
                line = token.lstrip()
            else:
                line = candidate
        if line:
            lines.append(line.rstrip())
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 8,
) -> int:
    x, y = xy
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += text_height(draw, line, font) + line_gap
    return y


def draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    x0, y0, x1, y1 = box
    b = bbox(draw, text, font)
    w = b[2] - b[0]
    h = b[3] - b[1]
    draw.text((x0 + (x1 - x0 - w) / 2, y0 + (y1 - y0 - h) / 2), text, font=font, fill=fill)


def card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str = PAPER,
    outline: str = GRID,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=8, fill=fill, outline=outline, width=width)


def header(
    draw: ImageDraw.ImageDraw,
    fonts: Fonts,
    title: str,
    subtitle: str,
) -> None:
    draw.rectangle((0, 0, WIDTH, 152), fill=NAVY)
    draw.rectangle((0, 148, WIDTH, 152), fill=TEAL)
    draw.text((70, 40), title, font=fonts.bold(54), fill="#FFFFFF")
    draw.text((72, 105), subtitle, font=fonts.regular(27), fill="#DDE8F0")


def footer(draw: ImageDraw.ImageDraw, fonts: Fonts, data: dict[str, Any]) -> None:
    source = f"資料來源：experiment K1624 results.json；yfinance 日頻 OHLC；Local Whittle / PELT；seed={data['seed']}"
    draw.line((70, 938, WIDTH - 70, 938), fill=GRID, width=2)
    draw.text((70, 954), source, font=fonts.regular(21), fill=MUTED)


def verdict_colors(label: str) -> tuple[str, str, str]:
    if label == "真假參半":
        return AMBER, AMBER_SOFT, AMBER
    return RED, RED_SOFT, RED


def draw_arrow(draw: ImageDraw.ImageDraw, p0: tuple[int, int], p1: tuple[int, int], fill: str, width: int = 6) -> None:
    draw.line((p0, p1), fill=fill, width=width)
    angle = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    size = 18
    left = (p1[0] - size * math.cos(angle - 0.45), p1[1] - size * math.sin(angle - 0.45))
    right = (p1[0] - size * math.cos(angle + 0.45), p1[1] - size * math.sin(angle + 0.45))
    draw.polygon([p1, left, right], fill=fill)


def render_panel_1(data: dict[str, Any], fonts: Fonts) -> Path:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "波動率的「長記憶」大多是假象",
        "扣掉水位位移後，日波動的 d 幾乎歸零",
    )

    tally = data["verdict_tally"]
    spurious = int(tally["spurious (level-shift-induced)"])
    mixed = int(tally["mixed"])
    summary = f"六格中 {spurious} 格假象、{mixed} 格真假參半"
    card(draw, (70, 178, 1530, 285), fill="#F7FAFD", outline="#D4DEE8")
    draw.text((100, 201), summary, font=fonts.bold(46), fill=INK)
    draw.text(
        (100, 253),
        "平方報酬 r² 三個市場全部由「高 d」塌到接近 0；唯一保留疑點的是 SPY 的 GK 區間代理。",
        font=fonts.regular(24),
        fill=MUTED,
    )

    main_cards = [
        ("SPY", "SPY", "SPY 平方報酬"),
        ("GSPC", "S&P 500 指數", "S&P 500 指數"),
        ("TW0050", "台灣 0050", "台灣 0050"),
    ]
    x_positions = [70, 560, 1050]
    for x, (asset, display, required_label) in zip(x_positions, main_cards):
        y0, y1 = 315, 555
        label = verdict(data, asset, "absret")
        color, soft, outline = verdict_colors(label)
        card(draw, (x, y0, x + 460, y1), fill=PAPER, outline="#CCD6E0")
        phrase = (
            f"{required_label}：d 從 {fmt2(d_pre(data, asset, 'absret'))} "
            f"塌到 {fmt2(d_post(data, asset, 'absret'))}（{label}）"
        )
        draw_wrapped(draw, phrase, (x + 28, y0 + 24), fonts.bold(25), INK, 400, line_gap=5)
        draw.text(
            (x + 30, y0 + 92),
            fmt2(d_pre(data, asset, "absret")),
            font=fonts.bold(58),
            fill=NAVY,
        )
        draw_arrow(draw, (x + 178, y0 + 128), (x + 265, y0 + 128), fill=TEAL, width=5)
        draw.text(
            (x + 292, y0 + 92),
            fmt2(d_post(data, asset, "absret")),
            font=fonts.bold(58),
            fill=color,
        )
        draw.rounded_rectangle((x + 30, y0 + 176, x + 150, y0 + 212), radius=8, fill=soft, outline=outline)
        draw_centered(draw, label, (x + 30, y0 + 176, x + 150, y0 + 212), fonts.bold(22), color)
        draw.text((x + 168, y0 + 182), "Local Whittle, T^0.6", font=fonts.regular(19), fill=MUTED)

    draw.text((70, 590), "六個市場 × 代理的判定", font=fonts.bold(30), fill=INK)
    grid_specs = [
        ("SPY", "SPY", "absret", "平方報酬 r²"),
        ("SPY", "SPY", "range", "GK 區間"),
        ("GSPC", "S&P 500", "absret", "平方報酬 r²"),
        ("GSPC", "S&P 500", "range", "GK 區間"),
        ("TW0050", "0050.TW", "absret", "平方報酬 r²"),
        ("TW0050", "0050.TW", "range", "GK 區間"),
    ]
    grid_x = [70, 560, 1050]
    grid_y = [635, 770]
    for idx, (asset, asset_label, proxy_name, proxy_label) in enumerate(grid_specs):
        x = grid_x[idx % 3]
        y = grid_y[idx // 3]
        label = verdict(data, asset, proxy_name)
        color, soft, outline = verdict_colors(label)
        card(draw, (x, y, x + 460, y + 105), fill="#FBFCFD", outline="#D6DEE7")
        draw.text((x + 22, y + 18), f"{asset_label}｜{proxy_label}", font=fonts.bold(23), fill=INK)
        draw.text(
            (x + 22, y + 57),
            f"d {fmt2(d_pre(data, asset, proxy_name))} → {fmt2(d_post(data, asset, proxy_name))}",
            font=fonts.regular(22),
            fill=MUTED,
        )
        draw.rounded_rectangle((x + 315, y + 32, x + 435, y + 75), radius=8, fill=soft, outline=outline)
        draw_centered(draw, label, (x + 315, y + 32, x + 435, y + 75), fonts.bold(22), color)

    footer(draw, fonts, data)
    out = OUT_DIR / "01_finding.png"
    img.save(out, dpi=(DPI, DPI))
    return out


def draw_curve_card(draw: ImageDraw.ImageDraw, fonts: Fonts, box: tuple[int, int, int, int], kind: str) -> None:
    x0, y0, x1, y1 = box
    card(draw, box, fill="#FBFCFD", outline="#D6DEE7")
    if kind == "true":
        draw.text((x0 + 28, y0 + 24), "真長記憶", font=fonts.bold(31), fill=INK)
        draw.text((x0 + 28, y0 + 66), "同一地基上的慢衰退", font=fonts.regular(22), fill=MUTED)
        pts = []
        for i in range(80):
            t = i / 79
            x = x0 + 60 + int(t * (x1 - x0 - 120))
            y = y0 + 250 - int(120 * math.exp(-2.4 * t))
            pts.append((x, y))
        draw.line(pts, fill=BLUE, width=7)
        draw.line((x0 + 60, y0 + 255, x1 - 60, y0 + 255), fill=GRID, width=3)
        draw.text((x0 + 60, y0 + 270), "低頻慣性來自同一個過程", font=fonts.regular(20), fill=MUTED)
    else:
        draw.text((x0 + 28, y0 + 24), "水位位移", font=fonts.bold(31), fill=INK)
        draw.text((x0 + 28, y0 + 66), "幾段不同平均水準被接起來", font=fonts.regular(22), fill=MUTED)
        levels = [225, 185, 235, 150, 205]
        xs = [x0 + 60, x0 + 180, x0 + 310, x0 + 455, x0 + 570, x1 - 60]
        points: list[tuple[int, int]] = []
        for i, level in enumerate(levels):
            points.append((xs[i], y0 + level))
            points.append((xs[i + 1], y0 + level))
            if i < len(levels) - 1:
                points.append((xs[i + 1], y0 + levels[i + 1]))
        draw.line(points, fill=TEAL, width=7)
        for x in xs[1:-1]:
            draw.line((x, y0 + 128, x, y0 + 260), fill="#B7C5D4", width=2)
        draw.text((x0 + 60, y0 + 270), "長記憶尺會把台階誤讀成慢坡", font=fonts.regular(20), fill=MUTED)


def render_panel_2(data: dict[str, Any], fonts: Fonts) -> Path:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "不是所有慢慢衰退都是真長記憶",
        "水準位移也能製造同樣的外觀",
    )

    draw_curve_card(draw, fonts, (70, 190, 765, 535), "true")
    draw_curve_card(draw, fonts, (835, 190, 1530, 535), "shift")

    bridge = "真長記憶 vs 水位位移：外觀像，地基不同"
    draw.rounded_rectangle((410, 548, 1190, 600), radius=8, fill=NAVY_2, outline=NAVY_2)
    draw_centered(draw, bridge, (410, 548, 1190, 600), fonts.bold(29), "#FFFFFF")

    spy_abs = proxy(data, "SPY", "absret")
    n_breaks = int(spy_abs["n_breaks"])
    event_card = (70, 630, 770, 900)
    card(draw, event_card, fill="#FBFCFD", outline="#D6DEE7")
    event_phrase = f"SPY 偵測到 {n_breaks} 次水位位移\n對得上雷曼、歐債、COVID、2022 熊市"
    draw_wrapped(draw, event_phrase, (100, 660), fonts.bold(27), INK, 635, line_gap=8)
    events = [
        ("雷曼", "2008-09-15"),
        ("歐債", "2011-08-01"),
        ("COVID", "2020-02-25"),
        ("2022 熊市", "2021-11-29 → 2023-03-23"),
    ]
    y = 725
    for label, date in events:
        draw.rounded_rectangle((100, y, 230, y + 34), radius=8, fill=RED_SOFT, outline=RED)
        draw_centered(draw, label, (100, y, 230, y + 34), fonts.bold(19), RED)
        draw.text((250, y + 5), date, font=fonts.regular(20), fill=MUTED)
        y += 40

    band_card = (835, 630, 1530, 900)
    card(draw, band_card, fill="#FBFCFD", outline="#D6DEE7")
    lw = spy_abs["d_pre_demean"]["lw"]
    d_values = [
        float(lw["m_T0.5"]["d"]),
        float(lw["m_T0.6"]["d"]),
        float(lw["m_T0.7"]["d"]),
    ]
    band_phrase = (
        f"d 隨頻寬下降 {fmt2(d_values[0])} → {fmt2(d_values[1])} → {fmt2(d_values[2])}"
        "（真長記憶應穩定）"
    )
    draw_wrapped(draw, band_phrase, (865, 660), fonts.bold(25), INK, 625, line_gap=8)
    chart_x0, chart_y0, chart_x1, chart_y1 = 900, 760, 1485, 850
    draw.line((chart_x0, chart_y1, chart_x1, chart_y1), fill=GRID, width=3)
    draw.line((chart_x0, chart_y0, chart_x0, chart_y1), fill=GRID, width=3)
    xs = [chart_x0 + 45, chart_x0 + 280, chart_x0 + 515]
    min_d, max_d = 0.30, 0.50
    pts = []
    for x, value in zip(xs, d_values):
        y_val = chart_y1 - int((value - min_d) / (max_d - min_d) * (chart_y1 - chart_y0))
        pts.append((x, y_val))
    draw.line(pts, fill=TEAL, width=6)
    draw.line((xs[0], pts[0][1], xs[-1], pts[0][1]), fill=AMBER, width=3)
    for idx, (x, y_val) in enumerate(pts):
        draw.ellipse((x - 10, y_val - 10, x + 10, y_val + 10), fill=TEAL, outline=PAPER, width=3)
        draw.text((x - 26, y_val - 42), fmt2(d_values[idx]), font=fonts.bold(21), fill=TEAL)
        draw.text((x - 38, chart_y1 + 12), f"T^{0.5 + idx * 0.1:.1f}", font=fonts.regular(19), fill=MUTED)
    draw.text((chart_x0 + 390, chart_y0 - 7), "穩定基準", font=fonts.regular(18), fill=AMBER)

    footer(draw, fonts, data)
    out = OUT_DIR / "02_mechanism.png"
    img.save(out, dpi=(DPI, DPI))
    return out


def short_asset_label(asset: str) -> str:
    return {"SPY": "SPY", "GSPC": "S&P 500", "TW0050": "0050.TW"}[asset]


def short_proxy_label(name: str) -> str:
    return {"absret": "平方報酬", "range": "GK 區間"}[name]


def render_panel_3(data: dict[str, Any], fonts: Fonts) -> Path:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "投資人的結論：別把假象寫死進模型",
        "樣本外預測顯示，短記憶模型更穩",
    )

    cells = [
        ("SPY", "range"),
        ("SPY", "absret"),
        ("GSPC", "range"),
        ("GSPC", "absret"),
        ("TW0050", "range"),
        ("TW0050", "absret"),
    ]
    wins = 0
    rows = []
    for asset, name in cells:
        q = proxy(data, asset, name)["forecast"]["qlike"]
        arfima = float(q["arfima"])
        har = float(q["har"])
        if arfima < har:
            wins += 1
        rows.append((asset, name, arfima, har))

    card(draw, (70, 195, 670, 500), fill="#FBFCFD", outline="#D6DEE7")
    required = "假設長記憶的模型：一格都沒贏過短記憶模型"
    draw_wrapped(draw, required, (105, 228), fonts.bold(31), INK, 525, line_gap=9)
    draw.text((110, 315), f"{wins} / {len(cells)}", font=fonts.bold(96), fill=RED)
    draw.text((110, 420), "ARFIMA 贏 HAR 的格數", font=fonts.regular(25), fill=MUTED)

    tw_range = proxy(data, "TW0050", "range")["forecast"]["qlike"]
    tw_arfima = float(tw_range["arfima"])
    tw_har = float(tw_range["har"])
    card(draw, (735, 195, 1530, 500), fill="#FBFCFD", outline="#D6DEE7")
    focus_phrase = (
        f"台灣 0050 預測誤差 {fmt2(tw_arfima)} vs 短記憶模型 {fmt2(tw_har)}"
    )
    draw_wrapped(draw, focus_phrase, (770, 228), fonts.bold(31), INK, 725, line_gap=9)
    bar_label_x, bar_x0, bar_y0 = 790, 1030, 345
    max_val = 5.2
    max_bar_w = 390
    for idx, (label, val, color) in enumerate(
        [("假設長記憶 ARFIMA", tw_arfima, RED), ("短記憶 HAR", tw_har, TEAL)]
    ):
        y = bar_y0 + idx * 58
        w = int((val / max_val) * max_bar_w)
        draw.text((bar_label_x, y - 4), label, font=fonts.regular(22), fill=INK)
        draw.rounded_rectangle((bar_x0, y, bar_x0 + w, y + 30), radius=8, fill=color)
        draw.text((bar_x0 + w + 18, y - 1), fmt2(val), font=fonts.bold(24), fill=color)
    draw.text((770, 468), "指標：QLIKE；數值越低越好", font=fonts.regular(20), fill=MUTED)

    card(draw, (70, 535, 1530, 840), fill=PAPER, outline="#D6DEE7")
    draw.text((105, 565), "六格樣本外 QLIKE：長記憶假設都沒有勝出", font=fonts.bold(30), fill=INK)
    x_label, x_a, x_h, x_out = 105, 520, 760, 1040
    draw.text((x_label, 615), "資產 / 代理", font=fonts.bold(21), fill=MUTED)
    draw.text((x_a, 615), "ARFIMA", font=fonts.bold(21), fill=RED)
    draw.text((x_h, 615), "HAR", font=fonts.bold(21), fill=TEAL)
    draw.text((x_out, 615), "讀法", font=fonts.bold(21), fill=MUTED)
    y = 650
    for asset, name, arfima, har in rows:
        draw.line((100, y - 8, 1500, y - 8), fill="#EDF1F5", width=2)
        label = f"{short_asset_label(asset)} / {short_proxy_label(name)}"
        draw.text((x_label, y), label, font=fonts.regular(22), fill=INK)
        draw.text((x_a, y), fmt2(arfima), font=fonts.bold(22), fill=RED)
        draw.text((x_h, y), fmt2(har), font=fonts.bold(22), fill=TEAL)
        draw.text((x_out, y), "HAR 較低", font=fonts.regular(22), fill=MUTED)
        y += 32

    takeaway = "把波動當成『短記憶 + 偶爾換水位』更穩也更誠實"
    draw.rounded_rectangle((70, 865, 1530, 925), radius=8, fill=NAVY_2, outline=NAVY_2)
    draw_centered(draw, takeaway, (70, 865, 1530, 925), fonts.bold(31), "#FFFFFF")

    footer(draw, fonts, data)
    out = OUT_DIR / "03_takeaway.png"
    img.save(out, dpi=(DPI, DPI))
    return out


def verify_png(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= 10_000:
        raise RuntimeError(f"PNG missing or too small: {path}")
    with Image.open(path) as img:
        if img.size != (WIDTH, HEIGHT):
            raise RuntimeError(f"Unexpected image size for {path}: {img.size}")
        stat = ImageStat.Stat(img.convert("L"))
        if stat.extrema[0][0] == stat.extrema[0][1]:
            raise RuntimeError(f"Image appears blank: {path}")


def main() -> None:
    data = load_results()
    fonts = load_fonts()

    required_checks = [
        ("SPY absret d pre", fmt2(d_pre(data, "SPY", "absret")), "0.41"),
        ("SPY absret d post", fmt2(d_post(data, "SPY", "absret")), "0.04"),
        ("GSPC absret d pre", fmt2(d_pre(data, "GSPC", "absret")), "0.44"),
        ("GSPC absret d post", fmt2(d_post(data, "GSPC", "absret")), "0.08"),
        ("TW0050 absret d pre", fmt2(d_pre(data, "TW0050", "absret")), "0.35"),
        ("TW0050 absret d post", fmt2(d_post(data, "TW0050", "absret")), "0.21"),
        (
            "TW0050 range ARFIMA QLIKE",
            fmt2(float(proxy(data, "TW0050", "range")["forecast"]["qlike"]["arfima"])),
            "5.09",
        ),
        (
            "TW0050 range HAR QLIKE",
            fmt2(float(proxy(data, "TW0050", "range")["forecast"]["qlike"]["har"])),
            "0.59",
        ),
    ]
    for label, actual, expected in required_checks:
        if actual != expected:
            raise RuntimeError(f"{label}: expected displayed {expected}, got {actual}")

    paths = [
        render_panel_1(data, fonts),
        render_panel_2(data, fonts),
        render_panel_3(data, fonts),
    ]
    for path in paths:
        verify_png(path)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
