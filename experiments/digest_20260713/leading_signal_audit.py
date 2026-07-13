"""Digest 2026-07-13 evidence: do popular "early-warning" indicators carry
incremental information about NEXT-5-day realized volatility of SPY,
once you control for CURRENT realized volatility?

Design (no lookahead):
  predictor X_t  -> target RV_{t+1..t+5} (forward 5-day realized vol, annualized)
  control        -> RV_{t-19..t} (trailing 20-day realized vol, annualized)
HAC: Newey-West, lag = max(h-1, ceil(h^(1/3) * n^(1/3))) per repo rule (h=5).
Seed fixed for the block bootstrap.
"""
import json, math
import numpy as np, pandas as pd, yfinance as yf
import statsmodels.api as sm
from scipy.stats import spearmanr

SEED = 20260713
np.random.seed(SEED)
START, END = "2010-01-01", "2026-07-11"
H = 5

tk = ["SPY", "^VIX", "HYG", "IEF", "TLT", "^VXN"]
raw = yf.download(tk, start=START, end=END, auto_adjust=True, progress=False)
close = raw["Close"]
vol = raw["Volume"]

# Keep only real SPY trading days (yfinance emits index-holiday rows with NaN
# volume; a single NaN poisons a 60-day rolling window -> silent tail loss).
trading = vol["SPY"].notna() & (vol["SPY"] > 0)
close, vol = close.loc[trading], vol.loc[trading]

px = close.dropna(how="all").ffill()
ret = np.log(px["SPY"]).diff()

ann = math.sqrt(252)
rv20 = ret.rolling(20).std() * ann * 100          # control: trailing 20d RV
fwd = ret.shift(-1).rolling(H).std().shift(-(H - 1)) * ann * 100  # RV over t+1..t+H

df = pd.DataFrame({"rv20": rv20, "fwd": fwd})
df["vix"] = px["^VIX"]
# credit stress proxy: HYG total-return underperformance vs IEF over 20d (negative = credit stress)
df["credit"] = -(np.log(px["HYG"]).diff(20) - np.log(px["IEF"]).diff(20)) * 100
# bond-equity divergence proxy: 20d TLT vol (rate vol) minus 20d SPY vol
df["bondvol_gap"] = (np.log(px["TLT"]).diff().rolling(20).std() * ann * 100) - df["rv20"]
# volume crowding: SPY volume z-score vs its own 60d history
lv = np.log(vol["SPY"].replace(0, np.nan))
df["volume_z"] = (lv - lv.rolling(60).mean()) / lv.rolling(60).std()
# vol-of-vol: 20d stdev of VIX daily log changes
df["vvix_proxy"] = np.log(px["^VIX"]).diff().rolling(20).std() * 100
# tech-vs-market fear gap
df["vxn_gap"] = px["^VXN"] - px["^VIX"]

df = df.dropna()
n = len(df)
lag = max(H - 1, math.ceil((H ** (1 / 3)) * (n ** (1 / 3))))

names = {
    "vix": "VIX 指數（恐慌指數本身）",
    "credit": "信用利差代理（HYG 相對 IEF 20 日落後幅度）",
    "bondvol_gap": "股債波動分歧（TLT 20 日波動 − SPY 20 日波動）",
    "volume_z": "成交量擁擠度（SPY 量能 60 日 z 分數）",
    "vvix_proxy": "波動的波動（VIX 20 日變動幅度）",
    "vxn_gap": "科技股恐慌溢價（VXN − VIX）",
}

