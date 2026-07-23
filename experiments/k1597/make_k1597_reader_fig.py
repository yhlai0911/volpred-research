#!/usr/bin/env python3
"""Reader-facing figure for K1597 (zh-Hant). All numbers bind to k1597_results.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style(dpi=160)

RES = json.loads((ROOT / "experiments/k1597/k1597_results.json").read_text())
ti = RES["diagnostics"]["tail_index"]
race = RES["oos_model_race"]
qlike = race["qlike"]
dm = race["dm_tests"]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.4))

# ── Panel A: tail index vs the alpha < 2 stable region ────────────────────
labels = ["Hill\n最極端 10%", "Hill\n最極端 5%", "Hill\n右尾 10%", "log-log\n最極端 20%"]
vals = [
    ti["hill_abs_q90"]["alpha"],
    ti["hill_abs_q95"]["alpha"],
    ti["hill_right_q90"]["alpha"],
    ti["loglog_survival_abs_q80"]["alpha"],
]
ax1.axhspan(0, 2, color="#d9534f", alpha=0.12)
ax1.axhline(2, color="#d9534f", ls="--", lw=1.6)
bars = ax1.bar(labels, vals, color="#3d6b9c", width=0.6)
for b, v in zip(bars, vals):
    ax1.text(b.get_x() + b.get_width() / 2, v + 0.09, f"{v:.2f}", ha="center", fontsize=11)
ax1.annotate("", xy=(-0.44, 2.02), xytext=(-0.44, 4.72),
             arrowprops=dict(arrowstyle="->", color="#a03030", lw=1.2))
ax1.text(-0.44, 5.28, "紅線以下才是 alpha < 2 的無窮方差區", fontsize=10.5,
         color="#a03030", va="top", ha="left")
ax1.set_ylim(0, 5.6)
ax1.set_ylabel("尾部指數 alpha（越小＝尾巴越厚）")
ax1.set_title("台指期日盤 RV 的尾巴有多厚？四種算法都落在 2 以上", fontsize=12.5, pad=10)
ax1.tick_params(axis="x", labelsize=10)

# ── Panel B: OOS mean QLIKE race ──────────────────────────────────────────
order = ["HAR", "HARQ", "StableTailHAR", "CodiffAR", "LFSM_lite"]
names = ["HAR\n（基準）", "HARQ\n（基準）", "StableTailHAR\n（新特徵）",
         "CodiffAR\n（新特徵）", "LFSM_lite\n（新特徵）"]
vals2 = [qlike[m] for m in order]
colors = ["#8d99a6", "#8d99a6", "#3d6b9c", "#3d6b9c", "#3d6b9c"]
bars2 = ax2.bar(names, vals2, color=colors, width=0.62)
for b, v in zip(bars2, vals2):
    ax2.text(b.get_x() + b.get_width() / 2, v + 0.0035, f"{v:.4f}", ha="center", fontsize=10.5)

t_cod = dm["CodiffAR_vs_HAR"]["t_stat"]
p_cod = dm["CodiffAR_vs_HAR"]["p_value"]
ax2.axhline(qlike["HAR"], color="#8d99a6", ls=":", lw=1.4)
ax2.annotate(
    f"最低的 CodiffAR 對上 HAR：\nt = {t_cod:.3f}，p = {p_cod:.3f}\nHarvey 門檻 |t| > 3 沒過",
    xy=(3, qlike["CodiffAR"]), xytext=(2.3, 0.108),
    fontsize=10.5, color="#333333",
    arrowprops=dict(arrowstyle="->", color="#666666", lw=1.2),
)
ax2.set_ylim(0, 0.30)
ax2.set_ylabel("樣本外平均 QLIKE（越低＝預測越準）")
ax2.set_title(f"2020-2021 共 {race['n_oos']} 個交易日的次日 RV 預測比賽", fontsize=12.5, pad=10)
ax2.tick_params(axis="x", labelsize=9.5)

fig.suptitle("K1597：診斷說它厚尾又粗糙，預測卻沒有變準", fontsize=15, y=0.985)
fig.text(0.5, 0.012, "資料：TAIFEX TX 期貨日盤 5 分鐘 bar，2017-05-16 至 2021-12-30，1,138 個交易日"
                     "　|　來源：experiments/k1597/k1597_results.json",
         ha="center", fontsize=9.5, color="#666666")
fig.tight_layout(rect=(0, 0.035, 1, 0.955))

out = ROOT / "storage/assets/k1597_tail_vs_forecast_zh.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, bbox_inches="tight")
print(f"wrote {out}")
