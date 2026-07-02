#!/usr/bin/env python3
"""Render K1568 data-bound lazypack PNG panels.

The renderer is intentionally local and deterministic. It reads the K1568
evidence package, binds displayed statistics to k1568_results.json fields, and
writes three 1600x1000 PNG files. It does not call any image generation model.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "experiments/k1568/k1568_results.json"
README_PATH = ROOT / "experiments/k1568/README.md"
ARTICLE_PATH = Path("/var/folders/f1/g41vrs0n20v7cx66qzcsd1nc0000gn/T/tmp0qq1zo3__article.md")

FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]
FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]

NAVY = "#182335"
INK = "#1E2633"
MUTED = "#5F6B7A"
FAINT = "#8D99A8"
LINE = "#D8DEE8"
PAPER = "#FFFFFF"
SOFT_BG = "#F5F7FA"
BLUE = "#245C9F"
BLUE_SOFT = "#E6EFFA"
TEAL = "#177C7D"
TEAL_SOFT = "#E0F2F1"
AMBER = "#A66A1F"
AMBER_SOFT = "#F4E7D2"
RED = "#B33B3B"
RED_SOFT = "#F4DEDE"
GREEN = "#2E7D57"
GREEN_SOFT = "#E1F0E8"
GRAY_CARD = "#F0F3F7"


@dataclass(frozen=True)
class FontBook:
    regular_path: Path
    bold_path: Path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


@dataclass(frozen=True)
class Metrics:
    experiment_id: str
    sample_start: str
    sample_end: str
    docs: int
    primary_family_count: int
    raw_pass_count: int
    strict_pass_count: int
    xli_t: float
    xli_rho: float
    xlv_t: float
    bank_raw_count: int


def first_existing(paths: list[str]) -> Path:
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    raise RuntimeError("No Traditional Chinese capable local font was found.")


def load_fonts() -> FontBook:
    regular = first_existing(FONT_CANDIDATES_REGULAR)
    bold = first_existing(FONT_CANDIDATES_BOLD)
    font = ImageFont.truetype(str(regular), size=48)
    if not font.getmask("監管波動率").getbbox():
        raise RuntimeError(f"Selected font cannot render Traditional Chinese: {regular}")
    configure_matplotlib_if_available(regular)
    return FontBook(regular_path=regular, bold_path=bold)


def configure_matplotlib_if_available(font_path: Path) -> None:
    """Set CJK rcParams when matplotlib is present; rendering uses Pillow."""
    try:
        import matplotlib as mpl
        from matplotlib import font_manager

        font_manager.fontManager.addfont(str(font_path))
        font_name = font_manager.FontProperties(fname=str(font_path)).get_name()
        mpl.rcParams["font.sans-serif"] = [font_name, "Heiti TC", "PingFang TC", "Arial Unicode MS"]
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        return


def load_text(path: Path, *, required: bool) -> str:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return ""
    return path.read_text(encoding="utf-8")


def load_evidence() -> dict[str, Any]:
    readme = load_text(README_PATH, required=True)
    article = load_text(ARTICLE_PATH, required=False)
    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        results = json.load(fh)

    required_context = ["78,564", "144", "14", "0"]
    context_blob = readme + "\n" + article
    missing = [token for token in required_context if token not in context_blob]
    if missing:
        raise RuntimeError(f"Evidence prose does not contain expected tokens: {missing}")
    return results


def at(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            raise KeyError(f"Missing evidence field: {path}")
    return cur


def parse_primary_family(text: str) -> int:
    match = re.search(r"=\s*([0-9,]+)\s+controlled-HAC", text)
    if not match:
        raise ValueError(f"Cannot parse primary family count from: {text}")
    return int(match.group(1).replace(",", ""))


def build_metrics(results: dict[str, Any]) -> Metrics:
    raw_labels = list(at(results, "verdict_assessment.positive_raw_p_lt_0_05"))
    strict_labels = set(at(results, "verdict_assessment.positive_bonferroni_survivors")) | set(
        at(results, "verdict_assessment.positive_holm_survivors")
    )
    bank_raw = [label for label in raw_labels if label.startswith("KRE|") or label.startswith("KBE|")]

    return Metrics(
        experiment_id=str(at(results, "metadata.experiment_id")),
        sample_start=str(at(results, "sample.start")),
        sample_end=str(at(results, "sample.end")),
        docs=int(at(results, "sample.federal_register_docs")),
        primary_family_count=parse_primary_family(str(at(results, "methodology.primary_family"))),
        raw_pass_count=len(raw_labels),
        strict_pass_count=len(strict_labels),
        xli_t=float(
            at(
                results,
                "primary_tests.XLI.5d.log_downside_var.proposed_rule_flow_stress.controlled_hac.hac_t",
            )
        ),
        xli_rho=float(
            at(results, "primary_tests.XLI.5d.log_downside_var.proposed_rule_flow_stress.spearman.rho")
        ),
        xlv_t=float(at(results, "primary_tests.XLV.5d.log_rv.proposed_rule_flow_stress.controlled_hac.hac_t")),
        bank_raw_count=len(bank_raw),
    )


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_float(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            trial = current + ch
            if text_size(draw, trial, font)[0] <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = ch.lstrip()
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
    *,
    line_gap: int = 8,
) -> int:
    x, y = xy
    _, line_h = text_size(draw, "波動率Ag", font)
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + line_gap
    return y


def draw_centered(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    w, _ = text_size(draw, text, font)
    draw.text((center_x - w // 2, y), text, font=font, fill=fill)


def draw_right(
    draw: ImageDraw.ImageDraw,
    right_x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    w, _ = text_size(draw, text, font)
    draw.text((right_x - w, y), text, font=font, fill=fill)


def card(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], *, fill: str = PAPER, outline: str = LINE) -> None:
    draw.rounded_rectangle(xy, radius=8, fill=fill, outline=outline, width=2)


def header(draw: ImageDraw.ImageDraw, fonts: FontBook, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, 142), fill=NAVY)
    draw.text((80, 28), title, font=fonts.bold(48), fill="#FFFFFF")
    draw.text((80, 92), subtitle, font=fonts.regular(27), fill="#D9E2EF")
    draw.text((WIDTH - 250, 40), "VolPred 懶人包", font=fonts.regular(24), fill="#B9C7D8")


def footer(draw: ImageDraw.ImageDraw, fonts: FontBook, metrics: Metrics) -> None:
    draw.line((80, HEIGHT - 74, WIDTH - 80, HEIGHT - 74), fill=LINE, width=2)
    source = f"資料來源：experiment {metrics.experiment_id}；Federal Register API、yfinance adjusted OHLCV"
    span = f"樣本：{metrics.sample_start} 至 {metrics.sample_end}"
    draw.text((80, HEIGHT - 50), source, font=fonts.regular(21), fill=MUTED)
    draw_right(draw, WIDTH - 80, HEIGHT - 50, span, fonts.regular(21), MUTED)


def draw_document_icon(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    for offset in (20, 10, 0):
        draw.rounded_rectangle((x + offset, y + offset, x + 112 + offset, y + 150 + offset), radius=6, fill="#FFFFFF", outline=color, width=3)
        draw.line((x + 24 + offset, y + 45 + offset, x + 92 + offset, y + 45 + offset), fill=color, width=3)
        draw.line((x + 24 + offset, y + 78 + offset, x + 92 + offset, y + 78 + offset), fill=color, width=3)


def draw_arrow(draw: ImageDraw.ImageDraw, x1: int, y: int, x2: int, color: str) -> None:
    draw.line((x1, y, x2 - 18, y), fill=color, width=6)
    draw.polygon([(x2, y), (x2 - 24, y - 16), (x2 - 24, y + 16)], fill=color)


def draw_signal_icon(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    draw.line((x, y + 120, x + 150, y + 120), fill=color, width=4)
    draw.line((x + 25, y + 95, x + 68, y + 62), fill=color, width=6)
    draw.line((x + 68, y + 62, x + 112, y + 32), fill=color, width=6)
    draw.polygon([(x + 123, y + 25), (x + 103, y + 29), (x + 115, y + 45)], fill=color)


def draw_zero_icon(draw: ImageDraw.ImageDraw, x: int, y: int, color: str, font: ImageFont.FreeTypeFont) -> None:
    draw.ellipse((x, y, x + 140, y + 140), outline=color, width=8, fill="#FFFFFF")
    draw_centered(draw, x + 70, y + 28, "0", font, color)


def render_panel_1(metrics: Metrics, fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    header(draw, fonts, "監管文件很多，校正後還不是交易訊號", "公開規則流量可以當研究入口，但不能直接跳成交易規則")

    intro = "這次測試把 Federal Register 規則與擬議規則流量，延後一天後檢查 ETF 未來波動與下跌風險。"
    draw_wrapped(draw, (90, 178), intro, fonts.regular(28), INK, 1360)

    docs_phrase = f"{fmt_int(metrics.docs)} 份 Federal Register 文件"
    family_phrase = f"{metrics.primary_family_count} 種組合"
    raw_phrase = f"{metrics.raw_pass_count} 種初步過關"
    strict_phrase = f"{metrics.strict_pass_count} 種嚴格校正後通過"

    y0 = 275
    card_w = 410
    card_h = 420
    xs = [90, 595, 1100]
    palette = [(BLUE, BLUE_SOFT), (AMBER, AMBER_SOFT), (RED, RED_SOFT)]

    for x, (accent, soft) in zip(xs, palette, strict=False):
        card(draw, (x, y0, x + card_w, y0 + card_h), fill="#FFFFFF")
        draw.rectangle((x, y0, x + card_w, y0 + 10), fill=accent)

    draw_document_icon(draw, xs[0] + 44, y0 + 66, BLUE)
    draw.text((xs[0] + 190, y0 + 72), "監管文件變多", font=fonts.bold(31), fill=INK)
    draw.text((xs[0] + 190, y0 + 126), fmt_int(metrics.docs), font=fonts.bold(47), fill=BLUE)
    draw.text((xs[0] + 44, y0 + 254), docs_phrase, font=fonts.bold(22), fill=BLUE)
    draw_wrapped(draw, (xs[0] + 44, y0 + 302), "公開文件量夠大，但它只是廣域規則流量代理，不等於企業真實法遵成本。", fonts.regular(23), MUTED, 320)

    draw_signal_icon(draw, xs[1] + 45, y0 + 76, AMBER)
    draw.text((xs[1] + 195, y0 + 74), "初步方向性", font=fonts.bold(31), fill=INK)
    draw.text((xs[1] + 195, y0 + 126), family_phrase, font=fonts.bold(35), fill=AMBER)
    draw.rounded_rectangle((xs[1] + 45, y0 + 232, xs[1] + 365, y0 + 292), radius=8, fill=AMBER_SOFT, outline="#E1C28D", width=2)
    draw_centered(draw, xs[1] + 205, y0 + 244, raw_phrase, fonts.bold(28), AMBER)
    draw_wrapped(draw, (xs[1] + 45, y0 + 320), "看得到一些漂亮格子，但同時檢查很多格時，不能只挑最亮的結果。", fonts.regular(25), MUTED, 320)

    draw_zero_icon(draw, xs[2] + 50, y0 + 82, RED, fonts.bold(72))
    draw.text((xs[2] + 205, y0 + 76), "嚴格校正後", font=fonts.bold(31), fill=INK)
    draw_wrapped(draw, (xs[2] + 205, y0 + 126), strict_phrase, fonts.bold(34), RED, 170, line_gap=6)
    draw_wrapped(draw, (xs[2] + 48, y0 + 260), "Bonferroni / Holm 後沒有留下可宣稱的穩健訊號；結論只能是 raw-only 線索。", fonts.regular(25), MUTED, 320)

    draw_arrow(draw, 520, y0 + 210, 575, FAINT)
    draw_arrow(draw, 1025, y0 + 210, 1080, FAINT)

    note_box = (120, 745, WIDTH - 120, 850)
    card(draw, note_box, fill=SOFT_BG, outline="#E2E7EF")
    draw_wrapped(
        draw,
        (155, 770),
        "讀法：監管新聞很多，先當研究線索；要變成波動率訊號，必須先通過多重檢定與更細資料切分。",
        fonts.bold(29),
        INK,
        1280,
    )

    footer(draw, fonts, metrics)
    path = OUT_DIR / "01_signal_vs_evidence.png"
    img.save(path, dpi=DPI)
    return path


def sector_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    xy: tuple[int, int, int, int],
    *,
    accent: str,
    soft: str,
    title: str,
    stat: str | None,
    body: str,
) -> None:
    x1, y1, x2, y2 = xy
    card(draw, xy, fill="#FFFFFF")
    draw.rectangle((x1, y1, x2, y1 + 10), fill=accent)
    draw_wrapped(draw, (x1 + 32, y1 + 34), title, fonts.bold(29), INK, x2 - x1 - 64, line_gap=7)
    if stat:
        draw.rounded_rectangle((x1 + 32, y1 + 182, x2 - 32, y1 + 300), radius=8, fill=soft, outline=accent, width=2)
        draw_centered(draw, (x1 + x2) // 2, y1 + 202, stat, fonts.bold(64), accent)
        draw_centered(draw, (x1 + x2) // 2, y1 + 270, "controlled HAC t", fonts.regular(23), MUTED)
        body_y = y1 + 340
    else:
        draw.rounded_rectangle((x1 + 32, y1 + 174, x2 - 32, y1 + 282), radius=8, fill=soft, outline="#C7CED8", width=2)
        draw_centered(draw, (x1 + x2) // 2, y1 + 205, "無清楚訊號", fonts.bold(38), accent)
        body_y = y1 + 330
    draw_wrapped(draw, (x1 + 32, body_y), body, fonts.regular(25), MUTED, x2 - x1 - 64)


def render_panel_2(metrics: Metrics, fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    header(draw, fonts, "哪裡看得到方向？", "工業與醫療有初步格；區域銀行沒有形成清楚訊號")

    xli_sentence = f"XLI 工業：最強初步格，統計強度 {fmt_float(metrics.xli_t, 2)}，排名相關 {fmt_float(metrics.xli_rho, 3)}"
    xlv_sentence = f"XLV 醫療：初步格，統計強度 {fmt_float(metrics.xlv_t, 2)}"
    bank_sentence = "KRE/KBE：沒有清楚通過訊號"

    y = 205
    h = 520
    sector_card(
        draw,
        fonts,
        (80, y, 510, y + h),
        accent=BLUE,
        soft=BLUE_SOFT,
        title=xli_sentence,
        stat=fmt_float(metrics.xli_t, 2),
        body="方向性集中在擬議規則流量與 5 日下跌風險，但仍只是初步格，不能升級成穩健交易訊號。",
    )
    sector_card(
        draw,
        fonts,
        (585, y, 1015, y + h),
        accent=TEAL,
        soft=TEAL_SOFT,
        title=xlv_sentence,
        stat=fmt_float(metrics.xlv_t, 2),
        body="醫療 ETF 也出現 raw-only 線索；排名與尾端診斷沒有強到足以撐起直接交易結論。",
    )
    sector_card(
        draw,
        fonts,
        (1090, y, 1520, y + h),
        accent=MUTED,
        soft=GRAY_CARD,
        title=bank_sentence,
        stat=None,
        body=f"KRE/KBE 在初步過關清單中的格數為 {metrics.bank_raw_count}。廣域規則流量太粗，不能直接當區域銀行訊號。",
    )

    conclusion = "結論：廣域 Federal Register 流量比較像研究篩網；真正要做區域銀行，必須切到機關、產業與規則類型。"
    card(draw, (120, 775, WIDTH - 120, 862), fill=SOFT_BG, outline="#E2E7EF")
    draw_wrapped(draw, (155, 798), conclusion, fonts.bold(28), INK, 1270)

    footer(draw, fonts, metrics)
    path = OUT_DIR / "02_where_signal_appears.png"
    img.save(path, dpi=DPI)
    return path


def draw_takeaway_card(
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    xy: tuple[int, int, int, int],
    *,
    accent: str,
    soft: str,
    title: str,
    body: str,
) -> None:
    x1, y1, x2, y2 = xy
    card(draw, xy, fill="#FFFFFF")
    draw.rounded_rectangle((x1 + 34, y1 + 34, x1 + 116, y1 + 116), radius=8, fill=soft, outline=accent, width=3)
    draw.line((x1 + 58, y1 + 76, x1 + 78, y1 + 98), fill=accent, width=7)
    draw.line((x1 + 78, y1 + 98, x1 + 102, y1 + 56), fill=accent, width=7)
    draw.text((x1 + 145, y1 + 30), title, font=fonts.bold(38), fill=INK)
    draw_wrapped(draw, (x1 + 145, y1 + 88), body, fonts.regular(27), MUTED, x2 - x1 - 190)


def render_panel_3(metrics: Metrics, fonts: FontBook) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    header(draw, fonts, "投資人怎麼用？", "看到監管新聞時，先做資料切分，再談波動率訊號")

    card(draw, (90, 178, WIDTH - 90, 258), fill=SOFT_BG, outline="#E2E7EF")
    draw_wrapped(
        draw,
        (125, 199),
        f"本次 {metrics.primary_family_count} 格測試中，嚴格校正後 {metrics.strict_pass_count} 格通過；因此操作上要先降一階使用。",
        fonts.bold(28),
        INK,
        1330,
    )

    draw_takeaway_card(
        draw,
        fonts,
        (120, 310, WIDTH - 120, 445),
        accent=BLUE,
        soft=BLUE_SOFT,
        title="監管新聞 = 研究線索",
        body="新聞可以提示風險來源，但只代表值得追查，不代表市場已經給出可交易訊號。",
    )
    draw_takeaway_card(
        draw,
        fonts,
        (120, 490, WIDTH - 120, 625),
        accent=RED,
        soft=RED_SOFT,
        title="不是直接交易按鈕",
        body="廣域文件總量容易稀釋產業差異；不要把「監管變嚴」直接翻成買賣 ETF。",
    )
    draw_takeaway_card(
        draw,
        fonts,
        (120, 670, WIDTH - 120, 805),
        accent=GREEN,
        soft=GREEN_SOFT,
        title="下一步：機關、產業、生效日",
        body="更有用的資料粒度，是哪個主管機關、打到哪個產業、成本在公告日還是生效日落地。",
    )

    footer(draw, fonts, metrics)
    path = OUT_DIR / "03_investor_takeaway.png"
    img.save(path, dpi=DPI)
    return path


def main() -> None:
    fonts = load_fonts()
    results = load_evidence()
    metrics = build_metrics(results)

    generated = [
        render_panel_1(metrics, fonts),
        render_panel_2(metrics, fonts),
        render_panel_3(metrics, fonts),
    ]

    for path in generated:
        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError(f"Failed to render non-empty PNG: {path}")
        print(path)


if __name__ == "__main__":
    main()
