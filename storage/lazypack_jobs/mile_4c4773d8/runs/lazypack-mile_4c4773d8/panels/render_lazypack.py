#!/usr/bin/env python3
"""
LazyPack Panel Renderer for mile_4c4773d8.
Reads evidence JSON and plan JSON dynamically and renders 3 high-quality PNG panels.
"""

import json
import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# 1. Constants and Absolute Paths
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_4c4773d8/runs/lazypack-mile_4c4773d8/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1594/k1594_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_4c4773d8/runs/lazypack-mile_4c4773d8/panels"

# Font setting
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

def wrap_cjk(text: str, max_units: int) -> str:
    """
    Wraps text for CJK / mixed text.
    Full-width (CJK) characters count as 2 units, half-width (ASCII) as 1 unit.
    Preserves '•  ' prefix formatting for sub-lines.
    """
    prefix = ""
    content = text
    if text.startswith("•  "):
        prefix = "•  "
        content = text[3:]

    lines = []
    current_line = [prefix] if prefix else []
    current_units = 4 if prefix else 0

    for char in content:
        u = 2 if ord(char) > 127 else 1
        if current_units + u > max_units and current_line:
            lines.append("".join(current_line))
            indent = "   " if prefix else ""
            current_line = [indent, char] if indent else [char]
            current_units = (3 if prefix else 0) + u
        else:
            current_line.append(char)
            current_units += u
    if current_line:
        lines.append("".join(current_line))
    return "\n".join(lines)

def resolve_path(data: dict, path_str: str):
    """Traverse dict by slash-separated path. Raises KeyError/IndexError/ValueError if missing."""
    tokens = [t for t in path_str.split('/') if t]
    curr = data
    for t in tokens:
        if isinstance(curr, dict):
            if t not in curr:
                raise KeyError(f"Key '{t}' missing in path '{path_str}'")
            curr = curr[t]
        elif isinstance(curr, list):
            idx = int(t)
            curr = curr[idx]
        else:
            raise ValueError(f"Cannot traverse token '{t}' on non-container {type(curr)} in path '{path_str}'")
    return curr

def format_metric(val, fmt: dict) -> str:
    """Formats value based on format spec in plan.json."""
    kind = fmt.get("kind")
    suffix = fmt.get("suffix", "")
    if kind == "integer":
        return f"{int(round(float(val)))}{suffix}"
    elif kind == "number":
        digits = fmt.get("digits", 0)
        return f"{float(val):.{digits}f}{suffix}"
    elif kind == "percent":
        digits = fmt.get("digits", 1)
        return f"{float(val)*100:.{digits}f}%"
    else:
        return f"{val}{suffix}"

def load_data():
    if not os.path.exists(PLAN_PATH):
        raise FileNotFoundError(f"Plan file not found: {PLAN_PATH}")
    if not os.path.exists(RESULTS_PATH):
        raise FileNotFoundError(f"Results file not found: {RESULTS_PATH}")

    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan = json.load(f)
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results = json.load(f)
    return plan, results

def draw_card(ax, x, y, width, height, bg_color, border_color=None, border_width=1.5, corner_radius=12):
    patch = FancyBboxPatch(
        (x, y), width, height,
        boxstyle=f"round,pad=0,rounding_size={corner_radius}",
        facecolor=bg_color,
        edgecolor=border_color if border_color else "none",
        linewidth=border_width if border_color else 0,
        zorder=1
    )
    ax.add_patch(patch)

def draw_header(ax, title, alt_text, bg_color="#0F172A", title_color="#FFFFFF", alt_color="#94A3B8"):
    # Header box (y=860 to 1000)
    draw_card(ax, 0, 860, 1600, 140, bg_color, corner_radius=0)
    ax.text(60, 948, title, fontsize=22, fontweight="bold", color=title_color, va="center", ha="left", zorder=2)
    wrapped_alt = wrap_cjk(alt_text, max_units=110)
    lines = wrapped_alt.split('\n')
    if len(lines) == 1:
        ax.text(60, 895, lines[0], fontsize=11, color=alt_color, va="center", ha="left", zorder=2)
    else:
        ax.text(60, 908, lines[0], fontsize=11, color=alt_color, va="center", ha="left", zorder=2)
        ax.text(60, 880, lines[1], fontsize=11, color=alt_color, va="center", ha="left", zorder=2)

def draw_footer(ax, source_label, bg_color="#F8FAFC", text_color="#64748B"):
    # Footer box (y=0 to 60)
    draw_card(ax, 0, 0, 1600, 60, bg_color, border_color="#E2E8F0", border_width=1, corner_radius=0)
    ax.text(60, 30, f"資料來源：{source_label}", fontsize=13, color=text_color, va="center", ha="left", zorder=2)

