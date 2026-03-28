"""
Write two general-reader articles based on K604, K597, K598 findings.
Article 1: Implementation costs (K604)
Article 2: Stress test + debounce (K597 + K598)
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from volpred.charts import generate_bar_chart, generate_grouped_bar_chart, upload_chart, embed_chart

BASE = Path(__file__).parent.parent

# ──────────────────────────────────────────────
# ARTICLE 1: COSTS (K604)
# ──────────────────────────────────────────────

def make_article1():
    print("=== Article 1: Implementation Costs (K604) ===")

    # Data from K604 results
    strategies = [
        "Adaptive Tier",
        "Taiwan Hybrid\nLeverage",
        "VIX 條件\n槓桿",
        "Piecewise\nConservative",
        "Risk Parity\n(GARCH)",
        "Taiwan VT\n(0050)",
        "VIX+Leading\n(台股)",
        "50/50\nSPY/GLD",
        "Fear DCA",
        "GARCH VT\n(SPY)",
        "12/VIX\n(SPY)",
    ]
    net_sharpes = [2.095, 1.903, 1.792, 1.776, 1.431, 1.239, 1.199, 1.007, 0.707, 0.449, 0.424]
    complexity = [2, 4, 3, 1, 5, 2, 3, 2, 1, 4, 1]

    # Generate chart: net Sharpe after costs
    chart_path = generate_bar_chart(
        labels=strategies,
        values=net_sharpes,
        title="各策略扣除成本後淨 Sharpe 比率（K604 實驗）",
        ylabel="淨 Sharpe（對無風險利率 4.5%）",
        xlabel="策略",
        filename="k604_net_sharpe_all_strategies",
        figsize=(14, 7),
        highlight_best=True,
        horizontal=True,
    )
    chart_url = upload_chart(chart_path)
    print(f"  Chart 1 uploaded: {chart_url}")

    content = """## 你的策略，扣掉現實的帳單後，還剩多少？

很多人在研究投資策略時，看的都是「回測報酬」或「理論 Sharpe」——但這些數字都是稅前、手續費前、借貸成本前的理想世界。

K604 實驗做了一件很現實的事：**把每個策略的真實執行成本一條一條列清楚，然後看看扣掉之後，你還剩下多少 Sharpe**。

結果讓人大開眼界。

---

## 成本的真實面目：三大殺手

### 第一殺手：美股資本利得稅（2.3–6.7%/年）

美國短期資本利得稅率高達 22%，長期也要 15%。對於每天都在調倉的策略而言，大部分獲利都是「短期」——這意味著每年會有 2.3% 到 6.7% 的報酬直接繳給國稅局。

| 策略 | 年稅負拖累 |
|------|-----------|
| GARCH VT (SPY) | 2.41% |
| 12/VIX (SPY) | 2.31% |
| 50/50 SPY/GLD | 3.57% |
| Piecewise Conservative | 3.84% |
| VIX 條件槓桿 | 6.28% |
| Adaptive Tier | 6.72% |

Adaptive Tier 每年光是稅就繳掉 6.72%。這是主要成本——不是手續費。

### 第二殺手：台股佣金（美股的 13 倍）

台股 0050.TW 的狀況截然不同：美股已全面零手續費（Interactive Brokers/Schwab），但台灣券商每筆交易仍要約新台幣 20 元（約 0.6 美元）。聽起來不多，但如果你每年交易 200 次……

- 以 10 萬美元（約 320 萬台幣）操作台灣 VT 策略：佣金就佔 **4.9%/年**
- 同樣規模的美股策略：佣金 **0%**

台股策略要讓佣金降到可接受範圍（<2%），**最低資金門檻約 97 萬美元（約 3,100 萬台幣）**。這不是一般投資人能輕易達到的數字。

### 第三殺手：台股證交稅（0.3%/每筆賣出）

台股每賣一次都要繳 0.3% 證交稅。高換手率的策略（如台灣 Hybrid Leverage，年賣出達 538%）每年多繳 **1.6%**。反而低換手的 VIX+Leading 策略（年換手 65%）稅負只有 **0.2%**——換手率直接決定稅負。

---

## 實際數字：扣掉成本後你還剩多少？

"""

    content = embed_chart(content, chart_url, "各策略扣除現實成本（稅、手續費、借貸）後的淨 Sharpe 比率。數據來源：K604 實驗，基於 paper_trading.json 實際權重歷史。")

    content += """

