"""0050 融資餘額變動 vs 未來 realized vol 的領先滯後檢驗。"""
import json, sqlite3
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = "/Users/yhlai0911/volpred-research"
OUT = f"{ROOT}/storage/article_assets/tw-margin-vol-leadlag"
plt.rcParams["font.sans-serif"] = ["PingFang HK", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

# ---- price ----
con = sqlite3.connect(f"{ROOT}/data/cache/price_cache.db")
px = pd.read_sql("select date, close from price_data where ticker='0050.TW' order by date", con)
con.close()
px["date"] = pd.to_datetime(px["date"])
px = px.set_index("date")
# 本地 price cache 在 2014-01-02 有一段未回溯調整的分割斷點（2013-12-31 收 58.70 → 2014-01-02 收 14.64，
# 比例約 4.01），2009-2013 段等於沒有套用 2025 年的 1 拆 4。為避免自己手動接價引入誤差，樣本從 2014-01-02 起算。
px = px.loc["2014-01-02":]
px["ret"] = np.log(px["close"]).diff()

ANN = np.sqrt(252) * 100
px["rv20"] = px["ret"].rolling(20).std() * ANN          # 過去 20 日已實現波動（年化%）
for h in (5, 10, 20):
    px[f"fwd_rv{h}"] = px["ret"].shift(-1).rolling(h).std().shift(-(h - 1)) * ANN

# ---- margin ----
mg = pd.read_csv(f"{ROOT}/storage/sentiment/tw_margin_0050.csv", parse_dates=["date"])
mg = mg.set_index("date").sort_index()
bal = mg["MarginPurchaseTodayBalance"].replace(0, np.nan)
d = pd.DataFrame({"margin": bal}).join(px, how="inner")
d["mchg5"] = d["margin"].pct_change(5) * 100
d["mchg20"] = d["margin"].pct_change(20) * 100

ev = {}
ev["sample"] = {"start": str(d.index.min().date()), "end": str(d.index.max().date()),
                "n_days": int(len(d)),
                "note": "0050 融資資料與 0050 收盤的交集。融資 csv 起於 2003-06-27、價格 cache 起於 2009-01-02，但 cache 在 2014-01-02 有未回溯調整的 1:4 分割斷點，故統計樣本自 2014-01-02 起"}

# ---- 事件背景 ----
r717 = float(px.loc["2026-07-17", "close"] / px.loc["2026-07-16", "close"] - 1) * 100
ytd = px.loc["2026-01-01":]
peak = ytd["close"].max(); peak_d = ytd["close"].idxmax()
dd = float(px.loc["2026-07-17", "close"] / peak - 1) * 100
r2026 = ytd["close"].pct_change() * 100
worst = r2026.nsmallest(3)
ev["event"] = {"ret_2026_07_17_pct": round(r717, 2),
               "peak_2026": {"date": str(peak_d.date()), "close": round(float(peak), 2)},
               "drawdown_from_2026_peak_pct": round(dd, 2),
               "worst3_2026_daily_pct": {str(k.date()): round(float(v), 2) for k, v in worst.items()},
               "rv20_before_2026_07_17": round(float(px.loc["2026-07-16", "rv20"]), 1),
               "rv20_on_2026_07_17": round(float(px.loc["2026-07-17", "rv20"]), 1)}

vx = pd.read_csv(f"{ROOT}/data/vixtwn/vixtwn_daily.csv", parse_dates=["date"]).set_index("date")
ev["vixtwn"] = {"start": str(vx.index.min().date()), "end": str(vx.index.max().date()),
                "close_2026_07_16": float(vx.loc["2026-07-16", "vixtwn_close"]),
                "median_full": round(float(vx["vixtwn_close"].median()), 2),
                "pctile_of_0716": round(float((vx["vixtwn_close"] <= vx.loc["2026-07-16", "vixtwn_close"]).mean() * 100), 1),
                "n_days": int(len(vx))}

# ---- 相關性（同期 vs 領先）----
c = {}
for h in (5, 10, 20):
    sub = d[["mchg20", "rv20", f"fwd_rv{h}"]].dropna()
    c[f"corr_mchg20_fwdrv{h}"] = round(float(sub["mchg20"].corr(sub[f"fwd_rv{h}"])), 3)
    c[f"corr_rv20_fwdrv{h}"] = round(float(sub["rv20"].corr(sub[f"fwd_rv{h}"])), 3)
c["corr_mchg20_rv20_same_day"] = round(float(d[["mchg20", "rv20"]].dropna().corr().iloc[0, 1]), 3)
ev["correlations"] = c

# ---- 迴歸：融資變動有沒有「額外」資訊 ----
def hac_ols(y, X, lags):
    X = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None])
        S += w * (G + G.T)
    V = XtXi @ S @ XtXi
    se = np.sqrt(np.diag(V))
    r2 = 1 - e.var() / y.var()
    return b, b / se, r2

