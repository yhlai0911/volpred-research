#!/usr/bin/env python3
"""
台股代表性個股 / 產業相對估值篩選
============================================

目的
----
用「真實歷史 PER / PBR」衡量台股市值前 ~30 大代表股目前估值在自身近 5 年
分佈中的「相對位置（百分位）」，回答「哪些產業/個股目前位於自身歷史較低分位
（相對便宜）、哪些偏貴」。**只做相對估值位置的客觀描述 + value-trap 警示，
不喊買賣、不捏造目標價。**

資料來源（皆為真實數據）
------------------------
1. FinMind  TaiwanStockPER  (anonymous endpoint) — 各股每日 PER / PBR / 殖利率
   歷史序列。本研究取近 5 年（today-5y ~ today）作為「自身歷史分佈」。
   API: https://api.finmindtrade.com/api/v4/data  dataset=TaiwanStockPER
2. yfinance .info — 取 sector / industry / trailingPE / forwardPE / priceToBook
   作為「截面 / 同業比較」與 cross-check（與 FinMind 最新值對照）。

方法
----
A. 個股「自身歷史分位」：對每檔股票，取近 5 年 PER 與 PBR 日序列，計算
   「最新值」落在該分佈的百分位 (percentile rank)。
   - 分位 ≤ 25% → 相對自身歷史「便宜」帶
   - 分位 ≥ 75% → 相對自身歷史「偏貴」帶
   - 同時報 z-score（(x - mean)/std）作為偏離度補充。
B. 「同業中位數比較」：以 yfinance sector 分群，計算各 sector 內 PER / PBR
   中位數，標出各股相對其 sector 中位數是高是低（截面相對便宜/貴）。
C. 產業層級：對每個 sector 取「成分股自身歷史 PBR 分位的中位數」，描述
   哪個產業整體目前位於自身歷史較低分位。

誠實聲明 / 假設
---------------
- PER 受一次性損益、景氣循環高低點扭曲（cyclical 股低 PER 常是高點訊號 →
  value trap）；本研究 **PBR 為主、PER 為輔**，且明確標注 cyclical 警示。
- 「低分位 ≠ 保證上漲」：便宜可以更便宜（value trap）。歷史分佈不保證未來
  重演（regime change、產業結構改變、AI 重評價等）。
- FinMind PER/PBR 用「歷史 EPS / 淨值」計算，與 yfinance forwardPE（前瞻）
  口徑不同，數值會有差異，屬正常；本研究 cross-check 只看「方向一致性」。
- 近 5 年窗含 2021 多頭高點 + 2022 空頭 + 2023-25 AI 行情，分佈跨越牛熊，
  較不會只反映單一 regime；但仍非「永久常態」。

無 lookahead：所有分位/中位數計算只用到 <= 最新可得交易日 (2026-06-18) 的資料。
隨機種子：本研究為 deterministic 統計分位，無隨機程序；仍記錄 SEED=42 以符規範。

Run:  uv run python valuation.py
Out:  valuation_results.json  +  valuation_percentile.png / sector_heatmap.png
"""
from __future__ import annotations
import json
import time
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import warnings

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)  # deterministic 統計，無隨機程序；記錄以符規範

HERE = Path(__file__).resolve().parent
TODAY = dt.date(2026, 6, 19)               # 任務指定「今天」
HIST_START = (TODAY - dt.timedelta(days=365 * 5 + 5)).isoformat()  # 近 5 年
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# ── 代表性籃子：市值前 ~30 大，跨產業（含任務點名的個股）──────────────
#   sector_hint 只作為 fallback 中文標籤；正式 sector 以 yfinance .info 為準
BASKET = {
    "2330": "台積電",   "2454": "聯發科",  "2317": "鴻海",    "2308": "台達電",
    "2382": "廣達",     "3711": "日月光投控","2891": "中信金",  "2881": "富邦金",
    "2882": "國泰金",   "2886": "兆豐金",   "2884": "玉山金",  "2412": "中華電",
    "3045": "台灣大",   "2603": "長榮",     "2615": "萬海",    "1216": "統一",
    "2912": "統一超",   "1303": "南亞",     "1301": "台塑",    "2002": "中鋼",
    "2207": "和泰車",   "2357": "華碩",     "3034": "聯詠",    "2379": "瑞昱",
    "2345": "智邦",     "3008": "大立光",   "2880": "華南金",  "2885": "元大金",
    "5880": "合庫金",   "2890": "永豐金",
}


