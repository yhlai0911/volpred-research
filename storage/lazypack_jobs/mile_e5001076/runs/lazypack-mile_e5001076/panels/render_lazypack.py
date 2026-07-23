#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render script for K1608 懶人包 panels.
Generates panel_question.png, panel_results.png, and panel_boundary.png.
"""
import os
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Set up matplotlib configuration for Traditional Chinese and standard settings
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# Absolute Paths
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1608/k1608_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_e5001076/runs/lazypack-mile_e5001076/panels"

def get_path_value(data, path):
    """Retrieve values from nested dict using dot notation. Raise error if missing."""
    parts = path.split('.')
    curr = data
    for part in parts:
        if isinstance(curr, dict):
            if part in curr:
                curr = curr[part]
            else:
                raise KeyError(f"Key '{part}' not found in path '{path}'")
        else:
            raise TypeError(f"Cannot traverse path '{path}' at '{part}'")
    return curr

def format_val(val, format_spec):
    """Format the value dynamically based on format rules."""
    kind = format_spec.get("kind", "number")
    digits = format_spec.get("digits", 2)
    show_plus = format_spec.get("show_plus", False)
    absolute = format_spec.get("absolute", False)
    suffix = format_spec.get("suffix", "")
    
    if absolute:
        val = abs(val)
        
    if kind == "percent":
        val_num = float(val) * 100.0
        fmt_str = f"{{:{'+' if show_plus else ''}.{digits}f}}%"
        return fmt_str.format(val_num) + suffix
    elif kind == "integer":
        val_num = int(val)
        return f"{val_num}{suffix}"
    elif kind == "date":
        return str(val)
    elif kind == "number":
        val_num = float(val)
        fmt_str = f"{{:{'+' if show_plus else ''}.{digits}f}}"
        return fmt_str.format(val_num) + suffix
    else:
        return str(val)

def wrap_zh_text(text, max_len):
    """Simple wrapper for Chinese/English mixed text to fit within a line width limit."""
    lines = []
    current_line = []
    current_len = 0
    for char in text:
        if char == '\n':
            lines.append("".join(current_line))
            current_line = []
            current_len = 0
            continue
        current_line.append(char)
        # Approximate width: Chinese char is 2, ASCII is 1
        char_len = 2 if ord(char) > 127 else 1
        current_len += char_len
        if current_len >= max_len:
            lines.append("".join(current_line))
            current_line = []
            current_len = 0
    if current_line:
        lines.append("".join(current_line))
    return lines

def draw_wrapped_text(ax, text, x, y, fontsize, color='#0F172A', weight='normal', ha='left', wrap_width=40, line_spacing=1.4):
    """Draw multiline text line by line and return the next free y coordinate."""
    lines = wrap_zh_text(text, wrap_width)
    curr_y = y
    dy = (fontsize * 2.0833 * line_spacing) / 1000.0
    for line in lines:
        ax.text(
            x, curr_y, line,
            fontsize=fontsize, color=color, weight=weight,
            ha=ha, va='top', zorder=2
        )
        curr_y -= dy
    return curr_y

def draw_card(ax, x, y, width, height, facecolor='#FFFFFF', edgecolor='#E2E8F0', linewidth=1.5):
    """Draw a clean rectangular card with flat edges for modern, premium presentation."""
    rect = patches.Rectangle(
        (x, y), width, height,
        facecolor=facecolor, edgecolor=edgecolor,
        linewidth=linewidth, zorder=1
    )
    ax.add_patch(rect)

def draw_metric_card(ax, label, value, note, x, y, w, h, border_color='#E2E8F0', text_color='#0F172A', label_color='#0284C7', note_color='#64748B'):
    """Draw a card containing a single big metric value, label, and explanation note."""
    draw_card(ax, x, y, w, h, facecolor='#FFFFFF', edgecolor=border_color, linewidth=1.5)
    
    # Internal paddings
    p_x = x + 0.015
    p_y = y + h - 0.03
    
    # 1. Label
    ax.text(p_x, p_y, label, fontsize=10, color=label_color, weight='bold', ha='left', va='top', zorder=2)
    
    # 2. Value
    p_y -= 0.035
    ax.text(p_x, p_y, value, fontsize=22, color=text_color, weight='bold', ha='left', va='top', zorder=2)
    
    # 3. Note
    if note:
        p_y -= 0.06
        wrap_w = int(w * 110)
        draw_wrapped_text(ax, note, p_x, p_y, fontsize=9, color=note_color, weight='normal', ha='left', wrap_width=wrap_w, line_spacing=1.35)

def draw_text_card(ax, heading, body_list, x, y, w, h, facecolor='#F8FAFC', border_color='#E2E8F0', heading_color='#0284C7'):
    """Draw a card with multiple text paragraphs and a bold heading."""
    draw_card(ax, x, y, w, h, facecolor=facecolor, edgecolor=border_color, linewidth=1.5)
    
    p_x = x + 0.02
    p_y = y + h - 0.035
    
    # Draw Heading
    ax.text(p_x, p_y, heading, fontsize=13, color=heading_color, weight='bold', ha='left', va='top', zorder=2)
    
    p_y -= 0.05
    wrap_w = int(w * 90)
    for item in body_list:
        p_y = draw_wrapped_text(ax, item, p_x, p_y, fontsize=10.5, color='#334155', weight='normal', ha='left', wrap_width=wrap_w, line_spacing=1.4)
        p_y -= 0.025

def draw_header(ax, title, subtitle, accent_color='#0284C7'):
    """Draw panel header block with colored top line, large title, and subtitle."""
    rect = patches.Rectangle((0.05, 0.96), 0.90, 0.006, facecolor=accent_color, edgecolor='none', zorder=1)
    ax.add_patch(rect)
    
    # Title
    ax.text(0.05, 0.91, title, fontsize=20, color='#0F172A', weight='bold', ha='left', va='top', zorder=2)
    
    # Subtitle
    draw_wrapped_text(ax, subtitle, 0.05, 0.86, fontsize=11.5, color='#64748B', weight='normal', ha='left', wrap_width=95, line_spacing=1.35)

def draw_footer(ax):
    """Draw standard footer with source citation."""
    rect = patches.Rectangle((0.05, 0.10), 0.90, 0.001, facecolor='#E2E8F0', edgecolor='none', zorder=1)
    ax.add_patch(rect)
    
    source_text = "來源：K1608 票房注意力衝擊事件檢定結果（維基百科票房冠軍表 + yfinance，2005-2026）"
    ax.text(0.05, 0.07, source_text, fontsize=9, color='#94A3B8', ha='left', va='top', zorder=2)

def render_panel_1(results_data):
    """Panel 1: Concept Framing (panel_question.png)"""
    fig = plt.figure(figsize=(10.67, 6.67), dpi=150, facecolor='#FFFFFF')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    draw_header(ax, "想問的是：大片的熱度會流進下一週的市場嗎", 
                "研究概念：把週末票房異常高的週末標記成注意力衝擊，觀察後續一週的市場表現",
                accent_color='#0284C7')
    
    shocks_val = get_path_value(results_data, "sample.n_blockbuster_shocks")
    shocks_str = format_val(shocks_val, {"kind": "integer", "suffix": " 次"})
    
    body_paragraphs = [
        "文獻有個猜想：大家看完大片心情變好、注意力被娛樂拉走，下一週的股市可能因此變得不一樣。",
        "我只用免費的公開資料試著把這條線索抓出來：維基百科的每週票房冠軍，加上日線收盤價。",
        f"把票房異常高的週末標成一次「注意力衝擊」，全期間共出現 {shocks_str}，只佔全部週末的一小部分。"
    ]
    draw_text_card(ax, "這篇在測什麼", body_paragraphs, 
                   x=0.05, y=0.15, w=0.40, h=0.65, 
                   facecolor='#F8FAFC', border_color='#E2E8F0', heading_color='#0284C7')
    
    val_1 = format_val(get_path_value(results_data, "sample.n_weekends"), {"kind": "integer", "suffix": " 個"})
    draw_metric_card(ax, "涵蓋週末數", val_1, "樣本涵蓋的完整週末數",
                     x=0.48, y=0.60, w=0.22, h=0.20,
                     border_color='#E2E8F0', label_color='#0284C7')
                     
    val_2 = format_val(get_path_value(results_data, "sample.n_assets"), {"kind": "integer", "suffix": " 檔"})
    draw_metric_card(ax, "被檢定的資產", val_2, "大盤與消費類 ETF，加上娛樂類個股與等權籃子",
                     x=0.73, y=0.60, w=0.22, h=0.20,
                     border_color='#E2E8F0', label_color='#0284C7')
                     
    val_3 = format_val(get_path_value(results_data, "sample.n_signal_available"), {"kind": "integer", "suffix": " 個"})
    draw_metric_card(ax, "算得出衝擊分數的週末", val_3, "要累積夠長的歷史才能判斷「異常高」",
                     x=0.48, y=0.38, w=0.47, h=0.18,
                     border_color='#E2E8F0', label_color='#0284C7')
                     
    val_4 = format_val(get_path_value(results_data, "sample.calendar_start"), {"kind": "date"})
    draw_metric_card(ax, "樣本起點", val_4, "",
                     x=0.48, y=0.16, w=0.22, h=0.18,
                     border_color='#E2E8F0', label_color='#0284C7')
                     
    val_5 = format_val(get_path_value(results_data, "sample.calendar_end"), {"kind": "date"})
    draw_metric_card(ax, "樣本終點", val_5, "",
                     x=0.73, y=0.16, w=0.22, h=0.18,
                     border_color='#E2E8F0', label_color='#0284C7')
    
    draw_footer(ax)
    plt.savefig(os.path.join(OUT_DIR, "panel_question.png"), dpi=150)
    plt.close()

def render_panel_2(results_data):
    """Panel 2: Results Bento (panel_results.png)"""
    fig = plt.figure(figsize=(10.67, 6.67), dpi=150, facecolor='#FFFFFF')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    draw_header(ax, "每一組檢定都沒過關", 
                "所有資產與結果變數的檢定統計量都遠離顯著門檻，最大的一組也只到邊緣",
                accent_color='#0D9488')
    
    val_1 = format_val(get_path_value(results_data, "asset_results.SPY.fwd5_return.ols_hac.t_hac_lag4"),
                       {"kind": "number", "digits": 2, "show_plus": True})
    draw_metric_card(ax, "SPY 次週報酬的檢定統計量", val_1, "方向甚至跟「心情變好更敢冒險」相反",
                     x=0.05, y=0.49, w=0.28, h=0.31,
                     border_color='#E2E8F0', label_color='#0D9488')
                     
    val_2 = format_val(get_path_value(results_data, "asset_results.SPY.log_fwd5_rv_ratio.ols_hac.t_hac_lag4"),
                       {"kind": "number", "digits": 2, "show_plus": True})
    draw_metric_card(ax, "SPY 次週波動比的檢定統計量", val_2, "幾乎就是釘在零上",
                     x=0.35, y=0.49, w=0.28, h=0.31,
                     border_color='#E2E8F0', label_color='#0D9488')
                     
    val_3 = format_val(get_path_value(results_data, "asset_results.AMC.log_fwd5_rv_ratio.ols_hac.t_hac_lag4"),
                       {"kind": "number", "digits": 2, "absolute": True})
    draw_metric_card(ax, "全表最大的一組（AMC 波動比）", val_3, "唯一稍微有點動靜的一格",
                     x=0.05, y=0.15, w=0.28, h=0.31,
                     border_color='#FDE68A', label_color='#D97706')
                     
    val_4 = format_val(get_path_value(results_data, "asset_results.AMC.log_fwd5_rv_ratio.ols_hac.p_hac_lag4"),
                       {"kind": "number", "digits": 3})
    draw_metric_card(ax, "它的 p 值", val_4, "仍高於常用的顯著水準，測不到關係",
                     x=0.35, y=0.15, w=0.28, h=0.31,
                     border_color='#FDE68A', label_color='#D97706')
                     
    body_paragraphs = [
        "每檔資產都測了接下來五個交易日的報酬、波動度相對前一段時間的變化，以及下跌方向的風險。",
        "沒有任何一組跨過門檻。更值得注意的是，測這麼多次照理該撞出幾個假陽性，這次連假陽性都沒撈到。"
    ]
    draw_text_card(ax, "怎麼讀這張成績單", body_paragraphs,
                   x=0.65, y=0.15, w=0.30, h=0.65,
                   facecolor='#F8FAFC', border_color='#E2E8F0', heading_color='#0D9488')
                   
    draw_footer(ax)
    plt.savefig(os.path.join(OUT_DIR, "panel_results.png"), dpi=150)
    plt.close()

def render_panel_3(results_data):
    """Panel 3: Boundary Takeaway (panel_boundary.png)"""
    fig = plt.figure(figsize=(10.67, 6.67), dpi=150, facecolor='#FFFFFF')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    draw_header(ax, "「測不到」不等於「不存在」", 
                "研究邊界：信賴區間仍容得下很大的效果，且訊號時點晚於週末，不是可交易訊號的檢定",
                accent_color='#1E3A8A')
    
    body_paragraphs = [
        "正確的說法是「這份資料沒能力偵測到」，不是「電影對市場沒有影響」。區間裡還容得下經濟上很大的效果。",
        "維基百科記的多半是週一才公布的實際票房，而觀察窗也從週一起算，所以這不是「週日晚上能不能靠票房下單」的檢定。",
        "本文是資料診斷，不是策略驗證，也不構成任何投資建議。"
    ]
    draw_text_card(ax, "三件不能省略的話", body_paragraphs, 
                   x=0.05, y=0.15, w=0.40, h=0.65, 
                   facecolor='#F8FAFC', border_color='#E2E8F0', heading_color='#1E3A8A')
    
    val_1 = format_val(get_path_value(results_data, "asset_results.SPY.fwd5_return.ols_hac.ci95_low"),
                       {"kind": "percent", "digits": 2})
    draw_metric_card(ax, "SPY 次週報酬區間下緣", val_1, "這是五個交易日的量級，換算年化並不小",
                     x=0.48, y=0.49, w=0.22, h=0.31,
                     border_color='#E2E8F0', label_color='#1E3A8A')
                     
    val_2 = format_val(get_path_value(results_data, "asset_results.SPY.fwd5_return.ols_hac.ci95_high"),
                       {"kind": "percent", "digits": 2, "show_plus": True})
    draw_metric_card(ax, "SPY 次週報酬區間上緣", val_2, "區間兩端都離零很遠，資料還分不出勝負",
                     x=0.73, y=0.49, w=0.22, h=0.31,
                     border_color='#E2E8F0', label_color='#1E3A8A')
                     
    val_3 = format_val(get_path_value(results_data, "asset_results.SPY.fwd5_return.ols_hac.se_hac_lag4"),
                       {"kind": "percent", "digits": 2})
    draw_metric_card(ax, "這組估計的誤差幅度", val_3, "誤差這麼大，小一點的效果本來就看不見",
                     x=0.48, y=0.15, w=0.22, h=0.31,
                     border_color='#E2E8F0', label_color='#1E3A8A')
                     
    val_4 = format_val(get_path_value(results_data, "asset_results.SPY.fwd5_return.ols_hac.n_shock"),
                       {"kind": "integer", "suffix": " 次"})
    draw_metric_card(ax, "手上的事件次數", val_4, "在週頻資料裡，這個量並不算多",
                     x=0.73, y=0.15, w=0.22, h=0.31,
                     border_color='#E2E8F0', label_color='#1E3A8A')
    
    draw_footer(ax)
    plt.savefig(os.path.join(OUT_DIR, "panel_boundary.png"), dpi=150)
    plt.close()

def main():
    print(f"Loading results from: {RESULTS_PATH}")
    if not os.path.exists(RESULTS_PATH):
        raise FileNotFoundError(f"Results file not found: {RESULTS_PATH}")
        
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)
        
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Saving output panels to: {OUT_DIR}")
    
    render_panel_1(results_data)
    print("Generated panel_question.png")
    
    render_panel_2(results_data)
    print("Generated panel_results.png")
    
    render_panel_3(results_data)
    print("Generated panel_boundary.png")
    
    print("All panels rendered successfully!")

if __name__ == "__main__":
    main()
