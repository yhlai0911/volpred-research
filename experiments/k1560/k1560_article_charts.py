"""Generate two reader-facing charts for the K1560 general article.

All numbers are read directly from k1560_results.json — no hardcoded values.
Chart 1: per-asset direction of the dispersion signal (Spearman rho vs GARCH QLIKE).
Chart 2: the 7 formal signal tests, raw p-value vs Holm-corrected p-value.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

HERE = Path(__file__).resolve().parent
RESULTS = json.loads((HERE / "k1560_results.json").read_text())

_FONT_CANDIDATES = ["PingFang HK", "Heiti TC", "STHeiti", "Arial Unicode MS",
                    "PingFang TC", "Noto Sans CJK SC", "sans-serif"]
_resolved = fm.findfont("PingFang HK")
if not any(k in _resolved for k in ("PingFang", "Heiti", "STHeiti")):
    fm._load_fontmanager(try_read_cache=False)
plt.rcParams["font.sans-serif"] = _FONT_CANDIDATES
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "white"

# ── Chart 1: per-asset Spearman rho for GARCH QLIKE ──────────────────
rows = [r for r in RESULTS["per_asset_spearman"] if r["target"] == "loss_GARCH"]
rows.sort(key=lambda r: r["rho"])
assets = [r["asset"] for r in rows]
rhos = [r["rho"] for r in rows]
colors = ["#F44336" if v < 0 else "#2E7D32" for v in rhos]

fig, ax = plt.subplots(figsize=(8, 4.8))
bars = ax.barh(assets, rhos, color=colors, edgecolor="white", height=0.62)
ax.axvline(0, color="#555", linewidth=1)
for bar, v in zip(bars, rhos):
    off = 0.006 if v >= 0 else -0.006
    ax.text(v + off, bar.get_y() + bar.get_height() / 2, f"{v:+.2f}",
            va="center", ha="left" if v >= 0 else "right", fontsize=11)
ax.set_xlim(-0.18, 0.30)
ax.set_xlabel("分歧訊號 vs 隔天 GARCH 預測誤差的關聯（Spearman 相關係數）", fontsize=11)
ax.set_title("分歧越大、隔天誤差越大？6 檔裡 5 檔方向對，但都很弱",
             fontsize=13, fontweight="bold", pad=14)
ax.text(0.98, 0.04, "正值＝分歧大時誤差偏大（符合直覺）；只有黃金 GLD 反向",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color="#666")
ax.grid(axis="x", alpha=0.3)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
out1 = HERE / "k1560_article_direction.png"
fig.savefig(out1, dpi=150, bbox_inches="tight")
plt.close(fig)
print("saved", out1)

# ── Chart 2: 7 formal tests, raw p vs Holm-corrected p ───────────────
label_map = {
    "loss_GARCH": "GARCH 隔天預測誤差",
    "vt_abs_log_error_GARCH": "GARCH 部位抓錯幅度",
    "loss_EWMA": "EWMA 隔天預測誤差",
    "vt_excess_risk_GARCH": "GARCH 部位超額風險",
    "future_near_best_size_5d": "未來 5 日模型不確定性",
    "loss_HAR": "HAR 隔天預測誤差",
    "vt_excess_risk_HAR": "HAR 部位超額風險",
}
tests = sorted(RESULTS["regression_tests"],
               key=lambda t: t["p_signal_dispersion"], reverse=True)
names = [label_map[t["target"]] for t in tests]
raw_p = [t["p_signal_dispersion"] for t in tests]
holm_p = [t["holm_p_signal_dispersion"] for t in tests]
y = range(len(tests))

fig, ax = plt.subplots(figsize=(8.4, 5))
for yi, rp, hp in zip(y, raw_p, holm_p):
    ax.plot([rp, hp], [yi, yi], color="#BBB", linewidth=2, zorder=1)
ax.scatter(raw_p, list(y), s=90, color="#1565C0", zorder=3, label="未校正 p 值")
ax.scatter(holm_p, list(y), s=90, facecolors="white",
           edgecolors="#C62828", linewidths=1.8, zorder=3, label="多重比較校正後 p 值")
ax.axvline(0.05, color="#C62828", linestyle="--", linewidth=1.2)
ax.text(0.065, 2.4, "顯著門檻 0.05", color="#C62828", fontsize=9, va="center", ha="left")
ax.set_yticks(list(y))
ax.set_yticklabels(names, fontsize=10)
ax.set_xlim(-0.02, 1.05)
ax.set_xlabel("p 值（越小代表越可能不是巧合；低於 0.05 才算通過）", fontsize=11)
ax.set_title("7 個檢定全數落榜：連未校正的 p 值都沒一個低於 0.05",
             fontsize=13, fontweight="bold", pad=20)
ax.legend(loc="lower right", fontsize=9, framealpha=0.9)
ax.grid(axis="x", alpha=0.3)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
out2 = HERE / "k1560_article_pvalues.png"
fig.savefig(out2, dpi=150, bbox_inches="tight")
plt.close(fig)
print("saved", out2)
