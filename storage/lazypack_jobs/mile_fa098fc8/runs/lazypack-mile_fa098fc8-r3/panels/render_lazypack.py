#!/usr/bin/env python3
import os
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Color scheme
COLOR_PRIMARY = "#1F4E79"
COLOR_PRIMARY_BG = "#F0F4F8"
COLOR_SUCCESS = "#2E7D32"
COLOR_SUCCESS_BG = "#E8F5E9"
COLOR_WARNING = "#C62828"
COLOR_WARNING_BG = "#FFEBEE"
COLOR_ACCENT = "#EF6C00"
COLOR_ACCENT_BG = "#FFF3E0"
BORDER_COLOR = "#E0E0E0"
TEXT_MAIN = "#1A1A1A"
TEXT_MUTED = "#555555"
TEXT_LIGHT = "#777777"

# Font setting
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

def resolve_val(data, path):
    if path.startswith('/'):
        parts = path.lstrip('/').split('/')
    elif '/' in path:
        parts = path.split('/')
    else:
        parts = path.split('.')
    
    cur = data
    for part in parts:
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Key '{part}' not found in data. Path: {path}")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Index '{part}' not found in list. Path: {path}") from exc
        else:
            raise KeyError(f"Cannot traverse '{part}' on non-collection. Path: {path}")
    return cur

def format_metric(val, format_cfg):
    kind = format_cfg.get("kind")
    digits = format_cfg.get("digits", 0)
    suffix = format_cfg.get("suffix", "")
    show_plus = format_cfg.get("show_plus", False)
    
    if kind == "percent":
        val_pct = val * 100
        sign = "+" if (show_plus and val_pct > 0) else ""
        return f"{sign}{val_pct:.{digits}f}%{suffix}"
    elif kind == "number":
        sign = "+" if (show_plus and val > 0) else ""
        return f"{sign}{val:.{digits}f}{suffix}"
    elif kind == "integer":
        val_int = int(round(val))
        sign = "+" if (show_plus and val_int > 0) else ""
        return f"{sign}{val_int}{suffix}"
    else:
        return f"{val}{suffix}"

def wrap_chinese_english_text(text, max_width_pts, fontsize):
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph.strip():
            lines.append('')
            continue
        
        current_line = ""
        current_width = 0
        for char in paragraph:
            char_w = fontsize if ord(char) > 127 else fontsize * 0.55
            if current_width + char_w > max_width_pts:
                lines.append(current_line)
                current_line = char
                current_width = char_w
            else:
                current_line += char
                current_width += char_w
        if current_line:
            lines.append(current_line)
    return lines

def draw_text_block(ax, text, x, y, width_frac, fontsize, color, weight='normal', ha='left', va='top', line_spacing=1.3):
    max_width_pts = width_frac * 768.0 * 0.93
    lines = wrap_chinese_english_text(text, max_width_pts, fontsize)
    
    dy = (fontsize * line_spacing) / 480.0
    current_y = y
    for line in lines:
        ax.text(x, current_y, line, fontsize=fontsize, color=color, fontweight=weight, ha=ha, va=va, transform=ax.transAxes)
        current_y -= dy
    return current_y

def draw_card(ax, x, y, width, height, facecolor='#FFFFFF', edgecolor='#E0E0E0', linewidth=1, alpha=1.0):
    rect = patches.FancyBboxPatch(
        (x + 0.002, y + 0.002), width - 0.004, height - 0.004,
        boxstyle="round,pad=0.002",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        alpha=alpha,
        transform=ax.transAxes
    )
    ax.add_patch(rect)

