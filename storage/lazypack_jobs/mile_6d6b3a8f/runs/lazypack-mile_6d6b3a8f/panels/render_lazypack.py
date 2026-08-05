#!/usr/bin/env python3
"""render_lazypack.py - VolPred mile_6d6b3a8f 懶人包圖組渲染程式.

獨立可執行程式，無頭環境下讀取 K1700 實驗結果與 plan.json 數據，
為此文章繪製三張獨立的高畫質 PNG 懶人包圖卡：
  1_concept.png  - 概念與歷史滾動視窗
  2_results.png  - 達標區間數與 CAGR 分布結果
  3_takeaway.png - 槓桿與回撤代價 takeaway
"""

import os
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

# ─── 常數與硬規則 ─────────────────────────────────────────────────────────────
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_6d6b3a8f/runs/lazypack-mile_6d6b3a8f/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/K1700/k1700_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_6d6b3a8f/runs/lazypack-mile_6d6b3a8f/panels"

WIDTH = 1600
HEIGHT = 1000

# 統一設 Matplotlib 全域字型
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# 顏色與設計系統
COLOR_BG = "#F8FAFC"         # 畫布背景色 (Slate 50)
COLOR_INK = "#0F172A"        # 主標題/數字黑 (Slate 900)
COLOR_MUTED = "#475569"      # 副標與說明文字 (Slate 600)
COLOR_FAINT = "#64748B"      # 頁尾/淡色 (Slate 500)
COLOR_BORDER = "#E2E8F0"     # 卡片邊框 (Slate 200)
COLOR_CARD = "#FFFFFF"       # 白底卡片

COLOR_TEAL = "#0D9488"       # 主調 Teal
COLOR_TEAL_BG = "#F0FDFA"    # Teal 淡底
COLOR_TEAL_BORDER = "#CCFBF1"

COLOR_BLUE = "#2563EB"       # 主調 Blue
COLOR_BLUE_BG = "#EFF6FF"    # Blue 淡底
COLOR_BLUE_BORDER = "#DBEAFE"

COLOR_RED = "#E11D48"        # 主調 Red
COLOR_RED_BG = "#FFF1F2"     # Red 淡底
COLOR_RED_BORDER = "#FFE4E6"

COLOR_AMBER = "#D97706"      # 主調 Amber
COLOR_AMBER_BG = "#FFF7ED"   # Amber 淡底
COLOR_AMBER_BORDER = "#FFEDD5"

COLOR_GREEN = "#16A34A"      # 主調 Green
COLOR_GREEN_BG = "#F0FDF4"   # Green 淡底
COLOR_GREEN_BORDER = "#DCFCE7"


# ─── 資料讀取與格式化 Helper ──────────────────────────────────────────────────
def load_json(path_str: str) -> Dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Missing essential file: {path_str}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_value_by_path(data: Any, path_str: str) -> Any:
    """依點號與數字索引從 nested json 讀取數值，缺失即 raise KeyError/IndexError."""
    cur = data
    for part in path_str.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Field '{part}' missing from dict in path '{path_str}'")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                idx = int(part)
                cur = cur[idx]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Invalid list index '{part}' in path '{path_str}'") from e
        else:
            raise KeyError(f"Cannot traverse non-container type {type(cur).__name__} at '{part}' in path '{path_str}'")
    return cur


def format_metric(val: Any, fmt_spec: Dict[str, Any]) -> str:
    kind = fmt_spec.get("kind", "str")
    digits = fmt_spec.get("digits", 2)
    suffix = fmt_spec.get("suffix", "")

    if kind == "number":
        return f"{float(val):.{digits}f}{suffix}"
    elif kind == "integer":
        return f"{int(round(val)):,}{suffix}"
    elif kind == "percent":
        return f"{float(val) * 100:.{digits}f}%{suffix}"
    else:
        return f"{val}{suffix}"


# ─── PIL 字型與繪圖 Helper ─────────────────────────────────────────────────────
def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("Heiti TC", size=size)
    except Exception:
        return ImageFont.load_default()


