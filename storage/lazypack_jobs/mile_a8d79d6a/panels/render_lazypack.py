#!/usr/bin/env python3
"""Render the three data-bound VolPred drone EP0 lazypack panels.

All market statistics are loaded from ``drone_ep0_market_snapshot.json``.
Policy, capacity, and series facts that exist only in the article are extracted
from the supplied Markdown evidence.  Required fields and phrases deliberately
raise on absence so a changed evidence package cannot silently produce stale art.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import textwrap
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULTS_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "drone_ep0_market_snapshot.json"
)
DRAFT_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/drafts/"
    "drone_ep0_general_draft.md"
)
ARTICLE_PATH = Path(
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a8d79d6a/panels/mile_a8d79d6a_article.md"
)
out_dir = (
    "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/"
    "mile_a8d79d6a/panels"
)

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#102A43"
NAVY_2 = "#173F5F"
BLUE = "#1F6FA8"
TEAL = "#168A89"
GOLD = "#D69E2E"
RED = "#C94C4C"
INK = "#1D2B3A"
MUTED = "#5D6B78"
LIGHT = "#F4F7FA"
PALE_BLUE = "#EAF3F9"
PALE_TEAL = "#E8F5F3"
PALE_GOLD = "#FBF4E5"
PALE_RED = "#FAECEC"
BORDER = "#D8E1E8"
WHITE = "#FFFFFF"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object: {path}")
    return payload


def load_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Evidence file is empty: {path}")
    return text


def required(mapping: dict[str, Any], *keys: str) -> Any:
    cursor: Any = mapping
    walked: list[str] = []
    for key in keys:
        walked.append(key)
        if not isinstance(cursor, dict) or key not in cursor:
            raise KeyError("Missing required JSON field: " + ".".join(walked))
        cursor = cursor[key]
    return cursor


def required_number(mapping: dict[str, Any], *keys: str) -> float:
    value = required(mapping, *keys)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected number at {'.'.join(keys)}; got {value!r}")
    return float(value)


def required_int(mapping: dict[str, Any], *keys: str) -> int:
    value = required_number(mapping, *keys)
    if not value.is_integer():
        raise ValueError(f"Expected integer at {'.'.join(keys)}; got {value}")
    return int(value)


def required_string(mapping: dict[str, Any], *keys: str) -> str:
    value = required(mapping, *keys)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"Expected non-empty string at {'.'.join(keys)}")
    return value


def require_fragment(text: str, fragment: str, label: str) -> str:
    if fragment not in text:
        raise ValueError(f"Missing required article evidence for {label}: {fragment}")
    return fragment


def require_match(pattern: str, text: str, label: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if match is None:
        raise ValueError(f"Missing required article evidence for {label}")
    return match


def pct(value: float, signed: bool = False) -> str:
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value * 100:.1f}%"


def wrap_zh(text: str, width: int) -> str:
    """Wrap Chinese or mixed text at deterministic character widths."""
    wrapper = textwrap.TextWrapper(
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
        drop_whitespace=True,
    )
    return "\n".join(
        wrapper.fill(line) if line else "" for line in text.splitlines()
    )


def extract_article_facts(article_text: str) -> dict[str, Any]:
    verify_date = require_match(
        r"代碼與板別在 (\d{4}-\d{2}-\d{2})",
        article_text,
        "名冊查證日",
    ).group(1)

    policy = require_match(
        r"\| 無人載具採購特別條例草案 \| "
        r"(\d{4}-\d{2}-\d{2}) 排定三委員會聯席審查；尚未完成立法 \| "
        r"上限 ([\d,]+) 億元；草案公開文本未列總採購數量 \|",
        article_text,
        "無人載具採購特別條例草案",
    )
    planned_usv = require_match(
        r"小型自殺無人艇 ([\d,]+) 艘",
        article_text,
        "小型自殺無人艇規畫數量",
    )
    realized_output = require_match(
        r"(\d{4}) 年無人機產值是 ([\d,]+) 億元",
        article_text,
        "已實現無人機產值",
    )
    monthly_capacity_target = require_match(
        r"月產能 ([\d,]+) 架，是政策目標",
        article_text,
        "月產能政策目標",
    )
    output_target = require_match(
        r"(\d{4}) 年產值目標列為 ([\d,]+) 億元",
        article_text,
        "產值政策目標",
    )

    # These prose claims are required content but have no structured JSON field.
    for fragment, label in [
        ("百萬美元等級的攔截彈", "攔截成本"),
        ("幾萬元的無人機", "無人機成本"),
        ("不含中國零件", "非紅供應鏈"),
        ("最像半導體劇本的候選人", "台灣定位"),
        ("已停止公開發行", "經緯航太排除原因"),
        ("世紀鋼", "世紀鋼排除"),
        ("佳龍", "佳龍排除"),
        ("查不到明確的無人載具業務描述", "業務證據不足"),
        ("描述用的截面統計，不是可交易策略", "描述性統計限制"),
        ("不是投資建議", "投資建議限制"),
        ("EP1 上游晶片", "EP1"),
        ("EP2 中游機體", "EP2"),
        ("EP3 下游整機", "EP3"),
        ("EP4 挑幾家純度最高", "EP4"),
        ("EP-Final 收在投資組合、風險與台灣的全球定位", "EP-Final"),
        ("主要是 AI 晶片行情推的，跟無人機幾乎無關", "聯發科歸因"),
        ("2,100 億是草案上限，不是公司訂單", "政策上限限制"),
        ("目前公開草案文本沒有列出這個總採購數量", "總採購數量更正"),
        ("撤回 21 萬架與 20 倍缺口兩項說法", "舊口徑撤回"),
        ("不是目前已實現的月產量", "產能目標限制"),
        ("不能再用媒體區間除以規畫數量", "產能倍數限制"),
    ]:
        require_fragment(article_text, fragment, label)

    return {
        "verify_date": verify_date,
        "policy_review_date": policy.group(1),
        "policy_budget_e8": int(policy.group(2).replace(",", "")),
        "planned_usv_units": int(planned_usv.group(1).replace(",", "")),
        "realized_output_year": int(realized_output.group(1)),
        "realized_output_e8": int(realized_output.group(2).replace(",", "")),
        "monthly_capacity_target": int(monthly_capacity_target.group(1).replace(",", "")),
        "output_target_year": int(output_target.group(1)),
        "output_target_e8": int(output_target.group(2).replace(",", "")),
    }


def build_evidence() -> dict[str, Any]:
    results = load_json_object(RESULTS_PATH)
    # Both Markdown inputs are intentionally read.  The render uses the article
    # as the canonical prose surface and confirms the draft contains the same
    # core title, preventing accidental cross-article rendering.
    draft_text = load_text(DRAFT_PATH)
    article_text = load_text(ARTICLE_PATH)
    title_fragment = "無人載具｜EP0"
    require_fragment(draft_text, title_fragment, "草稿標題")
    require_fragment(article_text, title_fragment, "文章標題")

    n_names = required_int(results, "basket", "n_names")
    names = required(results, "names")
    if not isinstance(names, list):
        raise TypeError("Expected names to be a list")
    if len(names) != n_names:
        raise ValueError(
            f"basket.n_names={n_names}, but names contains {len(names)} rows"
        )

    vols: list[float] = []
    mediatek_rows: list[dict[str, Any]] = []
    for index, row in enumerate(names):
        if not isinstance(row, dict):
            raise TypeError(f"names[{index}] is not an object")
        vol = row.get("vol_ann")
        if isinstance(vol, bool) or not isinstance(vol, (int, float)):
            raise TypeError(f"names[{index}].vol_ann is missing or non-numeric")
        vols.append(float(vol))
        if row.get("name") == "聯發科":
            mediatek_rows.append(row)
    if len(mediatek_rows) != 1:
        raise ValueError(f"Expected exactly one 聯發科 row; found {len(mediatek_rows)}")
    mediatek = mediatek_rows[0]
    for key in ("mcap_e8", "ret_1y"):
        if isinstance(mediatek.get(key), bool) or not isinstance(
            mediatek.get(key), (int, float)
        ):
            raise TypeError(f"聯發科.{key} is missing or non-numeric")

    total_mcap_e8 = required_number(results, "total_mcap_e8")
    if total_mcap_e8 <= 0:
        raise ValueError("total_mcap_e8 must be positive")

    article = extract_article_facts(article_text)
    return {
        "n_names": n_names,
        "basket_return": required_number(results, "basket", "ret_1y"),
        "benchmark_return": required_number(results, "benchmark", "ret_1y"),
        "excess_return": required_number(
            results, "basket", "excess_ret_vs_bench"
        ),
        "basket_construction": required_string(
            results, "basket", "construction"
        ),
        "n_beat_benchmark": required_int(results, "n_beat_bench"),
        "n_vol_above_benchmark": required_int(results, "n_vol_above_bench"),
        "benchmark_vol": required_number(results, "benchmark", "vol_ann"),
        "median_name_vol": statistics.median(vols),
        "total_mcap_e8": total_mcap_e8,
        "mediatek_mcap_share": float(mediatek["mcap_e8"]) / total_mcap_e8,
        "mediatek_return": float(mediatek["ret_1y"]),
        "window_start": required_string(results, "window", "start"),
        "window_end": required_string(results, "window", "end"),
        "trading_days": required_int(results, "window", "trading_days"),
        "benchmark_ticker": required_string(results, "benchmark", "ticker"),
        "data_source": required_string(results, "data_source"),
        **article,
    }


def new_canvas(title: str, subtitle: str, accent: str = TEAL):
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0.84), 1, 0.16, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0.055, 0.872), 0.008, 0.078, facecolor=accent, edgecolor="none"))
    ax.text(
        0.079,
        0.925,
        title,
        ha="left",
        va="center",
        color=WHITE,
        fontsize=25,
        fontweight="bold",
    )
    ax.text(
        0.079,
        0.875,
        subtitle,
        ha="left",
        va="center",
        color="#D7E6F2",
        fontsize=12.5,
    )
    return fig, ax


def add_card(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = BORDER,
    linewidth: float = 1.0,
    radius: float = 0.012,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.006,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
    )
    ax.add_patch(patch)
    return patch


def add_step_badge(ax, x: float, y: float, label: str, color: str):
    ax.add_patch(Circle((x, y), 0.026, facecolor=color, edgecolor="none"))
    ax.text(
        x,
        y,
        label,
        ha="center",
        va="center",
        color=WHITE,
        fontsize=11,
        fontweight="bold",
    )


def add_footer(ax, evidence: dict[str, Any]):
    ax.plot([0.055, 0.945], [0.066, 0.066], color=BORDER, linewidth=0.9)
    ax.text(
        0.055,
        0.035,
        f"資料來源：drone_ep0_market_snapshot.json／{evidence['data_source']}",
        ha="left",
        va="center",
        color=MUTED,
        fontsize=9.3,
    )


def save_panel(fig, filename: str):
    os.makedirs(out_dir, exist_ok=True)
    fig.savefig(
        os.path.join(out_dir, filename),
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
    )
    plt.close(fig)


def render_framework(evidence: dict[str, Any]):
    fig, ax = new_canvas(
        "無人載具 EP0｜台灣接得穩嗎？",
        "六集系列總覽：先釐清戰場需求、供應鏈條件與概念股純度",
        accent=TEAL,
    )

    ax.text(
        0.055,
        0.805,
        "一條從戰場成本一路連到台灣製造的問題鏈",
        ha="left",
        va="center",
        color=INK,
        fontsize=16.5,
        fontweight="bold",
    )

    flow = [
        (
            0.055,
            "戰場現實",
            "百萬美元等級攔截彈\n對上幾萬元無人機\n防守方先承受不起",
            PALE_RED,
            RED,
        ),
        (
            0.367,
            "民主陣營的選擇",
            "建立不含中國零件的\n「非紅供應鏈」\n降低關鍵零組件風險",
            PALE_GOLD,
            GOLD,
        ),
        (
            0.679,
            "台灣被點名",
            "複製半導體供應鏈劇本\n把電子與製造能力\n轉成無人載具產能",
            PALE_TEAL,
            TEAL,
        ),
    ]
    for i, (x, title, body, fill, color) in enumerate(flow):
        add_card(ax, x, 0.646, 0.266, 0.125, facecolor=fill, edgecolor=color)
        ax.text(
            x + 0.018,
            0.739,
            title,
            ha="left",
            va="center",
            color=color,
            fontsize=13.3,
            fontweight="bold",
        )
        ax.text(
            x + 0.018,
            0.684,
            body,
            ha="left",
            va="center",
            color=INK,
            fontsize=9.8,
            linespacing=1.3,
        )
        if i < 2:
            ax.annotate(
                "",
                xy=(x + 0.303, 0.708),
                xytext=(x + 0.273, 0.708),
                arrowprops=dict(arrowstyle="-|>", color=NAVY_2, lw=1.8),
            )

    add_card(ax, 0.055, 0.565, 0.89, 0.055, facecolor=NAVY_2, edgecolor=NAVY_2)
    ax.text(
        0.5,
        0.592,
        "核心問題：題材與政策都到位之後，台灣真的接得穩嗎？",
        ha="center",
        va="center",
        color=WHITE,
        fontsize=15,
        fontweight="bold",
    )

    ax.text(
        0.055,
        0.523,
        "先用白話分清三個名詞",
        ha="left",
        va="center",
        color=INK,
        fontsize=16.5,
        fontweight="bold",
    )

    glossary = [
        (
            0.055,
            "無人載具",
            "不只空中的無人機，\n也包含海上的無人艇 USV。",
            "01",
            BLUE,
            PALE_BLUE,
        ),
        (
            0.36,
            "非紅供應鏈",
            "零組件來源不含中國，\n重點是可控、可追溯、可替代。",
            "02",
            TEAL,
            PALE_TEAL,
        ),
        (
            0.665,
            "概念股純度",
            "看無人機營收占比，\n別只看技術上是否說得通。",
            "03",
            GOLD,
            PALE_GOLD,
        ),
    ]
    for x, title, body, badge, color, fill in glossary:
        add_card(ax, x, 0.306, 0.28, 0.18, facecolor=fill, edgecolor=color)
        add_step_badge(ax, x + 0.038, 0.447, badge, color)
        ax.text(
            x + 0.076,
            0.447,
            title,
            ha="left",
            va="center",
            color=INK,
            fontsize=14.8,
            fontweight="bold",
        )
        ax.text(
            x + 0.025,
            0.368,
            body,
            ha="left",
            va="center",
            color=INK,
            fontsize=11.2,
            linespacing=1.5,
        )

    add_card(ax, 0.055, 0.102, 0.89, 0.16, facecolor=LIGHT, edgecolor=BORDER)
    ax.text(
        0.075,
        0.226,
        "系列路線｜EP0 總覽，EP1–EP4 與 EP-Final 逐層深挖",
        ha="left",
        va="center",
        color=NAVY,
        fontsize=14.2,
        fontweight="bold",
    )
    series = [
        ("EP0", "總覽"),
        ("EP1", "上游晶片"),
        ("EP2", "中游產能"),
        ("EP3", "下游＋USV"),
        ("EP4", "公司純度"),
        ("EP-Final", "組合風險"),
    ]
    start_x = 0.075
    pill_w = 0.132
    gap = 0.012
    for i, (ep, topic) in enumerate(series):
        x = start_x + i * (pill_w + gap)
        selected = i == 0
        add_card(
            ax,
            x,
            0.125,
            pill_w,
            0.067,
            facecolor=NAVY_2 if selected else WHITE,
            edgecolor=NAVY_2 if selected else BORDER,
            radius=0.01,
        )
        ax.text(
            x + pill_w / 2,
            0.158,
            f"{ep}｜{topic}",
            ha="center",
            va="center",
            color=WHITE if selected else INK,
            fontsize=9.3,
            fontweight="bold" if selected else "normal",
        )

    add_footer(ax, evidence)
    save_panel(fig, "1_framework.png")


def render_method(evidence: dict[str, Any]):
    fig, ax = new_canvas(
        "怎麼算的｜三步把題材放回市場檢驗",
        "同一份名冊、同一段窗口、同一個大盤基準；只做描述，不做買賣訊號",
        accent=BLUE,
    )

    cards = [
        {
            "y": 0.625,
            "h": 0.168,
            "number": "1",
            "color": BLUE,
            "fill": PALE_BLUE,
            "title": "先盤出可交易、可查證的上市櫃名冊",
            "body": (
                f"股票代碼與板別於 {evidence['verify_date']} 用 yfinance 逐檔查證；"
                "經緯航太因停止公開發行排除，世紀鋼與佳龍因查無明確業務證據不列入。"
            ),
            "metric": f"{evidence['n_names']}",
            "unit": "檔台股",
        },
        {
            "y": 0.422,
            "h": 0.168,
            "number": "2",
            "color": TEAL,
            "fill": PALE_TEAL,
            "title": "把名冊等權買進，觀察完整一年",
            "body": (
                f"{evidence['window_start']} 至 {evidence['window_end']}；"
                f"{evidence['basket_construction']}。所有公司用同一套規則。"
            ),
            "metric": f"{evidence['trading_days']}",
            "unit": "個交易日",
        },
        {
            "y": 0.219,
            "h": 0.168,
            "number": "3",
            "color": GOLD,
            "fill": PALE_GOLD,
            "title": "跟直接買台股加權指數比較",
            "body": (
                "在完全相同的時間窗口，比較近一年報酬與年化波動；"
                "回答的是這批股票過去一年表現如何。"
            ),
            "metric": evidence["benchmark_ticker"],
            "unit": "大盤基準",
        },
    ]

    for card in cards:
        y = card["y"]
        add_card(
            ax,
            0.055,
            y,
            0.89,
            card["h"],
            facecolor=WHITE,
            edgecolor=card["color"],
            linewidth=1.2,
        )
        ax.add_patch(
            Rectangle(
                (0.055, y),
                0.012,
                card["h"],
                facecolor=card["color"],
                edgecolor="none",
            )
        )
        add_step_badge(ax, 0.105, y + card["h"] / 2, card["number"], card["color"])
        ax.text(
            0.151,
            y + 0.121,
            card["title"],
            ha="left",
            va="center",
            color=INK,
            fontsize=15.2,
            fontweight="bold",
        )
        ax.text(
            0.151,
            y + 0.057,
            wrap_zh(card["body"], 42),
            ha="left",
            va="center",
            color=MUTED,
            fontsize=10.6,
            linespacing=1.42,
        )
        ax.plot(
            [0.765, 0.765],
            [y + 0.025, y + card["h"] - 0.025],
            color=BORDER,
            linewidth=1.0,
        )
        ax.text(
            0.85,
            y + 0.102,
            card["metric"],
            ha="center",
            va="center",
            color=card["color"],
            fontsize=25 if card["number"] != "3" else 19,
            fontweight="bold",
        )
        ax.text(
            0.85,
            y + 0.049,
            card["unit"],
            ha="center",
            va="center",
            color=MUTED,
            fontsize=10.4,
        )

    add_card(ax, 0.055, 0.102, 0.89, 0.078, facecolor=NAVY_2, edgecolor=NAVY_2)
    ax.text(
        0.5,
        0.141,
        "描述性截面統計　｜　不是可交易策略　｜　不是投資建議",
        ha="center",
        va="center",
        color=WHITE,
        fontsize=14.4,
        fontweight="bold",
    )

    add_footer(ax, evidence)
    save_panel(fig, "2_method.png")


def draw_return_bar(
    ax,
    y: float,
    label: str,
    value: float,
    maximum: float,
    color: str,
):
    ax.text(0.073, y + 0.014, label, ha="left", va="center", color=INK, fontsize=10.4)
    bar_x = 0.19
    bar_w = 0.31
    fill_ratio = value / maximum
    ax.add_patch(
        FancyBboxPatch(
            (bar_x, y),
            bar_w,
            0.028,
            boxstyle="round,pad=0,rounding_size=0.007",
            facecolor="#E6ECF1",
            edgecolor="none",
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (bar_x, y),
            bar_w * fill_ratio,
            0.028,
            boxstyle="round,pad=0,rounding_size=0.007",
            facecolor=color,
            edgecolor="none",
        )
    )
    ax.text(
        bar_x + bar_w - 0.01,
        y + 0.014,
        pct(value, signed=True),
        ha="right",
        va="center",
        color=WHITE if fill_ratio >= 0.85 else color,
        fontsize=11.5,
        fontweight="bold",
    )


def render_results(evidence: dict[str, Any]):
    fig, ax = new_canvas(
        "結果｜題材很熱，但整籃仍跑輸大盤",
        (
            f"市場窗口 {evidence['window_start']} 至 {evidence['window_end']}｜"
            f"{evidence['trading_days']} 個交易日"
        ),
        accent=RED,
    )

    # Return comparison.
    add_card(ax, 0.055, 0.635, 0.50, 0.16, facecolor=WHITE, edgecolor=BORDER)
    ax.text(
        0.073,
        0.766,
        "近一年報酬",
        ha="left",
        va="center",
        color=NAVY,
        fontsize=14.4,
        fontweight="bold",
    )
    max_return = max(evidence["basket_return"], evidence["benchmark_return"])
    if max_return <= 0:
        raise ValueError("Return bar chart requires a positive maximum return")
    draw_return_bar(
        ax,
        0.704,
        f"{evidence['n_names']} 檔等權籃",
        evidence["basket_return"],
        max_return,
        TEAL,
    )
    draw_return_bar(
        ax,
        0.656,
        "加權指數",
        evidence["benchmark_return"],
        max_return,
        BLUE,
    )

    add_card(ax, 0.58, 0.635, 0.365, 0.16, facecolor=PALE_RED, edgecolor=RED)
    ax.text(
        0.603,
        0.758,
        "相對大盤",
        ha="left",
        va="center",
        color=RED,
        fontsize=12.5,
        fontweight="bold",
    )
    ax.text(
        0.603,
        0.702,
        f"落後 {abs(evidence['excess_return']) * 100:.1f} 個百分點",
        ha="left",
        va="center",
        color=INK,
        fontsize=20.5,
        fontweight="bold",
    )
    ax.text(
        0.603,
        0.661,
        f"只有 {evidence['n_beat_benchmark']}/{evidence['n_names']} 檔跑贏大盤",
        ha="left",
        va="center",
        color=MUTED,
        fontsize=11.3,
    )

    # Volatility strip.
    add_card(ax, 0.055, 0.472, 0.89, 0.125, facecolor=NAVY_2, edgecolor=NAVY_2)
    ax.text(
        0.075,
        0.563,
        "波動成本",
        ha="left",
        va="center",
        color="#BFD7E8",
        fontsize=11.2,
        fontweight="bold",
    )
    risk_items = [
        (
            f"{evidence['n_vol_above_benchmark']}/{evidence['n_names']}",
            "個股波動全高於指數",
        ),
        (pct(evidence["benchmark_vol"]), "加權指數年化波動"),
        (pct(evidence["median_name_vol"]), "個股波動中位數"),
    ]
    for i, (value, label) in enumerate(risk_items):
        x = 0.075 + i * 0.285
        if i:
            ax.plot([x - 0.025, x - 0.025], [0.493, 0.574], color="#42647D", lw=1)
        ax.text(
            x,
            0.525,
            value,
            ha="left",
            va="center",
            color=WHITE,
            fontsize=20.5,
            fontweight="bold",
        )
        ax.text(
            x + 0.112,
            0.525,
            label,
            ha="left",
            va="center",
            color="#DCE8F0",
            fontsize=10.2,
        )

    # Three evidence blocks: concentration, policy, capacity.
    add_card(ax, 0.055, 0.176, 0.27, 0.255, facecolor=PALE_BLUE, edgecolor=BLUE)
    ax.text(
        0.075,
        0.397,
        "市值極度集中",
        ha="left",
        va="center",
        color=BLUE,
        fontsize=14.3,
        fontweight="bold",
    )
    ax.text(
        0.075,
        0.342,
        f"{evidence['total_mcap_e8'] / 10000:.2f} 兆元",
        ha="left",
        va="center",
        color=INK,
        fontsize=20.5,
        fontweight="bold",
    )
    ax.text(
        0.22,
        0.342,
        f"{evidence['n_names']} 家合計市值",
        ha="left",
        va="center",
        color=MUTED,
        fontsize=8.9,
    )
    ax.text(
        0.075,
        0.287,
        f"聯發科一家占 {pct(evidence['mediatek_mcap_share'])}",
        ha="left",
        va="center",
        color=BLUE,
        fontsize=12.1,
        fontweight="bold",
    )
    ax.text(
        0.075,
        0.225,
        wrap_zh(
            f"它的 {pct(evidence['mediatek_return'], signed=True)} 主要來自 AI 晶片行情，與無人機幾乎無關。",
            18,
        ),
        ha="left",
        va="center",
        color=INK,
        fontsize=8.8,
        linespacing=1.35,
    )

    add_card(ax, 0.345, 0.176, 0.36, 0.255, facecolor=WHITE, edgecolor=GOLD)
    ax.text(
        0.365,
        0.397,
        "政策上限｜還不是公司訂單",
        ha="left",
        va="center",
        color=GOLD,
        fontsize=13.6,
        fontweight="bold",
    )
    ax.text(
        0.365,
        0.337,
        f"上限 {evidence['policy_budget_e8']:,} 億元",
        ha="left",
        va="center",
        color=INK,
        fontsize=19.5,
        fontweight="bold",
    )
    ax.text(
        0.365,
        0.290,
        f"{evidence['policy_review_date']}｜三委員會聯席審查",
        ha="left",
        va="center",
        color=GOLD,
        fontsize=9.6,
        fontweight="bold",
    )
    ax.text(
        0.365,
        0.247,
        f"小型自殺無人艇 {evidence['planned_usv_units']:,} 艘｜規畫數量",
        ha="left",
        va="center",
        color=INK,
        fontsize=9.3,
    )
    ax.text(
        0.365,
        0.207,
        "尚未完成立法；草案未列總採購數量。",
        ha="left",
        va="center",
        color=MUTED,
        fontsize=8.8,
    )

    add_card(ax, 0.725, 0.176, 0.22, 0.255, facecolor=PALE_TEAL, edgecolor=TEAL)
    ax.text(
        0.745,
        0.397,
        "實績 ≠ 政策目標",
        ha="left",
        va="center",
        color=TEAL,
        fontsize=14.3,
        fontweight="bold",
    )
    ax.text(
        0.745,
        0.345,
        f"{evidence['realized_output_e8']:,} 億",
        ha="left",
        va="center",
        color=INK,
        fontsize=21,
        fontweight="bold",
    )
    ax.text(
        0.745,
        0.292,
        f"{evidence['realized_output_year']}｜已實現產值",
        ha="left",
        va="center",
        color=INK,
        fontsize=10.2,
    )
    ax.text(
        0.745,
        0.251,
        f"月產 {evidence['monthly_capacity_target']:,} 架｜目標",
        ha="left",
        va="center",
        color=INK,
        fontsize=10.2,
    )
    ax.text(
        0.745,
        0.208,
        f"{evidence['output_target_year']} 產值 {evidence['output_target_e8']:,} 億｜目標",
        ha="left",
        va="center",
        color=TEAL,
        fontsize=9.1,
        fontweight="bold",
    )

    add_card(ax, 0.055, 0.091, 0.89, 0.052, facecolor=LIGHT, edgecolor=BORDER)
    ax.text(
        0.5,
        0.117,
        "題材熱度寫在新聞裡，成本寫在波動率裡——值得研究，跟值得現在整籃買進，是兩回事。",
        ha="center",
        va="center",
        color=NAVY,
        fontsize=11.7,
        fontweight="bold",
    )

    add_footer(ax, evidence)
    save_panel(fig, "3_results.png")


def main():
    evidence = build_evidence()
    render_framework(evidence)
    render_method(evidence)
    render_results(evidence)


if __name__ == "__main__":
    main()
