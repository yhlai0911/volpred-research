#!/usr/bin/env python3
"""
Render Lazypack PNG panels for mile_679eb2a1.

Data-bound rendering script for VolPred general reader article.
Reads evidence strictly from K1323 results JSON and writes 4 PNG panels.
"""

import json
import os
import textwrap
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Set font parameters as required by prompt
plt.rcParams['font.sans-serif'] = ['Heiti TC']
plt.rcParams['axes.unicode_minus'] = False

# Absolute paths
PLAN_PATH = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_679eb2a1/runs/lazypack-mile_679eb2a1/plan.json"
K1323_PATH = "/Users/yhlai0911/volpred-research/experiments/k1323/k1323_results.json"
OUT_DIR = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_679eb2a1/runs/lazypack-mile_679eb2a1/panels"

SOURCE_FOOTER = "資料來源：台灣與美國恐慌指數比值的門檻進度、兩種配對口徑統計量與資料新鮮度自查結果 JSON"


def load_json(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing evidence file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_json_val(data: dict, path_str: str):
    parts = [p for p in path_str.split("/") if p]
    curr = data
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            raise KeyError(f"Missing key '{p}' in path '{path_str}' while parsing evidence JSON")
    return curr


def create_base_figure(title: str, subtitle: str):
    fig, ax = plt.subplots(figsize=(16, 10), dpi=100)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis("off")

    # Background fill
    bg = patches.Rectangle((0, 0), 16, 10, facecolor="#F8FAFC", edgecolor="none")
    ax.add_patch(bg)

    # Brand Pill
    brand_box = patches.FancyBboxPatch(
        (0.8, 9.15), 2.2, 0.45,
        boxstyle="round,pad=0.05,rounding_size=0.1",
        facecolor="#EFF6FF", edgecolor="#BFDBFE", linewidth=1
    )
    ax.add_patch(brand_box)
    ax.text(1.9, 9.37, "VOLPRED 懶人包", fontsize=11, fontweight="bold", color="#2563EB", ha="center", va="center")

    # Title
    ax.text(0.8, 8.65, title, fontsize=22, fontweight="bold", color="#0F172A", ha="left", va="center")

    # Subtitle
    wrapped_sub = textwrap.fill(subtitle, width=70)
    ax.text(0.8, 8.15, wrapped_sub, fontsize=12, color="#475569", ha="left", va="top", linespacing=1.3)

    # Footer Separator Line
    ax.plot([0.8, 15.2], [0.7, 0.7], color="#CBD5E1", linewidth=1)

    # Footer Text
    ax.text(0.8, 0.4, SOURCE_FOOTER, fontsize=11, color="#64748B", ha="left", va="center")

    return fig, ax


def draw_card(ax, x: float, y: float, w: float, h: float, bg_color="#FFFFFF", edge_color="#E2E8F0"):
    card = patches.FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.0,rounding_size=0.25",
        facecolor=bg_color, edgecolor=edge_color, linewidth=1.5
    )
    ax.add_patch(card)


