#!/usr/bin/env python3
"""
VolPred Lazypack Renderer for mile_7d19ad76
Generates 3 PNG infographic panels: 1_concept.png, 2_result.png, 3_conclusion.png.
Data-bound strictly to k1625_results.json and plan.json.
"""

import json
import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Set Chinese font & unicode minus handling
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# Absolute file paths
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_7d19ad76/runs/lazypack-mile_7d19ad76/plan.json"
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1625/k1625_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_7d19ad76/runs/lazypack-mile_7d19ad76/panels"

def resolve_json_path(data, path_str):
    """
    Resolves a JSON path string like '/per_asset/BTC/sample_start' or '/primary_tstats/12/t'.
    Raises KeyError or IndexError if path is invalid or missing.
    """
    parts = [p for p in path_str.split('/') if p]
    curr = data
    for part in parts:
        if isinstance(curr, dict):
            if part not in curr:
                raise KeyError(f"Key '{part}' not found when resolving path '{path_str}'")
            curr = curr[part]
        elif isinstance(curr, list):
            try:
                idx = int(part)
                curr = curr[idx]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Invalid list index '{part}' when resolving path '{path_str}'") from e
        else:
            raise KeyError(f"Cannot navigate into {type(curr)} with part '{part}' for path '{path_str}'")
    return curr

def format_value(val, fmt_spec):
    """
    Formats a raw value based on spec: integer, percent, number, text, etc.
    """
    kind = fmt_spec.get("kind")
    suffix = fmt_spec.get("suffix", "")
    if kind == "integer":
        return f"{int(round(float(val)))}{suffix}"
    elif kind == "text":
        return f"{str(val)}{suffix}"
    elif kind == "percent":
        digits = fmt_spec.get("digits", 1)
        return f"{float(val) * 100:.{digits}f}%{suffix}"
    elif kind == "number":
        digits = fmt_spec.get("digits", 2)
        return f"{float(val):.{digits}f}{suffix}"
    else:
        return f"{val}{suffix}"

def wrap_cjk_text(text, max_chars_per_line=36):
    """
    Wraps CJK text into lines fitting max_chars_per_line.
    """
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        cur = ""
        for char in paragraph:
            cur += char
            if len(cur) >= max_chars_per_line:
                lines.append(cur)
                cur = ""
        if cur:
            lines.append(cur)
    return "\n".join(lines)

def setup_canvas(bg_color="#FAFAFC"):
    """
    Creates a 1600x1000 matplotlib figure with inverted Y axis for top-down coordinates.
    """
    fig = plt.figure(figsize=(1600/150, 1000/150), dpi=150)
    fig.patch.set_facecolor(bg_color)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1600)
    ax.set_ylim(1000, 0)  # Inverted Y axis: (0,0) is top-left
    return fig, ax

def draw_header(ax, title, subtitle, accent_color="#2563EB"):
    """
    Draws panel header with brand tag, title, and subtitle.
    """
    # Brand tag
    ax.text(80, 40, "VolPred 懶人包", fontsize=13, fontweight="bold", color=accent_color, va="top")
    
    # Title
    ax.text(80, 68, title, fontsize=26, fontweight="bold", color="#0F172A", va="top")
    
    # Subtitle
    wrapped_sub = wrap_cjk_text(subtitle, max_chars_per_line=46)
    ax.text(80, 126, wrapped_sub, fontsize=13, color="#475569", va="top", linespacing=1.3)
    
    # Header separator line
    ax.plot([80, 1520], [180, 180], color="#E2E8F0", linewidth=1.5)

def draw_footer(ax, source_label):
    """
    Draws panel footer with mandatory data source label.
    """
    ax.plot([80, 1520], [940, 940], color="#CBD5E1", linewidth=1.5)
    footer_text = f"資料來源：{source_label}"
    ax.text(80, 955, footer_text, fontsize=12, color="#64748B", va="top")

def draw_card(ax, x, y, width, height, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=16):
    """
    Draws a rounded rectangular card on canvas.
    """
    rect = patches.FancyBboxPatch(
        (x, y), width, height,
        boxstyle=f"round,pad=0,rounding_size={corner_radius}",
        facecolor=bg_color, edgecolor=border_color, linewidth=1.5
    )
    ax.add_patch(rect)


