#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render script for VolPred Lazypack: mile_16c9f784
Generates PNG panels using matplotlib.
"""
import os
import json
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Absolute paths to evidence and configuration files
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k492/k492_research_efficiency_results.json"
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_16c9f784/runs/lazypack-mile_16c9f784/plan.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_16c9f784/runs/lazypack-mile_16c9f784/panels"

# Configure matplotlib for Traditional Chinese rendering
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

def resolve_path(data, dotted_path):
    """
    Resolve a dotted path in a nested dictionary.
    Raises KeyError or TypeError if any field is missing.
    """
    parts = dotted_path.split('.')
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Key '{part}' not found in path '{dotted_path}'")
            current = current[part]
        else:
            raise TypeError(f"Cannot resolve key '{part}' in non-dict object of type {type(current)} for path '{dotted_path}'")
    return current

def format_value(value, format_spec):
    """
    Format a value according to the specified format rules.
    """
    kind = format_spec.get("kind")
    suffix = format_spec.get("suffix", "")
    scale = format_spec.get("scale", 1)
    
    val = value * scale
    if kind == "integer":
        return f"{int(round(val))}{suffix}"
    elif kind == "number":
        digits = format_spec.get("digits", 1)
        return f"{val:.{digits}f}{suffix}"
    else:
        return f"{val}{suffix}"

def draw_card(ax, x, y, width, height, facecolor='#FFFFFF', edgecolor='#E5E7EB', linewidth=1.5):
    """
    Draw a clean, professional rectangular card.
    """
    rect = patches.Rectangle((x, y), width, height, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth, transform=ax.transData)
    ax.add_patch(rect)

def get_line_spacing(fontsize, gap=4):
    """
    Calculate coordinate spacing for a given font size.
    """
    return (fontsize + gap) / (72.0 * 6.667)

def draw_wrapped_text(ax, x, y, text, width_chars, fontsize, color='#374151', spacing=None, weight='normal', ha='left', va='top'):
    """
    Wrap and draw text line-by-line to prevent overflows and overlaps.
    """
    if spacing is None:
        spacing = get_line_spacing(fontsize)
    lines = textwrap.wrap(text, width=width_chars)
    current_y = y
    for line in lines:
        ax.text(x, current_y, line, fontsize=fontsize, color=color, weight=weight, ha=ha, va=va, transform=ax.transData)
        current_y -= spacing
    return current_y

def draw_footer(ax, text):
    """
    Draw footer with data sources.
    """
    ax.text(0.05, 0.05, f"資料來源：{text}", fontsize=10, color='#9CA3AF', ha='left', va='center')

def render_panel_1(results_data, plan_data):
    fig, ax = plt.subplots(figsize=(10.667, 6.667), dpi=150)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    fig.patch.set_facecolor('#F9FAFB')
    ax.set_facecolor('#F9FAFB')
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    
    panel_info = plan_data['panels'][0]
    title = panel_info['title']
    subtitle = panel_info['alt']
    
    # 1. Header (Professional: Dark Title Bar)
    header_rect = patches.Rectangle((0, 0.80), 1.0, 0.20, facecolor='#111827', edgecolor='none', transform=ax.transData)
    ax.add_patch(header_rect)
    
    ax.text(0.05, 0.91, title, color='#FFFFFF', fontsize=22, weight='bold', ha='left', va='center')
    ax.text(0.05, 0.85, subtitle, color='#9CA3AF', fontsize=12, ha='left', va='center')
    
    # 2. Main Content Area
    # Left Card (Text block)
    draw_card(ax, 0.05, 0.16, 0.50, 0.58, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    
    text_block = panel_info['blocks'][0]
    ax.text(0.08, 0.68, text_block['heading'], fontsize=16, color='#111827', weight='bold', ha='left', va='center')
    
    y_pos = 0.58
    p1 = text_block['body'][0]
    y_pos = draw_wrapped_text(ax, 0.08, y_pos, p1, width_chars=28, fontsize=12, color='#374151')
    
    y_pos -= 0.04
    p2 = text_block['body'][1]
    draw_wrapped_text(ax, 0.08, y_pos, p2, width_chars=28, fontsize=12, color='#374151')
    
    # Right Card (Metric block)
    draw_card(ax, 0.60, 0.16, 0.35, 0.58, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    
    metric_block = panel_info['blocks'][1]
    metric_label = metric_block['label']
    val_path = metric_block['value']['path']
    val_fmt = metric_block['value']['format']
    
    val_raw = resolve_path(results_data, val_path)
    val_str = format_value(val_raw, val_fmt)
    
    ax.text(0.63, 0.62, metric_label, fontsize=14, color='#4B5563', weight='bold', ha='left', va='center')
    ax.text(0.63, 0.45, val_str, fontsize=42, color='#0F766E', weight='bold', ha='left', va='center')
    
    metric_desc = "在波動率預測研究中測試的想法，每一個都是認真的嘗試。"
    draw_wrapped_text(ax, 0.63, 0.32, metric_desc, width_chars=18, fontsize=11, color='#6B7280')
    
    # 3. Footer
    source_label = plan_data['evidence']['results']['label']
    draw_footer(ax, source_label)
    
    # Save file
    plt.savefig(os.path.join(OUT_DIR, "1_concept.png"), dpi=150)
    plt.close()

def render_panel_2(results_data, plan_data):
    fig, ax = plt.subplots(figsize=(10.667, 6.667), dpi=150)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    fig.patch.set_facecolor('#F9FAFB')
    ax.set_facecolor('#F9FAFB')
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    
    panel_info = plan_data['panels'][1]
    title = panel_info['title']
    subtitle = panel_info['alt']
    
    # 1. Header (Bento-grid: Premium Teal Title Bar)
    header_rect = patches.Rectangle((0, 0.80), 1.0, 0.20, facecolor='#0F766E', edgecolor='none', transform=ax.transData)
    ax.add_patch(header_rect)
    
    ax.text(0.05, 0.91, title, color='#FFFFFF', fontsize=22, weight='bold', ha='left', va='center')
    ax.text(0.05, 0.85, subtitle, color='#CCFBF1', fontsize=12, ha='left', va='center')
    
    # 2. Bento Grid Cards
    # Card 1 (Left, large card)
    draw_card(ax, 0.05, 0.16, 0.43, 0.58, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    
    metric1 = panel_info['blocks'][0]
    val1_raw = resolve_path(results_data, metric1['value']['path'])
    val1_str = format_value(val1_raw, metric1['value']['format'])
    
    ax.text(0.08, 0.68, metric1['label'], fontsize=15, color='#4B5563', weight='bold', ha='left', va='center')
    ax.text(0.08, 0.52, val1_str, fontsize=48, color='#BE123C', weight='bold', ha='left', va='center')
    
    desc1 = "無效果佔比最高，代表多數波動率預測想法在回測中不具顯著性。這是量化研究的常態。"
    draw_wrapped_text(ax, 0.08, 0.38, desc1, width_chars=24, fontsize=11, color='#6B7280')
    
    # Card 2 (Top Right)
    draw_card(ax, 0.51, 0.47, 0.44, 0.27, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    
    metric2 = panel_info['blocks'][1]
    val2_raw = resolve_path(results_data, metric2['value']['path'])
    val2_str = format_value(val2_raw, metric2['value']['format'])
    
    ax.text(0.54, 0.66, metric2['label'], fontsize=14, color='#4B5563', weight='bold', ha='left', va='center')
    ax.text(0.54, 0.54, val2_str, fontsize=32, color='#0F766E', weight='bold', ha='left', va='center')
    
    # Card 3 (Bottom Right)
    draw_card(ax, 0.51, 0.16, 0.44, 0.27, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    
    metric3 = panel_info['blocks'][2]
    val3_raw = resolve_path(results_data, metric3['value']['path'])
    val3_str = format_value(val3_raw, metric3['value']['format'])
    
    ax.text(0.54, 0.35, metric3['label'], fontsize=13, color='#4B5563', weight='bold', ha='left', va='center')
    ax.text(0.54, 0.23, val3_str, fontsize=32, color='#B45309', weight='bold', ha='left', va='center')
    
    # 3. Footer
    source_label = plan_data['evidence']['results']['label']
    draw_footer(ax, source_label)
    
    # Save file
    plt.savefig(os.path.join(OUT_DIR, "2_results.png"), dpi=150)
    plt.close()

def render_panel_3(results_data, plan_data):
    fig, ax = plt.subplots(figsize=(10.667, 6.667), dpi=150)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    fig.patch.set_facecolor('#F9FAFB')
    ax.set_facecolor('#F9FAFB')
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    
    panel_info = plan_data['panels'][2]
    title = panel_info['title']
    subtitle = panel_info['alt']
    
    # 1. Header (Editorial: Premium Rose/Crimson Title Bar)
    header_rect = patches.Rectangle((0, 0.80), 1.0, 0.20, facecolor='#BE123C', edgecolor='none', transform=ax.transData)
    ax.add_patch(header_rect)
    
    ax.text(0.05, 0.91, title, color='#FFFFFF', fontsize=22, weight='bold', ha='left', va='center')
    ax.text(0.05, 0.85, subtitle, color='#FFE4E6', fontsize=12, ha='left', va='center')
    
    # 2. Editorial Layout
    # Left Column: Survival comparison visual + mini metrics
    # Draw survival horizontal bar
    bar_y = 0.65
    bar_height = 0.06
    bar_total_width = 0.45
    bar_start_x = 0.05
    
    # 17 validated experiments: 8 survived, 9 failed
    survived_ratio = 8.0 / 17.0
    failed_ratio = 9.0 / 17.0
    
    survived_width = bar_total_width * survived_ratio
    failed_width = bar_total_width * failed_ratio
    
    # Draw Survived (Teal)
    survived_rect = patches.Rectangle((bar_start_x, bar_y), survived_width, bar_height, facecolor='#0F766E', edgecolor='none', transform=ax.transData)
    ax.add_patch(survived_rect)
    
    # Draw Failed (Rose/Crimson)
    failed_rect = patches.Rectangle((bar_start_x + survived_width, bar_y), failed_width, bar_height, facecolor='#BE123C', edgecolor='none', transform=ax.transData)
    ax.add_patch(failed_rect)
    
    # Add text labels
    ax.text(bar_start_x, bar_y + 0.08, "跨樣本存活對照 (共 17 個確定判定)", fontsize=13, color='#1F2937', weight='bold', ha='left', va='center')
    ax.text(bar_start_x + survived_width/2, bar_y + 0.03, "仍有效 (47.1%)", fontsize=10, color='#FFFFFF', weight='bold', ha='center', va='center')
    ax.text(bar_start_x + survived_width + failed_width/2, bar_y + 0.03, "失效 (52.9%)", fontsize=10, color='#FFFFFF', weight='bold', ha='center', va='center')
    
    # Horizontal row of 3 metric cards
    card_y = 0.16
    card_h = 0.40
    card_w = 0.14
    gap = 0.015
    
    # Card 1: n_experiments_with_cross_oos
    x1 = 0.05
    draw_card(ax, x1, card_y, card_w, card_h, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    metric1 = panel_info['blocks'][0]
    val1_raw = resolve_path(results_data, metric1['value']['path'])
    val1_str = format_value(val1_raw, metric1['value']['format'])
    draw_wrapped_text(ax, x1 + 0.015, card_y + 0.35, metric1['label'], width_chars=6, fontsize=10, color='#4B5563')
    ax.text(x1 + 0.015, card_y + 0.12, val1_str, fontsize=20, color='#1F2937', weight='bold', ha='left', va='center')
    
    # Card 2: failure_rate_pct
    x2 = x1 + card_w + gap
    draw_card(ax, x2, card_y, card_w, card_h, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    metric2 = panel_info['blocks'][1]
    val2_raw = resolve_path(results_data, metric2['value']['path'])
    val2_str = format_value(val2_raw, metric2['value']['format'])
    draw_wrapped_text(ax, x2 + 0.015, card_y + 0.35, metric2['label'], width_chars=6, fontsize=10, color='#4B5563')
    ax.text(x2 + 0.015, card_y + 0.12, val2_str, fontsize=20, color='#BE123C', weight='bold', ha='left', va='center')
    
    # Card 3: n_survived
    x3 = x2 + card_w + gap
    draw_card(ax, x3, card_y, card_w, card_h, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    metric3 = panel_info['blocks'][2]
    val3_raw = resolve_path(results_data, metric3['value']['path'])
    val3_str = format_value(val3_raw, metric3['value']['format'])
    draw_wrapped_text(ax, x3 + 0.015, card_y + 0.35, metric3['label'], width_chars=6, fontsize=10, color='#4B5563')
    ax.text(x3 + 0.015, card_y + 0.12, val3_str, fontsize=20, color='#0F766E', weight='bold', ha='left', va='center')
    
    # Right Column: Text takeaways
    draw_card(ax, 0.54, 0.16, 0.41, 0.58, facecolor='#FFFFFF', edgecolor='#E5E7EB')
    
    text_block = panel_info['blocks'][3]
    ax.text(0.57, 0.68, text_block['heading'], fontsize=16, color='#1F2937', weight='bold', ha='left', va='center')
    
    y_pos = 0.58
    p1 = text_block['body'][0]
    y_pos = draw_wrapped_text(ax, 0.57, y_pos, p1, width_chars=22, fontsize=11, color='#374151')
    
    y_pos -= 0.04
    p2 = text_block['body'][1]
    draw_wrapped_text(ax, 0.57, y_pos, p2, width_chars=22, fontsize=11, color='#374151')
    
    # 3. Footer
    source_label = plan_data['evidence']['results']['label']
    draw_footer(ax, source_label)
    
    # Save file
    plt.savefig(os.path.join(OUT_DIR, "3_takeaway.png"), dpi=150)
    plt.close()

def main():
    # Ensure output directory exists
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Load JSON files
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan_data = json.load(f)
        
    # Render Panels
    render_panel_1(results_data, plan_data)
    render_panel_2(results_data, plan_data)
    render_panel_3(results_data, plan_data)
    print("All panels rendered successfully.")

if __name__ == "__main__":
    main()
