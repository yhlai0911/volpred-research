#!/usr/bin/env python3
"""Render data-bound VolPred lazypack panels for K267.

The displayed numbers are read from
``experiments/k267/k267_session_summary_results.json``.  The article prose and
README were reviewed for context, but no panel number is copied from prose.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
RESULTS_PATH = REPO_ROOT / "experiments/k267/k267_session_summary_results.json"
README_PATH = REPO_ROOT / "experiments/k267/README.md"
OUT_DIR = SCRIPT_DIR

os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".mplconfig"))
(SCRIPT_DIR / ".mplconfig").mkdir(parents=True, exist_ok=True)

import matplotlib as mpl  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402


mpl.rcParams["font.sans-serif"] = ["Heiti TC", "Arial Unicode MS"]
mpl.rcParams["axes.unicode_minus"] = False

WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

INK = "#182433"
MUTED = "#586575"
FAINT = "#7A8797"
WHITE = "#FFFFFF"
PANEL_BG = "#FFFFFF"
CARD = "#FBFCFE"
BORDER = "#DCE3EC"
NAVY = "#14263B"
NAVY_2 = "#21384F"
TEAL = "#167C7B"
TEAL_SOFT = "#DDEFEF"
BLUE = "#28639C"
BLUE_SOFT = "#E2ECF8"
AMBER = "#B36B16"
AMBER_SOFT = "#F5E8D6"
GREEN = "#2F7E52"
GREEN_SOFT = "#DFEFE6"
RED = "#BD433A"
RED_SOFT = "#F3DEDC"
SLATE_SOFT = "#EEF2F6"

FONT_CANDIDATES = [
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
]


@dataclass(frozen=True)
class Fonts:
    path: Path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.path), size=size)


@dataclass(frozen=True)
class Evidence:
    experiment_id: str
    total_experiments: int
    k_range: str
    strategy_search: int
    investor_guide: int
    vol_prediction: int
    methodology: int
    cross_market: int
    initial_claims: int
    survived_validation: int
    strategies_tested: int
    strategies_that_beat_50_50: int
    null_rate_percent: float
    self_corrections: int


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_path(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        cur = cur[part]
    return cur


def first_font() -> Fonts:
    for path in FONT_CANDIDATES:
        if path.exists():
            return Fonts(path)
    raise RuntimeError("找不到可用 CJK 字型；請安裝 Heiti TC 或 Arial Unicode MS。")


def load_evidence() -> Evidence:
    if not README_PATH.exists():
        raise FileNotFoundError(README_PATH)
    raw = load_json(RESULTS_PATH)
    ev = Evidence(
        experiment_id=str(get_path(raw, "experiment_id")),
        total_experiments=int(get_path(raw, "inventory.total_experiments")),
        k_range=str(get_path(raw, "inventory.k_range")),
        strategy_search=int(get_path(raw, "inventory.by_topic.strategy_search.count")),
        investor_guide=int(get_path(raw, "inventory.by_topic.investor_guide.count")),
        vol_prediction=int(get_path(raw, "inventory.by_topic.vol_prediction.count")),
        methodology=int(get_path(raw, "inventory.by_topic.methodology.count")),
        cross_market=int(get_path(raw, "inventory.by_topic.cross_market.count")),
        initial_claims=int(get_path(raw, "session_statistics.harvey_threshold_passes.initial_claims")),
        survived_validation=int(get_path(raw, "session_statistics.harvey_threshold_passes.survived_validation")),
        strategies_tested=int(get_path(raw, "session_statistics.strategies_tested")),
        strategies_that_beat_50_50=int(get_path(raw, "session_statistics.strategies_that_beat_50_50")),
        null_rate_percent=float(get_path(raw, "session_statistics.null_rate_percent")),
        self_corrections=int(get_path(raw, "session_statistics.self_corrections")),
    )

    assert ev.experiment_id == "K267"
    assert ev.total_experiments == 84
    assert ev.strategy_search == 25
    assert ev.investor_guide == 24
    assert ev.vol_prediction == 22
    assert ev.methodology == 8
    assert ev.cross_market == 5
    assert ev.initial_claims == 6
    assert ev.survived_validation == 2
    assert ev.strategies_tested == 25
    assert ev.strategies_that_beat_50_50 == 0
    assert ev.null_rate_percent == 44.0
    assert ev.self_corrections == 3
    return ev


def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (WIDTH, HEIGHT), PANEL_BG)
    return img, ImageDraw.Draw(img)


def bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    font: ImageFont.FreeTypeFont,
    fill: str = INK,
    anchor: str | None = None,
) -> None:
    draw.text(xy, value, font=font, fill=fill, anchor=anchor)


def wrap_text(
    draw: ImageDraw.ImageDraw,
    value: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in value:
        trial = current + ch
        if bbox(draw, trial, font)[0] <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = ch.lstrip()
    if current:
        lines.append(current)
    return lines


def wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    line_gap: int,
    fill: str = MUTED,
) -> int:
    x, y = xy
    for line in wrap_text(draw, value, font, max_width):
        text(draw, (x, y), line, font, fill)
        y += font.size + line_gap
    return y


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str = BORDER,
    width: int = 2,
    radius: int = 8,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def footer(draw: ImageDraw.ImageDraw, fonts: Fonts, ev: Evidence) -> None:
    text(
        draw,
        (80, 942),
        f"資料來源：experiment {ev.experiment_id}；結果檔 experiments/k267/k267_session_summary_results.json",
        fonts.regular(25),
        FAINT,
    )


def draw_topic_icon(draw: ImageDraw.ImageDraw, kind: str, cx: int, cy: int, color: str) -> None:
    if kind == "search":
        draw.ellipse((cx - 30, cy - 30, cx + 18, cy + 18), outline=color, width=6)
        draw.line((cx + 12, cy + 12, cx + 42, cy + 42), fill=color, width=6)
    elif kind == "guide":
        draw.rectangle((cx - 36, cy - 28, cx + 30, cy + 30), outline=color, width=6)
        draw.line((cx - 18, cy - 12, cx + 15, cy - 12), fill=color, width=5)
        draw.line((cx - 18, cy + 6, cx + 15, cy + 6), fill=color, width=5)
    elif kind == "vol":
        pts = [(cx - 42, cy + 26), (cx - 24, cy - 8), (cx - 7, cy + 12), (cx + 12, cy - 22), (cx + 38, cy + 14)]
        draw.line(pts, fill=color, width=7, joint="curve")
    elif kind == "method":
        draw.rectangle((cx - 34, cy - 34, cx + 34, cy + 34), outline=color, width=6)
        draw.line((cx - 18, cy - 2, cx - 4, cy + 14, cx + 22, cy - 18), fill=color, width=6)
    elif kind == "market":
        draw.ellipse((cx - 36, cy - 36, cx + 36, cy + 36), outline=color, width=6)
        draw.arc((cx - 25, cy - 36, cx + 25, cy + 36), 90, 270, fill=color, width=4)
        draw.arc((cx - 25, cy - 36, cx + 25, cy + 36), -90, 90, fill=color, width=4)
        draw.line((cx - 34, cy, cx + 34, cy), fill=color, width=4)


def topic_card(
    draw: ImageDraw.ImageDraw,
    fonts: Fonts,
    box: tuple[int, int, int, int],
    label: str,
    count: int,
    note: str,
    color: str,
    soft: str,
    icon: str,
) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, CARD, BORDER)
    draw.rectangle((x1, y1, x1 + 14, y2), fill=color)
    draw.ellipse((x2 - 114, y1 + 30, x2 - 36, y1 + 108), fill=soft, outline=color, width=2)
    draw_topic_icon(draw, icon, x2 - 74, y1 + 68, color)
    text(draw, (x1 + 42, y1 + 36), label, fonts.bold(36), INK)
    text(draw, (x1 + 42, y1 + 92), f"{count}", fonts.bold(96), color)
    text(draw, (x1 + 154, y1 + 128), "個實驗", fonts.regular(32), MUTED)
    wrapped(draw, (x1 + 42, y1 + 182), note, fonts.regular(25), x2 - x1 - 84, 8, MUTED)


def panel_1(ev: Evidence, fonts: Fonts) -> Path:
    img, draw = new_canvas()
    text(draw, (80, 58), f"{ev.total_experiments} 個實驗留下的研究地圖", fonts.bold(62), INK)
    text(draw, (82, 132), f"{ev.k_range} 的描述性主題盤點", fonts.regular(30), MUTED)

    rounded(draw, (80, 190, 505, 570), NAVY, NAVY)
    text(draw, (122, 235), "總樣本", fonts.regular(34), "#C9D6E3")
    text(draw, (122, 300), f"{ev.total_experiments}", fonts.bold(142), WHITE)
    text(draw, (332, 392), "個實驗", fonts.regular(38), "#C9D6E3")
    draw.line((122, 458, 458, 458), fill="#6D7F91", width=3)
    wrapped(draw, (122, 492), "只整理研究力氣分布；不等於投資結論。", fonts.regular(26), 330, 8, "#E5EDF5")

    topic_card(
        draw,
        fonts,
        (535, 190, 990, 430),
        "策略搜尋",
        ev.strategy_search,
        "最多實驗放在新策略、輪動、配對與風險開關。",
        TEAL,
        TEAL_SOFT,
        "search",
    )
    topic_card(
        draw,
        fonts,
        (1018, 190, 1520, 430),
        "投資指南",
        ev.investor_guide,
        "配置、再平衡、稅務、退休與行為面向。",
        BLUE,
        BLUE_SOFT,
        "guide",
    )
    topic_card(
        draw,
        fonts,
        (535, 458, 850, 728),
        "波動預測",
        ev.vol_prediction,
        "測 VIX 以外的預測訊號與資產邊界。",
        AMBER,
        AMBER_SOFT,
        "vol",
    )
    topic_card(
        draw,
        fonts,
        (878, 458, 1193, 728),
        "方法檢查",
        ev.methodology,
        "驗證、修正與防止樣本外誤判。",
        GREEN,
        GREEN_SOFT,
        "method",
    )
    topic_card(
        draw,
        fonts,
        (1221, 458, 1520, 728),
        "跨市場",
        ev.cross_market,
        "跨資產、宏觀與市場連動研究。",
        RED,
        RED_SOFT,
        "market",
    )

    rounded(draw, (80, 760, 1520, 890), SLATE_SOFT, "#D7E0EA")
    text(draw, (120, 800), "註記", fonts.bold(31), INK)
    wrapped(
        draw,
        (222, 794),
        "依 results JSON count 欄位，這是描述性人工盤點；同一實驗可能在研究脈絡上有交叉標籤，圖中只呈現 session-level count。",
        fonts.regular(28),
        1210,
        10,
        MUTED,
    )
    footer(draw, fonts, ev)

    path = OUT_DIR / "1_research_map.png"
    img.save(path, dpi=DPI)
    return path


def metric_block(
    draw: ImageDraw.ImageDraw,
    fonts: Fonts,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    suffix: str,
    color: str,
    soft: str,
    note: str,
) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, CARD, BORDER)
    draw.rectangle((x1, y1, x2, y1 + 10), fill=color)
    text(draw, (x1 + 34, y1 + 40), label, fonts.bold(34), INK)
    value_font = fonts.bold(92)
    suffix_font = fonts.regular(31)
    value_top = y1 + 94
    text(draw, (x1 + 34, value_top), value, value_font, color)
    text(draw, (x1 + 34 + bbox(draw, value, value_font)[0] + 22, value_top + 48), suffix, suffix_font, MUTED)
    wrapped(draw, (x1 + 34, y1 + 190), note, fonts.regular(25), x2 - x1 - 68, 8, MUTED)


def panel_2(ev: Evidence, fonts: Fonts) -> Path:
    img, draw = new_canvas()
    draw.rectangle((0, 0, WIDTH, 170), fill=NAVY)
    text(draw, (80, 48), "漂亮結果先過濾", fonts.bold(62), WHITE)
    text(draw, (82, 122), "先看驗證後剩下什麼，再談研究線索是否值得追。", fonts.regular(29), "#C9D6E3")

    rounded(draw, (80, 220, 940, 780), CARD, BORDER)
    text(draw, (124, 264), "初步強結果到驗證後保留", fonts.bold(38), INK)
    text(draw, (124, 318), "初步通過 Harvey 門檻的聲稱，經後續驗證篩選。", fonts.regular(25), MUTED)

    draw.rounded_rectangle((180, 392, 840, 510), radius=8, fill=BLUE_SOFT, outline=BLUE, width=3)
    text(draw, (234, 420), "初步強結果", fonts.bold(34), INK)
    text(draw, (695, 405), f"{ev.initial_claims}", fonts.bold(74), BLUE, anchor="ma")
    text(draw, (763, 445), "個", fonts.regular(30), BLUE)

    draw.polygon([(500, 535), (545, 535), (522, 588)], fill=FAINT)
    draw.rounded_rectangle((295, 610, 725, 728), radius=8, fill=GREEN_SOFT, outline=GREEN, width=3)
    text(draw, (342, 638), "較穩線索", fonts.bold(34), INK)
    text(draw, (584, 622), f"{ev.survived_validation}", fonts.bold(78), GREEN)
    text(draw, (662, 664), "個", fonts.regular(30), GREEN)
    text(draw, (126, 730), "驗證後只保留 2 個較穩線索。", fonts.regular(27), MUTED)

    metric_block(
        draw,
        fonts,
        (990, 220, 1520, 455),
        "策略搜尋",
        f"{ev.strategies_tested}",
        "個測試",
        TEAL,
        TEAL_SOFT,
        "同一輪策略題目先進入共同比較框架。",
    )
    metric_block(
        draw,
        fonts,
        (990, 505, 1520, 780),
        "穩定勝過 50/50",
        f"{ev.strategies_that_beat_50_50}",
        "個",
        RED,
        RED_SOFT,
        "在風險調整且具統計支撐的口徑下，未找到足夠證據。",
    )

    rounded(draw, (80, 820, 1520, 900), SLATE_SOFT, "#D7E0EA")
    text(
        draw,
        (120, 846),
        "口徑：這是研究驗證摘要，不是投資建議；也不宣稱 50/50 永遠最佳。",
        fonts.regular(29),
        MUTED,
    )
    footer(draw, fonts, ev)

    path = OUT_DIR / "2_validation_filter.png"
    img.save(path, dpi=DPI)
    return path


def checklist_item(
    draw: ImageDraw.ImageDraw,
    fonts: Fonts,
    y: int,
    num: int,
    title: str,
    note: str,
) -> None:
    draw.ellipse((690, y, 756, y + 66), fill=NAVY)
    text(draw, (723, y + 33), str(num), fonts.bold(33), WHITE, anchor="mm")
    text(draw, (790, y + 2), title, fonts.bold(40), INK)
    wrapped(draw, (792, y + 56), note, fonts.regular(27), 640, 8, MUTED)


def panel_3(ev: Evidence, fonts: Fonts) -> Path:
    img, draw = new_canvas()
    text(draw, (80, 58), "讀者該怎麼用", fonts.bold(62), INK)
    text(draw, (82, 132), "把研究地圖轉成可重複的檢查順序。", fonts.regular(30), MUTED)

    draw.rectangle((80, 195, 102, 838), fill=NAVY)
    text(draw, (132, 205), "先留下會阻止自己誤判的規則", fonts.bold(38), INK)
    wrapped(
        draw,
        (132, 266),
        f"{ev.total_experiments} 個實驗最實用的部分，不是下一個神奇訊號，而是哪些漂亮結果需要被降級、暫停或重算。",
        fonts.regular(29),
        450,
        10,
        MUTED,
    )

    draw.rounded_rectangle((132, 430, 585, 620), radius=8, fill=RED_SOFT, outline=RED, width=3)
    text(draw, (168, 460), "無效率", fonts.bold(34), INK)
    text(draw, (168, 510), f"{ev.null_rate_percent:.0f}%", fonts.bold(98), RED)
    text(draw, (362, 560), "無效率", fonts.regular(28), RED)

    draw.rounded_rectangle((132, 654, 585, 838), radius=8, fill=BLUE_SOFT, outline=BLUE, width=3)
    text(draw, (168, 684), "自我修正", fonts.bold(34), INK)
    text(draw, (168, 732), f"{ev.self_corrections}", fonts.bold(96), BLUE)
    text(draw, (282, 784), "次", fonts.regular(36), BLUE)
    wrapped(draw, (340, 715), "把推翻舊結論的紀錄留在流程裡。", fonts.regular(28), 190, 8, MUTED)

    checklist_item(
        draw,
        fonts,
        230,
        1,
        "先比簡單基準",
        "新規則要先證明自己值得增加複雜度。",
    )
    checklist_item(
        draw,
        fonts,
        420,
        2,
        "扣成本與換期間後再信",
        "交易成本、不同期間與完整樣本是漂亮結果的基本壓力測試。",
    )
    checklist_item(
        draw,
        fonts,
        630,
        3,
        "把無效結果和自我修正留下來",
        "失敗題目能減少重複犯錯；被推翻的結論也要能回溯。",
    )

    draw.line((670, 838, 1480, 838), fill=BORDER, width=3)
    text(draw, (690, 865), "重點：先有停損清單，再考慮新增訊號。", fonts.bold(30), INK)
    footer(draw, fonts, ev)

    path = OUT_DIR / "3_reader_checklist.png"
    img.save(path, dpi=DPI)
    return path


def verify(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.stat().st_size <= 0:
            raise RuntimeError(f"empty PNG: {path}")
        with Image.open(path) as img:
            if img.size != (WIDTH, HEIGHT):
                raise RuntimeError(f"unexpected size for {path}: {img.size}")
            extrema = img.convert("L").getextrema()
            if extrema == (255, 255):
                raise RuntimeError(f"blank white PNG: {path}")


def main() -> None:
    fonts = first_font()
    ev = load_evidence()
    paths = [panel_1(ev, fonts), panel_2(ev, fonts), panel_3(ev, fonts)]
    verify(paths)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
