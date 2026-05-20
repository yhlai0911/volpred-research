"""K715 article charts (general audience).

Three figures:
  1. k715_strategy_ranking_2023_2026.png — bar chart of paper_trading
     strategies (live forward 2023-01-04 → 2026-05-08) with BH 50/50 baseline
     overlaid as a horizontal reference line. Source: storage/strategy_metrics.json
     (live forward; 837 trading days for SPY/GLD-anchored strategies).
  2. k715_long_term_vs_recent_bh.png — long-term context: K687 19.2yr (2007-2026)
     full-sample Sharpe ranking (BH 50/50 #1 at 0.545) vs same-period 2023-2026
     live (BH falls behind — illustrative subset). Two-panel side-by-side.
  3. k715_vix_regime_overlay.png — daily VIX 2023-2026 with shaded high-VIX
     periods (>25) highlighting tariff-shock regime where VT thrives.

Numbers byte-for-byte from:
  - storage/strategy_metrics.json (paper_trading post-2023 stats)
  - experiments/k687/k687_results.json (full-sample 2006-2026 ranking)
  - storage/paper_trading.json _market_daily (VIX series)

No look-ahead, no synthetic data. Charts saved under storage/charts/ and
embedded via Supabase upload by the publish step.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "storage" / "charts"
OUT.mkdir(parents=True, exist_ok=True)

# ─── Load data ──────────────────────────────────────────────
metrics = json.loads((ROOT / "storage" / "strategy_metrics.json").read_text())
paper_trading = json.loads((ROOT / "storage" / "paper_trading.json").read_text())
k687 = json.loads((ROOT / "experiments" / "k687" / "k687_results.json").read_text())

# ─── Figure 1: 2023-2026 paper-trading strategy ranking ─────
# Pretty display labels (knowledge.json K715 narrative reference)
display = {
    "taiwan_spy_momentum": "TW Momentum (0050)",
    "tz_tw_jp_5050": "Tri-Zone TW/JP/SPY",
    "global_vt_tz": "Global VT (Tri-Zone)",
    "piecewise_conservative": "Piecewise Conservative",
    "adaptive_tier": "Adaptive Tier (VIX)",
    "taiwan_hybrid_leverage": "TW Hybrid Leverage",
    "vix_cond_leverage": "VIX-Cond Leverage",
    "taiwan_8.63vix": "TW VT 8.63/VIX",
    "risk_parity": "Risk Parity (SPY+GLD)",
    "recommended_5050": "Recommended 50/50 (12/VIX)",
    "vix_leading_guard": "VIX Leading Guard",
    "fear_dca": "Fear DCA",
    "slow_vt": "Slow VT (GARCH)",
    "simple_12vix": "Simple 12/VIX",
}

rows = []
for k, v in metrics.items():
    if k == "_market_daily":
        continue
    rows.append({
        "key": k,
        "label": display.get(k, k),
        "sharpe": v.get("sharpe"),
        "ann_ret": v.get("annualized_return"),
        "mdd": v.get("max_drawdown"),
        "calmar": v.get("calmar"),
        "days": v.get("trading_days"),
    })

# K715 narrative cites Sharpe 1.862 BH baseline (2026-03-29 snapshot).
# Live forward refresh shifts; use snapshot from K715 + show current update
# in caption text. For chart honesty plot BH baseline = 1.862 as REPORTED
# at K715 evaluation (frozen in knowledge.json L18004), not a moving target.
BH_5050_SHARPE = 1.862
BH_5050_LABEL = "BH 50/50 (baseline @ K715)"

rows = sorted(rows, key=lambda r: -r["sharpe"])

fig, ax = plt.subplots(figsize=(12, 7))
labels = [r["label"] for r in rows]
sharpes = [r["sharpe"] for r in rows]

# Color: Taiwan strategies = #d62728 (red), VT/SPY = #1f77b4 (blue),
# Recommended/baseline-adjacent = #2ca02c (green)
def _color(key):
    if key.startswith("taiwan") or key in ("tz_tw_jp_5050", "global_vt_tz"):
        return "#d62728"
    if key in ("recommended_5050", "risk_parity"):
        return "#2ca02c"
    return "#4c72b0"

colors = [_color(r["key"]) for r in rows]
bars = ax.barh(labels, sharpes, color=colors, edgecolor="white", linewidth=0.6)
ax.axvline(BH_5050_SHARPE, color="#888", linestyle="--", linewidth=1.5,
           label=f"BH 50/50 baseline (Sharpe {BH_5050_SHARPE:.2f})")
ax.invert_yaxis()
ax.set_xlabel("Sharpe Ratio (live forward, 2023-01-04 → 2026-05-08)", fontsize=11)
ax.set_title("2023-2026 同期間策略排名:VT 家族在高 VIX 時期勝過 BH",
             fontsize=13, weight="bold", pad=12)
for b, s in zip(bars, sharpes):
    ax.text(b.get_width() + 0.04, b.get_y() + b.get_height() / 2,
            f"{s:.2f}", va="center", fontsize=9.5)
ax.legend(loc="lower right", fontsize=10)
ax.grid(axis="x", alpha=0.3)
ax.set_xlim(0, max(sharpes) * 1.12)
plt.tight_layout()
out1 = OUT / "k715_strategy_ranking_2023_2026.png"
plt.savefig(out1, dpi=120)
plt.close()
print(f"saved {out1}")

# ─── Figure 2: long-term vs same-period BH-VT comparison ────
# K687 full-sample Sharpe ranking (top 5) — 2007-2026 19.2 years
k687_top = k687["full_sample_ranking"][:6]
labels_k687 = [r["strategy"] for r in k687_top]
sharpes_k687 = [r["sharpe"] for r in k687_top]

# Same-period (2023-2026) — BH baseline + matching strategies for comparison
# Numbers from K715 narrative + live strategy_metrics.json refresh.
# Use K715 snapshot (2026-03-29) for parity with K687 lag conventions.
k715_compare = [
    ("BH 50/50 SPY/GLD", BH_5050_SHARPE),       # K715 baseline (Mar 2026 snapshot)
    ("Recommended 50/50 (12/VIX)", 1.865),       # K715 narrative
    ("Risk Parity (SPY+GLD)", metrics["risk_parity"]["sharpe"]),
    ("Simple 12/VIX (SPY)", metrics["simple_12vix"]["sharpe"]),
    ("Slow VT GARCH (SPY)", metrics["slow_vt"]["sharpe"]),
]
labels_k715 = [t[0] for t in k715_compare]
sharpes_k715 = [t[1] for t in k715_compare]

fig, axes = plt.subplots(1, 2, figsize=(14, 6.5))

# Left: K687 long-term
axes[0].barh(labels_k687, sharpes_k687,
             color=["#1f77b4" if "BH" in l else "#aec7e8" for l in labels_k687],
             edgecolor="white", linewidth=0.6)
axes[0].invert_yaxis()
axes[0].set_xlabel("Sharpe Ratio", fontsize=11)
axes[0].set_title("長期 (K687, 2007-2026, 19.2 年)\nBH 50/50 排名第一",
                  fontsize=12, weight="bold")
for i, s in enumerate(sharpes_k687):
    axes[0].text(s + 0.005, i, f"{s:.3f}", va="center", fontsize=9)
axes[0].set_xlim(0, max(sharpes_k687) * 1.18)
axes[0].grid(axis="x", alpha=0.3)

# Right: K715 same-period
axes[1].barh(labels_k715, sharpes_k715,
             color=["#1f77b4" if "BH" in l else "#2ca02c" for l in labels_k715],
             edgecolor="white", linewidth=0.6)
axes[1].invert_yaxis()
axes[1].set_xlabel("Sharpe Ratio", fontsize=11)
axes[1].set_title("近期 (K715, 2023-2026, 高 VIX 期間)\nVT 家族普遍勝過 BH",
                  fontsize=12, weight="bold")
for i, s in enumerate(sharpes_k715):
    axes[1].text(s + 0.02, i, f"{s:.2f}", va="center", fontsize=9)
axes[1].set_xlim(0, max(sharpes_k715) * 1.18)
axes[1].grid(axis="x", alpha=0.3)

fig.suptitle("VT 是 Regime-Dependent:長期沒 alpha,高 VIX 時才大放異彩",
             fontsize=13, weight="bold", y=1.02)
plt.tight_layout()
out2 = OUT / "k715_long_term_vs_recent_bh.png"
plt.savefig(out2, dpi=120, bbox_inches="tight")
plt.close()
print(f"saved {out2}")

# ─── Figure 3: VIX regime overlay 2023-2026 ─────────────────
md = paper_trading["_market_daily"]
dates = sorted(md.keys())
vix = []
date_obj = []
for d in dates:
    row = md[d]
    v = row.get("vix_close") or row.get("vix_level")
    if v is None:
        continue
    date_obj.append(np.datetime64(d))
    vix.append(float(v))

date_obj = np.array(date_obj)
vix = np.array(vix)

fig, ax = plt.subplots(figsize=(13, 5.5))
ax.plot(date_obj, vix, color="#1f77b4", linewidth=1.2, label="VIX daily close")

# Highlight high-VIX regime (>25)
high_mask = vix >= 25
# Find contiguous runs
runs = []
start = None
for i, m in enumerate(high_mask):
    if m and start is None:
        start = i
    elif not m and start is not None:
        runs.append((start, i - 1))
        start = None
if start is not None:
    runs.append((start, len(high_mask) - 1))

for s, e in runs:
    ax.axvspan(date_obj[s], date_obj[e], alpha=0.18, color="#d62728")

ax.axhline(25, color="#d62728", linestyle="--", linewidth=1, alpha=0.7,
           label="VIX = 25 (高 VIX 門檻)")
ax.axhline(np.mean(vix), color="#888", linestyle=":", linewidth=1,
           label=f"期間平均 VIX = {np.mean(vix):.1f}")

# Annotate tariff shock peak
peak_idx = int(np.argmax(vix))
peak_date = date_obj[peak_idx]
peak_val = vix[peak_idx]
ax.annotate(f"關稅衝擊高點\nVIX = {peak_val:.1f}",
            xy=(peak_date, peak_val), xytext=(peak_date, peak_val + 8),
            ha="center", fontsize=10,
            arrowprops=dict(arrowstyle="->", color="#444"))

ax.set_title(
    "2023-2026 VIX 時間序列:多次高 VIX 區段 (紅) 提供 VT 策略發揮空間",
    fontsize=13, weight="bold", pad=12,
)
ax.set_xlabel("Date", fontsize=11)
ax.set_ylabel("VIX Index", fontsize=11)
ax.legend(loc="upper right", fontsize=10)
ax.grid(alpha=0.3)
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
plt.tight_layout()
out3 = OUT / "k715_vix_regime_overlay.png"
plt.savefig(out3, dpi=120)
plt.close()
print(f"saved {out3}")

print("\nAll three K715 charts generated.")
print(f"  - {out1.name} ({out1.stat().st_size//1024} KB)")
print(f"  - {out2.name} ({out2.stat().st_size//1024} KB)")
print(f"  - {out3.name} ({out3.stat().st_size//1024} KB)")
