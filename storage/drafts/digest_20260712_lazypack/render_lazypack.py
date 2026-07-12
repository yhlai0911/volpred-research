#!/usr/bin/env python3
"""Render the three-panel VolPred 「油震斷鏈圖」 lazypack.

All displayed statistics are loaded from the experiment result JSON files below.
The renderer is intentionally argument-free so the publishing worker can execute it
directly and receive a traceback if any required evidence field is missing.
"""

from __future__ import annotations

import json
import os
import textwrap
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


K1647_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k1647/k1647_results.json"
K1647_README = "/Users/yhlai0911/volpred-research/experiments/k1647/README.md"
K1665_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k1665/k1665_results.json"
K1665_README = "/Users/yhlai0911/volpred-research/experiments/k1665/README.md"
K861_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k861/k861_results.json"
K1088_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k1088/k1088_results.json"
EVIDENCE_MD = "/Users/yhlai0911/volpred-research/storage/drafts/digest_20260712_lazypack/evidence.md"

out_dir = "/Users/yhlai0911/volpred-research/storage/drafts/digest_20260712_lazypack"

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150
FIGSIZE = (WIDTH_PX / DPI, HEIGHT_PX / DPI)

# Palette: restrained editorial colors, no decorative chart-like marks.
NAVY = "#071D2B"
NAVY_2 = "#0D2D42"
NAVY_3 = "#153C54"
OIL = "#E87924"
OIL_SOFT = "#FFF0E4"
YELLOW = "#FFD166"
CREAM = "#F4EFE5"
PAPER = "#FAFBFC"
WHITE = "#FFFFFF"
INK = "#102536"
MUTED = "#526575"
LINE = "#D9E1E7"
TEAL = "#1B7C82"
TEAL_SOFT = "#E5F3F1"
RED = "#B84A48"
RED_SOFT = "#F8E9E7"
BLUE_SOFT = "#E8F0F5"


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Expected a JSON object at {path}, got {type(data).__name__}")
    return data


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    if not content.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return content


def require_path(data: Any, path: Sequence[str], source: str) -> Any:
    current = data
    traversed: list[str] = []
    for key in path:
        traversed.append(key)
        if not isinstance(current, Mapping) or key not in current:
            joined = ".".join(traversed)
            raise KeyError(f"Missing required field {joined!r} in {source}")
        current = current[key]
    return current


def require_mapping(data: Any, path: Sequence[str], source: str) -> Mapping[str, Any]:
    value = require_path(data, path, source)
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected object at {'.'.join(path)} in {source}")
    return value


def require_number(data: Any, path: Sequence[str], source: str) -> float:
    value = require_path(data, path, source)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {'.'.join(path)} in {source}")
    return float(value)


def require_int(data: Any, path: Sequence[str], source: str) -> int:
    value = require_path(data, path, source)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Expected integer at {'.'.join(path)} in {source}")
    return value


def require_bool(data: Any, path: Sequence[str], source: str) -> bool:
    value = require_path(data, path, source)
    if not isinstance(value, bool):
        raise TypeError(f"Expected boolean at {'.'.join(path)} in {source}")
    return value


def require_str(data: Any, path: Sequence[str], source: str) -> str:
    value = require_path(data, path, source)
    if not isinstance(value, str) or not value:
        raise TypeError(f"Expected non-empty string at {'.'.join(path)} in {source}")
    return value


def require_marker(text: str, marker: str, source: str) -> None:
    if marker not in text:
        raise ValueError(f"Required evidence marker {marker!r} is absent from {source}")


def zh_wrap(text: str, width: int) -> str:
    """Predictably wrap zh-Hant copy before matplotlib sees it."""
    paragraphs = text.split("\n")
    wrapped: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                paragraph,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
        )
    return "\n".join(wrapped)


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    facecolor: str,
    edgecolor: str = "none",
    linewidth: float = 1.0,
    radius: float = 0.014,
    zorder: int = 1,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def new_canvas(background: str) -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=background)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_facecolor(background)
    return fig, ax


def save_panel(fig: plt.Figure, filename: str) -> None:
    path = os.path.join(out_dir, filename)
    fig.savefig(
        path,
        format="png",
        dpi=DPI,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
    )
    plt.close(fig)


