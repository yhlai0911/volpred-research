#!/usr/bin/env python3
"""Standalone lazypack renderer for mile_f9a81b80 article.

Reads evidence data from absolute paths and outputs 3 PNG panels to out_dir.
"""

import json
import os
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Absolute paths
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_f9a81b80/runs/lazypack-mile_f9a81b80/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1706/K1706_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_f9a81b80/runs/lazypack-mile_f9a81b80/panels"

# Font setup
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False


def resolve_path(data: dict, path: str):
    """Navigate nested dict/list structures by dot notation (e.g., 'primary_did.2.ri_p_holm_8')."""
    cur = data
    parts = path.split(".")
    for p in parts:
        if isinstance(cur, dict):
            if p not in cur:
                raise KeyError(f"Field path '{path}' missing key '{p}'")
            cur = cur[p]
        elif isinstance(cur, list):
            try:
                idx = int(p)
                cur = cur[idx]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Field path '{path}' invalid array index '{p}'") from e
        else:
            raise KeyError(f"Field path '{path}' cannot navigate key '{p}' in type {type(cur).__name__}")
    return cur


def format_value(value, fmt_spec: dict) -> str:
    """Format raw evidence value according to plan format spec."""
    kind = fmt_spec.get("kind")
    suffix = fmt_spec.get("suffix", "")
    show_plus = fmt_spec.get("show_plus", False)
    digits = fmt_spec.get("digits", None)

    if kind == "integer":
        val_int = int(value)
        return f"{val_int:,}{suffix}"
    elif kind == "date":
        return f"{value}{suffix}"
    elif kind == "number":
        num = float(value)
        if digits is not None:
            fmt_str = f"{{:{'+' if show_plus else ''}.{digits}f}}"
            formatted = fmt_str.format(num)
        else:
            fmt_str = f"{{:{'+' if show_plus else ''}}}"
            formatted = fmt_str.format(num)
        return f"{formatted}{suffix}"
    else:
        return f"{value}{suffix}"


def clean_text(text: str) -> str:
    """Strip markdown bold markers for clean graphic text rendering."""
    return text.replace("**", "")


def create_base_figure(title: str, alt: str, source_label: str):
    """Create a 1600x1000 figure with standard header and footer."""
    fig = plt.figure(figsize=(1600 / 150, 1000 / 150), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 1000)

    # White background canvas
    bg = patches.Rectangle((0, 0), 1600, 1000, facecolor='#FFFFFF', edgecolor='none')
    ax.add_patch(bg)

    # Header banner (dark slate navy)
    header_rect = patches.Rectangle((0, 870), 1600, 130, facecolor='#0F172A', edgecolor='none')
    ax.add_patch(header_rect)

    # Top accent bar
    top_bar = patches.Rectangle((0, 994), 1600, 6, facecolor='#2563EB', edgecolor='none')
    ax.add_patch(top_bar)

    # Header text
    ax.text(50, 940, title, fontsize=22, fontweight='bold', color='#FFFFFF', va='center')
    ax.text(50, 900, alt, fontsize=12, color='#94A3B8', va='center')

    # Footer separator line
    ax.plot([50, 1550], [50, 50], color='#E2E8F0', linewidth=1)

    # Footer text (strict reader-facing source name)
    footer_text = f"資料來源：{source_label}"
    ax.text(50, 25, footer_text, fontsize=11, color='#64748B', va='center')

    return fig, ax


def draw_rounded_card(ax, x, y, width, height, bg_color='#F8FAFC', border_color='#E2E8F0', radius=15):
    """Draw a rounded rectangle card container."""
    box = patches.FancyBboxPatch(
        (x, y), width, height,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=bg_color,
        edgecolor=border_color,
        linewidth=1.5
    )
    ax.add_patch(box)


