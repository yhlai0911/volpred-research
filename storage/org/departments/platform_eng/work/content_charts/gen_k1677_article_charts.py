"""Charts for the K1677 general-audience article (does trouble spread to peers?).

Every number is read from experiments/K1677-rev/K1677-rev_results.json at run
time:

  1. k1677_general_directional.png -- the eight pre-declared indicators, ranked
     by .aggregates_primary_complete_case.<outcome>.t_cluster_directional, with
     the pre-registered t = 3 bar drawn in. The three placebo indicators are
     hatched: they are the ones that are SUPPOSED to sit near zero, and they do,
     which is what makes the one real signal worth reading at all.
  2. k1677_general_primary_vs_sensitivity.png -- the spread indicator under the
     two specifications. The exact sign-flip p-values come from
     p_bh_cluster_signflip_directional (0.0752 primary, 0.0083 sensitivity), and
     the chart says on its face that the stronger one carries survivorship bias
     and is not the result we stand behind.

Palette reuses the repo's validated general-audience set (#1D4ED8 / #B45309 /
#15803D on a light surface, as in scripts/gen_k1356_article_charts.py). Every
bar carries a direct value label, so nothing depends on hue alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False


def _repo_root() -> Path:
    """Find the repo root by marker, so this file can move to scripts/ unedited."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "experiments").is_dir() and (parent / "storage").is_dir():
            return parent
    raise SystemExit("repo root not found (no ancestor holds experiments/ and storage/)")


ROOT = _repo_root()
RESULTS = ROOT / "experiments" / "K1677-rev" / "K1677-rev_results.json"
ASSETS = ROOT / "storage" / "assets"

C_SIGNAL = "#1D4ED8"
C_WEAK = "#A1A1AA"
C_PLACEBO = "#B45309"
C_THRESHOLD = "#15803D"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

THRESHOLD = 3.0
SPREAD_KEY = "spread_cs_mktadj"

LABELS = {
    "spread_cs_mktadj": "買賣價差（市場調整後）",
    "amihud_mktadj": "Amihud 非流動性（市場調整後）",
    "semivar_mktadj": "下行半變異數（市場調整後）",
    "rv_mktadj": "已實現波動（市場調整後）",
    "rv_raw_logratio": "已實現波動（原始對數比）",
    "rv_placebo_z": "已實現波動（安慰劑）",
    "semivar_placebo_z": "半變異數（安慰劑）",
    "worstday_placebo_z": "最差單日（安慰劑）",
}
PLACEBOS = {"rv_placebo_z", "semivar_placebo_z", "worstday_placebo_z"}


def _frame(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_GRID)
    ax.set_axisbelow(True)


