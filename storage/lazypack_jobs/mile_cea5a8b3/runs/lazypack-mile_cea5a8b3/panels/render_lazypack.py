#!/usr/bin/env python3
"""
Lazypack PNG Renderer for mile_cea5a8b3 (K1696 Term-spread Volatility).
Reads data directly from K1696_results.json and plan.json, rendering 3 PNG panels.
"""
import os
import json
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Absolute paths to evidence package and output directory
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_cea5a8b3/runs/lazypack-mile_cea5a8b3/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/K1696/K1696_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_cea5a8b3/runs/lazypack-mile_cea5a8b3/panels"

plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False


def get_nested_val(data, path_str):
    if not path_str:
        raise ValueError("Empty path provided for nested value lookup.")
    parts = path_str.split('.')
    curr = data
    for p in parts:
        if isinstance(curr, dict):
            if p not in curr:
                raise KeyError(f"Key '{p}' from path '{path_str}' not found in evidence JSON.")
            curr = curr[p]
        elif isinstance(curr, list):
            try:
                idx = int(p)
                curr = curr[idx]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Index '{p}' from path '{path_str}' invalid for list: {e}")
        else:
            raise KeyError(f"Cannot traverse key '{p}' on non-container type {type(curr)}.")
    return curr


def format_value(val, fmt_spec):
    kind = fmt_spec.get("kind", "text")
    if kind == "integer":
        suffix = fmt_spec.get("suffix", "")
        return f"{int(round(val)):,}{suffix}"
    elif kind == "number":
        digits = fmt_spec.get("digits", 2)
        show_plus = fmt_spec.get("show_plus", False)
        if show_plus:
            return f"{val:+.{digits}f}"
        else:
            return f"{val:.{digits}f}"
    elif kind == "text":
        return str(val)
    else:
        return str(val)


