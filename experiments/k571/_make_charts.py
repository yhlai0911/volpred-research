"""K571 article charts: half-life distribution + Sharpe vs Harvey + cross-OOS consistency."""
import json
import matplotlib.pyplot as plt
import matplotlib
import numpy as np
from pathlib import Path

matplotlib.rcParams['font.family'] = ['Heiti TC', 'Arial Unicode MS', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

HERE = Path(__file__).parent
RES = json.loads((HERE / "k571_vix_mean_reversion_speed_results.json").read_text())

# ─── Chart 1: half-life distribution + peak VIX scatter ───
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
events = RES["events"]
peaks = [e["peak_vix"] for e in events]
days = [e.get("days_to_20") for e in events if e.get("days_to_20") is not None]

# Add summary stats from full population
hl_mean = RES["reversion_statistics"]["half_life_mean"]
hl_med = RES["reversion_statistics"]["half_life_median"]

ax = axes[0]
# Approximate distribution illustration: use stats directly
hl_summary = {
    "mean": RES["reversion_statistics"]["half_life_mean"],
    "median": RES["reversion_statistics"]["half_life_median"],
    "std": RES["reversion_statistics"]["half_life_std"],
    "min": RES["reversion_statistics"]["half_life_min"],
    "max": RES["reversion_statistics"]["half_life_max"],
}
labels = ["min", "median", "mean", "+1σ", "max"]
vals = [hl_summary["min"], hl_summary["median"], hl_summary["mean"],
        hl_summary["mean"] + hl_summary["std"], hl_summary["max"]]
colors = ["#5fa8d3", "#3a7ca5", "#2f6690", "#d18b47", "#c1666b"]
ax.bar(labels, vals, color=colors, edgecolor="#16425b")
ax.set_ylabel("VIX 從尖峰回到 20 所需天數")
ax.set_title(f"半衰期分佈摘要（n={RES['methodology']['n_valid_events']} VIX>25 事件）")
for i, v in enumerate(vals):
    ax.text(i, v + 3, f"{v:.0f}d", ha="center", fontsize=9, color="#16425b")
ax.grid(axis="y", alpha=0.3)

ax = axes[1]
# Show R^2 of regression
coefs = RES["regression"]["coefficients"]
pvals = RES["regression"]["p_values"]
keys = ["peak_vix", "velocity", "spy_drawdown_pct"]
labels2 = ["Peak VIX", "Velocity", "SPY drawdown%"]
vals2 = [coefs[k] for k in keys]
colors2 = ["#2f6690" if pvals[k] < 0.05 else "#888" for k in keys]
ax.barh(labels2, vals2, color=colors2, edgecolor="#16425b")
ax.axvline(0, color="#333", lw=0.7)
ax.set_xlabel("迴歸係數（解釋變數 → days_to_20）")
ax.set_title(f"半衰期迴歸 (R²={RES['regression']['R2']:.3f})")
for i, (k, v) in enumerate(zip(keys, vals2)):
    p = pvals[k]
    txt = f"  {v:+.2f} (p={p:.3f})" if v >= 0 else f"{v:+.2f} (p={p:.3f})  "
    ha = "left" if v >= 0 else "right"
    ax.text(v, i, txt, va="center", ha=ha, fontsize=9, color="#16425b")
ax.grid(axis="x", alpha=0.3)

plt.tight_layout()
plt.savefig(HERE / "k571_half_life_overview.png", dpi=130, bbox_inches="tight")
plt.close()
print("saved k571_half_life_overview.png")

# ─── Chart 2: Strategy Sharpe + DM stats vs Harvey threshold ───
fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
strat = RES["strategy_results"]
dm = RES["dm_tests"]
order = ["baseline_12vix", "fast_reentry_14vix", "adaptive_peak", "regression_adaptive", "slow_reentry_10vix"]
disp = {
    "baseline_12vix": "Baseline\n12/VIX",
    "fast_reentry_14vix": "Fast re-entry\n(14/VIX)",
    "adaptive_peak": "Adaptive\n(peak)",
    "regression_adaptive": "Regression\nadaptive",
    "slow_reentry_10vix": "Slow re-entry\n(10/VIX)",
}
sharpes = [strat[k]["sharpe"] for k in order]
ax = axes[0]
colors = []
for k in order:
    if k == "baseline_12vix":
        colors.append("#888")
    elif k in dm and dm[k].get("harvey_significant"):
        colors.append("#2a9d8f")
    elif k in dm and dm[k].get("significant"):
        colors.append("#e9c46a")
    else:
        colors.append("#c1666b")
bars = ax.bar([disp[k] for k in order], sharpes, color=colors, edgecolor="#16425b")
ax.axhline(strat["baseline_12vix"]["sharpe"], color="#888", ls="--", lw=1, label="Baseline Sharpe")
ax.set_ylabel("樣本內 Sharpe（年化）")
ax.set_title("各策略 Sharpe — 相對 Baseline")
for b, s in zip(bars, sharpes):
    ax.text(b.get_x() + b.get_width()/2, s + 0.005, f"{s:.3f}", ha="center", fontsize=9)
ax.legend(loc="lower right", fontsize=8)
ax.grid(axis="y", alpha=0.3)
ax.set_ylim(0.20, 0.34)

ax = axes[1]
# DM stat with thresholds
non_base = ["fast_reentry_14vix", "adaptive_peak", "regression_adaptive", "slow_reentry_10vix"]
dm_stats = [dm[k]["dm_stat"] for k in non_base]
labels3 = [disp[k].replace("\n", " ") for k in non_base]
clrs = []
for k in non_base:
    if dm[k].get("harvey_significant"):
        clrs.append("#2a9d8f")
    elif dm[k].get("significant"):
        clrs.append("#e9c46a")
    else:
        clrs.append("#c1666b")
ax.barh(labels3, dm_stats, color=clrs, edgecolor="#16425b")
ax.axvline(1.96, color="#333", ls=":", lw=1, label="DM 5% 閾值 (±1.96)")
ax.axvline(-1.96, color="#333", ls=":", lw=1)
ax.axvline(2.78, color="#c1666b", ls="--", lw=1, label="Harvey 嚴格門檻 (~|t|>2.78)")
ax.axvline(-2.78, color="#c1666b", ls="--", lw=1)
ax.axvline(0, color="#000", lw=0.5)
ax.set_xlabel("DM 統計量 vs Baseline 12/VIX")
ax.set_title("DM-test：方向贏 ≠ 統計顯著")
ax.legend(loc="lower right", fontsize=8)
for i, (k, v) in enumerate(zip(non_base, dm_stats)):
    p = dm[k]["dm_pval"]
    ax.text(v + (0.05 if v >= 0 else -0.05), i, f" t={v:+.2f}, p={p:.3f}",
            va="center", ha="left" if v >= 0 else "right", fontsize=8)
ax.grid(axis="x", alpha=0.3)
ax.set_xlim(-3.5, 3.5)

plt.tight_layout()
plt.savefig(HERE / "k571_sharpe_vs_harvey.png", dpi=130, bbox_inches="tight")
plt.close()
print("saved k571_sharpe_vs_harvey.png")

# ─── Chart 3: Cross-OOS consistency ───
fig, ax = plt.subplots(figsize=(10, 4.4))
periods = RES["cross_oos"]
period_labels = [
    "OOS-1\n2012–2015",
    "OOS-2\n2018–2021",
    "OOS-3\n2023–2026",
]
strategies = ["baseline_12vix", "fast_reentry_14vix", "adaptive_peak", "regression_adaptive"]
disp_short = {
    "baseline_12vix": "Baseline 12/VIX",
    "fast_reentry_14vix": "Fast re-entry",
    "adaptive_peak": "Adaptive peak",
    "regression_adaptive": "Regression adaptive",
}
colors_ = {"baseline_12vix": "#888",
           "fast_reentry_14vix": "#2a9d8f",
           "adaptive_peak": "#e9c46a",
           "regression_adaptive": "#264653"}

x = np.arange(len(periods))
width = 0.20
for i, s in enumerate(strategies):
    vals = [p["results"][s]["sharpe"] for p in periods]
    ax.bar(x + (i - 1.5) * width, vals, width, label=disp_short[s],
           color=colors_[s], edgecolor="#222")
    for j, v in enumerate(vals):
        ax.text(x[j] + (i - 1.5) * width, v + 0.015, f"{v:.2f}",
                ha="center", fontsize=7.5)

ax.set_xticks(x)
ax.set_xticklabels(period_labels)
ax.set_ylabel("Out-of-sample Sharpe")
ax.set_title("跨 3 段 OOS 一致性 — 方向贏多次，仍未過 Harvey 嚴格檢定")
ax.legend(loc="upper left", fontsize=9, ncol=2)
ax.grid(axis="y", alpha=0.3)

# Annotate cross-OOS wins
wins = RES["cross_oos_wins"]
caption = (
    f"OOS 勝率（vs baseline）: fast_reentry {wins['fast_reentry_14vix']}/3 · "
    f"adaptive_peak {wins['adaptive_peak']}/3 · "
    f"regression_adaptive {wins['regression_adaptive']}/3 · "
    f"slow_reentry {wins['slow_reentry_10vix']}/3"
)
ax.text(0.5, -0.18, caption, transform=ax.transAxes, ha="center", fontsize=9, color="#16425b")

plt.tight_layout()
plt.savefig(HERE / "k571_cross_oos_consistency.png", dpi=130, bbox_inches="tight")
plt.close()
print("saved k571_cross_oos_consistency.png")
