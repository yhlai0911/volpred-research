#!/usr/bin/env python3
import os
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Path configuration
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k740/k740_strategy_meta_analysis_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_d9ff126f/runs/lazypack-mile_d9ff126f/panels"

# Visual settings
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

def resolve_path(data, path):
    """Resolves dotted path in data object. Raises KeyError if missing."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Path '{path}' not found in data: '{part}' is missing.")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Path '{path}' index error in list at '{part}'.") from exc
        else:
            raise KeyError(f"Path '{path}' type mismatch in data at '{part}'.")
    return cur

def format_val(val, fmt_spec):
    """Formats values according to format specifications."""
    kind = fmt_spec.get("kind")
    if kind == "integer":
        suffix = fmt_spec.get("suffix", "")
        return f"{int(round(val))}{suffix}"
    elif kind == "percent":
        digits = fmt_spec.get("digits", 2)
        return f"{val:.{digits}f}%"
    elif kind == "number":
        digits = fmt_spec.get("digits", 3)
        return f"{val:.{digits}f}"
    elif kind == "text":
        return str(val)
    else:
        return str(val)

def resolve_body_item(item, data):
    """Resolves template and bindings dynamically for body items."""
    if isinstance(item, dict) and "template" in item and "bindings" in item:
        template_str = item["template"]
        bindings = item["bindings"]
        res = template_str
        for key, bind in bindings.items():
            path = bind["path"]
            val = resolve_path(data, path)
            fmt_spec = bind["format"]
            formatted = format_val(val, fmt_spec)
            suffix = fmt_spec.get("suffix", "")
            placeholder = f"{{{key}}}"
            # Deduplicate suffix if it exists in the template immediately after the placeholder
            if suffix and (placeholder + suffix in res):
                val_no_suffix = format_val(val, {**fmt_spec, "suffix": ""})
                res = res.replace(placeholder, val_no_suffix)
            elif suffix and (placeholder + " " + suffix in res):
                val_no_suffix = format_val(val, {**fmt_spec, "suffix": ""})
                res = res.replace(placeholder, val_no_suffix)
            else:
                res = res.replace(placeholder, formatted)
        return res
    return str(item)

def draw_card(ax, x, y, w, h, facecolor='#FFFFFF', edgecolor='#E2E8F0', linewidth=1.5, r=0.15):
    """Draws a rounded card with exact coordinate boundaries."""
    pad = r
    if w <= 2 * pad or h <= 2 * pad:
        pad = min(w, h) * 0.4
    bbox = patches.FancyBboxPatch(
        (x + pad, y + pad), w - 2 * pad, h - 2 * pad,
        boxstyle=f"round,pad={pad}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        zorder=1
    )
    ax.add_patch(bbox)

def wrap_and_draw_text(ax, text, x, y, width_limit, font_size, font_weight='normal', color='#000000', line_spacing=1.3, align='left', va='top'):
    """Wraps text based on font size and physical width limit in data coordinate units, then draws it."""
    # At 100 dpi, 1 pt = 1.389 pixels = 0.01389 data units.
    # Conservatively estimate character widths in data units:
    # Full-width (Chinese): font_size * 0.015 units.
    # Half-width (English): font_size * 0.0085 units.
    char_unit_full = font_size * 0.015
    char_unit_half = font_size * 0.0085
    
    lines = []
    for part in text.split('\n'):
        current_line = ""
        current_width = 0.0
        for char in part:
            w_char = char_unit_full if ord(char) > 127 else char_unit_half
            if current_width + w_char > width_limit:
                if current_line == "":
                    lines.append(char)
                    current_line = ""
                    current_width = 0.0
                else:
                    lines.append(current_line)
                    current_line = char
                    current_width = w_char
            else:
                current_line += char
                current_width += w_char
        if current_line:
            lines.append(current_line)
            
    current_y = y
    for line in lines:
        ax.text(
            x, current_y, line,
            fontfamily='Heiti TC',
            fontsize=font_size,
            fontweight=font_weight,
            color=color,
            horizontalalignment=align,
            verticalalignment=va,
            zorder=2
        )
        line_height_y = (font_size / 100.0) * line_spacing
        current_y -= line_height_y
    return current_y

def draw_header(ax, title, subtitle):
    """Draws a premium header bar at the top."""
    header_rect = patches.Rectangle((0, 8.1), 16.0, 1.9, facecolor='#0F172A', edgecolor='none', zorder=0)
    ax.add_patch(header_rect)
    
    # Category badge
    draw_card(ax, 0.8, 9.3, 1.8, 0.32, facecolor='#0F766E', edgecolor='none', r=0.08)
    ax.text(0.8 + 0.9, 9.3 + 0.16, "VolPred 懶人包", color='#FFFFFF', fontsize=11, fontweight='bold', ha='center', va='center', fontfamily='Heiti TC', zorder=2)
    
    # Title
    ax.text(0.8, 8.85, title, color='#FFFFFF', fontsize=26, fontweight='bold', ha='left', va='top', fontfamily='Heiti TC', zorder=2)
    
    # Subtitle / Alt text
    wrap_and_draw_text(
        ax, subtitle, 0.8, 8.42,
        width_limit=14.4, font_size=14, font_weight='normal',
        color='#94A3B8', line_spacing=1.3
    )

def draw_footer(ax):
    """Draws a clean footer line and source labels."""
    # Divider line
    ax.plot([0.8, 15.2], [1.1, 1.1], color='#E2E8F0', linewidth=1.5, zorder=1)
    
    # Footer text (verbatim reader-facing source)
    footer_text = "資料來源：14 檔紙上交易策略的實際追蹤結果（2023-01 ~ 2026-03）"
    ax.text(0.8, 0.65, footer_text, color='#94A3B8', fontsize=12, fontweight='normal', ha='left', va='center', fontfamily='Heiti TC', zorder=2)

def draw_metric_card_fixed(ax, x, y, w, h, label, value, note=None, facecolor='#FFFFFF', edgecolor='#E2E8F0', accent_color='#0F766E', val_color='#0F172A', val_font_size=32):
    """Draws a clean metric block with labels and values."""
    draw_card(ax, x, y, w, h, facecolor=facecolor, edgecolor=edgecolor)
    
    label_y = y + h - 0.4
    label_x = x + 0.35
    
    wrap_and_draw_text(ax, label, label_x, label_y, width_limit=w - 0.7, font_size=13, font_weight='bold', color='#64748B')
    
    value_y = y + h - 1.2
    val_len_chars = sum(2 if ord(c) > 127 else 1 for c in value)
    adjusted_font_size = val_font_size
    
    # Adjust font size if it exceeds the card width bound
    # Half-width char width is roughly adjusted_font_size * 0.0095 data units.
    if val_len_chars * val_font_size * 0.0095 > (w - 0.7):
        adjusted_font_size = int((w - 0.7) / (val_len_chars * 0.0095))
        adjusted_font_size = max(16, adjusted_font_size)
        
    ax.text(label_x, value_y, value, fontfamily='Heiti TC', fontsize=adjusted_font_size, fontweight='bold', color=val_color, va='top', zorder=2)
    
    if note:
        note_y = y + 0.45
        wrap_and_draw_text(ax, note, label_x, note_y, width_limit=w - 0.7, font_size=12, font_weight='bold', color=accent_color)

def draw_text_card(ax, x, y, w, h, heading, body_list, facecolor='#FFFFFF', edgecolor='#E2E8F0'):
    """Draws a text block with styled lists."""
    draw_card(ax, x, y, w, h, facecolor=facecolor, edgecolor=edgecolor)
    
    hx = x + 0.35
    hy = y + h - 0.45
    
    wrap_and_draw_text(ax, heading, hx, hy, width_limit=w - 0.7, font_size=18, font_weight='bold', color='#0F172A')
    
    body_y = hy - 0.6
    for item in body_list:
        display_item = item
        if not item.startswith(('•', '1.', '2.', '3.')):
            display_item = "• " + item
        body_y = wrap_and_draw_text(ax, display_item, hx, body_y, width_limit=w - 0.7, font_size=14, font_weight='normal', color='#334155', line_spacing=1.35)
        body_y -= 0.15

def render_panel_winner(results):
    """Renders Panel 1: panel_winner.png"""
    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis('off')
    
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')
    
    # Title & Subtitle
    title = "冠軍是設定最單純的那一檔"
    subtitle = "綜合分數第一名的策略屬於最單純的複雜度等級，風險調整後表現與回撤控制皆居前"
    draw_header(ax, title, subtitle)
    
    # Left Card
    body_items = [
        {
          "template": "把 {n} 檔實際往前追蹤的策略，用同一組指標排名：風險調整後報酬、回撤、勝率、周轉率。",
          "bindings": {
            "n": {
              "source": "results",
              "path": "n_strategies",
              "format": {
                "kind": "integer",
                "suffix": " 檔"
              }
            }
          }
        },
        "複雜度是事前標好的等級，不是事後看績效倒推的。"
    ]
    resolved_body = [resolve_body_item(x, results) for x in body_items]
    draw_text_card(ax, 0.8, 1.6, 5.5, 6.2, "怎麼比的", resolved_body, facecolor='#F8FAFC', edgecolor='#E2E8F0')
    
    # Right Cards
    # Metric 1
    val_1 = format_val(resolve_path(results, "composite_ranking.0.display"), {"kind": "text"})
    draw_metric_card_fixed(ax, 6.7, 4.8, 4.1, 3.0, "綜合分數第一名", val_1, val_font_size=20)
    
    # Metric 2
    val_2 = format_val(resolve_path(results, "strategy_metrics.piecewise_conservative.complexity"), {"kind": "integer", "suffix": " 級"})
    draw_metric_card_fixed(ax, 11.1, 4.8, 4.1, 3.0, "它的複雜度等級（等級越小越單純）", val_2, val_font_size=36)
    
    # Metric 3
    val_3 = format_val(resolve_path(results, "strategy_metrics.piecewise_conservative.mdd"), {"kind": "percent", "digits": 2})
    draw_metric_card_fixed(ax, 6.7, 1.6, 4.1, 3.0, "最大回撤", val_3, note="全體策略中最淺", val_font_size=36, accent_color='#0D9488')
    
    # Metric 4
    val_4 = format_val(resolve_path(results, "strategy_metrics.piecewise_conservative.win_rate_monthly"), {"kind": "percent", "digits": 1})
    draw_metric_card_fixed(ax, 11.1, 1.6, 4.1, 3.0, "月勝率", val_4, val_font_size=36)
    
    # Footer
    draw_footer(ax)
    
    out_path = os.path.join(OUT_DIR, "panel_winner.png")
    plt.savefig(out_path, dpi=100, facecolor='#FFFFFF')
    plt.close(fig)
    print(f"Rendered: {out_path}")

def render_panel_complexity(results):
    """Renders Panel 2: panel_complexity.png"""
    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis('off')
    
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')
    
    # Title & Subtitle
    title = "把設定弄複雜，換不到更好的成績"
    subtitle = "複雜度與風險調整後報酬的等級相關不顯著，跨資產分散帶來的提升則明確得多"
    draw_header(ax, title, subtitle)
    
    # Bento Grid Boxes
    # Box 1
    val_rho = format_val(resolve_path(results, "characteristics_analysis.complexity_sharpe_correlation.rho"), {"kind": "number", "digits": 3})
    draw_metric_card_fixed(ax, 0.8, 4.8, 7.0, 3.0, "複雜度與風險調整後報酬的相關係數", val_rho, val_font_size=48, facecolor='#F8FAFC', val_color='#0F172A')
    
    # Box 2
    val_p = format_val(resolve_path(results, "characteristics_analysis.complexity_sharpe_correlation.p"), {"kind": "number", "digits": 3})
    draw_metric_card_fixed(ax, 8.2, 4.8, 7.0, 3.0, "上述相關的 p 值", val_p, note="遠高於常用顯著水準，測不到關係", val_font_size=48, facecolor='#F8FAFC', val_color='#E11D48', accent_color='#64748B')
    
    # Box 3
    val_div = format_val(resolve_path(results, "characteristics_analysis.diversification_premium_sharpe"), {"kind": "number", "digits": 3})
    draw_metric_card_fixed(ax, 0.8, 1.6, 7.0, 3.0, "跨資產分散帶來的提升", val_div, note="多資產相對單一資產的平均差距", val_font_size=48, facecolor='#F0FDFA', edgecolor='#CCFBF1', val_color='#0D9488', accent_color='#0F766E')
    
    # Box 4
    read_guide_body = [
        "複雜度那一欄怎麼看都看不出方向，統計上測不到。",
        "真正拉開差距的是「有沒有分散到別的資產」，不是「模型有多精巧」。"
    ]
    draw_text_card(ax, 8.2, 1.6, 7.0, 3.0, "讀法", read_guide_body, facecolor='#EEF2FF', edgecolor='#E0E7FF')
    
    # Footer
    draw_footer(ax)
    
    out_path = os.path.join(OUT_DIR, "panel_complexity.png")
    plt.savefig(out_path, dpi=100, facecolor='#FFFFFF')
    plt.close(fig)
    print(f"Rendered: {out_path}")

def render_panel_honesty(results):
    """Renders Panel 3: panel_honesty.png"""
    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis('off')
    
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')
    
    # Title & Subtitle
    title = "這份排名不能當投資建議"
    subtitle = "樣本為自建策略池、期間有限，排名為事後比較且未做多重比較校正"
    draw_header(ax, title, subtitle)
    
    # Card 1 (Top / Metric)
    val_period = format_val(resolve_path(results, "period"), {"kind": "text"})
    draw_metric_card_fixed(ax, 0.8, 5.4, 14.4, 2.4, "追蹤期間", val_period, note="只涵蓋有限的市場環境", val_font_size=32, facecolor='#F8FAFC', accent_color='#E11D48')
    
    # Card 2
    limits_body = [
        "這個策略池是我們自己養的，不是市場上所有做法的隨機抽樣。",
        "排名是在同一段期間、同一批策略裡比出來的，換一段期間名次就可能翻盤。",
        "沒有對「比了很多次」做統計修正，排名相鄰者的差距不該當成真實差距。"
    ]
    draw_text_card(ax, 0.8, 1.6, 7.0, 3.6, "三個要記得的限制", limits_body, facecolor='#F8FAFC', edgecolor='#E2E8F0')
    
    # Card 3
    takeaway_body = [
        "在這份資料裡，把設定弄複雜沒有換到更好的成績。",
        "本文為歷史追蹤結果，不構成任何投資建議。"
    ]
    draw_text_card(ax, 8.2, 1.6, 7.0, 3.6, "帶走一句話", takeaway_body, facecolor='#F8FAFC', edgecolor='#E2E8F0')
    
    # Footer
    draw_footer(ax)
    
    out_path = os.path.join(OUT_DIR, "panel_honesty.png")
    plt.savefig(out_path, dpi=100, facecolor='#FFFFFF')
    plt.close(fig)
    print(f"Rendered: {out_path}")

def main():
    # Make sure output directory exists
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Check that evidence file exists, raise if not
    if not os.path.exists(RESULTS_PATH):
        raise FileNotFoundError(f"Evidence file not found: {RESULTS_PATH}")
        
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results = json.load(f)
        
    render_panel_winner(results)
    render_panel_complexity(results)
    render_panel_honesty(results)

if __name__ == "__main__":
    main()
