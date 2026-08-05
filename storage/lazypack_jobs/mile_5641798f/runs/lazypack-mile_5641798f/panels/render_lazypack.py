#!/usr/bin/env python3
"""
render_lazypack.py — VolPred lazypack panel renderer for mile_5641798f.

Reads evidence and plan JSON files and renders 4 PNG panels into:
/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_5641798f/runs/lazypack-mile_5641798f/panels
"""

import os
import json
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

# Absolute paths
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_5641798f/runs/lazypack-mile_5641798f/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1356/K1356_results.json"
ARTICLE_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_5641798f/runs/lazypack-mile_5641798f/panels/mile_5641798f_article.md"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_5641798f/runs/lazypack-mile_5641798f/panels"

# Font setup
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False


def resolve_path(data, path):
    parts = [p for p in path.strip("/").split("/") if p]
    cur = data
    for part in parts:
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Key '{part}' not found in dict at path '{path}'")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                idx = int(part)
                cur = cur[idx]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Index '{part}' invalid for list at path '{path}'") from exc
        else:
            raise KeyError(f"Cannot traverse part '{part}' on non-container at path '{path}'")
    return cur


def format_metric(val, fmt_spec):
    kind = fmt_spec.get("kind")
    if kind == "integer":
        suffix = fmt_spec.get("suffix", "")
        formatted_val = f"{int(round(val)):,}"
        return f"{formatted_val}{suffix}"
    elif kind == "percent":
        scale = fmt_spec.get("scale", 1.0)
        digits = fmt_spec.get("digits", 2)
        show_plus = fmt_spec.get("show_plus", False)
        scaled_val = val * scale
        sign = "+" if (show_plus and scaled_val > 0) else ""
        return f"{sign}{scaled_val:.{digits}f}%"
    elif kind == "number":
        digits = fmt_spec.get("digits", 2)
        return f"{val:.{digits}f}"
    else:
        return str(val)


def wrap_text(text, max_chars):
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        cur = ""
        for char in paragraph:
            if len(cur) >= max_chars:
                lines.append(cur)
                cur = char
            else:
                cur += char
        if cur:
            lines.append(cur)
    return "\n".join(lines)


def draw_card(ax, x, y, width, height, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=15, linewidth=1.5):
    patch = FancyBboxPatch(
        (x, y), width, height,
        boxstyle=f"round,pad=0,rounding_size={corner_radius}",
        facecolor=bg_color,
        edgecolor=border_color,
        linewidth=linewidth,
        zorder=1
    )
    ax.add_patch(patch)


def render_header(ax, title, alt_text):
    # Top banner background
    draw_card(ax, 60, 850, 1480, 110, bg_color="#1E293B", border_color="#0F172A", corner_radius=12)
    ax.text(90, 930, "VolPred 懶人包", fontsize=13, fontweight="bold", color="#38BDF8", zorder=3)
    ax.text(90, 890, title, fontsize=24, fontweight="bold", color="#FFFFFF", zorder=3)
    ax.text(90, 865, alt_text, fontsize=12, color="#94A3B8", zorder=3)


def render_footer(ax, source_label):
    ax.plot([60, 1540], [80, 80], color="#CBD5E1", linewidth=1.0, zorder=2)
    ax.text(60, 50, f"資料來源：{source_label}", fontsize=11, color="#64748B", zorder=3)


def create_base_figure():
    fig, ax = plt.subplots(figsize=(16, 10), dpi=150)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 1000)
    ax.axis("off")
    return fig, ax


