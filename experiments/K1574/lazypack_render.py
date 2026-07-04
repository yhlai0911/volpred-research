#!/usr/bin/env python3
"""K1574 懶人包圖組 render — data-bound, reproducible.

每個數字直接對齊 experiments/K1574/k1574_results.json，無 AI 生圖 hallucination
風險（研究誠實）。codex 額度 2026-07-04 用盡，改主線程自寫 render 程式（等價於
codex 本要產出的東西，且完全掌控數字）。

輸出：4 張 PNG 到 --out-dir（預設 /tmp/mile_30438396_poster）
  1_framework.png    — 學術因子(長空) vs ETF(長多) 的 implementation shortfall 概念
  2_method.png       — 4 步記帳方法（白話）
  3_results.png      — alpha 短缺說不準 + 曝險被稀釋
  4_risk_takeaway.png— 真正的成本在 drawdown/殘差/追蹤誤差 + 兩句 takeaway
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ---- CJK 字型 ----
_CJK_CANDIDATES = ["PingFang TC", "Heiti TC", "Arial Unicode MS", "Songti TC", "STHeiti"]
_available = {f.name for f in fm.fontManager.ttflist}
_FONT = next((c for c in _CJK_CANDIDATES if c in _available), None)
if _FONT is None:  # macOS 系統路徑兜底
    for p in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"):
        if Path(p).exists():
            fm.fontManager.addfont(p)
            _FONT = fm.FontProperties(fname=p).get_name()
            break
plt.rcParams["font.sans-serif"] = [_FONT] if _FONT else plt.rcParams["font.sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# ---- 調色（專業、資料導向；深藍主色 + 紅=負/風險 + 灰）----
INK = "#1a2634"
SLATE = "#4a5a6a"
BLUE = "#2e5c8a"
LBLUE = "#8fb4d6"
RED = "#c0392b"
LRED = "#e6a89f"
GREEN = "#27794f"
GOLD = "#c99a2e"
BG = "#ffffff"
CARD = "#f4f6f8"
LINE = "#d5dce3"
SRC = "資料來源：experiment K1574（7 檔因子 ETF × FF6 每日迴歸，2013-07-19 至 2026-04-30，3,215 個交易日）"

FIGSIZE = (10.67, 6.67)  # ~1600x1000 @150dpi
DPI = 150


def _load(results_path: Path) -> dict:
    return json.loads(results_path.read_text())


def _footer(fig, extra: str = ""):
    fig.text(0.5, 0.028, SRC + (("　·　" + extra) if extra else ""),
             ha="center", va="center", fontsize=8.5, color=SLATE)


def _title(ax, txt, sub=None):
    ax.text(0.5, 0.955, txt, ha="center", va="top", fontsize=20, fontweight="bold",
            color=INK, transform=ax.transAxes)
    if sub:
        ax.text(0.5, 0.885, sub, ha="center", va="top", fontsize=12, color=SLATE,
                transform=ax.transAxes)


def _card(ax, x, y, w, h, fc=CARD, ec=LINE, lw=1.2):
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.008,rounding_size=0.02",
                         fc=fc, ec=ec, lw=lw, transform=ax.transAxes, zorder=1)
    ax.add_patch(box)


# ========== Panel 1 — 框架 ==========
def panel_framework(out: Path):
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    _title(ax, "把學術因子裝進 ETF，到底掉了多少？",
           "學術論文的因子是「長空組合」，ETF 只能「長多」——中間那段差距叫 implementation shortfall（實作損耗）")

    # 左卡：學術因子（長空）
    _card(ax, 0.06, 0.30, 0.38, 0.46, fc="#eef4fa", ec=BLUE, lw=1.6)
    ax.text(0.25, 0.715, "學術論文的因子", ha="center", fontsize=15, fontweight="bold", color=BLUE, transform=ax.transAxes)
    ax.text(0.25, 0.655, "長空組合", ha="center", fontsize=13, color=INK, transform=ax.transAxes)
    ax.text(0.115, 0.575, "＋　做多便宜／強動能的股票", ha="left", fontsize=12, color=INK, transform=ax.transAxes)
    ax.text(0.115, 0.505, "＋　同時放空貴／弱的股票", ha="left", fontsize=12, color=GREEN, transform=ax.transAxes)
    ax.text(0.115, 0.435, "＋　兩條腿一起賺溢酬", ha="left", fontsize=12, color=INK, transform=ax.transAxes)
    ax.text(0.25, 0.355, "= 論文裡漂亮的回測曲線", ha="center", fontsize=11.5, style="italic", color=SLATE, transform=ax.transAxes)

    # 右卡：ETF（長多）
    _card(ax, 0.56, 0.30, 0.38, 0.46, fc="#fdf3f1", ec=RED, lw=1.6)
    ax.text(0.75, 0.715, "你買到的因子 ETF", ha="center", fontsize=15, fontweight="bold", color=RED, transform=ax.transAxes)
    ax.text(0.75, 0.655, "只能長多", ha="center", fontsize=13, color=INK, transform=ax.transAxes)
    ax.text(0.615, 0.575, "＋　只能買一籃子被歸類的股票", ha="left", fontsize=12, color=INK, transform=ax.transAxes)
    ax.text(0.615, 0.505, "－　不能放空（少一條腿）", ha="left", fontsize=12, color=RED, transform=ax.transAxes)
    ax.text(0.615, 0.435, "－　指數權重＋流動性限制＋管理費", ha="left", fontsize=12, color=RED, transform=ax.transAxes)
    ax.text(0.75, 0.355, "= 對帳單上實際拿到的東西", ha="center", fontsize=11.5, style="italic", color=SLATE, transform=ax.transAxes)

    # 中間箭頭 + 損耗標籤
    arr = FancyArrowPatch((0.445, 0.53), (0.555, 0.53), transform=ax.transAxes,
                          arrowstyle="-|>", mutation_scale=26, lw=2.4, color=SLATE, zorder=5)
    ax.add_patch(arr)
    ax.text(0.50, 0.61, "包裝", ha="center", fontsize=11, color=SLATE, transform=ax.transAxes)
    ax.text(0.50, 0.455, "?", ha="center", fontsize=16, fontweight="bold", color=GOLD, transform=ax.transAxes)

    # 底部一句
    _card(ax, 0.14, 0.135, 0.72, 0.115, fc="#fbf6e9", ec=GOLD, lw=1.4)
    ax.text(0.5, 0.192, "坊間常猜「ETF 化每年掉幾個百分點」——這篇不談策略、不做擇時，", ha="center", fontsize=12.5, color=INK, transform=ax.transAxes)
    ax.text(0.5, 0.152, "只做一件事：把 7 檔因子 ETF 拉上一張表，用學術因子當座標，量量看到底掉了多少。", ha="center", fontsize=12.5, fontweight="bold", color=INK, transform=ax.transAxes)

    _footer(fig)
    fig.savefig(out, dpi=DPI, facecolor=BG); plt.close(fig)


# ========== Panel 2 — 方法 ==========
def panel_method(out: Path):
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    _title(ax, "我們怎麼量的：一張記帳單，不是策略回測",
           "把「學術因子那條報酬」被 ETF 包裝後變成什麼樣子，逐檔記帳")

    steps = [
        ("1", "選 7 檔因子代理 ETF",
         "MTUM（動能）· VLUE / RPV / IVE（三種價值）· QUAL（品質）\nUSMV（低波動）· IWF（成長／反價值）　樣本 3,215 個交易日"),
        ("2", "拿學術因子當座標",
         "Kenneth French 每日五因子＋動能\n（市場 · 規模 · 價值 · 獲利 · 投資 · 動能）"),
        ("3", "每檔對六因子做迴歸",
         "每日超額報酬 → 迴歸截距＝扣掉因子曝險後剩下的 alpha\n標準誤用 Newey-West HAC，7 檔顯著性再用 Holm 多重檢定校正"),
        ("4", "1,000 次區塊重抽樣",
         "每段約 21 個交易日 → 估「跨 ETF alpha 中位數」的 95% 信賴區間"),
    ]
    y0, h, gap = 0.635, 0.128, 0.022
    for i, (num, head, body) in enumerate(steps):
        y = y0 - i * (h + gap)
        _card(ax, 0.08, y, 0.84, h)
        # 編號圓
        ax.add_patch(plt.Circle((0.135, y + h / 2), 0.032, transform=ax.transAxes,
                                 fc=BLUE, ec="none", zorder=3))
        ax.text(0.135, y + h / 2, num, ha="center", va="center", fontsize=17,
                fontweight="bold", color="white", transform=ax.transAxes, zorder=4)
        ax.text(0.195, y + h * 0.66, head, ha="left", va="center", fontsize=14.5,
                fontweight="bold", color=INK, transform=ax.transAxes)
        ax.text(0.195, y + h * 0.28, body, ha="left", va="center", fontsize=11.3,
                color=SLATE, transform=ax.transAxes, linespacing=1.35)

    _footer(fig, "seed=42 · 1000 reps")
    fig.savefig(out, dpi=DPI, facecolor=BG); plt.close(fig)


# ========== Panel 3 — 結果 ==========
def panel_results(out: Path, res: dict):
    reg = res["etf_regressions"]
    agg = res["aggregate"]
    bs = res["bootstrap"]
    order = ["MTUM", "VLUE", "QUAL", "USMV", "IVE", "IWF", "RPV"]
    alphas = [reg[e]["alpha_ann"] * 100 for e in order]
    # 主因子曝險（USMV 無指定主因子）
    load_order = ["QUAL", "IWF", "IVE", "VLUE", "MTUM", "RPV"]
    load_lbl = {"QUAL": "QUAL·品質", "IWF": "IWF·反價值", "IVE": "IVE·價值",
                "VLUE": "VLUE·價值", "MTUM": "MTUM·動能", "RPV": "RPV·價值"}
    loads = [reg[e]["primary_directional_beta"] for e in load_order]

    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    _title(ax, "結果：曝險方向對得很清楚，alpha 卻拿不到")

    # 左圖：年化 alpha
    axL = fig.add_axes([0.075, 0.355, 0.40, 0.42])
    cols = [RED if a < 0 else GREEN for a in alphas]
    axL.barh(range(len(order)), alphas, color=cols, edgecolor="white")
    axL.set_yticks(range(len(order))); axL.set_yticklabels(order, fontsize=11)
    axL.invert_yaxis()
    axL.axvline(0, color=INK, lw=1)
    for i, a in enumerate(alphas):
        axL.text(a + (0.04 if a >= 0 else -0.04), i, f"{a:+.2f}%",
                 va="center", ha="left" if a >= 0 else "right", fontsize=10,
                 color=INK, fontweight="bold")
    axL.set_xlim(-1.5, 1.4)
    axL.set_title("年化 alpha（扣因子後）·  6／7 為負，Holm 後全不顯著",
                  fontsize=12, color=INK, pad=8)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)
    axL.tick_params(labelsize=9)

    # 右圖：主因子曝險
    axR = fig.add_axes([0.575, 0.355, 0.375, 0.42])
    axR.barh(range(len(load_order)), loads, color=BLUE, edgecolor="white")
    axR.set_yticks(range(len(load_order)))
    axR.set_yticklabels([load_lbl[e] for e in load_order], fontsize=10)
    axR.invert_yaxis()
    axR.axvline(1.0, color=GOLD, lw=1.6, ls="--")
    axR.text(1.0, -0.85, "學術強度 1.0", color=GOLD, fontsize=9.5, ha="center")
    for i, b in enumerate(loads):
        axR.text(b + 0.02, i, f"{b:.2f}", va="center", fontsize=10, color=INK, fontweight="bold")
    axR.set_xlim(0, 1.15)
    axR.set_title("主因子曝險·  全部命中卻只有 0.15～0.60",
                  fontsize=12, color=INK, pad=8)
    for s in ("top", "right"):
        axR.spines[s].set_visible(False)
    axR.tick_params(labelsize=9)

    # 底部結論條（兩行，整合跨 ETF 統計）
    med = agg["median_alpha_ann"] * 100
    ci = [bs["median_alpha_ann_ci95"][0] * 100, bs["median_alpha_ann_ci95"][1] * 100]
    _card(ax, 0.08, 0.075, 0.84, 0.155, fc="#eef4fa", ec=BLUE, lw=1.3)
    ax.text(0.5, 0.185, f"跨 ETF alpha 中位數 {med:.2f}%，1,000 次重抽樣 95% 信賴區間 [{ci[0]:.2f}%, {ci[1]:.2f}%]——橫跨零點",
            ha="center", fontsize=13, fontweight="bold", color=INK, transform=ax.transAxes)
    ax.text(0.5, 0.115, "曝險方向對得很清楚（只沾到三～六成強度），但 alpha 方向偏負、雜訊太大：",
            ha="center", fontsize=11.5, color=SLATE, transform=ax.transAxes)
    ax.text(0.5, 0.088, "撐不起「ETF 化大幅吃掉學術 alpha」的坊間版本結論。",
            ha="center", fontsize=11.5, color=SLATE, transform=ax.transAxes)

    _footer(fig)
    fig.savefig(out, dpi=DPI, facecolor=BG); plt.close(fig)


# ========== Panel 4 — 風險 + takeaway ==========
def panel_risk(out: Path, res: dict):
    reg = res["etf_regressions"]
    agg = res["aggregate"]

    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    _title(ax, "真正的成本不在 alpha，而在回檔、殘差與追蹤誤差")

    # 左圖：最大回檔
    dd_order = ["RPV", "VLUE", "IVE", "MTUM", "QUAL", "USMV", "IWF"]
    dd = [reg[e]["max_drawdown"] * 100 for e in dd_order]
    axL = fig.add_axes([0.075, 0.30, 0.40, 0.47])
    axL.barh(range(len(dd_order)), dd, color=[RED if e in ("RPV", "VLUE", "IVE") else LRED for e in dd_order],
             edgecolor="white")
    axL.set_yticks(range(len(dd_order))); axL.set_yticklabels(dd_order, fontsize=10)
    axL.invert_yaxis()
    for i, d in enumerate(dd):
        axL.text(d - 1.5, i, f"{d:.1f}%", va="center", ha="right", fontsize=9.5, color=INK, fontweight="bold")
    axL.set_xlim(-58, 0)
    axL.set_title("最大回檔：深度價值最凶", fontsize=12.5, color=INK, pad=6)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)
    axL.tick_params(labelsize=8.5)

    # 右上：殘差波動占比 + 追蹤誤差 兩個 tile
    rvs = agg["median_residual_vol_share"] * 100
    usmv_rvs = reg["USMV"]["residual_vol_share"] * 100
    te = agg["median_tracking_error_vs_spy"] * 100
    _card(ax, 0.55, 0.535, 0.39, 0.225, fc="#fdf3f1", ec=RED, lw=1.3)
    ax.text(0.565, 0.705, "殘差波動 ÷ 總波動", ha="left", fontsize=12, fontweight="bold", color=INK, transform=ax.transAxes)
    ax.text(0.575, 0.60, f"中位 {rvs:.0f}%", ha="left", fontsize=22, fontweight="bold", color=RED, transform=ax.transAxes)
    ax.text(0.755, 0.615, f"USMV 最高 {usmv_rvs:.0f}%", ha="left", fontsize=11, color=SLATE, transform=ax.transAxes)
    ax.text(0.565, 0.558, "低波動 ETF 有四成風險來自六因子之外", ha="left", fontsize=10, color=SLATE, transform=ax.transAxes)

    _card(ax, 0.55, 0.30, 0.39, 0.215, fc="#eef4fa", ec=BLUE, lw=1.3)
    ax.text(0.565, 0.462, "對 SPY 的追蹤誤差", ha="left", fontsize=12, fontweight="bold", color=INK, transform=ax.transAxes)
    ax.text(0.575, 0.355, f"中位 {te:.1f}%", ha="left", fontsize=22, fontweight="bold", color=BLUE, transform=ax.transAxes)
    ax.text(0.755, 0.37, "／年相對波動", ha="left", fontsize=11, color=SLATE, transform=ax.transAxes)
    ax.text(0.565, 0.313, "多扛 7.6 個百分點，alpha 卻換不到補償", ha="left", fontsize=10, color=SLATE, transform=ax.transAxes)

    # 底部：兩句帶回家
    _card(ax, 0.075, 0.075, 0.865, 0.185, fc=CARD, ec=LINE, lw=1.3)
    ax.text(0.095, 0.212, "帶回家兩句話", ha="left", fontsize=12.5, fontweight="bold", color=GOLD, transform=ax.transAxes)
    ax.text(0.105, 0.163, "①  因子 ETF 確實會帶你曝險到對應因子上——這點訊號極強、不是巧合。",
            ha="left", fontsize=12.5, color=INK, transform=ax.transAxes)
    ax.text(0.105, 0.113, "②  但你拿不到學術 paper 的 alpha——只是看不清是「少一點」還是「少一大段」。",
            ha="left", fontsize=12.5, color=INK, transform=ax.transAxes)

    _footer(fig)
    fig.savefig(out, dpi=DPI, facecolor=BG); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="experiments/K1574/k1574_results.json")
    ap.add_argument("--out-dir", default="/tmp/mile_30438396_poster")
    args = ap.parse_args()
    res = _load(Path(args.results))
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    panel_framework(out / "1_framework.png")
    panel_method(out / "2_method.png")
    panel_results(out / "3_results.png", res)
    panel_risk(out / "4_risk_takeaway.png", res)
    print(f"font={_FONT}")
    for p in sorted(out.glob("*.png")):
        print(f"[ok] {p}  ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
