#!/usr/bin/env python3
"""Render K1074 general-reader lazy-pack PNG panels.

All displayed statistics are bound to experiments/k1074/k1074_results.json.
This script uses local Pillow rendering only; it does not call any image model.
"""
from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path("/Users/yhlai0911/Desktop/volpred-research")
RESULTS_PATH = ROOT / "experiments/k1074/k1074_results.json"
README_PATH = ROOT / "experiments/k1074/README.md"
DRAFT_PATH = ROOT / "storage/drafts/k1074_general_draft.md"
OUT_DIR = Path("/tmp/k1074_poster")

WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

WHITE = "#FFFFFF"
INK = "#17202A"
MUTED = "#586270"
FAINT = "#7B8492"
NAVY = "#182A3A"
NAVY_2 = "#22384D"
LINE = "#DCE2EA"
SOFT = "#F4F7FA"
SOFT_2 = "#EEF3F7"
GREEN = "#1F7A4D"
GREEN_SOFT = "#DDEFE5"
BLUE = "#235A97"
BLUE_SOFT = "#E2ECF8"
AMBER = "#A86A16"
AMBER_SOFT = "#F5E6D1"
RED = "#B94743"
RED_SOFT = "#F4DAD8"
VIOLET = "#6956A5"
VIOLET_SOFT = "#E8E3F5"

FONT_REGULAR_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/Noto Sans CJK TC Regular.otf",
]
FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
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


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def require_evidence() -> None:
    missing = [p for p in [RESULTS_PATH, README_PATH, DRAFT_PATH] if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing evidence file(s): " + ", ".join(str(p) for p in missing))


def get_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"Missing results field: {path}")
        cur = cur[part]
    return cur


def metric(data: dict[str, Any], path: str) -> float:
    value = get_path(data, path)
    if not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric field at {path}, got {type(value).__name__}")
    return float(value)


def fmt3(value: float) -> str:
    return f"{value:.3f}"


def fmt1(value: float) -> str:
    return f"{value:.1f}"


def pct0(value: float) -> str:
    return f"{round(value):.0f}%"


def bp_to_pct(bps: float) -> str:
    return f"{bps / 10000:.2%}"


def year_from_date(raw: str) -> str:
    return raw[:4]


def source_line(data: dict[str, Any]) -> str:
    return (
        f"資料來源：experiment {data['experiment_id']}；{data['data_source']}；"
        f"OOS {data['oos_start']} 至 {data['oos_end']}，n={data['n_oos']}"
    )


def _font_has_chars(font: ImageFont.FreeTypeFont, text: str) -> bool:
    missing_mask = font.getmask("\uFFFF", mode="L")
    missing_bytes = bytes(missing_mask)
    missing_size = missing_mask.size
    for ch in set(text):
        if ch in "\n\r\t ":
            continue
        if unicodedata.category(ch).startswith("C") and ch != "\u3000":
            continue
        mask = font.getmask(ch, mode="L")
        if mask.size == (0, 0):
            continue
        if mask.size == missing_size and bytes(mask) == missing_bytes:
            return False
    return True


def choose_fonts(required_text: str) -> FontBook:
    regular_candidates = [Path(p) for p in FONT_REGULAR_CANDIDATES if Path(p).exists()]
    bold_candidates = [Path(p) for p in FONT_BOLD_CANDIDATES if Path(p).exists()]
    for reg in regular_candidates:
        reg_font = ImageFont.truetype(str(reg), size=42)
        if not _font_has_chars(reg_font, required_text):
            continue
        for bold in bold_candidates:
            bold_font = ImageFont.truetype(str(bold), size=42)
            if _font_has_chars(bold_font, required_text):
                return FontBook(reg, bold)
    raise RuntimeError("No installed CJK font can render all required panel text.")


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    if not text:
        return 0, 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        current = ""
        for ch in para:
            candidate = current + ch
            if text_size(draw, candidate, font)[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current.rstrip())
                current = ch.lstrip()
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
) -> int:
    x, y = xy
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += text_size(draw, line or "字", font)[1] + line_gap
    return y


