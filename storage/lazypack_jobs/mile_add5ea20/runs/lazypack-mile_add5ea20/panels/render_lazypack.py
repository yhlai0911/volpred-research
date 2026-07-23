#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1699 懶人包圖組渲染程式 (render_lazypack.py)
由 Antigravity 專為 K1699 懶人包所寫。
"""

import os
import json
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# 設定字型為繁體中文本機已安裝的 Heiti TC，並防止負號無法顯示
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# 絕對路徑定義
RESULTS_JSON_PATH = "/Users/yhlai0911/volpred-research/experiments/k1699/k1699_results.json"
PLAN_JSON_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_add5ea20/runs/lazypack-mile_add5ea20/plan.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_add5ea20/runs/lazypack-mile_add5ea20/panels"

def resolve_path(data, path):
    """
    動態讀取 JSON 字典中的路徑值。支持 . 或 / 作為分隔符。
    """
    if '/' in path:
        parts = [p for p in path.split('/') if p]
    else:
        # 特殊保護含有句點的 key，如 0050.TW
        path_protected = path.replace('0050.TW', '0050_TW_PLACEHOLDER')
        parts = [p for p in path_protected.split('.') if p]
        parts = [p.replace('0050_TW_PLACEHOLDER', '0050.TW') for p in parts]
    
    cur = data
    for part in parts:
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"Key '{part}' not found in path '{path}'")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Index '{part}' not valid for path '{path}'") from exc
        else:
            raise KeyError(f"Path '{path}' failed at '{part}'")
    return cur

def format_value(val, fmt_spec):
    """
    格式化數值。
    """
    kind = fmt_spec.get("kind")
    if kind == "integer":
        suffix = fmt_spec.get("suffix", "")
        return f"{int(round(val))}{suffix}"
    elif kind == "text":
        return str(val)
    elif kind == "number":
        digits = fmt_spec.get("digits", 2)
        show_plus = fmt_spec.get("show_plus", False)
        fmt = f"+.{digits}f" if show_plus else f".{digits}f"
        return f"{val:{fmt}}"
    elif kind == "percent":
        digits = fmt_spec.get("digits", 2)
        scale = fmt_spec.get("scale", 1)
        v = val * 100 if scale == 100 else val
        return f"{v:.{digits}f}%"
    else:
        return str(val)

def draw_footer(fig, text):
    """
    公用底部標示資料來源。
    """
    fig.text(0.06, 0.045, f"資料來源：{text}", fontsize=10, color='#6B7280')
    ax_line = fig.add_axes([0.06, 0.08, 0.88, 0.01])
    ax_line.axis('off')
    ax_line.axhline(0, color='#E5E7EB', linewidth=1.5)

# 讀取資料
os.makedirs(OUT_DIR, exist_ok=True)
with open(RESULTS_JSON_PATH, 'r', encoding='utf-8') as f:
    results_data = json.load(f)
with open(PLAN_JSON_PATH, 'r', encoding='utf-8') as f:
    plan_data = json.load(f)
results_label = plan_data['evidence']['results']['label']

def render_panel_problem():
    """
    Panel 1 — 檔名 panel_problem.png
    版面風格: professional (深色標題列 + 數據區塊，留白充足)
    """
    fig = plt.figure(figsize=(1600/150, 1000/150), dpi=150)
    fig.patch.set_facecolor('#FFFFFF')
    
    # 標題列
    ax_header = fig.add_axes([0, 0.82, 1, 0.18], facecolor='#1F2937') # 深灰背景
    ax_header.axis('off')
    fig.text(0.06, 0.90, "同一個模型同一批資料，只改「預測幾點發出」", fontsize=22, color='#FFFFFF', fontweight='bold', ha='left')
    fig.text(0.06, 0.85, "說明研究只更動預測發出的時點，模型、資料與損失函數都沒有變動", fontsize=13, color='#9CA3AF', ha='left')
    
    # 左側文字區
    ax_left = fig.add_axes([0.06, 0.12, 0.48, 0.65])
    ax_left.axis('off')
    ax_left.text(0, 0.92, "只動了一件事", fontsize=18, color='#111827', fontweight='bold', transform=ax_left.transAxes)
    
    body_lines = [
        "沒有換模型、沒有換資料、也沒有換評分方式。",
        "唯一的更動是：所有預測都必須在前一天收盤那一刻發出，不准回頭用當天早上才知道的跳空。",
        "招牌成績單上那個壓倒性的勝利，就是在混合時點的口徑下拿到的。"
    ]
    y_pos = 0.78
    for line in body_lines:
        wrapped = textwrap.fill(line, width=26)
        ax_left.text(0, y_pos, wrapped, fontsize=12.5, color='#374151', transform=ax_left.transAxes, linespacing=1.6, va='top')
        num_lines = len(wrapped.split('\n'))
        y_pos -= (num_lines * 0.08 + 0.05)
        
    # 右側數據卡片區
    ax_right = fig.add_axes([0.60, 0.12, 0.34, 0.65])
    ax_right.axis('off')
    
    # 卡片 1 (重跑的市場數)
    n_markets = resolve_path(results_data, "headline.n_markets")
    rect1 = patches.Rectangle((0, 0.52), 1, 0.44, facecolor='#F9FAFB', edgecolor='#E5E7EB', linewidth=1.5, transform=ax_right.transAxes)
    ax_right.add_patch(rect1)
    ax_right.text(0.08, 0.86, "重跑的市場數", fontsize=12.5, color='#4B5563', transform=ax_right.transAxes)
    ax_right.text(0.08, 0.68, format_value(n_markets, {"kind": "integer", "suffix": " 個市場"}), fontsize=26, color='#111827', fontweight='bold', transform=ax_right.transAxes)
    ax_right.text(0.08, 0.58, "美股、黃金、新興市場、台股與台指期", fontsize=10.5, color='#6B7280', transform=ax_right.transAxes)
    
    # 卡片 2 (本文採用的嚴格顯著門檻)
    harvey_threshold = resolve_path(results_data, "method_summary.harvey_threshold")
    rect2 = patches.Rectangle((0, 0.02), 1, 0.44, facecolor='#F9FAFB', edgecolor='#E5E7EB', linewidth=1.5, transform=ax_right.transAxes)
    ax_right.add_patch(rect2)
    ax_right.text(0.08, 0.36, "本文採用的嚴格顯著門檻", fontsize=12.5, color='#4B5563', transform=ax_right.transAxes)
    ax_right.text(0.08, 0.18, format_value(harvey_threshold, {"kind": "text"}), fontsize=26, color='#111827', fontweight='bold', transform=ax_right.transAxes)
    ax_right.text(0.08, 0.08, "小樣本修正後的嚴格標準", fontsize=10.5, color='#6B7280', transform=ax_right.transAxes)
    
    draw_footer(fig, results_label)
    plt.savefig(os.path.join(OUT_DIR, "panel_problem.png"), facecolor='#FFFFFF')
    plt.close()

def render_panel_results():
    """
    Panel 2 — 檔名 panel_results.png
    版面風格: bento-grid (分格，每格一個重點數字/圖示)
    """
    fig = plt.figure(figsize=(1600/150, 1000/150), dpi=150)
    fig.patch.set_facecolor('#FFFFFF')
    
    fig.text(0.06, 0.90, "嚴格收盤口徑下，六個市場全部沒跨過門檻", fontsize=22, color='#111827', fontweight='bold', ha='left')
    fig.text(0.06, 0.85, "六個市場的比較檢定統計量全部落在嚴格門檻之內，統計上分不出勝負", fontsize=13, color='#4B5563', ha='left')
    
    gs = fig.add_gridspec(3, 3, left=0.06, right=0.94, bottom=0.14, top=0.81, wspace=0.15, hspace=0.30)
    
    markets_info = [
        {"name": "台指期 TAIFEX", "path": "markets.TAIFEX.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat", "note": ""},
        {"name": "黃金 GLD", "path": "markets.GLD.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat", "note": ""},
        {"name": "新興市場 EEM", "path": "markets.EEM.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat", "note": ""},
        {"name": "台灣 0050.TW", "path": "/markets/0050.TW/dm_tests/PRG_tminus1_exp_vs_GJR/t_stat", "note": ""},
        {"name": "標普 SPY", "path": "markets.SPY.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat", "note": ""},
        {"name": "那斯達克 QQQ", "path": "markets.QQQ.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat", "note": "六格中離門檻最近的一格，方向還偏向老模型"}
    ]
    
    for idx, m_info in enumerate(markets_info):
        row = idx // 3
        col = idx % 3
        ax_cell = fig.add_subplot(gs[row, col])
        ax_cell.set_xticks([])
        ax_cell.set_yticks([])
        for spine in ax_cell.spines.values():
            spine.set_visible(False)
            
        val = resolve_path(results_data, m_info["path"])
        formatted_val = format_value(val, {"kind": "number", "digits": 2, "show_plus": True})
        
        # 設置 QQQ 獨特高亮背景
        bg_color = '#EFF6FF' if m_info["name"] == "那斯達克 QQQ" else '#F9FAFB'
        border_color = '#BFDBFE' if m_info["name"] == "那斯達克 QQQ" else '#E5E7EB'
        rect = patches.Rectangle((0, 0), 1, 1, facecolor=bg_color, edgecolor=border_color, linewidth=1.5, transform=ax_cell.transAxes)
        ax_cell.add_patch(rect)
        
        ax_cell.text(0.08, 0.78, m_info["name"], fontsize=11.5, color='#4B5563', fontweight='bold', transform=ax_cell.transAxes)
        ax_cell.text(0.08, 0.40, formatted_val, fontsize=24, color='#1F2937', fontweight='bold', transform=ax_cell.transAxes)
        if m_info["note"]:
            wrapped_note = textwrap.fill(m_info["note"], width=17)
            ax_cell.text(0.08, 0.12, wrapped_note, fontsize=9.5, color='#6B7280', transform=ax_cell.transAxes, linespacing=1.3)
            
    # 下方說明區
    ax_text = fig.add_subplot(gs[2, :])
    ax_text.set_xticks([])
    ax_text.set_yticks([])
    for spine in ax_text.spines.values():
        spine.set_visible(False)
        
    rect_text = patches.Rectangle((0, 0), 1, 1, facecolor='#FFFBEB', edgecolor='#FDE68A', linewidth=1.5, transform=ax_text.transAxes)
    ax_text.add_patch(rect_text)
    
    thr_val = resolve_path(results_data, "method_summary.harvey_threshold")
    template_str = "正負只代表哪一邊的預測誤差較低，絕對值要跨過門檻（{thr}）才算真的分出高下。"
    resolved_sentence = template_str.format(thr=thr_val)
    
    ax_text.text(0.03, 0.72, "怎麼讀這六個數字", fontsize=13, color='#78350F', fontweight='bold', transform=ax_text.transAxes)
    ax_text.text(0.03, 0.42, resolved_sentence, fontsize=11, color='#92400E', transform=ax_text.transAxes)
    ax_text.text(0.03, 0.18, "六格全部縮在門檻裡面，統計上就是分不出勝負。", fontsize=11, color='#92400E', transform=ax_text.transAxes)
    
    draw_footer(fig, results_label)
    plt.savefig(os.path.join(OUT_DIR, "panel_results.png"), facecolor='#FFFFFF')
    plt.close()

def render_panel_home_ground():
    """
    Panel 3 — 檔名 panel_home_ground.png
    版面風格: scientific (學術海報風，左右排版，帶科學圖表)
    """
    fig = plt.figure(figsize=(1600/150, 1000/150), dpi=150)
    fig.patch.set_facecolor('#FFFFFF')
    
    fig.text(0.06, 0.90, "最該讓它發光的主場，也沒有發光", fontsize=22, color='#111827', fontweight='bold', ha='left')
    fig.text(0.06, 0.85, "隔夜變異數佔比從最低到最高跨越一倍以上，比較檢定統計量並未隨之上升", fontsize=13, color='#4B5563', ha='left')
    
    # 左側：文字區
    ax_left = fig.add_axes([0.06, 0.14, 0.44, 0.66])
    ax_left.axis('off')
    
    ax_left.text(0, 0.94, "可以直接檢驗的一句話", fontsize=14.5, color='#111827', fontweight='bold', transform=ax_left.transAxes)
    text1 = "這個模型的賣點是把隔夜跳空和盤中震盪分開建模。照這個邏輯，隔夜佔全日波動越高的市場，好處應該越明顯。"
    ax_left.text(0, 0.88, textwrap.fill(text1, width=25), fontsize=11, color='#4B5563', transform=ax_left.transAxes, linespacing=1.5, va='top')
    
    ax_left.text(0, 0.62, "資料說了什麼", fontsize=14.5, color='#111827', fontweight='bold', transform=ax_left.transAxes)
    text2 = "隔夜佔比從最低排到最高，中間跨了一倍以上的差距。檢定統計量沒有跟著爬，主場優勢在資料上看不到影子。"
    ax_left.text(0, 0.56, textwrap.fill(text2, width=25), fontsize=11, color='#4B5563', transform=ax_left.transAxes, linespacing=1.5, va='top')
    
    # 底部指標卡片列表
    y_card = 0.28
    markets = ['QQQ', 'EEM', 'GLD', 'TAIFEX']
    market_names = ['那斯達克', '新興市場', '黃金', '台指期']
    for m, name in zip(markets, market_names):
        sh = resolve_path(results_data, f"markets.{m}.metadata.overnight_variance_share_pct")
        t = resolve_path(results_data, f"markets.{m}.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat")
        t_str = f"{t:+.2f}"
        
        if m == 'TAIFEX':
            note = f"六市場最高，但檢定統計量只有 {t_str}"
        elif m == 'QQQ':
            note = f"六市場最低，檢定統計量卻是最高的 {t_str}"
        else:
            note = f"檢定統計量 {t_str}"
            
        label_text = f"• {name}: 隔夜佔 {sh:.2f}% ({note})"
        ax_left.text(0, y_card, label_text, fontsize=9.5, color='#1F2937', transform=ax_left.transAxes)
        y_card -= 0.065
        
    # 右側：雙軸圖表
    ax_chart = fig.add_axes([0.58, 0.16, 0.34, 0.60])
    full_names = ['那斯達克\nQQQ', '新興市場\nEEM', '黃金\nGLD', '台指期\nTAIFEX']
    
    shares = [resolve_path(results_data, f"markets.{m}.metadata.overnight_variance_share_pct") for m in markets]
    t_stats = [resolve_path(results_data, f"markets.{m}.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat") for m in markets]
    
    ax_left_y = ax_chart
    ax_right_y = ax_chart.twinx()
    
    # 隔夜佔比 (藍色條形圖)
    ax_left_y.bar(full_names, shares, width=0.4, color='#93C5FD', alpha=0.75, label='隔夜佔比')
    # t-stat (紅色折線圖)
    ax_right_y.plot(full_names, t_stats, color='#EF4444', marker='o', linewidth=2.5, markersize=8, label='DM t值')
    
    # 標上具體 t 值
    for i, t in enumerate(t_stats):
        sign = "+" if t > 0 else ""
        ax_right_y.text(i, t + 0.25 if t > 0 else t - 0.5, f"{sign}{t:.2f}", color='#DC2626', fontsize=10, ha='center', fontweight='bold')
        
    ax_left_y.set_ylabel('隔夜變異數佔比 (%)', color='#2563EB', fontsize=11, fontweight='bold')
    ax_left_y.tick_params(axis='y', labelcolor='#2563EB')
    ax_left_y.set_ylim(0, 80)
    
    ax_right_y.set_ylabel('DM 檢定統計量 (t)', color='#DC2626', fontsize=11, fontweight='bold')
    ax_right_y.tick_params(axis='y', labelcolor='#DC2626')
    ax_right_y.set_ylim(-3.5, 3.5)
    
    # 門檻輔助線
    ax_right_y.axhline(0, color='#9CA3AF', linestyle='-', linewidth=0.8)
    ax_right_y.axhline(3.0, color='#F87171', linestyle='--', linewidth=1.2)
    ax_right_y.axhline(-3.0, color='#F87171', linestyle='--', linewidth=1.2)
    ax_right_y.text(1.5, 3.15, '嚴格顯著門檻 +3.0', color='#EF4444', fontsize=9, ha='center')
    ax_right_y.text(1.5, -2.85, '嚴格顯著門檻 -3.0', color='#EF4444', fontsize=9, ha='center')
    
    ax_chart.spines['top'].set_visible(False)
    ax_chart.set_title("隔夜佔比 vs 檢定統計量對比", fontsize=13, fontweight='bold', pad=15)
    
    draw_footer(fig, results_label)
    plt.savefig(os.path.join(OUT_DIR, "panel_home_ground.png"), facecolor='#FFFFFF')
    plt.close()

def render_panel_power():
    """
    Panel 4 — 檔名 panel_power.png
    版面風格: editorial (高對比雜誌編輯風，突出重點對比主視覺)
    """
    fig = plt.figure(figsize=(1600/150, 1000/150), dpi=150)
    fig.patch.set_facecolor('#FFFFFF')
    
    fig.text(0.06, 0.90, "是「真的沒差」，不是「量不準」", fontsize=22, color='#111827', fontweight='bold', ha='left')
    fig.text(0.06, 0.85, "同一套檢定用在另一組模型比較上，給出遠超門檻的統計量，顯示檢定本身有辨識力", fontsize=13, color='#4B5563', ha='left')
    
    # 左側：文字區 (調整寬度以加大左右間距，避免 Tick 溢出重疊)
    ax_left = fig.add_axes([0.06, 0.12, 0.40, 0.68])
    ax_left.axis('off')
    
    ax_left.text(0, 0.92, "合理的懷疑", fontsize=15, color='#111827', fontweight='bold', transform=ax_left.transAxes)
    text1 = "滿桌不顯著，第一個該問的是：會不會這把尺根本量不出東西？"
    ax_left.text(0, 0.86, textwrap.fill(text1, width=24), fontsize=11, color='#4B5563', transform=ax_left.transAxes, linespacing=1.5, va='top')
    
    ax_left.text(0, 0.56, "帶走一句話", fontsize=15, color='#111827', fontweight='bold', transform=ax_left.transAxes)
    text2_lines = [
        "• 同一批資料、同一個檢定，量得出 HAR 那邊的差距，量不出新模型這邊的差距。",
        "• 下次看到某個模型宣稱大勝，先問它的預測是幾點發出的。",
        "• 本文為研究結果整理，不構成任何投資建議。"
    ]
    y_pos = 0.50
    for line in text2_lines:
        wrapped = textwrap.fill(line, width=24)
        ax_left.text(0, y_pos, wrapped, fontsize=10.5, color='#374151', transform=ax_left.transAxes, linespacing=1.5, va='top')
        num_lines = len(wrapped.split('\n'))
        y_pos -= (num_lines * 0.05 + 0.02)
        
    # 下方指標卡片說明
    y_card = 0.16
    spy_har_t = resolve_path(results_data, "markets.SPY.dm_tests.GJR_vs_HAR.t_stat")
    qqq_har_t = resolve_path(results_data, "markets.QQQ.dm_tests.GJR_vs_HAR.t_stat")
    
    ax_left.text(0, y_card, f"• 同一把尺量 GJR 對 HAR (標普 SPY):  {spy_har_t:.2f}", fontsize=10.5, color='#111827', fontweight='bold', transform=ax_left.transAxes)
    ax_left.text(0.04, y_card - 0.04, "  (遠遠跨過嚴格門檻，差距非常明確)", fontsize=9.5, color='#6B7280', transform=ax_left.transAxes)
    
    ax_left.text(0, y_card - 0.09, f"• 同一把尺量 GJR 對 HAR (那斯達克 QQQ): {qqq_har_t:.2f}", fontsize=10.5, color='#111827', fontweight='bold', transform=ax_left.transAxes)
    ax_left.text(0.04, y_card - 0.13, "  (同樣遠遠跨過門檻)", fontsize=9.5, color='#6B7280', transform=ax_left.transAxes)

    # 右側：高對比水平條形圖 (向右平移且縮小寬度，給 Tick 預留充足空間)
    ax_chart = fig.add_axes([0.60, 0.16, 0.34, 0.60])
    
    spy_prg_t = resolve_path(results_data, "markets.SPY.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat")
    qqq_prg_t = resolve_path(results_data, "markets.QQQ.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat")
    
    # 縮短類別名稱，避免字串過長溢出
    categories = [
        'QQQ: GJR vs HAR',
        'SPY: GJR vs HAR',
        'QQQ: PRG vs GJR',
        'SPY: PRG vs GJR'
    ]
    t_stats = [qqq_har_t, spy_har_t, qqq_prg_t, spy_prg_t]
    
    # 顯著用鮮紅色，不顯著用冷灰色
    colors = ['#EF4444', '#EF4444', '#9CA3AF', '#9CA3AF']
    
    bars = ax_chart.barh(categories, t_stats, color=colors, height=0.5)
    
    for bar, t in zip(bars, t_stats):
        width = bar.get_width()
        sign = "+" if t > 0 else ""
        if t < 0:
            ax_chart.text(width - 0.2, bar.get_y() + bar.get_height()/2, f"{sign}{t:.2f}", 
                          va='center', ha='right', color='white' if abs(t) > 5 else 'black', 
                          fontweight='bold', fontsize=9.5)
        else:
            ax_chart.text(width + 0.2, bar.get_y() + bar.get_height()/2, f"{sign}{t:.2f}", 
                          va='center', ha='left', color='black', 
                          fontweight='bold', fontsize=9.5)
            
    # 門檻虛線與標記
    ax_chart.axvline(-3.0, color='#EF4444', linestyle='--', linewidth=1.2)
    ax_chart.axvline(3.0, color='#EF4444', linestyle='--', linewidth=1.2)
    
    # 將標記移動到 y=2.5 處，避免與標題 collision
    ax_chart.text(-3.2, 2.5, '門檻 -3.0', color='#EF4444', fontsize=9, ha='right', fontweight='bold')
    ax_chart.text(3.2, 2.5, '門檻 +3.0', color='#EF4444', fontsize=9, ha='left', fontweight='bold')
    
    # 設定 y-tick 字型大小為 9 以防溢出
    ax_chart.tick_params(axis='y', labelsize=9)
    
    ax_chart.set_xlim(-10, 4)
    ax_chart.set_xlabel('DM 檢定統計量 t 值 (越負代表前款越優)', fontsize=11)
    ax_chart.set_title("檢定統計量對比：顯著 vs 不顯著", fontsize=13, fontweight='bold', pad=15)
    
    ax_chart.spines['top'].set_visible(False)
    ax_chart.spines['right'].set_visible(False)
    
    draw_footer(fig, results_label)
    plt.savefig(os.path.join(OUT_DIR, "panel_power.png"), facecolor='#FFFFFF')
    plt.close()

if __name__ == '__main__':
    render_panel_problem()
    render_panel_results()
    render_panel_home_ground()
    render_panel_power()
    print("All panels rendered successfully!")
