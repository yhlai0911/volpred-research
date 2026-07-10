"""Lazypack (懶人包) poster set. Every number is read from credit_silence_results.json."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parents[1] / "storage" / "reports" / "assets" / "credit_silence_20260710"
ASSETS.mkdir(parents=True, exist_ok=True)

res = json.loads((HERE / "credit_silence_results.json").read_text(encoding="utf-8"))
cur = res["current"]
cond = res["conditional_on_equity_vol_spike"]

# A CJK-capable font, otherwise every glyph renders as a tofu box.
for name in ("PingFang TC", "Heiti TC", "Songti TC", "Arial Unicode MS", "STHeiti"):
    if any(f.name == name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = name
        break
plt.rcParams["axes.unicode_minus"] = False

INK = "#0f172a"
EQUITY = "#c2410c"
CREDIT = "#0f766e"
MUTED = "#64748b"


def poster(name: str, kicker: str, headline: str, blocks: list[tuple[str, str]], footer: str):
    fig = plt.figure(figsize=(7.2, 9.0), facecolor="white")
    fig.text(0.08, 0.945, kicker, fontsize=11, color=EQUITY, weight="bold")
    fig.text(0.08, 0.90, headline, fontsize=19, color=INK, weight="bold", va="top", wrap=True)

    y = 0.775
    for big, small in blocks:
        fig.text(0.08, y, big, fontsize=27, color=CREDIT, weight="bold", va="top")
        fig.text(0.08, y - 0.058, small, fontsize=12.5, color=INK, va="top", wrap=True)
        y -= 0.185

    fig.text(0.08, 0.055, footer, fontsize=9, color=MUTED, va="top", wrap=True)
    fig.text(0.08, 0.018, "VolPred · volpred.zeabur.app", fontsize=9, color=MUTED)
    out = ASSETS / name
    fig.savefig(out, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", out.name)


poster(
    "lazy1_concept.png",
    "懶人包 1 / 一句話",
    "股票在變吵，債券在變安靜",
    [
        (f"QQQ  {cur['qqq_rv']:.1f}%", f"那斯達克 100 的二十日已實現波動率，比自己的六十日均值高 {cur['qqq_rv_change']:+.1f} 個百分點。"),
        (f"HYG  {cur['hyg_rv']:.2f}%", f"高收益債 ETF 的同一個指標，比自己的六十日均值低 {abs(cur['hyg_rv_change']):.2f} 個百分點。"),
        (f"利差  {cur['hy_oas']:.2f}%", f"高收益利差反而收窄 {abs(cur['hy_oas_bp_change']):.1f} 個基點。VIX 只有 {cur['vix']:.2f}。"),
    ],
    f"資料截至 {cur['as_of']} 美股收盤。股價 yfinance，利差 FRED ICE BofA。",
)

poster(
    "lazy2_data.png",
    "懶人包 2 / 放進歷史裡看",
    "利差收窄不稀奇，債券變安靜才稀奇",
    [
        (f"{cond['n_days']} 天", f"過去股票波動率同樣高出六十日均值 {cur['qqq_rv_change']:.1f} 個百分點以上的交易日總數。"),
        (f"{cond['hy_oas_bp_change']['share_negative']:.0f}%", f"其中利差同樣收窄的日子比例。今天的 {cur['hy_oas_bp_change']:+.1f} 基點落在第 {cond['hy_oas_bp_change']['current_percentile']:.0f} 百分位，偏低但不罕見。"),
        ("最低的一天", f"今天 HYG 波動率 {cur['hyg_rv_change']:+.2f} 個百分點的降幅，是這 {cond['n_days']} 天裡最低。"),
    ],
    "條件樣本使用重疊的二十日視窗，彼此自相關；百分位是描述性位置，不是顯著性檢定。",
)

poster(
    "lazy3_takeaway.png",
    "懶人包 3 / 該盯什麼",
    "先動的是波動率，不是利差",
    [
        ("0.672", "全樣本裡 QQQ 與 HYG 二十日波動率的相關係數。它們長期一起動，現在是偏離。"),
        (f"−{abs(cur['qqq_drawdown_pct']):.2f}%", "QQQ 距離 252 日高點的幅度。指數沒真的跌，高波動來自內部換手，不等於償債風險。"),
        ("3.3% → 均值", "當 HYG 的二十日波動率往上穿回它的六十日均值，代表信用資產價格開始不安分。"),
    ],
    "本文只做同期比較，不宣稱因果，不構成投資建議。",
)

for src, dst in (
    ("fig1_vol_divergence.png", "fig1_vol_divergence.png"),
    ("fig2_conditional_credit.png", "fig2_conditional_credit.png"),
):
    shutil.copy(HERE / src, ASSETS / dst)
    print("copied", dst)
