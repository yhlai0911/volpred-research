#!/usr/bin/env python3
"""Render K1640 lazy-pack panels from the experiment result JSON.

The displayed statistics are bound to experiments/k1640/k1640_results.json.
This renderer uses local Pillow drawing only; it does not call any image model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTCollection, TTFont


ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = ROOT / "experiments/k1640/k1640_results.json"
OUT_DIR = Path(__file__).resolve().parent

WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)
MARGIN = 80
HEADER_H = 190
FOOTER_Y = 930

NAVY = "#122235"
NAVY_2 = "#1B3148"
INK = "#17202A"
MUTED = "#566371"
FAINT = "#7F8B99"
BORDER = "#D9E0E8"
PAPER = "#FFFFFF"
CARD = "#FFFFFF"
SOFT = "#F4F7FA"
BLUE = "#2563A8"
BLUE_SOFT = "#E6F0FA"
TEAL = "#127C7E"
TEAL_SOFT = "#E2F3F3"
GREEN = "#247A4A"
GREEN_SOFT = "#E0F0E7"
AMBER = "#A96713"
AMBER_SOFT = "#F6EAD5"
RED = "#B93A36"
RED_SOFT = "#F6DEDC"

FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
    "/Library/Fonts/Noto Sans CJK TC Regular.otf",
]

FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/NotoSansCJKtc-Bold.otf",
    "/Library/Fonts/Noto Sans CJK TC Bold.otf",
]


@dataclass(frozen=True)
class FontFace:
    path: Path
    index: int

    def load(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.path), size=size, index=self.index)


@dataclass(frozen=True)
class FontBook:
    regular_face: FontFace
    bold_face: FontFace

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return self.regular_face.load(size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return self.bold_face.load(size)


def load_results() -> dict[str, Any]:
    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("experiment_id") != "K1640":
        raise ValueError(f"Unexpected experiment_id: {data.get('experiment_id')}")
    return data


def pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def signed_pct(value: float, digits: int = 2) -> str:
    return f"{value * 100:+.{digits}f}%"


def years_from_period(period: str) -> str:
    start, end = period.split(" .. ")
    return f"{start[:4]}-{end[:4]}"


def period_full(period: str) -> str:
    return period.replace(" .. ", " 至 ")


def fmt_int(value: int) -> str:
    return f"{value:,}"


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str = INK,
    max_width: int | None = None,
    line_spacing: int = 8,
) -> int:
    if max_width is None:
        draw.text(xy, text, font=font, fill=fill)
        bbox = draw.textbbox(xy, text, font=font)
        return bbox[3] - bbox[1]

    lines = wrap_text(draw, text, font, max_width)
    x, y = xy
    line_height = font.getbbox("漢")[3] - font.getbbox("漢")[1] + line_spacing
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return max(0, y - xy[1] - line_spacing)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if ch == "\n":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append("\n")
        elif ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ord(ch) < 128 and (ch.isalnum() or ch in ".%()+-/"):
            buf += ch
        else:
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
    if buf:
        tokens.append(buf)
    return tokens


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for token in tokenize(text):
        if token == "\n":
            lines.append(line.rstrip())
            line = ""
            continue
        candidate = f"{line}{token}"
        width = draw.textlength(candidate, font=font)
        if line and width > max_width:
            lines.append(line.rstrip())
            line = token.lstrip()
        else:
            line = candidate
    if line:
        lines.append(line.rstrip())
    return lines


def rounded_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    border: str = BORDER,
    fill: str = CARD,
    accent: str | None = None,
) -> None:
    draw.rounded_rectangle((x + 4, y + 6, x + w + 4, y + h + 6), radius=8, fill="#EDF1F5")
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=fill, outline=border, width=2)
    if accent:
        draw.rounded_rectangle((x, y, x + 10, y + h), radius=8, fill=accent)
        draw.rectangle((x + 6, y, x + 12, y + h), fill=accent)


def draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    title: str,
    subtitle: str,
    kicker: str = "K1640 懶人包",
) -> None:
    draw.rectangle((0, 0, WIDTH, HEADER_H), fill=NAVY)
    draw.rectangle((0, HEADER_H - 8, WIDTH, HEADER_H), fill=TEAL)
    draw_text(draw, (MARGIN, 34), kicker, fonts.bold(25), fill="#A9D7D8")
    draw_text(draw, (MARGIN, 72), title, fonts.bold(48), fill="#FFFFFF", max_width=1340, line_spacing=6)
    draw_text(draw, (MARGIN, 145), subtitle, fonts.regular(27), fill="#D7E1EA", max_width=1340)


def draw_footer(draw: ImageDraw.ImageDraw, fonts: FontBook, experiment_id: str, extra: str | None = None) -> None:
    draw.line((MARGIN, FOOTER_Y - 18, WIDTH - MARGIN, FOOTER_Y - 18), fill=BORDER, width=2)
    source = f"資料來源：experiment {experiment_id}；yfinance ^VIX 收盤 + SPY 調整後收盤"
    if extra:
        source = f"{source}｜{extra}"
    draw_text(draw, (MARGIN, FOOTER_Y), source, fonts.regular(23), fill=MUTED, max_width=1220)


def draw_metric_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    x: int,
    y: int,
    w: int,
    h: int,
    label: str,
    value: str,
    note: str,
    accent: str,
    fill: str = CARD,
) -> None:
    rounded_card(draw, x, y, w, h, fill=fill, accent=accent)
    draw_text(draw, (x + 30, y + 24), label, fonts.bold(27), fill=MUTED, max_width=w - 60)
    draw_text(draw, (x + 30, y + 70), value, fonts.bold(45), fill=INK, max_width=w - 60)
    draw_text(draw, (x + 30, y + h - 45), note, fonts.regular(22), fill=FAINT, max_width=w - 60)


def draw_compact_stat_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    x: int,
    y: int,
    w: int,
    h: int,
    label: str,
    value: str,
    accent: str,
    fill: str = CARD,
    value_size: int = 38,
) -> None:
    rounded_card(draw, x, y, w, h, fill=fill, accent=accent)
    draw_text(draw, (x + 30, y + 22), label, fonts.bold(26), fill=MUTED, max_width=w - 60)
    draw_text(draw, (x + 30, y + 66), value, fonts.bold(value_size), fill=INK, max_width=w - 60)


def draw_h60_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    x: int,
    y: int,
    w: int,
    h: int,
    label: str,
    value: str,
    note: str,
    accent: str,
    fill: str,
) -> None:
    rounded_card(draw, x, y, w, h, fill=fill, accent=accent)
    draw_text(draw, (x + 30, y + 24), label, fonts.bold(27), fill=MUTED, max_width=w - 60)
    draw_text(draw, (x + 30, y + 70), value, fonts.bold(34), fill=INK, max_width=w - 60)
    draw_text(draw, (x + 30, y + 122), note, fonts.regular(21), fill=FAINT, max_width=w - 60)


def draw_section_label(draw: ImageDraw.ImageDraw, fonts: FontBook, x: int, y: int, text: str, color: str) -> None:
    draw.rounded_rectangle((x, y, x + 14, y + 34), radius=4, fill=color)
    draw_text(draw, (x + 26, y - 2), text, fonts.bold(32), fill=INK)


def render_panel_1(results: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    exp_id = results["experiment_id"]
    period = results["data"]["period"]
    years = years_from_period(period)
    n_days = int(results["data"]["n_trading_days"])
    event30 = int(results["event_counts"]["30"])
    event40 = int(results["event_counts"]["40"])
    cooldown = int(results["data"]["cooldown_trading_days"])

    draw_header(
        draw,
        fonts,
        "VIX 飆到 30/40 才進場，真的比隨機買更好嗎？",
        "恐慌抄底迷思，用真實交易日檢驗",
    )

    x, y, w, h = MARGIN, 250, 610, 400
    rounded_card(draw, x, y, w, h, fill=SOFT, accent=BLUE)
    draw_section_label(draw, fonts, x + 32, y + 28, "核心問題", BLUE)
    problem = (
        "每次美股大跌、VIX 衝上 30，社群都喊「恐慌是機會、等更慘再進場」。"
        "K1640 用 yfinance 的 ^VIX 收盤與 SPY 調整後收盤，檢驗這句話是否真的比隨機買更好。"
    )
    draw_text(draw, (x + 32, y + 88), problem, fonts.regular(31), fill=INK, max_width=w - 64, line_spacing=10)

    draw.line((x + 55, y + 318, x + w - 55, y + 318), fill=BORDER, width=3)
    draw.line((x + 145, y + 372, x + 320, y + 285), fill=TEAL, width=7)
    draw.line((x + 320, y + 285, x + 485, y + 255), fill=TEAL, width=7)
    draw.ellipse((x + 302, y + 267, x + 338, y + 303), fill=TEAL)
    draw_text(draw, (x + 355, y + 265), "首次由下往上穿越門檻", fonts.bold(24), fill=TEAL, max_width=210)

    card_w, card_h = 390, 172
    right_x = 760
    draw_metric_card(draw, fonts, right_x, 250, card_w, card_h, "研究期間", years, period_full(period), BLUE, BLUE_SOFT)
    draw_metric_card(draw, fonts, right_x + 430, 250, card_w, card_h, "樣本", f"{fmt_int(n_days)} 交易日", "共同可用交易日", TEAL, TEAL_SOFT)
    draw_metric_card(draw, fonts, right_x, 454, card_w, card_h, "恐慌門檻", f"VIX>30：{event30} 次", f"{cooldown} 交易日內去重複", GREEN, GREEN_SOFT)
    draw_metric_card(draw, fonts, right_x + 430, 454, card_w, card_h, "極端恐慌", f"VIX>40：{event40} 次", "樣本更少，推論更脆弱", AMBER, AMBER_SOFT)

    band_x, band_y, band_w, band_h = MARGIN, 715, WIDTH - 2 * MARGIN, 145
    rounded_card(draw, band_x, band_y, band_w, band_h, fill=CARD, accent=NAVY_2)
    draw_text(draw, (band_x + 36, band_y + 26), "事件定義", fonts.bold(32), fill=INK)
    definition = f"VIX 首次由下往上穿越門檻；同一波恐慌 {cooldown} 交易日內只算一次，避免同一場崩盤重複灌水。"
    draw_text(draw, (band_x + 230, band_y + 30), definition, fonts.regular(30), fill=INK, max_width=1130)

    draw_footer(draw, fonts, exp_id, "period / n_trading_days / event_counts / cooldown_trading_days")
    out = OUT_DIR / "問題設定：恐慌抄底迷思.png"
    img.save(out, dpi=DPI)
    return out


def render_panel_2(results: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    exp_id = results["experiment_id"]
    win_rates = {int(k): float(v) for k, v in results["baseline_win_rates"].items()}

    draw_header(
        draw,
        fonts,
        "關鍵陷阱：隨機進場本來就贏面高",
        "SPY 長期上漲，讓「隨便挑一天買」自帶順風",
    )

    x, y, w, h = MARGIN, 250, 570, 430
    rounded_card(draw, x, y, w, h, fill=SOFT, accent=AMBER)
    draw_section_label(draw, fonts, x + 34, y + 30, "方法重點", AMBER)
    body = (
        "任何「進場時機」比較都要先看隨機基準。"
        "如果隨機買 SPY 抱著不動本來就常常贏，恐慌訊號必須扣掉這股長期上漲順風，才看得出訊號本身值多少。"
    )
    draw_text(draw, (x + 34, y + 96), body, fonts.regular(32), fill=INK, max_width=w - 68, line_spacing=10)
    draw.rounded_rectangle((x + 34, y + 330, x + w - 34, y + 380), radius=8, fill=AMBER_SOFT)
    draw_text(draw, (x + 58, y + 340), "比較對象：每個可用交易日都當作一次隨機進場", fonts.bold(25), fill=AMBER, max_width=w - 116)

    chart_x, chart_y, chart_w, chart_h = 710, 255, 810, 440
    rounded_card(draw, chart_x, chart_y, chart_w, chart_h, fill=CARD, accent=TEAL)
    draw_text(draw, (chart_x + 36, chart_y + 28), "隨機進場勝率基準", fonts.bold(34), fill=INK)
    draw_text(draw, (chart_x + 36, chart_y + 74), "同一 SPY 價格序列、各持有天數的 unconditional baseline", fonts.regular(23), fill=MUTED)

    max_rate = 0.80
    bar_x = chart_x + 235
    bar_max_w = 430
    row_y = chart_y + 140
    for idx, horizon in enumerate([5, 10, 20, 60]):
        rate = win_rates[horizon]
        this_y = row_y + idx * 70
        label = f"H{horizon}：{pct(rate, 1)}"
        draw_text(draw, (chart_x + 42, this_y + 4), label, fonts.bold(31), fill=INK)
        draw.rounded_rectangle((bar_x, this_y, bar_x + bar_max_w, this_y + 34), radius=8, fill="#EEF2F6")
        bar_w = int(bar_max_w * rate / max_rate)
        color = [BLUE, TEAL, GREEN, AMBER][idx]
        draw.rounded_rectangle((bar_x, this_y, bar_x + bar_w, this_y + 34), radius=8, fill=color)
        draw_text(draw, (bar_x + bar_w + 18, this_y - 1), pct(rate, 1), fonts.bold(29), fill=color)

    card_y = 748
    small_w = 335
    gap = 28
    for idx, horizon in enumerate([5, 10, 20, 60]):
        rate = win_rates[horizon]
        cx = MARGIN + idx * (small_w + gap)
        draw_compact_stat_card(
            draw,
            fonts,
            cx,
            card_y,
            small_w,
            125,
            f"抱 {horizon} 天",
            f"H{horizon}：{pct(rate, 1)}",
            [BLUE, TEAL, GREEN, AMBER][idx],
            CARD,
        )

    draw_footer(draw, fonts, exp_id, "baseline_win_rates")
    out = OUT_DIR / "關鍵陷阱：隨機進場本來就贏面高.png"
    img.save(out, dpi=DPI)
    return out


def render_panel_3(results: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    exp_id = results["experiment_id"]
    lag0 = results["multiple_testing_lag0"]
    lag1 = results["multiple_testing_lag1"]
    h60_30 = float(results["h60_pattern"]["30"]["excess_mean"])
    h60_40 = float(results["h60_pattern"]["40"]["excess_mean"])
    event40 = int(results["event_counts"]["40"])
    fdr10_count = len(lag0["bh_fdr_10pct_survivors"])

    draw_header(
        draw,
        fonts,
        "結論：半真：增量在「慢慢等 60 天」",
        "方向性增量存在，但嚴格校正下證據脆弱",
    )

    verdict_x, verdict_y, verdict_w, verdict_h = MARGIN, 250, 500, 365
    rounded_card(draw, verdict_x, verdict_y, verdict_w, verdict_h, fill=SOFT, accent=TEAL)
    draw_text(draw, (verdict_x + 38, verdict_y + 34), "半真", fonts.bold(78), fill=TEAL)
    summary = f"{lag0['n_cells']} 個情境，{lag0['n_positive_excess']} 個超額報酬為正；但多重檢驗後證據沒有強到可以下保證式結論。"
    draw_text(draw, (verdict_x + 42, verdict_y + 130), summary, fonts.regular(30), fill=INK, max_width=verdict_w - 84, line_spacing=9)
    draw.rounded_rectangle((verdict_x + 42, verdict_y + 278, verdict_x + verdict_w - 42, verdict_y + 330), radius=8, fill=RED_SOFT)
    draw_text(draw, (verdict_x + 66, verdict_y + 288), "FDR 5% 無 survivor", fonts.bold(31), fill=RED)

    card_w, card_h = 425, 165
    draw_h60_card(
        draw,
        fonts,
        625,
        250,
        card_w,
        card_h,
        "最耐久型態",
        f"VIX>30 H60 {signed_pct(h60_30, 2)}",
        "超額平均報酬 vs 隨機進場",
        GREEN,
        GREEN_SOFT,
    )
    draw_h60_card(
        draw,
        fonts,
        1095,
        250,
        card_w,
        card_h,
        "小樣本高增量",
        f"VIX>40 H60 {signed_pct(h60_40, 2)}",
        "超額平均報酬 vs 隨機進場",
        AMBER,
        AMBER_SOFT,
    )

    fdr_x, fdr_y, fdr_w, fdr_h = 625, 455, 895, 160
    rounded_card(draw, fdr_x, fdr_y, fdr_w, fdr_h, fill=CARD, accent=BLUE)
    draw_text(draw, (fdr_x + 36, fdr_y + 28), f"FDR 10% 才留住 {fdr10_count} 組", fonts.bold(35), fill=BLUE)
    survivor_text = "VIX>30/H5、VIX>30/H60、VIX>40/H60；嚴格 BH-FDR 5% 則全部落榜。"
    draw_text(draw, (fdr_x + 36, fdr_y + 82), survivor_text, fonts.regular(28), fill=INK, max_width=fdr_w - 72)

    robust_x, robust_y, robust_w, robust_h = MARGIN, 675, 680, 175
    rounded_card(draw, robust_x, robust_y, robust_w, robust_h, fill=CARD, accent=NAVY_2)
    draw_text(draw, (robust_x + 36, robust_y + 28), "穩健檢查更弱", fonts.bold(34), fill=INK)
    robust_text = f"用 signal.shift(1) 延一日後，{lag1['n_cells']} 個情境中 FDR 10% 也無 survivor。"
    draw_text(draw, (robust_x + 36, robust_y + 82), robust_text, fonts.regular(28), fill=INK, max_width=robust_w - 72)

    limit_x, limit_y, limit_w, limit_h = 800, 675, 720, 175
    rounded_card(draw, limit_x, limit_y, limit_w, limit_h, fill=CARD, accent=RED)
    draw_text(draw, (limit_x + 36, limit_y + 28), "解讀邊界", fonts.bold(34), fill=INK)
    limit_text = f"證據支持慢速 60 日修復勝過立即反彈；VIX>40 僅 {event40} 次，單一格估計小樣本脆弱。"
    draw_text(draw, (limit_x + 36, limit_y + 82), limit_text, fonts.regular(28), fill=INK, max_width=limit_w - 72)

    draw.rounded_rectangle((MARGIN, 874, MARGIN + 250, 914), radius=8, fill=RED_SOFT)
    draw_text(draw, (MARGIN + 24, 880), "非投資建議", fonts.bold(25), fill=RED)

    draw_footer(draw, fonts, exp_id, "multiple_testing_lag0 / multiple_testing_lag1 / h60_pattern")
    out = OUT_DIR / "結論：半真 —— 增量在『慢慢等 60 天』.png"
    img.save(out, dpi=DPI)
    return out


def text_codepoints(text: str) -> set[int]:
    return {ord(ch) for ch in text if not ch.isspace()}


def cmap_for_font(path: Path, index: int) -> set[int]:
    if path.suffix.lower() in {".ttc", ".otc"}:
        font = TTCollection(str(path)).fonts[index]
    else:
        font = TTFont(str(path))
    cmap: set[int] = set()
    for table in font["cmap"].tables:
        cmap.update(table.cmap.keys())
    return cmap


def face_count(path: Path) -> int:
    if path.suffix.lower() in {".ttc", ".otc"}:
        return len(TTCollection(str(path)).fonts)
    return 1


def choose_face(candidates: list[str], required_text: str, label: str) -> FontFace:
    required = text_codepoints(required_text)
    for raw in candidates:
        path = Path(raw)
        if not path.exists():
            continue
        for idx in range(face_count(path)):
            cmap = cmap_for_font(path, idx)
            missing = sorted(required - cmap)
            if not missing:
                return FontFace(path, idx)
    raise RuntimeError(f"No {label} CJK font covers all panel text.")


def all_panel_text(results: dict[str, Any]) -> str:
    period = results["data"]["period"]
    win_rates = {int(k): float(v) for k, v in results["baseline_win_rates"].items()}
    h60_30 = float(results["h60_pattern"]["30"]["excess_mean"])
    h60_40 = float(results["h60_pattern"]["40"]["excess_mean"])
    bits = [
        "K1640 懶人包",
        "VIX 飆到 30/40 才進場，真的比隨機買更好嗎？",
        "恐慌抄底迷思，用真實交易日檢驗",
        "核心問題 每次美股大跌、VIX 衝上 30，社群都喊「恐慌是機會、等更慘再進場」。",
        "K1640 用 yfinance 的 ^VIX 收盤與 SPY 調整後收盤，檢驗這句話是否真的比隨機買更好。",
        "首次由下往上穿越門檻",
        f"研究期間 {years_from_period(period)} {period_full(period)}",
        f"樣本 {fmt_int(int(results['data']['n_trading_days']))} 交易日 共同可用交易日",
        f"恐慌門檻 VIX>30：{int(results['event_counts']['30'])} 次 {int(results['data']['cooldown_trading_days'])} 交易日內去重複",
        f"極端恐慌 VIX>40：{int(results['event_counts']['40'])} 次 樣本更少，推論更脆弱",
        "事件定義 避免同一場崩盤重複灌水",
        "關鍵陷阱：隨機進場本來就贏面高",
        "SPY 長期上漲，讓「隨便挑一天買」自帶順風",
        "方法重點 任何「進場時機」比較都要先看隨機基準。",
        "比較對象：每個可用交易日都當作一次隨機進場",
        "隨機進場勝率基準 同一 SPY 價格序列、各持有天數的 unconditional baseline",
        *[f"H{h}：{pct(win_rates[h], 1)} 抱 {h} 天 隨機進場勝率" for h in [5, 10, 20, 60]],
        "結論：半真：增量在「慢慢等 60 天」",
        "方向性增量存在，但嚴格校正下證據脆弱",
        "半真 多重檢驗後證據沒有強到可以下保證式結論",
        "FDR 5% 無 survivor",
        f"VIX>30 H60 {signed_pct(h60_30, 2)}",
        f"VIX>40 H60 {signed_pct(h60_40, 2)}",
        "超額平均報酬 vs 隨機進場",
        "FDR 10% 才留住 3 組",
        "VIX>30/H5、VIX>30/H60、VIX>40/H60；嚴格 BH-FDR 5% 則全部落榜。",
        "穩健檢查更弱 用 signal.shift(1) 延一日後，FDR 10% 也無 survivor。",
        "解讀邊界 證據支持慢速 60 日修復勝過立即反彈；單一格估計小樣本脆弱。",
        "非投資建議",
        "資料來源：experiment K1640；yfinance ^VIX 收盤 + SPY 調整後收盤",
        "period / n_trading_days / event_counts / cooldown_trading_days baseline_win_rates multiple_testing_lag0 multiple_testing_lag1 h60_pattern",
    ]
    return "\n".join(bits)


def load_fonts(required_text: str) -> FontBook:
    regular = choose_face(FONT_CANDIDATES_REGULAR, required_text, "regular")
    bold = choose_face(FONT_CANDIDATES_BOLD, required_text, "bold")
    return FontBook(regular_face=regular, bold_face=bold)


def main() -> None:
    results = load_results()
    fonts = load_fonts(all_panel_text(results))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = [
        render_panel_1(results, fonts),
        render_panel_2(results, fonts),
        render_panel_3(results, fonts),
    ]

    for path in outputs:
        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError(f"Render failed or empty output: {path}")

    print("Rendered panels:")
    for path in outputs:
        print(path)
    print(f"Regular font: {fonts.regular_face.path} index={fonts.regular_face.index}")
    print(f"Bold font: {fonts.bold_face.path} index={fonts.bold_face.index}")


if __name__ == "__main__":
    main()