# ─────────────────────────────────────────────────────────────────────
def fetch_finmind_per(stock_id: str, start: str, end: str,
                      retries: int = 3) -> pd.DataFrame:
    """FinMind TaiwanStockPER 真實歷史 PER/PBR/殖利率序列 (anonymous)."""
    params = {"dataset": "TaiwanStockPER", "data_id": stock_id,
              "start_date": start, "end_date": end}
    for k in range(retries):
        try:
            r = requests.get(FINMIND_URL, params=params, timeout=40)
            if r.status_code == 200:
                d = r.json().get("data", [])
                if d:
                    df = pd.DataFrame(d)
                    df["date"] = pd.to_datetime(df["date"])
                    return df.sort_values("date").reset_index(drop=True)
                return pd.DataFrame()
            # 402 = quota，429 = rate limit
            time.sleep(2 + k * 2)
        except Exception:
            time.sleep(2 + k * 2)
    return pd.DataFrame()


def fetch_yf_info(stock_id: str, retries: int = 2) -> dict:
    """yfinance .info — sector / forwardPE / cross-check 用。失敗回 {}。"""
    import yfinance as yf
    for k in range(retries):
        try:
            info = yf.Ticker(f"{stock_id}.TW").info
            if info and info.get("sector"):
                return info
        except Exception:
            time.sleep(1.5)
    return {}


def pct_rank(series: pd.Series, value: float) -> float:
    """value 在 series 分佈的百分位 (0-100)。無 lookahead：series 只含歷史。"""
    s = series.dropna()
    s = s[(s > 0) & np.isfinite(s)]
    if len(s) < 30 or value is None or not np.isfinite(value):
        return float("nan")
    return float((s < value).mean() * 100.0)


def zscore(series: pd.Series, value: float) -> float:
    s = series.dropna()
    s = s[(s > 0) & np.isfinite(s)]
    if len(s) < 30 or value is None or not np.isfinite(value):
        return float("nan")
    mu, sd = s.mean(), s.std(ddof=1)
    if sd == 0 or not np.isfinite(sd):
        return float("nan")
    return float((value - mu) / sd)


# ── value-trap 高風險產業（cyclical / 結構性逆風）標記規則 ──────────────
CYCLICAL_SECTORS = {"Basic Materials", "Industrials", "Energy"}
# 航運（長榮/萬海）、塑化（台塑/南亞）、鋼鐵（中鋼）= 強景氣循環
CYCLICAL_IDS = {"2603", "2615", "1303", "1301", "2002"}


