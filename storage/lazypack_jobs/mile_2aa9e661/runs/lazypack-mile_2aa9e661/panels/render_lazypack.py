#!/usr/bin/env python3
"""Programmatic Lazypack Panel Renderer for mile_2aa9e661 (K1589).

Reads evidence JSON, plan JSON, and article markdown, then renders 3 PNG panels:
1_concept.png, 2_results.png, 3_takeaway.png
"""

import os
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# Absolute paths
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_2aa9e661/runs/lazypack-mile_2aa9e661/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/K1589/k1589_results.json"
ARTICLE_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_2aa9e661/runs/lazypack-mile_2aa9e661/panels/mile_2aa9e661_article.md"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_2aa9e661/runs/lazypack-mile_2aa9e661/panels"

plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False


def get_by_path(data, path):
    """Retrieve value from nested dict/list using dot notation. Raise KeyError if missing."""
    parts = path.split('.')
    cur = data
    for part in parts:
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Key '{part}' not found in evidence path '{path}'")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as err:
                raise KeyError(f"Index '{part}' invalid in evidence path '{path}'") from err
        else:
            raise KeyError(f"Cannot traverse key '{part}' in evidence path '{path}'")
    return cur


def format_metric_value(raw_val, fmt_spec):
    """Format raw value according to format specification in plan.json."""
    kind = fmt_spec.get("kind")
    if kind == "integer":
        suffix = fmt_spec.get("suffix", "")
        return f"{int(raw_val)}{suffix}"
    elif kind == "number":
        digits = fmt_spec.get("digits", 2)
        show_plus = fmt_spec.get("show_plus", False)
        fmt_str = f"+.{digits}f" if show_plus else f".{digits}f"
        suffix = fmt_spec.get("suffix", "")
        return f"{raw_val:{fmt_str}}{suffix}"
    else:
        return str(raw_val)


def wrap_cjk(text, width):
    """Wraps text (including CJK Chinese) to specified character width per line."""
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append("")
            continue
        cur = ""
        cur_w = 0.0
        for char in paragraph:
            char_w = 1.0 if ord(char) > 127 else 0.55
            if cur_w + char_w > width and cur:
                lines.append(cur)
                cur = char
                cur_w = char_w
            else:
                cur += char
                cur_w += char_w
        if cur:
            lines.append(cur)
    return "\n".join(lines)


def draw_card(ax, x, y, w, h, bg_color="#FFFFFF", border_color="#E2E8F0", rounding=0.2, lw=1.5):
    """Draw a rounded card rectangle on the axes."""
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={rounding}",
        fc=bg_color, ec=border_color, lw=lw,
        zorder=1
    )
    ax.add_patch(box)


def draw_footer(ax, source_label):
    """Draw the standard verbatim source footer across all panels."""
    ax.plot([0.6, 15.4], [0.8, 0.8], color="#CBD5E1", lw=1, zorder=2)
    footer_text = f"資料來源：{source_label}"
    ax.text(0.6, 0.45, footer_text, fontsize=11, color="#64748B", va="center", ha="left", zorder=3)


