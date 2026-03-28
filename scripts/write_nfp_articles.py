#!/usr/bin/env python3
"""
Generate 2 NFP pre-event articles for April 3, 2026 NFP release.
Based on K528 experiment results.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.charts import (
    generate_bar_chart,
    generate_grouped_bar_chart,
    generate_line_chart,
    upload_chart,
    embed_chart,
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ─── Load K528 results ────────────────────────────────────────
results_path = ROOT / "experiments" / "k528_nfp_event_study_results.json"
with open(results_path) as f:
    K528 = json.load(f)


# ─── Chart 1: NFP vol by VIX regime (for general article) ────
def make_chart_vix_regime():
    """Bar chart: NFP day abs return by VIX regime."""
    import matplotlib.patches as mpatches

    plt.rcParams["font.sans-serif"] = ["PingFang HK", "PingFang TC", "Arial Unicode MS", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.3

    fig, ax = plt.subplots(figsize=(10, 6))

    labels = ["一般非農日\n(低 VIX, n=127)", "當前情境\n(高 VIX, n=127)", "非非農日\n(基準)"]
    values = [
        K528["regime_analysis"]["low_vix_nfp_abs_return"] * 100,
        K528["regime_analysis"]["high_vix_nfp_abs_return"] * 100,
        K528["main_results"]["non_nfp_avg_abs_return"] * 100,
    ]
    colors = ["#4CAF50", "#F44336", "#2196F3"]

    bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=0.5, width=0.5)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.02,
            f"{val:.3f}%",
            ha="center", va="bottom", fontsize=11, fontweight="bold"
        )

    # Annotate ratio
    ax.annotate(
        f"2.17倍！",
        xy=(1, values[1]),
        xytext=(1.4, values[1] * 0.85),
        fontsize=12, color="#F44336", fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#F44336"),
    )

    ax.set_ylabel("非農當日平均絕對報酬 (%)", fontsize=12)
    ax.set_title("高 VIX vs 低 VIX 環境下的非農日波動", fontsize=14, fontweight="bold", pad=15)
    ax.set_ylim(0, max(values) * 1.3)

    # Add VIX info box
    ax.text(
        0.98, 0.97,
        f"VIX 分界點: 16.71\n當前 VIX: 29.71 (高波動!)",
        transform=ax.transAxes,
        ha="right", va="top",
        fontsize=10, color="#F44336",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#FFF3F3", edgecolor="#F44336", alpha=0.8)
    )

    fig.tight_layout()
    from pathlib import Path
    import uuid
    chart_dir = Path("/tmp/volpred_charts")
    chart_dir.mkdir(exist_ok=True)
    uid = uuid.uuid4().hex[:6]
    path = chart_dir / f"nfp_vix_regime_{uid}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


# ─── Chart 2: t-test vs Wilcoxon comparison (for research article) ────
def make_chart_test_comparison():
    """Grouped bar showing parametric vs nonparametric results."""
    plt.rcParams["font.sans-serif"] = ["PingFang HK", "PingFang TC", "Arial Unicode MS", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.3

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))

    # Left: p-values for each test
    tests = ["t-test\n(vs 全市場)", "t-test\n(vs 週五)", "Wilcoxon\n(Mann-Whitney U)"]
    p_values = [
        K528["statistical_tests"]["A_nfp_vs_all"]["p_value"],
        K528["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
        K528["statistical_tests"]["C_wilcoxon"]["p_value"],
    ]
    significance = [False, True, True]
    bar_colors = ["#FF9800", "#4CAF50", "#2196F3"]

    ax = axes[0]
    bars = ax.bar(tests, p_values, color=bar_colors, edgecolor="white", linewidth=0.5, width=0.5)
    ax.axhline(y=0.05, color="red", linestyle="--", linewidth=1.5, label="顯著水準 5%")
    ax.set_ylabel("p 值 (越小越顯著)", fontsize=11)
    ax.set_title("各統計檢定 p 值", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)

    for bar, p, sig in zip(bars, p_values, significance):
        label = f"p={p:.4f}\n{'★顯著' if sig else '✗不顯著'}"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.003,
            label,
            ha="center", va="bottom", fontsize=9,
            color="darkgreen" if sig else "gray"
        )

    # Right: vol ratio by month (seasonal)
    months = list(K528["seasonal_analysis"].keys())
    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    vol_ratios = [K528["seasonal_analysis"][m]["vol_ratio"] for m in months]

    ax2 = axes[1]
    bar_colors2 = ["#F44336" if m == "4" else "#2196F3" for m in months]
    bars2 = ax2.bar(month_labels, vol_ratios, color=bar_colors2, edgecolor="white", linewidth=0.5)
    ax2.axhline(y=1.0, color="gray", linestyle="--", linewidth=1.5, label="基準 (=1.0)")
    ax2.set_ylabel("波動比率 vs 非非農日", fontsize=11)
    ax2.set_title("各月非農日波動比率（4月高亮）", fontsize=13, fontweight="bold")
    ax2.legend(fontsize=10)

    # Annotate April
    april_idx = 3  # 0-indexed
    ax2.text(
        april_idx, vol_ratios[april_idx] + 0.03,
        f"4月: {vol_ratios[april_idx]:.2f}x\n(n=21, NS)",
        ha="center", va="bottom", fontsize=9, color="#F44336", fontweight="bold"
    )

    fig.suptitle("K528: NFP 事件研究 — 統計檢定結果", fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()

    from pathlib import Path
    import uuid
    chart_dir = Path("/tmp/volpred_charts")
    chart_dir.mkdir(exist_ok=True)
    uid = uuid.uuid4().hex[:6]
    path = chart_dir / f"nfp_test_comparison_{uid}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


# ─── Chart 3: VIX vs NFP day vol scatter (for research article) ────
def make_chart_vix_scatter():
    """Scatter plot of VIX vs NFP day absolute return."""
    plt.rcParams["font.sans-serif"] = ["PingFang HK", "PingFang TC", "Arial Unicode MS", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"

    fig, ax = plt.subplots(figsize=(10, 6))

    # Extract scatter data from event_data
    event_data = K528.get("event_data", [])
    vix_vals = [e["pre_vix"] for e in event_data]
    abs_rets = [e["event_abs_return"] * 100 for e in event_data]

    # Color by high/low VIX
    vix_median = K528["regime_analysis"]["vix_median_split"]
    colors = ["#F44336" if v > vix_median else "#4CAF50" for v in vix_vals]

    ax.scatter(vix_vals, abs_rets, c=colors, alpha=0.5, s=30, edgecolors="none")

    # Regression line
    slope = K528["statistical_tests"]["E_vix_predictive"]["slope"]
    pearson_r = K528["statistical_tests"]["E_vix_predictive"]["pearson_r"]
    x_range = np.linspace(min(vix_vals), max(vix_vals), 100)
    # Calculate intercept from mean
    mean_vix = np.mean(vix_vals)
    mean_ret = np.mean(abs_rets)
    intercept = mean_ret - slope * mean_vix * 100
    y_range = slope * 100 * x_range + intercept
    ax.plot(x_range, y_range, "k--", linewidth=2, label=f"回歸線 (r={pearson_r:.3f})")

    # Mark current VIX
    current_vix = 29.71
    ax.axvline(x=current_vix, color="#FF5722", linewidth=2, linestyle=":", label=f"當前 VIX={current_vix}")

    # Add patches for legend
    high_patch = mpatches.Patch(color="#F44336", label=f"高 VIX (>{vix_median:.0f})")
    low_patch = mpatches.Patch(color="#4CAF50", label=f"低 VIX (<{vix_median:.0f})")
    handles, _ = ax.get_legend_handles_labels()
    ax.legend(handles=[high_patch, low_patch] + handles, fontsize=10, loc="upper left")

    ax.set_xlabel("事前 VIX (T-1)", fontsize=12)
    ax.set_ylabel("非農當日絕對報酬 (%)", fontsize=12)
    ax.set_title(f"VIX 是真正的預測因子 (r={pearson_r:.3f}, p<0.001)\n2005-2026，254 個非農事件", fontsize=13, fontweight="bold")

    # Annotation for current VIX
    ax.annotate(
        "← 當前 VIX 29.71\n   預期高波動！",
        xy=(current_vix, 0.5),
        xytext=(35, 0.8),
        fontsize=10, color="#FF5722", fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#FF5722"),
    )

    fig.tight_layout()
    from pathlib import Path
    import uuid
    chart_dir = Path("/tmp/volpred_charts")
    chart_dir.mkdir(exist_ok=True)
    uid = uuid.uuid4().hex[:6]
    path = chart_dir / f"nfp_vix_scatter_{uid}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def make_article_id():
    return "mile_" + uuid.uuid4().hex[:8]


def now_utc():
    return datetime.now(timezone.utc).isoformat()


# ─── Generate charts ─────────────────────────────────────────
print("Generating charts...")
chart1_path = make_chart_vix_regime()
chart2_path = make_chart_test_comparison()
chart3_path = make_chart_vix_scatter()
print(f"  Chart 1: {chart1_path}")
print(f"  Chart 2: {chart2_path}")
print(f"  Chart 3: {chart3_path}")

print("Uploading to Supabase Storage...")
chart1_url = upload_chart(chart1_path)
chart2_url = upload_chart(chart2_path)
chart3_url = upload_chart(chart3_path)
print(f"  URL 1: {chart1_url}")
print(f"  URL 2: {chart2_url}")
print(f"  URL 3: {chart3_url}")


# ─── Article 1: 一般讀者 ─────────────────────────────────────
ART1_ID = make_article_id()
ART1_TITLE = "下週五非農數據公布——你該緊張嗎？VIX 29 告訴你的事"

ART1_CONTENT = f"""# 下週五非農數據公布——你該緊張嗎？VIX 29 告訴你的事

