"""Charts for the K1331 general-audience article.

Every number is read from experiments/k1331/K1331_results.json. Nothing is
hard-coded.

  1. k1331_general_mean_reversion.png -- the quintile check. Days that start in
     the lowest-dispersion bucket see dispersion climb over the next 21 sessions;
     days that start in the highest bucket see it fall. Two bars around zero.
  2. k1331_general_forecast_error.png -- two panels. Left: out-of-sample forecast
     error for the six models (lower is better). Right: how strong each model's
     improvement over the baseline is, against the strict pass line. Adding the
     dispersion features does nothing; VIX helps but still misses the line.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "k1331" / "K1331_results.json"
ASSETS = ROOT / "storage" / "drafts" / "assets"

SURFACE = "#fcfcfb"
TEXT_1 = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#d4d4d8"
BLUE = "#2a78d6"     # categorical slot 1 / diverging cool pole
ORANGE = "#eb6834"   # categorical slot 2
RED = "#e34948"      # diverging warm pole / threshold line

STRICT_T = 3.0

MODEL_LABEL = {
    "M0_index_rv": "只看大盤自己近期的波動（基準）",
    "M1_index_rv_dispersion": "基準 ＋ 分歧度",
    "M2_index_rv_corr": "基準 ＋ 同步率",
    "M3_index_rv_disp_corr": "基準 ＋ 分歧度 ＋ 同步率",
    "M4_vix_index_rv": "VIX ＋ 大盤近期波動",
    "M5_vix_index_rv_disp_corr": "VIX ＋ 大盤近期波動 ＋ 分歧度 ＋ 同步率",
}
MODEL_ORDER = list(MODEL_LABEL)
USES_VIX = {"M4_vix_index_rv", "M5_vix_index_rv_disp_corr"}


def load() -> dict:
    return json.loads(RESULTS.read_text())


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_2, length=0)


def _caption(data: dict) -> str:
    p = data["period"]
    n = p["n_obs"]
    return (
        f"資料：yfinance 調整後收盤（SPY ＋ 20 檔美股大型股 ＋ VIX），"
        f"{p['start']} 至 {p['end']}，{n:,} 個交易日"
    )


def fig_mean_reversion(data: dict) -> Path:
    q = data["mean_reversion"]["dispersion_quintile_forward_change"]
    low = q["low_mean_forward_change"]
    high = q["high_mean_forward_change"]
    gap = q["high_minus_low"]
    n_low, n_high = q["n_low"], q["n_high"]
    reg = data["mean_reversion"]["dispersion_z_21d_change_on_current"]

    labels = [
        f"當下分歧度最低的那 20% 交易日\n（{n_low:,} 天）",
        f"當下分歧度最高的那 20% 交易日\n（{n_high:,} 天）",
    ]
    vals = [low, high]
    colors = [BLUE, RED]

    fig, ax = plt.subplots(figsize=(9.6, 5.2))
    fig.patch.set_facecolor(SURFACE)

    bars = ax.bar([0, 1], vals, width=0.5, color=colors, zorder=3)
    for rect, val in zip(bars, vals):
        off = 0.10 if val >= 0 else -0.10
        va = "bottom" if val >= 0 else "top"
        ax.text(
            rect.get_x() + rect.get_width() / 2,
            val + off,
            f"{val:+.2f}",
            ha="center",
            va=va,
            fontsize=17,
            color=TEXT_1,
            zorder=4,
        )
    ax.axhline(0, color=TEXT_2, lw=1.2, zorder=2)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(labels, fontsize=12, color=TEXT_1)
    ax.set_xlim(-0.62, 1.62)
    ax.set_ylim(-2.9, 1.7)
    ax.set_ylabel("接下來 21 個交易日，分歧度的變化（標準差為單位）", fontsize=11, color=TEXT_2)
    ax.grid(axis="y", color=GRID, lw=0.7, zorder=0)
    _style(ax)

    ax.text(0, low / 2, "往上回升", ha="center", va="center", fontsize=12.5,
            color="#ffffff", zorder=4)
    ax.text(1, high / 2, "往下收斂", ha="center", va="center", fontsize=12.5,
            color="#ffffff", zorder=4)
    ax.text(
        0.5,
        -2.62,
        f"兩組落差 {gap:.2f}　·　全樣本迴歸斜率 {reg['slope']:.3f}，"
        f"解釋了 {reg['r2'] * 100:.1f}% 的變化（{reg['n_obs']:,} 天）",
        ha="center",
        fontsize=11.5,
        color=TEXT_2,
    )

    fig.suptitle(
        "分歧度拉開的時候會收回去，壓縮的時候會彈回來",
        fontsize=16,
        color=TEXT_1,
        y=0.975,
    )
    fig.text(0.5, 0.015, _caption(data), ha="center", fontsize=9.5, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.045, 1, 0.93))
    out = ASSETS / "k1331_general_mean_reversion.png"
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(fig)
    return out


def fig_forecast_error(data: dict) -> Path:
    fc = data["forecast_results"]
    models = fc["models"]
    ys = list(range(len(MODEL_ORDER)))[::-1]

    fig, axes = plt.subplots(
        1, 2, figsize=(12.4, 5.6), gridspec_kw={"width_ratios": [1.55, 1]}
    )
    fig.patch.set_facecolor(SURFACE)
    ax_err, ax_t = axes

    base_q = models["M0_index_rv"]["qlike"]

    for y, key in zip(ys, MODEL_ORDER):
        m = models[key]
        color = ORANGE if key in USES_VIX else BLUE
        ax_err.barh(y, m["qlike"], height=0.5, color=color, zorder=3)
        ax_err.text(
            m["qlike"] - 0.006,
            y,
            f"{m['qlike']:.3f}",
            ha="right",
            va="center",
            fontsize=12,
            color="#ffffff",
            zorder=4,
        )

    ax_err.axvline(base_q, color=TEXT_2, lw=1.3, ls="--", zorder=2)
    ax_err.text(
        base_q + 0.004,
        len(MODEL_ORDER) - 0.35,
        "基準線",
        fontsize=10.5,
        color=TEXT_2,
        va="top",
    )
    ax_err.set_yticks(ys)
    ax_err.set_yticklabels([MODEL_LABEL[k] for k in MODEL_ORDER], fontsize=12, color=TEXT_1)
    ax_err.set_ylim(-0.7, len(MODEL_ORDER) - 0.3)
    ax_err.set_xlim(0, base_q * 1.18)
    ax_err.set_xlabel("預測未來一個月大盤波動的平均誤差（越短越準）", fontsize=11, color=TEXT_2)
    ax_err.grid(axis="x", color=GRID, lw=0.7, zorder=0)
    _style(ax_err)

    for y, key in zip(ys, MODEL_ORDER):
        m = models[key]
        strength = abs(m["dm_t_vs_M0"])
        color = ORANGE if key in USES_VIX else BLUE
        ax_t.barh(y, strength, height=0.5, color=color, zorder=3)
        ax_t.text(
            strength + 0.08,
            y,
            f"{strength:.2f}",
            ha="left",
            va="center",
            fontsize=12,
            color=TEXT_1,
            zorder=4,
        )

    ax_t.axvline(STRICT_T, color=RED, lw=1.6, ls="--", zorder=2)
    ax_t.text(
        STRICT_T - 0.12,
        len(MODEL_ORDER) - 0.35,
        "嚴格及格線",
        fontsize=10.5,
        color=RED,
        va="top",
        ha="right",
    )
    ax_t.set_yticks(ys)
    ax_t.set_yticklabels([])
    ax_t.set_ylim(-0.7, len(MODEL_ORDER) - 0.3)
    ax_t.set_xlim(0, 4.0)
    ax_t.set_xlabel("比基準準多少的可信程度（越長越不像運氣）", fontsize=11, color=TEXT_2)
    ax_t.grid(axis="x", color=GRID, lw=0.7, zorder=0)
    _style(ax_t)

    ax_err.plot([], [], "s", ms=10, color=BLUE, label="沒有用到 VIX")
    ax_err.plot([], [], "s", ms=10, color=ORANGE, label="有用到 VIX")
    ax_err.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.005),
        ncol=2,
        frameon=False,
        fontsize=11,
        labelcolor=TEXT_1,
    )

    fig.suptitle(
        "把分歧度加進去沒有變準；VIX 有幫上忙，但兩根橘色都沒碰到嚴格及格線",
        fontsize=15.5,
        color=TEXT_1,
        y=0.985,
    )
    fig.text(
        0.5,
        0.015,
        f"實測期間 {fc['oos_start']} 至 {fc['oos_end']}，{fc['oos_n']:,} 個交易日；"
        f"每天用當天為止的資料重新配適，預測未來 {fc['horizon_days']} 個交易日",
        ha="center",
        fontsize=9.5,
        color=TEXT_2,
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.90))
    out = ASSETS / "k1331_general_forecast_error.png"
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for path in (fig_mean_reversion(data), fig_forecast_error(data)):
        print(path)


if __name__ == "__main__":
    main()