def build():
    print(f"[i] HIST window: {HIST_START} ~ {TODAY.isoformat()} (近5年)")
    rows = []
    for i, (sid, zh) in enumerate(BASKET.items(), 1):
        print(f"  [{i:>2}/{len(BASKET)}] {sid} {zh} ...", end=" ", flush=True)
        df = fetch_finmind_per(sid, HIST_START, TODAY.isoformat())
        info = fetch_yf_info(sid)
        time.sleep(0.35)  # 對 anonymous endpoint 客氣

        if df.empty:
            print("FinMind 無資料 → skip")
            continue

        # 最新可得交易日（無 lookahead：FinMind 不會給未來資料）
        last = df.iloc[-1]
        last_date = last["date"].date().isoformat()
        per_now = float(last["PER"]) if pd.notna(last["PER"]) else None
        pbr_now = float(last["PBR"]) if pd.notna(last["PBR"]) else None
        dy_now = float(last["dividend_yield"]) if pd.notna(last["dividend_yield"]) else None

        # FinMind 對「虧損/EPS<=0」公司回傳 PER=0.0 → PER 無意義，視為 None
        # 並標 loss/PER-undefined flag（深景氣循環 / 獲利谷底訊號）
        per_undefined = (per_now is not None and per_now <= 0)
        if per_undefined:
            per_now = None

        per_pct = pct_rank(df["PER"], per_now)
        pbr_pct = pct_rank(df["PBR"], pbr_now)
        per_z = zscore(df["PER"], per_now)
        pbr_z = zscore(df["PBR"], pbr_now)

        sector = info.get("sector") or "Unknown"
        industry = info.get("industry") or "Unknown"
        fwd_pe = info.get("forwardPE")
        yf_pb = info.get("priceToBook")
        yf_tpe = info.get("trailingPE")

        n = int(df["PBR"].dropna().shape[0])
        hist_first = df["date"].iloc[0].date().isoformat()

        cyclical = (sid in CYCLICAL_IDS) or (sector in CYCLICAL_SECTORS)

        # PER 歷史統計：剔除 <=0（虧損日）才有意義
        per_pos = df["PER"][df["PER"] > 0]
        per_stat_n = int(per_pos.dropna().shape[0])

        rows.append({
            "stock_id": sid, "name_zh": zh,
            "sector": sector, "industry": industry,
            "last_date": last_date, "n_obs_5y": n, "hist_first": hist_first,
            "PER_now": per_now, "PBR_now": pbr_now, "dividend_yield_now": dy_now,
            "PER_pct_5y": round(per_pct, 1) if np.isfinite(per_pct) else None,
            "PBR_pct_5y": round(pbr_pct, 1) if np.isfinite(pbr_pct) else None,
            "PER_z_5y": round(per_z, 2) if np.isfinite(per_z) else None,
            "PBR_z_5y": round(pbr_z, 2) if np.isfinite(pbr_z) else None,
            "PER_undefined_loss": bool(per_undefined),
            "PER_5y_min": round(float(per_pos.min()), 2) if per_stat_n else None,
            "PER_5y_median": round(float(per_pos.median()), 2) if per_stat_n else None,
            "PER_5y_max": round(float(per_pos.max()), 2) if per_stat_n else None,
            "PBR_5y_min": round(float(df["PBR"].min()), 2),
            "PBR_5y_median": round(float(df["PBR"].median()), 2),
            "PBR_5y_max": round(float(df["PBR"].max()), 2),
            "yf_forwardPE": round(float(fwd_pe), 2) if fwd_pe else None,
            "yf_trailingPE": round(float(yf_tpe), 2) if yf_tpe else None,
            "yf_priceToBook": round(float(yf_pb), 2) if yf_pb else None,
            "is_cyclical_valuetrap_flag": cyclical,
        })
        print(f"PER {per_now} (p{per_pct:.0f}) PBR {pbr_now} (p{pbr_pct:.0f}) [{sector}]")

    res = pd.DataFrame(rows)

    # ── 截面同業中位數比較 ────────────────────────────────────────────
    sector_stats = {}
    for sec, g in res.groupby("sector"):
        sector_stats[sec] = {
            "n": int(len(g)),
            "PER_now_median": round(float(g["PER_now"].median()), 2),
            "PBR_now_median": round(float(g["PBR_now"].median()), 2),
            # 產業整體歷史分位：成分股 PBR 自身歷史分位的中位數
            "PBR_pct_5y_median": round(float(g["PBR_pct_5y"].median()), 1),
            "PER_pct_5y_median": round(float(g["PER_pct_5y"].median()), 1),
            "members": g["stock_id"].tolist(),
        }
    # 各股相對 sector 中位數
    res["PBR_vs_sector_med"] = res.apply(
        lambda r: round(r["PBR_now"] / sector_stats[r["sector"]]["PBR_now_median"], 2)
        if sector_stats[r["sector"]]["PBR_now_median"] else None, axis=1)
    res["PER_vs_sector_med"] = res.apply(
        lambda r: round(r["PER_now"] / sector_stats[r["sector"]]["PER_now_median"], 2)
        if sector_stats[r["sector"]]["PER_now_median"] else None, axis=1)

    # ── 分類 ──────────────────────────────────────────────────────────
    def classify(r):
        p = r["PBR_pct_5y"]
        if p is None or not np.isfinite(p):
            return "no_data"
        if p <= 25:
            return "cheap_vs_own_history"        # 相對自身歷史低分位
        if p >= 75:
            return "expensive_vs_own_history"     # 相對自身歷史高分位
        return "mid_range"
    res["valuation_zone"] = res.apply(classify, axis=1)

    cheap = res[res["valuation_zone"] == "cheap_vs_own_history"].sort_values("PBR_pct_5y")
    expensive = res[res["valuation_zone"] == "expensive_vs_own_history"].sort_values("PBR_pct_5y", ascending=False)

    # ── 輸出 JSON ─────────────────────────────────────────────────────
    out = {
        "experiment_id": "k_taiex_60k_scenario_20260619/valuation",
        "title": "台股代表股相對估值篩選（自身歷史分位 + 同業中位數）",
        "generated_at_taipei": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "as_of_date": TODAY.isoformat(),
        "data_latest_trading_day": res["last_date"].max() if len(res) else None,
        "hist_window": f"{HIST_START} ~ {TODAY.isoformat()} (近5年)",
        "seed": SEED,
        "n_stocks": int(len(res)),
        "data_sources": {
            "historical_per_pbr": "FinMind TaiwanStockPER (anonymous endpoint), 真實每日歷史 PER/PBR/殖利率",
            "sector_and_forward_pe": "yfinance .info (sector/industry/forwardPE/priceToBook cross-check)",
        },
        "method": "對每檔股票取近5年 PER/PBR 日序列，計算最新值的歷史百分位(percentile rank)與 z-score；PBR≤p25=相對自身歷史便宜帶、≥p75=偏貴帶。截面以 yfinance sector 分群比較同業中位數。產業層級取成分股 PBR 自身歷史分位中位數。",
        "honesty_notes": [
            "PBR 為主、PER 為輔（PER 受一次性損益與景氣循環高低點扭曲）。",
            "低分位 ≠ 保證上漲；便宜可以更便宜 (value trap)。歷史分佈不保證未來重演。",
            "cyclical 股（航運/塑化/鋼鐵）低 PER 常出現在獲利高點 → 反向訊號，已標 flag。",
            "FinMind PER/PBR(歷史 EPS/淨值) 與 yfinance forwardPE(前瞻) 口徑不同，cross-check 只看方向。",
            "近5年窗跨 2021 多頭高點 + 2022 空頭 + 2023-25 AI 行情，較不偏單一 regime。",
            "本研究只描述相對估值位置 + 風險警示，不喊買賣、不給目標價。",
            "無 lookahead：所有計算僅用到最新可得交易日資料。無隨機程序，seed=42 僅為合規記錄。",
        ],
        "sector_stats": sector_stats,
        "cheap_vs_own_history": cheap[[
            "stock_id", "name_zh", "sector", "PBR_now", "PBR_pct_5y", "PBR_z_5y",
            "PER_now", "PER_pct_5y", "dividend_yield_now", "is_cyclical_valuetrap_flag",
            "PBR_5y_median", "PBR_vs_sector_med"]].to_dict("records"),
        "expensive_vs_own_history": expensive[[
            "stock_id", "name_zh", "sector", "PBR_now", "PBR_pct_5y", "PBR_z_5y",
            "PER_now", "PER_pct_5y", "is_cyclical_valuetrap_flag"]].to_dict("records"),
        "all_stocks": res.sort_values("PBR_pct_5y").to_dict("records"),
    }
    (HERE / "valuation_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ok] wrote valuation_results.json  ({len(res)} stocks)")

    # ── 圖 1：個股 PBR 自身歷史分位 ranking bar ───────────────────────
    plot_df = res.dropna(subset=["PBR_pct_5y"]).sort_values("PBR_pct_5y")
    fig, ax = plt.subplots(figsize=(11, 10))
    colors = []
    for _, r in plot_df.iterrows():
        if r["PBR_pct_5y"] <= 25:
            colors.append("#2e8b57" if not r["is_cyclical_valuetrap_flag"] else "#c98a00")
        elif r["PBR_pct_5y"] >= 75:
            colors.append("#c0392b")
        else:
            colors.append("#7f8c8d")
    labels = [f"{r['name_zh']}({r['stock_id']})" for _, r in plot_df.iterrows()]
    ax.barh(labels, plot_df["PBR_pct_5y"], color=colors)
    ax.axvline(25, ls="--", color="green", lw=1, alpha=0.7)
    ax.axvline(75, ls="--", color="red", lw=1, alpha=0.7)
    ax.axvline(50, ls=":", color="gray", lw=1, alpha=0.5)
    ax.set_xlabel("PBR 在自身近5年分佈的百分位 (%)  ← 低=相對便宜  高=相對貴 →")
    ax.set_title("台股代表股：目前 PBR 相對自身近5年歷史的位置\n"
                 "(綠=低分位 非循環 / 橙=低分位但循環股 value-trap警示 / 紅=高分位)\n"
                 f"資料: FinMind 真實歷史 PBR, as-of {res['last_date'].max()}", fontsize=11)
    ax.set_xlim(0, 100)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    plt.tight_layout()
    fig.savefig(HERE / "valuation_percentile.png", dpi=130)
    plt.close(fig)
    print("[ok] wrote valuation_percentile.png")

    # ── 圖 2：產業層級 PBR 歷史分位中位數 ─────────────────────────────
    sec_df = pd.DataFrame([
        {"sector": s, "PBR_pct_5y_median": v["PBR_pct_5y_median"],
         "PER_pct_5y_median": v["PER_pct_5y_median"], "n": v["n"]}
        for s, v in sector_stats.items() if v["n"] >= 1
    ]).sort_values("PBR_pct_5y_median")
    fig, ax = plt.subplots(figsize=(10, 6))
    scolors = ["#2e8b57" if v <= 35 else "#c0392b" if v >= 65 else "#7f8c8d"
               for v in sec_df["PBR_pct_5y_median"]]
    ax.barh([f"{s} (n={n})" for s, n in zip(sec_df["sector"], sec_df["n"])],
            sec_df["PBR_pct_5y_median"], color=scolors)
    ax.axvline(50, ls=":", color="gray", lw=1)
    ax.set_xlabel("產業內成分股『PBR 自身近5年分位』之中位數 (%)")
    ax.set_title("產業層級相對估值位置（越低=該產業整體越靠近自身歷史低檔）\n"
                 f"資料: FinMind 真實歷史 PBR, as-of {res['last_date'].max()}", fontsize=11)
    ax.set_xlim(0, 100)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    plt.tight_layout()
    fig.savefig(HERE / "sector_heatmap.png", dpi=130)
    plt.close(fig)
    print("[ok] wrote sector_heatmap.png")

    return out


if __name__ == "__main__":
    build()