def draw_metric_card(ax, x, y, width, height, value, label, note=None, bg_color='#FFFFFF', border_color='#E0E0E0', value_color='#1A1A1A', label_color='#555555', note_color='#777777'):
    draw_card(ax, x, y, width, height, facecolor=bg_color, edgecolor=border_color, linewidth=1 if border_color != 'none' else 0)
    
    text_x = x + 0.015
    val_y = y + height - 0.03
    
    ax.text(text_x, val_y, value, fontsize=24, fontweight='bold', color=value_color, ha='left', va='top', transform=ax.transAxes)
    
    label_y = val_y - 0.06
    end_label_y = draw_text_block(ax, label, text_x, label_y, width - 0.03, fontsize=9.5, color=label_color, line_spacing=1.2)
    
    if note:
        note_y = end_label_y - 0.01
        draw_text_block(ax, note, text_x, note_y, width - 0.03, fontsize=8.0, color=note_color, line_spacing=1.1)

def draw_header_and_footer(ax, title, subtitle, sources_list):
    ax.text(0.05, 0.94, "VolPred 懶人包", fontsize=10, fontweight='bold', color='#1F4E79', ha='left', va='top', transform=ax.transAxes)
    ax.text(0.05, 0.89, title, fontsize=20, fontweight='bold', color='#1A1A1A', ha='left', va='top', transform=ax.transAxes)
    
    sub_y = draw_text_block(ax, subtitle, 0.05, 0.83, 0.90, fontsize=11, color='#555555')
    
    ax.plot([0.05, 0.95], [0.07, 0.07], color='#E0E0E0', linewidth=1, transform=ax.transAxes)
    
    sources_text = "資料來源：" + " | ".join(sources_list)
    ax.text(0.05, 0.04, sources_text, fontsize=8.5, color='#777777', ha='left', va='bottom', transform=ax.transAxes)
    
    return sub_y

def format_block_text(block, results_data, robustness_data):
    if block.get("kind") == "text":
        lines = []
        for item in block["body"]:
            if isinstance(item, str):
                lines.append(item)
            elif isinstance(item, dict) and "template" in item:
                template = item["template"]
                bindings = item["bindings"]
                fmt_vals = {}
                for var_name, bind_info in bindings.items():
                    source = bind_info["source"]
                    data = results_data if source == "results" else robustness_data
                    val = resolve_val(data, bind_info["path"])
                    fmt_vals[var_name] = format_metric(val, bind_info["format"])
                lines.append(template.format(**fmt_vals))
        return "\n\n".join(lines)
    return ""

def render_panel_signal(results_data, robustness_data, panel_cfg, out_path, sources_list):
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')
    
    title = panel_cfg["title"]
    subtitle = panel_cfg["alt"]
    sub_y = draw_header_and_footer(ax, title, subtitle, sources_list)
    
    body_start_y = sub_y - 0.03
    
    # Left Card
    left_x = 0.05
    left_width = 0.40
    left_height = body_start_y - 0.085
    draw_card(ax, left_x, 0.085, left_width, left_height, facecolor='#F0F4F8', edgecolor='none')
    
    # Left Content
    block_text = format_block_text(panel_cfg["blocks"][0], results_data, robustness_data)
    heading = panel_cfg["blocks"][0]["heading"]
    
    y_ptr = body_start_y - 0.03
    y_ptr = draw_text_block(ax, heading, left_x + 0.02, y_ptr, left_width - 0.04, fontsize=13, color='#1F4E79', weight='bold')
    y_ptr -= 0.015
    draw_text_block(ax, block_text, left_x + 0.02, y_ptr, left_width - 0.04, fontsize=10.5, color='#555555', line_spacing=1.4)
    
    # Right 2x2 cards
    mid_y = (body_start_y + 0.085) / 2
    r_width = 0.22
    r_height = (body_start_y - 0.085) / 2 - 0.01
    
    m1 = panel_cfg["blocks"][1]
    m2 = panel_cfg["blocks"][2]
    m3 = panel_cfg["blocks"][3]
    m4 = panel_cfg["blocks"][4]
    
    v1 = format_metric(resolve_val(results_data, m1["value"]["path"]), m1["value"]["format"])
    v2 = format_metric(resolve_val(results_data, m2["value"]["path"]), m2["value"]["format"])
    v3 = format_metric(resolve_val(results_data, m3["value"]["path"]), m3["value"]["format"])
    v4 = format_metric(resolve_val(results_data, m4["value"]["path"]), m4["value"]["format"])
    
    # Card 1 (Top Left): mean_ret_after_big_down_ann
    draw_metric_card(ax, 0.48, mid_y + 0.01, r_width, r_height, v1, m1["label"], bg_color='#E8F5E9', border_color='none', value_color='#2E7D32')
    
    # Card 2 (Top Right): mean_ret_after_big_up_ann
    draw_metric_card(ax, 0.73, mid_y + 0.01, r_width, r_height, v2, m2["label"], bg_color='#FFEBEE', border_color='none', value_color='#C62828')
    
    # Card 3 (Bottom Left): acf_lag1
    draw_metric_card(ax, 0.48, 0.085, r_width, r_height, v3, m3["label"], note=m3.get("note"), bg_color='#F9F9FB', border_color='#E0E0E0', value_color='#1A1A1A')
    
    # Card 4 (Bottom Right): n_observations
    draw_metric_card(ax, 0.73, 0.085, r_width, r_height, v4, m4["label"], bg_color='#F0F4F8', border_color='none', value_color='#1F4E79')
    
    plt.savefig(out_path, bbox_inches='tight', dpi=150)
    plt.close()

