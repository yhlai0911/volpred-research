#!/usr/bin/env python3
"""Render K1627 懶人包 PNG panels from evidence JSON.

All displayed statistics are read from ../k1627_results.json.  The README is
loaded as part of the evidence package, but numeric values are never taken from
README prose.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)
MARGIN = 72

EXP_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXP_DIR / "k1627_results.json"
README_PATH = EXP_DIR / "README.md"

INK = "#18202B"
MUTED = "#536172"
FAINT = "#7B8794"
PAPER = "#FFFFFF"
SURFACE = "#F5F7FA"
GRID = "#D9E0EA"
HEADER = "#17202A"
HEADER_2 = "#243244"
TEAL = "#177C7D"
TEAL_SOFT = "#DCEFEF"
BLUE = "#245B8F"
BLUE_SOFT = "#E1EBF7"
AMBER = "#A76616"
AMBER_SOFT = "#F4E5CC"
RED = "#C84038"
RED_SOFT = "#F4DAD8"
GREEN = "#277B4C"
GREEN_SOFT = "#DDEFE4"


FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
    "/Library/Fonts/Noto Sans CJK TC Regular.otf",
]

FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJKtc-Bold.otf",
    "/Library/Fonts/Noto Sans CJK TC Bold.otf",
]


@dataclass(frozen=True)
class FontBook:
    regular_path: Path
    bold_path: Path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


def first_existing(paths: list[str]) -> Path | None:
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    return None


def load_fonts() -> FontBook:
    regular = first_existing(FONT_CANDIDATES_REGULAR)
    bold = first_existing(FONT_CANDIDATES_BOLD)
    if regular is None or bold is None:
        raise RuntimeError("找不到可用 CJK 字型，無法保證繁體中文不缺字。")

    probe = ImageFont.truetype(str(regular), size=40)
    if probe.getbbox("美股大跌台股必補跌") is None:
        raise RuntimeError(f"選到的字型無法渲染繁體中文：{regular}")
    return FontBook(regular, bold)


def load_evidence() -> dict[str, Any]:
    if not RESULTS_PATH.exists():
        raise FileNotFoundError(RESULTS_PATH)
    if not README_PATH.exists():
        raise FileNotFoundError(README_PATH)

    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    readme = README_PATH.read_text(encoding="utf-8")
    if "無 lookahead" not in readme:
        raise RuntimeError("README 缺少無 lookahead 方法說明，停止渲染。")
    return data


def get_path(data: dict[str, Any], path: str | list[str | int]) -> Any:
    current: Any = data
    parts: list[str | int] = path.split(".") if isinstance(path, str) else path
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(str(path))
    return current


def pct_1(value: float) -> str:
    return f"{value * 100:.1f}%"


def comma_int(value: int) -> str:
    return f"{value:,}"


def new_canvas() -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), PAPER)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


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
        for char in paragraph:
            candidate = current + char
            if text_size(draw, candidate, font)[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = char
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
    line_gap: int = 8,
) -> int:
    x, y = xy
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += text_size(draw, line or " ", font)[1] + line_gap
    return y


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_fn,
    max_width: int,
    start: int,
    minimum: int,
) -> ImageFont.FreeTypeFont:
    for size in range(start, minimum - 1, -2):
        font = font_fn(size)
        if text_size(draw, text, font)[0] <= max_width:
            return font
    return font_fn(minimum)


def rounded_card(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    fill: str = SURFACE,
    outline: str = GRID,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(xy, radius=8, fill=fill, outline=outline, width=width)


def draw_header(draw: ImageDraw.ImageDraw, fonts: FontBook, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, 170), fill=HEADER)
    draw.rectangle((0, 156, WIDTH, 170), fill=TEAL)
    draw.rectangle((0, 0, 18, 170), fill=AMBER)
    title_font = fit_font(draw, title, fonts.bold, WIDTH - 2 * MARGIN, 58, 42)
    draw.text((MARGIN, 44), title, font=title_font, fill="#FFFFFF")
    draw.text((MARGIN, 114), subtitle, font=fonts.regular(28), fill="#D5DCE5")


def draw_footer(draw: ImageDraw.ImageDraw, fonts: FontBook, experiment_id: str) -> None:
    y = 930
    draw.line((MARGIN, y, WIDTH - MARGIN, y), fill=GRID, width=2)
    draw.text(
        (MARGIN, y + 24),
        f"資料來源：experiment {experiment_id.upper()}",
        font=fonts.regular(24),
        fill=FAINT,
    )
    draw.text(
        (WIDTH - 470, y + 24),
        "VolPred 懶人包圖組",
        font=fonts.regular(24),
        fill=FAINT,
    )


def draw_metric_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    xy: tuple[int, int, int, int],
    label: str,
    value: str,
    note: str,
    accent: str,
    soft: str,
) -> None:
    x1, y1, x2, y2 = xy
    rounded_card(draw, xy, fill="#FFFFFF")
    draw.rectangle((x1, y1, x1 + 12, y2), fill=accent)
    draw.rounded_rectangle((x1 + 28, y1 + 26, x1 + 118, y1 + 62), radius=8, fill=soft)
    draw.text((x1 + 42, y1 + 30), label, font=fonts.bold(22), fill=accent)
    value_font = fit_font(draw, value, fonts.bold, x2 - x1 - 70, 58, 36)
    draw.text((x1 + 34, y1 + 88), value, font=value_font, fill=INK)
    draw_wrapped(draw, (x1 + 36, y1 + 164), note, fonts.regular(25), MUTED, x2 - x1 - 72, 8)


def draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str) -> None:
    x1, y1 = start
    x2, y2 = end
    draw.line((x1, y1, x2 - 16, y2), fill=color, width=5)
    draw.polygon([(x2, y2), (x2 - 24, y2 - 14), (x2 - 24, y2 + 14)], fill=color)


def panel_framework(data: dict[str, Any], fonts: FontBook) -> Image.Image:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    exp_id = str(get_path(data, "experiment_id"))
    us = str(get_path(data, "data.us_ticker"))
    tw = str(get_path(data, "data.tw_ticker"))
    start = str(get_path(data, "data.analysis_start"))
    start_year = start[:4]
    n_pairs = int(get_path(data, "data.n_pairs"))

    draw_header(
        draw,
        fonts,
        "美股大跌，台股隔天必補跌？",
        "股版老話，用真實數據拆成「機率」與「必然」兩件事",
    )

    rounded_card(draw, (MARGIN, 220, WIDTH - MARGIN, 438), fill=SURFACE)
    draw.text((104, 250), "核心問題", font=fonts.bold(30), fill=TEAL)
    quote = "「美股大跌，台股隔天必補跌？」這句股版老話成不成立。"
    quote_font = fit_font(draw, quote, fonts.bold, 1320, 52, 38)
    draw.text((104, 300), quote, font=quote_font, fill=INK)
    draw_wrapped(
        draw,
        (104, 372),
        "白話說：跟跌「機率」變高，不等於每一次都「必然」下跌；本篇用真實數據檢驗。",
        fonts.regular(30),
        MUTED,
        1380,
        10,
    )

    draw_metric_card(
        draw,
        fonts,
        (MARGIN, 492, 508, 728),
        "機率",
        "會不會更容易跌？",
        "比較不同美股跌幅後，台股次日下跌比例是否升高。",
        TEAL,
        TEAL_SOFT,
    )
    draw_metric_card(
        draw,
        fonts,
        (556, 492, 992, 728),
        "必然",
        "是不是 100%？",
        "「必補跌」是更強說法；只要不是 100%，就不能說成必然。",
        RED,
        RED_SOFT,
    )
    draw_metric_card(
        draw,
        fonts,
        (1040, 492, WIDTH - MARGIN, 728),
        "檢驗",
        f"N={comma_int(n_pairs)}",
        f"{us} 對 {tw}\n自 {start_year}年起逐日配對，回答老話",
        BLUE,
        BLUE_SOFT,
    )

    rounded_card(draw, (MARGIN, 772, WIDTH - MARGIN, 890), fill="#FFFFFF")
    draw.text((104, 804), "讀圖重點", font=fonts.bold(30), fill=INK)
    draw_wrapped(
        draw,
        (104, 846),
        "本組圖只回答一件事：隔夜美股下跌是否提高台股下一個交易日下跌機率，以及它能不能被說成「必」。",
        fonts.regular(27),
        MUTED,
        1360,
        8,
    )

    draw_footer(draw, fonts, exp_id)
    return img


def panel_method(data: dict[str, Any], fonts: FontBook) -> Image.Image:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    exp_id = str(get_path(data, "experiment_id"))
    us = str(get_path(data, "data.us_ticker"))
    tw = str(get_path(data, "data.tw_ticker"))
    start = str(get_path(data, "data.analysis_start"))
    start_year = start[:4]
    n_pairs = int(get_path(data, "data.n_pairs"))
    no_lookahead = str(get_path(data, "alignment.no_lookahead_reason"))
    if not no_lookahead:
        raise RuntimeError("Missing no-lookahead evidence in k1627_results.json")

    draw_header(
        draw,
        fonts,
        "怎麼查：把美股收盤對到台股下一天",
        f"{start_year}年起，{us} 與 {tw} 逐日配對，共 N={comma_int(n_pairs)} 組",
    )

    cards = [
        (
            (MARGIN, 238, 508, 690),
            "1",
            "逐日配對",
            f"把 {us} 每日收盤報酬\n配到 {tw} 次一交易日。",
            f"N={comma_int(n_pairs)} 組",
            TEAL,
            TEAL_SOFT,
        ),
        (
            (556, 238, 992, 690),
            "2",
            "守住時間順序",
            "美股收盤在台灣半夜已經發生，再對照台股下一個交易日，時間順序合理。",
            "無偷看未來",
            BLUE,
            BLUE_SOFT,
        ),
        (
            (1040, 238, WIDTH - MARGIN, 690),
            "3",
            "按跌幅分組",
            "把美股收黑、跌破 1%、跌破 2%、跌破 3% 分組，計算每組台股次日下跌比例。",
            "算下跌比例",
            AMBER,
            AMBER_SOFT,
        ),
    ]
    for xy, num, title, body, badge, accent, soft in cards:
        x1, y1, x2, y2 = xy
        rounded_card(draw, xy, fill="#FFFFFF")
        draw.ellipse((x1 + 32, y1 + 30, x1 + 94, y1 + 92), fill=accent)
        draw.text((x1 + 52, y1 + 43), num, font=fonts.bold(30), fill="#FFFFFF")
        draw.text((x1 + 118, y1 + 40), title, font=fonts.bold(34), fill=INK)
        draw.rounded_rectangle((x1 + 34, y1 + 120, x1 + 250, y1 + 170), radius=8, fill=soft)
        draw.text((x1 + 52, y1 + 130), badge, font=fonts.bold(25), fill=accent)
        draw_wrapped(draw, (x1 + 34, y1 + 212), body, fonts.regular(29), MUTED, x2 - x1 - 68, 12)

    draw_arrow(draw, (510, 464), (548, 464), FAINT)
    draw_arrow(draw, (994, 464), (1032, 464), FAINT)

    rounded_card(draw, (MARGIN, 744, WIDTH - MARGIN, 890), fill=SURFACE)
    draw.text((104, 778), "關鍵防錯", font=fonts.bold(31), fill=RED)
    draw_wrapped(
        draw,
        (104, 824),
        "美股收盤（台灣半夜）已經發生；台股下一個交易日尚未開盤。不是同日硬對同日，也不是先知道台股結果再回頭挑訊號。",
        fonts.regular(28),
        INK,
        1368,
        8,
    )

    draw_footer(draw, fonts, exp_id)
    return img


def draw_bar(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    y: int,
    label: str,
    value: float,
    color: str,
    x: int = 120,
    width: int = 820,
) -> None:
    bar_x = x + 310
    bar_y = y + 12
    bar_w = width - 350
    draw.text((x, y), label, font=fonts.bold(28), fill=INK)
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 36), radius=8, fill="#E8EDF3")
    fill_w = int(bar_w * value)
    draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + 36), radius=8, fill=color)
    draw.text((bar_x + bar_w + 22, y - 4), pct_1(value), font=fonts.bold(42), fill=color)


def panel_results(data: dict[str, Any], fonts: FontBook) -> Image.Image:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    exp_id = str(get_path(data, "experiment_id"))

    p_nonneg = float(get_path(data, "control_us_nonneg.P_tw_down_main"))
    p_down = float(get_path(data, ["by_threshold", "us_below_+0.00", "P_tw_down_given_event_main"]))
    p_down2 = float(get_path(data, ["by_threshold", "us_below_-0.02", "P_tw_down_given_event_main"]))
    boot_hi = float(get_path(data, ["bootstrap_main_threshold", "ci95", 1]))
    beta = float(get_path(data, "regression.beta"))

    draw_header(
        draw,
        fonts,
        "結果：跟跌機率升高，但不是必然",
        "K1627 主定義：台股下一個交易日報酬 < 0",
    )

    rounded_card(draw, (MARGIN, 220, 1010, 742), fill="#FFFFFF")
    draw.text((112, 250), "台股次日下跌機率", font=fonts.bold(36), fill=INK)
    draw.text((112, 300), "條件越嚴格，機率越高；但沒有到 100%。", font=fonts.regular(27), fill=MUTED)
    draw_bar(draw, fonts, 386, "美股沒跌", p_nonneg, TEAL)
    draw_bar(draw, fonts, 496, "美股收黑", p_down, AMBER)
    draw_bar(draw, fonts, 606, "美股跌破 2%", p_down2, RED)
    draw.line((902, 360, 902, 682), fill="#9AA5B3", width=3)
    for yy in range(360, 682, 22):
        draw.line((902, yy, 902, yy + 10), fill="#9AA5B3", width=3)
    draw.text((764, 704), "100% 才叫必然", font=fonts.regular(25), fill=FAINT)

    draw_metric_card(
        draw,
        fonts,
        (1058, 220, WIDTH - MARGIN, 456),
        "不是 100%",
        f"抽樣上緣 {pct_1(boot_hi)}",
        "主門檻自助抽樣 95% 區間上界仍低於 100%，所以「必」不成立。",
        RED,
        RED_SOFT,
    )
    draw_metric_card(
        draw,
        fonts,
        (1058, 506, WIDTH - MARGIN, 742),
        "打折跟跌",
        f"beta={beta:.3f}",
        f"傳導係數約 {beta:.3f}：美股每跌 1%，台股次日平均約跌 {beta:.3f}%，不是全額補跌。",
        BLUE,
        BLUE_SOFT,
    )

    rounded_card(draw, (MARGIN, 790, WIDTH - MARGIN, 890), fill=SURFACE)
    conclusion = (
        f"一句話：{pct_1(p_nonneg)} 升到 {pct_1(p_down)}，再到 {pct_1(p_down2)}；"
        "機率確實大幅升高、越跌越高，但「必」不成立，且是打折補跌。"
    )
    draw_wrapped(draw, (104, 818), conclusion, fonts.bold(31), INK, 1380, 8)

    draw_footer(draw, fonts, exp_id)
    return img


def save_panel(img: Image.Image, name: str) -> Path:
    path = OUT_DIR / name
    img.save(path, dpi=DPI)
    if path.stat().st_size <= 0:
        raise RuntimeError(f"輸出檔案為空：{path}")
    return path


def main() -> None:
    data = load_evidence()
    fonts = load_fonts()
    outputs = [
        save_panel(panel_framework(data, fonts), "1_framework.png"),
        save_panel(panel_method(data, fonts), "2_method.png"),
        save_panel(panel_results(data, fonts), "3_results.png"),
    ]
    for path in outputs:
        print(path.resolve())


if __name__ == "__main__":
    main()
