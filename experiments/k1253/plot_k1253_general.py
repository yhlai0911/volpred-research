"""K1253 一般讀者文章圖表（reproducible）。

從 k1253_results.json 畫兩張圖：
1. fig_overview：整段 OOS（2025-01 ~ 2026-04）GARCH 預測日波動率 vs 市場實際單日波動，
   標出 2025-04 關稅風暴視窗。
2. fig_shock_zoom：放大 2025-03 ~ 2025-05，逐日對照預測 vs 實際，示範模型的反應式適應。

單位換算：pred_var / realized_var 是（日報酬×100）^2，開根號得「日波動率（百分點）」。
所有數字來自 k1253_results.json，不新增估計。輸出寫回 experiments/k1253/。

用法：uv run python experiments/k1253/plot_k1253_general.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.resolve().parents[1] / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style(dpi=150)

# theme-neutral palette
C_PRED = "#2563EB"   # 預測（藍）
C_REAL = "#E11D48"   # 實際（洋紅）
C_MUTE = "#94A3B8"
C_BAND = "#FEF3C7"   # 風暴視窗淡黃底
INK = "#1E293B"


def load() -> pd.DataFrame:
    src = json.loads((HERE / "k1253_results.json").read_text())
    rr = src["rolling_results"]
    df = pd.DataFrame(rr)
    df["date"] = pd.to_datetime(df["date"])
    df["pred_vol"] = np.sqrt(df["pred_var"])          # 日波動率（百分點）
    df["real_vol"] = np.sqrt(df["realized_var"])      # |日報酬|（百分點）
    return df.sort_values("date").reset_index(drop=True)


def _style_axes(ax) -> None:
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(C_MUTE)
    ax.tick_params(colors=INK, labelsize=10)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8, zorder=0)


def fig_overview(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    band0, band1 = pd.Timestamp("2025-04-01"), pd.Timestamp("2025-04-30")
    ax.axvspan(band0, band1, color=C_BAND, zorder=0)
    ax.bar(df["date"], df["real_vol"], width=1.4, color=C_REAL, alpha=0.35,
           label="市場實際單日波動｜實際 |日報酬|", zorder=2)
    ax.plot(df["date"], df["pred_vol"], color=C_PRED, linewidth=1.9,
            label="模型每天的預警線｜GARCH 預測日波動", zorder=3)
    ax.annotate("2025 年 4 月\n關稅風暴",
                xy=(pd.Timestamp("2025-04-11"), 9.6),
                xytext=(pd.Timestamp("2025-05-20"), 8.4),
                fontsize=11, color=INK, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=INK, lw=1.2))
    _style_axes(ax)
    ax.set_ylabel("單日波動（%）", color=INK, fontsize=11)
    ax.set_title("預警線平時貼著市場走，卻擋不掉突發的第一擊",
                 color=INK, fontsize=15, fontweight="bold", loc="left", pad=12)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.set_ylim(0, 10.5)
    ax.legend(loc="upper right", frameon=False, fontsize=10)
    fig.text(0.008, 0.01,
             "資料：SPY 日報酬 2020–2026｜模型：GARCH(1,1) rolling 1 日預測｜實驗 K1253",
             fontsize=8.5, color=C_MUTE)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out = HERE / "fig_k1253_overview.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"✓ {out}")


def fig_shock_zoom(df: pd.DataFrame) -> None:
    m = (df["date"] >= "2025-03-10") & (df["date"] <= "2025-05-09")
    d = df[m]
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    x = np.arange(len(d))
    ax.bar(x, d["real_vol"], width=0.62, color=C_REAL, alpha=0.5,
           label="市場實際單日波動", zorder=2)
    ax.plot(x, d["pred_vol"], color=C_PRED, linewidth=2.2, marker="o",
            markersize=3.5, label="模型當天的預警線", zorder=3)

    def mark(date: str, text: str, dy: float) -> None:
        idx = int(np.where(d["date"].dt.strftime("%Y-%m-%d") == date)[0][0])
        ax.annotate(text, xy=(idx, d["real_vol"].iloc[idx]),
                    xytext=(idx, d["real_vol"].iloc[idx] + dy),
                    fontsize=9.5, color=INK, ha="center", fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color=INK, lw=1.0))

    mark("2025-04-03", "第一擊：模型預警\n遠低於實際跌幅", 1.6)
    mark("2025-04-09", "測試期最大單日\n震盪（+10%）", 0.5)
    mark("2025-04-10", "隔天：預警線\n已追上實際", 2.4)
    _style_axes(ax)
    step = max(1, len(d) // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(d["date"].dt.strftime("%m-%d").iloc[::step], rotation=0)
    ax.set_ylabel("單日波動（%）", color=INK, fontsize=11)
    ax.set_title("放大關稅風暴：擋不掉第一下，但亂流一延續就快速校準",
                 color=INK, fontsize=15, fontweight="bold", loc="left", pad=12)
    ax.set_ylim(0, 12)
    ax.legend(loc="upper right", frameon=False, fontsize=10)
    fig.text(0.008, 0.01,
             "資料：SPY 日報酬｜模型：GARCH(1,1) rolling 1 日預測｜實驗 K1253",
             fontsize=8.5, color=C_MUTE)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out = HERE / "fig_k1253_shock_zoom.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"✓ {out}")


def main() -> None:
    df = load()
    fig_overview(df)
    fig_shock_zoom(df)


if __name__ == "__main__":
    main()
