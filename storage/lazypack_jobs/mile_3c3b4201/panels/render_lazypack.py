#!/usr/bin/env python3
"""Render the K1675 data-quality lazypack as deterministic PNG files.

The renderer is intentionally data-bound: every date, count, sample period,
identifier, and ratio-like string drawn on the posters comes from
``k1675_results.json`` (or is a length/count computed from one of its arrays).
README/article prose is used only for the non-numeric explanation of the data
quality failure modes.  No image-generation service is called.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTCollection, TTFont
from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)
WHITE = "#FFFFFF"
NAVY = "#102A43"
INK = "#183047"
MUTED = "#5C6B7A"
FAINT = "#7B8996"
LINE = "#D8E1EA"
PALE = "#F5F8FB"
BLUE = "#2F6B9A"
BLUE_SOFT = "#E8F1F8"
TEAL = "#167C80"
TEAL_SOFT = "#E5F4F2"
AMBER = "#B87516"
AMBER_SOFT = "#FBF0DE"
RED = "#B94742"
RED_SOFT = "#F9E8E6"
GREEN = "#2E7651"
GREEN_SOFT = "#E7F2EB"

REGULAR_FONT = Path("/System/Library/Fonts/STHeiti Light.ttc")
BOLD_FONT = Path("/System/Library/Fonts/STHeiti Medium.ttc")
FONT_INDEX = 0  # Heiti TC; index 1 is Heiti SC.

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
DEFAULT_RESULTS = REPO_ROOT / "experiments/k1675/k1675_results.json"
DEFAULT_README = REPO_ROOT / "experiments/k1675/README.md"
DEFAULT_ARTICLE = Path(
    "/var/folders/f1/g41vrs0n20v7cx66qzcsd1nc0000gn/T/"
    "tmp9i9y9yoh_article.md"
)


@dataclass(frozen=True)
class Binding:
    panel: str
    display: str
    source: str


class Evidence:
    """Resolve JSON paths and retain an audit trail for every shown value."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.bindings: list[Binding] = []

    def get(self, path: str) -> Any:
        cur: Any = self.data
        for part in path.split("."):
            if isinstance(cur, dict):
                if part not in cur:
                    raise KeyError(f"Missing evidence path: {path}")
                cur = cur[part]
            elif isinstance(cur, list):
                try:
                    cur = cur[int(part)]
                except (ValueError, IndexError) as exc:
                    raise KeyError(f"Missing evidence path: {path}") from exc
            else:
                raise KeyError(f"Missing evidence path: {path}")
        return cur

    def value(self, panel: str, path: str, *, display: str | None = None) -> str:
        raw = self.get(path)
        shown = str(raw) if display is None else display
        self.bindings.append(Binding(panel, shown, path))
        return shown

    def count(self, panel: str, path: str, *, prefix: str = "") -> str:
        raw = self.get(path)
        if not isinstance(raw, list):
            raise TypeError(f"Expected list for len({path})")
        shown = f"{prefix}{len(raw)}"
        self.bindings.append(Binding(panel, shown, f"len({path})"))
        return shown

    def derived_count(self, panel: str, display: str, source: str) -> str:
        self.bindings.append(Binding(panel, display, source))
        return display