def render_panel_result(results_data, robustness_data, panel_cfg, out_path, sources_list):
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')
    
    title = panel_cfg["title"]
    subtitle = panel_cfg["alt"]
    sub_y = draw_header_and_footer(ax, title, subtitle, sources_list)
    
    body_start_y = sub_y - 0.03
    mid_y = (body_start_y + 0.085) / 2
    
    # Card 1 (Top Left): 兩種做法
    c1 = panel_cfg["blocks"][0]
    c1_txt = format_block_text(c1, results_data, robustness_data)
    c1_h = body_start_y - (mid_y + 0.01)
    draw_card(ax, 0.05, mid_y + 0.01, 0.36, c1_h, facecolor='#F9F9FB', edgecolor='#E0E0E0')
    draw_text_block(ax, c1["heading"], 0.07, body_start_y - 0.03, 0.32, fontsize=12, color='#1F4E79', weight='bold')
    draw_text_block(ax, c1_txt, 0.07, body_start_y - 0.075, 0.32, fontsize=9.5, color='#555555', line_spacing=1.3)
    
    # Card 2 (Bottom Left): 怎麼讀
    c2 = panel_cfg["blocks"][6]
    c2_txt = format_block_text(c2, results_data, robustness_data)
    c2_h = mid_y - 0.085 - 0.01
    draw_card(ax, 0.05, 0.085, 0.36, c2_h, facecolor='#F9F9FB', edgecolor='#E0E0E0')
    draw_text_block(ax, c2["heading"], 0.07, mid_y - 0.03, 0.32, fontsize=12, color='#1F4E79', weight='bold')
    draw_text_block(ax, c2_txt, 0.07, mid_y - 0.075, 0.32, fontsize=9.5, color='#555555', line_spacing=1.3)
    
    # Card 3 (Top Middle): Sharpe
    m1 = panel_cfg["blocks"][1]
    m2 = panel_cfg["blocks"][2]
    v1 = format_metric(resolve_val(results_data, m1["value"]["path"]), m1["value"]["format"])
    v2 = format_metric(resolve_val(results_data, m2["value"]["path"]), m2["value"]["format"])
    
    draw_card(ax, 0.44, mid_y + 0.01, 0.25, c1_h, facecolor='#FFFFFF', edgecolor='#E0E0E0')
    draw_text_block(ax, "風險調整後分數", 0.46, body_start_y - 0.03, 0.21, fontsize=11, color='#555555', weight='bold')
    ax.text(0.46, body_start_y - 0.08, v1, fontsize=24, fontweight='bold', color='#2E7D32', ha='left', va='top', transform=ax.transAxes)
    draw_text_block(ax, m1["label"], 0.46, body_start_y - 0.14, 0.21, fontsize=9, color='#777777')
    ax.text(0.46, body_start_y - 0.18, v2, fontsize=18, fontweight='bold', color='#555555', ha='left', va='top', transform=ax.transAxes)
    draw_text_block(ax, m2["label"], 0.46, body_start_y - 0.23, 0.21, fontsize=9, color='#777777')
    
    # Card 4 (Bottom Middle): Max Drawdown
    m3 = panel_cfg["blocks"][3]
    m4 = panel_cfg["blocks"][4]
    v3 = format_metric(resolve_val(results_data, m3["value"]["path"]), m3["value"]["format"])
    v4 = format_metric(resolve_val(results_data, m4["value"]["path"]), m4["value"]["format"])
    
    draw_card(ax, 0.44, 0.085, 0.25, c2_h, facecolor='#FFFFFF', edgecolor='#E0E0E0')
    draw_text_block(ax, "最大回撤 (風險控制)", 0.46, mid_y - 0.03, 0.21, fontsize=11, color='#555555', weight='bold')
    ax.text(0.46, mid_y - 0.08, v3, fontsize=24, fontweight='bold', color='#2E7D32', ha='left', va='top', transform=ax.transAxes)
    draw_text_block(ax, m3["label"], 0.46, mid_y - 0.14, 0.21, fontsize=9, color='#777777')
    ax.text(0.46, mid_y - 0.18, v4, fontsize=18, fontweight='bold', color='#555555', ha='left', va='top', transform=ax.transAxes)
    draw_text_block(ax, m4["label"], 0.46, mid_y - 0.23, 0.21, fontsize=9, color='#777777')
    
    # Card 5 (Right Column): Turnover
    m5 = panel_cfg["blocks"][5]
    v5 = format_metric(resolve_val(results_data, m5["value"]["path"]), m5["value"]["format"])
    
    draw_card(ax, 0.72, 0.085, 0.23, body_start_y - 0.085, facecolor='#FFF3E0', edgecolor='none')
    draw_text_block(ax, "年化換手率", 0.74, body_start_y - 0.03, 0.19, fontsize=11, color='#EF6C00', weight='bold')
    ax.text(0.74, body_start_y - 0.09, v5, fontsize=30, fontweight='bold', color='#1A1A1A', ha='left', va='top', transform=ax.transAxes)
    draw_text_block(ax, m5["label"], 0.74, body_start_y - 0.16, 0.19, fontsize=9.5, color='#555555')
    draw_text_block(ax, f"({m5['note']})", 0.74, body_start_y - 0.20, 0.19, fontsize=8.5, color='#EF6C00')
    
    draw_text_block(ax, "頻繁的調整代表需要付出更多的交易成本，必須確認超額報酬能覆蓋此成本。", 0.74, body_start_y - 0.32, 0.19, fontsize=9, color='#555555', line_spacing=1.3)
    
    plt.savefig(out_path, bbox_inches='tight', dpi=150)
    plt.close()

