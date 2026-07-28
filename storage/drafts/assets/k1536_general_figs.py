#!/usr/bin/env python3
"""Charts for the K1536 general-audience draft.

Every plotted value is read programmatically from
experiments/k1536/k1536_results.json — nothing is hard-coded here.

Run:
    uv run python storage/drafts/assets/k1536_general_figs.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "experiments" / "k1536" / "k1536_results.json"
OUT = REPO / "storage" / "drafts" / "assets"

for cand in ("Heiti TC", "Songti TC", "PingFang TC", "Arial Unicode MS"):
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.family"] = cand
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

D = json.loads(SRC.read_text(encoding="utf-8"))

INK = "#1b1b1f"
GRID = "#d8d8de"
NEG = "#2f6f9f"   # measured direction (agri calmer)
POS = "#c2622d"   # hypothesised direction
MUTE = "#8a8a93"


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=9)
    ax.yaxis.grid(True, color=GRID, lw=0.7)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------- figure 1
# Full-sample mean difference (high-biodiversity minus control), 95% CI.
uncond = {t["metric"]: t for t in D["unconditional_tests"]}
order = ["rv_high_minus_control", "downside_high_minus_control"]
labels = ["已實現波動率", "下行半變異數"]

fig, ax = plt.subplots(figsize=(7.0, 3.9), dpi=170)
for i, key in enumerate(order):
    t = uncond[key]
    lo, hi = t["ci95"]
    ax.errorbar(
        t["mean"], i,
        xerr=[[t["mean"] - lo], [hi - t["mean"]]],
        fmt="o", color=NEG, ecolor=NEG, elinewidth=2.2,
        capsize=5, markersize=8, zorder=3,
    )
    ax.annotate(
        f"{t['mean']:+.4f}\nHAC t = {t['hac_t']:.2f}",
        (t["mean"], i), textcoords="offset points", xytext=(0, 16),
        ha="center", fontsize=9, color=INK,
    )

ax.axvline(0, color=MUTE, lw=1.2, ls="--", zorder=2)
ax.annotate("假說預測落在這條線右邊", (0, 1.42), textcoords="offset points",
            xytext=(8, 0), ha="left", va="center", fontsize=9, color=POS)
ax.set_yticks(range(len(order)))
ax.set_yticklabels(labels)
ax.set_ylim(-0.6, 1.7)
ax.set_xlabel("農林商品組 減 控制組（全樣本每日平均差，95% 信賴區間）", fontsize=9.5)
ax.set_title("兩個風險口徑都落在零的左邊", fontsize=12.5, color=INK, pad=12)
_style(ax)
fig.tight_layout()
fig.savefig(OUT / "k1536_general_unconditional_gap.png", bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- figure 2
# Event-window log RV ratio, per event, high vs control.
ev_name = {e["id"]: e["name"] for e in D["events"]}
ev_date = {e["id"]: e["date"] for e in D["events"]}
by_event: dict[str, dict[str, float]] = {}
for row in D["event_group_summary"]:
    by_event.setdefault(row["event_id"], {})[row["group"]] = row["log_rv_ratio"]

eids = sorted(by_event, key=lambda k: ev_date[k])
short = {
    "kunming_declaration": "昆明宣言",
    "gbf_adoption": "昆明-蒙特婁\n生物多樣性框架",
    "eudr_signed": "歐盟禁伐法\n簽署",
    "eudr_entry_force": "歐盟禁伐法\n生效",
    "tnfd_final": "TNFD\n最終建議",
    "eu_nature_restoration_adopted": "歐盟自然\n恢復法",
}

x = range(len(eids))
w = 0.38
fig, ax = plt.subplots(figsize=(8.4, 4.1), dpi=170)
ax.bar([i - w / 2 for i in x], [by_event[e]["high_biodiversity"] for e in eids],
       width=w, color=POS, label="農林商品組", zorder=3)
ax.bar([i + w / 2 for i in x], [by_event[e]["control"] for e in eids],
       width=w, color=NEG, label="控制組（金銀銅油氣）", zorder=3)
ax.axhline(0, color=MUTE, lw=1.1)
ax.set_xticks(list(x))
ax.set_xticklabels([short.get(e, e) for e in eids], fontsize=8.6)
ax.set_ylabel("事件後 / 事件前 波動率取對數比", fontsize=9.5)

boot = {t["metric"]: t for t in D["event_bootstrap_tests"]}["log_rv_ratio"]
ax.set_title(
    f"六次政策事件，方向對了但站不住（拔靴法 p = {boot['p_two_sided']:.3f}）",
    fontsize=12.5, color=INK, pad=12,
)
ax.legend(frameon=False, fontsize=9, loc="upper left")
_style(ax)
fig.tight_layout()
fig.savefig(OUT / "k1536_general_event_windows.png", bbox_inches="tight")
plt.close(fig)

print("wrote k1536_general_unconditional_gap.png, k1536_general_event_windows.png")
