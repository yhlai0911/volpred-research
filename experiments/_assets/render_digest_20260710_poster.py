"""恐慌溫差三問診法 — daily_digest 20260710 框架 summary poster.
純框架合成圖（非內文證據圖），供懶人包使用。數字取自策展來源文章。
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import matplotlib.font_manager as fm
import os

# 中文字型
for fp in [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

INK = "#1a2332"
MUTED = "#5b6b82"
ACCENT = "#c0392b"   # 恐慌紅
COOL = "#2874a6"     # 冷靜藍
CARD = "#f4f6f9"
LINE = "#d6dde6"

fig = plt.figure(figsize=(8.5, 11), dpi=150)
fig.patch.set_facecolor("white")
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 100)
ax.set_ylim(0, 130)
ax.axis("off")

# 標題
ax.text(6, 124, "恐慌溫差三問診法", fontsize=30, fontweight="bold", color=INK, va="top")
ax.text(6, 117.5, "兩地恐慌指數出現大溫差時，別急著判斷，先過三問", fontsize=13, color=MUTED, va="top")
ax.plot([6, 94], [114, 114], color=LINE, lw=1.5)

# 頭條數據帶
band = FancyBboxPatch((6, 100), 88, 11, boxstyle="round,pad=0.4,rounding_size=1.5",
                      fc=CARD, ec=LINE, lw=1.2)
ax.add_patch(band)
ax.text(16, 108.5, "37", fontsize=30, fontweight="bold", color=ACCENT, ha="center", va="center")
ax.text(16, 103, "台版 VIX", fontsize=11, color=MUTED, ha="center", va="center")
ax.text(50, 105.7, "－", fontsize=28, color=MUTED, ha="center", va="center")
ax.text(50, 108.5, "≈21 點溫差", fontsize=13, fontweight="bold", color=INK, ha="center", va="center")
ax.text(50, 102.5, "台股比華爾街更害怕", fontsize=10, color=MUTED, ha="center", va="center")
ax.text(84, 108.5, "16", fontsize=30, fontweight="bold", color=COOL, ha="center", va="center")
ax.text(84, 103, "美股 VIX", fontsize=11, color=MUTED, ha="center", va="center")

# 三問卡片
questions = [
    ("問診一　溫差從哪來？", "結構 vs 情緒",
     "台股波動率天生是美股的 2.34 倍——電子權重高、單一台積電\n"
     "佔指數 36–38%。先扣掉這層「結構性溫差」，剩下的才是真恐慌。",
     "2.34×"),
    ("問診二　溫差是領先還是滯後？", "先知 vs 跟跌",
     "查 2,600 多天：美股大跌後台股次日補跌機率隨跌幅升高，\n"
     "傳導係數約 0.485。台股恐慌多半是「跟跌反應」而非「先知」。",
     "0.485"),
    ("問診三　溫差怎麼用？", "收斂方向 + 避險成本",
     "極端溫差通常向下收斂（如 MOVE 與 VIX 的分裂終會靠攏）。\n"
     "把恐慌指數放對「層」再讀，樣本外校準可改善約 5.6%。",
     "5.6%"),
]
y = 92
for i, (head, tag, body, big) in enumerate(questions):
    h = 22
    card = FancyBboxPatch((6, y - h + 2), 88, h - 3,
                          boxstyle="round,pad=0.5,rounding_size=1.5",
                          fc="white", ec=LINE, lw=1.3)
    ax.add_patch(card)
    # 左側序號條
    ax.add_patch(FancyBboxPatch((6, y - h + 2), 2.2, h - 3,
                 boxstyle="round,pad=0,rounding_size=0.4",
                 fc=ACCENT if i == 0 else (COOL if i == 2 else "#8e6f2e"), ec="none"))
    ax.text(11, y - 1, head, fontsize=15, fontweight="bold", color=INK, va="top")
    ax.text(11, y - 5, tag, fontsize=11, color=MUTED, va="top", style="italic")
    ax.text(11, y - 8.5, body, fontsize=10.3, color=INK, va="top", linespacing=1.5)
    ax.text(88, y - 9.5, big, fontsize=22, fontweight="bold",
            color=ACCENT if i == 0 else (COOL if i == 2 else "#8e6f2e"),
            ha="right", va="center")
    y -= h + 1.5

# 底註
ax.plot([6, 94], [10, 10], color=LINE, lw=1.2)
ax.text(6, 7.5, "VolPred 波動率研究平台　·　每日精選導讀　·　數字取自平台實測研究",
        fontsize=9.5, color=MUTED, va="top")
ax.text(6, 4, "volpred.zeabur.app", fontsize=9.5, color=COOL, va="top", fontweight="bold")

out = "experiments/_assets/digest_20260710_framework_poster.png"
os.makedirs("experiments/_assets", exist_ok=True)
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white", pad_inches=0.3)
print("SAVED", out)