def wrap_cjk_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """專為 CJK 中文字串精確折行，確保不會溢出 max_width."""
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            test = current + char
            bbox = draw.textbbox((0, 0), test, font=font)
            w = bbox[2] - bbox[0]
            if w <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines


def draw_card(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    fill: str = COLOR_CARD,
    outline: str = COLOR_BORDER,
    radius: int = 16,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_header(
    draw: ImageDraw.ImageDraw,
    title: str,
    subtitle: str,
    tag_bg: str = COLOR_TEAL,
) -> None:
    """繪製標準深色頂部 Header 區塊 (x:60, y:45, w:1480, h:125)."""
    box = (60, 45, 1540, 170)
    draw_card(draw, box, fill=COLOR_INK, outline=COLOR_INK, radius=16)

    # Pill Tag
    draw.rounded_rectangle((85, 62, 215, 90), radius=6, fill=tag_bg)
    font_tag = load_font(15, bold=True)
    draw.text((100, 66), "VolPred 懶人包", font=font_tag, fill="#FFFFFF")

    # Subtitle on right of tag
    font_sub = load_font(18, bold=False)
    draw.text((230, 66), subtitle, font=font_sub, fill="#94A3B8")

    # Title
    font_title = load_font(32, bold=True)
    draw.text((85, 106), title, font=font_title, fill="#FFFFFF")


def draw_footer(draw: ImageDraw.ImageDraw, source_label: str) -> None:
    """繪製標準底部資料來源列 (y: 915 - 970)."""
    draw.line((60, 915, 1540, 915), fill=COLOR_BORDER, width=2)
    font_footer = load_font(18, bold=False)
    text = f"資料來源：{source_label}"
    draw.text((60, 932), text, font=font_footer, fill=COLOR_FAINT)


# ─── Panel 1 Render ───────────────────────────────────────────────────────────
def render_panel1(plan_panel: Dict[str, Any], results: Dict[str, Any], source_label: str) -> str:
    """Panel 1 - 1_concept.png (Style: professional)."""
    img = Image.new("RGB", (WIDTH, HEIGHT), COLOR_BG)
    draw = ImageDraw.Draw(img)

    title = plan_panel.get("title", "先問一件事：這個目標在歷史上出現過嗎")
    alt = plan_panel.get("alt", "說明目標換算、樣本期間與滾動視窗數")
    draw_header(draw, title, alt, tag_bg=COLOR_TEAL)

    # 提取 JSON 數據 (對應 blocks 的 3 個 metrics)
    val_mult = format_metric(get_value_by_path(results, "target_multiple_30y"), {"kind": "number", "digits": 2, "suffix": " 倍"})
    val_nwin = format_metric(get_value_by_path(results, "spx_total_return_30y.n_windows"), {"kind": "integer", "suffix": " 個"})
    val_indep = format_metric(get_value_by_path(results, "spx_total_return_30y.n_independent_windows"), {"kind": "number", "digits": 2, "suffix": " 個"})

    # 左側：文字說明卡片 (x: 60, y: 195, w: 760, h: 690)
    box_left = (60, 195, 820, 885)
    draw_card(draw, box_left, fill=COLOR_CARD, outline=COLOR_BORDER, radius=20)

    font_h = load_font(28, bold=True)
    draw.text((100, 235), "一句話直覺", font=font_h, fill=COLOR_TEAL)
    draw.line((100, 285, 780, 285), fill=COLOR_TEAL_BORDER, width=2)

    body_texts = [
        "有人問：想要三十年每年賺一成五，該掌握哪些事。",
        "這種問題通常會得到一篇談心態與紀律的文章。我們決定先做一件更笨的事：去查歷史上到底有沒有人做到過。",
        "取美股大盤近百年資料，每一個交易日都當成一個三十年的起點往後算，含息計算。"
    ]

    font_body = load_font(21, bold=False)
    y_cursor = 315
    for paragraph in body_texts:
        wrapped_lines = wrap_cjk_text(draw, paragraph, font_body, max_width=680)
        for line in wrapped_lines:
            draw.text((100, y_cursor), line, font=font_body, fill=COLOR_INK)
            y_cursor += 36
        y_cursor += 20  # 段落間距

    # 右側：3 個 Metric 卡片 (x: 850, y: 195, w: 690, h: 690)
    cards_data = [
        ("目標對應的本金倍數", val_mult, COLOR_TEAL, COLOR_TEAL_BG, COLOR_TEAL_BORDER),
        ("可用的三十年區間", val_nwin, COLOR_BLUE, COLOR_BLUE_BG, COLOR_BLUE_BORDER),
        ("其中互不重疊的獨立區間", val_indep, COLOR_MUTED, COLOR_BG, COLOR_BORDER),
    ]

    card_y = 195
    card_h = 210
    card_gap = 30
    for label, val_str, color_accent, bg_color, border_color in cards_data:
        box_metric = (850, card_y, 1540, card_y + card_h)
        draw_card(draw, box_metric, fill=bg_color, outline=border_color, radius=20)

        font_label = load_font(22, bold=True)
        draw.text((890, card_y + 35), label, font=font_label, fill=color_accent)

        font_val = load_font(54, bold=True)
        draw.text((890, card_y + 90), val_str, font=font_val, fill=COLOR_INK)

        card_y += card_h + card_gap

    draw_footer(draw, source_label)

    out_path = os.path.join(OUT_DIR, "1_concept.png")
    img.save(out_path, "PNG", optimize=True)
    return out_path


# ─── Panel 2 Render ───────────────────────────────────────────────────────────
def render_panel2(plan_panel: Dict[str, Any], results: Dict[str, Any], source_label: str) -> str:
    """Panel 2 - 2_results.png (Style: bento-grid)."""
    img = Image.new("RGB", (WIDTH, HEIGHT), COLOR_BG)
    draw = ImageDraw.Draw(img)

    title = plan_panel.get("title", "達標的區間有幾個：零個")
    alt = plan_panel.get("alt", "列出含息三十年滾動報酬的中位數、最佳、最差與達標數")
    draw_header(draw, title, alt, tag_bg=COLOR_RED)

    # 提取 JSON 數據
    val_median = format_metric(get_value_by_path(results, "spx_total_return_30y.cagr_median"), {"kind": "percent", "digits": 2})
    val_max = format_metric(get_value_by_path(results, "spx_total_return_30y.cagr_max"), {"kind": "percent", "digits": 2})
    val_min = format_metric(get_value_by_path(results, "spx_total_return_30y.cagr_min"), {"kind": "percent", "digits": 2})
    val_nge = format_metric(get_value_by_path(results, "spx_total_return_30y.n_ge_target"), {"kind": "integer", "suffix": " 個"})

    # Bento Grid 上排 4 個獨立 Card (y: 195, h: 250, width ~ 345 each)
    bento_metrics = [
        ("中位數年化", val_median, "美股滾動 30 年常態", COLOR_BLUE, COLOR_BLUE_BG, COLOR_BLUE_BORDER),
        ("史上最佳的三十年", val_max, "起點大蕭條谷底(1932)", COLOR_GREEN, COLOR_GREEN_BG, COLOR_GREEN_BORDER),
        ("史上最差的三十年", val_min, "起點大恐慌頂點(1929)", COLOR_AMBER, COLOR_AMBER_BG, COLOR_AMBER_BORDER),
        ("達標區間數", val_nge, "無一區間達到 15%", COLOR_RED, COLOR_RED_BG, COLOR_RED_BORDER),
    ]

    col_w = 347
    gap_x = 30
    start_x = 60
    for idx, (label, val_str, subtext, color_accent, bg_color, border_color) in enumerate(bento_metrics):
        cx = start_x + idx * (col_w + gap_x)
        box = (cx, 195, cx + col_w, 445)
        draw_card(draw, box, fill=bg_color, outline=border_color, radius=20)

        font_lbl = load_font(20, bold=True)
        draw.text((cx + 25, 225), label, font=font_lbl, fill=color_accent)

        font_val = load_font(48, bold=True)
        val_color = COLOR_RED if idx == 3 else COLOR_INK
        draw.text((cx + 25, 275), val_str, font=font_val, fill=val_color)

        font_sub = load_font(16, bold=False)
        draw.text((cx + 25, 385), subtext, font=font_sub, fill=COLOR_MUTED)

    # Bento Grid 下排大 Block (x: 60, y: 475, w: 1480, h: 410)
    box_bottom = (60, 475, 1540, 885)
    draw_card(draw, box_bottom, fill=COLOR_CARD, outline=COLOR_BORDER, radius=20)

    font_h = load_font(26, bold=True)
    draw.text((100, 515), "怎麼讀這幾個數字", font=font_h, fill=COLOR_INK)
    draw.line((100, 560, 1500, 560), fill=COLOR_BORDER, width=2)

    texts = [
        "史上最好的那個三十年，起點正好買在大蕭條的谷底，抱滿三十年，離目標還差不到三分之一個百分點。",
        "最差的那個起點跟它相隔不到三年。同一個市場，起點差三年，三十年後的年化差了將近一倍。"
    ]

    font_body = load_font(22, bold=False)
    y_cursor = 590
    for paragraph in texts:
        # 繪製 Icon / Bullet Accent
        draw.rounded_rectangle((100, y_cursor + 6, 112, y_cursor + 18), radius=3, fill=COLOR_RED)
        wrapped_lines = wrap_cjk_text(draw, paragraph, font_body, max_width=1340)
        for line_idx, line in enumerate(wrapped_lines):
            x_pos = 130 if line_idx == 0 else 130
            draw.text((x_pos, y_cursor), line, font=font_body, fill=COLOR_INK)
            y_cursor += 38
        y_cursor += 30

    draw_footer(draw, source_label)

    out_path = os.path.join(OUT_DIR, "2_results.png")
    img.save(out_path, "PNG", optimize=True)
    return out_path


# ─── Panel 3 Render ───────────────────────────────────────────────────────────
def render_panel3(plan_panel: Dict[str, Any], results: Dict[str, Any], source_label: str) -> str:
    """Panel 3 - 3_takeaway.png (Style: scientific)."""
    img = Image.new("RGB", (WIDTH, HEIGHT), COLOR_BG)
    draw = ImageDraw.Draw(img)

    title = plan_panel.get("title", "借錢確實能達標，代價寫在回撤那一欄")
    alt = plan_panel.get("alt", "對照兩倍槓桿的達標比例與回撤，以及最佳十分位區間的回撤下限")
    draw_header(draw, title, alt, tag_bg=COLOR_AMBER)

    # 提取 JSON 數據 (leverage_30y[4] 對應 2x 實際短率+1pp)
    val_lev_share = format_metric(get_value_by_path(results, "leverage_30y.4.share_ge_target"), {"kind": "percent", "digits": 2})
    val_lev_mdd = format_metric(get_value_by_path(results, "leverage_30y.4.mdd_median"), {"kind": "percent", "digits": 2})
    val_best_share = format_metric(get_value_by_path(results, "best_decile_windows.share_with_mdd_worse_than_30pct"), {"kind": "percent", "digits": 0})
    val_best_mdd = format_metric(get_value_by_path(results, "best_decile_windows.mdd_shallowest"), {"kind": "percent", "digits": 2})

    # 上排 4 個 Metric Card (y: 195, h: 230)
    top_metrics = [
        ("借到兩倍：達標比例", val_lev_share, COLOR_BLUE, COLOR_BLUE_BG, COLOR_BLUE_BORDER),
        ("借到兩倍：最大回撤中位數", val_lev_mdd, COLOR_RED, COLOR_RED_BG, COLOR_RED_BORDER),
        ("報酬最高十分位：跌過三成比例", val_best_share, COLOR_AMBER, COLOR_AMBER_BG, COLOR_AMBER_BORDER),
        ("報酬最高十分位：最淺回撤", val_best_mdd, COLOR_MUTED, COLOR_CARD, COLOR_BORDER),
    ]

    col_w = 347
    gap_x = 30
    start_x = 60
    for idx, (label, val_str, color_accent, bg_color, border_color) in enumerate(top_metrics):
        cx = start_x + idx * (col_w + gap_x)
        box = (cx, 195, cx + col_w, 425)
        draw_card(draw, box, fill=bg_color, outline=border_color, radius=20)

        font_lbl = load_font(19, bold=True)
        draw.text((cx + 25, 225), label, font=font_lbl, fill=color_accent)

        font_val = load_font(46, bold=True)
        val_color = COLOR_RED if "-" in val_str else COLOR_INK
        draw.text((cx + 25, 290), val_str, font=font_val, fill=val_color)

    # 下排 研討會/Scientific 風格: 該問的三個問題 Block (x: 60, y: 455, w: 1480, h: 430)
    box_bottom = (60, 455, 1540, 885)
    draw_card(draw, box_bottom, fill=COLOR_CARD, outline=COLOR_BORDER, radius=20)

    font_h = load_font(26, bold=True)
    draw.text((100, 490), "該問的三個問題", font=font_h, fill=COLOR_INK)
    draw.line((100, 535, 1500, 535), fill=COLOR_BORDER, width=2)

    questions = [
        ("問 1", "我的目標在歷史上出現過嗎？超出歷史上界的話，後面所有方法討論都是在討論怎麼做到一件沒發生過的事。"),
        ("問 2", "達標的那條路，回撤長什麼樣？報酬和回撤是同一個決定的兩面，只看一面就是沒看。"),
        ("問 3", "我撐得住入場費嗎？就算完全不借錢，歷史上最好的那批三十年，每一個都跌過三成。")
    ]

    y_cursor = 560
    font_badge = load_font(16, bold=True)
    font_text = load_font(20, bold=False)
    badge_colors = [COLOR_TEAL, COLOR_BLUE, COLOR_AMBER]

    for idx, (badge_str, q_text) in enumerate(questions):
        # 畫 Badge
        draw.rounded_rectangle((100, y_cursor + 2, 165, y_cursor + 32), radius=6, fill=badge_colors[idx])
        draw.text((112, y_cursor + 6), badge_str, font=font_badge, fill="#FFFFFF")

        # 畫問題內文折行
        wrapped = wrap_cjk_text(draw, q_text, font_text, max_width=1280)
        for line_idx, line in enumerate(wrapped):
            draw.text((185, y_cursor + (line_idx * 30)), line, font=font_text, fill=COLOR_INK)

        y_cursor += (len(wrapped) * 30) + 25

    draw_footer(draw, source_label)

    out_path = os.path.join(OUT_DIR, "3_takeaway.png")
    img.save(out_path, "PNG", optimize=True)
    return out_path


# ─── Main 入口點 ───────────────────────────────────────────────────────────────
def main() -> None:
    # 建立輸出目錄
    os.makedirs(OUT_DIR, exist_ok=True)

    # 讀取 evidence & plan
    plan_data = load_json(PLAN_PATH)
    results_data = load_json(RESULTS_PATH)

    # 驗證來源名稱
    source_label = plan_data.get("evidence", {}).get("results", {}).get("label", "K1700 三十年滾動報酬與槓桿達標率檢定結果")

    panels_list = plan_data.get("panels", [])
    if len(panels_list) < 3:
        raise ValueError(f"Expected at least 3 panels in plan.json, got {len(panels_list)}")

    # 執行繪製
    p1 = render_panel1(panels_list[0], results_data, source_label)
    p2 = render_panel2(panels_list[1], results_data, source_label)
    p3 = render_panel3(panels_list[2], results_data, source_label)

    print(f"Successfully generated 3 panels in {OUT_DIR}:")
    print(f"  - Panel 1: {p1}")
    print(f"  - Panel 2: {p2}")
    print(f"  - Panel 3: {p3}")


if __name__ == "__main__":
    main()
