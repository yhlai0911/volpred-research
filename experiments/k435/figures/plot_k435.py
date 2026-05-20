"""K435 figures: structural breaks + per-regime parameters + rolling persistence + OOS."""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

plt.rcParams["font.sans-serif"] = ["Heiti TC", "PingFang HK", "Hiragino Sans GB", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[2].parent
RESULTS = Path(__file__).resolve().parent.parent / "k435_structural_break_garch_results.json"
OUT = Path(__file__).resolve().parent

with open(RESULTS) as f:
    R = json.load(f)

breaks = R["structural_breaks"]["breaks"]
break_dates = [pd.Timestamp(b["date"]) for b in breaks]
vol_before = [b["vol_before_ann"] for b in breaks]
vol_after = [b["vol_after_ann"] for b in breaks]
vol_ratios = [b["vol_ratio"] for b in breaks]
test_stats = [b["test_statistic"] for b in breaks]

# Rolling persistence series (filter out any non-dict entries from truncation markers)
rp = [s for s in R["rolling_persistence"]["series"] if isinstance(s, dict)]
rp_dates = [pd.Timestamp(s["date"]) for s in rp]
rp_pers = [s["persistence"] for s in rp]


def fig1_breaks_timeline():
    """Detected break dates timeline with vol step changes."""
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=160)
    # Build piecewise vol step line: each break carries vol_before/vol_after
    seg_x, seg_y = [], []
    seg_x.append(pd.Timestamp("2005-01-04"))
    seg_y.append(vol_before[0])
    for d, vb, va in zip(break_dates, vol_before, vol_after):
        seg_x.append(d); seg_y.append(vb)
        seg_x.append(d); seg_y.append(va)
    seg_x.append(pd.Timestamp("2026-03-25"))
    seg_y.append(vol_after[-1])
    ax.plot(seg_x, seg_y, color="#1f77b4", lw=1.6, label="分段年化波動率（%）")
    # Mark breaks
    for d, ts in zip(break_dates, test_stats):
        ax.axvline(d, color="#d62728", alpha=0.35, lw=0.9)
    # Annotate biggest jumps
    big = sorted(zip(break_dates, vol_before, vol_after, test_stats), key=lambda r: r[3], reverse=True)[:4]
    for d, vb, va, ts in big:
        ax.annotate(d.strftime("%Y-%m"), xy=(d, max(vb, va)),
                    xytext=(0, 12), textcoords="offset points",
                    fontsize=9, ha="center", color="#d62728")
    ax.set_xlabel("日期")
    ax.set_ylabel("年化波動率（%）")
    ax.set_title("K435 SPY 報酬變異數結構斷點 — ICSS 共偵測 20 個斷點（2005-2026）")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right")
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(OUT / "k435_fig1_breaks_timeline.png", dpi=160)
    plt.close(fig)


