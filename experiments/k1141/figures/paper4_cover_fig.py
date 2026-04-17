"""
K1141: Paper 4 Cover Figure Generator
Heatmap 3×4 (Channel × Asset class), colored by signed DM t-stat

Reproducibility: reads all DM t from experiment JSONs.
No hardcoded values except for the FX column (no experiments).

Run:
    python experiments/k1141/figures/paper4_cover_fig.py

Outputs:
    experiments/k1141/figures/paper4_cover_fig.png  (300 dpi)
    experiments/k1141/figures/paper4_cover_fig.pdf  (vector)
"""

import json
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import TwoSlopeNorm

# ── Paths ──────────────────────────────────────────────────────────────────────
# Try main repo first; fall back to worktree-relative path
_this_dir = os.path.dirname(os.path.abspath(__file__))
# If running from worktree (.claude/worktrees/agent-xxx/experiments/k1141/figures/):
#   ../../../../../../  =>  volpred-research/
# If running from main repo (experiments/k1141/figures/):
#   ../../../../../     =>  volpred-research/
_candidate_main = os.path.abspath(os.path.join(_this_dir, "../../../../../../"))
_candidate_wt   = os.path.abspath(os.path.join(_this_dir, "../../../../../"))
if os.path.isdir(os.path.join(_candidate_main, "experiments")):
    REPO_ROOT = _candidate_main
else:
    REPO_ROOT = _candidate_wt
EXPERIMENTS = os.path.join(REPO_ROOT, "experiments")
OUT_DIR = os.path.dirname(__file__)


def load(relpath):
    with open(os.path.join(EXPERIMENTS, relpath)) as f:
        return json.load(f)


# ── Load experiment JSONs ──────────────────────────────────────────────────────
k1136 = load("k1136/k1136_results.json")
k1137 = load("k1137/k1137_results.json")
k1138 = load("k1138/k1138_results.json")
k1129 = load("K1129/k1129_results.json")
k1135 = load("k1135/k1135_results.json")
k1143 = load("k1143/k1143_results.json")

# ── Extract DM t-stats from JSONs (no hardcoding) ─────────────────────────────
nine = k1138["nine_cell_analysis"]["cell_results"]
ch_analysis = k1137["channel_analysis"]
pass_cells = k1137["pass_cells_BH"]

def get_pass_cell_t(ticker, model, regime):
    cells = [c for c in pass_cells if c["ticker"] == ticker and c["model"] == model and c["regime"] == regime]
    return cells[0]["DM_HLN_t"] if cells else None


# ── Channel 1: HAR-RV-X vs GJR ────────────────────────────────────────────────
# Equity: mean of SPY/QQQ/IWM DM t from K1138 nine_cell
spy_har_t = nine["SPY_HAR-RV-X"]["DM_HLN_t"]
qqq_har_t = nine["QQQ_HAR-RV-X"]["DM_HLN_t"]
iwm_har_t = nine["IWM_HAR-RV-X"]["DM_HLN_t"]
ch1_equity_t = (spy_har_t + qqq_har_t + iwm_har_t) / 3.0

# Commodity: mean of USO/GLD low-regime t from K1137
uso_har_low_t = get_pass_cell_t("USO", "M4_HAR_RV_X", "low")
gld_har_low_t = get_pass_cell_t("GLD", "M4_HAR_RV_X", "low")
ch1_commodity_t = (uso_har_low_t + gld_har_low_t) / 2.0

# Bond: TLT max-regime t from K1137
tlt_har_low_t  = get_pass_cell_t("TLT", "M4_HAR_RV_X", "low")
tlt_har_mid_t  = get_pass_cell_t("TLT", "M4_HAR_RV_X", "mid")
tlt_har_high_t = get_pass_cell_t("TLT", "M4_HAR_RV_X", "high")
ch1_bond_t = max(tlt_har_low_t, tlt_har_mid_t, tlt_har_high_t)

ch1_fx_t = None  # no experiment

# ── Channel 2: MIDAS-X vs GJR ─────────────────────────────────────────────────
# Equity: max DM t from K1138 nine_cell
spy_midas_t = nine["SPY_GARCH-MIDAS-X"]["DM_HLN_t"]
qqq_midas_t = nine["QQQ_GARCH-MIDAS-X"]["DM_HLN_t"]
iwm_midas_t = nine["IWM_GARCH-MIDAS-X"]["DM_HLN_t"]
ch2_equity_t = max(spy_midas_t, qqq_midas_t, iwm_midas_t)

