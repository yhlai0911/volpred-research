"""K672 feed 文章配圖：
1) Knowledge base 分類分佈（top 12 category bar chart）
2) Evidence Hierarchy 金字塔（definitive 7 / strong 6 / emerging 5 / single 5 / open 7）

Data sources:
- storage/memory/knowledge.json (2043 entries, category counts)
- experiments/k672/k672_results.json (hierarchy counts)
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "experiments" / "k672" / "charts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Chart 1: category distribution ----------
with open(ROOT / "storage" / "memory" / "knowledge.json") as f:
    kb = json.load(f)

counts = Counter()
for entry in kb:
    cat = entry.get("category") or "unlabeled"
    counts[cat] += 1

top = counts.most_common(12)
labels = [c for c, _ in top][::-1]
values = [v for _, v in top][::-1]
total = sum(counts.values())

fig, ax = plt.subplots(figsize=(10, 6.2))
colors = plt.cm.viridis([i / len(labels) for i in range(len(labels))])
bars = ax.barh(labels, values, color=colors, edgecolor="black", linewidth=0.5)
for bar, v in zip(bars, values):
    pct = v / total * 100
    ax.text(
        bar.get_width() + max(values) * 0.01,
        bar.get_y() + bar.get_height() / 2,
        f"{v}  ({pct:.1f}%)",
        va="center",
        fontsize=9,
    )
ax.set_xlabel("Knowledge entries count")
ax.set_title(
    f"VolPred Knowledge Base — Top 12 Categories\n"
    f"(total N={total:,} entries, {counts.__len__():,} distinct categories)",
    fontsize=12,
)
ax.set_xlim(0, max(values) * 1.18)
ax.grid(True, axis="x", linestyle="--", alpha=0.4)
plt.tight_layout()
chart1 = OUT_DIR / "k672_knowledge_category_distribution.png"
plt.savefig(chart1, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"saved: {chart1}")

# ---------- Chart 2: evidence hierarchy pyramid ----------
with open(ROOT / "experiments" / "k672" / "k672_results.json") as f:
    k672 = json.load(f)

scorecard = k672["research_program_scorecard"]
layers = [
    ("Category A — Definitive", scorecard["category_a_proven"], "#1a5490",
     "Harvey t>3.0 OR 10+ confirmations"),
    ("Category B — Strong", scorecard["category_b_strong"], "#2e7d32",
     "5-9 independent confirmations"),
    ("Category C — Emerging", scorecard["category_c_emerging"], "#ef6c00",
     "2-4 confirmations, needs replication"),
    ("Category D — Single finding", scorecard["category_d_single"], "#8d6e63",
     "Unreplicated but important"),
    ("Open Questions", scorecard["open_questions"], "#c62828",
     "Active research frontier"),
]

fig, ax = plt.subplots(figsize=(10.5, 6.4))
max_width = 1.0
n_layers = len(layers)
for i, (name, count, color, subtitle) in enumerate(layers):
    # top is most definitive (narrowest), bottom widest (most open) — inverted pyramid of certainty
    # Here layer 0 (definitive) at top with wider bar to emphasise "most proven"
    # Use decreasing width as we go down to look like hierarchy triangle
    width = max_width * (1 - i * 0.12)
    y = n_layers - 1 - i
    left = (max_width - width) / 2
    rect = mpatches.Rectangle(
        (left, y + 0.1),
        width,
        0.78,
        facecolor=color,
        edgecolor="black",
        linewidth=0.9,
    )
    ax.add_patch(rect)
    ax.text(
        0.5,
        y + 0.58,
        f"{name}  —  n={count}",
        ha="center",
        va="center",
        color="white",
        fontsize=11,
        fontweight="bold",
    )
    ax.text(
        0.5,
        y + 0.28,
        subtitle,
        ha="center",
        va="center",
        color="white",
        fontsize=8.5,
        style="italic",
    )

ax.set_xlim(-0.05, 1.05)
ax.set_ylim(-0.2, n_layers + 0.2)
ax.set_xticks([])
ax.set_yticks([])
for spine in ("top", "right", "bottom", "left"):
    ax.spines[spine].set_visible(False)

ax.set_title(
    f"Evidence Hierarchy — K672 Synthesis of {scorecard['total_knowledge_entries']:,} knowledge entries\n"
    f"({scorecard['total_experiments_referenced']} experiments referenced, "
    f"{scorecard['papers_produced']} papers, {scorecard['strategies_live']}/{scorecard['strategies_total']} strategies live)",
    fontsize=12,
)
plt.tight_layout()
chart2 = OUT_DIR / "k672_evidence_hierarchy.png"
plt.savefig(chart2, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"saved: {chart2}")
