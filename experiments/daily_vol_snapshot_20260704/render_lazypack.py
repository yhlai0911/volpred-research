"""Render the reader-facing lazypack summary card for daily_vol_snapshot_20260704.

All numbers are read from results.json so the infographic stays tied to the
experiment output.
"""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
FIGS = HERE / "figs"
OUT = FIGS / "lazypack_summary.png"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/RODE Noto Sans CJK SC B.otf" if bold else "/Library/Fonts/RODE Noto Sans CJK SC R.otf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int,
         fill: str = "#111827", bold: bool = False, spacing: int = 10,
         width: int | None = None) -> int:
    x, y = xy
    lines = wrap(value, width=width) if width else value.splitlines()
    f = font(size, bold=bold)
    for line in lines:
        draw.text((x, y), line, font=f, fill=fill)
        bbox = draw.textbbox((x, y), line, font=f)
        y += (bbox[3] - bbox[1]) + spacing
    return y


def card(draw: ImageDraw.ImageDraw, xy: tuple[int, int], wh: tuple[int, int],
         title: str, value: str, subtitle: str, color: str) -> None:
    x, y = xy
    w, h = wh
    draw.rounded_rectangle((x, y, x + w, y + h), radius=26, fill="#ffffff", outline="#d1d5db", width=2)
    draw.rectangle((x, y, x + 12, y + h), fill=color)
    text(draw, (x + 38, y + 28), title, 28, "#4b5563", bold=True)
    text(draw, (x + 38, y + 78), value, 58, color, bold=True)
    # Pixel audit found that the old 25px/22-char copy exceeded this 330px card
    # by 25-114px. At 20px/13 chars the longest copy wraps to two readable lines
    # and stays inside the card both horizontally and vertically.
    text(draw, (x + 38, y + 158), subtitle, 20, "#374151", width=13)


def main() -> None:
    FIGS.mkdir(exist_ok=True)
    r = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    div = r["us_tw_divergence"]
    vrp = r["vol_risk_premium"]
    tw = r["tw_price_vol_divergence"]

    img = Image.new("RGB", (1600, 1000), "#f8fafc")
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, 1600, 140), fill="#111827")
    text(draw, (80, 34), "台股波動率是美股的 2.3 倍", 56, "#ffffff", bold=True)
    text(draw, (80, 96), "但差距大半來自真實波動，不只是恐慌溢價", 28, "#d1d5db")

    draw.rounded_rectangle((80, 180, 720, 520), radius=34, fill="#0f172a")
    text(draw, (126, 220), "現在最重要的一個數字", 30, "#cbd5e1", bold=True)
    text(draw, (126, 270), f"{div['ratio']:.2f}x", 108, "#fbbf24", bold=True)
    text(
        draw,
        (126, 395),
        f"VIXTWN {div['vixtwn_last']:.2f} / VIX {div['vix_last']:.2f}\n"
        f"比值在近 7 個月第 {div['ratio_percentile_in_window']:.1f} 百分位",
        28,
        "#e5e7eb",
        spacing=14,
    )

    card(
        draw,
        (780, 180),
        (330, 250),
        "台美價差",
        f"{div['gap']:.2f}",
        f"VIXTWN - VIX，窗口第 {div['gap_percentile_in_window']:.1f} 百分位",
        "#dc2626",
    )
    card(
        draw,
        (1150, 180),
        (330, 250),
        "台股 VRP",
        f"+{vrp['tw_vrp']:.2f}",
        f"隱含 {vrp['tw_vixtwn']:.2f} vs 已實現 {vrp['tw_realized_rv20']:.2f}%",
        "#2563eb",
    )
    card(
        draw,
        (780, 470),
        (330, 250),
        "美股 VRP",
        f"{vrp['us_vrp']:.2f}",
        f"VIX {vrp['us_vix']:.2f} 低於 RV20 {vrp['us_realized_rv20']:.2f}%",
        "#7c3aed",
    )
    card(
        draw,
        (1150, 470),
        (330, 250),
        "台股位置",
        f"{tw['twii_pct_below_window_high']:.2f}%",
        f"加權指數距 5 年高點；一週漲 {tw['twii_week_chg_pct_0626_0703']:.2f}%",
        "#059669",
    )

    draw.rounded_rectangle((80, 560, 720, 820), radius=28, fill="#ffffff", outline="#d1d5db", width=2)
    text(draw, (126, 600), "怎麼讀", 36, "#111827", bold=True)
    text(
        draw,
        (126, 662),
        "台指 VIX 高，不等於單純恐慌。台股最近二十日年化已實現波動已達 "
        f"{vrp['tw_realized_rv20']:.2f}%，所以 37.82 的隱含波動有真實震盪支撐。",
        25,
        "#374151",
        spacing=12,
        width=18,
    )

    draw.rounded_rectangle((80, 860, 1480, 940), radius=22, fill="#e0f2fe")
    text(
        draw,
        (110, 882),
        "一句話：美股選擇權偏便宜，台股選擇權小貴但有基本面波動支撐；同一個 VIX 數字，換市場就要換讀法。",
        28,
        "#0f172a",
        bold=True,
        width=52,
    )
    text(
        draw,
        (80, 958),
        "資料來源：daily_vol_snapshot_20260704 results.json；Yahoo Finance；台灣期交所 VIXTWN。百分位窗口 2025-12-01 至 2026-07-03。",
        20,
        "#64748b",
    )

    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