def render_panel_1(panel_def: dict, results_data: dict, source_label: str):
    """Render Panel 1 — 1_concept.png (concept / professional)."""
    fig, ax = create_base_figure(
        title=panel_def["title"],
        alt=panel_def["alt"],
        source_label=source_label
    )

    blocks = panel_def["blocks"]
    text_block = [b for b in blocks if b["kind"] == "text"][0]
    metric_blocks = [b for b in blocks if b["kind"] == "metric"]

    # Left Column — Explanation Card (x: 50..980, y: 70..840)
    draw_rounded_card(ax, 50, 70, 930, 770, bg_color='#F8FAFC', border_color='#E2E8F0')

    # Section Heading
    ax.text(80, 800, text_block["heading"], fontsize=18, fontweight='bold', color='#0F172A', va='top')
    ax.plot([80, 950], [770, 770], color='#CBD5E1', linewidth=1)

    # Body Paragraphs
    curr_y = 745
    for p in text_block["body"]:
        clean_p = clean_text(p)
        wrapped_lines = textwrap.wrap(clean_p, width=32, break_long_words=True)
        for line in wrapped_lines:
            ax.text(80, curr_y, line, fontsize=12, color='#334155', va='top')
            curr_y -= 24
        curr_y -= 12

    # Right Column — 4 Metric Cards (x: 1010..1550, stacked vertically)
    card_colors = ['#0284C7', '#0F766E', '#D97706', '#4338CA']
    card_bg_colors = ['#F0F9FF', '#F0FDF4', '#FFFBEB', '#EEF2FF']
    card_border_colors = ['#BAE6FD', '#BBF7D0', '#FDE68A', '#C7D2FE']

    y_positions = [660, 470, 280, 90]
    for idx, mb in enumerate(metric_blocks):
        cy = y_positions[idx]
        val_raw = resolve_path(results_data, mb["value"]["path"])
        val_formatted = format_value(val_raw, mb["value"]["format"])

        draw_rounded_card(
            ax, 1010, cy, 540, 160,
            bg_color=card_bg_colors[idx],
            border_color=card_border_colors[idx]
        )

        label_clean = mb["label"].replace("・", " / ")
        ax.text(1040, cy + 125, label_clean, fontsize=13, color='#475569', va='top')
        ax.text(1040, cy + 45, val_formatted, fontsize=26, fontweight='bold', color=card_colors[idx], va='bottom')

    out_path = os.path.join(OUT_DIR, "1_concept.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Rendered {out_path}")


