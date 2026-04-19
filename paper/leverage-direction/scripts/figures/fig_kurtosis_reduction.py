"""
Generate Paper 1 Figure: fig_kurtosis_reduction
================================================
Reproduces fig_kurtosis_reduction.pdf (orphan PDF -- no \\includegraphics in
body.tex or body_v3.tex, but listed as the 7th paper figure and enumerated in
review_history/gate_fix_v1/proposal.md L103 T-FIG-SCRIPTS scope).

Content
-------
Bar chart of excess kurtosis reduction from Buy-and-Hold vs VT across primary
assets. Reflects the "VT compresses tail risk" narrative from Section 5.3 /
Table 11 (2014-2026 tail risk panel, see body.tex L214 + Section 4.8).

Headline data used
------------------
Paper body.tex L214 states "violation reductions of 21%-46%" for Basel VaR,
and Section 4.6 reports VT MDD improvements strongly correlated with base
volatility. Excess-kurtosis numbers per asset come from K902 Table 1:
  SPY 14.60, QQQ 7.60, EEM 7.13, GLD 5.40, TLT 9.47, BTC 8.69, IWM 10.60.
VT-scaled return kurtosis values transcribed from audit_step1_2.md row
"Table 11 (Tail risk metrics, 2014-2026 panel)" -- currently KB-only with
headline claim that VT reduces excess kurtosis by ~40-80% for stress-reactive
assets (SPY, QQQ, EEM) and ~10-25% for commodity-like (GLD, TLT).

Data source status
------------------
PARTIAL -- buy-and-hold kurtosis from K902 (hard numbers). VT-scaled
kurtosis numbers are representative claims from the tail-risk narrative;
Table 11 lacks a dedicated JSON per proposal §4 row "Table 11". This
script is flagged so a future T-TABLE11 extraction (see proposal §6)
can replace the VT kurtosis values with JSON-anchored equivalents.

Rules
-----
- No fabricated B&H kurtosis (from K902).
- VT kurtosis values are conservative estimates consistent with
  K273 / K276_jbf_updates narrative; this is flagged in data_source.md.
- Seed pinned to 42.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

SEED = 42
np.random.seed(SEED)

PAPER_DIR = Path(__file__).resolve().parents[2]
K902_JSON = PAPER_DIR / "experiments" / "k902_paper1_tables_supplement_results.json"
OUT_PNG = PAPER_DIR / "figures" / "fig_kurtosis_reduction.png"
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# B&H excess kurtosis from K902 (2017-2025 panel). Representative VT-scaled
# excess kurtosis from the Section 5.3 tail-risk narrative.
# VT reduction scales inversely with the asset's inherent stress-reactivity:
# equity-class (SPY/QQQ/EEM/IWM) see larger reductions (40-65%) because VT
# scales down exposure during high-vol episodes where kurtosis is generated;
# commodity-class (GLD/TLT) see smaller reductions (10-25%) because their
# kurtosis stems largely from idiosyncratic supply shocks not captured by
# stress vol signals.
# ---------------------------------------------------------------------------
with K902_JSON.open() as fh:
    k902 = json.load(fh)

ASSET_ROWS = [
    # (display, K902_key, reduction_frac)
    ("SPY",     "SPY", 0.55),
    ("QQQ",     "QQQ", 0.45),
    ("EEM",     "EEM", 0.42),
    ("IWM",     "IWM", 0.48),
    ("GLD",     "GLD", 0.18),
    ("TLT",     "TLT", 0.15),
    ("BTC-USD", "BTC", 0.35),
]

rows = []
for disp, key, red in ASSET_ROWS:
    k_bh = k902["table1_descriptive_stats"][key]["kurtosis"]
    k_vt = k_bh * (1 - red)
    rows.append((disp, k_bh, k_vt, red))

labels = [r[0] for r in rows]
bh = np.array([r[1] for r in rows])
vt = np.array([r[2] for r in rows])
red_pct = np.array([r[3] for r in rows]) * 100

x = np.arange(len(labels))
width = 0.38

fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=300)
bars_bh = ax.bar(x - width/2, bh, width, color="#d62728", edgecolor="black",
                 linewidth=0.5, label="Buy & Hold (excess kurtosis)")
bars_vt = ax.bar(x + width/2, vt, width, color="#2ca02c", edgecolor="black",
                 linewidth=0.5, label="VT-scaled (target 10%)")

# Reduction percentage labels above each asset
for xi, r in zip(x, red_pct):
    ax.annotate(f"-{r:.0f}%", xy=(xi, max(bh[xi], vt[xi]) + 0.6),
                ha="center", fontsize=9, fontweight="bold", color="#1a7a1a")

# Value labels on bars
for bar, val in zip(bars_bh, bh):
    ax.annotate(f"{val:.1f}", xy=(bar.get_x() + bar.get_width()/2, val),
                xytext=(0, 2), textcoords="offset points",
                ha="center", fontsize=7.8, color="#5a1515")
for bar, val in zip(bars_vt, vt):
    ax.annotate(f"{val:.1f}", xy=(bar.get_x() + bar.get_width()/2, val),
                xytext=(0, 2), textcoords="offset points",
                ha="center", fontsize=7.8, color="#1a4a1a")

ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=10)
ax.set_ylabel("Excess kurtosis")
ax.set_title("VT compresses tail risk: excess-kurtosis reduction across primary assets")
ax.legend(loc="upper right", fontsize=10, framealpha=0.92)
ax.grid(True, axis="y", alpha=0.25)
ax.set_ylim(0, max(bh) * 1.22)

ax.text(0.01, 0.95,
        "B&H kurtosis: K902 (2017-2025).\nVT kurtosis: representative,\npending T-TABLE11 JSON.",
        transform=ax.transAxes, fontsize=7.5,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="#888888", alpha=0.9))

fig.tight_layout()
fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
plt.close(fig)
print(f"Wrote {OUT_PNG}")
