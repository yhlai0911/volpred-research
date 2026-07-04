"""
Daily vol snapshot 2026-07-04 — 美台隱含波動率背離
NFP (2026-07-02) 只作時間錨；主軸 = 台股創高但台指 VIX 高掛 vs 美 VIX 壓縮的 cross-market 背離。

資料來源:
  - VIXTWN (台指 VIX): data/vixtwn/vixtwn_daily.csv (2025-12-01 起, TAIFEX)
  - VIX / VXN / SPY / ^GSPC / ^TWII: yfinance (auto_adjust=False)
輸出: results.json + figs/*.png
研究誠實: 全部實算, VIXTWN 窗口僅 ~7 個月 (誠實標註); VIX vs VIXTWN 標的不同, 以 ratio + 趨勢背離為主論述, 非絕對水準可比。
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

HERE = Path(__file__).parent
FIGS = HERE / "figs"
FIGS.mkdir(exist_ok=True)

# ---- 1. Load VIXTWN ----
vt = pd.read_csv(HERE.parent.parent / "data/vixtwn/vixtwn_daily.csv", parse_dates=["date"])
vt = vt.rename(columns={"date": "Date", "vixtwn_close": "VIXTWN"})[["Date", "VIXTWN"]].set_index("Date")

# ---- 2. yfinance ----
start = "2025-12-01"
end = "2026-07-05"
def dl(t):
    d = yf.download(t, start=start, end=end, progress=False, auto_adjust=False)
    c = d["Close"]
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    return c.rename(t)

vix = dl("^VIX")
vxn = dl("^VXN")
spy = dl("SPY")
gspc = dl("^GSPC")
twii = dl("^TWII")

# ---- 3. Align US VIX vs TW VIX ----
df = pd.concat([vix.rename("VIX"), vt["VIXTWN"], twii.rename("TWII")], axis=1)
df = df.sort_index()
df["VIXTWN"] = df["VIXTWN"].ffill(limit=1)  # 台美假日錯開, 最多補1日
gap = (df["VIXTWN"] - df["VIX"]).dropna()
ratio = (df["VIXTWN"] / df["VIX"]).dropna()

cur_gap = float(gap.iloc[-1])
cur_ratio = float(ratio.iloc[-1])
gap_pct = float((gap <= cur_gap).mean() * 100)      # 當前 gap 在窗口內百分位
ratio_pct = float((ratio <= cur_ratio).mean() * 100)

# ---- 4. Realized vol (20d annualized), TW & US, vs implied (VRP proxy) ----
def rv20(px):
    r = np.log(px / px.shift(1)).dropna()
    return (r.rolling(20).std() * np.sqrt(252) * 100).dropna()

tw_rv = rv20(twii)
us_rv = rv20(spy)
cur_tw_rv = float(tw_rv.iloc[-1])
cur_us_rv = float(us_rv.iloc[-1])
cur_vixtwn = float(vt["VIXTWN"].dropna().iloc[-1])
vix_valid = vix.dropna()
cur_vix = float(vix_valid.iloc[-1])
tw_vrp = cur_vixtwn - cur_tw_rv   # 台指隱含 - 台股已實現
us_vrp = cur_vix - cur_us_rv      # 美 VIX 隱含 - 美股已實現

# ---- 5. VIX compression percentile (use valid series) ----
vix_pct = float((vix_valid <= cur_vix).mean() * 100)
vixtwn_pct = float((vt["VIXTWN"].dropna() <= cur_vixtwn).mean() * 100)

# ---- 5b. long TWII context: 47xxx 是否真為歷史高 ----
twii_long = dl("^TWII")  # 短窗口重取; 補抓 5y 判斷 all-time
try:
    d5 = yf.download("^TWII", period="5y", progress=False, auto_adjust=False)["Close"]
    if isinstance(d5, pd.DataFrame):
        d5 = d5.iloc[:, 0]
    twii_5y_max = round(float(d5.max()), 2)
    twii_5y_max_date = str(d5.idxmax().date())
except Exception:
    twii_5y_max = None; twii_5y_max_date = None

# ---- 6. NFP-day (7/2) reactions ----
def chg(s, d0, d1):
    try:
        a = float(s.loc[d0]); b = float(s.loc[d1])
        return round((b / a - 1) * 100, 2)
    except Exception:
        return None
def lvl(s, d):
    try:
        return round(float(s.loc[d]), 2)
    except Exception:
        return None

nfp = {
    "vix_0701": lvl(vix, "2026-07-01"), "vix_0702": lvl(vix, "2026-07-02"),
    "vix_chg_pct": chg(vix, "2026-07-01", "2026-07-02"),
    "spy_chg_pct": chg(spy, "2026-07-01", "2026-07-02"),
    "gspc_0701": lvl(gspc, "2026-07-01"), "gspc_0702": lvl(gspc, "2026-07-02"),
    "gspc_chg_pct": chg(gspc, "2026-07-01", "2026-07-02"),
    "twii_0702": lvl(twii, "2026-07-02"), "twii_0703": lvl(twii, "2026-07-03"),
    "twii_chg_0702_0703": chg(twii, "2026-07-02", "2026-07-03"),
    "vxn_0702": lvl(vxn, "2026-07-02"),
}

# TWII 一週漲幅 (6/26 -> 7/3)
twii_week = chg(twii, "2026-06-26", "2026-07-03")
twii_high = float(twii.max())
twii_high_date = str(twii.idxmax().date())
twii_last = float(twii.iloc[-1])
twii_last_date = str(twii.index[-1].date())

results = {
    "as_of": "2026-07-04",
    "window": {"start": start, "end": "2026-07-03", "vixtwn_history_from": "2025-12-01",
               "note": "VIXTWN 僅回溯 2025-12-01 (~7 個月); 百分位為近期 regime 內, 非長期"},
    "us_tw_divergence": {
        "vix_last": round(cur_vix, 2), "vix_last_date": str(vix_valid.index[-1].date()),
        "vixtwn_last": round(cur_vixtwn, 2), "vixtwn_last_date": str(vt["VIXTWN"].dropna().index[-1].date()),
        "gap": round(cur_gap, 2), "gap_percentile_in_window": round(gap_pct, 1),
        "ratio": round(cur_ratio, 2), "ratio_percentile_in_window": round(ratio_pct, 1),
        "vix_compression_percentile": round(vix_pct, 1),
        "vixtwn_percentile_in_window": round(vixtwn_pct, 1),
        "vxn_last": round(float(vxn.dropna().iloc[-1]), 2),
    },
    "vol_risk_premium": {
        "tw_vixtwn": round(cur_vixtwn, 2), "tw_realized_rv20": round(cur_tw_rv, 2),
        "tw_vrp": round(tw_vrp, 2),
        "us_vix": round(cur_vix, 2), "us_realized_rv20": round(cur_us_rv, 2),
        "us_vrp": round(us_vrp, 2),
        "note": "VRP = 隱含 - 已實現(20d年化). 台股高波動大半有 realized 支撐, 非純恐慌溢價",
    },
    "tw_price_vol_divergence": {
        "twii_high_window": round(twii_high, 2), "twii_high_window_date": twii_high_date,
        "twii_5y_max": twii_5y_max, "twii_5y_max_date": twii_5y_max_date,
        "twii_last": round(twii_last, 2), "twii_last_date": twii_last_date,
        "twii_pct_below_window_high": round((twii_last / twii_high - 1) * 100, 2),
        "twii_week_chg_pct_0626_0703": twii_week,
        "vixtwn_range_window": [round(float(vt['VIXTWN'].min()), 2), round(float(vt['VIXTWN'].max()), 2)],
    },
    "nfp_20260702": nfp,
}

(HERE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))

# ---- Charts ----
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
                     "font.sans-serif": ["Arial Unicode MS", "Heiti TC", "PingFang HK"],
                     "axes.unicode_minus": False})

# fig1: VIX vs VIXTWN
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.plot(df.index, df["VIX"], color="#2563eb", lw=1.8, label="美股 VIX")
ax.plot(vt.index, vt["VIXTWN"], color="#dc2626", lw=1.8, label="台指 VIX (VIXTWN)")
ax.axvline(pd.Timestamp("2026-07-02"), color="#666", ls="--", lw=1, alpha=0.7)
ax.text(pd.Timestamp("2026-07-02"), ax.get_ylim()[1]*0.96, " NFP", fontsize=9, color="#666")
ax.set_title("美台隱含波動率背離：台指 VIX 高掛、美 VIX 壓縮", fontsize=13, fontweight="bold")
ax.set_ylabel("波動率指數"); ax.legend(loc="upper left", framealpha=0.9)
fig.tight_layout(); fig.savefig(FIGS / "fig1_vix_vs_vixtwn.png", dpi=130); plt.close()

# fig2: TWII price vs VIXTWN
fig, ax1 = plt.subplots(figsize=(9, 4.5))
ax1.plot(twii.index, twii.values, color="#059669", lw=1.8, label="加權指數 (左軸)")
ax1.set_ylabel("加權指數", color="#059669")
ax2 = ax1.twinx()
ax2.plot(vt.index, vt["VIXTWN"], color="#dc2626", lw=1.5, alpha=0.8, label="台指 VIX (右軸)")
ax2.set_ylabel("台指 VIX", color="#dc2626")
ax1.set_title("台股創高，台指波動率卻不降反高", fontsize=13, fontweight="bold")
fig.tight_layout(); fig.savefig(FIGS / "fig2_twii_vs_vixtwn.png", dpi=130); plt.close()

# fig3: gap over window
fig, ax = plt.subplots(figsize=(9, 4))
ax.fill_between(gap.index, gap.values, color="#f59e0b", alpha=0.25)
ax.plot(gap.index, gap.values, color="#d97706", lw=1.6)
ax.axhline(cur_gap, color="#dc2626", ls=":", lw=1.2)
ax.set_title(f"台美 VIX 價差 (VIXTWN − VIX)，當前 {cur_gap:.1f} 點 (窗口第 {gap_pct:.0f} 百分位)",
             fontsize=12, fontweight="bold")
ax.set_ylabel("價差 (波動率點)")
fig.tight_layout(); fig.savefig(FIGS / "fig3_gap.png", dpi=130); plt.close()

print(json.dumps(results, ensure_ascii=False, indent=2))