def render_panel_turnover(results_data, robustness_data, panel_cfg, out_path, sources_list):
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')
    
    title = panel_cfg["title"]
    subtitle = panel_cfg["alt"]
    sub_y = draw_header_and_footer(ax, title, subtitle, sources_list)
    
    body_start_y = sub_y - 0.03
    mid_y = (body_start_y + 0.085) / 2
    
    # Left column: Description
    c0 = panel_cfg["blocks"][0]
    c0_txt = format_block_text(c0, results_data, robustness_data)
    draw_card(ax, 0.05, 0.085, 0.38, body_start_y - 0.085, facecolor='#F4F6F9', edgecolor='none')
    draw_text_block(ax, c0["heading"], 0.07, body_start_y - 0.03, 0.34, fontsize=13, color='#1F4E79', weight='bold')
    draw_text_block(ax, c0_txt, 0.07, body_start_y - 0.08, 0.34, fontsize=10.5, color='#555555', line_spacing=1.4)
    
    ax.plot([0.07, 0.41], [body_start_y - 0.28, body_start_y - 0.28], color='#D0D4DC', linewidth=1, transform=ax.transAxes)
    
    details = "雙維度網格參數掃描：\n• 觸發門檻：0.5% ~ 3.0% (每 0.5% 遞增)\n• 股票傾斜幅度：10% ~ 30% (每 5% 遞增)\n• 交易成本假設：單邊 5 bps"
    draw_text_block(ax, details, 0.07, body_start_y - 0.31, 0.34, fontsize=9.5, color='#777777', line_spacing=1.3)
    
    # Right Column: Cards
    # Card 1 (Top Right): Best Point
    m1 = panel_cfg["blocks"][1]
    m2 = panel_cfg["blocks"][2]
    m3 = panel_cfg["blocks"][3]
    m4 = panel_cfg["blocks"][4]
    
    v1 = format_metric(resolve_val(results_data, m1["value"]["path"]), m1["value"]["format"])
    v2 = format_metric(resolve_val(results_data, m2["value"]["path"]), m2["value"]["format"])
    v3 = format_metric(resolve_val(results_data, m3["value"]["path"]), m3["value"]["format"])
    v4 = format_metric(resolve_val(results_data, m4["value"]["path"]), m4["value"]["format"])
    
    c1_h = body_start_y - (mid_y + 0.01)
    draw_card(ax, 0.47, mid_y + 0.01, 0.48, c1_h, facecolor='#E8F5E9', edgecolor='#2E7D32')
    draw_text_block(ax, "網格最佳點 (高門檻、低頻率)", 0.49, body_start_y - 0.03, 0.44, fontsize=11, color='#2E7D32', weight='bold')
    
    # Row 1
    ax.text(0.49, body_start_y - 0.08, v1, fontsize=18, fontweight='bold', color='#1A1A1A', va='top', transform=ax.transAxes)
    draw_text_block(ax, m1["label"], 0.49, body_start_y - 0.125, 0.20, fontsize=8.5, color='#555555')
    
    ax.text(0.72, body_start_y - 0.08, v2, fontsize=18, fontweight='bold', color='#1A1A1A', va='top', transform=ax.transAxes)
    draw_text_block(ax, m2["label"], 0.72, body_start_y - 0.125, 0.20, fontsize=8.5, color='#555555')
    
    # Row 2
    ax.text(0.49, body_start_y - 0.17, v3, fontsize=18, fontweight='bold', color='#1A1A1A', va='top', transform=ax.transAxes)
    draw_text_block(ax, m3["label"], 0.49, body_start_y - 0.215, 0.20, fontsize=8.5, color='#555555')
    
    ax.text(0.72, body_start_y - 0.17, v4, fontsize=20, fontweight='bold', color='#2E7D32', va='top', transform=ax.transAxes)
    draw_text_block(ax, m4["label"], 0.72, body_start_y - 0.215, 0.20, fontsize=8.5, color='#555555')
    
    # Card 2 (Bottom Right): Low Threshold
    m5 = panel_cfg["blocks"][5]
    m6 = panel_cfg["blocks"][6]
    m7 = panel_cfg["blocks"][7]
    m8 = panel_cfg["blocks"][8]
    
    v5 = format_metric(resolve_val(results_data, m5["value"]["path"]), m5["value"]["format"])
    v6 = format_metric(resolve_val(results_data, m6["value"]["path"]), m6["value"]["format"])
    v7 = format_metric(resolve_val(results_data, m7["value"]["path"]), m7["value"]["format"])
    v8 = format_metric(resolve_val(results_data, m8["value"]["path"]), m8["value"]["format"])
    
    c2_h = mid_y - 0.085 - 0.01
    draw_card(ax, 0.47, 0.085, 0.48, c2_h, facecolor='#FFEBEE', edgecolor='#C62828')
    draw_text_block(ax, "低門檻情境 (頻繁交易、高成本)", 0.49, mid_y - 0.03, 0.44, fontsize=11, color='#C62828', weight='bold')
    
    # Col 1: Threshold
    ax.text(0.49, mid_y - 0.08, v5, fontsize=18, fontweight='bold', color='#1A1A1A', va='top', transform=ax.transAxes)
    draw_text_block(ax, m5["label"], 0.49, mid_y - 0.125, 0.14, fontsize=8.5, color='#555555')
    draw_text_block(ax, f"({m5['note']})", 0.49, mid_y - 0.165, 0.14, fontsize=7.5, color='#C62828')
    
    # Col 2: Turnover range
    turnover_range = f"{v6.replace(' 倍', '')} ~ {v7}"
    ax.text(0.64, mid_y - 0.08, turnover_range, fontsize=18, fontweight='bold', color='#1A1A1A', va='top', transform=ax.transAxes)
    draw_text_block(ax, "年化換手率範圍", 0.64, mid_y - 0.125, 0.15, fontsize=8.5, color='#555555')
    draw_text_block(ax, "多抓到的反轉次數\n最後付給了成本", 0.64, mid_y - 0.165, 0.15, fontsize=7.5, color='#777777')
    
    # Col 3: Sharpe drop
    ax.text(0.81, mid_y - 0.08, v8, fontsize=20, fontweight='bold', color='#C62828', va='top', transform=ax.transAxes)
    draw_text_block(ax, m8["label"], 0.81, mid_y - 0.125, 0.13, fontsize=8.5, color='#555555')
    draw_text_block(ax, "超額利潤被稀釋", 0.81, mid_y - 0.165, 0.13, fontsize=7.5, color='#777777')
    
    plt.savefig(out_path, bbox_inches='tight', dpi=150)
    plt.close()