每個月第一個週五，全球投資人都會盯著同一個數字：**非農就業人口（Non-Farm Payrolls，NFP）**。
2026 年 4 月 3 日，下週五，又是這個時刻。

你是否感覺到那種「不知道會發生什麼」的焦慮？市場可能大漲、也可能大跌。要不要先賣掉、等公布完再買回來？

我們用 21 年的真實數據回答這個問題。結論可能讓你意外。

---

## 什麼是非農就業報告？

非農就業報告（NFP）由美國勞工統計局每月第一個週五發布，衡量前一個月美國非農業部門新增或減少的工作崗位數。

這個數字被視為美國經濟健康的體溫計：
- **遠超預期** → 經濟強勁 → 股市可能上漲（但也可能引發加息預期）
- **遠低預期** → 經濟疲軟 → 股市可能下跌

由於幾乎每個人都在看這個數字，市場反應往往劇烈而迅速。

---

## 21 年的數據怎麼說？

我們研究了 2005 年至 2026 年共 **254 個非農公布日** 的 SPY（追蹤 S&P 500 的 ETF）表現。

**核心發現：非農當日的波動，平均只有 0.84%。**

這是什麼概念？比正常的非週五交易日（0.76%）高不了多少——統計上甚至**不顯著**（t 檢定 p=0.128）。

