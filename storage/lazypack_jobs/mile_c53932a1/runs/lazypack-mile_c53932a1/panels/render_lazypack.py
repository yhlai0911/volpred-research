#!/usr/bin/env python3
"""Render the four data-bound PNG panels for the mile_c53932a1 article."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


README_PATH = Path("/Users/yhlai0911/volpred-research/experiments/k775/README.md")
PLAN_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_c53932a1/runs/lazypack-mile_c53932a1/plan.json"
)
RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/experiments/k775/"
    "k775_har_pd_results.json"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_c53932a1/runs/lazypack-mile_c53932a1/panels/"
    "mile_c53932a1_article.md"
)
OUT_DIR = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_c53932a1/runs/lazypack-mile_c53932a1/panels"
)

SOURCE_LABEL = (
    "SPY 日收盤波動率模型比較實驗結果"
    "（滾動重新校準、樣本外逐日評分、統一預測目標）"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#13293D"
INK = "#172B3A"
MUTED = "#5D6B78"
LINE = "#DCE4EA"
PALE = "#F4F7F9"
WHITE = "#FFFFFF"
TEAL = "#087E8B"
TEAL_PALE = "#E6F3F4"
BLUE = "#2D5B88"
BLUE_PALE = "#EAF0F6"
AMBER = "#B06B16"
AMBER_PALE = "#FAF1E5"
RED = "#A83B3B"
RED_PALE = "#F9EAEA"
GREEN = "#287A55"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load every evidence-package file and validate the strict source label."""
    plan = load_json(PLAN_PATH)
    results = load_json(RESULTS_PATH)
    README_PATH.read_text(encoding="utf-8")
    ARTICLE_PATH.read_text(encoding="utf-8")

    label = plan["evidence"]["results"]["label"]
    if label != SOURCE_LABEL:
        raise ValueError(
            "plan.json 的 results 來源標籤與 strict plan 不一致："
            f"{label!r}"
        )
    return plan, results


def pointer(data: Any, json_pointer: str) -> Any:
    """Resolve an RFC-6901-style pointer; all missing fields raise."""
    if not json_pointer.startswith("/"):
        raise ValueError(f"JSON pointer 必須以 / 開頭：{json_pointer}")
    current = data
    for raw_part in json_pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(
                f"{json_pointer} 無法穿過 {type(current).__name__}"
            )
    return current


def number(results: dict[str, Any], path: str, digits: int = 3) -> str:
    value = pointer(results, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{path} 必須是數字，實際為 {type(value).__name__}")
    return f"{value:.{digits}f}"


def integer(results: dict[str, Any], path: str) -> str:
    value = pointer(results, path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{path} 必須是整數，實際為 {type(value).__name__}")
    return f"{value:d}"


def text_value(results: dict[str, Any], path: str) -> str:
    value = pointer(results, path)
    if not isinstance(value, str):
        raise TypeError(f"{path} 必須是文字，實際為 {type(value).__name__}")
    return value


def absolute_percent(
    results: dict[str, Any], path: str, digits: int = 2
) -> str:
    value = pointer(results, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{path} 必須是數字，實際為 {type(value).__name__}")
    return f"{abs(value):.{digits}f}%"


def new_canvas(title: str) -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(
        FancyBboxPatch(
            (0, 0.86),
            1,
            0.14,
            boxstyle="square,pad=0",
            linewidth=0,
            facecolor=NAVY,
        )
    )
    ax.text(
        0.055,
        0.93,
        title,
        color=WHITE,
        fontsize=29,
        fontweight="bold",
        va="center",
        ha="left",
    )
    return fig, ax


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LINE,
    linewidth: float = 1.2,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.012,rounding_size=0.014",
            linewidth=linewidth,
            edgecolor=edgecolor,
            facecolor=facecolor,
        )
    )


def wrap_lines(text: str, width: int) -> list[str]:
    lines = textwrap.wrap(
        text,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    )
    return lines or [""]


def draw_text_block(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    heading: str,
    paragraphs: Iterable[str],
    *,
    wrap_width: int,
    heading_size: int = 18,
    body_size: int = 14,
    line_step: float = 0.035,
    facecolor: str = PALE,
    accent: str = TEAL,
) -> None:
    rounded_box(ax, x, y, w, h, facecolor=facecolor)
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            0.008,
            h,
            boxstyle="round,pad=0,rounding_size=0.005",
            linewidth=0,
            facecolor=accent,
        )
    )
    ax.text(
        x + 0.025,
        y + h - 0.035,
        heading,
        color=INK,
        fontsize=heading_size,
        fontweight="bold",
        va="top",
        ha="left",
    )

    lines: list[str] = []
    for paragraph in paragraphs:
        wrapped = wrap_lines(paragraph, wrap_width)
        lines.append("• " + wrapped[0])
        lines.extend("   " + line for line in wrapped[1:])
    available = h - 0.105
    needed = len(lines) * line_step
    if needed > available:
        raise RuntimeError(
            f"文字區塊「{heading}」超出版位：需要 {needed:.3f}，"
            f"可用 {available:.3f}"
        )
    ax.text(
        x + 0.025,
        y + h - 0.092,
        "\n".join(lines),
        color=INK,
        fontsize=body_size,
        va="top",
        ha="left",
        linespacing=1.36,
    )


