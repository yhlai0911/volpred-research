#!/usr/bin/env python3
import os
import sys
import json
import traceback
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.lines import Line2D

# Configure fonts and unicode minus
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

def escape_math(text):
    if isinstance(text, str):
        return text.replace('$', '\\$')
    return text

PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_9fbac50b/runs/lazypack-mile_9fbac50b/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1409/k1409_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_9fbac50b/runs/lazypack-mile_9fbac50b/panels"

def get_nested_val(data, path):
    parts = path.split('.')
    curr = data
    for part in parts:
        if isinstance(curr, dict):
            if part not in curr:
                raise KeyError(f"Key '{part}' not found in path '{path}'")
            curr = curr[part]
        elif isinstance(curr, list):
            try:
                curr = curr[int(part)]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Invalid index '{part}' in path '{path}'") from e
        else:
            raise KeyError(f"Cannot traverse path '{path}' at '{part}'")
    return curr

def format_value(val, fmt_config):
    kind = fmt_config.get("kind")
    if kind == "percent":
        digits = fmt_config.get("digits", 1)
        percent_val = val * 100
        return f"{percent_val:.{digits}f}%"
    elif kind == "integer":
        val_int = int(round(val))
        suffix = fmt_config.get("suffix", "")
        prefix = fmt_config.get("prefix", "")
        return f"{prefix}{val_int}{suffix}"
    elif kind == "number":
        prefix = fmt_config.get("prefix", "")
        suffix = fmt_config.get("suffix", "")
        digits = fmt_config.get("digits", 0)
        thousands = fmt_config.get("thousands", False)
        
        if thousands:
            fmt_str = f",.{digits}f"
        else:
            fmt_str = f".{digits}f"
        
        formatted_num = format(val, fmt_str)
        return f"{prefix}{formatted_num}{suffix}"
    else:
        return str(val)

def wrap_chinese_text(text, max_chars_per_line):
    lines = []
    for paragraph in text.split('\n'):
        current_line = []
        current_len = 0
        for char in paragraph:
            char_len = 2 if ord(char) > 127 else 1
            if current_len + char_len > max_chars_per_line * 2:
                lines.append("".join(current_line))
                current_line = [char]
                current_len = char_len
            else:
                current_line.append(char)
                current_len += char_len
        if current_line:
            lines.append("".join(current_line))
    return "\n".join(lines)

def draw_wrapped_text(ax, text, x, y, max_chars, fontsize, color, line_height=0.03, va='top', ha='left', weight='normal'):
    wrapped = wrap_chinese_text(text, max_chars)
    lines = wrapped.split('\n')
    current_y = y
    for line in lines:
        ax.text(x, current_y, escape_math(line), fontsize=fontsize, color=color, fontweight=weight,
                fontfamily='Heiti TC', va=va, ha=ha, transform=ax.transAxes)
        if va == 'top':
            current_y -= line_height
        else:
            current_y += line_height
    return current_y

def draw_card(ax, xmin, ymin, xmax, ymax, facecolor='#FFFFFF', edgecolor='#E2E8F0', accent_color=None):
    rect = patches.Rectangle((xmin, ymin), xmax - xmin, ymax - ymin, 
                             facecolor=facecolor, edgecolor=edgecolor, linewidth=1.5,
                             transform=ax.transAxes, zorder=1)
    ax.add_patch(rect)
    if accent_color:
        bar_width = 0.012
        accent_bar = patches.Rectangle((xmin, ymin), bar_width, ymax - ymin,
                                       facecolor=accent_color, edgecolor='none',
                                       transform=ax.transAxes, zorder=2)
        ax.add_patch(accent_bar)