class FontBook:
    def __init__(self) -> None:
        if not REGULAR_FONT.exists() or not BOLD_FONT.exists():
            raise RuntimeError(
                "Heiti TC fonts are unavailable; install a Traditional Chinese font "
                "or update REGULAR_FONT/BOLD_FONT."
            )
        self.regular_cmap = self._load_cmap(REGULAR_FONT, expected="Heiti TC")
        self.bold_cmap = self._load_cmap(BOLD_FONT, expected="Heiti TC")
        self._regular: dict[int, ImageFont.FreeTypeFont] = {}
        self._bold: dict[int, ImageFont.FreeTypeFont] = {}

    @staticmethod
    def _load_cmap(path: Path, *, expected: str) -> set[int]:
        if path.suffix.lower() == ".ttc":
            collection = TTCollection(str(path), lazy=True)
            font = collection.fonts[FONT_INDEX]
        else:
            font = TTFont(str(path), lazy=True)
        families: set[str] = set()
        for name in font["name"].names:
            if name.nameID == 1:
                try:
                    families.add(name.toUnicode())
                except Exception:
                    pass
        if expected not in families:
            raise RuntimeError(
                f"Wrong TTC face for {path}: expected {expected}, got {sorted(families)}"
            )
        cmap: set[int] = set()
        for table in font["cmap"].tables:
            cmap.update(table.cmap.keys())
        return cmap

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._regular:
            self._regular[size] = ImageFont.truetype(
                str(REGULAR_FONT), size=size, index=FONT_INDEX
            )
        return self._regular[size]

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._bold:
            self._bold[size] = ImageFont.truetype(
                str(BOLD_FONT), size=size, index=FONT_INDEX
            )
        return self._bold[size]

    def assert_text(self, text: str, *, bold: bool) -> None:
        cmap = self.bold_cmap if bold else self.regular_cmap
        missing = sorted({ch for ch in text if not ch.isspace() and ord(ch) not in cmap})
        if missing:
            codepoints = ", ".join(f"{ch!r}=U+{ord(ch):04X}" for ch in missing)
            raise RuntimeError(f"CJK font glyph coverage failure: {codepoints}")


FONTS = FontBook()