def render_panel_1(plan, results):
    """Panel 1: 1_concept.png (Style: professional)"""
    panel_data = plan["panels"][0]
    title = panel_data["title"]
    alt = panel_data["alt"]
    source_label = plan["evidence"]["results"]["label"]

    # Extract block data dynamically
    blocks = panel_data["blocks"]
    text_block_1 = blocks[0]  # 一句話直覺
    metric_1 = blocks[1]      # 納入事件數
    metric_2 = blocks[2]      # 登陸前波動估計窗口
    text_block_2 = blocks[3]  # 防偷看未來

    # Resolve metric values from results.json
    val_1 = format_metric_value(get_by_path(results, metric_1["value"]["path"]), metric_1["value"]["format"])
    val_2 = format_metric_value(get_by_path(results, metric_2["value"]["path"]), metric_2["value"]["format"])

    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis("off")

    # Header Card (Dark Slate)
    draw_card(ax, 0.6, 8.2, 14.8, 1.4, bg_color="#1E293B", border_color="#0F172A", rounding=0.25)
    ax.text(0.9, 9.15, title, fontsize=22, fontweight="bold", color="#FFFFFF", va="center", zorder=3)
    alt_wrapped = wrap_cjk(alt, width=70)
    ax.text(0.9, 8.55, alt_wrapped, fontsize=11.5, color="#94A3B8", va="center", zorder=3)

    # Block 1: "一句話直覺" (Left side top)
    draw_card(ax, 0.6, 4.4, 9.2, 3.5, bg_color="#FFFFFF", border_color="#E2E8F0", rounding=0.25)
    ax.text(0.9, 7.5, text_block_1["heading"], fontsize=16, fontweight="bold", color="#0F4C81", va="center", zorder=3)
    
    body_1_lines = []
    for bullet in text_block_1["body"]:
        wrapped_bullet = wrap_cjk(f"• {bullet}", width=40)
        body_1_lines.append(wrapped_bullet)
    body_1_text = "\n\n".join(body_1_lines)
    ax.text(0.9, 5.9, body_1_text, fontsize=12, color="#334155", va="center", multialignment="left", zorder=3)

    # Metric Card 1: "納入事件數" (Right top)
    draw_card(ax, 10.1, 6.2, 5.3, 1.7, bg_color="#EFF6FF", border_color="#BFDBFE", rounding=0.25)
    ax.text(10.4, 7.4, metric_1["label"], fontsize=13, fontweight="bold", color="#1E40AF", va="center", zorder=3)
    ax.text(10.4, 6.7, val_1, fontsize=30, fontweight="bold", color="#1E3A8A", va="center", zorder=3)

    # Metric Card 2: "登陸前波動估計窗口" (Right middle)
    draw_card(ax, 10.1, 4.4, 5.3, 1.7, bg_color="#F0FDF4", border_color="#BBF7D0", rounding=0.25)
    ax.text(10.4, 5.6, metric_2["label"], fontsize=13, fontweight="bold", color="#166534", va="center", zorder=3)
    ax.text(10.4, 4.9, val_2, fontsize=30, fontweight="bold", color="#14532D", va="center", zorder=3)

    # Block 2: "防偷看未來" (Bottom full width)
    draw_card(ax, 0.6, 1.1, 14.8, 3.0, bg_color="#FFFFFF", border_color="#E2E8F0", rounding=0.25)
    ax.text(0.9, 3.6, text_block_2["heading"], fontsize=16, fontweight="bold", color="#7C2D12", va="center", zorder=3)
    
    body_2_lines = []
    for bullet in text_block_2["body"]:
        wrapped_bullet = wrap_cjk(f"• {bullet}", width=68)
        body_2_lines.append(wrapped_bullet)
    body_2_text = "\n\n".join(body_2_lines)
    ax.text(0.9, 2.4, body_2_text, fontsize=12, color="#334155", va="center", multialignment="left", zorder=3)

    # Footer
    draw_footer(ax, source_label)

    output_path = os.path.join(OUT_DIR, "1_concept.png")
    plt.savefig(output_path, dpi=100, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def render_panel_2(plan, results):
    """Panel 2: 2_results.png (Style: bento-grid)"""
    panel_data = plan["panels"][1]
    title = panel_data["title"]
    alt = panel_data["alt"]
    source_label = plan["evidence"]["results"]["label"]

    blocks = panel_data["blocks"]
    
    # Resolve all 5 metrics dynamically from results.json
    val_0 = format_metric_value(get_by_path(results, blocks[0]["value"]["path"]), blocks[0]["value"]["format"])
    val_1 = format_metric_value(get_by_path(results, blocks[1]["value"]["path"]), blocks[1]["value"]["format"])
    val_2 = format_metric_value(get_by_path(results, blocks[2]["value"]["path"]), blocks[2]["value"]["format"])
    val_3 = format_metric_value(get_by_path(results, blocks[3]["value"]["path"]), blocks[3]["value"]["format"])
    val_4 = format_metric_value(get_by_path(results, blocks[4]["value"]["path"]), blocks[4]["value"]["format"])

    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis("off")

    # Header Banner
    draw_card(ax, 0.6, 8.2, 14.8, 1.4, bg_color="#0F172A", border_color="#020617", rounding=0.25)
    ax.text(0.9, 9.15, title, fontsize=22, fontweight="bold", color="#FFFFFF", va="center", zorder=3)
    alt_wrapped = wrap_cjk(alt, width=70)
    ax.text(0.9, 8.55, alt_wrapped, fontsize=11.5, color="#CBD5E1", va="center", zorder=3)

    # Bento Top Row (3 ACGL Cards)
    # Card 1: ACGL 斜率
    draw_card(ax, 0.6, 4.7, 4.7, 3.2, bg_color="#EEF2FF", border_color="#C7D2FE", rounding=0.25)
    ax.text(0.9, 7.4, blocks[0]["label"], fontsize=14, fontweight="bold", color="#3730A3", va="center", zorder=3)
    ax.text(0.9, 6.2, val_0, fontsize=42, fontweight="bold", color="#1E1B4B", va="center", zorder=3)
    desc_0 = wrap_cjk("巨災曝險最高再保商；每增強一級，登陸後波動估計上升幅度", width=22)
    ax.text(0.9, 5.2, desc_0, fontsize=11, color="#4338CA", va="center", zorder=3)

    # Card 2: ACGL t 值
    draw_card(ax, 5.65, 4.7, 4.7, 3.2, bg_color="#F0FDF4", border_color="#BBF7D0", rounding=0.25)
    ax.text(5.95, 7.4, blocks[1]["label"], fontsize=14, fontweight="bold", color="#166534", va="center", zorder=3)
    ax.text(5.95, 6.2, val_1, fontsize=42, fontweight="bold", color="#064E3B", va="center", zorder=3)
    desc_1 = wrap_cjk("訊號強度顯著高於一般統計雜訊門檻 (t > 2)", width=22)
    ax.text(5.95, 5.2, desc_1, fontsize=11, color="#15803D", va="center", zorder=3)

    # Card 3: ACGL p 值
    draw_card(ax, 10.7, 4.7, 4.7, 3.2, bg_color="#FEF2F2", border_color="#FECACA", rounding=0.25)
    ax.text(11.0, 7.4, blocks[2]["label"], fontsize=13.5, fontweight="bold", color="#991B1B", va="center", zorder=3)
    ax.text(11.0, 6.2, val_2, fontsize=42, fontweight="bold", color="#7F1D1D", va="center", zorder=3)
    desc_2 = wrap_cjk("Holm-Bonferroni 4 檔再保商多重檢定校正後仍達極顯著", width=22)
    ax.text(11.0, 5.2, desc_2, fontsize=11, color="#B91C1C", va="center", zorder=3)

    # Bento Bottom Row (2 KIE Control Cards)
    # Card 4: KIE 斜率
    draw_card(ax, 0.6, 1.1, 7.1, 3.3, bg_color="#FFFBEB", border_color="#FDE68A", rounding=0.25)
    ax.text(0.9, 3.9, blocks[3]["label"], fontsize=15, fontweight="bold", color="#92400E", va="center", zorder=3)
    ax.text(0.9, 2.7, val_3, fontsize=40, fontweight="bold", color="#78350F", va="center", zorder=3)
    desc_3 = wrap_cjk("對照組保險業 ETF 巨災曝險低得多，但每升一級斜率亦高達 +0.020", width=30)
    ax.text(0.9, 1.7, desc_3, fontsize=11.5, color="#B45309", va="center", zorder=3)

    # Card 5: KIE t 值
    draw_card(ax, 8.3, 1.1, 7.1, 3.3, bg_color="#FFFBEB", border_color="#FDE68A", rounding=0.25)
    ax.text(8.6, 3.9, blocks[4]["label"], fontsize=15, fontweight="bold", color="#92400E", va="center", zorder=3)
    ax.text(8.6, 2.7, val_4, fontsize=40, fontweight="bold", color="#78350F", va="center", zorder=3)
    desc_4 = wrap_cjk("對照組訊號強度 t = 2.31 亦過門檻，證實整體保險板塊皆有類似季節斜坡", width=30)
    ax.text(8.6, 1.7, desc_4, fontsize=11.5, color="#B45309", va="center", zorder=3)

    # Footer
    draw_footer(ax, source_label)

    output_path = os.path.join(OUT_DIR, "2_results.png")
    plt.savefig(output_path, dpi=100, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def render_panel_3(plan, results):
    """Panel 3: 3_takeaway.png (Style: scientific)"""
    panel_data = plan["panels"][2]
    title = panel_data["title"]
    alt = panel_data["alt"]
    source_label = plan["evidence"]["results"]["label"]

    blocks = panel_data["blocks"]
    
    val_0 = format_metric_value(get_by_path(results, blocks[0]["value"]["path"]), blocks[0]["value"]["format"])
    val_1 = format_metric_value(get_by_path(results, blocks[1]["value"]["path"]), blocks[1]["value"]["format"])
    val_2 = format_metric_value(get_by_path(results, blocks[2]["value"]["path"]), blocks[2]["value"]["format"])
    val_3 = format_metric_value(get_by_path(results, blocks[3]["value"]["path"]), blocks[3]["value"]["format"])
    text_block = blocks[4]

    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    fig.patch.set_facecolor("#FAFAFA")
    ax.set_facecolor("#FAFAFA")
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis("off")

    # Header Card
    draw_card(ax, 0.6, 8.2, 14.8, 1.4, bg_color="#0F172A", border_color="#020617", rounding=0.25)
    ax.text(0.9, 9.15, title, fontsize=22, fontweight="bold", color="#FFFFFF", va="center", zorder=3)
    alt_wrapped = wrap_cjk(alt, width=70)
    ax.text(0.9, 8.55, alt_wrapped, fontsize=11.5, color="#94A3B8", va="center", zorder=3)

    # Top Metric Strip (4 Cards)
    # Metric 1: 超額斜率
    draw_card(ax, 0.6, 5.3, 3.4, 2.6, bg_color="#FFFFFF", border_color="#CBD5E1", rounding=0.2)
    ax.text(0.8, 7.4, blocks[0]["label"], fontsize=12, fontweight="bold", color="#475569", va="center", zorder=3)
    ax.text(0.8, 6.4, val_0, fontsize=32, fontweight="bold", color="#0F172A", va="center", zorder=3)
    ax.text(0.8, 5.7, "再保險股減 KIE", fontsize=10.5, color="#64748B", va="center", zorder=3)

    # Metric 2: t 值
    draw_card(ax, 4.4, 5.3, 3.4, 2.6, bg_color="#FFFFFF", border_color="#CBD5E1", rounding=0.2)
    ax.text(4.6, 7.4, blocks[1]["label"], fontsize=12, fontweight="bold", color="#475569", va="center", zorder=3)
    ax.text(4.6, 6.4, val_1, fontsize=32, fontweight="bold", color="#0F172A", va="center", zorder=3)
    ax.text(4.6, 5.7, "訊號極弱 (t < 0.5)", fontsize=10.5, color="#64748B", va="center", zorder=3)

    # Metric 3: p 值
    draw_card(ax, 8.2, 5.3, 3.4, 2.6, bg_color="#FEF2F2", border_color="#FCA5A5", rounding=0.2)
    ax.text(8.4, 7.4, blocks[2]["label"], fontsize=12, fontweight="bold", color="#991B1B", va="center", zorder=3)
    ax.text(8.4, 6.4, val_2, fontsize=32, fontweight="bold", color="#7F1D1D", va="center", zorder=3)
    ax.text(8.4, 5.7, "無統計顯著差異", fontsize=10.5, color="#B91C1C", va="center", zorder=3)

    # Metric 4: 併池觀測數
    draw_card(ax, 12.0, 5.3, 3.4, 2.6, bg_color="#FFFFFF", border_color="#CBD5E1", rounding=0.2)
    ax.text(12.2, 7.4, blocks[3]["label"], fontsize=12, fontweight="bold", color="#475569", va="center", zorder=3)
    ax.text(12.2, 6.4, val_3, fontsize=32, fontweight="bold", color="#0F172A", va="center", zorder=3)
    ax.text(12.2, 5.7, "5 檔股票 × 42 事件", fontsize=10.5, color="#64748B", va="center", zorder=3)

    # Bottom Takeaway Card
    draw_card(ax, 0.6, 1.1, 14.8, 3.9, bg_color="#F0FDFA", border_color="#99F6E4", rounding=0.25)
    ax.text(0.9, 4.5, text_block["heading"], fontsize=16, fontweight="bold", color="#0D9488", va="center", zorder=3)

    body_lines = []
    for bullet in text_block["body"]:
        wrapped_bullet = wrap_cjk(f"• {bullet}", width=68)
        body_lines.append(wrapped_bullet)
    body_text = "\n\n".join(body_lines)
    ax.text(0.9, 2.8, body_text, fontsize=12, color="#134E4A", va="center", multialignment="left", zorder=3)

    # Footer
    draw_footer(ax, source_label)

    output_path = os.path.join(OUT_DIR, "3_takeaway.png")
    plt.savefig(output_path, dpi=100, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan = json.load(f)

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results = json.load(f)

    render_panel_1(plan, results)
    render_panel_2(plan, results)
    render_panel_3(plan, results)


if __name__ == "__main__":
    main()
