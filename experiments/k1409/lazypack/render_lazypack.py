#!/usr/bin/env python3
"""Render the K1409 Traditional-Chinese infographic set from results JSON.

This renderer is deliberately data-bound: every displayed statistic is read
from ``k1409_results.json`` and formatted at render time.  It uses Pillow only
and never calls an image-generation service.

The evidence package contains one known internal inconsistency.  Structured
calendar fields say 12/12 months are covered, while ``verdict.summary`` says
approximately 11/12 months with April as a gap.  The article panel brief
explicitly requires the latter wording, so the concept panel extracts its
calendar statement from ``verdict.summary`` rather than silently reconciling
the two claims.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from fontTools.ttLib import TTCollection, TTFont
from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = 150

WHITE = "#FFFFFF"
NAVY = "#102A43"
NAVY_2 = "#173F5F"
INK = "#172B3A"
MUTED = "#5D6B78"
FAINT = "#7F8C99"
BORDER = "#DCE4EA"
SURFACE = "#F4F7F9"
TEAL = "#147D7E"
TEAL_SOFT = "#E2F2F0"
BLUE = "#2D6A9F"
BLUE_SOFT = "#E7F0F8"
AMBER = "#B76E12"
AMBER_SOFT = "#F9EEDB"
RED = "#C94A45"
RED_SOFT = "#F9E7E5"
GREEN = "#2C7A57"
GREEN_SOFT = "#E3F1E9"

SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_EVIDENCE = SCRIPT_PATH.parents[1] / "k1409_results.json"
DEFAULT_OUT_DIR = SCRIPT_PATH.parent


FONT_PAIRS = [
    (
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    ),
    (
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ),
    (
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ),
]


@dataclass(frozen=True)
class FontBook:
    regular_path: Path
    bold_path: Path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size, index=0)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size, index=0)


@dataclass(frozen=True)
class BoundText:
    ticker_line: str
    principal_total: str
    principal_by_ticker: dict[str, str]
    target: str
    calendar: str
    calendar_total: int
    calendar_gap: int
    simulations: str
    horizon: str
    avg_hit: str
    avg_hit_raw: str
    paid_hit: str
    paid_hit_raw: str
    yield_compare: str
    median_dividend: str
    p5_dividend: str
    p95_dividend: str
    source: str


class Poster:
    """Small drawing wrapper that records all rendered text for QA."""

    def __init__(self, fonts: FontBook) -> None:
        self.fonts = fonts
        self.image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.text_log: list[str] = []

    def text(
        self,
        xy: tuple[int, int],
        value: str,
        font: ImageFont.FreeTypeFont,
        fill: str = INK,
        *,
        anchor: str | None = None,
        align: str = "left",
        spacing: int = 6,
    ) -> None:
        self.text_log.append(value)
        self.draw.text(
            xy,
            value,
            font=font,
            fill=fill,
            anchor=anchor,
            align=align,
            spacing=spacing,
        )

    def rounded(
        self,
        box: tuple[int, int, int, int],
        *,
        radius: int = 24,
        fill: str = WHITE,
        outline: str | None = BORDER,
        width: int = 2,
    ) -> None:
        self.draw.rounded_rectangle(
            box, radius=radius, fill=fill, outline=outline, width=width
        )

    def assert_text_fits(
        self,
        value: str,
        font: ImageFont.FreeTypeFont,
        *,
        left: int,
        right: int,
        context: str,
    ) -> None:
        bbox = self.draw.textbbox((left, 0), value, font=font)
        if bbox[2] > right:
            raise ValueError(
                f"Text overflow in {context}: right={bbox[2]} exceeds {right}: {value!r}"
            )


def deep_get(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            raise KeyError(f"Missing evidence field: {path}")
        current = current[component]
    return current


def number(data: dict[str, Any], path: str) -> float:
    value = deep_get(data, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}, got {value!r}")
    return float(value)


def load_evidence(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("experiment_id") != "k1409":
        raise ValueError(f"Expected experiment_id='k1409', got {data.get('experiment_id')!r}")
    return data


def parse_calendar_summary(summary: str) -> tuple[str, int, int]:
    """Extract the article-requested calendar wording from verdict.summary."""

    match = re.search(
        r"(?P<total>\d+) 個日曆月中約 (?P<covered>\d+) 個有配息（(?P<gap>\d+) 月空窗）",
        summary,
    )
    if match is None:
        raise ValueError(
            "verdict.summary no longer contains the requested 11/12-April statement"
        )
    total = int(match.group("total"))
    gap = int(match.group("gap"))
    label = (
        f"{match.group('covered')}/{match.group('total')} 月有配息"
        f"（{match.group('gap')} 月空窗）"
    )
    return label, total, gap


def bind_text(data: dict[str, Any]) -> BoundText:
    tickers = deep_get(data, "config.tickers")
    if not isinstance(tickers, list) or len(tickers) != 3:
        raise ValueError("K1409 config.tickers must contain exactly three ETFs")
    ticker_codes = [str(ticker).split(".")[0] for ticker in tickers]

    total = number(data, "results.principal_total")
    target = number(data, "config.monthly_target_ntd")
    per_ticker = deep_get(data, "results.principal_by_ticker")
    if not isinstance(per_ticker, dict):
        raise TypeError("results.principal_by_ticker must be a mapping")

    principal_labels = {
        code: f"約 {float(per_ticker[ticker]) / 10_000:.1f} 萬元"
        for code, ticker in zip(ticker_codes, tickers, strict=True)
    }

    avg_hit_value = number(data, "results.monthly_div_avg_stats.P_avg_ge_10000")
    paid_hit_value = number(data, "results.monthly_div_stats.paid_months_P_ge_10000")
    implied_yield = number(data, "results.yield_stats.implied_yield_from_chart")
    realized_yield = number(data, "results.yield_stats.realized_yield_median")
    median_dividend = number(data, "results.monthly_div_stats.paid_months_median")
    p5_dividend = number(data, "results.monthly_div_stats.paid_months_p5")
    p95_dividend = number(data, "results.monthly_div_stats.paid_months_p95")

    experiment = str(deep_get(data, "experiment_id")).upper()
    summary = str(deep_get(data, "verdict.summary"))
    calendar_label, calendar_total, calendar_gap = parse_calendar_summary(summary)

    bound = BoundText(
        ticker_line=" / ".join(ticker_codes),
        principal_total=f"本金 {total / 10_000:.1f} 萬元",
        principal_by_ticker=principal_labels,
        target=f"目標：月領 {target / 10_000:.0f} 萬",
        calendar=calendar_label,
        calendar_total=calendar_total,
        calendar_gap=calendar_gap,
        simulations=f"{number(data, 'config.n_sim'):.0f} 次蒙地卡羅模擬",
        horizon=f"{number(data, 'config.horizon_months'):.0f} 個月本金淨值路徑",
        avg_hit=f"平均月達標率 {avg_hit_value * 100:.1f}%",
        avg_hit_raw=f"原始機率 {avg_hit_value:.4f}",
        paid_hit=f"有配息月 P(≥1萬)={paid_hit_value * 100:.1f}%",
        paid_hit_raw=f"原始機率 {paid_hit_value:.4f}",
        yield_compare=(
            f"隱含殖利率 {implied_yield * 100:.1f}% vs "
            f"實現 {realized_yield * 100:.1f}%"
        ),
        median_dividend=f"月配息中位數 {median_dividend:,.0f} 元",
        p5_dividend=f"P5 約 {p5_dividend:,.0f} 元",
        p95_dividend=f"P95 約 {p95_dividend:,.0f} 元",
        source=f"資料來源：experiment {experiment}",
    )

    # Fail loudly if evidence or rounding changes away from the commissioned copy.
    expected = {
        "ticker_line": "0056 / 00878 / 00919",
        "principal_total": "本金 160.5 萬元",
        "target": "目標：月領 1 萬",
        "calendar": "11/12 月有配息（4 月空窗）",
        "simulations": "5000 次蒙地卡羅模擬",
        "horizon": "36 個月本金淨值路徑",
        "avg_hit": "平均月達標率 2.7%",
        "paid_hit": "有配息月 P(≥1萬)=33.9%",
        "yield_compare": "隱含殖利率 9.7% vs 實現 7.0%",
        "median_dividend": "月配息中位數 9,216 元",
    }
    for attribute, expected_value in expected.items():
        actual = getattr(bound, attribute)
        if actual != expected_value:
            raise ValueError(
                f"Evidence formatting drift for {attribute}: {actual!r} != {expected_value!r}"
            )
    return bound


def font_cmap(path: Path) -> set[int]:
    if path.suffix.lower() in {".ttc", ".otc"}:
        collection = TTCollection(str(path), lazy=False)
        font = collection.fonts[0]
        cmap = set((font["cmap"].getBestCmap() or {}).keys())
        collection.close()
        return cmap
    font = TTFont(str(path), lazy=False)
    cmap = set((font["cmap"].getBestCmap() or {}).keys())
    font.close()
    return cmap


def missing_glyphs(path: Path, texts: Iterable[str]) -> list[str]:
    cmap = font_cmap(path)
    characters = {
        character
        for text in texts
        for character in text
        if not character.isspace() and character not in {"\n", "\r", "\t"}
    }
    return sorted(character for character in characters if ord(character) not in cmap)


def choose_fonts(probe_texts: Iterable[str]) -> FontBook:
    probe_texts = list(probe_texts)
    diagnostics: list[str] = []
    for regular, bold in FONT_PAIRS:
        if not regular.exists() or not bold.exists():
            diagnostics.append(f"missing files: {regular}, {bold}")
            continue
        regular_missing = missing_glyphs(regular, probe_texts)
        bold_missing = missing_glyphs(bold, probe_texts)
        if not regular_missing and not bold_missing:
            return FontBook(regular_path=regular, bold_path=bold)
        diagnostics.append(
            f"{regular.name}/{bold.name}: missing {regular_missing or bold_missing}"
        )
    raise RuntimeError("No tofu-safe CJK font pair found: " + "; ".join(diagnostics))


def draw_header(poster: Poster, kicker: str, title: str, subtitle: str) -> None:
    poster.draw.rectangle((0, 0, WIDTH, 160), fill=NAVY)
    poster.text((70, 27), kicker, poster.fonts.bold(24), fill="#A9D6D3")
    poster.text((70, 60), title, poster.fonts.bold(54), fill=WHITE)
    poster.text((1530, 104), subtitle, poster.fonts.regular(27), fill="#DCE9F1", anchor="ra")


def draw_footer(poster: Poster, source: str) -> None:
    poster.draw.line((70, 941, 1530, 941), fill=BORDER, width=2)
    poster.text((70, 958), source, poster.fonts.regular(23), fill=FAINT)
    poster.text(
        (1530, 958),
        "VolPred｜數據綁定、可復現",
        poster.fonts.regular(23),
        fill=FAINT,
        anchor="ra",
    )


def draw_arrow(
    poster: Poster,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: str = TEAL,
    width: int = 10,
) -> None:
    x1, y1 = start
    x2, y2 = end
    poster.draw.line((x1, y1, x2 - 19, y2), fill=fill, width=width)
    poster.draw.polygon(
        [(x2, y2), (x2 - 27, y2 - 18), (x2 - 27, y2 + 18)], fill=fill
    )


def draw_coin_stack(poster: Poster, x: int, y: int, color: str) -> None:
    for offset in (32, 16, 0):
        poster.draw.rectangle((x, y + offset, x + 76, y + offset + 22), fill=color)
        poster.draw.ellipse((x, y + offset - 10, x + 76, y + offset + 12), fill=color)
        poster.draw.ellipse(
            (x + 7, y + offset - 4, x + 69, y + offset + 7), fill=WHITE
        )


def draw_target(poster: Poster, x: int, y: int) -> None:
    for radius, color in ((48, BLUE_SOFT), (33, BLUE), (17, WHITE), (7, RED)):
        poster.draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius), fill=color
        )


def draw_database(poster: Poster, x: int, y: int) -> None:
    poster.draw.rectangle((x, y + 15, x + 98, y + 84), fill=BLUE_SOFT, outline=BLUE, width=3)
    poster.draw.ellipse((x, y, x + 98, y + 32), fill=BLUE_SOFT, outline=BLUE, width=3)
    poster.draw.ellipse((x, y + 68, x + 98, y + 100), fill=BLUE_SOFT, outline=BLUE, width=3)
    poster.draw.arc((x, y + 28, x + 98, y + 60), 0, 180, fill=BLUE, width=3)


def draw_resample(poster: Poster, x: int, y: int) -> None:
    nodes = [(x, y + 45), (x + 70, y), (x + 70, y + 45), (x + 70, y + 90)]
    for destination in nodes[1:]:
        poster.draw.line((nodes[0], destination), fill=TEAL, width=5)
    for cx, cy in nodes:
        poster.draw.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill=TEAL)


def draw_histogram(poster: Poster, x: int, y: int) -> None:
    heights = [30, 58, 88, 66, 42]
    for index, height in enumerate(heights):
        x0 = x + index * 27
        poster.draw.rounded_rectangle(
            (x0, y + 95 - height, x0 + 18, y + 95), radius=5, fill=AMBER
        )
    poster.draw.line((x - 8, y + 96, x + 132, y + 96), fill=INK, width=3)


def render_concept(bound: BoundText, fonts: FontBook) -> Poster:
    poster = Poster(fonts)
    draw_header(
        poster,
        "K1409｜三檔高股息 ETF 現金流規劃",
        "本金能不能換成穩定月領？",
        bound.ticker_line,
    )

    poster.rounded((70, 195, 1530, 450), radius=30, fill=SURFACE, outline=None)
    draw_coin_stack(poster, 118, 268, TEAL)
    poster.text((230, 235), "投入規模", poster.fonts.bold(27), fill=MUTED)
    poster.text((230, 285), bound.principal_total, poster.fonts.bold(58), fill=NAVY)

    draw_arrow(poster, (720, 325), (875, 325), fill=TEAL, width=10)

    draw_target(poster, 958, 322)
    poster.text((1040, 235), "現金流期待", poster.fonts.bold(27), fill=MUTED)
    poster.text((1040, 285), bound.target, poster.fonts.bold(58), fill=BLUE)

    card_width = 466
    card_gap = 31
    card_xs = [70, 70 + card_width + card_gap, 70 + 2 * (card_width + card_gap)]
    colors = [(TEAL, TEAL_SOFT), (BLUE, BLUE_SOFT), (AMBER, AMBER_SOFT)]
    for x, (ticker, principal), (accent, soft) in zip(
        card_xs, bound.principal_by_ticker.items(), colors, strict=True
    ):
        poster.rounded((x, 485, x + card_width, 670), radius=24, fill=WHITE)
        poster.draw.rounded_rectangle((x, 485, x + 12, 670), radius=6, fill=accent)
        poster.draw.ellipse((x + 36, 523, x + 96, 583), fill=soft)
        poster.text((66 + x, 553), ticker[-2:], poster.fonts.bold(20), fill=accent, anchor="mm")
        poster.text((x + 125, 515), ticker, poster.fonts.bold(37), fill=NAVY)
        poster.text((x + 125, 573), principal, poster.fonts.bold(42), fill=accent)
        poster.text((x + 125, 626), "配置本金", poster.fonts.regular(23), fill=MUTED)

    poster.rounded((70, 705, 1530, 910), radius=28, fill=NAVY_2, outline=None)
    poster.text((110, 740), "季配息錯開後", poster.fonts.regular(25), fill="#BFD3DF")
    poster.text((110, 786), bound.calendar, poster.fonts.bold(43), fill=WHITE)

    # Calendar cells are a visual restatement of verdict.summary, not the
    # contradictory structured calendar fields (see module docstring).
    start_x = 790
    for month in range(1, bound.calendar_total + 1):
        x = start_x + (month - 1) * 57
        is_gap = month == bound.calendar_gap
        fill = RED_SOFT if is_gap else TEAL_SOFT
        outline = RED if is_gap else TEAL
        poster.draw.rounded_rectangle(
            (x, 755, x + 44, 843), radius=10, fill=fill, outline=outline, width=2
        )
        poster.text(
            (x + 22, 782),
            str(month),
            poster.fonts.bold(19),
            fill=outline,
            anchor="mm",
        )
        poster.draw.ellipse((x + 17, 813, x + 27, 823), fill=outline)
    poster.text(
        (790, 862),
        f"{bound.calendar_gap} 月標示為空窗",
        poster.fonts.regular(22),
        fill="#D5E4EC",
    )

    draw_footer(poster, bound.source)
    return poster


def render_method(bound: BoundText, fonts: FontBook) -> Poster:
    poster = Poster(fonts)
    draw_header(
        poster,
        "K1409｜怎麼把歷史資料變成達標機率",
        "用大量路徑檢驗月領目標",
        "配息與價格分開模擬",
    )

    hero_cards = [
        (70, 195, 775, 420, TEAL_SOFT, TEAL, bound.simulations),
        (825, 195, 1530, 420, BLUE_SOFT, BLUE, bound.horizon),
    ]
    for x1, y1, x2, y2, soft, accent, label in hero_cards:
        poster.rounded((x1, y1, x2, y2), radius=28, fill=soft, outline=None)
        poster.draw.ellipse((x1 + 38, y1 + 57, x1 + 150, y1 + 169), fill=WHITE)
        if label == bound.simulations:
            draw_resample(poster, x1 + 52, y1 + 67)
        else:
            poster.draw.line((x1 + 68, y1 + 88, x1 + 122, y1 + 88), fill=accent, width=7)
            poster.draw.line((x1 + 68, y1 + 113, x1 + 122, y1 + 113), fill=accent, width=7)
            poster.draw.line((x1 + 68, y1 + 138, x1 + 112, y1 + 138), fill=accent, width=7)
        poster.text((x1 + 185, y1 + 74), label, poster.fonts.bold(43), fill=NAVY)
        sub = "重複抽樣，建立可能情境" if label == bound.simulations else "追蹤本金與每月現金流"
        poster.text((x1 + 185, y1 + 137), sub, poster.fonts.regular(27), fill=MUTED)

    poster.rounded((70, 465, 1530, 785), radius=30, fill=WHITE)
    poster.text((110, 500), "資料流", poster.fonts.bold(27), fill=MUTED)

    pipeline = [
        (110, 555, 495, 735, BLUE_SOFT, BLUE, "真實 ETF 歷史配息數據", "搭配價格月報酬"),
        (605, 555, 990, 735, TEAL_SOFT, TEAL, "保留真實除息日曆", "配息金額重新抽樣"),
        (1100, 555, 1485, 735, AMBER_SOFT, AMBER, "逐月整理分布", "計算配息與達標機率"),
    ]
    for index, (x1, y1, x2, y2, soft, accent, title, subtitle) in enumerate(pipeline):
        poster.draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=soft)
        if index == 0:
            draw_database(poster, x1 + 10, y1 + 35)
        elif index == 1:
            draw_resample(poster, x1 + 30, y1 + 46)
        else:
            draw_histogram(poster, x1 + 20, y1 + 33)
        text_left = x1 + (160 if index == 2 else 120)
        text_right = x2 - 18
        title_font = poster.fonts.bold(24)
        subtitle_font = poster.fonts.regular(23)
        poster.assert_text_fits(
            title,
            title_font,
            left=text_left,
            right=text_right,
            context=f"pipeline card {index + 1} title",
        )
        poster.assert_text_fits(
            subtitle,
            subtitle_font,
            left=text_left,
            right=text_right,
            context=f"pipeline card {index + 1} subtitle",
        )
        poster.text((text_left, y1 + 43), title, title_font, fill=NAVY)
        poster.text((text_left, y1 + 98), subtitle, subtitle_font, fill=MUTED)
        if index < 2:
            draw_arrow(poster, (x2 + 20, 645), (x2 + 100, 645), fill=FAINT, width=7)

    poster.rounded((70, 820, 1530, 910), radius=22, fill=NAVY_2, outline=None)
    poster.text(
        (110, 865),
        "所有數字直接讀自 k1409_results.json，非估計",
        poster.fonts.bold(29),
        fill=WHITE,
        anchor="lm",
    )
    poster.text(
        (1490, 865),
        "固定 seed，可復現",
        poster.fonts.regular(25),
        fill="#C9DCE7",
        anchor="rm",
    )

    draw_footer(poster, bound.source)
    return poster


def render_results(bound: BoundText, data: dict[str, Any], fonts: FontBook) -> Poster:
    poster = Poster(fonts)
    draw_header(
        poster,
        "K1409｜月領目標的真實機率",
        "有配息，不等於每月都領滿",
        bound.target,
    )

    top_cards = [
        (70, 195, 775, 435, RED_SOFT, RED, bound.avg_hit, bound.avg_hit_raw),
        (825, 195, 1530, 435, AMBER_SOFT, AMBER, bound.paid_hit, bound.paid_hit_raw),
    ]
    for x1, y1, x2, y2, soft, accent, headline, raw in top_cards:
        poster.rounded((x1, y1, x2, y2), radius=28, fill=soft, outline=None)
        poster.draw.rounded_rectangle((x1, y1, x1 + 14, y2), radius=7, fill=accent)
        poster.text((x1 + 45, y1 + 54), headline, poster.fonts.bold(46), fill=NAVY)
        poster.text((x1 + 45, y1 + 125), raw, poster.fonts.regular(27), fill=accent)
        note = "平均每月能否領滿目標" if headline == bound.avg_hit else "只看有配息的月份"
        poster.text((x1 + 45, y1 + 178), note, poster.fonts.regular(25), fill=MUTED)

    poster.rounded((70, 470, 930, 790), radius=28, fill=WHITE)
    poster.text((110, 505), bound.yield_compare, poster.fonts.bold(39), fill=NAVY)
    poster.text((110, 560), "圖表宣傳隱含值", poster.fonts.regular(25), fill=MUTED)

    implied = number(data, "results.yield_stats.implied_yield_from_chart")
    realized = number(data, "results.yield_stats.realized_yield_median")
    bar_left, bar_right = 285, 865
    max_width = bar_right - bar_left
    poster.text((110, 620), "隱含", poster.fonts.bold(26), fill=AMBER)
    poster.draw.rounded_rectangle((bar_left, 618, bar_right, 654), radius=18, fill=AMBER_SOFT)
    poster.draw.rounded_rectangle((bar_left, 618, bar_right, 654), radius=18, fill=AMBER)
    poster.text((850, 636), f"{implied * 100:.1f}%", poster.fonts.bold(25), fill=WHITE, anchor="rm")

    realized_width = round(max_width * realized / implied)
    poster.text((110, 694), "實現", poster.fonts.bold(26), fill=TEAL)
    poster.draw.rounded_rectangle((bar_left, 692, bar_right, 728), radius=18, fill=TEAL_SOFT)
    poster.draw.rounded_rectangle(
        (bar_left, 692, bar_left + realized_width, 728), radius=18, fill=TEAL
    )
    poster.text(
        (bar_left + realized_width - 14, 710),
        f"{realized * 100:.1f}%",
        poster.fonts.bold(25),
        fill=WHITE,
        anchor="rm",
    )
    poster.text((110, 752), "實現值為模擬中位數", poster.fonts.regular(23), fill=MUTED)

    poster.rounded((970, 470, 1530, 790), radius=28, fill=SURFACE, outline=None)
    poster.text((1010, 510), bound.median_dividend, poster.fonts.bold(38), fill=NAVY)
    poster.draw.line((1010, 585, 1490, 585), fill=BORDER, width=3)
    poster.text((1010, 630), bound.p5_dividend, poster.fonts.bold(31), fill=RED)
    poster.text((1490, 630), bound.p95_dividend, poster.fonts.bold(31), fill=GREEN, anchor="ra")
    poster.text((1010, 692), "較差情境", poster.fonts.regular(23), fill=MUTED)
    poster.text((1490, 692), "較佳情境", poster.fonts.regular(23), fill=MUTED, anchor="ra")
    poster.draw.line((1030, 740, 1470, 740), fill=BORDER, width=8)
    poster.draw.ellipse((1020, 728, 1044, 752), fill=RED)
    poster.draw.ellipse((1238, 726, 1266, 754), fill=NAVY)
    poster.draw.ellipse((1456, 728, 1480, 752), fill=GREEN)

    limitation_text = "母體期間短且偏多頭，真實下檔與斷配風險可能被低估"
    limitations = " ".join(str(item) for item in deep_get(data, "data_limitations"))
    summary = str(deep_get(data, "verdict.summary"))
    if "樣本短" not in limitations or "偏多頭" not in limitations or "斷配風險" not in summary:
        raise ValueError("Evidence no longer supports the rendered limitation statement")
    poster.rounded((70, 825, 1530, 910), radius=22, fill=NAVY_2, outline=None)
    poster.text((110, 867), "資料限制", poster.fonts.bold(25), fill="#A9D6D3", anchor="lm")
    poster.text((260, 867), limitation_text, poster.fonts.bold(29), fill=WHITE, anchor="lm")

    draw_footer(poster, bound.source)
    return poster


REQUIRED_TEXT = {
    "concept.png": [
        "本金 160.5 萬元",
        "0056 / 00878 / 00919",
        "目標：月領 1 萬",
        "11/12 月有配息（4 月空窗）",
    ],
    "method.png": [
        "5000 次蒙地卡羅模擬",
        "36 個月本金淨值路徑",
        "真實 ETF 歷史配息數據",
    ],
    "results.png": [
        "平均月達標率 2.7%",
        "有配息月 P(≥1萬)=33.9%",
        "隱含殖利率 9.7% vs 實現 7.0%",
        "月配息中位數 9,216 元",
    ],
}


def save_and_verify(
    poster: Poster,
    path: Path,
    required_text: list[str],
    fonts: FontBook,
) -> None:
    rendered_text = "\n".join(poster.text_log)
    missing_required = [text for text in required_text if text not in rendered_text]
    if missing_required:
        raise AssertionError(f"{path.name} missing commissioned text: {missing_required}")

    # A codepoint-level CJK check catches missing-glyph boxes before saving.
    for font_path in {fonts.regular_path, fonts.bold_path}:
        missing = missing_glyphs(font_path, poster.text_log)
        if missing:
            raise RuntimeError(f"Potential tofu in {path.name} using {font_path}: {missing}")

    path.parent.mkdir(parents=True, exist_ok=True)
    poster.image.save(path, format="PNG", dpi=(DPI, DPI), optimize=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"PNG was not created or is empty: {path}")

    with Image.open(path) as check:
        if check.format != "PNG" or check.size != (WIDTH, HEIGHT):
            raise RuntimeError(
                f"Bad output {path}: format={check.format}, size={check.size}"
            )
        dpi = check.info.get("dpi")
        if dpi and not all(abs(component - DPI) < 1 for component in dpi):
            raise RuntimeError(f"Bad DPI metadata for {path}: {dpi}")
        check.verify()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=DEFAULT_EVIDENCE,
        help="Path to k1409_results.json",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory for concept.png, method.png, and results.png",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    evidence_path = args.evidence.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    data = load_evidence(evidence_path)
    bound = bind_text(data)

    probe = [
        *REQUIRED_TEXT["concept.png"],
        *REQUIRED_TEXT["method.png"],
        *REQUIRED_TEXT["results.png"],
        bound.source,
        "繁體中文｜數據綁定、可復現",
    ]
    fonts = choose_fonts(probe)

    posters = {
        "concept.png": render_concept(bound, fonts),
        "method.png": render_method(bound, fonts),
        "results.png": render_results(bound, data, fonts),
    }
    for filename, poster in posters.items():
        output = out_dir / filename
        save_and_verify(poster, output, REQUIRED_TEXT[filename], fonts)
        print(f"created {output} ({output.stat().st_size:,} bytes)")
    print(f"font regular={fonts.regular_path} bold={fonts.bold_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