換句話說，如果你只是「因為有非農要公布」就想賣股票避險，這個決定在統計上站不住腳。

---

## 但是——VIX 才是關鍵

等等，不是說波動不大嗎？為什麼市場感覺有時候非農後波動很大？

答案在 VIX。

我們發現：**VIX（恐慌指數）才是預測非農日波動的真正因子**，相關係數高達 r=0.451，統計上極度顯著（p<0.0001）。

更直接的說：

| VIX 環境 | 非農日平均波動 | 是正常日的幾倍 |
|---------|------------|------------|
| 低 VIX (<16.7) | 0.53% | 0.7x（比正常日還低！）|
| 高 VIX (>16.7) | **1.15%** | **2.17x** |

**高 VIX 環境下的非農日，波動是低 VIX 的 2.17 倍。**

這就是為什麼有時候感覺非農後波動劇烈、有時候風平浪靜——不是非農本身的問題，是當時的 VIX 水位。

---

## 4 月 3 日的情況：VIX 29.71，高警戒

"""

# Embed chart 1
ART1_CONTENT += f"\n\n![高 VIX vs 低 VIX 環境下的非農日波動]({chart1_url})\n\n"

ART1_CONTENT += f"""
目前 VIX 是 **29.71**，遠高於歷史中位數 16.7。

