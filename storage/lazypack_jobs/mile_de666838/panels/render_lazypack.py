#!/usr/bin/env python3
"""Render the K1639 VolPred lazypack as three evidence-bound PNG panels.

Every displayed statistic is resolved at runtime from ``k1639_results.json``.
The README and article informed the reader-facing wording, but no article-only
number is used.  Rendering is local and deterministic; no image model or API is
called.

Default outputs (1600x1000 px, 150 dpi):
  - 1_concept.png
  - 2_method.png
  - 3_results.png
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

NAVY = "#10243E"
INK = "#182433"
MUTED = "#617083"
FAINT = "#8A97A7"
PAPER = "#F5F7FA"
WHITE = "#FFFFFF"
BORDER = "#DDE4EC"
BLUE = "#2E67D1"
BLUE_SOFT = "#E8F0FF"
TEAL = "#137A74"
TEAL_SOFT = "#E1F2F0"
ORANGE = "#D96F2B"
ORANGE_SOFT = "#FFF0E5"
RED = "#B84646"
RED_SOFT = "#FBEAEA"
GREEN = "#2D7D58"
GREEN_SOFT = "#E7F3EC"

REGULAR_FONTS = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
]
BOLD_FONTS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/NotoSansCJKtc-Bold.otf",
]

METHOD_LABELS = {
    "equal_weight": "等權重",
    "inverse_vol": "反波動加權",
    "erc_risk_parity": "ERC 風險平價",
    "min_variance": "最小變異",
    "hrp": "HRP 階層式",
    "herc_erc": "HERC 階層式",
    "nco_minvar": "NCO 階層式",
    "schur_block_mv": "Schur 分塊",
}
SIMPLE_METHODS = ["equal_weight", "inverse_vol", "erc_risk_parity", "min_variance"]
HIER_METHODS = ["hrp", "herc_erc", "nco_minvar", "schur_block_mv"]


@dataclass(frozen=True)
class FontBook:
    regular_path: Path
    bold_path: Path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


def first_existing(candidates: Iterable[str]) -> Path | None:
    for raw in candidates:
        path = Path(raw)
        if path.exists():
            return path
    return None


def glyph_signature(font: ImageFont.FreeTypeFont, char: str) -> tuple[Any, bytes]:
    mask = font.getmask(char)
    return (mask.size, bytes(mask))


def assert_zh_hant_glyphs(font_path: Path) -> None:
    """Reject a font if any required zh-Hant probe renders as .notdef/tofu."""
    font = ImageFont.truetype(str(font_path), size=44)
    missing = glyph_signature(font, chr(0x10FFFF))
    probe = "階層風險樣本權重變異檢驗淨夏普換手回撤資產過去今天贏穩健"
    tofu = [char for char in probe if glyph_signature(font, char) == missing]
    if tofu:
        raise RuntimeError(f"CJK font lacks required glyphs {tofu}: {font_path}")


def load_fonts() -> FontBook:
    regular = first_existing(REGULAR_FONTS)
    bold = first_existing(BOLD_FONTS)
    if regular is None or bold is None:
        raise RuntimeError("找不到可用的繁體中文字型（Heiti/PingFang/Arial Unicode/Noto CJK）。")
    assert_zh_hant_glyphs(regular)
    assert_zh_hant_glyphs(bold)
    return FontBook(regular, bold)


def load_results(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError("results JSON 必須是 object")
    if data.get("experiment_id") != "K1639":
        raise ValueError(f"預期 experiment_id=K1639，實際為 {data.get('experiment_id')!r}")
    expected_verdict = "CONDITIONAL_PASS_NULL_HIERARCHICAL_DOES_NOT_BEAT_SIMPLE_BASELINES"
    if data.get("verdict") != expected_verdict:
        raise ValueError("K1639 verdict 已改變；請先重新審閱文案再 render。")
    strategies = data_path(data, "method.strategies")
    if set(strategies) != set(SIMPLE_METHODS + HIER_METHODS):
        raise ValueError("策略集合已改變；panel 分組需要重新審閱。")
    validate_reader_claims(data)
    return data


def data_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(f"Evidence path 不存在：{path}")
    return current


def as_number(data: dict[str, Any], path: str) -> float:
    value = data_path(data, path)
    if not isinstance(value, (int, float)):
        raise TypeError(f"Evidence path 不是數字：{path}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Evidence path 不是有限數字：{path}")
    return value


def validate_reader_claims(data: dict[str, Any]) -> None:
    """Fail closed when a qualitative headline no longer follows the JSON."""
    ranking = data_path(data, "ranked_by_net_sharpe")
    top_two = [row["strategy"] for row in ranking[:2]]
    if top_two != ["erc_risk_parity", "inverse_vol"]:
        raise ValueError("淨夏普前兩名已改變；results panel 標題需要重新審閱。")
    best_hier = max(HIER_METHODS, key=lambda key: as_number(data, f"net_performance.{key}.sharpe"))
    if best_hier != "herc_erc":
        raise ValueError("階層式最高淨夏普策略已改變。")
    if data_path(data, "ranked_by_mdd.0.strategy") != "min_variance":
        raise ValueError("最小最大回撤策略已改變。")
    lowest_turnover = min(
        data_path(data, "method.strategies"),
        key=lambda key: as_number(data, f"net_performance.{key}.annual_turnover"),
    )
    if lowest_turnover != "equal_weight":
        raise ValueError("最低年換手率策略已改變。")
    herc_ci = data_path(data, "tests_vs_erc_risk_parity.herc_erc.sharpe_diff_bootstrap.ci95")
    nco_ci = data_path(data, "tests_vs_erc_risk_parity.nco_minvar.sharpe_diff_bootstrap.ci95")
    if not (herc_ci[0] <= 0 <= herc_ci[1]):
        raise ValueError("HERC 對 ERC 的信賴區間不再跨 0。")
    if not nco_ci[1] < 0:
        raise ValueError("NCO 對 ERC 的信賴區間不再全低於 0。")


def fmt_int(value: float | int) -> str:
    return f"{int(value):,}"


def fmt_decimal(value: float, digits: int = 3, plus: bool = False) -> str:
    spec = f"{'+' if plus else ''}.{digits}f"
    return format(value, spec)


def fmt_percent(value: float, digits: int = 1, plus: bool = False) -> str:
    spec = f"{'+' if plus else ''}.{digits}f"
    return f"{format(value * 100, spec)}%"


def text_box(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = current + char
            if not current or text_box(draw, candidate, font)[0] <= max_width:
                current = candidate
            else:
                lines.append(current.rstrip())
                current = char.lstrip()
        if current:
            lines.append(current.rstrip())
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 8,
    max_lines: int | None = None,
) -> int:
    lines = wrap_text(draw, text, font, max_width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        while text_box(draw, lines[-1] + "…", font)[0] > max_width and lines[-1]:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    x, y = xy
    line_height = text_box(draw, "國Ag", font)[1]
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + line_gap
    return y


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    radius: int = 24,
    outline: str | None = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_footer(draw: ImageDraw.ImageDraw, fonts: FontBook, experiment_id: str) -> None:
    y = 955
    draw.line((60, y - 14, 1540, y - 14), fill=BORDER, width=2)
    draw.text((60, y), f"資料來源：experiment {experiment_id}", font=fonts.regular(22), fill=MUTED)
    right = "VolPred｜程式化、可復現的資料視覺化"
    width, _ = text_box(draw, right, fonts.regular(22))
    draw.text((1540 - width, y), right, font=fonts.regular(22), fill=FAINT)


def draw_dark_header(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    kicker: str,
    title: str,
    subtitle: str,
    height: int = 185,
) -> None:
    draw.rectangle((0, 0, WIDTH, height), fill=NAVY)
    draw.text((64, 30), kicker, font=fonts.bold(23), fill="#91B6E6")
    draw.text((64, 65), title, font=fonts.bold(52), fill=WHITE)
    draw.text((66, 132), subtitle, font=fonts.regular(25), fill="#D8E3F0")
    draw.rectangle((1510, 0, 1600, height), fill=ORANGE)


def draw_method_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], hierarchical: bool) -> None:
    cx, cy = center
    if hierarchical:
        draw.line((cx, cy - 28, cx, cy - 5), fill=ORANGE, width=5)
        draw.line((cx - 40, cy + 18, cx + 40, cy + 18), fill=ORANGE, width=5)
        draw.line((cx - 40, cy + 18, cx - 40, cy + 42), fill=ORANGE, width=5)
        draw.line((cx + 40, cy + 18, cx + 40, cy + 42), fill=ORANGE, width=5)
        for x, y in [(cx, cy - 38), (cx - 40, cy + 50), (cx + 40, cy + 50)]:
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=ORANGE)
    else:
        for offset, height in [(-34, 42), (0, 62), (34, 50)]:
            draw.rounded_rectangle(
                (cx + offset - 11, cy + 42 - height, cx + offset + 11, cy + 42),
                radius=6,
                fill=BLUE,
            )


def render_concept(out_path: Path, data: dict[str, Any], fonts: FontBook) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    strategy_count = len(data_path(data, "method.strategies"))
    experiment_id = str(data_path(data, "experiment_id"))

    draw_dark_header(
        draw,
        fonts,
        "資產配置的兩條路線",
        "差別不在名稱，而在先不先分群",
        f"{strategy_count} 種方法分成兩個家族：左邊直接配，右邊先辨認資產的關聯結構。",
    )

    cards = [
        ((58, 220, 770, 675), "不分群的簡單基準", SIMPLE_METHODS, BLUE, BLUE_SOFT, False),
        ((830, 220, 1542, 675), "先分群再配置", HIER_METHODS, ORANGE, ORANGE_SOFT, True),
    ]
    for box, heading, methods, accent, soft, hierarchical in cards:
        rounded(draw, box, WHITE, radius=30, outline=BORDER, width=2)
        draw.ellipse((box[0] + 34, box[1] + 30, box[0] + 118, box[1] + 114), fill=soft)
        draw_method_icon(draw, (box[0] + 76, box[1] + 72), hierarchical)
        draw.text((box[0] + 142, box[1] + 42), heading, font=fonts.bold(32), fill=INK)
        draw.text(
            (box[0] + 142, box[1] + 85),
            f"{len(methods)} 種配置法",
            font=fonts.regular(23),
            fill=MUTED,
        )
        y = box[1] + 145
        for method in methods:
            rounded(draw, (box[0] + 34, y, box[2] - 34, y + 59), PAPER, radius=14)
            draw.ellipse((box[0] + 55, y + 20, box[0] + 73, y + 38), fill=accent)
            draw.text((box[0] + 91, y + 13), METHOD_LABELS[method], font=fonts.bold(26), fill=INK)
            y += 70

    rounded(draw, (58, 710, 1542, 910), PAPER, radius=26)
    draw.text((90, 742), "配置邏輯", font=fonts.bold(23), fill=MUTED)

    rounded(draw, (90, 790, 670, 866), BLUE_SOFT, radius=18)
    draw.text((122, 810), "波動／共變異數", font=fonts.bold(25), fill=BLUE)
    draw_arrow(draw, (350, 829), (470, 829), BLUE, width=5)
    draw.text((496, 810), "直接產生權重", font=fonts.bold(25), fill=INK)

    rounded(draw, (720, 790, 1510, 866), ORANGE_SOFT, radius=18)
    draw.text((752, 810), "資產相關性", font=fonts.bold(25), fill=ORANGE)
    draw_arrow(draw, (915, 829), (1020, 829), ORANGE, width=5)
    draw.text((1045, 810), "先分群", font=fonts.bold(25), fill=ORANGE)
    draw_arrow(draw, (1150, 829), (1255, 829), ORANGE, width=5)
    draw.text((1280, 810), "群內／群間配置", font=fonts.bold(25), fill=INK)

    question = "比較的核心：多出的分群層，能不能換回更好的樣本外淨績效？"
    question_w, _ = text_box(draw, question, fonts.bold(24))
    draw.text(((WIDTH - question_w) // 2, 881), question, font=fonts.bold(24), fill=NAVY)

    draw_footer(draw, fonts, experiment_id)
    save_png(image, out_path)


def draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], fill: str, width: int = 6) -> None:
    x1, y1 = start
    x2, y2 = end
    draw.line((x1, y1, x2 - 18, y2), fill=fill, width=width)
    draw.polygon([(x2, y2), (x2 - 24, y2 - 13), (x2 - 24, y2 + 13)], fill=fill)


def render_method(out_path: Path, data: dict[str, Any], fonts: FontBook) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    lookback = int(as_number(data, "method.lookback_trading_days"))
    cost_bps = as_number(data, "method.transaction_cost_bps_per_dollar_traded")
    strategy_count = len(data_path(data, "method.strategies"))
    reps = int(as_number(data, "method.bootstrap.reps"))
    block = int(as_number(data, "method.bootstrap.block"))
    seed = int(as_number(data, "method.bootstrap.seed"))
    experiment_id = str(data_path(data, "experiment_id"))

    draw.rectangle((0, 0, 20, HEIGHT), fill=ORANGE)
    draw.text((72, 46), "一場公平的樣本外測試", font=fonts.bold(24), fill=ORANGE)
    draw.text((72, 88), "每個方法，都只准看昨天以前", font=fonts.bold(58), fill=NAVY)
    draw_wrapped(
        draw,
        (75, 164),
        "權重生成時排除今天的報酬；所有策略再用相同節奏與相同成本接受檢驗。",
        fonts.regular(27),
        MUTED,
        1250,
        line_gap=6,
        max_lines=2,
    )

    rounded(draw, (70, 260, 1090, 700), PAPER, radius=30)
    draw.text((112, 298), fmt_int(lookback), font=fonts.bold(102), fill=BLUE)
    n_w, _ = text_box(draw, fmt_int(lookback), fonts.bold(102))
    draw.text((130 + n_w, 342), "個交易日的回看窗", font=fonts.bold(32), fill=INK)

    timeline_y = 502
    rounded(draw, (120, 448, 760, 555), BLUE_SOFT, radius=20, outline="#C9D9F5", width=2)
    draw.text((154, 470), "只用已發生的歷史報酬", font=fonts.bold(29), fill=BLUE)
    draw_arrow(draw, (772, timeline_y), (950, timeline_y), NAVY, width=6)
    draw.ellipse((930, timeline_y - 34, 998, timeline_y + 34), fill=ORANGE)
    draw.text((951, timeline_y - 20), "今", font=fonts.bold(28), fill=WHITE, anchor="mm")
    draw.text((874, 438), "產生權重", font=fonts.bold(24), fill=NAVY)
    draw.text((835, 553), "今天報酬不進估計窗", font=fonts.bold(25), fill=ORANGE)
    draw.text((120, 599), "防止同日訊號乘上同日報酬", font=fonts.bold(28), fill=INK)
    draw.text((120, 646), "每次決策只使用當下真正看得到的資訊。", font=fonts.regular(25), fill=MUTED)

    note_cards = [
        ("同一組對手", f"{strategy_count} 種方法", BLUE, BLUE_SOFT),
        ("同一更新節奏", "每月再平衡", TEAL, TEAL_SOFT),
        ("同一交易成本", f"每元換手 {cost_bps:g} bps", ORANGE, ORANGE_SOFT),
    ]
    y = 260
    for label, value, accent, soft in note_cards:
        rounded(draw, (1140, y, 1530, y + 126), WHITE, radius=22, outline=BORDER, width=2)
        draw.rectangle((1140, y, 1152, y + 126), fill=accent)
        draw.text((1180, y + 20), label, font=fonts.regular(22), fill=MUTED)
        draw.text((1180, y + 59), value, font=fonts.bold(29), fill=INK)
        draw.ellipse((1465, y + 42, 1503, y + 80), fill=soft)
        y += 145

    rounded(draw, (70, 742, 1530, 916), NAVY, radius=28)
    draw.text((108, 773), "再用區塊自助抽樣檢查差距是否只是運氣", font=fonts.bold(30), fill=WHITE)
    bootstrap_metrics = [
        (fmt_int(reps), "次重抽"),
        (fmt_int(block), "日一個區塊"),
        (fmt_int(seed), "基準 seed"),
    ]
    x = 755
    for value, label in bootstrap_metrics:
        draw.text((x, 768), value, font=fonts.bold(42), fill="#9CC5F2")
        width, _ = text_box(draw, value, fonts.bold(42))
        draw.text((x, 826), label, font=fonts.regular(21), fill="#D5E2EF")
        x += max(220, width + 105)

    draw_footer(draw, fonts, experiment_id)
    save_png(image, out_path)


def draw_metric_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    box: tuple[int, int, int, int],
    eyebrow: str,
    value: str,
    label: str,
    accent: str,
    soft: str,
    note: str,
    value_size: int = 62,
) -> None:
    rounded(draw, box, WHITE, radius=26, outline=BORDER, width=2)
    x1, y1, x2, y2 = box
    draw.rectangle((x1, y1, x1 + 12, y2), fill=accent)
    draw.text((x1 + 34, y1 + 24), eyebrow, font=fonts.bold(21), fill=accent)
    draw.text((x1 + 34, y1 + 63), value, font=fonts.bold(value_size), fill=INK)
    value_h = text_box(draw, value, fonts.bold(value_size))[1]
    draw.text((x1 + 38, y1 + 82 + value_h), label, font=fonts.bold(25), fill=INK)
    draw_wrapped(
        draw,
        (x1 + 38, y1 + 124 + value_h),
        note,
        fonts.regular(21),
        MUTED,
        x2 - x1 - 72,
        line_gap=5,
        max_lines=2,
    )
    draw.ellipse((x2 - 70, y1 + 28, x2 - 34, y1 + 64), fill=soft)


def draw_ci_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    box: tuple[int, int, int, int],
    method_label: str,
    diff: float,
    ci: list[float],
    accent: str,
    soft: str,
    interpretation: str,
) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, WHITE, radius=26, outline=BORDER, width=2)
    draw.text((x1 + 30, y1 + 22), f"{method_label} 對 ERC", font=fonts.bold(22), fill=accent)
    draw.text((x1 + 30, y1 + 58), fmt_decimal(diff, 3, plus=True), font=fonts.bold(53), fill=INK)
    draw.text((x1 + 30, y1 + 116), "淨夏普差", font=fonts.regular(21), fill=MUTED)
    low, high = ci
    ci_text = f"區間 [{fmt_decimal(low, 3, plus=True)}, {fmt_decimal(high, 3, plus=True)}]"
    draw.text((x1 + 30, y1 + 153), ci_text, font=fonts.bold(20), fill=INK)

    axis_left = x1 + 34
    axis_right = x2 - 34
    axis_y = y1 + 211
    domain_low = min(-0.55, low)
    domain_high = max(0.15, high)

    def scale(value: float) -> int:
        return int(axis_left + (value - domain_low) / (domain_high - domain_low) * (axis_right - axis_left))

    zero_x = scale(0.0)
    draw.line((axis_left, axis_y, axis_right, axis_y), fill=BORDER, width=5)
    draw.line((zero_x, axis_y - 18, zero_x, axis_y + 18), fill=FAINT, width=3)
    draw.line((scale(low), axis_y, scale(high), axis_y), fill=accent, width=9)
    draw.ellipse((scale(diff) - 8, axis_y - 8, scale(diff) + 8, axis_y + 8), fill=accent)
    draw.text((zero_x - 7, axis_y + 22), "0", font=fonts.regular(17), fill=FAINT)
    rounded(draw, (x1 + 28, y2 - 54, x2 - 28, y2 - 18), soft, radius=14)
    draw.text((x1 + 43, y2 - 48), interpretation, font=fonts.bold(19), fill=accent)


def render_results(out_path: Path, data: dict[str, Any], fonts: FontBook) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    experiment_id = str(data_path(data, "experiment_id"))

    erc_sharpe = as_number(data, "net_performance.erc_risk_parity.sharpe")
    herc_sharpe = as_number(data, "net_performance.herc_erc.sharpe")
    minvar_mdd = as_number(data, "net_performance.min_variance.mdd")
    equal_turnover = as_number(data, "net_performance.equal_weight.annual_turnover")
    herc_diff = as_number(data, "tests_vs_erc_risk_parity.herc_erc.sharpe_diff_bootstrap.obs_sharpe_diff")
    herc_ci = list(data_path(data, "tests_vs_erc_risk_parity.herc_erc.sharpe_diff_bootstrap.ci95"))
    nco_diff = as_number(data, "tests_vs_erc_risk_parity.nco_minvar.sharpe_diff_bootstrap.obs_sharpe_diff")
    nco_ci = list(data_path(data, "tests_vs_erc_risk_parity.nco_minvar.sharpe_diff_bootstrap.ci95"))

    draw_dark_header(
        draw,
        fonts,
        "淨績效與正式檢定",
        "前兩名，都是簡單方法",
        "最好的階層式方法仍落後；正式區間也沒有替它證明額外優勢。",
        height=174,
    )

    draw_metric_card(
        draw,
        fonts,
        (48, 208, 500, 470),
        "全場最高淨夏普",
        fmt_decimal(erc_sharpe, 3),
        "ERC 風險平價",
        BLUE,
        BLUE_SOFT,
        "不用樹狀分群，排名第一。",
    )
    draw_metric_card(
        draw,
        fonts,
        (524, 208, 976, 470),
        "階層式方法最高",
        fmt_decimal(herc_sharpe, 3),
        "HERC 階層式",
        ORANGE,
        ORANGE_SOFT,
        "階層式家族中最好，但仍低於 ERC。",
    )
    draw_metric_card(
        draw,
        fonts,
        (1000, 208, 1552, 470),
        "最小最大回撤",
        fmt_percent(minvar_mdd, 1),
        "最小變異",
        TEAL,
        TEAL_SOFT,
        "回撤較淺，卻不是淨夏普冠軍。",
    )

    draw_metric_card(
        draw,
        fonts,
        (48, 494, 500, 894),
        "最低年換手率",
        fmt_percent(equal_turnover, 0),
        "等權重／年",
        GREEN,
        GREEN_SOFT,
        "最簡單的方法，也最少交易。",
        value_size=74,
    )
    draw_ci_card(
        draw,
        fonts,
        (524, 494, 1028, 894),
        "HERC",
        herc_diff,
        herc_ci,
        ORANGE,
        ORANGE_SOFT,
        "區間跨過 0：沒有明確勝負",
    )
    draw_ci_card(
        draw,
        fonts,
        (1052, 494, 1552, 894),
        "NCO",
        nco_diff,
        nco_ci,
        RED,
        RED_SOFT,
        "整段低於 0：顯著落後 ERC",
    )

    rounded(draw, (48, 909, 1552, 940), NAVY, radius=15)
    summary = "K1639：階層式方法沒有同時穩健勝過 ERC 與最小變異"
    summary_w, _ = text_box(draw, summary, fonts.bold(22))
    draw.text(((WIDTH - summary_w) // 2, 913), summary, font=fonts.bold(22), fill=WHITE)
    draw_footer(draw, fonts, experiment_id)
    save_png(image, out_path)


def save_png(image: Image.Image, out_path: Path) -> None:
    if image.size != (WIDTH, HEIGHT):
        raise ValueError(f"錯誤畫布尺寸：{image.size}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", optimize=True, dpi=DPI)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"PNG 未成功寫出：{out_path}")


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main() -> int:
    root = default_repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=root / "experiments/k1639/k1639_results.json",
        help="K1639 results JSON（所有顯示統計量的唯一數字來源）",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="PNG 輸出目錄",
    )
    args = parser.parse_args()

    try:
        data = load_results(args.evidence)
        fonts = load_fonts()
        outputs = [
            ("1_concept.png", render_concept),
            ("2_method.png", render_method),
            ("3_results.png", render_results),
        ]
        for filename, renderer in outputs:
            path = args.out_dir / filename
            renderer(path, data, fonts)
            with Image.open(path) as rendered:
                if rendered.size != (WIDTH, HEIGHT) or rendered.mode not in {"RGB", "RGBA"}:
                    raise RuntimeError(f"PNG 驗證失敗：{path} / {rendered.size} / {rendered.mode}")
            print(f"OK {path.resolve()} ({path.stat().st_size:,} bytes)")
        print(f"FONT regular={fonts.regular_path}")
        print(f"FONT bold={fonts.bold_path}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
