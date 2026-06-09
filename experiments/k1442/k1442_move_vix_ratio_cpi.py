"""K1442 — MOVE/VIX 比值與 CPI 公布前後的隱含波動率定價

研究問題：
1. MOVE/VIX 當前比值（2026-06-09）相對歷史分布在哪？
2. CPI 公布前 5 日 MOVE/VIX 變化模式？
3. CPI 公布當日（surprise day）MOVE 與 VIX 的相對反應？

資料：yfinance ^MOVE, ^VIX 2003-2026 daily
CPI dates: BLS calendar (last 5 years 抽樣)
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

OUT = Path(__file__).parent

np.random.seed(42)


def fetch_close(ticker, start="2003-01-01"):
    df = yf.download(ticker, start=start, progress=False, auto_adjust=False)
    if hasattr(df.columns, "levels"):
        s = df["Close"].iloc[:, 0]
    else:
        s = df["Close"]
    return s.dropna().rename(ticker)


def main():
    move = fetch_close("^MOVE")
    vix = fetch_close("^VIX")
    df = pd.concat([move, vix], axis=1).dropna()
    df.columns = ["MOVE", "VIX"]
    df["ratio"] = df["MOVE"] / df["VIX"]

    n = len(df)
    last_date = df.index[-1]
    cur_move = float(df["MOVE"].iloc[-1])
    cur_vix = float(df["VIX"].iloc[-1])
    cur_ratio = float(df["ratio"].iloc[-1])

    # Historical percentile of current ratio
    pct_all = float((df["ratio"] <= cur_ratio).mean() * 100)
    # Trailing 1Y window stats
    last_1y = df["ratio"].iloc[-252:]
    pct_1y = float((last_1y <= cur_ratio).mean() * 100)
    mean_1y = float(last_1y.mean())
    median_all = float(df["ratio"].median())
    mean_all = float(df["ratio"].mean())
    std_all = float(df["ratio"].std())

    # CPI dates - representative releases 2024-2026 (BLS publishes 2nd week of month)
    cpi_dates = [
        # 2024
        "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15",
        "2024-06-12", "2024-07-11", "2024-08-14", "2024-09-11", "2024-10-10",
        "2024-11-13", "2024-12-11",
        # 2025
        "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
        "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-15",
        "2025-11-13", "2025-12-10",
        # 2026 (so far)
        "2026-01-14", "2026-02-11", "2026-03-12", "2026-04-10", "2026-05-13",
    ]
    cpi_dates = pd.to_datetime(cpi_dates)

    # Align to trading days (pick nearest available date >= cpi_date)
    event_records = []
    for d in cpi_dates:
        # find first trading day on or after d
        future_idx = df.index[df.index >= d]
        if len(future_idx) == 0:
            continue
        evt_d = future_idx[0]
        pos = df.index.get_loc(evt_d)
        if pos < 5 or pos > n - 6:
            continue
        # T-5 to T+5 window
        win = df.iloc[pos - 5 : pos + 6].copy()
        win["t"] = range(-5, 6)
        evt_row = {
            "cpi_date": d.strftime("%Y-%m-%d"),
            "trading_d": evt_d.strftime("%Y-%m-%d"),
            "ratio_T-5": float(win.loc[win["t"] == -5, "ratio"].iloc[0]),
            "ratio_T0": float(win.loc[win["t"] == 0, "ratio"].iloc[0]),
            "ratio_T+5": float(win.loc[win["t"] == 5, "ratio"].iloc[0]),
            "move_T0_pct_change_5d": float(
                (win.loc[win["t"] == 0, "MOVE"].iloc[0] / win.loc[win["t"] == -5, "MOVE"].iloc[0] - 1) * 100
            ),
            "vix_T0_pct_change_5d": float(
                (win.loc[win["t"] == 0, "VIX"].iloc[0] / win.loc[win["t"] == -5, "VIX"].iloc[0] - 1) * 100
            ),
            "move_post_pct_change_5d": float(
                (win.loc[win["t"] == 5, "MOVE"].iloc[0] / win.loc[win["t"] == 0, "MOVE"].iloc[0] - 1) * 100
            ),
            "vix_post_pct_change_5d": float(
                (win.loc[win["t"] == 5, "VIX"].iloc[0] / win.loc[win["t"] == 0, "VIX"].iloc[0] - 1) * 100
            ),
        }
        event_records.append(evt_row)

    events_df = pd.DataFrame(event_records)

    # Aggregate stats
    n_events = len(events_df)
    move_pre_mean = float(events_df["move_T0_pct_change_5d"].mean())
    vix_pre_mean = float(events_df["vix_T0_pct_change_5d"].mean())
    move_post_mean = float(events_df["move_post_pct_change_5d"].mean())
    vix_post_mean = float(events_df["vix_post_pct_change_5d"].mean())
    move_pre_median = float(events_df["move_T0_pct_change_5d"].median())
    vix_pre_median = float(events_df["vix_T0_pct_change_5d"].median())

    # "MOVE 過度定價" 判定：CPI 公布後 5 日 MOVE 下跌頻率
    move_drop_after = float((events_df["move_post_pct_change_5d"] < 0).mean() * 100)
    vix_drop_after = float((events_df["vix_post_pct_change_5d"] < 0).mean() * 100)

    # Paired t-test on MOVE pre vs post (5d)
    from scipy import stats as scs
    t_stat_move, p_move = scs.ttest_rel(
        events_df["move_T0_pct_change_5d"], events_df["move_post_pct_change_5d"]
    )
    t_stat_vix, p_vix = scs.ttest_rel(
        events_df["vix_T0_pct_change_5d"], events_df["vix_post_pct_change_5d"]
    )

    results = {
        "experiment_id": "k1442",
        "title": "MOVE/VIX 比值與 CPI 公布前後的隱含波動率定價",
        "sample": {
            "data_source": "yfinance ^MOVE, ^VIX",
            "period": f"{df.index[0].strftime('%Y-%m-%d')} to {last_date.strftime('%Y-%m-%d')}",
            "n_days": int(n),
        },
        "current_snapshot": {
            "as_of": last_date.strftime("%Y-%m-%d"),
            "MOVE": cur_move,
            "VIX": cur_vix,
            "MOVE_VIX_ratio": cur_ratio,
            "percentile_full_history": pct_all,
            "percentile_trailing_1y": pct_1y,
            "trailing_1y_mean_ratio": mean_1y,
            "full_history_mean_ratio": mean_all,
            "full_history_median_ratio": median_all,
            "full_history_std_ratio": std_all,
        },
        "cpi_event_study": {
            "n_events": int(n_events),
            "window_def": "T-5 to T+5 trading days around CPI release",
            "move_T-5_to_T0_mean_pct": move_pre_mean,
            "move_T-5_to_T0_median_pct": move_pre_median,
            "vix_T-5_to_T0_mean_pct": vix_pre_mean,
            "vix_T-5_to_T0_median_pct": vix_pre_median,
            "move_T0_to_T+5_mean_pct": move_post_mean,
            "vix_T0_to_T+5_mean_pct": vix_post_mean,
            "move_drop_after_release_pct_events": move_drop_after,
            "vix_drop_after_release_pct_events": vix_drop_after,
            "paired_t_test_move_pre_vs_post": {"t": float(t_stat_move), "p": float(p_move)},
            "paired_t_test_vix_pre_vs_post": {"t": float(t_stat_vix), "p": float(p_vix)},
        },
        "interpretation_summary": {
            "ratio_position": (
                "elevated" if pct_all > 75
                else "normal" if pct_all > 25
                else "depressed"
            ),
            "pre_cpi_pattern_move": "MOVE 平均 " + (
                f"上升 {move_pre_mean:.2f}%" if move_pre_mean > 0 else f"下降 {abs(move_pre_mean):.2f}%"
            ) + " 在 CPI 前 5 日",
            "post_cpi_pattern_move": "CPI 公布後 5 日 MOVE 下跌頻率 " + f"{move_drop_after:.1f}%",
            "vol_crush_evidence": (
                "顯著 vol crush" if (p_move < 0.05 and move_post_mean < move_pre_mean - 2)
                else "vol crush 不顯著（差距 < 2pct or p ≥ 0.05）"
            ),
        },
    }

    # Save JSON
    with open(OUT / "k1442_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Save event-level CSV
    events_df.to_csv(OUT / "k1442_cpi_events.csv", index=False)

    # Figure 1: MOVE/VIX ratio time series with percentile bands + current marker
    fig, ax = plt.subplots(figsize=(11, 5.5))
    df["ratio"].plot(ax=ax, color="#2c5f8d", linewidth=0.7, label="MOVE/VIX ratio")
    ax.axhline(median_all, color="gray", linestyle="--", linewidth=0.7, alpha=0.7, label=f"歷史中位數 {median_all:.2f}")
    ax.axhline(df["ratio"].quantile(0.9), color="orange", linestyle=":", linewidth=0.7, alpha=0.7, label=f"歷史 P90 {df['ratio'].quantile(0.9):.2f}")
    ax.axhline(df["ratio"].quantile(0.1), color="green", linestyle=":", linewidth=0.7, alpha=0.7, label=f"歷史 P10 {df['ratio'].quantile(0.1):.2f}")
    ax.scatter([last_date], [cur_ratio], color="red", s=80, zorder=5, label=f"當前 {cur_ratio:.2f} (P{pct_all:.0f})")
    ax.set_title(f"MOVE/VIX 比值（{df.index[0].year}–{last_date.year}）\n當前 {cur_ratio:.2f}，歷史百分位 P{pct_all:.0f}")
    ax.set_xlabel("日期")
    ax.set_ylabel("MOVE / VIX")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "fig_a_ratio_timeseries.png", dpi=110)
    plt.close()

    # Figure 2: CPI event study — MOVE & VIX % change pre vs post
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].hist(events_df["move_T0_pct_change_5d"], bins=12, alpha=0.6, color="#2c5f8d", edgecolor="white", label="T-5→T0 (pre)")
    axes[0].hist(events_df["move_post_pct_change_5d"], bins=12, alpha=0.5, color="#d97441", edgecolor="white", label="T0→T+5 (post)")
    axes[0].axvline(0, color="gray", linewidth=0.8)
    axes[0].axvline(move_pre_mean, color="#2c5f8d", linestyle="--", linewidth=1, label=f"pre 均值 {move_pre_mean:+.2f}%")
    axes[0].axvline(move_post_mean, color="#d97441", linestyle="--", linewidth=1, label=f"post 均值 {move_post_mean:+.2f}%")
    axes[0].set_title(f"MOVE 在 CPI 前後 5 日 % 變化（{n_events} 次事件）")
    axes[0].set_xlabel("% change")
    axes[0].set_ylabel("event count")
    axes[0].legend(fontsize=8)

    axes[1].hist(events_df["vix_T0_pct_change_5d"], bins=12, alpha=0.6, color="#2c5f8d", edgecolor="white", label="T-5→T0 (pre)")
    axes[1].hist(events_df["vix_post_pct_change_5d"], bins=12, alpha=0.5, color="#d97441", edgecolor="white", label="T0→T+5 (post)")
    axes[1].axvline(0, color="gray", linewidth=0.8)
    axes[1].axvline(vix_pre_mean, color="#2c5f8d", linestyle="--", linewidth=1, label=f"pre 均值 {vix_pre_mean:+.2f}%")
    axes[1].axvline(vix_post_mean, color="#d97441", linestyle="--", linewidth=1, label=f"post 均值 {vix_post_mean:+.2f}%")
    axes[1].set_title(f"VIX 在 CPI 前後 5 日 % 變化（{n_events} 次事件）")
    axes[1].set_xlabel("% change")
    axes[1].legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(OUT / "fig_b_cpi_event_study.png", dpi=110)
    plt.close()

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
