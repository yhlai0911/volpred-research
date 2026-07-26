"""K1801 — 紐約 PM2.5 十分位 vs 標普 500 後續已實現波動（讀者向描述性分析）。

定位
----
本實驗**不做新的預測宣稱**。K1587 已用正式 OOS 設計檢驗「落後 PM2.5 能否改善
SPY 波動預測」並判定 NULL。K1801 的唯一目的是把該結論轉成一般讀者看得懂的
描述統計與圖表，並讓文章引用的每一個數字都能回溯到可重跑的產物。

因此本檔只做三件事：
  1. 依前一日 PM2.5 / 前一日 VIX 各分十組，計算「之後五個交易日已實現波動」中位數
  2. 取 2023 年加拿大野火煙霧窗口做事件放大
  3. 輸出兩張中文圖 + results JSON（含文章實際採用的四捨五入顯示值）

資料來源（皆為 K1587 已提交的快取，不重新下載）
  - experiments/k1587/data/k1587_panel.csv
      · PM2.5：EPA AirData 參數 88101，紐約五郡日均，2018-2025
      · 市場：SPY 收盤、VIX 收盤（paper/garch-x-vix 資料集）

兩張圖用的是**兩種不同的時間對齊**，這裡寫清楚，因為它們回答的問題不同
（2026-07-26 Codex 審查 finding 1：原 docstring 誤稱全檔只用落後欄位）：

  Fig 1（十分位）— **預測式對齊**。分組變數用 `pm25_signal` / `vix_signal`，
    即 K1587 建面板時已 `.shift(1)` 的前一日值；被觀察量 `fwd_rv5` 是列 t 起算的
    五日已實現變異數（K1587 的 `fwd_rv1` 與同列 `rv1` 相等，故 `fwd_rv5` 覆蓋
    t..t+4）。因此這張圖問的是「昨天的空污能不能預告今天起的波動」，訊號嚴格
    落後於被預測窗口。

  Fig 2（野火事件）— **同期對齊**。柱狀用同日實測 `pm25_mean`，因為「六月七日
    紐約空氣有多髒」是關於當天空氣品質的事實陳述，用前一日值反而錯置；折線同樣
    是列 t 起算的五日波動，與柱狀在第 t 日重疊。這張圖是描述性事件對照，**不是**
    預測檢定，不可據以推論預測力。

預測層面的結論一律歸屬 K1587 的正式 OOS 檢驗（verdict=NULL），本檔不新增預測宣稱，
因此沒有訓練/測試切分，也沒有相應的洩漏面。

Seed: 不適用（無隨機程序）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from volpred.research.reproduce_spec import finalize_experiment

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style()

PANEL = REPO / "experiments/k1587/data/k1587_panel.csv"


def annualise_5d(v):
    """5 日已實現變異數 → 年化波動率（%）。"""
    return np.sqrt(v / 5.0 * 252.0) * 100.0


def main() -> int:
    started_at = time.time()
    p = pd.read_csv(PANEL)
    p["date"] = pd.to_datetime(p["date"])

    d = p.dropna(subset=["pm25_signal", "vix_signal", "fwd_rv5"]).copy()
    d["fwd_vol5"] = annualise_5d(d["fwd_rv5"])

    d["pm_dec"] = pd.qcut(d["pm25_signal"], 10, labels=False, duplicates="drop") + 1
    d["vix_dec"] = pd.qcut(d["vix_signal"], 10, labels=False, duplicates="drop") + 1

    pm_grp = d.groupby("pm_dec")["fwd_vol5"].median()
    vix_grp = d.groupby("vix_dec")["fwd_vol5"].median()
    pm_lvl = d.groupby("pm_dec")["pm25_signal"].median()
    vix_lvl = d.groupby("vix_dec")["vix_signal"].median()

    # ── Fig 1：兩把「風向球」的階梯對照 ──────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.4), sharey=True)

    ax = axes[0]
    ax.bar(pm_grp.index, pm_grp.values, color="#5d8aa8", width=0.72)
    ax.set_title("依前一日『紐約空污濃度』分成十組\n之後五個交易日的標普 500 波動（中位數）",
                 fontsize=12.5, pad=10)
    ax.set_xlabel("空污由低到高（第 1 組最乾淨、第 10 組最髒）", fontsize=10.5)
    ax.set_ylabel("之後五日已實現波動（年化 %）", fontsize=11)
    ax.set_xticks(range(1, 11))
    ax.grid(alpha=0.25, axis="y")
    ax.text(0.5, 0.94, "看不出往上爬的階梯", transform=ax.transAxes, ha="center",
            fontsize=12, color="#c0392b")

    ax = axes[1]
    ax.bar(vix_grp.index, vix_grp.values, color="#c0392b", width=0.72)
    ax.set_title("同一批交易日，改依前一日 VIX 分成十組\n之後五個交易日的標普 500 波動（中位數）",
                 fontsize=12.5, pad=10)
    ax.set_xlabel("VIX 由低到高（第 1 組最平靜、第 10 組最恐慌）", fontsize=10.5)
    ax.set_xticks(range(1, 11))
    ax.grid(alpha=0.25, axis="y")
    ax.text(0.5, 0.94, "階梯一路往上", transform=ax.transAxes, ha="center",
            fontsize=12, color="#1a5276")

    fig.text(0.5, 0.02,
             f"樣本：{len(d)} 個交易日（{d['date'].min().date()} ~ {d['date'].max().date()}）；"
             "空污為 EPA AirData 紐約五郡 PM2.5 日均，一律取前一日數值",
             ha="center", fontsize=9, color="#555")
    fig.tight_layout(rect=[0, 0.045, 1, 1])
    fig.savefig(HERE / "k1801_fig1_decile_ladder.png", dpi=150)
    plt.close(fig)

    # ── Fig 2：2023 加拿大野火煙霧事件 ───────────────────────────────
    ev = p[(p["date"] >= "2023-05-15") & (p["date"] <= "2023-07-14")].copy()
    ev["fwd_vol5"] = annualise_5d(ev["fwd_rv5"])
    peak = ev.loc[ev["pm25_mean"].idxmax()]

    fig, ax = plt.subplots(figsize=(13.2, 5.6))
    ax.bar(ev["date"], ev["pm25_mean"], color="#8d6e63", width=0.85)
    ax.set_ylabel("PM2.5 日均（µg/m³）", color="#6d4c41", fontsize=11)
    ax.tick_params(axis="y", labelcolor="#6d4c41")
    ax.set_ylim(0, ev["pm25_mean"].max() * 1.15)

    ax2 = ax.twinx()
    ax2.plot(ev["date"], ev["fwd_vol5"], color="#1a5276", lw=2.0, marker="o",
             markersize=3.2)
    ax2.set_ylabel("接下來五日已實現波動（年化 %）", color="#1a5276", fontsize=11)
    ax2.tick_params(axis="y", labelcolor="#1a5276")
    ax2.set_ylim(0, max(20, ev["fwd_vol5"].max() * 1.25))

    ax.annotate(f"{peak['date'].date()}\n煙霧最濃：{peak['pm25_mean']:.0f} µg/m³",
                xy=(peak["date"], peak["pm25_mean"]),
                xytext=(peak["date"] - pd.Timedelta(days=13), peak["pm25_mean"] * 0.92),
                fontsize=11, color="#6d4c41",
                arrowprops=dict(arrowstyle="->", color="#6d4c41", lw=1.4))

    ax.legend(handles=[ax.patches[0], ax2.get_lines()[0]],
              labels=["紐約五郡 PM2.5 日均（µg/m³）",
                      "接下來五個交易日的標普 500 波動（年化 %）"],
              loc="upper right", fontsize=10, framealpha=0.92)
    ax.set_title("2023 年加拿大野火煙霧籠罩紐約的那兩個月：空污爆表，市場波動沒跟著上去"
                 "（同期對照，非預測檢定）",
                 fontsize=13, pad=12)
    ax.grid(alpha=0.2, axis="y")

    fig.text(0.5, 0.015,
             "期間 2023-05-15 ~ 2023-07-14；資料來源：EPA AirData PM2.5、SPY 每日收盤",
             ha="center", fontsize=9, color="#555")
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(HERE / "k1801_fig2_wildfire_window.png", dpi=150)
    plt.close(fig)

    win = ev[(ev["date"] >= "2023-06-05") & (ev["date"] <= "2023-06-16")]

    pm_d1, pm_d10 = float(pm_grp.iloc[0]), float(pm_grp.iloc[-1])
    vix_d1, vix_d10 = float(vix_grp.iloc[0]), float(vix_grp.iloc[-1])
    pm_lvl_d1, pm_lvl_d10 = float(pm_lvl.iloc[0]), float(pm_lvl.iloc[-1])
    vix_lvl_d1, vix_lvl_d10 = float(vix_lvl.iloc[0]), float(vix_lvl.iloc[-1])
    sample_median = float(d["fwd_vol5"].median())
    win_median = float(win["fwd_vol5"].median())
    pm25_mean_signal = float(d["pm25_signal"].mean())
    peak_pm25 = float(peak["pm25_mean"])

    results = {
        "experiment_id": "K1801",
        "title": "紐約 PM2.5 十分位 vs 標普 500 後續已實現波動（讀者向描述性分析）",
        "scope": ("描述統計與圖表產生；不做預測宣稱。預測結論以 K1587 的 OOS "
                  "檢驗（verdict=NULL）為準。"),
        "parent_experiment": "K1587",
        "data": {
            "panel_path": "experiments/k1587/data/k1587_panel.csv",
            "pm25_source": ("EPA AirData 88101, NYC 5 counties "
                            "(Bronx/Kings/New York/Queens/Richmond)"),
            "market_source": "SPY / VIX daily close (paper/garch-x-vix dataset)",
            "target_column": "fwd_rv5",
            "target_transform": "sqrt(fwd_rv5 / 5 * 252) * 100  → 年化波動率 %",
            "target_window": "列 t 起算五個交易日（t..t+4）；K1587 的 fwd_rv1 等於同列 rv1",
            "alignment": {
                "decile_figure": {
                    "kind": "predictive",
                    "grouping_columns": ["pm25_signal", "vix_signal"],
                    "note": "分組變數為 shift(1) 後的前一日值，嚴格落後於被觀察窗口",
                },
                "wildfire_figure": {
                    "kind": "contemporaneous",
                    "pollution_column": "pm25_mean",
                    "note": ("同日實測值，因為『該日空氣有多髒』是當日事實陳述；"
                             "與 fwd_rv5 在第 t 日重疊，屬描述性事件對照，"
                             "不得據以推論預測力"),
                },
            },
        },
        "sample": {
            "rows": int(len(d)),
            "start": str(d["date"].min().date()),
            "end": str(d["date"].max().date()),
        },
        "decile_medians_fwd_vol5_pct": {
            "by_pm25": [round(v, 4) for v in pm_grp.tolist()],
            "by_vix": [round(v, 4) for v in vix_grp.tolist()],
        },
        "decile_median_levels": {
            "pm25_ugm3": [round(v, 4) for v in pm_lvl.tolist()],
            "vix": [round(v, 4) for v in vix_lvl.tolist()],
        },
        "headline": {
            "pm25_decile1_fwd_vol5_pct": round(pm_d1, 4),
            "pm25_decile10_fwd_vol5_pct": round(pm_d10, 4),
            "pm25_decile1_level_ugm3": round(pm_lvl_d1, 4),
            "pm25_decile10_level_ugm3": round(pm_lvl_d10, 4),
            "vix_decile1_fwd_vol5_pct": round(vix_d1, 4),
            "vix_decile10_fwd_vol5_pct": round(vix_d10, 4),
            "vix_decile1_level": round(vix_lvl_d1, 4),
            "vix_decile10_level": round(vix_lvl_d10, 4),
            "vix_d10_over_d1_ratio": round(vix_d10 / vix_d1, 4),
            "pm25_d10_minus_d1_pp": round(pm_d10 - pm_d1, 4),
            "sample_median_fwd_vol5_pct": round(sample_median, 4),
            "pm25_signal_mean_ugm3": round(pm25_mean_signal, 4),
        },
        "wildfire_event": {
            "window": ["2023-05-15", "2023-07-14"],
            "peak_date": str(peak["date"].date()),
            "peak_pm25_ugm3": round(peak_pm25, 4),
            "peak_over_sample_mean_ratio": round(peak_pm25 / pm25_mean_signal, 4),
            "smoke_window": ["2023-06-05", "2023-06-16"],
            "smoke_window_median_fwd_vol5_pct": round(win_median, 4),
            "smoke_window_n": int(len(win)),
        },
        # 文章正文採用的四捨五入顯示值。明列於此，讓 content-vs-source gate
        # 能逐值核對讀者實際看到的數字（而非只核對全精度值）。
        "article_display_values": {
            "pm25_decile1_fwd_vol5_pct": round(pm_d1, 1),
            "pm25_decile10_fwd_vol5_pct": round(pm_d10, 1),
            "pm25_decile1_level_ugm3": round(pm_lvl_d1, 1),
            "pm25_decile10_level_ugm3": round(pm_lvl_d10, 1),
            "vix_decile1_fwd_vol5_pct": round(vix_d1, 1),
            "vix_decile10_fwd_vol5_pct": round(vix_d10, 1),
            "vix_decile1_level": round(vix_lvl_d1, 1),
            "vix_decile10_level": round(vix_lvl_d10, 1),
            "vix_d10_over_d1_ratio": round(vix_d10 / vix_d1, 1),
            "sample_median_fwd_vol5_pct": round(sample_median, 1),
            "smoke_window_median_fwd_vol5_pct": round(win_median, 1),
            "peak_pm25_ugm3": round(peak_pm25, 0),
            "peak_over_sample_mean_ratio": round(peak_pm25 / pm25_mean_signal, 0),
            "pm25_signal_mean_ugm3": round(pm25_mean_signal, 1),
        },
        "figures": [
            "experiments/k1801/k1801_fig1_decile_ladder.png",
            "experiments/k1801/k1801_fig2_wildfire_window.png",
        ],
    }

    out, _ = finalize_experiment(
        results=results,
        entrypoint=__file__,
        canonical_result="k1801_results.json",
        inputs=[PANEL],
        outputs=[
            "k1801_fig1_decile_ladder.png",
            "k1801_fig2_wildfire_window.png",
        ],
        seeds=None,
        started_at=started_at,
    )
    print(json.dumps(results["headline"], ensure_ascii=False, indent=2))
    print(json.dumps(results["wildfire_event"], ensure_ascii=False, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
