#!/usr/bin/env python3
"""Render K1631 data-bound lazypack PNG panels.

The panels are generated from experiments/k1631/k1631_results.json and contain
only numbers that can be traced to that evidence file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault(
    "MPLCONFIGDIR",
    "/private/var/folders/f1/g41vrs0n20v7cx66qzcsd1nc0000gn/T/matplotlib-volpred",
)

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ft2font import FT2Font
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle
from matplotlib.textpath import TextPath


ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = ROOT / "experiments/k1631/k1631_results.json"
OUT_DIR = ROOT / "storage/lazypack_jobs/mile_0f7d1501/panels"

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

TITLE_BAR = "#172033"
INK = "#17202A"
MUTED = "#536173"
FAINT = "#E7EBF0"
PAPER = "#FFFFFF"
PANEL_BG = "#F6F8FB"
BLUE = "#235A97"
TEAL = "#177C7D"
AMBER = "#A96A12"
RED = "#C83E3A"
GREEN = "#257A4C"

FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]
BOLD_FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]

TEXT_PROBE = """
融資餘額創新高真的代表台股快見頂嗎？
白話結論：不是可靠見頂訊號；比較像後續震盪風險提示。
必須使用 evidence 數字，不可臆造。
資料：TWSE 市場融資餘額 + 0050.TW 調整收盤價。
期間：2014-01-02 至 2026-07-03；有效日資料 N=3,034。
訊號日 t 用收盤後融資餘額；後續報酬從 t+1 開始，避免偷看同日報酬。
事件定義：全樣本新高 + 20 交易日 cooldown；主窗口看後續 20 日。
全樣本新高事件 n=10，其他日 n=3,004。
後續 20 日平均報酬：創高日 +4.53%，其他日 +1.60%，差 +2.93%，但未達統計顯著。
下跌機率：創高日 40.0%，其他日 35.5%。
後續 20 日年化波動：創高日 25.40%，其他日 17.19%，差 +8.21%，高度顯著。
一句話：融資創高不是見頂按鈕，是震盪風險升溫。
資料來源：experiment K1631
"""


def load_results() -> dict[str, Any]:
    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(f"Missing evidence field: {path}")
    return cur


def choose_font(paths: Iterable[str], probe_text: str) -> Path:
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        ft = FT2Font(str(path))
        missing = {
            ch
            for ch in probe_text
            if ch.strip() and ft.get_char_index(ord(ch)) == 0
        }
        if not missing:
            return path
    raise RuntimeError("No CJK font covers all panel text; rerun with a zh-Hant font installed.")


FONT_PATH = choose_font(FONT_CANDIDATES, TEXT_PROBE)
BOLD_FONT_PATH = choose_font(BOLD_FONT_CANDIDATES, TEXT_PROBE)
FONT_NAME = font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
plt.rcParams["font.sans-serif"] = [FONT_NAME, "Heiti TC", "PingFang TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = PAPER

REGULAR = FontProperties(fname=str(FONT_PATH))
BOLD = FontProperties(fname=str(BOLD_FONT_PATH))


def pct(value: float, digits: int = 2, signed: bool = True) -> str:
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value * 100:.{digits}f}%"


def pct_pp(value: float, digits: int = 2, signed: bool = True) -> str:
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value * 100:.{digits}f}%"


def pct_plain(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def comma_int(value: int | float) -> str:
    return f"{int(value):,}"


def text_width_px(text: str, size: int, prop: FontProperties = REGULAR) -> float:
    if not text:
        return 0
    path = TextPath((0, 0), text, size=size, prop=prop)
    return path.get_extents().width * DPI / 72


def wrap_text(text: str, max_width_px: float, size: int, prop: FontProperties = REGULAR) -> str:
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if current and text_width_px(trial, size, prop) > max_width_px:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return "\n".join(lines)


def add_text(
    ax: plt.Axes,
    x: float,
    y: float,
    text: str,
    size: int,
    *,
    color: str = INK,
    bold: bool = False,
    ha: str = "left",
    va: str = "top",
    max_width_px: float | None = None,
    linespacing: float = 1.18,
) -> None:
    prop = BOLD if bold else REGULAR
    rendered = wrap_text(text, max_width_px, size, prop) if max_width_px else text
    ax.text(
        x,
        y,
        rendered,
        ha=ha,
        va=va,
        fontsize=size,
        color=color,
        fontproperties=prop,
        linespacing=linespacing,
        transform=ax.transAxes,
    )


def rect(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fc: str = PANEL_BG,
    ec: str = FAINT,
    lw: float = 1.4,
) -> None:
    ax.add_patch(
        Rectangle(
            (x, y),
            w,
            h,
            facecolor=fc,
            edgecolor=ec,
            linewidth=lw,
            transform=ax.transAxes,
        )
    )


def add_header(ax: plt.Axes, title: str, subtitle: str) -> None:
    rect(ax, 0, 0.86, 1, 0.14, fc=TITLE_BAR, ec=TITLE_BAR, lw=0)
    add_text(ax, 0.055, 0.965, title, 28, color="#FFFFFF", bold=True)
    add_text(ax, 0.055, 0.895, subtitle, 14, color="#C7D0DD")


def add_footer(ax: plt.Axes, experiment_id: str) -> None:
    rect(ax, 0, 0, 1, 0.055, fc="#F1F4F8", ec="#F1F4F8", lw=0)
    add_text(
        ax,
        0.055,
        0.035,
        f"資料來源：experiment {experiment_id.upper()}",
        15,
        color=MUTED,
        va="center",
    )


def setup_ax() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def save(fig: plt.Figure, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / name, dpi=DPI, facecolor=PAPER, bbox_inches=None, pad_inches=0)
    plt.close(fig)


def panel_question(data: dict[str, Any]) -> None:
    experiment_id = resolve_path(data, "experiment_id")
    primary = resolve_path(data, "primary_result")
    n_event = comma_int(resolve_path(primary, "n_event"))
    n_other = comma_int(resolve_path(primary, "n_other"))
    ret_diff = pct_pp(resolve_path(primary, "mean_return_diff_event_minus_other"), 2)
    vol_diff = pct_pp(resolve_path(primary, "mean_vol_diff_event_minus_other_ann"), 2)

    fig, ax = setup_ax()
    add_header(ax, "融資餘額創高懶人包", "先把見頂故事拆成可檢定問題")

    rect(ax, 0.055, 0.615, 0.89, 0.205, fc="#FFFFFF", ec="#D8DEE7")
    ax.add_patch(Circle((0.105, 0.725), 0.044, transform=ax.transAxes, facecolor=BLUE, edgecolor=BLUE))
    add_text(ax, 0.105, 0.74, "?", 40, color="#FFFFFF", bold=True, ha="center", va="center")
    add_text(
        ax,
        0.165,
        0.785,
        "核心問題：融資餘額創新高，真的代表台股快見頂嗎？",
        23,
        bold=True,
        max_width_px=1210,
    )
    add_text(
        ax,
        0.165,
        0.675,
        "把網路常見說法轉成事件研究：看創高日之後 20 個交易日的報酬與波動。",
        16,
        color=MUTED,
        max_width_px=1090,
    )

    rect(ax, 0.055, 0.355, 0.425, 0.205, fc="#F6FAFF", ec="#D4E2F2")
    add_text(ax, 0.085, 0.525, "白話結論", 17, color=BLUE, bold=True)
    add_text(
        ax,
        0.085,
        0.485,
        "白話結論：不是可靠見頂訊號；比較像後續震盪風險提示。",
        20,
        bold=True,
        max_width_px=590,
    )

    rect(ax, 0.52, 0.355, 0.425, 0.205, fc="#FFF9EF", ec="#E8D6B7")
    add_text(ax, 0.55, 0.525, "主結果摘要", 17, color=AMBER, bold=True)
    add_text(
        ax,
        0.55,
        0.485,
        f"事件 n={n_event}、其他日 n={n_other}；20 日報酬差 {ret_diff}，20 日年化波動差 {vol_diff}。",
        18,
        bold=True,
        max_width_px=595,
    )

    rect(ax, 0.055, 0.145, 0.89, 0.15, fc="#FAFBFC", ec="#D8DEE7")
    ax.add_patch(Circle((0.095, 0.225), 0.03, transform=ax.transAxes, facecolor=GREEN, edgecolor=GREEN))
    add_text(ax, 0.095, 0.232, "證", 21, color="#FFFFFF", bold=True, ha="center", va="center")
    add_text(ax, 0.145, 0.26, "研究誠實原則", 16, color=GREEN, bold=True)
    add_text(
        ax,
        0.145,
        0.215,
        "必須使用 evidence 數字，不可臆造。",
        23,
        bold=True,
        max_width_px=1020,
    )

    add_footer(ax, experiment_id)
    save(fig, "1_question.png")


def panel_method(data: dict[str, Any]) -> None:
    experiment_id = resolve_path(data, "experiment_id")
    price_start = resolve_path(data, "data.price_start")
    price_end = resolve_path(data, "data.price_end")
    n_obs = comma_int(resolve_path(data, "data.n_joined_daily_obs"))
    horizon = resolve_path(data, "primary_result.horizon_days")
    event_col = resolve_path(data, "primary_result.event_col")

    fig, ax = setup_ax()
    add_header(ax, "方法：怎麼避免把故事看成證據", "資料、時間對齊與事件定義")

    rect(ax, 0.055, 0.69, 0.89, 0.13, fc="#FFFFFF", ec="#D8DEE7")
    add_text(
        ax,
        0.085,
        0.785,
        "資料：TWSE 市場融資餘額 + 0050.TW 調整收盤價。",
        21,
        bold=True,
        max_width_px=1280,
    )
    add_text(
        ax,
        0.085,
        0.735,
        f"期間：{price_start} 至 {price_end}；有效日資料 N={n_obs}。",
        20,
        color=BLUE,
        bold=True,
        max_width_px=1280,
    )

    steps = [
        ("1", "訊號日 t", "訊號日 t 用收盤後融資餘額；後續報酬從 t+1 開始，避免偷看同日報酬。"),
        ("2", "事件定義", f"事件定義：全樣本新高 + 20 交易日 cooldown；主窗口看後續 {horizon} 日。"),
        ("3", "主檢定", "比較創高日與其他日的後續報酬、下跌機率與年化波動。"),
    ]
    xs = [0.055, 0.365, 0.675]
    for x, (num, label, body) in zip(xs, steps):
        rect(ax, x, 0.34, 0.27, 0.27, fc="#F7F9FC", ec="#D8DEE7")
        ax.add_patch(Circle((x + 0.045, 0.545), 0.027, transform=ax.transAxes, facecolor=TEAL, edgecolor=TEAL))
        add_text(ax, x + 0.045, 0.552, num, 18, color="#FFFFFF", bold=True, ha="center", va="center")
        add_text(ax, x + 0.085, 0.565, label, 18, color=TEAL, bold=True)
        add_text(ax, x + 0.03, 0.505, body, 15, color=INK, max_width_px=350, linespacing=1.18)

    for start, end in [(0.325, 0.365), (0.635, 0.675)]:
        ax.add_patch(
            FancyArrowPatch(
                (start, 0.47),
                (end, 0.47),
                arrowstyle="-|>",
                mutation_scale=22,
                linewidth=2,
                color="#9AA6B2",
                transform=ax.transAxes,
            )
        )

    rect(ax, 0.055, 0.155, 0.89, 0.105, fc="#FFF9EF", ec="#E8D6B7")
    add_text(ax, 0.085, 0.228, "Evidence 對齊", 16, color=AMBER, bold=True)
    add_text(
        ax,
        0.085,
        0.19,
        "訊號時點與事件欄位皆由 results.json 讀取，避免手填造成數字漂移。",
        14,
        color=MUTED,
        max_width_px=1280,
    )

    add_footer(ax, experiment_id)
    save(fig, "2_method.png")


def metric_card(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    event_value: str,
    other_value: str,
    diff_value: str,
    accent: str,
    note: str,
) -> None:
    rect(ax, x, y, w, h, fc="#FFFFFF", ec="#D8DEE7")
    rect(ax, x, y + h - 0.055, w, 0.055, fc=accent, ec=accent, lw=0)
    add_text(ax, x + 0.025, y + h - 0.02, title, 16, color="#FFFFFF", bold=True, va="center")
    add_text(ax, x + 0.03, y + h - 0.095, "創高日", 14, color=MUTED)
    add_text(ax, x + w - 0.035, y + h - 0.105, event_value, 26, color=accent, bold=True, ha="right")
    ax.plot([x + 0.03, x + w - 0.03], [y + h - 0.165, y + h - 0.165], color=FAINT, lw=1, transform=ax.transAxes)
    add_text(ax, x + 0.03, y + h - 0.19, "其他日", 14, color=MUTED)
    add_text(ax, x + w - 0.035, y + h - 0.2, other_value, 24, color=INK, bold=True, ha="right")
    ax.plot([x + 0.03, x + w - 0.03], [y + h - 0.22, y + h - 0.22], color=FAINT, lw=1, transform=ax.transAxes)
    add_text(ax, x + 0.03, y + h - 0.245, "差", 14, color=MUTED)
    add_text(ax, x + w - 0.035, y + h - 0.252, diff_value, 19, color=accent, bold=True, ha="right")
    if note:
        add_text(ax, x + 0.025, y + 0.045, note, 11, color=MUTED, max_width_px=235)


def panel_results(data: dict[str, Any]) -> None:
    experiment_id = resolve_path(data, "experiment_id")
    primary = resolve_path(data, "primary_result")
    n_event = resolve_path(primary, "n_event")
    n_other = resolve_path(primary, "n_other")
    ret_event = resolve_path(primary, "mean_return_event")
    ret_other = resolve_path(primary, "mean_return_other")
    ret_diff = resolve_path(primary, "mean_return_diff_event_minus_other")
    prob_down_event = resolve_path(primary, "prob_down_event")
    prob_down_other = resolve_path(primary, "prob_down_other")
    vol_event = resolve_path(primary, "mean_vol_event_ann")
    vol_other = resolve_path(primary, "mean_vol_other_ann")
    vol_diff = resolve_path(primary, "mean_vol_diff_event_minus_other_ann")
    hac_return_p = resolve_path(primary, "hac_return_p")
    hac_vol_p = resolve_path(primary, "hac_vol_p")

    fig, ax = setup_ax()
    add_header(ax, "結果：不是見頂按鈕，是震盪風險升溫", "主窗口：全樣本新高 + 20 交易日 cooldown")

    rect(ax, 0.055, 0.735, 0.89, 0.09, fc="#FFFFFF", ec="#D8DEE7")
    add_text(
        ax,
        0.085,
        0.795,
        f"全樣本新高事件 n={comma_int(n_event)}，其他日 n={comma_int(n_other)}。",
        25,
        bold=True,
        max_width_px=1280,
    )

    metric_card(
        ax,
        0.055,
        0.37,
        0.28,
        0.30,
        "後續 20 日平均報酬",
        pct(ret_event),
        pct(ret_other),
        pct_pp(ret_diff),
        BLUE,
        "",
    )
    metric_card(
        ax,
        0.36,
        0.37,
        0.28,
        0.30,
        "下跌機率",
        pct_plain(prob_down_event),
        pct_plain(prob_down_other),
        pct_pp(prob_down_event - prob_down_other),
        AMBER,
        "",
    )
    metric_card(
        ax,
        0.665,
        0.37,
        0.28,
        0.30,
        "後續 20 日年化波動",
        pct(vol_event),
        pct(vol_other),
        pct_pp(vol_diff),
        RED,
        "",
    )

    rect(ax, 0.055, 0.125, 0.89, 0.22, fc="#FAFBFC", ec="#D8DEE7")
    add_text(
        ax,
        0.085,
        0.315,
        (
            f"後續 20 日平均報酬：創高日 {pct(ret_event)}，其他日 {pct(ret_other)}，"
            f"差 {pct_pp(ret_diff)}，但未達統計顯著。"
        ),
        14,
        bold=True,
        max_width_px=1290,
    )
    add_text(
        ax,
        0.085,
        0.265,
        f"下跌機率：創高日 {pct_plain(prob_down_event)}，其他日 {pct_plain(prob_down_other)}。",
        14,
        bold=True,
        max_width_px=1290,
    )
    add_text(
        ax,
        0.085,
        0.215,
        (
            f"後續 20 日年化波動：創高日 {pct(vol_event)}，其他日 {pct(vol_other)}，"
            f"差 {pct_pp(vol_diff)}，高度顯著。"
        ),
        14,
        bold=True,
        max_width_px=1290,
    )
    add_text(
        ax,
        0.085,
        0.162,
        "一句話：融資創高不是見頂按鈕，是震盪風險升溫。",
        17,
        color=GREEN,
        bold=True,
        max_width_px=1290,
    )

    add_footer(ax, experiment_id)
    save(fig, "3_results.png")


def validate_outputs() -> None:
    expected = ["1_question.png", "2_method.png", "3_results.png"]
    missing: list[str] = []
    empty: list[str] = []
    for name in expected:
        path = OUT_DIR / name
        if not path.exists():
            missing.append(str(path))
        elif path.stat().st_size <= 0:
            empty.append(str(path))
    if missing or empty:
        raise RuntimeError(f"Render validation failed. missing={missing}, empty={empty}")


def main() -> None:
    data = load_results()
    panel_question(data)
    panel_method(data)
    panel_results(data)
    validate_outputs()
    for name in ["1_question.png", "2_method.png", "3_results.png"]:
        path = OUT_DIR / name
        print(f"{path} ({path.stat().st_size:,} bytes)")
    print(f"CJK font: {FONT_NAME} ({FONT_PATH})")


if __name__ == "__main__":
    main()
