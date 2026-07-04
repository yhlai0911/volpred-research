#!/usr/bin/env python3
"""Render K1635 lazy-pack panels as deterministic PNG files.

Displayed result statistics are bound to experiments/k1635/k1635_results.json;
method-design wording follows the K1635 README evidence package.  The renderer
uses local CJK fonts and Pillow only; it does not call any image generation
model or external service.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = ROOT / "experiments/k1635/k1635_results.json"
OUT_DIR = ROOT / "storage/lazypack_jobs/mile_e7b6e075/panels"

WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

FONT_REGULAR_CANDIDATES = [
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
]
FONT_BOLD_CANDIDATES = [
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
]

COLORS = {
    "ink": "#14202B",
    "muted": "#5B6675",
    "soft": "#EEF2F6",
    "line": "#D9E1EA",
    "paper": "#FFFFFF",
    "header": "#102A43",
    "header2": "#193B5A",
    "teal": "#167A7F",
    "teal_soft": "#DDF1F2",
    "red": "#C83C3C",
    "red_soft": "#F6DDDD",
    "amber": "#B26A00",
    "amber_soft": "#F7E9D2",
    "blue": "#245B9D",
    "blue_soft": "#E1ECFA",
    "green": "#23744B",
    "green_soft": "#DDEEE5",
}


@dataclass(frozen=True)
class FontBook:
    regular_path: Path
    bold_path: Path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


def first_existing(candidates: list[Path]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    raise RuntimeError("找不到可用的繁中文字型；請安裝 Heiti TC / Hiragino / Arial Unicode。")


def load_fonts() -> FontBook:
    fonts = FontBook(
        regular_path=first_existing(FONT_REGULAR_CANDIDATES),
        bold_path=first_existing(FONT_BOLD_CANDIDATES),
    )
    probe = fonts.regular(36)
    text = "台積電傳導迷思懶人包"
    if probe.getbbox(text) is None:
        raise RuntimeError(f"字型無法渲染繁中測試文字：{fonts.regular_path}")
    return fonts


def load_results() -> dict[str, Any]:
    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            raise KeyError(f"缺少 evidence 欄位：{path}")
    return cur


def pct(value: float, digits: int = 1, signed: bool = False) -> str:
    sign = "+" if signed else ""
    return f"{float(value) * 100:{sign}.{digits}f}%"


def num(value: float, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}"


def ratio(value: float, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}倍"


def money_trillion(value: float, digits: int = 1) -> str:
    return f"{float(value):.{digits}f}兆"


def measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def center_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    anchor_y: str = "middle",
) -> None:
    x0, y0, x1, y1 = box
    w, h = measure(draw, text, font)
    y = y0 + (y1 - y0 - h) / 2 if anchor_y == "middle" else y0
    draw.text((x0 + (x1 - x0 - w) / 2, y), text, font=font, fill=fill)


def center_multiline(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    fill: str,
    line_gap: int = 8,
) -> None:
    x0, y0, x1, y1 = box
    sizes = [measure(draw, line, font) for line in lines]
    total_h = sum(h for _, h in sizes) + line_gap * (len(lines) - 1)
    y = y0 + (y1 - y0 - total_h) / 2
    for line, (w, h) in zip(lines, sizes, strict=True):
        draw.text((x0 + (x1 - x0 - w) / 2, y), line, font=font, fill=fill)
        y += h + line_gap


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for raw in text.split("\n"):
        current = ""
        for ch in raw:
            trial = current + ch
            if measure(draw, trial, font)[0] <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = ch
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
    line_gap: int = 8,
) -> int:
    x, y = xy
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += measure(draw, line, font)[1] + line_gap
    return y


def rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str | None = None,
    width: int = 2,
    radius: int = 8,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def header(draw: ImageDraw.ImageDraw, fonts: FontBook, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, 128), fill=COLORS["header"])
    draw.rectangle((0, 118, WIDTH, 128), fill=COLORS["teal"])
    draw.text((80, 28), title, font=fonts.bold(52), fill="white")
    draw.text((82, 88), subtitle, font=fonts.regular(25), fill="#D7E5F2")


def footer(draw: ImageDraw.ImageDraw, fonts: FontBook) -> None:
    draw.line((80, 944, WIDTH - 80, 944), fill=COLORS["line"], width=2)
    draw.text(
        (80, 958),
        "資料來源：experiment K1635；台積電(2330.TW)、台灣加權指數(^TWII)，2010-01-04至2026-07-03。",
        font=fonts.regular(23),
        fill=COLORS["muted"],
    )


def badge(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    xy: tuple[int, int],
    text: str,
    fg: str,
    bg: str,
    width: int = 106,
) -> None:
    x, y = xy
    rounded_rect(draw, (x, y, x + width, y + 38), fill=bg, outline=None, radius=8)
    center_text(draw, (x, y + 2, x + width, y + 36), text, fonts.bold(23), fg)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str) -> None:
    x0, y0 = start
    x1, y1 = end
    draw.line((x0, y0, x1, y1), fill=color, width=5)
    direction = 1 if x1 >= x0 else -1
    draw.polygon(
        [(x1, y1), (x1 - direction * 18, y1 - 10), (x1 - direction * 18, y1 + 10)],
        fill=color,
    )


def bar(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    value: float,
    max_value: float,
    fill: str,
    bg: str = "#ECF0F4",
) -> None:
    x0, y0, x1, y1 = box
    rounded_rect(draw, box, fill=bg, outline=None, radius=6)
    w = max(0, min(1, value / max_value)) * (x1 - x0)
    rounded_rect(draw, (x0, y0, int(x0 + w), y1), fill=fill, outline=None, radius=6)


def concept_panel(data: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["paper"])
    draw = ImageDraw.Draw(img)
    header(
        draw,
        fonts,
        "台積電傳導迷思懶人包",
        "一句俗諺拆成四層命題：集中度、同日、隔日、波動",
    )

    weight_2010 = get(data, "M1_concentration.weight_proxy_yearly_central.2010")
    weight_last = get(data, "M1_concentration.weight_proxy_last_central")
    weight_2026 = get(data, "M1_concentration.weight_proxy_yearly_central.2026")
    p_same_3 = get(data, "M2_transmission.thresholds.-3pct.same_day.p_twii_down")
    mean_same_3 = get(data, "M2_transmission.thresholds.-3pct.same_day.mean_twii_ret")
    p_next_3 = get(data, "M2_transmission.thresholds.-3pct.next_day_T1.p_twii_down")
    mean_next_3 = get(data, "M2_transmission.thresholds.-3pct.next_day_T1.mean_twii_ret")
    p_plain = get(data, "M2_transmission.unconditional_next_day.p_twii_down")
    vol_3 = get(data, "M4_vol_transmission.thresholds.-3pct.ratio_event_vs_nonevent")
    vol_5 = get(data, "M4_vol_transmission.thresholds.-5pct.ratio_event_vs_nonevent")

    draw.text(
        (80, 162),
        "「台積電打噴嚏、台股重感冒」不是單一結論；拆開後，成立與迷思分得很清楚。",
        font=fonts.bold(30),
        fill=COLORS["ink"],
    )

    card_w = 342
    gap = 24
    top = 232
    bottom = 820
    cards = [
        (80 + i * (card_w + gap), top, 80 + i * (card_w + gap) + card_w, bottom)
        for i in range(4)
    ]
    card_data = [
        {
            "title": "一、集中度",
            "main": [f"2010 {pct(weight_2010, 1)}", f"2026 {pct(weight_last, 1)}–{pct(weight_2026, 1)}"],
            "sub": "前提成立：台積電已從重要成分股變成大盤主角。",
            "badge": "成立",
            "fg": COLORS["green"],
            "bg": COLORS["green_soft"],
            "accent": COLORS["green"],
        },
        {
            "title": "二、同日方向",
            "main": pct(p_same_3, 2),
            "sub": f"台積電跌3%以上當天，大盤下跌機率；平均報酬{pct(mean_same_3, 2, signed=True)}。",
            "badge": "成立",
            "fg": COLORS["teal"],
            "bg": COLORS["teal_soft"],
            "accent": COLORS["teal"],
        },
        {
            "title": "三、隔日方向",
            "main": pct(p_next_3, 2),
            "sub": f"隔日與平常無異，平均{pct(mean_next_3, 2, signed=True)}。",
            "badge": "迷思",
            "fg": COLORS["amber"],
            "bg": COLORS["amber_soft"],
            "accent": COLORS["amber"],
        },
        {
            "title": "四、波動",
            "main": f"{ratio(vol_3)} / {ratio(vol_5)}",
            "sub": "台積電跌3%/5%以上後，未來5日大盤已實現波動度放大。",
            "badge": "成立",
            "fg": COLORS["blue"],
            "bg": COLORS["blue_soft"],
            "accent": COLORS["blue"],
        },
    ]

    for i, box in enumerate(cards):
        x0, y0, x1, y1 = box
        item = card_data[i]
        rounded_rect(draw, box, fill="#FFFFFF", outline=COLORS["line"], radius=8)
        draw.rectangle((x0, y0, x1, y0 + 10), fill=item["accent"])
        draw.text((x0 + 24, y0 + 34), item["title"], font=fonts.bold(27), fill=COLORS["ink"])
        badge(draw, fonts, (x0 + 24, y0 + 78), item["badge"], item["fg"], item["bg"])
        if isinstance(item["main"], list):
            center_multiline(draw, (x0 + 20, y0 + 138, x1 - 20, y0 + 248), item["main"], fonts.bold(36), item["accent"], line_gap=12)
        else:
            center_text(draw, (x0 + 20, y0 + 138, x1 - 20, y0 + 248), item["main"], fonts.bold(43), item["accent"])
        draw.line((x0 + 28, y0 + 262, x1 - 28, y0 + 262), fill=COLORS["line"], width=2)
        draw_wrapped(
            draw,
            (x0 + 30, y0 + 298),
            item["sub"],
            fonts.regular(27),
            COLORS["muted"],
            card_w - 60,
            line_gap=10,
        )
        if i < 3:
            arrow(draw, (x1 + 6, y0 + 292), (x1 + gap - 6, y0 + 292), COLORS["line"])

    rounded_rect(draw, (80, 854, WIDTH - 80, 916), fill=COLORS["soft"], outline=None, radius=8)
    draw.text((112, 870), "結論色碼", font=fonts.bold(24), fill=COLORS["ink"])
    badge(draw, fonts, (248, 866), "成立", COLORS["teal"], COLORS["teal_soft"], width=98)
    draw.text((368, 870), "同日方向與波動傳導有證據支持", font=fonts.regular(24), fill=COLORS["muted"])
    badge(draw, fonts, (765, 866), "迷思", COLORS["amber"], COLORS["amber_soft"], width=98)
    draw.text((884, 870), "隔日方向拖累與平常無異", font=fonts.regular(24), fill=COLORS["muted"])

    footer(draw, fonts)
    path = OUT_DIR / "concept.png"
    img.save(path, dpi=DPI)
    return path


def method_panel(data: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["paper"])
    draw = ImageDraw.Draw(img)
    header(draw, fonts, "研究設計：同日與隔日分開看", "事件研究法：把當天反應、隔天方向、未來波動拆開比較")

    stock = get(data, "data.stock_ticker")
    index = get(data, "data.index_ticker")
    period_start = get(data, "data.period.0")
    period_end = get(data, "data.period.1")
    n_obs = get(data, "data.n_obs")
    n_3 = get(data, "M2_transmission.thresholds.-3pct.n_drop_days")
    n_5 = get(data, "M2_transmission.thresholds.-5pct.n_drop_days")
    horizon = get(data, "M4_vol_transmission.horizon_days")

    left = (80, 170, 560, 824)
    rounded_rect(draw, left, fill="#FFFFFF", outline=COLORS["line"], radius=8)
    draw.rectangle((80, 170, 560, 180), fill=COLORS["blue"])
    draw.text((110, 208), "資料與事件定義", font=fonts.bold(34), fill=COLORS["ink"])
    y = 272
    blocks = [
        ("資料", f"台積電({stock})與台灣加權指數({index})"),
        ("期間", f"{period_start}至{period_end}"),
        ("樣本", f"{int(n_obs):,}個交易日"),
        ("事件A", f"台積電單日跌幅達3%以上：{int(n_3)}天"),
        ("事件B", f"台積電單日跌幅達5%以上：{int(n_5)}天（小樣本）"),
    ]
    for label, text in blocks:
        rounded_rect(draw, (110, y, 530, y + 74), fill=COLORS["soft"], outline=None, radius=8)
        draw.text((132, y + 19), label, font=fonts.bold(24), fill=COLORS["header"])
        draw_wrapped(draw, (230, y + 16), text, fonts.regular(24), COLORS["ink"], 278, line_gap=4)
        y += 92

    draw.text((610, 174), "比較設計", font=fonts.bold(34), fill=COLORS["ink"])
    draw.text((612, 218), "同一批事件日，分成三條觀察路徑；每條都和非事件日對照。", font=fonts.regular(25), fill=COLORS["muted"])

    center_x = 730
    t_box = (610, 300, 920, 414)
    rounded_rect(draw, t_box, fill=COLORS["header"], outline=None, radius=8)
    center_text(draw, (610, 310, 920, 348), "事件日 T", fonts.bold(28), "white")
    center_text(draw, (628, 354, 902, 396), "2330.TW 單日大跌", fonts.regular(25), "#D7E5F2")

    lanes = [
        ((1035, 250, 1490, 374), COLORS["red"], "同日方向", f"比較 {index}(T) 報酬與非事件日"),
        ((1035, 410, 1490, 534), COLORS["amber"], "隔日方向 T+1", f"比較 {index}(T+1) 報酬與非事件日"),
        ((1035, 570, 1490, 694), COLORS["blue"], "未來波動", f"計算事件後未來{int(horizon)}日已實現波動度"),
    ]
    for box, color, title, desc in lanes:
        x0, y0, x1, y1 = box
        arrow(draw, (920, 357), (1010, (y0 + y1) // 2), color)
        rounded_rect(draw, box, fill="#FFFFFF", outline=COLORS["line"], radius=8)
        draw.rectangle((x0, y0, x0 + 10, y1), fill=color)
        draw.text((x0 + 34, y0 + 24), title, font=fonts.bold(29), fill=COLORS["ink"])
        draw_wrapped(draw, (x0 + 34, y0 + 70), desc, fonts.regular(25), COLORS["muted"], x1 - x0 - 68, line_gap=6)

    beta_box = (610, 742, 1490, 850)
    rounded_rect(draw, beta_box, fill=COLORS["blue_soft"], outline=None, radius=8)
    draw.text((642, 766), "結構性連動", font=fonts.bold(29), fill=COLORS["header"])
    draw.text(
        (642, 810),
        "另以252日移動窗估計大盤對台積電的連動係數，追蹤集中度上升後的敏感度變化。",
        font=fonts.regular(25),
        fill=COLORS["ink"],
    )

    footer(draw, fonts)
    path = OUT_DIR / "method.png"
    img.save(path, dpi=DPI)
    return path


def result_row(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    y: int,
    title: str,
    n: int,
    same_p: float,
    same_mean: float,
    next_p: float,
    next_mean: float,
) -> None:
    draw.text((110, y + 10), f"{title}（N={n}）", font=fonts.bold(27), fill=COLORS["ink"])
    draw.text((425, y + 10), "同日", font=fonts.bold(25), fill=COLORS["red"])
    bar(draw, (500, y + 15, 820, y + 45), same_p, 1.0, COLORS["red"], COLORS["red_soft"])
    draw.text((840, y + 8), f"下跌{pct(same_p, 2)}｜平均{pct(same_mean, 2, signed=True)}", font=fonts.regular(24), fill=COLORS["ink"])
    draw.text((425, y + 68), "隔日", font=fonts.bold(25), fill=COLORS["amber"])
    bar(draw, (500, y + 73, 820, y + 103), next_p, 1.0, COLORS["amber"], COLORS["amber_soft"])
    draw.text((840, y + 66), f"下跌{pct(next_p, 2)}｜平均{pct(next_mean, 2, signed=True)}", font=fonts.regular(24), fill=COLORS["ink"])


def results_panel(data: dict[str, Any], fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["paper"])
    draw = ImageDraw.Draw(img)
    header(draw, fonts, "核心結果：同日成立、隔日迷思、波動放大", "K1635 事件研究摘要數字")

    t3 = get(data, "M2_transmission.thresholds.-3pct")
    t5 = get(data, "M2_transmission.thresholds.-5pct")
    beta_min = get(data, "M3_beta.rolling_beta_min")
    beta_last = get(data, "M3_beta.rolling_beta_last")
    vol3 = get(data, "M4_vol_transmission.thresholds.-3pct")
    vol5 = get(data, "M4_vol_transmission.thresholds.-5pct")

    direction_box = (80, 170, 1520, 498)
    rounded_rect(draw, direction_box, fill="#FFFFFF", outline=COLORS["line"], radius=8)
    draw.rectangle((80, 170, 1520, 180), fill=COLORS["red"])
    draw.text((110, 205), "方向傳導：台積電大跌日的大盤反應", font=fonts.bold(34), fill=COLORS["ink"])
    draw.text((1050, 208), "同日 / 隔日分開看", font=fonts.regular(25), fill=COLORS["muted"])
    result_row(
        draw,
        fonts,
        270,
        "跌3%以上",
        int(t3["n_drop_days"]),
        t3["same_day"]["p_twii_down"],
        t3["same_day"]["mean_twii_ret"],
        t3["next_day_T1"]["p_twii_down"],
        t3["next_day_T1"]["mean_twii_ret"],
    )
    result_row(
        draw,
        fonts,
        390,
        "跌5%以上",
        int(t5["n_drop_days"]),
        t5["same_day"]["p_twii_down"],
        t5["same_day"]["mean_twii_ret"],
        t5["next_day_T1"]["p_twii_down"],
        t5["next_day_T1"]["mean_twii_ret"],
    )

    beta_box = (80, 526, 760, 886)
    rounded_rect(draw, beta_box, fill="#FFFFFF", outline=COLORS["line"], radius=8)
    draw.rectangle((80, 526, 760, 536), fill=COLORS["blue"])
    draw.text((112, 560), "連動係數升高", font=fonts.bold(33), fill=COLORS["ink"])
    draw.text((112, 606), "252日移動窗：早期低點到最新值", font=fonts.regular(24), fill=COLORS["muted"])
    center_text(draw, (112, 658, 728, 744), f"{num(beta_min, 2)} → {num(beta_last, 2)}", fonts.bold(58), COLORS["blue"])
    draw.line((170, 808, 660, 726), fill=COLORS["blue"], width=8)
    draw.ellipse((156, 794, 184, 822), fill=COLORS["blue"])
    draw.ellipse((646, 712, 674, 740), fill=COLORS["blue"])
    draw.text((112, 840), "研究說明：2014約0.32–0.35，2025–26約0.70。", font=fonts.regular(22), fill=COLORS["muted"])

    vol_box = (840, 526, 1520, 886)
    rounded_rect(draw, vol_box, fill="#FFFFFF", outline=COLORS["line"], radius=8)
    draw.rectangle((840, 526, 1520, 536), fill=COLORS["teal"])
    draw.text((872, 560), "未來5日波動傳導", font=fonts.bold(33), fill=COLORS["ink"])
    draw.text((872, 606), "事件後大盤已實現波動度相對非事件日", font=fonts.regular(24), fill=COLORS["muted"])

    max_ratio = 2.5
    rows = [
        ("跌3%以上", vol3["ratio_event_vs_nonevent"], vol3["event_fwd5d_rv_mean"], vol3["nonevent_fwd5d_rv_mean"], 670),
        ("跌5%以上", vol5["ratio_event_vs_nonevent"], vol5["event_fwd5d_rv_mean"], vol5["nonevent_fwd5d_rv_mean"], 778),
    ]
    for label, r, ev, non, y in rows:
        draw.text((872, y), label, font=fonts.bold(27), fill=COLORS["ink"])
        bar(draw, (1040, y + 8, 1370, y + 42), float(r), max_ratio, COLORS["teal"], COLORS["teal_soft"])
        draw.text((1392, y - 2), ratio(r), font=fonts.bold(29), fill=COLORS["teal"])
        draw.text((1040, y + 52), f"事件{pct(ev, 1)}對非事件{pct(non, 1)}", font=fonts.regular(22), fill=COLORS["muted"])

    footer(draw, fonts)
    path = OUT_DIR / "results.png"
    img.save(path, dpi=DPI)
    return path


def assert_nonempty_png(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            raise RuntimeError(f"PNG 未產出：{path}")
        if path.stat().st_size <= 10_000:
            raise RuntimeError(f"PNG 檔案過小，疑似空白：{path}")
        with Image.open(path) as img:
            if img.size != (WIDTH, HEIGHT):
                raise RuntimeError(f"PNG 尺寸錯誤：{path} -> {img.size}")
            bbox = ImageChops.difference(img.convert("RGB"), Image.new("RGB", img.size, "white")).getbbox()
            if bbox is None:
                raise RuntimeError(f"PNG 疑似全白：{path}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fonts = load_fonts()
    data = load_results()

    paths = [
        concept_panel(data, fonts),
        method_panel(data, fonts),
        results_panel(data, fonts),
    ]
    assert_nonempty_png(paths)
    print("CJK font regular:", fonts.regular_path)
    print("CJK font bold:", fonts.bold_path)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
