"""
K812/K812v2: Close-to-Close vs Open-to-Close — 方法論警告文章
跨市場策略研究的隱形陷阱：一個報酬計算的選擇，Sharpe 差了 3.68！
"""
import sys
import os
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from volpred.charts import generate_bar_chart, generate_grouped_bar_chart, upload_chart, embed_chart
from volpred.charts.article_charts import _setup_style, _save
from src.volpred.publisher.publisher import Publisher

# ─── 1. 圖表 1: C2C vs OtC Sharpe 對比（grouped bar chart）────
labels = ["BH 0050.TW\n（被動持有）", "Smooth tanh(SPY)\n（主動策略）", "8.63/VIX TW VT\n（波動率目標）"]
group_data = {
    "Close-to-Close（C2C）": [0.908, 3.514, 1.308],
    "Open-to-Close（OtC，正確）": [0.071, -0.168, 0.239],
}

chart_path1 = generate_grouped_bar_chart(
    labels=labels,
    group_data=group_data,
    title="K812 vs K812v2：C2C 與 OtC 報酬計算的 Sharpe 差異",
    ylabel="Sharpe Ratio",
    filename="k812v2_c2c_vs_otc_sharpe",
    figsize=(11, 6),
)
chart_url1 = upload_chart(chart_path1)
print(f"Chart 1 uploaded: {chart_url1}")

# ─── 2. 圖表 2: 方向準確度對比（bar chart）───────────────────
from pathlib import Path

def generate_direction_accuracy_chart():
    _setup_style()
    fig, ax = plt.subplots(figsize=(9, 5))

    categories = ["SPY 上漲→台股上漲", "SPY 下跌→台股下跌", "整體方向準確度"]
    c2c = [63.41, 64.59, 63.93]
    otc = [48.79, 51.87, 50.16]

    x = np.arange(len(categories))
    width = 0.35
    bars1 = ax.bar(x - width/2, c2c, width, label="C2C（錯誤方法）", color="#F44336", alpha=0.85, edgecolor="white")
    bars2 = ax.bar(x + width/2, otc, width, label="OtC（正確方法）", color="#2196F3", alpha=0.85, edgecolor="white")

    # 50% 參考線（隨機猜測）
    ax.axhline(50, color="black", linestyle="--", linewidth=1.5, label="50%（硬幣翻轉基準）")

    # 數值標籤
    for bar, val in zip(bars1, c2c):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f"{val:.1f}%", ha="center", va="bottom", fontsize=9, color="#B71C1C", fontweight="bold")
    for bar, val in zip(bars2, otc):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f"{val:.1f}%", ha="center", va="bottom", fontsize=9, color="#0D47A1")

    ax.set_ylabel("方向準確度（%）")
    ax.set_ylim(40, 75)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=10)
    ax.legend(fontsize=10)
    ax.set_title("US→台股 lead-lag 方向準確度：C2C 看似強力，OtC 僅剩硬幣翻轉",
                 fontsize=12, fontweight="bold", pad=12)
    fig.tight_layout()
    return _save(fig, "k812v2_direction_accuracy")

chart_path2 = generate_direction_accuracy_chart()
chart_url2 = upload_chart(chart_path2)
print(f"Chart 2 uploaded: {chart_url2}")