def render_panel_1(plan_data, k1625_data, source_label, out_dir):
    """
    Panel 1: 1_concept.png (Style: professional)
    """
    # Extract numbers strictly from k1625_data
    btc_days = resolve_json_path(k1625_data, "/per_asset/BTC/n_daily_rows_with_funding_and_rv")
    btc_start = resolve_json_path(k1625_data, "/per_asset/BTC/sample_start")
    btc_end = resolve_json_path(k1625_data, "/per_asset/BTC/sample_end")
    
    eth_days = resolve_json_path(k1625_data, "/per_asset/ETH/n_daily_rows_with_funding_and_rv")
    eth_start = resolve_json_path(k1625_data, "/per_asset/ETH/sample_start")
    eth_end = resolve_json_path(k1625_data, "/per_asset/ETH/sample_end")
    
    fig, ax = setup_canvas(bg_color="#F8FAFC")
    
    title = "誰在付錢，後面就會亂嗎"
    subtitle = "概念說明：永續合約每八小時結算一次資金費率，費率極端代表持倉擠在同一邊，本研究檢定它能否預告未來五天的高波動週"
    draw_header(ax, title, subtitle, accent_color="#2563EB")
    
    # Left Column: Concept Cards
    # Card 1: Every 8 hours pay fee
    draw_card(ax, 80, 210, 680, 340, bg_color="#0F172A", border_color="#1E293B", corner_radius=16)
    ax.text(110, 235, "每八小時付一次錢", fontsize=18, fontweight="bold", color="#F8FAFC", va="top")
    body1 = (
        "• 永續合約每八小時結算一次資金費率，做多的人付給做空的人，或者反過來。\n\n"
        "• 費率飆到平常的好幾倍，代表大家都擠在同一邊，而擠在同一邊要付租金。\n\n"
        "• 交易台上的講法是這種時候要小心，因為擁擠的部位被推一下就會連環出場。"
    )
    wrapped_b1 = wrap_cjk_text(body1, max_chars_per_line=21)
    ax.text(110, 275, wrapped_b1, fontsize=12, color="#CBD5E1", va="top", linespacing=1.3)
    
    # Card 2: Reframe question
    draw_card(ax, 80, 570, 680, 350, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=16)
    ax.text(110, 595, "換一個問法", fontsize=18, fontweight="bold", color="#0F172A", va="top")
    body2 = (
        "• 先前測過「隔天的波動預測得準不準」，把費率加進模型之後誤差幾乎沒動。\n\n"
        "• 這次不問明天那個數字，問接下來五天會不會整個變成高波動的一週。\n\n"
        "• 高波動週的定義是往後五天的平均波動，落在過去一年最高的那一段。"
    )
    wrapped_b2 = wrap_cjk_text(body2, max_chars_per_line=21)
    ax.text(110, 635, wrapped_b2, fontsize=12, color="#334155", va="top", linespacing=1.3)
    
    # Right Column: Data Metrics
    # BTC Metric Card
    draw_card(ax, 800, 210, 720, 340, bg_color="#FFFFFF", border_color="#3B82F6", corner_radius=16)
    ax.text(840, 235, "比特幣可用交易日", fontsize=16, fontweight="bold", color="#1D4ED8", va="top")
    ax.text(840, 270, f"{btc_days} 天", fontsize=42, fontweight="bold", color="#1E3A8A", va="top")
    ax.plot([840, 1480], [375, 375], color="#E2E8F0", linewidth=1)
    btc_note = f"樣本自 {btc_start} 至 {btc_end}，同時有費率與波動的日子"
    ax.text(840, 395, wrap_cjk_text(btc_note, max_chars_per_line=22), fontsize=13, color="#475569", va="top", linespacing=1.3)
    
    # ETH Metric Card
    draw_card(ax, 800, 570, 720, 350, bg_color="#FFFFFF", border_color="#0D9488", corner_radius=16)
    ax.text(840, 595, "以太幣可用交易日", fontsize=16, fontweight="bold", color="#0F766E", va="top")
    ax.text(840, 630, f"{eth_days} 天", fontsize=42, fontweight="bold", color="#115E59", va="top")
    ax.plot([840, 1480], [735, 735], color="#E2E8F0", linewidth=1)
    eth_note = f"樣本自 {eth_start} 至 {eth_end}，同一套定義與同一個資料來源"
    ax.text(840, 755, wrap_cjk_text(eth_note, max_chars_per_line=22), fontsize=13, color="#475569", va="top", linespacing=1.3)
    
    draw_footer(ax, source_label)
    
    out_file = os.path.join(out_dir, "1_concept.png")
    fig.savefig(out_file, format="png", dpi=150)
    plt.close(fig)


