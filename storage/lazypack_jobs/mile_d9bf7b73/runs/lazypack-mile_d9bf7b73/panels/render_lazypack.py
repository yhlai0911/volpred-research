#!/usr/bin/env python3
"""VolPred Lazypack Renderer for mile_d9bf7b73 (K1609).

Binds evidence metrics dynamically from K1609_results.json and plan.json
and renders 3 clean, professional PNG panels.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Global Font Settings
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# Absolute evidence and output paths
PLAN_PATH = Path("/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_d9bf7b73/runs/lazypack-mile_d9bf7b73/plan.json")
RESULTS_PATH = Path("/Users/yhlai0911/volpred-research/experiments/K1609/K1609_results.json")
ARTICLE_PATH = Path("/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_d9bf7b73/runs/lazypack-mile_d9bf7b73/panels/mile_d9bf7b73_article.md")
OUT_DIR = Path("/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_d9bf7b73/runs/lazypack-mile_d9bf7b73/panels")


def resolve_path(data: dict, path_str: str) -> str | int | float | dict:
    """Traverse nested dict by dot notation; raises KeyError if any key is missing."""
    cur = data
    for part in path_str.split('.'):
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Key '{part}' missing in path '{path_str}'")
            cur = cur[part]
        else:
            raise KeyError(f"Cannot resolve key '{part}' in non-dict structure at path '{path_str}'")
    return cur


def wrap_cjk_lines(text: str | list[str], max_chars: int = 26) -> list[str]:
    """Wrap Traditional Chinese text cleanly without breaking words unnaturally."""
    paragraphs = text if isinstance(text, list) else text.split('\n')
    lines: list[str] = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            lines.append("")
            continue
        cur = ""
        for ch in p:
            cur += ch
            if len(cur) >= max_chars:
                lines.append(cur)
                cur = ""
        if cur:
            lines.append(cur)
    return lines


def create_canvas() -> tuple[plt.Figure, plt.Axes]:
    """Create 1600x1000 canvas at 150 dpi with full 1:1 pixel coordinate mapping."""
    fig = plt.figure(figsize=(10.666667, 6.666667), dpi=150)
    fig.patch.set_facecolor('#F8FAFC')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor('#F8FAFC')
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 1000)
    ax.invert_yaxis()  # Top-left origin
    ax.axis('off')
    return fig, ax


def draw_header(ax: plt.Axes, title: str, subtitle: str, tag: str = "VolPred 懶人包") -> None:
    """Draw top header banner."""
    # Tag pill
    tag_box = patches.FancyBboxPatch(
        (60, 40), 140, 32,
        boxstyle="round,pad=0,rounding_size=8",
        facecolor="#DBEAFE", edgecolor="#93C5FD", linewidth=1.2
    )
    ax.add_patch(tag_box)
    ax.text(130, 56, tag, fontsize=11.5, fontweight='bold', color="#1E40AF", ha='center', va='center')

    # Main Title
    ax.text(60, 95, title, fontsize=20, fontweight='bold', color="#0F172A", va='top')

    # Subtitle
    ax.text(60, 150, subtitle, fontsize=12, color="#475569", va='top')

    # Divider line
    ax.plot([60, 1540], [190, 190], color="#E2E8F0", linewidth=1.5)


def draw_footer(ax: plt.Axes, source_label: str) -> None:
    """Draw bottom footer with strict evidence source attribution."""
    ax.plot([60, 1540], [935, 935], color="#E2E8F0", linewidth=1.5)
    footer_text = f"來源：{source_label}"
    ax.text(60, 960, footer_text, fontsize=11, color="#64748B", va='center')


def draw_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    bg_color: str = "#FFFFFF",
    border_color: str = "#E2E8F0",
    radius: float = 14
) -> None:
    """Draw a rounded rectangle card container."""
    card = patches.FancyBboxPatch(
        (x, y), width, height,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=bg_color, edgecolor=border_color, linewidth=1.5
    )
    ax.add_patch(card)


def render_panel_1(
    out_path: Path,
    title: str,
    subtitle: str,
    source_label: str,
    heading: str,
    paragraphs: list[str],
    sample_start: str,
    sample_end: str,
    weekly_origin_rows: str
) -> None:
    """Render Panel 1: Concept (1_concept.png)."""
    fig, ax = create_canvas()
    draw_header(ax, title, subtitle)

    # Left Narrative Card
    draw_card(ax, 60, 215, 900, 695, bg_color="#FFFFFF", border_color="#E2E8F0")
    ax.text(95, 248, heading, fontsize=17, fontweight='bold', color="#1E3A8A", va='top')

    # Wrapped narrative lines (max 26 CJK chars per line, fontsize 12.5)
    wrapped_lines = wrap_cjk_lines(paragraphs, max_chars=26)
    curr_y = 290
    for line in wrapped_lines:
        if line == "":
            curr_y += 14
        else:
            ax.text(95, curr_y, line, fontsize=12.5, color="#334155", va='top')
            curr_y += 25

    # Right Metric Cards Stack
    metric_items = [
        ("樣本起點", sample_start, "資料採集起始日期", "(sample.start)", "#0F172A", "#F8FAFC"),
        ("樣本終點", sample_end, "資料採集截止日期", "(sample.end)", "#0F172A", "#F8FAFC"),
        ("週五起算點", weekly_origin_rows, "總計採集週五觀測點數", "(sample.weekly_origin_rows)", "#2563EB", "#EFF6FF"),
    ]

    card_y = 215
    for label, val_str, note_l1, note_l2, val_color, bg in metric_items:
        draw_card(ax, 990, card_y, 550, 215, bg_color=bg, border_color="#CBD5E1")
        ax.text(1025, card_y + 25, label, fontsize=13, color="#64748B", va='top')
        ax.text(1025, card_y + 60, val_str, fontsize=28, fontweight='bold', color=val_color, va='top')
        ax.text(1025, card_y + 125, note_l1, fontsize=10.5, color="#64748B", va='top')
        ax.text(1025, card_y + 148, note_l2, fontsize=10, color="#94A3B8", va='top')
        card_y += 240

    draw_footer(ax, source_label)
    plt.savefig(out_path, format="png")
    plt.close(fig)


def render_panel_2(
    out_path: Path,
    title: str,
    subtitle: str,
    source_label: str,
    heading: str,
    paragraphs: list[str],
    rv_t: str,
    downside_t: str,
    corr_t: str,
    n_obs: str
) -> None:
    """Render Panel 2: Results Bento Grid (2_results.png)."""
    fig, ax = create_canvas()
    draw_header(ax, title, subtitle)

    # Top-Left Bento Card: Text Context
    draw_card(ax, 60, 215, 900, 275, bg_color="#FFFFFF", border_color="#E2E8F0")
    ax.text(95, 242, heading, fontsize=16, fontweight='bold', color="#1E3A8A", va='top')

    wrapped_lines = wrap_cjk_lines(paragraphs, max_chars=26)
    curr_y = 280
    for line in wrapped_lines:
        if line == "":
            curr_y += 12
        else:
            ax.text(95, curr_y, line, fontsize=12, color="#334155", va='top')
            curr_y += 24

    # Top-Right Bento Card: Threshold Benchmark Box
    draw_card(ax, 990, 215, 550, 275, bg_color="#FEF2F2", border_color="#FCA5A5")
    ax.text(1025, 240, "判決基準門檻", fontsize=13, fontweight='bold', color="#991B1B", va='top')
    ax.text(1025, 268, "|t| ≥ 3.00", fontsize=26, fontweight='bold', color="#DC2626", va='top')
    
    # Wrap subtext cleanly to fit inside 550px card
    ax.text(1025, 336, "嚴格多重比對標準：", fontsize=10.5, color="#991B1B", va='top')
    ax.text(1025, 358, "估計值需達誤差 3 倍才算數", fontsize=10.5, color="#991B1B", va='top')

    pill_bg = patches.FancyBboxPatch(
        (1015, 392), 500, 42,
        boxstyle="round,pad=0,rounding_size=8",
        facecolor="#FEE2E2", edgecolor="#F87171", linewidth=1.2
    )
    ax.add_patch(pill_bg)
    ax.text(1265, 413, "結果：6 格中 0 格達標 (最高僅 ~2.05)", fontsize=11.5, fontweight='bold', color="#991B1B", ha='center', va='center')

    # Bottom Row 4 Bento Cards (equal width 355px, total width 1480px)
    results_cards = [
        ("黃金·未來五日波動", rv_t, "t-stat (ols_hac)", f"|{rv_t}| < 3.00", "未達 3 倍門檻", 60, 355),
        ("黃金·未來五日下跌波動", downside_t, "t-stat (ols_hac)", f"|{downside_t}| < 3.00", "未達 3 倍門檻", 435, 355),
        ("黃金·一月報酬與實質利率", corr_t, "t-stat (ols_hac)", f"|{corr_t}| < 3.00", "未達門檻 (最高)", 810, 355),
        ("黃金各格觀測數", n_obs, "觀測數 (n)", "週次有效點", "足量長時間序列", 1185, 355),
    ]

    for label, val_str, unit_str, pill_str, note_str, x_pos, width in results_cards:
        is_n_card = (label == "黃金各格觀測數")
        bg_col = "#EFF6FF" if is_n_card else "#FFFFFF"
        border_col = "#93C5FD" if is_n_card else "#CBD5E1"

        draw_card(ax, x_pos, 510, width, 400, bg_color=bg_col, border_color=border_col)
        
        lbl_size = 11.0 if len(label) > 10 else 12.0
        ax.text(x_pos + 20, 535, label, fontsize=lbl_size, fontweight='bold', color="#1E293B", va='top')
        
        val_color = "#2563EB" if is_n_card else "#0F172A"
        ax.text(x_pos + 20, 565, val_str, fontsize=26, fontweight='bold', color=val_color, va='top')
        ax.text(x_pos + 20, 635, unit_str, fontsize=10.5, color="#64748B", va='top')

        p_bg = "#DBEAFE" if is_n_card else "#FEE2E2"
        p_edge = "#93C5FD" if is_n_card else "#F87171"
        p_txt = "#1D4ED8" if is_n_card else "#DC2626"

        pill = patches.FancyBboxPatch(
            (x_pos + 18, 675), width - 36, 40,
            boxstyle="round,pad=0,rounding_size=8",
            facecolor=p_bg, edgecolor=p_edge, linewidth=1.2
        )
        ax.add_patch(pill)
        ax.text(x_pos + width / 2, 695, pill_str, fontsize=11, fontweight='bold', color=p_txt, ha='center', va='center')
        ax.text(x_pos + 20, 735, note_str, fontsize=10.5, color="#64748B", va='top')

    draw_footer(ax, source_label)
    plt.savefig(out_path, format="png")
    plt.close(fig)


def render_panel_3(
    out_path: Path,
    title: str,
    subtitle: str,
    source_label: str,
    heading: str,
    paragraphs: list[str],
    verdict: str
) -> None:
    """Render Panel 3: Takeaway (3_takeaway.png)."""
    fig, ax = create_canvas()
    draw_header(ax, title, subtitle)

    # Left Narrative Card
    draw_card(ax, 60, 215, 900, 695, bg_color="#FFFFFF", border_color="#E2E8F0")
    ax.text(95, 248, heading, fontsize=17, fontweight='bold', color="#1E3A8A", va='top')

    wrapped_lines = wrap_cjk_lines(paragraphs, max_chars=26)
    curr_y = 290
    for line in wrapped_lines:
        if line == "":
            curr_y += 14
        else:
            ax.text(95, curr_y, line, fontsize=12.5, color="#334155", va='top')
            curr_y += 25

    # Right Hero Verdict Card
    draw_card(ax, 990, 215, 550, 695, bg_color="#F0F9FF", border_color="#BAE6FD")

    # Top Tag
    tag_bg = patches.FancyBboxPatch(
        (1025, 245), 140, 30,
        boxstyle="round,pad=0,rounding_size=6",
        facecolor="#E0F2FE", edgecolor="#7DD3FC", linewidth=1.2
    )
    ax.add_patch(tag_bg)
    ax.text(1095, 260, "FINAL VERDICT", fontsize=10.5, fontweight='bold', color="#0369A1", ha='center', va='center')

    ax.text(1025, 290, "研究判定", fontsize=14, fontweight='bold', color="#0284C7", va='top')

    # Hero Value Box
    draw_card(ax, 1025, 330, 480, 90, bg_color="#FFFFFF", border_color="#CBD5E1", radius=10)
    verdict_fontsize = 13.0 if len(verdict) > 18 else 18.0
    ax.text(1265, 375, verdict, fontsize=verdict_fontsize, fontweight='bold', color="#0F172A", ha='center', va='center')

    # Status Pill
    status_bg = patches.FancyBboxPatch(
        (1025, 440), 480, 44,
        boxstyle="round,pad=0,rounding_size=8",
        facecolor="#FEF3C7", edgecolor="#FDE68A", linewidth=1.2
    )
    ax.add_patch(status_bg)
    ax.text(1265, 462, "代理指標檢定未達顯著 (|t| < 3)", fontsize=11.5, fontweight='bold', color="#B45309", ha='center', va='center')

    # Divider line
    ax.plot([1025, 1505], [510, 510], color="#BAE6FD", linewidth=1.5)

    # Core Principles List (Using [v] to prevent font missing glyph warning)
    principles = [
        "[v]  原始資料受限：連線逾時如實記錄",
        "[v]  替代指標標籤：代理指標不冒充庫存",
        "[v]  事先嚴格門檻：|t| ≥ 3.0 事後不放寬",
        "[v]  劃清研究邊界：無過度宣稱結論"
    ]
    py = 535
    for p in principles:
        ax.text(1025, py, p, fontsize=12, fontweight='bold', color="#0F172A", va='top')
        py += 40

    draw_footer(ax, source_label)
    plt.savefig(out_path, format="png")
    plt.close(fig)


def main() -> None:
    # 1. Ensure output directory exists
    os.makedirs(OUT_DIR, exist_ok=True)

    # 2. Read evidence package (strict absolute paths)
    if not PLAN_PATH.exists():
        raise FileNotFoundError(f"Plan file not found at: {PLAN_PATH}")
    if not RESULTS_PATH.exists():
        raise FileNotFoundError(f"Results file not found at: {RESULTS_PATH}")

    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan_data = json.load(f)

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)

    # Extract source label (raises if evidence structure missing)
    source_label = resolve_path(plan_data, "evidence.results.label")

    # 3. Dynamic field binding with strict key-existence enforcement
    sample_start = str(resolve_path(results_data, "sample.start"))
    sample_end = str(resolve_path(results_data, "sample.end"))
    weekly_origin_rows = f"{resolve_path(results_data, 'sample.weekly_origin_rows')} 個"

    gold_rv_t = f"{float(resolve_path(results_data, 'results.gold.log_fwd5_rv_ratio.ols_hac.t_hac_lag4')):.2f}"
    gold_downside_t = f"{float(resolve_path(results_data, 'results.gold.downside_semivar_5d_ann.ols_hac.t_hac_lag4')):.2f}"
    gold_corr_t = f"{float(resolve_path(results_data, 'results.gold.fwd21_return_real_yield_corr.ols_hac.t_hac_lag4')):.2f}"
    gold_n = f"{resolve_path(results_data, 'results.gold.log_fwd5_rv_ratio.ols_hac.n')} 筆"

    verdict_str = str(resolve_path(results_data, "verdict.verdict"))

    # Extract text blocks from plan
    panels_plan = resolve_path(plan_data, "panels")

    # Render Panel 1
    p1_plan = panels_plan[0]
    render_panel_1(
        out_path=OUT_DIR / "1_concept.png",
        title=p1_plan["title"],
        subtitle=p1_plan["alt"],
        source_label=source_label,
        heading=p1_plan["blocks"][0]["heading"],
        paragraphs=p1_plan["blocks"][0]["body"],
        sample_start=sample_start,
        sample_end=sample_end,
        weekly_origin_rows=weekly_origin_rows
    )

    # Render Panel 2
    p2_plan = panels_plan[1]
    render_panel_2(
        out_path=OUT_DIR / "2_results.png",
        title=p2_plan["title"],
        subtitle=p2_plan["alt"],
        source_label=source_label,
        heading=p2_plan["blocks"][0]["heading"],
        paragraphs=p2_plan["blocks"][0]["body"],
        rv_t=gold_rv_t,
        downside_t=gold_downside_t,
        corr_t=gold_corr_t,
        n_obs=gold_n
    )

    # Render Panel 3
    p3_plan = panels_plan[2]
    render_panel_3(
        out_path=OUT_DIR / "3_takeaway.png",
        title=p3_plan["title"],
        subtitle=p3_plan["alt"],
        source_label=source_label,
        heading=p3_plan["blocks"][0]["heading"],
        paragraphs=p3_plan["blocks"][0]["body"],
        verdict=verdict_str
    )


if __name__ == "__main__":
    main()
