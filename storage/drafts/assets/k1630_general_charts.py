#!/usr/bin/env python3
"""Reader-facing (Traditional Chinese) charts for the Halloween / Sell-in-May draft.

All numbers are read programmatically from experiments/k1630/k1630_results.json.
Nothing is hard-coded. Run from repo root:

    uv run python storage/drafts/assets/k1630_general_charts.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from plot_style import apply_cjk_style  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

apply_cjk_style(dpi=150)

RESULTS = ROOT / "experiments" / "k1630" / "k1630_results.json"
OUT_DIR = Path(__file__).resolve().parent

data = json.loads(RESULTS.read_text(encoding="utf-8"))
res = data["results"]

CELLS = [
    ("美股\n1928–2026", res["US_SP500"]["full"], "#2F6FBF"),
    ("美股\n2011–2026", res["US_SP500"]["last15y"], "#8FB8E8"),
    ("台股\n1997–2026", res["TW_TAIEX"]["full"], "#C0392B"),
    ("台股\n2011–2026", res["TW_TAIEX"]["last15y"], "#E8A29B"),
]

labels = [c[0] for c in CELLS]
colors = [c[2] for c in CELLS]
betas = [c[1]["hac_regression"]["beta_mean_diff_monthly"] * 100 for c in CELLS]
lo = [c[1]["block_bootstrap"]["ci95_low"] * 100 for c in CELLS]
hi = [c[1]["block_bootstrap"]["ci95_high"] * 100 for c in CELLS]
winter = [c[1]["nov_apr"]["mean_monthly"] * 100 for c in CELLS]
summer = [c[1]["may_oct"]["mean_monthly"] * 100 for c in CELLS]
n_months = [c[1]["n_months_total"] for c in CELLS]

# ── Chart 1: effect size with 95% interval ────────────────────────────────
fig, ax = plt.subplots(figsize=(9.2, 5.6))
x = range(len(CELLS))
err_lo = [b - l for b, l in zip(betas, lo)]
err_hi = [h - b for b, h in zip(betas, hi)]
ax.bar(x, betas, color=colors, width=0.56, zorder=2)
ax.errorbar(
    x, betas, yerr=[err_lo, err_hi], fmt="none",
    ecolor="#333333", elinewidth=1.6, capsize=9, capthick=1.6, zorder=3,
)
ax.axhline(0, color="#111111", linewidth=1.2, zorder=4)
for i, (b, h) in enumerate(zip(betas, hi)):
    ax.text(i, h + 0.16, f"+{b:.2f}", ha="center", fontsize=11, fontweight="bold")
ax.set_xticks(list(x))
ax.set_xticklabels(labels, fontsize=11)
ax.set_ylabel("冬半年月均報酬 減 夏半年月均報酬（百分點／月）", fontsize=11)
ax.set_title("冬半年真的比夏半年好嗎？四組資料的答案與它們的不確定範圍", fontsize=13.5, pad=14)
ax.set_ylim(-1.3, 4.35)
ax.grid(axis="y", alpha=0.25, zorder=0)
ax.text(
    0.015, 0.965,
    "黑色直線＝這個差距合理可能落在的範圍。\n範圍碰到底下那條零線，就代表「兩個半年沒差別」還沒被排除。",
    transform=ax.transAxes, va="top", fontsize=10.5,
    bbox=dict(boxstyle="round,pad=0.45", facecolor="#F4F4F2", edgecolor="#CCCCCC"),
)
for spine in ("top", "right"):
    ax.spines[spine].set_visible(False)
fig.tight_layout()
fig.savefig(OUT_DIR / "k1630_general_effect_ci.png", bbox_inches="tight")
plt.close(fig)

# ── Chart 2: winter vs summer monthly means ───────────────────────────────
fig, ax = plt.subplots(figsize=(9.2, 5.2))
w = 0.34
xs = [i for i in range(len(CELLS))]
ax.bar([i - w / 2 for i in xs], winter, width=w, color="#2E7D46", label="冬半年（11 月–4 月）", zorder=2)
ax.bar([i + w / 2 for i in xs], summer, width=w, color="#E07B2A", label="夏半年（5 月–10 月）", zorder=2)
for i, v in zip(xs, winter):
    ax.text(i - w / 2, v + 0.06, f"{v:+.2f}", ha="center", fontsize=10)
for i, v in zip(xs, summer):
    off = 0.06 if v >= 0 else -0.18
    ax.text(i + w / 2, v + off, f"{v:+.2f}", ha="center", fontsize=10)
ax.axhline(0, color="#111111", linewidth=1.1, zorder=3)
ax.set_xticks(xs)
ax.set_xticklabels([f"{lab}\n({n} 個月)" for lab, n in zip(labels, n_months)], fontsize=10.5)
ax.set_ylabel("月平均報酬（％）", fontsize=11)
ax.set_title("兩個半年各自的月平均報酬：只有台股全期間的夏半年是負的", fontsize=13.5, pad=14)
ax.set_ylim(-0.75, 2.15)
ax.legend(fontsize=10.5, frameon=False, loc="upper right")
ax.grid(axis="y", alpha=0.25, zorder=0)
for spine in ("top", "right"):
    ax.spines[spine].set_visible(False)
fig.tight_layout()
fig.savefig(OUT_DIR / "k1630_general_winter_summer.png", bbox_inches="tight")
plt.close(fig)

print("beta pp/month :", [round(b, 3) for b in betas])
print("ci95 low      :", [round(v, 3) for v in lo])
print("ci95 high     :", [round(v, 3) for v in hi])
print("winter %/mo   :", [round(v, 3) for v in winter])
print("summer %/mo   :", [round(v, 3) for v in summer])
print("n months      :", n_months)
print("hac p         :", [round(c[1]["hac_regression"]["p_hac_auto"], 4) for c in CELLS])
print("wrote:", OUT_DIR / "k1630_general_effect_ci.png")
print("wrote:", OUT_DIR / "k1630_general_winter_summer.png")