def render_panel_1(panel_spec, results, source_label, out_path):
    """Panel 1 - Concept (Professional style)"""
    fig, ax = plt.subplots(figsize=(10.666667, 6.666667), dpi=150)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 1000)
    ax.axis("off")
    fig.patch.set_facecolor('#FFFFFF')

    # Draw Header & Footer
    draw_header(ax, panel_spec["title"], panel_spec["alt"], bg_color="#1E293B", title_color="#FFFFFF", alt_color="#CBD5E1")
    draw_footer(ax, source_label)

    blocks = panel_spec["blocks"]
    text_block1 = blocks[0]
    text_block2 = blocks[1]
    metric_block = blocks[2]

    # Left content card: x=60 to 980, y=90 to 830
    draw_card(ax, 60, 90, 920, 740, bg_color="#F8FAFC", border_color="#E2E8F0", border_width=1.5, corner_radius=16)

    # Section 1
    ax.text(90, 785, text_block1["heading"], fontsize=17, fontweight="bold", color="#0F172A", va="center", zorder=2)
    cur_y = 742
    for body_line in text_block1["body"]:
        wrapped = wrap_cjk(f"•  {body_line}", max_units=64)
        for wline in wrapped.split('\n'):
            ax.text(90, cur_y, wline, fontsize=12.5, color="#334155", va="center", zorder=2)
            cur_y -= 36

    # Divider line
    ax.plot([90, 950], [625, 625], color="#CBD5E1", linewidth=1.5, zorder=2)

    # Section 2
    ax.text(90, 575, text_block2["heading"], fontsize=17, fontweight="bold", color="#0F172A", va="center", zorder=2)
    cur_y = 532
    for body_line in text_block2["body"]:
        wrapped = wrap_cjk(f"•  {body_line}", max_units=64)
        for wline in wrapped.split('\n'):
            ax.text(90, cur_y, wline, fontsize=12.5, color="#334155", va="center", zorder=2)
            cur_y -= 36

    # Right metric card: x=1020 to 1540, y=90 to 830
    draw_card(ax, 1020, 90, 520, 740, bg_color="#EFF6FF", border_color="#BFDBFE", border_width=2, corner_radius=16)

    # Metric Extraction
    val_raw = resolve_path(results, metric_block["value"]["path"])
    val_str = format_metric(val_raw, metric_block["value"]["format"])

    ax.text(1280, 730, metric_block["label"], fontsize=17, fontweight="bold", color="#1E40AF", ha="center", va="center", zorder=2)
    ax.text(1280, 530, val_str, fontsize=52, fontweight="bold", color="#1D4ED8", ha="center", va="center", zorder=2)

    # Note Box
    draw_card(ax, 1050, 150, 460, 160, bg_color="#DBEAFE", border_color="#93C5FD", border_width=1, corner_radius=12)
    wrapped_note = wrap_cjk(metric_block["note"], max_units=30)
    lines = wrapped_note.split('\n')
    if len(lines) == 1:
        ax.text(1280, 230, lines[0], fontsize=13, color="#1E3A8A", ha="center", va="center", zorder=2)
    else:
        ax.text(1280, 245, lines[0], fontsize=13, color="#1E3A8A", ha="center", va="center", zorder=2)
        ax.text(1280, 215, lines[1], fontsize=13, color="#1E3A8A", ha="center", va="center", zorder=2)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

