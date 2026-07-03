"""Generate 3 real charts for the summer-vol predictive article."""
import numpy as np
import pandas as pd
import yfinance as yf
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from scipy import stats

# CJK font
for fp in ["/System/Library/Fonts/PingFang.ttc",
           "/System/Library/Fonts/STHeiti Medium.ttc",
           "/System/Library/Fonts/Hiragino Sans GB.ttc"]:
    try:
        font_manager.fontManager.addfont(fp)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

D = "experiments/event_article_summer_vol_predictive_20260704"
res = json.load(open(f"{D}/results.json"))

def _close(df):
    c = df["Close"]
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    return c.dropna()

vix = _close(yf.download("^VIX", start="2005-01-01", end="2026-07-04", progress=False, auto_adjust=False))
vix.index = pd.to_datetime(vix.index)

NAVY = "#1b3a5b"; RED = "#c0392b"; GREY = "#95a5a6"; GREEN = "#27ae60"

# ---- Chart 1: monthly mean VIX ----
fig, ax = plt.subplots(figsize=(8, 4.2))
months = list(range(1, 13))
vals = [res["monthly_mean_vix"][m if isinstance(m, str) else str(m)] if str(m) in res["monthly_mean_vix"] else res["monthly_mean_vix"][m] for m in months]
vals = [res["monthly_mean_vix"][str(m)] if str(m) in res["monthly_mean_vix"] else res["monthly_mean_vix"][m] for m in months]
colors = [GREEN if m == 7 else (RED if m == 10 else NAVY) for m in months]
ax.bar([f"{m}月" for m in months], vals, color=colors)
ax.axhline(np.mean(vals), color=GREY, ls="--", lw=1, label=f"全年均值 {np.mean(vals):.1f}")
ax.set_ylabel("平均 VIX")
ax.set_title("VIX 月均值（2005–2026）：7 月最低、10 月最高", fontsize=12, fontweight="bold")
ax.set_ylim(15, 22)
for i, (m, v) in enumerate(zip(months, vals)):
    if m in (7, 10):
        ax.text(i, v + 0.1, f"{v:.1f}", ha="center", fontsize=9, fontweight="bold")
ax.legend(fontsize=9)
plt.tight_layout()
plt.savefig(f"{D}/fig1_monthly_vix.png", dpi=130)
plt.close()

# ---- Chart 2: scatter summer vs autumn VIX + OLS + 2024 highlight ----
def season_mean(series, mo):
    d = series[series.index.month.isin(mo)]
    return d.groupby(d.index.year).mean()

summer = season_mean(vix, [6, 7])
autumn = season_mean(vix, [9, 10])
yrs = sorted(set(summer.index) & set(autumn.index))
s = np.array([summer[y] for y in yrs]); a = np.array([autumn[y] for y in yrs])
slope, intercept, r, p, se = stats.linregress(s, a)

fig, ax = plt.subplots(figsize=(7.6, 5.6))
# shade "calm summer" zone (summer VIX < 15)
ax.axvspan(6, 15, color=GREEN, alpha=0.07, zorder=0)
ax.scatter(s, a, color=NAVY, s=55, zorder=3, alpha=0.85)
xline = np.linspace(s.min(), s.max(), 50)
ax.plot(xline, intercept + slope * xline, color=RED, lw=2,
        label=f"OLS 斜率 +{slope:.2f}  r={r:.2f} (p={p:.3f})")
lim_lo = min(s.min(), a.min()) - 1; lim_hi = max(s.max(), a.max()) + 1
ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi], color=GREY, ls=":", lw=1, label="45° 持平線")
# annotate the true "stormy autumn" outliers — both came from ALREADY-nervous summers
for yr in (2008, 2011):
    i = yrs.index(yr)
    ax.scatter([s[i]], [a[i]], color=RED, s=110, zorder=4, edgecolor="black")
    ax.annotate(f"{yr}", (s[i], a[i]), xytext=(s[i] - 2.5, a[i] + 0.5),
                fontsize=10, color=RED, fontweight="bold")
# calm-summer zone label (dynamically find the worst autumn among genuinely-calm summers)
_calm = [(a[i], yrs[i]) for i, ss in enumerate(s) if ss < 15]
calm_max_autumn, calm_max_year = max(_calm)
ax.text(6.4, 42, "夏季 VIX<15（真正平靜）：\n21 年來秋季從未失控\n（最高僅 %d 的 %.1f）" % (calm_max_year, calm_max_autumn),
        fontsize=9, color=GREEN, fontweight="bold", va="top")
ax.set_xlabel("夏季（6–7 月）平均 VIX")
ax.set_ylabel("同年秋季（9–10 月）平均 VIX")
ax.set_title("平靜的夏天，接的是平靜的秋天——秋季風暴來自「本已緊張」的夏季",
             fontsize=11, fontweight="bold")
ax.legend(fontsize=9, loc="lower right")
plt.tight_layout()
plt.savefig(f"{D}/fig2_summer_autumn_scatter.png", dpi=130)
plt.close()

# ---- Chart 3: annual max VIX spike month distribution ----
counts = res["annual_max_vix_spike_month_counts"]
fig, ax = plt.subplots(figsize=(8, 4.2))
mo_all = list(range(1, 13))
cvals = [counts.get(str(m), counts.get(m, 0)) for m in mo_all]
colors3 = [RED if m in (8, 9, 10) else NAVY for m in mo_all]
ax.bar([f"{m}月" for m in mo_all], cvals, color=colors3)
ax.set_ylabel("該月出現年度最大 VIX 尖峰的年數")
ax.set_title(f"年度最大恐慌尖峰落在哪個月（22 年）：秋季並不特別（8–10月占 {res['annual_max_vix_spike_aug_oct_share']*100:.0f}%＜均勻25%）",
             fontsize=10.5, fontweight="bold")
plt.tight_layout()
plt.savefig(f"{D}/fig3_spike_month.png", dpi=130)
plt.close()

print("charts written: fig1_monthly_vix.png, fig2_summer_autumn_scatter.png, fig3_spike_month.png")
print(f"OLS check: slope={slope:.3f} r={r:.3f} p={p:.4f} n={len(yrs)}")