def render_panel_1(k1323: dict):
    target_days = get_json_val(k1323, "/progress_to_252/target_days")
    unique_days = get_json_val(k1323, "/progress_to_252/unique_vixtwn_days")
    vixtwn_start = get_json_val(k1323, "/data_sources/vixtwn/start")
    vixtwn_end = get_json_val(k1323, "/data_sources/vixtwn/end")

    fig, ax = create_base_figure(
        title="一個事先訂好的規矩",
        subtitle="概念說明：台灣恐慌指數除以美國恐慌指數得到一個倍數，事先講好要累積滿一年的交易日才認定穩不穩，目前只走到不到一半"
    )

    # Left Column: Text Cards
    # Card 1
    draw_card(ax, 0.8, 4.6, 6.9, 3.0, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(1.1, 7.2, "在看什麼數字", fontsize=16, fontweight="bold", color="#0F172A", va="center")
    lines1 = [
        "• 台灣的恐慌指數除以美國的恐慌指數，得到一個倍數。",
        "• 這個倍數大，代表台股的隱含波動相對美股被墊得比較高。",
        "• 問題不是它今天多少，而是它到底穩不穩定。"
    ]
    ax.text(1.1, 6.7, "\n".join(lines1), fontsize=12, color="#334155", va="top", linespacing=1.6)

    # Card 2
    draw_card(ax, 0.8, 1.2, 6.9, 3.0, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(1.1, 3.8, "規矩事先訂好", fontsize=16, fontweight="bold", color="#0F172A", va="center")
    lines2 = [
        "• 要認定穩或不穩，事先講好要累積滿一整年的交易日才拿出來說。",
        "• 門檻是事先訂的，不是事後挑的。",
        "• 事先講好的門檻，只有在對自己不利的時候才有價值。"
    ]
    ax.text(1.1, 3.3, "\n".join(lines2), fontsize=12, color="#334155", va="top", linespacing=1.6)

    # Right Column: Metric Cards
    # Metric 1
    draw_card(ax, 8.3, 4.6, 6.9, 3.0, bg_color="#EFF6FF", edge_color="#BFDBFE")
    ax.text(8.7, 7.0, "事先訂的門檻", fontsize=15, fontweight="bold", color="#1E40AF", va="center")
    ax.text(8.7, 5.7, f"{target_days} 個交易日", fontsize=36, fontweight="bold", color="#1E3A8A", va="center")

    # Metric 2
    draw_card(ax, 8.3, 1.2, 6.9, 3.0, bg_color="#F0FDF4", edge_color="#BBF7D0")
    ax.text(8.7, 3.6, "目前累積", fontsize=15, fontweight="bold", color="#166534", va="center")
    ax.text(8.7, 2.5, f"{unique_days} 個交易日", fontsize=36, fontweight="bold", color="#14532D", va="center")
    ax.text(8.7, 1.6, f"台灣端樣本自 {vixtwn_start} 至 {vixtwn_end}", fontsize=12, color="#15803D", va="center")

    fig.savefig(os.path.join(OUT_DIR, "1_concept.png"), dpi=100)
    plt.close(fig)


def render_panel_2(k1323: dict):
    local_vix_end = get_json_val(k1323, "/data_sources/local_vix_primary/end")
    vixtwn_last = get_json_val(k1323, "/source_freshness_gap/vixtwn_last_date")
    stale_days = get_json_val(k1323, "/source_freshness_gap/local_source_stale_vs_vixtwn_days")
    local_overlap = get_json_val(k1323, "/source_freshness_gap/local_pairing_overlap_days")
    fresh_overlap = get_json_val(k1323, "/source_freshness_gap/fresh_pairing_overlap_days")

    fig, ax = create_base_figure(
        title="跑到一半，出事的是自己",
        subtitle="方法說明：本地那份配對用的美股資料末端落後台灣端數個交易日，使可用的配對天數變少，於是另外重抓一份當期資料再算一次"
    )

    # Top Text Block
    draw_card(ax, 0.8, 5.4, 14.4, 2.2, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(1.1, 7.1, "兩邊日期對不上", fontsize=16, fontweight="bold", color="#0F172A", va="center")
    lines = [
        "• 配對那一步，兩份資料的最後日期對不上。",
        "• 台灣那份已經更新到最新，本地那份美股資料的末端停在更早以前。",
        "• 這個缺口不會報錯、不會少一欄，也不會出現任何異常值。"
    ]
    ax.text(1.1, 6.6, "\n".join(lines), fontsize=12, color="#334155", va="top", linespacing=1.5)

    # 2x2 Grid of Metrics
    # Cell (0,0) Top-Left
    draw_card(ax, 0.8, 3.3, 6.9, 1.8, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(1.1, 4.7, "本地美股檔末端", fontsize=14, fontweight="bold", color="#475569", va="center")
    ax.text(1.1, 4.0, f"{local_vix_end}", fontsize=28, fontweight="bold", color="#0F172A", va="center")
    ax.text(1.1, 3.55, f"台灣端已到 {vixtwn_last}", fontsize=11, color="#64748B", va="center")

    # Cell (0,1) Top-Right
    draw_card(ax, 8.3, 3.3, 6.9, 1.8, bg_color="#FEF2F2", edge_color="#FCA5A5")
    ax.text(8.6, 4.7, "落後幅度", fontsize=14, fontweight="bold", color="#991B1B", va="center")
    ax.text(8.6, 3.9, f"{stale_days} 個交易日", fontsize=28, fontweight="bold", color="#DC2626", va="center")

    # Cell (1,0) Bottom-Left
    draw_card(ax, 0.8, 1.2, 6.9, 1.8, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(1.1, 2.6, "舊檔配得出的天數", fontsize=14, fontweight="bold", color="#475569", va="center")
    ax.text(1.1, 1.8, f"{local_overlap} 天", fontsize=28, fontweight="bold", color="#0F172A", va="center")

    # Cell (1,1) Bottom-Right
    draw_card(ax, 8.3, 1.2, 6.9, 1.8, bg_color="#ECFDF5", edge_color="#6EE7B7")
    ax.text(8.6, 2.6, "重抓後配得出的天數", fontsize=14, fontweight="bold", color="#065F46", va="center")
    ax.text(8.6, 1.9, f"{fresh_overlap} 天", fontsize=28, fontweight="bold", color="#059669", va="center")
    ax.text(8.6, 1.45, "少掉的那幾天，全部是最新的那幾天", fontsize=11, color="#047857", va="center")

    fig.savefig(os.path.join(OUT_DIR, "2_method.png"), dpi=100)
    plt.close(fig)


def render_panel_3(k1323: dict):
    k1181_mean = get_json_val(k1323, "/baseline_comparison/k1181_mean")
    local_mean = get_json_val(k1323, "/primary_local_gate/ratio_stats/mean")
    fresh_mean = get_json_val(k1323, "/fresh_vix_audit/ratio_stats/mean")

    k1181_cv = get_json_val(k1323, "/baseline_comparison/k1181_cv")
    fresh_cv = get_json_val(k1323, "/fresh_vix_audit/ratio_stats/cv")

    rolling20_end = get_json_val(k1323, "/fresh_vix_audit/ratio_stats/rolling20_mean_end")
    rolling20_start = get_json_val(k1323, "/fresh_vix_audit/ratio_stats/rolling20_mean_start")

    fig, ax = create_base_figure(
        title="重抓一份，結論沒有被救回來",
        subtitle="結果對照：換上當期重抓的美股資料之後，倍數的平均更高、跳動幅度更大，兩種口徑的平均都高於先前研究定的參考水位"
    )

    # Left 2x3 Metric Cards (x: 0.8 to 9.8)
    # Row 1 (y: 5.6 to 7.6)
    draw_card(ax, 0.8, 5.6, 4.3, 2.0, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(1.0, 7.1, "參考水位（先前研究）", fontsize=13, fontweight="bold", color="#475569", va="center")
    ax.text(1.0, 6.3, f"{k1181_mean:.3f}", fontsize=28, fontweight="bold", color="#0F172A", va="center")

    draw_card(ax, 5.4, 5.6, 4.3, 2.0, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(5.6, 7.1, "舊檔口徑平均", fontsize=13, fontweight="bold", color="#475569", va="center")
    ax.text(5.6, 6.3, f"{local_mean:.3f}", fontsize=28, fontweight="bold", color="#0F172A", va="center")

    # Row 2 (y: 3.4 to 5.4)
    draw_card(ax, 0.8, 3.4, 4.3, 2.0, bg_color="#EFF6FF", edge_color="#BFDBFE")
    ax.text(1.0, 4.9, "重抓口徑平均", fontsize=13, fontweight="bold", color="#1E40AF", va="center")
    ax.text(1.0, 4.1, f"{fresh_mean:.3f}", fontsize=28, fontweight="bold", color="#1E3A8A", va="center")

    draw_card(ax, 5.4, 3.4, 4.3, 2.0, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(5.6, 4.9, "參考的跳動幅度", fontsize=13, fontweight="bold", color="#475569", va="center")
    ax.text(5.6, 4.1, f"{k1181_cv:.3f}", fontsize=28, fontweight="bold", color="#0F172A", va="center")

    # Row 3 (y: 1.2 to 3.2)
    draw_card(ax, 0.8, 1.2, 4.3, 2.0, bg_color="#FFFBEB", edge_color="#FDE68A")
    ax.text(1.0, 2.7, "重抓口徑跳動幅度", fontsize=13, fontweight="bold", color="#92400E", va="center")
    ax.text(1.0, 2.0, f"{fresh_cv:.3f}", fontsize=28, fontweight="bold", color="#D97706", va="center")
    ax.text(1.0, 1.55, "約為參考值的兩倍", fontsize=11, color="#B45309", va="center")

    draw_card(ax, 5.4, 1.2, 4.3, 2.0, bg_color="#F5F3FF", edge_color="#DDD6FE")
    ax.text(5.6, 2.7, "二十天平均的終點", fontsize=13, fontweight="bold", color="#5B21B6", va="center")
    ax.text(5.6, 2.0, f"{rolling20_end:.3f}", fontsize=28, fontweight="bold", color="#6D28D9", va="center")
    ax.text(5.6, 1.55, f"起點是 {rolling20_start:.3f}，整段路上沒有像樣的回頭", fontsize=10, color="#6D28D9", va="center")

    # Right Text Card (x: 10.0 to 15.2)
    draw_card(ax, 10.0, 1.2, 5.2, 6.4, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(10.3, 7.0, "把樣本切一半", fontsize=16, fontweight="bold", color="#0F172A", va="center")
    lines = [
        "• 前半段的平均貼著參考水位，",
        "  後半段拉開一大截。",
        "",
        "• 換成新鮮資料，這條上升的斜線",
        "  只有更陡，沒有變平。",
        "",
        "• 原本猜資料過期製造了假象，",
        "  這個猜測不成立。"
    ]
    ax.text(10.3, 6.4, "\n".join(lines), fontsize=12, color="#334155", va="top", linespacing=1.5)

    fig.savefig(os.path.join(OUT_DIR, "3_results.png"), dpi=100)
    plt.close(fig)


def render_panel_4(k1323: dict):
    completion_ratio = get_json_val(k1323, "/progress_to_252/completion_ratio")
    days_remaining = get_json_val(k1323, "/progress_to_252/days_remaining")

    fig, ax = create_base_figure(
        title="門檻沒到，所以不下結論",
        subtitle="結論：進度尚未達到事先訂好的門檻，倍數的跳動幅度仍偏大且單向爬升，因此本輪不宣布任何結果，數字全部停在樣本截止日"
    )

    # Top Metric Cards (y: 4.8 to 7.6)
    draw_card(ax, 0.8, 4.8, 6.9, 2.8, bg_color="#EFF6FF", edge_color="#BFDBFE")
    ax.text(1.2, 7.0, "門檻進度", fontsize=16, fontweight="bold", color="#1E40AF", va="center")
    ax.text(1.2, 5.8, f"{completion_ratio*100:.1f}%", fontsize=42, fontweight="bold", color="#1E3A8A", va="center")

    draw_card(ax, 8.3, 4.8, 6.9, 2.8, bg_color="#FFFBEB", edge_color="#FDE68A")
    ax.text(8.7, 7.0, "還差", fontsize=16, fontweight="bold", color="#92400E", va="center")
    ax.text(8.7, 5.8, f"{days_remaining} 個交易日", fontsize=42, fontweight="bold", color="#D97706", va="center")

    # Bottom Text Cards (y: 1.2 to 4.4)
    draw_card(ax, 0.8, 1.2, 6.9, 3.2, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(1.1, 3.9, "這輪的結論只有一句", fontsize=16, fontweight="bold", color="#0F172A", va="center")
    lines1 = [
        "• 門檻沒到，而且以目前的散開程度和趨勢，",
        "  還不到能講穩定的狀態。",
        "• 材料其實夠寫一篇讀起來很順的結論文章，",
        "  但門檻是事先講好的。",
        "• 現在就宣布，等於承認那條線可以移動。"
    ]
    ax.text(1.1, 3.4, "\n".join(lines1), fontsize=11.5, color="#334155", va="top", linespacing=1.5)

    draw_card(ax, 8.3, 1.2, 6.9, 3.2, bg_color="#FFFFFF", edge_color="#E2E8F0")
    ax.text(8.6, 3.9, "真正的收穫", fontsize=16, fontweight="bold", color="#0F172A", va="center")
    lines2 = [
        "• 比較有用的，是那幾天的資料落差。",
        "• 它只會安靜地讓樣本變少，然後把最新的一段",
        "  資訊從結論裡拿掉。",
        "• 所有數字停在樣本截止日，不描述當前市場。"
    ]
    ax.text(8.6, 3.4, "\n".join(lines2), fontsize=11.5, color="#334155", va="top", linespacing=1.5)

    fig.savefig(os.path.join(OUT_DIR, "4_takeaway.png"), dpi=100)
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    k1323_data = load_json(K1323_PATH)

    render_panel_1(k1323_data)
    render_panel_2(k1323_data)
    render_panel_3(k1323_data)
    render_panel_4(k1323_data)


if __name__ == "__main__":
    main()
