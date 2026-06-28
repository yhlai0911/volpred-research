#!/usr/bin/env python3
"""K1557 charts — honest visual story for the FinLab-claim verification."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

OUT = Path(__file__).resolve().parent
plt.rcParams.update({"font.size": 11, "figure.dpi": 130,
                     "axes.spines.top": False, "axes.spines.right": False})
# CJK font (macOS) — only set a family matplotlib's font_manager actually sees,
# else it silently falls back to a Latin font and renders CJK as □ boxes.
from matplotlib import font_manager as _fm
_seen = {f.name for f in _fm.fontManager.ttflist}
for _f in ("Heiti TC", "Arial Unicode MS", "Hiragino Sans GB", "PingFang HK", "STHeiti"):
    if _f in _seen:
        plt.rcParams["font.sans-serif"] = [_f, "DejaVu Sans"]
        plt.rcParams["font.family"] = "sans-serif"
        break
plt.rcParams["axes.unicode_minus"] = False

df = yf.download("^TWII", start="1997-01-01", end="2026-06-28",
                 progress=False, auto_adjust=False)
c = df["Close"]; c = c.iloc[:, 0] if c.ndim > 1 else c; c = c.dropna()
idx = c.index; cv = c.values; n = len(cv)
r3 = pd.Series(cv, index=idx).pct_change(3).values
rh = pd.Series(cv, index=idx).rolling(252).max().values
ph = pd.Series(cv, index=idx).shift(1).rolling(252).max().values

raw = []
for t in range(255, n):
    if idx[t].year < 1999:
        continue
    if not any(not np.isnan(rh[t-k]) and abs(cv[t-k]-rh[t-k]) < 1e-6
               and (np.isnan(ph[t-k]) or cv[t-k] > ph[t-k]-1e-6) for k in range(6)):
        continue
    w = r3[t-251:t+1]; w = w[~np.isnan(w)]
    if len(w) < 100:
        continue
    if r3[t] <= np.percentile(w, 2):
        raw.append(t)
eps = []
for t in raw:
    if eps and t-eps[-1] <= 20:
        continue
    eps.append(t)

rng = np.random.default_rng(42)
FWD = {"3M": 63, "6M": 126, "1Y": 252}


def placebo(h):
    pool = np.array([t+1 for t in range(255, n-h-1) if idx[t].year >= 1999 and t+1+h < n])
    ev = np.array([(cv[t+1+h]/cv[t+1]-1)*100 for t in eps if t+1+h < n])
    rm = np.array([np.median([(cv[e+h]/cv[e]-1)*100 for e in rng.choice(pool, len(ev), replace=False)])
                   for _ in range(10000)])
    return ev, rm


# ── fig 1: placebo (3M noise vs 1Y) ──
fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
NAVY, RED, GREY = "#1f3a5f", "#c0392b", "#8a8f99"
for ax, (lab, h) in zip(axes, [("3M", 63), ("1Y", 252)]):
    ev, rm = placebo(h)
    em = np.median(ev)
    pct = (rm <= em).mean()
    ax.hist(rm, bins=60, color=GREY, alpha=0.55, edgecolor="none")
    ax.axvline(em, color=RED, lw=2.4,
               label=f"事件後中位 {em:+.1f}%\n(隨機分佈第 {pct*100:.0f} 百分位)")
    ax.axvline(np.median(rm), color=NAVY, lw=1.4, ls="--", label=f"隨機中位 {np.median(rm):+.1f}%")
    verdict = "與隨機無異 → 雜訊" if 0.05 < pct < 0.95 else "落在尾端 (p<0.05)"
    ax.set_title(f"{lab} 報酬：事件 vs 隨機 {len(ev)} 個日期\n{verdict}", fontsize=11)
    ax.set_xlabel("forward 報酬中位數 (%)"); ax.legend(fontsize=8.5, loc="upper left")
fig.suptitle("Placebo Bootstrap：創新高急殺後「能不能分辨真信號 vs 隨機」", fontsize=12.5, y=1.02)
fig.tight_layout(); fig.savefig(OUT/"fig_a_placebo.png", bbox_inches="tight"); plt.close(fig)

# ── fig 2: sensitivity (1Y fragile) ──
res = json.load(open(OUT/"k1557_results.json"))
sens = res["sensitivity"]
labels = [f"lb{s['lookback']}/p{int(s['pctile'])}\n(n={s['n_events']})" for s in sens]
vals = [s["m1Y"] for s in sens]
fig, ax = plt.subplots(figsize=(9.5, 4.3))
cols = [RED if v is not None and v < 0 else NAVY for v in vals]
ax.bar(range(len(vals)), [v if v is not None else 0 for v in vals], color=cols, alpha=0.85)
ax.axhline(9.1, color="#2e7d32", lw=1.8, ls="--", label="隨便買持有 1 年中位 +9.1%")
ax.axhline(0, color="#444", lw=0.8)
ax.set_xticks(range(len(vals))); ax.set_xticklabels(labels, fontsize=8)
ax.set_ylabel("事件後 1 年報酬中位數 (%)")
ax.set_title("「一年詛咒」對 filter 極度敏感：換個切法就從 −5.6% 翻成 +3.4%", fontsize=11.5)
ax.legend(fontsize=9)
fig.tight_layout(); fig.savefig(OUT/"fig_b_sensitivity.png", bbox_inches="tight"); plt.close(fig)

# ── fig 3: per-event forward returns ──
rows = res["events"]
dts = [r["event_date"][:7] for r in rows]
m3 = [r["3M"] for r in rows]; m1 = [r["1Y"] for r in rows]
x = np.arange(len(rows)); w = 0.4
fig, ax = plt.subplots(figsize=(10.5, 4.3))
ax.bar(x-w/2, [v if v is not None else 0 for v in m3], w, color=NAVY, alpha=0.85, label="3 個月後")
ax.bar(x+w/2, [v if v is not None else 0 for v in m1], w, color=RED, alpha=0.8, label="1 年後")
ax.axhline(0, color="#444", lw=0.8)
ax.set_xticks(x); ax.set_xticklabels(dts, rotation=45, ha="right", fontsize=8)
ax.set_ylabel("報酬 (%)"); ax.legend(fontsize=9.5)
ax.set_title("13 次「創新高急殺」事件後的報酬（3 個月多半反彈，1 年各走各的）", fontsize=11.5)
fig.tight_layout(); fig.savefig(OUT/"fig_c_events.png", bbox_inches="tight"); plt.close(fig)

print("charts: fig_a_placebo.png fig_b_sensitivity.png fig_c_events.png")
