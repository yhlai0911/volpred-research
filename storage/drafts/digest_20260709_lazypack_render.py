#!/usr/bin/env python3
"""Lazypack poster for daily_digest 2026-07-09 — 「平靜四診」framework summary card.

Data-accurate, reproducible, zero metered cost (pure PIL). Every number traces to
the source articles' results.json / public data cited in the digest draft.
Output: two poster PNGs (framework card + current-readings card).
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_L = "/System/Library/Fonts/STHeiti Light.ttc"

# palette (professional, data-forward; no cartoon)
BG = (15, 23, 42)        # slate-900
CARD = (30, 41, 59)      # slate-800
CARD2 = (24, 33, 48)
INK = (241, 245, 249)    # slate-100
SUB = (148, 163, 184)    # slate-400
ACCENT = (56, 189, 248)  # sky-400
WARN = (251, 146, 60)    # orange-400
GOOD = (74, 222, 128)    # green-400


def f(size, light=False):
    return ImageFont.truetype(FONT_L if light else FONT, size)


def rrect(d, xy, r, fill):
    d.rounded_rectangle(xy, radius=r, fill=fill)


def text_wrap(d, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if d.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines


# ─────────────────────────────────────────────────────────────
# Card 1 — framework: 平靜四診
# ─────────────────────────────────────────────────────────────
def card1():
    W, H = 1200, 1500
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((60, 54), "平靜四診", font=f(76), fill=INK)
    d.text((60, 150), "VIX 是一張把 500 檔、各天期、各方向壓成一個數字的平均分。", font=f(30, True), fill=SUB)
    d.text((60, 194), "低 VIX 只代表平均分低，不代表班上沒人被當。", font=f(30, True), fill=SUB)

    diag = [
        ("① 天期診", ACCENT, "VIX 只講未來 30 天，更遠的沒說",
         "查 VIX3M 減 VIX：正價差 = 對更遠的未來反而更鬆",
         "7/1  VIX3M 19.16  對  VIX 16.59"),
        ("② 分散診", ACCENT, "VIX 是 500 檔的平均，個股藏在裡面",
         "查 VXN−VIX、台股自己的 RV、你持股的個別波動",
         "7/1  VXN 27.69  對  VIX 16.59（差 11.1）"),
        ("③ 形狀診", ACCENT, "VIX 只講水準高低，不講方向偏斜",
         "查賣權 IV 減買權 IV：正 = 下跌保費貴",
         "Mag 7 燒錢前三家  下跌保費反而最便宜"),
        ("④ 時間軸診", ACCENT, "VIX 往前看，你的已實現波動往後算",
         "查 VIX 見高日  對照持股真正落底日的時間差",
         "六月  VIX 6/10 見高，個股 6/25 才落底"),
    ]
    y = 268
    ch = 268
    for tag, col, dead, how, read in diag:
        rrect(d, (60, y, W - 60, y + ch - 22), 20, CARD)
        d.rectangle((60, y, 70, y + ch - 22), fill=col)
        d.text((100, y + 26), tag, font=f(44), fill=INK)
        d.text((100, y + 96), "死角：" + dead, font=f(28, True), fill=SUB)
        d.text((100, y + 142), "怎麼查：" + how, font=f(28, True), fill=INK)
        rrect(d, (100, y + 188, W - 96, y + 236), 12, CARD2)
        d.text((116, y + 196), read, font=f(28), fill=col)
        y += ch

    d.text((60, H - 66), "資料來源：yfinance、FRED（VIXCLS/VXNCLS/VXDCLS）、各檔選擇權鏈，2026-07 as-of。", font=f(22, True), fill=SUB)
    img.save(OUT / "digest_20260709_lazypack_1_framework.png")
    print("saved card1")


# ─────────────────────────────────────────────────────────────
# Card 2 — 讀完四診怎麼動（節制 + 訊號 + 工具）
# ─────────────────────────────────────────────────────────────
def card2():
    W, H = 1200, 1350
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((60, 54), "四診讀完，怎麼動？", font=f(66), fill=INK)
    d.text((60, 142), "讀出風險，不等於馬上避險。三條節制，一次記牢。", font=f(30, True), fill=SUB)

    blocks = [
        ("別急著賭暴風雨", GOOD,
         ["21 年 VIX 資料：夏季 VIX 與同年秋季相關 +0.63（顯著）。",
          "平靜多半延續，不是暴風雨前寧靜。夏季偏低半 → 秋季均 16.2；",
          "偏高半 → 秋季均 24.8。別看 VIX 十幾點就追高買貴保險。"]),
        ("訊號要極端才可靠", ACCENT,
         ["VRP 極端低那組方向準確率 87.6%，中間組只有 54.8%。",
          "最低十分位後 21 天波動率下降機率 92.5%。",
          "現在 VRP 僅輕微翻負（−1.0），還沒到可下重注的強度。"]),
        ("平靜時就決定風控好壞", WARN,
         ["FZ 聯合分數實測：把 VIX 納入的模型，優勢最大在 VIX 15–25",
          "的普通市況（DM 4.01 顯著），不是危機期。",
          "扣板機邏輯：百分位派年化 15.4%/夏普 1.68；分段保守派",
          "11.1%/1.48 但最大回撤只 −4.9%。先想清楚自己是哪一派。"]),
    ]
    y = 220
    for title, col, lines in blocks:
        bh = 90 + 46 * len(lines) + 40
        rrect(d, (60, y, W - 60, y + bh - 24), 20, CARD)
        d.rectangle((60, y, 70, y + bh - 24), fill=col)
        d.text((100, y + 24), title, font=f(40), fill=col)
        yy = y + 92
        for ln in lines:
            d.text((100, yy), ln, font=f(28, True), fill=INK)
            yy += 46
        y += bh

    d.text((60, y + 6), "一句話帶走：把 VIX 拆開來看，你才知道自己站在平均分的哪一邊。", font=f(30), fill=INK)
    d.text((60, H - 60), "資料來源：VolPred 實驗 K430 / K1076 / K683、yfinance，2005–2026。", font=f(22, True), fill=SUB)
    img.save(OUT / "digest_20260709_lazypack_2_action.png")
    print("saved card2")


if __name__ == "__main__":
    card1()
    card2()