**重點發現**：
- **Adaptive Tier**：扣完稅（6.72%）和借貸成本（0.58%）後，淨 Sharpe 仍有 **2.095**——仍是最高
- **Piecewise Conservative**：毛 Sharpe 3.16，扣成本後 **1.776**，但複雜度只有 1/5（最簡單的策略）
- **GARCH VT / 12/VIX**：扣稅後淨 Sharpe 只剩 0.449 和 0.424——**比買入持有還差**

---

## 最低資金門檻：你需要多少錢才能執行？

| 策略 | 最低資金 | 主要限制 |
|------|---------|---------|
| 美股系列（SPY/GLD） | **$5,000** | 融資保證金 |
| VIX 條件槓桿（需融資） | $25,000 | 融資帳戶門檻 |
| 台灣 VT（0050.TW） | **$977,000**（約 3,100 萬台幣）| 佣金吃掉獲利 |
| 台灣 Hybrid Leverage | **$823,000**（約 2,600 萬台幣）| 佣金吃掉獲利 |
| VIX+Leading（台股月頻）| $100,000 | 佣金可接受 |

美股策略最低只要 5,000 美元就能執行。台股日頻策略因為佣金太高，**沒有 800 萬以上的資金根本划不來**。

---

## 最值得的選擇：性價比冠軍

綜合考量「扣成本後 Sharpe」和「操作複雜度」，**Piecewise Conservative（分段保守）**表現最突出：

- 複雜度：**1/5**（最簡單——只需看 VIX 在哪個區間）
- 淨 Sharpe：**1.776**（扣掉稅後仍高）
- 最低資金：**$5,000**
- 操作方式：每天查一次 VIX，三個區間決定倉位，不需要任何程式

具體規則：
- VIX < 15：全倉 50/50 SPY/GLD
- 15 ≤ VIX < 20：按比例減倉（VIX 越高越減）
- VIX ≥ 20：空倉，全部轉現金/債券

這是「最聰明的懶人策略」——規則簡單，成本最低，但風險控制效果卻相當好。

---

## 為什麼台股策略成本是美股的 13 倍？

美股之所以成本如此低，原因只有一個：**零手續費革命**。2019 年 Schwab 帶頭砍零手續費，現在幾乎所有美國主流券商（IB、Schwab、Fidelity）都是零手續費。

台股還沒有這個革命。每筆 $20 新台幣的佣金，乘上每年 200 次交易，對小資金是致命的。

不過，台股有一個美股沒有的優勢：**沒有資本利得稅**。所以對大資金（超過 3,000 萬台幣）的投資人而言，台股策略長期下來成本反而可能更低。

---

## 結語：看穿「理論報酬」的幻覺

投資學術論文裡的 Sharpe 都是稅前的。基金公司的行銷材料忽略手續費。

K604 告訴我們：**平均而言，成本會吃掉你 27% 的 Sharpe**。

在你把下一個「看起來很厲害」的策略放進實際帳戶之前，先把成本算清楚。

---

*本文基於實驗 K604 的實證結果（數據來源：paper_trading.json 實際權重歷史，期間：2023–2026）*

