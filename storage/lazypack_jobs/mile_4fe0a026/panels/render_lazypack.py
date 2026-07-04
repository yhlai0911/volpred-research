#!/usr/bin/env python3
"""Render data-bound PNG panels for the TWSE price-limit lazypack.

The displayed statistics are derived from
experiments/research_magnet_effect_2015_7_10_vol/
research_magnet_effect_2015_7_10_vol_results.json.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


OUT_DIR = Path(__file__).resolve().parent
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "volpred_lazypack_mplconfig" / "mile_4fe0a026"),
)

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


WIDTH = 1600
HEIGHT = 1000
DPI = 150

NAVY = "#17233B"
NAVY_2 = "#23304D"
INK = "#1F2937"
MUTED = "#667085"
SOFT = "#F5F7FA"
BORDER = "#D0D5DD"
BLUE = "#245B9A"
BLUE_SOFT = "#E7F0FA"
TEAL = "#0F766E"
TEAL_SOFT = "#DFF3F0"
AMBER = "#B76E00"
AMBER_SOFT = "#FFF3D6"
RED = "#B42318"
RED_SOFT = "#FEE4E2"
GREEN = "#237A57"
GREEN_SOFT = "#E6F4EA"
PURPLE = "#5A4B8A"
PURPLE_SOFT = "#ECE9F7"
WHITE = "#FFFFFF"


def find_root(start: Path) -> Path:
    for path in [start, *start.parents]:
        if (path / "experiments").is_dir() and (path / "storage").is_dir():
            return path
    raise RuntimeError("Could not locate repository root from render script path.")


ROOT = find_root(Path(__file__).resolve())
EXP_DIR = ROOT / "experiments" / "research_magnet_effect_2015_7_10_vol"
RESULTS_PATH = EXP_DIR / "research_magnet_effect_2015_7_10_vol_results.json"


def load_results() -> dict[str, Any]:
    with RESULTS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"Missing required evidence field: {path}")
        cur = cur[part]
    return cur


def pct(frac: float, decimals: int = 0) -> str:
    return f"{frac * 100:.{decimals}f}%"


def pp(frac: float, decimals: int = 3) -> str:
    return f"{frac * 100:+.{decimals}f}pp"


def pp_plain(frac: float, decimals: int = 2) -> str:
    return f"{frac * 100:.{decimals}f}pp"


def num(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}"


def int_comma(value: int | float) -> str:
    return f"{int(value):,}"


def setup_fonts() -> str:
    candidates = ["Heiti TC", "PingFang TC", "Arial Unicode MS", "Hiragino Sans GB"]
    selected = None
    for name in candidates:
        try:
            font_manager.findfont(name, fallback_to_default=False)
            selected = name
            break
        except ValueError:
            continue
    if selected is None:
        raise RuntimeError("No CJK-capable matplotlib font found.")

    plt.rcParams["font.sans-serif"] = [selected, "Arial Unicode MS", "Hiragino Sans GB"]
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False
    return selected


FONT_NAME = setup_fonts()


def text_units(text: str) -> float:
    units = 0.0
    for ch in text:
        if ch == "\n":
            units = 0.0
        elif ch.isascii():
            units += 0.56 if ch.isalnum() else 0.34
        else:
            units += 1.0
    return units


def wrap_text(text: str, max_units: float) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        line = ""
        units = 0.0
        for ch in raw:
            add = 0.56 if ch.isascii() and ch.isalnum() else 0.34 if ch.isascii() else 1.0
            if line and units + add > max_units:
                lines.append(line)
                line = ch
                units = add
            else:
                line += ch
                units += add
        if line:
            lines.append(line)
    return lines


def add_text(
    ax: plt.Axes,
    x: float,
    y: float,
    text: str,
    *,
    size: int,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "top",
    max_units: float | None = None,
    line_height: float = 1.25,
    alpha: float = 1.0,
) -> float:
    lines = wrap_text(text, max_units) if max_units else text.split("\n")
    yy = y
    font_size_pt = size * 72 / DPI
    for line in lines:
        ax.text(
            x,
            yy,
            line,
            fontsize=font_size_pt,
            color=color,
            fontweight=weight,
            ha=ha,
            va=va,
            alpha=alpha,
        )
        yy += size * line_height
    return yy


def card(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    face: str = WHITE,
    edge: str = BORDER,
    lw: float = 1.2,
    radius: float = 8,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            linewidth=lw,
            edgecolor=edge,
            facecolor=face,
        )
    )


def make_fig() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(HEIGHT, 0)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), WIDTH, HEIGHT, facecolor=WHITE, edgecolor="none"))
    return fig, ax


def header(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.add_patch(Rectangle((0, 0), WIDTH, 132, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0, 122), WIDTH, 10, facecolor=TEAL, edgecolor="none"))
    add_text(ax, 78, 32, title, size=38, color=WHITE, weight="bold")
    add_text(ax, 80, 88, subtitle, size=20, color="#D8DEE9")
    add_text(ax, 1450, 42, "VolPred", size=20, color="#D8DEE9", weight="bold", ha="right")


def footer(ax: plt.Axes, experiment_id: str) -> None:
    add_text(
        ax,
        80,
        945,
        f"資料來源：experiment {experiment_id}（results.json）；TWSE 官方 MI_INDEX 日資料",
        size=18,
        color=MUTED,
    )


def source_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "experiment_id": get(data, "experiment_id"),
        "source": get(data, "data.source"),
        "change_date": get(data, "data.change_date"),
        "pre_limit": float(get(data, "data.price_limit_pre")),
        "post_limit": float(get(data, "data.price_limit_post")),
        "touch_tolerance": float(get(data, "data.event_definition.touch_tolerance")),
        "near_close_band": float(get(data, "data.event_definition.near_close_band")),
        "first_trading_date": get(data, "data.fetch_meta.first_trading_date"),
        "last_trading_date": get(data, "data.fetch_meta.last_trading_date"),
        "valid_stock_days": int(get(data, "event_summary.total_valid_stock_days")),
        "old7_event_days": int(get(data, "event_summary.total_old7_event_stock_days")),
        "applicable_event_days": int(get(data, "event_summary.total_event_stock_days")),
        "n_dates": int(get(data, "tests.old7_band_robustness.cross_section_clustered_event_regression.n_dates")),
    }


def render_concept(data: dict[str, Any]) -> Path:
    s = source_summary(data)
    fig, ax = make_fig()
    header(
        ax,
        "台股漲跌停放寬懶人包",
        f"{s['change_date']}：每日漲跌幅限制從 {pct(s['pre_limit'])} 放寬到 {pct(s['post_limit'])}",
    )

    card(ax, 80, 170, 1440, 170, face=SOFT, edge="#E4E7EC")
    add_text(ax, 126, 202, pct(s["pre_limit"]), size=72, color=BLUE, weight="bold")
    add_text(ax, 252, 224, "舊制漲跌幅限制", size=28, color=INK, weight="bold")
    add_text(ax, 252, 268, "放寬前的硬邊界", size=22, color=MUTED)
    ax.add_patch(FancyArrowPatch((635, 250), (935, 250), arrowstyle="-|>", mutation_scale=30, linewidth=4, color=TEAL))
    add_text(ax, 755, 202, s["change_date"], size=26, color=TEAL, weight="bold", ha="center")
    add_text(ax, 982, 202, pct(s["post_limit"]), size=72, color=TEAL, weight="bold")
    add_text(ax, 1110, 224, "新制漲跌幅限制", size=28, color=INK, weight="bold")
    add_text(ax, 1110, 268, "放寬後的制度邊界", size=22, color=MUTED)

    card(ax, 80, 390, 690, 360)
    add_text(ax, 118, 428, "「近停板」白話定義", size=30, color=INK, weight="bold")
    ax.add_patch(Rectangle((118, 482), 5, 180, facecolor=BLUE, edgecolor="none"))
    add_text(
        ax,
        148,
        480,
        f"股價在事件日 t 已經非常接近日內漲停或跌停：\n盤中高低價距離限制線 {pp_plain(s['touch_tolerance'])} 內，或收盤價距離限制線 {pp_plain(s['near_close_band'])} 內。",
        size=25,
        color=INK,
        max_units=23,
        line_height=1.35,
    )
    add_text(
        ax,
        148,
        656,
        "本文另用「固定舊 7% 門檻」做公平比較。",
        size=23,
        color=BLUE,
        weight="bold",
        max_units=25,
    )

    card(ax, 830, 390, 690, 360)
    add_text(ax, 868, 428, "「隔天波動溢價」白話定義", size=30, color=INK, weight="bold")
    ax.add_patch(Rectangle((868, 482), 5, 180, facecolor=TEAL, edgecolor="none"))
    add_text(
        ax,
        898,
        480,
        "事件股隔天的絕對報酬，減掉非事件股隔天的絕對報酬。\n差值為正，表示近停板股票隔天比較會動。",
        size=25,
        color=INK,
        max_units=24,
        line_height=1.35,
    )
    add_text(
        ax,
        898,
        656,
        "事件在當天 t 觀察；報酬看 t+1。",
        size=23,
        color=TEAL,
        weight="bold",
        max_units=24,
    )

    card(ax, 80, 798, 1440, 100, face=NAVY_2, edge=NAVY_2)
    add_text(
        ax,
        800,
        825,
        "核心問題：靠近漲跌停的股票，隔天是不是比較會動？",
        size=32,
        color=WHITE,
        weight="bold",
        ha="center",
        max_units=42,
    )
    footer(ax, s["experiment_id"])

    out = OUT_DIR / "1_concept.png"
    fig.savefig(out, dpi=DPI, facecolor=WHITE)
    plt.close(fig)
    return out


def render_method(data: dict[str, Any]) -> Path:
    s = source_summary(data)
    fig, ax = make_fig()
    header(ax, "怎麼比才公平？", "同一條舊 7% 邊界，前後期間都用同一把尺")

    top_cards = [
        ("資料來源", "TWSE 官方\nMI_INDEX 日資料", BLUE, BLUE_SOFT),
        ("樣本期間", f"{s['first_trading_date']}\n至 {s['last_trading_date']}", TEAL, TEAL_SOFT),
        ("股票日觀察值", int_comma(s["valid_stock_days"]), AMBER, AMBER_SOFT),
        ("交易日", f"{int_comma(s['n_dates'])} 天", PURPLE, PURPLE_SOFT),
    ]
    x0 = 80
    for idx, (label, value, color, face) in enumerate(top_cards):
        x = x0 + idx * 365
        card(ax, x, 170, 325, 165, face=face, edge="#E4E7EC")
        add_text(ax, x + 28, 196, label, size=21, color=MUTED, weight="bold")
        add_text(ax, x + 28, 242, value, size=34, color=color, weight="bold", max_units=12, line_height=1.12)

    card(ax, 80, 385, 1440, 190)
    add_text(ax, 118, 415, "自然實驗時間線", size=28, color=INK, weight="bold")
    line_y = 500
    ax.plot([180, 1420], [line_y, line_y], color=BORDER, linewidth=5, solid_capstyle="round")
    positions = [180, 800, 1420]
    labels = [
        (s["first_trading_date"], f"舊制 {pct(s['pre_limit'])}"),
        (s["change_date"], f"{pct(s['pre_limit'])} → {pct(s['post_limit'])}"),
        (s["last_trading_date"], "樣本結束"),
    ]
    colors = [BLUE, TEAL, MUTED]
    for x, (date, label), color in zip(positions, labels, colors):
        ax.add_patch(Circle((x, line_y), 15, facecolor=color, edgecolor=WHITE, linewidth=3))
        add_text(ax, x, line_y + 28, date, size=21, color=INK, weight="bold", ha="center")
        add_text(ax, x, line_y + 62, label, size=20, color=color, weight="bold", ha="center")

    card(ax, 80, 625, 690, 230)
    add_text(ax, 118, 660, "公平比較：固定舊 7% 門檻", size=30, color=INK, weight="bold")
    add_text(
        ax,
        118,
        715,
        f"放寬前後都用舊制 {pct(s['pre_limit'])} 當近停板門檻，避免放寬後拿更極端的 {pct(s['post_limit'])} 事件去比舊制事件。",
        size=25,
        color=INK,
        max_units=26,
        line_height=1.34,
    )
    add_text(ax, 118, 815, f"固定舊 7% 事件：{int_comma(s['old7_event_days'])} 筆股票日", size=21, color=BLUE, weight="bold")

    card(ax, 830, 625, 690, 230)
    add_text(ax, 868, 660, "避免未來資訊：t 到 t+1", size=30, color=INK, weight="bold")
    flow_y = 757
    ax.add_patch(Rectangle((900, flow_y - 32), 155, 64, facecolor=TEAL_SOFT, edgecolor=TEAL, linewidth=1.5))
    add_text(ax, 978, flow_y - 16, "事件日 t", size=24, color=TEAL, weight="bold", ha="center")
    ax.add_patch(FancyArrowPatch((1080, flow_y), (1200, flow_y), arrowstyle="-|>", mutation_scale=25, linewidth=3, color=MUTED))
    ax.add_patch(Rectangle((1225, flow_y - 32), 215, 64, facecolor=BLUE_SOFT, edgecolor=BLUE, linewidth=1.5))
    add_text(ax, 1332, flow_y - 16, "隔天報酬 t+1", size=24, color=BLUE, weight="bold", ha="center")
    add_text(
        ax,
        868,
        815,
        "訊號先發生，目標後觀察；不讓同一天報酬偷渡進訊號。",
        size=21,
        color=MUTED,
        max_units=31,
    )

    footer(ax, s["experiment_id"])
    out = OUT_DIR / "2_method.png"
    fig.savefig(out, dpi=DPI, facecolor=WHITE)
    plt.close(fig)
    return out


def result_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    app = get(data, "tests.applicable_limit.daily_diff_abs_return_did")
    old_daily = get(data, "tests.old7_band_robustness.daily_diff_abs_return_did")
    old_xs = get(data, "tests.old7_band_robustness.cross_section_clustered_event_regression")
    cont = get(data, "tests.old7_band_robustness.daily_side_adjusted_continuation_did")

    return [
        {
            "test": "當時制度門檻：隔天波動溢價 後−前",
            "estimate": pp(float(app["post_minus_pre"]), 3),
            "stat": f"統計值 {num(float(app['t_stat']), 2)}",
            "read": "顯著；但 10% 事件較極端，易被制度定義放大",
            "tone": "amber",
        },
        {
            "test": "固定舊 7%：隔天波動溢價 後−前",
            "estimate": pp(float(old_daily["post_minus_pre"]), 3),
            "stat": f"統計值 {num(float(old_daily['t_stat']), 2)}",
            "read": "未顯著；公平口徑下沒有乾淨斷點",
            "tone": "muted",
        },
        {
            "test": "放寬前近舊停板：隔天波動溢價",
            "estimate": pp(float(old_xs["coef_event_pre"]), 3),
            "stat": f"統計值 {num(float(old_xs['t_event_pre']), 2)}",
            "read": "顯著；放寬前近停板股票隔天較會動",
            "tone": "green",
        },
        {
            "test": "固定舊 7% 交互作用：溢價額外增加",
            "estimate": pp(float(old_xs["coef_event_post_change"]), 3),
            "stat": f"統計值 {num(float(old_xs['t_event_post_change']), 2)}",
            "read": "未顯著；沒有可靠證據說放寬後溢價變大",
            "tone": "muted",
        },
        {
            "test": "隔天同方向延續力道：放寬前 → 放寬後",
            "estimate": f"{pp(float(cont['pre_mean']), 2)} → {pp(float(cont['post_mean']), 2)}",
            "stat": f"差 {pp(float(cont['post_minus_pre']), 3)}；統計值 {num(float(cont['t_stat']), 2)}",
            "read": "顯著減弱；舊 7% 不再綁住後，延續力道幾乎歸零",
            "tone": "red",
        },
    ]


def tone_colors(tone: str) -> tuple[str, str]:
    if tone == "green":
        return GREEN, GREEN_SOFT
    if tone == "red":
        return RED, RED_SOFT
    if tone == "amber":
        return AMBER, AMBER_SOFT
    return MUTED, SOFT


def render_results(data: dict[str, Any]) -> Path:
    s = source_summary(data)
    rows = result_rows(data)
    fig, ax = make_fig()
    header(ax, "五項檢定怎麼說？", "近停板隔天會動，但放寬 7%→10% 不是乾淨的波動斷點")

    card(ax, 80, 165, 1440, 126, face=NAVY_2, edge=NAVY_2)
    add_text(
        ax,
        118,
        194,
        "結論先講：日資料只能看到部分現象，非逐筆磁吸效應證據。",
        size=31,
        color=WHITE,
        weight="bold",
        max_units=46,
    )
    add_text(
        ax,
        118,
        240,
        "最穩的變化是「隔天延續力道」變弱；不是證明放寬後隔天波動變大。",
        size=22,
        color="#D8DEE9",
        max_units=58,
    )

    x = 80
    y = 328
    widths = [560, 245, 250, 365]
    headers = ["檢定", "估計值", "統計強度", "白話判讀"]
    x_positions = [x, x + widths[0], x + widths[0] + widths[1], x + widths[0] + widths[1] + widths[2]]
    ax.add_patch(Rectangle((x, y), sum(widths), 48, facecolor="#EEF2F7", edgecolor=BORDER, linewidth=1))
    for xi, label in zip(x_positions, headers):
        add_text(ax, xi + 18, y + 13, label, size=19, color=INK, weight="bold")

    row_y = y + 48
    row_h = 98
    for idx, row in enumerate(rows):
        bg = WHITE if idx % 2 == 0 else "#FAFBFC"
        ax.add_patch(Rectangle((x, row_y), sum(widths), row_h, facecolor=bg, edgecolor=BORDER, linewidth=1))
        tone, soft = tone_colors(row["tone"])
        ax.add_patch(Rectangle((x, row_y), 8, row_h, facecolor=tone, edgecolor="none"))
        ax.add_patch(Rectangle((x_positions[1] + 16, row_y + 20), 190, 45, facecolor=soft, edgecolor="none"))
        add_text(ax, x_positions[0] + 22, row_y + 20, row["test"], size=21, color=INK, weight="bold", max_units=23, line_height=1.2)
        add_text(ax, x_positions[1] + 110, row_y + 30, row["estimate"], size=24, color=tone, weight="bold", ha="center")
        add_text(ax, x_positions[2] + 18, row_y + 31, row["stat"], size=21, color=INK, weight="bold", max_units=13)
        add_text(ax, x_positions[3] + 18, row_y + 20, row["read"], size=20, color=INK, max_units=18, line_height=1.22)
        row_y += row_h

    card(ax, 80, 885, 1440, 44, face="#F8FAFC", edge="#E4E7EC")
    add_text(
        ax,
        118,
        897,
        "讀法：統計值絕對值超過 3 才視為嚴格顯著；固定舊 7% 口徑是本文的主要比較。",
        size=18,
        color=MUTED,
        max_units=70,
    )
    footer(ax, s["experiment_id"])

    out = OUT_DIR / "3_results.png"
    fig.savefig(out, dpi=DPI, facecolor=WHITE)
    plt.close(fig)
    return out


def main() -> None:
    data = load_results()
    outputs = [
        render_concept(data),
        render_method(data),
        render_results(data),
    ]
    for path in outputs:
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"Render failed or produced an empty file: {path}")
        print(path)


if __name__ == "__main__":
    main()