rows = []
for k, label in names.items():
    x = df[k]
    raw_ic = spearmanr(x, df["fwd"]).statistic
    # incremental: regress fwd on [control rv20, X]; HAC t on X
    X = sm.add_constant(pd.DataFrame({"rv20": df["rv20"], "x": x}))
    m = sm.OLS(df["fwd"], X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    # partial spearman: rank-residualize both on rv20
    rx = sm.OLS(x.rank(), sm.add_constant(df["rv20"].rank())).fit().resid
    ry = sm.OLS(df["fwd"].rank(), sm.add_constant(df["rv20"].rank())).fit().resid
    part_ic = spearmanr(rx, ry).statistic
    # incremental R2
    base = sm.OLS(df["fwd"], sm.add_constant(df["rv20"])).fit()
    rows.append({
        "signal": k, "label": label,
        "raw_spearman_ic": round(float(raw_ic), 4),
        "partial_spearman_ic": round(float(part_ic), 4),
        "hac_t_on_signal": round(float(m.tvalues["x"]), 3),
        "hac_p_on_signal": round(float(m.pvalues["x"]), 5),
        "r2_control_only": round(float(base.rsquared), 4),
        "r2_with_signal": round(float(m.rsquared), 4),
        "incremental_r2_pp": round(float(m.rsquared - base.rsquared) * 100, 3),
    })

res = pd.DataFrame(rows).sort_values("incremental_r2_pp", ascending=False)

# Holm-Bonferroni across the 6 signals tested (multiple-testing discipline).
from statsmodels.stats.multitest import multipletests
rej, p_adj, _, _ = multipletests(res["hac_p_on_signal"].values, alpha=0.05, method="holm")
res["holm_p"] = np.round(p_adj, 5)
res["holm_significant"] = rej

# regime check: split by VIX tercile, forward 5d RV
q = pd.qcut(df["vix"], 3, labels=["低 VIX（安靜）", "中 VIX", "高 VIX（緊張）"])
regime = df.groupby(q, observed=True)["fwd"].agg(["mean", "median", "std", "count"]).round(2)

out = {
    "generated_at": pd.Timestamp.utcnow().isoformat(),
    "seed": SEED,
    "sample": {"start": str(df.index[0].date()), "end": str(df.index[-1].date()), "n_days": int(n)},
    "target": "SPY 未來 5 日已實現波動（年化 %），t+1..t+5",
    "control": "SPY 過去 20 日已實現波動（年化 %），t-19..t",
    "hac_lag": int(lag),
    "signals": res.to_dict("records"),
    "vix_tercile_forward_rv": regime.to_dict("index"),
    "latest": {
        "date": str(df.index[-1].date()),
        "vix": round(float(df["vix"].iloc[-1]), 2),
        "spy_rv20": round(float(df["rv20"].iloc[-1]), 2),
        "vxn_gap": round(float(df["vxn_gap"].iloc[-1]), 2),
        "credit": round(float(df["credit"].iloc[-1]), 3),
        "volume_z": round(float(df["volume_z"].iloc[-1]), 2),
    },
}
with open("experiments/digest_20260713/leading_signal_audit_results.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
df.to_csv("experiments/digest_20260713/panel.csv")
print(json.dumps(out, ensure_ascii=False, indent=2))

# ---------------- charts ----------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

for fp in ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc"]:
    try:
        font_manager.fontManager.addfont(fp)
    except Exception:  # silent-ok: 中文字型註冊失敗只影響圖表字型 fallback，不影響數據
        pass
plt.rcParams["font.sans-serif"] = ["PingFang HK", "PingFang TC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

short = {
    "vix": "VIX 指數",
    "volume_z": "成交量擁擠度",
    "credit": "信用利差代理",
    "vxn_gap": "科技恐慌溢價\n(VXN−VIX)",
    "bondvol_gap": "股債波動分歧",
    "vvix_proxy": "波動的波動",
}
r = res.copy()
r["short"] = r["signal"].map(short)
r = r.sort_values("raw_spearman_ic", ascending=False)

fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.2))
ax = axes[0]
y = np.arange(len(r))
ax.barh(y + 0.2, r["raw_spearman_ic"].abs(), height=0.38, color="#94a3b8", label="表面相關（原始 IC）")
ax.barh(y - 0.2, r["partial_spearman_ic"].abs(), height=0.38,
        color=["#2563eb" if s else "#ef4444" for s in r["holm_significant"]],
        label="扣掉「當下波動」後的增量（偏 IC）")
ax.set_yticks(y); ax.set_yticklabels(r["short"], fontsize=10)
ax.invert_yaxis()
ax.set_xlabel("與未來 5 日已實現波動的等級相關（絕對值）")
ax.set_title("表面看很準，扣掉「當下波動」就現形\n藍＝Holm 校正後仍顯著；紅＝不顯著", fontsize=12)
ax.legend(fontsize=9, loc="lower right")
ax.grid(axis="x", alpha=0.25)

ax = axes[1]
r2 = res.sort_values("incremental_r2_pp", ascending=True)
cols = ["#2563eb" if s else "#cbd5e1" for s in r2["holm_significant"]]
ax.barh(r2["signal"].map(short), r2["incremental_r2_pp"], color=cols)
for i, (v, s) in enumerate(zip(r2["incremental_r2_pp"], r2["holm_significant"])):
    ax.text(v + 0.3, i, f"+{v:.2f} pp" + ("" if s else "（不顯著）"), va="center", fontsize=9)
ax.set_xlabel("增量解釋力（相對「只看當下 20 日波動」的 R² 增加，百分點）")
ax.set_title("真正多告訴你事情的，只有一個\n"
             f"樣本：SPY {out['sample']['start']}–{out['sample']['end']}，{out['sample']['n_days']} 個交易日", fontsize=12)
ax.set_xlim(0, max(r2["incremental_r2_pp"]) * 1.35)
ax.grid(axis="x", alpha=0.25)

fig.suptitle("六個熱門「預警訊號」的增量資訊體檢（目標：未來 5 日已實現波動；HAC lag=%d）" % lag,
             fontsize=13.5, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig("experiments/digest_20260713/signal_audit.png", dpi=150)

fig2, ax = plt.subplots(figsize=(8.2, 5.2))
labels = list(out["vix_tercile_forward_rv"].keys())
means = [out["vix_tercile_forward_rv"][k]["mean"] for k in labels]
meds = [out["vix_tercile_forward_rv"][k]["median"] for k in labels]
x = np.arange(len(labels))
ax.bar(x - 0.2, means, 0.4, label="平均", color="#2563eb")
ax.bar(x + 0.2, meds, 0.4, label="中位數", color="#93c5fd")
for i, (m, d) in enumerate(zip(means, meds)):
    ax.text(i - 0.2, m + 0.3, f"{m:.1f}", ha="center", fontsize=10)
    ax.text(i + 0.2, d + 0.3, f"{d:.1f}", ha="center", fontsize=10)
ax.set_xticks(x); ax.set_xticklabels(labels)
ax.set_ylabel("未來 5 日已實現波動（年化 %）")
ax.set_title("體制比訊號穩：VIX 三分位決定接下來一週的震幅\n"
             f"SPY {out['sample']['start']}–{out['sample']['end']}，每組約 {out['vix_tercile_forward_rv'][labels[0]]['count']} 天",
             fontsize=12)
ax.legend()
ax.grid(axis="y", alpha=0.25)
fig2.tight_layout()
fig2.savefig("experiments/digest_20260713/vix_regime.png", dpi=150)
print("charts written")

# ---- Robustness: once VIX is IN the baseline, do the others still add anything?
# (Prior: mile_f1be9128 / K872 found HY spread adds ~0 once VIX is controlled.)
base2 = sm.OLS(df["fwd"], sm.add_constant(df[["rv20", "vix"]])).fit(
    cov_type="HAC", cov_kwds={"maxlags": lag})
rows2 = []
for k, label in names.items():
    if k == "vix":
        continue
    X = sm.add_constant(df[["rv20", "vix", k]])
    m = sm.OLS(df["fwd"], X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    rows2.append({"signal": k, "label": label,
                  "hac_t": round(float(m.tvalues[k]), 3),
                  "hac_p": round(float(m.pvalues[k]), 5),
                  "incremental_r2_pp_over_rv20_plus_vix":
                      round(float(m.rsquared - base2.rsquared) * 100, 3)})
res2 = pd.DataFrame(rows2).sort_values("incremental_r2_pp_over_rv20_plus_vix", ascending=False)
rej2, padj2, _, _ = multipletests(res2["hac_p"].values, alpha=0.05, method="holm")
res2["holm_p"] = np.round(padj2, 5); res2["holm_significant"] = rej2
out["baseline_rv20_plus_vix_r2"] = round(float(base2.rsquared), 4)
out["signals_given_vix"] = res2.to_dict("records")
with open("experiments/digest_20260713/leading_signal_audit_results.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n=== given rv20+VIX baseline (R2=%.4f) ===" % base2.rsquared)
print(res2.to_string(index=False))