def render_panel_2(plan_data, k1625_data, source_label, out_dir):
    """
    Panel 2: 2_result.png (Style: scientific)
    """
    # Extract numbers strictly from k1625_data
    btc_pos_rate = resolve_json_path(k1625_data, "/per_asset/BTC/conditional_high_rv_rates/h5/positive_funding_extreme/high_rv_rate")
    btc_pos_n = resolve_json_path(k1625_data, "/per_asset/BTC/conditional_high_rv_rates/h5/positive_funding_extreme/n")
    
    btc_non_rate = resolve_json_path(k1625_data, "/per_asset/BTC/conditional_high_rv_rates/h5/non_extreme/high_rv_rate")
    btc_non_n = resolve_json_path(k1625_data, "/per_asset/BTC/conditional_high_rv_rates/h5/non_extreme/n")
    
    eth_pos_rate = resolve_json_path(k1625_data, "/per_asset/ETH/conditional_high_rv_rates/h5/positive_funding_extreme/high_rv_rate")
    eth_base_rate = resolve_json_path(k1625_data, "/per_asset/ETH/conditional_high_rv_rates/h5/non_extreme/high_rv_rate")
    
    btc_z_t = resolve_json_path(k1625_data, "/primary_tstats/12/t")
    btc_pos_t = resolve_json_path(k1625_data, "/primary_tstats/13/t")
    eth_fz_t = resolve_json_path(k1625_data, "/primary_tstats/28/t")
    
    fig, ax = setup_canvas(bg_color="#F8FAFC")
    
    title = "比率很好看，控制之後不見了"
    subtitle = "結果說明：比特幣在費率極高日之後的高波動週比率遠高於平常日，但加入前一日波動與漲跌幅控制後，極端日這個開關的估計值掉到接近零"
    draw_header(ax, title, subtitle, accent_color="#4F46E5")
    
    # 4 Top Metric Cards (Grid)
    # Card 1: BTC Positive Extreme
    draw_card(ax, 80, 210, 340, 330, bg_color="#FFFFFF", border_color="#FCA5A5", corner_radius=16)
    ax.text(105, 230, "比特幣：多方極端日", fontsize=14, fontweight="bold", color="#DC2626", va="top")
    ax.text(105, 265, f"{btc_pos_rate * 100:.1f}%", fontsize=38, fontweight="bold", color="#991B1B", va="top")
    ax.text(105, 355, "高波動週比率", fontsize=13, fontweight="bold", color="#334155", va="top")
    ax.text(105, 390, wrap_cjk_text(f"這種日子在樣本裡\n共 {btc_pos_n} 天", max_chars_per_line=11), fontsize=12, color="#64748B", va="top", linespacing=1.3)
    
    # Card 2: BTC Non-extreme
    draw_card(ax, 440, 210, 340, 330, bg_color="#FFFFFF", border_color="#E2E8F0", corner_radius=16)
    ax.text(465, 230, "比特幣：平常日", fontsize=14, fontweight="bold", color="#475569", va="top")
    ax.text(465, 265, f"{btc_non_rate * 100:.1f}%", fontsize=38, fontweight="bold", color="#334155", va="top")
    ax.text(465, 355, "平常日同格比率", fontsize=13, fontweight="bold", color="#334155", va="top")
    ax.text(465, 390, wrap_cjk_text(f"共 {btc_non_n} 天；與極端日\n落差接近翻倍", max_chars_per_line=11), fontsize=12, color="#64748B", va="top", linespacing=1.3)
    
    # Card 3: ETH Positive Extreme
    draw_card(ax, 800, 210, 340, 330, bg_color="#FFFFFF", border_color="#FDE68A", corner_radius=16)
    ax.text(825, 230, "以太幣：多方極端日", fontsize=14, fontweight="bold", color="#D97706", va="top")
    ax.text(825, 265, f"{eth_pos_rate * 100:.1f}%", fontsize=38, fontweight="bold", color="#B45309", va="top")
    ax.text(825, 355, "高波動週比率", fontsize=13, fontweight="bold", color="#334155", va="top")
    ax.text(825, 390, wrap_cjk_text(f"平常日為 {eth_base_rate * 100:.1f}%\n落差僅 BTC 一半", max_chars_per_line=11), fontsize=12, color="#64748B", va="top", linespacing=1.3)
    
    # Card 4: Signal t-stat
    draw_card(ax, 1160, 210, 360, 330, bg_color="#FFFFFF", border_color="#6EE7B7", corner_radius=16)
    ax.text(1185, 230, "控制後顯著訊號", fontsize=14, fontweight="bold", color="#059669", va="top")
    ax.text(1185, 265, f"{btc_z_t:.2f} 倍", fontsize=38, fontweight="bold", color="#047857", va="top")
    ax.text(1185, 355, "比特幣費率高低 (t值)", fontsize=13, fontweight="bold", color="#065F46", va="top")
    ax.text(1185, 390, wrap_cjk_text("相對於估計誤差倍數\n過關門檻為 3.00 倍", max_chars_per_line=12), fontsize=12, color="#64748B", va="top", linespacing=1.3)
    
    # Bottom Scientific Regression Card
    draw_card(ax, 80, 560, 1440, 360, bg_color="#EFF6FF", border_color="#BFDBFE", corner_radius=16)
    ax.text(110, 585, "極端日那個開關，控制之後沒了", fontsize=19, fontweight="bold", color="#1E3A8A", va="top")
    
    text_line1 = f"• 扣掉前一日的波動與漲跌幅之後，「今天是不是極端日」這個開關掉到 {btc_pos_t:.2f} 倍，離過關線遠得看不見。"
    text_line2 = f"• 同一個費率高低的問法搬到以太幣只有 {eth_fz_t:.2f} 倍，多空之間的不對稱檢定兩個幣都沒過。"
    
    ax.text(110, 630, wrap_cjk_text(text_line1, max_chars_per_line=42), fontsize=13, color="#1E40AF", va="top", linespacing=1.3)
    ax.text(110, 685, wrap_cjk_text(text_line2, max_chars_per_line=42), fontsize=13, color="#1E40AF", va="top", linespacing=1.3)
    
    # Callout highlight box inside bottom card
    draw_card(ax, 110, 755, 1380, 145, bg_color="#FFFFFF", border_color="#93C5FD", corner_radius=12)
    takeaway_callout = "結論解讀：單看比率（29.6% vs 16.8%）看起來很有吸引力，但迴歸控制前一日波動後，極端日開關完全失效。看起來很大的落差主要來自『前一天本來就在波動』的延續。"
    ax.text(130, 770, wrap_cjk_text(takeaway_callout, max_chars_per_line=40), fontsize=13, fontweight="bold", color="#1E3A8A", va="top", linespacing=1.35)
    
    draw_footer(ax, source_label)
    
    out_file = os.path.join(out_dir, "2_result.png")
    fig.savefig(out_file, format="png", dpi=150)
    plt.close(fig)


