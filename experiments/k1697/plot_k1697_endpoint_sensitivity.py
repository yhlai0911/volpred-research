#!/usr/bin/env python3
"""K1697 — TWII rolling gamma 端點敏感度圖（reader-facing）。

所有數值 hard-bound 到 experiments/k1697/k1697_results.json：
  - 2025-01-22 端點 → reconciliation_checks.^TWII_log_end_20250122_vs_predecessor
  - 2026-04-05 端點 → reconciliation_checks.twii_log_end_20260405_isolation
  - 2026-07-09 端點 → variants.adjclose.per_security.^TWII (canonical)
  - legacy 0.272 / 3.18 → comparison_table.^TWII.legacy_n121（無存活 JSON，虛線標註）
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
rec = RES["reconciliation_checks"]
canon = RES["variants"]["adjclose"]["per_security"]["^TWII"]
legacy = RES["comparison_table"]["^TWII"]["legacy_n121"]

points = [
    ("2025-01-22", rec["^TWII_log_end_20250122_vs_predecessor"]["gamma"],
     rec["^TWII_log_end_20250122_vs_predecessor"]["gamma_t"]),
    ("2026-04-05", rec["twii_log_end_20260405_isolation"]["gamma"],
     rec["twii_log_end_20260405_isolation"]["gamma_t"]),
    ("2026-07-09", canon["gamma"], canon["gamma_t"]),
]
labels = [p[0] for p in points]
gammas = [p[1] for p in points]
tstats = [p[2] for p in points]
x = list(range(len(points)))

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.2, 8.0), sharex=True,
                               gridspec_kw={"height_ratios": [1.15, 1.0]})

# ── Panel 1: gamma ────────────────────────────────────────────────────────
ax1.plot(x, gammas, "-o", color="#1f4e79", lw=2.4, ms=11, zorder=3)
ax1.axhline(legacy["gamma"], color="#c0392b", ls="--", lw=1.6, zorder=2)
ax1.text(-0.38, legacy["gamma"] + 0.006,
         f"論文舊值 {legacy['gamma']:.3f}（無存活 JSON，不可復現）",
         color="#c0392b", fontsize=11, va="bottom", ha="left")
for xi, g in zip(x, gammas):
    ax1.annotate(f"{g:.3f}", (xi, g), textcoords="offset points",
                 xytext=(0, 14), ha="center", fontsize=12.5, fontweight="bold",
                 color="#1f4e79")
ax1.annotate("", xy=(2, gammas[2]), xytext=(1, gammas[1]),
             arrowprops=dict(arrowstyle="->", color="#7f8c8d", lw=1.4, ls=":"))
ax1.text(1.5, (gammas[1] + gammas[2]) / 2 - 0.028,
         f"三個月移動 {gammas[1] - gammas[2]:.3f}", fontsize=11,
         ha="center", color="#7f8c8d")
ax1.set_ylabel("槓桿參數 γ（GJR-GARCH）", fontsize=12)
ax1.set_title("同一個模型、同一組設定，只換窗口結束日：台股加權指數 rolling γ",
              fontsize=14.5, fontweight="bold", pad=14)
ax1.set_ylim(0.10, 0.325)
ax1.grid(alpha=0.25, ls=":")

# ── Panel 2: t stat ───────────────────────────────────────────────────────
colors = ["#2e7d32" if t >= 1.96 else "#c0392b" for t in tstats]
ax2.bar(x, tstats, color=colors, width=0.42, zorder=3)
ax2.axhline(1.96, color="#000000", ls="--", lw=1.6, zorder=4)
ax2.text(0.52, 2.04, "5% 顯著門檻 t = 1.96", fontsize=11, va="bottom", ha="center")
for xi, t in zip(x, tstats):
    inside = t < 1.96
    ax2.annotate(f"t = {t:.2f}", (xi, t), textcoords="offset points",
                 xytext=(0, -22 if inside else 7), ha="center", fontsize=12,
                 fontweight="bold", color="white" if inside else colors[xi])
ax2.set_ylabel("穩健 t 值", fontsize=12)
ax2.set_ylim(0, 4.1)
ax2.set_xticks(x)
ax2.set_xticklabels([f"窗口結束日\n{l}" for l in labels], fontsize=11.5)
ax2.grid(axis="y", alpha=0.25, ls=":")

fig.text(0.5, 0.015,
         "資料：yfinance pinned snapshot（2026-07-12 下載）｜"
         "設定：GJR-GARCH(1,1)、rolling 窗口 2000 日、log 報酬、Bollerslev–Wooldridge 穩健 t｜"
         "來源：experiments/k1697/k1697_results.json",
         ha="center", fontsize=8.8, color="#555555")

fig.tight_layout(rect=(0, 0.035, 1, 1))
out = ROOT / "storage/assets/k1697_twii_rolling_gamma_endpoint.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, bbox_inches="tight", facecolor="white")
print(f"saved: {out}")
print(f"gammas={[round(g, 4) for g in gammas]} tstats={[round(t, 3) for t in tstats]}")
