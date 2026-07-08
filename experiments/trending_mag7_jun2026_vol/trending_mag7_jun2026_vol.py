"""
2026 年 6 月科技七巨頭回檔期間的波動率行為
Trending repost evidence package.

資料源：yfinance 日資料（Adj/Close，close-to-close）
期間：2026-01-01 ~ 2026-07-09（重點 5-7 月）
標的：QQQ + Mag7(AAPL MSFT NVDA GOOGL AMZN META TSLA) + ^VIX + ^VVIX

計算：
 (a) 2026-06 QQQ / Mag7 實際 peak-to-trough 回檔幅度（真實 %）
 (b) 回檔前 / 中 / 後三段年化 realized vol（20 日 rolling，close-to-close，×sqrt(252)）
 (c) VIX 回檔期間水位變化（真實點位）
 (d) Mag7 個股 realized vol 橫斷面離散度排序

無隨機程序（純描述統計）。無 lookahead：rolling RV 只用截至當日的過去報酬；
peak-to-trough 只用實際歷史收盤價。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# CJK 字型（macOS）：Arial Unicode MS 覆蓋繁中，避免圖上出現 tofu 方塊
matplotlib.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC",
                                          "Hiragino Sans GB", "STHeiti"]
matplotlib.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parent
START = "2026-01-01"
END = "2026-07-09"
MAG7 = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
TICKERS = ["QQQ"] + MAG7 + ["^VIX", "^VVIX"]
ANN = np.sqrt(252)


def fetch():
    raw = yf.download(TICKERS, start=START, end=END, auto_adjust=True,
                      progress=False)
    close = raw["Close"].copy()
    # yfinance 可能對抓不到的 ticker 整欄 NaN
    close = close.dropna(how="all")
    return close


def realized_vol(close_series, window=20):
    """年化 realized vol：20 日 rolling std of daily log return × sqrt(252)。
    只用過去報酬，無 lookahead。
    先對該檔自己的序列 dropna，避免多 ticker union index 的 NaN gap
    汙染 rolling window（NaN 在 window 內會讓整個 rolling std 變 NaN）。"""
    s = close_series.dropna()
    ret = np.log(s / s.shift(1))
    rv = ret.rolling(window).std() * ANN
    return rv * 100.0  # 百分比


def peak_to_trough(series, lo, hi):
    """在 [lo, hi] 期間找 peak，再找 peak 之後的 trough，算回檔 %。"""
    seg = series.loc[lo:hi].dropna()
    if seg.empty:
        return None
    peak_date = seg.idxmax()
    peak_val = seg.loc[peak_date]
    after = seg.loc[peak_date:]
    trough_date = after.idxmin()
    trough_val = after.loc[trough_date]
    dd = (trough_val / peak_val - 1.0) * 100.0
    return {
        "peak_date": str(peak_date.date()),
        "peak": round(float(peak_val), 2),
        "trough_date": str(trough_date.date()),
        "trough": round(float(trough_val), 2),
        "drawdown_pct": round(float(dd), 2),
    }


def main():
    close = fetch()
    have = [t for t in TICKERS if t in close.columns and close[t].notna().sum() > 20]
    missing = [t for t in TICKERS if t not in have]
    print("available:", have)
    print("missing:", missing)

    results = {
        "meta": {
            "data_source": "yfinance (auto_adjust=True, close-to-close)",
            "period": f"{START} ~ {END}",
            "tickers_requested": TICKERS,
            "tickers_available": have,
            "tickers_missing": missing,
            "rv_method": "20d rolling std of daily log return x sqrt(252), percent",
            "n_trading_days": int(close.shape[0]),
        }
    }

    # ---- (a) peak-to-trough 回檔（聚焦 2026-06；順帶看 5-7 月整段）----
    june_dd = {}
    wide_dd = {}
    for t in ["QQQ"] + MAG7:
        if t in have:
            june_dd[t] = peak_to_trough(close[t], "2026-06-01", "2026-06-30")
            wide_dd[t] = peak_to_trough(close[t], "2026-05-15", "2026-07-08")
    results["drawdown_june2026"] = june_dd
    results["drawdown_mid_may_to_jul"] = wide_dd

    # regime 切點：用 Mag7 共識而非單一 QQQ。多數 Mag7 個股 06-01 前後見高、
    # 06-25 見低（見 drawdown 表）；QQQ 指數本身 06-10 見低後陷入震盪（-7%），
    # 但個股回檔更深且集中 06-25 觸底，故以共識期間定義壓力段。
    qqq_dd = june_dd.get("QQQ")
    peak_date = pd.Timestamp("2026-06-01")
    trough_date = pd.Timestamp("2026-06-25")
    results["regime_note"] = (
        "regime cut points = Mag7 consensus: peak 2026-06-01, trough 2026-06-25. "
        "QQQ index bottomed earlier (2026-06-10, -7%) then chopped; single names "
        "fell deeper and bottomed 2026-06-25/26."
    )

    # ---- (b) 三段年化 realized vol ----
    # before: 回檔前約 20 交易日均值（peak 之前）
    # during: peak -> trough 壓力段均值
    # after: trough 之後至今均值
    rv_qqq = realized_vol(close["QQQ"]) if "QQQ" in have else None
    seg_defs = {
        "before_peak": (peak_date - pd.Timedelta(days=32), peak_date),
        "during_selloff": (peak_date, trough_date),
        "after_trough": (trough_date, pd.Timestamp(END)),
    }
    rv_segments = {}
    for t in ["QQQ"] + MAG7:
        if t not in have:
            continue
        rv = realized_vol(close[t])
        seg_vals = {}
        for name, (lo, hi) in seg_defs.items():
            v = rv.loc[lo:hi].dropna()
            seg_vals[name] = round(float(v.mean()), 2) if not v.empty else None
        rv_segments[t] = seg_vals
    results["realized_vol_segments"] = rv_segments
    results["segment_dates"] = {k: [str(v[0].date()), str(v[1].date())]
                                for k, v in seg_defs.items()}

    # ---- (c) VIX 水位變化 ----
    vix_info = {}
    if "^VIX" in have:
        vix = close["^VIX"]
        vix_pre = vix.loc[peak_date - pd.Timedelta(days=10):peak_date].dropna()
        vix_selloff = vix.loc[peak_date:trough_date].dropna()
        vix_now = vix.dropna()
        vix_info = {
            "level_at_peak": round(float(vix.loc[:peak_date].dropna().iloc[-1]), 2),
            "avg_before": round(float(vix_pre.mean()), 2) if not vix_pre.empty else None,
            "peak_during_selloff": round(float(vix_selloff.max()), 2) if not vix_selloff.empty else None,
            "peak_during_selloff_date": str(vix_selloff.idxmax().date()) if not vix_selloff.empty else None,
            "level_at_trough": round(float(vix.loc[:trough_date].dropna().iloc[-1]), 2),
            "latest": round(float(vix_now.iloc[-1]), 2),
            "latest_date": str(vix_now.index[-1].date()),
            "ytd_min": round(float(vix_now.min()), 2),
            "ytd_max": round(float(vix_now.max()), 2),
        }
    results["vix"] = vix_info

    vvix_info = {}
    if "^VVIX" in have:
        vvix = close["^VVIX"].dropna()
        vvix_selloff = vvix.loc[peak_date:trough_date]
        vvix_info = {
            "level_at_peak": round(float(vvix.loc[:peak_date].iloc[-1]), 2),
            "peak_during_selloff": round(float(vvix_selloff.max()), 2) if not vvix_selloff.empty else None,
            "latest": round(float(vvix.iloc[-1]), 2),
        }
    results["vvix"] = vvix_info

    # ---- (d) 橫斷面離散度：selloff 期間 realized vol 排序 ----
    cross = {}
    for t in MAG7:
        if t in rv_segments and rv_segments[t].get("during_selloff") is not None:
            cross[t] = rv_segments[t]["during_selloff"]
    cross_sorted = dict(sorted(cross.items(), key=lambda kv: kv[1], reverse=True))
    results["cross_section_rv_during_selloff"] = cross_sorted
    if cross_sorted:
        vals = list(cross_sorted.values())
        results["cross_section_stats"] = {
            "highest": {"ticker": list(cross_sorted)[0], "rv": vals[0]},
            "lowest": {"ticker": list(cross_sorted)[-1], "rv": vals[-1]},
            "spread": round(vals[0] - vals[-1], 2),
            "mean": round(float(np.mean(vals)), 2),
            "std_across_names": round(float(np.std(vals, ddof=1)), 2),
        }

    # ---- 圖 1：QQQ 價格 + 6 月回檔標註 ----
    if "QQQ" in have:
        fig, ax = plt.subplots(figsize=(10, 5))
        q = close["QQQ"].dropna()
        ax.plot(q.index, q.values, color="#1f4e79", lw=1.6, label="QQQ 收盤")
        if qqq_dd:
            ax.scatter([peak_date], [qqq_dd["peak"]], color="#c0392b", zorder=5, s=60)
            ax.scatter([trough_date], [qqq_dd["trough"]], color="#27ae60", zorder=5, s=60)
            ax.annotate(f"高點 {qqq_dd['peak']}\n{qqq_dd['peak_date']}",
                        (peak_date, qqq_dd["peak"]), textcoords="offset points",
                        xytext=(-10, 15), fontsize=9, color="#c0392b")
            ax.annotate(f"低點 {qqq_dd['trough']}\n{qqq_dd['trough_date']}\n({qqq_dd['drawdown_pct']}%)",
                        (trough_date, qqq_dd["trough"]), textcoords="offset points",
                        xytext=(10, -35), fontsize=9, color="#27ae60")
        ax.set_title("QQQ 2026 年走勢與 6 月回檔", fontsize=13)
        ax.set_ylabel("價格 (USD)")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(OUT / "fig1_qqq_drawdown.png", dpi=130)
        plt.close(fig)

    # ---- 圖 2：QQQ realized vol vs VIX 疊圖 ----
    if rv_qqq is not None and "^VIX" in have:
        fig, ax1 = plt.subplots(figsize=(10, 5))
        rvp = rv_qqq.dropna()
        ax1.plot(rvp.index, rvp.values, color="#8e44ad", lw=1.6,
                 label="QQQ 20 日已實現波動率 (年化 %)")
        ax1.set_ylabel("已實現波動率 (年化 %)", color="#8e44ad")
        ax1.tick_params(axis="y", labelcolor="#8e44ad")
        ax2 = ax1.twinx()
        vp = close["^VIX"].dropna()
        ax2.plot(vp.index, vp.values, color="#e67e22", lw=1.4, alpha=0.8,
                 label="VIX (右軸)")
        ax2.set_ylabel("VIX", color="#e67e22")
        ax2.tick_params(axis="y", labelcolor="#e67e22")
        ax1.axvspan(peak_date, trough_date, color="grey", alpha=0.15)
        ax1.set_title("QQQ 已實現波動率 vs VIX：6 月回檔區間灰底", fontsize=13)
        ax1.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(OUT / "fig2_rv_vs_vix.png", dpi=130)
        plt.close(fig)

    # ---- 圖 3：Mag7 橫斷面 selloff RV bar ----
    if cross_sorted:
        fig, ax = plt.subplots(figsize=(9, 5))
        names = list(cross_sorted.keys())
        vals = list(cross_sorted.values())
        colors = plt.cm.RdYlGn_r(np.linspace(0.2, 0.85, len(names)))
        ax.bar(names, vals, color=colors)
        for i, v in enumerate(vals):
            ax.text(i, v + 0.5, f"{v}", ha="center", fontsize=9)
        ax.set_title("科技七巨頭 6 月回檔期間已實現波動率排序 (年化 %)", fontsize=12)
        ax.set_ylabel("已實現波動率 (年化 %)")
        ax.grid(alpha=0.3, axis="y")
        fig.tight_layout()
        fig.savefig(OUT / "fig3_mag7_cross_section.png", dpi=130)
        plt.close(fig)

    with open(OUT / "trending_mag7_jun2026_vol_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
