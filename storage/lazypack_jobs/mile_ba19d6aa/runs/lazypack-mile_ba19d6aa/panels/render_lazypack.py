#!/usr/bin/env python3
"""Lazypack renderer script for mile_ba19d6aa.

Reads data dynamically from evidence files (plan.json and member_qa_3e258ba2_results.json),
renders 3 panel PNG images (1_concept.png, 2_results.png, 3_takeaway.png),
and outputs them to the designated panels directory.
"""

import os
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Absolute file paths
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_ba19d6aa/runs/lazypack-mile_ba19d6aa/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/member_qa_3e258ba2/member_qa_3e258ba2_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_ba19d6aa/runs/lazypack-mile_ba19d6aa/panels"

# Configure matplotlib font settings
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False


def resolve_json_path(data: dict, path: str):
    """Retrieve value from nested dictionary using dot-separated path."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Missing field '{part}' in JSON path '{path}'")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (IndexError, ValueError) as exc:
                raise KeyError(f"Invalid list index '{part}' in path '{path}'") from exc
        else:
            raise KeyError(f"Cannot traverse non-dict object at '{part}' in path '{path}'")
    return cur


def format_value(val, fmt_spec: dict) -> str:
    """Format raw value according to plan format specification."""
    kind = fmt_spec.get("kind", "text")
    if kind == "text":
        return str(val)
    elif kind == "integer":
        suffix = fmt_spec.get("suffix", "")
        return f"{int(val):,}{suffix}"
    elif kind == "percent":
        digits = fmt_spec.get("digits", 1)
        suffix = fmt_spec.get("suffix", "%")
        return f"{val * 100:.{digits}f}{suffix}"
    else:
        return str(val)


def create_base_figure():
    """Create a 1600x1000 standard figure with canvas coordinates."""
    fig, ax = plt.subplots(figsize=(1600 / 150, 1000 / 150), dpi=150)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#F8FAFC")
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 1000)
    ax.axis("off")
    return fig, ax


def draw_header(ax, title: str, subtitle: str):
    """Draw common header across panels."""
    # Top accent line
    rect = patches.FancyBboxPatch(
        (80, 940), 60, 6,
        boxstyle="round,pad=0,rounding_size=3",
        facecolor="#2563EB", edgecolor="none"
    )
    ax.add_patch(rect)
    
    # Title & Subtitle - separate y positions with sufficient gap to prevent text bbox collision
    ax.text(80, 898, title, fontsize=20, fontweight="bold", color="#0F172A", va="center")
    ax.text(80, 848, subtitle, fontsize=12, color="#475569", va="center")
    
    # Separator
    ax.plot([80, 1520], [820, 820], color="#CBD5E1", linewidth=1.2)


def draw_footer(ax, source_label: str):
    """Draw common footer across panels."""
    ax.plot([80, 1520], [75, 75], color="#CBD5E1", linewidth=1.2)
    footer_text = f"資料來源：{source_label}"
    ax.text(80, 50, footer_text, fontsize=11, color="#64748B", va="center")


def render_panel_1(results_data: dict, source_label: str, out_path: str):
    """Render Panel 1 — 1_concept.png (Professional Style)."""
    fig, ax = create_base_figure()
    
    title = "回頭看歷史，目標達成過幾次"
    subtitle = "說明樣本期間、觀測月數與滾動三十年視窗數"
    draw_header(ax, title, subtitle)
    
    # Fetch metrics from results JSON
    period_val = resolve_json_path(results_data, "data.shiller.period")
    period_str = format_value(period_val, {"kind": "text"})
    
    n_months_val = resolve_json_path(results_data, "data.shiller.n_months")
    n_months_str = format_value(n_months_val, {"kind": "integer", "suffix": " 個月"})
    
    n_windows_val = resolve_json_path(results_data, "component2_rolling_30yr.shiller_nominal.n_windows")
    n_windows_str = format_value(n_windows_val, {"kind": "integer", "suffix": " 個"})
    
    # --- Top Block: Intuition Text Box ---
    top_box = patches.FancyBboxPatch(
        (80, 510), 1440, 270,
        boxstyle="round,pad=0,rounding_size=16",
        facecolor="#FFFFFF", edgecolor="#E2E8F0", linewidth=1.5
    )
    ax.add_patch(top_box)
    
    # Left vertical accent bar
    left_accent = patches.FancyBboxPatch(
        (80, 510), 10, 270,
        boxstyle="round,pad=0,rounding_size=4",
        facecolor="#2563EB", edgecolor="none"
    )
    ax.add_patch(left_accent)
    
    ax.text(115, 735, "一句話直覺", fontsize=16, fontweight="bold", color="#1E3A8A", va="center")
    ax.text(
        115, 680,
        "• 把美股一百多年的含息月資料，每一個月都當成起點，",
        fontsize=13, color="#334155", va="center"
    )
    ax.text(
        132, 650,
        "往後推三十年，看看有沒有做到目標報酬。",
        fontsize=13, color="#334155", va="center"
    )
    ax.text(
        115, 595,
        "• 同一組視窗再把物價上漲的影響扣掉，看達標比例會不會不一樣。",
        fontsize=13, color="#334155", va="center"
    )
    
    # --- Bottom Section: 3 Metric Cards ---
    card_width = 453
    gap = 40
    cards_data = [
        ("樣本期間", period_str, "Shiller 152 年長時序資料", "#0F172A", 13),
        ("觀測月數", n_months_str, "含息月報酬觀測點", "#2563EB", 24),
        ("滾動三十年視窗數", n_windows_str, "重疊 30 年視窗總數", "#0D9488", 24),
    ]
    
    for i, (label, val_str, desc, val_color, font_sz) in enumerate(cards_data):
        cx = 80 + i * (card_width + gap)
        cy = 110
        ch = 360
        
        card_bg = patches.FancyBboxPatch(
            (cx, cy), card_width, ch,
            boxstyle="round,pad=0,rounding_size=16",
            facecolor="#FFFFFF", edgecolor="#E2E8F0", linewidth=1.5
        )
        ax.add_patch(card_bg)
        
        # Label
        ax.text(cx + 30, cy + ch - 45, label, fontsize=14, fontweight="bold", color="#475569", va="center")
        
        # Divider line inside card
        ax.plot([cx + 30, cx + card_width - 30], [cy + ch - 75, cy + ch - 75], color="#F1F5F9", linewidth=1.2)
        
        # Value
        ax.text(cx + 30, cy + 195, val_str, fontsize=font_sz, fontweight="bold", color=val_color, va="center")
        
        # Sub-desc badge / text
        badge_box = patches.FancyBboxPatch(
            (cx + 30, cy + 40), card_width - 60, 45,
            boxstyle="round,pad=0,rounding_size=8",
            facecolor="#F8FAFC", edgecolor="#E2E8F0", linewidth=1.0
        )
        ax.add_patch(badge_box)
        ax.text(cx + 45, cy + 62, desc, fontsize=11, color="#64748B", va="center")

    draw_footer(ax, source_label)
    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def render_panel_2(results_data: dict, source_label: str, out_path: str):
    """Render Panel 2 — 2_results.png (Bento Grid Style)."""
    fig, ax = create_base_figure()
    
    title = "把通膨算進去，達標率少了將近一半"
    subtitle = "對照名目與實質達標率，以及史上最好最差的三十年"
    draw_header(ax, title, subtitle)
    
    # Fetch metrics
    nom_rate_val = resolve_json_path(results_data, "component2_rolling_30yr.shiller_nominal.fraction_ge_7pct")
    nom_rate_str = format_value(nom_rate_val, {"kind": "percent", "digits": 1})
    
    real_rate_val = resolve_json_path(results_data, "component2_rolling_30yr.shiller_real.fraction_ge_7pct")
    real_rate_str = format_value(real_rate_val, {"kind": "percent", "digits": 1})
    
    min_30yr_val = resolve_json_path(results_data, "component2_rolling_30yr.shiller_nominal.min")
    min_30yr_str = format_value(min_30yr_val, {"kind": "percent", "digits": 2})
    
    max_30yr_val = resolve_json_path(results_data, "component2_rolling_30yr.shiller_nominal.max")
    max_30yr_str = format_value(max_30yr_val, {"kind": "percent", "digits": 2})
    
    # --- Top Bento Row: 4 Metric Cards ---
    bento_width = 345
    bento_gap = 20
    bento_cards = [
        ("名目達標率", nom_rate_str, "未扣除通膨影響", "#F0FDF4", "#BBF7D0", "#15803D", "#166534"),
        ("扣通膨後達標率", real_rate_str, "實質年化達 7% 比例", "#FEF2F2", "#FECACA", "#B91C1C", "#991B1B"),
        ("史上最差 30 年", min_30yr_str, "最差滾動視窗年化", "#FFFBEB", "#FDE68A", "#B45309", "#92400E"),
        ("史上最好 30 年", max_30yr_str, "最佳滾動視窗年化", "#EFF6FF", "#BFDBFE", "#1D4ED8", "#1E40AF"),
    ]
    
    for i, (label, val_str, desc, bg_color, border_color, lbl_color, val_color) in enumerate(bento_cards):
        bx = 80 + i * (bento_width + bento_gap)
        by = 460
        bh = 320
        
        box = patches.FancyBboxPatch(
            (bx, by), bento_width, bh,
            boxstyle="round,pad=0,rounding_size=16",
            facecolor=bg_color, edgecolor=border_color, linewidth=1.5
        )
        ax.add_patch(box)
        
        ax.text(bx + 25, by + bh - 40, label, fontsize=13, fontweight="bold", color=lbl_color, va="center")
        ax.text(bx + 25, by + 175, val_str, fontsize=26, fontweight="bold", color=val_color, va="center")
        ax.text(bx + 25, by + 45, desc, fontsize=11, color="#64748B", va="center")

    # --- Bottom Bento Wide Block ---
    wide_box = patches.FancyBboxPatch(
        (80, 110), 1440, 310,
        boxstyle="round,pad=0,rounding_size=16",
        facecolor="#FFFFFF", edgecolor="#CBD5E1", linewidth=1.5
    )
    ax.add_patch(wide_box)
    
    # Sub-header bar
    sub_header = patches.FancyBboxPatch(
        (80, 350), 1440, 70,
        boxstyle="round,pad=0,rounding_size=14",
        facecolor="#F1F5F9", edgecolor="none"
    )
    ax.add_patch(sub_header)
    ax.text(115, 385, "怎麼讀這四個數字", fontsize=15, fontweight="bold", color="#0F172A", va="center")
    
    ax.text(
        115, 290,
        "• 同一批歷史區間，只是把通膨算進去，達標的比例就掉了將近一半。",
        fontsize=13, color="#334155", va="center"
    )
    ax.text(
        115, 230,
        "• 出生的年份是運氣，最好和最差的一段年化報酬差了一大截。",
        fontsize=13, color="#334155", va="center"
    )
    
    # Key Takeaway pill
    pill = patches.FancyBboxPatch(
        (115, 140), 1370, 45,
        boxstyle="round,pad=0,rounding_size=8",
        facecolor="#E0F2FE", edgecolor="#BAE6FD", linewidth=1.0
    )
    ax.add_patch(pill)
    ax.text(135, 162, "▶ 關鍵啟示：通膨與投入時點是三十年長期投資的最大變數", fontsize=12, fontweight="bold", color="#0369A1", va="center")

    draw_footer(ax, source_label)
    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def render_panel_3(results_data: dict, source_label: str, out_path: str):
    """Render Panel 3 — 3_takeaway.png (Scientific Poster Style)."""
    fig, ax = create_base_figure()
    
    title = "同樣放三十年，結果可能差十幾倍"
    subtitle = "呈現模擬路徑在偏差與偏好兩端的年化報酬與超過目標的比例"
    draw_header(ax, title, subtitle)
    
    # Fetch metrics
    p10_val = resolve_json_path(results_data, "component3_sequence_of_returns.block_bootstrap.lump_cagr_p10")
    p10_str = format_value(p10_val, {"kind": "percent", "digits": 2})
    
    p50_val = resolve_json_path(results_data, "component3_sequence_of_returns.block_bootstrap.lump_cagr_p50")
    p50_str = format_value(p50_val, {"kind": "percent", "digits": 2})
    
    p90_val = resolve_json_path(results_data, "component3_sequence_of_returns.block_bootstrap.lump_cagr_p90")
    p90_str = format_value(p90_val, {"kind": "percent", "digits": 2})
    
    beat_val = resolve_json_path(results_data, "component3_sequence_of_returns.block_bootstrap.lump_frac_beat_7pct")
    beat_str = format_value(beat_val, {"kind": "percent", "digits": 1})
    
    # --- Top Scientific Grid: 4 Metric Columns ---
    col_w = 345
    col_gap = 20
    cols_data = [
        ("表現偏差路徑年化", p10_str, "P10 分位數路徑", "#FFF1F2", "#FDA4AF", "#E11D48", "#BE123C"),
        ("中位數路徑年化", p50_str, "P50 中位數路徑", "#F0F9FF", "#BAE6FD", "#0284C7", "#0369A1"),
        ("表現偏好路徑年化", p90_str, "P90 分位數路徑", "#F0FDF4", "#A7F3D0", "#059669", "#047857"),
        ("路徑超過目標比例", beat_str, "達標 7% 目標比例", "#FAF5FF", "#E9D5FF", "#9333EA", "#7E22CE"),
    ]
    
    for i, (label, val_str, desc, bg_color, border_color, lbl_color, val_color) in enumerate(cols_data):
        cx = 80 + i * (col_w + col_gap)
        cy = 460
        ch = 320
        
        box = patches.FancyBboxPatch(
            (cx, cy), col_w, ch,
            boxstyle="round,pad=0,rounding_size=16",
            facecolor=bg_color, edgecolor=border_color, linewidth=1.5
        )
        ax.add_patch(box)
        
        ax.text(cx + 25, cy + ch - 40, label, fontsize=13, fontweight="bold", color=lbl_color, va="center")
        ax.text(cx + 25, cy + 175, val_str, fontsize=26, fontweight="bold", color=val_color, va="center")
        ax.text(cx + 25, cy + 45, desc, fontsize=11, color="#64748B", va="center")

    # --- Bottom Section: Scientific Takeaway Box ---
    takeaway_box = patches.FancyBboxPatch(
        (80, 110), 1440, 310,
        boxstyle="round,pad=0,rounding_size=16",
        facecolor="#FFFFFF", edgecolor="#0F172A", linewidth=2.0
    )
    ax.add_patch(takeaway_box)
    
    # Dark Header Banner
    header_banner = patches.FancyBboxPatch(
        (80, 350), 1440, 70,
        boxstyle="round,pad=0,rounding_size=14",
        facecolor="#0F172A", edgecolor="none"
    )
    ax.add_patch(header_banner)
    ax.text(115, 385, "能帶走的一句話", fontsize=15, fontweight="bold", color="#FFFFFF", va="center")
    
    ax.text(
        115, 290,
        "• 同一套市場、同樣的起手式，你實際走到的那條路徑，落點可能天差地遠。",
        fontsize=13, color="#1E293B", va="center"
    )
    ax.text(
        115, 230,
        "• 規劃退休金的時候，別只看那條最常見的路徑，要準備的是表現偏差的那一端。",
        fontsize=13, color="#1E293B", va="center"
    )
    
    # Method note at bottom of takeaway box
    ax.text(
        115, 150,
        "▶ 方法說明：基於 2,000 次 Block Bootstrap 序列重繪模擬 (24 個月區塊, 360 個月視窗)",
        fontsize=11, color="#64748B", va="center"
    )

    draw_footer(ax, source_label)
    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    # Ensure output directory exists
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Load evidence JSONs
    if not os.path.exists(PLAN_PATH):
        raise FileNotFoundError(f"Plan file not found at: {PLAN_PATH}")
    if not os.path.exists(RESULTS_PATH):
        raise FileNotFoundError(f"Results file not found at: {RESULTS_PATH}")
        
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan_data = json.load(f)
        
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)
        
    # Get strict source label from plan
    source_label = resolve_json_path(plan_data, "evidence.results.label")
    
    # Render all 3 panels
    p1_path = os.path.join(OUT_DIR, "1_concept.png")
    p2_path = os.path.join(OUT_DIR, "2_results.png")
    p3_path = os.path.join(OUT_DIR, "3_takeaway.png")
    
    render_panel_1(results_data, source_label, p1_path)
    render_panel_2(results_data, source_label, p2_path)
    render_panel_3(results_data, source_label, p3_path)
    
    print(f"Successfully generated panels in {OUT_DIR}:")
    print(f"  - {p1_path}")
    print(f"  - {p2_path}")
    print(f"  - {p3_path}")


if __name__ == "__main__":
    main()
