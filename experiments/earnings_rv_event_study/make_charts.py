#!/usr/bin/env python3
"""Charts for the earnings-day RV event study. Reads only the evidence JSON."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = [
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
    "STHeiti",
    "sans-serif",
]
plt.rcParams["axes.unicode_minus"] = False

REPO = Path(__file__).resolve().parents[2]
EV = json.loads(
    (REPO / "storage/experiments/earnings_rv_event_study.json").read_text(
        encoding="utf-8"
    )
)
OUT = REPO / "storage/article_assets/earnings-rv-20260720"
OUT.mkdir(parents=True, exist_ok=True)

ks = EV["pooled_path"]["k"]
mean_path = EV["pooled_path"]["mean_abs_over_base"]
p25 = EV["pooled_path"]["p25"]
p75 = EV["pooled_path"]["p75"]
by_day = {b["k"]: b for b in EV["by_event_day"]}

# ── Figure 1: event-time path ────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5.6), dpi=150)
ax.fill_between(ks, p25, p75, color="#93c5fd", alpha=0.35, label="個別財報的中間 50% 範圍")
for r in EV["per_ticker"]:
    ax.plot(
        ks,
        [r["path"][str(k)] for k in ks],
        color="#94a3b8",
        lw=0.9,
        alpha=0.55,
        zorder=2,
    )
ax.plot(ks, mean_path, color="#1d4ed8", lw=2.8, marker="o", ms=5, zorder=4, label="8 檔平均")
ax.axhline(1.0, color="#111827", ls="--", lw=1.2, label="常態水準（財報前 30~11 日）")
ax.axvline(0, color="#dc2626", lw=1.0, alpha=0.5)

for k in (0, 1):
    ax.annotate(
        f"{mean_path[ks.index(k)]:.2f} 倍",
        xy=(k, mean_path[ks.index(k)]),
        xytext=(k + 0.5, mean_path[ks.index(k)] + 0.25),
        color="#1d4ed8",
        fontsize=11,
        fontweight="bold",
    )

ax.set_xticks(ks)
ax.set_xlabel("距離財報反應日的交易日（0 = 消化財報的第一個收盤）")
ax.set_ylabel("當日漲跌幅絕對值 ÷ 該檔常態水準（倍）")
ax.set_title(
    f"科技股財報日的波動放大：只有一天半\n"
    f"8 檔大型科技股 × 各 12 季，共 {EV['meta']['n_events']} 次財報"
    f"（{EV['meta']['sample_first_event']} ~ {EV['meta']['sample_last_event']}）",
    fontsize=13,
    fontweight="bold",
)
ax.legend(loc="upper left", fontsize=9)
ax.grid(alpha=0.25)
ax.set_ylim(0, max(mean_path) * 1.25)
fig.text(
    0.5,
    0.008,
    "資料來源：yfinance 日線（還原價）+ yfinance 財報公布日；灰線為個股平均路徑",
    ha="center",
    fontsize=8,
    color="#6b7280",
)
fig.tight_layout(rect=(0, 0.03, 1, 1))
f1 = OUT / "fig1_event_time_path.png"
fig.savefig(f1)
plt.close(fig)

# ── Figure 2: cross-section ──────────────────────────────────────────────
pt = sorted(EV["per_ticker"], key=lambda r: r["vol_amp_rms"])
names = [r["ticker"] for r in pt]
amp = [r["vol_amp_rms"] for r in pt]
base = [r["rv_base_mean"] for r in pt]

fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 5.4), dpi=150, sharey=True)
bars = a1.barh(names, amp, color="#1d4ed8", alpha=0.85)
for b, v in zip(bars, amp):
    a1.text(v + 0.06, b.get_y() + b.get_height() / 2, f"{v:.2f}×", va="center", fontsize=10)
a1.axvline(1.0, color="#111827", ls="--", lw=1)
a1.set_xlabel("財報日波動 ÷ 常態波動（倍）")
a1.set_title("放大倍數：Meta 最猛，蘋果最鈍", fontsize=12, fontweight="bold")
a1.set_xlim(0, max(amp) * 1.2)
a1.grid(axis="x", alpha=0.25)

bars2 = a2.barh(names, base, color="#f59e0b", alpha=0.85)
for b, v in zip(bars2, base):
    a2.text(v + 0.8, b.get_y() + b.get_height() / 2, f"{v:.0f}%", va="center", fontsize=10)
a2.set_xlabel("平時的年化波動率（%）")
xs = EV["cross_section"]
a2.set_title(
    f"平時波動大 ≠ 財報日放大多\n（兩欄排序相關性 ρ={xs['spearman_rho']:.2f}，p={xs['spearman_p']:.2f}）",
    fontsize=12,
    fontweight="bold",
)
a2.set_xlim(0, max(base) * 1.25)
a2.grid(axis="x", alpha=0.25)

fig.suptitle(
    "誰的財報日最會跳？答案不是輝達", fontsize=14, fontweight="bold"
)
fig.text(
    0.5,
    0.01,
    "資料來源：yfinance 日線（還原價）；各檔取最近 12 季財報，樣本 "
    f"{EV['meta']['sample_first_event']} ~ {EV['meta']['sample_last_event']}",
    ha="center",
    fontsize=8,
    color="#6b7280",
)
fig.tight_layout(rect=(0, 0.035, 1, 0.95))
f2 = OUT / "fig2_cross_section.png"
fig.savefig(f2)
plt.close(fig)

print(f1)
print(f2)