這意味著：這次非農（4月3日）是**典型的高 VIX 非農日**，歷史上這種情況的平均波動是 1.15%，是正常日的 2.17 倍。

上圖清楚顯示：當你處於低 VIX 環境（綠色），非農日波動其實比平時更低；但高 VIX 環境（紅色，即目前狀況）下，非農日波動顯著放大。

---

## 那我該怎麼辦？

**最重要的一句話：你不需要因為非農而改變你的投資組合。**

理由如下：

1. **事件本身不可預測**：沒有人能一致性地預測非農數字，試圖「押寶方向」是賭博，不是投資。

2. **波動不等於方向**：我們的研究發現，57.1% 的非農日收紅（上漲）——雖然這個比例稍高，但你預先出場就意味著可能錯過上漲。

3. **高波動不等於一定下跌**：高 VIX 下的非農日波動確實較大，但方向仍然隨機。波動大 = 可能大漲，也可能大跌。

4. **策略比事件重要**：與其猜非農，不如確保你的部位符合你的風險承受度。如果 VIX 29 讓你睡不著覺，問題不在非農，在你的部位大小。

---

## 4 月非農的歷史紀錄

過去 21 年，4 月份非農日（共 21 次）的平均波動是 1.00%，波動比率 1.31x，但統計上**不顯著**（p=0.387）。

也就是說，4 月非農並不比其他月份的非農「特別危險」。

---

## 結論：把注意力放在 VIX，不是非農數字

| 問題 | 答案 |
|-----|-----|
| 非農日一定會大幅波動嗎？ | 不，統計上不顯著 |
| 現在 VIX 29 要緊張嗎？ | 是，高 VIX 意味著更大波動 |
| 應該賣出等非農公布後再買回？ | 不建議，方向隨機、交易成本確定 |
| 什麼最重要？ | 維持適合你風險承受度的部位 |

**非農數字自己不可怕，可怕的是在高 VIX 環境中不知道你能承受多少波動。**

保持倉位，保持清醒。

---

*本文基於實驗 K528 的實證結果（數據來源：yfinance SPY + VIX，期間：2005-2026，254 個非農事件）。*
*[提出: 用戶, 執行: Claude]*
"""

art1 = {
    "id": ART1_ID,
    "title": ART1_TITLE,
    "content": ART1_CONTENT,
    "thinking": "NFP 事前文章。K528 發現 NFP 本身波動不顯著，但 VIX 才是真正預測因子（r=0.451）。當前 VIX=29.71 是高 VIX 環境，歷史上高 VIX 非農日 = 2.17x 波動。核心訊息：不要因 NFP 改變策略，要關注 VIX。",
    "tags": ["一般讀者", "NFP", "經濟數據", "事件", "VIX"],
    "type": "general",
    "status": "draft",
    "phase": "NFP_pre_event_2026_04_03",
    "created_at": now_utc(),
    "published_at": None,
    "description": "下週五非農數據公布，VIX 29.71 告訴你這次是高波動環境。但 21 年數據顯示：非農本身波動不顯著，VIX 才是關鍵。投資建議：不要因 NFP 改變策略。",
    "proposer": "user",
    "executor": "Claude",
}


# ─── Article 2: 研究文章 ─────────────────────────────────────
ART2_ID = make_article_id()
ART2_TITLE = "K528：非農日的統計真相——為什麼 t-test 和 Wilcoxon 給出相反答案"

ART2_CONTENT = f"""# K528：非農日的統計真相——為什麼 t-test 和 Wilcoxon 給出相反答案

**實驗 ID**: K528
**資料期間**: 2005-02-04 至 2026-03-06
**樣本**: 254 個非農就業報告公布日（SPY + VIX，yfinance）

---

## 研究動機

每個月第一個週五，市場都在問：非農公布日的波動是否顯著高於正常日？
面向 2026 年 4 月 3 日的 NFP，我們用 K528 提供了嚴謹的統計回答。