def assert_box(box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    if not (0 <= x0 <= x1 <= WIDTH and 0 <= y0 <= y1 <= HEIGHT):
        raise AssertionError(f"Drawing box outside canvas: {box}")


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str,
    outline: str | None = None,
    width: int = 1,
    radius: int = 24,
) -> None:
    assert_box(box)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def put(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    size: int,
    fill: str = INK,
    bold: bool = False,
    anchor: str = "la",
    stroke_width: int = 0,
    stroke_fill: str | None = None,
) -> tuple[int, int, int, int]:
    FONTS.assert_text(text, bold=bold)
    font = FONTS.bold(size) if bold else FONTS.regular(size)
    bbox = draw.textbbox(
        xy,
        text,
        font=font,
        anchor=anchor,
        stroke_width=stroke_width,
    )
    assert_box(tuple(int(v) for v in bbox))
    draw.text(
        xy,
        text,
        font=font,
        fill=fill,
        anchor=anchor,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    return tuple(int(v) for v in bbox)


def wrap_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
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
            width = draw.textbbox((0, 0), candidate, font=font)[2]
            if current and width > max_width:
                lines.append(current.rstrip())
                current = char.lstrip()
            else:
                current = candidate
        if current:
            lines.append(current.rstrip())
    return lines


def paragraph(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    size: int,
    max_width: int,
    fill: str = MUTED,
    bold: bool = False,
    line_gap: int = 8,
    max_lines: int | None = None,
) -> int:
    FONTS.assert_text(text, bold=bold)
    font = FONTS.bold(size) if bold else FONTS.regular(size)
    lines = wrap_lines(draw, text, font=font, max_width=max_width)
    if max_lines is not None and len(lines) > max_lines:
        raise AssertionError(f"Text needs {len(lines)} lines but max_lines={max_lines}: {text}")
    x, y = xy
    step = size + line_gap
    for index, line in enumerate(lines):
        put(draw, (x, y + index * step), line, size=size, fill=fill, bold=bold)
    return y + len(lines) * step


def source_footer(draw: ImageDraw.ImageDraw, experiment_id: str) -> None:
    draw.line((64, 928, 1536, 928), fill=LINE, width=2)
    put(
        draw,
        (64, 950),
        f"資料來源：experiment {experiment_id}",
        size=22,
        fill=FAINT,
        anchor="lm",
    )
    put(
        draw,
        (1536, 950),
        "VolPred｜資料品質專題",
        size=22,
        fill=FAINT,
        anchor="rm",
    )


def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    return image, ImageDraw.Draw(image)


def draw_calendar_off(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    box = (x, y, x + size, y + int(size * 0.82))
    rounded(draw, box, fill=WHITE, outline=BLUE, width=4, radius=18)
    draw.rectangle((x, y, x + size, y + int(size * 0.22)), fill=BLUE)
    for dx in (int(size * 0.25), int(size * 0.72)):
        draw.line((x + dx, y - 10, x + dx, y + 18), fill=NAVY, width=7)
    cell = int(size * 0.11)
    for row in range(2):
        for col in range(3):
            cx = x + 24 + col * int(size * 0.25)
            cy = y + int(size * 0.34) + row * int(size * 0.21)
            rounded(draw, (cx, cy, cx + cell, cy + cell), fill=BLUE_SOFT, radius=4)
    draw.line((x + 18, y + size - 2, x + size - 16, y + 8), fill=RED, width=10)


def draw_table_icon(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    rounded(draw, box, fill=WHITE, outline=LINE, width=3, radius=12)
    header_h = 34
    draw.rectangle((x0, y0, x1, y0 + header_h), fill=BLUE_SOFT)
    columns = 6
    col_w = (x1 - x0) / columns
    for index in range(1, columns):
        x = int(x0 + col_w * index)
        draw.line((x, y0, x, y1), fill=LINE, width=2)
    draw.line((x0, y0 + header_h, x1, y0 + header_h), fill=LINE, width=2)
    draw.line((x0, y0 + 73, x1, y0 + 73), fill=LINE, width=2)
    draw.rectangle((x0 + 2, y0 + 74, x1 - 2, y1 - 2), fill=RED_SOFT)
    for row_y in (y0 + 53, y0 + 94):
        for index in range(columns):
            cx = int(x0 + col_w * index + 13)
            draw.line((cx, row_y, cx + int(col_w) - 26, row_y), fill=FAINT, width=5)


def draw_check_badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int) -> None:
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=GREEN_SOFT)
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=GREEN,
        width=4,
    )
    draw.line(
        (cx - radius // 2, cy, cx - radius // 8, cy + radius // 3),
        fill=GREEN,
        width=8,
    )
    draw.line(
        (cx - radius // 8, cy + radius // 3, cx + radius // 2, cy - radius // 3),
        fill=GREEN,
        width=8,
    )


def draw_arrow(draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int, *, color: str) -> None:
    draw.line((x0, y, x1 - 13, y), fill=color, width=5)
    draw.polygon([(x1, y), (x1 - 18, y - 11), (x1 - 18, y + 11)], fill=color)


def render_concept(ev: Evidence, out: Path, experiment_id: str) -> None:
    panel = "1_concept.png"
    image, draw = new_canvas()

    closure_days = ev.get("closure_days")
    date_a = "2014-07-23"
    date_b = "2016-07-08"
    if date_a not in closure_days or date_b not in closure_days:
        raise AssertionError("Expected documented phantom-row dates are absent from closure_days")
    date_a = ev.value(panel, f"closure_days.{closure_days.index(date_a)}")
    date_b = ev.value(panel, f"closure_days.{closure_days.index(date_b)}")
    cross_check = ev.value(panel, "derivation_audit.final_margin_cross_check")
    cross_number, cross_text = cross_check.split(" ", 1)

    rounded(draw, (30, 24, 1570, 194), fill=NAVY, radius=28)
    put(draw, (78, 55), "市場休市，資料卻說有交易", size=56, fill=WHITE, bold=True)
    put(
        draw,
        (80, 133),
        "一列行情只能證明資料庫有一列，不能證明市場真的開門。",
        size=27,
        fill="#DCE8F2",
    )

    rounded(draw, (78, 235, 770, 610), fill=PALE, outline=LINE, width=2, radius=26)
    put(draw, (118, 273), "行情供應商：看起來有資料", size=31, bold=True)
    draw_table_icon(draw, (118, 330, 450, 454))
    put(draw, (490, 337), date_a, size=30, fill=RED, bold=True)
    put(draw, (490, 380), date_b, size=30, fill=RED, bold=True)
    put(draw, (490, 431), "整列複製前日", size=24, fill=MUTED)
    rounded(draw, (118, 495, 352, 550), fill=AMBER_SOFT, radius=16)
    put(draw, (235, 523), "整列複製", size=24, fill=AMBER, bold=True, anchor="mm")
    rounded(draw, (370, 495, 702, 550), fill=AMBER_SOFT, radius=16)
    put(
        draw,
        (536, 523),
        "四價全平＋成交量為零",
        size=23,
        fill=AMBER,
        bold=True,
        anchor="mm",
    )

    rounded(draw, (830, 235, 1522, 610), fill=TEAL_SOFT, outline="#B9DDD9", width=2, radius=26)
    put(draw, (870, 273), "獨立官方證據：市場沒有交易", size=31, bold=True)
    draw_check_badge(draw, 958, 419, 63)
    put(draw, (1062, 372), cross_number, size=78, fill=TEAL, bold=True)
    paragraph(
        draw,
        (1065, 469),
        cross_text,
        size=25,
        max_width=395,
        fill=MUTED,
        max_lines=2,
    )

    rounded(draw, (205, 653, 1395, 770), fill=NAVY, radius=26)
    put(draw, (800, 697), "有行情列  ≠  有交易", size=49, fill=WHITE, bold=True, anchor="mm")
    put(
        draw,
        (800, 743),
        "回測前先驗證交易事實，再計算報酬與波動。",
        size=25,
        fill="#DCE8F2",
        anchor="mm",
    )

    rounded(draw, (78, 808, 770, 895), fill=RED_SOFT, radius=18)
    put(draw, (112, 837), "多一列", size=27, fill=RED, bold=True)
    put(draw, (245, 837), "停市日被誤判成交易日", size=25, fill=INK)
    rounded(draw, (830, 808, 1522, 895), fill=BLUE_SOFT, radius=18)
    put(draw, (864, 837), "少一列", size=27, fill=BLUE, bold=True)
    put(draw, (997, 837), "正常交易日被誤判成停市日", size=25, fill=INK)

    source_footer(draw, experiment_id)
    save_and_validate(image, out)


def render_method(ev: Evidence, out: Path, experiment_id: str) -> None:
    panel = "2_method.png"
    image, draw = new_canvas()

    sample_period = ev.value(panel, "sample_period")
    n_library = ev.count(panel, "derivation_audit.source_a_library_typhoons")
    accepted = ev.count(panel, "derivation_audit.source_b_residual_scan_accepted")
    rejected = ev.count(panel, "derivation_audit.source_b_residual_scan_rejected")
    n_candidates_int = int(accepted) + int(rejected)
    n_candidates = ev.derived_count(
        panel,
        str(n_candidates_int),
        "len(derivation_audit.source_b_residual_scan_accepted) + "
        "len(derivation_audit.source_b_residual_scan_rejected)",
    )
    accepted_date = ev.value(panel, "derivation_audit.source_b_residual_scan_accepted.0")
    n_days = ev.value(panel, "n_closure_days")
    n_events = ev.value(panel, "n_events")
    data_source_etf = ev.value(panel, "data_sources.1", display="0050")
    data_source_twse = ev.value(panel, "data_sources.3", display="TWSE 融資融券")

    put(draw, (64, 56), "單一資料源不夠，日期要交叉核對", size=50, bold=True)
    put(
        draw,
        (66, 121),
        "先寬鬆找候選，再用獨立資料逐一排除。",
        size=26,
        fill=MUTED,
    )
    rounded(draw, (1195, 54, 1536, 132), fill=PALE, outline=LINE, width=2, radius=18)
    put(draw, (1366, 78), "樣本期間", size=20, fill=FAINT, anchor="mm")
    put(draw, (1366, 111), sample_period, size=21, fill=INK, bold=True, anchor="mm")
    draw.line((64, 164, 1536, 164), fill=TEAL, width=5)

    card_y0, card_y1 = 220, 525
    cards = [
        (64, card_y0, 356, card_y1),
        (439, card_y0, 731, card_y1),
        (814, card_y0, 1106, card_y1),
        (1189, card_y0, 1536, card_y1),
    ]
    for box in cards:
        rounded(draw, box, fill=WHITE, outline=LINE, width=2, radius=24)

    put(draw, (98, 257), "來源 A｜日曆清單", size=24, fill=BLUE, bold=True)
    put(draw, (210, 349), n_library, size=78, fill=BLUE, bold=True, anchor="mm")
    put(draw, (258, 355), "天", size=29, fill=BLUE, bold=True, anchor="lm")
    paragraph(
        draw,
        (98, 420),
        "XTAI 結構化颱風停市清單",
        size=23,
        max_width=225,
        fill=MUTED,
        max_lines=2,
    )

    put(draw, (473, 257), "來源 B｜殘差掃描", size=24, fill=AMBER, bold=True)
    put(draw, (585, 349), n_candidates, size=78, fill=AMBER, bold=True, anchor="mm")
    put(draw, (633, 355), "個", size=29, fill=AMBER, bold=True, anchor="lm")
    put(
        draw,
        (585, 438),
        f"{accepted} 納入  ／  {rejected} 剔除",
        size=23,
        fill=MUTED,
        bold=True,
        anchor="mm",
    )

    put(draw, (848, 257), "獨立來源｜逐項排除", size=24, fill=TEAL, bold=True)
    rounded(draw, (848, 314, 1072, 363), fill=TEAL_SOFT, radius=14)
    put(
        draw,
        (960, 339),
        f"{data_source_etf} 真實行情",
        size=22,
        fill=TEAL,
        bold=True,
        anchor="mm",
    )
    rounded(draw, (848, 376, 1072, 425), fill=TEAL_SOFT, radius=14)
    put(draw, (960, 401), data_source_twse, size=22, fill=TEAL, bold=True, anchor="mm")
    rounded(draw, (848, 438, 1072, 487), fill=TEAL_SOFT, radius=14)
    put(draw, (960, 463), "預定假期鄰接", size=22, fill=TEAL, bold=True, anchor="mm")

    put(draw, (1223, 257), "最終樣本｜一致才納入", size=24, fill=GREEN, bold=True)
    put(draw, (1324, 343), n_days, size=78, fill=GREEN, bold=True, anchor="mm")
    put(draw, (1376, 350), "天", size=29, fill=GREEN, bold=True, anchor="lm")
    put(
        draw,
        (1362, 432),
        f"合併為 {n_events} 個事件",
        size=23,
        fill=MUTED,
        bold=True,
        anchor="mm",
    )

    for left, right in zip(cards, cards[1:]):
        draw_arrow(draw, left[2] + 12, 373, right[0] - 12, color=LINE)

    rounded(draw, (190, 590, 1410, 760), fill=NAVY, radius=28)
    rounded(draw, (232, 628, 524, 722), fill="#173B5C", radius=18)
    put(draw, (378, 657), "殘差掃描補回", size=22, fill="#BFD5E6", anchor="mm")
    put(draw, (378, 700), accepted_date, size=34, fill=WHITE, bold=True, anchor="mm")
    draw_arrow(draw, 559, 675, 650, color="#91B8D4")
    put(draw, (689, 623), "康芮颱風：唯一通過交叉驗證的殘差候選", size=29, fill=WHITE, bold=True)
    paragraph(
        draw,
        (690, 674),
        "日曆漏列並不等於資料無法修正；關鍵是用 ETF、官方交易資料與假期邊界把候選驗清楚。",
        size=23,
        max_width=650,
        fill="#DCE8F2",
        max_lines=3,
    )

    rounded(draw, (280, 805, 1320, 884), fill=TEAL_SOFT, radius=20)
    put(
        draw,
        (800, 844),
        "缺資料只算候選；獨立證據一致，才算停市。",
        size=31,
        fill=TEAL,
        bold=True,
        anchor="mm",
    )

    # These two bindings justify the exact identifiers printed in the evidence cards.
    if "0050.TW" not in ev.get("data_sources.1") or "TWSE 融資融券" not in ev.get(
        "data_sources.3"
    ):
        raise AssertionError("Expected independent-source identifiers are missing")
    source_footer(draw, experiment_id)
    save_and_validate(image, out)


def render_results(ev: Evidence, out: Path, experiment_id: str) -> None:
    panel = "3_results.png"
    image, draw = new_canvas()

    sample_period = ev.value(panel, "sample_period")
    n_library = ev.count(panel, "derivation_audit.source_a_library_typhoons")
    accepted = ev.count(panel, "derivation_audit.source_b_residual_scan_accepted", prefix="+")
    accepted_plain = str(len(ev.get("derivation_audit.source_b_residual_scan_accepted")))
    ev.derived_count(panel, accepted_plain, "len(derivation_audit.source_b_residual_scan_accepted)")
    rejected_plain = ev.count(panel, "derivation_audit.source_b_residual_scan_rejected")
    n_candidates_value = int(accepted_plain) + int(rejected_plain)
    n_candidates = ev.derived_count(
        panel,
        str(n_candidates_value),
        "len(derivation_audit.source_b_residual_scan_accepted) + "
        "len(derivation_audit.source_b_residual_scan_rejected)",
    )
    accepted_date = ev.value(panel, "derivation_audit.source_b_residual_scan_accepted.0")
    n_days = ev.value(panel, "n_closure_days")
    n_events = ev.value(panel, "n_events")
    cross_check = ev.value(panel, "derivation_audit.final_margin_cross_check")
    cross_number, cross_text = cross_check.split(" ", 1)

    rejected = ev.get("derivation_audit.source_b_residual_scan_rejected")
    groups: Counter[str] = Counter()
    for row in rejected:
        reason = row["reason"]
        if "0050 有真實行情" in reason:
            groups["0050 有行情"] += 1
        elif "融資券有資料" in reason:
            groups["TWSE 有資料"] += 1
        elif "緊鄰預定連假" in reason:
            groups["假期邊界"] += 1
        else:
            raise AssertionError(f"Unclassified rejected-candidate reason: {reason}")
    if sum(groups.values()) != int(rejected_plain):
        raise AssertionError("Rejected-candidate reason counts do not reconcile")
    group_source = "derivation_audit.source_b_residual_scan_rejected[].reason"
    etf_count = ev.derived_count(panel, str(groups["0050 有行情"]), group_source)
    twse_count = ev.derived_count(panel, str(groups["TWSE 有資料"]), group_source)
    holiday_count = ev.derived_count(panel, str(groups["假期邊界"]), group_source)

    put(draw, (64, 54), "交叉驗證後，資料樣本留下什麼", size=50, bold=True)
    put(draw, (66, 120), f"歷史樣本：{sample_period}", size=25, fill=MUTED)
    draw.line((64, 164, 1536, 164), fill=NAVY, width=5)

    boxes = {
        "library": (64, 200, 524, 470),
        "accepted": (548, 200, 1012, 470),
        "verified": (1036, 200, 1536, 470),
        "candidates": (64, 495, 524, 835),
        "rejected": (548, 495, 1012, 835),
        "events": (1036, 495, 1536, 835),
    }
    fills = [BLUE_SOFT, TEAL_SOFT, GREEN_SOFT, AMBER_SOFT, RED_SOFT, PALE]
    outlines = ["#C5DCEB", "#B9DDD9", "#C2DDCC", "#EED7AF", "#ECC8C5", LINE]
    for box, fill, outline in zip(boxes.values(), fills, outlines):
        rounded(draw, box, fill=fill, outline=outline, width=2, radius=26)

    put(draw, (98, 237), "日曆來源已列出", size=25, fill=BLUE, bold=True)
    put(draw, (165, 344), n_library, size=90, fill=BLUE, bold=True, anchor="mm")
    put(draw, (229, 351), "個停市日", size=27, fill=BLUE, bold=True, anchor="lm")
    put(draw, (98, 421), "exchange_calendars XTAI", size=22, fill=MUTED)

    put(draw, (582, 237), "殘差掃描再補入", size=25, fill=TEAL, bold=True)
    put(draw, (662, 334), accepted, size=82, fill=TEAL, bold=True, anchor="mm")
    put(draw, (731, 341), "個", size=27, fill=TEAL, bold=True, anchor="lm")
    rounded(draw, (606, 386, 954, 440), fill=WHITE, radius=15)
    put(draw, (780, 413), accepted_date + "　康芮", size=24, fill=INK, bold=True, anchor="mm")

    put(draw, (1070, 237), "官方資料正向總驗證", size=25, fill=GREEN, bold=True)
    put(draw, (1137, 332), n_days, size=82, fill=GREEN, bold=True, anchor="mm")
    put(draw, (1204, 341), "個停市日", size=27, fill=GREEN, bold=True, anchor="lm")
    rounded(draw, (1072, 383, 1498, 442), fill=WHITE, radius=15)
    put(draw, (1285, 413), cross_number + "　" + cross_text.split("（", 1)[0], size=22, fill=GREEN, bold=True, anchor="mm")

    put(draw, (98, 533), "殘差掃描候選", size=25, fill=AMBER, bold=True)
    put(draw, (178, 646), n_candidates, size=92, fill=AMBER, bold=True, anchor="mm")
    put(draw, (245, 653), "個日期", size=28, fill=AMBER, bold=True, anchor="lm")
    put(
        draw,
        (294, 746),
        f"{accepted_plain} 納入　／　{rejected_plain} 剔除",
        size=25,
        fill=MUTED,
        bold=True,
        anchor="mm",
    )

    put(draw, (582, 533), "被排除的假候選", size=25, fill=RED, bold=True)
    put(draw, (645, 632), rejected_plain, size=78, fill=RED, bold=True, anchor="mm")
    put(draw, (701, 638), "個", size=27, fill=RED, bold=True, anchor="lm")
    reason_rows = [
        ("0050 有真實行情", etf_count),
        ("TWSE 融資券有資料", twse_count),
        ("預定假期邊界", holiday_count),
    ]
    for idx, (label, count) in enumerate(reason_rows):
        y = 703 + idx * 38
        put(draw, (594, y), label, size=21, fill=MUTED)
        put(draw, (950, y), count, size=22, fill=RED, bold=True, anchor="ra")

    put(draw, (1070, 533), "連續停市日合併後", size=25, fill=NAVY, bold=True)
    put(draw, (1160, 654), n_events, size=92, fill=NAVY, bold=True, anchor="mm")
    put(draw, (1228, 661), "個事件", size=28, fill=NAVY, bold=True, anchor="lm")
    paragraph(
        draw,
        (1072, 735),
        "乾淨事件日期，才進入後續報酬與波動分析。",
        size=23,
        max_width=410,
        fill=MUTED,
        max_lines=2,
    )

    rounded(draw, (315, 862, 1285, 910), fill=NAVY, radius=15)
    put(
        draw,
        (800, 886),
        "先證明市場真的有交易，再相信回測結果。",
        size=28,
        fill=WHITE,
        bold=True,
        anchor="mm",
    )

    source_footer(draw, experiment_id)
    save_and_validate(image, out)


def save_and_validate(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", dpi=DPI, optimize=True)

    with Image.open(path) as probe:
        if probe.format != "PNG":
            raise AssertionError(f"Not a PNG: {path}")
        probe.verify()

    with Image.open(path) as probe:
        probe.load()
        if probe.size != (WIDTH, HEIGHT):
            raise AssertionError(f"Wrong size for {path}: {probe.size}")
        if probe.mode not in {"RGB", "RGBA"}:
            raise AssertionError(f"Wrong mode for {path}: {probe.mode}")
        if "A" in probe.getbands() and probe.getchannel("A").getextrema() != (255, 255):
            raise AssertionError(f"Unexpected transparency in {path}")
        rgb = probe.convert("RGB")
        white_extrema = ((255, 255), (255, 255), (255, 255))
        border = 16
        edges = (
            (0, 0, WIDTH, border),
            (0, HEIGHT - border, WIDTH, HEIGHT),
            (0, 0, border, HEIGHT),
            (WIDTH - border, 0, WIDTH, HEIGHT),
        )
        for edge in edges:
            if rgb.crop(edge).getextrema() != white_extrema:
                raise AssertionError(f"Canvas edge is not white in {path}: {edge}")
        colors = rgb.getcolors(maxcolors=WIDTH * HEIGHT)
        if colors is None:
            raise AssertionError(f"Unable to inspect color distribution: {path}")
        white_ratio = sum(count for count, color in colors if color == (255, 255, 255)) / (
            WIDTH * HEIGHT
        )
        if not 0.20 <= white_ratio < 0.99:
            raise AssertionError(f"White/blank ratio failed for {path}: {white_ratio:.3f}")
        dpi = probe.info.get("dpi")
        if not dpi or any(abs(float(value) - 150.0) >= 1.0 for value in dpi):
            raise AssertionError(f"DPI metadata failed for {path}: {dpi}")
    if path.stat().st_size <= 1024:
        raise AssertionError(f"PNG is unexpectedly small: {path}")


def load_evidence(results_path: Path, readme_path: Path, article_path: Path) -> Evidence:
    with results_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("experiment_id") != "K1675":
        raise AssertionError(f"Unexpected experiment_id: {data.get('experiment_id')}")

    readme = readme_path.read_text(encoding="utf-8")
    article = article_path.read_text(encoding="utf-8") if article_path.exists() else ""
    prose = readme + "\n" + article
    required_prose = ("整列複製", "TWSE 融資融券", "殘差候選")
    missing = [phrase for phrase in required_prose if phrase not in prose]
    if missing:
        raise AssertionError(f"Evidence prose is missing required claims: {missing}")

    ev = Evidence(data)
    source_a = ev.get("derivation_audit.source_a_library_typhoons")
    accepted = ev.get("derivation_audit.source_b_residual_scan_accepted")
    rejected = ev.get("derivation_audit.source_b_residual_scan_rejected")
    if len(source_a) + len(accepted) != ev.get("n_closure_days"):
        raise AssertionError("15 + residual accepted does not reconcile to n_closure_days")
    if len(accepted) + len(rejected) != 6:
        raise AssertionError("Residual candidate audit no longer reconciles to six candidates")
    expected_cross = f"{ev.get('n_closure_days')}/{ev.get('n_closure_days')}"
    if not ev.get("derivation_audit.final_margin_cross_check").startswith(expected_cross):
        raise AssertionError("final_margin_cross_check does not reconcile to n_closure_days")
    return ev


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--article", type=Path, default=DEFAULT_ARTICLE)
    parser.add_argument("--out-dir", type=Path, default=SCRIPT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ev = load_evidence(args.results, args.readme, args.article)
    experiment_id = ev.value("all", "experiment_id")

    outputs = [
        args.out_dir / "1_concept.png",
        args.out_dir / "2_method.png",
        args.out_dir / "3_results.png",
    ]
    render_concept(ev, outputs[0], experiment_id)
    render_method(ev, outputs[1], experiment_id)
    render_results(ev, outputs[2], experiment_id)

    print("Rendered PNG files:")
    for path in outputs:
        print(f"- {path.resolve()} ({path.stat().st_size:,} bytes)")
    print("\nDisplayed evidence bindings:")
    for binding in ev.bindings:
        print(f"- [{binding.panel}] {binding.display!r} <- {binding.source}")
    print(f"\nFont: Heiti TC (regular={REGULAR_FONT}, bold={BOLD_FONT}, TTC index 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
