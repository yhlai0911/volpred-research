#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VolPred K698 懶人包圖組產生器
"""
import os
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from decimal import Decimal, ROUND_HALF_UP

# 1. 定義絕對路徑
K698_PATH = "/Users/yhlai0911/volpred-research/experiments/k698/k698_results.json"
K699_PATH = "/Users/yhlai0911/volpred-research/experiments/k699/k699_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_fa098fc8/runs/lazypack-mile_fa098fc8/panels"

# 2. 建立輸出目錄
os.makedirs(OUT_DIR, exist_ok=True)

# 3. 讀取數據
with open(K698_PATH, 'r', encoding='utf-8') as f:
    k698_data = json.load(f)
with open(K699_PATH, 'r', encoding='utf-8') as f:
    k699_data = json.load(f)

# 4. 解析 path 函數
def resolve_path(data, path):
    if path.startswith('/'):
        parts = [p for p in path.split('/') if p]
    else:
        parts = path.split('.')
    cur = data
    for part in parts:
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            else:
                raise KeyError(f"Key '{part}' not found in dict path '{path}'")
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Index '{part}' invalid or out of range in list path '{path}'") from exc
        else:
            raise KeyError(f"Expected dict or list at '{part}', got {type(cur).__name__} in path '{path}'")
    return cur

# 5. 數值四捨五入與格式化
def quantize_value(val, digits):
    d = Decimal(str(val))
    if digits == 0:
        q_str = '1'
    else:
        q_str = '0.' + '0' * (digits - 1) + '1'
    return d.quantize(Decimal(q_str), rounding=ROUND_HALF_UP)

def format_value(val, fmt_spec):
    kind = fmt_spec.get("kind")
    digits = fmt_spec.get("digits", 0)
    suffix = fmt_spec.get("suffix", "")
    show_plus = fmt_spec.get("show_plus", False)
    
    if kind == "percent":
        val_pct = val * 100
        q_val = quantize_value(val_pct, digits)
        sign = "+" if (show_plus and q_val > 0) else ""
        return f"{sign}{q_val}{suffix}%"
    elif kind == "number":
        q_val = quantize_value(val, digits)
        sign = "+" if (show_plus and q_val > 0) else ""
        return f"{sign}{q_val}{suffix}"
    elif kind == "integer":
        q_val = quantize_value(val, 0)
        sign = "+" if (show_plus and q_val > 0) else ""
        return f"{sign}{q_val}{suffix}"
    else:
        return str(val)

# 6. 中文換行處理
def wrap_chinese_text(text, width):
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append('')
            continue
        current_line = []
        current_len = 0
        for char in paragraph:
            current_line.append(char)
            # 中英文字元皆算長度 1
            current_len += 1
            if current_len >= width:
                lines.append(''.join(current_line))
                current_line = []
                current_len = 0
        if current_line:
            lines.append(''.join(current_line))
    return '\n'.join(lines)

# 7. 設定 matplotlib 全局字型與屬性
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# 8. Visual Helpers
def draw_card(ax, x, y, width, height, facecolor='#FFFFFF', edgecolor='#E2E8F0', linewidth=1, pad=0.15):
    rect = patches.FancyBboxPatch(
        (x + pad, y + pad), 
        width - 2*pad, 
        height - 2*pad, 
        boxstyle=f"round,pad={pad}", 
        facecolor=facecolor, 
        edgecolor=edgecolor, 
        linewidth=linewidth,
        mutation_scale=1.0
    )
    ax.add_patch(rect)

def draw_text(ax, text, x, y, fontsize, color='#0F172A', weight='normal', ha='left', va='top', wrap_width=None):
    if wrap_width:
        text = wrap_chinese_text(text, wrap_width)
    return ax.text(x, y, text, fontsize=fontsize, color=color, weight=weight, ha=ha, va=va)

def add_header(ax, title):
    # 頂部背景色 #0F172A
    rect = patches.Rectangle((0, 8.5), 16, 1.5, facecolor='#0F172A', edgecolor='none')
    ax.add_patch(rect)
    # 大標題
    draw_text(ax, title, 0.8, 9.25, fontsize=28, color='#FFFFFF', weight='bold', va='center')
    # 裝飾藍條
    decor = patches.Rectangle((0.8, 8.8), 1.5, 0.08, facecolor='#38BDF8', edgecolor='none')
    ax.add_patch(decor)

def add_footer(ax, sources):
    # 分割線
    ax.plot([0.8, 15.2], [0.8, 0.8], color='#E2E8F0', linewidth=1)
    
    # 來源標註（逐字對齊）
    source_labels = []
    for src in sources:
        if src == 'results':
            source_labels.append("experiment K698 results (contrarian tilt backtest)")
        elif src == 'robustness':
            source_labels.append("experiment K699 results (cross-period robustness and DM test)")
    source_str = "資料來源：" + "；".join(source_labels)
    draw_text(ax, source_str, 0.8, 0.5, fontsize=12, color='#94A3B8', va='center')

# ==================== PANEL 1 ====================
def draw_panel_1():
    fig, ax = plt.subplots(figsize=(10.666, 6.666), dpi=150)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    
    add_header(ax, "訊號本身確實存在")
    
    # 說明文字
    trigger_val = format_value(resolve_path(k698_data, "sensitivity_daily_threshold.12.threshold"), {"kind": "percent", "digits": 0})
    intro_text = (
        "美股前一天與隔天的走勢帶著負向關聯：跌深的隔天偏強，漲多的隔天偏弱。\n"
        f"這裡的「大漲大跌」指前一日漲跌幅超過 {trigger_val}。"
    )
    draw_text(ax, intro_text, 0.8, 7.8, fontsize=16, color='#334155', va='top')
    
    # 4個大卡片 (2x2)
    # 卡片 1 (左上)
    draw_card(ax, 0.8, 4.3, 6.8, 2.6, facecolor='#ECFDF5', edgecolor='#D1FAE5')
    draw_text(ax, "前一日大跌，隔日平均報酬（年化）", 1.2, 6.5, fontsize=15, color='#047857', weight='bold')
    down_val = format_value(resolve_path(k698_data, "autocorrelation_diagnostic.mean_ret_after_big_down_ann"), {"kind": "percent", "digits": 1, "show_plus": True})
    draw_text(ax, down_val, 1.2, 5.6, fontsize=42, color='#059669', weight='bold', va='center')
    
    # 卡片 2 (右上)
    draw_card(ax, 8.4, 4.3, 6.8, 2.6, facecolor='#FEF2F2', edgecolor='#FEE2E2')
    draw_text(ax, "前一日大漲，隔日平均報酬（年化）", 8.8, 6.5, fontsize=15, color='#B91C1C', weight='bold')
    up_val = format_value(resolve_path(k698_data, "autocorrelation_diagnostic.mean_ret_after_big_up_ann"), {"kind": "percent", "digits": 1, "show_plus": True})
    draw_text(ax, up_val, 8.8, 5.6, fontsize=42, color='#DC2626', weight='bold', va='center')
    
    # 卡片 3 (左下)
    draw_card(ax, 0.8, 1.3, 6.8, 2.6, facecolor='#F8FAFC', edgecolor='#E2E8F0')
    draw_text(ax, "隔日報酬自我相關係數", 1.2, 3.5, fontsize=15, color='#475569', weight='bold')
    acf_val = format_value(resolve_path(k698_data, "autocorrelation_diagnostic.acf_lag1"), {"kind": "number", "digits": 3})
    draw_text(ax, acf_val, 1.2, 2.7, fontsize=42, color='#1E293B', weight='bold', va='center')
    draw_text(ax, "註：負值代表隔天傾向反向走", 1.2, 1.7, fontsize=12, color='#64748B')
    
    # 卡片 4 (右下)
    draw_card(ax, 8.4, 1.3, 6.8, 2.6, facecolor='#F8FAFC', edgecolor='#E2E8F0')
    draw_text(ax, "回測交易日數", 8.8, 3.5, fontsize=15, color='#475569', weight='bold')
    n_obs_val = format_value(resolve_path(k698_data, "n_observations"), {"kind": "integer", "suffix": " 天"})
    draw_text(ax, n_obs_val, 8.8, 2.7, fontsize=42, color='#1E293B', weight='bold', va='center')
    
    add_footer(ax, ["results"])
    
    plt.savefig(os.path.join(OUT_DIR, "panel_signal.png"), dpi=150)
    plt.close()

# ==================== PANEL 2 ====================
def draw_panel_2():
    fig, ax = plt.subplots(figsize=(10.666, 6.666), dpi=150)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    
    add_header(ax, "最好的做法反而是最保守的")
    
    trigger_val = format_value(resolve_path(k698_data, "sensitivity_daily_threshold.12.threshold"), {"kind": "percent", "digits": 0})
    tilt_val = format_value(resolve_path(k698_data, "sensitivity_daily_threshold.12.tilt"), {"kind": "percent", "digits": 0})
    intro_text = (
        "固定配比：每天把股票與黃金拉回一半一半。\n"
        f"日頻逆勢傾斜：前一日漲跌超過 {trigger_val} 時，把股票比重往反方向調 {tilt_val}。"
    )
    draw_text(ax, intro_text, 0.8, 7.8, fontsize=16, color='#334155', va='top')
    
    # Bento Grid
    # 格子 A (左上)
    draw_card(ax, 0.8, 4.3, 6.8, 3.0, facecolor='#F0F9FF', edgecolor='#BAE6FD')
    draw_text(ax, "風險調整後分數 (Sharpe Net)", 1.2, 6.9, fontsize=15, color='#0369A1', weight='bold')
    
    draw_text(ax, "逆勢傾斜", 1.2, 6.1, fontsize=13, color='#64748B')
    sharpe_tilt = format_value(resolve_path(k698_data, "strategies.1.sharpe_net"), {"kind": "number", "digits": 3})
    draw_text(ax, sharpe_tilt, 1.2, 5.1, fontsize=36, color='#0284C7', weight='bold')
    
    draw_text(ax, "固定配比", 4.4, 6.1, fontsize=13, color='#64748B')
    sharpe_static = format_value(resolve_path(k698_data, "strategies.0.sharpe_net"), {"kind": "number", "digits": 3})
    draw_text(ax, sharpe_static, 4.4, 5.1, fontsize=36, color='#64748B', weight='bold')
    
    # 格子 B (右上)
    draw_card(ax, 8.4, 4.3, 6.8, 3.0, facecolor='#FEF2F2', edgecolor='#FEE2E2')
    draw_text(ax, "最大回撤 (Max Drawdown Net)", 8.8, 6.9, fontsize=15, color='#991B1B', weight='bold')
    
    draw_text(ax, "逆勢傾斜", 8.8, 6.1, fontsize=13, color='#64748B')
    max_dd_tilt = format_value(resolve_path(k698_data, "strategies.1.max_dd_net"), {"kind": "percent", "digits": 1})
    draw_text(ax, max_dd_tilt, 8.8, 5.1, fontsize=36, color='#DC2626', weight='bold')
    
    draw_text(ax, "固定配比", 12.0, 6.1, fontsize=13, color='#64748B')
    max_dd_static = format_value(resolve_path(k698_data, "strategies.0.max_dd_net"), {"kind": "percent", "digits": 1})
    draw_text(ax, max_dd_static, 12.0, 5.1, fontsize=36, color='#64748B', weight='bold')
    
    # 格子 C (左下)
    draw_card(ax, 0.8, 1.3, 5.0, 2.6, facecolor='#F8FAFC', edgecolor='#E2E8F0')
    draw_text(ax, "年化換手 (Turnover)", 1.2, 3.5, fontsize=15, color='#475569', weight='bold')
    turnover_tilt = format_value(resolve_path(k698_data, "strategies.1.turnover_ann"), {"kind": "number", "digits": 1, "suffix": " 倍"})
    draw_text(ax, turnover_tilt, 1.2, 2.5, fontsize=36, color='#1E293B', weight='bold')
    draw_text(ax, "註：固定配比幾乎不需換手", 1.2, 1.7, fontsize=12, color='#64748B')
    
    # 格子 D (右下)
    draw_card(ax, 6.6, 1.3, 8.6, 2.6, facecolor='#FFFBEB', edgecolor='#FEF3C7')
    draw_text(ax, "怎麼讀", 7.0, 3.5, fontsize=15, color='#92400E', weight='bold')
    read_text = (
        "• 分數只高一點點，回撤縮小比較有感。\n"
        "• 疊上更多零件的版本反而更差，多裝機關沒有讓它變好。"
    )
    draw_text(ax, read_text, 7.0, 2.9, fontsize=14, color='#78350F')
    
    add_footer(ax, ["results"])
    
    plt.savefig(os.path.join(OUT_DIR, "panel_result.png"), dpi=150)
    plt.close()

# ==================== PANEL 3 ====================
def draw_panel_3():
    fig, ax = plt.subplots(figsize=(10.666, 6.666), dpi=150)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    
    add_header(ax, "越勤勞，賺得越少")
    
    intro_text = (
        "固定成本假設下，把觸發門檻與傾斜幅度做成網格逐格回測。\n"
        "多抓到的反轉次數，最後多半付給了交易成本。"
    )
    draw_text(ax, intro_text, 0.8, 7.8, fontsize=16, color='#334155', va='top')
    
    # 左半邊 (最佳點)
    draw_card(ax, 0.8, 1.3, 6.8, 6.0, facecolor='#F0FDF4', edgecolor='#BBF7D0')
    draw_text(ax, "網格最佳點 (高門檻情境)", 1.2, 6.8, fontsize=18, color='#166534', weight='bold')
    
    # 左 2x2
    draw_text(ax, "觸發門檻", 1.2, 5.8, fontsize=13, color='#475569')
    best_thresh = format_value(resolve_path(k698_data, "sensitivity_daily_best.threshold"), {"kind": "percent", "digits": 0})
    draw_text(ax, best_thresh, 1.2, 5.0, fontsize=28, color='#15803D', weight='bold')
    
    draw_text(ax, "淨 Sharpe 分數", 4.4, 5.8, fontsize=13, color='#475569')
    best_sharpe = format_value(resolve_path(k698_data, "sensitivity_daily_best.sharpe_net"), {"kind": "number", "digits": 3})
    draw_text(ax, best_sharpe, 4.4, 5.0, fontsize=28, color='#15803D', weight='bold')
    
    draw_text(ax, "年化換手", 1.2, 3.8, fontsize=13, color='#475569')
    best_turnover = format_value(resolve_path(k698_data, "sensitivity_daily_best.turnover_ann"), {"kind": "number", "digits": 1, "suffix": " 倍"})
    draw_text(ax, best_turnover, 1.2, 3.0, fontsize=28, color='#1E293B', weight='bold')
    
    draw_text(ax, "交易日佔比", 4.4, 3.8, fontsize=13, color='#475569')
    best_active = format_value(resolve_path(k698_data, "sensitivity_daily_best.pct_active"), {"kind": "number", "digits": 1, "suffix": "%"})
    draw_text(ax, best_active, 4.4, 3.0, fontsize=28, color='#1E293B', weight='bold')
    
    # 右半邊 (低門檻情境)
    draw_card(ax, 8.4, 1.3, 6.8, 6.0, facecolor='#FEF2F2', edgecolor='#FEE2E2')
    draw_text(ax, "低門檻情境 (頻繁交易)", 8.8, 6.8, fontsize=18, color='#991B1B', weight='bold')
    
    # 右 2x2 / 下排
    draw_text(ax, "觸發門檻", 8.8, 5.8, fontsize=13, color='#475569')
    low_thresh = format_value(resolve_path(k698_data, "sensitivity_daily_threshold.0.threshold"), {"kind": "percent", "digits": 1})
    draw_text(ax, low_thresh, 8.8, 5.0, fontsize=28, color='#B91C1C', weight='bold')
    draw_text(ax, "幾乎每兩天就要動一次", 8.8, 4.2, fontsize=11, color='#991B1B')
    
    draw_text(ax, "淨 Sharpe 分數", 12.0, 5.8, fontsize=13, color='#475569')
    low_sharpe = format_value(resolve_path(k698_data, "sensitivity_daily_threshold.4.sharpe_net"), {"kind": "number", "digits": 3})
    draw_text(ax, low_sharpe, 12.0, 5.0, fontsize=28, color='#B91C1C', weight='bold')
    
    draw_text(ax, "年化換手範圍", 8.8, 3.3, fontsize=13, color='#475569')
    low_turnover_min = format_value(resolve_path(k698_data, "sensitivity_daily_threshold.0.turnover_ann"), {"kind": "number", "digits": 1, "suffix": " 倍"})
    low_turnover_max = format_value(resolve_path(k698_data, "sensitivity_daily_threshold.4.turnover_ann"), {"kind": "number", "digits": 1, "suffix": " 倍"})
    turnover_range = f"{low_turnover_min} ~ {low_turnover_max}"
    draw_text(ax, turnover_range, 8.8, 2.5, fontsize=28, color='#1E293B', weight='bold')
    draw_text(ax, "(換手率較最佳點暴增 1.8 至 5.4 倍)", 8.8, 1.8, fontsize=11, color='#64748B')
    
    add_footer(ax, ["results"])
    
    plt.savefig(os.path.join(OUT_DIR, "panel_turnover.png"), dpi=150)
    plt.close()

# ==================== PANEL 4 ====================
def draw_panel_4():
    fig, ax = plt.subplots(figsize=(10.666, 6.666), dpi=150)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')
    
    add_header(ax, "誠實收尾：我們自己的檢定沒撐住")
    
    # 卡片 1 (統計顯著性)
    draw_card(ax, 0.8, 5.5, 8.0, 2.0, facecolor='#FEF2F2', edgecolor='#FEE2E2')
    draw_text(ax, "比較檢定顯著性 (p-value)", 1.2, 7.2, fontsize=14, color='#991B1B', weight='bold')
    dm_p = format_value(resolve_path(k699_data, "/full_period_confirmation/Default (1%, ±20%)/dm_pvalue"), {"kind": "number", "digits": 3})
    draw_text(ax, dm_p, 1.2, 6.4, fontsize=24, color='#DC2626', weight='bold')
    draw_text(ax, "未達一般認定的顯著水準", 3.0, 6.4, fontsize=12, color='#DC2626')
    draw_text(ax, "分數雖贏一點點，但兩模型檢定未通過，統計上分不出高下。", 1.2, 5.7, fontsize=11, color='#7F1D1D')
    
    # 卡片 2 (多重比較偏差)
    draw_card(ax, 0.8, 3.3, 8.0, 2.0, facecolor='#FFFBEB', edgecolor='#FEF3C7')
    draw_text(ax, "網格最高淨 Sharpe 分數", 1.2, 5.0, fontsize=14, color='#92400E', weight='bold')
    best_s = format_value(resolve_path(k698_data, "sensitivity_daily_best.sharpe_net"), {"kind": "number", "digits": 3})
    draw_text(ax, best_s, 1.2, 4.2, fontsize=24, color='#D97706', weight='bold')
    draw_text(ax, "樣本內掃描的最大值，未做多重比較校正", 3.0, 4.2, fontsize=12, color='#D97706')
    draw_text(ax, "最漂亮的分數是在網格裡挑出來的極值，只能當上限看，而非預期值。", 1.2, 3.5, fontsize=11, color='#78350F')
    
    # 卡片 3 (交易成本低估)
    draw_card(ax, 0.8, 1.1, 8.0, 2.0, facecolor='#F8FAFC', edgecolor='#E2E8F0')
    draw_text(ax, "假設的單邊交易成本", 1.2, 2.8, fontsize=14, color='#475569', weight='bold')
    tx_cost_val = format_value(resolve_path(k698_data, "tx_cost_bps"), {"kind": "integer", "suffix": " bps"})
    draw_text(ax, tx_cost_val, 1.2, 2.0, fontsize=24, color='#1E293B', weight='bold')
    draw_text(ax, "僅計美股一腿，實際成本約低估一倍", 3.0, 2.0, fontsize=12, color='#64748B')
    draw_text(ax, "本測試只計股票交易成本，若計入黃金那一腿，表現將進一步下滑。", 1.2, 1.3, fontsize=11, color='#475569')
    
    # 右半邊 (帶走三句話)
    draw_card(ax, 9.4, 1.1, 5.8, 6.4, facecolor='#FEF3C7', edgecolor='#FDE68A')
    draw_text(ax, "帶走三句話", 9.8, 7.1, fontsize=20, color='#78350F', weight='bold')
    
    draw_text(ax, "1. 短線反轉的現象看得到，\n   能不能變成錢沒有證據說得準。", 9.8, 6.2, fontsize=14, color='#92400E', wrap_width=22)
    draw_text(ax, "2. 訊號小到只要多動幾次手，\n   就會被自己的交易成本吃掉。", 9.8, 4.7, fontsize=14, color='#92400E', wrap_width=22)
    draw_text(ax, "3. 本文為歷史回測結果，\n   不構成任何投資建議。", 9.8, 3.2, fontsize=14, color='#B45309', weight='bold', wrap_width=22)
    
    add_footer(ax, ["results", "robustness"])
    
    plt.savefig(os.path.join(OUT_DIR, "panel_honesty.png"), dpi=150)
    plt.close()

# 9. 執行繪圖
if __name__ == "__main__":
    draw_panel_1()
    draw_panel_2()
    draw_panel_3()
    draw_panel_4()
    print("All panels rendered successfully!")