def render_panel_2(panel_def: dict, results_data: dict, source_label: str):
    """Render Panel 2 — 2_results.png (results / bento-grid)."""
    fig, ax = create_base_figure(
        title=panel_def["title"],
        alt=panel_def["alt"],
        source_label=source_label
    )

    blocks = panel_def["blocks"]
    text_block = [b for b in blocks if b["kind"] == "text"][0]
    metric_blocks = [b for b in blocks if b["kind"] == "metric"]

    # Bento Cell 1: Top Explanatory Banner (x: 50..1550, y: 640..840)
    draw_rounded_card(ax, 50, 640, 1500, 200, bg_color='#F8FAFC', border_color='#E2E8F0')
    ax.text(80, 815, text_block["heading"], fontsize=16, fontweight='bold', color='#0F172A', va='top')
    ax.plot([80, 1520], [788, 788], color='#E2E8F0', linewidth=1)

    curr_y = 770
    for p in text_block["body"]:
        clean_p = clean_text(p)
        wrapped_lines = textwrap.wrap(clean_p, width=54, break_long_words=True)
        for line in wrapped_lines:
            ax.text(80, curr_y, line, fontsize=11.5, color='#334155', va='top')
            curr_y -= 22
        curr_y -= 6

    # Process metrics:
    # m0: Narrow delta (+19.70 個基點)
    # m1: Narrow p (0.016)
    # m2: Wide delta (-10.05 個基點)
    # m3: Wide p (1.000)
    m0_val = format_value(resolve_path(results_data, metric_blocks[0]["value"]["path"]), metric_blocks[0]["value"]["format"])
    m1_val = format_value(resolve_path(results_data, metric_blocks[1]["value"]["path"]), metric_blocks[1]["value"]["format"])
    m2_val = format_value(resolve_path(results_data, metric_blocks[2]["value"]["path"]), metric_blocks[2]["value"]["format"])
    m3_val = format_value(resolve_path(results_data, metric_blocks[3]["value"]["path"]), metric_blocks[3]["value"]["format"])

    m0_label = metric_blocks[0]["label"].replace("・", " / ")
    m1_label = metric_blocks[1]["label"].replace("・", " / ")
    m2_label = metric_blocks[2]["label"].replace("・", " / ")
    m3_label = metric_blocks[3]["label"].replace("・", " / ")

    # Bento Cell 2: Narrow Group (Hero Highlight, x: 50..780, y: 90..610)
    draw_rounded_card(ax, 50, 90, 730, 520, bg_color='#EFF6FF', border_color='#93C5FD', radius=20)

    # Group Header Badge
    badge_box = patches.FancyBboxPatch((80, 545), 320, 38, boxstyle="round,pad=0,rounding_size=10", facecolor='#DBEAFE', edgecolor='none')
    ax.add_patch(badge_box)
    ax.text(95, 564, "原本價差最窄的一組 (Narrow)", fontsize=12, fontweight='bold', color='#1E40AF', va='center')

    # Metric 1: Delta
    ax.text(80, 515, m0_label, fontsize=13, color='#1E3A8A', va='top')
    ax.text(80, 480, m0_val, fontsize=30, fontweight='bold', color='#DC2626', va='top')

    ax.plot([80, 750], [405, 405], color='#BFDBFE', linewidth=1)

    # Metric 2: p-value
    ax.text(80, 385, m1_label, fontsize=13, color='#1E3A8A', va='top')
    ax.text(80, 350, f"p = {m1_val}", fontsize=26, fontweight='bold', color='#047857', va='top')

    # Significance tag box
    sig_box = patches.FancyBboxPatch((80, 115), 670, 155, boxstyle="round,pad=0,rounding_size=12", facecolor='#D1FAE5', edgecolor='#A7F3D0')
    ax.add_patch(sig_box)
    ax.text(100, 235, "統計檢定顯著 (Holm 校正後 p < 0.05)", fontsize=13, fontweight='bold', color='#065F46', va='top')
    ax.text(100, 195, "改制對價差最窄的股票造成顯著日內振幅擴大衝擊", fontsize=11.5, color='#047857', va='top')

    # Bento Cell 3: Wide Group (Comparison, x: 820..1550, y: 90..610)
    draw_rounded_card(ax, 820, 90, 730, 520, bg_color='#F8FAFC', border_color='#CBD5E1', radius=20)

    # Group Header Badge
    badge_box2 = patches.FancyBboxPatch((850, 545), 320, 38, boxstyle="round,pad=0,rounding_size=10", facecolor='#E2E8F0', edgecolor='none')
    ax.add_patch(badge_box2)
    ax.text(865, 564, "原本價差較寬的一組 (Wide)", fontsize=12, fontweight='bold', color='#475569', va='center')

    # Metric 1: Delta
    ax.text(850, 515, m2_label, fontsize=13, color='#475569', va='top')
    ax.text(850, 480, m2_val, fontsize=30, fontweight='bold', color='#64748B', va='top')

    ax.plot([850, 1520], [405, 405], color='#E2E8F0', linewidth=1)

    # Metric 2: p-value
    ax.text(850, 385, m3_label, fontsize=13, color='#475569', va='top')
    ax.text(850, 350, f"p = {m3_val}", fontsize=26, fontweight='bold', color='#64748B', va='top')

    # Insignificance tag box
    insig_box = patches.FancyBboxPatch((850, 115), 670, 155, boxstyle="round,pad=0,rounding_size=12", facecolor='#F1F5F9', edgecolor='#E2E8F0')
    ax.add_patch(insig_box)
    ax.text(870, 235, "統計檢定不顯著 (Holm 校正後 p = 1.000)", fontsize=13, fontweight='bold', color='#475569', va='top')
    ax.text(870, 195, "未測出統計差別，改制未對原本價差寬的股票產生顯著衝擊", fontsize=11.5, color='#64748B', va='top')

    out_path = os.path.join(OUT_DIR, "2_results.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Rendered {out_path}")