# Commodity: max of USO/GLD/UNG from K1136 Fair Test 1 (M3 vs M1 on r^2)
uso_midas_t = k1136["per_asset_results"]["USO"]["per_target"]["r2_close"]["dm_tests"]["M3_GARCH_MIDAS_X_vs_M1"]["DM_HLN_t"]
gld_midas_t = k1136["per_asset_results"]["GLD"]["per_target"]["r2_close"]["dm_tests"]["M3_GARCH_MIDAS_X_vs_M1"]["DM_HLN_t"]
ung_midas_t = k1136["per_asset_results"]["UNG"]["per_target"]["r2_close"]["dm_tests"]["M3_GARCH_MIDAS_X_vs_M1"]["DM_HLN_t"]
ch2_commodity_t = max(uso_midas_t, gld_midas_t, ung_midas_t)

# Bond: TLT max across regimes from K1137
ch2_bond_t = ch_analysis["channel_2_MIDAS_conditional"]["TLT"]["max_DM_t"]

ch2_fx_t = None  # no experiment

# ── Channel 3: GAS-t vs GJR ───────────────────────────────────────────────────
# Equity: min (most harmful) from K1138 nine_cell
spy_gas_t = nine["SPY_GAS-t"]["DM_HLN_t"]
qqq_gas_t = nine["QQQ_GAS-t"]["DM_HLN_t"]
iwm_gas_t = nine["IWM_GAS-t"]["DM_HLN_t"]
ch3_equity_t = min(spy_gas_t, qqq_gas_t, iwm_gas_t)  # most harmful = most negative

# Commodity: symmetric GAS-t from K1129 (best = USO)
uso_gas_t = k1129["results"]["USO"]["dm_tests"]["M3_GAS_t_vs_M1"]["DM_HLN_t"]
gld_gas_t = k1129["results"]["GLD"]["dm_tests"]["M3_GAS_t_vs_M1"]["DM_HLN_t"]
ung_gas_t = k1129["results"]["UNG"]["dm_tests"]["M3_GAS_t_vs_M1"]["DM_HLN_t"]
ch3_commodity_t = max(uso_gas_t, gld_gas_t, ung_gas_t)
# Note: K1135 skew-t VaR/ES PASS → partial rescue; displayed as PASS† on figure

# Bond: TLT from K1137 channel 3
ch3_bond_t = ch_analysis["channel_3_GAS_rescue"]["TLT"]["max_DM_t"]

ch3_fx_t = None  # no experiment

# ── Assemble 3×4 data matrix ───────────────────────────────────────────────────
# Rows: Ch1, Ch2, Ch3 (index 0, 1, 2)
# Cols: Equity, Commodity, Bond, FX (index 0, 1, 2, 3)
data = np.full((3, 4), np.nan)
data[0, 0] = ch1_equity_t
data[0, 1] = ch1_commodity_t
data[0, 2] = ch1_bond_t
# data[0, 3] stays NaN (FX)

data[1, 0] = ch2_equity_t
data[1, 1] = ch2_commodity_t
data[1, 2] = ch2_bond_t
# data[1, 3] stays NaN (FX)

data[2, 0] = ch3_equity_t
data[2, 1] = ch3_commodity_t
data[2, 2] = ch3_bond_t
# data[2, 3] stays NaN (FX)

# Verdict labels and K-number references
verdicts = [
    ["PASS",       "PASS*",          "PASS",        "—"],
    ["NULL",       "NULL",           "NULL",         "—"],
    ["HARM",       "NULL/PASS†",     "PASS",         "—"],
]

k_refs = [
    ["K1138\nK1137",  "K1137\nK1136",     "K1137",     ""],
    ["K1138\nK1137",  "K1136\nK1137",     "K1137",     ""],
    ["K1138\nK1143",  "K1129\nK1135",     "K1137",     ""],
]

row_labels = [
    "Ch. 1\nHAR+VIX\nvs GJR",
    "Ch. 2\nMIDAS-X\nvs GJR",
    "Ch. 3\nGAS-t\nvs GJR",
]
col_labels = ["Equity\n(SPY/QQQ/IWM)", "Commodity\n(USO/GLD/UNG)", "Bond\n(TLT)", "FX\n(no expt.)"]

# ── Color mapping ──────────────────────────────────────────────────────────────
# Diverging colormap: red = negative (HARM), white = 0, green = positive (PASS)
# Clamp to [-12, +12] for visual balance
VMIN, VCENTER, VMAX = -4.0, 0.0, 12.0
norm = TwoSlopeNorm(vmin=VMIN, vcenter=VCENTER, vmax=VMAX)
cmap = matplotlib.colormaps["RdYlGn"]

# ── Figure ─────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5.5))

