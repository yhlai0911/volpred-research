#!/usr/bin/env python3
import os
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Hardcoded absolute paths
EVIDENCE_PATH = "/Users/yhlai0911/volpred-research/storage/experiments/midterm_vix_event_study.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_b222a5d7/runs/lazypack-mile_b222a5d7/panels"

# Configure matplotlib for rendering Chinese characters and correct minus sign
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

def wrap_chinese_text(text, max_char_width):
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append("")
            continue
        current_line = []
        current_width = 0.0
        for char in paragraph:
            char_width = 1.0 if ord(char) > 127 else 0.55
            if current_width + char_width > max_char_width:
                lines.append("".join(current_line))
                current_line = [char]
                current_width = char_width
            else:
                current_line.append(char)
                current_width += char_width
        if current_line:
            lines.append("".join(current_line))
    return "\n".join(lines)

def resolve_path(data, path):
    parts = [p for p in path.split('/') if p]
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Key '{part}' not found in path '{path}'")
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Index '{part}' out of range or invalid for path '{path}'") from e
        else:
            raise KeyError(f"Cannot traverse '{part}' in '{current}' for path '{path}'")
    return current

def format_value(value, fmt_cfg):
    try:
        val_float = float(value)
    except (ValueError, TypeError):
        return str(value)
    
    digits = fmt_cfg.get("digits", 0)
    suffix = fmt_cfg.get("suffix", "")
    show_plus = fmt_cfg.get("show_plus", False)
    
    if show_plus:
        fmt_str = f"{{:+.{digits}f}}"
    else:
        fmt_str = f"{{:.{digits}f}}"
        
    return fmt_str.format(val_float) + suffix

def draw_card(ax, x1, y1, w, h, bg_color='#F8F9FA', border_color='#E5E9EF', border_width=1.0):
    pad = 0.005
    rounding_size = 0.01
    rect = patches.FancyBboxPatch(
        (x1 + pad, y1 + pad), w - 2*pad, h - 2*pad,
        boxstyle=f"round,pad={pad},rounding_size={rounding_size}",
        facecolor=bg_color,
        edgecolor=border_color,
        linewidth=border_width,
        transform=ax.transAxes,
        clip_on=False
    )
    ax.add_patch(rect)

def draw_header(ax, title, subtitle, badge_text="VolPred 懶人包"):
    # Badge
    badge_rect = patches.FancyBboxPatch(
        (0.06, 0.935), 0.12, 0.025,
        boxstyle="round,pad=0.002,rounding_size=0.005",
        facecolor='#235A97',
        edgecolor='none',
        transform=ax.transAxes,
        clip_on=False
    )
    ax.add_patch(badge_rect)
    ax.text(0.12, 0.947, badge_text, color='#FFFFFF', fontsize=9.5, fontweight='bold',
            va='center', ha='center', transform=ax.transAxes)
    
    # Title
    ax.text(0.06, 0.88, title, fontsize=22, fontweight='bold', color='#17202A',
            va='bottom', ha='left', transform=ax.transAxes)
    
    # Subtitle
    ax.text(0.06, 0.83, subtitle, fontsize=12.5, color='#5A6472',
            va='bottom', ha='left', transform=ax.transAxes)

def draw_footer(ax):
    # Divider line
    ax.plot([0.06, 0.94], [0.09, 0.09], color='#E5E9EF', linewidth=1.0, transform=ax.transAxes)
    
    # Footer text
    footer_text = "資料來源：六次期中選舉 VIX 事件研究（yfinance ^VIX/^GSPC）"
    ax.text(0.06, 0.05, footer_text, fontsize=9.5, color='#8792A0',
            va='center', ha='left', transform=ax.transAxes)