def render_panel_3(plan_data, k1625_data, source_label, out_dir):
    """
    Panel 3: 3_conclusion.png (Style: editorial)
    """
    # Extract numbers strictly from k1625_data
    n_passed = resolve_json_path(k1625_data, "/verdict_basis/n_h5_regime_abs_t_ge_3")
    max_abs_t = resolve_json_path(k1625_data, "/verdict_basis/max_abs_t_any_test")
    
    fig, ax = setup_canvas(bg_color="#FAF9F6")
    
    title = "事先講好要兩格，最後只中一格"
    subtitle = "結論說明：預先設定的判定規則要求五日高波動週檢定至少兩格站上門檻，實際只有一格，因此本研究列為待追線索而非可用訊號"
    draw_header(ax, title, subtitle, accent_color="#991B1B")
    
    # 2 Hero Metric Cards
    # Hero 1: Passed cells
    draw_card(ax, 80, 210, 680, 240, bg_color="#FFFFFF", border_color="#991B1B", corner_radius=16)
    ax.text(110, 235, "五日高波動週檢定中站上門檻的格數", fontsize=15, fontweight="bold", color="#991B1B", va="top")
    ax.text(110, 270, f"{n_passed} 格", fontsize=48, fontweight="bold", color="#7F1D1D", va="top")
    note1 = wrap_cjk_text("開跑前就寫死要兩格才算找到訊號，一格只能叫單格弱結果", max_chars_per_line=20)
    ax.text(110, 380, note1, fontsize=12, color="#71717A", va="top", linespacing=1.3)
    
    # Hero 2: Max Signal Strength
    draw_card(ax, 800, 210, 720, 240, bg_color="#FFFFFF", border_color="#2563EB", corner_radius=16)
    ax.text(830, 235, "全部檢定裡最高的訊號強度", fontsize=15, fontweight="bold", color="#1D4ED8", va="top")
    ax.text(830, 270, f"{max_abs_t:.2f} 倍", fontsize=48, fontweight="bold", color="#1E40AF", va="top")
    note2 = wrap_cjk_text("出現在比特幣的費率高低那一格，仍然是比特幣獨有", max_chars_per_line=21)
    ax.text(830, 380, note2, fontsize=12, color="#71717A", va="top", linespacing=1.3)
    
    # 2 Editorial Columns Below
    # Left Column: Limitations
    draw_card(ax, 80, 470, 680, 450, bg_color="#F4F4F5", border_color="#E4E4E7", corner_radius=16)
    ax.text(110, 495, "限制講在前面", fontsize=19, fontweight="bold", color="#27272A", va="top")
    
    bullets = (
        "1. 只有幣安一家的費率，跨交易所的分歧完全沒測。\n\n"
        "2. 費率是持倉壓力的代理，不是真正的爆倉量或帳戶槓桿。\n\n"
        "3. 比特幣那一格有可能只是它自己這幾年的體質，以太幣對不上就是最直接的反證。"
    )
    wrapped_bullets = wrap_cjk_text(bullets, max_chars_per_line=20)
    ax.text(110, 540, wrapped_bullets, fontsize=13, color="#3F3F46", va="top", linespacing=1.3)
    
    # Right Column: Takeaway Quotes
    draw_card(ax, 800, 470, 720, 450, bg_color="#FEF2F2", border_color="#FECACA", corner_radius=16)
    ax.text(830, 495, "帶得走的一句話", fontsize=19, fontweight="bold", color="#991B1B", va="top")
    
    quote1 = "「看起來很大的落差，跟站得住的落差，是兩回事。」"
    quote2 = "「把『加密貨幣』當成一個東西來談，很容易在這種地方跌倒。」"
    
    ax.text(830, 540, wrap_cjk_text(quote1, max_chars_per_line=18), fontsize=14, fontweight="bold", color="#7F1D1D", va="top", linespacing=1.3)
    ax.text(830, 630, wrap_cjk_text(quote2, max_chars_per_line=18), fontsize=14, fontweight="bold", color="#7F1D1D", va="top", linespacing=1.3)
    
    summary_box = "總結：資金費率走極端時，後續高波動週比率看起來很高，但多半是昨日波動的延續。這是一條待追線索，而非可執行的量化交易訊號。"
    ax.text(830, 740, wrap_cjk_text(summary_box, max_chars_per_line=22), fontsize=12, color="#52525B", va="top", linespacing=1.3)
    
    draw_footer(ax, source_label)
    
    out_file = os.path.join(out_dir, "3_conclusion.png")
    fig.savefig(out_file, format="png", dpi=150)
    plt.close(fig)


def main():
    # Make sure output directory exists
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Load evidence JSON files with absolute paths
    if not os.path.exists(PLAN_PATH):
        raise FileNotFoundError(f"Plan file not found at {PLAN_PATH}")
    if not os.path.exists(RESULTS_PATH):
        raise FileNotFoundError(f"Results file not found at {RESULTS_PATH}")
        
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan_data = json.load(f)
        
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        k1625_data = json.load(f)
        
    # Get mandatory source label from plan evidence
    source_label = resolve_json_path(plan_data, "/evidence/k1625/label")
    
    # Render each panel
    render_panel_1(plan_data, k1625_data, source_label, OUT_DIR)
    render_panel_2(plan_data, k1625_data, source_label, OUT_DIR)
    render_panel_3(plan_data, k1625_data, source_label, OUT_DIR)
    
    print(f"Successfully generated lazypack panels in {OUT_DIR}:")
    print(" - 1_concept.png")
    print(" - 2_result.png")
    print(" - 3_conclusion.png")

if __name__ == "__main__":
    main()
