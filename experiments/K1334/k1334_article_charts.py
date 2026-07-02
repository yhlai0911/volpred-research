"""K1334 general-article charts (reader-facing, zh-Hant).

Regenerates 2 body charts + 3 lazypack poster cards for the K1334 null-result
article. Every number is read live from K1334_results.json so the figures stay
byte-traceable to the experiment output (no hand-typed values).

Run:
    uv run python experiments/K1334/k1334_article_charts.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style(dpi=150)

RESULTS = json.loads((HERE / "K1334_results.json").read_text())

# colours: buy_hold grey, vol_target blue, cvar_target purple (match K1334 base figs)
C_BH = "#4d4d4d"
C_VOL = "#1f77b4"
C_CVAR = "#7b3fa0"

oos = RESULTS["metrics_oos"]
boot = RESULTS["formal_tests"]["paired_moving_block_bootstrap_oos_cvar_vs_vol"]
covid = RESULTS["stress_periods"]["covid_crash"]


def _val(section, method, key):
    return section[method][key]


# ---------------------------------------------------------------------------
# Chart 1 — OOS 2018-2026 三種做法對比（三個小圖：夏普 / 最大回撤 / 極端下跌日）
# ---------------------------------------------------------------------------
def chart_oos_compare(out: Path) -> None:
    methods = ["buy_hold", "vol_target", "cvar_target"]
    labels = ["買進持有\n(不做風控)", "波動率目標\n(看整體波動)", "尾部風控目標\n(看最慘1%)"]
    colors = [C_BH, C_VOL, C_CVAR]

    sharpe = [_val(oos, m, "sharpe") for m in methods]
    mdd = [abs(_val(oos, m, "mdd_pct")) for m in methods]
    tail = [_val(oos, m, "left_tail_days_2pct") for m in methods]

    fig, axes = plt.subplots(1, 3, figsize=(12.6, 5.0))

    panels = [
        (axes[0], sharpe, "夏普值（每承受一分風險換到的報酬，越高越好）", "{:.3f}", (0, max(sharpe) * 1.25)),
        (axes[1], mdd, "最大回撤 %（帳戶從高點縮水最深幅度，越小越好）", "{:.1f}%", (0, max(mdd) * 1.25)),
        (axes[2], tail, "單日跌超過 2% 的天數（越少越好）", "{:.0f} 天", (0, max(tail) * 1.30)),
    ]
    for ax, vals, title, fmt, ylim in panels:
        bars = ax.bar(range(3), vals, color=colors, width=0.62, edgecolor="white", linewidth=0.8)
        ax.set_title(title, fontsize=11.5, pad=10)
        ax.set_xticks(range(3))
        ax.set_xticklabels(labels, fontsize=9.5)
        ax.set_ylim(*ylim)
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, fmt.format(v),
                    ha="center", va="bottom", fontsize=11, fontweight="bold")

    n = oos["cvar_target"]["n_days"]
    fig.suptitle("2018–2026 樣本外實測：把風控訊號換成「尾部損失」，表現跟看波動率打平",
                 fontsize=14, fontweight="bold", y=0.99)
    fig.text(0.5, 0.015,
             f"四資產等權組合（SPY／TLT／GLD／DBC），共 {n:,} 個樣本外交易日，"
             f"扣 10 bps 單邊交易成本。資料來源：yfinance｜實驗 K1334",
             ha="center", fontsize=9, color="#555")
    fig.tight_layout(rect=(0, 0.045, 1, 0.955))
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"[chart] {out.name}: sharpe={sharpe}, mdd={mdd}, tail={tail}")


# ---------------------------------------------------------------------------
# Chart 2 — 重抽樣 1000 次的差異信賴區間（夏普 + 極端下跌日頻率），都跨過零
# ---------------------------------------------------------------------------
def chart_bootstrap_ci(out: Path) -> None:
    sh = boot["sharpe_diff_cvar_minus_vol"]
    tf = boot["left_tail_freq_diff_cvar_minus_vol"]

    fig, axes = plt.subplots(2, 1, figsize=(11.0, 5.6))

    def panel(ax, d, title, unit_fmt, note):
        mean, lo, hi = d["mean"], d["ci_2p5"], d["ci_97p5"]
        ax.axvline(0, color="#d62728", lw=1.6, ls="--", zorder=1)
        ax.hlines(0, lo, hi, color=C_CVAR, lw=6, alpha=0.35, zorder=2)
        ax.plot([lo, hi], [0, 0], "|", color=C_CVAR, markersize=18, markeredgewidth=2.5, zorder=3)
        ax.plot(mean, 0, "o", color=C_CVAR, markersize=13, zorder=4)
        ax.set_title(title, fontsize=12.5, pad=8, loc="left", fontweight="bold")
        ax.set_yticks([])
        span = hi - lo
        ax.set_xlim(lo - span * 0.35, hi + span * 0.35)
        for spine in ("top", "right", "left"):
            ax.spines[spine].set_visible(False)
        ax.annotate(unit_fmt.format(lo), (lo, 0), xytext=(0, -22), textcoords="offset points",
                    ha="center", fontsize=9.5, color="#444")
        ax.annotate(unit_fmt.format(hi), (hi, 0), xytext=(0, -22), textcoords="offset points",
                    ha="center", fontsize=9.5, color="#444")
        ax.annotate(f"平均差 {mean:+.4f}", (mean, 0), xytext=(0, 14),
                    textcoords="offset points", ha="center", fontsize=10.5, fontweight="bold",
                    color=C_CVAR)
        ax.annotate("零（毫無差別）", (0, 0), xytext=(0, 44), textcoords="offset points",
                    ha="center", fontsize=9.5, color="#d62728")
        ax.text(0.995, 0.06, note, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=10, color="#333",
                bbox=dict(boxstyle="round,pad=0.4", fc="#f2f0f7", ec="#cbb8dd"))

    panel(axes[0], sh, "投資效率差異（尾部風控目標 − 波動率目標）", "{:+.3f}",
          f"尾部風控勝出的機率只有 {sh['p_gt_0'] * 100:.1f}%，幾乎等於丟一枚硬幣")
    panel(axes[1], tf, "極端下跌日頻率差異（每交易日）", "{:+.4f}",
          "少踩幾天的方向雖略偏尾部風控，但區間橫跨零，站不住腳")

    fig.suptitle("把兩種做法重抽樣比較 1000 次：所有差異都跨過「零」那條線",
                 fontsize=14, fontweight="bold", y=0.99)
    fig.text(0.5, 0.01,
             "移動區塊重抽樣（moving-block bootstrap），1000 次、區塊長 21 日、亂數種子 42，"
             "僅用 2018–2026 樣本外資料。實驗 K1334",
             ha="center", fontsize=9, color="#555")
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"[chart] {out.name}: sharpe_ci=[{sh['ci_2p5']:.3f},{sh['ci_97p5']:.3f}] "
          f"p={sh['p_gt_0']}, tailfreq_ci=[{tf['ci_2p5']:.4f},{tf['ci_97p5']:.4f}]")


# ---------------------------------------------------------------------------
# 懶人包海報卡（poster-style，text-forward，數據精確）
# ---------------------------------------------------------------------------
def _poster_base(title, subtitle):
    fig, ax = plt.subplots(figsize=(7.6, 7.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.15, 0.15), 9.7, 9.7, boxstyle="round,pad=0.02,rounding_size=0.3",
                                fc="#ffffff", ec="#7b3fa0", lw=2.2))
    ax.add_patch(plt.Rectangle((0.15, 8.55), 9.7, 1.3, fc="#7b3fa0", ec="none"))
    ax.text(5, 9.2, title, ha="center", va="center", fontsize=19, fontweight="bold", color="white")
    ax.text(5, 8.05, subtitle, ha="center", va="center", fontsize=11.5, color="#4a2a63")
    return fig, ax


def poster_concept(out: Path) -> None:
    fig, ax = _poster_base("概念｜什麼是「尾部風控目標」", "把倉位大小交給一個自動風險刻度盤")
    lines = [
        ("波動率目標", "看過去 63 天整體波動有多大，", "波動變大就自動減碼、變小就加碼。"),
        ("尾部風控目標", "只盯過去 252 天裡「最慘的 1%」交易日，", "理論上應該更專注在真正的崩盤風險。"),
    ]
    y = 6.9
    for name, l1, l2 in lines:
        ax.add_patch(FancyBboxPatch((0.8, y - 1.35), 8.4, 1.55, boxstyle="round,pad=0.05,rounding_size=0.15",
                                    fc="#f4f0fa", ec="#c9b6e0", lw=1.2))
        ax.text(1.15, y - 0.15, f"● {name}", fontsize=14, fontweight="bold", color="#5a2d80", va="top")
        ax.text(1.4, y - 0.72, l1, fontsize=11.5, color="#333", va="top")
        ax.text(1.4, y - 1.12, l2, fontsize=11.5, color="#333", va="top")
        y -= 2.15
    ax.text(5, 1.35, "直覺：直接鎖定「尾巴」，是不是就能少踩幾次崩盤？",
            ha="center", fontsize=12.5, fontweight="bold", color="#222",
            bbox=dict(boxstyle="round,pad=0.5", fc="#fff3cd", ec="#e0c86b"))
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"[poster] {out.name}")


def poster_method(out: Path) -> None:
    n_oos = oos["cvar_target"]["n_days"]
    fig, ax = _poster_base("方法｜怎麼做這場公平測試", "同一組資產、同一段期間、只換風控訊號")
    rows = [
        ("測試組合", "SPY 股票、TLT 公債、GLD 黃金、DBC 商品，等權重"),
        ("樣本外期間", f"2018-01 至 2026-05，共 {n_oos:,} 個交易日"),
        ("交易成本", "單邊 10 bps（另測 5 bps，結論相同）"),
        ("公平校準", "兩種訊號在校準期的平均倉位對齊到同一水準"),
        ("防偷看未來", "風險訊號都只用「昨天以前」的資料，再延遲一天"),
        ("統計檢定", "移動區塊重抽樣 1000 次，比較兩種做法的差異"),
    ]
    y = 7.1
    for k, v in rows:
        ax.text(1.0, y, f"● {k}", fontsize=12.5, fontweight="bold", color="#5a2d80", va="top")
        ax.text(3.7, y, v, fontsize=11.5, color="#222", va="top")
        y -= 1.02
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"[poster] {out.name}")


def poster_results(out: Path) -> None:
    sh = boot["sharpe_diff_cvar_minus_vol"]
    s_cvar = oos["cvar_target"]["sharpe"]
    s_vol = oos["vol_target"]["sharpe"]
    exp_cvar = covid["cvar_target"]["mean_exposure"]
    exp_vol = covid["vol_target"]["mean_exposure"]
    mdd_cvar = covid["cvar_target"]["mdd_pct"]
    mdd_bh = covid["buy_hold"]["mdd_pct"]

    fig, ax = _poster_base("結果｜聽起來更聰明，實測是平手", "尾部風控目標沒有贏過波動率目標")
    ax.text(5, 6.95, f"{s_cvar:.3f}", ha="center", fontsize=38, fontweight="bold", color="#7b3fa0")
    ax.text(5, 6.05, f"尾部風控目標夏普值　vs　波動率目標 {s_vol:.3f}", ha="center", fontsize=12, color="#333")
    ax.text(5, 5.55, "（差距小到統計上分不出高下）", ha="center", fontsize=10.5, color="#777")

    bullets = [
        f"重抽樣 1000 次，尾部風控勝出機率 {sh['p_gt_0'] * 100:.1f}%，幾乎等於丟硬幣",
        f"2020 COVID 崩盤時它還留著 {exp_cvar * 100:.0f}% 倉位（波動率目標只留 {exp_vol * 100:.0f}%），",
        f"    回撤 {mdd_cvar:.1f}% 跟完全不做風控的 {mdd_bh:.1f}% 幾乎一樣",
        "根因：一年份的尾部記憶反應太慢，追不上幾天內的急跌",
        "和「回撤目標」實驗 K1494 一起確認：換哪種回頭看的風險訊號都贏不了",
    ]
    y = 4.8
    for b in bullets:
        lead = b.startswith("    ")
        ax.text(0.95 if not lead else 1.5, y, ("" if lead else "× ") + b.strip(),
                fontsize=11 if not lead else 10.5, color="#222" if not lead else "#555", va="top")
        y -= 0.72 if not lead else 0.6
    ax.text(5, 0.75, "普通的 63 日波動率目標，是一個難被打敗的簡單基準",
            ha="center", fontsize=12, fontweight="bold", color="#222",
            bbox=dict(boxstyle="round,pad=0.5", fc="#e7f5e9", ec="#8ec89a"))
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"[poster] {out.name}")


if __name__ == "__main__":
    chart_oos_compare(HERE / "k1334_article_oos_compare.png")
    chart_bootstrap_ci(HERE / "k1334_article_bootstrap_ci.png")
    poster_concept(HERE / "k1334_lazypack_1_concept.png")
    poster_method(HERE / "k1334_lazypack_2_method.png")
    poster_results(HERE / "k1334_lazypack_3_results.png")
    print("done")