def render_panel_1(panel_data, results_data, source_label, out_path):
    """
    Panel 1 — 1_concept.png (Style: professional)
    """
    title = panel_data["title"]
    alt = panel_data["alt"]
    blocks = panel_data["blocks"]

    text_block = None
    metric_blocks = []
    for b in blocks:
        if b["kind"] == "text":
            text_block = b
        elif b["kind"] == "metric":
            raw_val = get_nested_val(results_data, b["value"]["path"])
            fmt_val = format_value(raw_val, b["value"]["format"])
            metric_blocks.append({"label": b["label"], "formatted": fmt_val})

    fig = plt.figure(figsize=(10.667, 6.667), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)

    # Background
    ax.add_patch(patches.Rectangle((0, 0), 16, 10, facecolor='#F8FAFC', edgecolor='none'))

    # Header Box (Dark Slate)
    ax.add_patch(patches.Rectangle((0, 8.4), 16, 1.6, facecolor='#1E293B', edgecolor='none'))
    ax.text(0.8, 9.25, title, fontsize=21, fontweight='bold', color='#FFFFFF', va='center', ha='left')
    ax.text(0.8, 8.75, alt, fontsize=13, color='#94A3B8', va='center', ha='left')

    # Main Left Concept Card
    ax.add_patch(patches.Rectangle((0.8, 1.2), 9.0, 6.8, facecolor='#FFFFFF', edgecolor='#CBD5E1', linewidth=1.5))
    if text_block:
        heading = text_block.get("heading", "一句話直覺")
        body_lines = text_block.get("body", [])
        ax.text(1.2, 7.3, heading, fontsize=17, fontweight='bold', color='#0F172A', va='center', ha='left')
        ax.add_patch(patches.Rectangle((1.2, 6.95), 2.2, 0.05, facecolor='#0284C7', edgecolor='none'))

        y_cursor = 6.4
        for paragraph in body_lines:
            wrapped = textwrap.fill(paragraph, width=30)
            ax.text(1.2, y_cursor, wrapped, fontsize=12.5, color='#334155', va='top', ha='left', linespacing=1.5)
            n_lines = wrapped.count('\n') + 1
            y_cursor -= (n_lines * 0.42 + 0.35)

    # Right Metric Cards Stack
    card_y_starts = [5.8, 3.5, 1.2]
    for i, m in enumerate(metric_blocks):
        if i < len(card_y_starts):
            y_start = card_y_starts[i]
            ax.add_patch(patches.Rectangle((10.2, y_start), 5.0, 2.1, facecolor='#F0F9FF', edgecolor='#BAE6FD', linewidth=1.5))
            ax.text(10.6, y_start + 1.5, m["label"], fontsize=12, fontweight='bold', color='#0369A1', va='center', ha='left')
            ax.text(10.6, y_start + 0.7, m["formatted"], fontsize=24, fontweight='bold', color='#0C4A6E', va='center', ha='left')

    # Footer
    ax.text(0.8, 0.5, f"來源：{source_label}", fontsize=11, color='#64748B', va='center', ha='left')

    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def render_panel_2(panel_data, results_data, source_label, out_path):
    """
    Panel 2 — 2_results.png (Style: bento-grid)
    """
    title = panel_data["title"]
    alt = panel_data["alt"]
    blocks = panel_data["blocks"]

    metrics = []
    text_block = None
    for b in blocks:
        if b["kind"] == "metric":
            raw_val = get_nested_val(results_data, b["value"]["path"])
            fmt_val = format_value(raw_val, b["value"]["format"])
            metrics.append({"label": b["label"], "formatted": fmt_val})
        elif b["kind"] == "text":
            text_block = b

    fig = plt.figure(figsize=(10.667, 6.667), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)

    # Background
    ax.add_patch(patches.Rectangle((0, 0), 16, 10, facecolor='#F8FAFC', edgecolor='none'))

    # Header Box
    ax.add_patch(patches.Rectangle((0, 8.4), 16, 1.6, facecolor='#1E293B', edgecolor='none'))
    ax.text(0.8, 9.25, title, fontsize=21, fontweight='bold', color='#FFFFFF', va='center', ha='left')
    ax.text(0.8, 8.75, alt, fontsize=13, color='#94A3B8', va='center', ha='left')

    # Bento Grid Top: 4 Metric Cards across
    card_x_positions = [0.8, 4.5, 8.2, 11.9]
    card_widths = [3.4, 3.4, 3.4, 3.3]

    for i, m in enumerate(metrics[:4]):
        x_pos = card_x_positions[i]
        w_pos = card_widths[i]
        ax.add_patch(patches.Rectangle((x_pos, 4.8), w_pos, 3.2, facecolor='#FFFFFF', edgecolor='#CBD5E1', linewidth=1.5))
        ax.text(x_pos + 0.3, 7.3, m["label"], fontsize=12, fontweight='bold', color='#475569', va='center', ha='left')
        ax.text(x_pos + 0.3, 6.1, m["formatted"], fontsize=26, fontweight='bold', color='#1E293B', va='center', ha='left')
        ax.text(x_pos + 0.3, 5.3, "t 統計量 (未達顯著)", fontsize=10.5, color='#64748B', va='center', ha='left')

    # Bento Grid Bottom: Text Block Card
    ax.add_patch(patches.Rectangle((0.8, 1.2), 14.4, 3.2, facecolor='#FFFFFF', edgecolor='#CBD5E1', linewidth=1.5))
    if text_block:
        heading = text_block.get("heading", "怎麼讀這四個數字")
        body_lines = text_block.get("body", [])
        ax.text(1.2, 3.8, heading, fontsize=16, fontweight='bold', color='#0F172A', va='center', ha='left')
        ax.add_patch(patches.Rectangle((1.2, 3.55), 2.2, 0.04, facecolor='#6366F1', edgecolor='none'))

        y_cursor = 3.2
        for paragraph in body_lines:
            wrapped = textwrap.fill(paragraph, width=54)
            ax.text(1.2, y_cursor, wrapped, fontsize=12.5, color='#334155', va='top', ha='left', linespacing=1.4)
            n_lines = wrapped.count('\n') + 1
            y_cursor -= (n_lines * 0.38 + 0.25)

    # Footer
    ax.text(0.8, 0.5, f"來源：{source_label}", fontsize=11, color='#64748B', va='center', ha='left')

    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def render_panel_3(panel_data, results_data, source_label, out_path):
    """
    Panel 3 — 3_takeaway.png (Style: scientific)
    """
    title = panel_data["title"]
    alt = panel_data["alt"]
    blocks = panel_data["blocks"]

    metrics = []
    text_block = None
    for b in blocks:
        if b["kind"] == "metric":
            raw_val = get_nested_val(results_data, b["value"]["path"])
            fmt_val = format_value(raw_val, b["value"]["format"])
            metrics.append({"label": b["label"], "formatted": fmt_val})
        elif b["kind"] == "text":
            text_block = b

    fig = plt.figure(figsize=(10.667, 6.667), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)

    # Background
    ax.add_patch(patches.Rectangle((0, 0), 16, 10, facecolor='#F8FAFC', edgecolor='none'))

    # Header Box
    ax.add_patch(patches.Rectangle((0, 8.4), 16, 1.6, facecolor='#1E293B', edgecolor='none'))
    ax.text(0.8, 9.25, title, fontsize=21, fontweight='bold', color='#FFFFFF', va='center', ha='left')
    ax.text(0.8, 8.75, alt, fontsize=13, color='#94A3B8', va='center', ha='left')

    # Top Metrics Row
    card_x_positions = [0.8, 4.5, 8.2, 11.9]
    card_widths = [3.4, 3.4, 3.4, 3.3]

    for i, m in enumerate(metrics[:4]):
        x_pos = card_x_positions[i]
        w_pos = card_widths[i]

        if i == 0:
            # Highlight warning card
            ax.add_patch(patches.Rectangle((x_pos, 4.8), w_pos, 3.2, facecolor='#FEF2F2', edgecolor='#FCA5A5', linewidth=1.5))
            ax.text(x_pos + 0.3, 7.3, m["label"], fontsize=11.5, fontweight='bold', color='#991B1B', va='center', ha='left')
            ax.text(x_pos + 0.3, 6.1, m["formatted"], fontsize=26, fontweight='bold', color='#DC2626', va='center', ha='left')
            ax.text(x_pos + 0.3, 5.3, "顯著變差 (p < 0.001)", fontsize=10.5, fontweight='bold', color='#991B1B', va='center', ha='left')
        elif i == 3:
            # Verdict card
            ax.add_patch(patches.Rectangle((x_pos, 4.8), w_pos, 3.2, facecolor='#F1F5F9', edgecolor='#CBD5E1', linewidth=1.5))
            ax.text(x_pos + 0.3, 7.3, m["label"], fontsize=11.5, fontweight='bold', color='#334155', va='center', ha='left')
            ax.text(x_pos + 0.3, 6.1, m["formatted"], fontsize=26, fontweight='bold', color='#0F172A', va='center', ha='left')
            ax.text(x_pos + 0.3, 5.3, "無增量預測力", fontsize=10.5, color='#475569', va='center', ha='left')
        else:
            # Normal metric card
            ax.add_patch(patches.Rectangle((x_pos, 4.8), w_pos, 3.2, facecolor='#FFFFFF', edgecolor='#CBD5E1', linewidth=1.5))
            ax.text(x_pos + 0.3, 7.3, m["label"], fontsize=11, fontweight='bold', color='#475569', va='center', ha='left')
            ax.text(x_pos + 0.3, 6.1, m["formatted"], fontsize=24, fontweight='bold', color='#1E293B', va='center', ha='left')
            ax.text(x_pos + 0.3, 5.3, "QLIKE 損失分數", fontsize=10.5, color='#64748B', va='center', ha='left')

    # Bottom Text Block Card
    ax.add_patch(patches.Rectangle((0.8, 1.2), 14.4, 3.2, facecolor='#FFFFFF', edgecolor='#CBD5E1', linewidth=1.5))
    if text_block:
        heading = text_block.get("heading", "能帶走的一句話")
        body_lines = text_block.get("body", [])
        ax.text(1.2, 3.8, heading, fontsize=16, fontweight='bold', color='#0F172A', va='center', ha='left')
        ax.add_patch(patches.Rectangle((1.2, 3.55), 2.2, 0.04, facecolor='#DC2626', edgecolor='none'))

        y_cursor = 3.2
        for paragraph in body_lines:
            wrapped = textwrap.fill(paragraph, width=54)
            ax.text(1.2, y_cursor, wrapped, fontsize=12.5, color='#334155', va='top', ha='left', linespacing=1.4)
            n_lines = wrapped.count('\n') + 1
            y_cursor -= (n_lines * 0.38 + 0.25)

    # Footer
    ax.text(0.8, 0.5, f"來源：{source_label}", fontsize=11, color='#64748B', va='center', ha='left')

    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan_data = json.load(f)

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)

    source_label = plan_data.get("evidence", {}).get("results", {}).get("label", "K1696 期限利差波動增量預測力檢定結果")

    render_map = {
        "1_concept": render_panel_1,
        "2_results": render_panel_2,
        "3_takeaway": render_panel_3,
    }

    for panel in plan_data.get("panels", []):
        name = panel["name"]
        out_path = os.path.join(OUT_DIR, f"{name}.png")
        if name in render_map:
            render_map[name](panel, results_data, source_label, out_path)
        else:
            raise NotImplementedError(f"No renderer defined for panel '{name}'.")


if __name__ == "__main__":
    main()