def draw_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    x0, y0, x1, y1 = box
    tw, th = text_size(draw, text, font)
    draw.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2), text, font=font, fill=fill)


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str | None = None,
    width: int = 2,
    radius: int = 8,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def header(draw: ImageDraw.ImageDraw, fonts: FontBook, title: str, subtitle: str, accent: str = GREEN) -> None:
    draw.rectangle((0, 0, WIDTH, 150), fill=NAVY)
    draw.rectangle((0, 150, WIDTH, 164), fill=accent)
    draw.text((74, 42), title, font=fonts.bold(48), fill=WHITE)
    draw_wrapped(draw, (76, 104), subtitle, fonts.regular(25), "#DCE6EF", 1370, line_gap=4)


def footer(draw: ImageDraw.ImageDraw, fonts: FontBook, data: dict[str, Any]) -> None:
    draw.line((72, 948, WIDTH - 72, 948), fill=LINE, width=2)
    draw.text((74, 962), source_line(data), font=fonts.regular(20), fill=FAINT)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str) -> None:
    x0, y0 = start
    x1, y1 = end
    draw.line((x0, y0, x1, y1), fill=color, width=5)
    angle = math.atan2(y1 - y0, x1 - x0)
    head = 17
    left = (x1 - head * math.cos(angle - math.pi / 6), y1 - head * math.sin(angle - math.pi / 6))
    right = (x1 - head * math.cos(angle + math.pi / 6), y1 - head * math.sin(angle + math.pi / 6))
    draw.polygon([(x1, y1), left, right], fill=color)