# ─── 3. 文章內容 ──────────────────────────────────────────────
content = """\
[提出: 用戶, 執行: Claude]

## 摘要

K812 用「昨收→今收」報酬計算跨市場策略，得出 Sharpe 3.514，Codex 審查發現三個 HIGH 嚴重度 bug。K812v2 修正為「開盤→收盤」報酬後，Sharpe 跌至 -0.168，膨脹高達 **+3.68**。方向準確度從看似顯著的 63.9% 跌回 50.2%（硬幣翻轉）。教訓：跨時區策略研究**必須使用 open-to-close return**，否則捕捉到的是不可交易的隔夜 gap。

---

## 第一幕：一個「看起來很完美」的突破

2026 年 4 月，我們設計了 K812 實驗，測試一個核心問題：**美股（SPY）的隔日走勢，能否預測台灣 0050.TW 當日方向？**

這個假說有實證基礎。我們的研究記錄（T32/T33）早已確認 SPY→台股的 lead-lag 相關係數約 0.40，統計顯著（Harvey t=3.75，遠超 t>3.0 門檻）。問題是，這個信號能否轉化為可執行的交易策略？

K812 的結果令人震驚：

| 策略 | Sharpe（全樣本） | Sharpe（OOS 2023-24） | MDD |
|------|:---:|:---:|:---:|
| BH 0050.TW（被動持有） | 0.908 | 1.743 | -33.8% |
| Smooth tanh(SPY) 策略 | **3.400** | **5.053** | -9.8% |
| SPY Return Signal（二元） | 2.177 | 3.541 | -19.8% |

OOS Sharpe 5.05。Cross-OOS 5 個時期全部勝出。DM test Harvey PASS。方向準確度 64.1%。

這是我們見過最「完美」的結果——每一個指標都指向同一個結論：突破性發現。

然後，Codex 審查了代碼。

---

## 第二幕：三個 HIGH 嚴重度 Bug

Codex 在代碼審查中識別出三個 HIGH 嚴重度問題，而不是結果審查——是在代碼結構層面：

### Bug 1：日曆對齊錯誤

原始代碼用 `ffill` + `shift(1)` 處理兩個市場的混合日曆（美股與台股的非交易日不同）。這種做法在邊界條件下會錯誤對齊日期，讓信號和報酬之間的時序關係出現偏移。

**修正**：改用顯式的 merge-on-date + 獨立 shift，在各自的交易日曆上處理後合併。

### Bug 2：Sanity Check 硬編碼

K812 的「隨機基準 Sharpe 0.777」和「Lookahead 驗證」是硬編碼在代碼裡的數值，不是即時計算的。這意味著這些「驗證」其實沒有驗證任何東西——它們只是顯示了預設的數字。

**修正**：K812v2 的所有 sanity check 都是實時計算（`computed_not_hardcoded: true`）。

### Bug 3：報酬計算方式（最關鍵）

**K812 用 close-to-close return（收→收），K812v2 改為 open-to-close return（開→收）。**

這是三個 bug 裡影響最大的一個，以下詳細說明。

---

## 第三幕：C2C 與 OtC 的根本差異

跨時區策略的時序如下：

```
美東時間 15:00  台北時間 04:00（隔天）
美股收盤 ──────────────────────────────►
                                        台股開盤 09:00（隔天）
                                        台股收盤 13:30
```

**C2C（昨收→今收）包含兩段時間**：
1. **隔夜 gap**：台股昨天 13:30 收盤 → 今天 09:00 開盤（約 20 小時）
2. **盤中走勢**：今天 09:00 開盤 → 13:30 收盤

問題在於：**美股信號幾乎 100% 反映在隔夜 gap 中**，而不是在盤中走勢。

為什麼？因為台灣投資人在美股收盤後就知道 SPY 漲跌了。他們隔天開盤前就會下單，開盤價已經「消化」了這個信號。等你用這個信號交易時（09:00 開盤進場），信息早就沒有了。

用 C2C 計算，你「捕捉」到了隔夜 gap 的報酬——但那是你**進場前**已經發生的價格變動，你根本無法賺到。

| 指標 | C2C（含隔夜 gap） | OtC（僅盤中，可交易） |
|------|:---:|:---:|
| **年化平均報酬** | 18.1% | 5.1% |
| **滾動相關係數（SPY→台股）** | 0.410 | **0.009** |
| **Smooth tanh(SPY) Sharpe** | **3.514** | **-0.168** |
| **方向準確度** | 63.9% | **50.2%（硬幣）** |
| **Granger β（SPY→台股 OtC）** | 0.432（t=28.4） | **-0.004（t=-0.25）** |

Sharpe 膨脹：**+3.68**。方向準確度：63.9% → 50.2%。

用 OtC return 後，SPY 對台股盤中走勢的 beta 是 -0.004，t 值 -0.25——完全不顯著。Lead-lag 信號在開盤時就已被市場定價完畢。

---

## 數據對比圖

"""

