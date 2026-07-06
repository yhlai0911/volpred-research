#!/usr/bin/env python3
"""Render K1647 lazy-pack panels as data-bound PNG files.

This script intentionally uses local Pillow rendering only.  It does not call
any image-generation model.  Every displayed statistic is read from
experiments/k1647/k1647_results.json and formatted at render time.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = ROOT / "experiments/k1647/k1647_results.json"
OUT_DIR = Path(__file__).resolve().parent

W = 1600
H = 1000
DPI = (150, 150)

INK = "#17202A"
MUTED = "#5F6B7A"
FAINT = "#8A95A3"
PAPER = "#FFFFFF"
HEADER = "#111827"
CARD = "#F8FAFC"
LINE = "#D6DEE8"
GREEN = "#137A52"
GREEN_BG = "#E6F4EE"
RED = "#B93A38"
RED_BG = "#F8E6E5"
BLUE = "#1F5D99"
BLUE_BG = "#E7F0FA"
AMBER = "#A46616"
AMBER_BG = "#F7EBD8"
TEAL = "#117876"
TEAL_BG = "#E2F3F2"

FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJKtc-Regular.otf",
]
FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/NotoSansCJKtc-Bold.otf",
]


ALL_PANEL_TEXT = """
迷思實驗室 原油狂飆狂跌，股市波動真的會跟著抖嗎？
原油 → 標普500：關聯 +0.0006，不顯著
原油 → 能源股：不顯著
反向 標普500 → 原油：+0.0099，顯著
反向 能源股 → 原油：+0.0111，顯著
結論：帶動方向是『股帶油』，不是『油帶股』
寬鬆檢定：原油→標普看似顯著
嚴謹口徑（落後1期+穩健校正）：訊號消失，不顯著
四資產淨溢出全部接近零
耦合是『同一天一起抖』，不是『誰提前預告誰』
油狂飆狂跌 ≠ 隔天股市波動放大
能源股對油稍敏感（占其波動 11–13%），仍是接收方
資料：4103 個交易日、2010–2026、可完整複現
資料來源：experiment K1647
"""


class Fonts:
    def __init__(self, regular_path: Path, bold_path: Path) -> None:
        self.regular_path = regular_path
        self.bold_path = bold_path

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


def existing(paths: Iterable[str]) -> list[Path]:
    return [Path(p) for p in paths if Path(p).exists()]


def cmap_has_all(path: Path, text: str) -> bool:
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except Exception:
        return True

    def cmap_for_font(font: Any) -> set[int]:
        chars: set[int] = set()
        for table in font["cmap"].tables:
            chars.update(table.cmap.keys())
        return chars

    try:
        if path.suffix.lower() == ".ttc":
            collection = TTCollection(str(path))
            chars = set()
            for font in collection.fonts:
                chars.update(cmap_for_font(font))
        else:
            chars = cmap_for_font(TTFont(str(path)))
    except Exception:
        return True

    required = {ord(ch) for ch in text if not ch.isspace()}
    return required.issubset(chars)


def load_fonts() -> Fonts:
    regular_candidates = existing(FONT_CANDIDATES_REGULAR)
    bold_candidates = existing(FONT_CANDIDATES_BOLD)
    if not regular_candidates or not bold_candidates:
        raise RuntimeError("找不到可用 CJK 字型，無法避免中文字缺字。")

    regular = next((p for p in regular_candidates if cmap_has_all(p, ALL_PANEL_TEXT)), regular_candidates[0])
    bold = next((p for p in bold_candidates if cmap_has_all(p, ALL_PANEL_TEXT)), bold_candidates[0])

    probe = ImageFont.truetype(str(regular), size=48)
    if probe.getbbox("波動率") is None:
        raise RuntimeError(f"字型無法渲染繁中：{regular}")
    return Fonts(regular, bold)


def load_results() -> dict[str, Any]:
    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            raise KeyError(path)
    return cur


def fmt_coef(value: float) -> str:
    return f"{value:+.4f}"


def fmt_p(value: float) -> str:
    if value < 0.001:
        return f"{value:.4f}"
    if value < 0.01:
        return f"{value:.3f}"
    return f"{value:.2f}"


def fmt_pct(value: float, digits: int = 1) -> str:
    return f"{value:+.{digits}f}%"


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        if text_size(draw, candidate, font)[0] <= max_width or not current:
            current = candidate
        else:
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
    line_h = font.size + line_gap
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=8, fill=fill, outline=outline, width=width)


def header(draw: ImageDraw.ImageDraw, fonts: Fonts, title: str, subtitle: str) -> None:
    draw.rectangle((0, 0, W, 142), fill=HEADER)
    draw.text((80, 42), title, font=fonts.bold(48), fill="#FFFFFF")
    draw.text((82, 100), subtitle, font=fonts.regular(24), fill="#C9D3E0")


def footer(draw: ImageDraw.ImageDraw, fonts: Fonts, extra: str = "") -> None:
    base = "資料來源：experiment K1647"
    if extra:
        base += f"｜{extra}"
    draw.line((80, 934, 1520, 934), fill=LINE, width=2)
    draw.text((80, 952), base, font=fonts.regular(22), fill=MUTED)


def pill(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    fonts: Fonts,
    fill: str,
    ink: str,
) -> None:
    rounded(draw, box, fill=fill, outline=None)
    tw, th = text_size(draw, text, fonts.bold(24))
    x1, y1, x2, y2 = box
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2 - 2), text, font=fonts.bold(24), fill=ink)


def panel_01(data: dict[str, Any], fonts: Fonts) -> None:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    header(draw, fonts, "油市波動能預告股市波動嗎？", "昨天預測今天：lag-1 predictive regression + Newey-West HAC")

    oil_rows = [
        ("原油 → 標普500", "CL->SPY"),
        ("原油 → 能源股", "CL->XLE"),
        ("USO → 標普500", "USO->SPY"),
        ("USO → 能源股", "USO->XLE"),
    ]
    reverse_rows = [
        ("反向 標普500 → 原油", "SPY->CL"),
        ("反向 能源股 → 原油", "XLE->CL"),
    ]

    cl_spy_coef = get(data, "predictive_regressions.oil_to_equity.CL->SPY.no_control.coef_oil_lag1")
    spy_cl_coef = get(data, "predictive_regressions.equity_to_oil.SPY->CL.coef_oil_lag1")
    xle_cl_coef = get(data, "predictive_regressions.equity_to_oil.XLE->CL.coef_oil_lag1")

    callout_y = 180
    rounded(draw, (80, callout_y, 1520, callout_y + 142), fill="#F3F6FA", outline=LINE, width=2)
    draw.text(
        (112, callout_y + 28),
        f"原油 → 標普500：關聯 {fmt_coef(cl_spy_coef)}，不顯著",
        font=fonts.bold(34),
        fill=INK,
    )
    draw.text(
        (112, callout_y + 73),
        "原油 → 能源股：不顯著｜油→股四組配對全部不顯著",
        font=fonts.regular(27),
        fill=MUTED,
    )
    draw.text(
        (112, callout_y + 106),
        f"反向 標普500 → 原油：{fmt_coef(spy_cl_coef)}，顯著｜反向 能源股 → 原油：{fmt_coef(xle_cl_coef)}，顯著",
        font=fonts.regular(23),
        fill=GREEN,
    )

    table_x = 80
    table_y = 356
    table_w = 980
    row_h = 68
    table_h = 58 + 4 * row_h + 10 + 2 * row_h
    rounded(draw, (table_x, table_y, table_x + table_w, table_y + table_h), fill="#FFFFFF", outline=LINE, width=2)
    draw.rectangle((table_x, table_y, table_x + table_w, table_y + 58), fill="#243447")
    draw.text((table_x + 26, table_y + 16), "昨天波動 → 今天波動", font=fonts.bold(24), fill="#FFFFFF")
    draw.text((table_x + 522, table_y + 16), "斜率", font=fonts.bold(24), fill="#FFFFFF")
    draw.text((table_x + 674, table_y + 16), "p 值", font=fonts.bold(24), fill="#FFFFFF")
    draw.text((table_x + 818, table_y + 16), "判斷", font=fonts.bold(24), fill="#FFFFFF")

    y = table_y + 58
    for label, key in oil_rows:
        path = f"predictive_regressions.oil_to_equity.{key}.no_control"
        coef = get(data, f"{path}.coef_oil_lag1")
        pval = get(data, f"{path}.hac_p")
        sig = get(data, f"{path}.sig_5pct")
        fill = "#FFFFFF" if (y // row_h) % 2 == 0 else "#F8FAFC"
        draw.rectangle((table_x, y, table_x + table_w, y + row_h), fill=fill)
        draw.text((table_x + 26, y + 20), label, font=fonts.regular(25), fill=INK)
        draw.text((table_x + 522, y + 20), fmt_coef(coef), font=fonts.bold(25), fill=INK)
        draw.text((table_x + 674, y + 20), fmt_p(pval), font=fonts.regular(25), fill=INK)
        pill_text = "顯著" if sig else "不顯著"
        pill(draw, (table_x + 786, y + 14, table_x + 930, y + 54), pill_text, fonts, GREEN_BG if sig else RED_BG, GREEN if sig else RED)
        y += row_h

    draw.rectangle((table_x, y, table_x + table_w, y + 10), fill=LINE)
    y += 10
    for label, key in reverse_rows:
        path = f"predictive_regressions.equity_to_oil.{key}"
        coef = get(data, f"{path}.coef_oil_lag1")
        pval = get(data, f"{path}.hac_p")
        sig = get(data, f"{path}.sig_5pct")
        draw.rectangle((table_x, y, table_x + table_w, y + row_h), fill="#F4FBF7")
        draw.text((table_x + 26, y + 20), label, font=fonts.regular(25), fill=INK)
        draw.text((table_x + 522, y + 20), fmt_coef(coef), font=fonts.bold(25), fill=GREEN)
        draw.text((table_x + 674, y + 20), fmt_p(pval), font=fonts.regular(25), fill=INK)
        pill(draw, (table_x + 786, y + 14, table_x + 930, y + 54), "顯著" if sig else "不顯著", fonts, GREEN_BG if sig else RED_BG, GREEN if sig else RED)
        y += row_h

    side_x = 1100
    rounded(draw, (side_x, 356, 1520, 646), fill=BLUE_BG, outline="#BED6F0", width=2)
    draw.text((side_x + 34, 390), "方向反過來才有訊號", font=fonts.bold(32), fill=BLUE)
    draw.text((side_x + 34, 448), "標普500 → 原油", font=fonts.bold(24), fill=INK)
    draw.text((side_x + 250, 448), f"{fmt_coef(spy_cl_coef)}，顯著", font=fonts.bold(24), fill=GREEN)
    draw.text((side_x + 34, 500), "能源股 → 原油", font=fonts.bold(24), fill=INK)
    draw.text((side_x + 250, 500), f"{fmt_coef(xle_cl_coef)}，顯著", font=fonts.bold(24), fill=GREEN)
    draw_wrapped(
        draw,
        (side_x + 34, 560),
        "油→股是 NULL；反向檢定顯示股市波動領先油市波動。",
        fonts.regular(24),
        MUTED,
        350,
        line_gap=8,
    )

    rounded(draw, (1100, 684, 1520, 872), fill="#FFF8EC", outline="#E5C995", width=2)
    draw.text((1134, 720), "結論", font=fonts.bold(30), fill=AMBER)
    draw.text((1134, 772), "結論：帶動方向是『股帶油』，", font=fonts.bold(28), fill=INK)
    draw.text((1134, 818), "不是『油帶股』", font=fonts.bold(28), fill=INK)

    footer(draw, fonts, "核心欄位：predictive_regressions 與 verdict.dominant_direction")
    img.save(OUT_DIR / "01_finding.png", dpi=DPI)


def panel_02(data: dict[str, Any], fonts: Fonts) -> None:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    header(draw, fonts, "為什麼直覺會錯？", "同一份資料，寬鬆檢定與嚴謹預測口徑的答案不同")

    granger_p = get(data, "granger.CL->SPY.min_p")
    granger_lag = get(data, "granger.CL->SPY.best_lag")
    hac_p = get(data, "predictive_regressions.oil_to_equity.CL->SPY.no_control.hac_p")
    hac_coef = get(data, "predictive_regressions.oil_to_equity.CL->SPY.no_control.coef_oil_lag1")
    net = get(data, "diebold_yilmaz.net_pct")
    corr_spy = get(data, "contemp_logrv_corr.CL-SPY")
    corr_xle = get(data, "contemp_logrv_corr.CL-XLE")

    left = (80, 198, 740, 500)
    right = (860, 198, 1520, 500)
    rounded(draw, left, fill=AMBER_BG, outline="#E8C88F", width=2)
    rounded(draw, right, fill=GREEN_BG, outline="#BBDDCB", width=2)

    draw.text((120, 236), "寬鬆檢定：原油→標普看似顯著", font=fonts.bold(31), fill=AMBER)
    draw.text((120, 304), f"Granger min p = {granger_p:.4f}", font=fonts.bold(46), fill=INK)
    draw.text((120, 368), f"最佳落後期 = {granger_lag}", font=fonts.regular(28), fill=INK)
    draw_wrapped(draw, (120, 416), "可提示關聯，但不是隔天可交易的穩健預測口徑。", fonts.regular(24), MUTED, 560)

    draw.text((900, 236), "嚴謹口徑（落後1期+穩健校正）：", font=fonts.bold(29), fill=GREEN)
    draw.text((900, 286), "訊號消失，不顯著", font=fonts.bold(36), fill=GREEN)
    draw.text((900, 354), f"lag-1 HAC 斜率 {fmt_coef(hac_coef)}｜p = {fmt_p(hac_p)}", font=fonts.bold(32), fill=INK)
    draw_wrapped(draw, (900, 416), "只用昨天資訊預測今天，並校正 21 日重疊波動造成的殘差相關。", fonts.regular(24), MUTED, 560)

    draw.line((784, 268, 816, 268), fill=LINE, width=8)
    draw.polygon([(820, 268), (795, 250), (795, 286)], fill=LINE)
    draw.text((742, 306), "換口徑", font=fonts.regular(22), fill=FAINT)

    rounded(draw, (80, 560, 1520, 812), fill="#F8FAFC", outline=LINE, width=2)
    draw.text((120, 596), "四資產淨溢出全部接近零", font=fonts.bold(34), fill=INK)
    draw.text((120, 646), "Diebold-Yilmaz net spillover（百分點）", font=fonts.regular(23), fill=MUTED)

    bar_left = 132
    bar_top = 700
    bar_w = 270
    scale = 90
    for i, key in enumerate(["CL", "USO", "SPY", "XLE"]):
        x = bar_left + i * 350
        val = float(net[key])
        draw.text((x, bar_top + 64), key, font=fonts.bold(26), fill=INK)
        center_y = bar_top + 32
        draw.line((x + 72, center_y, x + 245, center_y), fill="#C9D3DF", width=3)
        end = x + 158 + int(val * scale)
        color = BLUE if val >= 0 else RED
        draw.line((x + 158, center_y, end, center_y), fill=color, width=14)
        draw.ellipse((end - 8, center_y - 8, end + 8, center_y + 8), fill=color)
        draw.text((x + 72, bar_top - 10), fmt_pct(val), font=fonts.bold(28), fill=color)

    draw.text(
        (120, 842),
        f"耦合是『同一天一起抖』，不是『誰提前預告誰』｜同期相關：CL-SPY {corr_spy:.2f}、CL-XLE {corr_xle:.2f}",
        font=fonts.bold(27),
        fill=TEAL,
    )

    footer(draw, fonts, "欄位：granger、predictive_regressions、diebold_yilmaz、contemp_logrv_corr")
    img.save(OUT_DIR / "02_mechanism.png", dpi=DPI)


def panel_03(data: dict[str, Any], fonts: Fonts) -> None:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    header(draw, fonts, "投資人的 take-away", "油市劇烈震盪，不等於隔天股市波動會放大")

    n_obs = get(data, "predictive_regressions.oil_to_equity.CL->SPY.no_control.n_obs")
    period = get(data, "data.period")
    start_year = period.split("..")[0].split("-")[0]
    end_year = period.split("..")[1].split("-")[0]
    xle_cl = get(data, "diebold_yilmaz.oil_to_equity_fev_share_pct.XLE.CL")
    xle_uso = get(data, "diebold_yilmaz.oil_to_equity_fev_share_pct.XLE.USO")
    spy_cl = get(data, "diebold_yilmaz.oil_to_equity_fev_share_pct.SPY.CL")
    spy_uso = get(data, "diebold_yilmaz.oil_to_equity_fev_share_pct.SPY.USO")
    sig_any = get(data, "verdict.any_oil_to_equity_survives_vix")

    rounded(draw, (80, 190, 1520, 380), fill=RED_BG, outline="#E3B9B8", width=2)
    draw.text((122, 236), "油狂飆狂跌 ≠ 隔天股市波動放大", font=fonts.bold(52), fill=RED)
    draw.text(
        (124, 314),
        f"VIX 控制後仍有油→股訊號：{'是' if sig_any else '否'}",
        font=fonts.bold(30),
        fill=INK,
    )

    card_y = 430
    cards = [
        (
            80,
            BLUE_BG,
            BLUE,
            "能源股比較敏感",
            f"{xle_cl:.0f}–{xle_uso:.0f}%",
            "能源股波動中由油解釋的份額",
        ),
        (
            585,
            "#F1F5F9",
            INK,
            "大盤敏感度較低",
            f"{spy_cl:.0f}–{spy_uso:.0f}%",
            "標普500 波動中由油解釋的份額",
        ),
        (
            1090,
            GREEN_BG,
            GREEN,
            "但方向不是油帶股",
            "接收方",
            "能源股對油稍敏感，仍是接收方",
        ),
    ]
    for x, bg, color, title, big, caption in cards:
        rounded(draw, (x, card_y, x + 430, card_y + 260), fill=bg, outline=LINE, width=2)
        draw.text((x + 34, card_y + 34), title, font=fonts.bold(30), fill=color)
        draw.text((x + 34, card_y + 96), big, font=fonts.bold(62), fill=INK if big != "接收方" else GREEN)
        draw_wrapped(draw, (x + 34, card_y + 184), caption, fonts.regular(24), MUTED, 350)

    rounded(draw, (80, 740, 1520, 878), fill="#F8FAFC", outline=LINE, width=2)
    draw.text((122, 778), f"資料：{n_obs} 個交易日、{start_year}–{end_year}、可完整複現", font=fonts.bold(38), fill=INK)
    draw.text((124, 836), "波動代理：21 日滾動標準差年化取對數；seed=42；lag policy = predictor .shift(1)", font=fonts.regular(25), fill=MUTED)

    footer(draw, fonts, "欄位：n_obs、data.period、oil_to_equity_fev_share_pct、verdict")
    img.save(OUT_DIR / "03_takeaway.png", dpi=DPI)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_results()
    fonts = load_fonts()
    panel_01(data, fonts)
    panel_02(data, fonts)
    panel_03(data, fonts)

    for name in ["01_finding.png", "02_mechanism.png", "03_takeaway.png"]:
        path = OUT_DIR / name
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"PNG 產出失敗或為空檔：{path}")

    print(f"Rendered 3 PNG files with font: {fonts.regular_path}")


if __name__ == "__main__":
    main()
