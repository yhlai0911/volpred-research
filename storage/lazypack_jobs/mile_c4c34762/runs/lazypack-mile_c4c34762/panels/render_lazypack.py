#!/usr/bin/env python3
"""
Render script for mile_c4c34762 lazypack panels.
Binds evidence numbers from K1704_results.json and outputs 3 PNG panels.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Configure Matplotlib fonts
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

PLAN_PATH = Path("/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_c4c34762/runs/lazypack-mile_c4c34762/plan.json")
RESULTS_PATH = Path("/Users/yhlai0911/volpred-research/experiments/k1704/K1704_results.json")
OUT_DIR = Path("/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_c4c34762/runs/lazypack-mile_c4c34762/panels")

def get_nested_val(data: dict, path_str: str) -> Any:
    keys = path_str.split(".")
    curr = data
    for k in keys:
        if isinstance(curr, dict) and k in curr:
            curr = curr[k]
        else:
            raise KeyError(f"Missing key '{k}' in JSON path '{path_str}'")
    return curr

def format_val(val: Any, fmt_spec: dict) -> str:
    kind = fmt_spec.get("kind")
    if kind == "integer":
        res = f"{int(val):,}"
        if "suffix" in fmt_spec:
            res += fmt_spec["suffix"]
        return res
    elif kind == "date":
        return str(val)
    elif kind == "number":
        digits = fmt_spec.get("digits", 3)
        show_plus = fmt_spec.get("show_plus", False)
        v = float(val)
        if show_plus and v > 0:
            res = f"+{v:.{digits}f}"
        else:
            res = f"{v:.{digits}f}"
        if "suffix" in fmt_spec:
            res += fmt_spec["suffix"]
        return res
    else:
        return str(val)

def draw_rounded_card(ax, x, y, width, height, bg_color="#FFFFFF", border_color="#E2E8F0", linewidth=1.5):
    rect = patches.FancyBboxPatch(
        (x, y), width, height,
        boxstyle=patches.BoxStyle("Round", pad=0.0, rounding_size=0.02),
        facecolor=bg_color,
        edgecolor=border_color,
        linewidth=linewidth,
        transform=ax.transAxes,
        clip_on=False
    )
    ax.add_patch(rect)

def render_panel_1(plan_panel: dict, results_data: dict, source_label: str, out_path: Path):
    fig, ax = plt.subplots(figsize=(10.666667, 6.666667), dpi=150)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.axis("off")

    # Header Banner Card
    draw_rounded_card(ax, 0.03, 0.82, 0.94, 0.15, bg_color="#0F172A", border_color="#1E293B")
    ax.text(0.06, 0.91, plan_panel["title"], transform=ax.transAxes, fontsize=20, fontweight="bold", color="#FFFFFF", va="center")
    ax.text(0.06, 0.85, plan_panel["alt"], transform=ax.transAxes, fontsize=12, color="#94A3B8", va="center")

    # Left Column: Concept / Text Block
    text_block = [b for b in plan_panel["blocks"] if b["kind"] == "text"][0]
    draw_rounded_card(ax, 0.03, 0.08, 0.54, 0.71, bg_color="#FFFFFF", border_color="#E2E8F0")
    
    ax.text(0.06, 0.74, text_block["heading"], transform=ax.transAxes, fontsize=16, fontweight="bold", color="#0D9488", va="center")
    
    y_cursor = 0.67
    for line in text_block["body"]:
        wrapped = textwrap.fill(line, width=28)
        line_count = wrapped.count("\n") + 1
        ax.text(0.06, y_cursor, wrapped, transform=ax.transAxes, fontsize=11.5, color="#334155", va="top", linespacing=1.5)
        y_cursor -= (0.05 * line_count + 0.03)

    # Right Column: 3 Metric Cards
    metric_blocks = [b for b in plan_panel["blocks"] if b["kind"] == "metric"]
    y_positions = [0.57, 0.33, 0.08]
    card_height = 0.22

    for b, y_pos in zip(metric_blocks, y_positions):
        val_raw = get_nested_val(results_data, b["value"]["path"])
        val_str = format_val(val_raw, b["value"]["format"])
        
        draw_rounded_card(ax, 0.60, y_pos, 0.37, card_height, bg_color="#FFFFFF", border_color="#E2E8F0")
        ax.text(0.63, y_pos + 0.16, b["label"], transform=ax.transAxes, fontsize=12, color="#64748B", va="center")
        ax.text(0.63, y_pos + 0.07, val_str, transform=ax.transAxes, fontsize=20, fontweight="bold", color="#0F172A", va="center")

    # Footer
    ax.text(0.03, 0.03, f"來源：{source_label}", transform=ax.transAxes, fontsize=10, color="#64748B", va="center")

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)

def render_panel_2(plan_panel: dict, results_data: dict, source_label: str, out_path: Path):
    fig, ax = plt.subplots(figsize=(10.666667, 6.666667), dpi=150)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.axis("off")

    # Header Banner Card
    draw_rounded_card(ax, 0.03, 0.82, 0.94, 0.15, bg_color="#0F172A", border_color="#1E293B")
    ax.text(0.06, 0.91, plan_panel["title"], transform=ax.transAxes, fontsize=20, fontweight="bold", color="#FFFFFF", va="center")
    ax.text(0.06, 0.85, plan_panel["alt"], transform=ax.transAxes, fontsize=12, color="#94A3B8", va="center")

    # Bento Grid Top Row: 4 Metric Cards
    metric_blocks = [b for b in plan_panel["blocks"] if b["kind"] == "metric"]
    card_width = 0.218
    gap = 0.022
    x_start = 0.03

    colors = ["#2563EB", "#334155", "#334155", "#0D9488"]
    
    for i, b in enumerate(metric_blocks):
        val_raw = get_nested_val(results_data, b["value"]["path"])
        val_str = format_val(val_raw, b["value"]["format"])
        x_pos = x_start + i * (card_width + gap)
        
        draw_rounded_card(ax, x_pos, 0.50, card_width, 0.28, bg_color="#FFFFFF", border_color="#E2E8F0")
        
        label_wrapped = textwrap.fill(b["label"], width=12)
        ax.text(x_pos + 0.02, 0.73, label_wrapped, transform=ax.transAxes, fontsize=11, color="#64748B", va="top", linespacing=1.2)
        ax.text(x_pos + 0.02, 0.57, val_str, transform=ax.transAxes, fontsize=22, fontweight="bold", color=colors[i], va="center")

    # Bento Grid Bottom Row: Text / Explanation Card
    text_block = [b for b in plan_panel["blocks"] if b["kind"] == "text"][0]
    draw_rounded_card(ax, 0.03, 0.08, 0.94, 0.38, bg_color="#FFFFFF", border_color="#CBD5E1")
    
    ax.text(0.06, 0.40, text_block["heading"], transform=ax.transAxes, fontsize=16, fontweight="bold", color="#0F172A", va="center")
    
    y_cursor = 0.33
    for line in text_block["body"]:
        wrapped = textwrap.fill(line, width=54)
        line_count = wrapped.count("\n") + 1
        ax.text(0.06, y_cursor, wrapped, transform=ax.transAxes, fontsize=12, color="#334155", va="top", linespacing=1.4)
        y_cursor -= (0.05 * line_count + 0.02)

    # Footer
    ax.text(0.03, 0.03, f"來源：{source_label}", transform=ax.transAxes, fontsize=10, color="#64748B", va="center")

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)

def render_panel_3(plan_panel: dict, results_data: dict, source_label: str, out_path: Path):
    fig, ax = plt.subplots(figsize=(10.666667, 6.666667), dpi=150)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.axis("off")

    # Header Banner Card
    draw_rounded_card(ax, 0.03, 0.82, 0.94, 0.15, bg_color="#0F172A", border_color="#1E293B")
    ax.text(0.06, 0.91, plan_panel["title"], transform=ax.transAxes, fontsize=20, fontweight="bold", color="#FFFFFF", va="center")
    ax.text(0.06, 0.85, plan_panel["alt"], transform=ax.transAxes, fontsize=12, color="#94A3B8", va="center")

    # Top Grid: 2x2 Metric Cards
    metric_blocks = [b for b in plan_panel["blocks"] if b["kind"] == "metric"]
    
    grid_coords = [
        (0.03, 0.65), # Top Left
        (0.51, 0.65), # Top Right
        (0.03, 0.47), # Bottom Left
        (0.51, 0.47), # Bottom Right
    ]
    card_w = 0.46
    card_h = 0.15

    highlights = ["#2563EB", "#2563EB", "#D97706", "#D97706"]

    for b, (xp, yp), col in zip(metric_blocks, grid_coords, highlights):
        val_raw = get_nested_val(results_data, b["value"]["path"])
        val_str = format_val(val_raw, b["value"]["format"])
        
        draw_rounded_card(ax, xp, yp, card_w, card_h, bg_color="#FFFFFF", border_color="#E2E8F0")
        ax.text(xp + 0.03, yp + 0.10, b["label"], transform=ax.transAxes, fontsize=12, color="#64748B", va="center")
        ax.text(xp + 0.03, yp + 0.04, val_str, transform=ax.transAxes, fontsize=20, fontweight="bold", color=col, va="center")

    # Bottom Half: Takeaway Card
    text_block = [b for b in plan_panel["blocks"] if b["kind"] == "text"][0]
    draw_rounded_card(ax, 0.03, 0.08, 0.94, 0.35, bg_color="#EFF6FF", border_color="#BFDBFE")
    
    ax.text(0.06, 0.37, text_block["heading"], transform=ax.transAxes, fontsize=16, fontweight="bold", color="#1E3A8A", va="center")
    
    y_cursor = 0.30
    for line in text_block["body"]:
        wrapped = textwrap.fill(line, width=54)
        line_count = wrapped.count("\n") + 1
        ax.text(0.06, y_cursor, wrapped, transform=ax.transAxes, fontsize=11.5, color="#1E293B", va="top", linespacing=1.4)
        y_cursor -= (0.05 * line_count + 0.02)

    # Footer
    ax.text(0.03, 0.03, f"來源：{source_label}", transform=ax.transAxes, fontsize=10, color="#64748B", va="center")

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    if not PLAN_PATH.exists():
        raise FileNotFoundError(f"Plan file not found at: {PLAN_PATH}")
    if not RESULTS_PATH.exists():
        raise FileNotFoundError(f"Results file not found at: {RESULTS_PATH}")

    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan = json.load(f)

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)

    source_label = plan["evidence"]["results"]["label"]

    for panel in plan["panels"]:
        name = panel["name"]
        out_path = OUT_DIR / f"{name}.png"
        
        if name == "1_concept":
            render_panel_1(panel, results_data, source_label, out_path)
        elif name == "2_results":
            render_panel_2(panel, results_data, source_label, out_path)
        elif name == "3_takeaway":
            render_panel_3(panel, results_data, source_label, out_path)
        else:
            raise ValueError(f"Unknown panel name: {name}")

if __name__ == "__main__":
    main()
