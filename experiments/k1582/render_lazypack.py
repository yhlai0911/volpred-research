#!/usr/bin/env python3
"""Render K1582 lazypack panels from the experiment results JSON."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "K1582_results.json"
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


def market(results: dict, name: str) -> dict:
    return next(m for m in results["markets"] if m["market"] == name)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def text(draw: ImageDraw.ImageDraw, xy, s: str, fill=INK, fnt=F_BODY, anchor=None):
    draw.text(xy, s, fill=fill, font=fnt, anchor=anchor)


def wrap(draw: ImageDraw.ImageDraw, s: str, max_w: int, fnt=F_BODY) -> list[str]:
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


def multiline(draw: ImageDraw.ImageDraw, xy, s: str, max_w: int, fnt=F_BODY, fill=INK, leading=1.25):
    x, y = xy
    line_h = int(fnt.size * leading)
    for line in wrap(draw, s, max_w, fnt):
        text(draw, (x, y), line, fill=fill, fnt=fnt)
        y += line_h
    return y


def card(draw: ImageDraw.ImageDraw, box, fill="#ffffff", outline=LINE, radius=28):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


def pill(draw: ImageDraw.ImageDraw, xy, label: str, fill="#e0f2fe", fg=BLUE):
    x, y = xy
    pad_x, pad_y = 20, 10
    tw = draw.textlength(label, font=F_SMALL)
    box = (x, y, x + tw + pad_x * 2, y + F_SMALL.size + pad_y * 2)
    draw.rounded_rectangle(box, radius=18, fill=fill)
    text(draw, (x + pad_x, y + pad_y - 2), label, fill=fg, fnt=F_SMALL)
    return box[2]


def footer(draw: ImageDraw.ImageDraw):
    text(draw, (80, H - 62), "資料來源：experiment K1582 / K1582_results.json；圖表由 render_lazypack.py 直接讀取結果檔產生。", fill=MUTED, fnt=F_SMALL)


def title(draw: ImageDraw.ImageDraw, main: str, sub: str):
    text(draw, (80, 58), main, fill=INK, fnt=F_TITLE)
    text(draw, (82, 132), sub, fill=MUTED, fnt=F_BODY)


def render_framework(results: dict):
    img, draw = canvas()
    title(draw, "更細的資料，要先過三關", "高頻資料能拆出更多細節；能不能拿來改善預測，是另一件事。")

    steps = [
        ("第一關", "資訊只能來自昨天以前", "每個預測欄位都先做 lag，當天資料不能偷跑進模型。", BLUE),
        ("第二關", "樣本要夠長", "短樣本只能做流程測試，不能拿來下市場結論。", TEAL),
        ("第三關", "改善要經得起嚴格檢驗", "方向對還不夠，改善幅度必須大到不像雜訊。", ORANGE),
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
            note = "結果檔標示：lookahead clean"
        elif i == 1:
            note = f"台指期可檢樣本：{market(results, 'TX_active')['n_oos']} 筆"
        else:
            note = "本次判定：方向性，不升格"
        multiline(draw, (x + 30, y0 + 306), note, cw - 60, fnt=F_SMALL, fill=MUTED)

    card(draw, (160, 670, 1440, 850), fill="#ffffff")
    text(draw, (210, 710), "一句話", fill=INK, fnt=F_H1)
    multiline(
        draw,
        (210, 770),
        "把每五分鐘資料拆得更精細，確實讓台指期日盤的預測誤差往好的方向動了一點；但這一點還沒有大到能宣稱新模型穩定勝出。",
        1180,
        fnt=F_BODY,
        fill=SLATE,
    )
    footer(draw)
    img.save(OUT_DIR / "k1582_lazypack_1_framework.png", quality=95)


def render_sample_gate(results: dict):
    img, draw = canvas()
    title(draw, "三個市場，只有一個能正式判斷", "同一套流程跑三個市場；結論強度由樣本長度決定。")

    rows = [
        ("台指期日盤", market(results, "TX_active"), GREEN),
        ("SPY", market(results, "SPY"), ORANGE),
        ("0050.TW", market(results, "0050.TW"), RED),
    ]
    left, top = 100, 250
    widths = [270, 360, 260, 250, 250]
    headers = ["市場", "原始期間", "樣本外筆數", "能否正式判斷", "結果定位"]
    x = left
    for w, h in zip(widths, headers):
        card(draw, (x, top, x + w, top + 76), fill="#e2e8f0", radius=14)
        text(draw, (x + 24, top + 20), h, fill=INK, fnt=F_SMALL)
        x += w

    y = top + 95
    for label, m, color in rows:
        x = left
        h = 138
        date_range = f"{m['date_range_raw'][0]} 到 {m['date_range_raw'][1]}"
        verdict = "可判斷" if m["gateable"] else "樣本太短"
        position = "方向性改善" if label == "台指期日盤" else "流程檢查"
        values = [label, date_range, str(m["n_oos"]), verdict, position]
        for idx, (w, val) in enumerate(zip(widths, values)):
            fill = "#ffffff"
            card(draw, (x, y, x + w, y + h), fill=fill, radius=14)
            if idx == 2:
                text(draw, (x + 24, y + 38), val, fill=color, fnt=F_MED_NUM)
                text(draw, (x + 24, y + 92), "筆", fill=MUTED, fnt=F_SMALL)
            elif idx == 3:
                pill(draw, (x + 24, y + 43), val, fill="#dcfce7" if m["gateable"] else "#fee2e2", fg=color)
            else:
                multiline(draw, (x + 24, y + 34), val, w - 48, fnt=F_BODY if idx == 0 else F_SMALL, fill=INK if idx == 0 else SLATE)
            x += w
        y += h + 24

    card(draw, (180, 800, 1420, 900), fill="#fff7ed", outline="#fed7aa", radius=24)
    multiline(draw, (230, 826), "SPY 只有 51 筆、0050.TW 只有 38 筆樣本外預測，低於 252 筆的最低門檻；不能拿這兩個市場說模型有效或無效。", 1140, fnt=F_BODY, fill="#7c2d12")
    footer(draw)
    img.save(OUT_DIR / "k1582_lazypack_2_sample_gate.png", quality=95)


def render_results(results: dict):
    img, draw = canvas()
    title(draw, "台指期：有改善，還不到勝利", "兩個修正版都比基本版低一點誤差；專案判定仍停在方向性結果。")

    tx = market(results, "TX_active")
    bars = [
        ("基本版", 0.0, SLATE),
        ("修正版 A", tx["pairwise_vs_har"]["HARQ"]["qlike_improvement_pct"], BLUE),
        ("修正版 B", tx["pairwise_vs_har"]["SHARK_like"]["qlike_improvement_pct"], GREEN),
    ]
    chart_box = (130, 250, 1020, 720)
    card(draw, chart_box, fill="#ffffff")
    text(draw, (170, 290), "預測誤差相對基本版改善", fill=INK, fnt=F_H2)
    base_x, base_y = 210, 635
    bar_w, max_h = 170, 260
    max_val = 2.6
    for i, (label, val, color) in enumerate(bars):
        x = base_x + i * 250
        h = int(max_h * max(val, 0) / max_val)
        draw.rounded_rectangle((x, base_y - h, x + bar_w, base_y), radius=18, fill=color)
        text(draw, (x + bar_w / 2, base_y + 28), label, fill=SLATE, fnt=F_BODY, anchor="ma")
        shown = "基準" if val == 0 else f"+{val:.2f}%"
        text(draw, (x + bar_w / 2, base_y - h - 58), shown, fill=color if val else SLATE, fnt=F_MED_NUM, anchor="ma")
    draw.line((180, base_y, 960, base_y), fill=LINE, width=2)

    card(draw, (1080, 250, 1470, 720), fill="#ffffff")
    text(draw, (1120, 292), "判讀", fill=INK, fnt=F_H2)
    points = [
        ("方向", "兩個修正版都往好的方向。", GREEN),
        ("幅度", "最佳改善只有約 2%。", ORANGE),
        ("結論", "不能升格成模型勝利。", RED),
    ]
    y = 360
    for k, body, color in points:
        pill(draw, (1120, y), k, fill="#f1f5f9", fg=color)
        multiline(draw, (1120, y + 58), body, 300, fnt=F_BODY, fill=SLATE)
        y += 120

    card(draw, (180, 785, 1420, 895), fill="#eff6ff", outline="#bfdbfe", radius=24)
    multiline(draw, (230, 814), "適合寫進研究筆記的結論：細分資料有方向性價值。還不適合寫成投資建議的結論：新模型已經穩定打敗基本版。", 1140, fnt=F_BODY, fill="#1e3a8a")
    footer(draw)
    img.save(OUT_DIR / "k1582_lazypack_3_results.png", quality=95)


def main() -> None:
    results = load_results()
    render_framework(results)
    render_sample_gate(results)
    render_results(results)
    for p in sorted(OUT_DIR.glob("k1582_lazypack_*.png")):
        print(p)


if __name__ == "__main__":
    main()
