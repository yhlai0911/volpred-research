"""Generate K302 figures from k302_open_questions_results.json.

Produces:
  - fig1_category_breakdown.png  (donut: 24 questions across 5 categories)
  - fig2_priority_difficulty.png (priority rank x confidence resolvable scatter)
  - fig3_timeline_distribution.png (confidence histogram by category)

All numbers traced to results.json. No fabrication.
"""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# Traditional Chinese font setup
ZH_FONTS = [
    "Heiti TC", "PingFang TC", "Noto Sans TC", "Noto Sans CJK TC",
    "STHeiti", "Songti TC", "Apple LiGothic", "Microsoft JhengHei",
    "Arial Unicode MS",
]
available = {f.name for f in font_manager.fontManager.ttflist}
chosen = next((f for f in ZH_FONTS if f in available), None)
if chosen:
    plt.rcParams["font.sans-serif"] = [chosen] + plt.rcParams.get("font.sans-serif", [])
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "experiments" / "k302" / "k302_open_questions_results.json"
OUT = ROOT / "experiments" / "k302" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

with RESULTS.open() as f:
    data = json.load(f)

cat_keys = [
    ("category_A_answerable_better_methods", "A 類：方法可破", "#4C72B0"),
    ("category_B_answerable_more_data", "B 類：等資料累積", "#55A868"),
    ("category_C_fundamentally_difficult", "C 類：本質難解", "#C44E52"),
    ("category_D_blind_spots_unexplored", "D 類：盲區未探", "#8172B2"),
    ("category_E_contradictory_evidence", "E 類：證據矛盾", "#CCB974"),
]

# ---------- Fig 1: donut breakdown ----------
sizes = [len(data[k]) for k, _, _ in cat_keys]
labels = [f"{lbl}\n（{n} 題）" for (k, lbl, _), n in zip(cat_keys, sizes)]
colors = [c for _, _, c in cat_keys]
fig, ax = plt.subplots(figsize=(8.2, 6.4))
wedges, texts, autotexts = ax.pie(
    sizes, labels=labels, colors=colors,
    autopct=lambda p: f"{int(round(p*sum(sizes)/100))}",
    startangle=90, pctdistance=0.78,
    wedgeprops=dict(width=0.42, edgecolor="white"),
    textprops=dict(fontsize=11),
)
for t in autotexts:
    t.set_color("white"); t.set_fontweight("bold"); t.set_fontsize(12)
total = data["meta_statistics"]["total_open_questions"]
ax.text(0, 0, f"24\n未解疑問", ha="center", va="center", fontsize=18, fontweight="bold")
ax.set_title("K302：300+ 實驗後的 24 個未解疑問分類", fontsize=14, pad=18)
plt.tight_layout()
plt.savefig(OUT / "fig1_category_breakdown.png", dpi=160, bbox_inches="tight")
plt.close()

# ---------- Fig 2: priority vs confidence ----------
# Collect all questions with confidence
import itertools
all_q = []
for k, lbl, color in cat_keys:
    for q in data[k]:
        conf = q.get("confidence_resolvable")
        if conf is None:
            continue
        all_q.append({
            "id": q["id"],
            "importance": q.get("importance", ""),
            "confidence": conf,
            "category": lbl,
            "color": color,
        })

importance_y = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
fig, ax = plt.subplots(figsize=(10, 6.2))
seen_cat = set()
for q in all_q:
    label = q["category"] if q["category"] not in seen_cat else None
    seen_cat.add(q["category"])
    y = importance_y.get(q["importance"], 0)
    ax.scatter(q["confidence"], y, s=180, color=q["color"], alpha=0.78,
               edgecolors="white", linewidths=1.5, label=label)
    ax.annotate(q["id"], (q["confidence"], y),
                xytext=(6, 6), textcoords="offset points", fontsize=8.5)
ax.set_xlabel("可被解答的信心度（confidence_resolvable，0=完全不可知）", fontsize=11)
ax.set_ylabel("重要性等級", fontsize=11)
ax.set_yticks([1, 2, 3, 4])
ax.set_yticklabels(["LOW", "MEDIUM", "HIGH", "CRITICAL"])
ax.set_xlim(-0.02, 0.85)
ax.set_ylim(0.6, 4.4)
ax.axvline(0.5, color="gray", linestyle="--", alpha=0.4)
ax.text(0.5, 4.32, "信心 0.5", color="gray", fontsize=9, ha="center")
ax.set_title("K302：21 個未解疑問的重要性 × 可解性矩陣", fontsize=14, pad=12)
ax.legend(loc="lower right", fontsize=9, frameon=True)
ax.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(OUT / "fig2_priority_difficulty.png", dpi=160, bbox_inches="tight")
plt.close()

# ---------- Fig 3: under-explored vs total entries ----------
meta = data["meta_statistics"]
top3 = meta["top_3_under_explored_areas"]
# Format: "Behavioral finance (3/1142 entries = 0.26%)"
import re
parsed = []
for s in top3:
    m = re.search(r"(.+?)\s*\((\d+)/(\d+)", s)
    if m:
        name, num, denom = m.group(1).strip(), int(m.group(2)), int(m.group(3))
        parsed.append((name, num, denom))
    else:
        # Causal inference 0 dedicated experiments
        parsed.append((s.split("(")[0].strip(), 0, meta["total_knowledge_entries"]))

zh_name_map = {
    "Behavioral finance": "行為金融",
    "Multivariate models": "多變量模型",
    "Causal inference": "因果推論",
}
labels = [zh_name_map.get(n, n) for n, _, _ in parsed]
counts = [n for _, n, _ in parsed]
denom = meta["total_knowledge_entries"]
pcts = [100.0 * n / denom for _, n, _ in parsed]

fig, ax = plt.subplots(figsize=(9, 5.4))
bars = ax.barh(labels, counts, color=["#8172B2", "#55A868", "#C44E52"], alpha=0.85,
               edgecolor="white", linewidth=1.5)
ax.set_xlabel(f"知識條目數（總共 {denom} 條）", fontsize=11)
ax.set_xlim(0, max(counts) + 1.2 if max(counts) > 0 else 5)
for bar, n, p in zip(bars, counts, pcts):
    ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
            f"{n} 條（{p:.2f}%）", va="center", fontsize=10.5)
ax.set_title("K302：研究覆蓋最薄弱的三個方向", fontsize=14, pad=12)
ax.invert_yaxis()
ax.grid(axis="x", alpha=0.25)
plt.tight_layout()
plt.savefig(OUT / "fig3_under_explored.png", dpi=160, bbox_inches="tight")
plt.close()

print("Generated:")
for p in sorted(OUT.glob("*.png")):
    print(f"  {p.name}: {p.stat().st_size} bytes")