實驗腳本：`experiments/k604_implementation_costs.py`
結果數據：`experiments/k604_implementation_costs_results.json`
"""

    return content


# ──────────────────────────────────────────────
# ARTICLE 2: STRESS TEST + DEBOUNCE (K597+K598)
# ──────────────────────────────────────────────

def make_article2():
    print("=== Article 2: Stress Test + Debounce (K597+K598) ===")

    # Strategy names for chart
    strat_labels = [
        "Buy & Hold",
        "12/VIX",
        "VIX 條件槓桿",
        "Piecewise\nConservative",
        "Fear DCA",
        "Adaptive Tier",
    ]

    # MDD during GFC (B_gfc_2008_2009)
    mdd_gfc = [
        -27.21,  # buy_and_hold
        -17.76,  # simple_12vix
        -7.69,   # vix_cond_leverage
        0.0,     # piecewise_conservative (0% drawdown during GFC period!)
        -41.83,  # fear_dca
        0.0,     # adaptive_tier (0% drawdown during GFC period!)
    ]

    # MDD during COVID (E_covid_v_recovery)
    mdd_covid = [
        -20.32,  # buy_and_hold
        -13.08,  # simple_12vix
        -6.56,   # vix_cond_leverage
        -0.44,   # piecewise_conservative
        -29.64,  # fear_dca
        -0.85,   # adaptive_tier
    ]

    # MDD during Whipsaw 2018Q4 (C_whipsaw_2018q4)
    mdd_whipsaw = [
        -7.50,   # buy_and_hold
        -12.45,  # simple_12vix
        -5.72,   # vix_cond_leverage
        -3.22,   # piecewise_conservative
        -13.15,  # fear_dca
        -4.80,   # adaptive_tier
    ]

    group_data = {
        "GFC 2008-09（最嚴峻）": [abs(v) for v in mdd_gfc],
        "COVID 2020（快速崩跌+反彈）": [abs(v) for v in mdd_covid],
        "震盪 2018Q4（最難防守）": [abs(v) for v in mdd_whipsaw],
    }

    chart_path = generate_grouped_bar_chart(
        labels=strat_labels,
        group_data=group_data,
        title="各策略在三大壓力情境下的最大回撤（K597 實驗）",
        ylabel="最大回撤 %（越低越好）",
        filename="k597_crisis_mdd_comparison",
        figsize=(14, 7),
    )
    chart_url = upload_chart(chart_path)
    print(f"  Chart 2 uploaded: {chart_url}")

    content = """## 你的策略，撐得過股災嗎？——五大情境壓力測試全紀錄

「這個策略回測很漂亮」和「這個策略股災時不會讓我崩潰」是兩回事。

K597 實驗對平台上所有主要策略進行了系統性壓力測試，選取歷史上五個最具代表性的極端情境，逐一驗證：**每個策略在真正的市場考驗面前，究竟表現如何？**

---

## 五大壓力情境

| 情境 | 期間 | 特徵 |
|------|------|------|
| **GFC 金融海嘯** | 2008/09–2009/03 | VIX 飆到 80，SPY 最大跌幅 -55% |
| **Volmageddon** | 2018/01–2018/03 | VIX 瞬間從 11 跳到 37，閃崩 |
| **震盪 2018Q4** | 2018/10–2018/12 | 急漲急跌，最考驗頻繁換手策略 |
| **2022 慢熊** | 2022/01–2022/10 | VIX 持續高位 25-35，緩慢下跌 |
| **COVID 崩跌+反彈** | 2020/02–2020/06 | 5 週崩 34%，13 週完全反彈 |

---

## 最重要的發現：哪些策略在股災時真的有保護作用？

"""

    content = embed_chart(content, chart_url, "各策略在 GFC、COVID、2018Q4 震盪三大情境的最大回撤比較。Piecewise Conservative 和 Adaptive Tier 在 GFC 期間回撤為 0%，因為 VIX>80 時已完全空倉。")

    content += """

**明星表現**：

### Piecewise Conservative：4/5 情境勝過 Buy & Hold
這是整個壓力測試裡的最大驚喜。Piecewise Conservative（分段保守）策略：
- **GFC**：回撤 **0%**（VIX>20 直接清空倉位，完全不參與下跌）
- **COVID 崩跌**：最大回撤只有 **-0.4%**（相比 Buy & Hold 的 -20.3%）
- **2022 慢熊**：回撤 **-0.9%**（相比 Buy & Hold 的 -18%）
- **唯一缺點**：COVID V型反彈時，因為倉位輕，漲幅也有限

### Adaptive Tier：3/5 情境勝出，但有一個意外
Adaptive Tier 在 GFC 同樣回撤 0%（自動空倉），2022 慢熊也表現優異（+2.76% 對比 Buy & Hold 的 -9.13%）。但在 COVID V型反彈中，由於太快出場，反而落後 Buy & Hold。

### 最大警告：Fear DCA 在股災中反而加碼
Fear DCA（恐懼定投）在 GFC 期間損失高達 **-41.83%**——比 Buy & Hold 的 -27.21% **還慘**。原因是它的邏輯是「越跌越買」，在 GFC 級別的長達 6 個月的持續下跌中，持續加碼等於持續加大損失。

---

## 策略壓力測試總評

