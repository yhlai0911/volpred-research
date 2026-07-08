"""K1660 general-article chart — 兩面板：家族校準 + 尺度診斷。
數字全部硬對齊 experiments/k1660_mz_calibration_audit/*_results.json (family_summary + proxy_scale_diagnostic)。
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# CJK font
for cand in ["PingFang HK", "Heiti TC", "Arial Unicode MS"]:
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [cand]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

RES = Path(__file__).resolve().parents[3] / "experiments/k1660_mz_calibration_audit/k1660_mz_calibration_audit_results.json"
res = json.loads(RES.read_text())
fam = res["family_summary"]
prox = res["proxy_scale_diagnostic"]

# ---- Panel A data: 4 families ordered by well-calibrated share ----
order = ["GJR-GARCH", "GARCH(1,1)", "EGARCH", "CGARCH"]
ratios = [fam[f]["median_fc_over_r2_ratio"] for f in order]
n_files = [fam[f]["n_files"] for f in order]
well = [fam[f]["verdict_counts"].get("well-calibrated", 0) for f in order]
well_frac = [w / n * 100 for w, n in zip(well, n_files)]

fig, (axA, axB) = plt.subplots(1, 2, figsize=(12.2, 5.4))

# Panel A
colors_a = ["#2b8cbe", "#6bb6d6", "#a9cfe3", "#d4e6f1"]
bars = axA.bar(order, ratios, color=colors_a, edgecolor="#1b5c80", width=0.62)
axA.axhline(1.0, color="#c0392b", ls="--", lw=1.4)
axA.text(3.42, 1.003, "剛剛好 = 1.0", color="#c0392b", fontsize=10, ha="right", va="bottom")
axA.set_ylim(0.95, 1.20)
axA.set_ylabel("預測值 ÷ 實際值（中位數）", fontsize=11)
axA.set_title("四個模型家族：預測比實際高多少", fontsize=13, weight="bold", pad=12)
for b, r, n, wf in zip(bars, ratios, n_files, well_frac):
    axA.text(b.get_x() + b.get_width() / 2, r + 0.004, f"{r:.2f}", ha="center", fontsize=11, weight="bold")
    axA.text(b.get_x() + b.get_width() / 2, 0.962, f"{n} 檔\n合格 {wf:.0f}%", ha="center", fontsize=9, color="#34495e")
axA.tick_params(axis="x", labelsize=10.5)

# Panel B: scale diagnostic
labels = ["以 r²（正確尺度）衡量", "以 Parkinson（舊尺度）衡量"]
fc_ratio = [prox["median_fc_over_r2_ratio"], prox["median_fc_over_parkinson_ratio"]]
colors_b = ["#27ae60", "#e67e22"]
barsB = axB.bar(labels, fc_ratio, color=colors_b, edgecolor="#555", width=0.55)
axB.axhline(1.0, color="#c0392b", ls="--", lw=1.4)
axB.set_ylim(0, 2.0)
axB.set_ylabel("預測值 ÷ 實際值（中位數）", fontsize=11)
axB.set_title("換一把尺，結論差很多", fontsize=13, weight="bold", pad=12)
for b, v in zip(barsB, fc_ratio):
    over = (v - 1) * 100
    axB.text(b.get_x() + b.get_width() / 2, v + 0.03, f"{v:.2f}\n(高估 {over:.0f}%)", ha="center", fontsize=10.5, weight="bold")
axB.tick_params(axis="x", labelsize=10)

fig.suptitle("VolPred 預測庫自我體檢：84 檔波動率預測的校準審計（K1660）", fontsize=14.5, weight="bold", y=0.99)
fig.text(0.5, 0.005, "資料來源：VolPred K1660 MZ 校準審計 · 84 檔 OOS 預測 · 7 資產 · 2026-07", ha="center", fontsize=8.5, color="#888")
fig.tight_layout(rect=[0, 0.02, 1, 0.95])

OUT = Path(__file__).resolve().parent / "k1660_general_calibration.png"
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print("saved", OUT)