def collect_evidence() -> dict[str, Any]:
    k861 = load_json(K861_RESULTS)
    k1088 = load_json(K1088_RESULTS)
    k1647 = load_json(K1647_RESULTS)
    k1665 = load_json(K1665_RESULTS)
    k1647_readme = load_text(K1647_README)
    k1665_readme = load_text(K1665_README)
    evidence_md = load_text(EVIDENCE_MD)

    ids = [
        require_str(k861, ("experiment_id",), K861_RESULTS),
        require_str(k1088, ("metadata", "experiment_id"), K1088_RESULTS),
        require_str(k1647, ("experiment",), K1647_RESULTS),
        require_str(k1665, ("k_id",), K1665_RESULTS),
    ]
    for experiment_id, source_text, source_path in (
        (ids[2], k1647_readme, K1647_README),
        (ids[3], k1665_readme, K1665_README),
    ):
        require_marker(source_text, experiment_id, source_path)

    chain = ["停火消息", "油價回落", "油市恐慌退潮", "股市波動下降", "避險部位可撤"]
    require_marker(evidence_md, " → ".join(chain), EVIDENCE_MD)
    for marker in (
        "供給恢復",
        "需求轉弱",
        "OVX",
        "VIX",
        "GLD／TLT",
        "CBOE",
    ):
        require_marker(evidence_md, marker, EVIDENCE_MD)

    drop_n = require_int(k861, ("results", "asymmetry_drop", "n_events"), K861_RESULTS)
    drop_change = require_number(
        k861, ("results", "asymmetry_drop", "mean_change"), K861_RESULTS
    )
    spike_n = require_int(k861, ("results", "asymmetry_spike", "n_events"), K861_RESULTS)
    spike_change = require_number(
        k861, ("results", "asymmetry_spike", "mean_change"), K861_RESULTS
    )
    k861_n = require_int(k861, ("data_sources", "n_observations"), K861_RESULTS)

    compare_path = ("vix_vs_ovx_compare", "a4f_vix_vs_a4f_ovx")
    k1088_n = require_int(k1088, compare_path + ("n",), K1088_RESULTS)
    qlike_diff = require_number(k1088, compare_path + ("qlike_diff_pct",), K1088_RESULTS)
    dm_t = require_number(k1088, compare_path + ("dm_t",), K1088_RESULTS)

    oil_to_equity = require_mapping(
        k1647, ("predictive_regressions", "oil_to_equity"), K1647_RESULTS
    )
    pair_names = ("CL->SPY", "CL->XLE", "USO->SPY", "USO->XLE")
    pair_results: list[dict[str, Any]] = []
    for pair in pair_names:
        spec = require_mapping(oil_to_equity, (pair,), K1647_RESULTS)
        no_control = require_mapping(spec, ("no_control",), K1647_RESULTS)
        pair_results.append(
            {
                "pair": pair,
                "p": require_number(no_control, ("hac_p",), K1647_RESULTS),
                "n": require_int(no_control, ("n_obs",), K1647_RESULTS),
                "significant": require_bool(no_control, ("sig_5pct",), K1647_RESULTS),
            }
        )
    if any(item["significant"] for item in pair_results):
        raise ValueError("K1647 evidence no longer supports the required four-group null panel")
    regression_ns = {item["n"] for item in pair_results}
    if len(regression_ns) != 1:
        raise ValueError(f"K1647 regression N differs across pairs: {sorted(regression_ns)}")
    k1647_n = regression_ns.pop()

    lag_policy = require_str(k1647, ("data", "lag_policy"), K1647_RESULTS)
    if "shift(1)" not in lag_policy:
        raise ValueError(f"K1647 lag policy is not explicit lag-1: {lag_policy}")

    # K1665 is part of the package even though no K1665 statistic is printed.
    # These strict reads keep a missing/replaced package from silently rendering.
    _k1665_integrity = (
        require_int(k1665, ("sample", "n_obs"), K1665_RESULTS),
        require_int(
            k1665,
            ("scoreboard", "rv_level_hac_wald_bonferroni_sig_of_4"),
            K1665_RESULTS,
        ),
        require_int(
            k1665,
            ("scoreboard", "rv_level_survive_vixlevel_control_of_4"),
            K1665_RESULTS,
        ),
        require_str(k1665, ("verdict",), K1665_RESULTS),
    )

    yfinance_markers = (
        require_str(k861, ("data_sources", "equities"), K861_RESULTS),
        require_str(k861, ("data_sources", "oil"), K861_RESULTS),
        require_str(k1647, ("data", "source"), K1647_RESULTS),
    )
    if not all("yfinance" in marker.lower() for marker in yfinance_markers):
        raise ValueError("Required yfinance source marker is missing from experiment evidence")

    return {
        "ids": ids,
        "chain": chain,
        "k861": {
            "drop_n": drop_n,
            "drop_change_pp": drop_change * 100.0,
            "spike_n": spike_n,
            "spike_change_pp": spike_change * 100.0,
            "n": k861_n,
        },
        "k1088": {"n": k1088_n, "qlike_diff_pct": qlike_diff, "dm_t": dm_t},
        "k1647": {
            "n": k1647_n,
            "pairs": pair_results,
            "n_pairs": len(pair_results),
            "n_nonsignificant": sum(not item["significant"] for item in pair_results),
        },
        "sources": "yfinance／CBOE",
        "k1665_integrity": _k1665_integrity,
    }