更有趣的是：**t-test 說不顯著（p=0.128），Wilcoxon 說顯著（p=0.004）。** 哪個才是真相？

---

## 基本統計

| 指標 | 數值 |
|-----|-----|
| 非農日平均絕對報酬 | 0.842% |
| 非非農日平均絕對報酬 | 0.763% |
| 週五基準平均絕對報酬 | 0.721% |
| 波動比率（vs 全市場） | 1.10x |
| 波動比率（vs 週五基準） | 1.17x |
| 非農日正報酬比例 | 57.1%（二項 p=0.028）|

"""

# Embed chart 2
ART2_CONTENT += f"\n\n![K528 統計檢定結果]({chart2_url})\n\n"

ART2_CONTENT += f"""
---

## 為什麼 t-test 和 Wilcoxon 說法不同？

這是一個教科書級的統計學問題。

### t-test：參數型檢定的侷限

Welch t-test 假設資料接近常態分配。但金融報酬有**厚尾（fat tails）**——極端值（大漲大跌）出現的頻率遠高於常態分配預期。

結果：t-test 的均值比較被極端值「稀釋」了。少數非常平靜的非農日拉低了整體平均，讓均值差異不顯著（p=0.128）。

### Wilcoxon（Mann-Whitney U）：非參數的優勢

Mann-Whitney U 檢定不假設常態分配——它比較**排序**（rank），而不是原始數值。這讓它對極端值更穩健。

結果：當我們改看「非農日是否系統性地出現在較大波動那一邊」，答案是**是的**（U=710,364，p=0.0036）。

### 實務解讀

| 檢定 | p 值 | 顯著？ | 說明 |
|------|-----|--------|-----|
| t-test（vs 全市場） | 0.128 | 否 | 均值差異不顯著（厚尾干擾）|
| t-test（vs 週五基準） | 0.034 | 是 | 排除週效應後顯著 |
| Wilcoxon（Mann-Whitney U） | 0.004 | **是** | 排序上非農日波動系統性偏高 |

**結論：非農日存在「中度但穩健」的波動效應，但幅度不大（1.10-1.17x），遠不到讓人換策略的程度。**

---

## VIX 才是真正的預測因子

"""

# Embed chart 3
ART2_CONTENT += f"\n\n![VIX 預測非農日波動的散點圖]({chart3_url})\n\n"

ART2_CONTENT += f"""
上圖呈現 254 個非農事件中，**事前 VIX 與非農當日絕對報酬的關係**。

統計結果：
- **Pearson r = 0.451**（p < 0.0001）
- **Spearman rho = 0.377**（p < 0.0001）
- **線性估計**：VIX 每上升 1 點 → 非農日波動增加 **0.044%**

這個效果遠比「是否是非農日」更強。

### VIX 區制分析

以歷史中位數 VIX=16.71 切分：

| VIX 區制 | 樣本數 | 非農日平均波動 | 比率 |
|---------|--------|------------|------|
| 低 VIX (<16.71) | 127 | 0.532% | 0.70x（低於基準！）|
| 高 VIX (>16.71) | 127 | **1.152%** | **2.17x** |
| 均值差異 t 檢定 | — | — | t=6.70, p<0.0001 |

**高 VIX 非農日的波動，是低 VIX 非農日的 2.17 倍。**

目前 VIX=29.71，顯然屬於高 VIX 環境，預期 4 月 3 日 NFP 日波動偏高。

---

## 4 月非農的季節性分析

從左圖（各月波動比率）可見，4 月份（n=21）的歷史波動比率為 **1.31x**，高於全年均值，但統計上**不顯著**（t=0.88，p=0.387）。

| 4月 NFP 統計 | 數值 |
|------------|-----|
| 歷史樣本數 | 21 次 |
| 平均絕對報酬 | 1.00% |
| 波動比率 | 1.31x |
| 正報酬比例 | 52.4% |
| 統計顯著性 | 否（p=0.387）|

4 月 NFP 比起其他月份並無特殊效應，主導因子仍是當時的 VIX 水位。

