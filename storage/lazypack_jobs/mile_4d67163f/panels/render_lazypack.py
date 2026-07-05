#!/usr/bin/env python3
"""Render K1633 VolPred lazypack PNG panels with local data-bound tooling.

This script deliberately uses Pillow only. It does not call any image
generation model. Every numeric statistic shown in the panels is read from
``experiments/k1633/k1633_results.json`` and formatted at render time.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

PANEL_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = REPO_ROOT / "experiments/k1633/k1633_results.json"
README_PATH = REPO_ROOT / "experiments/k1633/README.md"

WHITE = "#FFFFFF"
INK = "#172033"
MUTED = "#53616F"
FAINT = "#8793A3"
NAVY = "#111827"
NAVY_2 = "#1F2937"
BLUE = "#1D4E89"
BLUE_SOFT = "#E7F0FA"
TEAL = "#0E7C7B"
TEAL_SOFT = "#E0F2F1"
AMBER = "#B7791F"
AMBER_SOFT = "#FFF3D6"
RED = "#B42318"
RED_SOFT = "#FDE8E4"
GREEN = "#2F855A"
GREEN_SOFT = "#E4F4EA"
LILAC_SOFT = "#F0ECFF"
LINE = "#D9E1EC"
PANEL_BG = "#F7F9FC"

FONT_REGULAR_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
    "/Library/Fonts/Noto Sans CJK TC Regular.otf",
]
FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/PingFang.ttc",
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


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def first_existing(paths: list[str]) -> Path | None:
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    return None


def font_covers_text(font_path: Path, text: str) -> bool:
    """Best-effort glyph coverage check using fontTools when available."""
    chars = {
        ord(ch)
        for ch in text
        if ch.strip() and unicodedata.category(ch)[0] not in {"C"}
    }
    if not chars:
        return True
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except Exception:
        return True

    try:
        if font_path.suffix.lower() == ".ttc":
            collection = TTCollection(str(font_path))
            fonts = collection.fonts
        else:
            fonts = [TTFont(str(font_path), lazy=True)]
        for font in fonts:
            cmap: set[int] = set()
            for table in font["cmap"].tables:
                cmap.update(table.cmap.keys())
            if chars.issubset(cmap):
                return True
        return False
    except Exception:
        return True


def load_fonts(required_text: str) -> FontBook:
    regular = first_existing(FONT_REGULAR_CANDIDATES)
    bold = first_existing(FONT_BOLD_CANDIDATES)
    if regular is None or bold is None:
        raise RuntimeError("找不到可用的繁體中文 CJK 字型。")
    if not font_covers_text(regular, required_text):
        raise RuntimeError(f"字型缺字，請換 CJK 字型：{regular}")
    return FontBook(regular_path=regular, bold_path=bold)


def pct(value: float, digits: int = 1, signed: bool = False) -> str:
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value * 100:.{digits}f}%"


def pp(value: float, digits: int = 0, signed: bool = True) -> str:
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value * 100:.{digits}f} 個百分點"


def comma_int(value: int | float) -> str:
    return f"{int(value):,}"


def period_zh(period: str) -> str:
    return period.replace(" .. ", " 至 ")


def draw_round_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str | None = None,
    width: int = 1,
    radius: int = 6,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text_len(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=font)


def split_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_./:+%#^=-]+|[\s]+|.", text)


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
            if token == "":
                continue
            candidate = current + token
            if current and text_len(draw, candidate, font) > max_width:
                lines.append(current.rstrip())
                current = token.lstrip()
            else:
                current = candidate
        if current.strip():
            lines.append(current.rstrip())
    return lines or [""]


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
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + line_gap
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text(
        (left + (right - left - w) / 2, top + (bottom - top - h) / 2 - 2),
        text,
        font=font,
        fill=fill,
    )


def draw_header(draw: ImageDraw.ImageDraw, fonts: FontBook, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, 118), fill=NAVY)
    draw.text((76, 30), title, font=fonts.bold(46), fill=WHITE)
    draw.text((76, 82), subtitle, font=fonts.regular(22), fill="#C7D2E1")
    draw.rectangle((0, 118, WIDTH, 124), fill=TEAL)


def draw_footer(draw: ImageDraw.ImageDraw, fonts: FontBook) -> None:
    draw.line((76, 928, WIDTH - 76, 928), fill=LINE, width=2)
    draw.text(
        (76, 946),
        "資料來源：experiment K1633；數字取自 k1633_results.json，期間與方法說明見 K1633 README。",
        font=fonts.regular(20),
        fill=MUTED,
    )


def make_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    return img, draw


def panel_1(data: dict[str, Any], fonts: FontBook) -> Image.Image:
    img, draw = make_canvas()
    draw_header(
        draw,
        fonts,
        "VIX 破 30 抄底迷思",
        "半真：方向多半對，但大多只是搭上長期上漲的順風車",
    )

    question = "核心問題：VIX 破 30 就閉眼進場抄底，真的比隨便哪一天進場多賺嗎？"
    explain = "白話拆解：要分清楚兩件事——SPY 長期本來就漲（隨便進場放久也常賺），和「別人最恐慌時進場」有沒有額外溢酬。"
    verdict = "一句話：半真。方向對但幅度小，大多只是搭上長期上漲的順風車。"

    draw_wrapped(draw, (84, 158), question, fonts.bold(44), INK, 1380, line_gap=10)

    draw_round_rect(draw, (76, 292, 1524, 384), BLUE_SOFT, outline="#C7D8EC")
    draw_wrapped(draw, (112, 314), explain, fonts.regular(27), INK, 1372, line_gap=8)

    box_y = 430
    draw_round_rect(draw, (76, box_y, 748, 704), WHITE, outline=LINE, width=2)
    draw_round_rect(draw, (852, box_y, 1524, 704), WHITE, outline=LINE, width=2)
    draw.rectangle((76, box_y, 748, box_y + 10), fill=BLUE)
    draw.rectangle((852, box_y, 1524, box_y + 10), fill=TEAL)

    draw.text((112, box_y + 38), "市場順風車", font=fonts.bold(34), fill=BLUE)
    draw.text((888, box_y + 38), "恐慌溢酬", font=fonts.bold(34), fill=TEAL)
    draw_wrapped(
        draw,
        (112, box_y + 94),
        "SPY 長期本來就漲；隨便進場、放久一點，勝率本來就容易超過五成。",
        fonts.regular(27),
        INK,
        585,
        line_gap=9,
    )
    draw_wrapped(
        draw,
        (888, box_y + 94),
        "真正要問的是：恐慌當天進場，是否比無條件隨機進場多出額外報酬？",
        fonts.regular(27),
        INK,
        585,
        line_gap=9,
    )
    draw.line((772, box_y + 54, 828, box_y + 54), fill=FAINT, width=4)
    draw.polygon([(828, box_y + 54), (810, box_y + 42), (810, box_y + 66)], fill=FAINT)

    draw_round_rect(draw, (76, 760, 1524, 890), NAVY_2, outline=NAVY_2)
    draw_wrapped(draw, (114, 795), verdict, fonts.bold(37), WHITE, 1360, line_gap=10)
    draw.text((114, 854), "讀法：不要只問「有沒有賺」，要問「有沒有扣掉市場本來會漲之後的增量」。", font=fonts.regular(23), fill="#CBD5E1")

    draw_footer(draw, fonts)
    return img


def panel_2(data: dict[str, Any], fonts: FontBook) -> Image.Image:
    img, draw = make_canvas()
    draw_header(
        draw,
        fonts,
        "怎麼檢驗 VIX 抄底說",
        "同一天期、同價格序列，事件進場和隨機進場才公平",
    )

    data_cfg = data["data"]
    config = data["config"]
    thresholds = config["thresholds"]
    horizons = config["horizons"]
    n_cells = len(thresholds) * len(horizons)
    events = data["events"]

    strip_y = 148
    strip_items = [
        ("資料期間", period_zh(data_cfg["period"])),
        ("交易日", f"{comma_int(data_cfg['n_trading_days'])} 個"),
        ("門檻", " / ".join(str(x) for x in thresholds)),
        ("組合", f"{len(thresholds)} 門檻 × {len(horizons)} 天期 = {n_cells} 種"),
    ]
    strip_w = 344
    for i, (label, value) in enumerate(strip_items):
        x = 76 + i * (strip_w + 16)
        draw_round_rect(draw, (x, strip_y, x + strip_w, strip_y + 74), PANEL_BG, outline=LINE)
        draw.text((x + 18, strip_y + 13), label, font=fonts.regular(19), fill=MUTED)
        draw.text((x + 18, strip_y + 39), value, font=fonts.bold(24), fill=INK)

    step_texts = [
        f"資料：SPY {period_zh(data_cfg['period'])}，共 {comma_int(data_cfg['n_trading_days'])} 個交易日；恐慌指數 VIX 由下往上首次穿越 {' / '.join(str(x) for x in thresholds)} 當作進場事件。",
        f"去叢集：同一場恐慌只算一次（距上次事件至少 {data_cfg['de_cluster_cooldown_trading_days']} 個交易日）。實際事件數：破 30 有 {events['30']['n_events_raw_decluster']} 次、破 35 有 {events['35']['n_events_raw_decluster']} 次、破 40 只有 {events['40']['n_events_raw_decluster']} 次。",
        "對照組：把樣本內每一天都當成一次進場（無條件 baseline），用完全相同的天期與價格序列。兩邊之差才是恐慌帶來的額外好處。",
        "時間順序：進場點固定在訊號當天收盤，往後看 5 / 10 / 20 / 60 天報酬，不偷看未來。",
        f"嚴格把關：用處理重疊窗口的穩健統計，並對 {n_cells} 種組合（3 門檻 × 4 天期）加一層多重檢定校正，去掉「測很多次剛好中」的運氣成分。",
    ]
    colors = [BLUE, TEAL, AMBER, GREEN, RED]
    softs = [BLUE_SOFT, TEAL_SOFT, AMBER_SOFT, GREEN_SOFT, RED_SOFT]
    y = 250
    for idx, text in enumerate(step_texts, start=1):
        top = y + (idx - 1) * 128
        draw_round_rect(draw, (76, top, 1524, top + 108), WHITE, outline=LINE, width=2)
        draw.rectangle((76, top, 1524, top + 8), fill=colors[idx - 1])
        draw.ellipse((106, top + 28, 166, top + 88), fill=softs[idx - 1], outline=colors[idx - 1], width=2)
        draw_centered_text(draw, (106, top + 28, 166, top + 88), str(idx), fonts.bold(28), colors[idx - 1])
        draw_wrapped(draw, (194, top + 24), text, fonts.regular(25), INK, 1278, line_gap=7)
        if idx < len(step_texts):
            cx = 800
            draw.line((cx, top + 110, cx, top + 126), fill=FAINT, width=2)
            draw.polygon([(cx, top + 128), (cx - 8, top + 116), (cx + 8, top + 116)], fill=FAINT)

    draw_footer(draw, fonts)
    return img


def panel_3(data: dict[str, Any], fonts: FontBook) -> Image.Image:
    img, draw = make_canvas()
    draw_header(
        draw,
        fonts,
        "結果：方向對，但不是閉眼致富",
        "恐慌溢酬比較像三個月慢速回復，不是隔天立刻反彈",
    )

    baseline = data["baseline"]
    verdict = data["verdict"]["multiple_testing"]
    events = data["events"]
    per_cell = data["verdict"]["per_cell"]

    base_h5 = baseline["5"]["win_rate"]
    base_h60 = baseline["60"]["win_rate"]
    h5_thr30 = per_cell["thr30_H5"]
    h60_values = {
        30: events["30"]["horizons"]["60"]["excess_mean_vs_baseline"],
        35: events["35"]["horizons"]["60"]["excess_mean_vs_baseline"],
        40: events["40"]["horizons"]["60"]["excess_mean_vs_baseline"],
    }

    top_y = 148
    cards = [
        (76, top_y, 500, top_y + 178, BLUE_SOFT, BLUE, "先看底：隨便進場", f"{pct(base_h5)} / {pct(base_h60)}", "放 5 天 / 60 天勝率"),
        (538, top_y, 962, top_y + 178, TEAL_SOFT, TEAL, "方向幾乎一致", f"{verdict['n_cells_positive_excess']} / {verdict['n_cells']}", "超額報酬為正"),
        (1000, top_y, 1524, top_y + 178, RED_SOFT, RED, "嚴格多重檢定", f"{len(verdict['bh_fdr_0.05_survivors'])} 格", "FDR 5% 個別存活"),
    ]
    for x1, y1, x2, y2, fill, color, label, value, sub in cards:
        draw_round_rect(draw, (x1, y1, x2, y2), fill, outline="#D0D8E3", width=2)
        draw.text((x1 + 24, y1 + 22), label, font=fonts.bold(27), fill=color)
        draw.text((x1 + 24, y1 + 70), value, font=fonts.bold(52), fill=INK)
        draw.text((x1 + 24, y1 + 135), sub, font=fonts.regular(22), fill=MUTED)

    draw_wrapped(
        draw,
        (86, 352),
        f"先看底：完全不管 VIX、隨便一天進場的勝率本來就高——放 5 天 {pct(base_h5)}、放 60 天 {pct(base_h60)}。",
        fonts.regular(25),
        INK,
        1400,
        line_gap=8,
    )

    left_box = (76, 420, 740, 660)
    draw_round_rect(draw, left_box, WHITE, outline=LINE, width=2)
    draw.rectangle((left_box[0], left_box[1], left_box[2], left_box[1] + 8), fill=AMBER)
    draw.text((112, 452), "短天期最吸睛：破 30 隔一週", font=fonts.bold(29), fill=AMBER)
    draw.text((112, 506), pct(h5_thr30["excess_mean"], digits=1, signed=True), font=fonts.bold(58), fill=INK)
    draw.text((334, 524), f"勝率贏隨機約 {pp(h5_thr30['win_vs_base'])}", font=fonts.bold(26), fill=INK)
    draw.text((112, 590), "但用最嚴格的多重檢定後：", font=fonts.regular(24), fill=MUTED)
    draw.text((112, 624), "沒有任何一格單獨存活。", font=fonts.regular(24), fill=MUTED)

    right_box = (780, 420, 1524, 660)
    draw_round_rect(draw, right_box, WHITE, outline=LINE, width=2)
    draw.rectangle((right_box[0], right_box[1], right_box[2], right_box[1] + 8), fill=TEAL)
    draw.text((816, 452), "三個月（60 天）慢速回復", font=fonts.bold(29), fill=TEAL)
    chart_x = 930
    chart_y = 520
    chart_w = 420
    chart_h = 96
    max_v = max(h60_values.values())
    for i, threshold in enumerate([30, 35, 40]):
        value = h60_values[threshold]
        y = chart_y + i * 42
        draw.text((816, y - 7), f"破 {threshold}", font=fonts.bold(23), fill=INK)
        draw.line((chart_x, y + 10, chart_x + chart_w, y + 10), fill="#EEF2F7", width=18)
        bar_w = int(chart_w * value / max_v)
        draw.line((chart_x, y + 10, chart_x + bar_w, y + 10), fill=TEAL, width=18)
        draw.text((chart_x + bar_w + 16, y - 6), pct(value, digits=1, signed=True), font=fonts.bold(24), fill=TEAL)
    draw.text((816, 636), "恐慌越深，60 天超額越大；但樣本也越少。", font=fonts.regular(21), fill=MUTED)

    draw_wrapped(
        draw,
        (86, 700),
        f"方向幾乎一致：{verdict['n_cells']} 種組合有 {verdict['n_cells_positive_excess']} 種「恐慌後進場的超額報酬為正」，但幅度不大。",
        fonts.regular(24),
        INK,
        1410,
        line_gap=7,
    )
    draw_wrapped(
        draw,
        (86, 765),
        f"真正比較耐久的是三個月（60 天）的慢速回復，且恐慌越深越明顯：破 30 超額 {pct(h60_values[30], signed=True)}、破 35 {pct(h60_values[35], signed=True)}、破 40 {pct(h60_values[40], signed=True)}。",
        fonts.regular(24),
        INK,
        1410,
        line_gap=7,
    )
    draw_round_rect(draw, (76, 842, 1524, 910), NAVY_2, outline=NAVY_2)
    draw_wrapped(
        draw,
        (106, 858),
        f"一句話：抄底不是『隔天立刻反彈』，而是『別在最深的恐慌裡當最後一個賣的人』。\n而且門檻越極端，樣本越少（破 40 只有 {events['40']['n_events_raw_decluster']} 次），別過度自信。",
        fonts.bold(22),
        WHITE,
        1370,
        line_gap=5,
    )

    draw_footer(draw, fonts)
    return img


def required_text_for_font_check(data: dict[str, Any]) -> str:
    return "\n".join(
        [
            "核心問題：VIX 破 30 就閉眼進場抄底，真的比隨便哪一天進場多賺嗎？",
            "白話拆解：要分清楚兩件事——SPY 長期本來就漲（隨便進場放久也常賺），和「別人最恐慌時進場」有沒有額外溢酬。",
            "一句話：半真。方向對但幅度小，大多只是搭上長期上漲的順風車。",
            "資料：SPY 1993-01-29 至 2026-07-02，共 8,413 個交易日；恐慌指數 VIX 由下往上首次穿越 30 / 35 / 40 當作進場事件。",
            "去叢集：同一場恐慌只算一次（距上次事件至少 20 個交易日）。實際事件數：破 30 有 50 次、破 35 有 25 次、破 40 只有 17 次。",
            "對照組：把樣本內每一天都當成一次進場（無條件 baseline），用完全相同的天期與價格序列。兩邊之差才是恐慌帶來的額外好處。",
            "時間順序：進場點固定在訊號當天收盤，往後看 5 / 10 / 20 / 60 天報酬，不偷看未來。",
            "嚴格把關：用處理重疊窗口的穩健統計，並對 12 種組合（3 門檻 × 4 天期）加一層多重檢定校正，去掉「測很多次剛好中」的運氣成分。",
            "先看底：完全不管 VIX、隨便一天進場的勝率本來就高——放 5 天 58.8%、放 60 天 71.9%。",
            "方向幾乎一致：12 種組合有 11 種「恐慌後進場的超額報酬為正」，但幅度不大。",
            "短天期最吸睛的『破 30 隔一週』超額約 +1.3%、勝率贏隨機進場約 +11 個百分點；但用最嚴格的多重檢定後，沒有任何一格單獨存活。",
            "真正比較耐久的是三個月（60 天）的慢速回復，且恐慌越深越明顯：破 30 超額 +2.6%、破 35 +4.9%、破 40 +6.2%。",
        ]
    )


def validate_evidence(data: dict[str, Any]) -> None:
    if data["experiment_id"] != "k1633":
        raise ValueError("evidence package 不是 K1633。")
    if not README_PATH.exists():
        raise FileNotFoundError(README_PATH)
    thresholds = data["config"]["thresholds"]
    horizons = data["config"]["horizons"]
    if thresholds != [30, 35, 40]:
        raise ValueError(f"unexpected thresholds: {thresholds}")
    if horizons != [5, 10, 20, 60]:
        raise ValueError(f"unexpected horizons: {horizons}")
    verdict = data["verdict"]["multiple_testing"]
    if verdict["n_cells"] != len(thresholds) * len(horizons):
        raise ValueError("multiple-testing cell count does not match config.")
    if verdict["bh_fdr_0.05_survivors"] != []:
        raise ValueError("FDR 5% survivor wording must be revised.")


def save_panel(img: Image.Image, path: Path) -> None:
    img.save(path, dpi=DPI)
    if not path.exists() or path.stat().st_size <= 0:
        raise RuntimeError(f"PNG not created or empty: {path}")
    with Image.open(path) as check:
        if check.size != (WIDTH, HEIGHT):
            raise RuntimeError(f"unexpected image size for {path}: {check.size}")
        if check.getbbox() is None:
            raise RuntimeError(f"blank image: {path}")


def main() -> None:
    data = load_json(RESULTS_PATH)
    validate_evidence(data)
    fonts = load_fonts(required_text_for_font_check(data))

    panels = {
        "1_question.png": panel_1(data, fonts),
        "2_method.png": panel_2(data, fonts),
        "3_results.png": panel_3(data, fonts),
    }
    for filename, img in panels.items():
        save_panel(img, PANEL_DIR / filename)

    manifest = {
        "renderer": str(Path(__file__).resolve()),
        "results_json": str(RESULTS_PATH),
        "font_regular": str(fonts.regular_path),
        "font_bold": str(fonts.bold_path),
        "outputs": [str((PANEL_DIR / name).resolve()) for name in panels],
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