# Draw colored cells
for row in range(3):
    for col in range(4):
        val = data[row, col]
        if np.isnan(val):
            # FX column or missing: grey
            face_color = "#CCCCCC"
            text_color = "#666666"
        else:
            face_color = cmap(norm(val))
            text_color = "black"

        rect = mpatches.FancyBboxPatch(
            (col, 2 - row),
            1, 1,
            boxstyle="square,pad=0",
            linewidth=1.5,
            edgecolor="white",
            facecolor=face_color,
        )
        ax.add_patch(rect)

        # Verdict label (large)
        verdict = verdicts[row][col]
        ax.text(col + 0.5, 2 - row + 0.62, verdict,
                ha="center", va="center",
                fontsize=12.5, fontweight="bold",
                color=text_color)

        # DM t value (medium)
        if not np.isnan(val):
            ax.text(col + 0.5, 2 - row + 0.38, f"$t={val:+.2f}$",
                    ha="center", va="center", fontsize=9.5, color=text_color)
        else:
            ax.text(col + 0.5, 2 - row + 0.38, "",
                    ha="center", va="center", fontsize=9.5)

        # K-reference (small, bottom)
        k_ref = k_refs[row][col]
        if k_ref:
            ax.text(col + 0.5, 2 - row + 0.13, k_ref,
                    ha="center", va="center", fontsize=7.5,
                    color="#333333", style="italic")

# ── Axis labels ────────────────────────────────────────────────────────────────
ax.set_xlim(0, 4)
ax.set_ylim(0, 3)
ax.set_xticks([0.5, 1.5, 2.5, 3.5])
ax.set_xticklabels(col_labels, fontsize=10.5)
ax.set_yticks([0.5, 1.5, 2.5])
ax.set_yticklabels(row_labels[::-1], fontsize=10, va="center")
ax.tick_params(axis="both", length=0)

# Remove spines
for spine in ax.spines.values():
    spine.set_visible(False)

# ── Colorbar ───────────────────────────────────────────────────────────────────
sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
sm.set_array([])
cbar = fig.colorbar(sm, ax=ax, orientation="vertical", fraction=0.025, pad=0.02)
cbar.set_label("DM HLN $t$-statistic\n(+: model beats GJR; −: model worse)", fontsize=9)
cbar.ax.axhline(y=0, color="black", linewidth=1.5, linestyle="--")
cbar.ax.axhline(y=2, color="darkgreen", linewidth=1, linestyle=":")
cbar.ax.axhline(y=-2, color="darkred", linewidth=1, linestyle=":")
# Note: cbar y is in data units (norm scale), but axhline uses axes [0,1]
# Reset with actual norm mapping
cbar.ax.axhline(y=norm(2), color="darkgreen", linewidth=1.2, linestyle=":")
cbar.ax.axhline(y=norm(-2), color="darkred", linewidth=1.2, linestyle=":")

# ── Legend / footnotes ─────────────────────────────────────────────────────────
legend_text = (
    "PASS: DM $t>+2$, BH $p<0.05$ ─── "
    "NULL: $|t|≤2$ or BH $p≥0.05$ ─── "
    "HARM: DM $t<-2$, BH $p<0.05$\n"
    "PASS*: HAR structure beats GJR; VIX marginal NULL (K1136 Fair Test 2) ─── "
    "PASS†: VaR/ES only (skew-t GAS), QLIKE NULL (K1135)"
)
fig.text(0.01, 0.01, legend_text, fontsize=7.8, color="#444444", va="bottom")

# ── Title ──────────────────────────────────────────────────────────────────────
ax.set_title(
    "Paper 4: Channel-Specific VIX Sufficiency — Model vs GJR-GARCH Baseline\n"
    r"$3 \times 4$ Out-of-Sample DM HLN $t$-statistics (OOS: 2020–2026)",
    fontsize=12, fontweight="bold", pad=14,
)

plt.tight_layout(rect=[0, 0.06, 1, 1])

# ── Save ───────────────────────────────────────────────────────────────────────
png_path = os.path.join(OUT_DIR, "paper4_cover_fig.png")
pdf_path = os.path.join(OUT_DIR, "paper4_cover_fig.pdf")
plt.savefig(png_path, dpi=300, bbox_inches="tight")
plt.savefig(pdf_path, bbox_inches="tight")
print(f"Saved: {png_path}")
print(f"Saved: {pdf_path}")

# ── Print summary for verification ────────────────────────────────────────────
print("\n=== DM t matrix (rows=Ch1/Ch2/Ch3, cols=Equity/Commodity/Bond/FX) ===")
for r, row_name in enumerate(["Ch1 HAR+VIX", "Ch2 MIDAS-X", "Ch3 GAS-t  "]):
    row_str = f"{row_name}: "
    for c, col_name in enumerate(["Equity  ", "Commodity", "Bond   ", "FX     "]):
        val = data[r, c]
        row_str += f"{col_name}={val:+7.3f}  " if not np.isnan(val) else f"{col_name}=   NaN    "
    print(row_str)