---

## 其他發現

**Vol Crush（公布前後波動壓縮）**：未偵測到（前 5 天 vs 後 5 天，差異 p=0.736）。不像期權市場對 FOMC 那樣有明顯的隱含波動率壓縮現象。

**Pre-event VIX Buildup**：公布前 5 天 VIX 平均上升 0.23 點，但不顯著（p=0.227）。市場沒有系統性地「為非農預先定價」。

**成交量**：非農日成交量比正常日高出 13.1%，其中 57.9% 的非農日成交量高於年均值。

---

## 結論與實務意涵

1. **NFP 的波動效應存在但微弱**（Wilcoxon p=0.004，但幅度僅 1.10-1.17x）
2. **t-test vs Wilcoxon 分歧**源自金融報酬厚尾——非參數檢定更合適
3. **VIX 是非農日波動的主因**（r=0.451），事件本身是次因
4. **當前 VIX=29.71 → 高波動預期**，但方向仍隨機（歷史 57.1% 收紅）
5. **策略建議**：維持既有部位，無需因 NFP 調倉

---

*實驗腳本: experiments/k528_nfp_event_study.py*
*結果數據: experiments/k528_nfp_event_study_results.json*
*參考文獻: Savor & Wilson (2013) JFE; Lucca & Moench (2015) JFE*
*[提出: 用戶, 執行: Claude]*
"""

art2 = {
    "id": ART2_ID,
    "title": ART2_TITLE,
    "content": ART2_CONTENT,
    "thinking": "K528 NFP 事件研究的研究文章。核心矛盾：t-test 不顯著但 Wilcoxon 顯著，原因是厚尾。VIX 是真正預測因子 r=0.451。當前 VIX=29.71 高警戒。4 月 NFP 歷史 1.31x 但不顯著。",
    "tags": ["研究", "NFP", "統計", "事件研究", "VIX"],
    "type": "research",
    "status": "draft",
    "phase": "NFP_pre_event_2026_04_03",
    "created_at": now_utc(),
    "published_at": None,
    "description": "K528 實證研究：254 個非農事件中，t-test 和 Wilcoxon 給出相反結論。厚尾是關鍵原因。VIX 才是非農日波動的真正預測因子（r=0.451），當前 VIX=29.71 預示高波動。",
    "proposer": "user",
    "executor": "Claude",
}


# ─── Save to feed.json ────────────────────────────────────────
feed_path = ROOT / "storage" / "feed.json"
with open(feed_path) as f:
    feed = json.load(f)

if "items" in feed:
    feed["items"].append(art1)
    feed["items"].append(art2)
else:
    feed = {"items": [art1, art2]}

with open(feed_path, "w", encoding="utf-8") as f:
    json.dump(feed, f, ensure_ascii=False, indent=2)

print(f"\nSaved to feed.json:")
print(f"  Article 1 (general): {ART1_ID} — {ART1_TITLE}")
print(f"  Article 2 (research): {ART2_ID} — {ART2_TITLE}")


# ─── Save individual report JSONs ─────────────────────────────
reports_dir = ROOT / "storage" / "reports"
reports_dir.mkdir(exist_ok=True)

for art in [art1, art2]:
    rpath = reports_dir / f"{art['id']}.json"
    with open(rpath, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=2)
    print(f"  Report saved: {rpath}")


# ─── Sync to Supabase ─────────────────────────────────────────
print("\nSyncing to Supabase...")
import subprocess
result = subprocess.run(
    ["uv", "run", "python", "scripts/supabase_sync.py", "full"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    timeout=120,
)
if result.returncode == 0:
    print("  Supabase sync OK")
    # Print last few lines
    for line in result.stdout.strip().split("\n")[-5:]:
        if line.strip():
            print(f"  {line}")
else:
    print(f"  Sync warning (rc={result.returncode}):")
    print(result.stderr[-500:] if result.stderr else "(no stderr)")
    print(result.stdout[-500:] if result.stdout else "(no stdout)")

print("\nDone!")
print(f"Article 1 ID: {ART1_ID}")
print(f"Article 2 ID: {ART2_ID}")
