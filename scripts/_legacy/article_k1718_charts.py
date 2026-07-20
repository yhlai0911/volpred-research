#!/usr/bin/env python3
"""K1718 reader-facing article figures — all numbers bound to k1718_results.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

apply_cjk_style(dpi=150)

RES = json.loads((ROOT / "experiments/k1718/k1718_results.json").read_text())
OUT = ROOT / "storage/assets/articles"
OUT.mkdir(parents=True, exist_ok=True)

ASSET_LABEL = {"n225": "日經 225", "topix_etf": "TOPIX ETF"}
FAM_LABEL = {"garch": "GARCH", "gjr": "GJR", "har_r2": "HAR-style"}
FAMS = ["garch", "gjr", "har_r2"]
ASSETS = ["n225", "topix_etf"]

cells = []
for a in ASSETS:
    for f in FAMS:
        m = RES["assets"][a]["metrics"]
        cw = RES["assets"][a]["comparisons"][f]["clark_west_primary"]
        cells.append(
            dict(
                label=f"{ASSET_LABEL[a]}\n{FAM_LABEL[f]}",
                base=m[f]["qlike"],
                aug=m[f + "_x_vix"]["qlike"],
                raw_p=cw["p_value_one_sided"],
                holm_p=cw["holm_p_value_6_tests"],
            )
        )

# ── Figure 1: QLIKE base vs +VIX（六格） ─────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5.4))
x = np.arange(6)
w = 0.36
base = [c["base"] for c in cells]
aug = [c["aug"] for c in cells]
labels = [c["label"] for c in cells]

ax = axes[0]
ax.bar(x - w / 2, base, w, label="原模型", color="#4C78A8")
ax.bar(x + w / 2, aug, w, label="加進落後美股 VIX", color="#E45756")
for i, (b, a_) in enumerate(zip(base, aug)):
    ax.text(i - w / 2, b, f"{b:.2f}", ha="center", va="bottom", fontsize=8)
    ax.text(i + w / 2, a_, f"{a_:.2f}", ha="center", va="bottom", fontsize=8)
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=9)
ax.set_ylabel("QLIKE 預測誤差（越低越好）")
ax.set_title("六格全部：加了 VIX 誤差反而變大", fontsize=12)
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3)

ax = axes[1]
raw = [c["raw_p"] for c in cells]
holm = [c["holm_p"] for c in cells]
ax.bar(x - w / 2, raw, w, label="校正前 p 值", color="#72B7B2")
ax.bar(x + w / 2, holm, w, label="Holm 校正後 p 值", color="#B279A2")
ax.axhline(0.05, color="#333333", ls="--", lw=1.2)
ax.text(1.55, 0.075, "0.05 門檻", ha="left", fontsize=9, color="#333333")
for i, (r, h) in enumerate(zip(raw, holm)):
    ax.text(i - w / 2, r, f"{r:.3f}", ha="center", va="bottom", fontsize=8)
    ax.text(i + w / 2, h, f"{h:.3f}", ha="center", va="bottom", fontsize=8)
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=9)
ax.set_ylabel("Clark-West 單尾 p 值")
ax.set_ylim(0, 1.15)
ax.set_title("兩格原本擠進 0.05，校正後全部退回", fontsize=12)
ax.legend(fontsize=9, loc="upper left")
ax.grid(axis="y", alpha=0.3)

fig.suptitle("K1718：落後一天的美股 VIX 對日股波動預測的增量（2020–2026 樣本外）", fontsize=13)
fig.tight_layout(rect=(0, 0.02, 1, 0.96))
fig.text(
    0.5,
    0.005,
    "資料：Yahoo Finance via yfinance；數值出自 experiments/k1718/k1718_results.json",
    ha="center",
    fontsize=8,
    color="#666666",
)
p1 = OUT / "k1718_vix_japan_gate_20260720.png"
fig.savefig(p1, bbox_inches="tight")
plt.close(fig)

# ── Figure 2: QLIKE 相對變化（%）──────────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 4.6))
pct = [(c["aug"] - c["base"]) / c["base"] * 100 for c in cells]
colors = ["#E45756" if p > 0 else "#4C78A8" for p in pct]
ax.barh(x, pct, color=colors)
for i, p in enumerate(pct):
    ax.text(p + 0.08, i, f"+{p:.2f}%", va="center", fontsize=9)
ax.set_yticks(x)
ax.set_yticklabels([lb.replace("\n", " / ") for lb in labels], fontsize=9)
ax.invert_yaxis()
ax.axvline(0, color="#333333", lw=1)
ax.set_xlim(0, max(pct) * 1.25)
ax.set_xlabel("加進 VIX 後 QLIKE 的變化（正值 = 預測變差）")
ax.set_title("六個預先寫死的格子，沒有一格往好的方向動", fontsize=12)
ax.grid(axis="x", alpha=0.3)
fig.text(
    0.5,
    -0.02,
    "資料：Yahoo Finance via yfinance；數值出自 experiments/k1718/k1718_results.json",
    ha="center",
    fontsize=8,
    color="#666666",
)
p2 = OUT / "k1718_qlike_delta_20260720.png"
fig.savefig(p2, bbox_inches="tight")
plt.close(fig)

for c in cells:
    print(
        c["label"].replace("\n", "/"),
        f"base={c['base']:.4f} aug={c['aug']:.4f} "
        f"delta={(c['aug']-c['base'])/c['base']*100:+.2f}% "
        f"raw_p={c['raw_p']:.4f} holm_p={c['holm_p']:.4f}",
    )
print("wrote", p1)
print("wrote", p2)