def render_panel_1(evidence: Mapping[str, Any]) -> None:
    fig, ax = new_canvas(NAVY)

    ax.add_patch(
        Rectangle((0, 0.865), 1, 0.135, transform=ax.transAxes, facecolor=NAVY_2, edgecolor="none")
    )
    ax.text(0.04, 0.968, "VolPred｜油震斷鏈圖", color=YELLOW, fontsize=11.5, weight="bold", va="top")
    ax.text(
        0.04,
        0.915,
        "油跌後，股票就安全了嗎？",
        color=WHITE,
        fontsize=29,
        weight="bold",
        va="center",
    )

    node_x = (0.04, 0.2325, 0.425, 0.6175, 0.81)
    node_w = 0.15
    node_y = 0.56
    node_h = 0.17
    node_labels = ("停火消息", "油價回落", "油市恐慌\n退潮", "股市波動\n下降", "避險部位\n可撤")
    for index, (x, label) in enumerate(zip(node_x, node_labels, strict=True)):
        face = NAVY_3 if index not in (1, 2) else "#704019"
        edge = OIL if index in (1, 2) else "#2B536A"
        rounded_box(ax, x, node_y, node_w, node_h, facecolor=face, edgecolor=edge, linewidth=1.6)
        ax.text(
            x + node_w / 2,
            node_y + node_h / 2,
            label,
            color=WHITE,
            fontsize=15.5,
            weight="bold",
            ha="center",
            va="center",
            linespacing=1.25,
            zorder=3,
        )

    for index in range(4):
        start = node_x[index] + node_w + 0.004
        end = node_x[index + 1] - 0.004
        middle = (start + end) / 2
        ax.annotate(
            "",
            xy=(end, node_y + node_h / 2),
            xytext=(start, node_y + node_h / 2),
            xycoords=ax.transAxes,
            arrowprops={"arrowstyle": "-|>", "color": OIL, "lw": 2.2, "mutation_scale": 16},
            zorder=4,
        )
        ax.text(
            middle,
            0.765,
            "要驗證",
            color=NAVY,
            fontsize=10.5,
            weight="bold",
            ha="center",
            va="center",
            bbox={"boxstyle": "round,pad=0.28", "facecolor": YELLOW, "edgecolor": "none"},
            zorder=5,
        )

    cards = (
        (
            "原因段",
            "油跌可能是供給風險\n溢價回吐，也可能是\n需求轉弱。",
            OIL,
        ),
        (
            "油市段",
            "要看 OVX 是否跟著降；\n價格方向不等於\n不確定性。",
            TEAL,
        ),
        (
            "傳導段",
            "再驗 VIX／SPY／XLE；\n同期共振不等於\n隔日可預測。",
            "#3D7190",
        ),
        (
            "配置段",
            "看黃金、公債與股票\n避險是否照原劇本\n聯動。",
            "#8E7041",
        ),
    )
    card_x = (0.04, 0.275, 0.51, 0.745)
    for x, (heading, copy, accent) in zip(card_x, cards, strict=True):
        rounded_box(ax, x, 0.245, 0.215, 0.235, facecolor=WHITE, edgecolor="#315064", linewidth=1.1)
        ax.add_patch(
            Rectangle((x, 0.405), 0.215, 0.075, transform=ax.transAxes, facecolor=accent, edgecolor="none")
        )
        ax.text(x + 0.018, 0.442, heading, color=WHITE, fontsize=14.5, weight="bold", va="center")
        ax.text(
            x + 0.018,
            0.37,
            copy,
            color=INK,
            fontsize=10.5,
            va="top",
            linespacing=1.36,
        )

    rounded_box(ax, 0.04, 0.095, 0.92, 0.09, facecolor=YELLOW, radius=0.012)
    ax.text(
        0.5,
        0.14,
        "一段通過，不代表整條通車",
        color=NAVY,
        fontsize=26,
        weight="bold",
        ha="center",
        va="center",
    )
    source_ids = "、".join(evidence["ids"])
    ax.text(
        0.04,
        0.036,
        f"資料來源：experiment {source_ids}；油震斷鏈圖證據包",
        color="#A8BAC5",
        fontsize=9.2,
        va="center",
    )
    save_panel(fig, "1_oil_shock_chain.png")


