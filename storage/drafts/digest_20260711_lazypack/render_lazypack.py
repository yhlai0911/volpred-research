#!/usr/bin/env python3
"""懶人包圖組 render — 「財報控制盤」(2026-07-11 daily digest).

Every number on every panel is bound to EVIDENCE below, which is transcribed
verbatim from the source archive articles / experiment results JSON:
  K1147/K1151 (mile_0ae5323e), cross-market (mile_b9d5db50), K1157 (mile_858690fd),
  K1113 (mile_85502a95), K1207 (mile_34be417d), K1060 (mile_6c391484),
  K570b (mile_9fb5d7f7), TSM options observation (mile_aee1c78c).
Reproducible: same input -> same output. No image-gen API used.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle
from matplotlib import font_manager
from pathlib import Path

OUT = Path("/tmp/dg/poster")
OUT.mkdir(parents=True, exist_ok=True)

# ── CJK font ──────────────────────────────────────────────────────────────
_avail = {f.name for f in font_manager.fontManager.ttflist}
for _cand in ("PingFang TC", "Heiti TC", "Arial Unicode MS", "Songti TC"):
    if _cand in _avail:
        CJK = _cand
        break
else:
    raise SystemExit(f"no CJK font found; available sample: {sorted(_avail)[:20]}")
plt.rcParams["font.sans-serif"] = [CJK]
plt.rcParams["axes.unicode_minus"] = False
print(f"[render] CJK font = {CJK}")

# ── Palette ───────────────────────────────────────────────────────────────
INK = "#14202e"
MUTED = "#5b6b7c"
LINE = "#d7dee6"
GREEN = "#1f8a5c"   # 通電
RED = "#c0392b"     # 沒接線
AMBER = "#c98a12"   # 插錯孔 / 要重量
BG = "#ffffff"
SOFT = "#f3f6f9"

W, H, DPI = 1600, 1000, 150
FIGSIZE = (W / DPI, H / DPI)
SRC = ("資料來源：VolPred 實驗 K1147／K1151、K1150／K1153／K1157、K1109／K1113、"
       "K1207、K1060、K570b；TSM 選擇權鏈 2026-07-08 盤後（yfinance）")

# ── Evidence (verbatim from source articles) ──────────────────────────────
CELLS = [
    ("開關①", "今天有沒有財報", "通電", GREEN,
     "美股 30 檔大型股，統計強度 4.49（顯著性 0.00）\n90,479 筆日報酬 / 1,439 次財報事件 / 2014–2025"),
    ("旋鈕A", "beat 了多少", "沒接線", RED,
     "同資料同參數換成連續驚喜幅度：4.49 → 1.11（顯著性 0.41）\n日本 TOPIX30：1.32（顯著性 0.31）"),
    ("旋鈕B", "公司看得到的特徵", "沒接線", RED,
     "台灣 31 家、6 個公開指標，校正後最小顯著性 0.854\n交叉驗證 R² = −0.661；Tier A=0 / B=31 / C=0"),
    ("旋鈕C", "行業別", "唯一轉得動", GREEN,
     "12 市場 182 檔：行業解釋力是法人持股的 32 倍\n科技股 0.00137 vs 金融股 0.00012（11 倍）"),
    ("旋鈕D", "你在看哪一天", "插錯孔", AMBER,
     "台股前 10 大 2010–2025：公告當日 0.936（顯著性 0.682）\n隔一個交易日 1.466（顯著性 0.034）"),
    ("主電源", "整個財報季", "沒通電", RED,
     "SPY 5,342 個交易日：財報季 vs 非財報季\n已實現波動 15.6% vs 15.6%（顯著性 0.82）"),
    ("價格標籤", "選擇權替事件加了多少價", "要重新量", AMBER,
     "台積電 7/16 法說：溢價 3.6 個百分點 ≈ 單日 ±4.0%\n低於它自己過去 8 次法說的 4.89%"),
]


def _frame(title: str, subtitle: str):
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 100)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 92.5), 100, 8, boxstyle="square,pad=0",
                                fc=INK, ec="none"))
    ax.text(4, 96.3, title, fontsize=25, color="white", va="center", fontweight="bold")
    ax.text(96, 96.3, subtitle, fontsize=13, color="#9fb2c4", va="center", ha="right")
    ax.text(4, 2.4, SRC, fontsize=8.5, color=MUTED, va="center")
    ax.plot([4, 96], [5.6, 5.6], color=LINE, lw=0.9)
    return fig, ax


def _save(fig, name):
    p = OUT / f"{name}.png"
    fig.savefig(p, dpi=DPI, facecolor=BG)
    plt.close(fig)
    print(f"[render] wrote {p}")


# ── Panel 1: 概念 — 控制盤全圖 ─────────────────────────────────────────────
def panel1():
    fig, ax = _frame("財報控制盤", "2026 Q2 財報季　7/14 美國四大銀行開跑　7/16 台積電法說")
    ax.text(4, 87.5, "你以為手上有一排可以轉的旋鈕。我們替每一格接上電表。",
            fontsize=16.5, color=MUTED, va="center")

    short = ["今天有沒有\n財報", "beat 了\n多少", "公司看得到\n的特徵", "行業別",
             "你在看\n哪一天", "整個\n財報季", "選擇權替事件\n加了多少價"]
    xs = [4 + i * 13.4 for i in range(7)]
    for x, (tag, _label, verdict, col, _), label in zip(xs, CELLS, short):
        ax.add_patch(FancyBboxPatch((x, 30), 12.2, 50, boxstyle="round,pad=0.35,rounding_size=1.2",
                                    fc=SOFT, ec=LINE, lw=1.2))
        ax.text(x + 6.1, 75.5, tag, fontsize=14, color=INK, ha="center", fontweight="bold")
        ax.add_patch(Circle((x + 6.1, 66.5), 3.0, fc=col, ec="none",
                            transform=ax.transData))
        ax.text(x + 6.1, 57.5, verdict, fontsize=13.5, color=col, ha="center", fontweight="bold")
        ax.plot([x + 1.6, x + 10.6], [52.5, 52.5], color=LINE, lw=1)
        ax.text(x + 6.1, 44.5, label, fontsize=11.5, color=INK, ha="center", va="center",
                linespacing=1.7)
        ax.text(x + 6.1, 34.5, "● 通電" if col is GREEN else ("● 沒接線" if col is RED else "● 要小心"),
                fontsize=10, color=col, ha="center")

    ax.text(4, 20.5, "一個開關真的會亮。四個旋鈕裡，三個根本沒接線。",
            fontsize=20, color=INK, fontweight="bold", va="center")
    ax.text(4, 13.0, "唯一轉得動的是「行業別」；唯一要一次一次重新量的是「選擇權替事件標的價」。",
            fontsize=14, color=MUTED, va="center")
    _save(fig, "1_concept")


# ── Panel 2: 方法 — 怎麼量的 ───────────────────────────────────────────────
def panel2():
    fig, ax = _frame("怎麼量出來的", "同一份資料、同一組參數，只換一個變數")

    ax.text(4, 87, "把「今天有沒有財報」的 0／1 旗子，換成「驚喜幅度」的連續數字。其餘完全不動。",
            fontsize=15, color=MUTED, va="center")

    # controlled-comparison strip
    ax.add_patch(FancyBboxPatch((4, 70), 92, 12, boxstyle="round,pad=0.4,rounding_size=1",
                                fc=SOFT, ec=LINE, lw=1.2))
    holds = ["同樣 30 檔股票", "同樣的 GJR 模型規格", "同樣的 VIX 控制項", "同樣 152 個參數",
             "同樣 1,439 次財報事件"]
    for i, h in enumerate(holds):
        ax.text(8 + i * 18, 76, "● " + h, fontsize=12.5, color=INK, va="center")

    # big number comparison
    bars = [("有沒有財報\n（0／1 旗子）", 4.49, GREEN, "通電"),
            ("beat 了多少\n（連續驚喜幅度）", 1.11, RED, "沒接線")]
    ax0 = fig.add_axes([0.08, 0.20, 0.40, 0.42])
    ax0.set_facecolor(BG)
    for i, (lab, v, col, tag) in enumerate(bars):
        ax0.bar(i, v, width=0.52, color=col, zorder=3)
        ax0.text(i, v + 0.16, f"{v:.2f}", ha="center", fontsize=24, color=col, fontweight="bold")
        ax0.text(i, -1.05, lab, ha="center", fontsize=12, color=INK, linespacing=1.5)
    ax0.axhline(3.0, color=MUTED, ls="--", lw=1.3, zorder=2)
    ax0.text(1.62, 3.12, "嚴格門檻 3.0", fontsize=10.5, color=MUTED, ha="right")
    ax0.set_ylim(0, 5.4); ax0.set_xlim(-0.6, 1.6); ax0.set_clip_on(False)
    ax0.set_ylabel("統計強度", fontsize=12, color=INK)
    ax0.set_xticks([]); ax0.tick_params(labelsize=10)
    for s in ("top", "right", "bottom"):
        ax0.spines[s].set_visible(False)
    ax0.spines["left"].set_color(LINE)

    # sample scale block
    ax.add_patch(FancyBboxPatch((52, 14), 44, 46, boxstyle="round,pad=0.5,rounding_size=1.2",
                                fc=SOFT, ec=LINE, lw=1.2))
    ax.text(54.5, 55, "量了多大的樣本", fontsize=16, color=INK, fontweight="bold", va="center")
    rows = [
        ("四市場：美 30／日 30／歐 18／台 30 檔", "4,000+ 次財報事件"),
        ("美股 pooled panel（2014–2025）", "90,479 筆日報酬"),
        ("SPY + VIX（2004-12-31 ~ 2026-03-26）", "5,342 個交易日"),
        ("跨市場 GICS panel", "12 市場 182 檔"),
        ("台灣預先登記確認性實驗", "31 家 × 6 指標"),
    ]
    for i, (a, b) in enumerate(rows):
        y = 47 - i * 7.4
        ax.text(54.5, y, a, fontsize=11.5, color=INK, va="center")
        ax.text(94.2, y, b, fontsize=11.5, color=MUTED, va="center", ha="right", fontweight="bold")
        if i < len(rows) - 1:
            ax.plot([54.5, 93.5], [y - 3.7, y - 3.7], color=LINE, lw=0.8)

    ax.text(4, 9.5, "結論：統計強度 4.49 → 1.11。beat 10% 和 beat 50%，在波動率上沒有差別。",
            fontsize=15, color=INK, fontweight="bold", va="center")
    _save(fig, "2_method")


# ── Panel 3: 結果 — 七格盤點 ───────────────────────────────────────────────
def panel3():
    fig, ax = _frame("七格盤點結果", "每一格都用真實資料量過")
    y = 84.0
    for tag, label, verdict, col, ev in CELLS:
        ax.add_patch(FancyBboxPatch((4, y - 8.6), 92, 9.4,
                                    boxstyle="round,pad=0.25,rounding_size=0.8",
                                    fc=SOFT if col is not GREEN else "#eaf6f0",
                                    ec=LINE, lw=1))
        ax.add_patch(FancyBboxPatch((4.9, y - 8.0), 1.0, 8.2, boxstyle="square,pad=0",
                                    fc=col, ec="none"))
        ax.text(7.6, y - 2.4, tag, fontsize=13, color=INK, fontweight="bold", va="center")
        ax.text(7.6, y - 6.4, label, fontsize=11.5, color=MUTED, va="center")
        ax.text(31.5, y - 4.3, verdict, fontsize=15, color=col, fontweight="bold", va="center")
        ax.text(46, y - 4.3, ev, fontsize=11, color=INK, va="center", linespacing=1.6)
        y -= 10.6

    ax.text(4, 8.6, "你花在猜 beat 幾 % 的力氣，在波動率上收不回來。真正有用的是一份財報日曆。",
            fontsize=15.5, color=INK, fontweight="bold", va="center")
    _save(fig, "3_results")


# ── Panel 4: 行動 ─────────────────────────────────────────────────────────
def panel4():
    fig, ax = _frame("下週開盤前，這張盤怎麼用", "7/14 美國四大銀行　7/16 台積電法說")
    acts = [
        ("1", "力氣從「猜 beat 幾 %」搬到「排財報日曆」",
         "開關①的統計強度 4.49 就是在講這件事：事件本身才是訊號。"),
        ("2", "部位用二元分層，不用連續評分",
         "切成「未來兩週有財報」和「沒財報」兩堆；前者降部位或買保護。"),
        ("3", "個股先驗看行業別，不看市值和 beta",
         "科技股 vs 金融股差 11 倍；市值／beta／成交量那組 6 個指標全滅。"),
        ("4", "台股標的把眼睛移到隔一個交易日",
         "台股盤後公告：當日波動比 0.936，隔天才是 1.466。"),
        ("5", "不要為了財報季動整體槓桿",
         "SPY 21 年：財報季與非財報季的已實現波動都是 15.6%。VIX 會自己反應。"),
        ("6", "事件溢價每次重新量，別假設「大事前保費一定貴」",
         "台積電這次只被加價 3.6 個百分點，低於它自己過去 8 次法說的 4.89%。"),
    ]
    y = 84.0
    for n, head, sub in acts:
        ax.add_patch(Circle((7.4, y - 3.2), 2.5, fc=INK, ec="none"))
        ax.text(7.4, y - 3.2, n, fontsize=14, color="white", ha="center", va="center",
                fontweight="bold")
        ax.text(12.5, y - 1.6, head, fontsize=16, color=INK, va="center", fontweight="bold")
        ax.text(12.5, y - 6.0, sub, fontsize=12.5, color=MUTED, va="center")
        ax.plot([4, 96], [y - 9.4, y - 9.4], color=LINE, lw=0.8)
        y -= 12.2

    ax.text(4, 8.4, "市場現在的體溫：VIX 15.03　標普 500 = 7,575.39　費半 = 12,967（2026-07-10 收盤）",
            fontsize=13, color=MUTED, va="center")
    _save(fig, "4_action")


if __name__ == "__main__":
    panel1(); panel2(); panel3(); panel4()
    print("[render] done")