def render_panel_honesty(results_data, robustness_data, panel_cfg, out_path, sources_list):
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')
    
    title = panel_cfg["title"]
    subtitle = panel_cfg["alt"]
    sub_y = draw_header_and_footer(ax, title, subtitle, sources_list)
    
    body_start_y = sub_y - 0.03
    
    # Left Hero Card: p-value
    m1 = panel_cfg["blocks"][0]
    c1 = panel_cfg["blocks"][1]
    
    v1 = format_metric(resolve_val(robustness_data, m1["value"]["path"]), m1["value"]["format"])
    c1_txt = format_block_text(c1, results_data, robustness_data)
    
    draw_card(ax, 0.05, 0.085, 0.42, body_start_y - 0.085, facecolor='#FFEBEE', edgecolor='#C62828')
    draw_text_block(ax, "關鍵統計檢定結果", 0.07, body_start_y - 0.03, 0.38, fontsize=12, color='#C62828', weight='bold')
    ax.text(0.07, body_start_y - 0.08, v1, fontsize=54, fontweight='bold', color='#C62828', ha='left', va='top', transform=ax.transAxes)
    draw_text_block(ax, m1["label"], 0.07, body_start_y - 0.21, 0.38, fontsize=10, color='#555555')
    draw_text_block(ax, f"({m1['note']})", 0.07, body_start_y - 0.245, 0.38, fontsize=9.5, color='#C62828', weight='bold')
    draw_text_block(ax, c1_txt, 0.07, body_start_y - 0.29, 0.38, fontsize=10, color='#555555', line_spacing=1.3)
    
    # Right Column
    # Section 1: Overoptimism
    m2 = panel_cfg["blocks"][2]
    c2 = panel_cfg["blocks"][3]
    v2 = format_metric(resolve_val(results_data, m2["value"]["path"]), m2["value"]["format"])
    c2_txt = format_block_text(c2, results_data, robustness_data)
    
    draw_text_block(ax, f"1. {m2['label']}: {v2}", 0.51, body_start_y - 0.01, 0.44, fontsize=11, color='#1A1A1A', weight='bold')
    draw_text_block(ax, f"({m2['note']})", 0.51, body_start_y - 0.045, 0.44, fontsize=8.5, color='#777777')
    draw_text_block(ax, c2_txt, 0.51, body_start_y - 0.08, 0.44, fontsize=9.5, color='#555555', line_spacing=1.2)
    
    # Section 2: Cost
    m3 = panel_cfg["blocks"][4]
    v3 = format_metric(resolve_val(results_data, m3["value"]["path"]), m3["value"]["format"])
    
    draw_text_block(ax, f"2. {m3['label']}: {v3}", 0.51, body_start_y - 0.17, 0.44, fontsize=11, color='#1A1A1A', weight='bold')
    draw_text_block(ax, f"({m3['note']})", 0.51, body_start_y - 0.205, 0.44, fontsize=8.5, color='#777777')
    draw_text_block(ax, "回測僅計算了美股一腿的交易成本，實際交易涉及股票與黃金雙邊，成本被低估了大約一倍。扣除真實交易成本後，策略的表現會更低落。", 0.51, body_start_y - 0.24, 0.44, fontsize=9.5, color='#555555', line_spacing=1.2)
    
    # Section 3: Takeaways
    c4 = panel_cfg["blocks"][5]
    c4_txt = format_block_text(c4, results_data, robustness_data)
    
    c4_y = body_start_y - 0.35
    c4_h = c4_y - 0.085
    draw_card(ax, 0.51, 0.085, 0.44, c4_h, facecolor='#F0F4F8', edgecolor='none')
    draw_text_block(ax, "💡 " + c4["heading"], 0.53, c4_y - 0.02, 0.40, fontsize=11, color='#1F4E79', weight='bold')
    draw_text_block(ax, c4_txt, 0.53, c4_y - 0.065, 0.40, fontsize=9.5, color='#555555', line_spacing=1.3)
    
    plt.savefig(out_path, bbox_inches='tight', dpi=150)
    plt.close()

