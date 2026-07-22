#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VolPred 懶人包圖組渲染程式 (mile_a73bb294)
此程式讀取檢定結果數據並為 "mile_a73bb294" 文章生成一組懶人包圖組。
"""

import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# 絕對路徑設定
RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1348/k1348_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_a73bb294/runs/lazypack-mile_a73bb294/panels"

# 設定字型
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

def get_by_path(data, path):
    keys = path.split('.')
    curr = data
    for key in keys:
        if isinstance(curr, dict):
            if key not in curr:
                raise KeyError(f"在結果 JSON 中找不到鍵值 '{key}' (路徑: {path})")
            curr = curr[key]
        elif isinstance(curr, list):
            try:
                curr = curr[int(key)]
            except (ValueError, IndexError) as e:
                raise KeyError(f"列表索引 '{key}' 無效 (路徑: {path})") from e
        else:
            raise KeyError(f"無法在 {type(curr).__name__} 類型上繼續解析 '{key}' (路徑: {path})")
    return curr

def format_val(val, fmt_config):
    kind = fmt_config.get("kind", "number")
    digits = fmt_config.get("digits")
    show_plus = fmt_config.get("show_plus", False)
    suffix = fmt_config.get("suffix", "")
    
    if kind == "integer":
        formatted = f"{int(val)}"
    else: # number
        if digits is not None:
            if show_plus and val > 0:
                formatted = f"+{val:.{digits}f}"
            else:
                formatted = f"{val:.{digits}f}"
        else:
            if show_plus and val > 0:
                formatted = f"+{val}"
            else:
                formatted = f"{val}"
    return formatted + suffix

def wrap_chinese_text(text, max_chars=20):
    paragraphs = text.split('\n')
    wrapped_paragraphs = []
    for para in paragraphs:
        if not para:
            wrapped_paragraphs.append("")
            continue
        lines = []
        cur_line = []
        cur_len = 0
        for char in para:
            cur_line.append(char)
            if ord(char) > 127:
                cur_len += 1
            else:
                cur_len += 0.5
            if cur_len >= max_chars:
                lines.append("".join(cur_line))
                cur_line = []
                cur_len = 0
        if cur_line:
            lines.append("".join(cur_line))
        wrapped_paragraphs.append("\n".join(lines))
    return "\n".join(wrapped_paragraphs)

def draw_rounded_rect(ax, x1, y1, x2, y2, fc='#FFFFFF', ec='#E9ECEF', lw=1, radius=0.02):
    box = patches.FancyBboxPatch(
        (x1 + radius, y1 + radius), 
        (x2 - x1 - 2*radius), 
        (y2 - y1 - 2*radius),
        boxstyle=f"round,pad={radius}",
        fc=fc, ec=ec, lw=lw,
        transform=ax.transAxes,
        zorder=1
    )
    ax.add_patch(box)

def render_panel_1(results_data):
    # Panel 1 — 1_concept.png
    n_obs = get_by_path(results_data, "tier2.panel_regression.log_volume.n_obs")
    n_obs_str = format_val(n_obs, {"kind": "integer", "suffix": " 筆"})
    
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    
    # 畫深色標題列 (Professional 風格)
    header_rect = patches.Rectangle((0, 0.80), 1, 0.20, fc='#1A365D', transform=ax.transAxes, zorder=1)
    ax.add_patch(header_rect)
    
    # 標題與副標題
    ax.text(0.05, 0.91, "季末調倉在做什麼", color='#FFFFFF', fontsize=26, fontweight='bold', va='center', ha='left', transform=ax.transAxes, zorder=2)
    sub_text = wrap_chinese_text("概念說明：指數成分調整期間 ETF 需要同步調倉，交易集中在季末幾天", 45)
    ax.text(0.05, 0.84, sub_text, color='#E2E8F0', fontsize=12, va='center', ha='left', transform=ax.transAxes, zorder=2)
    
    # 左側內容
    ax.text(0.05, 0.70, "為什麼會集中在那幾天", color='#2D3748', fontsize=18, fontweight='bold', va='top', ha='left', transform=ax.transAxes, zorder=2)
    body_text = (
        "追蹤指數的 ETF 必須在成分調整生效時同步跟上，買賣因此擠在季末的窗口裡。\n\n"
        "常見的直覺是：交易量一擠，價格就會跟著晃。這篇檢定的就是這句直覺。"
    )
    wrapped_body = wrap_chinese_text(body_text, 24)
    ax.text(0.05, 0.62, wrapped_body, color='#4A5568', fontsize=14, va='top', ha='left', transform=ax.transAxes, zorder=2, linespacing=1.6)
    
    # 右側數據卡片
    draw_rounded_rect(ax, 0.60, 0.18, 0.95, 0.74, fc='#F7FAFC', ec='#E2E8F0', lw=1, radius=0.02)
    
    wrapped_label = wrap_chinese_text("納入檢定的股票日觀測數", 10)
    ax.text(0.775, 0.62, wrapped_label, color='#4A5568', fontsize=15, fontweight='bold', va='center', ha='center', transform=ax.transAxes, zorder=2)
    ax.text(0.775, 0.46, n_obs_str, color='#1A365D', fontsize=36, fontweight='bold', va='center', ha='center', transform=ax.transAxes, zorder=2)
    ax.text(0.775, 0.28, "12 年多美股日線數據全樣本檢定", color='#718096', fontsize=11, va='center', ha='center', transform=ax.transAxes, zorder=2)
    
    # 底部
    ax.plot([0.05, 0.95], [0.10, 0.10], color='#E2E8F0', lw=1, transform=ax.transAxes, zorder=2)
    ax.text(0.05, 0.06, "資料來源：季末 ETF 調倉對成分股量能與波動的檢定結果", color='#718096', fontsize=10, va='center', ha='left', transform=ax.transAxes, zorder=2)
    
    out_path = os.path.join(OUT_DIR, "1_concept.png")
    plt.savefig(out_path, dpi=150, bbox_inches=None, facecolor='#FFFFFF')
    plt.close()

def render_panel_2(results_data):
    # Panel 2 — 2_results.png
    val1 = get_by_path(results_data, "verdict_summary_per_etf.IVV.log_volume_diff")
    val1_str = format_val(val1, {"kind": "number", "digits": 3, "show_plus": True})
    
    val2 = get_by_path(results_data, "tier2.panel_regression.log_volume.quarter_end_t")
    val2_str = format_val(val2, {"kind": "number", "digits": 2, "show_plus": True})
    
    val3 = get_by_path(results_data, "verdict_summary_per_etf.IVV.log_volume_t")
    val3_str = format_val(val3, {"kind": "number", "digits": 2, "show_plus": True})
    
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    
    # 標題與副標題
    ax.text(0.05, 0.90, "量能確實跳起來了", color='#1A365D', fontsize=26, fontweight='bold', va='center', ha='left', transform=ax.transAxes, zorder=2)
    sub_text = wrap_chinese_text("全樣本迴歸顯示季末成交量顯著擴張，統計強度明確", 45)
    ax.text(0.05, 0.83, sub_text, color='#4A5568', fontsize=12, va='center', ha='left', transform=ax.transAxes, zorder=2)
    
    # Bento Grid 佈局
    # 左側大卡片
    draw_rounded_rect(ax, 0.05, 0.18, 0.50, 0.75, fc='#EBF8FF', ec='#BEE3F8', lw=1, radius=0.02)
    label1 = "量能擴張最明確的一檔\n季末比平常多出的交易量（對數）"
    ax.text(0.09, 0.68, label1, color='#2B6CB0', fontsize=15, fontweight='bold', va='top', ha='left', transform=ax.transAxes, zorder=2, linespacing=1.4)
    ax.text(0.09, 0.44, val1_str, color='#2B6CB0', fontsize=60, fontweight='bold', va='center', ha='left', transform=ax.transAxes, zorder=2)
    desc1 = "此標的為 IVV (S&P 500 ETF)\n顯示該基金在季末有極顯著的調倉交易量"
    ax.text(0.09, 0.24, desc1, color='#4A5568', fontsize=11, va='bottom', ha='left', transform=ax.transAxes, zorder=2, linespacing=1.4)
    
    # 右上卡片
    draw_rounded_rect(ax, 0.54, 0.48, 0.95, 0.75, fc='#F7FAFC', ec='#E2E8F0', lw=1, radius=0.02)
    label2 = "量能擴張的統計強度\n(全樣本 t值)"
    ax.text(0.57, 0.67, label2, color='#4A5568', fontsize=11, fontweight='bold', va='center', ha='left', transform=ax.transAxes, zorder=2)
    ax.text(0.57, 0.55, val2_str, color='#2D3748', fontsize=34, fontweight='bold', va='center', ha='left', transform=ax.transAxes, zorder=2)
    
    # 右下卡片
    draw_rounded_rect(ax, 0.54, 0.18, 0.95, 0.45, fc='#F7FAFC', ec='#E2E8F0', lw=1, radius=0.02)
    label3 = "量能擴張最明確的一檔\n的統計強度 (IVV t值)"
    ax.text(0.57, 0.37, label3, color='#4A5568', fontsize=11, fontweight='bold', va='center', ha='left', transform=ax.transAxes, zorder=2)
    ax.text(0.57, 0.25, val3_str, color='#2D3748', fontsize=34, fontweight='bold', va='center', ha='left', transform=ax.transAxes, zorder=2)
    
    # 底部
    ax.plot([0.05, 0.95], [0.10, 0.10], color='#E2E8F0', lw=1, transform=ax.transAxes, zorder=2)
    ax.text(0.05, 0.06, "資料來源：季末 ETF 調倉對成分股量能與波動的檢定結果", color='#718096', fontsize=10, va='center', ha='left', transform=ax.transAxes, zorder=2)
    
    out_path = os.path.join(OUT_DIR, "2_results.png")
    plt.savefig(out_path, dpi=150, bbox_inches=None, facecolor='#FFFFFF')
    plt.close()

def render_panel_3(results_data):
    # Panel 3 — 3_takeaway.png
    val1 = get_by_path(results_data, "tier2.panel_regression.range_vol.quarter_end_p")
    val1_str = format_val(val1, {"kind": "number", "digits": 2})
    
    val2 = get_by_path(results_data, "tier2.panel_regression.range_vol.quarter_end_t")
    val2_str = format_val(val2, {"kind": "number", "digits": 2, "show_plus": True})
    
    val3 = get_by_path(results_data, "tier2.panel_regression.c2c_rv.quarter_end_t")
    val3_str = format_val(val3, {"kind": "number", "digits": 2, "show_plus": True})
    
    fig, ax = plt.subplots(figsize=(10.67, 6.67), dpi=150)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    
    # 標題
    ax.text(0.05, 0.90, "但波動沒有跟著上來", color='#C53030', fontsize=26, fontweight='bold', va='center', ha='left', transform=ax.transAxes, zorder=2)
    sub_text = wrap_chinese_text("振幅波動在統計上看不出季末效應，收盤波動甚至方向相反", 45)
    ax.text(0.05, 0.83, sub_text, color='#4A5568', fontsize=12, va='center', ha='left', transform=ax.transAxes, zorder=2)
    
    # 左側：Editorial 雜誌風指標列表
    draw_rounded_rect(ax, 0.05, 0.18, 0.50, 0.75, fc='#FFFFFF', ec='#E2E8F0', lw=1, radius=0.02)
    ax.plot([0.05, 0.05], [0.18, 0.75], color='#C53030', lw=4, transform=ax.transAxes, zorder=3)
    
    # 指報 1
    ax.text(0.09, 0.68, "振幅波動統計強度 (t值)", color='#4A5568', fontsize=12, va='center', ha='left', transform=ax.transAxes, zorder=2)
    ax.text(0.46, 0.68, val2_str, color='#718096', fontsize=22, fontweight='bold', va='center', ha='right', transform=ax.transAxes, zorder=2)
    ax.plot([0.09, 0.46], [0.62, 0.62], color='#E2E8F0', lw=1, transform=ax.transAxes, zorder=2)
    
    # 指標 2
    ax.text(0.09, 0.53, "振幅波動顯著性水準 (p值)", color='#4A5568', fontsize=12, va='center', ha='left', transform=ax.transAxes, zorder=2)
    ax.text(0.46, 0.53, val1_str, color='#718096', fontsize=22, fontweight='bold', va='center', ha='right', transform=ax.transAxes, zorder=2)
    ax.plot([0.09, 0.46], [0.47, 0.47], color='#E2E8F0', lw=1, transform=ax.transAxes, zorder=2)
    
    # 指標 3
    ax.text(0.09, 0.38, "收盤波動統計強度 (t值)", color='#4A5568', fontsize=12, va='center', ha='left', transform=ax.transAxes, zorder=2)
    ax.text(0.46, 0.38, val3_str, color='#C53030', fontsize=22, fontweight='bold', va='center', ha='right', transform=ax.transAxes, zorder=2)
    
    # 左側底部的說明
    ax.text(0.09, 0.24, "註：收盤波動呈現顯著負向 (t = -4.33)\n代表季末收盤到收盤波動平均而言反而變小。", color='#718096', fontsize=10, va='bottom', ha='left', transform=ax.transAxes, zorder=2, linespacing=1.4)
    
    # 右側：註解卡片
    draw_rounded_rect(ax, 0.54, 0.18, 0.95, 0.75, fc='#FFFAF0', ec='#FEEBC8', lw=1, radius=0.02)
    ax.text(0.57, 0.69, "研究邊界", color='#DD6B20', fontsize=18, fontweight='bold', va='top', ha='left', transform=ax.transAxes, zorder=2)
    
    boundary_text = (
        "資料是日頻，抓不到日內的委託流與微結構，看不見不等於不存在。\n\n"
        "本次結論屬有條件通過：量能通道成立，波動通道在這個解析度上是空結果。"
    )
    wrapped_boundary = wrap_chinese_text(boundary_text, 16)
    ax.text(0.57, 0.60, wrapped_boundary, color='#7B341E', fontsize=11, va='top', ha='left', transform=ax.transAxes, zorder=2, linespacing=1.6)
    
    # 底部
    ax.plot([0.05, 0.95], [0.10, 0.10], color='#E2E8F0', lw=1, transform=ax.transAxes, zorder=2)
    ax.text(0.05, 0.06, "資料來源：季末 ETF 調倉對成分股量能與波動的檢定結果", color='#718096', fontsize=10, va='center', ha='left', transform=ax.transAxes, zorder=2)
    
    out_path = os.path.join(OUT_DIR, "3_takeaway.png")
    plt.savefig(out_path, dpi=150, bbox_inches=None, facecolor='#FFFFFF')
    plt.close()

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results_data = json.load(f)
        
    render_panel_1(results_data)
    render_panel_2(results_data)
    render_panel_3(results_data)
    print("Done generating panels.")

if __name__ == '__main__':
    main()
