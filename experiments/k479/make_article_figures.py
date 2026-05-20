"""K479 article figures: QLIKE comparison + DM p-values."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).parent
res = json.loads((ROOT / "k479_wavelet_vol_results.json").read_text())

plt.rcParams.update({
    "font.family": ["Heiti TC", "PingFang TC", "Arial Unicode MS", "DejaVu Sans"],
    "axes.unicode_minus": False,
})

# Figure 1: QLIKE_log comparison (static vs rolling), exclude blow-up wavelet_har
models = ["rv21_baseline", "har", "har_plus_wavelet", "low_freq_only", "high_freq_only"]
labels = ["RV21 基準", "HAR (標準)", "HAR + 小波 A4", "僅低頻 (A4)", "僅高頻 (D1+D2)"]

static_q = [res["results_static"][m]["qlike_log"] for m in models]
rolling_q = [res["results_rolling"][m]["qlike_log"] for m in models]

x = np.arange(len(models))
w = 0.38
fig, ax = plt.subplots(figsize=(9, 5.2))
b1 = ax.bar(x - w/2, static_q, w, label="Static (in-sample)", color="#3b6db5")
b2 = ax.bar(x + w/2, rolling_q, w, label="Rolling (季度滾動樣本外)", color="#d96a4a")
ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=15, ha="right")
ax.set_ylabel("QLIKE (log scale, 越低越好)")
ax.set_title("K479：六種模型 QLIKE 比較 (SPY, OOS 2023-2025)")
ax.axhline(0, color="gray", linewidth=0.5)
ax.legend()
# annotate
for bars in (b1, b2):
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h:.2f}", xy=(bar.get_x()+bar.get_width()/2, h),
                    xytext=(0, -12 if h < 0 else 4), textcoords="offset points",
                    ha="center", fontsize=8)
ax.text(0.02, 0.02,
        "註：Wavelet-HAR (D1-D4+A4) 因 ill-conditioned 在 OOS 爆炸 (QLIKE>3700)，已從本圖剔除以保留可讀性。",
        transform=ax.transAxes, fontsize=8, color="gray")
fig.tight_layout()
out1 = ROOT / "k479_qlike_compare.png"
fig.savefig(out1, dpi=140)
print(f"saved: {out1}")
plt.close(fig)

# Figure 2: DM test p-values (HAR vs each wavelet variant), static + rolling
pairs = [
    ("har_vs_wavelet_har", "HAR vs Wavelet-HAR"),
    ("har_vs_har_plus_wavelet", "HAR vs HAR+小波 A4"),
    ("har_vs_low_freq_only", "HAR vs 僅低頻"),
    ("har_vs_high_freq_only", "HAR vs 僅高頻"),
]
p_static = [res["dm_tests_static"][k]["p_value"] for k, _ in pairs]
p_rolling = [res["dm_tests_rolling"][k]["p_value"] for k, _ in pairs]
labels2 = [lbl for _, lbl in pairs]

x = np.arange(len(pairs))
fig, ax = plt.subplots(figsize=(9, 5.2))
b1 = ax.bar(x - w/2, p_static, w, label="Static", color="#3b6db5")
b2 = ax.bar(x + w/2, p_rolling, w, label="Rolling", color="#d96a4a")
ax.axhline(0.05, color="red", linestyle="--", linewidth=1, label="顯著門檻 p=0.05")
ax.set_xticks(x)
ax.set_xticklabels(labels2, rotation=12, ha="right")
ax.set_ylabel("Diebold–Mariano p-value")
ax.set_title("K479：DM 檢定 p-value（HAR 對各小波變體）")
ax.legend(loc="upper left")
for bars in (b1, b2):
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h:.3f}", xy=(bar.get_x()+bar.get_width()/2, h),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=8)
ax.set_ylim(0, max(max(p_static), max(p_rolling)) * 1.15 + 0.02)
fig.tight_layout()
out2 = ROOT / "k479_dm_pvalues.png"
fig.savefig(out2, dpi=140)
print(f"saved: {out2}")
plt.close(fig)

# Figure 3: in-sample R² comparison
r2 = res["in_sample_r2"]
models3 = ["rv21_baseline", "har", "har_plus_wavelet", "wavelet_har", "low_freq_only", "high_freq_only"]
labels3 = ["RV21 基準", "HAR", "HAR+小波 A4", "Wavelet-HAR\n(D1-D4+A4)", "僅低頻 A4", "僅高頻 D1+D2"]
vals = [r2[m] for m in models3]
colors = ["#888", "#3b6db5", "#2a9d8f", "#e76f51", "#bbbbcc", "#bbbbcc"]
fig, ax = plt.subplots(figsize=(9, 4.8))
bars = ax.bar(labels3, vals, color=colors)
ax.set_ylabel("In-sample R²")
ax.set_title("K479：樣本內 R²（六模型）")
for bar, v in zip(bars, vals):
    ax.annotate(f"{v:.3f}", xy=(bar.get_x()+bar.get_width()/2, v),
                xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9)
ax.text(0.02, 0.95,
        "HAR 與 HAR+小波 R² 幾乎相同（0.236 vs 0.236）；純小波分解單獨用反而更差。",
        transform=ax.transAxes, fontsize=8.5, color="gray", verticalalignment="top")
fig.tight_layout()
out3 = ROOT / "k479_r2_compare.png"
fig.savefig(out3, dpi=140)
print(f"saved: {out3}")
plt.close(fig)