def render_panel_2(evidence: Mapping[str, Any]) -> None:
    fig, ax = new_canvas(PAPER)
    ax.add_patch(
        Rectangle((0, 0.85), 1, 0.15, transform=ax.transAxes, facecolor=NAVY, edgecolor="none")
    )
    ax.text(0.04, 0.966, "VolPred｜研究證據", color=YELLOW, fontsize=11.5, weight="bold", va="top")
    ax.text(
        0.04,
        0.91,
        "三份證據，把油跌拆成三個問題",
        color=WHITE,
        fontsize=28,
        weight="bold",
        va="center",
    )
    ax.text(
        0.96,
        0.91,
        "描述關聯｜油市溫度計｜隔日領先力",
        color="#BFD0DA",
        fontsize=11.5,
        ha="right",
        va="center",
    )

    card_positions = (0.035, 0.355, 0.675)
    for x in card_positions:
        rounded_box(ax, x, 0.205, 0.29, 0.605, facecolor=WHITE, edgecolor=LINE, linewidth=1.2)

    k861 = evidence["k861"]
    x = card_positions[0]
    ax.text(x + 0.022, 0.773, evidence["ids"][0], color=OIL, fontsize=11.5, weight="bold", va="center")
    ax.text(x + 0.022, 0.725, "描述性事件", color=INK, fontsize=19, weight="bold", va="center")
    ax.text(x + 0.022, 0.655, f"{k861['drop_n']:,} 次劇跌", color=MUTED, fontsize=12, va="center")
    ax.text(
        x + 0.145,
        0.595,
        f"SPY RV {k861['drop_change_pp']:+.2f}pp",
        color=RED,
        fontsize=23,
        weight="bold",
        ha="center",
        va="center",
    )
    ax.plot([x + 0.025, x + 0.265], [0.535, 0.535], color=LINE, lw=1.1, transform=ax.transAxes)
    ax.text(x + 0.022, 0.495, f"{k861['spike_n']:,} 次劇漲", color=MUTED, fontsize=12, va="center")
    ax.text(
        x + 0.145,
        0.435,
        f"SPY RV {k861['spike_change_pp']:+.2f}pp",
        color=TEAL,
        fontsize=23,
        weight="bold",
        ha="center",
        va="center",
    )
    ax.text(
        x + 0.022,
        0.36,
        "事件後的描述性變化",
        color=MUTED,
        fontsize=10.8,
        va="center",
    )
    rounded_box(ax, x + 0.018, 0.225, 0.254, 0.09, facecolor=RED_SOFT, radius=0.009)
    ax.text(
        x + 0.145,
        0.27,
        "相關、非因果",
        color=RED,
        fontsize=14.5,
        weight="bold",
        ha="center",
        va="center",
    )

    k1088 = evidence["k1088"]
    x = card_positions[1]
    ax.text(x + 0.022, 0.773, evidence["ids"][1], color=TEAL, fontsize=11.5, weight="bold", va="center")
    ax.text(x + 0.022, 0.725, "同樣本比較", color=INK, fontsize=19, weight="bold", va="center")
    ax.text(x + 0.145, 0.645, "OVX 模型相對 VIX", color=MUTED, fontsize=12, ha="center", va="center")
    ax.text(x + 0.145, 0.585, "QLIKE 差", color=MUTED, fontsize=11.5, ha="center", va="center")
    ax.text(
        x + 0.145,
        0.515,
        f"{k1088['qlike_diff_pct']:.3f}%",
        color=TEAL,
        fontsize=29,
        weight="bold",
        ha="center",
        va="center",
    )
    ax.plot([x + 0.025, x + 0.265], [0.455, 0.455], color=LINE, lw=1.1, transform=ax.transAxes)
    ax.text(x + 0.145, 0.415, "DM 統計量", color=MUTED, fontsize=11.5, ha="center", va="center")
    ax.text(
        x + 0.145,
        0.36,
        f"{k1088['dm_t']:+.3f}",
        color=INK,
        fontsize=24,
        weight="bold",
        ha="center",
        va="center",
    )
    rounded_box(ax, x + 0.018, 0.225, 0.254, 0.09, facecolor=TEAL_SOFT, radius=0.009)
    ax.text(
        x + 0.145,
        0.27,
        "油市看 OVX 更貼題",
        color=TEAL,
        fontsize=14,
        weight="bold",
        ha="center",
        va="center",
    )

    k1647 = evidence["k1647"]
    x = card_positions[2]
    ax.text(x + 0.022, 0.773, evidence["ids"][2], color="#3D7190", fontsize=11.5, weight="bold", va="center")
    ax.text(x + 0.022, 0.725, "明確 lag-1", color=INK, fontsize=19, weight="bold", va="center")
    ax.text(x + 0.145, 0.65, "昨日油 RV → 今日股 RV", color=MUTED, fontsize=12, ha="center", va="center")
    ax.text(
        x + 0.145,
        0.555,
        f"{k1647['n_nonsignificant']} / {k1647['n_pairs']}",
        color="#3D7190",
        fontsize=35,
        weight="bold",
        ha="center",
        va="center",
    )
    ax.text(x + 0.145, 0.485, "四組皆不顯著", color=INK, fontsize=17, weight="bold", ha="center", va="center")
    ax.text(
        x + 0.145,
        0.405,
        "CL／USO → SPY／XLE",
        color=MUTED,
        fontsize=12.5,
        ha="center",
        va="center",
    )
    ax.text(x + 0.145, 0.355, "shift(1)；Newey-West HAC", color=MUTED, fontsize=10.5, ha="center", va="center")
    rounded_box(ax, x + 0.018, 0.225, 0.254, 0.09, facecolor=OIL_SOFT, radius=0.009)
    ax.text(
        x + 0.145,
        0.27,
        "沒有領先力 ≠ 沒有風險",
        color="#9C4C16",
        fontsize=13.2,
        weight="bold",
        ha="center",
        va="center",
    )

    rounded_box(ax, 0.035, 0.07, 0.93, 0.09, facecolor=NAVY, radius=0.009)
    ax.text(
        0.055,
        0.115,
        f"N={k861['n']:,}／{k1088['n']:,}／{k1647['n']:,}",
        color=WHITE,
        fontsize=13.5,
        weight="bold",
        va="center",
    )
    ax.text(
        0.945,
        0.115,
        f"資料來源：experiment {evidence['ids'][0]}、{evidence['ids'][1]}、{evidence['ids'][2]}｜{evidence['sources']}",
        color="#C6D5DD",
        fontsize=9.8,
        ha="right",
        va="center",
    )
    save_panel(fig, "2_three_pieces_of_evidence.png")


