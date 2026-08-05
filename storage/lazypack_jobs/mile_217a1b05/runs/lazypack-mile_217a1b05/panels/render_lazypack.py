#!/usr/bin/env python3
"""
Lazypack renderer for VolPred article mile_217a1b05.
Binds numbers directly from results.json and outputs 3 PNG panels.
"""

import json
import os
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Set CJK font directly as requested
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# Absolute file paths
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_217a1b05/runs/lazypack-mile_217a1b05/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1536/k1536_results.json"
ARTICLE_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_217a1b05/runs/lazypack-mile_217a1b05/panels/mile_217a1b05_article.md"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_217a1b05/runs/lazypack-mile_217a1b05/panels"

SOURCE_LABEL = "K1536 生態足跡商品波動率事件研究結果"

def resolve_path(data, path_str):
    parts = path_str.split(".")
    cur = data
    for part in parts:
        if isinstance(cur, list):
            try:
                idx = int(part)
                cur = cur[idx]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Failed to access index {part} in path '{path_str}'") from exc
        elif isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Key '{part}' not found in path '{path_str}'")
            cur = cur[part]
        else:
            raise KeyError(f"Cannot traverse '{part}' in path '{path_str}' on type {type(cur)}")
    return cur

def format_value(raw_val, fmt_spec):
    kind = fmt_spec.get("kind")
    if kind == "integer":
        suffix = fmt_spec.get("suffix", "")
        return f"{int(raw_val)}{suffix}"
    elif kind == "date":
        return str(raw_val)
    elif kind == "number":
        digits = fmt_spec.get("digits", 2)
        show_plus = fmt_spec.get("show_plus", False)
        val_float = float(raw_val)
        if show_plus and val_float > 0:
            return f"+{val_float:.{digits}f}"
        else:
            return f"{val_float:.{digits}f}"
    else:
        return str(raw_val)

def draw_header_and_footer(ax, title, alt):
    # Header container
    header_bg = patches.FancyBboxPatch(
        (0.04, 0.86), 0.92, 0.11,
        boxstyle="round,pad=0.005,rounding_size=0.015",
        facecolor='#1E293B', edgecolor='none', zorder=1
    )
    ax.add_patch(header_bg)
    ax.text(0.06, 0.93, title, fontsize=22, fontweight='bold', color='#FFFFFF', va='center', zorder=2)
    
    wrapped_alt = textwrap.fill(alt, width=56)
    ax.text(0.06, 0.885, wrapped_alt, fontsize=11, color='#94A3B8', va='center', zorder=2)
    
    # Footer line and source text
    ax.plot([0.04, 0.96], [0.06, 0.06], color='#CBD5E1', linewidth=1, zorder=1)
    ax.text(0.04, 0.03, f"資料來源：{SOURCE_LABEL}", fontsize=11, color='#64748B', va='center', zorder=2)

def render_panel_1(panel_plan, results_data, out_path):
    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    draw_header_and_footer(ax, panel_plan['title'], panel_plan['alt'])
    
    # Left Card: Concept text
    left_bg = patches.FancyBboxPatch(
        (0.04, 0.10), 0.56, 0.73,
        boxstyle="round,pad=0.01,rounding_size=0.02",
        facecolor='#FFFFFF', edgecolor='#CBD5E1', linewidth=1.5, zorder=1
    )
    ax.add_patch(left_bg)
    
    text_block = panel_plan['blocks'][0]
    ax.text(0.07, 0.78, text_block['heading'], fontsize=18, fontweight='bold', color='#0F172A', zorder=2)
    
    y_pos = 0.69
    for i, line in enumerate(text_block['body'], 1):
        wrapped = textwrap.fill(f"{i}. {line}", width=34)
        ax.text(0.07, y_pos, wrapped, fontsize=13, color='#334155', linespacing=1.4, va='top', zorder=2)
        y_pos -= 0.19
        
    # Right Cards: Metrics
    metrics_configs = [
        (panel_plan['blocks'][1], 0.61, '#F0F9FF', '#BAE6FD', '#0369A1'),
        (panel_plan['blocks'][2], 0.36, '#F0FDF4', '#BBF7D0', '#15803D'),
        (panel_plan['blocks'][3], 0.11, '#F5F3FF', '#DDD6FE', '#6D28D9'),
    ]
    
    for metric_block, y, bg_color, border_color, accent_color in metrics_configs:
        card_bg = patches.FancyBboxPatch(
            (0.63, y), 0.33, 0.22,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor=bg_color, edgecolor=border_color, linewidth=1.5, zorder=1
        )
        ax.add_patch(card_bg)
        
        raw_val = resolve_path(results_data, metric_block['value']['path'])
        formatted_val = format_value(raw_val, metric_block['value']['format'])
        
        ax.text(0.66, y + 0.16, metric_block['label'], fontsize=14, fontweight='bold', color=accent_color, zorder=2)
        ax.text(0.66, y + 0.07, formatted_val, fontsize=24, fontweight='bold', color='#0F172A', zorder=2)
        
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close(fig)

