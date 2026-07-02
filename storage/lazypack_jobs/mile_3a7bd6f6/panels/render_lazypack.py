#!/usr/bin/env python3
"""Render data-bound PNG panels for the K1605 general-audience lazypack.

The renderer intentionally binds every displayed statistic to
experiments/k1605/k1605_results.json.  README/article files are checked as part
of the evidence package, but rendered numeric values come from results.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


ROOT = Path("/Users/yhlai0911/volpred-research")
RESULTS_PATH = ROOT / "experiments/k1605/k1605_results.json"
README_PATH = ROOT / "experiments/k1605/README.md"
ARTICLE_PATH = Path(
    "/var/folders/f1/g41vrs0n20v7cx66qzcsd1nc0000gn/T/tmpe09q8akv_article.md"
)
OUT_DIR = ROOT / "storage/lazypack_jobs/mile_3a7bd6f6/panels"

WIDTH = 1600
HEIGHT = 1000
DPI = 150
FONT_SCALE = 0.62

TMP_ROOT = Path(os.environ.get("TMPDIR", "/tmp"))
os.environ.setdefault("MPLCONFIGDIR", str(TMP_ROOT / "volpred_lazypack_mplconfig"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager, rcParams  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.ft2font import FT2Font  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle  # noqa: E402


COLORS = {
    "ink": "#152033",
    "muted": "#5C6676",
    "faint": "#8A95A6",
    "navy": "#12213A",
    "navy2": "#182B49",
    "paper": "#FFFFFF",
    "warm": "#F6F3EC",
    "line": "#D9E0EA",
    "red": "#B9403A",
    "red_soft": "#F3D9D6",
    "teal": "#087F7A",
    "teal_soft": "#DCEFED",
    "blue": "#255D9B",
    "blue_soft": "#E0EAF6",
    "amber": "#A66A19",
    "amber_soft": "#F4E7CF",
    "green": "#24734D",
    "green_soft": "#DDEEE5",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def require_evidence() -> dict[str, Any]:
    for path in [RESULTS_PATH, README_PATH, ARTICLE_PATH]:
        if not path.exists():
            raise FileNotFoundError(path)
    return load_json(RESULTS_PATH)


def at(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            raise KeyError(path)
    return cur


def pct(data: dict[str, Any], path: str, decimals: int = 1) -> str:
    return f"{float(at(data, path)) * 100:.{decimals}f}%"


def num(data: dict[str, Any], path: str, decimals: int = 2) -> str:
    return f"{float(at(data, path)):.{decimals}f}"


def signed_num(data: dict[str, Any], path: str, decimals: int = 2) -> str:
    return f"{float(at(data, path)):+.{decimals}f}"


def intstr(data: dict[str, Any], path: str) -> str:
    return f"{int(at(data, path))}"


def footer_text(data: dict[str, Any]) -> str:
    exp = str(at(data, "experiment_id")).upper()
    return f"資料來源：experiment {exp}；k1605_results.json；yfinance"


def collect_panel_texts(data: dict[str, Any]) -> list[str]:
    return [
        "帳面價值慢半拍，市場價格先報警",
        "區域銀行 M/B 是風險溫度計",
        "M/B = 市值 / 帳面淨值",
        "帳面資料延後 45/75 天，訊號 shift(1)",
        "低於帳面比例",
        "KRE 22日波動率峰值",
        "低 M/B 對應後續較高波動",
        "第一階段檢查：控制 lagRV 後仍有增量訊號",
        "Fama-MacBeth",
        "邊界：這是風險溫度計，不是交易方向盤",
        "能支持：橫斷面壓力訊號",
        "不能過度宣稱：已驗證可交易預測",
        "倖存者樣本與價格混淆仍要保守解讀",
        footer_text(data),
        str(at(data, "diagnostics.end_date")),
        str(at(data, "descriptive.frac_below_book_max_date")),
    ]


def font_supports(path: str, texts: Iterable[str]) -> bool:
    charmap = FT2Font(path).get_charmap()
    for text in texts:
        for ch in text:
            if ch in "\n\t ":
                continue
            if ord(ch) not in charmap:
                return False
    return True


def choose_cjk_font(texts: Iterable[str]) -> tuple[FontProperties, FontProperties, str]:
    candidates = [
        "Heiti TC",
        "PingFang TC",
        "Arial Unicode MS",
        "Songti TC",
        "Hiragino Sans GB",
        "Noto Sans CJK TC",
        "Noto Sans TC",
    ]
    fonts = font_manager.fontManager.ttflist
    seen: set[str] = set()
    for candidate in candidates:
        matches = [
            f
            for f in fonts
            if candidate.lower() in f.name.lower()
            or candidate.lower() in Path(f.fname).name.lower()
        ]
        for font in matches:
            if font.fname in seen:
                continue
            seen.add(font.fname)
            if font_supports(font.fname, texts):
                rcParams["font.sans-serif"] = [font.name]
                rcParams["font.family"] = "sans-serif"
                rcParams["axes.unicode_minus"] = False
                regular = FontProperties(fname=font.fname)
                bold = FontProperties(fname=font.fname, weight="bold")
                return regular, bold, font.name
    raise RuntimeError("No installed CJK font supports all panel text.")


def new_canvas() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
    ax = plt.axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(HEIGHT, 0)
    ax.axis("off")
    fig.patch.set_facecolor(COLORS["paper"])
    ax.set_facecolor(COLORS["paper"])
    return fig, ax


def rounded(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    fc: str,
    ec: str | None = None,
    lw: float = 1.2,
    radius: float = 8,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=fc,
            edgecolor=ec or fc,
            linewidth=lw,
        )
    )


def text(
    ax: plt.Axes,
    x: float,
    y: float,
    s: str,
    size: int,
    color: str = "ink",
    weight: str = "regular",
    ha: str = "left",
    va: str = "top",
    linespacing: float = 1.15,
) -> None:
    prop = FONT_BOLD if weight == "bold" else FONT_REG
    ax.text(
        x,
        y,
        s,
        fontsize=size * FONT_SCALE,
        color=COLORS.get(color, color),
        fontproperties=prop,
        ha=ha,
        va=va,
        linespacing=linespacing,
    )


def small_source(ax: plt.Axes, data: dict[str, Any]) -> None:
    ax.plot([80, WIDTH - 80], [930, 930], color=COLORS["line"], lw=1)
    text(ax, 80, 954, footer_text(data), 22, "muted")


def panel1(data: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    ax.add_patch(Rectangle((0, 0), WIDTH, 155, facecolor=COLORS["navy"], edgecolor="none"))
    text(ax, 80, 44, "帳面價值慢半拍，市場價格先報警", 52, "#FFFFFF", "bold")
    text(
        ax,
        82,
        110,
        "區域銀行的 M/B 折價，可先看出市場對帳面淨值的懷疑程度",
        25,
        "#D8E2F0",
    )

    rounded(ax, 80, 205, 620, 620, COLORS["warm"], COLORS["line"], radius=8)
    text(ax, 125, 250, "M/B = 市值 / 帳面淨值", 46, "navy", "bold")
    text(ax, 126, 323, "市場價格每日更新；", 28, "muted")
    text(ax, 126, 368, "帳面淨值跟著財報慢慢更新。", 28, "muted")
    text(ax, 126, 413, f"帳面資料延後 {intstr(data, 'config.q_lag_days')}/{intstr(data, 'config.a_lag_days')} 天，訊號 shift(1)", 27, "muted")

    for x, label, fill in [
        (145, "價格\n每天", COLORS["blue_soft"]),
        (335, "帳面\n季報/年報", COLORS["amber_soft"]),
        (525, "未來\n波動", COLORS["teal_soft"]),
    ]:
        rounded(ax, x, 500, 130, 130, fill, COLORS["line"], radius=8)
        text(ax, x + 65, 532, label, 27, "ink", "bold", ha="center")
    ax.annotate(
        "",
        xy=(322, 565),
        xytext=(278, 565),
        arrowprops={"arrowstyle": "->", "lw": 2.2, "color": COLORS["faint"]},
    )
    ax.annotate(
        "",
        xy=(512, 565),
        xytext=(468, 565),
        arrowprops={"arrowstyle": "->", "lw": 2.2, "color": COLORS["faint"]},
    )
    text(ax, 126, 690, "這張圖只把 M/B 當壓力儀表，", 27, "ink", "bold")
    text(ax, 126, 732, "不把它直接當交易訊號。", 27, "ink", "bold")
    text(ax, 126, 782, "所有統計量皆來自 K1605 results.json。", 23, "muted")

    cards = [
        (
            760,
            205,
            360,
            180,
            "樣本銀行",
            f"{intstr(data, 'diagnostics.n_banks_book_usable')} 家",
            f"{at(data, 'descriptive.panel_effective_start')} 至 {at(data, 'diagnostics.end_date')}",
            COLORS["blue_soft"],
        ),
        (
            1140,
            205,
            360,
            180,
            "2023 壓力期",
            pct(data, "descriptive.frac_below_book_max"),
            f"低於帳面峰值：{at(data, 'descriptive.frac_below_book_max_date')}",
            COLORS["red_soft"],
        ),
        (
            760,
            425,
            360,
            180,
            "最新 M/B 中位數",
            num(data, "descriptive.mb_median_level_latest", 2),
            f"低於帳面比例 {pct(data, 'descriptive.frac_below_book_latest')}",
            COLORS["green_soft"],
        ),
        (
            1140,
            425,
            360,
            180,
            "KRE 22日波動率峰值",
            pct(data, "descriptive.stress_2023.kre_rv22_stress_max"),
            f"壓力前中位數 {pct(data, 'descriptive.stress_2023.kre_rv22_pre_median')}",
            COLORS["amber_soft"],
        ),
    ]
    for x, y, w, h, label, value, sub, fill in cards:
        rounded(ax, x, y, w, h, fill, COLORS["line"], radius=8)
        text(ax, x + 28, y + 28, label, 25, "muted", "bold")
        text(ax, x + 28, y + 77, value, 54, "ink", "bold")
        text(ax, x + 28, y + 142, sub, 20, "muted")

    rounded(ax, 760, 645, 720, 180, COLORS["paper"], COLORS["line"], radius=8)
    text(ax, 792, 683, "讀法", 25, "navy", "bold")
    text(
        ax,
        792,
        729,
        "當同一批區域銀行大量跌破帳面價值，",
        25,
        "muted",
        linespacing=1.28,
    )
    text(ax, 792, 770, "代表市場對帳本數字的信任正在下降。", 25, "muted")
    small_source(ax, data)
    fig.savefig(OUT_DIR / "1_concept.png", dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)


def draw_tbar(ax: plt.Axes, x: float, y: float, value: float, min_v: float = -4.5) -> None:
    w = 230
    h = 12
    ax.add_patch(Rectangle((x, y), w, h, facecolor="#EDF1F6", edgecolor="none"))
    zero_x = x + w
    bar_w = min(w, abs(value / min_v) * w)
    ax.add_patch(Rectangle((zero_x - bar_w, y), bar_w, h, facecolor=COLORS["red"], edgecolor="none"))
    threshold_x = zero_x - min(w, abs(-2.0 / min_v) * w)
    ax.plot([threshold_x, threshold_x], [y - 5, y + h + 5], color=COLORS["ink"], lw=1.2)


def bento_card(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    value: str,
    sub: str,
    fill: str,
    accent: str,
) -> None:
    rounded(ax, x, y, w, h, fill, COLORS["line"], radius=8)
    ax.add_patch(Rectangle((x, y), 8, h, facecolor=accent, edgecolor="none"))
    text(ax, x + 30, y + 26, title, 25, "muted", "bold")
    text(ax, x + 30, y + 74, value, 48, "ink", "bold")
    text(ax, x + 30, y + 136, sub, 21, "muted", linespacing=1.2)


def panel2(data: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    ax.add_patch(Rectangle((0, 0), WIDTH, HEIGHT, facecolor="#F8FAFC", edgecolor="none"))
    text(ax, 80, 60, "低 M/B 對應後續較高波動", 52, "navy", "bold")
    text(ax, 82, 124, "第一階段檢查：控制 lagRV 後仍有增量訊號", 27, "muted")

    rounded(ax, 80, 185, 520, 320, COLORS["navy"], COLORS["navy"], radius=8)
    text(ax, 120, 230, "達標的增量檢定", 29, "#D8E2F0", "bold")
    text(ax, 120, 292, intstr(data, "verdict.n_significant_incremental"), 120, "#FFFFFF", "bold")
    text(ax, 248, 332, "項", 43, "#FFFFFF", "bold")
    text(ax, 120, 430, "門檻：控制 lagRV、正確方向", 24, "#D8E2F0")
    text(ax, 120, 468, "|t| > 2.0", 24, "#D8E2F0")

    bento_card(
        ax,
        640,
        185,
        400,
        150,
        "Fama-MacBeth h5",
        signed_num(data, "firstlook.fama_macbeth_xs.h5.spec_B_control_lagRV.mean", 4),
        f"t={signed_num(data, 'firstlook.fama_macbeth_xs.h5.spec_B_control_lagRV.t')}；n={intstr(data, 'firstlook.fama_macbeth_xs.h5.spec_B_control_lagRV.n_days')}",
        COLORS["red_soft"],
        COLORS["red"],
    )
    bento_card(
        ax,
        1080,
        185,
        400,
        150,
        "Fama-MacBeth h22",
        signed_num(data, "firstlook.fama_macbeth_xs.h22.spec_B_control_lagRV.mean", 4),
        f"t={signed_num(data, 'firstlook.fama_macbeth_xs.h22.spec_B_control_lagRV.t')}；n={intstr(data, 'firstlook.fama_macbeth_xs.h22.spec_B_control_lagRV.n_days')}",
        COLORS["red_soft"],
        COLORS["red"],
    )
    bento_card(
        ax,
        640,
        370,
        400,
        150,
        "KRE 時序 h5 beta",
        signed_num(data, "firstlook.timeseries_etf.KRE.h5.reg_level_beta.1", 3),
        f"t={signed_num(data, 'firstlook.timeseries_etf.KRE.h5.reg_level_t.1')}；n={intstr(data, 'firstlook.timeseries_etf.KRE.h5.n')}",
        COLORS["blue_soft"],
        COLORS["blue"],
    )
    bento_card(
        ax,
        1080,
        370,
        400,
        150,
        "KBE 時序 h5 beta",
        signed_num(data, "firstlook.timeseries_etf.KBE.h5.reg_level_beta.1", 3),
        f"t={signed_num(data, 'firstlook.timeseries_etf.KBE.h5.reg_level_t.1')}；n={intstr(data, 'firstlook.timeseries_etf.KBE.h5.n')}",
        COLORS["blue_soft"],
        COLORS["blue"],
    )

    rounded(ax, 80, 555, 1400, 280, COLORS["paper"], COLORS["line"], radius=8)
    text(ax, 120, 592, "t 值橫向比較：越往左，代表低 M/B -> 高未來波動的證據越強", 28, "ink", "bold")
    rows = [
        ("FM h5", float(at(data, "firstlook.fama_macbeth_xs.h5.spec_B_control_lagRV.t"))),
        ("FM h22", float(at(data, "firstlook.fama_macbeth_xs.h22.spec_B_control_lagRV.t"))),
        ("KRE h5", float(at(data, "firstlook.timeseries_etf.KRE.h5.reg_level_t.1"))),
        ("KRE h22", float(at(data, "firstlook.timeseries_etf.KRE.h22.reg_level_t.1"))),
        ("KBE h5", float(at(data, "firstlook.timeseries_etf.KBE.h5.reg_level_t.1"))),
    ]
    for i, (label, value) in enumerate(rows):
        yy = 650 + i * 34
        text(ax, 120, yy - 8, label, 22, "muted", "bold")
        draw_tbar(ax, 235, yy, value)
        text(ax, 485, yy - 10, f"t={value:+.2f}", 22, "ink", "bold")
    text(ax, 770, 666, "註：Phase-1 first-look 使用 |t| > 2；", 24, "muted")
    text(ax, 770, 706, "正式 DM/Harvey |t| > 3 延後。", 24, "muted")
    text(ax, 770, 756, "負斜率/負 beta 代表 M/B 越低，後續波動越高。", 24, "muted")
    small_source(ax, data)
    fig.savefig(OUT_DIR / "2_results.png", dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)


def panel3(data: dict[str, Any]) -> None:
    fig, ax = new_canvas()
    ax.add_patch(Rectangle((0, 0), WIDTH, HEIGHT, facecolor="#FBFAF7", edgecolor="none"))
    text(ax, 80, 58, "邊界：這是風險溫度計，不是交易方向盤", 48, "navy", "bold")
    text(ax, 82, 120, "K1605 支持壓力分布的描述關係；預測與交易用途仍需更高門檻", 26, "muted")

    rounded(ax, 80, 190, 740, 590, COLORS["paper"], COLORS["line"], radius=8)
    text(ax, 125, 235, "低於帳面價值比例", 34, "ink", "bold")
    text(ax, 125, 286, "同一批銀行有多少市值跌到帳面淨值以下", 24, "muted")

    gauge_x, gauge_y, gauge_w, gauge_h = 150, 430, 600, 34
    ax.add_patch(Rectangle((gauge_x, gauge_y), gauge_w, gauge_h, facecolor="#E8EEF5", edgecolor="none"))
    ax.add_patch(Rectangle((gauge_x, gauge_y), gauge_w * 0.35, gauge_h, facecolor=COLORS["green_soft"], edgecolor="none"))
    ax.add_patch(Rectangle((gauge_x + gauge_w * 0.35, gauge_y), gauge_w * 0.35, gauge_h, facecolor=COLORS["amber_soft"], edgecolor="none"))
    ax.add_patch(Rectangle((gauge_x + gauge_w * 0.70, gauge_y), gauge_w * 0.30, gauge_h, facecolor=COLORS["red_soft"], edgecolor="none"))
    stress = float(at(data, "descriptive.frac_below_book_max"))
    latest = float(at(data, "descriptive.frac_below_book_latest"))
    for frac, color, label, dy in [
        (stress, COLORS["red"], f"壓力期 {pct(data, 'descriptive.frac_below_book_max')}", -96),
        (latest, COLORS["green"], f"最新 {pct(data, 'descriptive.frac_below_book_latest')}", 64),
    ]:
        px = gauge_x + gauge_w * frac
        ax.plot([px, px], [gauge_y - 22, gauge_y + gauge_h + 22], color=color, lw=3)
        ax.add_patch(Circle((px, gauge_y + gauge_h / 2), 11, facecolor=color, edgecolor="white", lw=2))
        text(ax, px, gauge_y + dy, label, 30, color, "bold", ha="center")
    text(ax, gauge_x, gauge_y + 58, "0%", 20, "faint")
    text(ax, gauge_x + gauge_w, gauge_y + 58, "100%", 20, "faint", ha="right")

    rounded(ax, 125, 585, 310, 135, COLORS["red_soft"], "none", radius=8)
    text(ax, 155, 617, at(data, "descriptive.frac_below_book_max_date"), 25, "red", "bold")
    text(ax, 155, 657, "壓力期峰值日期", 22, "muted")
    rounded(ax, 470, 585, 300, 135, COLORS["green_soft"], "none", radius=8)
    text(ax, 500, 617, at(data, "diagnostics.end_date"), 25, "green", "bold")
    text(ax, 500, 657, "最新樣本日期", 22, "muted")

    rounded(ax, 875, 190, 605, 170, COLORS["teal_soft"], COLORS["line"], radius=8)
    text(ax, 910, 225, "能支持", 28, "teal", "bold")
    text(ax, 910, 276, f"{intstr(data, 'verdict.n_significant_incremental')} 項增量檢定達標", 30, "ink", "bold")
    text(ax, 910, 316, f"verdict = {at(data, 'verdict.label')}", 24, "ink", "bold")
    text(ax, 910, 345, "低 M/B 與較高後續 RV 的橫斷面關係。", 23, "muted")

    rounded(ax, 875, 390, 605, 170, COLORS["amber_soft"], COLORS["line"], radius=8)
    text(ax, 910, 425, "不能過度宣稱", 28, "amber", "bold")
    text(ax, 910, 476, "不是已驗證的可交易預測模型", 30, "ink", "bold")
    text(ax, 910, 523, "results.json 註明：DM/Harvey 與 OOS refit 延後。", 23, "muted")

    rounded(ax, 875, 590, 605, 190, COLORS["paper"], COLORS["line"], radius=8)
    text(ax, 910, 624, "兩個保守解讀理由", 28, "navy", "bold")
    text(ax, 910, 676, "1. SVB/SBNY/FRC 等失敗銀行不在倖存者樣本。", 23, "muted")
    text(ax, 910, 718, "2. Daily M/B 多半由價格變動驅動，仍有價格混淆。", 23, "muted")
    small_source(ax, data)
    fig.savefig(OUT_DIR / "3_boundary.png", dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)


def verify_outputs() -> None:
    for name in ["1_concept.png", "2_results.png", "3_boundary.png"]:
        path = OUT_DIR / name
        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError(f"Missing or empty output: {path}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = require_evidence()
    global FONT_REG, FONT_BOLD
    FONT_REG, FONT_BOLD, font_name = choose_cjk_font(collect_panel_texts(data))
    print(f"Using CJK font: {font_name}")
    panel1(data)
    panel2(data)
    panel3(data)
    verify_outputs()
    for name in ["1_concept.png", "2_results.png", "3_boundary.png"]:
        path = OUT_DIR / name
        print(f"{path} {path.stat().st_size} bytes")


FONT_REG: FontProperties
FONT_BOLD: FontProperties


if __name__ == "__main__":
    main()