def chart_directional(results: dict, out: Path) -> None:
    node = results["aggregates_primary_complete_case"]
    rows = sorted(
        ((key, value["t_cluster_directional"]) for key, value in node.items()),
        key=lambda item: item[1],
    )

    fig, ax = plt.subplots(figsize=(10.6, 6.4))
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)
    ax.grid(axis="x", alpha=0.25, color=C_GRID)

    for i, (key, t_value) in enumerate(rows):
        placebo = key in PLACEBOS
        color = C_PLACEBO if placebo else (C_SIGNAL if t_value >= THRESHOLD else C_WEAK)
        ax.barh(
            i, t_value, height=0.62, color=color,
            hatch="///" if placebo else None,
            edgecolor=C_SURFACE if placebo else "none",
        )
        ax.text(
            t_value + (0.06 if t_value >= 0 else -0.06), i, f"{t_value:+.2f}",
            va="center", ha="left" if t_value >= 0 else "right",
            fontsize=10, color=C_TEXT,
        )

    ax.axvline(0, color=C_GRID, lw=1)
    ax.axvline(THRESHOLD, color=C_THRESHOLD, lw=1.4, ls="--")
    ax.text(
        THRESHOLD, len(rows) - 0.4, f"  事先宣告的門檻 t = {THRESHOLD:g}",
        color=C_THRESHOLD, fontsize=10, va="center",
    )

    ax.set_yticks(range(len(rows)), [LABELS.get(key, key) for key in rows and [r[0] for r in rows]])
    ax.tick_params(colors=C_TEXT)
    ax.set_xlabel("群集穩健 t 值（正 = 同業跟著惡化）", color=C_TEXT)
    ax.set_xlim(min(-1.2, min(t for _, t in rows) - 0.6), max(t for _, t in rows) + 1.1)

    passed = [LABELS.get(k, k) for k, t in rows if t >= THRESHOLD and k not in PLACEBOS]
    ax.set_title(
        f"八個事先宣告的指標裡，只有{'、'.join(passed)}過了門檻"
        if len(passed) == 1
        else f"八個事先宣告的指標裡，{len(passed)} 個過了門檻",
        fontsize=15, fontweight="bold", color=C_TEXT, pad=14,
    )
    # Say what the placebos actually did, not what placebos are supposed to do:
    # two of them sit near t = 1.3, above two of the real indicators. They stay
    # well under the bar, which is the point -- but calling them "near zero"
    # would be describing the ideal instead of the data.
    max_placebo = max(t for k, t in rows if k in PLACEBOS)
    fig.text(
        0.01, 0.02,
        "資料：experiments/K1677-rev/K1677-rev_results.json"
        "（.aggregates_primary_complete_case.<指標>.t_cluster_directional）。"
        f"斜線填色為安慰劑指標——它們最高只到 t = {max_placebo:.2f}，離門檻還有距離，"
        "但也不是貼在 0 上，所以這張圖只支持「唯一過門檻的是價差」這一句。",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def chart_primary_vs_sensitivity(results: dict, out: Path) -> None:
    specs = [
        ("aggregates_primary_complete_case", "主要設定\n（完整案例）", C_SIGNAL),
        ("aggregates_available_peer_sensitivity", "敏感度設定\n（可得同業）", C_PLACEBO),
    ]
    t_values, p_values, n_values, labels, colors = [], [], [], [], []
    for key, label, color in specs:
        node = results[key][SPREAD_KEY]
        t_values.append(node["t_cluster_directional"])
        p_values.append(node["p_bh_cluster_signflip_directional"])
        n_values.append(node["n"])
        labels.append(label)
        colors.append(color)

    fig, ax = plt.subplots(figsize=(9.2, 5.8))
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)
    ax.grid(axis="y", alpha=0.25, color=C_GRID)

    bars = ax.bar(range(len(specs)), t_values, width=0.5, color=colors)
    for i, (rect, t_value, p_value, n_value) in enumerate(
        zip(bars, t_values, p_values, n_values)
    ):
        verdict = "通過" if p_value < 0.05 else "未過"
        ax.text(
            rect.get_x() + rect.get_width() / 2, rect.get_height() + 0.08,
            f"t = {t_value:.2f}\n精確校正 p = {p_value:.4f}（{verdict}）\nn = {n_value}",
            ha="center", va="bottom", fontsize=10, color=C_TEXT,
        )

    ax.axhline(THRESHOLD, color=C_THRESHOLD, lw=1.4, ls="--")
    ax.text(
        0.52, THRESHOLD + 0.07, f"事先宣告的門檻 t = {THRESHOLD:g}",
        color=C_THRESHOLD, fontsize=10, ha="center",
        bbox={"boxstyle": "round,pad=0.2", "facecolor": C_SURFACE, "edgecolor": "none"},
    )
    ax.set_xticks(range(len(specs)), labels)
    ax.tick_params(colors=C_TEXT)
    ax.set_ylabel("群集穩健 t 值", color=C_TEXT)
    ax.set_ylim(0, max(t_values) * 1.42)

    ax.annotate(
        "看起來更強的這一邊有倖存者偏誤：\n只納入「還活著、資料拿得到」的同業，\n"
        "被下市的同業被排除在外。本文不採用這個數字。",
        xy=(0.78, t_values[1] * 0.72), xytext=(-0.42, max(t_values) * 1.05),
        fontsize=10, color=C_TEXT,
        arrowprops={"arrowstyle": "->", "color": C_MUTED, "lw": 1},
        bbox={"boxstyle": "round,pad=0.5", "facecolor": "#FEF3C7",
              "edgecolor": "#FCD34D"},
    )

    ax.set_title(
        "同一個指標，換一種納入規則就「顯著」了——這正是不能只看 t 值的原因",
        fontsize=14, fontweight="bold", color=C_TEXT, pad=14,
    )
    fig.text(
        0.01, 0.02,
        "資料：experiments/K1677-rev/K1677-rev_results.json（買賣價差指標；"
        "精確校正 p 取自 p_bh_cluster_signflip_directional，符號翻轉精確檢定經 BH 校正）",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def main() -> int:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    ASSETS.mkdir(parents=True, exist_ok=True)
    chart_directional(results, ASSETS / "k1677_general_directional.png")
    chart_primary_vs_sensitivity(
        results, ASSETS / "k1677_general_primary_vs_sensitivity.png"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