def render_panel_2(panel_spec, results, source_label, out_path):
    """Panel 2 - Results (Scientific style)"""
    fig, ax = plt.subplots(figsize=(10.666667, 6.666667), dpi=150)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 1000)
    ax.axis("off")
    fig.patch.set_facecolor('#FFFFFF')

    # Draw Header & Footer
    draw_header(ax, panel_spec["title"], panel_spec["alt"], bg_color="#0F2942", title_color="#FFFFFF", alt_color="#93C5FD")
    draw_footer(ax, source_label)

    blocks = panel_spec["blocks"]
    text_block = blocks[0]
    metric1 = blocks[1]
    metric2 = blocks[2]
    metric3 = blocks[3]

    # Upper text card: x=60 to 1540, y=550 to 830
    draw_card(ax, 60, 550, 1480, 280, bg_color="#F0F9FF", border_color="#BAE6FD", border_width=1.5, corner_radius=16)
    ax.text(90, 785, text_block["heading"], fontsize=18, fontweight="bold", color="#0369A1", va="center", zorder=2)
    cur_y = 740
    for line in text_block["body"]:
        wrapped = wrap_cjk(f"•  {line}", max_units=100)
        for wline in wrapped.split('\n'):
            ax.text(90, cur_y, wline, fontsize=13, color="#0F172A", va="center", zorder=2)
            cur_y -= 42

    # Lower 3 Metric cards side-by-side: y=90 to 520, height=430
    metrics = [
        (metric1, 60, "#EFF6FF", "#BFDBFE", "#1E40AF", "#1D4ED8"),
        (metric2, 570, "#FEF2F2", "#FECACA", "#991B1B", "#DC2626"),
        (metric3, 1080, "#F8FAFC", "#CBD5E1", "#334155", "#475569")
    ]

    for mspec, x_pos, bg, border, label_col, val_col in metrics:
        draw_card(ax, x_pos, 90, 460, 430, bg_color=bg, border_color=border, border_width=1.5, corner_radius=16)
        
        # Label wrapped
        wrapped_label = wrap_cjk(mspec["label"], max_units=24)
        lbl_lines = wrapped_label.split('\n')
        if len(lbl_lines) == 1:
            ax.text(x_pos + 230, 460, lbl_lines[0], fontsize=13.5, fontweight="bold", color=label_col, ha="center", va="center", zorder=2)
        else:
            ax.text(x_pos + 230, 475, lbl_lines[0], fontsize=13.5, fontweight="bold", color=label_col, ha="center", va="center", zorder=2)
            ax.text(x_pos + 230, 445, lbl_lines[1], fontsize=13.5, fontweight="bold", color=label_col, ha="center", va="center", zorder=2)

        # Value
        vraw = resolve_path(results, mspec["value"]["path"])
        vstr = format_metric(vraw, mspec["value"]["format"])
        ax.text(x_pos + 230, 335, vstr, fontsize=46, fontweight="bold", color=val_col, ha="center", va="center", zorder=2)

        # Note wrapped inside mini box
        draw_card(ax, x_pos + 20, 110, 420, 135, bg_color="#FFFFFF", border_color=border, border_width=1, corner_radius=10)
        wrapped_note = wrap_cjk(mspec["note"], max_units=24)
        note_lines = wrapped_note.split('\n')
        if len(note_lines) == 1:
            ax.text(x_pos + 230, 177, note_lines[0], fontsize=11, color="#475569", ha="center", va="center", zorder=2)
        else:
            ax.text(x_pos + 230, 192, note_lines[0], fontsize=11, color="#475569", ha="center", va="center", zorder=2)
            ax.text(x_pos + 230, 162, note_lines[1], fontsize=11, color="#475569", ha="center", va="center", zorder=2)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

