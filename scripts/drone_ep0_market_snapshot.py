#!/usr/bin/env python3
"""台灣無人載具產業 EP0 — 上市櫃名冊的市場截面統計 + 圖表。

資料源：yfinance（真抓真算）。名冊來自
storage/pending_series/taiwan_drone_series_ep0_research.md（代碼與板別已逐檔 live 驗證）。

輸出：
  storage/drafts/assets/drone_ep0_risk_return.png     — 風險/報酬散佈（名冊 vs 加權指數）
  storage/drafts/assets/drone_ep0_basket_vs_twii.png  — 等權籃 vs 加權指數 累積報酬 + 滾動波動
  storage/drafts/assets/drone_ep0_market_cap.png      — 市值分佈（依產業鏈層級）
  storage/drafts/drone_ep0_market_snapshot.json       — 所有引用數字（可複現）

用法：
  uv run python scripts/drone_ep0_market_snapshot.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "storage" / "drafts" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

# CJK font (macOS)
for cand in ["Heiti TC", "PingFang TC", "Arial Unicode MS", "Songti TC"]:
    if any(cand == f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = cand
        break
plt.rcParams["axes.unicode_minus"] = False

# (name, ticker, tier, confidence) — tier: 上游 / 中游 / 下游
ROSTER: list[tuple[str, str, str, str]] = [
    ("雷虎", "8033.TW", "下游", "高"),
    ("漢翔", "2634.TW", "下游", "高"),
    ("亞航", "2630.TW", "下游", "高"),
    ("長榮航太", "2645.TW", "下游", "高"),
    ("中光電", "5371.TWO", "下游", "高"),
    ("碳基", "7719.TWO", "中游", "高"),
    ("龍德造船", "6753.TW", "下游", "高"),
    ("台船", "2208.TW", "下游", "中高"),
    ("中信造船", "2644.TWO", "下游", "中高"),
    ("千附精密", "6829.TWO", "上游", "高"),
    ("全訊", "5222.TW", "上游", "高"),
    ("寶一", "8222.TW", "上游", "高"),
    ("晟田", "4541.TWO", "上游", "高"),
    ("永虹先進", "6618.TWO", "中游", "中高"),
    ("亞光", "3019.TW", "上游", "中高"),
    ("邑錡", "7402.TWO", "上游", "中"),
    ("加百裕", "3323.TWO", "中游", "中高"),
    ("系統電", "5309.TWO", "中游", "中"),
    ("力山", "1515.TW", "中游", "中"),
    ("富田", "4590.TW", "中游", "中"),
    ("神基", "3005.TW", "下游", "中"),
    ("融程電", "3416.TW", "下游", "中"),
    ("合勤控", "3704.TW", "上游", "中"),
    ("立積", "4968.TW", "上游", "中"),
    ("昇達科", "3491.TWO", "上游", "中"),
    ("義隆", "2458.TW", "上游", "中"),
    ("新唐", "4919.TW", "上游", "中"),
    ("聯發科", "2454.TW", "上游", "低"),
    ("聯詠", "3034.TW", "上游", "低"),
]
BENCH = "^TWII"

TIER_COLOR = {"上游": "#4C78A8", "中游": "#F58518", "下游": "#54A24B"}


def main() -> None:
    tickers = [t for _, t, _, _ in ROSTER]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=400)

    raw = yf.download(
        tickers + [BENCH],
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        group_by="column",
    )
    px = raw["Close"].dropna(how="all")
    # 只取最近 252 個交易日（約一年）
    px = px.tail(252)

    rows = []
    for name, tkr, tier, conf in ROSTER:
        if tkr not in px.columns:
            continue
        s = px[tkr].dropna()
        if len(s) < 200:
            print(f"[skip] {name} {tkr}: 樣本僅 {len(s)} 日")
            continue
        ret_1y = float(s.iloc[-1] / s.iloc[0] - 1.0)
        logret = np.log(s / s.shift(1)).dropna()
        vol = float(logret.std(ddof=1) * np.sqrt(252))
        try:
            fi = yf.Ticker(tkr).fast_info
            shares = fi.get("shares") or 0
            last = float(fi.get("last_price") or s.iloc[-1])
            mcap = (shares * last) / 1e8 if shares else float("nan")  # 億元
        except Exception:
            mcap = float("nan")
        rows.append(
            dict(name=name, ticker=tkr, tier=tier, confidence=conf,
                 ret_1y=ret_1y, vol_ann=vol, mcap_e8=mcap,
                 last_close=float(s.iloc[-1]), n_obs=len(s))
        )

    df = pd.DataFrame(rows)

    b = px[BENCH].dropna().tail(len(px))
    b_ret = float(b.iloc[-1] / b.iloc[0] - 1.0)
    b_logret = np.log(b / b.shift(1)).dropna()
    b_vol = float(b_logret.std(ddof=1) * np.sqrt(252))

    # 等權籃（每日等權重報酬平均，無再平衡成本，僅作截面描述）
    sub = px[[r["ticker"] for r in rows]].dropna(how="all")
    daily = sub.pct_change().dropna(how="all")
    basket = daily.mean(axis=1)
    # 對齊：指數與個股的交易日偶有落差（yfinance ^TWII 更新較慢），取交集比較
    common = basket.index.intersection(b.index)
    basket = basket.loc[common]
    basket_cum = (1 + basket).cumprod()
    basket_ret = float(basket_cum.iloc[-1] - 1.0)
    basket_vol = float(np.log1p(basket).std(ddof=1) * np.sqrt(252))
    bench_cum = b.loc[common] / b.loc[common].iloc[0]

    snap = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        data_source="yfinance (auto_adjust=True)",
        window=dict(start=str(px.index[0].date()), end=str(px.index[-1].date()),
                    trading_days=int(len(px))),
        benchmark=dict(ticker=BENCH, ret_1y=b_ret, vol_ann=b_vol),
        basket=dict(construction="等權、每日重設權重、無交易成本",
                    n_names=len(rows), ret_1y=basket_ret, vol_ann=basket_vol,
                    vol_ratio_vs_bench=basket_vol / b_vol,
                    excess_ret_vs_bench=basket_ret - b_ret),
        tier_stats={
            t: dict(n=int(g.shape[0]),
                    median_ret_1y=float(g.ret_1y.median()),
                    median_vol_ann=float(g.vol_ann.median()),
                    median_mcap_e8=float(g.mcap_e8.median()))
            for t, g in df.groupby("tier")
        },
        confidence_stats={
            c: dict(n=int(g.shape[0]),
                    median_ret_1y=float(g.ret_1y.median()),
                    median_vol_ann=float(g.vol_ann.median()))
            for c, g in df.groupby("confidence")
        },
        n_beat_bench=int((df.ret_1y > b_ret).sum()),
        n_vol_above_bench=int((df.vol_ann > b_vol).sum()),
        total_mcap_e8=float(df.mcap_e8.sum()),
        names=df.sort_values("ret_1y", ascending=False).to_dict("records"),
    )
    out_json = ROOT / "storage" / "drafts" / "drone_ep0_market_snapshot.json"
    out_json.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in snap.items() if k != "names"},
                     ensure_ascii=False, indent=2))

    # ── Fig 1: 風險/報酬散佈 ───────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 6.5), dpi=150)
    for tier, g in df.groupby("tier"):
        ax.scatter(g.vol_ann * 100, g.ret_1y * 100, s=70, alpha=.85,
                   color=TIER_COLOR[tier], label=f"{tier}（{len(g)} 家）",
                   edgecolor="white", linewidth=.8)
    for _, r in df.iterrows():
        ax.annotate(r["name"], (r.vol_ann * 100, r.ret_1y * 100),
                    fontsize=7.5, xytext=(4, 3), textcoords="offset points",
                    color="#333")
    ax.scatter([b_vol * 100], [b_ret * 100], marker="*", s=420, color="#E45756",
               edgecolor="white", zorder=5, label="加權指數 ^TWII")
    ax.axhline(b_ret * 100, color="#E45756", lw=.9, ls="--", alpha=.6)
    ax.axvline(b_vol * 100, color="#E45756", lw=.9, ls="--", alpha=.6)
    ax.set_xlabel("年化波動率（%，近 252 個交易日對數報酬）")
    ax.set_ylabel("近一年報酬（%，還原除權息）")
    ax.set_title(f"台灣無人載具名冊 29 檔：風險與報酬座標\n"
                 f"樣本 {snap['window']['start']} ~ {snap['window']['end']}｜資料源 yfinance",
                 fontsize=12)
    ax.legend(loc="upper left", fontsize=9, frameon=True)
    ax.grid(alpha=.25, lw=.6)
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep0_risk_return.png")
    plt.close(fig)

    # ── Fig 2: 等權籃 vs 指數 ─────────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7.5), dpi=150,
                                   sharex=True, height_ratios=[2, 1])
    ax1.plot(basket_cum.index, (basket_cum - 1) * 100, lw=2, color="#4C78A8",
             label=f"無人載具等權籃（{len(rows)} 檔）")
    ax1.plot(bench_cum.index, (bench_cum - 1) * 100, lw=2, color="#E45756",
             label="加權指數 ^TWII")
    ax1.axhline(0, color="#888", lw=.8)
    ax1.set_ylabel("累積報酬（%）")
    ax1.set_title("無人載具等權籃 vs 台股加權指數（近一年）\n"
                  "等權、每日重設權重、未計交易成本；資料源 yfinance",
                  fontsize=12)
    ax1.legend(fontsize=9)
    ax1.grid(alpha=.25, lw=.6)

    roll_b = np.log1p(basket).rolling(21).std(ddof=1) * np.sqrt(252) * 100
    roll_x = b_logret.reindex(basket.index).rolling(21).std(ddof=1) * np.sqrt(252) * 100
    ax2.plot(roll_b.index, roll_b, lw=1.5, color="#4C78A8", label="等權籃")
    ax2.plot(roll_x.index, roll_x, lw=1.5, color="#E45756", label="加權指數")
    ax2.set_ylabel("21 日滾動\n年化波動率（%）")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=.25, lw=.6)
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep0_basket_vs_twii.png")
    plt.close(fig)

    # ── Fig 3: 市值分佈 ──────────────────────────────────────────────
    d = df.dropna(subset=["mcap_e8"]).sort_values("mcap_e8")
    fig, ax = plt.subplots(figsize=(9, 8), dpi=150)
    ax.barh(d.name, d.mcap_e8, color=[TIER_COLOR[t] for t in d.tier], alpha=.9)
    ax.set_xscale("log")
    ax.set_xlabel("市值（新台幣億元，對數刻度）")
    ax.set_title(f"名冊 {len(d)} 家的市值分佈（依產業鏈層級著色）\n"
                 f"資料源 yfinance fast_info，{snap['window']['end']}", fontsize=12)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in TIER_COLOR.values()]
    ax.legend(handles, TIER_COLOR.keys(), fontsize=9, loc="lower right")
    ax.grid(axis="x", alpha=.25, lw=.6)
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep0_market_cap.png")
    plt.close(fig)

    print(f"\n[ok] 3 charts -> {ASSETS}")
    print(f"[ok] snapshot -> {out_json}")


if __name__ == "__main__":
    main()
