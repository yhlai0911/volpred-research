#!/usr/bin/env python3
"""Render K1632 VolPred lazypack panels as data-bound PNG files.

The renderer uses Pillow only. Every displayed statistic is read from
experiments/k1632/k1632_results.json and formatted at render time.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from fontTools.ttLib import TTCollection, TTFont
from PIL import Image, ImageChops, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)
WHITE = "#FFFFFF"
INK = "#111827"
MUTED = "#4B5563"
FAINT = "#6B7280"
BORDER = "#D7DEE8"
GRID = "#EEF2F7"
NAVY = "#172033"
TEAL = "#0F766E"
TEAL_SOFT = "#E0F2F1"
BLUE = "#1D4E89"
BLUE_SOFT = "#E5EEF8"
AMBER = "#B45309"
AMBER_SOFT = "#FEF3C7"
RED = "#B91C1C"
RED_SOFT = "#FEE2E2"
GREEN = "#15803D"
GREEN_SOFT = "#DCFCE7"
SLATE_SOFT = "#F3F6FA"

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = PROJECT_ROOT / "experiments/k1632/k1632_results.json"
README_PATH = PROJECT_ROOT / "experiments/k1632/README.md"
ARTICLE_PATH = Path(
    "/private/var/folders/f1/g41vrs0n20v7cx66qzcsd1nc0000gn/T/tmpsjplmy7m_article.md"
)
OUT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class FontChoice:
    name: str
    regular_path: Path
    bold_path: Path


@dataclass(frozen=True)
class Fonts:
    choice: FontChoice

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.choice.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.choice.bold_path), size=size)


FONT_CANDIDATES = [
    FontChoice(
        "Heiti TC",
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    ),
    FontChoice(
        "Arial Unicode MS",
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ),
    FontChoice(
        "Arial Unicode MS",
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ),
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def font_codepoints(path: Path) -> set[int]:
    if path.suffix.lower() == ".ttc":
        collection = TTCollection(str(path))
        fonts = collection.fonts
    else:
        fonts = [TTFont(str(path))]

    codepoints: set[int] = set()
    for font in fonts:
        for table in font["cmap"].tables:
            codepoints.update(table.cmap.keys())
    return codepoints


def nonspace_codepoints(texts: Iterable[str]) -> set[int]:
    points: set[int] = set()
    for text in texts:
        for ch in text:
            if not ch.isspace():
                points.add(ord(ch))
    return points


def select_fonts(all_text: list[str]) -> Fonts:
    needed = nonspace_codepoints(all_text)
    for candidate in FONT_CANDIDATES:
        if not candidate.regular_path.exists() or not candidate.bold_path.exists():
            continue
        supported = font_codepoints(candidate.regular_path) | font_codepoints(candidate.bold_path)
        missing = needed - supported
        if not missing:
            return Fonts(candidate)

    missing_preview = "".join(chr(cp) for cp in sorted(missing)[:20]) if "missing" in locals() else ""
    raise RuntimeError(f"No configured CJK font supports all panel text. Missing: {missing_preview}")


def pct(value: float, digits: int = 2, signed: bool = False) -> str:
    scaled = value * 100
    sign = "+" if signed else ""
    return f"{scaled:{sign}.{digits}f}%"


def fmt_int(value: int) -> str:
    return f"{value:,}"


def split_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9._%+\-/:=]+|\s+|.", text)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(bbox[2] - bbox[0])


def line_height(font: ImageFont.FreeTypeFont, spacing: float = 1.22) -> int:
    bbox = font.getbbox("國")
    return int((bbox[3] - bbox[1]) * spacing)


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for token in split_tokens(paragraph):
            candidate = current + token
            if text_width(draw, candidate, font) <= max_width or not current:
                current = candidate
                continue
            lines.append(current.rstrip())
            current = token.lstrip()
        if current:
            lines.append(current.rstrip())
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    spacing: float = 1.22,
) -> int:
    x, y = xy
    lh = line_height(font, spacing)
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += lh
    return y


def draw_header(draw: ImageDraw.ImageDraw, fonts: Fonts, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, 145), fill=NAVY)
    draw.text((80, 36), title, font=fonts.bold(54), fill=WHITE)
    draw.text((80, 98), subtitle, font=fonts.regular(26), fill="#D9E2EF")
    draw.text((1345, 56), "VolPred", font=fonts.bold(33), fill="#F9FAFB")
    draw.line((80, 145, 1520, 145), fill="#253148", width=1)


def draw_footer(draw: ImageDraw.ImageDraw, fonts: Fonts) -> None:
    footer = "資料來源：experiment K1632；數字綁定 experiments/k1632/k1632_results.json"
    draw.line((80, 950, 1520, 950), fill=BORDER, width=2)
    draw.text((80, 965), footer, font=fonts.regular(20), fill=FAINT)


def rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str = BORDER,
    width: int = 2,
    radius: int = 8,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_callout(
    draw: ImageDraw.ImageDraw,
    fonts: Fonts,
    box: tuple[int, int, int, int],
    title: str,
    body: str,
    accent: str,
    fill: str,
) -> None:
    rounded_rect(draw, box, fill=fill, outline=accent, width=3)
    x1, y1, x2, _ = box
    draw.rectangle((x1, y1, x1 + 12, box[3]), fill=accent)
    draw_wrapped(draw, title, (x1 + 34, y1 + 28), fonts.bold(34), accent, x2 - x1 - 68)
    draw_wrapped(draw, body, (x1 + 34, y1 + 90), fonts.regular(28), INK, x2 - x1 - 68)


def draw_bar_pair(
    draw: ImageDraw.ImageDraw,
    fonts: Fonts,
    x: int,
    y: int,
    width: int,
    event: float,
    other: float,
    event_label: str,
) -> None:
    max_value = max(event, other) * 1.18
    label_font = fonts.regular(20)
    value_font = fonts.bold(22)
    bar_h = 24
    rows = [(event_label, event, TEAL), ("其他日", other, "#94A3B8")]
    for idx, (label, value, color) in enumerate(rows):
        yy = y + idx * 48
        draw.text((x, yy - 2), label, font=label_font, fill=MUTED)
        bx = x + 108
        bw = int(width * value / max_value)
        draw.rounded_rectangle((bx, yy, bx + width, yy + bar_h), radius=5, fill=GRID)
        draw.rounded_rectangle((bx, yy, bx + bw, yy + bar_h), radius=5, fill=color)
        draw.text((bx + width + 16, yy - 4), pct(value), font=value_font, fill=INK)


def draw_market_card(
    draw: ImageDraw.ImageDraw,
    fonts: Fonts,
    x: int,
    y: int,
    w: int,
    market: str,
    event_vol: float,
    other_vol: float,
    diff: float,
    ci_low: float,
    ci_high: float,
) -> None:
    rounded_rect(draw, (x, y, x + w, y + 315), fill=WHITE, outline=BORDER, width=2)
    draw.text((x + 34, y + 26), market, font=fonts.bold(36), fill=INK)
    draw.text((x + 34, y + 70), "盤整達 10 天後，未來 20 日年化波動", font=fonts.regular(23), fill=MUTED)
    draw.text((x + 34, y + 112), pct(event_vol), font=fonts.bold(72), fill=TEAL)
    draw.text((x + 305, y + 137), f"vs 其他日 {pct(other_vol)}", font=fonts.regular(27), fill=MUTED)
    draw.text((x + 34, y + 202), f"差 {pct(diff, signed=True)}", font=fonts.bold(34), fill=RED)
    draw.text((x + 190, y + 207), f"Bootstrap 95%：{pct(ci_low, signed=True)} 到 {pct(ci_high, signed=True)}", font=fonts.regular(24), fill=FAINT)
    draw_bar_pair(draw, fonts, x + 34, y + 254, w - 220, event_vol, other_vol, "盤整後")


def render_panel_1(data: dict, fonts: Fonts, out_path: Path) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    draw_header(draw, fonts, "盤整越久懶人包", "先分清楚：結束日有動作，不等於未來 20 天更震")

    headline = "核心問題：盤整越久，真的代表後面會噴更兇嗎？"
    draw_wrapped(draw, headline, (90, 205), fonts.bold(58), INK, 1420, spacing=1.12)

    draw_callout(
        draw,
        fonts,
        (100, 360, 760, 640),
        "盤整結束那天",
        "描述的是當天已經發生的單日動作；收盤後才完整知道它結束了。",
        AMBER,
        AMBER_SOFT,
    )
    draw_callout(
        draw,
        fonts,
        (840, 360, 1500, 640),
        "確認盤整後",
        "這才是事前可以問的問題：從 t+1 開始，未來 20 天會不會更震？",
        BLUE,
        BLUE_SOFT,
    )

    plain = "白話拆解：要分清楚「盤整結束那天比較有動作」與「確認盤整後，未來 20 天更震」是兩件事。"
    rounded_rect(draw, (100, 690, 1500, 790), fill=SLATE_SOFT, outline=BORDER)
    draw_wrapped(draw, plain, (132, 715), fonts.regular(30), INK, 1336, spacing=1.18)

    takeaway = "一句話：迷思只有一半成立；結束日動作變大，但後續 20 天沒有更震。"
    rounded_rect(draw, (100, 825, 1500, 910), fill=NAVY, outline=NAVY)
    draw_wrapped(draw, takeaway, (132, 848), fonts.bold(33), WHITE, 1336, spacing=1.14)

    draw_footer(draw, fonts)
    save_png(img, out_path)


def render_panel_2(data: dict, fonts: Fonts, out_path: Path) -> None:
    spy = data["asset_results"]["SPY"]
    tw = data["asset_results"]["0050.TW"]
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    draw_header(draw, fonts, "方法怎麼做？", "門檻只看過去，訊號收盤後才成立，結果從 t+1 開始")

    line1 = "資料：SPY 與 0050.TW 調整收盤價。"
    line2 = (
        f"SPY：{spy['date_start']} 至 {spy['date_end']}，共 N={fmt_int(spy['n_price_obs'])} 筆；"
        f"0050.TW：{tw['date_start']} 至 {tw['date_end']}，共 N={fmt_int(tw['n_price_obs'])} 筆。"
    )
    rounded_rect(draw, (90, 185, 1510, 310), fill=SLATE_SOFT, outline=BORDER)
    draw.text((124, 214), line1, font=fonts.bold(31), fill=INK)
    draw_wrapped(draw, line2, (124, 260), fonts.regular(26), MUTED, 1350, spacing=1.12)

    steps = [
        ("20 日觀察窗", "計算年化波動與收盤價區間"),
        ("252 日歷史門檻", "各自低於過去一年 20% 分位"),
        ("連續達 10 天", "收盤後才知道訊號成立"),
        ("從 t+1 起算", "看未來 20 天波動與絕對報酬"),
    ]
    start_x = 100
    y = 370
    step_w = 315
    gap = 45
    for idx, (title, body) in enumerate(steps):
        x = start_x + idx * (step_w + gap)
        rounded_rect(draw, (x, y, x + step_w, y + 168), fill=WHITE, outline=BORDER)
        draw.ellipse((x + 22, y + 24, x + 72, y + 74), fill=NAVY)
        draw.text((x + 39, y + 31), str(idx + 1), font=fonts.bold(26), fill=WHITE)
        draw_wrapped(draw, title, (x + 88, y + 24), fonts.bold(25), INK, step_w - 112)
        draw_wrapped(draw, body, (x + 28, y + 90), fonts.regular(23), MUTED, step_w - 56)
        if idx < len(steps) - 1:
            ax = x + step_w + 12
            ay = y + 78
            draw.line((ax, ay, ax + gap - 24, ay), fill="#9AA6B2", width=4)
            draw.polygon([(ax + gap - 24, ay - 9), (ax + gap - 24, ay + 9), (ax + gap - 8, ay)], fill="#9AA6B2")

    definition = "低波動盤整定義：20 日年化波動與 20 日價格區間，同時低於自己過去 252 日的 20% 分位門檻。"
    timing = "時間順序：門檻只用 t-1 以前資料；訊號在 t 日收盤後才知道；後續結果從 t+1 開始算，避免偷看同日報酬。"
    main_test = "主檢定：盤整連續達 10 天後，看未來 20 天年化波動與絕對報酬。"
    lower_boxes = [
        (definition, TEAL, TEAL_SOFT, (100, 600, 780, 705)),
        (timing, BLUE, BLUE_SOFT, (820, 600, 1500, 735)),
        (main_test, GREEN, GREEN_SOFT, (100, 755, 1500, 885)),
    ]
    for text, accent, fill, box in lower_boxes:
        rounded_rect(draw, box, fill=fill, outline=accent, width=3)
        draw.rectangle((box[0], box[1], box[0] + 10, box[3]), fill=accent)
        draw_wrapped(draw, text, (box[0] + 30, box[1] + 26), fonts.regular(27), INK, box[2] - box[0] - 60, spacing=1.18)

    draw_footer(draw, fonts)
    save_png(img, out_path)


def render_panel_3(data: dict, fonts: Fonts, out_path: Path) -> None:
    spy = data["asset_results"]["SPY"]
    tw = data["asset_results"]["0050.TW"]
    spy_primary = spy["signal_comparisons"]["squeeze_reaches_10d"]["20"]
    tw_primary = tw["signal_comparisons"]["squeeze_reaches_10d"]["20"]
    spy_boot = spy["bootstrap_primary_vol_diff"]
    tw_boot = tw["bootstrap_primary_vol_diff"]
    spy_break = spy["episode_end_comparisons"]["episode_end_after_10d"]["breakout_day"]
    tw_break = tw["episode_end_comparisons"]["episode_end_after_10d"]["breakout_day"]
    spy_end20 = spy["episode_end_comparisons"]["episode_end_after_10d"]["forward"]["20"]
    tw_end20 = tw["episode_end_comparisons"]["episode_end_after_10d"]["forward"]["20"]

    primary_sentence = (
        "盤整連續達 10 天後，未來 20 日年化波動："
        f"SPY {pct(spy_primary['mean_vol_event_ann'])} vs 其他日 {pct(spy_primary['mean_vol_other_ann'])}，"
        f"差 {pct(spy_primary['mean_vol_diff_event_minus_other_ann'], signed=True)}；"
        f"0050.TW {pct(tw_primary['mean_vol_event_ann'])} vs {pct(tw_primary['mean_vol_other_ann'])}，"
        f"差 {pct(tw_primary['mean_vol_diff_event_minus_other_ann'], signed=True)}。"
    )
    ci_sentence = (
        "SPY 差距 bootstrap 95% 區間 "
        f"{pct(spy_boot['ci95'][0], signed=True)} 到 {pct(spy_boot['ci95'][1], signed=True)}；"
        f"0050.TW 為 {pct(tw_boot['ci95'][0], signed=True)} 到 {pct(tw_boot['ci95'][1], signed=True)}。"
    )
    breakout_sentence = (
        "盤整結束當天絕對報酬較大："
        f"SPY {pct(spy_break['mean_breakout_day_abs_ret_event'])} vs {pct(spy_break['mean_breakout_day_abs_ret_other'])}；"
        f"0050.TW {pct(tw_break['mean_breakout_day_abs_ret_event'])} vs {pct(tw_break['mean_breakout_day_abs_ret_other'])}。"
    )
    end20_sentence = (
        "但盤整結束後 20 日年化波動仍較低："
        f"SPY {pct(spy_end20['mean_vol_event_ann'])} vs {pct(spy_end20['mean_vol_other_ann'])}；"
        f"0050.TW {pct(tw_end20['mean_vol_event_ann'])} vs {pct(tw_end20['mean_vol_other_ann'])}。"
    )
    takeaway = "一句話：可以把盤整當 watchlist 條件，但不能把它當成「後面必大噴」的證據。"

    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    draw_header(draw, fonts, "結果：迷思只有一半成立", "結束日動作變大；但確認盤整後，未來 20 天沒有更震")

    rounded_rect(draw, (90, 178, 1510, 282), fill=SLATE_SOFT, outline=BORDER)
    draw_wrapped(draw, primary_sentence, (122, 203), fonts.regular(27), INK, 1355, spacing=1.16)

    draw_market_card(
        draw,
        fonts,
        100,
        325,
        670,
        "SPY",
        spy_primary["mean_vol_event_ann"],
        spy_primary["mean_vol_other_ann"],
        spy_primary["mean_vol_diff_event_minus_other_ann"],
        spy_boot["ci95"][0],
        spy_boot["ci95"][1],
    )
    draw_market_card(
        draw,
        fonts,
        830,
        325,
        670,
        "0050.TW",
        tw_primary["mean_vol_event_ann"],
        tw_primary["mean_vol_other_ann"],
        tw_primary["mean_vol_diff_event_minus_other_ann"],
        tw_boot["ci95"][0],
        tw_boot["ci95"][1],
    )

    rounded_rect(draw, (100, 665, 1500, 730), fill=WHITE, outline=BORDER)
    draw_wrapped(draw, ci_sentence, (128, 683), fonts.regular(24), MUTED, 1340, spacing=1.1)

    rounded_rect(draw, (100, 758, 1500, 825), fill=AMBER_SOFT, outline=AMBER, width=3)
    draw_wrapped(draw, breakout_sentence, (128, 777), fonts.regular(25), INK, 1340, spacing=1.1)

    rounded_rect(draw, (100, 842, 1500, 906), fill=BLUE_SOFT, outline=BLUE, width=3)
    draw_wrapped(draw, end20_sentence, (128, 860), fonts.regular(25), INK, 1340, spacing=1.1)

    rounded_rect(draw, (100, 912, 1500, 942), fill=RED_SOFT, outline=RED, width=2)
    draw.text((120, 916), takeaway, font=fonts.bold(22), fill=RED)
    draw_footer(draw, fonts)
    save_png(img, out_path)


def build_all_text(data: dict) -> list[str]:
    spy = data["asset_results"]["SPY"]
    tw = data["asset_results"]["0050.TW"]
    spy_primary = spy["signal_comparisons"]["squeeze_reaches_10d"]["20"]
    tw_primary = tw["signal_comparisons"]["squeeze_reaches_10d"]["20"]
    spy_boot = spy["bootstrap_primary_vol_diff"]
    tw_boot = tw["bootstrap_primary_vol_diff"]
    spy_break = spy["episode_end_comparisons"]["episode_end_after_10d"]["breakout_day"]
    tw_break = tw["episode_end_comparisons"]["episode_end_after_10d"]["breakout_day"]
    spy_end20 = spy["episode_end_comparisons"]["episode_end_after_10d"]["forward"]["20"]
    tw_end20 = tw["episode_end_comparisons"]["episode_end_after_10d"]["forward"]["20"]
    return [
        "VolPred",
        "資料來源：experiment K1632；數字綁定 experiments/k1632/k1632_results.json",
        "盤整越久懶人包",
        "先分清楚：結束日有動作，不等於未來 20 天更震",
        "核心問題：盤整越久，真的代表後面會噴更兇嗎？",
        "盤整結束那天",
        "描述的是當天已經發生的單日動作；收盤後才完整知道它結束了。",
        "確認盤整後",
        "這才是事前可以問的問題：從 t+1 開始，未來 20 天會不會更震？",
        "白話拆解：要分清楚「盤整結束那天比較有動作」與「確認盤整後，未來 20 天更震」是兩件事。",
        "一句話：迷思只有一半成立；結束日動作變大，但後續 20 天沒有更震。",
        "方法怎麼做？",
        "門檻只看過去，訊號收盤後才成立，結果從 t+1 開始",
        "資料：SPY 與 0050.TW 調整收盤價。",
        (
            f"SPY：{spy['date_start']} 至 {spy['date_end']}，共 N={fmt_int(spy['n_price_obs'])} 筆；"
            f"0050.TW：{tw['date_start']} 至 {tw['date_end']}，共 N={fmt_int(tw['n_price_obs'])} 筆。"
        ),
        "20 日觀察窗",
        "計算年化波動與收盤價區間",
        "252 日歷史門檻",
        "各自低於過去一年 20% 分位",
        "連續達 10 天",
        "收盤後才知道訊號成立",
        "從 t+1 起算",
        "看未來 20 天波動與絕對報酬",
        "低波動盤整定義：20 日年化波動與 20 日價格區間，同時低於自己過去 252 日的 20% 分位門檻。",
        "時間順序：門檻只用 t-1 以前資料；訊號在 t 日收盤後才知道；後續結果從 t+1 開始算，避免偷看同日報酬。",
        "主檢定：盤整連續達 10 天後，看未來 20 天年化波動與絕對報酬。",
        "結果：迷思只有一半成立",
        "結束日動作變大；但確認盤整後，未來 20 天沒有更震",
        (
            "盤整連續達 10 天後，未來 20 日年化波動："
            f"SPY {pct(spy_primary['mean_vol_event_ann'])} vs 其他日 {pct(spy_primary['mean_vol_other_ann'])}，"
            f"差 {pct(spy_primary['mean_vol_diff_event_minus_other_ann'], signed=True)}；"
            f"0050.TW {pct(tw_primary['mean_vol_event_ann'])} vs {pct(tw_primary['mean_vol_other_ann'])}，"
            f"差 {pct(tw_primary['mean_vol_diff_event_minus_other_ann'], signed=True)}。"
        ),
        "SPY",
        "0050.TW",
        "盤整達 10 天後，未來 20 日年化波動",
        "盤整後",
        "其他日",
        (
            "SPY 差距 bootstrap 95% 區間 "
            f"{pct(spy_boot['ci95'][0], signed=True)} 到 {pct(spy_boot['ci95'][1], signed=True)}；"
            f"0050.TW 為 {pct(tw_boot['ci95'][0], signed=True)} 到 {pct(tw_boot['ci95'][1], signed=True)}。"
        ),
        (
            "盤整結束當天絕對報酬較大："
            f"SPY {pct(spy_break['mean_breakout_day_abs_ret_event'])} vs {pct(spy_break['mean_breakout_day_abs_ret_other'])}；"
            f"0050.TW {pct(tw_break['mean_breakout_day_abs_ret_event'])} vs {pct(tw_break['mean_breakout_day_abs_ret_other'])}。"
        ),
        (
            "但盤整結束後 20 日年化波動仍較低："
            f"SPY {pct(spy_end20['mean_vol_event_ann'])} vs {pct(spy_end20['mean_vol_other_ann'])}；"
            f"0050.TW {pct(tw_end20['mean_vol_event_ann'])} vs {pct(tw_end20['mean_vol_other_ann'])}。"
        ),
        "一句話：可以把盤整當 watchlist 條件，但不能把它當成「後面必大噴」的證據。",
    ]


def save_png(img: Image.Image, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", dpi=DPI)


def validate_png(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= 0:
        raise RuntimeError(f"PNG missing or empty: {path}")
    with Image.open(path) as img:
        if img.size != (WIDTH, HEIGHT):
            raise RuntimeError(f"Unexpected image size for {path}: {img.size}")
        diff = ImageChops.difference(img.convert("RGB"), Image.new("RGB", img.size, WHITE))
        if diff.getbbox() is None:
            raise RuntimeError(f"PNG appears blank: {path}")


def main() -> None:
    data = load_json(RESULTS_PATH)
    if data.get("experiment_id") != "k1632":
        raise RuntimeError("Expected experiment_id k1632")
    if not README_PATH.exists():
        raise RuntimeError(f"Missing evidence README: {README_PATH}")
    if not ARTICLE_PATH.exists():
        raise RuntimeError(f"Missing evidence article markdown: {ARTICLE_PATH}")

    fonts = select_fonts(build_all_text(data))
    outputs = [
        ("1_question.png", render_panel_1),
        ("2_method.png", render_panel_2),
        ("3_results.png", render_panel_3),
    ]
    for filename, renderer in outputs:
        renderer(data, fonts, OUT_DIR / filename)
        validate_png(OUT_DIR / filename)

    for filename, _ in outputs:
        path = OUT_DIR / filename
        print(f"{path} {path.stat().st_size} bytes")
    print(f"font={fonts.choice.name} regular={fonts.choice.regular_path} bold={fonts.choice.bold_path}")


if __name__ == "__main__":
    main()