def render_panel_3(panel_spec, results, source_label, out_path):
    """Panel 3 - Conclusion (Editorial style)"""
    fig, ax = plt.subplots(figsize=(10.666667, 6.666667), dpi=150)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 1000)
    ax.axis("off")
    fig.patch.set_facecolor('#FFFFFF')

    # Draw Header & Footer
    draw_header(ax, panel_spec["title"], panel_spec["alt"], bg_color="#27272A", title_color="#FFFFFF", alt_color="#E4E4E7")
    draw_footer(ax, source_label)

    blocks = panel_spec["blocks"]
    metric1 = blocks[0]
    metric2 = blocks[1]
    text_block1 = blocks[2]
    text_block2 = blocks[3]

    # Left Column (Metrics): x=60 to 770 (width=710)
    # Metric 1 Top: y=470 to 830 (height=360)
    draw_card(ax, 60, 470, 710, 360, bg_color="#EFF6FF", border_color="#BFDBFE", border_width=1.5, corner_radius=16)
    wrapped_lbl1 = wrap_cjk(metric1["label"], max_units=30)
    lbl_lines1 = wrapped_lbl1.split('\n')
    if len(lbl_lines1) == 1:
        ax.text(415, 785, lbl_lines1[0], fontsize=15, fontweight="bold", color="#1E40AF", ha="center", va="center", zorder=2)
    else:
        ax.text(415, 795, lbl_lines1[0], fontsize=15, fontweight="bold", color="#1E40AF", ha="center", va="center", zorder=2)
        ax.text(415, 770, lbl_lines1[1], fontsize=15, fontweight="bold", color="#1E40AF", ha="center", va="center", zorder=2)

    vraw1 = resolve_path(results, metric1["value"]["path"])
    vstr1 = format_metric(vraw1, metric1["value"]["format"])
    ax.text(415, 670, vstr1, fontsize=46, fontweight="bold", color="#1D4ED8", ha="center", va="center", zorder=2)

    wrapped_note1 = wrap_cjk(metric1["note"], max_units=50)
    note_lines1 = wrapped_note1.split('\n')
    if len(note_lines1) == 1:
        ax.text(415, 545, note_lines1[0], fontsize=12, color="#3B82F6", ha="center", va="center", zorder=2)
    else:
        ax.text(415, 560, note_lines1[0], fontsize=12, color="#3B82F6", ha="center", va="center", zorder=2)
        ax.text(415, 530, note_lines1[1], fontsize=12, color="#3B82F6", ha="center", va="center", zorder=2)

    # Metric 2 Bottom: y=90 to 440 (height=350)
    draw_card(ax, 60, 90, 710, 350, bg_color="#FEF3C7", border_color="#FDE68A", border_width=1.5, corner_radius=16)
    wrapped_lbl2 = wrap_cjk(metric2["label"], max_units=30)
    lbl_lines2 = wrapped_lbl2.split('\n')
    if len(lbl_lines2) == 1:
        ax.text(415, 395, lbl_lines2[0], fontsize=15, fontweight="bold", color="#92400E", ha="center", va="center", zorder=2)
    else:
        ax.text(415, 405, lbl_lines2[0], fontsize=15, fontweight="bold", color="#92400E", ha="center", va="center", zorder=2)
        ax.text(415, 380, lbl_lines2[1], fontsize=15, fontweight="bold", color="#92400E", ha="center", va="center", zorder=2)

    vraw2 = resolve_path(results, metric2["value"]["path"])
    vstr2 = format_metric(vraw2, metric2["value"]["format"])
    ax.text(415, 280, vstr2, fontsize=46, fontweight="bold", color="#D97706", ha="center", va="center", zorder=2)

    wrapped_note2 = wrap_cjk(metric2["note"], max_units=50)
    note_lines2 = wrapped_note2.split('\n')
    if len(note_lines2) == 1:
        ax.text(415, 155, note_lines2[0], fontsize=12, color="#B45309", ha="center", va="center", zorder=2)
    else:
        ax.text(415, 170, note_lines2[0], fontsize=12, color="#B45309", ha="center", va="center", zorder=2)
        ax.text(415, 140, note_lines2[1], fontsize=12, color="#B45309", ha="center", va="center", zorder=2)

    # Right Column (Text Cards): x=830 to 1540 (width=710)
    # Text Block 1 Top: y=470 to 830 (height=360)
    draw_card(ax, 830, 470, 710, 360, bg_color="#F8FAFC", border_color="#E2E8F0", border_width=1.5, corner_radius=16)
    ax.text(860, 785, text_block1["heading"], fontsize=17, fontweight="bold", color="#0F172A", va="center", zorder=2)
    cur_y = 740
    for line in text_block1["body"]:
        wrapped = wrap_cjk(f"•  {line}", max_units=48)
        for wline in wrapped.split('\n'):
            ax.text(860, cur_y, wline, fontsize=12.5, color="#334155", va="center", zorder=2)
            cur_y -= 32
        cur_y -= 14

    # Text Block 2 Bottom (Takeaway Box): y=90 to 440 (height=350)
    draw_card(ax, 830, 90, 710, 350, bg_color="#FFFBEB", border_color="#FCD34D", border_width=2, corner_radius=16)
    ax.text(860, 395, text_block2["heading"], fontsize=17, fontweight="bold", color="#B45309", va="center", zorder=2)
    cur_y = 350
    for line in text_block2["body"]:
        wrapped = wrap_cjk(f"•  {line}", max_units=48)
        for wline in wrapped.split('\n'):
            ax.text(860, cur_y, wline, fontsize=12.5, color="#78350F", va="center", zorder=2)
            cur_y -= 32
        cur_y -= 14

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    plan, results = load_data()

    # Get strict source label from plan.json
    source_label = plan.get("evidence", {}).get("k1594", {}).get("label", "四種畫線方法的樣本外回測完整結果 JSON")

    for panel in plan["panels"]:
        name = panel["name"]
        out_path = os.path.join(OUT_DIR, f"{name}.png")
        if name == "1_concept":
            render_panel_1(panel, results, source_label, out_path)
        elif name == "2_result":
            render_panel_2(panel, results, source_label, out_path)
        elif name == "3_conclusion":
            render_panel_3(panel, results, source_label, out_path)
        else:
            raise ValueError(f"Unknown panel name: {name}")

if __name__ == "__main__":
    main()