def draw_metric_card(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    label: str,
    value: str,
    note: str | None = None,
    color: str = TEAL,
    facecolor: str = WHITE,
    label_wrap: int = 16,
    value_size: int = 27,
    label_size: float = 12.5,
    note_size: float = 9.5,
) -> None:
    rounded_box(ax, x, y, w, h, facecolor=facecolor)
    label_lines = wrap_lines(label, label_wrap)
    if len(label_lines) > 2:
        raise RuntimeError(f"數據卡標籤超過兩行：{label}")
    ax.text(
        x + 0.018,
        y + h - 0.025,
        "\n".join(label_lines),
        color=MUTED,
        fontsize=label_size,
        va="top",
        ha="left",
        linespacing=1.22,
    )
    ax.text(
        x + 0.018,
        y + (0.070 if note else 0.038),
        value,
        color=color,
        fontsize=value_size,
        fontweight="bold",
        va="bottom",
        ha="left",
    )
    if note:
        note_lines = wrap_lines(note, max(12, label_wrap + 3))
        if len(note_lines) > 2:
            raise RuntimeError(f"數據卡註記超過兩行：{note}")
        ax.text(
            x + 0.018,
            y + 0.018,
            "\n".join(note_lines),
            color=MUTED,
            fontsize=note_size,
            va="bottom",
            ha="left",
            linespacing=1.18,
        )


def draw_footer(ax: plt.Axes) -> None:
    ax.plot([0.055, 0.945], [0.082, 0.082], color=LINE, linewidth=1)
    ax.text(
        0.055,
        0.047,
        "資料來源：" + SOURCE_LABEL,
        color=MUTED,
        fontsize=10.5,
        va="center",
        ha="left",
    )