def build_panel_question(plan, results_data, source_label, out_path):
    panel_info = plan["panels"][0]
    fig, ax = create_base_figure()
    render_header(ax, panel_info["title"], panel_info["alt"])
    
    # Left Card (Text block)
    draw_card(ax, 60, 120, 840, 690, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=16)
    
    text_block = panel_info["blocks"][0]
    ax.text(100, 750, text_block["heading"], fontsize=20, fontweight="bold", color="#0F172A", zorder=3)
    
    body_text = "\n\n".join([wrap_text(p, 28) for p in text_block["body"]])
    ax.text(100, 680, body_text, fontsize=15, color="#334155", linespacing=1.8, verticalalignment="top", zorder=3)
    
    # Extract Metrics from results_data using plan path definitions
    m1_spec = panel_info["blocks"][1]
    m1_val = resolve_path(results_data, m1_spec["value"]["path"])
    m1_str = format_metric(m1_val, m1_spec["value"]["format"])
    
    m2_spec = panel_info["blocks"][2]
    m2_val = resolve_path(results_data, m2_spec["value"]["path"])
    m2_str = format_metric(m2_val, m2_spec["value"]["format"])
    
    # Right Top Card (Metric 1)
    draw_card(ax, 930, 480, 610, 330, bg_color="#F0FDF4", border_color="#BBF7D0", corner_radius=16)
    ax.text(970, 750, m1_spec["label"], fontsize=15, fontweight="bold", color="#166534", zorder=3)
    ax.text(970, 620, m1_str, fontsize=42, fontweight="bold", color="#15803D", zorder=3)
    ax.text(970, 540, "跨 9 年全量數據嚴格檢定", fontsize=12, color="#166534", zorder=3)
    
    # Right Bottom Card (Metric 2)
    draw_card(ax, 930, 120, 610, 330, bg_color="#EFF6FF", border_color="#BFDBFE", corner_radius=16)
    ax.text(970, 390, m2_spec["label"], fontsize=15, fontweight="bold", color="#1E40AF", zorder=3)
    ax.text(970, 260, m2_str, fontsize=42, fontweight="bold", color="#1D4ED8", zorder=3)
    ax.text(970, 180, "包含原油期貨、原油 ETF 及能源類股 ETF", fontsize=12, color="#1E40AF", zorder=3)

    render_footer(ax, source_label)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def build_panel_method(plan, results_data, source_label, out_path):
    panel_info = plan["panels"][1]
    fig, ax = create_base_figure()
    render_header(ax, panel_info["title"], panel_info["alt"])
    
    # Top Left Card (Comparison Rule)
    draw_card(ax, 60, 420, 720, 390, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=16)
    t1 = panel_info["blocks"][0]
    ax.text(95, 760, t1["heading"], fontsize=18, fontweight="bold", color="#0F172A", zorder=3)
    b1_text = "\n\n".join([wrap_text(p, 24) for p in t1["body"]])
    ax.text(95, 700, b1_text, fontsize=14, color="#334155", linespacing=1.7, verticalalignment="top", zorder=3)
    
    # Top Right Card (Threshold Rule)
    draw_card(ax, 820, 420, 720, 390, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=16)
    t2 = panel_info["blocks"][2]
    ax.text(855, 760, t2["heading"], fontsize=18, fontweight="bold", color="#991B1B", zorder=3)
    b2_text = "\n\n".join([wrap_text(p, 24) for p in t2["body"]])
    ax.text(855, 700, b2_text, fontsize=14, color="#334155", linespacing=1.7, verticalalignment="top", zorder=3)
    
    # Metric (Middle Banner)
    m_spec = panel_info["blocks"][1]
    m_val = resolve_path(results_data, m_spec["value"]["path"])
    m_str = format_metric(m_val, m_spec["value"]["format"])
    
    draw_card(ax, 60, 120, 1480, 260, bg_color="#F8FAFC", border_color="#CBD5E1", corner_radius=16)
    ax.text(100, 310, m_spec["label"], fontsize=16, fontweight="bold", color="#475569", zorder=3)
    ax.text(100, 200, m_str, fontsize=48, fontweight="bold", color="#0F172A", zorder=3)
    ax.text(600, 230, "樣本外 (OOS) 滾動檢定天數\n無前瞻偏誤，無偷看未來資訊", fontsize=14, color="#64748B", linespacing=1.6, zorder=3)

    render_footer(ax, source_label)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def build_panel_result(plan, results_data, source_label, out_path):
    panel_info = plan["panels"][2]
    fig, ax = create_base_figure()
    render_header(ax, panel_info["title"], panel_info["alt"])
    
    # 2x2 Bento Box Grid
    # Card 1: Top Left (Best Improvement)
    m1_spec = panel_info["blocks"][0]
    m1_val = resolve_path(results_data, m1_spec["value"]["path"])
    m1_str = format_metric(m1_val, m1_spec["value"]["format"])
    draw_card(ax, 60, 480, 720, 330, bg_color="#F0FDF4", border_color="#BBF7D0", corner_radius=16)
    ax.text(95, 750, m1_spec["label"], fontsize=16, fontweight="bold", color="#166534", zorder=3)
    ax.text(95, 620, m1_str, fontsize=46, fontweight="bold", color="#15803D", zorder=3)
    ax.text(95, 540, "USO (原油 ETF) 誤差微幅改善", fontsize=12, color="#166534", zorder=3)
    
    # Card 2: Top Right (Worst Degradation)
    m2_spec = panel_info["blocks"][1]
    m2_val = resolve_path(results_data, m2_spec["value"]["path"])
    m2_str = format_metric(m2_val, m2_spec["value"]["format"])
    draw_card(ax, 820, 480, 720, 330, bg_color="#FFF1F2", border_color="#FECDD3", corner_radius=16)
    ax.text(855, 750, m2_spec["label"], fontsize=16, fontweight="bold", color="#9F1239", zorder=3)
    ax.text(855, 620, m2_str, fontsize=46, fontweight="bold", color="#E11D48", zorder=3)
    ax.text(855, 540, "XLE (能源股票 ETF) 加入新聞後誤差反而擴大", fontsize=12, color="#9F1239", zorder=3)
    
    # Card 3: Bottom Left (Positive Asset Count vs Threshold)
    m3_spec = panel_info["blocks"][2]
    m3_val = resolve_path(results_data, m3_spec["value"]["path"])
    m3_str = format_metric(m3_val, m3_spec["value"]["format"])
    draw_card(ax, 60, 120, 720, 330, bg_color="#FFFBEB", border_color="#FDE68A", corner_radius=16)
    ax.text(95, 390, m3_spec["label"], fontsize=16, fontweight="bold", color="#92400E", zorder=3)
    ax.text(95, 260, m3_str, fontsize=46, fontweight="bold", color="#D97706", zorder=3)
    ax.text(95, 180, "未達事先預設之門檻 (需至少 3 個標的)", fontsize=12, color="#92400E", zorder=3)
    
    # Card 4: Bottom Right (DM p-value)
    m4_spec = panel_info["blocks"][3]
    m4_val = resolve_path(results_data, m4_spec["value"]["path"])
    m4_str = format_metric(m4_val, m4_spec["value"]["format"])
    draw_card(ax, 820, 120, 720, 330, bg_color="#EFF6FF", border_color="#BFDBFE", corner_radius=16)
    ax.text(855, 390, m4_spec["label"], fontsize=16, fontweight="bold", color="#1E40AF", zorder=3)
    ax.text(855, 260, f"p = {m4_str}", fontsize=46, fontweight="bold", color="#2563EB", zorder=3)
    ax.text(855, 180, "Diebold-Mariano 檢定 p-value (未達 0.05 顯著水準)", fontsize=12, color="#1E40AF", zorder=3)

    render_footer(ax, source_label)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def build_panel_takeaway(plan, results_data, source_label, out_path):
    panel_info = plan["panels"][3]
    fig, ax = create_base_figure()
    render_header(ax, panel_info["title"], panel_info["alt"])
    
    # Left Top Card (Why empty)
    draw_card(ax, 60, 480, 800, 330, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=16)
    t1 = panel_info["blocks"][0]
    ax.text(95, 750, t1["heading"], fontsize=18, fontweight="bold", color="#0F172A", zorder=3)
    b1_text = "\n\n".join([wrap_text(p, 27) for p in t1["body"]])
    ax.text(95, 680, b1_text, fontsize=14, color="#334155", linespacing=1.7, verticalalignment="top", zorder=3)
    
    # Left Bottom Card (What not to say)
    draw_card(ax, 60, 120, 800, 330, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=16)
    t2 = panel_info["blocks"][2]
    ax.text(95, 390, t2["heading"], fontsize=18, fontweight="bold", color="#0F172A", zorder=3)
    b2_text = "\n\n".join([wrap_text(p, 27) for p in t2["body"]])
    ax.text(95, 320, b2_text, fontsize=14, color="#334155", linespacing=1.7, verticalalignment="top", zorder=3)
    
    # Right Side Card (Diagnostic Metric - ABS Shock)
    m_spec = panel_info["blocks"][1]
    m_val = resolve_path(results_data, m_spec["value"]["path"])
    m_str = format_metric(m_val, m_spec["value"]["format"])
    
    draw_card(ax, 890, 120, 650, 690, bg_color="#F8FAFC", border_color="#CBD5E1", corner_radius=16)
    ax.text(930, 750, m_spec["label"], fontsize=16, fontweight="bold", color="#475569", zorder=3)
    ax.text(930, 630, f"p = {m_str}", fontsize=54, fontweight="bold", color="#0F172A", zorder=3)
    
    diag_desc = wrap_text(
        "診斷模型 HAR_INV_NEWS_ABS 改用新聞熱度衝擊絕對值，顯著性 p = 0.28 依然遠高於 0.05 門檻。\n\n"
        "這證實單純對新聞數量做非線性轉換，依然無法創造超越波動率自我相關的獨立訊息。",
        21
    )
    ax.text(930, 540, diag_desc, fontsize=13, color="#475569", linespacing=1.8, verticalalignment="top", zorder=3)

    render_footer(ax, source_label)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Load JSON data
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan = json.load(f)
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)
        
    source_label = plan["evidence"]["results"]["label"]
    
    panels_builders = [
        ("panel_question.png", build_panel_question),
        ("panel_method.png", build_panel_method),
        ("panel_result.png", build_panel_result),
        ("panel_takeaway.png", build_panel_takeaway),
    ]
    
    for filename, builder in panels_builders:
        out_path = os.path.join(OUT_DIR, filename)
        builder(plan, results_data, source_label, out_path)
        print(f"Rendered: {out_path}")


if __name__ == "__main__":
    main()