reg = {}
for h in (5, 10, 20):
    sub = d[["mchg20", "rv20", f"fwd_rv{h}"]].dropna()
    y = sub[f"fwd_rv{h}"].values
    b1, t1, r2_1 = hac_ols(y, sub[["rv20"]].values, 2 * h)
    b2, t2, r2_2 = hac_ols(y, sub[["rv20", "mchg20"]].values, 2 * h)
    reg[f"h{h}"] = {"n": int(len(sub)),
                    "baseline_rv20_only_R2": round(float(r2_1), 4),
                    "with_margin_R2": round(float(r2_2), 4),
                    "delta_R2_pp": round(float((r2_2 - r2_1) * 100), 2),
                    "beta_margin": round(float(b2[2]), 4),
                    "t_margin_HAC": round(float(t2[2]), 2),
                    "beta_rv20": round(float(b2[1]), 3),
                    "t_rv20_HAC": round(float(t2[1]), 2)}
ev["regression"] = reg

# ---- 分位數條件分析 ----
sub = d[["mchg20", "rv20", "fwd_rv20"]].dropna()
q = sub["mchg20"].quantile([0.1, 0.9])
dec = {}
for lab, mask in [("融資 20 日增幅最快 10%", sub["mchg20"] >= q[0.9]),
                  ("融資 20 日減幅最快 10%", sub["mchg20"] <= q[0.1]),
                  ("全樣本", pd.Series(True, index=sub.index))]:
    s = sub.loc[mask, "fwd_rv20"]
    p = sub.loc[mask, "rv20"]
    dec[lab] = {"n": int(len(s)), "mean_fwd_rv20": round(float(s.mean()), 1),
                "median_fwd_rv20": round(float(s.median()), 1),
                "p90_fwd_rv20": round(float(s.quantile(0.9)), 1),
                "mean_past_rv20": round(float(p.mean()), 1)}
ev["deciles"] = {"cut_top10_mchg20_pct": round(float(q[0.9]), 2),
                 "cut_bot10_mchg20_pct": round(float(q[0.1]), 2), "stats": dec}

# 波動率自身的分位對照（證明分組差異多半來自波動 persistence）
qr = sub["rv20"].quantile(0.9)
ev["rv_own_decile"] = {"cut_top10_rv20": round(float(qr), 1),
                       "mean_fwd_rv20_when_rv20_top10": round(float(sub.loc[sub["rv20"] >= qr, "fwd_rv20"].mean()), 1)}

# 控制波動率後：同一 RV 分層內再看融資分組
ev["double_sort"] = {}
sub2 = sub.copy()
sub2["rv_bin"] = pd.qcut(sub2["rv20"], 3, labels=["低波動", "中波動", "高波動"])
for b in ["低波動", "中波動", "高波動"]:
    g = sub2[sub2["rv_bin"] == b]
    hi = g[g["mchg20"] >= g["mchg20"].quantile(0.8)]["fwd_rv20"]
    lo = g[g["mchg20"] <= g["mchg20"].quantile(0.2)]["fwd_rv20"]
    ev["double_sort"][b] = {"n_bin": int(len(g)),
                            "fwd_rv20_margin_top20pct": round(float(hi.mean()), 1),
                            "fwd_rv20_margin_bot20pct": round(float(lo.mean()), 1),
                            "diff": round(float(hi.mean() - lo.mean()), 1)}

