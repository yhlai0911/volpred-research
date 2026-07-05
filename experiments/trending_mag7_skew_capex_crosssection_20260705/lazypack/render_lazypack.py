#!/usr/bin/env python3
"""Render the Mag 7 capex x option-skew lazypack panels.

The renderer is intentionally data-bound: every displayed company statistic is
read from experiments/trending_mag7_skew_capex_crosssection_20260705/results.json.
It does not call any image-generation service.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

DEFAULT_RESULTS = Path(
    "/Users/yhlai0911/volpred-research/"
    "experiments/trending_mag7_skew_capex_crosssection_20260705/results.json"
)
DEFAULT_README = Path(
    "/Users/yhlai0911/volpred-research/"
    "experiments/trending_mag7_skew_capex_crosssection_20260705/README.md"
)
DEFAULT_ARTICLE = Path("/tmp/trending_mag7_skew_20260705.md")
DEFAULT_OUT_DIR = Path("/tmp/mag7_skew_poster")

EXPERIMENT_ID = "trending_mag7_skew_capex_crosssection_20260705"

FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
    "/Library/Fonts/Noto Sans CJK TC Regular.otf",
]
FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJKtc-Bold.otf",
    "/Library/Fonts/Noto Sans CJK TC Bold.otf",
]

PAPER = "#FFFFFF"
INK = "#111827"
MUTED = "#5B6472"
FAINT = "#8A94A6"
NAVY = "#102A43"
NAVY_2 = "#183B56"
BLUE = "#2F6EA5"
BLUE_SOFT = "#E8F0FA"
TEAL = "#0F766E"
TEAL_SOFT = "#E2F4F1"
AMBER = "#B26A00"
AMBER_SOFT = "#FFF0D5"
RED = "#B42318"
RED_SOFT = "#FDE7E5"
GREEN = "#217A4C"
GREEN_SOFT = "#E3F3E8"
GRAY_SOFT = "#F4F6F8"
BORDER = "#D8DEE8"


@dataclass(frozen=True)
class Fonts:
    regular_path: Path
    bold_path: Path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


def first_existing(paths: Iterable[str]) -> Path | None:
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    return None


def load_fonts() -> Fonts:
    regular = first_existing(FONT_CANDIDATES_REGULAR)
    bold = first_existing(FONT_CANDIDATES_BOLD)
    if regular is None or bold is None:
        raise RuntimeError("找不到可用 CJK 字型，無法保證繁體中文不缺字。")

    probe = ImageFont.truetype(str(regular), size=44)
    sample = "繁體中文資本支出強度選擇權偏斜ρ−×％資料來源"
    missing = []
    for char in sample:
        if char.isspace():
            continue
        mask = probe.getmask(char)
        if mask.getbbox() is None:
            missing.append(char)
    if missing:
        raise RuntimeError(f"CJK 字型缺字：{''.join(sorted(set(missing)))}")
    return Fonts(regular_path=regular, bold_path=bold)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def source_label(readme_text: str) -> str:
    match = re.search(r"\bK\d{3,}\b", readme_text)
    experiment_ref = f"experiment {match.group(0)}" if match else f"experiment {EXPERIMENT_ID}"
    return f"資料來源：{experiment_ref}；results.json；yfinance 2026-07-05 快照"


def rows_by_ticker(results: dict) -> dict[str, dict]:
    return {row["ticker"]: row for row in results["cross_section"]}


def signed_pp(value: float) -> str:
    text = f"{value:+.1f}"
    return text.replace("-", "−")


def signed_number(value: float, digits: int = 3) -> str:
    text = f"{value:+.{digits}f}"
    return text.replace("+", "").replace("-", "−")


def pct(value: float) -> str:
    return f"{value:.1f}%"


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    if not text:
        return (0, 0)
    box = draw.textbbox((0, 0), text, font=font)
    return (box[2] - box[0], box[3] - box[1])


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
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
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
    line_gap: int = 10,
) -> int:
    x, y = xy
    line_height = text_size(draw, "測試", font)[1] + line_gap
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    fill: str,
    outline: str = BORDER,
    radius: int = 8,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def header(draw: ImageDraw.ImageDraw, fonts: Fonts, title: str, subtitle: str = "") -> None:
    draw.rectangle((0, 0, WIDTH, 138), fill=NAVY)
    draw.rectangle((0, 138, WIDTH, 148), fill=TEAL)
    draw.text((72, 37), title, font=fonts.bold(45), fill="#FFFFFF")
    if subtitle:
        draw.text((74, 96), subtitle, font=fonts.regular(22), fill="#D9EAF7")


def footer(draw: ImageDraw.ImageDraw, fonts: Fonts, label: str) -> None:
    draw.line((72, 930, WIDTH - 72, 930), fill="#E1E6EF", width=2)
    draw_wrapped(draw, (72, 946), label, fonts.regular(21), MUTED, WIDTH - 144, line_gap=3)


def draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], fill: str) -> None:
    x1, y1 = start
    x2, y2 = end
    draw.line((x1, y1, x2, y2), fill=fill, width=8)
    draw.polygon([(x2, y2), (x2 - 18, y2 - 12), (x2 - 18, y2 + 12)], fill=fill)


def draw_shield(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float, fill: str, outline: str) -> None:
    points = [
        (cx, cy - int(58 * scale)),
        (cx + int(52 * scale), cy - int(36 * scale)),
        (cx + int(43 * scale), cy + int(38 * scale)),
        (cx, cy + int(72 * scale)),
        (cx - int(43 * scale), cy + int(38 * scale)),
        (cx - int(52 * scale), cy - int(36 * scale)),
    ]
    draw.polygon(points, fill=fill, outline=outline)
    draw.line((cx, cy - int(35 * scale), cx, cy + int(45 * scale)), fill=outline, width=max(2, int(4 * scale)))


def draw_panel_1(out_path: Path, fonts: Fonts, source: str) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "Mag 7 資本支出強度 × 選擇權偏斜",
        "這篇只問一件事：AI 基建燒錢，市場有沒有幫下跌風險加價？",
    )

    left = (86, 216, 748, 762)
    right = (852, 216, 1514, 762)
    rounded_rect(draw, left, fill=GRAY_SOFT, outline="#D7DEE9", radius=8, width=2)
    rounded_rect(draw, right, fill=BLUE_SOFT, outline="#C9D8EB", radius=8, width=2)

    draw.text((126, 252), "問題框架", font=fonts.bold(34), fill=NAVY)
    concept_text = (
        "AI 資本支出燒最兇的科技巨頭，現在選擇權市場有沒有替它們的下跌風險多收保費？"
        "\n\n這不是在問誰會漲跌，而是在問：避險需求與風險溢酬，是否已經反映在選擇權價格的形狀裡。"
    )
    draw_wrapped(draw, (126, 314), concept_text, fonts.regular(33), INK, 560, line_gap=13)

    draw.text((892, 252), "下檔偏斜是什麼？", font=fonts.bold(34), fill=NAVY)
    skew_text = (
        "白話說，就是同一家股票的選擇權市場，對「下跌」與「上漲」兩邊，哪一邊收的錢比較貴。"
        "\n\n賣權比較貴，代表下跌保護較貴；買權比較貴，代表市場更願意為上漲情境付溢價。"
    )
    draw_wrapped(draw, (892, 314), skew_text, fonts.regular(33), INK, 560, line_gap=13)

    draw_shield(draw, 400, 670, 0.92, fill="#FFFFFF", outline=TEAL)
    draw.text((316, 746), "下跌保護", font=fonts.bold(27), fill=TEAL)
    draw_arrow(draw, (700, 655), (890, 655), fill=FAINT)
    draw.ellipse((990, 598, 1114, 722), fill="#FFFFFF", outline=AMBER, width=5)
    draw.arc((1014, 622, 1090, 698), start=210, end=510, fill=AMBER, width=6)
    draw.polygon([(1090, 652), (1117, 642), (1109, 671)], fill=AMBER)
    draw.text((1185, 622), "保費形狀", font=fonts.bold(31), fill=AMBER)
    draw.text((1185, 662), "下跌 vs 上漲", font=fonts.regular(27), fill=MUTED)

    footer(draw, fonts, source)
    img.save(out_path, dpi=DPI)


def draw_panel_2(out_path: Path, fonts: Fonts, source: str, results: dict) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "怎麼量：同一天、同一到期日、同一套公式",
        "七檔 Mag 7 統一比較，避免把不同期限或不同口徑混在一起。",
    )

    rows = results["cross_section"]
    expiry_set = sorted({row["expiry"] for row in rows})
    dte_set = sorted({row["dte"] for row in rows})
    if len(expiry_set) != 1 or len(dte_set) != 1:
        raise ValueError("Panel 2 expects one common expiry and one common DTE.")
    expiry = expiry_set[0]
    dte = dte_set[0]
    tickers = "/".join(results["tickers"])

    cards = [
        (
            (78, 214, 510, 530),
            "1",
            "資本支出強度",
            "最近 4 季資本支出\n÷\n最近 4 季營收",
            "用營收規模標準化，避免只看公司大小。",
            TEAL,
            TEAL_SOFT,
        ),
        (
            (584, 214, 1016, 530),
            "2",
            "下檔偏斜",
            "現價向下 10% 賣權 IV\n−\n現價向上 10% 買權 IV",
            "正值代表賣權較貴；負值代表買權較貴。",
            BLUE,
            BLUE_SOFT,
        ),
        (
            (1090, 214, 1522, 530),
            "3",
            "比較口徑",
            f"{expiry}\n到期\n{dte} 天後",
            "七檔股票使用同一到期日，保留橫向可比性。",
            AMBER,
            AMBER_SOFT,
        ),
    ]
    for box, step, title, formula, note, color, soft in cards:
        rounded_rect(draw, box, fill="#FFFFFF", outline="#D7DEE9", radius=8, width=2)
        x1, y1, x2, _ = box
        draw.ellipse((x1 + 26, y1 + 24, x1 + 82, y1 + 80), fill=soft, outline=color, width=3)
        draw.text((x1 + 45, y1 + 32), step, font=fonts.bold(30), fill=color)
        draw.text((x1 + 104, y1 + 32), title, font=fonts.bold(31), fill=NAVY)
        draw_wrapped(draw, (x1 + 36, y1 + 116), formula, fonts.bold(34), INK, x2 - x1 - 72, line_gap=9)
        draw_wrapped(draw, (x1 + 36, y1 + 254), note, fonts.regular(24), MUTED, x2 - x1 - 72, line_gap=7)

    rounded_rect(draw, (78, 590, 1522, 820), fill=GRAY_SOFT, outline="#D7DEE9", radius=8, width=2)
    draw.text((118, 624), "資料處理流程", font=fonts.bold(32), fill=NAVY)
    flow = [
        ("股票池", tickers),
        ("選擇權鏈", "yfinance 即時 option_chain"),
        ("財報口徑", "現金流量表 + 營收資料"),
        ("輸出", "描述性截面排名，不做因果宣稱"),
    ]
    box_w = 310
    gap = 34
    x = 118
    for idx, (label, body) in enumerate(flow):
        y = 690
        rounded_rect(draw, (x, y, x + box_w, y + 92), fill="#FFFFFF", outline=BORDER, radius=8, width=1)
        draw.text((x + 20, y + 16), label, font=fonts.bold(24), fill=NAVY_2)
        draw_wrapped(draw, (x + 20, y + 48), body, fonts.regular(20), MUTED, box_w - 40, line_gap=5)
        if idx < len(flow) - 1:
            draw_arrow(draw, (x + box_w + 8, y + 46), (x + box_w + gap - 8, y + 46), fill=FAINT)
        x += box_w + gap

    draw.text((118, 850), "資料來源標註：yfinance，2026-07-05", font=fonts.bold(28), fill=NAVY_2)
    footer(draw, fonts, source)
    img.save(out_path, dpi=DPI)


def draw_axis_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    value: float,
    max_abs: float,
    color: str,
    label: str,
    fonts: Fonts,
) -> None:
    center = x + width // 2
    draw.line((x, y, x + width, y), fill="#CAD2DF", width=2)
    draw.line((center, y - 18, center, y + 18), fill="#AEB8C8", width=2)
    if max_abs <= 0:
        return
    bar_len = int(abs(value) / max_abs * (width // 2 - 22))
    if value >= 0:
        rect = (center, y - 14, center + bar_len, y + 14)
        label_x = center + bar_len + 10
    else:
        rect = (center - bar_len, y - 14, center, y + 14)
        label_x = center - bar_len - 96
    draw.rounded_rectangle(rect, radius=6, fill=color)
    draw.text((label_x, y - 20), label, font=fonts.bold(23), fill=color)


def draw_panel_3(out_path: Path, fonts: Fonts, source: str, results: dict) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "結果：燒錢強度最高，沒有換到更貴的下跌保護",
        "2026-07-05 快照；同一到期日 2026-08-07；描述性排名，非統計檢定。",
    )

    rows = sorted(results["cross_section"], key=lambda row: row["capex_intensity_pct"], reverse=True)
    top3 = rows[:3]
    bottom2 = sorted(results["cross_section"], key=lambda row: row["capex_intensity_pct"])[:2]
    rho = results["spearman_capex_vs_skew"]["rho"]
    n = results["spearman_capex_vs_skew"]["n"]

    # Bento cards
    rounded_rect(draw, (72, 190, 744, 466), fill=RED_SOFT, outline="#E8B9B4", radius=8, width=2)
    draw.text((112, 222), "資本支出強度最高三家", font=fonts.bold(30), fill=RED)
    draw.text((112, 262), "下檔偏斜為負值或接近零", font=fonts.bold(25), fill=NAVY)
    y = 318
    for row in top3:
        line = (
            f"{row['ticker']}  {pct(row['capex_intensity_pct'])}  |  "
            f"{signed_pp(row['skew_10pct_otm_pp'])} 百分點"
        )
        draw.text((116, y), line, font=fonts.bold(31), fill=INK)
        y += 42
    draw.text((116, 432), "META/MSFT 買權比賣權貴；GOOGL 近乎持平。", font=fonts.regular(22), fill=MUTED)

    rounded_rect(draw, (796, 190, 1528, 466), fill=GREEN_SOFT, outline="#BFE3CB", radius=8, width=2)
    draw.text((836, 222), "資本支出強度最低兩家", font=fonts.bold(30), fill=GREEN)
    draw.text((836, 262), "下檔偏斜正值且最高", font=fonts.bold(25), fill=NAVY)
    y = 326
    for row in sorted(bottom2, key=lambda item: item["capex_intensity_pct"], reverse=True):
        line = (
            f"{row['ticker']}  {pct(row['capex_intensity_pct'])}  |  "
            f"{signed_pp(row['skew_10pct_otm_pp'])} 百分點"
        )
        draw.text((840, y), line, font=fonts.bold(36), fill=INK)
        y += 55
    draw.text((840, 432), "賣權比買權貴，呈現傳統下檔保護形狀。", font=fonts.regular(22), fill=MUTED)

    rounded_rect(draw, (72, 510, 560, 768), fill="#FFFFFF", outline="#D7DEE9", radius=8, width=2)
    draw.text((112, 544), "等級相關", font=fonts.bold(30), fill=NAVY)
    draw.text((112, 598), "Spearman ρ", font=fonts.bold(31), fill=RED)
    draw.text((112, 640), signed_number(rho, 3), font=fonts.bold(64), fill=RED)
    draw.text((340, 651), f"n = {n}", font=fonts.bold(37), fill=INK)
    draw_wrapped(draw, (112, 724), "描述性排名，非統計檢定。", fonts.regular(23), MUTED, 390, line_gap=5)

    rounded_rect(draw, (604, 510, 1528, 768), fill="#FFFFFF", outline="#D7DEE9", radius=8, width=2)
    draw.text((644, 544), "反向排序重點", font=fonts.bold(30), fill=NAVY)
    draw.text((644, 602), "資本支出強度高", font=fonts.bold(27), fill=RED)
    draw.text((644, 642), "META / MSFT / GOOGL", font=fonts.bold(30), fill=INK)
    draw.text((644, 686), "skew：−3.1 / −2.5 / +0.1 百分點", font=fonts.bold(27), fill=RED)
    draw_arrow(draw, (1056, 648), (1168, 648), fill=FAINT)
    draw.text((1208, 602), "資本支出強度低", font=fonts.bold(27), fill=GREEN)
    draw.text((1208, 642), "NVDA / AAPL", font=fonts.bold(30), fill=INK)
    draw.text((1208, 686), "skew：+3.8 / +3.9 百分點", font=fonts.bold(27), fill=GREEN)

    rounded_rect(draw, (72, 804, 1528, 904), fill=GRAY_SOFT, outline="#D7DEE9", radius=8, width=2)
    conclusion = "一句結論：資本支出燒最兇的巨頭，選擇權市場現在沒有多收下跌保費，跟直覺相反。"
    draw_wrapped(draw, (112, 832), conclusion, fonts.bold(30), INK, 1370, line_gap=7)

    footer(draw, fonts, source)
    img.save(out_path, dpi=DPI)


def verify_outputs(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.stat().st_size <= 0:
            raise RuntimeError(f"PNG is empty: {path}")
        with Image.open(path) as img:
            if img.size != (WIDTH, HEIGHT):
                raise RuntimeError(f"Unexpected size for {path}: {img.size}")
            extrema = img.convert("L").getextrema()
            if extrema[0] == extrema[1]:
                raise RuntimeError(f"PNG appears blank: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--article", type=Path, default=DEFAULT_ARTICLE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    results = load_json(args.results)
    readme_text = load_text(args.readme)
    article_text = load_text(args.article)
    if "Mag 7" not in article_text and "Mag7" not in article_text:
        raise RuntimeError("Article markdown does not appear to match the Mag 7 evidence package.")
    if results.get("n") != 7:
        raise RuntimeError("Expected n=7 in results.json.")

    fonts = load_fonts()
    label = source_label(readme_text)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    outputs = [
        args.out_dir / "1_framework.png",
        args.out_dir / "2_method.png",
        args.out_dir / "3_results.png",
    ]
    draw_panel_1(outputs[0], fonts, label)
    draw_panel_2(outputs[1], fonts, label, results)
    draw_panel_3(outputs[2], fonts, label, results)
    verify_outputs(outputs)

    print("Rendered PNGs:")
    for path in outputs:
        print(path)
    print(f"Font regular: {fonts.regular_path}")
    print(f"Font bold: {fonts.bold_path}")


if __name__ == "__main__":
    main()
