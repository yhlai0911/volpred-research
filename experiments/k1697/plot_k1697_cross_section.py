#!/usr/bin/env python3
"""K1697 — 同一端點（2026-07-09）下各標的 rolling gamma 與顯著性橫斷面。

數值 hard-bound 到 variants.adjclose.per_security（canonical adjclose 變體）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style(dpi=150)

RES = json.loads((ROOT / "experiments/k1697/k1697_results.json").read_text())
sec = RES["variants"]["adjclose"]["per_security"]

ZH = {
    "^TWII": "台股加權指數", "0050.TW": "0050 台灣50", "0056.TW": "0056 高股息",
    "2330.TW": "2330 台積電", "2317.TW": "2317 鴻海", "2454.TW": "2454 聯發科",
    "2383.TW": "2383 台光電", "2886.TW": "2886 兆豐金", "2412.TW": "2412 中華電",
    "2881.TW": "2881 富邦金", "2882.TW": "2882 國泰金", "2885.TW": "2885 元大金",
    "2891.TW": "2891 中信金", "SPY": "SPY 標普500 ETF",
}
order = ["0056.TW", "^TWII", "SPY", "2886.TW", "0050.TW", "2330.TW", "2891.TW",
         "2383.TW", "2885.TW", "2882.TW", "2454.TW", "2317.TW", "2881.TW", "2412.TW"]

rows = [(ZH[t], sec[t]["gamma"], sec[t]["gamma_t"]) for t in order]
rows.sort(key=lambda r: r[1])
names = [r[0] for r in rows]
gam = [r[1] for r in rows]
tv = [r[2] for r in rows]
y = list(range(len(rows)))

fig, ax = plt.subplots(figsize=(9.6, 7.4))
colors = ["#2e7d32" if abs(t) >= 1.96 else "#b0bec5" for t in tv]
ax.barh(y, gam, color=colors, height=0.62, zorder=3)
ax.axvline(0, color="#444444", lw=1.0, zorder=4)

for yi, (g, t) in enumerate(zip(gam, tv)):
    star = "  ← 5% 顯著" if abs(t) >= 1.96 else ""
    xpos = g + 0.006 if g >= 0 else 0.006
    ax.text(xpos, yi, f"{g:.3f}（t={t:.2f}）{star}", va="center", ha="left",
            fontsize=10.8, fontweight="bold" if abs(t) >= 1.96 else "normal",
            color="#1b5e20" if abs(t) >= 1.96 else "#455a64")

ax.set_yticks(y)
ax.set_yticklabels(names, fontsize=11.5)
ax.set_xlim(-0.075, 0.335)
ax.set_xlabel("槓桿參數 γ（同一窗口結束日 2026-07-09、同一組模型設定）", fontsize=12)
ax.set_title("14 檔標的 rolling γ 橫斷面：綠色才是 5% 顯著，灰色與 0 無異",
             fontsize=14.5, fontweight="bold", pad=14)
ax.grid(axis="x", alpha=0.25, ls=":")
for s in ("top", "right"):
    ax.spines[s].set_visible(False)

fig.text(0.5, 0.012,
         "資料：yfinance pinned snapshot（2026-07-12 下載）｜"
         "GJR-GARCH(1,1)、rolling 窗口 2000 日、還原權息報酬、Bollerslev–Wooldridge 穩健 t｜"
         "來源：experiments/k1697/k1697_results.json",
         ha="center", fontsize=8.8, color="#555555")

fig.tight_layout(rect=(0, 0.035, 1, 1))
out = ROOT / "storage/assets/k1697_rolling_gamma_cross_section.png"
fig.savefig(out, bbox_inches="tight", facecolor="white")
print(f"saved: {out}")
print("significant:", [(n, round(t, 2)) for n, _, t in rows if abs(t) >= 1.96])