def make_concept_panel(data, out_path):
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    title = "市場流傳的劇本，跟資料對不上"
    subtitle = "說明選舉季波動率套路的假設與實際資料的落差"
    draw_header(ax, title, subtitle)
    
    # Card 1: 劇本怎麼講 (left column, top)
    draw_card(ax, 0.06, 0.48, 0.41, 0.30, bg_color='#FDEDEC', border_color='#FADBD8')
    ax.text(0.085, 0.74, "劇本怎麼講", fontsize=15, fontweight='bold', color='#C83E3A',
            va='top', ha='left', transform=ax.transAxes)
    body_1 = wrap_chinese_text("選舉結果不確定，大家搶著買保護，恐慌指數被推高；開票後答案揭曉，保護不再需要，指數一夜塌下來。所以選前買、選後賣。", 22)
    ax.text(0.085, 0.69, body_1, fontsize=12, color='#17202A',
            va='top', ha='left', linespacing=1.4, transform=ax.transAxes)
    
    # Card 2: 資料怎麼講 (left column, bottom)
    draw_card(ax, 0.06, 0.14, 0.41, 0.30, bg_color='#E8F8F5', border_color='#D1F2EB')
    ax.text(0.085, 0.40, "資料怎麼講", fontsize=15, fontweight='bold', color='#177C7D',
            va='top', ha='left', transform=ax.transAxes)
    body_2 = wrap_chinese_text("恐慌指數的高點落在投票日前約三到四週，之後一路往下滑到投票日。最大的一段下滑，發生在開票之前。", 22)
    ax.text(0.085, 0.35, body_2, fontsize=12, color='#17202A',
            va='top', ha='left', linespacing=1.4, transform=ax.transAxes)
    
    # Metric 1 Card (right column, top)
    draw_card(ax, 0.53, 0.48, 0.41, 0.30, bg_color='#F8F9FA', border_color='#E5E9EF')
    val_1 = resolve_path(data, "/path_normalized/-18/median")
    fmt_val_1 = format_value(val_1, {"kind": "number", "digits": 1})
    lbl_1 = wrap_chinese_text("選前十八個交易日的 VIX（選前一日標準化為百，中位數）", 20)
    ax.text(0.555, 0.74, lbl_1, fontsize=11.5, fontweight='bold', color='#5A6472',
            va='top', ha='left', linespacing=1.3, transform=ax.transAxes)
    ax.text(0.555, 0.58, fmt_val_1, fontsize=42, fontweight='bold', color='#17202A',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.555, 0.50, "已對齊事件日標準化", fontsize=10.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)
            
    # Metric 2 Card (right column, bottom)
    draw_card(ax, 0.53, 0.14, 0.41, 0.30, bg_color='#F8F9FA', border_color='#E5E9EF')
    val_2 = resolve_path(data, "/path_normalized/-18/n_above_100")
    fmt_val_2 = format_value(val_2, {"kind": "number", "digits": 0, "suffix": " 次"})
    lbl_2 = wrap_chinese_text("同一時點高於選前一日水準的次數", 20)
    ax.text(0.555, 0.40, lbl_2, fontsize=11.5, fontweight='bold', color='#5A6472',
            va='top', ha='left', linespacing=1.3, transform=ax.transAxes)
    ax.text(0.555, 0.24, fmt_val_2, fontsize=42, fontweight='bold', color='#17202A',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.555, 0.16, "樣本共六次選舉", fontsize=10.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)
            
    draw_footer(ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#FFFFFF')
    plt.close()

def make_results_panel(data, out_path):
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    title = "開票隔天確實會掉，但只掉這麼多"
    subtitle = "選後隔日 VIX 變化的平均、中位數與統計檢定結果"
    draw_header(ax, title, subtitle)
    
    # Left Column 2x2 Grid
    # Metric 1 (Top-Left)
    draw_card(ax, 0.06, 0.46, 0.23, 0.30)
    val_1 = resolve_path(data, "/stats/mean_crush_pct")
    fmt_val_1 = format_value(val_1, {"kind": "number", "digits": 1, "suffix": "%", "show_plus": True})
    lbl_1 = wrap_chinese_text("開票隔天 VIX 平均變化", 11)
    ax.text(0.08, 0.73, lbl_1, fontsize=10.5, fontweight='bold', color='#5A6472',
            va='top', ha='left', linespacing=1.3, transform=ax.transAxes)
    ax.text(0.08, 0.58, fmt_val_1, fontsize=32, fontweight='bold', color='#17202A',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.08, 0.48, "中位數見下", fontsize=9.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)
            
    # Metric 2 (Top-Right)
    draw_card(ax, 0.31, 0.46, 0.23, 0.30)
    val_2 = resolve_path(data, "/stats/median_crush_pct")
    fmt_val_2 = format_value(val_2, {"kind": "number", "digits": 1, "suffix": "%", "show_plus": True})
    lbl_2 = wrap_chinese_text("開票隔天 VIX 變化中位數", 11)
    ax.text(0.33, 0.73, lbl_2, fontsize=10.5, fontweight='bold', color='#5A6472',
            va='top', ha='left', linespacing=1.3, transform=ax.transAxes)
    ax.text(0.33, 0.58, fmt_val_2, fontsize=32, fontweight='bold', color='#17202A',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.33, 0.48, "平均被單一極端年份拉低", fontsize=9.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)

    # Metric 3 (Bottom-Left)
    draw_card(ax, 0.06, 0.14, 0.23, 0.30)
    val_3 = resolve_path(data, "/stats/n_negative")
    fmt_val_3 = format_value(val_3, {"kind": "number", "digits": 0, "suffix": " 次"})
    lbl_3 = wrap_chinese_text("六次裡下跌的次數", 11)
    ax.text(0.08, 0.41, lbl_3, fontsize=10.5, fontweight='bold', color='#5A6472',
            va='top', ha='left', linespacing=1.3, transform=ax.transAxes)
    ax.text(0.08, 0.26, fmt_val_3, fontsize=32, fontweight='bold', color='#17202A',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.08, 0.16, "唯一例外的那次反而上漲", fontsize=9.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)

    # Metric 4 (Bottom-Right)
    draw_card(ax, 0.31, 0.14, 0.23, 0.30)
    val_4 = resolve_path(data, "/stats/bootstrap_p_one_sided")
    fmt_val_4 = format_value(val_4, {"kind": "number", "digits": 3})
    lbl_4 = wrap_chinese_text("隨機抽到同樣結果的機率", 11)
    ax.text(0.33, 0.41, lbl_4, fontsize=10.5, fontweight='bold', color='#5A6472',
            va='top', ha='left', linespacing=1.3, transform=ax.transAxes)
    ax.text(0.33, 0.26, fmt_val_4, fontsize=32, fontweight='bold', color='#17202A',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.33, 0.16, wrap_chinese_text("對照全樣本交易日重抽兩萬次，達統計顯著門檻", 11), fontsize=9, color='#8792A0',
            va='bottom', ha='left', linespacing=1.3, transform=ax.transAxes)

    # Right Column Editorial Text Card
    draw_card(ax, 0.58, 0.14, 0.36, 0.62, bg_color='#F8F9FA', border_color='#E5E9EF')
    # Accent line at top
    ax.plot([0.58, 0.94], [0.76, 0.76], color='#C83E3A', linewidth=4, solid_capstyle='butt', transform=ax.transAxes)
    ax.text(0.605, 0.71, "顯著不等於好賺", fontsize=16, fontweight='bold', color='#C83E3A',
            va='top', ha='left', transform=ax.transAxes)
    body_text = wrap_chinese_text("把幅度最大的那次極端值拿掉，剩下幾次的平均只剩個位數的零頭。扣掉選擇權買賣價差與每天付出去的時間價值，這點空間大概就沒了。", 18)
    ax.text(0.605, 0.65, body_text, fontsize=12.5, color='#17202A',
            va='top', ha='left', linespacing=1.4, transform=ax.transAxes)

    draw_footer(ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#FFFFFF')
    plt.close()

def make_takeaway_panel(data, out_path):
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    title = "賣方的利潤，在最想賣的時候消失"
    subtitle = "隱含與已實現波動價差的分佈，以及目前市場位置"
    draw_header(ax, title, subtitle)
    
    # --- Column 1: Left Column ---
    # Metric 1 (Top)
    draw_card(ax, 0.06, 0.56, 0.41, 0.21)
    val_1 = resolve_path(data, "/stats/mean_iv_rv_spread_post")
    fmt_val_1 = format_value(val_1, {"kind": "number", "digits": 1, "show_plus": True})
    lbl_1 = wrap_chinese_text("選前 VIX 減選後二十日實現波動（六次平均）", 20)
    ax.text(0.085, 0.75, lbl_1, fontsize=11, fontweight='bold', color='#5A6472',
            va='top', ha='left', linespacing=1.3, transform=ax.transAxes)
    ax.text(0.085, 0.65, fmt_val_1, fontsize=32, fontweight='bold', color='#177C7D',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.085, 0.58, "波動度口徑價差，非學術定義的變異數風險溢酬", fontsize=9.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)

    # Metric 2 (Middle)
    draw_card(ax, 0.06, 0.36, 0.41, 0.17)
    val_2 = resolve_path(data, "/events/5/iv_rv_spread_post")
    fmt_val_2 = format_value(val_2, {"kind": "number", "digits": 1, "show_plus": True})
    lbl_2 = "最近一次期中選舉的同一價差"
    ax.text(0.085, 0.515, lbl_2, fontsize=11, fontweight='bold', color='#5A6472',
            va='top', ha='left', transform=ax.transAxes)
    ax.text(0.085, 0.44, fmt_val_2, fontsize=32, fontweight='bold', color='#C83E3A',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.085, 0.375, "選前 VIX 最貴的那幾次，賣方反而倒賠", fontsize=9.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)

    # Text Block 1 (Bottom)
    draw_card(ax, 0.06, 0.14, 0.41, 0.19, bg_color='#FDEDEC', border_color='#FADBD8')
    ax.text(0.085, 0.31, "虧的是哪幾次", fontsize=13.5, fontweight='bold', color='#C83E3A',
            va='top', ha='left', transform=ax.transAxes)
    body_text_1 = wrap_chinese_text("正好是選前恐慌指數被墊得最高、劇本喊快賣喊得最大聲的那幾次。賣方以為在收保費，結果選後走出來的波動比報價還兇。", 22)
    ax.text(0.085, 0.27, body_text_1, fontsize=11, color='#17202A',
            va='top', ha='left', linespacing=1.35, transform=ax.transAxes)

    # --- Column 2: Right Column ---
    # Metric 3 (Top)
    draw_card(ax, 0.53, 0.56, 0.41, 0.21)
    val_3 = resolve_path(data, "/current/vix_now")
    fmt_val_3 = format_value(val_3, {"kind": "number", "digits": 2})
    lbl_3 = "目前 VIX"
    ax.text(0.555, 0.75, lbl_3, fontsize=11, fontweight='bold', color='#5A6472',
            va='top', ha='left', transform=ax.transAxes)
    ax.text(0.555, 0.65, fmt_val_3, fontsize=32, fontweight='bold', color='#235A97',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.555, 0.58, "距投票日尚有一段時間", fontsize=9.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)

    # Metric 4 (Middle)
    draw_card(ax, 0.53, 0.36, 0.41, 0.17)
    val_4 = resolve_path(data, "/current/hist_vix_at_same_horizon_mean")
    fmt_val_4 = format_value(val_4, {"kind": "number", "digits": 1})
    lbl_4 = "六次選舉在同一時點的 VIX 平均"
    ax.text(0.555, 0.515, lbl_4, fontsize=11, fontweight='bold', color='#5A6472',
            va='top', ha='left', transform=ax.transAxes)
    ax.text(0.555, 0.44, fmt_val_4, fontsize=32, fontweight='bold', color='#17202A',
            va='center', ha='left', transform=ax.transAxes)
    ax.text(0.555, 0.375, "目前讀數落在歷史區間中段", fontsize=9.5, color='#8792A0',
            va='bottom', ha='left', transform=ax.transAxes)

    # Text Block 2 (Bottom)
    draw_card(ax, 0.53, 0.14, 0.41, 0.19, bg_color='#DFEAF7', border_color='#D4E6F1')
    ax.text(0.555, 0.31, "所以要盯什麼", fontsize=13.5, fontweight='bold', color='#235A97',
            va='top', ha='left', transform=ax.transAxes)
    body_text_2 = wrap_chinese_text("盯投票前一個月的股市走勢，不是選舉日曆。近兩次選舉的波動率是被市場自己的下跌推上去的，選舉只是剛好排在後面。", 22)
    ax.text(0.555, 0.27, body_text_2, fontsize=11, color='#17202A',
            va='top', ha='left', linespacing=1.35, transform=ax.transAxes)

    draw_footer(ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#FFFFFF')
    plt.close()

def main():
    # Load evidence package
    if not os.path.exists(EVIDENCE_PATH):
        raise FileNotFoundError(f"Evidence file not found: {EVIDENCE_PATH}")
        
    with open(EVIDENCE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Render all panels
    make_concept_panel(data, os.path.join(OUT_DIR, "1_concept.png"))
    make_results_panel(data, os.path.join(OUT_DIR, "2_results.png"))
    make_takeaway_panel(data, os.path.join(OUT_DIR, "3_takeaway.png"))
    
    print("All panels rendered successfully.")

if __name__ == "__main__":
    main()
