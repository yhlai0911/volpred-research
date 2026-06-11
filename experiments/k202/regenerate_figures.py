"""Regenerate K202 article figures with proper CJK fonts.

2026-06-11 incident: the original figures (btc_feature_correlations.png,
btc_feature_oos_r2.png) rendered all Chinese text as tofu boxes (□) because
matplotlib had no CJK font configured — caught by the boss on the live
article mile_872abdc3. This script is the durable regeneration path: data
straight from k202_btc_features_results.json, fonts set explicitly.
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# CJK font setup (macOS): PingFang → Heiti → Arial Unicode fallbacks
plt.rcParams["font.sans-serif"] = [
    "PingFang TC", "PingFang HK", "Heiti TC", "Arial Unicode MS", "sans-serif",
]
plt.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).parent
d = json.loads((HERE / "k202_btc_features_results.json").read_text())

ORDER = ["weekend_ratio", "btc_spy_corr", "skewness_66d", "kurtosis_66d",
         "vol_surprise", "range_ratio"]
XLABELS = ["Weekend/Weekday", "BTC-SPY corr", "Skewness", "Kurtosis",
           "Vol surprise", "Range ratio"]

# ── Fig 1: unconditional vs partial (controlling VIX) correlations ──
unc = d["unconditional_correlations"]
par = d["partial_correlations_controlling_vix"]
keys = [k for k in ORDER if k in unc and k in par]
labels = [XLABELS[ORDER.index(k)] for k in keys]
u_vals = [unc[k]["pearson_r"] for k in keys]
p_vals = [par[k]["partial_r"] for k in keys]

fig, ax = plt.subplots(figsize=(14, 7))
x = range(len(keys))
w = 0.38
ax.bar([i - w / 2 for i in x], u_vals, w, label="無條件相關", color="#94a3b8")
ax.bar([i + w / 2 for i in x], p_vals, w, label="控制 VIX 後", color="#2563eb")
ax.axhline(0, color="black", lw=1.2)
ax.set_xticks(list(x))
ax.set_xticklabels(labels, rotation=15)
ax.set_ylabel("相關係數")
ax.set_title("六個 BTC 特徵與未來波動率的相關性（無條件 vs 控制 VIX 後）")
ax.legend()
ax.grid(axis="y", alpha=0.25)
fig.tight_layout()
fig.savefig(HERE / "btc_feature_correlations.png", dpi=160)
plt.close(fig)

# ── Fig 2: OOS predictive R² ──
oos = d["oos_predictive_regression"]
oos_keys = ["vix_only", "rv_lag_only"] + [k for k in ORDER if k in oos]
oos_labels = {"vix_only": "只用 VIX", "rv_lag_only": "只用落後 RV"}
labels2 = [oos_labels.get(k, XLABELS[ORDER.index(k)] if k in ORDER else k) for k in oos_keys]
r2 = [oos[k]["r2"] for k in oos_keys]

fig, ax = plt.subplots(figsize=(14, 7))
colors = ["#16a34a" if v == max(r2) else "#94a3b8" for v in r2]
ax.bar(range(len(oos_keys)), r2, color=colors)
ax.axhline(0, color="black", lw=1.2)
ax.set_xticks(range(len(oos_keys)))
ax.set_xticklabels(labels2, rotation=15)
ax.set_ylabel("樣本外 R²")
ax.set_title("樣本外預測 R²：BTC 自身特徵 vs VIX 基準（全數為負 = 都比天真預測差）")
ax.grid(axis="y", alpha=0.25)
fig.tight_layout()
fig.savefig(HERE / "btc_feature_oos_r2.png", dpi=160)
plt.close(fig)

print("regenerated 2 figures with CJK fonts")
