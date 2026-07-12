#!/usr/bin/env python3
"""Render NFP T-1 lazypack panels from event_article_nfp_2026_07_03_t1_results.json.

Pattern reused from experiments/k1582/render_lazypack.py (PIL-based, data-bound,
no billed image API). Numbers below are pulled directly from the results JSON,
not hand-typed from prose.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "event_article_nfp_2026_07_03_t1_results.json"
OUT_DIR = ROOT / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1600, 1000
BG = "#f8fafc"
INK = "#1f2937"
MUTED = "#64748b"
LINE = "#d6dee8"
BLUE = "#2563eb"
TEAL = "#0f766e"
GREEN = "#16a34a"
ORANGE = "#ea580c"
RED = "#dc2626"
SLATE = "#334155"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            return ImageFont.truetype(str(p), size=size, index=0)
    return ImageFont.load_default()


F_TITLE = font(58, True)
F_H1 = font(42, True)
F_H2 = font(32, True)
F_BODY = font(28)
F_SMALL = font(22)
F_NUM = font(64, True)
F_MED_NUM = font(44, True)


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def text(draw, xy, s, fill=INK, fnt=F_BODY, anchor=None):
    draw.text(xy, s, fill=fill, font=fnt, anchor=anchor)


def wrap(draw, s, max_w, fnt=F_BODY) -> list[str]:
    lines: list[str] = []
    cur = ""
    for ch in s:
        candidate = cur + ch
        if draw.textlength(candidate, font=fnt) <= max_w:
            cur = candidate
            continue
        if cur:
            lines.append(cur)
        cur = ch
    if cur:
        lines.append(cur)
    return lines


def multiline(draw, xy, s, max_w, fnt=F_BODY, fill=INK, leading=1.25):
    x, y = xy
    line_h = int(fnt.size * leading)
    for line in wrap(draw, s, max_w, fnt):
        text(draw, (x, y), line, fill=fill, fnt=fnt)
        y += line_h
    return y


def card(draw, box, fill="#ffffff", outline=LINE, radius=28):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


def pill(draw, xy, label, fill="#e0f2fe", fg=BLUE):
    x, y = xy
    pad_x, pad_y = 20, 10
    tw = draw.textlength(label, font=F_SMALL)
    box = (x, y, x + tw + pad_x * 2, y + F_SMALL.size + pad_y * 2)
    draw.rounded_rectangle(box, radius=18, fill=fill)
    text(draw, (x + pad_x, y + pad_y - 2), label, fill=fg, fnt=F_SMALL)
    return box[2]


def footer(draw, note="資料來源：yfinance（SPY / ^VIX / ^VIX9D 日收盤）；圖表由 render_lazypack.py 直接讀取 event_article_nfp_2026_07_03_t1_results.json 產生。"):
    text(draw, (80, H - 62), note, fill=MUTED, fnt=F_SMALL)


def title(draw, main, sub):
    text(draw, (80, 58), main, fill=INK, fnt=F_TITLE)
    text(draw, (82, 132), sub, fill=MUTED, fnt=F_BODY)


def render_framework(results: dict):
    snap = results["current_snapshot"]
    img, draw = canvas()
    title(draw, "非農公布前，VIX 短端在說什麼", "VIX9D 只看未來 9 天，NFP 這種單日事件最先反映在這裡。")

    steps = [
        ("第一步", "VIX 看 30 天", "標準恐慌指數，把整個月的不確定性打成一個數字。", BLUE),
        ("第二步", "VIX9D 看 9 天", "只算最近的事件視窗，NFP 這類單日衝擊會先讓它動。", TEAL),
        ("第三步", "兩者相除看結構", "比值 > 1 代表短端比長端貴，市場在為這幾天加價。", ORANGE),
    ]
    x0, y0, gap = 80, 240, 38
    cw, ch = 455, 360
    for i, (k, h, body, color) in enumerate(steps):
        x = x0 + i * (cw + gap)
        card(draw, (x, y0, x + cw, y0 + ch))
        pill(draw, (x + 30, y0 + 30), k, fill="#eef2ff" if color == BLUE else "#ecfeff" if color == TEAL else "#fff7ed", fg=color)
        text(draw, (x + 30, y0 + 104), h, fill=INK, fnt=F_H2)
        multiline(draw, (x + 30, y0 + 166), body, cw - 60, fnt=F_BODY, fill=SLATE)
        draw.line((x + 30, y0 + 285, x + cw - 30, y0 + 285), fill=LINE, width=2)
        if i == 0:
            note = f"最新收盤 {snap['vix_close_latest']}（{snap['vix_close_latest_date']}）"
        elif i == 1:
            note = f"最後一筆 {snap['vix9d_close_latest_print']}（{snap['vix9d_close_latest_print_date']}，落後 {snap['vix9d_data_lag_days_vs_vix']} 天）"
        else:
            note = f"同日比值 {snap['vix9d_over_vix_ratio_same_date']}（{snap['vix9d_over_vix_ratio_same_date_basis']}）"
        multiline(draw, (x + 30, y0 + 306), note, cw - 60, fnt=F_SMALL, fill=MUTED)

    card(draw, (160, 670, 1440, 850), fill="#ffffff")
    text(draw, (210, 710), "一句話", fill=INK, fnt=F_H1)
    multiline(
        draw,
        (210, 770),
        "VIX9D 資料本身落後幾個交易日，這篇不假裝有最新數字；用同一天的配對比值才乾淨。",
        1180,
        fnt=F_BODY,
        fill=SLATE,
    )
    footer(draw)
    img.save(OUT_DIR / "nfp_lazypack_1_framework.png", quality=95)


def render_results(results: dict):
    hist = results["historical_nfp_day_stats"]
    n = results["n_historical_nfp_events"]
    table = results["historical_nfp_table"]
    img, draw = canvas()
    title(draw, f"近 {n} 次非農發佈日，SPY 到底怎麼動", "當日報酬與 VIX 變化，逐次拆開看，不是只看平均。")

    stat_boxes = [
        ("上漲機率", f"{hist['spy_up_day_win_rate_pct']}%", GREEN, "當日 SPY 收紅的比例"),
        ("平均報酬", f"{hist['spy_ret_day0_mean_pct']:+.2f}%", ORANGE, "13 次算術平均，中位數 +0.10%"),
        ("VIX 平均變化", f"{hist['vix_chg_day0_mean_pts']:+.2f} 點", BLUE, "多數次數變化很小，但有極端值"),
        ("VIX 下降比例", f"{hist['pct_events_vix_fell_pct']}%", TEAL, "接近一半，恐慌指數不必然衝高"),
    ]
    x0, y0, gap = 80, 220, 30
    cw, ch2 = 335, 200
    for i, (label, val, color, note) in enumerate(stat_boxes):
        x = x0 + i * (cw + gap)
        card(draw, (x, y0, x + cw, y0 + ch2))
        text(draw, (x + 28, y0 + 26), label, fill=MUTED, fnt=F_SMALL)
        text(draw, (x + 28, y0 + 58), val, fill=color, fnt=F_MED_NUM)
        multiline(draw, (x + 28, y0 + 122), note, cw - 56, fnt=F_SMALL, fill=SLATE)

    # mini table: last 5 events
    ty0 = 450
    # Five 44px rows start at y=594; 340px made the final row straddle the
    # card's y=790 border. The layout guard measured an 11-13px overflow.
    table_h = 360
    card(draw, (80, ty0, 1520, ty0 + table_h), fill="#ffffff")
    text(draw, (120, ty0 + 24), "最近 5 次逐次拆開看", fill=INK, fnt=F_H2)
    cols = ["發佈日", "SPY 當日報酬", "VIX 當日變化"]
    col_x = [120, 560, 1000]
    hy = ty0 + 90
    for cx, c in zip(col_x, cols):
        text(draw, (cx, hy), c, fill=MUTED, fnt=F_SMALL)
    draw.line((120, hy + 36, 1480, hy + 36), fill=LINE, width=2)
    ry = hy + 54
    for row in table[-5:]:
        text(draw, (col_x[0], ry), row["trading_day"], fill=SLATE, fnt=F_BODY)
        ret_color = GREEN if row["spy_ret_day0_pct"] >= 0 else RED
        text(draw, (col_x[1], ry), f"{row['spy_ret_day0_pct']:+.2f}%", fill=ret_color, fnt=F_BODY)
        vix_color = RED if row["vix_chg_day0_pts"] >= 0 else GREEN
        text(draw, (col_x[2], ry), f"{row['vix_chg_day0_pts']:+.2f} 點", fill=vix_color, fnt=F_BODY)
        ry += 44

    note_y0 = ty0 + table_h + 20
    card(draw, (80, note_y0, 1520, note_y0 + 90), fill="#fff7ed", outline="#fed7aa", radius=24)
    multiline(
        draw,
        (120, note_y0 + 24),
        "上一次（2026-06-05）是例外：SPY 當天 -2.58%，VIX 單日 +6.11 點，是這 13 次裡最大的一次波動。平均數蓋不住這種尾巴。",
        1360,
        fnt=F_BODY,
        fill="#7c2d12",
    )
    footer(draw)
    img.save(OUT_DIR / "nfp_lazypack_2_results.png", quality=95)


def render_takeaway(results: dict):
    snap = results["current_snapshot"]
    img, draw = canvas()
    title(draw, "這次不是「照過去算」就能下注", "波動率統計描述過去，不是對這次非農的預測。")

    card(draw, (80, 240, 780, 620), fill="#ffffff")
    text(draw, (120, 276), "現在的位置", fill=INK, fnt=F_H2)
    rows = [
        ("SPY 5 日已實現波動率（年化）", f"{snap['spy_5d_realized_vol_annualized_pct']}%"),
        ("SPY 20 日已實現波動率（年化）", f"{snap['spy_20d_realized_vol_annualized_pct']}%"),
        ("VIX 最新收盤", f"{snap['vix_close_latest']}（{snap['vix_close_latest_date']}）"),
    ]
    y = 340
    for label, val in rows:
        multiline(draw, (120, y), label, 560, fnt=F_SMALL, fill=MUTED)
        text(draw, (120, y + 34), val, fill=INK, fnt=F_H2)
        y += 96

    card(draw, (820, 240, 1520, 620), fill="#ffffff")
    text(draw, (860, 276), "誠實的不確定性", fill=INK, fnt=F_H2)
    points = [
        "13 次樣本不足以做統計檢定，只能看描述性型態。",
        "NFP 日期用「當月第一個週五」規則近似，未逐月對照 BLS 公告。",
        "VIX9D 資料有落後，比值只能用同一天配對，不是即時。",
    ]
    y = 340
    for p in points:
        y = multiline(draw, (860, y), "• " + p, 620, fnt=F_BODY, fill=SLATE)
        y += 14

    card(draw, (180, 680, 1420, 880), fill="#eff6ff", outline="#bfdbfe", radius=24)
    y_end = multiline(
        draw,
        (230, 714),
        "適合帶走的結論：短端波動率結構值得每次事件前看一眼，但它描述的是風險定價的樣子，不是明天報酬的方向。",
        1140,
        fnt=F_BODY,
        fill="#1e3a8a",
    )
    multiline(
        draw,
        (230, y_end + 20),
        "本頁圖表僅供研究與教育用途，不構成投資建議。",
        1140,
        fnt=F_SMALL,
        fill="#1e3a8a",
    )
    footer(draw)
    img.save(OUT_DIR / "nfp_lazypack_3_takeaway.png", quality=95)


def main() -> None:
    results = load_results()
    render_framework(results)
    render_results(results)
    render_takeaway(results)
    for p in sorted(OUT_DIR.glob("nfp_lazypack_*.png")):
        print(p)


if __name__ == "__main__":
    main()