def save_panel(fig: plt.Figure, filename: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    fig.savefig(
        os.path.join(OUT_DIR, filename),
        dpi=DPI,
        facecolor=WHITE,
        edgecolor=WHITE,
    )
    plt.close(fig)


def render_question(results: dict[str, Any]) -> None:
    fig, ax = new_canvas("明天會晃多大，五個模型同場考")
    draw_text_block(
        ax,
        0.055,
        0.19,
        0.54,
        0.60,
        "考法：每天現場作答",
        [
            "模型每天只用當天以前的資料猜隔天波動，隔天揭曉就記一次分，分數越低代表越準。",
            "參數不是算一次就放著，訓練資料隨時間往後長、定期重新校準，所以記分的日子模型都沒見過。",
            "評分規則對低估特別嚴格：把明天說得比實際平靜，扣分比說得比實際激烈更重。",
        ],
        wrap_width=22,
        heading_size=20,
        body_size=16,
        line_step=0.044,
        facecolor=PALE,
    )
    draw_metric_card(
        ax,
        0.63,
        0.51,
        0.315,
        0.28,
        label="被記分的樣本外交易日數",
        value=integer(results, "/n_oos"),
        color=TEAL,
        label_wrap=17,
        value_size=38,
    )
    draw_metric_card(
        ax,
        0.63,
        0.19,
        0.315,
        0.27,
        label="資料期間",
        value=text_value(results, "/data_period"),
        color=BLUE,
        label_wrap=17,
        value_size=19,
    )
    draw_footer(ax)
    save_panel(fig, "panel_question.png")


def render_new_features(results: dict[str, Any]) -> None:
    fig, ax = new_canvas("新版本多加了四個描述走勢的欄位")
    draw_text_block(
        ax,
        0.055,
        0.48,
        0.89,
        0.31,
        "加的是「最近走過什麼路」",
        [
            "底本是那個把短、中、長期波動疊起來的迴歸模型；新版本在它上面多餵四個欄位。",
            "四個欄位分別是短期均線相對長期均線的方向、兩條均線的乖離幅度、過去一個月的累積報酬、過去一個月的最大回落。",
            "想法很直觀：剛從高點摔下來的市場，跟慢慢往上爬的市場，就算當下波動一樣，隔天也不該一樣。",
        ],
        wrap_width=44,
        body_size=14,
        line_step=0.031,
        facecolor=PALE,
    )
    draw_metric_card(
        ax,
        0.055,
        0.18,
        0.27,
        0.23,
        label="只有底本的平均誤差分數",
        value=number(results, "/metrics/har_abs/qlike"),
        color=BLUE,
        label_wrap=15,
    )
    draw_metric_card(
        ax,
        0.365,
        0.18,
        0.27,
        0.23,
        label="底本加上四個新欄位之後",
        value=number(results, "/metrics/har_pd/qlike"),
        color=RED,
        label_wrap=15,
    )
    draw_metric_card(
        ax,
        0.675,
        0.18,
        0.27,
        0.23,
        label="加了之後反而退步",
        value=absolute_percent(
            results, "/har_pd_vs_har_abs/improvement_pct"
        ),
        note="這個差距沒有跨過我們設的門檻，跟雜訊分不開，只能說沒幫上忙",
        color=RED,
        facecolor=RED_PALE,
        label_wrap=13,
        value_size=24,
        note_size=8.5,
    )
    draw_footer(ax)
    save_panel(fig, "panel_new_features.png")


def render_ranking(results: dict[str, Any]) -> None:
    fig, ax = new_canvas("真正拉開距離的是模型家族")
    cards = [
        (
            "全期第一名：分開處理跌與漲的舊模型",
            number(results, "/metrics/amem/qlike"),
            GREEN,
            TEAL_PALE,
            None,
        ),
        (
            "全期第二名：同樣分開處理跌與漲",
            number(results, "/metrics/gjr/qlike"),
            BLUE,
            BLUE_PALE,
            None,
        ),
        (
            "全期最後一名：底本加四個新欄位",
            number(results, "/metrics/har_pd/qlike"),
            RED,
            RED_PALE,
            None,
        ),
        (
            "波動大的那一半：新版本更吃力",
            number(results, "/subperiod_analysis/high_vol/har_pd/qlike"),
            AMBER,
            AMBER_PALE,
            "同一段裡沒加欄位的底本更準",
        ),
    ]
    for index, (label, value, color, facecolor, note) in enumerate(cards):
        draw_metric_card(
            ax,
            0.055 + index * 0.225,
            0.595,
            0.205,
            0.20,
            label=label,
            value=value,
            note=note,
            color=color,
            facecolor=facecolor,
            label_wrap=10,
            value_size=22,
            label_size=11.5,
            note_size=8.5,
        )

    draw_text_block(
        ax,
        0.055,
        0.17,
        0.425,
        0.40,
        "家族之間的差距，遠大於加不加欄位",
        [
            "前兩名贏過底本的幅度，統計強度遠遠超過門檻，大到幾乎不可能是運氣。",
            "同一份資料裡，換掉模型家族帶來的改善，是加那四個欄位那件事的好幾倍，而且方向相反。",
        ],
        wrap_width=20,
        heading_size=16,
        body_size=13,
        line_step=0.036,
        facecolor=PALE,
        accent=TEAL,
    )
    draw_text_block(
        ax,
        0.52,
        0.17,
        0.425,
        0.40,
        "切成兩半，冠亞軍沒換人",
        [
            "按當期波動高低把樣本切成一半一半，前兩名在兩邊都是前兩名，排名不是某一段市況撐出來的。",
            "新版本在平靜的那一半反而小勝底本；它的墊底幾乎全部來自波動大的那一半——偏偏那正是最需要模型撐住的時候。",
        ],
        wrap_width=20,
        heading_size=16,
        body_size=13,
        line_step=0.036,
        facecolor=PALE,
        accent=BLUE,
    )
    draw_footer(ax)
    save_panel(fig, "panel_ranking.png")


def render_takeaway(results: dict[str, Any]) -> None:
    fig, ax = new_canvas("先確認模型有沒有把跌和漲分開")
    cards = [
        (
            "冠軍模型：漲跌一視同仁那一項的權重",
            number(results, "/full_sample_params/amem/alpha"),
            MUTED,
            PALE,
        ),
        (
            "冠軍模型：只在下跌日啟動的那一項",
            number(results, "/full_sample_params/amem/gamma"),
            GREEN,
            TEAL_PALE,
        ),
        (
            "亞軍模型：上漲的反應係數",
            number(results, "/full_sample_params/gjr/alpha"),
            MUTED,
            PALE,
        ),
        (
            "亞軍模型：下跌額外再加的係數",
            number(results, "/full_sample_params/gjr/gamma"),
            BLUE,
            BLUE_PALE,
        ),
    ]
    for index, (label, value, color, facecolor) in enumerate(cards):
        draw_metric_card(
            ax,
            0.055 + index * 0.225,
            0.605,
            0.205,
            0.19,
            label=label,
            value=value,
            color=color,
            facecolor=facecolor,
            label_wrap=10,
            value_size=22,
            label_size=11.5,
        )

    draw_text_block(
        ax,
        0.055,
        0.17,
        0.425,
        0.40,
        "補錯地方了",
        [
            "兩個贏家都把跌和漲當成兩件事；底本那一家用報酬的絕對值，漲一分跟跌一分算同一件事。",
            "新加的四個欄位補的是最近走勢的形狀，剛好不是模型缺的那一塊。拿到「在既有模型上加欄位」的作法，先確認底本是不是這份資料上最好的選擇。",
        ],
        wrap_width=20,
        heading_size=17,
        body_size=13,
        line_step=0.035,
        facecolor=PALE,
        accent=TEAL,
    )
    draw_text_block(
        ax,
        0.52,
        0.17,
        0.425,
        0.40,
        "別把結論拉得太遠",
        [
            "這是單一標的、單一資料頻率、單一評分規則的結果，換市場、換頻率、換評分方式，名次有可能重排。",
            "而且家族之間的差距是穩定但不誇張的高下之分，不是舊模型碾壓新模型。",
        ],
        wrap_width=20,
        heading_size=17,
        body_size=13,
        line_step=0.035,
        facecolor=PALE,
        accent=BLUE,
    )
    draw_footer(ax)
    save_panel(fig, "panel_takeaway.png")


def main() -> None:
    plan, results = load_evidence()
    expected_names = [
        "panel_question",
        "panel_new_features",
        "panel_ranking",
        "panel_takeaway",
    ]
    actual_names = [panel["name"] for panel in plan["panels"]]
    if actual_names != expected_names:
        raise ValueError(
            "plan.json 的 panel 順序或名稱與 renderer 契約不一致："
            f"{actual_names!r}"
        )

    render_question(results)
    render_new_features(results)
    render_ranking(results)
    render_takeaway(results)


if __name__ == "__main__":
    main()
