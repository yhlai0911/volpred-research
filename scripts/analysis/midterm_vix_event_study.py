"""期中選舉 VIX 事件研究 — T-1→T+1 波動率壓縮是否真的存在。

輸出 storage/experiments/midterm_vix_event_study.json + 兩張圖。
資料：yfinance ^VIX / ^GSPC 日資料（2000 起，涵蓋 6 次期中選舉）。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# CJK 字型：沒設會整排豆腐格（見 scripts/audit_cjk_chart_fonts.py）
_installed = {f.name for f in font_manager.fontManager.ttflist}
for _f in ("PingFang TC", "PingFang HK", "Heiti TC", "Hiragino Sans GB",
           "Arial Unicode MS", "STHeiti"):
    if _f in _installed:
        plt.rcParams["font.sans-serif"] = [_f]
        break
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "storage/experiments/midterm_vix_event_study.json"
FIG_DIR = ROOT / "storage/figures"

MIDTERMS = ["2002-11-05", "2006-11-07", "2010-11-02",
            "2014-11-04", "2018-11-06", "2022-11-08"]
NEXT_MIDTERM = "2026-11-03"

px = yf.download(["^VIX", "^GSPC"], start="1999-06-01", progress=False,
                 auto_adjust=False)["Close"].dropna()
vix, spx = px["^VIX"], px["^GSPC"]
spx_ret = np.log(spx).diff()
dvix = np.log(vix).diff()          # VIX 日對數變動，作為無條件分佈基準

idx = px.index


def bar(date):
    """回傳事件日在 index 上的位置：取 >= date 的第一根。

    六次選舉日皆為週二且 NYSE 有開盤，已實測全部 exact match（t-1/t/t+1 = 一/二/三），
    故 t 就是選舉日本身。若 yfinance 某日缺值被 dropna 砍掉，t 會靜默後移 —— 下面的
    assert 就是擋這件事。
    """
    return idx.searchsorted(pd.Timestamp(date))


def rv20(pos):
    """[pos, pos+20) 這 20 個交易日的年化實現波動率（%）。"""
    seg = spx_ret.iloc[pos:pos + 20]
    return float(seg.std(ddof=1) * np.sqrt(252) * 100) if len(seg) == 20 else None


rows = []
for d in MIDTERMS:
    t = bar(d)                       # t = 選舉日本身（見 bar() docstring）
    assert str(idx[t].date()) == d, f"事件日 {d} 未 exact match（yfinance 缺值？）"
    row = {
        "election": d,
        "vix_t_minus_60": round(float(vix.iloc[t - 60]), 2),
        "vix_t_minus_20": round(float(vix.iloc[t - 20]), 2),
        "vix_t_minus_1": round(float(vix.iloc[t - 1]), 2),
        "vix_t_plus_1": round(float(vix.iloc[t + 1]), 2),
        "vix_t_plus_5": round(float(vix.iloc[t + 5]), 2),
        "vix_t_plus_20": round(float(vix.iloc[t + 20]), 2),
    }
    row["runup_pct"] = round((row["vix_t_minus_1"] / row["vix_t_minus_60"] - 1) * 100, 1)
    row["crush_pct"] = round((row["vix_t_plus_1"] / row["vix_t_minus_1"] - 1) * 100, 1)
    row["crush_5d_pct"] = round((row["vix_t_plus_5"] / row["vix_t_minus_1"] - 1) * 100, 1)
    row["rv20_pre"] = round(rv20(t - 20), 1)
    row["rv20_post"] = round(rv20(t + 1), 1)
    # 選前 VIX 減選後 20 日實現波動。這是 IV-RV 的「波動度」口徑價差，
    # 不是學術定義的 variance risk premium（那是變異數口徑），量級不可互換。
    row["iv_rv_spread_post"] = round(row["vix_t_minus_1"] - row["rv20_post"], 1)
    rows.append(row)

df = pd.DataFrame(rows)

# --- 統計檢定：選舉日的 VIX 單日變動 vs 無條件分佈 ---
event_dlog = np.array([np.log(r["vix_t_plus_1"] / r["vix_t_minus_1"]) for r in rows])
uncond = dvix.dropna().values
pctiles = [float((uncond < e).mean() * 100) for e in event_dlog]

# 每次選舉抽同長度隨機樣本，看事件平均值有多極端（bootstrap，無分佈假設）
rng = np.random.default_rng(20261103)
boot = np.array([rng.choice(uncond, size=len(event_dlog), replace=False).mean()
                 for _ in range(20000)])
obs_mean = float(event_dlog.mean())
p_boot = float((boot <= obs_mean).mean())

stats = {
    "n_events": len(rows),
    "mean_crush_pct": round(float(df["crush_pct"].mean()), 1),
    "median_crush_pct": round(float(df["crush_pct"].median()), 1),
    "n_negative": int((df["crush_pct"] < 0).sum()),
    "uncond_mean_1d_pct": round(float((np.exp(uncond.mean()) - 1) * 100), 3),
    "uncond_n": int(len(uncond)),
    "event_pctiles": [round(p, 1) for p in pctiles],
    "bootstrap_p_one_sided": round(p_boot, 4),
    "mean_runup_pct": round(float(df["runup_pct"].mean()), 1),
    "mean_iv_rv_spread_post": round(float(df["iv_rv_spread_post"].mean()), 1),
    "n_iv_rv_spread_positive": int((df["iv_rv_spread_post"] > 0).sum()),
}

# --- 目前位置：2026 期中選舉 T-N ---
# 選舉日尚未發生，searchsorted 會回 len(idx)，故剩餘交易日用日曆日 ×252/365 估算
today = idx[-1]
cal_days = int((pd.Timestamp(NEXT_MIDTERM) - today).days)
tdays_ahead = int(round(cal_days * 252 / 365))
# 把「今天」對齊到歷史同一 horizon（T-tdays_ahead）才能橫向比
hist_matched = [round(float(vix.iloc[bar(d) - tdays_ahead]), 2) for d in MIDTERMS]
current = {
    "as_of": str(today.date()),
    "vix_now": round(float(vix.iloc[-1]), 2),
    "calendar_days_to_election": cal_days,
    "approx_trading_days_to_election": tdays_ahead,
    "hist_vix_at_same_horizon": dict(zip([d[:4] for d in MIDTERMS], hist_matched)),
    "hist_vix_at_same_horizon_mean": round(float(np.mean(hist_matched)), 2),
    "hist_vix_at_same_horizon_range": [min(hist_matched), max(hist_matched)],
}

# --- 正規化事件路徑（T-1 = 100）：平均與中位數，n=6 故中位數才是主證據 ---
norm_paths = np.array([vix.iloc[bar(d) - 40:bar(d) + 41].values / vix.iloc[bar(d) - 1] * 100
                       for d in MIDTERMS])
path_stats = {}
for off in (-40, -30, -20, -18, -10, -5, -1, 1, 5, 10, 20):
    col = norm_paths[:, off + 40]
    path_stats[str(off)] = {
        "mean": round(float(col.mean()), 1),
        "median": round(float(np.median(col)), 1),
        "n_above_100": int((col > 100).sum()),
    }

payload = {"events": rows, "stats": stats, "path_normalized": path_stats,
           "current": current,
           "data_source": "yfinance ^VIX/^GSPC", "last_bar": str(today.date())}
OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

# --- 圖 1：六次選舉的 VIX 事件窗口路徑（以 T-1 標準化為 100）---
FIG_DIR.mkdir(parents=True, exist_ok=True)
fig, ax = plt.subplots(figsize=(9, 5.2))
win = range(-40, 41)
paths = []
for d in MIDTERMS:
    t = bar(d)
    seg = vix.iloc[t - 40:t + 41].values
    norm = seg / vix.iloc[t - 1] * 100
    paths.append(norm)
    ax.plot(list(win), norm, alpha=0.45, lw=1.2, label=d[:4])
ax.plot(list(win), np.median(paths, axis=0), color="crimson", lw=2.6, label="六次中位數")
ax.plot(list(win), np.mean(paths, axis=0), color="darkorange", lw=1.8, ls="--", label="六次平均")
ax.axvline(0, color="k", ls="--", lw=1)
ax.axhline(100, color="gray", ls=":", lw=1)
ax.set_xlabel("距選舉日交易日數（0 = 選舉日）")
ax.set_ylabel("VIX（選前一日 = 100）")
ax.set_title("期中選舉前後的 VIX 路徑：選前一路往下，選後再掉一階")
ax.legend(fontsize=8, ncol=4)
fig.tight_layout()
p1 = FIG_DIR / "midterm_vix_event_paths.png"
fig.savefig(p1, dpi=150)

# --- 圖 2：選舉日單日 VIX 變動 vs 無條件分佈 ---
fig, ax = plt.subplots(figsize=(9, 4.8))
ax.hist((np.exp(uncond) - 1) * 100, bins=140, range=(-25, 25),
        color="lightsteelblue", edgecolor="none")
for r, e in zip(rows, event_dlog):
    ax.axvline((np.exp(e) - 1) * 100, color="crimson", lw=1.6)
    ax.text((np.exp(e) - 1) * 100, ax.get_ylim()[1] * 0.92, r["election"][:4],
            rotation=90, fontsize=8, color="crimson", ha="right", va="top")
ax.set_xlabel("VIX 單日變動（%）")
ax.set_ylabel("交易日數")
ax.set_title(f"六次期中選舉的隔日 VIX 變動，落在 {len(uncond):,} 個交易日分佈的哪裡")
fig.tight_layout()
p2 = FIG_DIR / "midterm_vix_crush_distribution.png"
fig.savefig(p2, dpi=150)

print(json.dumps(payload, ensure_ascii=False, indent=2))
print(f"\nfigures: {p1}\n         {p2}")