def render_panel_1(data: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "準 ≠ 賺：一個關於預測模型的實測",
        "統計上更準的波動率預測模型，做成投資策略後、扣掉交易成本反而輸給一個超簡單的規則。",
        accent=GREEN,
    )

    draw.text((78, 212), "從預測模型到投資策略，中間會遇到交易摩擦", font=fonts.bold(34), fill=INK)
    steps = [
        ("預測精度", "模型估計未來市場風險"),
        ("倉位調整", "風險高就縮小部位"),
        ("交易成本", "每次調整都會付出摩擦"),
        ("策略績效", "最後才是投資人拿到的結果"),
    ]
    x = 92
    y = 292
    w = 300
    h = 116
    colors = [BLUE_SOFT, VIOLET_SOFT, AMBER_SOFT, GREEN_SOFT]
    outlines = [BLUE, VIOLET, AMBER, GREEN]
    for i, (name, desc) in enumerate(steps):
        bx = x + i * 366
        rounded(draw, (bx, y, bx + w, y + h), colors[i], outline=outlines[i], width=2)
        draw.text((bx + 24, y + 24), name, font=fonts.bold(31), fill=outlines[i])
        draw_wrapped(draw, (bx + 24, y + 66), desc, fonts.regular(20), MUTED, w - 48, line_gap=4)
        if i < len(steps) - 1:
            arrow(draw, (bx + w + 18, y + h // 2), (bx + 350, y + h // 2), "#96A2B1")

    draw.text((78, 486), "三個白話名詞", font=fonts.bold(34), fill=INK)
    cards = [
        (
            "波動率目標策略",
            "市場越動盪就減倉、越平靜就加倉，把風險維持在固定水準。",
            BLUE,
            BLUE_SOFT,
        ),
        (
            "Net Sharpe",
            "扣掉交易成本後的風險調整報酬，越高越好。",
            GREEN,
            GREEN_SOFT,
        ),
        (
            "周轉率",
            "倉位調整的頻繁程度，越高手續費付越多。",
            AMBER,
            AMBER_SOFT,
        ),
    ]
    for i, (title, body, color, fill) in enumerate(cards):
        x0 = 78 + i * 488
        y0 = 552
        rounded(draw, (x0, y0, x0 + 440, y0 + 268), WHITE, outline=LINE, width=2)
        draw.rectangle((x0, y0, x0 + 440, y0 + 8), fill=color)
        draw.ellipse((x0 + 26, y0 + 34, x0 + 90, y0 + 98), fill=fill, outline=color, width=3)
        draw_centered(draw, (x0 + 26, y0 + 34, x0 + 90, y0 + 98), str(i + 1), fonts.bold(28), color)
        draw.text((x0 + 112, y0 + 42), title, font=fonts.bold(30), fill=INK)
        draw_wrapped(draw, (x0 + 34, y0 + 122), body, fonts.regular(27), MUTED, 372, line_gap=10)

    draw.text((78, 868), "本圖只講框架與名詞；績效數字留到結果頁。", font=fonts.regular(24), fill=FAINT)
    footer(draw, fonts, data)
    out = OUT_DIR / "1_framework.png"
    img.save(out, dpi=DPI)
    return out


def render_panel_2(data: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "怎麼比較的：白話流程",
        "兩個對手用同一批資料、同一套限制、同一個交易成本假設，在同一個樣本外期間比較。",
        accent=BLUE,
    )

    start_year = year_from_date(str(data["oos_start"]))
    end_year = year_from_date(str(data["oos_end"]))
    cap = fmt1(metric(data, "weight_cap"))
    tx_bps = fmt1(metric(data, "tx_bps")).rstrip("0").rstrip(".")
    tx_pct = bp_to_pct(metric(data, "tx_bps"))
    n_oos = int(metric(data, "n_oos"))

    # Main visual rail.
    draw.rectangle((92, 216, 118, 820), fill=NAVY_2)
    for cy, label in [(266, "A"), (446, "B"), (650, "公平")]:
        draw.ellipse((74, cy - 34, 136, cy + 28), fill=WHITE, outline=NAVY_2, width=4)
        draw_centered(draw, (74, cy - 34, 136, cy + 28), label, fonts.bold(24), NAVY_2)

    # Opponent cards.
    rounded(draw, (176, 206, 736, 354), WHITE, outline=BLUE, width=3)
    draw.text((206, 234), "對手A：12/VIX 簡單規則", font=fonts.bold(30), fill=BLUE)
    draw_wrapped(
        draw,
        (206, 284),
        f"倉位 = 12 ÷ 昨日 VIX，上限 {cap} 倍；一個國中生看得懂的除法。",
        fonts.regular(25),
        MUTED,
        484,
        line_gap=7,
    )

    rounded(draw, (790, 206, 1428, 354), WHITE, outline=VIOLET, width=3)
    draw.text((820, 234), "對手B：A4f 精密模型", font=fonts.bold(30), fill=VIOLET)
    draw_wrapped(
        draw,
        (820, 284),
        "GARCH 家族模型；先前實驗已證明它預測波動率的精準度顯著更高。",
        fonts.regular(25),
        MUTED,
        552,
        line_gap=7,
    )

    arrow(draw, (738, 280), (786, 280), "#9AA7B4")

    draw.text((176, 412), "公平條件", font=fonts.bold(35), fill=INK)
    fair = [
        ("同一批資料", "SPY + GLD + VIX"),
        ("同槓桿上限", f"上限 {cap} 倍"),
        ("只用昨天資訊", "昨日訊號決定今日倉位，不偷看未來"),
        ("調倉扣成本", f"每次調倉扣 {tx_bps} 個基點（{tx_pct}）"),
    ]
    for i, (title, body) in enumerate(fair):
        row = i // 2
        col = i % 2
        x0 = 176 + col * 626
        y0 = 474 + row * 126
        rounded(draw, (x0, y0, x0 + 560, y0 + 94), SOFT, outline=LINE, width=2)
        draw.ellipse((x0 + 22, y0 + 23, x0 + 70, y0 + 71), fill=WHITE, outline=GREEN if i != 3 else AMBER, width=3)
        draw_centered(draw, (x0 + 22, y0 + 23, x0 + 70, y0 + 71), str(i + 1), fonts.bold(22), GREEN if i != 3 else AMBER)
        draw.text((x0 + 90, y0 + 18), title, font=fonts.bold(25), fill=INK)
        draw_wrapped(draw, (x0 + 90, y0 + 52), body, fonts.regular(22), MUTED, 430, line_gap=3)

    rounded(draw, (176, 746, 1428, 852), NAVY, outline=None)
    draw.text((206, 774), "樣本", font=fonts.bold(28), fill=WHITE)
    sample = (
        f"SPY + GLD + VIX，{start_year} 到 {end_year} 年共 {n_oos} 個交易日，"
        "涵蓋三次股災。"
    )
    draw_wrapped(draw, (296, 775), sample, fonts.regular(27), "#E6EEF5", 1030, line_gap=6)

    draw.text((176, 884), "這一頁只定義比較方法與條件，不放最後績效結果。", font=fonts.regular(24), fill=FAINT)
    footer(draw, fonts, data)
    out = OUT_DIR / "2_method.png"
    img.save(out, dpi=DPI)
    return out


def bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    value: float,
    max_value: float,
    color: str,
    bg: str = "#E8EDF3",
) -> None:
    rounded(draw, (x, y, x + w, y + h), bg, outline=None, radius=6)
    fill_w = max(8, int(w * value / max_value))
    rounded(draw, (x, y, x + fill_w, y + h), color, outline=None, radius=6)


def render_panel_3(data: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "主要結果：準不一定比較賺",
        "扣掉交易成本後，最簡單的 12/VIX 規則微幅領先；但差距未達嚴格統計顯著。",
        accent=AMBER,
    )

    net_12 = metric(data, "metrics.A_12VIX_net.sharpe")
    net_a4f = metric(data, "metrics.B_A4f_net.sharpe")
    net_gjr = metric(data, "metrics.C_GJR_net.sharpe")
    gross_12 = metric(data, "metrics.A_12VIX_gross.sharpe")
    gross_a4f = metric(data, "metrics.B_A4f_gross.sharpe")
    turn_12 = metric(data, "metrics.A_12VIX_net.annual_notional")
    turn_a4f = metric(data, "metrics.B_A4f_net.annual_notional")
    turnover_lift = (turn_a4f / turn_12 - 1.0) * 100.0
    ci_lo = metric(data, "bootstrap_sharpe_diff.B_A4f_net__minus__A_12VIX_net.ci95_lo")
    ci_hi = metric(data, "bootstrap_sharpe_diff.B_A4f_net__minus__A_12VIX_net.ci95_hi")
    p_val = metric(data, "bootstrap_sharpe_diff.B_A4f_net__minus__A_12VIX_net.p_two_sided")

    # Bento layout.
    card1 = (76, 206, 760, 542)
    card2 = (804, 206, 1524, 542)
    card3 = (76, 574, 760, 824)
    card4 = (804, 574, 1524, 824)
    for box in [card1, card2, card3, card4]:
        rounded(draw, box, WHITE, outline=LINE, width=2)

    # Card 1: net Sharpe.
    x0, y0, x1, y1 = card1
    draw.rectangle((x0, y0, x1, y0 + 8), fill=GREEN)
    draw.text((x0 + 28, y0 + 28), "扣成本後 Net Sharpe", font=fonts.bold(30), fill=INK)
    draw.text((x0 + 28, y0 + 72), "12/VIX 第一名", font=fonts.regular(23), fill=GREEN)
    rows = [("12/VIX", net_12, GREEN), ("A4f", net_a4f, BLUE), ("GJR", net_gjr, FAINT)]
    max_net = max(v for _, v, _ in rows) * 1.04
    for i, (label, value, color) in enumerate(rows):
        yy = y0 + 126 + i * 64
        draw.text((x0 + 28, yy), label, font=fonts.bold(24), fill=INK)
        bar(draw, x0 + 142, yy + 6, 350, 28, value, max_net, color)
        draw.text((x0 + 520, yy - 4), fmt3(value), font=fonts.bold(34), fill=color)
    draw.text((x0 + 28, y1 - 34), "最簡單的規則贏。", font=fonts.bold(25), fill=GREEN)

    # Card 2: turnover.
    x0, y0, x1, y1 = card2
    draw.rectangle((x0, y0, x1, y0 + 8), fill=AMBER)
    draw.text((x0 + 28, y0 + 28), "年化周轉率", font=fonts.bold(30), fill=INK)
    draw.text((x0 + 28, y0 + 72), "精密模型多交易，成本吃光精度優勢", font=fonts.regular(23), fill=MUTED)
    draw.text((x0 + 44, y0 + 148), "A4f", font=fonts.bold(25), fill=INK)
    draw.text((x0 + 44, y0 + 184), f"{fmt1(turn_a4f)}倍", font=fonts.bold(58), fill=AMBER)
    draw.text((x0 + 360, y0 + 148), "12/VIX", font=fonts.bold(25), fill=INK)
    draw.text((x0 + 360, y0 + 184), f"{fmt1(turn_12)}倍", font=fonts.bold(58), fill=BLUE)
    draw.text((x0 + 44, y0 + 272), f"多交易 {pct0(turnover_lift)}", font=fonts.bold(35), fill=RED)
    draw_wrapped(draw, (x0 + 270, y0 + 274), "每次倉位變動，都要付交易成本。", fonts.regular(23), MUTED, 370, line_gap=4)

    # Card 3: gross Sharpe.
    x0, y0, x1, y1 = card3
    draw.rectangle((x0, y0, x1, y0 + 8), fill=BLUE)
    draw.text((x0 + 28, y0 + 28), "沒扣成本前幾乎平手", font=fonts.bold(30), fill=INK)
    draw.text((x0 + 42, y0 + 104), "12/VIX", font=fonts.bold(25), fill=INK)
    draw.text((x0 + 42, y0 + 142), fmt3(gross_12), font=fonts.bold(56), fill=GREEN)
    draw.text((x0 + 338, y0 + 104), "A4f", font=fonts.bold(25), fill=INK)
    draw.text((x0 + 338, y0 + 142), fmt3(gross_a4f), font=fonts.bold(56), fill=BLUE)
    draw.text((x0 + 28, y1 - 48), "預測精度沒有自動轉成交易優勢。", font=fonts.regular(25), fill=MUTED)

    # Card 4: statistical honesty.
    x0, y0, x1, y1 = card4
    draw.rectangle((x0, y0, x1, y0 + 8), fill=RED)
    draw.text((x0 + 28, y0 + 28), "誠實補充", font=fonts.bold(30), fill=INK)
    draw_wrapped(
        draw,
        (x0 + 28, y0 + 82),
        "此差距未達嚴格統計顯著；信賴區間跨零。",
        fonts.regular(25),
        MUTED,
        620,
        line_gap=7,
    )
    draw.text((x0 + 28, y0 + 146), f"CI [{ci_lo:+.3f}, {ci_hi:+.3f}]", font=fonts.bold(35), fill=RED)
    draw.text((x0 + 28, y0 + 196), f"bootstrap p 約 {p_val:.2f}", font=fonts.bold(35), fill=RED)
    draw_wrapped(
        draw,
        (x0 + 28, y0 + 254),
        "精確講法：微幅領先，仍可能是雜訊。",
        fonts.regular(22),
        MUTED,
        620,
        line_gap=5,
    )

    rounded(draw, (76, 858, 1524, 928), NAVY, outline=None)
    draw_centered(
        draw,
        (76, 858, 1524, 928),
        "預測更準 ≠ 策略更賺；升級模型前先算周轉與成本",
        fonts.bold(34),
        WHITE,
    )
    footer(draw, fonts, data)
    out = OUT_DIR / "3_results.png"
    img.save(out, dpi=DPI)
    return out


def required_text(data: dict[str, Any]) -> str:
    pieces = [
        "準 ≠ 賺：一個關於預測模型的實測",
        "統計上更準的波動率預測模型，做成投資策略後、扣掉交易成本反而輸給一個超簡單的規則。",
        "波動率目標策略 市場越動盪就減倉、越平靜就加倉，把風險維持在固定水準。",
        "Net Sharpe 扣掉交易成本後的風險調整報酬，越高越好。",
        "周轉率 倉位調整的頻繁程度，越高手續費付越多。",
        "怎麼比較的：白話流程 對手A：12/VIX 簡單規則 倉位 = 12 ÷ 昨日 VIX，上限 1.5 倍",
        "對手B：A4f 精密模型 GARCH 家族模型 只用昨天資訊 不偷看未來 調倉扣成本 個基點（0.05%）",
        "SPY + GLD + VIX 2013 到 2026 年共 3338 個交易日，涵蓋三次股災。",
        "主要結果：準不一定比較賺 扣成本後 Net Sharpe 年化周轉率 沒扣成本前幾乎平手 誠實補充",
        "信賴區間跨零 bootstrap p 約 簡單規則微幅領先、無法排除是雜訊。",
        source_line(data),
    ]
    return "\n".join(pieces)


def main() -> None:
    require_evidence()
    data = load_json(RESULTS_PATH)
    if data.get("experiment_id") != "K1074":
        raise ValueError(f"Unexpected experiment_id: {data.get('experiment_id')}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fonts = choose_fonts(required_text(data))
    outputs = [
        render_panel_1(data, fonts),
        render_panel_2(data, fonts),
        render_panel_3(data, fonts),
    ]
    for path in outputs:
        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError(f"Render failed or empty file: {path}")
        print(path)


if __name__ == "__main__":
    main()