# 雙分層每格的「當下波動」對照 + block bootstrap
rng = np.random.default_rng(20260719)
def block_boot_diff(g, nboot=2000, blk=40):
    hi_c = g["mchg20"] >= g["mchg20"].quantile(0.8)
    lo_c = g["mchg20"] <= g["mchg20"].quantile(0.2)
    obs = g.loc[hi_c, "fwd_rv20"].mean() - g.loc[lo_c, "fwd_rv20"].mean()
    arr = g.reset_index(drop=True)
    n = len(arr); nb = max(1, n // blk)
    diffs = []
    for _ in range(nboot):
        starts = rng.integers(0, max(1, n - blk), nb)
        idx = np.concatenate([np.arange(s0, s0 + blk) for s0 in starts])
        idx = idx[idx < n]
        b = arr.iloc[idx]
        h = b[b["mchg20"] >= b["mchg20"].quantile(0.8)]["fwd_rv20"]
        l = b[b["mchg20"] <= b["mchg20"].quantile(0.2)]["fwd_rv20"]
        if len(h) > 5 and len(l) > 5:
            diffs.append(h.mean() - l.mean())
    diffs = np.array(diffs)
    return obs, float(np.percentile(diffs, 5)), float(np.percentile(diffs, 95))

for b in ["低波動", "中波動", "高波動"]:
    g = sub2[sub2["rv_bin"] == b]
    hi_c = g["mchg20"] >= g["mchg20"].quantile(0.8)
    lo_c = g["mchg20"] <= g["mchg20"].quantile(0.2)
    obs, lo95, hi95 = block_boot_diff(g)
    ev["double_sort"][b].update({
        "past_rv20_margin_top20pct": round(float(g.loc[hi_c, "rv20"].mean()), 1),
        "past_rv20_margin_bot20pct": round(float(g.loc[lo_c, "rv20"].mean()), 1),
        "boot_diff_p05": round(lo95, 1), "boot_diff_p95": round(hi95, 1),
        "boot_note": "block bootstrap, block=40 交易日, 2000 次, 90% 區間"})

# 最後一筆可觀測的融資讀數
last = d.dropna(subset=["mchg20"]).iloc[-1]
ev["last_margin_obs"] = {"date": str(d.dropna(subset=["mchg20"]).index[-1].date()),
                         "margin_lots": int(last["margin"]),
                         "mchg20_pct": round(float(last["mchg20"]), 1),
                         "pctile_in_sample": round(float((sub["mchg20"] <= last["mchg20"]).mean() * 100), 1),
                         "gap_days_to_event": int((pd.Timestamp("2026-07-17") - d.dropna(subset=["mchg20"]).index[-1]).days)}

# 最後讀數之後實際發生什麼（n=1 軼事，非統計證據）
after = px.loc["2026-03-17":]
ev["after_last_obs"] = {
    "rv_2026_03_17_to_04_15_ann_pct": round(float(px.loc["2026-03-17":"2026-04-15", "ret"].std() * ANN), 1),
    "rv_2026_03_17_to_07_17_ann_pct": round(float(after["ret"].std() * ANN), 1),
    "rv20_median_2014_2026": round(float(px["rv20"].median()), 1),
    "caveat": "n=1，只是後續事實紀錄，不能當統計證據"}

# ---- 圖 1：雙 y 軸 長期 ----
fig, ax = plt.subplots(2, 1, figsize=(11, 8))
a = ax[0]
a.plot(d.index, d["margin"] / 1000, color="#c0392b", lw=0.9, label="0050 融資餘額（千張）")
a.set_ylabel("融資餘額（千張）", color="#c0392b")
a2 = a.twinx()
a2.plot(d.index, d["rv20"], color="#2c3e50", lw=0.8, alpha=0.75, label="20 日已實現波動（年化%）")
a2.set_ylabel("20 日已實現波動（年化 %）", color="#2c3e50")
a.set_title("0050 融資餘額 與 20 日已實現波動（2014-01 ~ 2026-03）")
b = ax[1]
b.scatter(sub["mchg20"], sub["fwd_rv20"], s=3, alpha=0.18, color="#2980b9")
b.axvline(q[0.9], color="#c0392b", ls="--", lw=1)
b.axvline(q[0.1], color="#27ae60", ls="--", lw=1)
b.set_xlabel("融資餘額 20 日變動（%）")
b.set_ylabel("其後 20 日已實現波動（年化 %）")
b.set_title(f"融資變動 vs 其後 20 日波動：相關係數 {c['corr_mchg20_fwdrv20']}（n={len(sub)}）")
b.set_xlim(-40, 60)
plt.tight_layout()
fig.savefig(f"{OUT}/fig1_margin_vs_vol.png", dpi=140)
plt.close(fig)

# ---- 圖 2：分組後未來波動分布 ----
fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
bins = np.linspace(0, 60, 45)
ax[0].hist(sub["fwd_rv20"], bins=bins, density=True, alpha=0.45, color="#7f8c8d", label="全樣本")
ax[0].hist(sub.loc[sub["mchg20"] >= q[0.9], "fwd_rv20"], bins=bins, density=True,
           histtype="step", lw=2, color="#c0392b", label="融資增速前 10%")
ax[0].hist(sub.loc[sub["rv20"] >= qr, "fwd_rv20"], bins=bins, density=True,
           histtype="step", lw=2, color="#8e44ad", label="當前波動前 10%")
ax[0].set_xlabel("其後 20 日已實現波動（年化 %）"); ax[0].set_ylabel("密度")
ax[0].legend(fontsize=8); ax[0].set_title("誰能挑出高波動的未來？")
labels = ["低波動", "中波動", "高波動"]
xs = np.arange(3); w = 0.35
ax[1].bar(xs - w/2, [ev["double_sort"][l]["fwd_rv20_margin_top20pct"] for l in labels], w, color="#c0392b", label="融資增速前 20%")
ax[1].bar(xs + w/2, [ev["double_sort"][l]["fwd_rv20_margin_bot20pct"] for l in labels], w, color="#27ae60", label="融資增速後 20%")
ax[1].set_xticks(xs); ax[1].set_xticklabels(labels)
ax[1].set_ylabel("其後 20 日已實現波動（年化 %）")
ax[1].set_title("先按當前波動分三層，再看融資快慢")
ax[1].legend(fontsize=8)
plt.tight_layout()
fig.savefig(f"{OUT}/fig2_conditional.png", dpi=140)
plt.close(fig)

json.dump(ev, open(f"{OUT}/stats_raw.json", "w"), ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