def main():
    results_json_path = "/Users/yhlai0911/volpred-research/experiments/k698/k698_results.json"
    robustness_json_path = "/Users/yhlai0911/volpred-research/experiments/k699/k699_results.json"
    plan_json_path = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_fa098fc8/runs/lazypack-mile_fa098fc8-r3/plan.json"
    out_dir = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_fa098fc8/runs/lazypack-mile_fa098fc8-r3/panels"
    
    os.makedirs(out_dir, exist_ok=True)
    
    with open(results_json_path, "r", encoding="utf-8") as f:
        results_data = json.load(f)
    with open(robustness_json_path, "r", encoding="utf-8") as f:
        robustness_data = json.load(f)
    with open(plan_json_path, "r", encoding="utf-8") as f:
        plan = json.load(f)
        
    results_label = plan["evidence"]["results"]["label"]
    robustness_label = plan["evidence"]["robustness"]["label"]
    
    panels = plan["panels"]
    for panel in panels:
        name = panel["name"]
        out_path = os.path.join(out_dir, f"{name}.png")
        
        # Determine strict list of sources used in the panel based on config
        sources_list = []
        for src in panel["sources"]:
            if src == "results":
                sources_list.append(results_label)
            elif src == "robustness":
                sources_list.append(robustness_label)
        
        if name == "panel_signal":
            render_panel_signal(results_data, robustness_data, panel, out_path, sources_list)
        elif name == "panel_result":
            render_panel_result(results_data, robustness_data, panel, out_path, sources_list)
        elif name == "panel_turnover":
            render_panel_turnover(results_data, robustness_data, panel, out_path, sources_list)
        elif name == "panel_honesty":
            render_panel_honesty(results_data, robustness_data, panel, out_path, sources_list)
        else:
            raise ValueError(f"Unknown panel name: {name}")
            
        print(f"Rendered: {out_path}")

if __name__ == "__main__":
    main()
