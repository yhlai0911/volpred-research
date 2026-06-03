#!/usr/bin/env python3
"""VolPred 品牌視覺資產生成器（可復現，零外部 API）。

設計語言：
  - 平台官方主色 emerald（tailwind accent #10B981 / #059669 / #34D399）
  - 深炭底 #0A0B0E，暖白字 #FDFBF6
  - 核心 motif：volatility curve —— 一條平滑下行到谷底再上揚的 swoosh，
    象徵波動率的 spike → mean-reversion / V-shaped recovery。

輸出（storage/assets/）：
  - volpred_avatar.png   1080x1080  FB 大頭照（圓形裁切安全）
  - volpred_cover.png    1702x630   FB 粉專封面（2x retina；左下避開頭像疊放區）
  - volpred_logo_square.png 1080x1080 方形 logo（非圓，通用）

字體用系統 Avenir Next / SF Pro / PingFang，全程 matplotlib 向量繪製後輸出高 DPI PNG。
"""
from __future__ import annotations

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch, Circle, FancyBboxPatch
from matplotlib import font_manager as fm
from matplotlib.collections import LineCollection

# ---- 品牌色 ----------------------------------------------------------------
INK        = "#0A0B0E"   # 深炭底
INK_SOFT   = "#12161C"   # 稍亮深底（漸層用）
EMERALD    = "#10B981"   # accent-500 主色
EMERALD_D  = "#059669"   # accent-600
EMERALD_L  = "#34D399"   # accent-400
EMERALD_XL = "#6EE7B7"   # accent-300 高光
PAPER      = "#FDFBF6"   # 暖白字
MUTE       = "#9CA3AF"   # 次要灰字

ASSETS = os.path.join(os.path.dirname(__file__), "..", "storage", "assets")
ASSETS = os.path.abspath(ASSETS)

# ---- 字體 ------------------------------------------------------------------
def _font(paths, fallback="DejaVu Sans"):
    for p in paths:
        if os.path.exists(p):
            try:
                return fm.FontProperties(fname=p)
            except Exception:
                continue
    return fm.FontProperties(family=fallback)

F_DISPLAY = _font([
    "/System/Library/Fonts/Avenir Next.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
])
F_MONO = _font([
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
])
F_ZH = _font([
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
])


def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lerp(c1, c2, t):
    a, b = _hex2rgb(c1), _hex2rgb(c2)
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


# ---- volatility swoosh：平滑曲線，沿線做 emerald 漸層 + 線寬漸變 -----------
def vol_swoosh(ax, cx, cy, scale, lw_max, alpha=1.0, glow=True):
    """以 (cx,cy) 為中心畫 vol curve。回傳曲線點。

    形狀：左高 → 下行至谷 → 右側強力上揚（右端更高，象徵 recovery/breakout）。
    """
    # 控制點（單位座標，之後 *scale 平移）
    t = np.linspace(0, 1, 400)
    # 用兩段三次貝茲拼一條不對稱 valley
    P0 = np.array([-1.00,  0.62])
    P1 = np.array([-0.55, -0.30])
    P2 = np.array([-0.18, -0.78])
    P3 = np.array([ 0.10, -0.66])
    Q1 = np.array([ 0.45, -0.50])
    Q2 = np.array([ 0.66,  0.30])
    Q3 = np.array([ 0.92,  0.86])

    def bez(p0, p1, p2, p3, tt):
        tt = tt[:, None]
        return ((1 - tt) ** 3) * p0 + 3 * ((1 - tt) ** 2) * tt * p1 \
            + 3 * (1 - tt) * (tt ** 2) * p2 + (tt ** 3) * p3

    h = t < 0.5
    seg1 = bez(P0, P1, P2, P3, t[h] / 0.5)
    seg2 = bez(P3, Q1, Q2, Q3, (t[~h] - 0.5) / 0.5)
    pts = np.vstack([seg1, seg2])
    pts = pts * scale + np.array([cx, cy])

    # 線寬：谷底細、兩端粗 → 收尾感
    depth = (pts[:, 1] - pts[:, 1].min())
    depth = depth / depth.max()
    widths = lw_max * (0.42 + 0.58 * depth)

    segs = np.concatenate([pts[:-1, None, :], pts[1:, None, :]], axis=1)
    cols = [(*_lerp(EMERALD_D, EMERALD_XL, t[i]), alpha) for i in range(len(segs))]

    if glow:
        for gw, ga in ((3.2, 0.06), (2.2, 0.10), (1.5, 0.16)):
            lc = LineCollection(segs, linewidths=widths * gw,
                                colors=[(*_hex2rgb(EMERALD_L), ga)] * len(segs),
                                capstyle="round", joinstyle="round", zorder=2)
            ax.add_collection(lc)

    lc = LineCollection(segs, linewidths=widths, colors=cols,
                        capstyle="round", joinstyle="round", zorder=4)
    ax.add_collection(lc)
    return pts


