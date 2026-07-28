import json, csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.family"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

BASE = Path("/Users/yhlai0911/volpred-research/experiments/k1366")
OUT = Path("/Users/yhlai0911/volpred-research/storage/drafts/assets")
OUT.mkdir(parents=True, exist_ok=True)

res = json.loads((BASE / "K1366_results.json").read_text())
tmpl = list(csv.DictReader(open(BASE / "data/K1366_response_templates.csv")))
bands = list(csv.DictReader(open(BASE / "data/placebo_bands_by_horizon.csv")))

LABEL = {
    "2018Q4_equity_credit": "2018 年 10 月 股債信用賣壓",
    "2020_covid_liquidity": "2020 年 3 月 疫情流動性崩盤",
    "2022_rate_shock": "2022 年 6 月 利率通膨重定價",
    "2025_tariff_shock": "2025 年 4 月 關稅衝擊",
}
COLOR = {
    "2018Q4_equity_credit": "#1f6f78",
    "2020_covid_liquidity": "#b3352c",
    "2022_rate_shock": "#d98b1f",
    "2025_tariff_shock": "#6a4c93",
}
ORDER = ["2018Q4_equity_credit", "2020_covid_liquidity", "2022_rate_shock", "2025_tariff_shock"]

def path_of(ev, col):
    rows = [r for r in tmpl if r["event"] == ev]
    rows.sort(key=lambda r: int(r["horizon"]))
    return [int(r["horizon"]) for r in rows], [float(r[col]) for r in rows]

bh = [int(b["horizon"]) for b in bands]
p05 = [float(b["total_variance_lift_p05"]) for b in bands]
p95 = [float(b["total_variance_lift_p95"]) for b in bands]
p50 = [float(b["total_variance_lift_p50"]) for b in bands]
c95 = [float(b["avg_abs_corr_delta_p95"]) for b in bands]

# ---- Figure 1: total variance response ----
fig, ax = plt.subplots(figsize=(10.5, 6))
ax.fill_between(bh, p05, p95, color="#c8cdd6", alpha=.55, label="平常日子的正常範圍（隨機抽 1000 次的中間 90%）")
ax.plot(bh, p50, color="#6b7280", lw=1.4, label="平常日子的中位數")
for ev in ORDER:
    h, y = path_of(ev, "total_variance_lift")
    ax.plot(h, y, lw=2.2, color=COLOR[ev], label=LABEL[ev])
ax.axhline(0, color="#111", lw=.9)
ax.set_xlabel("事件後經過的交易日")
ax.set_ylabel("五資產總波動相對衝擊前的倍增幅度")
ax.set_title("大事件之後，市場總波動比事發前高多少？", fontsize=15, pad=12)
ax.legend(fontsize=9.5, loc="upper right", framealpha=.92)
ax.grid(alpha=.25)
ax.set_xlim(0, 60)
fig.tight_layout()
f1 = OUT / "k1366_general_variance_response.png"
fig.savefig(f1, dpi=150); plt.close(fig)

# ---- Figure 2: correlation response vs placebo 95 ----
fig, ax = plt.subplots(figsize=(10.5, 6))
ax.plot(bh, c95, color="#6b7280", ls="--", lw=2.0, label="平常日子同一天數的第 95 百分位（單日參考線）")
for ev in ORDER:
    h, y = path_of(ev, "avg_abs_corr_delta")
    ax.plot(h, y, lw=2.0, color=COLOR[ev], label=LABEL[ev])
ax.set_xlabel("事件後經過的交易日")
ax.set_ylabel("五資產之間相關性的平均變動幅度")
ax.set_title("危機後資產「一起垮」的程度：最高點都落在隨機日子的常見範圍內", fontsize=15, pad=12)
ax.legend(fontsize=9.5, loc="lower right", framealpha=.92)
ax.grid(alpha=.25)
ax.set_xlim(0, 60)
fig.tight_layout()
f2 = OUT / "k1366_general_correlation_response.png"
fig.savefig(f2, dpi=150); plt.close(fig)

# ---- Figure 3: per-asset peak vol lift ----
TICK = ["SPY", "TLT", "UUP", "GLD", "HYG"]
TICK_ZH = ["美股\nSPY", "長天期公債\nTLT", "美元\nUUP", "黃金\nGLD", "高收益債\nHYG"]
mat = np.array([[res_ev["peak_asset_vol_lifts"][t] for t in TICK]
                for res_ev in [e for ev in ORDER for e in res["events"] if e["event"] == ev]])
fig, ax = plt.subplots(figsize=(10.5, 5.2))
im = ax.imshow(mat, cmap="YlOrRd", aspect="auto", vmin=0, vmax=4)
ax.set_xticks(range(5)); ax.set_xticklabels(TICK_ZH, fontsize=10)
ax.set_yticks(range(4)); ax.set_yticklabels([LABEL[e] for e in ORDER], fontsize=10)
for i in range(4):
    for j in range(5):
        ax.text(j, i, f"+{mat[i, j]*100:.0f}%", ha="center", va="center",
                fontsize=11, color="#111" if mat[i, j] < 2.4 else "white")
ax.set_title("同一場衝擊，每個資產的波動各自漲了多少（各事件的最大值）", fontsize=15, pad=12)
cb = fig.colorbar(im, ax=ax); cb.set_label("波動上升倍數", fontsize=10)
fig.tight_layout()
f3 = OUT / "k1366_general_asset_vol_lifts.png"
fig.savefig(f3, dpi=150); plt.close(fig)

for f in (f1, f2, f3):
    print("wrote", f, f.stat().st_size)
