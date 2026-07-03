#!/usr/bin/env python3
"""Render data-bound PNG lazypack panels for the summer-vol article.

This renderer uses Pillow only. It reads the article evidence package and binds
displayed statistics to JSON fields where available. A few required article
facts that are not expanded in results.json are guarded by README/draft text
assertions before rendering.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXPERIMENT_DIR / "results.json"
README_PATH = EXPERIMENT_DIR / "README.md"
DRAFT_PATH = REPO_ROOT / "storage/drafts/event_summer_vol_predictive_20260704_general.md"

FONT_REGULAR_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]
FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]

NAVY = "#14213D"
NAVY_2 = "#1F3557"
INK = "#17202A"
MUTED = "#5E6A78"
LIGHT = "#EEF3F7"
BORDER = "#D7DEE8"
WHITE = "#FFFFFF"
TEAL = "#1B8A8F"
TEAL_LIGHT = "#E4F4F3"
BLUE = "#2B5F9E"
BLUE_LIGHT = "#E7EFF9"
AMBER = "#C77B20"
AMBER_LIGHT = "#FFF0D8"
RED = "#B9473F"
RED_LIGHT = "#F8E4E1"
GREEN = "#2E7D52"
GREEN_LIGHT = "#E3F1E9"
SLATE_LIGHT = "#F6F8FA"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def get(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            elif part.isdigit() and int(part) in cur:
                cur = cur[int(part)]
            else:
                raise KeyError(f"Missing JSON field: {dotted}")
        else:
            raise KeyError(f"Cannot resolve JSON field: {dotted}")
    return cur


def first_existing(paths: Iterable[str]) -> Path:
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    raise RuntimeError("No Traditional Chinese capable system font found.")


class Fonts:
    def __init__(self) -> None:
        self.regular_path = first_existing(FONT_REGULAR_CANDIDATES)
        self.bold_path = first_existing(FONT_BOLD_CANDIDATES)
        self._regular_cache: dict[int, ImageFont.FreeTypeFont] = {}
        self._bold_cache: dict[int, ImageFont.FreeTypeFont] = {}
        probe = ImageFont.truetype(str(self.regular_path), size=42)
        if not probe.getbbox("夏季波動率市場恐慌指數"):
            raise RuntimeError(f"CJK font probe failed: {self.regular_path}")

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._regular_cache:
            self._regular_cache[size] = ImageFont.truetype(str(self.regular_path), size=size)
        return self._regular_cache[size]

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._bold_cache:
            self._bold_cache[size] = ImageFont.truetype(str(self.bold_path), size=size)
        return self._bold_cache[size]


FONTS = Fonts()


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start: int,
    minimum: int,
    bold: bool = False,
) -> ImageFont.FreeTypeFont:
    for size in range(start, minimum - 1, -1):
        font = FONTS.bold(size) if bold else FONTS.regular(size)
        if text_size(draw, text, font)[0] <= max_width:
            return font
    return FONTS.bold(minimum) if bold else FONTS.regular(minimum)


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        current = ""
        for ch in raw_line:
            trial = current + ch
            if current and text_size(draw, trial, font)[0] > max_width:
                lines.append(current.rstrip())
                current = ch.lstrip()
            else:
                current = trial
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
        y += text_size(draw, line or " ", font)[1] + line_gap
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


def header(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, 170), fill=NAVY)
    title_font = fit_font(draw, title, 1420, 54, 42, bold=True)
    draw.text((80, 42), title, font=title_font, fill=WHITE)
    subtitle_font = fit_font(draw, subtitle, 1420, 30, 24, bold=False)
    draw.text((82, 112), subtitle, font=subtitle_font, fill="#DDE7F2")


def footer(draw: ImageDraw.ImageDraw, experiment_id: str, detail: str = "") -> None:
    text = f"資料來源：experiment {experiment_id}"
    if detail:
        text += f"｜{detail}"
    draw.line((80, 936, 1520, 936), fill=BORDER, width=2)
    draw.text((80, 955), text, font=FONTS.regular(21), fill=MUTED)


def metric_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    note: str,
    accent: str,
    accent_light: str,
    value_size: int = 58,
) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, fill=WHITE, outline=BORDER, radius=8)
    draw.rectangle((x1, y1, x1 + 14, y2), fill=accent)
    draw.text((x1 + 32, y1 + 24), label, font=FONTS.bold(24), fill=MUTED)
    vf = fit_font(draw, value, x2 - x1 - 64, value_size, 38, bold=True)
    draw.text((x1 + 32, y1 + 66), value, font=vf, fill=accent)
    draw.rounded_rectangle((x1 + 32, y2 - 62, x2 - 28, y2 - 22), radius=6, fill=accent_light)
    note_font = fit_font(draw, note, x2 - x1 - 82, 22, 18)
    draw.text((x1 + 48, y2 - 53), note, font=note_font, fill=INK)


def draw_step(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    number: str,
    title: str,
    body: str,
    accent: str,
) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, fill=WHITE, outline=BORDER, radius=8)
    draw.ellipse((x1 + 30, y1 + 28, x1 + 88, y1 + 86), fill=accent)
    draw.text((x1 + 49, y1 + 39), number, font=FONTS.bold(30), fill=WHITE)
    draw.text((x1 + 110, y1 + 34), title, font=FONTS.bold(30), fill=INK)
    draw_wrapped(draw, (x1 + 110, y1 + 88), body, FONTS.regular(25), MUTED, x2 - x1 - 150, 10)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str) -> None:
    x1, y1 = start
    x2, y2 = end
    draw.line((x1, y1, x2, y2), fill=color, width=6)
    if x2 >= x1:
        pts = [(x2, y2), (x2 - 18, y2 - 12), (x2 - 18, y2 + 12)]
    else:
        pts = [(x2, y2), (x2 + 18, y2 - 12), (x2 + 18, y2 + 12)]
    draw.polygon(pts, fill=color)


def verify_article_context(readme: str, draft: str) -> None:
    """Guard non-numeric article context that is not modeled as JSON fields."""
    required_snippets = [
        "2026-07-04 美股獨立紀念日長假、VIX 15.81",
        "夏季 = 6-7 月 VIX 月內平均；秋季 = 同年 9-10 月平均",
        "yfinance",
    ]
    combined = readme + "\n" + draft
    missing = [snippet for snippet in required_snippets if snippet not in combined]
    if missing:
        raise RuntimeError(f"README/draft evidence changed; missing snippets: {missing}")


def calm_summer_stats(results: dict[str, Any]) -> dict[str, Any]:
    """Derive panel-3 calm-summer statements from results.json rows."""
    block = get(results, "calm_summer_below15")
    if not isinstance(block, dict):
        raise TypeError("calm_summer_below15 must be a JSON object")
    rows = block.get("rows")
    if not isinstance(rows, list) or not rows:
        raise TypeError("calm_summer_below15.rows must be a non-empty list")

    threshold = float(block["threshold"])
    n_years = int(block["n_years"])
    if n_years != len(rows):
        raise RuntimeError(f"calm_summer_below15.n_years={n_years} but rows={len(rows)}")

    worst_row = max(rows, key=lambda row: float(row["autumn_vix"]))
    worst_year = int(worst_row["year"])
    worst_autumn = float(worst_row["autumn_vix"])
    if worst_year != int(block["worst_autumn_year"]):
        raise RuntimeError("calm_summer_below15.worst_autumn_year disagrees with rows")
    if abs(worst_autumn - float(block["worst_autumn_vix"])) > 1e-9:
        raise RuntimeError("calm_summer_below15.worst_autumn_vix disagrees with rows")

    other_autumns = [float(row["autumn_vix"]) for row in rows if int(row["year"]) != worst_year]
    other_max = max(other_autumns)
    other_below = math.ceil(other_max)
    if not other_max < other_below:
        raise RuntimeError("Cannot express strict upper bound for non-worst autumn rows")

    case_2024_rows = [row for row in rows if int(row["year"]) == 2024]
    if len(case_2024_rows) != 1:
        raise RuntimeError("Expected exactly one 2024 row in calm_summer_below15.rows")

    return {
        "threshold": threshold,
        "n_years": n_years,
        "worst_year": worst_year,
        "worst_autumn": worst_autumn,
        "other_below": other_below,
        "case_2024_autumn_vix": float(case_2024_rows[0]["autumn_vix"]),
    }


def render_concept(results: dict[str, Any]) -> Path:
    experiment_id = str(get(results, "meta.experiment_id"))
    n_years = int(get(results, "predictive_test_vix.n_years"))
    latest_vix = float(get(results, "current.latest_vix"))
    latest_date = str(get(results, "current.latest_date"))

    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    header(
        draw,
        "夏天太平靜，是暴風雨前的寧靜嗎？",
        f"用 {n_years} 年 VIX 數據檢驗「夏季低波動→秋季風暴」這個直覺。",
    )

    rounded(draw, (80, 215, 610, 465), fill=SLATE_LIGHT, outline=BORDER)
    draw.text((120, 245), "時間錨", font=FONTS.bold(28), fill=NAVY)
    draw_wrapped(
        draw,
        (120, 296),
        "2026 年 7 月獨立紀念日長假",
        FONTS.regular(30),
        INK,
        430,
        8,
    )
    draw.text((120, 355), f"VIX {latest_vix:.2f}", font=FONTS.bold(62), fill=TEAL)
    draw.text((124, 425), f"最新資料日：{latest_date}", font=FONTS.regular(22), fill=MUTED)

    rounded(draw, (650, 215, 1520, 465), fill=WHITE, outline=BORDER)
    draw.text((695, 245), "白話定義", font=FONTS.bold(30), fill=NAVY)
    draw.rounded_rectangle((695, 303, 1075, 408), radius=8, fill=BLUE_LIGHT)
    draw.text((725, 326), "VIX", font=FONTS.bold(40), fill=BLUE)
    draw.text((835, 333), "市場恐慌指數", font=FONTS.bold(31), fill=INK)
    draw.rounded_rectangle((1105, 303, 1480, 408), radius=8, fill=GREEN_LIGHT)
    draw.text((1135, 326), "已實現波動率", font=FONTS.bold(34), fill=GREEN)
    draw.text((1138, 371), "實際震盪幅度", font=FONTS.regular(26), fill=INK)

    draw.text((80, 520), "同一個低波動起點，有兩種可能", font=FONTS.bold(34), fill=INK)
    rounded(draw, (120, 610, 455, 765), fill=WHITE, outline=BORDER)
    draw.text((170, 645), "夏季低波動", font=FONTS.bold(34), fill=NAVY)
    draw.text((163, 702), "6–7 月平均 VIX 偏低", font=FONTS.regular(25), fill=MUTED)
    arrow(draw, (455, 685), (650, 625), TEAL)
    arrow(draw, (455, 695), (650, 775), RED)

    rounded(draw, (660, 545, 1515, 680), fill=TEAL_LIGHT, outline="#B8DAD8")
    draw.text((705, 574), "延續", font=FONTS.bold(42), fill=TEAL)
    draw.text((860, 584), "秋季仍偏平靜", font=FONTS.bold(33), fill=INK)
    draw.text((860, 628), "波動率跟著自己的狀態走", font=FONTS.regular(23), fill=MUTED)

    rounded(draw, (660, 720, 1515, 855), fill=RED_LIGHT, outline="#E9C1BD")
    draw.text((705, 749), "反轉", font=FONTS.bold(42), fill=RED)
    draw.text((860, 759), "平靜突然變秋季風暴", font=FONTS.bold(33), fill=INK)
    draw.text((860, 803), "「暴風雨前的寧靜」直覺", font=FONTS.regular(23), fill=MUTED)

    footer(draw, experiment_id, "yfinance ^VIX + ^GSPC")
    path = OUT_DIR / "1_concept.png"
    img.save(path, dpi=DPI)
    return path


def render_method(results: dict[str, Any]) -> Path:
    experiment_id = str(get(results, "meta.experiment_id"))
    n_years = int(get(results, "predictive_test_vix.n_years"))
    sample_start = str(get(results, "meta.sample_start"))
    sample_end = str(get(results, "meta.sample_end"))
    data_source = str(get(results, "meta.data_source"))

    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    header(draw, "怎麼算的：只問夏天對秋天有沒有預測力", "先定義季節，再比較同一年夏季與秋季的 VIX 水準。")

    draw_step(
        draw,
        (95, 225, 1505, 380),
        "1",
        "撈資料",
        f"2005 年以來的 VIX 與標普 500 資料；樣本 {sample_start} 至 {sample_end}，共 {n_years} 個完整年度。資料來源 yfinance。",
        BLUE,
    )
    draw_step(
        draw,
        (95, 420, 1505, 575),
        "2",
        "定義季節",
        "每年「夏季」= 6–7 月 VIX 平均；「秋季」= 同年 9–10 月平均。夏季完整早於秋季，避免偷看未來。",
        TEAL,
    )
    draw_step(
        draw,
        (95, 615, 1505, 770),
        "3",
        "檢驗直覺",
        "看夏季平靜的年份，秋季是變兇還是維持平靜；用 Pearson/Spearman/OLS 與 calm/hot 分組交叉檢查。",
        AMBER,
    )

    rounded(draw, (95, 815, 1505, 910), fill=SLATE_LIGHT, outline=BORDER)
    draw.text((130, 842), "^VIX", font=FONTS.bold(30), fill=BLUE)
    draw.text((222, 848), "隱含波動率", font=FONTS.regular(25), fill=INK)
    draw.text((500, 842), "^GSPC", font=FONTS.bold(30), fill=GREEN)
    draw.text((615, 848), "21 日年化已實現波動率", font=FONTS.regular(25), fill=INK)
    draw.text((1000, 848), "來源欄位", font=FONTS.bold(27), fill=NAVY)
    source_font = fit_font(draw, data_source, 430, 22, 17)
    draw.text((1120, 852), data_source, font=source_font, fill=MUTED)

    footer(draw, experiment_id, "results.meta / predictive_test_vix")
    path = OUT_DIR / "2_method.png"
    img.save(path, dpi=DPI)
    return path


def render_results(results: dict[str, Any]) -> Path:
    experiment_id = str(get(results, "meta.experiment_id"))
    calm_stats = calm_summer_stats(results)
    pearson_r = float(get(results, "predictive_test_vix.pearson_r"))
    pearson_p = float(get(results, "predictive_test_vix.pearson_p"))
    calm_mean = float(get(results, "predictive_test_vix.autumn_after_calm_summer_mean"))
    hot_mean = float(get(results, "predictive_test_vix.autumn_after_hot_summer_mean"))
    spike_share = float(get(results, "annual_max_vix_spike_aug_oct_share"))
    uniform_share = float(get(results, "annual_max_vix_spike_uniform_null_share"))
    aug_peak = float(get(results, "case_2024.aug_2024_peak_vix"))
    aug_peak_date = str(get(results, "case_2024.aug_2024_peak_date"))

    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)
    header(draw, "主要結果：平靜通常延續，不會自己反轉成風暴", "夏季越平靜，歷史上越不像秋季失控的前兆。")

    metric_card(
        draw,
        (80, 210, 550, 405),
        "夏季 → 秋季 VIX 相關",
        f"r={pearson_r:+.2f}",
        f"正相關，統計顯著 p={pearson_p:.4f}",
        TEAL,
        TEAL_LIGHT,
    )
    metric_card(
        draw,
        (565, 210, 1035, 405),
        "秋季平均 VIX",
        f"{calm_mean:.2f} vs {hot_mean:.2f}",
        "平靜夏季後 vs 火熱夏季後",
        BLUE,
        BLUE_LIGHT,
        value_size=50,
    )
    metric_card(
        draw,
        (1050, 210, 1520, 405),
        "年度最大恐慌尖峰",
        f"{spike_share * 100:.1f}% < {uniform_share * 100:.0f}%",
        "8–10 月占比低於均勻 25%",
        AMBER,
        AMBER_LIGHT,
        value_size=54,
    )

    rounded(draw, (80, 455, 780, 680), fill=GREEN_LIGHT, outline="#BEDCCB")
    draw.text((120, 490), "真正平靜的夏季", font=FONTS.bold(31), fill=GREEN)
    draw.text(
        (120, 542),
        f"VIX < {calm_stats['threshold']:.0f}：{calm_stats['n_years']} 個年份",
        font=FONTS.bold(48),
        fill=INK,
    )
    draw.text(
        (120, 610),
        f"秋季最高只有 {calm_stats['worst_year']} 的 {calm_stats['worst_autumn']:.1f}；其餘 <{calm_stats['other_below']:.0f}；",
        font=FONTS.regular(26),
        fill=MUTED,
    )
    draw.text((120, 650), "從未失控。", font=FONTS.regular(26), fill=MUTED)

    rounded(draw, (820, 455, 1520, 680), fill=RED_LIGHT, outline="#E9C1BD")
    date_label = aug_peak_date.replace("-", "/")
    draw.text((860, 490), "2024 案例", font=FONTS.bold(31), fill=RED)
    draw.text((860, 542), f"{date_label}  VIX {aug_peak:.2f}", font=FONTS.bold(45), fill=INK)
    draw_wrapped(
        draw,
        (860, 610),
        f"這是短暴；秋季已回落 {calm_stats['case_2024_autumn_vix']:.2f}，不是整季風暴。",
        FONTS.regular(27),
        MUTED,
        610,
        8,
    )

    rounded(draw, (80, 730, 1520, 895), fill=NAVY_2, outline=NAVY_2)
    draw.text((120, 765), "一句結論", font=FONTS.bold(30), fill="#BFD7EA")
    conclusion = "波動率會延續不會反轉；別因為太平靜就賭季節性風暴，但尾部保護要當常設配置。"
    draw_wrapped(draw, (120, 810), conclusion, FONTS.bold(36), WHITE, 1360, 10)

    footer(draw, experiment_id, "results.predictive_test_vix / annual_max_vix_spike / case_2024")
    path = OUT_DIR / "3_results.png"
    img.save(path, dpi=DPI)
    return path


def verify_png(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= 0:
        raise RuntimeError(f"PNG not written or empty: {path}")
    with Image.open(path) as img:
        if img.size != (WIDTH, HEIGHT):
            raise RuntimeError(f"Unexpected image size for {path}: {img.size}")


def main() -> None:
    results = load_json(RESULTS_PATH)
    readme = README_PATH.read_text(encoding="utf-8")
    draft = DRAFT_PATH.read_text(encoding="utf-8")
    verify_article_context(readme, draft)

    paths = [
        render_concept(results),
        render_method(results),
        render_results(results),
    ]
    for path in paths:
        verify_png(path)
        print(path)
    print(f"CJK font regular={FONTS.regular_path}")
    print(f"CJK font bold={FONTS.bold_path}")


if __name__ == "__main__":
    main()