def _radial_bg(ax, w, h, center=(0.5, 0.55)):
    """深色徑向漸層背景。"""
    ny, nx = 600, int(600 * w / h)
    yy, xx = np.mgrid[0:ny, 0:nx]
    cx, cy = center[0] * nx, center[1] * ny
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r = r / r.max()
    grad = np.zeros((ny, nx, 3))
    for i in range(3):
        a = _hex2rgb(INK_SOFT)[i]
        b = _hex2rgb(INK)[i]
        grad[..., i] = a + (b - a) * np.clip(r * 1.15, 0, 1)
    ax.imshow(grad, extent=[0, w, 0, h], origin="lower",
              aspect="auto", zorder=0, interpolation="bilinear")


# ---------------------------------------------------------------------------
def make_avatar(path):
    W = H = 1080
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")

    # 圓形深底（FB 會圓裁，這裡先填滿避免邊角白）
    fig.patch.set_facecolor(INK)
    _radial_bg(ax, 1, 1, center=(0.5, 0.52))

    # 細 emerald 圓環，提升精緻度
    ring = Circle((0.5, 0.5), 0.475, fill=False, lw=2.2,
                  edgecolor=(*_hex2rgb(EMERALD_D), 0.55), zorder=3)
    ax.add_patch(ring)

    # 中央 vol swoosh
    vol_swoosh(ax, 0.5, 0.55, scale=0.30, lw_max=15, glow=True)

    # 下方 wordmark
    ax.text(0.5, 0.205, "VolPred", ha="center", va="center",
            fontproperties=F_DISPLAY, fontsize=58, color=PAPER,
            fontweight="bold", zorder=5)

    fig.savefig(path, dpi=100, facecolor=INK)
    plt.close(fig)
    print("avatar ->", path)


def make_logo_square(path):
    W = H = 1080
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor(INK)

    # 圓角方底
    bg = FancyBboxPatch((0.06, 0.06), 0.88, 0.88,
                        boxstyle="round,pad=0,rounding_size=0.14",
                        linewidth=0, facecolor=INK_SOFT, zorder=1)
    ax.add_patch(bg)
    vol_swoosh(ax, 0.5, 0.56, scale=0.30, lw_max=16, glow=True)
    ax.text(0.5, 0.20, "VolPred", ha="center", va="center",
            fontproperties=F_DISPLAY, fontsize=62, color=PAPER,
            fontweight="bold", zorder=5)
    fig.savefig(path, dpi=100, facecolor=INK)
    plt.close(fig)
    print("logo_square ->", path)


def make_cover(path):
    W, H = 1702, 630
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H)
    ax.axis("off")
    fig.patch.set_facecolor(INK)
    _radial_bg(ax, W, H, center=(0.62, 0.5))

    # 背景大型半透明 vol swoosh（裝飾，偏右，不擾文字）
    vol_swoosh(ax, W * 0.74, H * 0.5, scale=320, lw_max=26, alpha=0.95, glow=True)

    # 細網格 baseline（資料感）
    for gy in np.linspace(H * 0.18, H * 0.82, 5):
        ax.plot([W * 0.06, W * 0.55], [gy, gy], lw=0.8,
                color=(*_hex2rgb(MUTE), 0.10), zorder=1)

    # 安全區：桌面版粉專頭像疊在封面左下角（約 x<22%, 下半部），
    # 故文字主體整體上移，footer 置中，全部避開左下頭像疊放區。
    LX = W * 0.075
    ax.text(LX, H * 0.74, "VolPred", ha="left", va="center",
            fontproperties=F_DISPLAY, fontsize=84, color=PAPER,
            fontweight="bold", zorder=5)
    # emerald 強調底線
    ax.plot([LX + 4, LX + 360], [H * 0.585, H * 0.585], lw=4,
            color=EMERALD, solid_capstyle="round", zorder=5)
    ax.text(LX, H * 0.485, "波動率預測研究平台", ha="left", va="center",
            fontproperties=F_ZH, fontsize=34, color=PAPER, zorder=5)
    ax.text(LX, H * 0.385, "Volatility Forecasting Research",
            ha="left", va="center", fontproperties=F_DISPLAY,
            fontsize=24, color=EMERALD_L, zorder=5)
    # footer 置中下緣，避開左下頭像疊放區
    ax.text(W * 0.5, H * 0.085, "真數據 · 真檢定 · 可復現      volpred.zeabur.app",
            ha="center", va="center", fontproperties=F_ZH,
            fontsize=21, color=MUTE, zorder=5)

    fig.savefig(path, dpi=100, facecolor=INK)
    plt.close(fig)
    print("cover ->", path)


if __name__ == "__main__":
    os.makedirs(ASSETS, exist_ok=True)
    make_avatar(os.path.join(ASSETS, "volpred_avatar.png"))
    make_logo_square(os.path.join(ASSETS, "volpred_logo_square.png"))
    make_cover(os.path.join(ASSETS, "volpred_cover.png"))
    print("done.")