| 策略 | 幫助 | 傷害 | 判決 |
|------|------|------|------|
| Piecewise Conservative | 4/5 情境 | 1/5 | ✅ 通過 |
| Adaptive Tier | 3/5 情境 | 2/5 | ✅ 通過 |
| VIX 條件槓桿 | 2/5 情境 | 3/5 | ⚠️ 謹慎 |
| Fear DCA | 2/5 情境 | 3/5 | ⚠️ 謹慎 |
| 12/VIX | 1/5 情境 | 4/5 | ❌ 不通過 |

---

## K598 新發現：77% 的「假出場」其實是在保護你

K597 發現 Adaptive Tier 每年切換約 27 次，其中 **77%（111/145 次）的退場持續不到 5 天就回倉**——這看起來很像「假訊號」，會浪費交易成本。

K598 實驗嘗試了 5 種「消除假訊號」的改良版本（延遲確認 3 天、5 天、MA 平滑、滯後帶等）。

結果非常反直覺：

**你以為在修問題，其實在破壞保護機制**

以「延遲 3 天確認才出場」的版本為例：
- 假出場從 77% 降到 23%（看起來很棒）
- 但 Sharpe 從 1.455 **直接掉到 0.906**（下降 38%）
- GFC 保護：從賺 10.4% 降到賺 4.31%

為什麼？因為那些「假出場」雖然很快就回頭，但**出場的時機通常正好是最危險的時刻**。延遲確認讓你在最脆弱的時候還留在市場裡。

真正的數據：這 111 次「假出場」期間，市場平均繼續下跌，如果你繼續持有，**累計多損失 62.8%（年化 2.95%）**。換句話說，這些「假出場」每年幫你省了近 3% 的損失。

**結論：原始 Adaptive Tier 保留不動，不需要修改**。

---

## 三個股災中的最壞單日

看看最壞的那天（2020/03/16，SPY 當天跌 -10.9%）各策略的表現：

| 策略 | 當日損失 |
|------|---------|
| Buy & Hold | **-10.94%** |
| Fear DCA | -9.85% |
| 12/VIX | -2.27% |
| VIX 條件槓桿 | -1.25% |
| **Adaptive Tier** | **0.00%** |
| **Piecewise Conservative** | **0.00%** |

當 VIX 在 2020 年 3 月跳到 82.7，Adaptive Tier 和 Piecewise Conservative 已完全空倉。那天市場崩跌，它們的帳戶紋絲不動。

---

## 給一般投資人的結論

壓力測試告訴我們一個核心事實：**不同策略在不同市場環境下的保護能力天差地別**。

如果你最怕的是股災跌 30-50%：Piecewise Conservative 是你的第一選擇。規則簡單，執行成本低，而且在歷史上四次重大股災中三次完全空倉避險。

如果你願意接受稍微複雜一點的系統（需要融資帳戶）：Adaptive Tier 提供更全面的保護，而且全週期表現最好。

如果你打算用「越跌越買」的邏輯：Fear DCA 需要極強的心理素質，因為在真正的股災中，它反而是風險最大的策略之一。

---

*本文基於實驗 K597（壓力測試）+ K598（Debounce 分析）的實證結果*

*數據來源：yfinance（SPY、GLD、^VIX），期間：2005–2026，共 5,342 個交易日*

實驗腳本：`experiments/k597_stress_test.py`、`experiments/k598_adaptive_debounce.py`
結果數據：`experiments/k597_stress_test_results.json`、`experiments/k598_adaptive_debounce_results.json`
"""

    return content


def publish_article(title, content, tags, phase):
    """Publish article as draft via volpred ops publish-milestone."""
    tags_str = ",".join(tags)
    cmd = [
        "uv", "run", "volpred", "ops", "publish-milestone",
        "--title", title,
        "--description", content,
        "--phase", phase,
        "--tags", tags_str,
        "--status", "draft",
        "--storage-dir", "storage",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr}")
        return None
    print(f"  Published: {result.stdout.strip()}")
    return result.stdout.strip()


if __name__ == "__main__":
    print("Generating articles...")

    # Article 1
    content1 = make_article1()
    publish_article(
        title="執行這些策略到底要花多少錢？——真實成本全公開",
        content=content1,
        tags=["一般讀者", "成本", "實務"],
        phase="K604",
    )

    # Article 2
    content2 = make_article2()
    publish_article(
        title="K598+K597 壓力測試完全報告——你的策略禁得起股災嗎？",
        content=content2,
        tags=["一般讀者", "壓力測試", "策略"],
        phase="K597_K598",
    )

    print("\nDone!")