def decision_card(
    ax: plt.Axes,
    x: float,
    y: float,
    title: str,
    judgment: str,
    action: str,
    accent: str,
    header_text_color: str = WHITE,
) -> None:
    width = 0.45
    height = 0.295
    rounded_box(ax, x, y, width, height, facecolor=WHITE, edgecolor="#D6DAD8", linewidth=1.15)
    ax.add_patch(
        Rectangle((x, y + height - 0.066), width, 0.066, transform=ax.transAxes, facecolor=accent, edgecolor="none")
    )
    ax.text(
        x + 0.022,
        y + height - 0.033,
        title,
        color=header_text_color,
        fontsize=15,
        weight="bold",
        va="center",
    )
    ax.text(x + 0.022, y + 0.196, "判讀", color=accent, fontsize=10, weight="bold", va="center")
    ax.text(
        x + 0.022,
        y + 0.165,
        judgment,
        color=INK,
        fontsize=10,
        va="top",
        linespacing=1.24,
    )
    ax.text(x + 0.022, y + 0.092, "不越權動作", color=accent, fontsize=10, weight="bold", va="center")
    ax.text(
        x + 0.022,
        y + 0.064,
        action,
        color=MUTED,
        fontsize=9.8,
        va="top",
        linespacing=1.24,
    )