def render_panel_2(panel_plan, results_data, out_path):
    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    draw_header_and_footer(ax, panel_plan['title'], panel_plan['alt'])
    
    # Top Row Bento Cards (Metrics)
    bento_metrics = [
        (panel_plan['blocks'][0], 0.04, '#FEF2F2', '#FCA5A5', '#991B1B', '#DC2626'),
        (panel_plan['blocks'][1], 0.28, '#FEF2F2', '#FCA5A5', '#991B1B', '#DC2626'),
        (panel_plan['blocks'][2], 0.52, '#FFF7ED', '#FDBA74', '#C2410C', '#EA580C'),
        (panel_plan['blocks'][3], 0.76, '#FFF7ED', '#FDBA74', '#C2410C', '#EA580C'),
    ]
    
    for metric_block, x, bg_color, border_color, label_color, val_color in bento_metrics:
        card_bg = patches.FancyBboxPatch(
            (x, 0.49), 0.20, 0.34,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor=bg_color, edgecolor=border_color, linewidth=1.5, zorder=1
        )
        ax.add_patch(card_bg)
        
        raw_val = resolve_path(results_data, metric_block['value']['path'])
        formatted_val = format_value(raw_val, metric_block['value']['format'])
        
        wrapped_label = textwrap.fill(metric_block['label'], width=12)
        ax.text(x + 0.02, 0.76, wrapped_label, fontsize=13, fontweight='bold', color=label_color, va='top', zorder=2)
        ax.text(x + 0.02, 0.56, formatted_val, fontsize=26, fontweight='bold', color=val_color, zorder=2)
        
    # Bottom Row Bento Card (Text)
    text_bg = patches.FancyBboxPatch(
        (0.04, 0.10), 0.92, 0.35,
        boxstyle="round,pad=0.01,rounding_size=0.02",
        facecolor='#F8FAFC', edgecolor='#CBD5E1', linewidth=1.5, zorder=1
    )
    ax.add_patch(text_bg)
    
    text_block = panel_plan['blocks'][4]
    ax.text(0.07, 0.38, text_block['heading'], fontsize=16, fontweight='bold', color='#0F172A', zorder=2)
    
    y_pos = 0.31
    for line in text_block['body']:
        wrapped = textwrap.fill(f"• {line}", width=56)
        ax.text(0.07, y_pos, wrapped, fontsize=13, color='#334155', linespacing=1.4, va='top', zorder=2)
        y_pos -= 0.10
        
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close(fig)

def render_panel_3(panel_plan, results_data, out_path):
    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    draw_header_and_footer(ax, panel_plan['title'], panel_plan['alt'])
    
    # Left 2x2 Metric Grid
    grid_metrics = [
        (panel_plan['blocks'][0], 0.04, 0.49, '#F1F5F9', '#CBD5E1', '#475569', '#0F172A'),
        (panel_plan['blocks'][1], 0.27, 0.49, '#F1F5F9', '#CBD5E1', '#475569', '#0F172A'),
        (panel_plan['blocks'][2], 0.04, 0.10, '#F1F5F9', '#CBD5E1', '#475569', '#0F172A'),
        (panel_plan['blocks'][3], 0.27, 0.10, '#EFF6FF', '#BFDBFE', '#1D4ED8', '#1E40AF'),
    ]
    
    for metric_block, x, y, bg_color, border_color, label_color, val_color in grid_metrics:
        card_bg = patches.FancyBboxPatch(
            (x, y), 0.21, 0.35,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor=bg_color, edgecolor=border_color, linewidth=1.5, zorder=1
        )
        ax.add_patch(card_bg)
        
        raw_val = resolve_path(results_data, metric_block['value']['path'])
        formatted_val = format_value(raw_val, metric_block['value']['format'])
        
        wrapped_label = textwrap.fill(metric_block['label'], width=12)
        ax.text(x + 0.02, y + 0.27, wrapped_label, fontsize=13, fontweight='bold', color=label_color, va='top', zorder=2)
        ax.text(x + 0.02, y + 0.07, formatted_val, fontsize=24, fontweight='bold', color=val_color, zorder=2)
        
    # Right Scientific Panel (Text)
    right_bg = patches.FancyBboxPatch(
        (0.51, 0.10), 0.45, 0.74,
        boxstyle="round,pad=0.01,rounding_size=0.02",
        facecolor='#F8FAFC', edgecolor='#CBD5E1', linewidth=1.5, zorder=1
    )
    ax.add_patch(right_bg)
    
    text_block = panel_plan['blocks'][4]
    ax.text(0.54, 0.78, text_block['heading'], fontsize=16, fontweight='bold', color='#0F172A', zorder=2)
    
    y_pos = 0.70
    for line in text_block['body']:
        wrapped = textwrap.fill(f"• {line}", width=26)
        ax.text(0.54, y_pos, wrapped, fontsize=13, color='#334155', linespacing=1.4, va='top', zorder=2)
        y_pos -= 0.19
        
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close(fig)

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan_data = json.load(f)
        
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)
        
    panels = plan_data.get("panels", [])
    
    for panel in panels:
        name = panel.get("name")
        out_path = os.path.join(OUT_DIR, f"{name}.png")
        
        if name == "1_concept":
            render_panel_1(panel, results_data, out_path)
        elif name == "2_results":
            render_panel_2(panel, results_data, out_path)
        elif name == "3_takeaway":
            render_panel_3(panel, results_data, out_path)
        else:
            raise ValueError(f"Unknown panel name: {name}")

if __name__ == "__main__":
    main()