content = embed_chart(content, chart_url1, "C2C 與 OtC 的 Sharpe 差距：被動投資 BH 0050.TW 相差 0.84，主動策略相差 3.68")
content += """

方向準確度的差距更能說明問題：

"""
content = embed_chart(content, chart_url2, "方向準確度：C2C 顯示 63.9%（看似有信號），OtC 僅剩 50.2%（等同隨機猜測）")

content += """

---

## Codex 審查的救贖

這次案例是 **Codex 審查防止假突破**的典型例子：

- K812 結果出來時，所有表面指標（Sharpe 3.5、OOS Sharpe 5.0、Cross-OOS 5/5 win）都指向「突破」
- **如果沒有 Codex 審查**，這個結果可能直接被記錄進知識庫、寫成文章、甚至用來設計新策略
- **Codex 在代碼層面發現** bug，不是在「結果看起來太好」才懷疑

這個流程的設計初衷正是如此：**寫代碼 → Codex 審代碼 → 修正 → 才跑**，不是跑完出結果才審查。

K812 是迄今為止我們遇到的**最大幅度假突破**（Sharpe 膨脹 +3.68），也是 Codex 審查流程正確性的最強證據。

---

## 方法論建議：跨時區策略研究 Checklist

基於 K812/K812v2 的教訓，跨時區策略研究應遵循以下規則：

**✅ 必須做**
- [ ] **使用 open-to-close return** 作為策略回測的 target
- [ ] 確認信號日期與報酬日期的對齊：信號 t-1，報酬從 t 的開盤計到 t 的收盤
- [ ] Sanity check 必須**即時計算**，不可硬編碼
- [ ] 對混合交易日曆做顯式 merge，不用 ffill 遮蓋 missing data
- [ ] 報告 C2C 和 OtC 兩種計算的結果，讓讀者看到差距

**❌ 禁止做**
- [ ] 用 C2C return 設計跨時區策略（除非明確研究隔夜 gap 本身）
- [ ] 把隔夜 gap 報酬當作「可交易利潤」
- [ ] 在代碼裡硬編碼驗證數字
- [ ] Sharpe > 2x baseline 時直接記錄結論（先審代碼）

**先例記錄**
- K502（2024）：lead-lag alpha 77-93% 在隔夜 gap，確認不可交易（TX 58.5bp）
- K812v2（2026-04-01）：C2C vs OtC Sharpe 差距 +3.68，方向準確度從 63.9% → 50.2%
- I8：SPY Momentum on OtC → FAIL（與 K812v2 結論一致）

---

## Null Result 報告

K812v2 的最終結論：**NULL**。

在正確的 open-to-close return 框架下，US→Taiwan lead-lag 策略**無法**在 Harvey t>3.0 門檻下打敗被動持有。最佳策略（Smooth tanh(SPY)）全樣本 Sharpe -0.168，OOS Sharpe 1.563，Cross-OOS 5 個時期只贏 2 個。

這與 K502 的結論完全一致：lead-lag 信號是真實的，但 alpha 在不可交易的隔夜 gap 裡，開盤後信號已被定價消除。

一個 Null Result，加上一個清晰的方法論教訓，價值遠高於一個建立在錯誤計算上的「突破性發現」。

---

*實驗腳本: experiments/k812_us_taiwan_leadlag.py / experiments/k812v2_us_taiwan_leadlag_otc.py*
*結果數據: experiments/k812_us_taiwan_leadlag_results.json / experiments/k812v2_us_taiwan_leadlag_otc_results.json*
*數據來源：yfinance，0050.TW + SPY + VIX，2006-2026*
"""

# ─── 4. 發佈為 draft ──────────────────────────────────────────
pub = Publisher(storage_dir='/Users/yhlai0911/Desktop/volpred-research/storage')
pub_id = pub.publish_milestone(
    title="Sharpe 3.5 到 -0.17：一個報酬計算選擇讓跨市場策略崩潰",
    description=content,
    phase="K812v2",
    tags=[
        "研究",
        "方法論",
        "跨市場",
        "return calculation",
        "lead-lag",
        "台股",
        "0050.TW",
        "open-to-close",
        "Codex審查",
    ],
    status="draft",
    audience="research",
    category="research",
)

print(f"Published (draft): {pub_id}")
