"""K1686 第二張圖：三個規格下「真實落差 vs 假世界 95% 區間」。

資料全部綁定 k1686_contemporaneous_null_results.json，不硬編數字。
說故事：舊版(標錯一天) 真實值遠在假世界外 → 修正後主檢定 真實值落回假世界內(差點失守)
→ 存活規格 真實值再度落在假世界外。
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
res = json.loads((HERE / "k1686_contemporaneous_null_results.json").read_text())

# 找一個能顯示中文的字型
for cand in [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]:
    if Path(cand).exists():
        font_manager.fontManager.addfont(cand)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=cand).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

cmp = res["sar_decline_comparison"]
survive = res["codex_followup_gate"]["same_seed_null_comparison"]

specs = [
    ("舊版：把衝擊標在大跌隔天\n（時間對錯一天）", cmp["k897_lagged|A"]),
    ("修正後主檢定：時間對齊當天\n（事前登記的判準）", cmp["contemporaneous|A"]),
    ("存活規格：用前一日恐慌\n分組 × 當日衝擊", survive),
]

fig, ax = plt.subplots(figsize=(9, 5.2))
ypos = list(range(len(specs)))[::-1]

for y, (label, node) in zip(ypos, specs):
    lo, hi = node["sim_ci_95"]
    mean = node["sim_mean"]
    emp = node["empirical"]
    inside = node["in_95_ci"]
    p = node["p_value_monte_carlo"]
    # 假世界 95% 區間（灰帶）
    ax.plot([lo, hi], [y, y], color="#9aa0a6", lw=9, solid_capstyle="round",
            alpha=0.55, zorder=1)
    ax.plot(mean, y, "|", color="#5f6368", markersize=16, mew=2, zorder=2)
    # 真實落差（點）
    color = "#c5221f" if not inside else "#1a73e8"
    ax.plot(emp, y, "o", color=color, markersize=13, zorder=3,
            markeredgecolor="white", markeredgewidth=1.5)
    verdict = "落在區間外" if not inside else "落回區間內"
    dy = -30 if y == max(ypos) else (10 if inside else 12)  # 最上面一列標在點下方，避免壓到標題
    ax.annotate(f"真實 {emp:.2f}\n{verdict}，p={p:.3f}",
                (emp, y), textcoords="offset points", xytext=(12, dy),
                fontsize=10, color=color, fontweight="bold")

ax.axvline(0, color="#dadce0", lw=1, zorder=0)
ax.set_yticks(ypos)
ax.set_yticklabels([s[0] for s in specs], fontsize=10.5)
ax.set_xlabel("平靜→恐慌 的衝擊放大比落差（灰帶＝假世界 95% 區間，短豎線＝假世界平均）", fontsize=10.5)
ax.set_title("同一個問題，換三種問法：真實落差落在假世界裡面還是外面？", fontsize=13, fontweight="bold", pad=14)
ax.set_xlim(-1.0, 2.0)
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(length=0)
fig.tight_layout()

out = HERE / "k1686_empirical_vs_null.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print("saved", out)
