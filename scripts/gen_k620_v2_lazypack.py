#!/usr/bin/env python3
"""
Generate lazypack infographic posters for K620 general article v2.

4 posters, each covering one information type:
- Poster 1: 概念 — 什麼是財報事件策略？
- Poster 2: 結果摘要 — 數字說話
- Poster 3: 核心發現 — 信賴區間含零（空包彈）
- Poster 4: 結論 — 散戶啟示
"""
from __future__ import annotations
import os
import sys
import json
import textwrap
import requests
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
from pathlib import Path

# ─── Font fix ───
plt.rcParams["font.sans-serif"] = ["PingFang HK", "Heiti TC", "Arial Unicode MS", "STHeiti", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# ─── Supabase config ───
_env_file = Path(__file__).resolve().parents[1] / ".env.local"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.strip().split("=", 1)
            if _k not in os.environ:
                os.environ[_k] = _v

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_KEY", "")
BUCKET = "article-images"
OUT_DIR = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/K620")
DPI = 150

BRAND_BLUE = "#1565C0"
BRAND_LIGHT = "#E3F2FD"
ACCENT_RED = "#C62828"
ACCENT_ORANGE = "#F57C00"
ACCENT_GREEN = "#2E7D32"
TEXT_DARK = "#212121"
TEXT_MED = "#424242"
TEXT_LIGHT = "#757575"


def upload(png_path: str, filename: str) -> str:
    storage_path = f"{BUCKET}/{filename}"
    with open(png_path, "rb") as f:
        resp = requests.post(
            f"{SUPABASE_URL}/storage/v1/object/{storage_path}",
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "apikey": SUPABASE_KEY,
                "Content-Type": "image/png",
                "x-upsert": "true",
            },
            data=f,
            timeout=30,
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed {resp.status_code}: {resp.text[:200]}")
    url = f"{SUPABASE_URL}/storage/v1/object/public/{storage_path}"
    print(f"  ✓ uploaded: {url}")
    return url


def poster_1_concept():
    """概念圖：財報事件策略是什麼？"""
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')
    fig.patch.set_facecolor(BRAND_LIGHT)

    # Title
    ax.text(5, 9.2, "財報事件策略 — 概念", ha='center', va='center',
            fontsize=18, fontweight='bold', color=BRAND_BLUE)
    ax.text(5, 8.6, "用台積電公告時間調整 0050 持倉", ha='center', va='center',
            fontsize=12, color=TEXT_MED)

    # Timeline
    ax.annotate("", xy=(9, 5), xytext=(1, 5),
                arrowprops=dict(arrowstyle="->, head_width=0.3", color=TEXT_MED, lw=2))
    ax.text(5, 4.5, "時間軸", ha='center', fontsize=10, color=TEXT_LIGHT)

    # Events on timeline
    positions = [2.5, 5, 7.5]
    labels = ["公告前 3 天\n↓ 持倉 -20%", "📢 台積電\n月營收/季報公告", "公告後 5 天\n↑ 持倉 +20%"]
    colors = [ACCENT_RED, BRAND_BLUE, ACCENT_GREEN]
    for x, label, color in zip(positions, labels, colors):
        ax.plot(x, 5, 'o', markersize=16, color=color, zorder=5)
        ax.text(x, 6.5 if x == 5 else 6.3, label, ha='center', va='center',
                fontsize=9.5, color=color, fontweight='bold' if x == 5 else 'normal',
                multialignment='center')

    # Stats box
    box = FancyBboxPatch((0.5, 1.2), 9, 2.5, boxstyle="round,pad=0.1",
                          facecolor='white', edgecolor=BRAND_BLUE, linewidth=1.5, alpha=0.9)
    ax.add_patch(box)
    ax.text(5, 3.3, "測試規模：2015—2026 年 ‧ 2,728 個交易日", ha='center', va='center',
            fontsize=11, color=TEXT_DARK, fontweight='bold')
    ax.text(5, 2.55, "月營收公告 135 場　季度財報 45 場", ha='center', va='center',
            fontsize=10.5, color=TEXT_MED)
    ax.text(5, 1.8, "資料：yfinance (0050.TW + VIX)　2015/01 — 2026/03", ha='center',
            va='center', fontsize=9, color=TEXT_LIGHT)

    # Brand
    ax.text(9.8, 0.2, "VolPred", ha='right', fontsize=9, color=TEXT_LIGHT, style='italic')

    plt.tight_layout(pad=0.3)
    out = str(OUT_DIR / "article_v2_lazypack_1_concept.png")
    fig.savefig(out, dpi=DPI, bbox_inches='tight', facecolor=BRAND_LIGHT)
    plt.close()
    print(f"  Saved: {out}")
    return out


def poster_2_results():
    """結果摘要圖：數字對比表"""
    fig, ax = plt.subplots(figsize=(8, 6.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')
    fig.patch.set_facecolor('#FAFAFA')

    ax.text(5, 9.4, "11 年測試結果一覽", ha='center', fontsize=18, fontweight='bold', color=BRAND_BLUE)
    ax.text(5, 8.8, "表面上策略有贏，但贏多少？值不值？", ha='center', fontsize=11, color=TEXT_MED)

    # Table header
    headers = ["策略", "年化報酬", "最大跌幅", "11年累積"]
    col_x = [1.5, 3.8, 5.8, 7.8]
    row_height = 0.9

    for i, h in enumerate(headers):
        ax.text(col_x[i], 8.0, h, ha='center', va='center',
                fontsize=10.5, fontweight='bold', color='white')

    rect_h = FancyBboxPatch((0.3, 7.6), 9.4, 0.7,
                             boxstyle="round,pad=0.05", facecolor=BRAND_BLUE, alpha=0.9)
    ax.add_patch(rect_h)
    for i, h in enumerate(headers):
        ax.text(col_x[i], 8.0, h, ha='center', va='center',
                fontsize=10.5, fontweight='bold', color='white')

    # Rows
    rows = [
        ("基準策略", "12.3%", "−13.1%", "2.65×"),
        ("事件後加碼", "13.4%", "−13.2%", "3.06×"),
        ("事件前減碼", "11.8%", "−12.1%", "2.46×"),
        ("加碼+減碼組合", "12.9%", "−12.2%", "2.85×"),
        ("季度財報策略", "12.2%", "−13.7%", "2.59×"),
    ]
    row_colors = ['#EEF7FF', 'white', '#EEF7FF', 'white', '#EEF7FF']
    for r_idx, (row, bg) in enumerate(zip(rows, row_colors)):
        y = 7.6 - (r_idx + 1) * row_height
        rect = FancyBboxPatch((0.3, y - 0.38), 9.4, 0.75,
                               boxstyle="round,pad=0.02", facecolor=bg, alpha=0.8,
                               edgecolor='#ddd', linewidth=0.5)
        ax.add_patch(rect)
        is_base = r_idx == 0
        font_w = 'bold' if is_base else 'normal'
        font_c = BRAND_BLUE if is_base else TEXT_DARK
        for c_idx, val in enumerate(row):
            color = font_c
            if c_idx > 0 and not is_base:
                # Highlight changes vs baseline
                base_vals = [0.123, -0.131, 2.65]
                try:
                    num = float(val.replace('%', '').replace('×', '').replace('−', '-'))
                    b = base_vals[c_idx - 1]
                    if c_idx == 2:  # MDD, lower is better
                        color = ACCENT_GREEN if num > b else ACCENT_RED
                    else:
                        color = ACCENT_GREEN if num > b else ACCENT_RED
                except:
                    color = TEXT_DARK
            ax.text(col_x[c_idx], y, val, ha='center', va='center',
                    fontsize=9.5 if c_idx == 0 else 10, color=color,
                    fontweight=font_w)

    # Note
    y_note = 7.6 - 6 * row_height - 0.1
    ax.text(5, y_note, "* 未扣交易成本　事件後加碼的超額報酬：毛利 +1.1%，扣成本後剩 +0.8%",
            ha='center', fontsize=8.5, color=TEXT_LIGHT)
    ax.text(5, y_note - 0.4, "資料：yfinance 0050.TW + ^VIX　2015/01—2026/03　n=2,728 交易日",
            ha='center', fontsize=8, color=TEXT_LIGHT)
    ax.text(9.8, 0.2, "VolPred", ha='right', fontsize=9, color=TEXT_LIGHT, style='italic')

    plt.tight_layout(pad=0.3)
    out = str(OUT_DIR / "article_v2_lazypack_2_results.png")
    fig.savefig(out, dpi=DPI, bbox_inches='tight', facecolor='#FAFAFA')
    plt.close()
    print(f"  Saved: {out}")
    return out


def poster_3_ci():
    """核心發現：信賴區間包含零"""
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.set_xlim(-0.6, 1.8)
    ax.set_ylim(-1, 4)
    ax.axis('off')
    fig.patch.set_facecolor('#FFF8E1')

    ax.text(0.6, 3.7, "重新抽 10,000 次：超額報酬最可能的範圍", ha='center',
            fontsize=16, fontweight='bold', color=ACCENT_ORANGE)
    ax.text(0.6, 3.2, "信賴區間跨過零線 → 可能完全沒效", ha='center',
            fontsize=11.5, color=TEXT_MED)

    # Number line
    y = 1.5
    ax.annotate("", xy=(1.5, y), xytext=(-0.4, y),
                arrowprops=dict(arrowstyle="->, head_width=0.2", color='#888', lw=2))

    # Zero line
    ax.axvline(x=0, ymin=0.1, ymax=0.75, color=ACCENT_RED, linewidth=2.5, linestyle='-')
    ax.text(0, 0.7, "0%\n（無效）", ha='center', va='top', fontsize=10, color=ACCENT_RED, fontweight='bold')

    # CI range bar
    ci_lo = -0.154  # percent
    ci_hi = 1.195   # percent
    mean_exc = 0.519  # percent

    # Scale: -0.5% to 1.5% maps to -0.4 to 1.4 on our axis
    def to_ax(pct):
        return pct / 1.5 * 1.2

    ci_lo_ax = to_ax(ci_lo)
    ci_hi_ax = to_ax(ci_hi)
    mean_ax = to_ax(mean_exc)

    # CI bar
    ax.barh(y, ci_hi_ax - ci_lo_ax, left=ci_lo_ax, height=0.35,
            color='#FFA726', alpha=0.5, label='95% 最可能範圍')
    ax.plot([ci_lo_ax, ci_lo_ax], [y - 0.22, y + 0.22], color=ACCENT_ORANGE, lw=2.5)
    ax.plot([ci_hi_ax, ci_hi_ax], [y - 0.22, y + 0.22], color=ACCENT_ORANGE, lw=2.5)
    ax.plot(mean_ax, y, 'D', markersize=10, color=BRAND_BLUE, zorder=5, label='平均超額報酬')

    # Labels
    ax.text(ci_lo_ax, y + 0.35, f'{ci_lo:.2f}%', ha='center', fontsize=9.5, color=ACCENT_ORANGE, fontweight='bold')
    ax.text(ci_hi_ax, y + 0.35, f'+{ci_hi:.2f}%', ha='center', fontsize=9.5, color=ACCENT_ORANGE, fontweight='bold')
    ax.text(mean_ax, y - 0.45, f'平均 +{mean_exc:.2f}%', ha='center', fontsize=9.5, color=BRAND_BLUE, fontweight='bold')

    ax.text(ci_lo_ax - 0.1, y, '◄', ha='right', fontsize=14, color=ACCENT_RED)
    ax.text(-0.05, 2.2, "含零！", ha='center', fontsize=13,
            color=ACCENT_RED, fontweight='bold', style='italic')

    # Explanation box
    box = FancyBboxPatch((-0.5, -0.85), 2.2, 1.1, boxstyle="round,pad=0.1",
                          facecolor='white', edgecolor=ACCENT_ORANGE, linewidth=1.5, alpha=0.9)
    ax.add_patch(box)
    ax.text(0.6, -0.1, "年化超額報酬 95% 最可能落在：−0.15% 到 +1.19%", ha='center',
            va='center', fontsize=9.5, color=TEXT_DARK)
    ax.text(0.6, -0.55, "範圍包含零 → 有可能根本沒超額收益，11年結果可能只是運氣", ha='center',
            va='center', fontsize=9, color=ACCENT_RED)

    ax.text(1.6, -0.8, "VolPred", ha='right', fontsize=9, color=TEXT_LIGHT, style='italic')

    plt.tight_layout(pad=0.3)
    out = str(OUT_DIR / "article_v2_lazypack_3_ci.png")
    fig.savefig(out, dpi=DPI, bbox_inches='tight', facecolor='#FFF8E1')
    plt.close()
    print(f"  Saved: {out}")
    return out


def poster_4_conclusion():
    """結論懶人包"""
    fig, ax = plt.subplots(figsize=(8, 6.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')
    fig.patch.set_facecolor('#E8F5E9')

    ax.text(5, 9.4, "散戶四大重點", ha='center', fontsize=18, fontweight='bold', color=ACCENT_GREEN)
    ax.text(5, 8.8, "台積電財報事件操作 0050 前，先看懂這四件事", ha='center', fontsize=11, color=TEXT_MED)

    points = [
        ("1", "財報日不等於獲利日",
         "扣完來回調整成本後，\n11 年年化超額報酬只剩 +0.10%",
         ACCENT_ORANGE),
        ("2", "只在牛市有效",
         "2023 年後才明顯，2019-2022 和 2015-2018\n差距微弱，牛市換人 = 優勢消失",
         ACCENT_RED),
        ("3", "信賴區間含零，可能只是運氣",
         "重新抽 10,000 次，結果範圍跨過零——\n這 11 年的超額報酬可能純屬運氣",
         BRAND_BLUE),
        ("4", "最穩健的選擇：什麼都別動",
         "基準策略（不調整）11 年累積 2.65 倍、\n年化 12.3%，本來就是很好的結果",
         ACCENT_GREEN),
    ]

    for i, (num, title, desc, color) in enumerate(points):
        y = 7.8 - i * 1.95
        # Circle number
        circle = plt.Circle((0.7, y), 0.38, color=color, zorder=5)
        ax.add_patch(circle)
        ax.text(0.7, y, num, ha='center', va='center', fontsize=14, fontweight='bold', color='white')
        # Title
        ax.text(1.5, y + 0.2, title, ha='left', va='center', fontsize=11,
                fontweight='bold', color=color)
        # Description
        ax.text(1.5, y - 0.35, desc, ha='left', va='center', fontsize=9.5,
                color=TEXT_MED, multialignment='left')
        # Separator line
        if i < 3:
            ax.axhline(y=y - 0.8, xmin=0.05, xmax=0.95, color='#ccc', linewidth=0.8)

    ax.text(5, 0.3, "資料：yfinance 0050.TW + ^VIX　2015-2026　n=2,728 交易日　月營收 135 場", ha='center',
            fontsize=8.5, color=TEXT_LIGHT)
    ax.text(9.8, 0.3, "VolPred", ha='right', fontsize=9, color=TEXT_LIGHT, style='italic')

    plt.tight_layout(pad=0.3)
    out = str(OUT_DIR / "article_v2_lazypack_4_conclusion.png")
    fig.savefig(out, dpi=DPI, bbox_inches='tight', facecolor='#E8F5E9')
    plt.close()
    print(f"  Saved: {out}")
    return out


def main():
    print("Generating K620 lazypack infographic posters...")

    p1 = poster_1_concept()
    p2 = poster_2_results()
    p3 = poster_3_ci()
    p4 = poster_4_conclusion()

    print("\nUploading to Supabase...")
    u1 = upload(p1, "k620_v2_lazypack_1_concept.png")
    u2 = upload(p2, "k620_v2_lazypack_2_results.png")
    u3 = upload(p3, "k620_v2_lazypack_3_ci.png")
    u4 = upload(p4, "k620_v2_lazypack_4_conclusion.png")

    urls = {"lazypack_1_concept": u1, "lazypack_2_results": u2,
            "lazypack_3_ci": u3, "lazypack_4_conclusion": u4}
    out = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/K620") / "article_v2_lazypack_urls.json"
    out.write_text(json.dumps(urls, indent=2))
    print(f"\nAll URLs saved: {out}")
    for k, v in urls.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