def fig2_per_regime_params():
    """Per-regime GARCH parameter comparison (omega/gamma/beta/persistence)."""
    pr = R["garch_parameters"]["per_regime"]
    fs = R["garch_parameters"]["full_sample"]
    rows = []
    for label, d in pr.items():
        if d.get("skipped"):
            continue
        # label like "Regime 7: 2011-12-20 to 2013-06-25"
        rid = label.split(":")[0].replace("Regime ", "R")
        rows.append({
            "regime": rid,
            "omega": d["omega"],
            "gamma": d["gamma"],
            "beta": d["beta"],
            "persistence": d["persistence"],
            "uncond_vol": d["unconditional_vol_ann"],
        })
    df = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=160)
    x = np.arange(len(df))
    # left: persistence per regime vs full sample
    ax = axes[0]
    bars = ax.bar(x, df["persistence"], color="#2ca02c", alpha=0.85, label="各體制 persistence")
    ax.axhline(fs["persistence"], color="#d62728", ls="--", lw=1.5,
               label=f"全樣本 persistence ({fs['persistence']:.3f})")
    avg = R["garch_parameters"]["hillebrand_effect"]["avg_regime_persistence"]
    ax.axhline(avg, color="#1f77b4", ls=":", lw=1.5,
               label=f"各體制平均 ({avg:.3f})")
    ax.set_xticks(x)
    ax.set_xticklabels(df["regime"], rotation=0, fontsize=9)
    ax.set_ylabel("Persistence (α + γ/2 + β)")
    ax.set_title("Hillebrand 效應：忽略斷點會誇大持續性")
    ax.set_ylim(0.65, 1.0)
    ax.grid(alpha=0.3, axis="y")
    ax.legend(loc="lower right", fontsize=9)
    for i, v in enumerate(df["persistence"]):
        ax.text(i, v + 0.005, f"{v:.2f}", ha="center", fontsize=8)

    # right: gamma (leverage) vs beta per regime
    ax = axes[1]
    width = 0.38
    ax.bar(x - width/2, df["gamma"], width, color="#ff7f0e", label="γ（槓桿項）")
    ax.bar(x + width/2, df["beta"], width, color="#1f77b4", label="β（GARCH 慣性）")
    ax.set_xticks(x)
    ax.set_xticklabels(df["regime"], rotation=0, fontsize=9)
    ax.set_ylabel("係數值")
    ax.set_title("各體制的 GARCH 係數結構不同")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(loc="upper right", fontsize=9)
    fig.suptitle("K435 SPY 各體制 GJR-GARCH 參數對照（已收斂體制 N=8）",
                 fontsize=12, y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "k435_fig2_per_regime_params.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def fig3_rolling_persistence():
    """Rolling persistence with breaks overlaid."""
    fig, ax = plt.subplots(figsize=(11, 5), dpi=160)
    ax.plot(rp_dates, rp_pers, color="#1f77b4", lw=1.4, label="504 日 rolling persistence")
    avg = R["garch_parameters"]["hillebrand_effect"]["avg_regime_persistence"]
    fs_p = R["garch_parameters"]["full_sample"]["persistence"]
    ax.axhline(fs_p, color="#d62728", ls="--", lw=1.2, label=f"全樣本 ({fs_p:.3f})")
    ax.axhline(1.0, color="black", ls=":", lw=0.8, alpha=0.6, label="IGARCH 邊界 (=1)")
    for d in break_dates:
        ax.axvline(d, color="#d62728", alpha=0.18, lw=0.7)
    ax.set_xlabel("日期")
    ax.set_ylabel("Persistence")
    ax.set_title("K435 滾動式持續性 vs ICSS 偵測斷點 — 持續性會在事件附近劇烈波動")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(OUT / "k435_fig3_rolling_persistence.png", dpi=160)
    plt.close(fig)


def fig4_oos_qlike():
    """OOS QLIKE per strategy + sub-period split."""
    oos = R["oos_forecasting"]
    sp = oos["subperiod_qlike"]
    strategies = ["Standard (w=2000)", "Post-break", "Adaptive"]
    full = [oos["strategies"][s]["QLIKE"] for s in strategies]
    yr_2023 = [sp["2023"][s] for s in strategies]
    yr_2024 = [sp["2024"][s] for s in strategies]

    fig, ax = plt.subplots(figsize=(10, 5), dpi=160)
    x = np.arange(len(strategies))
    w = 0.27
    ax.bar(x - w, yr_2023, w, color="#1f77b4", label="2023 OOS")
    ax.bar(x, yr_2024, w, color="#ff7f0e", label="2024 OOS")
    ax.bar(x + w, full, w, color="#2ca02c", label="全 OOS（2023-24）")
    for i, (a, b, c) in enumerate(zip(yr_2023, yr_2024, full)):
        ax.text(i - w, a + 0.01, f"{a:.3f}", ha="center", fontsize=8)
        ax.text(i, b + 0.01, f"{b:.3f}", ha="center", fontsize=8)
        ax.text(i + w, c + 0.01, f"{c:.3f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(["固定窗（2000日）", "事件後重估", "自適應斷點"], fontsize=10)
    ax.set_ylabel("QLIKE（越低越好）")
    ax.set_title("K435 OOS 預測表現：自適應僅微幅 0.29% 改善，未過嚴格統計門檻")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "k435_fig4_oos_qlike.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    fig1_breaks_timeline()
    fig2_per_regime_params()
    fig3_rolling_persistence()
    fig4_oos_qlike()
    print("OK: 4 figures written to", OUT)
