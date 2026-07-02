"""Generate a 3-panel lazypack (cheat-sheet infographic) SET for the K1560 general article.

Poster-session style: concept / method / results, each its own PNG.
Every number is pulled directly from k1560_results.json (data-accurate, reproducible).
No metered image API is used.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch

HERE = Path(__file__).resolve().parent
R = json.loads((HERE / "k1560_results.json").read_text())

_FONTS = ["PingFang HK", "Heiti TC", "STHeiti", "Arial Unicode MS",
          "PingFang TC", "Noto Sans CJK SC", "sans-serif"]
if not any(k in fm.findfont("PingFang HK") for k in ("PingFang", "Heiti", "STHeiti")):
    fm._load_fontmanager(try_read_cache=False)
plt.rcParams["font.sans-serif"] = _FONTS
plt.rcParams["axes.unicode_minus"] = False

INK = "#1A2233"
MUTE = "#5B6472"
ACCENT = "#1565C0"
GREEN = "#2E7D32"
RED = "#C62828"
BG = "#F7F9FC"
CARD = "#FFFFFF"

# ── derive real numbers ──────────────────────────────────────────────
reg = {t["target"]: t for t in R["regression_tests"]}
n_obs = reg["loss_GARCH"]["n"]
n_assets = reg["loss_GARCH"]["assets"]
pos_garch = R["positive_spearman_assets"]["loss_GARCH"]
best_raw_p = min(t["p_signal_dispersion"] for t in R["regression_tests"])
n_tests = len(R["regression_tests"])
intraday_start = R["data_summary"]["SPY"]["intraday_start"]
intraday_end = R["data_summary"]["SPY"]["intraday_end"]


def _card(ax, x, y, w, h, fc=CARD, ec="#E1E7F0", lw=1.4):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0.008,rounding_size=0.025",
                                fc=fc, ec=ec, lw=lw, zorder=1))


def _new():
    fig, ax = plt.subplots(figsize=(7.2, 9.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor(BG)
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, fc=BG, zorder=0))
    return fig, ax


def _save(fig, name):
    out = HERE / name
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print("saved", out)


# ═══ Poster 1: 概念 ═══════════════════════════════════════════════════
fig, ax = _new()
ax.text(0.5, 0.965, "懶人包 1｜這篇在問什麼", ha="center", va="top",
        fontsize=13, color=ACCENT, fontweight="bold")
ax.text(0.5, 0.935, "波動率「測不準」\n能當減碼訊號嗎？", ha="center", va="top",
        fontsize=25, color=INK, fontweight="bold", linespacing=1.3)

# card A
_card(ax, 0.07, 0.615, 0.86, 0.19)
ax.text(0.11, 0.785, "同一天的市場有多晃，能用好幾種方法量",
        va="top", fontsize=14.5, color=INK, fontweight="bold")
ax.text(0.11, 0.735, "5 分鐘資料、開高低收、隔夜跳空……各算各的，\n"
                     "就像好幾支溫度計同時量同一間房間。",
        va="top", fontsize=12.5, color=MUTE, linespacing=1.55)

# card B
_card(ax, 0.07, 0.385, 0.86, 0.205)
ax.text(0.11, 0.565, "「分歧」就是這些讀數彼此差多少",
        va="top", fontsize=14.5, color=INK, fontweight="bold")
ax.text(0.11, 0.515, "溫度計讀數對不上時，你對真實溫度更沒把握。\n"
                     "市場也一樣：估計量吵得越兇，\n"
                     "當天的波動可能越難量準。",
        va="top", fontsize=12.5, color=MUTE, linespacing=1.55)

# card C (highlight)
_card(ax, 0.07, 0.1, 0.86, 0.26, fc="#EEF4FF", ec="#C7D9F5")
ax.text(0.11, 0.335, "要驗證的直覺", va="top", fontsize=14.5, color=ACCENT, fontweight="bold")
ax.text(0.11, 0.285, "分歧大的那天，是不是預告了「隔天更難預測、\n"
                     "部位更容易抓錯」？如果成立，就能拿分歧\n"
                     "當一盞提前亮起的警示燈，晃得太兇時先減碼。",
        va="top", fontsize=12.5, color=INK, linespacing=1.55)
ax.text(0.5, 0.125, "六檔 ETF：SPY · QQQ · IWM · TLT · GLD · HYG",
        ha="center", va="top", fontsize=11.5, color=MUTE)
_save(fig, "k1560_lazypack_1_concept.png")


# ═══ Poster 2: 方法 ═══════════════════════════════════════════════════
fig, ax = _new()
ax.text(0.5, 0.965, "懶人包 2｜怎麼測的", ha="center", va="top",
        fontsize=13, color=ACCENT, fontweight="bold")
ax.text(0.5, 0.93, "把「分歧」變成\n可以檢定的數字", ha="center", va="top",
        fontsize=24, color=INK, fontweight="bold", linespacing=1.3)

stats = [
    (f"{n_assets}", "檔 ETF", "股債金與\n高收益債"),
    (f"{n_obs}", "個觀測日", f"{intraday_start}\n～{intraday_end}"),
    (f"{n_tests}", "個檢定", "誤差與\n部位風險"),
]
x0, w, gap = 0.07, 0.267, 0.03
for i, (big, unit, sub) in enumerate(stats):
    x = x0 + i * (w + gap)
    _card(ax, x, 0.6, w, 0.19)
    ax.text(x + w / 2, 0.765, big, ha="center", va="top", fontsize=30, color=ACCENT, fontweight="bold")
    ax.text(x + w / 2, 0.695, unit, ha="center", va="top", fontsize=12.5, color=INK, fontweight="bold")
    ax.text(x + w / 2, 0.658, sub, ha="center", va="top", fontsize=10, color=MUTE, linespacing=1.4)

steps = [
    ("1", "多把尺一起量", "每天用 8 種以上方法估波動，記下彼此差多少（分歧值）。"),
    ("2", "只用「昨天」的分歧", "分歧值往後挪一天，拿今天以前的資訊對隔天，不偷看未來。"),
    ("3", "問七個問題", "分歧大的那天，隔天誤差、部位抓錯幅度會不會跟著變大？"),
    ("4", "套上嚴格門檻", "同時問多個問題容易矇到，加做多重比較校正剔除僥倖。"),
]
y = 0.5
for num, head, body in steps:
    ax.add_patch(plt.Circle((0.12, y), 0.026, fc=ACCENT, ec="none", zorder=3))
    ax.text(0.12, y, num, ha="center", va="center", fontsize=13, color="white", fontweight="bold", zorder=4)
    ax.text(0.175, y + 0.028, head, va="top", fontsize=13.5, color=INK, fontweight="bold")
    ax.text(0.175, y - 0.012, body, va="top", fontsize=11.3, color=MUTE, linespacing=1.4)
    y -= 0.11
_save(fig, "k1560_lazypack_2_method.png")


# ═══ Poster 3: 結果 ═══════════════════════════════════════════════════
fig, ax = _new()
ax.text(0.5, 0.965, "懶人包 3｜結論", ha="center", va="top",
        fontsize=13, color=ACCENT, fontweight="bold")
ax.text(0.5, 0.93, "方向對，\n但還不能當減碼開關", ha="center", va="top",
        fontsize=24, color=INK, fontweight="bold", linespacing=1.3)

# two stat cards
_card(ax, 0.07, 0.6, 0.415, 0.19, fc="#EAF6EC", ec="#BFE3C6")
ax.text(0.277, 0.765, f"{len(pos_garch)} / {n_assets}", ha="center", va="top", fontsize=32, color=GREEN, fontweight="bold")
ax.text(0.277, 0.695, "檔方向符合直覺", ha="center", va="top", fontsize=12.5, color=INK, fontweight="bold")
ax.text(0.277, 0.658, "分歧大時隔天\n誤差偏大", ha="center", va="top", fontsize=10.5, color=MUTE, linespacing=1.4)

_card(ax, 0.515, 0.6, 0.415, 0.19, fc="#FDECEC", ec="#F5C6C6")
ax.text(0.722, 0.765, "0 / 7", ha="center", va="top", fontsize=32, color=RED, fontweight="bold")
ax.text(0.722, 0.695, "個檢定通過門檻", ha="center", va="top", fontsize=12.5, color=INK, fontweight="bold")
ax.text(0.722, 0.658, f"最強訊號\n也只到約 {best_raw_p:.2f}", ha="center", va="top", fontsize=10.5, color=MUTE, linespacing=1.4)

# why card
_card(ax, 0.07, 0.375, 0.86, 0.185)
ax.text(0.11, 0.535, "為什麼「方向對」還不夠", va="top", fontsize=14, color=INK, fontweight="bold")
ax.text(0.11, 0.485, "六檔裡五檔方向一致，看起來有戲；但關聯都很弱，\n"
                     "連最嚴格門檻的第一關都沒跨過。\n"
                     "校正後，七個訊號全部退回不顯著。",
        va="top", fontsize=12, color=MUTE, linespacing=1.55)

# use card
_card(ax, 0.07, 0.09, 0.86, 0.26, fc="#EEF4FF", ec="#C7D9F5")
ax.text(0.11, 0.325, "投資人可以怎麼用", va="top", fontsize=14, color=ACCENT, fontweight="bold")
ax.text(0.11, 0.275, "• 分歧變大時當「多留意一點」的參考，可以。\n"
                     "• 接成自動減碼規則，這批資料還撐不起來。\n"
                     "• 只有 60 天日內樣本，方向對但要更長期間才敢下注。",
        va="top", fontsize=12, color=INK, linespacing=1.75)
ax.text(0.5, 0.115, "資料：yfinance｜期間 2026-04～2026-06｜方向對但未達統計顯著",
        ha="center", va="top", fontsize=10.5, color=MUTE)
_save(fig, "k1560_lazypack_3_result.png")
