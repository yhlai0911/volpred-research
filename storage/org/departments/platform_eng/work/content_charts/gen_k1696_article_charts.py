"""Charts for the K1696 general-audience article (term-spread vol adds nothing).

Every number is read from experiments/K1696/ at run time:

  1. k1696_general_dm_heatmap.png -- the 3x3 grid of Diebold-Mariano t-statistics
     for "model with term-spread vol" vs "model without", read from
     .oos.<asset>_h<h>.dm_hln_qlike.M3_vs_M2.t_stat. Colour is centred on 0 so
     the reader sees the sign first: positive = adding the feature made the
     forecast worse.
  2. k1696_general_tsv_timeseries.png -- the 21- and 63-day term-spread
     volatility series. The results JSON carries no daily series, so the series
     is rebuilt by calling K1696's OWN loaders (load_yield_spread / load_prices
     / build_features) rather than re-deriving it here: whatever the experiment
     plotted is what this plots.

Palette reuses the repo's validated general-audience set (#1D4ED8 / #B45309 /
#15803D on a light surface, as in scripts/gen_k1356_article_charts.py). Every
cell and line carries a direct value label, so nothing depends on hue alone.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False


def _repo_root() -> Path:
    """Find the repo root by marker, not by depth.

    This file is authored under the platform_eng department subtree because the
    department cannot currently write scripts/. Resolving by marker means it can
    be moved to scripts/gen_k1696_article_charts.py verbatim, with no edit.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "experiments").is_dir() and (parent / "storage").is_dir():
            return parent
    raise SystemExit("repo root not found (no ancestor holds experiments/ and storage/)")


ROOT = _repo_root()
EXP = ROOT / "experiments" / "K1696"
RESULTS = EXP / "K1696_results.json"
ASSETS = ROOT / "storage" / "assets"

C_POS = "#B45309"   # adding the feature made it worse
C_NEG = "#1D4ED8"   # adding the feature helped
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

ASSET_LABELS = {"SPY": "標普 500（SPY）", "HYG": "高收益債（HYG）", "IWM": "小型股（IWM）"}
ASSET_ORDER = ["SPY", "HYG", "IWM"]
HORIZONS = [1, 21, 63]
HORIZON_LABELS = {1: "1 日", 21: "21 日", 63: "63 日"}


def _frame(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_GRID)


def _load_results() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def chart_dm_heatmap(results: dict, out: Path) -> None:
    grid = np.full((len(ASSET_ORDER), len(HORIZONS)), np.nan)
    for i, asset in enumerate(ASSET_ORDER):
        for j, h in enumerate(HORIZONS):
            cell = (
                results["oos"]
                .get(f"{asset}_h{h}", {})
                .get("dm_hln_qlike", {})
                .get("M3_vs_M2", {})
            )
            value = cell.get("t_stat")
            if value is not None and np.isfinite(value):
                grid[i, j] = value

    span = float(np.nanmax(np.abs(grid))) or 1.0
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        "k1696", [C_NEG, "#FFFFFF", C_POS]
    )

    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    fig.patch.set_facecolor(C_SURFACE)
    mesh = ax.imshow(grid, cmap=cmap, vmin=-span, vmax=span)

    ax.set_xticks(range(len(HORIZONS)), [HORIZON_LABELS[h] for h in HORIZONS])
    ax.set_yticks(range(len(ASSET_ORDER)), [ASSET_LABELS[a] for a in ASSET_ORDER])
    ax.set_xlabel("預測期距", color=C_TEXT)
    ax.tick_params(colors=C_TEXT)

    for i in range(len(ASSET_ORDER)):
        for j in range(len(HORIZONS)):
            value = grid[i, j]
            if not np.isfinite(value):
                ax.text(j, i, "無資料", ha="center", va="center", color=C_MUTED)
                continue
            shade = abs(value) / span
            ax.text(
                j, i, f"{value:+.2f}",
                ha="center", va="center", fontsize=15, fontweight="bold",
                color="#FFFFFF" if shade > 0.6 else C_TEXT,
            )

    bar = fig.colorbar(mesh, ax=ax, fraction=0.046, pad=0.04)
    bar.set_label("DM 檢定 t 值（正 = 加了利差波動反而更差）", color=C_TEXT)
    bar.ax.tick_params(colors=C_TEXT)

    # The headline is counted from the grid, never asserted: an earlier draft of
    # this title said "no cell improved", which the data contradicts -- two cells
    # are negative. What is true is that none of them improved *significantly*.
    finite = grid[np.isfinite(grid)]
    worse = int((finite > 0).sum())
    better_sig = int(((finite < 0) & (np.abs(finite) > 1.96)).sum())
    ax.set_title(
        f"加入「利差波動」後，{worse} 格反而更差，{finite.size - worse} 格略好但都不顯著"
        if better_sig == 0
        else f"加入「利差波動」後，{worse}/{finite.size} 格更差",
        fontsize=14, fontweight="bold", color=C_TEXT, pad=14,
    )
    fig.text(
        0.01, 0.02,
        "資料：experiments/K1696/K1696_results.json（DM-HLN，QLIKE 損失，M3 對 M2）",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def _k1696_module():
    """Import the experiment module so the series comes from ITS loaders."""
    spec = importlib.util.spec_from_file_location("k1696_experiment", EXP / "K1696.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["k1696_experiment"] = module
    spec.loader.exec_module(module)
    return module


def chart_tsv_timeseries(out: Path) -> None:
    k1696 = _k1696_module()
    features = k1696.build_features(k1696.load_yield_spread(), k1696.load_prices())
    feats = features.dropna(subset=["tsv21", "tsv63"])

    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)
    ax.plot(feats.index, feats["tsv21"], lw=0.9, color=C_NEG, label="21 日利差波動")
    ax.plot(feats.index, feats["tsv63"], lw=1.1, color=C_POS, alpha=0.85,
            label="63 日利差波動")
    ax.set_ylabel("年化標準差（10 年期減 2 年期公債殖利率變動）", color=C_TEXT)
    ax.set_xlabel("日期", color=C_TEXT)
    ax.tick_params(colors=C_TEXT)
    ax.grid(alpha=0.25, color=C_GRID)
    ax.legend(loc="upper right", frameon=False)

    peak = feats["tsv63"].idxmax()
    ax.annotate(
        f"63 日高點 {feats['tsv63'].max():.3f}\n{peak.date()}",
        xy=(peak, feats["tsv63"].max()),
        xytext=(12, -28), textcoords="offset points",
        fontsize=9, color=C_TEXT,
        arrowprops={"arrowstyle": "-", "color": C_MUTED, "lw": 0.8},
    )

    ax.set_title(
        "利差本身波動得很明顯——但這個訊號沒能轉成更好的預測",
        fontsize=15, fontweight="bold", color=C_TEXT, pad=12,
    )
    fig.text(
        0.01, 0.02,
        "資料：FRED DGS10 與 DGS2，經 experiments/K1696/K1696.py 自身的 build_features 計算",
        fontsize=8, color=C_MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=180, facecolor=C_SURFACE)
    plt.close(fig)
    print(f"wrote {out}  ({len(feats)} 個交易日, {feats.index.min().date()} – {feats.index.max().date()})")


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    chart_dm_heatmap(_load_results(), ASSETS / "k1696_general_dm_heatmap.png")
    chart_tsv_timeseries(ASSETS / "k1696_general_tsv_timeseries.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
