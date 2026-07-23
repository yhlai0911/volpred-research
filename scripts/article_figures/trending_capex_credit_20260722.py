"""Figures for trending_repost 2026-07-22 — AI capex funding shift to debt.

Fig 1: capex vs operating cash flow (META/MSFT/GOOGL/AMZN) + total debt
Fig 2: tech realized vol vs Baa credit spread + SMH-HYG rolling correlation
"""
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style(dpi=150)

OUTDIR = Path("/Users/yhlai0911/volpred-research/storage/figures")
OUTDIR.mkdir(parents=True, exist_ok=True)
EV = json.loads(Path("/tmp/capex_credit_evidence.json").read_text())

# ---------------- Figure 1 ----------------
q = pd.read_csv("/tmp/capex_quarters.csv", index_col=0, parse_dates=True)
debt = pd.read_csv("/tmp/total_debt.csv", index_col=0, parse_dates=True)["total_debt_bn"]
labels = [f"{d.year}Q{(d.month - 1) // 3 + 1}" for d in q.index]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2))

x = range(len(q))
w = 0.38
ax1.bar([i - w / 2 for i in x], q["ocf_sum_bn"], w, label="營運現金流", color="#4C78A8")
ax1.bar([i + w / 2 for i in x], q["capex_sum_bn"], w, label="資本支出", color="#E45756")
ax1.set_xticks(list(x))
ax1.set_xticklabels(labels)
ax1.set_ylabel("十億美元")
ax1.set_title("四巨頭單季資本支出 vs 營運現金流", fontsize=12, fontweight="bold")
ax1.legend(loc="upper left", fontsize=9)
ax1.grid(axis="y", alpha=0.3)

ax1b = ax1.twinx()
ax1b.plot(list(x), q["capex_over_ocf"] * 100, "o-", color="#333333", lw=2, label="資本支出/營運現金流")
ax1b.set_ylabel("資本支出佔營運現金流 (%)")
ax1b.set_ylim(50, 95)
for i, v in enumerate(q["capex_over_ocf"] * 100):
    ax1b.annotate(f"{v:.0f}%", (i, v), textcoords="offset points", xytext=(0, 8),
                  ha="center", fontsize=9, color="#333333")

ax2.bar(list(x), debt.reindex(q.index).values, color="#72B7B2")
ax2.set_xticks(list(x))
ax2.set_xticklabels(labels)
ax2.set_ylabel("十億美元")
ax2.set_title("四巨頭合計總負債", fontsize=12, fontweight="bold")
ax2.grid(axis="y", alpha=0.3)
for i, v in enumerate(debt.reindex(q.index).values):
    ax2.annotate(f"{v:.0f}", (i, v), textcoords="offset points", xytext=(0, 4),
                 ha="center", fontsize=9)

fig.suptitle("META / MSFT / GOOGL / AMZN 合計（資料：各公司 10-Q 現金流量表與資產負債表）",
             fontsize=10, y=0.02, color="#666666")
fig.tight_layout(rect=[0, 0.04, 1, 1])
p1 = OUTDIR / "trending_20260722_capex_funding_shift.png"
fig.savefig(p1, bbox_inches="tight")
print("saved", p1)

# ---------------- Figure 2 ----------------
rv = pd.read_csv("/tmp/tech_rv.csv", index_col=0, parse_dates=True)["tech_rv"]
ig = pd.read_csv("/tmp/ig_oas.csv", index_col=0, parse_dates=True)["ig_oas"]
roll = pd.read_csv("/tmp/roll_SMH_HYG.csv", index_col=0, parse_dates=True)["corr"]

fig, (axa, axb) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

axa.plot(rv.index, rv, color="#E45756", lw=1.1, label="四巨頭 21 日已實現波動率（左軸）")
axa.axhline(EV["tech_rv"]["median_full"], color="#E45756", ls=":", lw=1,
            label=f"波動率中位數 {EV['tech_rv']['median_full']:.1f}%")
axa.set_ylabel("年化波動率 (%)", color="#E45756")
axa.tick_params(axis="y", labelcolor="#E45756")
axa.set_title("科技股波動率高於常態，信用利差卻壓在十年低檔", fontsize=13, fontweight="bold")

axab = axa.twinx()
axab.plot(ig.index, ig, color="#4C78A8", lw=1.3, label="Baa 公司債 - 10 年公債利差（右軸）")
axab.axhline(EV["credit_levels"]["baa10y_median_2015_2026"], color="#4C78A8", ls=":", lw=1,
             label=f"利差中位數 {EV['credit_levels']['baa10y_median_2015_2026']:.2f}%")
axab.set_ylabel("信用利差 (百分點)", color="#4C78A8")
axab.tick_params(axis="y", labelcolor="#4C78A8")

h1, l1 = axa.get_legend_handles_labels()
h2, l2 = axab.get_legend_handles_labels()
axa.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9, framealpha=0.9)
axa.grid(alpha=0.25)

axb.plot(roll.index, roll, color="#54A24B", lw=1.2)
split = pd.Timestamp("2023-07-01")
axb.axvline(split, color="#888888", ls="--", lw=1)
axb.annotate("2023-07 起：AI 資本支出加速期", (split, roll.max() * 0.97),
             xytext=(10, 0), textcoords="offset points", fontsize=9, color="#555555")
e = EV["smh_credit_corr"]["HYG"]
axb.axhline(e["fullperiod_corr_early"], xmax=0.62, color="#54A24B", ls=":", lw=1.2)
axb.axhline(e["fullperiod_corr_recent"], xmin=0.62, color="#54A24B", ls=":", lw=1.2)
axb.annotate(f"前期 {e['fullperiod_corr_early']:.3f}", (rv.index[300], e["fullperiod_corr_early"]),
             xytext=(0, 8), textcoords="offset points", fontsize=9, color="#3B7A34")
axb.annotate(f"近期 {e['fullperiod_corr_recent']:.3f}", (rv.index[-350], e["fullperiod_corr_recent"]),
             xytext=(0, -16), textcoords="offset points", fontsize=9, color="#3B7A34")
axb.set_ylabel("SMH 與 HYG 日報酬\n120 日滾動相關係數")
axb.set_xlabel("資料：yfinance（SMH / HYG / META / MSFT / GOOGL / AMZN）、FRED BAA10Y")
axb.grid(alpha=0.25)
axb.set_title(f"半導體與高收益債的連動反而下降（Fisher z = {e['fisher_z']:.2f}，p = {e['p_value']:.1e}）",
              fontsize=11)

fig.tight_layout()
p2 = OUTDIR / "trending_20260722_vol_credit_divergence.png"
fig.savefig(p2, bbox_inches="tight")
print("saved", p2)