def draw_common_elements(ax, title, alt_text, footer_text):
    # Title
    ax.text(0.05, 0.90, escape_math(title), fontsize=24, fontweight='bold', color='#0F172A',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Subtitle / Alt text
    ax.text(0.05, 0.83, escape_math(alt_text), fontsize=13, color='#475569',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Footer line
    line = Line2D([0.05, 0.95], [0.09, 0.09], color='#E2E8F0', linewidth=1.0, transform=ax.transAxes)
    ax.add_line(line)
    
    # Footer text
    ax.text(0.05, 0.05, escape_math(f"資料來源：{footer_text}"), fontsize=10, color='#64748B',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')

def render_panel_1(p_spec, results, footer_text):
    title = p_spec["title"]
    alt = p_spec["alt"]
    
    # Extract blocks
    text_block = [b for b in p_spec["blocks"] if b["kind"] == "text"][0]
    heading = text_block["heading"]
    body_lines = text_block["body"]
    
    m1_spec = [b for b in p_spec["blocks"] if b["kind"] == "metric" and b["label"] == "投入本金"][0]
    m1_val = get_nested_val(results, m1_spec["value"]["path"])
    m1_str = format_value(m1_val, m1_spec["value"]["format"])
    
    m2_spec = [b for b in p_spec["blocks"] if b["kind"] == "metric" and b["label"] == "可用歷史長度"][0]
    m2_val = get_nested_val(results, m2_spec["value"]["path"])
    m2_str = format_value(m2_val, m2_spec["value"]["format"])
    
    # Setup plot
    fig, ax = plt.subplots(figsize=(1600/150, 1000/150), dpi=150)
    ax.axis('off')
    fig.patch.set_facecolor('white')
    
    # Draw deep header banner for professional style
    banner = patches.Rectangle((0, 0.78), 1.0, 0.22, facecolor='#1E293B', edgecolor='none', transform=ax.transAxes)
    ax.add_patch(banner)
    
    # Draw Header Text in white
    ax.text(0.05, 0.89, escape_math(title), fontsize=24, fontweight='bold', color='#FFFFFF',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.05, 0.83, escape_math(alt), fontsize=13, color='#E2E8F0',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Draw Footer
    line = Line2D([0.05, 0.95], [0.09, 0.09], color='#E2E8F0', linewidth=1.0, transform=ax.transAxes)
    ax.add_line(line)
    ax.text(0.05, 0.05, escape_math(f"資料來源：{footer_text}"), fontsize=10, color='#64748B',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Left Column: "做法" text card
    draw_card(ax, 0.05, 0.14, 0.48, 0.74, facecolor='#F8FAFC', edgecolor='#E2E8F0', accent_color='#0F766E')
    ax.text(0.09, 0.68, escape_math(heading), fontsize=18, fontweight='bold', color='#0F172A',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Wrap and draw body lines
    y_start = 0.60
    for line in body_lines:
        bullet_line = f"• {line}"
        y_start = draw_wrapped_text(ax, bullet_line, 0.09, y_start, 18, 12, '#334155', line_height=0.038, va='top')
        y_start -= 0.02
        
    # Right Column: Metric 1 (投入本金)
    draw_card(ax, 0.52, 0.46, 0.95, 0.74, facecolor='#FFFFFF', edgecolor='#E2E8F0', accent_color='#3B82F6')
    ax.text(0.56, 0.67, escape_math(m1_spec["label"]), fontsize=14, fontweight='bold', color='#475569',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.56, 0.54, escape_math(m1_str), fontsize=32, fontweight='bold', color='#0F172A',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Right Column: Metric 2 (可用歷史長度)
    draw_card(ax, 0.52, 0.14, 0.95, 0.42, facecolor='#FFFFFF', edgecolor='#E2E8F0', accent_color='#10B981')
    ax.text(0.56, 0.35, escape_math(m2_spec["label"]), fontsize=14, fontweight='bold', color='#475569',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.56, 0.22, escape_math(m2_str), fontsize=32, fontweight='bold', color='#0F172A',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Save figure
    out_path = os.path.join(OUT_DIR, "1_method.png")
    plt.savefig(out_path, dpi=150, facecolor='white', bbox_inches=None)
    plt.close()

def render_panel_2(p_spec, results, footer_text):
    title = p_spec["title"]
    alt = p_spec["alt"]
    
    # Extract metrics
    m1_spec = [b for b in p_spec["blocks"] if b["kind"] == "metric" and b["label"] == "有配息月份單月達目標金額的機率"][0]
    m1_val = get_nested_val(results, m1_spec["value"]["path"])
    m1_str = format_value(m1_val, m1_spec["value"]["format"])
    
    m2_spec = [b for b in p_spec["blocks"] if b["kind"] == "metric" and b["label"] == "平均月配息達目標金額的機率"][0]
    m2_val = get_nested_val(results, m2_spec["value"]["path"])
    m2_str = format_value(m2_val, m2_spec["value"]["format"])
    
    m3_spec = [b for b in p_spec["blocks"] if b["kind"] == "metric" and b["label"] == "單月配息中位數"][0]
    m3_val = get_nested_val(results, m3_spec["value"]["path"])
    m3_str = format_value(m3_val, m3_spec["value"]["format"])
    
    # Setup plot
    fig, ax = plt.subplots(figsize=(1600/150, 1000/150), dpi=150)
    ax.axis('off')
    fig.patch.set_facecolor('white')
    
    # Draw common elements
    draw_common_elements(ax, title, alt, footer_text)
    
    # Bento Cell 1: Left Hero Cell
    draw_card(ax, 0.05, 0.14, 0.48, 0.74, facecolor='#F0FDF4', edgecolor='#D1FAE5', accent_color='#059669')
    ax.text(0.08, 0.68, escape_math(m1_spec["label"]), fontsize=14, fontweight='bold', color='#065F46',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.08, 0.50, escape_math(m1_str), fontsize=48, fontweight='bold', color='#047857',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Draw progress bar inside Cell 1
    pbar_bg = patches.Rectangle((0.08, 0.35), 0.36, 0.03, facecolor='#E2E8F0', edgecolor='none', transform=ax.transAxes)
    ax.add_patch(pbar_bg)
    pbar_fill = patches.Rectangle((0.08, 0.35), 0.36 * m1_val, 0.03, facecolor='#059669', edgecolor='none', transform=ax.transAxes)
    ax.add_patch(pbar_fill)
    
    # Format description dynamically
    target_val = get_nested_val(results, "config.monthly_target_ntd")
    target_str = "1 萬" if target_val == 10000 else f"{int(target_val):,} "
    m1_val_pct = format_value(m1_val, {"kind": "percent", "digits": 1})
    desc_str1 = f"模擬結果顯示，約有 {m1_val_pct} 的月份配息能大於或等於 {target_str}元目標。"
    
    draw_wrapped_text(ax, desc_str1, 0.08, 0.28, 17, 11, '#065F46', line_height=0.032, va='top')
    
    # Bento Cell 2: Right Top Cell
    draw_card(ax, 0.52, 0.46, 0.95, 0.74, facecolor='#FEF2F2', edgecolor='#FEE2E2', accent_color='#DC2626')
    ax.text(0.55, 0.67, escape_math(m2_spec["label"]), fontsize=14, fontweight='bold', color='#991B1B',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.55, 0.57, escape_math(m2_str), fontsize=32, fontweight='bold', color='#DC2626',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    draw_wrapped_text(ax, "拉長到三年平均，月均配息達標的機率極低。", 
                      0.55, 0.51, 30, 10, '#991B1B', line_height=0.03, va='top')
    
    # Bento Cell 3: Right Bottom Cell
    draw_card(ax, 0.52, 0.14, 0.95, 0.42, facecolor='#F8FAFC', edgecolor='#E2E8F0', accent_color='#3B82F6')
    ax.text(0.55, 0.36, escape_math(m3_spec["label"]), fontsize=14, fontweight='bold', color='#475569',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.55, 0.26, escape_math(m3_str), fontsize=32, fontweight='bold', color='#0F172A',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    p5_val = get_nested_val(results, "results.monthly_div_stats.all_months_p5")
    p95_val = get_nested_val(results, "results.monthly_div_stats.all_months_p95")
    p5_str = format_value(p5_val, {"kind": "number", "prefix": "NT$ ", "digits": 0, "thousands": True})
    p95_str = format_value(p95_val, {"kind": "number", "prefix": "NT$ ", "digits": 0, "thousands": True})
    interval_str = f"90% 區間：{p5_str} 至 {p95_str}"
    
    ax.text(0.55, 0.18, escape_math(interval_str), fontsize=11, color='#64748B',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Save figure
    out_path = os.path.join(OUT_DIR, "2_results.png")
    plt.savefig(out_path, dpi=150, facecolor='white', bbox_inches=None)
    plt.close()

def render_panel_3(p_spec, results, footer_text):
    title = p_spec["title"]
    alt = p_spec["alt"]
    
    # Extract metrics and text
    m1_spec = [b for b in p_spec["blocks"] if b["kind"] == "metric" and b["label"] == "試算表隱含的現金殖利率"][0]
    m1_val = get_nested_val(results, m1_spec["value"]["path"])
    m1_str = format_value(m1_val, m1_spec["value"]["format"])
    
    m2_spec = [b for b in p_spec["blocks"] if b["kind"] == "metric" and b["label"] == "模擬可實現殖利率中位數"][0]
    m2_val = get_nested_val(results, m2_spec["value"]["path"])
    m2_str = format_value(m2_val, m2_spec["value"]["format"])
    
    m3_spec = [b for b in p_spec["blocks"] if b["kind"] == "metric" and b["label"] == "可實現殖利率達到宣傳水準的機率"][0]
    m3_val = get_nested_val(results, m3_spec["value"]["path"])
    m3_str = format_value(m3_val, m3_spec["value"]["format"])
    
    t_spec = [b for b in p_spec["blocks"] if b["kind"] == "text" and b["heading"] == "研究邊界"][0]
    heading = t_spec["heading"]
    body_lines = t_spec["body"]
    
    # Setup plot
    fig, ax = plt.subplots(figsize=(1600/150, 1000/150), dpi=150)
    ax.axis('off')
    fig.patch.set_facecolor('white')
    
    # Draw common elements
    draw_common_elements(ax, title, alt, footer_text)
    
    # Left Column - Top Left Card (Implied Yield)
    draw_card(ax, 0.05, 0.44, 0.28, 0.74, facecolor='#F1F5F9', edgecolor='#E2E8F0', accent_color='#64748B')
    label1 = m1_spec["label"].replace("試算表隱含的現金殖利率", "試算表隱含的\n現金殖利率")
    ax.text(0.08, 0.66, escape_math(label1), fontsize=12, fontweight='bold', color='#475569',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.08, 0.52, escape_math(m1_str), fontsize=32, fontweight='bold', color='#64748B',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Left Column - Top Right Card (Realized Yield Median)
    draw_card(ax, 0.30, 0.44, 0.53, 0.74, facecolor='#EFF6FF', edgecolor='#DBEAFE', accent_color='#2563EB')
    label2 = m2_spec["label"].replace("模擬可實現殖利率中位數", "模擬可實現\n殖利率中位數")
    ax.text(0.33, 0.66, escape_math(label2), fontsize=12, fontweight='bold', color='#1E40AF',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.33, 0.52, escape_math(m2_str), fontsize=32, fontweight='bold', color='#1D4ED8',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Left Column - Bottom Wide Card (Probability Callout)
    draw_card(ax, 0.05, 0.14, 0.53, 0.40, facecolor='#FEF2F2', edgecolor='#FEE2E2', accent_color='#DC2626')
    ax.text(0.08, 0.34, escape_math(m3_spec["label"]), fontsize=13, fontweight='bold', color='#991B1B',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    ax.text(0.08, 0.22, escape_math(m3_str), fontsize=32, fontweight='bold', color='#DC2626',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    n_sim = get_nested_val(results, "config.n_sim")
    implied_yield_val = get_nested_val(results, "results.yield_stats.implied_yield_from_chart")
    implied_yield_str = format_value(implied_yield_val, {"kind": "percent", "digits": 1})
    desc_str = f"({n_sim:,} 次模擬中無一達到 {implied_yield_str} 殖利率)"
    
    ax.text(0.20, 0.22, escape_math(desc_str), fontsize=11, color='#991B1B',
            fontfamily='Heiti TC', transform=ax.transAxes, va='bottom')
    
    # Right Column - Editorial Card (研究邊界)
    draw_card(ax, 0.56, 0.14, 0.95, 0.74, facecolor='#FAF8F5', edgecolor='#E5E7EB', accent_color='#B45309')
    ax.text(0.59, 0.68, escape_math(heading), fontsize=16, fontweight='bold', color='#78350F',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    
    # Bullet points rendering
    # Bullet 1
    ax.text(0.59, 0.61, escape_math("• 歷史樣本限制"), fontsize=13, fontweight='bold', color='#92400E',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    draw_wrapped_text(ax, body_lines[0], 0.59, 0.57, 17, 11, '#78350F', line_height=0.034, va='top')
    
    # Bullet 2
    ax.text(0.59, 0.39, escape_math("• 抽樣邊界效應"), fontsize=13, fontweight='bold', color='#92400E',
            fontfamily='Heiti TC', transform=ax.transAxes, va='center')
    draw_wrapped_text(ax, body_lines[1], 0.59, 0.35, 17, 11, '#78350F', line_height=0.034, va='top')
    
    # Save figure
    out_path = os.path.join(OUT_DIR, "3_takeaway.png")
    plt.savefig(out_path, dpi=150, facecolor='white', bbox_inches=None)
    plt.close()

def main():
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        
        with open(PLAN_PATH, "r", encoding="utf-8") as f:
            plan = json.load(f)
            
        with open(RESULTS_PATH, "r", encoding="utf-8") as f:
            results = json.load(f)
            
        # Get strict source label from plan
        footer_text = plan["evidence"]["results"]["label"]
        
        # Build index map
        panels_by_name = {p["name"]: p for p in plan["panels"]}
        
        # Render panel 1
        render_panel_1(panels_by_name["1_method"], results, footer_text)
        print("OK: 1_method.png generated successfully.")
        
        # Render panel 2
        render_panel_2(panels_by_name["2_results"], results, footer_text)
        print("OK: 2_results.png generated successfully.")
        
        # Render panel 3
        render_panel_3(panels_by_name["3_takeaway"], results, footer_text)
        print("OK: 3_takeaway.png generated successfully.")
        
    except Exception as e:
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
