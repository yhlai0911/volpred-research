"""K647 follow-up chart generation for live-OOS general-audience article.

Generates:
  (a) sharpe_vs_mdd_pareto.png — live Sharpe vs MDD scatter, Piecewise Conservative
      flagged as Pareto-frontier in 15-month live sample
  (b) net_sharpe_after_tx.png — live Sharpe vs net-Sharpe (after TX cost),
      sorted descending by net_sharpe; negative net_sharpe shaded
  (c) profile_match_matrix.png — top-3 recommendation matrix per profile

Reads experiments/k647/k647_results.json (no live recompute; results JSON is
canonical).
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "experiments" / "k647" / "k647_results.json"
OUT = ROOT / "experiments" / "k647"

# ---------- Font: prefer CJK font if available ----------
for fam in ["PingFang TC", "Heiti TC", "Hiragino Sans GB", "Noto Sans CJK TC", "Arial Unicode MS"]:
    try:
        mpl.font_manager.findfont(fam, fallback_to_default=False)
        mpl.rcParams["font.sans-serif"] = [fam] + mpl.rcParams["font.sans-serif"]
        break
    except Exception:
        continue
mpl.rcParams["axes.unicode_minus"] = False

with open(RESULTS, "r", encoding="utf-8") as f:
    R = json.load(f)

DB = R["strategy_database"]


# ---------- Chart (a): live Sharpe vs MDD with Pareto highlight ----------
fig, ax = plt.subplots(figsize=(9, 6))

names = []
sharpes = []
mdds = []
for k, v in DB.items():
    names.append(v["display_name"])
    sharpes.append(v["live_sharpe"])
    mdds.append(v["mdd_pct"])

sharpes_a = np.array(sharpes)
mdds_a = np.array(mdds)

# scatter colored by net_sharpe sign
net_s = np.array([DB[k]["net_sharpe"] for k in DB.keys()])
colors = ["#d62728" if ns < 0 else "#1f77b4" for ns in net_s]

ax.scatter(mdds_a, sharpes_a, c=colors, s=120, alpha=0.75, edgecolors="white", linewidth=1.2)

# Highlight piecewise conservative
pc_idx = list(DB.keys()).index("piecewise_conservative")
ax.scatter(mdds_a[pc_idx], sharpes_a[pc_idx], s=380, facecolors="none",
           edgecolors="#ffbb33", linewidth=3.0, zorder=5,
           label="Piecewise Conservative VT (Pareto-frontier in this 15-month live sample)")

for i, n in enumerate(names):
    short = n.replace(" Conditional ", " Cond ").replace("Piecewise ", "Piecewise\n")
    ax.annotate(short, (mdds_a[i], sharpes_a[i]),
                xytext=(6, 5), textcoords="offset points", fontsize=8.5)

ax.set_xlabel("Maximum Drawdown (%) — 越靠右越淺", fontsize=11)
ax.set_ylabel("Live Sharpe Ratio (15-month OOS)", fontsize=11)
ax.set_title("策略池：Live Sharpe vs Maximum Drawdown\n紅點 = net Sharpe 為負 (TX cost 吃光收益)", fontsize=12)
ax.axhline(0, color="grey", linewidth=0.5, alpha=0.4)
ax.grid(True, alpha=0.25)
ax.legend(loc="lower right", fontsize=9)

fig.tight_layout()
out_a = OUT / "sharpe_vs_mdd_pareto.png"
fig.savefig(out_a, dpi=130)
plt.close(fig)
print(f"wrote {out_a}")


# ---------- Chart (b): live Sharpe vs net Sharpe (after TX cost) ----------
fig, ax = plt.subplots(figsize=(10, 6))

# sort by net_sharpe desc
items = sorted(DB.items(), key=lambda kv: kv[1]["net_sharpe"], reverse=True)
labels = [v["display_name"] for k, v in items]
live = [v["live_sharpe"] for k, v in items]
net = [v["net_sharpe"] for k, v in items]
tx = [v["tx_cost_annual_pct"] for k, v in items]

x = np.arange(len(labels))
width = 0.38

bars1 = ax.bar(x - width/2, live, width, label="Live Sharpe (gross)", color="#4c78a8")
bars2 = ax.bar(x + width/2, net, width, label="Net Sharpe (after TX cost)",
               color=["#d62728" if v < 0 else "#2ca02c" for v in net])

ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
ax.axhline(0, color="black", linewidth=0.6)
ax.set_ylabel("Sharpe Ratio")
ax.set_title("交易成本是策略排序的關鍵差異化\n綠 = 扣完 TX cost 仍正報酬；紅 = TX cost 吃光報酬", fontsize=12)
ax.legend(loc="upper right", fontsize=10)
ax.grid(True, axis="y", alpha=0.25)

# annotate TX cost above each pair
for i, t in enumerate(tx):
    ax.text(x[i], max(live[i], net[i]) + 0.15, f"TX:{t:.1f}%",
            ha="center", fontsize=8, color="#444")

fig.tight_layout()
out_b = OUT / "net_sharpe_after_tx.png"
fig.savefig(out_b, dpi=130)
plt.close(fig)
print(f"wrote {out_b}")


# ---------- Chart (c): profile-strategy match matrix (top-3) ----------
fig, ax = plt.subplots(figsize=(10, 4.5))

profiles = ["conservative_retiree", "young_professional", "sophisticated_investor"]
profile_labels = ["保守型 (退休族)", "標準型 (上班族)", "成熟型 (高資本)"]

# build cell text grid: rows = profile, cols = rank 1/2/3
cell_text = []
for p in profiles:
    row = []
    for entry in R["recommendations"][p]["top3"]:
        cell = f"{entry['display_name']}\nSharpe {entry['live_sharpe']:.2f} | MDD {entry['mdd_pct']:.1f}%\nscore {entry['score']:.2f}"
        row.append(cell)
    cell_text.append(row)

# colour by rank
colours = [["#7fcdbb", "#c7e9b4", "#ffffd9"] for _ in profiles]

table = ax.table(cellText=cell_text,
                 rowLabels=profile_labels,
                 colLabels=["第一名", "第二名", "第三名"],
                 cellColours=colours,
                 cellLoc="center",
                 loc="center")
table.auto_set_font_size(False)
table.set_fontsize(9.5)
table.scale(1, 2.6)

ax.axis("off")
ax.set_title("K647 配對演算法：三種投資人 Profile → Top-3 策略推薦\n(基於 2025-01 至 2026-03 共 15 個月 live OOS Sharpe + MDD + TX cost penalty)", fontsize=11.5)

fig.tight_layout()
out_c = OUT / "profile_match_matrix.png"
fig.savefig(out_c, dpi=130)
plt.close(fig)
print(f"wrote {out_c}")
