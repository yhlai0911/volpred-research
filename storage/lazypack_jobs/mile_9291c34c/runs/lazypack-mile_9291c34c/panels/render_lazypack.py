#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VolPred 懶人包圖組渲染程式 (render_lazypack.py)
它會讀取 experiments 的 results.json 以及 K942_lazypack_evidence.json，
並利用 matplotlib 輸出三張 1600x1000 px 150 dpi 的 PNG 圖卡。
"""

import os
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.path import Path

# ==================== 1. 設定與路徑 ====================
EVIDENCE_PATH = "/Users/yhlai0911/volpred-research/storage/drafts/K942_lazypack_evidence.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k942/k942_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_9291c34c/runs/lazypack-mile_9291c34c/panels"

os.makedirs(OUT_DIR, exist_ok=True)

# 載入字型與設定
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# ==================== 2. 讀取數據與輔助函式 ====================
if not os.path.exists(EVIDENCE_PATH):
    raise FileNotFoundError(f"Missing evidence path: {EVIDENCE_PATH}")
if not os.path.exists(RESULTS_PATH):
    raise FileNotFoundError(f"Missing results path: {RESULTS_PATH}")

with open(EVIDENCE_PATH, 'r', encoding='utf-8') as f:
    evidence = json.load(f)
with open(RESULTS_PATH, 'r', encoding='utf-8') as f:
    results = json.load(f)

def get_path(d, path_str):
    """自 nested dict 中以 'a.b.c' 格式讀取數值。若缺失則 raise KeyError"""
    parts = path_str.split('.')
    curr = d
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            raise KeyError(f"Path '{path_str}' not found in data structure at part '{p}'")
    return curr

def format_value(value, fmt_spec):
    """依格式規格將數值格式化"""
    kind = fmt_spec.get("kind")
    if kind == "integer":
        return f"{int(value)}"
    elif kind == "percent":
        digits = fmt_spec.get("digits", 1)
        show_plus = fmt_spec.get("show_plus", False)
        sign = "+" if show_plus and value > 0 else ""
        return f"{sign}{value:.{digits}f}%"
    elif kind == "number":
        digits = fmt_spec.get("digits", 1)
        show_plus = fmt_spec.get("show_plus", False)
        sign = "+" if show_plus and value > 0 else ""
        return f"{sign}{value:.{digits}f}"
    elif kind == "text":
        return str(value)
    return str(value)

# ==================== 3. 繪圖輔助函式 ====================
def draw_rounded_rect(ax, x, y, w, h, rx, ry, fc='white', ec='#E2E7EF', lw=1.5, zorder=1):
    """手動繪製不受寬高比拉伸影響的圓角矩形"""
    verts = [
        (x + rx, y),
        (x + w - rx, y),
        (x + w, y),  # control
        (x + w, y + ry),
        (x + w, y + h - ry),
        (x + w, y + h),  # control
        (x + w - rx, y + h),
        (x + rx, y + h),
        (x, y + h),  # control
        (x, y + h - ry),
        (x, y + ry),
        (x, y),  # control
        (x + rx, y)
    ]
    codes = [
        Path.MOVETO,
        Path.LINETO,
        Path.CURVE3,
        Path.CURVE3,
        Path.LINETO,
        Path.CURVE3,
        Path.CURVE3,
        Path.LINETO,
        Path.CURVE3,
        Path.CURVE3,
        Path.LINETO,
        Path.CURVE3,
        Path.CURVE3
    ]
    path = Path(verts, codes)
    patch = patches.PathPatch(path, facecolor=fc, edgecolor=ec, linewidth=lw, transform=ax.transAxes, zorder=zorder, clip_on=False)
    ax.add_patch(patch)

def draw_title_bar(ax, x, y, w, h, rx, ry, fc):
    """繪製只有上方為圓角、下方為直角的標題列背景，貼合卡片上方圓角"""
    verts = [
        (x, y),
        (x + w, y),
        (x + w, y + h - ry),
        (x + w - rx, y + h),
        (x + rx, y + h),
        (x, y + h - ry),
        (x, y)
    ]
    codes = [
        Path.MOVETO,
        Path.LINETO,
        Path.LINETO,
        Path.CURVE3,
        Path.CURVE3,
        Path.LINETO,
        Path.LINETO
    ]
    path = Path(verts, codes)
    patch = patches.PathPatch(path, facecolor=fc, edgecolor='none', transform=ax.transAxes, zorder=2, clip_on=False)
    ax.add_patch(patch)

def draw_card_with_title(ax, x, y, w, h, rx, ry, title_text, title_bg_color, title_height=0.08, font_size=12):
    """繪製有深色標題列的卡片"""
    draw_rounded_rect(ax, x, y, w, h, rx, ry, fc='white', ec='#E2E7EF', lw=1.5, zorder=1)
    draw_title_bar(ax, x, y + h - title_height, w, title_height, rx, ry, fc=title_bg_color)
    ax.text(x + 0.02, y + h - title_height / 2, title_text, color='white', 
            fontsize=font_size, fontweight='bold', ha='left', va='center', 
            transform=ax.transAxes, zorder=3)

def draw_header(ax, title, subtitle, accent_color):
    """繪製頂部統一風格的標題與裝飾"""
    rect = patches.Rectangle((0.05, 0.92), 0.08, 0.02, facecolor=accent_color, edgecolor='none', transform=ax.transAxes)
    ax.add_patch(rect)
    ax.text(0.05, 0.88, "VolPred 懶人包", color=accent_color, fontsize=12, fontweight='bold', transform=ax.transAxes)
    ax.text(0.05, 0.80, title, color='#17202A', fontsize=22, fontweight='bold', transform=ax.transAxes)
    ax.text(0.05, 0.74, subtitle, color='#5A6472', fontsize=12, transform=ax.transAxes)

def draw_footer(ax, source_text):
    """繪製底部統一的資料來源聲明"""
    line = patches.ConnectionPatch((0.05, 0.12), (0.95, 0.12), coordsA="axes fraction", coordsB="axes fraction", color='#E1E6EE', linewidth=1)
    ax.add_artist(line)
    ax.text(0.05, 0.07, f"資料來源：{source_text}", color='#8792A0', fontsize=9, transform=ax.transAxes)

def draw_text_paragraph(ax, x, y, max_w_chars, text, color, fontsize, line_height=0.03):
    """中文自動折行繪製文字，避免重疊與溢出。回傳結束時的 y 座標"""
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph.strip():
            lines.append("")
            continue
        i = 0
        while i < len(paragraph):
            lines.append(paragraph[i:i+max_w_chars])
            i += max_w_chars
            
    current_y = y
    for line in lines:
        if line == "":
            current_y -= line_height * 0.5
        else:
            ax.text(x, current_y, line, color=color, fontsize=fontsize, ha='left', va='top', transform=ax.transAxes, zorder=4)
            current_y -= line_height
    return current_y

def draw_metric_card(ax, x, y, w, h, rx, ry, label, value, note, bg_color, text_color, note_color='#5A6472'):
    """繪製 Bento Grid 中的 Metric 重點數字格"""
    draw_rounded_rect(ax, x, y, w, h, rx, ry, fc=bg_color, ec='#E2E7EF', lw=1.2)
    ax.text(x + 0.018, y + h - 0.03, label, color='#17202A', fontsize=10, fontweight='bold', ha='left', va='center', transform=ax.transAxes)
    ax.text(x + 0.018, y + h - 0.075, value, color=text_color, fontsize=20, fontweight='bold', ha='left', va='center', transform=ax.transAxes)
    
    # 說明文字折行 (每行大約 14 字)
    lines = []
    i = 0
    while i < len(note):
        lines.append(note[i:i+14])
        i += 14
        
    note_y = y + 0.015
    # 從下往上排，若是多行就不會蓋到上面的 value
    for line in reversed(lines):
        ax.text(x + 0.018, note_y, line, color=note_color, fontsize=8, ha='left', va='bottom', transform=ax.transAxes)
        note_y += 0.02

# ==================== 4. 渲染 Panels ====================

# 圓角半徑像素對應比例
rx = 15 / 1600
ry = 15 / 1000

# ---------------- Panel 1 — 1_concept.png ----------------
fig, ax = plt.subplots(figsize=(1600/150, 1000/150), dpi=150)
fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
ax.set_facecolor('#F7F4EF')
fig.patch.set_facecolor('#F7F4EF')
ax.axis('off')

draw_header(ax, "它的價值不固定，看兩件事", "市場當下在哪個溫度、你想預測多久以後", "#235A97")
draw_footer(ax, "vix: SPY 恐慌指數效用拆解（轉錄自來源文章）")

# 讀取 bindings
calm_val = format_value(get_path(evidence, "thresholds.calm_level"), {"kind": "integer"})
panic_val = format_value(get_path(evidence, "thresholds.panic_level"), {"kind": "integer"})

# 左欄: 改善幅度是什麼意思
draw_card_with_title(ax, 0.05, 0.18, 0.43, 0.50, rx, ry, "改善幅度是什麼意思", "#235A97", title_height=0.08, font_size=12)
text_concept_left = (
    "同一套推估未來震盪幅度的做法，一版不看恐慌指數、一版看。\n\n"
    "比兩版誰更接近後來真實發生的震盪，差距換算成百分比。\n\n"
    "正數代表看了有幫助；負數代表加進去以後反而更糟。"
)
draw_text_paragraph(ax, 0.07, 0.55, 22, text_concept_left, '#17202A', 10, line_height=0.035)

# 右上欄: 兩個切法
draw_card_with_title(ax, 0.52, 0.42, 0.43, 0.26, rx, ry, "兩個切法", "#177C7D", title_height=0.08, font_size=12)
text_concept_right_top = (
    f"市場狀態：極端平靜（低於 {calm_val}）／一般水準／極端恐慌（高於 {panic_val}）\n\n"
    "預測窗口：一日／一週／一個月"
)
draw_text_paragraph(ax, 0.54, 0.55, 22, text_concept_right_top, '#17202A', 10, line_height=0.035)

# 右下欄: 樣本
draw_card_with_title(ax, 0.52, 0.18, 0.43, 0.20, rx, ry, "樣本", "#5A6472", title_height=0.08, font_size=12)
text_concept_right_bottom = "美股大盤指數基金 SPY，期間 二〇一六 到 二〇二五，資料來源 yfinance。"
draw_text_paragraph(ax, 0.54, 0.25, 22, text_concept_right_bottom, '#17202A', 10, line_height=0.035)

plt.savefig(os.path.join(OUT_DIR, "1_concept.png"), dpi=150)
plt.close()


# ---------------- Panel 2 — 2_results.png ----------------
fig, ax = plt.subplots(figsize=(1600/150, 1000/150), dpi=150)
fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
ax.set_facecolor('#F7F4EF')
fig.patch.set_facecolor('#F7F4EF')
ax.axis('off')

draw_header(ax, "好消息在兩端，壞消息在中間和遠處", "市場狀態與預測窗口的改善幅度數字", "#C83E3A")
draw_footer(ax, "vix: SPY 恐慌指數效用拆解（轉錄自來源文章）")

# 讀取 bindings
calm_below_15 = format_value(get_path(evidence, "regime_improvement_pct.calm_below_15"), {"kind": "percent", "digits": 1, "show_plus": True})
normal_15_to_25 = format_value(get_path(evidence, "regime_improvement_pct.normal_15_to_25"), {"kind": "percent", "digits": 1, "show_plus": True})
panic_above_25 = format_value(get_path(evidence, "regime_improvement_pct.panic_above_25"), {"kind": "percent", "digits": 1, "show_plus": True})

one_day = format_value(get_path(evidence, "horizon_improvement_pct.one_day"), {"kind": "percent", "digits": 1, "show_plus": True})
one_week = format_value(get_path(evidence, "horizon_improvement_pct.one_week"), {"kind": "percent", "digits": 1, "show_plus": True})
one_month = format_value(get_path(evidence, "horizon_improvement_pct.one_month"), {"kind": "percent", "digits": 1, "show_plus": True})

ratio = format_value(get_path(evidence, "derived_arithmetic.panic_over_normal_ratio"), {"kind": "number", "digits": 1})
gap = format_value(get_path(evidence, "derived_arithmetic.week_minus_month_pp"), {"kind": "number", "digits": 1})

# Left column metrics (regime)
draw_metric_card(ax, 0.05, 0.527, 0.28, 0.153, rx, ry, "極端平靜 (指數低於十五)", calm_below_15, "市場出奇安靜時，訊號偏強", "#F0F7F7", "#177C7D")
draw_metric_card(ax, 0.05, 0.354, 0.28, 0.153, rx, ry, "一般水準 (指數十五到二十五)", normal_15_to_25, "等同沒用；而市場大部分時間就待在這裡", "#F4F6F9", "#5A6472")
draw_metric_card(ax, 0.05, 0.180, 0.28, 0.153, rx, ry, "極端恐慌 (指數高於二十五)", panic_above_25, "全表最高", "#FDF3F2", "#C83E3A")

# Middle column metrics (horizon)
draw_metric_card(ax, 0.36, 0.527, 0.28, 0.153, rx, ry, "預測窗口：一日", one_day, "太短，資訊被當天雜訊蓋掉", "#F4F6F9", "#235A97")
draw_metric_card(ax, 0.36, 0.354, 0.28, 0.153, rx, ry, "預測窗口：一週", one_week, "甜蜜點", "#F0F7F7", "#177C7D")
draw_metric_card(ax, 0.36, 0.180, 0.28, 0.153, rx, ry, "預測窗口：一個月", one_month, "負的：加進去以後預測比不加還差，是倒扣", "#FDF7F0", "#A96A12")

# Right column: Arithmetic comparisons
draw_card_with_title(ax, 0.67, 0.180, 0.28, 0.50, rx, ry, "兩個純算術對照", "#235A97", title_height=0.08, font_size=12)
text_results_arith = (
    f"• 極端恐慌那格是一般水準那格的 {ratio} 倍。\n\n"
    f"• 一週與一個月之間，相差 {gap} 個百分點。"
)
draw_text_paragraph(ax, 0.688, 0.55, 14, text_results_arith, '#17202A', 10, line_height=0.035)

plt.savefig(os.path.join(OUT_DIR, "2_results.png"), dpi=150)
plt.close()


# ---------------- Panel 3 — 3_takeaway.png ----------------
fig, ax = plt.subplots(figsize=(1600/150, 1000/150), dpi=150)
fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
ax.set_facecolor('#F7F4EF')
fig.patch.set_facecolor('#F7F4EF')
ax.axis('off')

draw_header(ax, "怎麼改看盤習慣，以及不能過度解讀什麼", "行動建議與三條限制", "#177C7D")
draw_footer(ax, "vix: SPY 恐慌指數效用拆解（轉錄自來源文章）")

# 讀取 bindings
d1_val = format_value(get_path(evidence, "horizon_improvement_pct.one_day"), {"kind": "percent", "digits": 1, "show_plus": True})
w1_val = format_value(get_path(evidence, "horizon_improvement_pct.one_week"), {"kind": "percent", "digits": 1, "show_plus": True})
m1_val = format_value(get_path(evidence, "horizon_improvement_pct.one_month"), {"kind": "percent", "digits": 1, "show_plus": True})
calm_val = format_value(get_path(evidence, "thresholds.calm_level"), {"kind": "integer"})
panic_val = format_value(get_path(evidence, "thresholds.panic_level"), {"kind": "integer"})

sample_val = format_value(get_path(evidence, "caveats.sample"), {"kind": "text"})
sig_val = format_value(get_path(evidence, "caveats.significance"), {"kind": "text"})
hit_val = format_value(get_path(evidence, "direction_predictability.best_hit_rate_pct"), {"kind": "percent", "digits": 1})
up_val = format_value(get_path(evidence, "direction_predictability.market_up_time_pct"), {"kind": "percent", "digits": 0})
short_val = format_value(get_path(evidence, "direction_predictability.shortfall_pp"), {"kind": "number", "digits": 1})

# Left Column: Actions
draw_card_with_title(ax, 0.05, 0.32, 0.43, 0.38, rx, ry, "行動三條", "#235A97", title_height=0.07, font_size=12)
text_actions = (
    f"• 頻率降到一週一次。每天調倉是拿只值 {d1_val} 的訊號去做每次要付手續費的決定；"
    f"改成每週看一次，同一個指標值 {w1_val}。\n\n"
    f"• 只在跌破 {calm_val} 或站上 {panic_val} 時認真對待；落在中間區間時它給的資訊接近零。\n\n"
    f"• 一個月才調一次配置的長期投資人可以直接不看，那個窗口是 {m1_val}。"
)
draw_text_paragraph(ax, 0.07, 0.60, 22, text_actions, '#17202A', 9, line_height=0.026)

# Right Column: Caveats
draw_card_with_title(ax, 0.52, 0.32, 0.43, 0.38, rx, ry, "三條限制（同等重要）", "#C83E3A", title_height=0.07, font_size=12)
text_caveats = (
    f"一、{sample_val}\n\n"
    f"二、{sig_val}\n\n"
    f"三、方向不可預測：另一份週頻報酬分析中，方向猜對率最高只到 {hit_val}，"
    f"而同期市場有 {up_val} 的時間往上走，比「每次都猜漲」還差 {short_val} 個百分點。"
)
draw_text_paragraph(ax, 0.54, 0.60, 22, text_caveats, '#17202A', 9, line_height=0.026)

# Bottom: Headline Banner
draw_rounded_rect(ax, 0.05, 0.18, 0.90, 0.10, rx, ry, fc='#EBF6F6', ec='#177C7D', lw=1.2)
ax.text(0.50, 0.23, "一句話帶走：它回答的是「這週該承擔多少風險」，回答不了「該壓多還是壓空」。", 
        color='#177C7D', fontsize=12, fontweight='bold', ha='center', va='center', transform=ax.transAxes)

plt.savefig(os.path.join(OUT_DIR, "3_takeaway.png"), dpi=150)
plt.close()

print("All panels rendered successfully!")