def render_panel_3(evidence: Mapping[str, Any]) -> None:
    fig, ax = new_canvas(CREAM)
    ax.add_patch(
        Rectangle((0, 0.84), 1, 0.16, transform=ax.transAxes, facecolor=NAVY, edgecolor="none")
    )
    ax.text(0.04, 0.968, "VolPred｜今日檢查表", color=YELLOW, fontsize=11.5, weight="bold", va="top")
    ax.text(
        0.04,
        0.918,
        "今天怎麼用油震斷鏈圖",
        color=WHITE,
        fontsize=28,
        weight="bold",
        va="center",
    )
    ax.text(
        0.04,
        0.865,
        "同樣是油跌，先辨認原因與恐慌，再決定要不要調整風險配置。",
        color="#C7D5DD",
        fontsize=12,
        va="center",
    )

    decision_card(
        ax,
        0.04,
        0.51,
        "供給恢復 ＋ OVX 降",
        "只確認原因段與油市段降溫；\n股市段仍要另驗。",
        "維持原風險預算；別因單日反彈\n撤掉全部保護。",
        TEAL,
    )
    decision_card(
        ax,
        0.51,
        0.51,
        "需求轉弱 ＋ VIX 升",
        "傳導鏈未斷；油跌可能不是\n風險解除的好消息。",
        "檢查景氣敏感與能源曝險。",
        RED,
    )
    decision_card(
        ax,
        0.04,
        0.18,
        "油跌，但 OVX 仍高",
        "市場仍懷疑停火；油市恐慌\n沒有同步退潮。",
        "等待 OVX 與實際供應訊號確認。",
        OIL,
    )
    decision_card(
        ax,
        0.51,
        0.18,
        "油與 OVX 皆降，但 GLD／TLT 失靈",
        "避險標籤沒有照原劇本運作。",
        "重新量實際相關與部位；不靠\n「黃金／公債一定避險」的標籤。",
        NAVY_3,
    )

    rounded_box(ax, 0.39, 0.074, 0.57, 0.064, facecolor=NAVY, radius=0.009)
    ax.text(
        0.675,
        0.106,
        "先分原因，再看恐慌，再驗傳導，最後才動配置",
        color=YELLOW,
        fontsize=15.5,
        weight="bold",
        ha="center",
        va="center",
    )
    source_ids = "、".join(evidence["ids"])
    ax.text(
        0.04,
        0.035,
        f"資料來源：油震斷鏈圖證據包；experiment {source_ids}",
        color=MUTED,
        fontsize=9.2,
        va="center",
    )
    save_panel(fig, "3_today_checklist.png")


def main() -> None:
    evidence = collect_evidence()
    os.makedirs(out_dir, exist_ok=True)
    render_panel_1(evidence)
    render_panel_2(evidence)
    render_panel_3(evidence)


if __name__ == "__main__":
    main()