def render_panel_3(panel_def: dict, results_data: dict, source_label: str):
    """Render Panel 3 — 3_takeaway.png (takeaway / professional)."""
    fig, ax = create_base_figure(
        title=panel_def["title"],
        alt=panel_def["alt"],
        source_label=source_label
    )

    blocks = panel_def["blocks"]
    text_block = [b for b in blocks if b["kind"] == "text"][0]
    paragraphs = text_block["body"]

    # Container Card (x: 50..1550, y: 70..840)
    draw_rounded_card(ax, 50, 70, 1500, 770, bg_color='#F8FAFC', border_color='#E2E8F0', radius=20)

    # Main Header inside card
    ax.text(90, 800, text_block["heading"], fontsize=20, fontweight='bold', color='#0F172A', va='top')
    ax.plot([90, 1510], [775, 775], color='#CBD5E1', linewidth=1.5)

    # Section 1 Box (Paragraph 1)
    draw_rounded_card(ax, 90, 560, 1420, 190, bg_color='#FFFFFF', border_color='#E2E8F0')
    ax.text(120, 720, "1. 效應方向相反與互相抵消", fontsize=14, fontweight='bold', color='#1E293B', va='top')
    p1_lines = textwrap.wrap(clean_text(paragraphs[0]), width=50, break_long_words=True)
    curr_y = 680
    for line in p1_lines:
        ax.text(120, curr_y, line, fontsize=12, color='#334155', va='top')
        curr_y -= 24

    # Hero Takeaway Quote Card (Paragraph 2 - Amber Highlight)
    draw_rounded_card(ax, 90, 360, 1420, 170, bg_color='#FEF3C7', border_color='#F59E0B', radius=15)
    ax.text(120, 495, "【核心 Takeaway】", fontsize=13, fontweight='bold', color='#B45309', va='top')

    p2_text = clean_text(paragraphs[1])
    ax.text(120, 445, p2_text, fontsize=16, fontweight='bold', color='#78350F', va='top')

    # Section 2 Box (Paragraph 3)
    draw_rounded_card(ax, 90, 120, 1420, 210, bg_color='#FFFFFF', border_color='#E2E8F0')
    ax.text(120, 300, "2. 樣本精確度與統計力限制", fontsize=14, fontweight='bold', color='#1E293B', va='top')
    p3_lines = textwrap.wrap(clean_text(paragraphs[2]), width=50, break_long_words=True)
    curr_y = 260
    for line in p3_lines:
        ax.text(120, curr_y, line, fontsize=12, color='#334155', va='top')
        curr_y -= 24

    out_path = os.path.join(OUT_DIR, "3_takeaway.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Rendered {out_path}")


def main():
    # Ensure output directory exists
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1. Read evidence files strictly using absolute paths
    if not os.path.exists(PLAN_PATH):
        raise FileNotFoundError(f"Plan file missing: {PLAN_PATH}")
    if not os.path.exists(RESULTS_PATH):
        raise FileNotFoundError(f"Results file missing: {RESULTS_PATH}")

    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan_data = json.load(f)

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)

    # Extract strict source label from plan
    try:
        source_label = plan_data["evidence"]["results"]["label"]
    except KeyError as e:
        raise KeyError("plan.json missing evidence.results.label") from e

    panels = plan_data["panels"]

    for p_def in panels:
        p_name = p_def["name"]
        if p_name == "1_concept":
            render_panel_1(p_def, results_data, source_label)
        elif p_name == "2_results":
            render_panel_2(p_def, results_data, source_label)
        elif p_name == "3_takeaway":
            render_panel_3(p_def, results_data, source_label)
        else:
            raise ValueError(f"Unknown panel name: {p_name}")

    print("All panels rendered successfully.")


if __name__ == "__main__":
    main()
